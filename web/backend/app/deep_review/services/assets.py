"""Bytes-first asset storage and provider acquisition for document bundles.

The application deliberately keeps this module small and boring: uploads are
streamed to a server-generated quarantine key, inspected from those bytes, and
only then copied to a source key.  No caller can provide a storage path or an
arbitrary URL.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import stat
import time
import uuid
from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from fastapi import UploadFile

from ...core.config import Settings, get_settings
from ..document_mcp.errors import DocumentProcessingError
from ..document_mcp.processor import ClamAVChecker, DocumentProcessor, ProcessedDocument
from ..document_mcp.safety import MAX_INPUT_BYTES
from ...core.object_store import FilesystemObjectStore, ObjectMetadata, ObjectStoreError, object_store

MAX_ASSET_BYTES = MAX_INPUT_BYTES
UPLOAD_CHUNK_BYTES = 1024 * 1024
PROVIDER_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 5
SUPPORTED_EXTENSIONS = {
    ".hwp": "application/x-hwp",
    ".hwpx": "application/hwp+zip",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
EICAR_MARKER = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class AssetError(RuntimeError):
    """Safe asset failure suitable for the document-bundle service."""

    def __init__(self, code: str, message: str, *, blocked: bool = True) -> None:
        self.code = code
        self.message = message
        self.blocked = blocked
        super().__init__(message)


class ProviderSecurityError(AssetError):
    """Provider URL, redirect, DNS, or response-limit violation."""


@dataclass(frozen=True)
class ProviderResponse:
    body: bytes
    final_url: str
    suggested_filename: str | None = None


# ``kw_only`` is deliberate: the twelve fields below were once passed
# positionally and a caller that omitted three of them silently shifted the
# object-store identity into the provenance slots.  Keywords make that class
# of defect impossible rather than merely unlikely.
@dataclass(frozen=True, kw_only=True)
class QuarantinedAsset:
    path: Path
    filename: str
    size_bytes: int
    sha256: str
    declared_media_type: str | None
    source_kind: str
    source_system: str | None = None
    source_attachment_key: str | None = None
    source_url: str | None = None
    object_key: str | None = None
    object_version_id: str | None = None
    object_etag: str | None = None


@dataclass(frozen=True)
class InspectedAsset:
    asset: QuarantinedAsset
    detected_mime: str
    processed: ProcessedDocument | None
    safety_status: str
    scan_status: str
    error_code: str | None = None
    warnings: tuple[str, ...] = ()


def _contains_filename_control(value: str) -> bool:
    return any(ord(character) <= 0x1F or 0x7F <= ord(character) <= 0x9F for character in value)


def _filename_last_component(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _validate_suggested_filename(value: str) -> str | None:
    if _contains_filename_control(value):
        return None
    value = _filename_last_component(value)
    if not value or value in {".", ".."}:
        return None
    if _contains_filename_control(value) or len(value) > 255:
        return None
    return value


def _split_content_disposition(header: str) -> list[str]:
    """Split disposition parameters without treating quoted semicolons as separators."""

    parts: list[str] = []
    start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(header):
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
        elif character == ";" and not quoted:
            parts.append(header[start:index])
            start = index + 1
    parts.append(header[start:])
    return parts


def _header_parameter_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
        value = value.replace(r"\\", "\\").replace(r'\"', '"')
    return value.strip()


def _strict_percent_decode(value: str, encoding: str) -> str | None:
    """Decode a header value only when every percent escape is well formed."""

    for index, character in enumerate(value):
        if character != "%":
            continue
        if index + 2 >= len(value) or any(digit not in "0123456789abcdefABCDEF" for digit in value[index + 1:index + 3]):
            return None
    try:
        return unquote_to_bytes(value).decode(encoding, errors="strict")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return None


def parse_content_disposition_filename(header: str | None) -> str | None:
    """Return a safe filename candidate from a provider Content-Disposition header.

    G2B emits percent-encoded UTF-8 in the non-standard ``filename=`` form,
    so this parser deliberately does not delegate that value to an RFC 6266
    parser that would preserve the percent escapes literally.
    """

    if not isinstance(header, str) or not header:
        return None

    extended: list[str] = []
    plain: list[str] = []
    for part in _split_content_disposition(header):
        name, separator, raw_value = part.partition("=")
        if not separator:
            continue
        normalized_name = name.strip().casefold()
        value = _header_parameter_value(raw_value)
        if normalized_name == "filename*":
            extended.append(value)
        elif normalized_name == "filename":
            plain.append(value)

    for value in extended:
        charset, separator, remainder = value.partition("'")
        if not separator:
            continue
        _language, separator, encoded = remainder.partition("'")
        if not separator or charset.casefold() not in {"utf-8", "us-ascii"}:
            continue
        decoded = _strict_percent_decode(encoded, "utf-8" if charset.casefold() == "utf-8" else "ascii")
        if decoded is None:
            continue
        candidate = _validate_suggested_filename(decoded)
        if candidate is not None:
            return candidate

    for value in plain:
        decoded = value if "%" not in value else _strict_percent_decode(value, "utf-8")
        if decoded is None:
            return None
        return _validate_suggested_filename(decoded)
    return None


def asset_root(root: Path | None = None) -> Path:
    """Return the private asset root and create only its known namespaces."""

    configured = root or get_settings().attachments_dir
    if configured is None:
        raise AssetError("service_unavailable", "첨부 보관소를 사용할 수 없습니다")
    base = Path(configured).resolve() / "document-assets"
    for namespace in ("quarantine", "source", "structure"):
        (base / namespace).mkdir(parents=True, exist_ok=True)
    return base


def _safe_filename(filename: str | None) -> str:
    value = _filename_last_component(filename or "")
    if not value or value in {".", ".."}:
        raise AssetError("invalid_request", "파일명이 없습니다")
    if _contains_filename_control(value) or len(value) > 255:
        raise AssetError("invalid_request", "파일명이 올바르지 않습니다")
    suffix = Path(value).suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise AssetError("unsafe_document", "지원하지 않는 문서 확장자입니다")
    return value


def declared_type_for_filename(filename: str) -> str:
    suffix = Path(_safe_filename(filename)).suffix.casefold()
    return SUPPORTED_EXTENSIONS[suffix]


def _new_key(namespace: str, digest: str, suffix: str = "") -> Path:
    # The digest is useful for recovery/audit while the random component means
    # a user cannot infer or overwrite another object location.
    return Path(namespace) / f"{digest[:16]}-{uuid.uuid4().hex}{suffix}"


def _store(root: Path | None = None, *, namespace: str, read_only: bool = False):
    try:
        return object_store(root, namespaces=(namespace,), read_namespaces=(namespace,) if read_only else ())
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object storage를 사용할 수 없습니다") from error


def _path_for_key(root: Path | None, object_key: str) -> Path:
    return asset_root(root) / Path(*object_key.split("/"))


def _store_bytes(namespace: str, data: bytes, *, root: Path | None = None, suffix: str = "") -> tuple[Path, ObjectMetadata]:
    digest = hashlib.sha256(data).hexdigest()
    object_key = _new_key(namespace, digest, suffix).as_posix()
    try:
        metadata = _store(root, namespace=namespace).put(namespace, object_key, data, content_type="application/octet-stream")
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object storage에 저장할 수 없습니다") from error
    return _path_for_key(root, object_key), metadata


def store_bytes(namespace: str, data: bytes, *, root: Path | None = None, suffix: str = "", content_type: str = "application/octet-stream") -> tuple[Path, ObjectMetadata]:
    """Store bounded bytes in a purpose bucket and return persisted metadata."""

    digest = hashlib.sha256(data).hexdigest()
    object_key = _new_key(namespace, digest, suffix).as_posix()
    try:
        metadata = _store(root, namespace=namespace).put(namespace, object_key, data, content_type=content_type)
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object storage에 저장할 수 없습니다") from error
    return _path_for_key(root, object_key), metadata


def store_named(namespace: str, object_key: str, data: bytes, *, root: Path | None = None, content_type: str = "application/octet-stream") -> tuple[Path, ObjectMetadata]:
    """Store a validated server-generated key when idempotent identity is required."""

    try:
        metadata = _store(root, namespace=namespace).put(namespace, object_key, data, content_type=content_type)
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object storage에 저장할 수 없습니다") from error
    return _path_for_key(root, object_key), metadata


def read_object(namespace: str, object_key: str, *, root: Path | None = None, max_bytes: int = MAX_ASSET_BYTES) -> tuple[bytes, ObjectMetadata]:
    try:
        return _store(root, namespace=namespace, read_only=True).get(namespace, object_key, max_bytes=max_bytes)
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object storage를 읽을 수 없습니다") from error


def head_object(namespace: str, object_key: str, *, root: Path | None = None) -> ObjectMetadata:
    try:
        return _store(root, namespace=namespace, read_only=True).head(namespace, object_key)
    except ObjectStoreError as error:
        raise AssetError("service_unavailable", "문서 object metadata를 읽을 수 없습니다") from error


def _write_stream_sync(chunks: Iterable[bytes], destination: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.exists() or destination.is_symlink():
            raise AssetError("processing_failed", "asset location이 이미 존재합니다")
        with destination.open("xb") as target:
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise AssetError("invalid_request", "파일 입력이 올바르지 않습니다")
                blob = bytes(chunk)
                if not blob:
                    continue
                size += len(blob)
                if size > MAX_ASSET_BYTES:
                    raise AssetError("unsafe_document", "파일 크기가 50MiB를 초과합니다")
                target.write(blob)
                hasher.update(blob)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if size == 0:
        destination.unlink(missing_ok=True)
        raise AssetError("invalid_request", "빈 문서는 처리할 수 없습니다")
    return size, hasher.hexdigest()


async def quarantine_upload(
    upload: UploadFile,
    *,
    root: Path | None = None,
    source_kind: str = "manual",
    source_system: str | None = None,
    source_attachment_key: str | None = None,
    source_url: str | None = None,
) -> QuarantinedAsset:
    """Stream a multipart file to quarantine without trusting its name/path."""

    filename = _safe_filename(upload.filename)
    base = asset_root(root)
    temporary = base / "quarantine" / f".{uuid.uuid4().hex}.upload"
    hasher = hashlib.sha256()
    size = 0
    try:
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("wb") as target:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise AssetError("unsafe_document", "파일 크기가 50MiB를 초과합니다")
                target.write(chunk)
                hasher.update(chunk)
            target.flush()
            os.fsync(target.fileno())
        if size == 0:
            raise AssetError("invalid_request", "빈 문서는 처리할 수 없습니다")
        digest = hasher.hexdigest()
        object_key = _new_key("quarantine", digest, Path(filename).suffix.casefold()).as_posix()
        try:
            store = _store(root, namespace="quarantine")
            metadata = store.put("quarantine", object_key, temporary.read_bytes(), content_type=upload.content_type or "application/octet-stream")
        except ObjectStoreError as error:
            raise AssetError("service_unavailable", "문서 quarantine object를 저장할 수 없습니다") from error
        final = _path_for_key(root, object_key)
        temporary.unlink(missing_ok=True)
        return QuarantinedAsset(
            path=final,
            filename=filename,
            size_bytes=size,
            sha256=digest,
            declared_media_type=upload.content_type,
            source_kind=source_kind,
            source_system=source_system,
            source_attachment_key=source_attachment_key,
            source_url=source_url,
            object_key=object_key,
            object_version_id=metadata.object_version_id,
            object_etag=metadata.etag,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def quarantine_bytes(
    content: bytes,
    filename: str,
    *,
    declared_media_type: str | None = None,
    root: Path | None = None,
    source_kind: str = "provider",
    source_system: str | None = None,
    source_attachment_key: str | None = None,
    source_url: str | None = None,
) -> QuarantinedAsset:
    """Store trusted connector bytes through the same quarantine boundary."""

    safe_name = _safe_filename(filename)
    base = asset_root(root)
    digest = hashlib.sha256(content).hexdigest()
    destination, metadata = _store_bytes("quarantine", content, root=root, suffix=Path(safe_name).suffix.casefold())
    actual_digest = digest
    return QuarantinedAsset(
        path=destination,
        filename=safe_name,
        size_bytes=len(content),
        sha256=actual_digest,
        declared_media_type=declared_media_type,
        source_kind=source_kind,
        source_system=source_system,
        source_attachment_key=source_attachment_key,
        source_url=source_url,
        object_key=metadata.object_key,
        object_version_id=metadata.object_version_id,
        object_etag=metadata.etag,
    )


def _legacy_source_path(stored_path: str | None, *, root: Path | None = None) -> Path:
    """Resolve a legacy attachment path below the configured attachment root.

    Legacy rows predate the document asset namespaces and store a relative
    path such as ``<notice-id>/<server-generated-name>.pdf``.  The value is
    metadata, never an object key: absolute paths, traversal components,
    symlinks and anything outside the configured root fail closed before the
    source is opened.
    """

    configured = root or get_settings().attachments_dir
    if configured is None:
        raise AssetError("service_unavailable", "첨부 보관소를 사용할 수 없습니다")
    base = Path(configured).resolve()
    if not stored_path or not stored_path.strip():
        raise AssetError("legacy_source_missing", "기존 첨부 원문을 찾을 수 없습니다")
    relative = Path(stored_path)
    if relative.is_absolute() or any(part in {"..", "."} for part in relative.parts):
        raise AssetError("legacy_path_blocked", "기존 첨부 저장 경로가 허용되지 않습니다")
    candidate = base.joinpath(*relative.parts)
    # Reject symlinks in every component, including an intermediate
    # directory; do this before resolving so a dangling link is still a
    # symlink violation rather than being mistaken for an ordinary missing
    # source.
    current = base
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise AssetError("legacy_symlink_blocked", "기존 첨부 저장 경로가 허용되지 않습니다")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
    except FileNotFoundError as exc:
        raise AssetError("legacy_source_missing", "기존 첨부 원문을 찾을 수 없습니다") from exc
    except (OSError, ValueError) as exc:
        raise AssetError("legacy_path_blocked", "기존 첨부 저장 경로가 허용되지 않습니다") from exc

    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise AssetError("legacy_source_missing", "기존 첨부 원문을 찾을 수 없습니다") from exc
    if not stat.S_ISREG(mode):
        raise AssetError("legacy_non_regular", "기존 첨부 원문 형식이 올바르지 않습니다")
    return resolved


def _legacy_stat_fingerprint(metadata: os.stat_result) -> tuple[object, ...]:
    """Return stable file identity metadata available on this platform.

    Device/inode/size/mtime are the minimum identity fence.  Mode and ctime
    are included when the platform exposes them so permission or metadata
    changes during the copy also fail closed without depending on a platform-
    specific stat result shape.
    """

    return tuple(
        getattr(metadata, field, None)
        for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
    )


def acquire_legacy_attachment(
    *,
    stored_path: str | None,
    filename: str,
    expected_size: int | None = None,
    root: Path | None = None,
) -> QuarantinedAsset:
    """Stream an existing server-owned legacy file into quarantine.

    The source is opened read-only and copied in bounded chunks.  Its size is
    checked before and after the copy, and a declared legacy size (when
    present) must match the bytes actually read.  The legacy file is never
    replaced or deleted; only the request-created quarantine object can be
    cleaned by the caller.
    """

    safe_name = _safe_filename(filename)
    source = _legacy_source_path(stored_path, root=root)
    try:
        initial_stat = source.stat()
    except OSError as exc:
        raise AssetError("legacy_source_missing", "기존 첨부 원문을 찾을 수 없습니다") from exc
    if not stat.S_ISREG(initial_stat.st_mode):
        raise AssetError("legacy_non_regular", "기존 첨부 원문 형식이 올바르지 않습니다")
    initial_identity = _legacy_stat_fingerprint(initial_stat)
    initial_size = initial_stat.st_size
    if initial_size > MAX_ASSET_BYTES:
        raise AssetError("legacy_size_limit", "기존 첨부 원문이 50MiB를 초과합니다")
    if expected_size is not None and expected_size != initial_size:
        raise AssetError("legacy_size_mismatch", "기존 첨부 원문 크기가 메타데이터와 다릅니다")

    base = asset_root(root)
    digest_hint = hashlib.sha256(f"legacy:{stored_path}".encode("utf-8")).hexdigest()
    destination = base / _new_key("quarantine", digest_hint, Path(safe_name).suffix.casefold())
    fd: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(source, flags)
            descriptor_stat = os.fstat(fd)
        except OSError as exc:
            raise AssetError("legacy_source_changed", "기존 첨부 원문이 열리는 동안 변경되었습니다") from exc
        if not stat.S_ISREG(descriptor_stat.st_mode):
            raise AssetError("legacy_non_regular", "기존 첨부 원문 형식이 올바르지 않습니다")
        if _legacy_stat_fingerprint(descriptor_stat) != initial_identity:
            raise AssetError("legacy_source_changed", "기존 첨부 원문이 변경되었습니다")
        if expected_size is not None and descriptor_stat.st_size != expected_size:
            raise AssetError("legacy_size_mismatch", "기존 첨부 원문 크기가 메타데이터와 다릅니다")

        def chunks() -> Iterable[bytes]:
            assert fd is not None
            while True:
                try:
                    blob = os.read(fd, UPLOAD_CHUNK_BYTES)
                except OSError as exc:
                    raise AssetError("legacy_source_changed", "기존 첨부 원문을 읽는 동안 변경되었습니다") from exc
                if not blob:
                    break
                yield blob

        size, digest = _write_stream_sync(chunks(), destination)
        try:
            after_stat = os.fstat(fd)
        except OSError as exc:
            raise AssetError("legacy_source_changed", "기존 첨부 원문 상태를 확인할 수 없습니다") from exc
        if _legacy_stat_fingerprint(after_stat) != initial_identity or size != initial_size:
            raise AssetError("legacy_source_changed", "기존 첨부 원문이 복사 중 변경되었습니다")
        if expected_size is not None and size != expected_size:
            raise AssetError("legacy_size_mismatch", "기존 첨부 원문 크기가 메타데이터와 다릅니다")
        object_key = destination.relative_to(base).as_posix()
        store = _store(root, namespace="quarantine")
        try:
            metadata = store.put("quarantine", object_key, destination.read_bytes(), content_type="application/octet-stream")
        except ObjectStoreError as error:
            raise AssetError("service_unavailable", "기존 첨부 quarantine object를 저장할 수 없습니다") from error
        if not isinstance(store, FilesystemObjectStore):
            destination.unlink(missing_ok=True)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    # A legacy attachment has no provider provenance: source_system,
    # source_attachment_key and source_url stay unset, which is what
    # ``ck_document_version_source_provenance`` requires of source_kind
    # ``manual``.  The object identity belongs in the object_* fields; putting
    # it anywhere else loses the quarantine object and, on a non-filesystem
    # store where the local copy is removed after the put, makes the bytes
    # unreadable.
    return QuarantinedAsset(
        path=destination,
        filename=safe_name,
        size_bytes=size,
        sha256=digest,
        declared_media_type=None,
        source_kind="manual",
        object_key=object_key,
        object_version_id=metadata.object_version_id,
        object_etag=metadata.etag,
    )


def read_quarantine(asset: QuarantinedAsset) -> bytes:
    if asset.object_key:
        try:
            data, metadata = read_object("quarantine", asset.object_key, root=asset.path.parents[2])
        except AssetError:
            raise
        if len(data) != asset.size_bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
            raise AssetError("hash_mismatch", "격리 문서 hash 검증에 실패했습니다")
        if asset.object_etag and metadata.etag != asset.object_etag:
            raise AssetError("hash_mismatch", "격리 문서 object metadata 검증에 실패했습니다")
        return data
    base = asset.path.parent.parent
    if base.name != "document-assets" or asset.path.parent.name != "quarantine":
        raise AssetError("unsafe_document", "격리 문서 경로가 올바르지 않습니다")
    try:
        resolved = asset.path.resolve(strict=True)
        resolved.relative_to(base)
    except (OSError, ValueError) as exc:
        raise AssetError("unsafe_document", "격리 문서 경로가 올바르지 않습니다") from exc
    if asset.path.is_symlink():
        raise AssetError("unsafe_document", "격리 문서 경로가 올바르지 않습니다")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise AssetError("unsafe_document", "격리 문서를 읽을 수 없습니다") from exc
    if len(data) != asset.size_bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
        raise AssetError("hash_mismatch", "격리 문서 hash 검증에 실패했습니다")
    return data


def inspect_quarantine(
    asset: QuarantinedAsset,
    *,
    processor: DocumentProcessor | None = None,
    clamav_checker: ClamAVChecker | None = None,
    options: Mapping[str, object] | None = None,
) -> InspectedAsset:
    """Run MIME/magic/archive/PDF/ClamAV and the T2 structure processor."""

    data = read_quarantine(asset)
    if EICAR_MARKER in data:
        return InspectedAsset(asset, "application/octet-stream", None, "blocked", "infected", "malware_detected")
    expected_mime = declared_type_for_filename(asset.filename)
    worker = processor or DocumentProcessor(clamav_checker=clamav_checker)
    try:
        processed = worker.process(data, asset.declared_media_type, options)
    except DocumentProcessingError as exc:
        code = exc.code
        if code in {"clamav_unavailable", "ocr_unavailable", "renderer_unavailable"}:
            status = "quarantined"
            scan = "unavailable"
        elif code == "malware_detected":
            status = "blocked"
            scan = "infected"
        else:
            status = "blocked"
            scan = "error"
        return InspectedAsset(asset, "application/octet-stream", None, status, scan, code)
    if str(processed.get("media_type")) != expected_mime:
        return InspectedAsset(asset, str(processed.get("media_type", "application/octet-stream")), None, "blocked", "error", "mime_mismatch")
    warnings = tuple(str(item) for item in processed.get("warnings", []))
    unavailable = "clamav_unavailable" in warnings
    return InspectedAsset(
        asset,
        str(processed["media_type"]),
        processed,
        "quarantined" if unavailable else "safe",
        "unavailable" if unavailable else "clean",
        None,
        warnings,
    )


def commit_source(asset: QuarantinedAsset, *, root: Path | None = None) -> tuple[Path, str, int]:
    """Copy a verified quarantine object to source and verify hash/size again."""

    data = read_quarantine(asset)
    suffix = Path(asset.filename).suffix.casefold()
    destination, metadata = _store_bytes("source", data, root=root, suffix=suffix)
    try:
        size, digest = len(data), hashlib.sha256(data).hexdigest()
        if size != asset.size_bytes or digest != asset.sha256 or metadata.size_bytes != asset.size_bytes:
            raise AssetError("hash_mismatch", "원문 location hash 검증에 실패했습니다")
        reread, reread_metadata = read_object("source", metadata.object_key, root=root)
        if len(reread) != asset.size_bytes or hashlib.sha256(reread).hexdigest() != asset.sha256 or reread_metadata.etag != metadata.etag:
            raise AssetError("hash_mismatch", "원문 location hash 검증에 실패했습니다")
    except AssetError:
        raise
    return destination, asset.sha256, asset.size_bytes


def store_structure_payload(payload: Mapping[str, object], *, root: Path | None = None) -> tuple[Path, str, int]:
    """Persist the authoritative structure JSON in the structure namespace."""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    destination, metadata = store_bytes("structure", encoded, root=root, suffix=".json", content_type="application/json")
    if metadata.etag != digest and isinstance(_store(root, namespace="structure"), FilesystemObjectStore):
        raise AssetError("hash_mismatch", "구조 payload hash 검증에 실패했습니다")
    return destination, digest, len(encoded)


def _is_public_ip(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global and not any(
        (
            parsed.is_private,
            parsed.is_loopback,
            parsed.is_link_local,
            parsed.is_reserved,
            parsed.is_multicast,
            parsed.is_unspecified,
        )
    )


def resolve_public_ips(host: str, port: int) -> tuple[str, ...]:
    """Resolve and validate every address immediately before a request."""

    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderSecurityError("provider_dns_blocked", "provider host를 확인할 수 없습니다") from exc
    addresses = tuple(sorted({str(record[4][0]) for record in records}))
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ProviderSecurityError("provider_private_ip", "provider host가 허용된 공인 주소가 아닙니다")
    return addresses


def _parse_provider_url(url: str, *, allowed_hosts: set[str] | frozenset[str]) -> tuple[str, int]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    if parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password:
        raise ProviderSecurityError("provider_url_blocked", "provider URL이 허용되지 않습니다")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ProviderSecurityError("provider_url_blocked", "provider URL에는 host 이름이 필요합니다")
    if host not in {value.rstrip(".").casefold() for value in allowed_hosts}:
        raise ProviderSecurityError("provider_host_blocked", "provider host가 allowlist에 없습니다")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ProviderSecurityError("provider_url_blocked", "provider URL port가 올바르지 않습니다") from exc
    if port != 443:
        raise ProviderSecurityError("provider_url_blocked", "provider TLS port가 허용되지 않습니다")
    return host, port


def validate_provider_url(url: str, *, allowed_hosts: set[str] | frozenset[str]) -> tuple[str, int]:
    """Validate an allowlisted HTTPS URL and its current public resolution.

    The connector uses :func:`_parse_provider_url` directly so it can retain
    the one validated address returned by DNS and pass that address into the
    transport.  Keeping this public helper resolving is useful to callers
    that only need a validation probe.
    """

    host, port = _parse_provider_url(url, allowed_hosts=allowed_hosts)
    resolve_public_ips(host, port)
    return host, port


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that never asks the resolver to resolve ``host``.

    ``host`` remains the original allowlisted hostname for both certificate
    verification/SNI and the HTTP Host header.  Only the TCP destination is
    replaced by the address validated immediately before opening the request.
    """

    def __init__(self, host: str, *, pinned_ip: str, server_hostname: str, **kwargs: object) -> None:
        self._pinned_ip = pinned_ip
        self._server_hostname = server_hostname
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            # Proxy use is disabled by the connector.  Keep the guard here so
            # a future caller cannot silently tunnel to an unvalidated host.
            raise ProviderSecurityError("provider_proxy_blocked", "provider proxy가 허용되지 않습니다")
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._server_hostname)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, *, pinned_ip: str, server_hostname: str, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self._pinned_ip = pinned_ip
        self._server_hostname = server_hostname

    def https_open(self, req):  # type: ignore[no-untyped-def]
        def connection_factory(host, **kwargs):  # type: ignore[no-untyped-def]
            context = kwargs.pop("context", self._context)
            return _PinnedHTTPSConnection(
                host,
                pinned_ip=self._pinned_ip,
                server_hostname=self._server_hostname,
                context=context,
                **kwargs,
            )

        return self.do_open(
            connection_factory,
            req,
            context=self._context,
        )


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderSecurityError("provider_timeout", "provider 원문 취득 시간이 초과되었습니다")
    return remaining


