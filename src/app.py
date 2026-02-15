"""
Movie Recommendation API - Milestone 1
Serves recommendations at /recommend/<userid>
Returns comma-separated list of up to 20 movie IDs (single line).
"""
from flask import Flask
import requests

from src.recommender import get_recommendations

app = Flask(__name__)

API_BASE = "http://128.2.220.241:8080"
USER_TIMEOUT = 0.3  # Stay under 600ms total


@app.route("/")
def home():
    return "Movie Recommendation API is active. Use /recommend/<userid>"


@app.route("/recommend/<userid>")
def recommend(userid):
    user_data = None
    try:
        resp = requests.get(f"{API_BASE}/user/{userid}", timeout=USER_TIMEOUT)
        if resp.status_code == 200:
            user_data = resp.json()
    except Exception:
        pass  # Proceed without user data (cold start / fallback)

    recs = get_recommendations(userid, user_data=user_data, force_popularity=False)
    # Ensure we return only valid movie IDs, comma-separated, up to 20
    result = ",".join(recs[:20]) if isinstance(recs, list) else str(recs)
    return result


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082)
