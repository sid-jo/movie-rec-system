import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients import CourseApiClient


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, timeout=None):
        return self.mapping.get(url, _FakeResp(404, {}))


def test_course_api_client_get_user_ok():
    http = _FakeHttp({"http://api/user/123": _FakeResp(200, {"user_id": "123"})})
    client = CourseApiClient(api_base="http://api", http=http, timeout_sec=0.01)
    assert client.get_user("123") == {"user_id": "123"}


def test_course_api_client_get_user_not_found():
    http = _FakeHttp({})
    client = CourseApiClient(api_base="http://api", http=http)
    assert client.get_user("123") is None

