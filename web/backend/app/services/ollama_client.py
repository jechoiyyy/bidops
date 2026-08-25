"""Bounded, local-only Ollama invocation for Qwen deep review stages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .input_versions import MODEL_ENDPOINT_REF, MODEL_NAME


_SENSITIVE_KEY_NAMES = {
    "path", "file", "url", "uri", "source_file", "file_path", "source_url",
    "object_key", "encryption", "encryption_key", "encryption_key_ref",
    "storage_path",
    "credential", "secret", "token", "password", "api_key", "apikey",
    "authorization", "cookie",
}
_PATH_TEXT = re.compile(r"(?<![A-Za-z0-9])/(?:[A-Za-z0-9_.-]+/){1,}[A-Za-z0-9_.-]+")
_URL_TEXT = re.compile(r"\b(?:https?|ftp)://[^\s]+", re.I)
_SECRET_TEXT = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|[A-Za-z0-9_-]*(?:api[_-]?key|password|secret|token)[A-Za-z0-9_-]*\s*[:=]\s*[^\s,;]+)\b", re.I)
APPROVED_TIMEOUT_SECONDS = 120
APPROVED_RETRIES = 2
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ResponseTooLargeError(ValueError):
    """Provider response exceeded the bounded local response budget."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:  # noqa: ARG002
        return None


class EncryptedObjectStore(Protocol):
    """The only storage capability accepted for raw model responses."""

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str) -> Mapping[str, Any]: ...


class OllamaInvocationError(RuntimeError):
    def __init__(self, code: str, attempts: Sequence[Mapping[str, Any]]) -> None:
        self.code = code
        self.attempts = list(attempts)
        super().__init__(code)


@dataclass(frozen=True)
class InvocationResult:
    structured_output: Mapping[str, Any]
    raw_response: bytes
    input_sha256: str
    output_sha256: str
    prompt_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    attempts: tuple[Mapping[str, Any], ...]


def _safe_text(value: str) -> str:
    value = _URL_TEXT.sub("<redacted-url>", value)
    value = _SECRET_TEXT.sub("<redacted-secret>", value)
    value = _PATH_TEXT.sub("<redacted-path>", value)
    return value


def _sensitive_key(key: str) -> bool:
    """Match sensitive field *tokens*, never arbitrary substrings.

    A substring rule treats ``profile_version_id`` as sensitive because
    ``profile`` contains ``file``.  Normalize separators and camel-case into
    whole tokens while retaining explicit compound names such as
    ``source_file`` and ``api_key``.
    """

    if not isinstance(key, str):
        return False
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).replace("-", "_").lower()
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    # Storage locator fields are frequently namespaced (for example
    # ``raw_object_key`` or ``encrypted_storage_path``).  Treat only these
    # explicit suffixes as sensitive so stable prompt identities such as
    # ``block_key`` and ``profile_version_id`` remain available to the model.
    if normalized.endswith("_object_key") or normalized.endswith("_storage_path"):
        return True
    tokens = tuple(token for token in normalized.split("_") if token)
    return any(token in {"path", "file", "url", "uri", "credential", "secret", "token", "password", "authorization", "cookie", "encryption"} for token in tokens)


