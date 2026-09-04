"""결정적 요구사항 inventory와 목적별 segment manifest 계약 검사.

이 검사는 모델을 부르지 않는다. 모든 입력은 합성 텍스트이며 실제 공고 원문을
쓰지 않는다. 규칙이 label을 정하지 못하면 ``needs_human_review``가 정답이고,
빈 구간·겹침은 자동으로 메우지 않고 ``coverage``와 ``warnings``에 남는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.deep_review.models import (
    ContentObject,
    DocumentBundle,
    DocumentSegment,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    RequirementInventoryItem,
)
from app.deep_review.services import document_segments
from app.lifecycle.models import Attachment, Notice, Run

FIXTURES = Path(__file__).parents[1] / "fixtures" / "deep_review"
SOURCE_SHA = "b" * 64


def _blocks(rows: list[dict]) -> list[dict]:
    """구조 payload의 block 목록을 최소 형태로 만든다."""

    blocks: list[dict] = []
    for row in rows:
        block = {
            "block_key": row["block_key"],
            "parent_block_key": row.get("parent_block_key"),
            "type": row.get("type", "paragraph"),
            "page": row.get("page", 1),
            "bbox": None,
            "text": row.get("text", ""),
            "confidence": None,
            "attributes": row.get("attributes", {}),
        }
        blocks.append(block)
    return blocks


def _structure(blocks: list[dict], *, structure_id=None, document_version_id=None) -> dict:
    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(structure_id or uuid4()),
        "document_version_id": str(document_version_id or uuid4()),
        "source_sha256": SOURCE_SHA,
        "media_type": "application/hwp+zip",
        "extractor": {"name": "hwpx-stdlib", "version": "1", "upstream_commit": None},
        "pages": [{"number": 1, "width": 595.0, "height": 842.0, "image_content_object_id": None}],
        "blocks": blocks,
        "warnings": [],
        "created_at": "2026-09-04T00:00:00+00:00",
    }


def _requirement_table(
    ids: list[str],
    *,
    table_key: str = "table-1-1",
    header: str = "요구사항 ID",
    titles: list[str] | None = None,
) -> list[dict]:
    """요구사항 ID 열을 가진 합성 표 block을 만든다."""

    rows: list[dict] = [{
        "block_key": f"{table_key}-block",
        "type": "table",
        "text": "",
        "attributes": {"table_key": table_key},
    }]
    for column, label in enumerate((header, "요구사항 명칭")):
        rows.append({
            "block_key": f"{table_key}-r0-c{column}",
            "parent_block_key": f"{table_key}-block",
            "type": "table_cell",
            "text": label,
            "attributes": {"table_key": table_key, "row": 0, "column": column},
        })
    for index, raw_id in enumerate(ids, start=1):
        title = (titles or [])[index - 1] if titles and len(titles) >= index else f"합성 요구사항 {index}"
        for column, value in enumerate((raw_id, title)):
            rows.append({
                "block_key": f"{table_key}-r{index}-c{column}",
                "parent_block_key": f"{table_key}-block",
                "type": "table_cell",
                "text": value,
                "attributes": {"table_key": table_key, "row": index, "column": column},
            })
    return rows


def _fire_prevention_ids() -> list[str]:
    payload = json.loads((FIXTURES / "fire_prevention_55.json").read_text(encoding="utf-8"))
    return list(payload["expected_requirement_ids"])


# --------------------------------------------------------------------------
# 요구사항 inventory
# --------------------------------------------------------------------------


def test_fire_prevention_fixture_yields_fifty_five_unique_ids() -> None:
    ids = _fire_prevention_ids()
    assert len(ids) == 55
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제3장 기능 요구사항"},
            *_requirement_table(ids),
        ]))
    )
    summary = payload["inventory_summary"]
    assert summary["item_count"] == 55
    assert len(summary["expected_ids"]) == 55
    assert summary["duplicate_ids"] == []
    assert summary["ambiguous_items"] == []
    assert summary["prefixes"] == ["REQ"]


def test_table_inventory_keeps_raw_id_normalized_id_locator_and_title() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks(_requirement_table(["REQ-001"], titles=["합성 기능 항목"])))
    )
    item = payload["inventory_items"][0]
    assert item["raw_id"] == "REQ-001"
    assert item["normalized_id"] == "REQ-1"
    assert item["title"] == "합성 기능 항목"
    assert item["ordinal"] == 1
    assert item["locator"]["kind"] == "table_cell"
    assert item["locator"]["row"] == 1 and item["locator"]["column"] == 0
    assert item["locator"]["block_key"] == "table-1-1-r1-c0"


def test_duplicate_requirement_id_is_reported_and_both_rows_are_kept() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks(_requirement_table(["REQ-001", "REQ-002", "REQ-001"])))
    )
    summary = payload["inventory_summary"]
    assert summary["duplicate_ids"] == ["REQ-1"]
    assert summary["item_count"] == 3
    assert sorted(summary["expected_ids"]) == ["REQ-1", "REQ-2"]


def test_chapter_restarted_numbering_keeps_both_occurrences() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제2장 기능 요구사항"},
            *_requirement_table(["SFR-01", "SFR-02"], table_key="table-1-1"),
            {"block_key": "paragraph-1-2", "text": "제3장 보안 요구사항"},
            *_requirement_table(["SFR-01"], table_key="table-1-2"),
        ]))
    )
    assert payload["inventory_summary"]["duplicate_ids"] == ["SFR-1"]
    assert payload["inventory_summary"]["item_count"] == 3


def test_prefix_collision_is_recorded_as_ambiguous_not_merged() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks(_requirement_table(["SYR-01", "Syr-02"])))
    )
    reasons = {item["reason"] for item in payload["inventory_summary"]["ambiguous_items"]}
    assert "prefix_collision" in reasons


def test_paragraph_ids_need_a_confirmed_prefix() -> None:
    """산문 안의 ``ISO-9001``은 요구사항 ID가 아니다."""

    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "본 사업은 ISO-9001 인증을 요구한다."},
            {"block_key": "paragraph-1-2", "text": "품질 관리는 ISO-9001 절차를 따른다."},
        ]))
    )
    assert payload["inventory_summary"]["expected_ids"] == []
    assert any(
        item["reason"] == "prefix_unconfirmed" for item in payload["inventory_summary"]["ambiguous_items"]
    )


def test_leading_paragraph_ids_confirm_a_prefix_without_a_table() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제2장 기능 요구사항"},
            {"block_key": "paragraph-1-2", "text": "SYR-01 합성 시스템 요구사항 하나"},
            {"block_key": "paragraph-1-3", "text": "SYR-02 합성 시스템 요구사항 둘"},
            {"block_key": "paragraph-1-4", "text": "SYR-03 합성 시스템 요구사항 셋"},
        ]))
    )
    summary = payload["inventory_summary"]
    assert summary["prefixes"] == ["SYR"]
    assert sorted(summary["expected_ids"]) == ["SYR-1", "SYR-2", "SYR-3"]
    assert payload["inventory_items"][0]["locator"]["kind"] == "paragraph"
    assert payload["inventory_items"][0]["title"] is None


def test_document_without_any_id_system_has_empty_inventory() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "page-1-text", "type": "text", "text": "합성 서술 문단이며 식별자가 없다."},
        ]))
    )
    assert payload["inventory_summary"]["expected_ids"] == []
    assert payload["inventory_summary"]["item_count"] == 0
    assert "inventory_empty" in payload["warnings"]


# --------------------------------------------------------------------------
# segment manifest
# --------------------------------------------------------------------------


def test_numbered_headings_and_requirement_tables_are_boundaries() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "표지"},
            {"block_key": "paragraph-1-2", "text": "제1장 사업 개요"},
            {"block_key": "paragraph-1-3", "text": "합성 사업 설명 문단."},
            {"block_key": "paragraph-1-4", "text": "제2장 기능 요구사항"},
            *_requirement_table(["SFR-01", "SFR-02"]),
        ]))
    )
    assert [segment["ordinal"] for segment in payload["segments"]] == [1, 2, 3]
    assert payload["segments"][0]["start_locator"]["block_key"] == "paragraph-1-2"
    assert payload["segments"][2]["start_locator"]["block_key"] == "table-1-1-block"
    assert payload["segments"][2]["requirement_ids"] == ["SFR-1", "SFR-2"]


def test_toc_entries_link_to_body_headings_and_are_not_boundaries() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "목차"},
            {"block_key": "paragraph-1-2", "text": "제1장 사업 개요 ........ 3"},
            {"block_key": "paragraph-1-3", "text": "제2장 기능 요구사항 ........ 9"},
            {"block_key": "paragraph-1-4", "text": "제1장 사업 개요"},
            {"block_key": "paragraph-1-5", "text": "합성 개요 문단."},
            {"block_key": "paragraph-1-6", "text": "제2장 기능 요구사항"},
            {"block_key": "paragraph-1-7", "text": "합성 기능 문단."},
        ]))
    )
    starts = [segment["start_locator"]["block_key"] for segment in payload["segments"]]
    assert starts == ["paragraph-1-4", "paragraph-1-6"]
    toc = payload["coverage"]["toc"]
    assert toc["entry_count"] == 2 and toc["matched_heading_count"] == 2


def test_keyword_rule_labels_a_segment_and_prefix_rule_adds_labels() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제1장 입찰참가자격"},
            {"block_key": "paragraph-1-2", "text": "합성 자격 문단."},
            {"block_key": "paragraph-1-3", "text": "제2장 기능 요구사항"},
            *_requirement_table(["SFR-01"]),
        ]))
    )
    first, last = payload["segments"][0], payload["segments"][-1]
    assert first["taxonomy_labels"] == ["business_eligibility_evaluation"]
    assert first["status"] == "classified"
    assert first["classification_source"] == "deterministic"
    assert first["confidence"] is None
    assert "technical_functional" in last["taxonomy_labels"]


def test_unlabelled_segment_is_needs_human_review_without_a_model() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제1장 총칙"},
            {"block_key": "paragraph-1-2", "text": "합성 총칙 문단."},
        ]))
    )
    segment = payload["segments"][0]
    assert segment["status"] == "needs_human_review"
    assert segment["taxonomy_labels"] == []
    assert segment["confidence"] is None
    assert segment["classification_source"] == "deterministic"


def test_conflicting_rules_stay_needs_human_review_and_keep_both_candidates() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제1장 입찰참가자격"},
            {"block_key": "paragraph-1-2", "text": "SFR-01 합성 기능 하나"},
            {"block_key": "paragraph-1-3", "text": "SFR-02 합성 기능 둘"},
            {"block_key": "paragraph-1-4", "text": "SFR-03 합성 기능 셋"},
        ]))
    )
    segment = payload["segments"][0]
    assert segment["status"] == "needs_human_review"
    assert segment["taxonomy_labels"] == ["business_eligibility_evaluation", "technical_functional"]
    assert segment["confidence"] is None
    assert any(warning.startswith("taxonomy_conflict:") for warning in payload["warnings"])


def test_coverage_reports_the_leading_gap_and_does_not_fill_it() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "표지"},
            {"block_key": "paragraph-1-2", "text": "제1장 사업 개요"},
        ]))
    )
    coverage = payload["coverage"]
    assert coverage["block_count"] == 2
    assert coverage["covered_block_count"] == 1
    assert coverage["gaps"] == [{"start_ordinal": 0, "end_ordinal": 0}]
    assert coverage["overlap_count"] == 0
    assert any(warning.startswith("coverage_gap:") for warning in payload["warnings"])


def test_document_without_any_boundary_warns_and_keeps_no_segment() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([{"block_key": "page-1-text", "type": "text", "text": "합성 문단."}]))
    )
    assert payload["segments"] == []
    assert "no_segment_boundary" in payload["warnings"]


def test_segment_id_is_deterministic_for_the_same_document_and_locators() -> None:
    structure_id, document_id = uuid4(), uuid4()
    rows = _blocks([
        {"block_key": "paragraph-1-1", "text": "제1장 사업 개요"},
        {"block_key": "paragraph-1-2", "text": "합성 문단."},
    ])
    first = document_segments.build_manifest_payload(
        _structure(rows, structure_id=structure_id, document_version_id=document_id)
    )
    second = document_segments.build_manifest_payload(
        _structure(rows, structure_id=structure_id, document_version_id=document_id)
    )
    assert first["segments"][0]["segment_id"] == second["segments"][0]["segment_id"]
    assert first["payload_sha256"] == second["payload_sha256"]
    other = document_segments.build_manifest_payload(_structure(rows))
    assert other["segments"][0]["segment_id"] != first["segments"][0]["segment_id"]


def test_extractor_binding_is_fixed_and_hashed() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([{"block_key": "paragraph-1-1", "text": "제1장 사업 개요"}]))
    )
    binding = payload["extractor_binding"]
    assert binding["name"] == document_segments.EXTRACTOR_NAME
    assert binding["taxonomy_version"] == document_segments.TAXONOMY_VERSION
    assert len(payload["extractor_binding_sha256"]) == 64


# --------------------------------------------------------------------------
# 저장 (append-only, 같은 키의 재계산은 기존 행)
# --------------------------------------------------------------------------


@pytest.fixture
def stored(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with Session(engine) as session:
        run = Run(id=f"seg-{uuid4()}")
        notice = Notice(run=run, notice_key=f"seg-notice-{uuid4()}", title="합성", sample_role="analysis")
        session.add(run)
        session.flush()
        attachment = Attachment(notice=notice, name="합성.hwpx", source_url=None)
        content = ContentObject(sha256=SOURCE_SHA, size_bytes=10, detected_mime="application/hwp+zip", retention_class="source")
        session.add_all([attachment, content])
        session.flush()
        bundle = DocumentBundle(notice_id=notice.id, revision=1, version=1, status="draft", issues_snapshot=[])
        session.add(bundle)
        session.flush()
        document = DocumentVersion(
            notice_id=notice.id, attachment_id=attachment.id, version=1, source_kind="manual",
            role="제안요청서", is_current=True, content_object_id=content.id,
            original_filename="합성.hwpx", safety_status="safe", created_by_name="담당자",
        )
        session.add(document)
        session.flush()
        structure = DocumentStructure(
            document_version_id=document.id, source_sha256=SOURCE_SHA, media_type="application/hwp+zip",
            extractor_name="hwpx-stdlib", extractor_version="1", upstream_commit=None,
            payload_content_object_id=content.id, payload_sha256=SOURCE_SHA,
            page_count=1, block_count=1, validation_status="ready",
        )
        session.add(structure)
        session.commit()
        return {"engine": engine, "structure_id": structure.id, "document_id": document.id}


def _stored_structure(stored) -> dict:
    return _structure(
        _blocks([
            {"block_key": "paragraph-1-1", "text": "제2장 기능 요구사항"},
            *_requirement_table(["SFR-01", "SFR-02"]),
        ]),
        structure_id=stored["structure_id"],
        document_version_id=stored["document_id"],
    )


def test_store_manifest_is_idempotent_for_the_same_identity(stored) -> None:
    payload = _stored_structure(stored)
    with Session(stored["engine"]) as session:
        first = document_segments.store_manifest(session, payload)
        session.commit()
        first_id = first.id
    with Session(stored["engine"]) as session:
        second = document_segments.store_manifest(session, payload)
        session.commit()
        assert second.id == first_id
        assert session.scalar(select(func.count()).select_from(DocumentSegmentManifest)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentSegment)) == 2
        assert session.scalar(select(func.count()).select_from(RequirementInventoryItem)) == 2


def test_manifest_rows_reject_update_and_delete(stored) -> None:
    payload = _stored_structure(stored)
    with Session(stored["engine"]) as session:
        manifest = document_segments.store_manifest(session, payload)
        session.commit()
        manifest_id = manifest.id
    with Session(stored["engine"]) as session:
        row = session.get(DocumentSegmentManifest, manifest_id)
        assert row is not None
        row.taxonomy_version = "다른 버전"
        with pytest.raises(ValueError):
            session.flush()
        session.rollback()
    with Session(stored["engine"]) as session:
        row = session.get(DocumentSegmentManifest, manifest_id)
        session.delete(row)
        with pytest.raises(ValueError):
            session.flush()
        session.rollback()


def test_segments_view_never_exposes_source_text(stored) -> None:
    payload = _stored_structure(stored)
    with Session(stored["engine"]) as session:
        document_segments.store_manifest(session, payload)
        session.commit()
    with Session(stored["engine"]) as session:
        view = document_segments.read_manifest_view(session, stored["structure_id"])
    assert view is not None
    assert view["schema"] == "bidops.document-segments.v1"
    serialized = json.dumps(view, ensure_ascii=False)
    assert "title" not in serialized
    assert "합성 요구사항" not in serialized
    assert "기능 요구사항" not in serialized
    assert view["inventory_summary"]["expected_ids"] == ["SFR-1", "SFR-2"]
    assert "inventory_items" not in view


def test_read_manifest_view_returns_none_when_absent(stored) -> None:
    with Session(stored["engine"]) as session:
        assert document_segments.read_manifest_view(session, uuid4()) is None


def test_bundle_inventory_context_unions_every_document(stored) -> None:
    payload = _stored_structure(stored)
    with Session(stored["engine"]) as session:
        document_segments.store_manifest(session, payload)
        session.commit()
    with Session(stored["engine"]) as session:
        context = document_segments.inventory_context(session, [stored["structure_id"]])
    assert context["expected_ids"] == ["SFR-1", "SFR-2"]
    assert context["prefixes"] == ["SFR"]
    assert context["manifest_count"] == 1
    assert context["needs_human_review_count"] >= 0


def test_wire_payload_satisfies_the_published_contract() -> None:
    from app.deep_review.services.deep_review_validation import validate_document_segments

    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-1-1", "text": "제1장 입찰참가자격"},
            {"block_key": "paragraph-1-2", "text": "합성 자격 문단."},
            {"block_key": "paragraph-1-3", "text": "제2장 기능 요구사항"},
            *_requirement_table(_fire_prevention_ids()),
        ]))
    )
    wire = document_segments.wire_payload(payload)
    assert validate_document_segments(wire) == dict(wire)
    assert "inventory_items" not in wire and "segment_titles" not in wire
