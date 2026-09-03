"""심층 검토 단계의 구조화 출력 계약.

무엇을 물어볼지는 계약을 소유한 이 모듈이 정하고, 승인된 vLLM 배치로 나가는
경계 자체는 `app.core.vllm_client`가 소유한다.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..contracts.deep_review import DEEP_REVIEW_STAGE_SCHEMA, load_schema
from ..core.vllm_client import StructuredOutputContract

STAGE_SYSTEM_PROMPT = (
    "Return exactly one JSON object matching the enforced deep-review-stage schema. "
    "Copy input identity fields exactly, use lowercase UUIDs for new claim/evidence IDs, "
    "and do not include analysis, reasoning, or Markdown fences in content."
)


def _provider_stage_schema() -> dict[str, Any]:
    """Flatten the evidence ``allOf`` for vLLM's structured decoder.

    The authoritative validator still applies the complete ``allOf``/``oneOf``
    contract after generation.  The provider schema is only a constrained
    decoding aid and must require every common evidence field explicitly.
    """

    schema = deepcopy(load_schema(DEEP_REVIEW_STAGE_SCHEMA))
    evidence_base = schema["$defs"]["evidence_base"]
    schema["$defs"]["evidence"] = {
        "type": "object",
        "additionalProperties": False,
        "required": list(evidence_base["required"]),
        "properties": deepcopy(evidence_base["properties"]),
    }
    return schema


STAGE_RESPONSE_SCHEMA = _provider_stage_schema()

DEEP_REVIEW_STAGE_CONTRACT = StructuredOutputContract(
    name="bidops_deep_review_stage_v1",
    schema=STAGE_RESPONSE_SCHEMA,
    system_prompt=STAGE_SYSTEM_PROMPT,
)

__all__ = [
    "DEEP_REVIEW_STAGE_CONTRACT",
    "STAGE_RESPONSE_SCHEMA",
    "STAGE_SYSTEM_PROMPT",
]
