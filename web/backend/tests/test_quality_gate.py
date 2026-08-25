from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.screening.profile_snapshot import BASELINE_COMMIT
from app.screening.quality_gate import (
    FIXED_BASELINE_RELATIVE,
    FIXED_SAMPLE_RELATIVE,
    QualityGateValidationError,
    validate_fixed_inputs,
)


def _fixed_fixture(root: Path, *, sample_count: int = 40, baseline_ids: list[str] | None = None) -> None:
    sample_path = root / FIXED_SAMPLE_RELATIVE
    baseline_path = root / FIXED_BASELINE_RELATIVE
    sample_path.parent.mkdir(parents=True)
    ids = [f"n-{index}" for index in range(sample_count)]
    baseline_ids = baseline_ids or ids
    sample_path.write_text(json.dumps({"schema_version": "bidops.validation-set.v2", "notices": [{"notice_id": value} for value in ids]}), encoding="utf-8")
    baseline_path.write_text(json.dumps({"schema_version": "bidops.decisions.v2", "judgments": [{"notice_id": value} for value in baseline_ids]}), encoding="utf-8")


def test_fixed_sample_requires_exactly_40_and_matching_claude_ids(tmp_path: Path):
    _fixed_fixture(tmp_path)
    sample, baseline, sample_raw, baseline_raw, ids = validate_fixed_inputs(tmp_path)
    assert len(ids) == 40
    assert sample["schema_version"] == "bidops.validation-set.v2"
    assert baseline["schema_version"] == "bidops.decisions.v2"
    assert sample_raw and baseline_raw

    _fixed_fixture(tmp_path, sample_count=39)
    with pytest.raises(QualityGateValidationError):
        validate_fixed_inputs(tmp_path)

    _fixed_fixture(tmp_path, baseline_ids=[f"other-{index}" for index in range(40)])
    with pytest.raises(QualityGateValidationError):
        validate_fixed_inputs(tmp_path)


def test_fixed_source_policy_is_explicit_in_contract():
    assert FIXED_SAMPLE_RELATIVE == "data/runs/20260817-20260823/validation-set.json"
    assert FIXED_BASELINE_RELATIVE == "data/runs/20260817-20260823/screening-decisions.json"
    assert len(BASELINE_COMMIT) == 40
