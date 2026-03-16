"""Tests for Flask recommendation API."""
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_app_home():
    """Test / returns 200 and info message."""
    from src.app import app
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"recommend" in resp.data.lower() or b"active" in resp.data.lower()


def test_app_recommend_format():
    """Test /recommend/<userid> returns comma-separated movie IDs, 1-20 items."""
    from src.app import app
    client = app.test_client()
    resp = client.get("/recommend/70106")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "\n" not in body.strip()
    parts = body.strip().split(",")
    if body.strip():
        assert 1 <= len(parts) <= 20
        for p in parts:
            assert p.strip()
            assert "70106" not in p  # no userid in response
