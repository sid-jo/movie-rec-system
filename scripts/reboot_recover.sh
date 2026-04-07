#!/usr/bin/env bash
# After VM reboot: wait for network, then full keepalive (tunnel, Docker, API, exporter, cold-start).
# Install via cron @reboot — see scripts/crontab.txt
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p logs

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] reboot_recover: waiting for network..." | tee -a logs/reboot_recover.log
sleep 90

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] reboot_recover: running keepalive" | tee -a logs/reboot_recover.log
bash "$SCRIPT_DIR/keepalive.sh" 2>&1 | tee -a logs/reboot_recover.log || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] reboot_recover: done" | tee -a logs/reboot_recover.log
