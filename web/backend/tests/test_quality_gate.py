from __future__ import annotations

import copy
from dataclasses import replace
import inspect
import json
import hashlib
import os
import pickle
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

import app.screening.quality_gate as quality_gate_module
import app.screening.orchestrator as orchestrator_module
from app.config import Settings
from app.db import Base
from app.ingest.loader import ingest_run, deterministic_run_id
from app.models import AuditEvent, CompanyProfileSnapshot, Judgment, Notice, QualityGate, QualityGateEvaluation, QualityGateReview, Run, ScreeningExecution, ScreeningPolicy
from app.screening.artifacts import ArtifactStore
from app.screening.contracts import MODEL_NAME, ModelIdentity, two_axis_mixing
from app.screening.orchestrator import (
    CreatedExecution,
    ScreeningCreationError,
    ScreeningOrchestrator,
    _QUALITY_BINDING_FACTORY_CAPABILITY,
    _QualitySampleBinding,
    _binding_registry_state,
    _consume_quality_binding,
    _make_quality_sample_binding,
)
from app.screening.policy import load_policy_file, policy_content_digest
from app.screening.profile_snapshot import BASELINE_COMMIT
from app.screening.generation_config import legacy_generation_config
from app.screening.quality_metrics import judgment_digest
from app.screening.quality_gate import (
    FIXED_BASELINE_RELATIVE,
    FIXED_BASELINE_DIGEST,
    FIXED_RESULTS_DIGEST,
    FIXED_SAMPLE_DIGEST,
    FIXED_RESULTS_RELATIVE,
    FIXED_RUN_ID,
    FIXED_SAMPLE_RELATIVE,
    QualityGateConflict,
    QualityGateValidationError,
    validate_fixed_inputs,
    QualityGateService,
    _metric_structure_reasons,
    _input_matches_fixed_sample,
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
    sample_path.write_text(json.dumps({
        "schema_version": "bidops.validation-set.v2",
        "source_window": {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"},
        "notices": [
            {"notice_id": value, "sample_stratum": "AI/데이터", "sample_role": "analysis" if index % 2 == 0 else "audit"}
            for index, value in enumerate(ids)
        ],
    }), encoding="utf-8")
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


@pytest.mark.parametrize(
    "field_value",
    [None, "not-a-role", 17],
)
def test_fixed_sample_rejects_missing_or_invalid_sample_annotations(tmp_path: Path, field_value):
    _fixed_fixture(tmp_path)
    path = tmp_path / FIXED_SAMPLE_RELATIVE
    value = json.loads(path.read_text(encoding="utf-8"))
    if field_value is None:
        value["notices"][0].pop("sample_role")
    else:
        value["notices"][0]["sample_role"] = field_value
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(QualityGateValidationError):
        validate_fixed_inputs(tmp_path)


def test_fixed_sample_binding_preserves_order_and_metadata(tmp_path: Path):
    _fixed_fixture(tmp_path)
    sample, _baseline, _sample_raw, _baseline_raw, ids = validate_fixed_inputs(tmp_path)
    value = {"notices": [dict(item) for item in sample["notices"]]}
    assert _input_matches_fixed_sample(value, sample, ids)

    value["notices"][0]["sample_role"] = "audit"
    assert not _input_matches_fixed_sample(value, sample, ids)
    value["notices"][0] = dict(sample["notices"][1])
    value["notices"][1] = dict(sample["notices"][0])
    assert not _input_matches_fixed_sample(value, sample, ids)

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


def _canonical_service_fixture(root: Path):
    """Build the production fixed source and ingest its suffixed Run row."""

    production_root = Path(__file__).resolve().parents[3]
    run_dir = root / "data/runs" / FIXED_RUN_ID
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(production_root / "data/runs" / FIXED_RUN_ID, run_dir)
    (root / "docs/reference").mkdir(parents=True, exist_ok=True)
    shutil.copy(production_root / "docs/reference/company-profile.md", root / "docs/reference/company-profile.md")
    settings = Settings(bidops_root=root, data_dir=root / "data", database_url=f"sqlite:///{root / 'quality.db'}")
    engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    body = load_policy_file()
    body["policy_version"] = "policy-1"
    with factory() as session:
        ingested = ingest_run(run_dir, session, reports_root=root / "reports")
        session.add(ScreeningPolicy(
            policy_version=body["policy_version"], prompt_version=body["prompt_version"],
            content_digest=policy_content_digest(body), status="activation_candidate",
            schema_version=body["schema_version"], perspective_prompts_json=body["perspective_prompts"],
            counterargument_prompt_json=body["counterargument_prompt"],
            synthesis_prompt_json=body["synthesis_prompt"], candidate_selection_json=body["candidate_selection"],
            thresholds_json=body["thresholds"],
            created_at=NOW, created_by="tester",
        ))
        session.commit()
    return settings, engine, factory, run_dir, ingested.run_id


def _assert_no_gate_side_effects(engine, root: Path) -> None:
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QualityGate)) == 0
        assert session.scalar(select(func.count()).select_from(ScreeningExecution)) == 0
    execution_root = root / "data/screening-executions"
    assert not execution_root.exists() or not list(execution_root.iterdir())


