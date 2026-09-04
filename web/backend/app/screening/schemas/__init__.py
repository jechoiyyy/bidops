"""screening이 소유한 요청·응답 DTO (명세 §5.2·§6.1).

프로필 projection, 판정 실행·품질 게이트·정책·스케줄 런타임 계약이다.
`models`·`services`를 import하지 않는다 (명세 §4). 공용 기반 모델·검증기는
아직 `app/schemas/__init__.py`에 core 이름으로 남아 있어 거기서 받는다.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from ...schemas import (
    APIModel,
    Actor,
    AwareDateTime,
    Digest,
    NonEmpty,
    RuntimeContractModel,
    _validate_clock_time,
    _validate_generation_binding,
    _validate_profile_binding,
    _validate_profile_error_codes,
    _validate_profile_projection_binding_values,
    _validate_run_key_for_kind,
)


ProfileStatus = Literal["confirmed", "inferred", "unknown"]
ProfileSectionState = Literal["confirmed", "inferred", "unknown", "mixed", "unrecorded"]

class ProfileItemResponse(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    key: str
    label: str
    section_id: str
    section_number: str | None = None
    status: ProfileStatus
    value: Any = None


class ProfileSectionResponse(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    number: str | None = None
    title: str
    heading: str
    level: int
    state: ProfileSectionState
    status_counts: dict[str, int] = Field(default_factory=dict)
    items: list[ProfileItemResponse] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    children: list["ProfileSectionResponse"] = Field(default_factory=list)

    _validate_error_codes = field_validator("error_codes")(_validate_profile_error_codes)


class ProfileSectionsResponse(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    schema_version: Literal["bidops.profile-projection.v1"] = "bidops.profile-projection.v1"
    profile_version: str
    profile_digest: str
    sections: list[ProfileSectionResponse] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    error_codes: list[str] = Field(default_factory=list)

    _validate_error_codes = field_validator("error_codes")(_validate_profile_error_codes)

    @model_validator(mode="after")
    def validate_profile_binding(self) -> "ProfileSectionsResponse":
        _validate_profile_projection_binding_values(self.profile_version, self.profile_digest)
        return self


class ProfileUnknownResponse(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    key: str
    label: str
    section_id: str
    section_number: str | None = None
    section_title: str
    status: Literal["unknown"] = "unknown"
    value: Any = None
    reference_count: int | None = None
    reference_status: Literal["counted", "unavailable"]


class ProfileUnknownsResponse(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    schema_version: Literal["bidops.profile-projection.v1"] = "bidops.profile-projection.v1"
    profile_version: str
    profile_digest: str
    items: list[ProfileUnknownResponse] = Field(default_factory=list)
    total: int
    reference_fields: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)

    _validate_error_codes = field_validator("error_codes")(_validate_profile_error_codes)

    @model_validator(mode="after")
    def validate_profile_binding(self) -> "ProfileUnknownsResponse":
        _validate_profile_projection_binding_values(self.profile_version, self.profile_digest)
        return self

CompanyProfileVersion = Annotated[str, StringConstraints(pattern=r"^company-profile\.sha256:[0-9a-f]{64}$")]
ScreeningExecutionId = Annotated[str, StringConstraints(pattern=r"^scr-[0-9a-f]{32}$")]
QualityGateId = Annotated[str, StringConstraints(pattern=r"^gate-[0-9a-f]{32}$")]
QualityGateEvaluationId = Annotated[str, StringConstraints(pattern=r"^gateeval-[0-9a-f]{32}$")]
ScheduleExecutionId = Annotated[str, StringConstraints(pattern=r"^sched-[0-9a-f]{32}$")]

ScreeningTrigger = Literal["cli_single", "manual_run", "quality_gate", "schedule"]
ScreeningScope = Literal["single_notice", "full_run", "quality_sample"]
ScreeningStatus = Literal["대기", "실행 중", "중지 요청", "성공", "부분 성공", "실패", "중단됨"]
ScreeningStage = Literal[
    "기술 적합성",
    "실적 정합성",
    "공공 SI 적합성",
    "사업성·자격 제약",
    "전략 부합",
    "counterargument",
    "synthesis",
    "merge",
    "publish",
]
AttemptStage = Literal[
    "기술 적합성",
    "실적 정합성",
    "공공 SI 적합성",
    "사업성·자격 제약",
    "전략 부합",
    "counterargument",
    "synthesis",
    "carried_over_validation",
]
ScreeningFailureType = Literal[
    "timeout",
    "truncated_output",
    "schema_violation",
    "evidence_missing",
    "counterargument_repetition",
]


class JudgmentExecutionCreateRequest(RuntimeContractModel):
    policy_version: NonEmpty
    profile_source: str
    requested_by: Actor

    @field_validator("profile_source")
    @classmethod
    def validate_profile_source(cls, value: str) -> str:
        if value != "current" and not value.startswith("git:"):
            raise ValueError("profile_source must be current or git:<40hex>")
        if value.startswith("git:") and (len(value) != 44 or any(c not in "0123456789abcdef" for c in value[4:])):
            raise ValueError("profile_source must be current or git:<40hex>")
        return value


class ScreeningStopRequest(RuntimeContractModel):
    requested_by: Actor


class ScreeningArtifactUrls(RuntimeContractModel):
    decisions: str | None = None
    failures: str | None = None
    telemetry: str | None = None
    screening_result: str | None = None
    published_run: str | None = None

    @field_validator("decisions", "failures", "telemetry", "screening_result", "published_run")
    @classmethod
    def validate_api_path(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/api/") or "\\" in value or ".." in value):
            raise ValueError("result URL must be a relative API path")
        return value


class ScreeningExecutionResponse(RuntimeContractModel):
    queue_no: int = Field(ge=1)
    execution_id: ScreeningExecutionId
    trigger: ScreeningTrigger
    source_run_id: NonEmpty
    scope: ScreeningScope
    notice_id: str | None = None
    status: ScreeningStatus
    requested_by: Actor
    policy_version: NonEmpty
    prompt_version: NonEmpty
    model_name: NonEmpty
    model_digest: Digest
    company_profile_version: CompanyProfileVersion
    company_profile_digest: Digest
    generation_config: dict[str, Any]
    generation_config_digest: Digest
    input_artifact_digest: Digest
    queued_at: AwareDateTime
    started_at: AwareDateTime | None = None
    finished_at: AwareDateTime | None = None
    heartbeat_at: AwareDateTime | None = None
    stop_requested_at: AwareDateTime | None = None
    stop_requested_by: Actor | None = None
    stop_reason: Literal["user_requested", "process_interrupted"] | None = None
    candidate_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    published_run_id: NonEmpty | None = None
    error_summary: NonEmpty | None = None
    queue_position: int | None = Field(default=None, ge=1)
    current_notice_id: NonEmpty | None = None
    current_stage: ScreeningStage | None = None
    result_urls: ScreeningArtifactUrls

    @model_validator(mode="after")
    def validate_scope_and_state(self) -> "ScreeningExecutionResponse":
        _validate_profile_binding(self.company_profile_version, self.company_profile_digest)
        _validate_generation_binding(self.generation_config, self.generation_config_digest, required=True)
        if self.scope == "single_notice" and self.notice_id is None:
            raise ValueError("single_notice execution requires notice_id")
        if self.scope != "single_notice" and self.notice_id is not None:
            raise ValueError("non-single execution cannot expose notice_id")
        if self.status == "대기" and self.queue_position is None:
            raise ValueError("queued execution requires queue_position")
        if self.status != "대기" and self.queue_position is not None:
            raise ValueError("queue_position is only available while queued")
        if self.status == "중지 요청" and (self.stop_requested_at is None or self.stop_requested_by is None):
            raise ValueError("stop-requested execution requires stop metadata")
        if self.stop_reason == "user_requested" and (self.stop_requested_at is None or self.stop_requested_by is None):
            raise ValueError("user stop requires stop metadata")
        if self.status in {"성공", "부분 성공", "실패", "중단됨"} and self.finished_at is None:
            raise ValueError("terminal execution requires finished_at")
        return self


class ScreeningAttemptResponse(RuntimeContractModel):
    attempt_id: int = Field(ge=1)
    execution_id: ScreeningExecutionId
    notice_id: NonEmpty
    stage: AttemptStage
    attempt_no: int = Field(ge=1)
    status: Literal["success", "failure"]
    failure_type: ScreeningFailureType | None = None
    done_reason: NonEmpty | None = None
    trace_id: NonEmpty
    span_id: NonEmpty
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)
    prompt_eval_duration_ns: int | None = Field(default=None, ge=0)
    eval_duration_ns: int | None = Field(default=None, ge=0)
    load_duration_ns: int | None = Field(default=None, ge=0)
    total_duration_ns: int | None = Field(default=None, ge=0)
    generation_config_digest: Digest | None = None
    num_ctx: int | None = Field(default=None, ge=1)
    num_predict: int | None = Field(default=None, ge=1)
    started_at: AwareDateTime
    finished_at: AwareDateTime
    error_summary: NonEmpty | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> "ScreeningAttemptResponse":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.status == "success" and self.failure_type is not None:
            raise ValueError("successful attempt cannot have failure_type")
        if self.status == "failure" and self.failure_type is None:
            raise ValueError("failed attempt requires failure_type")
        return self


class ScreeningFailureItem(RuntimeContractModel):
    notice_id: NonEmpty
    failed_stage: Literal[
        "기술 적합성",
        "실적 정합성",
        "공공 SI 적합성",
        "사업성·자격 제약",
        "전략 부합",
        "반론 검토",
        "종합 판정",
        "병합·검증",
    ]
    failure_type: ScreeningFailureType
    last_attempt_at: AwareDateTime
    retry_count: int = Field(ge=0)
    status: Literal["사람 검토 대기"]
    failure_context: Literal["carried_over_validation"] | None = None
    trace_id: NonEmpty | None = None
    span_id: NonEmpty | None = None
    error_summary: NonEmpty


class ScreeningExecutionListResponse(RuntimeContractModel):
    items: list[ScreeningExecutionResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ScreeningExecutionDetailResponse(ScreeningExecutionResponse):
    attempts: list[ScreeningAttemptResponse] = Field(default_factory=list)
    failures: list[ScreeningFailureItem] = Field(default_factory=list)


class ScreeningExecutionQuery(RuntimeContractModel):
    status: ScreeningStatus | None = None
    trigger: ScreeningTrigger | None = None
    run_id: NonEmpty | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class CompanyProfileSnapshotResponse(RuntimeContractModel):
    version: CompanyProfileVersion
    digest: Digest
    source_kind: Literal["working_tree", "git_blob"]
    # A working-tree source reference is an internal repository path and is
    # intentionally omitted from the public projection.  Historical git blob
    # SHA values remain useful lineage identifiers.
    source_ref: NonEmpty | None = None
    created_at: AwareDateTime

    @model_validator(mode="after")
    def validate_source_ref(self) -> "CompanyProfileSnapshotResponse":
        _validate_profile_binding(self.version, self.digest)
        if self.source_kind == "git_blob":
            if self.source_ref is None or len(self.source_ref) != 40 or any(c not in "0123456789abcdef" for c in self.source_ref):
                raise ValueError("git_blob source_ref must be a 40-character lowercase commit")
        elif self.source_ref is not None:
            raise ValueError("working-tree source_ref is not public")
        return self


class CompanyProfileSnapshotListResponse(RuntimeContractModel):
    items: list[CompanyProfileSnapshotResponse] = Field(default_factory=list)
    total: int = Field(ge=0)


QualityGatePurpose = Literal["model_comparison", "operational_approval"]
QualityGateExecutionStatus = Literal["대기", "실행 중", "완료", "실패", "중단됨"]
QualityGateResultStatus = Literal["통과", "미달", "미측정", "보류"]


class QualityGateCreateRequest(RuntimeContractModel):
    purpose: QualityGatePurpose
    policy_version: NonEmpty
    profile_source: str
    created_by: Actor

    @field_validator("profile_source")
    @classmethod
    def validate_profile_source(cls, value: str) -> str:
        if value != "current" and not value.startswith("git:"):
            raise ValueError("profile_source must be current or git:<40hex>")
        if value.startswith("git:") and (len(value) != 44 or any(c not in "0123456789abcdef" for c in value[4:])):
            raise ValueError("profile_source must be current or git:<40hex>")
        return value

    @model_validator(mode="after")
    def validate_purpose_profile(self) -> "QualityGateCreateRequest":
        if self.purpose == "model_comparison" and self.profile_source != "git:ee621835db934ddac944f7a07a986ed0b73ecc7a":
            raise ValueError("model_comparison requires the historical profile source")
        if self.purpose == "operational_approval" and self.profile_source != "current":
            raise ValueError("operational_approval requires current profile source")
        return self


class QualityGateEvaluationResponse(RuntimeContractModel):
    evaluation_id: QualityGateEvaluationId
    gate_id: QualityGateId
    revision: int = Field(ge=1)
    result_status: QualityGateResultStatus
    metrics: dict[str, Any]
    reasons: list[NonEmpty] = Field(default_factory=list)
    valid_review_count: int = Field(ge=0)
    distinct_notice_review_count: int = Field(ge=0)
    generation_config: dict[str, Any]
    generation_config_digest: Digest
    created_at: AwareDateTime

    @model_validator(mode="after")
    def validate_generation(self) -> "QualityGateEvaluationResponse":
        _validate_generation_binding(self.generation_config, self.generation_config_digest, required=True)
        return self


class QualityGateReviewResponse(RuntimeContractModel):
    review_id: int = Field(ge=1)
    gate_id: QualityGateId
    execution_id: ScreeningExecutionId
    notice_id: NonEmpty
    decision_digest: Digest
    reviewer: Actor
    evidence_judgment: Literal["동의", "근거 부족", "판단 보류"]
    note: NonEmpty | None = None
    created_at: AwareDateTime
    updated_at: AwareDateTime


class QualityGateReviewUpsertRequest(RuntimeContractModel):
    reviewer: Actor
    evidence_judgment: Literal["동의", "근거 부족", "판단 보류"]
    note: NonEmpty | None = None


class QualityGateResponse(RuntimeContractModel):
    gate_id: QualityGateId
    purpose: QualityGatePurpose
    execution_status: QualityGateExecutionStatus
    result_status: QualityGateResultStatus
    baseline_run_id: NonEmpty
    sample_artifact_digest: Digest
    baseline_decisions_digest: Digest
    policy_version: NonEmpty
    prompt_version: NonEmpty
    model_name: NonEmpty
    model_digest: Digest
    company_profile_version: CompanyProfileVersion
    company_profile_digest: Digest
    generation_config: dict[str, Any]
    generation_config_digest: Digest
    pass_a_execution_id: ScreeningExecutionId
    pass_b_execution_id: ScreeningExecutionId
    created_by: Actor
    created_at: AwareDateTime
    completed_at: AwareDateTime | None = None
    latest_evaluation_id: QualityGateEvaluationId
    metrics: dict[str, Any]
    reasons: list[NonEmpty] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_execution_status(self) -> "QualityGateResponse":
        _validate_profile_binding(self.company_profile_version, self.company_profile_digest)
        _validate_generation_binding(self.generation_config, self.generation_config_digest, required=True)
        terminal = {"완료", "실패", "중단됨"}
        if self.execution_status in terminal and self.completed_at is None:
            raise ValueError("terminal quality gate requires completed_at")
        if self.execution_status not in terminal and self.completed_at is not None:
            raise ValueError("non-terminal quality gate cannot have completed_at")
        if self.pass_a_execution_id == self.pass_b_execution_id:
            raise ValueError("quality gate passes must use distinct executions")
        return self


class QualityGateDetailResponse(QualityGateResponse):
    pass_a: ScreeningExecutionResponse
    pass_b: ScreeningExecutionResponse
    evaluations: list[QualityGateEvaluationResponse] = Field(default_factory=list)
    reviews: list[QualityGateReviewResponse] = Field(default_factory=list)


class QualityGateListResponse(RuntimeContractModel):
    items: list[QualityGateResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class QualityGateQuery(RuntimeContractModel):
    purpose: QualityGatePurpose | None = None
    execution_status: QualityGateExecutionStatus | None = None
    result_status: QualityGateResultStatus | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class PolicyVersionCreateRequest(RuntimeContractModel):
    policy_version: NonEmpty
    created_by: Actor
    prompt_version: NonEmpty
    perspective_prompts: dict[str, Any]
    counterargument_prompt: dict[str, Any]
    synthesis_prompt: dict[str, Any]
    candidate_selection: dict[str, Any]
    thresholds: dict[str, Any]


class PolicyCandidateRequest(RuntimeContractModel):
    confirmed_by: Actor


class PolicyActivationRequest(RuntimeContractModel):
    quality_gate_result_id: QualityGateEvaluationId
    confirmed_by: Actor


PolicyStatus = Literal["draft", "activation_candidate", "active"]


class PolicyVersionResponse(RuntimeContractModel):
    schema_version: Literal["bidops.screening-policy.v1"]
    policy_version: NonEmpty
    prompt_version: NonEmpty
    perspective_prompts: dict[str, Any]
    counterargument_prompt: dict[str, Any]
    synthesis_prompt: dict[str, Any]
    candidate_selection: dict[str, Any]
    thresholds: dict[str, Any]
    content_digest: Digest
    status: PolicyStatus
    created_at: AwareDateTime
    created_by: Actor
    activated_at: AwareDateTime | None = None
    activated_by: Actor | None = None
    quality_gate_result_id: QualityGateEvaluationId | None = None

    @model_validator(mode="after")
    def validate_activation_metadata(self) -> "PolicyVersionResponse":
        activated = (self.activated_at, self.activated_by, self.quality_gate_result_id)
        if self.status == "active" and any(value is None for value in activated):
            raise ValueError("active policy requires activation metadata")
        if self.status != "active" and any(value is not None for value in activated):
            raise ValueError("non-active policy cannot expose activation metadata")
        return self


class PolicyVersionListResponse(RuntimeContractModel):
    items: list[PolicyVersionResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    active_policy_version: NonEmpty | None = None


class PolicyVersionQuery(RuntimeContractModel):
    status: PolicyStatus | None = None


class PolicyActivationResponse(RuntimeContractModel):
    policy: PolicyVersionResponse
    previous_active_policy_version: NonEmpty | None = None
    quality_gate_result_id: QualityGateEvaluationId
    activation_status: Literal["activated"]
    activated_at: AwareDateTime

    @model_validator(mode="after")
    def validate_gate_binding(self) -> "PolicyActivationResponse":
        if self.policy.quality_gate_result_id != self.quality_gate_result_id:
            raise ValueError("activation result must match active policy gate result")
        return self


class ScheduleSettingsResponse(RuntimeContractModel):
    timezone: Literal["Asia/Seoul"]
    daily_time: str
    weekly_time: str
    prespec_enabled: bool
    updated_at: AwareDateTime
    updated_by: Actor

    _validate_times = field_validator("daily_time", "weekly_time")(_validate_clock_time)


class ScheduleSettingsUpdateRequest(RuntimeContractModel):
    daily_time: str | None = None
    weekly_time: str | None = None
    prespec_enabled: bool | None = None
    updated_by: Actor

    _validate_times = field_validator("daily_time", "weekly_time")(_validate_clock_time)

    @model_validator(mode="after")
    def require_setting(self) -> "ScheduleSettingsUpdateRequest":
        if self.daily_time is None and self.weekly_time is None and self.prespec_enabled is None:
            raise ValueError("at least one schedule setting must be supplied")
        return self


ScheduleJobKind = Literal["daily", "weekly"]
ScheduleStatus = Literal["예약", "실행 중", "성공", "부분 성공", "실패", "건너뜀"]
ScheduleTrigger = Literal["schedule", "manual"]


class ScheduleExecutionCreateRequest(RuntimeContractModel):
    job_kind: ScheduleJobKind
    window_from: date
    window_to: date
    recovery_of_execution_id: ScheduleExecutionId | None = None
    requested_by: Actor

    @model_validator(mode="after")
    def validate_window(self) -> "ScheduleExecutionCreateRequest":
        if self.window_from > self.window_to:
            raise ValueError("window_from must not be after window_to")
        span = (self.window_to - self.window_from).days
        if self.job_kind == "daily" and span != 0:
            raise ValueError("daily schedule window must contain one date")
        if self.job_kind == "weekly" and (span != 6 or self.window_from.weekday() != 0):
            raise ValueError("weekly schedule window must be Monday through Sunday")
        return self


class ScheduleExecutionSummary(RuntimeContractModel):
    run_key: NonEmpty
    run_id: NonEmpty | None = None
    window_from: date
    window_to: date
    job_kind: ScheduleJobKind
    status: ScheduleStatus
    execution_id: ScheduleExecutionId
    trigger: ScheduleTrigger
    duplicate_of_execution_id: ScheduleExecutionId | None = None
    recovery_of_execution_id: ScheduleExecutionId | None = None
    skip_reason: NonEmpty | None = None
    failure_reason: NonEmpty | None = None
    requested_by: Actor
    started_at: AwareDateTime | None = None
    finished_at: AwareDateTime | None = None
    candidate_count: int | None = Field(default=None, ge=0)
    result_count: int | None = Field(default=None, ge=0)
    failure_count: int | None = Field(default=None, ge=0)
    partial_artifact: bool | None = None
    policy_version: NonEmpty | None = None
    model_name: NonEmpty | None = None
    model_digest: Digest | None = None
    prompt_version: NonEmpty | None = None
    company_profile_version: CompanyProfileVersion | None = None
    company_profile_digest: Digest | None = None
    generation_config: dict[str, Any] | None = None
    generation_config_digest: Digest | None = None

    @model_validator(mode="after")
    def validate_schedule_summary(self) -> "ScheduleExecutionSummary":
        _validate_run_key_for_kind(self.run_key, self.job_kind)
        expected_run_key = (
            f"{self.window_from:%Y%m%d}-{self.window_to:%Y%m%d}"
            if self.job_kind == "daily"
            else f"weekly:{self.window_from:%Y%m%d}-{self.window_to:%Y%m%d}"
        )
        if self.run_key != expected_run_key:
            raise ValueError("run_key does not match the schedule window")
        if self.duplicate_of_execution_id is not None and self.recovery_of_execution_id is not None:
            raise ValueError("schedule execution cannot be both duplicate and recovery")
        if self.duplicate_of_execution_id is not None and self.status != "건너뜀":
            raise ValueError("duplicate schedule execution must be skipped")
        if self.recovery_of_execution_id is not None and self.trigger != "manual":
            raise ValueError("schedule recovery must be manual")
        if self.trigger == "schedule" and self.requested_by != "system:scheduler":
            raise ValueError("scheduled execution must use system:scheduler actor")
        if (self.company_profile_version is None) != (self.company_profile_digest is None):
            raise ValueError("company profile metadata must be provided as a pair")
        if self.company_profile_version is not None and self.company_profile_digest is not None:
            _validate_profile_binding(self.company_profile_version, self.company_profile_digest)
        _validate_generation_binding(self.generation_config, self.generation_config_digest)
        if self.status == "건너뜀" and self.skip_reason is None:
            raise ValueError("skipped schedule execution requires skip_reason")
        if self.status != "건너뜀" and self.skip_reason is not None:
            raise ValueError("skip_reason is only valid for skipped execution")
        return self


class ScheduleExecutionListResponse(RuntimeContractModel):
    items: list[ScheduleExecutionSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ScheduleExecutionQuery(RuntimeContractModel):
    job_kind: ScheduleJobKind | None = None
    status: ScheduleStatus | None = None
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    @model_validator(mode="after")
    def validate_range(self) -> "ScheduleExecutionQuery":
        if self.from_ is not None and self.to is not None and self.from_ > self.to:
            raise ValueError("from must not be after to")
        return self


class AlwaysOnSwitchUpdateRequest(RuntimeContractModel):
    enabled: bool
    confirmed_by: Actor
    quality_gate_result_id: QualityGateEvaluationId | None = None

    @model_validator(mode="after")
    def require_gate_when_enabled(self) -> "AlwaysOnSwitchUpdateRequest":
        if self.enabled and self.quality_gate_result_id is None:
            raise ValueError("enabled always-on requires quality_gate_result_id")
        return self


class AlwaysOnSwitchResponse(RuntimeContractModel):
    configured_enabled: bool
    effective_enabled: bool
    environment_enabled: bool
    quality_gate_status: QualityGateResultStatus | None = None
    quality_gate_result_id: QualityGateEvaluationId | None = None
    policy_version: NonEmpty | None = None
    model_name: NonEmpty | None = None
    model_digest: Digest | None = None
    prompt_version: NonEmpty | None = None
    company_profile_version: CompanyProfileVersion | None = None
    company_profile_digest: Digest | None = None
    generation_config: dict[str, Any] | None = None
    generation_config_digest: Digest | None = None
    updated_at: AwareDateTime
    updated_by: Actor
    rejection_reason: NonEmpty | None = None

    @model_validator(mode="after")
    def validate_profile_binding(self) -> "AlwaysOnSwitchResponse":
        if (self.company_profile_version is None) != (self.company_profile_digest is None):
            raise ValueError("company profile metadata must be provided as a pair")
        if self.company_profile_version is not None and self.company_profile_digest is not None:
            _validate_profile_binding(self.company_profile_version, self.company_profile_digest)
        _validate_generation_binding(self.generation_config, self.generation_config_digest)
        return self
