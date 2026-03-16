"""
Data quality: schema validation and drift detection.
"""
import json
import os
import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


VALID_EVENT_TYPES = {"rating", "watch", "recommendation", "signup"}


def validate_kafka_event(data: Any) -> bool:
    """
    Validate a Kafka log event (dict from JSONL).
    Required: type in {rating, watch, recommendation, signup}
    Per-type: userid, and type-specific fields.
    """
    if not isinstance(data, dict):
        return False
    event_type = data.get("type")
    if event_type not in VALID_EVENT_TYPES:
        return False
    userid = data.get("userid")
    if userid is None or not str(userid).strip():
        return False
    if event_type == "rating":
        return (
            "movieid" in data
            and "rating" in data
            and "timestamp" in data
            and isinstance(data.get("rating"), (int, float))
            and 1 <= data["rating"] <= 10
        )
    if event_type == "watch":
        return (
            "movieid" in data
            and "minute" in data
            and "timestamp" in data
            and isinstance(data.get("minute"), (int, float))
        )
    if event_type == "recommendation":
        return "timestamp" in data and "status" in data
    if event_type == "signup":
        return "timestamp" in data
    return False


def validate_user_api_response(data: Any) -> bool:
    """Validate user API response. Requires userid; optional self_description fields."""
    if not isinstance(data, dict):
        return False
    if "userid" not in data:
        return False
    likes = data.get("self_description_likes")
    dislikes = data.get("self_description_dislikes")
    if likes is not None and not isinstance(likes, str):
        return False
    if dislikes is not None and not isinstance(dislikes, str):
        return False
    return True


def validate_movie_api_response(data: Any) -> bool:
    """Validate movie API response. Requires id; optional title, cost."""
    if not isinstance(data, dict):
        return False
    if "id" not in data and "title" not in data and "original_title" not in data:
        return False
    cost = data.get("cost")
    if cost is not None and not isinstance(cost, (int, float)):
        return False
    return True


def validate_userid(userid: str) -> bool:
    """Validate recommendation API userid input. Reject empty or suspicious values."""
    if not userid or not isinstance(userid, str):
        return False
    s = userid.strip()
    if not s:
        return False
    if len(s) > 100:
        return False
    if "\n" in s or "\r" in s or "," in s:
        return False
    return True


# --- Drift detection ---


def compute_rating_distribution(ratings: List[dict]) -> Dict[int, float]:
    """Compute rating histogram (1-10) as proportions."""
    counts = Counter()
    for r in ratings:
        rating = r.get("rating")
        if isinstance(rating, (int, float)) and 1 <= rating <= 10:
            counts[int(rating)] += 1
    total = sum(counts.values())
    if total == 0:
        return {i: 0.0 for i in range(1, 11)}
    return {i: counts.get(i, 0) / total for i in range(1, 11)}


def compute_feature_stats(ratings: List[dict], watches: List[dict]) -> Dict[str, float]:
    """Compute mean/std of key features: ratings per user, movies per user."""
    user_ratings = defaultdict(int)
    user_movies = defaultdict(set)
    for r in ratings:
        uid = r.get("user_id") or r.get("userid")
        if uid:
            user_ratings[str(uid)] += 1
            mid = r.get("movie_id") or r.get("movieid")
            if mid:
                user_movies[str(uid)].add(str(mid))
    for w in watches:
        uid = w.get("user_id") or w.get("userid")
        if uid:
            mid = w.get("movie_id") or w.get("movieid")
            if mid:
                user_movies[str(uid)].add(str(mid))
    rpu = list(user_ratings.values())
    mpu = [len(user_movies[u]) for u in user_movies]
    return {
        "ratings_per_user_mean": statistics.mean(rpu) if rpu else 0,
        "ratings_per_user_std": statistics.stdev(rpu) if len(rpu) > 1 else 0,
        "movies_per_user_mean": statistics.mean(mpu) if mpu else 0,
        "movies_per_user_std": statistics.stdev(mpu) if len(mpu) > 1 else 0,
    }


def detect_rating_drift(
    baseline_dist: Dict[int, float],
    recent_dist: Dict[int, float],
    threshold: float = 0.3,
) -> Tuple[bool, float]:
    """
    Compare rating distributions. Use simple L1 distance.
    Returns (drift_detected, distance).
    """
    distance = sum(abs(baseline_dist.get(i, 0) - recent_dist.get(i, 0)) for i in range(1, 11))
    return (distance > threshold, distance)


def detect_feature_drift(
    baseline_stats: Dict[str, float],
    recent_stats: Dict[str, float],
    threshold_sigma: float = 3.0,
) -> Tuple[bool, List[str]]:
    """
    Flag if any feature mean shifts by more than threshold_sigma standard deviations.
    Returns (drift_detected, list of drifted feature names).
    """
    drifted = []
    for key in ["ratings_per_user_mean", "movies_per_user_mean"]:
        b = baseline_stats.get(key, 0)
        r = recent_stats.get(key, 0)
        std_key = key.replace("_mean", "_std")
        std = baseline_stats.get(std_key, 1e-6)
        if std > 0 and abs(r - b) > threshold_sigma * std:
            drifted.append(key)
    return (len(drifted) > 0, drifted)


def save_baseline_stats(stats: dict, path: str) -> None:
    """Persist baseline stats for drift comparison."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(stats, f, indent=2)


def load_baseline_stats(path: str) -> Optional[dict]:
    """Load baseline stats from file."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def run_quality_checks(
    raw_logs_dir: str,
    output_dir: str,
    invalid_events_path: Optional[str] = None,
) -> dict:
    """
    Run schema validation on raw logs, optionally write invalid events.
    Compute baseline stats for drift (caller can persist to baseline_stats.json).
    """
    import glob

    pattern = os.path.join(raw_logs_dir, "*.jsonl")
    log_files = glob.glob(pattern)
    valid_count = 0
    invalid_count = 0
    invalid_events = []
    ratings = []
    watches = []

    for filepath in log_files:
        with open(filepath) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    invalid_count += 1
                    continue
                if validate_kafka_event(data):
                    valid_count += 1
                    if data.get("type") == "rating":
                        ratings.append(
                            {
                                "user_id": data["userid"],
                                "movie_id": data["movieid"],
                                "rating": data["rating"],
                            }
                        )
                    elif data.get("type") == "watch":
                        watches.append(
                            {
                                "user_id": data["userid"],
                                "movie_id": data["movieid"],
                            }
                        )
                else:
                    invalid_count += 1
                    if invalid_events_path:
                        invalid_events.append(data)

    if invalid_events_path and invalid_events:
        parent = os.path.dirname(invalid_events_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(invalid_events_path, "w") as f:
            for ev in invalid_events[:1000]:  # Cap
                f.write(json.dumps(ev) + "\n")

    rating_dist = compute_rating_distribution(ratings)
    feature_stats = compute_feature_stats(ratings, watches)

    return {
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "violation_rate": invalid_count / max(1, valid_count + invalid_count),
        "rating_distribution": rating_dist,
        "feature_stats": feature_stats,
    }
