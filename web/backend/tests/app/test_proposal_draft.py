"""RL-04 STEP-005 T4/T5: draft creation gates, section worker, state machine, cap, audit, mock path.

World: the real Rootlab v2 company (outside Git) with a completed RL-03 card-v1
verdict (the real worker with the scripted fake Luna of the RL-03 suite, or the
reference-mode mock card client on policy v6), the opportunity linked to that
pre-spec, the imported ``proposal-policy-luna-v1`` row selected by
``BIDOPS_PROPOSAL_POLICY_VERSION_ID`` and a proposal transfer approval.

The proposal worker runs for real; the Luna transport is a scripted fake
(``FakeProposalLuna``) injected into ``ProposalWorker`` or, for the mock
provider, the product's ``MockProposalClient``.  ``LunaClient`` construction and
every other model transport fail the test (autouse guard).  Runs on SQLite and,
with ``BIDOPS_TEST_POSTGRES_URL``, on migrated PostgreSQL 17; the runtime-role
matrix (``SET ROLE app``/``worker`` with ``scripts/runtime-privileges.sql``) is
PostgreSQL only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import _json_serializer, schema_bound
from app.core.model_client import InvocationResult, ModelInvocationError
from app.core.models import AuditEvent
from app.deep_review.models import (
    ProposalDraft,
    ProposalSection,
    TransferPolicyApproval,
    WorkJob,
)
from app.deep_review.services import transfer_policy as tpol
from app.deep_review.services.deep_reviews import DeepReviewService
from app.deep_review.services.input_versions import PROPOSAL_LUNA_POLICY_FILE, PROPOSAL_SECTION_KEYS, import_policy_version
from app.deep_review.services.mock_proposal_client import mock_section
from app.deep_review.services.proposal_draft import (
    ProposalServiceError,
    create_proposal_draft,
    latest_sections,
    request_section_regeneration,
)
from app.deep_review.services.proposal_validation import validate_proposal_section
from app.deep_review.services.proposal_worker import ProposalWorker
from app.lifecycle.models import Opportunity, OpportunityLink
from tests.app import test_transfer_policy as rl_tp
from tests.app.test_deep_reviews import _FixtureStore
from tests.app.test_verdict_trigger_postgres import flow_engine, no_model_transport  # noqa: F401
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401
from tests.postgres import requires_postgres, temporary_database


pytestmark = rl_tp.needs_rootlab

ACTOR = "jechoi"
SENT = "analysis.transfer.sent"


# --- world -------------------------------------------------------------------------------------


def _proposal_policy(session: Session, monkeypatch, *, daily_cap: int = 3, approve: bool = True):
    policy = import_policy_version(session, PROPOSAL_LUNA_POLICY_FILE, created_by_name=ACTOR,
                                   label="proposal-policy-luna-v1")
    session.commit()
    monkeypatch.setenv("BIDOPS_PROPOSAL_POLICY_VERSION_ID", str(policy.id))
    get_settings.cache_clear()
    approval = None
    if approve:
        approval = tpol.approve_transfer_policy(session, policy_identity="proposal-policy-luna-v1", actor=ACTOR,
                                                daily_cap=daily_cap)
        session.commit()
    return policy, approval


def verdict_world(session: Session, monkeypatch, *, run_verdict: bool = True, daily_cap: int = 3,
                  approve: bool = True) -> SimpleNamespace:
    """Completed RL-03 card-v1 verdict (fake Luna, policy v1) + proposal policy/approval."""

    from tests.app.test_verdict_api import run_completed, start, started_world

    world, seeded, _item = started_world(session, monkeypatch)
    started = run_completed(session, world, seeded) if run_verdict else None
    policy, approval = _proposal_policy(session, monkeypatch, daily_cap=daily_cap, approve=approve)
    return SimpleNamespace(world=world, seeded=seeded, started=started, policy=policy, approval=approval,
                           opportunity_id=seeded.opportunity_id, notice_id=seeded.notice_id,
                           run_verdict=lambda: run_completed(session, world, seeded), start=start)


def _provider(monkeypatch, value: str) -> None:
    monkeypatch.setenv("BIDOPS_ANALYSIS_PROVIDER", value)
    get_settings.cache_clear()


def create(session: Session, w, *, request_id=None, actor: str = ACTOR) -> dict:
    return create_proposal_draft(session, opportunity_id=w.opportunity_id, actor=actor,
                                 request_id=request_id or uuid4())


def create_code(session: Session, w, **kwargs) -> str:
    with pytest.raises(ProposalServiceError) as error:
        create(session, w, **kwargs)
    return error.value.code


class FakeProposalLuna:
    """Scripted ``proposal-section-v1`` transport; records prompts and the sent audits seen at each call."""

    def __init__(self, engine, script=None) -> None:
        self.engine = engine
        self.script = {key: list(steps) for key, steps in (script or {}).items()}
        self.prompts: list[dict] = []
        self.sent_at_call: list[int] = []

    def invoke_prompt(self, prompt: str, *, contract: str) -> InvocationResult:
        envelope = json.loads(prompt)
        payload = envelope["input"]
        self.prompts.append({**envelope, "contract": contract})
        with Session(self.engine) as probe:
            self.sent_at_call.append(int(probe.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == SENT, AuditEvent.aggregate_type == "proposal_section")) or 0))
        steps = self.script.get(payload["section_key"]) or []
        step = steps.pop(0) if steps else None
        if isinstance(step, Exception):
            raise step
        output = step(payload) if step is not None else mock_section(payload)
        raw = json.dumps(output, ensure_ascii=False).encode("utf-8")
        return InvocationResult(output, raw, hashlib.sha256(prompt.encode()).hexdigest(),
                                hashlib.sha256(raw).hexdigest(), 11, 22, 5, (), "codex-exec", "gpt-6-luna")


def worker(fake=None, *, clock=None) -> ProposalWorker:
    base = DeepReviewService(raw_response_store=_FixtureStore(), **({"clock": clock} if clock else {}))
    return ProposalWorker(base=base, client=fake)


def run_all(session: Session, proposal_worker: ProposalWorker, *, limit: int = 20) -> int:
    claimed = 0
    for _ in range(limit):
        if not proposal_worker.run_once(session, "worker-proposal"):
            break
        claimed += 1
    return claimed


def count(session: Session, model, *where) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def audits(session: Session, action: str) -> list[AuditEvent]:
    return session.scalars(select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.created_at)).all()


def proposal_sent(session: Session) -> list[AuditEvent]:
    return session.scalars(select(AuditEvent).where(
        AuditEvent.action == SENT, AuditEvent.aggregate_type == "proposal_section",
    ).order_by(AuditEvent.created_at)).all()


def _first_statement(output: dict) -> dict:
    return next(s for p in output["paragraphs"] for s in p["sentences"] if s["kind"] == "statement")


def forbidden_staffing(payload: dict) -> dict:
    output = mock_section(payload)
    _first_statement(output)["text"] = "디자인 인력 3명 투입으로 수행한다."
    return output


def missing_sources(payload: dict) -> dict:
    output = mock_section(payload)
    _first_statement(output)["sources"] = []
    return output


def bad_quote(payload: dict) -> dict:
    output = mock_section(payload)
    _first_statement(output)["sources"][0]["quote"] = "원문에 없는 인용"
    return output


# --- T4: creation gates -------------------------------------------------------------------------


def test_t4_creation_gate_order_one_transaction_and_replay(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, run_verdict=False, daily_cap=2, approve=False)
        with pytest.raises(ProposalServiceError) as error:
            create_proposal_draft(session, opportunity_id=999_999, actor=ACTOR, request_id=uuid4())
        assert error.value.code == "opportunity_not_found" and error.value.status_code == 404
        assert create_code(session, w, actor=" ") == "actor_name_required"
        # approval before flags and verdict
        monkeypatch.setenv("BIDOPS_LUNA_DEEP_REVIEW_ENABLED", "false")
        get_settings.cache_clear()
        assert create_code(session, w) == "policy_not_approved"
        tpol.approve_transfer_policy(session, policy_identity="proposal-policy-luna-v1", actor=ACTOR, daily_cap=2)
        session.commit()
        # flags before the verdict
        assert create_code(session, w) == "service_unavailable"
        monkeypatch.setenv("BIDOPS_LUNA_DEEP_REVIEW_ENABLED", "true")
        get_settings.cache_clear()
        # no card-v1 attempt yet, then a queued one: no completed verdict
        assert create_code(session, w) == "verdict_required"
        started = w.start(session, w.world, w.seeded)
        assert create_code(session, w) == "verdict_required"
        assert count(session, ProposalDraft) == count(session, ProposalSection) == 0
        assert count(session, WorkJob, WorkJob.job_type == "proposal_section") == 0
        from tests.app.test_card_analysis_postgres import run
        from tests.app.test_verdict_api import worker as card_worker

        run(session, card_worker(session))
        session.commit()

        request_id = uuid4()
        created = create(session, w, request_id=request_id)
        assert created == {"draft_id": created["draft_id"], "status": "queued", "created": True}
        draft = session.get(ProposalDraft, UUID(created["draft_id"]))
        assert (draft.status, draft.stage, draft.verdict_attempt_id) == ("queued", "toc", started.attempt_id)
        assert draft.policy_version_id == w.policy.id and draft.created_by == ACTOR
        sections = session.scalars(select(ProposalSection).where(ProposalSection.draft_id == draft.id)).all()
        assert sorted(row.section_key for row in sections) == sorted(PROPOSAL_SECTION_KEYS)
        assert {(row.revision, row.status, row.payload) for row in sections} == {(1, "queued", None)}
        jobs = session.scalars(select(WorkJob).where(WorkJob.job_type == "proposal_section")).all()
        assert len(jobs) == 6 and {job.aggregate_id for job in jobs} == {row.id for row in sections}
        assert {(job.status, job.aggregate_type, job.max_attempts) for job in jobs} == {("queued", "proposal_section", 1)}
        creation = audits(session, "proposal.draft.created")
        assert len(creation) == 1 and creation[0].request_id == str(request_id)
        assert creation[0].safe_metadata["provider"] == "codex-exec"
        assert creation[0].safe_metadata["quality_status"] == "unmeasured_reference"
        # replay: same draft, created=False; another actor is a conflict; nothing new
        replay = create(session, w, request_id=request_id)
        assert replay == {"draft_id": created["draft_id"], "status": "queued", "created": False}
        assert create_code(session, w, request_id=request_id, actor="other") == "idempotency_conflict"
        # a queued draft is in progress (cap 2 = 12 units: 6 reserved + 6 still fit)
        assert create_code(session, w) == "draft_in_progress"
        assert count(session, ProposalDraft) == 1 and count(session, ProposalSection) == 6


# --- T5: worker ---------------------------------------------------------------------------------


def test_t5_six_sections_complete_with_one_audit_each_before_the_first_call(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        fake = FakeProposalLuna(flow_engine)
        assert run_all(session, worker(fake)) == 6
        draft = session.get(ProposalDraft, draft_id)
        assert (draft.status, draft.stage) == ("completed", "draft")
        assert draft.started_at is not None and draft.completed_at is not None
        sections = latest_sections(session, draft_id)
        assert {row.status for row in sections.values()} == {"completed"}
        for row in sections.values():
            assert row.input_sha256 and row.result_sha256 and row.payload["section_key"] == row.section_key
            assert (row.prompt_tokens, row.output_tokens, row.latency_ms) == (11, 22, 5)
        # one call per section with the proposal contract; the audit of that section is
        # already committed when its first (and only) call starts.
        assert [p["contract"] for p in fake.prompts] == ["proposal-section-v1"] * 6
        assert [p["stage"] for p in fake.prompts] == list(PROPOSAL_SECTION_KEYS)
        assert fake.sent_at_call == [1, 2, 3, 4, 5, 6]
        assert all(set(p["input"]) == {"section_key", "notice_meta", "units", "compares", "verdict",
                                       "company_facts", "missing_facts", "toc_reference"} for p in fake.prompts)
        sent = proposal_sent(session)
        assert len(sent) == 6 and {row.aggregate_type for row in sent} == {"proposal_section"}
        assert {row.safe_metadata["purpose"] for row in sent} == {"proposal"}
        assert {row.safe_metadata["input_sha256"] for row in sent} == {row.input_sha256 for row in sections.values()}
        assert len(audits(session, "proposal.section.raw_response.stored")) == 6
        assert {job.status for job in session.scalars(select(WorkJob).where(
            WorkJob.job_type == "proposal_section"))} == {"completed"}
        assert tpol.proposal_cap_usage(session) == (6, 0)
        # RL-03's own cap never counts proposal sections
        assert tpol.today_used(session) == 1


def test_t5_one_failed_section_keeps_the_others_and_the_draft_is_partial(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        fake = FakeProposalLuna(flow_engine, {"requirements": [forbidden_staffing]})
        run_all(session, worker(fake))
        sections = latest_sections(session, draft_id)
        failed = sections["requirements"]
        assert (failed.status, failed.error_code, failed.payload) == ("failed", "proposal_forbidden_content", None)
        assert failed.input_sha256 is not None and failed.result_sha256 is None
        assert {row.status for key, row in sections.items() if key != "requirements"} == {"completed"}
        assert session.get(ProposalDraft, draft_id).status == "partial"
        # forbidden content is evidence-class: one call, no repair
        assert [p["stage"] for p in fake.prompts].count("requirements") == 1
        failure = audits(session, "proposal.section.failed")[0].safe_metadata
        assert failure["error_code"] == "proposal_forbidden_content" and failure["rule_codes"] == ["forbidden_staffing"]
        assert "명 투입" not in json.dumps(failure, ensure_ascii=False)
        job = session.scalar(select(WorkJob).where(WorkJob.aggregate_id == failed.id))
        assert (job.status, job.last_error_code) == ("failed", "proposal_forbidden_content")


def test_t5_schema_class_failure_gets_one_repair_with_codes_only(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        fake = FakeProposalLuna(flow_engine, {
            "requirements": [missing_sources],
            "overview": [ModelInvocationError("schema_invalid", (), b'{"broken": true}')],
        })
        run_all(session, worker(fake))
        sections = latest_sections(session, draft_id)
        assert {row.status for row in sections.values()} == {"completed"}
        assert session.get(ProposalDraft, draft_id).status == "completed"
        requirements = [p for p in fake.prompts if p["stage"] == "requirements"]
        assert len(requirements) == 2 and "validation_repair" not in requirements[0]
        repair = requirements[1]["validation_repair"]
        assert repair["scope"] == "syntax_or_schema_only" and repair["rule_codes"] == ["statement_sources_required"]
        assert all(set(row) == {"rule_code", "paragraph_index", "sentence_index", "source_index", "link_index",
                                "unit_index"} for row in repair["violations"])
        overview = [p for p in fake.prompts if p["stage"] == "overview"]
        assert len(overview) == 2 and overview[1]["validation_repair"]["rule_codes"] == ["output_schema"]
        # still exactly one transfer audit per section; the rejected answer is kept encrypted
        assert len(proposal_sent(session)) == 6
        assert len(audits(session, "proposal.section.raw_response.stored")) == 8
        completed = {row.safe_metadata["section_key"]: row.safe_metadata for row in audits(
            session, "proposal.section.completed")}
        assert completed["requirements"]["call_count"] == 2 and completed["requirements"]["repair_count"] == 1


def test_t5_evidence_failure_and_a_second_schema_failure_are_not_repaired(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        fake = FakeProposalLuna(flow_engine, {
            "requirements": [bad_quote],
            "overview": [missing_sources, missing_sources],
            "strategy": [ModelInvocationError("runner_failed", ())],
        })
        run_all(session, worker(fake))
        sections = latest_sections(session, draft_id)
        assert (sections["requirements"].status, sections["requirements"].error_code) == (
            "failed", "proposal_section_invalid")
        assert [p["stage"] for p in fake.prompts].count("requirements") == 1
        assert (sections["overview"].status, sections["overview"].error_code) == ("failed", "proposal_section_invalid")
        assert [p["stage"] for p in fake.prompts].count("overview") == 2
        assert (sections["strategy"].status, sections["strategy"].error_code) == ("failed", "runner_failed")
        assert [p["stage"] for p in fake.prompts].count("strategy") == 1
        assert session.get(ProposalDraft, draft_id).status == "partial"


def test_t5_regeneration_is_a_new_revision_and_resettles_the_draft(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, daily_cap=2)
        draft_id = UUID(create(session, w)["draft_id"])
        run_all(session, worker(FakeProposalLuna(flow_engine, {"requirements": [bad_quote]})))
        assert session.get(ProposalDraft, draft_id).status == "partial"
        first = latest_sections(session, draft_id)["requirements"]
        request_id = uuid4()
        regenerated = request_section_regeneration(session, draft_id=draft_id, section_key="requirements",
                                                   actor=ACTOR, request_id=request_id)
        assert regenerated["revision"] == 2 and regenerated["created"] is True
        assert request_section_regeneration(session, draft_id=draft_id, section_key="requirements", actor=ACTOR,
                                            request_id=request_id)["created"] is False
        with pytest.raises(ProposalServiceError) as error:
            request_section_regeneration(session, draft_id=draft_id, section_key="requirements", actor=ACTOR,
                                         request_id=uuid4())
        assert error.value.code == "section_in_progress"
        for key in ("pricing", "requirements"):
            with pytest.raises(ProposalServiceError) as error:
                request_section_regeneration(session, draft_id=uuid4() if key == "requirements" else draft_id,
                                             section_key=key, actor=ACTOR, request_id=uuid4())
            assert error.value.code == "not_found"
        # a regeneration costs one unit: 6 transmitted + 1 in flight
        assert tpol.proposal_cap_usage(session) == (6, 1)
        fake = FakeProposalLuna(flow_engine)
        assert run_all(session, worker(fake)) == 1
        sections = latest_sections(session, draft_id)
        assert sections["requirements"].revision == 2 and sections["requirements"].status == "completed"
        old = session.get(ProposalSection, first.id)
        assert (old.revision, old.status, old.error_code) == (1, "failed", "proposal_section_invalid")
        assert session.get(ProposalDraft, draft_id).status == "completed"
        assert tpol.proposal_cap_usage(session) == (7, 0)


def test_t5_new_draft_supersedes_and_superseded_is_not_regenerated(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, daily_cap=3)
        first = UUID(create(session, w)["draft_id"])
        run_all(session, worker(FakeProposalLuna(flow_engine)))
        second = UUID(create(session, w)["draft_id"])
        assert session.get(ProposalDraft, first).status == "superseded"
        assert session.get(ProposalDraft, second).status == "queued"
        with pytest.raises(ProposalServiceError) as error:
            request_section_regeneration(session, draft_id=first, section_key="overview", actor=ACTOR,
                                         request_id=uuid4())
        assert error.value.code == "stage_transition_invalid"
        # cap 3 = 18 units: 6 transmitted + 6 reserved + 6 still fit, so the in-progress gate answers
        assert create_code(session, w) == "draft_in_progress"


def test_t5_draft_review_timeout_fails_the_remaining_sections_without_a_call(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        now = [datetime.now(UTC)]
        fake = FakeProposalLuna(flow_engine)
        proposal_worker = worker(fake, clock=lambda: now[0])
        assert proposal_worker.run_once(session, "worker-proposal") is True
        assert latest_sections(session, draft_id)["overview"].status == "completed"
        now[0] = now[0] + timedelta(seconds=5401)
        assert proposal_worker.run_once(session, "worker-proposal") is True
        sections = latest_sections(session, draft_id)
        assert {key: row.status for key, row in sections.items()} == {
            "overview": "completed", **{key: "failed" for key in PROPOSAL_SECTION_KEYS[1:]}}
        assert {row.error_code for key, row in sections.items() if key != "overview"} == {"proposal_review_timeout"}
        assert len(fake.prompts) == 1 and len(proposal_sent(session)) == 1
        assert session.get(ProposalDraft, draft_id).status == "partial"
        assert proposal_worker.run_once(session, "worker-proposal") is False
        assert {job.last_error_code for job in session.scalars(select(WorkJob).where(
            WorkJob.job_type == "proposal_section", WorkJob.status == "failed"))} == {"proposal_review_timeout"}


def test_t5_endpoint_is_checked_before_the_transfer_audit(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        monkeypatch.setenv("BIDOPS_LUNA_RUNNER_URL", "http://rla-codex-runner:8091")
        get_settings.cache_clear()
        assert worker().run_once(session, "worker-proposal") is True
        overview = latest_sections(session, draft_id)["overview"]
        assert (overview.status, overview.error_code) == ("failed", "runner_unavailable")
        assert proposal_sent(session) == [] and tpol.proposal_cap_usage(session) == (0, 5)


def test_t5_cap_counts_six_per_draft_one_per_regeneration_and_the_worker_rechecks(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, daily_cap=1)
        draft_id = UUID(create(session, w)["draft_id"])
        assert tpol.proposal_cap_usage(session) == (0, 6)
        run_all(session, worker(FakeProposalLuna(flow_engine, {"strategy": [bad_quote]})))
        assert tpol.proposal_cap_usage(session) == (6, 0)
        with pytest.raises(ProposalServiceError) as error:
            request_section_regeneration(session, draft_id=draft_id, section_key="strategy", actor=ACTOR,
                                         request_id=uuid4())
        assert error.value.code == "daily_cap_reached"
        assert create_code(session, w) == "daily_cap_reached"
        assert count(session, ProposalSection) == 6


def test_t5_revoked_approval_stops_the_worker_before_any_audit(flow_engine, monkeypatch) -> None:  # noqa: F811
    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch)
        draft_id = UUID(create(session, w)["draft_id"])
        tpol.revoke_transfer_policy(session, approval_id=UUID(w.approval["approval_id"]), actor=ACTOR,
                                    reason="시험 철회")
        session.commit()
        fake = FakeProposalLuna(flow_engine)
        run_all(session, worker(fake))
        assert {row.error_code for row in latest_sections(session, draft_id).values()} == {"policy_not_approved"}
        assert fake.prompts == [] and proposal_sent(session) == []
        assert session.get(ProposalDraft, draft_id).status == "failed"


# --- mock end to end on a real RL-03 v6 mock verdict -----------------------------------------------


def mock_verdict_world(session: Session, monkeypatch) -> SimpleNamespace:
    from tests.app.test_card_analysis_postgres import _plain_service, run

    world = rl_tp.build_world(session, monkeypatch, policy_identity="analysis-policy-luna-rl-v6")
    rl_tp.approve(session, policy_identity="analysis-policy-luna-rl-v6")
    _provider(monkeypatch, "mock")
    started = rl_tp.start(session, world, _plain_service())
    run(session, _plain_service())
    session.commit()
    opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=world.notice_id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"R26BD{world.notice_id:08d}"))
    session.commit()
    policy, approval = _proposal_policy(session, monkeypatch, daily_cap=1)
    return SimpleNamespace(world=world, started=started, opportunity_id=opportunity.id, notice_id=world.notice_id,
                           policy=policy, approval=approval)


def test_t10_mock_draft_completes_on_a_v6_mock_verdict_without_transfer(flow_engine, monkeypatch) -> None:  # noqa: F811
    from app.deep_review.services.proposal_input import build_proposal_input, load_verdict_sources, notice_meta
    from app.deep_review.workers.proposal import run_once
    from app.lifecycle.models import Notice

    with Session(flow_engine) as session:
        w = mock_verdict_world(session, monkeypatch)
        from app.deep_review.models import DeepReviewAttempt

        assert session.get(DeepReviewAttempt, w.started.attempt_id).status == "completed"
        draft_id = UUID(create(session, w)["draft_id"])
        assert audits(session, "proposal.draft.created")[0].safe_metadata["quality_status"] == "mock_reference"
        # queued mock sections reserve nothing: with cap 1 the in-progress gate (not the cap) answers
        assert tpol.proposal_cap_usage(session) == (0, 0)
        assert create_code(session, w) == "draft_in_progress"
        for _ in range(6):
            assert run_once(session, "worker-proposal") is True
        assert run_once(session, "worker-proposal") is False
        draft = session.get(ProposalDraft, draft_id)
        assert (draft.status, draft.stage) == ("completed", "draft")
        assert proposal_sent(session) == []
        assert audits(session, "proposal.section.raw_response.stored") == []
        assert {row.safe_metadata["quality_status"] for row in audits(session, "proposal.section.completed")} == {
            "mock_reference"}
        # every stored section revalidates against its re-frozen input
        sources = load_verdict_sources(session, w.started.attempt_id)
        notice = session.get(Notice, w.notice_id)
        for key, row in latest_sections(session, draft_id).items():
            value = build_proposal_input(sources, section_key=key, execution_nonce=row.id, draft_id=draft_id,
                                         opportunity_id=w.opportunity_id, notice_id=w.notice_id,
                                         policy_sha256=draft.policy_sha256, notice_meta=notice_meta(notice))
            assert validate_proposal_section(row.payload, section_input=value).ok
        requirements = latest_sections(session, draft_id)["requirements"].payload
        assert requirements["requirement_links"]
        # mock drafts never count against the cap (cap 1): a second mock draft is allowed
        assert tpol.proposal_cap_usage(session) == (0, 0)
        second = create(session, w)
        assert second["status"] == "queued" and session.get(ProposalDraft, draft_id).status == "superseded"
        # a mock-lineage draft is not run by a real-provider worker
        _provider(monkeypatch, "vllm")
        fake = FakeProposalLuna(flow_engine)
        assert worker(fake).run_once(session, "worker-proposal") is True
        assert fake.prompts == []
        failed = [row for row in latest_sections(session, UUID(second["draft_id"])).values() if row.status == "failed"]
        assert [row.error_code for row in failed] == ["model_binding_invalid"]


# --- runtime roles (PostgreSQL) -------------------------------------------------------------------


@requires_postgres
def test_t5_app_and_worker_runtime_roles_run_the_real_paths(monkeypatch) -> None:
    from tests.app.test_runtime_database_privileges import _apply_policy, _ensure_roles
    from app.deep_review.workers.proposal import run_once

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        owner = schema_bound(create_engine(database_url, json_serializer=_json_serializer, future=True))
        engines = {}
        for role in ("app", "worker"):
            base = create_engine(database_url, json_serializer=_json_serializer, future=True)

            @event.listens_for(base, "connect")
            def _role(dbapi_connection, _record, role=role):  # type: ignore[no-untyped-def]
                cursor = dbapi_connection.cursor()
                cursor.execute(f"SET ROLE {role}")
                cursor.close()
                dbapi_connection.commit()

            engines[role] = (base, schema_bound(base))
        try:
            with Session(owner) as session:
                w = mock_verdict_world(session, monkeypatch)
                tpol.revoke_transfer_policy(session, approval_id=UUID(w.approval["approval_id"]), actor=ACTOR,
                                            reason="상한 변경")
                session.commit()
                tpol.approve_transfer_policy(session, policy_identity="proposal-policy-luna-v1", actor=ACTOR,
                                             daily_cap=3)
                session.commit()
            with Session(engines["app"][1]) as session:
                assert session.execute(select(func.current_user())).scalar() == "app"
                draft_id = UUID(create(session, w)["draft_id"])
            with Session(engines["worker"][1]) as session:
                assert session.execute(select(func.current_user())).scalar() == "worker"
                for _ in range(6):
                    assert run_once(session, "worker-proposal") is True
            with Session(engines["app"][1]) as session:
                assert session.get(ProposalDraft, draft_id).status == "completed"
                regenerated = request_section_regeneration(session, draft_id=draft_id, section_key="overview",
                                                           actor=ACTOR, request_id=uuid4())
            with Session(engines["worker"][1]) as session:
                assert run_once(session, "worker-proposal") is True
                assert latest_sections(session, draft_id)["overview"].revision == regenerated["revision"]
                # the worker cannot create rows or move a settled draft back to running
                with pytest.raises(DBAPIError):
                    session.execute(text("UPDATE bidops.proposal_draft SET status = 'running' WHERE id = :id"),
                                    {"id": draft_id})
                session.rollback()
                with pytest.raises(DBAPIError):
                    session.execute(text("INSERT INTO bidops.proposal_section (id, draft_id, section_key, revision,"
                                         " status) VALUES (:id, :draft, 'overview', 9, 'queued')"),
                                    {"id": uuid4(), "draft": draft_id})
                session.rollback()
            with Session(engines["app"][1]) as session:
                # the web role supersedes through a new draft; it cannot settle a draft itself
                with pytest.raises(DBAPIError):
                    session.execute(text("UPDATE bidops.proposal_draft SET status = 'partial' WHERE id = :id"),
                                    {"id": draft_id})
                session.rollback()
                second = UUID(create(session, w)["draft_id"])
            with Session(owner) as session:
                assert session.get(ProposalDraft, draft_id).status == "superseded"
                assert session.get(ProposalDraft, second).status == "queued"
                # role-agnostic trigger rules: queued -> completed and superseded -> any are refused
                for sql in ("UPDATE bidops.proposal_draft SET status = 'completed' WHERE id = :id",):
                    with pytest.raises(DBAPIError, match="invalid proposal draft status transition"):
                        session.execute(text(sql), {"id": second})
                    session.rollback()
                with pytest.raises(DBAPIError, match="superseded proposal draft"):
                    session.execute(text("UPDATE bidops.proposal_draft SET status = 'failed' WHERE id = :id"),
                                    {"id": draft_id})
                session.rollback()
        finally:
            for base, _bound in engines.values():
                base.dispose()
            owner.dispose()
            policy_engine.dispose()


def test_b50_reviewed_or_ready_draft_is_not_regenerated(flow_engine, monkeypatch) -> None:  # noqa: F811
    """Review decision B50: a rewrite after review would leave an unreviewed section under a
    reviewed/ready stage that never moves back, so it is refused; a new draft is still possible."""

    from app.deep_review.services.proposal_view import review_section, set_draft_stage

    with Session(flow_engine) as session:
        w = verdict_world(session, monkeypatch, daily_cap=3)
        draft_id = UUID(create(session, w)["draft_id"])
        run_all(session, worker(FakeProposalLuna(flow_engine)))
        for key in PROPOSAL_SECTION_KEYS[:5]:
            review_section(session, draft_id=draft_id, section_key=key, actor=ACTOR, request_id=uuid4())
        # stage is still "draft": a rewrite is allowed until the last review
        assert session.get(ProposalDraft, draft_id).stage == "draft"
        review_section(session, draft_id=draft_id, section_key=PROPOSAL_SECTION_KEYS[5], actor=ACTOR,
                       request_id=uuid4())
        session.expire_all()
        assert session.get(ProposalDraft, draft_id).stage == "reviewed"
        sections_before = count(session, ProposalSection)
        for stage in ("reviewed", "ready"):
            if stage == "ready":
                set_draft_stage(session, draft_id=draft_id, stage="ready", actor=ACTOR, request_id=uuid4())
            with pytest.raises(ProposalServiceError) as error:
                request_section_regeneration(session, draft_id=draft_id, section_key="overview", actor=ACTOR,
                                             request_id=uuid4())
            assert error.value.code == "stage_transition_invalid" and error.value.status_code == 409
        assert count(session, ProposalSection) == sections_before
        assert count(session, WorkJob, WorkJob.job_type == "proposal_section", WorkJob.status == "queued") == 0
        # the header "다시 만들기" (a new draft) stays available
        second = create(session, w)
        assert second["created"] is True and session.get(ProposalDraft, draft_id).status == "superseded"
