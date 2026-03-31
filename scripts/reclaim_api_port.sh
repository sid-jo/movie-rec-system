#!/usr/bin/env bash
# Free REC_SERVICE_PORT (default 8082) so our recommendation API can bind.
# Stops our gunicorn, then kills anything still listening on the port (needs sudo for foreign PIDs).
#
#   bash scripts/reclaim_api_port.sh
#   REC_SERVICE_PORT=8082 bash scripts/reclaim_api_port.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${REC_SERVICE_PORT:-8082}"

echo "[reclaim] Freeing port ${PORT} for recommendation API..."

pkill -f 'src.app:app' 2>/dev/null || true
sleep 1

fuser -k "${PORT}/tcp" 2>/dev/null || true
sudo fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 1

if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "[reclaim] ERROR: port ${PORT} still busy. Inspect: sudo ss -tlnp | grep ${PORT}"
  exit 1
fi

echo "[reclaim] Port ${PORT} is free."
