"""Read-only object/version verification, run inside the saved application image.

Input on stdin contains credentials. Output contains identifiers and hashes only.
Missing source references are reported as baseline issues, never repaired.
"""

import base64
import hashlib
import json
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from minio import Minio
from sqlalchemy import create_engine, text


def check(config):
    client = Minio("minio:9000", access_key=config["minio_user"],
                   secret_key=config["minio_password"], secure=False)
    versions = {}
    issues = []
    for namespace in ("source", "structure", "quarantine", "model-response", "proposal-pdf"):
        bucket = "bidops-" + namespace
        if client.get_bucket_versioning(bucket).status != "Enabled":
            raise ValueError("bucket versioning disabled")
        for obj in client.list_objects(bucket, recursive=True, include_version=True):
            identity = namespace + "/" + obj.object_name + "@" + str(obj.version_id)
            value = {"version": obj.version_id, "delete_marker": bool(obj.is_delete_marker),
                     "latest": bool(obj.is_latest), "size": obj.size}
            if not obj.is_delete_marker:
                response = client.get_object(bucket, obj.object_name, version_id=obj.version_id)
                try:
                    h = hashlib.sha256()
                    for chunk in response.stream(1024 * 1024):
                        h.update(chunk)
                    value["sha256"] = h.hexdigest()
                finally:
                    response.close()
                    response.release_conn()
            versions[identity] = value
    engine = create_engine(config["database_url"], connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as connection:
        rows = connection.execute(text("""SELECT l.id, l.namespace_key, l.object_key,
            l.object_version_id, o.sha256 FROM bidops.content_object_location l
            JOIN bidops.content_object o ON o.id=l.content_object_id
            WHERE l.status='verified' AND l.purged_at IS NULL ORDER BY l.id""")).mappings().all()
        for row in rows:
            identity = row["object_key"] + "@" + str(row["object_version_id"])
            saved = versions.get(identity)
            reason = None
            if not saved or saved["delete_marker"]:
                reason = "missing_version"
            elif row["namespace_key"] != "model-response":
                if saved["sha256"] != row["sha256"]:
                    reason = "hash_mismatch"
            else:
                try:
                    key = config["model_key"].strip()
                    try:
                        decoded = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
                    except ValueError:
                        decoded = b""
                    if len(decoded) not in (16, 24, 32):
                        decoded = bytes.fromhex(key)
                    response = client.get_object("bidops-model-response", row["object_key"].split("/", 1)[1],
                                                 version_id=row["object_version_id"])
                    try:
                        envelope = response.read()
                    finally:
                        response.close()
                        response.release_conn()
                    prefix = b"BIDOPS-AESGCM-V1\0"
                    if not envelope.startswith(prefix):
                        raise ValueError("unknown envelope")
                    offset = len(prefix)
                    plain = AESGCM(decoded).decrypt(envelope[offset:offset + 12], envelope[offset + 12:], None)
                    if hashlib.sha256(plain).hexdigest() != row["sha256"]:
                        reason = "plaintext_hash_mismatch"
                except Exception:
                    reason = "model_response_decryption_failed"
            if reason:
                issues.append({"location_id": str(row["id"]), "reason": reason})
    engine.dispose()
    return {"versions": versions, "active_references": len(rows), "issues": issues}


if __name__ == "__main__":
    try:
        print(json.dumps(check(json.load(sys.stdin)), sort_keys=True))
    except Exception:
        print("object check failed; sensitive details suppressed", file=sys.stderr)
        sys.exit(1)
