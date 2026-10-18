"""Policy-level pre-approval of Luna transfer for RL card analysis (RL-03 spec "정책 단위 사전 승인").

One ``transfer_policy_approval`` row approves sending the frozen inputs of the
selected RL ``card-v1`` policy row (``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID``)
to the one runner identity (HP-00 ``gpt-6-luna``/``high``/CLI ``0.162.1``),
within a scope and a daily cap.  The row is append-only: only the ``revoked_*``
triple is filled, once.

Execution check order (before the existing §9 identity/binding/ownership
gates, and again at the worker before the first call): approval active →
policy sha equal → scope contains the stage/purpose → daily cap.  A failure is
``policy_not_approved`` or ``daily_cap_reached`` and no preview, approval,
attempt or call is created.

Every attempt that is actually executed leaves one ``analysis.transfer.sent``
audit (system actor) right after the worker claim and before the first model
call; its metadata carries hashes and counts only -- never tokens, source text
or company values.

Daily cap (결정 B17): ``today_used`` counts only attempts that actually
transmitted -- an RL attempt approved today (KST ``approved_at``) with its
``analysis.transfer.sent`` audit.  A mock attempt (결정 B16, provider lineage
``mock-analysis``) never writes that audit and never counts.  So that the cap
still holds before anything is sent, the creation gate additionally reserves
today's real attempts that are queued/running and have not transmitted yet,
and the worker re-checks the cap right before the transfer audit.

RL-04 proposal drafting (spec "생성 입력·정책·호출" 전송 승인) uses the same
table with its own row: the policy ``proposal-policy-luna-v1`` selected by
``BIDOPS_PROPOSAL_POLICY_VERSION_ID``, ``scope = {"purposes": ["proposal"]}``
(no ``stages`` check) and ``daily_cap`` = drafts per KST day (default 3,
1..20).  A section regeneration costs 1/6 of a draft; integer rule: the day
allows ``daily_cap * 6`` section generations, a new draft needs 6 and a
regeneration 1.  Usage counts today's (``proposal_section.created_at``, KST)
sections that transmitted (their ``analysis.transfer.sent`` audit, aggregate
``proposal_section``) and, at the creation gate, today's queued/running
sections without that audit.  Repairs never count.  The RL-03 functions
above ignore proposal approvals and the proposal functions ignore RL ones.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import AuditEvent
from ..models import (
    AnalysisPolicyVersion,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    ProposalDraft,
    ProposalSection,
    TransferPolicyApproval,
)
from .input_versions import InputVersionError, load_canonical_policy, validate_pinned_policy
from .luna_identity import (
    CLI_VERSION,
    MODEL,
    PROPOSAL_POLICY_IDENTITIES,
    PROVIDER,
    REASONING_EFFORT,
    RL_POLICY_IDENTITIES,
)
from .mock_analysis_client import MOCK_CARD_PROVIDER


KST = ZoneInfo("Asia/Seoul")
#: ``claimed_name`` of every row the automatic RL path creates (spec "전송 승인").
SYSTEM_ACTOR = "system:transfer-policy"
#: The only scope RL-03 approves (spec "정책 단위 사전 승인").
SCOPE: dict[str, list[str]] = {"stages": ["pre_spec"], "purposes": ["deep_review"]}
DAILY_CAP_DEFAULT = 10
DAILY_CAP_MIN = 1
DAILY_CAP_MAX = 50
TRANSFER_SENT_ACTION = "analysis.transfer.sent"
#: Exact ``safe_metadata`` keys of ``analysis.transfer.sent`` (spec, T10).
TRANSFER_SENT_KEYS = frozenset({
    "approval_id", "policy_sha256", "input_sha256", "unit_count", "planned_call_count",
    "notice_id", "attempt_id",
})
_ACTOR_MAX = 128
#: RL-04 proposal approval (spec "설정 키와 기본값": daily_cap 3, 1..20, tunable).
PROPOSAL_SCOPE: dict[str, list[str]] = {"purposes": ["proposal"]}
PROPOSAL_DAILY_CAP_DEFAULT = 3
PROPOSAL_DAILY_CAP_MIN = 1
PROPOSAL_DAILY_CAP_MAX = 20
#: One draft = six section generations; a regeneration is one (= cap 1/6).
PROPOSAL_SECTIONS_PER_DRAFT = 6
PROPOSAL_AUDIT_AGGREGATE = "proposal_section"
#: The draft creation audit; its ``provider`` pins the draft's lineage (RL-04 STEP-005).
PROPOSAL_DRAFT_CREATED_ACTION = "proposal.draft.created"
#: Exact ``safe_metadata`` keys of a proposal ``analysis.transfer.sent`` (spec "상태 값과 실패 처리").
PROPOSAL_TRANSFER_SENT_KEYS = frozenset({
    "purpose", "approval_id", "policy_sha256", "input_sha256", "draft_id", "section_id", "section_key",
    "notice_id",
})


class TransferPolicyError(ValueError):
    """Stable, source-free code of a transfer policy failure."""

    STATUS = {
        "invalid_request": 400,
        "actor_name_required": 400,
        "actor_name_invalid": 400,
        "not_found": 404,
        "policy_identity_mismatch": 409,
        "active_approval_exists": 409,
        "already_revoked": 409,
        "policy_not_approved": 409,
        "daily_cap_reached": 409,
        "analysis_policy_unavailable": 503,
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.STATUS else "invalid_request"
        self.status_code = self.STATUS[self.code]
        super().__init__(self.code)


def _actor(value: str | None) -> str:
    if value is None or not value.strip():
        raise TransferPolicyError("actor_name_required")
    clean = value.strip()
    if (
        len(clean) > _ACTOR_MAX
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean)
        or clean.lower() == "system"
        or clean.lower().startswith("system:")
    ):
        raise TransferPolicyError("actor_name_invalid")
    return clean


def _policy_snapshot(row: AnalysisPolicyVersion) -> Mapping[str, Any]:
    rules = row.validation_rules if isinstance(row.validation_rules, Mapping) else {}
    snapshot = rules.get("policy_snapshot")
    return snapshot if isinstance(snapshot, Mapping) else {}


def policy_identity_of(row: AnalysisPolicyVersion | None) -> str | None:
    if row is None:
        return None
    value = _policy_snapshot(row).get("policy_identity")
    return value if isinstance(value, str) else None


def selected_rl_policy_row(session: Session, settings: Any = None) -> AnalysisPolicyVersion | None:
    """The import row selected by ``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`` (or None)."""

    settings = settings or get_settings()
    policy_id = getattr(settings, "rl_deep_review_policy_version_id", None)
    return session.get(AnalysisPolicyVersion, policy_id) if policy_id else None


@dataclass(frozen=True)
class PolicyIdentity:
    row: AnalysisPolicyVersion
    policy_identity: str
    policy_sha256: str
    model_name: str
    reasoning_effort: str
    cli_version: str


def verify_rl_policy_identity(
    session: Session,
    *,
    policy_identity: str,
    settings: Any = None,
) -> PolicyIdentity:
    """Bind the CLI identity to the selected row, the immutable file and HP-00 constants.

    The identity is one of the RL card identities (``analysis-policy-luna-rl-v1``,
    .. ``-v9``, 결정 B23·B30·B33·B35·B37·B51·B53·B55) and must equal both the selected row's and the policy
    file's (``BIDOPS_RL_ANALYSIS_POLICY_PATH``) identity.

    ``analysis_policy_unavailable``: no row selected/found or the row is not
    the approved bytes.  ``policy_identity_mismatch``: the requested identity,
    the row identity, the row canonical sha vs. the policy file sha, or the
    model/effort/CLI identity differ.
    """

    settings = settings or get_settings()
    row = selected_rl_policy_row(session, settings)
    if row is None:
        raise TransferPolicyError("analysis_policy_unavailable")
    try:
        validate_pinned_policy(row, allow_unmeasured_reference=True)
        file_policy, _canonical, file_sha = load_canonical_policy(settings.rl_analysis_policy_path)
    except InputVersionError:
        raise TransferPolicyError("analysis_policy_unavailable") from None
    snapshot = _policy_snapshot(row)
    generation = snapshot.get("generation") if isinstance(snapshot.get("generation"), Mapping) else {}
    execution = snapshot.get("execution") if isinstance(snapshot.get("execution"), Mapping) else {}
    if (
        policy_identity not in RL_POLICY_IDENTITIES
        or snapshot.get("policy_identity") != policy_identity
        or file_policy.get("policy_identity") != policy_identity
        or snapshot.get("pipeline_version") != "card-v1"
        or row.policy_sha256 != file_sha
        or row.model_name != MODEL
        or snapshot.get("model_name") != MODEL
        or generation.get("reasoning_effort") != REASONING_EFFORT
        or execution.get("cli_version") != CLI_VERSION
        or row.model_endpoint_ref != PROVIDER
    ):
        raise TransferPolicyError("policy_identity_mismatch")
    return PolicyIdentity(
        row=row, policy_identity=policy_identity, policy_sha256=row.policy_sha256,
        model_name=MODEL, reasoning_effort=REASONING_EFFORT, cli_version=CLI_VERSION,
    )


def approval_view(row: TransferPolicyApproval, *, created: bool) -> dict[str, Any]:
    return {
        "approval_id": str(row.id), "policy_identity": row.policy_identity,
        "policy_sha256": row.policy_sha256, "model_name": row.model_name,
        "reasoning_effort": row.reasoning_effort, "cli_version": row.cli_version,
        "daily_cap": int(row.daily_cap), "request_id": str(row.request_id),
        "created": created, "errors": [],
    }


def selected_proposal_policy_row(session: Session, settings: Any = None) -> AnalysisPolicyVersion | None:
    """The import row selected by ``BIDOPS_PROPOSAL_POLICY_VERSION_ID`` (or None)."""

    settings = settings or get_settings()
    policy_id = getattr(settings, "proposal_policy_version_id", None)
    return session.get(AnalysisPolicyVersion, policy_id) if policy_id else None


def verify_proposal_policy_identity(
    session: Session,
    *,
    policy_identity: str,
    settings: Any = None,
) -> PolicyIdentity:
    """RL-04: bind the CLI identity to the selected proposal row, its file and HP-00 constants.

    Same codes as ``verify_rl_policy_identity``; the row is the one selected by
    ``BIDOPS_PROPOSAL_POLICY_VERSION_ID`` and the file is
    ``BIDOPS_PROPOSAL_POLICY_PATH``; pipeline ``proposal-v1``, purpose ``proposal``.
    """

    settings = settings or get_settings()
    row = selected_proposal_policy_row(session, settings)
    if row is None:
        raise TransferPolicyError("analysis_policy_unavailable")
    try:
        validate_pinned_policy(row, allow_unmeasured_reference=True)
        file_policy, _canonical, file_sha = load_canonical_policy(settings.proposal_policy_path)
    except InputVersionError:
        raise TransferPolicyError("analysis_policy_unavailable") from None
    snapshot = _policy_snapshot(row)
    generation = snapshot.get("generation") if isinstance(snapshot.get("generation"), Mapping) else {}
    execution = snapshot.get("execution") if isinstance(snapshot.get("execution"), Mapping) else {}
    if (
        policy_identity not in PROPOSAL_POLICY_IDENTITIES
        or snapshot.get("policy_identity") != policy_identity
        or file_policy.get("policy_identity") != policy_identity
        or snapshot.get("pipeline_version") != "proposal-v1"
        or snapshot.get("purpose") != "proposal"
        or row.policy_sha256 != file_sha
        or row.model_name != MODEL
        or snapshot.get("model_name") != MODEL
        or generation.get("reasoning_effort") != REASONING_EFFORT
        or execution.get("cli_version") != CLI_VERSION
        or row.model_endpoint_ref != PROVIDER
    ):
        raise TransferPolicyError("policy_identity_mismatch")
    return PolicyIdentity(
        row=row, policy_identity=policy_identity, policy_sha256=row.policy_sha256,
        model_name=MODEL, reasoning_effort=REASONING_EFFORT, cli_version=CLI_VERSION,
    )


def approve_transfer_policy(
    session: Session,
    *,
    policy_identity: str,
    actor: str | None,
    daily_cap: int | None = None,
    request_id: UUID | None = None,
    dry_run: bool = False,
    settings: Any = None,
) -> dict[str, Any]:
    """Insert one active approval (flush only; the caller commits or rolls back).

    The same ``request_id`` replays the row it created (``created=false``).
    Another active approval of the same policy sha is ``active_approval_exists``
    (the partial UNIQUE also enforces it under a race).  ``--dry-run`` checks
    everything and writes nothing (``approval_id`` null).
    """

    claimed = _actor(actor)
    proposal = policy_identity in PROPOSAL_POLICY_IDENTITIES
    if proposal:
        # RL-04: proposal row, scope purposes=["proposal"], cap = drafts per day (1..20, default 3).
        low, high, default, scope, identities = (
            PROPOSAL_DAILY_CAP_MIN, PROPOSAL_DAILY_CAP_MAX, PROPOSAL_DAILY_CAP_DEFAULT, PROPOSAL_SCOPE,
            PROPOSAL_POLICY_IDENTITIES,
        )
    else:
        low, high, default, scope, identities = (
            DAILY_CAP_MIN, DAILY_CAP_MAX, DAILY_CAP_DEFAULT, SCOPE, RL_POLICY_IDENTITIES,
        )
    if daily_cap is None:
        daily_cap = default
    if type(daily_cap) is not int or not low <= daily_cap <= high:
        raise TransferPolicyError("invalid_request")
    if proposal:
        identity = verify_proposal_policy_identity(session, policy_identity=policy_identity, settings=settings)
    else:
        identity = verify_rl_policy_identity(session, policy_identity=policy_identity, settings=settings)
    request_id = request_id or uuid4()
    replay = session.scalar(select(TransferPolicyApproval).where(TransferPolicyApproval.request_id == request_id))
    if replay is not None:
        if (
            replay.policy_sha256 != identity.policy_sha256
            or replay.policy_version_id != identity.row.id
            or replay.approved_by != claimed
            or int(replay.daily_cap) != daily_cap
        ):
            raise TransferPolicyError("invalid_request")
        return approval_view(replay, created=False)
    active = active_approval(session, identity.policy_sha256, identities=identities)
    if active is not None:
        raise TransferPolicyError("active_approval_exists")
    if dry_run:
        return {
            "approval_id": None, "policy_identity": identity.policy_identity,
            "policy_sha256": identity.policy_sha256, "model_name": identity.model_name,
            "reasoning_effort": identity.reasoning_effort, "cli_version": identity.cli_version,
            "daily_cap": daily_cap, "request_id": str(request_id), "created": False, "errors": [],
        }
    row = TransferPolicyApproval(
        id=uuid4(), policy_identity=identity.policy_identity, policy_version_id=identity.row.id,
        policy_sha256=identity.policy_sha256, model_name=identity.model_name,
        reasoning_effort=identity.reasoning_effort, cli_version=identity.cli_version,
        scope={key: list(value) for key, value in scope.items()}, daily_cap=daily_cap,
        approved_by=claimed, request_id=request_id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        raise TransferPolicyError("active_approval_exists") from None
    return approval_view(row, created=True)


def revoke_transfer_policy(
    session: Session,
    *,
    approval_id: UUID,
    actor: str | None,
    reason: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fill the ``revoked_*`` triple once (flush only)."""

    claimed = _actor(actor)
    if reason is None or not reason.strip() or len(reason.strip()) > 500:
        raise TransferPolicyError("invalid_request")
    row = session.get(TransferPolicyApproval, approval_id)
    if row is None:
        raise TransferPolicyError("not_found")
    if row.revoked_at is not None:
        raise TransferPolicyError("already_revoked")
    row.revoked_by = claimed
    row.revoked_at = now or datetime.now(KST)
    row.revoke_reason = reason.strip()
    session.flush()
    return {
        "approval_id": str(row.id), "policy_sha256": row.policy_sha256, "revoked_by": row.revoked_by,
        "revoked_at": row.revoked_at.isoformat(), "errors": [],
    }


