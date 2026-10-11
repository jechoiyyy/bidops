"""Company-scoped read projections: list, detail, fit attempts, review, report, comparison.

Demo contract §6 (endpoints, CompanyNotice, summaries, comparison rules), §9
(DEMO off and foreign ids are ``not_found``; reads ignore the reference-mode and
Luna flags; a report without a result is ``review_not_ready``) and §10 (views
serialize the *stored* FrozenProvenance snapshot -- the fit attempt's own, the
current attempt's approved preview for a review -- and never rebuild it from
live rows; any identity disagreement is ``processing_failed``).

Boundaries:

* Every company query filters by ``company_id``; another company's review,
  attempt or evidence is ``not_found``.
* Shared notice rows (population, search, order, authoritative opportunity) and
  per-company tracking decisions come from lifecycle public names
  (``company_pre_spec_notices``, ``company_tracking_views``); lifecycle never
  imports this module.
* Projections are batched: a fixed number of queries per request regardless of
  the number of notices (no per-notice lookups).
* Nothing here writes, enqueues or calls a model.  Fit decision, review status
  and tracking status are reported side by side, never merged into a verdict.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...lifecycle import company_pre_spec_notices, company_tracking_views
from ...lifecycle.models import Company, Notice
from ..models import (
    CompanyFitPolicyVersion,
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    DeepReview,
    EvidenceRef,
    KnowledgeOntologyVersion,
    PreSpecCompanyFitAttempt,
)
from ..schemas.company_analysis import (
    CompanyComparisonView,
    CompanyFitAttemptsView,
    CompanyFitSummary,
    CompanyNoticeDetailView,
    CompanyPreSpecListView,
    CompanyReportView,
    CompanyReviewSummary,
    FrozenProvenance,
)
from ..schemas.reports import EvidenceView
from .company_analysis_input import ready_bundle_document_sets
from .company_deep_review import company_review_current_flags, company_review_view, current_attempt_previews
from .company_fit import (
    CompanyFitResultError,
    company_current_flags,
    current_company_overviews,
    digest,
    validate_company_fit_result,
)
from .company_fit_policy import policy_row_payload
from .deep_reviews import DeepReviewService, DeepReviewServiceError
from .evidence import EvidenceService, EvidenceServiceError
from .reports import ReportService, ReportServiceError


#: The fixed demo population of the comparison (contract §7), slug ascending.
DEMO_COMPANY_SLUGS: tuple[str, ...] = ("demo-cloud-si", "demo-data-ai", "demo-public-si")
FIT_DECISIONS: tuple[str, ...] = ("matched", "mismatch", "unknown")
LIST_SORTS: tuple[str, ...] = ("posted_at_desc", "deadline_asc")
TRACKING_STATUSES: tuple[str, ...] = ("미선택", "계속 추적", "보류", "종료")

#: Stable codes a company read may answer with (contract §9) and their status.
READ_ERROR_STATUS: dict[str, int] = {
    "not_found": 404,
    "evidence_out_of_scope": 403,
    "unsafe_document": 403,
    "review_not_ready": 409,
    "processing_failed": 500,
}
READ_ERROR_MESSAGES: dict[str, str] = {
    "not_found": "대상을 찾을 수 없습니다",
    "evidence_out_of_scope": "심층 검토 범위 밖의 근거입니다",
    "unsafe_document": "안전 검사를 통과하지 못한 문서입니다",
    "review_not_ready": "심층 검토가 아직 준비되지 않았습니다",
    "processing_failed": "회사 분석 결과를 처리할 수 없습니다",
}


class CompanyReadError(RuntimeError):
    """One stable read code; the message never carries source text."""

    def __init__(self, code: str) -> None:
        if code not in READ_ERROR_STATUS:
            code = "processing_failed"
        self.code = code
        self.status_code = READ_ERROR_STATUS[code]
        super().__init__(READ_ERROR_MESSAGES[code])


def _error(code: str) -> CompanyReadError:
    return CompanyReadError(code)


# --- gates and ownership ------------------------------------------------------------


def _demo_gate(settings: Any) -> None:
    if not getattr(settings, "demo_enabled", False):
        raise _error("not_found")


def _company(session: Session, company_id: UUID, settings: Any) -> Company:
    """DEMO off or unknown company → ``not_found``. No reference/Luna flag is read."""

    _demo_gate(settings)
    company = session.get(Company, company_id)
    if company is None:
        raise _error("not_found")
    return company


def _owned_review(session: Session, company_id: UUID, review_id: UUID) -> DeepReview:
    review = session.scalar(select(DeepReview).where(
        DeepReview.id == review_id, DeepReview.company_id == company_id,
    ))
    if review is None:
        # Unknown, NULL-lineage and other companies' reviews look the same.
        raise _error("not_found")
    return review


def _pre_spec_notice(session: Session, notice_id: int):
    """The shared notice row of any pre-spec (past results are not hidden by SW changes)."""

    rows = company_pre_spec_notices(session, notice_ids=[int(notice_id)], sw_only=False)
    if not rows:
        raise _error("not_found")
    return rows[0]


def is_company_review(session: Session, review_id: UUID) -> bool:
    """True for a company-scoped review (legacy ID readers refuse those, contract §1/§6)."""

    return session.scalar(
        select(DeepReview.id).where(DeepReview.id == review_id, DeepReview.company_id.is_not(None))
    ) is not None


def is_company_evidence(session: Session, evidence_id: UUID) -> bool:
    """True when the evidence belongs to a company-scoped review."""

    return session.scalar(
        select(EvidenceRef.id)
        .join(DeepReview, DeepReview.id == EvidenceRef.deep_review_id)
        .where(EvidenceRef.id == evidence_id, DeepReview.company_id.is_not(None))
    ) is not None


def company_dto(company: Company) -> dict[str, Any]:
    return {
        "company_id": company.id, "slug": company.slug, "name": company.name,
        "is_fictional": company.is_fictional, "created_at": company.created_at,
    }


# --- batched latest executions and summaries --------------------------------------------


def latest_company_fits(
    session: Session, company_ids: Iterable[UUID], notice_ids: Iterable[int]
) -> dict[tuple[UUID, int], PreSpecCompanyFitAttempt]:
    """(company, notice) → latest-created fit attempt (created_at DESC, id DESC). One query.

    The latest execution is selected even when it is queued or failed; an
    older completed attempt is never used as a fallback.
    """

    companies = tuple(dict.fromkeys(company_ids))
    notices = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not companies or not notices:
        return {}
    latest: dict[tuple[UUID, int], PreSpecCompanyFitAttempt] = {}
    for row in session.scalars(
        select(PreSpecCompanyFitAttempt)
        .where(
            PreSpecCompanyFitAttempt.company_id.in_(companies),
            PreSpecCompanyFitAttempt.notice_id.in_(notices),
        )
        .order_by(PreSpecCompanyFitAttempt.created_at.desc(), PreSpecCompanyFitAttempt.id.desc())
    ):
        latest.setdefault((row.company_id, int(row.notice_id)), row)
    return latest


def latest_company_reviews(
    session: Session, company_ids: Iterable[UUID], notice_ids: Iterable[int]
) -> dict[tuple[UUID, int], DeepReview]:
    """(company, notice) → latest-created review (created_at DESC, id DESC). One query."""

    companies = tuple(dict.fromkeys(company_ids))
    notices = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not companies or not notices:
        return {}
    latest: dict[tuple[UUID, int], DeepReview] = {}
    for row in session.scalars(
        select(DeepReview)
        .where(DeepReview.company_id.in_(companies), DeepReview.notice_id.in_(notices))
        .order_by(DeepReview.created_at.desc(), DeepReview.id.desc())
    ):
        latest.setdefault((row.company_id, int(row.notice_id)), row)
    return latest


def _fit_result(row: PreSpecCompanyFitAttempt):
    """(status, validated v2 payload | None, error_code) of one attempt.

    A completed row whose stored result does not hash or validate against its
    frozen input is shown as ``needs_human_review`` with
    ``company_fit_validation_failed`` (same rule as the legacy view); its
    decision is never shown.
    """

    if row.status != "completed":
        return row.status, None, row.error_code
    try:
        if digest(row.result_jsonb) != row.result_sha256:
            raise CompanyFitResultError("result_hash_mismatch")
        return "completed", validate_company_fit_result(row.result_jsonb, row.input_jsonb), row.error_code
    except (CompanyFitResultError, ValidationError, TypeError, ValueError, KeyError, AttributeError):
        return "needs_human_review", None, "company_fit_validation_failed"


def fit_summaries(
    session: Session, rows: Sequence[PreSpecCompanyFitAttempt], *, settings: Any
) -> dict[UUID, CompanyFitSummary]:
    """attempt id → CompanyFitSummary; currentness batched in ``company_current_flags``."""

    if not rows:
        return {}
    flags = company_current_flags(session, rows, settings=settings)
    out: dict[UUID, CompanyFitSummary] = {}
    for row in rows:
        status, payload, _error_code = _fit_result(row)
        out[row.id] = CompanyFitSummary(
            attempt_id=row.id, status=status,
            decision=payload.decision if payload is not None else None,
            summary=payload.summary if payload is not None else None,
            is_current=bool(flags.get(row.id, False)),
        )
    return out


def review_summaries(
    session: Session, reviews: Sequence[DeepReview], *, settings: Any
) -> dict[UUID, CompanyReviewSummary]:
    """review id → CompanyReviewSummary; currentness batched in ``company_review_current_flags``."""

    if not reviews:
        return {}
    flags = company_review_current_flags(session, reviews, settings=settings)
    return {
        review.id: CompanyReviewSummary(
            review_id=review.id, status=review.status, is_current=bool(flags.get(review.id, False)),
        )
        for review in reviews
    }


def current_document_sets(
    session: Session, notice_ids: Sequence[int]
) -> dict[int, tuple[UUID, list[UUID]]]:
    """notice → (latest ``ready`` bundle id, its document_version_ids sorted). Two queries.

    This is the notice's *common current document-version set* used by the
    detail view and the comparison (company independent).  A notice without a
    ready bundle is absent (detail: ``bundle_id=null``, ``document_version_ids=[]``).
    Same source as the frozen document set of a deep review and of a company
    fit (a v3 fit enqueue requires this ready bundle, contract §9 2026-10-11).
    """

    return ready_bundle_document_sets(session, notice_ids)


# --- GET base/pre-specs -------------------------------------------------------------


def company_pre_spec_list(
    session: Session,
    *,
    company_id: UUID,
    q: str | None = None,
    fit: str | None = None,
    tracking_status: str | None = None,
    sort: str = "posted_at_desc",
    limit: int = 50,
    offset: int = 0,
    settings: Any = None,
) -> dict[str, Any]:
    """``bidops.company-pre-spec-list.v1`` of one company.

    Population: every SW사업대상=Y pre-spec in the DB (with or without
    executions).  ``fit`` keeps notices whose latest fit attempt is a current,
    completed, validated result with that decision; ``tracking_status`` keeps
    notices whose connected opportunity has that company decision (a notice
    without an opportunity has no tracking and never matches).  Both filters
    and ``q`` run before pagination; ``total`` counts the filtered set.
    """

    settings = settings or get_settings()
    if fit is not None and fit not in FIT_DECISIONS:
        raise ValueError("fit_filter_invalid")
    if tracking_status is not None and tracking_status not in TRACKING_STATUSES:
        raise ValueError("tracking_status_invalid")
    if sort not in LIST_SORTS or int(limit) < 1 or int(offset) < 0:
        raise ValueError("pagination_invalid")
    _company(session, company_id, settings)
    notices = company_pre_spec_notices(session, q=q, sort=sort)
    fits = latest_company_fits(session, [company_id], [row.notice_id for row in notices])
    fit_views = fit_summaries(session, list(fits.values()), settings=settings)
    tracking = company_tracking_views(
        session, company_ids=[company_id],
        opportunity_ids=[row.opportunity_id for row in notices if row.opportunity_id is not None],
    )
    filtered = []
    for row in notices:
        attempt = fits.get((company_id, row.notice_id))
        summary = fit_views.get(attempt.id) if attempt is not None else None
        if fit is not None and not (
            summary is not None and summary.status == "completed" and summary.is_current and summary.decision == fit
        ):
            continue
        decision = tracking.get((company_id, row.opportunity_id)) if row.opportunity_id is not None else None
        if tracking_status is not None and (decision is None or decision.tracking_status != tracking_status):
            continue
        filtered.append((row, summary, decision))
    page = filtered[int(offset): int(offset) + int(limit)]
    reviews = latest_company_reviews(session, [company_id], [row.notice_id for row, _, _ in page])
    review_views = review_summaries(session, list(reviews.values()), settings=settings)
    items = []
    for row, summary, decision in page:
        review = reviews.get((company_id, row.notice_id))
        items.append({
            "notice_id": row.notice_id, "opportunity_id": row.opportunity_id, "title": row.title,
            "posted_at": row.posted_at, "deadline_at": row.deadline_at,
            "fit": summary, "review": review_views.get(review.id) if review is not None else None,
            "tracking": decision,
        })
    try:
        return CompanyPreSpecListView.model_validate({
            "items": items, "total": len(filtered), "limit": int(limit), "offset": int(offset),
        }).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


# --- GET base/pre-specs/{notice_id} --------------------------------------------------


def company_pre_spec_detail(
    session: Session, *, company_id: UUID, notice_id: int, settings: Any = None
) -> dict[str, Any]:
    """CompanyNotice + current analysis inputs of one pre-spec for one company.

    ``overview_run_id`` is the notice's current completed v7 overview run;
    ``bundle_id``/``document_version_ids`` are the latest ready bundle and its
    documents (the common current document set).  All nullable/empty when not
    ready; past executions are still summarised.
    """

    settings = settings or get_settings()
    _company(session, company_id, settings)
    row = _pre_spec_notice(session, notice_id)
    attempt = latest_company_fits(session, [company_id], [row.notice_id]).get((company_id, row.notice_id))
    review = latest_company_reviews(session, [company_id], [row.notice_id]).get((company_id, row.notice_id))
    fit_view = fit_summaries(session, [attempt], settings=settings).get(attempt.id) if attempt is not None else None
    review_view = review_summaries(session, [review], settings=settings).get(review.id) if review is not None else None
    decision = None
    if row.opportunity_id is not None:
        decision = company_tracking_views(
            session, company_ids=[company_id], opportunity_ids=[row.opportunity_id]
        ).get((company_id, row.opportunity_id))
    overview = current_company_overviews(session, [row.notice_id]).get(row.notice_id)
    bundle_id, document_ids = current_document_sets(session, [row.notice_id]).get(row.notice_id, (None, []))
    try:
        return CompanyNoticeDetailView.model_validate({
            "notice_id": row.notice_id, "opportunity_id": row.opportunity_id, "title": row.title,
            "posted_at": row.posted_at, "deadline_at": row.deadline_at,
            "fit": fit_view, "review": review_view, "tracking": decision,
            "overview_run_id": overview[0].id if overview is not None else None,
            "bundle_id": bundle_id, "document_version_ids": document_ids, "company_id": company_id,
        }).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


# --- GET base/pre-specs/{notice_id}/company-fit --------------------------------------


def _pages(requirement: Mapping[str, Any]) -> list[int]:
    return sorted({
        unit["page"] for unit in requirement.get("source_units") or []
        if isinstance(unit, Mapping) and isinstance(unit.get("page"), int) and not isinstance(unit.get("page"), bool)
    })


def _fit_view(
    row: PreSpecCompanyFitAttempt,
    *,
    graph: CompanyKnowledgeVersion | None,
    ontology: KnowledgeOntologyVersion | None,
    policy_row: CompanyFitPolicyVersion | None,
    is_current: bool,
) -> dict[str, Any]:
    """One CompanyScopedFitView from the stored attempt row and its frozen snapshot.

    Identity comes from immutable rows (attempt columns, graph/ontology/policy
    versions) and the frozen input; ``provenance`` is the stored snapshot.
    A broken input hash, a foreign graph, an unverifiable pinned policy or
    any identity disagreement is ``processing_failed`` -- never repaired.
    """

    inputs = row.input_jsonb if isinstance(row.input_jsonb, Mapping) else None
    provenance = row.provenance_jsonb if isinstance(row.provenance_jsonb, Mapping) else None
    payload = policy_row_payload(policy_row)
    try:
        intact = inputs is not None and digest(inputs) == row.input_sha256
    except (TypeError, ValueError):
        intact = False
    if (
        not intact
        or provenance is None
        or graph is None
        or ontology is None
        or payload is None
        or graph.company_id != row.company_id
        or graph.id != row.graph_version_id
        or graph.profile_version_id != row.profile_version_id
        or graph.ontology_id != ontology.id
        or policy_row.sha256 != row.policy_digest
        or provenance.get("ontology_sha256") != ontology.sha256
        or provenance.get("policy_version_id") != str(row.company_fit_policy_version_id)
    ):
        raise _error("processing_failed")
    status, result, error_code = _fit_result(row)
    try:
        notice_facts = [
            {"ref": requirement["id"], "text": requirement["text"], "pages": _pages(requirement), "block_key": None}
            for requirement in inputs["requirements"]
        ]
        company_facts = [
            {"ref": fact["fact_key"], "fact_key": fact["fact_key"], "status": fact["status"], "value": fact["value"]}
            for fact in inputs["profile_facts"]
        ]
        return {
            "id": row.id, "notice_id": row.notice_id, "status": status, "result": result,
            "error_code": error_code, "is_current": bool(is_current), "overview_kind": "overview_run",
            "overview_id": row.overview_run_id, "document_version_id": row.document_version_id,
            "overview_sha256": inputs["overview_sha256"], "profile_version_id": row.profile_version_id,
            "profile_sha256": inputs["profile_sha256"], "policy_digest": row.policy_digest,
            "model_name": row.model_name, "model_revision": row.model_revision,
            "prompt_version": payload["prompt_version"], "quality_status": row.quality_status,
            "notice_facts": notice_facts, "company_facts": company_facts,
            "created_at": row.created_at, "completed_at": row.completed_at,
            "prompt_tokens": row.prompt_tokens, "output_tokens": row.output_tokens, "latency_ms": row.latency_ms,
            "company_id": row.company_id, "graph_version_id": row.graph_version_id,
            "graph_sha256": graph.graph_sha256, "ontology_version": ontology.version,
            "input_sha256": row.input_sha256, "paths": deepcopy(inputs["graph_paths"]),
            "provenance": deepcopy(dict(provenance)),
        }
    except (KeyError, TypeError):
        raise _error("processing_failed") from None


def company_fit_attempts(
    session: Session, *, company_id: UUID, notice_id: int, settings: Any = None
) -> dict[str, Any]:
    """``{company_id, notice_id, attempts: CompanyFitView[]}`` (created_at DESC, id DESC).

    Every attempt of this company for the notice, including queued ones (their
    provenance is already frozen at enqueue).  Constant query count.
    """

    settings = settings or get_settings()
    _company(session, company_id, settings)
    notice = session.get(Notice, int(notice_id))
    if notice is None or notice.source_type != "pre_spec":
        raise _error("not_found")
    rows = session.scalars(
        select(PreSpecCompanyFitAttempt)
        .where(PreSpecCompanyFitAttempt.company_id == company_id, PreSpecCompanyFitAttempt.notice_id == int(notice_id))
        .order_by(PreSpecCompanyFitAttempt.created_at.desc(), PreSpecCompanyFitAttempt.id.desc())
    ).all()
    flags = company_current_flags(session, rows, settings=settings) if rows else {}
    graphs = {
        row.id: row for row in session.scalars(select(CompanyKnowledgeVersion).where(
            CompanyKnowledgeVersion.id.in_({row.graph_version_id for row in rows})
        ))
    } if rows else {}
    ontologies = {
        row.id: row for row in session.scalars(select(KnowledgeOntologyVersion).where(
            KnowledgeOntologyVersion.id.in_({graph.ontology_id for graph in graphs.values()})
        ))
    } if graphs else {}
    policies = {
        row.id: row for row in session.scalars(select(CompanyFitPolicyVersion).where(
            CompanyFitPolicyVersion.id.in_({row.company_fit_policy_version_id for row in rows})
        ))
    } if rows else {}
    views = []
    for row in rows:
        graph = graphs.get(row.graph_version_id)
        views.append(_fit_view(
            row, graph=graph, ontology=ontologies.get(graph.ontology_id) if graph is not None else None,
            policy_row=policies.get(row.company_fit_policy_version_id), is_current=flags.get(row.id, False),
        ))
    try:
        return CompanyFitAttemptsView.model_validate({
            "company_id": company_id, "notice_id": int(notice_id), "attempts": views,
        }).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


# --- GET base/deep-reviews/{review_id}[/report|/evidence/{id}] -----------------------


def company_review_detail(
    service: DeepReviewService, session: Session, *, company_id: UUID, review_id: UUID, settings: Any = None
) -> dict[str, Any]:
    """CompanyReviewView; provenance is the current attempt's approved preview snapshot."""

    settings = settings or get_settings()
    _company(session, company_id, settings)
    review = _owned_review(session, company_id, review_id)
    try:
        return company_review_view(service, session, review, settings=settings)
    except DeepReviewServiceError as error:
        raise _error(error.code if error.code == "not_found" else "processing_failed") from None


