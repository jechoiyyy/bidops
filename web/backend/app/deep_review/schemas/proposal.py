"""RL-04 proposal REST DTOs (``bidops.proposal.v1``, spec "REST").

Every model is closed (extra keys forbidden).  The view carries no operational
information: no policy, model, input/result sha or token counts (the export
``pdf_sha256`` is part of the spec view).  Sentences are shown with the latest
edit applied and ``edited`` set; the stored model payload is never changed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from .document_bundles import StrictModel


PROPOSAL_SCHEMA_VERSION = "bidops.proposal.v1"

NonEmpty = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SectionKey = Literal["overview", "track_record", "strategy", "requirements", "operations_sla", "organization"]
DraftStatus = Literal["queued", "running", "completed", "partial", "failed", "superseded"]
DraftStage = Literal["toc", "draft", "reviewed", "ready"]
SectionStatus = Literal["queued", "running", "completed", "failed", "reviewed"]
SentenceKind = Literal["statement", "placeholder", "proposed_figure"]
SourceKind = Literal["requirement_unit", "company_fact", "notice_meta"]
Fit = Literal["met", "gap", "unknown"]


# --- requests ---------------------------------------------------------------------------------


class ProposalRequestCreate(StrictModel):
    request_id: UUID


class SectionRegenerationCreate(StrictModel):
    request_id: UUID


class SectionReviewUpdate(StrictModel):
    request_id: UUID


class SentenceEditCreate(StrictModel):
    text: str = Field(min_length=1, max_length=400)
    request_id: UUID


class ProposalExportCreate(StrictModel):
    request_id: UUID


class DraftStageUpdate(StrictModel):
    stage: Literal["ready"]
    request_id: UUID


# --- responses --------------------------------------------------------------------------------


class ProposalRequestReceipt(StrictModel):
    draft_id: UUID
    status: DraftStatus


class SectionRegenerationReceipt(StrictModel):
    section_id: UUID
    revision: StrictInt = Field(ge=1)


class SentenceEditReceipt(StrictModel):
    edit_id: UUID


class ProposalExportReceipt(StrictModel):
    export_id: UUID
    pdf_sha256: Sha256
    created: StrictBool


class DraftStageView(StrictModel):
    stage: DraftStage


class SourceView(StrictModel):
    kind: SourceKind
    ref: NonEmpty
    quote: NonEmpty


class SentenceView(StrictModel):
    sentence_id: NonEmpty
    text: NonEmpty
    kind: SentenceKind
    sources: list[SourceView]
    placeholder_hint: str | None
    edited: StrictBool


class ParagraphView(StrictModel):
    paragraph_id: NonEmpty
    heading: str | None
    sentences: list[SentenceView]


class RequirementLinkView(StrictModel):
    unit_id: NonEmpty
    paragraph_id: NonEmpty
    fit_status: Fit


class SectionView(StrictModel):
    section_key: SectionKey
    title: NonEmpty
    revision: StrictInt = Field(ge=1)
    status: SectionStatus
    paragraphs: list[ParagraphView]
    requirement_links: list[RequirementLinkView]
    error_code: str | None


class RequirementCoverage(StrictModel):
    total: StrictInt = Field(ge=0)
    linked: StrictInt = Field(ge=0)
    unlinked_unit_ids: list[NonEmpty]


class ProposalCounters(StrictModel):
    sentences_to_confirm: StrictInt = Field(ge=0)
    placeholders: StrictInt = Field(ge=0)
    proposed_figures: StrictInt = Field(ge=0)
    reviewed_sections: StrictInt = Field(ge=0, le=6)


class LatestExportView(StrictModel):
    export_id: UUID
    created_at: datetime
    pdf_sha256: Sha256


class DraftView(StrictModel):
    draft_id: UUID
    status: DraftStatus
    stage: DraftStage
    created_at: datetime
    sections: list[SectionView] = Field(min_length=6, max_length=6)
    requirement_coverage: RequirementCoverage
    counters: ProposalCounters
    latest_export: LatestExportView | None


class ProposalView(StrictModel):
    schema_version: Literal["bidops.proposal.v1"] = PROPOSAL_SCHEMA_VERSION
    draft: DraftView | None


__all__ = [
    "PROPOSAL_SCHEMA_VERSION",
    "DraftStageUpdate",
    "DraftStageView",
    "DraftView",
    "ProposalCounters",
    "ProposalExportCreate",
    "ProposalExportReceipt",
    "ProposalRequestCreate",
    "ProposalRequestReceipt",
    "ProposalView",
    "RequirementCoverage",
    "SectionRegenerationCreate",
    "SectionRegenerationReceipt",
    "SectionReviewUpdate",
    "SectionView",
    "SentenceEditCreate",
    "SentenceEditReceipt",
]
