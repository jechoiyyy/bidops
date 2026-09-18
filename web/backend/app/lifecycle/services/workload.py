"""소유 모듈의 업무 집계를 고정된 응답 순서로 조합한다."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..extensions import WorkloadCount, extension_registry
from ..schemas.workload import WorkloadItem, WorkloadKey, WorkloadResponse
from .opportunity_queries import count_hold_review, count_opportunity_section

_WORKLOAD_KEYS: tuple[WorkloadKey, ...] = (
    "order_plan_pending",
    "pre_spec_deep_review_ready",
    "tracking_action_required",
    "tracking_hold_review_due",
    "bid_final_decision_pending",
)


def get_workload(session: Session, *, now: datetime | None = None) -> WorkloadResponse:
    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    counts = dict(extension_registry().workload_counts(session))
    # lifecycle이 직접 세는 두 값은 목록과 같은 식을 쓴다: `조치 필요` 구역과
    # `hold_review=overdue` 필터(spec §8).
    counts["tracking_action_required"] = WorkloadCount(
        count_opportunity_section(session, "조치 필요", now=generated_at)
    )
    counts["tracking_hold_review_due"] = WorkloadCount(
        count_hold_review(session, "overdue", now=generated_at)
    )
    items = []
    for key in _WORKLOAD_KEYS:
        value = counts.get(key, WorkloadCount(None, "provider_absent"))
        items.append(WorkloadItem(
            key=key, count=value.count, unavailable_reason=value.unavailable_reason
        ))
    return WorkloadResponse(generated_at=generated_at, items=items)
