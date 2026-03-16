"""
Telemetry for online evaluation: log recommendations, latency, and costs.
Writes to logs/telemetry.jsonl (non-blocking).
"""
import json
import os
import threading
from datetime import datetime, timezone
from typing import List, Optional


LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "telemetry.jsonl")
_lock = threading.Lock()


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_recommendation(
    userid: str,
    recommendations: List[str],
    latency_ms: float,
    movie_costs: Optional[float] = None,
    llm_tokens: Optional[int] = None,
):
    """
    Log a recommendation event for online evaluation.
    Non-blocking: writes in a background thread.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "userid": userid,
        "recommendations": recommendations,
        "latency_ms": round(latency_ms, 2),
        "movie_license_cost_usd": round(movie_costs, 4) if movie_costs is not None else 0,
        "llm_tokens": llm_tokens,
    }

    def _write():
        try:
            _ensure_log_dir()
            with _lock:
                with open(LOG_FILE, "a") as f:
                    f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    t = threading.Thread(target=_write, daemon=True)
    t.start()


def get_movie_costs(recommendations, movies_metadata):
    """Sum license cost (USD) for recommended movies. Uses cost field; 0 if missing."""
    total = 0.0
    for mid in recommendations:
        m = movies_metadata.get(mid)
        if isinstance(m, dict):
            c = m.get("cost")
            if isinstance(c, (int, float)):
                total += float(c)
    return total
