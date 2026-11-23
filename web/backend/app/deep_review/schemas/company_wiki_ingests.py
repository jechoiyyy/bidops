from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_status: Literal["awaiting_review"]


class Rejection(Approval):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class IngestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_id: UUID
    project_id: str
    project_title: str
    status: Literal["queued", "extracting", "classifying", "awaiting_review", "approved",
                    "applying", "applied", "failed", "rejected", "aborted"]
    quality_status: Literal["mock_reference"]
    error_code: str | None
    source_filename: str
    source_size_bytes: int
    source_media_type: str
    requirement_count: int | None
    created_at: datetime
    updated_at: datetime


class Unit(BaseModel):
    id: str
    title: str
    count: int


class Assignment(BaseModel):
    req_id: str
    name: str
    unit_titles: list[str]


class IngestDetail(IngestSummary):
    unlisted_id_count: int | None
    units: list[Unit]
    assignments: list[Assignment]
    new_units: list[dict[str, str]]
    unassigned_count: int | None
    classification_attempts: int
    apply_allowed: bool
    wiki_sha256_before: str | None
    wiki_sha256_after: str | None
    backup_name: str | None
    created_by_name: str
    decided_by_name: str | None
    decision_reason: str | None
    decided_at: datetime | None
    applied_at: datetime | None


class IngestList(BaseModel):
    items: list[IngestSummary]
    total: int
