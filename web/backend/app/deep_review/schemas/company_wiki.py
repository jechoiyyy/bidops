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
    date: str
    text: str


class Summary(WikiResponse):
    slug: str
    company_name: str | None
    counts: WikiCounts
    work_units_available: bool
    log: list[LogEntry]


class Fact(BaseModel):
    path: str
    section: str
    value: str | None
    level: str | None


class Profile(WikiResponse):
    facts: list[Fact]


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


class Project(BaseModel):
    project: str
    req_ids: list[str]


class NoRecord(BaseModel):
    note: str
    as_of: str | None = None
    source: str | None = None


class Unit(BaseModel):
    id: str
    title: str
    covers: str | None = None
    excludes: str | None = Field(default=None, alias="not")
    projects: list[Project]
    no_record: list[NoRecord]


class Topic(BaseModel):
    id: str
    title: str
    scope: str | None = None
    units: list[Unit]


class WorkUnits(WikiResponse):
    topics: list[Topic]


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
