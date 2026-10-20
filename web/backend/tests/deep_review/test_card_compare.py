"""RL-03 deterministic compare (spec T1 compare part: HP-03 T4 with the Rootlab allowlist).

* company values are read only through ``CARD_COMPARE_FACT_PATHS`` /
  ``card_fact_value``; facts outside the list are not linked (unmapped);
* ``proposed`` → ``proposed_fact`` (unknown), ``unknown``/null → ``unknown_fact``;
  an unknown never becomes ``gap``;
* the Rootlab v2 fixture shapes: 직접생산 ``detail`` null → unknown, 지역제한 by
  ``qual:branch.value.detail`` ("대구(본점), 세종"), 디자인 인력 by
  ``staff:design_publishing.value.available`` (5), 총 인원 58, 상주 6.

Pure compare on frozen mappings; the Rootlab facts are frozen through the
real STEP-004 builder in an isolated SQLite database.  No model or network.
"""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.deep_review.schemas.card_analysis import CardRequirementExtract
from app.deep_review.services.card_analysis import CardAnalysisValidationError
from app.deep_review.services.card_compare import compare_requirements, validate_requirement_compare
from app.deep_review.services.card_units import (
    card_company_binding,
    card_requirement_units,
    freeze_card_analysis_input,
    select_analysis_units,
)
from app.deep_review.services.company_analysis_input import (
    build_company_analysis_input_v2,
    resolve_company_knowledge_context,
)
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
)
from app.deep_review.services.company_knowledge_retrieval import requirements_from_source_units
from tests.deep_review.test_card_analysis import _source, card_input, constraint, extract_item
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store


ROOTLAB_DIR = Path(os.environ.get("BIDOPS_ROOTLAB_FIXTURE_DIR", str(Path.home() / "orca/fixtures/company/rootlab")))
ROOTLAB_SOURCE = ROOTLAB_DIR / "rootlab.source.v2.json"
ROOTLAB_ONTOLOGY = ROOTLAB_DIR / "ontology.v2.json"
needs_rootlab = pytest.mark.skipif(
    not (ROOTLAB_SOURCE.is_file() and ROOTLAB_ONTOLOGY.is_file()),
    reason="Rootlab v2 fixture (outside Git) is not available",
)


# --- synthetic frozen company part ----------------------------------------------------


def _fact(key: str, status: str, value, origin: str = "user_interview") -> dict:
    return {"fact_key": key, "status": status, "origin": origin if status != "proposed" else "agent_proposal",
            "value": value, "quote": "" if status == "unknown" else "회사 등록 사실", "locator": {"fact_key": key}}


def _evidence_row(key: str) -> dict:
    return {"profile_evidence_id": str(uuid4()), "profile_version_id": str(uuid4()), "fact_key": key,
            "source_sha256": "e" * 64, "locator_type": "profile_fact", "locator": {"fact_key": key},
            "quote": "회사 등록 사실", "origin": "user_interview"}


def synthetic_company(facts: list[dict]) -> dict:
    return {
        "profile_facts": facts,
        "profile_evidence": [_evidence_row(row["fact_key"]) for row in facts if row["status"] == "confirmed"],
        "graph_nodes": [], "graph_edges": [], "graph_paths": [],
    }


def frozen_for(texts: list[str], company: dict) -> tuple[dict, list]:
    card = card_input(texts)
    frozen = {"card_analysis": card.model_dump(mode="json"), **deepcopy(company)}
    return frozen, card.units


def compare_one(frozen: dict, item: dict):
    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1",
                                                     "items": [item]})
    return compare_requirements(extract, frozen=frozen).items[0]


def compare_all(frozen: dict, items: list[dict]):
    """Compare item lists batch by batch (compare accepts exactly one frozen batch)."""

    by_id = {item["unit_id"]: item for item in items}
    rows = []
    for batch in frozen["card_analysis"]["batches"]:
        extract = CardRequirementExtract.model_validate({
            "schema_version": "bidops.requirement-extract.v1", "items": [by_id[key] for key in batch["unit_ids"]],
        })
        rows.extend(compare_requirements(extract, frozen=frozen).items)
    return rows


def count_item(unit, text: str, value: int, *, operator: str = "gte", type_: str = "인력") -> dict:
    return extract_item(unit, type_=type_, constraints=[
        constraint(unit, kind="count", value=value, unit_name="person", operator=operator, quote=text)])


# --- synthetic: status rules ------------------------------------------------------------


