#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_MIGRATE_PASSWORD:?BIDOPS_MIGRATE_PASSWORD is required}"
export PGPASSWORD="$BIDOPS_MIGRATE_PASSWORD"
cd /app/web/backend
alembic upgrade head

# Runtime roles receive only the privileges needed after the migration owns
# the tables.  No credential values are printed by this script.
psql --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username migrate --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  -v ON_ERROR_STOP=1 <<'SQL'
GRANT USAGE ON SCHEMA bidops TO app, worker, ro_backup;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bidops TO worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bidops TO app;
GRANT SELECT ON ALL TABLES IN SCHEMA bidops TO ro_backup;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bidops TO app, worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;
SQL
