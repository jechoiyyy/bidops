"""RL-03 card-v1 unit selection, batching and the frozen ``card_analysis`` input (spec T1 unit·batch part).

The HP-03 T1/T2 rules are ported to the RL names (``card-sections-v1``,
``card_source_selection_incomplete``) with the real-company ``company_binding``
instead of HP basis hashes.  Pure functions only: no DB, model or network.

STEP-005 (rest of T1): extract validation (quotes in the exact source block,
traceable numbers/operators, allowlisted anchored fact keys, ontology
coverage, strict schema), the append-only stage envelope and the role /
synthesis closure (HP-03 T3·T5 with RL names).  Compare is in
``test_card_compare.py``.
"""

from __future__ import annotations

from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.deep_review.contracts import CARD_ANALYSIS_INPUT_SCHEMA, SchemaValidationError, validate_payload
from app.core.company_ontology import OntologyConcept
from app.deep_review.schemas.card_analysis import (
    CardAnalysisBatch,
    CardAnalysisInput,
    CardAnalysisUnit,
    CardCompanyBinding,
    CardRequirementCompare,
    CardRequirementExtract,
    CardSelector,
    CardUnitBlock,
)
from app.deep_review.services.card_analysis import (
    CardAnalysisStageStoreError,
    CardAnalysisValidationError,
    canonical_card_stage_payload,
    validate_requirement_extract,
)
from app.deep_review.services.card_roles import (
    assemble_practitioner_verdict,
    build_synthesis_input,
    build_verdict_role_inputs,
    validate_practitioner_verdict,
    validate_verdict_role,
)
from app.deep_review.schemas.card_analysis import CardAssembledPractitionerVerdict
from app.deep_review.services.card_units import (
    SELECTOR_SHA256,
    SELECTOR_SHA256_V2,
    SELECTOR_SHA256_V3,
    SELECTOR_VERSION,
    SELECTOR_VERSION_V2,
    SELECTOR_VERSION_V3,
    CardAnalysisSelectionError,
    analysis_call_budget,
    card_requirement_units,
    freeze_card_analysis_input,
    pack_analysis_batches,
    select_analysis_units,
)


SOURCE_SHA = "a" * 64


def _binding() -> CardCompanyBinding:
    return CardCompanyBinding(
        graph_version_id=uuid4(), graph_sha256="b" * 64, profile_version_id=uuid4(),
        profile_sha256="c" * 64, ontology_version="bidops.company-ontology.rl-v2", ontology_sha256="d" * 64,
    )


def _block(key: str, text: str, *, kind: str = "paragraph", table: str | None = None,
           row: int | None = None, column: int | None = None, page: int = 1) -> dict:
    attributes: dict[str, object] = {}
    if table is not None:
        attributes["table_key"] = table
    if row is not None:
        attributes["row"] = row
    if column is not None:
        attributes["column"] = column
    return {
        "block_key": key, "parent_block_key": table if kind == "table_cell" else None, "type": kind,
        "page": page, "bbox": None, "text": text, "confidence": None, "attributes": attributes,
    }


def _card_cells(table: str, start_row: int, suffix: str) -> list[dict]:
    fields = [
        ("요구사항분류", "기능"),
        ("요구사항고유번호", "SFR-001"),
        ("요구사항명칭", f"기능 {suffix}"),
        ("정의", f"정의 {suffix}"),
        ("세부내용", f"세부 {suffix}"),
    ]
    rows: list[dict] = []
    for offset, (label, value) in enumerate(fields):
        row = start_row + offset
        rows.extend([
            _block(f"{table}-{row}-0", label, kind="table_cell", table=table, row=row, column=0),
            _block(f"{table}-{row}-1", value, kind="table_cell", table=table, row=row, column=1),
        ])
    return rows


def _source(*, document_version_id: UUID | None = None) -> dict:
    document_version_id = document_version_id or uuid4()
    table = "card-table"
    blocks = [
        _block("toc", "목차"),
        _block("toc-overview", "1. 사업개요  1"),
        _block("overview-heading", "제1장 사업개요"),
        _block("overview-body", "홈페이지 사업의 목적"),
        _block("schedule-heading", "1.1 추진일정"),
        _block("schedule-body", "착수 후 6개월"),
        _block(table, "요구사항 카드 두 장", kind="table", table=table),
        *_card_cells(table, 0, "A"),
        *_card_cells(table, 5, "B"),
        _block("budget-heading", "제2장 사업예산 및 평가기준"),
        _block("budget-body", "사업비 2억원, 평가 배점 100점"),
        _block("eligibility-heading", "제3장 입찰참가자격"),
        _block("eligibility-body", "참가 자격을 확인한다", page=2),
    ]
    positions = {block["block_key"]: index for index, block in enumerate(blocks)}

    def segment(keys: list[str], ordinal: int) -> dict:
        return {
            "segment_id": uuid4(), "ordinal": ordinal,
            "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
            "source_block_keys": keys, "page_range": None, "mapping_status": "unavailable",
        }

    cards = []
    for ordinal, id_row in ((1, 1), (2, 6)):
        cards.append({
            "raw_id": "SFR-001", "normalized_id": "SFR-1",
            "locator": {
                "kind": "table_cell", "block_key": f"{table}-{id_row}-0", "table_key": table,
                "row": id_row, "column": 0, "page": 1, "ordinal": positions[f"{table}-{id_row}-0"],
            },
            "title": f"기능 {ordinal}", "ordinal": ordinal, "source": "label_value_table",
            "card": {
                "category": "기능", "compliance_level": None, "definition": f"정의 {ordinal}",
                "details": f"세부 {ordinal}", "outputs": None, "related_raw": None,
                "related_ids": [], "table_key": table, "first_cell_block_key": f"{table}-0-0",
                "card_warnings": [], "page_anchor_block_keys": ["schedule-body"],
            },
            "page_range": None, "mapping_status": "unavailable",
        })
    card_keys = [block["block_key"] for block in blocks
                 if block["block_key"] == table or block["attributes"].get("table_key") == table]
    return {
        "source_sha256": SOURCE_SHA, "document_version_id": document_version_id,
        "structure_id": uuid4(), "manifest_id": uuid4(), "blocks": blocks, "cards": cards,
        "segments": [
            segment(["overview-heading", "overview-body"], 1),
            segment(["schedule-heading", "schedule-body", *card_keys], 2),
            segment(["budget-heading", "budget-body"], 3),
            segment(["eligibility-heading", "eligibility-body"], 4),
        ],
    }


def _unit(index: int, characters: int) -> CardAnalysisUnit:
    normalized_id = f"SFR-{index + 1}"
    return CardAnalysisUnit(
        unit_id=f"card:{SOURCE_SHA}:{index}:{normalized_id}", source_sha256=SOURCE_SHA,
        document_version_id=uuid4(), structure_id=uuid4(), manifest_id=uuid4(), kind="card",
        ordinal=index, normalized_id=normalized_id, section_kinds=[],
        blocks=[CardUnitBlock(block_key=f"block-{index}", text="가" * characters)],
        page_range=None, mapping_status="unavailable",
    )


# --- T1: units and selector ----------------------------------------------------------


def test_t1_selects_cards_and_heading_scopes_once_and_freezes_reasons() -> None:
    first = _source()
    second = _source(document_version_id=uuid4())
    # Same source bytes under another document version: one source, both versions bound.
    second["source_sha256"] = first["source_sha256"]
    selection = select_analysis_units([first, second])

    assert [unit.kind for unit in selection.units].count("card") == 2
    assert len({unit.unit_id for unit in selection.units}) == len(selection.units)
    assert [unit.normalized_id for unit in selection.units if unit.kind == "card"] == ["SFR-1", "SFR-1"]
    assert len(selection.source_bindings) == 1
    assert selection.source_bindings[0].document_version_ids == [
        first["document_version_id"], second["document_version_id"],
    ]
    assert selection.selector.version == SELECTOR_VERSION == "card-sections-v1"
    assert selection.selector.sha256 == SELECTOR_SHA256
    selected_keys = [row.block_key for row in selection.selector.selected_blocks]
    candidate_keys = [row.block_key for row in selection.selector.candidate_blocks]
    assert "toc-overview" in candidate_keys and "toc-overview" not in selected_keys
    assert not any(key.startswith("card-table") for key in selected_keys)
    assert selection.missing_sections == ["contract"]
    budget = next(unit for unit in selection.units if any(block.block_key == "budget-heading" for block in unit.blocks))
    assert budget.section_kinds == ["budget", "evaluation"]
    all_keys = [block.block_key for unit in selection.units for block in unit.blocks]
    assert len(all_keys) == len(set(all_keys))
    # Only card units and the six heading-scoped segment units exist (T9 (d) basis).
    assert {unit.kind for unit in selection.units} == {"card", "segment"}
    assert all(unit.section_kinds for unit in selection.units if unit.kind == "segment")


def test_t1_rejects_card_identity_that_would_duplicate_a_unit_id() -> None:
    source = _source()
    source["cards"][1]["ordinal"] = source["cards"][0]["ordinal"]
    with pytest.raises(CardAnalysisSelectionError, match="card_source_selection_incomplete"):
        select_analysis_units([source])


def test_t1_card_without_table_cells_is_selection_incomplete() -> None:
    source = _source()
    source["cards"][0]["card"]["table_key"] = "missing-table"
    with pytest.raises(CardAnalysisSelectionError) as error:
        select_analysis_units([source])
    assert error.value.code == "card_source_selection_incomplete"


def test_t1_orders_multiple_source_identities_by_hash_then_original_block_order() -> None:
    later = _source()
    earlier = _source()
    earlier["source_sha256"] = "0" * 64
    selection = select_analysis_units([later, earlier])
    hashes = [unit.source_sha256 for unit in selection.units]
    assert hashes == sorted(hashes)
    assert [row.source_sha256 for row in selection.selector.candidate_blocks] == sorted(
        row.source_sha256 for row in selection.selector.candidate_blocks
    )


def test_t1_heading_keyword_in_body_text_alone_is_not_selected() -> None:
    source = _source()
    # A body paragraph mentioning "계약조건" without a numbered heading never opens a section.
    source["blocks"].append(_block("contract-mention", "계약조건은 별도로 정한다"))
    source["segments"].append({
        "segment_id": uuid4(), "ordinal": 5, "start_locator": {"ordinal": 99, "block_key": "contract-mention"},
        "source_block_keys": ["contract-mention"], "page_range": None, "mapping_status": "unavailable",
    })
    selection = select_analysis_units([source])
    assert "contract" in selection.missing_sections


# --- T2: batches and call budget -----------------------------------------------------


def test_t2_greedy_batches_obey_eight_and_twelve_thousand_character_limits() -> None:
    exact = [_unit(index, 1500) for index in range(8)]
    batches = pack_analysis_batches([*exact, _unit(8, 1)])
    assert [(len(batch.unit_ids), batch.source_characters) for batch in batches] == [(8, 12000), (1, 1)]
    assert [batch.batch_index for batch in batches] == [0, 1]
    split = pack_analysis_batches([_unit(0, 6000), _unit(1, 6001)])
    assert [batch.source_characters for batch in split] == [6000, 6001]
    with pytest.raises(CardAnalysisSelectionError, match="input_budget_exceeded"):
        pack_analysis_batches([_unit(0, 12001)])
    # tunable policy values inside the HP-03 ranges
    assert [len(batch.unit_ids) for batch in pack_analysis_batches(
        [_unit(index, 1) for index in range(5)], policy={"batch_size": 2},
    )] == [2, 2, 1]
    with pytest.raises(ValidationError):
        pack_analysis_batches([_unit(0, 1)], policy={"batch_size": 9})


def test_t2_call_budget_is_batches_plus_four_and_repair_doubles_the_maximum() -> None:
    assert analysis_call_budget(2, repair_attempts=0).model_dump() == {
        "batch_count": 2, "normal_calls": 6, "maximum_calls": 6,
    }
    assert analysis_call_budget(2, repair_attempts=1).maximum_calls == 12
    with pytest.raises(CardAnalysisSelectionError):
        analysis_call_budget(True)  # type: ignore[arg-type]


def test_t2_strict_batch_schema_rejects_bool_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CardAnalysisBatch.model_validate({"batch_index": True, "unit_ids": ["u"], "source_characters": 1})
    with pytest.raises(ValidationError):
        CardAnalysisBatch.model_validate({
            "batch_index": 0, "unit_ids": ["u"], "source_characters": 1, "unexpected": "field",
        })


# --- frozen card_analysis input ------------------------------------------------------


def test_frozen_card_analysis_has_the_exact_rl_key_set_and_validates_against_the_schema() -> None:
    binding = _binding()
    frozen = freeze_card_analysis_input(select_analysis_units([_source()]), company_binding=binding)
    payload = frozen.model_dump(mode="json")
    assert set(payload) == {"schema_version", "company_binding", "units", "batches", "missing_sections", "selector"}
    assert payload["schema_version"] == "bidops.card-analysis-input.v1"
    assert set(payload["company_binding"]) == {
        "graph_version_id", "graph_sha256", "profile_version_id", "profile_sha256",
        "ontology_version", "ontology_sha256",
    }
    # HP basis/scenario/registration identities are gone (spec "루트랩 재명세 차이").
    assert not {"company_sha256", "scenario_sha256", "registration_sha256", "company_basis"} & set(payload)
    validate_payload(payload, CARD_ANALYSIS_INPUT_SCHEMA)
    with pytest.raises(SchemaValidationError):
        validate_payload({**payload, "company_basis": {}}, CARD_ANALYSIS_INPUT_SCHEMA)
    with pytest.raises(SchemaValidationError):
        validate_payload({**payload, "selector": {**payload["selector"], "version": "hp-sections-v1"}},
                         CARD_ANALYSIS_INPUT_SCHEMA)
    with pytest.raises(ValidationError):
        CardAnalysisInput.model_validate({**payload, "batches": []})


def test_requirement_units_follow_frozen_unit_order_with_stored_block_pages() -> None:
    source = _source()
    frozen = freeze_card_analysis_input(select_analysis_units([source]), company_binding=_binding())
    structure_id = str(source["structure_id"])
    bundle = {"documents": [{"document_version_id": str(source["document_version_id"]), "ordinal": 0}]}
    rows = card_requirement_units(frozen, bundle, {structure_id: {"blocks": source["blocks"]}})
    assert [row["requirement_id"] for row in rows] == [unit.unit_id for unit in frozen.units]
    eligibility = next(row for row in rows if "참가 자격" in row["text"])
    # page comes from the first selected stored block (the heading on page 1), never invented
    assert eligibility["page"] == 1 and eligibility["locator"] == {"page": 1}
    cards = [row for row in rows if row["requirement_id"].startswith("card:")]
    assert all(row["document_requirement_ids"] == ["SFR-1"] for row in cards)
    with pytest.raises(CardAnalysisSelectionError):
        card_requirement_units(frozen, bundle, {})


# --- STEP-005 helpers: frozen units of plain requirement texts -----------------------

ONTOLOGY = (
    OntologyConcept("qual.direct-production", "직접생산확인", ("직접생산확인증명서", "직접생산 확인"), "qualification"),
    OntologyConcept("qual.isms", "ISMS", (), "qualification"),
    OntologyConcept("qual.isms-p", "ISMS-P", (), "qualification"),
    OntologyConcept("cap.cms", "CMS 구축", ("콘텐츠관리시스템 구축",), "capability"),
    OntologyConcept("cap.onsite", "상주 운영", ("상주 유지관리",), "capability"),
)


def card_input(texts: list[str]) -> CardAnalysisInput:
    """One card unit (one block) per text, packed with the default policy."""

    units = [
        CardAnalysisUnit(
            unit_id=f"card:{SOURCE_SHA}:{index}:REQ-{index}", source_sha256=SOURCE_SHA,
            document_version_id=UUID(int=1), structure_id=UUID(int=2), manifest_id=UUID(int=3), kind="card",
            ordinal=index, normalized_id=f"REQ-{index}", section_kinds=[],
            blocks=[CardUnitBlock(block_key=f"block-{index}", text=text)],
            page_range=None, mapping_status="unavailable",
        )
        for index, text in enumerate(texts)
    ]
    return CardAnalysisInput(
        company_binding=_binding(), units=units, batches=pack_analysis_batches(units), missing_sections=[],
        selector=CardSelector(sha256=SELECTOR_SHA256, candidate_blocks=[], selected_blocks=[]),
    )


def evidence(unit: CardAnalysisUnit, quote: str | None = None) -> dict:
    return {"source_sha256": unit.source_sha256, "block_key": unit.blocks[0].block_key,
            "quote": quote if quote is not None else unit.blocks[0].text}


def constraint(unit: CardAnalysisUnit, *, kind: str, value, unit_name, operator: str, quote: str,
               fact_key: str | None = None) -> dict:
    return {"kind": kind, "value": value, "unit": unit_name, "operator": operator, "fact_key": fact_key,
            "quote": quote, "locator": {"source_sha256": unit.source_sha256, "block_key": unit.blocks[0].block_key}}


def extract_item(unit: CardAnalysisUnit, *, type_: str = "자격", mandatory=True, constraints=(),
                 concepts=(), unknowns=(), normalized: str | None = None) -> dict:
    return {
        "unit_id": unit.unit_id, "type": type_, "normalized_requirement": normalized or unit.blocks[0].text,
        "mandatory": mandatory, "constraints": list(constraints), "concept_candidates": list(concepts),
        "unknowns": list(unknowns), "evidence": [evidence(unit)],
    }


EXTRACT_TEXT = "직접생산확인증명서 보유 필수 및 상주 인원 3명 이상"


def _valid_extract(frozen: CardAnalysisInput) -> dict:
    unit = frozen.units[0]
    return {"schema_version": "bidops.requirement-extract.v1", "items": [extract_item(
        unit,
        normalized="직접생산확인증명서 보유 및 상주 인원 3명 이상",
        constraints=[
            constraint(unit, kind="boolean", value=True, unit_name=None, operator="eq",
                       quote="직접생산확인증명서 보유 필수", fact_key="qual:direct_production"),
            constraint(unit, kind="count", value=3, unit_name="person", operator="gte", quote="상주 인원 3명 이상"),
        ],
        concepts=[{"concept_id": "qual.direct-production", "alias_text": "직접생산확인증명서"}],
    )]}


def _invalid(payload: dict, mutate) -> dict:
    changed = deepcopy(payload)
    mutate(changed["items"])
    return changed


# --- T1 (HP-03 T3): extract validation --------------------------------------------


def test_t1_extract_binds_exact_quotes_numbers_operators_fact_anchors_and_concepts() -> None:
    frozen = card_input([EXTRACT_TEXT])
    valid = _valid_extract(frozen)
    result = validate_requirement_extract(valid, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert [row.value for row in result.items[0].constraints] == [True, 3]
    # 2억원 = 200백만원: exact KRW conversion of the quote's own unit is accepted
    amount = card_input(["사업예산 200백만원 이하"])
    unit = amount.units[0]
    validate_requirement_extract(
        {"schema_version": "bidops.requirement-extract.v1", "items": [extract_item(unit, type_="계약", constraints=[
            constraint(unit, kind="amount", value=200_000_000, unit_name="KRW", operator="lte", quote=unit.blocks[0].text),
        ])]},
        card_input=amount, batch_index=0, ontology=ONTOLOGY,
    )

    cases = {
        "quote_not_in_source": lambda items: items[0]["evidence"][0].update(quote="직접생산확인증명서 및 ISMS 보유"),
        "other_block": lambda items: items[0]["evidence"][0].update(block_key="block-outside"),
        "constraint_quote_elsewhere": lambda items: items[0]["constraints"][1].update(quote="상주 인원 4명 이상"),
        "invented_number": lambda items: items[0]["constraints"][1].update(value=4),
        "invented_requirement_number": lambda items: items[0].update(normalized_requirement="상주 인원 5명 이상"),
        "wrong_operator": lambda items: items[0]["constraints"][1].update(operator="lte"),
        "fact_outside_allowlist": lambda items: items[0]["constraints"][0].update(fact_key="qual:social_enterprise"),
        "fact_without_anchor": lambda items: items[0]["constraints"][1].update(fact_key="staff:total"),
        "fact_wrong_kind": lambda items: items[0]["constraints"][1].update(fact_key="qual:direct_production"),
        "wrong_concept": lambda items: items[0]["concept_candidates"][0].update(concept_id="cap.cms"),
        "missing_concept": lambda items: items[0].update(concept_candidates=[]),
        "duplicate_unit": lambda items: items.append(deepcopy(items[0])),
        "missing_unit": lambda items: items.clear(),
        "schema_extra_key": lambda items: items[0].update(confidence=0.9),
        "schema_bool_number": lambda items: items[0]["constraints"][1].update(value=True),
    }
    for name, mutate in cases.items():
        payload = _invalid(valid, mutate)
        before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with pytest.raises(CardAnalysisValidationError) as error:
            validate_requirement_extract(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
        assert error.value.code == "card_extract_invalid", name
        # never corrected in place
        assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before, name
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract(valid, card_input=frozen, batch_index=1, ontology=ONTOLOGY)


def test_t1_extract_keeps_ambiguous_alternatives_unknown_and_rejects_a_guessed_fact_key() -> None:
    frozen = card_input(["상주 인원 2/3명"])
    unit = frozen.units[0]
    item = extract_item(unit, type_="인력", constraints=[
        constraint(unit, kind="count", value=2, unit_name="person", operator="unknown", quote=unit.blocks[0].text),
    ], unknowns=["2명 또는 3명 중 적용 인원 미확인"], normalized="상주 인원 2명 또는 3명")
    payload = {"schema_version": "bidops.requirement-extract.v1", "items": [item]}
    validate_requirement_extract(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    guessed = deepcopy(payload)
    guessed["items"][0]["constraints"][0].update(operator="eq")
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract(guessed, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    linked = deepcopy(payload)
    linked["items"][0]["constraints"][0].update(fact_key="staff:onsite")  # unknown operator never links
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract(linked, card_input=frozen, batch_index=0, ontology=ONTOLOGY)


# --- stage row envelope ----------------------------------------------------------------


def test_stage_payload_canonicalization_is_strict_and_deterministic() -> None:
    first, digest = canonical_card_stage_payload({"b": [1, "가"], "a": None})
    second, same = canonical_card_stage_payload({"a": None, "b": [1, "가"]})
    assert first == second and digest == same and len(digest) == 64
    for bad in ({"x": float("nan")}, {"x": {1, 2}}, ["not", "object"]):
        with pytest.raises(CardAnalysisStageStoreError):
            canonical_card_stage_payload(bad)  # type: ignore[arg-type]


# --- T1 (HP-03 T5): roles and synthesis ----------------------------------------------


def _role_world():
    texts = ["상주 인원 8명 이상", "CMS 구축", "손해배상 조건 수용", "평가 기준 충족"]
    frozen = card_input(texts)
    units = frozen.units
    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1", "items": [
        extract_item(units[0], type_="인력", constraints=[
            constraint(units[0], kind="count", value=8, unit_name="person", operator="gte", quote=texts[0])]),
        extract_item(units[1], type_="기능", concepts=[{"concept_id": "cap.cms", "alias_text": texts[1]}]),
        extract_item(units[2], type_="계약", constraints=[
            constraint(units[2], kind="text", value=texts[2], unit_name=None, operator="eq", quote=texts[2])]),
        extract_item(units[3], type_="평가", mandatory=None),
    ]})
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": units[0].unit_id, "fit_status": "gap", "evidence_ids": [], "reason_codes": ["confirmed_contradiction"],
         "constraint_results": [{"constraint_index": 0, "status": "gap", "fact_ids": ["staff:onsite"], "path_ids": [],
                                 "reason_code": "confirmed_contradiction"}]},
        {"unit_id": units[1].unit_id, "fit_status": "unknown", "evidence_ids": [], "reason_codes": ["unmapped"],
         "constraint_results": []},
        {"unit_id": units[2].unit_id, "fit_status": "unknown", "evidence_ids": [],
         "reason_codes": ["unmapped", "contract_unaccepted"],
         "constraint_results": [{"constraint_index": 0, "status": "unknown", "fact_ids": [], "path_ids": [],
                                 "reason_code": "unmapped"}]},
        {"unit_id": units[3].unit_id, "fit_status": "unknown", "evidence_ids": [], "reason_codes": ["incomplete_unit"],
         "constraint_results": []},
    ]})
    return frozen, extract, compare


