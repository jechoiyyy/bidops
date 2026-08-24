#!/usr/bin/env bash
set -euo pipefail

WEB_ROOT="$(cd "$(dirname "$0")" && pwd)"

cd "$WEB_ROOT/backend"
if [ -x .venv/bin/pytest ]; then
  .venv/bin/pytest
else
  python3 -m pytest
fi

cd "$WEB_ROOT/frontend"
npm run build
