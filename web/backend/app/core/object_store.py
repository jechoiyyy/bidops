"""Purpose-scoped object storage for Lean v1.

Production uses MinIO with one credential per purpose bucket.  The filesystem
implementation is deliberately available only inside the explicit isolated
pytest boundary; it is not a production fallback.  Callers receive object
metadata so the existing ``content_object_location`` contract can persist the
object key, version and etag without adding tables or APIs.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import secrets
from typing import Protocol
from uuid import uuid4

from .config import Settings, get_settings
from .db import isolated_test_boundary_active


NAMESPACES = ("source", "structure", "quarantine", "model-response")
BUCKETS = {namespace: f"bidops-{namespace}" for namespace in NAMESPACES}
_SAFE_KEY = re.compile(r"^(?:source|structure|quarantine|model-response)/[A-Za-z0-9._/-]+$")
MAX_OBJECT_BYTES = 50 * 1024 * 1024


class ObjectStoreError(RuntimeError):
    """Safe object storage/configuration failure."""


@dataclass(frozen=True)
class ObjectMetadata:
    namespace: str
    object_key: str
    object_version_id: str | None
    etag: str
    size_bytes: int


class ObjectStore(Protocol):
    def put(self, namespace: str, object_key: str, data: bytes, *, content_type: str) -> ObjectMetadata: ...

    def get(self, namespace: str, object_key: str, *, max_bytes: int = MAX_OBJECT_BYTES) -> tuple[bytes, ObjectMetadata]: ...

    def head(self, namespace: str, object_key: str) -> ObjectMetadata: ...


def _validate_namespace(namespace: str) -> None:
    if namespace not in NAMESPACES:
        raise ObjectStoreError("invalid object namespace")


def _validate_key(namespace: str, object_key: str) -> str:
    _validate_namespace(namespace)
    if not isinstance(object_key, str) or not _SAFE_KEY.fullmatch(object_key) or not object_key.startswith(f"{namespace}/"):
        raise ObjectStoreError("invalid object key")
    path = PurePosixPath(object_key)
    if path.is_absolute() or ".." in path.parts or "//" in object_key:
        raise ObjectStoreError("invalid object key")
    return object_key


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FilesystemObjectStore:
    """Bounded filesystem backend for explicit isolated tests only."""

    def __init__(self, root: Path) -> None:
        self.root = (Path(root).resolve() / "document-assets").resolve()

    def _path(self, namespace: str, object_key: str) -> Path:
        key = _validate_key(namespace, object_key)
        candidate = (self.root / Path(*PurePosixPath(key).parts)).resolve()
        candidate.relative_to(self.root)
        return candidate

    def put(self, namespace: str, object_key: str, data: bytes, *, content_type: str) -> ObjectMetadata:  # noqa: ARG002
        path = self._path(namespace, object_key)
        if not isinstance(data, bytes) or len(data) > MAX_OBJECT_BYTES:
            raise ObjectStoreError("object size limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.staging")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return ObjectMetadata(namespace, object_key, _digest(data), _digest(data), len(data))

    def get(self, namespace: str, object_key: str, *, max_bytes: int = MAX_OBJECT_BYTES) -> tuple[bytes, ObjectMetadata]:
        path = self._path(namespace, object_key)
        try:
            size = path.stat().st_size
            if size > max_bytes or size > MAX_OBJECT_BYTES:
                raise ObjectStoreError("object size limit")
            data = path.read_bytes()
        except ObjectStoreError:
            raise
        except OSError as error:
            raise ObjectStoreError("object unavailable") from error
        metadata = ObjectMetadata(namespace, object_key, _digest(data), _digest(data), len(data))
        return data, metadata

    def head(self, namespace: str, object_key: str) -> ObjectMetadata:
        data, metadata = self.get(namespace, object_key)
        return ObjectMetadata(namespace, object_key, metadata.object_version_id, metadata.etag, len(data))


class MinioObjectStore:
    """MinIO backend with purpose-specific clients and no delete capability."""

    def __init__(self, settings: Settings, namespaces: tuple[str, ...], read_namespaces: tuple[str, ...] = ()) -> None:
        endpoint = settings.object_store_endpoint
        if settings.object_store_backend != "minio" or not endpoint:
            raise ObjectStoreError("MinIO object storage is not configured")
        try:
            from minio import Minio
        except ImportError as error:  # pragma: no cover - image dependency guard
            raise ObjectStoreError("MinIO client is unavailable") from error
        self._clients: dict[str, object] = {}
        for namespace in namespaces:
            access_key = settings.object_store_credentials(namespace, read_only=namespace in read_namespaces)[0]
            secret_key = settings.object_store_credentials(namespace, read_only=namespace in read_namespaces)[1]
            if not access_key or not secret_key:
                raise ObjectStoreError(f"MinIO credentials are missing for {namespace}")
            self._clients[namespace] = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=settings.object_store_secure)

    @staticmethod
    def _key(object_key: str) -> str:
        return object_key.split("/", 1)[1]

    def _client(self, namespace: str):
        _validate_namespace(namespace)
        try:
            return self._clients[namespace]
        except KeyError as error:
            raise ObjectStoreError("object namespace is not configured") from error

    def put(self, namespace: str, object_key: str, data: bytes, *, content_type: str) -> ObjectMetadata:
        key = _validate_key(namespace, object_key)
        if not isinstance(data, bytes) or len(data) > MAX_OBJECT_BYTES:
            raise ObjectStoreError("object size limit")
        try:
            result = self._client(namespace).put_object(
                BUCKETS[namespace], self._key(key), io.BytesIO(data), len(data), content_type=content_type,
            )
            version_id = getattr(result, "version_id", None) or None
            etag = str(getattr(result, "etag", "")).strip('"') or _digest(data)
            return ObjectMetadata(namespace, key, version_id, etag, len(data))
        except Exception as error:
            raise ObjectStoreError("object write failed") from error

    def get(self, namespace: str, object_key: str, *, max_bytes: int = MAX_OBJECT_BYTES) -> tuple[bytes, ObjectMetadata]:
        key = _validate_key(namespace, object_key)
        response = None
        try:
            response = self._client(namespace).get_object(BUCKETS[namespace], self._key(key))
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes or total > MAX_OBJECT_BYTES:
                    raise ObjectStoreError("object size limit")
                chunks.append(chunk)
            data = b"".join(chunks)
            metadata = self._metadata(namespace, key, len(data))
            return data, metadata
        except ObjectStoreError:
            raise
        except Exception as error:
            raise ObjectStoreError("object unavailable") from error
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def _metadata(self, namespace: str, object_key: str, size: int | None = None) -> ObjectMetadata:
        try:
            stat = self._client(namespace).stat_object(BUCKETS[namespace], self._key(object_key))
            return ObjectMetadata(
                namespace,
                object_key,
                getattr(stat, "version_id", None) or None,
                str(getattr(stat, "etag", "")).strip('"'),
                int(size if size is not None else getattr(stat, "size", 0)),
            )
        except Exception as error:
            raise ObjectStoreError("object metadata unavailable") from error

    def head(self, namespace: str, object_key: str) -> ObjectMetadata:
        return self._metadata(namespace, _validate_key(namespace, object_key))


def object_store(root: Path | None = None, *, namespaces: tuple[str, ...] = (), read_namespaces: tuple[str, ...] = ()) -> ObjectStore:
    settings = get_settings()
    backend = settings.object_store_backend
    if backend == "filesystem":
        if not isolated_test_boundary_active():
            raise ObjectStoreError("filesystem object storage is test-only")
        return FilesystemObjectStore(root or settings.attachments_dir or settings.data_dir)
    if backend == "minio":
        return MinioObjectStore(settings, namespaces=namespaces, read_namespaces=read_namespaces)
    if isolated_test_boundary_active():
        return FilesystemObjectStore(root or settings.attachments_dir or settings.data_dir)
    raise ObjectStoreError("production object storage requires MinIO")


def assert_object_store_runtime(*, require_model_response: bool = False) -> None:
    """Fail fast on production startup when MinIO/purpose credentials are absent."""

    settings = get_settings()
    if isolated_test_boundary_active():
        return
    namespaces = ("structure", "model-response") if require_model_response else ("source", "structure", "quarantine")
    read_namespaces = ("structure",) if require_model_response else ()
    object_store(namespaces=namespaces, read_namespaces=read_namespaces)
    if require_model_response and (not settings.model_response_encryption_key or not settings.model_response_encryption_key_ref):
        raise ObjectStoreError("model-response encryption key and external key reference are required")


def _decode_key(value: str) -> bytes:
    text = value.strip()
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        decoded = b""
    if len(decoded) in {16, 24, 32}:
        return decoded
    try:
        decoded = bytes.fromhex(text)
    except ValueError as error:
        raise ObjectStoreError("model-response encryption key is not valid") from error
    if len(decoded) not in {16, 24, 32}:
        raise ObjectStoreError("model-response encryption key length is invalid")
    return decoded


class EncryptedModelResponseStore:
    """AES-GCM wrapper storing ciphertext only in model-response."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str) -> dict[str, object]:  # noqa: ARG002
        key_value = self.settings.model_response_encryption_key
        key_ref = self.settings.model_response_encryption_key_ref
        if not key_value or not key_ref:
            raise ObjectStoreError("model-response encryption configuration is missing")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = _decode_key(key_value)
            nonce = secrets.token_bytes(12)
            ciphertext = AESGCM(key).encrypt(nonce, data, None)
        except ObjectStoreError:
            raise
        except Exception as error:
            raise ObjectStoreError("model-response encryption failed") from error
        envelope = b"BIDOPS-AESGCM-V1\0" + nonce + ciphertext
        key = f"model-response/{uuid4().hex}.bin"
        metadata = object_store(namespaces=("model-response",)).put("model-response", key, envelope, content_type="application/octet-stream")
        return {
            "encrypted": True,
            "object_key": metadata.object_key,
            "object_version_id": metadata.object_version_id,
            "etag": metadata.etag,
            "encryption_key_ref": key_ref,
            "plaintext_sha256": _digest(data),
            "plaintext_size_bytes": len(data),
        }


__all__ = [
    "BUCKETS", "EncryptedModelResponseStore", "FilesystemObjectStore", "MAX_OBJECT_BYTES",
    "MinioObjectStore", "NAMESPACES", "ObjectMetadata", "ObjectStoreError", "assert_object_store_runtime", "object_store",
]