def _role_output(role_input, assessments: dict[str, str] | None = None) -> dict:
    assessments = assessments or {}
    fits = {row.unit_id: row.fit_status for row in role_input.compare.items}
    return {
        "schema_version": "bidops.verdict-role.v1", "role": role_input.role,
        "unit_findings": [
            {"unit_id": row.unit_id, "assessment": assessments.get(row.unit_id, fits[row.unit_id]),
             "reason": "결정적 대조 결과를 그대로 따른다",
             "evidence_refs": [item.model_dump(mode="json") for item in row.evidence]}
            for row in role_input.extract.items
        ],
        "cautions": [], "evidence_refs": [],
    }


def test_t1_role_inputs_keep_type_allowlists_exact_coverage_and_compare_bounds() -> None:
    _frozen, extract, compare = _role_world()
    inputs = build_verdict_role_inputs(extract, compare)
    types = {role: [row.type for row in value.extract.items] for role, value in inputs.items()}
    assert types == {
        "eligibility_economics": ["인력", "계약", "평가"],
        "technical_fit": ["기능"],
        "operations_risk": ["인력", "계약"],
    }
    eligibility = inputs["eligibility_economics"]
    validate_verdict_role(_role_output(eligibility), role_input=eligibility)
    gap_unit, contract_unit = extract.items[0].unit_id, extract.items[2].unit_id
    # an unknown stays unknown: a role cannot turn it into met or gap ("부족")
    for assessments in ({contract_unit: "met"}, {contract_unit: "gap"}, {gap_unit: "met"}):
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role(_role_output(eligibility, assessments), role_input=eligibility)
    # a role may stay more cautious than the compare (gap → unknown) -- kept as a conflict later
    validate_verdict_role(_role_output(eligibility, {gap_unit: "unknown"}), role_input=eligibility)
    broken = _role_output(eligibility)
    broken["unit_findings"].pop()
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role(broken, role_input=eligibility)
    foreign = _role_output(eligibility)
    foreign["unit_findings"][0]["evidence_refs"] = [
        evidence(card_input(["다른 문장"]).units[0])
    ]
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role(foreign, role_input=eligibility)
    wrong_role = _role_output(eligibility)
    wrong_role["role"] = "technical_fit"
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role(wrong_role, role_input=eligibility)


def _synthesis(units, *, verdict: str = "조건부 진행", blocking=None, cautions=None, actions=None) -> dict:
    return {
        "schema_version": "bidops.practitioner-verdict.v1", "verdict": verdict,
        "reason": "상주 인원 요구가 회사 가용 인원을 넘고 확인할 조건이 남아 있다.",
        "blocking_condition_ids": blocking if blocking is not None else [units[0].unit_id],
        "cautions": cautions or [], "next_actions": actions or [],
    }


def test_t1_synthesis_requires_three_roles_known_units_no_invented_owner_and_no_false_proceed() -> None:
    frozen, extract, compare = _role_world()
    units = frozen.units
    inputs = build_verdict_role_inputs(extract, compare)
    roles = {role: validate_verdict_role(_role_output(value), role_input=value) for role, value in inputs.items()}
    synthesis_input = build_synthesis_input(roles)
    verdict = validate_practitioner_verdict(_synthesis(units), synthesis_input=synthesis_input,
                                            extract=extract, compare=compare)
    assert verdict.verdict == "조건부 진행"
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        build_synthesis_input({key: value for key, value in roles.items() if key != "technical_fit"})
    action = {"unit_id": units[0].unit_id, "owner": "김담당", "action": "상주 인력 보강 검토",
              "evidence_refs": [evidence(units[0])]}
    invalid = [
        _synthesis(units, verdict="진행 가능", blocking=[]),  # mandatory gap and unresolved units
        _synthesis(units, blocking=[]),  # mandatory gap neither blocking nor caution
        _synthesis(units, blocking=[units[1].unit_id]),  # blocking must be a mandatory gap
        _synthesis(units, actions=[action]),  # invented owner
        _synthesis(units, actions=[{**action, "owner": None, "unit_id": "card:unknown"}]),
        _synthesis(units, cautions=[{"unit_id": units[1].unit_id, "text": "확인 필요",
                                     "evidence_refs": [evidence(units[0])]}]),  # evidence of another unit
    ]
    for payload in invalid:
        with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
            validate_practitioner_verdict(payload, synthesis_input=synthesis_input, extract=extract, compare=compare)
    validate_practitioner_verdict(_synthesis(units, actions=[{**action, "owner": None}]),
                                  synthesis_input=synthesis_input, extract=extract, compare=compare)


def test_t1_assembly_preserves_conflicts_compare_fit_and_checklist() -> None:
    frozen, extract, compare = _role_world()
    units = frozen.units
    inputs = build_verdict_role_inputs(extract, compare)
    roles = {
        "eligibility_economics": validate_verdict_role(
            _role_output(inputs["eligibility_economics"]), role_input=inputs["eligibility_economics"]),
        "technical_fit": validate_verdict_role(
            _role_output(inputs["technical_fit"]), role_input=inputs["technical_fit"]),
        # operations stays cautious on the gap → a preserved conflict, not a correction
        "operations_risk": validate_verdict_role(
            _role_output(inputs["operations_risk"], {units[0].unit_id: "unknown"}),
            role_input=inputs["operations_risk"]),
    }
    synthesis_input = build_synthesis_input(roles)
    assembled = assemble_practitioner_verdict(_synthesis(units), synthesis_input=synthesis_input,
                                              extract=extract, compare=compare)
    assert [row.fit_status for row in assembled.matrix] == ["gap", "unknown", "unknown", "unknown"]
    assert [row.model_dump() for row in assembled.conflicts] == [{
        "unit_id": units[0].unit_id, "roles": ["eligibility_economics", "operations_risk"],
        "assessments": ["gap", "unknown"],
    }]
    checklist = {row.key: row.status for row in assembled.checklist}
    assert checklist == {
        "qualification_track_record": "unknown", "staffing_onsite": "gap", "amount_period": "unknown",
        "technology": "unknown", "operations_sla_security": "unknown",
    }
    assert assembled.verdict == "조건부 진행" and assembled.blocking_condition_ids == [units[0].unit_id]



# --- 결정 B23: selector card-sections-v2 on the real Polytech RFP shape -------------
#
# Block keys and texts are copied verbatim from the converted public Polytech RFP
# (T11 structure 944579cd-…, "(붙임2) 2027년 홈페이지 유지관리 용역사업 제안요청서").
# Its budget/eligibility/evaluation headings start with the Wingdings bullet
# U+F06D; contract keywords appear only inside bullet sentences (209, 226) or a
# dash body line (299), never as a heading.

POLYTECH_SHA = "8b6cbf1a7da6f242dae0a1a90b2513513178667a7fc2343e93cbcf6318005a1e"
POLYTECH_BLOCKS = (
    ("paragraph-1-72", "Ⅰ사업개요"),
    ("paragraph-1-73", "1. 사업개요"),
    ("paragraph-1-74", " 사 업 명: 2027년 홈페이지 유지관리 용역사업"),
    ("paragraph-1-75", " 사업기간: 2027. 1. 1. ~ 12. 31.(12개월)"),
    ("paragraph-1-76", " 사업예산: 134,700천원(부가가치세 포함)"),
    ("paragraph-1-77", "※ ‘27. 1. 1. 이후 계약 체결 시 계약일 및 계약금액을 기준으로 일할 계산하여 대가 지급"),
    ("paragraph-1-78", " 입찰방식: 제한경쟁입찰"),
    ("paragraph-1-83", "2. 추진배경 및 필요성"),
    ("paragraph-1-84", " 홈페이지의 안정적·효율적인 운영관리를 통한 홈페이지 방문자 대상 양질의 서비스 제공"),
    ("paragraph-1-115", "4. 추진일정"),
    ("paragraph-1-117", "※ 상기 일정은 사업 진행 사정에 따라 일부 변경될 수 있음"),
    ("paragraph-1-207", "Ⅳ제안서 작성 안내"),
    ("paragraph-1-208", "1. 제안서의 효력"),
    ("paragraph-1-209", " 제출된 제안서의 내용은 주관기관에서 요청하지 않는 한 변경할 수 없으며, 계약 체결 시 계약조건의 일부로 간주"),
    ("paragraph-1-222", "3. 제안서 유의사항"),
    ("paragraph-1-226", " 제안사는 제안서의 내용이 허위 또는 이행 불가능한 내용으로 작성된 사실이 발견될 경우"
                        "「(계약예규)용역계약일반조건」제29조를 따름"),
    ("paragraph-1-247", "Ⅴ제안 안내"),
    ("paragraph-1-248", "1. 입찰방식"),
    ("paragraph-1-252", " 입찰참가 자격"),
    ("paragraph-1-253", "-「국가를 당사자로 하는 계약에 관한 법률 시행령」제12조 및 같은 법 시행규칙 제14조에 의한 경쟁 입찰 "
                        "참가자격을 갖춘 업체로서, 아래 각 호에 모두 해당하여야 함"),
    ("paragraph-1-264", "2. 사업자 선정방법"),
    ("paragraph-1-265", " 제안서 평가 방법"),
    ("paragraph-1-266", "- 기술능력평가와 입찰가격평가를 실시하여 종합평가점수로 산출함"),
    ("paragraph-1-291", "3. 입찰 및 기타 유의사항"),
    ("paragraph-1-297", " 하자담보 책임기간 및 범위"),
    ("paragraph-1-299", "-「일반용역계약 특수조건」제17조제1항제1호에 따라 별도의 하자담보책임기간은 없음"),
)
#: One manifest segment per numbered heading region (the HP-01 manifest shape).
POLYTECH_SEGMENTS = (
    ("paragraph-1-72",),
    ("paragraph-1-73", "paragraph-1-74", "paragraph-1-75", "paragraph-1-76", "paragraph-1-77", "paragraph-1-78"),
    ("paragraph-1-83", "paragraph-1-84"),
    ("paragraph-1-115", "paragraph-1-117"),
    ("paragraph-1-207",),
    ("paragraph-1-208", "paragraph-1-209"),
    ("paragraph-1-222", "paragraph-1-226"),
    ("paragraph-1-247",),
    ("paragraph-1-248", "paragraph-1-252", "paragraph-1-253"),
    ("paragraph-1-264", "paragraph-1-265", "paragraph-1-266"),
    ("paragraph-1-291", "paragraph-1-297", "paragraph-1-299"),
)


def _polytech_source() -> dict:
    blocks = [_block(key, text) for key, text in POLYTECH_BLOCKS]
    positions = {key: index for index, (key, _text) in enumerate(POLYTECH_BLOCKS)}
    return {
        "source_sha256": POLYTECH_SHA, "document_version_id": uuid4(), "structure_id": uuid4(),
        "manifest_id": uuid4(), "blocks": blocks, "cards": [],
        "segments": [
            {"segment_id": uuid4(), "ordinal": ordinal, "source_block_keys": list(keys),
             "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
             "page_range": None, "mapping_status": "unavailable"}
            for ordinal, keys in enumerate(POLYTECH_SEGMENTS, start=1)
        ],
    }


def _sections_by_block(selection) -> dict[str, list[str]]:
    return {row.block_key: list(row.section_kinds) for row in selection.selector.selected_blocks}


def test_b23_v1_selector_is_unchanged_and_misses_the_bullet_headings() -> None:
    # Same result T11 recorded for the real file (card-sections-v1, sha pinned).
    selection = select_analysis_units([_polytech_source()])
    assert selection.selector.version == "card-sections-v1"
    assert selection.selector.sha256 == SELECTOR_SHA256 == (
        "ac18ffd120333e80b2dccbde0129969d6202e05b9aa1493119a927400ffa67f1")
    assert selection.missing_sections == ["budget", "eligibility", "evaluation", "contract"]


def test_b23_v2_selector_finds_bullet_budget_eligibility_evaluation_and_reports_contract_missing() -> None:
    selection = select_analysis_units([_polytech_source()], selector_version=SELECTOR_VERSION_V2)
    assert selection.selector.version == SELECTOR_VERSION_V2 == "card-sections-v2"
    assert selection.selector.sha256 == SELECTOR_SHA256_V2 != SELECTOR_SHA256
    assert selection.missing_sections == ["contract"]
    sections = _sections_by_block(selection)
    assert "budget" in sections["paragraph-1-76"]
    assert sections["paragraph-1-252"] == ["eligibility"] and sections["paragraph-1-253"] == ["eligibility"]
    assert sections["paragraph-1-265"] == ["evaluation"] and sections["paragraph-1-266"] == ["evaluation"]
    # the bullet budget scope ends at the next numbered heading ("2. 추진배경" opens overview)
    assert "budget" not in sections["paragraph-1-83"]
    # bullet sentences mentioning 계약조건/계약일반조건 and the dash line with 계약특수 are not headings
    assert not any("contract" in kinds for kinds in sections.values())
    assert "paragraph-1-209" not in sections and "paragraph-1-226" not in sections
    assert "paragraph-1-299" not in sections and "paragraph-1-297" not in sections
    frozen = freeze_card_analysis_input(selection, company_binding=_binding())
    payload = frozen.model_dump(mode="json")
    validate_payload(payload, CARD_ANALYSIS_INPUT_SCHEMA)
    assert payload["selector"]["version"] == "card-sections-v2" and payload["missing_sections"] == ["contract"]
    assert {unit.kind for unit in selection.units} == {"segment"}


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        (" 사업예산: 134,700천원(부가가치세 포함)", ["budget"]),
        ("■ 계약조건", ["contract"]),
        ("□ 입찰참가자격 및 제한", ["eligibility"]),
        ("※ 사업비 산정 기준", ["budget"]),
        (" 제안서 평가 기준", ["evaluation"]),
        (" 입찰방식: 제한경쟁입찰", None),  # bullet without a section keyword
        ("- 계약조건은 별도로 정한다", None),  # a dash body line is not a bullet heading
        ("계약조건은 별도로 정한다", None),  # no bullet
        (" " + "가" * 30 + " 계약조건의 일부로 간주", None),  # bullet sentence over the title cap
        ("", None),
    ],
)
def test_b23_bullet_heading_rule(text: str, kinds) -> None:
    source = _source()
    source["blocks"].append(_block("bullet", text))
    source["blocks"].append(_block("bullet-body", "본문"))
    source["segments"].append({
        "segment_id": uuid4(), "ordinal": 5, "start_locator": {"ordinal": 99, "block_key": "bullet"},
        "source_block_keys": ["bullet", "bullet-body"], "page_range": None, "mapping_status": "unavailable",
    })
    v2 = _sections_by_block(select_analysis_units([source], selector_version=SELECTOR_VERSION_V2))
    v1 = _sections_by_block(select_analysis_units([source]))
    # v1 never treats a bullet as a heading: both blocks stay in the preceding eligibility scope
    assert v1.get("bullet") == ["eligibility"]
    if kinds is None:
        assert v2.get("bullet") == ["eligibility"] and v2.get("bullet-body") == ["eligibility"]
    else:
        # one level below numbered headings: nested inside the open eligibility scope
        assert v2["bullet"] == sorted({"eligibility", *kinds}, key=["overview", "schedule", "budget",
                                      "eligibility", "evaluation", "contract"].index)
        assert v2["bullet-body"] == v2["bullet"]


def test_b23_unknown_selector_and_mismatched_selector_sha_are_selection_incomplete() -> None:
    with pytest.raises(CardAnalysisSelectionError, match="card_source_selection_incomplete"):
        select_analysis_units([_polytech_source()], selector_version="card-sections-v5")
    selection = select_analysis_units([_polytech_source()], selector_version=SELECTOR_VERSION_V2)
    tampered = selection.model_copy(update={"selector": selection.selector.model_copy(
        update={"sha256": SELECTOR_SHA256})})
    with pytest.raises(CardAnalysisSelectionError, match="card_source_selection_incomplete"):
        freeze_card_analysis_input(tampered, company_binding=_binding())
    with pytest.raises(SchemaValidationError):
        validate_payload({**freeze_card_analysis_input(selection, company_binding=_binding()).model_dump(mode="json"),
                          "selector": {**selection.selector.model_dump(mode="json"), "version": "card-sections-v5"}},
                         CARD_ANALYSIS_INPUT_SCHEMA)


def _all_met_world():
    frozen = card_input(["CMS 구축"])
    unit = frozen.units[0]
    extract = CardRequirementExtract.model_validate({"schema_version": "bidops.requirement-extract.v1", "items": [
        extract_item(unit, type_="기능", concepts=[{"concept_id": "cap.cms", "alias_text": "CMS 구축"}]),
    ]})
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": unit.unit_id, "fit_status": "met", "evidence_ids": [], "reason_codes": ["confirmed_match"],
         "constraint_results": []},
    ]})
    inputs = build_verdict_role_inputs(extract, compare)
    roles = {role: validate_verdict_role(_role_output(value), role_input=value) for role, value in inputs.items()}
    return frozen, extract, compare, build_synthesis_input(roles)


def test_b23_missing_sections_cap_the_verdict_below_proceed_and_are_recorded() -> None:
    frozen, extract, compare, synthesis_input = _all_met_world()
    proceed = _synthesis(frozen.units, verdict="진행 가능", blocking=[])
    # with every unit met and nothing unresolved, "진행 가능" is valid only without missing sections
    assert validate_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract,
                                         compare=compare).verdict == "진행 가능"
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract,
                                      compare=compare, missing_sections=["contract"])
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        assemble_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract,
                                      compare=compare, missing_sections=["contract"])
    conditional = _synthesis(frozen.units, verdict="조건부 진행", blocking=[])
    assembled = assemble_practitioner_verdict(conditional, synthesis_input=synthesis_input, extract=extract,
                                              compare=compare, missing_sections=["contract"])
    assert assembled.verdict == "조건부 진행" and assembled.missing_sections == ["contract"]
    payload = assembled.model_dump(mode="json")
    assert payload["missing_sections"] == ["contract"]
    # code-owned row: a stored final that says 진행 가능 with a missing section never parses
    with pytest.raises(ValidationError):
        CardAssembledPractitionerVerdict.model_validate({**payload, "verdict": "진행 가능"})
    # rows stored before the key existed read as null (additive key)
    legacy = {key: value for key, value in payload.items() if key != "missing_sections"}
    assert CardAssembledPractitionerVerdict.model_validate(legacy).missing_sections is None
    assert assemble_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract,
                                         compare=compare).missing_sections == []


# --- 결정 B30: selector card-sections-v3 (TOC without page numbers, title-only units) -------
#
# The real Polytech structure (T12 4차 offline diagnosis) has a table of contents
# whose entries carry no page numbers (paragraph-1-19 "목    차" .. -63, blanks to
# -71).  The manifest makes the numbered TOC entries single-block segments, so
# v2 sent three title-only units ("1. 사업개요", "2. 추진배경 및 필요성",
# "4. 추진일정") that a model cannot extract a requirement from.  Texts below are
# the public RFP's TOC titles (the contact line before the marker is left out).

POLYTECH_TOC_BLOCKS = (
    ("paragraph-1-19", "목    차"),
    ("paragraph-1-20", ""),
    ("paragraph-1-21", "Ⅰ. 사업개요"),
    ("paragraph-1-22", "1. 사업개요"),
    ("paragraph-1-23", "2. 추진배경 및 필요성"),
    ("paragraph-1-24", "3. 사업내용"),
    ("paragraph-1-25", "4. 추진일정"),
    ("paragraph-1-26", "5. 기대효과"),
    ("paragraph-1-27", ""),
    ("paragraph-1-28", "Ⅱ. 유지관리 대상"),
    ("paragraph-1-29", "1. 유지관리 대상"),
    ("paragraph-1-30", "2. 시스템 구성도 및 기타 현황자료"),
    ("paragraph-1-31", ""),
    ("paragraph-1-32", "Ⅲ. 제안요청 내용"),
    ("paragraph-1-33", "1. 제안요청 개요"),
    ("paragraph-1-34", "2. 상세 요구사항"),
    ("paragraph-1-35", " 표준 요구사항"),
    ("paragraph-1-36", " 유지관리 수행 요구사항"),
    ("paragraph-1-45", ""),
    ("paragraph-1-46", "Ⅳ. 제안서 작성 안내"),
    ("paragraph-1-47", "1. 제안서의 효력"),
    ("paragraph-1-51", "5. 제안서 목차 및 세부 작성지침"),
    ("paragraph-1-52", ""),
    ("paragraph-1-53", "Ⅴ. 제안 안내\t26"),
    ("paragraph-1-54", "1. 입찰방식"),
    ("paragraph-1-55", "2. 사업자 선정방법"),
    ("paragraph-1-56", "3. 입찰 및 기타 유의사항"),
    ("paragraph-1-57", ""),
    ("paragraph-1-58", "【붙임자료】"),
    ("paragraph-1-59", "붙임 1. 제안서 관련 서식"),
    ("paragraph-1-60", "붙임 2. 계약 관련 서식"),
    ("paragraph-1-64", ""),
    ("paragraph-1-71", ""),
)
#: Manifest segments of the TOC region (one per numbered entry, as in the real manifest).
POLYTECH_TOC_SEGMENTS = (
    ("paragraph-1-22",), ("paragraph-1-23",), ("paragraph-1-24",), ("paragraph-1-25",),
    ("paragraph-1-26", "paragraph-1-27", "paragraph-1-28"), ("paragraph-1-29",),
    ("paragraph-1-30", "paragraph-1-31", "paragraph-1-32"), ("paragraph-1-33",),
    ("paragraph-1-34", "paragraph-1-35", "paragraph-1-36", "paragraph-1-45", "paragraph-1-46"),
    ("paragraph-1-47",), ("paragraph-1-51", "paragraph-1-52", "paragraph-1-53"),
    ("paragraph-1-54",), ("paragraph-1-55",),
    ("paragraph-1-56", "paragraph-1-57", "paragraph-1-58", "paragraph-1-59", "paragraph-1-60",
     "paragraph-1-64", "paragraph-1-71"),
)
TOC_KEYS = {key for key, _text in POLYTECH_TOC_BLOCKS}


def _polytech_source_with_toc() -> dict:
    """TOC region, the chapter banner table, then the v2 Polytech body blocks."""

    banner = [
        _block("table-1-3-block", "", kind="table", table="table-1-3"),
        _block("table-1-3-r0-c0", "Ⅰ", kind="table_cell", table="table-1-3", row=0, column=0),
        _block("table-1-3-r0-c2", "사업개요", kind="table_cell", table="table-1-3", row=0, column=2),
    ]
    body = [_block(key, text) for key, text in POLYTECH_BLOCKS]
    blocks = [*(_block(key, text) for key, text in POLYTECH_TOC_BLOCKS), body[0], *banner, *body[1:]]
    positions = {block["block_key"]: index for index, block in enumerate(blocks)}
    segments = [*POLYTECH_TOC_SEGMENTS, *POLYTECH_SEGMENTS]
    return {
        "source_sha256": POLYTECH_SHA, "document_version_id": uuid4(), "structure_id": uuid4(),
        "manifest_id": uuid4(), "blocks": blocks, "cards": [],
        "segments": [
            {"segment_id": uuid4(), "ordinal": ordinal, "source_block_keys": list(keys),
             "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
             "page_range": None, "mapping_status": "unavailable"}
            for ordinal, keys in enumerate(segments, start=1)
        ],
    }


