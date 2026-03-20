"""
Movie Recommendation API
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).

Instrumented with Prometheus metrics for monitoring.
"""
import os
import time
import json

from flask import Flask, request, g
import requests
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    generate_latest, CONTENT_TYPE_LATEST,
)

from src.recommender import get_recommendations, get_model_type

app = Flask(__name__)

API_BASE = "http://128.2.220.241:8080"
USER_TIMEOUT = 0.2

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return "Movie Recommendation API is active. Use /recommend/<userid>"


@app.route("/recommend/<userid>")
def recommend(userid):
    start = time.time()
    model_type = "unknown"
    try:
        user_data = None
        try:
            resp = requests.get(f"{API_BASE}/user/{userid}", timeout=USER_TIMEOUT)
            if resp.status_code == 200:
                user_data = resp.json()
        except Exception:
            pass

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082)
