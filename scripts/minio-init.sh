#!/usr/bin/env bash
set -euo pipefail

: "${MINIO_ROOT_USER:?root user is required}"
: "${MINIO_ROOT_PASSWORD:?root password is required}"
: "${BIDOPS_SOURCE_ACCESS_KEY:?source access key is required}"
: "${BIDOPS_SOURCE_SECRET_KEY:?source secret key is required}"
: "${BIDOPS_STRUCTURE_ACCESS_KEY:?structure access key is required}"
: "${BIDOPS_STRUCTURE_SECRET_KEY:?structure secret key is required}"
: "${BIDOPS_STRUCTURE_READ_ACCESS_KEY:?structure read access key is required}"
: "${BIDOPS_STRUCTURE_READ_SECRET_KEY:?structure read secret key is required}"
: "${BIDOPS_QUARANTINE_ACCESS_KEY:?quarantine access key is required}"
: "${BIDOPS_QUARANTINE_SECRET_KEY:?quarantine secret key is required}"
: "${BIDOPS_MODEL_RESPONSE_ACCESS_KEY:?model-response access key is required}"
: "${BIDOPS_MODEL_RESPONSE_SECRET_KEY:?model-response secret key is required}"

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response; do
  mc mb --ignore-existing "local/$bucket" >/dev/null
  # Keep immutable content addressable by its persisted version id.  Re-running
  # this bootstrap is idempotent and never removes prior versions.
  mc version enable "local/$bucket" >/dev/null 2>&1 || true
done

create_user() {
  local name="$1" access="$2" secret="$3"
  mc admin user add local "$access" "$secret" >/dev/null 2>&1 || true
  printf '%s\n' "$name" >/dev/null
}
create_user source "$BIDOPS_SOURCE_ACCESS_KEY" "$BIDOPS_SOURCE_SECRET_KEY"
create_user structure "$BIDOPS_STRUCTURE_ACCESS_KEY" "$BIDOPS_STRUCTURE_SECRET_KEY"
create_user structure-read "$BIDOPS_STRUCTURE_READ_ACCESS_KEY" "$BIDOPS_STRUCTURE_READ_SECRET_KEY"
create_user quarantine "$BIDOPS_QUARANTINE_ACCESS_KEY" "$BIDOPS_QUARANTINE_SECRET_KEY"
create_user model-response "$BIDOPS_MODEL_RESPONSE_ACCESS_KEY" "$BIDOPS_MODEL_RESPONSE_SECRET_KEY"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
cat >"$tmp_dir/source.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:PutObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-source","arn:aws:s3:::bidops-source/*"]}]}
JSON
cat >"$tmp_dir/structure.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:PutObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-structure","arn:aws:s3:::bidops-structure/*"]}]}
JSON
cat >"$tmp_dir/structure-read.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-structure","arn:aws:s3:::bidops-structure/*"]}]}
JSON
cat >"$tmp_dir/quarantine.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:PutObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-quarantine","arn:aws:s3:::bidops-quarantine/*"]}]}
JSON
cat >"$tmp_dir/model-response.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:PutObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-model-response","arn:aws:s3:::bidops-model-response/*"]}]}
JSON
for name in source structure quarantine model-response; do mc admin policy create local "bidops-$name" "$tmp_dir/$name.json" >/dev/null 2>&1 || true; done
mc admin policy attach local bidops-source --user "$BIDOPS_SOURCE_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-structure --user "$BIDOPS_STRUCTURE_ACCESS_KEY" >/dev/null
mc admin policy create local bidops-structure-read "$tmp_dir/structure-read.json" >/dev/null 2>&1 || true
mc admin policy attach local bidops-structure-read --user "$BIDOPS_STRUCTURE_READ_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-quarantine --user "$BIDOPS_QUARANTINE_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-model-response --user "$BIDOPS_MODEL_RESPONSE_ACCESS_KEY" >/dev/null

# Only encrypted model responses expire; source, structure, and quarantine
# buckets retain their versioned objects until an explicit governed process.
mc ilm add --expire-days 90 local/bidops-model-response >/dev/null
