"""A small, strict Ollama boundary for the BidOps screening runtime.

This module owns HTTP and model-call telemetry only.  It does not access the
database, the profile artifact, or the filesystem.  The orchestrator supplies
already-frozen notice/profile/policy values and receives pure Python values.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Final, Mapping, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from ..config import Settings, get_settings
from .contracts import (
    CallMetadata,
    ContractViolation,
    FailureType,
    MODEL_NAME,
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


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout: float,
    ) -> Mapping[str, Any]: ...


class OllamaTransport:
    """Stdlib-only transport; constructing it never performs network I/O."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        body = None if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = urllib_request.Request(
            self.base_url + "/" + path.lstrip("/"),
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method=method,
        )
        with urllib_request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured internal endpoint
            raw = response.read()
        malformed = False
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            malformed = True
        if malformed:
            # JSONDecodeError retains the complete response body; do not
            # retain it as exception context.
            raise ValueError("Ollama returned malformed JSON")
        if not isinstance(value, Mapping):
            raise ValueError("Ollama response must be an object")
        return value


class ModelInspectionError(RuntimeError):
    """The enqueue-time model tag/digest inspection could not be trusted."""

    status_code: Final[int] = 503

    def __init__(self, summary: str):
        self.failure_type = "model_inspection"
        self.error_summary = _safe_summary(summary)
        super().__init__(self.error_summary)


class OllamaCallError(RuntimeError):
    """A bounded model-call failure with safe metadata and no raw response."""

    def __init__(
        self,
        metadata: CallMetadata,
        *,
        attempts: tuple[CallMetadata, ...] = (),
    ):
        self.metadata = metadata
        self.attempts = attempts or (metadata,)
        self.failure_type = metadata.failure_type
        self.error_summary = metadata.error_summary or "Ollama call failed"
        # Never include model output, prompt, or HTTP body in this message.
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


_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_RETRYABLE: Final[frozenset[str]] = frozenset(
    {"timeout", "truncated_output", "schema_violation", "evidence_missing"}
)
_TRUNCATION_REASONS: Final[frozenset[str]] = frozenset(
    {"length", "max_tokens", "limit", "truncated", "token_limit"}
)
_STAGES: Final[frozenset[str]] = frozenset(
    {"기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합", "counterargument", "synthesis", "carried_over_validation"}
)


def _safe_summary(value: Any) -> str:
    """Return a short category-like summary without untrusted body text."""

    if isinstance(value, BaseException):
        name = type(value).__name__
        if isinstance(value, (TimeoutError, urllib_error.URLError, ConnectionError, OSError)):
            return f"transport {name}"
        return f"transport {name}"
    text = str(value).splitlines()[0] if value is not None else "unknown failure"
    # Keep only a stable, non-sensitive diagnostic vocabulary.  This also
    # prevents a server body accidentally flowing into logs.
    text = re.sub(r"[^0-9A-Za-z가-힣 _.-]", "", text).strip()
    return text[:160] or "unknown failure"


def _metric(payload: Mapping[str, Any], key: str) -> int | None:
    """Read an Ollama metric without coercion or fabricated defaults."""

    if key not in payload:
        return None
    value = payload[key]
    if type(value) is not int or value < 0:
        raise ContractViolation("Ollama metric contract failed")
    return value


def _done_reason(payload: Mapping[str, Any]) -> str | None:
    if "done_reason" not in payload:
        return None
    value = payload["done_reason"]
    if not isinstance(value, str):
        raise ContractViolation("Ollama done reason contract failed")
    return value


def _aware_now() -> datetime:
    return datetime.now(timezone.utc)


