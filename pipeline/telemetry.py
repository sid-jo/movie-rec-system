from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dtparser


def parse_timestamp(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        try:
            # Fast path: ISO-ish
            if s.endswith("Z"):
                return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                dt = dtparser.parse(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
    return None


@dataclass(frozen=True)
class TelemetryEvent:
    type: str
    user_id: str
    ts: datetime | None
    movie_id: str | None = None
    rating: float | None = None
    status: int | None = None
    recommendations: list[str] | None = None


def _parse_recs(recs: Any) -> list[str] | None:
    if recs is None:
        return None
    if isinstance(recs, list):
        return [str(x) for x in recs if str(x)]
    if isinstance(recs, str):
        parts = [p.strip() for p in recs.split(",")]
        return [p for p in parts if p]
    return None


def parsed_dict_to_event(obj: dict[str, Any]) -> TelemetryEvent | None:
    """Build a TelemetryEvent from a parsed Kafka/log dict (e.g. from kafka_parsing.parse_log_entry)."""
    t = obj.get("type")
    uid = obj.get("userid")
    if t is None or uid is None:
        return None
    return TelemetryEvent(
        type=str(t),
        user_id=str(uid),
        ts=parse_timestamp(obj.get("timestamp")),
        movie_id=str(obj["movieid"]) if obj.get("movieid") is not None else None,
        rating=float(obj["rating"]) if obj.get("rating") is not None and isinstance(obj.get("rating"), (int, float)) else None,
        status=int(obj["status"]) if isinstance(obj.get("status"), int) else None,
        recommendations=_parse_recs(obj.get("recommendations")),
    )


def load_events(raw_logs_dir: str, max_events: int | None = None) -> list[TelemetryEvent]:
    import glob

    files = sorted(glob.glob(os.path.join(raw_logs_dir, "*.jsonl")))
    out: list[TelemetryEvent] = []
    for fp in files:
        with open(fp) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type")
                uid = obj.get("userid")
                if t is None or uid is None:
                    continue
                ev = TelemetryEvent(
                    type=str(t),
                    user_id=str(uid),
                    ts=parse_timestamp(obj.get("timestamp")),
                    movie_id=str(obj.get("movieid")) if obj.get("movieid") is not None else None,
                    rating=float(obj["rating"]) if obj.get("rating") is not None and isinstance(obj.get("rating"), (int, float)) else None,
                    status=int(obj["status"]) if isinstance(obj.get("status"), int) else None,
                    recommendations=_parse_recs(obj.get("recommendations")),
                )
                out.append(ev)
                if max_events and len(out) >= max_events:
                    return out
    return out