def sanitize_for_prompt(value: Any, *, key: str | None = None) -> Any:
    """Remove unsafe metadata before a payload can enter a prompt."""

    if key and _sensitive_key(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): sanitize_for_prompt(v, key=str(k)) for k, v in value.items() if not _sensitive_key(str(k))}
    if isinstance(value, list):
        return [sanitize_for_prompt(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_prompt(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def build_prompt(
    stage: str,
    input_slice: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    profile: Mapping[str, Any] | None = None,
    prior_stages: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Build a bounded JSON prompt with no storage metadata or credentials."""

    instructions = next((row.get("instruction", "") for row in policy.get("stages", []) if row.get("stage") == stage), "")
    prompt_input = dict(input_slice)
    if profile is not None:
        # Stage two receives selected rows in the fixed profile section.  Do
        # not also leave them under input_slice: doing so duplicates every
        # profile fact/evidence row and makes occurrence-count and prompt-size
        # guarantees depend on the selected data.
        prompt_input.pop("profile_facts", None)
        prompt_input.pop("profile_evidence", None)
    payload: dict[str, Any] = {
        "stage": stage,
        "instruction": instructions,
        "input_slice": sanitize_for_prompt(prompt_input),
        "output_contract": {
            "schema": "bidops.deep-review-stage.v1",
            "fields": ["claims", "evidence", "unknowns", "warnings"],
            "evidence_rule": "Every fact, calculation, inference, and requirement must cite only this slice or fixed profile evidence.",
        },
    }
    if profile is not None:
        # The profile object is pinned for validation, but only the selected
        # fact/evidence rows may enter a stage-2 prompt.  Passing the entire
        # profile repeatedly both defeats bounded slicing and leaks unrelated
        # source material into every invocation.
        selected_profile = {
            "profile_version_id": profile.get("profile_version_id"),
            "profile_sha256": profile.get("profile_sha256"),
            "facts": input_slice.get("profile_facts", []),
            "evidence": input_slice.get("profile_evidence", []),
        }
        payload["fixed_profile_slice"] = sanitize_for_prompt(selected_profile)
    if prior_stages:
        # Preserve only claims/evidence required for rechecking, never whole
        # prior stage payloads containing unrelated source or diagnostics.
        selected_prior: list[dict[str, Any]] = []
        for prior in prior_stages:
            if not isinstance(prior, Mapping):
                continue
            selected_prior.append({"claims": prior.get("claims", []), "evidence": prior.get("evidence", [])})
        payload["prior_verified_claims"] = sanitize_for_prompt(selected_prior)
    prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # This is the actual built prompt budget, measured in Unicode code points
    # (the policy's contract), rather than an estimate of source text alone.
    if len(prompt) > 24000:
        raise ValueError("bounded prompt exceeds the local analysis limit")
    return prompt


class OllamaClient:
    """Minimal stdlib client restricted to the local Ollama generate API."""

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:11434/api/generate",
        transport: Callable[[Request, float], bytes] | None = None,
        model: str = MODEL_NAME,
        endpoint_ref: str = MODEL_ENDPOINT_REF,
    ) -> None:
        if endpoint_ref != MODEL_ENDPOINT_REF or model != MODEL_NAME:
            raise ValueError("only ollama-local qwen3.8:27b is permitted")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Ollama endpoint must be local http")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("Ollama endpoint must not contain userinfo, query, or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Ollama endpoint port is invalid") from exc
        if port is None or not 1 <= port <= 65535 or parsed.path != "/api/generate":
            raise ValueError("Ollama endpoint must include an explicit port and /api/generate path")
        self.endpoint = endpoint
        self.model = model
        self._transport = transport or self._urlopen

    @staticmethod
    def _urlopen(request: Request, timeout: float) -> bytes:
        # Never inherit HTTP(S)_PROXY from the host process and never follow a
        # redirect that could turn the local-only endpoint into an SSRF proxy.
        opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - endpoint is validated local-only
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ResponseTooLargeError("response_too_large")
        return data

    def _request(self, prompt: str, *, timeout_seconds: int) -> tuple[dict[str, Any], bytes]:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(self.endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        raw = self._transport(request, float(timeout_seconds))
        if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) > MAX_RESPONSE_BYTES:
            raise ResponseTooLargeError("response_too_large")
        raw = bytes(raw)
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response, dict):
            raise ValueError("malformed_json")
        return response, raw

    def invoke(
        self,
        stage: str,
        input_slice: Mapping[str, Any],
        policy: Mapping[str, Any],
        *,
        profile: Mapping[str, Any] | None = None,
        prior_stages: Sequence[Mapping[str, Any]] = (),
    ) -> InvocationResult:
        if policy.get("model_endpoint_ref", MODEL_ENDPOINT_REF) != MODEL_ENDPOINT_REF or policy.get("model_name", MODEL_NAME) != MODEL_NAME:
            raise OllamaInvocationError("model_not_allowed", ())
        chunking = policy.get("chunking") if isinstance(policy.get("chunking"), Mapping) else {}
        try:
            timeout_seconds = int(chunking.get("timeout_seconds", APPROVED_TIMEOUT_SECONDS))
            retries = int(chunking.get("retries", APPROVED_RETRIES))
        except (TypeError, ValueError):
            raise OllamaInvocationError("policy_invalid", ()) from None
        # Timeout is fixed to the approved budget.  A caller may request
        # fewer retries for a deterministic unit-test/provider probe, but can
        # never exceed the approved two retry cap.
        if timeout_seconds != APPROVED_TIMEOUT_SECONDS or retries < 0 or retries > APPROVED_RETRIES:
            raise OllamaInvocationError("policy_invalid", ())
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages)
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        observations: list[dict[str, Any]] = []
        for index in range(retries + 1):
            started = time.monotonic()
            try:
                response, raw = self._request(prompt, timeout_seconds=timeout_seconds)
                output = response.get("response")
                if not isinstance(output, str):
                    raise ValueError("malformed_json")
                structured = json.loads(output)
                if not isinstance(structured, Mapping):
                    raise ValueError("malformed_json")
                elapsed = int((time.monotonic() - started) * 1000)
                output_bytes = output.encode("utf-8")
                observations.append({"retry_index": index, "status": "succeeded", "latency_ms": elapsed})
                return InvocationResult(
                    structured_output=dict(structured), raw_response=output_bytes,
                    input_sha256=input_hash, output_sha256=hashlib.sha256(output_bytes).hexdigest(),
                    prompt_tokens=response.get("prompt_eval_count") if isinstance(response.get("prompt_eval_count"), int) else None,
                    output_tokens=response.get("eval_count") if isinstance(response.get("eval_count"), int) else None,
                    latency_ms=elapsed, attempts=tuple(observations),
                )
            except TimeoutError:
                code = "timeout"
            except ResponseTooLargeError:
                code = "response_too_large"
            except HTTPError:
                code = "provider_http_error"
            except (URLError, OSError):
                code = "provider_unavailable"
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                code = "malformed_json"
            except Exception:
                # Do not echo provider exception text: it can contain the
                # prompt, local endpoint details, or credentials.
                code = "provider_error"
            elapsed = int((time.monotonic() - started) * 1000)
            observations.append({"retry_index": index, "status": "failed", "error_code": code, "latency_ms": elapsed})
        raise OllamaInvocationError(str(observations[-1].get("error_code", "provider_error")), observations)


__all__ = [
    "EncryptedObjectStore", "InvocationResult", "OllamaClient", "OllamaInvocationError",
    "build_prompt", "sanitize_for_prompt",
]