class OllamaClient:
    """Strict `/api/tags` + `/api/generate` client with bounded retries."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if self.settings.model_name != MODEL_NAME:
            raise ValueError(f"only {MODEL_NAME} is permitted")
        self.transport: Transport = transport or OllamaTransport(self.settings.model_base_url)
        self.identity: ModelIdentity | None = None

    def inspect_model(self) -> ModelIdentity:
        """Resolve the exact model from Ollama's real ``/api/tags`` shape."""

        if self.identity is not None:
            return self.identity
        failure_summary: str | None = None
        try:
            response = self.transport.request(
                "GET",
                "/api/tags",
                None,
                timeout=float(self.settings.model_timeout),
            )
        except (TimeoutError, ConnectionError, OSError, urllib_error.URLError):
            failure_summary = "Ollama model inspection transport failed"
        except Exception:
            failure_summary = "Ollama model inspection failed"
        if failure_summary is not None:
            # Raise after leaving the handler so no raw transport exception is
            # retained as ``__context__`` or ``__cause__``.
            raise ModelInspectionError(failure_summary)
        if not isinstance(response, Mapping) or not isinstance(response.get("models"), list):
            raise ModelInspectionError("Ollama model inspection returned no object")
        matches = [
            item for item in response["models"]
            if isinstance(item, Mapping)
            and item.get("name", item.get("model")) == MODEL_NAME
            and item.get("model", item.get("name")) == MODEL_NAME
        ]
        if len(matches) != 1:
            raise ModelInspectionError("Ollama model tag is missing or ambiguous")
        digest = matches[0].get("digest")
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            raise ModelInspectionError("Ollama model digest is not a lowercase SHA-256")
        self.identity = ModelIdentity(MODEL_NAME, digest)
        return self.identity

    verify_model = inspect_model

    def _ensure_identity(self) -> ModelIdentity:
        if self.identity is None:
            return self.inspect_model()
        return self.identity

    def _request_payload(self, prompt: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        identity = self._ensure_identity()
        # Build a fresh object each attempt; callers cannot mutate future
        # attempts or the original prompt inputs.
        return {
            "model": identity.model_name,
            "prompt": prompt,
            "system": SYSTEM_MESSAGE,
            "stream": False,
            "think": False,
            "format": deepcopy(dict(schema)),
            "keep_alive": self.settings.model_keep_alive,
            "options": {
                "num_ctx": self.settings.model_context,
                "num_predict": self.settings.model_max_output,
            },
        }

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
            model_name=identity.model_name if identity else MODEL_NAME,
            model_digest=identity.digest if identity else None,
            prompt_eval_count=kwargs.pop("prompt_eval_count", None),
            eval_count=kwargs.pop("eval_count", None),
            prompt_eval_duration_ns=kwargs.pop("prompt_eval_duration_ns", None),
            eval_duration_ns=kwargs.pop("eval_duration_ns", None),
            load_duration_ns=kwargs.pop("load_duration_ns", None),
            total_duration_ns=kwargs.pop("total_duration_ns", None),
            error_summary=kwargs.pop("error_summary", None),
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
    ) -> tuple[dict[str, Any], CallMetadata]:
        started = _aware_now()
        try:
            response = self.transport.request(
                "POST",
                "/api/generate",
                self._request_payload(prompt, schema),
                timeout=float(self.settings.model_timeout),
            )
        except (TimeoutError, ConnectionError, OSError, urllib_error.URLError) as exc:
            finished = _aware_now()
            metadata = self._new_metadata(
                execution_id=execution_id,
                notice_id=notice_id,
                stage=stage,
                attempt=attempt,
                trace_id=trace_id,
                span_id=span_id,
                started_at=started,
                finished_at=finished,
                failure_type="timeout",
                error_summary="Ollama generate transport timeout",
            )
            raise OllamaCallError(metadata) from None
        except ValueError:
            finished = _aware_now()
            metadata = self._new_metadata(
                execution_id=execution_id,
                notice_id=notice_id,
                stage=stage,
                attempt=attempt,
                trace_id=trace_id,
                span_id=span_id,
                started_at=started,
                finished_at=finished,
                failure_type="schema_violation",
                error_summary="Ollama response decoding failed",
            )
            raise OllamaCallError(metadata) from None
        except ModelInspectionError:
            raise
        except Exception:
            finished = _aware_now()
            metadata = self._new_metadata(
                execution_id=execution_id,
                notice_id=notice_id,
                stage=stage,
                attempt=attempt,
                trace_id=trace_id,
                span_id=span_id,
                started_at=started,
                finished_at=finished,
                failure_type="timeout",
                error_summary="Ollama generate transport failure",
            )
            raise OllamaCallError(metadata) from None

        finished = _aware_now()
        if not isinstance(response, Mapping):
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary="Ollama response is not an object",
            )
            raise OllamaCallError(failure)

        returned_model = response.get("model")
        if returned_model != MODEL_NAME:
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary="Ollama response model tag mismatch",
                done_reason=response.get("done_reason") if isinstance(response.get("done_reason"), str) else None,
            )
            raise OllamaCallError(failure)
        if "digest" in response and (
            not isinstance(response["digest"], str)
            or not _DIGEST_RE.fullmatch(response["digest"])
            or response["digest"] != self.identity.digest
        ):
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary="Ollama response model digest mismatch",
            )
            raise OllamaCallError(failure)

        try:
            done_reason = _done_reason(response)
            metrics = {
                "prompt_eval_count": _metric(response, "prompt_eval_count"),
                "eval_count": _metric(response, "eval_count"),
                "prompt_eval_duration_ns": _metric(response, "prompt_eval_duration"),
                "eval_duration_ns": _metric(response, "eval_duration"),
                "load_duration_ns": _metric(response, "load_duration"),
                "total_duration_ns": _metric(response, "total_duration"),
            }
        except ContractViolation as exc:
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary=exc.reason,
            )
            raise OllamaCallError(failure)
        if type(response.get("done")) is not bool:
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary="Ollama response done flag is invalid",
                done_reason=done_reason, **metrics,
            )
            raise OllamaCallError(failure)
        if response.get("done") is False or done_reason in _TRUNCATION_REASONS:
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="truncated_output", error_summary="Ollama output was truncated",
                done_reason=done_reason, **metrics,
            )
            raise OllamaCallError(failure)
        raw = response.get("response")
        if not isinstance(raw, str):
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type="schema_violation", error_summary="Ollama response field is not text",
                done_reason=done_reason, **metrics,
            )
            raise OllamaCallError(failure)
        try:
            parsed = parse_json_object(raw)
        except ContractViolation as exc:
            failure = self._new_metadata(
                execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
                trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
                failure_type=exc.failure_type, error_summary=exc.reason,
                done_reason=done_reason, **metrics,
            )
            raise OllamaCallError(failure)
        success = self._new_metadata(
            execution_id=execution_id, notice_id=notice_id, stage=stage, attempt=attempt,
            trace_id=trace_id, span_id=span_id, started_at=started, finished_at=finished,
            status="success", done_reason=done_reason, **metrics,
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
    ) -> CallResult:
        """Generate one validated object, with the exact bounded retry policy."""

        if not isinstance(prompt, str) or not prompt:
            raise ValueError("prompt must be nonblank")
        if not isinstance(schema, Mapping):
            raise ValueError("schema must be an object")
        if stage not in _STAGES:
            raise ValueError("stage is not a ScreeningAttempt stage")
        # Model inspection is an enqueue/use boundary, not a generate
        # transport failure.  Keep ModelInspectionError distinguishable.
        self._ensure_identity()
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
                )
                if validator is not None:
                    value = validator(value)
                attempts.append(metadata)
                return CallResult(value=value, metadata=metadata, attempts=tuple(attempts))
            except OllamaCallError as exc:
                metadata = exc.metadata
                attempts.extend(exc.attempts if exc.attempts != (metadata,) else (metadata,))
                failure = metadata.failure_type
                if failure not in _RETRYABLE or attempt >= 2:
                    raise OllamaCallError(metadata, attempts=tuple(attempts)) from None
            except ContractViolation as exc:
                # The HTTP attempt itself succeeded; only deterministic
                # validation failed.  Preserve the original attempt timing and
                # metrics while changing its status/type.
                metadata = replace(
                    metadata,
                    status="failure",
                    failure_type=exc.failure_type,
                    error_summary=exc.reason,
                )
                attempts.append(metadata)
                failure = exc.failure_type
                if exc.failure_type not in _RETRYABLE or attempt >= 2:
                    raise OllamaCallError(metadata, attempts=tuple(attempts)) from None
            # Correction retries restate the frozen input/schema, never the
            # rejected response body.  Timeout/truncation use the identical
            # prompt; schema/evidence failures use this safe correction.
            if failure in {"schema_violation", "evidence_missing"}:
                current_prompt = correction_prompt or (
                    prompt
                    + "\n이전 결과는 계약을 충족하지 않았다. 원래 입력만 사용하여 지정된 JSON 스키마를 정확히 다시 출력하라."
                )
            else:
                current_prompt = prompt
            attempt += 1

    call = generate


class ScreeningOrchestrator:
    """Pure seven-stage (5 + 1 + 1) screening call assembly."""

    def __init__(self, client: OllamaClient):
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
        identity = self.client._ensure_identity()
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


ScreeningRunner = ScreeningOrchestrator


__all__ = [
    "CallResult", "ModelInspectionError", "OllamaCallError", "OllamaClient", "OllamaTransport",
    "ScreeningOrchestrator", "ScreeningRunResult", "ScreeningRunner", "Transport",
]
