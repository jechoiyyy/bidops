"""Live MinIO checks (opt in with BIDOPS_MINIO_E2E=1)."""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import object_store as storage
from app.core.object_store import EncryptedModelResponseStore, ObjectStoreError
from app.core.config import get_settings


pytestmark = pytest.mark.skipif(os.environ.get("BIDOPS_MINIO_E2E") != "1", reason="requires the isolated MinIO service")


def test_minio_purpose_buckets_restart_persistence():
    settings = get_settings()
    assert settings.object_store_backend == "minio"
    suffix = uuid4().hex
    source_key = f"source/e2e-{suffix}.pdf"
    structure_key = f"structure/e2e-{suffix}.json"
    quarantine_key = f"quarantine/e2e-{suffix}.pdf"
    source_data = b"source-persistence"
    structure_data = b'{"source_sha256":"' + hashlib.sha256(source_data).hexdigest().encode() + b'"}'

    for namespace, key, data in (
        ("quarantine", quarantine_key, source_data),
        ("source", source_key, source_data),
        ("structure", structure_key, structure_data),
    ):
        store = storage.object_store(namespaces=(namespace,))
        metadata = store.put(namespace, key, data, content_type="application/octet-stream")
        assert metadata.object_key == key and metadata.object_version_id and metadata.etag

    # A fresh client is the web-restart persistence check; no filesystem path
    # or in-memory object is consulted.
    restarted = storage.object_store(namespaces=("source", "structure"))
    assert restarted.get("source", source_key)[0] == source_data
    assert restarted.get("structure", structure_key)[0] == structure_data



def test_minio_encrypted_model_response_is_ciphertext_only_and_authenticated():
    settings = get_settings()
    assert settings.model_response_encryption_key and settings.model_response_encryption_key_ref
    plaintext = b'{"private_prompt":"do-not-leak","raw":"model output"}'
    encrypted = EncryptedModelResponseStore(settings).put_encrypted(
        plaintext, retention_days=90, content_type="application/json"
    )
    model_store = storage.object_store(namespaces=("model-response",))
    ciphertext, _metadata = model_store.get("model-response", str(encrypted["object_key"]))
    assert plaintext not in ciphertext
    assert ciphertext.startswith(b"BIDOPS-AESGCM-V1\0")
    assert encrypted["encryption_key_ref"] == settings.model_response_encryption_key_ref
    envelope = ciphertext[len(b"BIDOPS-AESGCM-V1\0"):]
    nonce, body = envelope[:12], envelope[12:]
    key = storage._decode_key(settings.model_response_encryption_key)  # type: ignore[arg-type]
    assert AESGCM(key).decrypt(nonce, body, None) == plaintext
    tampered_nonce = bytearray(nonce)
    tampered_nonce[0] ^= 1
    with pytest.raises(InvalidTag):
        AESGCM(key).decrypt(bytes(tampered_nonce), body, None)
    tampered_body = bytearray(body)
    tampered_body[-1] ^= 1
    with pytest.raises(InvalidTag):
        AESGCM(key).decrypt(nonce, bytes(tampered_body), None)


def test_minio_missing_unrelated_and_required_credentials_fail_closed(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    missing_source = settings.model_copy(update={"source_access_key": None, "source_secret_key": None})
    monkeypatch.setattr(storage, "get_settings", lambda: missing_source)
    with pytest.raises(ObjectStoreError):
        storage.object_store(namespaces=("source",))

    missing_model = settings.model_copy(update={"model_response_access_key": None, "model_response_secret_key": None})
    monkeypatch.setattr(storage, "get_settings", lambda: missing_model)
    with pytest.raises(ObjectStoreError):
        storage.object_store(namespaces=("model-response",))