class _FailingPassOrchestrator:
    def __init__(self, settings, factory, *, run_id: str, sample: dict[str, object]):
        self.settings = settings
        self.factory = factory
        self.run_id = run_id
        self.sample = sample
        self.queue = SimpleNamespace()
        self.calls = 0

    def prepare_execution(self, session, **kwargs):
        self.calls += 1
        if self.calls == 2:
            raise ScreeningCreationError("queue_failure")
        execution_id = "scr-" + "1" * 32
        store = ArtifactStore(self.settings.bidops_root)
        workspace = store.create_execution_workspace(execution_id)
        legacy = legacy_generation_config()
        input_value = {
            "schema_version": "bidops.screening-input.v1", "execution_id": execution_id,
            "run_id": self.run_id, "generated_at": NOW.isoformat(), "source_window": self.sample["source_window"],
            "policy_version": "policy-1", "prompt_version": "prompt-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST,
            "candidate_count": 40,
            "notices": [
                {**item, "judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None}
                for item in self.sample["notices"]
            ],
            "generation_config": legacy.canonical_value(), "generation_config_digest": legacy.digest(),
        }
        path, digest = workspace.write_json("screening-input.json", input_value)
        row = ScreeningExecution(
                execution_id=execution_id, trigger="quality_gate", source_run_id=self.run_id,
                scope="quality_sample", status="대기", requested_by="tester", policy_version="policy-1",
                prompt_version="prompt-1", model_name="qwen3.8:27b", model_digest=DIGEST,
                company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
                input_artifact_path=path, input_artifact_digest=digest,
                artifact_dir=f"data/screening-executions/{execution_id}", queued_at=NOW,
                candidate_count=40, completed_count=0, failure_count=0,
                generation_config_json=legacy.canonical_value(), generation_config_digest=legacy.digest(),
            )
        session.add(row)
        session.flush()
        return SimpleNamespace(
            created=CreatedExecution(execution_id, "대기", "qwen3.8:27b", DIGEST, PROFILE_VERSION, DIGEST,
                                     f"data/screening-executions/{execution_id}", path, digest),
            row=row,
            workspace=workspace,
        )


def test_failed_second_pass_leaves_no_execution_or_artifact(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    fixed_sample = json.loads((tmp_path / FIXED_SAMPLE_RELATIVE).read_text(encoding="utf-8"))
    with factory() as session:
        session.add(CompanyProfileSnapshot(
            digest=DIGEST, version=PROFILE_VERSION, source_kind="working_tree",
            source_ref="docs/reference/company-profile.md",
            artifact_path=f"web/data/profile-snapshots/{DIGEST}.md", created_at=NOW,
        ))
        session.commit()
    orchestrator = _FailingPassOrchestrator(
        settings, factory, run_id=canonical_run_id, sample=fixed_sample,
    )
    service = QualityGateService(settings, session_factory=factory, orchestrator=orchestrator)
    with pytest.raises(ScreeningCreationError):
        service.create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    assert orchestrator.calls == 2
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
    production_root = Path(__file__).resolve().parents[3]
    run_dir = root / "data/runs" / FIXED_RUN_ID
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(production_root / "data/runs" / FIXED_RUN_ID, run_dir)
    (root / "docs/reference").mkdir(parents=True, exist_ok=True)
    shutil.copy(production_root / "docs/reference/company-profile.md", root / "docs/reference/company-profile.md")
    settings = Settings(bidops_root=root, data_dir=root / "data", database_url=f"sqlite:///{root / 'quality.db'}")
    engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    body = load_policy_file()
    with factory() as session:
        ingested = ingest_run(run_dir, session, reports_root=root / "reports")
        canonical_run_id = ingested.run_id
        assert canonical_run_id == "20260817-20260823--20260824T090927.138116Z"
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
        assert session.get(Run, FIXED_RUN_ID) is None
        run = session.get(Run, canonical_run_id)
        assert run is not None
        rows = session.scalars(select(ScreeningExecution).order_by(ScreeningExecution.queue_no)).all()
        assert [row.execution_id for row in rows] == [gate.pass_a_execution_id, gate.pass_b_execution_id]
        assert [row.queue_no for row in rows] == [1, 2]
        assert all(row.status == "대기" for row in rows)
        assert [row.source_run_id for row in rows] == [canonical_run_id, canonical_run_id]
        gate_row = session.get(QualityGate, gate.gate_id)
        assert gate_row is not None
        assert gate_row.baseline_run_id == canonical_run_id
        assert session.get(Run, gate_row.baseline_run_id).id == canonical_run_id
    a = ArtifactStore(root).read_json(gate.pass_a_execution_id, "screening-input.json")
    b = ArtifactStore(root).read_json(gate.pass_b_execution_id, "screening-input.json")
    sample, _baseline, _sample_raw, _baseline_raw, sample_ids = validate_fixed_inputs(root, strict=True)
    assert a["execution_id"] != b["execution_id"]
    assert a["run_id"] == canonical_run_id and b["run_id"] == canonical_run_id
    assert a["notices"] == b["notices"]
    assert _input_matches_fixed_sample(a, sample, sample_ids)
    assert _input_matches_fixed_sample(b, sample, sample_ids)
    assert [item["notice_id"] for item in a["notices"]] == sample_ids
    assert [item["notice_id"] for item in b["notices"]] == sample_ids
    assert a["candidate_count"] == b["candidate_count"] == 40
    assert a["source_window"] == {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
    assert all(item["judgment_mode"] == "신규" and item["carry_over_from"] is None and item["rejudge_reason"] is None for item in a["notices"])


@pytest.mark.parametrize(
    ("relative", "expected_digest"),
    [
        (FIXED_SAMPLE_RELATIVE, FIXED_SAMPLE_DIGEST),
        (FIXED_BASELINE_RELATIVE, FIXED_BASELINE_DIGEST),
        (FIXED_RESULTS_RELATIVE, FIXED_RESULTS_DIGEST),
    ],
)
def test_trusted_fixed_hash_pin_tamper_is_fail_closed_without_side_effects(
    tmp_path: Path, relative: str, expected_digest: str
):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    path = tmp_path / relative
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    assert hashlib.sha256(original).hexdigest() == expected_digest
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)
    with Session(engine) as session:
        assert session.get(Run, canonical_run_id) is not None


@pytest.mark.parametrize("relative", [FIXED_SAMPLE_RELATIVE, FIXED_BASELINE_RELATIVE, FIXED_RESULTS_RELATIVE])
def test_strict_fixed_source_rejects_symlinked_file(tmp_path: Path, relative: str):
    production_root = Path(__file__).resolve().parents[3]
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((production_root / relative).read_bytes())
    real = tmp_path / "outside-fixed-input.json"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(QualityGateValidationError):
        quality_gate_module._read_strict_fixed_snapshot(tmp_path)


def test_trusted_snapshot_is_deep_immutable_and_cannot_be_forged_for_resolver(tmp_path: Path):
    _settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)

    with pytest.raises(TypeError):
        snapshot.sample["notices"][0]["sample_role"] = "audit"  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot.sample["notices"].append({})  # type: ignore[union-attr]
    with pytest.raises(TypeError):
        quality_gate_module._FixedInputSnapshot(
            root=snapshot.root, sample=snapshot.sample, baseline=snapshot.baseline,
            results=snapshot.results, sample_raw=snapshot.sample_raw,
            baseline_raw=snapshot.baseline_raw, results_raw=snapshot.results_raw,
            sample_digest=snapshot.sample_digest, baseline_digest=snapshot.baseline_digest,
            results_digest=snapshot.results_digest, ids=snapshot.ids,
        )

    with Session(engine) as session:
        with pytest.raises(TypeError):
            quality_gate_module.resolve_fixed_run(session, tmp_path, snapshot=snapshot)
        resolved = quality_gate_module.resolve_fixed_run(session, tmp_path)
        assert resolved.id == canonical_run_id


def test_db_and_nested_snapshot_forge_is_rejected_without_gate_side_effects(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    with pytest.raises(TypeError):
        snapshot.sample["notices"][0]["title"] = "forged"  # type: ignore[index]
    with factory() as session:
        notice = session.scalar(select(Notice).where(Notice.run_id == canonical_run_id).order_by(Notice.id))
        assert notice is not None
        notice.title = "database forge"
        session.commit()

    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)


def test_snapshot_issuer_identity_rejects_copy_replace_pickle_and_field_forge(tmp_path: Path):
    _settings, engine, factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)

    for operation in (
        lambda: copy.copy(snapshot),
        lambda: copy.deepcopy(snapshot),
        lambda: replace(snapshot, sample_raw=b"forged"),
    ):
        try:
            forged = operation()
        except Exception:
            continue
        assert forged is not snapshot
        assert not quality_gate_module._snapshot_matches_raw(forged)

    try:
        forged_pickle = pickle.loads(pickle.dumps(snapshot))
    except Exception:
        forged_pickle = None
    if forged_pickle is not None:
        assert not quality_gate_module._snapshot_matches_raw(forged_pickle)

    object.__setattr__(snapshot, "sample_raw", b"forged")
    assert not quality_gate_module._snapshot_matches_raw(snapshot)
    with Session(engine) as session:
        with pytest.raises(QualityGateValidationError):
            quality_gate_module._resolve_fixed_run(
                session, tmp_path, snapshot=snapshot,
            )

    fresh = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    for name, value in (
        ("root", tmp_path / "other-root"),
        ("sample_digest", "0" * 64),
        ("canonical_run_id", "forged-run"),
    ):
        try:
            object.__setattr__(fresh, name, value)
        except (AttributeError, TypeError):
            pass
        else:
            assert not quality_gate_module._snapshot_matches_raw(fresh)


