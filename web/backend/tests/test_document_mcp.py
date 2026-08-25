from __future__ import annotations

import io
import json
import os
import struct
import uuid
import zipfile
import zlib
from pathlib import Path

import pytest

from app.document_mcp import (
    MAX_INPUT_BYTES,
    DocumentProcessingError,
    DocumentProcessor,
    ProcessorOptions,
    process_document,
    validate_structure,
)

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def hwpx_bytes(*, name: str = "Contents/section0.xml") -> bytes:
    stream = (FIXTURES / "section0.xml").read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, stream)
    return output.getvalue()


def hwpx_with_member(name: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", (FIXTURES / "section0.xml").read_bytes())
        archive.writestr(name, content)
    return output.getvalue()


def text_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 40 >> stream\nBT (Fixture PDF) Tj ET\nendstream endobj\n%%EOF"
    )


def one_pixel_png() -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        import binascii
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", binascii.crc32(kind + value) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b"")


def test_hwpx_paragraph_table_cell_and_provenance() -> None:
    source = hwpx_bytes()
    result = process_document(source, "application/hwp+zip", {"ocr": False})
    assert result["schema"] == "bidops.document-structure.v1"
    assert {block["type"] for block in result["blocks"]} == {"paragraph", "table", "table_cell"}
    assert any(block["attributes"].get("row") == 0 for block in result["blocks"])
    assert result.original_bytes == source
    assert result["extractor"]["upstream_commit"] == "96a2633f23a08f707679d7e212ebdc59948260e6"
    validate_structure(result)


def test_text_pdf_page_bbox() -> None:
    result = process_document(text_pdf(), "application/pdf", {"ocr": False})
    assert result["pages"][0]["width"] == 612
    assert result["blocks"][0]["bbox"] == [0.0, 0.0, 612.0, 792.0]
    assert result["blocks"][0]["text"] == "Fixture PDF"


def test_image_ocr_is_injected_and_confidence_is_bounded() -> None:
    # 1x1 PNG
    png = one_pixel_png()
    result = process_document(png, "image/png", {"ocr": True}, ocr_engine=lambda data, mime: {"text": "OCR", "confidence": 0.75})
    assert result["blocks"][0]["text"] == "OCR"
    assert result["blocks"][0]["confidence"] == 0.75


def test_ocr_unavailable_is_explicit_warning() -> None:
    png = one_pixel_png()
    result = DocumentProcessor().process(png, "image/png")
    assert "ocr_unavailable" in result["warnings"] or result["blocks"]


def test_clamav_unavailable_is_not_reported_as_clean() -> None:
    result = DocumentProcessor(clamav_checker=lambda data: None).process(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    assert "clamav_unavailable" in result["warnings"]
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: False).process(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "malware_detected"


def test_hwp_conversion_failure_preserves_source_and_blocks() -> None:
    hwp = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"invalid fixture"
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: True).process(hwp, "application/x-hwp", {"ocr": False})
    assert caught.value.code == "conversion_required"
    assert caught.value.blocking is True
    assert caught.value.source_preserved is True


def test_archive_bomb_and_oversize_input_are_blocked() -> None:
    bomb = hwpx_with_member("data.bin", b"A" * 100_000)
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(bomb, "application/hwp+zip", {"ocr": False, "max_archive_uncompressed_bytes": 10_000})
    assert caught.value.code in {"archive_size_limit", "archive_member_limit", "archive_ratio_limit"}
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(b"0" * (MAX_INPUT_BYTES + 1), "application/pdf", {"ocr": False})
    assert caught.value.code == "input_size_limit"


def test_nested_archive_magic_is_blocked_even_with_disguised_name() -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("inner.txt", b"nested")
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_with_member("notes.txt", nested.getvalue()), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "archive_depth_limit"

    tar_header = bytearray(512)
    tar_header[257:262] = b"ustar"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_with_member("notes.txt", bytes(tar_header)), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "archive_depth_limit"


