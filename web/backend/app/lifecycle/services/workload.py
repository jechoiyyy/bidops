"""소유 모듈의 업무 집계를 고정된 응답 순서로 조합한다."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..extensions import WorkloadCount, extension_registry
from ..schemas.workload import WorkloadItem, WorkloadKey, WorkloadResponse
from .opportunity_queries import count_opportunity_section

_WORKLOAD_KEYS: tuple[WorkloadKey, ...] = (
    "order_plan_pending",
    "pre_spec_deep_review_ready",
    "tracking_action_required",
    "bid_final_decision_pending",
)


def get_workload(session: Session) -> WorkloadResponse:
    counts = dict(extension_registry().workload_counts(session))
    counts["tracking_action_required"] = WorkloadCount(
        count_opportunity_section(session, "조치 필요")
    )
    items = []
    for key in _WORKLOAD_KEYS:
        value = counts.get(key, WorkloadCount(None, "provider_absent"))
        items.append(WorkloadItem(
            key=key, count=value.count, unavailable_reason=value.unavailable_reason
        ))
    return WorkloadResponse(generated_at=datetime.now(UTC), items=items)
