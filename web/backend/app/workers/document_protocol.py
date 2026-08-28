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
import os
from pathlib import Path, PurePosixPath
import re
import signal
import tempfile
import time
from typing import Any, Mapping
from uuid import UUID

from ..document_mcp.errors import DocumentProcessingError
from ..document_mcp.processor import DocumentProcessor
from ..document_mcp.safety import MAX_INPUT_BYTES, ProcessorOptions


logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESULT_BYTES = 24 * 1024 * 1024
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ALLOWED_METADATA = frozenset({"schema", "request_id", "media_type", "original_filename", "content_file", "content_sha256", "options", "scan"})
PROTOCOL_SCHEMA = "bidops.document-converter-request.v1"
RESULT_SCHEMA = "bidops.document-converter-result.v1"


class ScratchProtocolError(RuntimeError):
    """Safe, bounded scratch protocol error."""


def scratch_dirs(root: Path) -> tuple[Path, Path, Path]:
    """Create and return inbox, claimed, and results directories."""

    root = root.resolve()
    directories = (root / "inbox", root / "claimed", root / "results")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
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
    candidate = (root / Path(*relative.parts)).resolve()
    if candidate.parent not in {(root / "inbox").resolve(), (root / "claimed").resolve(), (root / "results").resolve()}:
        raise ScratchProtocolError("invalid scratch path")
    return candidate


def _atomic_json(path: Path, payload: Mapping[str, Any], *, limit: int = MAX_RESULT_BYTES) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > limit:
        raise ScratchProtocolError("scratch result exceeds bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


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
    ProcessorOptions.from_mapping(safe_options)
    if not isinstance(scan, Mapping) or set(scan) != {"scanner", "version", "sha256", "verdict"} or scan.get("scanner") != "clamav" or scan.get("version") != "clamd-instream-v1" or scan.get("sha256") != hashlib.sha256(content).hexdigest() or scan.get("verdict") != "clean":
        raise ScratchProtocolError("invalid scratch scan envelope")
    inbox, _claimed, _results = scratch_dirs(root)
    content_name = f"{request}.bin"
    content_path = inbox / content_name
    request_path = inbox / f"{request}.json"
    with tempfile.NamedTemporaryFile(dir=inbox, prefix=".content-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, content_path)
    envelope = {
        "schema": PROTOCOL_SCHEMA,
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


def _load_request(root: Path, path: Path) -> tuple[str, bytes, str, dict[str, Any], dict[str, Any]]:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_REQUEST_BYTES:
            raise ScratchProtocolError("scratch request exceeds bounded size")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScratchProtocolError("invalid scratch request") from error
    if not isinstance(payload, Mapping) or set(payload) != ALLOWED_METADATA or payload.get("schema") != PROTOCOL_SCHEMA:
        raise ScratchProtocolError("invalid scratch request")
    request_id = _safe_request_id(str(payload.get("request_id")))
    content_path = _safe_relative(root, str(payload.get("content_file")))
    if content_path.parent != (root / "inbox").resolve() or content_path.name != f"{request_id}.bin":
        raise ScratchProtocolError("invalid scratch content path")
    content = content_path.read_bytes()
    if len(content) > MAX_INPUT_BYTES or hashlib.sha256(content).hexdigest() != payload.get("content_sha256"):
        raise ScratchProtocolError("scratch content integrity failure")
    media_type = payload.get("media_type")
    if not isinstance(media_type, str) or not media_type:
        raise ScratchProtocolError("invalid scratch media type")
    options = payload.get("options")
    if not isinstance(options, Mapping):
        raise ScratchProtocolError("invalid scratch options")
    safe_options = dict(options)
    ProcessorOptions.from_mapping(safe_options)
    scan = payload.get("scan")
    if not isinstance(scan, Mapping) or set(scan) != {"scanner", "version", "sha256", "verdict"} or scan.get("scanner") != "clamav" or scan.get("version") != "clamd-instream-v1" or scan.get("sha256") != hashlib.sha256(content).hexdigest() or scan.get("verdict") != "clean":
        raise ScratchProtocolError("invalid scratch scan envelope")
    return request_id, content, media_type, safe_options, dict(scan)


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
    # This replica now owns the request, so it is the only process that can
    # report on it.  The identifiers below are protocol metadata; the document
    # bytes, its original filename, and the structure never reach the log.
    started = time.monotonic()
    logger.info(
        "document request claimed",
        extra={"bidops": {"event": "document.claimed", "job_id": request_id}},
    )
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "request_id": request_id, "status": "failed"}
    old_handler = signal.signal(signal.SIGALRM, _timeout)
    try:
        request_id, content, media_type, options, _scan = _load_request(root, claimed_path)
        signal.setitimer(signal.ITIMER_REAL, float(options.get("timeout_seconds", 30)) + 5)
        # The trusted-by-hash scan envelope was validated before this point.
        # The converter has no scanner credentials/network; this trusted
        # callback only prevents DocumentProcessor from downgrading a verified
        # clean envelope to ``clamav_unavailable``.
        processed = DocumentProcessor(clamav_checker=lambda _content: True).process(content, media_type, options)
        structure = dict(processed)
        if len(json.dumps(structure, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_RESULT_BYTES:
            raise ScratchProtocolError("scratch result exceeds bounded size")
        result = {"schema": RESULT_SCHEMA, "request_id": request_id, "status": "succeeded", "structure": structure}
    except _ConversionTimeout:
        result["error"] = {"code": "timeout", "message": "문서 처리 시간이 제한을 초과했습니다"}
    except DocumentProcessingError as error:
        result["error"] = {"code": error.code, "message": error.message}
    except (ScratchProtocolError, OSError, ValueError, TypeError):
        result["error"] = {"code": "processing_failed", "message": "문서 처리를 완료할 수 없습니다"}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
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
    _atomic_json(results / f"{request_id}.json", result)
    claimed_path.unlink(missing_ok=True)
    (inbox / f"{request_id}.bin").unlink(missing_ok=True)
    return True


__all__ = ["ALLOWED_METADATA", "MAX_REQUEST_BYTES", "PROTOCOL_SCHEMA", "RESULT_SCHEMA", "ScratchProtocolError", "convert_one", "scratch_dirs", "write_request"]
