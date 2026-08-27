"""Approved deep-review report/evidence endpoints #11-14 (T7 registers router)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import (
    AgentAction,
    AgentActorKind,
    AgentActorRef,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    CreateFullRevisionCommand,
    DecisionAgent,
    FinalOpinionPayload,
    FullRevisionPayload,
    RecordFinalOpinionCommand,
    report_revision_artifact_ref,
    validation_artifact_ref,
)
from ..db import get_db
from ..models import AuditEvent, DeepReview, IdempotencyRecord, ReportRevision, ValidationCheck, ValidationRun
from ..schemas.reports import EvidenceView, FinalOpinionRequest, FinalOpinionView, ReportRevisionRequest, ReportView
from ..services.evidence import EvidenceService, EvidenceServiceError
from ..services.document_bundles import BundleServiceError, validate_actor
from ..services.reports import ReportService, ReportServiceError


router = APIRouter(prefix="/api", tags=["deep-review-reports"])
service = ReportService()
evidence_service = EvidenceService()


def _actor_ref(actor: str | None, actor_format: str | None = None) -> AgentActorRef:
    """Build the strict human actor after preserving the legacy validation."""

    try:
        claimed_name = validate_actor(actor, actor_format)
        return AgentActorRef(actor_kind=AgentActorKind.human, claimed_name=claimed_name)
    except BundleServiceError as error:
        raise ReportServiceError(error.code, error.message, status_code=error.status_code) from error
    except ValidationError as error:
        raise ReportServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400) from error


def _revision_ref(session: Session, review_id: UUID, revision_id: UUID) -> AgentArtifactRef:
    revision = session.scalar(
        select(ReportRevision).where(
            ReportRevision.deep_review_id == review_id,
            ReportRevision.id == revision_id,
        )
    )
    if revision is None:
        raise ReportServiceError("not_found", "report revision을 찾을 수 없습니다", status_code=404)
    return report_revision_artifact_ref(revision)


def _revision_ref_for_command(
    session: Session,
    review_id: UUID,
    revision_id: UUID,
    *,
    allow_missing: bool,
) -> AgentArtifactRef:
    try:
        return _revision_ref(session, review_id, revision_id)
    except ReportServiceError:
        if not allow_missing:
            raise
        return AgentArtifactRef(
            artifact_type=AgentArtifactType.report_revision,
            artifact_id=str(revision_id),
            version=1,
            sha256="0" * 64,
        )


def _validation_ref(session: Session, review_id: UUID, validation_id: UUID) -> AgentArtifactRef:
    validation = session.scalar(
        select(ValidationRun).where(
            ValidationRun.deep_review_id == review_id,
            ValidationRun.id == validation_id,
        )
    )
    if validation is None:
        raise ReportServiceError("not_found", "validation run을 찾을 수 없습니다", status_code=404)
    checks = session.scalars(
        select(ValidationCheck)
        .where(ValidationCheck.validation_run_id == validation.id)
        .order_by(ValidationCheck.id.asc())
    ).all()
    return validation_artifact_ref(validation, checks)


def _validation_ref_for_command(
    session: Session,
    review_id: UUID,
    validation_id: UUID,
    *,
    allow_missing: bool,
) -> AgentArtifactRef:
    try:
        return _validation_ref(session, review_id, validation_id)
    except ReportServiceError:
        if not allow_missing:
            raise
        return AgentArtifactRef(
            artifact_type=AgentArtifactType.validation_run,
            artifact_id=str(validation_id),
            version=1,
            sha256="0" * 64,
        )


def _review_lineage(session: Session, review_id: UUID) -> UUID | None:
    """Read the persisted lineage without allocating a correlation ID."""

    audits = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == "deep_review.create",
            AuditEvent.aggregate_type == "deep_review",
            AuditEvent.aggregate_id == str(review_id),
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(2)
    ).all()
    if len(audits) > 1:
        raise ReportServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500)
    audit = audits[0] if audits else None
    metadata = audit.safe_metadata if audit is not None and isinstance(audit.safe_metadata, Mapping) else {}
    value = metadata.get("correlation_id")
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ReportServiceError("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500) from error


def _review(session: Session, review_id: UUID) -> DeepReview:
    review = session.get(DeepReview, review_id)
    if review is None:
        raise ReportServiceError("not_found", "deep review를 찾을 수 없습니다", status_code=404)
    return review


def _current_revision(session: Session, review_id: UUID) -> ReportRevision | None:
    return session.scalar(
        select(ReportRevision)
        .where(ReportRevision.deep_review_id == review_id)
        .order_by(ReportRevision.sequence.desc(), ReportRevision.id.desc())
        .limit(1)
    )


def _has_replay(
    session: Session,
    *,
    operation: str,
    review_id: UUID,
    actor: str,
    request_id: UUID,
) -> bool:
    return session.scalar(
        select(IdempotencyRecord.id).where(
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.aggregate_type == "deep_review",
            IdempotencyRecord.aggregate_id == str(review_id),
            IdempotencyRecord.claimed_name == actor,
            IdempotencyRecord.request_id == request_id,
        )
    ) is not None

_MESSAGES = {
    "invalid_request": "요청을 처리할 수 없습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "대상을 찾을 수 없습니다",
    "review_not_ready": "심층 검토가 아직 준비되지 않았습니다",
    "version_conflict": "대상이 변경되어 다시 시도해야 합니다",
    "idempotency_conflict": "같은 request_id가 다른 요청에 사용되었습니다",
    "evidence_out_of_scope": "심층 검토 범위 밖의 근거입니다",
    "factual_change_evidence_required": "사실 변경에는 범위 내 근거가 필요합니다",
    "validation_failed": "검증에 실패했습니다",
    "final_opinion_reason_required": "최종 의견 사유가 필요합니다",
    "unsafe_document": "안전 검사를 통과하지 못한 문서입니다",
    "processing_failed": "보고서 작업을 완료할 수 없습니다",
}
_ALLOWED = frozenset(_MESSAGES)
_STATUS = {
    "not_found": 404, "review_not_ready": 409, "version_conflict": 409,
    "idempotency_conflict": 409, "evidence_out_of_scope": 403,
    "factual_change_evidence_required": 400, "validation_failed": 409,
    "unsafe_document": 403, "final_opinion_reason_required": 400,
}


def _error_response(error: ReportServiceError | EvidenceServiceError, *, request_id: UUID | None = None) -> JSONResponse:
    code = error.code if error.code in _ALLOWED else "processing_failed"
    return JSONResponse(
        status_code=getattr(error, "status_code", None) or _STATUS.get(code, 400),
        content={
            "error": {"code": code, "message": _MESSAGES[code], "details": None},
            "request_id": str(request_id or getattr(error, "request_id", None)) if (request_id or getattr(error, "request_id", None)) else None,
        },
    )


@router.get("/deep-reviews/{deep_review_id}/report", response_model=ReportView)
def get_report(deep_review_id: UUID, session: Session = Depends(get_db)) -> ReportView | JSONResponse:
    try:
        return service.get_report(session, deep_review_id)
    except ReportServiceError as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "report failed", status_code=500))


@router.post("/deep-reviews/{deep_review_id}/report-revisions", response_model=ReportView, status_code=201)
def create_report_revision(
    deep_review_id: UUID,
    payload: ReportRevisionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> ReportView | JSONResponse:
    try:
        actor_ref = _actor_ref(actor, actor_format)
        _review(session, deep_review_id)
        replay = _has_replay(
            session,
            operation="deep_review_report_revision",
            review_id=deep_review_id,
            actor=actor_ref.claimed_name,  # type: ignore[arg-type]
            request_id=payload.request_id,
        )
        current = _current_revision(session, deep_review_id)
        if not replay and (current is None or current.id != payload.base_revision_id):
            raise ReportServiceError(
                "version_conflict",
                "현재 report revision이 변경되었습니다",
                status_code=409,
                request_id=payload.request_id,
            )
        if not replay and payload.report.deep_review_id != deep_review_id:
            raise ReportServiceError(
                "validation_failed",
                "report가 deep review 범위와 일치하지 않습니다",
                status_code=422,
                request_id=payload.request_id,
            )
        old_payload = current.report_payload if current is not None and isinstance(current.report_payload, Mapping) else {}
        if not replay and payload.report.system_recommendation != old_payload.get("system_recommendation"):
            raise ReportServiceError(
                "validation_failed",
                "system recommendation은 base revision에서 변경할 수 없습니다",
                status_code=409,
                request_id=payload.request_id,
            )
        command = CreateFullRevisionCommand(
            schema="bidops.agent-command.v1",
            agent_name="decision",
            action=AgentAction.create_full_revision,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.deep_review,
                aggregate_id=str(deep_review_id),
            ),
            actor=actor_ref,
            request_id=payload.request_id,
            correlation_id=_review_lineage(session, deep_review_id),
            expected_version=None,
            input_refs=[_revision_ref_for_command(
                session,
                deep_review_id,
                payload.base_revision_id,
                allow_missing=replay,
            )],
            payload=FullRevisionPayload(
                base_revision_id=payload.base_revision_id,
                report=payload.report,
                reason=payload.reason,
                factual_change_evidence_ids=payload.factual_change_evidence_ids,
            ),
        )
        return DecisionAgent(service).create_full_revision(session, command).result
    except ReportServiceError as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "revision failed", status_code=500), request_id=payload.request_id)


@router.post("/deep-reviews/{deep_review_id}/final-opinions", response_model=FinalOpinionView, status_code=201)
def create_final_opinion(
    deep_review_id: UUID,
    payload: FinalOpinionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> FinalOpinionView | JSONResponse:
    try:
        actor_ref = _actor_ref(actor, actor_format)
        _review(session, deep_review_id)
        replay = _has_replay(
            session,
            operation="deep_review_final_opinion",
            review_id=deep_review_id,
            actor=actor_ref.claimed_name,  # type: ignore[arg-type]
            request_id=payload.request_id,
        )
        revision = session.scalar(
            select(ReportRevision).where(
                ReportRevision.deep_review_id == deep_review_id,
                ReportRevision.id == payload.report_revision_id,
            )
        )
        validation = session.scalar(
            select(ValidationRun).where(
                ValidationRun.deep_review_id == deep_review_id,
                ValidationRun.report_revision_id == payload.report_revision_id,
                ValidationRun.id == payload.validation_run_id,
            )
        )
        if not replay and (revision is None or validation is None):
            raise ReportServiceError(
                "not_found",
                "report revision 또는 validation run을 찾을 수 없습니다",
                status_code=404,
                request_id=payload.request_id,
            )
        if not replay and validation is not None and payload.acknowledged_validation_failure != (validation.status == "failed"):
            raise ReportServiceError(
                "validation_failed",
                "validation 상태와 acknowledge가 일치하지 않습니다",
                status_code=409,
                request_id=payload.request_id,
            )
        if not replay and not payload.reason.strip():
            raise ReportServiceError(
                "final_opinion_reason_required",
                "최종 의견 사유가 필요합니다",
                status_code=400,
                request_id=payload.request_id,
            )
        command = RecordFinalOpinionCommand(
            schema="bidops.agent-command.v1",
            agent_name="decision",
            action=AgentAction.record_final_opinion,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.deep_review,
                aggregate_id=str(deep_review_id),
            ),
            actor=actor_ref,
            request_id=payload.request_id,
            correlation_id=_review_lineage(session, deep_review_id),
            expected_version=None,
            input_refs=[
                _revision_ref_for_command(
                    session,
                    deep_review_id,
                    payload.report_revision_id,
                    allow_missing=replay,
                ),
                _validation_ref_for_command(
                    session,
                    deep_review_id,
                    payload.validation_run_id,
                    allow_missing=replay,
                ),
            ],
            payload=FinalOpinionPayload(
                report_revision_id=payload.report_revision_id,
                validation_run_id=payload.validation_run_id,
                value=payload.value,
                reason=payload.reason,
                acknowledged_validation_failure=payload.acknowledged_validation_failure,
            ),
        )
        return DecisionAgent(service).record_final_opinion(session, command).result
    except ReportServiceError as error:
        return _error_response(error, request_id=payload.request_id)
    except Exception:
        session.rollback()
        return _error_response(ReportServiceError("processing_failed", "opinion failed", status_code=500), request_id=payload.request_id)


@router.get("/evidence/{evidence_id}", response_model=EvidenceView)
def get_evidence(evidence_id: UUID, session: Session = Depends(get_db)) -> EvidenceView | JSONResponse:
    try:
        return evidence_service.get(session, evidence_id)
    except EvidenceServiceError as error:
        return _error_response(error)
    except Exception:
        session.rollback()
        return _error_response(EvidenceServiceError("processing_failed", "evidence failed", status_code=500))


__all__ = ["evidence_service", "router", "service"]
