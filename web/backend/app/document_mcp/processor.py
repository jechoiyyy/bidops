"""Bytes-first, quarantine-safe document processor."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import SCHEMA, UPSTREAM_COMMIT, validate_structure
from .errors import DocumentProcessingError
from .hwpx import extract_hwpx, extractor_info
from .pdf import PdfPage, extract_pdf
from .safety import ProcessorOptions, detect_media_type, enforce_input_limit, image_dimensions

OCRResult = str | tuple[str, float | None] | dict[str, Any]
OCREngine = Callable[[bytes, str], OCRResult]
ClamAVChecker = Callable[[bytes], bool | None]


class ProcessedDocument(dict[str, Any]):
    """Contract mapping with quarantined source provenance kept out of JSON.

    ``dict(processed)`` and JSON serialization contain exactly the structure
    contract.  The non-serializable source/conversion fields are available only
    to the quarantine storage adapter, so an analysis client cannot accidentally
    receive the original HWP bytes.
    """

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        original_bytes: bytes,
        converted_bytes: bytes | None = None,
        rendered_pages: dict[int, bytes] | None = None,
    ) -> None:
        super().__init__(payload)
        self.original_bytes = original_bytes
        self.converted_bytes = converted_bytes
        self.rendered_pages = rendered_pages or {}


def _resource_limiter() -> Callable[[], None] | None:
    if os.name != "posix":
        return None
    try:
        import resource
    except ImportError:
        return None

    def limit() -> None:
        # The worker process itself remains alive; only the child converter is
        # capped.  Memory is deliberately below the default container limit.
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        # RLIMIT_AS prevents Node/V8 from reserving its WebAssembly virtual
        # address space even for a small input.  RLIMIT_DATA still bounds the
        # process data segment while allowing the fixed vendored WASM runtime
        # to start.  Containers provide the final RSS/cgroup ceiling.
        resource.setrlimit(resource.RLIMIT_DATA, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))

    return limit


class DocumentProcessor:
    """Process HWP/HWPX/PDF/image bytes into a constrained structure JSON."""

    def __init__(
        self,
        *,
        ocr_engine: OCREngine | None = None,
        node_executable: str | None = None,
        clamav_checker: ClamAVChecker | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.clamav_checker = clamav_checker
        # A trusted worker may choose an absolute node path.  It is not exposed
        # through request options and never comes from document input.
        self.node_executable = node_executable or shutil.which("node")

    def process(
        self,
        content: bytes,
        media_type: str | None = None,
        options: ProcessorOptions | dict[str, Any] | None = None,
    ) -> ProcessedDocument:
        opts = ProcessorOptions.from_mapping(options)
        original = enforce_input_limit(content)
        detected = detect_media_type(original, media_type)
        source_hash = hashlib.sha256(original).hexdigest()
        converted: bytes | None = None
        rendered: dict[int, bytes] = {}
        warnings: list[str] = []
        if self.clamav_checker is None:
            # No claim of a clean scan is made when ClamAV is not available.
            # The bundle/quarantine layer must keep this source blocked.
            warnings.append("clamav_unavailable")
        else:
            try:
                scan_result = self.clamav_checker(original)
            except Exception as exc:  # trusted adapter failures remain quarantine failures
                raise DocumentProcessingError("clamav_unavailable", "malware 검사를 완료할 수 없습니다", source_preserved=True) from exc
            if scan_result is False:
                raise DocumentProcessingError("malware_detected", "malware 검사에서 차단되었습니다", source_preserved=True)
            if scan_result is not True:
                warnings.append("clamav_unavailable")
        if detected == "application/x-hwp":
            try:
                converted = self._convert_hwp(original, opts)
                pages, blocks, child_warnings = extract_hwpx(converted, opts)
                warnings.extend(child_warnings)
                extractor = {"name": "hwp-rhwp-hwpx", "version": "1", "upstream_commit": UPSTREAM_COMMIT}
            except DocumentProcessingError as exc:
                exc.source_preserved = True
                if exc.code in {"timeout", "converter_unavailable", "conversion_required", "malformed_hwpx", "malformed_archive"}:
                    exc.code = "conversion_required"
                    exc.message = "HWP 변환 확인 필요"
                raise
        elif detected == "application/hwp+zip":
            pages, blocks, child_warnings = extract_hwpx(original, opts)
            warnings.extend(child_warnings)
            extractor = extractor_info()
        elif detected == "application/pdf":
            pages, blocks, child_warnings, parsed_pages = extract_pdf(original, opts)
            warnings.extend(child_warnings)
            extractor = {"name": "pdf-stdlib", "version": "1", "upstream_commit": None}
            if opts.render_pages or (opts.ocr and all(not page.text for page in parsed_pages)):
                for page in parsed_pages:
                    try:
                        rendered_page = self._render_pdf_page(original, page.number, opts)
                    except DocumentProcessingError as exc:
                        if exc.code == "renderer_unavailable":
                            warnings.append("page_render_unavailable")
                            if opts.ocr:
                                warnings.append("ocr_unavailable")
                            continue
                        raise
                    rendered[page.number] = rendered_page
                    for item in pages:
                        if item["number"] == page.number:
                            item["image_content_object_id"] = str(uuid.uuid4())
                            break
                if opts.ocr and rendered:
                    self._ocr_pages(rendered, pages, blocks, warnings, timeout_seconds=opts.timeout_seconds)
        elif detected.startswith("image/"):
            width, height = image_dimensions(original, detected)
            if width <= 0 or height <= 0 or width > 100_000 or height > 100_000 or width * height > 100_000_000:
                raise DocumentProcessingError("image_size_limit", "이미지 해상도 제한을 초과했습니다")
            pages = [{"number": 1, "width": float(width), "height": float(height), "image_content_object_id": str(uuid.uuid4())}]
            blocks = []
            extractor = {"name": "image-ocr", "version": "1", "upstream_commit": None}
            rendered[1] = original
            if opts.ocr:
                self._ocr_pages(rendered, pages, blocks, warnings, image_media_type=detected, timeout_seconds=opts.timeout_seconds)
        else:  # pragma: no cover - detect_media_type is exhaustive
            raise DocumentProcessingError("unsupported_media", "지원하지 않는 문서 형식입니다")

        payload = {
            "schema": SCHEMA,
            "structure_id": str(uuid.uuid4()),
            "document_version_id": str(uuid.uuid4()),
            "source_sha256": source_hash,
            "media_type": detected,
            "extractor": extractor,
            "pages": pages,
            "blocks": blocks,
            "warnings": sorted(set(warnings)),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        validate_structure(payload)
        return ProcessedDocument(
            payload,
            original_bytes=original,
            converted_bytes=converted,
            rendered_pages=rendered,
        )

    def _convert_hwp(self, original: bytes, options: ProcessorOptions) -> bytes:
        if not self.node_executable:
            raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True)
        script = Path(__file__).with_name("vendor") / "rhwp_convert.mjs"
        if not script.is_file():
            raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True)
        with tempfile.TemporaryDirectory(prefix="bidops-doc-") as tmp:
            source = Path(tmp) / "source.hwp"
            source.write_bytes(original)
            env = {
                "PATH": str(Path(self.node_executable).parent),
                "NODE_OPTIONS": "--no-warnings",
                "LC_ALL": "C.UTF-8",
            }
            try:
                completed = subprocess.run(
                    [self.node_executable, str(script), "--stdout", str(source)],
                    cwd=tmp,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    timeout=options.timeout_seconds,
                    check=False,
                    preexec_fn=_resource_limiter(),
                )
            except subprocess.TimeoutExpired as exc:
                raise DocumentProcessingError("timeout", "문서 변환 시간이 제한을 초과했습니다", source_preserved=True) from exc
            except OSError as exc:
                raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True) from exc
            if completed.returncode != 0 or not completed.stdout:
                raise DocumentProcessingError("conversion_required", "HWP 변환 확인 필요", source_preserved=True)
            if len(completed.stdout) > options.max_output_bytes:
                raise DocumentProcessingError("output_size_limit", "변환 결과 크기 제한을 초과했습니다", source_preserved=True)
            if not completed.stdout.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                raise DocumentProcessingError("conversion_required", "HWP 변환 확인 필요", source_preserved=True)
            return completed.stdout

    def _render_pdf_page(self, original: bytes, page: int, options: ProcessorOptions) -> bytes:
        executable = shutil.which("pdftoppm")
        if not executable:
            raise DocumentProcessingError("renderer_unavailable", "PDF page render 도구를 사용할 수 없습니다")
        with tempfile.TemporaryDirectory(prefix="bidops-render-") as tmp:
            source = Path(tmp) / "source.pdf"
            prefix = Path(tmp) / "page"
            source.write_bytes(original)
            env = {"PATH": str(Path(executable).parent), "LC_ALL": "C.UTF-8"}
            try:
                completed = subprocess.run(
                    [executable, "-f", str(page), "-l", str(page), "-png", "-singlefile", str(source), str(prefix)],
                    cwd=tmp, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, shell=False, timeout=options.timeout_seconds,
                    check=False, preexec_fn=_resource_limiter(),
                )
            except subprocess.TimeoutExpired as exc:
                raise DocumentProcessingError("timeout", "page render 시간이 제한을 초과했습니다") from exc
            if completed.returncode != 0:
                raise DocumentProcessingError("render_failed", "PDF page를 render할 수 없습니다")
            output = prefix.with_suffix(".png")
            if not output.is_file() or output.stat().st_size > options.max_output_bytes:
                raise DocumentProcessingError("output_size_limit", "page render 결과 크기 제한을 초과했습니다")
            return output.read_bytes()

    def _ocr_pages(
        self,
        rendered: dict[int, bytes],
        pages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        warnings: list[str],
        *,
        image_media_type: str = "image/png",
        timeout_seconds: float = 30.0,
    ) -> None:
        for page_number, image in sorted(rendered.items()):
            try:
                text, confidence = self._ocr(image, image_media_type, timeout_seconds=timeout_seconds)
            except DocumentProcessingError as exc:
                if exc.code == "ocr_unavailable":
                    warnings.append("ocr_unavailable")
                    continue
                raise
            if text:
                page = next((item for item in pages if item["number"] == page_number), None)
                bbox = [0.0, 0.0, float(page["width"]), float(page["height"])] if page else None
                blocks.append({
                    "block_key": f"page-{page_number}-ocr",
                    "parent_block_key": None,
                    "type": "ocr_text",
                    "page": page_number,
                    "bbox": bbox,
                    "text": text,
                    "confidence": confidence,
                    "attributes": {"source": "ocr", "media": image_media_type},
                })

    def _ocr(self, image: bytes, media_type: str, *, timeout_seconds: float = 30.0) -> tuple[str, float | None]:
        if self.ocr_engine is not None:
            result = self.ocr_engine(image, media_type)
            if isinstance(result, str):
                return result, None
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
                confidence = result[1]
                if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
                    raise DocumentProcessingError("ocr_failed", "OCR confidence 형식이 올바르지 않습니다")
                return result[0], confidence
            if isinstance(result, dict) and isinstance(result.get("text"), str):
                confidence = result.get("confidence")
                if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
                    raise DocumentProcessingError("ocr_failed", "OCR confidence 형식이 올바르지 않습니다")
                return result["text"], confidence
            raise DocumentProcessingError("ocr_failed", "OCR 결과 형식이 올바르지 않습니다")
        executable = shutil.which("tesseract")
        if not executable:
            raise DocumentProcessingError("ocr_unavailable", "OCR 도구를 사용할 수 없습니다")
        env = {"PATH": str(Path(executable).parent), "LC_ALL": "C.UTF-8"}
        try:
            completed = subprocess.run(
                [executable, "stdin", "stdout", "--dpi", "150"], input=image,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                timeout=timeout_seconds, check=False, env=env, preexec_fn=_resource_limiter(),
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentProcessingError("timeout", "OCR 시간이 제한을 초과했습니다") from exc
        if completed.returncode != 0:
            raise DocumentProcessingError("ocr_failed", "OCR을 수행할 수 없습니다")
        return completed.stdout.decode("utf-8", "replace").strip(), None


def process_document(
    content: bytes,
    media_type: str | None = None,
    options: ProcessorOptions | dict[str, Any] | None = None,
    *,
    ocr_engine: OCREngine | None = None,
    clamav_checker: ClamAVChecker | None = None,
) -> ProcessedDocument:
    """Convenience API.  It accepts bytes only and never accepts a path/URL."""
    return DocumentProcessor(ocr_engine=ocr_engine, clamav_checker=clamav_checker).process(content, media_type, options)


# Names used by worker adapters in early prototypes; aliases preserve one
# implementation and do not add another input surface.
process_bytes = process_document
extract_structure = process_document
