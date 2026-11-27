#!/usr/bin/env bash
# Isolated live-engine trial: throwaway PostgreSQL 17.11 + fake Responses server + the trial test,
# all from the release image, on an --internal Docker network (no egress, no production access).
# usage: run-trial.sh <image> <clone-dir> <trial-dir> <log-file>
set -euo pipefail
IMAGE="$1"; CLONE="$2"; TRIAL="$3"; LOG="$4"
ID="bidops-live-trial-$$"; NET="$ID-net"; PG="$ID-pg"; FAKE="$ID-fake"
cleanup() { docker rm -f "$PG" "$FAKE" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
rm -f "$TRIAL/requests.jsonl" "$TRIAL/frozen.json" "$TRIAL/summary.json"
docker network create --internal --subnet "${VERIFY_SUBNET:-10.251.230.0/24}" "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" -e POSTGRES_DB=bidops -e POSTGRES_USER=owner \
  -e POSTGRES_PASSWORD=verify-only postgres:17.11 >/dev/null
docker run -d --rm --name "$FAKE" --network "$NET" --network-alias fake --platform linux/amd64 \
  -v "$TRIAL:/trial" -v "$CLONE/docs/validation-runs/20261127-engine-live-trial/fake_responses.py:/run/fake_responses.py:ro" \
  --entrypoint python "$IMAGE" /run/fake_responses.py >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U owner -d bidops >/dev/null 2>&1 && break; sleep 1; done
set +e
docker run --rm --name "$ID-tests" --platform linux/amd64 --network "$NET" \
  -v "$CLONE:/repo" -v "$TRIAL:/trial" \
  -e BIDOPS_ROOT=/repo -e BIDOPS_DATA_DIR=/tmp/bidops-tests/data -e BIDOPS_ATTACHMENTS_DIR=/tmp/bidops-tests/attachments \
  -e BIDOPS_SCHEDULER_ENABLED=false -e PYTHONDONTWRITEBYTECODE=1 \
  -e BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://owner:verify-only@$PG:5432/postgres" \
  -e TRIAL_RESPONSES_URL="http://fake:8080/v1/responses" \
  -w /repo/web/backend --entrypoint python "$IMAGE" \
  -m pytest -p no:cacheprovider -p tests.conftest -q -rfE --tb=short \
  "/repo/docs/validation-runs/20261127-engine-live-trial/test_trial_live_e2e.py::test_trial_live_review_end_to_end[postgres]" > "$LOG" 2>&1
code=$?
set -e
echo "exit=$code" >> "$LOG"
