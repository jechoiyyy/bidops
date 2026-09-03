"""Pydantic contracts for the seven T3 document/bundle endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentRole = Literal["공고", "정정", "제안요청서", "과업지시서", "내역서", "제출서식", "부록", "기타"]
SafetyStatus = Literal["quarantined", "scanning", "safe", "blocked"]
StructureStatus = Literal["pending", "processing", "ready", "failed", "needs_review"]
BundleStatus = Literal["draft", "processing", "needs_review", "ready", "quarantined", "failed", "superseded"]
RiskSeverity = Literal["차단", "중대", "보통", "낮음"]
LocatorType = Literal["none", "page", "paragraph", "table_cell", "bbox"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class EmptyRequest(StrictModel):
    pass


class DocumentVersionView(StrictModel):
    id: UUID
    bundle_id: UUID
    version: int = Field(ge=1)
    role: DocumentRole
    effective_date: date | None
    replaces_document_version_id: UUID | None
    is_current: bool
    safety_status: SafetyStatus
    structure_status: StructureStatus
    original_filename: str


class BundleIssue(StrictModel):
    issue_id: str
    code: str
    severity: RiskSeverity
    blocking: bool
    document_version_id: UUID | None
    message: str
    locator_type: LocatorType
    locator: dict[str, Any] | None


class BundleView(StrictModel):
    id: UUID
    notice_id: int
    revision: int = Field(ge=1)
    version: int = Field(ge=1)
    status: BundleStatus
    documents: list[DocumentVersionView]
    issues: list[BundleIssue]
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime


class BundleListResponse(StrictModel):
    items: list[BundleView]


class UploadResponse(DocumentVersionView):
    pass


class ConfirmedDocument(StrictModel):
    document_version_id: UUID
    version: int = Field(ge=1)


class ConfirmRequest(StrictModel):
    request_id: UUID
    version: int = Field(ge=1)
    confirmed_documents: list[ConfirmedDocument]


class PatchDocumentVersionRequest(StrictModel):
    role: DocumentRole
    effective_date: date | None
    replaces_document_version_id: UUID | None
    is_current: bool
    version: int = Field(ge=1)


class PageMetadata(StrictModel):
    number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    image_content_object_id: UUID | None


class StructureExtractor(StrictModel):
    name: str
    version: str
    upstream_commit: str | None


class StructureBlock(StrictModel):
    block_key: str
    parent_block_key: str | None
    type: str
    page: int = Field(ge=1)
    bbox: list[float] | None
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    attributes: dict[str, Any]


class DocumentStructure(StrictModel):
    schema: Literal["bidops.document-structure.v1"]
    structure_id: UUID
    document_version_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    extractor: StructureExtractor
    pages: list[PageMetadata]
    blocks: list[StructureBlock]
    warnings: list[str]
    created_at: datetime


class DocumentStructurePageView(StrictModel):
    structure_id: UUID
    page: int = Field(ge=1)
    metadata: PageMetadata
    blocks: list[StructureBlock]
