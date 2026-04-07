#!/usr/bin/env bash
# Restart the recommendation service if it's not running (cron / manual).
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

PYTHON="${PYTHON:-python3}"
WORKERS="${GUNICORN_WORKERS:-4}"
REC_PORT="${REC_SERVICE_PORT:-8082}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restart_service: health path..."

if pgrep -f "src.app:app" > /dev/null 2>&1; then
    echo "  Gunicorn running but unhealthy — sending HUP..."
    pkill -HUP -f "src.app:app" || true
else
    echo "  Starting gunicorn (${WORKERS} workers) on :${REC_PORT}..."
    mkdir -p logs
    nohup "$PYTHON" -m gunicorn -w "${WORKERS}" -b "0.0.0.0:${REC_PORT}" src.app:app \
        --timeout 120 --graceful-timeout 30 \
        --access-logfile logs/gunicorn_access.log \
        --error-logfile logs/gunicorn_error.log \
        --pid /tmp/gunicorn_rec.pid \
        >> logs/cron_restart.log 2>&1 &
    echo "  Gunicorn started."
fi
