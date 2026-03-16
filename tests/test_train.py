"""Tests for pipeline.train."""
import json
import os
import pytest
import pandas as pd
from pipeline.train import run


@pytest.fixture
def train_fixture(tmpdir_fixture):
    """Create data + metadata for training. NMF needs n_components <= min(users, movies)."""
    data_dir = os.path.join(tmpdir_fixture, "data")
    meta_dir = os.path.join(tmpdir_fixture, "metadata")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)
    n = 60  # NMF uses n_components=50, need min(users,movies) >= 50
    users = {f"u{i}": {"userid": f"u{i}"} for i in range(n)}
    movies = {f"m{i}": {"id": f"m{i}", "title": f"Movie {i}", "genres": [{"name": "Drama"}]} for i in range(n)}
    with open(os.path.join(meta_dir, "users.json"), "w") as f:
        json.dump(users, f)
    with open(os.path.join(meta_dir, "movies.json"), "w") as f:
        json.dump(movies, f)
    rows = []
    for i in range(n):
        for j in range(5):
            rows.append({"user_id": f"u{i}", "movie_id": f"m{(i + j) % n}", "rating": 3 + (i + j) % 3})
    ratings = pd.DataFrame(rows)
    watches = pd.DataFrame([{"user_id": f"u{i}", "movie_id": f"m{i}", "minutes_watched": 10} for i in range(10)])
    ratings.to_csv(os.path.join(data_dir, "ratings.csv"), index=False)
    watches.to_csv(os.path.join(data_dir, "watches.csv"), index=False)
    return {"data_dir": data_dir, "meta_dir": meta_dir}


def test_train_run(tmpdir_fixture, train_fixture):
    models_dir = os.path.join(tmpdir_fixture, "models")
    result = run(
        data_dir=train_fixture["data_dir"],
        metadata_dir=train_fixture["meta_dir"],
        models_dir=models_dir,
    )
    assert os.path.exists(result["model_nmf"])
    assert os.path.exists(result["model_popularity"])
    assert os.path.exists(result["cold_start"])
    assert "nmf_train_sec" in result
