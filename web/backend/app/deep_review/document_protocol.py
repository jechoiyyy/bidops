"""Credential-free scratch protocol between FastAPI and document-worker.

The orchestrator writes a bounded metadata envelope and a quarantined content
blob into a scoped scratch volume. The converter atomically claims the envelope,
reads only that blob, runs :class:`DocumentProcessor`, and writes structure JSON
without source bytes, request headers, credentials, paths, or URLs. No database
or object-store capability is imported by this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import stat
from pathlib import Path, PurePosixPath
import re
import signal
import tempfile
import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .document_mcp.errors import DocumentProcessingError
from .document_mcp.contracts import para_page_map_bytes
from .document_mcp.native_artifacts import validate_native_bundle
from .document_mcp.processor import DocumentProcessor
from .document_mcp.safety import MAX_INPUT_BYTES, ProcessorOptions


logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESULT_BYTES = 24 * 1024 * 1024
MAX_PDF_SIDECAR_BYTES = 100 * 1024 * 1024
MAX_PDF_METADATA_BYTES = 2 * 1024 * 1024
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_METADATA = frozenset({"schema", "request_id", "media_type", "original_filename", "content_file", "content_sha256", "options", "scan"})
PROTOCOL_SCHEMA = "bidops.document-converter-request.v1"
RESULT_SCHEMA = "bidops.document-converter-result.v1"
PDF_PROTOCOL_SCHEMA = "bidops.document-converter-request.v2"
PDF_RESULT_SCHEMA = "bidops.document-converter-result.v2"
PDF_SIDECAR_NAMESPACE = "pdf"
NATIVE_SIDECAR_SUFFIXES = {"hwpx": "hwpx", "page_text": "page-text.json", "para_page_map": "para-page-map.json"}


class ScratchProtocolError(RuntimeError):
    """Safe, bounded scratch protocol error."""

    def __init__(self, message: str, *, code: str = "processing_failed") -> None:
        super().__init__(message)
        self.code = code


def scratch_dirs(root: Path) -> tuple[Path, Path, Path]:
    """Create and return inbox, claimed, and results directories."""

    root = Path(root)
    if root.is_symlink():
        raise ScratchProtocolError("invalid scratch root")
    root = root.resolve()
    directories = (root / "inbox", root / "claimed", root / "results")
    for directory in directories:
        if directory.is_symlink():
            raise ScratchProtocolError("invalid scratch directory")
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise ScratchProtocolError("invalid scratch directory")
    pdf_directory = root / PDF_SIDECAR_NAMESPACE
    if pdf_directory.is_symlink():
        raise ScratchProtocolError("invalid scratch directory")
    pdf_directory.mkdir(parents=True, exist_ok=True)
    if not pdf_directory.is_dir():
        raise ScratchProtocolError("invalid scratch directory")
    native_directory = root / "native"
    if native_directory.is_symlink():
        raise ScratchProtocolError("invalid scratch directory")
    native_directory.mkdir(parents=True, exist_ok=True)
    if not native_directory.is_dir():
        raise ScratchProtocolError("invalid scratch directory")
    return directories


def _safe_request_id(value: str) -> str:
    if not isinstance(value, str) or not REQUEST_ID_RE.fullmatch(value):
        raise ScratchProtocolError("invalid request id")
    return value


def _safe_relative(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ScratchProtocolError("invalid scratch path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise ScratchProtocolError("invalid scratch path")
    candidate = root / Path(*relative.parts)
    if candidate.parent not in {(root / "inbox").resolve(), (root / "claimed").resolve(), (root / "results").resolve()}:
        raise ScratchProtocolError("invalid scratch path")
    if candidate.is_symlink():
        raise ScratchProtocolError("scratch path must not be a symlink")
    return candidate


def _open_scratch_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ScratchProtocolError("scratch parent must be a directory")
        return descriptor
    except ScratchProtocolError:
        raise
    except OSError as error:
        raise ScratchProtocolError("scratch parent cannot be opened") from error


def _atomic_write(path: Path, content: bytes, *, limit: int) -> None:
    if not isinstance(content, bytes):
        raise ScratchProtocolError("scratch file is not bytes")
    if len(content) > limit:
        raise ScratchProtocolError("scratch file exceeds bounded size", code="output_size_limit")
    directory_fd = _open_scratch_directory(path.parent)
    temporary_name: str | None = None
    try:
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ScratchProtocolError("scratch target is already owned")
        temporary_fd, temporary_path = tempfile.mkstemp(dir=f"/proc/self/fd/{directory_fd}", prefix=".pending-")
        temporary_name = Path(temporary_path).name
        with os.fdopen(temporary_fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link publishes the fully fsynced file without replacing an
        # existing request-owned path. Both operations are relative to the
        # already-open, no-symlink parent directory.
        os.link(temporary_name, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _atomic_json(path: Path, payload: Mapping[str, Any], *, limit: int = MAX_RESULT_BYTES) -> None:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ScratchProtocolError("scratch metadata is not valid JSON") from error
    _atomic_write(path, encoded, limit=limit)


def read_bounded_file(path: Path, *, limit: int) -> bytes:
    """Read one regular, non-symlink scratch file with a post-read size check."""

    if limit < 1:
        raise ScratchProtocolError("invalid scratch read limit")
    directory_fd = _open_scratch_directory(path.parent)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, flags, dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ScratchProtocolError("scratch file must be regular")
        if before.st_size > limit:
            raise ScratchProtocolError("scratch file exceeds bounded size", code="output_size_limit")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(content) > limit or after.st_size != before.st_size or len(content) != before.st_size:
            raise ScratchProtocolError("scratch file changed during bounded read", code="processing_failed")
        return content
    except ScratchProtocolError:
        raise
    except FileNotFoundError as error:
        raise ScratchProtocolError("scratch file is missing", code="missing_file") from error
    except OSError as error:
        raise ScratchProtocolError("scratch file cannot be read") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _pdf_sidecar_path(root: Path, request_id: str) -> Path:
    request = _safe_request_id(request_id)
    root = Path(root).resolve()
    directory = root / PDF_SIDECAR_NAMESPACE
    if directory.is_symlink() or not directory.is_dir():
        raise ScratchProtocolError("invalid PDF sidecar directory")
    path = directory / f"{request}.pdf"
    if path.is_symlink():
        raise ScratchProtocolError("PDF sidecar path must not be a symlink")
    return path


def _safe_pdf_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScratchProtocolError("invalid PDF metadata")

    def check_keys(item: Any, depth: int = 0) -> None:
        if depth > 32:
            raise ScratchProtocolError("invalid PDF metadata")
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ScratchProtocolError("invalid PDF metadata")
                check_keys(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check_keys(child, depth + 1)

    check_keys(value)
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_PDF_METADATA_BYTES:
            raise ScratchProtocolError("PDF metadata exceeds bounded size", code="output_size_limit")
        decoded = json.loads(encoded.decode("utf-8"))
    except ScratchProtocolError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ScratchProtocolError("invalid PDF metadata") from error
    if not isinstance(decoded, dict):
        raise ScratchProtocolError("invalid PDF metadata")
    return decoded


def _original_pdf_structure_parts(structure: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[int, list[str]]]:
    pages = structure.get("pages") if isinstance(structure, Mapping) else None
    blocks = structure.get("blocks") if isinstance(structure, Mapping) else None
    if not isinstance(pages, list) or not pages or not isinstance(blocks, list):
        raise ScratchProtocolError("original PDF page metadata is incomplete", code="pdf_metadata_invalid")
    text_by_page: dict[int, list[str]] = {}
    for page in pages:
        if (
            not isinstance(page, Mapping)
            or isinstance(page.get("number"), bool)
            or not isinstance(page.get("number"), int)
            or not isinstance(page.get("width"), (int, float))
            or isinstance(page.get("width"), bool)
            or not math.isfinite(float(page["width"]))
            or not isinstance(page.get("height"), (int, float))
            or isinstance(page.get("height"), bool)
            or not math.isfinite(float(page["height"]))
        ):
            raise ScratchProtocolError("original PDF structure pages are invalid", code="pdf_metadata_invalid")
        text_by_page[page["number"]] = []
    if len(text_by_page) != len(pages):
        raise ScratchProtocolError("original PDF structure pages are invalid", code="pdf_metadata_invalid")
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        page = block.get("page")
        text = block.get("text")
        if page not in text_by_page or not isinstance(text, str):
            raise ScratchProtocolError("original PDF structure text is invalid", code="pdf_metadata_invalid")
        text_by_page[page].append(text)
    return pages, text_by_page


def validate_original_pdf_metadata(metadata: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the physical-page metadata required for an original PDF."""

    safe = _safe_pdf_metadata(metadata)
    if (
        safe.get("schema") != "bidops.pdf-snapshot.v1"
        or safe.get("renderer") != "source-pdf"
        or safe.get("renderer_version") != "1"
        or safe.get("rerendered") is not False
        or safe.get("font_provenance") is not None
    ):
        raise ScratchProtocolError("original PDF metadata is not versioned", code="pdf_metadata_invalid")
    extractor = structure.get("extractor") if isinstance(structure, Mapping) else None
    processor_provenance = safe.get("processor_provenance")
    processor_sha256 = processor_provenance.get("processor_sha256") if isinstance(processor_provenance, Mapping) else None
    text_extractor = processor_provenance.get("text_extractor") if isinstance(processor_provenance, Mapping) else None
    poppler_hashes = processor_provenance.get("poppler_binary_sha256") if isinstance(processor_provenance, Mapping) else None
    if (
        not isinstance(extractor, Mapping)
        or not isinstance(processor_provenance, Mapping)
        or processor_provenance.get("schema") != "bidops.pdf-text-provenance.v1"
        or not isinstance(processor_sha256, str)
        or not SHA256_RE.fullmatch(processor_sha256)
        or text_extractor != dict(extractor)
        or (
            extractor.get("name") == "pdf-poppler-prepared"
            and (
                not isinstance(poppler_hashes, Mapping)
                or set(poppler_hashes) != {"pdfinfo", "pdftotext"}
                or any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in poppler_hashes.values())
            )
        )
        or (extractor.get("name") != "pdf-poppler-prepared" and poppler_hashes is not None)
    ):
        raise ScratchProtocolError("original PDF text extractor provenance is invalid", code="pdf_metadata_invalid")
    pages, text_by_page = _original_pdf_structure_parts(structure)
    metadata_pages = safe.get("pages")
    page_count = safe.get("page_count")
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count != len(pages)
        or not isinstance(metadata_pages, list)
        or len(metadata_pages) != len(pages)
    ):
        raise ScratchProtocolError("original PDF page metadata is incomplete", code="pdf_metadata_invalid")
    for page, metadata_page in zip(pages, metadata_pages, strict=True):
        if (
            not isinstance(page, Mapping)
            or not isinstance(metadata_page, Mapping)
            or set(metadata_page) != {"number", "width", "height", "text_sha256"}
            or metadata_page.get("number") != page.get("number")
            or not isinstance(metadata_page.get("width"), (int, float))
            or isinstance(metadata_page.get("width"), bool)
            or not math.isfinite(float(metadata_page["width"]))
            or float(metadata_page["width"]) != float(page.get("width"))
            or not isinstance(metadata_page.get("height"), (int, float))
            or isinstance(metadata_page.get("height"), bool)
            or not math.isfinite(float(metadata_page["height"]))
            or float(metadata_page["height"]) != float(page.get("height"))
            or not isinstance(metadata_page.get("text_sha256"), str)
            or not SHA256_RE.fullmatch(metadata_page["text_sha256"])
        ):
            raise ScratchProtocolError("original PDF page metadata is invalid", code="pdf_metadata_invalid")
        text = "".join(text_by_page[page["number"]])
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != metadata_page["text_sha256"]:
            raise ScratchProtocolError("original PDF text hash does not match structure", code="pdf_metadata_invalid")
    return safe


