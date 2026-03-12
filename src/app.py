"""
Movie Recommendation API - Milestone 1
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).
"""
from flask import Flask
import requests

from src.recommender import get_recommendations
from src.clients import CourseApiClient

app = Flask(__name__)

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
    user_data = None
    try:
        client = create_course_api_client()
        user_data = client.get_user(userid)
    except Exception:
        pass  # Proceed without user data (cold start / fallback)

    recs = get_recommendations(userid, user_data=user_data, force_popularity=False)
    # Ensure we return only valid movie IDs, comma-separated, up to 20 (plain text, not JSON)
    result = ",".join(recs[:20]) if isinstance(recs, list) else str(recs)
    return result, 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082)
