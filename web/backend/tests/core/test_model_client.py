"""통일 모델 client의 경계 검사 (명세 §6.6).

여기서 지키는 것은 transport 하나뿐이다. 어떤 모델을 부를지는 용도별 설정과
policy가 정하고, client는 그것을 검증만 한다. 그래서 이 파일은 **코드에 고정된
모델명이 없다는 것**과 **설정이 비면 fail closed한다는 것**을 먼저 본다.

fixture는 전부 합성 텍스트다. 실제 endpoint·프롬프트·응답 원문을 넣지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

import pytest

from app.core.config import Settings
from app.core.model_client import (
    MAX_RESPONSE_BYTES,
    MODEL_PURPOSES,
    ModelClient,
    ModelEndpoint,
    ModelEndpointError,
    ModelIdentity,
    ModelIdentityError,
    ModelInvocationError,
    StructuredOutputContract,
    resolve_model_endpoint,
)


REVISION = "a" * 64
OTHER_REVISION = "b" * 64
CONTRACT = StructuredOutputContract(
    name="test_contract",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"verdict": {"type": "string"}},
        "required": ["verdict"],
    },
    system_prompt="합성 system prompt",
)
POLICY: dict[str, Any] = {
    "model_endpoint_ref": "vllm-openai-compatible",
    "model_name": "합성-모델-a",
    "stages": [{"stage": "s1", "instruction": "합성 지시"}],
}


def _settings(**overrides: Any) -> Settings:
    """공유 기본값만 채운 설정 객체를 만든다."""

    base: dict[str, Any] = {
        "vllm_base_url": "http://127.0.0.1:8000/v1",
        "vllm_allowed_hosts": "127.0.0.1",
        "vllm_api_key": "shared-key",
        "vllm_model_revision": REVISION,
    }
    base.update(overrides)
    return Settings(**base)


def _completion(model: str, payload: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    """한 번의 성공 응답 문서를 만든다."""

    document = {
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }
    document.update(extra)
    return document


# --- 용도별 설정 해석 ------------------------------------------------------


def test_every_purpose_falls_back_to_the_shared_endpoint() -> None:
    """용도별 override가 없으면 세 용도 모두 공유 설정을 그대로 쓴다."""

    settings = _settings()
    for purpose in MODEL_PURPOSES:
        endpoint = resolve_model_endpoint(purpose, settings=settings)
        assert isinstance(endpoint, ModelEndpoint)
        assert endpoint.purpose == purpose
        assert endpoint.base_url == "http://127.0.0.1:8000/v1"
        assert endpoint.allowed_hosts == ("127.0.0.1",)
        assert endpoint.api_key.get_secret_value() == "shared-key"
        assert endpoint.model_revision == REVISION


def test_purpose_override_replaces_only_the_declared_fields() -> None:
    """선언한 override 항목만 바뀌고 나머지는 공유값이 남는다."""

    settings = _settings(
        vllm_deep_review_base_url="http://127.0.0.2:8001/v1",
        vllm_deep_review_allowed_hosts="127.0.0.2",
        vllm_deep_review_model_revision=OTHER_REVISION,
    )
    endpoint = resolve_model_endpoint("deep_review", settings=settings)
    assert endpoint.base_url == "http://127.0.0.2:8001/v1"
    assert endpoint.allowed_hosts == ("127.0.0.2",)
    assert endpoint.model_revision == OTHER_REVISION
    # api_key는 override하지 않았으므로 공유값이 남는다.
    assert endpoint.api_key.get_secret_value() == "shared-key"
    # 다른 용도는 override의 영향을 받지 않는다.
    assert resolve_model_endpoint("screening", settings=settings).base_url == "http://127.0.0.1:8000/v1"


def test_empty_allowed_hosts_fails_closed() -> None:
    """허용 host가 비면 그 용도의 client 생성 자체가 실패한다."""

    settings = _settings(vllm_allowed_hosts="")
    for purpose in MODEL_PURPOSES:
        with pytest.raises(ModelEndpointError):
            resolve_model_endpoint(purpose, settings=settings)


def test_one_purpose_failing_closed_does_not_open_the_others() -> None:
    """override를 가진 용도만 살아남고 나머지는 fail closed한다.

    공유 허용 host가 비었는데 한 용도만 override를 갖는 배포에서, 나머지
    용도가 그 override로 새어 나가지 않는지 본다.
    """

    settings = _settings(vllm_allowed_hosts="", vllm_screening_allowed_hosts="127.0.0.1")
    assert resolve_model_endpoint("screening", settings=settings).allowed_hosts == ("127.0.0.1",)
    for purpose in ("overview", "deep_review"):
        with pytest.raises(ModelEndpointError):
            resolve_model_endpoint(purpose, settings=settings)


def test_missing_declared_revision_fails_closed() -> None:
    """선언 revision이 비면 모델을 부르는 모든 용도가 fail closed한다."""

    settings = _settings(vllm_model_revision="")
    for purpose in MODEL_PURPOSES:
        with pytest.raises(ModelEndpointError):
            resolve_model_endpoint(purpose, settings=settings)


def test_declared_revision_must_be_64_hex() -> None:
    """선언 revision은 배포가 확인한 64자 digest여야 한다 (ADR-0042)."""

    with pytest.raises(ModelEndpointError):
        resolve_model_endpoint("screening", settings=_settings(vllm_model_revision="not-a-digest"))


def test_unknown_purpose_is_rejected() -> None:
    """용도 이름은 명세 §5의 셋뿐이다."""

    assert MODEL_PURPOSES == ("screening", "overview", "deep_review")
    with pytest.raises(ModelEndpointError):
        resolve_model_endpoint("bid_delta", settings=_settings())


def test_resolved_endpoint_never_repeats_the_api_key_in_its_repr() -> None:
    """설정 객체를 로그에 흘려도 비밀값이 따라 나가지 않는다."""

    endpoint = resolve_model_endpoint("screening", settings=_settings())
    assert "shared-key" not in repr(endpoint)


# --- 설정 필드 ------------------------------------------------------------


def test_shared_vllm_model_setting_is_gone() -> None:
    """`BIDOPS_VLLM_MODEL`은 제거됐다. 모델명은 policy와 용도별 설정이 정한다."""

    assert "vllm_model" not in Settings.model_fields
    aliases = {
        str(field.validation_alias)
        for field in Settings.model_fields.values()
        if field.validation_alias is not None
    }
    assert "BIDOPS_VLLM_MODEL" not in aliases


def test_screening_model_is_configurable() -> None:
    """C-1 모델명은 `BIDOPS_VLLM_SCREENING_MODEL`이다."""

    assert Settings().vllm_screening_model == "qwen3.8-27B"
    assert Settings(vllm_screening_model="합성-모델-b").vllm_screening_model == "합성-모델-b"


# --- transport 경계 --------------------------------------------------------


def test_client_accepts_any_configured_model_name() -> None:
    """client는 모델명을 코드에 고정하지 않는다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
    )
    assert client.model == "합성-모델-a"
    result = client.invoke("s1", {"item": "합성"}, POLICY)
    assert result.structured_output == {"verdict": "ok"}
    assert result.model == "합성-모델-a"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8000/v1/chat",
        "https://127.0.0.1:8000/v1",
        "http://198.51.100.7:8000/v1",
        "http://127.0.0.1:8000/v1?x=1",
    ],
)
def test_base_url_must_be_an_allowlisted_v1_endpoint(base_url: str) -> None:
    """redirect·다른 host·다른 path로 새지 않도록 base URL을 좁게 검증한다."""

    with pytest.raises(ValueError):
        ModelClient(model="합성-모델-a", output_contract=CONTRACT, base_url=base_url, allowed_hosts="127.0.0.1")


