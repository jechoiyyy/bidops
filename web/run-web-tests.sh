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

export BIDOPS_ROOT="$PROJECT_ROOT"
export BIDOPS_DATA_DIR="$TEST_TMP/data"
export BIDOPS_ATTACHMENTS_DIR="$TEST_TMP/attachments"
export BIDOPS_OLLAMA_BASE_URL="http://127.0.0.1:9"
export BIDOPS_SCHEDULER_ENABLED="false"
export BIDOPS_LIVE_OLLAMA_TEST="false"

# PostgreSQL is the canonical store.  The pytest collection harness creates a
# fresh migrated application database for every invocation and uses this URL
# only for maintenance.  A caller may provide a disposable maintenance server;
# otherwise this script owns a short-lived container and removes it on every
# exit path.
TEST_PG_CONTAINER=""
TEST_PG_ADMIN_URL="${BIDOPS_TEST_POSTGRES_URL:-}"
if [ -z "$TEST_PG_ADMIN_URL" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "BIDOPS_TEST_POSTGRES_URL is required when Docker is unavailable" >&2
    exit 1
  fi

  TEST_PG_CONTAINER="bidops-web-tests-pg-$$"
  docker run -d --rm --name "$TEST_PG_CONTAINER" \
    -e POSTGRES_DB=bidops \
    -e POSTGRES_USER=owner \
    -e POSTGRES_PASSWORD=verify-only \
    -p 127.0.0.1::5432 \
    postgres:17.11 >/dev/null

  cleanup_postgres() {
    docker rm -f "$TEST_PG_CONTAINER" >/dev/null 2>&1 || true
    cleanup
  }
  trap cleanup_postgres EXIT

  ready=0
  for _ in $(seq 1 40); do
    if docker exec "$TEST_PG_CONTAINER" pg_isready -U owner -d bidops >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" -ne 1 ]; then
    docker logs "$TEST_PG_CONTAINER" >&2 || true
    exit 1
  fi

  TEST_PG_PORT="$(docker port "$TEST_PG_CONTAINER" 5432/tcp | sed -n 's/.*://p' | head -1)"
  if [ -z "$TEST_PG_PORT" ]; then
    echo "Could not resolve the temporary PostgreSQL host port" >&2
    exit 1
  fi
  TEST_PG_ADMIN_URL="postgresql+psycopg://owner:verify-only@127.0.0.1:${TEST_PG_PORT}/postgres"
fi
export BIDOPS_TEST_POSTGRES_URL="$TEST_PG_ADMIN_URL"

if [ -x "$WEB_ROOT/backend/.venv/bin/python" ]; then
  PYTHON="$WEB_ROOT/backend/.venv/bin/python"
else
  PYTHON="python3"
fi

cd "$WEB_ROOT/backend"
echo "== backend: pytest (isolated PostgreSQL 17 harness)"
"$PYTHON" -m pytest

cd "$WEB_ROOT/frontend"
echo "== frontend: production build"
npm run build
