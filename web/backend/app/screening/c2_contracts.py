"""C-2(발주계획 선별) 산출물 계약 (`bidops.order-plan-screening-*.v1`).

`app/ingest/contracts.py`의 회차 적재 계약과 달리 C-2는 동결된 버전 hand-off라
알 수 없는 키를 거부하고 JSON Schema의 ``if/then`` 상태 조합까지 검증한다.
정본 스키마는 `skills/bidops-screen/contracts/`이며 이 모듈은 그 소비자다.
screening 모듈이 소유하고, lifecycle은 이 계약을 알지 못한다(명세 §6.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# The older importer models above intentionally allow extra fields for
# compatibility warnings.  C-2 is a frozen, versioned hand-off, so these
# models reject unknown keys and validate the state combinations that a JSON
# Schema ``if/then`` rule expresses.


class C2StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _c2_sha256(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
    return value


def _c2_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class C2ArtifactReference(C2StrictModel):
    name: str = Field(min_length=1)
    schema_version: Literal["bidops.collected-order-plans.v1"]
    sha256: str

    _validate_sha256 = field_validator("sha256")(_c2_sha256)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "/" in value or "\\" in value:
            raise ValueError("artifact name must be a single safe relative name")
        if value in {".", ".."}:
            raise ValueError("artifact name is unsafe")
        return value


class C2BindingReference(C2StrictModel):
    version: str = Field(min_length=1)
    sha256: str

    _validate_sha256 = field_validator("sha256")(_c2_sha256)


class OrderPlanScreeningInputItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class OrderPlanScreeningInputArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-input.v1"]
    producer: Literal["order-plan-screening-orchestrator"]
    consumer: Literal["order-plan-screening-worker"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    source_artifact: C2ArtifactReference
    population_count: int = Field(ge=1)
    population_sha256: str
    policy: C2BindingReference
    stage1_binding: C2BindingReference
    stage2_binding: C2BindingReference
    items: list[OrderPlanScreeningInputItem] = Field(min_length=1)
    status: Literal["frozen"]
    created_at: datetime

    _validate_population_sha256 = field_validator("population_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def unique_population(self) -> "OrderPlanScreeningInputArtifact":
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("input items must contain unique plan_id values")
        if self.population_count != len(self.items):
            raise ValueError("population_count must equal the number of items")
        return self


class OrderPlanScreeningRankingItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=1)
    score: float | None = Field(default=None, ge=0)
    nearest_capability: str | None = None
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"]

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float | None) -> float | None:
        if value is not None:
            import math

            if not math.isfinite(value):
                raise ValueError("score must be finite")
        return value


class OrderPlanScreeningRankingArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-ranking.v1"]
    producer: Literal["order-plan-screening-bm25"]
    consumer: Literal["order-plan-screening-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    policy_version: str = Field(min_length=1)
    policy_sha256: str
    status: Literal["성공", "실패"]
    population_count: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    filtered_out_count: int = Field(ge=0)
    items: list[OrderPlanScreeningRankingItem] = Field(min_length=1)
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_policy_sha256 = field_validator("policy_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def population_and_status(self) -> "OrderPlanScreeningRankingArtifact":
        if len(self.items) != self.population_count:
            raise ValueError("ranking must contain the full population")
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("ranking items must contain unique plan_id values")
        selected = sum(item.stage1_status == "selected" for item in self.items)
        filtered = sum(item.stage1_status == "filtered_out" for item in self.items)
        if selected != self.selected_count or filtered != self.filtered_out_count:
            raise ValueError("ranking counts do not match item statuses")
        for item in self.items:
            if item.stage1_status in {"selected", "filtered_out"} and (
                item.rank is None or item.score is None
            ):
                raise ValueError("rank and score are required for ranked items")
            if item.stage1_status in {"failed", "rejected"} and any(
                value is not None
                for value in (item.rank, item.score, item.nearest_capability)
            ):
                raise ValueError("failed or rejected ranking items must be null")
        return self


class OrderPlanScreeningDecisionBinding(C2StrictModel):
    model_name: Literal["qwen3.8-27B"]
    model_digest: str
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str
    company_profile_version: str = Field(min_length=1)
    company_profile_sha256: str
    generation_config_sha256: str

    _validate_hashes = field_validator(
        "model_digest",
        "prompt_sha256",
        "company_profile_sha256",
        "generation_config_sha256",
    )(_c2_sha256)


class OrderPlanScreeningDecisionBatch(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    plan_ids: list[str]
    attempt_count: int = Field(ge=1, le=2)
    status: Literal["success", "failed", "rejected"]


class OrderPlanScreeningDecisionItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1, le=2)
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class OrderPlanScreeningDecisionsArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-decisions.v1"]
    producer: Literal["order-plan-screening-qwen-worker"]
    consumer: Literal["order-plan-screening-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    ranking_artifact_sha256: str
    binding: OrderPlanScreeningDecisionBinding
    status: Literal["성공", "부분 성공", "실패"]
    candidate_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    batches: list[OrderPlanScreeningDecisionBatch]
    items: list[OrderPlanScreeningDecisionItem]
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_ranking_sha256 = field_validator("ranking_artifact_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def unique_batches_and_items(self) -> "OrderPlanScreeningDecisionsArtifact":
        batch_ids = [batch.batch_id for batch in self.batches]
        if len(batch_ids) != len(set(batch_ids)) or self.batch_count != len(self.batches):
            raise ValueError("decision batch count or identity is invalid")
        item_ids = [item.plan_id for item in self.items]
        if len(item_ids) != len(set(item_ids)) or self.success_count != len(self.items):
            raise ValueError("decision item count or identity is invalid")
        if any(item.batch_id not in set(batch_ids) for item in self.items):
            raise ValueError("decision item references an unknown batch")
        return self


class OrderPlanScreeningFailure(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    plan_ids: list[str] = Field(min_length=1)
    attempt_count: int = Field(ge=1, le=2)
    max_attempts: Literal[2]
    failure_type: Literal[
        "timeout", "truncated_output", "schema_violation", "id_mismatch",
        "model_mismatch", "binding_mismatch", "payload_not_approved", "transport",
        "policy_rejected", "unknown",
    ]
    outcome: Literal["failed", "rejected", "unknown"]
    status: Literal["human_review_required"]
    error_code: str = Field(min_length=1, max_length=128)


class OrderPlanScreeningFailuresArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-failures.v1"]
    producer: Literal["order-plan-screening-worker"]
    consumer: Literal["order-plan-screening-review-and-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    status: Literal["none", "partial", "failed", "rejected"]
    failure_count: int = Field(ge=0)
    failures: list[OrderPlanScreeningFailure]
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def count_failures(self) -> "OrderPlanScreeningFailuresArtifact":
        if self.failure_count != len(self.failures):
            raise ValueError("failure_count does not match failures")
        if not self.failures and self.status != "none":
            raise ValueError("empty failures artifact must have status none")
        if self.failures and self.status == "none":
            raise ValueError("non-empty failures artifact cannot have status none")
        return self


class OrderPlanScreeningMeasurement(C2StrictModel):
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def aware_if_present(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _c2_aware_datetime(value)

    @model_validator(mode="after")
    def ordered(self) -> "OrderPlanScreeningMeasurement":
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("measurement finished_at precedes started_at")
        return self


class OrderPlanScreeningTelemetryAttempt(C2StrictModel):
    attempt_no: int = Field(ge=1, le=2)
    status: Literal["success", "failed", "rejected"]
    started_at: datetime | None
    finished_at: datetime | None
    measurement: OrderPlanScreeningMeasurement

    @field_validator("started_at", "finished_at")
    @classmethod
    def aware_if_present(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _c2_aware_datetime(value)

    @model_validator(mode="after")
    def ordered(self) -> "OrderPlanScreeningTelemetryAttempt":
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("attempt finished_at precedes started_at")
        return self


class OrderPlanScreeningTelemetryBatch(C2StrictModel):
    batch_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    status: Literal["success", "failed", "rejected", "unknown"]
    attempts: list[OrderPlanScreeningTelemetryAttempt]


class OrderPlanScreeningTelemetryArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-telemetry.v1"]
    producer: Literal["order-plan-screening-worker"]
    consumer: Literal["observability-and-merge"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    status: Literal["complete", "partial", "not_measured"]
    execution: OrderPlanScreeningMeasurement
    batches: list[OrderPlanScreeningTelemetryBatch]
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)


class OrderPlanScreeningResultCounts(C2StrictModel):
    population: int = Field(ge=0)
    stage1_selected: int = Field(ge=0)
    stage1_filtered_out: int = Field(ge=0)
    stage1_failed: int = Field(ge=0)
    stage2_relevant: int = Field(ge=0)
    stage2_not_relevant: int = Field(ge=0)
    stage2_uncertain: int = Field(ge=0)
    stage2_failed: int = Field(ge=0)
    stage2_rejected: int = Field(ge=0)
    human_review_count: int = Field(ge=0)


class OrderPlanScreeningResultItem(C2StrictModel):
    plan_id: str = Field(min_length=1)
    stage1_status: Literal["selected", "filtered_out", "failed", "rejected"]
    stage1_rank: int | None = Field(ge=1)
    stage1_score: float | None = Field(ge=0)
    nearest_capability: str | None
    stage2_status: Literal["not_attempted", "success", "failed", "rejected", "unknown"]
    qwen_relevance: Literal["relevant", "not_relevant", "uncertain"] | None
    qwen_score: float | None = Field(ge=0, le=1)
    qwen_reason: str | None
    batch_id: str | None
    attempt_no: int | None = Field(ge=1, le=2)
    failure_code: str | None

    @field_validator("stage1_score", "qwen_score")
    @classmethod
    def finite_if_present(cls, value: float | None) -> float | None:
        if value is not None:
            import math

            if not math.isfinite(value):
                raise ValueError("score must be finite")
        return value

    @model_validator(mode="after")
    def state_fields(self) -> "OrderPlanScreeningResultItem":
        stage2_null = (
            self.qwen_relevance, self.qwen_score, self.qwen_reason,
            self.batch_id, self.attempt_no, self.failure_code,
        )
        if self.stage1_status in {"failed", "rejected"}:
            if self.stage2_status != "not_attempted" or any(
                value is not None for value in stage2_null
            ):
                raise ValueError("stage1 failure/rejection must not carry stage2 data")
            return self
        if self.stage1_rank is None or self.stage1_score is None:
            raise ValueError("rank and score are required for a ranked item")
        if self.stage1_status == "filtered_out" and self.stage2_status != "not_attempted":
            raise ValueError("filtered_out item must not be attempted")
        if self.stage2_status == "not_attempted":
            if any(value is not None for value in (self.qwen_relevance, self.qwen_score, self.qwen_reason, self.batch_id, self.attempt_no, self.failure_code)):
                raise ValueError("not_attempted item has result fields")
        elif self.stage2_status == "success":
            if self.qwen_relevance is None or self.qwen_score is None or self.qwen_reason is None or not self.qwen_reason.strip() or len(self.qwen_reason) > 500 or self.batch_id is None or self.attempt_no is None or self.failure_code is not None:
                raise ValueError("successful stage2 item is incomplete")
        else:
            if self.qwen_relevance is not None or self.qwen_score is not None or self.qwen_reason is not None or self.failure_code is None or not self.failure_code.strip():
                raise ValueError("failed stage2 item has invalid nullable fields")
        if (self.batch_id is None) != (self.attempt_no is None):
            raise ValueError("batch_id and attempt_no must be paired")
        return self


class OrderPlanScreeningResultArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-result.v1"]
    producer: Literal["order-plan-screening-merge"]
    consumer: Literal["postgres-loader-and-review-api"]
    execution_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    input_artifact_sha256: str
    policy_version: str = Field(min_length=1)
    policy_sha256: str
    status: Literal["성공", "부분 성공", "실패", "거부됨"]
    partial_artifact: bool
    counts: OrderPlanScreeningResultCounts
    items: list[OrderPlanScreeningResultItem] = Field(min_length=1)
    created_at: datetime

    _validate_input_sha256 = field_validator("input_artifact_sha256")(_c2_sha256)
    _validate_policy_sha256 = field_validator("policy_sha256")(_c2_sha256)
    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @model_validator(mode="after")
    def full_population_and_counts(self) -> "OrderPlanScreeningResultArtifact":
        ids = [item.plan_id for item in self.items]
        if len(ids) != len(set(ids)) or len(ids) != self.counts.population:
            raise ValueError("result must contain the full population exactly once")
        stage1_selected = sum(item.stage1_status == "selected" for item in self.items)
        stage1_filtered = sum(item.stage1_status == "filtered_out" for item in self.items)
        stage1_failed = sum(item.stage1_status in {"failed", "rejected"} for item in self.items)
        stage2_relevant = sum(item.qwen_relevance == "relevant" for item in self.items)
        stage2_not_relevant = sum(item.qwen_relevance == "not_relevant" for item in self.items)
        stage2_uncertain = sum(item.qwen_relevance == "uncertain" for item in self.items)
        stage2_failed = sum(item.stage2_status == "failed" for item in self.items)
        stage2_rejected = sum(item.stage2_status == "rejected" for item in self.items)
        expected = {
            "stage1_selected": stage1_selected,
            "stage1_filtered_out": stage1_filtered,
            "stage1_failed": stage1_failed,
            "stage2_relevant": stage2_relevant,
            "stage2_not_relevant": stage2_not_relevant,
            "stage2_uncertain": stage2_uncertain,
            "stage2_failed": stage2_failed,
            "stage2_rejected": stage2_rejected,
            "human_review_count": stage1_failed + stage2_failed + stage2_rejected + sum(item.stage2_status == "unknown" for item in self.items) + stage2_relevant + stage2_uncertain,
        }
        for field_name, value in expected.items():
            if getattr(self.counts, field_name) != value:
                raise ValueError(f"result count {field_name} does not match items")
        incomplete = stage1_failed + stage2_failed + stage2_rejected + sum(item.stage2_status == "unknown" for item in self.items)
        successful = stage2_relevant + stage2_not_relevant + stage2_uncertain
        expected_status = (
            "성공" if incomplete == 0 and successful == stage1_selected
            else "거부됨" if stage1_failed == 0 and stage1_selected > 0 and stage2_rejected == stage1_selected
            else "부분 성공" if successful > 0
            else "실패"
        )
        if self.status != expected_status or self.partial_artifact != (self.status != "성공"):
            raise ValueError("result status or partial_artifact is inconsistent")
        return self


class OrderPlanScreeningFeedbackArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-feedback.v1"]
    producer: Literal["human-review-api"]
    consumer: Literal["postgres-review-history"]
    feedback_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    actor_kind: Literal["human"]
    claimed_name: str = Field(min_length=1)
    relevance: Literal["relevant", "not_relevant", "uncertain"]
    priority: Literal["high", "medium", "low"] | None
    memo: str | None
    supersedes_feedback_id: str | None = None
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)

    @field_validator("memo")
    @classmethod
    def nonblank_memo(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("memo must be nonblank when supplied")
        return value


class OrderPlanScreeningPolicyArtifact(C2StrictModel):
    schema_version: Literal["bidops.order-plan-screening-policy.v1"]
    producer: Literal["phase0-contracts"]
    consumer: Literal["phase1-screening-pipeline"]
    policy_version: str = Field(min_length=1, max_length=64)
    policy_status: Literal["draft", "activation_candidate", "active", "retired"]
    decision_scope: Literal["c2_order_plan_first_pass"]
    created_at: datetime
    stage1: dict[str, Any]
    stage2: dict[str, Any]
    audit_sample: dict[str, Any]
    execution: dict[str, Any]
    feedback: dict[str, Any]
    quality_gate: dict[str, Any]
    bindings: dict[str, Any]
    activation: dict[str, Any]

    _validate_created_at = field_validator("created_at")(_c2_aware_datetime)


# Public names mirror the filenames and keep callers from depending on the
# internal ``C2`` prefix used by the shared strict base model.
OrderPlanScreeningInput = OrderPlanScreeningInputArtifact
OrderPlanScreeningRanking = OrderPlanScreeningRankingArtifact
OrderPlanScreeningDecisions = OrderPlanScreeningDecisionsArtifact
OrderPlanScreeningFailures = OrderPlanScreeningFailuresArtifact
OrderPlanScreeningTelemetry = OrderPlanScreeningTelemetryArtifact
OrderPlanScreeningResult = OrderPlanScreeningResultArtifact
OrderPlanScreeningFeedback = OrderPlanScreeningFeedbackArtifact
OrderPlanScreeningPolicy = OrderPlanScreeningPolicyArtifact
