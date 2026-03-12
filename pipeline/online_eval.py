from __future__ import annotations

import argparse
import json
import os
from typing import Any
from datetime import timedelta

from pipeline.paths import default_paths
from pipeline.telemetry import load_events


def run(raw_logs_dir: str, output_path: str) -> dict[str, Any]:
    """
    Online evaluation (accuracy proxy) computed from production telemetry.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    events = load_events(raw_logs_dir)
    # Consider only recommendation events that were successfully served
    rec_events = [e for e in events if e.type == "recommendation" and e.status == 200 and e.recommendations and e.ts]
    watch_events = [e for e in events if e.type == "watch" and e.movie_id and e.ts]
    rating_events = [e for e in events if e.type == "rating" and e.movie_id and e.ts and e.rating is not None]

    # Index recommendation windows by user (sorted)
    rec_by_user: dict[str, list[tuple[Any, list[str]]]] = {}
    for e in rec_events:
        rec_by_user.setdefault(e.user_id, []).append((e.ts, e.recommendations or []))
    for uid in rec_by_user:
        rec_by_user[uid].sort(key=lambda x: x[0])

    window = timedelta(days=7)
    positive_threshold = 4.0  # "liked" threshold on 1–5

    def _attributed_hits(events_list, kind: str) -> tuple[int, int]:
        # returns (attributed_hits, total_recs_considered)
        hits = 0
        total = 0
        # For each rec event, check if any matching event occurs later in window.
        by_user: dict[str, list[Any]] = {}
        for ev in events_list:
            by_user.setdefault(ev.user_id, []).append(ev)
        for uid, recs in rec_by_user.items():
            user_ev = by_user.get(uid, [])
            user_ev.sort(key=lambda e: e.ts)
            for ts, mids in recs:
                if not mids:
                    continue
                total += min(20, len(mids))
                end = ts + window
                midset = set(mids[:20])
                for ev in user_ev:
                    if ev.ts < ts:
                        continue
                    if ev.ts > end:
                        break
                    if kind == "watch":
                        if ev.movie_id in midset:
                            hits += 1
                    elif kind == "rating_pos":
                        if ev.movie_id in midset and (ev.rating or 0) >= positive_threshold:
                            hits += 1
        return hits, total

    watch_hits, total_recs = _attributed_hits(watch_events, "watch")
    rating_hits, total_recs2 = _attributed_hits(rating_events, "rating_pos")
    total_recs = max(total_recs, total_recs2)

    result = {
        "evaluation_type": "online_accuracy_proxy",
        "status": "ok",
        "raw_logs_dir": os.path.abspath(raw_logs_dir),
        "window_days": 7,
        "positive_rating_threshold": positive_threshold,
        "counts": {
            "recommendation_events_200": len(rec_events),
            "watch_events": len(watch_events),
            "rating_events": len(rating_events),
            "recommendations_considered": int(total_recs),
        },
        "metrics": {
            "watch_through_rate": float(watch_hits / total_recs) if total_recs else 0.0,
            "positive_rating_rate": float(rating_hits / total_recs) if total_recs else 0.0,
        },
        "llm_tokens": 0,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Online evaluation (accuracy proxy) → JSON")
    p.add_argument("--raw-logs-dir", default=None, help="Directory of raw log jsonl files")
    p.add_argument("--output", default=None, help="Path to write online_eval.json")
    args = p.parse_args(argv)

    paths = default_paths()
    raw_dir = args.raw_logs_dir or paths.data_raw_logs
    out = args.output or os.path.join(paths.reports_dir, "online_eval.json")
    res = run(raw_logs_dir=raw_dir, output_path=out)
    print(f"wrote {out} (status={res['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

