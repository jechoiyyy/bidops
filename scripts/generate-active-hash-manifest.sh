#!/usr/bin/env bash
set -euo pipefail

: "${BIDOPS_DATABASE_URL:?BIDOPS_DATABASE_URL is required}"
: "${BIDOPS_DATABASE_HOST:?BIDOPS_DATABASE_HOST is required}"
: "${BIDOPS_DATABASE_USER:?BIDOPS_DATABASE_USER is required}"
: "${BIDOPS_DATABASE_PASSWORD:?BIDOPS_DATABASE_PASSWORD is required}"
: "${ACTIVE_HASH_MANIFEST:?ACTIVE_HASH_MANIFEST is required}"

manifest_dir="$(dirname -- "$ACTIVE_HASH_MANIFEST")"
mkdir -p "$manifest_dir"
tmp_manifest="$(mktemp "$manifest_dir/.active-hashes.tsv.XXXXXX")"
trap 'rm -f -- "$tmp_manifest"' EXIT

export PGPASSWORD="$BIDOPS_DATABASE_PASSWORD"

# A physical object is represented by ContentObjectLocation.  Its
# content_object_id joins the byte identity in ContentObject, while the
# location row owns the namespace, key, and persisted MinIO version.  A
# verified, non-purged location is the active object set; the business tables
# reference the same ContentObject identity through
# document_version.content_object_id, document_structure.payload_content_object_id,
# document_bundle_item.content_object_id, profile_evidence.content_object_id, and
# deep_review_stage.raw_response_content_object_id; content_scan.content_object_id
# is scan metadata for that same identity.  None of those columns contains a
# second physical key/version pair.  Keep this query as the recovery source of truth.
psql --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username "$BIDOPS_DATABASE_USER" --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM bidops.content_object_location AS location
    LEFT JOIN bidops.content_object AS content
      ON content.id = location.content_object_id
    WHERE location.status = 'verified'
      AND location.purged_at IS NULL
      AND (
        location.namespace_key NOT IN ('source', 'structure', 'quarantine', 'model-response')
        OR location.object_key IS NULL
        OR location.object_version_id IS NULL
        OR content.id IS NULL
        OR content.sha256 IS NULL
        OR content.sha256 !~ '^[0-9a-f]{64}$'
        OR location.object_key = location.namespace_key || '/'
        OR position('//' IN location.object_key) > 0
        OR position('/../' IN location.object_key) > 0
        OR right(location.object_key, 3) = '/..'
        OR left(location.object_key, 3) = '../'
        OR position(chr(92) IN location.object_key) > 0
        OR position(chr(9) IN location.object_key) > 0
        OR position(chr(10) IN location.object_key) > 0
        OR position(chr(13) IN location.object_key) > 0
        OR position(chr(9) IN location.object_version_id) > 0
        OR position(chr(10) IN location.object_version_id) > 0
        OR position(chr(13) IN location.object_version_id) > 0
        OR position(chr(47) IN location.object_version_id) > 0
        OR left(location.object_key, length(location.namespace_key) + 1)
             <> location.namespace_key || '/'
      )
  ) THEN
    RAISE EXCEPTION 'active object location metadata is invalid';
  END IF;
END
$$;

SQL

psql --host "$BIDOPS_DATABASE_HOST" --port "${BIDOPS_DATABASE_PORT:-5432}" \
  --username "$BIDOPS_DATABASE_USER" --dbname "${BIDOPS_DATABASE_NAME:-bidops}" \
  -v ON_ERROR_STOP=1 -At -F $'\t' > "$tmp_manifest" <<'SQL'

-- Keep the existing three-column manifest: the namespace in object_key is
-- the hash-semantics discriminator.  source, structure, and quarantine rows
-- use ContentObject.sha256 as their stored-byte hash.  model-response rows
-- intentionally carry the existing plaintext ContentObject.sha256 instead,
-- because MinIO stores their encrypted response envelope.  The verifier
-- therefore checks model-response presence and target version only.
SELECT location.object_key, location.object_version_id, content.sha256
FROM bidops.content_object_location AS location
JOIN bidops.content_object AS content
  ON content.id = location.content_object_id
WHERE location.status = 'verified'
  AND location.purged_at IS NULL
ORDER BY location.object_key, location.object_version_id, location.id;
SQL

mv -f -- "$tmp_manifest" "$ACTIVE_HASH_MANIFEST"
trap - EXIT
printf '%s\n' "Active object hash manifest generated from the database." >&2
