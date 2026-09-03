"""Stable, non-leaking error and human-wait mappings for agent contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

from .contracts import (
    AgentAction,
    AgentErrorCode,
    AgentSafeError,
    AgentWait,
    AgentWaitReason,
)


@dataclass(frozen=True)
class SafeErrorSpec:
    message: str
    retryable: bool


@dataclass(frozen=True)
class WaitSpec:
    message: str
    required_actions: tuple[AgentAction, ...]


SAFE_ERROR_MAPPING: Final[Mapping[AgentErrorCode, SafeErrorSpec]] = MappingProxyType(
    {
        AgentErrorCode.invalid_request: SafeErrorSpec("요청을 처리할 수 없습니다", False),
        AgentErrorCode.actor_name_required: SafeErrorSpec("담당자 이름이 필요합니다", False),
        AgentErrorCode.actor_name_invalid: SafeErrorSpec("담당자 이름이 올바르지 않습니다", False),
        AgentErrorCode.not_found: SafeErrorSpec("대상을 찾을 수 없습니다", False),
        AgentErrorCode.effective_grade_ineligible: SafeErrorSpec("현재 공고는 검토 대상이 아닙니다", False),
        AgentErrorCode.bundle_not_ready: SafeErrorSpec("ready document bundle이 필요합니다", True),
        AgentErrorCode.bundle_has_blocking_issues: SafeErrorSpec("bundle에 해결되지 않은 차단 항목이 있습니다", False),
        AgentErrorCode.unsafe_document: SafeErrorSpec("문서 안전 검사를 통과하지 못했습니다", False),
        AgentErrorCode.structure_unavailable: SafeErrorSpec("문서 구조를 확인할 수 없습니다", True),
        AgentErrorCode.version_conflict: SafeErrorSpec("대상이 변경되어 다시 확인해야 합니다", True),
        AgentErrorCode.idempotency_conflict: SafeErrorSpec("같은 request_id가 다른 요청에 사용되었습니다", False),
        AgentErrorCode.active_attempt_exists: SafeErrorSpec("이미 실행 중인 attempt가 있습니다", True),
        AgentErrorCode.review_not_ready: SafeErrorSpec("심층 검토가 아직 준비되지 않았습니다", True),
        AgentErrorCode.evidence_out_of_scope: SafeErrorSpec("심층 검토 범위 밖의 근거입니다", False),
        AgentErrorCode.validation_failed: SafeErrorSpec("검증에 실패했습니다", False),
        AgentErrorCode.factual_change_evidence_required: SafeErrorSpec("사실 변경에는 범위 내 근거가 필요합니다", False),
        AgentErrorCode.final_opinion_reason_required: SafeErrorSpec("최종 의견 사유가 필요합니다", False),
        AgentErrorCode.service_unavailable: SafeErrorSpec("서비스를 일시적으로 사용할 수 없습니다", True),
        AgentErrorCode.processing_failed: SafeErrorSpec("작업을 완료할 수 없습니다", True),
    }
)


WAIT_MAPPING: Final[Mapping[AgentWaitReason, WaitSpec]] = MappingProxyType(
    {
        AgentWaitReason.document_registration_required: WaitSpec(
            "검토할 문서를 등록해야 합니다", (AgentAction.register_document,)
        ),
        AgentWaitReason.document_metadata_confirmation_required: WaitSpec(
            "문서 metadata를 확인하고 bundle을 확정해야 합니다",
            (AgentAction.update_document_metadata, AgentAction.confirm_ready),
        ),
        AgentWaitReason.document_blocking_issues_resolution_required: WaitSpec(
            "문서 차단 항목을 해결해야 합니다",
            (AgentAction.register_document, AgentAction.update_document_metadata),
        ),
        AgentWaitReason.machine_report_required: WaitSpec(
            "machine report와 validation을 기다리고 있습니다", ()
        ),
        AgentWaitReason.report_review_required: WaitSpec(
            "report와 근거를 사람이 검토해야 합니다",
            (AgentAction.create_full_revision, AgentAction.record_final_opinion),
        ),
        AgentWaitReason.final_opinion_required: WaitSpec(
            "최신 report에 최종 의견을 기록해야 합니다", (AgentAction.record_final_opinion,)
        ),
    }
)


# These are the legacy document-asset safety codes used at the existing asset
# boundary.  They are intentionally copied as a closed set here instead of
# importing a service module into the common contract.
DOCUMENT_ASSET_SAFETY_CODES: Final[frozenset[str]] = frozenset(
    {
        "unsafe_document",
        "malware_detected",
        "mime_mismatch",
        "malformed_pdf",
        "malformed_archive",
        "archive_size_limit",
        "archive_ratio_limit",
        "archive_member_limit",
        "conversion_required",
        "ocr_unavailable",
        "renderer_unavailable",
        "clamav_unavailable",
        "provider_url_blocked",
        "provider_host_blocked",
        "provider_private_ip",
        "provider_dns_blocked",
        "provider_redirect_blocked",
        "provider_size_limit",
        "provider_response_invalid",
        "provider_connector_blocked",
        "provider_proxy_blocked",
        "legacy_path_blocked",
        "legacy_symlink_blocked",
        "legacy_non_regular",
        "legacy_size_limit",
        "legacy_size_mismatch",
        "legacy_source_changed",
        "legacy_source_missing",
        "legacy_provenance_invalid",
    }
)

AVAILABILITY_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"service_unavailable", "provider_unavailable"}
)

_DOMAIN_ERROR_CODES: Final[frozenset[str]] = frozenset(code.value for code in AgentErrorCode)


def safe_error_spec(code: AgentErrorCode) -> SafeErrorSpec:
    """Return the fixed public mapping for a domain error code."""

    return SAFE_ERROR_MAPPING[AgentErrorCode(code)]


def wait_spec(reason_code: AgentWaitReason) -> WaitSpec:
    """Return the fixed public mapping for a wait reason."""

    return WAIT_MAPPING[AgentWaitReason(reason_code)]


def _source_code(source: object) -> str | None:
    if isinstance(source, AgentErrorCode):
        return source.value
    if isinstance(source, str):
        return source
    code = getattr(source, "code", None)
    if isinstance(code, AgentErrorCode):
        return code.value
    if isinstance(code, str):
        return code
    return None


def classify_error_code(source: object) -> AgentErrorCode:
    """Collapse an internal/legacy error into the safe v1 error enum.

    Only a code attribute is considered.  Exception text is never copied to
    the public contract, which prevents internal messages and implementation
    details from crossing the boundary.
    """

    code = _source_code(source)
    if code in _DOMAIN_ERROR_CODES:
        return AgentErrorCode(code)
    if code in DOCUMENT_ASSET_SAFETY_CODES:
        return AgentErrorCode.unsafe_document
    if code in AVAILABILITY_ERROR_CODES or (code is not None and code.endswith("_unavailable")):
        return AgentErrorCode.service_unavailable
    return AgentErrorCode.processing_failed


def safe_error(source: object) -> AgentSafeError:
    """Build a safe error using only the fixed code/message mapping."""

    code = classify_error_code(source)
    spec = safe_error_spec(code)
    return AgentSafeError(code=code, message=spec.message, retryable=spec.retryable, details=None)


def make_safe_error(source: object) -> AgentSafeError:
    return safe_error(source)


def to_safe_error(source: object) -> AgentSafeError:
    return safe_error(source)


def make_wait(reason_code: AgentWaitReason | str) -> AgentWait:
    reason = AgentWaitReason(reason_code)
    spec = wait_spec(reason)
    return AgentWait(reason_code=reason, message=spec.message, required_actions=list(spec.required_actions))


def wait_for(reason_code: AgentWaitReason | str) -> AgentWait:
    return make_wait(reason_code)


__all__ = [
    "AVAILABILITY_ERROR_CODES",
    "DOCUMENT_ASSET_SAFETY_CODES",
    "SAFE_ERROR_MAPPING",
    "WAIT_MAPPING",
    "SafeErrorSpec",
    "WaitSpec",
    "classify_error_code",
    "make_safe_error",
    "make_wait",
    "safe_error",
    "safe_error_spec",
    "to_safe_error",
    "wait_for",
    "wait_spec",
]
