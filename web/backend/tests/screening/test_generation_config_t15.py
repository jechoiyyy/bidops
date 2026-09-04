from __future__ import annotations

import json

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
from app.screening.ollama import OllamaCallError, OllamaClient
from tests.fakes import FakeOllamaTransport


def _response() -> dict[str, object]:
    return {
        "model": "qwen3.8:27b",
        "done": True,
        "done_reason": "stop",
        "response": json.dumps({}),
        "prompt_eval_count": 1,
        "eval_count": 1,
        "prompt_eval_duration": 1,
        "eval_duration": 1,
        "load_duration": 1,
        "total_duration": 1,
    }


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


def test_request_payload_and_retry_share_frozen_stage_options_and_telemetry() -> None:
    transport = FakeOllamaTransport([{"model": "qwen3.8:27b", "done": True, "done_reason": "length", "response": "{}"}, _response()])
    client = OllamaClient(transport=transport)
    result = client.generate("p", {}, stage="synthesis")
    assert len(transport.generate_requests) == 2
    assert all(item["payload"]["options"] == {"num_ctx": 16384, "num_predict": 4096} for item in transport.generate_requests)
    assert result.metadata.generation_config_digest == GenerationConfig().digest()
    assert result.metadata.num_ctx == 16384
    assert result.metadata.num_predict == 4096


def test_generation_config_digest_mismatch_fails_before_request() -> None:
    transport = FakeOllamaTransport([_response()])
    with pytest.raises(GenerationConfigError):
        OllamaClient(transport=transport).generate("p", {}, stage="synthesis", generation_config={
            **GenerationConfig().canonical_value(),
            "think": True,
        })
    assert transport.generate_requests == []
