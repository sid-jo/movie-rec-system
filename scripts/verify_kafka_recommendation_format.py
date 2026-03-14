#!/usr/bin/env python3
"""
Verify that recommendation responses appear correctly in the Kafka movielog.

FLOW (what to check):
  1. Your service returns: "movie1,movie2,movie3" (comma-separated, plain text)
  2. The COURSE infrastructure receives it, parses it, and writes to Kafka
  3. Kafka log entry format: <time>,<userid>,recommendation request <server>, status 200, result: [rec1,rec2,...], <ms>ms
  4. If you see status 200 + result with your movie IDs → your answer was correctly received and parsed

Usage:
  python3 scripts/verify_kafka_recommendation_format.py [--count N] [--raw]
  --raw: print the exact raw Kafka log line (to match the format your teammate described)
"""
import argparse
import re
import sys

try:
    from kafka import KafkaConsumer
except ImportError:
    print("Install kafka: pip install kafka-python-ng")
    sys.exit(1)


def parse_recommendation_entry(log_line):
    """Extract fields from a recommendation request log entry."""
    # Expected: <time>,<userid>,recommendation request <server>, status <code>, result: [...], <responsetime>
    if 'recommendation request' not in log_line:
        return None

    parts = log_line.split(',', 2)
    if len(parts) < 3:
        return None

    timestamp, userid, action = parts[0], parts[1], parts[2]

    status_match = re.search(r'status (\d+)', action)
    status = int(status_match.group(1)) if status_match else None

    result_match = re.search(r'result: \[(.*?)\]', action)
    result_match_alt = re.search(r'result: (.+?)(?:,\s*\d+ms)?$', action)  # fallback if no brackets
    recommendations = None
    if result_match:
        recommendations = result_match.group(1)
    elif result_match_alt:
        recommendations = result_match_alt.group(1).strip()

    return {
        'timestamp': timestamp,
        'userid': userid,
        'status': status,
        'recommendations': recommendations,
        'raw': log_line[:200] + '...' if len(log_line) > 200 else log_line
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=20, help='Max recommendation entries to print')
    parser.add_argument('--show-errors', action='store_true', help='Also show non-200 status entries')
    parser.add_argument('--raw', action='store_true', help='Print the exact raw Kafka log line (matches rubric format)')
    args = parser.parse_args()

    print("Connecting to Kafka (movielog2)...")
    try:
        consumer = KafkaConsumer(
            'movielog2',
            bootstrap_servers=['localhost:9092'],
            auto_offset_reset='latest',  # Start from recent messages
            enable_auto_commit=False,
            consumer_timeout_ms=10000,
            value_deserializer=lambda x: x.decode('utf-8')
        )
    except Exception as e:
        print(f"Failed to connect to Kafka: {e}")
        print("Ensure Kafka is running and reachable (e.g., SSH tunnel to course server)")
        sys.exit(1)

    print("\nWhat to check (per rubric):")
    print("  Kafka entry = <time>,<userid>,recommendation request <server>, status 200, result: <parsed recommendations>, <responsetime>")
    print("  If status 200 and result contains your movie IDs → your answer was correctly received and parsed.\n")
    print("-" * 80)

    found = 0
    success_200 = 0
    for message in consumer:
        line = message.value
        parsed = parse_recommendation_entry(line)
        if parsed:
            found += 1
            if parsed['status'] == 200:
                success_200 += 1
                if args.raw:
                    print(f"[{found}] RAW KAFKA LOG LINE:")
                    print(line)
                    print()
                else:
                    print(f"[{found}] ✓ status 200 | user={parsed['userid']} | result: [{parsed['recommendations'][:80]}...]")
            elif args.show_errors:
                print(f"[{found}] ✗ status {parsed['status']} | user={parsed['userid']}")
            if found >= args.count:
                break

    print("-" * 80)
    print(f"Found {found} recommendation entries, {success_200} with status 200")
    if success_200 > 0:
        print("✓ Your responses are being parsed correctly in the Kafka stream.")
        if not args.raw:
            print("  (Use --raw to see the exact log line format)")
    else:
        print("⚠ No status-200 recommendation entries found. Check:")
        print("  - Is your service running on port 8082?")
        print("  - Is the course sending requests to your VM?")
        print("  - Try --show-errors to see non-200 entries")
    consumer.close()


if __name__ == "__main__":
    main()
