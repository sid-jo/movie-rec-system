from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class HttpClient(Protocol):
    def get(self, url: str, timeout: float | None = None) -> Any: ...


@dataclass(frozen=True)
class CourseApiClient:
    """
    Thin wrapper around the course-provided API (user/movie endpoints).

    Injectable `http` enables offline unit tests without network.
    """

    api_base: str
    http: HttpClient
    timeout_sec: float = 0.2

    def get_user(self, userid: str) -> dict[str, Any] | None:
        resp = self.http.get(f"{self.api_base}/user/{userid}", timeout=self.timeout_sec)
        if getattr(resp, "status_code", None) != 200:
            return None
        return resp.json()

    def get_movie(self, movieid: str) -> dict[str, Any] | None:
        resp = self.http.get(f"{self.api_base}/movie/{movieid}", timeout=self.timeout_sec)
        if getattr(resp, "status_code", None) != 200:
            return None
        return resp.json()

