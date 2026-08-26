"""Pydantic response models for the read-only BidOps Admin API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageFilters(APIModel):
    run_id: str
    grade: str | None = None
    readiness: str | None = None
    focus: str | None = None
    sample_role: str | None = None
    attachment: Literal["any", "none", "manual"] = "any"
    q: str | None = None
    sort: Literal["deadline", "grade", "published"] = "deadline"
    limit: int
    offset: int


class AttachmentResponse(APIModel):
    id: int
    name: str | None = None
    url: str | None = None
    origin: str | None = None
    file_ext: str | None = None
    size_bytes: int | None = None
    stored_path: str | None = None
    extract_status: str | None = None
    created_at: datetime | None = None


class AgencyPortalResponse(APIModel):
    id: int
    agency_pattern: str
    system_name: str
    search_url_template: str
    enabled: bool
    note: str | None = None


class AgencyPortalCreateRequest(APIModel):
    agency_pattern: str
    system_name: str
    search_url_template: str
    enabled: bool = True
    note: str | None = None


class AgencyPortalUpdateRequest(APIModel):
    agency_pattern: str | None = None
    system_name: str | None = None
    search_url_template: str | None = None
    enabled: bool | None = None
    note: str | None = None


class AttachmentProcedureResponse(APIModel):
    notice_pk: int
    agency: str | None = None
    bid_no: str | None = None
    title: str | None = None
    status: str
    matched_portal: AgencyPortalResponse | None = None
    search_url: str | None = None
    portal_message: str
    steps: list[str] = Field(default_factory=list)
    attachments: list[AttachmentResponse] = Field(default_factory=list)


class EvidenceResponse(APIModel):
    id: int
    source: str | None = None
    status: str | None = None
    fact: str | None = None


class PerspectiveResponse(APIModel):
    id: int
    position: int | None = None
    name: str | None = None
    assessment: str | None = None
    reason: str | None = None
    evidence: list[EvidenceResponse] = Field(default_factory=list)


class CounterargumentResponse(APIModel):
    id: int
    position: int | None = None
    text: str | None = None


class VerificationItemResponse(APIModel):
    id: int
    item: str | None = None
    why: str | None = None
    blocking: bool
    status: str | None = None


class MatchedPerformanceResponse(APIModel):
    id: int
    name: str | None = None
    match_reason: str | None = None
    mismatch_or_limit: str | None = None
    source: str | None = None
    status: str | None = None


class ReviewAnswerResponse(APIModel):
    id: int
    item: str | None = None
    answer: str | None = None


class ReviewAnswerInput(APIModel):
    item: str | None = None
    answer: str | None = None


class ReviewUpsertRequest(APIModel):
    run_id: str
    disposition: str | None = None
    system_judgment_review: str | None = None
    corrected_grade: str | None = None
    corrected_readiness: str | None = None
    weakest_perspective: str | None = None
    reason: str | None = None
    reviewer: str | None = None
    verification_answers: list[ReviewAnswerInput] = Field(default_factory=list)


class ReviewResponse(APIModel):
    id: int
    run_id: str
    notice_pk: int
    disposition: str | None = None
    system_judgment_review: str | None = None
    corrected_grade: str | None = None
    corrected_readiness: str | None = None
    weakest_perspective: str | None = None
    reason: str | None = None
    reviewer: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    answers: list[ReviewAnswerResponse] = Field(default_factory=list)


class JudgmentResponse(APIModel):
    id: int
    schema_version: str | None = None
    grade: str | None = None
    readiness: str | None = None
    primary_focus: str | None = None
    exclusion_category: str | None = None
    summary: str | None = None
    next_action: str | None = None
    perspectives: list[PerspectiveResponse] = Field(default_factory=list)
    counterarguments: list[CounterargumentResponse] = Field(default_factory=list)
    verification_items: list[VerificationItemResponse] = Field(default_factory=list)
    matched_performances: list[MatchedPerformanceResponse] = Field(default_factory=list)


class NoticeListItem(APIModel):
    id: int
    notice_key: str
    run_id: str
    title: str | None = None
    agency: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    estimated_price: float | None = None
    sample_role: str | None = None
    sample_stratum: str | None = None
    collection_bucket: str | None = None
    grade: str | None = None
    readiness: str | None = None
    focus: str | None = None
    attachment_count: int = 0
    attachment_status: Literal["none", "g2b", "manual"] = "none"


class AttachmentQueueItem(NoticeListItem):
    bid_no: str | None = None
    matched_portal: AgencyPortalResponse | None = None
    search_url: str | None = None
    portal_message: str


class AttachmentQueueResponse(APIModel):
    run_id: str
    total: int
    items: list[AttachmentQueueItem] = Field(default_factory=list)


class NoticeDetailResponse(NoticeListItem):
    bid_no: str | None = None
    bid_ord: str | None = None
    source_type: str | None = None
    budget: float | None = None
    method: str | None = None
    url: str | None = None
    timezone: str
    procurement_class: Any = None
    region_limit: Any = None
    lifecycle: Any = None
    qualification_flags: Any = None
    focus_matches: list[Any] = Field(default_factory=list)
    performance_matches: list[Any] = Field(default_factory=list)
    performance_top_score: float | None = None
    candidate_sources: list[Any] = Field(default_factory=list)
    judgment: JudgmentResponse | None = None
    attachments: list[AttachmentResponse] = Field(default_factory=list)
    reviews: list[ReviewResponse] = Field(default_factory=list)


class NoticeListResponse(APIModel):
    items: list[NoticeListItem]
    total: int
    filters: PageFilters


class HistoryItemResponse(APIModel):
    notice_pk: int
    run_id: str
    window_from: date | None = None
    window_to: date | None = None
    timezone: str
    generated_at: datetime
    grade: str | None = None
    readiness: str | None = None
    focus: str | None = None
    summary: str | None = None
    corrected_grade: str | None = None
    corrected_readiness: str | None = None
    review_reason: str | None = None


class NoticeHistoryResponse(APIModel):
    notice_key: str
    items: list[HistoryItemResponse]


class RelatedNoticeResponse(APIModel):
    relation: Literal["ordinal", "unified", "pre_spec"]
    notice_pk: int
    notice_key: str
    title: str | None = None
    grade: str | None = None
    published_at: datetime | None = None
    change_reason: str | None = None


class RelatedNoticeListResponse(APIModel):
    notice_pk: int
    items: list[RelatedNoticeResponse] = Field(default_factory=list)


class WarningResponse(APIModel):
    id: int
    run_id: str
    level: str
    code: str
    message: str
    context: Any = None


class WarningListResponse(APIModel):
    run_id: str
    items: list[WarningResponse]
    total: int
    level: str | None = None
    code: str | None = None


class RunCounts(APIModel):
    notices: int = 0
    judgments: int = 0
    reviews: int = 0
    collection: dict[str, Any] = Field(default_factory=dict)


class RunSummary(APIModel):
    run_id: str
    window_from: date | None = None
    window_to: date | None = None
    timezone: str
    generated_at: datetime
    screening_basis: str | None = None
    status: str
    superseded_by: str | None = None
    counts: RunCounts


class RunListResponse(APIModel):
    items: list[RunSummary]
    total: int


class ArtifactValidationResponse(APIModel):
    name: str
    present: bool
    schema_version: str | None = None
    expected_schema_version: str | None = None
    valid: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class PipelineStageResponse(APIModel):
    name: str
    status: str
    artifact: str | None = None
    script: str | None = None
    execution_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    execution_allowed: bool = True
    message: str | None = None


class CollectionScopeResponse(APIModel):
    window_from: date | None = None
    window_to: date | None = None
    timezone: str
    business_area: str | None = None
    pre_spec_available: bool | None = None
    pre_spec_reason: str | None = None
    focus_axes: list[str] = Field(default_factory=list)
    performance_reference_count: int | None = None


class RunDetailResponse(RunSummary):
    collection_scope: CollectionScopeResponse
    pipeline: list[PipelineStageResponse] = Field(default_factory=list)
    artifacts: list[ArtifactValidationResponse] = Field(default_factory=list)
    warning_counts: dict[str, int] = Field(default_factory=dict)


class FunnelItem(APIModel):
    key: str
    label: str
    # 산출물이 값을 주지 않은 단계는 0이 아니라 null 로 남긴다.
    count: int | None = None


class DistributionItem(APIModel):
    key: str
    label: str
    count: int


class VerificationRequest(APIModel):
    item: str
    count: int
    notice_pks: list[int] = Field(default_factory=list)
    profile_sections: list[str] = Field(default_factory=list)


class DeadlineNotice(NoticeListItem):
    blocking_verification_items: list[str] = Field(default_factory=list)


class RunStatsResponse(APIModel):
    run_id: str
    timezone: str
    # 마감 임박 목록은 이 시각을 기준으로 7일 구간을 잡는다. 화면이 남은 일수를
    # 같은 기준으로 계산하도록 응답에 함께 담는다.
    generated_at: datetime
    collected_count: int | None = None
    candidate_count: int | None = None
    sample_count: int
    priority_review_count: int
    audit_missed_count: int
    funnel: list[FunnelItem]
    grade_distribution: list[DistributionItem]
    readiness_distribution: list[DistributionItem]
    focus_distribution: list[DistributionItem]
    verification_requests: list[VerificationRequest]
    imminent_deadlines: list[DeadlineNotice]


class IngestRequest(APIModel):
    run_id: str | None = None


class IngestResponse(APIModel):
    run_id: str
    notices: int
    judgments: int
    reviews: int
    warnings: list[WarningResponse] = Field(default_factory=list)
    warning_counts: dict[str, int] = Field(default_factory=dict)


class PipelineRunRequest(APIModel):
    from_raw: bool = False


class PipelineLogLineResponse(APIModel):
    timestamp: datetime
    stream: str
    level: str
    message: str


class PipelineExecutionResponse(APIModel):
    execution_id: str
    source_run_id: str
    result_run_id: str | None = None
    stage: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None
    log_count: int = 0


class PipelineLogResponse(APIModel):
    run_id: str
    executions: list[PipelineExecutionResponse] = Field(default_factory=list)
    items: list[PipelineLogLineResponse] = Field(default_factory=list)
    total: int = 0


class MetricBasis(APIModel):
    numerator: int | float
    denominator: int | float
    detail: dict[str, Any] = Field(default_factory=dict)


class ValidationMetric(APIModel):
    key: str
    label: str
    value: float | None = None
    percentage: float | None = None
    threshold: Any = None
    meets_threshold: bool | None = None
    status: Literal["pass", "fail", "measured", "not_measurable"]
    basis: MetricBasis
    reason: str | None = None


class ValidationMetricsResponse(APIModel):
    run_id: str
    metrics: list[ValidationMetric]


ProfileStatus = Literal["confirmed", "inferred", "unknown"]
ProfileSectionState = Literal["confirmed", "inferred", "unknown", "mixed", "unrecorded"]


class ProfileRawBlockResponse(APIModel):
    line_start: int
    raw: str
    error: str


class ProfileItemResponse(APIModel):
    key: str
    label: str
    section_id: str
    section_number: str | None = None
    status: ProfileStatus
    value: Any = None
    source_line: int | None = None


class ProfileSectionResponse(APIModel):
    id: str
    number: str | None = None
    title: str
    heading: str
    level: int
    state: ProfileSectionState
    status_counts: dict[str, int] = Field(default_factory=dict)
    items: list[ProfileItemResponse] = Field(default_factory=list)
    raw_blocks: list[ProfileRawBlockResponse] = Field(default_factory=list)
    raw: str | None = None
    children: list["ProfileSectionResponse"] = Field(default_factory=list)


class ProfileSectionsResponse(APIModel):
    source: str
    sections: list[ProfileSectionResponse] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    parse_errors: list[str] = Field(default_factory=list)


class ProfileUnknownResponse(APIModel):
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
    source: str
    items: list[ProfileUnknownResponse] = Field(default_factory=list)
    total: int
    reference_fields: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Screening runtime REST contracts
#
# The legacy models above intentionally preserve the permissive behaviour of
# the original read-only API.  Runtime endpoints are a versioned, write-heavy
# contract, so they use a strict base model below.  Execution, gate, and
# profile presenters deliberately omit artifact paths, prompt/profile bodies,
# and model responses; only public metadata and API result links are exposed.


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value


def _validate_clock_time(value: str) -> str:
    if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit():
        raise ValueError("time must use HH:MM")
    hour = int(value[:2])
    minute = int(value[3:])
    if hour > 23 or minute > 59:
        raise ValueError("time must use HH:MM")
    return value


def _validate_relative_source_ref(value: str) -> str:
    if (
        value.startswith(("/", "\\"))
        or value == ".."
        or value.startswith("../")
        or "/../" in value
        or value.endswith("/..")
    ):
        raise ValueError("working-tree source_ref must be a relative path")
    if "\\" in value:
        raise ValueError("working-tree source_ref must use a relative POSIX path")
    return value


def _validate_run_key_for_kind(value: str, kind: str) -> str:
    try:
        if kind == "daily":
            start_text, end_text = value.split("-", 1)
            start = date.fromisoformat(f"{start_text[:4]}-{start_text[4:6]}-{start_text[6:8]}")
            end = date.fromisoformat(f"{end_text[:4]}-{end_text[4:6]}-{end_text[6:8]}")
            if len(start_text) != 8 or len(end_text) != 8 or start != end or value != f"{start_text}-{end_text}":
                raise ValueError
        else:
            prefix, dates = value.split(":", 1)
            start_text, end_text = dates.split("-", 1)
            start = date.fromisoformat(f"{start_text[:4]}-{start_text[4:6]}-{start_text[6:8]}")
            end = date.fromisoformat(f"{end_text[:4]}-{end_text[4:6]}-{end_text[6:8]}")
            if (
                prefix != "weekly"
                or len(start_text) != 8
                or len(end_text) != 8
                or start.weekday() != 0
                or (end - start).days != 6
            ):
                raise ValueError
    except (ValueError, IndexError):
        raise ValueError("run_key does not match its job_kind") from None
    return value


def _validate_profile_binding(version: str, digest: str) -> None:
    if version.split(":", 1)[-1] != digest:
        raise ValueError("company profile version and digest must match")


AwareDateTime = Annotated[datetime, AfterValidator(_require_aware)]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CompanyProfileVersion = Annotated[str, StringConstraints(pattern=r"^company-profile\.sha256:[0-9a-f]{64}$")]
ScreeningExecutionId = Annotated[str, StringConstraints(pattern=r"^scr-[0-9a-f]{32}$")]
QualityGateId = Annotated[str, StringConstraints(pattern=r"^gate-[0-9a-f]{32}$")]
QualityGateEvaluationId = Annotated[str, StringConstraints(pattern=r"^gateeval-[0-9a-f]{32}$")]
ScheduleExecutionId = Annotated[str, StringConstraints(pattern=r"^sched-[0-9a-f]{32}$")]


class RuntimeContractModel(BaseModel):
    """Strict, metadata-only base for the new named REST contracts."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


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
    generation_config_digest: Digest | None = None
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
    source_ref: NonEmpty
    created_at: AwareDateTime

    @model_validator(mode="after")
    def validate_source_ref(self) -> "CompanyProfileSnapshotResponse":
        _validate_profile_binding(self.version, self.digest)
        if self.source_kind == "git_blob":
            if len(self.source_ref) != 40 or any(c not in "0123456789abcdef" for c in self.source_ref):
                raise ValueError("git_blob source_ref must be a 40-character lowercase commit")
        else:
            _validate_relative_source_ref(self.source_ref)
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
    generation_config_digest: Digest | None = None
    created_at: AwareDateTime


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
    generation_config_digest: Digest | None = None
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
        return self
