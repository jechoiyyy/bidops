"""ingest 단계의 데이터 모델(NoticeBundle, RawDoc). 필드 순서가 JSON 키 순서가 된다."""

from typing import Literal

from pydantic import BaseModel, Field

# 모듈 수준 별칭. Role의 "skipped"와 BundleStatus의 "degraded"는 M0-03(hwp)에서 추가했다.
Format = Literal["hwpx", "hwp", "pdf"]
Role = Literal["primary", "reference", "pending_hwp", "superseded", "skipped"]
BundleStatus = Literal["ok", "degraded", "failed"]
BlockKind = Literal["paragraph", "table"]
Extractor = Literal["hwpx-lxml", "pypdf", "rhwp", "rhwp-hwpx"]


class SourceFile(BaseModel):
    path: str  # data_dir 기준 상대 경로, POSIX 구분자
    format: Format
    role: Role
    size_bytes: int
    sha256: str


class NoticeMeta(BaseModel):
    """매니페스트가 주는 공고 메타. facts 입력(rfp_input_payload)에는 들어가지 않는다."""

    kind: Literal["prespec", "bid"] | None = None
    notice_no: str | None = None
    opinion_deadline: str | None = None
    assigned_budget_krw: int | None = None


class NoticeBundle(BaseModel):
    slug: str
    title: str
    manifest_matched: bool
    files: list[SourceFile]
    primary_format: Format
    status: BundleStatus
    warnings: list[str] = Field(default_factory=list)
    created_at: str  # ISO 8601
    notice: NoticeMeta | None = None  # 매니페스트 선택 키가 하나라도 있을 때만


class Block(BaseModel):
    idx: int
    kind: BlockKind
    text: str
    table_id: str | None = None
    page: int | None = None  # pdf만 1부터


class RawTable(BaseModel):
    id: str  # "T" + 3자리
    block_idx: int
    rows: list[list[str]]


class PageBound(BaseModel):
    file: str
    first_page: int
    last_page: int


class RawMeta(BaseModel):
    chars: int
    digits: int
    paragraphs: int
    tables: int
    pages: int | None = None
    extractor: Extractor
    extractor_version: str
    warnings: list[str] = Field(default_factory=list)


class RawDoc(BaseModel):
    slug: str
    format: Format
    source_paths: list[str]
    blocks: list[Block]
    tables: list[RawTable]
    page_texts: list[str] | None = None
    page_bounds: list[PageBound] | None = None
    meta: RawMeta


# --- 정규화 결과(M0-04): RfpDocument ---
SectionKind = Literal[
    "overview",
    "requirements",
    "eligibility",
    "evaluation",
    "proposal_guide",
    "contract",
    "attachments",
    "other",
]
TableKind = Literal[
    "requirement_detail",
    "requirement_list",
    "requirement_summary",
    "evaluation_scores",
    "staffing",
    "commercial_sw",
    "schedule",
    "other",
]
RequirementSource = Literal["table", "text"]


class Section(BaseModel):
    id: str  # "S" + 3자리, 전문은 "S000"
    heading: str  # 전문은 "전문"
    level: Literal[0, 1, 2, 3, 4]  # 전문만 0
    kind: SectionKind
    parent_id: str | None = None
    block_start: int
    block_end: int  # 포함
    text: str
    table_ids: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None


class Requirement(BaseModel):
    id: str = Field(pattern=r"^[A-Z]{3}-\d{3}$")
    category: str  # ID 접두 3자
    name: str
    definition: str | None = None
    details: str
    mandatory: bool | None = None
    section_id: str | None = None
    table_id: str | None = None
    source: RequirementSource


class Table(BaseModel):
    id: str  # "T" + 3자리, RawTable.id 승계
    section_id: str
    kind: TableKind
    rows: list[list[str]]
    markdown: str


class SourceQuality(BaseModel):
    primary_format: Format
    primary_chars: int
    primary_digits: int
    reference_pdf_chars: int | None = None
    reference_pdf_digits: int | None = None
    has_tables: bool
    requirements_found: int
    requirements_expected: int | None = None
    sections_mapped_to_pages: int
    warnings: list[str] = Field(default_factory=list)


class RfpDocument(BaseModel):
    slug: str
    title: str
    source_files: list[str]
    primary_format: Format
    sections: list[Section]
    requirements: list[Requirement]
    tables: list[Table]
    full_text: str
    source_quality: SourceQuality
    schema_version: int = 1