def test_unknown_or_null_company_facts_are_unknown_never_gap() -> None:
    texts = ["상주 인원 3명 이상", "총인원 50명 이상", "디자인 인력 2명 이상"]
    company = synthetic_company([
        _fact("staff:onsite", "unknown", None),
        _fact("staff:total", "confirmed", {"total": None, "available": None}),
        _fact("staff:design_publishing", "inferred", {"available": 9}),
    ])
    frozen, units = frozen_for(texts, company)
    rows = compare_all(frozen, [count_item(units[index], texts[index], value)
                                for index, value in enumerate((3, 50, 2))])
    assert [row.fit_status for row in rows] == ["unknown", "unknown", "unknown"]
    assert [row.constraint_results[0].reason_code for row in rows] == ["unknown_fact"] * 3
    assert all(row.evidence_ids == [] for row in rows)
    # a fact missing from the frozen input is unknown too (no fact id invented)
    frozen, units = frozen_for(texts[:1], synthetic_company([]))
    row = compare_one(frozen, count_item(units[0], texts[0], 3))
    assert (row.fit_status, row.constraint_results[0].reason_code, row.constraint_results[0].fact_ids) == (
        "unknown", "unknown_fact", [])


def test_proposed_fact_is_marked_and_never_evidence() -> None:
    text = "신용평가등급 BB 이상"
    company = synthetic_company([_fact("qual:credit_rating", "proposed", {"held": True, "detail": "BBB0"})])
    frozen, units = frozen_for([text], company)
    row = compare_one(frozen, extract_item(units[0], constraints=[
        constraint(units[0], kind="text", value="BB", unit_name=None, operator="gte", quote=text)]))
    assert row.fit_status == "unknown"
    assert row.constraint_results[0].reason_code == "proposed_fact"
    assert row.constraint_results[0].fact_ids == ["qual:credit_rating"]
    assert row.reason_codes == ["proposed_fact"] and row.evidence_ids == []


def test_confirmed_contradiction_is_the_only_gap_and_match_cites_confirmed_evidence() -> None:
    texts = ["상주 인원 8명 이상", "상주 인원 3명 이상"]
    company = synthetic_company([_fact("staff:onsite", "confirmed", {"available": 6, "region": "대구"})])
    frozen, units = frozen_for(texts, company)
    gap, met = compare_all(frozen, [count_item(units[0], texts[0], 8), count_item(units[1], texts[1], 3)])
    assert (gap.fit_status, gap.constraint_results[0].reason_code) == ("gap", "confirmed_contradiction")
    assert (met.fit_status, met.constraint_results[0].reason_code) == ("met", "confirmed_match")
    evidence_id = UUID(frozen["profile_evidence"][0]["profile_evidence_id"])
    assert gap.evidence_ids == [evidence_id] and met.evidence_ids == [evidence_id]


def test_allowlist_outside_operator_unknown_contract_scope_and_incomplete_units_stay_unknown() -> None:
    texts = [
        "사회적기업 인증 보유 시 가점",       # not allowlisted (bonus item) → unmapped
        "상주 인원 2/3명",                  # ambiguous operator
        "손해배상 조건 수용",                # 계약
        "현재 가용 개발자 상주 인원 2명",      # role/current-availability scope
        "상주 인원 3명 이상 및 ISMS 보유 필수",  # second atom omitted by the extraction
        "최근 3년 총인원 50명 이상",          # scope term
    ]
    company = synthetic_company([
        _fact("staff:onsite", "confirmed", {"available": 6, "region": "대구"}),
        _fact("staff:total", "confirmed", {"total": 58}),
        _fact("qual:social_enterprise", "confirmed", {"held": True, "detail": "사회적기업"}),
    ])
    frozen, units = frozen_for(texts, company)
    rows = compare_all(frozen, [
        extract_item(units[0], constraints=[
            constraint(units[0], kind="text", value="사회적기업", unit_name=None, operator="eq", quote=texts[0])]),
        extract_item(units[1], type_="인력", constraints=[
            constraint(units[1], kind="count", value=2, unit_name="person", operator="unknown", quote=texts[1])],
            unknowns=["2명 또는 3명 미확인"]),
        extract_item(units[2], type_="계약", constraints=[
            constraint(units[2], kind="text", value=texts[2], unit_name=None, operator="eq", quote=texts[2])]),
        count_item(units[3], texts[3], 2, operator="eq"),
        count_item(units[4], "상주 인원 3명 이상", 3),
        count_item(units[5], texts[5], 50),
    ])
    assert [row.fit_status for row in rows] == ["unknown"] * 6
    assert rows[0].constraint_results[0].reason_code == "unmapped"
    assert rows[1].constraint_results[0].reason_code == "unsupported_comparison"
    assert "incomplete_unit" in rows[1].reason_codes
    assert "contract_unaccepted" in rows[2].reason_codes
    assert rows[3].constraint_results[0].reason_code == "scope_unverified"
    assert rows[4].constraint_results[0].reason_code == "confirmed_match"  # atom met, unit still unknown
    assert "incomplete_unit" in rows[4].reason_codes
    assert rows[5].constraint_results[0].reason_code == "scope_unverified"


