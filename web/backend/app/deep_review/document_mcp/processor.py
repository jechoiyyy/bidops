"""Bytes-first, quarantine-safe document processor."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import selectors
import signal
import secrets
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
from .hwpx import extract_hwpx, extractor_info
from .pdf import PdfPage, extract_pdf
from .safety import OutputBudget, ProcessorOptions, detect_media_type, enforce_input_limit, image_dimensions, validate_zip

OCRResult = str | tuple[str, float | None] | dict[str, Any]
OCREngine = Callable[[bytes, str], OCRResult]
ClamAVChecker = Callable[[bytes], bool | None]
_CANVAS_PRINT_RECEIPT = "bidops-hwp-canvas-render-complete-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FONT_FILES = 4096
_MAX_FONT_FILE_BYTES = 64 * 1024 * 1024
_MAX_FONT_PATH_BYTES = 256 * 1024
_DEBIAN_CHROMIUM_BINARY = Path("/usr/lib/chromium/chromium")


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


def _resolve_chromium_binary(executable: str) -> str:
    """Resolve a launcher such as Debian's ``/usr/bin/chromium`` script.

    The launcher is used to start the child, but its shell-script bytes do not
    identify the Chromium binary that determines print output.  Fail closed
    when a trusted binary cannot be located rather than recording the wrapper
    as a renderer fingerprint.
    """

    def is_elf(path: Path) -> bool:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"

    try:
        launcher = Path(executable).resolve(strict=True)
        if is_elf(launcher):
            return str(launcher)
        # Debian's trusted /usr/bin/chromium launcher always delegates to
        # this package-owned binary.  Do not parse arbitrary shell scripts or
        # search request-controlled paths for another ELF file.
        if launcher.name != "chromium":
            raise OSError("unsupported Chromium launcher")
        binary = _DEBIAN_CHROMIUM_BINARY.resolve(strict=True)
        if binary == launcher or not os.access(binary, os.X_OK) or not is_elf(binary):
            raise OSError("Chromium binary is not an ELF executable")
        return str(binary)
    except OSError as error:
        raise DocumentProcessingError("converter_unavailable", "Chromium 실제 binary를 확인할 수 없습니다", source_preserved=True) from error


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


def _worker_provenance(
    *,
    runtime: str,
    wasm: bytes,
    adapter: bytes,
    processor_source: bytes,
    chromium_executable: str,
    options: ProcessorOptions,
    deadline: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return renderer/font fingerprints produced inside the document worker."""

    chromium_binary = _resolve_chromium_binary(chromium_executable)
    chromium_digest = _file_sha256(chromium_binary)
    renderer_asset_digest = hashlib.sha256(
        runtime.encode("utf-8") + b"\0" + wasm + b"\0" + adapter
    ).hexdigest()
    processor_digest = hashlib.sha256(processor_source).hexdigest()
    # The runtime fingerprint includes the trusted adapter and print/CSS
    # implementation, so a code-only change cannot reuse an old snapshot.
    runtime_digest = hashlib.sha256(
        runtime.encode("utf-8")
        + b"\0"
        + wasm
        + b"\0"
        + adapter
        + b"\0"
        + processor_source
        + b"\0"
        + chromium_digest.encode("ascii")
    ).hexdigest()
    font_digest = _font_manifest_sha256(options, deadline)
    configured_image_digest = os.environ.get("BIDOPS_DOCUMENT_WORKER_IMAGE_DIGEST", "").strip().lower()
    if configured_image_digest and not _SHA256.fullmatch(configured_image_digest):
        raise DocumentProcessingError("converter_unavailable", "document-worker image digest 선언을 확인할 수 없습니다", source_preserved=True)
    if not configured_image_digest:
        configured_image_digest = None
        image_source = "undeclared"
    else:
        image_source = "environment"
    return (
        {
            "worker_image_digest": configured_image_digest,
            "worker_image_digest_source": image_source,
            "runtime_sha256": runtime_digest,
            "renderer_asset_sha256": renderer_asset_digest,
            "processor_sha256": processor_digest,
            "chromium_sha256": chromium_digest,
            "renderer": "rhwp-canvas-chromium",
        },
        {
            "worker_image_digest": configured_image_digest,
            "font_manifest_sha256": font_digest,
            "font_family": "Noto Sans CJK KR",
        },
    )


