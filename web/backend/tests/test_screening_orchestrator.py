from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.models import Notice, Run, ScreeningAttempt, ScreeningExecution, ScreeningPolicy
from app.screening.execution_store import ScreeningExecutionStore
from app.screening.ollama import OllamaClient
from app.screening.orchestrator import ScreeningOrchestrator
from app.screening.policy import load_policy_file, policy_content_digest
from app.screening.worker import ScreeningWorker, WorkerError
from tests.fakes import FakeOllamaTransport


NAMES = ("기술 적합성", "실적 정합성", "공공 SI 적합성", "사업성·자격 제약", "전략 부합")
NOW = datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc)


def _response(value: object, *, model: str = "qwen3.8:27b") -> dict[str, object]:
    return {
        "model": model, "done": True, "done_reason": "stop",
        "response": json.dumps(value, ensure_ascii=False),
        "prompt_eval_count": 1, "eval_count": 1,
        "prompt_eval_duration": 1, "eval_duration": 1,
        "load_duration": 1, "total_duration": 1,
    }


def _perspective(name: str) -> dict[str, object]:
    return {"name": name, "assessment": "적합", "reason": "공고와 회사 자료에 연결된 충분한 판단 근거입니다", "evidence": [{"source": "title", "status": "confirmed", "fact": "공고 제목에서 확인한 사실입니다"}]}


def _script(notice_id: str = "notice-1") -> list[dict[str, object]]:
    values: list[dict[str, object]] = [_response(_perspective(name)) for name in NAMES]
    counter = ["예산과 요구 역할의 세부 범위가 회사 수행 조건과 다를 수 있습니다"]
    values.append(_response({"counterarguments": counter}))
    values.append(_response({
        "notice_id": notice_id, "grade": "검토 권장", "readiness": "확인 완료",
        "primary_focus": "AI/데이터", "exclusion_category": None,
        "summary": "다섯 관점과 반론을 종합한 판단입니다",
        "perspectives": [_perspective(name) for name in NAMES], "matched_performances": [],
        "counterarguments": counter,
        "counterargument_resolutions": [{"counterargument": counter[0], "status": "추가 확인", "reflection": "담당자가 범위를 확인합니다"}],
        "verification_items": [], "next_action": "담당자가 원문 범위를 확인합니다",
    }))
    return values


def _notice(notice_id: str = "notice-1") -> dict[str, object]:
    return {
        "notice_id": notice_id, "source_type": "bid_notice", "title": "데이터 플랫폼 구축", "agency": "기관",
        "method": "일반경쟁", "url": "https://example.invalid/notice", "collection_bucket": "candidate_pool",
        "published_at": "2026-08-25T10:00:00+09:00", "deadline_at": None, "budget": "100.00", "estimated_price": None,
        "procurement_class": {"large": "용역", "middle": "SW 및 시스템 개발", "detail": "개발", "code": "01"},
        "region_limit": {"basis": None, "joint_contract_regions": [], "joint_contract_rate": None, "regional_joint_contract_limit": None},
        "lifecycle": {"pre_spec_no": None, "re_notice": None, "changed_at": None, "change_reason": None, "unified_notice_no": "n-1", "previous_failed_notice_no": None},
        "qualification_flags": {}, "attachments": [], "focus_matches": [{"axis": "AI/데이터", "label": "AI", "matched_field": "title", "matched_text": "데이터", "field_kind": "title"}],
        "performance_matches": [], "performance_top_score": None, "candidate_sources": ["focus_title"], "unknown_fields": [],
        "sample_stratum": None, "sample_role": None, "raw_source": "raw/notices.json",
    }


