"""Purpose-scoped object-store and fail-fast boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
import json
import io
from pathlib import Path

import pytest

from app.core import object_store as storage


class FakeMinio:
    clients: list[tuple[str, str, str, bool]] = []

    def __init__(self, endpoint, *, access_key, secret_key, secure):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self.__class__.clients.append((endpoint, access_key, secret_key, secure))


def fake_settings(**overrides):
    values = {
        "object_store_backend": "minio",
        "object_store_endpoint": "minio:9000",
        "object_store_secure": False,
        "source_access_key": "source",
        "source_secret_key": "source-secret",
        "structure_access_key": "structure",
        "structure_secret_key": "structure-secret",
        "structure_read_access_key": "structure-read",
        "structure_read_secret_key": "structure-read-secret",
        "quarantine_access_key": "quarantine",
        "quarantine_secret_key": "quarantine-secret",
        "model_response_access_key": "model",
        "model_response_secret_key": "model-secret",
        "model_response_encryption_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "model_response_encryption_key_ref": "external-ref",
    }
    values.update(overrides)

    def credentials(namespace: str, *, read_only: bool = False):
        if namespace == "structure" and read_only:
            return values["structure_read_access_key"], values["structure_read_secret_key"]
        return values[f"{namespace.replace('-', '_')}_access_key"], values[f"{namespace.replace('-', '_')}_secret_key"]

    result = SimpleNamespace(**values)
    result.object_store_credentials = credentials
    return result


def test_each_factory_only_constructs_requested_namespace(monkeypatch):
    FakeMinio.clients = []
    monkeypatch.setitem(__import__("sys").modules, "minio", SimpleNamespace(Minio=FakeMinio))
    monkeypatch.setattr(storage, "get_settings", lambda: fake_settings())
    store = storage.object_store(namespaces=("structure", "model-response"), read_namespaces=("structure",))
    assert set(store._clients) == {"structure", "model-response"}  # type: ignore[attr-defined]
    assert {row[1] for row in FakeMinio.clients} == {"structure-read", "model"}
    FakeMinio.clients = []
    analysis_settings = fake_settings(structure_access_key=None, structure_secret_key=None)
    monkeypatch.setattr(storage, "get_settings", lambda: analysis_settings)
    analysis_store = storage.object_store(namespaces=("structure", "model-response"), read_namespaces=("structure",))
    assert set(analysis_store._clients) == {"structure", "model-response"}  # type: ignore[attr-defined]
    assert {row[1] for row in FakeMinio.clients} == {"structure-read", "model"}


@pytest.mark.parametrize("version", ["frozen-version", "missing-version"])
def test_minio_reads_the_pinned_version_without_latest_fallback(monkeypatch, version):
    calls = []

    class Response(io.BytesIO):
        def release_conn(self):
            pass

    class VersionedMinio(FakeMinio):
        def get_object(self, bucket, key, *, version_id=None):
            calls.append(("get", version_id))
            if version_id == "missing-version":
                raise RuntimeError("missing")
            return Response(b"frozen" if version_id else b"newer")

        def stat_object(self, bucket, key, *, version_id=None):
            calls.append(("stat", version_id))
            return SimpleNamespace(version_id=version_id or "latest", etag="etag", size=6)

    monkeypatch.setitem(__import__("sys").modules, "minio", SimpleNamespace(Minio=VersionedMinio))
    store = storage.MinioObjectStore(fake_settings(), ("source",))
    if version == "missing-version":
        with pytest.raises(storage.ObjectStoreError):
            store.get("source", "source/profile.md", version_id=version)
        assert calls == [("get", version)]
    else:
        data, metadata = store.get("source", "source/profile.md", version_id=version)
        assert data == b"frozen"
        assert metadata.object_version_id == version
        assert calls == [("get", version), ("stat", version)]


def test_web_runtime_requires_only_document_buckets(monkeypatch):
    monkeypatch.setattr(storage, "isolated_test_boundary_active", lambda: False)
    monkeypatch.setattr(storage, "get_settings", lambda: fake_settings(model_response_access_key=None, model_response_secret_key=None))
    monkeypatch.setitem(__import__("sys").modules, "minio", SimpleNamespace(Minio=FakeMinio))
    storage.assert_object_store_runtime()


def test_analysis_runtime_requires_structure_reader_and_model_but_not_source_quarantine(monkeypatch):
    monkeypatch.setattr(storage, "isolated_test_boundary_active", lambda: False)
    settings = fake_settings(source_access_key=None, source_secret_key=None, structure_access_key=None, structure_secret_key=None, quarantine_access_key=None, quarantine_secret_key=None)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setitem(__import__("sys").modules, "minio", SimpleNamespace(Minio=FakeMinio))
    storage.assert_object_store_runtime(require_model_response=True)
    with pytest.raises(storage.ObjectStoreError):
        storage.object_store(namespaces=("source",))
    original_credentials = settings.object_store_credentials
    settings.object_store_credentials = lambda namespace, *, read_only=False: (None, None) if namespace == "structure" and read_only else original_credentials(namespace, read_only=read_only)
    with pytest.raises(storage.ObjectStoreError):
        storage.assert_object_store_runtime(require_model_response=True)


def test_filesystem_backend_is_rejected_outside_isolated_test_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "isolated_test_boundary_active", lambda: False)
    monkeypatch.setattr(storage, "get_settings", lambda: fake_settings(object_store_backend="filesystem", attachments_dir=tmp_path))
    with pytest.raises(storage.ObjectStoreError):
        storage.object_store(tmp_path, namespaces=("source",))


def test_encrypted_model_response_has_no_plaintext_and_is_authenticated(monkeypatch, tmp_path: Path):
    settings = fake_settings(object_store_backend="filesystem", attachments_dir=tmp_path)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    plaintext = json.dumps({"prompt": "private", "answer": "do not expose"}).encode()
    result = storage.EncryptedModelResponseStore(settings).put_encrypted(
        plaintext, retention_days=90, content_type="application/json"
    )
    assert result["encrypted"] is True
    assert result["object_key"].startswith("model-response/")
    assert result["encryption_key_ref"] == "external-ref"
    backend = storage.object_store(tmp_path, namespaces=("model-response",))
    ciphertext, metadata = backend.get("model-response", str(result["object_key"]))
    assert plaintext not in ciphertext
    assert ciphertext.startswith(b"BIDOPS-AESGCM-V1\0")
    assert metadata.etag == result["etag"]
