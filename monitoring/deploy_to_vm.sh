#!/usr/bin/env bash
#
# Deploy the full monitoring stack to the VM.
# Run this FROM your local machine — it SSHes into the VM and sets everything up.
#
# Usage: bash monitoring/deploy_to_vm.sh <vm-user>@<vm-ip>
# Example: bash monitoring/deploy_to_vm.sh team2@128.2.220.241
#
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <vm-user>@<vm-ip>"
    echo "Example: $0 team2@128.2.220.241"
    exit 1
fi

VM_HOST="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REMOTE_PROJECT="/home/$(echo $VM_HOST | cut -d@ -f1)/group-project-s26-model-impossible-1"

echo "=============================================="
echo "Deploying monitoring stack to $VM_HOST"
echo "Remote project: $REMOTE_PROJECT"
echo "=============================================="

# Step 1: Push latest code to git so VM can pull it
echo -e "\n--- Step 1: Pushing latest code ---"
cd "$PROJECT_ROOT"
git add -A && git commit -m "Deploy monitoring stack" 2>/dev/null || echo "Nothing to commit"
git push origin main || echo "Push failed, VM will use whatever is on main"

# Step 2: SSH into VM and set up everything
echo -e "\n--- Step 2: Setting up on VM ---"
ssh "$VM_HOST" bash -s "$REMOTE_PROJECT" << 'REMOTE_SCRIPT'
PROJECT_ROOT="$1"
cd "$PROJECT_ROOT" || exit 1

echo "Pulling latest code..."
git pull origin main

echo "Installing dependencies..."
pip3 install --user prometheus_client kafka-python-ng 2>/dev/null || pip install prometheus_client kafka-python-ng
if ! command -v autossh >/dev/null 2>&1; then
  echo "Installing autossh (auto-restart Kafka SSH tunnel on drops)..."
  sudo apt-get update -qq && sudo apt-get install -y autossh || echo "autossh install skipped"
fi

# Prometheus runs in Docker; scrape targets use host.docker.internal:host-gateway (see monitoring/docker-compose.yml).
# Do NOT replace with localhost — that would scrape inside the container, not the host gunicorn/exporter.

# Ensure Docker is available
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not installed on VM. Install Docker first."
    exit 1
fi

# Stop existing containers
echo "Stopping old containers..."
cd monitoring
docker rm -f prometheus grafana 2>/dev/null || true
docker compose down 2>/dev/null || true

# Start Prometheus + Grafana
echo "Starting Prometheus + Grafana..."
docker compose up -d

# Start metrics exporter (kill old one first)
echo "Starting metrics exporter..."
pkill -f "metrics_exporter.py" 2>/dev/null || true
sleep 1
cd "$PROJECT_ROOT"
mkdir -p logs
nohup python3 monitoring/metrics_exporter.py \
    --port 8083 --bootstrap localhost:9092 \
    > logs/metrics_exporter.log 2>&1 &
echo "Metrics exporter PID: $!"

# Continuous cold-start processor (signup -> cold_start_cache.json)
pkill -f "scripts/update_cold_start.py" 2>/dev/null || true
sleep 1
nohup python3 scripts/update_cold_start.py --mode continuous --bootstrap localhost:9092 \
    > logs/cold_start_daemon.log 2>&1 &
echo "Cold-start daemon PID: $!"

# Restart the main service (gunicorn) to pick up Prometheus instrumentation
echo "Restarting recommendation service..."
if pgrep -f "gunicorn.*src.app" > /dev/null 2>&1; then
    pkill -HUP -f "gunicorn.*src.app" || true
    echo "Sent HUP to gunicorn for graceful reload."
else
    echo "Starting gunicorn..."
    mkdir -p logs
    nohup gunicorn -w 2 -b 0.0.0.0:8082 src.app:app \
        --timeout 120 --graceful-timeout 30 \
        --access-logfile logs/gunicorn_access.log \
        --error-logfile logs/gunicorn_error.log \
        > /dev/null 2>&1 &
    echo "Gunicorn started. PID: $!"
fi

# Install crontab (paths expanded to this repo)
echo "Installing cron jobs..."
bash scripts/install_crontab.sh 2>/dev/null && echo "Crontab installed." || echo "Crontab install failed — run: bash scripts/install_crontab.sh"

echo ""
echo "=============================================="
echo "DEPLOYMENT COMPLETE"
echo "  Recommendation service: http://$(hostname -I | awk '{print $1}'):8082"
echo "  Prometheus:             http://$(hostname -I | awk '{print $1}'):9090"
echo "  Grafana:                http://$(hostname -I | awk '{print $1}'):3000"
echo "  Grafana login:          admin / mlip2026"
echo "=============================================="
REMOTE_SCRIPT

echo -e "\nDone! Connect to Grafana at http://$(echo $VM_HOST | cut -d@ -f2):3000"
