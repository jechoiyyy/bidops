"""업무별 대기 건수의 메타데이터 전용 REST 계약."""
from typing import Literal

from pydantic import Field

from ...core.schema_base import AwareDateTime, RuntimeContractModel

#: 응답 항목의 고정 순서이자 전체 어휘. 앞 다섯은 ADR-0053(2026-09-17 개정 포함),
#: 뒤 다섯은 실무자 대시보드 패널 계약(ADR-0067)이 더했다 — 세는 키 넷과 그중 둘의
#: 합계 하나다. `human_check_required`가 그 합계이며 바로 뒤 두 하위 건수를 더한
#: 값이고, 하나라도 `null`이면 합계도 `null`(`sub_count_unavailable`)이다.
#: 마지막 `company_attention`(RL-00)은 실회사 활성 그래프의 `proposed`+`unknown`
#: 비evidence 노드 수이며 deep_review가 센다. 짝 목록 REST가 없는 ADR-0067 예외다
#: (화면은 profile facts로 직접 센다). 실회사가 없으면 `null`(`provider_absent`).
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
    "company_attention",
]


class WorkloadItem(RuntimeContractModel):
    key: WorkloadKey
    count: int | None = Field(ge=0)
    unavailable_reason: str | None


class WorkloadResponse(RuntimeContractModel):
    generated_at: AwareDateTime
    items: list[WorkloadItem]
