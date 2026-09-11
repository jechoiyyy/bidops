from __future__ import annotations

import io
import hashlib
import json
import os
import struct
import time
import uuid
import zipfile
import zlib
from pathlib import Path

import pytest

from app.deep_review.document_mcp import (
    MAX_INPUT_BYTES,
    DocumentProcessingError,
    DocumentProcessor,
    ProcessorOptions,
    process_document,
    validate_structure,
)
from app.deep_review.document_mcp import processor as processor_module
from app.deep_review.document_mcp.para_page_map import build_para_page_map
from app.deep_review.document_mcp import native as native_module
from app.deep_review.document_mcp.native import (
    RHWP_SCHEMA_VERSION,
    RHWP_STDOUT_LIMIT,
    NativeRhwpProcessor,
    parse_hwpx_manifest,
    parse_page_dump_manifest,
    parse_page_text_manifest,
    parse_pdf_manifest,
    parse_section_candidates_manifest,
)
from app.deep_review.document_mcp.native_artifacts import (
    validate_native_bundle,
    validate_section_candidates,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


def hwpx_bytes(*, name: str = "Contents/section0.xml") -> bytes:
    stream = (FIXTURES / "section0.xml").read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        # A pinned member timestamp keeps repeated calls byte-identical; the
        # default is the wall clock, whose 2-second ZIP granularity otherwise
        # makes two fixtures in one test differ.
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, stream)
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


def mixed_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 28 >> stream\nBT (Text page) Tj ET\nendstream endobj\n"
        b"5 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 6 0 R >> endobj\n"
        b"6 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n%%EOF"
    )


def blank_two_page_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n"
        b"5 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 6 0 R >> endobj\n"
        b"6 0 obj << /Length 8 >> stream\nBT ET\nendstream endobj\n%%EOF"
    )


def multi_stream_pdf() -> bytes:
    first = b"A" * 700
    second = b"B" * 700
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents [4 0 R 5 0 R] >> endobj\n"
        + b"4 0 obj << /Length " + str(len(first)).encode() + b" >> stream\n"
        + first + b"\nendstream endobj\n"
        + b"5 0 obj << /Length " + str(len(second)).encode() + b" >> stream\n"
        + second + b"\nendstream endobj\n%%EOF"
    )


def compressed_large_text_pdf() -> bytes:
    content = zlib.compress(b"BT (" + b"A" * 2_000_000 + b") Tj ET")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
        + b"4 0 obj << /Filter /FlateDecode >> stream\n"
        + content
        + b"\nendstream endobj\n%%EOF"
    )


