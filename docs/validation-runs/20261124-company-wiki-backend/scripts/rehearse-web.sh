#!/usr/bin/env bash
# Isolated rehearsal of the new backend on a migrated copy of production data.
# Restores the production dump into a throwaway PostgreSQL on an internal Docker network
# (no egress, no ports published), migrates it with the release image, starts the release
# image's web process against it with the real company bundle mounted read-only, and replays
# the GET requests the production screens make. Nothing connects to production services.
#
# usage: rehearse-web.sh <image> <dump-file> <url-list> <out-dir>
set -euo pipefail
IMAGE="$1"; DUMP="$2"; URLS="$3"; OUT="$4"
mkdir -p "$OUT"
ID="bidops-rehearsal-$$"; NET="$ID-net"; PG="$ID-pg"; WEB="$ID-web"; PW="rehearsal-only"
cleanup() {
  docker logs "$WEB" > "$OUT/web.log" 2>&1 || true
  docker rm -f "$WEB" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" -v "$DUMP:/restore/prod.dump:ro" \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD="$PW" postgres:17.11 >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U owner -d bidops >/dev/null 2>&1 && break; sleep 1; done
sleep 2
q() { docker exec "$PG" psql -U owner -d bidops -v ON_ERROR_STOP=1 -Atc "$1"; }
for role in app migrate worker ro_backup; do q "CREATE ROLE $role LOGIN PASSWORD '$PW'" >/dev/null; done
q "GRANT CREATE, CONNECT ON DATABASE bidops TO migrate" >/dev/null
docker exec "$PG" pg_restore -U owner -d bidops --exit-on-error /restore/prod.dump
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:$PW@$PG:5432/bidops" \
  -e BIDOPS_DATABASE_HOST="$PG" -e BIDOPS_MIGRATE_PASSWORD="$PW" \
  --entrypoint /app/scripts/migrate.sh "$IMAGE" > "$OUT/migrate.log" 2>&1
echo "revision: $(q 'select version_num from bidops.alembic_version')"
docker run -d --name "$WEB" --platform linux/amd64 --network "$NET" \
  -v /Users/temp/orca/bidops/wiki:/app/company-bundle:ro \
  -v "$URLS:/probe/urls.txt:ro" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://app:$PW@$PG:5432/bidops" \
  -e BIDOPS_ENGINE_COMPANY_BUNDLE_DIR=/app/company-bundle -e BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG=rootlab \
  -e BIDOPS_OBJECT_STORE_BACKEND=minio -e BIDOPS_OBJECT_STORE_ENDPOINT=minio.invalid:9000 -e BIDOPS_OBJECT_STORE_SECURE=false \
  -e BIDOPS_SOURCE_ACCESS_KEY=rehearsal-source -e BIDOPS_SOURCE_SECRET_KEY=rehearsal-source-secret \
  -e BIDOPS_STRUCTURE_ACCESS_KEY=rehearsal-structure -e BIDOPS_STRUCTURE_SECRET_KEY=rehearsal-structure-secret \
  -e BIDOPS_QUARANTINE_ACCESS_KEY=rehearsal-quarantine -e BIDOPS_QUARANTINE_SECRET_KEY=rehearsal-quarantine-secret \
  -e BIDOPS_SCHEDULER_ENABLED=false -e BIDOPS_C2_EXECUTION_ALLOWED=false -e BIDOPS_C2_DAILY_TRIGGER_ENABLED=false \
  -e BIDOPS_PRESPEC_OVERVIEW_ENABLED=false -e BIDOPS_OPENAI_ENABLED=false \
  -e BIDOPS_COMPANY_WIKI_INGEST_ENABLED=false -e BIDOPS_COMPANY_WIKI_INGEST_APPLY_REFERENCE_ENABLED=false \
  "$IMAGE" >/dev/null
ok=0
for _ in $(seq 1 90); do
  if docker exec "$WEB" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)" >/dev/null 2>&1; then ok=1; break; fi
  docker inspect "$WEB" >/dev/null 2>&1 || break
  sleep 2
done
echo "web healthy: $ok"
[ "$ok" = 1 ] || { docker logs "$WEB" 2>&1 | tail -30; exit 1; }
docker exec "$WEB" python -c "
import hashlib, json, urllib.request, urllib.error
extra = ['/api/company-wiki', '/api/company-wiki/profile', '/api/company-wiki/portfolio', '/api/company-wiki/work-units', '/api/company-wiki/pages', '/api/company-wiki/ingests']
paths = [line.strip() for line in open('/probe/urls.txt', encoding='utf-8') if line.strip()]
for path in paths + [p for p in extra if p not in paths]:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8787' + path, timeout=120) as response:
            body = response.read(); status = response.status
    except urllib.error.HTTPError as error:
        body = error.read(); status = error.code
    except Exception as error:
        body = repr(error).encode(); status = 0
    print(json.dumps({'path': path, 'status': status, 'bytes': len(body), 'sha': hashlib.sha256(body).hexdigest()[:16]}, ensure_ascii=False))
" > "$OUT/rehearsal-responses.jsonl"
echo "probed: $(wc -l < "$OUT/rehearsal-responses.jsonl")"

# Rollback rehearsal: with no ingest rows, downgrade to 0042 and confirm the previous image accepts the DB.
docker rm -f "$WEB" >/dev/null 2>&1 || true
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:$PW@$PG:5432/bidops" \
  -w /app/web/backend --entrypoint alembic "$IMAGE" downgrade 0042_engine_run > "$OUT/downgrade.log" 2>&1
echo "downgrade exit=$? revision: $(q 'select version_num from bidops.alembic_version') tables: $(q "select count(*) from pg_tables where schemaname='bidops'")"
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://app:$PW@$PG:5432/bidops" \
  -w /app/web/backend --entrypoint python bidops:list-review-sheets-20261123 -c "
from app.core.db import init_db
init_db(); print('previous image accepts the downgraded DB')
" 2>&1 | grep -vE "UserWarning|class DeepReviewValidation" | tail -2
