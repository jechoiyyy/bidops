"""RL-04 STEP-004: deterministic proposal section validation (spec T2·T3).

Spec "문장 계약 `bidops.proposal-section.v1`": sentence kind rules, source
existence and raw-substring quotes per source kind (결정 B42: ``notice_meta``
quote is a substring of the value), requirements coverage of every card unit,
and the forbidden price/staffing/schedule patterns with the source-quote
exception.  Failures are classified schema-class (one repair, 결정 B33 mirror)
vs evidence-class (never repaired).  Pure functions: no DB, model or network,
and the model payload is never modified.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from app.deep_review.services.proposal_validation import (
    EVIDENCE_RULES,
    PROPOSAL_COVERAGE_INCOMPLETE,
    PROPOSAL_FORBIDDEN_CONTENT,
    PROPOSAL_SECTION_INVALID,
    SCHEMA_RULES,
    ProposalSectionInputError,
    company_fact_quote_texts,
    validate_proposal_section,
)

U1_TEXT = "SFR-001 회원 관리 기능을 제공하여야 한다. 응답시간은 3초 이내로 한다."
U2_TEXT = "총 사업비는 150,000,000원(부가세 포함)이며 사업기간은 계약일로부터 6개월 이내 완료한다."
U2_STAFF = "PM 1명 상주 및 개발자 13명 투입을 요구한다."
U3_TEXT = "사업 목적: 공공 웹 접근성 개선"

S = [
    "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b",
    "6f9619ff-8b86-4011-b42d-00c04fc964ff",
    "3d813cbb-47fb-42ba-91df-831e1593ac29",
    "9c858901-8a57-4791-81fe-4c455b099bc9",
    "0e6d2b4a-5a6b-4c8e-9b2f-1f2e3d4c5b6a",
    "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
]


def section_input(section_key: str = "requirements") -> dict[str, Any]:
    return {
        "schema_version": "bidops.proposal-input.v1",
        "purpose": "proposal",
        "section_key": section_key,
        "notice_meta": {
            "title": "2026년 폴리텍 누리집 고도화",
            "agency": "한국폴리텍대학",
            "deadline_at": "2026-11-02T10:00:00+09:00",
            "method": "협상에 의한 계약",
            "estimated_price": None,
        },
        "units": [
            {"unit_id": "unit-1", "kind": "card", "blocks": [{"block_key": "b1", "text": U1_TEXT}]},
            {"unit_id": "unit-2", "kind": "card", "blocks": [
                {"block_key": "b2", "text": U2_TEXT}, {"block_key": "b2s", "text": U2_STAFF}]},
            {"unit_id": "unit-3", "kind": "segment", "blocks": [{"block_key": "b3", "text": U3_TEXT}]},
        ],
        "compares": [],
        "verdict": {"verdict": "조건부 진행", "reason": "확인 필요", "checklist": []},
        "company_facts": [
            {"fact_key": "cert:patents", "type": "qualification", "label": "특허",
             "value": {"held": True, "detail": "등록 8건, 출원 18건", "valid_until": None}},
            {"fact_key": "staff:design_publishing", "type": "staff_group", "label": "디자인·퍼블리싱 인력",
             "value": {"role": "디자인·퍼블리싱", "total": None, "available": 5}},
            {"fact_key": "project:nuri", "type": "project", "label": "충남 누리집 개편",
             "value": {"agency": "충청남도", "year": 2023, "role": None, "extra": {"nested": "x"}}},
        ],
        "missing_facts": [{"fact_key": "qual:credit_rating", "status": "proposed"}],
        "toc_reference": ["Ⅲ-2 기능 요구사항별 수행 방안"],
    }


def statement(sid: str, text: str, *sources: dict[str, str]) -> dict[str, Any]:
    return {"sentence_id": sid, "text": text, "kind": "statement", "sources": list(sources), "placeholder_hint": None}


def src(kind: str, ref: str, quote: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref, "quote": quote}


def valid_section() -> dict[str, Any]:
    return {
        "section_key": "requirements",
        "title": "요구사항 수행방안",
        "paragraphs": [
            {"paragraph_id": "p1", "heading": "회원 관리", "sentences": [
                statement(S[0], "회원 관리 기능을 표준 프레임워크로 구현한다.",
                          src("requirement_unit", "unit-1", "회원 관리 기능을 제공하여야 한다")),
                {"sentence_id": S[1], "text": "응답시간 3초 이내를 목표로 한다.", "kind": "proposed_figure",
                 "sources": [src("requirement_unit", "unit-1", "응답시간은 3초 이내")], "placeholder_hint": None},
            ]},
            {"paragraph_id": "p2", "heading": None, "sentences": [
                statement(S[2], "한국폴리텍대학의 누리집 개편 경험을 살린다.",
                          src("notice_meta", "agency", "폴리텍"),
                          src("company_fact", "project:nuri", "충남 누리집 개편")),
                {"sentence_id": S[3], "text": "투입 인력은 사람이 정한다.", "kind": "placeholder",
                 "sources": [], "placeholder_hint": "투입 인력 수"},
            ]},
        ],
        "requirement_links": [
            {"unit_id": "unit-1", "paragraph_id": "p1"},
            {"unit_id": "unit-2", "paragraph_id": "p2"},
        ],
    }


def sentence(payload: dict[str, Any], paragraph: int, index: int) -> dict[str, Any]:
    return payload["paragraphs"][paragraph]["sentences"][index]


def run(payload: Any, frozen: dict[str, Any] | None = None):
    frozen = section_input() if frozen is None else frozen
    before = deepcopy(payload)
    before_input = deepcopy(frozen)
    result = validate_proposal_section(payload, section_input=frozen)
    assert payload == before, "validator must never modify the model output"
    assert frozen == before_input
    return result


def violation_codes(result) -> list[str]:
    return [violation.rule_code for violation in result.violations]


# --- valid -----------------------------------------------------------------------------


def test_valid_section_passes_without_changes() -> None:
    result = run(valid_section())
    assert result.ok is True
    assert result.error_code is None
    assert result.violations == ()
    assert result.rule_codes == ()
    assert result.repairable is False


def test_rule_classes_are_disjoint_and_named_like_rl03() -> None:
    assert not SCHEMA_RULES & EVIDENCE_RULES
    import re
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{2,63}", code) for code in SCHEMA_RULES | EVIDENCE_RULES)


# --- T2: kind rules (schema-class, one repair) -----------------------------------------


def test_statement_without_sources_is_schema_class_failure() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["sources"] = []
    result = run(payload)
    assert not result.ok
    assert result.error_code == PROPOSAL_SECTION_INVALID
    assert violation_codes(result) == ["statement_sources_required"]
    assert result.repairable is True
    violation = result.violations[0]
    assert (violation.paragraph_index, violation.sentence_index) == (0, 0)


def test_proposed_figure_needs_sources_and_a_number() -> None:
    payload = valid_section()
    sentence(payload, 0, 1)["sources"] = []
    sentence(payload, 0, 1)["text"] = "응답시간을 빠르게 한다."
    result = run(payload)
    assert result.error_code == PROPOSAL_SECTION_INVALID
    assert sorted(violation_codes(result)) == ["proposed_figure_number_required", "proposed_figure_sources_required"]
    assert result.repairable is True


def test_placeholder_without_hint_or_with_sources_fails() -> None:
    payload = valid_section()
    sentence(payload, 1, 1)["placeholder_hint"] = None
    result = run(payload)
    assert violation_codes(result) == ["placeholder_hint_required"]
    assert result.repairable is True

    payload = valid_section()
    sentence(payload, 1, 1)["placeholder_hint"] = "   "
    assert violation_codes(run(payload)) == ["placeholder_hint_required"]

    payload = valid_section()
    sentence(payload, 1, 1)["sources"] = [src("notice_meta", "agency", "폴리텍")]
    result = run(payload)
    assert violation_codes(result) == ["placeholder_sources_forbidden"]
    assert result.repairable is True


def test_hint_on_non_placeholder_is_rejected() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["placeholder_hint"] = "가격"
    result = run(payload)
    assert violation_codes(result) == ["placeholder_hint_forbidden"]
    assert result.repairable is True


def test_blank_text_is_rejected() -> None:
    payload = valid_section()
    sentence(payload, 1, 1)["text"] = "  "
    assert violation_codes(run(payload)) == ["sentence_text_blank"]


def test_duplicate_sentence_and_paragraph_ids_and_section_key() -> None:
    payload = valid_section()
    sentence(payload, 1, 0)["sentence_id"] = S[0]
    result = run(payload)
    assert violation_codes(result) == ["sentence_id_duplicate"]
    assert (result.violations[0].paragraph_index, result.violations[0].sentence_index) == (1, 0)

    payload = valid_section()
    payload["paragraphs"][1]["paragraph_id"] = "p1"
    result = run(payload)
    # p2 no longer exists, so its link is also unknown; unit-2 is still covered by that link
    assert result.rule_codes == ("paragraph_id_duplicate", "requirement_link_paragraph_unknown")
    assert result.repairable is True

    payload = valid_section()
    payload["section_key"] = "strategy"
    result = run(payload)
    assert violation_codes(result) == ["section_key_mismatch"]
    assert result.repairable is True


def test_output_schema_failure_short_circuits_with_location() -> None:
    payload = valid_section()
    sentence(payload, 1, 0)["sentence_id"] = "not-a-uuid"
    result = run(payload)
    assert result.error_code == PROPOSAL_SECTION_INVALID
    assert violation_codes(result) == ["output_schema"]
    assert result.repairable is True
    assert (result.violations[0].paragraph_index, result.violations[0].sentence_index) == (1, 0)

    payload = valid_section()
    sentence(payload, 0, 0)["text"] = "가" * 401
    assert violation_codes(run(payload)) == ["output_schema"]

    payload = valid_section()
    payload["extra"] = 1
    assert violation_codes(run(payload)) == ["output_schema"]

    result = run(["not", "an", "object"])
    assert violation_codes(result) == ["output_schema"]
    assert result.repairable is True


def test_requirement_link_to_unknown_paragraph_is_schema_class() -> None:
    payload = valid_section()
    payload["requirement_links"].append({"unit_id": "unit-1", "paragraph_id": "p9"})
    result = run(payload)
    assert violation_codes(result) == ["requirement_link_paragraph_unknown"]
    assert result.violations[0].link_index == 2
    assert result.repairable is True


# --- T2: sources and quotes (evidence-class, never repaired) ---------------------------


def test_requirement_unit_quote_must_be_raw_substring_of_one_block() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0]["quote"] = "회원 관리 기능을  제공하여야 한다"  # extra space
    result = run(payload)
    assert result.error_code == PROPOSAL_SECTION_INVALID
    assert violation_codes(result) == ["source_quote_mismatch"]
    assert result.repairable is False
    violation = result.violations[0]
    assert (violation.paragraph_index, violation.sentence_index, violation.source_index) == (0, 0, 0)

    payload = valid_section()  # spans two blocks of unit-2: not one block
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", "완료한다.\nPM")
    assert violation_codes(run(payload)) == ["source_quote_mismatch"]

    payload = valid_section()  # quote of another unit
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-3", "회원 관리 기능")
    assert violation_codes(run(payload)) == ["source_quote_mismatch"]


def test_unknown_source_refs_are_evidence_failures() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-9", "회원")
    assert violation_codes(run(payload)) == ["source_unit_unknown"]

    payload = valid_section()  # a missing (proposed) fact is never a source
    sentence(payload, 0, 0)["sources"][0] = src("company_fact", "qual:credit_rating", "BBB0")
    result = run(payload)
    assert violation_codes(result) == ["source_fact_unknown"]
    assert result.repairable is False

    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0] = src("notice_meta", "budget", "폴리텍")
    assert violation_codes(run(payload)) == ["source_meta_unknown"]


def test_company_fact_quote_texts_join_sorted_scalars_without_nulls() -> None:
    facts = {fact["fact_key"]: fact for fact in section_input()["company_facts"]}
    assert company_fact_quote_texts(facts["cert:patents"]) == ("특허", "등록 8건, 출원 18건 · true")
    assert company_fact_quote_texts(facts["staff:design_publishing"]) == ("디자인·퍼블리싱 인력", "5 · 디자인·퍼블리싱")
    # nested objects are not scalars; year keeps its JSON form
    assert company_fact_quote_texts(facts["project:nuri"]) == ("충남 누리집 개편", "충청남도 · 2023")
    assert company_fact_quote_texts({"fact_key": "k", "label": "L", "value": "단일 값"}) == ("L", "단일 값")
    assert company_fact_quote_texts({"fact_key": "k", "label": "L", "value": None}) == ("L", "")


@pytest.mark.parametrize("quote, ok", [
    ("특허", True),
    ("등록 8건, 출원 18건 · true", True),
    ("출원 18건", True),
    ("등록 8건, 출원 18건 · True", False),
    ("None", False),
    ("등록 8건 · 출원 18건", False),
])
def test_company_fact_quote_rules(quote: str, ok: bool) -> None:
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][1] = src("company_fact", "cert:patents", quote)
    result = run(payload)
    assert result.ok is ok
    if not ok:
        assert violation_codes(result) == ["source_quote_mismatch"]


def test_company_fact_value_order_follows_sorted_keys() -> None:
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][1] = src("company_fact", "staff:design_publishing", "5 · 디자인")
    assert run(payload).ok
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][1] = src("company_fact", "staff:design_publishing", "디자인·퍼블리싱 · 5")
    assert violation_codes(run(payload)) == ["source_quote_mismatch"]


def test_notice_meta_quote_is_substring_of_value_and_null_value_cannot_be_quoted() -> None:
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][0] = src("notice_meta", "title", "2026년 폴리텍 누리집 고도화")
    assert run(payload).ok
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][0] = src("notice_meta", "agency", "폴리텍 대학")
    assert violation_codes(run(payload)) == ["source_quote_mismatch"]
    payload = valid_section()
    sentence(payload, 1, 0)["sources"][0] = src("notice_meta", "estimated_price", "1")
    assert violation_codes(run(payload)) == ["source_quote_mismatch"]


@pytest.mark.parametrize("quote", [
    "3명 투입",          # cut from "13명 투입" (front)
    "50,000,000원",      # cut from "150,000,000원" (front)
    "000,000원",         # cut after a thousands separator (front)
    "150,000",           # stops inside "150,000,000" (back)
    "PM 1명 상주 및 개발자 1",  # stops inside "13" (back)
])
def test_quote_that_cuts_a_number_is_truncated(quote: str) -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", quote)
    result = run(payload)
    assert violation_codes(result) == ["source_quote_truncated"]
    assert result.repairable is False


def test_untruncated_number_quotes_pass_even_before_a_unit_word() -> None:
    # Only digit-level cuts are rejected; a whole number before its unit/comparator is that number.
    for quote in ("13명 투입", "150,000,000원", "6개월 이내 완료", "응답시간은 3"):
        payload = valid_section()
        unit = "unit-1" if quote.startswith("응답") else "unit-2"
        sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", unit, quote)
        assert run(payload).ok, quote


def test_truncation_accepts_a_clean_occurrence_elsewhere() -> None:
    frozen = section_input()
    frozen["units"][2]["blocks"].append({"block_key": "b4", "text": "기준 13억원, 별도 3억원"})
    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-3", "3억원")
    assert run(payload, frozen).ok


# --- T2: forbidden content -------------------------------------------------------------


@pytest.mark.parametrize("text, code", [
    ("사업비는 1억원 규모로 수행한다.", "forbidden_amount"),
    ("총 2,500 천원을 제안한다.", "forbidden_amount"),
    ("PM 2명 상주를 제안한다.", "forbidden_staffing"),
    ("개발자 4인 투입으로 수행한다.", "forbidden_staffing"),
    ("3개월 내 구축을 약속한다.", "forbidden_schedule"),
    ("착수 후 30일 이내 완료한다.", "forbidden_schedule"),
])
def test_forbidden_content_without_quote_is_rejected(text: str, code: str) -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["text"] = text
    result = run(payload)
    assert result.error_code == PROPOSAL_FORBIDDEN_CONTENT
    assert violation_codes(result) == [code]
    assert result.repairable is False
    assert (result.violations[0].paragraph_index, result.violations[0].sentence_index) == (0, 0)


def test_forbidden_content_also_applies_to_proposed_figure_but_not_placeholder() -> None:
    payload = valid_section()
    sentence(payload, 0, 1)["text"] = "응답시간 3초, 개발자 5명 투입을 제안한다."
    assert violation_codes(run(payload)) == ["forbidden_staffing"]

    payload = valid_section()
    sentence(payload, 1, 1)["text"] = "가격 1억원과 인원 3명 투입은 사람이 정한다."
    assert run(payload).ok


@pytest.mark.parametrize("text, quote", [
    ("총 사업비 150,000,000원 범위에서 수행한다.", "총 사업비는 150,000,000원"),
    ("계약일로부터 6개월 이내 완료 일정을 따른다.", "6개월 이내 완료"),
    ("PM 1명 상주 요구를 따른다.", "PM 1명 상주"),
])
def test_source_quote_with_the_same_number_is_the_allowed_exception(text: str, quote: str) -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["text"] = text
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", quote)
    assert run(payload).ok


def test_notice_meta_quote_counts_for_the_exception() -> None:
    frozen = section_input()
    frozen["notice_meta"]["estimated_price"] = "136,363,636원"
    payload = valid_section()
    sentence(payload, 0, 0)["text"] = "추정가격 136,363,636원 사업이다."
    sentence(payload, 0, 0)["sources"][0] = src("notice_meta", "estimated_price", "136,363,636")
    assert run(payload, frozen).ok


def test_company_fact_quote_does_not_exempt_forbidden_content() -> None:
    # B43: an available-staff count from the company file is not a staffing commitment for this project.
    payload = valid_section()
    sentence(payload, 0, 0)["text"] = "디자인·퍼블리싱 인력 5명 투입한다."
    sentence(payload, 0, 0)["sources"][0] = src("company_fact", "staff:design_publishing", "5 · 디자인·퍼블리싱")
    result = run(payload)
    assert result.error_code == PROPOSAL_FORBIDDEN_CONTENT
    assert violation_codes(result) == ["forbidden_staffing"]
    assert result.repairable is False


def test_exception_needs_the_whole_number_token_not_a_digit_inside_another() -> None:
    payload = valid_section()  # "1" occurs in the quote only inside "150,000,000"
    sentence(payload, 0, 0)["text"] = "사업비 1억원 규모다."
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", "150,000,000원")
    assert violation_codes(run(payload)) == ["forbidden_amount"]

    payload = valid_section()  # "1.5" is one number; "5" alone in the quote does not exempt it
    sentence(payload, 0, 0)["text"] = "사업비 1.5억원 규모다."
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-1", "3초")
    assert violation_codes(run(payload)) == ["forbidden_amount"]

    payload = valid_section()  # the number must be written the same way ("그대로")
    sentence(payload, 0, 0)["text"] = "총 사업비 150000000원 범위다."
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", "150,000,000원")
    assert violation_codes(run(payload)) == ["forbidden_amount"]


def test_exception_ignores_quotes_that_fail_verification() -> None:
    payload = valid_section()  # truncated quote carries "50,000,000" but is not valid evidence
    sentence(payload, 0, 0)["text"] = "사업비 50,000,000원 규모다."
    sentence(payload, 0, 0)["sources"][0] = src("requirement_unit", "unit-2", "50,000,000원")
    result = run(payload)
    assert result.error_code == PROPOSAL_FORBIDDEN_CONTENT
    assert sorted(violation_codes(result)) == ["forbidden_amount", "source_quote_truncated"]
    assert result.repairable is False


def test_forbidden_wins_over_schema_class_and_blocks_repair() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["text"] = "PM 2명 상주를 제안한다."
    sentence(payload, 1, 1)["placeholder_hint"] = None
    result = run(payload)
    assert result.error_code == PROPOSAL_FORBIDDEN_CONTENT
    assert result.rule_codes == ("forbidden_staffing", "placeholder_hint_required")
    assert result.repairable is False


# --- T3: requirements coverage ---------------------------------------------------------


def test_requirements_section_missing_one_card_unit_is_coverage_incomplete() -> None:
    payload = valid_section()
    payload["requirement_links"] = [{"unit_id": "unit-1", "paragraph_id": "p1"}]
    result = run(payload)
    assert result.error_code == PROPOSAL_COVERAGE_INCOMPLETE
    assert violation_codes(result) == ["requirement_coverage_missing"]
    assert result.violations[0].unit_index == 1
    assert result.repairable is False


def test_segment_units_are_not_required_and_other_sections_need_no_coverage() -> None:
    assert run(valid_section()).ok  # unit-3 (segment) is not linked

    payload = valid_section()
    payload["section_key"] = "strategy"
    payload["requirement_links"] = []
    assert run(payload, section_input("strategy")).ok


def test_requirement_link_to_a_unit_outside_this_input_is_rejected() -> None:
    payload = valid_section()
    payload["requirement_links"].append({"unit_id": "unit-x", "paragraph_id": "p1"})
    result = run(payload)
    assert result.error_code == PROPOSAL_SECTION_INVALID
    assert violation_codes(result) == ["requirement_link_unit_unknown"]
    assert result.violations[0].link_index == 2
    assert result.repairable is False


def test_coverage_counts_a_link_even_if_its_paragraph_is_wrong() -> None:
    payload = valid_section()
    payload["requirement_links"][1]["paragraph_id"] = "p9"
    result = run(payload)
    assert violation_codes(result) == ["requirement_link_paragraph_unknown"]
    assert result.repairable is True


# --- result shape and input errors -----------------------------------------------------


def test_safe_detail_carries_codes_and_indexes_only() -> None:
    payload = valid_section()
    sentence(payload, 0, 0)["sources"][0]["quote"] = "없는 인용 문구"
    sentence(payload, 0, 0)["text"] = "사업비 9억원 규모다."
    detail = run(payload).safe_detail()
    assert set(detail) == {"error_code", "repairable", "rule_codes", "violations"}
    text = json.dumps(detail, ensure_ascii=False)
    assert "없는 인용" not in text and "9억원" not in text and "unit-1" not in text
    for violation in detail["violations"]:
        assert set(violation) == {
            "rule_code", "paragraph_index", "sentence_index", "source_index", "link_index", "unit_index"}
        assert all(value is None or type(value) is int
                   for key, value in violation.items() if key != "rule_code")


@pytest.mark.parametrize("mutate", [
    lambda frozen: frozen.pop("units"),
    lambda frozen: frozen.update(section_key="pricing"),
    lambda frozen: frozen["units"].append(dict(frozen["units"][0])),
    lambda frozen: frozen["company_facts"].append(dict(frozen["company_facts"][0])),
    lambda frozen: frozen["notice_meta"].pop("method"),
    lambda frozen: frozen["units"][0].update(kind="table"),
])
def test_malformed_frozen_input_raises(mutate) -> None:
    frozen = section_input()
    mutate(frozen)
    with pytest.raises(ProposalSectionInputError):
        validate_proposal_section(valid_section(), section_input=frozen)
