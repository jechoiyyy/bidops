#!/usr/bin/env bash
set -euo pipefail

: "${MINIO_ALIAS:?MINIO_ALIAS is required}"
: "${OBJECT_BACKUP_DIR:?OBJECT_BACKUP_DIR is required}"
mkdir -p "$OBJECT_BACKUP_DIR"
manifest="$OBJECT_BACKUP_DIR/object-versions.tsv"
: > "$manifest"
for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response; do
  namespace="${bucket#bidops-}"
  # This pinned mc has no mirror --versions flag. Enumerate every immutable
  # version explicitly, copy it under a version-qualified backup filename, and
  # write the exact source version plus stored-byte hash to the manifest.
  # ``--print`` gives us a tab-separated version id and a rendered object
  # reference.  mc still appends " (version)" to the rendered reference, so
  # remove that exact suffix instead of splitting on the first parenthesis;
  # object names may themselves contain parentheses and spaces.
  mc find --versions --print $'{version}\t{}' "$MINIO_ALIAS/$bucket" | while IFS=$'\t' read -r version_id rendered_ref extra; do
    [ -n "$version_id" ] && [ -n "$rendered_ref" ] && [ -z "${extra:-}" ] || {
      printf '%s\n' "invalid version listing from mc" >&2
      exit 2
    }
    suffix=" ($version_id)"
    case "$rendered_ref" in
      *"$suffix") object_ref="${rendered_ref%"$suffix"}" ;;
      *) printf '%s\n' "mc version listing has no exact version suffix" >&2; exit 2 ;;
    esac
    prefix="$MINIO_ALIAS/$bucket/"
    case "$object_ref" in
      "$prefix"*) object_name="${object_ref#"$prefix"}" ;;
      *) printf '%s\n' "mc version listing escaped its bucket" >&2; exit 2 ;;
    esac
    if [[ -z "$object_name" || "$object_name" == /* || "$object_name" == *$'\n'* || "$object_name" == *$'\t'* || "$object_name" == *'//'* || "$object_name" == '..' || "$object_name" == ../* || "$object_name" == */../* || "$object_name" == */.. || "$object_name" == *'\\'* ]]; then
      printf '%s\n' "unsafe object name in mc version listing" >&2
      exit 2
    fi
    if [[ "$version_id" == */* || "$version_id" == *$'\n'* || "$version_id" == *$'\t'* ]]; then
      printf '%s\n' "unsafe object version id in mc version listing" >&2
      exit 2
    fi
    backup_file="$OBJECT_BACKUP_DIR/$bucket/$object_name.__version_$version_id"
    mkdir -p "$(dirname "$backup_file")"
    source_sha256="$(mc cat --version-id "$version_id" "$object_ref" | sha256sum | awk '{print $1}')"
    [[ "$source_sha256" =~ ^[0-9a-f]{64}$ ]] || {
      printf '%s\n' "could not hash source object bytes" >&2
      exit 2
    }
    mc cp --version-id "$version_id" "$object_ref" "$backup_file" >/dev/null
    backup_sha256="$(sha256sum -- "$backup_file" | awk '{print $1}')"
    [ "$backup_sha256" = "$source_sha256" ] || {
      printf '%s\n' "backup object hash does not match source object" >&2
      exit 1
    }
    printf '%s\t%s\t%s\n' "$namespace/$object_name" "$version_id" "$backup_sha256" >> "$manifest"
  done
done
printf '%s\n' "Version-aware object copy completed; exact object-versions.tsv written; no source objects were deleted." >&2
