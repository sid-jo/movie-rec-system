from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pipeline.data_quality import summarize_issues, validate_kafka_event
from pipeline.paths import default_paths, path_relative_to_root


def _safe_log(x: float) -> float:
    return math.log(x) if x > 0 else 0.0


def _psi(expected: list[float], actual: list[float], eps: float = 1e-9) -> float:
    """
    Population Stability Index for binned distributions.
    """
    s = 0.0
    for e, a in zip(expected, actual):
        e2 = max(eps, e)
        a2 = max(eps, a)
        s += (a2 - e2) * _safe_log(a2 / e2)
    return float(s)


def _js_divergence(p: dict[str, float], q: dict[str, float], eps: float = 1e-12) -> float:
    keys = set(p) | set(q)
    m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in keys}

    def kl(a: dict[str, float], b: dict[str, float]) -> float:
        s = 0.0
        for k in keys:
            ak = a.get(k, 0.0)
            bk = b.get(k, 0.0)
            if ak <= 0:
                continue
            s += ak * math.log(ak / max(eps, bk))
        return s

    return 0.5 * (kl(p, m) + kl(q, m))


def _normalize(counter: Counter) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {str(k): v / total for k, v in counter.items()}


def _hist_numeric(values: list[float], bins: list[float]) -> list[float]:
    # bins: sorted edges, inclusive left, exclusive right except last
    if not bins or len(bins) < 2:
        return []
    counts = [0] * (len(bins) - 1)
    for x in values:
        for i in range(len(bins) - 1):
            lo, hi = bins[i], bins[i + 1]
            if (x >= lo and x < hi) or (i == len(bins) - 2 and x == hi):
                counts[i] += 1
                break
    total = sum(counts)
    return [c / total for c in counts] if total else [0.0 for _ in counts]


