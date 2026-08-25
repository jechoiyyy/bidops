from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.models import Notice, Run, ScreeningAttempt, ScreeningExecution, ScreeningPolicy
from app.screening.execution_store import ScreeningExecutionStore
from app.screening.ollama import OllamaClient
from app.screening.orchestrator import ScreeningOrchestrator
from app.screening.policy import load_policy_file, policy_content_digest
from app.screening.worker import ScreeningWorker
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