def _unit_keys(selection) -> list[list[str]]:
    return [[block.block_key for block in unit.blocks] for unit in selection.units]


def test_b30_v2_is_unchanged_and_still_sends_the_title_only_toc_units() -> None:
    # Same three title-only units the real T12 batch 0 carried (units 0..2).
    selection = select_analysis_units([_polytech_source_with_toc()], selector_version=SELECTOR_VERSION_V2)
    assert selection.selector.sha256 == SELECTOR_SHA256_V2
    keys = _unit_keys(selection)
    assert keys[:3] == [["paragraph-1-22"], ["paragraph-1-23"], ["paragraph-1-25"]]
    assert selection.missing_sections == ["contract"]
    # v2 on the body-only fixture is exactly the earlier B23 result
    body = select_analysis_units([_polytech_source()], selector_version=SELECTOR_VERSION_V2)
    assert keys[3:] == _unit_keys(body)


def test_b30_v3_excludes_the_toc_without_page_numbers_and_title_only_units() -> None:
    source = _polytech_source_with_toc()
    selection = select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)
    assert selection.selector.version == SELECTOR_VERSION_V3 == "card-sections-v3"
    assert selection.selector.sha256 == SELECTOR_SHA256_V3 == (
        "8c4332763fb89a47ebd67a3c9f59575406fcef0a2a878ed66dd3309a39654d38")
    assert SELECTOR_SHA256_V2 == "d3ed2e2e6f573b1c5a7830ace9a02e363a9a0ae4929643c871b6d6a309b94617"
    assert len({SELECTOR_SHA256, SELECTOR_SHA256_V2, SELECTOR_SHA256_V3}) == 3
    keys = _unit_keys(selection)
    assert not any(key in TOC_KEYS for unit in keys for key in unit)
    # no unit is only a heading: every unit has a non-heading, non-blank block
    by_key = {block["block_key"]: block["text"] for block in source["blocks"]}
    for unit in keys:
        assert any(by_key[key].strip() and key not in {"paragraph-1-73", "paragraph-1-83", "paragraph-1-115",
                                                         "paragraph-1-248", "paragraph-1-264"}
                   for key in unit), unit
    # the body units, sections and missing sections are the v2 body result
    body_v2 = select_analysis_units([_polytech_source()], selector_version=SELECTOR_VERSION_V2)
    assert keys == _unit_keys(body_v2)
    assert selection.missing_sections == ["contract"]
    assert [unit.section_kinds for unit in selection.units] == [unit.section_kinds for unit in body_v2.units]
    frozen = freeze_card_analysis_input(selection, company_binding=_binding())
    payload = frozen.model_dump(mode="json")
    validate_payload(payload, CARD_ANALYSIS_INPUT_SCHEMA)
    assert payload["selector"]["version"] == "card-sections-v3"


def _toc_source(entries: list[str], body: list[tuple[str, str, list[str]]]) -> dict:
    """``목차`` + entries (``toc-<i>``), then body segments ``(heading, text, extra_keys)``."""

    blocks = [_block("toc", "목 차"), *(_block(f"toc-{index}", text) for index, text in enumerate(entries))]
    segments = [[f"toc-{index}"] for index, _text in enumerate(entries)]
    for index, (heading, text, _extra) in enumerate(body):
        blocks.append(_block(f"h-{index}", heading))
        keys = [f"h-{index}"]
        if text:
            blocks.append(_block(f"b-{index}", text))
            keys.append(f"b-{index}")
        segments.append(keys)
    positions = {block["block_key"]: index for index, block in enumerate(blocks)}
    return {
        "source_sha256": SOURCE_SHA, "document_version_id": uuid4(), "structure_id": uuid4(),
        "manifest_id": uuid4(), "blocks": blocks, "cards": [],
        "segments": [
            {"segment_id": uuid4(), "ordinal": ordinal, "source_block_keys": keys,
             "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
             "page_range": None, "mapping_status": "unavailable"}
            for ordinal, keys in enumerate(segments, start=1)
        ],
    }


def test_b30_toc_region_stops_at_the_repeated_first_body_heading() -> None:
    # No banner table between TOC and body: the body heading repeats a TOC entry.
    source = _toc_source(
        ["1. 사업개요", "2. 사업예산", "3. 입찰참가자격"],
        [("1. 사업개요", "대학 홈페이지 유지관리", []), ("2. 사업예산", "", []),
         ("3. 입찰참가자격", "소프트웨어사업자로 신고한 자", [])],
    )
    v3 = select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)
    assert _unit_keys(v3) == [["h-0", "b-0"], ["h-2", "b-2"]]  # "2. 사업예산" alone is title-only
    assert v3.missing_sections == ["schedule", "budget", "evaluation", "contract"]
    v2 = select_analysis_units([source], selector_version=SELECTOR_VERSION_V2)
    assert _unit_keys(v2) == [["toc-0"], ["toc-1"], ["toc-2"], ["h-0", "b-0"], ["h-1"], ["h-2", "b-2"]]
    assert v2.missing_sections == ["schedule", "evaluation", "contract"]


def test_b30_toc_region_stops_at_body_text_and_keeps_the_page_numbered_rule() -> None:
    # a body paragraph ends the region: the numbered line after it is not a TOC entry
    # (it carries a digit after its number, so it is content and stays a unit)
    source = _toc_source(["1. 사업개요", "2. 2027년 사업기간"], [("3. 사업예산", "사업비 2억원", [])])
    source["blocks"].insert(2, _block("note", "본 제안요청서는 사업 수행을 위한 요구사항을 기술한다."))
    v3 = select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)
    assert _unit_keys(v3) == [["toc-1"], ["h-0", "b-0"]]
    without_note = _toc_source(["1. 사업개요", "2. 2027년 사업기간"], [("3. 사업예산", "사업비 2억원", [])])
    assert _unit_keys(select_analysis_units([without_note], selector_version=SELECTOR_VERSION_V3)) == [
        ["h-0", "b-0"]]
    # a page-numbered TOC (v1 rule) is still excluded, entries without a lead included
    numbered = _toc_source(["사업개요 ······ 3", "1. 사업예산  4"], [("1. 사업예산", "사업비 2억원", [])])
    assert _unit_keys(select_analysis_units([numbered], selector_version=SELECTOR_VERSION_V3)) == [["h-0", "b-0"]]
    assert _unit_keys(select_analysis_units([numbered])) == [["h-0", "b-0"]]
    # a label: value line is body text, never a TOC entry
    labelled = _toc_source(["1. 사업예산: 2억원"], [("2. 사업기간", "착수 후 6개월", [])])
    assert _unit_keys(select_analysis_units([labelled], selector_version=SELECTOR_VERSION_V3)) == [
        ["toc-0"], ["h-0", "b-0"]]


def test_b30_two_toc_markers_make_no_region_and_inline_value_headings_are_body() -> None:
    source = _toc_source(["1. 사업개요"], [("1. 사업개요", "대학 홈페이지 유지관리", [])])
    source["blocks"].insert(0, _block("toc-again", "목차"))
    v3 = select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)
    # ambiguous markers: no TOC region, but the TOC entry is still a title-only unit and is dropped
    assert _unit_keys(v3) == [["h-0", "b-0"]]
    inline = _toc_source([], [("1. 사업기간: 계약일로부터 12개월", "", []), ("2. 추진일정", "", []),
                              ("3. 2027년 사업예산", "", [])])
    keys = _unit_keys(select_analysis_units([inline], selector_version=SELECTOR_VERSION_V3))
    # ":" or a digit after the leading number is content; a bare title is dropped
    assert keys == [["h-0"], ["h-2"]]


def test_b30_expected_concepts_use_verbatim_in_context_terms_and_fail_closed_when_inexpressible() -> None:
    from app.deep_review.services.company_analysis_input import CompanyAnalysisError, card_expected_concepts

    concepts = (
        OntologyConcept("tech.ai", "AI", (), "technology"),
        OntologyConcept("cap.ai-platform", "AI플랫폼", (), "capability"),
        OntologyConcept("cap.web-accessibility", "웹접근성", ("웹 접근성",), "capability"),
    )
    # "ai" inside "mail" is not an occurrence; the later "AI" is copied as written.
    assert card_expected_concepts(["mail 서버와 AI 도입"], concepts) == [
        {"concept_id": "tech.ai", "alias_text": "AI"}]
    # whitespace inside the term is copied verbatim (validator: substring of the block)
    rows = card_expected_concepts(["웹\n접근성 인증 유지", "본문"], concepts)
    assert rows == [{"concept_id": "cap.web-accessibility", "alias_text": "웹\n접근성"}]
    validate_requirement_extract(
        {"schema_version": "bidops.requirement-extract.v1", "items": [extract_item(
            card_input(["웹\n접근성 인증 유지"]).units[0], type_="운영", concepts=rows)]},
        card_input=card_input(["웹\n접근성 인증 유지"]), batch_index=0, ontology=concepts,
    )
    assert card_expected_concepts(["본문"], concepts) == []
    # "OpenAI플랫폼": the platform concept matches the text, but its only occurrence
    # "AI플랫폼" also matches tech.ai on its own, which the unit text does not: no
    # passing answer exists, so the payload fails closed before any call.
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        card_expected_concepts(["OpenAI플랫폼 도입"], concepts)


# --- 결정 B33: bidops.requirement-extract.v2 (model output of policy v4) -------------------

def _v2_constraint(kind: str, value, unit) -> dict:
    return {"kind": kind, "value": value, "unit": unit, "fact_key": None, "quote": "인용",
            "locator": {"source_sha256": SOURCE_SHA, "block_key": "block-0"}}


def _v2_answer(constraints: list[dict]) -> dict:
    return {"schema_version": "bidops.requirement-extract.v2", "items": [{
        "unit_id": "u-1", "type": "운영", "normalized_requirement": "요구", "mandatory": None,
        "constraints": constraints, "unknowns": [],
        "evidence": [{"source_sha256": SOURCE_SHA, "block_key": "block-0", "quote": "인용"}],
    }]}


V2_VALUES = {"amount": 1000, "duration": 12, "count": 3, "percentage": 10, "date": "2027-01-31",
             "boolean": True, "text": "다음 달 10일까지"}
V2_UNITS = ("KRW", "person", "month", "day", "year", "percent", None)


def test_b33_v2_schema_kind_unit_branches_are_exactly_the_validator_table() -> None:
    # Every kind x unit pair: the output schema accepts it iff the pydantic DTO does (no invented rule).
    from app.deep_review.schemas.card_analysis import CardRequirementConstraint

    for kind, value in V2_VALUES.items():
        for unit in V2_UNITS:
            constraint = _v2_constraint(kind, value, unit)
            try:
                validate_payload(_v2_answer([constraint]), "requirement-extract-v2")
                schema_ok = True
            except SchemaValidationError:
                schema_ok = False
            try:
                CardRequirementConstraint.model_validate({**constraint, "operator": "eq"})
                dto_ok = True
            except ValidationError:
                dto_ok = False
            assert schema_ok == dto_ok, (kind, unit)
    # value formats per kind (date pattern, numbers are not bools, text/date non-empty)
    for kind, value, unit in (("date", "2027", None), ("date", "2027.1.31", None), ("count", True, None),
                              ("amount", "1000", "KRW"), ("text", "", None), ("boolean", "true", None),
                              ("count", 10, "day")):
        with pytest.raises(SchemaValidationError):
            validate_payload(_v2_answer([_v2_constraint(kind, value, unit)]), "requirement-extract-v2")
    for kind, value in V2_VALUES.items():
        unit = {"amount": "KRW", "duration": "day", "percentage": "percent"}.get(kind)
        validate_payload(_v2_answer([_v2_constraint(kind, value, unit)]), "requirement-extract-v2")


def test_b33_v2_schema_has_no_model_supplied_concepts_operators_or_fact_keys() -> None:
    answer = _v2_answer([_v2_constraint("text", "다음 달 10일까지", None)])
    validate_payload(answer, "requirement-extract-v2")
    for mutate in (
        lambda a: a["items"][0].__setitem__("concept_candidates", []),
        lambda a: a["items"][0]["constraints"][0].__setitem__("operator", "eq"),
        lambda a: a["items"][0]["constraints"][0].__setitem__("fact_key", "staff:onsite"),
        lambda a: a["items"][0]["constraints"][0].pop("fact_key"),
        lambda a: a.__setitem__("schema_version", "bidops.requirement-extract.v1"),
        lambda a: a["items"][0].__setitem__("evidence", []),
    ):
        changed = deepcopy(answer)
        mutate(changed)
        with pytest.raises(SchemaValidationError):
            validate_payload(changed, "requirement-extract-v2")


def _v2_item(unit: CardAnalysisUnit, *, constraints=(), quote: str | None = None) -> dict:
    return {"unit_id": unit.unit_id, "type": "운영", "normalized_requirement": unit.blocks[0].text,
            "mandatory": None, "constraints": list(constraints), "unknowns": [],
            "evidence": [evidence(unit, quote)]}


