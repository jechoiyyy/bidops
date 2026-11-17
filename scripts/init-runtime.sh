#!/usr/bin/env bash
# Explicit bootstrap only. Never run from an application's entrypoint or start.
set -euo pipefail
compose="$(cd "$(dirname "$0")" && pwd)/compose.sh"
"$compose" up -d postgres minio
"$compose" run --rm postgres-init
"$compose" run --rm migrate
"$compose" run --rm minio-init
