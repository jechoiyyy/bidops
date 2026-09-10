"""Strict adapter for the vendored rhwp v0.8.6 JSON command surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from .errors import DocumentProcessingError
from .hwpx import extract_hwpx
from .pdf import extract_pdf
from .safety import PDF_MAGIC, ZIP_MAGIC, ProcessorOptions, validate_zip

RHWP_SCHEMA_VERSION = "1.0"
RHWP_STDOUT_LIMIT = 1024 * 1024
RHWP_RENDERER = "rhwp-svg-pdf"
RHWP_VERSION = "0.8.6"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION_LINE = re.compile(r"^rhwp v([0-9]+\.[0-9]+\.[0-9]+)$")


def _integer(value: Any, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    return value


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    return value


def _base_manifest(stdout: bytes) -> dict[str, Any]:
    try:
        value = json.loads(stdout.decode("utf-8", "strict"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True) from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != RHWP_SCHEMA_VERSION:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    if not isinstance(value.get("source"), str) or not value["source"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    if not isinstance(value.get("untrustedContent"), bool):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    fields = value.get("untrustedFields")
    if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp 결과 계약이 올바르지 않습니다", source_preserved=True)
    return value


def parse_hwpx_manifest(stdout: bytes, artifact: bytes) -> dict[str, Any]:
    value = _base_manifest(stdout)
    verify = value.get("verify")
    verify_pages = value.get("verifyPages")
    if value.get("format") != "hwpx" or not isinstance(value.get("output"), str) or not value["output"] or value["untrustedContent"] or value["untrustedFields"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp HWPX 결과 계약이 올바르지 않습니다", source_preserved=True)
    if _boolean(value.get("passwordProtected")):
        raise DocumentProcessingError("encrypted_document", "암호화된 HWP 문서는 처리할 수 없습니다", source_preserved=True)
    if not isinstance(verify, Mapping) or not isinstance(verify_pages, Mapping):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp HWPX 검증 계약이 올바르지 않습니다", source_preserved=True)
    diff_count = _integer(verify.get("diffCount"))
    before = _integer(verify_pages.get("before"), minimum=1)
    after = _integer(verify_pages.get("after"), minimum=1)
    identical = _boolean(verify.get("identical"))
    pages_identical = _boolean(verify_pages.get("identical"))
    size = _integer(value.get("bytes"), minimum=1)
    if not identical or not pages_identical or diff_count != 0 or before != after:
        raise DocumentProcessingError("hwpx_verify_failed", "HWPX 변환 검증에 실패했습니다", source_preserved=True)
    if size != len(artifact) or not artifact.startswith((ZIP_MAGIC, b"PK\x05\x06", b"PK\x07\x08")):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp HWPX 산출물을 확인할 수 없습니다", source_preserved=True)
    return {"identical": True, "diff_count": diff_count, "pages": {"before": before, "after": after, "identical": True}}


def parse_pdf_manifest(stdout: bytes, artifact: bytes) -> int:
    value = _base_manifest(stdout)
    if value.get("format") != "pdf" or value.get("backend") != "svg" or not isinstance(value.get("output"), str) or not value["output"] or value["untrustedContent"] or value["untrustedFields"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp PDF 결과 계약이 올바르지 않습니다", source_preserved=True)
    page_count = _integer(value.get("pageCount"), minimum=1)
    rendered_count = _integer(value.get("renderedCount"), minimum=1)
    size = _integer(value.get("bytes"), minimum=1)
    if page_count != rendered_count:
        raise DocumentProcessingError("pdf_page_mismatch", "변환 PDF page 대응을 확인할 수 없습니다", source_preserved=True)
    if size != len(artifact) or not artifact.startswith(PDF_MAGIC):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp PDF 산출물을 확인할 수 없습니다", source_preserved=True)
    return page_count


def parse_page_text_manifest(stdout: bytes, expected_pages: int) -> dict[str, Any]:
    value = _base_manifest(stdout)
    if not value["untrustedContent"] or "pages[].text" not in value["untrustedFields"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text 신뢰 표식이 올바르지 않습니다", source_preserved=True)
    page_count = _integer(value.get("pageCount"), minimum=1)
    omitted = _integer(value.get("omittedCount"))
    truncated = _boolean(value.get("truncated"))
    pages = value.get("pages")
    if page_count != expected_pages:
        raise DocumentProcessingError("pdf_page_mismatch", "변환 page text 대응을 확인할 수 없습니다", source_preserved=True)
    if omitted != 0 or truncated:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text가 생략되었습니다", source_preserved=True)
    if not isinstance(pages, list) or len(pages) != page_count:
        raise DocumentProcessingError("pdf_page_mismatch", "변환 page text 대응을 확인할 수 없습니다", source_preserved=True)
    result_pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in pages:
        if not isinstance(page, dict) or set(page) - {"page", "text", "truncated", "omittedCount"}:
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text 계약이 올바르지 않습니다", source_preserved=True)
        index = _integer(page.get("page"))
        text = page.get("text")
        if not isinstance(text, str) or index >= page_count or index in seen:
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text 번호가 올바르지 않습니다", source_preserved=True)
        page_truncated = _boolean(page["truncated"]) if "truncated" in page else False
        page_omitted = _integer(page["omittedCount"]) if "omittedCount" in page else 0
        if page_truncated or page_omitted != 0:
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text가 생략되었습니다", source_preserved=True)
        seen.add(index)
        result_pages.append({"number": index + 1, "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    if seen != set(range(page_count)):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page text 번호가 연속적이지 않습니다", source_preserved=True)
    result_pages.sort(key=lambda item: item["number"])
    if not any(item["text"].strip() for item in result_pages):
        raise DocumentProcessingError("pdf_empty_text", "변환 PDF에서 읽을 수 있는 page text가 없습니다", source_preserved=True)
    return {"schema": "bidops.rhwp-page-text.v1", "page_count": page_count, "pages": result_pages}


def parse_page_dump_manifest(stdout: bytes, expected_pages: int) -> dict[str, Any]:
    value = _base_manifest(stdout)
    if not value["untrustedContent"] or "pages[].columns[].items[].textPreview" not in value["untrustedFields"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page 배치 신뢰 표식이 올바르지 않습니다", source_preserved=True)
    if value.get("pageFilter") is not None or not isinstance(value.get("respectVposReset"), bool):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page 배치 option 계약이 올바르지 않습니다", source_preserved=True)
    page_count = _integer(value.get("pageCount"), minimum=1)
    pages = value.get("pages")
    if page_count != expected_pages or not isinstance(pages, list) or len(pages) != page_count:
        raise DocumentProcessingError("pdf_page_mismatch", "rhwp page 배치 대응을 확인할 수 없습니다", source_preserved=True)
    sanitized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page 배치 계약이 올바르지 않습니다", source_preserved=True)
        index = _integer(page.get("pageIndex"))
        _integer(page.get("pageNumber"), minimum=1)
        section = _integer(page.get("section"))
        display_page = page.get("displayPage")
        if display_page is not None:
            display_page = _integer(display_page)
        # pageNumber is the document's printed numbering and may restart;
        # pageIndex alone is the continuous physical identity in Spec section 1.
        if index >= page_count or index in seen or not isinstance(page.get("columns"), list) or not isinstance(page.get("extras"), list):
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page 배치 번호가 올바르지 않습니다", source_preserved=True)
        seen.add(index)
        columns: list[dict[str, Any]] = []
        for column in page["columns"]:
            if not isinstance(column, dict) or not isinstance(column.get("items"), list):
                raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp paragraph 배치 계약이 올바르지 않습니다", source_preserved=True)
            items = [_sanitize_dump_item(item, extras=False) for item in column["items"]]
            columns.append({"items": items})
        extras = [_sanitize_dump_item(item, extras=True) for item in page["extras"]]
        sanitized.append({"pageIndex": index, "displayPage": display_page, "section": section, "columns": columns, "extras": extras})
    if seen != set(range(page_count)):
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp page 배치 번호가 연속적이지 않습니다", source_preserved=True)
    sanitized.sort(key=lambda item: item["pageIndex"])
    return {"schemaVersion": RHWP_SCHEMA_VERSION, "pageCount": page_count, "pages": sanitized}


def _sanitize_dump_item(item: Any, *, extras: bool) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not item["kind"]:
        raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp paragraph 배치 계약이 올바르지 않습니다", source_preserved=True)
    para_index = _integer(item.get("paraIndex"))
    result: dict[str, Any] = {"kind": item["kind"], "paraIndex": para_index}
    if not extras:
        result["isEndnote"] = _boolean(item.get("isEndnote"))
    # textPreview and every other document-derived field are intentionally dropped.
    return result


class NativeRhwpProcessor:
    """Execute native conversion while preserving the existing structure schema."""

    def __init__(
        self,
        executable: str,
        *,
        run: Any,
        limiter: Any,
        child_environment: Any,
        timeout_error: type[BaseException],
        output_error: type[BaseException],
        font_manifest: Any,
    ) -> None:
        self.executable = str(Path(executable).resolve())
        self._run = run
        self._limiter = limiter
        self._child_environment = child_environment
        self._timeout_error = timeout_error
        self._output_error = output_error
        self._font_manifest = font_manifest

    def process(self, original: bytes, media_type: str, options: ProcessorOptions, deadline: float) -> dict[str, Any]:
        if media_type not in {"application/x-hwp", "application/hwp+zip"}:
            raise DocumentProcessingError("unsupported_media", "native renderer 입력 형식이 올바르지 않습니다", source_preserved=True)
        if media_type == "application/hwp+zip":
            archive = validate_zip(original, options)
            archive.close()
        binary_sha = self._fingerprint_binary()
        with tempfile.TemporaryDirectory(prefix="bidops-rhwp-") as tmp:
            root = Path(tmp)
            extension = "hwp" if media_type == "application/x-hwp" else "hwpx"
            source = root / f"source.{extension}"
            source.write_bytes(original)
            converted: bytes | None = None
            verify: dict[str, Any] | None = None
            if media_type == "application/x-hwp":
                converted_path = root / "converted.hwpx"
                stdout = self._call(["export-hwpx", source.name, converted_path.name, "--verify", "--verify-pages", "--json"], root, options, deadline, verify_exit=True)
                converted = self._read_artifact(converted_path, options)
                verify = parse_hwpx_manifest(stdout, converted)
                archive = validate_zip(converted, options)
                archive.close()
                structure_source = converted
            else:
                structure_source = original
            pages, blocks, warnings = extract_hwpx(structure_source, options)

            if not options.prepare_pdf:
                return {
                    "pages": pages,
                    "blocks": blocks,
                    "warnings": warnings,
                    "converted": converted,
                    "verify": verify,
                    "pdf": None,
                    "pdf_metadata": {},
                    "page_text": {},
                    "page_dump": {},
                }

            pdf_path = root / "output.pdf"
            pdf_stdout = self._call(["export-pdf", source.name, "-o", pdf_path.name, "--backend", "svg", "--fallback-serif", "NanumMyeongjo", "--fallback-sans", "NanumGothic", "--fallback-mono", "NanumGothicCoding", "--json"], root, options, deadline)
            pdf = self._read_artifact(pdf_path, options)
            page_count = parse_pdf_manifest(pdf_stdout, pdf)
            if page_count > min(options.max_pages, options.max_pdf_pages):
                raise DocumentProcessingError("pdf_page_limit", "PDF page 수 제한을 초과했습니다", source_preserved=True)
            try:
                extract_pdf(pdf, options)
            except DocumentProcessingError as exc:
                if exc.code != "malformed_pdf":
                    raise
            if self._pdfinfo_pages(pdf_path, root, options, deadline) != page_count:
                raise DocumentProcessingError("pdf_page_mismatch", "변환 PDF page 대응을 확인할 수 없습니다", source_preserved=True)
            text = parse_page_text_manifest(self._call(["export-text", source.name, "--json"], root, options, deadline), page_count)
            dump = parse_page_dump_manifest(self._call(["dump-pages", source.name, "--json"], root, options, deadline), page_count)
            self._check_json_artifact(text, options)
            self._check_json_artifact(dump, options)
            for page, dump_page in zip(text["pages"], dump["pages"]):
                page["display_page"] = dump_page["displayPage"]
                page["section"] = dump_page["section"]
            version = self._version(root, options, deadline)
            font_digest = self._font_manifest(options, deadline)
            renderer_provenance = {"renderer": RHWP_RENDERER, "rhwp_version": version, "rhwp_binary_sha256": binary_sha, "backend": "svg", "compat": "2022", "fallback_fonts": {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"}, "worker_image_digest": self._image_digest()}
            pdf_metadata = {"schema": "bidops.rhwp-pdf-snapshot.v1", "renderer": RHWP_RENDERER, "renderer_version": "1", "page_count": page_count, "renderer_provenance": renderer_provenance, "font_provenance": {"font_manifest_sha256": font_digest}, "pages": [{"number": item["number"], "display_page": item["display_page"], "section": item["section"], "text_sha256": item["text_sha256"]} for item in text["pages"]]}
            return {"pages": pages, "blocks": blocks, "warnings": warnings, "converted": converted, "verify": verify, "pdf": pdf, "pdf_metadata": pdf_metadata, "page_text": text, "page_dump": dump}

    def _call(self, arguments: list[str], root: Path, options: ProcessorOptions, deadline: float, *, verify_exit: bool = False) -> bytes:
        try:
            code, stdout, stderr = self._run([self.executable, *map(str, arguments)], cwd=str(root), env=self._child_environment(self.executable), timeout=self._remaining(deadline, options), output_limit=RHWP_STDOUT_LIMIT, preexec_fn=self._limiter(options.max_output_bytes))
        except self._timeout_error as exc:
            raise DocumentProcessingError("timeout", "rhwp 문서 처리 시간이 제한을 초과했습니다", source_preserved=True) from exc
        except self._output_error as exc:
            raise DocumentProcessingError("output_size_limit", "rhwp JSON 출력 크기 제한을 초과했습니다", source_preserved=True) from exc
        except subprocess.SubprocessError as exc:
            raise DocumentProcessingError("converter_unavailable", "rhwp 변환기를 사용할 수 없습니다", source_preserved=True) from exc
        except OSError as exc:
            raise DocumentProcessingError("converter_unavailable", "rhwp 변환기를 사용할 수 없습니다", source_preserved=True) from exc
        if verify_exit and code in {3, 4}:
            raise DocumentProcessingError("hwpx_verify_failed", "HWPX 변환 검증에 실패했습니다", source_preserved=True)
        if code != 0:
            lowered = stderr.lower()
            if b"encrypted" in lowered or "암호".encode("utf-8") in stderr:
                raise DocumentProcessingError("encrypted_document", "암호화된 HWP 문서는 처리할 수 없습니다", source_preserved=True)
            raise DocumentProcessingError("conversion_required", "rhwp 문서 변환 확인이 필요합니다", source_preserved=True)
        return stdout

    @staticmethod
    def _check_json_artifact(value: Mapping[str, Any], options: ProcessorOptions) -> None:
        try:
            size = len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise DocumentProcessingError("rhwp_manifest_invalid", "rhwp JSON 산출물을 확인할 수 없습니다", source_preserved=True) from exc
        if size > options.max_output_bytes:
            raise DocumentProcessingError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다", source_preserved=True)

    def _read_artifact(self, path: Path, options: ProcessorOptions) -> bytes:
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                file_stat = os.fstat(handle.fileno())
                if not stat.S_ISREG(file_stat.st_mode) or not 1 <= file_stat.st_size <= options.max_output_bytes:
                    raise DocumentProcessingError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다", source_preserved=True)
                artifact = handle.read(options.max_output_bytes + 1)
            if len(artifact) != file_stat.st_size:
                raise DocumentProcessingError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다", source_preserved=True)
            return artifact
        except DocumentProcessingError:
            raise
        except OSError as exc:
            raise DocumentProcessingError("conversion_required", "rhwp 산출물을 확인할 수 없습니다", source_preserved=True) from exc

    def _pdfinfo_pages(self, pdf: Path, root: Path, options: ProcessorOptions, deadline: float) -> int:
        executable = shutil.which("pdfinfo")
        if not executable:
            raise DocumentProcessingError("converter_unavailable", "PDF page 수를 확인할 수 없습니다", source_preserved=True)
        try:
            code, stdout, _stderr = self._run([executable, pdf.name], cwd=str(root), env=self._child_environment(executable), timeout=self._remaining(deadline, options), output_limit=64 * 1024, preexec_fn=self._limiter(options.max_output_bytes))
        except self._timeout_error as exc:
            raise DocumentProcessingError("timeout", "PDF page 확인 시간이 제한을 초과했습니다", source_preserved=True) from exc
        except self._output_error as exc:
            raise DocumentProcessingError("output_size_limit", "PDF metadata 크기 제한을 초과했습니다", source_preserved=True) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentProcessingError("converter_unavailable", "PDF page 수를 확인할 수 없습니다", source_preserved=True) from exc
        if code != 0:
            raise DocumentProcessingError("conversion_required", "PDF page 수를 확인할 수 없습니다", source_preserved=True)
        try:
            match = re.search(rb"(?m)^Pages:\s*([0-9]+)\s*$", stdout)
            if match is None:
                raise ValueError
            return int(match.group(1))
        except ValueError as exc:
            raise DocumentProcessingError("rhwp_manifest_invalid", "PDF page 수 계약이 올바르지 않습니다", source_preserved=True) from exc

    def _version(self, root: Path, options: ProcessorOptions, deadline: float) -> str:
        try:
            code, stdout, _stderr = self._run([self.executable, "--version"], cwd=str(root), env=self._child_environment(self.executable), timeout=self._remaining(deadline, options), output_limit=4096, preexec_fn=self._limiter(options.max_output_bytes))
        except (self._timeout_error, self._output_error, OSError, subprocess.SubprocessError) as exc:
            raise DocumentProcessingError("renderer_binding_invalid", "rhwp renderer binding을 확인할 수 없습니다", source_preserved=True) from exc
        try:
            match = _VERSION_LINE.fullmatch(stdout.decode("ascii", "strict").strip())
        except UnicodeError:
            match = None
        if code != 0 or match is None or match.group(1) != RHWP_VERSION:
            raise DocumentProcessingError("renderer_binding_invalid", "rhwp renderer binding을 확인할 수 없습니다", source_preserved=True)
        return match.group(1)

    def _fingerprint_binary(self) -> str:
        try:
            binary = Path(self.executable)
            size = binary.stat().st_size
            if not binary.is_file() or not os.access(self.executable, os.X_OK) or not 1 <= size <= 64 * 1024 * 1024:
                raise OSError
            content = binary.read_bytes()
            if len(content) != size:
                raise OSError
            return hashlib.sha256(content).hexdigest()
        except OSError as exc:
            raise DocumentProcessingError("converter_unavailable", "rhwp 변환기를 사용할 수 없습니다", source_preserved=True) from exc

    @staticmethod
    def _remaining(deadline: float, options: ProcessorOptions) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DocumentProcessingError("timeout", "rhwp 문서 처리 시간이 제한을 초과했습니다", source_preserved=True)
        return min(float(options.timeout_seconds), remaining)

    @staticmethod
    def _image_digest() -> str | None:
        value = os.environ.get("BIDOPS_DOCUMENT_WORKER_IMAGE_DIGEST", "").strip().lower()
        if value and not _SHA256.fullmatch(value):
            raise DocumentProcessingError("renderer_binding_invalid", "document-worker image digest 선언을 확인할 수 없습니다", source_preserved=True)
        return value or None
