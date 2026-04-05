#!/usr/bin/env bash
#
# Starts API + Kafka helpers + optional Docker monitoring.
# Prefer: bash scripts/go.sh  (uses sudo for Docker once; no docker group needed.)
#
# Env: see go.sh; also REQUIRE_KAFKA_TUNNEL=1 to fail if SSH tunnel cannot start.
#      AUTO_INSTALL_CRON=1 to install scripts/crontab.txt
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

KAFKA_SSH_HOST="${KAFKA_SSH_HOST:-128.2.220.241}"
KAFKA_SSH_USER="${KAFKA_SSH_USER:-tunnel}"
KAFKA_SSH_PORT="${KAFKA_SSH_PORT:-${SSH_PORT:-22}}"
KAFKA_LOCAL_PORT="${KAFKA_LOCAL_PORT:-9092}"
REC_SERVICE_PORT="${REC_SERVICE_PORT:-8082}"
METRICS_EXPORTER_PORT="${METRICS_EXPORTER_PORT:-8083}"
SKIP_TUNNEL="${SKIP_TUNNEL:-0}"
SKIP_COLD_START_DAEMON="${SKIP_COLD_START_DAEMON:-0}"
PYTHON="${PYTHON:-python3}"
REQUIRE_KAFKA_TUNNEL="${REQUIRE_KAFKA_TUNNEL:-0}"
AUTO_INSTALL_CRON="${AUTO_INSTALL_CRON:-0}"
# If 8082 has the wrong process (404 on /metrics), reclaim the port before starting gunicorn.
AUTO_RECLAIM_API_PORT="${AUTO_RECLAIM_API_PORT:-0}"

mkdir -p "$PROJECT_ROOT/logs"