def _set_response_timeout(response: object, timeout: float) -> None:
    """Refresh a socket read timeout for the single overall deadline.

    urllib does not expose a public response-socket timeout setter.  The
    nested object is present on CPython's HTTPResponse; fake test responses
    simply skip this best-effort transport detail and are still checked before
    and after every read.
    """

    raw = getattr(response, "fp", None)
    raw = getattr(raw, "raw", raw)
    sock = getattr(raw, "_sock", None)
    setter = getattr(sock, "settimeout", None)
    if callable(setter):
        setter(timeout)


@dataclass(frozen=True)
class ProviderConnector:
    """An explicit source-system connector; arbitrary URL fetch is impossible."""

    source_system: str
    allowed_hosts: frozenset[str]
    fetcher: Callable[[str], bytes | Iterable[bytes]] | None = None
    timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.source_system.strip() or not self.allowed_hosts:
            raise ValueError("provider connector requires source_system and hosts")
        if not 0.1 <= self.timeout_seconds <= 60:
            raise ValueError("provider connector timeout out of range")

    def fetch(self, url: str) -> ProviderResponse:
        current = url
        deadline = time.monotonic() + self.timeout_seconds
        for redirect_count in range(MAX_REDIRECTS + 1):
            _remaining(deadline)
            host, port = _parse_provider_url(current, allowed_hosts=self.allowed_hosts)
            # Resolve once per hop and pin the selected public address.  The
            # standard urllib HTTPS handler is never used because it would
            # resolve ``host`` again inside socket.create_connection().
            pinned_ips = resolve_public_ips(host, port)
            if not pinned_ips or any(not _is_public_ip(address) for address in pinned_ips):
                raise ProviderSecurityError("provider_private_ip", "provider host가 허용된 공인 주소가 아닙니다")
            pinned_ip = pinned_ips[0]
            if self.fetcher is not None:
                # This is an explicitly trusted test seam.  It has no access
                # to the pinned transport, so only its result size/deadline is
                # bounded here; transport security is covered by the native
                # path below.
                try:
                    _remaining(deadline)
                    result = self.fetcher(current)
                    _remaining(deadline)
                    if isinstance(result, (bytes, bytearray, memoryview)):
                        body = bytes(result)
                    else:
                        _, body = _collect_chunks(result, deadline=deadline)
                except AssetError:
                    # Trusted adapters may deliberately report a classified
                    # asset failure (for example a bounded response error).
                    # Preserve that classification for the service layer.
                    raise
                except Exception as exc:
                    # Connector implementations are trusted code, but their
                    # exception text may contain credentials or provider
                    # internals.  Normalize every unexpected adapter failure
                    # before it can cross the service boundary.
                    raise ProviderSecurityError(
                        "provider_fetch_failed",
                        "provider 원문을 취득할 수 없습니다",
                    ) from exc
                if len(body) > MAX_ASSET_BYTES:
                    raise ProviderSecurityError("provider_size_limit", "provider 응답이 50MiB를 초과합니다")
                return ProviderResponse(body=body, final_url=current)
            request = Request(
                current,
                headers={
                    "Accept": "application/pdf,application/octet-stream,*/*",
                    # Keep Host as the allowlisted hostname while the socket
                    # connects to the pinned IP.
                    "Host": host,
                },
                method="GET",
            )
            opener = build_opener(
                _NoRedirects,
                ProxyHandler({}),
                _PinnedHTTPSHandler(
                    pinned_ip=pinned_ip,
                    server_hostname=host,
                    context=ssl.create_default_context(),
                ),
            )
            try:
                with opener.open(request, timeout=_remaining(deadline)) as response:
                    final_url = response.geturl() or current
                    # Redirects are disabled in the opener; this validation is
                    # a defense-in-depth check against an unusual handler.
                    final_host, _final_port = _parse_provider_url(final_url, allowed_hosts=self.allowed_hosts)
                    if final_host != host:
                        raise ProviderSecurityError("provider_redirect_blocked", "provider redirect host가 변경되었습니다")
                    length = response.headers.get("Content-Length")
                    if length is not None:
                        try:
                            parsed_length = int(length)
                            if parsed_length < 0 or parsed_length > MAX_ASSET_BYTES:
                                raise ProviderSecurityError("provider_size_limit", "provider 응답이 50MiB를 초과합니다")
                        except ValueError as exc:
                            raise ProviderSecurityError("provider_response_invalid", "provider 응답 크기가 올바르지 않습니다") from exc
                    chunks: list[bytes] = []
                    total = 0
                    while True:
                        remaining = _remaining(deadline)
                        _set_response_timeout(response, remaining)
                        chunk = response.read(UPLOAD_CHUNK_BYTES)
                        _remaining(deadline)
                        if not chunk:
                            break
                        if not isinstance(chunk, (bytes, bytearray, memoryview)):
                            raise ProviderSecurityError("provider_response_invalid", "provider 응답 형식이 올바르지 않습니다")
                        chunk = bytes(chunk)
                        total += len(chunk)
                        if total > MAX_ASSET_BYTES:
                            raise ProviderSecurityError("provider_size_limit", "provider 응답이 50MiB를 초과합니다")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    suggested_filename = parse_content_disposition_filename(
                        response.headers.get("Content-Disposition")
                    )
                    return ProviderResponse(
                        body=body,
                        final_url=final_url,
                        suggested_filename=suggested_filename,
                    )
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("Location")
                    if not location:
                        raise ProviderSecurityError("provider_redirect_blocked", "provider redirect가 올바르지 않습니다") from exc
                    if redirect_count >= MAX_REDIRECTS:
                        raise ProviderSecurityError("provider_redirect_blocked", "provider redirect 횟수 제한을 초과했습니다") from exc
                    current = urljoin(current, location)
                    continue
                raise ProviderSecurityError("provider_fetch_failed", "provider 원문을 취득할 수 없습니다") from exc
            except (socket.timeout, TimeoutError) as exc:
                raise ProviderSecurityError("provider_timeout", "provider 원문 취득 시간이 초과되었습니다") from exc
            except (URLError, OSError, ssl.SSLError) as exc:
                raise ProviderSecurityError("provider_fetch_failed", "provider 원문을 취득할 수 없습니다") from exc
        raise ProviderSecurityError("provider_redirect_blocked", "provider redirect 횟수 제한을 초과했습니다")


