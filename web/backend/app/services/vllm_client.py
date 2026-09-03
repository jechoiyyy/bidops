"""Bounded OpenAI-compatible vLLM invocation for Qwen deep-review stages."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
import re
import time
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from ..contracts.deep_review import DEEP_REVIEW_STAGE_SCHEMA, load_schema
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
APPROVED_TIMEOUT_SECONDS = 300
APPROVED_RETRIES = 2
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_COMPLETION_TOKENS = 16_384
APPROVED_GENERATION = {
    "enable_thinking": False,
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "seed": 0,
    "temperature": 0.7,
    "top_k": 20,
    "top_p": 0.8,
}


def _provider_stage_schema() -> dict[str, Any]:
    """Flatten the evidence ``allOf`` for vLLM's structured decoder.

    The authoritative validator still applies the complete ``allOf``/``oneOf``
    contract after generation.  The provider schema is only a constrained
    decoding aid and must require every common evidence field explicitly.
    """

    schema = deepcopy(load_schema(DEEP_REVIEW_STAGE_SCHEMA))
    evidence_base = schema["$defs"]["evidence_base"]
    schema["$defs"]["evidence"] = {
        "type": "object",
        "additionalProperties": False,
        "required": list(evidence_base["required"]),
        "properties": deepcopy(evidence_base["properties"]),
    }
    return schema


STAGE_RESPONSE_SCHEMA = _provider_stage_schema()


class ResponseTooLargeError(ValueError):
    """Provider response exceeded the bounded response budget."""


class EncryptedObjectStore(Protocol):
    """The only storage capability accepted for raw model responses."""

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str) -> Mapping[str, Any]: ...


class VllmInvocationError(RuntimeError):
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
    provider: str | None = None
    model: str | None = None


def _safe_text(value: str) -> str:
    value = _URL_TEXT.sub("<redacted-url>", value)
    value = _SECRET_TEXT.sub("<redacted-secret>", value)
    value = _PATH_TEXT.sub("<redacted-path>", value)
    return value


def _sensitive_key(key: str) -> bool:
    """Match sensitive field tokens, never arbitrary substrings."""

    if not isinstance(key, str):
        return False
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).replace("-", "_").lower()
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    if normalized.endswith("_object_key") or normalized.endswith("_storage_path"):
        return True
    tokens = tuple(token for token in normalized.split("_") if token)
    return any(token in {
        "path", "file", "url", "uri", "credential", "secret", "token",
        "password", "authorization", "cookie", "encryption",
    } for token in tokens)


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
        prompt_input.pop("profile_facts", None)
        prompt_input.pop("profile_evidence", None)
    payload: dict[str, Any] = {
        "stage": stage,
        "instruction": instructions,
        "input_slice": sanitize_for_prompt(prompt_input),
        "output_contract": {
            "schema": "bidops.deep-review-stage.v1",
            "fields": ["schema", "deep_review_id", "attempt_id", "stage", "claims", "evidence", "unknowns", "warnings"],
            "identity_rule": "Copy deep_review_id, attempt_id, and stage exactly from input_slice.",
            "bounded_output_rule": "Emit at most 8 claims, 8 evidence rows, 8 unknowns, and 8 warnings for this reference-workflow slice. Prefer material requirements and explicit unknowns over exhaustive restatement.",
            "evidence_rule": "Every fact, calculation, inference, and requirement must cite only this slice or fixed profile evidence.",
            "document_evidence_rule": "For document evidence copy document_version_id, structure_id, source_sha256, locator_type, and locator from the cited requirement; set profile IDs to null and use an exact substring from one source block as quote. Never quote across newline-separated blocks in a page excerpt.",
        },
    }
    if profile is not None:
        selected_profile = {
            "profile_version_id": profile.get("profile_version_id"),
            "profile_sha256": profile.get("profile_sha256"),
            "facts": input_slice.get("profile_facts", []),
            "evidence": input_slice.get("profile_evidence", []),
        }
        payload["fixed_profile_slice"] = sanitize_for_prompt(selected_profile)
    if prior_stages:
        selected_prior: list[dict[str, Any]] = []
        for prior in prior_stages:
            if not isinstance(prior, Mapping):
                continue
            selected_prior.append({"claims": prior.get("claims", []), "evidence": prior.get("evidence", [])})
        payload["prior_verified_claims"] = sanitize_for_prompt(selected_prior)
    if stage == "synthesis_and_validation":
        payload["output_contract"]["recommendation_rule"] = (
            "Emit exactly one claim whose category is system_recommendation and whose body is exactly one of: "
            "추진 검토, 조건부 추진 검토, 보류, 검토 종료. The recommendation must be supported by prior verified claims."
        )
    prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(prompt) > 24000:
        raise ValueError("bounded prompt exceeds the local analysis limit")
    return prompt


def _validated_base_url(base_url: str, allowed_hosts: Sequence[str]) -> str:
    parsed = urlsplit(base_url)
    allowed = {"localhost", "127.0.0.1", "::1"}
    allowed.update(item.strip().lower() for item in allowed_hosts if item.strip())
    hostname = parsed.hostname.lower() if parsed.hostname else None
    if parsed.scheme != "http" or hostname is None or hostname not in allowed:
        raise ValueError("vLLM base URL must use approved plain HTTP host")
    if hostname != "localhost":
        try:
            ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise ValueError("vLLM host must be localhost or a literal IP") from exc
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("vLLM base URL must not contain userinfo, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("vLLM base URL port is invalid") from exc
    if port is None or not 1 <= port <= 65535 or parsed.path.rstrip("/") != "/v1":
        raise ValueError("vLLM base URL must include an explicit port and /v1 path")
    return base_url.rstrip("/")


def _bounded_response(response: httpx.Response) -> None:
    """Reject declared oversized responses before the SDK parses the body."""

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_RESPONSE_BYTES:
                raise ResponseTooLargeError("response_too_large")
        except ValueError as exc:
            raise ResponseTooLargeError("response_too_large") from exc


class VllmClient:
    """OpenAI SDK client restricted to one approved vLLM model and base URL."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key: str = "EMPTY",
        allowed_hosts: str | Sequence[str] | None = None,
        completion_create: Callable[..., Any] | None = None,
        model: str = MODEL_NAME,
        endpoint_ref: str = MODEL_ENDPOINT_REF,
    ) -> None:
        if endpoint_ref != MODEL_ENDPOINT_REF or model != MODEL_NAME:
            raise ValueError("only approved vLLM qwen3.8-27B is permitted")
        if allowed_hosts is None:
            allowed_hosts = os.getenv("BIDOPS_VLLM_ALLOWED_HOSTS", "").split(",")
        elif isinstance(allowed_hosts, str):
            allowed_hosts = allowed_hosts.split(",")
        self.base_url = _validated_base_url(base_url, allowed_hosts)
        self.model = model
        self.provider_name = "vllm-openai-compatible"
        self._http_client: httpx.Client | None = None
        if completion_create is not None:
            self._completion_create = completion_create
        else:
            self._http_client = httpx.Client(
                trust_env=False,
                follow_redirects=False,
                event_hooks={"response": [_bounded_response]},
            )
            sdk = OpenAI(
                base_url=self.base_url,
                api_key=api_key,
                max_retries=0,
                http_client=self._http_client,
            )
            self._completion_create = sdk.chat.completions.create

    def _request(self, prompt: str, *, timeout_seconds: int) -> Mapping[str, Any]:
        response = self._completion_create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "Return exactly one JSON object matching the enforced deep-review-stage schema. Copy input identity fields exactly, use lowercase UUIDs for new claim/evidence IDs, and do not include analysis, reasoning, or Markdown fences in content.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=APPROVED_GENERATION["temperature"],
            top_p=APPROVED_GENERATION["top_p"],
            seed=APPROVED_GENERATION["seed"],
            max_tokens=APPROVED_GENERATION["max_completion_tokens"],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "bidops_deep_review_stage_v1",
                    "strict": True,
                    "schema": STAGE_RESPONSE_SCHEMA,
                },
            },
            extra_body={
                "top_k": APPROVED_GENERATION["top_k"],
                "chat_template_kwargs": {"enable_thinking": APPROVED_GENERATION["enable_thinking"]},
            },
            timeout=float(timeout_seconds),
        )
        if isinstance(response, Mapping):
            payload = response
        elif hasattr(response, "model_dump"):
            payload = response.model_dump(mode="json")
        else:
            raise ValueError("malformed_json")
        if not isinstance(payload, Mapping):
            raise ValueError("malformed_json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ResponseTooLargeError("response_too_large")
        return payload

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
            raise VllmInvocationError("model_not_allowed", ())
        chunking = policy.get("chunking") if isinstance(policy.get("chunking"), Mapping) else {}
        try:
            timeout_seconds = int(chunking.get("timeout_seconds", APPROVED_TIMEOUT_SECONDS))
            retries = int(chunking.get("retries", APPROVED_RETRIES))
        except (TypeError, ValueError):
            raise VllmInvocationError("policy_invalid", ()) from None
        if timeout_seconds != APPROVED_TIMEOUT_SECONDS or retries < 0 or retries > APPROVED_RETRIES:
            raise VllmInvocationError("policy_invalid", ())
        if policy.get("generation", APPROVED_GENERATION) != APPROVED_GENERATION:
            raise VllmInvocationError("policy_invalid", ())
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages)
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        observations: list[dict[str, Any]] = []
        for index in range(retries + 1):
            started = time.monotonic()
            try:
                response = self._request(prompt, timeout_seconds=timeout_seconds)
                if response.get("model") != self.model:
                    raise ValueError("model_mismatch")
                choices = response.get("choices")
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
                    raise ValueError("malformed_json")
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    raise EOFError("truncated_json")
                if choice.get("finish_reason") != "stop":
                    raise ValueError("malformed_json")
                message = choice.get("message")
                if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
                    raise ValueError("malformed_json")
                output = message["content"]
                output_bytes = output.encode("utf-8")
                if len(output_bytes) > MAX_RESPONSE_BYTES:
                    raise ResponseTooLargeError("response_too_large")
                structured = json.loads(output)
                if not isinstance(structured, Mapping):
                    raise ValueError("malformed_json")
                usage = response.get("usage") if isinstance(response.get("usage"), Mapping) else {}
                elapsed = int((time.monotonic() - started) * 1000)
                observations.append({"retry_index": index, "status": "succeeded", "latency_ms": elapsed})
                return InvocationResult(
                    structured_output=dict(structured),
                    raw_response=output_bytes,
                    input_sha256=input_hash,
                    output_sha256=hashlib.sha256(output_bytes).hexdigest(),
                    prompt_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
                    output_tokens=usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
                    latency_ms=elapsed,
                    attempts=tuple(observations),
                    provider=self.provider_name,
                    model=self.model,
                )
            except (TimeoutError, APITimeoutError):
                code = "timeout"
            except ResponseTooLargeError:
                code = "response_too_large"
            except APIStatusError:
                code = "provider_http_error"
            except (APIConnectionError, httpx.NetworkError, OSError):
                code = "provider_unavailable"
            except EOFError:
                code = "truncated_json"
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                code = "malformed_json"
            except Exception:
                code = "provider_error"
            elapsed = int((time.monotonic() - started) * 1000)
            observations.append({"retry_index": index, "status": "failed", "error_code": code, "latency_ms": elapsed})
        raise VllmInvocationError(str(observations[-1].get("error_code", "provider_error")), observations)


