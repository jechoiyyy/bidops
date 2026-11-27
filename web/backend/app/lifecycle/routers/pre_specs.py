"""Cumulative pre-specification discovery list."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, get_args
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, and_, column, exists, func, literal, or_, select, values
from sqlalchemy.orm import Session, aliased

from ...core.constants import PreSpecAutoPreparationStatus
from ...core.db import get_db
from ...core.search import search_key, search_sql_match
from .. import PreSpecDocumentCounts, extension_registry
from ..models import Attachment, Notice, NoticeObservation, Opportunity, OpportunityLink
from ..schemas.pre_specs import (
    PreSpecCompanyFitGroup,
    PreSpecCompanyFitSummary,
    PreSpecReviewExclusionFilter,
    PreSpecReviewExclusionRequest,
    PreSpecReviewExclusionResponse,
    PreSpecDocumentSummary,
    PreSpecOrderPlanCandidatesResponse,
    PreSpecListItem,
    PreSpecListResponse,
    PreSpecDeadlineScope,
    PreSpecDeadlineScopeCounts,
    PreSpecDeadlineStatus,
    PreSpecDisplayGradeFilter,
    PreSpecGradeFilter,
    PreSpecOverviewView,
    PreSpecOverviewStatusCount,
    PreSpecOverviewReviewStatus,
    PreSpecOrigin,
    PreSpecSort,
    PreSpecTrackingDecision,
    PreSpecWorkspace,
)
from ..schemas.opportunities import OpportunityTrackingStatus
from ..services.pre_spec_review_exclusions import change_review_exclusions
from ..services.opportunity_candidates import pre_spec_order_plan_candidates
from ..services.opportunity_connections import tracked_order_plan_connection_predicate
from ..services.pre_spec_scope import (
    TRACKING_ACTIVE_STATUSES,
    deadline_passed_expression,
    deadline_sort_expression,
)
from ..services.opportunity_integrity import (
    active_opportunity_predicate,
    authoritative_link_predicate,
)
from .common import decimal_float


router = APIRouter(prefix="/api/pre-specs", tags=["pre-specs"])


def _attachment_counts_subquery():
    """공고별 현재 첨부 수. lifecycle이 자기 `attachment` 테이블에서 직접 센다.

    취득 상태 건수(완료·대기·진행·차단·실패)는 개요·문서 projection(명세 §6.1)이
    공고 id 집합을 받아 채운다.
    """

    return (
        select(
            Attachment.notice_id.label("notice_id"),
            func.count(Attachment.id).label("attachments"),
        )
        .where(Attachment.retired_at.is_(None))
        .group_by(Attachment.notice_id)
        .subquery("pre_spec_attachment_counts")
    )


def _connected_link_subquery():
    """Select the sole authoritative active owner for each notice."""

    link = aliased(OpportunityLink)
    opportunity = aliased(Opportunity)
    return (
        select(
            link.notice_id.label("notice_id"),
            link.id.label("link_id"),
        )
        .join(opportunity, opportunity.id == link.opportunity_id)
        .where(
            link.stage == "notice",
            link.notice_id.is_not(None),
            authoritative_link_predicate(link),
            active_opportunity_predicate(opportunity),
        )
        .subquery("pre_spec_connected_link")
    )


def _qualification_value(notice: Notice, key: str) -> Any:
    flags = notice.qualification_flags_json
    if not isinstance(flags, Mapping):
        return None
    return flags.get(key)


def _pre_spec_number(notice: Notice) -> Any:
    lifecycle = notice.lifecycle_json
    if not isinstance(lifecycle, Mapping):
        return None
    # The response contract deliberately names this exact source location;
    # an arbitrary notice key must not be promoted to a pre-spec number.
    return lifecycle.get("pre_spec_no")


def _count(value: Any) -> int:
    return int(value or 0)


_SEOUL = ZoneInfo("Asia/Seoul")
_TRACKING_PENDING_STATUSES = ("미선택",)
_TRACKING_ACTIVE_STATUSES = TRACKING_ACTIVE_STATUSES
_OVERVIEW_PENDING_STATUSES = (
    "awaiting_document",
    "awaiting_structure",
    "preparing",
    "awaiting_model",
    "queued",
    "running",
)


def _now_utc() -> datetime:
    """Return one request-wide clock value for deadline filters and sorting."""

    return datetime.now(UTC)


def _today_seoul(now: datetime | None = None) -> date:
    """Return today's calendar date in the contract timezone."""

    return (now or _now_utc()).astimezone(_SEOUL).date()