def g2b_attachment_connectors(settings: Settings) -> dict[str, ProviderConnector]:
    """Build the explicitly enabled G2B attachment connector, fail closed."""

    if not settings.g2b_attachment_enabled:
        return {}
    hosts = frozenset(
        host.strip()
        for host in settings.g2b_attachment_allowed_hosts.split(",")
        if host.strip()
    )
    if not hosts:
        return {}
    return {
        "g2b": ProviderConnector(
            "g2b",
            hosts,
            timeout_seconds=settings.g2b_attachment_timeout_seconds,
        )
    }


def _collect_chunks(chunks: Iterable[bytes] | AsyncIterable[bytes], *, deadline: float | None = None) -> tuple[int, bytes]:
    """Collect a bounded connector result; async fetchers are rejected."""

    if hasattr(chunks, "__aiter__"):
        raise ProviderSecurityError("provider_fetch_failed", "비동기 provider connector는 지원하지 않습니다")
    result: list[bytes] = []
    total = 0
    for chunk in chunks:  # type: ignore[union-attr]
        if deadline is not None:
            _remaining(deadline)
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise ProviderSecurityError("provider_response_invalid", "provider 응답 형식이 올바르지 않습니다")
        blob = bytes(chunk)
        total += len(blob)
        if total > MAX_ASSET_BYTES:
            raise ProviderSecurityError("provider_size_limit", "provider 응답이 50MiB를 초과합니다")
        result.append(blob)
    if deadline is not None:
        _remaining(deadline)
    return total, b"".join(result)


