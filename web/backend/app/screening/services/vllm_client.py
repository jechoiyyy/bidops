"""C-2 발주계획 선별의 사설 모델 어댑터.

심층 검토 client와 달리 고정된 batch payload만 받고 fallback provider가 없다.
공통 경계(응답 크기 한도·객체 저장소 규약)는 core의 범용 client에서 가져온다.

전송 방식(``api_dialect``)은 승인된 generation config가 정한다. ``vllm``은
literal IP의 사설 vLLM이고, ``litellm``은 승인 host의 LiteLLM 별칭 뒤에 있는
사설 Ollama다(ADR-0072). 어느 쪽이든 binding의 모델명·digest와 배포 선언
revision이 같아야 호출을 시작한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import ipaddress
import json
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from ...core.model_client import MAX_RESPONSE_BYTES


# Model names a C-2 binding may name, per wire dialect.  ``qwen3.8:27b`` is the
# Ollama build that the contracts already admit as ``approved_private_ollama``.
APPROVED_MODELS_BY_DIALECT: Mapping[str, frozenset[str]] = {
    "vllm": frozenset({"qwen3.8-27B"}),
    "litellm": frozenset({"qwen3.8:27b"}),
}
_ALIAS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HOSTNAME_PATTERN = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")


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


def _validated_litellm_base_url(base_url: str, allowed_hosts: str | Sequence[str]) -> str:
    """Validate an exact HTTPS ``/v1`` boundary on an allowlisted LiteLLM host.

    The proxy sits behind a TLS name, so a literal IP cannot be verified; the
    allowlist instead holds exact lowercase hostnames, never wildcards.
    """

    entries = allowed_hosts.split(",") if isinstance(allowed_hosts, str) else list(allowed_hosts)
    hosts = [entry.strip() for entry in entries if entry.strip()]
    if not hosts or any(not _HOSTNAME_PATTERN.fullmatch(entry) for entry in hosts):
        raise ValueError("C-2 LiteLLM host allowlist must hold exact lowercase hostnames")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("C-2 LiteLLM endpoint is invalid") from exc
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1"
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ValueError("C-2 LiteLLM endpoint must be an exact https /v1 URL")
    if hostname not in hosts:
        raise ValueError("C-2 LiteLLM endpoint host is not allowlisted")
    return base_url


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class OrderPlanVllmAdapter:
    """Strict OpenAI-compatible adapter for one approved private C-2 model."""

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
        if not isinstance(generation_config, Mapping):
            raise ValueError("C-2 generation config is required")
        api_dialect = generation_config.get("api_dialect", "vllm")
        if api_dialect not in APPROVED_MODELS_BY_DIALECT:
            raise ValueError("C-2 generation config names an unsupported API dialect")
        if model not in APPROVED_MODELS_BY_DIALECT[api_dialect] or not re.fullmatch(r"[0-9a-f]{64}", model_digest):
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
            or (api_dialect == "vllm" and not isinstance(chat_template_kwargs, Mapping))
        ):
            raise ValueError("C-2 generation config is missing approved values")
        self.api_dialect = api_dialect
        self.max_tokens = max_tokens
        # Behind LiteLLM the Ollama upstream ignores ``chat_template_kwargs``;
        # only ``reasoning_effort="none"`` turns thinking off (ADR-0072), so
        # each dialect sends exactly its own switch.  The wire model is the
        # LiteLLM alias, which the response must echo back.
        self.extra_request_fields: dict[str, Any] = {}
        if api_dialect == "litellm":
            request_model = generation_config.get("request_model")
            if (
                not isinstance(request_model, str)
                or not _ALIAS_PATTERN.fullmatch(request_model)
                or generation_config.get("reasoning_effort") != "none"
            ):
                raise ValueError("C-2 LiteLLM generation config is missing approved values")
            self.request_model = request_model
            self.extra_request_fields["reasoning_effort"] = "none"
            self.base_url = _validated_litellm_base_url(base_url, allowed_hosts)
            # The deployment allowlist may only narrow the approved one, so an
            # env edit alone cannot point the binding at another host.
            approved_hosts = generation_config.get("allowed_hosts")
            if (
                not isinstance(approved_hosts, list)
                or not approved_hosts
                or urlsplit(base_url).hostname not in approved_hosts
            ):
                raise ValueError("C-2 LiteLLM endpoint host is not in the approved generation config")
        else:
            self.request_model = model
            self.extra_request_fields["chat_template_kwargs"] = dict(chat_template_kwargs)
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
            "model": self.request_model,
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
            **self.extra_request_fields,
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
        if document.get("model") != self.request_model:
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
    "OrderPlanVllmAdapter",
    "OrderPlanVllmError",
    "OrderPlanVllmResponse",
    "order_plan_batch_output_schema",
]
