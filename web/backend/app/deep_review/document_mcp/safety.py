"""Input detection and archive safety checks for the quarantine boundary."""

from __future__ import annotations

import io
import math
import os
import struct
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .contracts import DEFAULT_MAX_BLOCKS, DEFAULT_MAX_PAGES
from .errors import DocumentLimitError, DocumentProcessingError

HWP_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
MAX_INPUT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class ProcessorOptions:
    """The only knobs exposed by the processor.

    No filesystem, URL, command, output location, or callback can be supplied
    through this object.  A worker may still inject a trusted OCR implementation
    into :class:`DocumentProcessor` itself.
    """

    timeout_seconds: float = 30.0
    max_output_bytes: int = 20 * 1024 * 1024
    max_archive_files: int = 512
    max_archive_depth: int = 2
    max_archive_uncompressed_bytes: int = 100 * 1024 * 1024
    max_xml_depth: int = 256
    max_pages: int = DEFAULT_MAX_PAGES
    max_pdf_pages: int = 512
    max_pdf_objects: int = 4096
    max_blocks: int = DEFAULT_MAX_BLOCKS
    render_pages: bool = False
    # HWP/HWPX page-PDF preparation is opt-in at the processor boundary.  The
    # prespec v4 path sets this explicitly after the policy/worker gate; legacy
    # document inspection keeps its existing structure-only contract.
    prepare_pdf: bool = False
    # R3 may opt a snapshot into the native renderer.  The default deliberately
    # preserves the existing Canvas/Chromium path until that integration lands.
    renderer: str = "rhwp-canvas-chromium"
    ocr: bool = True

    @classmethod
    def from_mapping(cls, value: Any | None) -> "ProcessorOptions":
        if value is None:
            result = cls()
        elif isinstance(value, cls):
            result = value
        elif isinstance(value, dict):
            payload = dict(value)
            allowed = {
                "timeout_seconds", "max_output_bytes", "max_archive_files",
                "max_archive_depth", "max_archive_uncompressed_bytes", "max_xml_depth",
                "max_pages", "max_pdf_pages", "max_pdf_objects", "max_blocks", "render_pages", "prepare_pdf", "renderer", "ocr",
            }
            if set(payload) - allowed:
                raise DocumentProcessingError("invalid_options", "허용되지 않는 문서 처리 option입니다")
            try:
                result = cls(**payload)
            except (TypeError, ValueError) as exc:
                raise DocumentProcessingError("invalid_options", "문서 처리 options 형식이 올바르지 않습니다") from exc
        else:
            raise DocumentProcessingError("invalid_options", "문서 처리 options 형식이 올바르지 않습니다")

        if (
            isinstance(result.timeout_seconds, bool)
            or not isinstance(result.timeout_seconds, (int, float))
            or not math.isfinite(result.timeout_seconds)
            or not 0.1 <= result.timeout_seconds <= 300
        ):
            raise DocumentProcessingError("invalid_options", "처리 timeout 범위를 벗어났습니다")
        if isinstance(result.max_output_bytes, bool) or not isinstance(result.max_output_bytes, int) or not 1 <= result.max_output_bytes <= 100 * 1024 * 1024:
            raise DocumentProcessingError("invalid_options", "처리 output 크기 제한이 올바르지 않습니다")
        if isinstance(result.max_archive_files, bool) or isinstance(result.max_archive_depth, bool) or not isinstance(result.max_archive_files, int) or not isinstance(result.max_archive_depth, int) or not 1 <= result.max_archive_files <= 10_000 or not 0 <= result.max_archive_depth <= 5:
            raise DocumentProcessingError("invalid_options", "압축 파일 제한이 올바르지 않습니다")
        if isinstance(result.max_archive_uncompressed_bytes, bool) or not isinstance(result.max_archive_uncompressed_bytes, int) or not 1 <= result.max_archive_uncompressed_bytes <= 500 * 1024 * 1024:
            raise DocumentProcessingError("invalid_options", "압축 해제 크기 제한이 올바르지 않습니다")
        if (
            isinstance(result.max_xml_depth, bool)
            or not isinstance(result.max_xml_depth, int)
            or not 8 <= result.max_xml_depth <= 1024
            or isinstance(result.max_pages, bool)
            or not isinstance(result.max_pages, int)
            or not 1 <= result.max_pages <= 4096
            or isinstance(result.max_pdf_pages, bool)
            or not isinstance(result.max_pdf_pages, int)
            or not 1 <= result.max_pdf_pages <= 4096
            or isinstance(result.max_pdf_objects, bool)
            or not isinstance(result.max_pdf_objects, int)
            or not 1 <= result.max_pdf_objects <= 100_000
            or isinstance(result.max_blocks, bool)
            or not isinstance(result.max_blocks, int)
            or not 1 <= result.max_blocks <= 1_000_000
        ):
            raise DocumentProcessingError("invalid_options", "문서 구조 제한이 올바르지 않습니다")
        if not isinstance(result.render_pages, bool) or not isinstance(result.prepare_pdf, bool) or not isinstance(result.ocr, bool):
            raise DocumentProcessingError("invalid_options", "문서 처리 option 형식이 올바르지 않습니다")
        if result.renderer not in {"rhwp-canvas-chromium", "rhwp-svg-pdf"}:
            raise DocumentProcessingError("invalid_options", "문서 renderer option이 올바르지 않습니다")
        return result


