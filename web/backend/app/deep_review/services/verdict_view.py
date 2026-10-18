"""RL-03 practitioner verdict view, feedback and transfer-policy read (HP-04 "API 계약" + RL-03 "REST").

Read projection of one card-v1 attempt (``bidops.practitioner-verdict-view.v1``):

* attempt selection: an explicit ``attempt_id`` of this company/notice, else the
  newest card-v1 attempt by ``DeepReviewApproval.approved_at`` then attempt id
  (RL-03 "시각"); an explicitly selected narrative attempt is ``legacy``; no
  card attempt is ``none``.
* availability: queued→pending, running→running, completed→completed; failed
  with a ``NEEDS_HUMAN_REVIEW_CODES`` code (``WorkJob.last_error_code`` -- card
  attempts have no ``deep_review_stage`` rows) → needs_human_review, other
  failures → failed; superseded → completed if its final result exists, else
  failed, with stale reason ``superseded``.
* result only for a completed attempt with its validated ``synthesis``/``final``
  row; otherwise ``partial_matrix`` lists the validated compare rows (with the
  validated role findings) and ``partial_stage_ids`` the stored stage rows.
* identity and source binding are the attempt's frozen values (approved
  preview, immutable policy row), never the latest ones;
  ``source_binding.company_sha256`` is the frozen graph sha.
* currentness: the existing company review rule (``company_review_current_flags``)
  for the review's current attempt; stale reasons are computed per component
  (company binding, ontology, documents/bundle, policy, superseded).  An SW
  flag change makes the review not current but has no HP-04 reason value.

Nothing here writes (except the feedback insert), enqueues or calls a model.
Any disagreement in the stored rows is ``processing_failed`` -- never repaired.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...lifecycle.models import Company, Notice
from ..models import (
    AnalysisPolicyVersion,
    CardAnalysisStage,
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentVersion,
    KnowledgeOntologyVersion,
    VerdictFeedback,
    WorkJob,
)
from ..schemas.card_analysis import (
    CardAnalysisInput,
    CardAssembledPractitionerVerdict,
    CardRequirementCompare,
    CardRequirementExtract,
    CardVerdictRoleResult,
)
from ..schemas.verdict_view import (
    STALE_REASON_ORDER,
    VIEW_SCHEMA_VERSION,
    PractitionerVerdictView,
    TransferPolicyView,
    VerdictFeedbackCreate,
)
from . import transfer_policy
from .card_analysis import NEEDS_HUMAN_REVIEW_CODES
from .card_roles import cited_constraint_refs
from .company_deep_review import company_review_current_flags, resolve_company_deep_policy, rl_path
from .deep_reviews import DeepReviewServiceError, _policy_payload, quality_status_for_review
from .luna_identity import policy_reasoning_effort
from .verdict_trigger import (
    PRE_SPEC_SOURCE_TYPES,
    latest_recommendation,
    notice_opportunity_id,
    opportunity_pre_spec_notice_id,
    real_company,
    resolve_opportunity,
)


#: Stable codes of the verdict reads/feedback and their HTTP status.
VERDICT_ERROR_STATUS: dict[str, int] = {
    "invalid_request": 422,
    "actor_name_required": 400,
    "actor_name_invalid": 400,
    "not_found": 404,
    "opportunity_not_found": 404,
    "idempotency_conflict": 409,
    "processing_failed": 500,
}
VERDICT_ERROR_MESSAGES: dict[str, str] = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "opportunity_not_found": "사업기회를 찾을 수 없습니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "processing_failed": "판정 결과를 처리할 수 없습니다",
}

_ROLES = ("eligibility_economics", "technical_fit", "operations_risk")
_FIT_ORDER = {"gap": 0, "unknown": 1, "met": 2}
_STAGE_ORDER = {"extract": 0, "compare": 1, "role": 2, "synthesis": 3}


class VerdictViewError(RuntimeError):
    """One stable verdict read/feedback code; the message never carries source text."""

    def __init__(self, code: str) -> None:
        if code not in VERDICT_ERROR_STATUS:
            code = "processing_failed"
        self.code = code
        self.status_code = VERDICT_ERROR_STATUS[code]
        self.message = VERDICT_ERROR_MESSAGES[code]
        super().__init__(self.message)


def _error(code: str) -> VerdictViewError:
    return VerdictViewError(code)


# --- gates ---------------------------------------------------------------------------


def verdict_company(session: Session, company_id: UUID, settings: Any) -> Company:
    """DEMO rule (any company while the demo is on) or the RL rule (real company ∧ RL enabled)."""

    company = session.get(Company, company_id)
    if company is None:
        raise _error("not_found")
    if not getattr(settings, "demo_enabled", False) and not rl_path(settings, company):
        raise _error("not_found")
    return company


def _pre_spec_notice(session: Session, notice_id: int) -> Notice:
    notice = session.get(Notice, int(notice_id))
    if notice is None or notice.source_type not in PRE_SPEC_SOURCE_TYPES:
        raise _error("not_found")
    return notice


def _is_card_policy(policy: AnalysisPolicyVersion | None) -> bool:
    return policy is not None and _policy_payload(policy).get("pipeline_version") == "card-v1"


# --- attempt selection ---------------------------------------------------------------


def _card_policy_ids(session: Session, policy_ids: set[UUID]) -> set[UUID]:
    if not policy_ids:
        return set()
    rows = session.scalars(select(AnalysisPolicyVersion).where(AnalysisPolicyVersion.id.in_(policy_ids))).all()
    return {row.id for row in rows if _is_card_policy(row)}


def _latest_card_attempts(session: Session, company_id: UUID, notice_id: int) -> list[DeepReviewAttempt]:
    """Card attempts of the company/notice, newest first (approval ``approved_at``, then attempt id)."""

    reviews = session.execute(select(DeepReview.id, DeepReview.policy_version_id).where(
        DeepReview.company_id == company_id, DeepReview.notice_id == int(notice_id),
    )).all()
    card_policies = _card_policy_ids(session, {row.policy_version_id for row in reviews})
    review_ids = [row.id for row in reviews if row.policy_version_id in card_policies]
    if not review_ids:
        return []
    rows = session.execute(
        select(DeepReviewAttempt, DeepReviewApproval.approved_at)
        .join(DeepReviewApproval, DeepReviewApproval.attempt_id == DeepReviewAttempt.id)
        .where(DeepReviewAttempt.deep_review_id.in_(review_ids))
    ).all()
    ordered = sorted(rows, key=lambda row: (row[1], str(row[0].id)), reverse=True)
    return [attempt for attempt, _approved in ordered]


# --- projection helpers --------------------------------------------------------------


def _approved_preview(session: Session, attempt_id: UUID) -> DeepReviewPreview | None:
    return session.scalar(
        select(DeepReviewPreview)
        .join(DeepReviewApproval, DeepReviewApproval.preview_id == DeepReviewPreview.id)
        .where(DeepReviewApproval.attempt_id == attempt_id)
    )


def _stage_rows(session: Session, attempt_id: UUID) -> list[CardAnalysisStage]:
    rows = session.scalars(select(CardAnalysisStage).where(CardAnalysisStage.attempt_id == attempt_id)).all()

    def key(row: CardAnalysisStage) -> tuple[Any, ...]:
        batch = int(row.stage_key) if row.stage in {"extract", "compare"} else 0
        role = _ROLES.index(row.stage_key) if row.stage == "role" and row.stage_key in _ROLES else 0
        return (batch if row.stage in {"extract", "compare"} else 10**9, _STAGE_ORDER[row.stage], role, str(row.id))

    return sorted(rows, key=key)


def _evidence(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {"source_sha256": row.source_sha256, "block_key": row.block_key, "quote": row.quote}
        for row in rows
    ]


def _fact_labels(frozen: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for node in frozen.get("graph_nodes") or []:
        if isinstance(node, Mapping) and isinstance(node.get("id"), str) and isinstance(node.get("label"), str):
            if node["label"].strip():
                labels[node["id"]] = node["label"]
    return labels


class _AttemptStages:
    """Validated stage payloads of one attempt (any invalid stored row is ``processing_failed``)."""

    def __init__(self, rows: Sequence[CardAnalysisStage]) -> None:
        self.rows = list(rows)
        self.extract_items: dict[str, Any] = {}
        self.compare_items: list[Any] = []
        self.roles: dict[str, CardVerdictRoleResult] = {}
        self.final: CardAssembledPractitionerVerdict | None = None
        #: 결정 B51: units isolated at extract (``unit_id`` -> rule codes).
        self.rejected: dict[str, list[str]] = {}
        try:
            for row in self.rows:
                payload = row.payload if isinstance(row.payload, Mapping) else {}
                if row.stage == "extract":
                    parsed = CardRequirementExtract.model_validate(payload)
                    for item in parsed.items:
                        if item.unit_id in self.extract_items or item.unit_id in self.rejected:
                            raise _error("processing_failed")
                        self.extract_items[item.unit_id] = item
                    for rejected in parsed.rejected_units:
                        if rejected.unit_id in self.extract_items or rejected.unit_id in self.rejected:
                            raise _error("processing_failed")
                        self.rejected[rejected.unit_id] = list(rejected.rule_codes)
                elif row.stage == "compare":
                    self.compare_items.extend(CardRequirementCompare.model_validate(payload).items)
                elif row.stage == "role":
                    result = CardVerdictRoleResult.model_validate(payload)
                    if result.role != row.stage_key:
                        raise _error("processing_failed")
                    self.roles[result.role] = result
                elif row.stage == "synthesis":
                    self.final = CardAssembledPractitionerVerdict.model_validate(payload)
        except (ValidationError, TypeError, ValueError):
            raise _error("processing_failed") from None


def _matrix_row(
    *,
    unit_id: str,
    type_: str,
    fit_status: str,
    role_findings: list[dict[str, Any]],
    stages: _AttemptStages,
    units: Mapping[str, Any],
    compare_by_unit: Mapping[str, Any],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    unit = units.get(unit_id)
    extract = stages.extract_items.get(unit_id)
    if unit is None:
        raise _error("processing_failed")
    rejected_codes = stages.rejected.get(unit_id, [])
    if rejected_codes and (extract is not None or type_ is not None or fit_status != "unknown" or role_findings):
        raise _error("processing_failed")
    fact_labels: list[str] = []
    compare = compare_by_unit.get(unit_id)
    if compare is not None:
        for result in compare.constraint_results:
            for fact_id in result.fact_ids:
                label = labels.get(fact_id)
                if label is not None and label not in fact_labels:
                    fact_labels.append(label)
    return {
        "unit_id": unit_id,
        "type": type_,
        "fit_status": fit_status,
        "role_findings": role_findings,
        # 결정 B53: the unit's evidence plus the constraint quotes its role findings cite.
        "evidence_refs": _evidence([*extract.evidence, *_cited_constraints(extract, role_findings)])
        if extract is not None else [],
        "page_range": unit.page_range.model_dump(mode="json") if unit.page_range is not None else None,
        "mapping_status": unit.mapping_status,
        "normalized_requirement": extract.normalized_requirement if extract is not None else None,
        "mandatory": extract.mandatory if extract is not None else None,
        "fact_labels": fact_labels,
        "rejected_rule_codes": list(rejected_codes),
    }


def _cited_constraints(extract: Any, role_findings: Sequence[Mapping[str, Any]]) -> list[Any]:
    from ..schemas.card_analysis import CardEvidence

    refs = [CardEvidence.model_validate(ref) for finding in role_findings for ref in finding.get("evidence_refs", [])]
    return cited_constraint_refs(extract, refs)


def _sorted_matrix(rows: list[dict[str, Any]], unit_order: Mapping[str, int]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (_FIT_ORDER[row["fit_status"]], unit_order.get(row["unit_id"], 10**9)))


def _result(stages: _AttemptStages, card: CardAnalysisInput, labels: Mapping[str, str]) -> dict[str, Any]:
    final = stages.final
    assert final is not None
    # 결정 B23: the final row's missing sections are the frozen input's (rows
    # stored before the key existed carry null), and a missing section caps
    # the verdict below "진행 가능" -- a stored row that disagrees is not shown.
    if final.missing_sections is not None and list(final.missing_sections) != list(card.missing_sections):
        raise _error("processing_failed")
    if card.missing_sections and final.verdict == "진행 가능":
        raise _error("processing_failed")
    # 결정 B51: the final row's rejected units are the extract rows' (null only
    # on rows stored before the key, which can have none) and cap the verdict.
    final_rejected = {row.unit_id: list(row.rule_codes) for row in final.rejected_units or []}
    if final_rejected != stages.rejected or (stages.rejected and final.verdict == "진행 가능"):
        raise _error("processing_failed")
    units = {unit.unit_id: unit for unit in card.units}
    order = {unit.unit_id: index for index, unit in enumerate(card.units)}
    compare_by_unit = {item.unit_id: item for item in stages.compare_items}
    for row in final.matrix:
        if (row.rejected_rule_codes or None) != (stages.rejected.get(row.unit_id) or None):
            raise _error("processing_failed")
    matrix = [
        _matrix_row(
            unit_id=row.unit_id, type_=row.type, fit_status=row.fit_status,
            role_findings=[finding.model_dump(mode="json") for finding in row.role_findings],
            stages=stages, units=units, compare_by_unit=compare_by_unit, labels=labels,
        )
        for row in final.matrix
    ]
    if sorted(row["unit_id"] for row in matrix) != sorted(units):
        raise _error("processing_failed")
    return {
        "verdict": final.verdict,
        "reason": final.reason,
        "blocking_condition_ids": list(final.blocking_condition_ids),
        "checklist": [row.model_dump(mode="json") for row in final.checklist],
        "matrix": _sorted_matrix(matrix, order),
        "cautions": [row.model_dump(mode="json") for row in final.cautions],
        "conflicts": [row.model_dump(mode="json") for row in final.conflicts],
        # 결정 B55: ``origin`` is always present in the view (null before policy v9).
        "next_actions": [{**row.model_dump(mode="json"), "origin": row.origin} for row in final.next_actions],
    }


def _partial_matrix(stages: _AttemptStages, card: CardAnalysisInput, labels: Mapping[str, str]) -> list[dict[str, Any]]:
    units = {unit.unit_id: unit for unit in card.units}
    order = {unit.unit_id: index for index, unit in enumerate(card.units)}
    compare_by_unit = {item.unit_id: item for item in stages.compare_items}
    rows = []
    for item in stages.compare_items:
        extract = stages.extract_items.get(item.unit_id)
        if item.unit_id in stages.rejected:
            # 결정 B51: the fixed compare row of a rejected unit; no role sees it.
            if extract is not None or item.reason_codes != ["extract_rejected"]:
                raise _error("processing_failed")
            rows.append(_matrix_row(
                unit_id=item.unit_id, type_=None, fit_status=item.fit_status, role_findings=[],
                stages=stages, units=units, compare_by_unit=compare_by_unit, labels=labels,
            ))
            continue
        if extract is None:
            raise _error("processing_failed")
        findings = []
        for role in _ROLES:
            result = stages.roles.get(role)
            if result is None:
                continue
            for finding in result.unit_findings:
                if finding.unit_id == item.unit_id:
                    findings.append({
                        "role": role, "assessment": finding.assessment, "reason": finding.reason,
                        "evidence_refs": _evidence(finding.evidence_refs),
                    })
        rows.append(_matrix_row(
            unit_id=item.unit_id, type_=extract.type, fit_status=item.fit_status, role_findings=findings,
            stages=stages, units=units, compare_by_unit=compare_by_unit, labels=labels,
        ))
    return _sorted_matrix(rows, order)


def _identity(policy: AnalysisPolicyVersion, frozen: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = _policy_payload(policy)
    execution = payload.get("execution") if isinstance(payload.get("execution"), Mapping) else {}
    effort = policy_reasoning_effort(policy)
    cli_version = execution.get("cli_version")
    if not isinstance(effort, str) or not isinstance(cli_version, str):
        return None
    return {
        "policy_id": str(policy.id), "policy_sha256": frozen.get("policy_sha256"),
        "model": frozen.get("model_name"), "reasoning_effort": effort, "cli_version": cli_version,
    }


def _source_binding(session: Session, provenance: Mapping[str, Any], bundle_id: UUID) -> dict[str, Any]:
    structures = dict(session.execute(
        select(DocumentBundleItem.document_version_id, DocumentBundleItem.structure_id_at_confirmation)
        .where(DocumentBundleItem.bundle_id == bundle_id)
    ).all())
    documents = []
    for row in provenance.get("documents") or []:
        try:
            document_id = UUID(str(row["document_version_id"]))
        except (KeyError, TypeError, ValueError):
            raise _error("processing_failed") from None
        structure = structures.get(document_id)
        documents.append({
            "document_version_id": str(document_id), "source_sha256": row.get("source_sha256"),
            "structure_id": str(structure) if structure is not None else None,
        })
    return {
        "document_versions": documents,
        "company_version_id": provenance.get("graph_version_id"),
        "company_sha256": provenance.get("graph_sha256"),
        "ontology_sha256": provenance.get("ontology_sha256"),
    }


def _stale_reasons(
    session: Session,
    review: DeepReview,
    attempt: DeepReviewAttempt,
    frozen: Mapping[str, Any],
    provenance: Mapping[str, Any],
    settings: Any,
    *,
    newer_attempt: bool,
) -> list[str]:
    reasons: set[str] = set()
    binding = session.get(CompanyKnowledgeBinding, review.company_id)
    if (
        binding is None
        or binding.graph_version_id != review.graph_version_id
        or binding.profile_version_id != review.profile_version_id
    ):
        reasons.add("company_changed")
    if binding is not None:
        graph = session.get(CompanyKnowledgeVersion, binding.graph_version_id)
        ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id) if graph is not None else None
        if ontology is None or ontology.sha256 != frozen.get("ontology_sha256"):
            reasons.add("ontology_changed")
    bundle = session.get(DocumentBundle, review.bundle_id)
    frozen_documents: set[UUID] = set()
    for row in provenance.get("documents") or []:
        try:
            frozen_documents.add(UUID(str(row["document_version_id"])))
        except (KeyError, TypeError, ValueError):
            continue
    current_documents = set(session.scalars(select(DocumentVersion.id).where(
        DocumentVersion.id.in_(frozen_documents), DocumentVersion.is_current.is_(True),
    ))) if frozen_documents else set()
    if bundle is None or bundle.status != "ready" or not frozen_documents or frozen_documents - current_documents:
        reasons.add("documents_changed")
    try:
        policy = resolve_company_deep_policy(session, settings, rl=True)
    except DeepReviewServiceError:
        policy = None
    if (
        policy is None
        or policy.row.id != review.policy_version_id
        or policy.row.policy_sha256 != frozen.get("policy_sha256")
        or policy.row.model_name != frozen.get("model_name")
        or policy.model_revision != frozen.get("model_revision")
        or policy.generation_config_sha256 != frozen.get("generation_config_sha256")
    ):
        reasons.add("policy_changed")
    if attempt.status == "superseded" or attempt.id != review.current_attempt_id or newer_attempt:
        reasons.add("superseded")
    return [reason for reason in STALE_REASON_ORDER if reason in reasons]


def _base_view(company_id: UUID, notice_id: int | None, *, briefing_item_id: UUID | None,
               opportunity_id: int | None) -> dict[str, Any]:
    return {
        "schema_version": VIEW_SCHEMA_VERSION, "company_id": str(company_id), "notice_id": notice_id,
        "attempt_id": None, "availability": "none", "is_current": False, "stale_reasons": [],
        "quality_status": None, "identity": None, "source_binding": None, "result": None,
        "partial_stage_ids": [], "error_code": None, "missing_sections": [], "started_at": None,
        "finished_at": None, "partial_matrix": [],
        "briefing_item_id": str(briefing_item_id) if briefing_item_id is not None else None,
        "opportunity_id": opportunity_id,
        "rejected_units": [],
    }


def _validated(view: dict[str, Any]) -> dict[str, Any]:
    try:
        return PractitionerVerdictView.model_validate(view).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _project_attempt(
    session: Session,
    view: dict[str, Any],
    review: DeepReview,
    attempt: DeepReviewAttempt,
    settings: Any,
    *,
    newer_attempt: bool,
) -> dict[str, Any]:
    policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
    view["attempt_id"] = str(attempt.id)
    view["started_at"] = _iso(attempt.started_at)
    view["finished_at"] = _iso(attempt.completed_at)
    view["quality_status"] = quality_status_for_review(session, review.id)
    if not _is_card_policy(policy):
        view["availability"] = "legacy"
        return view
    preview = _approved_preview(session, attempt.id)
    frozen = preview.input_snapshot if preview is not None and isinstance(preview.input_snapshot, Mapping) else None
    provenance = (
        preview.provenance_jsonb if preview is not None and isinstance(preview.provenance_jsonb, Mapping) else None
    )
    if (
        preview is None or frozen is None or provenance is None
        or preview.company_id != review.company_id
        or preview.graph_version_id != review.graph_version_id
        or preview.policy_version_id != review.policy_version_id
        or preview.bundle_id != review.bundle_id
        or provenance.get("input_sha256") != preview.input_sha256
        or provenance.get("graph_version_id") != str(review.graph_version_id)
    ):
        raise _error("processing_failed")
    try:
        card = CardAnalysisInput.model_validate(frozen["card_analysis"])
    except (KeyError, TypeError, ValueError, ValidationError):
        raise _error("processing_failed") from None
    rows = _stage_rows(session, attempt.id)
    stages = _AttemptStages(rows)
    labels = _fact_labels(frozen)
    job = session.get(WorkJob, attempt.work_job_id) if attempt.work_job_id is not None else None
    error_code = job.last_error_code if job is not None and job.last_error_code else None

    has_result = stages.final is not None
    if attempt.status == "queued":
        availability = "pending"
    elif attempt.status == "running":
        availability = "running"
    elif attempt.status == "completed":
        if not has_result:
            raise _error("processing_failed")
        availability = "completed"
    elif attempt.status == "failed":
        availability = "needs_human_review" if error_code in NEEDS_HUMAN_REVIEW_CODES else "failed"
    elif attempt.status == "superseded":
        availability = "completed" if has_result else "failed"
    else:
        raise _error("processing_failed")

    view["availability"] = availability
    view["identity"] = _identity(policy, frozen)
    view["source_binding"] = _source_binding(session, provenance, review.bundle_id)
    view["missing_sections"] = list(card.missing_sections)
    view["rejected_units"] = [
        {"unit_id": unit.unit_id, "normalized_id": unit.normalized_id, "rule_codes": stages.rejected[unit.unit_id]}
        for unit in card.units if unit.unit_id in stages.rejected
    ]
    if set(stages.rejected) - {unit.unit_id for unit in card.units}:
        raise _error("processing_failed")
    view["error_code"] = error_code if availability in {"failed", "needs_human_review"} else None
    if availability == "completed":
        view["result"] = _result(stages, card, labels)
    else:
        view["partial_matrix"] = _partial_matrix(stages, card, labels)
        view["partial_stage_ids"] = [str(row.id) for row in rows]
    reasons = _stale_reasons(session, review, attempt, frozen, provenance, settings, newer_attempt=newer_attempt)
    current = company_review_current_flags(session, [review], settings=settings).get(review.id, False)
    view["is_current"] = bool(current and not reasons)
    view["stale_reasons"] = [] if view["is_current"] else reasons
    return view


def latest_card_attempt(session: Session, company_id: UUID, notice_id: int) -> DeepReviewAttempt | None:
    """The newest card-v1 attempt of the company/notice -- the one the verdict view shows (or None)."""

    attempts = _latest_card_attempts(session, company_id, notice_id)
    return attempts[0] if attempts else None


@dataclass(frozen=True)
class CompletedCardAttempt:
    """The validated frozen sources of one completed card-v1 attempt (read only).

    RL-04 reads its proposal input from here (spec "입력 읽기 경로"): ``frozen``
    is the approved preview ``input_snapshot`` (``bidops.company-analysis-input.v2``),
    ``card`` its validated ``card_analysis``, ``extract_items``/``compare_items``
    the validated ``card_analysis_stage`` rows and ``result`` the HP-04 verdict
    projection of the synthesis row (the same ``_result`` the verdict view shows).
    """

    attempt_id: UUID
    company_id: UUID
    notice_id: int
    input_sha256: str
    frozen: Mapping[str, Any]
    card: CardAnalysisInput
    extract_items: Mapping[str, Any]
    compare_items: tuple[Any, ...]
    result: Mapping[str, Any]


def completed_card_attempt(session: Session, attempt_id: UUID) -> CompletedCardAttempt:
    """Validated sources of a completed card-v1 attempt.

    ``not_found``: no such attempt, not a card-v1 attempt or not ``completed``.
    ``processing_failed``: the approved preview or a stored stage row disagrees
    (the same checks the verdict view applies) -- never repaired.
    """

    attempt = session.get(DeepReviewAttempt, attempt_id)
    review = session.get(DeepReview, attempt.deep_review_id) if attempt is not None else None
    if attempt is None or review is None or attempt.status != "completed":
        raise _error("not_found")
    policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
    if not _is_card_policy(policy):
        raise _error("not_found")
    preview = _approved_preview(session, attempt.id)
    frozen = preview.input_snapshot if preview is not None and isinstance(preview.input_snapshot, Mapping) else None
    provenance = (
        preview.provenance_jsonb if preview is not None and isinstance(preview.provenance_jsonb, Mapping) else None
    )
    if (
        preview is None or frozen is None or provenance is None
        or preview.company_id != review.company_id
        or preview.graph_version_id != review.graph_version_id
        or preview.policy_version_id != review.policy_version_id
        or preview.bundle_id != review.bundle_id
        or provenance.get("input_sha256") != preview.input_sha256
        or provenance.get("graph_version_id") != str(review.graph_version_id)
    ):
        raise _error("processing_failed")
    try:
        card = CardAnalysisInput.model_validate(frozen["card_analysis"])
    except (KeyError, TypeError, ValueError, ValidationError):
        raise _error("processing_failed") from None
    stages = _AttemptStages(_stage_rows(session, attempt.id))
    if stages.final is None:
        raise _error("processing_failed")
    result = _result(stages, card, _fact_labels(frozen))
    return CompletedCardAttempt(
        attempt_id=attempt.id, company_id=review.company_id, notice_id=int(review.notice_id),
        input_sha256=str(preview.input_sha256), frozen=frozen, card=card,
        extract_items=dict(stages.extract_items), compare_items=tuple(stages.compare_items), result=result,
    )


def verdict_view(
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    attempt_id: UUID | None = None,
    opportunity_id: int | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """GET /api/companies/{company_id}/pre-specs/{notice_id}/verdict?attempt_id= (read only)."""

    settings = settings or get_settings()
    verdict_company(session, company_id, settings)
    _pre_spec_notice(session, notice_id)
    item = latest_recommendation(session, notice_id)
    view = _base_view(
        company_id, int(notice_id), briefing_item_id=item.id if item is not None else None,
        opportunity_id=opportunity_id if opportunity_id is not None else notice_opportunity_id(session, notice_id),
    )
    latest = _latest_card_attempts(session, company_id, notice_id)
    if attempt_id is not None:
        attempt = session.get(DeepReviewAttempt, attempt_id)
        review = session.get(DeepReview, attempt.deep_review_id) if attempt is not None else None
        if (
            attempt is None or review is None or review.company_id != company_id
            or review.notice_id != int(notice_id)
        ):
            raise _error("not_found")
    else:
        if not latest:
            return _validated(view)
        attempt = latest[0]
        review = session.get(DeepReview, attempt.deep_review_id)
        if review is None:
            raise _error("processing_failed")
    newer = bool(latest) and latest[0].id != attempt.id and any(row.id == attempt.id for row in latest)
    return _validated(_project_attempt(session, view, review, attempt, settings, newer_attempt=newer))


def opportunity_verdict_view(
    session: Session,
    *,
    opportunity_id: int,
    attempt_id: UUID | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """GET /api/opportunities/{id}/verdict: the same view for the linked pre-spec (alias, read only).

    RL path only (``BIDOPS_RL_ANALYSIS_ENABLED`` and the registered real
    company).  A merged opportunity reads its retained opportunity.  Without an
    authoritatively linked pre-spec the answer is 200 ``availability=none``
    with ``notice_id=null``.
    """

    settings = settings or get_settings()
    if not getattr(settings, "rl_analysis_enabled", False):
        raise _error("not_found")
    opportunity = resolve_opportunity(session, opportunity_id)
    if opportunity is None:
        raise _error("opportunity_not_found")
    company = real_company(session)
    if company is None or not rl_path(settings, company):
        raise _error("not_found")
    notice_id = opportunity_pre_spec_notice_id(session, opportunity.id)
    if notice_id is None:
        if attempt_id is not None:
            raise _error("not_found")
        return _validated(_base_view(company.id, None, briefing_item_id=None, opportunity_id=opportunity.id))
    return verdict_view(
        session, company_id=company.id, notice_id=notice_id, attempt_id=attempt_id,
        opportunity_id=opportunity.id, settings=settings,
    )


# --- feedback ----------------------------------------------------------------------------


def create_verdict_feedback(
    session: Session,
    *,
    company_id: UUID,
    notice_id: int,
    payload: VerdictFeedbackCreate,
    actor: str,
    settings: Any = None,
) -> dict[str, Any]:
    """POST …/verdict-feedback → 201 ``{feedback_id}`` (append-only; commits).

    The attempt must be a card-v1 attempt of this company/notice (else 404);
    ``unit_id`` must be one of its frozen units (else 422).  The same
    ``request_id`` replays the first receipt; a different body with it is
    ``idempotency_conflict``.  Feedback never changes a verdict, tracking or
    Go/No-Go.
    """

    settings = settings or get_settings()
    verdict_company(session, company_id, settings)
    _pre_spec_notice(session, notice_id)
    note = payload.note
    replay = session.scalar(select(VerdictFeedback).where(VerdictFeedback.request_id == payload.request_id))
    if replay is not None:
        return _feedback_replay(replay, payload, actor, note)
    attempt = session.get(DeepReviewAttempt, payload.attempt_id)
    review = session.get(DeepReview, attempt.deep_review_id) if attempt is not None else None
    if (
        attempt is None or review is None or review.company_id != company_id
        or review.notice_id != int(notice_id)
        or not _is_card_policy(session.get(AnalysisPolicyVersion, review.policy_version_id))
    ):
        raise _error("not_found")
    if payload.unit_id is not None:
        preview = _approved_preview(session, attempt.id)
        frozen = preview.input_snapshot if preview is not None and isinstance(preview.input_snapshot, Mapping) else {}
        units = (frozen.get("card_analysis") or {}).get("units") if isinstance(frozen, Mapping) else None
        unit_ids = {row.get("unit_id") for row in units or [] if isinstance(row, Mapping)}
        if payload.unit_id not in unit_ids:
            raise _error("invalid_request")
    row = VerdictFeedback(
        id=uuid4(), attempt_id=attempt.id, kind=payload.kind, unit_id=payload.unit_id, note=note,
        actor=actor, request_id=payload.request_id,
    )
    try:
        session.add(row)
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(select(VerdictFeedback).where(VerdictFeedback.request_id == payload.request_id))
        if replay is None:
            raise _error("processing_failed") from None
        return _feedback_replay(replay, payload, actor, note)
    return {"feedback_id": str(row.id)}


def _feedback_replay(row: VerdictFeedback, payload: VerdictFeedbackCreate, actor: str, note: str | None) -> dict[str, Any]:
    if (
        row.attempt_id != payload.attempt_id or row.kind != payload.kind or row.unit_id != payload.unit_id
        or row.note != note or row.actor != actor
    ):
        raise _error("idempotency_conflict")
    return {"feedback_id": str(row.id)}


# --- transfer policy (settings screen) ----------------------------------------------------


def transfer_policy_view(session: Session, *, settings: Any = None) -> dict[str, Any]:
    """GET /api/analysis/transfer-policy (operational; RL off → 404)."""

    settings = settings or get_settings()
    if not getattr(settings, "rl_analysis_enabled", False):
        raise _error("not_found")
    approval = transfer_policy.active_approval(session)
    active = None
    if approval is not None:
        active = {
            "approval_id": str(approval.id), "policy_identity": approval.policy_identity,
            "policy_sha256": approval.policy_sha256, "daily_cap": int(approval.daily_cap),
            "approved_at": approval.approved_at, "approved_by": approval.approved_by,
            "today_used": transfer_policy.today_used(session),
        }
    try:
        return TransferPolicyView.model_validate({"active": active}).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


__all__ = [
    "CompletedCardAttempt",
    "VERDICT_ERROR_MESSAGES",
    "VERDICT_ERROR_STATUS",
    "VerdictViewError",
    "completed_card_attempt",
    "create_verdict_feedback",
    "latest_card_attempt",
    "opportunity_verdict_view",
    "transfer_policy_view",
    "verdict_company",
    "verdict_view",
]