def hwpx_xml(raw: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", raw)
    return output.getvalue()


def one_pixel_png() -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        import binascii
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", binascii.crc32(kind + value) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b"")


def rhwp_envelope(**fields: object) -> bytes:
    return json.dumps({
        "schemaVersion": RHWP_SCHEMA_VERSION,
        "source": "source.hwp",
        "untrustedContent": False,
        "untrustedFields": [],
        **fields,
    }).encode()


def native_text_manifest(pages: list[dict[str, object]], **fields: object) -> bytes:
    return rhwp_envelope(
        untrustedContent=True,
        untrustedFields=["pages[].text"],
        pageCount=len(pages),
        omittedCount=0,
        truncated=False,
        pages=pages,
        **fields,
    )


def native_dump_manifest(pages: list[dict[str, object]], *, page_count: int | None = None) -> bytes:
    return rhwp_envelope(
        untrustedContent=True,
        untrustedFields=["pages[].columns[].items[].textPreview"],
        pageCount=len(pages) if page_count is None else page_count,
        pageFilter=None,
        respectVposReset=True,
        pages=pages,
    )


def native_digest_manifest(sections: list[dict[str, object]], *, page_count: int = 1, **fields: object) -> bytes:
    envelope: dict[str, object] = {
        "untrustedContent": True,
        "untrustedFields": ["sections[].excerpt"],
        "format": "hwpx",
        "pageCount": page_count,
        "paraCount": len(sections),
        "sectionsMode": "clause",
        "sectionCount": len(sections),
        # The real envelope reports truncated excerpts; that flag is dropped.
        "truncated": True,
        "nextStep": "절 원문은 export-text --json -p <쪽>",
        "sections": sections,
    }
    envelope.update(fields)
    return rhwp_envelope(**envelope)


def digest_section(page: int, title: str = "Ⅰ. 사업 개요", chars: int = 12) -> dict[str, object]:
    return {"title": title, "page": page, "charCount": chars, "excerpt": "must-drop"}


def dump_page(index: int) -> dict[str, object]:
    return {
        "pageIndex": index,
        "pageNumber": 1,
        "displayPage": index + 1,
        "section": 0,
        "columns": [],
        "extras": [],
    }


def test_native_manifests_accept_actual_v086_types_and_strip_preview() -> None:
    hwpx = b"PK\x03\x04verified"
    verify = parse_hwpx_manifest(rhwp_envelope(
        format="hwpx", output="converted.hwpx", bytes=len(hwpx), passwordProtected=False,
        verify={"diffCount": 0, "identical": True},
        verifyPages={"before": 1, "after": 1, "identical": True},
    ), hwpx)
    pdf = b"%PDF-safe"
    assert verify["pages"]["before"] == 1
    assert parse_pdf_manifest(rhwp_envelope(
        format="pdf", backend="svg", output="output.pdf", bytes=len(pdf),
        pageCount=1, renderedCount=1,
    ), pdf) == 1
    page_text = parse_page_text_manifest(native_text_manifest([{"page": 0, "text": "safe fixture"}]), 1)
    dump = parse_page_dump_manifest(rhwp_envelope(
        untrustedContent=True,
        untrustedFields=["pages[].columns[].items[].textPreview"],
        pageCount=1,
        pageFilter=None,
        respectVposReset=True,
        pages=[{
            "pageIndex": 0, "pageNumber": 9, "displayPage": 7, "section": 2,
            "columns": [{"items": [{"kind": "fullParagraph", "paraIndex": 4, "isEndnote": False, "textPreview": "must-drop", "height": {}}]}],
            "extras": [{"kind": "hiddenEmptyPara", "paraIndex": 5, "textPreview": "must-drop"}],
        }],
    ), 1)

    assert page_text["pages"][0]["number"] == 1
    assert dump["pages"][0]["columns"][0]["items"] == [{"kind": "fullParagraph", "paraIndex": 4, "isEndnote": False}]
    assert dump["pages"][0]["extras"] == [{"kind": "hiddenEmptyPara", "paraIndex": 5}]
    assert "textPreview" not in json.dumps(dump)


@pytest.mark.parametrize(
    ("manifest", "expected_code"),
    [
        (native_text_manifest([{"page": 0, "text": ""}]), "pdf_empty_text"),
        (native_text_manifest([{"page": 0, "text": "a"}, {"page": 0, "text": "b"}]), "rhwp_manifest_invalid"),
        (native_text_manifest([{"page": 1, "text": "a"}]), "rhwp_manifest_invalid"),
        (native_text_manifest([{"page": 0, "text": "a", "truncated": True, "omittedCount": 1}]), "rhwp_manifest_invalid"),
        (native_text_manifest([{"page": True, "text": "a"}]), "rhwp_manifest_invalid"),
        (rhwp_envelope(pageCount=1, omittedCount=0, truncated=False, pages=[{"page": 0, "text": "a"}]), "rhwp_manifest_invalid"),
    ],
)
def test_native_page_text_rejects_empty_duplicate_missing_truncated_and_wrong_types(
    manifest: bytes,
    expected_code: str,
) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        parse_page_text_manifest(manifest, 1 if b'"pageCount": 1' in manifest else 2)
    assert caught.value.code == expected_code


def test_native_page_text_defaults_missing_top_level_truncated_but_keeps_required_omitted_count() -> None:
    manifest = json.loads(native_text_manifest([{"page": 0, "text": "safe fixture"}]).decode())
    manifest.pop("truncated")
    parsed = parse_page_text_manifest(json.dumps(manifest).encode(), 1)
    assert parsed["pages"][0]["text"] == "safe fixture"

    malformed_truncated = dict(manifest, truncated=None)
    with pytest.raises(DocumentProcessingError) as caught:
        parse_page_text_manifest(json.dumps(malformed_truncated).encode(), 1)
    assert caught.value.code == "rhwp_manifest_invalid"

    missing_omitted_count = dict(manifest)
    missing_omitted_count.pop("omittedCount")
    with pytest.raises(DocumentProcessingError) as caught:
        parse_page_text_manifest(json.dumps(missing_omitted_count).encode(), 1)
    assert caught.value.code == "rhwp_manifest_invalid"


def test_native_page_text_rejects_lone_unicode_surrogate_safely() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        parse_page_text_manifest(native_text_manifest([{"page": 0, "text": "\ud800"}]), 1)
    assert caught.value.code == "rhwp_manifest_invalid"
    assert "surrogate" not in caught.value.message


def test_native_verify_and_page_count_fail_closed() -> None:
    hwpx = b"PK\x03\x04verified"
    with pytest.raises(DocumentProcessingError) as verify_error:
        parse_hwpx_manifest(rhwp_envelope(
            format="hwpx", output="converted.hwpx", bytes=len(hwpx), passwordProtected=False,
            verify={"diffCount": 1, "identical": False},
            verifyPages={"before": 1, "after": 1, "identical": True},
        ), hwpx)
    assert verify_error.value.code == "hwpx_verify_failed"

    with pytest.raises(DocumentProcessingError) as page_error:
        parse_pdf_manifest(rhwp_envelope(
            format="pdf", backend="svg", output="output.pdf", bytes=9,
            pageCount=2, renderedCount=1,
        ), b"%PDF-safe")
    assert page_error.value.code == "pdf_page_mismatch"


@pytest.mark.parametrize(
    "pages",
    [
        [dump_page(0), dump_page(0)],
        [dump_page(0)],
        [dump_page(0), dump_page(2)],
    ],
)
def test_native_dump_rejects_duplicate_missing_and_out_of_range_page_ids(
    pages: list[dict[str, object]],
) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        parse_page_dump_manifest(native_dump_manifest(pages, page_count=2), 2)
    assert caught.value.code in {"rhwp_manifest_invalid", "pdf_page_mismatch"}


def test_native_manifest_rejects_wrong_schema_size_and_magic() -> None:
    wrong_version = json.loads(rhwp_envelope(format="pdf").decode())
    wrong_version["schemaVersion"] = 1.0
    with pytest.raises(DocumentProcessingError) as schema_error:
        parse_pdf_manifest(json.dumps(wrong_version).encode(), b"%PDF-safe")
    assert schema_error.value.code == "rhwp_manifest_invalid"

    with pytest.raises(DocumentProcessingError) as artifact_error:
        parse_pdf_manifest(rhwp_envelope(
            format="pdf", backend="svg", output="output.pdf", bytes=9,
            pageCount=1, renderedCount=1,
        ), b"not-a-pdf")
    assert artifact_error.value.code == "rhwp_manifest_invalid"


@pytest.mark.parametrize("renderer", [[], {}, None, 1])
def test_native_renderer_rejects_non_string_selection_without_type_error(renderer: object) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        ProcessorOptions.from_mapping({"renderer": renderer})
    assert caught.value.code == "invalid_options"


def test_native_dump_drops_endnote_separator_and_rejects_unknown_or_malformed_items() -> None:
    page = dump_page(0)
    page["columns"] = [{"items": [
        {"kind": "endnoteSeparator", "separatorLength": 1, "marginAbove": 2, "marginBelow": 3, "lineWidth": 4, "color": "#000000"},
        *({"kind": kind, "paraIndex": index, "isEndnote": False} for index, kind in enumerate((
            "fullParagraph", "partialParagraph", "table", "partialTable", "shape",
        ), start=1)),
    ]}]
    sanitized = parse_page_dump_manifest(native_dump_manifest([page]), 1)
    assert [item["kind"] for item in sanitized["pages"][0]["columns"][0]["items"]] == [
        "fullParagraph", "partialParagraph", "table", "partialTable", "shape",
    ]

    for malformed in (
        {"kind": "unknown", "paraIndex": 0, "isEndnote": False},
        {"kind": "fullParagraph", "isEndnote": False},
        {"kind": "fullParagraph", "paraIndex": 0},
    ):
        bad_page = dump_page(0)
        bad_page["columns"] = [{"items": [malformed]}]
        with pytest.raises(DocumentProcessingError) as caught:
            parse_page_dump_manifest(native_dump_manifest([bad_page]), 1)
        assert caught.value.code == "rhwp_manifest_invalid"


def test_native_renderer_requires_explicit_validated_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    source = hwpx_bytes()
    structure_only = DocumentProcessor().process(source, "application/hwp+zip", {"ocr": False})
    assert structure_only.converted_pdf_bytes is None
    assert structure_only.page_text == {}
    assert structure_only.para_page_map == {}
    assert structure_only.para_page_map_bytes is None
    assert structure_only.section_candidates == {}
    assert structure_only.section_candidates_bytes is None

    native = DocumentProcessor()
    structure = process_document(source, "application/hwp+zip", {"ocr": False})
    monkeypatch.setattr(native, "_process_native", lambda *_args, **_kwargs: {
        "pages": structure["pages"], "blocks": structure["blocks"], "warnings": [],
        "converted": None, "verify": None, "pdf": b"%PDF-safe",
        "pdf_metadata": {"renderer": "rhwp-svg-pdf"},
        "page_text": {"schema": "bidops.rhwp-page-text.v1", "page_count": 1, "pages": []},
        "page_dump": {"schemaVersion": "1.0", "pageCount": 1, "pages": []},
        "para_page_map": {"schema": "bidops.para-page-map.v1"},
        "para_page_map_bytes": b'{"schema":"bidops.para-page-map.v1"}',
        "section_candidates": {"schema": "bidops.section-candidates.v1"},
        "section_candidates_bytes": b'{"schema":"bidops.section-candidates.v1"}',
    })
    opted_in = native.process(source, "application/hwp+zip", {"ocr": False, "prepare_pdf": True, "renderer": "rhwp-svg-pdf"})
    assert opted_in["blocks"] == structure["blocks"]
    assert opted_in.converted_pdf_bytes == b"%PDF-safe"
    assert opted_in.hwpx_bytes == source
    assert opted_in.para_page_map == {"schema": "bidops.para-page-map.v1"}
    assert opted_in.para_page_map_bytes == b'{"schema":"bidops.para-page-map.v1"}'
    assert opted_in.section_candidates_bytes == b'{"schema":"bidops.section-candidates.v1"}'
    assert "para_page_map" not in dict(opted_in) and "section_candidates" not in dict(opted_in)
    with pytest.raises(DocumentProcessingError) as invalid:
        ProcessorOptions.from_mapping({"renderer": "native-or-fallback"})
    assert invalid.value.code == "invalid_options"


def test_removed_canvas_renderer_option_is_rejected() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        ProcessorOptions.from_mapping({"renderer": "rhwp-canvas-chromium"})
    assert caught.value.code == "invalid_options"


def test_processor_does_not_look_up_node_or_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    looked_up: list[str] = []
    monkeypatch.setattr(processor_module.shutil, "which", lambda name: looked_up.append(name) or None)

    processor = DocumentProcessor()

    assert looked_up == []
    assert not hasattr(processor, "node_executable")
    assert not hasattr(processor, "chromium_executable")
    assert processor.rhwp_executable.endswith("vendor/rhwp/bin/rhwp")


def test_native_command_uses_one_mib_stdout_and_ordinary_limiter(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def run(_command: list[str], **kwargs: object) -> tuple[int, bytes, bytes]:
        calls.append(kwargs)
        return 0, rhwp_envelope(format="pdf"), b""

    limiter_result = object()
    adapter = NativeRhwpProcessor(
        "/bin/true",
        run=run,
        limiter=lambda size: (size, limiter_result),
        child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    adapter._call(["export-pdf"], tmp_path, ProcessorOptions(timeout_seconds=1), time.monotonic() + 1)
    assert calls[0]["output_limit"] == RHWP_STDOUT_LIMIT
    assert calls[0]["preexec_fn"] == (20 * 1024 * 1024, limiter_result)


def test_native_page_text_budget_is_checked_after_display_metadata_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    text = {
        "schema": "bidops.rhwp-page-text.v1",
        "page_count": 1,
        "pages": [{"number": 1, "text": "x" * 2048, "text_sha256": "0" * 64}],
    }
    dump = {
        "schemaVersion": RHWP_SCHEMA_VERSION,
        "pageCount": 1,
        "pages": [{"pageIndex": 0, "displayPage": 1, "section": 0, "columns": [], "extras": []}],
    }

    def artifact_size(value: dict[str, object]) -> int:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    un_enriched_size = artifact_size(text)
    enriched = json.loads(json.dumps(text))
    enriched["pages"][0].update({"display_page": 1, "section": 0})
    assert artifact_size(enriched) > max(un_enriched_size, artifact_size(dump))
    max_output_bytes = max(un_enriched_size, artifact_size(dump))

    monkeypatch.setattr(native_module, "extract_hwpx", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(native_module, "extract_pdf", lambda *_args: ([], [], [], []))
    monkeypatch.setattr(native_module, "parse_pdf_manifest", lambda *_args: 1)
    monkeypatch.setattr(native_module, "parse_page_text_manifest", lambda *_args: text)
    monkeypatch.setattr(native_module, "parse_page_dump_manifest", lambda *_args: dump)
    adapter = NativeRhwpProcessor(
        "/bin/true",
        run=lambda *_args, **_kwargs: (0, b"", b""),
        limiter=lambda _size: None,
        child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    monkeypatch.setattr(adapter, "_fingerprint_binary", lambda: "0" * 64)
    monkeypatch.setattr(adapter, "_call", lambda *_args, **_kwargs: b"")
    monkeypatch.setattr(adapter, "_read_artifact", lambda *_args, **_kwargs: b"%PDF-safe")
    monkeypatch.setattr(adapter, "_pdfinfo_pages", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(adapter, "_version", lambda *_args, **_kwargs: "0.8.6")

    with pytest.raises(DocumentProcessingError) as caught:
        adapter.process(
            hwpx_bytes(),
            "application/hwp+zip",
            ProcessorOptions(prepare_pdf=True, max_output_bytes=max_output_bytes),
            time.monotonic() + 1,
        )
    assert caught.value.code == "output_size_limit"


@pytest.mark.parametrize(
    ("digest_stdout", "expected_warning", "expected_candidates"),
    [
        (b"not-json", "section_candidates_unavailable", False),
        (
            native_digest_manifest([digest_section(0)], sectionCount=2, truncated=True),
            "section_candidates_incomplete",
            True,
        ),
    ],
)
def test_optional_section_candidate_failure_or_partial_result_keeps_verified_core_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    digest_stdout: bytes,
    expected_warning: str,
    expected_candidates: bool,
) -> None:
    text = {
        "schema": "bidops.rhwp-page-text.v1",
        "page_count": 1,
        "pages": [{"number": 1, "text": "verified", "text_sha256": hashlib.sha256(b"verified").hexdigest()}],
    }
    dump = {
        "schemaVersion": RHWP_SCHEMA_VERSION,
        "pageCount": 1,
        "pages": [{"pageIndex": 0, "displayPage": 1, "section": 0, "columns": [], "extras": []}],
    }
    monkeypatch.setattr(native_module, "extract_hwpx", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(native_module, "extract_pdf", lambda *_args: ([], [], [], []))
    monkeypatch.setattr(native_module, "parse_pdf_manifest", lambda *_args: 1)
    monkeypatch.setattr(native_module, "parse_page_text_manifest", lambda *_args: text)
    monkeypatch.setattr(native_module, "parse_page_dump_manifest", lambda *_args: dump)
    adapter = NativeRhwpProcessor(
        "/bin/true",
        run=lambda *_args, **_kwargs: (0, b"", b""),
        limiter=lambda _size: None,
        child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    monkeypatch.setattr(adapter, "_fingerprint_binary", lambda: "0" * 64)
    monkeypatch.setattr(
        adapter,
        "_call",
        lambda arguments, *_args, **_kwargs: digest_stdout if arguments[0] == "digest" else b"",
    )
    monkeypatch.setattr(adapter, "_read_artifact", lambda *_args, **_kwargs: b"%PDF-safe")
    monkeypatch.setattr(adapter, "_pdfinfo_pages", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(adapter, "_version", lambda *_args, **_kwargs: "0.8.6")

    result = adapter.process(
        hwpx_bytes(),
        "application/hwp+zip",
        ProcessorOptions(prepare_pdf=True),
        time.monotonic() + 10,
    )

    assert result["pdf"] == b"%PDF-safe"
    assert result["page_text"]["pages"][0]["text"] == "verified"
    assert expected_warning in result["warnings"]
    assert bool(result["section_candidates"]) is expected_candidates
    assert bool(result["section_candidates_bytes"]) is expected_candidates


def test_core_page_text_failure_is_not_downgraded_to_an_optional_candidate_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(native_module, "extract_hwpx", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(native_module, "extract_pdf", lambda *_args: ([], [], [], []))
    monkeypatch.setattr(native_module, "parse_pdf_manifest", lambda *_args: 1)

    def fail_page_text(*_args: object) -> dict[str, object]:
        raise DocumentProcessingError("pdf_page_mismatch", "safe", source_preserved=True)

    monkeypatch.setattr(native_module, "parse_page_text_manifest", fail_page_text)
    adapter = NativeRhwpProcessor(
        "/bin/true",
        run=lambda *_args, **_kwargs: (0, b"", b""),
        limiter=lambda _size: None,
        child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    monkeypatch.setattr(adapter, "_fingerprint_binary", lambda: "0" * 64)
    monkeypatch.setattr(adapter, "_call", lambda *_args, **_kwargs: b"")
    monkeypatch.setattr(adapter, "_read_artifact", lambda *_args, **_kwargs: b"%PDF-safe")
    monkeypatch.setattr(adapter, "_pdfinfo_pages", lambda *_args, **_kwargs: 1)

    with pytest.raises(DocumentProcessingError) as caught:
        adapter.process(
            hwpx_bytes(),
            "application/hwp+zip",
            ProcessorOptions(prepare_pdf=True),
            time.monotonic() + 10,
        )
    assert caught.value.code == "pdf_page_mismatch"


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [(processor_module._ChildTimeout, "timeout"), (processor_module._ChildOutputLimit, "output_size_limit")],
)
def test_native_command_maps_bounded_failures_to_safe_codes(
    tmp_path: Path,
    error_type: type[BaseException],
    expected_code: str,
) -> None:
    def run(*_args: object, **_kwargs: object) -> tuple[int, bytes, bytes]:
        raise error_type

    adapter = NativeRhwpProcessor(
        "/bin/true", run=run, limiter=lambda _size: None,
        child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    with pytest.raises(DocumentProcessingError) as caught:
        adapter._call(["export-text"], tmp_path, ProcessorOptions(timeout_seconds=1), time.monotonic() + 1)
    assert caught.value.code == expected_code


def test_native_nonzero_encrypted_error_is_safely_classified(tmp_path: Path) -> None:
    adapter = NativeRhwpProcessor(
        "/bin/true", run=lambda *_args, **_kwargs: (1, b"", b"encrypted document"),
        limiter=lambda _size: None, child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    with pytest.raises(DocumentProcessingError) as caught:
        adapter._call(["export-text"], tmp_path, ProcessorOptions(timeout_seconds=1), time.monotonic() + 1)
    assert caught.value.code == "encrypted_document"
    assert "encrypted" not in caught.value.message


def test_native_artifact_reader_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"%PDF-safe")
    link = tmp_path / "output.pdf"
    link.symlink_to(target)
    adapter = NativeRhwpProcessor(
        "/bin/true", run=lambda *_args, **_kwargs: (0, b"", b""),
        limiter=lambda _size: None, child_environment=lambda _path: {},
        timeout_error=processor_module._ChildTimeout,
        output_error=processor_module._ChildOutputLimit,
        font_manifest=lambda _options, _deadline: "0" * 64,
    )
    with pytest.raises(DocumentProcessingError) as caught:
        adapter._read_artifact(link, ProcessorOptions())
    assert caught.value.code == "conversion_required"


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


def test_control_heavy_stdlib_pdf_text_uses_bounded_poppler_fallback(monkeypatch) -> None:
    processor = DocumentProcessor()
    fallback = (
        [{"number": 1, "width": 612.0, "height": 792.0, "image_content_object_id": None}],
        [{
            "block_key": "page-1-text", "parent_block_key": None, "type": "text", "page": 1,
            "bbox": [0.0, 0.0, 612.0, 792.0], "text": "정상 공고문", "confidence": 1.0,
            "attributes": {"source": "pdf-poppler-text"},
        }],
        [],
        [],
    )
    monkeypatch.setattr(
        "app.deep_review.document_mcp.processor.extract_pdf",
        lambda _data, _options: (
            fallback[0],
            [{**fallback[1][0], "text": "binary\x01font\x9cstream"}],
            [],
            [],
        ),
    )
    monkeypatch.setattr(processor, "_extract_pdf_poppler", lambda _data, _options: fallback)

    result = processor.process(text_pdf(), "application/pdf", {"ocr": False})

    assert result["extractor"]["name"] == "pdf-poppler-fallback"
    assert result["blocks"][0]["text"] == "정상 공고문"
    assert "pdf_stdlib_text_fallback" in result["warnings"]


def test_prepare_pdf_uses_poppler_even_when_stdlib_returns_nonempty_glyphs(monkeypatch) -> None:
    processor = DocumentProcessor()
    poppler = (
        [{"number": 1, "width": 612.0, "height": 792.0, "image_content_object_id": None}],
        [{
            "block_key": "page-1-text", "parent_block_key": None, "type": "text", "page": 1,
            "bbox": [0.0, 0.0, 612.0, 792.0], "text": "정본 PDF 본문", "confidence": 1.0,
            "attributes": {"source": "pdf-poppler-text"},
        }],
        [],
        [],
    )
    monkeypatch.setattr(
        "app.deep_review.document_mcp.processor.extract_pdf",
        lambda _data, _options: (
            poppler[0],
            [{**poppler[1][0], "text": "\ue000\ue001\ue002"}],
            [],
            [],
        ),
    )
    monkeypatch.setattr(
        processor,
        "_extract_pdf_poppler",
        lambda _data, _options, *, deadline=None: poppler,
    )

    result = processor.process(text_pdf(), "application/pdf", {"ocr": False, "prepare_pdf": True})

    assert result["extractor"]["name"] == "pdf-poppler-prepared"
    assert result["blocks"][0]["text"] == "정본 PDF 본문"
    assert "pdf_poppler_text_fallback" in result["warnings"]


def test_prepare_pdf_keeps_the_existing_object_budget() -> None:
    assert ProcessorOptions.from_mapping({"ocr": False}).max_pdf_objects == 4096
    assert ProcessorOptions.from_mapping({"ocr": False, "prepare_pdf": True}).max_pdf_objects == 4096
    assert ProcessorOptions.from_mapping(ProcessorOptions(prepare_pdf=True)).max_pdf_objects == 4096
    assert ProcessorOptions.from_mapping({
        "ocr": False, "prepare_pdf": True, "max_pdf_objects": 4096,
    }).max_pdf_objects == 4096
    assert ProcessorOptions.from_mapping({
        "ocr": False, "prepare_pdf": True, "max_pdf_objects": 10_000,
    }).max_pdf_objects == 10_000
    assert ProcessorOptions.from_mapping({
        "ocr": False, "prepare_pdf": True, "max_pdf_objects": 10_001,
    }).max_pdf_objects == 10_001
    with pytest.raises(DocumentProcessingError) as caught:
        ProcessorOptions.from_mapping({"ocr": False, "prepare_pdf": True, "max_pdf_objects": 100_001})
    assert caught.value.code == "invalid_options"


def test_font_manifest_changes_when_same_path_bytes_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    font = tmp_path / "trusted-font.ttf"
    font.write_bytes(b"font-v1")
    fc_list = tmp_path / "fc-list"
    fc_list.write_text(f'#!/bin/sh\nprintf \'%s: Family\\n\' "{font}"\n', encoding="utf-8")
    fc_list.chmod(0o700)
    monkeypatch.setattr(processor_module.shutil, "which", lambda name: str(fc_list) if name == "fc-list" else None)

    first = processor_module._font_manifest_sha256(ProcessorOptions(ocr=False), None)
    font.write_bytes(b"font-v2")
    second = processor_module._font_manifest_sha256(ProcessorOptions(ocr=False), None)
    assert first != second


def test_pdf_object_limit_does_not_fallback_to_success(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = DocumentProcessor()

    def object_limited(_data: bytes, _options: ProcessorOptions) -> tuple[object, ...]:
        raise DocumentProcessingError("pdf_object_limit", "object limit")

    monkeypatch.setattr("app.deep_review.document_mcp.processor.extract_pdf", object_limited)
    monkeypatch.setattr(
        processor,
        "_extract_pdf_poppler",
        lambda _data, _options: pytest.fail("object limit must not use the fallback"),
    )

    with pytest.raises(DocumentProcessingError) as caught:
        processor.process(
            text_pdf(),
            "application/pdf",
            {"ocr": False, "prepare_pdf": True, "max_pdf_objects": 4096},
        )
    assert caught.value.code == "pdf_object_limit"


def test_pdf_decoded_output_limit_rejects_compressed_two_megabyte_payload() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(compressed_large_text_pdf(), "application/pdf", {"ocr": False, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_decoded_output_limit_is_aggregate_across_content_streams() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(multi_stream_pdf(), "application/pdf", {"ocr": False, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_rendered_page_bytes_are_aggregate_before_retaining_pages() -> None:
    processor = DocumentProcessor()
    processor._render_pdf_page = lambda _original, _page, _options: b"x" * 700  # type: ignore[method-assign]
    with pytest.raises(DocumentProcessingError) as caught:
        processor.process(mixed_pdf(), "application/pdf", {"ocr": False, "render_pages": True, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_pdf_ocr_text_is_aggregate_across_pages_before_appending_blocks() -> None:
    processor = DocumentProcessor(ocr_engine=lambda _data, _mime: "x" * 700)
    processor._render_pdf_page = lambda _original, _page, _options: b"rendered"  # type: ignore[method-assign]
    with pytest.raises(DocumentProcessingError) as caught:
        processor.process(blank_two_page_pdf(), "application/pdf", {"ocr": True, "max_output_bytes": 1024})
    assert caught.value.code == "output_size_limit"


def test_subprocess_output_limit_is_aggregate_across_stdout_and_stderr() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        executable = Path(temporary) / "mixed-noise-converter"
        executable.write_text(
            "#!/bin/sh\n"
            "i=0\n"
            "while [ $i -lt 700 ]; do printf x; i=$((i + 1)); done\n"
            "i=0\n"
            "while [ $i -lt 700 ]; do printf x >&2; i=$((i + 1)); done\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        with pytest.raises(processor_module._ChildOutputLimit):
            processor_module._run_limited_subprocess(
                [str(executable)],
                cwd=temporary,
                env=processor_module._child_environment(str(executable)),
                timeout=5.0,
                output_limit=1024,
            )


def test_mixed_pdf_ocr_targets_only_pages_without_extractable_text() -> None:
    calls: list[str] = []
    processor = DocumentProcessor(
        ocr_engine=lambda _data, mime: calls.append(mime) or {"text": "OCR page", "confidence": 0.8}
    )
    processor._render_pdf_page = lambda _original, _page, _options: one_pixel_png()  # type: ignore[method-assign]
    result = processor.process(mixed_pdf(), "application/pdf", {"ocr": True})
    assert calls == ["image/png"]
    assert [block["page"] for block in result["blocks"] if block["type"] == "ocr_text"] == [2]
    assert not any(block["type"] == "ocr_text" and block["page"] == 1 for block in result["blocks"])


def test_mixed_pdf_without_renderer_is_explicitly_needs_review() -> None:
    processor = DocumentProcessor()

    def unavailable(_original: bytes, _page: int, _options: ProcessorOptions) -> bytes:
        raise DocumentProcessingError("renderer_unavailable", "renderer unavailable")

    processor._render_pdf_page = unavailable  # type: ignore[method-assign]
    result = processor.process(mixed_pdf(), "application/pdf", {"ocr": True})
    assert "needs_review" in result["warnings"]
    assert "ocr_unavailable" in result["warnings"]
    assert not any(block["type"] == "ocr_text" for block in result["blocks"])


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


def test_prepare_pdf_reuses_hwpx_archive_boundary_before_rhwp(monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = hwpx_with_member("data.bin", b"A" * 100_000)

    def unexpected_renderer(*args: object, **kwargs: object) -> None:
        raise AssertionError("rhwp must not receive an archive that failed validation")

    monkeypatch.setattr(native_module.NativeRhwpProcessor, "_call", unexpected_renderer)
    with pytest.raises(DocumentProcessingError) as caught:
        DocumentProcessor(clamav_checker=lambda data: True).process(
            bomb,
            "application/hwp+zip",
            {"ocr": False, "prepare_pdf": True, "max_archive_uncompressed_bytes": 10_000},
        )
    assert caught.value.code in {"archive_size_limit", "archive_member_limit", "archive_ratio_limit"}
    assert caught.value.source_preserved is True


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
            DocumentProcessor(rhwp_executable=str(executable), clamav_checker=lambda data: True).process(
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


def test_structure_rejects_naive_page_and_unapproved_provenance() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})

    naive = dict(result)
    naive["created_at"] = "2026-08-25T00:00:00"
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(naive)
    assert caught.value.code == "invalid_structure"

    bool_page = dict(result)
    bool_page["blocks"] = [dict(result["blocks"][0], page=True)]
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(bool_page)
    assert caught.value.code == "invalid_structure"

    unknown_commit = dict(result)
    unknown_commit["extractor"] = dict(result["extractor"], upstream_commit="0" * 40)
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(unknown_commit)
    assert caught.value.code == "invalid_structure"


def test_hwpx_xml_entity_and_depth_limits_fail_closed() -> None:
    entity_xml = b'<!DOCTYPE root [<!ENTITY x "unsafe">]><root>&x;</root>'
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_xml(entity_xml), "application/hwp+zip", {"ocr": False})
    assert caught.value.code == "unsafe_xml"

    deep_xml = b"<root>" + b"<a>" * 16 + b"x" + b"</a>" * 16 + b"</root>"
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(hwpx_xml(deep_xml), "application/hwp+zip", {"ocr": False, "max_xml_depth": 8})
    assert caught.value.code == "xml_depth_limit"


def test_injected_ocr_output_limit_is_enforced() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        process_document(
            one_pixel_png(),
            "image/png",
            {"ocr": True, "max_output_bytes": 1024},
            ocr_engine=lambda _data, _mime: "A" * 2048,
        )
    assert caught.value.code == "output_size_limit"


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


def test_structure_rejects_payload_page_and_block_counts_above_defaults() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})

    too_many_pages = dict(result)
    too_many_pages["pages"] = [dict(result["pages"][0], number=number) for number in range(1, 514)]
    too_many_pages["blocks"] = []
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(too_many_pages)
    assert caught.value.code == "page_limit"

    too_many_blocks = dict(result)
    too_many_blocks["blocks"] = [result["blocks"][0]] * 100_001
    with pytest.raises(DocumentProcessingError) as caught:
        validate_structure(too_many_blocks)
    assert caught.value.code == "block_limit"


def test_structure_large_parent_chain_is_linear_and_bounded() -> None:
    result = process_document(hwpx_bytes(), "application/hwp+zip", {"ocr": False})
    blocks: list[dict[str, object]] = []
    for index in range(12_000):
        blocks.append({
            "block_key": f"chain-{index}",
            "parent_block_key": f"chain-{index - 1}" if index else None,
            "type": "paragraph",
            "page": 1,
            "bbox": None,
            "text": "",
            "confidence": None,
            "attributes": {},
        })
    payload = dict(result)
    payload["blocks"] = blocks
    started = time.monotonic()
    validate_structure(payload)
    assert time.monotonic() - started < 2.0


def test_vendored_sha256_manifest_is_deterministic_and_complete() -> None:
    vendor = Path(__file__).parents[2] / "app" / "deep_review" / "document_mcp" / "vendor"
    manifest = vendor / "SHA256SUMS"
    contents = manifest.read_text(encoding="utf-8")
    assert "hwpx-skill.git" in contents
    assert "96a2633f23a08f707679d7e212ebdc59948260e6" in contents
    assert "edwardkim/rhwp" in contents
    entries = [line.split(maxsplit=1) for line in contents.splitlines() if line and not line.startswith("#")]
    assert entries == sorted(entries, key=lambda item: item[1])
    assert all(len(digest) == 64 and path != "SHA256SUMS" for digest, path in entries)
    for digest, relative_path in entries:
        path = vendor / relative_path
        assert path.is_file(), relative_path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_native_section_candidates_accept_outline_rebase_pages_cap_titles_and_drop_untrusted_text() -> None:
    long_title = "가" * 350
    candidates = parse_section_candidates_manifest(
        native_digest_manifest(
            [digest_section(0), digest_section(24, long_title, 0), digest_section(78, "  제\t3장   범위\n", 7)],
            page_count=79,
            sectionsMode="outline",
        ),
        79,
    )

    assert candidates["schema"] == "bidops.section-candidates.v2"
    assert candidates["mode"] == "outline"
    assert candidates["page_count"] == 79 and candidates["section_count"] == 3
    assert candidates["returned_count"] == 3 and candidates["truncated"] is True
    assert candidates["candidates_truncated"] is False
    assert [(item["index"], item["page"]) for item in candidates["sections"]] == [(0, 1), (1, 25), (2, 79)]
    assert candidates["sections"][1]["title"] == "가" * 300 and candidates["sections"][1]["truncated"] is True
    # Whitespace is normalised before the 300-character cap is applied.
    assert candidates["sections"][2]["title"] == "제 3장 범위" and candidates["sections"][2]["truncated"] is False
    assert candidates["sections"][0] == {"index": 0, "title": "Ⅰ. 사업 개요", "page": 1, "char_count": 12, "truncated": False}
    serialized = json.dumps(candidates, ensure_ascii=False)
    assert "must-drop" not in serialized and "nextStep" not in serialized and "untrusted" not in serialized
    assert "excerpt" not in serialized and "source" not in serialized


def test_native_section_candidates_accept_an_empty_page_mode_result() -> None:
    candidates = parse_section_candidates_manifest(
        native_digest_manifest([], sectionsMode="page"), 1,
    )
    assert candidates == {
        "schema": "bidops.section-candidates.v2", "page_count": 1, "mode": "page",
        "section_count": 0, "returned_count": 0, "truncated": True,
        "candidates_truncated": False, "sections": [],
    }


def test_native_section_candidates_preserve_total_when_rhwp_returns_a_truncated_prefix() -> None:
    candidates = parse_section_candidates_manifest(
        native_digest_manifest(
            [digest_section(index % 10, title=f"절 {index}") for index in range(50)],
            page_count=10,
            sectionCount=67,
            truncated=True,
        ),
        10,
    )

    assert candidates["schema"] == "bidops.section-candidates.v2"
    assert candidates["section_count"] == 67
    assert candidates["returned_count"] == 50
    assert candidates["truncated"] is True
    assert candidates["candidates_truncated"] is True
    assert len(candidates["sections"]) == 50


@pytest.mark.parametrize(
    ("manifest", "expected_pages", "expected_code"),
    [
        (native_digest_manifest([digest_section(0)], sectionsMode=None), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(i % 79) for i in range(2001)], page_count=79), 79, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(1)], page_count=1), 1, "section_candidates_invalid"),
        (native_digest_manifest([{"title": "t", "page": 0}]), 1, "section_candidates_invalid"),
        (native_digest_manifest([dict(digest_section(0), extra=1)]), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0, chars=-1)]), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(True)]), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0, title=7)]), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0)], sectionCount=0), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0)], sectionCount=2, truncated=False), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0)], untrustedFields=[]), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0)], untrustedContent=False), 1, "section_candidates_invalid"),
        (rhwp_envelope(untrustedContent=True, untrustedFields=["sections[].excerpt"], pageCount=1, sectionsMode="clause", sectionCount=0, sections={}), 1, "section_candidates_invalid"),
        (native_digest_manifest([digest_section(0)], page_count=2), 1, "pdf_page_mismatch"),
        (rhwp_envelope(pageCount=1, sectionsMode="clause", sectionCount=0, sections=[]), 1, "section_candidates_invalid"),
        (b"not json", 1, "rhwp_manifest_invalid"),
    ],
)
def test_native_section_candidates_reject_bad_mode_shape_and_page_range(
    manifest: bytes,
    expected_pages: int,
    expected_code: str,
) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        parse_section_candidates_manifest(manifest, expected_pages)
    assert caught.value.code == expected_code