def test_c21_text_value_outside_its_quote_does_not_cover_another_clause() -> None:
    """결정 C21(리뷰 권고): a v11 summarized text value that is not verbatim in its quote
    must not mark a different source clause as covered; a verbatim value still does."""

    from app.deep_review.schemas.card_analysis import CardAnalysisUnit, CardRequirementExtractItem
    from app.deep_review.services.card_compare import _atomic_coverage_incomplete

    texts = ["보안서약서 제출 및 발주기관 사전승인"]
    company = synthetic_company([_fact("qual:sanction_free", "confirmed", {"held": True, "detail": None})])
    _frozen, units = frozen_for(texts, company)
    # clause 1 is covered by a verbatim value; clause 2 only by a summarized value whose
    # quote does not contain it -- before C21 that summary marked clause 2 covered.
    summarized = extract_item(units[0], type_="계약", constraints=[
        constraint(units[0], kind="text", value="보안서약서 제출", unit_name=None, operator="eq",
                   quote="보안서약서 제출"),
        constraint(units[0], kind="text", value="발주기관 사전승인", unit_name=None, operator="eq",
                   quote="보안서약서 제출 및 발주기관"),
    ])
    verbatim = extract_item(units[0], type_="계약", constraints=[
        constraint(units[0], kind="text", value="보안서약서 제출", unit_name=None, operator="eq",
                   quote="보안서약서 제출"),
        constraint(units[0], kind="text", value="발주기관 사전승인", unit_name=None, operator="eq",
                   quote="발주기관 사전승인"),
    ])
    unit = units[0] if isinstance(units[0], CardAnalysisUnit) else CardAnalysisUnit.model_validate(units[0])
    as_item = CardRequirementExtractItem.model_validate
    assert _atomic_coverage_incomplete(as_item(summarized), unit) is True
    assert _atomic_coverage_incomplete(as_item(verbatim), unit) is False


def test_concept_paths_defer_to_the_allowlist_and_refuse_other_targets() -> None:
    texts = ["직접생산확인증명서 제출", "사회적기업 인증", "신용평가등급 확인"]
    company = synthetic_company([
        _fact("qual:direct_production", "confirmed", {"held": True, "detail": None}),
        _fact("qual:social_enterprise", "confirmed", {"held": True, "detail": "사회적기업"}),
        _fact("qual:credit_rating", "proposed", {"held": True, "detail": "BBB0"}),
    ])
    frozen, units = frozen_for(texts, company)

    def node(node_id, type_, status, concept=None):
        origin = "agent_proposal" if status == "proposed" else "user_interview"
        return {"id": node_id, "type": type_, "label": node_id, "concept_id": concept, "status": status,
                "origin": origin, "value": None, "evidence_ids": []}

    def edge(edge_id, to_id, status="confirmed"):
        origin = "agent_proposal" if status == "proposed" else "user_interview"
        return {"id": edge_id, "type": "holds_qualification", "from_id": "company:rootlab", "to_id": to_id,
                "status": status, "origin": origin, "evidence_ids": []}

    frozen["graph_nodes"] = [
        node("company:rootlab", "company", "confirmed"),
        node("qual:direct_production", "qualification", "confirmed", "qual.direct-production"),
        node("qual:social_enterprise", "qualification", "confirmed", "rl.qualification.06"),
        node("qual:credit_rating", "qualification", "proposed", "rl.qualification.03"),
    ]
    frozen["graph_edges"] = [edge("e1", "qual:direct_production"), edge("e2", "qual:social_enterprise"),
                             edge("e3", "qual:credit_rating", "proposed")]
    frozen["graph_paths"] = [
        {"requirement_id": units[index].unit_id, "node_ids": ["company:rootlab", target], "edge_ids": [edge_id],
         "profile_evidence_ids": [], "relation": "direct"}
        for index, (target, edge_id) in enumerate((("qual:direct_production", "e1"),
                                                   ("qual:social_enterprise", "e2"),
                                                   ("qual:credit_rating", "e3")))
    ]
    rows = compare_all(frozen, [
        extract_item(units[0], concepts=[{"concept_id": "qual.direct-production", "alias_text": "직접생산확인증명서"}]),
        extract_item(units[1], concepts=[{"concept_id": "rl.qualification.06", "alias_text": "사회적기업"}]),
        extract_item(units[2], concepts=[{"concept_id": "rl.qualification.03", "alias_text": "신용평가등급"}]),
    ])
    assert [row.fit_status for row in rows] == ["unknown"] * 3
    assert "scope_unverified" in rows[0].reason_codes and "confirmed_match" not in rows[0].reason_codes
    assert "unmapped" in rows[1].reason_codes
    assert "proposed_fact" in rows[2].reason_codes


