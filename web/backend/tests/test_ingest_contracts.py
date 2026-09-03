from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ingest.contracts import (
    DecisionArtifact,
    DecisionJudgment,
    FeedbackArtifact,
    OrderPlanScreeningInputArtifact,
    OrderPlanScreeningResultItem,
    ScreeningResultsArtifact,
    ValidationSetArtifact,
    model_extra_fields,
)


def test_decisions_v1_and_v2_are_accepted_without_fabricating_lists():
    legacy = DecisionArtifact.model_validate(
        {
            "schema_version": "bidops.decisions.v1",
            "screening_basis": "legacy",
            "judgments": [
                {
                    "notice_id": "bid:LEGACY:000",
                    "grade": "관찰 대상",
                    "readiness": "해당 없음",
                    "perspectives": [{"name": "제목·API 메타데이터 적합성"}],
                }
            ],
        }
    )
    current = DecisionArtifact.model_validate(
        {
            "schema_version": "bidops.decisions.v2",
            "screening_basis": "current",
            "judgments": [
                {
                    "notice_id": "bid:CURRENT:000",
                    "grade": "우선 검토",
                    "readiness": "부분 확인 필요",
                    "perspectives": [{"name": "기술 적합성"}],
                    "counterarguments": [],
                    "verification_items": [],
                }
            ],
        }
    )

    assert isinstance(legacy.judgments[0], DecisionJudgment)
    assert legacy.judgments[0].counterarguments is None
    assert current.judgments[0].perspectives[0].name == "기술 적합성"


def test_artifact_models_keep_unknown_fields_for_info_warning():
    artifact = ValidationSetArtifact.model_validate(
        {
            "schema_version": "bidops.validation-set.v2",
            "notices": [],
            "future_field": "ignore me",
        }
    )
    feedback = FeedbackArtifact.model_validate(
        {"schema_version": "bidops.feedback.v2", "reviews": [], "future": True}
    )

    assert "future_field" in model_extra_fields(artifact)
    assert "future" in model_extra_fields(feedback)


def test_other_artifact_aliases_are_pydantic_models():
    screening = ScreeningResultsArtifact.model_validate(
        {"schema_version": "bidops.screening.v2", "results": []}
    )
    assert screening.results == []


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
