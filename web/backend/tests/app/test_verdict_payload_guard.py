"""RL-03 transfer payload rule (spec "전송 payload 규칙", D2) and the v2 card input (T9).

The real Rootlab v2 company file (``~/orca/fixtures/company/rootlab``, outside
Git) is imported into an isolated SQLite database and frozen into a
``bidops.company-analysis-input.v2`` exactly as the card-v1 preview does.  Each
stage payload built from that frozen input is then checked strictly:

(a) every ``confirmed`` fact is projected with its value (``pref:*``
    conditions included), but a role/synthesis payload carries only the
    facts its compare rows reference -- never an unreferenced fact
    (2026-10-17 결정 B11);
(b) ``proposed``/``unknown`` entries are exactly ``{fact_key, status}`` and the
    ``qual:credit_rating`` value (``BBB0``) appears nowhere; the extract
    ontology rows are ``{id, label, aliases}`` (결정 B10);
(c) notes, approval id, cap, policy/model identity and binding version/sha
    are absent;
(d) notice units are only the frozen card + six-section segment units;
(e) top-level key sets are exact; violations fail closed with
    ``company_input_invalid`` before any call.

No model, network or object storage outside the in-memory fixture is used.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import os
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.core.model_binding import canonical_json_bytes
from app.deep_review.schemas.company_analysis import (
    CompanyAnalysisInputV2,
    FrozenProvenance,
    validate_company_analysis_input,
)
from app.deep_review.services.card_units import (
    card_company_binding,
    card_requirement_units,
    freeze_card_analysis_input,
    select_analysis_units,
)
from app.deep_review.services.company_analysis_input import (
    CARD_TRANSFER_STAGE_KEYS,
    COMPANY_ANALYSIS_INPUT_V2_KEYS,
    CompanyAnalysisError,
    build_company_analysis_input,
    build_company_analysis_input_v2,
    CARD_COMPARE_FACT_PATHS,
    card_company_transfer,
    card_extract_transfer,
    card_fact_value,
    card_referenced_fact_keys,
    card_role_transfer,
    card_synthesis_transfer,
    check_card_transfer_payload,
    frozen_provenance,
    resolve_company_knowledge_context,
)
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
)
from app.deep_review.services.company_knowledge_retrieval import (
    CompanyRetrievalError,
    build_company_retrieval,
    requirements_from_source_units,
)
from tests.deep_review.test_card_analysis import _source
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store


ROOTLAB_DIR = Path(os.environ.get("BIDOPS_ROOTLAB_FIXTURE_DIR", str(Path.home() / "orca/fixtures/company/rootlab")))
ROOTLAB_SOURCE = ROOTLAB_DIR / "rootlab.source.v2.json"
ROOTLAB_ONTOLOGY = ROOTLAB_DIR / "ontology.v2.json"

pytestmark = pytest.mark.skipif(
    not (ROOTLAB_SOURCE.is_file() and ROOTLAB_ONTOLOGY.is_file()),
    reason="Rootlab v2 fixture (outside Git) is not available",
)

POLICY_VERSION_ID = uuid4()
POLICY_SHA = "e" * 64
APPROVAL_ID = uuid4()
ATTEMPT_ID = uuid4()
REVIEW_ID = uuid4()
NOTE_BODY = "노트 본문: 발주처 담당자와 통화함"
GENERATION = {"reasoning_effort": "high"}


@pytest.fixture(autouse=True)
def real_company_settings(monkeypatch):
    monkeypatch.setenv("BIDOPS_DEMO_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _rootlab_nodes() -> list[dict]:
    return json.loads(ROOTLAB_SOURCE.read_text(encoding="utf-8"))["nodes"]


@pytest.fixture
def knowledge():
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    with Session(bind) as session:
        prepared = prepare_company_knowledge(ROOTLAB_ONTOLOGY.read_bytes(), ROOTLAB_SOURCE.read_bytes())
        imported = import_company_knowledge(session, prepared, actor="등록 담당자")
        activate_company_knowledge(
            session, company_id=imported.company_id, graph_version_id=imported.graph_version_id,
            actor="활성 담당자",
        )
        session.flush()
        yield resolve_company_knowledge_context(session, imported.company_id)
    bind.dispose()


def _frozen(knowledge, *, source=None, selector_version: str = "card-sections-v1") -> dict:
    source = source or _source()
    card = freeze_card_analysis_input(
        select_analysis_units([source], selector_version=selector_version),
        company_binding=card_company_binding(knowledge),
    )
    bundle = {"documents": [{"document_version_id": str(source["document_version_id"]), "ordinal": 0}]}
    units = card_requirement_units(card, bundle, {str(source["structure_id"]): {"blocks": source["blocks"]}})
    return build_company_analysis_input_v2(
        card_analysis=card.model_dump(mode="json"), purpose="deep_review", execution_nonce=uuid4(),
        knowledge=knowledge, notice_id=101, document_version_ids=[source["document_version_id"]],
        policy_version_id=POLICY_VERSION_ID, policy_sha256=POLICY_SHA, model_name="gpt-6-luna",
        model_revision=None, generation=GENERATION,
        requirements=requirements_from_source_units(units, knowledge.ontology),
        path_limit_per_requirement=32, profile_characters=8000, bundle_id=uuid4(), target_review_id=None,
    )


def _text(value) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _role_parts() -> tuple[dict, dict]:
    # STEP-005 supplies validated extract/compare rows; the guard only needs their shape.
    # Referenced facts: qual:credit_rating (proposed), staff:onsite (confirmed), staff:pm (unknown).
    extract = {"items": [{
        "unit_id": "u-1", "type": "자격", "normalized_requirement": "신용평가등급 BB 이상",
        "mandatory": True, "constraints": [{
            "kind": "text", "value": "BB 이상", "unit": None, "operator": "unknown",
            "fact_key": "qual:credit_rating", "quote": "신용평가등급 BB 이상",
            "locator": {"source_sha256": "a" * 64, "block_key": "eligibility-body"},
        }],
        "concept_candidates": [], "unknowns": [],
        "evidence": [{"source_sha256": "a" * 64, "block_key": "eligibility-body", "quote": "참가 자격"}],
    }]}
    compare = {"items": [{
        "unit_id": "u-1", "fit_status": "unknown", "evidence_ids": [],
        "constraint_results": [{"constraint_index": 0, "status": "unknown", "fact_ids": ["qual:credit_rating"],
                                "path_ids": [], "reason_code": "proposed_fact"}],
        "reason_codes": ["proposed_fact"],
    }, {
        "unit_id": "u-2", "fit_status": "unknown", "evidence_ids": [],
        "constraint_results": [
            {"constraint_index": 0, "status": "met", "fact_ids": ["staff:onsite"], "path_ids": [],
             "reason_code": "confirmed_match"},
            {"constraint_index": 1, "status": "unknown", "fact_ids": ["staff:pm"], "path_ids": [],
             "reason_code": "unknown_fact"},
        ],
        "reason_codes": ["unknown_fact", "confirmed_match"],
    }]}
    return extract, compare


REFERENCED = ["qual:credit_rating", "staff:onsite", "staff:pm"]


OPERATIONAL = (APPROVAL_ID, ATTEMPT_ID, REVIEW_ID, NOTE_BODY)


def _stage_payloads(frozen: dict, knowledge) -> dict[str, dict]:
    extract, compare = _role_parts()
    role = card_role_transfer(frozen, role="eligibility_economics", extract=extract, compare=compare,
                              operational_values=OPERATIONAL)
    return {
        "extract": card_extract_transfer(frozen, 0, knowledge.ontology, operational_values=OPERATIONAL),
        "role": role,
        "synthesis": card_synthesis_transfer(
            frozen, roles=[{"role": "eligibility_economics", "unit_findings": [], "cautions": [],
                            "evidence_refs": []}],
            fact_keys=card_referenced_fact_keys(compare), operational_values=OPERATIONAL,
        ),
    }


# --- v2 input --------------------------------------------------------------------------


def test_t9_v2_input_has_exact_keys_null_overview_and_every_binding_fact(knowledge) -> None:
    frozen = _frozen(knowledge)
    assert set(frozen) == COMPANY_ANALYSIS_INPUT_V2_KEYS
    assert frozen["schema_version"] == "bidops.company-analysis-input.v2"
    assert frozen["overview_run_id"] is None and frozen["overview_sha256"] is None
    assert frozen["card_analysis"]["company_binding"]["ontology_sha256"] == frozen["ontology_sha256"]
    fact_nodes = {node["id"] for node in _rootlab_nodes() if node["type"] != "evidence"}
    assert {row["fact_key"] for row in frozen["profile_facts"]} == fact_nodes
    assert frozen["coverage"]["excluded_fact_keys"] == []
    # origins are preserved (RL-00 7 values), never rewritten to fictional_scenario
    origins = {row["fact_key"]: row["origin"] for row in frozen["profile_facts"]}
    assert origins["staff:total"] == "company_brochure"
    assert origins["qual:credit_rating"] == "agent_proposal"
    assert origins["company:rootlab"] == "homepage"
    evidence_origin = {row["fact_key"]: row["origin"] for row in frozen["profile_evidence"]}
    assert evidence_origin["staff:total"] == "company_brochure"
    assert "fictional_scenario" not in _text(frozen)
    validate_company_analysis_input(frozen)
    provenance = frozen_provenance(frozen, input_sha256="f" * 64, documents=[{
        "document_version_id": frozen["document_version_ids"][0], "source_sha256": "a" * 64,
    }])
    assert provenance["overview_run_id"] is None and provenance["overview_sha256"] is None
    FrozenProvenance.model_validate(provenance)


def test_t9_overview_fields_are_both_null_or_both_set(knowledge) -> None:
    frozen = _frozen(knowledge)
    with pytest.raises(ValueError):
        validate_company_analysis_input({**frozen, "overview_run_id": str(uuid4())})
    both = {**frozen, "overview_run_id": str(uuid4()), "overview_sha256": "1" * 64}
    assert isinstance(validate_company_analysis_input(both), CompanyAnalysisInputV2)
    base = {
        "input_sha256": "f" * 64, "purpose": "deep_review", "company_id": str(uuid4()),
        "profile_version_id": str(uuid4()), "profile_sha256": "1" * 64, "graph_version_id": str(uuid4()),
        "graph_sha256": "2" * 64, "ontology_version": "o", "ontology_sha256": "3" * 64,
        "documents": [{"document_version_id": str(uuid4()), "source_sha256": "4" * 64}],
        "overview_run_id": None, "overview_sha256": None, "bundle_id": None,
        "policy_version_id": str(uuid4()), "policy_sha256": "5" * 64, "model_name": "m",
        "model_revision": None, "generation_config_sha256": "6" * 64,
    }
    FrozenProvenance.model_validate(base)
    with pytest.raises(ValidationError):
        FrozenProvenance.model_validate({**base, "overview_run_id": str(uuid4())})
    with pytest.raises(ValidationError):
        FrozenProvenance.model_validate({**base, "overview_sha256": "7" * 64})
    with pytest.raises(ValidationError):  # a company-fit input always has its overview
        FrozenProvenance.model_validate({**base, "purpose": "company_fit"})
    assert set(FrozenProvenance.model_fields) == set(base)


def test_t9_v1_input_still_rejects_a_null_overview(knowledge) -> None:
    frozen = _frozen(knowledge)
    common = dict(
        purpose="deep_review", execution_nonce=uuid4(), knowledge=knowledge, notice_id=101,
        document_version_ids=[UUID(frozen["document_version_ids"][0])], policy_version_id=POLICY_VERSION_ID,
        policy_sha256=POLICY_SHA, model_name="gpt-6-luna", model_revision=None, generation=GENERATION,
        requirements=frozen["requirements"], path_limit_per_requirement=32, profile_characters=8000,
    )
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        build_company_analysis_input(overview_run_id=None, overview_sha256=None, **common)
    with pytest.raises(ValueError):
        validate_company_analysis_input({**frozen, "schema_version": "bidops.company-analysis-input.v1"})


def test_t9_v2_rejects_a_card_binding_of_another_company_version(knowledge) -> None:
    frozen = _frozen(knowledge)
    tampered = deepcopy(frozen)
    tampered["card_analysis"]["company_binding"]["graph_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_company_analysis_input(tampered)


# --- (a)~(e) stage payloads ------------------------------------------------------------


def test_t9_confirmed_facts_are_projected_with_values_and_others_only_as_key_and_status(knowledge) -> None:
    frozen = _frozen(knowledge)
    # every fact referenced: the per-fact projection rule over the whole binding
    company = card_company_transfer(frozen, [row["fact_key"] for row in frozen["profile_facts"]])
    by_key = {row["fact_key"]: row for row in company["profile_facts"]}
    nodes = [node for node in _rootlab_nodes() if node["type"] != "evidence"]
    confirmed = [node for node in nodes if node["status"] == "confirmed"]
    others = [node for node in nodes if node["status"] != "confirmed"]
    assert len(confirmed) == 126 and len(others) == 22  # fixture state (D13: unknown 21 + proposed 1)
    for node in confirmed:  # (a)
        value = node["value"]
        if isinstance(value, dict):
            # prompt-sensitive metadata keys (``file_name``) never enter a prompt; nothing else changes
            value = {key: item for key, item in value.items() if key != "file_name"}
        assert by_key[node["id"]] == {
            "fact_key": node["id"], "type": node["type"], "label": node["label"], "status": "confirmed",
            "origin": node["origin"], "value": value,
        }
    assert by_key["qual:branch"]["value"] == {
        "held": True, "detail": "대구(본점), 세종", "valid_until": None, "issued_on": None,
    }
    for key in ("pref:solo_cap", "pref:consortium", "pref:subcontract", "pref:amount_range"):
        assert by_key[key]["value"]["params"]
    assert by_key["pref:solo_cap"]["value"]["params"] == {"krw": 1500000000}
    assert by_key["staff:total"]["value"]["total"] == 58
    assert by_key["qual:branch"]["value"]["detail"] == "대구(본점), 세종"
    assert by_key["staff:design_publishing"]["value"]["available"] == 5
    for node in others:  # (b)
        assert by_key[node["id"]] == {"fact_key": node["id"], "status": node["status"]}
    assert by_key["qual:credit_rating"] == {"fact_key": "qual:credit_rating", "status": "proposed"}
    confirmed_keys = {node["id"] for node in confirmed}
    assert company["profile_evidence"]
    assert all(set(row) == {"profile_evidence_id", "fact_key", "quote"} for row in company["profile_evidence"])
    assert {row["fact_key"] for row in company["profile_evidence"]} <= confirmed_keys


def test_t9_every_stage_payload_is_strict(knowledge) -> None:
    frozen = _frozen(knowledge)
    payloads = _stage_payloads(frozen, knowledge)
    for stage, payload in payloads.items():
        assert set(payload) == CARD_TRANSFER_STAGE_KEYS[stage]  # (e)
        text = _text(payload)
        assert "BBB0" not in text and "신용평가등급·창업기업 여부" not in text  # (b)
        for value in (
            frozen["policy_version_id"], frozen["policy_sha256"], frozen["generation_config_sha256"],
            frozen["graph_version_id"], frozen["graph_sha256"], frozen["profile_version_id"],
            frozen["profile_sha256"], frozen["ontology_sha256"], frozen["company_id"],
            frozen["execution_nonce"], frozen["bundle_id"], "gpt-6-luna",
            str(APPROVAL_ID), str(ATTEMPT_ID), str(REVIEW_ID), NOTE_BODY,
        ):
            assert value not in text  # (c)
        for key in ("policy_version_id", "policy_sha256", "model_name", "model_revision",
                    "generation_config_sha256", "daily_cap", "approval_id", "today_used",
                    "graph_sha256", "profile_sha256", "note"):
            assert f'"{key}"' not in text
    extract = payloads["extract"]  # (d)
    batch = frozen["card_analysis"]["batches"][0]
    units = {row["unit_id"]: row for row in frozen["card_analysis"]["units"]}
    assert extract["batch"] == batch
    assert extract["units"] == [units[unit_id] for unit_id in batch["unit_ids"]]
    assert {row["kind"] for row in extract["units"]} <= {"card", "segment"}
    labels = {concept.id: concept.label for concept in knowledge.ontology.concepts}
    assert all(set(row) == {"id", "label", "aliases"} for row in extract["ontology"])  # B10
    assert all(row["label"] == labels[row["id"]] for row in extract["ontology"])
    assert "profile_facts" not in extract and "credit" not in _text(extract["units"])
    for stage in ("role", "synthesis"):
        assert payloads[stage]["profile_facts"] == card_company_transfer(frozen, REFERENCED)["profile_facts"]


def test_b11_role_and_synthesis_send_exactly_the_referenced_facts(knowledge) -> None:
    frozen = _frozen(knowledge)
    payloads = _stage_payloads(frozen, knowledge)
    onsite = next(row for row in frozen["profile_facts"] if row["fact_key"] == "staff:onsite")
    node = next(row for row in knowledge.graph_nodes if row["id"] == "staff:onsite")
    for stage in ("role", "synthesis"):
        payload = payloads[stage]
        assert payload["profile_facts"] == [
            {"fact_key": "qual:credit_rating", "status": "proposed"},
            {"fact_key": "staff:onsite", "type": node["type"], "label": node["label"], "status": "confirmed",
             "origin": onsite["origin"], "value": onsite["value"]},
            {"fact_key": "staff:pm", "status": "unknown"},
        ]
        assert {row["fact_key"] for row in payload["profile_evidence"]} == {"staff:onsite"}
        text = _text(payload)
        for unreferenced in ("pref:solo_cap", "qual:branch", "staff:total", "대구(본점), 세종"):
            assert unreferenced not in text
    # no reference → no company fact at all; the proposed credit rating appears only when referenced
    plain = card_role_transfer(frozen, role="technical_fit", extract={"items": []}, compare={"items": []})
    assert plain["profile_facts"] == [] and plain["profile_evidence"] == []
    assert "qual:credit_rating" not in _text(plain)
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("synthesis", payloads["synthesis"], frozen)  # union must be given
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("role", payloads["role"], frozen, fact_keys=["staff:onsite"])
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        card_company_transfer(frozen, ["staff:not-registered"])


@pytest.mark.parametrize("case", [
    "proposed_value", "unknown_label", "proposed_evidence", "forbidden_key", "note_key",
    "operational_value", "policy_sha_value", "extra_top_key", "missing_confirmed", "foreign_unit",
    "withheld_node_value", "sensitive_key_sent", "unreferenced_confirmed", "ontology_without_label",
])
def test_t9_violations_fail_closed_with_company_input_invalid(knowledge, case) -> None:
    frozen = _frozen(knowledge)
    payloads = _stage_payloads(frozen, knowledge)
    stage = "extract" if case in {"foreign_unit", "ontology_without_label"} else "role"
    payload = deepcopy(payloads[stage])
    operational: tuple = ()
    if case == "proposed_value":
        row = next(item for item in payload["profile_facts"] if item["fact_key"] == "qual:credit_rating")
        row["value"] = {"detail": "BBB0"}
    elif case == "unknown_label":
        row = next(item for item in payload["profile_facts"] if item["status"] == "unknown")
        row["label"] = "라벨"
    elif case == "proposed_evidence":
        payload["profile_evidence"].append(
            {"profile_evidence_id": str(uuid4()), "fact_key": "qual:credit_rating", "quote": "BBB0 수준"}
        )
    elif case == "forbidden_key":
        payload["compare"]["items"][0]["policy_sha256"] = POLICY_SHA
    elif case == "note_key":
        payload["extract"]["note"] = NOTE_BODY
    elif case == "operational_value":
        payload["compare"]["items"][0]["unit_id"] = str(APPROVAL_ID)
        operational = (APPROVAL_ID,)
    elif case == "policy_sha_value":
        payload["compare"]["items"][0]["reason_codes"] = [frozen["policy_sha256"]]
    elif case == "extra_top_key":
        payload["company_binding"] = frozen["card_analysis"]["company_binding"]
    elif case == "missing_confirmed":
        payload["profile_facts"] = [row for row in payload["profile_facts"] if row["fact_key"] != "staff:onsite"]
    elif case == "unreferenced_confirmed":
        payload["profile_facts"].append(
            card_company_transfer(frozen, ["pref:solo_cap"])["profile_facts"][0])
    elif case == "ontology_without_label":
        payload["ontology"] = [{"id": row["id"], "aliases": row["aliases"]} for row in payload["ontology"]]
    elif case == "foreign_unit":
        payload["units"][0] = {**payload["units"][0], "blocks": [{"block_key": "x", "text": "다른 원문"}]}
    elif case == "sensitive_key_sent":
        row = next(item for item in payload["profile_facts"] if item["fact_key"] == "staff:onsite")
        row["value"]["file_name"] = None
    elif case == "withheld_node_value":
        payload["compare"]["items"][0]["node"] = {"id": "qual:credit_rating", "status": "proposed", "value": 1}
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload(stage, payload, frozen, operational_values=operational)


def test_t9_the_guard_rejects_a_frozen_input_that_is_not_v2(knowledge) -> None:
    frozen = _frozen(knowledge)
    legacy = {key: value for key, value in frozen.items() if key != "card_analysis"}
    with pytest.raises(CompanyAnalysisError):
        card_company_transfer({**legacy, "schema_version": "bidops.company-analysis-input.v1"}, [])


# --- retrieval: proposed status and origin preservation --------------------------------


def test_retrieval_accepts_proposed_and_rejects_an_unknown_origin(knowledge) -> None:
    frozen = _frozen(knowledge)
    common = dict(
        # The budgeted (narrative) mode needs room for every required qualification/unknown fact.
        ontology=knowledge.ontology, profile=knowledge.profile_context, path_limit_per_requirement=32,
        profile_budget=200_000,
    )
    retrieval = build_company_retrieval(
        frozen["requirements"], graph_nodes=knowledge.graph_nodes, graph_edges=knowledge.graph_edges, **common,
    )
    statuses = {row["status"] for row in retrieval["profile_facts"]}
    assert "proposed" in statuses  # qualification facts are always selected
    nodes = [dict(node) for node in knowledge.graph_nodes]
    nodes[0]["origin"] = "made_up_origin"
    with pytest.raises(CompanyRetrievalError):
        build_company_retrieval(frozen["requirements"], graph_nodes=nodes, graph_edges=knowledge.graph_edges, **common)


# --- compare allowlist value paths (read by STEP-005) ----------------------------------


def test_allowlisted_fact_paths_read_the_rootlab_v2_shapes(knowledge) -> None:
    frozen = _frozen(knowledge)

    def read(key, *path):
        reading = card_fact_value(frozen, key, path)
        return reading.state, reading.value

    assert read("qual:branch", "detail") == ("confirmed", "대구(본점), 세종")
    assert read("staff:design_publishing", "available") == ("confirmed", 5)
    assert read("staff:total", "total") == ("confirmed", 58)
    assert read("staff:onsite", "available") == ("confirmed", 6)
    assert read("staff:onsite", "region") == ("confirmed", "대구")
    assert read("qual:direct_production", "held") == ("confirmed", True)
    assert read("qual:direct_production", "detail") == ("null", None)  # item names unknown
    assert read("qual:sme_certificate", "valid_until") == ("null", None)
    assert read("qual:infosec_cert", "detail") == ("null", None)  # ISMS vs ISMS-P unknown
    assert read("qual:credit_rating", "detail") == ("proposed", None)  # never the BBB0 value
    assert read("qual:sanction_free", "held") == ("confirmed", True)
    assert read("pref:solo_cap", "params", "krw") == ("confirmed", 1500000000)
    assert read("pref:subcontract", "params", "allowed") == ("confirmed", True)
    assert read("pref:consortium", "params") == ("confirmed", {"over_krw": 1000000000, "over_onsite_count": 8})
    # outside the allowlist (bonus/information items, other paths, sums) is refused
    for key, path in (("qual:social_enterprise", ("held",)), ("qual:staff_certifications", ("held",)),
                      ("staff:design_publishing", ("total",)), ("qual:branch", ("held",)), ("staff:dev", ("total",))):
        with pytest.raises(CompanyAnalysisError):
            card_fact_value(frozen, key, path)
    assert "staff:dev" not in CARD_COMPARE_FACT_PATHS


# --- 결정 B24: v2 synthesis payload carries missing_sections; v1 does not ------------------


def _synthesis_payload(frozen: dict) -> dict:
    _extract, compare = _role_parts()
    return card_synthesis_transfer(
        frozen, roles=[{"role": "eligibility_economics", "unit_findings": [], "cautions": [], "evidence_refs": []}],
        fact_keys=card_referenced_fact_keys(compare), operational_values=OPERATIONAL,
    )


def test_b24_v2_synthesis_payload_has_exactly_the_frozen_missing_sections(knowledge) -> None:
    from app.deep_review.services.company_analysis_input import card_synthesis_missing_sections

    frozen = _frozen(knowledge, selector_version="card-sections-v2")
    assert frozen["card_analysis"]["missing_sections"] == ["contract"]
    payload = _synthesis_payload(frozen)
    assert set(payload) == CARD_TRANSFER_STAGE_KEYS["synthesis"] | {"missing_sections"}
    assert payload["missing_sections"] == ["contract"] == card_synthesis_missing_sections(frozen)
    fact_keys = card_referenced_fact_keys(_role_parts()[1])
    for tampered in ([], ["contract", "budget"], None):
        changed = {**payload, "missing_sections": tampered}
        with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
            check_card_transfer_payload("synthesis", changed, frozen, fact_keys=fact_keys)
    without = {key: value for key, value in payload.items() if key != "missing_sections"}
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("synthesis", without, frozen, fact_keys=fact_keys)
    # role and extract payloads of a v2 input do not change
    roles = _stage_payloads(frozen, knowledge)
    assert set(roles["role"]) == CARD_TRANSFER_STAGE_KEYS["role"]
    assert set(roles["extract"]) == CARD_TRANSFER_STAGE_KEYS["extract"]


def test_b24_v2_synthesis_payload_sends_an_empty_list_when_nothing_is_missing(knowledge) -> None:
    source = _source()
    source["blocks"].append({
        "block_key": "contract-heading", "parent_block_key": None, "type": "paragraph", "page": 2, "bbox": None,
        "text": "제4장 계약조건", "confidence": None, "attributes": {},
    })
    source["segments"].append({
        "segment_id": uuid4(), "ordinal": 5, "start_locator": {"ordinal": 99, "block_key": "contract-heading"},
        "source_block_keys": ["contract-heading"], "page_range": None, "mapping_status": "unavailable",
    })
    frozen = _frozen(knowledge, source=source, selector_version="card-sections-v2")
    assert frozen["card_analysis"]["missing_sections"] == []
    assert _synthesis_payload(frozen)["missing_sections"] == []


def test_b24_v1_synthesis_payload_has_no_missing_sections_key(knowledge) -> None:
    frozen = _frozen(knowledge)
    assert frozen["card_analysis"]["selector"]["version"] == "card-sections-v1"
    payload = _synthesis_payload(frozen)
    assert set(payload) == CARD_TRANSFER_STAGE_KEYS["synthesis"] == {"roles", "profile_facts", "profile_evidence"}
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("synthesis", {**payload, "missing_sections": ["contract"]}, frozen,
                                    fact_keys=card_referenced_fact_keys(_role_parts()[1]))


# --- 결정 B30: v3 extract payload carries deterministic expected concepts per unit -------
#
# Offline replay of the T12 4차 rejection (attempt 6dd54a57…, extract batch 0).  The
# source below is a sanitized excerpt of the frozen Polytech units (public RFP text,
# shortened): a table of contents without page numbers, the overview/background/
# schedule segments and the MPR-001 card.  The real answer failed the unchanged
# validator because (1) it skipped the three title-only TOC units and split units,
# (2) it mapped concepts by meaning (``rl.domain.02`` via "홈페이지·포털·CMS 구축·운영",
# ``cap.vulnerability`` via "웹 취약점") and missed exact matches, (3) it wrote the
# year "2027" as a date, and (4) it counted servers as persons, twice.

PT_SHA = "8b6cbf1a7da6f242dae0a1a90b2513513178667a7fc2343e93cbcf6318005a1e"
PT_TOC = [
    ("paragraph-1-19", "목    차"), ("paragraph-1-20", ""), ("paragraph-1-21", "Ⅰ. 사업개요"),
    ("paragraph-1-22", "1. 사업개요"), ("paragraph-1-23", "2. 추진배경 및 필요성"),
    ("paragraph-1-24", "3. 사업내용"), ("paragraph-1-25", "4. 추진일정"), ("paragraph-1-26", "5. 기대효과"),
    ("paragraph-1-27", ""),
]
PT_BODY = [
    ("paragraph-1-72", "Ⅰ사업개요"),
    ("paragraph-1-73", "1. 사업개요"),
    ("paragraph-1-74", " 사 업 명: 2027년 홈페이지 유지관리 용역사업"),
    ("paragraph-1-75", " 사업기간: 2027. 1. 1. ~ 12. 31.(12개월)"),
    ("paragraph-1-83", "2. 추진배경 및 필요성"),
    ("paragraph-1-84", " 홈페이지의 안정적·효율적인 운영관리를 통한 홈페이지 방문자 대상 양질의 서비스 제공"),
    ("paragraph-1-85", "「개인정보 보호법」, 국가정보원「국가 정보보안 기본지침」등을 준수하고 웹 취약점을 보완"),
    ("paragraph-1-86", " 웹 접근성 인증마크를 취득하여 장애인‧고령자 등 정보소외계층이 웹사이트를 이용"),
    ("paragraph-1-87", " 홈페이지 운영 업무를 안정적으로 지원하기 위한 유지보수 체계 마련"),
    ("paragraph-1-115", "4. 추진일정"),
    ("paragraph-1-116", "내용2027년123456789101112사업 착수‧완료 보고시스템 운영 및 유지관리웹 접근성 품질 인증마크 갱신"),
]
PT_SEGMENTS = [
    ["paragraph-1-22"], ["paragraph-1-23"], ["paragraph-1-24"], ["paragraph-1-25"],
    ["paragraph-1-26", "paragraph-1-27"],
    ["paragraph-1-73", "paragraph-1-74", "paragraph-1-75"],
    ["paragraph-1-83", "paragraph-1-84", "paragraph-1-85", "paragraph-1-86", "paragraph-1-87"],
    ["paragraph-1-115", "paragraph-1-116"],
]
PT_CARD_CELLS = [
    (0, ["요구사항 분류", "유지관리 수행 요구사항"]),
    (1, ["요구사항 고유번호", "MPR-001"]),
    (2, ["요구사항 명칭", "홈페이지 운영환경"]),
    (3, ["요구사항상세설명", "정의", "홈페이지 운영환경 준수"]),
    (4, ["세부내용", "○ 대학 홈페이지  - HW정보: WEB서버 2대, WAS서버 2대, DB서버 1대, SVN서버 1대"]),
    (5, ["산출 정보", ""]),
]


def _pt_block(key: str, text: str, *, kind: str = "paragraph", row: int | None = None,
              column: int | None = None) -> dict:
    attributes = {} if kind == "paragraph" else {"table_key": "table-1-10"}
    if row is not None:
        attributes.update(row=row, column=column)
    return {"block_key": key, "parent_block_key": "table-1-10-block" if kind == "table_cell" else None,
            "type": kind, "page": 1, "bbox": None, "text": text, "confidence": None, "attributes": attributes}


def _polytech_excerpt() -> dict:
    blocks = [_pt_block(key, text) for key, text in (*PT_TOC, *PT_BODY)]
    blocks.append(_pt_block("table-1-10-block", "", kind="table"))
    for row, cells in PT_CARD_CELLS:
        blocks.extend(_pt_block(f"table-1-10-r{row}-c{column}", text, kind="table_cell", row=row, column=column)
                      for column, text in enumerate(cells))
    positions = {block["block_key"]: index for index, block in enumerate(blocks)}
    card = {
        "raw_id": "MPR-001", "normalized_id": "MPR-1",
        "locator": {"kind": "table_cell", "block_key": "table-1-10-r1-c0", "table_key": "table-1-10", "row": 1,
                    "column": 0, "page": 1, "ordinal": positions["table-1-10-r1-c0"]},
        "title": "홈페이지 운영환경", "ordinal": 1, "source": "label_value_table",
        "card": {"category": "유지관리 수행 요구사항", "compliance_level": None, "definition": "홈페이지 운영환경 준수",
                 "details": PT_CARD_CELLS[4][1][1], "outputs": None, "related_raw": None, "related_ids": [],
                 "table_key": "table-1-10", "first_cell_block_key": "table-1-10-r0-c0", "card_warnings": [],
                 "page_anchor_block_keys": []},
        "page_range": None, "mapping_status": "unavailable",
    }
    return {
        "source_sha256": PT_SHA, "document_version_id": uuid4(), "structure_id": uuid4(), "manifest_id": uuid4(),
        "blocks": blocks, "cards": [card],
        "segments": [
            {"segment_id": uuid4(), "ordinal": ordinal, "source_block_keys": keys,
             "start_locator": {"ordinal": positions[keys[0]], "block_key": keys[0]},
             "page_range": None, "mapping_status": "unavailable"}
            for ordinal, keys in enumerate(PT_SEGMENTS, start=1)
        ],
    }


def _evidence(unit: dict, block_key: str, quote: str) -> dict:
    return {"source_sha256": unit["source_sha256"], "block_key": block_key, "quote": quote}


def _constraint(owner: dict, block_key: str, quote: str, **values) -> dict:
    row = {"kind": "text", "value": quote, "unit": None, "operator": "eq", "fact_key": None, "quote": quote,
           "locator": {"source_sha256": owner["source_sha256"], "block_key": block_key}}
    row.update(values)
    return row


def _contract_answer(payload: dict) -> dict:
    """What a model following the v3 extract instruction returns for the excerpt batch."""

    items = []
    for unit in payload["units"]:
        texts = {block["block_key"]: block["text"] for block in unit["blocks"]}
        base = {"unit_id": unit["unit_id"], "mandatory": None, "unknowns": [],
                "concept_candidates": [dict(row) for row in unit["expected_concepts"]]}
        if "paragraph-1-74" in texts:
            items.append({**base, "type": "운영", "normalized_requirement": "2027년 홈페이지 유지관리 용역사업, 12개월",
                          "constraints": [_constraint(unit, "paragraph-1-75", "12개월", kind="duration", value=12,
                                                      unit="month")],
                          "evidence": [_evidence(unit, "paragraph-1-74", "사 업 명: 2027년 홈페이지 유지관리 용역사업")]})
        elif "paragraph-1-84" in texts:
            items.append({**base, "type": "보안", "normalized_requirement": "개인정보 보호법 준수와 웹 접근성 인증마크 취득",
                          "constraints": [],
                          "evidence": [_evidence(unit, "paragraph-1-85", "「개인정보 보호법」"),
                                       _evidence(unit, "paragraph-1-86", "웹 접근성 인증마크를 취득")]})
        elif "paragraph-1-116" in texts:
            # B30 (4): a year is kind=text copied verbatim, never a date
            items.append({**base, "type": "운영", "normalized_requirement": "2027년 사업 착수‧완료 보고",
                          "constraints": [_constraint(unit, "paragraph-1-116", "2027년")],
                          "evidence": [_evidence(unit, "paragraph-1-116", "사업 착수‧완료 보고")]})
        else:
            # B30 (4): servers are counted without unit=person, one number per quote, no duplicates
            assert unit["kind"] == "card"
            items.append({**base, "type": "기술", "normalized_requirement": "대학 홈페이지 운영환경(WEB서버 2대) 준수",
                          "constraints": [_constraint(unit, "table-1-10-r4-c1", "WEB서버 2대", kind="count", value=2)],
                          "evidence": [_evidence(unit, "table-1-10-r4-c1", "WEB서버 2대, WAS서버 2대")]})
    return {"schema_version": "bidops.requirement-extract.v1", "items": items}


def test_b30_v3_extract_units_carry_exactly_the_deterministic_expected_concepts(knowledge) -> None:
    from app.deep_review.services.company_analysis_input import card_expected_concepts
    from app.deep_review.services.company_knowledge_retrieval import match_concepts

    frozen = _frozen(knowledge, source=_polytech_excerpt(), selector_version="card-sections-v3")
    card = frozen["card_analysis"]
    payload = card_extract_transfer(frozen, 0, knowledge.ontology, operational_values=OPERATIONAL)
    assert set(payload) == CARD_TRANSFER_STAGE_KEYS["extract"]
    units = {row["unit_id"]: row for row in card["units"]}
    assert [row["unit_id"] for row in payload["units"]] == card["batches"][0]["unit_ids"]
    by_unit = {}
    for sent in payload["units"]:
        frozen_unit = units[sent["unit_id"]]
        assert set(sent) == set(frozen_unit) | {"expected_concepts"}
        assert {key: sent[key] for key in frozen_unit} == frozen_unit
        texts = [block["text"] for block in frozen_unit["blocks"]]
        # exactly the set the validator demands, as verbatim ontology terms of the unit text
        assert {row["concept_id"] for row in sent["expected_concepts"]} == {
            cid for text in texts for cid in match_concepts(text, knowledge.ontology)}
        for row in sent["expected_concepts"]:
            assert set(row) == {"concept_id", "alias_text"} and any(row["alias_text"] in text for text in texts)
            assert row["concept_id"] in match_concepts(row["alias_text"], knowledge.ontology)
        assert sent["expected_concepts"] == card_expected_concepts(texts, knowledge.ontology)
        by_unit[frozen_unit["blocks"][0]["block_key"]] = sent["expected_concepts"]
    assert by_unit["paragraph-1-83"] == [
        {"concept_id": "cap.privacy", "alias_text": "개인정보 보호"},
        {"concept_id": "cap.web-accessibility", "alias_text": "웹 접근성"},
        {"concept_id": "dom.website", "alias_text": "홈페이지"},
    ]
    assert by_unit["table-1-10-r0-c0"] == [
        {"concept_id": "dom.website", "alias_text": "홈페이지"},
        {"concept_id": "tech.db", "alias_text": "DB"},
    ]
    text = _text(payload)
    for value in (frozen["policy_sha256"], frozen["ontology_sha256"], str(APPROVAL_ID), NOTE_BODY, "BBB0"):
        assert value not in text
    # strict guard: the deterministic list exactly, ontology required, v1/v2 units unchanged
    for mutate in (
        lambda p: p["units"][0]["expected_concepts"].append({"concept_id": "rl.domain.02",
                                                             "alias_text": "홈페이지"}),
        lambda p: p["units"][-1]["expected_concepts"].pop(),
        lambda p: p["units"][0].pop("expected_concepts"),
        lambda p: p["units"][0].__setitem__("note", NOTE_BODY),
        lambda p: p["ontology"].pop(),
    ):
        changed = deepcopy(payload)
        mutate(changed)
        with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
            check_card_transfer_payload("extract", changed, frozen, ontology=knowledge.ontology)
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("extract", payload, frozen)  # v3 needs the ontology
    check_card_transfer_payload("extract", payload, frozen, ontology=knowledge.ontology)
    v2 = _frozen(knowledge, source=_polytech_excerpt(), selector_version="card-sections-v2")
    v2_payload = card_extract_transfer(v2, 0, knowledge.ontology)
    assert all("expected_concepts" not in row for row in v2_payload["units"])
    smuggled = deepcopy(v2_payload)
    smuggled["units"][0]["expected_concepts"] = []
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("extract", smuggled, v2, ontology=knowledge.ontology)


def test_b30_offline_replay_a_contract_following_answer_passes_and_the_t12_errors_fail(knowledge) -> None:
    from app.deep_review.services.card_analysis import CardAnalysisValidationError, validate_requirement_extract

    source = _polytech_excerpt()
    v2 = _frozen(knowledge, source=source, selector_version="card-sections-v2")
    v2_first = [row for row in v2["card_analysis"]["units"]][:3]
    # v2 froze the three title-only TOC units the real batch 0 started with
    assert [[block["block_key"] for block in row["blocks"]] for row in v2_first] == [
        ["paragraph-1-22"], ["paragraph-1-23"], ["paragraph-1-25"]]
    frozen = _frozen(knowledge, source=source, selector_version="card-sections-v3")
    card = frozen["card_analysis"]
    assert len(card["units"]) == 4 and len(card["batches"]) == 1
    assert all(len([b for b in row["blocks"] if b["text"].strip()]) > 1 for row in card["units"])
    payload = card_extract_transfer(frozen, 0, knowledge.ontology)
    answer = _contract_answer(payload)

    def validate(value: dict):
        return validate_requirement_extract(value, card_input=card, batch_index=0, ontology=knowledge.ontology)

    result = validate(answer)
    assert [item.unit_id for item in result.items] == card["batches"][0]["unit_ids"]

    def background(value: dict) -> dict:
        return next(item for item in value["items"] if item["type"] == "보안")

    def schedule(value: dict) -> dict:
        return next(item for item in value["items"] if item["constraints"] and item["constraints"][0]["value"] == "2027년")

    def card_item(value: dict) -> dict:
        return value["items"][-1]

    failures = {
        # (1) items: a unit skipped / a unit split into two items
        "unit_skipped": lambda a: a["items"].pop(0),
        "unit_split": lambda a: a["items"].insert(1, deepcopy(a["items"][1])),
        # (2) concepts by meaning or incomplete
        "semantic_concept": lambda a: background(a).__setitem__("concept_candidates", [
            {"concept_id": "rl.domain.02", "alias_text": "홈페이지·포털·CMS 구축·운영"}]),
        "meaning_alias": lambda a: background(a)["concept_candidates"].append(
            {"concept_id": "cap.vulnerability", "alias_text": "웹 취약점"}),
        "missing_exact_match": lambda a: background(a)["concept_candidates"].pop(),
        # (3) a year written as a date
        "year_as_date": lambda a: schedule(a)["constraints"].__setitem__(0, {
            **schedule(a)["constraints"][0], "kind": "date", "value": "2027", "unit": "year"}),
        # (4) servers counted as persons, twice
        "servers_as_persons": lambda a: card_item(a)["constraints"].__setitem__(0, {
            **card_item(a)["constraints"][0], "unit": "person"}),
        "duplicate_constraint": lambda a: card_item(a)["constraints"].append(
            deepcopy(card_item(a)["constraints"][0])),
        "several_numbers_eq": lambda a: card_item(a)["constraints"].__setitem__(0, {
            **card_item(a)["constraints"][0], "quote": "WEB서버 2대, WAS서버 2대, DB서버 1대"}),
    }
    for name, mutate in failures.items():
        changed = deepcopy(answer)
        mutate(changed)
        with pytest.raises(CardAnalysisValidationError, match="card_extract_invalid"):
            validate(changed)
        assert name


# --- 결정 B33: v4 (requirement-extract v2) on the T12 5차 batch-0 pattern ------------------
#
# Attempt bd0fe0a3 (policy v3) answered 8/8 units with every concept copied; the only
# violation was one constraint: "10일까지" in the MPR-005-like card (table-1-13, monthly
# inspection report "다음 달 10일까지") as kind=count, unit=day.  Sanitized excerpt below.

PT_CARD13_CELLS = [
    (0, ["요구사항 분류", "유지관리 수행 요구사항"]),
    (1, ["요구사항 고유번호", "MPR-005"]),
    (2, ["요구사항 명칭", "정기점검 및 보고"]),
    (3, ["요구사항상세설명", "정의", "정기점검 실시 및 결과 보고"]),
    (4, ["세부내용", "○ 정기점검 및 특별점검 결과 제출  - 매월 유지관리 처리내역에 대한 정기점검보고서 제출"
                  "(다음 달 10일까지)  - 웹 취약점 자가 점검 실시 후 취약사항 및 조치결과 제출"]),
]


def _polytech_excerpt_t12_5() -> dict:
    source = _polytech_excerpt()
    blocks = source["blocks"]
    blocks.append({"block_key": "table-1-13-block", "parent_block_key": None, "type": "table", "page": 1,
                   "bbox": None, "text": "", "confidence": None, "attributes": {"table_key": "table-1-13"}})
    for row, cells in PT_CARD13_CELLS:
        for column, text_value in enumerate(cells):
            blocks.append({"block_key": f"table-1-13-r{row}-c{column}", "parent_block_key": "table-1-13-block",
                           "type": "table_cell", "page": 1, "bbox": None, "text": text_value, "confidence": None,
                           "attributes": {"table_key": "table-1-13", "row": row, "column": column}})
    position = next(index for index, block in enumerate(blocks) if block["block_key"] == "table-1-13-r1-c0")
    card = deepcopy(source["cards"][0])
    card.update({"raw_id": "MPR-005", "normalized_id": "MPR-5", "title": "정기점검 및 보고", "ordinal": 2})
    card["locator"] = {**card["locator"], "block_key": "table-1-13-r1-c0", "table_key": "table-1-13",
                       "ordinal": position}
    card["card"] = {**card["card"], "table_key": "table-1-13", "first_cell_block_key": "table-1-13-r0-c0",
                    "definition": "정기점검 실시 및 결과 보고", "details": PT_CARD13_CELLS[4][1][1]}
    source["cards"].append(card)
    return source


def test_b33_v4_payload_sends_no_expected_concepts_and_still_fails_closed_before_the_call(knowledge) -> None:
    frozen = _frozen(knowledge, source=_polytech_excerpt_t12_5(), selector_version="card-sections-v3")
    card = frozen["card_analysis"]
    payload = card_extract_transfer(frozen, 0, knowledge.ontology, operational_values=OPERATIONAL,
                                    stage_schema="bidops.requirement-extract.v2")
    units = {row["unit_id"]: row for row in card["units"]}
    assert payload["units"] == [units[unit_id] for unit_id in card["batches"][0]["unit_ids"]]
    check_card_transfer_payload("extract", payload, frozen, ontology=knowledge.ontology,
                                stage_schema="bidops.requirement-extract.v2")
    smuggled = deepcopy(payload)
    smuggled["units"][0]["expected_concepts"] = []
    for value, kwargs in (
        (smuggled, {"ontology": knowledge.ontology, "stage_schema": "bidops.requirement-extract.v2"}),
        (payload, {"stage_schema": "bidops.requirement-extract.v2"}),  # ontology required
        (payload, {"ontology": knowledge.ontology, "stage_schema": "bidops.requirement-extract.v9"}),
        (payload, {"ontology": knowledge.ontology}),  # a v3/v1-contract check expects expected_concepts
    ):
        with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
            check_card_transfer_payload("extract", value, frozen, **kwargs)


def test_b33_offline_t12_5th_pattern_count_day_is_repairable_and_the_text_answer_passes(knowledge) -> None:
    from app.deep_review.services.card_analysis import (
        CardExtractStructureError,
        assemble_requirement_extract_v2,
        validate_requirement_extract,
    )
    from app.deep_review.services.company_analysis_input import card_expected_concepts

    frozen = _frozen(knowledge, source=_polytech_excerpt_t12_5(), selector_version="card-sections-v3")
    card = frozen["card_analysis"]
    assert len(card["units"]) == 5 and len(card["batches"]) == 1
    payload = card_extract_transfer(frozen, 0, knowledge.ontology, stage_schema="bidops.requirement-extract.v2")
    answer = {"schema_version": "bidops.requirement-extract.v2", "items": []}
    for unit in payload["units"]:
        first = next(block for block in unit["blocks"] if block["text"].strip()
                     and not block["text"].startswith(("1.", "2.", "4.")) and block["text"] != "요구사항 분류")
        item = {"unit_id": unit["unit_id"], "type": "운영", "normalized_requirement": "원문 요구사항을 따른다",
                "mandatory": None, "constraints": [], "unknowns": [],
                "evidence": [{"source_sha256": unit["source_sha256"], "block_key": first["block_key"],
                              "quote": first["text"]}]}
        if any(block["block_key"] == "table-1-13-r4-c1" for block in unit["blocks"]):
            item["constraints"].append({
                "kind": "text", "value": "다음 달 10일까지", "unit": None, "fact_key": None, "quote": "다음 달 10일까지",
                "locator": {"source_sha256": unit["source_sha256"], "block_key": "table-1-13-r4-c1"}})
        answer["items"].append(item)
    from app.deep_review.contracts import validate_payload
    validate_payload(answer, "requirement-extract-v2")
    assembled = assemble_requirement_extract_v2(answer, card_input=card, batch_index=0, ontology=knowledge.ontology)
    validate_requirement_extract(assembled, card_input=card, batch_index=0, ontology=knowledge.ontology)
    units = {row["unit_id"]: row for row in card["units"]}
    for item in assembled["items"]:
        assert item["concept_candidates"] == card_expected_concepts(
            [block["text"] for block in units[item["unit_id"]]["blocks"]], knowledge.ontology)
    deadline = [c for item in assembled["items"] for c in item["constraints"]]
    # 결정 B35: the deadline "까지" derives lte
    assert deadline == [{**answer["items"][-1]["constraints"][0], "operator": "lte"}]
    # the real 5th answer: the same deadline as count/day (model operator lte) -> repair-class, not terminal
    real = deepcopy(answer)
    real["items"][-1]["constraints"][0].update({"kind": "count", "value": 10, "unit": "day", "quote": "10일까지"})
    with pytest.raises(CardExtractStructureError) as error:
        assemble_requirement_extract_v2(real, card_input=card, batch_index=0, ontology=knowledge.ontology)
    assert error.value.rule_codes == ["constraint_unit_invalid", "output_schema"]
    assert error.value.item_indexes == [len(answer["items"]) - 1]


def test_b51_v7_synthesis_payload_names_exactly_the_rejected_units(knowledge) -> None:
    frozen = _frozen(knowledge, selector_version="card-sections-v3")
    unit_ids = [row["unit_id"] for row in frozen["card_analysis"]["units"]]
    _extract, compare = _role_parts()
    fact_keys = card_referenced_fact_keys(compare)
    roles = [{"role": "eligibility_economics", "unit_findings": [], "cautions": [], "evidence_refs": []}]
    payload = card_synthesis_transfer(frozen, roles=roles, fact_keys=fact_keys, operational_values=OPERATIONAL,
                                      rejected_units=[unit_ids[1]])
    assert payload["rejected_units"] == [unit_ids[1]]
    assert set(payload) == CARD_TRANSFER_STAGE_KEYS["synthesis"] | {"missing_sections", "rejected_units"}
    empty = card_synthesis_transfer(frozen, roles=roles, fact_keys=fact_keys, rejected_units=[])
    assert empty["rejected_units"] == []
    for value, rejected in (
        ({**payload, "rejected_units": [unit_ids[0]]}, [unit_ids[1]]),   # not the isolated ids
        (payload, None),                                                # v1-v6 payload has no such key
        ({**payload, "rejected_units": ["unit-unknown"]}, ["unit-unknown"]),
        ({**payload, "rejected_units": [unit_ids[1], unit_ids[1]]}, [unit_ids[1], unit_ids[1]]),
    ):
        with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
            check_card_transfer_payload("synthesis", value, frozen, fact_keys=fact_keys, rejected_units=rejected)
    without = {key: value for key, value in payload.items() if key != "rejected_units"}
    with pytest.raises(CompanyAnalysisError, match="company_input_invalid"):
        check_card_transfer_payload("synthesis", without, frozen, fact_keys=fact_keys, rejected_units=[unit_ids[1]])