def test_snapshot_external_backing_mutation_cannot_change_semantics(tmp_path: Path):
    _settings, _engine, _factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    backing = {"nested": [{"value": "original"}]}
    frozen = quality_gate_module._deep_freeze(backing)
    backing["nested"][0]["value"] = "forged"
    backing["nested"].append({"value": "new"})
    assert frozen["nested"][0]["value"] == "original"
    assert len(frozen["nested"]) == 1


def test_snapshot_and_binding_canonical_identity_reject_foreign_root_and_run_id(tmp_path: Path):
    _settings, engine, _factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    with pytest.raises(TypeError):
        _make_quality_sample_binding(
            "arbitrary-run-id",
            source_token=snapshot,
            capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
        )
    with Session(engine) as session:
        with pytest.raises(QualityGateValidationError):
            quality_gate_module._resolve_fixed_run(
                session, tmp_path / "foreign-root", snapshot=snapshot,
            )

    _consume_quality_binding(binding, canonical_run_id, tmp_path)
    with pytest.raises(ScreeningCreationError):
        _consume_quality_binding(binding, canonical_run_id, tmp_path)
    forged = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    object.__setattr__(forged, "sample_raw", b"forged")
    with pytest.raises(ScreeningCreationError):
        _consume_quality_binding(forged, canonical_run_id, tmp_path)
    with pytest.raises(TypeError):
        _QualitySampleBinding(
            capability=object(), sample_raw=b"", baseline_raw=b"", results_raw=b"",
        )


def test_snapshot_issuer_state_is_opaque_and_old_registry_forge_is_ignored(tmp_path: Path, monkeypatch):
    _settings, _engine, _factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    module_namespace = vars(quality_gate_module)
    assert "_SNAPSHOT_FACTS" not in module_namespace
    assert "_SNAPSHOT_REFS" not in module_namespace
    issuer = module_namespace["_SNAPSHOT_ISSUER"]
    with pytest.raises(TypeError):
        vars(issuer)
    with pytest.raises(AttributeError):
        object.__getattribute__(issuer, "_IdentityIssuer__entries")
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(issuer, "lookup_fn", lambda _value: None)
    facts = quality_gate_module._snapshot_registry_entry(snapshot)
    assert isinstance(facts, tuple)
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(facts, "root", tmp_path / "foreign")
    monkeypatch.setattr(
        quality_gate_module,
        "_SNAPSHOT_FACTS",
        {id(snapshot): (tmp_path / "foreign", b"forged")},
        raising=False,
    )
    assert quality_gate_module._snapshot_matches_raw(snapshot)


def test_snapshot_closure_entry_tamper_is_authenticated_before_public_prepare(tmp_path: Path):
    _settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    lookup_vars = inspect.getclosurevars(quality_gate_module._SNAPSHOT_ISSUER.lookup_fn)
    entries = lookup_vars.nonlocals["entries"]
    assert "secret" not in lookup_vars.nonlocals
    record = entries[id(snapshot)]
    foreign_root = tmp_path / "foreign-root"
    foreign_root.mkdir()
    entries[id(snapshot)] = record._replace(
        facts=record.facts._replace(root=foreign_root, root_identity=(0, 0))
    )
    foreign_settings = Settings(
        bidops_root=foreign_root,
        data_dir=foreign_root / "data",
        database_url=f"sqlite:///{foreign_root / 'quality.db'}",
    )
    creator = ScreeningOrchestrator(
        foreign_settings,
        session_factory=factory,
        ollama=type("NoModelCall", (), {"inspect_model": lambda _self: (_ for _ in ()).throw(AssertionError("must reject before model"))})(),
        clock=lambda: NOW,
    )
    with factory() as session:
        with pytest.raises(ScreeningCreationError):
            creator.prepare_execution(
                session,
                run_id=canonical_run_id,
                policy_version="policy-1",
                requested_by="tester",
                scope="quality_sample",
                trigger="quality_gate",
                _quality_binding=binding,
            )
        session.rollback()
    assert quality_gate_module._snapshot_registry_entry(snapshot) is None
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
    execution_root = tmp_path / "data/screening-executions"
    assert not execution_root.exists() or not list(execution_root.iterdir())


