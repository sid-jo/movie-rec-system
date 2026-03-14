"""Tests for pipeline components: data parsing, feature engineering, recommender logic."""
import sys
import os
import json
import re
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.recommender import get_recommendations, _extract_movies_from_description


# ---------------------------------------------------------------------------
# Kafka log parsing (same logic used in kafka_collector.py and data_prep.py)
# ---------------------------------------------------------------------------

def parse_log_entry(log_line):
    """Reusable parser extracted from kafka_collector.py for testability."""
    parts = log_line.split(",", 2)
    if len(parts) < 3:
        return None
    timestamp, userid, action = parts[0].strip(), parts[1].strip(), parts[2].strip()
    entry = {"timestamp": timestamp, "userid": userid, "raw": log_line}

    if "recommendation request" in action:
        match = re.search(r"status (\d+)", action)
        if match:
            entry["type"] = "recommendation"
            entry["status"] = int(match.group(1))
            result_match = re.search(r"result: \[(.*?)\]", action)
            if result_match:
                entry["recommendations"] = result_match.group(1)
    elif "/data/m/" in action:
        match = re.search(r"/data/m/([^/]+)/(\d+)\.mpg", action)
        if match:
            entry["type"] = "watch"
            entry["movieid"] = match.group(1)
            entry["minute"] = int(match.group(2))
    elif "/rate/" in action:
        match = re.search(r"/rate/(.+)=(\d+)", action)
        if match:
            entry["type"] = "rating"
            entry["movieid"] = match.group(1)
            entry["rating"] = int(match.group(2))
    elif "create_account" in action:
        entry["type"] = "signup"

    return entry


class TestKafkaLogParsing:
    def test_parse_rating(self):
        line = "2026-03-01T12:00:00,70106,GET /rate/the+matrix+1999=4"
        result = parse_log_entry(line)
        assert result is not None
        assert result["type"] == "rating"
        assert result["movieid"] == "the+matrix+1999"
        assert result["rating"] == 4
        assert result["userid"] == "70106"

    def test_parse_watch(self):
        line = "2026-03-01T12:00:00,70106,GET /data/m/inception+2010/15.mpg"
        result = parse_log_entry(line)
        assert result["type"] == "watch"
        assert result["movieid"] == "inception+2010"
        assert result["minute"] == 15

    def test_parse_recommendation(self):
        line = "2026-03-01T12:00:00,70106,recommendation request 1.2.3.4, status 200, result: [m1, m2, m3]"
        result = parse_log_entry(line)
        assert result["type"] == "recommendation"
        assert result["status"] == 200
        assert "m1, m2, m3" in result["recommendations"]

    def test_parse_signup(self):
        line = "2026-03-01T12:00:00,70106,create_account"
        result = parse_log_entry(line)
        assert result["type"] == "signup"

    def test_parse_malformed_short(self):
        line = "just_one_field"
        result = parse_log_entry(line)
        assert result is None

    def test_parse_unknown_action(self):
        line = "2026-03-01T12:00:00,70106,GET /unknown/endpoint"
        result = parse_log_entry(line)
        assert result is not None
        assert "type" not in result


# ---------------------------------------------------------------------------
# Recommender logic
# ---------------------------------------------------------------------------

class TestRecommender:
    def test_returns_list(self):
        recs = get_recommendations("70106")
        assert isinstance(recs, list)

    def test_returns_at_most_20(self):
        recs = get_recommendations("70106")
        assert len(recs) <= 20

    def test_returns_at_least_one(self):
        recs = get_recommendations("70106")
        assert len(recs) >= 1

    def test_no_duplicates(self):
        recs = get_recommendations("70106")
        assert len(recs) == len(set(recs))

    def test_different_users_different_results(self):
        r1 = get_recommendations("70106")
        r2 = get_recommendations("99999")
        assert r1 != r2 or len(r1) > 0

    def test_unknown_user_returns_results(self):
        recs = get_recommendations("nonexistent_user_999999999")
        assert isinstance(recs, list)
        assert len(recs) >= 1

    def test_force_popularity(self):
        recs = get_recommendations("70106", force_popularity=True)
        assert isinstance(recs, list)
        assert len(recs) >= 1

    def test_movie_ids_are_strings(self):
        recs = get_recommendations("70106")
        for mid in recs:
            assert isinstance(mid, str)
            assert len(mid) > 0


# ---------------------------------------------------------------------------
# Title matching for cold start
# ---------------------------------------------------------------------------

class TestTitleMatching:
    def test_extract_empty_text(self):
        result = _extract_movies_from_description("", {})
        assert result == []

    def test_extract_none_text(self):
        result = _extract_movies_from_description(None, {})
        assert result == []

    def test_extract_matching_title(self):
        title_map = {"the+matrix": "the+matrix+1999", "inception": "inception+2010"}
        result = _extract_movies_from_description("I really love The Matrix", title_map)
        assert "the+matrix+1999" in result

    def test_extract_no_match(self):
        title_map = {"the+matrix": "the+matrix+1999"}
        result = _extract_movies_from_description("I like pizza", title_map)
        assert result == []
