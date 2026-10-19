"""승인 실행 프로필 허용 목록 (DEMO-05 STEP-005, 데모 브랜치 범위).

`ModelClient.invoke`가 받는 (호출 timeout, generation) 짝은 정확히 둘이다.

- 기존 300초 / `max_completion_tokens` 16384: 모든 dialect.
- LiteLLM 데모 900초 / 8192(나머지 generation 동일): `litellm` dialect만.

LiteLLM 프로필을 선언한 policy는 다른 dialect의 client에서 **호출 전에**
`policy_invalid`로 막힌다. 두 값을 섞은 짝이나 다른 값은 어느 dialect에서도
받지 않는다. fixture는 전부 합성 값이며 네트워크를 열지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

import pytest

from app.core.model_client import (
    APPROVED_GENERATION,
    LITELLM_MODEL_ENDPOINT_REF,
    ModelClient,
    ModelInvocationError,
    StructuredOutputContract,
)


CONTRACT = StructuredOutputContract(
    name="profile_contract",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"verdict": {"type": "string"}},
        "required": ["verdict"],
    },
    system_prompt="합성 system prompt",
)
MODEL = "local-agent-main"
#: 승인된 LiteLLM 데모 값 (2026-10-13 사용자 승인). 코드 상수를 쓰지 않고
#: 숫자를 직접 적어 승인값 자체가 바뀌면 이 테스트가 잡는다.
LITELLM_TIMEOUT = 900
LITELLM_GENERATION = {**APPROVED_GENERATION, "max_completion_tokens": 8192}
STANDARD_GENERATION = {
    "enable_thinking": False,
    "max_completion_tokens": 16384,
    "seed": 0,
    "temperature": 0.7,
    "top_k": 20,
    "top_p": 0.8,
}


def _completion(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
        }],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


def _client(api_dialect: str, calls: list[dict[str, Any]]) -> ModelClient:
    return ModelClient(
        model=MODEL,
        output_contract=CONTRACT,
        api_dialect=api_dialect,
        completion_create=lambda **kwargs: calls.append(kwargs) or _completion({"verdict": "ok"}),
    )


def _policy(timeout: int, generation: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    """회사 핏 정책처럼 `model_endpoint_ref` 없이 timeout·generation만 선언한다."""

    return {
        "model_name": MODEL,
        "stages": [{"stage": "s1", "instruction": "합성 지시"}],
        "generation": dict(generation),
        "chunking": {"retries": 0, "timeout_seconds": timeout},
        **extra,
    }


def test_standard_generation_constant_is_unchanged() -> None:
    assert APPROVED_GENERATION == STANDARD_GENERATION


def test_litellm_profile_is_sent_with_its_timeout_and_output_budget() -> None:
    calls: list[dict[str, Any]] = []
    client = _client("litellm", calls)
    result = client.invoke("s1", {"item": "합성"}, _policy(LITELLM_TIMEOUT, LITELLM_GENERATION))
    assert result.structured_output == {"verdict": "ok"}
    assert len(calls) == 1
    sent = calls[0]
    assert sent["timeout"] == 900.0
    assert sent["max_tokens"] == 8192
    # 나머지 generation은 승인 기본값 그대로다.
    assert sent["temperature"] == 0.7 and sent["top_p"] == 0.8 and sent["seed"] == 0
    assert sent["extra_body"] == {
        "top_k": 20, "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none",
    }


def test_litellm_profile_also_works_with_the_litellm_endpoint_ref() -> None:
    calls: list[dict[str, Any]] = []
    policy = _policy(LITELLM_TIMEOUT, LITELLM_GENERATION, model_endpoint_ref=LITELLM_MODEL_ENDPOINT_REF)
    assert _client("litellm", calls).invoke("s1", {"item": "합성"}, policy).structured_output == {"verdict": "ok"}
    assert calls[0]["timeout"] == 900.0 and calls[0]["max_tokens"] == 8192


@pytest.mark.parametrize("dialect", ["vllm", "ollama"])
def test_litellm_profile_fails_closed_before_any_call_on_other_dialects(dialect: str) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(dialect, calls)
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("s1", {"item": "합성"}, _policy(LITELLM_TIMEOUT, LITELLM_GENERATION))
    assert error.value.code == "policy_invalid"
    assert error.value.attempts == []
    assert calls == []


@pytest.mark.parametrize("dialect", ["vllm", "litellm"])
def test_standard_profile_is_still_accepted_and_sent_unchanged(dialect: str) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(dialect, calls)
    assert client.invoke("s1", {"item": "합성"}, _policy(300, STANDARD_GENERATION)).structured_output == {
        "verdict": "ok"
    }
    # 생략한 policy도 기존 기본값(300/16384)이다.
    assert client.invoke("s1", {"item": "합성"}, {"model_name": MODEL}).structured_output == {"verdict": "ok"}
    assert [(call["timeout"], call["max_tokens"]) for call in calls] == [(300.0, 16384), (300.0, 16384)]


@pytest.mark.parametrize("dialect", ["vllm", "litellm", "ollama"])
@pytest.mark.parametrize("timeout,generation", [
    # 두 프로필의 값을 섞은 짝은 어느 쪽도 아니다.
    (900, STANDARD_GENERATION),
    (300, LITELLM_GENERATION),
    # 다른 timeout이나 generation 값은 여전히 거부된다.
    (600, STANDARD_GENERATION),
    (1800, LITELLM_GENERATION),
    (900, {**LITELLM_GENERATION, "max_completion_tokens": 4096}),
    (900, {**LITELLM_GENERATION, "temperature": 0.2}),
    (900, {**LITELLM_GENERATION, "enable_thinking": True}),
    (300, {**STANDARD_GENERATION, "max_completion_tokens": 8192, "top_k": 40}),
])
def test_no_other_timeout_generation_pair_is_accepted(dialect: str, timeout: int, generation: dict) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(ModelInvocationError) as error:
        _client(dialect, calls).invoke("s1", {"item": "합성"}, _policy(timeout, generation))
    assert error.value.code == "policy_invalid"
    assert calls == []


def test_retries_bound_is_unchanged_for_the_litellm_profile() -> None:
    calls: list[dict[str, Any]] = []
    policy = _policy(LITELLM_TIMEOUT, LITELLM_GENERATION)
    policy["chunking"]["retries"] = 3
    with pytest.raises(ModelInvocationError) as error:
        _client("litellm", calls).invoke("s1", {"item": "합성"}, policy)
    assert error.value.code == "policy_invalid" and calls == []


def test_the_allow_list_has_exactly_two_dialect_keyed_profiles() -> None:
    from app.core.model_client import APPROVED_EXECUTION_PROFILES, approved_execution_profile

    assert [(p.timeout_seconds, dict(p.generation), sorted(p.api_dialects)) for p in APPROVED_EXECUTION_PROFILES] == [
        (300, STANDARD_GENERATION, ["litellm", "ollama", "vllm"]),
        (900, LITELLM_GENERATION, ["litellm"]),
    ]
    assert approved_execution_profile(
        api_dialect="litellm", timeout_seconds=900, generation=LITELLM_GENERATION
    ) is APPROVED_EXECUTION_PROFILES[1]
    assert approved_execution_profile(api_dialect="vllm", timeout_seconds=900, generation=LITELLM_GENERATION) is None
    assert approved_execution_profile(
        api_dialect="vllm", timeout_seconds=300, generation=STANDARD_GENERATION
    ) is APPROVED_EXECUTION_PROFILES[0]