def detect_media_type(data: bytes, declared: str | None) -> str:
    """Detect a supported MIME from magic bytes and reconcile it with MIME."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise DocumentProcessingError("invalid_input", "문서 입력은 bytes여야 합니다")
    blob = bytes(data)
    if len(blob) > MAX_INPUT_BYTES:
        raise DocumentLimitError("input_size_limit", "문서 입력 크기 제한을 초과했습니다")
    detected: str | None
    if blob.startswith(HWP_MAGIC):
        detected = "application/x-hwp"
    elif blob.startswith(PDF_MAGIC):
        detected = "application/pdf"
    elif blob.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif blob.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif blob.startswith((b"GIF87a", b"GIF89a")):
        detected = "image/gif"
    elif blob.startswith(b"BM"):
        detected = "image/bmp"
    elif blob.startswith(b"II*\x00") or blob.startswith(b"MM\x00*"):
        detected = "image/tiff"
    elif blob.startswith(ZIP_MAGIC) or blob.startswith(b"PK\x05\x06") or blob.startswith(b"PK\x07\x08"):
        declared_normalized = (declared or "").split(";", 1)[0].strip().lower()
        detected = "application/hwp+zip" if _looks_like_hwpx(blob) or declared_normalized in {
            "application/hwp+zip", "application/vnd.hancom.hwpx", "application/haansoft-hwpx",
        } else "application/zip"
    else:
        raise DocumentProcessingError("mime_mismatch", "지원하지 않는 문서 형식입니다")
    if declared:
        normalized = declared.split(";", 1)[0].strip().lower()
        aliases = {
            "application/octet-stream": detected,
            "application/zip": "application/hwp+zip" if detected == "application/hwp+zip" else "application/zip",
            "application/x-zip-compressed": "application/hwp+zip" if detected == "application/hwp+zip" else "application/zip",
            "image/jpg": "image/jpeg",
            "application/vnd.hancom.hwp": "application/x-hwp",
            "application/vnd.hancom.hwpx": "application/hwp+zip",
            "application/haansoft-hwpx": "application/hwp+zip",
        }
        if aliases.get(normalized, normalized) != detected:
            raise DocumentProcessingError("mime_mismatch", "선언된 media type과 파일 형식이 일치하지 않습니다")
    return detected


def _looks_like_hwpx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            # Detection only inspects the central directory and a bounded
            # filename set.  It never decompresses an untrusted member here.
            if not members or len(members) > 10_000:
                return False
            names = {info.filename.replace("\\", "/") for info in members}
    except (OSError, zipfile.BadZipFile):
        return False
    # Do not read a member at detection time: the central directory is still
    # untrusted and is checked for decompression limits immediately afterwards.
    return "mimetype" in names or any(name.startswith("Contents/") and name.endswith(".xml") for name in names)


def validate_zip(data: bytes, options: ProcessorOptions) -> zipfile.ZipFile:
    """Validate ZIP central-directory metadata before any member is read."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocumentProcessingError("malformed_archive", "압축 문서를 읽을 수 없습니다") from exc
    if not members or len(members) > options.max_archive_files:
        archive.close()
        raise DocumentLimitError("archive_file_limit", "압축 문서 파일 수 제한을 초과했습니다")
    total = 0
    seen_names: set[str] = set()
    for info in members:
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (
            not path.parts
            or not name
            or "\x00" in name
            or ":" in path.parts[0]
            or path.is_absolute()
            or ".." in path.parts
        ):
            archive.close()
            raise DocumentProcessingError("archive_traversal", "압축 문서 경로가 안전하지 않습니다")
        if name in seen_names:
            archive.close()
            raise DocumentProcessingError("archive_duplicate", "압축 문서에 중복 파일이 있습니다")
        seen_names.add(name)
        if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
            archive.close()
            raise DocumentProcessingError("archive_link", "압축 문서 링크는 허용되지 않습니다")
        if info.flag_bits & 0x1:
            archive.close()
            raise DocumentProcessingError("encrypted_archive", "암호화된 압축 문서는 처리할 수 없습니다")
        if info.file_size < 0 or info.file_size > options.max_output_bytes:
            archive.close()
            raise DocumentLimitError("archive_member_limit", "압축 문서 파일 크기 제한을 초과했습니다")
        total += info.file_size
        if total > options.max_archive_uncompressed_bytes:
            archive.close()
            raise DocumentLimitError("archive_size_limit", "압축 해제 크기 제한을 초과했습니다")
        if info.compress_size and info.file_size / info.compress_size > 1000:
            archive.close()
            raise DocumentLimitError("archive_ratio_limit", "압축 해제 비율 제한을 초과했습니다")
        # Every regular member is magic-sniffed.  File extensions are metadata
        # controlled by an attacker and must not be used as the archive-depth
        # boundary.  Reading a bounded 265-byte prefix reaches the TAR magic
        # at offset 257 without loading the member into memory;
        # central-directory size, member size, ratio, and total limits above
        # bound the decompressor before this read.
        try:
            with archive.open(info) as member:
                head = member.read(265)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            archive.close()
            raise DocumentProcessingError("malformed_archive", "압축 문서를 읽을 수 없습니다") from exc
        nested_magic = (
            head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
            or head.startswith(b"ustar")
            or head[257:262] == b"ustar"
            or head.startswith(b"\x1f\x8b")
            or head.startswith(b"7z\xbc\xaf\x27\x1c")
            or head.startswith(b"Rar!\x1a\x07")
        )
        if nested_magic:
            archive.close()
            # The processor does not need nested archives; reject them even
            # when the configured depth would otherwise permit one.  This
            # makes max_archive_depth an active safety boundary rather than a
            # filename-dependent hint.
            nested_depth = 1
            if nested_depth > options.max_archive_depth:
                raise DocumentLimitError("archive_depth_limit", "압축 중첩 깊이 제한을 초과했습니다")
            raise DocumentLimitError("archive_depth_limit", "중첩 압축 문서는 허용되지 않습니다")
    return archive


