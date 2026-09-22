"""Per-attempt consent and immutable input boundary for the Luna reference path."""
from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select

from ...core.models import AuditEvent
from ..models import DeepReviewPreview, DeepReviewApproval, DeepReview
from .input_versions import bundle_context, profile_context, canonical_json_hash, InputVersionError, effective_grade_basis
from .effective_grade import eligible_with_grade


def is_luna(policy):
    return getattr(policy, "model_endpoint_ref", None) == "codex-exec"


def snapshot(service, session, notice, bundle_id, profile, policy, verification):
    from .deep_reviews import _policy_payload, DeepReviewServiceError
    if not service.settings.luna_deep_review_enabled or not service.reference_workflow_mode or service.settings.analysis_provider == "mock":
        raise DeepReviewServiceError("service_unavailable", "Luna 참조 실행이 비활성입니다", status_code=503)
    if notice.source_type != "pre_spec":
        raise DeepReviewServiceError("invalid_request", "사전규격만 지원합니다")
    from .overview_runs import current_runs
    overview = current_runs(session, [notice.id]).get(notice.id)
    if overview is None or overview.status != "completed":
        raise DeepReviewServiceError("review_not_ready", "개요검토 완료가 필요합니다", status_code=409)
    if not eligible_with_grade(session, notice.id, effective_grade_basis(session, notice.id).grade):
        raise DeepReviewServiceError("effective_grade_ineligible", "심층검토 자격이 없습니다", status_code=403)
    bundle, structures = bundle_context(session, bundle_id, structure_loader=service.structure_loader)
    if bundle["notice_id"] != notice.id:
        raise DeepReviewServiceError("not_found", "공고와 묶음이 일치하지 않습니다", status_code=404)
    from .document_segments import inventory_context
    inventory = inventory_context(session, [UUID(str(row["structure_id_at_confirmation"])) for row in bundle["documents"]])
    return {"inventory": inventory, "schema": "bidops.luna-input.v1", "notice_id": notice.id,
            "overview_run_id": str(overview.id), "bundle": bundle, "structures": structures,
            "profile": profile_context(session, profile), "policy": _policy_payload(policy),
            "source_verification_enabled": verification}


def preview(service, session, notice_id, bundle_id, verification, review_id=None):
    from ...lifecycle import lock_notice
    from .input_versions import resolve_active_versions, validate_pinned_policy
    from ..models import ProfileVersion, AnalysisPolicyVersion
    from .deep_reviews import DeepReviewServiceError
    notice = lock_notice(session, notice_id)
    if notice is None:
        raise DeepReviewServiceError("not_found", "공고를 찾을 수 없습니다", status_code=404)
    if review_id:
        review = session.get(DeepReview, review_id)
        if review is None or review.notice_id != notice_id or review.bundle_id != bundle_id:
            raise DeepReviewServiceError("not_found", "검토를 찾을 수 없습니다", status_code=404)
        profile = session.get(ProfileVersion, review.profile_version_id)
        policy = session.get(AnalysisPolicyVersion, review.policy_version_id)
        validate_pinned_policy(policy, allow_unmeasured_reference=True)
    else:
        profile, policy = resolve_active_versions(session, allow_unmeasured_reference=True)
    if not is_luna(policy):
        raise DeepReviewServiceError("invalid_request", "Luna 정책의 새 검토가 필요합니다")
    data = snapshot(service, session, notice, bundle_id, profile, policy, verification)
    row = DeepReviewPreview(id=uuid4(), notice_id=notice_id, bundle_id=bundle_id,
                            profile_version_id=profile.id, policy_version_id=policy.id,
                            input_sha256=canonical_json_hash(data), input_snapshot=data)
    session.add(row)
    session.commit()
    return {"preview_id": str(row.id), "input_sha256": row.input_sha256,
            "provider": "codex-exec", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh",
            "quality_status": "unmeasured_reference", "source_verification_enabled": verification,
            "input": deepcopy(data)}


def check(service, session, preview_id, notice, bundle_id, profile, policy, verification):
    from .deep_reviews import DeepReviewServiceError
    row = session.get(DeepReviewPreview, preview_id) if preview_id else None
    if row is None:
        raise DeepReviewServiceError("preview_required", "전송 미리보기를 확인하십시오", status_code=409)
    current = snapshot(service, session, notice, bundle_id, profile, policy, verification)
    if (row.notice_id != notice.id or row.bundle_id != bundle_id or row.profile_version_id != profile.id
            or row.policy_version_id != policy.id or row.input_sha256 != canonical_json_hash(current)
            or row.input_sha256 != canonical_json_hash(row.input_snapshot)):
        raise DeepReviewServiceError("preview_changed", "입력이 변경되었습니다. 전송 미리보기를 다시 확인하십시오", status_code=409)
    if session.scalar(select(DeepReviewApproval.id).where(DeepReviewApproval.preview_id == row.id)):
        raise DeepReviewServiceError("preview_used", "이미 승인한 미리보기입니다", status_code=409)
    return row


def approve(session, row, attempt_id, actor, request_id):
    session.add(DeepReviewApproval(preview_id=row.id, attempt_id=attempt_id, claimed_name=actor, request_id=request_id))
    session.add(AuditEvent(actor_kind="human", claimed_name=actor, action="deep_review.external_transfer_approved",
                           aggregate_type="deep_review_attempt", aggregate_id=str(attempt_id), request_id=str(request_id),
                           safe_metadata={"preview_id": str(row.id), "input_sha256": row.input_sha256,
                                          "provider": "codex-exec", "model": "gpt-5.6-luna", "reasoning_effort": "xhigh"}))
    session.flush()


def approved_input(session, attempt_id, review):
    approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt_id))
    row = session.get(DeepReviewPreview, approval.preview_id) if approval else None
    if (row is None or row.notice_id != review.notice_id or row.bundle_id != review.bundle_id
            or row.profile_version_id != review.profile_version_id or row.policy_version_id != review.policy_version_id
            or canonical_json_hash(row.input_snapshot) != row.input_sha256):
        raise InputVersionError("approval_invalid", "승인된 동결 입력을 확인할 수 없습니다")
    return deepcopy(row.input_snapshot)
