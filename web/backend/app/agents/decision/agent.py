"""Thin DecisionAgent adapter over the existing report service."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import (
    AgentAction,
    AgentActionResult,
    AgentAggregateRef,
    AgentAggregateType,
    AgentCommand,
    AgentName,
    AgentRunStatus,
)
from ...models import (
    AuditEvent,
    DeepReview,
    EvidenceRef,
    FinalOpinion,
    ReportRevision,
    ReportRevisionEvidence,
    ValidationCheck,
    ValidationRun,
)
from ...schemas.reports import (
    FinalOpinionRequest,
    FinalOpinionView,
    ReportRevisionRequest,
    ReportView,
)
from ...services.reports import ReportService, ReportServiceError
from .commands import (
    CreateFullRevisionCommand,
    DecisionActionCommand,
    RecordFinalOpinionCommand,
)
from .projection import DecisionProjectionError, project_decision

CommandT = TypeVar("CommandT", bound=BaseModel)


class DecisionAgent:
    """Typed action boundary; report persistence remains service-owned."""

    name = AgentName.decision

    def __init__(self, service: ReportService | None = None, *, session: Session | None = None) -> None:
        self.service = service or ReportService()
        self._session = session

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        status_code: int = 400,
        request_id: UUID | None = None,
    ) -> ReportServiceError:
        return ReportServiceError(code, message, status_code=status_code, request_id=request_id)

    @classmethod
    def _invalid(cls, message: str = "decision command is invalid", *, request_id: UUID | None = None) -> ReportServiceError:
        return cls._error("invalid_request", message, request_id=request_id)

    @classmethod
    def _command(cls, command: object, command_type: type[CommandT]) -> CommandT:
        try:
            if isinstance(command, command_type):
                return command
            if isinstance(command, BaseModel):
                return command_type.model_validate(command.model_dump())
            return command_type.model_validate(command)
        except ValidationError as exc:
            request_id = getattr(command, "request_id", None)
            raise cls._invalid(request_id=request_id if isinstance(request_id, UUID) else None) from exc

    def _bind(self, session: Session | None, command: object | None) -> tuple[Session, object]:
        if session is None:
            session = self._session
        if session is None or command is None:
            raise self._invalid()
        return session, command

    @staticmethod
    def _uuid(value: object, *, request_id: UUID | None = None) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DecisionAgent._error(
                "invalid_request",
                "deep review aggregate가 올바르지 않습니다",
                request_id=request_id,
            ) from exc

    @staticmethod
    def _actor(command: AgentCommand[BaseModel]) -> str:
        claimed_name = command.actor.claimed_name
        if not claimed_name:
            raise DecisionAgent._error(
                "actor_name_required",
                "담당자 이름이 필요합니다",
                request_id=command.request_id,
            )
        return claimed_name

    @staticmethod
    def _review_id(command: AgentCommand[BaseModel]) -> UUID:
        return DecisionAgent._uuid(command.aggregate.aggregate_id, request_id=command.request_id)

    def _read_snapshot(self, session: Session, review_id: UUID) -> dict[str, Any]:
        review = session.get(DeepReview, review_id)
        if review is None:
            raise self._error("not_found", "deep review를 찾을 수 없습니다", status_code=404)
        revisions = session.scalars(
            select(ReportRevision)
            .where(ReportRevision.deep_review_id == review.id)
            .order_by(ReportRevision.sequence.asc(), ReportRevision.id.asc())
        ).all()
        validations = session.scalars(
            select(ValidationRun)
            .where(ValidationRun.deep_review_id == review.id)
            .order_by(ValidationRun.sequence.asc(), ValidationRun.id.asc())
        ).all()
        validation_ids = [row.id for row in validations]
        checks = session.scalars(
            select(ValidationCheck)
            .where(ValidationCheck.validation_run_id.in_(validation_ids) if validation_ids else False)
            .order_by(ValidationCheck.validation_run_id.asc(), ValidationCheck.id.asc())
        ).all()
        revision_ids = [row.id for row in revisions]
        revision_evidence = session.scalars(
            select(ReportRevisionEvidence)
            .where(ReportRevisionEvidence.report_revision_id.in_(revision_ids) if revision_ids else False)
            .order_by(ReportRevisionEvidence.report_revision_id.asc(), ReportRevisionEvidence.evidence_ref_id.asc())
        ).all()
        evidence = session.scalars(
            select(EvidenceRef)
            .where(EvidenceRef.deep_review_id == review.id)
            .order_by(EvidenceRef.id.asc())
        ).all()
        opinions = session.scalars(
            select(FinalOpinion)
            .where(FinalOpinion.deep_review_id == review.id)
            .order_by(FinalOpinion.sequence.asc(), FinalOpinion.id.asc())
        ).all()
        audits = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.aggregate_type == "deep_review",
                AuditEvent.aggregate_id == str(review.id),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        ).all()
        return {
            "review": review,
            "revisions": revisions,
            "validations": validations,
            "validation_checks": checks,
            "revision_evidence": revision_evidence,
            "evidence": evidence,
            "opinions": opinions,
            "audits": audits,
        }

    def _project(self, session: Session, review_id: UUID):
        snapshot = self._read_snapshot(session, review_id)
        try:
            return project_decision(snapshot)
        except DecisionProjectionError as exc:
            raise self._error("processing_failed", "decision 상태를 확인할 수 없습니다", status_code=500) from exc

    @staticmethod
    def _ensure_command_scope(command: AgentCommand[BaseModel], run: Any, action: AgentAction) -> None:
        if run.status is AgentRunStatus.failed:
            raise DecisionAgent._error("processing_failed", "decision 상태를 확인할 수 없습니다", status_code=500, request_id=command.request_id)
        if action not in run.available_actions:
            raise DecisionAgent._error("review_not_ready", "현재 decision 상태에서는 이 작업을 수행할 수 없습니다", status_code=409, request_id=command.request_id)
        if command.correlation_id is not None and command.correlation_id != run.correlation_id:
            raise DecisionAgent._invalid("decision correlation lineage does not match the review", request_id=command.request_id)

    @staticmethod
    def _current_refs(run: Any, expected: int) -> list[Any]:
        if len(run.input_refs) < expected:
            raise DecisionAgent._error("review_not_ready", "현재 report와 validation이 아직 준비되지 않았습니다", status_code=409)
        refs = list(run.input_refs[:expected])
        return refs

    def create_full_revision(
        self,
        session: Session,
        command: CreateFullRevisionCommand | AgentCommand[BaseModel],
    ) -> AgentActionResult[ReportView]:
        typed = self._command(command, CreateFullRevisionCommand)
        review_id = self._review_id(typed)
        run = self._project(session, review_id)
        self._ensure_command_scope(typed, run, AgentAction.create_full_revision)
        current_ref = self._current_refs(run, 2)[0]
        if typed.input_refs[0] != current_ref or typed.payload.base_revision_id != UUID(current_ref.artifact_id):
            raise self._invalid("create_full_revision ref does not match the current report revision", request_id=typed.request_id)
        payload = typed.payload
        request = ReportRevisionRequest(
            request_id=typed.request_id,  # type: ignore[arg-type]
            base_revision_id=payload.base_revision_id,
            report=payload.report,
            reason=payload.reason,
            factual_change_evidence_ids=payload.factual_change_evidence_ids,
        )
        result = self.service.create_revision(session, review_id, self._actor(typed), request)
        domain = result if isinstance(result, ReportView) else ReportView.model_validate(result)
        return AgentActionResult[ReportView](run=self._project(session, review_id), result=domain)

    def record_final_opinion(
        self,
        session: Session,
        command: RecordFinalOpinionCommand | AgentCommand[BaseModel],
    ) -> AgentActionResult[FinalOpinionView]:
        typed = self._command(command, RecordFinalOpinionCommand)
        review_id = self._review_id(typed)
        run = self._project(session, review_id)
        self._ensure_command_scope(typed, run, AgentAction.record_final_opinion)
        current_refs = self._current_refs(run, 2)
        if typed.input_refs != current_refs:
            raise self._invalid("record_final_opinion refs do not match the current report and validation", request_id=typed.request_id)
        payload = typed.payload
        request = FinalOpinionRequest(
            request_id=typed.request_id,  # type: ignore[arg-type]
            report_revision_id=payload.report_revision_id,
            validation_run_id=payload.validation_run_id,
            value=payload.value,
            reason=payload.reason,
            acknowledged_validation_failure=payload.acknowledged_validation_failure,
        )
        result = self.service.create_final_opinion(session, review_id, self._actor(typed), request)
        domain = result if isinstance(result, FinalOpinionView) else FinalOpinionView.model_validate(result)
        return AgentActionResult[FinalOpinionView](run=self._project(session, review_id), result=domain)

    def act(
        self,
        session: Session | DecisionActionCommand | None,
        command: DecisionActionCommand | None = None,
    ) -> AgentActionResult[ReportView] | AgentActionResult[FinalOpinionView]:
        if command is None and isinstance(session, BaseModel):
            command, session = session, self._session
        current_session, raw_command = self._bind(session if isinstance(session, Session) else None, command)
        if not isinstance(raw_command, BaseModel):
            raise self._invalid()
        action = getattr(raw_command, "action", None)
        if action is AgentAction.create_full_revision or action == AgentAction.create_full_revision.value:
            return self.create_full_revision(current_session, raw_command)  # type: ignore[arg-type]
        if action is AgentAction.record_final_opinion or action == AgentAction.record_final_opinion.value:
            return self.record_final_opinion(current_session, raw_command)  # type: ignore[arg-type]
        raise self._invalid()

    def status(
        self,
        session: Session | AgentAggregateRef | None,
        aggregate: AgentAggregateRef | None = None,
    ):
        if aggregate is None and isinstance(session, AgentAggregateRef):
            aggregate, session = session, self._session
        if not isinstance(aggregate, AgentAggregateRef) or not isinstance(session, Session):
            raise self._invalid()
        if aggregate.aggregate_type is not AgentAggregateType.deep_review:
            raise self._invalid("decision status는 deep review aggregate가 필요합니다")
        review_id = self._uuid(aggregate.aggregate_id)
        return self._project(session, review_id)


__all__ = ["DecisionAgent"]
