"""
Data quality module: schema validation and drift detection for all external data interfaces.
Covers Kafka stream, User API, Movie API, and recommendation API inputs.
"""
import re
import json
import logging
from datetime import datetime
from collections import Counter

logger = logging.getLogger(__name__)

VALID_KAFKA_EVENT_TYPES = {"rating", "watch", "recommendation", "signup"}
EXPECTED_MOVIE_ID_PATTERN = re.compile(r"^[a-z0-9+_\-().,' ]+$", re.IGNORECASE)
EXPECTED_RATING_RANGE = (1, 5)
EXPECTED_MINUTE_RANGE = (0, 600)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate_kafka_log_entry(raw_line: str) -> dict:
    """Validate a raw Kafka log line. Returns dict with 'valid' bool and 'errors' list."""
    errors = []
    if not raw_line or not raw_line.strip():
        return {"valid": False, "errors": ["empty line"]}

    parts = raw_line.strip().split(",", 2)
    if len(parts) < 3:
        return {"valid": False, "errors": ["expected at least 3 comma-separated fields"]}

    timestamp_str, userid_str, action = parts[0].strip(), parts[1].strip(), parts[2].strip()

    if not userid_str:
        errors.append("missing userid")

    if not action:
        errors.append("missing action field")

    if "recommendation request" in action:
        if "status" not in action:
            errors.append("recommendation event missing status code")
    elif "/data/m/" in action:
        match = re.search(r"/data/m/([^/]+)/(\d+)\.mpg", action)
        if not match:
            errors.append("watch event has malformed path")
        else:
            minute = int(match.group(2))
            if not (EXPECTED_MINUTE_RANGE[0] <= minute <= EXPECTED_MINUTE_RANGE[1]):
                errors.append(f"watch minute {minute} outside expected range")
    elif "/rate/" in action:
        match = re.search(r"/rate/(.+)=(\d+)", action)
        if not match:
            errors.append("rating event has malformed format")
        else:
            rating = int(match.group(2))
            if not (EXPECTED_RATING_RANGE[0] <= rating <= EXPECTED_RATING_RANGE[1]):
                errors.append(f"rating {rating} outside expected range {EXPECTED_RATING_RANGE}")
    elif "create_account" not in action:
        errors.append(f"unrecognized event type in action: {action[:80]}")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_user_api_response(data: dict) -> dict:
    """Validate a user API JSON response against expected schema."""
    errors = []
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["response is not a dict"]}

    required_fields = ["user_id"]
    for field in required_fields:
        if field not in data:
            errors.append(f"missing required field: {field}")

    if "user_id" in data:
        uid = data["user_id"]
        if not isinstance(uid, (int, str)):
            errors.append(f"user_id has unexpected type: {type(uid).__name__}")

    for text_field in ("self_description_likes", "self_description_dislikes"):
        if text_field in data and data[text_field] is not None:
            if not isinstance(data[text_field], str):
                errors.append(f"{text_field} should be a string, got {type(data[text_field]).__name__}")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_movie_api_response(data: dict) -> dict:
    """Validate a movie API JSON response against expected schema."""
    errors = []
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["response is not a dict"]}

    expected_fields = ["id", "title", "vote_average", "genres"]
    for field in expected_fields:
        if field not in data:
            errors.append(f"missing expected field: {field}")

    if "vote_average" in data:
        va = data["vote_average"]
        if isinstance(va, (int, float)) and not (0 <= va <= 10):
            errors.append(f"vote_average {va} outside expected range [0, 10]")

    if "genres" in data:
        genres = data["genres"]
        if not isinstance(genres, list):
            errors.append("genres should be a list")

    if "cost" in data and data["cost"] is not None:
        cost = data["cost"]
        if not isinstance(cost, (int, float)):
            errors.append(f"cost should be numeric, got {type(cost).__name__}")
        elif cost < 0:
            errors.append(f"cost should be non-negative, got {cost}")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_recommendation_request(user_id: str) -> dict:
    """Validate incoming recommendation API request parameters."""
    errors = []
    if not user_id or not str(user_id).strip():
        errors.append("user_id is empty or missing")
    else:
        uid_str = str(user_id).strip()
        if not uid_str.isdigit() and not uid_str.isalnum():
            errors.append(f"user_id '{uid_str}' contains unexpected characters")
    return {"valid": len(errors) == 0, "errors": errors}


