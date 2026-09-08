"""용도별로 설정되는 유일한 모델 transport (명세 §6.6).

core는 승인된 사설 OpenAI-compatible 배치로 나가는 경계만 소유한다. 무엇을
물어볼지(응답 schema·system prompt)는 계약을 소유한 도메인 모듈이
`StructuredOutputContract`로 넘기고, **어떤 모델을 부를지는 policy와 용도별
설정이 정한다.** 그래서 이 모듈에는 고정된 모델명이 없다 — 모델명을 코드에
박아 두면 배포가 모델을 바꿀 때 코드를 고쳐야 하고, 그 사이에 실행 row에
기록된 모델명과 실제로 부른 모델이 갈린다.

`MODEL_ENDPOINT_REF`는 모델이 아니라 "OpenAI 호환 transport"의 식별자다.
기존 policy 파일과 그 hash를 바꾸지 않으려고 문자열을 그대로 둔다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import os
import re
import time
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import SecretStr

from .model_binding import MODEL_ENDPOINT_REF


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

#: 모델을 부르는 용도 (명세 §5). 용도마다 자기 endpoint·자격증명·선언
#: revision을 가질 수 있고, 하나가 fail closed해도 다른 용도로 새지 않는다.
MODEL_PURPOSES: Final[tuple[str, ...]] = ("screening", "overview", "deep_review")

_REVISION_PATTERN = re.compile(r"[0-9a-f]{64}")
APPROVED_GENERATION = {
    "enable_thinking": False,
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "seed": 0,
    "temperature": 0.7,
    "top_k": 20,
    "top_p": 0.8,
}




@dataclass(frozen=True)
class StructuredOutputContract:
    """The structured-output surface a caller pins on this client.

    core는 어느 도메인 모듈의 응답 계약도 알지 못한다. 계약을 소유한 모듈이
    schema·이름·system prompt를 그대로 넘기고, 이 client는 그것을 provider
    요청에 실어 보내기만 한다.
    """

    name: str
    schema: Mapping[str, Any]
    system_prompt: str


class ResponseTooLargeError(ValueError):
    """Provider response exceeded the bounded response budget."""


class EncryptedObjectStore(Protocol):
    """The only storage capability accepted for raw model responses."""

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str) -> Mapping[str, Any]: ...


class ModelInvocationError(RuntimeError):
    """분류된 호출 실패. 원문·프롬프트·비밀값은 담지 않는다."""

    def __init__(self, code: str, attempts: Sequence[Mapping[str, Any]]) -> None:
        self.code = code
        self.attempts = list(attempts)
        super().__init__(code)



class ModelEndpointError(ValueError):
    """용도별 설정이 모델을 부를 수 있는 상태가 아니다 (fail closed).

    허용 host가 비었거나 배포가 revision을 선언하지 않았으면 **부르기 전에**
    여기서 멈춘다. 다른 주소·다른 provider로 넘어가지 않는다.
    """


class ModelIdentityError(RuntimeError):
    """서버가 내는 identity가 설정·policy와 다르다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ModelIdentity:
    """한 용도가 실제로 묶인 모델명과 배포 선언 revision."""

    model: str
    revision: str


@dataclass(frozen=True)
class ModelEndpoint:
    """한 용도의 해석된 transport 설정.

    `api_key`는 `SecretStr`이라 repr·로그에 값이 실리지 않는다.
    """

    purpose: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    api_key: SecretStr = field(repr=False)
    model_revision: str
    api_dialect: str = "vllm"


def _endpoint_value(settings: Any, purpose: str, suffix: str) -> Any:
    """용도별 override가 있으면 그것을, 없으면 공유값을 낸다."""

    override = getattr(settings, f"vllm_{purpose}_{suffix}", None)
    if isinstance(override, SecretStr):
        return override if override.get_secret_value() else getattr(settings, f"vllm_{suffix}")
    if isinstance(override, str) and override.strip():
        return override
    return getattr(settings, f"vllm_{suffix}")