def active_approval(
    session: Session,
    policy_sha256: str | None = None,
    *,
    identities: frozenset[str] = RL_POLICY_IDENTITIES,
) -> TransferPolicyApproval | None:
    """The active approval (``revoked_at IS NULL``) of the RL identities (default) or
    of ``identities`` (RL-04 passes the proposal set), optionally of one policy sha."""

    query = select(TransferPolicyApproval).where(
        TransferPolicyApproval.revoked_at.is_(None),
        TransferPolicyApproval.policy_identity.in_(sorted(identities)),
    )
    if policy_sha256 is not None:
        query = query.where(TransferPolicyApproval.policy_sha256 == policy_sha256)
    return session.scalar(query.order_by(TransferPolicyApproval.approved_at.desc()).limit(1))


def kst_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(KST)).astimezone(KST)
    start = datetime.combine(current.date(), time.min, tzinfo=KST)
    return start, start + timedelta(days=1)


def _rl_policy_row_ids(session: Session) -> list[UUID]:
    rows = session.scalars(select(AnalysisPolicyVersion).where(
        AnalysisPolicyVersion.model_endpoint_ref == PROVIDER,
    )).all()
    return [row.id for row in rows if policy_identity_of(row) in RL_POLICY_IDENTITIES]


#: The per-attempt approval audit that carries the provider lineage (B16).
_APPROVAL_AUDIT_ACTION = "deep_review.external_transfer_approved"
_IN_FLIGHT_STATUSES = ("queued", "running")