def _review_lineage(session: Session, review: DeepReview) -> tuple[CompanyKnowledgeVersion, KnowledgeOntologyVersion]:
    graph = session.get(CompanyKnowledgeVersion, review.graph_version_id) if review.graph_version_id else None
    ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id) if graph is not None else None
    if (
        graph is None
        or ontology is None
        or graph.company_id != review.company_id
        or graph.profile_version_id != review.profile_version_id
    ):
        raise _error("processing_failed")
    return graph, ontology


def company_report(
    report_service: ReportService,
    session: Session,
    *,
    company_id: UUID,
    review_id: UUID,
    settings: Any = None,
) -> dict[str, Any]:
    """``bidops.company-report-view.v1`` wrapping the existing ReportView unchanged.

    No materialized report is the existing ``review_not_ready`` (409).  The
    report's own review/notice/bundle/profile/policy ids must be the review's;
    otherwise ``processing_failed``.
    """

    settings = settings or get_settings()
    _company(session, company_id, settings)
    review = _owned_review(session, company_id, review_id)
    graph, ontology = _review_lineage(session, review)
    try:
        view = report_service.get_report(session, review.id)
    except ReportServiceError as error:
        raise _error(error.code if error.code in {"not_found", "review_not_ready"} else "processing_failed") from None
    report = view.get("report") if isinstance(view, Mapping) else None
    if (
        not isinstance(report, Mapping)
        or str(view.get("deep_review_id")) != str(review.id)
        or str(report.get("deep_review_id")) != str(review.id)
        or report.get("notice_id") != review.notice_id
        or str(report.get("bundle_id")) != str(review.bundle_id)
        or str(report.get("policy_version_id")) != str(review.policy_version_id)
    ):
        raise _error("processing_failed")
    try:
        return CompanyReportView.model_validate({
            "company_id": review.company_id, "graph_version_id": graph.id, "graph_sha256": graph.graph_sha256,
            "ontology_version": ontology.version, "profile_version_id": review.profile_version_id,
            "view": view,
        }).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


