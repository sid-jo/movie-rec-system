"""
Pytest fixtures for movie recommendation pipeline tests.
"""
import os
import tempfile
import pytest


@pytest.fixture
def project_root():
    """Project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tmpdir_fixture():
    """Temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_raw_log_lines():
    """Sample raw Kafka log lines (timestamp,userid,action format)."""
    return [
        "2025-12-25T03:20:08,50451,GET /data/m/superman+1978/0.mpg",
        "2025-12-25T03:22:05,50451,GET /rate/superman+1978=8",
        "2025-12-25T03:24:10,50451,recommendation request status 200 result: [movie1,movie2]",
        "2025-12-25T03:25:00,50451,create_account",
    ]


@pytest.fixture
def sample_jsonl_events():
    """Sample JSONL events (as in raw_logs from GCS)."""
    return [
        {"type": "watch", "userid": "u1", "movieid": "m1", "minute": 5, "timestamp": "2025-01-01T00:00:00"},
        {"type": "rating", "userid": "u1", "movieid": "m1", "rating": 8, "timestamp": "2025-01-01T00:01:00"},
        {"type": "recommendation", "userid": "u1", "status": 200, "timestamp": "2025-01-01T00:02:00"},
        {"type": "signup", "userid": "u2", "timestamp": "2025-01-01T00:03:00"},
    ]


@pytest.fixture
def sample_metadata(tmpdir_fixture):
    """Create minimal users.json and movies.json in a temp dir."""
    users = {"u1": {"userid": "u1"}, "u2": {"userid": "u2"}}
    movies = {
        "m1": {"id": "m1", "title": "Movie One", "genres": [{"name": "Drama"}]},
        "m2": {"id": "m2", "title": "Movie Two", "genres": [{"name": "Comedy"}]},
    }
    users_path = os.path.join(tmpdir_fixture, "users.json")
    movies_path = os.path.join(tmpdir_fixture, "movies.json")
    import json
    with open(users_path, "w") as f:
        json.dump(users, f)
    with open(movies_path, "w") as f:
        json.dump(movies, f)
    return {"users": users_path, "movies": movies_path, "dir": tmpdir_fixture}
