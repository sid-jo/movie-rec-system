"""Tests for data quality: schema validation and drift detection."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from data_quality import (
    validate_kafka_log_entry,
    validate_user_api_response,
    validate_movie_api_response,
    validate_recommendation_request,
    validate_recommendation_response,
    DriftDetector,
)


# ---------------------------------------------------------------------------
# Kafka schema validation
# ---------------------------------------------------------------------------

class TestKafkaValidation:
    def test_valid_rating_event(self):
        line = "2026-03-01T12:00:00,12345,GET /rate/the+matrix+1999=4"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_valid_watch_event(self):
        line = "2026-03-01T12:00:00,12345,GET /data/m/the+matrix+1999/15.mpg"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is True

    def test_valid_recommendation_event(self):
        line = "2026-03-01T12:00:00,12345,recommendation request 123.456.7.8, status 200, result: [movie1, movie2]"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is True

    def test_valid_signup_event(self):
        line = "2026-03-01T12:00:00,12345,create_account"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is True

    def test_empty_line(self):
        result = validate_kafka_log_entry("")
        assert result["valid"] is False
        assert "empty line" in result["errors"]

    def test_too_few_fields(self):
        result = validate_kafka_log_entry("just,two")
        assert result["valid"] is False
        assert "expected at least 3 comma-separated fields" in result["errors"]

    def test_rating_out_of_range(self):
        line = "2026-03-01T12:00:00,12345,GET /rate/movie=9"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is False
        assert any("outside expected range" in e for e in result["errors"])

    def test_malformed_watch(self):
        line = "2026-03-01T12:00:00,12345,GET /data/m/badformat"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is False
        assert any("malformed" in e for e in result["errors"])

    def test_recommendation_missing_status(self):
        line = "2026-03-01T12:00:00,12345,recommendation request 123.456.7.8"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is False

    def test_unrecognized_event(self):
        line = "2026-03-01T12:00:00,12345,some random action"
        result = validate_kafka_log_entry(line)
        assert result["valid"] is False
        assert any("unrecognized" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# User API schema validation
# ---------------------------------------------------------------------------

class TestUserApiValidation:
    def test_valid_user(self):
        data = {"user_id": 123, "age": 25, "self_description_likes": "I like sci-fi"}
        result = validate_user_api_response(data)
        assert result["valid"] is True

    def test_missing_user_id(self):
        data = {"age": 25}
        result = validate_user_api_response(data)
        assert result["valid"] is False
        assert any("user_id" in e for e in result["errors"])

    def test_not_a_dict(self):
        result = validate_user_api_response("not a dict")
        assert result["valid"] is False

    def test_wrong_type_likes(self):
        data = {"user_id": 1, "self_description_likes": 123}
        result = validate_user_api_response(data)
        assert result["valid"] is False
        assert any("self_description_likes" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Movie API schema validation
# ---------------------------------------------------------------------------

class TestMovieApiValidation:
    def test_valid_movie(self):
        data = {"id": "m1", "title": "Test Movie", "vote_average": 7.5, "genres": [{"name": "Drama"}], "cost": 0.15}
        result = validate_movie_api_response(data)
        assert result["valid"] is True

    def test_missing_title(self):
        data = {"id": "m1", "vote_average": 5.0, "genres": []}
        result = validate_movie_api_response(data)
        assert result["valid"] is False
        assert any("title" in e for e in result["errors"])

    def test_vote_average_out_of_range(self):
        data = {"id": "m1", "title": "T", "vote_average": 15, "genres": []}
        result = validate_movie_api_response(data)
        assert result["valid"] is False

    def test_negative_cost(self):
        data = {"id": "m1", "title": "T", "vote_average": 5, "genres": [], "cost": -1}
        result = validate_movie_api_response(data)
        assert result["valid"] is False

    def test_not_a_dict(self):
        result = validate_movie_api_response([1, 2, 3])
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Recommendation API validation
# ---------------------------------------------------------------------------

class TestRecommendationValidation:
    def test_valid_user_id(self):
        result = validate_recommendation_request("12345")
        assert result["valid"] is True

    def test_empty_user_id(self):
        result = validate_recommendation_request("")
        assert result["valid"] is False

    def test_valid_response(self):
        result = validate_recommendation_response(["movie1", "movie2", "movie3"])
        assert result["valid"] is True

    def test_too_many_recs(self):
        result = validate_recommendation_response([f"m{i}" for i in range(25)])
        assert result["valid"] is False

    def test_empty_recs(self):
        result = validate_recommendation_response([])
        assert result["valid"] is False

    def test_duplicates_in_recs(self):
        result = validate_recommendation_response(["m1", "m2", "m1"])
        assert result["valid"] is False
        assert any("duplicate" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

class TestDriftDetector:
    def test_no_drift_when_stable(self):
        dd = DriftDetector(window_size=100)
        dd.set_reference(ratings=[3.0] * 100, event_types=["watch"] * 80 + ["rating"] * 20, watch_minutes=[30] * 100)
        for _ in range(40):
            dd.add_observation("watch", rating=3.0, watch_minutes=30)
        for _ in range(10):
            dd.add_observation("rating", rating=3.0, watch_minutes=30)
        result = dd.check_drift()
        assert result["drifted"] is False

    def test_drift_on_rating_shift(self):
        dd = DriftDetector(window_size=100)
        dd.set_reference(ratings=[3.0] * 100, event_types=["watch"] * 100, watch_minutes=[30] * 100)
        for _ in range(100):
            dd.add_observation("watch", rating=5.0, watch_minutes=30)
        result = dd.check_drift(threshold_rating=0.5)
        assert result["drifted"] is True
        assert result["details"].get("rating_drift") is True

    def test_drift_on_event_type_shift(self):
        dd = DriftDetector(window_size=100)
        dd.set_reference(ratings=[3.0] * 100, event_types=["watch"] * 90 + ["rating"] * 10, watch_minutes=[30] * 100)
        for _ in range(100):
            dd.add_observation("rating", rating=3.0)
        result = dd.check_drift(threshold_event=0.15)
        assert result["drifted"] is True

    def test_reset_window(self):
        dd = DriftDetector(window_size=100)
        dd.set_reference(ratings=[3.0] * 100, event_types=["watch"] * 100, watch_minutes=[])
        dd.add_observation("watch", rating=5.0)
        dd.reset_window()
        assert len(dd.current_window["ratings"]) == 0
