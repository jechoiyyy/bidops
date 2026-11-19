"""단가표·비용 계산 테스트(spec M2-01 T12)."""

import pytest

from bid_deep_engine.analysis.pricing import (
    CACHE_WRITE_MULTIPLIER,
    CONSERVATIVE_LIMITS,
    MAX_PRICE,
    MODEL_LIMITS,
    P0_MODEL_IDS,
    PRICES,
    ModelLimits,
    Price,
    TokenUsage,
    cost_usd,
    estimate_usd,
    limits_for,
    max_output_for,
    price_for,
    single_pass_limit,
)

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"


def test_cost_usd_opus_all_components():
    usage = TokenUsage(1000, 2000, 50000, 10000, 60000)
    # (1000*4 + 2000*20 + 50000*0.2 + 10000*4*1.25 + 60000*4*2) / 1e6
    assert cost_usd(OPUS, usage) == pytest.approx(0.584)


def test_cost_usd_sonnet_all_components():
    usage = TokenUsage(1000, 2000, 50000, 10000, 60000)
    assert cost_usd(SONNET, usage) == pytest.approx(0.292)


def test_ag05_t1_cache_read_prices():
    assert PRICES[SONNET].cache_read == 0.10
    assert PRICES[OPUS].cache_read == 0.20
    assert PRICES["claude-opus-5"].cache_read == 0.50
    assert PRICES["claude-opus-4-8"].cache_read == 0.50
    assert MAX_PRICE == Price(5.00, 25.00, 0.50)


def test_ag05_t2_sonnet_cache_read_cost():
    usage = TokenUsage(input_tokens=10192, output_tokens=5, cache_read_input_tokens=122900)
    assert cost_usd(SONNET, usage) == pytest.approx(0.032724)
    assert cost_usd(OPUS, usage) == pytest.approx(0.065448)


def test_estimate_usd_is_upper_bound_for_sonnet():
    estimate = estimate_usd(SONNET, 60000, 16000, "1h")
    actual = cost_usd(SONNET, TokenUsage(input_tokens=60000, output_tokens=16000))
    assert estimate >= actual


def test_estimate_usd_one_hour_and_five_minutes():
    assert estimate_usd(OPUS, 60000, 16000, "1h") == pytest.approx(0.80)
    assert estimate_usd(OPUS, 60000, 16000, "5m") == pytest.approx(0.62)


def test_estimate_usd_is_upper_bound_of_cost_usd():
    est = estimate_usd(OPUS, 60000, 16000, "1h")
    actual = cost_usd(OPUS, TokenUsage(input_tokens=60000, output_tokens=16000))
    assert est >= actual


def test_fallback_target_model_prices():
    assert cost_usd("claude-opus-4-8", TokenUsage(1000, 0, 0, 0, 0)) == pytest.approx(0.005)
    assert cost_usd("claude-opus-5", TokenUsage(0, 1000, 0, 0, 0)) == pytest.approx(0.025)
    assert PRICES["claude-opus-5"].cache_read == 0.50
    assert PRICES["claude-opus-4-8"].cache_read == 0.50


def test_price_for_exact():
    lookup = price_for(OPUS)
    assert lookup.cost_basis == "exact"
    assert lookup.price_model == OPUS
    assert lookup.price == PRICES[OPUS]
    assert lookup.warning is None


def test_price_for_date_suffix_is_stripped():
    lookup = price_for("claude-opus-5-5-20261001")
    assert lookup.cost_basis == "exact"
    assert lookup.price_model == OPUS
    assert lookup.price == PRICES[OPUS]
    assert lookup.warning is None


@pytest.mark.parametrize("model", ["claude-opus-5-5-2026", "claude-x", "", "claude-opus-5-5-"])
def test_price_for_unknown_uses_max_price(model):
    lookup = price_for(model)
    assert lookup.cost_basis == "max_price"
    assert lookup.price_model is None
    assert lookup.price == MAX_PRICE
    assert lookup.warning is not None
    assert f"unpriced model {model}" in lookup.warning


def test_max_price_is_componentwise_max():
    assert MAX_PRICE == Price(5.00, 25.00, 0.50)


def test_unknown_model_cost_does_not_raise():
    cost = cost_usd("claude-x", TokenUsage(1000, 0, 0, 0, 0))
    assert isinstance(cost, float)
    assert cost == pytest.approx(0.005)
    assert isinstance(estimate_usd("claude-x", 1000, 1000, "5m"), float)


def test_constants():
    assert CACHE_WRITE_MULTIPLIER == {"5m": 1.25, "1h": 2.0}
    assert P0_MODEL_IDS == {"opus": OPUS, "sonnet": SONNET}
    assert set(P0_MODEL_IDS.values()) <= set(PRICES)


def test_token_usage_defaults_to_zero():
    assert cost_usd(OPUS, TokenUsage()) == 0.0


# --- LLM-01 모델 한도(T1~T3) ------------------------------------------------------------

LIMIT_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-opus-4-8"]


def test_model_limits_table():
    assert set(MODEL_LIMITS) == set(LIMIT_MODELS) == set(PRICES)
    assert all(v == ModelLimits(1_000_000, 128_000) for v in MODEL_LIMITS.values())
    assert CONSERVATIVE_LIMITS == ModelLimits(256_000, 32_000)


@pytest.mark.parametrize("model", LIMIT_MODELS)
def test_t1_limits_for_known_models(model):
    assert limits_for(model) == (ModelLimits(1_000_000, 128_000), "known")


@pytest.mark.parametrize("model", [f"{m}-20261006" for m in LIMIT_MODELS])
def test_t1_limits_for_strips_date_suffix(model):
    assert limits_for(model) == (ModelLimits(1_000_000, 128_000), "known")


@pytest.mark.parametrize(
    "model", ["claude-x", "claude-opus-5-5-preview", "claude-opus-5-5-2026", ""]
)
def test_t1_limits_for_unknown_is_conservative(model):
    assert limits_for(model) == (ModelLimits(256_000, 32_000), "conservative")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (OPUS, None),
        (SONNET, None),
        (f"{SONNET}-20261006", None),
        ("claude-opus-4-8", None),
        ("claude-x", None),
    ],
)
def test_t2_single_pass_limit(model, expected):
    assert single_pass_limit(model) == expected


@pytest.mark.parametrize(
    ("model", "setting", "expected"),
    [
        (SONNET, 128_000, 128_000),
        (SONNET, 16_000, 16_000),
        (SONNET, 200_000, 128_000),
        ("claude-x", 128_000, 32_000),
        ("claude-x", 16_000, 16_000),
    ],
)
def test_t3_max_output_for_clamps_to_model_max(model, setting, expected):
    assert max_output_for(model, setting) == expected
