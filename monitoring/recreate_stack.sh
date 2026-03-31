#!/usr/bin/env bash
# Recreate Prometheus/Grafana/Alertmanager so they pick up monitoring/prometheus.yml from disk.
# Fixes "no data in Grafana" when Prometheus was started with an old config that scraped
# 127.0.0.1:8082 from inside the container (wrong — must use host.docker.internal).
#
# Run from repo root or monitoring/:
#   bash monitoring/recreate_stack.sh
# If you get "permission denied" on Docker, use: sudo bash monitoring/recreate_stack.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DC=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  DC=(docker-compose)
fi

"${DC[@]}" up -d --force-recreate prometheus grafana alertmanager
echo "Done. Open http://127.0.0.1:9090/targets — recommendation-service and metrics-exporter should be UP."
echo "If still DOWN, ensure gunicorn is on :8082 and metrics_exporter on :8083 on the host."
