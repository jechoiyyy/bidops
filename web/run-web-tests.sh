#!/usr/bin/env bash
set -euo pipefail

WEB_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$WEB_ROOT/.." && pwd)"

# Ordinary CI must never inspect or mutate an operator database.  Keep every
# test artifact in one private temporary directory and remove it on every
# exit path, including a failing migration or test process.
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/bidops-web-tests.XXXXXX")"
cleanup() {
  rm -rf -- "$TEST_TMP"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

DATABASE_PATH="$TEST_TMP/bidops.db"
export BIDOPS_ROOT="$PROJECT_ROOT"
export BIDOPS_DATA_DIR="$TEST_TMP/data"
export BIDOPS_ATTACHMENTS_DIR="$TEST_TMP/attachments"
export BIDOPS_DATABASE_URL="sqlite:///$DATABASE_PATH"
export BIDOPS_OLLAMA_BASE_URL="http://127.0.0.1:9"
export BIDOPS_SCHEDULER_ENABLED="false"
export BIDOPS_LIVE_OLLAMA_TEST="false"

if [ -x "$WEB_ROOT/backend/.venv/bin/python" ]; then
  PYTHON="$WEB_ROOT/backend/.venv/bin/python"
else
  PYTHON="python3"
fi

cd "$WEB_ROOT/backend"
echo "== backend: alembic upgrade head (fresh SQLite)"
"$PYTHON" -m alembic upgrade head

echo "== backend: pytest"
"$PYTHON" -m pytest

cd "$WEB_ROOT/frontend"
echo "== frontend: production build"
npm run build
