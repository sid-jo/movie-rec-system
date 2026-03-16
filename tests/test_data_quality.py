"""Tests for pipeline.data_quality."""
import json
import os
import pytest
from pipeline.data_quality import (
    validate_kafka_event,
    validate_user_api_response,
    validate_movie_api_response,
    validate_userid,
    compute_rating_distribution,
    compute_feature_stats,
    detect_rating_drift,
    detect_feature_drift,
    run_quality_checks,
    save_baseline_stats,
    load_baseline_stats,
)


def test_validate_kafka_event_rating():
    assert validate_kafka_event({"type": "rating", "userid": "u1", "movieid": "m1", "rating": 8, "timestamp": "t"})
    assert not validate_kafka_event({"type": "rating", "userid": "u1", "movieid": "m1", "rating": 15, "timestamp": "t"})
    assert not validate_kafka_event({"type": "rating", "userid": "", "movieid": "m1", "rating": 8, "timestamp": "t"})


def test_validate_kafka_event_watch():
    assert validate_kafka_event({"type": "watch", "userid": "u1", "movieid": "m1", "minute": 5, "timestamp": "t"})
    assert not validate_kafka_event({"type": "watch", "userid": "u1"})  # missing fields


def test_validate_kafka_event_invalid_type():
    assert not validate_kafka_event({"type": "unknown", "userid": "u1"})
    assert not validate_kafka_event({})
    assert not validate_kafka_event("not a dict")


def test_validate_userid():
    assert validate_userid("70106")
    assert validate_userid("abc")
    assert not validate_userid("")
    assert not validate_userid("a\nb")
    assert not validate_userid("a,b")


def test_validate_user_api_response():
    assert validate_user_api_response({"userid": "u1"})
    assert validate_user_api_response({"userid": "u1", "self_description_likes": "I like X"})
    assert not validate_user_api_response({})
    assert not validate_user_api_response({"userid": "u1", "self_description_likes": 123})


def test_validate_movie_api_response():
    assert validate_movie_api_response({"id": "m1", "title": "X"})
    assert validate_movie_api_response({"title": "X"})
    assert validate_movie_api_response({"id": "m1", "cost": 1.5})
    assert not validate_movie_api_response({"cost": "invalid"})


def test_compute_rating_distribution():
    ratings = [{"rating": 8}, {"rating": 8}, {"rating": 5}]
    dist = compute_rating_distribution(ratings)
    assert dist[8] == pytest.approx(2 / 3)
    assert dist[5] == pytest.approx(1 / 3)


def test_detect_rating_drift():
    base = {i: 0.1 for i in range(1, 11)}
    recent = {i: 0.1 for i in range(1, 11)}
    drifted, dist = detect_rating_drift(base, recent)
    assert not drifted
    recent[1] = 0.5
    recent[2] = 0.0
    drifted, _ = detect_rating_drift(base, recent, threshold=0.1)
    assert drifted


def test_detect_feature_drift():
    base = {"ratings_per_user_mean": 10, "ratings_per_user_std": 1, "movies_per_user_mean": 5, "movies_per_user_std": 1}
    recent = {"ratings_per_user_mean": 10, "ratings_per_user_std": 1, "movies_per_user_mean": 5, "movies_per_user_std": 1}
    drifted, names = detect_feature_drift(base, recent)
    assert not drifted
    recent["ratings_per_user_mean"] = 20  # 10 sigma shift
    drifted, names = detect_feature_drift(base, recent, threshold_sigma=3.0)
    assert drifted
    assert "ratings_per_user_mean" in names


def test_run_quality_checks(tmpdir_fixture):
    raw_dir = os.path.join(tmpdir_fixture, "raw_logs")
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, "t.jsonl"), "w") as f:
        f.write(json.dumps({"type": "rating", "userid": "u1", "movieid": "m1", "rating": 8, "timestamp": "t"}) + "\n")
        f.write(json.dumps({"type": "invalid"}) + "\n")
    out_dir = os.path.join(tmpdir_fixture, "quality")
    result = run_quality_checks(raw_logs_dir=raw_dir, output_dir=out_dir, invalid_events_path=os.path.join(out_dir, "invalid.jsonl"))
    assert result["valid_count"] == 1
    assert result["invalid_count"] == 1
    assert "rating_distribution" in result
    assert "feature_stats" in result


def test_save_load_baseline_stats(tmpdir_fixture):
    path = os.path.join(tmpdir_fixture, "baseline.json")
    stats = {"rating_distribution": {"1": 0.1}, "feature_stats": {"x": 1.0}}
    save_baseline_stats(stats, path)
    loaded = load_baseline_stats(path)
    assert loaded == stats
    assert load_baseline_stats("/nonexistent/path.json") is None
