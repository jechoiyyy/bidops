"""LiteLLM requests must switch thinking off in a form the upstream honors (DEMO-05 STEP-005).

2026-10-13 real stack: `local-agent-main` (qwen3.8:27b-ctx32k behind LiteLLM) ignored
`chat_template_kwargs.enable_thinking=false` and reasoned ~466 s before any content
(finish_reason=length at 8192); the same request with `reasoning_effort="none"` returned
content at 0.4 s and stopped after 1783 tokens. The approved generation already says
`enable_thinking: false`; the litellm wire must carry both forms.
"""

from __future__ import annotations

from app.core.model_client import APPROVED_GENERATION, StructuredOutputContract, _structured_request_kwargs

CONTRACT = StructuredOutputContract(
    name="test_contract",
    system_prompt="합성 시스템",
    schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def _kwargs(dialect: str) -> dict:
    return _structured_request_kwargs(
        model="m", prompt="합성", contract=CONTRACT, api_dialect=dialect,
        max_tokens=8192, timeout_seconds=900, seed=0, correction=None,
    )


def test_litellm_request_disables_thinking_with_reasoning_effort_none() -> None:
    assert APPROVED_GENERATION["enable_thinking"] is False
    assert _kwargs("litellm")["extra_body"] == {
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }


def test_vllm_and_ollama_requests_are_unchanged() -> None:
    assert _kwargs("vllm")["extra_body"] == {"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}}
    assert _kwargs("ollama")["extra_body"] == {"reasoning_effort": "none"}
