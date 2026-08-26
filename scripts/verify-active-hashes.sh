#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_DATABASE_USER:?BIDOPS_DATABASE_USER is required}"
: "${BIDOPS_DATABASE_PASSWORD:?BIDOPS_DATABASE_PASSWORD is required}"
: "${OBJECT_BACKUP_DIR:?OBJECT_BACKUP_DIR is required}"
: "${OBJECT_VERIFY_ALIAS:?OBJECT_VERIFY_ALIAS is required}"
manifest="${ACTIVE_HASH_MANIFEST:?ACTIVE_HASH_MANIFEST is required}"
[ -r "$manifest" ] || { printf '%s\n' "active hash manifest is unavailable" >&2; exit 2; }
export PGPASSWORD="$BIDOPS_DATABASE_PASSWORD"
while IFS=$'\t' read -r object_key expected_version_id expected_sha256; do
  [ -n "$object_key" ] || continue
  [ -n "$expected_version_id" ] && [ -n "$expected_sha256" ] || { printf '%s\n' "active hash manifest must contain object key, exact version id, and object hash" >&2; exit 2; }
  namespace="${object_key%%/*}"
  object_name="${object_key#*/}"
  case "$namespace" in
    source|structure|quarantine|model-response) bucket="bidops-$namespace" ;;
    *) printf '%s\n' "invalid object namespace in active hash manifest" >&2; exit 2 ;;
  esac
  # Verify the exact immutable version in the restored target.  The manifest
  # hash is the stored object bytes hash; encrypted model-response objects are
  # never compared with their plaintext ContentObject hash.
  mc stat --version-id "$expected_version_id" "$OBJECT_VERIFY_ALIAS/$bucket/$object_name" >/dev/null
  actual_sha256="$(mc cat --version-id "$expected_version_id" "$OBJECT_VERIFY_ALIAS/$bucket/$object_name" | sha256sum | awk '{print $1}')"
  [ "$actual_sha256" = "$expected_sha256" ] || { printf '%s\n' "active object hash verification failed" >&2; exit 1; }
done < "$manifest"
psql --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username "$BIDOPS_DATABASE_USER" --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  -v ON_ERROR_STOP=1 -Atqc "SELECT 1 FROM bidops.document_bundle LIMIT 1" >/dev/null
printf '%s\n' "active object hashes and database connectivity verified" >&2
