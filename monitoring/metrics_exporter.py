#!/usr/bin/env python3
"""
Prometheus metrics exporter for online evaluation.
Reads from the Kafka movielog2 stream continuously and exposes:
  - Watch-Through Rate (WTR)
  - Positive-Rating Rate (PRR)
  - License cost metrics
  - Data drift indicators
  - Service availability (based on recommendation event rate)

Runs as a standalone HTTP server on port 8083, scraped by Prometheus.
"""
import os
import sys
import json
import time
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import HTTPServer

from prometheus_client import (
    Gauge, Counter, Histogram, Info,
    generate_latest, CONTENT_TYPE_LATEST,
    MetricsHandler,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.online_eval import parse_kafka_line

METADATA_PATH = os.path.join(PROJECT_ROOT, "metadata", "movies.json")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
WATCH_THROUGH_RATE = Gauge(
    "online_watch_through_rate", "Watch-Through Rate (WTR)"
)
POSITIVE_RATING_RATE = Gauge(
    "online_positive_rating_rate", "Positive-Rating Rate (PRR)"
)
TOTAL_LICENSE_COST = Counter(
    "online_license_cost_usd_total", "Cumulative movie licensing cost (USD)"
)
REC_ATTRIBUTED_COST = Counter(
    "online_rec_attributed_cost_usd_total",
    "Cumulative licensing cost attributed to recommendations (USD)",
)
RECOMMENDATION_EVENTS = Counter(
    "online_recommendation_events_total", "Total recommendation events observed"
)
WATCH_EVENTS = Counter(
    "online_watch_events_total", "Total watch events observed"
)
RATING_EVENTS = Counter(
    "online_rating_events_total", "Total rating events observed"
)
KAFKA_MESSAGES = Counter(
    "online_kafka_messages_total", "Total Kafka messages parsed"
)

# Drift
DRIFT_RATING_MEAN = Gauge(
    "drift_rating_mean", "Current rolling mean of ratings"
)
DRIFT_WATCH_DURATION_MEAN = Gauge(
    "drift_watch_duration_mean", "Current rolling mean of watch minutes"
)
DRIFT_RATING_SHIFT = Gauge(
    "drift_rating_shift_detected",
    "1 if rating mean shifted > 0.5 from reference, else 0",
)
DRIFT_WATCH_SHIFT = Gauge(
    "drift_watch_duration_shift_detected",
    "1 if watch duration shifted > 30% from reference, else 0",
)

# Availability proxy: recommendation events per minute
REC_RATE_PER_MINUTE = Gauge(
    "online_rec_rate_per_minute",
    "Recommendation events observed per minute (proxy for service availability)",
)

POSITIVE_RATING_THRESHOLD = 4.0
WINDOW_SIZE = 10000  # rolling window for drift


def _load_movies_metadata():
    if not os.path.exists(METADATA_PATH):
        return {}
    with open(METADATA_PATH) as f:
        return json.load(f)


def _movie_cost(mid, metadata):
    info = metadata.get(mid, {})
    if isinstance(info, dict):
        return info.get("license_cost") or info.get("cost") or 0.0
    return 0.0


def kafka_collector(bootstrap_servers="localhost:9092"):
    """Background thread: consume Kafka and update Prometheus gauges."""
    from kafka import KafkaConsumer

    metadata = _load_movies_metadata()
    print(f"[metrics_exporter] Loaded {len(metadata)} movies")

    consumer = None
    while consumer is None:
        print(f"[metrics_exporter] Connecting to Kafka at {bootstrap_servers}...")
        try:
            consumer = KafkaConsumer(
                "movielog2",
                bootstrap_servers=[bootstrap_servers],
                auto_offset_reset="latest",
                enable_auto_commit=True,
                group_id="team2-metrics-exporter",
                consumer_timeout_ms=5000,
                value_deserializer=lambda x: x.decode("utf-8"),
            )
            print("[metrics_exporter] Connected. Consuming...")
        except Exception as e:
            print(
                f"[metrics_exporter] Kafka not ready ({e!s}); retry in 30s "
                f"(SSH tunnel must expose localhost:9092)."
            )
            time.sleep(30)

    user_recs = defaultdict(list)
    user_watches = defaultdict(set)
    user_ratings = defaultdict(dict)

    rating_window = []
    watch_min_window = []
    ref_rating_mean = 3.5
    ref_watch_min_mean = 30.0

    rec_timestamps = []

    while True:
        try:
            msg_pack = consumer.poll(timeout_ms=3000)
            for tp, messages in msg_pack.items():
                for message in messages:
                    event = parse_kafka_line(message.value)
                    if not event:
                        continue
                    KAFKA_MESSAGES.inc()

                    etype = event.get("type")
                    uid = event.get("userid", "")

                    if etype == "recommendation":
                        RECOMMENDATION_EVENTS.inc()
                        rec_timestamps.append(time.time())
                        movies_str = event.get("movies", "")
                        if movies_str:
                            rec_list = [
                                m.strip().strip("'\" ")
                                for m in movies_str.split(",")
                                if m.strip()
                            ]
                            if rec_list:
                                user_recs[uid].append(rec_list)

                    elif etype == "watch":
                        WATCH_EVENTS.inc()
                        mid = event.get("movieid", "")
                        if mid and uid:
                            user_watches[uid].add(mid)
                            c = _movie_cost(mid, metadata)
                            if c > 0:
                                TOTAL_LICENSE_COST.inc(c)
                                if uid in user_recs:
                                    for rec_set in user_recs[uid]:
                                        if mid in rec_set:
                                            REC_ATTRIBUTED_COST.inc(c)
                                            break
                        minute = event.get("minute", 0)
                        if minute > 0:
                            watch_min_window.append(minute)
                            if len(watch_min_window) > WINDOW_SIZE:
                                watch_min_window.pop(0)

                    elif etype == "rating":
                        RATING_EVENTS.inc()
                        mid = event.get("movieid", "")
                        rating_val = event.get("rating", 0)
                        if mid and uid and rating_val:
                            user_ratings[uid][mid] = rating_val
                        if rating_val:
                            rating_window.append(rating_val)
                            if len(rating_window) > WINDOW_SIZE:
                                rating_window.pop(0)

            # Recompute gauges periodically
            _update_accuracy_gauges(user_recs, user_watches, user_ratings)
            _update_drift_gauges(
                rating_window, watch_min_window,
                ref_rating_mean, ref_watch_min_mean,
            )
            _update_availability(rec_timestamps)

        except Exception as e:
            print(f"[metrics_exporter] Error: {e}")
            time.sleep(5)


def _update_accuracy_gauges(user_recs, user_watches, user_ratings):
    total_recommended = 0
    total_watched = 0
    total_positive = 0
    for uid, rec_sets in user_recs.items():
        watched = user_watches.get(uid, set())
        rated = user_ratings.get(uid, {})
        for rec_movies in rec_sets:
            total_recommended += len(rec_movies)
            total_watched += sum(1 for m in rec_movies if m in watched)
            total_positive += sum(
                1 for m in rec_movies
                if rated.get(m, 0) >= POSITIVE_RATING_THRESHOLD
            )
    if total_recommended > 0:
        WATCH_THROUGH_RATE.set(round(total_watched / total_recommended, 6))
        POSITIVE_RATING_RATE.set(round(total_positive / total_recommended, 6))
    else:
        WATCH_THROUGH_RATE.set(0)
        POSITIVE_RATING_RATE.set(0)


def _update_drift_gauges(ratings, watch_mins, ref_rating, ref_watch):
    if ratings:
        mean_r = sum(ratings) / len(ratings)
        DRIFT_RATING_MEAN.set(round(mean_r, 4))
        DRIFT_RATING_SHIFT.set(1 if abs(mean_r - ref_rating) > 0.5 else 0)
    if watch_mins:
        mean_w = sum(watch_mins) / len(watch_mins)
        DRIFT_WATCH_DURATION_MEAN.set(round(mean_w, 4))
        shift = abs(mean_w - ref_watch) / max(ref_watch, 1)
        DRIFT_WATCH_SHIFT.set(1 if shift > 0.3 else 0)


def _update_availability(rec_timestamps):
    now = time.time()
    cutoff = now - 60
    recent = [t for t in rec_timestamps if t > cutoff]
    REC_RATE_PER_MINUTE.set(len(recent))
    while rec_timestamps and rec_timestamps[0] < cutoff - 300:
        rec_timestamps.pop(0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Prometheus metrics exporter")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--bootstrap", default="localhost:9092")
    args = parser.parse_args()

    collector_thread = threading.Thread(
        target=kafka_collector,
        args=(args.bootstrap,),
        daemon=True,
    )
    collector_thread.start()

    print(f"[metrics_exporter] Serving Prometheus metrics on :{args.port}/metrics")
    server = HTTPServer(("0.0.0.0", args.port), MetricsHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
