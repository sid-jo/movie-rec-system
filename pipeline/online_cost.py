from __future__ import annotations

import argparse
import json
import os
from typing import Any
from datetime import timedelta

from pipeline.paths import default_paths
from pipeline.telemetry import load_events


def run(raw_logs_dir: str, metadata_dir: str, output_path: str) -> dict[str, Any]:
    """
    Online cost evaluation computed from telemetry + `metadata/movies.json` cost field.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    movies_path = os.path.join(metadata_dir, "movies.json")
    cost_by_mid: dict[str, float] = {}
    if os.path.exists(movies_path):
        with open(movies_path) as f:
            movies = json.load(f)
        if isinstance(movies, dict):
            for mid, m in movies.items():
                if isinstance(m, dict) and isinstance(m.get("cost"), (int, float)):
                    cost_by_mid[str(mid)] = float(m["cost"])

    events = load_events(raw_logs_dir)
    rec_events = [e for e in events if e.type == "recommendation" and e.status == 200 and e.recommendations and e.ts]
    watch_events = [e for e in events if e.type == "watch" and e.movie_id and e.ts]

    rec_by_user: dict[str, list[tuple[Any, list[str]]]] = {}
    for e in rec_events:
        rec_by_user.setdefault(e.user_id, []).append((e.ts, e.recommendations or []))
    for uid in rec_by_user:
        rec_by_user[uid].sort(key=lambda x: x[0])

    window = timedelta(days=7)
    attributed_watches = 0
    attributed_cost = 0.0
    total_watches = 0

    watch_by_user: dict[str, list[Any]] = {}
    for w in watch_events:
        watch_by_user.setdefault(w.user_id, []).append(w)
    for uid in watch_by_user:
        watch_by_user[uid].sort(key=lambda e: e.ts)

    for uid, watches in watch_by_user.items():
        recs = rec_by_user.get(uid, [])
        if not recs:
            total_watches += len(watches)
            continue
        for w in watches:
            total_watches += 1
            # Find most recent recommendation before this watch within window
            best = None
            for ts, mids in reversed(recs):
                if ts is None or w.ts is None:
                    continue
                if ts > w.ts:
                    continue
                if w.ts - ts > window:
                    break
                best = (ts, mids)
                break
            if best is None:
                continue
            mids = best[1][:20]
            if w.movie_id in set(mids):
                attributed_watches += 1
                attributed_cost += float(cost_by_mid.get(w.movie_id, 0.0))

    result = {
        "evaluation_type": "online_cost",
        "status": "ok",
        "raw_logs_dir": os.path.abspath(raw_logs_dir),
        "metadata_dir": os.path.abspath(metadata_dir),
        "window_days": 7,
        "llm_tokens": 0,
        "counts": {
            "recommendation_events_200": len(rec_events),
            "watch_events": len(watch_events),
            "attributed_watches": int(attributed_watches),
        },
        "metrics": {
            "attributed_license_cost_total_usd": float(attributed_cost),
            "expected_cost_per_attributed_watch_usd": float(attributed_cost / attributed_watches) if attributed_watches else 0.0,
            "attributed_watch_rate": float(attributed_watches / total_watches) if total_watches else 0.0,
        },
        "notes": [
            "A watch is attributed if the watched movie appears in the user's most recent recommendation list within 7 days.",
            "If movie cost is missing in metadata, cost is treated as 0 for that watch.",
        ],
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Online cost eval → JSON")
    p.add_argument("--raw-logs-dir", default=None)
    p.add_argument("--metadata-dir", default=None)
    p.add_argument("--output", default=None, help="Path to write online_cost.json")
    args = p.parse_args(argv)

    paths = default_paths()
    raw_dir = args.raw_logs_dir or paths.data_raw_logs
    md_dir = args.metadata_dir or paths.metadata_dir
    out = args.output or os.path.join(paths.reports_dir, "online_cost.json")
    res = run(raw_logs_dir=raw_dir, metadata_dir=md_dir, output_path=out)
    print(f"wrote {out} (status={res['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

