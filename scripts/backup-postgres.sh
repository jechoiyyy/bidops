#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_RO_BACKUP_PASSWORD:?BIDOPS_RO_BACKUP_PASSWORD is required}"
backup_dir="${BACKUP_DIR:?BACKUP_DIR is required}"
export PGPASSWORD="$BIDOPS_RO_BACKUP_PASSWORD"
mkdir -p "$backup_dir/full" "$backup_dir/wal"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username ro_backup --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  --format=custom --file="$backup_dir/full/bidops-$stamp.dump"
printf '%s\n' "Full backup written to a worktree-scoped external backup directory. Configure pg_receivewal/WAL archiving for the 4-hour RPO; this script never deletes backups." \
  >&2