def test_b33_assembly_derives_concepts_and_operators_and_classifies_failures() -> None:
    from app.deep_review.services.card_analysis import (
        CardExtractStructureError,
        assemble_requirement_extract_v2,
        expected_constraint_operator,
    )

    texts = ["CMS 구축 및 상주 인원 3명 이상", "정기점검보고서 제출(다음 달 10일까지)"]
    frozen = card_input(texts)
    first, second = frozen.units
    answer = {"schema_version": "bidops.requirement-extract.v2", "items": [
        _v2_item(first, constraints=[{
            "kind": "count", "value": 3, "unit": "person", "fact_key": None, "quote": "상주 인원 3명 이상",
            "locator": {"source_sha256": SOURCE_SHA, "block_key": first.blocks[0].block_key}}]),
        _v2_item(second, constraints=[{
            "kind": "text", "value": "다음 달 10일까지", "unit": None, "fact_key": None, "quote": "다음 달 10일까지",
            "locator": {"source_sha256": SOURCE_SHA, "block_key": second.blocks[0].block_key}}]),
    ]}
    assembled = assemble_requirement_extract_v2(answer, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert assembled["schema_version"] == "bidops.requirement-extract.v1"
    # code-derived: the validator's own operator rule and the unit's expected concepts
    # 결정 B35: "까지" (deadline) is lte like "이내"
    assert [c["operator"] for item in assembled["items"] for c in item["constraints"]] == ["gte", "lte"]
    assert expected_constraint_operator("text", "다음 달 10일까지") == "lte"
    assert [item["concept_candidates"] for item in assembled["items"]] == [
        [{"concept_id": "cap.cms", "alias_text": "CMS 구축"}], []]
    # every model field is copied unchanged
    for model_item, built in zip(answer["items"], assembled["items"]):
        assert {key: built[key] for key in model_item if key != "constraints"} == {
            key: value for key, value in model_item.items() if key != "constraints"}
        assert [{k: v for k, v in c.items() if k != "operator"} for c in built["constraints"]] == model_item["constraints"]
    validate_requirement_extract(assembled, card_input=frozen, batch_index=0, ontology=ONTOLOGY)

    def structure(mutate) -> CardExtractStructureError:
        changed = deepcopy(answer)
        mutate(changed)
        with pytest.raises(CardExtractStructureError) as error:
            assemble_requirement_extract_v2(changed, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
        assert error.value.code == "card_extract_invalid"
        return error.value

    # schema-class (repairable): kind x unit, value format, duplicates, item-per-unit order/count
    error = structure(lambda a: a["items"][1]["constraints"][0].update({"kind": "count", "unit": "day", "value": 10}))
    assert error.rule_codes == ["constraint_unit_invalid", "output_schema"] and error.item_indexes == [1]
    error = structure(lambda a: a["items"][1]["constraints"][0].update({"kind": "date", "value": "2027"}))
    assert "constraint_value_invalid" in error.rule_codes and error.item_indexes == [1]
    error = structure(lambda a: a["items"][0]["constraints"].append(deepcopy(a["items"][0]["constraints"][0])))
    assert error.rule_codes == ["extract_reference_duplicate"] and error.item_indexes == [0]
    error = structure(lambda a: a["items"].reverse())
    assert error.rule_codes == ["extract_unit_coverage"] and error.item_indexes == [0, 1]
    error = structure(lambda a: a["items"].pop())
    assert error.rule_codes == ["extract_unit_coverage"] and error.item_indexes == [1]
    # the model never supplies the derived fields
    error = structure(lambda a: a["items"][0].__setitem__("concept_candidates", []))
    assert error.rule_codes == ["output_schema"]
    error = structure(lambda a: a["items"][0]["constraints"][0].__setitem__("operator", "gte"))
    assert error.rule_codes == ["output_schema"]
    # quote / number failures pass assembly and stay non-repairable validator failures
    for mutate in (
        lambda a: a["items"][0]["evidence"][0].__setitem__("quote", "원문에 없음"),
        lambda a: a["items"][0].__setitem__("normalized_requirement", "상주 인원 5명"),
        lambda a: a["items"][0]["constraints"][0].__setitem__("value", 4),
    ):
        changed = deepcopy(answer)
        mutate(changed)
        built = assemble_requirement_extract_v2(changed, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
        with pytest.raises(CardAnalysisValidationError) as failure:
            validate_requirement_extract(built, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
        assert type(failure.value) is CardAnalysisValidationError


def test_b33_repair_envelope_carries_only_codes_and_indexes() -> None:
    from app.deep_review.services.card_analysis import CardAnalysisRuntimeError, stage_prompt

    plain = json.loads(stage_prompt("extract", "x", {}, {"a": 1}, repair=True))
    assert plain["validation_repair"] == {"scope": "syntax_or_schema_only"}
    detailed = json.loads(stage_prompt("extract", "x", {}, {"a": 1}, repair=True, repair_detail={
        "rule_codes": ["constraint_unit_invalid"], "item_indexes": [3]}))
    assert detailed["validation_repair"] == {"scope": "syntax_or_schema_only",
                                             "rule_codes": ["constraint_unit_invalid"], "item_indexes": [3]}
    assert "validation_repair" not in json.loads(stage_prompt("extract", "x", {}, {"a": 1}, repair=False,
                                                              repair_detail={"rule_codes": ["x_y"], "item_indexes": []}))
    for bad in ({"rule_codes": ["다음 달 10일까지"], "item_indexes": []}, {"rule_codes": [], "item_indexes": []},
                {"rule_codes": ["ok_code"], "item_indexes": ["0"]},
                {"rule_codes": ["ok_code"], "item_indexes": [], "quote": "원문"}):
        with pytest.raises(CardAnalysisRuntimeError):
            stage_prompt("extract", "x", {}, {"a": 1}, repair=True, repair_detail=bad)


# --- 결정 B35: truncated constraint quotes and the deadline vocabulary ---------------------
#
# Sanitized excerpts of the real T12 6차 batch 1 cards (MPR-5, MHR-2, PER-1, SER-2).  The
# v4 answers quoted only the number, so the quote-derived operator read eq.

B35_PENALTY = "중복장애(장애횟수)품질기준- 월 3회 미만벌점- 3회 초과 시 벌점 ※ 월 유지관리 금액 10% 삭감"
B35_HANDOVER = "동급 이상의 대체인력을 투입하여 5일 이상의 업무 인계·인수기간을 두어야 함"
B35_CAPACITY = "사용하는 사용자 숫자가 동시 사용자 용량의 90%를 초과하는 경우에는 적용되지 않음"
B35_PASSWORD = "화면 보호기(10분 간격) 패스워드를 문자‧숫자‧특수문자가 조합된 9글자 이상으로 설정"
B35_RESPONSE = "사용자가 요청한 시간으로부터 3초 내에 완전히 디스플레이 되어야 함"


def _b35_validate(text: str, kind: str, value, unit_name, quote: str):
    from app.deep_review.services.card_analysis import expected_constraint_operator

    frozen = card_input([text])
    unit = frozen.units[0]
    operator = expected_constraint_operator(kind, quote)
    payload = {"schema_version": "bidops.requirement-extract.v1", "items": [extract_item(
        unit, type_="운영", mandatory=None, normalized="요구사항",
        constraints=[constraint(unit, kind=kind, value=value, unit_name=unit_name, operator=operator, quote=quote)],
    )]}
    validate_requirement_extract(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    return operator


@pytest.mark.parametrize(
    ("text", "kind", "value", "unit_name", "short", "full", "operator", "rule"),
    [
        # 결정 B37: "3" is twice in the block ("3회 미만", "3회 초과") -> not unique before truncation
        (B35_PENALTY, "count", 3, None, "3", "3회 미만", "unknown", "constraint_quote_not_unique"),
        (B35_HANDOVER, "duration", 5, "day", "5", "5일 이상", "gte", "constraint_quote_truncated"),
        (B35_HANDOVER, "duration", 5, "day", "5일", "5일 이상", "gte", "constraint_quote_truncated"),
        (B35_CAPACITY, "percentage", 90, "percent", "90%", "90%를 초과", "unknown", "constraint_quote_truncated"),
        (B35_PASSWORD, "text", "9글자 이상", None, "9", "9글자 이상", "gte", "constraint_quote_truncated"),
        (B35_PASSWORD, "text", "10분 간격", None, "10", "10분 간격", "eq", "constraint_quote_truncated"),
        (B35_RESPONSE, "text", "3초 내에", None, "3초", "3초 내에", "lte", "constraint_quote_truncated"),
    ],
)
def test_b35_truncated_quote_is_rejected_and_the_full_quote_passes(text, kind, value, unit_name, short, full,
                                                                  operator, rule) -> None:
    from app.deep_review.services.card_analysis import constraint_quote_truncated

    short_value = value if kind != "text" else short
    with pytest.raises(CardAnalysisValidationError) as error:
        _b35_validate(text, kind, short_value, unit_name, short)
    assert error.value.code == "card_extract_invalid" and error.value.rule_code == rule
    assert constraint_quote_truncated(kind, short, text) is True
    assert constraint_quote_truncated(kind, full, text) is False
    assert _b35_validate(text, kind, value, unit_name, full) == operator


@pytest.mark.parametrize(
    ("kind", "quote", "text"),
    [
        ("percentage", "10%", B35_PENALTY),                       # "10% 삭감": no unit/comparator follows
        ("amount", "134,700천원", "사업예산: 134,700천원(부가가치세 포함)"),
        ("duration", "5일 이상", B35_HANDOVER),                    # "이상의 업무": particle, then a noun
        ("count", "1회", "점검 주기(연 1회) 실시"),
        ("count", "3명", "인력 3명이 상주"),                       # "이" + space is not "이상"
        ("count", "3개", "점검 항목 3개 내용 확인"),               # "내용" is not "내"
        ("boolean", "ISO 9001", "ISO 9001 이상 인증 보유"),         # boolean is never checked
        ("text", "대체인력", B35_HANDOVER),                        # no digit in the quote
    ],
)
def test_b35_complete_quotes_are_not_truncated(kind, quote, text) -> None:
    from app.deep_review.services.card_analysis import constraint_quote_truncated

    assert constraint_quote_truncated(kind, quote, text) is False


def test_b35_number_continuing_after_the_quote_is_truncated() -> None:
    from app.deep_review.services.card_analysis import constraint_quote_truncated

    assert constraint_quote_truncated("count", "1", "인원 10명") is True  # the number itself continues
    # 결정 B37 replaced the B35 "any occurrence" rule: a repeated quote is now not unique (see below)
    # and truncation is judged on the single cited occurrence only.


@pytest.mark.parametrize(
    ("kind", "quote", "expected"),
    [
        ("text", "3초 내에", "lte"), ("text", "10일 내로 제출", "lte"), ("duration", "10일 내", "lte"),
        ("text", "다음 달 10일까지", "lte"), ("text", "4시간 이내", "lte"),
        ("count", "3개 내용", "eq"), ("count", "국내 3개", "eq"), ("count", "3개 내부 서버", "eq"),
        ("text", "1단계부터 3단계까지", "unknown"), ("count", "3명 이상 5명까지", "unknown"),
        ("count", "3회 미만", "unknown"), ("percentage", "90%를 초과", "unknown"),
        # the existing relative-date rule keeps unknown for text/date
        ("text", "계약 후 30일까지", "unknown"), ("date", "착수 후 2027.1.31까지", "unknown"),
        ("count", "5명 이상", "gte"), ("count", "3명", "eq"),
    ],
)
def test_b35_operator_vocabulary(kind, quote, expected) -> None:
    from app.deep_review.services.card_analysis import expected_constraint_operator

    assert expected_constraint_operator(kind, quote) == expected


def test_b35_mock_numeric_constraints_quote_unit_and_comparator_and_pass_the_validator() -> None:
    from app.deep_review.services.card_analysis import assemble_requirement_extract_v2
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient, mock_numeric_constraints

    texts = [B35_HANDOVER, B35_CAPACITY, "투입인력 3명 이상, 추정가격 금150,000,000원(부가세 포함)",
             "장애 2～3명 대기, 금액 10% 삭감"]
    frozen = card_input(texts)
    payload_units = [unit.model_dump(mode="json") for unit in frozen.units]
    quotes = [[c["quote"] for c in mock_numeric_constraints(unit)] for unit in payload_units]
    assert quotes == [["5일 이상"], ["90%를 초과"], ["3명 이상", "150,000,000원"], ["10%"]]  # "～3명" is skipped
    answer = MockCardAnalysisClient(ONTOLOGY)._extract({"units": payload_units}, v2=True)
    validate_payload(answer, "requirement-extract-v2")
    assembled = assemble_requirement_extract_v2(answer, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    validate_requirement_extract(assembled, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert [[c["operator"] for c in item["constraints"]] for item in assembled["items"]] == [
        ["gte"], ["unknown"], ["gte", "eq"], ["eq"]]
    assert assembled["items"][2]["constraints"][1]["value"] == 150_000_000


@pytest.mark.parametrize(
    ("kind", "value", "unit_name", "quote", "text", "truncated"),
    [
        # 결정 B36: front truncation (the number itself is cut), both directions
        ("count", 0, "person", "0명", "투입인력 10명", True),
        ("amount", 0, "KRW", "000,000원", "추정가격 금150,000,000원(부가세 포함)", True),
        ("amount", 0.5, "KRW", "5원", "단가 0.5원", True),
        ("count", 5, "person", "5명", "제3조 5명", False),
        ("count", 3, "person", "3명", "1. 3명", False),
        ("amount", 150_000_000, "KRW", "150,000,000원", "추정가격 금150,000,000원(부가세 포함)", False),
    ],
)
def test_b36_front_truncated_quote_is_rejected(kind, value, unit_name, quote, text, truncated) -> None:
    from app.deep_review.services.card_analysis import CardConstraintQuoteTruncatedError, constraint_quote_truncated

    assert constraint_quote_truncated(kind, quote, text) is truncated
    if truncated:
        with pytest.raises(CardConstraintQuoteTruncatedError) as error:
            _b35_validate(text, kind, value, unit_name, quote)
        assert error.value.rule_code == "constraint_quote_truncated"
    else:
        assert _b35_validate(text, kind, value, unit_name, quote) == "eq"


def test_b36_front_cut_repeat_is_still_rejected_as_not_unique() -> None:
    from app.deep_review.services.card_analysis import CardConstraintQuoteNotUniqueError, constraint_quote_occurrences

    # "0명" is a whole number once ("0명 감소") and also the tail of "10명": two occurrences (결정 B37)
    text = "결원 0명 감소, 투입 10명"
    assert constraint_quote_occurrences("0명", text) == 2
    with pytest.raises(CardConstraintQuoteNotUniqueError):
        _b35_validate(text, "count", 0, "person", "0명")



# --- 결정 B37: quote uniqueness (single cited occurrence) and range forms -------------------

B37_INSPECTION = "○ 정기점검(월 1회)  - 대상: 유지관리 대상 홈페이지 전체○ 특별점검(연 1회 이상): 웹 취약점 점검"


def test_b37_repeated_quote_is_not_unique_and_the_left_extended_quotes_pass() -> None:
    from app.deep_review.services.card_analysis import (
        CardConstraintQuoteNotUniqueError,
        constraint_quote_occurrences,
        constraint_quote_truncated,
    )

    assert constraint_quote_occurrences("1회", B37_INSPECTION) == 2
    with pytest.raises(CardConstraintQuoteNotUniqueError) as error:
        _b35_validate(B37_INSPECTION, "count", 1, None, "1회")
    assert error.value.code == "card_extract_invalid" and error.value.rule_code == "constraint_quote_not_unique"
    assert _b35_validate(B37_INSPECTION, "count", 1, None, "월 1회") == "eq"
    assert _b35_validate(B37_INSPECTION, "count", 1, None, "연 1회 이상") == "gte"
    # truncation is still caught on a unique occurrence ("연 1회" is followed by "이상")
    assert constraint_quote_occurrences("연 1회", B37_INSPECTION) == 1
    assert constraint_quote_truncated("count", "연 1회", B37_INSPECTION) is True
    with pytest.raises(CardAnalysisValidationError) as truncated:
        _b35_validate(B37_INSPECTION, "count", 1, None, "연 1회")
    assert truncated.value.rule_code == "constraint_quote_truncated"
    # quotes without digits and boolean constraints are outside the rule
    assert _b35_validate("보안 교육 실시, 보안 교육 결과 제출", "text", "보안 교육", None, "보안 교육") == "eq"


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("4〜8시간", "unknown"), ("8〜12시간", "unknown"), ("2～3점", "unknown"), ("3~4회", "unknown"),
        ("2027. 1. 1. ～ 2027. 12. 31.", "unknown"), ("2027. 1. 1. ~ 12. 31.", "unknown"),
        ("4-8시간", "unknown"), ("1–2단계", "unknown"), ("10 − 20%", "unknown"),
        # negatives: not ranges
        ("전화 032-650-6751", "eq"), ("2027-01-31", "eq"), ("SFR-001", "eq"), ("MPR-005 요구사항", "eq"),
        ("벌점- 3회", "eq"), ("24시간 이상", "gte"), ("4시간 이내", "lte"),
    ],
)
def test_b37_range_forms_derive_unknown(quote, expected) -> None:
    from app.deep_review.services.card_analysis import expected_constraint_operator

    assert expected_constraint_operator("count" if quote[0].isdigit() else "text", quote) == expected


def test_b37_date_range_is_text_unknown_and_a_computed_duration_fails() -> None:
    period = "사업기간: 2027. 1. 1. ～ 2027. 12. 31."
    quote = "2027. 1. 1. ～ 2027. 12. 31."
    assert _b35_validate(period, "text", quote, None, quote) == "unknown"
    # the T12 7차 model error: a duration of 12 months computed from the range (12 is in the quote,
    # but "12개월" is not -- the duration expression must be the quote's own)
    with pytest.raises(CardAnalysisValidationError):
        _b35_validate(period, "duration", 12, "month", quote)


def test_b37_mock_extends_repeated_quotes_to_the_left_until_unique() -> None:
    from app.deep_review.services.card_analysis import assemble_requirement_extract_v2
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient, mock_numeric_constraints

    texts = ["정기점검 인력 3명 이상, 특별점검 인력 3명 이상 투입", "1조 3명 이상 2조 3명 이상"]
    frozen = card_input(texts)
    units = [unit.model_dump(mode="json") for unit in frozen.units]
    # first: extended by whole words on the left until unique; second: the left word carries a
    # digit, so no unique quote is formed and no constraint is emitted (never a guess)
    assert [[c["quote"] for c in mock_numeric_constraints(unit)] for unit in units] == [
        ["정기점검 인력 3명 이상", "특별점검 인력 3명 이상"], []]
    answer = MockCardAnalysisClient(ONTOLOGY)._extract({"units": units}, v2=True)
    assembled = assemble_requirement_extract_v2(answer, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    validate_requirement_extract(assembled, card_input=frozen, batch_index=0, ontology=ONTOLOGY)


# --- 결정 B51 (T18): item isolation of evidence-class extract failures ---------------------

B51_TEXTS = [
    "상주 인원 3명 이상 투입",
    "사업예산 200백만원 이하",
    "정기점검(월 1회) 및 특별점검(연 1회 이상)",
    "CMS 구축 지원",
]


def _b51_payload(frozen: CardAnalysisInput) -> dict:
    u0, u1, u2, u3 = frozen.units
    return {"schema_version": "bidops.requirement-extract.v1", "items": [
        extract_item(u0, type_="인력", normalized="상주 인원 3명 이상", constraints=[
            constraint(u0, kind="count", value=3, unit_name="person", operator="gte", quote="3명 이상")]),
        extract_item(u1, type_="계약", normalized="사업예산 200백만원 이하", constraints=[
            constraint(u1, kind="amount", value=200_000_000, unit_name="KRW", operator="lte",
                       quote="사업예산 200백만원 이하")]),
        extract_item(u2, type_="운영", normalized="정기점검 월 1회", constraints=[
            constraint(u2, kind="count", value=1, unit_name=None, operator="eq", quote="월 1회")]),
        extract_item(u3, type_="기능", normalized="CMS 구축 지원",
                     concepts=[{"concept_id": "cap.cms", "alias_text": "CMS 구축"}]),
    ]}


def test_b51_isolated_validator_rejects_only_the_failing_items_with_all_their_codes() -> None:
    from app.deep_review.services.card_analysis import (
        CardConstraintQuoteNotUniqueError,
        validate_requirement_extract_isolated,
    )

    frozen = card_input(B51_TEXTS)
    payload = _b51_payload(frozen)
    clean = validate_requirement_extract_isolated(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert clean.rejected_units == [] and len(clean.items) == 4
    assert clean.model_dump(mode="json")["items"] == validate_requirement_extract(
        payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY).model_dump(mode="json")["items"]

    bad = deepcopy(payload)
    bad["items"][1]["evidence"][0]["quote"] = "원문에 없는 인용"                      # evidence quote
    bad["items"][2]["constraints"][0]["quote"] = "1회"                             # repeated in its block
    bad["items"][2]["normalized_requirement"] = "정기점검 월 7회"                     # number not in the unit
    result = validate_requirement_extract_isolated(bad, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert [item.unit_id for item in result.items] == [frozen.units[0].unit_id, frozen.units[3].unit_id]
    assert [row.model_dump() for row in result.rejected_units] == [
        {"unit_id": frozen.units[1].unit_id, "rule_codes": ["evidence_quote_not_verbatim"]},
        {"unit_id": frozen.units[2].unit_id,
         "rule_codes": ["constraint_quote_not_unique", "requirement_number_untraceable"]},
    ]
    # the accepted items are the model's items, unchanged; the rejected ones are nowhere in items
    assert result.items[0].model_dump(mode="json") == bad["items"][0]
    stored = result.model_dump(mode="json")
    assert set(stored) == {"schema_version", "items", "rejected_units"}
    assert "원문에 없는 인용" not in json.dumps(stored, ensure_ascii=False)
    # the batch-level validator (policies v1-v6) still fails at the first violation
    with pytest.raises(CardAnalysisValidationError) as first:
        validate_requirement_extract(bad, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert type(first.value) is CardAnalysisValidationError
    only_unique = deepcopy(payload)
    only_unique["items"][2]["constraints"][0]["quote"] = "1회"
    with pytest.raises(CardConstraintQuoteNotUniqueError):
        validate_requirement_extract(only_unique, card_input=frozen, batch_index=0, ontology=ONTOLOGY)


@pytest.mark.parametrize("mutate", [
    lambda p: p["items"].reverse(),                                            # item order
    lambda p: p["items"].pop(),                                                # item count
    lambda p: p["items"][0]["constraints"].append(deepcopy(p["items"][0]["constraints"][0])),  # duplicate
    lambda p: p["items"][0]["constraints"][0].update({"unit": "day"}),          # kind x unit
    lambda p: p.__setitem__("rejected_units", []),                             # not a model field
])
def test_b51_structural_failures_still_fail_the_whole_call(mutate) -> None:
    from app.deep_review.services.card_analysis import validate_requirement_extract_isolated

    frozen = card_input(B51_TEXTS)
    payload = _b51_payload(frozen)
    mutate(payload)
    with pytest.raises(CardAnalysisValidationError) as error:
        validate_requirement_extract_isolated(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert error.value.code == "card_extract_invalid"


@pytest.mark.parametrize(("rejected", "units", "exceeds"), [
    (0, 4, False), (1, 4, False), (2, 4, True), (2, 8, False), (3, 8, True), (8, 32, False), (9, 32, True),
])
def test_b51_threshold_is_more_than_a_quarter_of_all_units(rejected, units, exceeds) -> None:
    from app.deep_review.services.card_analysis import rejected_units_exceed_limit

    assert rejected_units_exceed_limit(rejected, units) is exceeds


def test_b51_rejected_compare_row_and_dto_rules() -> None:
    from app.deep_review.schemas.card_analysis import CardRejectedUnit, CardRequirementMatrixItem
    from app.deep_review.services.card_compare import rejected_compare_row

    row = rejected_compare_row("u-1")
    assert row.model_dump(mode="json") == {"unit_id": "u-1", "fit_status": "unknown", "constraint_results": [],
                                          "evidence_ids": [], "reason_codes": ["extract_rejected"]}
    with pytest.raises(ValidationError):
        CardRejectedUnit(unit_id="u-1", rule_codes=[])
    with pytest.raises(ValidationError):
        CardRejectedUnit(unit_id="u-1", rule_codes=["원문 문장"])
    with pytest.raises(ValidationError):  # a unit is either accepted or rejected
        CardRequirementExtract.model_validate({"items": [extract_item(card_input(["가나"]).units[0])],
                                               "rejected_units": [{"unit_id": card_input(["가나"]).units[0].unit_id,
                                                                   "rule_codes": ["x_rule"]}]})
    CardRequirementMatrixItem(unit_id="u-1", type=None, fit_status="unknown", role_findings=[],
                              rejected_rule_codes=["evidence_quote_not_verbatim"])
    for bad in ({"type": "기능"}, {"fit_status": "met"}, {"rejected_rule_codes": None}):
        with pytest.raises(ValidationError):
            CardRequirementMatrixItem.model_validate({
                "unit_id": "u-1", "type": None, "fit_status": "unknown", "role_findings": [],
                "rejected_rule_codes": ["evidence_quote_not_verbatim"], **bad})


def _b51_world():
    """Two units: one accepted (all met), one rejected; compare and roles built by the real code."""

    frozen = card_input(["CMS 구축", "상주 인원 3명 이상"])
    accepted, rejected_unit = frozen.units
    extract = CardRequirementExtract.model_validate({
        "items": [extract_item(accepted, type_="기능",
                               concepts=[{"concept_id": "cap.cms", "alias_text": "CMS 구축"}])],
        "rejected_units": [{"unit_id": rejected_unit.unit_id, "rule_codes": ["constraint_quote_truncated"]}],
    })
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": accepted.unit_id, "fit_status": "met", "evidence_ids": [], "reason_codes": ["confirmed_match"],
         "constraint_results": []},
        {"unit_id": rejected_unit.unit_id, "fit_status": "unknown", "evidence_ids": [],
         "reason_codes": ["extract_rejected"], "constraint_results": []},
    ]})
    inputs = build_verdict_role_inputs(extract, compare)
    roles = {role: validate_verdict_role(_role_output(value), role_input=value) for role, value in inputs.items()}
    return frozen, extract, compare, inputs, build_synthesis_input(roles)


def test_b51_roles_never_see_a_rejected_unit_and_synthesis_is_capped() -> None:
    frozen, extract, compare, inputs, synthesis_input = _b51_world()
    accepted, rejected_unit = frozen.units
    assert all(rejected_unit.unit_id not in [row.unit_id for row in value.compare.items] for value in inputs.values())
    proceed = _synthesis([accepted], verdict="진행 가능", blocking=[])
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                      rejected_units=[rejected_unit.unit_id])
    # the rejected ids must be exactly the extract's
    conditional = _synthesis([accepted], verdict="조건부 진행", blocking=[])
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(conditional, synthesis_input=synthesis_input, extract=extract,
                                      compare=compare, rejected_units=[])
    assembled = assemble_practitioner_verdict(conditional, synthesis_input=synthesis_input, extract=extract,
                                              compare=compare, rejected_units=[rejected_unit.unit_id],
                                              record_rejected_units=True)
    rows = {row.unit_id: row for row in assembled.matrix}
    assert rows[rejected_unit.unit_id].model_dump(mode="json") == {
        "unit_id": rejected_unit.unit_id, "type": None, "fit_status": "unknown", "role_findings": [],
        "rejected_rule_codes": ["constraint_quote_truncated"]}
    assert rows[accepted.unit_id].rejected_rule_codes is None and rows[accepted.unit_id].type == "기능"
    assert [row.unit_id for row in assembled.matrix] == [accepted.unit_id, rejected_unit.unit_id]
    assert [row.model_dump() for row in assembled.rejected_units] == [
        {"unit_id": rejected_unit.unit_id, "rule_codes": ["constraint_quote_truncated"]}]
    payload = assembled.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CardAssembledPractitionerVerdict.model_validate({**payload, "verdict": "진행 가능"})
    with pytest.raises(ValidationError):
        CardAssembledPractitionerVerdict.model_validate({**payload, "rejected_units": []})


# --- 결정 B53: role/synthesis evidence = unit evidence ∪ the unit's own constraint triples ---

def _b53_world():
    """Two 운영 units (operations_risk); each has a constraint quote that differs from its evidence quote."""

    texts = ["장애는 자체 감지 후 4시간 이내 복구하고 결과를 보고한다", "웹 접근성 품질 인증을 매년 갱신한다"]
    frozen = card_input(texts)
    first, second = frozen.units
    extract = CardRequirementExtract.model_validate({"items": [
        extract_item(first, type_="운영", mandatory=None, normalized="장애 복구 체계", constraints=[
            constraint(first, kind="text", value="자체 감지 후 4시간 이내 복구", unit_name=None, operator="lte",
                       quote="자체 감지 후 4시간 이내 복구")]),
        extract_item(second, type_="운영", mandatory=None, normalized="웹 접근성 인증 갱신", constraints=[
            constraint(second, kind="text", value="매년 갱신", unit_name=None, operator="eq", quote="매년 갱신")]),
    ]})
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": unit.unit_id, "fit_status": "unknown", "evidence_ids": [], "reason_codes": ["unmapped"],
         "constraint_results": [{"constraint_index": 0, "status": "unknown", "fact_ids": [], "path_ids": [],
                                 "reason_code": "unmapped"}]}
        for unit in frozen.units
    ]})
    return frozen, extract, compare, build_verdict_role_inputs(extract, compare)


def _triple(unit, quote: str) -> dict:
    return {"source_sha256": unit.source_sha256, "block_key": unit.blocks[0].block_key, "quote": quote}


def test_b53_role_may_cite_its_own_constraint_triple_but_nothing_else() -> None:
    frozen, extract, compare, inputs = _b53_world()
    first, second = frozen.units
    role_input = inputs["operations_risk"]
    output = _role_output(role_input)
    output["unit_findings"][0]["evidence_refs"] = [_triple(first, "자체 감지 후 4시간 이내 복구")]
    output["cautions"] = [{"unit_id": first.unit_id, "text": "복구 기준 확인 필요",
                           "evidence_refs": [_triple(first, "자체 감지 후 4시간 이내 복구")]}]
    output["evidence_refs"] = [_triple(second, "매년 갱신")]
    validate_verdict_role(output, role_input=role_input)  # the T12 8차 shape now passes
    for mutate in (
        # another unit's constraint triple
        lambda o: o["unit_findings"][0].__setitem__("evidence_refs", [_triple(second, "매년 갱신")]),
        lambda o: o["cautions"][0].__setitem__("evidence_refs", [_triple(second, "매년 갱신")]),
        # not verbatim (a substring of the constraint quote, or a paraphrase)
        lambda o: o["unit_findings"][0].__setitem__("evidence_refs", [_triple(first, "4시간 이내 복구")]),
        lambda o: o["unit_findings"][0].__setitem__("evidence_refs", [_triple(first, "자체 감지 후 4시간 내 복구")]),
        # right quote, wrong block
        lambda o: o["unit_findings"][0].__setitem__("evidence_refs", [{
            **_triple(first, "자체 감지 후 4시간 이내 복구"), "block_key": second.blocks[0].block_key}]),
        lambda o: o.__setitem__("evidence_refs", [_triple(first, "임의의 근거")]),
    ):
        changed = deepcopy(output)
        mutate(changed)
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role(changed, role_input=role_input)


def test_b53_synthesis_and_assembly_use_the_same_evidence_set() -> None:
    from app.deep_review.services.card_roles import unit_evidence_keys

    frozen, extract, compare, inputs = _b53_world()
    first, second = frozen.units
    assert unit_evidence_keys(extract.items[0]) == {
        (first.source_sha256, first.blocks[0].block_key, first.blocks[0].text),
        (first.source_sha256, first.blocks[0].block_key, "자체 감지 후 4시간 이내 복구")}
    roles = {}
    for role, value in inputs.items():
        output = _role_output(value)
        if role == "operations_risk":
            output["unit_findings"][0]["evidence_refs"] = [_triple(first, "자체 감지 후 4시간 이내 복구")]
        roles[role] = validate_verdict_role(output, role_input=value)
    synthesis_input = build_synthesis_input(roles)
    caution = {"unit_id": first.unit_id, "text": "복구 기준 확인", "evidence_refs": [_triple(first, "자체 감지 후 4시간 이내 복구")]}
    answer = _synthesis(frozen.units, blocking=[], cautions=[caution])
    validate_practitioner_verdict(answer, synthesis_input=synthesis_input, extract=extract, compare=compare)
    # synthesis may cite only what the roles cited for that unit (the second unit's constraint was not cited)
    uncited = _synthesis(frozen.units, blocking=[], cautions=[
        {"unit_id": second.unit_id, "text": "갱신 주기 확인", "evidence_refs": [_triple(second, "매년 갱신")]}])
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(uncited, synthesis_input=synthesis_input, extract=extract, compare=compare)
    assembled = assemble_practitioner_verdict(answer, synthesis_input=synthesis_input, extract=extract, compare=compare)
    row = next(item for item in assembled.matrix if item.unit_id == first.unit_id)
    cited = [ref.model_dump() for finding in row.role_findings for ref in finding.evidence_refs]
    assert _triple(first, "자체 감지 후 4시간 이내 복구") in cited
    operations = next(item for item in assembled.checklist if item.key == "operations_sla_security")
    refs = [ref.model_dump() for ref in operations.evidence_refs]
    # item evidence first, then the constraint quote a role cited; the uncited one is absent
    assert refs == [_triple(first, first.blocks[0].text), _triple(first, "자체 감지 후 4시간 이내 복구"),
                    _triple(second, second.blocks[0].text)]


# --- 결정 B55 (T20): synthesis contract v2, code blocking ids / "사람 확인" rows, resume lineage ----


def _synthesis_v2(*, verdict: str = "조건부 진행", cautions=None, actions=None) -> dict:
    return {
        "schema_version": "bidops.practitioner-verdict.v2", "verdict": verdict,
        "reason": "상주 인원 요구가 회사 가용 인원을 넘고 확인할 조건이 남아 있다.",
        "cautions": cautions or [], "next_actions": actions or [],
    }


def test_b55_synthesis_contract_v2_has_no_blocking_ids_and_maps_to_card_synthesis_v2() -> None:
    from app.deep_review.contracts import PRACTITIONER_VERDICT_V2_SCHEMA, SCHEMA_FILES
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS

    assert CONTRACT_SCHEMAS["card-synthesis-v2"] == PRACTITIONER_VERDICT_V2_SCHEMA == "practitioner-verdict-v2"
    assert SCHEMA_FILES[PRACTITIONER_VERDICT_V2_SCHEMA] == "bidops.practitioner-verdict.v2.json"
    validate_payload(_synthesis_v2(), PRACTITIONER_VERDICT_V2_SCHEMA)
    for broken in ({**_synthesis_v2(), "blocking_condition_ids": []},  # removed from the wire
                   {**_synthesis_v2(), "schema_version": "bidops.practitioner-verdict.v1"},
                   {key: value for key, value in _synthesis_v2().items() if key != "cautions"},
                   _synthesis_v2(actions=[{"unit_id": "u", "owner": None, "action": "확인", "evidence_refs": [],
                                           "origin": "code"}])):  # the model never writes an origin
        with pytest.raises(SchemaValidationError):
            validate_payload(broken, PRACTITIONER_VERDICT_V2_SCHEMA)


def test_b55_code_computes_blocking_ids_and_the_unchanged_validator_decides() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v2

    frozen, extract, compare = _role_world()
    units = frozen.units
    inputs = build_verdict_role_inputs(extract, compare)
    roles = {role: validate_verdict_role(_role_output(value), role_input=value) for role, value in inputs.items()}
    synthesis_input = build_synthesis_input(roles)
    answer = _synthesis_v2()
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    v1 = synthesis_v1_from_v2(answer, extract=extract, compare=compare)
    # blocking = the mandatory gap units (units[0]: mandatory, gap); units[2] is mandatory but unknown
    assert v1["blocking_condition_ids"] == [units[0].unit_id]
    assert {key: v1[key] for key in ("verdict", "reason", "cautions", "next_actions")} == {
        key: answer[key] for key in ("verdict", "reason", "cautions", "next_actions")}
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before  # never corrected in place
    verdict = validate_practitioner_verdict(v1, synthesis_input=synthesis_input, extract=extract, compare=compare)
    assert verdict.blocking_condition_ids == [units[0].unit_id]
    # everything the validator rejected before is still rejected (no auto-correction)
    action = {"unit_id": units[0].unit_id, "owner": None, "action": "상주 인력 보강 검토",
              "evidence_refs": [evidence(units[0])]}
    for payload in (
        _synthesis_v2(verdict="진행 가능"),  # mandatory gap and unresolved units
        _synthesis_v2(actions=[{**action, "unit_id": "card:unknown"}]),  # not a role unit (not schema-expressible)
        _synthesis_v2(actions=[{**action, "unit_id": "missing_section:budget"}]),  # code-only target
        _synthesis_v2(actions=[{**action, "owner": "김담당"}]),  # invented owner
        _synthesis_v2(cautions=[{"unit_id": units[1].unit_id, "text": "확인 필요",
                                 "evidence_refs": [evidence(units[0])]}]),
    ):
        with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
            validate_practitioner_verdict(synthesis_v1_from_v2(payload, extract=extract, compare=compare),
                                          synthesis_input=synthesis_input, extract=extract, compare=compare)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        synthesis_v1_from_v2({**answer, "blocking_condition_ids": []}, extract=extract, compare=compare)
    # no mandatory gap → no blocking id (the met / unknown compare rows never block)
    met_compare = CardRequirementCompare.model_validate({**compare.model_dump(mode="json"), "items": [
        {**compare.items[0].model_dump(mode="json"), "fit_status": "unknown", "reason_codes": ["unmapped"],
         "constraint_results": [{"constraint_index": 0, "status": "unknown", "fact_ids": [], "path_ids": [],
                                 "reason_code": "unmapped"}]},
        *[row.model_dump(mode="json") for row in compare.items[1:]]]})
    assert synthesis_v1_from_v2(answer, extract=extract, compare=met_compare)["blocking_condition_ids"] == []


def test_b55_assembly_appends_code_person_check_rows_for_missing_sections_and_rejected_units() -> None:
    from app.deep_review.services.card_roles import (
        MISSING_SECTION_ACTION, REJECTED_UNIT_ACTION, synthesis_v1_from_v2,
    )

    frozen, extract, compare, _inputs, synthesis_input = _b51_world()
    accepted, rejected_unit = frozen.units
    action = {"unit_id": accepted.unit_id, "owner": None, "action": "CMS 범위 확인",
              "evidence_refs": [evidence(accepted)]}
    v1 = synthesis_v1_from_v2(_synthesis_v2(actions=[action]), extract=extract, compare=compare)
    assert v1["blocking_condition_ids"] == []
    verdict = validate_practitioner_verdict(v1, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                            missing_sections=["budget"], rejected_units=[rejected_unit.unit_id])
    assembled = assemble_practitioner_verdict(
        verdict, synthesis_input=synthesis_input, extract=extract, compare=compare, missing_sections=["budget"],
        rejected_units=[rejected_unit.unit_id], record_rejected_units=True, code_actions=True)
    rows = [row.model_dump(mode="json") for row in assembled.next_actions]
    assert rows == [
        {**action, "origin": "model"},
        {"unit_id": "missing_section:budget", "owner": None,
         "action": MISSING_SECTION_ACTION.format(name="사업예산"), "evidence_refs": [], "origin": "code"},
        {"unit_id": rejected_unit.unit_id, "owner": None, "action": REJECTED_UNIT_ACTION, "evidence_refs": [],
         "origin": "code"},
    ]
    assert assembled.verdict == "조건부 진행" and assembled.blocking_condition_ids == []
    payload = assembled.model_dump(mode="json")
    # the stored row's code rows must be exactly one per missing section and rejected unit, after the model rows
    for broken in (
        rows[:2],  # a rejected unit without its row
        [rows[0], rows[2], rows[1]],  # wrong order
        [rows[1], rows[0], rows[2]],  # code before model
        [{**rows[0], "origin": None}, *rows[1:]],  # mixed origin
        [rows[0], {**rows[1], "owner": "김담당"}, rows[2]],  # a code row never has an owner
        [rows[0], rows[1], {**rows[2], "evidence_refs": [evidence(rejected_unit)]}],  # nor evidence
        [{**rows[0], "unit_id": "missing_section:budget"}, *rows[1:]],  # model row naming a code target
    ):
        with pytest.raises(ValidationError):
            CardAssembledPractitionerVerdict.model_validate({**payload, "next_actions": broken})
    # rows before policy v9 (no origin) keep their exact stored shape: no origin key at all
    legacy = assemble_practitioner_verdict(
        _synthesis([accepted], blocking=[], actions=[action]), synthesis_input=synthesis_input, extract=extract,
        compare=compare, rejected_units=[rejected_unit.unit_id], record_rejected_units=True)
    assert [row.model_dump(mode="json") for row in legacy.next_actions] == [action]
    assert "origin" not in json.dumps(legacy.model_dump(mode="json"), ensure_ascii=False)


def _resume_policy(identity: str = "analysis-policy-luna-rl-v8") -> dict:
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V8, RL_LUNA_POLICY_FILE_V9

    path = RL_LUNA_POLICY_FILE_V9 if identity.endswith("v9") else RL_LUNA_POLICY_FILE_V8
    return {**json.loads(path.read_bytes()), "policy_sha256": "e" * 64 if identity.endswith("v9") else "f" * 64}


def test_b55_resume_lineage_accepts_identical_content_and_rejects_any_mismatch() -> None:
    from app.deep_review.services.card_analysis import resume_content_sha256, resume_lineage_valid

    frozen = card_input(["상주 인원 3명 이상"])
    source = {"execution_nonce": str(uuid4()), "target_review_id": None, "policy_version_id": str(uuid4()),
              "policy_sha256": "f" * 64, "bundle_id": str(uuid4()), "company_id": str(uuid4()),
              "graph_sha256": "b" * 64, "profile_sha256": "c" * 64, "document_version_ids": [str(uuid4())],
              "generation_config_sha256": "d" * 64, "card_analysis": frozen.model_dump(mode="json")}
    new = {**source, "execution_nonce": str(uuid4()), "target_review_id": str(uuid4()),
           "policy_version_id": str(uuid4()), "policy_sha256": "e" * 64}
    v8, v9 = _resume_policy(), _resume_policy("analysis-policy-luna-rl-v9")
    assert resume_content_sha256(source) == resume_content_sha256(new)
    assert resume_lineage_valid(source, v8, new, v9)  # v8 -> v9: only synthesis differs
    assert resume_lineage_valid(source, v9, new, v9)  # same policy
    for key, value in (("bundle_id", str(uuid4())), ("company_id", str(uuid4())), ("graph_sha256", "0" * 64),
                       ("profile_sha256", "0" * 64), ("document_version_ids", []),
                       ("generation_config_sha256", "0" * 64),
                       ("card_analysis", card_input(["상주 인원 4명 이상"]).model_dump(mode="json"))):
        assert not resume_lineage_valid(source, v8, {**new, key: value}, v9), key
    mutations = (
        lambda p: p["stages"][0].__setitem__("instruction", p["stages"][0]["instruction"] + " "),  # extract
        lambda p: p["stages"][2].__setitem__("instruction", "다른 역할 지시"),  # a role
        lambda p: p.__setitem__("stage_schema", "bidops.requirement-extract.v1"),
        lambda p: p["prompt_output_contract"].__setitem__("input_rule", "다른 규칙"),
        lambda p: p["card"].__setitem__("batch_size", 4),  # packing
        lambda p: p.__setitem__("pipeline_version", "narrative-v2"),
        lambda p: p.__setitem__("policy_identity", "analysis-policy-luna-rl-v6"),  # isolation differs
        lambda p: p.__setitem__("stages", p["stages"][:4]),
    )
    for index, mutate in enumerate(mutations):
        changed = deepcopy(v9)
        mutate(changed)
        assert not resume_lineage_valid(source, v8, new, changed), index
    # the synthesis instruction and report_schema are the only policy parts allowed to differ
    synthesis_only = deepcopy(v9)
    synthesis_only["stages"][4]["instruction"] = "다른 종합 지시"
    assert resume_lineage_valid(source, v8, new, synthesis_only)
    assert not resume_lineage_valid(source, v8, {**new, "card_analysis": None}, v9)


# --- 결정 C15 (RL-05 STEP-006): selector card-sections-v4 splits an oversized segment unit ---
#
# RL-05 manual verdicts on policy v9 (card-sections-v3, batch_max_chars 12000) refused 3 of 10
# real pre-specs with input_budget_exceeded before any call: every card unit was <= 5,304
# characters but one segment unit was 12,061 / 29,949 / 12,963.  v4 splits such a segment at
# block boundaries (original order, greedy, nothing cut or dropped); one block above the limit
# is still refused.

OVERVIEW_HEADING = "제1장 사업개요"
#: Canonical card-sections-v4 selector policy SHA (결정 C15).
V4_SELECTOR_SHA256 = "4ff2c74b0a010c5368d7fa1c59ce3331b48ec50d30a6c49951ebd5d6f428d7e0"


def _v4():
    from app.deep_review.services import card_units

    return card_units


def _long_segment_source(sizes: list[int], *, pages: list[int] | None = None) -> dict:
    """``제1장 사업개요`` + body blocks ``b-<i>`` of the given sizes (one segment), then a short budget segment."""

    pages = pages or [1] * len(sizes)
    blocks = [
        _block("h-overview", OVERVIEW_HEADING),
        *(_block(f"b-{index}", "가" * size, page=page) for index, (size, page) in enumerate(zip(sizes, pages))),
        _block("h-budget", "제2장 사업예산", page=pages[-1]),
        _block("b-budget", "사업비는 별도로 정한다", page=pages[-1]),
    ]
    positions = {block["block_key"]: index for index, block in enumerate(blocks)}
    segments = [["h-overview", *(f"b-{index}" for index in range(len(sizes)))], ["h-budget", "b-budget"]]
    return {
        "source_sha256": SOURCE_SHA, "document_version_id": uuid4(), "structure_id": uuid4(),
        "manifest_id": uuid4(), "blocks": blocks, "cards": [],
        "segments": [
            {"segment_id": uuid4(), "ordinal": ordinal, "source_block_keys": keys,
             "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
             "page_range": {"first": 1, "last": max(pages)}, "mapping_status": "mapped"}
            for ordinal, keys in enumerate(segments, start=1)
        ],
    }


def _segment_unit_id(source: dict, index: int) -> str:
    return f"segment:{source['source_sha256']}:{source['segments'][index]['segment_id']}"


def test_c15_v4_splits_an_oversized_segment_at_block_boundaries_in_source_order() -> None:
    from app.deep_review.services.card_units import unit_characters

    card_units = _v4()
    source = _long_segment_source([5000] * 5, pages=[1, 1, 2, 2, 3])
    selection = select_analysis_units([source], selector_version=card_units.SELECTOR_VERSION_V4)
    # deterministic: the same input gives the same selection, ids included
    again = select_analysis_units([deepcopy(source)], selector_version=card_units.SELECTOR_VERSION_V4)
    assert again.model_dump(mode="json") == selection.model_dump(mode="json")

    parent = _segment_unit_id(source, 0)
    parts = [unit for unit in selection.units if unit.unit_id.startswith(parent)]
    assert [unit.unit_id for unit in parts] == [f"{parent}#p1", f"{parent}#p2", f"{parent}#p3"]
    assert _unit_keys(selection)[:3] == [["h-overview", "b-0", "b-1"], ["b-2", "b-3"], ["b-4"]]
    assert [unit_characters(unit) for unit in parts] == [len(OVERVIEW_HEADING) + 10000, 10000, 5000]
    assert all(unit_characters(unit) <= 12000 for unit in selection.units)
    # nothing cut, dropped or reordered: the parts are the segment's blocks in order, texts unchanged
    assert [block.block_key for unit in parts for block in unit.blocks] == source["segments"][0]["source_block_keys"]
    texts = {block["block_key"]: block["text"] for block in source["blocks"]}
    assert all(block.text == texts[block.block_key] for unit in parts for block in unit.blocks)
    # every part keeps the parent's attributes
    for unit in parts:
        assert (unit.kind, unit.ordinal, unit.normalized_id, unit.section_kinds, unit.mapping_status) == (
            "segment", 1, None, ["overview"], "mapped")
        assert unit.page_range is not None and unit.page_range.model_dump() == {"first": 1, "last": 3}
        assert (unit.source_sha256, unit.document_version_id, unit.structure_id, unit.manifest_id) == (
            SOURCE_SHA, source["document_version_id"], source["structure_id"], source["manifest_id"])
    # an unsplit segment keeps the v3 id form
    assert selection.units[3].unit_id == _segment_unit_id(source, 1)
    assert selection.selector.version == card_units.SELECTOR_VERSION_V4 == "card-sections-v4"
    assert selection.selector.sha256 == card_units.SELECTOR_SHA256_V4
    assert [row.block_key for row in selection.selector.selected_blocks] == [
        block["block_key"] for block in source["blocks"]]
    assert selection.missing_sections == ["schedule", "eligibility", "evaluation", "contract"]
    # batches pack the parts greedily like any unit; the call budget is B + 4
    budget_characters = len("제2장 사업예산") + len("사업비는 별도로 정한다")
    assert [(batch.unit_ids, batch.source_characters) for batch in selection.batches] == [
        ([f"{parent}#p1"], len(OVERVIEW_HEADING) + 10000),
        ([f"{parent}#p2"], 10000),
        ([f"{parent}#p3", _segment_unit_id(source, 1)], 5000 + budget_characters),
    ]
    assert analysis_call_budget(len(selection.batches)).model_dump() == {
        "batch_count": 3, "normal_calls": 7, "maximum_calls": 14,
    }
    frozen = freeze_card_analysis_input(selection, company_binding=_binding())
    validate_payload(frozen.model_dump(mode="json"), CARD_ANALYSIS_INPUT_SCHEMA)
    # v3 on the same input is still refused before any call (its behaviour is unchanged)
    with pytest.raises(CardAnalysisSelectionError, match="input_budget_exceeded"):
        select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)


