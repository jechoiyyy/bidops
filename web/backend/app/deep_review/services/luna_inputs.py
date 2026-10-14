"""Per-attempt consent and immutable input boundary for the Luna reference path."""
from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select

from ...core.models import AuditEvent
from ..models import DeepReviewPreview, DeepReviewApproval, DeepReview
from .input_versions import bundle_context, profile_context, canonical_json_hash, InputVersionError, effective_grade_basis
from .effective_grade import eligible_with_grade
from .luna_identity import PROVIDER, matches_runtime, policy_reasoning_effort


def is_luna(policy):
    return getattr(policy, "model_endpoint_ref", None) == "codex-exec"


def require_runtime(policy):
    """Reject a pinned codex policy that the one shared runner cannot execute."""

    from .deep_reviews import DeepReviewServiceError
    if is_luna(policy) and not matches_runtime(
        getattr(policy, "model_name", None), policy_reasoning_effort(policy)
    ):
        raise DeepReviewServiceError(
            "model_binding_invalid", "심층 분석 모델 설정이 유효하지 않습니다", status_code=503
        )


def snapshot(service, session, notice, bundle_id, profile, policy, verification):
    from .deep_reviews import _policy_payload, DeepReviewServiceError
    if not service.settings.luna_deep_review_enabled or not service.reference_workflow_mode or service.settings.analysis_provider == "mock":
        raise DeepReviewServiceError("service_unavailable", "Luna 참조 실행이 비활성입니다", status_code=503)
    require_runtime(policy)
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
        # Company reviews (DEMO-03) are retried only through the company path.
        if review is None or review.company_id is not None or review.notice_id != notice_id or review.bundle_id != bundle_id:
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
            "provider": PROVIDER, "model": policy.model_name,
            "reasoning_effort": policy_reasoning_effort(policy),
            "quality_status": "unmeasured_reference", "source_verification_enabled": verification,
            "input": deepcopy(data)}


def check(service, session, preview_id, notice, bundle_id, profile, policy, verification):
    from .deep_reviews import DeepReviewServiceError
    row = session.get(DeepReviewPreview, preview_id) if preview_id else None
    if row is None:
        raise DeepReviewServiceError("preview_required", "전송 미리보기를 확인하십시오", status_code=409)
    if row.company_id is not None:
        # A company preview freezes a CompanyAnalysisInput; it is approved only
        # through the company path (demo contract §9).
        raise DeepReviewServiceError("preview_changed", "입력이 변경되었습니다. 전송 미리보기를 다시 확인하십시오", status_code=409)
    current = snapshot(service, session, notice, bundle_id, profile, policy, verification)
    if (row.notice_id != notice.id or row.bundle_id != bundle_id or row.profile_version_id != profile.id
            or row.policy_version_id != policy.id or row.input_sha256 != canonical_json_hash(current)
            or row.input_sha256 != canonical_json_hash(row.input_snapshot)):
        raise DeepReviewServiceError("preview_changed", "입력이 변경되었습니다. 전송 미리보기를 다시 확인하십시오", status_code=409)
    if session.scalar(select(DeepReviewApproval.id).where(DeepReviewApproval.preview_id == row.id)):
        raise DeepReviewServiceError("preview_used", "이미 승인한 미리보기입니다", status_code=409)
    return row


