#!/usr/bin/env python3
"""
Milestone 4 feedback-loop analysis.

Goal:
  Detect "rich-get-richer" dynamics where a small set of frequently recommended
  titles accumulates disproportionate watch activity, reinforcing future
  popularity-based recommendations.

Inputs:
  - experiments/logs/*.jsonl  (recommendation events with 20-title lists)
  - data/processed/watches.csv (historical watch telemetry)

Output:
  - experiments/results/m4_feedback_loop.json
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone


def rankdata(values: list[float]) -> list[float]:
    """Average-rank ties; 1-indexed ranks."""
    pairs = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][1] == pairs[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[pairs[k][0]] = avg_rank
        i = j
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = math.sqrt(sum((a - mx) ** 2 for a in x))
    deny = math.sqrt(sum((b - my) ** 2 for b in y))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def spearman(x: list[float], y: list[float]) -> float | None:
    return pearson(rankdata(x), rankdata(y))


def load_recommendation_counts(rec_log_dir: str) -> tuple[Counter, int, int]:
    rec_counts: Counter = Counter()
    rec_events = 0
    total_slots = 0

    for path in sorted(glob.glob(os.path.join(rec_log_dir, "*.jsonl"))):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                recs = obj.get("recommendations")
                if not isinstance(recs, list) or not recs:
                    continue
                rec_events += 1
                total_slots += len(recs)
                for mid in recs:
                    rec_counts[str(mid)] += 1
    return rec_counts, rec_events, total_slots


def load_watch_counts(watches_csv: str) -> tuple[Counter, Counter]:
    watch_events: Counter = Counter()
    watch_minutes: Counter = Counter()
    with open(watches_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mid = str(row.get("movie_id", ""))
            if not mid:
                continue
            watch_events[mid] += 1
            try:
                watch_minutes[mid] += int(float(row.get("minutes_watched", 0) or 0))
            except ValueError:
                pass
    return watch_events, watch_minutes


def main() -> int:
    ap = argparse.ArgumentParser(description="M4 feedback-loop analysis")
    ap.add_argument("--rec-log-dir", default="experiments/logs")
    ap.add_argument("--watches-csv", default="data/processed/watches.csv")
    ap.add_argument("--output", default="experiments/results/m4_feedback_loop.json")
    args = ap.parse_args()

    rec_counts, rec_events, total_slots = load_recommendation_counts(args.rec_log_dir)
    watch_events, watch_minutes = load_watch_counts(args.watches_csv)

    if not rec_counts:
        raise SystemExit("No recommendation events found in rec-log-dir.")

    total_recs = sum(rec_counts.values())
    unique_movies = len(rec_counts)
    sorted_movies = rec_counts.most_common()

    top10_share = sum(c for _, c in sorted_movies[:10]) / total_recs
    top1pct_n = max(1, math.ceil(unique_movies * 0.01))
    top1pct_share = sum(c for _, c in sorted_movies[:top1pct_n]) / total_recs

    probs = [c / total_recs for _, c in sorted_movies]
    hhi = sum(p * p for p in probs)

    mids = [m for m, _ in sorted_movies]
    x_rec = [float(rec_counts[m]) for m in mids]
    y_watch_events = [float(watch_events.get(m, 0)) for m in mids]
    y_watch_minutes = [float(watch_minutes.get(m, 0)) for m in mids]

    spearman_rec_watch_events = spearman(x_rec, y_watch_events)
    spearman_rec_watch_minutes = spearman(x_rec, y_watch_minutes)

    decile = max(1, unique_movies // 10)
    top_decile = mids[:decile]
    bottom_decile = mids[-decile:]

    avg_watch_top = sum(watch_events.get(m, 0) for m in top_decile) / len(top_decile)
    avg_watch_bottom = sum(watch_events.get(m, 0) for m in bottom_decile) / len(bottom_decile)
    top_bottom_watch_ratio = (avg_watch_top / avg_watch_bottom) if avg_watch_bottom else None

    # Heuristic "evidence" condition for positive-loop signal
    loop_signal = (
        top1pct_share >= 0.15
        and spearman_rec_watch_events is not None
        and spearman_rec_watch_events >= 0.3
        and top_bottom_watch_ratio is not None
        and top_bottom_watch_ratio >= 2.0
    )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "rec_log_dir": args.rec_log_dir,
            "watches_csv": args.watches_csv,
        },
        "telemetry": {
            "recommendation_events": rec_events,
            "recommendation_slots": total_slots,
            "unique_recommended_movies": unique_movies,
            "watch_rows": int(sum(watch_events.values())),
        },
        "concentration": {
            "top_10_recommendation_share": top10_share,
            "top_1pct_movie_count": top1pct_n,
            "top_1pct_recommendation_share": top1pct_share,
            "hhi_recommendation_share": hhi,
        },
        "feedback_correlation": {
            "spearman_rec_count_vs_watch_events": spearman_rec_watch_events,
            "spearman_rec_count_vs_watch_minutes": spearman_rec_watch_minutes,
            "top_decile_movie_count": decile,
            "avg_watch_events_top_decile": avg_watch_top,
            "avg_watch_events_bottom_decile": avg_watch_bottom,
            "top_bottom_watch_ratio": top_bottom_watch_ratio,
        },
        "conclusion": {
            "negative_feedback_loop_signal_detected": bool(loop_signal),
            "interpretation": (
                "positive rich-get-richer signal"
                if loop_signal
                else "no strong loop signal under current thresholds"
            ),
            "thresholds": {
                "top_1pct_recommendation_share": 0.15,
                "spearman_rec_count_vs_watch_events": 0.3,
                "top_bottom_watch_ratio": 2.0,
            },
        },
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result["conclusion"], indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