MON_DOTENV="$PROJECT_ROOT/monitoring/.env"
if [ -f "$MON_DOTENV" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$MON_DOTENV"
  set +a
fi
PROMETHEUS_HOST_PORT="${PROMETHEUS_HOST_PORT:-9090}"
GRAFANA_HOST_PORT="${GRAFANA_HOST_PORT:-3000}"

ENV_TUNNEL="$PROJECT_ROOT/.env.tunnel"
if [ -f "$ENV_TUNNEL" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_TUNNEL"
  set +a
fi

echo "=============================================="
echo "Stack setup — $PROJECT_ROOT"
echo "=============================================="

# --- Kafka SSH tunnel (autossh when installed; cron also runs ensure_kafka_tunnel) ---
if [ "$SKIP_TUNNEL" != "1" ]; then
  if [ "${AUTO_INSTALL_AUTOSSH:-0}" = "1" ] && ! command -v autossh >/dev/null 2>&1; then
    bash "$SCRIPT_DIR/install_autossh.sh" 2>/dev/null || true
  fi
  echo "[tunnel] Ensuring localhost:${KAFKA_LOCAL_PORT} (autossh preferred)..."
  if bash "$SCRIPT_DIR/ensure_kafka_tunnel.sh"; then
    sleep 2
    echo "[tunnel] OK."
  else
    echo "[tunnel] Could not start (SSH keys / port?). Kafka metrics wait until tunnel works."
    [ "$REQUIRE_KAFKA_TUNNEL" = "1" ] && exit 1
  fi
fi

# --- Python packages ---
if ! "$PYTHON" -c "import prometheus_client" 2>/dev/null; then
  pip install --user prometheus_client kafka-python-ng 2>/dev/null || pip install prometheus_client kafka-python-ng
fi
if ! "$PYTHON" -c "import gunicorn" 2>/dev/null; then
  pip install --user gunicorn 2>/dev/null || pip install gunicorn
fi

# --- Docker: only if Prometheus is not already up on the host ---
DOCKER_STACK_OK=0
_dc() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  elif [ -x /usr/bin/docker-compose ]; then
    /usr/bin/docker-compose "$@"
  else
    return 127
  fi
}

if curl -sf --max-time 2 "http://127.0.0.1:${PROMETHEUS_HOST_PORT}/-/healthy" >/dev/null 2>&1 \
  || curl -sf --max-time 2 "http://127.0.0.1:${PROMETHEUS_HOST_PORT}/-/ready" >/dev/null 2>&1 \
  || curl -sf --max-time 2 "http://127.0.0.1:${PROMETHEUS_HOST_PORT}/api/v1/query?query=up" >/dev/null 2>&1; then
  echo "[docker] Prometheus already up on host :${PROMETHEUS_HOST_PORT} (skip docker compose)."
  DOCKER_STACK_OK=1
elif ! command -v docker >/dev/null 2>&1; then
  echo "[docker] docker not installed — run: bash scripts/go.sh"
elif docker info >/dev/null 2>&1; then
  echo "[docker] Starting / refreshing stack..."
  cd "$PROJECT_ROOT/monitoring"
  _dc pull -q 2>/dev/null || true
  if _dc up -d --force-recreate prometheus grafana alertmanager || _dc up -d; then
    DOCKER_STACK_OK=1
  fi
  cd "$PROJECT_ROOT"
else
  echo "[docker] Your user cannot run Docker. Run once:  bash scripts/go.sh"
  echo "      (That uses sudo; you do not need a 'docker' group.)"
fi

# --- Gunicorn (must expose /health and /metrics for Prometheus + Grafana) ---
_api_ok() {
  curl -sf --max-time 10 "http://127.0.0.1:${REC_SERVICE_PORT}/health" >/dev/null 2>&1 \
    && curl -sf --max-time 10 "http://127.0.0.1:${REC_SERVICE_PORT}/metrics" 2>/dev/null | head -1 | grep -q '#'
}

_start_gunicorn() {
  echo "[api] Starting gunicorn on 0.0.0.0:${REC_SERVICE_PORT} (src.app:app)..."
  nohup "$PYTHON" -m gunicorn -w 2 -b "0.0.0.0:${REC_SERVICE_PORT}" src.app:app \
    --timeout 120 --graceful-timeout 30 \
    --access-logfile logs/gunicorn_access.log \
    --error-logfile logs/gunicorn_error.log \
    --pid /tmp/gunicorn_rec.pid \
    >/dev/null 2>&1 &
  sleep 3
}

if _api_ok; then
  echo "[api] OK on :${REC_SERVICE_PORT} (/health + /metrics)."
else
  if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${REC_SERVICE_PORT} "; then
    echo "[api] Port ${REC_SERVICE_PORT} is in use but this is not our API (bad /health or /metrics)."
    if [ "$AUTO_RECLAIM_API_PORT" = "1" ] && [ -x "$SCRIPT_DIR/reclaim_api_port.sh" ]; then
      bash "$SCRIPT_DIR/reclaim_api_port.sh" || true
    else
      echo "[api] Run:  sudo bash scripts/reclaim_api_port.sh"
      echo "     Then: bash scripts/setup_full_stack.sh"
      echo "     Or:   AUTO_RECLAIM_API_PORT=1 bash scripts/go.sh"
    fi
  fi
  if ! _api_ok; then
    _start_gunicorn
  fi
  if ! _api_ok; then
    echo "[api] WARNING: Still not healthy. Check logs/gunicorn_error.log"
  else
    echo "[api] OK after start."
  fi
fi

# --- Metrics exporter ---
pkill -f "monitoring/metrics_exporter.py" 2>/dev/null || true
sleep 1
echo "[exporter] metrics_exporter on :${METRICS_EXPORTER_PORT}..."
nohup "$PYTHON" monitoring/metrics_exporter.py \
  --port "${METRICS_EXPORTER_PORT}" --bootstrap "localhost:${KAFKA_LOCAL_PORT}" \
  > logs/metrics_exporter.log 2>&1 &

# --- Cold-start daemon ---
if [ "$SKIP_COLD_START_DAEMON" != "1" ]; then
  pkill -f "scripts/update_cold_start.py" 2>/dev/null || true
  sleep 1
  echo "[cold_start] continuous signup helper..."
  nohup "$PYTHON" scripts/update_cold_start.py \
    --mode continuous --bootstrap "localhost:${KAFKA_LOCAL_PORT}" \
    > logs/cold_start_daemon.log 2>&1 &
fi

# --- Cron ---
if [ "$AUTO_INSTALL_CRON" = "1" ] && [ -x "$SCRIPT_DIR/install_crontab.sh" ]; then
  bash "$SCRIPT_DIR/install_crontab.sh"
else
  echo "[cron] Install later: bash scripts/install_crontab.sh"
fi

echo ""
echo "=============================================="
echo "Done."
[ "$DOCKER_STACK_OK" != "1" ] && echo "If Grafana is down, run:  bash scripts/go.sh"
echo "  API:        http://127.0.0.1:${REC_SERVICE_PORT}/health"
echo "  Grafana:    http://127.0.0.1:${GRAFANA_HOST_PORT}  (admin / mlip2026)"
echo "  Prometheus: http://127.0.0.1:${PROMETHEUS_HOST_PORT}/targets"
echo "=============================================="
