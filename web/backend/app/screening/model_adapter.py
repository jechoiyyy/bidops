"""C-1 공고 판정이 통일 모델 client 위에 얹는 얇은 어댑터 (명세 §6.6).

`app/core/model_client.py`가 승인된 사설 OpenAI-compatible 배치로 나가는
유일한 경계다. 이 모듈은 그 위에서 **판정 계약만** 얹는다 — 제한 재시도,
correction prompt, 결정적 validator, attempt telemetry, 그리고
`inspect_model()`이 내는 `ModelIdentity`.

여기에 없는 것이 요점이다. HTTP, 자격증명, 허용 host, 모델명 판정은 core가
소유하고 이 모듈은 알지 못한다. 모델명은 `BIDOPS_VLLM_SCREENING_MODEL`이
정하며 **코드에 고정하지 않는다** — 코드에 박으면 배포가 모델을 바꿀 때
실행 row에 기록된 이름과 실제로 부른 모델이 갈린다.

`ModelIdentity.digest`는 Ollama blob digest가 아니라 **배포가 선언한 64자
revision**이다(ADR-0042). 선언이 비면 모델을 부르는 모든 용도가 fail closed
한다. 7개 logical stage, 호출당 8 attempt 상한, stop, telemetry 계약은
이전과 같다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Any, Callable, Final, Mapping, Protocol

from ..core.config import Settings, get_settings
from ..core.generation_config import (
    GenerationConfig,
    ensure_generation_config,
    generation_config_from_settings,
)
from ..core.model_client import (
    APPROVED_TIMEOUT_SECONDS,
    ModelClient,
    ModelEndpointError,
    ModelIdentityError,
    ResponseTooLargeError,
    StructuredOutputContract,
)
from .contracts import (
    CallMetadata,
    ContractViolation,
    ModelIdentity,
    SYSTEM_MESSAGE,
    add_two_axis_metadata,
    new_span_id,
    new_trace_id,
    parse_json_object,
    validate_counterargument,
    validate_judgment,
    validate_perspective,
)
from .prompts import (
    assemble_counterargument_prompt,
    assemble_perspective_prompt,
    assemble_synthesis_prompt,
    schema_for_stage,
)


class ScreeningTransport(Protocol):
    """어댑터가 소켓 없이 돌 때 주입되는 OpenAI 호환 최소 경계.

    mock 판정 transport(ADR-0029)와 테스트 fake가 이것을 구현한다. 모양은
    provider의 `GET /models`와 `chat.completions.create` 그대로다.
    """

    model_revision: str

    def models(self) -> Mapping[str, Any]: ...

    def create(self, **request: Any) -> Mapping[str, Any]: ...


#: 주입된 transport는 소켓을 열지 않는다. `ModelClient`의 base URL 검증만
#: 통과하면 되므로 loopback 자리표시자를 준다 — 이 주소로 나가는 요청은
#: 없고, 실제 endpoint는 `for_purpose("screening")`이 설정에서 해석한다.
_INJECTED_BASE_URL: Final[str] = "http://127.0.0.1:8000/v1"
_INJECTED_ALLOWED_HOSTS: Final[tuple[str, ...]] = ("127.0.0.1",)

_REVISION_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_RETRYABLE: Final[frozenset[str]] = frozenset(
    {"timeout", "truncated_output", "schema_violation", "evidence_missing"}
)
_TRUNCATION_REASONS: Final[frozenset[str]] = frozenset(
    {"length", "max_tokens", "limit", "truncated", "token_limit"}
)
_STAGES: Final[frozenset[str]] = frozenset(
    {"기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합", "counterargument", "synthesis", "carried_over_validation"}
)


class ModelInspectionError(RuntimeError):
    """enqueue 시점의 모델 identity 확인을 믿을 수 없다."""

    status_code: Final[int] = 503

    def __init__(self, summary: str):
        self.failure_type = "model_inspection"
        self.error_summary = _safe_summary(summary)
        super().__init__(self.error_summary)


class ScreeningCallError(RuntimeError):
    """제한된 모델 호출 실패. 안전한 metadata만 담고 원문 응답은 담지 않는다."""

    def __init__(
        self,
        metadata: CallMetadata,
        *,
        attempts: tuple[CallMetadata, ...] = (),
    ):
        self.metadata = metadata
        self.attempts = attempts or (metadata,)
        self.failure_type = metadata.failure_type
        self.error_summary = metadata.error_summary or "screening model call failed"
        # 모델 출력·프롬프트·HTTP 본문을 이 message에 절대 넣지 않는다.
        super().__init__(self.error_summary)


@dataclass(frozen=True)
class CallResult:
    value: dict[str, Any]
    metadata: CallMetadata
    attempts: tuple[CallMetadata, ...]


@dataclass(frozen=True)
class ScreeningRunResult:
    execution_id: str
    notice_id: str
    trace_id: str
    perspectives: tuple[dict[str, Any], ...]
    counterargument: dict[str, Any]
    judgment: dict[str, Any]
    telemetry: tuple[CallMetadata, ...]


def _safe_summary(value: Any) -> str:
    """본문을 담지 않는 짧은 분류형 요약을 낸다."""

    if isinstance(value, BaseException):
        return f"transport {type(value).__name__}"
    text = str(value).splitlines()[0] if value is not None else "unknown failure"
    # 안정적이고 비민감한 진단 어휘만 남긴다. provider 본문이 로그로 흘러드는
    # 것도 이 정리가 막는다.
    text = re.sub(r"[^0-9A-Za-z가-힣 _.-]", "", text).strip()
    return text[:160] or "unknown failure"


def _token_count(usage: Mapping[str, Any], key: str) -> int | None:
    """usage 값을 보정 없이 읽는다. 없으면 `null`이다."""

    if key not in usage:
        return None
    value = usage[key]
    if type(value) is not int or value < 0:
        raise ContractViolation("model usage contract failed")
    return value


def _aware_now() -> datetime:
    return datetime.now(timezone.utc)


class ScreeningModelClient:
    """통일 client 위의 판정 어댑터: 제한 재시도와 attempt telemetry."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: ScreeningTransport | None = None,
        client: ModelClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_name = self.settings.vllm_screening_model
        self.transport = transport
        self._injected_client = client
        self._client = client
        self.identity: ModelIdentity | None = None

    def _output_contract(self, stage: str, schema: Mapping[str, Any]) -> StructuredOutputContract:
        return StructuredOutputContract(
            name="bidops.screening-stage.v1",
            schema=dict(schema),
            system_prompt=SYSTEM_MESSAGE,
        )

    def _ensure_client(self) -> ModelClient:
        """client를 한 번만 만든다. identity 확인은 `inspect_model`이 한다."""

        if self._client is not None:
            return self._client
        contract = self._output_contract("", {})
        if self.transport is not None:
            revision = getattr(self.transport, "model_revision", "")
            # 주입된 transport도 선언 revision 규칙을 그대로 받는다.
            if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
                raise ModelInspectionError("declared model revision is not a 64 hex digest")
            self._client = ModelClient(
                base_url=_INJECTED_BASE_URL,
                allowed_hosts=_INJECTED_ALLOWED_HOSTS,
                completion_create=self.transport.create,
                models_list=self.transport.models,
                model=self.model_name,
                model_revision=revision,
                purpose="screening",
                output_contract=contract,
            )
            return self._client
        try:
            self._client = ModelClient.for_purpose(
                "screening",
                model=self.model_name,
                output_contract=contract,
                settings=self.settings,
                verify_identity=False,
            )
        except (ModelEndpointError, ValueError):
            # 허용 host나 선언 revision이 없으면 부르기 전에 멈춘다. 다른
            # 주소·provider로 넘어가지 않는다.
            raise ModelInspectionError("screening model endpoint is not configured") from None
        return self._client

    def inspect_model(self, *, refresh: bool = False) -> ModelIdentity:
        """served id에 설정 모델명이 있는지 확인하고 선언 revision을 묶는다."""

        if self.identity is not None and not refresh:
            return self.identity
        if refresh and self._injected_client is None:
            # 배포가 선언한 revision 자체가 바뀌었을 수 있다. refresh는 served
            # id뿐 아니라 **선언의 출처**를 다시 읽는다는 뜻이다.
            self._client = None
        client = self._ensure_client()
        failure_summary: str | None = None
        try:
            identity = client.verify_identity()
        except ModelIdentityError as error:
            failure_summary = f"screening model identity failed {error.code}"
        except (TimeoutError, ConnectionError, OSError, ResponseTooLargeError):
            failure_summary = "screening model identity transport failed"
        except Exception:
            failure_summary = "screening model identity failed"
        if failure_summary is not None:
            # handler 밖에서 올려 raw transport 예외가 `__context__`·`__cause__`
            # 로 남지 않게 한다.
            raise ModelInspectionError(failure_summary)
        self.identity = ModelIdentity(identity.model, identity.revision)
        return self.identity

    verify_model = inspect_model

    def _ensure_identity(self) -> ModelIdentity:
        if self.identity is None:
            return self.inspect_model()
        return self.identity

    def _new_metadata(
        self,
        *,
        execution_id: str,
        notice_id: str,
        stage: str,
        attempt: int,
        trace_id: str,
        span_id: str,
        started_at: datetime,
        generation_config: GenerationConfig | None = None,
        **kwargs: Any,
    ) -> CallMetadata:
        identity = self.identity
        return CallMetadata(
            execution_id=execution_id,
            notice_id=notice_id,
            stage=stage,
            attempt_no=attempt,
            trace_id=trace_id,
            span_id=span_id,
            started_at=started_at,
            finished_at=kwargs.pop("finished_at", None),
            status=kwargs.pop("status", "failure"),
            failure_type=kwargs.pop("failure_type", None),
            done_reason=kwargs.pop("done_reason", None),
            model_name=identity.model_name if identity else self.model_name,
            model_digest=identity.digest if identity else None,
            prompt_eval_count=kwargs.pop("prompt_eval_count", None),
            eval_count=kwargs.pop("eval_count", None),
            # OpenAI 호환 응답에는 서버 측 소요 시간 계측이 없다. 없는 값을
            # client 측 경과 시간으로 채우면 지난 Ollama 회차의 계측과 뜻이
            # 다른 숫자가 같은 컬럼에 섞이므로 `null`로 남긴다.
            prompt_eval_duration_ns=kwargs.pop("prompt_eval_duration_ns", None),
            eval_duration_ns=kwargs.pop("eval_duration_ns", None),
            load_duration_ns=kwargs.pop("load_duration_ns", None),
            total_duration_ns=kwargs.pop("total_duration_ns", None),
            error_summary=kwargs.pop("error_summary", None),
            generation_config_digest=(generation_config.digest() if generation_config is not None else kwargs.pop("generation_config_digest", None)),
            num_ctx=(generation_config.num_ctx if generation_config is not None else kwargs.pop("num_ctx", None)),
            num_predict=(generation_config.budget_for_stage(stage) if generation_config is not None else kwargs.pop("num_predict", None)),
        )

    def _generate_once(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        execution_id: str,
        notice_id: str,
        stage: str,
        attempt: int,
        trace_id: str,
        span_id: str,
        generation_config: GenerationConfig,
    ) -> tuple[dict[str, Any], CallMetadata]:
        started = _aware_now()
        client = self._ensure_client()

        def new_metadata(**kwargs: Any) -> CallMetadata:
            return self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started,
                generation_config=generation_config, **kwargs,
            )

        try:
            response = client.complete_structured(
                prompt,
                contract=self._output_contract(stage, schema),
                # Ollama의 stage별 `num_predict`가 여기서 `max_tokens`가 된다.
                max_tokens=generation_config.budget_for_stage(stage),
                timeout_seconds=APPROVED_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ConnectionError, OSError):
            metadata = new_metadata(
                finished_at=_aware_now(),
                failure_type="timeout",
                error_summary="screening model transport timeout",
            )
            raise ScreeningCallError(metadata) from None
        except ResponseTooLargeError:
            metadata = new_metadata(
                finished_at=_aware_now(),
                failure_type="truncated_output",
                error_summary="screening model response exceeded the response budget",
            )
            raise ScreeningCallError(metadata) from None
        except ModelInspectionError:
            raise
        except Exception:
            # provider·SDK 예외를 여기서 하나로 모은다. `ScreeningAttempt`의
            # failure_type에는 전송 실패를 담을 칸이 `timeout`뿐이므로 분류를
            # 늘리지 않고 이전 계약을 그대로 지킨다. 원문 예외는 남기지 않는다.
            metadata = new_metadata(
                finished_at=_aware_now(),
                failure_type="timeout",
                error_summary="screening model transport failure",
            )
            raise ScreeningCallError(metadata) from None

        finished = _aware_now()
        if not isinstance(response, Mapping):
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model response is not an object",
            ))

        identity = self._ensure_identity()
        if response.get("model") != identity.model_name:
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model response model id mismatch",
            ))
        # 응답이 revision을 실어 보내면 배포 선언과 대조한다. stock vLLM은
        # 내지 않으므로 부재는 통과다(ADR-0042).
        reported_revision = response.get("model_revision", response.get("revision"))
        if reported_revision is not None and reported_revision != identity.digest:
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model response revision mismatch",
            ))

        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model response choice contract failed",
            ))
        choice = choices[0]
        done_reason = choice.get("finish_reason")
        if done_reason is not None and not isinstance(done_reason, str):
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model finish reason is invalid",
            ))
        usage = response.get("usage")
        if usage is not None and not isinstance(usage, Mapping):
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                done_reason=done_reason, error_summary="screening model usage is invalid",
            ))
        try:
            metrics = {
                "prompt_eval_count": _token_count(usage or {}, "prompt_tokens"),
                "eval_count": _token_count(usage or {}, "completion_tokens"),
            }
        except ContractViolation as exc:
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                done_reason=done_reason, error_summary=exc.reason,
            ))
        if done_reason in _TRUNCATION_REASONS:
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="truncated_output",
                error_summary="screening model output was truncated",
                done_reason=done_reason, **metrics,
            ))
        message = choice.get("message")
        if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type="schema_violation",
                error_summary="screening model message content is not text",
                done_reason=done_reason, **metrics,
            ))
        try:
            parsed = parse_json_object(message["content"])
        except ContractViolation as exc:
            raise ScreeningCallError(new_metadata(
                finished_at=finished, failure_type=exc.failure_type, error_summary=exc.reason,
                done_reason=done_reason, **metrics,
            ))
        success = new_metadata(
            finished_at=finished, status="success", done_reason=done_reason, **metrics,
        )
        return parsed, success

    def generate(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        execution_id: str = "",
        notice_id: str = "",
        stage: str = "",
        trace_id: str | None = None,
        validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        correction_prompt: str | None = None,
        attempt_callback: Callable[[CallMetadata], None] | None = None,
        generation_config: GenerationConfig | Mapping[str, Any] | None = None,
    ) -> CallResult:
        """검증된 객체 하나를 만든다. 재시도 정책은 이전과 정확히 같다."""

        if not isinstance(prompt, str) or not prompt:
            raise ValueError("prompt must be nonblank")
        if not isinstance(schema, Mapping):
            raise ValueError("schema must be an object")
        if stage not in _STAGES:
            raise ValueError("stage is not a ScreeningAttempt stage")
        # identity 확인은 enqueue/사용 경계이지 generate transport 실패가
        # 아니다. `ModelInspectionError`를 구분 가능한 채로 둔다.
        self._ensure_identity()
        # 직접 호출부는 생성 경계에서 현재 설정을 한 번 얼린다. 큐를 거친
        # worker는 자기가 보존한 config를 넘기므로 이 fallback에 오지 않는다.
        frozen_config, _config_digest = ensure_generation_config(
            generation_config if generation_config is not None else generation_config_from_settings(self.settings)
        )
        trace = trace_id or new_trace_id()
        attempts: list[CallMetadata] = []
        current_prompt = prompt
        attempt = 1
        while True:
            span = new_span_id()
            try:
                value, metadata = self._generate_once(
                    current_prompt,
                    schema,
                    execution_id=execution_id,
                    notice_id=notice_id,
                    stage=stage,
                    attempt=attempt,
                    trace_id=trace,
                    span_id=span,
                    generation_config=frozen_config,
                )
                if validator is not None:
                    value = validator(value)
                attempts.append(metadata)
                if attempt_callback is not None:
                    attempt_callback(metadata)
                return CallResult(value=value, metadata=metadata, attempts=tuple(attempts))
            except ScreeningCallError as exc:
                metadata = exc.metadata
                new_attempts = exc.attempts if exc.attempts else (metadata,)
                attempts.extend(new_attempts)
                if attempt_callback is not None:
                    for item in new_attempts:
                        attempt_callback(item)
                failure = metadata.failure_type
                if failure not in _RETRYABLE or attempt >= 2:
                    raise ScreeningCallError(metadata, attempts=tuple(attempts)) from None
            except ContractViolation as exc:
                # HTTP attempt 자체는 성공했고 결정적 검증만 실패했다. 원래
                # attempt의 시각과 계측을 보존한 채 상태·유형만 바꾼다.
                metadata = replace(
                    metadata,
                    status="failure",
                    failure_type=exc.failure_type,
                    error_summary=exc.reason,
                )
                attempts.append(metadata)
                if attempt_callback is not None:
                    attempt_callback(metadata)
                failure = exc.failure_type
                if exc.failure_type not in _RETRYABLE or attempt >= 2:
                    raise ScreeningCallError(metadata, attempts=tuple(attempts)) from None
            # correction 재시도는 얼린 입력·schema를 다시 말할 뿐 거부된 응답
            # 본문을 다시 넣지 않는다. timeout·truncation은 같은 프롬프트를
            # 쓰고 schema·evidence 실패만 이 안전한 correction을 쓴다.
            if failure in {"schema_violation", "evidence_missing"}:
                current_prompt = correction_prompt or (
                    prompt
                    + "\n이전 결과는 계약을 충족하지 않았다. 원래 입력만 사용하여 지정된 JSON 스키마를 정확히 다시 출력하라."
                )
            else:
                current_prompt = prompt
            attempt += 1

    call = generate


