from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ValidationIssue:
    source: str
    message: str
    severity: str = "error"  # error | warning
    context: dict[str, Any] | None = None


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_kafka_event(obj: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    t = obj.get("type")
    if t not in {"rating", "watch", "recommendation", "signup"}:
        issues.append(ValidationIssue("kafka", f"unknown type={t!r}", context={"type": t}))
        return issues

    if not obj.get("timestamp"):
        issues.append(ValidationIssue("kafka", "missing timestamp"))
    if "userid" not in obj or obj.get("userid") in (None, ""):
        issues.append(ValidationIssue("kafka", "missing userid"))

    if t == "rating":
        if not obj.get("movieid"):
            issues.append(ValidationIssue("kafka", "rating missing movieid"))
        if "rating" not in obj or not _is_number(obj.get("rating")):
            issues.append(ValidationIssue("kafka", "rating missing/invalid rating"))
    elif t == "watch":
        if not obj.get("movieid"):
            issues.append(ValidationIssue("kafka", "watch missing movieid"))
        if "minute" in obj and not isinstance(obj.get("minute"), int):
            issues.append(ValidationIssue("kafka", "watch minute should be int", severity="warning"))
    elif t == "recommendation":
        status = obj.get("status")
        if status is None or not isinstance(status, int):
            issues.append(ValidationIssue("kafka", "recommendation missing/invalid status"))
        recs = obj.get("recommendations")
        if status == 200 and recs is None:
            issues.append(ValidationIssue("kafka", "status=200 but recommendations missing", severity="warning"))
    elif t == "signup":
        # nothing else required
        pass

    return issues


def validate_course_user(user: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "user_id" not in user:
        issues.append(ValidationIssue("course_api.user", "missing user_id"))
    if "age" in user and user["age"] is not None and not isinstance(user["age"], int):
        issues.append(ValidationIssue("course_api.user", "age should be int", severity="warning"))
    if "gender" in user and user["gender"] is not None and not isinstance(user["gender"], str):
        issues.append(ValidationIssue("course_api.user", "gender should be str", severity="warning"))
    # Optional self-description fields used for cold start
    for k in ("self_description_likes", "self_description_dislikes"):
        if k in user and user[k] is not None and not isinstance(user[k], str):
            issues.append(ValidationIssue("course_api.user", f"{k} should be str", severity="warning"))
    return issues


def validate_course_movie(movie: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if "id" not in movie and "movie_id" not in movie:
        issues.append(ValidationIssue("course_api.movie", "missing id/movie_id"))
    if "cost" in movie and movie["cost"] is not None and not _is_number(movie["cost"]):
        issues.append(ValidationIssue("course_api.movie", "cost should be number", severity="warning"))
    return issues


_MOVIE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+\\-]*$")


def validate_recommend_response_text(text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if text is None:
        return [ValidationIssue("recommend_api", "response is None")]
    if not isinstance(text, str):
        return [ValidationIssue("recommend_api", "response is not text/plain", context={"type": str(type(text))})]
    if "\\n" in text:
        issues.append(ValidationIssue("recommend_api", "response contains newline"))

    parts = [p for p in text.strip().split(",") if p != ""]
    if not parts:
        issues.append(ValidationIssue("recommend_api", "no movie ids returned", severity="warning"))
        return issues
    if len(parts) > 20:
        issues.append(ValidationIssue("recommend_api", f"returned {len(parts)} ids > 20"))
    for mid in parts[:50]:
        if not _MOVIE_ID_RE.match(mid):
            issues.append(ValidationIssue("recommend_api", f"invalid movie id token: {mid!r}"))
    return issues


def summarize_issues(issues: Iterable[ValidationIssue]) -> dict[str, Any]:
    issues = list(issues)
    return {
        "errors": [i.__dict__ for i in issues if i.severity == "error"],
        "warnings": [i.__dict__ for i in issues if i.severity != "error"],
        "error_count": sum(1 for i in issues if i.severity == "error"),
        "warning_count": sum(1 for i in issues if i.severity != "error"),
    }