@pytest.mark.parametrize("tamper", ["tag", "facts", "state"])
def test_snapshot_registry_tag_tamper_fails_closed(tmp_path: Path, tamper: str):
    _settings, _engine, _factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    entries = inspect.getclosurevars(quality_gate_module._SNAPSHOT_ISSUER.lookup_fn).nonlocals["entries"]
    record = entries[id(snapshot)]
    if tamper == "tag":
        forged = record._replace(tag=b"x" * len(record.tag))
    elif tamper == "facts":
        forged = record._replace(facts=record.facts._replace(canonical_run_id="forged-run"))
    else:
        forged = record._replace(state="used")
    entries[id(snapshot)] = forged
    assert not quality_gate_module._snapshot_matches_raw(snapshot)
    assert quality_gate_module._snapshot_registry_entry(snapshot) is None


@pytest.mark.parametrize("tamper", ["tag", "facts", "state"])
def test_binding_registry_tag_tamper_rejects_replay(tmp_path: Path, tamper: str):
    _settings, _engine, _factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    entries = inspect.getclosurevars(orchestrator_module._BINDING_ISSUER.lookup_fn).nonlocals["entries"]
    record = entries[id(binding)]
    if tamper == "tag":
        forged = record._replace(tag=b"x" * len(record.tag))
    elif tamper == "facts":
        forged = record._replace(facts=record.facts._replace(run_id="forged-run"))
    else:
        _consume_quality_binding(binding, canonical_run_id, tmp_path)
        record = entries[id(binding)]
        forged = record._replace(state="issued")
    entries[id(binding)] = forged
    with pytest.raises(ScreeningCreationError):
        _consume_quality_binding(binding, canonical_run_id, tmp_path)
    assert _binding_registry_state(binding) is None


def test_snapshot_binding_rejects_foreign_public_prepare_without_side_effect(tmp_path: Path):
    _settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    foreign_root = tmp_path / "foreign-service-root"
    foreign_settings = Settings(
        bidops_root=foreign_root,
        data_dir=foreign_root / "data",
        database_url=f"sqlite:///{foreign_root / 'quality.db'}",
    )
    creator = ScreeningOrchestrator(
        foreign_settings,
        session_factory=factory,
        ollama=type("NoModelCall", (), {"inspect_model": lambda _self: (_ for _ in ()).throw(AssertionError("must reject before model"))})(),
        clock=lambda: NOW,
    )
    with factory() as session:
        with pytest.raises(ScreeningCreationError):
            creator.prepare_execution(
                session,
                run_id=canonical_run_id,
                policy_version="policy-1",
                requested_by="tester",
                scope="quality_sample",
                trigger="quality_gate",
                _quality_binding=binding,
            )
        session.rollback()
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
    workspace_root = tmp_path / "data/screening-executions"
    assert not workspace_root.exists() or not list(workspace_root.iterdir())


@pytest.mark.parametrize("preflight", ["policy", "model", "profile"])
def test_quality_binding_preflight_failure_releases_retry_capability(tmp_path: Path, preflight: str):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    good_model = type(
        "GoodModel",
        (),
        {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)},
    )()
    bad_model = type(
        "BadModel",
        (),
        {"inspect_model": lambda _self: (_ for _ in ()).throw(OSError("model unavailable"))},
    )()
    bad_policy = "missing-policy" if preflight == "policy" else "policy-1"
    bad_profile = "invalid-profile" if preflight == "profile" else "current"
    bad_creator = ScreeningOrchestrator(
        settings,
        session_factory=factory,
        ollama=bad_model if preflight == "model" else good_model,
        clock=lambda: NOW,
    )
    with factory() as session:
        with pytest.raises(ScreeningCreationError):
            bad_creator.prepare_execution(
                session,
                run_id=canonical_run_id,
                policy_version=bad_policy,
                profile_source=bad_profile,
                requested_by="tester",
                scope="quality_sample",
                trigger="quality_gate",
                _quality_binding=binding,
            )
        session.rollback()
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
    workspace_root = tmp_path / "data/screening-executions"
    assert not workspace_root.exists() or not list(workspace_root.iterdir())

    good_creator = ScreeningOrchestrator(
        settings,
        session_factory=factory,
        ollama=good_model,
        clock=lambda: NOW,
    )
    with factory() as session:
        prepared = good_creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        session.commit()
        prepared.workspace.close()
    with Session(engine) as session:
        assert len(session.scalars(select(ScreeningExecution)).all()) == 1


def test_quality_binding_reservation_failure_releases_for_retry(tmp_path: Path, monkeypatch):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    good_model = type(
        "GoodModel",
        (),
        {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)},
    )()
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=good_model, clock=lambda: NOW)

    def fail_workspace(_self, _execution_id):
        raise OSError("workspace unavailable")

    monkeypatch.setattr(ArtifactStore, "create_execution_workspace", fail_workspace)
    with factory() as session:
        with pytest.raises(ScreeningCreationError):
            creator.prepare_execution(
                session,
                run_id=canonical_run_id,
                policy_version="policy-1",
                profile_source="current",
                requested_by="tester",
                scope="quality_sample",
                trigger="quality_gate",
                _quality_binding=binding,
            )
        session.rollback()
    with Session(engine) as session:
        assert session.scalars(select(ScreeningExecution)).all() == []
    monkeypatch.undo()
    with factory() as session:
        prepared = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        session.commit()
        prepared.workspace.close()


