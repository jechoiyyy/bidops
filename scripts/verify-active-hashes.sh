#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_DATABASE_USER:?BIDOPS_DATABASE_USER is required}"
: "${BIDOPS_DATABASE_PASSWORD:?BIDOPS_DATABASE_PASSWORD is required}"
: "${OBJECT_VERIFY_ALIAS:?OBJECT_VERIFY_ALIAS is required}"
manifest="${ACTIVE_HASH_MANIFEST:?ACTIVE_HASH_MANIFEST is required}"
if [ -n "${OBJECT_VERSION_MAPPING_MANIFEST:-}" ]; then
  mapping_manifest="$OBJECT_VERSION_MAPPING_MANIFEST"
elif [ -n "${OBJECT_BACKUP_DIR:-}" ]; then
  # Backward-compatible default for direct operator invocations.  restore.sh
  # always passes the explicit mapping path it just wrote.
  mapping_manifest="$OBJECT_BACKUP_DIR/object-version-mapping.tsv"
else
  printf '%s\n' "OBJECT_VERSION_MAPPING_MANIFEST is required" >&2
  exit 2
fi
[ -r "$manifest" ] || { printf '%s\n' "active hash manifest is unavailable" >&2; exit 2; }
[ -r "$mapping_manifest" ] || { printf '%s\n' "object version mapping manifest is unavailable" >&2; exit 2; }
export PGPASSWORD="$BIDOPS_DATABASE_PASSWORD"

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT
db_manifest="$tmp_dir/db-active-hashes.tsv"
ACTIVE_HASH_MANIFEST="$db_manifest" "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/generate-active-hash-manifest.sh"

validate_object_key() {
  local object_key="$1"
  local namespace="${object_key%%/*}"
  local object_name="${object_key#*/}"
  case "$namespace" in
    source|structure|quarantine|model-response|proposal-pdf) ;;
    *) printf '%s\n' "invalid object namespace in object manifest" >&2; return 2 ;;
  esac
  if [[ -z "$object_name" || "$object_name" == /* || "$object_name" == *$'\n'* || "$object_name" == *$'\t'* || "$object_name" == *'//'* || "$object_name" == '..' || "$object_name" == ../* || "$object_name" == */../* || "$object_name" == */.. || "$object_name" == *'\\'* ]]; then
    printf '%s\n' "unsafe object key in object manifest" >&2
    return 2
  fi
}