def _today_rl_attempts(session: Session, now: datetime | None) -> list[tuple[str, str]]:
    """``(attempt_id, attempt status)`` of every RL company approval approved today (KST).

    Counted over every company approval whose preview froze an RL-identity
    policy row, so switching the selected row does not reset the cap.
    """

    ids = _rl_policy_row_ids(session)
    if not ids:
        return []
    start, end = kst_day_bounds(now)
    rows = session.execute(
        select(DeepReviewApproval.attempt_id, DeepReviewAttempt.status)
        .join(DeepReviewPreview, DeepReviewPreview.id == DeepReviewApproval.preview_id)
        .join(DeepReviewAttempt, DeepReviewAttempt.id == DeepReviewApproval.attempt_id)
        .where(
            DeepReviewPreview.company_id.is_not(None),
            DeepReviewPreview.policy_version_id.in_(ids),
            DeepReviewApproval.approved_at >= start,
            DeepReviewApproval.approved_at < end,
        )
    ).all()
    return [(str(attempt_id), str(status)) for attempt_id, status in rows]


def _attempt_audit_ids(session: Session, action: str, attempt_ids: list[str]) -> set[str]:
    if not attempt_ids:
        return set()
    return {
        str(value)
        for value in session.scalars(select(AuditEvent.aggregate_id).where(
            AuditEvent.action == action,
            AuditEvent.aggregate_type == "deep_review_attempt",
            AuditEvent.aggregate_id.in_(attempt_ids),
        ))
    }