def test_quality_binding_outer_rollback_releases_and_commit_consumes(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    model = type(
        "GoodModel",
        (),
        {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)},
    )()
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=model, clock=lambda: NOW)
    store = ArtifactStore(settings.bidops_root)
    with factory() as session:
        first = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        assert _binding_registry_state(binding) == "reserved"
        session.rollback()
        store.remove_execution(first.workspace)
        first.workspace.close()
        assert _binding_registry_state(binding) == "issued"

        second = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        assert _binding_registry_state(binding) == "reserved"
        session.commit()
        second.workspace.close()
        assert _binding_registry_state(binding) == "used"
    with Session(engine) as session:
        assert len(session.scalars(select(ScreeningExecution)).all()) == 1

    with factory() as session:
        with pytest.raises(ScreeningCreationError):
            creator.prepare_execution(
                session,
                run_id=canonical_run_id,
                policy_version="policy-1",
                profile_source="current",
                requested_by="tester",
                scope="quality_sample",
                trigger="quality_gate",
                _quality_binding=binding,
            )
        session.rollback()


def test_quality_binding_nested_savepoint_lifecycle_is_transaction_aware(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
    binding = _make_quality_sample_binding(
        canonical_run_id,
        source_token=snapshot,
        capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
    )
    model = type(
        "GoodModel",
        (),
        {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)},
    )()
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=model, clock=lambda: NOW)
    store = ArtifactStore(settings.bidops_root)
    with factory() as session:
        outer = session.begin()
        nested = session.begin_nested()
        first = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        nested.rollback()
        assert _binding_registry_state(binding) == "issued"
        store.remove_execution(first.workspace)
        first.workspace.close()

        nested = session.begin_nested()
        second = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        nested.commit()
        assert _binding_registry_state(binding) == "reserved"
        outer.rollback()
        assert _binding_registry_state(binding) == "issued"
        store.remove_execution(second.workspace)
        second.workspace.close()

        outer = session.begin()
        nested = session.begin_nested()
        third = creator.prepare_execution(
            session,
            run_id=canonical_run_id,
            policy_version="policy-1",
            profile_source="current",
            requested_by="tester",
            scope="quality_sample",
            trigger="quality_gate",
            _quality_binding=binding,
        )
        nested.commit()
        outer.commit()
        third.workspace.close()
        assert _binding_registry_state(binding) == "used"
    with Session(engine) as session:
        assert len(session.scalars(select(ScreeningExecution)).all()) == 1


def test_quality_binding_concurrent_consume_and_invalid_preflight_race(tmp_path: Path):
    _settings, _engine, _factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    snapshot_refs = []

    def issue():
        snapshot = quality_gate_module._read_strict_fixed_snapshot(tmp_path)
        snapshot_refs.append(snapshot)
        return _make_quality_sample_binding(
            canonical_run_id,
            source_token=snapshot,
            capability=_QUALITY_BINDING_FACTORY_CAPABILITY,
        )

    binding = issue()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcome_lock = threading.Lock()

    def consume_once():
        barrier.wait()
        try:
            _consume_quality_binding(binding, canonical_run_id, tmp_path)
        except ScreeningCreationError:
            outcome = "rejected"
        else:
            outcome = "accepted"
        with outcome_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=consume_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(outcomes) == ["accepted", "rejected"]

    binding = issue()
    barrier = threading.Barrier(2)
    outcomes = []

    def consume_with_run(candidate_run_id: str):
        barrier.wait()
        try:
            _consume_quality_binding(binding, candidate_run_id, tmp_path)
        except ScreeningCreationError:
            outcome = "rejected"
        else:
            outcome = "accepted"
        with outcome_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=consume_with_run, args=("invalid-run",)),
        threading.Thread(target=consume_with_run, args=(canonical_run_id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(outcomes) == ["accepted", "rejected"]


@pytest.mark.parametrize("unsupported", ["_O_NOFOLLOW", "_O_DIRECTORY", "supports_dir_fd"])
def test_fixed_secure_open_unsupported_platform_fails_closed(tmp_path: Path, monkeypatch, unsupported: str):
    production_root = Path(__file__).resolve().parents[3]
    shutil.copytree(production_root / "data/runs" / FIXED_RUN_ID, tmp_path / "data/runs" / FIXED_RUN_ID)
    if unsupported == "supports_dir_fd":
        monkeypatch.setattr(quality_gate_module.os, "supports_dir_fd", set())
    else:
        monkeypatch.setattr(quality_gate_module, unsupported, 0)
    with pytest.raises(QualityGateValidationError):
        quality_gate_module._read_strict_fixed_snapshot(tmp_path)


@pytest.mark.parametrize("component", ["data", "runs", FIXED_RUN_ID])
def test_strict_fixed_source_rejects_symlinked_path_component(tmp_path: Path, component: str):
    production_root = Path(__file__).resolve().parents[3]
    source = production_root / "data/runs" / FIXED_RUN_ID
    target = tmp_path / "data/runs" / FIXED_RUN_ID
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    if component == "data":
        original, moved = tmp_path / "data", tmp_path / "data-real"
    elif component == "runs":
        original, moved = tmp_path / "data/runs", tmp_path / "runs-real"
    else:
        original, moved = target, tmp_path / "run-real"
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    with pytest.raises(QualityGateValidationError):
        quality_gate_module._read_strict_fixed_snapshot(tmp_path)


def test_fixed_snapshot_path_swap_during_second_prepare_has_no_input_effect(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    delegate = ScreeningOrchestrator(
        settings, session_factory=factory,
        ollama=type("FakeModel", (), {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)})(),
        clock=lambda: NOW,
    )

    class SwappingOrchestrator:
        def __init__(self):
            self.calls = 0

        def prepare_execution(self, session, **kwargs):
            prepared = delegate.prepare_execution(session, **kwargs)
            self.calls += 1
            if self.calls == 1:
                path = tmp_path / FIXED_SAMPLE_RELATIVE
                swapped = path.with_name("validation-set.swap.json")
                swapped.write_bytes(path.read_bytes() + b"\n")
                path.rename(path.with_name("validation-set.original.json"))
                swapped.rename(path)
            return prepared

    orchestrator = SwappingOrchestrator()
    gate = QualityGateService(settings, session_factory=factory, orchestrator=orchestrator).create_gate(
        purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
    )
    assert orchestrator.calls == 2
    with Session(engine) as session:
        rows = session.scalars(select(ScreeningExecution).order_by(ScreeningExecution.queue_no)).all()
        assert len(rows) == 2
        assert all(row.source_run_id == canonical_run_id for row in rows)
        assert session.get(QualityGate, gate.gate_id) is not None
        before = session.scalar(select(func.count()).select_from(QualityGateEvaluation))
        for row in rows:
            row.status = "성공"
            row.completed_count = 40
            row.finished_at = NOW
        session.commit()
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).refresh(gate.gate_id)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QualityGateEvaluation)) == before


