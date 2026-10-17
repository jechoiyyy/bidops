"""RL-03 card-v1 worker run with a fake Luna client (spec T5: HP-03 T6~T8 with ``card_analysis_stage``).

The STEP-003 world (real Rootlab v2 company, approved ``analysis-policy-luna-rl-v1``
row, SW=Y pre-spec with six heading sections and one requirement card, policy
transfer approval) is started through ``start_rl_verdict`` and claimed by the
real worker.  The model is a scripted fake ``invoke_prompt`` client: it answers
valid stage outputs from the prompt input and can return an invalid quote, an
invented number, a schema failure, a role that upgrades an unknown, or a false
"진행 가능"; it can also move the clock past the review timeout or steal the
lease.

Each case runs on SQLite and, with ``BIDOPS_TEST_POSTGRES_URL``, on a migrated
PostgreSQL 17 database where the append-only trigger of ``card_analysis_stage``
is checked as well.  No LunaClient, model endpoint or network is used.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.model_client import InvocationResult, ModelClient, ModelInvocationError
from app.core.models import AuditEvent
from app.deep_review.models import (
    CardAnalysisStage,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewPreview,
    DeepReviewStage,
    WorkJob,
)
from app.deep_review.services import card_analysis, company_analysis_input
from app.deep_review.services.company_analysis_input import (
    card_referenced_fact_keys,
    check_card_transfer_payload,
    resolve_company_knowledge_context,
)
from app.deep_review.services.company_knowledge_retrieval import match_concepts
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError, StaleFenceError
from tests.app import test_transfer_policy as tp
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store
from tests.postgres import migrated_engine, requires_postgres


pytestmark = tp.needs_rootlab

ROLES = ("eligibility_economics", "technical_fit", "operations_risk")


@pytest.fixture(autouse=True)
def no_model_transport(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("model transport called")

    from app.deep_review.services import luna_client

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(forbidden))
    monkeypatch.setattr(luna_client.LunaClient, "__init__", forbidden)
    yield


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def flow_engine(request):
    if request.param == "sqlite":
        bind = tp._sqlite_engine()
        try:
            yield bind
        finally:
            bind.dispose()
    else:
        with migrated_engine() as bind:
            yield bind


# --- scripted fake Luna ------------------------------------------------------------


class FakeLuna:
    """``invoke_prompt`` double that derives valid stage outputs from the prompt input."""

    def __init__(self, ontology, overrides: dict[tuple[str, int], Callable[[dict], dict]] | None = None,
                 on_call: Callable[["FakeLuna", dict], None] | None = None,
                 copy_expected_concepts: bool = False) -> None:
        self.ontology = ontology
        #: 결정 B30: answer like a model following the v3 extract instruction.
        self.copy_expected_concepts = copy_expected_concepts
        self.overrides = overrides or {}
        self.on_call = on_call
        self.calls: list[tuple[str, str, bool]] = []
        self.envelopes: list[dict] = []
        self.prompts: list[str] = []
        self._seen: dict[str, int] = {}

    def invoke_prompt(self, prompt: str, *, contract: str):
        envelope = json.loads(prompt)
        stage = envelope["stage"]
        occurrence = self._seen.get(stage, 0)
        self._seen[stage] = occurrence + 1
        self.calls.append((contract, stage, "validation_repair" in envelope))
        self.envelopes.append(envelope)
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(self, envelope)
        output = self._valid(stage, envelope["input"], contract)
        override = self.overrides.get((stage, occurrence))
        if override is not None:
            output = override(output)
        raw = json.dumps(output, ensure_ascii=False).encode("utf-8")
        return InvocationResult(output, raw, hashlib.sha256(prompt.encode()).hexdigest(),
                                hashlib.sha256(raw).hexdigest(), None, None, 1, (), "codex-exec", "gpt-6-luna")

    def _valid(self, stage: str, value: dict, contract: str = "") -> dict:
        if stage == "extract":
            items = []
            for unit in value["units"]:
                blocks = [block for block in unit["blocks"] if block["text"].strip()]
                candidates, seen = [], set()
                if self.copy_expected_concepts:
                    candidates = [dict(row) for row in unit["expected_concepts"]]
                    blocks_for_concepts: list[dict] = []
                else:
                    blocks_for_concepts = blocks
                for block in blocks_for_concepts:
                    for concept_id in match_concepts(block["text"], self.ontology):
                        if (concept_id, block["text"]) not in seen:
                            seen.add((concept_id, block["text"]))
                            candidates.append({"concept_id": concept_id, "alias_text": block["text"]})
                type_ = "기능" if unit["kind"] == "card" else "자격" if "eligibility" in unit["section_kinds"] else "운영"
                items.append({
                    "unit_id": unit["unit_id"], "type": type_, "normalized_requirement": blocks[0]["text"],
                    "mandatory": None, "constraints": [], "concept_candidates": candidates, "unknowns": [],
                    "evidence": [{"source_sha256": unit["source_sha256"], "block_key": blocks[0]["block_key"],
                                  "quote": blocks[0]["text"]}],
                })
            if contract == "card-extract-v2":
                # 결정 B33: the v2 answer omits concept_candidates (and operators); code derives them.
                for item in items:
                    item.pop("concept_candidates")
                return {"schema_version": "bidops.requirement-extract.v2", "items": items}
            return {"schema_version": "bidops.requirement-extract.v1", "items": items}
        if stage in ROLES:
            fits = {row["unit_id"]: row["fit_status"] for row in value["compare"]["items"]}
            return {
                "schema_version": "bidops.verdict-role.v1", "role": value["role"],
                "unit_findings": [
                    {"unit_id": row["unit_id"], "assessment": fits[row["unit_id"]],
                     "reason": "결정적 대조 결과를 따른다", "evidence_refs": row["evidence"]}
                    for row in value["extract"]["items"]
                ],
                "cautions": [], "evidence_refs": [],
            }
        assert stage == "synthesis"
        return {"schema_version": "bidops.practitioner-verdict.v1", "verdict": "조건부 진행",
                "reason": "확인이 필요한 요구사항이 남아 있어 조건부로 검토한다.",
                "blocking_condition_ids": [], "cautions": [], "next_actions": []}


class SchemaFailure:
    """Override that raises the transport schema failure the Luna client reports."""

    def __init__(self) -> None:
        self.raised = 0

    def __call__(self, _output: dict) -> dict:
        self.raised += 1
        raise ModelInvocationError("schema_invalid", (), b'{"items": "not-a-list"}')


# --- world --------------------------------------------------------------------------


def start_world(session: Session, monkeypatch, *, overrides=None, on_call=None):
    world = tp.build_world(session, monkeypatch)
    approval = tp.approve(session)
    started = tp.start(session, world)
    knowledge = resolve_company_knowledge_context(session, world.company_id)
    fake = FakeLuna(knowledge.ontology, overrides, on_call)
    session.commit()
    svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
    return world, started, svc, fake, approval


def run(session: Session, svc: DeepReviewService):
    claim = svc.claim_next_job(session, "worker-rl-card")
    assert claim is not None
    svc.run_claim(session, claim)
    return claim


def run_code(session: Session, svc: DeepReviewService) -> str:
    claim = svc.claim_next_job(session, "worker-rl-card")
    assert claim is not None
    with pytest.raises(DeepReviewServiceError) as error:
        svc.run_claim(session, claim)
    return error.value.code


def assert_payload_fact_subsets(fake: FakeLuna, frozen: dict) -> dict[str, list[str]]:
    """Every payload passes the D2 check; role/synthesis facts are exactly the referenced ones (B10/B11)."""

    statuses = {row["fact_key"]: row["status"] for row in frozen["profile_facts"]}
    referenced: dict[str, list[str]] = {}
    union: list[str] = []
    for envelope in fake.envelopes:
        stage, value = envelope["stage"], envelope["input"]
        if stage == "extract":
            check_card_transfer_payload("extract", value, frozen, ontology=fake.ontology)
            assert all(set(row) == {"id", "label", "aliases"} for row in value["ontology"])
            continue
        if stage == "synthesis":
            check_card_transfer_payload("synthesis", value, frozen, fact_keys=union)
            keys = union
        else:
            keys = card_referenced_fact_keys(value["compare"])
            check_card_transfer_payload("role", value, frozen, fact_keys=keys)
            union.extend(key for key in keys if key not in union)
        referenced[stage] = list(keys)
        assert {row["fact_key"] for row in value["profile_facts"]} == set(keys)
        for row in value["profile_facts"]:
            if statuses[row["fact_key"]] == "confirmed":
                assert set(row) == {"fact_key", "type", "label", "status", "origin", "value"}
            else:
                assert row == {"fact_key": row["fact_key"], "status": statuses[row["fact_key"]]}
        assert {row["fact_key"] for row in value["profile_evidence"]} <= {
            key for key in keys if statuses[key] == "confirmed"}
    return referenced


def stage_keys(session: Session, attempt_id: UUID) -> set[tuple[str, str]]:
    return {(row.stage, row.stage_key) for row in session.scalars(
        select(CardAnalysisStage).where(CardAnalysisStage.attempt_id == attempt_id))}


def batch_count(session: Session, started) -> int:
    preview = session.get(DeepReviewPreview, started.preview_id)
    return len(preview.input_snapshot["card_analysis"]["batches"])


def audits(session: Session, action: str) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.created_at)))


def assert_failed(session: Session, started, code: str) -> None:
    attempt = session.get(DeepReviewAttempt, started.attempt_id)
    job = session.get(WorkJob, attempt.work_job_id)
    assert attempt.status == "failed" and job.status == "failed" and job.last_error_code == code
    assert session.get(DeepReview, started.review_id).status == "failed"
    assert code in card_analysis.NEEDS_HUMAN_REVIEW_CODES or code == "company_input_invalid"


# --- T5: full run, call budget, append-only rows -----------------------------------


def test_t5_full_run_uses_b_plus_four_calls_and_appends_every_validated_stage(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        world, started, svc, fake, approval = start_world(session, monkeypatch)
        batches = batch_count(session, started)
        run(session, svc)

        attempt = session.get(DeepReviewAttempt, started.attempt_id)
        assert attempt.status == "completed"
        assert session.get(DeepReview, started.review_id).status == "completed"
        assert session.get(WorkJob, attempt.work_job_id).status == "completed"
        # narrative StageName rows are not created for card-v1 attempts
        assert session.scalar(select(func.count()).select_from(DeepReviewStage).where(
            DeepReviewStage.attempt_id == started.attempt_id)) == 0
        expected = ({("extract", str(i)) for i in range(batches)} | {("compare", str(i)) for i in range(batches)}
                    | {("role", role) for role in ROLES} | {("synthesis", "final")})
        assert stage_keys(session, started.attempt_id) == expected
        # exactly B+4 calls on the three card contracts, no repair
        assert len(fake.calls) == batches + 4
        assert [call[0] for call in fake.calls] == (
            ["card-extract-v1"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"])
        assert not any(call[2] for call in fake.calls)
        sent = audits(session, "analysis.transfer.sent")
        assert len(sent) == 1 and sent[0].safe_metadata["planned_call_count"] == batches + 4
        completed = [row for row in audits(session, "deep_review.job.completed")
                     if row.safe_metadata.get("attempt_id") == str(started.attempt_id)]
        assert len(completed) == 1
        assert {key: completed[0].safe_metadata[key] for key in ("pipeline_version", "batch_count", "call_count",
                                                                "target_seconds", "target_missed")} == {
            "pipeline_version": "card-v1", "batch_count": batches, "call_count": batches + 4,
            "target_seconds": 2400, "target_missed": False,
        }
        raw = audits(session, "deep_review.card.raw_response.stored")
        assert [row.safe_metadata["call_index"] for row in raw] == list(range(1, batches + 5))

        # every outgoing payload is the checked D2 projection; no operational or withheld value leaks
        preview = session.get(DeepReviewPreview, started.preview_id)
        frozen = preview.input_snapshot
        assert_payload_fact_subsets(fake, frozen)
        joined = "\n".join(fake.prompts)
        for forbidden in (approval["approval_id"], str(started.attempt_id), str(started.review_id),
                          world.policy_sha256, "BBB0", frozen["graph_sha256"], frozen["profile_sha256"]):
            assert forbidden not in joined
        # no unit referenced the proposed credit rating, so it is not sent even as key+status (B11)
        assert "qual:credit_rating" not in joined
        # v1 synthesis payload is unchanged: no missing_sections key (결정 B24 is v2 only)
        synthesis_envelope = next(row for row in fake.envelopes if row["stage"] == "synthesis")
        assert "missing_sections" not in synthesis_envelope["input"]

        final = session.scalar(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "synthesis"))
        assert final.payload["verdict"] == "조건부 진행"
        assert [row["key"] for row in final.payload["checklist"]] == [
            "qualification_track_record", "staffing_onsite", "amount_period", "technology", "operations_sla_security"]
        # an unknown never becomes 부족: with no confirmed contradiction nothing is gap
        compare_rows = session.scalars(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "compare")).all()
        fits = [item["fit_status"] for row in compare_rows for item in row.payload["items"]]
        assert "gap" not in fits

        if flow_engine.dialect.name == "postgresql":
            row_id = final.id
            session.commit()
            for statement in ("UPDATE bidops.card_analysis_stage SET stage_key = stage_key WHERE id = :id",
                              "DELETE FROM bidops.card_analysis_stage WHERE id = :id"):
                with pytest.raises(DBAPIError):
                    session.execute(text(statement), {"id": row_id})
                session.rollback()
            assert len(stage_keys(session, started.attempt_id)) == len(expected)


# --- T5: deterministic validation failures go to people (no repair, no correction) ----


def _bad_quote(output: dict) -> dict:
    output["items"][0]["evidence"][0]["quote"] += " 및 ISMS-P 인증"
    return output


def _invented_number(output: dict) -> dict:
    output["items"][0]["normalized_requirement"] += " 상주 인원 99명"
    return output


def _schema_violation(output: dict) -> dict:
    output["items"][0]["confidence"] = 0.9
    return output


@pytest.mark.parametrize("override", [_bad_quote, _invented_number, _schema_violation],
                         ids=["quote_not_in_source", "invented_number", "schema_violation"])
def test_t5_invalid_extract_fails_without_repair_or_stored_rows(flow_engine, monkeypatch, override) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(session, monkeypatch, overrides={("extract", 0): override})
        assert run_code(session, svc) == "card_extract_invalid"
        assert len(fake.calls) == 1  # evidence / number / schema-shape errors are never repaired
        assert stage_keys(session, started.attempt_id) == set()
        assert_failed(session, started, "card_extract_invalid")
        assert len(audits(session, "analysis.transfer.sent")) == 1


def test_t5_transport_schema_failure_is_repaired_once(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        failure = SchemaFailure()
        _world, started, svc, fake, _approval = start_world(session, monkeypatch, overrides={("extract", 0): failure})
        batches = batch_count(session, started)
        run(session, svc)
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert failure.raised == 1 and len(fake.calls) == batches + 5
        assert fake.calls[1] == ("card-extract-v1", "extract", True)  # the repair carries the marker
        raw = audits(session, "deep_review.card.raw_response.stored")
        assert [row.safe_metadata["repair_attempt"] for row in raw[:2]] == [0, 1]


def test_t5_second_transport_schema_failure_stops_the_attempt(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        failure = SchemaFailure()
        _world, started, svc, fake, _approval = start_world(
            session, monkeypatch, overrides={("extract", 0): failure, ("extract", 1): failure})
        assert run_code(session, svc) == "card_extract_invalid"
        assert failure.raised == 2 and len(fake.calls) == 2
        assert stage_keys(session, started.attempt_id) == set()
        assert_failed(session, started, "card_extract_invalid")


def _upgrade_unknown(output: dict) -> dict:
    for finding in output["unit_findings"]:
        finding["assessment"] = "met"
    return output


def test_t5_role_that_upgrades_an_unknown_fails_and_keeps_earlier_rows(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(
            session, monkeypatch, overrides={("technical_fit", 0): _upgrade_unknown})
        batches = batch_count(session, started)
        assert run_code(session, svc) == "card_role_invalid"
        keys = stage_keys(session, started.attempt_id)
        assert ("role", "eligibility_economics") in keys and ("role", "technical_fit") not in keys
        assert {("extract", str(i)) for i in range(batches)} <= keys  # partial rows preserved
        assert len(fake.calls) == batches + 2
        assert_failed(session, started, "card_role_invalid")


def _false_proceed(output: dict) -> dict:
    output["verdict"] = "진행 가능"
    return output


def test_t5_unconditional_proceed_with_unresolved_units_is_rejected(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, _fake, _approval = start_world(
            session, monkeypatch, overrides={("synthesis", 0): _false_proceed})
        assert run_code(session, svc) == "card_synthesis_invalid"
        keys = stage_keys(session, started.attempt_id)
        assert {("role", role) for role in ROLES} <= keys and ("synthesis", "final") not in keys
        assert_failed(session, started, "card_synthesis_invalid")


def test_t5_missing_source_section_stops_before_synthesis(flow_engine, monkeypatch) -> None:
    original = tp._structure_blocks
    monkeypatch.setattr(tp, "_structure_blocks", lambda: [
        block for block in original() if block["block_key"] not in {"h-contract", "b-contract"}])
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(session, monkeypatch)
        preview = session.get(DeepReviewPreview, started.preview_id)
        assert preview.input_snapshot["card_analysis"]["missing_sections"] == ["contract"]
        # v1 policy row → card-sections-v1 keeps the HP-03 stop (결정 B23 changes only v2)
        assert preview.input_snapshot["card_analysis"]["selector"]["version"] == "card-sections-v1"
        batches = batch_count(session, started)
        assert run_code(session, svc) == "card_source_selection_incomplete"
        assert len(fake.calls) == batches + 3  # no synthesis call
        keys = stage_keys(session, started.attempt_id)
        assert {("role", role) for role in ROLES} <= keys and ("synthesis", "final") not in keys
        assert_failed(session, started, "card_source_selection_incomplete")


# --- 결정 B23: card-sections-v2 records missing sections and caps the verdict -----------

RL_V2 = "analysis-policy-luna-rl-v2"


def _without_contract(monkeypatch) -> None:
    original = tp._structure_blocks
    monkeypatch.setattr(tp, "_structure_blocks", lambda: [
        block for block in original() if block["block_key"] not in {"h-contract", "b-contract"}])


def start_world_v2(session: Session, monkeypatch, *, overrides=None):
    world = tp.build_world(session, monkeypatch, policy_identity=RL_V2)
    approval = tp.approve(session, policy_identity=RL_V2)
    started = tp.start(session, world)
    knowledge = resolve_company_knowledge_context(session, world.company_id)
    fake = FakeLuna(knowledge.ontology, overrides)
    session.commit()
    svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
    return world, started, svc, fake, approval


def test_b23_v2_missing_section_completes_with_missing_sections_recorded(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import verdict_view

    _without_contract(monkeypatch)
    with Session(flow_engine) as session:
        world, started, svc, fake, approval = start_world_v2(session, monkeypatch)
        assert approval["policy_identity"] == RL_V2
        preview = session.get(DeepReviewPreview, started.preview_id)
        card = preview.input_snapshot["card_analysis"]
        assert card["selector"]["version"] == "card-sections-v2" and card["missing_sections"] == ["contract"]
        batches = batch_count(session, started)
        run(session, svc)

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(fake.calls) == batches + 4  # synthesis is no longer skipped
        # 결정 B24: the model is told which areas were not found and that 진행 가능 is not allowed
        synthesis_envelope = next(row for row in fake.envelopes if row["stage"] == "synthesis")
        assert synthesis_envelope["input"]["missing_sections"] == ["contract"]
        assert "missing_sections" in synthesis_envelope["instruction"]
        assert "진행 가능" in synthesis_envelope["instruction"]
        assert all("missing_sections" not in row["input"] for row in fake.envelopes if row["stage"] != "synthesis")
        check_card_transfer_payload("synthesis", synthesis_envelope["input"], preview.input_snapshot,
                                    fact_keys=assert_payload_fact_subsets(fake, preview.input_snapshot)["synthesis"])
        final = session.scalar(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "synthesis"))
        assert final.payload["missing_sections"] == ["contract"]
        assert final.payload["verdict"] == "조건부 진행"
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["error_code"] is None
        assert view["missing_sections"] == ["contract"]
        assert view["result"]["verdict"] != "진행 가능"
        if flow_engine.dialect.name == "sqlite":
            # (no append-only trigger on SQLite) a stored final whose missing sections
            # disagree with the frozen input is never shown as a completed verdict
            session.execute(update(CardAnalysisStage).where(CardAnalysisStage.id == final.id).values(
                payload={**final.payload, "missing_sections": []}))
            session.commit()
            with pytest.raises(verdict_view.VerdictViewError) as error:
                verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
            assert error.value.code == "processing_failed"


def test_b23_v2_without_missing_sections_records_an_empty_list(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, _fake, _approval = start_world_v2(session, monkeypatch)
        run(session, svc)
        final = session.scalar(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "synthesis"))
        assert final.payload["missing_sections"] == []


def test_b23_v2_false_proceed_with_missing_section_is_rejected(flow_engine, monkeypatch) -> None:
    _without_contract(monkeypatch)
    with Session(flow_engine) as session:
        _world, started, svc, _fake, _approval = start_world_v2(
            session, monkeypatch, overrides={("synthesis", 0): _false_proceed})
        assert run_code(session, svc) == "card_synthesis_invalid"
        assert ("synthesis", "final") not in stage_keys(session, started.attempt_id)
        assert_failed(session, started, "card_synthesis_invalid")


# --- 결정 B30: card-sections-v3 + extract contract + expected concepts -----------------

RL_V3 = "analysis-policy-luna-rl-v3"


def start_world_v3(session: Session, monkeypatch, *, overrides=None):
    world = tp.build_world(session, monkeypatch, policy_identity=RL_V3)
    approval = tp.approve(session, policy_identity=RL_V3)
    started = tp.start(session, world)
    knowledge = resolve_company_knowledge_context(session, world.company_id)
    fake = FakeLuna(knowledge.ontology, overrides, copy_expected_concepts=True)
    session.commit()
    svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
    return world, started, svc, fake, approval


def _expected_by_unit(frozen: dict, ontology) -> dict[str, list[dict]]:
    from app.deep_review.services.company_analysis_input import card_expected_concepts

    return {unit["unit_id"]: card_expected_concepts([block["text"] for block in unit["blocks"]], ontology)
            for unit in frozen["card_analysis"]["units"]}


def test_b30_v3_run_sends_expected_concepts_and_completes_with_the_contract_answer(flow_engine, monkeypatch) -> None:
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V3

    with Session(flow_engine) as session:
        _world, started, svc, fake, approval = start_world_v3(session, monkeypatch)
        assert approval["policy_identity"] == RL_V3
        preview = session.get(DeepReviewPreview, started.preview_id)
        frozen = preview.input_snapshot
        assert frozen["card_analysis"]["selector"]["version"] == "card-sections-v3"
        batches = batch_count(session, started)
        run(session, svc)

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(fake.calls) == batches + 4
        expected = _expected_by_unit(frozen, fake.ontology)
        assert any(expected.values())  # the fixture has exact ontology matches
        policy = json.loads(RL_LUNA_POLICY_FILE_V3.read_bytes())
        extract_envelopes = [row for row in fake.envelopes if row["stage"] == "extract"]
        assert len(extract_envelopes) == batches
        for envelope in extract_envelopes:
            assert envelope["instruction"] == policy["stages"][0]["instruction"]
            for unit in envelope["input"]["units"]:
                assert unit["expected_concepts"] == expected[unit["unit_id"]]
        # the synthesis payload keeps the B24 key; role payloads are unchanged
        synthesis = next(row for row in fake.envelopes if row["stage"] == "synthesis")
        assert "missing_sections" in synthesis["input"]
        assert all("expected_concepts" not in _text_of(row["input"]) for row in fake.envelopes
                   if row["stage"] != "extract")
        assert_payload_fact_subsets(fake, frozen)
        stored = session.scalars(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "extract")).all()
        for row in stored:
            for item in row.payload["items"]:
                assert item["concept_candidates"] == expected[item["unit_id"]]


def _text_of(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_b30_mock_v3_run_completes_and_copies_the_expected_concepts(flow_engine, monkeypatch) -> None:
    """T11 shape for v3: the mock answers follow the same extract contract as the real model."""

    from app.deep_review.services import verdict_view

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V3)
        tp.approve(session, policy_identity=RL_V3)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        frozen = session.get(DeepReviewPreview, started.preview_id).input_snapshot
        assert frozen["card_analysis"]["selector"]["version"] == "card-sections-v3"
        batches = batch_count(session, started)
        calls = _count_mock_calls(monkeypatch)

        run(session, _plain_service())

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert calls == ["card-extract-v1"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"]
        assert audits(session, "analysis.transfer.sent") == []
        knowledge = resolve_company_knowledge_context(session, world.company_id)
        expected = _expected_by_unit(frozen, knowledge.ontology)
        stored = session.scalars(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "extract")).all()
        items = [item for row in stored for item in row.payload["items"]]
        assert [item["unit_id"] for item in items] == [unit["unit_id"] for unit in frozen["card_analysis"]["units"]]
        for item in items:
            assert item["concept_candidates"] == expected[item["unit_id"]]
        assert any(item["concept_candidates"] for item in items)
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"
        assert view["result"]["verdict"] == "판단 불가"


# --- 결정 B33: policy v4, requirement-extract v2, code-derived fields, repair codes ------

RL_V4 = "analysis-policy-luna-rl-v4"


def start_world_v4(session: Session, monkeypatch, *, overrides=None):
    world = tp.build_world(session, monkeypatch, policy_identity=RL_V4)
    approval = tp.approve(session, policy_identity=RL_V4)
    started = tp.start(session, world)
    knowledge = resolve_company_knowledge_context(session, world.company_id)
    fake = FakeLuna(knowledge.ontology, overrides)
    session.commit()
    svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
    return world, started, svc, fake, approval


def _count_in_days(output: dict) -> dict:
    """The T12 5차 pattern: a deadline answered as kind=count, unit=day (pydantic kind x unit rule)."""

    item = output["items"][0]
    block = item["evidence"][0]
    item["constraints"].append({"kind": "count", "value": 10, "unit": "day", "fact_key": None,
                                "quote": block["quote"],
                                "locator": {"source_sha256": block["source_sha256"], "block_key": block["block_key"]}})
    return output


def _quote_not_in_source(output: dict) -> dict:
    output["items"][0]["evidence"][0]["quote"] = "원문에 없는 문장"
    return output


def _extract_rows(session: Session, attempt_id) -> list:
    return session.scalars(select(CardAnalysisStage).where(
        CardAnalysisStage.attempt_id == attempt_id, CardAnalysisStage.stage == "extract")).all()


def test_b33_v4_run_assembles_concepts_and_operators_in_code(flow_engine, monkeypatch) -> None:
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V4

    with Session(flow_engine) as session:
        _world, started, svc, fake, approval = start_world_v4(session, monkeypatch)
        assert approval["policy_identity"] == RL_V4
        frozen = session.get(DeepReviewPreview, started.preview_id).input_snapshot
        assert frozen["card_analysis"]["selector"]["version"] == "card-sections-v3"
        batches = batch_count(session, started)
        run(session, svc)

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(fake.calls) == batches + 4
        assert [row[0] for row in fake.calls if row[1] == "extract"] == ["card-extract-v2"] * batches
        policy = json.loads(RL_LUNA_POLICY_FILE_V4.read_bytes())
        for envelope in (row for row in fake.envelopes if row["stage"] == "extract"):
            assert envelope["instruction"] == policy["stages"][0]["instruction"]
            assert all("expected_concepts" not in unit for unit in envelope["input"]["units"])
            check_card_transfer_payload("extract", envelope["input"], frozen, ontology=fake.ontology,
                                        stage_schema="bidops.requirement-extract.v2")
        expected = _expected_by_unit(frozen, fake.ontology)
        for row in _extract_rows(session, started.attempt_id):
            assert row.payload["schema_version"] == "bidops.requirement-extract.v1"  # the assembled object
            for item in row.payload["items"]:
                assert item["concept_candidates"] == expected[item["unit_id"]]
        raw = audits(session, "deep_review.card.raw_response.stored")
        extract_raw = [row.safe_metadata for row in raw if row.safe_metadata["stage"] == "extract"]
        assert extract_raw and all(
            row["extract_contract"] == "bidops.requirement-extract.v2"
            and row["code_derived_fields"] == ["concept_candidates", "constraints.operator"] for row in extract_raw)
        assert all("code_derived_fields" not in row.safe_metadata for row in raw if row.safe_metadata["stage"] != "extract")
        completed = audits(session, "deep_review.job.completed")[-1].safe_metadata
        assert completed["code_derived_fields"] == ["concept_candidates", "constraints.operator"]
        assert completed["extract_contract"] == "bidops.requirement-extract.v2"


def test_b33_kind_unit_violation_gets_one_repair_with_rule_codes_only(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world_v4(
            session, monkeypatch, overrides={("extract", 0): _count_in_days})
        batches = batch_count(session, started)
        run(session, svc)

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(fake.calls) == batches + 4 + 1
        assert fake.calls[0] == ("card-extract-v2", "extract", False)
        assert fake.calls[1] == ("card-extract-v2", "extract", True)
        repair = fake.envelopes[1]["validation_repair"]
        assert repair == {"scope": "syntax_or_schema_only",
                          "rule_codes": ["constraint_unit_invalid", "output_schema"], "item_indexes": [0]}
        # the repair prompt is the identical frozen input + codes; no answer text is echoed
        assert fake.envelopes[1]["input"] == fake.envelopes[0]["input"]
        assert set(fake.envelopes[1]) == set(fake.envelopes[0]) | {"validation_repair"}
        raw = [row.safe_metadata for row in audits(session, "deep_review.card.raw_response.stored")
               if row.safe_metadata["stage"] == "extract" and row.safe_metadata["stage_key"] == "0"]
        assert [row["repair_attempt"] for row in raw] == [0, 1]
        assert "repair_rule_codes" not in raw[0]
        assert raw[1]["repair_rule_codes"] == ["constraint_unit_invalid", "output_schema"]
        stored = _extract_rows(session, started.attempt_id)
        assert all(constraint["unit"] != "day" for row in stored for item in row.payload["items"]
                   for constraint in item["constraints"] if constraint["kind"] == "count")


def _client_rejects_count_in_days(output: dict) -> dict:
    """The real path: LunaClient checks the v2 output schema and reports ``schema_invalid`` with the raw answer."""

    raise ModelInvocationError("schema_invalid", (), json.dumps(_count_in_days(output), ensure_ascii=False).encode())


def test_b33_client_schema_rejection_repair_also_names_the_rule_codes(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world_v4(
            session, monkeypatch, overrides={("extract", 0): _client_rejects_count_in_days})
        batches = batch_count(session, started)
        run(session, svc)
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(fake.calls) == batches + 4 + 1
        assert fake.envelopes[1]["validation_repair"] == {
            "scope": "syntax_or_schema_only", "rule_codes": ["constraint_unit_invalid", "output_schema"],
            "item_indexes": [0]}


def test_b33_v1_contract_transport_repair_keeps_the_existing_envelope(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, _started, svc, fake, _approval = start_world_v3(
            session, monkeypatch, overrides={("extract", 0): SchemaFailure()})
        run(session, svc)
        assert fake.envelopes[1]["validation_repair"] == {"scope": "syntax_or_schema_only"}


def test_b33_second_structural_failure_stops_within_the_budget(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world_v4(
            session, monkeypatch, overrides={("extract", 0): _count_in_days, ("extract", 1): _count_in_days})
        assert run_code(session, svc) == "card_extract_invalid"
        assert [row[2] for row in fake.calls] == [False, True]
        assert stage_keys(session, started.attempt_id) == set()
        assert_failed(session, started, "card_extract_invalid")


def test_b33_quote_failure_is_still_not_repaired(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world_v4(
            session, monkeypatch, overrides={("extract", 0): _quote_not_in_source})
        assert run_code(session, svc) == "card_extract_invalid"
        assert fake.calls == [("card-extract-v2", "extract", False)]
        assert stage_keys(session, started.attempt_id) == set()
        assert_failed(session, started, "card_extract_invalid")


def test_b33_mock_v4_run_completes_with_v2_answers(flow_engine, monkeypatch) -> None:
    """T11 shape for v4: the mock answers the v2 schema; code derives concepts and operators."""

    from app.deep_review.contracts import validate_payload
    from app.deep_review.services import verdict_view
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V4)
        tp.approve(session, policy_identity=RL_V4)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        frozen = session.get(DeepReviewPreview, started.preview_id).input_snapshot
        batches = batch_count(session, started)
        answers: list[dict] = []
        original = MockCardAnalysisClient.invoke_prompt

        def recording(self, prompt: str, *, contract: str):
            result = original(self, prompt, contract=contract)
            answers.append((contract, result.structured_output))
            return result

        monkeypatch.setattr(MockCardAnalysisClient, "invoke_prompt", recording)

        run(session, _plain_service())

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert [contract for contract, _output in answers] == (
            ["card-extract-v2"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"])
        for contract, output in answers[:batches]:
            validate_payload(output, "requirement-extract-v2")
            assert all("concept_candidates" not in item for item in output["items"])
        assert audits(session, "analysis.transfer.sent") == []
        knowledge = resolve_company_knowledge_context(session, world.company_id)
        expected = _expected_by_unit(frozen, knowledge.ontology)
        items = [item for row in _extract_rows(session, started.attempt_id) for item in row.payload["items"]]
        assert [item["unit_id"] for item in items] == [unit["unit_id"] for unit in frozen["card_analysis"]["units"]]
        assert all(item["concept_candidates"] == expected[item["unit_id"]] for item in items)
        assert any(item["concept_candidates"] for item in items)
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"
        assert view["result"]["verdict"] == "판단 불가"


# --- 결정 B35: policy v5 (same v2 wire), mock with realistic numeric constraints ---------

RL_V5 = "analysis-policy-luna-rl-v5"


def test_b35_mock_v5_run_completes_with_numeric_constraints(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import verdict_view
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V5
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V5)
        tp.approve(session, policy_identity=RL_V5)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        batches = batch_count(session, started)
        prompts: list[dict] = []
        original = MockCardAnalysisClient.invoke_prompt

        def recording(self, prompt: str, *, contract: str):
            prompts.append(json.loads(prompt) | {"contract": contract})
            return original(self, prompt, contract=contract)

        monkeypatch.setattr(MockCardAnalysisClient, "invoke_prompt", recording)

        run(session, _plain_service())

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert [row["contract"] for row in prompts] == (
            ["card-extract-v2"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"])
        policy = json.loads(RL_LUNA_POLICY_FILE_V5.read_bytes())
        assert prompts[0]["instruction"] == policy["stages"][0]["instruction"]
        constraints = [c for row in _extract_rows(session, started.attempt_id) for item in row.payload["items"]
                       for c in item["constraints"]]
        # the fixture's "추정가격 금150,000,000원(부가세 포함)" is quoted whole and passes the stricter validator
        assert {(c["kind"], c["value"], c["unit"], c["operator"], c["quote"]) for c in constraints} >= {
            ("amount", 150_000_000, "KRW", "eq", "150,000,000원")}
        assert audits(session, "analysis.transfer.sent") == []
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"


def test_b35_truncated_quote_from_the_model_fails_without_repair(flow_engine, monkeypatch) -> None:
    holder: dict = {}

    def truncated(output: dict) -> dict:
        # "150,000,000" of "금150,000,000원": the unit word is cut off (count, unit null -> passes the old rules)
        units = {unit["unit_id"]: unit for unit in holder["fake"].envelopes[-1]["input"]["units"]}
        for item in output["items"]:
            for block in units[item["unit_id"]]["blocks"]:
                if "150,000,000원" in block["text"]:
                    item["constraints"] = [{"kind": "count", "value": 150000000, "unit": None, "fact_key": None,
                                            "quote": "150,000,000", "locator": {
                                                "source_sha256": item["evidence"][0]["source_sha256"],
                                                "block_key": block["block_key"]}}]
                    holder["hit"] = True
        return output

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V5)
        tp.approve(session, policy_identity=RL_V5)
        started = tp.start(session, world)
        knowledge = resolve_company_knowledge_context(session, world.company_id)
        fake = FakeLuna(knowledge.ontology, {("extract", 0): truncated})
        holder["fake"] = fake
        session.commit()
        svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
        assert run_code(session, svc) == "card_extract_invalid"
        assert holder.get("hit") is True
        assert [row[2] for row in fake.calls] == [False]  # evidence failure: no repair
        assert_failed(session, started, "card_extract_invalid")


# --- 결정 B37: policy v6 (unique numeric quotes, same v2 wire) ------------------------

RL_V6 = "analysis-policy-luna-rl-v6"


def test_b37_mock_v6_run_completes_with_unique_numeric_quotes(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import verdict_view
    from app.deep_review.services.card_analysis import constraint_quote_occurrences
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V6
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V6)
        tp.approve(session, policy_identity=RL_V6)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        frozen = session.get(DeepReviewPreview, started.preview_id).input_snapshot
        batches = batch_count(session, started)
        prompts: list[dict] = []
        original = MockCardAnalysisClient.invoke_prompt

        def recording(self, prompt: str, *, contract: str):
            prompts.append(json.loads(prompt) | {"contract": contract})
            return original(self, prompt, contract=contract)

        monkeypatch.setattr(MockCardAnalysisClient, "invoke_prompt", recording)

        run(session, _plain_service())

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert [row["contract"] for row in prompts] == (
            ["card-extract-v2"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"])
        assert prompts[0]["instruction"] == json.loads(RL_LUNA_POLICY_FILE_V6.read_bytes())["stages"][0]["instruction"]
        blocks = {block["block_key"]: block["text"] for unit in frozen["card_analysis"]["units"]
                  for block in unit["blocks"]}
        constraints = [c for row in _extract_rows(session, started.attempt_id) for item in row.payload["items"]
                       for c in item["constraints"]]
        assert ("amount", 150_000_000, "KRW", "eq", "150,000,000원") in {
            (c["kind"], c["value"], c["unit"], c["operator"], c["quote"]) for c in constraints}
        assert all(constraint_quote_occurrences(c["quote"], blocks[c["locator"]["block_key"]]) == 1
                   for c in constraints)
        assert audits(session, "analysis.transfer.sent") == []
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"


# --- proposed company fact: never evidence, a role cannot use it ----------------------

CREDIT_TEXT = "소프트웨어사업자(컴퓨터관련서비스사업)로 신고한 자 및 신용평가등급 BB 이상인 자"


def _with_credit_requirement(monkeypatch) -> None:
    original = tp._structure_blocks

    def blocks():
        rows = original()
        for row in rows:
            if row["block_key"] == "b-eligibility":
                row["text"] = CREDIT_TEXT
        return rows

    monkeypatch.setattr(tp, "_structure_blocks", blocks)


def _credit_constraint(output: dict) -> dict:
    for item in output["items"]:
        if item["type"] == "자격":
            item["constraints"].append({
                "kind": "text", "value": "BB", "unit": None, "operator": "gte", "fact_key": None,
                "quote": "신용평가등급 BB 이상",
                "locator": {"source_sha256": item["evidence"][0]["source_sha256"], "block_key": "b-eligibility"},
            })
    return output


def _treat_proposed_as_met(output: dict) -> dict:
    for finding in output["unit_findings"]:
        finding["assessment"] = "met"
    return output


def test_t5_proposed_fact_is_marked_and_never_sent(flow_engine, monkeypatch) -> None:
    _with_credit_requirement(monkeypatch)
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(
            session, monkeypatch, overrides={("extract", 0): _credit_constraint})
        run(session, svc)
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        compare_rows = session.scalars(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "compare")).all()
        items = [item for row in compare_rows for item in row.payload["items"]
                 if any(result["reason_code"] == "proposed_fact" for result in item["constraint_results"])]
        assert len(items) == 1
        item = items[0]
        assert item["fit_status"] == "unknown" and "proposed_fact" in item["reason_codes"]
        assert item["constraint_results"][-1]["fact_ids"] == ["qual:credit_rating"]
        assert item["evidence_ids"] == []  # a proposed value is never company evidence
        joined = "\n".join(fake.prompts)
        assert "BBB0" not in joined and "창업 7년" not in joined
        assert '{"fact_key":"qual:credit_rating","status":"proposed"}' in joined
        preview = session.get(DeepReviewPreview, started.preview_id)
        referenced = assert_payload_fact_subsets(fake, preview.input_snapshot)
        # sent (key+status only) where referenced: the eligibility role and the synthesis union
        assert "qual:credit_rating" in referenced["eligibility_economics"]
        assert "qual:credit_rating" in referenced["synthesis"]
        assert "qual:credit_rating" not in referenced["technical_fit"]


def test_t5_role_that_treats_a_proposed_fact_as_met_is_rejected(flow_engine, monkeypatch) -> None:
    _with_credit_requirement(monkeypatch)
    with Session(flow_engine) as session:
        _world, started, svc, _fake, _approval = start_world(session, monkeypatch, overrides={
            ("extract", 0): _credit_constraint, ("eligibility_economics", 0): _treat_proposed_as_met})
        assert run_code(session, svc) == "card_role_invalid"
        assert ("role", "eligibility_economics") not in stage_keys(session, started.attempt_id)
        assert_failed(session, started, "card_role_invalid")


# --- T5: timeout and lease fence (HP-03 T7·T8) ----------------------------------------


def test_t5_timeout_stores_no_late_response(flow_engine, monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(card_analysis, "_monotonic", lambda: clock["now"])

    def late(_fake: FakeLuna, _envelope: dict) -> None:
        clock["now"] += 3601.0  # the response arrives after review_timeout_seconds

    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(session, monkeypatch, on_call=late)
        assert run_code(session, svc) == "card_review_timeout"
        assert len(fake.calls) == 1
        assert stage_keys(session, started.attempt_id) == set()
        assert audits(session, "deep_review.card.raw_response.stored") == []
        assert_failed(session, started, "card_review_timeout")


def test_t5_stolen_lease_stores_no_late_response(flow_engine, monkeypatch) -> None:
    def steal(_fake: FakeLuna, _envelope: dict) -> None:
        # another worker reclaimed the job while the call was in flight
        session_holder["session"].execute(update(WorkJob).values(lease_fence=WorkJob.lease_fence + 1))
        session_holder["session"].commit()

    session_holder: dict[str, Session] = {}
    with Session(flow_engine) as session:
        session_holder["session"] = session
        _world, started, svc, fake, _approval = start_world(session, monkeypatch, on_call=steal)
        claim = svc.claim_next_job(session, "worker-rl-card")
        with pytest.raises(StaleFenceError):
            svc.run_claim(session, claim)
        assert len(fake.calls) == 1
        assert stage_keys(session, started.attempt_id) == set()
        assert audits(session, "deep_review.card.raw_response.stored") == []
        # the stale worker does not fail or complete the attempt it no longer owns
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "running"


# --- payload guard at the call site ----------------------------------------------------


def test_t5_oversized_prompt_fails_closed_without_any_send(flow_engine, monkeypatch) -> None:
    # Same rule as the 100,000-character cap at a size this fixture reaches; nothing is truncated.
    monkeypatch.setattr(card_analysis, "PROMPT_CHARACTER_LIMIT", 1000)
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(session, monkeypatch)
        assert run_code(session, svc) == "prompt_rejected"
        assert fake.calls == [] and fake.prompts == []
        assert stage_keys(session, started.attempt_id) == set()
        assert audits(session, "deep_review.card.raw_response.stored") == []
        assert_failed(session, started, "prompt_rejected")


def test_t5_payload_guard_violation_fails_closed_before_any_call(flow_engine, monkeypatch) -> None:
    real = company_analysis_input.card_extract_transfer

    def leaking(frozen, batch_index, ontology, *, operational_values=(), **kwargs):
        payload = real(frozen, batch_index, ontology, operational_values=operational_values, **kwargs)
        payload["units"][0]["blocks"][0]["text"] += str(operational_values[0])  # approval id in the payload
        check_card_transfer_payload("extract", payload, frozen, operational_values=operational_values)
        return payload

    monkeypatch.setattr(company_analysis_input, "card_extract_transfer", leaking)
    with Session(flow_engine) as session:
        _world, started, svc, fake, _approval = start_world(session, monkeypatch)
        assert run_code(session, svc) == "company_input_invalid"
        assert fake.calls == []
        assert stage_keys(session, started.attempt_id) == set()
        assert_failed(session, started, "company_input_invalid")


# --- 결정 B16: deterministic mock card client (reference mode, no transmission) -----------


def _provider(monkeypatch, value: str) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("BIDOPS_ANALYSIS_PROVIDER", value)
    get_settings.cache_clear()


def _plain_service() -> DeepReviewService:
    # no injected client: the configured provider decides (mock → mock card client)
    return DeepReviewService(structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())


def _count_mock_calls(monkeypatch) -> list[str]:
    from app.deep_review.services.mock_analysis_client import MockCardAnalysisClient

    calls: list[str] = []
    original = MockCardAnalysisClient.invoke_prompt

    def recording(self, prompt: str, *, contract: str):
        calls.append(contract)
        return original(self, prompt, contract=contract)

    monkeypatch.setattr(MockCardAnalysisClient, "invoke_prompt", recording)
    return calls


def test_b16_mock_run_completes_without_transfer_and_reads_mock_reference(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import transfer_policy, verdict_view
    from app.deep_review.services.mock_analysis_client import MOCK_MODEL_NAME

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch)
        tp.approve(session)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        creation = audits(session, "deep_review.auto_create")
        assert len(creation) == 1
        assert creation[0].safe_metadata["analysis_provider"] == "mock-analysis"
        assert creation[0].safe_metadata["runtime_model"] == MOCK_MODEL_NAME
        approved = audits(session, "deep_review.external_transfer_approved")
        assert [row.safe_metadata["provider"] for row in approved] == ["mock-analysis"]
        batches = batch_count(session, started)
        calls = _count_mock_calls(monkeypatch)

        run(session, _plain_service())

        attempt = session.get(DeepReviewAttempt, started.attempt_id)
        assert attempt.status == "completed"
        assert session.get(DeepReview, started.review_id).status == "completed"
        assert stage_keys(session, started.attempt_id) == (
            {("extract", str(i)) for i in range(batches)} | {("compare", str(i)) for i in range(batches)}
            | {("role", role) for role in ROLES} | {("synthesis", "final")})
        assert calls == ["card-extract-v1"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"]
        # nothing was transmitted and no model response object exists
        assert audits(session, "analysis.transfer.sent") == []
        assert audits(session, "deep_review.card.raw_response.stored") == []
        assert transfer_policy.today_used(session) == 0
        # quotes are verbatim unit text (validators passed) and no constraint/number was invented
        extract_rows = session.scalars(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "extract")).all()
        assert all(item["constraints"] == [] for row in extract_rows for item in row.payload["items"])
        final = session.scalar(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "synthesis"))
        assert final.payload["verdict"] == "판단 불가"

        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["attempt_id"] == str(started.attempt_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"
        assert view["is_current"] is True and view["stale_reasons"] == []
        assert view["result"]["verdict"] == "판단 불가"


def test_b23_mock_v2_run_completes_with_missing_contract_and_no_proceed(flow_engine, monkeypatch) -> None:
    """T11 shape: the mock reference run now reaches synthesis instead of needs_human_review."""

    from app.deep_review.services import verdict_view

    _without_contract(monkeypatch)
    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch, policy_identity=RL_V2)
        tp.approve(session, policy_identity=RL_V2)
        _provider(monkeypatch, "mock")
        started = tp.start(session, world, _plain_service())
        batches = batch_count(session, started)
        calls = _count_mock_calls(monkeypatch)

        run(session, _plain_service())

        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert calls == ["card-extract-v1"] * batches + ["card-role-v1"] * 3 + ["card-synthesis-v1"]
        assert audits(session, "analysis.transfer.sent") == []
        final = session.scalar(select(CardAnalysisStage).where(
            CardAnalysisStage.attempt_id == started.attempt_id, CardAnalysisStage.stage == "synthesis"))
        assert final.payload["missing_sections"] == ["contract"]
        assert final.payload["verdict"] != "진행 가능"
        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["availability"] == "completed" and view["quality_status"] == "mock_reference"
        assert view["missing_sections"] == ["contract"]
        assert view["result"]["verdict"] == "판단 불가"


def test_b16_real_path_is_unchanged_under_vllm(flow_engine, monkeypatch) -> None:
    """Control: the non-mock creation lineage is codex-exec and the run transmits (one audit)."""

    with Session(flow_engine) as session:
        world, started, svc, fake, _approval = start_world(session, monkeypatch)
        creation = audits(session, "deep_review.auto_create")
        assert creation[0].safe_metadata["analysis_provider"] == "codex-exec"
        run(session, svc)
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert len(audits(session, "analysis.transfer.sent")) == 1
        from app.deep_review.services import verdict_view

        view = verdict_view.verdict_view(session, company_id=world.company_id, notice_id=world.notice_id)
        assert view["quality_status"] == "unmeasured_reference"


# --- 결정 B17: the daily cap counts only attempts that actually transmitted ----------------


def test_b17_two_mock_attempts_leave_a_cap_of_two_free_for_a_real_attempt(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import transfer_policy

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch)
        tp.approve(session, daily_cap=2)
        _provider(monkeypatch, "mock")
        for _ in range(2):
            started = tp.start(session, world, _plain_service())
            run(session, _plain_service())
            assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
        assert transfer_policy.today_used(session) == 0
        assert audits(session, "analysis.transfer.sent") == []

        _provider(monkeypatch, "vllm")
        real = tp.start(session, world)
        attempt = session.get(DeepReviewAttempt, real.attempt_id)
        assert attempt.status == "queued"
        approved = [row for row in audits(session, "deep_review.external_transfer_approved")
                    if row.aggregate_id == str(real.attempt_id)]
        assert [row.safe_metadata["provider"] for row in approved] == ["codex-exec"]


def test_b17_two_transmitted_attempts_refuse_the_third(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import transfer_policy

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch)
        tp.approve(session, daily_cap=2)
        knowledge = resolve_company_knowledge_context(session, world.company_id)
        session.commit()
        fake = FakeLuna(knowledge.ontology)
        svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
        for expected_used in (1, 2):
            started = tp.start(session, world)
            run(session, svc)
            assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
            assert transfer_policy.today_used(session) == expected_used
        attempts_before = session.scalar(select(func.count()).select_from(DeepReviewAttempt))
        assert tp.start_code(session, world) == "daily_cap_reached"
        assert session.scalar(select(func.count()).select_from(DeepReviewAttempt)) == attempts_before


def test_b17_worker_rechecks_the_cap_before_the_transfer_audit(flow_engine, monkeypatch) -> None:
    from app.deep_review.services import transfer_policy

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch)
        first_approval = tp.approve(session, daily_cap=2)
        knowledge = resolve_company_knowledge_context(session, world.company_id)
        session.commit()
        fake = FakeLuna(knowledge.ontology)
        svc = DeepReviewService(client=fake, structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
        tp.start(session, world)
        run(session, svc)  # transmitted: today_used == 1
        second = tp.start(session, world)  # admitted under cap 2 (1 sent + 0 in flight)
        # the operator lowers the cap to 1 before the worker picks the queued attempt up
        transfer_policy.revoke_transfer_policy(session, approval_id=UUID(first_approval["approval_id"]),
                                               actor="jechoi", reason="상한 축소")
        session.commit()
        tp.approve(session, daily_cap=1)
        calls_before = len(fake.calls)
        assert run_code(session, svc) == "daily_cap_reached"
        assert session.get(DeepReviewAttempt, second.attempt_id).status == "failed"
        assert len(fake.calls) == calls_before
        assert [row.aggregate_id for row in audits(session, "analysis.transfer.sent")] != [] and all(
            row.aggregate_id != str(second.attempt_id) for row in audits(session, "analysis.transfer.sent"))
        assert transfer_policy.today_used(session) == 1


def test_b25_invalid_runner_endpoint_fails_before_the_transfer_audit(flow_engine, monkeypatch) -> None:
    """결정 B25: a misconfigured runner URL (e.g. "rla-codex-runner") must not record a send or use the cap."""

    from app.deep_review.services import transfer_policy

    with Session(flow_engine) as session:
        world = tp.build_world(session, monkeypatch)
        tp.approve(session, daily_cap=2)
        session.commit()
        svc = DeepReviewService(structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
        svc.settings = svc.settings.model_copy(update={"luna_runner_url": "http://rla-codex-runner:8091"})
        started = tp.start(session, world)
        assert run_code(session, svc) == "runner_unavailable"
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "failed"
        assert all(row.aggregate_id != str(started.attempt_id) for row in audits(session, "analysis.transfer.sent"))
        assert transfer_policy.today_used(session) == 0
