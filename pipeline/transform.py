from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from pipeline.paths import default_paths


@dataclass(frozen=True)
class TransformResult:
    ratings: pd.DataFrame
    watches: pd.DataFrame
    recommendations: pd.DataFrame
    signups: pd.DataFrame
    parse_errors: int
    input_files: int


def _iter_jsonl_files(raw_logs_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(raw_logs_dir, "*.jsonl")))


def _parse_json_lines(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        if not line.strip():
            continue
        yield json.loads(line)


def run(raw_logs_dir: str, output_dir: str) -> TransformResult:
    """
    Transform raw log jsonl files into processed CSVs.

    Expected raw log line format: JSON object produced by `src/kafka_to_gcs.py`
    (fields like type, userid, movieid, rating, timestamp, etc.).
    """
    os.makedirs(output_dir, exist_ok=True)

    log_files = _iter_jsonl_files(raw_logs_dir)
    ratings_rows: list[dict[str, Any]] = []
    watches_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    recommendation_rows: list[dict[str, Any]] = []
    signup_rows: list[dict[str, Any]] = []
    parse_errors = 0

    for fp in log_files:
        try:
            with open(fp) as f:
                for obj in _parse_json_lines(f):
                    event_type = obj.get("type")
                    if event_type == "rating":
                        try:
                            ratings_rows.append(
                                {
                                    "user_id": obj["userid"],
                                    "movie_id": obj["movieid"],
                                    "rating": obj["rating"],
                                    "timestamp": obj["timestamp"],
                                }
                            )
                        except Exception:
                            parse_errors += 1
                    elif event_type == "watch":
                        try:
                            watches_counts[str(obj["userid"])][str(obj["movieid"])] += 1
                        except Exception:
                            parse_errors += 1
                    elif event_type == "recommendation":
                        try:
                            recommendation_rows.append(
                                {
                                    "user_id": obj.get("userid"),
                                    "status": obj.get("status"),
                                    "timestamp": obj.get("timestamp"),
                                    "recommendations": obj.get("recommendations"),
                                }
                            )
                        except Exception:
                            parse_errors += 1
                    elif event_type == "signup":
                        try:
                            signup_rows.append(
                                {
                                    "user_id": obj.get("userid"),
                                    "timestamp": obj.get("timestamp"),
                                }
                            )
                        except Exception:
                            parse_errors += 1
        except Exception:
            parse_errors += 1

    ratings_df = pd.DataFrame(ratings_rows)

    watch_rows: list[dict[str, Any]] = []
    for uid, movies in watches_counts.items():
        for mid, minutes in movies.items():
            watch_rows.append({"user_id": uid, "movie_id": mid, "minutes_watched": minutes})
    watches_df = pd.DataFrame(watch_rows)

    recs_df = pd.DataFrame(recommendation_rows)
    signups_df = pd.DataFrame(signup_rows)

    ratings_df.to_csv(os.path.join(output_dir, "ratings.csv"), index=False)
    watches_df.to_csv(os.path.join(output_dir, "watches.csv"), index=False)
    recs_df.to_csv(os.path.join(output_dir, "recommendations.csv"), index=False)
    signups_df.to_csv(os.path.join(output_dir, "signups.csv"), index=False)

    return TransformResult(
        ratings=ratings_df,
        watches=watches_df,
        recommendations=recs_df,
        signups=signups_df,
        parse_errors=parse_errors,
        input_files=len(log_files),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Transform raw logs → processed CSVs")
    p.add_argument("--raw-logs-dir", default=None, help="Directory containing *.jsonl raw logs")
    p.add_argument("--output-dir", default=None, help="Directory to write processed CSVs")
    args = p.parse_args(argv)

    paths = default_paths()
    raw_dir = args.raw_logs_dir or paths.data_raw_logs
    out_dir = args.output_dir or paths.data_processed
    res = run(raw_logs_dir=raw_dir, output_dir=out_dir)
    print(
        f"wrote processed CSVs to {out_dir} (files={res.input_files}, "
        f"ratings={len(res.ratings):,}, watches={len(res.watches):,}, "
        f"errors={res.parse_errors})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

