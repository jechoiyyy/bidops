"""RL-04 STEP-003: proposal transfer approval, gate, daily cap (1/6) and audit; verdict source read.

* approve: ``approve-transfer-policy --policy proposal-policy-luna-v1`` binds the
  row selected by ``BIDOPS_PROPOSAL_POLICY_VERSION_ID`` to its immutable file and
  the HP-00 runner identity, writes ``scope={"purposes": ["proposal"]}`` with
  ``daily_cap`` default 3 (1..20); RL-03 approvals and proposal approvals never
  see each other (SQLite and PostgreSQL).
* gate (SQLite, rows without the attempt FK chain): approval → sha → purposes →
  cap, where ``daily_cap`` drafts = ``daily_cap * 6`` section generations, a new
  draft needs 6 and a regeneration 1; usage = transmitted sections today (KST)
  plus, at creation, queued/running sections without a transfer audit.
* audit: one ``analysis.transfer.sent`` per section with ``purpose=proposal`` and
  hashes/ids only.
* integration (real Rootlab world outside Git; SQLite and PostgreSQL): the
  completed card-v1 attempt from the real worker with the scripted fake Luna is
  read through ``load_verdict_sources``, every section input passes the payload
  guard, and a real draft with six queued sections is counted by the gate.

No model transport or network is called.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.cli import approve_transfer_policy as approve_cli
from app.deep_review.models import (
    AnalysisPolicyVersion,
    DeepReviewAttempt,
    DeepReviewPreview,
    ProposalDraft,
    ProposalSection,
    TransferPolicyApproval,
)
from app.deep_review.services import transfer_policy as tpol
from app.deep_review.services.input_versions import (
    PROPOSAL_LUNA_POLICY_FILE,
    PROPOSAL_SECTION_KEYS,
    RL_LUNA_POLICY_FILE_V6,
    import_policy_version,
)
from app.deep_review.services.proposal_input import (
    PROPOSAL_TRANSFER_KEYS,
    ProposalInputError,
    build_proposal_input,
    load_verdict_sources,
    notice_meta,
    proposal_input_sha256,
    proposal_transfer_payload,
)
from app.lifecycle.models import Notice
from tests.postgres import migrated_engine, requires_postgres


KST = tpol.KST
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=KST)


def configure(monkeypatch, **values: str | None) -> None:
    base: dict[str, str | None] = {
        "BIDOPS_PROPOSAL_POLICY_VERSION_ID": None,
        "BIDOPS_PROPOSAL_POLICY_PATH": None,
        "BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID": None,
        "BIDOPS_RL_ANALYSIS_POLICY_PATH": None,
    }
    base.update(values)
    for key, value in base.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture
def sqlite_engine():
    # Isolated SQLite without the app connect hook: foreign keys are not enforced,
    # so draft/section rows need no deep-review attempt chain.
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


def _policies(session: Session, monkeypatch) -> tuple:
    proposal = import_policy_version(session, PROPOSAL_LUNA_POLICY_FILE, created_by_name="jechoi",
                                     label="proposal-policy-luna-v1")
    rl = import_policy_version(session, RL_LUNA_POLICY_FILE_V6, created_by_name="jechoi",
                               label="analysis-policy-luna-rl-v6")
    session.commit()
    # The RL approval binds row identity = policy file identity; pin the v6 file explicitly
    # (the import default moved to v7 with RL-03 결정 B51).
    configure(monkeypatch, BIDOPS_PROPOSAL_POLICY_VERSION_ID=str(proposal.id),
              BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(rl.id),
              BIDOPS_RL_ANALYSIS_POLICY_PATH=str(RL_LUNA_POLICY_FILE_V6))
    return proposal, rl


def _cli(monkeypatch, engine, *argv: str, capsys) -> tuple[int, dict, str]:
    monkeypatch.setattr(approve_cli, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(approve_cli, "init_db", lambda: None)
    code = approve_cli.main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err.strip()


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- approve ---------------------------------------------------------------------------------


def test_approve_cli_accepts_the_proposal_identity_with_purpose_scope_and_cap_3(engine, monkeypatch, capsys) -> None:
    with Session(engine) as session:
        proposal, rl = _policies(session, monkeypatch)
    for cap in ("0", "21"):
        code, payload, err = _cli(monkeypatch, engine, "--policy", "proposal-policy-luna-v1", "--actor", "jechoi",
                                  "--daily-cap", cap, capsys=capsys)
        assert code == 2 and payload["errors"] == ["invalid_request"] and err == "invalid_request"
    code, approved, _ = _cli(monkeypatch, engine, "--policy", "proposal-policy-luna-v1", "--actor", "jechoi",
                             capsys=capsys)
    assert code == 0 and approved["created"] is True and approved["errors"] == []
    assert approved["daily_cap"] == 3 and approved["policy_sha256"] == proposal.policy_sha256
    assert (approved["model_name"], approved["reasoning_effort"], approved["cli_version"]) == (
        "gpt-6-luna", "high", "0.162.1")
    with Session(engine) as session:
        row = session.get(TransferPolicyApproval, UUID(approved["approval_id"]))
        assert row.policy_identity == "proposal-policy-luna-v1" and row.policy_version_id == proposal.id
        assert row.scope == {"purposes": ["proposal"]} and row.daily_cap == 3
        # RL-03 never sees the proposal approval; the proposal gate never sees an RL one.
        assert tpol.active_approval(session) is None
        assert tpol.active_proposal_approval(session).id == row.id
    code, replay, _ = _cli(monkeypatch, engine, "--policy", "proposal-policy-luna-v1", "--actor", "jechoi",
                           "--request-id", approved["request_id"], capsys=capsys)
    assert code == 0 and replay["created"] is False and replay["approval_id"] == approved["approval_id"]
    code, duplicate, err = _cli(monkeypatch, engine, "--policy", "proposal-policy-luna-v1", "--actor", "jechoi",
                                "--daily-cap", "20", capsys=capsys)
    assert code == 2 and err == "active_approval_exists"
    # RL-03 behaviour is unchanged: RL identity, RL scope, RL default cap 10.
    code, rl_approved, _ = _cli(monkeypatch, engine, "--policy", "analysis-policy-luna-rl-v6", "--actor", "jechoi",
                                capsys=capsys)
    assert code == 0 and rl_approved["daily_cap"] == 10
    with Session(engine) as session:
        rl_row = session.get(TransferPolicyApproval, UUID(rl_approved["approval_id"]))
        assert rl_row.scope == {"stages": ["pre_spec"], "purposes": ["deep_review"]}
        assert tpol.active_approval(session).id == rl_row.id
        assert tpol.active_proposal_approval(session).id == UUID(approved["approval_id"])
        assert _count(session, TransferPolicyApproval) == 2


@pytest.mark.parametrize("case", ["no_row", "rl_row", "file_mismatch", "rl_identity_on_proposal_row"])
def test_approve_cli_binds_the_proposal_row_and_file(engine, monkeypatch, capsys, case) -> None:
    with Session(engine) as session:
        proposal, rl = _policies(session, monkeypatch)
    policy, expected = "proposal-policy-luna-v1", "policy_identity_mismatch"
    if case == "no_row":
        configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(rl.id))
        expected = "analysis_policy_unavailable"
    elif case == "rl_row":
        configure(monkeypatch, BIDOPS_PROPOSAL_POLICY_VERSION_ID=str(rl.id))
    elif case == "file_mismatch":
        configure(monkeypatch, BIDOPS_PROPOSAL_POLICY_VERSION_ID=str(proposal.id),
                  BIDOPS_PROPOSAL_POLICY_PATH=str(RL_LUNA_POLICY_FILE_V6))
    else:
        configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(proposal.id))
        policy = "analysis-policy-luna-rl-v6"
    code, payload, err = _cli(monkeypatch, engine, "--policy", policy, "--actor", "jechoi", capsys=capsys)
    assert code == 2 and payload["errors"] == [expected] and err == expected
    with Session(engine) as session:
        assert _count(session, TransferPolicyApproval) == 0


# --- gate and cap ------------------------------------------------------------------------------


def _approval(session: Session, policy, *, daily_cap: int, scope=None, identity="proposal-policy-luna-v1"):
    row = TransferPolicyApproval(
        id=uuid4(), policy_identity=identity, policy_version_id=policy.id, policy_sha256=policy.policy_sha256,
        model_name="gpt-6-luna", reasoning_effort="high", cli_version="0.162.1",
        scope=scope or {"purposes": ["proposal"]}, daily_cap=daily_cap, approved_by="jechoi", request_id=uuid4(),
    )
    session.add(row)
    session.commit()
    return row


def _draft(session: Session, policy, approval, *, sections: int = 6, status: str = "queued",
           created_at: datetime = NOW) -> list[ProposalSection]:
    draft = ProposalDraft(
        opportunity_id=1, notice_id=1, verdict_attempt_id=uuid4(), policy_version_id=policy.id,
        policy_sha256=policy.policy_sha256, approval_id=approval.id, status="queued", stage="toc",
        created_by="jechoi", created_at=created_at,
    )
    session.add(draft)
    session.flush()
    rows = [
        ProposalSection(draft_id=draft.id, section_key=PROPOSAL_SECTION_KEYS[index % 6], revision=1 + index // 6,
                        status=status, created_at=created_at)
        for index in range(sections)
    ]
    session.add_all(rows)
    session.commit()
    return rows


def _gate_code(session: Session, policy, **kwargs) -> str | None:
    try:
        tpol.require_proposal_transfer_approval(session, policy, now=NOW, **kwargs)
    except tpol.TransferPolicyError as error:
        return error.code
    return None


def _sent(session: Session, approval, section: ProposalSection) -> None:
    assert tpol.record_proposal_transfer_sent(
        session, approval=approval, draft_id=section.draft_id, section_id=section.id,
        section_key=section.section_key, notice_id=1, input_sha256="c" * 64,
    )
    session.commit()


def test_gate_order_approval_sha_purpose_then_cap(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        proposal, rl = _policies(session, monkeypatch)
        assert _gate_code(session, proposal, requested_sections=6) == "policy_not_approved"
        # An RL approval is not a proposal approval.
        _approval(session, rl, daily_cap=10, scope={"stages": ["pre_spec"], "purposes": ["deep_review"]},
                  identity="analysis-policy-luna-rl-v6")
        assert _gate_code(session, proposal, requested_sections=6) == "policy_not_approved"
        # A proposal approval whose scope lacks "proposal" does not open the gate.
        wrong = _approval(session, proposal, daily_cap=3, scope={"purposes": ["deep_review"]})
        assert _gate_code(session, proposal, requested_sections=6) == "policy_not_approved"
        wrong.revoked_by, wrong.revoked_at, wrong.revoke_reason = "jechoi", NOW, "범위 오류"
        session.commit()
        approval = _approval(session, proposal, daily_cap=1)
        # Another policy sha (the RL row) is not approved for proposals.
        assert _gate_code(session, rl, requested_sections=6) == "policy_not_approved"
        for bad in (0, 7, True, "6"):
            assert _gate_code(session, proposal, requested_sections=bad) == "invalid_request"
        assert _gate_code(session, proposal, requested_sections=6) is None
        assert tpol.require_proposal_transfer_approval(session, proposal, requested_sections=6, now=NOW).id == approval.id
        # RL-03 sees none of this.
        assert tpol.active_approval(session).policy_identity == "analysis-policy-luna-rl-v6"
        assert tpol.today_used(session, now=NOW) == 0


def test_daily_cap_counts_drafts_and_regenerations_as_one_sixth(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        proposal, _rl = _policies(session, monkeypatch)
        approval = _approval(session, proposal, daily_cap=1)
        first = _draft(session, proposal, approval)
        assert tpol.proposal_cap_usage(session, now=NOW) == (0, 6)
        # cap 1 = 6 section generations: the six reserved sections leave no room.
        assert _gate_code(session, proposal, requested_sections=6) == "daily_cap_reached"
        assert _gate_code(session, proposal, requested_sections=1) == "daily_cap_reached"
        # The worker re-check excludes its own section and does not reserve in-flight ones.
        assert _gate_code(session, proposal, requested_sections=1, reserve_in_flight=False,
                          exclude_section_id=first[0].id) is None
        # Transmitted sections count; completed without a transfer audit (mock) and failed do not.
        for section in first:
            _sent(session, approval, section)
            section.status = "completed"
        session.commit()
        assert tpol.proposal_cap_usage(session, now=NOW) == (6, 0)
        assert _gate_code(session, proposal, requested_sections=1, reserve_in_flight=False) == "daily_cap_reached"
        # Yesterday's sections are not today's usage.
        assert tpol.proposal_cap_usage(session, now=NOW + timedelta(days=1)) == (0, 0)

    with Session(sqlite_engine) as session:
        approval = session.scalar(select(TransferPolicyApproval))
        approval.revoked_by, approval.revoked_at, approval.revoke_reason = "jechoi", NOW, "상한 변경"
        session.commit()
    with Session(sqlite_engine) as session:
        proposal = session.scalar(select(AnalysisPolicyVersion).where(
            AnalysisPolicyVersion.label == "proposal-policy-luna-v1"))
        approval = _approval(session, proposal, daily_cap=2)
        # 6 transmitted today; mock-completed and failed sections never count.
        _draft(session, proposal, approval, sections=6, status="completed")
        _draft(session, proposal, approval, sections=6, status="failed")
        assert tpol.proposal_cap_usage(session, now=NOW) == (6, 0)
        # cap 2 = 12: a new draft (6) still fits exactly, then only five regenerations.
        assert _gate_code(session, proposal, requested_sections=6) is None
        _draft(session, proposal, approval, sections=5)
        assert tpol.proposal_cap_usage(session, now=NOW) == (6, 5)
        assert _gate_code(session, proposal, requested_sections=1) is None
        assert _gate_code(session, proposal, requested_sections=6) == "daily_cap_reached"
        _draft(session, proposal, approval, sections=1)
        assert _gate_code(session, proposal, requested_sections=1) == "daily_cap_reached"


def test_transfer_audit_is_one_per_section_with_purpose_proposal_and_no_text(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        proposal, rl = _policies(session, monkeypatch)
        approval = _approval(session, proposal, daily_cap=3)
        section = _draft(session, proposal, approval, sections=1)[0]
        assert tpol.record_proposal_transfer_sent(
            session, approval=approval, draft_id=section.draft_id, section_id=section.id,
            section_key="overview", notice_id=1, input_sha256="c" * 64,
        ) is True
        assert tpol.record_proposal_transfer_sent(
            session, approval=approval, draft_id=section.draft_id, section_id=section.id,
            section_key="overview", notice_id=1, input_sha256="c" * 64,
        ) is False
        rows = session.scalars(select(AuditEvent).where(AuditEvent.action == "analysis.transfer.sent")).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.actor_kind, row.claimed_name, row.aggregate_type, row.aggregate_id) == (
            "system", "system:transfer-policy", "proposal_section", str(section.id))
        assert row.safe_metadata == {
            "purpose": "proposal", "approval_id": str(approval.id), "policy_sha256": proposal.policy_sha256,
            "input_sha256": "c" * 64, "draft_id": str(section.draft_id), "section_id": str(section.id),
            "section_key": "overview", "notice_id": 1,
        }
        assert set(row.safe_metadata) == tpol.PROPOSAL_TRANSFER_SENT_KEYS
        # An RL approval row cannot stamp a proposal transfer; malformed values are refused.
        rl_approval = _approval(session, rl, daily_cap=1, identity="analysis-policy-luna-rl-v6",
                                scope={"stages": ["pre_spec"], "purposes": ["deep_review"]})
        other = _draft(session, proposal, approval, sections=1)[0]
        for kwargs in ({"approval": rl_approval}, {"input_sha256": "short"}, {"notice_id": -1},
                       {"section_key": ""}):
            arguments = {"approval": approval, "draft_id": other.draft_id, "section_id": other.id,
                         "section_key": "overview", "notice_id": 1, "input_sha256": "c" * 64, **kwargs}
            with pytest.raises(tpol.TransferPolicyError):
                tpol.record_proposal_transfer_sent(session, **arguments)
        # RL-03's cap never counts a proposal audit.
        assert tpol.today_used(session) == 0


# --- integration on the completed card-v1 attempt (real Rootlab, outside Git) -------------------

from tests.app import test_transfer_policy as rl_tp  # noqa: E402
from tests.app.test_verdict_trigger_postgres import flow_engine, no_model_transport  # noqa: E402,F401
from tests.deep_review.test_company_knowledge import object_store  # noqa: E402,F401


@rl_tp.needs_rootlab
def test_completed_verdict_attempt_feeds_every_section_and_a_real_draft_is_capped(flow_engine, monkeypatch) -> None:  # noqa: F811
    from tests.app.test_verdict_api import run_completed, started_world

    with Session(flow_engine) as session:
        world, seeded, _item = started_world(session, monkeypatch)
        started = run_completed(session, world, seeded)
        with pytest.raises(ProposalInputError) as error:
            load_verdict_sources(session, uuid4())
        assert error.value.code == "verdict_required"
        sources = load_verdict_sources(session, started.attempt_id)
        preview = session.get(DeepReviewPreview, started.preview_id)
        assert sources.notice_id == seeded.notice_id and sources.verdict_input_sha256 == preview.input_sha256
        assert set(sources.verdict) == {"verdict", "reason", "checklist"}
        assert [row["key"] for row in sources.verdict["checklist"]] == [
            "qualification_track_record", "staffing_onsite", "amount_period", "technology",
            "operations_sla_security"]
        notice = session.get(Notice, seeded.notice_id)
        proposal = import_policy_version(session, PROPOSAL_LUNA_POLICY_FILE, created_by_name="jechoi",
                                         label="proposal-policy-luna-v1")
        session.commit()
        draft_id = uuid4()
        digests = set()
        for key in PROPOSAL_SECTION_KEYS:
            value = build_proposal_input(
                sources, section_key=key, execution_nonce=uuid4(), draft_id=draft_id,
                opportunity_id=seeded.opportunity_id, notice_id=seeded.notice_id,
                policy_sha256=proposal.policy_sha256, notice_meta=notice_meta(notice),
            )
            payload = proposal_transfer_payload(value, sources, operational_values=(world.approval["approval_id"],))
            assert list(payload) == list(PROPOSAL_TRANSFER_KEYS)
            digests.add(proposal_input_sha256(value))
            if key == "requirements":
                assert [row["unit_id"] for row in payload["units"]] == [
                    row["unit_id"] for row in preview.input_snapshot["card_analysis"]["units"] if row["kind"] == "card"]
                assert "BBB0" not in json.dumps(payload, ensure_ascii=False)
        assert len(digests) == 6

        # A real draft with six queued sections (all foreign keys real) is counted by the gate.
        monkeypatch.setenv("BIDOPS_PROPOSAL_POLICY_VERSION_ID", str(proposal.id))
        get_settings.cache_clear()
        approved = tpol.approve_transfer_policy(session, policy_identity="proposal-policy-luna-v1",
                                                actor="jechoi", daily_cap=1)
        session.commit()
        approval = session.get(TransferPolicyApproval, UUID(approved["approval_id"]))
        assert tpol.require_proposal_transfer_approval(session, proposal, requested_sections=6).id == approval.id
        draft = ProposalDraft(
            id=draft_id, opportunity_id=seeded.opportunity_id, notice_id=seeded.notice_id,
            verdict_attempt_id=started.attempt_id, policy_version_id=proposal.id,
            policy_sha256=proposal.policy_sha256, approval_id=approval.id, status="queued", stage="toc",
            created_by="jechoi",
        )
        session.add(draft)
        session.flush()
        sections = [ProposalSection(draft_id=draft.id, section_key=key, revision=1, status="queued")
                    for key in PROPOSAL_SECTION_KEYS]
        session.add_all(sections)
        session.commit()
        assert tpol.proposal_cap_usage(session) == (0, 6)
        with pytest.raises(tpol.TransferPolicyError) as error:
            tpol.require_proposal_transfer_approval(session, proposal, requested_sections=1)
        assert error.value.code == "daily_cap_reached"
        assert tpol.record_proposal_transfer_sent(
            session, approval=approval, draft_id=draft.id, section_id=sections[0].id,
            section_key=sections[0].section_key, notice_id=seeded.notice_id, input_sha256="d" * 64,
        )
        session.commit()
        assert tpol.proposal_cap_usage(session) == (1, 5)
        # RL-03's own cap and approval are untouched by the proposal rows.
        assert tpol.active_approval(session).id == UUID(world.approval["approval_id"])
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
