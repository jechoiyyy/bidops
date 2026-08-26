#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_HOST:?database host is required}"
: "${BIDOPS_OWNER_PASSWORD:?owner password is required}"
: "${BIDOPS_MIGRATE_PASSWORD:?migrate password is required}"
: "${BIDOPS_APP_PASSWORD:?app password is required}"
: "${BIDOPS_WORKER_PASSWORD:?worker password is required}"
: "${BIDOPS_RO_BACKUP_PASSWORD:?ro_backup password is required}"

export PGPASSWORD="$BIDOPS_OWNER_PASSWORD"
psql --host "$BIDOPS_DATABASE_HOST" --username owner --dbname bidops -v ON_ERROR_STOP=1 \
  -v migrate_password="$BIDOPS_MIGRATE_PASSWORD" \
  -v app_password="$BIDOPS_APP_PASSWORD" \
  -v worker_password="$BIDOPS_WORKER_PASSWORD" \
  -v ro_backup_password="$BIDOPS_RO_BACKUP_PASSWORD" <<'SQL'
CREATE SCHEMA IF NOT EXISTS bidops;
SELECT format('CREATE ROLE migrate LOGIN PASSWORD %L', :'migrate_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migrate')\gexec
ALTER ROLE migrate PASSWORD :'migrate_password';
SELECT format('CREATE ROLE app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app')\gexec
ALTER ROLE app PASSWORD :'app_password';
SELECT format('CREATE ROLE worker LOGIN PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'worker')\gexec
ALTER ROLE worker PASSWORD :'worker_password';
SELECT format('CREATE ROLE ro_backup LOGIN PASSWORD %L', :'ro_backup_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ro_backup')\gexec
ALTER ROLE ro_backup PASSWORD :'ro_backup_password';
GRANT USAGE, CREATE ON SCHEMA bidops TO migrate;
GRANT CONNECT, CREATE ON DATABASE bidops TO migrate;
GRANT CONNECT ON DATABASE bidops TO app, worker, ro_backup;
ALTER SCHEMA bidops OWNER TO migrate;
SQL