def _fixture(tmp_path: Path, *, notice_id: str = "notice-1"):
    root = tmp_path
    script_source = Path(__file__).resolve().parents[3] / "skills/bidops-screen/scripts/build_screening_results.py"
    script_target = root / "skills/bidops-screen/scripts/build_screening_results.py"
    script_target.parent.mkdir(parents=True)
    shutil.copy2(script_source, script_target)
    (root / "docs/reference").mkdir(parents=True)
    (root / "docs/reference/company-profile.md").write_text("# 회사 프로필\n## 2.1 기술\n확인된 자료\n## 2.2 실적\n자료\n## 2.3 공공\n자료\n## 2.4 수행\n자료\n## 4.1 전략\n자료\n## 5.2 자격\n자료\n", encoding="utf-8")
    run_directory = root / "data/runs/run-1"
    (run_directory / "raw").mkdir(parents=True)
    (run_directory / "raw/notices.json").write_text("{}", encoding="utf-8")
    item = _notice(notice_id)
    (run_directory / "collected-notices.json").write_text(json.dumps({
        "schema_version": "bidops.collected.v2", "generated_at": NOW.isoformat(),
        "source_window": {"from": "2026-08-25", "to": "2026-08-25", "timezone": "Asia/Seoul"},
        "counts": {"total": 1, "candidate_pool": 1, "audit_pool": 0}, "warnings": [], "notices": [item],
    }, ensure_ascii=False), encoding="utf-8")
    (run_directory / "validation-set.json").write_text(json.dumps({
        "schema_version": "bidops.validation-set.v2", "generated_at": NOW.isoformat(),
        "source_window": {"from": "2026-08-25", "to": "2026-08-25", "timezone": "Asia/Seoul"},
        "selection": {"sample_size": 1}, "warnings": [], "notices": [item],
    }, ensure_ascii=False), encoding="utf-8")
    settings = Settings(bidops_root=root, data_dir=root / "data", database_url=f"sqlite:///{root / 'db.sqlite'}")
    engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    body = load_policy_file()
    with factory() as session:
        session.add(Run(id="run-1", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(Notice(run_id="run-1", notice_key=notice_id))
        session.add(ScreeningPolicy(
            policy_version=body["policy_version"], schema_version=body["schema_version"], prompt_version=body["prompt_version"],
            content_digest=policy_content_digest(body), status="activation_candidate", perspective_prompts_json=body["perspective_prompts"],
            counterargument_prompt_json=body["counterargument_prompt"], synthesis_prompt_json=body["synthesis_prompt"],
            candidate_selection_json=body["candidate_selection"], thresholds_json=body["thresholds"], created_at=NOW, created_by="test",
        ))
        session.commit()
    return root, settings, engine, factory, body


def test_single_success_writes_exact_seven_attempts_and_telemetry(tmp_path: Path):
    root, settings, engine, factory, body = _fixture(tmp_path)
    transport = FakeOllamaTransport(_script())
    client = OllamaClient(settings=settings, transport=transport)
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW)
    created = creator.create_execution(run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice")
    worker = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW)
    final = worker.run_once()
    assert final is not None and final.status == "성공"
    with factory() as session:
        attempts = session.scalars(select(ScreeningAttempt)).all()
    assert len(attempts) == 7
    telemetry = (root / created.artifact_dir / "screening-telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    expected = {"schema_version", "execution_id", "trace_id", "span_id", "notice_id", "stage", "attempt_no", "status", "failure_type", "done_reason", "model_name", "model_digest", "prompt_eval_count", "eval_count", "prompt_eval_duration_ns", "eval_duration_ns", "load_duration_ns", "total_duration_ns", "started_at", "finished_at"}
    assert len(telemetry) == 7
    assert all(set(json.loads(line)) == expected for line in telemetry)
    assert [json.loads(line)["stage"] for line in telemetry] == [*NAMES, "counterargument", "synthesis"]
    assert not (root / created.artifact_dir / "screening-results.json").exists()


def test_input_tamper_fails_before_any_generate_call(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    transport = FakeOllamaTransport(_script())
    client = OllamaClient(settings=settings, transport=transport)
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW)
    created = creator.create_execution(run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice")
    input_path = root / created.input_artifact_path
    input_path.write_bytes(input_path.read_bytes().replace(b"notice-1", b"notice-x"))
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패"
    assert transport.generate_requests == []


def test_policy_tamper_fails_before_any_generate_call(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    transport = FakeOllamaTransport(_script())
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    with factory() as session:
        policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == body["policy_version"]))
        assert policy is not None
        policy.content_digest = "f" * 64
        session.commit()
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패"
    assert transport.generate_requests == []


def test_profile_artifact_tamper_fails_before_any_generate_call(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    transport = FakeOllamaTransport(_script())
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    artifact = root / "web/data/profile-snapshots" / f"{created.profile_digest}.md"
    artifact.write_text("tampered profile", encoding="utf-8")
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패"
    assert transport.generate_requests == []


def test_model_digest_tamper_after_enqueue_fails_before_any_generate_call(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    state = {"inspections": 0}

    def changing_tags(_request: dict[str, object]) -> dict[str, object]:
        state["inspections"] += 1
        digest = "a" * 64 if state["inspections"] == 1 else "b" * 64
        return {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": digest}]}

    transport = FakeOllamaTransport(_script(), inspect_response=changing_tags)
    client = OllamaClient(settings=settings, transport=transport)
    ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패"
    assert len(transport.generate_requests) == 0 and state["inspections"] == 2


def test_collected_performance_source_page_integer_is_preserved(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    item = _notice()
    item["performance_matches"] = [{
        "project_name": "공공 데이터 사업", "source_page": 42, "similarity": 0.91,
        "common_fragment": "데이터 구축", "legal_qualification_status": "확인 필요",
    }]
    for filename in ("collected-notices.json", "validation-set.json"):
        path = root / "data/runs/run-1" / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        value["notices"][0] = item
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    client = OllamaClient(settings=settings, transport=FakeOllamaTransport())
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    frozen = json.loads((root / created.input_artifact_path).read_text(encoding="utf-8"))
    assert frozen["notices"][0]["performance_matches"][0]["source_page"] == 42


def test_retry_attempt_is_persisted_before_success_and_has_no_failed_response(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    bad = {"model": "qwen3.8:27b", "done": True, "done_reason": "stop", "response": "{malformed"}
    transport = FakeOllamaTransport([bad, *_script()])
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공"
    with factory() as session:
        attempts = session.scalars(select(ScreeningAttempt).order_by(ScreeningAttempt.attempt_id)).all()
    assert len(attempts) == 8
    assert attempts[0].status == "failure" and attempts[0].response_artifact_path is None
    assert all(item.status == "success" for item in attempts[1:])
    lines = [json.loads(line) for line in (root / created.artifact_dir / "screening-telemetry.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 8 and lines[0]["status"] == "failure"
    response_files = list((root / created.artifact_dir / "responses").rglob("*.json"))
    assert len(response_files) == 7


def test_stop_observed_after_blocking_call_finishes_without_next_model_call(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    store = ScreeningExecutionStore(session_factory=factory, settings=settings)
    execution_ref: dict[str, str] = {}

    def first_response(_request: dict[str, object]) -> dict[str, object]:
        store.request_stop(execution_ref["id"], "tester")
        return _response(_perspective(NAMES[0]))

    transport = FakeOllamaTransport([first_response, *_script()[1:]])
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice"
    )
    execution_ref["id"] = created.execution_id
    worker = ScreeningWorker(settings, session_factory=factory, ollama=client, store=store, clock=lambda: NOW)
    final = worker.run_once()
    assert final is not None and final.status == "중단됨"
    assert len(transport.generate_requests) == 1
    assert (root / created.artifact_dir / "screening-decisions.json").is_file()


def test_full_run_merges_ingests_and_publishes_immutable_derived_directory(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    source_before = (root / "data/runs/run-1/collected-notices.json").read_bytes()
    transport = FakeOllamaTransport(_script())
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공" and final.published_run_id
    derived = next(path for path in (root / "data/runs").iterdir() if path.name.startswith("run-1--screen-"))
    assert derived.name.startswith("run-1--screen-20260826010000-")
    assert (derived / "screening-input.json").read_bytes() == (root / created.input_artifact_path).read_bytes()
    assert (derived / "screening-decisions.json").is_file() and (derived / "screening-results.json").is_file()
    assert (root / "data/runs/run-1/collected-notices.json").read_bytes() == source_before
    with factory() as session:
        run = session.get(Run, final.published_run_id)
        assert run is not None and run.counts_json["notices"] == 1 and run.counts_json["judgments"] == 1


def test_publication_runs_swap_cannot_redirect_current_artifacts_to_external_tree(tmp_path: Path, monkeypatch):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    runs = root / "data/runs"
    external = root / "external-runs"
    external.mkdir()
    real_runs = root / "data/runs-real"
    original_mkdir = os.mkdir
    swapped = {"done": False}

    def race_mkdir(path, mode=0o777, *, dir_fd=None):
        result = original_mkdir(path, mode, dir_fd=dir_fd)
        if not swapped["done"] and dir_fd is not None and isinstance(path, str) and path.startswith(".run-1--screen-"):
            runs.rename(real_runs)
            runs.symlink_to(external, target_is_directory=True)
            swapped["done"] = True
        return result

    monkeypatch.setattr(os, "mkdir", race_mkdir)
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공" and swapped["done"]
    assert not (external / "screening-input.json").exists()
    derived = next(path for path in real_runs.iterdir() if path.name.startswith("run-1--screen-"))
    assert (derived / "screening-input.json").is_file() and (derived / "screening-results.json").is_file()


def test_publish_invalid_clock_opens_no_descriptor_chain(tmp_path: Path):
    _root, settings, _engine, factory, _body = _fixture(tmp_path)
    worker = ScreeningWorker(
        settings,
        session_factory=factory,
        ollama=OllamaClient(settings=settings, transport=FakeOllamaTransport()),
        clock=lambda: datetime(2026, 8, 26, 1, 0),
    )
    before = set(os.listdir("/proc/self/fd"))
    with pytest.raises(WorkerError):
        worker._publish(SimpleNamespace(source_run_id="run-1"), {}, None, "")
    after = set(os.listdir("/proc/self/fd"))
    assert after == before


def test_full_run_uses_collected_candidates_outside_validation_and_ingests_all(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    second = _notice("notice-2")
    collected_path = root / "data/runs/run-1/collected-notices.json"
    collected = json.loads(collected_path.read_text(encoding="utf-8"))
    collected["counts"] = {"total": 2, "candidate_pool": 2, "audit_pool": 0}
    collected["notices"].append(second)
    collected_path.write_text(json.dumps(collected, ensure_ascii=False), encoding="utf-8")
    transport = FakeOllamaTransport([*_script("notice-1"), *_script("notice-2")])
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    frozen = json.loads((root / created.input_artifact_path).read_text(encoding="utf-8"))
    assert frozen["candidate_count"] == 2 and [item["notice_id"] for item in frozen["notices"]] == ["notice-1", "notice-2"]
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공" and final.published_run_id
    with factory() as session:
        run = session.get(Run, final.published_run_id)
        assert run is not None and run.counts_json["notices"] == 2 and run.counts_json["judgments"] == 2
        assert {notice.notice_key for notice in run.notices} == {"notice-1", "notice-2"}


def test_malformed_merge_output_never_publishes_or_changes_source(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    source_before = (root / "data/runs/run-1/collected-notices.json").read_bytes()

    def fake_merge(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        output = Path(argv[argv.index("--output") + 1])
        output.write_bytes(b"{}")
        return SimpleNamespace(returncode=0)

    client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW, popen=fake_merge).run_once()
    assert final is not None and final.status == "실패" and final.published_run_id is None
    assert (root / "data/runs/run-1/collected-notices.json").read_bytes() == source_before
    assert not any(path.name.startswith("run-1--screen-") for path in (root / "data/runs").iterdir())
    assert not (root / created.artifact_dir / "screening-results.json").exists()


def test_merge_rejects_boolean_count_and_invalid_timestamp(tmp_path: Path):
    for field, value in (("candidate_count", True), ("generated_at", "not-aware")):
        root, settings, _engine, factory, body = _fixture(tmp_path / field)

        def tampering_merge(argv: list[str], **kwargs: object) -> SimpleNamespace:
            completed = subprocess.run(argv, **kwargs)
            output = Path(argv[argv.index("--output") + 1])
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact[field] = value
            output.write_bytes(json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            return SimpleNamespace(returncode=completed.returncode)

        client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
        ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
            run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
        )
        final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW, popen=tampering_merge).run_once()
        assert final is not None and final.status == "실패" and final.published_run_id is None


def test_nonzero_merge_does_not_publish(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)

    def failed_merge(_argv: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=7)

    client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW, popen=failed_merge).run_once()
    assert final is not None and final.status == "실패" and final.published_run_id is None


def test_merge_stage_failure_trace_is_rejected_and_never_published(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    second = _notice("notice-2")
    for filename in ("collected-notices.json", "validation-set.json"):
        path = root / "data/runs/run-1" / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        value["counts"] = {"total": 2, "candidate_pool": 2, "audit_pool": 0}
        value["notices"].append(second)
        if filename == "validation-set.json":
            value["selection"]["sample_size"] = 2
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with factory() as session:
        session.add(Notice(run_id="run-1", notice_key="notice-2"))
        session.commit()
    bad = {"model": "qwen3.8:27b", "done": True, "done_reason": "stop", "response": "{invalid"}
    client = OllamaClient(settings=settings, transport=FakeOllamaTransport([bad, bad, *_script("notice-2")]))
    ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )

    def tampering_merge(argv: list[str], **kwargs: object) -> SimpleNamespace:
        completed = subprocess.run(argv, **kwargs)
        failure_path = Path(argv[argv.index("--failures") + 1])
        artifact = json.loads(failure_path.read_text(encoding="utf-8"))
        artifact["failures"][0].update({"failed_stage": "병합·검증", "failure_context": None, "trace_id": "forged", "span_id": "forged"})
        failure_path.write_bytes(json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        return SimpleNamespace(returncode=completed.returncode)

    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW, popen=tampering_merge).run_once()
    assert final is not None and final.status == "실패" and final.published_run_id is None
    assert not any(path.name.startswith("run-1--screen-") for path in (root / "data/runs").iterdir())


def test_publication_finish_uncertain_commit_is_resolved_by_fresh_read(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    store = ScreeningExecutionStore(session_factory=factory, settings=settings)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    original_finish = store.finish
    injected = {"done": False}

    def uncertain(*args: object, **kwargs: object):
        result = original_finish(*args, **kwargs)
        if kwargs.get("published_run_id") is not None and not injected["done"]:
            injected["done"] = True
            raise RuntimeError("connection lost after commit")
        return result

    store.finish = uncertain  # type: ignore[method-assign]
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, store=store, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공" and final.published_run_id
    assert any(path.name.startswith("run-1--screen-") for path in (root / "data/runs").iterdir())


def test_publication_finish_before_commit_rolls_back_derived_run_after_runs_path_swap(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    store = ScreeningExecutionStore(session_factory=factory, settings=settings)
    ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    original_finish = store.finish
    injected = {"done": False}
    runs = root / "data/runs"
    external = root / "external-runs"
    external.mkdir()
    real_runs = root / "data/runs-real"

    def before_commit(*args: object, **kwargs: object):
        if kwargs.get("published_run_id") is not None and not injected["done"]:
            injected["done"] = True
            runs.rename(real_runs)
            runs.symlink_to(external, target_is_directory=True)
            raise RuntimeError("injected transaction failure")
        return original_finish(*args, **kwargs)

    store.finish = before_commit  # type: ignore[method-assign]
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, store=store, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패" and final.published_run_id is None
    assert not any(path.name.startswith("run-1--screen-") for path in real_runs.iterdir())
    assert not any(path.name.startswith("run-1--screen-") for path in external.iterdir())


def test_valid_prior_judgment_is_carried_without_model_calls(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    first_client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    first = ScreeningOrchestrator(settings, session_factory=factory, ollama=first_client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    first_final = ScreeningWorker(settings, session_factory=factory, ollama=first_client, clock=lambda: NOW).run_once()
    assert first_final is not None and first_final.status == "성공"
    source = root / "data/runs/run-3"
    source.mkdir(parents=True)
    shutil.copy2(root / "data/runs/run-1/collected-notices.json", source / "collected-notices.json")
    shutil.copy2(root / "data/runs/run-1/validation-set.json", source / "validation-set.json")
    execution_dir = root / first.artifact_dir
    prior_input = json.loads((execution_dir / "screening-input.json").read_text(encoding="utf-8"))
    prior_input["run_id"] = "run-3"
    prior_input["notices"][0]["judgment_mode"] = "승계"
    prior_input["notices"][0]["carry_over_from"] = "run-1"
    prior_input["notices"].append({**_notice("notice-2"), "judgment_mode": "승계", "carry_over_from": "run-1", "rejudge_reason": None})
    prior_input["candidate_count"] = 2
    prior_decisions = json.loads((execution_dir / "screening-decisions.json").read_text(encoding="utf-8"))
    prior_decisions["run_id"] = "run-3"
    prior_decisions["judgments"][0]["judgment_mode"] = "승계"
    prior_decisions["judgments"][0]["carried_over"] = True
    prior_decisions["judgments"][0]["judged_in_run"] = "run-1"
    prior_decisions["judgments"][0]["recorded_in_run"] = "run-3"
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (source / "screening-input.json").write_bytes(canonical(prior_input))
    (source / "screening-decisions.json").write_bytes(canonical(prior_decisions))
    # Simulate optional artifacts left by an earlier partial replacement.  A
    # zero-call carry must not copy these stale bytes into the new directory.
    (source / "screening-failures.json").write_bytes(canonical({
        "schema_version": "bidops.screening-failures.v1", "execution_id": prior_input["execution_id"],
        "run_id": "run-3", "generated_at": prior_input["generated_at"], "failure_count": 1,
        "failures": [{"notice_id": "notice-2", "failed_stage": "병합·검증", "failure_type": "schema_violation",
                      "last_attempt_at": NOW.isoformat(), "retry_count": 0, "status": "사람 검토 대기",
                      "failure_context": "carried_over_validation", "trace_id": None, "span_id": None,
                      "error_summary": "schema_violation"}],
    }))
    (source / "screening-telemetry.jsonl").write_text("stale telemetry\n", encoding="utf-8")
    with factory() as session:
        session.add(Run(id="run-3", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(Notice(run_id="run-3", notice_key="notice-1"))
        session.commit()
    second_transport = FakeOllamaTransport(digest="b" * 64)
    second_client = OllamaClient(settings=settings, transport=second_transport)
    second = ScreeningOrchestrator(settings, session_factory=factory, ollama=second_client, clock=lambda: NOW).create_execution(
        run_id="run-3", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    frozen = json.loads((root / second.input_artifact_path).read_text(encoding="utf-8"))
    assert frozen["notices"][0]["judgment_mode"] == "승계"
    assert frozen["notices"][0]["carry_over_from"] == "run-1"
    final = ScreeningWorker(settings, session_factory=factory, ollama=second_client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "성공"
    assert second_transport.generate_requests == []
    decisions = json.loads((root / second.artifact_dir / "screening-decisions.json").read_text(encoding="utf-8"))
    assert decisions["model_digest"] == "b" * 64
    assert decisions["judgments"][0]["model_digest"] == "a" * 64
    assert decisions["judgments"][0]["judged_in_run"] == "run-1"
    derived = next(path for path in (root / "data/runs").iterdir() if path.name.startswith("run-3--screen-"))
    assert not (derived / "screening-failures.json").exists()
    assert not (derived / "screening-telemetry.jsonl").exists()


def test_run_until_processes_earlier_fifo_execution_before_target(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    second = _notice("notice-2")
    collected_path = root / "data/runs/run-1/collected-notices.json"
    collected = json.loads(collected_path.read_text(encoding="utf-8"))
    collected["notices"].append(second)
    collected["counts"] = {"total": 2, "candidate_pool": 2, "audit_pool": 0}
    collected_path.write_text(json.dumps(collected, ensure_ascii=False), encoding="utf-8")
    with factory() as session:
        session.add(Notice(run_id="run-1", notice_key="notice-2"))
        session.commit()
    transport = FakeOllamaTransport([*_script("notice-1"), *_script("notice-2")])
    client = OllamaClient(settings=settings, transport=transport)
    creator = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW)
    first = creator.create_execution(run_id="run-1", notice_id="notice-1", policy_version=body["policy_version"], requested_by="tester", scope="single_notice")
    target = creator.create_execution(run_id="run-1", notice_id="notice-2", policy_version=body["policy_version"], requested_by="tester", scope="single_notice")
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_until(target.execution_id)
    assert final.status == "성공"
    with factory() as session:
        earlier = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == first.execution_id))
        assert earlier is not None and earlier.status == "성공"
    assert len(transport.generate_requests) == 14


def test_invalid_carry_is_recorded_as_validation_failure_without_model_calls(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    first_client = OllamaClient(settings=settings, transport=FakeOllamaTransport(_script()))
    first = ScreeningOrchestrator(settings, session_factory=factory, ollama=first_client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    assert ScreeningWorker(settings, session_factory=factory, ollama=first_client, clock=lambda: NOW).run_once().status == "성공"
    source = root / "data/runs/run-3"
    source.mkdir(parents=True)
    for name in ("collected-notices.json", "validation-set.json"):
        shutil.copy2(root / "data/runs/run-1" / name, source / name)
    prior_input = json.loads((root / first.artifact_dir / "screening-input.json").read_text(encoding="utf-8"))
    prior_decisions = json.loads((root / first.artifact_dir / "screening-decisions.json").read_text(encoding="utf-8"))
    prior_input["run_id"] = "run-3"
    prior_input["notices"][0].update({"judgment_mode": "승계", "carry_over_from": "run-1"})
    prior_decisions["run_id"] = "run-3"
    prior_decisions["judgments"][0].update({"judgment_mode": "승계", "carried_over": True, "judged_in_run": "wrong-run", "recorded_in_run": "run-3", "model_name": "attacker-model"})
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (source / "screening-input.json").write_bytes(canonical(prior_input))
    (source / "screening-decisions.json").write_bytes(canonical(prior_decisions))
    with factory() as session:
        session.add(Run(id="run-3", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25), timezone="Asia/Seoul", generated_at=NOW, status="active"))
        session.add(Notice(run_id="run-3", notice_key="notice-1"))
        session.commit()
    transport = FakeOllamaTransport(digest="b" * 64)
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-3", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    assert json.loads((root / created.input_artifact_path).read_text(encoding="utf-8"))["notices"][0]["judgment_mode"] == "승계"
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "실패" and transport.generate_requests == []
    failures = json.loads((root / created.artifact_dir / "screening-failures.json").read_text(encoding="utf-8"))
    assert failures["failures"][0]["failure_context"] == "carried_over_validation"


def test_full_run_continues_after_one_notice_failure_and_publishes_partial(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    second = _notice("notice-2")
    for filename in ("collected-notices.json", "validation-set.json"):
        path = root / "data/runs/run-1" / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        value["counts"] = {"total": 2, "candidate_pool": 2, "audit_pool": 0}
        value["notices"].append(second)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with factory() as session:
        session.add(Notice(run_id="run-1", notice_key="notice-2"))
        session.commit()
    bad = {"model": "qwen3.8:27b", "done": True, "done_reason": "stop", "response": "{invalid"}
    transport = FakeOllamaTransport([bad, bad, *_script("notice-2")])
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="full_run"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "부분 성공" and final.published_run_id
    failures = json.loads((root / created.artifact_dir / "screening-failures.json").read_text(encoding="utf-8"))
    assert failures["failure_count"] == 1 and failures["failures"][0]["notice_id"] == "notice-1"
    assert len(transport.generate_requests) == 9


def test_quality_sample_mixed_results_is_partial_without_publication(tmp_path: Path):
    root, settings, _engine, factory, body = _fixture(tmp_path)
    second = _notice("notice-2")
    for filename in ("collected-notices.json", "validation-set.json"):
        path = root / "data/runs/run-1" / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        value["counts"] = {"total": 2, "candidate_pool": 2, "audit_pool": 0}
        value["notices"].append(second)
        if filename == "validation-set.json":
            value["selection"]["sample_size"] = 2
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    bad = {"model": "qwen3.8:27b", "done": True, "done_reason": "stop", "response": "{invalid"}
    transport = FakeOllamaTransport([bad, bad, *_script("notice-2")])
    client = OllamaClient(settings=settings, transport=transport)
    created = ScreeningOrchestrator(settings, session_factory=factory, ollama=client, clock=lambda: NOW).create_execution(
        run_id="run-1", policy_version=body["policy_version"], requested_by="tester", scope="quality_sample"
    )
    final = ScreeningWorker(settings, session_factory=factory, ollama=client, clock=lambda: NOW).run_once()
    assert final is not None and final.status == "부분 성공" and final.published_run_id is None
    assert not (root / created.artifact_dir / "screening-results.json").exists()
