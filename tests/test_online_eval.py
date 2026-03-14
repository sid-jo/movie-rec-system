"""Tests for online evaluation metric computation and Kafka line parsing."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.online_eval import parse_kafka_line, compute_accuracy_metrics, compute_cost_metrics


# ---------------------------------------------------------------------------
# Kafka line parsing (raw CSV format from the stream)
# ---------------------------------------------------------------------------

class TestParseKafkaLine:
    def test_recommendation_event_no_brackets(self):
        line = "2026-03-01T12:00:00,70106,recommendation request 1.2.3.4:8082, status 200, result: movie_a, movie_b"
        event = parse_kafka_line(line)
        assert event is not None
        assert event["type"] == "recommendation"
        assert event["userid"] == "70106"
        assert event["status"] == 200
        assert "movie_a" in event["movies"]
        assert "movie_b" in event["movies"]

    def test_recommendation_event_with_brackets(self):
        line = "2026-03-01T12:00:00,70106,recommendation request 1.2.3.4:8082, status 200, result: [movie_a, movie_b]"
        event = parse_kafka_line(line)
        assert event is not None
        assert event["type"] == "recommendation"
        assert "movie_a" in event["movies"]

    def test_watch_event(self):
        line = "2026-03-01T12:00:00,70106,GET /data/m/inception+2010/15.mpg"
        event = parse_kafka_line(line)
        assert event is not None
        assert event["type"] == "watch"
        assert event["movieid"] == "inception+2010"
        assert event["minute"] == 15

    def test_rating_event(self):
        line = "2026-03-01T12:00:00,70106,GET /rate/the+matrix+1999=4"
        event = parse_kafka_line(line)
        assert event is not None
        assert event["type"] == "rating"
        assert event["movieid"] == "the+matrix+1999"
        assert event["rating"] == 4

    def test_malformed_line(self):
        assert parse_kafka_line("bad") is None
        assert parse_kafka_line("a,b") is None

    def test_unknown_action(self):
        event = parse_kafka_line("2026-03-01,70106,GET /some/unknown/path")
        assert event is None

    def test_recommendation_no_result(self):
        line = "2026-03-01T12:00:00,70106,recommendation request 1.2.3.4, status 200"
        event = parse_kafka_line(line)
        assert event is not None
        assert event["type"] == "recommendation"
        assert event["movies"] == ""


# ---------------------------------------------------------------------------
# Accuracy metrics (WTR + Positive-Rating Rate)
# ---------------------------------------------------------------------------

class TestAccuracyMetrics:
    def test_perfect_wtr(self):
        user_recs = {"1": [["m1", "m2", "m3"]]}
        user_watches = {"1": {"m1", "m2", "m3"}}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["watch_through_rate"] == 1.0

    def test_zero_wtr(self):
        user_recs = {"1": [["m1", "m2"]]}
        user_watches = {"1": {"m99"}}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["watch_through_rate"] == 0.0

    def test_empty_data(self):
        result = compute_accuracy_metrics({}, {}, {})
        assert result["watch_through_rate"] == 0.0
        assert result["positive_rating_rate"] == 0.0
        assert result["recommendations_considered"] == 0

    def test_partial_wtr(self):
        user_recs = {"1": [["m1", "m2"]]}
        user_watches = {"1": {"m1"}}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["watch_through_rate"] == 0.5

    def test_multiple_users(self):
        user_recs = {
            "1": [["m1", "m2"]],
            "2": [["m3", "m4"]],
        }
        user_watches = {
            "1": {"m1", "m2"},
            "2": {"m5"},
        }
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["watch_through_rate"] == 0.5

    def test_positive_rating_rate(self):
        user_recs = {"1": [["m1", "m2", "m3", "m4"]]}
        user_watches = {"1": set()}
        user_ratings = {"1": {"m1": 5, "m2": 4, "m3": 3, "m4": 1}}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["positive_rating_rate"] == 0.5  # m1(5) + m2(4) >= 4.0 threshold

    def test_positive_rating_rate_none_positive(self):
        user_recs = {"1": [["m1", "m2"]]}
        user_watches = {"1": set()}
        user_ratings = {"1": {"m1": 2, "m2": 1}}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["positive_rating_rate"] == 0.0

    def test_positive_rating_rate_no_ratings(self):
        user_recs = {"1": [["m1", "m2"]]}
        user_watches = {"1": set()}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["positive_rating_rate"] == 0.0

    def test_recommendations_considered_count(self):
        user_recs = {
            "1": [["m1", "m2"], ["m3"]],
            "2": [["m4"]],
        }
        user_watches = {}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["recommendations_considered"] == 3

    def test_total_recs_served(self):
        user_recs = {"1": [["m1", "m2"]], "2": [["m3", "m4", "m5"]]}
        user_watches = {}
        user_ratings = {}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["total_recs_served"] == 5

    def test_combined_wtr_and_prr(self):
        user_recs = {"1": [["m1", "m2"]]}
        user_watches = {"1": {"m1"}}
        user_ratings = {"1": {"m1": 5}}
        result = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
        assert result["watch_through_rate"] == 0.5
        assert result["positive_rating_rate"] == 0.5
        assert result["total_watched"] == 1
        assert result["total_positive_rated"] == 1


# ---------------------------------------------------------------------------
# Cost metrics
# ---------------------------------------------------------------------------

class TestCostMetrics:
    def test_basic_cost(self):
        watch_events = [
            {"userid": "1", "movieid": "m1"},
            {"userid": "1", "movieid": "m2"},
        ]
        movies_meta = {"m1": {"license_cost": 0.10}, "m2": {"license_cost": 0.20}}
        result = compute_cost_metrics(watch_events, movies_meta, total_rec_requests=1)
        assert result["total_license_cost_usd"] == 0.30
        assert result["total_views"] == 2
        assert result["llm_token_cost_usd"] == 0.0

    def test_fallback_to_cost_field(self):
        watch_events = [{"userid": "1", "movieid": "m1"}]
        movies_meta = {"m1": {"cost": 0.50}}
        result = compute_cost_metrics(watch_events, movies_meta, total_rec_requests=1)
        assert result["total_license_cost_usd"] == 0.50

    def test_missing_cost_field(self):
        watch_events = [{"userid": "1", "movieid": "m1"}]
        movies_meta = {"m1": {"title": "Test"}}
        result = compute_cost_metrics(watch_events, movies_meta, total_rec_requests=0)
        assert result["total_license_cost_usd"] == 0.0
        assert result["views_missing_cost_data"] == 1

    def test_empty_watches(self):
        result = compute_cost_metrics([], {}, total_rec_requests=0)
        assert result["total_views"] == 0
        assert result["total_cost_usd"] == 0.0

    def test_per_rec_cost_attributed(self):
        watch_events = [
            {"userid": "1", "movieid": "m1"},
            {"userid": "2", "movieid": "m1"},
        ]
        movies_meta = {"m1": {"license_cost": 1.00}}
        user_recs = {"1": [["m1"]], "2": [["m1", "m2"]]}
        user_watches = {"1": {"m1"}, "2": {"m1"}}
        result = compute_cost_metrics(watch_events, movies_meta, total_rec_requests=2,
                                      user_recs=user_recs, user_watches=user_watches)
        assert result["rec_attributed_cost_usd"] == 2.0
        assert result["rec_attributed_views"] == 2
        assert result["per_recommendation_cost_usd"] == 1.0

    def test_per_rec_cost_no_recs(self):
        watch_events = [
            {"userid": "1", "movieid": "m1"},
        ]
        movies_meta = {"m1": {"license_cost": 1.00}}
        result = compute_cost_metrics(watch_events, movies_meta, total_rec_requests=4)
        assert result["per_recommendation_cost_usd"] == 0.0
        assert result["rec_attributed_cost_usd"] == 0.0