def test_fixed_snapshot_aba_restore_during_prepare_keeps_original_semantics(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    delegate = ScreeningOrchestrator(
        settings, session_factory=factory,
        ollama=type("FakeModel", (), {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)})(),
        clock=lambda: NOW,
    )

    class AbaOrchestrator:
        def prepare_execution(self, session, **kwargs):
            prepared = delegate.prepare_execution(session, **kwargs)
            path = tmp_path / FIXED_SAMPLE_RELATIVE
            raw = path.read_bytes()
            original_stat = path.stat()
            path.write_bytes(raw + b"\n")
            path.write_bytes(raw)
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return prepared

    gate = QualityGateService(settings, session_factory=factory, orchestrator=AbaOrchestrator()).create_gate(
        purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
    )
    with Session(engine) as session:
        rows = session.scalars(select(ScreeningExecution)).all()
        assert len(rows) == 2 and all(row.source_run_id == canonical_run_id for row in rows)
        assert session.get(QualityGate, gate.gate_id) is not None


@pytest.mark.parametrize("relative", [FIXED_SAMPLE_RELATIVE, FIXED_BASELINE_RELATIVE, FIXED_RESULTS_RELATIVE])
def test_refresh_fixed_source_tamper_has_no_evaluation_side_effect(tmp_path: Path, relative: str):
    settings, engine, factory, gate_id, _judgments_a, _sample_ids = _completed_gate_fixture(tmp_path)
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b"\n")
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(QualityGateEvaluation))
        gate = session.get(QualityGate, gate_id)
        assert gate is not None and gate.execution_status == "대기"
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).refresh(gate_id)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(QualityGateEvaluation)) == before
        gate = session.get(QualityGate, gate_id)
        assert gate is not None and gate.execution_status == "대기"


@pytest.mark.parametrize(
    ("status_a", "status_b"),
    [("대기", "대기"), ("실행 중", "대기"), ("성공", "성공")],
)
def test_refresh_tamper_is_fail_closed_before_pending_running_or_terminal_side_effect(
    tmp_path: Path, status_a: str, status_b: str,
):
    settings, engine, factory, gate_id, _judgments_a, _sample_ids = _completed_gate_fixture(tmp_path)
    with factory() as session:
        gate = session.get(QualityGate, gate_id)
        assert gate is not None
        rows = [
            session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_a_execution_id)),
            session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_b_execution_id)),
        ]
        assert all(row is not None for row in rows)
        rows[0].status = status_a
        rows[1].status = status_b
        if status_a in {"대기", "실행 중"}:
            rows[0].finished_at = None
        if status_b in {"대기", "실행 중"}:
            rows[1].finished_at = None
        if status_a == "실행 중":
            rows[0].active_slot = 1
            rows[0].started_at = NOW
            rows[0].heartbeat_at = NOW
        session.commit()
    with Session(engine) as session:
        gate = session.get(QualityGate, gate_id)
        assert gate is not None
        before_gate = (gate.execution_status, gate.result_status, gate.completed_at, gate.metrics_json, gate.reasons_json)
        before_evaluations = session.scalar(select(func.count()).select_from(QualityGateEvaluation))
        before_rows = [
            (row.execution_id, row.status, row.finished_at, row.completed_count, row.failure_count)
            for row in session.scalars(select(ScreeningExecution).where(ScreeningExecution.execution_id.in_([gate.pass_a_execution_id, gate.pass_b_execution_id])).order_by(ScreeningExecution.execution_id))
        ]
    path = tmp_path / FIXED_SAMPLE_RELATIVE
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).refresh(gate_id)
    with Session(engine) as session:
        gate = session.get(QualityGate, gate_id)
        assert gate is not None
        assert (gate.execution_status, gate.result_status, gate.completed_at, gate.metrics_json, gate.reasons_json) == before_gate
        assert session.scalar(select(func.count()).select_from(QualityGateEvaluation)) == before_evaluations
        after_rows = [
            (row.execution_id, row.status, row.finished_at, row.completed_count, row.failure_count)
            for row in session.scalars(select(ScreeningExecution).where(ScreeningExecution.execution_id.in_([gate.pass_a_execution_id, gate.pass_b_execution_id])).order_by(ScreeningExecution.execution_id))
        ]
        assert after_rows == before_rows


def test_fixed_run_resolver_query_budget_is_bounded(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    statements: list[str] = []

    from sqlalchemy import event

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            resolved = quality_gate_module.resolve_fixed_run(session, tmp_path)
            assert resolved.id == canonical_run_id
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) < 30


def test_quality_gate_creation_query_budget_is_bounded(tmp_path: Path):
    settings, engine, factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    statements: list[str] = []

    from sqlalchemy import event

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    orchestrator = ScreeningOrchestrator(
        settings, session_factory=factory,
        ollama=type("FakeModel", (), {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)})(),
        clock=lambda: NOW,
    )
    event.listen(engine, "before_cursor_execute", record)
    try:
        QualityGateService(settings, session_factory=factory, orchestrator=orchestrator).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) < 100


@pytest.mark.parametrize("mutation", ["missing", "stale", "superseded", "ambiguous"])
def test_fixed_run_resolver_rejects_missing_stale_superseded_and_ambiguous_rows(
    tmp_path: Path, mutation: str
):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    with factory() as session:
        run = session.get(Run, canonical_run_id)
        assert run is not None
        if mutation == "missing":
            session.delete(run)
        elif mutation == "stale":
            run.generated_at = datetime(2026, 8, 24, 9, 9, 28, 138116, tzinfo=timezone.utc)
        elif mutation == "superseded":
            run.status = "superseded"
        else:
            session.add(Run(
                id="20260817-20260823--20260824T090928Z", window_from=run.window_from,
                window_to=run.window_to, timezone=run.timezone, generated_at=run.generated_at, status="active",
            ))
        session.commit()
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)