def acquire_provider_attachment(
    *,
    source_system: str,
    source_url: str,
    filename: str | None = None,
    source_attachment_key: str | None = None,
    connectors: Mapping[str, ProviderConnector],
    root: Path | None = None,
) -> QuarantinedAsset:
    """Acquire only through the named allowlisted connector."""

    connector = connectors.get(source_system)
    if connector is None or connector.source_system != source_system:
        raise ProviderSecurityError("provider_connector_blocked", "허용된 provider connector가 없습니다")
    response = connector.fetch(source_url)
    selected_filename = filename if filename is not None else response.suggested_filename
    if selected_filename is None:
        raise AssetError("unsupported_extension", "첨부 파일명을 확인할 수 없습니다")
    try:
        safe_filename = _safe_filename(selected_filename)
    except AssetError as error:
        if error.code == "unsafe_document":
            raise AssetError("unsupported_extension", "지원하지 않는 문서 확장자입니다") from error
        raise
    return quarantine_bytes(
        response.body,
        safe_filename,
        declared_media_type=None,
        root=root,
        source_kind="provider",
        source_system=source_system,
        source_attachment_key=source_attachment_key,
        # The attachment's source URL is the business provenance.  A
        # connector may follow an allowlisted redirect to acquire bytes, but
        # the final transport URL is not a replacement for that provenance.
        source_url=source_url,
    )


def cleanup_paths(paths: Iterable[Path]) -> None:
    """Remove only filesystem objects created by the current request."""

    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Rollback cleanup is best effort; a missing/unreadable object is
            # retained for the operator's storage reconciliation job.
            continue


def cleanup_asset(asset: QuarantinedAsset | None) -> None:
    if asset is not None:
        cleanup_paths((asset.path,))


# Stable names for worker adapters that were prototyped before the service
# split; both aliases preserve the same bytes-first implementation.
stream_upload = quarantine_upload
scan_asset = inspect_quarantine
