import os

import pandas as pd

from pipeline.transform import run


def test_transform_writes_expected_csvs(tmp_path):
    raw_dir = tmp_path / "raw"
    out_dir = tmp_path / "processed"
    raw_dir.mkdir()

    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_raw_logs.jsonl")
    with open(fixture_path) as f:
        (raw_dir / "sample.jsonl").write_text(f.read())

    res = run(raw_logs_dir=str(raw_dir), output_dir=str(out_dir))
    assert res.input_files == 1

    ratings = pd.read_csv(out_dir / "ratings.csv")
    watches = pd.read_csv(out_dir / "watches.csv")
    recs = pd.read_csv(out_dir / "recommendations.csv")
    signups = pd.read_csv(out_dir / "signups.csv")

    assert len(ratings) == 1
    assert set(ratings.columns) >= {"user_id", "movie_id", "rating", "timestamp"}
    assert len(watches) == 1
    assert set(watches.columns) >= {"user_id", "movie_id", "minutes_watched"}
    assert len(recs) == 1
    assert "recommendations" in recs.columns
    assert len(signups) == 1

