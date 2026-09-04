"""Fail-closed scoring for human-reviewed Qwen candidate evidence.

This module never invokes a model and never activates a policy.  It accepts a
bounded manifest containing only source identities, expected item IDs, and
human adjudication labels.  The resulting sample hash and three measurements
can be supplied to the immutable policy import command only after ``passed``
is true.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...core.model_binding import canonical_json_bytes


QUALITY_MANIFEST_SCHEMA = "bidops.qwen-quality-evaluation.v1"
QUALITY_RESULT_SCHEMA = "bidops.qwen-quality-result.v1"
REQUIREMENTS_55_TAG = "requirements-55"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MODEL_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-f]{12,64}$")


class CandidateQualityError(ValueError):
    """A safe validation error for a candidate quality manifest."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RequiredItemScore(_StrictModel):
    item_id: str = Field(min_length=1, max_length=256)
    detected: bool

    @field_validator("item_id")
    @classmethod
    def item_id_is_safe(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError("item_id must be a trimmed printable value")
        return value


ClaimStatus = Literal["supported", "unsupported", "conflicting", "unknown"]


class HumanJudgmentScore(_StrictModel):
    claim_id: str = Field(min_length=1, max_length=256)
    model_status: ClaimStatus
    human_status: ClaimStatus
    evidence_sufficient: bool

    @field_validator("claim_id")
    @classmethod
    def claim_id_is_safe(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError("claim_id must be a trimmed printable value")
        return value


class CandidateSampleScore(_StrictModel):
    sample_id: str = Field(min_length=1, max_length=128)
    source_format: Literal["hwp", "hwpx", "pdf"]
    source_sha256: str
    coverage_tags: list[str]
    required_items: list[RequiredItemScore]
    judgments: list[HumanJudgmentScore]

    @field_validator("sample_id")
    @classmethod
    def sample_id_is_safe(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError("sample_id must be a trimmed printable value")
        return value

    @field_validator("source_sha256")
    @classmethod
    def source_hash_is_canonical(cls, value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError("source_sha256 must be lowercase hex64")
        return value

    @field_validator("coverage_tags")
    @classmethod
    def coverage_tags_are_unique(cls, value: list[str]) -> list[str]:
        if not value or any(not tag or tag != tag.strip() for tag in value) or len(set(value)) != len(value):
            raise ValueError("coverage_tags must contain unique trimmed values")
        return value

    @model_validator(mode="after")
    def score_rows_are_unique(self) -> "CandidateSampleScore":
        item_ids = [item.item_id for item in self.required_items]
        claim_ids = [item.claim_id for item in self.judgments]
        if not item_ids or len(set(item_ids)) != len(item_ids):
            raise ValueError("required item IDs must be non-empty and unique within a sample")
        if not claim_ids or len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim IDs must be non-empty and unique within a sample")
        if REQUIREMENTS_55_TAG in self.coverage_tags and len(item_ids) != 55:
            raise ValueError("requirements-55 sample must contain exactly 55 expected item IDs")
        return self


class CandidateQualityManifest(_StrictModel):
    schema_name: Literal["bidops.qwen-quality-evaluation.v1"] = Field(alias="schema", serialization_alias="schema")
    model_name: Literal["qwen3.8-27B"]
    model_artifact_digest: str
    policy_sha256: str
    samples: list[CandidateSampleScore]

    @field_validator("model_artifact_digest")
    @classmethod
    def model_digest_is_pinned(cls, value: str) -> str:
        if not _MODEL_DIGEST.fullmatch(value):
            raise ValueError("model_artifact_digest must be a pinned lowercase hex digest")
        return value

    @field_validator("policy_sha256")
    @classmethod
    def policy_hash_is_canonical(cls, value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError("policy_sha256 must be lowercase hex64")
        return value

    @model_validator(mode="after")
    def coverage_is_complete(self) -> "CandidateQualityManifest":
        sample_ids = [sample.sample_id for sample in self.samples]
        if not sample_ids or len(set(sample_ids)) != len(sample_ids):
            raise ValueError("sample IDs must be non-empty and unique")
        formats = {sample.source_format for sample in self.samples}
        if "pdf" not in formats or not formats.intersection({"hwp", "hwpx"}):
            raise ValueError("candidate quality set must include PDF and HWP/HWPX samples")
        if not any(REQUIREMENTS_55_TAG in sample.coverage_tags for sample in self.samples):
            raise ValueError("candidate quality set must include the requirements-55 fixture")
        if not any(judgment.model_status == "supported" for sample in self.samples for judgment in sample.judgments):
            raise ValueError("unsupported false-positive rate is not measurable without model-supported claims")
        return self


class MetricResult(_StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)
    value: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    passed: bool


class CandidateQualityResult(_StrictModel):
    schema_name: Literal["bidops.qwen-quality-result.v1"] = Field(alias="schema", serialization_alias="schema")
    model_name: Literal["qwen3.8-27B"]
    model_artifact_digest: str
    policy_sha256: str
    sample_hash: str
    sample_count: int = Field(gt=0)
    required_item_recall: MetricResult
    human_agreement: MetricResult
    unsupported_false_positive_rate: MetricResult
    passed: bool

    def policy_import_arguments(self) -> list[str]:
        """Return explicit activation evidence arguments only after a pass."""

        if not self.passed:
            return []
        return [
            "--expected-policy-sha256", self.policy_sha256,
            "--sample-hash", self.sample_hash,
            "--required-item-recall", _metric_text(self.required_item_recall.value),
            "--human-agreement", _metric_text(self.human_agreement.value),
            "--unsupported-false-positive-rate", _metric_text(self.unsupported_false_positive_rate.value),
        ]


def _metric_text(value: float) -> str:
    return f"{value:.12f}".rstrip("0").rstrip(".")


def _ratio(numerator: int, denominator: int, threshold: float, *, maximum: bool = False) -> MetricResult:
    if denominator <= 0:
        raise CandidateQualityError("quality metric denominator must be positive")
    value = numerator / denominator
    passed = value <= threshold if maximum else value >= threshold
    return MetricResult(
        numerator=numerator,
        denominator=denominator,
        value=value,
        threshold=threshold,
        passed=passed,
    )


def candidate_sample_hash(manifest: CandidateQualityManifest) -> str:
    """Hash only the fixed source/gold projection, never candidate answers."""

    samples: list[dict[str, object]] = []
    for sample in sorted(manifest.samples, key=lambda item: item.sample_id):
        samples.append({
            "sample_id": sample.sample_id,
            "source_format": sample.source_format,
            "source_sha256": sample.source_sha256,
            "coverage_tags": sorted(sample.coverage_tags),
            "expected_required_item_ids": sorted(item.item_id for item in sample.required_items),
            "human_judgments": [
                {
                    "claim_id": judgment.claim_id,
                    "human_status": judgment.human_status,
                    "evidence_sufficient": judgment.evidence_sufficient,
                }
                for judgment in sorted(sample.judgments, key=lambda item: item.claim_id)
            ],
        })
    projection: Mapping[str, object] = {
        "schema": "bidops.qwen-quality-sample.v1",
        "samples": samples,
    }
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


def score_candidate_quality(manifest: CandidateQualityManifest) -> CandidateQualityResult:
    required_items = [item for sample in manifest.samples for item in sample.required_items]
    judgments = [item for sample in manifest.samples for item in sample.judgments]
    supported = [item for item in judgments if item.model_status == "supported"]

    recall = _ratio(
        sum(item.detected for item in required_items),
        len(required_items),
        0.8,
    )
    agreement = _ratio(
        sum(item.model_status == item.human_status for item in judgments),
        len(judgments),
        0.7,
    )
    unsupported_false_positive = _ratio(
        sum(item.human_status != "supported" or not item.evidence_sufficient for item in supported),
        len(supported),
        0.1,
        maximum=True,
    )
    passed = recall.passed and agreement.passed and unsupported_false_positive.passed
    return CandidateQualityResult(
        schema=QUALITY_RESULT_SCHEMA,
        model_name=manifest.model_name,
        model_artifact_digest=manifest.model_artifact_digest,
        policy_sha256=manifest.policy_sha256,
        sample_hash=candidate_sample_hash(manifest),
        sample_count=len(manifest.samples),
        required_item_recall=recall,
        human_agreement=agreement,
        unsupported_false_positive_rate=unsupported_false_positive,
        passed=passed,
    )


__all__ = [
    "CandidateQualityError",
    "CandidateQualityManifest",
    "CandidateQualityResult",
    "CandidateSampleScore",
    "HumanJudgmentScore",
    "MetricResult",
    "RequiredItemScore",
    "candidate_sample_hash",
    "score_candidate_quality",
]
