"""
Training pipeline: load processed data, train NMF + popularity models, save to disk.
"""
import json
import os
import joblib
import pandas as pd

# Add project root for scripts import
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in __import__("sys").path:
    __import__("sys").path.insert(0, _project_root)

from scripts.train import train_nmf, train_popularity


def _load_data(data_dir: str, metadata_dir: str):
    """Load ratings, watches, movies, users from given directories."""
    ratings = pd.read_csv(os.path.join(data_dir, "ratings.csv"))
    watches = pd.read_csv(os.path.join(data_dir, "watches.csv"))
    with open(os.path.join(metadata_dir, "movies.json")) as f:
        movies = json.load(f)
    with open(os.path.join(metadata_dir, "users.json")) as f:
        users = json.load(f)
    return ratings, watches, movies, users


def run(data_dir: str, metadata_dir: str, models_dir: str) -> dict:
    """
    Train NMF and popularity models, save to models_dir.

    Args:
        data_dir: Directory with ratings.csv, watches.csv
        metadata_dir: Directory with users.json, movies.json
        models_dir: Where to write model_nmf.joblib, model_popularity.joblib, cold_start.joblib

    Returns:
        Summary dict with paths and train times
    """
    ratings, watches, movies, users = _load_data(data_dir, metadata_dir)
    os.makedirs(models_dir, exist_ok=True)

    nmf_artifacts = train_nmf(ratings, movies)
    path_nmf = os.path.join(models_dir, "model_nmf.joblib")
    joblib.dump(nmf_artifacts, path_nmf)

    pop_artifacts = train_popularity(ratings, watches, movies)
    path_pop = os.path.join(models_dir, "model_popularity.joblib")
    joblib.dump(pop_artifacts, path_pop)

    cs_path = os.path.join(models_dir, "cold_start.joblib")
    joblib.dump(
        {
            "title_to_id": pop_artifacts["title_to_id"],
            "top_movies": pop_artifacts["top_movies"][:500],
        },
        cs_path,
    )

    return {
        "model_nmf": path_nmf,
        "model_popularity": path_pop,
        "cold_start": cs_path,
        "nmf_train_sec": nmf_artifacts["train_time_sec"],
    }