def _mock_attempt_ids(session: Session, attempt_ids: list[str]) -> set[str]:
    """Attempts whose approval audit pinned the mock provider lineage (B16)."""

    if not attempt_ids:
        return set()
    result: set[str] = set()
    for aggregate_id, metadata in session.execute(select(AuditEvent.aggregate_id, AuditEvent.safe_metadata).where(
        AuditEvent.action == _APPROVAL_AUDIT_ACTION,
        AuditEvent.aggregate_type == "deep_review_attempt",
        AuditEvent.aggregate_id.in_(attempt_ids),
    )):
        if isinstance(metadata, Mapping) and metadata.get("provider") == MOCK_CARD_PROVIDER:
            result.add(str(aggregate_id))
    return result


def _cap_usage(
    session: Session,
    *,
    now: datetime | None,
    exclude_attempt_id: UUID | None,
) -> tuple[int, int]:
    """(transmitted today, real attempts today still in flight without a transfer audit)."""

    excluded = str(exclude_attempt_id) if exclude_attempt_id is not None else None
    rows = [(attempt_id, status) for attempt_id, status in _today_rl_attempts(session, now) if attempt_id != excluded]
    attempt_ids = [attempt_id for attempt_id, _status in rows]
    sent = _attempt_audit_ids(session, TRANSFER_SENT_ACTION, attempt_ids)
    mock = _mock_attempt_ids(session, attempt_ids)
    transmitted = sum(1 for attempt_id in attempt_ids if attempt_id in sent and attempt_id not in mock)
    in_flight = sum(
        1 for attempt_id, status in rows
        if status in _IN_FLIGHT_STATUSES and attempt_id not in sent and attempt_id not in mock
    )
    return transmitted, in_flight


