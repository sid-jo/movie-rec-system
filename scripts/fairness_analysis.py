#!/usr/bin/env python3
"""
Fairness analysis CLI — produces the numbers that back the Fairness Analysis
section of m4_report.md.

Usage (from repo root):

    # full run against the 6.5 GB raw-log corpus
    python scripts/fairness_analysis.py \
        --log-dir data/raw_logs \
        --output experiments/results/m4_fairness.json

    # quick sanity run on the first 20 shards (seconds, not minutes)
    python scripts/fairness_analysis.py --log-dir data/raw_logs --max-files 20

    # when rec-event telemetry is available, compute per-group WTR too
    python scripts/fairness_analysis.py \
        --log-dir data/raw_logs \
        --rec-log-dir experiments/logs

Outputs:
  - JSON results at --output (default experiments/results/m4_fairness.json)
  - PNG bar charts under docs/report_figures/ (if matplotlib is installed)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# allow running as `python scripts/fairness_analysis.py` from repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.analysis import fairness as fa  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="M4 fairness analysis")
    ap.add_argument("--log-dir", default="data/raw_logs",
                    help="Directory of pre-parsed JSONL shards (watches + ratings).")
    ap.add_argument("--rec-log-dir", default=None,
                    help="Optional: directory of recommendation-event JSONL files. "
                         "If set, compute WTR per group on top of engagement metrics.")
    ap.add_argument("--users", default="metadata/users.json")
    ap.add_argument("--movies", default="metadata/movies.json")
    ap.add_argument("--output", default="experiments/results/m4_fairness.json")
    ap.add_argument("--figures-dir", default="docs/report_figures")
    ap.add_argument("--max-files", type=int, default=None,
                    help="Limit number of log shards (useful for a fast sanity check).")
    ap.add_argument("--min-catalog", type=int, default=20,
                    help="Minimum catalog titles for a language to count against the exposure floor.")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    os.makedirs(args.figures_dir, exist_ok=True)

    t0 = time.time()
    print(f"[fairness] loading metadata ...", flush=True)
    users = fa.load_users(args.users)
    movies = fa.load_movies(args.movies)
    print(f"[fairness]   users={len(users)}  movies={len(movies)}", flush=True)

    print(f"[fairness] describing bias sources ...", flush=True)
    catalog_bias = fa.describe_catalog_bias(movies)
    user_bias = fa.describe_user_bias(users)

    print(f"[fairness] aggregating per-user engagement from {args.log_dir} ...", flush=True)
    per_user = fa.aggregate_by_user(args.log_dir, max_files=args.max_files)
    print(f"[fairness]   aggregated {len(per_user)} users   ({time.time()-t0:.1f}s)", flush=True)

    gender_groups = fa.user_group_map(users, "gender")
    age_groups = fa.user_group_map(users, "age")

    print(f"[fairness] computing group engagement ...", flush=True)
    eng_gender = fa.group_engagement(per_user, gender_groups)
    eng_age = fa.group_engagement(per_user, age_groups)

    # Welch's t-test on per-user mean rating, M vs F
    m_ratings = [a.mean_rating for uid, a in per_user.items()
                 if gender_groups.get(uid) == "M" and a.mean_rating is not None]
    f_ratings = [a.mean_rating for uid, a in per_user.items()
                 if gender_groups.get(uid) == "F" and a.mean_rating is not None]
    gender_rating_test = fa.welch_ttest(m_ratings, f_ratings)

    print(f"[fairness] counting plays per movie for exposure parity ...", flush=True)
    play_counts = fa.play_counts_by_movie(args.log_dir, max_files=args.max_files)
    exposure_lang = fa.exposure_parity_by_plays(play_counts, movies, attr="original_language",
                                                min_catalog=args.min_catalog)
    # Budget quartile exposure
    _tag_budget_quartile(movies)
    exposure_budget = fa.exposure_parity_by_plays(play_counts, movies, attr="_budget_q",
                                                  min_catalog=args.min_catalog)

    wtr = None
    if args.rec_log_dir and os.path.isdir(args.rec_log_dir):
        print(f"[fairness] computing per-group WTR from {args.rec_log_dir} ...", flush=True)
        wtr = {
            "by_gender": fa.watch_through_rate_by_group(args.rec_log_dir, args.log_dir,
                                                       gender_groups),
            "by_age":    fa.watch_through_rate_by_group(args.rec_log_dir, args.log_dir,
                                                       age_groups),
        }

    # ---------------------- assemble results -----------------------------
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 1),
        "inputs": {
            "log_dir": args.log_dir,
            "rec_log_dir": args.rec_log_dir,
            "max_files": args.max_files,
            "min_catalog": args.min_catalog,
        },
        "catalog_bias": catalog_bias,
        "user_bias": user_bias,
        "engagement_by_gender": eng_gender,
        "engagement_by_age":    eng_age,
        "gender_rating_welch_t": gender_rating_test,
        "exposure_parity_language": exposure_lang,
        "exposure_parity_budget_quartile": exposure_budget,
        "wtr_by_group": wtr,
        "requirements_summary": _summarise_requirements(eng_gender, eng_age,
                                                        gender_rating_test,
                                                        exposure_lang),
    }

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=_json_default)
    print(f"[fairness] wrote {args.output}", flush=True)

    try:
        _plot_all(result, args.figures_dir)
    except Exception as e:
        print(f"[fairness] plots skipped: {e}", flush=True)

    _print_headline(result)
    return 0


def _summarise_requirements(eng_gender: dict, eng_age: dict,
                            gender_rating_test: dict | None,
                            exposure_lang: dict) -> dict:
    # R1: gender mean-rating gap <= 10%, age max/min ratio >= 0.8
    g = eng_gender
    m = (g.get("M") or {}).get("mean_rating_per_user")
    f = (g.get("F") or {}).get("mean_rating_per_user")
    r1_gender_ratio = (min(m, f) / max(m, f)) if (m and f) else None
    r1_gender_gap_pct = (abs(m - f) / ((m + f) / 2) * 100) if (m and f) else None

    age_ratings = [(k, v.get("mean_rating_per_user"))
                   for k, v in eng_age.items() if v.get("mean_rating_per_user")]
    if age_ratings:
        vals = [v for _, v in age_ratings]
        r1_age_ratio = min(vals) / max(vals)
    else:
        r1_age_ratio = None

    r1_met = (
        (r1_gender_gap_pct is not None and r1_gender_gap_pct <= 10.0)
        and (r1_age_ratio is not None and r1_age_ratio >= 0.8)
    )

    # R2: exposure floor 0.5 across languages with >= min_catalog titles
    r2_min_ratio = exposure_lang.get("eligible_min_ratio")
    r2_met = (r2_min_ratio is not None and r2_min_ratio >= 0.5)

    return {
        "R1_gender_gap_pct": r1_gender_gap_pct,
        "R1_gender_ratio": r1_gender_ratio,
        "R1_gender_welch_p": (gender_rating_test or {}).get("p_value"),
        "R1_age_min_max_ratio": r1_age_ratio,
        "R1_met": bool(r1_met),
        "R2_min_language_ratio": r2_min_ratio,
        "R2_met": bool(r2_met),
    }


def _tag_budget_quartile(movies: dict) -> None:
    """Add a '_budget_q' field to each movie dict (in-place) to use with exposure_parity."""
    budgets = sorted(
        (m.get("budget", 0) or 0) for m in movies.values()
        if isinstance(m, dict) and (m.get("budget", 0) or 0) > 0
    )
    if not budgets:
        return
    n = len(budgets)
    q1 = budgets[n // 4]
    q2 = budgets[n // 2]
    q3 = budgets[(3 * n) // 4]
    for m in movies.values():
        if not isinstance(m, dict):
            continue
        b = m.get("budget", 0) or 0
        if b <= 0:
            m["_budget_q"] = "zero"
        elif b <= q1:
            m["_budget_q"] = "q1_lowest"
        elif b <= q2:
            m["_budget_q"] = "q2"
        elif b <= q3:
            m["_budget_q"] = "q3"
        else:
            m["_budget_q"] = "q4_highest"


def _print_headline(result: dict) -> None:
    r = result["requirements_summary"]
    print("\n" + "=" * 60)
    print("FAIRNESS HEADLINE")
    print("=" * 60)
    print(f"  R1 gender mean-rating gap:   {r['R1_gender_gap_pct']!r}%")
    if r["R1_gender_welch_p"] is not None:
        print(f"       Welch t-test p-value:   {r['R1_gender_welch_p']:.4g}")
    print(f"  R1 age bucket min/max ratio: {r['R1_age_min_max_ratio']!r}")
    print(f"  R1 met? {r['R1_met']}")
    print(f"  R2 min language play/catalog ratio: {r['R2_min_language_ratio']!r}")
    print(f"  R2 met? {r['R2_met']}")
    exp = result["exposure_parity_language"]
    if exp and exp.get("eligible_languages"):
        print("  Worst languages by ratio:")
        for lang, ratio in exp["eligible_languages"][:5]:
            print(f"    {lang:>5}  ratio={ratio:.3f}")
    print()


def _plot_all(result: dict, out_dir: str) -> None:
    import matplotlib  # noqa: F401  (imported for side effects)
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def bar(groups_dict, key, title, fname, ylim=None):
        labels = [k for k in groups_dict if groups_dict[k].get(key) is not None]
        values = [groups_dict[k][key] for k in labels]
        if not labels:
            return
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.bar(labels, values)
        ax.set_title(title)
        ax.set_ylabel(key)
        if ylim:
            ax.set_ylim(*ylim)
        fig.tight_layout()
        p = os.path.join(out_dir, fname)
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"[fairness]   wrote {p}")

    bar(result["engagement_by_gender"], "mean_rating_per_user",
        "Mean rating per user, by gender (1-10 scale)",
        "m4_fairness_mean_rating_gender.png",
        ylim=(0, 10))
    bar(result["engagement_by_gender"], "mean_watch_per_user",
        "Mean watches per user, by gender",
        "m4_fairness_watches_gender.png")
    bar(result["engagement_by_age"], "mean_rating_per_user",
        "Mean rating per user, by age bucket",
        "m4_fairness_mean_rating_age.png",
        ylim=(0, 10))

    # exposure plot
    exp = result.get("exposure_parity_language", {})
    per_val = exp.get("per_value", {}) if exp else {}
    top = sorted(per_val.items(), key=lambda kv: kv[1]["catalog_share"], reverse=True)[:10]
    if top:
        labels = [k for k, _ in top]
        cs = [v["catalog_share"] for _, v in top]
        ps = [v["play_share"] for _, v in top]
        x = range(len(labels))
        fig, ax = plt.subplots(figsize=(7, 3.5))
        width = 0.4
        ax.bar([i - width / 2 for i in x], cs, width, label="catalog share")
        ax.bar([i + width / 2 for i in x], ps, width, label="play share")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=0)
        ax.set_title("Language exposure: catalog share vs play share (top 10)")
        ax.legend()
        fig.tight_layout()
        p = os.path.join(out_dir, "m4_fairness_exposure_language.png")
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"[fairness]   wrote {p}")


def _json_default(obj):
    # UserAgg dataclass serialisation
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


if __name__ == "__main__":
    raise SystemExit(main())