validate_active_manifest() {
  local input="$1"
  local output="$2"
  : > "$output"
  while IFS=$'\t' read -r object_key source_version_id expected_sha256 extra; do
    if [[ -z "$object_key" && -z "${source_version_id:-}" && -z "${expected_sha256:-}" && -z "${extra:-}" ]]; then
      continue
    fi
    [ -n "$object_key" ] || { printf '%s\n' "active hash manifest has an empty object key" >&2; return 2; }
    [ -z "${extra:-}" ] || { printf '%s\n' "active hash manifest has too many columns" >&2; return 2; }
    [ -n "$source_version_id" ] && [[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || {
      printf '%s\n' "active hash manifest must contain object key, source version id, and object hash" >&2
      return 2
    }
    validate_object_key "$object_key" || return $?
    if [[ "$source_version_id" == */* || "$source_version_id" == *$'\n'* || "$source_version_id" == *$'\t'* ]]; then
      printf '%s\n' "unsafe source version id in active hash manifest" >&2
      return 2
    fi
    printf '%s\t%s\t%s\n' "$object_key" "$source_version_id" "$expected_sha256" >> "$output"
  done < "$input"
}

validate_mapping_manifest() {
  local input="$1"
  local output="$2"
  : > "$output"
  while IFS=$'\t' read -r object_key source_version_id target_version_id expected_sha256 extra; do
    if [[ -z "$object_key" && -z "${source_version_id:-}" && -z "${target_version_id:-}" && -z "${expected_sha256:-}" && -z "${extra:-}" ]]; then
      continue
    fi
    [ -n "$object_key" ] || { printf '%s\n' "object version mapping has an empty object key" >&2; return 2; }
    [ -z "${extra:-}" ] || { printf '%s\n' "object version mapping has too many columns" >&2; return 2; }
    [ -n "$source_version_id" ] && [ -n "$target_version_id" ] && [[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || {
      printf '%s\n' "object version mapping must contain object key, source version id, target version id, and sha256" >&2
      return 2
    }
    validate_object_key "$object_key" || return $?
    if [[ "$source_version_id" == */* || "$source_version_id" == *$'\n'* || "$source_version_id" == *$'\t'* || "$target_version_id" == */* || "$target_version_id" == *$'\n'* || "$target_version_id" == *$'\t'* ]]; then
      printf '%s\n' "unsafe version id in object version mapping" >&2
      return 2
    fi
    printf '%s\t%s\t%s\t%s\n' "$object_key" "$source_version_id" "$target_version_id" "$expected_sha256" >> "$output"
  done < "$input"
}

active_records="$tmp_dir/active.tsv"
db_active_records="$tmp_dir/db-active.tsv"
mapping_records="$tmp_dir/mapping.tsv"
validate_active_manifest "$manifest" "$active_records"
validate_active_manifest "$db_manifest" "$db_active_records"
validate_mapping_manifest "$mapping_manifest" "$mapping_records"

if ! LC_ALL=C sort "$active_records" > "$tmp_dir/active.sorted" || ! LC_ALL=C sort "$db_active_records" > "$tmp_dir/db-active.sorted"; then
  printf '%s\n' "could not sort active hash manifests" >&2
  exit 2
fi
if ! cmp -s "$tmp_dir/active.sorted" "$tmp_dir/db-active.sorted"; then
  printf '%s\n' "active hash manifest does not match database active object set" >&2
  extra_active="$(comm -23 "$tmp_dir/active.sorted" "$tmp_dir/db-active.sorted")"
  missing_active="$(comm -13 "$tmp_dir/active.sorted" "$tmp_dir/db-active.sorted")"
  [ -z "$extra_active" ] || { printf 'manifest extra: %s\n' "$extra_active" >&2; }
  [ -z "$missing_active" ] || { printf 'manifest missing: %s\n' "$missing_active" >&2; }
  exit 1
fi

duplicate_active="$(awk -F '\t' '{ if (seen[$1]++) print $1 }' "$active_records")"
[ -z "$duplicate_active" ] || { printf 'duplicate active object: %s\n' "$duplicate_active" >&2; exit 1; }
duplicate_mapping_source="$(awk -F '\t' '{ key=$1 "\t" $2; if (seen[key]++) print key }' "$mapping_records")"
[ -z "$duplicate_mapping_source" ] || { printf 'duplicate source mapping: %s\n' "$duplicate_mapping_source" >&2; exit 1; }
duplicate_mapping_target="$(awk -F '\t' '{ key=$1 "\t" $3; if (seen[key]++) print key }' "$mapping_records")"
[ -z "$duplicate_mapping_target" ] || { printf 'duplicate target mapping: %s\n' "$duplicate_mapping_target" >&2; exit 1; }

LC_ALL=C sort -u <(cut -f1 "$active_records") > "$tmp_dir/active.keys"
LC_ALL=C sort -u <(cut -f1 "$mapping_records") > "$tmp_dir/mapping.keys"
extra_keys="$(comm -23 "$tmp_dir/mapping.keys" "$tmp_dir/active.keys")"
missing_keys="$(comm -13 "$tmp_dir/mapping.keys" "$tmp_dir/active.keys")"
[ -z "$extra_keys" ] || { printf 'restored object extra: %s\n' "$extra_keys" >&2; exit 1; }
[ -z "$missing_keys" ] || { printf 'restored object missing: %s\n' "$missing_keys" >&2; exit 1; }

active_targets="$tmp_dir/active-targets.tsv"
mapping_match_errors="$tmp_dir/mapping-match-errors"
if ! awk -F '\t' -v mapping_file="$mapping_records" -v error_file="$mapping_match_errors" '
  BEGIN {
    while ((getline line < mapping_file) > 0) {
      split(line, fields, FS)
      key = fields[1] SUBSEP fields[2]
      target[key] = fields[3]
      hash[key] = fields[4]
    }
    close(mapping_file)
  }
  {
    key = $1 SUBSEP $2
    if (!(key in target)) {
      print "active object has no restored source mapping: " $1 > error_file
      failed = 1
    # The mapping hash is a backup stored-byte hash.  It is comparable with
    # ContentObject.sha256 for the unencrypted namespaces, but model-response
    # ContentObject.sha256 is plaintext; retain the mapping and target checks
    # without comparing those different hash domains.
    } else if (index($1, "model-response/") != 1 && hash[key] != $3) {
      print "active object mapping hash differs from database hash: " $1 > error_file
      failed = 1
    } else {
      print $1 "\t" target[key] "\t" $3
    }
  }
  END { close(error_file); exit failed ? 1 : 0 }
' "$active_records" > "$active_targets"; then
  cat "$mapping_match_errors" >&2
  exit 1
fi

target_records="$tmp_dir/target.tsv"
: > "$target_records"
for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response bidops-proposal-pdf; do
  namespace="${bucket#bidops-}"
  target_listing="$(mc find --versions --print $'{version}\t{}' "$OBJECT_VERIFY_ALIAS/$bucket")"
  while IFS=$'\t' read -r target_version_id rendered_ref extra; do
    if [[ -z "$target_version_id" && -z "${rendered_ref:-}" && -z "${extra:-}" ]]; then
      continue
    fi
    [ -n "$target_version_id" ] || { printf '%s\n' "target object listing has an empty version id" >&2; exit 2; }
    [ -z "${extra:-}" ] || { printf '%s\n' "target object listing has too many columns" >&2; exit 2; }
    suffix=" ($target_version_id)"
    case "$rendered_ref" in
      *"$suffix") target_ref="${rendered_ref%"$suffix"}" ;;
      *) printf '%s\n' "target object listing has no exact version suffix" >&2; exit 2 ;;
    esac
    prefix="$OBJECT_VERIFY_ALIAS/$bucket/"
    case "$target_ref" in
      "$prefix"*) object_name="${target_ref#"$prefix"}" ;;
      *) printf '%s\n' "target object listing escaped its bucket" >&2; exit 2 ;;
    esac
    object_key="$namespace/$object_name"
    validate_object_key "$object_key" || exit $?
    if [[ "$target_version_id" == */* || "$target_version_id" == *$'\n'* || "$target_version_id" == *$'\t'* ]]; then
      printf '%s\n' "unsafe target version id in target object listing" >&2
      exit 2
    fi
    printf '%s\t%s\n' "$object_key" "$target_version_id" >> "$target_records"
  done <<< "$target_listing"
done
duplicate_target="$(awk -F '\t' '{ key=$1 "\t" $2; if (seen[key]++) print key }' "$target_records")"
[ -z "$duplicate_target" ] || { printf 'duplicate target object: %s\n' "$duplicate_target" >&2; exit 1; }
LC_ALL=C sort <(awk -F '\t' '{print $1 "\t" $3}' "$mapping_records") > "$tmp_dir/mapping.targets"
LC_ALL=C sort "$target_records" > "$tmp_dir/target.sorted"
extra_target="$(comm -23 "$tmp_dir/target.sorted" "$tmp_dir/mapping.targets")"
missing_target="$(comm -13 "$tmp_dir/target.sorted" "$tmp_dir/mapping.targets")"
[ -z "$extra_target" ] || { printf 'target object extra: %s\n' "$extra_target" >&2; exit 1; }
[ -z "$missing_target" ] || { printf 'target object missing: %s\n' "$missing_target" >&2; exit 1; }

while IFS=$'\t' read -r object_key target_version_id expected_sha256; do
  [ -n "$object_key" ] || continue
  namespace="${object_key%%/*}"
  object_name="${object_key#*/}"
  case "$namespace" in
    source|structure|quarantine|model-response|proposal-pdf) bucket="bidops-$namespace" ;;
    *) printf '%s\n' "invalid object namespace in active hash manifest" >&2; exit 2 ;;
  esac
  mc stat --version-id "$target_version_id" "$OBJECT_VERIFY_ALIAS/$bucket/$object_name" >/dev/null
  if [ "$namespace" = "model-response" ]; then
    # ContentObject.sha256 for model-response is the plaintext hash.  MinIO
    # stores the encrypted BIDOPS-AESGCM-V1 envelope, so its stored bytes
    # cannot be compared with that plaintext hash.  The target-version stat
    # above remains mandatory; only the stored-byte hash comparison is skipped.
    continue
  fi
  actual_sha256="$(mc cat --version-id "$target_version_id" "$OBJECT_VERIFY_ALIAS/$bucket/$object_name" | sha256sum | awk '{print $1}')"
  [ "$actual_sha256" = "$expected_sha256" ] || { printf '%s\n' "active object hash verification failed" >&2; exit 1; }
done < "$active_targets"
printf '%s\n' "active object presence/version, stored-byte hashes, target version mapping, and database active set verified" >&2
