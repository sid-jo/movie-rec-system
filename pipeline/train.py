from __future__ import annotations

import argparse
import os
from typing import Any

import pandas as pd

from pipeline.paths import default_paths


def _import_training_module():
    # Keep training logic in one place: existing `scripts/train.py` produces
    # artifacts consumed by `src/recommender.py` (joblib files in models/artifacts).
    import importlib.util

    paths = default_paths()
    train_py = os.path.join(paths.root, "scripts", "train.py")
    spec = importlib.util.spec_from_file_location("scripts_train", train_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import training module at {train_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[assignment]
    return mod


def run(
    processed_dir: str,
    metadata_dir: str,
    artifacts_dir: str,
) -> dict[str, Any]:
    """
    Train serving-compatible artifacts using the logic from `scripts/train.py`.
    """
    os.makedirs(artifacts_dir, exist_ok=True)

    train_mod = _import_training_module()

    ratings = pd.read_csv(os.path.join(processed_dir, "ratings.csv"))
    watches = pd.read_csv(os.path.join(processed_dir, "watches.csv"))

    import json

    with open(os.path.join(metadata_dir, "movies.json")) as f:
        movies = json.load(f)
    with open(os.path.join(metadata_dir, "users.json")) as f:
        users = json.load(f)

    nmf_artifacts = train_mod.train_nmf(ratings, movies)
    pop_artifacts = train_mod.train_popularity(ratings, watches, movies)

    import joblib

    joblib.dump(nmf_artifacts, os.path.join(artifacts_dir, "model_nmf.joblib"))
    joblib.dump(pop_artifacts, os.path.join(artifacts_dir, "model_popularity.joblib"))
    joblib.dump(
        {"title_to_id": pop_artifacts["title_to_id"], "top_movies": pop_artifacts["top_movies"][:500]},
        os.path.join(artifacts_dir, "cold_start.joblib"),
    )

    return {
        "artifacts_dir": artifacts_dir,
        "n_users": len(nmf_artifacts.get("user_id_to_idx", {})),
        "n_movies": int(nmf_artifacts.get("n_movies", 0)),
        "train_time_sec": float(nmf_artifacts.get("train_time_sec", 0.0)),
        "metadata_users": len(users),
        "metadata_movies": len(movies),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train models from processed data")
    p.add_argument("--processed-dir", default=None, help="Directory containing ratings.csv and watches.csv")
    p.add_argument("--metadata-dir", default=None, help="Directory containing users.json and movies.json")
    p.add_argument("--artifacts-dir", default=None, help="Output directory for serving artifacts")
    args = p.parse_args(argv)

    paths = default_paths()
    processed_dir = args.processed_dir or paths.data_processed
    metadata_dir = args.metadata_dir or paths.metadata_dir
    artifacts_dir = args.artifacts_dir or paths.model_artifacts

    res = run(processed_dir=processed_dir, metadata_dir=metadata_dir, artifacts_dir=artifacts_dir)
    print(f"trained artifacts in {res['artifacts_dir']} (users={res['n_users']}, movies={res['n_movies']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

