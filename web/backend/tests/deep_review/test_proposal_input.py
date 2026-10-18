"""RL-04 STEP-003: per-section frozen input, Luna payload and its guard (spec T1, T9, 입력 예산).

The company comes from two sources, each registered into an isolated SQLite
database and frozen into a ``bidops.company-analysis-input.v2`` exactly as the
RL-03 card-v1 preview does (same path as ``test_verdict_payload_guard``):

* ``synthetic`` -- the committed Rootlab-shaped fixture
  (``tests/fixtures/deep_review/rootlab_synthetic``; synthetic values, same
  node ids/types/statuses as the real file).  Always runs, so T1/T9 never
  skip in CI.
* ``rootlab`` -- the real Rootlab v2 file outside Git
  (``~/orca/fixtures/company/rootlab``); skipped when it is not present.

The verdict side (extract types, compares, verdict) is synthetic stage rows
validated by the RL-03 DTOs.  No model, network or object storage outside the
in-memory fixture is used.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.core.model_binding import canonical_json_bytes
from app.deep_review.contracts import load_schema, validate_payload
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
from app.deep_review.services.input_versions import PROPOSAL_SECTION_KEYS
from app.deep_review.services.proposal_input import (
    PROPOSAL_IDENTITY_KEYS,
    PROPOSAL_TRANSFER_KEYS,
    SECTION_TOC,
    ProposalInputError,
    build_proposal_input,
    check_proposal_transfer_payload,
    notice_meta,
    proposal_input_sha256,
    proposal_transfer_payload,
    require_input_budget,
    verdict_sources,
)
from tests.deep_review.test_card_analysis import _source
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store


SYNTHETIC_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "deep_review" / "rootlab_synthetic"
ROOTLAB_DIR = Path(os.environ.get("BIDOPS_ROOTLAB_FIXTURE_DIR", str(Path.home() / "orca/fixtures/company/rootlab")))
FIXTURES = {
    "synthetic": (SYNTHETIC_DIR / "ontology.json", SYNTHETIC_DIR / "source.json"),
    "rootlab": (ROOTLAB_DIR / "ontology.v2.json", ROOTLAB_DIR / "rootlab.source.v2.json"),
}
#: The proposed credit rating value (D2: never sent).  Both fixtures carry this marker.
CREDIT_MARKER = "BBB0"
POLICY_SHA = "e" * 64
PROPOSAL_POLICY_SHA = "0eb36cf9e4318e447dd2c66f59a060a9ec1d87b92c23326200867060973e7d91"
APPROVAL_ID = uuid4()
SECTION_ID = uuid4()
NOTE_BODY = "노트 본문: 발주처 담당자와 통화함"
NOTICE_ID = 101
OPPORTUNITY_ID = 7


@pytest.fixture(autouse=True)
def real_company_settings(monkeypatch):
    monkeypatch.setenv("BIDOPS_DEMO_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(params=["synthetic", "rootlab"])
def company(request, object_store):  # noqa: F811 - pytest fixture
    ontology_path, source_path = FIXTURES[request.param]
    if not (ontology_path.is_file() and source_path.is_file()):
        pytest.skip(f"{request.param} company fixture is not available")
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    with Session(bind) as session:
        prepared = prepare_company_knowledge(ontology_path.read_bytes(), source_path.read_bytes())
        imported = import_company_knowledge(session, prepared, actor="등록 담당자")
        activate_company_knowledge(session, company_id=imported.company_id,
                                   graph_version_id=imported.graph_version_id, actor="활성 담당자")
        session.flush()
        knowledge = resolve_company_knowledge_context(session, imported.company_id)
        source = json.loads(source_path.read_text(encoding="utf-8"))
        yield SimpleNamespace(name=request.param, knowledge=knowledge, nodes=source["nodes"])
    bind.dispose()


def _frozen(knowledge) -> dict:
    source = _source()
    card = freeze_card_analysis_input(
        select_analysis_units([source], selector_version="card-sections-v3"),
        company_binding=card_company_binding(knowledge),
    )
    bundle = {"documents": [{"document_version_id": str(source["document_version_id"]), "ordinal": 0}]}
    units = card_requirement_units(card, bundle, {str(source["structure_id"]): {"blocks": source["blocks"]}})
    return build_company_analysis_input_v2(
        card_analysis=card.model_dump(mode="json"), purpose="deep_review", execution_nonce=uuid4(),
        knowledge=knowledge, notice_id=NOTICE_ID, document_version_ids=[source["document_version_id"]],
        policy_version_id=uuid4(), policy_sha256=POLICY_SHA, model_name="gpt-6-luna",
        model_revision=None, generation={"reasoning_effort": "high"},
        requirements=requirements_from_source_units(units, knowledge.ontology),
        path_limit_per_requirement=32, profile_characters=8000, bundle_id=uuid4(), target_review_id=None,
    )


def _units_by_role(frozen: dict) -> dict[str, dict]:
    """The six frozen units of ``_source()`` (card-sections-v3) by role."""

    units = frozen["card_analysis"]["units"]
    cards = [row for row in units if row["kind"] == "card"]
    segments = {tuple(row["section_kinds"]): row for row in units if row["kind"] == "segment"}
    return {
        "seg_overview": segments[("overview",)], "seg_schedule": segments[("overview", "schedule")],
        "card_1": cards[0], "card_2": cards[1], "seg_budget": segments[("budget", "evaluation")],
        "seg_eligibility": segments[("eligibility",)],
    }


#: Extract type per unit role (seg_overview has no extract row on purpose).
TYPES = {"seg_schedule": "운영", "card_1": "기능", "card_2": "보안", "seg_budget": "계약", "seg_eligibility": "자격"}
#: Facts each compare references (confirmed, proposed, unknown -- present in both fixtures).
COMPARE_FACTS = {
    "card_1": [("staff:onsite", "met", "confirmed_match"), ("qual:credit_rating", "unknown", "proposed_fact")],
    "card_2": [("staff:pm", "unknown", "unknown_fact"), ("cert:iso_9001", "met", "confirmed_match")],
    "seg_budget": [("pref:solo_cap", "met", "confirmed_match")],
}
EVIDENCE = {"source_sha256": "a" * 64, "block_key": "overview-body", "quote": "홈페이지 사업의 목적"}


def _sources(frozen: dict):
    roles = _units_by_role(frozen)
    extract_items = []
    for role, type_ in TYPES.items():
        unit = roles[role]
        block = unit["blocks"][0]
        extract_items.append({
            "unit_id": unit["unit_id"], "type": type_, "normalized_requirement": f"{role} 요구",
            "mandatory": True, "constraints": [], "concept_candidates": [], "unknowns": [],
            "evidence": [{"source_sha256": unit["source_sha256"], "block_key": block["block_key"],
                          "quote": block["text"] or "본문"}],
        })
    compare_items = []
    for role, facts in COMPARE_FACTS.items():
        compare_items.append({
            "unit_id": roles[role]["unit_id"], "fit_status": "unknown" if any(f[1] == "unknown" for f in facts) else "met",
            "constraint_results": [
                {"constraint_index": index, "status": status, "fact_ids": [key], "path_ids": [], "reason_code": reason}
                for index, (key, status, reason) in enumerate(facts)
            ],
            "evidence_ids": [], "reason_codes": sorted({reason for _key, _status, reason in facts}),
        })
    verdict = {
        "verdict": "조건부 진행", "reason": "상주 인력과 신용등급 확인이 필요하다.",
        "checklist": [{"key": key, "status": "unknown", "evidence_refs": [EVIDENCE]} for key in (
            "qualification_track_record", "staffing_onsite", "amount_period", "technology",
            "operations_sla_security")],
    }
    return verdict_sources(
        attempt_id=uuid4(), notice_id=NOTICE_ID, frozen=frozen, verdict_input_sha256="f" * 64,
        extract_payloads=[{"schema_version": "bidops.requirement-extract.v1", "items": extract_items}],
        compare_payloads=[{"schema_version": "bidops.requirement-compare.v1", "items": compare_items}],
        verdict=verdict,
    )


NOTICE = SimpleNamespace(
    title="합성 누리집 고도화", agency="합성기관", method="협상에 의한 계약",
    deadline_at=datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc), estimated_price=Decimal("134700000.00"),
)


def _input(sources, section_key: str) -> dict:
    return build_proposal_input(
        sources, section_key=section_key, execution_nonce=uuid4(), draft_id=uuid4(),
        opportunity_id=OPPORTUNITY_ID, notice_id=NOTICE_ID, policy_sha256=PROPOSAL_POLICY_SHA,
        notice_meta=notice_meta(NOTICE),
    )


def _text(value) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _statuses(frozen: dict) -> dict[str, str]:
    return {row["fact_key"]: row["status"] for row in frozen["profile_facts"]}


def _ids(rows) -> list[str]:
    return [row["unit_id"] for row in rows]


# --- T1: input assembly ---------------------------------------------------------------------


def test_t1_section_inputs_select_units_and_confirmed_facts_only(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    roles = _units_by_role(frozen)
    statuses = _statuses(frozen)
    fact_order = [row["fact_key"] for row in frozen["profile_facts"]]
    schema = load_schema("proposal-input")
    inputs = {key: _input(sources, key) for key in PROPOSAL_SECTION_KEYS}

    expected_units = {
        "overview": ["seg_overview", "seg_schedule", "seg_budget"],
        "track_record": [],
        "strategy": ["card_1", "card_2"],
        "requirements": ["card_1", "card_2"],
        "operations_sla": ["seg_schedule", "card_2", "seg_budget"],
        "organization": [],
    }
    referenced = {
        "strategy": {"staff:onsite", "qual:credit_rating", "staff:pm", "cert:iso_9001"},
        "requirements": {"staff:onsite", "qual:credit_rating", "staff:pm", "cert:iso_9001"},
        "operations_sla": {"staff:pm", "cert:iso_9001", "pref:solo_cap"},
        "overview": set(),
        "track_record": {key for key in fact_order if key.startswith(("project:", "cert:"))},
        "organization": {key for key in fact_order if key.startswith("staff:")},
    }
    for key, value in inputs.items():
        # exact 20-key frozen input, valid against bidops.proposal-input.v1
        assert set(value) == set(schema["properties"]) == set(PROPOSAL_TRANSFER_KEYS) | set(PROPOSAL_IDENTITY_KEYS)
        validate_payload(value, "proposal-input")
        assert value["section_key"] == key and value["purpose"] == "proposal"
        assert value["toc_reference"] == list(SECTION_TOC[key])
        assert value["company_binding"] == frozen["card_analysis"]["company_binding"]
        assert (value["model_name"], value["reasoning_effort"]) == ("gpt-6-luna", "high")
        assert value["verdict"] == dict(sources.verdict)
        # units are verbatim frozen units, frozen order; compares belong to those units
        assert value["units"] == [roles[role] for role in expected_units[key]]
        assert _ids(value["compares"]) == [roles[role]["unit_id"] for role in expected_units[key]
                                           if role in COMPARE_FACTS]
        # facts: confirmed with value, proposed/unknown as {fact_key, status} only, frozen order
        wanted = referenced[key]
        assert [row["fact_key"] for row in value["company_facts"]] == [
            fact for fact in fact_order if fact in wanted and statuses[fact] == "confirmed"]
        assert [row["fact_key"] for row in value["missing_facts"]] == [
            fact for fact in fact_order if fact in wanted and statuses[fact] != "confirmed"]
        assert all(set(row) == {"fact_key", "type", "label", "value"} for row in value["company_facts"])
        assert all(set(row) == {"fact_key", "status"} for row in value["missing_facts"])
        assert all(row["status"] == statuses[row["fact_key"]] for row in value["missing_facts"])
        assert all(statuses[row["fact_key"]] == "confirmed" for row in value["company_facts"])
        # the proposed credit rating never carries its value; no attachment file name key
        assert CREDIT_MARKER not in _text(value)
        assert "file_name" not in _text(value["company_facts"])
    # input_sha256 is the canonical SHA of the whole input and differs per section
    digests = {proposal_input_sha256(value) for value in inputs.values()}
    assert len(digests) == len(PROPOSAL_SECTION_KEYS)
    # requirements: every card unit; missing proposed credit rating shows as {fact_key, status}
    assert {"fact_key": "qual:credit_rating", "status": "proposed"} in inputs["requirements"]["missing_facts"]
    assert {"fact_key": "staff:pm", "status": "unknown"} in inputs["organization"]["missing_facts"]
    # design/publishing staff is sent with ``available`` (``total`` null), onsite with available+region
    staff = {row["fact_key"]: row["value"] for row in inputs["organization"]["company_facts"]}
    nodes = {node["id"]: node for node in company.nodes}
    for key in ("staff:design_publishing", "staff:onsite", "staff:total"):
        assert staff[key] == {k: v for k, v in nodes[key]["value"].items()}
    assert staff["staff:design_publishing"]["total"] is None
    assert staff["staff:design_publishing"]["available"] == nodes["staff:design_publishing"]["value"]["available"]
    # track record: project label + agency/year values, patents as cert:patents.value.detail
    track = {row["fact_key"]: row for row in inputs["track_record"]["company_facts"]}
    assert track["cert:patents"]["value"]["detail"] == nodes["cert:patents"]["value"]["detail"]
    project = next(row for key, row in track.items() if key.startswith("project:"))
    assert project["label"] == nodes[project["fact_key"]]["label"] and project["value"]["agency"]
    assert "file_name" not in track["cert:patents"]["value"]
    # notice meta strings (KST deadline, integral price without a fraction)
    assert inputs["overview"]["notice_meta"] == {
        "title": "합성 누리집 고도화", "agency": "합성기관", "deadline_at": "2026-11-02T10:00:00+09:00",
        "method": "협상에 의한 계약", "estimated_price": "134700000",
    }


def test_t1_builder_fails_closed_on_mismatch_and_unsupported_status(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    with pytest.raises(ProposalInputError) as error:
        build_proposal_input(sources, section_key="pricing", execution_nonce=uuid4(), draft_id=uuid4(),
                             opportunity_id=OPPORTUNITY_ID, notice_id=NOTICE_ID, policy_sha256=PROPOSAL_POLICY_SHA,
                             notice_meta=notice_meta(NOTICE))
    assert error.value.code == "company_input_invalid"
    with pytest.raises(ProposalInputError):
        build_proposal_input(sources, section_key="overview", execution_nonce=uuid4(), draft_id=uuid4(),
                             opportunity_id=OPPORTUNITY_ID, notice_id=NOTICE_ID + 1,
                             policy_sha256=PROPOSAL_POLICY_SHA, notice_meta=notice_meta(NOTICE))
    with pytest.raises(ProposalInputError):
        build_proposal_input(sources, section_key="overview", execution_nonce=uuid4(), draft_id=uuid4(),
                             opportunity_id=OPPORTUNITY_ID, notice_id=NOTICE_ID, policy_sha256=PROPOSAL_POLICY_SHA,
                             notice_meta={**notice_meta(NOTICE), "demand_agency": "x"})
    # A referenced fact whose status has no proposal form (``inferred``) fails closed.
    changed = deepcopy(frozen)
    for row in changed["profile_facts"]:
        if row["fact_key"] == "staff:pm":
            row["status"] = "inferred"
    for row in changed["graph_nodes"]:
        if row["id"] == "staff:pm":
            row["status"] = "inferred"
    with pytest.raises(ProposalInputError) as error:
        _input(_sources(changed), "requirements")
    assert error.value.code == "company_input_invalid"
    # A compare that references a fact outside the frozen binding fails closed.
    stray = _sources(frozen)
    roles = _units_by_role(frozen)
    stray.compares[roles["card_1"]["unit_id"]]["constraint_results"][0]["fact_ids"] = ["staff:ghost"]
    with pytest.raises(ProposalInputError):
        _input(stray, "requirements")


# --- T9: transfer payload and guard -----------------------------------------------------------


OPERATIONAL = (APPROVAL_ID, SECTION_ID, NOTE_BODY)


def test_t9_payload_is_exactly_the_eight_transfer_keys_and_passes_the_guard(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    for key in PROPOSAL_SECTION_KEYS:
        value = _input(sources, key)
        payload = proposal_transfer_payload(value, sources, operational_values=OPERATIONAL)
        assert list(payload) == list(PROPOSAL_TRANSFER_KEYS)
        assert set(payload) == {"section_key", "notice_meta", "units", "compares", "verdict", "company_facts",
                                "missing_facts", "toc_reference"}
        assert not set(payload) & set(PROPOSAL_IDENTITY_KEYS)
        text = _text(payload)
        for identity in ("execution_nonce", "draft_id", "verdict_attempt_id", "verdict_input_sha256",
                         "policy_sha256"):
            assert value[identity] not in text
        for binding in ("graph_version_id", "graph_sha256", "profile_version_id", "profile_sha256",
                        "ontology_sha256"):
            assert value["company_binding"][binding] not in text
        for operational in OPERATIONAL:
            assert str(operational) not in text
        assert CREDIT_MARKER not in text and "gpt-6-luna" not in text and POLICY_SHA not in text
        for word in ('"note"', '"notes"', '"note_body"', '"approval_id"', '"daily_cap"'):
            assert word not in text


def _tamper(value: dict, mutate) -> tuple[dict, dict]:
    """Apply ``mutate`` to a copy of the frozen input and return (payload, input) from the copy."""

    changed = deepcopy(value)
    mutate(changed)
    return {key: deepcopy(changed[key]) for key in PROPOSAL_TRANSFER_KEYS if key in changed}, changed


def test_t9_guard_rejects_every_tamper_before_any_call(company) -> None:
    frozen = _frozen(company.knowledge)
    sources = _sources(frozen)
    requirements = _input(sources, "requirements")
    organization = _input(sources, "organization")
    credit_detail = next(row["value"]["detail"] for row in frozen["profile_facts"]
                         if row["fact_key"] == "qual:credit_rating")
    staff_total = next(row for row in organization["company_facts"] if row["fact_key"] == "staff:total")

    def payload_only(mutate):
        payload = {key: deepcopy(requirements[key]) for key in PROPOSAL_TRANSFER_KEYS}
        mutate(payload)
        return payload, requirements

    cases = {
        # top-level key set
        "identity key added": payload_only(lambda p: p.__setitem__("draft_id", requirements["draft_id"])),
        "policy sha added": payload_only(lambda p: p.__setitem__("policy_sha256", PROPOSAL_POLICY_SHA)),
        "key missing": payload_only(lambda p: p.pop("toc_reference")),
        "payload differs from input": payload_only(lambda p: p["units"].pop()),
        # proposed/unknown value or label smuggled into missing_facts / company_facts
        "missing fact value": _tamper(requirements, lambda v: v["missing_facts"][0].__setitem__("value", credit_detail)),
        "missing fact label": _tamper(requirements, lambda v: v["missing_facts"][0].__setitem__("label", "신용등급")),
        "proposed fact as company fact": _tamper(requirements, lambda v: v["company_facts"].append({
            "fact_key": "qual:credit_rating", "type": "qualification", "label": "신용평가등급",
            "value": {"held": True, "detail": credit_detail}})),
        "unreferenced confirmed fact": _tamper(requirements, lambda v: v["company_facts"].append(staff_total)),
        "confirmed value changed": _tamper(organization, lambda v: v["company_facts"][0].__setitem__(
            "value", {"total": 999})),
        # notice units: altered text, unit of another section, dropped card unit
        "unit text altered": _tamper(requirements, lambda v: v["units"][0]["blocks"][0].__setitem__("text", "변조")),
        "foreign unit added": _tamper(requirements, lambda v: v["units"].append(
            _units_by_role(frozen)["seg_eligibility"])),
        "card unit dropped": _tamper(requirements, lambda v: (v["units"].pop(), v["compares"].pop())),
        "compare altered": _tamper(requirements, lambda v: v["compares"][0].__setitem__("fit_status", "met")),
        "verdict altered": _tamper(requirements, lambda v: v["verdict"].__setitem__("verdict", "진행 가능")),
        "toc altered": _tamper(requirements, lambda v: v["toc_reference"].__setitem__(0, "Ⅱ-1 일반현황")),
        "section swapped": _tamper(requirements, lambda v: v.__setitem__("section_key", "strategy")),
        # notes / withheld / identity text inside an otherwise free field
        "note text in title": _tamper(requirements, lambda v: v["notice_meta"].__setitem__("title", NOTE_BODY)),
        "withheld value in title": _tamper(requirements, lambda v: v["notice_meta"].__setitem__("title", credit_detail)),
        "policy sha in title": _tamper(requirements, lambda v: v["notice_meta"].__setitem__("title", POLICY_SHA)),
        "binding id in method": _tamper(requirements, lambda v: v["notice_meta"].__setitem__(
            "method", v["company_binding"]["graph_version_id"])),
        "model name in agency": _tamper(requirements, lambda v: v["notice_meta"].__setitem__("agency", "gpt-6-luna")),
        # frozen identity that disagrees with the verdict sources
        "other verdict attempt": _tamper(requirements, lambda v: v.__setitem__("verdict_attempt_id", str(uuid4()))),
        "other binding": _tamper(requirements, lambda v: v["company_binding"].__setitem__("graph_sha256", "0" * 64)),
        "input extra key": _tamper(requirements, lambda v: v.__setitem__("notes", NOTE_BODY)),
    }
    for name, (payload, value) in cases.items():
        with pytest.raises(ProposalInputError) as error:
            check_proposal_transfer_payload(payload, value, sources, operational_values=OPERATIONAL)
        assert error.value.code == "company_input_invalid", name
    # An operational value (approval id, section id, note body) found in the payload fails closed.
    leaked, value = _tamper(requirements, lambda v: v["notice_meta"].__setitem__("title", str(APPROVAL_ID)))
    with pytest.raises(ProposalInputError):
        check_proposal_transfer_payload(leaked, value, sources, operational_values=OPERATIONAL)
    # The untouched payload still passes (the cases above did not mutate the originals).
    check_proposal_transfer_payload({key: requirements[key] for key in PROPOSAL_TRANSFER_KEYS}, requirements,
                                    sources, operational_values=OPERATIONAL)


# --- 입력 예산 -------------------------------------------------------------------------------------


def test_input_budget_is_120000_characters_and_never_split() -> None:
    require_input_budget("가" * 120000)
    for prompt in ("가" * 120001, None, b"x"):
        with pytest.raises(ProposalInputError) as error:
            require_input_budget(prompt)
        assert error.value.code == "input_budget_exceeded"


def test_synthetic_fixture_mirrors_the_rootlab_shape() -> None:
    """The committed fixture keeps the node ids/statuses the RL-04 tests rely on (synthetic values only)."""

    source = json.loads((SYNTHETIC_DIR / "source.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in source["nodes"]}
    assert source["company"]["is_fictional"] is False
    assert nodes["qual:credit_rating"]["status"] == "proposed"
    assert nodes["qual:credit_rating"]["origin"] == "agent_proposal"
    assert CREDIT_MARKER in nodes["qual:credit_rating"]["value"]["detail"]
    assert nodes["staff:design_publishing"]["value"]["total"] is None
    assert nodes["staff:pm"]["status"] == "unknown" and nodes["project:certified_list"]["status"] == "unknown"
    assert {key for key in nodes if key.startswith(("project:", "cert:", "staff:"))} >= {
        "project:2025-01", "cert:patents", "staff:total", "staff:onsite"}
