"""Page-based overview contract; deliberately contains no recommendation."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from ...core.schema_base import AwareDateTime, Digest, RuntimeContractModel

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
