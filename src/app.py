"""
Movie Recommendation API - Milestone 3
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).

Includes A/B experimentation support: active experiments route users to
different recommendation variants and log assignments for analysis.
"""
import logging
from flask import Flask, abort, jsonify
import requests

from src.recommender import get_recommendations
from src.clients import CourseApiClient
from src.data_quality import validate_recommendation_request
from src.experiment import get_manager
from src.recommender_variants import get_variant_recommender

app = Flask(__name__)
logger = logging.getLogger(__name__)

API_BASE = "http://128.2.220.241:8080"
USER_TIMEOUT = 0.2  # Stay under 600ms total


def create_course_api_client(
    api_base: str = API_BASE,
    timeout_sec: float = USER_TIMEOUT,
    http=None,
) -> CourseApiClient:
    return CourseApiClient(api_base=api_base, http=http or requests, timeout_sec=timeout_sec)


@app.route("/")
def home():
    return "Movie Recommendation API is active. Use /recommend/<userid>"


@app.route("/recommend/<userid>")
def recommend(userid):
    # Schema validation: reject invalid user IDs (data quality - M2)
    validation = validate_recommendation_request(userid)
    if not validation["valid"]:
        abort(400, "Invalid userid")

    user_data = None
    try:
        client = create_course_api_client()
        user_data = client.get_user(userid)
    except Exception:
        pass  # Proceed without user data (cold start / fallback)

    # --- A/B Experiment routing ---
    recs = None
    try:
        mgr = get_manager()
        for exp in mgr.get_active_experiments():
            variant = mgr.get_variant_for_user(exp.id, userid)
            if variant:
                variant_fn = get_variant_recommender(exp.id, variant.name)
                if variant_fn:
                    recs = variant_fn(userid, user_data=user_data)
                    mgr.log_assignment(exp.id, userid, variant.name, recs or [])
                    break  # Use the first matching active experiment
    except Exception as e:
        logger.warning("Experiment routing failed, using default: %s", e)

    # Fallback to default recommender if no experiment matched
    if recs is None:
        recs = get_recommendations(userid, user_data=user_data, force_popularity=False)

    # Ensure we return only valid movie IDs, comma-separated, up to 20 (plain text, not JSON)
    result = ",".join(recs[:20]) if isinstance(recs, list) else str(recs)
    return result, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/experiments")
def list_experiments():
    """Status page: show active experiments and their variants."""
    mgr = get_manager()
    experiments = []
    for exp in mgr.get_active_experiments():
        experiments.append({
            "id": exp.id,
            "name": exp.name,
            "status": exp.status,
            "variants": [{"name": v.name, "traffic_pct": v.traffic_pct} for v in exp.variants],
        })
    return jsonify({"active_experiments": experiments})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082)
