"""Approved model binding constants and the canonical JSON encoding.

두 도메인 모듈이 같은 사설 vLLM 배치를 가리켜야 하므로, 승인된 모델 이름과
endpoint 참조는 어느 한 모듈이 아니라 core가 소유한다. `canonical_json_bytes`
역시 정책·입력 version 해시와 C-2 산출물이 함께 쓰는 직렬화라 여기에 둔다.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

MODEL_ENDPOINT_REF = "vllm-openai-compatible"
MODEL_NAME = "qwen3.8-27B"


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode JSON exactly as the approved policy requires."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["MODEL_ENDPOINT_REF", "MODEL_NAME", "canonical_json_bytes"]
