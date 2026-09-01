from __future__ import annotations

import json

import httpx
import pytest

from app.services.vllm_client import OrderPlanVllmAdapter, OrderPlanVllmError


DIGEST = "a" * 64


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
        assert body["max_tokens"] == 8192
        assert body["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
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
        response = adapter.invoke(prompt="{}", payload={"items": []}, expected_model="qwen3.8-27B")
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
        )


def test_adapter_requires_the_bound_model_revision() -> None:
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
            adapter.invoke(prompt="{}", payload={"items": []}, expected_model="qwen3.8-27B")
    finally:
        client.close()
