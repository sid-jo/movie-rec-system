"""
Parse Kafka log lines into structured events.
Used by Kafka consumers; raw_logs JSONL files are already in this format.
"""
import json
import re
from typing import Optional


def parse_log_line(log_line: str) -> Optional[dict]:
    """
    Parse a raw Kafka log line (timestamp,userid,action) into a structured event dict.
    Returns None for malformed lines.

    Raw format: "2025-12-25T03:20:08,50451,GET /data/m/superman+1978/0.mpg"
    """
    if not log_line or not isinstance(log_line, str) or not log_line.strip():
        return None

    parts = log_line.split(",", 2)
    if len(parts) < 3:
        return None

    timestamp = parts[0].strip()
    userid = parts[1].strip()
    action = parts[2].strip()

    if not timestamp or not userid:
        return None

    entry: dict = {
        "timestamp": timestamp,
        "userid": userid,
        "raw": log_line,
    }

    # Recommendation request
    if "recommendation request" in action:
        match = re.search(r"status (\d+)", action)
        if match:
            entry["type"] = "recommendation"
            entry["status"] = int(match.group(1))
            result_match = re.search(r"result: \[(.*?)\]", action)
            if result_match:
                entry["recommendations"] = result_match.group(1)
            return entry
        return None

    # Movie watching
    if "/data/m/" in action:
        match = re.search(r"/data/m/([^/]+)/(\d+)\.mpg", action)
        if match:
            entry["type"] = "watch"
            entry["movieid"] = match.group(1)
            entry["minute"] = int(match.group(2))
            return entry
        return None

    # Rating
    if "/rate/" in action:
        match = re.search(r"/rate/(.+)=(\d+)", action)
        if match:
            entry["type"] = "rating"
            entry["movieid"] = match.group(1)
            entry["rating"] = int(match.group(2))
            return entry
        return None

    # New account
    if "create_account" in action:
        entry["type"] = "signup"
        return entry

    return None


def parse_json_event(line: str) -> Optional[dict]:
    """
    Parse a JSONL line (already in structured format from GCS raw_logs).
    Returns the dict if valid JSON, None otherwise.
    """
    if not line or not line.strip():
        return None
    try:
        return json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
