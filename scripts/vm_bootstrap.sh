#!/usr/bin/env bash
# Same as: bash scripts/go.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/go.sh" "$@"
