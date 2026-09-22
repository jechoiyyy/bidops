"""소유 모듈의 업무 집계를 고정된 응답 순서로 조합한다."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..extensions import WorkloadCount, extension_registry
from ..schemas.workload import WorkloadItem, WorkloadKey, WorkloadResponse
from .opportunity_queries import (
    count_deadline_imminent,
    count_hold_review,
    count_opportunity_action_reason,
    count_opportunity_section,
)

_WORKLOAD_KEYS: tuple[WorkloadKey, ...] = (
    "order_plan_pending",
    "pre_spec_deep_review_ready",
    "tracking_action_required",
    "tracking_hold_review_due",
    "bid_final_decision_pending",
    "tracking_deadline_imminent",
    "human_check_required",
    "overview_human_review",
    "blocking_items_open",
    "order_plan_new_priority",
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
    counts["human_check_required"] = _sum_parts(counts)
    items = []
    for key in _WORKLOAD_KEYS:
        value = counts.get(key, WorkloadCount(None, "provider_absent"))
        items.append(WorkloadItem(
            key=key, count=value.count, unavailable_reason=value.unavailable_reason
        ))
    return WorkloadResponse(generated_at=generated_at, items=items)
