"""Wire schemas for the manual C-2 order-plan review surface."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionCreateRequest(_Strict):
    schema_version: Literal["execution-create-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["screening-api"]
    request_id: UUID
    source_run_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=64)


class ExecutionStopRequest(_Strict):
    schema_version: Literal["execution-stop-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["screening-api"]
    request_id: UUID
    reason: Literal["user_requested"] = "user_requested"


class FeedbackCreateRequest(_Strict):
    schema_version: Literal["feedback-create-request.v1"]
    producer: Literal["human-review-client"]
    consumer: Literal["review-api"]
    request_id: UUID
    execution_id: UUID
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None = None
    memo: str | None = Field(default=None, max_length=2000)
    expected_revision: int | None = Field(default=None, ge=0)


class ArtifactSummary(_Strict):
    kind: Literal["screening_input", "ranking", "decisions", "failures", "telemetry", "screening_result"]
    artifact_schema_version: str
    artifact_producer: str
    artifact_consumer: str
    sha256: str
    byte_count: int = Field(ge=0)
    object_version: str | None = None
    validation_status: Literal["pending", "valid", "invalid"]
    created_at: datetime


class ArtifactSummaryResponse(_Strict):
    schema_version: Literal["artifact-summary-response.v1"]
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    kind: Literal["screening_input", "ranking", "decisions", "failures", "telemetry", "screening_result"]
    artifact_schema_version: str
    artifact_producer: str
    artifact_consumer: str
    sha256: str
    byte_count: int = Field(ge=0)
    object_version: str | None = None
    validation_status: Literal["pending", "valid", "invalid"]
    created_at: datetime


class ExecutionCounts(_Strict):
    candidate_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    stage1_selected_count: int = Field(ge=0)
    stage1_filtered_out_count: int = Field(ge=0)
    stage1_failed_count: int = Field(ge=0)
    stage2_relevant_count: int = Field(ge=0)
    stage2_not_relevant_count: int = Field(ge=0)
    stage2_uncertain_count: int = Field(ge=0)
    stage2_failed_count: int = Field(ge=0)
    stage2_rejected_count: int = Field(ge=0)
    human_review_count: int = Field(ge=0)


class ExecutionSummary(_Strict):
    execution_id: UUID
    request_id: UUID
    source_run_id: str
    policy_version: str
    status: Literal["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"]
    requested_by: str
    execution_allowed: bool
    population_count: int = Field(ge=1)
    population_sha256: str
    policy_sha256: str
    binding_sha256: str
    stage1_binding_version: str
    stage1_binding_sha256: str
    stage2_binding_version: str
    stage2_binding_sha256: str
    counts: ExecutionCounts
    purpose: Literal["operational", "gate_measurement"]
    partial_artifact: bool
    error_code: str | None
    queued_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None


class ExecutionAttemptSummary(_Strict):
    attempt_id: UUID
    batch_id: str
    sequence: int
    attempt_no: int
    model_name: str
    model_digest: str
    prompt_version: str
    prompt_sha256: str
    company_profile_version: str
    company_profile_sha256: str
    generation_config_sha256: str
    attempt_status: Literal["running", "success", "failed", "rejected"]
    failure_type: Literal[
        "timeout",
        "truncated_output",
        "schema_violation",
        "id_mismatch",
        "model_mismatch",
        "binding_mismatch",
        "payload_not_approved",
        "transport",
        "policy_rejected",
        "unknown",
    ] | None
    failure_code: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None


class ExecutionCreateResponse(_Strict):
    schema_version: Literal["execution-create-response.v1"]
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    execution_id: UUID
    request_id: UUID
    source_run_id: str
    policy_version: str
    status: Literal["대기"]
    binding_sha256: str
    stage1_binding_sha256: str
    stage2_binding_sha256: str
    execution_allowed: bool


class ExecutionListResponse(_Strict):
    schema_version: Literal["execution-list-response.v2"]
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    items: list[ExecutionSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class ExecutionDetailResponse(ExecutionSummary):
    schema_version: Literal["execution-detail-response.v2"]
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    artifacts: list[ArtifactSummary]
    attempts: list[ExecutionAttemptSummary]


class ExecutionStopResponse(_Strict):
    schema_version: Literal["execution-stop-response.v1"]
    producer: Literal["screening-api"]
    consumer: Literal["human-review-client"]
    execution_id: UUID
    request_id: UUID
    status: Literal["중지 요청", "중단됨"]


class HumanFeedbackSummary(_Strict):
    revision: int
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None
    memo: str | None
    claimed_name: str
    created_at: datetime


class OrderPlanTracking(_Strict):
    opportunity_id: int
    tracking_status: Literal["미선택", "계속 추적", "보류", "종료"]
    tracking_reason: str | None
    tracking_selected_by: str | None
    tracking_selected_at: datetime | None


class OrderPlanCumulativeScope(_Strict):
    """누적 모드의 두 목록. 둘 다 policy `activated_at` 오름차순(동률은 버전 오름차순)이다.

    - `policy_versions`: 범위에 완료 실행이 실제로 있는 버전. 판정 유무를 말한다. 없으면 빈 목록이다.
    - `activated_policy_versions`: 활성화된 적 있는(`activated_at IS NOT NULL`) 버전 전부. 실행 상태를
      보일 범위를 말하므로 결과가 아직 없는 실행도 포함한다. `policy_versions`는 이것의 부분집합이다.
    """

    mode: Literal["cumulative"]
    policy_versions: list[str]
    activated_policy_versions: list[str]


class OrderPlanRunScope(_Strict):
    """회차 모드: 그 회차의 최신 완료 실행 하나. policy·purpose를 묻지 않는다."""

    mode: Literal["run"]
    execution_id: UUID
    source_run_id: str
    status: Literal["성공", "부분 성공"]
    finished_at: datetime | None
    policy_version: str
    purpose: Literal["operational", "gate_measurement"]


class OrderPlanListItem(_Strict):
    order_plan_pk: int
    order_plan_unty_no: str
    source_url: str | None
    title: str | None
    agency_name: str | None
    business_division: str | None
    budget_amount: float | None
    planned_order_year: str | None
    planned_order_month: str | None
    # 계약방법(`cntrctMthdNm`)과 공고 게시 여부(`ntceNticeYn`, 원문 `Y`/`N`)는 수집 원본 값을 그대로
    # 낸다. `notice_posted`를 bool로 좁히지 않는 것은 값이 없는 것(`null`)과 `N`이 다른 사실이기
    # 때문이다. 목록은 500행을 한 번에 받으므로 상세용 필드는 여기에 넣지 않는다.
    contract_method: str | None
    notice_posted: str | None
    source_run_id: str | None
    observed_at: datetime | None
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"] | None
    stage1_rank: int | None
    stage1_score: float | None
    nearest_capability: str | None
    stage2_status: Literal["not_attempted", "success", "failed", "rejected", "unknown"] | None
    qwen_relevance: Literal["relevant", "not_relevant", "uncertain"] | None
    qwen_score: float | None
    qwen_reason: str | None
    human_feedback: HumanFeedbackSummary | None
    tracking: OrderPlanTracking | None
    execution_id: UUID | None
    policy_version: str | None
    first_observed_at: datetime | None


class OrderPlanListResponse(_Strict):
    schema_version: Literal["order-plan-list-response.v5"]
    producer: Literal["order-plan-review-api"]
    consumer: Literal["order-plan-review-client"]
    scope: Annotated[OrderPlanCumulativeScope | OrderPlanRunScope, Field(discriminator="mode")] | None
    items: list[OrderPlanListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class OrderPlanObservationView(_Strict):
    source_run_id: str
    observed_at: datetime
    source_sha256: str | None


class ScreeningHistoryItem(_Strict):
    execution_id: UUID
    source_run_id: str
    policy_version: str
    policy_sha256: str
    binding_sha256: str
    execution_status: Literal["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"]
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"]
    stage1_rank: int | None
    stage1_score: float | None
    nearest_capability: str | None
    batch_id: str | None
    attempt_no: int | None
    stage2_status: Literal["not_attempted", "success", "failed", "rejected", "unknown"]
    qwen_relevance: Literal["relevant", "not_relevant", "uncertain"] | None
    qwen_score: float | None
    qwen_reason: str | None
    feedback_revision_count: int
    # 그 실행이 무엇이었는지 화면이 구분할 수 있게 실행 행의 값을 그대로 낸다.
    # `execution_purpose`는 `order_plan_screening_execution.purpose`(INSERT 때 고정, trigger가
    # 이후 변경을 거부)이며 화면이 `gate_measurement`를 운영 판정으로 읽지 않게 한다.
    # 시각은 대표값을 서버가 고르지 않는다 — `started_at`·`finished_at`을 나란히 내고 둘 다
    # 실행 상태에 따라 `null`일 수 있다(대기는 둘 다 null, 실행 중은 finished만 null).
    # 참조 실행(한 번도 활성화된 적 없는 policy의 실행)은 이 행에 표식이 없다. C-2에는
    # `quality_status` 열이 없고, 화면은 목록 누적 scope의 `activated_policy_versions`와
    # 이 항목의 `policy_version`을 대조해 가른다(기존 계약, 새 필드를 만들지 않는다).
    execution_purpose: Literal["operational", "gate_measurement"]
    execution_started_at: datetime | None
    execution_finished_at: datetime | None


class OrderPlanDetailResponse(_Strict):
    schema_version: Literal["order-plan-detail-response.v4"]
    producer: Literal["screening-api"]
    consumer: Literal["order-plan-review-client"]
    order_plan_pk: int
    order_plan_unty_no: str
    source_url: str | None
    title: str | None
    agency_name: str | None
    business_division: str | None
    business_division_code: str | None
    service_type: str | None
    budget_amount: float | None
    planned_order_year: str | None
    planned_order_month: str | None
    # 누적 발주계획 행(`order_plan`)이 이미 가진 열의 투영이다. 새 migration은 없고 값은
    # 수집 원본 그대로다 — `bid_ntice_no_list`는 `bidNtceNoList` 원문 문자열(공고번호가 여럿이면
    # 구분자로 이어진 한 문자열)이므로 서버가 쪼개지 않는다.
    supervising_agency_name: str | None
    procurement_method: str | None
    contract_method: str | None
    notice_posted: str | None
    bid_ntice_no_list: str | None
    published_at: datetime | None
    observations: list[OrderPlanObservationView]
    screening_history: list[ScreeningHistoryItem]
    latest_human_feedback: HumanFeedbackSummary | None
    tracking: OrderPlanTracking | None


class ScreeningHistoryResponse(_Strict):
    # `GET /api/order-plans/{id}/screening-history`는 상세와 같은 `order-plan-detail-response`
    # family 이름을 쓰면서 번호만 따로 올려 왔다(v1). 번호는 family 안에서 한 번만 쓰므로
    # (v2·v3은 상세가 이미 썼고 v4는 이번에 상세가 쓴다) 이 응답은 v5로 간다. 같은 문자열이
    # 서로 다른 모양을 뜻하게 두지 않는 것이 규칙이다.
    schema_version: Literal["order-plan-detail-response.v5"]
    producer: Literal["screening-api"]
    consumer: Literal["order-plan-review-client"]
    order_plan_pk: int
    items: list[ScreeningHistoryItem]


class FeedbackView(_Strict):
    feedback_id: UUID
    execution_id: UUID
    order_plan_pk: int
    revision: int
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None
    memo: str | None
    claimed_name: str
    created_at: datetime


class FeedbackListResponse(_Strict):
    schema_version: Literal["feedback-list-response.v1"]
    producer: Literal["screening-api"]
    consumer: Literal["order-plan-review-client"]
    items: list[FeedbackView]


class FeedbackCreateResponse(_Strict):
    schema_version: Literal["feedback-create-response.v1"]
    producer: Literal["human-review-api"]
    consumer: Literal["postgres-history"]
    feedback_id: UUID
    execution_id: UUID
    order_plan_pk: int
    revision: int
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None
    memo: str | None
    claimed_name: str
    created_at: datetime


Limit = Annotated[int, Field(default=100, ge=1, le=500)]
Offset = Annotated[int, Field(default=0, ge=0)]