def _source_pdf_metadata(parsed_pages: list[PdfPage], extractor_name: str) -> dict[str, Any]:
    """Describe a byte-preserved PDF's actual bounded text path.

    This is deliberately separate from Canvas renderer provenance.  A source
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


def _build_canvas_print_html(
    *,
    source: bytes,
    runtime: str,
    wasm: bytes,
    pages: list[dict[str, Any]],
    max_html_bytes: int,
) -> str:
    """Build the request-local Canvas print sheet from trusted renderer assets.

    The only document-derived values placed in the module are base64 bytes.
    Text returned by rhwp is assigned with ``textContent`` in the browser and
    is never parsed as HTML or CSS.  The Canvas is the visual layer; the
    renderer text runs provide a transparent, selectable PDF text layer at the
    same coordinates.
    """

    if not pages or not isinstance(runtime, str) or "</script" in runtime.casefold():
        raise DocumentProcessingError("conversion_required", "HWP PDF print HTML을 만들 수 없습니다", source_preserved=True)
    if not isinstance(wasm, bytes) or not wasm:
        raise DocumentProcessingError("conversion_required", "HWP PDF runtime을 확인할 수 없습니다", source_preserved=True)
    first_width = float(pages[0]["width"])
    first_height = float(pages[0]["height"])
    if not (
        math.isfinite(first_width)
        and math.isfinite(first_height)
        and first_width > 0
        and first_height > 0
    ):
        raise DocumentProcessingError("conversion_required", "HWP PDF page 크기를 확인할 수 없습니다", source_preserved=True)
    if any(
        float(page["width"]) != first_width or float(page["height"]) != first_height
        for page in pages[1:]
    ):
        raise DocumentProcessingError(
            "pdf_page_mismatch",
            "문서 page 크기가 서로 달라 PDF 대응을 확인할 수 없습니다",
            source_preserved=True,
        )

    nonce = secrets.token_urlsafe(24)
    source_b64 = base64.b64encode(source).decode("ascii")
    wasm_b64 = base64.b64encode(wasm).decode("ascii")
    page_config = json.dumps(pages, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    # This is trusted vendored JavaScript.  It is deliberately kept as an
    # inline module so Chromium cannot resolve a file/import URL from input.
    module = f"""
const maxHtmlBytes = {int(max_html_bytes)};
const renderScale = 1;
const expectedPages = {page_config};
const sourceBase64 = {json.dumps(source_b64)};
const wasmBase64 = {json.dumps(wasm_b64)};

function decodeBase64(value) {{
  const binary = atob(value);
  const result = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) result[index] = binary.charCodeAt(index);
  return result;
}}

function finiteNumber(value, label, minimum, maximum) {{
  const number = Number(value);
  if (!Number.isFinite(number) || number < minimum || number > maximum) throw new Error(label);
  return number;
}}

function safeFontFamily(value) {{
  const family = String(value ?? "").replace(/[^\\p{{L}}\\p{{N}} _-]/gu, "").trim();
  return family ? `"${{family}}","Noto Sans CJK KR",sans-serif` : `"Noto Sans CJK KR",sans-serif`;
}}

const styleRules = [];
const pageStyle = `
@page {{ size: {first_width}px {first_height}px; margin: 0; }}
html, body {{ margin: 0; padding: 0; width: {first_width}px; background: #fff; }}
.page {{ position: relative; width: {first_width}px; height: {first_height}px; overflow: hidden; background: #fff; break-after: page; page-break-after: always; }}
.page:last-child {{ break-after: auto; page-break-after: auto; }}
.paint {{ position: absolute; left: 0; top: 0; display: block; width: {first_width}px; height: {first_height}px; background: #fff; }}
.text-layer {{ position: absolute; left: 0; top: 0; width: {first_width}px; height: {first_height}px; overflow: hidden; pointer-events: none; }}
.text-run {{ position: absolute; display: block; overflow: visible; white-space: pre; color: transparent; background: transparent; transform-origin: left top; pointer-events: none; }}
`;

globalThis.measureTextWidth = (font, text) => {{
  const measureCanvas = globalThis.__bidopsMeasureCanvas || document.createElement("canvas");
  const measureContext = measureCanvas.getContext("2d");
  if (!measureContext) throw new Error("canvas measurement is unavailable");
  globalThis.__bidopsMeasureCanvas = measureCanvas;
  measureContext.font = String(font ?? "");
  return measureContext.measureText(String(text ?? "")).width;
}};

