from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.models import CompanyProfileSnapshot, Run, ScreeningExecution, ScreeningPolicy
from app.screening.artifacts import ArtifactStore
from app.screening.orchestrator import CreatedExecution, ScreeningCreationError
from app.screening.profile_snapshot import BASELINE_COMMIT
from app.screening.quality_gate import (
    FIXED_BASELINE_RELATIVE,
    FIXED_RUN_ID,
    FIXED_SAMPLE_RELATIVE,
    QualityGateValidationError,
    validate_fixed_inputs,
    QualityGateService,
)


DIGEST = "a" * 64
PROFILE_VERSION = "company-profile.sha256:" + DIGEST
NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _fixed_fixture(root: Path, *, sample_count: int = 40, baseline_ids: list[str] | None = None) -> None:
    sample_path = root / FIXED_SAMPLE_RELATIVE
    baseline_path = root / FIXED_BASELINE_RELATIVE
    sample_path.parent.mkdir(parents=True, exist_ok=True)
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


def _service_fixture(root: Path, *, sample_count: int = 40):
    _fixed_fixture(root, sample_count=sample_count)
    settings = Settings(bidops_root=root, data_dir=root / "data", database_url=f"sqlite:///{root / 'quality.db'}")
    engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Run(id=FIXED_RUN_ID, timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(CompanyProfileSnapshot(
            digest=DIGEST, version=PROFILE_VERSION, source_kind="working_tree",
            source_ref="docs/reference/company-profile.md",
            artifact_path=f"web/data/profile-snapshots/{DIGEST}.md", created_at=NOW,
        ))
        session.add(ScreeningPolicy(
            policy_version="policy-1", prompt_version="prompt-1", content_digest=DIGEST,
            status="activation_candidate", perspective_prompts_json={}, counterargument_prompt_json={},
            synthesis_prompt_json={}, candidate_selection_json={}, thresholds_json={},
            created_at=NOW, created_by="tester",
        ))
        session.commit()
    return settings, engine, factory


class _FailingPassOrchestrator:
    def __init__(self, settings, factory):
        self.settings = settings
        self.factory = factory
        self.queue = SimpleNamespace()
        self.calls = 0

    def create_execution(self, **kwargs):
        self.calls += 1
        if self.calls == 2:
            raise ScreeningCreationError("queue_failure")
        execution_id = "scr-" + "1" * 32
        store = ArtifactStore(self.settings.bidops_root)
        store.execution_dir(execution_id, create=True)
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id,
            "run_id": FIXED_RUN_ID, "generated_at": NOW.isoformat(), "source_window": {},
            "policy_version": "policy-1", "prompt_version": "prompt-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST,
            "candidate_count": 40, "notices": [{"notice_id": f"n-{i}"} for i in range(40)],
        }
        path, digest = store.write_json(execution_id, "screening-input.json", input_value)
        with self.factory() as session:
            session.add(ScreeningExecution(
                execution_id=execution_id, trigger="quality_gate", source_run_id=FIXED_RUN_ID,
                scope="quality_sample", status="대기", requested_by="tester", policy_version="policy-1",
                prompt_version="prompt-1", model_name="qwen3.8:27b", model_digest=DIGEST,
                company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
                input_artifact_path=path, input_artifact_digest=digest,
                artifact_dir=f"data/screening-executions/{execution_id}", queued_at=NOW,
                candidate_count=40, completed_count=0, failure_count=0,
            ))
            session.commit()
        return CreatedExecution(execution_id, "대기", "qwen3.8:27b", DIGEST, PROFILE_VERSION, DIGEST,
                                f"data/screening-executions/{execution_id}", path, digest)


def test_failed_second_pass_leaves_no_execution_or_artifact(tmp_path: Path):
    settings, engine, factory = _service_fixture(tmp_path)
    service = QualityGateService(settings, session_factory=factory, orchestrator=_FailingPassOrchestrator(settings, factory))
    with pytest.raises(ScreeningCreationError):
        service.create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
    assert not (tmp_path / "data/screening-executions").exists() or not list((tmp_path / "data/screening-executions").iterdir())


def test_invalid_fixed_input_is_rejected_before_any_gate_or_execution_row(tmp_path: Path):
    settings, engine, factory = _service_fixture(tmp_path, sample_count=39)
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []


@pytest.mark.parametrize(
    ("purpose", "profile_source"),
    [("model_comparison", "current"), ("operational_approval", f"git:{BASELINE_COMMIT}")],
)
def test_purpose_profile_source_mismatch_has_no_side_effects(tmp_path: Path, purpose: str, profile_source: str):
    settings, engine, factory = _service_fixture(tmp_path)
    service = QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace())
    with pytest.raises(QualityGateValidationError):
        service.create_gate(purpose=purpose, policy_version="policy-1", profile_source=profile_source, created_by="tester")
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