def test_c15_v4_keeps_units_under_the_limit_exactly_as_v3() -> None:
    card_units = _v4()
    for source in (_source(), _polytech_source_with_toc(), _long_segment_source([5000, 6000]),
                   _long_segment_source([12000 - len(OVERVIEW_HEADING)])):  # exactly the limit
        v3 = select_analysis_units([source], selector_version=SELECTOR_VERSION_V3)
        v4 = select_analysis_units([source], selector_version=card_units.SELECTOR_VERSION_V4)
        identity = {"selector": {"version", "sha256"}}
        assert v4.model_dump(mode="json", exclude=identity) == v3.model_dump(mode="json", exclude=identity)
        assert (v4.selector.version, v4.selector.sha256) == (
            card_units.SELECTOR_VERSION_V4, card_units.SELECTOR_SHA256_V4)
        assert not any("#" in unit.unit_id for unit in v4.units)


def test_c15_v4_single_block_over_the_limit_is_still_input_budget_exceeded() -> None:
    card_units = _v4()
    for sizes in ([12001], [3000, 12001, 3000]):
        for version in (SELECTOR_VERSION_V3, card_units.SELECTOR_VERSION_V4):
            with pytest.raises(CardAnalysisSelectionError, match="input_budget_exceeded"):
                select_analysis_units([_long_segment_source(sizes)], selector_version=version)
    # a block of exactly the limit becomes its own part
    exact = _long_segment_source([12000])
    selection = select_analysis_units([exact], selector_version=card_units.SELECTOR_VERSION_V4)
    parent = _segment_unit_id(exact, 0)
    assert [unit.unit_id for unit in selection.units[:2]] == [f"{parent}#p1", f"{parent}#p2"]
    assert _unit_keys(selection)[:2] == [["h-overview"], ["b-0"]]


def test_c15_v4_split_follows_the_policy_batch_max_chars() -> None:
    from app.deep_review.services.card_units import unit_characters

    card_units = _v4()
    source = _long_segment_source([3000] * 4)  # 12,008 characters
    default = select_analysis_units([source], selector_version=card_units.SELECTOR_VERSION_V4)
    assert _unit_keys(default)[:2] == [["h-overview", "b-0", "b-1", "b-2"], ["b-3"]]
    tight = select_analysis_units([source], policy={"batch_max_chars": 6000},
                                  selector_version=card_units.SELECTOR_VERSION_V4)
    parent = _segment_unit_id(source, 0)
    assert [unit.unit_id for unit in tight.units[:3]] == [f"{parent}#p1", f"{parent}#p2", f"{parent}#p3"]
    assert _unit_keys(tight)[:3] == [["h-overview", "b-0"], ["b-1", "b-2"], ["b-3"]]
    assert all(unit_characters(unit) <= 6000 for unit in tight.units)
    assert all(batch.source_characters <= 6000 for batch in tight.batches)
    # v3 with the same tight policy refuses the segment
    with pytest.raises(CardAnalysisSelectionError, match="input_budget_exceeded"):
        select_analysis_units([source], policy={"batch_max_chars": 6000}, selector_version=SELECTOR_VERSION_V3)


def _renamed(payload: dict, renames: dict[str, str]) -> dict:
    changed = deepcopy(payload)
    for unit in changed["units"]:
        unit["unit_id"] = renames.get(unit["unit_id"], unit["unit_id"])
    for batch in changed["batches"]:
        batch["unit_ids"] = [renames.get(unit_id, unit_id) for unit_id in batch["unit_ids"]]
    return changed


def test_c15_part_ids_are_accepted_only_as_complete_v4_parts() -> None:
    from app.deep_review.schemas.card_analysis import CardUnitSelection

    card_units = _v4()
    source = _long_segment_source([5000] * 5)
    payload = select_analysis_units([source], selector_version=card_units.SELECTOR_VERSION_V4).model_dump(mode="json")
    parent = _segment_unit_id(source, 0)
    CardUnitSelection.model_validate(payload)
    frozen = freeze_card_analysis_input(payload, company_binding=_binding()).model_dump(mode="json")
    CardAnalysisInput.model_validate(frozen)
    # part ids exist only under card-sections-v4
    for version, sha in ((SELECTOR_VERSION, SELECTOR_SHA256), (SELECTOR_VERSION_V2, SELECTOR_SHA256_V2),
                         (SELECTOR_VERSION_V3, SELECTOR_SHA256_V3)):
        selector = {**payload["selector"], "version": version, "sha256": sha}
        with pytest.raises(ValidationError):
            CardUnitSelection.model_validate({**payload, "selector": selector})
        with pytest.raises(ValidationError):
            CardAnalysisInput.model_validate({**frozen, "selector": selector})
        with pytest.raises(CardAnalysisSelectionError, match="card_source_selection_incomplete"):
            freeze_card_analysis_input({**payload, "selector": selector}, company_binding=_binding())
    # the suffix is exactly "#p<n>" with n >= 1 and no leading zero
    unit = payload["units"][0]
    for suffix in ("#p0", "#p01", "#q1", "#p", "#p1#p2", "#P1", "p1"):
        with pytest.raises(ValidationError):
            CardAnalysisUnit.model_validate({**unit, "unit_id": parent + suffix})
    # parts are p1..pk (k >= 2) in unit order with the parent's attributes, never beside the unsplit id
    other = f"segment:{SOURCE_SHA}:{uuid4()}"
    for renames in (
        {f"{parent}#p3": f"{parent}#p4"},  # gap
        {f"{parent}#p1": f"{parent}#p2", f"{parent}#p2": f"{parent}#p1"},  # order
        {f"{parent}#p3": parent},  # unsplit id beside its parts
        {f"{parent}#p2": f"{other}#p1", f"{parent}#p3": f"{other}#p2"},  # a lone p1 left behind
    ):
        with pytest.raises(ValidationError):
            CardUnitSelection.model_validate(_renamed(payload, renames))
    changed = deepcopy(payload)
    changed["units"][1]["ordinal"] = 7
    with pytest.raises(ValidationError):
        CardUnitSelection.model_validate(changed)


def test_c15_selector_v4_sha_is_pinned_and_earlier_selectors_are_unchanged() -> None:
    card_units = _v4()
    assert card_units.SELECTOR_SHA256_BY_VERSION == {
        "card-sections-v1": "ac18ffd120333e80b2dccbde0129969d6202e05b9aa1493119a927400ffa67f1",
        "card-sections-v2": "d3ed2e2e6f573b1c5a7830ace9a02e363a9a0ae4929643c871b6d6a309b94617",
        "card-sections-v3": "8c4332763fb89a47ebd67a3c9f59575406fcef0a2a878ed66dd3309a39654d38",
        "card-sections-v4": card_units.SELECTOR_SHA256_V4,
    }
    assert card_units.SELECTOR_SHA256_V4 == V4_SELECTOR_SHA256
    payload = freeze_card_analysis_input(
        select_analysis_units([_source()], selector_version=card_units.SELECTOR_VERSION_V4),
        company_binding=_binding(),
    ).model_dump(mode="json")
    validate_payload(payload, CARD_ANALYSIS_INPUT_SCHEMA)
    with pytest.raises(SchemaValidationError):
        validate_payload({**payload, "selector": {**payload["selector"], "version": "card-sections-v5"}},
                         CARD_ANALYSIS_INPUT_SCHEMA)


def test_c15_requirement_units_of_parts_take_each_part_first_stored_block_page() -> None:
    card_units = _v4()
    source = _long_segment_source([5000] * 5, pages=[1, 1, 2, 2, 3])
    frozen = freeze_card_analysis_input(
        select_analysis_units([source], selector_version=card_units.SELECTOR_VERSION_V4), company_binding=_binding())
    bundle = {"documents": [{"document_version_id": str(source["document_version_id"]), "ordinal": 0}]}
    rows = card_requirement_units(frozen, bundle, {str(source["structure_id"]): {"blocks": source["blocks"]}})
    parent = _segment_unit_id(source, 0)
    assert [row["requirement_id"] for row in rows] == [unit.unit_id for unit in frozen.units]
    assert [(row["requirement_id"], row["page"]) for row in rows[:3]] == [
        (f"{parent}#p1", 1), (f"{parent}#p2", 2), (f"{parent}#p3", 3)]
    assert rows[1]["text"] == "\n".join(["가" * 5000] * 2)
    assert all(row["document_requirement_ids"] == [] for row in rows)