def today_used(
    session: Session,
    *,
    now: datetime | None = None,
    exclude_attempt_id: UUID | None = None,
) -> int:
    """RL attempts approved today (KST) that actually transmitted (결정 B17).

    An attempt counts only with its ``analysis.transfer.sent`` audit and a
    non-mock provider lineage; queued, refused-before-send and mock attempts
    do not.
    """

    transmitted, _in_flight = _cap_usage(session, now=now, exclude_attempt_id=exclude_attempt_id)
    return transmitted


def _scope_contains(scope: Any, *, stage: str, purpose: str) -> bool:
    if not isinstance(scope, Mapping):
        return False
    stages = scope.get("stages")
    purposes = scope.get("purposes")
    return (
        isinstance(stages, list) and stage in stages
        and isinstance(purposes, list) and purpose in purposes
    )


def require_transfer_approval(
    session: Session,
    policy_row: AnalysisPolicyVersion | None,
    *,
    stage: str = "pre_spec",
    purpose: str = "deep_review",
    check_cap: bool = True,
    now: datetime | None = None,
    reserve_in_flight: bool = True,
    exclude_attempt_id: UUID | None = None,
) -> TransferPolicyApproval:
    """Spec order: approval active → sha equal → scope → cap.  Read-only.

    The cap compares ``today_used`` (transmitted only, B17) plus -- when
    ``reserve_in_flight`` (the creation gate) -- today's real attempts that
    are still queued/running without a transfer audit, so a burst of starts
    cannot exceed the cap before the worker sends anything.  The worker calls
    with ``reserve_in_flight=False`` and its own attempt excluded.
    """

    if active_approval(session) is None:
        raise TransferPolicyError("policy_not_approved")
    approval = active_approval(session, policy_row.policy_sha256) if policy_row is not None else None
    if approval is None:
        # An active approval exists, but for another policy sha.
        raise TransferPolicyError("policy_not_approved")
    if not _scope_contains(approval.scope, stage=stage, purpose=purpose):
        raise TransferPolicyError("policy_not_approved")
    if check_cap:
        transmitted, in_flight = _cap_usage(session, now=now, exclude_attempt_id=exclude_attempt_id)
        if transmitted + (in_flight if reserve_in_flight else 0) >= int(approval.daily_cap):
            raise TransferPolicyError("daily_cap_reached")
    return approval


