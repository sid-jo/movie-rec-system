#!/usr/bin/env bash
#
# Build and run the recommendation service in Docker (Milestone 3 containerization).
#
# Usage:
#   bash scripts/run_rec_docker.sh up        # build + detached
#   bash scripts/run_rec_docker.sh logs      # follow logs
#   bash scripts/run_rec_docker.sh reload    # SIGHUP gunicorn (reload models on volume)
#   bash scripts/run_rec_docker.sh down
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.serving.yml)
cmd="${1:-up}"

case "$cmd" in
  up)
    "${COMPOSE[@]}" up -d --build
    echo "API: http://127.0.0.1:${REC_SERVICE_PORT:-8082}/health"
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  logs)
    "${COMPOSE[@]}" logs -f recommendation
    ;;
  reload)
    # Prefer `docker kill` — some compose versions treat `compose kill` like SIGKILL.
    if ! docker ps -q -f name=mlip-recommendation | grep -q .; then
      echo "Container mlip-recommendation is not running."
      exit 1
    fi
    docker kill -s HUP mlip-recommendation
    echo "Sent SIGHUP to gunicorn master in container."
    ;;
  *)
    echo "Usage: $0 {up|down|logs|reload}"
    exit 1
    ;;
esac
