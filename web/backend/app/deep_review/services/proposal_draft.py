"""RL-04 proposal draft creation, section regeneration and the draft state machine.

Spec "생성 입력·정책·호출" and "저장"; the web process owns every row it creates
(the worker never INSERTs proposal rows):

* ``create_proposal_draft``: one draft (``queued``/``toc``), its six ``queued``
  revision-1 sections and six ``proposal_section`` WorkJobs in one transaction;
  every earlier draft of the opportunity becomes ``superseded``.
* ``request_section_regeneration``: a new ``queued`` revision of one section and
  its WorkJob; earlier revisions are untouched.

Gate order (RL-03 "정책 단위 사전 승인", then the existing gates): request shape →
opportunity → idempotent replay → selected proposal policy row → transfer
approval (active → sha → ``purposes`` → cap: a draft needs 6 section units, a
regeneration 1) → Luna/reference flags → a completed card-v1 verdict → nothing
in progress.  A failure creates nothing.

Draft state machine (the 0041 trigger enforces it in PostgreSQL; the ORM guard
mirrors it for SQLite):

* status ``queued`` → ``running`` (first section claim) → settled by the worker
  when no latest section revision is queued/running: all six completed (or
  reviewed) → ``completed``; at least one completed → ``partial`` (human
  review); none completed → ``failed`` (nothing to review or export).  A
  regeneration re-settles a settled draft among those three.  A new draft of
  the same opportunity sets every older draft to ``superseded`` (web only).
* stage ``toc`` → ``draft`` when the first section completes (worker).

Provider lineage: the creation audit (``proposal.draft.created``) pins
``provider`` (``codex-exec`` or the reference-mode ``mock-analysis``) and the
``quality_status`` (``unmeasured_reference`` / ``mock_reference``); the worker
refuses a draft whose lineage differs from its current provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import AuditEvent
from ..models import AnalysisPolicyVersion, ProposalDraft, ProposalSection, WorkJob
from . import transfer_policy
from .deep_reviews import DeepReviewServiceError, _idempotency_hash, _policy_payload, _validate_actor
from .input_versions import PROPOSAL_SECTION_KEYS, InputVersionError, validate_pinned_policy
from .luna_identity import PROPOSAL_POLICY_IDENTITIES, PROVIDER, matches_runtime, policy_reasoning_effort
from .mock_analysis_client import MOCK_CARD_PROVIDER
from .proposal_input import ProposalInputError, load_verdict_sources


JOB_TYPE = "proposal_section"
AGGREGATE_TYPE = "proposal_section"
DRAFT_CREATED_ACTION = transfer_policy.PROPOSAL_DRAFT_CREATED_ACTION
REGENERATION_ACTION = "proposal.section.regeneration_requested"
QUALITY_STATUS = "unmeasured_reference"
MOCK_QUALITY_STATUS = "mock_reference"
#: Spec "절과 목차 대응" screen names.
SECTION_TITLES: dict[str, str] = {
    "overview": "제안 개요",
    "track_record": "사업수행 실적",
    "strategy": "수행 전략",
    "requirements": "요구사항 수행방안",
    "operations_sla": "운영·SLA",
    "organization": "수행조직",
}
ACTIVE_STATUSES = frozenset({"queued", "running"})
SETTLED_STATUSES = frozenset({"completed", "partial", "failed"})
COMPLETED_SECTION_STATUSES = frozenset({"completed", "reviewed"})
_LOCK_KEY = 0x52_4C_30_34  # "RL04": serializes the proposal cap check and creation (PostgreSQL only)

ERROR_STATUS: dict[str, int] = {
    "invalid_request": 422,
    "actor_name_required": 400,
    "actor_name_invalid": 400,
    "not_found": 404,
    "opportunity_not_found": 404,
    "idempotency_conflict": 409,
    "verdict_required": 409,
    "policy_not_approved": 409,
    "daily_cap_reached": 409,
    "draft_in_progress": 409,
    "section_in_progress": 409,
    "stage_transition_invalid": 409,
    # RL-04 STEP-006 REST codes (spec "REST", "상태 값과 실패 처리").
    "sentence_not_found": 404,
    "section_not_completed": 409,
    "draft_not_completed": 409,
    "pdf_unavailable": 503,
    "analysis_policy_unavailable": 503,
    "service_unavailable": 503,
    "processing_failed": 500,
}


ERROR_MESSAGES: dict[str, str] = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "opportunity_not_found": "사업기회를 찾을 수 없습니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "verdict_required": "완료된 판정이 있어야 제안서 초안을 만들 수 있습니다",
    "policy_not_approved": "제안서 전송 승인이 없습니다",
    "daily_cap_reached": "오늘의 제안서 초안 상한에 도달했습니다",
    "draft_in_progress": "이미 만들고 있는 제안서 초안이 있습니다",
    "section_in_progress": "이 절은 이미 다시 쓰는 중입니다",
    "stage_transition_invalid": "이 단계로 바꿀 수 없습니다",
    "sentence_not_found": "문장을 찾을 수 없습니다",
    "section_not_completed": "생성이 끝난 절만 검토 완료할 수 있습니다",
    "draft_not_completed": "생성이 끝난 초안만 내보낼 수 있습니다",
    "pdf_unavailable": "PDF를 만들 수 없습니다",
    "analysis_policy_unavailable": "제안서 정책을 사용할 수 없습니다",
    "service_unavailable": "제안서 초안 실행이 비활성입니다",
    "processing_failed": "제안서 초안을 처리할 수 없습니다",
}


class ProposalServiceError(RuntimeError):
    """One stable proposal code and its HTTP status; never carries source text."""

    def __init__(self, code: str) -> None:
        if code not in ERROR_STATUS:
            code = "processing_failed"
        self.code = code
        self.status_code = ERROR_STATUS[code]
        super().__init__(code)


# --- provider lineage and policy ----------------------------------------------------------


def provider_lineage(settings: Any) -> tuple[str, str]:
    """``(provider, quality_status)`` of the configured provider (mock only in reference mode)."""

    if getattr(settings, "analysis_provider", None) == "mock":
        return MOCK_CARD_PROVIDER, MOCK_QUALITY_STATUS
    return PROVIDER, QUALITY_STATUS


def require_execution_flags(settings: Any) -> None:
    """Spec "실행 조건": Luna on and reference mode on (the mock provider needs reference mode too)."""

    if not getattr(settings, "luna_deep_review_enabled", False) or not getattr(settings, "reference_workflow_mode", False):
        raise ProposalServiceError("service_unavailable")


def validate_proposal_policy_row(row: AnalysisPolicyVersion | None) -> AnalysisPolicyVersion:
    """The pinned proposal row: approved bytes, proposal identity/pipeline/purpose, runtime model."""

    if row is None:
        raise ProposalServiceError("analysis_policy_unavailable")
    try:
        validate_pinned_policy(row, allow_unmeasured_reference=True)
    except InputVersionError:
        raise ProposalServiceError("analysis_policy_unavailable") from None
    payload = _policy_payload(row)
    if (
        payload.get("policy_identity") not in PROPOSAL_POLICY_IDENTITIES
        or payload.get("pipeline_version") != "proposal-v1"
        or payload.get("purpose") != "proposal"
        or row.model_endpoint_ref != PROVIDER
        or not matches_runtime(row.model_name, policy_reasoning_effort(row))
    ):
        raise ProposalServiceError("analysis_policy_unavailable")
    return row


def draft_lineage(session: Session, draft_id: UUID) -> Mapping[str, Any] | None:
    """The creation audit metadata of a draft (provider, quality status, ...)."""

    row = session.scalar(select(AuditEvent).where(
        AuditEvent.action == DRAFT_CREATED_ACTION,
        AuditEvent.aggregate_type == "proposal_draft",
        AuditEvent.aggregate_id == str(draft_id),
    ).limit(1))
    return row.safe_metadata if row is not None and isinstance(row.safe_metadata, Mapping) else None


# --- state ----------------------------------------------------------------------------------


def latest_sections(session: Session, draft_id: UUID) -> dict[str, ProposalSection]:
    """The newest revision of each section key of a draft."""

    rows = session.scalars(select(ProposalSection).where(ProposalSection.draft_id == draft_id)).all()
    latest: dict[str, ProposalSection] = {}
    for row in rows:
        current = latest.get(row.section_key)
        if current is None or row.revision > current.revision:
            latest[row.section_key] = row
    return latest


def settled_status(sections: Mapping[str, ProposalSection]) -> str | None:
    """The settled draft status, or None while a latest revision is still queued/running."""

    if set(sections) != set(PROPOSAL_SECTION_KEYS) or any(row.status in ACTIVE_STATUSES for row in sections.values()):
        return None
    completed = sum(1 for row in sections.values() if row.status in COMPLETED_SECTION_STATUSES)
    if completed == len(PROPOSAL_SECTION_KEYS):
        return "completed"
    return "partial" if completed else "failed"


def settle_draft(session: Session, draft: ProposalDraft, *, now: datetime) -> None:
    """Worker-side draft update after a section result (caller holds the claim and commits).

    Advances ``toc -> draft`` on the first completed section and settles the
    status once no latest revision is queued/running.  A superseded draft is
    left alone (only its section rows record the late result).
    """

    if draft.status == "superseded":
        return
    sections = latest_sections(session, draft.id)
    if draft.stage == "toc" and any(row.status in COMPLETED_SECTION_STATUSES for row in sections.values()):
        draft.stage = "draft"
    status = settled_status(sections)
    if status is not None and (draft.status != status or draft.completed_at is None):
        draft.status = status
        draft.completed_at = now


def _in_progress(session: Session, draft: ProposalDraft) -> bool:
    if draft.status in ACTIVE_STATUSES:
        return True
    return any(row.status in ACTIVE_STATUSES for row in latest_sections(session, draft.id).values())


# --- shared gate pieces ---------------------------------------------------------------------


def _lock(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})


def _actor(actor: str | None) -> str:
    try:
        return _validate_actor(actor)
    except DeepReviewServiceError as error:
        raise ProposalServiceError(error.code) from None


def _approval(session: Session, policy: AnalysisPolicyVersion, requested_sections: int) -> Any:
    try:
        return transfer_policy.require_proposal_transfer_approval(
            session, policy, requested_sections=requested_sections,
        )
    except transfer_policy.TransferPolicyError as error:
        raise ProposalServiceError(error.code) from None


def _replay(session: Session, action: str, request_id: UUID) -> AuditEvent | None:
    return session.scalar(select(AuditEvent).where(
        AuditEvent.action == action, AuditEvent.request_id == str(request_id),
    ).limit(1))


def _completed_verdict_attempt(session: Session, opportunity: Any) -> tuple[UUID, int]:
    """The newest card-v1 attempt of the opportunity's linked pre-spec, required to be completed."""

    from .verdict_trigger import opportunity_pre_spec_notice_id, real_company
    from .verdict_view import latest_card_attempt

    company = real_company(session)
    notice_id = opportunity_pre_spec_notice_id(session, opportunity.id)
    if company is None or notice_id is None:
        raise ProposalServiceError("verdict_required")
    attempt = latest_card_attempt(session, company.id, notice_id)
    if attempt is None or attempt.status != "completed":
        raise ProposalServiceError("verdict_required")
    try:
        sources = load_verdict_sources(session, attempt.id)
    except ProposalInputError as error:
        raise ProposalServiceError(error.code) from None
    if sources.notice_id != int(notice_id):
        raise ProposalServiceError("processing_failed")
    return attempt.id, int(notice_id)