def auto_request_id(approval_id: UUID, input_sha256: str) -> UUID:
    """``uuid5(transfer_policy_approval.id, input_sha256)`` (spec "전송 승인")."""

    return uuid5(approval_id, input_sha256)


def transfer_sent_recorded(session: Session, attempt_id: UUID) -> bool:
    return session.scalar(select(AuditEvent.id).where(
        AuditEvent.action == TRANSFER_SENT_ACTION,
        AuditEvent.aggregate_type == "deep_review_attempt",
        AuditEvent.aggregate_id == str(attempt_id),
    ).limit(1)) is not None


def record_transfer_sent(
    session: Session,
    *,
    approval: TransferPolicyApproval,
    attempt_id: UUID,
    notice_id: int,
    input_sha256: str,
    unit_count: int,
    planned_call_count: int,
) -> bool:
    """Append the one per-attempt ``analysis.transfer.sent`` audit (flush only).

    Returns False (and writes nothing) when this attempt already has one.
    """

    if transfer_sent_recorded(session, attempt_id):
        return False
    for value in (unit_count, planned_call_count, notice_id):
        if type(value) is not int or value < 0:
            raise TransferPolicyError("invalid_request")
    metadata = {
        "approval_id": str(approval.id), "policy_sha256": approval.policy_sha256,
        "input_sha256": input_sha256, "unit_count": unit_count,
        "planned_call_count": planned_call_count, "notice_id": notice_id,
        "attempt_id": str(attempt_id),
    }
    if set(metadata) != TRANSFER_SENT_KEYS:
        raise TransferPolicyError("invalid_request")
    session.add(AuditEvent(
        actor_kind="system", claimed_name=SYSTEM_ACTOR, action=TRANSFER_SENT_ACTION,
        aggregate_type="deep_review_attempt", aggregate_id=str(attempt_id), request_id=None,
        safe_metadata=metadata,
    ))
    session.flush()
    return True


