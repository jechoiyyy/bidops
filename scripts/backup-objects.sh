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
  mc find --versions "$MINIO_ALIAS/$bucket" | while IFS= read -r entry; do
    object_ref="${entry%% (*}"
    version_id="${entry##*(}"
    version_id="${version_id%)}"
    [ -n "$object_ref" ] && [ -n "$version_id" ] || continue
    object_name="${object_ref#"$MINIO_ALIAS/$bucket/"}"
    backup_file="$OBJECT_BACKUP_DIR/$bucket/$object_name.__version_$version_id"
    mkdir -p "$(dirname "$backup_file")"
    mc cp --version-id "$version_id" "$object_ref" "$backup_file" >/dev/null
    object_sha256="$(mc cat --version-id "$version_id" "$object_ref" | sha256sum)"
    object_sha256="${object_sha256%% *}"
    printf '%s\t%s\t%s\n' "$namespace/$object_name" "$version_id" "$object_sha256" >> "$manifest"
  done
done
printf '%s\n' "Version-aware object copy completed; exact object-versions.tsv written; no source objects were deleted." >&2
