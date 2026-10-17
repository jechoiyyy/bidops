"""RL-03 automatic card verdict trigger, daily-cap queue and manual request (spec "자동 트리거와 일일 상한").

Conditions of an automatic start (all true):

1. a briefing ``kind=recommendation``/stage ``pre_spec`` item exists for the
   notice (lifecycle hook ``on_briefing_recommendation``; the ready-transition
   re-evaluation looks the item up);
2. the notice's latest document bundle is ``ready`` -- otherwise the briefing
   hook asks ``maybe_auto_prepare`` (trigger ``briefing_recommendation``) to
   start the preparation and the ready-transition hook (``on_bundle_ready``,
   called by ``auto_preparation``) evaluates (3)~(7) again;
3. ``qualification_flags_json.sw_business_status='Y'`` (no overview run, D1);
4. ``BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED`` (with ``BIDOPS_RL_ANALYSIS_ENABLED``);
5. an active ``transfer_policy_approval`` of the selected policy sha;
6. today's RL attempts < ``daily_cap`` -- otherwise one ``verdict_request``
   ``queued``/``daily_cap_reached`` row (no WorkJob);
7. no ``verdict_request(status=rejected, reason=gold_holdout)`` for the notice.

The same (notice, document fingerprint, company graph version, policy sha)
combination never gets a second automatic attempt: a completed one is current
(DEMO §5) and a failed one goes to people (no automatic retry, intent "실패
보존"); a manual request is always a new attempt.

Decision B8: the cap check and the attempt creation are serialized with one
PostgreSQL transaction-level advisory lock (no-op on SQLite), so concurrent
starts (worker ready hooks, briefing, drain, manual requests) cannot exceed the
daily cap.  The lock is held until the surrounding transaction ends.

Rows are created by the existing service functions (``start_rl_verdict`` →
preview → review/attempt → approval, ``actor_kind=system``).  Nothing here
calls a model or the network.  Hook failures never reach the triggering work
(briefing build, bundle confirmation): they are logged with safe identifiers
only and retried at the next trigger.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.models import AuditEvent
from ...lifecycle import active_opportunity_predicate, authoritative_link_predicate
from ...lifecycle.models import Briefing, BriefingItem, Company, Notice, Opportunity, OpportunityLink
from ..models import (
    AnalysisPolicyVersion,
    CompanyKnowledgeBinding,
    DeepReview,
    DeepReviewAttempt,
    DocumentBundleItem,
    VerdictRequest,
)
from . import transfer_policy
from .auto_preparation import _work_session
from .company_analysis_input import ready_bundle_document_sets
from .deep_reviews import DeepReviewServiceError
from .effective_grade import sw_business_notice_ids


logger = logging.getLogger(__name__)

#: ``maybe_auto_prepare`` trigger of a briefing recommendation (bundle audit ``trigger``).
BRIEFING_TRIGGER = "briefing_recommendation"
#: ``actor`` of the cap-queue rows the automatic path writes (same marker as the auto rows).
SYSTEM_ACTOR = transfer_policy.SYSTEM_ACTOR
#: Audit of a manual "다시 판정" request (human actor; the attempt rows stay system/policy rows).
MANUAL_REQUEST_ACTION = "verdict.request.manual"
#: Pre-spec source types of the opportunity record stage rule (lifecycle ``PRE_SPEC_SOURCE_TYPES``).
PRE_SPEC_SOURCE_TYPES = ("pre_spec", "prespec", "pre-spec")

_LOCK_NAME = "bidops.rl.verdict-start"

# --- outcome reasons (internal, never a REST code) ----------------------------------
REASON_DISABLED = "auto_start_disabled"
REASON_NOT_PRE_SPEC = "not_pre_spec"
REASON_NOT_RECOMMENDED = "not_recommended"
REASON_HOLDOUT = "gold_holdout"
REASON_NOT_SW = "effective_grade_ineligible"
REASON_BUNDLE_NOT_READY = "bundle_not_ready"
REASON_PREPARATION = "preparation_requested"
REASON_VERDICT_CURRENT = "verdict_current"
REASON_FAILED_MANUAL = "manual_request_required"
REASON_ACTIVE = "active_attempt_exists"
REASON_CAP = "daily_cap_reached"
REASON_NOT_FOUND = "not_found"
REASON_PROCESSING_FAILED = "processing_failed"

#: A queued row whose notice can never start automatically any more is closed
#: (``rejected``, keeping its reason); transient reasons keep it ``queued``.
_PERMANENT_REASONS = frozenset({
    REASON_NOT_PRE_SPEC, REASON_NOT_RECOMMENDED, REASON_HOLDOUT, REASON_NOT_SW,
    REASON_VERDICT_CURRENT, REASON_FAILED_MANUAL,
})
#: Reasons that stop a drain (nothing else can start either).
_STOP_REASONS = frozenset({REASON_CAP, "policy_not_approved", REASON_NOT_FOUND, REASON_DISABLED})


@dataclass(frozen=True)
class VerdictTriggerOutcome:
    """What one trigger evaluation did for one notice."""

    notice_id: int
    #: ``None`` when an attempt was started.
    reason: str | None = None
    attempt_id: UUID | None = None
    queued: bool = False
    #: The ``verdict_request`` row of a cap queue entry.
    request_row_id: UUID | None = None


@dataclass
class DrainResult:
    as_of: date
    started: list[UUID] = field(default_factory=list)
    rejected: int = 0
    remaining: int = 0
    stopped_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(), "started_attempt_ids": [str(value) for value in self.started],
            "started": len(self.started), "rejected": self.rejected, "remaining": self.remaining,
            "stopped_reason": self.stopped_reason,
        }


class VerdictRequestError(ValueError):
    """Stable code of a manual verdict request / holdout failure (no source text)."""

    STATUS = {
        "invalid_request": 400,
        "actor_name_required": 400,
        "actor_name_invalid": 400,
        "not_found": 404,
        "opportunity_not_found": 404,
        "idempotency_conflict": 409,
        "processing_failed": 500,
    }
    MESSAGES = {
        "invalid_request": "요청을 처리할 수 없습니다",
        "actor_name_required": "담당자 이름이 필요합니다",
        "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
        "not_found": "대상을 찾을 수 없습니다",
        "opportunity_not_found": "사업기회를 찾을 수 없습니다",
        "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
        "processing_failed": "판정 요청을 처리할 수 없습니다",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.STATUS else "processing_failed"
        self.status_code = self.STATUS[self.code]
        self.message = self.MESSAGES[self.code]
        super().__init__(self.code)


# --- lock and lookups ----------------------------------------------------------------


def _lock_key() -> int:
    raw = int.from_bytes(hashlib.sha256(_LOCK_NAME.encode("utf-8")).digest()[:8], "big")
    return raw - (1 << 64) if raw >= (1 << 63) else raw


def rl_start_lock(session: Session) -> bool:
    """Serialize RL cap check + attempt creation (decision B8). No-op (False) on SQLite."""

    if session.get_bind().dialect.name != "postgresql":
        return False
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _lock_key()})
    return True


def real_company(session: Session) -> Company | None:
    """The one registered real company (lifecycle allows at most one)."""

    return session.scalar(
        select(Company).where(Company.is_fictional.is_(False)).order_by(Company.created_at, Company.id).limit(1)
    )


def _auto_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "rl_analysis_enabled", False)
                and getattr(settings, "rl_analysis_auto_start_enabled", False))


def latest_recommendation(session: Session, notice_id: int) -> BriefingItem | None:
    """The newest briefing ``recommendation``/``pre_spec`` item of the notice (condition 1)."""

    return session.scalar(
        select(BriefingItem)
        .join(Briefing, Briefing.id == BriefingItem.briefing_id)
        .where(
            BriefingItem.notice_id == int(notice_id),
            BriefingItem.kind == "recommendation",
            BriefingItem.stage == "pre_spec",
        )
        .order_by(Briefing.briefing_date.desc(), BriefingItem.id.desc())
        .limit(1)
    )


def has_holdout(session: Session, notice_id: int) -> bool:
    return session.scalar(select(VerdictRequest.id).where(
        VerdictRequest.notice_id == int(notice_id),
        VerdictRequest.status == "rejected",
        VerdictRequest.reason == "gold_holdout",
    ).limit(1)) is not None


def notice_opportunity_id(session: Session, notice_id: int) -> int | None:
    """The active opportunity owning the notice through an authoritative link (or None)."""

    return session.scalar(
        select(OpportunityLink.opportunity_id)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            OpportunityLink.notice_id == int(notice_id),
            authoritative_link_predicate(),
            active_opportunity_predicate(),
        )
        .order_by(OpportunityLink.created_at.desc(), OpportunityLink.id.desc())
        .limit(1)
    )


def resolve_opportunity(session: Session, opportunity_id: int) -> Opportunity | None:
    """The opportunity, following ``merged_into_opportunity_id`` to the retained one."""

    current = session.get(Opportunity, int(opportunity_id))
    seen: set[int] = set()
    while current is not None and current.merged_into_opportunity_id is not None and current.id not in seen:
        seen.add(current.id)
        current = session.get(Opportunity, current.merged_into_opportunity_id)
    return current


def opportunity_pre_spec_notice_id(session: Session, opportunity_id: int) -> int | None:
    """The authoritatively linked pre-spec of an opportunity (latest link ``created_at``, then id)."""

    return session.scalar(
        select(OpportunityLink.notice_id)
        .join(Notice, Notice.id == OpportunityLink.notice_id)
        .where(
            OpportunityLink.opportunity_id == int(opportunity_id),
            OpportunityLink.stage == "notice",
            authoritative_link_predicate(),
            Notice.source_type.in_(PRE_SPEC_SOURCE_TYPES),
        )
        .order_by(OpportunityLink.created_at.desc(), OpportunityLink.id.desc())
        .limit(1)
    )


def _bundle_fingerprints(session: Session, bundle_ids: Iterable[UUID]) -> dict[UUID, frozenset[str]]:
    ids = set(bundle_ids)
    if not ids:
        return {}
    out: dict[UUID, set[str]] = {bundle_id: set() for bundle_id in ids}
    for bundle_id, sha in session.execute(
        select(DocumentBundleItem.bundle_id, DocumentBundleItem.content_sha256)
        .where(DocumentBundleItem.bundle_id.in_(ids))
    ).all():
        out[bundle_id].add(str(sha))
    return {key: frozenset(value) for key, value in out.items()}


def _combination_attempt_status(
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    bundle_id: UUID,
    settings: Any,
) -> str | None:
    """Status of an existing attempt of the same (notice, fingerprint, graph, policy sha), or None."""

    binding = session.get(CompanyKnowledgeBinding, company_id)
    policy_row = transfer_policy.selected_rl_policy_row(session, settings)
    if binding is None or policy_row is None:
        return None
    same_policy_ids = select(AnalysisPolicyVersion.id).where(
        AnalysisPolicyVersion.policy_sha256 == policy_row.policy_sha256
    )
    reviews = session.execute(
        select(DeepReview.id, DeepReview.bundle_id).where(
            DeepReview.company_id == company_id,
            DeepReview.notice_id == int(notice_id),
            DeepReview.graph_version_id == binding.graph_version_id,
            DeepReview.policy_version_id.in_(same_policy_ids),
        )
    ).all()
    if not reviews:
        return None
    fingerprints = _bundle_fingerprints(session, {bundle_id, *(row.bundle_id for row in reviews)})
    current = fingerprints.get(bundle_id, frozenset())
    matching = [row.id for row in reviews if fingerprints.get(row.bundle_id) == current]
    if not matching:
        return None
    statuses = set(session.scalars(select(DeepReviewAttempt.status).where(
        DeepReviewAttempt.deep_review_id.in_(matching),
        DeepReviewAttempt.status != "superseded",
    )).all())
    for status in ("queued", "running", "completed", "failed"):
        if status in statuses:
            return status
    return None


def _queued_rows(session: Session, notice_id: int) -> list[VerdictRequest]:
    return list(session.scalars(select(VerdictRequest).where(
        VerdictRequest.notice_id == int(notice_id), VerdictRequest.status == "queued",
    ).order_by(VerdictRequest.created_at, VerdictRequest.id)).all())


def _mark_started(session: Session, notice_id: int, attempt_id: UUID, *, holdout: bool = False) -> int:
    """Queued rows (and, for a manual request, gold_holdout markers) of the notice → ``started``."""

    conditions = [VerdictRequest.status == "queued"]
    if holdout:
        conditions = [VerdictRequest.status.in_(("queued", "rejected"))]
    rows = [
        row for row in session.scalars(select(VerdictRequest).where(
            VerdictRequest.notice_id == int(notice_id), *conditions,
        )).all()
        if row.status == "queued" or row.reason == "gold_holdout"
    ]
    for row in rows:
        row.status = "started"
        row.started_attempt_id = attempt_id
    session.flush()
    return len(rows)


def _service(service: Any) -> Any:
    if service is not None:
        return service
    from .deep_reviews import DeepReviewService

    return DeepReviewService()


# --- evaluation ------------------------------------------------------------------------


def _auto_start(
    session: Session,
    notice_id: int,
    *,
    service: Any,
    settings: Any,
    now: datetime | None,
    enqueue_on_cap: bool = True,
) -> VerdictTriggerOutcome:
    """Evaluate (1)~(7) for one notice and start or queue (caller holds the lock and commits)."""

    from .company_deep_review import rl_path, start_rl_verdict

    notice_id = int(notice_id)
    notice = session.get(Notice, notice_id)
    if notice is None or notice.source_type != "pre_spec":
        return VerdictTriggerOutcome(notice_id, REASON_NOT_PRE_SPEC)
    item = latest_recommendation(session, notice_id)
    if item is None:
        return VerdictTriggerOutcome(notice_id, REASON_NOT_RECOMMENDED)
    if has_holdout(session, notice_id):
        return VerdictTriggerOutcome(notice_id, REASON_HOLDOUT)
    if notice_id not in sw_business_notice_ids(session, [notice_id]):
        return VerdictTriggerOutcome(notice_id, REASON_NOT_SW)
    ready = ready_bundle_document_sets(session, [notice_id]).get(notice_id)
    if ready is None:
        return VerdictTriggerOutcome(notice_id, REASON_BUNDLE_NOT_READY)
    bundle_id = ready[0]
    company = real_company(session)
    if company is None or not rl_path(settings, company):
        return VerdictTriggerOutcome(notice_id, REASON_NOT_FOUND)
    existing = _combination_attempt_status(
        session, company_id=company.id, notice_id=notice_id, bundle_id=bundle_id, settings=settings,
    )
    if existing == "completed":
        return VerdictTriggerOutcome(notice_id, REASON_VERDICT_CURRENT)
    if existing == "failed":
        return VerdictTriggerOutcome(notice_id, REASON_FAILED_MANUAL)
    if existing in {"queued", "running"}:
        return VerdictTriggerOutcome(notice_id, REASON_ACTIVE)
    try:
        started = start_rl_verdict(
            _service(service), session, company_id=company.id, notice_id=notice_id, bundle_id=bundle_id,
            settings=settings, now=now, commit=False,
        )
    except DeepReviewServiceError as error:
        if error.code != REASON_CAP or not enqueue_on_cap:
            return VerdictTriggerOutcome(notice_id, error.code)
        queued = _queued_rows(session, notice_id)
        if queued:
            return VerdictTriggerOutcome(notice_id, REASON_CAP, queued=True, request_row_id=queued[0].id)
        row = VerdictRequest(
            id=uuid4(), opportunity_id=item.opportunity_id, notice_id=notice_id, actor=SYSTEM_ACTOR,
            request_id=uuid4(), status="queued", reason=REASON_CAP,
        )
        session.add(row)
        session.flush()
        return VerdictTriggerOutcome(notice_id, REASON_CAP, queued=True, request_row_id=row.id)
    _mark_started(session, notice_id, started.attempt_id)
    return VerdictTriggerOutcome(notice_id, None, attempt_id=started.attempt_id)


def _run_locked(session: Session, work_fn: Callable[[Session], Any]) -> Any:
    """Run ``work_fn`` under the advisory lock in the caller's transaction (savepoint) or its own."""

    with _work_session(session) as work:
        try:
            rl_start_lock(work)
            result = work_fn(work)
            work.commit()
            return result
        except BaseException:
            work.rollback()
            raise


