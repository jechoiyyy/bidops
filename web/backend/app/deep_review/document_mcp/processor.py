"""Bytes-first, quarantine-safe document processor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import SCHEMA, UPSTREAM_COMMIT, validate_structure
from .errors import DocumentProcessingError
from .hwpx import extractor_info
from .native import NativeRhwpProcessor
from .pdf import PdfPage, extract_pdf
from .safety import OutputBudget, ProcessorOptions, detect_media_type, enforce_input_limit, image_dimensions

OCRResult = str | tuple[str, float | None] | dict[str, Any]
OCREngine = Callable[[bytes, str], OCRResult]
ClamAVChecker = Callable[[bytes], bool | None]
_MAX_FONT_FILES = 4096
_MAX_FONT_FILE_BYTES = 64 * 1024 * 1024
_MAX_FONT_PATH_BYTES = 256 * 1024


def _file_sha256(path: str, *, max_bytes: int | None = None) -> str:
    """Fingerprint one trusted worker asset without exposing its bytes."""

    digest = hashlib.sha256()
    try:
        before = os.stat(path, follow_symlinks=True)
        if not os.path.isfile(path):
            raise OSError("asset is not a regular file")
        if max_bytes is not None and before.st_size > max_bytes:
            raise DocumentProcessingError("output_size_limit", "PDF renderer 자산 크기 제한을 초과했습니다", source_preserved=True)
        total = 0
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise DocumentProcessingError("output_size_limit", "PDF renderer 자산 크기 제한을 초과했습니다", source_preserved=True)
                digest.update(chunk)
        after = os.stat(path, follow_symlinks=True)
        if before.st_size != after.st_size or total != before.st_size:
            raise OSError("asset changed during fingerprint")
    except DocumentProcessingError:
        raise
    except OSError as error:
        raise DocumentProcessingError("converter_unavailable", "PDF renderer 자산을 확인할 수 없습니다", source_preserved=True) from error
    return digest.hexdigest()


def _font_manifest_sha256(options: ProcessorOptions, deadline: float | None) -> str:
    """Fingerprint installed font *bytes*, rather than fc-list labels/paths."""

    executable = shutil.which("fc-list")
    if not executable:
        raise DocumentProcessingError("converter_unavailable", "PDF 글꼴 manifest를 확인할 수 없습니다", source_preserved=True)
    try:
        timeout = float(options.timeout_seconds)
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise DocumentProcessingError("timeout", "PDF 글꼴 확인 시간이 제한을 초과했습니다", source_preserved=True)
        returncode, stdout, _stderr = _run_limited_subprocess(
            [executable, ":", "family", "file"],
            cwd=str(Path(executable).parent),
            env=_child_environment(executable),
            timeout=timeout,
            output_limit=256 * 1024,
            preexec_fn=_resource_limiter(options.max_output_bytes),
        )
    except _ChildTimeout as exc:
        raise DocumentProcessingError("timeout", "PDF 글꼴 확인 시간이 제한을 초과했습니다", source_preserved=True) from exc
    except _ChildOutputLimit as exc:
        raise DocumentProcessingError("output_size_limit", "PDF 글꼴 manifest 크기 제한을 초과했습니다", source_preserved=True) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise DocumentProcessingError("converter_unavailable", "PDF 글꼴 manifest를 확인할 수 없습니다", source_preserved=True) from exc
    if returncode != 0 or not stdout:
        raise DocumentProcessingError("converter_unavailable", "PDF 글꼴 manifest를 확인할 수 없습니다", source_preserved=True)
    try:
        raw_paths = {
            line.partition(":")[0].strip()
            for line in stdout.decode("utf-8", "strict").splitlines()
            if line.partition(":")[0].strip()
        }
    except UnicodeDecodeError as exc:
        raise DocumentProcessingError("converter_unavailable", "PDF 글꼴 manifest를 확인할 수 없습니다", source_preserved=True) from exc
    if not raw_paths or len(raw_paths) > _MAX_FONT_FILES:
        raise DocumentProcessingError("output_size_limit", "PDF 글꼴 manifest 크기 제한을 초과했습니다", source_preserved=True)
    records: list[dict[str, Any]] = []
    for raw_path in sorted(raw_paths):
        try:
            path = Path(raw_path).resolve(strict=True)
            stat_result = path.stat()
            if not path.is_file() or stat_result.st_size > _MAX_FONT_FILE_BYTES:
                raise OSError("invalid font file")
            records.append(
                {
                    "path": str(path),
                    "size": stat_result.st_size,
                    "sha256": _file_sha256(str(path), max_bytes=_MAX_FONT_FILE_BYTES),
                }
            )
        except DocumentProcessingError:
            raise
        except OSError as exc:
            raise DocumentProcessingError("converter_unavailable", "PDF 글꼴 manifest를 확인할 수 없습니다", source_preserved=True) from exc
    manifest = json.dumps(records, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(manifest) > _MAX_FONT_PATH_BYTES:
        raise DocumentProcessingError("output_size_limit", "PDF 글꼴 manifest 크기 제한을 초과했습니다", source_preserved=True)
    return hashlib.sha256(manifest).hexdigest()


def _source_pdf_metadata(parsed_pages: list[PdfPage], extractor_name: str) -> dict[str, Any]:
    """Describe a byte-preserved PDF's actual bounded text path.

    This is deliberately separate from native renderer provenance.  A source
    PDF is not re-rendered and therefore has no generated font asset; the
    processor and the text extractor binaries still need stable fingerprints
    so a sidecar produced by a different parser cannot look equivalent.
    """

    processor_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    poppler: dict[str, str] | None = None
    if extractor_name == "pdf-poppler-prepared":
        poppler = {}
        for name in ("pdfinfo", "pdftotext"):
            executable = shutil.which(name)
            if not executable:
                raise DocumentProcessingError("converter_unavailable", "PDF text extractor를 확인할 수 없습니다", source_preserved=True)
            poppler[name] = _file_sha256(str(Path(executable).resolve()))
    return {
        "schema": "bidops.pdf-text-provenance.v1",
        "processor_sha256": processor_digest,
        "text_extractor": {
            "name": extractor_name,
            "version": "1",
            "upstream_commit": None,
        },
        "poppler_binary_sha256": poppler,
    }


def _has_binary_text_controls(blocks: list[dict[str, Any]]) -> bool:
    """Reject PDF text that is actually a decoded font/binary stream.

    The small stdlib parser intentionally supports only portable PDF text.
    Complex CID/font streams can still contain tokens that look like ``Tj``;
    accepting their control-heavy bytes as text produces unusable evidence.
    """

    return any(
        any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text)
        for block in blocks
        if isinstance(block, dict) and isinstance((text := block.get("text")), str)
    )


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
        converted_pdf_bytes: bytes | None = None,
        pdf_metadata: dict[str, Any] | None = None,
        page_text: dict[str, Any] | None = None,
        page_dump: dict[str, Any] | None = None,
        hwpx_verify: dict[str, Any] | None = None,
        hwpx_bytes: bytes | None = None,
        para_page_map: dict[str, Any] | None = None,
        para_page_map_bytes: bytes | None = None,
        section_candidates: dict[str, Any] | None = None,
        section_candidates_bytes: bytes | None = None,
    ) -> None:
        super().__init__(payload)
        self.original_bytes = original_bytes
        self.converted_bytes = converted_bytes
        self.rendered_pages = rendered_pages or {}
        # These fields are intentionally outside the JSON structure contract.
        # The trusted persistence adapter may store the generated PDF and its
        # page metadata as an immutable snapshot; a model client only receives
        # ``dict(processed)``.
        self.converted_pdf_bytes = converted_pdf_bytes
        self.pdf_metadata = pdf_metadata or {}
        self.page_text = page_text or {}
        self.page_dump = page_dump or {}
        self.hwpx_verify = hwpx_verify
        self.hwpx_bytes = hwpx_bytes
        self.para_page_map = para_page_map or {}
        self.para_page_map_bytes = para_page_map_bytes
        self.section_candidates = section_candidates or {}
        self.section_candidates_bytes = section_candidates_bytes


class _ChildTimeout(RuntimeError):
    pass


class _ChildOutputLimit(RuntimeError):
    pass


def _resource_limiter(max_file_bytes: int) -> Callable[[], None] | None:
    if os.name != "posix":
        return None
    try:
        import resource
    except ImportError:
        return None

    def limit() -> None:
        def set_limit(kind: int, requested: int) -> None:
            _soft, hard = resource.getrlimit(kind)
            ceiling = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (ceiling, ceiling))

        set_limit(resource.RLIMIT_CPU, 60)
        # The cgroup/container remains the authoritative isolation boundary;
        # these child limits cap a compromised converter even in a direct
        # worker invocation.
        set_limit(resource.RLIMIT_AS, 32 * 1024 * 1024 * 1024)
        set_limit(resource.RLIMIT_DATA, 512 * 1024 * 1024)
        set_limit(resource.RLIMIT_FSIZE, max_file_bytes)
        set_limit(resource.RLIMIT_NOFILE, 256)
        set_limit(resource.RLIMIT_CORE, 0)

    return limit


def _child_environment(executable: str) -> dict[str, str]:
    """Build a minimal child environment with no credentials or proxy routes.

    OS-level network denial is supplied by the worker container/runtime (the
    documented deployment assumption is a network-disabled namespace). The
    processor additionally removes proxy and module-path configuration so a
    child cannot inherit an ambient outbound route or credential-bearing env.
    """
    environment = {
        "PATH": str(Path(executable).parent),
        "LC_ALL": "C.UTF-8",
        "NO_PROXY": "*",
        "no_proxy": "*",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
    }
    return environment


def _terminate_child(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows has no process-group signal equivalent here
            process.kill()
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=1)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _run_limited_subprocess(
    command: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout: float,
    output_limit: int,
    input_bytes: bytes | None = None,
    preexec_fn: Callable[[], None] | None = None,
) -> tuple[int, bytes, bytes]:
    """Run a child while bounding both pipes before completion."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        start_new_session=os.name == "posix",
        preexec_fn=preexec_fn,
    )
    stdout = bytearray()
    stderr = bytearray()
    total_output = 0
    selector = selectors.DefaultSelector()
    streams: dict[int, bytearray] = {}
    for pipe, target in ((process.stdout, stdout), (process.stderr, stderr)):
        if pipe is not None:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
            streams[pipe.fileno()] = target

    feeder: threading.Thread | None = None
    if input_bytes is not None and process.stdin is not None:
        stdin = process.stdin

        def feed() -> None:
            try:
                stdin.write(input_bytes)
                stdin.close()
            except (BrokenPipeError, OSError):
                try:
                    stdin.close()
                except OSError:
                    pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()

    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None or selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_child(process)
                raise _ChildTimeout
            if not selector.get_map():
                time.sleep(min(remaining, 0.01))
                continue
            for key, _mask in selector.select(min(remaining, 0.05)):
                pipe = key.fileobj
                try:
                    chunk = os.read(pipe.fileno(), 64 * 1024)
                except OSError:
                    chunk = b""
                if not chunk:
                    try:
                        selector.unregister(pipe)
                    except (KeyError, ValueError):
                        pass
                    pipe.close()
                    continue
                target = streams[pipe.fileno()]
                if total_output + len(chunk) > output_limit:
                    _terminate_child(process)
                    raise _ChildOutputLimit
                target.extend(chunk)
                total_output += len(chunk)
        return process.wait(timeout=max(0.0, deadline - time.monotonic())), bytes(stdout), bytes(stderr)
    finally:
        try:
            selector.close()
        except OSError:
            pass
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
        if feeder is not None:
            feeder.join(timeout=0.2)


