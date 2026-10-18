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
: "${BIDOPS_PROPOSAL_PDF_ACCESS_KEY:?proposal-pdf access key is required}"
: "${BIDOPS_PROPOSAL_PDF_SECRET_KEY:?proposal-pdf secret key is required}"

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
for bucket in bidops-source bidops-structure bidops-quarantine bidops-model-response bidops-proposal-pdf; do
  mc mb --ignore-existing "local/$bucket" >/dev/null
  # Keep immutable content addressable by its persisted version id.  Re-running
  # this bootstrap is idempotent and never removes prior versions: enabling an
  # already-versioned bucket succeeds, so no failure here is safe to swallow.
  # Read the state back rather than trusting the exit status -- `mc version
  # info` exits 0 for an un-versioned bucket too, so the enabled state is the
  # only evidence that the DB's object-version-as-identity premise holds.
  mc version enable "local/$bucket" >/dev/null
  bucket_versioning="$(mc version info --json "local/$bucket")"
  case "$bucket_versioning" in
    *'"versioning":{"status":"Enabled"'*) ;;
    *)
      printf '%s\n' "bucket versioning is not enabled: $bucket" >&2
      exit 1
      ;;
  esac
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
create_user proposal-pdf "$BIDOPS_PROPOSAL_PDF_ACCESS_KEY" "$BIDOPS_PROPOSAL_PDF_SECRET_KEY"

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
cat >"$tmp_dir/proposal-pdf.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:PutObject","s3:ListBucket"],"Resource":["arn:aws:s3:::bidops-proposal-pdf","arn:aws:s3:::bidops-proposal-pdf/*"]}]}
JSON
for name in source structure quarantine model-response proposal-pdf; do mc admin policy create local "bidops-$name" "$tmp_dir/$name.json" >/dev/null 2>&1 || true; done
mc admin policy attach local bidops-source --user "$BIDOPS_SOURCE_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-structure --user "$BIDOPS_STRUCTURE_ACCESS_KEY" >/dev/null
mc admin policy create local bidops-structure-read "$tmp_dir/structure-read.json" >/dev/null 2>&1 || true
mc admin policy attach local bidops-structure-read --user "$BIDOPS_STRUCTURE_READ_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-quarantine --user "$BIDOPS_QUARANTINE_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-model-response --user "$BIDOPS_MODEL_RESPONSE_ACCESS_KEY" >/dev/null
mc admin policy attach local bidops-proposal-pdf --user "$BIDOPS_PROPOSAL_PDF_ACCESS_KEY" >/dev/null

# Encrypted model responses expire after 90 days and RL-04 proposal draft PDFs
# (retention_class proposal-pdf-365d, not company material) after 365 days;
# source, structure, and quarantine buckets retain their versioned objects
# until an explicit governed process.
mc ilm add --expire-days 90 local/bidops-model-response >/dev/null
mc ilm add --expire-days 365 local/bidops-proposal-pdf >/dev/null