def _section_and_job(draft_id: UUID, section_key: str, revision: int, priority: int) -> tuple[ProposalSection, WorkJob]:
    section = ProposalSection(id=uuid4(), draft_id=draft_id, section_key=section_key, revision=revision,
                              status="queued")
    job = WorkJob(id=uuid4(), job_type=JOB_TYPE, aggregate_type=AGGREGATE_TYPE, aggregate_id=section.id,
                  status="queued", priority=priority, max_attempts=1)
    return section, job


# --- create ---------------------------------------------------------------------------------


def create_proposal_draft(
    session: Session,
    *,
    opportunity_id: int,
    actor: str | None,
    request_id: UUID,
    settings: Any = None,
) -> dict[str, Any]:
    """POST /api/opportunities/{id}/proposal-requests → ``{draft_id, status}`` (owns the transaction).

    The same ``request_id`` replays the draft it created (``created=False``);
    with another opportunity or actor it is ``idempotency_conflict``.
    """

    settings = settings or get_settings()
    claimed = _actor(actor)
    if not isinstance(request_id, UUID):
        raise ProposalServiceError("invalid_request")
    try:
        from .verdict_trigger import resolve_opportunity

        opportunity = resolve_opportunity(session, int(opportunity_id))
        if opportunity is None:
            raise ProposalServiceError("opportunity_not_found")
        request_hash = _idempotency_hash("proposal.create", {"opportunity_id": opportunity.id})
        replay = _replay(session, DRAFT_CREATED_ACTION, request_id)
        if replay is not None:
            metadata = replay.safe_metadata if isinstance(replay.safe_metadata, Mapping) else {}
            draft = session.get(ProposalDraft, UUID(str(replay.aggregate_id)))
            if draft is None or metadata.get("request_hash") != request_hash or replay.claimed_name != claimed:
                raise ProposalServiceError("idempotency_conflict")
            result = {"draft_id": str(draft.id), "status": draft.status, "created": False}
            session.rollback()
            return result
        policy = validate_proposal_policy_row(transfer_policy.selected_proposal_policy_row(session, settings))
        # One advisory lock serializes the cap check and the in-progress check with the
        # insert (lifecycle rows are never locked from this module).
        _lock(session)
        approval = _approval(session, policy, transfer_policy.PROPOSAL_SECTIONS_PER_DRAFT)
        require_execution_flags(settings)
        attempt_id, notice_id = _completed_verdict_attempt(session, opportunity)
        drafts = session.scalars(select(ProposalDraft).where(ProposalDraft.opportunity_id == opportunity.id)).all()
        if any(_in_progress(session, row) for row in drafts if row.status != "superseded"):
            raise ProposalServiceError("draft_in_progress")
        for row in drafts:
            if row.status != "superseded":
                row.status = "superseded"
        draft = ProposalDraft(
            id=uuid4(), opportunity_id=opportunity.id, notice_id=notice_id, verdict_attempt_id=attempt_id,
            policy_version_id=policy.id, policy_sha256=policy.policy_sha256, approval_id=approval.id,
            status="queued", stage="toc", created_by=claimed,
        )
        session.add(draft)
        session.flush()
        rows: list[Any] = []
        for index, key in enumerate(PROPOSAL_SECTION_KEYS):
            rows.extend(_section_and_job(draft.id, key, 1, len(PROPOSAL_SECTION_KEYS) - index))
        session.add_all([row for row in rows if isinstance(row, ProposalSection)])
        session.flush()
        session.add_all([row for row in rows if isinstance(row, WorkJob)])
        provider, quality_status = provider_lineage(settings)
        session.add(AuditEvent(
            actor_kind="human", claimed_name=claimed, action=DRAFT_CREATED_ACTION,
            aggregate_type="proposal_draft", aggregate_id=str(draft.id), request_id=str(request_id),
            safe_metadata={
                "draft_id": str(draft.id), "opportunity_id": opportunity.id, "notice_id": notice_id,
                "verdict_attempt_id": str(attempt_id), "approval_id": str(approval.id),
                "policy_sha256": policy.policy_sha256, "provider": provider, "quality_status": quality_status,
                "section_count": len(PROPOSAL_SECTION_KEYS), "request_hash": request_hash,
            },
        ))
        session.commit()
        return {"draft_id": str(draft.id), "status": "queued", "created": True}
    except BaseException:
        session.rollback()
        raise


