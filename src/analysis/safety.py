"""
Safety analysis helpers for Milestone 4.

Focuses on a concrete telemetry-backed safety concern that is measurable with
the artifacts already present in the repository: minors receiving adult titles
in recommendation lists.
"""
from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator


def load_users(path: str = "metadata/users.json") -> dict:
    with open(path) as handle:
        return json.load(handle)


def load_movies(path: str = "metadata/movies.json") -> dict:
    with open(path) as handle:
        return json.load(handle)


def iter_rec_events(rec_log_dir: str) -> Iterator[dict]:
    """Yield normalized recommendation events from experiment JSONL files."""
    for file_path in sorted(glob.glob(os.path.join(rec_log_dir, "*.jsonl"))):
        with open(file_path) as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                recs = obj.get("recommendations")
                user_id = obj.get("user_id") or obj.get("userid")
                if not user_id or not isinstance(recs, list):
                    continue
                yield {
                    "timestamp": obj.get("timestamp"),
                    "user_id": str(user_id),
                    "variant": obj.get("variant") or "unknown",
                    "experiment_id": obj.get("experiment_id") or "unknown",
                    "recommendations": [str(movie_id) for movie_id in recs if movie_id],
                    "source_file": os.path.basename(file_path),
                }


def iter_watch_events(watch_log_dir: str | None) -> Iterator[dict]:
    """Yield normalized watch events from raw-log JSONL shards when available."""
    if not watch_log_dir or not os.path.isdir(watch_log_dir):
        return
    for file_path in sorted(glob.glob(os.path.join(watch_log_dir, "*.jsonl"))):
        with open(file_path) as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "watch":
                    continue
                user_id = obj.get("userid") or obj.get("user_id")
                movie_id = obj.get("movieid") or obj.get("movie_id")
                if not user_id or not movie_id:
                    continue
                yield {
                    "timestamp": obj.get("timestamp"),
                    "user_id": str(user_id),
                    "movie_id": str(movie_id),
                }


def parse_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        if normalized.endswith("Z"):
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


@dataclass
class ExposureRecord:
    user_id: str
    age: int
    experiment_id: str
    variant: str
    adult_titles: list[str]
    recommendations: list[str]
    timestamp: str | None
    watched_later: bool | None = None


def build_minor_adult_exposures(rec_events: Iterator[dict], users: dict, movies: dict) -> list[ExposureRecord]:
    """Return one record per under-18 recommendation event with adult-title exposure details."""
    exposures: list[ExposureRecord] = []
    for event in rec_events:
        user = users.get(event["user_id"])
        if not isinstance(user, dict):
            continue
        age = user.get("age")
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            continue
        if age_int >= 18:
            continue
        adult_titles = []
        for movie_id in event["recommendations"]:
            movie = movies.get(movie_id)
            if isinstance(movie, dict) and bool(movie.get("adult")):
                adult_titles.append(movie_id)
        exposures.append(
            ExposureRecord(
                user_id=event["user_id"],
                age=age_int,
                experiment_id=event["experiment_id"],
                variant=event["variant"],
                adult_titles=adult_titles,
                recommendations=event["recommendations"],
                timestamp=event.get("timestamp"),
            )
        )
    return exposures


def annotate_watch_followthrough(exposures: list[ExposureRecord], watch_events: Iterator[dict]) -> None:
    """Mark whether exposed adult titles were later watched by the same user.

    If timestamps are present and parseable, only count watches at or after the
    recommendation event. Otherwise any matching watch event counts as evidence
    of later watch in the available telemetry window.
    """
    exposure_lookup: dict[tuple[str, str], list[ExposureRecord]] = defaultdict(list)
    for exposure in exposures:
        for movie_id in exposure.adult_titles:
            exposure_lookup[(exposure.user_id, movie_id)].append(exposure)

    if not exposure_lookup:
        return

    for exposure in exposures:
        if exposure.adult_titles:
            exposure.watched_later = False

    for watch_event in watch_events:
        key = (watch_event["user_id"], watch_event["movie_id"])
        matched = exposure_lookup.get(key)
        if not matched:
            continue
        watch_ts = parse_timestamp(watch_event.get("timestamp"))
        for exposure in matched:
            if exposure.watched_later is True:
                continue
            exposure_ts = parse_timestamp(exposure.timestamp)
            if exposure_ts and watch_ts and watch_ts < exposure_ts:
                continue
            exposure.watched_later = True


def summarize_minor_safety(exposures: list[ExposureRecord]) -> dict:
    total_events = len(exposures)
    total_titles = sum(len(exposure.recommendations) for exposure in exposures)
    exposed_events = [exposure for exposure in exposures if exposure.adult_titles]
    adult_titles_shown = sum(len(exposure.adult_titles) for exposure in exposures)
    minor_users = sorted({exposure.user_id for exposure in exposures})

    variant_breakdown: dict[str, dict] = {}
    for exposure in exposures:
        bucket = variant_breakdown.setdefault(
            exposure.variant,
            {
                "recommendation_events": 0,
                "events_with_adult_titles": 0,
                "recommended_titles": 0,
                "adult_titles": 0,
            },
        )
        bucket["recommendation_events"] += 1
        bucket["recommended_titles"] += len(exposure.recommendations)
        bucket["adult_titles"] += len(exposure.adult_titles)
        if exposure.adult_titles:
            bucket["events_with_adult_titles"] += 1

    for bucket in variant_breakdown.values():
        bucket["adult_recommendation_rate"] = safe_div(
            bucket["events_with_adult_titles"], bucket["recommendation_events"]
        )
        bucket["adult_title_share"] = safe_div(
            bucket["adult_titles"], bucket["recommended_titles"]
        )

    watched_candidates = [exposure for exposure in exposed_events if exposure.watched_later is not None]
    watched_positive = [exposure for exposure in watched_candidates if exposure.watched_later]

    if not exposures:
        conclusion = "insufficient_minor_telemetry"
    elif exposed_events:
        conclusion = "evidence_of_harm"
    else:
        conclusion = "no_observed_harm_in_sample"

    top_examples = []
    for exposure in exposed_events[:10]:
        top_examples.append(
            {
                "user_id": exposure.user_id,
                "age": exposure.age,
                "experiment_id": exposure.experiment_id,
                "variant": exposure.variant,
                "adult_titles": exposure.adult_titles,
                "recommendation_count": len(exposure.recommendations),
                "watched_later": exposure.watched_later,
            }
        )

    return {
        "minor_user_count": len(minor_users),
        "recommendation_events_analyzed": total_events,
        "recommended_titles_analyzed": total_titles,
        "events_with_adult_titles": len(exposed_events),
        "adult_titles_shown": adult_titles_shown,
        "minor_adult_recommendation_rate": safe_div(len(exposed_events), total_events),
        "minor_adult_title_share": safe_div(adult_titles_shown, total_titles),
        "minor_adult_watch_rate": safe_div(len(watched_positive), len(watched_candidates)),
        "watch_followthrough_observation_count": len(watched_candidates),
        "variant_breakdown": variant_breakdown,
        "conclusion": conclusion,
        "example_exposures": top_examples,
    }


def safe_div(num: int, den: int) -> float | None:
    if not den:
        return None
    return num / den