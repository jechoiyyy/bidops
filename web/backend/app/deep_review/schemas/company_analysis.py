"""DEMO company analysis DTOs (demo contract §6, §10).

``FrozenProvenance`` is the immutable lineage snapshot written when an input is
frozen (company-fit enqueue, company deep-review preview).  The company deep
review views extend the existing Luna DTOs with explicitly enumerated fields
only; every identity/hash present on both the view and its provenance must be
equal, otherwise validation fails and the service answers ``processing_failed``
instead of a repaired response (§10).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from ...lifecycle.schemas.companies import CompanyDTO, CompanyTrackingDTO
from .company_fit import CompanyFitPayloadV2, CompanyFitView
from .deep_reviews import AttemptView, DeepReviewPreviewView, DeepReviewView
from .card_analysis import CardAnalysisInput
from .document_bundles import StrictModel
from .reports import ReportView

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FrozenDocument(StrictModel):
    document_version_id: UUID
    source_sha256: Sha256


class FrozenProvenance(StrictModel):
    input_sha256: Sha256
    purpose: Literal["company_fit", "deep_review"]
    company_id: UUID
    profile_version_id: UUID
    profile_sha256: Sha256
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)
    ontology_sha256: Sha256
    documents: list[FrozenDocument] = Field(min_length=1)
    #: RL-03 "개요 의존 제거" (D1): a ``card-v1`` deep-review input freezes both
    #: as null.  Both null or both set; a company-fit provenance always has both.
    overview_run_id: UUID | None
    overview_sha256: Sha256 | None
    bundle_id: UUID | None
    policy_version_id: UUID
    policy_sha256: Sha256
    model_name: str = Field(min_length=1)
    model_revision: str | None
    generation_config_sha256: Sha256

    @model_validator(mode="after")
    def _documents_sorted(self) -> "FrozenProvenance":
        ids = [str(row.document_version_id) for row in self.documents]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("provenance_documents_unsorted")
        if (self.overview_run_id is None) != (self.overview_sha256 is None):
            raise ValueError("provenance_overview_partial")
        if self.purpose == "company_fit" and self.overview_run_id is None:
            raise ValueError("provenance_overview_required")
        return self


class CompanyAnalysisInputV1(StrictModel):
    """``bidops.company-analysis-input.v1`` (DEMO §5): narrative-v2 and company fit.

    The retrieval parts keep the builder's own validation; this model fixes the
    top-level key set, identity types and the required completed overview.
    """

    schema_version: Literal["bidops.company-analysis-input.v1"]
    purpose: Literal["company_fit", "deep_review"]
    execution_nonce: UUID
    target_review_id: UUID | None
    company_id: UUID
    profile_version_id: UUID
    profile_sha256: Sha256
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)
    ontology_sha256: Sha256
    notice_id: int = Field(ge=1)
    document_version_ids: list[UUID] = Field(min_length=1)
    bundle_id: UUID | None
    overview_run_id: UUID
    overview_sha256: Sha256
    policy_version_id: UUID
    policy_sha256: Sha256
    model_name: str = Field(min_length=1)
    model_revision: str | None
    generation_config_sha256: Sha256
    requirements: list[dict[str, Any]]
    profile_facts: list[dict[str, Any]]
    profile_evidence: list[dict[str, Any]]
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    graph_paths: list[dict[str, Any]]
    coverage: dict[str, Any]


class CompanyAnalysisInputV2(CompanyAnalysisInputV1):
    """``bidops.company-analysis-input.v2`` (HP-03 v2 keys; RL-03 ``card_analysis``).

    ``overview_*`` are both null (RL ``card-v1``, D1) or both set.  The nested
    ``company_binding`` must be the same binding as the top-level identity.
    """

    schema_version: Literal["bidops.company-analysis-input.v2"]  # type: ignore[assignment]
    purpose: Literal["deep_review"]  # type: ignore[assignment]
    overview_run_id: UUID | None  # type: ignore[assignment]
    overview_sha256: Sha256 | None  # type: ignore[assignment]
    card_analysis: CardAnalysisInput

    @model_validator(mode="after")
    def _binding_and_overview(self) -> "CompanyAnalysisInputV2":
        if (self.overview_run_id is None) != (self.overview_sha256 is None):
            raise ValueError("input_overview_partial")
        binding = self.card_analysis.company_binding
        if (
            binding.graph_version_id != self.graph_version_id
            or binding.graph_sha256 != self.graph_sha256
            or binding.profile_version_id != self.profile_version_id
            or binding.profile_sha256 != self.profile_sha256
            or binding.ontology_version != self.ontology_version
            or binding.ontology_sha256 != self.ontology_sha256
        ):
            raise ValueError("card_company_binding_mismatch")
        return self


CompanyAnalysisInput = Annotated[
    CompanyAnalysisInputV1 | CompanyAnalysisInputV2,
    Field(discriminator="schema_version"),
]
_COMPANY_ANALYSIS_INPUT = TypeAdapter(CompanyAnalysisInput)


def validate_company_analysis_input(value: Any) -> CompanyAnalysisInputV1 | CompanyAnalysisInputV2:
    """Validate a frozen input as v1 or v2 by ``schema_version`` (ValueError on failure)."""

    try:
        return _COMPANY_ANALYSIS_INPUT.validate_python(value)
    except ValidationError as error:
        raise ValueError("company_analysis_input_invalid") from error


#: Identity fields duplicated on a company view and its provenance (§10).
_SHARED_IDENTITY = (
    "company_id", "profile_version_id", "graph_version_id", "graph_sha256",
    "ontology_version", "input_sha256",
)


def _assert_identity(view: object, provenance: FrozenProvenance, extra: tuple[str, ...] = ()) -> None:
    for name in (*_SHARED_IDENTITY, *extra):
        if getattr(view, name) != getattr(provenance, name):
            raise ValueError("provenance_identity_mismatch")


class CompanyDeepReviewPreviewView(DeepReviewPreviewView):
    """Existing Luna preview + company identity; ``input`` is CompanyAnalysisInput."""

    company_id: UUID
    profile_version_id: UUID
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _input_identity(self) -> "CompanyDeepReviewPreviewView":
        frozen = self.input
        validate_company_analysis_input(frozen)
        if (
            frozen.get("schema_version") not in {
                "bidops.company-analysis-input.v1", "bidops.company-analysis-input.v2",
            }
            or frozen.get("purpose") != "deep_review"
            or frozen.get("execution_nonce") != str(self.preview_id)
            or frozen.get("company_id") != str(self.company_id)
            or frozen.get("profile_version_id") != str(self.profile_version_id)
            or frozen.get("graph_version_id") != str(self.graph_version_id)
            or frozen.get("graph_sha256") != self.graph_sha256
            or frozen.get("ontology_version") != self.ontology_version
        ):
            raise ValueError("preview_identity_mismatch")
        return self


class CompanyReviewView(DeepReviewView):
    """Existing DeepReviewView + company identity and the frozen provenance.

    The source of ``provenance`` (and of every identity field here) is the
    approved preview of ``current_attempt``; a company review always has one.
    """

    company_id: UUID
    profile_version_id: UUID
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)
    input_sha256: Sha256
    is_current: bool
    provenance: FrozenProvenance

    @model_validator(mode="after")
    def _identity(self) -> "CompanyReviewView":
        if self.current_attempt is None:
            raise ValueError("company_review_without_attempt")
        if self.provenance.purpose != "deep_review":
            raise ValueError("provenance_identity_mismatch")
        _assert_identity(self, self.provenance, ("bundle_id",))
        return self


# --- company-scoped reads (contract §6, §10) ------------------------------------


class GraphPath(StrictModel):
    """One frozen ``input.graph_paths`` row (contract §5 GraphPath)."""

    requirement_id: str = Field(min_length=1)
    node_ids: list[str]
    edge_ids: list[str]
    profile_evidence_ids: list[UUID]
    relation: Literal["direct", "partial", "unmapped"]


#: Same-name fields present on both a company fit view and its provenance (§10).
_FIT_SHARED_IDENTITY = ("profile_sha256", "overview_sha256", "model_name", "model_revision")


class CompanyScopedFitView(CompanyFitView):
    """Existing ``CompanyFitView`` + the explicitly enumerated company fields.

    Only two base fields are re-typed for company rows: ``result`` is the v2
    payload and ``model_revision`` may be ``null`` (a company attempt stores the
    policy's declared revision or NULL, never a guessed value).  ``provenance``
    is the attempt's frozen snapshot; every identity/hash duplicated between
    the view and the snapshot must be equal.
    """

    result: CompanyFitPayloadV2 | None
    model_revision: str | None
    company_id: UUID
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)
    input_sha256: Sha256
    paths: list[GraphPath]
    provenance: FrozenProvenance

    @model_validator(mode="after")
    def _identity(self) -> "CompanyScopedFitView":
        provenance = self.provenance
        if provenance.purpose != "company_fit" or provenance.bundle_id is not None:
            raise ValueError("provenance_identity_mismatch")
        _assert_identity(self, provenance, _FIT_SHARED_IDENTITY)
        if (
            self.overview_id != provenance.overview_run_id
            or self.policy_digest != provenance.policy_sha256
            or self.document_version_id not in {row.document_version_id for row in provenance.documents}
        ):
            raise ValueError("provenance_identity_mismatch")
        return self


class CompanyFitAttemptsView(StrictModel):
    """``GET base/pre-specs/{notice_id}/company-fit`` (created_at DESC, id DESC)."""

    company_id: UUID
    notice_id: int = Field(ge=1)
    attempts: list[CompanyScopedFitView]

    @model_validator(mode="after")
    def _scope(self) -> "CompanyFitAttemptsView":
        if any(row.company_id != self.company_id or row.notice_id != self.notice_id for row in self.attempts):
            raise ValueError("company_scope_mismatch")
        return self


class CompanyFitSummary(StrictModel):
    attempt_id: UUID
    status: Literal["queued", "running", "completed", "failed", "needs_human_review"]
    decision: Literal["matched", "mismatch", "unknown"] | None
    summary: str | None
    is_current: bool

    @model_validator(mode="after")
    def _decision_only_when_completed(self) -> "CompanyFitSummary":
        # A decision exists only for a validated completed result; queued,
        # failed or unverifiable results are never shown as a decision.
        if self.status != "completed" and (self.decision is not None or self.summary is not None):
            raise ValueError("fit_decision_without_result")
        if self.status == "completed" and (self.decision is None or self.summary is None):
            raise ValueError("fit_result_missing")
        return self


class CompanyReviewSummary(StrictModel):
    review_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    is_current: bool


class CompanyNotice(StrictModel):
    notice_id: int = Field(ge=1)
    opportunity_id: int | None
    title: str | None
    posted_at: datetime | None
    deadline_at: datetime | None
    fit: CompanyFitSummary | None
    review: CompanyReviewSummary | None
    tracking: CompanyTrackingDTO | None

    @model_validator(mode="after")
    def _tracking_matches_opportunity(self) -> "CompanyNotice":
        if (self.tracking is None) != (self.opportunity_id is None):
            raise ValueError("tracking_opportunity_mismatch")
        if self.tracking is not None and self.tracking.opportunity_id != self.opportunity_id:
            raise ValueError("tracking_opportunity_mismatch")
        return self


class CompanyPreSpecListView(StrictModel):
    schema_version: Literal["bidops.company-pre-spec-list.v1"] = "bidops.company-pre-spec-list.v1"
    items: list[CompanyNotice]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CompanyNoticeDetailView(CompanyNotice):
    overview_run_id: UUID | None
    bundle_id: UUID | None
    document_version_ids: list[UUID]
    company_id: UUID

    @model_validator(mode="after")
    def _company_scope(self) -> "CompanyNoticeDetailView":
        if self.tracking is not None and self.tracking.company_id != self.company_id:
            raise ValueError("company_scope_mismatch")
        return self


class CompanyReportView(StrictModel):
    """Wrapper preserving the existing ``ReportView`` unchanged in ``view``."""

    schema_version: Literal["bidops.company-report-view.v1"] = "bidops.company-report-view.v1"
    company_id: UUID
    graph_version_id: UUID
    graph_sha256: Sha256
    ontology_version: str = Field(min_length=1)
    profile_version_id: UUID
    view: ReportView

    @model_validator(mode="after")
    def _report_scope(self) -> "CompanyReportView":
        if self.view.report.profile_version_id != self.profile_version_id:
            raise ValueError("report_identity_mismatch")
        return self


ComparisonStatus = Literal["comparable", "stale", "missing", "different_input"]


class CompanyComparisonItem(StrictModel):
    company: CompanyDTO
    fit: CompanyFitSummary | None
    review: CompanyReviewSummary | None
    tracking: CompanyTrackingDTO | None
    graph_version_id: UUID | None
    comparison_status: ComparisonStatus

    @model_validator(mode="after")
    def _company_scope(self) -> "CompanyComparisonItem":
        if self.tracking is not None and self.tracking.company_id != self.company.company_id:
            raise ValueError("company_scope_mismatch")
        return self


class CompanyComparisonView(StrictModel):
    schema_version: Literal["bidops.company-comparison.v1"] = "bidops.company-comparison.v1"
    notice_id: int = Field(ge=1)
    document_version_ids: list[UUID]
    items: list[CompanyComparisonItem]

    @model_validator(mode="after")
    def _slug_order(self) -> "CompanyComparisonView":
        slugs = [item.company.slug for item in self.items]
        if slugs != sorted(slugs) or len(slugs) != len(set(slugs)):
            raise ValueError("comparison_order_invalid")
        return self


__all__ = [
    "AttemptView",
    "CompanyAnalysisInput",
    "CompanyAnalysisInputV1",
    "CompanyAnalysisInputV2",
    "CompanyComparisonItem",
    "CompanyComparisonView",
    "CompanyDeepReviewPreviewView",
    "CompanyFitAttemptsView",
    "CompanyFitSummary",
    "CompanyNotice",
    "CompanyNoticeDetailView",
    "CompanyPreSpecListView",
    "CompanyReportView",
    "CompanyReviewSummary",
    "CompanyReviewView",
    "CompanyScopedFitView",
    "FrozenDocument",
    "FrozenProvenance",
    "validate_company_analysis_input",
    "GraphPath",
]