@pytest.mark.parametrize(
    "mutation",
    ["window", "generated_at", "count", "order", "notice_id", "normalized_field", "judgment", "provenance"],
)
def test_fixed_run_projection_mismatches_are_rejected_before_gate_side_effects(
    tmp_path: Path, mutation: str
):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)
    with factory() as session:
        run = session.get(Run, canonical_run_id)
        notices = session.scalars(select(Notice).where(Notice.run_id == canonical_run_id).order_by(Notice.id)).all()
        assert run is not None and len(notices) == 40
        if mutation == "window":
            run.window_to = run.window_to.replace(day=22)
        elif mutation == "generated_at":
            run.generated_at = datetime(2026, 8, 24, 9, 9, 28, 138116, tzinfo=timezone.utc)
        elif mutation == "count":
            session.delete(notices[-1])
        elif mutation == "order":
            first_id, second_id = notices[0].id, notices[1].id
            first_key, second_key = notices[0].notice_key, notices[1].notice_key
            session.execute(update(Notice).where(Notice.id == first_id).values(notice_key="__temporary-order-key__"))
            session.execute(update(Notice).where(Notice.id == second_id).values(notice_key=first_key))
            session.execute(update(Notice).where(Notice.id == first_id).values(notice_key=second_key))
        elif mutation == "notice_id":
            notices[0].notice_key = "bid:tampered:000"
        elif mutation == "normalized_field":
            notices[0].title = "tampered normalized title"
        elif mutation == "judgment":
            assert notices[0].judgment is not None
            notices[0].judgment.grade = "제외"
        else:
            assert notices[0].judgment is not None
            notices[0].judgment.schema_version = "bidops.decisions.v1"
        session.commit()
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "perspective_order", "perspective_duplicate", "perspective_negative", "perspective_missing",
        "counter_order", "counter_duplicate", "counter_negative", "counter_missing",
    ],
)
def test_fixed_run_child_position_contract_mismatches_are_rejected(tmp_path: Path, mutation: str):
    settings, engine, factory, _run_dir, _canonical_run_id = _canonical_service_fixture(tmp_path)
    with factory() as session:
        notices = session.scalars(select(Notice).order_by(Notice.id)).all()
        assert notices and notices[0].judgment is not None
        judgment = notices[0].judgment
        if mutation.startswith("perspective"):
            children = sorted(judgment.perspectives, key=lambda row: row.position or 0)
        else:
            children = sorted(judgment.counterarguments, key=lambda row: row.position or 0)
        assert len(children) >= 2
        if mutation.endswith("order"):
            children[0].position, children[1].position = children[1].position, children[0].position
        elif mutation.endswith("negative"):
            children[0].position = -1
        elif mutation.endswith("missing"):
            children[0].position = None
        else:
            children[1].position = children[0].position
        session.commit()
    with pytest.raises(QualityGateValidationError):
        QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)


def test_quality_pass_provenance_alias_is_rejected_before_gate_publish(tmp_path: Path):
    settings, engine, factory, _run_dir, canonical_run_id = _canonical_service_fixture(tmp_path)

    class AliasBindingOrchestrator:
        def __init__(self):
            self.delegate = ScreeningOrchestrator(
                settings, session_factory=factory,
                ollama=type("FakeModel", (), {"inspect_model": lambda _self: ModelIdentity(MODEL_NAME, "c" * 64)})(),
                clock=lambda: NOW,
            )

        def prepare_execution(self, session, **kwargs):
            prepared = self.delegate.prepare_execution(session, **kwargs)
            prepared.row.source_run_id = FIXED_RUN_ID
            return prepared

    service = QualityGateService(
        settings, session_factory=factory, orchestrator=AliasBindingOrchestrator()
    )
    with pytest.raises(QualityGateConflict):
        service.create_gate(
            purpose="operational_approval", policy_version="policy-1", profile_source="current", created_by="tester"
        )
    _assert_no_gate_side_effects(engine, tmp_path)
    with Session(engine) as session:
        assert session.get(Run, FIXED_RUN_ID) is None
        assert session.get(Run, canonical_run_id) is not None


