"""결정적 요구사항 inventory와 목적별 segment manifest 계약 검사.

이 검사는 모델을 부르지 않는다. 모든 입력은 합성 텍스트이며 실제 공고 원문을
쓰지 않는다. 규칙이 label을 정하지 못하면 ``needs_human_review``가 정답이고,
빈 구간·겹침은 자동으로 메우지 않고 ``coverage``와 ``warnings``에 남는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.object_store import FilesystemObjectStore
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    ContentScan,
    DocumentBundle,
    DocumentSegment,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    PrespecV4PdfSnapshot,
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


def _requirement_card_table(
    cards: list[list[tuple[str, str]]],
    *,
    table_key: str = "card-table-1",
) -> list[dict]:
    """라벨·값 요구사항 카드가 세로로 쌓인 합성 표를 만든다."""

    rows: list[dict] = [{
        "block_key": f"{table_key}-block",
        "type": "table",
        "text": "",
        "attributes": {"table_key": table_key},
    }]
    row = 0
    for card in cards:
        for label, value in card:
            for column, text in enumerate((label, value)):
                rows.append({
                    "block_key": f"{table_key}-r{row}-c{column}",
                    "parent_block_key": f"{table_key}-block",
                    "type": "table_cell",
                    "text": text,
                    "attributes": {"table_key": table_key, "row": row, "column": column},
                })
            row += 1
    return rows


def _taxonomy_card(raw_id: str, category: str) -> list[tuple[str, str]]:
    return [
        ("요구사항분류", category),
        ("요구사항고유번호", raw_id),
        ("요구사항명칭", "합성 taxonomy 항목"),
        ("정의", "합성 정의"),
        ("세부내용", "합성 세부내용"),
    ]


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


def test_label_value_cards_preserve_raw_fields_related_ids_and_anchors() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-anchor-1", "text": "첫 앵커"},
            {"block_key": "paragraph-anchor-2", "text": "둘째 앵커"},
            {"block_key": "paragraph-anchor-empty", "text": "  "},
            {"block_key": "paragraph-anchor-3", "text": "셋째 앵커"},
            *_requirement_card_table([
                [
                    ("요구사항 분류", " 기능 요구사항 "),
                    ("요구사항 고유번호", " SFR-001 "),
                    ("요구사항 명칭", " 원문 명칭 "),
                    ("응락 수준", "필수"),
                    ("정의", " 원문 정의 "),
                    ("세부 내용", " 원문 세부 내용 "),
                    ("산출 정보", " 산출 원문 "),
                    ("관련 요구사항", "SFR-003, SFR_002 / SFR-003"),
                ],
                [
                    ("요구사항분류", "데이터 요구사항"),
                    ("요구사항고유번호", "DAR-010"),
                    ("요구사항명칭", "데이터 항목"),
                    ("정의", "데이터 정의"),
                    ("세부내용", "데이터 세부 내용"),
                ],
            ]),
        ]))
    )

    items = payload["inventory_items"]
    assert len(items) == 2
    assert [item["source"] for item in items] == ["label_value_table", "label_value_table"]
    first = items[0]
    assert first["raw_id"] == " SFR-001 "
    assert first["normalized_id"] == "SFR-1"
    assert first["title"] == " 원문 명칭 "
    assert first["card"] == {
        "category": " 기능 요구사항 ",
        "compliance_level": "필수",
        "definition": " 원문 정의 ",
        "details": " 원문 세부 내용 ",
        "outputs": " 산출 원문 ",
        "related_raw": "SFR-003, SFR_002 / SFR-003",
        "related_ids": ["SFR-2", "SFR-3"],
        "table_key": "card-table-1",
        "first_cell_block_key": "card-table-1-r0-c0",
        "card_warnings": [],
        "page_anchor_block_keys": ["paragraph-anchor-3", "paragraph-anchor-2", "paragraph-anchor-1"],
    }
    assert payload["inventory_summary"]["card_item_count"] == 2
    assert payload["inventory_summary"]["label_value_table_count"] == 1
    assert payload["segment_anchors"] == [["paragraph-anchor-3", "paragraph-anchor-2", "paragraph-anchor-1"]]
    assert "segment_anchors" not in document_segments.wire_payload(payload)


def test_card_label_variants_keep_card_and_warn_for_missing_required_field() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks(_requirement_card_table([[
            ("요구사항분류", "기능"),
            ("고유번호", "ECR-007"),
            ("명칭", "변형 라벨 항목"),
            ("세부설명", "세부 설명 원문"),
            ("산출물", "산출물 원문"),
        ]])))
    )

    item = payload["inventory_items"][0]
    assert item["normalized_id"] == "ECR-7"
    assert item["title"] == "변형 라벨 항목"
    assert item["card"]["definition"] == ""
    assert item["card"]["details"] == "세부 설명 원문"
    assert item["card"]["outputs"] == "산출물 원문"
    assert item["card"]["card_warnings"] == ["missing:definition"]


def test_card_table_is_not_column_header_table_and_card_prefix_does_not_confirm_paragraph() -> None:
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "paragraph-mention", "text": "본문에서 SFR-001 참조"},
            *_requirement_card_table([[
                ("요구사항분류", "기능"),
                ("요구사항고유번호", "REQ-001"),
                ("요구사항명칭", "카드 경로"),
                ("정의", "카드 정의"),
                ("세부내용", "카드 상세"),
            ]]),
            *_requirement_table(["REQ-001"], table_key="column-table-1"),
        ]))
    )

    items = payload["inventory_items"]
    assert [(item["normalized_id"], item["source"]) for item in items] == [
        ("REQ-1", "label_value_table"),
        ("REQ-1", "column_header_table"),
    ]
    assert payload["inventory_summary"]["duplicate_ids"] == ["REQ-1"]
    assert "SFR-1" not in payload["inventory_summary"]["expected_ids"]
    assert [segment["start_locator"]["block_key"] for segment in payload["segments"]] == [
        "card-table-1-block",
        "column-table-1-block",
    ]


def test_tokenless_card_is_ignored_and_duplicate_cards_are_both_kept() -> None:
    tokenless = document_segments.build_manifest_payload(
        _structure(_blocks(_requirement_card_table([[
            ("요구사항분류", "기능"),
            ("요구사항번호", "해당 없음"),
            ("요구사항명", "ID 없는 행"),
            ("정의", "정의"),
            ("세부내용", "세부"),
        ]])))
    )
    assert tokenless["inventory_summary"]["card_item_count"] == 0
    assert tokenless["inventory_items"] == []

    duplicate = document_segments.build_manifest_payload(
        _structure(_blocks([
            *_requirement_card_table([[
                ("요구사항분류", "기능"),
                ("요구사항번호", "SFR-001"),
                ("요구사항명", "첫 카드"),
                ("정의", "첫 정의"),
                ("세부내용", "첫 세부"),
            ]], table_key="card-table-1"),
            *_requirement_card_table([[
                ("요구사항분류", "기능"),
                ("요구사항번호", "SFR-001"),
                ("요구사항명", "둘째 카드"),
                ("정의", "둘째 정의"),
                ("세부내용", "둘째 세부"),
            ]], table_key="card-table-2"),
        ]))
    )
    assert [item["normalized_id"] for item in duplicate["inventory_items"]] == ["SFR-1", "SFR-1"]
    assert duplicate["inventory_summary"]["duplicate_ids"] == ["SFR-1"]
    assert duplicate["inventory_summary"]["label_value_table_count"] == 2


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


def test_taxonomy_v2_maps_contract_categories_exactly() -> None:
    expected = {
        "기능": "technical_functional",
        "데이터": "technical_functional",
        "인터페이스": "technical_functional",
        "시스템": "technical_functional",
        "시스템장비구성": "technical_functional",
        "보안": "quality_security_constraints",
        "품질": "quality_security_constraints",
        "성능": "quality_security_constraints",
        "제약": "quality_security_constraints",
        "테스트": "quality_security_constraints",
        "표준": "quality_security_constraints",
        "프로젝트관리": "partnership_governance",
        "프로젝트지원": "partnership_governance",
        "유지관리": "operations_maintenance",
        "유지관리수행": "operations_maintenance",
        "유지관리인력": "operations_maintenance",
        "운영": "operations_maintenance",
    }
    assert document_segments._RULES["category_taxonomy"] == expected
    for category, label in expected.items():
        assert document_segments._category_labels(category) == {label}

    assert document_segments._category_labels(" 시 스 템 장 비 구 성 요 구 사 항 ") == {
        "technical_functional"
    }
    assert document_segments._category_labels(" 유지관리 수행 요구사항 ") == {
        "operations_maintenance"
    }
    assert document_segments._category_labels("기능 분류") == set()
    assert document_segments._category_labels("기능 요구사항 추가") == set()


def test_taxonomy_v2_card_categories_override_title_and_prefix_candidates() -> None:
    card_table = _requirement_card_table([
        _taxonomy_card("STR-001", " 기능 요구사항 "),
        _taxonomy_card("QUR-002", "운영"),
    ], table_key="card-table-category-priority")
    card_table[0]["text"] = "제1장 입찰참가자격"
    payload = document_segments.build_manifest_payload(
        _structure(_blocks(card_table))
    )

    segment = payload["segments"][0]
    assert payload["taxonomy_version"] == "bidops.segment-taxonomy.v2"
    assert segment["taxonomy_labels"] == ["operations_maintenance", "technical_functional"]
    assert segment["status"] == "classified"
    assert not any(warning.startswith("taxonomy_conflict:") for warning in payload["warnings"])


def test_taxonomy_v2_prefix_keywords_and_unknown_categories_keep_existing_review_rule() -> None:
    prefix_tables = [
        *_requirement_card_table([_taxonomy_card("ECR-001", "미분류")], table_key="card-ecr"),
        *_requirement_card_table([_taxonomy_card("STR-002", "미분류")], table_key="card-str"),
        *_requirement_card_table([_taxonomy_card("MAR-003", "미분류")], table_key="card-mar"),
        *_requirement_card_table([_taxonomy_card("MPR-004", "미분류")], table_key="card-mpr"),
        *_requirement_card_table([_taxonomy_card("MHR-005", "미분류")], table_key="card-mhr"),
    ]
    ambiguous_table = _requirement_card_table(
        [_taxonomy_card("SFR-006", "알 수 없는 category")],
        table_key="card-unknown-category",
    )
    ambiguous_table[0]["text"] = "제2장 입찰참가자격"
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            {"block_key": "maintenance-heading", "text": "제1장 장애 대응 체계"},
            *prefix_tables,
            *ambiguous_table,
        ]))
    )

    assert payload["taxonomy_version"] == "bidops.segment-taxonomy.v2"
    assert payload["segments"][0]["taxonomy_labels"] == ["operations_maintenance"]
    assert [segment["taxonomy_labels"] for segment in payload["segments"][1:6]] == [
        ["technical_functional"],
        ["quality_security_constraints"],
        ["operations_maintenance"],
        ["operations_maintenance"],
        ["operations_maintenance"],
    ]
    unknown = payload["segments"][-1]
    assert unknown["taxonomy_labels"] == [
        "business_eligibility_evaluation",
        "technical_functional",
    ]
    assert unknown["status"] == "needs_human_review"
    assert any(warning == f"taxonomy_conflict:{unknown['segment_id']}" for warning in payload["warnings"])


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


def test_card_ids_and_prefixes_feed_inventory_context_and_observed_ids(stored) -> None:
    payload = document_segments.build_manifest_payload(
        _structure(
            _blocks(_requirement_card_table([[
                ("요구사항분류", "기능"),
                ("요구사항번호", "ECR-007"),
                ("요구사항명", "카드 항목"),
                ("정의", "정의 원문"),
                ("세부내용", "세부 원문"),
            ]])),
            structure_id=stored["structure_id"],
            document_version_id=stored["document_id"],
        )
    )
    with Session(stored["engine"]) as session:
        session.add(DocumentSegmentManifest(
            structure_id=stored["structure_id"],
            document_version_id=stored["document_id"],
            source_sha256=payload["source_sha256"],
            taxonomy_version=document_segments.TAXONOMY_VERSION,
            extractor_binding=payload["extractor_binding"],
            extractor_binding_sha256=payload["extractor_binding_sha256"],
            inventory_summary=payload["inventory_summary"],
            warnings=payload["warnings"],
            coverage=payload["coverage"],
            payload_sha256=payload["payload_sha256"],
        ))
        session.commit()
    with Session(stored["engine"]) as session:
        context = document_segments.inventory_context(session, [stored["structure_id"]])

    assert context["expected_ids"] == ["ECR-7"]
    assert context["prefixes"] == ["ECR"]
    assert document_segments.observed_requirement_ids(
        ["ECR-007, ECR_008: 함께 이행한다. ISO-9001은 요구사항이 아니다."],
        context["prefixes"],
    ) == ["ECR-7", "ECR-8"]


def test_wire_payload_satisfies_the_published_contract() -> None:
    from app.deep_review.services.deep_review_validation import (
        DeepReviewValidationError,
        validate_document_segments,
    )
    from app.deep_review.schemas.document_bundles import DocumentSegmentsView

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
    assert DocumentSegmentsView.model_validate(wire).model_dump(mode="json")["schema"] == wire["schema"]
    assert not {"inventory_items", "segment_titles", "segment_anchors"} & wire.keys()

    # STEP-002 publishes the enum additions before STEP-003/004 starts
    # producing them.  Both validation layers must accept the future wire
    # values without exposing the parallel storage-only anchor list.
    inherited = json.loads(json.dumps(wire))
    inherited["segments"][0]["taxonomy_labels"] = ["operations_maintenance"]
    inherited["segments"][0]["mapping_status"] = "inherited"
    inherited["segments"][0]["page_range"] = {"first": 7, "last": 7}
    assert validate_document_segments(inherited) == inherited
    assert DocumentSegmentsView.model_validate(inherited).segments[0].mapping_status == "inherited"

    missing_summary_count = json.loads(json.dumps(wire))
    missing_summary_count["inventory_summary"].pop("card_item_count")
    with pytest.raises(DeepReviewValidationError):
        validate_document_segments(missing_summary_count)


# --------------------------------------------------------------------------
# 대응표 유래 page_range·mapping_status (조회 시 계산, 저장하지 않는다)
# --------------------------------------------------------------------------


def _mapped_structure(stored) -> dict:
    """네 개의 segment가 나오도록 만든 구조 payload."""

    return _structure(
        _blocks([
            {"block_key": "paragraph-1-1", "text": "제1장 입찰참가자격"},
            {"block_key": "paragraph-1-2", "text": "합성 자격 문단."},
            {"block_key": "paragraph-1-3", "text": "제2장 기능 요구사항"},
            *_requirement_table(["SFR-01", "SFR-02"]),
            {"block_key": "paragraph-1-4", "text": "제3장 품질 및 보안 요구사항"},
            {"block_key": "paragraph-1-5", "text": "합성 보안 문단."},
        ]),
        structure_id=stored["structure_id"],
        document_version_id=stored["document_id"],
    )


def _para_page_map() -> dict:
    """``bidops.para-page-map.v1`` 합성 대응표.

    segment 1·2는 전부, segment 3은 일부만, segment 4는 직접 매핑하지 않는다.
    """

    mapped = [
        {"block_key": "paragraph-1-1", "section": 0, "para_index": 0, "page_first": 1, "page_last": 2, "match": "exact"},
        {"block_key": "paragraph-1-2", "section": 0, "para_index": None, "page_first": 2, "page_last": 2, "match": "page_text"},
        {"block_key": "paragraph-1-3", "section": 0, "para_index": None, "page_first": 3, "page_last": 3, "match": "page_text"},
        {"block_key": "table-1-1-block", "section": 0, "para_index": None, "page_first": 4, "page_last": 4, "match": "page_text"},
        {"block_key": "table-1-1-r0-c0", "section": 0, "para_index": None, "page_first": 4, "page_last": 4, "match": "page_text"},
        {"block_key": "table-1-1-r1-c0", "section": 0, "para_index": None, "page_first": 5, "page_last": 5, "match": "page_text"},
    ]
    unmapped = [
        "table-1-1-r0-c1", "table-1-1-r1-c1", "table-1-1-r2-c0", "table-1-1-r2-c1",
        "paragraph-1-4", "paragraph-1-5",
    ]
    return {
        "schema": "bidops.para-page-map.v1",
        "page_count": 5,
        "paragraph_count": 1,
        "paragraphs": [{"section": 0, "para_index": 0, "page_first": 1, "page_last": 2, "kind": "fullParagraph"}],
        "blocks": mapped,
        "unmapped_block_keys": unmapped,
        "mapping": {
            "blocks_total": len(mapped) + len(unmapped),
            "blocks_mapped": len(mapped),
            "blocks_unmapped": len(unmapped),
            "rule": "para-page-align.v1",
        },
    }


def _native_snapshot(stored, store: FilesystemObjectStore, payload_bytes: bytes, *, recorded_sha256: str | None = None) -> None:
    """대응표를 가진 native snapshot 한 행을 만든다.

    ``recorded_sha256``으로 저장된 hash를 실제 바이트와 어긋나게 둘 수 있다.
    """

    digest = hashlib.sha256(payload_bytes).hexdigest()
    metadata = store.put("structure", f"structure/para-page-map/{digest}", payload_bytes, content_type="application/json")
    with Session(stored["engine"]) as session:
        document = session.get(DocumentVersion, stored["document_id"])
        assert document is not None
        pdf_bytes = b"%PDF-1.7\n% synthetic\n"
        pdf_digest = hashlib.sha256(pdf_bytes).hexdigest()
        pdf_metadata = store.put("source", f"source/v4/pdf-{pdf_digest}", pdf_bytes, content_type="application/pdf")
        map_content = ContentObject(sha256=digest, size_bytes=len(payload_bytes), detected_mime="application/json", retention_class="structure")
        pdf_content = ContentObject(sha256=pdf_digest, size_bytes=len(pdf_bytes), detected_mime="application/pdf", retention_class="document-source")
        session.add_all([map_content, pdf_content])
        session.flush()
        map_location = ContentObjectLocation(
            content_object_id=map_content.id, namespace_key="structure", object_key=metadata.object_key,
            object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified",
        )
        pdf_location = ContentObjectLocation(
            content_object_id=pdf_content.id, namespace_key="source", object_key=pdf_metadata.object_key,
            object_version_id=pdf_metadata.object_version_id, etag=pdf_metadata.etag, status="verified",
        )
        session.add_all([map_location, pdf_location])
        session.add(ContentScan(content_object_id=pdf_content.id, scanner="test", scanner_version="1", status="clean", safe_result={"sha256": pdf_digest}))
        session.flush()
        session.add(PrespecV4PdfSnapshot(
            notice_id=document.notice_id,
            document_version_id=document.id,
            source_content_object_id=document.content_object_id,
            source_location_id=pdf_location.id,
            pdf_content_object_id=pdf_content.id,
            pdf_location_id=pdf_location.id,
            page_text_content_object_id=map_content.id,
            page_text_location_id=map_location.id,
            structure_id=stored["structure_id"],
            para_page_map_content_object_id=map_content.id,
            para_page_map_location_id=map_location.id,
            para_page_map_sha256=recorded_sha256 or digest,
            rhwp_binary_sha256="a" * 64,
            rhwp_version="0.8.6",
            source_kind="original",
            source_sha256=SOURCE_SHA,
            source_size_bytes=10,
            pdf_sha256=pdf_digest,
            pdf_size_bytes=len(pdf_bytes),
            pdf_page_count=5,
            page_text_sha256=digest,
            page_text_size_bytes=len(payload_bytes),
            pdf_metadata_jsonb={"schema": "bidops.rhwp-pdf-snapshot.v1", "renderer": "rhwp-svg-pdf", "page_count": 5},
            renderer_jsonb={"renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6"},
            renderer_digest="b" * 64,
            font_jsonb={"font_manifest_sha256": "c" * 64},
            font_digest="c" * 64,
            config_jsonb={"options": {}},
            config_sha256="d" * 64,
            scan_jsonb={"status": "clean"},
            binding_sha256="e" * 64,
        ))
        session.commit()


def _view(stored, store: FilesystemObjectStore | None) -> dict:
    with Session(stored["engine"]) as session:
        return document_segments.segments_view(session, stored["structure_id"], store)


def test_segments_are_unavailable_without_a_para_page_map(stored, tmp_path) -> None:
    with Session(stored["engine"]) as session:
        document_segments.store_manifest(session, _mapped_structure(stored))
        session.commit()
    view = _view(stored, FilesystemObjectStore(tmp_path))
    assert [segment["mapping_status"] for segment in view["segments"]] == ["unavailable"] * 4
    assert all(segment["page_range"] is None for segment in view["segments"])


def test_para_page_map_yields_mapped_partial_and_inherited_segments(stored, tmp_path) -> None:
    with Session(stored["engine"]) as session:
        document_segments.store_manifest(session, _mapped_structure(stored))
        session.commit()
    store = FilesystemObjectStore(tmp_path)
    _native_snapshot(stored, store, json.dumps(_para_page_map(), ensure_ascii=False).encode("utf-8"))
    view = _view(stored, store)
    assert [(segment["mapping_status"], segment["page_range"]) for segment in view["segments"]] == [
        ("mapped", {"first": 1, "last": 2}),
        ("mapped", {"first": 3, "last": 3}),
        ("partial", {"first": 4, "last": 5}),
        ("inherited", {"first": 3, "last": 3}),
    ]
    # 계산값은 저장하지 않는다 — segment 행에는 그런 열이 없다.
    columns = {column.name for column in DocumentSegment.__table__.columns}
    assert not columns & {"page_range", "mapping_status"}


def test_segment_pages_prefers_direct_mapping_over_anchors() -> None:
    block_pages = {
        "direct": (2, 4),
        "anchor-near": (7, 7),
        "anchor-far": (3, 3),
    }
    assert document_segments._segment_pages(
        ["direct"], block_pages, ["anchor-near", "anchor-far"]
    ) == {"page_range": {"first": 2, "last": 4}, "mapping_status": "mapped"}
    assert document_segments._segment_pages(
        ["direct", "unmapped"], block_pages, ["anchor-near", "anchor-far"]
    ) == {"page_range": {"first": 2, "last": 4}, "mapping_status": "partial"}
    assert document_segments._segment_pages(
        ["unmapped"], block_pages, ["anchor-unmapped", "anchor-near", "anchor-far"]
    ) == {"page_range": {"first": 7, "last": 7}, "mapping_status": "inherited"}
    assert document_segments._segment_pages(
        ["unmapped"], block_pages, ["anchor-unmapped"]
    ) == {"page_range": None, "mapping_status": "unavailable"}
    assert document_segments._segment_pages(
        ["direct"], None, ["anchor-near"]
    ) == {"page_range": None, "mapping_status": "unavailable"}


def test_requirement_cards_returns_empty_without_current_manifest(stored, tmp_path) -> None:
    with Session(stored["engine"]) as session:
        cards = document_segments.requirement_cards(
            session,
            stored["structure_id"],
            FilesystemObjectStore(tmp_path),
        )
    assert cards == []


def test_resolve_card_pages_uses_only_card_locator_and_nearest_anchor() -> None:
    card_fields = [
        ("요구사항분류", "기능"),
        ("요구사항번호", "SFR-001"),
        ("요구사항명", "합성 조회"),
        ("정의", "합성 정의"),
        ("세부내용", "합성 상세"),
    ]
    payload = document_segments.build_manifest_payload(
        _structure(_blocks([
            *_requirement_card_table([card_fields], table_key="card-unanchored"),
            {"block_key": "anchor-far", "text": "제1장 기능 요구사항"},
            {"block_key": "anchor-near", "text": "제2장 시스템 기능"},
            *_requirement_card_table(
                [card_fields, [
                    ("요구사항분류", "운영"),
                    ("요구사항번호", "MAR-002"),
                    ("요구사항명", "합성 운영"),
                    ("정의", "합성 운영 정의"),
                    ("세부내용", "합성 운영 상세"),
                ]],
                table_key="card-anchored",
            ),
            *_requirement_table(["REQ-010"], table_key="column-table"),
        ]))
    )
    original = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    page_map = {
        "blocks": [
            {"block_key": "anchor-near", "page_first": 4, "page_last": 5},
            {"block_key": "anchor-far", "page_first": 3, "page_last": 3},
            {"block_key": "card-anchored-r1-c0", "page_first": 8, "page_last": 8},
        ]
    }

    cards = document_segments.resolve_card_pages(payload, page_map)

    assert [card["normalized_id"] for card in cards] == ["SFR-1", "SFR-1", "MAR-2"]
    assert [(card["mapping_status"], card["page_range"]) for card in cards] == [
        ("unavailable", None),
        ("mapped", {"first": 8, "last": 8}),
        ("inherited", {"first": 4, "last": 4}),
    ]
    assert cards[1]["card"]["page_anchor_block_keys"] == ["anchor-near", "anchor-far"]
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == original


def test_para_page_map_hash_mismatch_fails_closed(stored, tmp_path) -> None:
    with Session(stored["engine"]) as session:
        document_segments.store_manifest(session, _mapped_structure(stored))
        session.commit()
    store = FilesystemObjectStore(tmp_path)
    _native_snapshot(
        stored, store, json.dumps(_para_page_map(), ensure_ascii=False).encode("utf-8"),
        recorded_sha256="f" * 64,
    )
    with pytest.raises(document_segments.SegmentViewError) as error:
        _view(stored, store)
    assert error.value.code == "processing_failed"
    assert error.value.status_code == 500
