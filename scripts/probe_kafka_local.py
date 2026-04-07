#!/usr/bin/env python3
"""Exit 0 if localhost Kafka answers metadata; 1 otherwise. Used by keepalive to detect stale SSH tunnels."""
import os
import sys

bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")

try:
    from kafka import KafkaAdminClient

    c = KafkaAdminClient(bootstrap_servers=[bootstrap], request_timeout_ms=8000)
    c.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
