"""Thin DeepReviewAgent adapter over ``DeepReviewService``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..common import (
    AgentAction,
    AgentActionResult,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactType,
    AgentCommand,
    AgentName,
    AgentRunView,
)
from ...schemas.deep_reviews import AttemptView, DeepReviewView
from ...core.models import AuditEvent
from ...deep_review.models import (
    AnalysisPolicyVersion,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    DocumentBundle,
    DocumentBundleItem,
    EvidenceRef,
    ProfileVersion,
    ReportRevision,
    ReportRevisionEvidence,
    ValidationCheck,
    ValidationRun,
    WorkJob,
)
from .commands import (
    DeepReviewActionCommand,
    RetryAttemptCommand,
    StartReviewCommand,
)
from .projection import (
    attempt_artifact_ref,
    bundle_artifact_ref,
    project_deep_review,
)

if TYPE_CHECKING:
    from ...services.deep_reviews import DeepReviewService, DeepReviewServiceError


CommandT = TypeVar("CommandT", bound=BaseModel)


class DeepReviewAgent:
    """Typed command boundary; service/worker/materializer remain authoritative."""

    name = AgentName.deep_review

    def __init__(
        self,
        service: Any | None = None,
        *,
        session: Session | None = None,
    ) -> None:
        if service is None:
            from ...services.deep_reviews import DeepReviewService

            service = DeepReviewService()
        self.service = service
        self._session = session

    @staticmethod
    def _error(code: str, message: str, *, status_code: int = 400, request_id: UUID | None = None) -> Any:
        from ...services.deep_reviews import DeepReviewServiceError

        return DeepReviewServiceError(code, message, status_code=status_code, request_id=request_id)

    @classmethod
    def _invalid(cls, message: str = "deep review command is invalid", *, request_id: UUID | None = None) -> Any:
        return cls._error("invalid_request", message, status_code=400, request_id=request_id)

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
            raise DeepReviewAgent._error(
                "invalid_request", "aggregate ID가 올바르지 않습니다", status_code=400, request_id=request_id
            ) from exc

    @staticmethod
    def _notice_id(command: AgentCommand[BaseModel]) -> int:
        try:
            value = int(command.aggregate.aggregate_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DeepReviewAgent._error("invalid_request", "notice aggregate가 올바르지 않습니다", status_code=400) from exc
        if value < 1:
            raise DeepReviewAgent._error("invalid_request", "notice aggregate가 올바르지 않습니다", status_code=400)
        return value

    @staticmethod
    def _actor(command: AgentCommand[BaseModel]) -> str:
        claimed_name = command.actor.claimed_name
        if not claimed_name:
            raise DeepReviewAgent._error("actor_name_required", "담당자 이름이 필요합니다", status_code=400, request_id=command.request_id)
        return claimed_name

    @staticmethod
    def _bundle_creation_lineage(session: Session, bundle_id: UUID) -> UUID | None:
        rows = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.action == "document_bundle.create",
                AuditEvent.aggregate_type == "document_bundle",
                AuditEvent.aggregate_id == str(bundle_id),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(2)
        ).all()
        if len(rows) > 1:
            raise DeepReviewAgent._error("processing_failed", "document bundle 계보를 확인할 수 없습니다", status_code=500)
        if not rows:
            return None
        metadata = rows[0].safe_metadata if isinstance(rows[0].safe_metadata, Mapping) else {}
        if "correlation_id" not in metadata:
            return None
        value = metadata.get("correlation_id")
        if value is None:
            raise DeepReviewAgent._error("processing_failed", "document bundle 계보를 확인할 수 없습니다", status_code=500)
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DeepReviewAgent._error("processing_failed", "document bundle 계보를 확인할 수 없습니다", status_code=500) from exc

    @staticmethod
    def _bundle_snapshot(session: Session, bundle_id: UUID) -> tuple[DocumentBundle, list[DocumentBundleItem]]:
        bundle = session.get(DocumentBundle, bundle_id)
        if bundle is None:
            raise DeepReviewAgent._error("not_found", "document bundle을 찾을 수 없습니다", status_code=404)
        items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == bundle.id)
            .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
        ).all()
        return bundle, items

    def _verify_start_bundle(self, session: Session, command: StartReviewCommand) -> UUID:
        bundle_id = command.payload.bundle_id
        bundle, items = self._bundle_snapshot(session, bundle_id)
        if bundle.notice_id != self._notice_id(command) or bundle.status != "ready":
            raise self._invalid("start_review requires the ready bundle for the notice", request_id=command.request_id)
        try:
            actual = bundle_artifact_ref(bundle, items)
        except ValueError as exc:
            raise self._error("processing_failed", "ready bundle snapshot을 확인할 수 없습니다", status_code=500, request_id=command.request_id) from exc
        if command.input_refs[0] != actual:
            raise self._invalid("start_review bundle ref does not match the persisted ready bundle", request_id=command.request_id)
        lineage = self._bundle_creation_lineage(session, bundle.id)
        if command.correlation_id is not None and command.correlation_id != lineage:
            raise self._invalid("start_review correlation lineage does not match the bundle", request_id=command.request_id)
        return bundle_id

    @staticmethod
    def _stages_for_attempt(session: Session, attempt_id: UUID) -> list[DeepReviewStage]:
        return session.scalars(
            select(DeepReviewStage)
            .where(DeepReviewStage.attempt_id == attempt_id)
            .order_by(DeepReviewStage.sequence.asc(), DeepReviewStage.id.asc())
        ).all()

    def _verify_retry_attempt(self, session: Session, command: RetryAttemptCommand) -> UUID:
        review_id = self._uuid(command.aggregate.aggregate_id, request_id=command.request_id)
        review = session.get(DeepReview, review_id)
        if review is None or review.current_attempt_id is None:
            raise self._error("review_not_ready", "재시도할 current attempt가 없습니다", status_code=409, request_id=command.request_id)
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        if attempt is None or attempt.deep_review_id != review.id:
            raise self._error("review_not_ready", "재시도할 current attempt가 없습니다", status_code=409, request_id=command.request_id)
        try:
            actual_ref = attempt_artifact_ref(attempt, self._stages_for_attempt(session, attempt.id))
        except (ValueError, TypeError) as exc:
            raise self._error("processing_failed", "current attempt snapshot을 확인할 수 없습니다", status_code=500, request_id=command.request_id) from exc
        if command.input_refs[0] != actual_ref:
            raise self._invalid("retry_attempt ref does not match the current attempt", request_id=command.request_id)
        lineage = self._review_lineage(session, review.id)
        if command.correlation_id is not None and command.correlation_id != lineage:
            raise self._invalid("retry_attempt correlation lineage does not match the review", request_id=command.request_id)
        return review_id

    @staticmethod
    def _review_lineage(session: Session, review_id: UUID) -> UUID | None:
        rows = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.action == "deep_review.create",
                AuditEvent.aggregate_type == "deep_review",
                AuditEvent.aggregate_id == str(review_id),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(2)
        ).all()
        if len(rows) > 1:
            raise DeepReviewAgent._error("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500)
        if not rows:
            return None
        metadata = rows[0].safe_metadata if isinstance(rows[0].safe_metadata, Mapping) else {}
        if "correlation_id" not in metadata:
            return None
        value = metadata.get("correlation_id")
        if value is None:
            raise DeepReviewAgent._error("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500)
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DeepReviewAgent._error("processing_failed", "deep review 계보를 확인할 수 없습니다", status_code=500) from exc

    def _read_snapshot(self, session: Session, review_id: UUID) -> dict[str, Any]:
        review = session.get(DeepReview, review_id)
        if review is None:
            raise self._error("not_found", "deep review를 찾을 수 없습니다", status_code=404)
        attempts = session.scalars(
            select(DeepReviewAttempt)
            .where(DeepReviewAttempt.deep_review_id == review.id)
            .order_by(DeepReviewAttempt.sequence.asc(), DeepReviewAttempt.id.asc())
        ).all()
        if review.current_attempt_id is None or not any(row.id == review.current_attempt_id for row in attempts):
            raise self._error("processing_failed", "deep review current attempt가 없습니다", status_code=500)
        attempt_ids = [row.id for row in attempts]
        stage_rows = session.scalars(
            select(DeepReviewStage)
            .where(DeepReviewStage.attempt_id.in_(attempt_ids) if attempt_ids else False)
            .order_by(DeepReviewStage.attempt_id.asc(), DeepReviewStage.sequence.asc(), DeepReviewStage.id.asc())
        ).all()
        stages: dict[str, list[DeepReviewStage]] = {str(row.id): [] for row in attempts}
        for row in stage_rows:
            stages.setdefault(str(row.attempt_id), []).append(row)
        bundle = session.get(DocumentBundle, review.bundle_id)
        bundle_items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == review.bundle_id)
            .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
        ).all()
        profile = session.get(ProfileVersion, review.profile_version_id)
        policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
        audits = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.aggregate_type == "deep_review", AuditEvent.aggregate_id == str(review.id))
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        ).all()
        bundle_creation_audits = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.action == "document_bundle.create",
                AuditEvent.aggregate_type == "document_bundle",
                AuditEvent.aggregate_id == str(review.bundle_id),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        ).all()
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
        evidence_ids = [row.evidence_ref_id for row in revision_evidence]
        evidence = session.scalars(
            select(EvidenceRef)
            .where(EvidenceRef.deep_review_id == review.id)
            .order_by(EvidenceRef.id.asc())
        ).all()
        jobs = session.scalars(
            select(WorkJob)
            .where(WorkJob.job_type == "deep_review", WorkJob.aggregate_type == "deep_review", WorkJob.aggregate_id == review.id)
            .order_by(WorkJob.created_at.asc(), WorkJob.id.asc())
        ).all()
        return {
            "review": review,
            "attempts": attempts,
            "stages": stages,
            "bundle": bundle,
            "bundle_items": bundle_items,
            "profile": profile,
            "policy": policy,
            "audits": audits,
            "bundle_creation_audits": bundle_creation_audits,
            "revisions": revisions,
            "validations": validations,
            "validation_checks": checks,
            "revision_evidence": revision_evidence,
            "evidence": evidence,
            "jobs": jobs,
        }

    def _project(self, session: Session, review_id: UUID, *, attempt_id: UUID | None = None) -> AgentRunView:
        snapshot = self._read_snapshot(session, review_id)
        return project_deep_review(snapshot, attempt_id=attempt_id)

    def start(
        self,
        session: Session | StartReviewCommand | None,
        command: StartReviewCommand | None = None,
    ) -> AgentActionResult[DeepReviewView]:
        if command is None and isinstance(session, StartReviewCommand):
            command, session = session, self._session
        current_session, raw_command = self._bind(session if isinstance(session, Session) else None, command)
        typed = self._command(raw_command, StartReviewCommand)
        bundle_id = self._verify_start_bundle(current_session, typed)
        result = self.service.create_review(
            current_session,
            self._notice_id(typed),
            bundle_id,
            self._actor(typed),
            typed.request_id,  # type: ignore[arg-type]
        )
        domain = result if isinstance(result, DeepReviewView) else DeepReviewView.model_validate(result)
        run = self._project(current_session, domain.id)
        return AgentActionResult[DeepReviewView](run=run, result=domain)

    def retry_attempt(
        self,
        session: Session,
        command: RetryAttemptCommand | AgentCommand[BaseModel],
    ) -> AgentActionResult[AttemptView]:
        typed = self._command(command, RetryAttemptCommand)
        review_id = self._verify_retry_attempt(session, typed)
        result = self.service.create_attempt(
            session,
            review_id,
            self._actor(typed),
            typed.request_id,  # type: ignore[arg-type]
        )
        domain = result if isinstance(result, AttemptView) else AttemptView.model_validate(result)
        run = self._project(session, review_id, attempt_id=domain.id)
        return AgentActionResult[AttemptView](run=run, result=domain)

    def act(
        self,
        session: Session | DeepReviewActionCommand | None,
        command: DeepReviewActionCommand | None = None,
    ) -> AgentActionResult[DeepReviewView | AttemptView]:
        if command is None and isinstance(session, BaseModel):
            command, session = session, self._session
        current_session, raw_command = self._bind(session if isinstance(session, Session) else None, command)
        if not isinstance(raw_command, BaseModel):
            raise self._invalid()
        action = getattr(raw_command, "action", None)
        if action is AgentAction.start_review or action == AgentAction.start_review.value:
            return self.start(current_session, raw_command)  # type: ignore[arg-type]
        if action is AgentAction.retry_attempt or action == AgentAction.retry_attempt.value:
            return self.retry_attempt(current_session, raw_command)  # type: ignore[arg-type]
        raise self._invalid()

    def status(
        self,
        session: Session | AgentAggregateRef | None,
        aggregate: AgentAggregateRef | None = None,
    ) -> AgentRunView:
        if aggregate is None and isinstance(session, AgentAggregateRef):
            aggregate, session = session, self._session
        if not isinstance(aggregate, AgentAggregateRef) or not isinstance(session, Session):
            raise self._invalid()
        if aggregate.aggregate_type is not AgentAggregateType.deep_review:
            raise self._invalid("deep review status는 deep review aggregate가 필요합니다")
        review_id = self._uuid(aggregate.aggregate_id)
        return self._project(session, review_id)


__all__ = ["DeepReviewAgent"]