def validate_recommendation_response(recs: list) -> dict:
    """Validate recommendation API output format."""
    errors = []
    if not isinstance(recs, list):
        errors.append("recommendations should be a list")
        return {"valid": False, "errors": errors}
    if len(recs) > 20:
        errors.append(f"too many recommendations: {len(recs)} (max 20)")
    if len(recs) == 0:
        errors.append("empty recommendation list")
    for i, mid in enumerate(recs):
        if not isinstance(mid, str) or not mid.strip():
            errors.append(f"recommendation[{i}] is not a non-empty string")
    if len(recs) != len(set(recs)):
        errors.append("duplicate movie IDs in recommendations")
    return {"valid": len(errors) == 0, "errors": errors}


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

class DriftDetector:
    """Detects distribution drift in streaming data using simple statistical checks."""

    def __init__(self, window_size: int = 5000):
        self.window_size = window_size
        self.reference_stats = {}
        self.current_window = {
            "ratings": [],
            "event_types": [],
            "watch_minutes": [],
        }

    def set_reference(self, ratings: list, event_types: list, watch_minutes: list):
        """Set reference distribution from historical data."""
        if ratings:
            self.reference_stats["rating_mean"] = sum(ratings) / len(ratings)
            self.reference_stats["rating_std"] = (
                sum((r - self.reference_stats["rating_mean"]) ** 2 for r in ratings) / len(ratings)
            ) ** 0.5
        if event_types:
            total = len(event_types)
            counter = Counter(event_types)
            self.reference_stats["event_type_dist"] = {k: v / total for k, v in counter.items()}
        if watch_minutes:
            self.reference_stats["watch_mean"] = sum(watch_minutes) / len(watch_minutes)

    def add_observation(self, event_type: str, rating: float = None, watch_minutes: int = None):
        """Add a single observation to the current window."""
        self.current_window["event_types"].append(event_type)
        if rating is not None:
            self.current_window["ratings"].append(rating)
        if watch_minutes is not None:
            self.current_window["watch_minutes"].append(watch_minutes)

        for key in self.current_window:
            if len(self.current_window[key]) > self.window_size:
                self.current_window[key] = self.current_window[key][-self.window_size:]

    def check_drift(self, threshold_rating: float = 0.5, threshold_event: float = 0.15) -> dict:
        """
        Check for drift between reference and current window.
        Returns dict with 'drifted' bool and 'details' dict.
        """
        details = {}
        drifted = False

        if "rating_mean" in self.reference_stats and self.current_window["ratings"]:
            current_ratings = self.current_window["ratings"]
            current_mean = sum(current_ratings) / len(current_ratings)
            ref_mean = self.reference_stats["rating_mean"]
            shift = abs(current_mean - ref_mean)
            details["rating_mean_shift"] = round(shift, 4)
            details["rating_current_mean"] = round(current_mean, 4)
            details["rating_reference_mean"] = round(ref_mean, 4)
            if shift > threshold_rating:
                drifted = True
                details["rating_drift"] = True

        if "event_type_dist" in self.reference_stats and self.current_window["event_types"]:
            current_types = self.current_window["event_types"]
            total = len(current_types)
            current_dist = Counter(current_types)
            current_dist = {k: v / total for k, v in current_dist.items()}
            ref_dist = self.reference_stats["event_type_dist"]
            all_keys = set(list(ref_dist.keys()) + list(current_dist.keys()))
            max_diff = 0
            for k in all_keys:
                diff = abs(ref_dist.get(k, 0) - current_dist.get(k, 0))
                max_diff = max(max_diff, diff)
            details["event_type_max_diff"] = round(max_diff, 4)
            if max_diff > threshold_event:
                drifted = True
                details["event_type_drift"] = True

        if "watch_mean" in self.reference_stats and self.current_window["watch_minutes"]:
            current_mean = sum(self.current_window["watch_minutes"]) / len(self.current_window["watch_minutes"])
            ref_mean = self.reference_stats["watch_mean"]
            shift = abs(current_mean - ref_mean)
            details["watch_mean_shift"] = round(shift, 4)
            if shift > ref_mean * 0.3:
                drifted = True
                details["watch_drift"] = True

        return {"drifted": drifted, "details": details}

    def reset_window(self):
        """Reset the current observation window."""
        self.current_window = {
            "ratings": [],
            "event_types": [],
            "watch_minutes": [],
        }
