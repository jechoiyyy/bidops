from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.models import AuditEvent, CompanyProfileSnapshot, QualityGate, QualityGateEvaluation, QualityGateReview, Run, ScreeningExecution, ScreeningPolicy
from app.screening.artifacts import ArtifactStore
from app.screening.contracts import MODEL_NAME, ModelIdentity
from app.screening.orchestrator import CreatedExecution, ScreeningCreationError, ScreeningOrchestrator
from app.screening.policy import load_policy_file, policy_content_digest
from app.screening.profile_snapshot import BASELINE_COMMIT
from app.screening.quality_metrics import judgment_digest
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
    sample_path.write_text(json.dumps({"schema_version": "bidops.validation-set.v2", "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}, "notices": [{"notice_id": value} for value in ids]}), encoding="utf-8")
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

    def prepare_execution(self, session, **kwargs):
        self.calls += 1
        if self.calls == 2:
            raise ScreeningCreationError("queue_failure")
        execution_id = "scr-" + "1" * 32
        store = ArtifactStore(self.settings.bidops_root)
        store.execution_dir(execution_id, create=True)
        ownership = store.capture_execution_ownership(execution_id)
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id,
            "run_id": FIXED_RUN_ID, "generated_at": NOW.isoformat(), "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"},
            "policy_version": "policy-1", "prompt_version": "prompt-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST,
            "candidate_count": 40, "notices": [{"notice_id": f"n-{i}"} for i in range(40)],
        }
        path, digest = store.write_json(execution_id, "screening-input.json", input_value)
        row = ScreeningExecution(
                execution_id=execution_id, trigger="quality_gate", source_run_id=FIXED_RUN_ID,
                scope="quality_sample", status="대기", requested_by="tester", policy_version="policy-1",
                prompt_version="prompt-1", model_name="qwen3.8:27b", model_digest=DIGEST,
                company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
                input_artifact_path=path, input_artifact_digest=digest,
                artifact_dir=f"data/screening-executions/{execution_id}", queued_at=NOW,
                candidate_count=40, completed_count=0, failure_count=0,
            )
        session.add(row)
        session.flush()
        return SimpleNamespace(
            created=CreatedExecution(execution_id, "대기", "qwen3.8:27b", DIGEST, PROFILE_VERSION, DIGEST,
                                     f"data/screening-executions/{execution_id}", path, digest),
            row=row,
            ownership=ownership,
        )


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


def test_production_transaction_preparer_publishes_two_fifo_rows_atomically(tmp_path: Path):
    root = tmp_path
    _fixed_fixture(root)
    from tests.test_screening_orchestrator import _notice

    notices = [_notice(f"n-{index}") for index in range(40)]
    (root / FIXED_SAMPLE_RELATIVE).write_text(
        json.dumps({"schema_version": "bidops.validation-set.v2", "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}, "notices": notices}, ensure_ascii=False), encoding="utf-8"
    )
    run_dir = root / "data/runs" / FIXED_RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "collected-notices.json").write_text(json.dumps({
        "schema_version": "bidops.collected.v2",
        "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"},
        "notices": notices,
    }, ensure_ascii=False), encoding="utf-8")
    (root / "docs/reference").mkdir(parents=True, exist_ok=True)
    (root / "docs/reference/company-profile.md").write_text("# profile\n", encoding="utf-8")
    settings = Settings(bidops_root=root, data_dir=root / "data", database_url=f"sqlite:///{root / 'quality.db'}")
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    body = load_policy_file()
    with factory() as session:
        session.add(Run(id=FIXED_RUN_ID, timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(ScreeningPolicy(
            policy_version=body["policy_version"], schema_version=body["schema_version"],
            prompt_version=body["prompt_version"], content_digest=policy_content_digest(body),
            status="activation_candidate", perspective_prompts_json=body["perspective_prompts"],
            counterargument_prompt_json=body["counterargument_prompt"], synthesis_prompt_json=body["synthesis_prompt"],
            candidate_selection_json=body["candidate_selection"], thresholds_json=body["thresholds"],
            created_at=NOW, created_by="tester",
        ))
        session.commit()

    class FakeModel:
        def inspect_model(self):
            return ModelIdentity(MODEL_NAME, "c" * 64)

    orchestrator = ScreeningOrchestrator(settings, session_factory=factory, ollama=FakeModel(), clock=lambda: NOW)
    gate = QualityGateService(settings, session_factory=factory, orchestrator=orchestrator).create_gate(
        purpose="operational_approval", policy_version=body["policy_version"], profile_source="current", created_by="tester"
    )
    with Session(engine) as session:
        rows = session.scalars(select(ScreeningExecution).order_by(ScreeningExecution.queue_no)).all()
        assert [row.execution_id for row in rows] == [gate.pass_a_execution_id, gate.pass_b_execution_id]
        assert [row.queue_no for row in rows] == [1, 2]
        assert all(row.status == "대기" for row in rows)
    a = ArtifactStore(root).read_json(gate.pass_a_execution_id, "screening-input.json")
    b = ArtifactStore(root).read_json(gate.pass_b_execution_id, "screening-input.json")
    assert a["execution_id"] != b["execution_id"]
    assert a["notices"] == b["notices"]
    assert a["source_window"] == {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
    assert all(item["judgment_mode"] == "신규" and item["carry_over_from"] is None and item["rejudge_reason"] is None for item in a["notices"])


def _completed_gate_fixture(root: Path):
    settings, engine, factory = _service_fixture(root)
    from tests.test_quality_metrics import judgment

    store = ArtifactStore(root)
    execution_rows: list[ScreeningExecution] = []
    judgments_a: list[dict[str, object]] = []
    for pass_index in (1, 2):
        execution_id = "scr-" + str(pass_index) * 32
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id,
            "run_id": FIXED_RUN_ID, "generated_at": NOW.isoformat(),
            "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"},
            "policy_version": "policy-1", "prompt_version": "prompt-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST,
            "candidate_count": 40,
            "notices": [{"notice_id": f"n-{i}", "judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None} for i in range(40)],
        }
        store.execution_dir(execution_id, create=True)
        input_path, input_digest = store.write_json(execution_id, "screening-input.json", input_value)
        decisions: list[dict[str, object]] = []
        for i in range(40):
            value = dict(judgment(f"n-{i}"))
            value.update({"model_digest": DIGEST, "prompt_version": "prompt-1", "policy_version": "policy-1", "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST, "judged_in_run": FIXED_RUN_ID, "recorded_in_run": FIXED_RUN_ID})
            decisions.append(value)
        if pass_index == 1:
            judgments_a = decisions
        decisions_value = {
            "schema_version": "bidops.decisions.v3", "execution_id": execution_id, "run_id": FIXED_RUN_ID,
            "generated_at": NOW.isoformat(), "screening_basis": "회차에 고정된 정규화 공고와 회사 프로필·정책 버전",
            "model_name": MODEL_NAME, "model_digest": DIGEST, "prompt_version": "prompt-1", "policy_version": "policy-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST, "judgments": decisions,
        }
        decision_path, _decision_digest = store.write_json(execution_id, "screening-decisions.json", decisions_value)
        execution_rows.append(ScreeningExecution(
            execution_id=execution_id, trigger="quality_gate", source_run_id=FIXED_RUN_ID, scope="quality_sample", status="성공",
            requested_by="tester", policy_version="policy-1", prompt_version="prompt-1", model_name=MODEL_NAME,
            model_digest=DIGEST, company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
            input_artifact_path=input_path, input_artifact_digest=input_digest, artifact_dir=f"data/screening-executions/{execution_id}",
            queued_at=NOW, finished_at=NOW, candidate_count=40, completed_count=40, failure_count=0,
        ))
    sample_raw = (root / FIXED_SAMPLE_RELATIVE).read_bytes()
    baseline_raw = (root / FIXED_BASELINE_RELATIVE).read_bytes()
    gate_id = "gate-" + "f" * 32
    with factory() as session:
        session.add_all(execution_rows)
        session.add(QualityGate(
            gate_id=gate_id, purpose="operational_approval", execution_status="대기", result_status="미측정",
            baseline_run_id=FIXED_RUN_ID, sample_artifact_path=FIXED_SAMPLE_RELATIVE, sample_artifact_digest=hashlib.sha256(sample_raw).hexdigest(),
            baseline_decisions_path=FIXED_BASELINE_RELATIVE, baseline_decisions_digest=hashlib.sha256(baseline_raw).hexdigest(),
            policy_version="policy-1", prompt_version="prompt-1", model_name=MODEL_NAME, model_digest=DIGEST,
            company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
            pass_a_execution_id=execution_rows[0].execution_id, pass_b_execution_id=execution_rows[1].execution_id,
            created_at=NOW, metrics_json={}, reasons_json=[], created_by="tester",
        ))
        session.add(QualityGateEvaluation(
            evaluation_id="gateeval-" + "f" * 32, gate_id=gate_id, revision=1, result_status="미측정",
            metrics_json={}, reasons_json=["execution_pending"], valid_review_count=0, distinct_notice_review_count=0, created_at=NOW,
        ))
        session.commit()
    return settings, engine, factory, gate_id, judgments_a


def test_refresh_review_upsert_audit_and_immutable_history(tmp_path: Path):
    settings, engine, factory, gate_id, judgments_a = _completed_gate_fixture(tmp_path)
    service = QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace())
    first = service.refresh(gate_id)
    assert first.revision == 2
    assert first.result_status == "미측정"
    for index in range(10):
        service.upsert_review(
            gate_id, f"n-{index}", reviewer="reviewer", evidence_judgment="동의",
            decision_digest=judgment_digest(judgments_a[index]), note=f"old-{index}",
        )
    updated = service.upsert_review(
        gate_id, "n-0", reviewer="reviewer", evidence_judgment="근거 부족",
        decision_digest=judgment_digest(judgments_a[0]), note="new-note",
    )
    assert updated.note == "new-note"
    with Session(engine) as session:
        evaluations = session.scalars(select(QualityGateEvaluation).where(QualityGateEvaluation.gate_id == gate_id).order_by(QualityGateEvaluation.revision)).all()
        assert [row.revision for row in evaluations] == list(range(1, len(evaluations) + 1))
        assert evaluations[0].result_status == "미측정"
        audits = session.scalars(select(AuditEvent).where(AuditEvent.event_type == "quality_gate.review_updated").order_by(AuditEvent.event_id)).all()
        assert any(
            isinstance(event.details_json.get("before"), dict)
            and event.details_json["before"].get("note") == "old-0"
            and event.details_json["after"].get("note") == "new-note"
            for event in audits
        )
        review = session.scalar(select(QualityGateReview).where(QualityGateReview.gate_id == gate_id, QualityGateReview.notice_id == "n-0"))
        assert review is not None and review.execution_id == "scr-" + "1" * 32
