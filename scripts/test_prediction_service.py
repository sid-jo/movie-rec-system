#!/usr/bin/env python3
"""
Test script for M1 rubric requirements:
1. 2000+ successful recommendation requests (status 200, <600ms)
2. At least 10% personalized (different recommendations for different users)

Usage:
  # Test against local service (run app first: python -m src.app)
  python scripts/test_prediction_service.py --url http://localhost:8082

  # Test against deployed VM
  python scripts/test_prediction_service.py --url http://YOUR-VM-ADDRESS:8082

  # Quick test (100 requests)
  python scripts/test_prediction_service.py --url http://localhost:8082 --num 100
"""
import argparse
import random
import time
from collections import Counter
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import os
import sys

import pytest

# Skip this integration-style script when collected by pytest in CI.
if os.getenv("CI", "").lower() == "true":
    pytest.skip("Skipping prediction-service load test in CI environment.", allow_module_level=True)

# Load user IDs from ratings data
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_user_ids(n=None):
    """Load user IDs from ratings.csv for testing."""
    ratings_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "processed", "ratings.csv"
    )
    if not os.path.exists(ratings_path):
        # Fallback: use a range of user IDs (course may use various IDs)
        return [str(i) for i in range(1, 50000)]
    import pandas as pd
    df = pd.read_csv(ratings_path)
    users = df["user_id"].unique().tolist()
    random.shuffle(users)
    return [str(u) for u in (users[:n] if n else users)]


def test_request(url_base, user_id, timeout_sec=1.0):
    """
    Send GET /recommend/<userid> and return (status, body, latency_ms).
    """
    url = f"{url_base.rstrip('/')}/recommend/{user_id}"
    start = time.perf_counter()
    try:
        req = Request(url, headers={"User-Agent": "M1-test-script"})
        with urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8").strip()
            elapsed_ms = (time.perf_counter() - start) * 1000
            return resp.status, body, elapsed_ms
    except HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return e.code, str(e), elapsed_ms
    except (URLError, TimeoutError, OSError) as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return None, str(e), elapsed_ms


def validate_response(body):
    """Check response format: comma-separated movie IDs, up to 20."""
    if not body:
        return False, "empty response"
    parts = [p.strip() for p in body.split(",") if p.strip()]
    if len(parts) > 20:
        return False, f"more than 20 items: {len(parts)}"
    if len(parts) == 0:
        return False, "no movie IDs"
    return True, None


def main():
    parser = argparse.ArgumentParser(description="Test prediction service for M1 rubric")
    parser.add_argument("--url", default="http://localhost:8082", help="Base URL of recommendation service")
    parser.add_argument("--num", type=int, default=2100, help="Number of requests (default 2100 to exceed 2000)")
    parser.add_argument("--timeout", type=float, default=0.6, help="Request timeout in seconds (default 0.6)")
    args = parser.parse_args()

    user_ids = load_user_ids(args.num)
    if len(user_ids) < args.num:
        # Repeat users if we don't have enough unique users
        while len(user_ids) < args.num:
            user_ids.extend(load_user_ids(args.num))
    user_ids = user_ids[:args.num]

    print(f"Testing {args.num} requests to {args.url}/recommend/<userid>")
    print(f"Timeout: {args.timeout}s (rubric requires <600ms)")
    print("-" * 60)

    successes = 0
    latencies = []
    response_bodies = []
    format_errors = 0

    for i, uid in enumerate(user_ids):
        status, body, latency_ms = test_request(args.url, uid, args.timeout)
        latencies.append(latency_ms)

        if status == 200:
            ok, err = validate_response(body)
            if ok:
                successes += 1
                response_bodies.append(body)
            else:
                format_errors += 1
                if format_errors <= 3:
                    print(f"  Format error for user {uid}: {err}")
        else:
            if i < 5:
                print(f"  Fail user {uid}: status={status}, body={body[:80]}...")

        if (i + 1) % 500 == 0:
            print(f"  Progress: {i+1}/{args.num} requests, {successes} successes")

    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    # 1. Success count (need 2000+)
    print(f"\n1. Successful requests (status 200, valid format): {successes}")
    if successes >= 2000:
        print(f"   ✓ PASS: {successes} >= 2000 required")
    else:
        print(f"   ✗ FAIL: need 2000+, got {successes}")

    # 2. Latency (all should be <600ms for grading)
    if latencies:
        avg_ms = sum(latencies) / len(latencies)
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies)
        over_600 = sum(1 for L in latencies if L > 600)
        print(f"\n2. Latency: avg={avg_ms:.1f}ms, p95={p95_ms:.1f}ms")
        if over_600 > 0:
            print(f"   ⚠ {over_600} requests exceeded 600ms (grading may mark as failed)")
        else:
            print(f"   ✓ All requests under 600ms")

    # 3. Personalization (need 10%+ unique recommendations)
    if response_bodies:
        counter = Counter(response_bodies)
        unique_responses = len(counter)
        most_common_body, most_common_count = counter.most_common(1)[0]
        personalized_count = len(response_bodies) - most_common_count  # requests that got something different
        personalized_pct = 100.0 * personalized_count / len(response_bodies) if response_bodies else 0

        print(f"\n3. Personalization:")
        print(f"   Unique recommendation lists: {unique_responses}")
        print(f"   Most common list received by: {most_common_count} users ({100*most_common_count/len(response_bodies):.1f}%)")
        print(f"   Personalized (different from mode): {personalized_count} ({personalized_pct:.1f}%)")
        if personalized_pct >= 10:
            print(f"   ✓ PASS: {personalized_pct:.1f}% >= 10% personalized")
        else:
            print(f"   ✗ FAIL: need 10%+ personalized, got {personalized_pct:.1f}%")

    if format_errors > 0:
        print(f"\n⚠ Format errors: {format_errors}")

    print("\n" + "-" * 60)
    print("Note: Actual grading uses the course Kafka movielog. This script")
    print("simulates requests to verify your service is ready. Ensure your")
    print("VM is reachable at port 8082 during the 24h window.")
    print("-" * 60)


if __name__ == "__main__":
    main()
