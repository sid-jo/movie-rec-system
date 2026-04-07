#!/usr/bin/env bash
# Cron-friendly recovery: Kafka tunnel, Docker monitoring, API (/health + /metrics), metrics exporter, cold-start daemon.
# Reduces long Grafana gaps from dead tunnel, dead exporter, or stopped gunicorn.
#
#   bash scripts/keepalive.sh
#
# Env: AUTO_RECYCLE_KAFKA_TUNNEL=1 (default) — if :9092 listens but broker probe fails, kill port and restart tunnel.
#      AUTO_RECYCLE_KAFKA_TUNNEL=0 — only run ensure_kafka_tunnel when port is free.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

mkdir -p logs
PYTHON="${PYTHON:-python3}"
REC_PORT="${REC_SERVICE_PORT:-8082}"
METRICS_PORT="${METRICS_EXPORTER_PORT:-8083}"
KAFKA_PORT="${KAFKA_LOCAL_PORT:-9092}"
WORKERS="${GUNICORN_WORKERS:-4}"
AUTO_RECYCLE_KAFKA_TUNNEL="${AUTO_RECYCLE_KAFKA_TUNNEL:-1}"

ENV_TUNNEL="$PROJECT_ROOT/.env.tunnel"
if [ -f "$ENV_TUNNEL" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_TUNNEL"
  set +a
fi
KAFKA_PORT="${KAFKA_LOCAL_PORT:-9092}"

MON_ENV="$PROJECT_ROOT/monitoring/.env"
if [ -f "$MON_ENV" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$MON_ENV"
  set +a
fi
PROM_PORT="${PROMETHEUS_HOST_PORT:-9090}"

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_port_listening() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | grep -q ":${p} "
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tln 2>/dev/null | grep -q ":${p} "
  else
    return 1
  fi
}

_kafka_probe() {
  KAFKA_BOOTSTRAP="localhost:${KAFKA_PORT}" "$PYTHON" "$SCRIPT_DIR/probe_kafka_local.py" 2>/dev/null
}

# --- 1) Kafka tunnel: ensure listening; recycle if zombie (port open, broker dead) ---
if [ -x "$SCRIPT_DIR/ensure_kafka_tunnel.sh" ]; then
  bash "$SCRIPT_DIR/ensure_kafka_tunnel.sh" >> logs/tunnel.log 2>&1 || true
fi

if [ "$AUTO_RECYCLE_KAFKA_TUNNEL" = "1" ] && _port_listening "$KAFKA_PORT"; then
  if ! _kafka_probe; then
    echo "[$(_ts)] keepalive: :${KAFKA_PORT} open but broker probe failed — recycling tunnel" >> logs/keepalive.log
    fuser -k "${KAFKA_PORT}/tcp" 2>/dev/null || true
    sudo -n fuser -k "${KAFKA_PORT}/tcp" 2>/dev/null || true
    sleep 2
    bash "$SCRIPT_DIR/ensure_kafka_tunnel.sh" >> logs/tunnel.log 2>&1 || true
    sleep 2
  fi
fi

# --- 2) Docker monitoring stack ---
_dc_up() {
  (
    cd "$PROJECT_ROOT/monitoring" || exit 0
    if [ -f .env ]; then
      docker compose --env-file .env up -d prometheus grafana alertmanager 2>/dev/null \
        || sudo -n docker compose --env-file .env up -d prometheus grafana alertmanager 2>/dev/null
    else
      docker compose up -d prometheus grafana alertmanager 2>/dev/null \
        || sudo -n docker compose up -d prometheus grafana alertmanager 2>/dev/null
    fi
  ) >> logs/keepalive.log 2>&1 || true
}

if ! curl -sf --max-time 3 "http://127.0.0.1:${PROM_PORT}/-/healthy" >/dev/null 2>&1 \
  && ! curl -sf --max-time 3 "http://127.0.0.1:${PROM_PORT}/api/v1/query?query=up" >/dev/null 2>&1; then
  echo "[$(_ts)] keepalive: Prometheus down on :${PROM_PORT}; docker compose up..." >> logs/keepalive.log
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    _dc_up
  elif sudo -n true 2>/dev/null; then
    _dc_up
  fi
fi

_api_metrics_ok() {
  curl -sf --max-time 8 "http://127.0.0.1:${REC_PORT}/health" >/dev/null 2>&1 || return 1
  local body
  body="$(curl -sf --max-time 12 "http://127.0.0.1:${REC_PORT}/metrics" 2>/dev/null)" || return 1
  echo "$body" | grep -qE '^# HELP|^# TYPE|recommendation_requests_total' || return 1
}

# --- 3) Recommendation API ---
if pgrep -f "src.app:app" >/dev/null 2>&1 && ! _api_metrics_ok; then
  echo "[$(_ts)] keepalive: gunicorn up but /health or /metrics bad — HUP" >> logs/keepalive.log
  pkill -HUP -f "src.app:app" || true
  sleep 4
fi

if ! _api_metrics_ok; then
  echo "[$(_ts)] keepalive: API unhealthy on :${REC_PORT}" >> logs/keepalive.log
  if _port_listening "$REC_PORT"; then
    if [ -x "$SCRIPT_DIR/reclaim_api_port.sh" ]; then
      REC_SERVICE_PORT="$REC_PORT" bash "$SCRIPT_DIR/reclaim_api_port.sh" >> logs/keepalive.log 2>&1 || true
    fi
  fi
  if ! _api_metrics_ok; then
    nohup "$PYTHON" -m gunicorn -w "${WORKERS}" -b "0.0.0.0:${REC_PORT}" src.app:app \
      --timeout 120 --graceful-timeout 30 \
      --access-logfile logs/gunicorn_access.log \
      --error-logfile logs/gunicorn_error.log \
      --pid /tmp/gunicorn_rec.pid \
      >> logs/keepalive.log 2>&1 &
    sleep 3
  fi
fi

_exporter_metrics_ok() {
  curl -sf --max-time 8 "http://127.0.0.1:${METRICS_PORT}/metrics" 2>/dev/null | head -1 | grep -q '#'
}

_kafka_metric_connected() {
  local raw
  raw="$(curl -sf --max-time 8 "http://127.0.0.1:${METRICS_PORT}/metrics" 2>/dev/null | grep '^kafka_stream_consumer_connected ' | head -1)" || true
  [ -z "$raw" ] && return 0
  [[ "$raw" == *" 1.0"* ]] || [[ "$raw" == *" 1 "* ]] && return 0
  return 1
}

# --- 4) Kafka metrics exporter ---
if ! _exporter_metrics_ok; then
  echo "[$(_ts)] keepalive: restarting metrics_exporter (no /metrics on :${METRICS_PORT})" >> logs/keepalive.log
  pkill -f "monitoring/metrics_exporter.py" 2>/dev/null || true
  sleep 1
  nohup "$PYTHON" monitoring/metrics_exporter.py \
    --port "${METRICS_PORT}" --bootstrap "localhost:${KAFKA_PORT}" \
    >> logs/metrics_exporter.log 2>&1 &
  sleep 2
elif _port_listening "$KAFKA_PORT" && _kafka_probe && ! _kafka_metric_connected; then
  # Exporter up but consumer not connected while broker is reachable — restart exporter
  FAILS_FILE="/tmp/keepalive_kafka_consumer_fails"
  fails=0
  [ -f "$FAILS_FILE" ] && fails="$(cat "$FAILS_FILE" 2>/dev/null || echo 0)"
  fails=$((fails + 1))
  echo "$fails" > "$FAILS_FILE"
  if [ "$fails" -ge 3 ]; then
    echo "[$(_ts)] keepalive: kafka_stream_consumer_connected!=1 for 3 checks — restarting exporter" >> logs/keepalive.log
    pkill -f "monitoring/metrics_exporter.py" 2>/dev/null || true
    sleep 1
    nohup "$PYTHON" monitoring/metrics_exporter.py \
      --port "${METRICS_PORT}" --bootstrap "localhost:${KAFKA_PORT}" \
      >> logs/metrics_exporter.log 2>&1 &
    echo 0 > "$FAILS_FILE"
    sleep 2
  fi
else
  echo 0 > "/tmp/keepalive_kafka_consumer_fails" 2>/dev/null || true
fi

# --- 5) Cold-start daemon (signup → cache) ---
if ! pgrep -f "scripts/update_cold_start.py" >/dev/null 2>&1; then
  echo "[$(_ts)] keepalive: starting cold_start daemon" >> logs/keepalive.log
  nohup "$PYTHON" scripts/update_cold_start.py \
    --mode continuous --bootstrap "localhost:${KAFKA_PORT}" \
    >> logs/cold_start_daemon.log 2>&1 &
fi

curl -sf -X POST "http://127.0.0.1:${PROM_PORT}/-/reload" >/dev/null 2>&1 || true