def enforce_input_limit(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise DocumentProcessingError("invalid_input", "문서 입력은 bytes여야 합니다")
    blob = bytes(data)
    if len(blob) > MAX_INPUT_BYTES:
        raise DocumentLimitError("input_size_limit", "문서 입력 크기 제한을 초과했습니다")
    if not blob:
        raise DocumentProcessingError("invalid_input", "빈 문서는 처리할 수 없습니다")
    return blob


class OutputBudget:
    """A monotonic byte budget for decoded and generated processor output."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self, size: int) -> None:
        if size < 0 or size > self.remaining:
            raise DocumentLimitError("output_size_limit", "문서 처리 결과 크기 제한을 초과했습니다")
        self.used += size

    def consume_text(self, value: str) -> None:
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError as exc:
            raise DocumentProcessingError("output_size_limit", "문서 처리 결과 형식이 올바르지 않습니다") from exc
        self.consume(size)


def image_dimensions(data: bytes, media_type: str) -> tuple[int, int]:
    """Read image dimensions without importing a heavyweight image library."""
    try:
        if media_type == "image/png":
            if len(data) < 24:
                raise ValueError
            return struct.unpack(">II", data[16:24])
        if media_type == "image/gif":
            if len(data) < 10:
                raise ValueError
            return struct.unpack("<HH", data[6:10])
        if media_type == "image/bmp":
            if len(data) < 26:
                raise ValueError
            return struct.unpack("<II", data[18:26])
        if media_type == "image/jpeg":
            offset = 2
            while offset + 9 < len(data):
                if data[offset] != 0xFF:
                    offset += 1
                    continue
                marker = data[offset + 1]
                offset += 2
                if marker in (0xD8, 0xD9):
                    continue
                if offset + 2 > len(data):
                    break
                length = int.from_bytes(data[offset:offset + 2], "big")
                if length < 2 or offset + length > len(data):
                    break
                if marker in range(0xC0, 0xC4) or marker in range(0xC5, 0xC8) or marker in range(0xC9, 0xCC) or marker in range(0xCD, 0xD0):
                    if length < 7:
                        break
                    return int.from_bytes(data[offset + 3:offset + 5], "big"), int.from_bytes(data[offset + 5:offset + 7], "big")
                offset += length
        if media_type == "image/tiff":
            endian = "little" if data[:2] == b"II" else "big"
            base = int.from_bytes(data[4:8], endian)
            count = int.from_bytes(data[base:base + 2], endian)
            width: int | None = None
            height: int | None = None
            for index in range(count):
                start = base + 2 + index * 12
                tag = int.from_bytes(data[start:start + 2], endian)
                if tag in (256, 257):
                    field_type = int.from_bytes(data[start + 2:start + 4], endian)
                    item_count = int.from_bytes(data[start + 4:start + 8], endian)
                    if item_count != 1:
                        continue
                    if field_type == 3:  # SHORT fits inline in the value field.
                        value_offset = int.from_bytes(data[start + 8:start + 10], endian)
                    elif field_type == 4:  # LONG also fits inline for count=1.
                        value_offset = int.from_bytes(data[start + 8:start + 12], endian)
                    else:
                        continue
                    if tag == 256:
                        width = value_offset
                    else:
                        height = value_offset
            if width is not None and height is not None:
                return width, height
    except (IndexError, struct.error, ValueError):
        pass
    raise DocumentProcessingError("malformed_image", "이미지 크기를 확인할 수 없습니다")