def test_reingest_fixed_artifacts_reuses_one_canonical_id_and_no_alias_row(tmp_path: Path):
    production_root = Path(__file__).resolve().parents[3]
    run_dir = tmp_path / "data/runs" / FIXED_RUN_ID
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(production_root / "data/runs" / FIXED_RUN_ID, run_dir)
    engine = create_engine(f"sqlite:///{tmp_path / 'repeat.db'}", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = ingest_run(run_dir, session, reports_root=tmp_path / "reports")
        second = ingest_run(run_dir, session, reports_root=tmp_path / "reports")
        assert first.run_id == second.run_id == deterministic_run_id(
            FIXED_RUN_ID, datetime(2026, 8, 24, 9, 9, 27, 138116, tzinfo=timezone.utc)
        )
        assert session.scalar(select(func.count()).select_from(Run)) == 1
        assert session.scalar(select(func.count()).select_from(Notice)) == 40
        assert session.scalar(select(func.count()).select_from(Judgment)) == 40
        assert session.get(Run, FIXED_RUN_ID) is None


def _completed_gate_fixture(root: Path):
    settings, engine, factory = _service_fixture(root)
    production_root = Path(__file__).resolve().parents[3]
    for relative in (FIXED_SAMPLE_RELATIVE, FIXED_BASELINE_RELATIVE, FIXED_RESULTS_RELATIVE):
        destination = root / relative
        shutil.copy(production_root / relative, destination)
    fixed_sample = json.loads((root / FIXED_SAMPLE_RELATIVE).read_text(encoding="utf-8"))
    sample_ids = [item["notice_id"] for item in fixed_sample["notices"]]
    sample_by_id = {item["notice_id"]: item for item in fixed_sample["notices"]}
    # This fixture intentionally models a pre-binding v3 artifact: the
    # artifact JSON omits generation fields, so the persisted execution and
    # gate must carry the deterministic legacy binding.
    legacy_config = legacy_generation_config()
    legacy_value = legacy_config.canonical_value()
    legacy_digest = legacy_config.digest()
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
            "notices": [
                {**item, "judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None}
                for item in fixed_sample["notices"]
            ],
        }
        workspace = store.create_execution_workspace(execution_id)
        input_path, input_digest = workspace.write_json("screening-input.json", input_value)
        decisions: list[dict[str, object]] = []
        for notice_id in sample_ids:
            value = dict(judgment(notice_id))
            performance_matches = sample_by_id[notice_id].get("performance_matches") or []
            if performance_matches:
                value["matched_performances"] = [{
                    "name": match.get("project_name") or "검증 대상 수행실적",
                    "match_reason": "수행실적 후보 신호를 검토했습니다",
                    "mismatch_or_limit": "직접 정합성은 추가 확인이 필요합니다",
                    "source": str(match.get("source_page") or "수집 단계 performance_matches"),
                    "status": "unknown",
                } for match in performance_matches[:1]]
            mixing = two_axis_mixing(value["perspectives"], value["grade"])
            value.update({
                "notice_id": notice_id, "judgment_mode": "신규", "carried_over": False,
                "rejudge_reason": None, "model_name": MODEL_NAME, "model_digest": DIGEST,
                "prompt_version": "prompt-1", "policy_version": "policy-1",
                "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST,
                "judged_in_run": FIXED_RUN_ID, "recorded_in_run": FIXED_RUN_ID,
                "two_axis_mixing_flag": mixing.flag, "two_axis_mixing_label": mixing.label,
            })
            decisions.append(value)
        if pass_index == 1:
            judgments_a = decisions
        decisions_value = {
            "schema_version": "bidops.decisions.v3", "execution_id": execution_id, "run_id": FIXED_RUN_ID,
            "generated_at": NOW.isoformat(), "screening_basis": "회차에 고정된 정규화 공고와 회사 프로필·정책 버전",
            "model_name": MODEL_NAME, "model_digest": DIGEST, "prompt_version": "prompt-1", "policy_version": "policy-1",
            "company_profile_version": PROFILE_VERSION, "company_profile_digest": DIGEST, "judgments": decisions,
        }
        _decision_path, _decision_digest = store.write_json(execution_id, "screening-decisions.json", decisions_value)
        workspace.close()
        execution_rows.append(ScreeningExecution(
            execution_id=execution_id, trigger="quality_gate", source_run_id=FIXED_RUN_ID, scope="quality_sample", status="성공",
            requested_by="tester", policy_version="policy-1", prompt_version="prompt-1", model_name=MODEL_NAME,
            model_digest=DIGEST, company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
            generation_config_json=legacy_value, generation_config_digest=legacy_digest,
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
            generation_config_json=legacy_value, generation_config_digest=legacy_digest,
            company_profile_version=PROFILE_VERSION, company_profile_digest=DIGEST,
            pass_a_execution_id=execution_rows[0].execution_id, pass_b_execution_id=execution_rows[1].execution_id,
            created_at=NOW, metrics_json={}, reasons_json=[], created_by="tester",
        ))
        session.add(QualityGateEvaluation(
            evaluation_id="gateeval-" + "f" * 32, gate_id=gate_id, revision=1, result_status="미측정",
            metrics_json={}, reasons_json=["execution_pending"], valid_review_count=0, distinct_notice_review_count=0,
            generation_config_digest=legacy_digest, created_at=NOW,
        ))
        session.commit()
    return settings, engine, factory, gate_id, judgments_a, sample_ids


def test_refresh_review_upsert_audit_and_immutable_history(tmp_path: Path):
    settings, engine, factory, gate_id, judgments_a, sample_ids = _completed_gate_fixture(tmp_path)
    service = QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace())
    first = service.refresh(gate_id)
    assert first.revision == 2
    assert first.result_status == "미측정"
    for index in range(10):
        service.upsert_review(
            gate_id, sample_ids[index], reviewer="reviewer", evidence_judgment="동의",
            decision_digest=judgment_digest(judgments_a[index]), note=f"old-{index}",
        )
    updated = service.upsert_review(
        gate_id, sample_ids[0], reviewer="reviewer", evidence_judgment="근거 부족",
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
        review = session.scalar(select(QualityGateReview).where(QualityGateReview.gate_id == gate_id, QualityGateReview.notice_id == sample_ids[0]))
        assert review is not None and review.execution_id == "scr-" + "1" * 32


def test_partial_success_missing_notice_is_fixed_denominator_mismatch_not_structure_hold():
    metrics = {
        "excluded_notices": [
            {"notice_id": "n-0", "pass": "A", "reason": "missing_judgment"},
            {"notice_id": "n-1", "pass": "A", "reason": "invalid_judgment:counterarguments_missing"},
            {"notice_id": "n-2", "pass": "B", "reason": "missing_judgment"},
        ]
    }
    reasons = _metric_structure_reasons(metrics, partial_passes=frozenset({"A"}))
    assert "A_structure:n-0:missing_judgment" not in reasons
    assert "A_structure:n-1:invalid_judgment:counterarguments_missing" in reasons
    assert "B_structure:n-2:missing_judgment" in reasons


def test_partial_success_service_evaluation_does_not_hold_for_legal_missing_notice(tmp_path: Path):
    settings, engine, factory, gate_id, judgments_a, sample_ids = _completed_gate_fixture(tmp_path)
    store = ArtifactStore(tmp_path)
    with factory() as session:
        gate = session.get(QualityGate, gate_id)
        assert gate is not None
        pass_a_id = gate.pass_a_execution_id
    decisions = store.read_json(pass_a_id, "screening-decisions.json")
    decisions["judgments"] = decisions["judgments"][:-1]
    store.replace_json(pass_a_id, "screening-decisions.json", decisions)
    with factory() as session:
        execution = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == pass_a_id))
        assert execution is not None
        execution.status = "부분 성공"
        for index in range(10):
            session.add(QualityGateReview(
                gate_id=gate_id,
                execution_id=execution.execution_id,
                notice_id=sample_ids[index],
                decision_digest=judgment_digest(judgments_a[index]),
                reviewer="reviewer",
                evidence_judgment="동의",
                note="partial-success review",
                created_at=NOW,
                updated_at=NOW,
            ))
        session.commit()
    evaluation = QualityGateService(settings, session_factory=factory, orchestrator=SimpleNamespace()).refresh(gate_id)
    assert evaluation.result_status != "보류"
    assert not any("missing_judgment" in reason for reason in evaluation.reasons_json)
