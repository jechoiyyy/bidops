"""Focused immutable PDF preparation and range binding contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.object_store import FilesystemObjectStore
from app.deep_review.document_mcp import process_document
from app.deep_review.document_mcp.contracts import para_page_map_bytes
from app.deep_review.document_mcp.para_page_map import build_para_page_map
from app.deep_review.document_mcp.processor import ProcessedDocument
from app.deep_review.document_mcp.safety import ProcessorOptions
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentVersion,
    PrespecV4PdfSnapshot,
)
from app.deep_review.services.overview_range import (
    V4_MANIFEST_SCHEMA,
    V4PreparationError,
    build_v4_range_review_manifest,
    select_v4_input_range,
    select_v4_page_span,
)
from app.deep_review.services.pdf_snapshot import (
    _NATIVE_REFERENCE_FIELDS,
    _validate_native_references,
    prepare_v4_pdf_snapshot,
    read_snapshot_section_candidates,
)
from app.lifecycle.models import Notice
from tests.deep_review.test_document_mcp import hwpx_bytes


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SOURCE_PROCESSOR_PROVENANCE = {
    "schema": "bidops.pdf-text-provenance.v1",
    "processor_sha256": "d" * 64,
    "text_extractor": {"name": "pdf-poppler-prepared", "version": "1"},
    "poppler_binary_sha256": {"pdfinfo": "e" * 64, "pdftotext": "f" * 64},
}
_SOURCE_RENDERER = {"source_pdf": True, "processor_provenance": _SOURCE_PROCESSOR_PROVENANCE}
_SOURCE_FONT = {"source_pdf": True, "font_provenance": None}
_NATIVE_RENDERER = {
    "renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6", "rhwp_binary_sha256": "a" * 64,
    "backend": "svg", "compat": "2022",
    "fallback_fonts": {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"},
    "worker_image_digest": None,
}
_NATIVE_FONT = {"font_manifest_sha256": "b" * 64}


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return engine


def _source(session: Session, store: FilesystemObjectStore, data: bytes) -> tuple[DocumentVersion, ContentObjectLocation]:
    notice = Notice(id=142, notice_key="pre:R26BD00271191", title="fixture")
    session.add(notice)
    session.flush()
    detected_mime = "application/pdf" if data.startswith(b"%PDF-") else "application/x-hwp"
    filename = "fixture_제안요청서.pdf" if detected_mime == "application/pdf" else "fixture_제안요청서.hwp"
    metadata = store.put("source", f"source/v4/source-{_sha(data)}", data, content_type=detected_mime)
    content = ContentObject(
        sha256=_sha(data), size_bytes=len(data), detected_mime=detected_mime, retention_class="document-source"
    )
    session.add(content)
    session.flush()
    location = ContentObjectLocation(
        content_object_id=content.id,
        namespace_key="source",
        object_key=metadata.object_key,
        object_version_id=metadata.object_version_id,
        etag=metadata.etag,
        status="verified",
    )
    session.add(location)
    session.add(ContentScan(content_object_id=content.id, scanner="test", scanner_version="1", status="clean", safe_result={"sha256": _sha(data)}))
    document = DocumentVersion(
        id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
        source_kind="manual", original_filename=filename, role="제안요청서",
        is_current=True, safety_status="safe", needs_human_review=False,
    )
    session.add(document)
    session.flush()
    return document, location


def _processed(source: bytes) -> ProcessedDocument:
    page_one = "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"
    page_two = "Ⅰ. 감리 개요\n1. 목적\n본문\n2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장"
    payload = {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "source_sha256": _sha(source),
        "media_type": "application/pdf",
        "extractor": {"name": "pdf-poppler-prepared", "version": "1"},
        "pages": [
            {"number": 1, "width": 612.0, "height": 792.0, "image_content_object_id": None},
            {"number": 2, "width": 612.0, "height": 792.0, "image_content_object_id": None},
        ],
        "blocks": [
            {"block_key": "page-1-text", "page": 1, "type": "text", "text": page_one, "bbox": [0, 0, 612, 792], "confidence": 1.0, "attributes": {}},
            {"block_key": "page-2-text", "page": 2, "type": "text", "text": page_two, "bbox": [0, 0, 612, 792], "confidence": 1.0, "attributes": {}},
        ],
        "warnings": ["pdf_poppler_text_fallback"],
        "created_at": datetime.now(UTC).isoformat(),
    }
    return ProcessedDocument(
        payload,
        original_bytes=source,
        converted_pdf_bytes=None,
        pdf_metadata={
            "schema": "bidops.pdf-snapshot.v1",
            "renderer": "source-pdf",
            "renderer_version": "1",
            "rerendered": False,
            "processor_provenance": _SOURCE_PROCESSOR_PROVENANCE,
            "font_provenance": None,
            "page_count": 2,
            "pages": [
                {"number": 1, "width": 612.0, "height": 792.0, "text_sha256": _sha(page_one.encode())},
                {"number": 2, "width": 612.0, "height": 792.0, "text_sha256": _sha(page_two.encode())},
            ],
        },
    )


class _Converter:
    def __init__(self, processed: ProcessedDocument, scanner):
        self.processed = processed
        self.clamav_checker = scanner
        self.calls = 0

    def process(self, content: bytes, media_type: str | None, options: Any) -> ProcessedDocument:
        self.calls += 1
        assert content == self.processed.original_bytes
        assert media_type == "application/pdf"
        return self.processed


class _GeneratedConverter(_Converter):
    """Return the native rhwp artifact bundle a document worker produces."""

    def process(self, content: bytes, media_type: str | None, options: Any) -> ProcessedDocument:
        self.calls += 1
        assert content == self.processed.original_bytes
        assert media_type == "application/octet-stream"
        hwpx = hwpx_bytes()
        payload = dict(process_document(hwpx, "application/hwp+zip", {"ocr": False}))
        payload["source_sha256"] = _sha(content)
        payload["media_type"] = "application/x-hwp"
        text = "Ⅰ. 감리 개요\n감리 예산 123,456,789원"
        page = {"number": 1, "display_page": 1, "section": 0, "text": text, "text_sha256": _sha(text.encode())}
        page_text = {"schema": "bidops.rhwp-page-text.v1", "page_count": 1, "pages": [page]}
        dump = {"schemaVersion": "1.0", "pageCount": 1, "pages": [{"pageIndex": 0, "section": 0, "columns": [], "extras": []}]}
        mapping = build_para_page_map(payload["blocks"], dump, page_text, original_hwpx=False)
        return ProcessedDocument(
            payload,
            original_bytes=content,
            converted_pdf_bytes=b"%PDF-1.7\ngenerated-pdf",
            hwpx_bytes=hwpx,
            hwpx_verify={"identical": True, "diff_count": 0, "pages": {"before": 1, "after": 1, "identical": True}},
            page_text=page_text,
            para_page_map=mapping,
            para_page_map_bytes=para_page_map_bytes(mapping, max_output_bytes=20 * 1024 * 1024),
            pdf_metadata={
                "schema": "bidops.rhwp-pdf-snapshot.v1",
                "renderer": "rhwp-svg-pdf",
                "renderer_version": "1",
                "page_count": 1,
                "renderer_provenance": dict(_NATIVE_RENDERER),
                "font_provenance": dict(_NATIVE_FONT),
                "pages": [{key: page[key] for key in ("number", "display_page", "section", "text_sha256")}],
            },
        )


def _selection(document: DocumentVersion, source: bytes):
    return select_v4_input_range({
        "document_version_id": str(document.id),
        "source_sha256": _sha(source),
        "pages": [
            {"number": 1, "text": "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"},
            {"number": 2, "text": "Ⅰ. 감리 개요\n1. 목적\n본문\n2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장"},
        ],
        "blocks": [],
    })


def test_snapshot_roundtrip_stores_full_page_text_and_reuses_exact_binding(tmp_path: Path):
    source = b"%PDF-1.7\nfixture-original"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    scanner_calls: list[bytes] = []

    def scanner(value: bytes) -> bool:
        scanner_calls.append(value)
        return True

    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        session.commit()
        converter = _Converter(_processed(source), scanner)
        snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/pdf",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer=_SOURCE_RENDERER,
            font=_SOURCE_FONT,
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
            scanner=scanner,
        )
        session.commit()
        assert snapshot.source_kind == "original"
        assert converter.calls == 1
        assert snapshot.source_content_object_id == snapshot.pdf_content_object_id
        assert snapshot.source_location_id == snapshot.pdf_location_id
        page_text, _ = store.get("structure", f"structure/prespec-v4/{document.id}/page-text-{snapshot.page_text_sha256}.json")
        assert "Ⅰ. 감리 개요" in json.loads(page_text)["pages"][0]["text"]
        assert scanner_calls.count(source) >= 2

        assert _selection(document, source).status == "ready"

        reused_snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/pdf",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer=_SOURCE_RENDERER,
            font=_SOURCE_FONT,
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
            scanner=scanner,
        )
        assert reused_snapshot.id == snapshot.id
        assert converter.calls == 1

        # Cache reuse must honor the newest scan row.  An older clean result
        # cannot mask a later infected/unavailable verdict.
        session.add(ContentScan(
            content_object_id=snapshot.pdf_content_object_id,
            scanner="clamav",
            scanner_version="2",
            status="infected",
            safe_result={"verdict": "infected"},
            scanned_at=datetime.now(UTC) + timedelta(seconds=1),
        ))
        session.flush()
        with pytest.raises(V4PreparationError) as scan_error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/pdf",
                converter=converter,
                store=store,
                options={"prepare_pdf": True},
                renderer=_SOURCE_RENDERER,
                font=_SOURCE_FONT,
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True})), "text_extractor": "pdf-poppler-prepared"},
                scanner=scanner,
            )
        assert scan_error.value.code == "scanner_unavailable"
        assert converter.calls == 1

        with pytest.raises(ValueError, match="append-only"):
            snapshot.pdf_metadata_jsonb = {"changed": True}
            session.flush()
        session.rollback()


def test_range_keeps_exact_substrings_and_marks_missing_boundary_for_human_review():
    selection = select_v4_input_range({
        "pages": [
            {"number": 1, "text": "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항"},
            {"number": 2, "text": "Ⅰ. 감리 개요\n1. 목적\n본문\nⅡ. 제안요청 사항\n다음"},
        ],
        "blocks": [],
    })
    assert selection.status == "ready"
    assert selection.page_numbers == (2,)
    assert "Ⅱ. 제안요청 사항" not in selection.manifest["pages"][0]["text"]
    assert selection.manifest["pages"][0]["source_page_text_sha256"] != selection.manifest["pages"][0]["text_sha256"]

    ambiguous = select_v4_input_range({
        "pages": [{"number": 1, "text": "Ⅰ. 감리 개요\n1. 목적\n본문"}],
        "blocks": [],
    })
    assert ambiguous.status == "needs_human_review"
    assert ambiguous.reason_code == "scope_end_missing"


def test_same_line_chapter_boundaries_require_manual_pages_without_truncating_source():
    import copy

    payload = {"pages": [
        {"number": 1, "text": "목차\nⅠ 사업 개요    Ⅱ 사업추진 방안"},
        {"number": 2, "text": "Ⅰ 사업 개요    Ⅱ 사업추진 방안\n1. 사업 목적\n개요와 주요 과업\n2. 사업 범위\n세부 요구사항"},
        {"number": 3, "text": "Ⅲ 제안 안내\n다음 장"},
    ], "blocks": []}
    before = copy.deepcopy(payload)
    selected = select_v4_input_range(payload)
    assert selected.status == "needs_human_review"
    assert selected.reason_code == "ambiguous_scope_boundary"
    assert selected.page_numbers == () and "pages" not in selected.manifest
    assert payload == before
    # A multi-column table of contents alone does not invalidate clear body headings.
    payload["pages"][1]["text"] = "Ⅰ 사업 개요\n1. 사업 목적\n개요와 주요 과업\nⅡ 사업추진 방안"
    assert select_v4_input_range(payload).status == "ready"


@pytest.mark.parametrize("purpose", ["제안목적 및 배경", "제안 목적"])
def test_proposal_writing_overview_requires_manual_range(purpose):
    text_value = f"Ⅰ. 제안개요\n1. {purpose}\n제안사가 작성하는 내용\n2. 제안의 범위\nⅡ. 제안업체 일반"
    payload = {"pages": [{"number": 1, "text": text_value}], "blocks": []}
    selection = select_v4_input_range(payload)
    assert selection.status == "needs_human_review"
    assert selection.reason_code == "ambiguous_scope_boundary"
    assert selection.page_numbers == () and "pages" not in selection.manifest
    assert payload["pages"][0]["text"] == text_value


#: 실제 목차 쪽 (0911 공고 805, 2쪽). 표제는 장식 기호에 싸여 있고 항목은
#: 탭 뒤 쪽 번호로 끝난다.
TOC_PAGE = (
    "- 목  차 -\n"
    "\n"
    "Ⅰ. 사업 개요\n"
    "   1. 추진배경 및 목적\t4\n"
    "   2. 사업 개요\t4\n"
    "Ⅱ. 유지관리 대상\n"
    "   1. 정보자원 현황 \t7\n"
    "Ⅲ. 제안요청 내용\n"
    "   1. 요구사항 총괄표 \t11\n"
)


def test_table_of_contents_page_never_establishes_the_range():
    """목차 쪽의 장 제목은 본문 범위가 아니다 (0911 공고 805)."""

    payload = {"pages": [
        {"number": 1, "text": TOC_PAGE},
        {"number": 2, "text": "Ⅰ. 사업 개요\n1. 추진배경 및 목적\n본문\nⅡ. 유지관리 대상\n다음"},
    ], "blocks": []}

    assert select_v4_input_range(payload).page_numbers == (2,)

    # 표제 없이 쪽 번호 항목만 늘어선 쪽도 목차로 보고 제외한다.
    payload["pages"][0]["text"] = TOC_PAGE.replace("- 목  차 -\n\n", "") + "   2. 요구사항 상세\t12\n"
    assert select_v4_input_range(payload).page_numbers == (2,)


def test_the_table_of_contents_aligns_printed_pages_and_bounds_the_overview_chapter():
    """목차 항목의 인쇄 쪽을 본문 제목 대조로 물리 쪽에 맞춘다 (ADR-0057 결정 2)."""

    payload = {"pages": [
        {"number": 1, "text": "제 안 요 청 서\n2026. 9."},
        {"number": 2, "text": (
            "목 차\n"
            "Ⅰ. 사업 개요\t1\n"
            " 1. 사업 일반\t1\n"
            " 2. 사업 목표\t2\n"
            "Ⅱ. 제안 안내\t3\n"
            " 1. 입찰 참가자격\t3\n"
        )},
        {"number": 3, "text": "Ⅰ. 사업 개요\n1. 사업 일반\n사업명은 합성 통합 시스템 구축이다.\n- 1 -"},
        {"number": 4, "text": "2. 사업 목표\n목표는 합성 자료의 연계다.\n- 2 -"},
        {"number": 5, "text": "Ⅱ. 제안 안내\n1. 입찰 참가자격\n자격은 원문으로 확인한다.\n- 3 -"},
    ], "blocks": []}

    selection = select_v4_input_range(payload)

    assert selection.status == "ready" and selection.strategy == "toc_scope"
    assert selection.reason_code is None
    # 인쇄 1~2쪽 = 물리 3~4쪽. 끝 장은 배타이므로 물리 5쪽은 들어가지 않는다.
    assert selection.page_numbers == (3, 4)
    assert selection.start_locator["page"] == 3 and selection.end_locator["page"] == 5
    assert all("Ⅱ. 제안 안내" not in item["text"] for item in selection.manifest["pages"])


def test_a_table_of_contents_that_does_not_align_hands_the_range_to_the_heading_scope():
    """한 장만 맞는 offset은 확정이 아니다. 추측하지 않고 본문 전략으로 간다."""

    payload = {"pages": [
        {"number": 1, "text": (
            "목 차\n"
            "Ⅰ. 사업 개요\t1\n"
            " 1. 사업 일반\t1\n"
            "Ⅱ. 제안 안내\t5\n"
            " 1. 입찰 참가자격\t5\n"
        )},
        {"number": 2, "text": "Ⅰ. 사업 개요\n1. 사업 일반\n본문이다.\nⅡ. 제안 안내\n다음 장"},
    ], "blocks": []}

    selection = select_v4_input_range(payload)

    assert selection.status == "ready" and selection.strategy == "heading_scope"
    # 성공한 선택에는 사유가 없다. 목차 실패 사유는 따로 따라가며 최종 결과가
    # fallback·사람 검토일 때만 `range_reason_codes`에 남는다.
    assert selection.reason_code is None
    assert selection.toc_reason_code == "toc_alignment_failed"
    assert selection.page_numbers == (2,)


def test_a_chapter_marker_split_from_its_title_is_still_one_heading():
    """`Ⅰ`과 제목이 두 줄로 갈라진 조판도 한 장이다 (0916 공고 781·805)."""

    payload = {"pages": [
        {"number": 1, "text": "Ⅰ\n\n 사업 개요\n1. 목적\n합성 사업의 목적이다."},
        {"number": 2, "text": "Ⅱ\n\n 제안요청 사항\n1. 상세 요구사항"},
    ], "blocks": []}

    selection = select_v4_input_range(payload)

    assert selection.status == "ready" and selection.strategy == "heading_scope"
    assert selection.page_numbers == (1,)
    # 장은 제목 줄이 아니라 표식 줄에서 시작한다.
    assert (selection.start_locator["page"], selection.start_locator["line"]) == (1, 0)
    assert (selection.end_locator["page"], selection.end_locator["line"]) == (2, 0)


def test_a_proposal_form_chapter_and_everything_after_it_is_not_an_overview_chapter():
    """제안서 작성 안내 뒤의 양식 장은 후보가 아니다 (0916 공고 805의 70쪽)."""

    payload = {"pages": [
        {"number": 1, "text": "Ⅰ. 사업 안내\n발주 안내 본문이다."},
        {"number": 2, "text": (
            "Ⅴ. 제안서 작성 안내\n"
            "3. 제안서 목차\n"
            "Ⅰ. 사업 개요\n"
            "1. 목적\n"
            "Ⅱ. 사업 내용\n"
        )},
    ], "blocks": []}

    selection = select_v4_input_range(payload)

    assert selection.status == "needs_human_review"
    assert selection.reason_code == "scope_heading_missing" and selection.page_numbers == ()


def test_partial_section_list_requires_manual_range_even_with_clear_headings():
    payload = {"pages": [{"number": 1, "text": "Ⅰ 사업 개요\n1. 사업 목적\n전체 본문\nⅡ 추진 방안"}], "blocks": []}
    selected = select_v4_input_range(payload, candidates_complete=False)
    assert selected.status == "needs_human_review"
    assert selected.reason_code == "section_candidates_incomplete" and selected.page_numbers == ()


def test_snapshot_rejects_page_text_or_scanner_failure(tmp_path: Path):
    source = b"%PDF-1.7\nfixture"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        with pytest.raises(V4PreparationError) as error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/pdf",
                converter=_Converter(_processed(source), lambda _value: False),
                store=store,
                options={"prepare_pdf": True},
                renderer=_SOURCE_RENDERER,
                font=_SOURCE_FONT,
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
                scanner=lambda _value: False,
            )
        assert error.value.code == "scanner_failed"
        assert session.scalar(select(PrespecV4PdfSnapshot)) is None


def test_generated_pdf_is_versioned_in_source_namespace(tmp_path: Path):
    source = b"HWP source bytes"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        converter = _GeneratedConverter(_processed(source), lambda _value: True)
        snapshot = prepare_v4_pdf_snapshot(
            session,
            document_version_id=document.id,
            source_location_id=source_location.id,
            source_bytes=source,
            media_type="application/octet-stream",
            converter=converter,
            store=store,
            options={"prepare_pdf": True},
            renderer=dict(_NATIVE_RENDERER),
            font=dict(_NATIVE_FONT),
            config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
        )
        pdf_location = session.get(ContentObjectLocation, snapshot.pdf_location_id)
        assert snapshot.source_kind == "generated"
        assert snapshot.source_content_object_id != snapshot.pdf_content_object_id
        assert pdf_location is not None and pdf_location.namespace_key == "source"


def test_generated_pdf_requires_worker_emitted_provenance(tmp_path: Path):
    source = b"HWP source bytes"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    with Session(engine) as session:
        document, source_location = _source(session, store, source)
        converter = _GeneratedConverter(_processed(source), lambda _value: True)
        with pytest.raises(V4PreparationError) as error:
            prepare_v4_pdf_snapshot(
                session,
                document_version_id=document.id,
                source_location_id=source_location.id,
                source_bytes=source,
                media_type="application/octet-stream",
                converter=converter,
                store=store,
                options={"prepare_pdf": True},
                renderer={**_NATIVE_RENDERER, "rhwp_binary_sha256": "9" * 64},
                font=dict(_NATIVE_FONT),
                config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
            )
        assert error.value.code == "renderer_binding_invalid"
        assert converter.calls == 1
        assert session.scalar(select(PrespecV4PdfSnapshot)) is None


def _native_fixtures():
    """Import the shared native fixture lazily to avoid a test-module cycle."""

    from tests.deep_review.test_rhwp_snapshot import NativeConverter, native_processed, prepare, seed_native

    return NativeConverter, native_processed, prepare, seed_native


def test_native_snapshot_stores_section_candidates_and_rebinds_them_on_reuse(tmp_path: Path) -> None:
    NativeConverter, native_processed, prepare, seed_native = _native_fixtures()
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)
        snapshot = prepare(session, store, document, location, converter)
        session.commit()

        digest = _sha(processed.section_candidates_bytes)
        assert snapshot.section_candidates_sha256 == digest
        content = session.get(ContentObject, snapshot.section_candidates_content_object_id)
        candidate_location = session.get(ContentObjectLocation, snapshot.section_candidates_location_id)
        assert content.detected_mime == "application/json" and content.retention_class == "document-structure"
        assert candidate_location.namespace_key == "structure"
        assert candidate_location.object_key == f"structure/prespec-v4/{document.id}/section-candidates-{digest}.json"
        stored, _metadata = store.get(
            candidate_location.namespace_key, candidate_location.object_key,
            version_id=candidate_location.object_version_id,
        )
        assert stored == processed.section_candidates_bytes
        assert read_snapshot_section_candidates(session, store, snapshot) == processed.section_candidates
        # The cached snapshot is re-read at the pinned version and hash-checked.
        assert prepare(session, store, document, location, converter).id == snapshot.id
        assert converter.calls == 1


def test_snapshot_without_section_candidates_stays_cache_reusable(tmp_path: Path) -> None:
    NativeConverter, native_processed, prepare, seed_native = _native_fixtures()
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        # A bundle frozen before 0024: the three references are null together.
        processed = native_processed(candidates=False)
        document, location = seed_native(session, store, processed)
        converter = NativeConverter(processed)
        snapshot = prepare(session, store, document, location, converter)
        session.commit()

        assert snapshot.section_candidates_content_object_id is None
        assert snapshot.section_candidates_location_id is None
        assert snapshot.section_candidates_sha256 is None
        assert read_snapshot_section_candidates(session, store, snapshot) is None
        assert prepare(session, store, document, location, converter).id == snapshot.id
        assert converter.calls == 1


def test_mixed_section_candidate_references_are_rejected(tmp_path: Path) -> None:
    NativeConverter, native_processed, prepare, seed_native = _native_fixtures()
    store = FilesystemObjectStore(tmp_path)
    with Session(_engine()) as session:
        processed = native_processed()
        document, location = seed_native(session, store, processed)
        snapshot = prepare(session, store, document, location, NativeConverter(processed))
        session.commit()

        refs = {field: getattr(snapshot, field) for field in _NATIVE_REFERENCE_FIELDS}
        refs["section_candidates_location_id"] = None
        page_text_bytes = json.dumps(
            processed.page_text, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        with pytest.raises(V4PreparationError) as error:
            _validate_native_references(
                session, store, refs, document, processed.original_bytes, page_text_bytes,
                snapshot.pdf_metadata_jsonb,
                ProcessorOptions.from_mapping(snapshot.config_jsonb.get("options")),
            )
        assert error.value.code == "native_artifact_reference_invalid"

        partial = SimpleNamespace(
            section_candidates_content_object_id=snapshot.section_candidates_content_object_id,
            section_candidates_location_id=None,
            section_candidates_sha256=snapshot.section_candidates_sha256,
            config_jsonb=snapshot.config_jsonb,
            pdf_page_count=snapshot.pdf_page_count,
        )
        with pytest.raises(V4PreparationError) as error:
            read_snapshot_section_candidates(session, store, partial)
        assert error.value.code == "native_artifact_reference_invalid"


_SPAN_PAGES = [
    {"number": 1, "text": "1. 일반 사항\n본문"},
    {"number": 2, "text": "2. 제출 서류\n본문"},
]
_SPAN_EXTRA = {
    "confirmed_from_target_id": "00000000-0000-0000-0000-0000000007a1",
    "confirmed_by": "tester",
    "note": None,
    "candidate_indices": {"start": 0, "end": 1},
}


def _span(payload: dict[str, Any], first: int, last: int, extra: dict[str, Any] | None = _SPAN_EXTRA):
    return select_v4_page_span(
        payload, first, last,
        start_locator={"kind": "section_candidate", "page": first, "candidate_index": 0},
        end_locator={"kind": "section_candidate", "page": last, "candidate_index": 1},
        extra=extra,
    )


def test_human_confirmed_span_takes_whole_pages_and_repeats_byte_identically():
    payload = {"document_version_id": str(uuid4()), "source_sha256": "a" * 64, "pages": _SPAN_PAGES, "blocks": []}
    span = _span(payload, 1, 2)

    assert span.status == "ready" and span.strategy == "human_confirmed" and span.reason_code is None
    assert span.page_numbers == (1, 2)
    # 사람 확정은 쪽 전체를 고른다. 잘라낸 구간이 아니므로 두 hash가 같다.
    assert all(page["text_sha256"] == page["source_page_text_sha256"] for page in span.manifest["pages"])
    assert [page["text"] for page in span.manifest["pages"]] == [page["text"] for page in _SPAN_PAGES]
    assert span.manifest["block_keys"] == ["page-1-text", "page-2-text"]
    assert span.manifest["selection_status"] == "ready" and span.manifest["schema_version"] == V4_MANIFEST_SCHEMA
    assert span.manifest["confirmed_by"] == "tester" and span.manifest["note"] is None
    assert span.manifest["candidate_indices"] == {"start": 0, "end": 1}
    assert span.manifest["selected_text_sha256"] == _sha("\n".join(page["text"] for page in _SPAN_PAGES).encode())
    assert _span(payload, 1, 2).manifest_bytes == span.manifest_bytes

    for first, last in ((0, 1), (2, 1), (1, 3)):
        with pytest.raises(V4PreparationError) as error:
            _span(payload, first, last)
        assert error.value.code == "page_range_invalid"

    # 확정이 manifest의 다른 필드를 덮어쓸 수는 없다.
    with pytest.raises(V4PreparationError) as error:
        _span(payload, 1, 1, {"selection_status": "ready"})
    assert error.value.code == "range_confirmation_invalid"

    oversized = {"pages": [{"number": 1, "text": "가" * 3_000_000}], "blocks": []}
    with pytest.raises(V4PreparationError) as error:
        _span(oversized, 1, 1)
    assert error.value.code == "input_size_limit"


def test_range_review_manifest_binds_the_candidate_list_without_titles():
    selection = select_v4_input_range({"pages": [{"number": 1, "text": "1. 일반 사항\n본문"}], "blocks": []})
    assert selection.status == "needs_human_review"

    manifest, raw = build_v4_range_review_manifest(selection, candidates_sha256="b" * 64, candidate_count=3)
    assert manifest["schema_version"] == "bidops.prespec-v4-range-review.v1"
    assert manifest["reason_code"] == selection.reason_code and manifest["strategy"] == "heading_scope"
    assert manifest["candidates_sha256"] == "b" * 64 and manifest["candidate_count"] == 3
    assert raw == json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert "title" not in raw.decode()
    # 후보가 없는 snapshot은 null·0으로 남는다. 0을 "후보 없음 아님"으로 올리지 않는다.
    assert build_v4_range_review_manifest(selection)[0]["candidates_sha256"] is None

    with pytest.raises(V4PreparationError) as error:
        build_v4_range_review_manifest(selection, candidates_sha256="not-a-digest")
    assert error.value.code == "section_candidates_invalid"
