from __future__ import annotations

import re
from typing import Any


def parse_log_entry(log_line: str) -> dict[str, Any] | None:
    """
    Parse raw Kafka movielog line into a structured dict.

    Expected raw format:
      <timestamp>,<userid>,<action...>
    """
    parts = log_line.split(",", 2)
    if len(parts) < 3:
        return None

    timestamp, userid, action = parts[0], parts[1], parts[2]
    entry: dict[str, Any] = {"timestamp": timestamp, "userid": userid, "raw": log_line}

    if "recommendation request" in action:
        match = re.search(r"status (\d+)", action)
        if not match:
            return None
        entry["type"] = "recommendation"
        entry["status"] = int(match.group(1))
        result_match = re.search(r"result: \\[(.*?)\\]", action)
        if result_match:
            entry["recommendations"] = result_match.group(1)
        return entry

    if "/data/m/" in action:
        match = re.search(r"/data/m/([^/]+)/(\d+)\\.mpg", action)
        if not match:
            return None
        entry["type"] = "watch"
        entry["movieid"] = match.group(1)
        entry["minute"] = int(match.group(2))
        return entry

    if "/rate/" in action:
        match = re.search(r"/rate/(.+)=(\d+)", action)
        if not match:
            return None
        entry["type"] = "rating"
        entry["movieid"] = match.group(1)
        entry["rating"] = int(match.group(2))
        return entry

    if "create_account" in action:
        entry["type"] = "signup"
        return entry

    return None