class DocumentProcessor:
    """Process HWP/HWPX/PDF/image bytes into a constrained structure JSON."""

    def __init__(
        self,
        *,
        ocr_engine: OCREngine | None = None,
        clamav_checker: ClamAVChecker | None = None,
        rhwp_executable: str | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.clamav_checker = clamav_checker
        # The vendored native CLI is selected by the worker image, never by a
        # scratch request.  The explicit constructor argument is a test seam.
        self.rhwp_executable = rhwp_executable or str(
            Path(__file__).with_name("vendor") / "rhwp" / "bin" / "rhwp"
        )

    def process(
        self,
        content: bytes,
        media_type: str | None = None,
        options: ProcessorOptions | dict[str, Any] | None = None,
    ) -> ProcessedDocument:
        """Return the structure contract for one document.

        HWP/HWPX always run the native rhwp path, where ``prepare_pdf`` only
        decides whether the PDF, page text, and para-page map are produced on
        top of that structure; ``application/pdf`` keeps its existing meaning.
        """

        opts = ProcessorOptions.from_mapping(options)
        deadline = time.monotonic() + float(opts.timeout_seconds)
        original = enforce_input_limit(content)
        detected = detect_media_type(original, media_type)
        source_hash = hashlib.sha256(original).hexdigest()
        converted: bytes | None = None
        converted_pdf: bytes | None = None
        pdf_metadata: dict[str, Any] = {}
        rendered: dict[int, bytes] = {}
        warnings: list[str] = []
        page_text: dict[str, Any] = {}
        page_dump: dict[str, Any] = {}
        hwpx_verify: dict[str, Any] | None = None
        canonical_hwpx: bytes | None = None
        para_page_map: dict[str, Any] = {}
        para_page_map_bytes: bytes | None = None
        section_candidates: dict[str, Any] = {}
        section_candidates_bytes: bytes | None = None
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
                native = self._process_native(original, detected, opts, deadline)
            except DocumentProcessingError as exc:
                exc.source_preserved = True
                raise
            pages, blocks = native["pages"], native["blocks"]
            warnings.extend(native["warnings"])
            converted = native["converted"]
            converted_pdf = native["pdf"]
            pdf_metadata = native["pdf_metadata"]
            page_text = native["page_text"]
            page_dump = native["page_dump"]
            para_page_map = native["para_page_map"]
            para_page_map_bytes = native["para_page_map_bytes"]
            section_candidates = native["section_candidates"]
            section_candidates_bytes = native["section_candidates_bytes"]
            hwpx_verify = native["verify"]
            canonical_hwpx = converted
            extractor = {"name": "hwp-rhwp-native-hwpx", "version": "1", "upstream_commit": UPSTREAM_COMMIT}
        elif detected == "application/hwp+zip":
            # The native adapter reuses the existing archive traversal, link,
            # member, ratio, and decompressed-size boundary before any child
            # process reads the document.
            try:
                native = self._process_native(original, detected, opts, deadline)
            except DocumentProcessingError as exc:
                exc.source_preserved = True
                raise
            pages, blocks = native["pages"], native["blocks"]
            warnings.extend(native["warnings"])
            converted_pdf = native["pdf"]
            pdf_metadata = native["pdf_metadata"]
            page_text = native["page_text"]
            page_dump = native["page_dump"]
            para_page_map = native["para_page_map"]
            para_page_map_bytes = native["para_page_map_bytes"]
            section_candidates = native["section_candidates"]
            section_candidates_bytes = native["section_candidates_bytes"]
            canonical_hwpx = original
            extractor = extractor_info()
        elif detected == "application/pdf":
            try:
                if opts.prepare_pdf:
                    # The stdlib reader can decode a few font glyph bytes as
                    # apparently valid Unicode.  That is unsafe for the v4
                    # input cut: a non-empty but meaningless result prevents
                    # the bounded Poppler fallback from running.  Prepared
                    # PDF inputs therefore use the same bounded Poppler text
                    # source as a generated native PDF.  The legacy path below
                    # remains unchanged.
                    # Run the existing bounded parser first for structural,
                    # page, and object-count limits.  Its text is deliberately
                    # discarded below, but a limit failure must never become
                    # a Poppler fallback success.
                    stdlib_result: tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[PdfPage]] | None = None
                    try:
                        stdlib_pages, stdlib_blocks, stdlib_warnings, stdlib_parsed = extract_pdf(original, opts)
                        if _has_binary_text_controls(stdlib_blocks):
                            raise DocumentProcessingError("malformed_pdf", "PDF text stream이 portable text가 아닙니다")
                        stdlib_result = (stdlib_pages, stdlib_blocks, stdlib_warnings, stdlib_parsed)
                    except DocumentProcessingError as exc:
                        if exc.code != "malformed_pdf":
                            raise
                    try:
                        pages, blocks, child_warnings, parsed_pages = self._extract_pdf_poppler(
                            original, opts, deadline=deadline,
                        )
                        child_warnings.append("pdf_poppler_text_fallback")
                        pdf_extractor = "pdf-poppler-prepared"
                    except DocumentProcessingError:
                        # A tiny, structurally valid PDF may be accepted by
                        # the bounded stdlib reader while Poppler rejects its
                        # intentionally minimal stream.  Preserve the v1
                        # contract for that case only when the bounded reader
                        # produced portable text; complex prepared PDFs still
                        # use Poppler as the canonical text source.
                        if stdlib_result is None:
                            raise
                        pages, blocks, child_warnings, parsed_pages = stdlib_result
                        child_warnings = list(child_warnings)
                        child_warnings.append("pdf_stdlib_prepared_fallback")
                        pdf_extractor = "pdf-stdlib-prepared"
                else:
                    pages, blocks, child_warnings, parsed_pages = extract_pdf(original, opts)
                    if _has_binary_text_controls(blocks):
                        raise DocumentProcessingError("malformed_pdf", "PDF text stream이 portable text가 아닙니다")
                    pdf_extractor = "pdf-stdlib"
            except DocumentProcessingError as exc:
                if exc.code != "malformed_pdf" or opts.prepare_pdf:
                    raise
                pages, blocks, child_warnings, parsed_pages = self._extract_pdf_poppler(original, opts)
                pdf_extractor = "pdf-poppler-fallback"
                child_warnings.append("pdf_stdlib_text_fallback")
            warnings.extend(child_warnings)
            extractor = {"name": pdf_extractor, "version": "1", "upstream_commit": None}
            if opts.prepare_pdf:
                pdf_metadata = {
                    "schema": "bidops.pdf-snapshot.v1",
                    "renderer": "source-pdf",
                    "renderer_version": "1",
                    "rerendered": False,
                    "processor_provenance": _source_pdf_metadata(parsed_pages, pdf_extractor),
                    "font_provenance": None,
                    "page_count": len(parsed_pages),
                    "pages": [
                        {
                            "number": page.number,
                            "width": page.width,
                            "height": page.height,
                            "text_sha256": hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                        }
                        for page in parsed_pages
                    ],
                }
            render_targets = parsed_pages if opts.render_pages else [page for page in parsed_pages if not page.text]
            rendered_budget = OutputBudget(opts.max_output_bytes)
            if render_targets:
                for page in render_targets:
                    try:
                        rendered_page = self._render_pdf_page(original, page.number, opts)
                    except DocumentProcessingError as exc:
                        if exc.code == "renderer_unavailable":
                            warnings.append("page_render_unavailable")
                            if not page.text:
                                warnings.append("ocr_unavailable")
                            warnings.append("needs_review")
                            continue
                        raise
                    rendered_budget.consume(len(rendered_page))
                    rendered[page.number] = rendered_page
                    for item in pages:
                        if item["number"] == page.number:
                            item["image_content_object_id"] = str(uuid.uuid4())
                            break
                if opts.ocr and rendered:
                    self._ocr_pages(
                        rendered,
                        pages,
                        blocks,
                        warnings,
                        page_numbers={page.number for page in parsed_pages if not page.text},
                        output_limit=opts.max_output_bytes,
                        timeout_seconds=opts.timeout_seconds,
                        text_budget=OutputBudget(opts.max_output_bytes),
                    )
        elif detected.startswith("image/"):
            width, height = image_dimensions(original, detected)
            if width <= 0 or height <= 0 or width > 100_000 or height > 100_000 or width * height > 100_000_000:
                raise DocumentProcessingError("image_size_limit", "이미지 해상도 제한을 초과했습니다")
            if len(original) > opts.max_output_bytes:
                raise DocumentProcessingError("output_size_limit", "이미지 page render 결과 크기 제한을 초과했습니다")
            pages = [{"number": 1, "width": float(width), "height": float(height), "image_content_object_id": str(uuid.uuid4())}]
            blocks = []
            extractor = {"name": "image-ocr", "version": "1", "upstream_commit": None}
            rendered_budget = OutputBudget(opts.max_output_bytes)
            rendered_budget.consume(len(original))
            rendered[1] = original
            if opts.ocr:
                self._ocr_pages(
                    rendered,
                    pages,
                    blocks,
                    warnings,
                    image_media_type=detected,
                    output_limit=opts.max_output_bytes,
                    timeout_seconds=opts.timeout_seconds,
                    text_budget=OutputBudget(opts.max_output_bytes),
                )
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
        validate_structure(
            payload,
            max_output_bytes=opts.max_output_bytes,
            max_pages=opts.max_pages,
            max_blocks=opts.max_blocks,
        )
        return ProcessedDocument(
            payload,
            original_bytes=original,
            converted_bytes=converted,
            rendered_pages=rendered,
            converted_pdf_bytes=converted_pdf,
            pdf_metadata=pdf_metadata,
            page_text=page_text,
            page_dump=page_dump,
            hwpx_verify=hwpx_verify,
            hwpx_bytes=canonical_hwpx,
            para_page_map=para_page_map,
            para_page_map_bytes=para_page_map_bytes,
            section_candidates=section_candidates,
            section_candidates_bytes=section_candidates_bytes,
        )

    def _process_native(
        self,
        original: bytes,
        media_type: str,
        options: ProcessorOptions,
        deadline: float,
    ) -> dict[str, Any]:
        """Run the vendored native rhwp CLI; there is no other renderer."""

        adapter = NativeRhwpProcessor(
            self.rhwp_executable,
            run=_run_limited_subprocess,
            limiter=_resource_limiter,
            child_environment=_child_environment,
            timeout_error=_ChildTimeout,
            output_error=_ChildOutputLimit,
            font_manifest=_font_manifest_sha256,
        )
        return adapter.process(original, media_type, options, deadline)

    @staticmethod
    def _remaining_timeout(deadline: float | None, options: ProcessorOptions, message: str) -> float:
        if deadline is None:
            return float(options.timeout_seconds)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DocumentProcessingError("timeout", message, source_preserved=True)
        return min(float(options.timeout_seconds), remaining)

    def _extract_pdf_poppler(
        self,
        original: bytes,
        options: ProcessorOptions,
        *,
        deadline: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[PdfPage]]:
        """Parse valid complex PDFs with bounded Poppler subprocesses.

        This fallback runs only in the credential-free, network-disabled
        document worker.  It is intentionally limited to metadata and UTF-8
        text extraction; rendering/OCR continues through the existing bounded
        path below.
        """

        info_executable = shutil.which("pdfinfo")
        text_executable = shutil.which("pdftotext")
        if not info_executable or not text_executable:
            raise DocumentProcessingError("malformed_pdf", "PDF object를 해석할 수 없습니다")
        with tempfile.TemporaryDirectory(prefix="bidops-pdf-") as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(original)
            try:
                info_code, info_stdout, _info_stderr = _run_limited_subprocess(
                    [info_executable, str(source)], cwd=tmp,
                    env=_child_environment(info_executable),
                    timeout=self._remaining_timeout(deadline, options, "PDF 정보 확인 시간이 제한을 초과했습니다"), output_limit=64 * 1024,
                    preexec_fn=_resource_limiter(options.max_output_bytes),
                )
                text_code, text_stdout, _text_stderr = _run_limited_subprocess(
                    [text_executable, "-layout", "-enc", "UTF-8", str(source), "-"],
                    cwd=tmp, env=_child_environment(text_executable),
                    timeout=self._remaining_timeout(deadline, options, "PDF text 확인 시간이 제한을 초과했습니다"), output_limit=options.max_output_bytes,
                    preexec_fn=_resource_limiter(options.max_output_bytes),
                )
            except _ChildTimeout as exc:
                raise DocumentProcessingError("timeout", "PDF 처리 시간이 제한을 초과했습니다", source_preserved=True) from exc
            except _ChildOutputLimit as exc:
                raise DocumentProcessingError("output_size_limit", "PDF 처리 결과 크기 제한을 초과했습니다", source_preserved=True) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise DocumentProcessingError("malformed_pdf", "PDF object를 해석할 수 없습니다") from exc
        if info_code != 0 or text_code != 0:
            raise DocumentProcessingError("malformed_pdf", "PDF object를 해석할 수 없습니다")
        try:
            info = info_stdout.decode("utf-8", "strict")
            text = text_stdout.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError("malformed_pdf", "PDF text encoding이 올바르지 않습니다") from exc
        encrypted = re.search(r"(?mi)^Encrypted:\s*(\S+)", info)
        if encrypted and encrypted.group(1).casefold() not in {"no", "false"}:
            raise DocumentProcessingError("encrypted_pdf", "암호화된 PDF는 처리할 수 없습니다")
        page_match = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", info)
        if page_match is None:
            raise DocumentProcessingError("malformed_pdf", "PDF page 수를 확인할 수 없습니다")
        page_count = int(page_match.group(1))
        if not 1 <= page_count <= min(options.max_pdf_pages, options.max_pages):
            raise DocumentProcessingError("pdf_page_limit", "PDF page 수 제한을 초과했습니다")
        size_match = re.search(r"(?mi)^Page size:\s*([0-9.]+)\s+x\s+([0-9.]+)\s+pts", info)
        width = float(size_match.group(1)) if size_match else 595.0
        height = float(size_match.group(2)) if size_match else 842.0
        if width <= 0 or height <= 0 or width * height > 100_000_000:
            raise DocumentProcessingError("pdf_page_limit", "PDF page 해상도 제한을 초과했습니다")
        page_texts = text.split("\f")
        if page_texts and not page_texts[-1].strip():
            page_texts.pop()
        page_texts.extend([""] * max(0, page_count - len(page_texts)))
        pages: list[dict[str, Any]] = []
        blocks: list[dict[str, Any]] = []
        parsed: list[PdfPage] = []
        budget = OutputBudget(options.max_output_bytes)
        for page_number in range(1, page_count + 1):
            page_text = page_texts[page_number - 1].strip() if page_number <= len(page_texts) else ""
            budget.consume_text(page_text)
            pages.append({"number": page_number, "width": width, "height": height, "image_content_object_id": None})
            if page_text:
                blocks.append({
                    "block_key": f"page-{page_number}-text",
                    "parent_block_key": None, "type": "text", "page": page_number,
                    "bbox": [0.0, 0.0, width, height], "text": page_text,
                    "confidence": 1.0, "attributes": {"source": "pdf-poppler-text"},
                })
            parsed.append(PdfPage(page_number, width, height, page_text, b""))
        return pages, blocks, ["pdf_poppler_fallback"], parsed

    def _render_pdf_page(self, original: bytes, page: int, options: ProcessorOptions) -> bytes:
        executable = shutil.which("pdftoppm")
        if not executable:
            raise DocumentProcessingError("renderer_unavailable", "PDF page render 도구를 사용할 수 없습니다")
        with tempfile.TemporaryDirectory(prefix="bidops-render-") as tmp:
            source = Path(tmp) / "source.pdf"
            prefix = Path(tmp) / "page"
            source.write_bytes(original)
            env = _child_environment(executable)
            try:
                returncode, _stdout, _stderr = _run_limited_subprocess(
                    [executable, "-f", str(page), "-l", str(page), "-png", "-singlefile", str(source), str(prefix)],
                    cwd=tmp,
                    env=env,
                    timeout=options.timeout_seconds,
                    output_limit=options.max_output_bytes,
                    preexec_fn=_resource_limiter(options.max_output_bytes),
                )
            except _ChildTimeout as exc:
                raise DocumentProcessingError("timeout", "page render 시간이 제한을 초과했습니다") from exc
            except _ChildOutputLimit as exc:
                raise DocumentProcessingError("output_size_limit", "page render 결과 크기 제한을 초과했습니다") from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise DocumentProcessingError("renderer_unavailable", "PDF page render 도구를 사용할 수 없습니다") from exc
            if returncode != 0:
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
        page_numbers: set[int] | None = None,
        output_limit: int = 20 * 1024 * 1024,
        timeout_seconds: float = 30.0,
        text_budget: OutputBudget | None = None,
    ) -> None:
        if text_budget is None:
            text_budget = OutputBudget(output_limit)
        for page_number, image in sorted(rendered.items()):
            if page_numbers is not None and page_number not in page_numbers:
                continue
            try:
                text, confidence = self._ocr(
                    image,
                    image_media_type,
                    output_limit=output_limit,
                    timeout_seconds=timeout_seconds,
                )
            except DocumentProcessingError as exc:
                if exc.code == "ocr_unavailable":
                    warnings.append("ocr_unavailable")
                    warnings.append("needs_review")
                    continue
                raise
            if text:
                page = next((item for item in pages if item["number"] == page_number), None)
                bbox = [0.0, 0.0, float(page["width"]), float(page["height"])] if page else None
                text_budget.consume_text(text)
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

    def _ocr(
        self,
        image: bytes,
        media_type: str,
        *,
        output_limit: int = 20 * 1024 * 1024,
        timeout_seconds: float = 30.0,
    ) -> tuple[str, float | None]:
        if self.ocr_engine is not None:
            result = self.ocr_engine(image, media_type)
            if isinstance(result, str):
                if len(result.encode("utf-8")) > output_limit:
                    raise DocumentProcessingError("output_size_limit", "OCR 결과 크기 제한을 초과했습니다")
                return result, None
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
                if len(result[0].encode("utf-8")) > output_limit:
                    raise DocumentProcessingError("output_size_limit", "OCR 결과 크기 제한을 초과했습니다")
                confidence = result[1]
                if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
                    raise DocumentProcessingError("ocr_failed", "OCR confidence 형식이 올바르지 않습니다")
                return result[0], confidence
            if isinstance(result, dict) and isinstance(result.get("text"), str):
                if len(result["text"].encode("utf-8")) > output_limit:
                    raise DocumentProcessingError("output_size_limit", "OCR 결과 크기 제한을 초과했습니다")
                confidence = result.get("confidence")
                if confidence is not None and (not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
                    raise DocumentProcessingError("ocr_failed", "OCR confidence 형식이 올바르지 않습니다")
                return result["text"], confidence
            raise DocumentProcessingError("ocr_failed", "OCR 결과 형식이 올바르지 않습니다")
        executable = shutil.which("tesseract")
        if not executable:
            raise DocumentProcessingError("ocr_unavailable", "OCR 도구를 사용할 수 없습니다")
        env = _child_environment(executable)
        try:
            returncode, stdout, _stderr = _run_limited_subprocess(
                [executable, "stdin", "stdout", "--dpi", "150"],
                input_bytes=image,
                cwd=tempfile.gettempdir(),
                env=env,
                timeout=timeout_seconds,
                output_limit=output_limit,
                preexec_fn=_resource_limiter(output_limit),
            )
        except _ChildTimeout as exc:
            raise DocumentProcessingError("timeout", "OCR 시간이 제한을 초과했습니다") from exc
        except _ChildOutputLimit as exc:
            raise DocumentProcessingError("output_size_limit", "OCR 결과 크기 제한을 초과했습니다") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentProcessingError("ocr_unavailable", "OCR 도구를 사용할 수 없습니다") from exc
        if returncode != 0:
            raise DocumentProcessingError("ocr_failed", "OCR을 수행할 수 없습니다")
        return stdout.decode("utf-8", "replace").strip(), None


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
