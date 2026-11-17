"""Claude API 단가표와 비용 계산(spec M2-01 "단가표").

단가 출처: Anthropic 공식 가격표(https://platform.claude.com/docs/en/about-claude/pricing,
2026-10-27 확인). 단가를 바꿀 때는 출처와 함께 갱신한다.
미지 모델은 예외 대신 알려진 최대 단가(`MAX_PRICE`)로 계산하고 `cost_basis="max_price"`로
표시한다(계약 시트 13절 X4 — 임의 가정 단가가 아니라 표에서 알려진 최대치). 반올림하지 않는다.
"""

import re
from dataclasses import dataclass
from typing import Literal

from bid_deep_engine.model_catalog import ModelCatalog


@dataclass(frozen=True)
class Price:
    """USD per MTok."""

    input: float
    output: float
    cache_read: float


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),  # cache hits $0.20/MTok
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.10),  # cache hits $0.10/MTok
    # 서버측 fallbacks 대상 모델(응답 served_model로만 등장, 직접 요청하지 않음).
    "claude-opus-5": Price(input=5.00, output=25.00, cache_read=0.50),  # cache hits $0.50/MTok
    "claude-opus-4-8": Price(input=5.00, output=25.00, cache_read=0.50),  # cache hits $0.50/MTok
}

# PRICES 성분별 최댓값(현재 5.00/25.00/0.50).
MAX_PRICE = Price(
    input=max(p.input for p in PRICES.values()),
    output=max(p.output for p in PRICES.values()),
    cache_read=max(p.cache_read for p in PRICES.values()),
)

CACHE_WRITE_MULTIPLIER: dict[str, float] = {"5m": 1.25, "1h": 2.0}  # x input 단가

P0_MODEL_IDS: dict[str, str] = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"}

_DATE_SUFFIX = re.compile(r"-\d{8}$")


@dataclass(frozen=True)
class PriceLookup:
    price: Price
    price_model: str | None  # 단가를 찾은 PRICES 키. max_price면 None
    cost_basis: Literal["exact", "max_price"]
    warning: str | None


def price_for(model_id: str, catalog: ModelCatalog | None = None) -> PriceLookup:
    """정확 일치 -> 날짜 접미사(`-YYYYMMDD`) 제거 후 일치 -> `MAX_PRICE`(계약 시트 13절 X4)."""
    if catalog is not None:
        try:
            spec = catalog.resolve(model_id)
            price = Price(
                spec.input_per_token * 1e6,
                spec.output_per_token * 1e6,
                spec.cache_read_per_token * 1e6,
            )
            return PriceLookup(price, spec.upstream, "exact", None)
        except ValueError:
            return PriceLookup(
                MAX_PRICE, None, "max_price", f"unpriced gateway response model: {model_id}"
            )
    if model_id in PRICES:
        return PriceLookup(PRICES[model_id], model_id, "exact", None)
    stripped = _DATE_SUFFIX.sub("", model_id)
    if stripped in PRICES:
        return PriceLookup(PRICES[stripped], stripped, "exact", None)
    return PriceLookup(
        MAX_PRICE,
        None,
        "max_price",
        f"unpriced model {model_id}: cost at max known price",
    )


@dataclass(frozen=True)
class ModelLimits:
    """모델 컨텍스트 창과 최대 출력 토큰(LLM-01 spec "모델 한도")."""

    context_tokens: int
    max_output_tokens: int


# 출처: claude-api 스킬(2026-10-06 캐시) 모델 표 — 네 모델 모두 컨텍스트 1M·최대 출력 128K.
MODEL_LIMITS: dict[str, ModelLimits] = {
    "claude-opus-5-5": ModelLimits(1_000_000, 128_000),
    "claude-sonnet-5-5": ModelLimits(1_000_000, 128_000),
    "claude-opus-5": ModelLimits(1_000_000, 128_000),
    "claude-opus-4-8": ModelLimits(1_000_000, 128_000),
}

# 미지 모델은 256k 대비책(tech-stack 공통 계약 5): 컨텍스트 256k·출력 32k로 본다.
CONSERVATIVE_LIMITS = ModelLimits(256_000, 32_000)


def limits_for(model_id: str) -> tuple[ModelLimits, Literal["known", "conservative"]]:
    """정확 일치 -> 날짜 접미사 제거 후 일치 -> `CONSERVATIVE_LIMITS`(`price_for`와 같은 정규화)."""
    if model_id in MODEL_LIMITS:
        return MODEL_LIMITS[model_id], "known"
    stripped = _DATE_SUFFIX.sub("", model_id)
    if stripped in MODEL_LIMITS:
        return MODEL_LIMITS[stripped], "known"
    return CONSERVATIVE_LIMITS, "conservative"


def single_pass_limit(model_id: str, catalog: ModelCatalog | None = None) -> None:
    """앱의 single 입력 상한은 없다. 벤치 결과의 기존 필드에는 null을 기록한다."""
    return None


def max_output_for(model_id: str, setting: int) -> int:
    """`max_tokens`로 보낼 값: 설정값을 모델 최대 출력으로 자른다."""
    return min(setting, limits_for(model_id)[0].max_output_tokens)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_5m: int = 0
    cache_creation_1h: int = 0


def cost_usd(model: str, usage: TokenUsage, catalog: ModelCatalog | None = None) -> float:
    """실제 사용량 비용(USD). 미지 모델은 `MAX_PRICE`로 계산하며 예외를 내지 않는다."""
    if catalog is not None:
        try:
            spec = catalog.resolve(model)
        except ValueError:
            return cost_usd(model, usage)
        if usage.cache_creation_5m and spec.cache_write_per_token is None:
            raise ValueError(f"cache write price unavailable: {model}")
        if usage.cache_creation_1h and spec.cache_write_1h_per_token is None:
            raise ValueError(f"1h cache write price unavailable: {model}")
        return (
            usage.input_tokens * spec.input_per_token
            + usage.output_tokens * spec.output_per_token
            + usage.cache_read_input_tokens * spec.cache_read_per_token
            + usage.cache_creation_5m * (spec.cache_write_per_token or 0)
            + usage.cache_creation_1h * (spec.cache_write_1h_per_token or 0)
        )
    p = price_for(model).price
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_input_tokens * p.cache_read
        + usage.cache_creation_5m * p.input * CACHE_WRITE_MULTIPLIER["5m"]
        + usage.cache_creation_1h * p.input * CACHE_WRITE_MULTIPLIER["1h"]
    ) / 1_000_000


def estimate_usd(
    model: str, input_tokens: int, max_output_tokens: int, cache_ttl: Literal["5m", "1h"]
) -> float:
    """호출 전 추정(USD): 입력 전부가 캐시 쓰기로 과금되고 출력은 세 번째 인자만큼 나온다고 본다.

    세 번째 인자는 추정 출력이다(LLM-01 D2 — `LlmClient.expected_output_tokens`, 표본이 없으면
    클램프된 max_tokens 전부). 시그니처는 그대로 둔다.
    """
    p = price_for(model).price
    return (
        input_tokens * p.input * CACHE_WRITE_MULTIPLIER[cache_ttl] + max_output_tokens * p.output
    ) / 1_000_000
