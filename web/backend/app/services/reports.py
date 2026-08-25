"""Append-only report, validation, and final-opinion service for lean v1."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Claim,
    ClaimEvidence,
    AuditEvent,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    DocumentBlock,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    EvidenceRef,
    FinalOpinion,
    IdempotencyRecord,
    ProfileEvidence,
    ProfileVersion,
    ReportRevision,
    ReportRevisionEvidence,
    ValidationCheck,
    ValidationRun,
    WorkJob,
)
from ..schemas.reports import FinalOpinionRequest, ReportRevisionRequest
from .deep_review_validation import (
    DeepReviewValidationError,
    REQUIRED_SECTIONS,
    validate_deep_review_report,
    validate_deep_review_validation,
)
from .document_bundles import BundleServiceError, validate_actor
from .deep_reviews import JobClaim, StaleFenceError


STAGE_NAMES = ("requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation")
SECTION_TITLES = {
    "project_overview": "프로젝트 기본정보",
    "eligibility_matrix": "참가 자격 matrix",
    "scope_deliverables": "범위·산출물",
    "requirements_matrix": "요구사항 대응 matrix",
    "evaluation_strategy": "평가·배점 matrix와 제안 전략",
    "delivery_plan": "수행 계획 초안",
    "technical_integration_risks": "기술·연계 위험",
    "security_legal_contract_risks": "보안·법률·계약 위험",
    "economics_scenarios": "경제성 시나리오",
    "competitive_proposal_strategy": "경쟁·제안 전략",
    "questions_internal_actions": "질문·내부 조치",
    "document_bundle_limitations": "문서 묶음·한계",
    "decision_card": "의사결정 카드",
}
SECTION_TOKENS = {
    "eligibility_matrix": ("elig", "자격", "qualification"),
    "scope_deliverables": ("scope", "deliver", "범위", "산출"),
    "requirements_matrix": ("require", "요구"),
    "evaluation_strategy": ("evaluat", "평가", "배점"),
    "delivery_plan": ("deliver", "수행", "계획"),
    "technical_integration_risks": ("technical", "integration", "기술", "연계"),
    "security_legal_contract_risks": ("security", "legal", "contract", "보안", "법률", "계약"),
    "economics_scenarios": ("economic", "econom", "금액", "경제"),
    "competitive_proposal_strategy": ("competitive", "proposal", "경쟁", "제안"),
    "questions_internal_actions": ("question", "action", "질문", "조치"),
    "document_bundle_limitations": ("document", "bundle", "limit", "문서", "한계"),
    "project_overview": ("project", "overview", "프로젝트", "기본"),
}


class ReportServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, request_id: UUID | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_str(value: UUID | str) -> str:
    return str(value)


def _unique(values: Iterable[UUID | str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _error(code: str, message: str, *, status_code: int = 400, request_id: UUID | None = None) -> ReportServiceError:
    return ReportServiceError(code, message, status_code=status_code, request_id=request_id)


class ReportService:
    """Own report snapshots and validation/opinion history in short txns."""

    def get_report(self, session: Session, review_id: UUID) -> dict[str, Any]:
        """Read a report that was already materialized by the worker.

        API #11 is deliberately read-only.  Report creation belongs to the
        fenced worker transaction between stage 3 persistence and
        ``_finish_claim``; a browser GET must never create a machine revision
        as a side effect.
        """

        review = session.scalar(select(DeepReview).where(DeepReview.id == review_id))
        if review is None:
            raise _error("not_found", "deep review를 찾을 수 없습니다", status_code=404)
        attempt, _stages = self._completed_attempt(session, review)
        machine_revision = self._machine_revision_for_attempt(session, review, attempt.id)
        if machine_revision is None:
            raise _error("review_not_ready", "machine report가 아직 준비되지 않았습니다", status_code=409)
        revision = session.scalar(select(ReportRevision).where(
            ReportRevision.deep_review_id == review.id,
        ).order_by(ReportRevision.sequence.desc()).limit(1))
        if revision is None:
            raise _error("review_not_ready", "현재 report revision이 아직 준비되지 않았습니다", status_code=409)
        return self._view(session, review.id, revision.id)

    def materialize_machine_report(self, session: Session, claim: JobClaim) -> dict[str, Any]:
        """Materialize the first report while the T5 lease fence is held.

        T7 calls this after stage 3 has committed and immediately before
        ``DeepReviewService._finish_claim``.  This method intentionally does
        not commit: the report, validation, evidence joins, audit row, and the
        subsequent fenced job/attempt/review completion are one transaction.
        """

        try:
            job = session.scalar(select(WorkJob).where(WorkJob.id == claim.job_id).with_for_update())
            review = session.scalar(select(DeepReview).where(DeepReview.id == claim.deep_review_id).with_for_update())
            attempt = session.scalar(select(DeepReviewAttempt).where(DeepReviewAttempt.id == claim.attempt_id).with_for_update())
            if (
                job is None
                or review is None
                or attempt is None
                or job.job_type != "deep_review"
                or job.aggregate_type != "deep_review"
                or job.aggregate_id != review.id
                or job.status != "running"
                or job.lease_owner != claim.worker_id
                or int(job.lease_fence) != int(claim.fence)
                or job.lease_expires_at is None
                or job.lease_expires_at <= _now()
                or review.id != claim.deep_review_id
                or review.current_attempt_id != attempt.id
                or review.status != "running"
                or attempt.deep_review_id != review.id
                or attempt.work_job_id != job.id
                or attempt.status != "running"
                or int(attempt.lease_fence) != int(claim.fence)
            ):
                session.rollback()
                raise StaleFenceError()

            stages = session.scalars(select(DeepReviewStage).where(
                DeepReviewStage.attempt_id == attempt.id,
            ).order_by(DeepReviewStage.sequence.asc()).with_for_update()).all()
            if len(stages) != 3 or tuple(stage.stage for stage in stages) != STAGE_NAMES or any(stage.status != "completed" or stage.completed_at is None for stage in stages):
                session.rollback()
                raise StaleFenceError()

            existing = self._machine_revision_for_attempt(session, review, attempt.id)
            if existing is not None:
                validation = session.scalar(select(ValidationRun).where(
                    ValidationRun.deep_review_id == review.id,
                    ValidationRun.report_revision_id == existing.id,
                ).order_by(ValidationRun.sequence.asc()).limit(1))
                if validation is None:
                    session.rollback()
                    raise _error("processing_failed", "machine report validation이 없습니다", status_code=500)
                self._add_machine_audit_if_missing(session, claim, review, existing, validation)
                return self._view(session, review.id, session.scalar(select(ReportRevision.id).where(
                    ReportRevision.deep_review_id == review.id,
                ).order_by(ReportRevision.sequence.desc()).limit(1)) or existing.id)

            report, stage_payloads, evidence_payloads, contexts = self._initial_report_projection(session, review, attempt, stages)
            self._validate_submitted_report(report, review, stage_payloads, evidence_payloads, contexts, None)
            evidence_ids = [_uuid(item["evidence_id"]) for item in evidence_payloads]
            revision = self._insert_revision_and_validation(
                session,
                review,
                report,
                stage_payloads=stage_payloads,
                evidence_payloads=evidence_payloads,
                contexts=contexts,
                origin="machine",
                parent_revision_id=None,
                reason=None,
                actor=None,
                evidence_ids=evidence_ids,
            )
            validation = session.scalar(select(ValidationRun).where(
                ValidationRun.deep_review_id == review.id,
                ValidationRun.report_revision_id == revision.id,
            ).order_by(ValidationRun.sequence.asc()).limit(1))
            if validation is None:
                raise _error("processing_failed", "machine report validation을 만들 수 없습니다", status_code=500)
            self._add_machine_audit_if_missing(session, claim, review, revision, validation)
            return self._view(session, review.id, revision.id)
        except StaleFenceError:
            session.rollback()
            raise
        except ReportServiceError:
            raise

    def create_revision(self, session: Session, review_id: UUID, actor: str | None, payload: ReportRevisionRequest) -> dict[str, Any]:
        claimed_name = self._validate_actor(actor, payload.request_id)
        request_hash = _hash({
            "base_revision_id": str(payload.base_revision_id),
            "report": payload.report.model_dump(mode="json"),
            "reason": payload.reason,
            "factual_change_evidence_ids": [str(item) for item in payload.factual_change_evidence_ids],
        })
        try:
            review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
            if review is None:
                raise _error("not_found", "deep review를 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            duplicate = self._idempotent(session, "deep_review_report_revision", review_id, claimed_name, payload.request_id, request_hash)
            if duplicate is not None:
                session.commit()
                return duplicate
            current = session.scalar(select(ReportRevision).where(
                ReportRevision.deep_review_id == review.id,
            ).order_by(ReportRevision.sequence.desc()).limit(1))
            if current is None or current.id != payload.base_revision_id:
                raise _error("version_conflict", "현재 report revision이 변경되었습니다", status_code=409, request_id=payload.request_id)
            if payload.report.deep_review_id != review.id:
                raise _error("validation_failed", "report가 deep review 범위와 일치하지 않습니다", status_code=422, request_id=payload.request_id)
            new_payload = payload.report.model_dump(mode="json")
            old_payload = current.report_payload if isinstance(current.report_payload, Mapping) else {}
            if new_payload.get("system_recommendation") != old_payload.get("system_recommendation"):
                raise _error("validation_failed", "system recommendation은 base revision에서 변경할 수 없습니다", status_code=409, request_id=payload.request_id)
            current_validation = session.scalar(select(ValidationRun).where(
                ValidationRun.deep_review_id == review.id,
                ValidationRun.report_revision_id == current.id,
            ).order_by(ValidationRun.sequence.desc()).limit(1))
            if current_validation is not None and current_validation.status == "failed" and new_payload.get("validation_summary", {}).get("status") != "failed":
                raise _error("validation_failed", "validation 실패 label은 후속 revision에서 통과로 바꿀 수 없습니다", status_code=409, request_id=payload.request_id)
            changed = self._factual_projection(new_payload) != self._factual_projection(old_payload)
            requested_evidence_ids = list(payload.factual_change_evidence_ids)
            if len(set(requested_evidence_ids)) != len(requested_evidence_ids):
                raise _error("evidence_out_of_scope", "factual change evidence ID가 중복되었습니다", status_code=403, request_id=payload.request_id)
            evidence_ids = requested_evidence_ids
            if changed and not evidence_ids:
                raise _error("factual_change_evidence_required", "사실을 바꾸는 revision에는 범위 내 evidence가 필요합니다", status_code=400, request_id=payload.request_id)
            linked_evidence_ids = [*(_uuid(item) for item in evidence_ids), *(_uuid(item) for item in new_payload_evidence_ids(new_payload))]
            if linked_evidence_ids:
                self._require_in_scope_evidence(session, review, list(dict.fromkeys(linked_evidence_ids)), request_id=payload.request_id)
            attempt, stages = self._completed_attempt(session, review)
            stage_payloads, all_evidence, contexts = self._stage_projection(session, review, attempt, stages)
            self._validate_submitted_report(new_payload, review, stage_payloads, all_evidence, contexts, payload.request_id)
            revision = self._insert_revision_and_validation(
                session,
                review,
                new_payload,
                stage_payloads=stage_payloads,
                evidence_payloads=all_evidence,
                contexts=contexts,
                origin="human",
                parent_revision_id=current.id,
                reason=payload.reason,
                actor=claimed_name,
                evidence_ids=evidence_ids or [_uuid(item["evidence_id"]) for item in all_evidence if str(item["evidence_id"]) in _unique(new_payload_evidence_ids(new_payload))],
            )
            validation = session.scalar(select(ValidationRun).where(
                ValidationRun.deep_review_id == review.id,
                ValidationRun.report_revision_id == revision.id,
            ).order_by(ValidationRun.sequence.asc()).limit(1))
            if validation is None:
                raise _error("processing_failed", "report validation을 만들 수 없습니다", status_code=500, request_id=payload.request_id)
            self._add_human_revision_audit(session, review, revision, validation, claimed_name, payload.request_id)
            response = self._view(session, review.id, revision.id)
            session.add(IdempotencyRecord(
                operation="deep_review_report_revision", aggregate_type="deep_review", aggregate_id=str(review.id),
                claimed_name=claimed_name, request_id=payload.request_id, request_sha256=request_hash,
                response_status=201, response_snapshot=response,
            ))
            session.commit()
            return response
        except ReportServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            duplicate = self._idempotent(session, "deep_review_report_revision", review_id, claimed_name, payload.request_id, request_hash)
            if duplicate is not None:
                session.commit()
                return duplicate
            raise _error("version_conflict", "동시에 다른 revision이 생성되었습니다", status_code=409, request_id=payload.request_id) from exc

    def create_final_opinion(self, session: Session, review_id: UUID, actor: str | None, payload: FinalOpinionRequest) -> dict[str, Any]:
        claimed_name = self._validate_actor(actor, payload.request_id)
        request_hash = _hash(payload.model_dump(mode="json"))
        try:
            review = session.scalar(select(DeepReview).where(DeepReview.id == review_id).with_for_update())
            if review is None:
                raise _error("not_found", "deep review를 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            duplicate = self._idempotent(session, "deep_review_final_opinion", review_id, claimed_name, payload.request_id, request_hash)
            if duplicate is not None:
                session.commit()
                return duplicate
            revision = session.scalar(select(ReportRevision).where(
                ReportRevision.deep_review_id == review.id,
                ReportRevision.id == payload.report_revision_id,
            ))
            validation = session.scalar(select(ValidationRun).where(
                ValidationRun.deep_review_id == review.id,
                ValidationRun.report_revision_id == payload.report_revision_id,
                ValidationRun.id == payload.validation_run_id,
            ))
            if revision is None or validation is None:
                raise _error("not_found", "report revision 또는 validation run을 찾을 수 없습니다", status_code=404, request_id=payload.request_id)
            if payload.acknowledged_validation_failure != (validation.status == "failed"):
                raise _error("validation_failed", "validation 상태와 acknowledge가 일치하지 않습니다", status_code=409, request_id=payload.request_id)
            if not payload.reason.strip():
                raise _error("final_opinion_reason_required", "최종 의견 사유가 필요합니다", status_code=400, request_id=payload.request_id)
            sequence = int(session.scalar(select(func.max(FinalOpinion.sequence)).where(FinalOpinion.deep_review_id == review.id)) or 0) + 1
            opinion = FinalOpinion(
                id=uuid4(), deep_review_id=review.id, report_revision_id=revision.id, sequence=sequence,
                value=payload.value, reason=payload.reason, validation_run_id=validation.id,
                validation_status_at_opinion=validation.status,
                acknowledged_validation_failure=payload.acknowledged_validation_failure,
                claimed_name=claimed_name,
            )
            session.add(opinion)
            session.flush()
            response = self._opinion_view(opinion)
            session.add(AuditEvent(
                actor_kind="human", claimed_name=claimed_name,
                action="deep_review.final_opinion.created",
                aggregate_type="deep_review", aggregate_id=str(review.id),
                request_id=str(payload.request_id),
                safe_metadata={
                    "review_id": str(review.id), "opinion_id": str(opinion.id),
                    "report_revision_id": str(revision.id), "validation_run_id": str(validation.id),
                    "sequence": opinion.sequence, "validation_status": validation.status,
                    "status": "succeeded",
                },
            ))
            session.add(IdempotencyRecord(
                operation="deep_review_final_opinion", aggregate_type="deep_review", aggregate_id=str(review.id),
                claimed_name=claimed_name, request_id=payload.request_id, request_sha256=request_hash,
                response_status=201, response_snapshot=response,
            ))
            session.commit()
            return response
        except ReportServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            duplicate = self._idempotent(session, "deep_review_final_opinion", review_id, claimed_name, payload.request_id, request_hash)
            if duplicate is not None:
                session.commit()
                return duplicate
            raise _error("version_conflict", "동시에 다른 최종 의견이 생성되었습니다", status_code=409, request_id=payload.request_id) from exc

    def _idempotent(self, session: Session, operation: str, review_id: UUID, actor: str, request_id: UUID, request_hash: str) -> dict[str, Any] | None:
        row = session.scalar(select(IdempotencyRecord).where(
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.aggregate_type == "deep_review",
            IdempotencyRecord.aggregate_id == str(review_id),
            IdempotencyRecord.claimed_name == actor,
            IdempotencyRecord.request_id == request_id,
        ))
        if row is None:
            return None
        if row.request_sha256 != request_hash:
            raise _error("idempotency_conflict", "같은 request_id가 다른 요청에 사용되었습니다", status_code=409, request_id=request_id)
        return dict(row.response_snapshot) if isinstance(row.response_snapshot, Mapping) else None

    @staticmethod
    def _validate_actor(actor: str | None, request_id: UUID) -> str:
        try:
            return validate_actor(actor)
        except BundleServiceError as error:
            raise _error(error.code, error.message, status_code=error.status_code, request_id=request_id) from error

    def _completed_attempt(self, session: Session, review: DeepReview) -> tuple[DeepReviewAttempt, list[DeepReviewStage]]:
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id) if review.current_attempt_id else None
        if attempt is None or attempt.deep_review_id != review.id or attempt.status != "completed" or attempt.completed_at is None:
            raise _error("review_not_ready", "완료된 deep review attempt가 필요합니다", status_code=409)
        stages = session.scalars(select(DeepReviewStage).where(
            DeepReviewStage.attempt_id == attempt.id,
        ).order_by(DeepReviewStage.sequence.asc())).all()
        if len(stages) != 3 or tuple(stage.stage for stage in stages) != STAGE_NAMES or any(stage.status != "completed" or stage.completed_at is None for stage in stages):
            raise _error("review_not_ready", "세 단계 분석이 모두 완료되지 않았습니다", status_code=409)
        return attempt, stages

    def _machine_revision_for_attempt(self, session: Session, review: DeepReview, attempt_id: UUID) -> ReportRevision | None:
        """Resolve the machine revision through its same-transaction audit."""

        audits = session.scalars(select(AuditEvent).where(
            AuditEvent.action == "deep_review.report.machine_materialized",
            AuditEvent.aggregate_type == "deep_review",
            AuditEvent.aggregate_id == str(review.id),
        ).order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())).all()
        revision_ids = [
            _uuid(row.safe_metadata["revision_id"])
            for row in audits
            if isinstance(row.safe_metadata, Mapping)
            and str(row.safe_metadata.get("attempt_id")) == str(attempt_id)
            and row.safe_metadata.get("revision_id")
        ]
        if not revision_ids:
            return None
        revision = session.scalar(select(ReportRevision).where(
            ReportRevision.deep_review_id == review.id,
            ReportRevision.id == revision_ids[-1],
            ReportRevision.origin == "machine",
        ))
        return revision

    def _initial_report_projection(self, session: Session, review: DeepReview, attempt: DeepReviewAttempt, stages: Sequence[DeepReviewStage]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        stage_payloads, evidence_payloads, contexts = self._stage_projection(session, review, attempt, stages)
        claim_payloads = self._claims(session, review.id, stages)
        if not claim_payloads:
            raise _error("review_not_ready", "완료된 분석 claim projection이 없습니다", status_code=409)
        unknowns: list[str] = []
        for payload in stage_payloads:
            for value in payload.get("unknowns", []):
                if isinstance(value, str) and value not in unknowns:
                    unknowns.append(value)
        failed_claims = [claim for claim in claim_payloads if claim["status"] in {"unsupported", "conflicting"}]
        status = "failed" if failed_claims else "passed"
        report = self._render_report(review, claim_payloads, unknowns, status)
        return report, stage_payloads, evidence_payloads, contexts

    def _claims(self, session: Session, review_id: UUID, stages: Sequence[DeepReviewStage]) -> list[dict[str, Any]]:
        stage_ids = [stage.id for stage in stages]
        claims = session.scalars(select(Claim).where(
            Claim.deep_review_id == review_id,
            Claim.stage_id.in_(stage_ids),
        ).order_by(Claim.stage_id.asc(), Claim.id.asc())).all()
        result: list[dict[str, Any]] = []
        for claim in claims:
            evidence_ids = session.scalars(select(ClaimEvidence.evidence_ref_id).where(
                ClaimEvidence.deep_review_id == review_id,
                ClaimEvidence.claim_id == claim.id,
            ).order_by(ClaimEvidence.ordinal.asc())).all()
            result.append({
                "claim_id": str(claim.id), "category": claim.category, "claim_type": claim.claim_type,
                "body": claim.body, "status": claim.status, "formula": claim.formula,
                "premise_claim_ids": [str(item) for item in (claim.premise_claim_ids if isinstance(claim.premise_claim_ids, list) else [])],
                "reason": claim.reason, "evidence_ids": [str(item) for item in evidence_ids],
            })
        return result

    def _evidence(self, session: Session, review_id: UUID, evidence_ids: Iterable[UUID | str] | None = None) -> list[dict[str, Any]]:
        statement = select(EvidenceRef).where(EvidenceRef.deep_review_id == review_id).order_by(EvidenceRef.id.asc())
        if evidence_ids is not None:
            values = [_uuid(item) for item in evidence_ids]
            statement = statement.where(EvidenceRef.id.in_(values)) if values else statement.where(EvidenceRef.id == UUID(int=0))
        rows = session.scalars(statement).all()
        if evidence_ids is not None and len(rows) != len(values):
            raise _error("evidence_out_of_scope", "report가 심층 검토 범위 밖의 evidence를 참조합니다", status_code=403)
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append({
                "evidence_id": str(row.id), "source_kind": row.source_kind,
                "document_version_id": str(row.document_version_id) if row.document_version_id else None,
                "structure_id": str(row.structure_id) if row.structure_id else None,
                "profile_version_id": str(row.profile_version_id) if row.profile_version_id else None,
                "profile_evidence_id": str(row.profile_evidence_id) if row.profile_evidence_id else None,
                "locator_type": row.locator_type, "locator": dict(row.locator) if isinstance(row.locator, Mapping) else {},
                "quote": row.quote or "", "confidence": float(row.confidence) if row.confidence is not None else None,
                "source_sha256": row.source_sha256,
            })
        return result

    def _stage_projection(self, session: Session, review: DeepReview, attempt: DeepReviewAttempt, stages: Sequence[DeepReviewStage]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        claims = self._claims(session, review.id, stages)
        claim_ids = {item["claim_id"] for item in claims}
        evidence_ids = _unique(item for claim in claims for item in claim["evidence_ids"])
        evidence = self._evidence(session, review.id, evidence_ids)
        evidence_by_id = {item["evidence_id"]: item for item in evidence}
        stage_payloads: list[dict[str, Any]] = []
        for stage in stages:
            raw = stage.structured_output if isinstance(stage.structured_output, Mapping) else {}
            stage_claims = [item for item in claims if self._claim_stage(session, item["claim_id"]) == stage.id]
            stage_evidence = [item for item in evidence if any(item["evidence_id"] in claim["evidence_ids"] for claim in stage_claims)]
            stage_payloads.append({
                "schema": "bidops.deep-review-stage.v1", "deep_review_id": str(review.id),
                "attempt_id": str(attempt.id), "stage": stage.stage, "claims": stage_claims,
                "evidence": stage_evidence,
                "unknowns": [item for item in raw.get("unknowns", []) if isinstance(item, str)] if isinstance(raw.get("unknowns"), list) else [],
                "warnings": [item for item in raw.get("warnings", []) if isinstance(item, str)] if isinstance(raw.get("warnings"), list) else [],
            })
        return stage_payloads, evidence, self._contexts(session, review, evidence_by_id)

    def _claim_stage(self, session: Session, claim_id: str) -> UUID | None:
        return session.scalar(select(Claim.stage_id).where(Claim.id == _uuid(claim_id)))

    def _contexts(self, session: Session, review: DeepReview, evidence_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        bundle = session.get(DocumentBundle, review.bundle_id)
        items = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == review.bundle_id).order_by(DocumentBundleItem.ordinal.asc())).all()
        bundle_context: dict[str, Any] = {
            "bundle_id": str(review.bundle_id), "notice_id": review.notice_id,
            "status": bundle.status if bundle else "unknown",
            "documents": [{
                "document_version_id": str(item.document_version_id), "structure_id_at_confirmation": str(item.structure_id_at_confirmation),
                "content_sha256": item.content_sha256, "safety_status_at_confirmation": item.safety_status_at_confirmation,
            } for item in items],
        }
        structures: dict[str, Any] = {}
        structure_ids = {str(item["structure_id"]) for item in evidence_by_id.values() if item.get("structure_id")}
        for value in structure_ids:
            structure = session.get(DocumentStructure, _uuid(value))
            if structure is None:
                continue
            blocks = session.scalars(select(DocumentBlock).where(DocumentBlock.structure_id == structure.id).order_by(DocumentBlock.page.asc(), DocumentBlock.block_key.asc())).all()
            structures[value] = {
                "structure_id": str(structure.id), "document_version_id": str(structure.document_version_id),
                "source_sha256": structure.source_sha256,
                "pages": [{"number": number} for number in range(1, max(structure.page_count, 1) + 1)],
                "blocks": [{
                    "block_key": block.block_key, "page": block.page, "text": block.content or "",
                    "bbox": block.bbox, "attributes": block.attributes if isinstance(block.attributes, Mapping) else {},
                } for block in blocks],
            }
        profile = session.get(ProfileVersion, review.profile_version_id)
        profile_payload = profile.profile_payload if profile and isinstance(profile.profile_payload, Mapping) else {}
        profile_rows = session.scalars(select(ProfileEvidence).where(ProfileEvidence.profile_version_id == review.profile_version_id).order_by(ProfileEvidence.id.asc())).all()
        profile_context: dict[str, Any] = {
            "profile_version_id": str(review.profile_version_id),
            "facts": profile_payload.get("facts", []) if isinstance(profile_payload.get("facts"), list) else [],
            "evidence": [{
                "profile_evidence_id": str(row.id), "profile_version_id": str(row.profile_version_id), "fact_key": row.fact_key,
                "source_sha256": row.source_sha256, "locator_type": row.locator_type,
                "locator": row.locator if isinstance(row.locator, Mapping) else {}, "quote": row.quote,
            } for row in profile_rows],
        }
        return {"bundle": bundle_context, "profile": profile_context, "structures": structures}

    def _render_report(self, review: DeepReview, claims: list[dict[str, Any]], unknowns: list[str], validation_status: str) -> dict[str, Any]:
        all_ids = [claim["claim_id"] for claim in claims]
        sections: list[dict[str, Any]] = []
        matrix_sections = {"eligibility_matrix", "requirements_matrix", "evaluation_strategy"}
        plan_sections = {"delivery_plan", "questions_internal_actions"}
        scenario_sections = {"economics_scenarios"}
        for section_key in REQUIRED_SECTIONS:
            selected = self._section_claims(section_key, claims) or claims
            selected_ids = [claim["claim_id"] for claim in selected]
            first_body = selected[0]["body"] if selected else None
            decision_rows: list[dict[str, Any]] = []
            if section_key == "decision_card":
                recommendation = "보류" if validation_status == "failed" else "추진 검토"
                failed = [claim for claim in selected if claim.get("status") in {"unsupported", "conflicting"}]
                body = f"시스템 권고: {recommendation}. 핵심 근거, 차단 위험, 미확인 사항과 다음 조치를 연결된 claim에서 확인하십시오."
                block_type = "decision_card"
                decision_rows = [
                    {"row_key": "decision-card-core-evidence", "label": "핵심 근거", "cells": [claim["body"] for claim in selected] or ["연결된 핵심 근거가 없습니다."], "claim_ids": selected_ids},
                    {"row_key": "decision-card-blocking-risks", "label": "차단 위험", "cells": [claim["body"] for claim in failed] or ["확인된 차단 위험이 없습니다."], "claim_ids": [claim["claim_id"] for claim in failed] or selected_ids},
                    {"row_key": "decision-card-unknowns", "label": "미확인 사항", "cells": unknowns or ["미확인 사항이 없습니다."], "claim_ids": selected_ids},
                    {"row_key": "decision-card-next-actions", "label": "다음 조치", "cells": ["validation 결과와 연결된 근거를 확인한 뒤 담당자 최종 의견을 기록합니다."], "claim_ids": selected_ids},
                ]
            elif section_key in matrix_sections:
                body = None
                block_type = "matrix"
            elif section_key in plan_sections:
                body = first_body
                block_type = "action_list"
            elif section_key in scenario_sections:
                body = first_body
                block_type = "scenario"
            else:
                body = first_body
                block_type = "paragraph"
            rows = decision_rows or [{
                "row_key": f"{section_key}-row-{index + 1:04d}", "label": claim["category"],
                "cells": [claim["body"]], "claim_ids": [claim["claim_id"]],
            } for index, claim in enumerate(selected)] if section_key in matrix_sections or section_key == "decision_card" else []
            sections.append({
                "section_key": section_key, "title": SECTION_TITLES[section_key],
                "blocks": [{
                    "block_id": f"{section_key}-block-0001", "type": block_type,
                    "title": SECTION_TITLES[section_key], "body": body,
                    "claim_ids": selected_ids, "rows": rows,
                }],
            })
        failed = 1 if validation_status == "failed" else 0
        return {
            "schema": "bidops.deep-review-report.v1", "deep_review_id": str(review.id), "notice_id": review.notice_id,
            "bundle_id": str(review.bundle_id), "profile_version_id": str(review.profile_version_id),
            "policy_version_id": str(review.policy_version_id), "sections": sections,
            "system_recommendation": "보류" if validation_status == "failed" else "추진 검토",
            "claims": claims, "unknowns": unknowns,
            "validation_summary": {"status": validation_status, "failed": failed, "warnings": len(unknowns), "passed": 1 - failed},
            "created_at": _iso(_now()),
        }

    def _section_claims(self, section_key: str, claims: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        tokens = SECTION_TOKENS.get(section_key, ())
        return [claim for claim in claims if any(token.casefold() in str(claim.get("category", "")).casefold() for token in tokens)]

    def _validate_submitted_report(self, payload: Mapping[str, Any], review: DeepReview, stages: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], contexts: Mapping[str, Any], request_id: UUID | None) -> None:
        try:
            validate_deep_review_report(
                payload,
                bundle=contexts["bundle"], profile=contexts["profile"], evidence=evidence,
                stages=stages, expected_deep_review_id=str(review.id), structures=contexts["structures"],
            )
        except (DeepReviewValidationError, ValueError) as error:
            raise _error("validation_failed", "report validation을 통과하지 못했습니다", status_code=409, request_id=request_id) from error

    def _insert_revision_and_validation(self, session: Session, review: DeepReview, report: Mapping[str, Any], *, stage_payloads: Sequence[Mapping[str, Any]], evidence_payloads: Sequence[Mapping[str, Any]], contexts: Mapping[str, Any], origin: str, parent_revision_id: UUID | None, reason: str | None, actor: str | None, evidence_ids: Sequence[UUID]) -> ReportRevision:
        """Prepare and validate every payload before the first INSERT.

        ``revision_id`` and ``validation_run_id`` are allocated up front so
        the validated wire payload and the persisted row share exactly one
        validation UUID.
        """

        self._validate_submitted_report(report, review, stage_payloads, evidence_payloads, contexts, None)
        linked = list(dict.fromkeys([*evidence_ids, *(_uuid(item) for item in new_payload_evidence_ids(report))]))
        self._require_in_scope_evidence(session, review, linked, request_id=None)
        revision_id = uuid4()
        validation_id = uuid4()
        validation_status, checks, validation_payload = self._validation_result(
            report, revision_id, validation_id, review, stage_payloads, evidence_payloads, contexts,
        )
        sequence = int(session.scalar(select(func.max(ReportRevision.sequence)).where(ReportRevision.deep_review_id == review.id)) or 0) + 1
        revision = ReportRevision(
            id=revision_id, deep_review_id=review.id, sequence=sequence, parent_revision_id=parent_revision_id,
            origin=origin, report_payload=dict(report), report_sha256=_hash(report), change_reason=reason,
            created_by_name=actor,
        )
        session.add(revision)
        session.flush()
        for evidence_id in linked:
            session.add(ReportRevisionEvidence(deep_review_id=review.id, report_revision_id=revision.id, evidence_ref_id=evidence_id))
        run_sequence = int(session.scalar(select(func.max(ValidationRun.sequence)).where(ValidationRun.deep_review_id == review.id)) or 0) + 1
        run = ValidationRun(id=validation_id, deep_review_id=review.id, report_revision_id=revision.id, sequence=run_sequence, status=validation_status)
        session.add(run)
        session.flush()
        for check in checks:
            session.add(ValidationCheck(
                id=uuid4(), validation_run_id=run.id, check_type=check["check_type"], status=check["status"],
                severity=check["severity"], message=check["message"],
                related_claim_ids=check["related_claim_ids"], related_evidence_ids=check["related_evidence_ids"],
            ))
        # Keep the local variable visible to reviewers and static analyzers:
        # this is the exact validation payload whose UUID was persisted above.
        if validation_payload["validation_run_id"] != str(run.id):
            raise _error("processing_failed", "validation run 식별자가 일치하지 않습니다", status_code=500)
        return revision

    def _validation_result(self, report: Mapping[str, Any], revision_id: UUID, validation_id: UUID, review: DeepReview, stages: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], contexts: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        failed_ids = [str(claim["claim_id"]) for claim in report.get("claims", []) if claim.get("status") in {"unsupported", "conflicting"}]
        summary = report.get("validation_summary", {})
        declared_failed = summary.get("status") == "failed" and int(summary.get("failed", 0) or 0) > 0
        status = "failed" if failed_ids or declared_failed else "passed"
        checks: list[dict[str, Any]] = []
        if failed_ids:
            checks.append({"check_type": "claim_support", "status": "failed", "severity": "중대", "message": "근거가 부족하거나 충돌하는 claim이 있습니다", "related_claim_ids": failed_ids, "related_evidence_ids": []})
        elif declared_failed:
            checks.append({"check_type": "declared_validation", "status": "failed", "severity": "중대", "message": "report가 validation failed 상태를 보존합니다", "related_claim_ids": [], "related_evidence_ids": []})
        else:
            checks.append({"check_type": "report_contract", "status": "passed", "severity": "낮음", "message": "전체 report contract와 immutable projection을 확인했습니다", "related_claim_ids": [], "related_evidence_ids": []})
        validation_payload = {
            "schema": "bidops.deep-review-validation.v1", "validation_run_id": str(validation_id),
            "report_revision_id": str(revision_id), "status": status, "checks": checks, "created_at": _iso(_now()),
        }
        if report.get("validation_summary", {}).get("status") != status:
            raise _error("validation_failed", "report validation_summary가 결정적 validation 상태와 다릅니다", status_code=409)
        try:
            validate_deep_review_validation(validation_payload, expected_report_revision_id=str(revision_id), expected_deep_review_id=str(review.id), claim_ids=[str(claim["claim_id"]) for claim in report.get("claims", [])], evidence_ids=[str(item["evidence_id"]) for item in evidence])
        except (DeepReviewValidationError, ValueError) as error:
            raise _error("validation_failed", "validation contract를 통과하지 못했습니다", status_code=409) from error
        return status, checks, validation_payload

    def _require_in_scope_evidence(self, session: Session, review: DeepReview, evidence_ids: Sequence[UUID], *, request_id: UUID | None) -> None:
        if len(set(evidence_ids)) != len(evidence_ids):
            raise _error("evidence_out_of_scope", "factual change evidence ID가 중복되었습니다", status_code=403, request_id=request_id)
        if not evidence_ids:
            return
        rows = session.scalars(select(EvidenceRef).where(EvidenceRef.deep_review_id == review.id, EvidenceRef.id.in_(list(evidence_ids)))).all()
        if len(rows) != len(evidence_ids):
            raise _error("evidence_out_of_scope", "다른 deep review의 evidence는 사용할 수 없습니다", status_code=403, request_id=request_id)

    @staticmethod
    def _factual_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the report fields whose change alters a factual snapshot.

        Section/block titles and row labels are presentation-only.  Claim
        content, evidence links, decision-card content, unknowns, and the
        deterministic validation summary remain factual and therefore require
        explicit in-scope evidence when changed.
        """

        projected = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        projected.pop("created_at", None)
        for section in projected.get("sections", []):
            if isinstance(section, Mapping):
                section.pop("title", None)
                for block in section.get("blocks", []):
                    if isinstance(block, Mapping):
                        block.pop("title", None)
                        for row in block.get("rows", []):
                            if isinstance(row, Mapping):
                                row.pop("label", None)
        return projected

    @staticmethod
    def _audit_exists(session: Session, *, action: str, aggregate_id: UUID, metadata_key: str, metadata_value: str) -> bool:
        rows = session.scalars(select(AuditEvent).where(
            AuditEvent.action == action,
            AuditEvent.aggregate_type == "deep_review",
            AuditEvent.aggregate_id == str(aggregate_id),
        )).all()
        return any(
            isinstance(row.safe_metadata, Mapping)
            and str(row.safe_metadata.get(metadata_key)) == metadata_value
            for row in rows
        )

    def _add_machine_audit_if_missing(self, session: Session, claim: JobClaim, review: DeepReview, revision: ReportRevision, validation: ValidationRun) -> None:
        if self._audit_exists(
            session,
            action="deep_review.report.machine_materialized",
            aggregate_id=review.id,
            metadata_key="revision_id",
            metadata_value=str(revision.id),
        ):
            return
        session.add(AuditEvent(
            actor_kind="system", claimed_name=None,
            action="deep_review.report.machine_materialized",
            aggregate_type="deep_review", aggregate_id=str(review.id), request_id=None,
            safe_metadata={
                "job_id": str(claim.job_id), "review_id": str(review.id),
                "attempt_id": str(claim.attempt_id), "lease_fence": int(claim.fence),
                "revision_id": str(revision.id), "sequence": int(revision.sequence),
                "report_sha256": revision.report_sha256,
                "validation_run_id": str(validation.id), "validation_status": validation.status,
                "status": "succeeded",
            },
        ))

    def _add_human_revision_audit(self, session: Session, review: DeepReview, revision: ReportRevision, validation: ValidationRun, claimed_name: str, request_id: UUID) -> None:
        if self._audit_exists(
            session,
            action="deep_review.report_revision.created",
            aggregate_id=review.id,
            metadata_key="revision_id",
            metadata_value=str(revision.id),
        ):
            return
        session.add(AuditEvent(
            actor_kind="human", claimed_name=claimed_name,
            action="deep_review.report_revision.created",
            aggregate_type="deep_review", aggregate_id=str(review.id), request_id=str(request_id),
            safe_metadata={
                "review_id": str(review.id), "revision_id": str(revision.id),
                "parent_revision_id": str(revision.parent_revision_id),
                "sequence": int(revision.sequence), "report_sha256": revision.report_sha256,
                "validation_run_id": str(validation.id), "validation_status": validation.status,
                "status": "succeeded",
            },
        ))

    def _view(self, session: Session, review_id: UUID, revision_id: UUID) -> dict[str, Any]:
        revision = session.get(ReportRevision, revision_id)
        if revision is None:
            raise _error("not_found", "report revision을 찾을 수 없습니다", status_code=404)
        validation = session.scalar(select(ValidationRun).where(
            ValidationRun.deep_review_id == review_id, ValidationRun.report_revision_id == revision.id,
        ).order_by(ValidationRun.sequence.desc()).limit(1))
        if validation is None:
            raise _error("review_not_ready", "report validation이 아직 없습니다", status_code=409)
        checks = session.scalars(select(ValidationCheck).where(ValidationCheck.validation_run_id == validation.id).order_by(ValidationCheck.id.asc())).all()
        validation_view = {
            "schema": "bidops.deep-review-validation.v1", "validation_run_id": str(validation.id),
            "report_revision_id": str(revision.id), "status": validation.status,
            "checks": [{
                "check_type": check.check_type, "status": check.status, "severity": check.severity,
                "message": check.message, "related_claim_ids": [str(item) for item in (check.related_claim_ids if isinstance(check.related_claim_ids, list) else [])],
                "related_evidence_ids": [str(item) for item in (check.related_evidence_ids if isinstance(check.related_evidence_ids, list) else [])],
            } for check in checks], "created_at": _iso(validation.created_at),
        }
        revisions = session.scalars(select(ReportRevision).where(ReportRevision.deep_review_id == review_id).order_by(ReportRevision.sequence.asc())).all()
        history: list[dict[str, Any]] = []
        for row in revisions:
            run = session.scalar(select(ValidationRun).where(
                ValidationRun.deep_review_id == review_id, ValidationRun.report_revision_id == row.id,
            ).order_by(ValidationRun.sequence.desc()).limit(1))
            history.append({"revision_id": str(row.id), "sequence": row.sequence, "origin": row.origin, "validation_status": run.status if run else None, "created_by_name": row.created_by_name, "created_at": _iso(row.created_at)})
        opinion = session.scalar(select(FinalOpinion).where(
            FinalOpinion.deep_review_id == review_id, FinalOpinion.report_revision_id == revision.id,
        ).order_by(FinalOpinion.sequence.desc()).limit(1))
        return {
            "deep_review_id": str(review_id), "current_revision_id": str(revision.id),
            "report": revision.report_payload, "validation": validation_view, "history": history,
            "final_opinion": self._opinion_view(opinion) if opinion else None,
        }

    @staticmethod
    def _opinion_view(opinion: FinalOpinion | None) -> dict[str, Any] | None:
        if opinion is None:
            return None
        return {
            "id": str(opinion.id), "sequence": opinion.sequence, "value": opinion.value,
            "reason": opinion.reason, "validation_status_at_opinion": opinion.validation_status_at_opinion,
            "acknowledged_validation_failure": opinion.acknowledged_validation_failure,
            "claimed_name": opinion.claimed_name, "created_at": _iso(opinion.created_at),
        }


def new_payload_evidence_ids(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for claim in payload.get("claims", []):
        if isinstance(claim, Mapping):
            values.extend(str(item) for item in claim.get("evidence_ids", []) if item)
    return _unique(values)


__all__ = ["ReportService", "ReportServiceError"]
