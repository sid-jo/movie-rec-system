#!/usr/bin/env bash
# Restart the recommendation service if it's not running.
# Called by cron health check.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Service health check failed, restarting..."

if pgrep -f "gunicorn.*src.app" > /dev/null 2>&1; then
    echo "  Gunicorn is running but health check failed. Sending HUP..."
    pkill -HUP -f "gunicorn.*src.app" || true
else
    echo "  Gunicorn not found. Starting..."
    nohup gunicorn -w 2 -b 0.0.0.0:8082 src.app:app \
        --timeout 120 --graceful-timeout 30 \
        --access-logfile logs/gunicorn_access.log \
        --error-logfile logs/gunicorn_error.log \
        --pid /tmp/gunicorn_rec.pid \
        &
    echo "  Gunicorn started."
fi