class ScreeningStageRunner:
    """7개 logical stage(5 + 1 + 1) 호출 조립만 하는 순수 실행기."""

    def __init__(self, client: ScreeningModelClient):
        self.client = client

    def run(
        self,
        *,
        execution_id: str,
        notice_id: str,
        policy: Mapping[str, Any] | Any,
        notice: Mapping[str, Any],
        profile_sections: Mapping[str, Any],
        trace_id: str | None = None,
    ) -> ScreeningRunResult:
        self.client._ensure_identity()
        trace = trace_id or new_trace_id()
        perspectives: list[dict[str, Any]] = []
        telemetry: list[CallMetadata] = []
        for name in (
            "기술 적합성",
            "실적 정합성",
            "공공 SI 적합성",
            "사업성·자격 제약",
            "전략 부합",
        ):
            prompt = assemble_perspective_prompt(policy, name, notice, profile_sections)
            result = self.client.generate(
                prompt.user_message,
                schema_for_stage(name),
                execution_id=execution_id,
                notice_id=notice_id,
                stage=name,
                trace_id=trace,
                validator=lambda value, expected=name: validate_perspective(value, expected_name=expected),
            )
            perspectives.append(result.value)
            telemetry.extend(result.attempts)

        counter_prompt = assemble_counterargument_prompt(policy, notice, perspectives)
        counter_result = self.client.generate(
            counter_prompt.user_message,
            schema_for_stage("counterargument.v1"),
            execution_id=execution_id,
            notice_id=notice_id,
            stage="counterargument",
            trace_id=trace,
            validator=validate_counterargument,
        )
        telemetry.extend(counter_result.attempts)

        synthesis_prompt = assemble_synthesis_prompt(policy, notice, perspectives, counter_result.value)
        synthesis_result = self.client.generate(
            synthesis_prompt.user_message,
            schema_for_stage("judgment.v3"),
            execution_id=execution_id,
            notice_id=notice_id,
            stage="synthesis",
            trace_id=trace,
            validator=lambda value: validate_judgment(value, notice=notice),
        )
        telemetry.extend(synthesis_result.attempts)
        judgment = add_two_axis_metadata(synthesis_result.value)
        return ScreeningRunResult(
            execution_id=execution_id,
            notice_id=notice_id,
            trace_id=trace,
            perspectives=tuple(perspectives),
            counterargument=counter_result.value,
            judgment=judgment,
            telemetry=tuple(telemetry),
        )


__all__ = [
    "CallResult", "ModelInspectionError", "ScreeningCallError", "ScreeningModelClient",
    "ScreeningRunResult", "ScreeningStageRunner", "ScreeningTransport",
]
