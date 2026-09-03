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
mapping_manifest="$OBJECT_BACKUP_DIR/object-version-mapping.tsv"
[ -r "$version_manifest" ] || { printf '%s\n' "versioned object manifest is unavailable" >&2; exit 2; }
: > "$mapping_manifest"
while IFS=$'\t' read -r object_key source_version_id expected_sha256 extra; do
  if [[ -z "$object_key" && -z "${source_version_id:-}" && -z "${expected_sha256:-}" && -z "${extra:-}" ]]; then
    continue
  fi
  [ -n "$object_key" ] || { printf '%s\n' "versioned object manifest has an empty object key" >&2; exit 2; }
  [ -z "${extra:-}" ] || { printf '%s\n' "versioned object manifest has too many columns" >&2; exit 2; }
  [ -n "$source_version_id" ] && [[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || {
    printf '%s\n' "versioned object manifest must contain object key, source version id, and sha256" >&2
    exit 2
  }
  namespace="${object_key%%/*}"
  object_name="${object_key#*/}"
  case "$namespace" in
    source|structure|quarantine|model-response) bucket="bidops-$namespace" ;;
    *) printf '%s\n' "invalid object namespace in versioned object manifest" >&2; exit 2 ;;
  esac
  if [[ -z "$object_name" || "$object_name" == /* || "$object_name" == *$'\n'* || "$object_name" == *$'\t'* || "$object_name" == *'//'* || "$object_name" == '..' || "$object_name" == ../* || "$object_name" == */../* || "$object_name" == */.. || "$object_name" == *'\\'* || "$source_version_id" == */* || "$source_version_id" == *$'\n'* || "$source_version_id" == *$'\t'* ]]; then
    printf '%s\n' "unsafe object key or source version id in versioned object manifest" >&2
    exit 2
  fi
  source_file="$OBJECT_BACKUP_DIR/$bucket/$object_name.__version_$source_version_id"
  [ -r "$source_file" ] || { printf '%s\n' "versioned object backup is unavailable" >&2; exit 2; }
  backup_sha256="$(sha256sum -- "$source_file" | awk '{print $1}')"
  [ "$backup_sha256" = "$expected_sha256" ] || {
    printf '%s\n' "versioned object backup hash verification failed" >&2
    exit 1
  }
  target_ref="$RESTORE_MINIO_ALIAS/$bucket/$object_name"
  mc cp "$source_file" "$target_ref" >/dev/null
  target_stat="$(mc stat --json --no-list "$target_ref")"
  target_version_id="$(printf '%s\n' "$target_stat" | sed -n 's/.*"versionID":"\([^"]*\)".*/\1/p')"
  [ -n "$target_version_id" ] && [[ "$target_version_id" != *$'\n'* && "$target_version_id" != *$'\t'* ]] || {
    printf '%s\n' "restored object has no target version id" >&2
    exit 1
  }
  printf '%s\t%s\t%s\t%s\n' "$object_key" "$source_version_id" "$target_version_id" "$expected_sha256" >> "$mapping_manifest"
done < "$version_manifest"
export PGPASSWORD="$BIDOPS_DATABASE_PASSWORD"
pg_restore --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username "$BIDOPS_DATABASE_USER" --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  --no-owner "$DUMP_FILE"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/generate-active-hash-manifest.sh"
OBJECT_VERSION_MAPPING_MANIFEST="$mapping_manifest" \
  OBJECT_VERIFY_ALIAS="$RESTORE_MINIO_ALIAS" \
  "$script_dir/verify-active-hashes.sh"
