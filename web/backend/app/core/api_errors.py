"""Stable, safe API error vocabulary and actor-header validation.

응답으로 나가는 오류 코드·문구와 담당자 이름 검증은 세 도메인 모듈의 router가
모두 같은 규칙으로 써야 하므로 core가 소유한다(명세 §5.2). 내부 코드는 감사
metadata에 남더라도 여기서 승인된 작은 집합으로만 바깥에 나간다.
"""

from __future__ import annotations

import re
from urllib.parse import quote_from_bytes, unquote_to_bytes
from uuid import UUID

MAX_ACTOR_NAME = 128
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
API_ERROR_CODES = {
    "invalid_request", "actor_name_required", "actor_name_invalid", "not_found", "effective_grade_ineligible",
    "bundle_not_ready", "bundle_has_blocking_issues", "unsafe_document", "structure_unavailable",
    "version_conflict", "idempotency_conflict", "service_unavailable", "processing_failed",
}
UTF8_ACTOR_PREFIX = "UTF-8''"
UTF8_ACTOR_FORMAT = "utf-8-percent-v1"

_UNSAFE_ASSET_CODES = {
    "unsafe_document", "malware_detected", "mime_mismatch", "malformed_pdf",
    "malformed_archive", "archive_size_limit", "archive_ratio_limit", "archive_member_limit",
    "conversion_required", "ocr_unavailable", "renderer_unavailable", "clamav_unavailable",
    "provider_url_blocked", "provider_host_blocked", "provider_private_ip", "provider_dns_blocked",
    "provider_redirect_blocked", "provider_size_limit", "provider_response_invalid",
    "provider_connector_blocked", "provider_proxy_blocked", "legacy_path_blocked", "legacy_symlink_blocked",
    "unsupported_extension", "legacy_non_regular", "legacy_size_limit", "legacy_size_mismatch", "legacy_source_changed",
    "legacy_source_missing", "legacy_provenance_invalid",
}
_SAFE_API_MESSAGES = {
    "invalid_request": "요청이 올바르지 않습니다",
    "actor_name_required": "담당자 이름이 필요합니다",
    "actor_name_invalid": "담당자 이름이 올바르지 않습니다",
    "not_found": "요청한 문서를 찾을 수 없습니다",
    "effective_grade_ineligible": "현재 공고는 문서 검토 대상이 아닙니다",
    "bundle_not_ready": "ready bundle은 수정할 수 없습니다",
    "bundle_has_blocking_issues": "bundle에 해결되지 않은 차단 항목이 있습니다",
    "unsafe_document": "문서 안전 검사를 통과하지 못했습니다",
    "structure_unavailable": "문서 구조를 확인할 수 없습니다",
    "version_conflict": "문서가 변경되어 다시 시도해야 합니다",
    "idempotency_conflict": "동일 요청이 충돌했습니다",
    "service_unavailable": "문서 작업을 일시적으로 사용할 수 없습니다",
    "processing_failed": "문서 작업을 완료할 수 없습니다",
}

class BundleServiceError(RuntimeError):
    """A safe, stable API error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, request_id: UUID | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(message)


def stable_api_error(code: str, message: str | None = None) -> tuple[str, str]:
    """Map internal asset/processor/provider codes at the API boundary.

    Internal codes remain useful in content-scan/audit metadata, but never
    become endpoint response codes or messages.  The approved endpoint set is
    intentionally small and shared by all seven T3 routes.
    """

    if code in API_ERROR_CODES:
        return code, _SAFE_API_MESSAGES.get(code, "문서 요청을 처리할 수 없습니다")
    if code in _UNSAFE_ASSET_CODES:
        return "unsafe_document", _SAFE_API_MESSAGES["unsafe_document"]
    return "processing_failed", _SAFE_API_MESSAGES["processing_failed"]


def _decode_actor_header(actor: str) -> str:
    if not actor.startswith(UTF8_ACTOR_PREFIX):
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
    encoded = actor[len(UTF8_ACTOR_PREFIX):]
    try:
        if not encoded:
            raise ValueError("empty encoded actor")
        raw = unquote_to_bytes(encoded)
        if quote_from_bytes(raw, safe="") != encoded:
            raise ValueError("non-canonical actor encoding")
        decoded = raw.decode("utf-8")
        if decoded.isascii():
            raise ValueError("encoded actor must contain non-ASCII text")
        return decoded
    except (UnicodeDecodeError, ValueError) as error:
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400) from error


def validate_actor(actor: str | None, actor_format: str | None = None) -> str:
    if actor is None or not actor.strip():
        raise BundleServiceError("actor_name_required", "X-BidOps-Actor-Name이 필요합니다", status_code=400)
    if actor_format is None:
        value = actor.strip()
    elif actor_format == UTF8_ACTOR_FORMAT:
        value = _decode_actor_header(actor).strip()
    else:
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
    if not value or len(value) > MAX_ACTOR_NAME or _CONTROL.search(value) or value.casefold() == "system":
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
    return value


__all__ = [
    "API_ERROR_CODES",
    "MAX_ACTOR_NAME",
    "UTF8_ACTOR_FORMAT",
    "UTF8_ACTOR_PREFIX",
    "BundleServiceError",
    "stable_api_error",
    "validate_actor",
]