def read_pdf_sidecar(
    root: Path,
    request_id: str,
    descriptor: Mapping[str, Any],
    *,
    max_bytes: int,
) -> tuple[bytes, dict[str, Any], str]:
    """Validate and read the request-owned PDF sidecar described by v2 metadata."""

    required = {"file", "byte_count", "sha256", "metadata", "source_kind"}
    if not isinstance(descriptor, Mapping) or set(descriptor) != required:
        raise ScratchProtocolError("invalid PDF sidecar metadata")
    request = _safe_request_id(request_id)
    expected_name = f"{PDF_SIDECAR_NAMESPACE}/{request}.pdf"
    if descriptor.get("file") != expected_name:
        raise ScratchProtocolError("invalid PDF sidecar path")
    byte_count = descriptor.get("byte_count")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
        raise ScratchProtocolError("invalid PDF sidecar byte count")
    digest = descriptor.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ScratchProtocolError("invalid PDF sidecar hash")
    source_kind = descriptor.get("source_kind")
    if source_kind not in {"generated", "original"}:
        raise ScratchProtocolError("invalid PDF sidecar source")
    metadata = _safe_pdf_metadata(descriptor.get("metadata"))
    path = _pdf_sidecar_path(root, request)
    bounded = min(max_bytes, MAX_PDF_SIDECAR_BYTES)
    try:
        content = read_bounded_file(path, limit=bounded)
    except ScratchProtocolError as error:
        if error.code == "missing_file":
            raise ScratchProtocolError("PDF sidecar is missing", code="pdf_sidecar_missing") from error
        raise
    if len(content) != byte_count or hashlib.sha256(content).hexdigest() != digest:
        raise ScratchProtocolError("PDF sidecar hash mismatch", code="hash_mismatch")
    if not content.startswith(b"%PDF-"):
        raise ScratchProtocolError("PDF sidecar media mismatch", code="processing_failed")
    return content, metadata, source_kind


