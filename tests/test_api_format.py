import os
import requests
import json
import pytest

# Skip this integration-style test when running in CI (requires GCS credentials).
if os.getenv("CI", "").lower() == "true":
    pytest.skip("Skipping GCS-dependent API format test in CI environment.", allow_module_level=True)


@pytest.mark.integration
def test_course_api_user_and_movie_shapes_smoke():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration test (set RUN_INTEGRATION_TESTS=1 to enable)")

    API_BASE = "http://128.2.220.241:8080"

    resp = requests.get(f"{API_BASE}/user/1", timeout=10)
    assert resp.status_code == 200
    user = resp.json()
    assert isinstance(user, dict)
    assert "user_id" in user

    # Pick a known movie id from metadata if available; otherwise skip movie check.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    movies_path = os.path.join(project_root, "metadata", "movies.json")
    if not os.path.exists(movies_path):
        pytest.skip("metadata/movies.json missing for movie smoke test")

    with open(movies_path) as f:
        movies = json.load(f)
    movieid = next(iter(movies.keys()))
    resp = requests.get(f"{API_BASE}/movie/{movieid}", timeout=10)
    assert resp.status_code == 200
    movie = resp.json()
    assert isinstance(movie, dict)