def resolve_model_endpoint(purpose: str, *, settings: Any | None = None) -> ModelEndpoint:
    """용도 하나의 transport 설정을 해석한다 (명세 §6.6).

    공유 `BIDOPS_VLLM_*`가 기본값이고 `BIDOPS_VLLM_{용도}_*`가 있으면 그것을
    쓴다. **허용 host가 비거나 선언 revision이 없으면 그 용도는 fail closed**
    한다 — 여기서 실패시키는 것이 요점이다. client를 만든 뒤에 검사하면 이미
    주소를 열어 둔 상태가 되고, hosted 주소가 기본값으로 새어 들어갈 자리가
    생긴다.
    """

    if purpose not in MODEL_PURPOSES:
        raise ModelEndpointError("모델 용도는 " + ", ".join(MODEL_PURPOSES) + " 중 하나여야 한다")
    if settings is None:  # pragma: no cover - 실행 경로에서만 쓰인다
        from .config import get_settings

        settings = get_settings()
    base_url = str(_endpoint_value(settings, purpose, "base_url") or "")
    allowed_raw = _endpoint_value(settings, purpose, "allowed_hosts")
    api_key = _endpoint_value(settings, purpose, "api_key")
    revision = str(_endpoint_value(settings, purpose, "model_revision") or "")
    entries = allowed_raw.split(",") if isinstance(allowed_raw, str) else list(allowed_raw or ())
    allowed_hosts = tuple(entry.strip() for entry in entries if entry.strip())
    if not allowed_hosts:
        raise ModelEndpointError(f"{purpose} 용도의 허용 host 목록이 비어 있다")
    if not _REVISION_PATTERN.fullmatch(revision):
        raise ModelEndpointError(f"{purpose} 용도의 배포 선언 model revision이 64자 digest가 아니다")
    if not isinstance(api_key, SecretStr):
        api_key = SecretStr(str(api_key or "EMPTY"))
    return ModelEndpoint(
        purpose=purpose,
        base_url=_validated_base_url(base_url, allowed_hosts),
        allowed_hosts=allowed_hosts,
        api_key=api_key,
        model_revision=revision,
        api_dialect=getattr(settings, f"vllm_{purpose}_api_dialect", "vllm"),
    )


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


#: policy가 자기 출력 계약 문구를 선언하지 않았을 때 쓰는 심층 검토 stage 계약.
#: 이 값은 기존 policy 파일의 프롬프트 바이트를 그대로 유지하기 위한 기본값이다.
_DEEP_REVIEW_PROMPT_CONTRACT: Mapping[str, Any] = {
    "schema": "bidops.deep-review-stage.v1",
    "fields": ["schema", "deep_review_id", "attempt_id", "stage", "claims", "evidence", "unknowns", "warnings"],
    "identity_rule": "Copy deep_review_id, attempt_id, and stage exactly from input_slice.",
    "bounded_output_rule": "Emit at most 8 claims, 8 evidence rows, 8 unknowns, and 8 warnings for this reference-workflow slice. Prefer material requirements and explicit unknowns over exhaustive restatement.",
    "evidence_rule": "Every fact, calculation, inference, and requirement must cite only this slice or fixed profile evidence.",
    "document_evidence_rule": "For document evidence copy document_version_id, structure_id, source_sha256, locator_type, and locator from the cited requirement; set profile IDs to null and use an exact substring from one source block as quote. Never quote across newline-separated blocks in a page excerpt.",
}