def test_compare_validator_rejects_status_reason_mismatch_and_promotion() -> None:
    text = "상주 인원 3명 이상"
    company = synthetic_company([_fact("staff:onsite", "confirmed", {"available": 6, "region": "대구"})])
    frozen, units = frozen_for([text], company)
    item = count_item(units[0], text, 3)
    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1",
                                                     "items": [item]})
    result = compare_requirements(extract, frozen=frozen).model_dump(mode="json")
    facts = ["staff:onsite"]
    evidence = [UUID(row["profile_evidence_id"]) for row in frozen["profile_evidence"]]
    validate_requirement_compare(result, extract=extract, graph_paths=[], known_fact_ids=facts,
                                 known_evidence_ids=evidence)
    for mutate in (
        lambda row: row["constraint_results"][0].update(reason_code="proposed_fact"),  # met with proposed
        lambda row: row.update(fit_status="gap"),
        lambda row: row["constraint_results"][0].update(fact_ids=["staff:unknown"]),
        lambda row: row.update(reason_codes=["proposed_fact", "confirmed_match"]),
    ):
        changed = deepcopy(result)
        mutate(changed["items"][0])
        with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):
            validate_requirement_compare(changed, extract=extract, graph_paths=[], known_fact_ids=facts,
                                         known_evidence_ids=evidence)


def test_compare_refuses_an_extract_that_is_not_one_frozen_batch() -> None:
    frozen, units = frozen_for(["상주 인원 3명 이상"], synthetic_company([]))
    other = card_input(["다른 요구"]).units[0]
    with pytest.raises(CardAnalysisValidationError, match="card_compare_invalid"):
        compare_one(frozen, extract_item(other))


# --- Rootlab v2 fixture (T1) --------------------------------------------------------------


@pytest.fixture
def rootlab_company():
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    with Session(bind) as session:
        prepared = prepare_company_knowledge(ROOTLAB_ONTOLOGY.read_bytes(), ROOTLAB_SOURCE.read_bytes())
        imported = import_company_knowledge(session, prepared, actor="등록 담당자")
        activate_company_knowledge(session, company_id=imported.company_id,
                                   graph_version_id=imported.graph_version_id, actor="활성 담당자")
        session.flush()
        knowledge = resolve_company_knowledge_context(session, imported.company_id)
        source = _source()
        card = freeze_card_analysis_input(select_analysis_units([source]),
                                          company_binding=card_company_binding(knowledge))
        bundle = {"documents": [{"document_version_id": str(source["document_version_id"]), "ordinal": 0}]}
        units = card_requirement_units(card, bundle, {str(source["structure_id"]): {"blocks": source["blocks"]}})
        frozen = build_company_analysis_input_v2(
            card_analysis=card.model_dump(mode="json"), purpose="deep_review", execution_nonce=uuid4(),
            knowledge=knowledge, notice_id=101, document_version_ids=[source["document_version_id"]],
            policy_version_id=uuid4(), policy_sha256="e" * 64, model_name="gpt-6-luna", model_revision=None,
            generation={"reasoning_effort": "high"},
            requirements=requirements_from_source_units(units, knowledge.ontology),
            path_limit_per_requirement=32, profile_characters=8000, bundle_id=uuid4(), target_review_id=None,
        )
    bind.dispose()
    # Synthetic requirement units are compared against the real frozen company part.
    return {key: frozen[key] for key in ("profile_facts", "profile_evidence", "graph_nodes", "graph_edges")} | {
        "graph_paths": []}


