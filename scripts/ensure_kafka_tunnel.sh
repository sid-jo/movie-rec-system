#!/usr/bin/env bash
# Idempotent: ensure localhost:KAFKA_LOCAL_PORT forwards to remote Kafka (SSH -L).
# Cron-friendly: sources optional PROJECT_ROOT/.env.tunnel for KAFKA_SSH_* overrides.
#
# Exit 0: port already listening or tunnel started.
# Exit 1: tunnel needed but ssh failed (check keys, KAFKA_SSH_PORT, host reachability).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.tunnel"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

KAFKA_SSH_HOST="${KAFKA_SSH_HOST:-128.2.220.241}"
KAFKA_SSH_USER="${KAFKA_SSH_USER:-tunnel}"
KAFKA_SSH_PORT="${KAFKA_SSH_PORT:-${SSH_PORT:-22}}"
KAFKA_LOCAL_PORT="${KAFKA_LOCAL_PORT:-9092}"

if command -v ss >/dev/null 2>&1; then
  if ss -tln 2>/dev/null | grep -q ":${KAFKA_LOCAL_PORT} "; then
    exit 0
  fi
elif command -v netstat >/dev/null 2>&1; then
  if netstat -tln 2>/dev/null | grep -q ":${KAFKA_LOCAL_PORT} "; then
    exit 0
  fi
fi

echo "[ensure_kafka_tunnel] Port ${KAFKA_LOCAL_PORT} not listening — starting SSH tunnel to ${KAFKA_SSH_USER}@${KAFKA_SSH_HOST}:${KAFKA_SSH_PORT}..."
# BatchMode=yes avoids hung cron jobs if keys are missing (set SSH_BATCH_MODE=no to allow password prompts — not recommended for cron)
EXTRA_SSH=()
if [ "${SSH_BATCH_MODE:-yes}" = "yes" ]; then
  EXTRA_SSH=(-o BatchMode=yes)
fi
exec ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
  "${EXTRA_SSH[@]}" \
  -p "${KAFKA_SSH_PORT}" \
  -L "${KAFKA_LOCAL_PORT}:localhost:9092" \
  "${KAFKA_SSH_USER}@${KAFKA_SSH_HOST}"
