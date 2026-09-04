from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from app.screening.services.vllm_client import (
    OrderPlanVllmAdapter,
    OrderPlanVllmError,
    order_plan_batch_output_schema,
)


DIGEST = "a" * 64

# The adapter takes its generation settings from the approved artifact, so the
# tests read the real file instead of restating its values.
GENERATION_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[4]
    / "experiments/order-plan-screening/config/order-plan-screening-generation-config.v4.json"
)
GENERATION_CONFIG = json.loads(GENERATION_CONFIG_PATH.read_text(encoding="utf-8"))

PAYLOAD = {
    "company_capabilities": {
        "profile_version": "rootlab-company-profile-2026-08-96731dd5f77d",
        "capabilities": [{"id": "ai-data-analytics", "summary": "요약"}],
    },
    "items": [{"item_id": 0, "title": "지식그래프 구축 용역"}],
}


def _adapter(handler) -> tuple[OrderPlanVllmAdapter, httpx.Client]:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    return (
        OrderPlanVllmAdapter(
            base_url="http://127.0.0.1:8000/v1",
            allowed_hosts="127.0.0.1",
            api_key="EMPTY",
            model="qwen3.8-27B",
            model_digest=DIGEST,
            deployed_revision=DIGEST,
            generation_config=GENERATION_CONFIG,
            http_client=client,
        ),
        client,
    )


def test_adapter_uses_only_the_exact_private_chat_boundary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:8000/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "qwen3.8-27B"
        # Generation settings come from the approved artifact, not constants.
        assert body["max_tokens"] == GENERATION_CONFIG["max_output_tokens"]
        # Raw JSON goes on the wire, so the generation switch has to be a
        # top-level field.  Nested under "extra_body" vLLM silently ignores it.
        assert "extra_body" not in body
        assert body["chat_template_kwargs"] == GENERATION_CONFIG["chat_template_kwargs"]
        # The approved prompt is the system message; the batch is the user one.
        assert body["messages"][0] == {"role": "system", "content": "{}"}
        assert json.loads(body["messages"][1]["content"]) == PAYLOAD
        assert body["temperature"] == 0
        assert body["stream"] is False
        assert "top_p" not in body and "seed" not in body
        schema = body["response_format"]["json_schema"]
        assert body["response_format"]["type"] == "json_schema"
        assert schema["strict"] is True
        assert schema["schema"]["properties"]["items"]["minItems"] == len(PAYLOAD["items"])
        assert schema["schema"]["properties"]["items"]["maxItems"] == len(PAYLOAD["items"])
        assert set(schema["schema"]["properties"]["items"]["items"]["properties"]) == {
            "item_id", "relevance", "score", "reason",
        }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-c2",
                "model": "qwen3.8-27B",
                "model_revision": DIGEST,
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"items": []}'},
                }],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
            },
        )

    adapter, client = _adapter(handler)
    try:
        response = adapter.invoke(prompt="{}", payload=PAYLOAD, expected_model="qwen3.8-27B")
    finally:
        client.close()
    assert response.structured_output == {"items": []}
    assert response.input_tokens == 12
    assert response.output_tokens == 3
    assert response.total_tokens == 15
    assert response.duration_ms >= 0
    assert b"reasoning" not in response.approved_raw_response


@pytest.mark.parametrize(
    "base_url,allowed_hosts",
    [
        ("http://127.0.0.1:8000/v1/", "127.0.0.1"),
        ("http://127.0.0.1:8000/v1?x=1", "127.0.0.1"),
        ("http://localhost:8000/v1", "127.0.0.1"),
        ("http://127.0.0.1:8000/v1", "127.0.0.1,model.internal"),
    ],
)
def test_adapter_rejects_non_exact_or_non_literal_endpoint(base_url: str, allowed_hosts: str) -> None:
    with pytest.raises(ValueError):
        OrderPlanVllmAdapter(
            base_url=base_url,
            allowed_hosts=allowed_hosts,
            api_key="EMPTY",
            model="qwen3.8-27B",
            model_digest=DIGEST,
            deployed_revision=DIGEST,
            generation_config=GENERATION_CONFIG,
        )


