from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.generation_config import (
    GenerationConfig,
    GenerationConfigError,
    config_from_value,
    generation_config_from_settings,
    legacy_generation_config,
    validate_digest,
)
from app.screening.model_adapter import ScreeningModelClient
from tests.fakes import FakeScreeningTransport, completion


def _response() -> dict[str, object]:
    return completion({}, usage={"prompt_tokens": 1, "completion_tokens": 1})


def test_canonical_config_digest_is_stable_and_stage_aware() -> None:
    config = GenerationConfig()
    assert config.canonical_json() == (
        '{"num_ctx":16384,"num_predict":{"counterargument":2048,'
        '"perspective":2048,"synthesis":4096},"schema_version":'
        '"bidops.generation-config.v1","stream":false,"think":false}'
    )
    assert config.digest() == "51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1"
    assert validate_digest(config_from_value(config.canonical_value()), config.digest()) == config.digest()
    assert config.budget_for_stage("기술 적합성") == 2048
    assert config.budget_for_stage("counterargument.v1") == 2048
    assert config.budget_for_stage("judgment.v3") == 4096
    assert legacy_generation_config().synthesis_num_predict == 2048


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_ctx": True},
        {"perspective_num_predict": 0},
        {"synthesis_num_predict": 32769},
        {"num_ctx": 100, "synthesis_num_predict": 101},
        {"think": True},
        {"stream": True},
    ],
)
def test_invalid_generation_config_is_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(GenerationConfigError):
        GenerationConfig(**kwargs)  # type: ignore[arg-type]


def test_settings_freeze_uses_synthesis_budget_alias() -> None:
    settings = Settings(model_max_output=2048, model_synthesis_output=4096, model_context=16384)
    config = generation_config_from_settings(settings)
    assert config.stages == {"perspective": 2048, "counterargument": 2048, "synthesis": 4096}


def test_request_payload_and_retry_share_frozen_stage_budget_and_telemetry() -> None:
    """stage별 `num_predict`가 요청에서는 `max_tokens` 하나로만 나타난다.

    `num_ctx`는 OpenAI 호환 대응 파라미터가 없으므로 요청에 실리지 않고
    binding 기록(attempt telemetry)에만 남는다.
    """

    transport = FakeScreeningTransport([completion({}, finish_reason="length"), _response()])
    client = ScreeningModelClient(transport=transport)
    result = client.generate("p", {}, stage="synthesis")
    assert len(transport.generate_requests) == 2
    assert all(item["max_tokens"] == 4096 for item in transport.generate_requests)
    assert all("num_ctx" not in item and "options" not in item for item in transport.generate_requests)
    assert result.metadata.generation_config_digest == GenerationConfig().digest()
    assert result.metadata.num_ctx == 16384
    assert result.metadata.num_predict == 4096


def test_generation_config_digest_mismatch_fails_before_request() -> None:
    transport = FakeScreeningTransport([_response()])
    with pytest.raises(GenerationConfigError):
        ScreeningModelClient(transport=transport).generate("p", {}, stage="synthesis", generation_config={
            **GenerationConfig().canonical_value(),
            "think": True,
        })
    assert transport.generate_requests == []
