"""Pydantic response models for the read-only BidOps Admin API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    count: int


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
    collected_count: int
    candidate_count: int
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
