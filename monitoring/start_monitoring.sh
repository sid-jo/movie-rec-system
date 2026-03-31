#!/usr/bin/env bash
# Start the full monitoring stack:
#   1. Prometheus + Grafana (via docker-compose)
#   2. Kafka metrics exporter (background process)
#
# Prerequisites:
#   - Docker and docker-compose installed
#   - SSH tunnel to Kafka (set KAFKA_SSH_PORT if not 22):
#       ssh -L 9092:localhost:9092 -p "${KAFKA_SSH_PORT:-22}" tunnel@128.2.220.241 -NT
#   - Recommendation service on :8082; metrics exporter on :8083 (matches monitoring/prometheus.yml)
#   - pip install prometheus_client kafka-python-ng
#
# Prefer one command: bash scripts/setup_full_stack.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=============================================="
echo "Starting Monitoring Stack"
echo "=============================================="

# Start Prometheus + Grafana
echo -e "\n--- Starting Prometheus + Grafana ---"
cd "$SCRIPT_DIR"
docker-compose up -d
echo "  Prometheus:    http://localhost:9090"
echo "  Alertmanager:  http://localhost:9093"
echo "  Grafana:       http://localhost:3000 (admin / mlip2026)"

# Start metrics exporter
echo -e "\n--- Starting Kafka Metrics Exporter ---"
cd "$PROJECT_ROOT"
if pgrep -f "metrics_exporter.py" > /dev/null 2>&1; then
    echo "  Metrics exporter already running."
else
    nohup python3 monitoring/metrics_exporter.py --port 8083 --bootstrap localhost:9092 \
        > logs/metrics_exporter.log 2>&1 &
    echo "  Metrics exporter started on :8083 (PID: $!)"
fi

echo -e "\n=============================================="
echo "Monitoring stack is running."
echo "  Dashboard: http://localhost:3000/d/rec-service-dashboard"
echo "=============================================="