def native_sidecar_paths(root: Path, request_id: str) -> dict[str, Path]:
    request = _safe_request_id(request_id)
    directory = Path(root).resolve() / "native"
    if directory.is_symlink() or not directory.is_dir():
        raise ScratchProtocolError("invalid native sidecar directory")
    return {kind: directory / f"{request}.{suffix}" for kind, suffix in NATIVE_SIDECAR_SUFFIXES.items()}


def _write_native_sidecars(root: Path, request_id: str, processed: Any, source: bytes, options: ProcessorOptions) -> tuple[dict[str, Any], list[Path]]:
    validate_native_bundle(
        processed, source_bytes=source, hwpx_bytes=processed.hwpx_bytes,
        hwpx_verify=processed.hwpx_verify, page_text=processed.page_text,
        para_page_map=processed.para_page_map, pdf_metadata=processed.pdf_metadata, options=options,
    )
    map_bytes = para_page_map_bytes(processed.para_page_map, max_output_bytes=options.max_output_bytes, max_pages=options.max_pages, max_blocks=options.max_blocks)
    if map_bytes != processed.para_page_map_bytes:
        raise ScratchProtocolError("native map bytes mismatch", code="hash_mismatch")
    artifacts = {
        "hwpx": processed.hwpx_bytes if processed["media_type"] == "application/x-hwp" else None,
        "page_text": json.dumps(processed.page_text, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        "para_page_map": map_bytes,
    }
    paths = native_sidecar_paths(root, request_id)
    written: list[Path] = []
    result = {"hwpx_verify": processed.hwpx_verify}
    try:
        for kind, content in artifacts.items():
            result[kind] = None
            if content is None:
                continue
            _atomic_write(paths[kind], content, limit=options.max_output_bytes)
            written.append(paths[kind])
            result[kind] = {"file": f"native/{paths[kind].name}", "byte_count": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return result, written


def read_native_sidecars(
    root: Path, request_id: str, descriptors: Any, *, structure: Mapping[str, Any],
    source: bytes, pdf_metadata: Mapping[str, Any], options: ProcessorOptions,
) -> dict[str, Any]:
    if not isinstance(descriptors, Mapping) or set(descriptors) != {*NATIVE_SIDECAR_SUFFIXES, "hwpx_verify"}:
        raise ScratchProtocolError("native sidecar metadata missing", code="rhwp_manifest_invalid")
    paths = native_sidecar_paths(root, request_id)
    contents = {}
    for kind, path in paths.items():
        descriptor = descriptors[kind]
        if kind == "hwpx" and structure.get("media_type") == "application/hwp+zip":
            if descriptor is not None:
                raise ScratchProtocolError("native source HWPX mismatch", code="hash_mismatch")
            contents[kind] = source
            continue
        if not isinstance(descriptor, Mapping) or set(descriptor) != {"file", "byte_count", "sha256"} or descriptor["file"] != f"native/{path.name}":
            raise ScratchProtocolError("native sidecar descriptor invalid")
        if type(descriptor["byte_count"]) is not int or descriptor["byte_count"] < 1 or not isinstance(descriptor["sha256"], str) or not SHA256_RE.fullmatch(descriptor["sha256"]):
            raise ScratchProtocolError("native sidecar identity invalid")
        data = read_bounded_file(path, limit=min(options.max_output_bytes, MAX_PDF_SIDECAR_BYTES))
        if len(data) != descriptor["byte_count"] or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
            raise ScratchProtocolError("native sidecar hash mismatch", code="hash_mismatch")
        contents[kind] = data
    try:
        page_text = json.loads(contents["page_text"])
        para_map = json.loads(contents["para_page_map"])
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ScratchProtocolError("native JSON invalid", code="rhwp_manifest_invalid") from error
    validate_native_bundle(
        structure, source_bytes=source, hwpx_bytes=contents["hwpx"], hwpx_verify=descriptors["hwpx_verify"],
        page_text=page_text, para_page_map=para_map, pdf_metadata=pdf_metadata, options=options,
    )
    if contents["para_page_map"] != para_page_map_bytes(para_map, max_output_bytes=options.max_output_bytes, max_pages=options.max_pages, max_blocks=options.max_blocks):
        raise ScratchProtocolError("native map is not canonical", code="para_page_map_invalid")
    return {"hwpx_bytes": contents["hwpx"], "hwpx_verify": descriptors["hwpx_verify"], "page_text": page_text, "para_page_map": para_map, "para_page_map_bytes": contents["para_page_map"]}


def write_request(
    root: Path,
    *,
    request_id: UUID | str,
    content: bytes,
    media_type: str,
    original_filename: str,
    options: Mapping[str, Any] | None = None,
    scan: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically spool one document without accepting credential-bearing metadata."""

    request = _safe_request_id(str(request_id))
    if not isinstance(content, bytes) or len(content) > MAX_INPUT_BYTES:
        raise ScratchProtocolError("document exceeds bounded input size")
    if not isinstance(media_type, str) or not media_type or not isinstance(original_filename, str) or not original_filename or len(original_filename) > 255:
        raise ScratchProtocolError("invalid document metadata")
    if any(ord(char) < 32 or char in {"/", "\\"} for char in original_filename):
        raise ScratchProtocolError("invalid document filename")
    safe_options = dict(options or {})
    validated_options = ProcessorOptions.from_mapping(safe_options)
    if not isinstance(scan, Mapping) or set(scan) != {"scanner", "version", "sha256", "verdict"} or scan.get("scanner") != "clamav" or scan.get("version") != "clamd-instream-v1" or scan.get("sha256") != hashlib.sha256(content).hexdigest() or scan.get("verdict") != "clean":
        raise ScratchProtocolError("invalid scratch scan envelope")
    inbox, _claimed, _results = scratch_dirs(root)
    content_name = f"{request}.bin"
    content_path = inbox / content_name
    request_path = inbox / f"{request}.json"
    _atomic_write(content_path, content, limit=MAX_INPUT_BYTES)
    envelope = {
        "schema": PDF_PROTOCOL_SCHEMA if validated_options.prepare_pdf else PROTOCOL_SCHEMA,
        "request_id": request,
        "media_type": media_type,
        "original_filename": original_filename,
        "content_file": f"inbox/{content_name}",
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "options": safe_options,
        "scan": dict(scan),
    }
    try:
        _atomic_json(request_path, envelope, limit=MAX_REQUEST_BYTES)
    except Exception:
        content_path.unlink(missing_ok=True)
        raise
    return request_path


def _load_request(root: Path, path: Path) -> tuple[str, bytes, str, dict[str, Any], dict[str, Any], str]:
    root = Path(root).resolve()
    try:
        raw = read_bounded_file(path, limit=MAX_REQUEST_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except ScratchProtocolError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ScratchProtocolError("invalid scratch request") from error
    if not isinstance(payload, Mapping) or set(payload) != ALLOWED_METADATA or payload.get("schema") not in {PROTOCOL_SCHEMA, PDF_PROTOCOL_SCHEMA}:
        raise ScratchProtocolError("invalid scratch request")
    protocol_schema = str(payload["schema"])
    request_id = _safe_request_id(str(payload.get("request_id")))
    if request_id != path.stem:
        raise ScratchProtocolError("scratch request id does not match filename")
    content_path = _safe_relative(root, str(payload.get("content_file")))
    if content_path.parent != (root / "inbox").resolve() or content_path.name != f"{request_id}.bin":
        raise ScratchProtocolError("invalid scratch content path")
    content = read_bounded_file(content_path, limit=MAX_INPUT_BYTES)
    if hashlib.sha256(content).hexdigest() != payload.get("content_sha256"):
        raise ScratchProtocolError("scratch content integrity failure", code="hash_mismatch")
    media_type = payload.get("media_type")
    if not isinstance(media_type, str) or not media_type:
        raise ScratchProtocolError("invalid scratch media type")
    options = payload.get("options")
    if not isinstance(options, Mapping):
        raise ScratchProtocolError("invalid scratch options")
    safe_options = dict(options)
    validated_options = ProcessorOptions.from_mapping(safe_options)
    safe_options = dict(vars(validated_options))
    expected_schema = PDF_PROTOCOL_SCHEMA if validated_options.prepare_pdf else PROTOCOL_SCHEMA
    if protocol_schema != expected_schema:
        raise ScratchProtocolError("scratch protocol version does not match options")
    scan = payload.get("scan")
    if not isinstance(scan, Mapping) or set(scan) != {"scanner", "version", "sha256", "verdict"} or scan.get("scanner") != "clamav" or scan.get("version") != "clamd-instream-v1" or scan.get("sha256") != hashlib.sha256(content).hexdigest() or scan.get("verdict") != "clean":
        raise ScratchProtocolError("invalid scratch scan envelope")
    return request_id, content, media_type, safe_options, dict(scan), protocol_schema


def _request_result_schema_hint(path: Path) -> str:
    """Select a versioned failure envelope without trusting request contents."""

    try:
        payload = json.loads(read_bounded_file(path, limit=MAX_REQUEST_BYTES).decode("utf-8"))
    except (ScratchProtocolError, UnicodeError, json.JSONDecodeError):
        return RESULT_SCHEMA
    return PDF_RESULT_SCHEMA if isinstance(payload, Mapping) and payload.get("schema") == PDF_PROTOCOL_SCHEMA else RESULT_SCHEMA


class _ConversionTimeout(Exception):
    pass


def _timeout(_signum: int, _frame: Any) -> None:
    raise _ConversionTimeout


def convert_one(root: Path) -> bool:
    """Atomically claim and process one request; return whether work was found."""

    inbox, claimed, results = scratch_dirs(root)
    requests = sorted(inbox.glob("*.json"))
    if not requests:
        return False
    request_path = requests[0]
    claimed_path = claimed / request_path.name
    try:
        os.replace(request_path, claimed_path)
    except FileNotFoundError:
        return False
    request_id = request_path.stem
    result_path = results / f"{request_id}.json"
    sidecar_path: Path | None = None
    native_paths: list[Path] = []
    # This replica now owns the request, so it is the only process that can
    # report on it.  The identifiers below are protocol metadata; the document
    # bytes, its original filename, and the structure never reach the log.
    started = time.monotonic()
    logger.info(
        "document request claimed",
        extra={"bidops": {"event": "document.claimed", "job_id": request_id}},
    )
    result: dict[str, Any] = {
        "schema": _request_result_schema_hint(claimed_path),
        "request_id": request_id,
        "status": "failed",
    }
    old_handler = signal.signal(signal.SIGALRM, _timeout)
    try:
        request_id, content, media_type, options, _scan, protocol_schema = _load_request(root, claimed_path)
        result["schema"] = PDF_RESULT_SCHEMA if protocol_schema == PDF_PROTOCOL_SCHEMA else RESULT_SCHEMA
        signal.setitimer(signal.ITIMER_REAL, float(options.get("timeout_seconds", 30)) + 5)
        # The trusted-by-hash scan envelope was validated before this point.
        # The converter has no scanner credentials/network; this trusted
        # callback only prevents DocumentProcessor from downgrading a verified
        # clean envelope to ``clamav_unavailable``.
        processed = DocumentProcessor(clamav_checker=lambda _content: True).process(content, media_type, options)
        structure = dict(processed)
        if protocol_schema == PDF_PROTOCOL_SCHEMA:
            pdf_bytes = processed.converted_pdf_bytes
            source_kind = "generated"
            detected_media_type = structure.get("media_type")
            if pdf_bytes is None and detected_media_type == "application/pdf":
                # Existing PDF input remains byte-identical; it uses the same
                # bounded v2 sidecar so consumers have one PDF handoff path.
                pdf_bytes = content
                source_kind = "original"
            if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
                raise ScratchProtocolError("PDF preparation did not produce a PDF", code="pdf_sidecar_missing")
            if source_kind == "original":
                if detected_media_type != "application/pdf" or pdf_bytes != content or hashlib.sha256(pdf_bytes).hexdigest() != structure.get("source_sha256"):
                    raise ScratchProtocolError("original PDF bytes do not match the input", code="hash_mismatch")
                metadata = _safe_pdf_metadata(processed.pdf_metadata)
                if not metadata:
                    raise ScratchProtocolError(
                        "original PDF provenance is missing",
                        code="pdf_metadata_invalid",
                    )
                validate_original_pdf_metadata(metadata, structure)
            else:
                if detected_media_type == "application/pdf":
                    raise ScratchProtocolError("generated PDF source mismatches original media", code="processing_failed")
                metadata = _safe_pdf_metadata(processed.pdf_metadata)
            sidecar_path = _pdf_sidecar_path(root, request_id)
            _atomic_write(
                sidecar_path,
                pdf_bytes,
                limit=min(MAX_PDF_SIDECAR_BYTES, int(options["max_output_bytes"])),
            )
            result = {
                "schema": PDF_RESULT_SCHEMA,
                "request_id": request_id,
                "status": "succeeded",
                "structure": structure,
                "pdf_sidecar": {
                    "file": f"{PDF_SIDECAR_NAMESPACE}/{request_id}.pdf",
                    "byte_count": len(pdf_bytes),
                    "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                    "metadata": metadata,
                    "source_kind": source_kind,
                },
            }
            if options["renderer"] == "rhwp-svg-pdf" and detected_media_type != "application/pdf":
                result["native_sidecars"], native_paths = _write_native_sidecars(
                    root, request_id, processed, content, ProcessorOptions.from_mapping(options),
                )
        else:
            result = {"schema": RESULT_SCHEMA, "request_id": request_id, "status": "succeeded", "structure": structure}
        try:
            encoded_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise ScratchProtocolError("scratch result is not valid JSON") from error
        if len(encoded_result) > MAX_RESULT_BYTES:
            raise ScratchProtocolError("scratch result exceeds bounded size", code="output_size_limit")
    except _ConversionTimeout:
        result = {
            "schema": result.get("schema", RESULT_SCHEMA),
            "request_id": request_id,
            "status": "failed",
            "error": {"code": "timeout", "message": "문서 처리 시간이 제한을 초과했습니다"},
        }
    except DocumentProcessingError as error:
        result = {
            "schema": result.get("schema", RESULT_SCHEMA),
            "request_id": request_id,
            "status": "failed",
            "error": {"code": error.code, "message": error.message},
        }
    except ScratchProtocolError as error:
        result = {
            "schema": result.get("schema", RESULT_SCHEMA),
            "request_id": request_id,
            "status": "failed",
            "error": {"code": error.code, "message": "문서 처리를 완료할 수 없습니다"},
        }
    except (OSError, ValueError, TypeError):
        result = {
            "schema": result.get("schema", RESULT_SCHEMA),
            "request_id": request_id,
            "status": "failed",
            "error": {"code": "processing_failed", "message": "문서 처리를 완료할 수 없습니다"},
        }
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if result.get("status") != "succeeded" and sidecar_path is not None:
            sidecar_path.unlink(missing_ok=True)
        if result.get("status") != "succeeded":
            for path in native_paths:
                path.unlink(missing_ok=True)
    telemetry = {
        "event": "document.converted",
        "job_id": request_id,
        "status": result["status"],
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
    }
    if result["status"] == "succeeded":
        logger.info("document request converted", extra={"bidops": telemetry})
    else:
        # ``error.message`` is operator-facing Korean text from a fixed set, but
        # only the stable code is logged so a future message cannot smuggle
        # document content into the log.
        telemetry["error_code"] = result.get("error", {}).get("code", "unknown")
        logger.warning("document request failed", extra={"bidops": telemetry})
    try:
        _atomic_json(result_path, result)
    except Exception:
        if sidecar_path is not None:
            sidecar_path.unlink(missing_ok=True)
        for path in native_paths:
            path.unlink(missing_ok=True)
        claimed_path.unlink(missing_ok=True)
        (inbox / f"{request_id}.bin").unlink(missing_ok=True)
        raise
    claimed_path.unlink(missing_ok=True)
    (inbox / f"{request_id}.bin").unlink(missing_ok=True)
    return True


__all__ = [
    "ALLOWED_METADATA", "MAX_PDF_SIDECAR_BYTES", "MAX_REQUEST_BYTES", "MAX_RESULT_BYTES",
    "PDF_PROTOCOL_SCHEMA", "PDF_RESULT_SCHEMA", "PROTOCOL_SCHEMA", "RESULT_SCHEMA",
    "ScratchProtocolError", "convert_one", "read_bounded_file", "read_pdf_sidecar", "scratch_dirs",
    "validate_original_pdf_metadata", "write_request",
]