def build_prompt(
    stage: str,
    input_slice: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    profile: Mapping[str, Any] | None = None,
    prior_stages: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Build a bounded JSON prompt with no storage metadata or credentials.

    출력 계약 문구는 policy가 ``prompt_output_contract``로 선언하면 그것을
    쓰고, 선언이 없으면 심층 검토 stage 계약을 쓴다. core가 도메인 계약을
    아는 것이 아니라 policy가 들고 오는 것이며, 선언이 없는 기존 policy는
    프롬프트 바이트가 그대로다.
    """

    instructions = next((row.get("instruction", "") for row in policy.get("stages", []) if row.get("stage") == stage), "")
    prompt_input = dict(input_slice)
    if profile is not None:
        prompt_input.pop("profile_facts", None)
        prompt_input.pop("profile_evidence", None)
    raw_contract = policy.get("prompt_output_contract")
    declared_contract = dict(raw_contract) if isinstance(raw_contract, Mapping) else None
    payload: dict[str, Any] = {
        "stage": stage,
        "instruction": instructions,
        "input_slice": sanitize_for_prompt(prompt_input),
        "output_contract": declared_contract if declared_contract is not None else dict(_DEEP_REVIEW_PROMPT_CONTRACT),
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


class ModelClient:
    """승인된 base URL 하나로만 나가는 OpenAI SDK client.

    모델명은 호출자가 준다. 개요·심층 검토는 policy의 `model_name`을,
    C-1은 `BIDOPS_VLLM_SCREENING_MODEL`을 넘긴다.

    **승인 게이트는 이 생성자가 아니라 `resolve_model_endpoint`에 있다**
    (명세 §6.6, ADR-0050). "허용 host가 비었거나 선언 revision이 64자 hex가
    아니면 그 용도는 호출 전에 fail closed한다"는 규칙은 용도별 설정을 푸는
    그 함수가 강제하며, 그래서 `for_purpose`는 client를 **만들기 전에** 멈춘다.
    생성자를 직접 부르는 것은 transport 주입 seam이다 — 허용 host 목록과 선언
    revision을 호출자가 책임지고 넘겨야 하고, 생성자는 그 둘의 존재를 다시
    검사하지 않는다. 운영 경로는 예외 없이 `for_purpose`를 지난다. 직접
    생성하는 제품 코드는 `app/screening/model_adapter.py`의 주입 transport
    한 곳뿐이며, 그곳은 선언 revision을 스스로 64자 hex로 검사한다.

    소유한 `httpx.Client`는 `close()`나 `with` 문으로 닫는다. 버릴 client를
    닫지 않으면 poll마다 연결이 쌓인다.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key: str = "EMPTY",
        allowed_hosts: str | Sequence[str] | None = None,
        completion_create: Callable[..., Any] | None = None,
        models_list: Callable[[], Mapping[str, Any]] | None = None,
        model: str,
        model_revision: str = "",
        endpoint_ref: str = MODEL_ENDPOINT_REF,
        purpose: str | None = None,
        output_contract: StructuredOutputContract,
        api_dialect: str = "vllm",
    ) -> None:
        # transport 식별자만 확인한다. 모델명은 여기서 판정하지 않는다 —
        # 어떤 모델이 승인됐는지는 policy와 배포 설정이 정하고, identity는
        # `verify_identity`가 서버의 served id로 확인한다.
        if endpoint_ref != MODEL_ENDPOINT_REF:
            raise ValueError("only the OpenAI-compatible transport is permitted")
        if not isinstance(model, str) or not model.strip() or any(character.isspace() for character in model):
            raise ValueError("model name must be a non-empty token")
        self.output_contract = output_contract
        if api_dialect not in {"vllm", "ollama"}:
            raise ModelEndpointError("unsupported model API dialect")
        self.api_dialect = api_dialect
        if allowed_hosts is None:
            allowed_hosts = os.getenv("BIDOPS_VLLM_ALLOWED_HOSTS", "").split(",")
        elif isinstance(allowed_hosts, str):
            allowed_hosts = allowed_hosts.split(",")
        self.base_url = _validated_base_url(base_url, allowed_hosts)
        self.model = model
        self.model_revision = model_revision
        self.purpose = purpose
        self.provider_name = "ollama-openai-compatible" if api_dialect == "ollama" else "vllm-openai-compatible"
        self._http_client: httpx.Client | None = None
        self._sdk: OpenAI | None = None
        self._api_key = api_key
        self._models_list = models_list
        if completion_create is not None:
            self._completion_create = completion_create
        else:
            self._http_client = httpx.Client(
                trust_env=False,
                follow_redirects=False,
                event_hooks={"response": [_bounded_response]},
            )
            self._sdk = OpenAI(
                base_url=self.base_url,
                api_key=api_key,
                max_retries=0,
                http_client=self._http_client,
            )
            self._completion_create = self._sdk.chat.completions.create

    @property
    def http_client(self) -> httpx.Client | None:
        """이 client가 소유한 bounded transport (없으면 주입된 호출자)."""

        return self._http_client

    def close(self) -> None:
        """소유한 `httpx.Client`를 닫는다. 주입된 transport는 건드리지 않는다.

        여러 번 불러도 안전하다. 닫은 뒤 호출하면 SDK가 실패하므로 **버리는
        client에만** 쓴다.
        """

        client, self._http_client = self._http_client, None
        self._sdk = None
        if client is not None:
            client.close()

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def sdk_max_retries(self) -> int | None:
        """SDK 자동 재시도 설정. 재시도는 `invoke`가 정책대로만 한다."""

        return None if self._sdk is None else int(self._sdk.max_retries)

    @classmethod
    def for_purpose(
        cls,
        purpose: str,
        *,
        model: str,
        output_contract: StructuredOutputContract,
        settings: Any | None = None,
        completion_create: Callable[..., Any] | None = None,
        models_list: Callable[[], Mapping[str, Any]] | None = None,
        verify_identity: bool = True,
    ) -> "ModelClient":
        """용도별 설정으로 client를 만들고 identity를 확인한다 (명세 §6.6).

        설정 해석이 먼저다. 허용 host나 선언 revision이 없으면 `/models`조차
        부르지 않고 `ModelEndpointError`로 끝난다.
        """

        endpoint = resolve_model_endpoint(purpose, settings=settings)
        client = cls(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key.get_secret_value(),
            allowed_hosts=endpoint.allowed_hosts,
            completion_create=completion_create,
            models_list=models_list,
            model=model,
            model_revision=endpoint.model_revision,
            purpose=endpoint.purpose,
            output_contract=output_contract,
            api_dialect=endpoint.api_dialect,
        )
        if verify_identity:
            client.verify_identity()
        return client

    def _served_models(self) -> Mapping[str, Any]:
        """`GET {base_url}/models`를 bounded transport로 읽는다."""

        if self._models_list is not None:
            return self._models_list()
        if self._http_client is None:
            raise ModelIdentityError("identity_unavailable")
        headers = {"Accept": "application/json"}
        if self._api_key and self._api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = self._http_client.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=float(APPROVED_TIMEOUT_SECONDS),
            )
            if response.is_redirect or response.status_code >= 400:
                raise ModelIdentityError("identity_unavailable")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ModelIdentityError("identity_unavailable")
            document = response.json()
        except ModelIdentityError:
            raise
        except (httpx.HTTPError, ValueError, OSError, ResponseTooLargeError):
            raise ModelIdentityError("identity_unavailable") from None
        if not isinstance(document, Mapping):
            raise ModelIdentityError("identity_unavailable")
        return document

    def verify_identity(self) -> ModelIdentity:
        """served id에 설정·policy 모델명이 있는지 확인한다 (명세 §6.6).

        모델 digest는 배포가 선언한 64자 revision이다(ADR-0042). stock vLLM은
        `/models`에 revision을 싣지 않으므로 **부재는 실패가 아니다.** 값을
        내는 서버(또는 승인된 proxy)만 선언 revision과 대조한다.
        """

        document = self._served_models()
        rows = document.get("data")
        if not isinstance(rows, list):
            raise ModelIdentityError("identity_unavailable")
        served = [row for row in rows if isinstance(row, Mapping) and row.get("id") == self.model]
        if not served:
            raise ModelIdentityError("model_not_served")
        for row in served:
            reported = row.get("model_revision", row.get("revision"))
            if reported is not None and reported != self.model_revision:
                raise ModelIdentityError("model_revision_invalid")
        if self.api_dialect == "ollama":
            self._verify_ollama_parameters()
        return ModelIdentity(model=self.model, revision=self.model_revision)

    def _verify_ollama_parameters(self) -> None:
        # OpenAI compatibility cannot override top_k. Require the immutable
        # model's parameter and digest to match before transmitting a prompt.
        if self._http_client is None:
            raise ModelIdentityError("identity_unavailable")
        origin = self.base_url.removesuffix("/v1")
        try:
            tags = self._http_client.get(f"{origin}/api/tags", timeout=15)
            show = self._http_client.post(f"{origin}/api/show", json={"model": self.model}, timeout=15)
            if tags.is_redirect or show.is_redirect:
                raise ModelIdentityError("identity_unavailable")
            tags.raise_for_status()
            show.raise_for_status()
            models = tags.json().get("models", [])
            matches = [row for row in models if row.get("name") == self.model]
            if len(matches) != 1 or matches[0].get("digest") != self.model_revision:
                raise ModelIdentityError("model_revision_invalid")
            parameters = show.json().get("parameters", "")
            values = re.findall(r"^top_k\s+(\d+)\s*$", parameters, re.MULTILINE)
            if values != [str(APPROVED_GENERATION["top_k"])]:
                raise ModelIdentityError("generation_config_mismatch")
        except ModelIdentityError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, OSError, ResponseTooLargeError):
            raise ModelIdentityError("identity_unavailable") from None

    def _request(self, prompt: str, *, timeout_seconds: int) -> Mapping[str, Any]:
        return self.complete_structured(prompt, timeout_seconds=timeout_seconds)

    def complete_structured(
        self,
        prompt: str,
        *,
        contract: StructuredOutputContract | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int = APPROVED_TIMEOUT_SECONDS,
    ) -> Mapping[str, Any]:
        """구조화 응답 한 번을 요청하고 provider 응답 원형을 낸다.

        `contract`와 `max_tokens`는 호출마다 계약과 출력 예산이 다른 호출부를
        위한 것이다. C-1 판정은 stage마다 응답 schema가 다르고 stage별
        `num_predict` 예산을 `max_tokens`로 넘긴다. 생략하면 이 client가 묶인
        계약과 승인 기본값을 쓴다.

        재시도는 하지 않는다 — 재시도 정책은 `invoke`와 도메인 어댑터가
        각자의 계약대로 소유한다.
        """

        selected = contract or self.output_contract
        if self.api_dialect == "ollama":
            self.verify_identity()
        extra_body = (
            {"reasoning_effort": "none"}
            if self.api_dialect == "ollama"
            else {
                "top_k": APPROVED_GENERATION["top_k"],
                "chat_template_kwargs": {"enable_thinking": APPROVED_GENERATION["enable_thinking"]},
            }
        )
        response = self._completion_create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": selected.system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            temperature=APPROVED_GENERATION["temperature"],
            top_p=APPROVED_GENERATION["top_p"],
            seed=APPROVED_GENERATION["seed"],
            max_tokens=int(APPROVED_GENERATION["max_completion_tokens"] if max_tokens is None else max_tokens),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": selected.name,
                    "strict": True,
                    "schema": selected.schema,
                },
            },
            extra_body=extra_body,
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
        # policy가 모델을 지정했으면 이 client가 묶인 모델과 같아야 한다.
        # 승인 목록을 코드가 아니라 policy가 갖는다는 뜻이다.
        if policy.get("model_endpoint_ref", MODEL_ENDPOINT_REF) != MODEL_ENDPOINT_REF or policy.get("model_name", self.model) != self.model:
            raise ModelInvocationError("model_not_allowed", ())
        chunking = policy.get("chunking") if isinstance(policy.get("chunking"), Mapping) else {}
        try:
            timeout_seconds = int(chunking.get("timeout_seconds", APPROVED_TIMEOUT_SECONDS))
            retries = int(chunking.get("retries", APPROVED_RETRIES))
        except (TypeError, ValueError):
            raise ModelInvocationError("policy_invalid", ()) from None
        if timeout_seconds != APPROVED_TIMEOUT_SECONDS or retries < 0 or retries > APPROVED_RETRIES:
            raise ModelInvocationError("policy_invalid", ())
        if policy.get("generation", APPROVED_GENERATION) != APPROVED_GENERATION:
            raise ModelInvocationError("policy_invalid", ())
        prompt = build_prompt(stage, input_slice, policy, profile=profile, prior_stages=prior_stages)
        input_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        observations: list[dict[str, Any]] = []
        for index in range(retries + 1):
            started = time.monotonic()
            try:
                response = self._request(prompt, timeout_seconds=timeout_seconds)
                if response.get("model") != self.model:
                    raise ValueError("model_mismatch")
                # 응답이 revision을 실어 보내면 배포 선언과 대조한다. stock
                # vLLM은 내지 않으므로 부재는 통과다(ADR-0042). 판단 기준은
                # **응답이 값을 냈는가**이지 배포가 선언했는가가 아니다 —
                # 선언이 비었을 때 통과시키면 서버가 다른 weight를 말해도
                # 그대로 받게 되고, `verify_identity`와도 어긋난다.
                reported_revision = response.get("model_revision", response.get("revision"))
                if reported_revision is not None and reported_revision != self.model_revision:
                    raise ModelIdentityError("model_revision_invalid")
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
            except ModelIdentityError as identity_error:
                code = identity_error.code
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
        raise ModelInvocationError(str(observations[-1].get("error_code", "provider_error")), observations)

__all__ = [
    "APPROVED_GENERATION",
    "APPROVED_RETRIES",
    "APPROVED_TIMEOUT_SECONDS",
    "MAX_COMPLETION_TOKENS",
    "MAX_RESPONSE_BYTES",
    "MODEL_PURPOSES",
    "EncryptedObjectStore",
    "InvocationResult",
    "ModelClient",
    "ModelEndpoint",
    "ModelEndpointError",
    "ModelIdentity",
    "ModelIdentityError",
    "ModelInvocationError",
    "ResponseTooLargeError",
    "StructuredOutputContract",
    "build_prompt",
    "resolve_model_endpoint",
    "sanitize_for_prompt",
]
