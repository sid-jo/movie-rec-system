"""
Data preparation: load raw logs + metadata -> ratings.csv, watches.csv, etc.
"""
import json
import glob
import os
from collections import defaultdict
from typing import Optional

import pandas as pd


def run(
    raw_logs_dir: str,
    metadata_dir: str,
    output_dir: str,
    parse_json_line=None,
) -> dict:
    """
    Process raw log files and metadata into training CSVs.

    Args:
        raw_logs_dir: Directory containing *.jsonl files
        metadata_dir: Directory with users.json, movies.json
        output_dir: Where to write ratings.csv, watches.csv, etc.
        parse_json_line: Optional function(line) -> dict|None; default json.loads

    Returns:
        Summary dict with counts (ratings, watches, users, movies)
    """
    if parse_json_line is None:

        def parse_json_line(line: str) -> Optional[dict]:
            if not line.strip():
                return None
            try:
                return json.loads(line)
            except (json.JSONDecodeError, TypeError):
                return None

    # Load metadata
    users_path = os.path.join(metadata_dir, "users.json")
    movies_path = os.path.join(metadata_dir, "movies.json")
    with open(users_path) as f:
        users = json.load(f)
    with open(movies_path) as f:
        movies = json.load(f)

    # Process log files
    pattern = os.path.join(raw_logs_dir, "*.jsonl")
    log_files = glob.glob(pattern)

    ratings = []
    watches: dict = defaultdict(lambda: defaultdict(int))
    recommendations = []
    signups = []

    for filepath in log_files:
        with open(filepath) as f:
            for line in f:
                data = parse_json_line(line)
                if not data:
                    continue
                event_type = data.get("type")
                if event_type == "rating":
                    ratings.append(
                        {
                            "user_id": data["userid"],
                            "movie_id": data["movieid"],
                            "rating": data["rating"],
                            "timestamp": data["timestamp"],
                        }
                    )
                elif event_type == "watch":
                    watches[data["userid"]][data["movieid"]] += 1
                elif event_type == "recommendation":
                    recommendations.append(
                        {
                            "user_id": data["userid"],
                            "status": data.get("status"),
                            "timestamp": data["timestamp"],
                        }
                    )
                elif event_type == "signup":
                    signups.append(
                        {
                            "user_id": data["userid"],
                            "timestamp": data["timestamp"],
                        }
                    )

    # Create DataFrames
    ratings_df = pd.DataFrame(ratings)
    watch_data = []
    for user_id, movies_dict in watches.items():
        for movie_id, minutes in movies_dict.items():
            watch_data.append(
                {
                    "user_id": user_id,
                    "movie_id": movie_id,
                    "minutes_watched": minutes,
                }
            )
    watches_df = pd.DataFrame(watch_data)

    # Save
    os.makedirs(output_dir, exist_ok=True)
    ratings_df.to_csv(os.path.join(output_dir, "ratings.csv"), index=False)
    watches_df.to_csv(os.path.join(output_dir, "watches.csv"), index=False)
    pd.DataFrame(recommendations).to_csv(
        os.path.join(output_dir, "recommendations.csv"), index=False
    )
    pd.DataFrame(signups).to_csv(
        os.path.join(output_dir, "signups.csv"), index=False
    )

    summary = {
        "ratings": len(ratings_df),
        "watches": len(watches_df),
        "users": ratings_df["user_id"].nunique() if len(ratings_df) > 0 else 0,
        "movies": ratings_df["movie_id"].nunique() if len(ratings_df) > 0 else 0,
    }
    return summary