def test_section_candidates_validation_accepts_two_thousand_and_rejects_more() -> None:
    def payload(count: int) -> dict[str, object]:
        return {
            "schema": "bidops.section-candidates.v1", "page_count": 2, "mode": "clause",
            "section_count": count,
            "sections": [
                {"index": index, "title": "t", "page": 1 + index % 2, "char_count": 0, "truncated": False}
                for index in range(count)
            ],
        }

    assert validate_section_candidates(payload(2000), page_count=2)["section_count"] == 2000
    for broken, page_count in (
        (payload(2001), 2),
        (payload(3), 1),
        ({**payload(1), "schema": "bidops.section-candidates.v2"}, 2),
        ({**payload(1), "section_count": 2}, 2),
    ):
        with pytest.raises(DocumentProcessingError) as caught:
            validate_section_candidates(broken, page_count=page_count)
        assert caught.value.code == "section_candidates_invalid"

    partial = {
        "schema": "bidops.section-candidates.v2", "page_count": 2, "mode": "outline",
        "section_count": 67, "returned_count": 1, "truncated": True, "candidates_truncated": True,
        "sections": [
            {"index": 0, "title": "t", "page": 1, "char_count": 0, "truncated": False},
        ],
    }
    assert validate_section_candidates(partial, page_count=2)["section_count"] == 67
    for broken in (
        {**partial, "returned_count": 2},
        {**partial, "section_count": 0},
        {**partial, "truncated": False},
        {**partial, "candidates_truncated": False},
        {**partial, "mode": "auto"},
    ):
        with pytest.raises(DocumentProcessingError) as caught:
            validate_section_candidates(broken, page_count=2)
        assert caught.value.code == "section_candidates_invalid"


