#!/usr/bin/env bash
# Install autossh for resilient Kafka SSH tunnels (cron / VM survives laptop disconnect).
set -euo pipefail
if command -v autossh >/dev/null 2>&1; then
  echo "autossh already installed: $(command -v autossh)"
  exit 0
fi
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y autossh
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y autossh
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y autossh
else
  echo "Install autossh with your OS package manager, then re-run ensure_kafka_tunnel.sh"
  exit 1
fi
