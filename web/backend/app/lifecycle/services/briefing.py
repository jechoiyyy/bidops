"""평일 브리핑 생성·조회·반응 저장 (RL-01 spec "기준일과 모집단"·"항목·반응 계약").

- 생성(`build_briefing`)은 하루 1회다. 같은 날 재실행은 기존 행을 그대로 두고
  `created=False`를 돌려준다. 재생성·삭제 경로는 없다(append-only).
- 점수·제외·정렬·추적 변화 병합은 `briefing_rules`의 순수 함수가 한다. 여기서는 모집단
  조회(창·stage·소유 사업기회·이미 항목인 레코드 제외)와 저장만 한다.
- 회사 사실과 발주계획 후보는 lifecycle 확장점으로만 받는다(lifecycle은 deep_review·
  screening을 import하지 않는다).
- 반응(`react_to_item`)은 core `IdempotencyRecord` fence와 `expected_revision`으로 지킨다.
  반응은 `Opportunity.tracking_*`·`CompanyOpportunityTracking`을 읽지도 쓰지도 않는다.
  화면(REST)과 Slack worker가 같은 함수를 `via`만 달리 해서 부른다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.idempotency_fence import (
    IdempotencyFenceError,
    load_receipt,
    new_receipt,
    receipt_id as fence_receipt_id,
    request_sha256,
)
from ...core.models import utc_now
from ..extensions import extension_registry
from ..models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    IngestWarning,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from ..schemas.briefings import BRIEFING_SCHEMA_VERSION, BriefingItemView, BriefingView
from .briefing_policy import BriefingPolicy, BriefingPolicyError, load_briefing_policy
from .briefing_rules import (
    EXCLUSION_KINDS,
    TRACKED_STATUSES,
    BriefingCandidate,
    BriefingRulesError,
    Recommendation,
    TrackedChange,
    TrackedChangeObservation,
    build_recommendations,
    company_rules,
    merge_tracked_changes,
    notice_candidate,
    order_plan_candidate,
    tracked_changes,
)
from .company_context import _ensure_sqlite_outer_transaction
from .opportunity_candidates import PRE_SPEC_SOURCE_TYPES
from .opportunity_integrity import active_opportunity_predicate, authoritative_link_predicate

KST = ZoneInfo("Asia/Seoul")
#: `briefing.created_by`. 생성은 CLI(`build-briefing`)만 한다.
BRIEFING_CREATED_BY = "system:build-briefing"

REACTIONS = ("대기", "채택", "무시", "나중에")
REACTION_VIAS = ("screen", "slack")
REACT_OPERATION = "briefing.react"
REACT_AGGREGATE_TYPE = "briefing_item"
_REACT_RECEIPT_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://bidops.invalid/idempotency/briefing-react/v1"
)

#: 생성 경고 code(CLI `warnings[]`와 `briefing.warnings`).
WARNING_ORDER_PLAN_PROVIDER_ABSENT = "order_plan_provider_absent"
WARNING_ORPHAN_CANDIDATE = "orphan_candidate"
WARNING_RUN_AMBIGUOUS = "run_ambiguous"
#: 수집 회차 판정 경고. `collection_note`는 저장 열이 없으므로 이 code에서 읽는다.
WARNING_COLLECTION_RUN_MISSING = "collection_run_missing"
WARNING_COLLECTION_RUN_WARNINGS = "collection_run_warnings"
COLLECTION_NOTES: dict[str, str] = {
    WARNING_COLLECTION_RUN_MISSING: "기준일 수집 회차 없음",
    WARNING_RUN_AMBIGUOUS: "회차 중복",
    WARNING_COLLECTION_RUN_WARNINGS: "기준일 수집 회차에 적재 경고가 있습니다",
}
#: 생성이 실패한 code(행 없음, CLI exit 1).
COMPANY_NOT_REGISTERED = "company_not_registered"


class BriefingError(ValueError):
    """안전한 code 하나와 API에 그대로 내보낼 수 있는 `details`."""

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


# --- 기준일·창 ----------------------------------------------------------------


def today_kst(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(KST).date()


def is_weekday(value: date) -> bool:
    """월~금. 공휴일은 범위 밖이다(spec)."""

    return value.weekday() < 5


def _aware(now: datetime | None) -> datetime:
    value = now or utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CandidateWindow:
    """후보 창. 직전 브리핑이 있으면 `(since, until]`, 없으면 `[since, until]`."""

    since: datetime
    until: datetime
    since_inclusive: bool

    def lower(self, column: Any) -> Any:
        return column >= self.since if self.since_inclusive else column > self.since

    def contains(self, column: Any) -> Any:
        return and_(self.lower(column), column <= self.until)

    @property
    def exclusive_since(self) -> datetime:
        """`> since`만 받는 확장점에 넘길 하한. 포함 하한은 1µs 앞으로 당긴다."""

        if self.since_inclusive:
            return self.since - timedelta(microseconds=1)
        return self.since


def candidate_window(session: Session, briefing_date: date, now: datetime) -> CandidateWindow:
    """(직전 브리핑 `generated_at`, 지금]. 직전 브리핑이 없으면 D-1 00:00 KST부터."""

    previous = session.scalar(select(func.max(Briefing.generated_at)))
    if previous is not None:
        return CandidateWindow(since=previous.astimezone(UTC), until=now, since_inclusive=False)
    start = datetime.combine(briefing_date - timedelta(days=1), time.min, tzinfo=KST)
    return CandidateWindow(since=start.astimezone(UTC), until=now, since_inclusive=True)


# --- 수집 회차 판정 ------------------------------------------------------------


def collection_run_patterns(briefing_date: date) -> tuple[str, str]:
    """기준일 D-1 notices 트랙 회차의 `Run.id` LIKE 패턴 두 개(retry 디렉터리 포함)."""

    day = (briefing_date - timedelta(days=1)).strftime("%Y%m%d")
    return (f"lifecycle-{day}-notices--%", f"lifecycle-{day}-notices-retry%--%")


def collection_warning(session: Session, briefing_date: date) -> str | None:
    """수집이 완전하면 `None`, 아니면 그 사유 경고 code.

    0행 → `collection_run_missing`, 2행 이상 → 추정하지 않고 `run_ambiguous`, 1행이면 그
    회차의 `IngestWarning`이 0건일 때만 완전하다.
    """

    first, retry = collection_run_patterns(briefing_date)
    run_ids = session.scalars(
        select(Run.id).where(or_(Run.id.like(first), Run.id.like(retry))).limit(2)
    ).all()
    if not run_ids:
        return WARNING_COLLECTION_RUN_MISSING
    if len(run_ids) > 1:
        return WARNING_RUN_AMBIGUOUS
    warnings = session.scalar(
        select(func.count(IngestWarning.id)).where(IngestWarning.run_id == run_ids[0])
    )
    return WARNING_COLLECTION_RUN_WARNINGS if int(warnings or 0) > 0 else None


def collection_note(warnings: Iterable[str]) -> str | None:
    for code in warnings:
        note = COLLECTION_NOTES.get(code)
        if note is not None:
            return note
    return None


# --- 모집단 -------------------------------------------------------------------


def _owner_subquery(stage: str):
    """레코드당 권위 있는 활성 소유 사업기회(opportunity_integrity의 단일 정의)."""

    link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    target = link.notice_id if stage == "notice" else link.order_plan_id
    return (
        select(target.label("record_id"), func.min(link.opportunity_id).label("opportunity_id"))
        .join(opportunity, opportunity.id == link.opportunity_id)
        .where(
            link.stage == stage,
            target.is_not(None),
            authoritative_link_predicate(link),
            active_opportunity_predicate(opportunity),
        )
        .group_by(target)
        .subquery()
    )


def _notice_stage(source_type: str | None) -> str | None:
    if source_type in PRE_SPEC_SOURCE_TYPES:
        return "pre_spec"
    if source_type == "bid_notice":
        return "bid_notice"
    return None


@dataclass
class _Population:
    candidates: list[BriefingCandidate] = field(default_factory=list)
    orphans: int = 0
    warnings: list[str] = field(default_factory=list)


def _notice_population(
    session: Session, window: CandidateWindow, now: datetime, population: _Population
) -> None:
    first_seen = (
        select(
            NoticeObservation.notice_id.label("notice_id"),
            func.min(NoticeObservation.observed_at).label("first_observed_at"),
        )
        .group_by(NoticeObservation.notice_id)
        .subquery()
    )
    owner = _owner_subquery("notice")
    itemized = select(BriefingItem.notice_id).where(BriefingItem.notice_id.is_not(None))
    sw_status = Notice.qualification_flags_json["sw_business_status"].as_string()
    rows = session.execute(
        select(Notice, first_seen.c.first_observed_at, owner.c.opportunity_id)
        .join(first_seen, first_seen.c.notice_id == Notice.id)
        .outerjoin(owner, owner.c.record_id == Notice.id)
        .where(
            window.contains(first_seen.c.first_observed_at),
            Notice.review_exclusion_status == "included",
            or_(
                and_(Notice.source_type.in_(PRE_SPEC_SOURCE_TYPES), sw_status == "Y"),
                and_(Notice.source_type == "bid_notice", Notice.deadline_at > now),
            ),
            Notice.id.not_in(itemized),
        )
        .order_by(Notice.id)
    ).all()
    for notice, first_observed_at, opportunity_id in rows:
        if opportunity_id is None:
            population.orphans += 1
            continue
        stage = _notice_stage(notice.source_type)
        population.candidates.append(
            notice_candidate(
                notice,
                stage=stage,  # type: ignore[arg-type]
                first_observed_at=first_observed_at,
                opportunity_id=int(opportunity_id),
            )
        )


def _order_plan_population(
    session: Session, window: CandidateWindow, population: _Population
) -> None:
    registry = extension_registry()
    if not registry.briefing_order_plan_candidates_supported:
        population.warnings.append(WARNING_ORDER_PLAN_PROVIDER_ABSENT)
        return
    ids = sorted({int(value) for value in registry.briefing_order_plan_candidates(
        session, window.exclusive_since, window.until
    )})
    if not ids:
        return
    owner = _owner_subquery("order_plan")
    itemized = select(BriefingItem.order_plan_id).where(BriefingItem.order_plan_id.is_not(None))
    rows = session.execute(
        select(OrderPlan, owner.c.opportunity_id)
        .outerjoin(owner, owner.c.record_id == OrderPlan.id)
        .where(
            OrderPlan.id.in_(ids),
            OrderPlan.first_discovered_at.is_not(None),
            OrderPlan.id.not_in(itemized),
        )
        .order_by(OrderPlan.id)
    ).all()
    for plan, opportunity_id in rows:
        if opportunity_id is None:
            population.orphans += 1
            continue
        population.candidates.append(order_plan_candidate(plan, opportunity_id=int(opportunity_id)))


def _tracked_changes(
    session: Session, window: CandidateWindow, policy: BriefingPolicy
) -> tuple[tuple[TrackedChange, ...], dict[int, Notice]]:
    """추적 상태 `계속 추적|보류`인 사업기회의 권위 연결 공고 중 창 안 관측에 추적 필드
    변경이 있는 공고. 권위 연결 = contracts "마감 임박 창"의 정의(`authoritative_link_predicate`)."""

    owner = _owner_subquery("notice")
    rows = session.execute(
        select(
            NoticeObservation.notice_id,
            owner.c.opportunity_id,
            Opportunity.tracking_status,
            NoticeObservation.changed_fields_json,
        )
        .join(owner, owner.c.record_id == NoticeObservation.notice_id)
        .join(Opportunity, Opportunity.id == owner.c.opportunity_id)
        .join(Notice, Notice.id == NoticeObservation.notice_id)
        .where(
            window.contains(NoticeObservation.observed_at),
            Opportunity.tracking_status.in_(sorted(TRACKED_STATUSES)),
            or_(Notice.source_type.in_(PRE_SPEC_SOURCE_TYPES), Notice.source_type == "bid_notice"),
        )
        .order_by(NoticeObservation.notice_id, NoticeObservation.id)
    ).all()
    changes = tracked_changes(
        (
            TrackedChangeObservation(
                notice_id=int(notice_id),
                opportunity_id=int(opportunity_id),
                tracking_status=status,
                changed_fields=fields if isinstance(fields, (list, dict)) else [],
            )
            for notice_id, opportunity_id, status, fields in rows
        ),
        policy,
    )
    if not changes:
        return (), {}
    notices = {
        notice.id: notice
        for notice in session.scalars(
            select(Notice).where(Notice.id.in_([change.notice_id for change in changes]))
        )
    }
    return changes, notices


# --- 생성 ---------------------------------------------------------------------


@dataclass(frozen=True)
class BriefingBuildResult:
    briefing_date: date
    status: str | None
    created: bool
    item_count: int
    tracked_change_count: int
    excluded: dict[str, int]
    warnings: tuple[str, ...]
    briefing_id: UUID | None = None


def _weekend_result(briefing_date: date) -> BriefingBuildResult:
    return BriefingBuildResult(
        briefing_date=briefing_date,
        status=None,
        created=False,
        item_count=0,
        tracked_change_count=0,
        excluded={},
        warnings=(),
    )


def _existing_result(session: Session, briefing: Briefing) -> BriefingBuildResult:
    tracked = session.scalar(
        select(func.count(BriefingItem.id)).where(
            BriefingItem.briefing_id == briefing.id, BriefingItem.kind == "tracked_change"
        )
    )
    excluded = briefing.excluded_counts if isinstance(briefing.excluded_counts, dict) else {}
    warnings = briefing.warnings if isinstance(briefing.warnings, list) else []
    return BriefingBuildResult(
        briefing_date=briefing.briefing_date,
        status=briefing.status,
        created=False,
        item_count=int(briefing.item_count),
        tracked_change_count=int(tracked or 0),
        excluded={str(key): int(value) for key, value in excluded.items()},
        warnings=tuple(str(code) for code in warnings),
        briefing_id=briefing.id,
    )


def _existing(session: Session, briefing_date: date) -> Briefing | None:
    return session.scalar(select(Briefing).where(Briefing.briefing_date == briefing_date))


def _notice_amount(notice: Notice) -> int | None:
    value = notice.estimated_price if notice.estimated_price is not None else notice.budget
    return None if value is None else int(value)


def _recommendation_row(briefing_id: UUID, item: Recommendation) -> BriefingItem:
    candidate = item.candidate
    deadline_kind = candidate.deadline_kind
    if candidate.deadline_at is None and candidate.planned_month is None:
        deadline_kind = None
    return BriefingItem(
        briefing_id=briefing_id,
        kind="recommendation",
        rank=item.rank,
        stage=candidate.stage,
        notice_id=candidate.notice_id,
        order_plan_id=candidate.order_plan_id,
        opportunity_id=int(candidate.opportunity_id),
        score=Decimal(item.score),
        reasons=[dict(reason) for reason in item.reasons],
        blocking=[dict(block) for block in item.blocking],
        change_fields=list(item.change_fields),
        deadline_at=candidate.deadline_at,
        deadline_kind=deadline_kind,
        planned_month=candidate.planned_month,
        amount_krw=candidate.amount_krw,
        reaction="대기",
        revision=0,
    )


_DEADLINE_KIND = {"pre_spec": "opinion_close", "bid_notice": "bid_close"}


def _tracked_row(briefing_id: UUID, change: TrackedChange, notice: Notice) -> BriefingItem:
    stage = _notice_stage(notice.source_type) or "bid_notice"
    return BriefingItem(
        briefing_id=briefing_id,
        kind="tracked_change",
        rank=None,
        stage=stage,
        notice_id=change.notice_id,
        order_plan_id=None,
        opportunity_id=change.opportunity_id,
        score=None,
        reasons=[],
        blocking=[],
        change_fields=list(change.change_fields),
        deadline_at=notice.deadline_at,
        deadline_kind=_DEADLINE_KIND[stage] if notice.deadline_at is not None else None,
        planned_month=None,
        amount_krw=_notice_amount(notice),
        reaction=None,
        revision=0,
    )


def build_briefing(
    session: Session,
    briefing_date: date,
    *,
    now: datetime | None = None,
    policy: BriefingPolicy | None = None,
    persist: bool = True,
) -> BriefingBuildResult:
    """기준일 D의 브리핑을 하루 1회 만든다. 호출자가 commit/rollback한다.

    - D가 토·일이면 행을 만들지 않고 `status=None`.
    - 같은 D의 행이 있으면 그대로 두고 `created=False`(재생성 없음).
    - 실회사 확정 사실이 없으면 `BriefingError("company_not_registered")`(행 없음).
    - `persist=False`(dry-run)는 같은 계산을 하되 행을 넣지 않는다.
    """

    current = _aware(now)
    if not is_weekday(briefing_date):
        return _weekend_result(briefing_date)
    existing = _existing(session, briefing_date)
    if existing is not None:
        return _existing_result(session, existing)

    try:
        active_policy = policy if policy is not None else load_briefing_policy()
    except BriefingPolicyError as error:
        raise BriefingError(error.code) from None
    projection = extension_registry().company_facts_projection(session)
    if projection is None:
        raise BriefingError(COMPANY_NOT_REGISTERED)
    try:
        rules = company_rules(projection)
    except BriefingRulesError as error:
        raise BriefingError(error.code) from None

    window = candidate_window(session, briefing_date, current)
    population = _Population()
    _notice_population(session, window, current, population)
    _order_plan_population(session, window, population)
    result = build_recommendations(population.candidates, rules, active_policy, now=current)
    changes, tracked_notices = _tracked_changes(session, window, active_policy)
    recommendations, remaining = merge_tracked_changes(result.items, changes)

    warnings: list[str] = list(population.warnings)
    if population.orphans:
        warnings.append(WARNING_ORPHAN_CANDIDATE)
    collection = collection_warning(session, briefing_date)
    if collection is not None:
        warnings.append(collection)
        status = "collection_incomplete"
    elif recommendations:
        status = "generated"
    else:
        status = "empty"
    warnings = list(dict.fromkeys(warnings))
    excluded = {kind: int(result.excluded_counts.get(kind, 0)) for kind in EXCLUSION_KINDS}

    outcome = BriefingBuildResult(
        briefing_date=briefing_date,
        status=status,
        created=persist,
        item_count=len(recommendations),
        tracked_change_count=len(remaining),
        excluded=excluded,
        warnings=tuple(warnings),
    )
    if not persist:
        return BriefingBuildResult(**{**outcome.__dict__, "created": False})

    briefing = Briefing(
        briefing_date=briefing_date,
        status=status,
        generated_at=current,
        policy_sha256=active_policy.sha256,
        graph_version_id=rules.graph_version_id,
        item_count=len(recommendations),
        excluded_counts=excluded,
        warnings=warnings,
        slack_message_ts=None,
        slack_sent_at=None,
        tracked_change_message_ts=None,
        created_by=BRIEFING_CREATED_BY,
    )
    _ensure_sqlite_outer_transaction(session)
    try:
        with session.begin_nested():
            session.add(briefing)
            session.flush()
    except IntegrityError:
        # 같은 날 동시 실행: 먼저 넣은 쪽이 이긴다. 그 행을 그대로 돌려준다.
        winner = _existing(session, briefing_date)
        if winner is None:
            raise
        return _existing_result(session, winner)
    session.add_all(
        [_recommendation_row(briefing.id, item) for item in recommendations]
        + [_tracked_row(briefing.id, change, tracked_notices[change.notice_id]) for change in remaining]
    )
    session.flush()
    return BriefingBuildResult(**{**outcome.__dict__, "briefing_id": briefing.id})


# --- 조회 projection ------------------------------------------------------------


def _verdict(item: BriefingItem) -> str:
    if item.kind == "tracked_change":
        return "재검토 중"
    return "연차 추적" if item.stage == "order_plan" else "분석 대기"


def item_views(session: Session, items: Sequence[BriefingItem]) -> list[BriefingItemView]:
    """항목 행을 응답으로 바꾼다. 제목·기관은 원 레코드에서 읽는다(조회 2회 이하)."""

    notice_ids = sorted({item.notice_id for item in items if item.notice_id is not None})
    plan_ids = sorted({item.order_plan_id for item in items if item.order_plan_id is not None})
    notices = (
        {
            row.id: (row.title, row.agency)
            for row in session.execute(
                select(Notice.id, Notice.title, Notice.agency).where(Notice.id.in_(notice_ids))
            )
        }
        if notice_ids
        else {}
    )
    plans = (
        {
            row.id: (row.title, row.agency_name)
            for row in session.execute(
                select(OrderPlan.id, OrderPlan.title, OrderPlan.agency_name).where(
                    OrderPlan.id.in_(plan_ids)
                )
            )
        }
        if plan_ids
        else {}
    )
    views = []
    for item in items:
        if item.notice_id is not None:
            title, agency = notices.get(item.notice_id, (None, None))
        else:
            title, agency = plans.get(item.order_plan_id, (None, None))
        views.append(
            BriefingItemView(
                item_id=item.id,
                kind=item.kind,
                rank=item.rank,
                stage=item.stage,
                notice_id=item.notice_id,
                order_plan_id=item.order_plan_id,
                opportunity_id=item.opportunity_id,
                # 원 레코드의 제목·기관이 비어 있으면 빈 문자열로 그린다(계약상 문자열).
                title=title or "",
                agency=agency or "",
                amount_krw=item.amount_krw,
                deadline_at=item.deadline_at,
                deadline_kind=item.deadline_kind,
                planned_month=item.planned_month,
                verdict_display=_verdict(item),
                reasons=list(item.reasons or []),
                blocking=list(item.blocking or []),
                change_fields=list(item.change_fields or []),
                reaction=item.reaction,
                reacted_by=item.reacted_by,
                reacted_at=item.reacted_at,
                reacted_via=item.reacted_via,
                revision=item.revision,
                record_path=f"/opportunities/{item.opportunity_id}",
            )
        )
    return views


def _briefing_view(session: Session, briefing: Briefing) -> BriefingView:
    rows = session.scalars(
        select(BriefingItem)
        .where(BriefingItem.briefing_id == briefing.id)
        .order_by(
            BriefingItem.kind,
            BriefingItem.rank,
            BriefingItem.notice_id,
            BriefingItem.order_plan_id,
            BriefingItem.id,
        )
    ).all()
    views = item_views(session, rows)
    warnings = briefing.warnings if isinstance(briefing.warnings, list) else []
    return BriefingView(
        schema_version=BRIEFING_SCHEMA_VERSION,
        briefing_date=briefing.briefing_date,
        status=briefing.status,
        generated_at=briefing.generated_at,
        item_count=briefing.item_count,
        slack_sent_at=briefing.slack_sent_at,
        items=[view for view in views if view.kind == "recommendation"],
        tracked_changes=[view for view in views if view.kind == "tracked_change"],
        collection_note=(
            collection_note(str(code) for code in warnings)
            if briefing.status == "collection_incomplete"
            else None
        ),
    )


def get_briefing_view(session: Session, briefing_date: date) -> BriefingView:
    briefing = _existing(session, briefing_date)
    if briefing is None:
        raise BriefingError("briefing_not_found")
    return _briefing_view(session, briefing)


def get_latest_briefing_view(session: Session) -> BriefingView:
    briefing = session.scalar(
        select(Briefing).order_by(Briefing.briefing_date.desc()).limit(1)
    )
    if briefing is None:
        raise BriefingError("briefing_not_found")
    return _briefing_view(session, briefing)


def count_briefing_pending(session: Session) -> int | None:
    """가장 최근 브리핑의 `reaction=대기` 추천 수. 브리핑이 없으면 `None`(workload)."""

    latest = session.scalar(
        select(Briefing.id).order_by(Briefing.briefing_date.desc()).limit(1)
    )
    if latest is None:
        return None
    return int(
        session.scalar(
            select(func.count(BriefingItem.id)).where(
                BriefingItem.briefing_id == latest,
                BriefingItem.kind == "recommendation",
                BriefingItem.reaction == "대기",
            )
        )
        or 0
    )


# --- 반응 ---------------------------------------------------------------------


@dataclass(frozen=True)
class BriefingReactionResult:
    """응답 DTO와 영수증에 저장한 JSON snapshot(재생은 snapshot을 그대로 돌려준다)."""

    response: BriefingItemView
    snapshot: dict[str, Any]
    replayed: bool = False


def _react_request_hash(
    *, item_id: UUID, reaction: str, expected_revision: int, actor: str, via: str
) -> str:
    return request_sha256(
        {
            "operation": REACT_OPERATION,
            "item_id": str(item_id),
            "reaction": reaction,
            "expected_revision": expected_revision,
            "actor": actor,
            "via": via,
        }
    )


def _react_receipt(*, item_id: UUID, actor: str, request_id: UUID) -> UUID:
    return fence_receipt_id(
        _REACT_RECEIPT_NAMESPACE,
        operation=REACT_OPERATION,
        aggregate_type=REACT_AGGREGATE_TYPE,
        aggregate_id=str(item_id),
        claimed_name=actor,
        request_id=request_id,
    )


def _replay(snapshot: dict[str, Any], *, item_id: UUID) -> BriefingReactionResult:
    try:
        response = BriefingItemView.model_validate(snapshot)
    except Exception as error:
        raise BriefingError("processing_failed") from error
    if response.item_id != item_id:
        raise BriefingError("processing_failed")
    return BriefingReactionResult(response=response, snapshot=snapshot, replayed=True)


def react_to_item(
    session: Session,
    *,
    item_id: UUID,
    reaction: str,
    expected_revision: int,
    request_id: UUID,
    actor: str,
    via: str,
    reacted_at: datetime | None = None,
) -> BriefingReactionResult:
    """추천 항목의 반응을 기록한다. 호출자가 commit/rollback한다.

    검사 순서: 입력 → 항목 404 → 추적 변화 행 409 `reaction_not_allowed` → 같은 영수증
    재생/409 `idempotency_conflict` → `expected_revision` 불일치 409 `version_conflict`.
    변화마다 `briefing_reaction_event`를 하나 덧붙이고 `revision`을 1 올린다.
    """

    if (
        not isinstance(reaction, str)
        or reaction not in REACTIONS
        or not isinstance(via, str)
        or via not in REACTION_VIAS
        or not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
        or not isinstance(request_id, UUID)
        or not isinstance(item_id, UUID)
    ):
        raise BriefingError("invalid_request")
    try:
        clean_actor = validate_actor(actor if isinstance(actor, str) else None)
    except BundleServiceError as error:
        raise BriefingError(error.code) from None
    event_at = _aware(reacted_at)

    item = session.get(BriefingItem, item_id, with_for_update=True)
    if item is None:
        raise BriefingError("briefing_item_not_found")
    if item.kind != "recommendation":
        raise BriefingError("reaction_not_allowed")

    request_hash = _react_request_hash(
        item_id=item_id,
        reaction=reaction,
        expected_revision=expected_revision,
        actor=clean_actor,
        via=via,
    )
    receipt = _react_receipt(item_id=item_id, actor=clean_actor, request_id=request_id)
    try:
        snapshot = load_receipt(
            session,
            receipt=receipt,
            operation=REACT_OPERATION,
            aggregate_type=REACT_AGGREGATE_TYPE,
            aggregate_id=str(item_id),
            claimed_name=clean_actor,
            request_id=request_id,
            request_hash=request_hash,
        )
    except IdempotencyFenceError as error:
        raise BriefingError(error.code) from None
    if snapshot is not None:
        return _replay(snapshot, item_id=item_id)

    if item.revision != expected_revision:
        raise BriefingError("version_conflict", details={"current_revision": item.revision})

    previous = item.reaction or "대기"
    item.reaction = reaction
    item.reacted_by = clean_actor
    item.reacted_at = event_at
    item.reacted_via = via
    item.revision = item.revision + 1
    session.flush()
    response = item_views(session, [item])[0]
    snapshot = response.model_dump(mode="json")
    try:
        session.add_all(
            [
                BriefingReactionEvent(
                    item_id=item_id,
                    revision=item.revision,
                    previous=previous,
                    new=reaction,
                    actor=clean_actor,
                    via=via,
                    request_id=request_id,
                    created_at=event_at,
                ),
                new_receipt(
                    receipt=receipt,
                    operation=REACT_OPERATION,
                    aggregate_type=REACT_AGGREGATE_TYPE,
                    aggregate_id=str(item_id),
                    claimed_name=clean_actor,
                    request_id=request_id,
                    request_hash=request_hash,
                    snapshot=snapshot,
                ),
            ]
        )
        session.flush()
    except (IntegrityError, IdempotencyFenceError) as error:
        raise BriefingError("processing_failed") from error
    return BriefingReactionResult(response=response, snapshot=snapshot)


__all__ = [
    "BRIEFING_CREATED_BY",
    "COLLECTION_NOTES",
    "COMPANY_NOT_REGISTERED",
    "KST",
    "REACTIONS",
    "REACTION_VIAS",
    "REACT_AGGREGATE_TYPE",
    "REACT_OPERATION",
    "BriefingBuildResult",
    "BriefingError",
    "BriefingReactionResult",
    "CandidateWindow",
    "build_briefing",
    "candidate_window",
    "collection_note",
    "collection_run_patterns",
    "collection_warning",
    "count_briefing_pending",
    "get_briefing_view",
    "get_latest_briefing_view",
    "is_weekday",
    "item_views",
    "react_to_item",
    "today_kst",
]