# --- RL-04 proposal gate, cap and transfer audit -------------------------------------


def active_proposal_approval(session: Session, policy_sha256: str | None = None) -> TransferPolicyApproval | None:
    return active_approval(session, policy_sha256, identities=PROPOSAL_POLICY_IDENTITIES)


def _proposal_sent_section_ids(session: Session, section_ids: list[str]) -> set[str]:
    if not section_ids:
        return set()
    return {
        str(value)
        for value in session.scalars(select(AuditEvent.aggregate_id).where(
            AuditEvent.action == TRANSFER_SENT_ACTION,
            AuditEvent.aggregate_type == PROPOSAL_AUDIT_AGGREGATE,
            AuditEvent.aggregate_id.in_(section_ids),
        ))
    }


def _mock_draft_ids(session: Session, draft_ids: list[str]) -> set[str]:
    """Drafts whose creation audit pinned the mock provider lineage (never transmitted)."""

    if not draft_ids:
        return set()
    result: set[str] = set()
    for aggregate_id, metadata in session.execute(select(AuditEvent.aggregate_id, AuditEvent.safe_metadata).where(
        AuditEvent.action == PROPOSAL_DRAFT_CREATED_ACTION,
        AuditEvent.aggregate_type == "proposal_draft",
        AuditEvent.aggregate_id.in_(draft_ids),
    )):
        if isinstance(metadata, Mapping) and metadata.get("provider") == MOCK_CARD_PROVIDER:
            result.add(str(aggregate_id))
    return result


def proposal_cap_usage(
    session: Session,
    *,
    now: datetime | None = None,
    exclude_section_id: UUID | None = None,
) -> tuple[int, int]:
    """(section generations transmitted today, today's queued/running sections not yet transmitted).

    "Today" is the KST day of ``proposal_section.created_at`` over every draft
    (switching the selected policy row does not reset the cap).  One unit is
    one section generation; ``daily_cap`` drafts allow ``daily_cap * 6`` units.
    Sections of a mock-lineage draft (STEP-005 creation audit ``provider``) never
    count: nothing is transmitted for them.
    """

    start, end = kst_day_bounds(now)
    rows = session.execute(
        select(ProposalSection.id, ProposalSection.status, ProposalSection.draft_id)
        .join(ProposalDraft, ProposalDraft.id == ProposalSection.draft_id)
        .where(ProposalSection.created_at >= start, ProposalSection.created_at < end)
    ).all()
    mock = _mock_draft_ids(session, sorted({str(draft_id) for _id, _status, draft_id in rows}))
    excluded = str(exclude_section_id) if exclude_section_id is not None else None
    rows = [(str(section_id), str(status)) for section_id, status, draft_id in rows
            if str(section_id) != excluded and str(draft_id) not in mock]
    sent = _proposal_sent_section_ids(session, [section_id for section_id, _status in rows])
    transmitted = sum(1 for section_id, _status in rows if section_id in sent)
    in_flight = sum(1 for section_id, status in rows if status in _IN_FLIGHT_STATUSES and section_id not in sent)
    return transmitted, in_flight


def require_proposal_transfer_approval(
    session: Session,
    policy_row: AnalysisPolicyVersion | None,
    *,
    requested_sections: int,
    check_cap: bool = True,
    now: datetime | None = None,
    reserve_in_flight: bool = True,
    exclude_section_id: UUID | None = None,
) -> TransferPolicyApproval:
    """RL-04 gate, RL-03 order: approval active → sha equal → ``purposes`` contains
    ``proposal`` → cap.  Read-only.

    ``requested_sections`` is 6 for a new draft and 1 for a section
    regeneration (cap 1/6) or for the worker's own re-check (with its section
    excluded and ``reserve_in_flight=False``).  ``daily_cap_reached`` when
    ``transmitted (+ in flight) + requested_sections > daily_cap * 6``.
    """

    if type(requested_sections) is not int or not 1 <= requested_sections <= PROPOSAL_SECTIONS_PER_DRAFT:
        raise TransferPolicyError("invalid_request")
    if active_proposal_approval(session) is None:
        raise TransferPolicyError("policy_not_approved")
    approval = active_proposal_approval(session, policy_row.policy_sha256) if policy_row is not None else None
    if approval is None:
        raise TransferPolicyError("policy_not_approved")
    purposes = approval.scope.get("purposes") if isinstance(approval.scope, Mapping) else None
    if not isinstance(purposes, list) or "proposal" not in purposes:
        raise TransferPolicyError("policy_not_approved")
    if check_cap:
        transmitted, in_flight = proposal_cap_usage(session, now=now, exclude_section_id=exclude_section_id)
        used = transmitted + (in_flight if reserve_in_flight else 0)
        if used + requested_sections > int(approval.daily_cap) * PROPOSAL_SECTIONS_PER_DRAFT:
            raise TransferPolicyError("daily_cap_reached")
    return approval


