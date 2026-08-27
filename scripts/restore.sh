#!/usr/bin/env bash
set -euo pipefail

: "${OBJECT_BACKUP_DIR:?OBJECT_BACKUP_DIR is required}"
: "${DUMP_FILE:?DUMP_FILE is required}"
: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_DATABASE_USER:?BIDOPS_DATABASE_USER is required}"
: "${BIDOPS_DATABASE_PASSWORD:?BIDOPS_DATABASE_PASSWORD is required}"
: "${ACTIVE_HASH_MANIFEST:?ACTIVE_HASH_MANIFEST is required}"
: "${RESTORE_MINIO_ALIAS:?RESTORE_MINIO_ALIAS is required}"

[ -d "$OBJECT_BACKUP_DIR" ] || { printf '%s\n' "object backup directory is unavailable" >&2; exit 2; }
[ -r "$DUMP_FILE" ] || { printf '%s\n' "database dump is unavailable" >&2; exit 2; }
# Restore is intentionally non-destructive: provision an empty target, copy
# versioned objects first, then restore DB state, and finally verify hashes.
# No dropdb, volume deletion, or source-object deletion is part of this flow.
printf '%s\n' "Copy versioned objects into the isolated restore target before DB restore." >&2
version_manifest="$OBJECT_BACKUP_DIR/object-versions.tsv"
[ -r "$version_manifest" ] || { printf '%s\n' "versioned object manifest is unavailable" >&2; exit 2; }
while IFS=$'\t' read -r object_key expected_version_id expected_sha256; do
  [ -n "$object_key" ] || continue
  namespace="${object_key%%/*}"
  object_name="${object_key#*/}"
  case "$namespace" in
    source|structure|quarantine|model-response) bucket="bidops-$namespace" ;;
    *) printf '%s\n' "invalid object namespace in versioned object manifest" >&2; exit 2 ;;
  esac
  source_file="$OBJECT_BACKUP_DIR/$bucket/$object_name.__version_$expected_version_id"
  [ -r "$source_file" ] || { printf '%s\n' "versioned object backup is unavailable" >&2; exit 2; }
  mc cp "$source_file" "$RESTORE_MINIO_ALIAS/$bucket/$object_name" >/dev/null
done < "$version_manifest"
export PGPASSWORD="$BIDOPS_DATABASE_PASSWORD"
pg_restore --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username "$BIDOPS_DATABASE_USER" --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  --no-owner "$DUMP_FILE"
OBJECT_VERIFY_ALIAS="$RESTORE_MINIO_ALIAS" "$(dirname "$0")/verify-active-hashes.sh"
