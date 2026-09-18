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
    """누적 모드: 활성화된 적 있는 policy 버전(`activated_at` 오름차순). 비어 있을 수 있다."""

    mode: Literal["cumulative"]
    policy_versions: list[str]


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
    schema_version: Literal["order-plan-list-response.v4"]
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


class OrderPlanDetailResponse(_Strict):
    schema_version: Literal["order-plan-detail-response.v3"]
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
    observations: list[OrderPlanObservationView]
    screening_history: list[ScreeningHistoryItem]
    latest_human_feedback: HumanFeedbackSummary | None
    tracking: OrderPlanTracking | None


class ScreeningHistoryResponse(_Strict):
    schema_version: Literal["order-plan-detail-response.v1"]
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