@needs_rootlab
def test_t1_rootlab_v2_values_drive_met_gap_and_unknown(rootlab_company) -> None:
    texts = [
        "상주 인원 3명 이상",                                        # staff:onsite.available 6
        "상주 인원 8명 이상",
        "총인원 50명 이상",                                          # staff:total.total 58
        "디자인 인력 3명 이상",                                       # staff:design_publishing.available 5
        "디자인 인력 6명 이상",
        "신용평가등급 BB 이상",                                       # proposed
        "직접생산확인증명서(소프트웨어유지및지원서비스) 보유 필수",              # detail null
        "법인등기부상 본점 소재지가 대구광역시인 자",                       # qual:branch detail main office
        "법인등기부상 본점 소재지가 부산광역시인 자",
        "지점 소재지 세종특별자치시",
        "ISMS-P 인증 보유 필수",                                      # detail null → ISMS/ISMS-P unknown
        "추정가격 12억원",                                           # pref:solo_cap 15억
        "추정가격 20억원",
        "1468 업종으로 등록한 자",                                    # qual:procurement_1468.held
        "부정당업자 제재를 받지 않은 자",                                # qual:sanction_free.held
    ]
    frozen, units = frozen_for(texts, rootlab_company)

    def text_item(index: int, value: str, operator: str = "eq") -> dict:
        return extract_item(units[index], constraints=[
            constraint(units[index], kind="text", value=value, unit_name=None, operator=operator, quote=texts[index])])

    def bool_item(index: int, value: bool = True) -> dict:
        return extract_item(units[index], constraints=[
            constraint(units[index], kind="boolean", value=value, unit_name=None, operator="eq", quote=texts[index])])

    def amount_item(index: int, value: int) -> dict:
        return extract_item(units[index], type_="평가", constraints=[
            constraint(units[index], kind="amount", value=value, unit_name="KRW", operator="eq", quote=texts[index])])

    rows = compare_all(frozen, [
        count_item(units[0], texts[0], 3), count_item(units[1], texts[1], 8), count_item(units[2], texts[2], 50),
        count_item(units[3], texts[3], 3), count_item(units[4], texts[4], 6),
        text_item(5, "BB", "gte"), bool_item(6),
        text_item(7, "대구광역시"), text_item(8, "부산광역시"), text_item(9, "세종특별자치시"),
        bool_item(10), amount_item(11, 1_200_000_000), amount_item(12, 2_000_000_000),
        bool_item(13), bool_item(14, False),
    ])
    summary = [(row.fit_status, row.constraint_results[0].reason_code, row.constraint_results[0].fact_ids)
               for row in rows]
    assert summary == [
        ("met", "confirmed_match", ["staff:onsite"]),
        ("gap", "confirmed_contradiction", ["staff:onsite"]),
        ("met", "confirmed_match", ["staff:total"]),
        ("met", "confirmed_match", ["staff:design_publishing"]),
        ("gap", "confirmed_contradiction", ["staff:design_publishing"]),
        ("unknown", "proposed_fact", ["qual:credit_rating"]),
        ("unknown", "unknown_fact", ["qual:direct_production"]),
        ("met", "confirmed_match", ["qual:branch"]),
        ("gap", "confirmed_contradiction", ["qual:branch"]),
        ("met", "confirmed_match", ["qual:branch"]),
        ("unknown", "unknown_fact", ["qual:infosec_cert"]),
        ("met", "confirmed_match", ["pref:solo_cap"]),
        ("gap", "confirmed_contradiction", ["pref:solo_cap"]),
        ("met", "confirmed_match", ["qual:procurement_1468"]),
        ("met", "confirmed_match", ["qual:sanction_free"]),
    ]
    # proposed / unknown rows never cite company evidence; confirmed decisions do
    assert rows[5].evidence_ids == [] and rows[6].evidence_ids == [] and rows[10].evidence_ids == []
    assert rows[0].evidence_ids and rows[7].evidence_ids


def test_non_onsite_wording_is_not_linked_to_the_onsite_fact() -> None:
    text = "비상주 인력 2명 이상"
    company = synthetic_company([_fact("staff:onsite", "confirmed", {"available": 1, "region": "대구"})])
    frozen, units = frozen_for([text], company)
    row = compare_one(frozen, count_item(units[0], text, 2))
    assert (row.fit_status, row.constraint_results[0].reason_code) == ("unknown", "unmapped")
