"""C-2 산출물 계약의 엄격성 (명세 §6.2).

C-2 계약은 screening 소유이므로 이 검사도 선별 폴더에 둔다. 회차 적재 계약과
달리 알 수 없는 키를 거부하고 상태 조합까지 검증한다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.screening.c2_contracts import (
    OrderPlanScreeningInputArtifact,
    OrderPlanScreeningResultItem,
)


def test_c2_input_is_strict_and_requires_timezone_aware_created_at():
    value = {
        "schema_version": "bidops.order-plan-screening-input.v1",
        "producer": "order-plan-screening-orchestrator",
        "consumer": "order-plan-screening-worker",
        "execution_id": "00000000-0000-0000-0000-000000000001",
        "source_run_id": "c2-contract-run",
        "source_artifact": {
            "name": "collected-order-plans.json",
            "schema_version": "bidops.collected-order-plans.v1",
            "sha256": "a" * 64,
        },
        "population_count": 1,
        "population_sha256": "b" * 64,
        "policy": {"version": "policy-v1", "sha256": "c" * 64},
        "stage1_binding": {"version": "bm25-v1", "sha256": "d" * 64},
        "stage2_binding": {"version": "qwen-v1", "sha256": "e" * 64},
        "items": [{"plan_id": "plan-1", "title": "계획"}],
        "status": "frozen",
        "created_at": "2026-09-01T00:00:00+00:00",
    }

    parsed = OrderPlanScreeningInputArtifact.model_validate(value)
    assert parsed.items[0].plan_id == "plan-1"

    with pytest.raises(ValidationError):
        OrderPlanScreeningInputArtifact.model_validate({**value, "unexpected": True})
    with pytest.raises(ValidationError):
        OrderPlanScreeningInputArtifact.model_validate(
            {**value, "created_at": "2026-09-01T00:00:00"}
        )


def test_c2_result_item_rejects_a_partial_success_card():
    with pytest.raises(ValidationError):
        OrderPlanScreeningResultItem.model_validate(
            {
                "plan_id": "plan-1",
                "stage1_status": "selected",
                "stage1_rank": 1,
                "stage1_score": 1.0,
                "nearest_capability": "cap-ai",
                "stage2_status": "success",
                "qwen_relevance": "relevant",
                "qwen_score": None,
                "qwen_reason": "판정",
                "batch_id": "batch-1",
                "attempt_no": 1,
                "failure_code": None,
            }
        )


def test_c2_result_item_keeps_not_attempted_for_a_stage1_failure():
    item = OrderPlanScreeningResultItem.model_validate(
        {
            "plan_id": "plan-1",
            "stage1_status": "failed",
            "stage1_rank": None,
            "stage1_score": None,
            "nearest_capability": None,
            "stage2_status": "not_attempted",
            "qwen_relevance": None,
            "qwen_score": None,
            "qwen_reason": None,
            "batch_id": None,
            "attempt_no": None,
            "failure_code": None,
        }
    )
    assert item.stage2_status == "not_attempted"