def test_adapter_rejects_a_response_revision_that_contradicts_the_binding() -> None:
    """A server that does report a revision still has to agree with the binding."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-c2",
                "model": "qwen3.8-27B",
                "model_revision": "b" * 64,
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"items": []}'},
                }],
            },
        )

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(OrderPlanVllmError, match="model_revision_invalid"):
            adapter.invoke(prompt="{}", payload=PAYLOAD, expected_model="qwen3.8-27B")
    finally:
        client.close()


def test_adapter_accepts_a_response_without_a_revision_field() -> None:
    """A stock OpenAI-compatible vLLM reports no weight revision at all."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-c2",
                "model": "qwen3.8-27B",
                "system_fingerprint": "vllm-0.24.0-tp2-8477a424",
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"items": []}'},
                }],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            },
        )

    adapter, client = _adapter(handler)
    try:
        result = adapter.invoke(prompt="{}", payload=PAYLOAD, expected_model="qwen3.8-27B")
        assert result.structured_output == {"items": []}
        assert result.total_tokens == 15
    finally:
        client.close()


def test_adapter_refuses_to_start_without_a_declared_deployment_revision() -> None:
    with pytest.raises(ValueError, match="64-hex model revision"):
        OrderPlanVllmAdapter(
            base_url="http://127.0.0.1:8000/v1",
            allowed_hosts="127.0.0.1",
            api_key="EMPTY",
            model="qwen3.8-27B",
            model_digest=DIGEST,
            deployed_revision="",
            generation_config=GENERATION_CONFIG,
        )


def test_adapter_refuses_a_deployment_revision_that_differs_from_the_binding() -> None:
    with pytest.raises(ValueError, match="does not match the binding"):
        OrderPlanVllmAdapter(
            base_url="http://127.0.0.1:8000/v1",
            allowed_hosts="127.0.0.1",
            api_key="EMPTY",
            model="qwen3.8-27B",
            model_digest=DIGEST,
            deployed_revision="b" * 64,
            generation_config=GENERATION_CONFIG,
        )


def test_adapter_request_matches_the_measured_selection_run() -> None:
    """The wire body must equal what the C-2 selection experiment sent.

    ADR-0037 measured the method through
    ``experiments/order-plan-screening/scripts/methods.py`` ``_score_batch``.
    Any drift between that body and this adapter means the product is running a
    method nobody measured, which is how the thinking switch, the payload
    identity, and the response format all diverged unnoticed ([ADR-0044]).
    """

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-c2",
                "model": "qwen3.8-27B",
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"items": []}'},
                }],
            },
        )

    adapter, client = _adapter(handler)
    try:
        adapter.invoke(prompt="승인 prompt 본문", payload=PAYLOAD, expected_model="qwen3.8-27B")
    finally:
        client.close()

    expected = {
        "model": "qwen3.8-27B",
        "messages": [
            {"role": "system", "content": "승인 prompt 본문"},
            {
                "role": "user",
                "content": json.dumps(
                    PAYLOAD, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": GENERATION_CONFIG["max_output_tokens"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "order_plan_relevance",
                "strict": True,
                "schema": order_plan_batch_output_schema(len(PAYLOAD["items"])),
            },
        },
        "chat_template_kwargs": GENERATION_CONFIG["chat_template_kwargs"],
    }
    assert captured == expected


def test_adapter_refuses_a_generation_config_without_approved_values() -> None:
    for broken in ({}, {"max_output_tokens": 8192}, dict(GENERATION_CONFIG, max_output_tokens=0)):
        with pytest.raises(ValueError, match="generation config"):
            OrderPlanVllmAdapter(
                base_url="http://127.0.0.1:8000/v1",
                allowed_hosts="127.0.0.1",
                api_key="EMPTY",
                model="qwen3.8-27B",
                model_digest=DIGEST,
                deployed_revision=DIGEST,
                generation_config=broken,
            )


def test_adapter_refuses_an_empty_batch() -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json={}))
    try:
        with pytest.raises(OrderPlanVllmError, match="payload_invalid"):
            adapter.invoke(prompt="p", payload={"items": []}, expected_model="qwen3.8-27B")
    finally:
        client.close()