def proposal_transfer_sent_recorded(session: Session, section_id: UUID) -> bool:
    return session.scalar(select(AuditEvent.id).where(
        AuditEvent.action == TRANSFER_SENT_ACTION,
        AuditEvent.aggregate_type == PROPOSAL_AUDIT_AGGREGATE,
        AuditEvent.aggregate_id == str(section_id),
    ).limit(1)) is not None


def record_proposal_transfer_sent(
    session: Session,
    *,
    approval: TransferPolicyApproval,
    draft_id: UUID,
    section_id: UUID,
    section_key: str,
    notice_id: int,
    input_sha256: str,
) -> bool:
    """Append the one per-section ``analysis.transfer.sent`` audit, ``purpose=proposal`` (flush only).

    Hashes and ids only -- never tokens, source text or company values.
    Returns False (and writes nothing) when this section already has one.
    """

    if proposal_transfer_sent_recorded(session, section_id):
        return False
    if (
        type(notice_id) is not int or notice_id < 0
        or not isinstance(section_key, str) or not section_key
        or not isinstance(input_sha256, str) or len(input_sha256) != 64
        or approval.policy_identity not in PROPOSAL_POLICY_IDENTITIES
    ):
        raise TransferPolicyError("invalid_request")
    metadata = {
        "purpose": "proposal", "approval_id": str(approval.id), "policy_sha256": approval.policy_sha256,
        "input_sha256": input_sha256, "draft_id": str(draft_id), "section_id": str(section_id),
        "section_key": section_key, "notice_id": notice_id,
    }
    if set(metadata) != PROPOSAL_TRANSFER_SENT_KEYS:
        raise TransferPolicyError("invalid_request")
    session.add(AuditEvent(
        actor_kind="system", claimed_name=SYSTEM_ACTOR, action=TRANSFER_SENT_ACTION,
        aggregate_type=PROPOSAL_AUDIT_AGGREGATE, aggregate_id=str(section_id), request_id=None,
        safe_metadata=metadata,
    ))
    session.flush()
    return True


__all__ = [
    "DAILY_CAP_DEFAULT",
    "DAILY_CAP_MAX",
    "DAILY_CAP_MIN",
    "KST",
    "PROPOSAL_AUDIT_AGGREGATE",
    "PROPOSAL_DAILY_CAP_DEFAULT",
    "PROPOSAL_DAILY_CAP_MAX",
    "PROPOSAL_DAILY_CAP_MIN",
    "PROPOSAL_DRAFT_CREATED_ACTION",
    "PROPOSAL_SCOPE",
    "PROPOSAL_SECTIONS_PER_DRAFT",
    "PROPOSAL_TRANSFER_SENT_KEYS",
    "SCOPE",
    "SYSTEM_ACTOR",
    "TRANSFER_SENT_ACTION",
    "TRANSFER_SENT_KEYS",
    "PolicyIdentity",
    "TransferPolicyError",
    "active_approval",
    "active_proposal_approval",
    "approval_view",
    "approve_transfer_policy",
    "auto_request_id",
    "kst_day_bounds",
    "policy_identity_of",
    "proposal_cap_usage",
    "proposal_transfer_sent_recorded",
    "record_proposal_transfer_sent",
    "record_transfer_sent",
    "require_proposal_transfer_approval",
    "require_transfer_approval",
    "revoke_transfer_policy",
    "selected_proposal_policy_row",
    "selected_rl_policy_row",
    "today_used",
    "transfer_sent_recorded",
    "verify_proposal_policy_identity",
    "verify_rl_policy_identity",
]
