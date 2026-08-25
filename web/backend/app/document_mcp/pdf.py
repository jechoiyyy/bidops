"""Small, bounded PDF text/page reader.

This is intentionally not a general PDF implementation.  It handles the
portable text PDF subset needed by the quarantine worker and delegates page
rendering/OCR to optional, resource-limited executables or a trusted injected
engine.  Unsupported or damaged PDFs fail closed.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from typing import Any

from .errors import DocumentProcessingError
from .safety import ProcessorOptions


@dataclass(frozen=True)
class PdfPage:
    number: int
    width: float
    height: float
    text: str
    content: bytes


_OBJECT = re.compile(rb"(?ms)(\d+)\s+(\d+)\s+obj\s*(.*?)\s*endobj")
_PAGE = re.compile(rb"/Type\s*/Page\b")
_MEDIA = re.compile(rb"/MediaBox\s*\[\s*([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s*\]")
_REF = re.compile(rb"/Contents\s+(\d+)\s+(\d+)\s+R")
_REFS = re.compile(rb"/Contents\s*\[([^]]+)\]")


def _pdf_literal(raw: bytes) -> str:
    if raw.startswith(b"<") and raw.endswith(b">"):
        try:
            return bytes.fromhex(re.sub(rb"\s+", b"", raw[1:-1]).decode()).decode("utf-16-be", "ignore")
        except (ValueError, UnicodeError):
            return raw[1:-1].decode("latin-1", "replace")
    value = raw[1:-1]
    result = bytearray()
    escaped = False
    octal = b""
    for char in value:
        if octal:
            if 48 <= char <= 55 and len(octal) < 3:
                octal += bytes([char])
                if len(octal) == 3:
                    result.append(int(octal, 8))
                    octal = b""
                continue
            result.append(int(octal, 8))
            octal = b""
        if escaped:
            if char in b"nrtbf":
                result.append({110: 10, 114: 13, 116: 9, 98: 8, 102: 12}[char])
            elif 48 <= char <= 55:
                octal = bytes([char])
            else:
                result.append(char)
            escaped = False
        elif char == 92:
            escaped = True
        else:
            result.append(char)
    if octal:
        result.append(int(octal, 8))
    return bytes(result).decode("utf-8", "replace")


def _text_from_stream(stream: bytes) -> str:
    chunks: list[str] = []
    # Both literal and hexadecimal strings are accepted as operands to Tj/TJ.
    pattern = re.compile(rb"(\((?:\\.|[^()])*\)|<[0-9a-fA-F\s]+>)\s*(?:Tj|')")
    for match in pattern.finditer(stream):
        chunks.append(_pdf_literal(match.group(1)))
    for match in re.finditer(rb"\[(.*?)\]\s*TJ", stream, re.S):
        for token in re.findall(rb"\((?:\\.|[^()])*\)|<[0-9a-fA-F\s]+>", match.group(1)):
            chunks.append(_pdf_literal(token))
        chunks.append(" ")
    return "".join(chunks).strip()


def _stream_body(obj: bytes) -> bytes:
    marker = re.search(rb"stream\r?\n", obj)
    if not marker:
        return b""
    end = obj.find(b"endstream", marker.end())
    if end < 0:
        raise DocumentProcessingError("malformed_pdf", "PDF stream이 손상되었습니다")
    body = obj[marker.end():end]
    if b"/FlateDecode" in obj[:marker.start()]:
        try:
            body = zlib.decompress(body)
        except zlib.error as exc:
            raise DocumentProcessingError("malformed_pdf", "PDF 압축 stream을 읽을 수 없습니다") from exc
    return body


def extract_pdf(data: bytes, options: ProcessorOptions) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[PdfPage]]:
    if b"/Encrypt" in data:
        raise DocumentProcessingError("encrypted_pdf", "암호화된 PDF는 처리할 수 없습니다")
    if data.count(b" obj") > options.max_archive_files * 8:
        raise DocumentProcessingError("pdf_object_limit", "PDF object 수 제한을 초과했습니다")
    objects = {(int(match.group(1)), int(match.group(2))): match.group(3) for match in _OBJECT.finditer(data)}
    if not objects:
        raise DocumentProcessingError("malformed_pdf", "PDF object를 찾을 수 없습니다")
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    parsed: list[PdfPage] = []
    page_objects = [obj for obj in objects.values() if _PAGE.search(obj)]
    if not page_objects:
        page_objects = [obj for obj in objects.values() if b"stream" in obj]
    for page_number, page_obj in enumerate(page_objects, 1):
        media = _MEDIA.search(page_obj)
        if media:
            x0, y0, x1, y1 = (float(media.group(i)) for i in range(1, 5))
            width, height = abs(x1 - x0), abs(y1 - y0)
        else:
            width, height = 595.0, 842.0
        if width <= 0 or height <= 0 or width > 100_000 or height > 100_000 or width * height > 100_000_000:
            raise DocumentProcessingError("pdf_page_limit", "PDF page 해상도 제한을 초과했습니다")
        content = b""
        reference = _REF.search(page_obj)
        references = _REFS.search(page_obj)
        if reference:
            content = _stream_body(objects.get((int(reference.group(1)), int(reference.group(2))), b""))
        elif references:
            for number, generation in re.findall(rb"(\d+)\s+(\d+)\s+R", references.group(1)):
                content += _stream_body(objects.get((int(number), int(generation)), b""))
        elif b"stream" in page_obj:
            content = _stream_body(page_obj)
        text = _text_from_stream(content)
        pages.append({"number": page_number, "width": width, "height": height, "image_content_object_id": None})
        if text:
            blocks.append({
                "block_key": f"page-{page_number}-text",
                "parent_block_key": None,
                "type": "text",
                "page": page_number,
                "bbox": [0.0, 0.0, width, height],
                "text": text,
                "confidence": 1.0,
                "attributes": {"source": "pdf-text"},
            })
        parsed.append(PdfPage(page_number, width, height, text, content))
    if not pages:
        raise DocumentProcessingError("malformed_pdf", "PDF page를 찾을 수 없습니다")
    return pages, blocks, [], parsed