def company_evidence(
    evidence_service: EvidenceService,
    session: Session,
    *,
    company_id: UUID,
    review_id: UUID,
    evidence_id: UUID,
    settings: Any = None,
) -> dict[str, Any]:
    """Existing EvidenceView of an evidence row that belongs to this company's review."""

    settings = settings or get_settings()
    _company(session, company_id, settings)
    review = _owned_review(session, company_id, review_id)
    owned = session.scalar(select(EvidenceRef.id).where(
        EvidenceRef.id == evidence_id, EvidenceRef.deep_review_id == review.id,
    ))
    if owned is None:
        raise _error("not_found")
    try:
        value = evidence_service.get(session, evidence_id)
    except EvidenceServiceError as error:
        raise _error(error.code) from None
    try:
        return EvidenceView.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


# --- GET /api/pre-specs/{notice_id}/company-comparison ---------------------------------


def _frozen_documents(value: Any) -> frozenset[UUID]:
    try:
        provenance = FrozenProvenance.model_validate(value)
    except ValidationError:
        raise _error("processing_failed") from None
    return frozenset(row.document_version_id for row in provenance.documents)


def comparison_status(
    common: frozenset[UUID],
    executions: Sequence[tuple[frozenset[UUID], bool]],
    *,
    fit_present: bool,
    review_present: bool,
) -> str:
    """Contract §6 priority: different_input > stale > missing > comparable.

    ``executions`` are (frozen document set, is_current) of the existing fit
    and review.  Each execution's own status is reported separately.
    """

    if any(documents != common for documents, _current in executions):
        return "different_input"
    if any(not current for _documents, current in executions):
        return "stale"
    if not fit_present or not review_present:
        return "missing"
    return "comparable"


