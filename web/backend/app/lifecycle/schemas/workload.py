"""업무별 대기 건수의 메타데이터 전용 REST 계약."""
from typing import Literal

from pydantic import Field

from ...core.schema_base import AwareDateTime, RuntimeContractModel

WorkloadKey = Literal[
    "order_plan_pending",
    "pre_spec_deep_review_ready",
    "tracking_action_required",
    "tracking_hold_review_due",
    "bid_final_decision_pending",
]


class WorkloadItem(RuntimeContractModel):
    key: WorkloadKey
    count: int | None = Field(ge=0)
    unavailable_reason: str | None


class WorkloadResponse(RuntimeContractModel):
    generated_at: AwareDateTime
    items: list[WorkloadItem]