def test_malformed_pdf_and_real_timeout_path() -> None:
    malformed = b"%PDF-1.4\n1 0 obj << /Type /Page /Contents 2 0 R >> endobj\n2 0 obj << /Length 3 >> stream\nabc\nendobj\n%%EOF"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(malformed, "application/pdf", {"ocr": False})
    assert caught.value.code == "malformed_pdf"

    # A trusted test-only converter executable sleeps after receiving the
    # internal source path.  The public bytes API never accepts this path.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "slow-converter"
        executable.write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
        executable.chmod(0o700)
        with pytest.raises(DocumentProcessingError) as caught:
            DocumentProcessor(node_executable=str(executable), clamav_checker=lambda data: True).process(
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1slow", "application/x-hwp", {"ocr": False, "timeout_seconds": 0.1}
            )
        assert caught.value.code == "conversion_required"
        assert caught.value.source_preserved is True


def test_boolean_bbox_and_confidence_are_not_numbers() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    bad_bbox = dict(result)
    bad_bbox["blocks"] = [dict(result["blocks"][0], bbox=[0, False, 1, 1])]
    with pytest.raises(DocumentProcessingError):
        validate_structure(bad_bbox)
    bad_confidence = dict(result)
    bad_confidence["blocks"] = [dict(result["blocks"][0], confidence=True)]
    with pytest.raises(DocumentProcessingError):
        validate_structure(bad_confidence)


def test_tiff_dimensions_use_distinct_width_and_height_tags() -> None:
    # Little-endian classic TIFF, two inline SHORT IFD entries: width=3,
    # height=5.  No image pixels are needed for dimension sniffing.
    header = b"II*\x00" + (8).to_bytes(4, "little")
    ifd = (2).to_bytes(2, "little")
    width = (256).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + (3).to_bytes(2, "little") + b"\x00\x00"
    height = (257).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + (5).to_bytes(2, "little") + b"\x00\x00"
    tiff = header + ifd + width + height + b"\x00\x00\x00\x00"
    result = process_document(tiff, "image/tiff", {"ocr": False})
    assert (result["pages"][0]["width"], result["pages"][0]["height"]) == (3.0, 5.0)


def test_hwp_fixture_converts_in_isolated_child_and_keeps_original() -> None:
    source = (FIXTURES / "labor_template.hwp").read_bytes()
    result = DocumentProcessor(clamav_checker=lambda data: True).process(source, "application/x-hwp", {"ocr": False})
    assert result.original_bytes == source
    assert result.converted_bytes and result.converted_bytes.startswith(b"PK")
    assert result["extractor"]["upstream_commit"] == "96a2633f23a08f707679d7e212ebdc59948260e6"


@pytest.mark.parametrize(
    ("content", "media_type", "code"),
    [
        (b"%PDF-1.4 /Encrypt", "application/pdf", "encrypted_pdf"),
        (b"not a document", "application/pdf", "mime_mismatch"),
        (hwpx_bytes(name="../escape.xml"), "application/hwp+zip", "archive_traversal"),
    ],
)
def test_safe_failure_modes(content: bytes, media_type: str, code: str) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(content, media_type, {"ocr": False})
    assert caught.value.code == code
    assert "/" not in caught.value.message
    assert "escape" not in caught.value.message


def test_limits_and_restricted_options() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_bytes(), "application/hwp+zip", {"output_path": "/tmp/out"})
    assert caught.value.code == "invalid_options"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_bytes(), "application/hwp+zip", {"timeout_seconds": 0.01})
    assert caught.value.code == "invalid_options"
    with pytest.raises(DocumentProcessingError):
        process_document("/tmp/input.hwpx", "application/hwp+zip")


def test_structure_rejects_additional_fields_and_cycles() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    extra = dict(result)
    extra["internal_path"] = "/quarantine/secret"
    with pytest.raises(DocumentProcessingError):
        validate_structure(extra)
    cyclic = dict(result)
    cyclic["blocks"] = [dict(cyclic["blocks"][0], parent_block_key=cyclic["blocks"][0]["block_key"])]
    with pytest.raises(DocumentProcessingError):
        validate_structure(cyclic)