# C-2 uses a deliberately separate adapter contract.  The deep-review client
# above remains compatible with its existing provider surface; this adapter
# only accepts the fixed order-plan batch payload and never has a fallback
# provider.


class OrderPlanVllmError(RuntimeError):
    """Safe, classified error from the C-2 private model boundary."""

    def __init__(self, failure_type: str, code: str) -> None:
        self.failure_type = failure_type
        self.code = code
        super().__init__(code)


def _canonical_text(value: Any) -> str:
    """Serialise a model payload the way the C-2 selection experiment does."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def order_plan_batch_output_schema(batch_count: int) -> dict[str, Any]:
    """Constrained-decoding schema for one C-2 batch.

    Mirrors ``model_batch_output_schema`` in the C-2 selection experiment
    (``experiments/order-plan-screening/scripts/methods.py``), which cannot be
    imported here because the runtime image ships ``skills/`` only.  Pinning the
    batch size in the schema is what stops the model from returning a short,
    long, or renamed batch ([ADR-0044]).
    """

    if batch_count < 1:
        raise ValueError("a model batch needs at least one item")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "minItems": batch_count,
                "maxItems": batch_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "item_id": {"type": "integer", "minimum": 0, "maximum": batch_count - 1},
                        "relevance": {"type": "string", "enum": ["relevant", "not_relevant", "uncertain"]},
                        "score": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                    "required": ["item_id", "relevance", "score", "reason"],
                },
            },
        },
        "required": ["items"],
    }


@dataclass(frozen=True)
class OrderPlanVllmResponse:
    structured_output: Mapping[str, Any]
    approved_raw_response: bytes
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int


def _validated_order_plan_base_url(base_url: str, allowed_hosts: str | Sequence[str]) -> str:
    """Validate an exact private vLLM ``/v1`` boundary."""

    entries = allowed_hosts.split(",") if isinstance(allowed_hosts, str) else list(allowed_hosts)
    literal_hosts = [entry.strip() for entry in entries if entry.strip()]
    if not literal_hosts or any(any(character.isspace() for character in entry) for entry in literal_hosts):
        raise ValueError("C-2 vLLM literal host allowlist is required")
    try:
        for entry in literal_hosts:
            ipaddress.ip_address(entry)
    except ValueError as exc:
        raise ValueError("C-2 vLLM allowlist must contain literal IPs") from exc
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("C-2 vLLM endpoint is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1"
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ValueError("C-2 vLLM endpoint must be an exact /v1 URL")
    if hostname not in literal_hosts:
        raise ValueError("C-2 vLLM endpoint host is not allowlisted")
    try:
        ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ValueError("C-2 vLLM endpoint host must be a literal IP") from exc
    return base_url


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class OrderPlanVllmAdapter:
    """Strict OpenAI-compatible adapter for one approved private vLLM."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: str | Sequence[str],
        api_key: str,
        model: str,
        model_digest: str,
        deployed_revision: str,
        generation_config: Mapping[str, Any],
        http_client: httpx.Client | None = None,
    ) -> None:
        if model != "qwen3.8-27B" or not re.fullmatch(r"[0-9a-f]{64}", model_digest):
            raise ValueError("only the approved C-2 Qwen model binding is permitted")
        # An OpenAI-compatible vLLM server exposes no weight revision: neither
        # ``/v1/models`` nor a completion response carries one, so there is no
        # server-side value to compare a response against.  The deployment
        # declares the operator-attested digest instead and it must equal the
        # binding, the same one-shot check the C-2 selection experiment ran
        # before it sent anything ([ADR-0042]).  Declaring nothing fails closed.
        if not re.fullmatch(r"[0-9a-f]{64}", deployed_revision or ""):
            raise ValueError("C-2 deployment must declare a 64-hex model revision")
        if deployed_revision != model_digest:
            raise ValueError("C-2 deployed model revision does not match the binding")
        # Generation settings come from the approved config artifact so the
        # ``generation_config_sha256`` recorded on every attempt describes what
        # actually went on the wire.  Hardcoding them here is what let the
        # thinking switch go missing unnoticed ([ADR-0044]).
        if not isinstance(generation_config, Mapping):
            raise ValueError("C-2 generation config is required")
        max_tokens = generation_config.get("max_output_tokens")
        timeout_seconds = generation_config.get("timeout_seconds")
        chat_template_kwargs = generation_config.get("chat_template_kwargs")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens < 1
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 600
            or not isinstance(chat_template_kwargs, Mapping)
        ):
            raise ValueError("C-2 generation config is missing approved values")
        self.max_tokens = max_tokens
        self.chat_template_kwargs = dict(chat_template_kwargs)
        self.base_url = _validated_order_plan_base_url(base_url, allowed_hosts)
        self.model = model
        self.model_digest = model_digest
        self.timeout_seconds = float(timeout_seconds)
        self._owned_client = http_client is None
        self._client = http_client or httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout_seconds,
        )
        self._api_key = api_key

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def invoke(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        expected_model: str,
    ) -> OrderPlanVllmResponse:
        if expected_model != self.model:
            raise OrderPlanVllmError("model_mismatch", "model_mismatch")
        items = payload.get("items") if isinstance(payload, Mapping) else None
        if not isinstance(items, list) or not items:
            raise OrderPlanVllmError("schema_violation", "payload_invalid")
        # The approved prompt is the system message and the batch payload is
        # the user message, matching the measured C-2 selection run.  Folding
        # them into one message would send the model a different input than the
        # one ADR-0037 measured ([ADR-0044]).
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": _canonical_text(payload)},
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "order_plan_relevance",
                    "strict": True,
                    "schema": order_plan_batch_output_schema(len(items)),
                },
            },
            # ``extra_body`` is an OpenAI *python client* concept: the SDK
            # flattens it into the request body.  This adapter posts raw JSON,
            # so the key has to sit at the top level or vLLM drops it and the
            # model keeps its thinking budget, exhausting max_tokens.
            "chat_template_kwargs": dict(self.chat_template_kwargs),
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key and self._api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = time.monotonic()
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=request_payload,
            )
            if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
                raise OrderPlanVllmError("transport", "redirect_rejected")
            if response.status_code >= 400:
                raise OrderPlanVllmError("transport", "provider_http_error")
            raw_bytes = response.content
            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                raise OrderPlanVllmError("truncated_output", "response_too_large")
            document = response.json()
        except OrderPlanVllmError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise OrderPlanVllmError("timeout", "timeout") from None
        except json.JSONDecodeError:
            raise OrderPlanVllmError("schema_violation", "response_json_invalid") from None
        except (httpx.HTTPError, ValueError, OSError):
            raise OrderPlanVllmError("transport", "transport_error") from None
        if not isinstance(document, Mapping):
            raise OrderPlanVllmError("schema_violation", "response_schema_invalid")
        if document.get("model") != self.model:
            raise OrderPlanVllmError("model_mismatch", "model_mismatch")
        # The revision is verified once at construction against the deployment
        # declaration.  A stock vLLM omits it here, so absence is expected and
        # is not treated as a failure.  A server (or an approved proxy) that
        # does report one still has to agree with the binding.
        revision = document.get("model_revision", document.get("revision"))
        if revision is not None and revision != self.model_digest:
            raise OrderPlanVllmError("model_mismatch", "model_revision_invalid")
        choices = document.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
            raise OrderPlanVllmError("schema_violation", "response_schema_invalid")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise OrderPlanVllmError("truncated_output", "truncated_output")
        if choice.get("finish_reason") != "stop":
            raise OrderPlanVllmError("schema_violation", "finish_reason_invalid")
        message = choice.get("message")
        if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
            raise OrderPlanVllmError("schema_violation", "response_schema_invalid")
        content = message["content"]
        try:
            structured = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise OrderPlanVllmError("schema_violation", "response_json_invalid") from None
        if not isinstance(structured, Mapping):
            raise OrderPlanVllmError("schema_violation", "response_json_invalid")
        response_id = document.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise OrderPlanVllmError("schema_violation", "response_id_invalid")
        usage = document.get("usage") if isinstance(document.get("usage"), Mapping) else {}
        details = usage.get("prompt_tokens_details")
        cached_tokens = _nonnegative_int(details.get("cached_tokens")) if isinstance(details, Mapping) else None
        prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
        completion_tokens = _nonnegative_int(usage.get("completion_tokens"))
        total_tokens = _nonnegative_int(usage.get("total_tokens"))
        approved = {
            "id": response_id,
            "model": self.model,
            "choices": [{
                "index": choice.get("index", 0),
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }
        return OrderPlanVllmResponse(
            structured_output=dict(structured),
            approved_raw_response=json.dumps(approved, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            input_tokens=prompt_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )


__all__ = [
    "EncryptedObjectStore", "InvocationResult", "OrderPlanVllmAdapter", "OrderPlanVllmError",
    "OrderPlanVllmResponse", "VllmClient", "VllmInvocationError", "build_prompt", "sanitize_for_prompt",
]
