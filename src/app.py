"""
Movie Recommendation API - Milestone 3
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).

Includes:
  - A/B experimentation support: active experiments route users to
    different recommendation variants and log assignments for analysis.
  - Prometheus metrics instrumentation for monitoring.
"""
import logging
import os
import re
import time
import json

from flask import Flask, abort, jsonify
import requests
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    generate_latest, CONTENT_TYPE_LATEST,
)

from src.recommender import get_recommendations, get_model_type
from src.clients import CourseApiClient
from src.data_quality import validate_recommendation_request
from src.experiment import get_manager
from src.recommender_variants import get_variant_recommender

app = Flask(__name__)
logger = logging.getLogger(__name__)

API_BASE = os.environ.get("USER_API_BASE", "http://128.2.220.241:8080")
USER_TIMEOUT = 0.2

# Path segment must be safe for upstream API URLs and match M2 schema (alphanumeric + _-).
_USERID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _valid_userid(userid: str) -> bool:
    return bool(userid and _USERID_RE.fullmatch(userid))

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "recommendation_requests_total",
    "Total recommendation requests",
    ["status", "model_type"],
)
REQUEST_LATENCY = Histogram(
    "recommendation_latency_seconds",
    "Recommendation request latency",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.4, 0.6, 1.0, 2.0, 5.0],
)
REQUEST_ERRORS = Counter(
    "recommendation_errors_total",
    "Total recommendation errors",
    ["error_type"],
)
RECS_SERVED = Counter(
    "recommendations_served_total",
    "Total individual movie recommendations served",
)
MODEL_INFO = Info(
    "recommendation_model",
    "Currently loaded model metadata",
)
SERVICE_UP = Gauge(
    "recommendation_service_up",
    "Whether the recommendation service is healthy (1=up, 0=down)",
)
SERVICE_UP.set(1)

_model_version_file = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "artifacts", "model_version.json",
)


def _load_model_info():
    try:
        if os.path.exists(_model_version_file):
            with open(_model_version_file) as f:
                info = json.load(f)
            MODEL_INFO.info({
                "version": str(info.get("version", "unknown")),
                "trained_at": str(info.get("trained_at", "unknown")),
                "git_sha": str(info.get("git_sha", "unknown")),
            })
    except Exception:
        pass


_load_model_info()


def create_course_api_client(
    api_base: str = API_BASE,
    timeout_sec: float = USER_TIMEOUT,
    http=None,
) -> CourseApiClient:
    return CourseApiClient(api_base=api_base, http=http or requests, timeout_sec=timeout_sec)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return "Movie Recommendation API is active. Use /recommend/<userid>"


@app.route("/recommend/<userid>")
def recommend(userid):
    if not _valid_userid(userid):
        REQUEST_COUNT.labels(status="400", model_type="unknown").inc()
        return "invalid userid", 400, {"Content-Type": "text/plain; charset=utf-8"}

    start = time.time()
    model_type = "unknown"

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

    try:
        # --- A/B Experiment routing (composed pipeline) ---
        # Both experiments run simultaneously on every request:
        #   exp_cold_start   → Stage 1: decides whether to use self-description (input)
        #   exp_cost_optimise → Stage 3: decides whether to re-rank by cost (output)
        # get_recommendations is called exactly once; both experiments log the same
        # final rec list so outcome attribution is consistent.
        recs = None
        try:
            mgr = get_manager()

            # Collect assignments for all active experiments
            assignments = {}
            for exp in mgr.get_active_experiments():
                variant = mgr.get_variant_for_user(exp.id, userid)
                if variant:
                    assignments[exp.id] = variant

            # Stage 1 — exp_cold_start: suppress self-description for treatment arm
            effective_user_data = user_data
            if "exp_cold_start" in assignments:
                if assignments["exp_cold_start"].name == "no_cold_start":
                    effective_user_data = None

            # Stage 2 — run recommender once with the decided input
            recs = get_recommendations(userid, user_data=effective_user_data, force_popularity=False)

            # Stage 3 — exp_cost_optimise: re-rank output for treatment arm
            if "exp_cost_optimise" in assignments:
                if assignments["exp_cost_optimise"].name == "cost_optimised":
                    from src.recommender_variants import _apply_cost_rerank
                    recs = _apply_cost_rerank(userid, recs)

            # Log all assignments with the same final rec list
            for exp_id, variant in assignments.items():
                mgr.log_assignment(exp_id, userid, variant.name, recs or [])

        except Exception as e:
            logger.warning("Experiment routing failed, using default: %s", e)

        # Fallback to default recommender if no experiment matched
        if recs is None:
            recs = get_recommendations(userid, user_data=user_data, force_popularity=False)

        model_type = get_model_type(userid, user_data=user_data)
        result = ",".join(recs[:20]) if isinstance(recs, list) else str(recs)
        n_recs = len(recs[:20]) if isinstance(recs, list) else 0
        RECS_SERVED.inc(n_recs)

        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        REQUEST_COUNT.labels(status="200", model_type=model_type).inc()

        return result, 200, {"Content-Type": "text/plain; charset=utf-8"}

    except Exception as e:
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        REQUEST_COUNT.labels(status="500", model_type=model_type).inc()
        REQUEST_ERRORS.labels(error_type=type(e).__name__).inc()
        return "internal error", 500


@app.route("/health")
def health():
    return "ok", 200


@app.route("/metrics")
def metrics():
    _load_model_info()
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


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
