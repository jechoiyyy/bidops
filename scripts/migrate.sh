#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_MIGRATE_PASSWORD:?BIDOPS_MIGRATE_PASSWORD is required}"
export PGPASSWORD="$BIDOPS_MIGRATE_PASSWORD"
cd /app/web/backend
alembic upgrade head

# Runtime roles receive only the privileges needed after the migration owns
# the tables.  No credential values are printed by this script.  The policy
# first revokes legacy blanket grants, then applies table/operation allowlists.
psql --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username migrate --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  -v ON_ERROR_STOP=1 --file /app/scripts/runtime-privileges.sql
