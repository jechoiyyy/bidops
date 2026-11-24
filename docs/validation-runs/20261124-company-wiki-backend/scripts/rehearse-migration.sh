#!/usr/bin/env bash
# Isolated rehearsal of the production migration: restore this morning's production dump
# (revision 0042) into a throwaway PostgreSQL 17.11 on an internal network, then run the
# release image's own scripts/migrate.sh (alembic upgrade head + runtime-privileges.sql).
# Nothing here connects to the production database or leaves the host.
#
# usage: rehearse-migration.sh <image> <dump-file>
set -euo pipefail
IMAGE="$1"; DUMP="$2"
ID="bidops-rehearsal-$$"; NET="$ID-net"; PG="$ID-pg"; PW="rehearsal-only"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create --internal "$NET" >/dev/null
docker run -d --rm --name "$PG" --network "$NET" -v "$DUMP:/restore/prod.dump:ro" \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD="$PW" postgres:17.11 >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U owner -d bidops >/dev/null 2>&1 && break; sleep 1; done
sleep 2
q() { docker exec "$PG" psql -U owner -d bidops -v ON_ERROR_STOP=1 -Atc "$1"; }
for role in app migrate worker ro_backup; do q "CREATE ROLE $role LOGIN PASSWORD '$PW'" >/dev/null; done
# Mirror production's database-level ACL (read from production: migrate=Cc, others=c).
q "GRANT CREATE, CONNECT ON DATABASE bidops TO migrate" >/dev/null
echo "== restore"
docker exec "$PG" pg_restore -U owner -d bidops --exit-on-error /restore/prod.dump
echo "restore exit=$?"
echo "revision before: $(q 'select version_num from bidops.alembic_version')"
counts() { q "select string_agg(format('%s=%s', relname, n_live), ',' order by relname) from (select c.relname, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from bidops.%I', c.relname), false, true, '')))[1]::text::bigint as n_live from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='bidops' and c.relkind='r') t"; }
before="$(counts)"
echo "tables before: $(q "select count(*) from pg_tables where schemaname='bidops'")"
echo "== migrate (release image scripts/migrate.sh)"
set +e
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:$PW@$PG:5432/bidops" \
  -e BIDOPS_DATABASE_HOST="$PG" -e BIDOPS_MIGRATE_PASSWORD="$PW" \
  --entrypoint /app/scripts/migrate.sh "$IMAGE" 2>&1 | grep -vE "UserWarning|class DeepReviewValidation" | tail -25
echo "migrate exit=${PIPESTATUS[0]}"
set -e
echo "revision after: $(q 'select version_num from bidops.alembic_version')"
echo "tables after: $(q "select count(*) from pg_tables where schemaname='bidops'")"
after="$(counts)"
python3 - "$before" "$after" <<'PY'
import sys
b = dict(x.split("=") for x in sys.argv[1].split(","))
a = dict(x.split("=") for x in sys.argv[2].split(","))
changed = {k: (b[k], a[k]) for k in b if a.get(k) != b[k]}
print("existing tables with changed row counts:", changed or "none")
print("new tables:", {k: a[k] for k in a if k not in b})
print("total rows before/after:", sum(map(int, b.values())), sum(map(int, a.values())))
PY
echo "== new table privileges"
q "select grantee, string_agg(privilege_type, ',' order by privilege_type) from information_schema.role_table_grants where table_schema='bidops' and table_name='company_wiki_ingest_run' group by 1 order by 1"
echo "== trigger and audit row"
q "select tgname from pg_trigger where tgrelid='bidops.company_wiki_ingest_run'::regclass and not tgisinternal"
q "select count(*) from bidops.screening_audit_event where payload_json::text like '%0043_company_wiki_ingest%'" 2>/dev/null || q "select count(*) from bidops.screening_audit_event where (to_jsonb(screening_audit_event)::text) like '%0043_company_wiki_ingest%'"
echo "== app role can read what web reads at startup"
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://app:$PW@$PG:5432/bidops" \
  -w /app/web/backend --entrypoint python "$IMAGE" -c "
from app.core.db import engine, current_revision, ALEMBIC_HEAD, init_db
init_db()
print('init_db ok as app role; revision', current_revision(), 'expected', ALEMBIC_HEAD)
" 2>&1 | grep -vE "UserWarning|class DeepReviewValidation" | tail -5
echo "== old image against migrated DB (what an un-replaced worker would hit on restart)"
docker run --rm --platform linux/amd64 --network "$NET" \
  -e BIDOPS_DATABASE_URL="postgresql+psycopg://app:$PW@$PG:5432/bidops" \
  -w /app/web/backend --entrypoint python bidops:list-review-sheets-20261123 -c "
from app.core.db import init_db
try:
    init_db(); print('old image init_db ok')
except Exception as exc:
    print('old image refuses:', str(exc)[:160])
" 2>&1 | grep -vE "UserWarning|class DeepReviewValidation" | tail -3
