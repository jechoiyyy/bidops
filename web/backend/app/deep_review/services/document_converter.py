"""Trusted-side adapter for the credential-free document-worker."""

from __future__ import annotations

import json
import hashlib
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...core.config import get_settings
from ..document_mcp.contracts import validate_structure
from ..document_mcp.errors import DocumentProcessingError
from ..document_mcp.processor import ProcessedDocument
from ..document_mcp.safety import MAX_INPUT_BYTES, ProcessorOptions
from ...core.clamav import ClamAVScanner
from ..document_protocol import (
    MAX_RESULT_BYTES,
    RESULT_SCHEMA,
    ScratchProtocolError,
    write_request,
)


class ScratchDocumentProcessor:
    """Submit one quarantined document and consume one sidecar result.

    The API process owns only this bounded request/result exchange. It never
    imports converter credentials or invokes the converter in production; the
    credential-free ``document-worker`` service consumes the scratch file.
    Tests may inject a runner that calls ``convert_one`` to exercise the same
    protocol without requiring a second container.
    """

    def __init__(self, root: Path | None = None, *, wait_seconds: float | None = None, clamav_checker: Any | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.document_scratch_dir).resolve()
        self.wait_seconds = float(wait_seconds if wait_seconds is not None else settings.document_converter_wait_seconds)
        if clamav_checker is None:
            scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds)
            clamav_checker = scanner.scan
        self.clamav_checker = clamav_checker

    def process(
        self,
        content: bytes,
        media_type: str | None = None,
        options: ProcessorOptions | Mapping[str, Any] | None = None,
    ) -> ProcessedDocument:
        if not isinstance(content, bytes) or len(content) > MAX_INPUT_BYTES:
            raise DocumentProcessingError("input_size_limit", "문서 입력 크기 제한을 초과했습니다")
        try:
            safe_options = vars(ProcessorOptions.from_mapping(options if isinstance(options, dict) or options is None else dict(options)))
        except DocumentProcessingError:
            raise
        try:
            scan_result = self.clamav_checker(content)
        except Exception as error:
            raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True) from error
        if scan_result is False:
            raise DocumentProcessingError("malware_detected", "malware 검사에서 차단되었습니다", source_preserved=True)
        if scan_result is not True:
            raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True)
        scan = {
            "scanner": "clamav",
            "version": "clamd-instream-v1",
            "sha256": hashlib.sha256(content).hexdigest(),
            "verdict": "clean",
        }
        request_id = uuid4()
        request_path = write_request(
            self.root,
            request_id=request_id,
            content=content,
            media_type=media_type or "application/octet-stream",
            original_filename="document.bin",
            options=safe_options,
            scan=scan,
        )
        result_path = self.root / "results" / f"{request_id}.json"
        content_path = request_path.parent / f"{request_id}.bin"
        claimed_path = self.root / "claimed" / request_path.name
        deadline = time.monotonic() + max(0.1, min(self.wait_seconds, safe_options["timeout_seconds"] + 10.0))
        try:
            while not result_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not result_path.is_file():
                raise DocumentProcessingError("converter_unavailable", "문서 변환기를 사용할 수 없습니다", source_preserved=True)
            try:
                if result_path.stat().st_size > MAX_RESULT_BYTES:
                    raise DocumentProcessingError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다", source_preserved=True)
            except OSError as error:
                raise DocumentProcessingError("processing_failed", "문서 처리 결과를 읽을 수 없습니다", source_preserved=True) from error
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise DocumentProcessingError("processing_failed", "문서 처리 결과를 읽을 수 없습니다", source_preserved=True) from error
            if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA or result.get("request_id") != str(request_id):
                raise DocumentProcessingError("processing_failed", "문서 처리 결과가 올바르지 않습니다", source_preserved=True)
            if result.get("status") != "succeeded":
                detail = result.get("error")
                code = detail.get("code") if isinstance(detail, Mapping) else "processing_failed"
                safe_code = code if isinstance(code, str) and code in {
                    "timeout", "processing_failed", "conversion_required", "unsupported_media",
                    "malformed_pdf", "malformed_archive", "invalid_options", "mime_mismatch",
                    "output_size_limit", "pdf_object_limit", "pdf_page_limit", "pdf_page_mismatch",
                    "pdf_empty_text",
                } else "processing_failed"
                raise DocumentProcessingError(safe_code, "문서 처리를 완료할 수 없습니다", source_preserved=True)
            payload = result.get("structure")
            if not isinstance(payload, dict):
                raise DocumentProcessingError("processing_failed", "문서 구조 결과가 올바르지 않습니다", source_preserved=True)
            if payload.get("source_sha256") != hashlib.sha256(content).hexdigest():
                raise DocumentProcessingError("hash_mismatch", "문서 처리 결과 원문 hash가 일치하지 않습니다", source_preserved=True)
            validate_structure(
                payload,
                max_output_bytes=safe_options["max_output_bytes"],
                max_pages=safe_options["max_pages"],
                max_blocks=safe_options["max_blocks"],
            )
            return ProcessedDocument(payload, original_bytes=content)
        except ScratchProtocolError as error:
            raise DocumentProcessingError("processing_failed", "문서 처리 요청이 올바르지 않습니다", source_preserved=True) from error
        finally:
            # The converter removes its claimed/input files.  Only clean an
            # unclaimed inbox request after timeout; a claimed request's
            # content belongs to the document-worker and must not be deleted here.
            if not result_path.exists() and not claimed_path.exists():
                try:
                    request_path.unlink()
                except FileNotFoundError:
                    pass
                else:
                    content_path.unlink(missing_ok=True)
            # Only the result owned by this request is removed here, after it
            # was consumed.
            result_path.unlink(missing_ok=True)


__all__ = ["ScratchDocumentProcessor"]
