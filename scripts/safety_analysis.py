#!/usr/bin/env python3
"""Run the Milestone 4 safety analysis and write a JSON artifact."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.analysis import safety as sa  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 safety analysis")
    parser.add_argument("--rec-log-dir", default="experiments/logs",
                        help="Directory containing recommendation-event JSONL files.")
    parser.add_argument("--watch-log-dir", default=None,
                        help="Optional directory containing watch-event JSONL shards.")
    parser.add_argument("--users", default="metadata/users.json")
    parser.add_argument("--movies", default="metadata/movies.json")
    parser.add_argument("--output", default="experiments/results/m4_safety.json")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    users = sa.load_users(args.users)
    movies = sa.load_movies(args.movies)

    rec_events = list(sa.iter_rec_events(args.rec_log_dir))
    exposures = sa.build_minor_adult_exposures(iter(rec_events), users, movies)

    watch_log_used = bool(args.watch_log_dir and os.path.isdir(args.watch_log_dir))
    if watch_log_used:
        sa.annotate_watch_followthrough(exposures, sa.iter_watch_events(args.watch_log_dir))

    summary = sa.summarize_minor_safety(exposures)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": "minor_adult_exposure",
        "inputs": {
            "rec_log_dir": args.rec_log_dir,
            "watch_log_dir": args.watch_log_dir,
            "users": args.users,
            "movies": args.movies,
            "watch_log_used": watch_log_used,
        },
        "telemetry": {
            "recommendation_event_count": len(rec_events),
            "under_18_event_count": summary["recommendation_events_analyzed"],
        },
        "results": summary,
    }

    with open(args.output, "w") as handle:
        json.dump(result, handle, indent=2)

    _print_summary(result)
    return 0


def _print_summary(result: dict) -> None:
    res = result["results"]
    print("=" * 60)
    print("SAFETY ANALYSIS HEADLINE")
    print("=" * 60)
    print(f"Recommendation events scanned: {result['telemetry']['recommendation_event_count']}")
    print(f"Under-18 recommendation events: {res['recommendation_events_analyzed']}")
    print(f"Events with adult titles: {res['events_with_adult_titles']}")
    print(f"Adult-title share: {res['minor_adult_title_share']}")
    print(f"Adult-recommendation rate: {res['minor_adult_recommendation_rate']}")
    print(f"Adult-watch followthrough rate: {res['minor_adult_watch_rate']}")
    print(f"Conclusion: {res['conclusion']}")


if __name__ == "__main__":
    raise SystemExit(main())