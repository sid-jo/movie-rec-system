"""Tests for pipeline.data_prep."""
import json
import os
import pytest
from pipeline.data_prep import run


def test_data_prep_run(tmpdir_fixture, sample_metadata):
    raw_dir = os.path.join(tmpdir_fixture, "raw_logs")
    os.makedirs(raw_dir, exist_ok=True)
    # Write minimal JSONL
    with open(os.path.join(raw_dir, "test.jsonl"), "w") as f:
        f.write(json.dumps({"type": "rating", "userid": "u1", "movieid": "m1", "rating": 8, "timestamp": "2025-01-01"}) + "\n")
        f.write(json.dumps({"type": "watch", "userid": "u1", "movieid": "m1", "minute": 5, "timestamp": "2025-01-01"}) + "\n")
    out_dir = os.path.join(tmpdir_fixture, "processed")
    meta_dir = sample_metadata["dir"]
    summary = run(raw_logs_dir=raw_dir, metadata_dir=meta_dir, output_dir=out_dir)
    assert summary["ratings"] == 1
    assert summary["watches"] == 1
    assert os.path.exists(os.path.join(out_dir, "ratings.csv"))
    assert os.path.exists(os.path.join(out_dir, "watches.csv"))
    assert os.path.exists(os.path.join(out_dir, "recommendations.csv"))
    assert os.path.exists(os.path.join(out_dir, "signups.csv"))
    import pandas as pd
    ratings = pd.read_csv(os.path.join(out_dir, "ratings.csv"))
    assert list(ratings.columns) == ["user_id", "movie_id", "rating", "timestamp"]
    assert len(ratings) == 1