# --- regenerate -----------------------------------------------------------------------------


def request_section_regeneration(
    session: Session,
    *,
    draft_id: UUID,
    section_key: str,
    actor: str | None,
    request_id: UUID,
    settings: Any = None,
) -> dict[str, Any]:
    """POST /api/proposals/{draft_id}/sections/{key}/regenerations → ``{section_id, revision}``.

    One new ``queued`` revision (cap 1/6); earlier revisions are untouched.
    A superseded draft, or one at stage ``reviewed``/``ready``, is not regenerated
    (``stage_transition_invalid``, decision B50).
    """

    settings = settings or get_settings()
    claimed = _actor(actor)
    if not isinstance(request_id, UUID):
        raise ProposalServiceError("invalid_request")
    try:
        draft = session.get(ProposalDraft, draft_id) if isinstance(draft_id, UUID) else None
        if draft is None or section_key not in PROPOSAL_SECTION_KEYS:
            raise ProposalServiceError("not_found")
        request_hash = _idempotency_hash("proposal.regenerate", {"draft_id": str(draft.id), "section_key": section_key})
        replay = _replay(session, REGENERATION_ACTION, request_id)
        if replay is not None:
            metadata = replay.safe_metadata if isinstance(replay.safe_metadata, Mapping) else {}
            section = session.get(ProposalSection, UUID(str(replay.aggregate_id)))
            if section is None or metadata.get("request_hash") != request_hash or replay.claimed_name != claimed:
                raise ProposalServiceError("idempotency_conflict")
            result = {"section_id": str(section.id), "revision": section.revision, "created": False}
            session.rollback()
            return result
        policy = validate_proposal_policy_row(session.get(AnalysisPolicyVersion, draft.policy_version_id))
        _lock(session)
        session.scalar(select(ProposalDraft).where(ProposalDraft.id == draft.id).with_for_update())
        approval = _approval(session, policy, 1)
        require_execution_flags(settings)
        # A superseded draft, and a draft already reviewed or marked ready, is not rewritten
        # (a new revision would leave an unreviewed section under a reviewed/ready stage that
        # never moves back; review decision B50) -- the user makes a new draft instead.
        if draft.status == "superseded" or draft.stage in {"reviewed", "ready"}:
            raise ProposalServiceError("stage_transition_invalid")
        lineage = draft_lineage(session, draft.id)
        provider, _quality = provider_lineage(settings)
        if lineage is None or lineage.get("provider") != provider:
            raise ProposalServiceError("service_unavailable")
        latest = latest_sections(session, draft.id).get(section_key)
        if latest is None:
            raise ProposalServiceError("not_found")
        if latest.status in ACTIVE_STATUSES:
            raise ProposalServiceError("section_in_progress")
        section, job = _section_and_job(draft.id, section_key, latest.revision + 1,
                                        len(PROPOSAL_SECTION_KEYS) - PROPOSAL_SECTION_KEYS.index(section_key))
        session.add(section)
        session.flush()
        session.add(job)
        session.add(AuditEvent(
            actor_kind="human", claimed_name=claimed, action=REGENERATION_ACTION,
            aggregate_type=AGGREGATE_TYPE, aggregate_id=str(section.id), request_id=str(request_id),
            safe_metadata={
                "draft_id": str(draft.id), "section_id": str(section.id), "section_key": section_key,
                "revision": section.revision, "approval_id": str(approval.id), "request_hash": request_hash,
            },
        ))
        session.commit()
        return {"section_id": str(section.id), "revision": section.revision, "created": True}
    except BaseException:
        session.rollback()
        raise


__all__ = [
    "ACTIVE_STATUSES",
    "AGGREGATE_TYPE",
    "DRAFT_CREATED_ACTION",
    "ERROR_MESSAGES",
    "ERROR_STATUS",
    "JOB_TYPE",
    "MOCK_QUALITY_STATUS",
    "QUALITY_STATUS",
    "REGENERATION_ACTION",
    "SECTION_TITLES",
    "ProposalServiceError",
    "create_proposal_draft",
    "draft_lineage",
    "latest_sections",
    "provider_lineage",
    "request_section_regeneration",
    "require_execution_flags",
    "settle_draft",
    "settled_status",
    "validate_proposal_policy_row",
]