def _native_bundle_arguments(source: bytes) -> dict[str, object]:
    structure = dict(process_document(source, "application/hwp+zip", {"ocr": False}))
    text = "Ⅰ. 사업 개요"
    page = {
        "number": 1, "display_page": 1, "section": 0, "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    return {
        "structure": structure,
        "source_bytes": source,
        "hwpx_bytes": source,
        "hwpx_verify": None,
        "page_text": {"schema": "bidops.rhwp-page-text.v1", "page_count": 1, "pages": [page]},
        "para_page_map": build_para_page_map(
            structure["blocks"],
            {"schemaVersion": "1.0", "pageCount": 1, "pages": [{"pageIndex": 0, "section": 0, "columns": [], "extras": []}]},
            {"schema": "bidops.rhwp-page-text.v1", "page_count": 1, "pages": [page]},
            original_hwpx=True,
        ),
        "pdf_metadata": {
            "schema": "bidops.rhwp-pdf-snapshot.v1", "renderer": "rhwp-svg-pdf", "renderer_version": "1",
            "page_count": 1,
            "renderer_provenance": {
                "renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6", "rhwp_binary_sha256": "a" * 64,
                "backend": "svg", "compat": "2022",
                "fallback_fonts": {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"},
                "worker_image_digest": None,
            },
            "font_provenance": {"font_manifest_sha256": "b" * 64},
            "pages": [{key: value for key, value in page.items() if key != "text"}],
        },
        "options": ProcessorOptions.from_mapping({"prepare_pdf": True, "renderer": "rhwp-svg-pdf", "ocr": False}),
    }


def test_native_bundle_accepts_a_legacy_null_candidate_set_and_checks_a_present_one() -> None:
    arguments = _native_bundle_arguments(hwpx_bytes())
    # A bundle frozen before 0024 carries no candidates and stays valid.
    assert validate_native_bundle(section_candidates=None, **arguments) is None
    good = {
        "schema": "bidops.section-candidates.v1", "page_count": 1, "mode": "clause", "section_count": 1,
        "sections": [{"index": 0, "title": "Ⅰ. 사업 개요", "page": 1, "char_count": 12, "truncated": False}],
    }
    assert validate_native_bundle(section_candidates=good, **arguments) is None
    partial = {
        "schema": "bidops.section-candidates.v2",
        "page_count": 1,
        "mode": "outline",
        "section_count": 2,
        "returned_count": 1,
        "truncated": True,
        "candidates_truncated": True,
        "sections": [{"index": 0, "title": "Ⅰ. 사업 개요", "page": 1, "char_count": 12, "truncated": False}],
    }
    assert validate_native_bundle(section_candidates=partial, **arguments) is None
    with pytest.raises(DocumentProcessingError) as caught:
        validate_native_bundle(section_candidates={**good, "page_count": 2}, **arguments)
    assert caught.value.code == "section_candidates_invalid"