# --- 결정 C16 (RL-05 STEP-007): role output contract v2 (short evidence ids), role item
# isolation and extract missing-unit isolation (policy v10) ------------------------------

C16_NAMES = ("보안", "백업", "장애", "접근성", "모니터링", "교육", "인수인계", "품질")


def _c16_world(count: int = 4, *, fits: dict[int, str] | None = None, mandatory=None):
    """``count`` 운영 units (operations_risk only), each with one evidence and one distinct constraint triple."""

    fits = fits or {}
    texts = [f"{name} 운영 계획을 매월 보고한다" for name in C16_NAMES[:count]]
    frozen = card_input(texts)
    extract = CardRequirementExtract.model_validate({"items": [
        extract_item(unit, type_="운영", mandatory=mandatory, normalized=f"{name} 운영 계획 보고", constraints=[
            constraint(unit, kind="text", value=f"{name} 운영 계획", unit_name=None, operator="eq",
                       quote=f"{name} 운영 계획")])
        for unit, name in zip(frozen.units, C16_NAMES)
    ]})
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": unit.unit_id, "fit_status": fits.get(index, "unknown"), "evidence_ids": [],
         "reason_codes": ["confirmed_match" if fits.get(index) == "met" else "unmapped"],
         "constraint_results": [{"constraint_index": 0, "status": fits.get(index, "unknown"), "fact_ids": [],
                                 "path_ids": [],
                                 "reason_code": "confirmed_match" if fits.get(index) == "met" else "unmapped"}]}
        for index, unit in enumerate(frozen.units)
    ]})
    return frozen, extract, compare, build_verdict_role_inputs(extract, compare)


def _ids_by_unit(role_input) -> dict[str, list[str]]:
    from app.deep_review.services.company_analysis_input import card_role_evidence_index

    result: dict[str, list[str]] = {}
    for row in card_role_evidence_index(role_input.extract.model_dump(mode="json")):
        result.setdefault(row["unit_id"], []).append(row["evidence_id"])
    return result


def _role_v2_output(role_input, assessments: dict[str, str] | None = None) -> dict:
    """A contract-following v2 answer: compare fits, every finding cites its unit's ids."""

    assessments = assessments or {}
    fits = {row.unit_id: row.fit_status for row in role_input.compare.items}
    ids = _ids_by_unit(role_input)
    return {
        "schema_version": "bidops.verdict-role.v2", "role": role_input.role,
        "unit_findings": [
            {"unit_id": row.unit_id, "assessment": assessments.get(row.unit_id, fits[row.unit_id]),
             "reason": "결정적 대조 결과를 그대로 따른다", "evidence_ids": list(ids.get(row.unit_id, []))}
            for row in role_input.extract.items
        ],
        "cautions": [],
    }


def test_c16_role_contract_v2_is_registered_and_carries_ids_only() -> None:
    from app.deep_review.contracts import SCHEMA_FILES, VERDICT_ROLE_V2_SCHEMA
    from app.deep_review.services.card_analysis import ROLE_CONTRACT_V2, ROLE_CONTRACT_V2_POLICY_IDENTITIES
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS

    assert ROLE_CONTRACT_V2 == "card-role-v2"
    assert CONTRACT_SCHEMAS["card-role-v2"] == VERDICT_ROLE_V2_SCHEMA == "verdict-role-v2"
    assert SCHEMA_FILES[VERDICT_ROLE_V2_SCHEMA] == "bidops.verdict-role.v2.json"
    assert ROLE_CONTRACT_V2_POLICY_IDENTITIES == frozenset({"analysis-policy-luna-rl-v10"})
    _frozen, _extract, _compare, inputs = _c16_world()
    answer = _role_v2_output(inputs["operations_risk"])
    validate_payload(answer, VERDICT_ROLE_V2_SCHEMA)
    finding = answer["unit_findings"][0]
    for broken in (
        {**answer, "schema_version": "bidops.verdict-role.v1"},
        {**answer, "evidence_refs": []},  # no triple and no global list on the v2 wire
        {**answer, "evidence_ids": ["E1"]},
        {**answer, "unit_findings": [{**finding, "evidence_refs": [evidence(_frozen.units[0])]}]},
        {**answer, "unit_findings": [{**finding, "evidence_ids": ["e1"]}]},  # malformed id
        {**answer, "unit_findings": [{**finding, "evidence_ids": ["E01"]}]},
        {**answer, "cautions": [{"unit_id": finding["unit_id"], "text": "확인", "evidence_refs": []}]},
    ):
        with pytest.raises(SchemaValidationError):
            validate_payload(broken, VERDICT_ROLE_V2_SCHEMA)


def test_c16_evidence_ids_are_deterministic_and_map_back_to_the_frozen_triples() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2
    from app.deep_review.services.company_analysis_input import card_role_evidence_catalog, card_role_evidence_index

    frozen, extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    payload_extract = role_input.extract.model_dump(mode="json")
    index = card_role_evidence_index(payload_extract)
    u0, u1 = frozen.units[:2]
    # unit order, then each unit's evidence before its constraint triples; E1..En across the role payload
    assert index[:4] == [
        {"evidence_id": "E1", "unit_id": u0.unit_id, "source_sha256": SOURCE_SHA,
         "block_key": u0.blocks[0].block_key, "quote": u0.blocks[0].text},
        {"evidence_id": "E2", "unit_id": u0.unit_id, "source_sha256": SOURCE_SHA,
         "block_key": u0.blocks[0].block_key, "quote": "보안 운영 계획"},
        {"evidence_id": "E3", "unit_id": u1.unit_id, "source_sha256": SOURCE_SHA,
         "block_key": u1.blocks[0].block_key, "quote": u1.blocks[0].text},
        {"evidence_id": "E4", "unit_id": u1.unit_id, "source_sha256": SOURCE_SHA,
         "block_key": u1.blocks[0].block_key, "quote": "백업 운영 계획"},
    ]
    assert [row["evidence_id"] for row in index] == [f"E{n}" for n in range(1, 9)]
    assert index == card_role_evidence_index(deepcopy(payload_extract))  # deterministic
    # the sent catalog carries no source hash (the model cites ids only)
    catalog = card_role_evidence_catalog(payload_extract)
    assert catalog[0] == {"unit_id": u0.unit_id, "evidence": [
        {"evidence_id": "E1", "block_key": u0.blocks[0].block_key, "quote": u0.blocks[0].text},
        {"evidence_id": "E2", "block_key": u0.blocks[0].block_key, "quote": "보안 운영 계획"}]}
    assert [row["unit_id"] for row in catalog] == [row.unit_id for row in role_input.extract.items]
    # a constraint triple equal to an evidence triple keeps one id
    same = CardRequirementExtract.model_validate({"items": [extract_item(u0, type_="운영", constraints=[
        constraint(u0, kind="text", value=u0.blocks[0].text, unit_name=None, operator="eq", quote=u0.blocks[0].text)])]})
    assert [row["evidence_id"] for row in card_role_evidence_index(same.model_dump(mode="json"))] == ["E1"]

    answer = _role_v2_output(role_input)
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    result = validate_verdict_role_v2(answer, role_input=role_input)
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before  # never changed in place
    # the stored result is the v1 shape every consumer reads, plus an (empty) isolation list
    triples = {(row["source_sha256"], row["block_key"], row["quote"]) for row in index[:2]}
    assert result.schema_version == "bidops.verdict-role.v1" and result.evidence_refs == []
    assert {(ref.source_sha256, ref.block_key, ref.quote) for ref in result.unit_findings[0].evidence_refs} == triples
    assert result.isolated_items == []
    stored = result.model_dump(mode="json")
    assert set(stored) == {"schema_version", "role", "unit_findings", "cautions", "evidence_refs", "isolated_items"}
    v1_shape = {key: value for key, value in stored.items() if key != "isolated_items"}
    assert validate_verdict_role(v1_shape, role_input=role_input).model_dump(mode="json") == v1_shape
    # v1 results keep their exact stored shape (no isolation key)
    v1 = validate_verdict_role(_role_output(role_input), role_input=role_input)
    assert "isolated_items" not in v1.model_dump(mode="json")
    mapped = result.model_copy(update={"isolated_items": None}).model_dump(mode="json")
    assert [row["evidence_refs"][0] for row in mapped["unit_findings"]] == [
        row["evidence_refs"][0] for row in v1.model_dump(mode="json")["unit_findings"]]


@pytest.mark.parametrize(("bad_id", "code"), [
    ("E99", "role_evidence_unknown"),
    ("E3", "role_evidence_foreign_unit"),  # the second unit's evidence
])
def test_c16_wrong_or_foreign_id_isolates_only_that_finding(bad_id, code) -> None:
    from app.deep_review.services.card_roles import ROLE_ISOLATED_REASON, validate_verdict_role_v2

    frozen, _extract, _compare, inputs = _c16_world(fits={0: "met"})
    role_input = inputs["operations_risk"]
    answer = _role_v2_output(role_input)
    assert answer["unit_findings"][0]["assessment"] == "met"
    answer["unit_findings"][0]["evidence_ids"] = ["E1", bad_id]
    result = validate_verdict_role_v2(answer, role_input=role_input)
    isolated = result.unit_findings[0]
    # kept, unknown, no evidence, a fixed BidOps notice instead of the unverified reason (no new claim)
    assert isolated.model_dump(mode="json") == {"unit_id": frozen.units[0].unit_id, "assessment": "unknown",
                                                "reason": ROLE_ISOLATED_REASON, "evidence_refs": []}
    assert [row.model_dump(mode="json") for row in result.isolated_items] == [
        {"kind": "finding", "unit_id": frozen.units[0].unit_id, "rule_codes": [code]}]
    # every other finding is the model's own, mapped
    assert [row.assessment for row in result.unit_findings[1:]] == ["unknown"] * 3
    assert all(len(row.evidence_refs) == 2 for row in result.unit_findings[1:])
    assert "E99" not in json.dumps(result.model_dump(mode="json"))
    both = _role_v2_output(role_input)
    both["unit_findings"][0]["evidence_ids"] = ["E99", "E3", "E99"]
    assert result.isolated_items[0].rule_codes == [code]
    assert validate_verdict_role_v2(both, role_input=role_input).isolated_items[0].rule_codes == [
        "role_evidence_unknown", "role_evidence_foreign_unit"]


def test_c16_invalid_caution_is_dropped_and_recorded() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2

    frozen, _extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    u0, u1 = frozen.units[:2]
    answer = _role_v2_output(role_input)
    answer["cautions"] = [
        {"unit_id": u0.unit_id, "text": "보안 계획 확인", "evidence_ids": ["E2"]},
        {"unit_id": u1.unit_id, "text": "백업 계획 확인", "evidence_ids": ["E1"]},   # another unit's id
        {"unit_id": u1.unit_id, "text": "백업 주기 확인", "evidence_ids": ["E40"]},  # unknown id
    ]
    result = validate_verdict_role_v2(answer, role_input=role_input)
    assert [row.model_dump(mode="json") for row in result.cautions] == [{
        "unit_id": u0.unit_id, "text": "보안 계획 확인",
        "evidence_refs": [{"source_sha256": SOURCE_SHA, "block_key": u0.blocks[0].block_key, "quote": "보안 운영 계획"}]}]
    assert [row.model_dump(mode="json") for row in result.isolated_items] == [
        {"kind": "caution", "unit_id": u1.unit_id, "rule_codes": ["role_evidence_foreign_unit"]},
        {"kind": "caution", "unit_id": u1.unit_id, "rule_codes": ["role_evidence_unknown"]}]
    assert all(row.reason != "" and row.evidence_refs for row in result.unit_findings)  # findings untouched
    assert "백업 주기 확인" not in json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    # 결정 C19 changed one C16 rule: a caution naming a unit outside the role is no longer
    # fatal but isolated (``role_caution_foreign_unit``) -- see the C19 tests below.


@pytest.mark.parametrize(("units", "isolated", "fails"), [(4, 1, False), (4, 2, True), (8, 2, False), (8, 3, True)])
def test_c16_role_isolation_above_a_quarter_of_the_role_units_fails(units, isolated, fails) -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2

    _frozen, _extract, _compare, inputs = _c16_world(units)
    role_input = inputs["operations_risk"]
    answer = _role_v2_output(role_input)
    for index in range(isolated):
        answer["unit_findings"][index]["evidence_ids"] = ["E999"]
    # invalid cautions never count toward the limit
    answer["cautions"] = [{"unit_id": row.unit_id, "text": "확인", "evidence_ids": ["E999"]}
                          for row in role_input.extract.items]
    if fails:
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role_v2(answer, role_input=role_input)
    else:
        result = validate_verdict_role_v2(answer, role_input=role_input)
        assert [row.kind for row in result.isolated_items].count("finding") == isolated
        assert [row.kind for row in result.isolated_items].count("caution") == units


def test_c16_structural_role_violations_stay_fatal() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2

    _frozen, _extract, _compare, inputs = _c16_world(8, fits={0: "met", 1: "gap"})
    role_input = inputs["operations_risk"]
    valid = _role_v2_output(role_input)
    validate_verdict_role_v2(valid, role_input=role_input)
    cases = {
        "order": lambda o: o["unit_findings"].reverse(),
        "coverage": lambda o: o["unit_findings"].pop(),
        "duplicate": lambda o: o["unit_findings"].append(deepcopy(o["unit_findings"][0])),
        "role_name": lambda o: o.__setitem__("role", "technical_fit"),
        # assessment beyond the compare is fatal even when the finding would be isolated anyway
        "unknown_to_met": lambda o: o["unit_findings"][2].update(assessment="met", evidence_ids=["E999"]),
        "gap_to_met": lambda o: o["unit_findings"][1].update(assessment="met"),
        "met_to_gap": lambda o: o["unit_findings"][0].update(assessment="gap"),
        "v1_answer": lambda o: o.update(_role_output(role_input)),
        "extra_key": lambda o: o.update(confidence=0.9),
    }
    for name, mutate in cases.items():
        changed = deepcopy(valid)
        mutate(changed)
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role_v2(changed, role_input=role_input)
        assert name  # for the failure message
    # the v2 validator never accepts a role input the deterministic builder would not produce
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role_v2(valid, role_input=inputs["technical_fit"])


def test_c16_v1_role_validation_is_unchanged_and_still_fatal_on_a_shortened_quote() -> None:
    _frozen, _extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    output = _role_output(role_input)
    validate_verdict_role(output, role_input=role_input)
    unit = _frozen.units[0]
    for mutate in (
        lambda o: o["unit_findings"][0]["evidence_refs"][0].update(quote="보안 운영 계획을"),   # shortened
        lambda o: o["unit_findings"][0]["evidence_refs"][0].update(source_sha256="b" * 64),  # miscopied sha
        lambda o: o["unit_findings"][0].__setitem__("evidence_refs", [evidence(_frozen.units[1])]),  # other unit
        lambda o: o.__setitem__("cautions", [{"unit_id": unit.unit_id, "text": "확인",
                                             "evidence_refs": [evidence(unit, "보안 운영")]}]),
    ):
        changed = deepcopy(output)
        mutate(changed)
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role(changed, role_input=role_input)
    # a v2 answer is not a v1 answer
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role(_role_v2_output(role_input), role_input=role_input)


def test_c16_role_isolation_dto_rules() -> None:
    from app.deep_review.schemas.card_analysis import CardRoleIsolation, CardVerdictRoleResult
    from app.deep_review.services.card_roles import ROLE_ISOLATED_REASON, validate_verdict_role_v2

    frozen, _extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    answer = _role_v2_output(role_input)
    answer["unit_findings"][0]["evidence_ids"] = ["E99"]
    stored = validate_verdict_role_v2(answer, role_input=role_input).model_dump(mode="json")
    CardVerdictRoleResult.model_validate(stored)
    with pytest.raises(ValidationError):
        CardRoleIsolation(kind="finding", unit_id="u", rule_codes=[])
    with pytest.raises(ValidationError):
        CardRoleIsolation(kind="finding", unit_id="u", rule_codes=["원문 문장"])
    with pytest.raises(ValidationError):
        CardRoleIsolation(kind="global", unit_id="u", rule_codes=["role_evidence_unknown"])
    finding = stored["unit_findings"][0]
    for broken in (
        {**stored, "unit_findings": [{**finding, "assessment": "met"}, *stored["unit_findings"][1:]]},
        {**stored, "unit_findings": [{**finding, "evidence_refs": [evidence(frozen.units[0])]},
                                     *stored["unit_findings"][1:]]},
        {**stored, "unit_findings": [{**finding, "reason": "모델 이유"}, *stored["unit_findings"][1:]]},
        {**stored, "isolated_items": [*stored["isolated_items"], *stored["isolated_items"]]},  # same finding twice
        {**stored, "isolated_items": [{"kind": "finding", "unit_id": "card:unknown",
                                       "rule_codes": ["role_evidence_unknown"]}]},
    ):
        with pytest.raises(ValidationError):
            CardVerdictRoleResult.model_validate(broken)
    assert finding["reason"] == ROLE_ISOLATED_REASON


def _c16_roles(inputs, operations_answer: dict):
    from app.deep_review.services.card_roles import validate_verdict_role_v2

    return {
        role: validate_verdict_role_v2(operations_answer if role == "operations_risk" else _role_v2_output(value),
                                       role_input=value)
        for role, value in inputs.items()
    }


def test_c16_role_isolation_caps_the_verdict_at_conditional() -> None:
    frozen, extract, compare, inputs = _c16_world(fits={0: "met", 1: "met", 2: "met", 3: "met"}, mandatory=True)
    units = frozen.units
    proceed = _synthesis(units, verdict="진행 가능", blocking=[])
    # control: nothing isolated, everything met -> "진행 가능" is allowed
    clean = build_synthesis_input(_c16_roles(inputs, _role_v2_output(inputs["operations_risk"])))
    assert validate_practitioner_verdict(proceed, synthesis_input=clean, extract=extract,
                                         compare=compare).verdict == "진행 가능"
    # only a dropped caution (every finding met): the isolation alone caps the verdict
    answer = _role_v2_output(inputs["operations_risk"])
    answer["cautions"] = [{"unit_id": units[0].unit_id, "text": "확인", "evidence_ids": ["E99"]}]
    roles = _c16_roles(inputs, answer)
    assert roles["operations_risk"].cautions == [] and roles["operations_risk"].isolated_items
    capped = build_synthesis_input(roles)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(proceed, synthesis_input=capped, extract=extract, compare=compare)
    conditional = _synthesis(units, verdict="조건부 진행", blocking=[])
    assembled = assemble_practitioner_verdict(conditional, synthesis_input=capped, extract=extract, compare=compare)
    assert assembled.verdict == "조건부 진행"
    # an isolated finding is a matrix role finding "unknown" with the fixed notice and no evidence
    isolated_answer = _role_v2_output(inputs["operations_risk"])
    isolated_answer["unit_findings"][0]["evidence_ids"] = ["E99"]
    synthesis_input = build_synthesis_input(_c16_roles(inputs, isolated_answer))
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(proceed, synthesis_input=synthesis_input, extract=extract, compare=compare)
    assembled = assemble_practitioner_verdict(conditional, synthesis_input=synthesis_input, extract=extract,
                                              compare=compare)
    row = next(item for item in assembled.matrix if item.unit_id == units[0].unit_id)
    from app.deep_review.services.card_roles import ROLE_ISOLATED_REASON

    assert [(finding.assessment, finding.reason, finding.evidence_refs) for finding in row.role_findings] == [
        ("unknown", ROLE_ISOLATED_REASON, [])]
    assert row.fit_status == "met"  # the deterministic compare is never changed
    # synthesis may not cite evidence through an isolated finding
    caution = {"unit_id": units[0].unit_id, "text": "확인", "evidence_refs": [evidence(units[0])]}
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(_synthesis(units, blocking=[], cautions=[caution]),
                                      synthesis_input=synthesis_input, extract=extract, compare=compare)
    # a stored v10 role row that disagrees with its isolation list is rejected at synthesis
    tampered = synthesis_input.model_dump(mode="json")
    operations = tampered["roles"][2]
    operations["isolated_items"] = []
    with pytest.raises((CardAnalysisValidationError, ValidationError)):
        validate_practitioner_verdict(conditional, synthesis_input=tampered, extract=extract, compare=compare)


def test_c16_extract_missing_unit_is_isolated_only_when_allowed() -> None:
    from app.deep_review.services.card_analysis import (
        EXTRACT_UNIT_MISSING_RULE,
        CardExtractStructureError,
        assemble_requirement_extract_v2,
        validate_requirement_extract_isolated,
    )

    texts = ["CMS 구축", "보안 운영 계획을 매월 보고한다", "백업 운영 계획을 매월 보고한다", "장애 운영 계획을 매월 보고한다"]
    frozen = card_input(texts)
    answer = {"schema_version": "bidops.requirement-extract.v2", "items": [_v2_item(unit) for unit in frozen.units]}
    missing = deepcopy(answer)
    dropped = missing["items"].pop(1)["unit_id"]
    # the first answer is still a repairable structure error (repair stays first, unchanged)
    with pytest.raises(CardExtractStructureError) as error:
        assemble_requirement_extract_v2(missing, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    assert error.value.rule_codes == ["extract_unit_coverage"]
    built = assemble_requirement_extract_v2(missing, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                            allow_missing_units=True)
    assert [item["unit_id"] for item in built["items"]] == [unit.unit_id for unit in frozen.units if unit.unit_id != dropped]
    result = validate_requirement_extract_isolated(built, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                                   missing_unit_ids=[dropped])
    assert EXTRACT_UNIT_MISSING_RULE == "extract_unit_missing"
    assert [row.model_dump() for row in result.rejected_units] == [
        {"unit_id": dropped, "rule_codes": ["extract_unit_missing"]}]
    assert [item.unit_id for item in result.items] == [item["unit_id"] for item in built["items"]]
    # missing and evidence-rejected units are listed together in batch order
    both = deepcopy(built)
    both["items"][2]["evidence"][0]["quote"] = "원문에 없는 인용"
    result = validate_requirement_extract_isolated(both, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                                   missing_unit_ids=[dropped])
    assert [(row.unit_id, row.rule_codes) for row in result.rejected_units] == [
        (dropped, ["extract_unit_missing"]), (frozen.units[3].unit_id, ["evidence_quote_not_verbatim"])]
    # extra/unknown/duplicate ids or a different order stay fatal even when missing units are allowed
    for mutate in (
        lambda a: a["items"].append({**deepcopy(a["items"][0]), "unit_id": "card:unknown"}),
        lambda a: a["items"].append(deepcopy(a["items"][0])),
        lambda a: a["items"].reverse(),
        lambda a: a["items"][0]["constraints"].append({"kind": "count", "value": 1, "unit": "day", "fact_key": None,
                                                       "quote": "CMS", "locator": {
                                                           "source_sha256": SOURCE_SHA, "block_key": "block-0"}}),
    ):
        changed = deepcopy(missing)
        mutate(changed)
        with pytest.raises(CardExtractStructureError):
            assemble_requirement_extract_v2(changed, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                            allow_missing_units=True)
    # the validator accepts exactly the batch minus the declared missing units
    for declared in ([], [frozen.units[0].unit_id], [dropped, dropped], ["card:unknown"]):
        with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
            validate_requirement_extract_isolated(built, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                                  missing_unit_ids=declared)
    # the batch-level validator (v1-v6) and the default isolated call are unchanged
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract_isolated(built, card_input=frozen, batch_index=0, ontology=ONTOLOGY)
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract(built, card_input=frozen, batch_index=0, ontology=ONTOLOGY)


def test_c16_mock_answers_role_v2_with_its_own_catalog_ids() -> None:
    from app.deep_review.services.card_analysis import stage_prompt
    from app.deep_review.services.card_roles import validate_verdict_role_v2
    from app.deep_review.services.company_analysis_input import card_role_evidence_catalog
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    _frozen, _extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    extract = role_input.extract.model_dump(mode="json")
    value = {"role": role_input.role, "extract": extract, "compare": role_input.compare.model_dump(mode="json"),
             "profile_facts": [], "profile_evidence": [], "evidence_catalog": card_role_evidence_catalog(extract)}
    client = MockCardAnalysisClient(ONTOLOGY)
    v2 = client.invoke_prompt(stage_prompt(role_input.role, "x", {}, value, repair=False), contract="card-role-v2")
    assert v2.structured_output["schema_version"] == "bidops.verdict-role.v2"
    assert [row["evidence_ids"] for row in v2.structured_output["unit_findings"]] == [["E1"], ["E3"], ["E5"], ["E7"]]
    result = validate_verdict_role_v2(v2.structured_output, role_input=role_input)
    assert result.isolated_items == []
    # the same mapped evidence as the v1 mock answer cites as triples
    v1_value = {key: item for key, item in value.items() if key != "evidence_catalog"}
    v1 = client.invoke_prompt(stage_prompt(role_input.role, "x", {}, v1_value, repair=False), contract="card-role-v1")
    assert result.model_copy(update={"isolated_items": None}).model_dump(mode="json") == validate_verdict_role(
        v1.structured_output, role_input=role_input).model_dump(mode="json")
    assert client.calls == [("card-role-v2", "operations_risk"), ("card-role-v1", "operations_risk")]


# --- 결정 C19 (RL-05 STEP-008): v10 role caution outside the role and synthesis item isolation ---


def _c19_world(*, fits: dict[int, str] | None = None):
    """Four 운영 units (operations_risk) and one 기능 unit (technical_fit only), each with one constraint triple."""

    fits = fits or {}
    names = C16_NAMES[:5]
    frozen = card_input([f"{name} 운영 계획을 매월 보고한다" for name in names])
    extract = CardRequirementExtract.model_validate({"items": [
        extract_item(unit, type_="기능" if index == 4 else "운영", mandatory=None, normalized=f"{name} 운영 계획 보고",
                     constraints=[constraint(unit, kind="text", value=f"{name} 운영 계획", unit_name=None,
                                             operator="eq", quote=f"{name} 운영 계획")])
        for index, (unit, name) in enumerate(zip(frozen.units, names))
    ]})
    compare = CardRequirementCompare.model_validate({"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": unit.unit_id, "fit_status": fits.get(index, "unknown"), "evidence_ids": [],
         "reason_codes": ["confirmed_match" if fits.get(index) == "met" else "unmapped"],
         "constraint_results": [{"constraint_index": 0, "status": fits.get(index, "unknown"), "fact_ids": [],
                                 "path_ids": [],
                                 "reason_code": "confirmed_match" if fits.get(index) == "met" else "unmapped"}]}
        for index, unit in enumerate(frozen.units)
    ]})
    return frozen, extract, compare, build_verdict_role_inputs(extract, compare)


