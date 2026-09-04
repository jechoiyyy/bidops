"""API-driven acceptance flow joining document bundle and deep review stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote_from_bytes, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BC_E2E_MANIFEST_SCHEMA = "bidops.bc-e2e-run.v1"
BC_E2E_RESULT_SCHEMA = "bidops.bc-e2e-result.v1"
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_API_RESPONSE_BYTES = 8 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".hwp", ".hwpx", ".pdf"})
MEDIA_TYPES = {
    ".hwp": "application/x-hwp",
    ".hwpx": "application/hwp+zip",
    ".pdf": "application/pdf",
}
UTF8_ACTOR_PREFIX = "UTF-8''"
UTF8_ACTOR_FORMAT = "utf-8-percent-v1"


def actor_header_value(actor: str) -> str:
    """Return an HTTP-header-safe claimed name without changing ASCII names."""

    try:
        actor.encode("ascii")
    except UnicodeEncodeError:
        return UTF8_ACTOR_PREFIX + quote_from_bytes(actor.encode("utf-8"), safe="")
    return actor


def actor_headers(actor: str) -> dict[str, str]:
    """Return the claimed name and an explicit format marker when encoded."""

    value = actor_header_value(actor)
    headers = {"X-BidOps-Actor-Name": value}
    if value != actor:
        headers["X-BidOps-Actor-Name-Format"] = UTF8_ACTOR_FORMAT
    return headers


class BcE2EError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]  # noqa: ARG002
        return None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


DocumentRole = Literal["공고", "정정", "제안요청서", "과업지시서", "내역서", "제출서식", "부록", "기타"]


class BcE2EDocument(_StrictModel):
    path: Path
    role: DocumentRole
    effective_date: date | None = None

    @field_validator("path")
    @classmethod
    def document_is_safe(cls, value: Path) -> Path:
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValueError("document path must be an absolute regular non-symlink file")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("document must be HWP, HWPX, or PDF")
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in path.name) or any(char in path.name for char in {'"', "\\"}):
            raise ValueError("document filename must be safe for multipart transport")
        size = path.stat().st_size
        if size <= 0 or size > MAX_DOCUMENT_BYTES:
            raise ValueError("document size must be between 1 byte and 50 MiB")
        return path


class BcE2EManifest(_StrictModel):
    schema_name: Literal["bidops.bc-e2e-run.v1"] = Field(alias="schema", serialization_alias="schema")
    api_base: str
    notice_id: int = Field(gt=0)
    actor_name: str = Field(min_length=1, max_length=128)
    documents: list[BcE2EDocument]
    analysis_retry_limit: int = Field(default=0, ge=0, le=2)

    @field_validator("api_base")
    @classmethod
    def api_base_is_explicit(cls, value: str) -> str:
        if value != value.strip() or value.endswith("/"):
            raise ValueError("api_base must be trimmed and must not end with slash")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None or parsed.port is None:
            raise ValueError("api_base must use http(s) with an explicit host and port")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("api_base must not contain credentials, query, fragment, or path")
        if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"} and parsed.scheme != "https":
            raise ValueError("non-loopback E2E targets must use https")
        return value

    @field_validator("actor_name")
    @classmethod
    def actor_is_valid(cls, value: str) -> str:
        clean = value.strip()
        if clean != value or clean.lower() == "system" or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in clean):
            raise ValueError("actor_name must be a trimmed printable claimed name")
        return value

    @model_validator(mode="after")
    def document_set_is_nonempty(self) -> "BcE2EManifest":
        if not self.documents:
            raise ValueError("at least one document is required")
        resolved = [str(document.path.resolve()) for document in self.documents]
        if len(set(resolved)) != len(resolved):
            raise ValueError("document paths must be unique")
        return self


class AcceptanceApi(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]: ...

    def upload_document(
        self,
        bundle_id: str,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        request_id: str,
        actor: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConfirmedDocumentEvidence:
    document_version_id: str
    version: int
    filename: str
    source_sha256: str | None
    safety_status: str
    structure_status: str
    role: str
    uploaded_in_run: bool


class JsonAcceptanceApi:
    """Small stdlib HTTP client that never logs headers or document bytes."""

    def __init__(self, api_base: str, *, timeout_seconds: float = 60.0, network_retries: int = 2) -> None:
        self.api_base = api_base
        self.timeout_seconds = timeout_seconds
        self.network_retries = max(0, min(int(network_retries), 2))
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def _send(self, request: Request, *, retryable: bool) -> bytes:
        attempts = self.network_retries + 1 if retryable else 1
        for index in range(attempts):
            try:
                with self._opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read(MAX_API_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_API_RESPONSE_BYTES:
                        raise BcE2EError("response_too_large", "acceptance API response exceeded its size limit")
                    return raw
            except HTTPError as error:
                raw = error.read(MAX_API_RESPONSE_BYTES + 1)
                if len(raw) > MAX_API_RESPONSE_BYTES:
                    raise BcE2EError("response_too_large", "acceptance API error response exceeded its size limit") from None
                code = "http_error"
                message = "acceptance API request failed"
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                        candidate_code = payload["error"].get("code")
                        candidate_message = payload["error"].get("message")
                        if isinstance(candidate_code, str) and candidate_code:
                            code = candidate_code
                        if isinstance(candidate_message, str) and candidate_message:
                            message = candidate_message
                except (UnicodeError, json.JSONDecodeError):
                    pass
                raise BcE2EError(code, message, status=error.code) from None
            except (URLError, TimeoutError, OSError) as error:
                if index + 1 >= attempts:
                    raise BcE2EError("api_unavailable", "acceptance API is unavailable") from error
        raise BcE2EError("api_unavailable", "acceptance API is unavailable")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if actor is not None:
            headers.update(actor_headers(actor))
        raw = self._send(Request(f"{self.api_base}{path}", data=body, headers=headers, method=method), retryable=retryable)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise BcE2EError("invalid_api_response", "acceptance API did not return JSON") from error
        if not isinstance(result, dict):
            raise BcE2EError("invalid_api_response", "acceptance API response must be an object")
        return result

    def upload_document(
        self,
        bundle_id: str,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        request_id: str,
        actor: str,
    ) -> dict[str, Any]:
        boundary = f"bidops-{uuid4().hex}"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"request_id\"\r\n\r\n{request_id}\r\n".encode(),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {media_type}\r\n\r\n"
            ).encode("utf-8"),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = Request(
            f"{self.api_base}/api/document-bundles/{bundle_id}/documents",
            data=b"".join(parts),
            headers={
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                **actor_headers(actor),
            },
            method="POST",
        )
        raw = self._send(request, retryable=True)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise BcE2EError("invalid_api_response", "document upload response was not JSON") from error
        if not isinstance(result, dict):
            raise BcE2EError("invalid_api_response", "document upload response must be an object")
        return result


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BcE2EError("invalid_api_response", f"acceptance API response is missing {key}")
    return value


def _required_version(payload: dict[str, Any]) -> int:
    value = payload.get("version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BcE2EError("invalid_api_response", "acceptance API response has an invalid version")
    return value


def _read_document(path: Path) -> tuple[bytes, str]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise BcE2EError("document_unavailable", "acceptance document cannot be read") from error
    if not 0 < len(content) <= MAX_DOCUMENT_BYTES:
        raise BcE2EError("document_size_changed", "acceptance document size changed after validation")
    return content, hashlib.sha256(content).hexdigest()


def _document_evidence(payload: dict[str, Any], *, source_sha256: str | None, uploaded_in_run: bool) -> ConfirmedDocumentEvidence:
    if payload.get("safety_status") != "safe" or payload.get("structure_status") != "ready":
        raise BcE2EError("document_not_ready", "bundle contains a document that is not safe with a ready structure")
    return ConfirmedDocumentEvidence(
        document_version_id=_required_string(payload, "id"),
        version=_required_version(payload),
        filename=_required_string(payload, "original_filename"),
        source_sha256=source_sha256,
        safety_status=_required_string(payload, "safety_status"),
        structure_status=_required_string(payload, "structure_status"),
        role=_required_string(payload, "role"),
        uploaded_in_run=uploaded_in_run,
    )


def run_bc_e2e(
    manifest: BcE2EManifest,
    api: AcceptanceApi,
    *,
    timeout_seconds: float = 3600,
    poll_seconds: float = 2,
    sleep: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> dict[str, Any]:
    """Execute B then C and return bounded acceptance evidence."""

    request_ids: dict[str, Any] = {"uploads": []}
    bundle = api.request_json(
        "POST",
        f"/api/notices/{manifest.notice_id}/document-bundles",
        payload={},
        actor=manifest.actor_name,
    )
    bundle_id = _required_string(bundle, "id")
    bundle_version = _required_version(bundle)
    if bundle.get("status") != "draft":
        raise BcE2EError("unexpected_bundle_status", "new document bundle was not draft")
    existing_documents = bundle.get("documents")
    if not isinstance(existing_documents, list) or not all(isinstance(document, dict) for document in existing_documents):
        raise BcE2EError("invalid_api_response", "new document bundle has an invalid document list")

    confirmed: dict[str, ConfirmedDocumentEvidence] = {}
    retryable_filenames = {document.path.name for document in manifest.documents}
    for existing in existing_documents:
        if existing.get("safety_status") == "safe" and existing.get("structure_status") == "ready":
            evidence = _document_evidence(existing, source_sha256=None, uploaded_in_run=False)
            confirmed[evidence.document_version_id] = evidence
            continue
        filename = existing.get("original_filename")
        if not isinstance(filename, str) or filename not in retryable_filenames:
            raise BcE2EError("document_not_ready", "bundle contains an unsafe document that this run will not replace")
    for document_input in manifest.documents:
        upload_request_id = str(uuid4())
        request_ids["uploads"].append(upload_request_id)
        content, source_sha256 = _read_document(document_input.path)
        document = api.upload_document(
            bundle_id,
            filename=document_input.path.name,
            media_type=MEDIA_TYPES[document_input.path.suffix.lower()],
            content=content,
            request_id=upload_request_id,
            actor=manifest.actor_name,
        )
        document_id = _required_string(document, "id")
        if document.get("safety_status") != "safe" or document.get("structure_status") != "ready":
            raise BcE2EError("document_not_ready", "uploaded document did not become safe with a ready structure")
        patched = api.request_json(
            "PATCH",
            f"/api/document-versions/{document_id}",
            payload={
                "role": document_input.role,
                "effective_date": document_input.effective_date.isoformat() if document_input.effective_date else None,
                # Preserve the immutable replacement lineage allocated by
                # upload; the acceptance runner owns role/current metadata,
                # not document ancestry.
                "replaces_document_version_id": document.get("replaces_document_version_id"),
                "is_current": True,
                "version": _required_version(document),
            },
            actor=manifest.actor_name,
        )
        evidence = _document_evidence(patched, source_sha256=source_sha256, uploaded_in_run=True)
        if evidence.document_version_id != document_id:
            raise BcE2EError("invalid_api_response", "patched document identity changed")
        # A fresh upload may supersede the safe document that was seeded into
        # this draft.  Confirm only the new current version for that filename;
        # retaining both IDs creates an intentionally rejected stale scope.
        for existing_id, existing_evidence in list(confirmed.items()):
            if existing_evidence.filename == evidence.filename:
                confirmed.pop(existing_id)
        confirmed[evidence.document_version_id] = evidence

    confirm_request_id = str(uuid4())
    request_ids["bundle_confirm"] = confirm_request_id
    ready = api.request_json(
        "POST",
        f"/api/document-bundles/{bundle_id}/confirm",
        payload={
            "request_id": confirm_request_id,
            "version": bundle_version,
            "confirmed_documents": [
                {"document_version_id": document.document_version_id, "version": document.version}
                for document in confirmed.values()
            ],
        },
        actor=manifest.actor_name,
        retryable=True,
    )
    if ready.get("status") != "ready" or any(issue.get("blocking") for issue in ready.get("issues", []) if isinstance(issue, dict)):
        raise BcE2EError("bundle_not_ready", "document bundle did not reach a clean ready snapshot")

    review_request_id = str(uuid4())
    request_ids["deep_review_create"] = review_request_id
    review = api.request_json(
        "POST",
        f"/api/notices/{manifest.notice_id}/deep-reviews",
        payload={"request_id": review_request_id, "bundle_id": bundle_id},
        actor=manifest.actor_name,
        retryable=True,
    )
    review_id = _required_string(review, "id")
    deadline = monotonic() + timeout_seconds
    retries_used = 0
    while True:
        review = api.request_json("GET", f"/api/deep-reviews/{review_id}", retryable=True)
        status = review.get("status")
        if status == "completed":
            break
        if status == "failed":
            if retries_used >= manifest.analysis_retry_limit:
                raise BcE2EError("analysis_failed", "deep review failed before completion")
            retry_request_id = str(uuid4())
            request_ids.setdefault("attempt_retries", []).append(retry_request_id)
            api.request_json(
                "POST",
                f"/api/deep-reviews/{review_id}/attempts",
                payload={"request_id": retry_request_id},
                actor=manifest.actor_name,
                retryable=True,
            )
            retries_used += 1
        elif status not in {"queued", "running"}:
            raise BcE2EError("unexpected_review_status", "deep review returned an unexpected status")
        if monotonic() >= deadline:
            raise BcE2EError("analysis_timeout", "deep review did not complete within the acceptance timeout")
        sleep(poll_seconds)

    attempt = review.get("current_attempt")
    stages = attempt.get("stages") if isinstance(attempt, dict) else None
    expected_stages = ["requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"]
    if (
        not isinstance(stages, list)
        or len(stages) != len(expected_stages)
        or not all(isinstance(stage, dict) for stage in stages)
        or [stage.get("stage") for stage in stages] != expected_stages
        or any(stage.get("status") != "completed" for stage in stages)
    ):
        raise BcE2EError("stage_sequence_invalid", "deep review did not complete all three ordered stages")

    report = api.request_json("GET", f"/api/deep-reviews/{review_id}/report", retryable=True)
    report_payload = report.get("report")
    if not isinstance(report_payload, dict) or report_payload.get("bundle_id") != bundle_id or report_payload.get("deep_review_id") != review_id:
        raise BcE2EError("report_scope_invalid", "machine report is not bound to the accepted review and bundle")
    history = report.get("history")
    if not isinstance(history, list) or not history or not isinstance(history[0], dict) or history[0].get("origin") != "machine":
        raise BcE2EError("report_revision_invalid", "machine report revision was not materialized")
    validation = report.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "passed":
        raise BcE2EError("validation_failed", "machine report validation did not pass")

    claims = report_payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise BcE2EError("report_evidence_missing", "machine report has no claims to verify")
    evidence_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("evidence_ids"), list):
            raise BcE2EError("report_evidence_invalid", "machine report claim evidence is invalid")
        evidence_ids.update(
            evidence_id for evidence_id in claim["evidence_ids"]
            if isinstance(evidence_id, str) and evidence_id
        )
    if not evidence_ids:
        raise BcE2EError("report_evidence_missing", "machine report has no evidence to verify")
    evidence_rows: list[dict[str, Any]] = []
    for evidence_id in sorted(evidence_ids):
        evidence = api.request_json("GET", f"/api/evidence/{evidence_id}", retryable=True)
        evidence_rows.append({
            "evidence_id": _required_string(evidence, "evidence_id"),
            "source_kind": _required_string(evidence, "source_kind"),
            "source_sha256": _required_string(evidence, "source_sha256"),
            "locator_type": _required_string(evidence, "locator_type"),
            "locator": evidence.get("locator"),
        })

    return {
        "schema": BC_E2E_RESULT_SCHEMA,
        "api_base": manifest.api_base,
        "notice_id": manifest.notice_id,
        "bundle": {
            "id": bundle_id,
            "revision": ready.get("revision"),
            "version": ready.get("version"),
            "status": ready.get("status"),
            "documents": [document.__dict__ for document in confirmed.values()],
        },
        "deep_review": {
            "id": review_id,
            "status": review.get("status"),
            "attempt_sequence": attempt.get("sequence") if isinstance(attempt, dict) else None,
            "stages": stages,
            "analysis_retries_used": retries_used,
        },
        "report": {
            "current_revision_id": report.get("current_revision_id"),
            "validation_run_id": validation.get("validation_run_id"),
            "validation_status": validation.get("status"),
            "system_recommendation": report_payload.get("system_recommendation"),
            "evidence": evidence_rows,
        },
        "request_ids": request_ids,
        "passed": True,
    }


__all__ = [
    "BC_E2E_MANIFEST_SCHEMA",
    "BC_E2E_RESULT_SCHEMA",
    "BcE2EDocument",
    "BcE2EError",
    "BcE2EManifest",
    "JsonAcceptanceApi",
    "actor_header_value",
    "run_bc_e2e",
]
