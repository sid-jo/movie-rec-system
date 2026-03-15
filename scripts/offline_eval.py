#!/usr/bin/env python3
"""
Offline evaluation: NDCG@k for the served recommender using a per-user chronological split.
Writes results to models/artifacts/offline_eval.json.

Usage:
  python scripts/offline_eval.py [--processed-dir data/processed] [--output models/artifacts/offline_eval.json]
"""
import argparse
import json
import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")

K = 20
RATING_THRESHOLD = 4.0
TEST_RATIO = 0.2


def _dcg(recommended: list, relevant: set, k: int) -> float:
    score = 0.0
    for i, mid in enumerate(recommended[:k]):
        if mid in relevant:
            score += 1.0 / math.log2(i + 2)
    return score


def ndcg_at_k(recommended: list, relevant: set, k: int = 20) -> float:
    if not relevant:
        return 0.0
    dcg = _dcg(recommended, relevant, k)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return 0.0 if idcg == 0 else (dcg / idcg)


def _train_test_split_per_user_chronological(ratings_df, test_ratio: float):
    import pandas as pd
    train_parts = []
    test_parts = []
    for user_id in ratings_df["user_id"].unique():
        u = ratings_df[ratings_df["user_id"] == user_id].copy()
        u = u.sort_values("timestamp")
        n = len(u)
        n_test = max(1, int(n * test_ratio))
        train_parts.append(u.iloc[:-n_test])
        test_parts.append(u.iloc[-n_test:])
    return pd.concat(train_parts, ignore_index=True), pd.concat(test_parts, ignore_index=True)


def run(processed_dir: str, metadata_dir: str, output_path: str) -> dict:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    import pandas as pd

    ratings_path = os.path.join(processed_dir, "ratings.csv")
    if not os.path.exists(ratings_path):
        raise FileNotFoundError(f"missing {ratings_path}")
    ratings_df = pd.read_csv(ratings_path)
    ratings_df["user_id"] = ratings_df["user_id"].astype(str)
    ratings_df["movie_id"] = ratings_df["movie_id"].astype(str)

    if not os.path.exists(os.path.join(metadata_dir, "movies.json")):
        raise FileNotFoundError(f"missing {metadata_dir}/movies.json")

    sys.path.insert(0, PROJECT_ROOT)
    from src.recommender import get_recommendations

    train_df, test_df = _train_test_split_per_user_chronological(ratings_df, test_ratio=TEST_RATIO)

    ndcg_scores = {}
    skipped_no_relevant = 0
    for user_id, utest in test_df.groupby("user_id"):
        relevant = set(utest[utest["rating"] >= RATING_THRESHOLD]["movie_id"].astype(str).tolist())
        if not relevant:
            skipped_no_relevant += 1
            continue
        recs = get_recommendations(user_id, user_data=None, force_popularity=False)
        if not isinstance(recs, list):
            recs = []
        score = ndcg_at_k([str(x) for x in recs], relevant, k=K)
        ndcg_scores[str(user_id)] = float(score)

    ndcg_mean = float(sum(ndcg_scores.values()) / max(1, len(ndcg_scores)))

    results = {
        "evaluation_type": "offline",
        "model": {"name": "served_recommender", "artifacts_dir": "models/artifacts"},
        "metric": {"name": "ndcg@20", "k": K, "rating_threshold": RATING_THRESHOLD},
        "data_split": {"type": "per_user_chronological", "test_ratio": TEST_RATIO},
        "results": {
            "ndcg_mean": ndcg_mean,
            "users_evaluated": int(len(ndcg_scores)),
            "users_skipped_no_relevant": int(skipped_no_relevant),
        },
        "dataset": {
            "num_ratings": int(len(ratings_df)),
            "num_users": int(ratings_df["user_id"].nunique()),
            "num_movies": int(ratings_df["movie_id"].nunique()),
            "train_ratings": int(len(train_df)),
            "test_ratings": int(len(test_df)),
        },
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    return results


def main():
    parser = argparse.ArgumentParser(description="Offline evaluation (NDCG@k) → models/artifacts")
    parser.add_argument("--processed-dir", default=DATA_DIR, help="Directory containing ratings.csv")
    parser.add_argument("--metadata-dir", default=METADATA_DIR, help="Directory containing movies.json")
    parser.add_argument("--output", default=None, help="Output JSON path (default: models/artifacts/offline_eval.json)")
    args = parser.parse_args()

    out = args.output or os.path.join(ARTIFACTS_DIR, "offline_eval.json")

    print("Offline evaluation (NDCG@20, per-user chronological split)...")
    res = run(processed_dir=args.processed_dir, metadata_dir=args.metadata_dir, output_path=out)
    print(f"Results saved to {out}")
    print(f"  ndcg_mean={res['results']['ndcg_mean']:.4f}  users_evaluated={res['results']['users_evaluated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
