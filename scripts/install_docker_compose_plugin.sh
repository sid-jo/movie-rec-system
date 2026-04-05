#!/usr/bin/env bash
# Install Docker Compose v2 as a CLI plugin (no docker-compose-plugin apt package needed).
# Use on Ubuntu 24.04+ when: apt cannot find docker-compose-plugin.
#
#   bash scripts/install_docker_compose_plugin.sh
#
set -euo pipefail
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) DARCH=x86_64 ;;
  aarch64|arm64) DARCH=aarch64 ;;
  *)
    echo "Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${DARCH}"
DEST=/usr/local/lib/docker/cli-plugins/docker-compose

echo "Downloading Docker Compose plugin for ${DARCH}..."
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -fSL "$URL" -o "$DEST"
sudo chmod +x "$DEST"

echo "Installed to $DEST"
sudo docker compose version