def test_transport_disables_redirects_environment_proxy_and_sdk_retries() -> None:
    """SDK 자동 재시도·환경 proxy·redirect는 모두 꺼져 있어야 한다."""

    client = ModelClient(model="합성-모델-a", output_contract=CONTRACT, allowed_hosts="127.0.0.1")
    transport = client.http_client
    assert transport is not None
    assert transport.trust_env is False
    assert transport.follow_redirects is False
    assert client.sdk_max_retries == 0


def test_request_body_pins_a_strict_json_schema() -> None:
    """응답 구조는 strict json_schema로 제한한다."""

    seen: dict[str, Any] = {}

    def completion_create(**kwargs: Any) -> Mapping[str, Any]:
        seen.update(kwargs)
        return _completion("합성-모델-a", {"verdict": "ok"})

    ModelClient(model="합성-모델-a", output_contract=CONTRACT, completion_create=completion_create).invoke(
        "s1", {"item": "합성"}, POLICY
    )
    assert seen["model"] == "합성-모델-a"
    assert seen["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "test_contract", "strict": True, "schema": CONTRACT.schema},
    }
    assert [message["role"] for message in seen["messages"]] == ["system", "user"]
    assert seen["timeout"] == 300.0


def test_oversized_response_is_rejected() -> None:
    """응답 상한을 넘으면 결과를 만들지 않고 분류된 오류로 끝난다."""

    oversized = _completion("합성-모델-a", {"verdict": "가" * (MAX_RESPONSE_BYTES // 2)})
    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        completion_create=lambda **_kwargs: oversized,
    )
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("s1", {"item": "합성"}, {**POLICY, "chunking": {"retries": 0, "timeout_seconds": 300}})
    assert error.value.code == "response_too_large"


def test_reported_revision_mismatch_fails_the_invocation() -> None:
    """응답이 revision을 실어 보내면 선언 revision과 대조한다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=REVISION,
        completion_create=lambda **_kwargs: _completion(
            "합성-모델-a", {"verdict": "ok"}, model_revision=OTHER_REVISION
        ),
    )
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("s1", {"item": "합성"}, {**POLICY, "chunking": {"retries": 0, "timeout_seconds": 300}})
    assert error.value.code == "model_revision_invalid"


def test_reported_revision_without_a_declared_one_fails_closed() -> None:
    """선언 revision이 비었는데 서버가 값을 내면 통과시키지 않는다.

    기준은 응답이 값을 냈는가다. 선언이 비었다고 대조를 건너뛰면 서버가
    어떤 weight를 말해도 그대로 받게 되고, `verify_identity`와 판단이
    갈린다.
    """

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision="",
        completion_create=lambda **_kwargs: _completion(
            "합성-모델-a", {"verdict": "ok"}, model_revision=REVISION
        ),
    )
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("s1", {"item": "합성"}, {**POLICY, "chunking": {"retries": 0, "timeout_seconds": 300}})
    assert error.value.code == "model_revision_invalid"


@pytest.mark.parametrize("declared", ["", REVISION])
def test_absent_reported_revision_passes_whatever_was_declared(declared: str) -> None:
    """응답이 revision을 내지 않으면 선언값과 무관하게 통과한다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=declared,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
    )
    assert client.invoke("s1", {"item": "합성"}, POLICY).structured_output == {"verdict": "ok"}


def test_reported_revision_match_passes() -> None:
    """선언 revision과 같은 값을 실어 보내면 통과한다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=REVISION,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}, model_revision=REVISION),
    )
    assert client.invoke("s1", {"item": "합성"}, POLICY).structured_output == {"verdict": "ok"}


# --- identity --------------------------------------------------------------


def test_identity_requires_the_model_in_the_served_ids() -> None:
    """`/models`의 served id에 설정 모델명이 없으면 `model_not_served`다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=REVISION,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
        models_list=lambda: {"data": [{"id": "합성-모델-z"}]},
    )
    with pytest.raises(ModelIdentityError) as error:
        client.verify_identity()
    assert error.value.code == "model_not_served"