def _load_raw_events(raw_logs_dir: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import glob

    events: list[dict[str, Any]] = []
    issues = []
    parse_errors = 0
    files = sorted(glob.glob(os.path.join(raw_logs_dir, "*.jsonl")))
    for fp in files:
        try:
            with open(fp) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        parse_errors += 1
                        continue
                    issues.extend(validate_kafka_event(obj))
                    events.append(obj)
        except Exception:
            parse_errors += 1
    return events, {"files": len(files), "events": len(events), "parse_errors": parse_errors, "issues": issues}


def compute_window_stats(raw_logs_dir: str, metadata_dir: str) -> dict[str, Any]:
    events, meta = _load_raw_events(raw_logs_dir)

    rating_values: list[float] = []
    rec_status = Counter()
    rec_lengths: list[float] = []
    cost_values: list[float] = []

    # Load cost map (optional)
    cost_by_mid: dict[str, float] = {}
    movies_path = os.path.join(metadata_dir, "movies.json")
    if os.path.exists(movies_path):
        with open(movies_path) as f:
            movies = json.load(f)
        for mid, m in movies.items():
            if isinstance(m, dict) and "cost" in m and isinstance(m["cost"], (int, float)):
                cost_by_mid[str(mid)] = float(m["cost"])

    for e in events:
        t = e.get("type")
        if t == "rating" and isinstance(e.get("rating"), (int, float)):
            rating_values.append(float(e["rating"]))
        elif t == "recommendation":
            if isinstance(e.get("status"), int):
                rec_status[str(e["status"])] += 1
            recs = e.get("recommendations")
            if isinstance(recs, str):
                mids = [x for x in recs.split(",") if x]
                rec_lengths.append(float(len(mids)))
                for mid in mids[:20]:
                    if mid in cost_by_mid:
                        cost_values.append(cost_by_mid[mid])

    stats = {
        "window": {
            "raw_logs_dir": os.path.abspath(raw_logs_dir),
            "files": meta["files"],
            "events": meta["events"],
            "parse_errors": meta["parse_errors"],
        },
        "schema_issues": summarize_issues(meta["issues"]),
        "metrics": {
            "ratings": {
                "count": len(rating_values),
                "mean": float(sum(rating_values) / max(1, len(rating_values))),
                "hist": _hist_numeric(rating_values, bins=[0, 1, 2, 3, 4, 5]),
                "bins": [0, 1, 2, 3, 4, 5],
            },
            "recommendations": {
                "count": int(sum(rec_status.values())),
                "status_dist": _normalize(rec_status),
                "len_hist": _hist_numeric(rec_lengths, bins=[0, 1, 5, 10, 15, 20, 21]),
                "len_bins": [0, 1, 5, 10, 15, 20, 21],
            },
            "cost": {
                "count": len(cost_values),
                "mean": float(sum(cost_values) / max(1, len(cost_values))),
                "hist": _hist_numeric(cost_values, bins=[0, 0.5, 1, 2, 5, 10, 1000]),
                "bins": [0, 0.5, 1, 2, 5, 10, 1000],
            },
        },
    }
    return stats


def compare_to_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    b = baseline.get("metrics", {})
    c = current.get("metrics", {})

    rating_psi = _psi(b.get("ratings", {}).get("hist", []), c.get("ratings", {}).get("hist", [])) if b else None
    len_psi = _psi(
        b.get("recommendations", {}).get("len_hist", []),
        c.get("recommendations", {}).get("len_hist", []),
    ) if b else None
    cost_psi = _psi(b.get("cost", {}).get("hist", []), c.get("cost", {}).get("hist", [])) if b else None

    status_js = (
        _js_divergence(
            b.get("recommendations", {}).get("status_dist", {}),
            c.get("recommendations", {}).get("status_dist", {}),
        )
        if b
        else None
    )

    # Heuristic thresholds (tunable)
    flags = {
        "rating_psi_high": (rating_psi is not None and rating_psi >= 0.2),
        "rec_len_psi_high": (len_psi is not None and len_psi >= 0.2),
        "cost_psi_high": (cost_psi is not None and cost_psi >= 0.2),
        "rec_status_js_high": (status_js is not None and status_js >= 0.1),
        "schema_errors_present": current.get("schema_issues", {}).get("error_count", 0) > 0,
    }

    return {
        "drift_scores": {
            "rating_psi": rating_psi,
            "recommendation_length_psi": len_psi,
            "cost_psi": cost_psi,
            "recommendation_status_js": status_js,
        },
        "flags": flags,
    }


def run(raw_logs_dir: str, metadata_dir: str, output_path: str, baseline_path: str | None) -> dict[str, Any]:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    paths = default_paths()
    current = compute_window_stats(raw_logs_dir=raw_logs_dir, metadata_dir=metadata_dir)
    current["window"]["raw_logs_dir"] = path_relative_to_root(raw_logs_dir, paths.root)

    baseline = None
    comparison = None
    if baseline_path and os.path.exists(baseline_path):
        with open(baseline_path) as f:
            baseline = json.load(f)
        comparison = compare_to_baseline(baseline, current)

    report = {
        "report_type": "drift_report",
        "baseline_path": path_relative_to_root(baseline_path, paths.root) if baseline_path else None,
        "current": current,
        "comparison": comparison,
    }
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate schema+drift report from logs")
    p.add_argument("--raw-logs-dir", default=None)
    p.add_argument("--metadata-dir", default=None)
    p.add_argument("--baseline", default=None, help="Optional baseline JSON to compare against")
    p.add_argument("--output", default=None, help="Path to write drift_report.json")
    args = p.parse_args(argv)

    paths = default_paths()
    raw_dir = args.raw_logs_dir or paths.data_raw_logs
    md_dir = args.metadata_dir or paths.metadata_dir
    out = args.output or os.path.join(paths.reports_dir, "drift_report.json")

    print(
        f"[drift] starting: raw_logs_dir={raw_dir}, metadata_dir={md_dir} "
        f"baseline={args.baseline or 'None'} → output={out}"
    )

    rep = run(raw_logs_dir=raw_dir, metadata_dir=md_dir, output_path=out, baseline_path=args.baseline)
    flags = (rep.get("comparison") or {}).get("flags") if rep.get("comparison") else {}
    print(f"[drift] completed: wrote {out} (flags={flags})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

