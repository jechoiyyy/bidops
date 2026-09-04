from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.screening.services.candidate_quality import CandidateQualityManifest, candidate_sample_hash, score_candidate_quality


def _manifest() -> dict:
    return {
        "schema": "bidops.qwen-quality-evaluation.v1",
        "model_name": "qwen3.8-27B",
        "model_artifact_digest": "abcdef123456",
        "policy_sha256": "1" * 64,
        "samples": [
            {
                "sample_id": "representative-hwp-55",
                "source_format": "hwp",
                "source_sha256": "2" * 64,
                "coverage_tags": ["requirements-55", "representative"],
                "required_items": [
                    {"item_id": f"REQ-{index:03d}", "detected": True}
                    for index in range(1, 56)
                ],
                "judgments": [
                    {
                        "claim_id": f"hwp-claim-{index}",
                        "model_status": "supported",
                        "human_status": "supported",
                        "evidence_sufficient": True,
                    }
                    for index in range(1, 6)
                ],
            },
            {
                "sample_id": "representative-pdf",
                "source_format": "pdf",
                "source_sha256": "3" * 64,
                "coverage_tags": ["representative"],
                "required_items": [
                    {"item_id": f"PDF-{index:03d}", "detected": index < 5}
                    for index in range(1, 6)
                ],
                "judgments": [
                    {
                        "claim_id": f"pdf-claim-{index}",
                        "model_status": "supported" if index < 4 else "unknown",
                        "human_status": "supported" if index < 4 else "unknown",
                        "evidence_sufficient": index < 4,
                    }
                    for index in range(1, 6)
                ],
            },
        ],
    }


def test_candidate_quality_scores_all_three_activation_metrics() -> None:
    result = score_candidate_quality(CandidateQualityManifest.model_validate(_manifest()))

    assert result.required_item_recall.numerator == 59
    assert result.required_item_recall.denominator == 60
    assert result.human_agreement.value == 1
    assert result.unsupported_false_positive_rate.value == 0
    assert result.passed is True
    assert result.policy_import_arguments() == [
        "--expected-policy-sha256", "1" * 64,
        "--sample-hash", result.sample_hash,
        "--required-item-recall", "0.983333333333",
        "--human-agreement", "1",
        "--unsupported-false-positive-rate", "0",
    ]


def test_candidate_quality_failure_never_emits_activation_arguments() -> None:
    payload = _manifest()
    for item in payload["samples"][0]["required_items"][20:]:
        item["detected"] = False
    payload["samples"][1]["judgments"][0].update(human_status="unsupported", evidence_sufficient=False)

    result = score_candidate_quality(CandidateQualityManifest.model_validate(payload))

    assert result.required_item_recall.passed is False
    assert result.unsupported_false_positive_rate.passed is False
    assert result.passed is False
    assert result.policy_import_arguments() == []


def test_candidate_sample_hash_excludes_candidate_answers_but_includes_gold() -> None:
    first = CandidateQualityManifest.model_validate(_manifest())
    changed_answers = deepcopy(_manifest())
    changed_answers["samples"][0]["required_items"][0]["detected"] = False
    changed_answers["samples"][0]["judgments"][0]["model_status"] = "unknown"
    second = CandidateQualityManifest.model_validate(changed_answers)
    assert candidate_sample_hash(first) == candidate_sample_hash(second)

    changed_gold = deepcopy(changed_answers)
    changed_gold["samples"][0]["judgments"][0]["human_status"] = "unknown"
    third = CandidateQualityManifest.model_validate(changed_gold)
    assert candidate_sample_hash(first) != candidate_sample_hash(third)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["samples"].pop(),
        lambda payload: payload["samples"][0].update(source_format="pdf"),
        lambda payload: payload["samples"][0]["coverage_tags"].remove("requirements-55"),
        lambda payload: payload["samples"][0]["required_items"].pop(),
        lambda payload: [row.update(model_status="unknown") for sample in payload["samples"] for row in sample["judgments"]],
    ],
)
def test_candidate_quality_rejects_incomplete_or_unmeasurable_coverage(mutation) -> None:
    payload = _manifest()
    mutation(payload)
    with pytest.raises(ValidationError):
        CandidateQualityManifest.model_validate(payload)