def company_comparison(session: Session, *, notice_id: int, settings: Any = None) -> dict[str, Any]:
    """``bidops.company-comparison.v1`` over the three §7 demo companies.

    Only registered companies with the fixed demo slugs, slug ascending (a slug
    that is not registered has no CompanyDTO and is omitted).  Latest execution
    per fit/review, no fallback.  ``graph_version_id`` is the company's active
    binding (null when unbound).  No ranking or aggregate score.
    """

    settings = settings or get_settings()
    _demo_gate(settings)
    row = _pre_spec_notice(session, notice_id)
    companies = session.scalars(
        select(Company).where(Company.slug.in_(DEMO_COMPANY_SLUGS)).order_by(Company.slug.asc())
    ).all()
    company_ids = [company.id for company in companies]
    fits = latest_company_fits(session, company_ids, [row.notice_id])
    reviews = latest_company_reviews(session, company_ids, [row.notice_id])
    fit_views = fit_summaries(session, list(fits.values()), settings=settings)
    review_views = review_summaries(session, list(reviews.values()), settings=settings)
    previews = current_attempt_previews(session, list(reviews.values()))
    bindings = {
        binding.company_id: binding.graph_version_id
        for binding in session.scalars(select(CompanyKnowledgeBinding).where(
            CompanyKnowledgeBinding.company_id.in_(company_ids)
        ))
    } if company_ids else {}
    tracking = company_tracking_views(
        session, company_ids=company_ids, opportunity_ids=[row.opportunity_id]
    ) if row.opportunity_id is not None and company_ids else {}
    _bundle_id, document_ids = current_document_sets(session, [row.notice_id]).get(row.notice_id, (None, []))
    common = frozenset(document_ids)
    items = []
    for company in companies:
        attempt = fits.get((company.id, row.notice_id))
        review = reviews.get((company.id, row.notice_id))
        fit_view = fit_views.get(attempt.id) if attempt is not None else None
        review_view = review_views.get(review.id) if review is not None else None
        executions: list[tuple[frozenset[UUID], bool]] = []
        if attempt is not None:
            executions.append((_frozen_documents(attempt.provenance_jsonb), fit_view.is_current))
        if review is not None:
            preview = previews.get(review.id)
            if preview is None:
                raise _error("processing_failed")
            executions.append((_frozen_documents(preview.provenance_jsonb), review_view.is_current))
        items.append({
            "company": company_dto(company), "fit": fit_view, "review": review_view,
            "tracking": tracking.get((company.id, row.opportunity_id)) if row.opportunity_id is not None else None,
            "graph_version_id": bindings.get(company.id),
            "comparison_status": comparison_status(
                common, executions, fit_present=attempt is not None, review_present=review is not None,
            ),
        })
    try:
        return CompanyComparisonView.model_validate({
            "notice_id": row.notice_id, "document_version_ids": document_ids, "items": items,
        }).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


__all__ = [
    "DEMO_COMPANY_SLUGS",
    "READ_ERROR_MESSAGES",
    "READ_ERROR_STATUS",
    "CompanyReadError",
    "company_comparison",
    "company_evidence",
    "company_fit_attempts",
    "company_pre_spec_detail",
    "company_pre_spec_list",
    "company_report",
    "company_review_detail",
    "comparison_status",
    "current_document_sets",
    "fit_summaries",
    "is_company_evidence",
    "is_company_review",
    "latest_company_fits",
    "latest_company_reviews",
    "review_summaries",
]
