#!/usr/bin/env bash
#
# Simple VM setup — run this from the project root (no "docker" group needed).
#
#   cd ~/group-project-s26-model-impossible-1
#   bash scripts/go.sh
#
# Step 1: sudo starts Grafana + Prometheus + Alertmanager (asks for your password once).
# Step 2: starts the recommendation API + metrics exporter + cron (no sudo).
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed yet. On Ubuntu/Debian run these two lines, then re-run this script:"
  echo ""
  echo "  sudo apt update && sudo apt install -y docker.io"
  echo "  sudo systemctl enable --now docker"
  echo ""
  exit 1
fi

echo "== 1/2: Monitoring (sudo password once) =="

# Pick host ports if defaults are already taken (common: another Prometheus on 9090)
_next_free_port() {
  local p="$1" end=$(( "$1" + 60 ))
  while [ "$p" -lt "$end" ]; do
    if ! ss -tln 2>/dev/null | grep -q ":${p} "; then
      echo "$p"
      return 0
    fi
    p=$((p + 1))
  done
  echo "No free port starting at $1" >&2
  return 1
}

MON_ENV="$ROOT/monitoring/.env"
# Re-use ports from last run when this file exists (override by exporting vars before go.sh).
if [ -f "$MON_ENV" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$MON_ENV"
  set +a
fi
if [ -z "${PROMETHEUS_HOST_PORT:-}" ]; then
  if ss -tln 2>/dev/null | grep -q ':9090 '; then
    PROMETHEUS_HOST_PORT="$(_next_free_port 9091)" || exit 1
    echo "Port 9090 is already in use — Prometheus will be on host port ${PROMETHEUS_HOST_PORT} (see monitoring/.env)."
  else
    PROMETHEUS_HOST_PORT=9090
  fi
  export PROMETHEUS_HOST_PORT
fi
if [ -z "${GRAFANA_HOST_PORT:-}" ]; then
  if ss -tln 2>/dev/null | grep -q ':3000 '; then
    GRAFANA_HOST_PORT="$(_next_free_port 3001)" || exit 1
    echo "Port 3000 is already in use — Grafana will be on host port ${GRAFANA_HOST_PORT}."
  else
    GRAFANA_HOST_PORT=3000
  fi
  export GRAFANA_HOST_PORT
fi
if [ -z "${ALERTMANAGER_HOST_PORT:-}" ]; then
  if ss -tln 2>/dev/null | grep -q ':9093 '; then
    ALERTMANAGER_HOST_PORT="$(_next_free_port 9094)" || exit 1
    echo "Port 9093 is busy — Alertmanager on host port ${ALERTMANAGER_HOST_PORT}."
  else
    ALERTMANAGER_HOST_PORT=9093
  fi
  export ALERTMANAGER_HOST_PORT
fi

umask 077
{
  echo "PROMETHEUS_HOST_PORT=${PROMETHEUS_HOST_PORT}"
  echo "GRAFANA_HOST_PORT=${GRAFANA_HOST_PORT}"
  echo "ALERTMANAGER_HOST_PORT=${ALERTMANAGER_HOST_PORT}"
} > "$MON_ENV"

# Compose: "docker compose" (plugin) or standalone "docker-compose" (Ubuntu package docker-compose)
_dc() {
  if sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    sudo docker-compose "$@"
  elif [ -x /usr/bin/docker-compose ]; then
    sudo /usr/bin/docker-compose "$@"
  else
    echo "This machine has 'docker' but not Docker Compose."
    echo ""
    echo "Ubuntu 24.04 (Noble) often does NOT have package 'docker-compose-plugin'. Pick one:"
    echo ""
    echo "  A) Apt (standalone v1 binary — works with this repo):"
    echo "       sudo apt update && sudo apt install -y docker-compose"
    echo ""
    echo "  B) Official Compose v2 plugin (no apt package needed):"
    echo "       bash scripts/install_docker_compose_plugin.sh"
    echo ""
    exit 1
  fi
}

cd "$ROOT/monitoring"
_dc down --remove-orphans 2>/dev/null || true
_dc pull -q 2>/dev/null || true
_dc up -d --force-recreate prometheus grafana alertmanager

cd "$ROOT"
echo "== 2/4: API + metrics + cron (no sudo) =="
export AUTO_INSTALL_CRON="${AUTO_INSTALL_CRON:-1}"
export REQUIRE_KAFKA_TUNNEL="${REQUIRE_KAFKA_TUNNEL:-0}"
export AUTO_RECLAIM_API_PORT="${AUTO_RECLAIM_API_PORT:-1}"
export VERIFY_API_METRICS="${VERIFY_API_METRICS:-1}"
export AUTO_INSTALL_AUTOSSH="${AUTO_INSTALL_AUTOSSH:-1}"
# setup_full_stack reads monitoring/.env for Prometheus URL checks
export PROMETHEUS_HOST_PORT GRAFANA_HOST_PORT ALERTMANAGER_HOST_PORT
bash scripts/setup_full_stack.sh

echo ""
echo "== 3/4: Keepalive pass (tunnel, exporter, cold-start, Docker if needed) =="
bash scripts/keepalive.sh || true

echo ""
echo "== 4/4: Scrape check (host :8082 == Prometheus host.docker.internal:8082) =="
REC_PORT="${REC_SERVICE_PORT:-8082}"
_scrape_ok() {
  curl -sf --max-time 8 "http://127.0.0.1:${REC_PORT}/metrics" 2>/dev/null | grep -qE '^# HELP|^# TYPE|recommendation_requests_total'
}
if _scrape_ok; then
  echo "OK — /metrics on :${REC_PORT} is valid Prometheus text (recommendation-service target should go UP)."
else
  echo "WARN — /metrics still wrong; running reclaim + one gunicorn start..."
  REC_SERVICE_PORT="$REC_PORT" bash scripts/reclaim_api_port.sh || true
  export PYTHONPATH="$ROOT"
  nohup python3 -m gunicorn -w "${GUNICORN_WORKERS:-4}" -b "0.0.0.0:${REC_PORT}" src.app:app \
    --timeout 120 --graceful-timeout 30 \
    --access-logfile logs/gunicorn_access.log \
    --error-logfile logs/gunicorn_error.log \
    --pid /tmp/gunicorn_rec.pid \
    >/dev/null 2>&1 &
  sleep 4
  if _scrape_ok; then
    echo "OK — /metrics fixed after reclaim + gunicorn."
  else
    echo "FATAL — still broken. Run: sudo REC_SERVICE_PORT=${REC_PORT} bash scripts/reclaim_api_port.sh"
    echo "        then: bash scripts/go.sh"
    exit 1
  fi
fi

# Same path Prometheus uses from Docker (Linux host-gateway)
if sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -qx prometheus; then
  if sudo docker exec prometheus wget -qO- -T 5 "http://host.docker.internal:${REC_PORT}/metrics" 2>/dev/null | grep -qE '^# HELP|recommendation_requests_total'; then
    echo "OK — prometheus container can reach host.docker.internal:${REC_PORT}/metrics"
  else
    echo "WARN — in-container wget to host.docker.internal failed (check extra_hosts: host-gateway in compose)."
  fi
fi

echo ""
echo "Open Grafana:     http://127.0.0.1:${GRAFANA_HOST_PORT}  (admin / mlip2026)"
echo "Prometheus UI:    http://127.0.0.1:${PROMETHEUS_HOST_PORT}/targets"
echo "Alertmanager:     http://127.0.0.1:${ALERTMANAGER_HOST_PORT}"
echo "API health:       curl -s http://127.0.0.1:${REC_PORT}/health"
echo "API metrics:      curl -s http://127.0.0.1:${REC_PORT}/metrics | head"
echo "Cron keepalive:   installed if AUTO_INSTALL_CRON=1 — VM stays up after you disconnect."
echo "(Host ports saved in monitoring/.env — re-used on the next go.sh run.)"