const sourceBytes = decodeBase64(sourceBase64);
const wasmBytes = decodeBase64(wasmBase64);
{runtime}
initSync(wasmBytes);
const documentModel = new HwpDocument(sourceBytes);
try {{
  const pageCount = documentModel.pageCount();
  if (pageCount !== expectedPages.length || pageCount < 1) throw new Error("page count mismatch");
  const geometries = [];
  for (let index = 0; index < pageCount; index += 1) {{
    const info = JSON.parse(documentModel.getPageInfo(index));
    const width = finiteNumber(info.width, "invalid page width", 1, 10000);
    const height = finiteNumber(info.height, "invalid page height", 1, 10000);
    const expected = expectedPages[index];
    if (width !== Number(expected.width) || height !== Number(expected.height)) throw new Error("page geometry mismatch");
    geometries.push({{ width, height }});
  }}

  const root = document.body;
  for (let index = 0; index < pageCount; index += 1) {{
    const page = document.createElement("section");
    page.className = "page";
    page.dataset.page = String(index + 1);
    const geometry = geometries[index];
    const canvas = document.createElement("canvas");
    canvas.className = "paint";
    canvas.width = Math.round(geometry.width * renderScale);
    canvas.height = Math.round(geometry.height * renderScale);
    page.appendChild(canvas);
    const layer = document.createElement("div");
    layer.className = "text-layer";
    page.appendChild(layer);
    root.appendChild(page);

    // rhwp's WASM keeps a temporary text-layout borrow after painting; the
    // layout call must immediately follow each successful canvas render.
    documentModel.renderPageToCanvas(index, canvas, renderScale);
    const layoutRaw = documentModel.getPageTextLayout(index);
    if (new TextEncoder().encode(layoutRaw).byteLength > maxHtmlBytes) throw new Error("text layout size limit");
    const layout = JSON.parse(layoutRaw);
    const runs = layout && Array.isArray(layout.runs)
      ? layout.runs
      : layout && layout.layout && Array.isArray(layout.layout.runs)
        ? layout.layout.runs
        : null;
    if (!Array.isArray(runs)) throw new Error("invalid text layout");
    for (let runIndex = 0; runIndex < runs.length; runIndex += 1) {{
      const run = runs[runIndex];
      if (!run || typeof run.text !== "string") throw new Error("invalid text run");
      const x = finiteNumber(run.x, "invalid text x", -geometry.width * 2, geometry.width * 3);
      const y = finiteNumber(run.y, "invalid text y", -geometry.height * 2, geometry.height * 3);
      const width = finiteNumber(run.w, "invalid text width", 0, geometry.width * 3);
      const height = finiteNumber(run.h, "invalid text height", 0, geometry.height * 3);
      const fontSize = finiteNumber(run.fontSize, "invalid text font size", 1, 512);
      const ratio = finiteNumber(run.ratio ?? 1, "invalid text ratio", 0.01, 20);
      const letterSpacing = finiteNumber(run.letterSpacing ?? 0, "invalid text spacing", -100, 100);
      const span = document.createElement("span");
      span.className = `text-run run-${{index}}-${{runIndex}}`;
      // Input text remains data, never markup or an executable URL.
      span.textContent = run.text;
      layer.appendChild(span);
      styleRules.push(`.run-${{index}}-${{runIndex}}{{left:${{x}}px;top:${{y}}px;width:${{width}}px;height:${{height}}px;font-family:${{safeFontFamily(run.fontFamily)}};font-size:${{fontSize}}px;line-height:${{height || fontSize}}px;font-weight:${{run.bold ? 700 : 400}};font-style:${{run.italic ? "italic" : "normal"}};letter-spacing:${{letterSpacing}}px;transform:scaleX(${{ratio}});}}`);
    }}
  }}
  const style = document.createElement("style");
  style.setAttribute("nonce", {json.dumps(nonce)});
  style.textContent = pageStyle + styleRules.join("\\n");
  document.head.appendChild(style);
  if (new TextEncoder().encode(document.documentElement.outerHTML).byteLength > maxHtmlBytes) throw new Error("print HTML size limit");
  // Chromium copies document.title into the PDF metadata.  Set this only
  // after every page, run validation, and HTML budget check has completed;
  // Python verifies the fixed receipt before accepting the PDF.
  document.title = {_CANVAS_PRINT_RECEIPT!r};
  document.documentElement.dataset.renderComplete = "true";
}} finally {{
  documentModel.free();
}}
"""
    html_document = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\""
        f"default-src 'none'; script-src 'nonce-{nonce}' 'wasm-unsafe-eval'; "
        f"style-src 'nonce-{nonce}'; img-src data:; font-src data:; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-src 'none'; connect-src 'none'; "
        f"worker-src 'none'\"><style nonce=\"{nonce}\">"
        "html,body{margin:0;padding:0;background:#fff}</style></head><body>"
        f"<script type=\"module\" nonce=\"{nonce}\">{module}</script>"
        "</body></html>"
    )
    if len(html_document.encode("utf-8")) > max_html_bytes:
        raise DocumentProcessingError("output_size_limit", "HWP PDF print HTML 크기 제한을 초과했습니다", source_preserved=True)
    return html_document


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


class _ChildTimeout(RuntimeError):
    pass


class _ChildOutputLimit(RuntimeError):
    pass


def _resource_limiter(
    max_file_bytes: int,
    *,
    address_space_bytes: int | None = 32 * 1024 * 1024 * 1024,
    data_bytes: int | None = 512 * 1024 * 1024,
) -> Callable[[], None] | None:
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
        # worker invocation. RLIMIT_AS is explicit for the Node/WASM
        # converter, but Chromium is allowed to reserve a larger virtual
        # address space and receives ``address_space_bytes=None`` below.
        # Chromium otherwise aborts before headless printing starts when a
        # finite address-space limit is applied.
        if address_space_bytes is not None:
            set_limit(resource.RLIMIT_AS, address_space_bytes)
        if data_bytes is not None:
            set_limit(resource.RLIMIT_DATA, data_bytes)
        set_limit(resource.RLIMIT_FSIZE, max_file_bytes)
        # Chromium needs a small process tree and shared-memory descriptor set;
        # a very low descriptor limit causes an abort before headless printing.
        set_limit(resource.RLIMIT_NOFILE, 256)
        set_limit(resource.RLIMIT_CORE, 0)

    return limit


def _child_environment(executable: str, *, node: bool = False) -> dict[str, str]:
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
    if node:
        environment["NODE_OPTIONS"] = "--no-warnings"
        environment["NODE_PATH"] = ""
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
        node_executable: str | None = None,
        chromium_executable: str | None = None,
        clamav_checker: ClamAVChecker | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.clamav_checker = clamav_checker
        # A trusted worker may choose an absolute node path.  It is not exposed
        # through request options and never comes from document input.
        self.node_executable = node_executable or shutil.which("node")
        # Chromium is likewise selected by the worker image, never by a
        # scratch request.  The explicit constructor argument is a test seam.
        self.chromium_executable = chromium_executable or next(
            (shutil.which(name) for name in (
                "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
            ) if shutil.which(name)),
            None,
        )

    def process(
        self,
        content: bytes,
        media_type: str | None = None,
        options: ProcessorOptions | dict[str, Any] | None = None,
    ) -> ProcessedDocument:
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
                if opts.prepare_pdf:
                    pages, blocks, child_warnings, converted_pdf, pdf_metadata = self._prepare_pdf_structure(
                        original, opts, deadline=deadline,
                    )
                    warnings.extend(child_warnings)
                    extractor = {"name": "hwp-rhwp-canvas-chromium-pdf", "version": "1", "upstream_commit": UPSTREAM_COMMIT}
                else:
                    converted = self._convert_hwp(original, opts, deadline=deadline)
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
            if opts.prepare_pdf:
                # MIME detection only inspects the ZIP central directory. Keep
                # the existing archive traversal, link, member, ratio, and
                # decompressed-size boundary in front of the rhwp process even
                # though PDF preparation does not need the stdlib XML parser.
                try:
                    archive = validate_zip(original, opts)
                except DocumentProcessingError as exc:
                    exc.source_preserved = True
                    raise
                archive.close()
                pages, blocks, child_warnings, converted_pdf, pdf_metadata = self._prepare_pdf_structure(
                    original, opts, deadline=deadline,
                )
                warnings.extend(child_warnings)
                extractor = {"name": "hwpx-rhwp-canvas-chromium-pdf", "version": "1", "upstream_commit": UPSTREAM_COMMIT}
            else:
                pages, blocks, child_warnings = extract_hwpx(original, opts)
                warnings.extend(child_warnings)
                extractor = extractor_info()
        elif detected == "application/pdf":
            try:
                if opts.prepare_pdf:
                    # The stdlib reader can decode a few font glyph bytes as
                    # apparently valid Unicode.  That is unsafe for the v4
                    # input cut: a non-empty but meaningless result prevents
                    # the bounded Poppler fallback from running.  Prepared
                    # PDF inputs therefore use the same bounded Poppler text
                    # source as generated Canvas PDFs.  The legacy path below
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
        )

    @staticmethod
    def _remaining_timeout(deadline: float | None, options: ProcessorOptions, message: str) -> float:
        if deadline is None:
            return float(options.timeout_seconds)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DocumentProcessingError("timeout", message, source_preserved=True)
        return min(float(options.timeout_seconds), remaining)

    def _verify_canvas_print_receipt(
        self,
        pdf_path: Path,
        options: ProcessorOptions,
        *,
        deadline: float | None = None,
    ) -> None:
        """Accept a print only when pdfinfo reports the final DOM receipt."""

        executable = shutil.which("pdfinfo")
        if not executable:
            raise DocumentProcessingError("converter_unavailable", "PDF 완료 receipt를 확인할 수 없습니다", source_preserved=True)
        try:
            returncode, stdout, _stderr = _run_limited_subprocess(
                [executable, str(pdf_path)],
                cwd=str(pdf_path.parent),
                env=_child_environment(executable),
                timeout=self._remaining_timeout(deadline, options, "HWP PDF 완료 확인 시간이 제한을 초과했습니다"),
                output_limit=64 * 1024,
                preexec_fn=_resource_limiter(options.max_output_bytes),
            )
        except _ChildTimeout as exc:
            raise DocumentProcessingError("timeout", "HWP PDF 완료 확인 시간이 제한을 초과했습니다", source_preserved=True) from exc
        except _ChildOutputLimit as exc:
            raise DocumentProcessingError("output_size_limit", "HWP PDF 완료 metadata 크기 제한을 초과했습니다", source_preserved=True) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise DocumentProcessingError("converter_unavailable", "PDF 완료 receipt를 확인할 수 없습니다", source_preserved=True) from exc
        if returncode != 0:
            raise DocumentProcessingError("conversion_required", "HWP PDF 완료 receipt를 확인할 수 없습니다", source_preserved=True)
        try:
            info = stdout.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError("conversion_required", "HWP PDF 완료 receipt를 확인할 수 없습니다", source_preserved=True) from exc
        title = next(
            (line.partition(":")[2].strip() for line in info.splitlines() if line.startswith("Title:")),
            None,
        )
        if title != _CANVAS_PRINT_RECEIPT:
            raise DocumentProcessingError("conversion_required", "HWP PDF 렌더 완료를 확인할 수 없습니다", source_preserved=True)

    def _prepare_pdf_structure(
        self,
        original: bytes,
        options: ProcessorOptions,
        *,
        deadline: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bytes, dict[str, Any]]:
        """Render HWP/HWPX through rhwp Canvas and fixed Chromium print.

        rhwp's SVG exporter can omit text in table controls.  The vendored
        browser binding paints the same pages to Canvas correctly; its text
        layout runs are added as a transparent selectable layer at the exact
        renderer coordinates.  The resulting PDF is parsed again by the
        existing bounded reader before it is returned as a snapshot.
        """

        if not self.node_executable or not self.chromium_executable:
            raise DocumentProcessingError(
                "converter_unavailable",
                "HWP PDF 변환기를 사용할 수 없습니다",
                source_preserved=True,
            )
        vendor = Path(__file__).with_name("vendor")
        script = vendor / "rhwp_render_canvas.mjs"
        runtime_path = vendor / "rhwp" / "rhwp.js"
        wasm_path = vendor / "rhwp" / "rhwp_bg.wasm"
        if not script.is_file() or not runtime_path.is_file() or not wasm_path.is_file():
            raise DocumentProcessingError(
                "converter_unavailable",
                "HWP PDF 변환기를 사용할 수 없습니다",
                source_preserved=True,
            )
        try:
            runtime = runtime_path.read_text(encoding="utf-8")
            wasm = wasm_path.read_bytes()
            adapter = script.read_bytes()
            processor_source = Path(__file__).read_bytes()
        except (OSError, UnicodeError) as exc:
            raise DocumentProcessingError("converter_unavailable", "HWP PDF runtime을 읽을 수 없습니다", source_preserved=True) from exc
        # These are fixed vendored assets, not request-controlled output. Keep
        # a hard bound so a mistaken replacement cannot become an HTML budget
        # bypass or an unbounded browser input.
        if len(runtime.encode("utf-8")) > 2 * 1024 * 1024 or len(wasm) > 16 * 1024 * 1024:
            raise DocumentProcessingError("output_size_limit", "HWP PDF runtime 크기 제한을 초과했습니다", source_preserved=True)

        with tempfile.TemporaryDirectory(prefix="bidops-hwp-pdf-") as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            html_path = root / "print.html"
            pdf_path = root / "output.pdf"
            source.write_bytes(original)
            node_env = _child_environment(self.node_executable, node=True)
            try:
                returncode, stdout, _stderr = _run_limited_subprocess(
                    [
                        self.node_executable,
                        str(script),
                        "--input",
                        str(source),
                        "--max-pages",
                        str(min(options.max_pages, options.max_pdf_pages)),
                        "--max-output-bytes",
                        str(options.max_output_bytes),
                    ],
                    cwd=tmp,
                    env=node_env,
                    timeout=self._remaining_timeout(deadline, options, "문서 PDF 변환 시간이 제한을 초과했습니다"),
                    output_limit=256 * 1024,
                    preexec_fn=_resource_limiter(options.max_output_bytes),
                )
            except _ChildTimeout as exc:
                raise DocumentProcessingError("timeout", "문서 PDF 변환 시간이 제한을 초과했습니다", source_preserved=True) from exc
            except _ChildOutputLimit as exc:
                raise DocumentProcessingError("output_size_limit", "문서 PDF 변환 metadata 크기 제한을 초과했습니다", source_preserved=True) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise DocumentProcessingError("converter_unavailable", "HWP PDF 변환기를 사용할 수 없습니다", source_preserved=True) from exc
            if returncode == 2:
                raise DocumentProcessingError("output_size_limit", "문서 PDF 변환 결과 크기 제한을 초과했습니다", source_preserved=True)
            if returncode != 0:
                raise DocumentProcessingError("conversion_required", "HWP PDF 변환 확인 필요", source_preserved=True)
            try:
                metadata = json.loads(stdout.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise DocumentProcessingError("conversion_required", "HWP PDF 페이지 정보를 확인할 수 없습니다", source_preserved=True) from exc
            if not isinstance(metadata, dict):
                raise DocumentProcessingError("conversion_required", "HWP PDF 페이지 정보를 확인할 수 없습니다", source_preserved=True)
            pages_meta = metadata.get("pages")
            if (
                metadata.get("schema") != "bidops.hwp-page-canvas.v1"
                or metadata.get("renderer") != "rhwp-canvas"
                or metadata.get("scale") != 1
                or not isinstance(pages_meta, list)
                or not pages_meta
            ):
                raise DocumentProcessingError("conversion_required", "HWP PDF 페이지 정보를 확인할 수 없습니다", source_preserved=True)
            if len(pages_meta) > min(options.max_pages, options.max_pdf_pages):
                raise DocumentProcessingError("pdf_page_limit", "PDF page 수 제한을 초과했습니다", source_preserved=True)

            validated_pages: list[dict[str, Any]] = []
            try:
                for expected_number, page in enumerate(pages_meta, 1):
                    if not isinstance(page, dict) or set(page) != {"number", "width", "height"}:
                        raise ValueError("invalid page metadata")
                    number = page.get("number")
                    width = float(page.get("width"))
                    height = float(page.get("height"))
                    if (
                        number != expected_number
                        or not isinstance(number, int)
                        or number < 1
                        or not math.isfinite(width)
                        or not math.isfinite(height)
                        or width <= 0
                        or height <= 0
                        or width * height > 100_000_000
                    ):
                        raise ValueError("invalid page metadata")
                    validated_pages.append({"number": number, "width": width, "height": height})
            except (TypeError, ValueError) as exc:
                raise DocumentProcessingError("conversion_required", "HWP PDF 페이지 정보를 확인할 수 없습니다", source_preserved=True) from exc
            if any(
                page["width"] != validated_pages[0]["width"]
                or page["height"] != validated_pages[0]["height"]
                for page in validated_pages[1:]
            ):
                raise DocumentProcessingError(
                    "pdf_page_mismatch",
                    "문서 page 크기가 서로 달라 PDF 대응을 확인할 수 없습니다",
                    source_preserved=True,
                )
            try:
                html_document = _build_canvas_print_html(
                    source=original,
                    runtime=runtime,
                    wasm=wasm,
                    pages=validated_pages,
                    max_html_bytes=options.max_output_bytes,
                )
                OutputBudget(options.max_output_bytes).consume(len(html_document.encode("utf-8")))
            except DocumentProcessingError as exc:
                exc.source_preserved = True
                raise
            html_path.write_text(html_document, encoding="utf-8")
            chrome_profile = root / "chrome-profile"
            chrome_profile.mkdir(mode=0o700)
            chromium_env = _child_environment(self.chromium_executable)
            chromium_command = [
                self.chromium_executable,
                "--headless",
                # The outer worker remains non-root/network-disabled/cgroup
                # isolated. Debian Chromium's inner user namespace cannot
                # initialize in that restricted namespace, so this flag is
                # limited to the already isolated print child.
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--no-first-run",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                f"--user-data-dir={chrome_profile}",
                f"--print-to-pdf={pdf_path}",
                html_path.resolve().as_uri(),
            ]
            try:
                returncode, _stdout, _stderr = _run_limited_subprocess(
                    chromium_command,
                    cwd=tmp,
                    env=chromium_env,
                    timeout=self._remaining_timeout(deadline, options, "HWP PDF 인쇄 시간이 제한을 초과했습니다"),
                    output_limit=256 * 1024,
                    preexec_fn=_resource_limiter(
                        min(options.max_output_bytes * 4, 256 * 1024 * 1024),
                        address_space_bytes=None,
                        data_bytes=None,
                    ),
                )
            except _ChildTimeout as exc:
                raise DocumentProcessingError("timeout", "HWP PDF 인쇄 시간이 제한을 초과했습니다", source_preserved=True) from exc
            except _ChildOutputLimit as exc:
                raise DocumentProcessingError("output_size_limit", "HWP PDF 인쇄 metadata 크기 제한을 초과했습니다", source_preserved=True) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise DocumentProcessingError("converter_unavailable", "Chromium PDF 인쇄기를 사용할 수 없습니다", source_preserved=True) from exc
            if returncode != 0 or not pdf_path.is_file():
                raise DocumentProcessingError("conversion_required", "HWP PDF 인쇄 확인 필요", source_preserved=True)
            try:
                pdf = pdf_path.read_bytes()
            except OSError as exc:
                raise DocumentProcessingError("conversion_required", "HWP PDF 결과를 읽을 수 없습니다", source_preserved=True) from exc
            if not pdf.startswith(b"%PDF-") or len(pdf) > options.max_output_bytes:
                raise DocumentProcessingError("output_size_limit", "HWP PDF 결과 크기 제한을 초과했습니다", source_preserved=True)
            self._verify_canvas_print_receipt(pdf_path, options, deadline=deadline)

        # The generated Canvas PDF is the v4 preparation artifact.  Always
        # obtain its page text through the existing bounded Poppler adapter:
        # the stdlib parser may return a non-empty stream made from font
        # glyph bytes, which would incorrectly suppress the fallback.  Keep
        # ``_parse_pdf_structure`` for the legacy PDF path and preserve its
        # object/page/output limits here through the same options.
        try:
            try:
                extract_pdf(pdf, options)
            except DocumentProcessingError as exc:
                if exc.code != "malformed_pdf":
                    raise
            pdf_pages, pdf_blocks, pdf_warnings, parsed_pages = self._extract_pdf_poppler(
                pdf,
                options,
                deadline=deadline,
            )
            pdf_warnings.append("pdf_poppler_text_fallback")
        except DocumentProcessingError:
            raise
        if len(parsed_pages) != len(validated_pages):
            raise DocumentProcessingError("pdf_page_mismatch", "변환 PDF page 대응을 확인할 수 없습니다", source_preserved=True)
        for expected, parsed in zip(validated_pages, parsed_pages):
            if parsed.number != expected["number"]:
                raise DocumentProcessingError("pdf_page_mismatch", "변환 PDF page 대응을 확인할 수 없습니다", source_preserved=True)
            expected_ratio = expected["width"] / expected["height"]
            parsed_ratio = parsed.width / parsed.height if parsed.height else 0
            if not math.isfinite(parsed_ratio) or abs(expected_ratio - parsed_ratio) > 0.01:
                raise DocumentProcessingError("pdf_page_mismatch", "변환 PDF page 크기를 확인할 수 없습니다", source_preserved=True)
        empty_pages = [page.number for page in parsed_pages if not page.text.strip()]
        if len(empty_pages) == len(parsed_pages):
            raise DocumentProcessingError("pdf_empty_text", "변환 PDF에서 읽을 수 있는 page text가 없습니다", source_preserved=True)
        if empty_pages:
            # A physically blank page is valid and remains in the snapshot;
            # later page-range validation decides whether selected text is
            # unreadable. Do not escalate a normal blank page globally.
            pdf_warnings.append("pdf_blank_page")
        renderer_provenance, font_provenance = _worker_provenance(
            runtime=runtime,
            wasm=wasm,
            adapter=adapter,
            processor_source=processor_source,
            chromium_executable=self.chromium_executable,
            options=options,
            deadline=deadline,
        )
        metadata = {
            "schema": "bidops.hwp-pdf-snapshot.v1",
            "renderer": "rhwp-canvas-chromium",
            "renderer_version": "1",
            "render_scale": 1,
            "page_count": len(parsed_pages),
            "renderer_provenance": renderer_provenance,
            "font_provenance": font_provenance,
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
        return pdf_pages, pdf_blocks, pdf_warnings, pdf, metadata

    def _parse_pdf_structure(
        self,
        pdf: bytes,
        options: ProcessorOptions,
        *,
        fallback_on_empty: bool = False,
        deadline: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[PdfPage]]:
        """Use the existing bounded parser and Poppler fallback for generated PDF."""

        try:
            pages, blocks, warnings, parsed = extract_pdf(pdf, options)
            if _has_binary_text_controls(blocks):
                raise DocumentProcessingError("malformed_pdf", "PDF text stream이 portable text가 아닙니다")
            if fallback_on_empty and parsed and not any(page.text.strip() for page in parsed):
                fallback_pages, fallback_blocks, fallback_warnings, fallback_parsed = (
                    self._extract_pdf_poppler(pdf, options, deadline=deadline)
                    if deadline is not None
                    else self._extract_pdf_poppler(pdf, options)
                )
                fallback_warnings.append("pdf_stdlib_text_fallback")
                return fallback_pages, fallback_blocks, fallback_warnings, fallback_parsed
            return pages, blocks, warnings, parsed
        except DocumentProcessingError as exc:
            if exc.code != "malformed_pdf":
                raise
            pages, blocks, warnings, parsed = (
                self._extract_pdf_poppler(pdf, options, deadline=deadline)
                if deadline is not None
                else self._extract_pdf_poppler(pdf, options)
            )
            warnings.append("pdf_stdlib_text_fallback")
            return pages, blocks, warnings, parsed

    def _convert_hwp(
        self,
        original: bytes,
        options: ProcessorOptions,
        *,
        deadline: float | None = None,
    ) -> bytes:
        if not self.node_executable:
            raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True)
        script = Path(__file__).with_name("vendor") / "rhwp_convert.mjs"
        if not script.is_file():
            raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True)
        with tempfile.TemporaryDirectory(prefix="bidops-doc-") as tmp:
            source = Path(tmp) / "source.hwp"
            source.write_bytes(original)
            env = _child_environment(self.node_executable, node=True)
            try:
                returncode, stdout, _stderr = _run_limited_subprocess(
                    [self.node_executable, str(script), "--stdout", str(source)],
                    cwd=tmp,
                    env=env,
                    timeout=self._remaining_timeout(deadline, options, "문서 변환 시간이 제한을 초과했습니다"),
                    output_limit=options.max_output_bytes,
                    preexec_fn=_resource_limiter(options.max_output_bytes),
                )
            except _ChildTimeout as exc:
                raise DocumentProcessingError("timeout", "문서 변환 시간이 제한을 초과했습니다", source_preserved=True) from exc
            except _ChildOutputLimit as exc:
                raise DocumentProcessingError("output_size_limit", "변환 결과 크기 제한을 초과했습니다", source_preserved=True) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise DocumentProcessingError("converter_unavailable", "HWP 변환기를 사용할 수 없습니다", source_preserved=True) from exc
            if returncode != 0 or not stdout:
                raise DocumentProcessingError("conversion_required", "HWP 변환 확인 필요", source_preserved=True)
            if not stdout.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                raise DocumentProcessingError("conversion_required", "HWP 변환 확인 필요", source_preserved=True)
            return stdout

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
