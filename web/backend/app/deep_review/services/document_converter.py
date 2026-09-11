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
    PDF_RESULT_SCHEMA,
    RESULT_SCHEMA,
    ScratchProtocolError,
    read_bounded_file,
    read_pdf_sidecar,
    read_native_sidecars,
    native_sidecar_paths,
    validate_original_pdf_metadata,
    write_request,
)


SAFE_CONVERTER_CODES = frozenset({
    "timeout", "processing_failed", "conversion_required", "unsupported_media",
    "malformed_pdf", "malformed_archive", "invalid_options", "mime_mismatch",
    "output_size_limit", "input_size_limit", "pdf_object_limit", "pdf_page_limit", "pdf_page_mismatch",
    "pdf_empty_text", "pdf_sidecar_missing", "hash_mismatch", "pdf_metadata_invalid",
    "hwpx_verify_failed", "encrypted_document", "rhwp_manifest_invalid", "para_page_map_invalid",
    "section_candidates_invalid",
    "renderer_binding_invalid", "font_binding_invalid", "converter_unavailable", "malformed_hwpx",
    "unsafe_xml", "xml_depth_limit", "archive_traversal", "archive_size_limit", "block_limit",
    "invalid_structure", "page_limit", "malware_detected", "clamav_unavailable", "missing_file",
    "encrypted_pdf", "archive_file_limit", "archive_duplicate", "archive_link", "encrypted_archive",
    "archive_member_limit", "archive_ratio_limit", "archive_depth_limit", "invalid_input", "render_failed",
})


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
            safe_options = vars(ProcessorOptions.from_mapping(options))
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
        pdf_directory = self.root / "pdf"
        sidecar_path = None if pdf_directory.is_symlink() or not pdf_directory.is_dir() else pdf_directory / f"{request_id}.pdf"
        deadline = time.monotonic() + max(0.1, min(self.wait_seconds, safe_options["timeout_seconds"] + 10.0))
        result_seen = False
        try:
            while not result_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not result_path.is_file():
                raise DocumentProcessingError("converter_unavailable", "문서 변환기를 사용할 수 없습니다", source_preserved=True)
            result_seen = True
            try:
                result = json.loads(read_bounded_file(result_path, limit=MAX_RESULT_BYTES).decode("utf-8"))
            except ScratchProtocolError as error:
                raise DocumentProcessingError(error.code, "문서 처리 결과를 읽을 수 없습니다", source_preserved=True) from error
            except (UnicodeError, json.JSONDecodeError) as error:
                raise DocumentProcessingError("processing_failed", "문서 처리 결과를 읽을 수 없습니다", source_preserved=True) from error
            expected_schema = PDF_RESULT_SCHEMA if safe_options["prepare_pdf"] else RESULT_SCHEMA
            if not isinstance(result, Mapping) or result.get("schema") != expected_schema or result.get("request_id") != str(request_id):
                raise DocumentProcessingError("processing_failed", "문서 처리 결과가 올바르지 않습니다", source_preserved=True)
            if result.get("status") != "succeeded":
                detail = result.get("error")
                code = detail.get("code") if isinstance(detail, Mapping) else "processing_failed"
                safe_code = code if isinstance(code, str) and code in SAFE_CONVERTER_CODES else "processing_failed"
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
            converted_pdf: bytes | None = None
            pdf_metadata: dict[str, Any] = {}
            native_artifacts: dict[str, Any] = {}
            if expected_schema == PDF_RESULT_SCHEMA:
                descriptor = result.get("pdf_sidecar")
                if not isinstance(descriptor, Mapping) or sidecar_path is None:
                    raise DocumentProcessingError("pdf_sidecar_missing", "PDF sidecar를 확인할 수 없습니다", source_preserved=True)
                try:
                    converted_pdf, pdf_metadata, source_kind = read_pdf_sidecar(
                        self.root,
                        str(request_id),
                        descriptor,
                        max_bytes=safe_options["max_output_bytes"],
                    )
                except ScratchProtocolError as error:
                    raise DocumentProcessingError(error.code, "PDF sidecar 무결성을 확인할 수 없습니다", source_preserved=True) from error
                if source_kind == "original":
                    if payload.get("media_type") != "application/pdf" or converted_pdf != content:
                        raise DocumentProcessingError(
                            "hash_mismatch",
                            "원본 PDF sidecar가 입력 원문과 일치하지 않습니다",
                            source_preserved=True,
                        )
                    try:
                        validate_original_pdf_metadata(pdf_metadata, payload)
                    except ScratchProtocolError as error:
                        raise DocumentProcessingError(
                            error.code,
                            "원본 PDF page metadata를 확인할 수 없습니다",
                            source_preserved=True,
                        ) from error
                elif payload.get("media_type") == "application/pdf":
                    raise DocumentProcessingError(
                        "processing_failed",
                        "PDF source kind이 입력 media type과 일치하지 않습니다",
                        source_preserved=True,
                    )
                if safe_options["renderer"] == "rhwp-svg-pdf" and payload.get("media_type") != "application/pdf":
                    native_artifacts = read_native_sidecars(
                        self.root, str(request_id), result.get("native_sidecars"),
                        structure=payload, source=content, pdf_metadata=pdf_metadata,
                        options=ProcessorOptions.from_mapping(safe_options),
                    )
                try:
                    pdf_scan = self.clamav_checker(converted_pdf)
                except Exception as error:
                    raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True) from error
                if pdf_scan is False:
                    raise DocumentProcessingError("malware_detected", "malware 검사에서 차단되었습니다", source_preserved=True)
                if pdf_scan is not True:
                    raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True)
                if native_artifacts and payload.get("media_type") == "application/x-hwp":
                    try:
                        hwpx_scan = self.clamav_checker(native_artifacts["hwpx_bytes"])
                    except Exception as error:
                        raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True) from error
                    if hwpx_scan is not True:
                        code = "malware_detected" if hwpx_scan is False else "clamav_unavailable"
                        raise DocumentProcessingError(code, "malware 검사를 완료할 수 없습니다", source_preserved=True)
            return ProcessedDocument(
                payload,
                original_bytes=content,
                converted_pdf_bytes=converted_pdf,
                pdf_metadata=pdf_metadata,
                converted_bytes=native_artifacts.get("hwpx_bytes") if payload.get("media_type") == "application/x-hwp" else None,
                **native_artifacts,
            )
        except ScratchProtocolError as error:
            raise DocumentProcessingError(error.code, "문서 처리 요청이 올바르지 않습니다", source_preserved=True) from error
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
            # A result is owned by this request once it was observed.  Keep a
            # claimed worker input intact during a timeout; the worker may
            # still be finishing its atomic sidecar/result publish.
            if result_seen:
                result_path.unlink(missing_ok=True)
            if sidecar_path is not None and not claimed_path.exists():
                sidecar_path.unlink(missing_ok=True)
            if result_seen and not claimed_path.exists():
                try:
                    paths = native_sidecar_paths(self.root, str(request_id))
                except ScratchProtocolError:
                    paths = {}
                for path in paths.values():
                    path.unlink(missing_ok=True)


__all__ = ["SAFE_CONVERTER_CODES", "ScratchDocumentProcessor"]