def approve(session, row, attempt_id, actor, request_id):
    # The approval carries the preview's company scope (NULL on the legacy
    # path, unchanged); company ids are added to the audit only when set.
    session.add(DeepReviewApproval(preview_id=row.id, attempt_id=attempt_id, claimed_name=actor, request_id=request_id,
                                   company_id=row.company_id))
    company = ({"company_id": str(row.company_id), "graph_version_id": str(row.graph_version_id)}
               if row.company_id is not None else {})
    from ..models import AnalysisPolicyVersion
    policy = session.get(AnalysisPolicyVersion, row.policy_version_id)
    if policy is None:
        from .deep_reviews import DeepReviewServiceError
        raise DeepReviewServiceError("model_binding_invalid", "심층 분석 모델 설정이 유효하지 않습니다", status_code=503)
    require_runtime(policy)
    session.add(AuditEvent(actor_kind="human", claimed_name=actor, action="deep_review.external_transfer_approved",
                           aggregate_type="deep_review_attempt", aggregate_id=str(attempt_id), request_id=str(request_id),
                           safe_metadata={"preview_id": str(row.id), "input_sha256": row.input_sha256,
                                          "provider": PROVIDER, "model": policy.model_name,
                                          "reasoning_effort": policy_reasoning_effort(policy),
                                          **company}))
    session.flush()


def approved_input(session, attempt_id, review):
    approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt_id))
    row = session.get(DeepReviewPreview, approval.preview_id) if approval else None
    # Legacy (NULL) lineage only; company attempts use approved_company_input.
    if (row is None or review.company_id is not None or row.company_id is not None or approval.company_id is not None
            or row.notice_id != review.notice_id or row.bundle_id != review.bundle_id
            or row.profile_version_id != review.profile_version_id or row.policy_version_id != review.policy_version_id
            or canonical_json_hash(row.input_snapshot) != row.input_sha256):
        raise InputVersionError("approval_invalid", "승인된 동결 입력을 확인할 수 없습니다")
    return deepcopy(row.input_snapshot)


def approved_company_input(session, attempt_id, review):
    """Worker-side ``approval_invalid`` check of a company attempt (demo contract §9).

    Returns a copy of the approved preview's frozen CompanyAnalysisInput only
    when the approval exists for this attempt, the approval/preview/review
    company ids agree, the preview lineage (notice/bundle/profile/graph/policy)
    is the review's, the stored hash matches the frozen input and its
    FrozenProvenance, and the input is bound to that preview (nonce) and to
    this review (``target_review_id``: none for the first attempt, the review
    for a retry).  The input is never rebuilt here.
    """

    from ..models import DeepReviewAttempt

    approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == attempt_id))
    row = session.get(DeepReviewPreview, approval.preview_id) if approval else None
    attempt = session.get(DeepReviewAttempt, attempt_id)
    frozen = row.input_snapshot if row is not None and isinstance(row.input_snapshot, dict) else None
    provenance = row.provenance_jsonb if row is not None and isinstance(row.provenance_jsonb, dict) else None
    try:
        digest = canonical_json_hash(frozen) if frozen is not None else None
    except (TypeError, ValueError):
        digest = None
    expected_target = None if attempt is None or attempt.sequence == 1 else str(review.id)
    if (
        row is None or attempt is None or frozen is None or provenance is None
        or review.company_id is None or review.graph_version_id is None
        or attempt.deep_review_id != review.id
        or approval.company_id != review.company_id or row.company_id != review.company_id
        or row.notice_id != review.notice_id or row.bundle_id != review.bundle_id
        or row.profile_version_id != review.profile_version_id
        or row.policy_version_id != review.policy_version_id
        or row.graph_version_id != review.graph_version_id
        or digest != row.input_sha256 or provenance.get("input_sha256") != row.input_sha256
        or frozen.get("purpose") != "deep_review" or frozen.get("execution_nonce") != str(row.id)
        or frozen.get("target_review_id") != expected_target
        or frozen.get("company_id") != str(review.company_id)
        or frozen.get("notice_id") != review.notice_id
        or frozen.get("bundle_id") != str(review.bundle_id)
        or frozen.get("profile_version_id") != str(review.profile_version_id)
        or frozen.get("graph_version_id") != str(review.graph_version_id)
        or frozen.get("policy_version_id") != str(review.policy_version_id)
    ):
        raise InputVersionError("approval_invalid", "승인된 동결 입력을 확인할 수 없습니다")
    return deepcopy(frozen)
