#!/usr/bin/env bash
# Compatibility entry point: all configuration is owned by compose.sh.
set -euo pipefail
export BIDOPS_ENV=prod
exec "$(dirname "$0")/compose.sh" "$@"