def _c19_roles(inputs, overrides: dict[str, dict] | None = None):
    from app.deep_review.services.card_roles import validate_verdict_role_v2

    overrides = overrides or {}
    return {role: validate_verdict_role_v2(overrides.get(role) or _role_v2_output(value), role_input=value)
            for role, value in inputs.items()}


def test_c19_role_caution_on_a_unit_outside_the_role_is_isolated_not_fatal() -> None:
    from app.deep_review.schemas.card_analysis import CardVerdictRoleResult
    from app.deep_review.services.card_roles import (
        ROLE_CAUTION_FOREIGN_UNIT_RULE,
        validate_isolated_verdict_role,
        validate_verdict_role_v2,
    )

    frozen, _extract, _compare, inputs = _c19_world()
    role_input = inputs["operations_risk"]
    assert [row.unit_id for row in inputs["technical_fit"].extract.items] == [frozen.units[4].unit_id]
    u0, other = frozen.units[0], frozen.units[4].unit_id  # ``other`` is a technical_fit unit
    answer = _role_v2_output(role_input)
    answer["cautions"] = [
        {"unit_id": u0.unit_id, "text": "보안 계획 확인", "evidence_ids": ["E2"]},
        {"unit_id": other, "text": "다른 역할 요구사항 주의", "evidence_ids": ["E1"]},
        {"unit_id": "card:unknown", "text": "없는 요구사항 주의", "evidence_ids": []},
    ]
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    result = validate_verdict_role_v2(answer, role_input=role_input)
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before
    assert ROLE_CAUTION_FOREIGN_UNIT_RULE == "role_caution_foreign_unit"
    assert [row.unit_id for row in result.cautions] == [u0.unit_id]
    assert [row.model_dump(mode="json") for row in result.isolated_items] == [
        {"kind": "caution", "unit_id": other, "rule_codes": ["role_caution_foreign_unit"]},
        {"kind": "caution", "unit_id": "card:unknown", "rule_codes": ["role_caution_foreign_unit"]}]
    # findings untouched; the dropped caution's text is nowhere in the stored row
    assert all(row.reason != "" and row.evidence_refs for row in result.unit_findings)
    stored = result.model_dump(mode="json")
    assert "다른 역할 요구사항 주의" not in json.dumps(stored, ensure_ascii=False)
    # the stored row re-validates (synthesis re-check and synthesis-only resume)
    validate_isolated_verdict_role(stored, role_input=role_input)
    # the 25% limit counts findings only: 1 of 4 isolated findings + many foreign cautions continues
    many = deepcopy(answer)
    many["unit_findings"][0]["evidence_ids"] = ["E999"]
    many["cautions"] = [{"unit_id": f"card:unknown-{index}", "text": "확인", "evidence_ids": []} for index in range(6)]
    limited = validate_verdict_role_v2(many, role_input=role_input)
    assert [row.kind for row in limited.isolated_items] == ["finding"] + ["caution"] * 6
    many["unit_findings"][1]["evidence_ids"] = ["E999"]  # 2 of 4 findings: above 25% with or without cautions
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role_v2(many, role_input=role_input)
    # DTO: the code is caution-only, the sole code, and never names a unit of the role
    for items in (
        [{"kind": "caution", "unit_id": u0.unit_id, "rule_codes": ["role_caution_foreign_unit"]}],
        [{"kind": "finding", "unit_id": other, "rule_codes": ["role_caution_foreign_unit"]}],
        [{"kind": "caution", "unit_id": other, "rule_codes": ["role_caution_foreign_unit", "role_evidence_unknown"]}],
        [{"kind": "caution", "unit_id": other, "rule_codes": ["role_evidence_unknown"]}],  # evidence codes: role units
    ):
        with pytest.raises(ValidationError):
            CardVerdictRoleResult.model_validate({**stored, "isolated_items": items})
    # v1 role validation (policies v1-v9) is unchanged: a caution outside the role stays fatal
    v1 = _role_output(role_input)
    v1["cautions"] = [{"unit_id": other, "text": "확인", "evidence_refs": [evidence(frozen.units[4])]}]
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role(v1, role_input=role_input)


def test_c19_foreign_role_caution_caps_the_verdict_like_any_role_isolation() -> None:
    frozen, extract, compare, inputs = _c19_world(fits={index: "met" for index in range(5)})
    proceed = _synthesis(frozen.units, verdict="진행 가능", blocking=[])
    clean = build_synthesis_input(_c19_roles(inputs))
    assert validate_practitioner_verdict(proceed, synthesis_input=clean, extract=extract,
                                         compare=compare).verdict == "진행 가능"
    answer = _role_v2_output(inputs["operations_risk"])
    answer["cautions"] = [{"unit_id": frozen.units[4].unit_id, "text": "확인", "evidence_ids": []}]
    capped = build_synthesis_input(_c19_roles(inputs, {"operations_risk": answer}))
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(proceed, synthesis_input=capped, extract=extract, compare=compare)
    assembled = assemble_practitioner_verdict(_synthesis(frozen.units, blocking=[]), synthesis_input=capped,
                                              extract=extract, compare=compare)
    assert assembled.verdict == "조건부 진행" and assembled.cautions == []


def _c19_synthesis_answer(frozen):
    u0, u1 = frozen.units[:2]
    shortened_quote = u1.blocks[0].text[:-3]
    assert shortened_quote and shortened_quote in u1.blocks[0].text  # a substring of the unit's own quote
    kept_action = {"unit_id": u0.unit_id, "owner": None, "action": "보안 계획 확인", "evidence_refs": [evidence(u0)]}
    shortened_action = {"unit_id": u1.unit_id, "owner": None, "action": "백업 계획을 원문에서 확인",
                        "evidence_refs": [evidence(u1, shortened_quote)]}
    outside_action = {"unit_id": "missing_section:budget", "owner": None, "action": "예산 확인", "evidence_refs": []}
    kept_caution = {"unit_id": u0.unit_id, "text": "보안 보고 주기 주의", "evidence_refs": [evidence(u0)]}
    outside_caution = {"unit_id": "card:unknown", "text": "범위 밖 주의", "evidence_refs": []}
    shortened_caution = {"unit_id": u1.unit_id, "text": "백업 보고 주의", "evidence_refs": [evidence(u1, "백업 운영")]}
    answer = _synthesis_v2(cautions=[kept_caution, outside_caution, shortened_caution],
                           actions=[kept_action, shortened_action, outside_action])
    return answer, kept_action, kept_caution


def test_c19_v10_synthesis_drops_items_outside_the_roles_or_their_evidence_and_keeps_the_verdict() -> None:
    from app.deep_review.services.card_roles import (
        SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE,
        SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE,
        synthesis_v1_from_v2,
        validate_practitioner_verdict_isolated,
    )

    frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c19_roles(inputs))
    u1 = frozen.units[1]
    answer, kept_action, kept_caution = _c19_synthesis_answer(frozen)
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    v1 = synthesis_v1_from_v2(answer, extract=extract, compare=compare)
    # v9 rules (no isolation): the same answer is still card_synthesis_invalid
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict(v1, synthesis_input=synthesis_input, extract=extract, compare=compare)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        assemble_practitioner_verdict(v1, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                      record_rejected_units=True, code_actions=True)
    verdict, isolated = validate_practitioner_verdict_isolated(
        v1, synthesis_input=synthesis_input, extract=extract, compare=compare)
    assert (SYNTHESIS_UNIT_OUTSIDE_ROLES_RULE, SYNTHESIS_EVIDENCE_OUTSIDE_UNIT_RULE) == (
        "synthesis_unit_outside_roles", "synthesis_evidence_outside_unit")
    # verdict, reason and code blocking ids unchanged; only the bad items are left out (never rewritten)
    assert (verdict.verdict, verdict.reason, verdict.blocking_condition_ids) == (
        v1["verdict"], v1["reason"], v1["blocking_condition_ids"])
    assert [row.model_dump(mode="json") for row in verdict.cautions] == [kept_caution]
    assert [row.model_dump(mode="json") for row in verdict.next_actions] == [kept_action]
    expected = [
        {"kind": "caution", "unit_id": "card:unknown", "rule_codes": ["synthesis_unit_outside_roles"]},
        {"kind": "caution", "unit_id": u1.unit_id, "rule_codes": ["synthesis_evidence_outside_unit"]},
        {"kind": "next_action", "unit_id": u1.unit_id, "rule_codes": ["synthesis_evidence_outside_unit"]},
        {"kind": "next_action", "unit_id": "missing_section:budget", "rule_codes": ["synthesis_unit_outside_roles"]},
    ]
    assert [row.model_dump(mode="json") for row in isolated] == expected
    assembled = assemble_practitioner_verdict(
        v1, synthesis_input=synthesis_input, extract=extract, compare=compare, record_rejected_units=True,
        code_actions=True, isolate_items=True)
    assert (assembled.verdict, assembled.reason, assembled.blocking_condition_ids) == (
        v1["verdict"], v1["reason"], v1["blocking_condition_ids"])
    stored = assembled.model_dump(mode="json")
    assert stored["next_actions"] == [{**kept_action, "origin": "model"}]  # dropped rows never reach the row
    assert stored["cautions"] == [kept_caution]
    assert stored["isolated_items"] == expected
    text = json.dumps(stored, ensure_ascii=False)
    assert "백업 계획을 원문에서 확인" not in text and "범위 밖 주의" not in text and "예산 확인" not in text
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before  # never corrected in place
    # the stored row validates; an assembly with nothing to drop records an empty list
    CardAssembledPractitionerVerdict.model_validate(stored)
    clean = assemble_practitioner_verdict(
        synthesis_v1_from_v2(_synthesis_v2(actions=[kept_action]), extract=extract, compare=compare),
        synthesis_input=synthesis_input, extract=extract, compare=compare, record_rejected_units=True,
        code_actions=True, isolate_items=True)
    assert clean.model_dump(mode="json")["isolated_items"] == []


def test_c19_v10_synthesis_owner_outside_the_allowlist_and_other_rules_stay_fatal() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v2, validate_practitioner_verdict_isolated

    frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c19_roles(inputs))
    answer, kept_action, _kept_caution = _c19_synthesis_answer(frozen)
    # an invented owner is fatal even on an action that would otherwise be dropped
    for action in answer["next_actions"]:
        payload = synthesis_v1_from_v2(_synthesis_v2(actions=[kept_action, {**action, "owner": "김담당"}]),
                                       extract=extract, compare=compare)
        with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
            validate_practitioner_verdict_isolated(payload, synthesis_input=synthesis_input, extract=extract,
                                                   compare=compare)
        with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
            assemble_practitioner_verdict(payload, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                          code_actions=True, isolate_items=True)
    # a listed owner is still allowed
    named = synthesis_v1_from_v2(_synthesis_v2(actions=[{**kept_action, "owner": "김담당"}]), extract=extract,
                                 compare=compare)
    validate_practitioner_verdict_isolated(named, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                           allowed_owners=["김담당"])
    # the rejected-units contract is unchanged
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict_isolated(named, synthesis_input=synthesis_input, extract=extract,
                                               compare=compare, allowed_owners=["김담당"],
                                               rejected_units=[frozen.units[0].unit_id])


def test_c19_v10_synthesis_isolation_caps_the_verdict_at_conditional() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v2, validate_practitioner_verdict_isolated

    frozen, extract, compare, inputs = _c19_world(fits={index: "met" for index in range(5)})
    synthesis_input = build_synthesis_input(_c19_roles(inputs))
    clean = synthesis_v1_from_v2(_synthesis_v2(verdict="진행 가능"), extract=extract, compare=compare)
    assert validate_practitioner_verdict_isolated(
        clean, synthesis_input=synthesis_input, extract=extract, compare=compare)[0].verdict == "진행 가능"
    dropped_only = synthesis_v1_from_v2(_synthesis_v2(verdict="진행 가능", actions=[
        {"unit_id": "card:unknown", "owner": None, "action": "확인", "evidence_refs": []}]),
        extract=extract, compare=compare)
    # dropping the item never turns an unresolved answer into "진행 가능"
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        validate_practitioner_verdict_isolated(dropped_only, synthesis_input=synthesis_input, extract=extract,
                                               compare=compare)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        assemble_practitioner_verdict(dropped_only, synthesis_input=synthesis_input, extract=extract,
                                      compare=compare, code_actions=True, isolate_items=True)


def test_c19_final_row_isolation_dto_and_rows_written_before_c19() -> None:
    from app.deep_review.schemas.card_analysis import CardSynthesisIsolation
    from app.deep_review.services.card_roles import synthesis_v1_from_v2

    frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c19_roles(inputs))
    answer, _kept_action, _kept_caution = _c19_synthesis_answer(frozen)
    stored = assemble_practitioner_verdict(
        synthesis_v1_from_v2(answer, extract=extract, compare=compare), synthesis_input=synthesis_input,
        extract=extract, compare=compare, record_rejected_units=True, code_actions=True,
        isolate_items=True).model_dump(mode="json")
    # a v10 row written before C19 (and every v1-v9 row) has no key: read as "none", dumped without it
    before_c19 = {key: value for key, value in stored.items() if key != "isolated_items"}
    parsed = CardAssembledPractitionerVerdict.model_validate(before_c19)
    assert parsed.isolated_items is None and parsed.model_dump(mode="json") == before_c19
    legacy = assemble_practitioner_verdict(
        synthesis_v1_from_v2(_synthesis_v2(), extract=extract, compare=compare), synthesis_input=synthesis_input,
        extract=extract, compare=compare, record_rejected_units=True, code_actions=True)
    assert "isolated_items" not in legacy.model_dump(mode="json")
    for broken in (
        {**stored, "verdict": "진행 가능"},  # an isolation caps the verdict
        {**stored, "isolated_items": [{"kind": "finding", "unit_id": "u", "rule_codes": ["synthesis_unit_outside_roles"]}]},
        {**stored, "isolated_items": [{"kind": "caution", "unit_id": "u", "rule_codes": ["role_evidence_unknown"]}]},
        {**stored, "isolated_items": [{"kind": "caution", "unit_id": "u", "rule_codes": []}]},
        {**stored, "isolated_items": [{"kind": "caution", "unit_id": "u", "rule_codes": [
            "synthesis_unit_outside_roles", "synthesis_unit_outside_roles"]}]},
        {**stored, "isolated_items": [{"kind": "caution", "unit_id": "u", "rule_codes": ["원문 문장"]}]},
    ):
        with pytest.raises(ValidationError):
            CardAssembledPractitionerVerdict.model_validate(broken)
    with pytest.raises(ValidationError):
        CardSynthesisIsolation(kind="next_action", unit_id="", rule_codes=["synthesis_unit_outside_roles"])


# --- 결정 C20 (RL-05 STEP-009): policy v11 -- unit refs (U1...) and evidence ids (E1...) in the role
# contract v3 and the synthesis contract v3, and the text-constraint value rule ----------------------
#
# v10 real failures C19 does not fix: a role answer copied 29 of 38 long unit ids with the source sha
# cut to 47 characters (coverage failed, card_role_invalid); synthesis cautions/next actions still
# copied (sha, block, quote) triples; an extract batch isolated 26% of its units because text-kind
# constraint values paraphrased a phrase of their verbatim quote.

RL_V11 = "analysis-policy-luna-rl-v11"


def _role_v3_output(role_input, assessments: dict[str, str] | None = None) -> dict:
    """A contract-following v3 answer: the v2 answer with each unit named by its ``U`` ref."""

    v2 = _role_v2_output(role_input, assessments)
    refs = {row.unit_id: f"U{index}" for index, row in enumerate(role_input.extract.items, start=1)}
    return {
        "schema_version": "bidops.verdict-role.v3", "role": v2["role"],
        "unit_findings": [
            {"unit_ref": refs[row["unit_id"]], **{key: value for key, value in row.items() if key != "unit_id"}}
            for row in v2["unit_findings"]
        ],
        "cautions": [],
    }


def _c20_roles(inputs, overrides: dict[str, dict] | None = None):
    from app.deep_review.services.card_roles import validate_verdict_role_v3

    overrides = overrides or {}
    return {role: validate_verdict_role_v3(overrides.get(role) or _role_v3_output(value), role_input=value)
            for role, value in inputs.items()}


def test_c20_role_contract_v3_is_registered_and_carries_refs_only() -> None:
    from app.deep_review.contracts import SCHEMA_FILES, VERDICT_ROLE_V3_SCHEMA
    from app.deep_review.services.card_analysis import (
        ROLE_CONTRACT_V2_POLICY_IDENTITIES,
        ROLE_CONTRACT_V3,
        ROLE_CONTRACT_V3_POLICY_IDENTITIES,
        ROLE_CONTRACT_V3_SCHEMA_VERSION,
    )
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS

    assert ROLE_CONTRACT_V3 == "card-role-v3" and ROLE_CONTRACT_V3_SCHEMA_VERSION == "bidops.verdict-role.v3"
    assert CONTRACT_SCHEMAS["card-role-v3"] == VERDICT_ROLE_V3_SCHEMA == "verdict-role-v3"
    assert SCHEMA_FILES[VERDICT_ROLE_V3_SCHEMA] == "bidops.verdict-role.v3.json"
    assert ROLE_CONTRACT_V3_POLICY_IDENTITIES == frozenset({RL_V11})
    assert ROLE_CONTRACT_V2_POLICY_IDENTITIES == frozenset({"analysis-policy-luna-rl-v10"})  # v10 unchanged
    frozen, _extract, _compare, inputs = _c16_world()
    answer = _role_v3_output(inputs["operations_risk"])
    validate_payload(answer, VERDICT_ROLE_V3_SCHEMA)
    assert [row["unit_ref"] for row in answer["unit_findings"]] == ["U1", "U2", "U3", "U4"]
    finding = answer["unit_findings"][0]
    long_id = frozen.units[0].unit_id
    for broken in (
        {**answer, "schema_version": "bidops.verdict-role.v2"},
        {**answer, "unit_findings": [{**finding, "unit_ref": long_id}]},          # a unit id is not a ref
        {**answer, "unit_findings": [{**finding, "unit_ref": long_id[:52]}]},     # the observed truncation
        {**answer, "unit_findings": [{**finding, "unit_ref": "U01"}]},
        {**answer, "unit_findings": [{**finding, "unit_ref": "u1"}]},
        {**answer, "unit_findings": [{**finding, "unit_id": long_id}]},           # extra key
        {**answer, "unit_findings": [{key: value for key, value in finding.items() if key != "unit_ref"}]},
        {**answer, "cautions": [{"unit_id": long_id, "text": "확인", "evidence_ids": []}]},
        {**answer, "cautions": [{"unit_ref": "U1", "text": "확인", "evidence_refs": []}]},
    ):
        with pytest.raises(SchemaValidationError):
            validate_payload(broken, VERDICT_ROLE_V3_SCHEMA)


def test_c20_unit_refs_are_deterministic_and_map_back_to_the_unit_ids() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2, validate_verdict_role_v3
    from app.deep_review.services.company_analysis_input import card_role_unit_refs

    frozen, _extract, _compare, inputs = _c16_world()
    role_input = inputs["operations_risk"]
    payload_extract = role_input.extract.model_dump(mode="json")
    refs = card_role_unit_refs(payload_extract)
    # role extract input order, U1..Un
    assert refs == [{"unit_ref": f"U{index}", "unit_id": unit.unit_id}
                    for index, unit in enumerate(frozen.units, start=1)]
    assert refs == card_role_unit_refs(deepcopy(payload_extract))
    answer = _role_v3_output(role_input)
    answer["cautions"] = [{"unit_ref": "U2", "text": "백업 계획 확인", "evidence_ids": ["E4"]}]
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    result = validate_verdict_role_v3(answer, role_input=role_input)
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before  # never changed in place
    # round trip: the stored row is exactly the v2 result of the same answer with unit ids
    v2 = _role_v2_output(role_input)
    v2["cautions"] = [{"unit_id": frozen.units[1].unit_id, "text": "백업 계획 확인", "evidence_ids": ["E4"]}]
    assert result.model_dump(mode="json") == validate_verdict_role_v2(v2, role_input=role_input).model_dump(mode="json")
    stored = result.model_dump(mode="json")
    assert [row["unit_id"] for row in stored["unit_findings"]] == [unit.unit_id for unit in frozen.units]
    assert stored["cautions"][0]["unit_id"] == frozen.units[1].unit_id
    assert stored["schema_version"] == "bidops.verdict-role.v1" and stored["isolated_items"] == []
    assert '"U1"' not in json.dumps(stored) and "unit_ref" not in json.dumps(stored)


