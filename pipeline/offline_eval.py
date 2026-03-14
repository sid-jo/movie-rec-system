from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from pipeline.paths import default_paths, path_relative_to_root


def _dcg(recommended: list[str], relevant: set[str], k: int) -> float:
    score = 0.0
    for i, mid in enumerate(recommended[:k]):
        if mid in relevant:
            score += 1.0 / __import__("math").log2(i + 2)
    return score


def ndcg_at_k(recommended: list[str], relevant: set[str], k: int = 20) -> float:
    if not relevant:
        return 0.0
    dcg = _dcg(recommended, relevant, k)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / __import__("math").log2(i + 2) for i in range(ideal_hits))
    return 0.0 if idcg == 0 else (dcg / idcg)


@dataclass(frozen=True)
class OfflineEvalResult:
    ndcg_mean: float
    ndcg_per_user: dict[str, float]
    users_evaluated: int
    users_skipped_no_relevant: int
    k: int
    rating_threshold: float
    test_ratio: float


def _train_test_split_per_user_chronological(
    ratings_df, test_ratio: float
) -> tuple[Any, Any]:
    import pandas as pd

    train_parts: list[pd.DataFrame] = []
    test_parts: list[pd.DataFrame] = []
    for user_id in ratings_df["user_id"].unique():
        u = ratings_df[ratings_df["user_id"] == user_id].copy()
        u = u.sort_values("timestamp")
        n = len(u)
        n_test = max(1, int(n * test_ratio))
        train_parts.append(u.iloc[:-n_test])
        test_parts.append(u.iloc[-n_test:])
    return pd.concat(train_parts, ignore_index=True), pd.concat(test_parts, ignore_index=True)


def run(artifacts_dir: str, processed_dir: str, metadata_dir: str, output_path: str) -> dict[str, Any]:
    """
    Offline evaluation for the **served recommender** (NMF/popularity artifacts).

    We compute NDCG@k on a per-user chronological split from `data/processed/ratings.csv`.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    import pandas as pd

    ratings_df = pd.read_csv(os.path.join(processed_dir, "ratings.csv"))
    # Ensure consistent dtypes
    ratings_df["user_id"] = ratings_df["user_id"].astype(str)
    ratings_df["movie_id"] = ratings_df["movie_id"].astype(str)

    # Make sure artifacts are loadable via `src.recommender` (joblib artifacts)
    # (Also ensures metadata/movies.json exists for valid_movie_ids filtering)
    if not os.path.exists(os.path.join(metadata_dir, "movies.json")):
        raise FileNotFoundError(f"missing {os.path.join(metadata_dir, 'movies.json')}")

    # Force artifact directory by copying/symlinking is overkill; `src.recommender`
    # always reads from repo models/artifacts, so we validate this is the same dir.
    paths = default_paths()
    expected_artifacts = os.path.join(paths.root, "models", "artifacts")
    if os.path.abspath(artifacts_dir) != os.path.abspath(expected_artifacts):
        raise ValueError(
            f"offline eval currently expects artifacts in {expected_artifacts} "
            f"(got {artifacts_dir})"
        )

    test_ratio = 0.2
    train_df, test_df = _train_test_split_per_user_chronological(ratings_df, test_ratio=test_ratio)

    # For this repo's served model, training artifacts are produced from the full dataset.
    # Offline eval still uses a *holdout* set, but recommendations come from the trained artifacts.
    # That means the metric is optimistic; we record this explicitly.
    from src.recommender import get_recommendations

    k = 20
    rating_threshold = 4.0  # 1–5 star scale in the course API
    ndcg_scores: dict[str, float] = {}
    skipped_no_relevant = 0

    # Relevant items are high-rated movies in each user's TEST set
    for user_id, utest in test_df.groupby("user_id"):
        relevant = set(utest[utest["rating"] >= rating_threshold]["movie_id"].astype(str).tolist())
        if not relevant:
            skipped_no_relevant += 1
            continue
        recs = get_recommendations(user_id, user_data=None, force_popularity=False)
        if not isinstance(recs, list):
            recs = []
        score = ndcg_at_k([str(x) for x in recs], relevant, k=k)
        ndcg_scores[str(user_id)] = float(score)

    ndcg_mean = float(sum(ndcg_scores.values()) / max(1, len(ndcg_scores)))

    results = {
        "evaluation_type": "offline",
        "model": {"name": "served_recommender", "artifacts_dir": path_relative_to_root(artifacts_dir, paths.root)},
        "metric": {"name": "ndcg@20", "k": k, "rating_threshold": rating_threshold},
        "data_split": {"type": "per_user_chronological", "test_ratio": test_ratio},
        "methodology_notes": [
            "Recommendations come from the trained serving artifacts in models/artifacts.",
            "Because artifacts are trained on the full dataset by default, this holdout evaluation is optimistic.",
            "For strict offline eval, retrain artifacts on train_df only before scoring.",
        ],
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline evaluation (emit JSON artifact)")
    p.add_argument("--artifacts-dir", default=None)
    p.add_argument("--processed-dir", default=None)
    p.add_argument("--metadata-dir", default=None)
    p.add_argument("--output", default=None, help="Path to write offline_eval.json")
    args = p.parse_args(argv)

    paths = default_paths()
    artifacts_dir = args.artifacts_dir or os.path.join(paths.root, "models", "artifacts")
    processed_dir = args.processed_dir or paths.data_processed
    metadata_dir = args.metadata_dir or paths.metadata_dir
    out = args.output or os.path.join(paths.reports_dir, "offline_eval.json")

    print(
        f"[offline_eval] starting: artifacts_dir={artifacts_dir}, "
        f"processed_dir={processed_dir}, metadata_dir={metadata_dir} → output={out}"
    )

    res = run(artifacts_dir=artifacts_dir, processed_dir=processed_dir, metadata_dir=metadata_dir, output_path=out)
    print(f"[offline_eval] completed: wrote {out} (ndcg_mean={res['results']['ndcg_mean']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