def _coerce_date(value: date | str | None, *, field_name: str) -> date | None:
    """Accept direct-router date values while retaining FastAPI's 422 contract."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise HTTPException(status_code=422, detail=f"{field_name} must be an ISO date")


def _seoul_day_start(value: date) -> datetime:
    """Convert a Seoul calendar day start to the UTC DB comparison value."""

    return datetime.combine(value, time.min, tzinfo=_SEOUL).astimezone(UTC)


def _seoul_day_end_exclusive(value: date) -> datetime:
    """Return the exclusive UTC boundary after one Seoul calendar day."""

    return _seoul_day_start(value + timedelta(days=1))


def _recent_dates(now: datetime | None = None) -> tuple[date, date]:
    today = _today_seoul(now)
    return today - timedelta(days=6), today


def _observation_membership_predicate(
    notice_id: Any,
    *,
    source_run_id: str | None = None,
    observed_from: date | None = None,
    observed_to: date | None = None,
):
    """Build one EXISTS predicate for source/date observation membership.

    The same observation must satisfy every supplied membership condition. This
    matters when a caller combines a source run with an observation date range:
    current notice columns are still returned, but the notice must have actually
    been observed in that run/window.
    """

    conditions: list[Any] = [NoticeObservation.notice_id == notice_id]
    if source_run_id is not None:
        conditions.append(NoticeObservation.run_id == source_run_id)
    if observed_from is not None:
        conditions.append(NoticeObservation.observed_at >= _seoul_day_start(observed_from))
    if observed_to is not None:
        conditions.append(NoticeObservation.observed_at < _seoul_day_end_exclusive(observed_to))
    return exists(select(1).select_from(NoticeObservation).where(*conditions))


def _overview_view_matches(view: PreSpecOverviewView, status: str | None) -> bool:
    """Map the compact workspace view to the persisted overview statuses."""

    if view == "all":
        return True
    if view == "attention":
        return status == "needs_human_review"
    if view == "pending":
        # `pending` deliberately excludes a missing run. `not_started` is the
        # separate null-only view.
        return status in _OVERVIEW_PENDING_STATUSES
    if view == "completed":
        return status == "completed"
    if view == "failed":
        return status == "failed"
    if view == "cancelled":
        return status == "cancelled"
    return status is None


def _normalise_projection_statuses(value: Mapping[Any, Any]) -> dict[int, str]:
    return {
        int(notice_id): str(status)
        for notice_id, status in value.items()
        if status is not None
    }


def _normalise_projection_fields(value: Mapping[Any, Any]) -> dict[int, Mapping[str, Any]]:
    return {
        int(notice_id): fields
        for notice_id, fields in value.items()
        if isinstance(fields, Mapping)
    }


def _tracking_decision_absent(status: Any) -> bool:
    """사람이 추적 결정을 내리지 않았다 — 추적 상태가 null이거나 `미선택`이다.

    `계속 추적`·`보류`·`종료`는 모두 **사람이 내린 결정**이다. 셋을 구분하지
    않는 것이 이 술어의 요점이다(2026-09-22 시안 M7 ③ 승인).
    """

    return status is None or status in _TRACKING_PENDING_STATUSES


#: `검토할 항목`을 여는 개요 상태 (2026-11-19 사전규격 단계 수정안 §3 B).
#: 사람이 읽을 개요가 있거나(`completed`) 사람이 범위를 확정해야 한다
#: (`needs_human_review`). 실패·취소는 읽을 것이 없으므로 `확인 필요`로 간다.
_ACTIONABLE_OVERVIEW_STATUSES = frozenset({"completed", "needs_human_review"})
#: `확인 필요`를 여는 개요 상태 — 개요가 결과 없이 끝났다.
_NEEDS_CHECK_OVERVIEW_STATUSES = frozenset({"failed", "cancelled"})
#: `확인 필요`를 여는 자동 준비 상태 — 문서 준비가 사람 없이는 끝나지 않는다.
#: `blocked`는 차단 issue가 있는 초안이거나 첨부 취득이 모두 `차단`·`실패`로
#: 끝난 경우, `bundle_draft`는 확정되지 않은 초안(사람이 만든 초안 포함)이다.
_NEEDS_CHECK_PREPARATION_STATUSES = frozenset({"blocked", "bundle_draft"})
#: `확인 필요`를 여는 자동 준비 사유 — 대기·진행 중인 취득 행이 없는데 묶음에
#: 넣을 준비된 문서가 없다(첨부가 없거나 구조가 준비되지 않았다).
_NEEDS_CHECK_PREPARATION_REASONS = frozenset({"no_ready_document"})


def _workspace_actionable(
    notice_id: int,
    *,
    overview_status: Mapping[int, str],
    tracking_decision_absent: Mapping[int, bool],
) -> bool:
    """`검토할 항목` 술어 (2026-11-19 개정, 사전규격 단계 수정안 §3 B).

    추적 결정 없음(추적 상태 null 또는 `미선택`) ∧ 개요 `completed` 또는
    `needs_human_review`. 마감 구간은 이 함수 밖 ``workspace_matches``의
    actionable 분기가 건다(ADR-0064 결정 4).

    옛 술어는 기존 심층 검토의 "클릭 대기"(`deep_review_ready_for_click`)를 같이
    보았기 때문에 **실패로 끝난 개요**도 검토할 항목에 올렸다. 그 건은 이제
    `확인 필요`(`_workspace_needs_check`)에서 센다.
    """

    if not tracking_decision_absent.get(notice_id, True):
        return False
    return overview_status.get(notice_id) in _ACTIONABLE_OVERVIEW_STATUSES


def _workspace_needs_check(
    notice_id: int,
    *,
    overview_status: Mapping[int, str],
    status_fields: Mapping[int, Mapping[str, Any]],
    tracking_decision_absent: Mapping[int, bool],
) -> bool:
    """`확인 필요` 술어 (2026-11-19, 사전규격 단계 수정안 §3 B·§5 #4).

    추적 결정 없음 ∧ `검토할 항목`이 아님 ∧ (개요 `failed`·`cancelled` ∨ 자동 준비
    `blocked`·`bundle_draft` ∨ 자동 준비 사유 `no_ready_document`). 둘째 항 때문에
    `검토할 항목`과 서로소다 — 같은 공고를 두 칸에서 세지 않는다.
    """

    if not tracking_decision_absent.get(notice_id, True):
        return False
    status = overview_status.get(notice_id)
    if status in _ACTIONABLE_OVERVIEW_STATUSES:
        return False
    if status in _NEEDS_CHECK_OVERVIEW_STATUSES:
        return True
    fields = status_fields.get(notice_id, {})
    return (
        fields.get("auto_preparation_status") in _NEEDS_CHECK_PREPARATION_STATUSES
        or fields.get("auto_preparation_reason") in _NEEDS_CHECK_PREPARATION_REASONS
    )


def _next_action(overview: str | None, tracking_decision_absent: bool) -> str | None:
    """다음 행동 안내 (2026-11-19 개정).

    `confirm_overview`(개요 확인 필요)는 사람이 개요 범위를 확정해야 진행되므로 추적
    결정과 무관하게 남는다. `review_overview`(개요 확인)는 개요를 읽고 추적을
    정하라는 안내라서 추적 결정이 없을 때만 나온다. 기존 심층 검토를 여는
    `open_deep_review`는 더 이상 나오지 않는다.
    """

    if overview == "needs_human_review":
        return "confirm_overview"
    if overview == "completed" and tracking_decision_absent:
        return "review_overview"
    return None


def _deadline_condition(status: PreSpecDeadlineStatus, now: datetime):
    if status == "open":
        return Notice.deadline_at.is_not(None), Notice.deadline_at >= now
    if status == "passed":
        return Notice.deadline_at.is_not(None), Notice.deadline_at < now
    return Notice.deadline_at.is_(None)


def _deadline_window_condition(days: int, now: datetime):
    """의견등록 마감이 ``[요청 시각, KST 오늘+days일의 끝)``에 드는 조건.

    D-day 표시가 날짜 단위이므로 창도 날짜로 끊는다(ADR-0067 결정 6). 하한이 요청
    시각이라 이미 지난 마감은 임박이 아니고, `deadline_at`이 null인 미확인 건도 창에
    들지 않는다 — 미확인을 임박으로 승격시키지 않는다.
    """

    last_day = _today_seoul(now) + timedelta(days=days)
    return and_(
        Notice.deadline_at.is_not(None),
        Notice.deadline_at >= now,
        Notice.deadline_at < _seoul_day_end_exclusive(last_day),
    )


def _deadline_passed_expression(now: datetime):
    """SQL로 평가하는 "의견등록 마감이 지났다" 술어.

    정의는 `services/pre_spec_scope.deadline_passed_expression` 하나다 — 사전규격
    자동 처리 범위(deep_review)가 같은 정의를 쓴다. `deadline_at`이 null이면
    false이므로 미확인은 `current`에 남는다(ADR-0064).
    """

    return deadline_passed_expression(now)


def _deadline_scope_matches(scope: PreSpecDeadlineScope, passed: bool) -> bool:
    if scope == "all":
        return True
    if scope == "passed":
        return passed
    return not passed


#: 회사 핏 그룹 순위 (PS-01 C7). 확장이 없거나 요약이 없는 공고는 ``pending``이다.
_COMPANY_FIT_GROUP_RANK: Mapping[str, int] = {"matched": 0, "unknown": 1, "pending": 2, "mismatch": 3}
_COMPANY_FIT_PENDING_RANK = _COMPANY_FIT_GROUP_RANK["pending"]


def _company_fit_group(fields: Mapping[str, Any]) -> str:
    """프로젝션 필드에서 회사 핏 그룹 하나. 값이 없거나 모르는 값이면 ``pending``이다."""

    summary = fields.get("company_fit")
    group = summary.get("group") if isinstance(summary, Mapping) else None
    return group if group in _COMPANY_FIT_GROUP_RANK else "pending"


def _company_fit_summary(fields: Mapping[str, Any]) -> PreSpecCompanyFitSummary | None:
    summary = fields.get("company_fit")
    if not isinstance(summary, Mapping):
        return None
    return PreSpecCompanyFitSummary.model_validate(dict(summary))


@router.get("", response_model=PreSpecListResponse)
def list_pre_specs(
    notice_pk: int | None = Query(default=None, ge=1),
    sw_only: bool = Query(default=True),
    business_division: str | None = Query(default=None),
    origin: PreSpecOrigin | None = Query(default=None),
    auto_preparation_status: Annotated[PreSpecAutoPreparationStatus | None, Query()] = None,
    # These new arguments intentionally use plain Python defaults.  Besides
    # being valid FastAPI query parameters, this keeps direct router calls in
    # isolated lifecycle tests from receiving a ``Query`` sentinel when the
    # optional argument is omitted.
    workspace: PreSpecWorkspace = "all",
    review_exclusion: PreSpecReviewExclusionFilter = "all",
    deadline_scope: PreSpecDeadlineScope = "all",
    overview_view: PreSpecOverviewView = "all",
    grade: PreSpecGradeFilter | None = None,
    display_grade: PreSpecDisplayGradeFilter | None = None,
    tracking_decision: PreSpecTrackingDecision | None = None,
    tracking_status: OpportunityTrackingStatus | None = None,
    source_run_id: str | None = None,
    observed_from: date | None = None,
    observed_to: date | None = None,
    deadline_status: PreSpecDeadlineStatus | None = None,
    deadline_within_days: int | None = None,
    company_fit: PreSpecCompanyFitGroup | None = None,
    q: str | None = Query(default=None),
    sort: PreSpecSort = Query(default="published"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> PreSpecListResponse:
    """List current pre-spec records through the cumulative observation contract.

    Observation/source filters constrain membership in immutable
    ``NoticeObservation`` rows. The selected ``Notice`` row remains the source of
    current response data, so a historical run never causes a historical snapshot
    to leak into the list. Projection values are resolved in batches before
    workspace predicates and pagination are applied.
    """

    # Direct calls in isolated tests may pass strings despite FastAPI normally
    # coercing these values before entering the router.
    observed_from_value = _coerce_date(observed_from, field_name="observed_from")
    observed_to_value = _coerce_date(observed_to, field_name="observed_to")
    if (
        observed_from_value is not None
        and observed_to_value is not None
        and observed_from_value > observed_to_value
    ):
        raise HTTPException(status_code=422, detail="observed_from must be on or before observed_to")

    workspace_value: PreSpecWorkspace = workspace or "all"
    overview_view_value: PreSpecOverviewView = overview_view or "all"
    if workspace_value not in get_args(PreSpecWorkspace):
        raise HTTPException(status_code=422, detail="workspace is invalid")
    if overview_view_value not in get_args(PreSpecOverviewView):
        raise HTTPException(status_code=422, detail="overview_view is invalid")
    if grade is not None and grade not in get_args(PreSpecGradeFilter):
        raise HTTPException(status_code=422, detail="grade is invalid")
    if tracking_decision is not None and tracking_decision not in get_args(PreSpecTrackingDecision):
        raise HTTPException(status_code=422, detail="tracking_decision is invalid")
    if deadline_status is not None and deadline_status not in get_args(PreSpecDeadlineStatus):
        raise HTTPException(status_code=422, detail="deadline_status is invalid")
    deadline_scope_value: PreSpecDeadlineScope = deadline_scope or "all"
    if deadline_scope_value not in get_args(PreSpecDeadlineScope):
        raise HTTPException(status_code=422, detail="deadline_scope is invalid")
    if deadline_within_days is not None and not 1 <= int(deadline_within_days) <= 365:
        raise HTTPException(status_code=422, detail="deadline_within_days is invalid")
    if company_fit is not None and company_fit not in get_args(PreSpecCompanyFitGroup):
        raise HTTPException(status_code=422, detail="company_fit is invalid")
    source_run_value = source_run_id.strip() if isinstance(source_run_id, str) else None
    if not source_run_value:
        source_run_value = None
    tracking_status_value = tracking_status.strip() if isinstance(tracking_status, str) else None
    if tracking_status_value == "":
        tracking_status_value = None
    now = _now_utc()

    registry = extension_registry()
    projection = registry.overview_document_projection
    projection_available = registry.overview_filters_supported
    connected_link = _connected_link_subquery()
    selected_link = aliased(OpportunityLink, name="pre_spec_selected_link")
    selected_opportunity = aliased(Opportunity, name="pre_spec_selected_opportunity")
    attachment_counts = _attachment_counts_subquery()
    observed_bounds = (
        select(
            NoticeObservation.notice_id.label("notice_id"),
            func.min(NoticeObservation.observed_at).label("first_observed_at"),
            func.max(NoticeObservation.observed_at).label("last_observed_at"),
        )
        .group_by(NoticeObservation.notice_id)
        .subquery("pre_spec_observed_bounds")
    )
    tracked_exception = tracked_order_plan_connection_predicate(Notice.id)
    sw_status = Notice.qualification_flags_json["sw_business_status"].as_string()
    division_value = Notice.qualification_flags_json["business_division"].as_string()
    kept_by_tracking = and_(or_(sw_status.is_(None), sw_status != "Y"), tracked_exception)

    conditions: list[Any] = [Notice.source_type == "pre_spec"]
    if review_exclusion not in get_args(PreSpecReviewExclusionFilter):
        raise HTTPException(status_code=422, detail="review_exclusion is invalid")
    if review_exclusion != "all":
        conditions.append(Notice.review_exclusion_status == review_exclusion)
    if notice_pk is not None:
        conditions.append(Notice.id == notice_pk)
    if sw_only and notice_pk is None:
        # The tracked exception is the same domain predicate used by
        # attachment eligibility; it is not a second router-owned rule.
        conditions.append(or_(sw_status == "Y", tracked_exception))
    if business_division and business_division.strip():
        conditions.append(division_value == business_division.strip())
    if origin == "추적":
        conditions.append(selected_opportunity.first_registered_stage == "order_plan")
    elif origin == "신규":
        conditions.append(selected_opportunity.first_registered_stage.in_(("pre_spec", "bid_notice")))
    if tracking_decision == "pending":
        conditions.append(
            and_(
                selected_opportunity.first_registered_stage.in_(("pre_spec", "bid_notice")),
                or_(
                    selected_opportunity.tracking_status.is_(None),
                    selected_opportunity.tracking_status.in_(_TRACKING_PENDING_STATUSES),
                ),
            )
        )
    if tracking_status_value is not None:
        if tracking_status_value not in {"계속 추적", "보류", "종료", "미선택"}:
            raise HTTPException(status_code=422, detail="tracking_status is invalid")
        conditions.append(selected_opportunity.tracking_status == tracking_status_value)
    if q and search_key(q):
        conditions.append(
            or_(
                search_sql_match(Notice.title, q),
                search_sql_match(Notice.agency, q),
                search_sql_match(Notice.demand_agency, q),
            )
        )
    if source_run_value is not None or observed_from_value is not None or observed_to_value is not None:
        conditions.append(
            _observation_membership_predicate(
                Notice.id,
                source_run_id=source_run_value,
                observed_from=observed_from_value,
                observed_to=observed_to_value,
            )
        )
    if deadline_status is not None:
        deadline_parts = _deadline_condition(deadline_status, now)
        if isinstance(deadline_parts, tuple):
            conditions.append(and_(*deadline_parts))
        else:
            conditions.append(deadline_parts)
    if deadline_within_days is not None:
        # `deadline_status`와 같은 자리의 서버 필터다 — `items`·`total`과 모든 집계
        # (`workspace_counts`·`overview_status_counts`·`deadline_scope_counts`)가 같은
        # 모집단을 읽는다.
        conditions.append(_deadline_window_condition(int(deadline_within_days), now))

    query = (
        select(
            Notice,
            selected_opportunity.id.label("opportunity_id"),
            selected_opportunity.tracking_status.label("tracking_status"),
            selected_opportunity.first_registered_stage.label("first_registered_stage"),
            kept_by_tracking.label("kept_by_tracking"),
            attachment_counts.c.attachments,
            observed_bounds.c.first_observed_at,
            observed_bounds.c.last_observed_at,
        )
        .select_from(Notice)
        .outerjoin(connected_link, connected_link.c.notice_id == Notice.id)
        .outerjoin(selected_link, selected_link.id == connected_link.c.link_id)
        .outerjoin(selected_opportunity, selected_opportunity.id == selected_link.opportunity_id)
        .outerjoin(attachment_counts, attachment_counts.c.notice_id == Notice.id)
        .outerjoin(observed_bounds, observed_bounds.c.notice_id == Notice.id)
        .where(*conditions)
    )

    # `recent` workspace has an implicit seven-day calendar window only when the
    # caller did not provide an observation range. Keep that implicit predicate
    # out of the base set so workspace_counts can count the other views over all
    # explicit filters; the recent count applies it separately below.
    recent_membership: dict[int, bool] = {}
    if observed_from_value is None and observed_to_value is None:
        recent_from, recent_to = _recent_dates(now)
        recent_expression = _observation_membership_predicate(
            Notice.id,
            source_run_id=source_run_value,
            observed_from=recent_from,
            observed_to=recent_to,
        )
    else:
        recent_expression = literal(True)
    base_id_rows = session.execute(
        query.with_only_columns(
            Notice.id.label("notice_id"),
            Notice.review_exclusion_status,
            selected_opportunity.first_registered_stage.label("first_stage"),
            selected_opportunity.tracking_status.label("selected_tracking_status"),
            recent_expression.label("recent_membership"),
            _deadline_passed_expression(now).label("deadline_passed"),
            maintain_column_froms=True,
        )
        .distinct()
        .order_by(None)
    ).all()
    included_ids: set[int] = set()
    base_ids: list[int] = []
    seen_ids: set[int] = set()
    tracking_status_by_id: dict[int, Any] = {}
    deadline_passed_by_id: dict[int, bool] = {}
    for row in base_id_rows:
        mapping = row._mapping
        notice_id = int(mapping["notice_id"])
        if mapping["review_exclusion_status"] == "included":
            included_ids.add(notice_id)
        if notice_id not in seen_ids:
            seen_ids.add(notice_id)
            base_ids.append(notice_id)
        tracking_status_by_id[notice_id] = mapping["selected_tracking_status"]
        recent_membership[notice_id] = bool(mapping["recent_membership"])
        deadline_passed_by_id[notice_id] = bool(mapping["deadline_passed"])

    registry_statuses = projection.overview_status(session, base_ids)
    overview_status = _normalise_projection_statuses(registry_statuses)
    registry_fields = projection.prespec_status_fields(session, base_ids)
    status_fields = _normalise_projection_fields(registry_fields)
    tracking_decision_absent_by_id = {
        notice_id: _tracking_decision_absent(tracking_status_by_id.get(notice_id))
        for notice_id in base_ids
    }

    projection_ids = [
        notice_id
        for notice_id in base_ids
        if (
            grade is None
            or (
                status_fields.get(notice_id, {}).get("grade") is None
                if grade == "판정 없음"
                else status_fields.get(notice_id, {}).get("grade") == grade
            )
        )
        and (
            display_grade is None
            or (
                status_fields.get(notice_id, {}).get("display_assessment", {}).get("status") == "held"
                if display_grade == "판단 보류"
                else status_fields.get(notice_id, {}).get("display_assessment", {}).get("status") == "none"
                if display_grade == "판정 없음"
                else status_fields.get(notice_id, {}).get("display_assessment", {}).get("grade") == display_grade
            )
        )
        and (
            auto_preparation_status is None
            or (
                projection_available
                and status_fields.get(notice_id, {}).get("auto_preparation_status")
                == auto_preparation_status
            )
        )
        # 회사 핏 필터(PS-01 C7)는 자동 준비 필터와 같은 자리다 — `items`·`total`·모든
        # 집계가 같은 모집단을 읽는다. 확장이 없거나 요약이 없는 공고는 `pending`이다.
        and (
            company_fit is None
            or _company_fit_group(status_fields.get(notice_id, {})) == company_fit
        )
    ]
    projection_filtered_ids = projection_ids
    overview_filtered_ids = [
        notice_id
        for notice_id in projection_filtered_ids
        if _overview_view_matches(overview_view_value, overview_status.get(notice_id))
    ]
    recent_workspace_ids = {
        notice_id
        for notice_id in projection_filtered_ids
        if recent_membership.get(notice_id, False)
    }
    if observed_from_value is not None or observed_to_value is not None:
        # Explicit observation bounds are already in the base SQL membership
        # predicate, so every base row belongs to the recent workspace count.
        recent_workspace_ids = set(projection_filtered_ids)

    def workspace_matches(
        notice_id: int,
        selected_workspace: PreSpecWorkspace,
        scope: PreSpecDeadlineScope,
    ) -> bool:
        # 검토 제외 숨김 가드가 구간 술어보다 **먼저** 온다 — 제외 건이 구간 분할의
        # 분모에 들어가면 탭 건수와 집계가 어긋난다(ADR-0064 결정 4).
        if selected_workspace in {"actionable", "needs_check", "recent"} and notice_id not in included_ids:
            return False
        if selected_workspace == "all":
            return True
        if selected_workspace == "recent":
            return notice_id in recent_workspace_ids
        if selected_workspace == "tracking":
            return tracking_status_by_id.get(notice_id) in _TRACKING_ACTIVE_STATUSES
        # 구간은 결정 대기 두 분기(actionable·needs_check)에만 산다. 위 세 분기는
        # ``scope``를 읽지 않으므로 ``workspace_counts``의 ``recent``·``tracking``·``all``
        # 칸과 그 workspace의 ``items``·``total``은 구간에 대해 구조적으로 불변이다.
        if not _deadline_scope_matches(scope, deadline_passed_by_id.get(notice_id, False)):
            return False
        if selected_workspace == "needs_check":
            return _workspace_needs_check(
                notice_id,
                overview_status=overview_status,
                status_fields=status_fields,
                tracking_decision_absent=tracking_decision_absent_by_id,
            )
        return _workspace_actionable(
            notice_id,
            overview_status=overview_status,
            tracking_decision_absent=tracking_decision_absent_by_id,
        )

    # ``overview_status_counts`` intentionally ignores ``overview_view`` while
    # retaining the active workspace. Keep this set separate from the final
    # response set, which includes the view predicate.
    active_ids = [
        notice_id
        for notice_id in projection_filtered_ids
        if workspace_matches(notice_id, workspace_value, deadline_scope_value)
    ]
    filtered_ids = [
        notice_id
        for notice_id in overview_filtered_ids
        if workspace_matches(notice_id, workspace_value, deadline_scope_value)
    ]

    # workspace_counts intentionally applies every other filter, including
    # overview_view, but not the selected workspace predicate. Its recent bucket
    # gets the implicit seven-day window when no explicit observation range exists.
    workspace_counts: dict[PreSpecWorkspace, int] = {
        name: sum(
            workspace_matches(notice_id, name, deadline_scope_value)
            for notice_id in overview_filtered_ids
        )
        for name in get_args(PreSpecWorkspace)
    }

    # 구간을 적용하기 **전** actionable 집합을 두 구간으로 나눈 건수다. 활성
    # workspace·활성 구간과 무관하게 언제나 같은 값이고 언제나 응답에 있다. 기준
    # 집합은 ``workspace_counts``와 같은 ``overview_filtered_ids``이므로 다른 필터는
    # 모두 반영된다. 두 칸의 합 == 구간 미적용 actionable 건수다.
    deadline_scope_current = 0
    deadline_scope_passed = 0
    for notice_id in overview_filtered_ids:
        if not workspace_matches(notice_id, "actionable", "all"):
            continue
        if deadline_passed_by_id.get(notice_id, False):
            deadline_scope_passed += 1
        else:
            deadline_scope_current += 1
    deadline_scope_counts = PreSpecDeadlineScopeCounts(
        current=deadline_scope_current,
        passed=deadline_scope_passed,
    )
    # `확인 필요`의 같은 분할(2026-11-19). 정의는 위와 같고 분기만 needs_check다.
    needs_check_current = 0
    needs_check_passed = 0
    for notice_id in overview_filtered_ids:
        if not workspace_matches(notice_id, "needs_check", "all"):
            continue
        if deadline_passed_by_id.get(notice_id, False):
            needs_check_passed += 1
        else:
            needs_check_current += 1
    needs_check_deadline_scope_counts = PreSpecDeadlineScopeCounts(
        current=needs_check_current,
        passed=needs_check_passed,
    )

    # Status grouping deliberately omits `overview_view`: it describes the
    # active workspace as a whole, retaining the historical ten persisted
    # statuses plus the null/not-started bucket.
    status_counts = projection.overview_status_counts(session, active_ids)
    overview_status_counts: list[PreSpecOverviewStatusCount] = []
    counted = 0
    for status in get_args(PreSpecOverviewReviewStatus):
        count = int(status_counts.get(status, 0))
        counted += count
        overview_status_counts.append(PreSpecOverviewStatusCount(status=status, count=count))
    # 개요 검토 행이 없는 공고(미시작)는 열한 번째 bucket이다. 제공자가 없으면
    # 전체가 여기 들어간다. 제공자가 전체보다 많이 세면 응답 계약(ge=0)을 지키려
    # 0으로 막는다 — 그런 제공자는 자기 테스트에서 잡혀야 한다.
    overview_status_counts.append(
        PreSpecOverviewStatusCount(status=None, count=max(len(active_ids) - counted, 0))
    )

    if sort == "fit":
        # 그룹 순위는 `(notice_id, rank)` VALUES 목록으로 join한다. 목록에 없는 id는
        # pending(2)이다. id는 서버가 만든 정수라 literal로 넣는다.
        ranked = [
            (notice_id, _COMPANY_FIT_GROUP_RANK[_company_fit_group(status_fields.get(notice_id, {}))])
            for notice_id in filtered_ids
        ]
        ranked = [(notice_id, rank) for notice_id, rank in ranked if rank != _COMPANY_FIT_PENDING_RANK]
        rank_order: list[Any] = []
        if ranked:
            fit_rank = (
                values(
                    column("notice_id", Integer),
                    column("fit_rank", Integer),
                    name="pre_spec_fit_rank",
                    literal_binds=True,
                )
                .data(ranked)
                .cte("pre_spec_fit_rank")
            )
            query = query.outerjoin(fit_rank, fit_rank.c.notice_id == Notice.id)
            rank_order.append(func.coalesce(fit_rank.c.fit_rank, _COMPANY_FIT_PENDING_RANK).asc())
        deadline_bucket, future_deadline, past_deadline = deadline_sort_expression(now)
        query = query.order_by(
            *rank_order,
            deadline_bucket.asc(),
            future_deadline.asc().nulls_last(),
            past_deadline.desc().nulls_last(),
            Notice.id.asc(),
        )
    elif sort == "deadline":
        deadline_bucket, future_deadline, past_deadline = deadline_sort_expression(now)
        query = query.order_by(
            deadline_bucket.asc(),
            future_deadline.asc().nulls_last(),
            past_deadline.desc().nulls_last(),
            Notice.id.asc(),
        )
    elif sort == "observed":
        query = query.order_by(
            observed_bounds.c.last_observed_at.desc().nulls_last(),
            Notice.id.desc(),
        )
    else:
        query = query.order_by(Notice.published_at.desc().nulls_last(), Notice.id.desc())
    query = query.where(Notice.id.in_(filtered_ids))
    rows = session.execute(query.offset(offset).limit(limit)).all()

    page_ids = [int(row._mapping[Notice].id) for row in rows]
    document_counts = projection.document_counts(session, page_ids)
    absent_counts = PreSpecDocumentCounts()
    absent_status: Mapping[str, Any] = {}

    items: list[PreSpecListItem] = []
    for row in rows:
        mapping = row._mapping
        notice: Notice = mapping[Notice]
        first_stage = mapping["first_registered_stage"]
        if first_stage == "order_plan":
            origin_value = "추적"
        elif first_stage in {"pre_spec", "bid_notice"}:
            origin_value = "신규"
        else:
            origin_value = None
        counts = document_counts.get(notice.id, absent_counts)
        status = status_fields.get(notice.id, absent_status)
        next_action = _next_action(
            overview_status.get(notice.id),
            tracking_decision_absent_by_id.get(notice.id, True),
        )
        items.append(
            PreSpecListItem(
                notice_pk=notice.id,
                review_exclusion_status=notice.review_exclusion_status,
                review_exclusion_actor_name=notice.review_exclusion_actor_name,
                review_exclusion_reason=notice.review_exclusion_reason,
                review_exclusion_changed_at=notice.review_exclusion_changed_at,
                pre_spec_no=_pre_spec_number(notice),
                title=notice.title,
                agency=notice.agency,
                demand_agency=notice.demand_agency,
                published_at=notice.published_at,
                deadline_at=notice.deadline_at,
                budget=decimal_float(notice.budget),
                sw_business_status=_qualification_value(notice, "sw_business_status"),
                business_division=_qualification_value(notice, "business_division"),
                origin=origin_value,
                opportunity_id=mapping["opportunity_id"],
                tracking_status=mapping["tracking_status"],
                kept_by_tracking=bool(mapping["kept_by_tracking"]),
                overview_review_status=overview_status.get(notice.id),
                grade=status.get("grade"),
                grade_source=status.get("grade_source"),
                display_assessment=status.get("display_assessment", {}),
                auto_preparation_status=status.get(
                    "auto_preparation_status", "not_applicable"
                ),
                auto_preparation_reason=status.get("auto_preparation_reason"),
                latest_deep_review_id=status.get("latest_deep_review_id"),
                latest_deep_review_status=status.get("latest_deep_review_status"),
                first_observed_at=mapping["first_observed_at"],
                last_observed_at=mapping["last_observed_at"],
                next_action=next_action,
                company_fit=_company_fit_summary(status),
                document=PreSpecDocumentSummary(
                    attachments=_count(mapping["attachments"]),
                    completed=counts.completed,
                    pending=counts.pending,
                    running=counts.running,
                    blocked=counts.blocked,
                    failed=counts.failed,
                ),
            )
        )
    return PreSpecListResponse(
        items=items,
        total=len(filtered_ids),
        limit=limit,
        offset=offset,
        overview_status_counts=overview_status_counts,
        workspace_counts=workspace_counts,
        deadline_scope_counts=deadline_scope_counts,
        needs_check_deadline_scope_counts=needs_check_deadline_scope_counts,
    )


def default_view_totals(session: Session) -> tuple[int, int] | None:
    """대시보드·사이드바 건수: (`검토할 항목` 기본 보기 total, `확인 필요` 기본 보기 total).

    둘 다 화면이 여는 목록 질의 **그 자체**로 센다 — `workspace=actionable`·
    `deadline_scope=current`·`sw_only=true`이고 나머지 필터는 없다. `확인 필요`는
    같은 응답의 `workspace_counts["needs_check"]`(같은 구간)이며 이것이
    `workspace=needs_check&deadline_scope=current` 목록의 total과 같다. 같은 식을
    다른 곳에 다시 쓰면 타일 건수와 목록 건수가 갈린다(옛 `pre_spec_deep_review_ready`는
    마감·검토 제외·SW 조건을 보지 않아 목록과 달랐다).

    개요·문서 projection 제공자가 없으면 ``None``이다 — 검토할 항목을 판정할 수
    없으므로 0으로 접지 않는다.
    """

    if not extension_registry().overview_filters_supported:
        return None
    response = list_pre_specs(
        notice_pk=None,
        sw_only=True,
        business_division=None,
        origin=None,
        auto_preparation_status=None,
        workspace="actionable",
        review_exclusion="all",
        deadline_scope="current",
        overview_view="all",
        q=None,
        sort="published",
        limit=1,
        offset=0,
        session=session,
    )
    return response.total, int(response.workspace_counts.get("needs_check", 0))


@router.post("/review-exclusions", response_model=PreSpecReviewExclusionResponse)
def update_review_exclusions(
    request: PreSpecReviewExclusionRequest,
    session: Session = Depends(get_db),
) -> PreSpecReviewExclusionResponse:
    try:
        result = change_review_exclusions(session, request)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


@router.get(
    "/{notice_pk}/order-plan-candidates",
    response_model=PreSpecOrderPlanCandidatesResponse,
)
def list_order_plan_candidates(
    notice_pk: int,
    session: Session = Depends(get_db),
) -> PreSpecOrderPlanCandidatesResponse:
    """Pending order-plan candidates proposed for one pre-spec (spec §4.4)."""

    response = pre_spec_order_plan_candidates(session, notice_pk)
    if response is None:
        raise HTTPException(status_code=404, detail="사전규격을 찾을 수 없습니다.")
    return response


__all__ = ["router"]
