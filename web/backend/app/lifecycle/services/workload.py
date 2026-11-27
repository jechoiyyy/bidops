"""소유 모듈의 업무 집계를 고정된 응답 순서로 조합한다."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..extensions import WorkloadCount, extension_registry
from ..schemas.workload import WorkloadItem, WorkloadKey, WorkloadResponse
from .briefing import count_briefing_pending
from .opportunity_queries import (
    count_deadline_imminent,
    count_hold_review,
    count_opportunity_action_reason,
    count_opportunity_section,
)

_WORKLOAD_KEYS: tuple[WorkloadKey, ...] = (
    "order_plan_pending",
    "pre_spec_actionable",
    "pre_spec_needs_check",
    "tracking_action_required",
    "tracking_hold_review_due",
    "bid_final_decision_pending",
    "tracking_deadline_imminent",
    "human_check_required",
    "overview_human_review",
    "blocking_items_open",
    "order_plan_new_priority",
    "company_attention",
    "briefing_pending",
    "engine_approval_pending",
    "engine_result_pending",
)
#: `human_check_required`는 저장·측정된 값이 아니라 두 하위 건수의 합이다.
_HUMAN_CHECK_PARTS: tuple[WorkloadKey, WorkloadKey] = ("overview_human_review", "blocking_items_open")


def _sum_parts(counts: dict[WorkloadKey, WorkloadCount]) -> WorkloadCount:
    """하위 건수의 합. 하나라도 셀 수 없으면 합계도 셀 수 없다(ADR-0067 결정 5).

    제공자 부재(`null`)를 0으로 접으면 "확인할 일 없음"으로 읽히므로, 합계는 두 하위가
    모두 정수일 때만 정수다.
    """

    parts = [counts.get(key, WorkloadCount(None, "provider_absent")) for key in _HUMAN_CHECK_PARTS]
    if any(part.count is None for part in parts):
        return WorkloadCount(None, "sub_count_unavailable")
    return WorkloadCount(sum(part.count for part in parts))


def get_workload(session: Session, *, now: datetime | None = None) -> WorkloadResponse:
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    counts = dict(extension_registry().workload_counts(session))
    # lifecycle이 직접 세는 네 값은 목록과 같은 식을 쓴다: `조치 필요` 구역,
    # `hold_review=overdue`, `deadline_within_days=7`, `reason=blocking_item`
    # (spec §7.1). 형제 모듈의 테이블은 확장점으로만 받는다.
    counts["tracking_action_required"] = WorkloadCount(
        count_opportunity_section(session, "조치 필요", now=generated_at)
    )
    counts["tracking_hold_review_due"] = WorkloadCount(
        count_hold_review(session, "overdue", now=generated_at)
    )
    counts["tracking_deadline_imminent"] = WorkloadCount(
        count_deadline_imminent(session, now=generated_at)
    )
    counts["blocking_items_open"] = WorkloadCount(
        count_opportunity_action_reason(session, "blocking_item", now=generated_at)
    )
    # 사전규격 두 칸은 화면이 여는 목록 질의 그 자체로 센다(2026-11-19). 목록 질의는
    # router에 있으므로 함수 안에서 늦게 들여온다 — 같은 식을 여기 다시 쓰지 않는다.
    from ..routers.pre_specs import default_view_totals

    pre_spec_totals = default_view_totals(session)
    if pre_spec_totals is None:
        counts["pre_spec_actionable"] = WorkloadCount(None, "provider_absent")
        counts["pre_spec_needs_check"] = WorkloadCount(None, "provider_absent")
    else:
        counts["pre_spec_actionable"] = WorkloadCount(pre_spec_totals[0])
        counts["pre_spec_needs_check"] = WorkloadCount(pre_spec_totals[1])
    counts["human_check_required"] = _sum_parts(counts)
    # RL-01: 가장 최근 브리핑의 대기 추천 수. 브리핑이 없으면 셀 대상이 없다(0으로 접지 않는다).
    pending = count_briefing_pending(session)
    counts["briefing_pending"] = (
        WorkloadCount(None, "provider_absent") if pending is None else WorkloadCount(pending)
    )
    items = []
    for key in _WORKLOAD_KEYS:
        value = counts.get(key, WorkloadCount(None, "provider_absent"))
        items.append(WorkloadItem(
            key=key, count=value.count, unavailable_reason=value.unavailable_reason
        ))
    return WorkloadResponse(generated_at=generated_at, items=items)