def _log_failure(where: str, notice_id: int | None, error: BaseException) -> None:
    logger.warning(
        "rl verdict trigger failed where=%s notice_id=%s error=%s code=%s sqlstate=%s",
        where, notice_id, type(error).__name__, getattr(error, "code", None),
        getattr(getattr(error, "orig", None), "sqlstate", None),
    )


def on_briefing_recommendation(
    session: Session,
    notice_id: int,
    briefing_item_id: UUID | None = None,
    *,
    service: Any = None,
    bundle_service: Any = None,
    settings: Any = None,
    now: datetime | None = None,
) -> VerdictTriggerOutcome:
    """Condition (1) happened: start now, or start the document preparation (re-evaluated when ready)."""

    settings = settings or get_settings()
    notice_id = int(notice_id)
    if not _auto_enabled(settings):
        return VerdictTriggerOutcome(notice_id, REASON_DISABLED)
    try:
        notice = session.get(Notice, notice_id)
        if notice is None or notice.source_type != "pre_spec":
            return VerdictTriggerOutcome(notice_id, REASON_NOT_PRE_SPEC)
        if ready_bundle_document_sets(session, [notice_id]).get(notice_id) is None:
            if notice_id not in sw_business_notice_ids(session, [notice_id]):
                return VerdictTriggerOutcome(notice_id, REASON_NOT_SW)
            from .auto_preparation import maybe_auto_prepare

            outcomes = maybe_auto_prepare(
                session, [notice_id], trigger=BRIEFING_TRIGGER, service=bundle_service,
                deep_review_service=service, rl_verdict_settings=settings, rl_verdict_now=now,
            )
            prepared = outcomes[0] if outcomes else None
            if prepared is not None and prepared.rl_verdict is not None:
                return prepared.rl_verdict
            return VerdictTriggerOutcome(notice_id, REASON_PREPARATION)
        return _run_locked(session, lambda work: _auto_start(
            work, notice_id, service=service, settings=settings, now=now,
        ))
    except Exception as error:  # noqa: BLE001 - hook failures stay inside the hook
        _log_failure("briefing_recommendation", notice_id, error)
        return VerdictTriggerOutcome(notice_id, REASON_PROCESSING_FAILED)


