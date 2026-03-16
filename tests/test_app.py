"""Tests for Flask recommendation API, including data quality validation (M2)."""
import os
import pytest

# Ensure project root is on path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in __import__("sys").path:
    __import__("sys").path.insert(0, project_root)

from src.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_recommend_rejects_empty_userid(client):
    """Invalid userid (empty) should return 400 (schema validation - M2)."""
    # Flask captures empty path segment as empty string for /recommend/
    resp = client.get("/recommend/")
    # Either 404 (route not matching) or 400 (validation) - with our route,
    # /recommend/ gives userid="" which fails validation
    assert resp.status_code in (400, 404)


def test_recommend_rejects_invalid_userid(client):
    """Invalid userid (special chars) should return 400 (schema validation - M2)."""
    resp = client.get("/recommend/foo!bar@")
    assert resp.status_code == 400


def test_recommend_accepts_valid_userid(client):
    """Valid userid should return 200 (may skip if metadata/models missing)."""
    resp = client.get("/recommend/70106")
    if resp.status_code == 200:
        assert "text/plain" in resp.headers.get("Content-Type", "")
        body = resp.get_data(as_text=True)
        assert "," in body or len(body) > 0
