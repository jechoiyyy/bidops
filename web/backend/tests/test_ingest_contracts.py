from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ingest.contracts import (
    DecisionArtifact,
    DecisionJudgment,
    FeedbackArtifact,
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
