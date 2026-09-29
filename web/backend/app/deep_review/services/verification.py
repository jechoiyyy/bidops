"""Immutable, per-attempt selection of optional source content checks."""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...core.models import AuditEvent
from ..models import Claim, ClaimEvidence, DeepReviewStage, DeepReviewAttempt, DeepReview, AnalysisPolicyVersion

ACTION = "deep_review.source_verification_selected"
NOT_PERFORMED = "원문 인용·숫자 대조를 끈 실행입니다. 본문의 인용과 수치는 원문을 직접 확인하십시오."


def enabled_for_attempt(session: Session, attempt_id: UUID) -> bool:
    if not result_checks_for_attempt(session, attempt_id):
        return False
    rows = session.scalars(select(AuditEvent).where(
        AuditEvent.action == ACTION, AuditEvent.aggregate_type == "deep_review_attempt",
        AuditEvent.aggregate_id == str(attempt_id),
    )).all()
    if not rows:
        return True  # Earlier attempts always ran these checks.
    if len(rows) != 1 or type(rows[0].safe_metadata.get("enabled")) is not bool:
        raise ValueError("source_verification_snapshot_invalid")
    return rows[0].safe_metadata["enabled"]


def record_selection(session: Session, attempt_id: UUID, enabled: bool, actor: str, actor_kind: str = "human") -> None:
    if type(enabled) is not bool:
        raise ValueError("source_verification_setting_invalid")
    session.add(AuditEvent(actor_kind=actor_kind, claimed_name=actor, action=ACTION,
        aggregate_type="deep_review_attempt", aggregate_id=str(attempt_id),
        safe_metadata={"enabled": enabled, "scope": "source_quotes_and_numbers"}))


def enabled_for_evidence(session: Session, evidence_id: UUID) -> bool:
    attempts = session.scalars(select(DeepReviewStage.attempt_id).join(Claim, Claim.stage_id == DeepReviewStage.id)
        .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
        .where(ClaimEvidence.evidence_ref_id == evidence_id).distinct()).all()
    return all(enabled_for_attempt(session, attempt_id) for attempt_id in attempts)


def skipped_check() -> dict:
    return {"check_type": "source_verification_skipped", "status": "warning", "severity": "중대",
            "message": NOT_PERFORMED, "related_claim_ids": [], "related_evidence_ids": []}


RESULT_NOT_PERFORMED = "내용·참조 의미·누락 검증을 끈 참조 실행입니다. 인용·수치·추론·검토 범위를 직접 확인하십시오. 형식·저장 무결성 검사는 유지합니다."


def result_checks_enabled(policy: dict) -> bool:
    return policy.get("validation", {}).get("result_checks") != "disabled_reference_v1"


def result_checks_for_attempt(session: Session, attempt_id: UUID) -> bool:
    policy = session.scalar(select(AnalysisPolicyVersion).join(DeepReview, DeepReview.policy_version_id == AnalysisPolicyVersion.id)
                            .join(DeepReviewAttempt, DeepReviewAttempt.deep_review_id == DeepReview.id)
                            .where(DeepReviewAttempt.id == attempt_id))
    if policy is None:
        return True
    return result_checks_enabled(policy.validation_rules.get("policy_snapshot", {}))


def result_skipped_check() -> dict:
    return {"check_type": "result_validation_skipped", "status": "warning", "severity": "중대",
            "message": RESULT_NOT_PERFORMED, "related_claim_ids": [], "related_evidence_ids": []}
