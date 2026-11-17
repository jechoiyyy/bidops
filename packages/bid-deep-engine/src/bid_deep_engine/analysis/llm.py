"""Transport-neutral upstream value/error types. No network factory is provided."""
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict
from .pricing import TokenUsage
from .spend import Purpose, CostBasis

class LlmError(Exception):
    """LLM 호출 오류의 공통 부모."""

class LlmConfigError(LlmError):
    """설정 오류(키 없음). CLI 종료 1."""

class LlmCallError(LlmError):
    """count_tokens 실패 또는 SDK 재시도 후에도 남은 API 오류(cli는 claude 실행 실패, C3).
    응답 usage·원장 기록 없음."""

class _RecordedLlmError(LlmError):
    """응답을 받은 뒤의 실패. `record`는 원장 줄과 같은 값의 CallRecord(X3)."""

    def __init__(self, message: str, slug: str, purpose: str, *, record: "CallRecord") -> None:
        super().__init__(message)
        self.slug = slug
        self.purpose = purpose
        self.record = record

class LlmRefusal(_RecordedLlmError):
    def __init__(self, slug: str, purpose: str, *, record: "CallRecord") -> None:
        super().__init__(
            f"model refused: slug={slug} purpose={purpose}", slug, purpose, record=record
        )

@dataclass(frozen=True, kw_only=True)
class OutputFailure:
    """출력 검증 실패 상세(spec LLM-01 "실패 상세"). 프롬프트는 담지 않는다(제약 7).

    - `response_text`: 마지막 `fallback` 블록 뒤 마지막 text 블록 전문(없으면 None)
    - `json_text`: `_json_object_text` 결과(중괄호가 없거나 텍스트가 없으면 None)
    - `validation_errors`: `ValidationError.errors()`의 `loc`(점 연결)·`msg`·`type`, 최대
      `MAX_VALIDATION_ERRORS`개. `error_count`는 잘리기 전 전체 수
    """

    response_text: str | None
    json_text: str | None
    validation_errors: list[dict[str, str]]
    error_count: int
    kind: Literal["no_text", "no_json", "validation"]

class LlmTruncated(_RecordedLlmError):
    """`response_text`는 잘린 부분 출력(`_response_text`, text 블록이 없으면 None)."""

    def __init__(
        self,
        slug: str,
        purpose: str,
        max_tokens: int | None,
        *,
        record: "CallRecord",
        response_text: str | None,
    ) -> None:
        super().__init__(
            f"output truncated at max_tokens={max_tokens}: slug={slug} purpose={purpose}",
            slug,
            purpose,
            record=record,
        )
        self.max_tokens = max_tokens
        self.response_text = response_text

class LlmOutputError(_RecordedLlmError):
    """`failure`는 텍스트 없음·JSON 없음·스키마 검증 실패의 상세(`OutputFailure`)."""

    def __init__(
        self, slug: str, purpose: str, *, record: "CallRecord", failure: OutputFailure
    ) -> None:
        super().__init__(
            f"output does not match schema: slug={slug} purpose={purpose}",
            slug,
            purpose,
            record=record,
        )
        self.failure = failure

class CallRecord(BaseModel):
    """응답을 받은 호출 1건(usage.json `calls[]` 항목, M3-01 공용). 필드 순서가 JSON 키 순서."""

    model_config = ConfigDict(frozen=True)

    at: str  # ISO 8601 초 단위, 로컬 시간대
    purpose: Purpose
    model: str  # 요청 모델
    served_model: str  # 응답 model(없으면 요청 모델)
    price_model: str | None  # pricing.price_for(served_model).price_model, max_price면 None
    cost_basis: CostBasis
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_5m: int
    cache_creation_1h: int
    input_tokens_counted: int  # 사전 count_tokens 결과
    estimate_usd: float | None  # None when there are no completed gateway output samples
    cost_usd: float  # pricing.cost_usd(served_model, usage), 항상 float
    duration_ms: int
    output_limit: int | None = None
    finish_reason: str | None = None
    model_fingerprint: str | None = None

@dataclass(frozen=True)
class ParseResult:
    """성공 결과. 5필드가 정본(14절 X52) — 비용·시간·추정은 `record`에서 읽는다."""

    parsed: BaseModel
    usage: TokenUsage
    served_model: str
    stop_reason: str
    record: CallRecord

class LlmClient(Protocol):
    def parse(self, **kwargs: Any) -> ParseResult: ...