def on_bundle_ready(
    session: Session,
    notice_id: int,
    *,
    service: Any = None,
    settings: Any = None,
    now: datetime | None = None,
) -> VerdictTriggerOutcome:
    """Ready-transition re-evaluation of (1)~(7) (called by ``auto_preparation``, worker role)."""

    settings = settings or get_settings()
    notice_id = int(notice_id)
    if not _auto_enabled(settings):
        return VerdictTriggerOutcome(notice_id, REASON_DISABLED)
    try:
        return _run_locked(session, lambda work: _auto_start(
            work, notice_id, service=service, settings=settings, now=now,
        ))
    except Exception as error:  # noqa: BLE001 - must not undo the bundle confirmation
        _log_failure("bundle_ready", notice_id, error)
        return VerdictTriggerOutcome(notice_id, REASON_PROCESSING_FAILED)


# --- daily-cap queue ---------------------------------------------------------------------


def drain_verdict_queue(
    session: Session,
    *,
    as_of: date | None = None,
    service: Any = None,
    settings: Any = None,
    now: datetime | None = None,
) -> DrainResult:
    """Start queued ``daily_cap_reached`` requests created before ``as_of`` (KST day), oldest first.

    Runs under the advisory lock in one transaction (the caller's savepoint or
    its own commit).  Stops at the cap or when no start is possible
    (``policy_not_approved``); a request whose notice can never start
    automatically any more is closed ``rejected`` (reason kept; only status/started_attempt_id are updatable); transient
    failures stay ``queued`` for the next drain.  No catch-up loop: one pass.
    """

    settings = settings or get_settings()
    current = (now or datetime.now(transfer_policy.KST)).astimezone(transfer_policy.KST)
    as_of = as_of or current.date()
    result = DrainResult(as_of=as_of)
    if not _auto_enabled(settings):
        result.stopped_reason = REASON_DISABLED
        return result
    cutoff = datetime.combine(as_of, time.min, tzinfo=transfer_policy.KST)

    def work_fn(work: Session) -> DrainResult:
        rows = list(work.scalars(select(VerdictRequest).where(
            VerdictRequest.status == "queued",
            VerdictRequest.reason == REASON_CAP,
            VerdictRequest.created_at < cutoff,
        ).order_by(VerdictRequest.created_at, VerdictRequest.id)).all())
        handled: set[UUID] = set()
        for row in rows:
            if row.id in handled or row.status != "queued":
                continue
            nested = work.begin_nested()
            try:
                outcome = _auto_start(
                    work, row.notice_id, service=service, settings=settings, now=now, enqueue_on_cap=False,
                )
                if outcome.reason is None and outcome.attempt_id is not None:
                    result.started.append(outcome.attempt_id)
                elif outcome.reason in _PERMANENT_REASONS:
                    row.status = "rejected"
                    work.flush()
                    result.rejected += 1
                nested.commit()
            except Exception as error:  # noqa: BLE001 - one row never stops the others
                nested.rollback()
                _log_failure("drain", row.notice_id, error)
                continue
            handled.add(row.id)
            if outcome.reason in _STOP_REASONS:
                result.stopped_reason = outcome.reason
                break
        result.remaining = len(work.scalars(select(VerdictRequest.id).where(
            VerdictRequest.status == "queued", VerdictRequest.reason == REASON_CAP,
        )).all())
        return result

    return _run_locked(session, work_fn)


