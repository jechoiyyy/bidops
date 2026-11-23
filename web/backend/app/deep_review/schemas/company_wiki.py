"""Read-only company wiki projections."""

from typing import Literal

from pydantic import BaseModel, Field


PageKind = Literal["category", "capability", "portfolio", "rule", "glossary"]


class WikiResponse(BaseModel):
    bundle_sha256: str


class WikiCounts(BaseModel):
    pages_by_kind: dict[PageKind, int]
    portfolio_items: int
    portfolio_pages: int
    ingested_projects: int | None
    work_topics: int | None
    work_units: int | None
    evidence_links: int | None
    units_without_evidence: int | None


class LogEntry(BaseModel):
    date: str | None
    kind: Literal["ingest", "feedback", "init", "other"] = "other"
    project: str | None = None
    project_title: str | None = None
    requirement_count: int | None = None
    unassigned_count: int | None = None
    text: str


class Summary(WikiResponse):
    slug: str
    company_name: str | None
    last_changed: str | None
    labels_available: bool
    counts: WikiCounts
    work_units_available: bool
    log: list[LogEntry]


class Fact(BaseModel):
    path: str
    label: str | None
    display_value: str | None
    value: str | None
    level: str | None


class Section(BaseModel):
    key: str
    label: str | None
    facts: list[Fact]


class Profile(WikiResponse):
    sections: list[Section]


class PortfolioItem(BaseModel):
    id: str
    title: str | None
    client: str | None
    period_start: str | None
    period_end: str | None
    type: str | None
    role: str | None
    has_page: bool
    requirement_count: int | None
    ingested: bool | None
    ingested_at: str | None
    evidence_links: int | None


class Portfolio(WikiResponse):
    items: list[PortfolioItem]


class Requirement(BaseModel):
    req_id: str
    name: str | None


class RequirementDetail(Requirement, WikiResponse):
    project: str
    text: str


class UnitName(BaseModel):
    id: str
    title: str


class ProjectWork(BaseModel):
    topic_id: str
    topic_title: str
    units: list[UnitName]


class ProjectDetail(PortfolioItem, WikiResponse):
    domain: list[str] | str | None
    scope_lines: list[str]
    work_units: list[ProjectWork]
    requirements: list[Requirement]


class Project(BaseModel):
    project: str
    title: str | None
    client: str | None
    period_start: str | None
    period_end: str | None
    year: int | None
    requirements: list[Requirement]


class NoRecord(BaseModel):
    note: str
    as_of: str | None = None
    source: str | None = None


class Unit(UnitName):
    project_count: int
    latest_year: int | None
    covers: str | None = None
    excludes: str | None = Field(default=None, alias="not")
    projects: list[Project]
    no_record: list[NoRecord]


class TopicInfo(BaseModel):
    id: str
    title: str
    scope: str | None = None


class Topic(TopicInfo, WikiResponse):
    units: list[Unit]


class TopicSummary(TopicInfo):
    unit_count: int
    units_without_evidence: int
    project_count: int


class WorkUnits(WikiResponse):
    topics: list[TopicSummary]


class Page(BaseModel):
    kind: PageKind
    slug: str
    title: str
    updated: str | None
    confidence: str | None


class PageEntry(Page):
    chars: int


class Pages(WikiResponse):
    pages: list[PageEntry]


class PageDetail(Page, WikiResponse):
    sources: list[str]
    body: str
