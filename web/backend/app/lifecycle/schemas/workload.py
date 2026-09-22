"""업무별 대기 건수의 메타데이터 전용 REST 계약."""
from typing import Literal

from pydantic import Field

from ...core.schema_base import AwareDateTime, RuntimeContractModel

#: 응답 항목의 고정 순서이자 전체 어휘. 앞 다섯은 ADR-0053(2026-09-17 개정 포함),
#: 뒤 다섯은 실무자 대시보드 패널 계약(ADR-0067)이 더했다 — 세는 키 넷과 그중 둘의
#: 합계 하나다. `human_check_required`가 그 합계이며 바로 뒤 두 하위 건수를 더한
#: 값이고, 하나라도 `null`이면 합계도 `null`(`sub_count_unavailable`)이다.
WorkloadKey = Literal[
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
]


class WorkloadItem(RuntimeContractModel):
    key: WorkloadKey
    count: int | None = Field(ge=0)
    unavailable_reason: str | None


class WorkloadResponse(RuntimeContractModel):
    generated_at: AwareDateTime
    items: list[WorkloadItem]
