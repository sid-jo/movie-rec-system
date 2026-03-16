"""
Movie Recommendation API - Milestone 1
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).
"""
import time
import json
import os
import sys
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask, abort
import requests

from src.recommender import get_recommendations
from src import telemetry

app = Flask(__name__)

API_BASE = "http://128.2.220.241:8080"
USER_TIMEOUT = 0.3  # Stay under 600ms total

# Cached movies metadata for cost
_movies_cache = None


def _get_movies():
    global _movies_cache
    if _movies_cache is None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata", "movies.json")
        if os.path.exists(path):
            with open(path) as f:
                _movies_cache = json.load(f)
        else:
            _movies_cache = {}
    return _movies_cache


@app.route("/")
def home():
    return "Movie Recommendation API is active. Use /recommend/<userid>"


@app.route("/recommend/<userid>")
def recommend(userid):
    from pipeline.data_quality import validate_userid
    if not validate_userid(userid):
        abort(400, "Invalid userid")

    user_data = None
    try:
        resp = requests.get(f"{API_BASE}/user/{userid}", timeout=USER_TIMEOUT)
        if resp.status_code == 200:
            user_data = resp.json()
    except Exception:
        pass  # Proceed without user data (cold start / fallback)

    t0 = time.perf_counter()
    recs = get_recommendations(userid, user_data=user_data, force_popularity=False)
    latency_ms = (time.perf_counter() - t0) * 1000

    recs = recs[:20] if isinstance(recs, list) else [str(recs)]
    result = ",".join(recs)

    # Telemetry (non-blocking)
    movies_meta = _get_movies()
    cost = telemetry.get_movie_costs(recs, movies_meta)
    telemetry.log_recommendation(userid, recs, latency_ms, movie_costs=cost)

    return result


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082)