def hold_notices(
    session: Session,
    notice_ids: Sequence[int],
    *,
    actor: str | None,
) -> dict[str, Any]:
    """Mark pre-specs as RL-05 gold holdout (``rejected``/``gold_holdout``); idempotent per notice (flush)."""

    claimed = transfer_policy._actor(actor)
    ids = list(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        raise VerdictRequestError("invalid_request")
    found = {
        int(notice_id) for notice_id in session.scalars(
            select(Notice.id).where(Notice.id.in_(ids), Notice.source_type == "pre_spec")
        ).all()
    }
    if set(ids) != found:
        raise VerdictRequestError("not_found")
    created: list[int] = []
    existing: list[int] = []
    for notice_id in ids:
        if has_holdout(session, notice_id):
            existing.append(notice_id)
            continue
        session.add(VerdictRequest(
            id=uuid4(), opportunity_id=notice_opportunity_id(session, notice_id), notice_id=notice_id,
            actor=claimed, request_id=uuid4(), status="rejected", reason="gold_holdout",
        ))
        created.append(notice_id)
    session.flush()
    return {"held": created, "already_held": existing}


# --- manual "다시 판정" ----------------------------------------------------------------------


def request_manual_verdict(
    service: Any,
    session: Session,
    *,
    opportunity_id: int,
    actor: str,
    request_id: UUID,
    settings: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """POST /api/opportunities/{id}/verdict-requests → 202 ``{request_id, attempt_id, status:"queued"}``.

    Always a new attempt (same lineage → ``create_company_attempt``, otherwise a
    new review); consumes the cap and answers 409 ``daily_cap_reached`` instead
    of queueing.  Releases the notice's ``gold_holdout`` markers and satisfies
    its queued entries (both → ``started`` with the attempt id, decision B1).
    The same ``request_id`` replays the first receipt; another use of it is
    ``idempotency_conflict``.  Commits on success; the caller rolls back on error.
    """

    from .company_deep_review import _error as service_error
    from .company_deep_review import rl_path, start_rl_verdict

    settings = settings or get_settings()
    opportunity = resolve_opportunity(session, opportunity_id)
    if opportunity is None:
        raise VerdictRequestError("opportunity_not_found")
    replay = session.scalar(select(VerdictRequest).where(VerdictRequest.request_id == request_id))
    if replay is not None:
        return _replayed_receipt(replay, opportunity_id=opportunity.id, actor=actor, request_id=request_id)
    company = real_company(session)
    if company is None or not rl_path(settings, company):
        raise VerdictRequestError("not_found")
    notice_id = opportunity_pre_spec_notice_id(session, opportunity.id)
    if notice_id is None:
        raise VerdictRequestError("not_found")
    try:
        rl_start_lock(session)
        started = start_rl_verdict(
            _service(service), session, company_id=company.id, notice_id=notice_id, settings=settings,
            now=now, commit=False,
        )
        released = _mark_started(session, notice_id, started.attempt_id, holdout=True)
        row = VerdictRequest(
            id=uuid4(), opportunity_id=opportunity.id, notice_id=int(notice_id), actor=actor,
            request_id=request_id, status="started", reason="manual", started_attempt_id=started.attempt_id,
        )
        session.add(row)
        session.add(AuditEvent(
            actor_kind="human", claimed_name=actor, action=MANUAL_REQUEST_ACTION,
            aggregate_type="verdict_request", aggregate_id=str(row.id), request_id=str(request_id),
            safe_metadata={
                "opportunity_id": opportunity.id, "notice_id": int(notice_id),
                "attempt_id": str(started.attempt_id), "released_count": released,
            },
        ))
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(select(VerdictRequest).where(VerdictRequest.request_id == request_id))
        if replay is None:
            raise service_error("processing_failed") from None
        return _replayed_receipt(replay, opportunity_id=opportunity.id, actor=actor, request_id=request_id)
    return {"request_id": str(request_id), "attempt_id": str(started.attempt_id), "status": "queued"}


def _replayed_receipt(row: VerdictRequest, *, opportunity_id: int, actor: str, request_id: UUID) -> dict[str, Any]:
    if (
        row.reason != "manual"
        or row.opportunity_id != int(opportunity_id)
        or row.actor != actor
        or row.started_attempt_id is None
    ):
        raise VerdictRequestError("idempotency_conflict")
    return {"request_id": str(request_id), "attempt_id": str(row.started_attempt_id), "status": "queued"}


# --- lifecycle hook provider ------------------------------------------------------------------


class RLVerdictBriefingHook:
    """lifecycle ``BriefingRecommendationHook`` (RL-03): drain first, then each pre-spec recommendation."""

    def __init__(self, *, service: Any = None, bundle_service: Any = None) -> None:
        self.service = service
        self.bundle_service = bundle_service

    def briefing_generated(self, session: Session, briefing_date: Any) -> None:
        settings = get_settings()
        if not _auto_enabled(settings):
            return
        try:
            drain_verdict_queue(
                session, as_of=briefing_date if isinstance(briefing_date, date) else None,
                service=self.service, settings=settings,
            )
        except Exception as error:  # noqa: BLE001 - the briefing stays created
            _log_failure("briefing_drain", None, error)

    def on_briefing_recommendation(self, session: Session, notice_id: int, briefing_item_id: UUID) -> None:
        on_briefing_recommendation(
            session, notice_id, briefing_item_id, service=self.service, bundle_service=self.bundle_service,
        )


__all__ = [
    "BRIEFING_TRIGGER",
    "MANUAL_REQUEST_ACTION",
    "DrainResult",
    "RLVerdictBriefingHook",
    "VerdictRequestError",
    "VerdictTriggerOutcome",
    "drain_verdict_queue",
    "hold_notices",
    "latest_recommendation",
    "notice_opportunity_id",
    "on_briefing_recommendation",
    "on_bundle_ready",
    "opportunity_pre_spec_notice_id",
    "real_company",
    "request_manual_verdict",
    "resolve_opportunity",
    "rl_start_lock",
]
