#!/usr/bin/env bash
# Install crontab with PROJECT_ROOT and PATH (cron's default PATH is tiny).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP="$(mktemp)"
PATH_LINE="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${HOME}/.local/bin"
{
  echo "# Installed by scripts/install_crontab.sh — edit scripts/crontab.txt and re-run."
  echo "$PATH_LINE"
  sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "$SCRIPT_DIR/crontab.txt"
} > "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "Crontab installed for $PROJECT_ROOT"
crontab -l
