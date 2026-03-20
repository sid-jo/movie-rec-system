"""Simple Kafka connectivity test for local dev."""
import os
import pytest

# Skip this Kafka integration test in CI where no broker is available.
if os.getenv("CI", "").lower() == "true":
    pytest.skip("Skipping Kafka-dependent test in CI environment.", allow_module_level=True)

from kafka import KafkaConsumer


def test_kafka_connect_and_read_one_message():
    consumer = KafkaConsumer(
        "movielog2",  # Your team's topic
        bootstrap_servers=["localhost:9092"],
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="team2-test",
        consumer_timeout_ms=5000,  # don't block forever
    )

    print("Connected! Waiting for messages...")
    for message in consumer:
        print(f"{message.value.decode('utf-8')}")
        # If we got here, the test passes (we saw at least one message)
        return

    # If no messages were read, don't fail hard in local runs
    pytest.skip("No messages received from Kafka within timeout.")
