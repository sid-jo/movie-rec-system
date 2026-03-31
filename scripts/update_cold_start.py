#!/usr/bin/env python3
"""
Automated cold-start updater.
Monitors new user signups from the Kafka stream, fetches their self-descriptions,
and pre-computes personalized recommendations that are cached for fast serving.

Runs continuously as a daemon or can be triggered periodically via cron.

Usage:
  # Continuous mode (daemon):
  python3 scripts/update_cold_start.py --mode continuous --bootstrap localhost:9092

  # One-shot mode (cron-friendly):
  python3 scripts/update_cold_start.py --mode oneshot --duration 120
"""
import os
import sys
import json
import time
import argparse
import re
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")
CACHE_PATH = os.path.join(ARTIFACTS_DIR, "cold_start_cache.json")

API_BASE = os.environ.get("USER_API_BASE", "http://128.2.220.241:8080")


def load_cold_start_artifacts():
    import joblib
    cs_path = os.path.join(ARTIFACTS_DIR, "cold_start.joblib")
    if os.path.exists(cs_path):
        return joblib.load(cs_path)
    return {"title_to_id": {}, "top_movies": []}


def load_existing_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def extract_movies_from_description(text, title_to_id):
    if not text or not isinstance(text, str):
        return []
    found = []
    text_lower = text.lower()
    for norm_title, mid in title_to_id.items():
        search = norm_title.replace("+", " ")
        if search in text_lower:
            found.append(mid)
    return list(dict.fromkeys(found))[:20]


def fetch_user_data(userid):
    import requests
    try:
        resp = requests.get(f"{API_BASE}/user/{userid}", timeout=2.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def compute_cold_start_recs(user_data, artifacts):
    title_to_id = artifacts.get("title_to_id", {})
    top_movies = artifacts.get("top_movies", [])

    likes = user_data.get("self_description_likes") or ""
    dislikes = user_data.get("self_description_dislikes") or ""

    liked_ids = extract_movies_from_description(likes, title_to_id)
    disliked_ids = extract_movies_from_description(dislikes, title_to_id)
    disliked_set = set(disliked_ids)

    recs = liked_ids[:20]
    if len(recs) < 20:
        for m in top_movies:
            if m not in recs and m not in disliked_set:
                recs.append(m)
            if len(recs) >= 20:
                break

    return recs[:20]


def process_signup(userid, artifacts, cache):
    user_data = fetch_user_data(userid)
    if not user_data:
        return False

    recs = compute_cold_start_recs(user_data, artifacts)
    cache[str(userid)] = {
        "recommendations": recs,
        "likes": user_data.get("self_description_likes", ""),
        "dislikes": user_data.get("self_description_dislikes", ""),
        "cached_at": datetime.utcnow().isoformat() + "Z",
    }
    return True


def run_continuous(bootstrap_servers, report_interval=60):
    from kafka import KafkaConsumer

    artifacts = load_cold_start_artifacts()
    cache = load_existing_cache()
    print(f"[cold_start] Loaded {len(artifacts.get('title_to_id', {}))} title mappings")
    print(f"[cold_start] Existing cache: {len(cache)} users")

    consumer = KafkaConsumer(
        "movielog2",
        bootstrap_servers=[bootstrap_servers],
        auto_offset_reset="latest",
        enable_auto_commit=True,
        group_id="team2-cold-start-updater",
        consumer_timeout_ms=5000,
        value_deserializer=lambda x: x.decode("utf-8"),
    )
    print(f"[cold_start] Connected to Kafka. Monitoring signups...")

    new_signups = 0
    processed = 0
    start = time.time()
    last_save = start

    while True:
        try:
            msg_pack = consumer.poll(timeout_ms=3000)
            for tp, messages in msg_pack.items():
                for message in messages:
                    raw = message.value
                    if "create_account" not in raw:
                        continue

                    parts = raw.split(",", 2)
                    if len(parts) < 3:
                        continue
                    userid = parts[1].strip()
                    new_signups += 1

                    if userid not in cache:
                        ok = process_signup(userid, artifacts, cache)
                        if ok:
                            processed += 1

            now = time.time()
            if now - last_save >= report_interval:
                save_cache(cache)
                elapsed = now - start
                print(
                    f"[cold_start] {elapsed:.0f}s | "
                    f"signups={new_signups} processed={processed} "
                    f"cache_size={len(cache)}"
                )
                last_save = now

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[cold_start] Error: {e}")
            time.sleep(5)

    save_cache(cache)
    consumer.close()
    print(f"[cold_start] Done. Cache saved with {len(cache)} users.")


def run_oneshot(bootstrap_servers, duration_sec):
    from kafka import KafkaConsumer

    artifacts = load_cold_start_artifacts()
    cache = load_existing_cache()
    print(f"[cold_start] One-shot mode: collecting for {duration_sec}s")

    consumer = KafkaConsumer(
        "movielog2",
        bootstrap_servers=[bootstrap_servers],
        auto_offset_reset="latest",
        enable_auto_commit=True,
        group_id="team2-cold-start-oneshot",
        consumer_timeout_ms=5000,
        value_deserializer=lambda x: x.decode("utf-8"),
    )

    start = time.time()
    new_count = 0

    while time.time() - start < duration_sec:
        msg_pack = consumer.poll(timeout_ms=3000)
        for tp, messages in msg_pack.items():
            for message in messages:
                raw = message.value
                if "create_account" not in raw:
                    continue
                parts = raw.split(",", 2)
                if len(parts) < 3:
                    continue
                userid = parts[1].strip()
                if userid not in cache:
                    ok = process_signup(userid, artifacts, cache)
                    if ok:
                        new_count += 1

    consumer.close()
    save_cache(cache)
    print(f"[cold_start] Processed {new_count} new signups. Cache: {len(cache)} users.")


def main():
    parser = argparse.ArgumentParser(description="Cold-start automation")
    parser.add_argument("--mode", choices=["continuous", "oneshot"], default="continuous")
    parser.add_argument("--bootstrap", default="localhost:9092")
    parser.add_argument("--duration", type=int, default=120,
                        help="Duration for oneshot mode (seconds)")
    parser.add_argument("--report-interval", type=int, default=60)
    args = parser.parse_args()

    if args.mode == "continuous":
        run_continuous(args.bootstrap, args.report_interval)
    else:
        run_oneshot(args.bootstrap, args.duration)


if __name__ == "__main__":
    main()
