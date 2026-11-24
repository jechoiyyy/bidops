#!/usr/bin/env bash
# Backend verification environment: the release image's own Linux runtime (python 3.12 +
# requirements.lock + OS tools), a clean clone of the commit mounted at /repo, and a
# throwaway PostgreSQL 17.11 on an internal Docker network (no egress, no production access).
#
# usage: run-backend-tests.sh <image> <clone-dir> <log-file> [pytest args...]
set -euo pipefail
IMAGE="$1"; CLONE="$2"; LOG="$3"; shift 3
ID="bidops-verify-$$"
NET="$ID-net"; PG="$ID-pg"
cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD=verify-only \
  postgres:17.11 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U owner -d bidops >/dev/null 2>&1 && break
  sleep 1
done
set +e
docker run --rm --name "$ID-tests" --platform linux/amd64 --network "$NET" \
  -v "$CLONE:/repo" \
  ${EXTRA_MOUNT:+-v "$EXTRA_MOUNT"} \
  -e BIDOPS_ROOT=/repo \
  -e BIDOPS_DATA_DIR=/tmp/bidops-tests/data \
  -e BIDOPS_ATTACHMENTS_DIR=/tmp/bidops-tests/attachments \
  -e BIDOPS_SCHEDULER_ENABLED=false \
  -e BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://owner:verify-only@$PG:5432/postgres" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /repo/web/backend --entrypoint python "$IMAGE" \
  -m pytest -p no:cacheprovider "$@" > "$LOG" 2>&1
code=$?
set -e
echo "exit=$code" >> "$LOG"
exit 0
