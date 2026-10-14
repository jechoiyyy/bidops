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


# --- 결정적 segment manifest 조회 (원문 text 없음) --------------------------

TaxonomyLabel = Literal[
    "business_eligibility_evaluation",
    "technical_functional",
    "quality_security_constraints",
    "partnership_governance",
    "operations_maintenance",
]
SegmentStatus = Literal["classified", "needs_human_review"]
SegmentLocatorKind = Literal["paragraph", "table_cell", "block"]
# 대응표(``bidops.para-page-map.v1``)는 native snapshot에만 있다. 없으면
# ``unavailable``·``null``이며 미확인을 페이지로 승격시키지 않는다.
SegmentMappingStatus = Literal["mapped", "partial", "inherited", "unavailable"]


class SegmentLocator(StrictModel):
    kind: SegmentLocatorKind
    block_key: str = Field(min_length=1)
    page: int = Field(ge=1)
    ordinal: int = Field(ge=0)
    table_key: str | None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)


class SegmentPageRange(StrictModel):
    """물리 PDF 순번(1 기준)의 닫힌 구간. 대응표가 있을 때만 채운다."""

    first: int = Field(ge=1)
    last: int = Field(ge=1)


class DocumentSegmentView(StrictModel):
    segment_id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    taxonomy_labels: list[TaxonomyLabel]
    start_locator: SegmentLocator
    end_locator: SegmentLocator
    requirement_ids: list[str]
    source_block_keys: list[str]
    classification_source: Literal["deterministic"]
    # 결정적 규칙에는 확률이 없다. 값을 만들어 내지 않고 항상 null로 둔다.
    confidence: None = None
    status: SegmentStatus
    # 조회 시점에 대응표에서 계산한다. 저장하지 않으며 원문 텍스트도 아니다.
    page_range: SegmentPageRange | None
    mapping_status: SegmentMappingStatus


class RequirementInventoryAmbiguity(StrictModel):
    reason: Literal["prefix_unconfirmed", "prefix_collision"]
    raw_id: str | None
    raw_prefix: str | None
    normalized_prefix: str = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    locator: SegmentLocator | None


class RequirementInventorySummary(StrictModel):
    expected_ids: list[str]
    duplicate_ids: list[str]
    ambiguous_items: list[RequirementInventoryAmbiguity]
    prefixes: list[str]
    item_count: int = Field(ge=0)
    card_item_count: int = Field(ge=0)
    label_value_table_count: int = Field(ge=0)


class SegmentSpan(StrictModel):
    start_ordinal: int = Field(ge=0)
    end_ordinal: int = Field(ge=0)


class SegmentTocSummary(StrictModel):
    entry_count: int = Field(ge=0)
    matched_heading_count: int = Field(ge=0)
    unmatched_entry_count: int = Field(ge=0)


class SegmentCoverage(StrictModel):
    block_count: int = Field(ge=0)
    covered_block_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    overlap_count: int = Field(ge=0)
    gaps: list[SegmentSpan]
    overlaps: list[SegmentSpan]
    needs_human_review_count: int = Field(ge=0)
    toc: SegmentTocSummary


class SegmentExtractorBinding(StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    rules_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema: Literal["bidops.document-segments.v1"]


class DocumentSegmentsView(StrictModel):
    schema: Literal["bidops.document-segments.v1"]
    structure_id: UUID
    document_version_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_version: str = Field(min_length=1)
    extractor_binding: SegmentExtractorBinding
    extractor_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segments: list[DocumentSegmentView]
    inventory_summary: RequirementInventorySummary
    coverage: SegmentCoverage
    warnings: list[str]
    created_at: datetime
