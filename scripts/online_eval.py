#!/usr/bin/env python3
"""
Online evaluation: compute model accuracy and cost metrics from live Kafka stream.
Consumes from the movielog2 topic, tracks recommendation→watch/rating conversions,
and reports Watch-Through Rate, Positive-Rating Rate, and licensing cost in real time.

Usage:
  1. Start SSH tunnel: ssh -L 9092:localhost:9092 <vm-host>
  2. Run: python scripts/online_eval.py [--duration 300] [--bootstrap localhost:9092]
"""
import os
import re
import json
import time
import argparse
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")

POSITIVE_RATING_THRESHOLD = 4.0
WINDOW_DAYS = 7


def load_movie_metadata():
    path = os.path.join(METADATA_DIR, "movies.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def parse_kafka_line(log_line: str) -> dict | None:
    """Parse a raw Kafka CSV log line into a structured event dict.
    Format: timestamp,userid,action
    """
    parts = log_line.split(",", 2)
    if len(parts) < 3:
        return None

    timestamp, userid, action = parts[0].strip(), parts[1].strip(), parts[2].strip()

    if "recommendation request" in action:
        status_match = re.search(r"status (\d+)", action)
        result_match = re.search(r"result: \[?(.*)", action)
        if status_match:
            movies_str = ""
            if result_match:
                movies_str = result_match.group(1).rstrip("]").strip()
            return {
                "type": "recommendation",
                "timestamp": timestamp,
                "userid": userid,
                "status": int(status_match.group(1)),
                "movies": movies_str,
            }

    elif "/data/m/" in action:
        match = re.search(r"/data/m/([^/]+)/(\d+)\.mpg", action)
        if match:
            return {
                "type": "watch",
                "timestamp": timestamp,
                "userid": userid,
                "movieid": match.group(1),
                "minute": int(match.group(2)),
            }

    elif "/rate/" in action:
        match = re.search(r"/rate/(.+)=(\d+)", action)
        if match:
            return {
                "type": "rating",
                "timestamp": timestamp,
                "userid": userid,
                "movieid": match.group(1),
                "rating": int(match.group(2)),
            }

    return None


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_accuracy_metrics(user_recs: dict, user_watches: dict, user_ratings: dict) -> dict:
    """
    Online accuracy metrics: Watch-Through Rate and Positive-Rating Rate.

    1. Metric: (a) WTR — fraction of recommended movies the user watched,
       (b) Positive-rating rate — fraction rated >= 4.0.
    2. Telemetry: recommendation events (userid + movie list), watch events
       (userid + movieid), and rating events (userid + movieid + rating)
       from the Kafka movielog2 stream.
    3. Operationalization: for each recommendation event, check how many
       recommended movies appear in the user's watch/rating events within
       the collection window. Rates = hits / total recommended slots.
    """
    total_recommended = 0
    total_watched = 0
    total_positive_rated = 0
    sample_size = 0

    for uid, rec_sets in user_recs.items():
        watched = user_watches.get(uid, set())
        rated = user_ratings.get(uid, {})
        for rec_movies in rec_sets:
            watch_hits = sum(1 for m in rec_movies if m in watched)
            rating_hits = sum(1 for m in rec_movies
                              if rated.get(m, 0) >= POSITIVE_RATING_THRESHOLD)
            total_recommended += len(rec_movies)
            total_watched += watch_hits
            total_positive_rated += rating_hits
            sample_size += 1

    wtr = total_watched / total_recommended if total_recommended > 0 else 0.0
    prr = total_positive_rated / total_recommended if total_recommended > 0 else 0.0
    return {
        "watch_through_rate": round(wtr, 6),
        "positive_rating_rate": round(prr, 6),
        "total_recs_served": total_recommended,
        "total_watched": total_watched,
        "total_positive_rated": total_positive_rated,
        "recommendations_considered": sample_size,
    }


def compute_cost_metrics(watch_events: list, movies_metadata: dict,
                         total_rec_requests: int,
                         user_recs: dict = None, user_watches: dict = None) -> dict:
    """
    Online cost metric: licensing cost + LLM token cost.

    1. Metric: total movie licensing cost (sum of per-view cost from movie
       metadata) plus any LLM API token cost.
    2. Telemetry: watch events (userid, movieid) from Kafka, and the
       license_cost field in the movie metadata JSON (USD per view).
    3. Operationalization: for each watch event, look up movie cost and sum.
       Additionally, compute the cost attributed to recommendations only
       (movies that were both recommended AND watched).
       LLM cost is tracked separately (currently $0 — no LLM in pipeline).
    """

    def _movie_cost(mid):
        info = movies_metadata.get(mid, {})
        if isinstance(info, dict):
            return info.get("license_cost") or info.get("cost") or 0.0
        return 0.0

    total_license_cost = 0.0
    views_with_cost = 0
    views_missing_cost = 0

    for event in watch_events:
        mid = event.get("movieid", "")
        c = _movie_cost(mid)
        if c > 0:
            total_license_cost += c
            views_with_cost += 1
        else:
            views_missing_cost += 1

    rec_attributed_cost = 0.0
    rec_attributed_views = 0
    if user_recs and user_watches:
        for uid, rec_sets in user_recs.items():
            watched = user_watches.get(uid, set())
            for rec_movies in rec_sets:
                for mid in rec_movies:
                    if mid in watched:
                        c = _movie_cost(mid)
                        rec_attributed_cost += c
                        rec_attributed_views += 1

    total_views = len(watch_events)
    llm_cost = 0.0

    return {
        "total_license_cost_usd": round(total_license_cost, 2),
        "total_views": total_views,
        "views_with_cost_data": views_with_cost,
        "views_missing_cost_data": views_missing_cost,
        "per_view_license_cost_usd": round(total_license_cost / total_views, 4) if total_views else 0.0,
        "rec_attributed_cost_usd": round(rec_attributed_cost, 2),
        "rec_attributed_views": rec_attributed_views,
        "per_rec_attributed_view_cost_usd": round(rec_attributed_cost / rec_attributed_views, 4) if rec_attributed_views else 0.0,
        "per_recommendation_cost_usd": round(rec_attributed_cost / total_rec_requests, 4) if total_rec_requests else 0.0,
        "total_rec_requests": total_rec_requests,
        "llm_token_cost_usd": llm_cost,
        "total_cost_usd": round(total_license_cost + llm_cost, 2),
    }


# ---------------------------------------------------------------------------
# Kafka consumer loop
# ---------------------------------------------------------------------------

def run_online_eval(bootstrap_servers: str, duration_sec: int, report_interval: int = 30):
    """Connect to Kafka and compute online metrics from live stream."""
    from kafka import KafkaConsumer

    movies_metadata = load_movie_metadata()
    print(f"Loaded {len(movies_metadata)} movies with metadata")

    print(f"\nConnecting to Kafka at {bootstrap_servers} ...")
    consumer = KafkaConsumer(
        "movielog2",
        bootstrap_servers=[bootstrap_servers],
        auto_offset_reset="latest",
        enable_auto_commit=True,
        group_id="team2-online-eval",
        consumer_timeout_ms=5000,
        value_deserializer=lambda x: x.decode("utf-8"),
    )
    print("Connected. Consuming messages...\n")

    user_recs = defaultdict(list)       # uid -> list of [movie_id, ...]
    user_watches = defaultdict(set)     # uid -> set of movie_ids watched
    user_ratings = defaultdict(dict)    # uid -> {movie_id: rating}
    watch_events = []
    rating_events = []
    rec_request_count = 0
    msg_count = 0
    start_time = time.time()
    last_report = start_time

    try:
        while True:
            elapsed = time.time() - start_time
            if duration_sec and elapsed >= duration_sec:
                print(f"\nDuration limit reached ({duration_sec}s).")
                break

            msg_pack = consumer.poll(timeout_ms=2000)
            for tp, messages in msg_pack.items():
                for message in messages:
                    raw = message.value
                    event = parse_kafka_line(raw)
                    if not event:
                        continue
                    msg_count += 1

                    etype = event.get("type")
                    uid = event.get("userid", "")

                    if etype == "recommendation":
                        rec_request_count += 1
                        movies_str = event.get("movies", "")
                        if movies_str:
                            rec_list = [m.strip().strip("'\" ") for m in movies_str.split(",") if m.strip()]
                            if rec_list:
                                user_recs[uid].append(rec_list)

                    elif etype == "watch":
                        mid = event.get("movieid", "")
                        if mid:
                            user_watches[uid].add(mid)
                            watch_events.append(event)

                    elif etype == "rating":
                        mid = event.get("movieid", "")
                        rating_val = event.get("rating", 0)
                        if mid and rating_val:
                            user_ratings[uid][mid] = rating_val
                        rating_events.append(event)

            now = time.time()
            if now - last_report >= report_interval:
                last_report = now
                _print_report(msg_count, rec_request_count, user_recs, user_watches,
                              user_ratings, watch_events, rating_events, movies_metadata, elapsed)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        consumer.close()

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("FINAL ONLINE EVALUATION RESULTS")
    print("=" * 60)
    _print_report(msg_count, rec_request_count, user_recs, user_watches,
                  user_ratings, watch_events, rating_events, movies_metadata, elapsed)

    accuracy = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
    cost = compute_cost_metrics(watch_events, movies_metadata, rec_request_count,
                                user_recs=user_recs, user_watches=user_watches)
    results = {
        "evaluation_type": "online_accuracy_proxy",
        "status": "ok",
        "window_days": WINDOW_DAYS,
        "positive_rating_threshold": POSITIVE_RATING_THRESHOLD,
        "counts": {
            "recommendation_events_200": rec_request_count,
            "watch_events": len(watch_events),
            "rating_events": len(rating_events),
            "recommendations_considered": accuracy["recommendations_considered"],
        },
        "metrics": {
            "watch_through_rate": accuracy["watch_through_rate"],
            "positive_rating_rate": accuracy["positive_rating_rate"],
        },
        "cost": {
            "total_license_cost_usd": cost["total_license_cost_usd"],
            "per_view_license_cost_usd": cost["per_view_license_cost_usd"],
            "rec_attributed_cost_usd": cost["rec_attributed_cost_usd"],
            "rec_attributed_views": cost["rec_attributed_views"],
            "per_rec_attributed_view_cost_usd": cost["per_rec_attributed_view_cost_usd"],
            "per_recommendation_cost_usd": cost["per_recommendation_cost_usd"],
            "total_views": cost["total_views"],
        },
        "llm_tokens": 0,
        "collection_duration_sec": round(elapsed, 1),
        "collected_at": datetime.now().isoformat(),
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, "online_eval_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")
    return results


def _print_report(msg_count, rec_count, user_recs, user_watches,
                  user_ratings, watch_events, rating_events, movies_metadata, elapsed):
    acc = compute_accuracy_metrics(user_recs, user_watches, user_ratings)
    cost = compute_cost_metrics(watch_events, movies_metadata, rec_count,
                                user_recs=user_recs, user_watches=user_watches)

    print(f"--- Report @ {elapsed:.0f}s | {msg_count} messages parsed ---")
    print(f"  Recommendation events:  {rec_count}")
    print(f"  Watch events:           {len(watch_events)}")
    print(f"  Rating events:          {len(rating_events)}")
    print(f"  Unique users (recs):    {len(user_recs)}")
    print(f"  Unique users (watches): {len(user_watches)}")
    print(f"  Recs considered:        {acc['recommendations_considered']}")
    print(f"  Watch-Through Rate:     {acc['watch_through_rate']:.4f}  ({acc['total_watched']}/{acc['total_recs_served']})")
    print(f"  Positive-Rating Rate:   {acc['positive_rating_rate']:.4f}  ({acc['total_positive_rated']}/{acc['total_recs_served']})")
    print(f"  --- Cost (platform-wide) ---")
    print(f"  Total license cost:     ${cost['total_license_cost_usd']:.2f}  ({cost['total_views']} views)")
    print(f"  Per-view cost:          ${cost['per_view_license_cost_usd']:.4f}")
    print(f"  --- Cost (recommendation-attributed) ---")
    print(f"  Rec-attributed cost:    ${cost['rec_attributed_cost_usd']:.2f}  ({cost['rec_attributed_views']} rec'd views)")
    print(f"  Per rec'd view cost:    ${cost['per_rec_attributed_view_cost_usd']:.4f}")
    print(f"  Per rec request cost:   ${cost['per_recommendation_cost_usd']:.4f}")
    print(f"  LLM token cost:         ${cost['llm_token_cost_usd']:.2f}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Online evaluation from live Kafka stream")
    parser.add_argument("--bootstrap", default="localhost:9092",
                        help="Kafka bootstrap server (default: localhost:9092)")
    parser.add_argument("--duration", type=int, default=300,
                        help="How long to collect data in seconds (default: 300). 0 = run forever.")
    parser.add_argument("--report-interval", type=int, default=30,
                        help="Print intermediate report every N seconds (default: 30)")
    args = parser.parse_args()

    print("=" * 60)
    print("ONLINE EVALUATION - Live Kafka Stream")
    print("=" * 60)
    print(f"  Bootstrap:       {args.bootstrap}")
    print(f"  Duration:        {'forever' if args.duration == 0 else f'{args.duration}s'}")
    print(f"  Report interval: {args.report_interval}s")
    print()

    run_online_eval(args.bootstrap, args.duration or None, args.report_interval)


if __name__ == "__main__":
    main()
