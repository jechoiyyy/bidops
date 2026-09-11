"""Page-based overview contract; deliberately contains no recommendation."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ...core.schema_base import AwareDateTime, Digest, RuntimeContractModel
from .prespec_overview_claims import (
    BoundedText, Identifier, OverviewAnalysis, StrictClaimModel, VerifiedEvidence,
)

Text = Annotated[str, Field(min_length=1)]
PageNumber = Annotated[int, Field(strict=True, ge=1)]


class PageFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: Text
    evidence_pages: Annotated[list[PageNumber], Field(min_length=1)]


class PageOverviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["bidops.prespec-overview-page-review.v3"]
    business_overview: Annotated[list[PageFact], Field(min_length=1)]
    main_tasks: Annotated[list[PageFact], Field(min_length=1)]
    budget_and_period: list[PageFact]
    important_conditions: list[PageFact]
    reviewer_analysis: Annotated[list[Text], Field(min_length=1)]
    unknowns: list[Text]
    input_limitations: Annotated[list[Text], Field(min_length=1)]


class PageOverviewView(RuntimeContractModel):
    id: UUID
    notice_id: int
    document_version_id: UUID
    source_sha256: Digest
    pdf_sha256: Digest
    pdf_page_count: int
    reviewed_pages: list[PageNumber]
    payload: PageOverviewPayload
    payload_sha256: Digest
    validation_status: Literal["passed", "failed"]
    validation_errors: list[str]
    evidence_check_status: Literal["passed", "failed"]
    evidence_check_errors: list[str]
    quality_status: Literal["unmeasured_reference", "mock_reference"]
    model_name: str
    prompt_version: str
    created_at: AwareDateTime


PageOverviewCurrentStatus = Literal[
    "queued", "running", "completed", "failed", "needs_human_review", "stale", "cancelled"
]


class PageOverviewCurrent(RuntimeContractModel):
    """Server-owned v4 pointer; ``reviews`` remains the historical list."""

    attempt_id: UUID | None
    status: PageOverviewCurrentStatus
    result_id: UUID | None
    reason_code: str | None
    prompt_version: str | None
    created_at: AwareDateTime


class PageOverviewRangeCandidate(RuntimeContractModel):
    """절 후보 하나. 제목은 산출물 ⑦이 정규화·길이 제한을 끝낸 값이다."""

    index: Annotated[int, Field(ge=0)]
    title: str
    page: PageNumber
    char_count: Annotated[int, Field(ge=0)]


class PageOverviewRangeAssist(RuntimeContractModel):
    """명시 CLI 액션이 남긴 모델 제안. 제안은 target을 바꾸지 않는다."""

    start_index: Annotated[int, Field(ge=0)]
    end_index: Annotated[int, Field(ge=0)]
    model_name: str
    quality_status: Literal["unmeasured_reference", "mock_reference"]
    created_at: AwareDateTime


class PageOverviewRangeConfirmation(RuntimeContractModel):
    """사람이 확정한 범위. 쪽으로 직접 확정했으면 두 index가 `null`이다."""

    target_id: UUID
    confirmed_from_target_id: UUID
    start_index: Annotated[int, Field(ge=0)] | None
    end_index: Annotated[int, Field(ge=0)] | None
    first_page: PageNumber
    last_page: PageNumber
    page_numbers: Annotated[list[PageNumber], Field(min_length=1)]
    actor: str
    note: str | None
    created_at: AwareDateTime


class PageOverviewRangeReview(RuntimeContractModel):
    """개요 입력 범위의 사람 확인 상태 (R7).

    결정적 선택기가 범위를 못 정한 최신 target이면 확정 대기
    (`confirmation=null`), 사람이 확정한 target이면 `ready`이고 `confirmation`이
    채워진다. 그 밖에는 응답에서 이 필드 자체가 `null`이다.
    """

    target_id: UUID
    snapshot_id: UUID
    selection_status: Literal["needs_human_review", "ready"]
    reason_code: str | None
    pdf_page_count: PageNumber
    created_at: AwareDateTime
    candidates_mode: Literal["clause", "page"] | None
    candidates: list[PageOverviewRangeCandidate]
    assisted: PageOverviewRangeAssist | None
    confirmation: PageOverviewRangeConfirmation | None


class PageOverviewRangeConfirmationRequest(RuntimeContractModel):
    """(start_index,end_index) 쌍이나 (first_page,last_page) 쌍 중 정확히 하나."""

    target_id: UUID
    start_index: int | None = None
    end_index: int | None = None
    first_page: int | None = None
    last_page: int | None = None
    note: Annotated[str, Field(max_length=500)] | None = None


class PageOverviewRangeReviewV2(PageOverviewRangeReview):
    """Prepared input and advisory candidates, independent of model results."""

    schema_version: Literal["bidops.prespec-overview-range-view.v2"] = "bidops.prespec-overview-range-view.v2"
    candidates_mode: Literal["clause", "page", "outline"] | None
    candidate_status: Literal["complete", "partial", "unavailable"]
    candidate_count_total: Annotated[int, Field(ge=0)] | None
    candidate_count_returned: Annotated[int, Field(ge=0)]
    warning_codes: list[str]
    selected_pages: list[PageNumber]
    can_confirm: bool


class PageOverviewRangeConfirmationResponse(RuntimeContractModel):
    target_id: UUID
    selection_status: Literal["ready"]
    first_page: PageNumber
    last_page: PageNumber
    page_numbers: Annotated[list[PageNumber], Field(min_length=1)]
    #: 범위 확정은 개요 검토 실행을 열지 않는다. 서버는 항상 `false`를 보낸다.
    attempt_enqueued: Literal[False] = False


class PageOverviewResponse(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-overview-pages.v1"] = "bidops.prespec-overview-pages.v1"
    notice_id: int
    reviews: list[PageOverviewView]
    current: PageOverviewCurrent | None = None
    #: 범위 사람 확인 대상이 없으면 `null`이다(기존 소비자에는 추가 필드).
    range_review: PageOverviewRangeReview | None = None


class VerifiedPageFact(StrictClaimModel):
    claim_id: Identifier
    text: BoundedText
    evidence: Annotated[list[VerifiedEvidence], Field(min_length=1)]


class PageOverviewPayloadV4(StrictClaimModel):
    schema_version: Literal["bidops.prespec-overview-page-review.v4"]
    business_overview: Annotated[list[VerifiedPageFact], Field(min_length=1)]
    main_tasks: Annotated[list[VerifiedPageFact], Field(min_length=1)]
    budget_and_period: list[VerifiedPageFact]
    important_conditions: list[VerifiedPageFact]
    reviewer_analysis: list[OverviewAnalysis]
    unknowns: list[Text]
    input_limitations: Annotated[list[Text], Field(min_length=1)]
    verification_id: UUID
    verification_sha256: Digest

    @model_validator(mode="after")
    def require_unique_claims(self):
        facts = self.business_overview + self.main_tasks + self.budget_and_period + self.important_conditions
        ids = [fact.claim_id for fact in facts]
        analysis_ids = [row.id for row in self.reviewer_analysis]
        if len(set(ids + analysis_ids)) != len(ids + analysis_ids):
            raise ValueError("duplicate_id")
        if any(not a.supporting_claim_ids or set(a.supporting_claim_ids) - set(ids) for a in self.reviewer_analysis):
            raise ValueError("analysis_reference_missing")
        return self


PageOverviewResultPayload = Annotated[PageOverviewPayload | PageOverviewPayloadV4, Field(discriminator="schema_version")]


def parse_page_overview_payload(value: object) -> PageOverviewPayload | PageOverviewPayloadV4:
    """Read a historical v3 or a verified v4 without promoting either version."""
    if isinstance(value, (PageOverviewPayload, PageOverviewPayloadV4)):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise ValueError("overview_schema_invalid")
    version = value.get("schema_version")
    if version == "bidops.prespec-overview-page-review.v3":
        return PageOverviewPayload.model_validate(value)
    if version == "bidops.prespec-overview-page-review.v4":
        # JSON validation permits the UUID wire encoding while retaining strict
        # integers, strings and unknown-field rejection in nested evidence.
        import json
        return PageOverviewPayloadV4.model_validate_json(json.dumps(value, ensure_ascii=False))
    raise ValueError("overview_schema_unsupported")


class PageOverviewViewV2(PageOverviewView):
    payload: PageOverviewResultPayload


class PageOverviewVerificationClaim(RuntimeContractModel):
    claim_id: Identifier
    text: BoundedText
    deterministic_status: Literal["passed", "failed"]
    semantic_status: Literal["supported", "contradicted", "insufficient", "not_run"]
    reason_codes: list[str]
    verified_evidence: list[VerifiedEvidence]


class PageOverviewVerification(RuntimeContractModel):
    verification_id: UUID
    status: Literal["passed", "needs_human_review"]
    reason_codes: list[str]
    claims: list[PageOverviewVerificationClaim]


class PageOverviewCurrentV2(PageOverviewCurrent):
    verification_status: Literal["passed", "needs_human_review"] | None = None


class PageOverviewResponseV2(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-overview-pages.v2"] = "bidops.prespec-overview-pages.v2"
    notice_id: int
    current: PageOverviewCurrentV2 | None
    reviews: list[PageOverviewViewV2]
    range_review: PageOverviewRangeReviewV2 | None
    verification: PageOverviewVerification | None