def test_c20_unknown_missing_duplicate_or_reordered_finding_ref_is_fatal() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v3

    frozen, _extract, _compare, inputs = _c16_world(8, fits={0: "met"})
    role_input = inputs["operations_risk"]
    valid = _role_v3_output(role_input)
    validate_verdict_role_v3(valid, role_input=role_input)
    cases = {
        "unknown_ref": lambda o: o["unit_findings"][3].update(unit_ref="U9"),
        "missing": lambda o: o["unit_findings"].pop(),
        "duplicate": lambda o: o["unit_findings"][1].update(unit_ref="U1"),
        "extra": lambda o: o["unit_findings"].append({**deepcopy(o["unit_findings"][0]), "unit_ref": "U9"}),
        "order": lambda o: o["unit_findings"].reverse(),
        # the observed v10 failure shape: a long unit id with the sha cut is not a ref at all
        "truncated_unit_id": lambda o: o["unit_findings"][0].update(unit_ref=frozen.units[0].unit_id[:52]),
        "role_name": lambda o: o.__setitem__("role", "technical_fit"),
        "met_to_gap": lambda o: o["unit_findings"][0].update(assessment="gap"),
        "v2_answer": lambda o: o.update(_role_v2_output(role_input)),
    }
    for name, mutate in cases.items():
        changed = deepcopy(valid)
        mutate(changed)
        with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
            validate_verdict_role_v3(changed, role_input=role_input)
        assert name
    # a finding citing a foreign id is still isolated per item (C16), never fatal
    isolated = deepcopy(valid)
    isolated["unit_findings"][0]["evidence_ids"] = ["E3"]
    result = validate_verdict_role_v3(isolated, role_input=role_input)
    assert [row.model_dump(mode="json") for row in result.isolated_items] == [
        {"kind": "finding", "unit_id": frozen.units[0].unit_id, "rule_codes": ["role_evidence_foreign_unit"]}]


def test_c20_role_caution_with_an_unknown_ref_is_dropped_and_recorded() -> None:
    from app.deep_review.schemas.card_analysis import CardVerdictRoleResult
    from app.deep_review.services.card_roles import validate_isolated_verdict_role, validate_verdict_role_v3

    frozen, _extract, _compare, inputs = _c19_world()
    role_input = inputs["operations_risk"]  # four units; the fifth (technical_fit) has no ref here
    answer = _role_v3_output(role_input)
    answer["cautions"] = [
        {"unit_ref": "U1", "text": "보안 계획 확인", "evidence_ids": ["E2"]},
        {"unit_ref": "U5", "text": "역할 밖 주의", "evidence_ids": ["E1"]},     # no such unit in this role
        {"unit_ref": "U2", "text": "다른 근거 주의", "evidence_ids": ["E1"]},   # another unit's id
    ]
    result = validate_verdict_role_v3(answer, role_input=role_input)
    assert [row.unit_id for row in result.cautions] == [frozen.units[0].unit_id]
    # C19 semantics: dropped, recorded with codes only; the record names the ref the model wrote
    assert [row.model_dump(mode="json") for row in result.isolated_items] == [
        {"kind": "caution", "unit_id": "U5", "rule_codes": ["role_caution_foreign_unit"]},
        {"kind": "caution", "unit_id": frozen.units[1].unit_id, "rule_codes": ["role_evidence_foreign_unit"]}]
    stored = result.model_dump(mode="json")
    assert "역할 밖 주의" not in json.dumps(stored, ensure_ascii=False)
    CardVerdictRoleResult.model_validate(stored)
    validate_isolated_verdict_role(stored, role_input=role_input)  # synthesis re-check / resume
    # cautions never count toward the 25% limit (findings only)
    many = deepcopy(answer)
    many["cautions"] = [{"unit_ref": f"U{index}", "text": "확인", "evidence_ids": []} for index in range(9, 20)]
    assert [row.kind for row in validate_verdict_role_v3(many, role_input=role_input).isolated_items] == (
        ["caution"] * 11)
    many["unit_findings"][0]["evidence_ids"] = ["E999"]
    many["unit_findings"][1]["evidence_ids"] = ["E999"]  # 2 of 4 findings: above 25%
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role_v3(many, role_input=role_input)


def test_c20_v10_role_contract_v2_is_unchanged() -> None:
    from app.deep_review.services.card_roles import validate_verdict_role_v2, validate_verdict_role_v3

    frozen, _extract, _compare, inputs = _c19_world()
    role_input = inputs["operations_risk"]
    v2 = _role_v2_output(role_input)
    v2["cautions"] = [{"unit_id": frozen.units[4].unit_id, "text": "확인", "evidence_ids": []}]
    stored = validate_verdict_role_v2(v2, role_input=role_input).model_dump(mode="json")
    assert stored["isolated_items"] == [
        {"kind": "caution", "unit_id": frozen.units[4].unit_id, "rule_codes": ["role_caution_foreign_unit"]}]
    # the two contracts never pass for each other
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role_v2(_role_v3_output(role_input), role_input=role_input)
    with pytest.raises(CardAnalysisValidationError, match="card_role_invalid"):
        validate_verdict_role_v3(_role_v2_output(role_input), role_input=role_input)
    # v1 (policies v1-v9) is unchanged as well
    validate_verdict_role(_role_output(role_input), role_input=role_input)


def test_c20_synthesis_contract_v3_is_registered_and_carries_refs_only() -> None:
    from app.deep_review.contracts import PRACTITIONER_VERDICT_V3_SCHEMA, SCHEMA_FILES
    from app.deep_review.services.card_analysis import PRACTITIONER_VERDICT_V3, SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA
    from app.deep_review.services.luna_client import CONTRACT_SCHEMAS

    assert PRACTITIONER_VERDICT_V3 == "bidops.practitioner-verdict.v3"
    assert SYNTHESIS_CONTRACT_BY_REPORT_SCHEMA[PRACTITIONER_VERDICT_V3] == "card-synthesis-v3"
    assert CONTRACT_SCHEMAS["card-synthesis-v3"] == PRACTITIONER_VERDICT_V3_SCHEMA == "practitioner-verdict-v3"
    assert SCHEMA_FILES[PRACTITIONER_VERDICT_V3_SCHEMA] == "bidops.practitioner-verdict.v3.json"
    answer = {"schema_version": "bidops.practitioner-verdict.v3", "verdict": "조건부 진행", "reason": "확인 필요",
              "cautions": [{"unit_ref": "U1", "text": "확인", "evidence_ids": ["E1"]}],
              "next_actions": [{"unit_ref": "U2", "owner": None, "action": "확인", "evidence_ids": []}]}
    validate_payload(answer, PRACTITIONER_VERDICT_V3_SCHEMA)
    caution, action = answer["cautions"][0], answer["next_actions"][0]
    for broken in (
        {**answer, "schema_version": "bidops.practitioner-verdict.v2"},
        {**answer, "blocking_condition_ids": []},
        {**answer, "cautions": [{**caution, "unit_ref": f"card:{SOURCE_SHA}:0:REQ-0"}]},
        {**answer, "cautions": [{**caution, "evidence_refs": []}]},
        {**answer, "next_actions": [{**action, "unit_id": "U2"}]},
        {**answer, "next_actions": [{**action, "evidence_ids": ["E1x"]}]},
        {**answer, "next_actions": [{key: value for key, value in action.items() if key != "owner"}]},
    ):
        with pytest.raises(SchemaValidationError):
            validate_payload(broken, PRACTITIONER_VERDICT_V3_SCHEMA)


def _synthesis_v3(*, verdict: str = "조건부 진행", cautions=None, actions=None) -> dict:
    return {
        "schema_version": "bidops.practitioner-verdict.v3", "verdict": verdict,
        "reason": "상주 인원 요구가 회사 가용 인원을 넘고 확인할 조건이 남아 있다.",
        "cautions": cautions or [], "next_actions": actions or [],
    }


def test_c20_synthesis_unit_catalog_refs_and_ids_map_back_to_ids_and_triples() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v2, synthesis_v1_from_v3
    from app.deep_review.services.company_analysis_input import card_synthesis_unit_index

    frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c20_roles(inputs))
    roles = [row.model_dump(mode="json") for row in synthesis_input.roles]
    units, index = card_synthesis_unit_index(roles)
    # units in role order (eligibility, technical, operations), then finding order; ids unique in the payload
    assert [row["unit_id"] for row in units] == [frozen.units[4].unit_id, *[unit.unit_id for unit in frozen.units[:4]]]
    assert [row["unit_ref"] for row in units] == ["U1", "U2", "U3", "U4", "U5"]
    assert [row["evidence_id"] for row in index] == [f"E{n}" for n in range(1, len(index) + 1)]
    assert len({(row["unit_id"], row["source_sha256"], row["block_key"], row["quote"]) for row in index}) == len(index)
    assert (units, index) == card_synthesis_unit_index(deepcopy(roles))  # deterministic
    by_unit = {}
    for row in index:
        by_unit.setdefault(row["unit_id"], []).append(row)
    u0 = frozen.units[0]
    ref0 = next(row["unit_ref"] for row in units if row["unit_id"] == u0.unit_id)
    first = by_unit[u0.unit_id][0]
    answer = _synthesis_v3(
        cautions=[{"unit_ref": ref0, "text": "보안 보고 주기 주의", "evidence_ids": [first["evidence_id"]]}],
        actions=[{"unit_ref": ref0, "owner": None, "action": "보안 계획 확인", "evidence_ids": []}])
    before = json.dumps(answer, ensure_ascii=False, sort_keys=True)
    mapped, isolated = synthesis_v1_from_v3(answer, synthesis_input=synthesis_input, extract=extract,
                                            compare=compare)
    assert json.dumps(answer, ensure_ascii=False, sort_keys=True) == before
    assert isolated == []
    triple = {key: first[key] for key in ("source_sha256", "block_key", "quote")}
    v2_equivalent = _synthesis_v2(
        cautions=[{"unit_id": u0.unit_id, "text": "보안 보고 주기 주의", "evidence_refs": [triple]}],
        actions=[{"unit_id": u0.unit_id, "owner": None, "action": "보안 계획 확인", "evidence_refs": []}])
    assert mapped == synthesis_v1_from_v2(v2_equivalent, extract=extract, compare=compare)  # round trip
    assembled = assemble_practitioner_verdict(
        mapped, synthesis_input=synthesis_input, extract=extract, compare=compare, record_rejected_units=True,
        code_actions=True, isolate_items=True, pre_isolated=isolated)
    stored = assembled.model_dump(mode="json")
    assert stored["isolated_items"] == []
    assert stored["cautions"] == [{"unit_id": u0.unit_id, "text": "보안 보고 주기 주의", "evidence_refs": [triple]}]
    assert "unit_ref" not in json.dumps(stored)


def test_c20_synthesis_bad_ref_or_evidence_id_drops_only_that_item() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v3
    from app.deep_review.services.company_analysis_input import card_synthesis_unit_index

    frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c20_roles(inputs))
    units, index = card_synthesis_unit_index([row.model_dump(mode="json") for row in synthesis_input.roles])
    ref_of = {row["unit_id"]: row["unit_ref"] for row in units}
    ids_of: dict[str, list[str]] = {}
    for row in index:
        ids_of.setdefault(row["unit_id"], []).append(row["evidence_id"])
    u0, u1 = frozen.units[:2]
    kept = {"unit_ref": ref_of[u0.unit_id], "owner": None, "action": "보안 계획 확인",
            "evidence_ids": ids_of[u0.unit_id][:1]}
    answer = _synthesis_v3(
        cautions=[
            {"unit_ref": "U9", "text": "범위 밖 주의", "evidence_ids": []},                                     # unknown ref
            {"unit_ref": ref_of[u1.unit_id], "text": "다른 근거 주의", "evidence_ids": ids_of[u0.unit_id][:1]},  # foreign id
        ],
        actions=[kept, {"unit_ref": ref_of[u1.unit_id], "owner": None, "action": "없는 근거 행동",
                        "evidence_ids": ["E999"]}])
    mapped, isolated = synthesis_v1_from_v3(answer, synthesis_input=synthesis_input, extract=extract,
                                            compare=compare)
    assert [row.model_dump(mode="json") for row in isolated] == [
        {"kind": "caution", "unit_id": "U9", "rule_codes": ["synthesis_unit_outside_roles"]},
        {"kind": "caution", "unit_id": u1.unit_id, "rule_codes": ["synthesis_evidence_outside_unit"]},
        {"kind": "next_action", "unit_id": u1.unit_id, "rule_codes": ["synthesis_evidence_outside_unit"]},
    ]
    assert [row["unit_id"] for row in mapped["next_actions"]] == [u0.unit_id] and mapped["cautions"] == []
    assembled = assemble_practitioner_verdict(
        mapped, synthesis_input=synthesis_input, extract=extract, compare=compare, record_rejected_units=True,
        code_actions=True, isolate_items=True, pre_isolated=isolated)
    # verdict, reason and code blocking ids as answered; dropped items never reach the row
    assert (assembled.verdict, assembled.reason) == (answer["verdict"], answer["reason"])
    stored = assembled.model_dump(mode="json")
    assert stored["isolated_items"] == [row.model_dump(mode="json") for row in isolated]
    text = json.dumps(stored, ensure_ascii=False)
    assert "범위 밖 주의" not in text and "다른 근거 주의" not in text and "없는 근거 행동" not in text
    # dropping never turns an answer into "진행 가능"
    met_world = _c19_world(fits={index: "met" for index in range(5)})
    met_input = build_synthesis_input(_c20_roles(met_world[3]))
    dropped_only = _synthesis_v3(verdict="진행 가능", actions=[
        {"unit_ref": "U9", "owner": None, "action": "확인", "evidence_ids": []}])
    proceed, records = synthesis_v1_from_v3(dropped_only, synthesis_input=met_input, extract=met_world[1],
                                            compare=met_world[2])
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        assemble_practitioner_verdict(proceed, synthesis_input=met_input, extract=met_world[1],
                                      compare=met_world[2], code_actions=True, isolate_items=True,
                                      pre_isolated=records)
    clean, none = synthesis_v1_from_v3(_synthesis_v3(verdict="진행 가능"), synthesis_input=met_input,
                                       extract=met_world[1], compare=met_world[2])
    assert none == [] and assemble_practitioner_verdict(
        clean, synthesis_input=met_input, extract=met_world[1], compare=met_world[2], code_actions=True,
        isolate_items=True, pre_isolated=none).verdict == "진행 가능"
    # pre-isolated records need the isolation mode (policy v11 always has it)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        assemble_practitioner_verdict(mapped, synthesis_input=synthesis_input, extract=extract, compare=compare,
                                      code_actions=True, pre_isolated=isolated)


def test_c20_synthesis_owner_outside_the_allowlist_stays_fatal_even_on_a_dropped_item() -> None:
    from app.deep_review.services.card_roles import synthesis_v1_from_v3

    _frozen, extract, compare, inputs = _c19_world()
    synthesis_input = build_synthesis_input(_c20_roles(inputs))
    for unit_ref in ("U1", "U9"):
        answer = _synthesis_v3(actions=[{"unit_ref": unit_ref, "owner": "김담당", "action": "확인",
                                         "evidence_ids": []}])
        with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
            synthesis_v1_from_v3(answer, synthesis_input=synthesis_input, extract=extract, compare=compare)
        mapped, _records = synthesis_v1_from_v3(answer, synthesis_input=synthesis_input, extract=extract,
                                                compare=compare, allowed_owners=["김담당"])
        assert mapped["blocking_condition_ids"] == []
    # schema violations are card_synthesis_invalid (the runner turns them into the single schema repair)
    with pytest.raises(CardAnalysisValidationError, match="card_synthesis_invalid"):
        synthesis_v1_from_v3(_synthesis_v2(), synthesis_input=synthesis_input, extract=extract, compare=compare)


#: The observed v10 extract failure shape (RL-05 1번): a verbatim quote whose text value paraphrases it.
C20_APPROVAL = "과업 내용을 변경하려면 반드시 발주기관으로부터 사전승인을 받아야 함"


def _c20_text_payload(text: str, *, value, quote: str, kind: str = "text", unit_name=None,
                      normalized: str = "요구사항") -> tuple[CardAnalysisInput, dict]:
    from app.deep_review.services.card_analysis import expected_constraint_operator

    frozen = card_input([text])
    unit = frozen.units[0]
    payload = {"schema_version": "bidops.requirement-extract.v1", "items": [extract_item(
        unit, type_="계약", mandatory=None, normalized=normalized,
        constraints=[constraint(unit, kind=kind, value=value, unit_name=unit_name,
                                operator=expected_constraint_operator(kind, quote), quote=quote)],
    )]}
    return frozen, payload


def _c20_rules(frozen, payload, *, relaxed: bool) -> list[list[str]]:
    from app.deep_review.services.card_analysis import validate_requirement_extract_isolated

    result = validate_requirement_extract_isolated(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY,
                                                   text_value_relaxed=relaxed)
    return [row.rule_codes for row in result.rejected_units]


def test_c20_v11_text_value_may_paraphrase_its_verbatim_quote_and_v10_still_rejects_it() -> None:
    from app.deep_review.services.card_analysis import TEXT_VALUE_RELAXED_POLICY_IDENTITIES

    assert TEXT_VALUE_RELAXED_POLICY_IDENTITIES == frozenset({RL_V11})
    frozen, payload = _c20_text_payload(C20_APPROVAL, value="발주기관의 사전승인",
                                        quote="반드시 발주기관으로부터 사전승인을 받아야 함")
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert _c20_rules(frozen, payload, relaxed=True) == []
    assert _c20_rules(frozen, payload, relaxed=False) == [["constraint_expression"]]  # v7-v10 unchanged
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        validate_requirement_extract(payload, card_input=frozen, batch_index=0, ontology=ONTOLOGY)  # v1-v6
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before  # the value is never rewritten
    # a verbatim value keeps passing under both rules
    _same, verbatim = _c20_text_payload(C20_APPROVAL, value="발주기관으로부터 사전승인",
                                        quote="반드시 발주기관으로부터 사전승인을 받아야 함")
    assert _c20_rules(frozen, verbatim, relaxed=True) == [] == _c20_rules(frozen, verbatim, relaxed=False)
    # the value stays a non-empty string (structural rule, unchanged)
    with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
        _c20_rules(frozen, _c20_text_payload(C20_APPROVAL, value="", quote="사전승인을 받아야 함")[1], relaxed=True)


def test_c20_v11_quote_rules_still_apply_to_a_text_constraint() -> None:
    frozen, payload = _c20_text_payload(C20_APPROVAL, value="발주기관의 사전승인",
                                        quote="반드시 발주기관의 사전승인을 받아야 함")  # quote not in the block
    assert _c20_rules(frozen, payload, relaxed=True) == [["constraint_quote_not_verbatim"]]
    deadline = "계약 후 30일 이내 착수계를 제출하고 계약 후 30일 이내 보안서약서를 제출"
    frozen, repeated = _c20_text_payload(deadline, value="30일 이내 제출", quote="계약 후 30일 이내",
                                         normalized="계약 후 30일 이내 제출")
    assert _c20_rules(frozen, repeated, relaxed=True) == [["constraint_quote_not_unique"]]
    frozen, truncated = _c20_text_payload("계약 후 30일 이내 착수계를 제출", value="착수계 제출", quote="계약 후 30",
                                          normalized="계약 후 30일 이내 착수계 제출")
    assert _c20_rules(frozen, truncated, relaxed=True) == [["constraint_quote_truncated"]]


def test_c20_v11_text_value_numbers_and_fact_linked_values_stay_exact() -> None:
    text = "계약 후 30일 이내 착수계를 제출"
    frozen, normalized = _c20_text_payload(text, value="30일 내 착수계 제출", quote=text,
                                           normalized="계약 후 30일 이내 착수계 제출")
    assert _c20_rules(frozen, normalized, relaxed=True) == []
    # a number the quote does not write is never accepted in a text value
    frozen, invented = _c20_text_payload(text, value="40일 내 착수계 제출", quote=text,
                                         normalized="계약 후 30일 이내 착수계 제출")
    assert _c20_rules(frozen, invented, relaxed=True) == [["constraint_expression"]]
    # a text value BidOps compares with a company fact (상주 지역·본점 소재지·직접생산 품명) stays verbatim
    branch = "본점 소재지가 서울특별시인 업체"
    frozen, paraphrased = _c20_text_payload(branch, value="서울 본점", quote=branch)
    assert _c20_rules(frozen, paraphrased, relaxed=True) == [["constraint_expression"]]
    frozen, exact = _c20_text_payload(branch, value="서울특별시", quote=branch)
    assert _c20_rules(frozen, exact, relaxed=True) == []


@pytest.mark.parametrize(("text", "kind", "value", "unit_name", "quote"), [
    ("투입 인력 3명 이상", "count", 4, "person", "투입 인력 3명 이상"),        # number not in the quote
    ("유지관리 기간 12개월", "duration", 12, "day", "유지관리 기간 12개월"),  # unit not the quote's
    ("사업예산 200백만원 이하", "amount", 2_000_000, "KRW", "사업예산 200백만원 이하"),
    ("가용률 99% 이상", "percentage", 98, "percent", "가용률 99% 이상"),
    ("2027년 1월 31일까지 납품", "date", "2027-02-01", None, "2027년 1월 31일까지 납품"),
])
def test_c20_v11_numeric_unit_and_date_kinds_keep_the_exact_expression_rule(text, kind, value, unit_name,
                                                                            quote) -> None:
    frozen, payload = _c20_text_payload(text, value=value, quote=quote, kind=kind, unit_name=unit_name,
                                        normalized=text)
    assert _c20_rules(frozen, payload, relaxed=True) == [["constraint_expression"]]
    assert _c20_rules(frozen, payload, relaxed=False) == [["constraint_expression"]]
    # a wrong operator is still constraint_expression under v11
    frozen, wrong = _c20_text_payload("투입 인력 3명 이상", value=3, quote="투입 인력 3명 이상", kind="count",
                                      unit_name="person", normalized="투입 인력 3명 이상")
    wrong["items"][0]["constraints"][0]["operator"] = "lte"
    assert _c20_rules(frozen, wrong, relaxed=True) == [["constraint_expression"]]


def test_c20_mock_answers_role_v3_and_synthesis_v3_with_refs() -> None:
    from app.deep_review.services.card_analysis import stage_prompt
    from app.deep_review.services.card_roles import synthesis_v1_from_v3, validate_verdict_role_v3
    from app.deep_review.services.company_analysis_input import card_role_ref_payload, card_synthesis_ref_payload
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    frozen, extract, compare, inputs = _c19_world()
    client = MockCardAnalysisClient(ONTOLOGY)
    roles = {}
    for role, role_input in inputs.items():
        sent = card_role_ref_payload(role_input.extract.model_dump(mode="json"),
                                     role_input.compare.model_dump(mode="json"))
        value = {"role": role, **sent, "profile_facts": [], "profile_evidence": []}
        answer = client.invoke_prompt(stage_prompt(role, "x", {}, value, repair=False), contract="card-role-v3")
        assert answer.structured_output["schema_version"] == "bidops.verdict-role.v3"
        assert all(row["unit_ref"].startswith("U") for row in answer.structured_output["unit_findings"])
        roles[role] = validate_verdict_role_v3(answer.structured_output, role_input=role_input)
        assert roles[role].isolated_items == []
    synthesis_input = build_synthesis_input(roles)
    sent_roles, catalog = card_synthesis_ref_payload([row.model_dump(mode="json") for row in synthesis_input.roles])
    value = {"roles": sent_roles, "unit_catalog": catalog, "profile_facts": [], "profile_evidence": [],
             "missing_sections": [], "rejected_units": []}
    answer = client.invoke_prompt(stage_prompt("synthesis", "x", {}, value, repair=False), contract="card-synthesis-v3")
    output = answer.structured_output
    assert output["schema_version"] == "bidops.practitioner-verdict.v3" and output["verdict"] == "판단 불가"
    assert output["cautions"] and output["cautions"][0]["unit_ref"] == "U1"
    mapped, isolated = synthesis_v1_from_v3(output, synthesis_input=synthesis_input, extract=extract, compare=compare)
    assert isolated == [] and mapped["cautions"][0]["unit_id"] == frozen.units[4].unit_id
    assert client.calls[-1] == ("card-synthesis-v3", "synthesis")
