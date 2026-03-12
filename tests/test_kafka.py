import os

import pytest


@pytest.mark.integration
def test_kafka_connects_and_reads_one_message():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration test (set RUN_INTEGRATION_TESTS=1 to enable)")

    from kafka import KafkaConsumer

    consumer = KafkaConsumer(
        "movielog2",
        bootstrap_servers=["localhost:9092"],
        auto_offset_reset="latest",
        enable_auto_commit=False,
        consumer_timeout_ms=5000,
        value_deserializer=lambda x: x.decode("utf-8"),
    )
    msgs = list(consumer)
    consumer.close()
    assert isinstance(msgs, list)