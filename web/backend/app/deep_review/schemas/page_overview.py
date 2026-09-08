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


class PageOverviewResponse(RuntimeContractModel):
    schema_version: Literal["bidops.prespec-overview-pages.v1"] = "bidops.prespec-overview-pages.v1"
    notice_id: int
    reviews: list[PageOverviewView]