def test_identity_passes_when_the_server_reports_no_revision() -> None:
    """stock vLLM은 revision을 내지 않는다. 부재는 실패가 아니다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=REVISION,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
        models_list=lambda: {"data": [{"id": "합성-모델-a"}]},
    )
    assert client.verify_identity() == ModelIdentity(model="합성-모델-a", revision=REVISION)


def test_identity_compares_a_reported_revision() -> None:
    """served row가 revision을 내면 선언 revision과 대조한다."""

    client = ModelClient(
        model="합성-모델-a",
        output_contract=CONTRACT,
        model_revision=REVISION,
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
        models_list=lambda: {"data": [{"id": "합성-모델-a", "model_revision": OTHER_REVISION}]},
    )
    with pytest.raises(ModelIdentityError) as error:
        client.verify_identity()
    assert error.value.code == "model_revision_invalid"


def test_for_purpose_verifies_identity_before_the_first_call() -> None:
    """용도로 만든 client는 생성 시점에 identity를 확인한다."""

    calls: list[str] = []

    def models_list() -> Mapping[str, Any]:
        calls.append("models")
        return {"data": [{"id": "합성-모델-a"}]}

    client = ModelClient.for_purpose(
        "deep_review",
        model="합성-모델-a",
        output_contract=CONTRACT,
        settings=_settings(),
        completion_create=lambda **_kwargs: _completion("합성-모델-a", {"verdict": "ok"}),
        models_list=models_list,
    )
    assert calls == ["models"]
    assert client.model_revision == REVISION
    assert client.purpose == "deep_review"


def test_for_purpose_fails_closed_before_touching_the_network() -> None:
    """허용 host가 비면 `/models`조차 부르지 않고 실패한다."""

    def models_list() -> Mapping[str, Any]:  # pragma: no cover - 불려서는 안 된다
        raise AssertionError("fail-closed 설정에서 identity 호출이 나갔다")

    with pytest.raises(ModelEndpointError):
        ModelClient.for_purpose(
            "screening",
            model="합성-모델-a",
            output_contract=CONTRACT,
            settings=_settings(vllm_allowed_hosts=""),
            completion_create=lambda **_kwargs: {},
            models_list=models_list,
        )
