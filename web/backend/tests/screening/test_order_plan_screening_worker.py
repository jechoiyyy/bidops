from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import _json_serializer, schema_bound
from app.core.models import AuditEvent
from app.lifecycle.models import Run
from app.screening.models import (
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
)
from app.screening.services.vllm_client import OrderPlanVllmError, OrderPlanVllmResponse
from app.screening.workers.order_plan import C2ScreeningWorker, C2WorkerError
from tests.screening.test_order_plan_screening_service import REPO_ROOT, _fixture, _create
from tests.postgres import requires_postgres, temporary_database


class MemoryResponseStore:
    def __init__(self) -> None:
        self.values: list[bytes] = []

    def put_encrypted(self, data: bytes, **_: object) -> dict[str, object]:
        self.values.append(data)
        return {"object_version_id": f"v-{len(self.values)}", "etag": "etag", "plaintext_sha256": "raw-digest"}


class FakeAdapter:
    def __init__(self, fail_sequence: int | None = None) -> None:
        self.calls: list[list[int]] = []
        self.fail_sequences = ({fail_sequence, fail_sequence + 1} if fail_sequence is not None else set())

    def invoke(self, *, prompt: str, payload: dict[str, object], expected_model: str) -> OrderPlanVllmResponse:
        del prompt, expected_model
        # The model only ever sees the approved payload: a batch-local item_id
        # and a title, plus the approved company capabilities projection.
        assert set(payload) == {"company_capabilities", "items"}
        assert set(payload["company_capabilities"]) == {"profile_version", "capabilities"}  # type: ignore[index]
        assert all(set(row) == {"item_id", "title"} for row in payload["items"])  # type: ignore[union-attr]
        ids = [int(row["item_id"]) for row in payload["items"]]  # type: ignore[index]
        self.calls.append(ids)
        if len(self.calls) in self.fail_sequences:
            raise OrderPlanVllmError("schema_violation", "response_json_invalid")
        return OrderPlanVllmResponse(
            structured_output={"items": [{"item_id": item_id, "relevance": "relevant", "score": .9, "reason": "관련"} for item_id in ids]},
            approved_raw_response=b'{"approved":true}',
            input_tokens=10,
            cached_input_tokens=None,
            output_tokens=20,
            total_tokens=30,
            duration_ms=4,
        )


class CrashAfterFirstAdapter(FakeAdapter):
    def invoke(self, *, prompt: str, payload: dict[str, object], expected_model: str) -> OrderPlanVllmResponse:
        if self.calls:
            raise KeyboardInterrupt
        return super().invoke(prompt=prompt, payload=payload, expected_model=expected_model)


def test_worker_batches_top300_in_contiguous_groups_and_publishes(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=51)
    service_response, _ = _create(__import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings), session, policy_version)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "성공"
    assert [len(batch) for batch in adapter.calls] == [25, 25, 1]
    execution = session.get(OrderPlanScreeningExecution, UUID(str(service_response["execution_id"])))
    assert execution is not None and execution.status == "성공" and execution.completed_count == 51
    assert execution.heartbeat_at is not None
    assert session.scalar(select(OrderPlanScreeningResult).where(OrderPlanScreeningResult.execution_id == execution.execution_id)) is not None
    assert session.scalar(select(OrderPlanScreeningArtifact).where(OrderPlanScreeningArtifact.execution_id == execution.execution_id, OrderPlanScreeningArtifact.kind == "result")) is not None
    assert session.scalar(select(OrderPlanScreeningBatchAttempt).where(OrderPlanScreeningBatchAttempt.execution_id == execution.execution_id, OrderPlanScreeningBatchAttempt.attempt_no == 1)) is not None


def test_worker_retries_once_then_records_partial_batch_failure(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=51)
    service_response, _ = _create(__import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings), session, policy_version)
    adapter = FakeAdapter(fail_sequence=2)
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "부분 성공"
    assert len(adapter.calls) == 4
    execution = session.get(OrderPlanScreeningExecution, UUID(str(service_response["execution_id"])))
    assert execution is not None and execution.status == "부분 성공" and execution.failure_count == 25
    assert session.scalar(select(OrderPlanScreeningBatchAttempt).where(OrderPlanScreeningBatchAttempt.execution_id == execution.execution_id, OrderPlanScreeningBatchAttempt.attempt_no == 2)) is not None


def test_worker_recovers_stale_execution_with_a_legal_transition(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    service_response, _ = _create(
        __import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings),
        session,
        policy_version,
    )
    execution_id = UUID(str(service_response["execution_id"]))
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    now = datetime(2026, 9, 2, tzinfo=UTC)
    execution.status = "실행 중"
    execution.active_slot = 1
    execution.started_at = now - timedelta(hours=1)
    execution.heartbeat_at = now - timedelta(hours=1)
    session.commit()

    worker = C2ScreeningWorker(settings=settings, clock=lambda: now)
    assert worker.run_once(session) is None

    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    assert execution.status == "중단됨"
    assert execution.active_slot is None
    assert execution.error_code == "stale_execution"
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.execution_stale_recovered")) is not None


def test_worker_keeps_an_execution_with_a_recent_heartbeat(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    service_response, _ = _create(
        __import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings),
        session,
        policy_version,
    )
    execution_id = UUID(str(service_response["execution_id"]))
    now = datetime(2026, 9, 2, tzinfo=UTC)
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    execution.status = "실행 중"
    execution.active_slot = 1
    execution.started_at = now - timedelta(hours=1)
    execution.heartbeat_at = now - timedelta(seconds=1)
    session.commit()

    worker = C2ScreeningWorker(settings=settings, clock=lambda: now)
    assert worker.run_once(session) is None

    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    assert execution.status == "실행 중"
    assert execution.active_slot == 1
    assert execution.heartbeat_at == now - timedelta(seconds=1)


def test_worker_rechecks_live_execution_switch_before_model_invocation(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=51)
    service_response, _ = _create(
        __import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings),
        session,
        policy_version,
    )
    settings.c2_execution_allowed = False
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())

    result = worker.run_once(session)

    assert result and result["status"] == "실패"
    assert adapter.calls == []
    execution = session.get(OrderPlanScreeningExecution, UUID(str(service_response["execution_id"])))
    assert execution is not None and execution.status == "실패"


def test_stale_recovery_materializes_completed_prefix_and_interrupted_failure(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=51)
    service_response, _ = _create(
        __import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings),
        session,
        policy_version,
    )
    execution_id = UUID(str(service_response["execution_id"]))
    now = datetime(2026, 9, 2, tzinfo=UTC)
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    execution.status = "실행 중"
    execution.active_slot = 1
    execution.started_at = now
    execution.heartbeat_at = now
    session.commit()

    crashed_worker = C2ScreeningWorker(
        settings=settings,
        adapter=CrashAfterFirstAdapter(),
        raw_response_store=MemoryResponseStore(),
        clock=lambda: now,
    )
    with pytest.raises(KeyboardInterrupt):
        crashed_worker._run_execution(session, execution)

    recovery_now = now + timedelta(seconds=settings.c2_worker_stale_seconds + 1)
    recovery_worker = C2ScreeningWorker(settings=settings, clock=lambda: recovery_now)
    assert recovery_worker.run_once(session) is None

    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None and execution.status == "중단됨"
    attempts = session.scalars(
        select(OrderPlanScreeningBatchAttempt).where(OrderPlanScreeningBatchAttempt.execution_id == execution_id).order_by(OrderPlanScreeningBatchAttempt.sequence)
    ).all()
    assert attempts[-1].attempt_status == "failed"
    assert attempts[-1].failure_code == "stale_execution"
    decisions_path = next((settings.bidops_root / "data" / "runs").glob("run-c2--c2-*/screening-decisions.json"))
    failures_path = decisions_path.with_name("screening-failures.json")
    decisions = json.loads(decisions_path.read_text())
    failures = json.loads(failures_path.read_text())
    assert decisions["success_count"] == 25
    assert decisions["batch_count"] == 2
    assert failures["failure_count"] == 1
    assert failures["failures"][0]["error_code"] == "stale_execution"


def test_stop_leaves_unprocessed_batches_not_attempted(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=51)
    service_response, _ = _create(
        __import__("app.screening.services.order_plan_screening", fromlist=["OrderPlanScreeningService"]).OrderPlanScreeningService(settings),
        session,
        policy_version,
    )
    execution_id = UUID(str(service_response["execution_id"]))
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    now = datetime(2026, 9, 2, tzinfo=UTC)
    execution.status = "중지 요청"
    execution.active_slot = 1
    execution.started_at = now
    execution.heartbeat_at = now
    session.commit()

    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore(), clock=lambda: now)
    result = worker._run_execution(session, execution)

    assert result["status"] == "중단됨"
    assert adapter.calls == []
    attempts = session.scalars(
        select(OrderPlanScreeningBatchAttempt).where(OrderPlanScreeningBatchAttempt.execution_id == execution_id)
    ).all()
    assert attempts == []
    results = session.scalars(
        select(OrderPlanScreeningResult).where(OrderPlanScreeningResult.execution_id == execution_id)
    ).all()
    assert len(results) == 51
    assert all(result.stage2_status == "not_attempted" for result in results)


# `BIDOPS_C2_QUEUED_MAX_DWELL_SECONDS` 기본값. 값을 박아 두어 옛 코드에서도 같은 시각으로 돈다.
QUEUED_MAX_DWELL_SECONDS = 14400


def _service(settings):
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    return OrderPlanScreeningService(settings)


def test_worker_closes_a_stale_queued_execution_instead_of_running_it(tmp_path: Path) -> None:
    """A-1: 워커가 오래 비어 있다 돌아오면 체류 한도를 넘긴 `대기`는 실행하지 않고 닫는다."""

    settings, session, policy_version, _, _ = _fixture(tmp_path, count=2)
    response, _ = _create(_service(settings), session, policy_version)
    execution_id = UUID(str(response["execution_id"]))
    queued = session.get(OrderPlanScreeningExecution, execution_id)
    assert queued is not None
    later = queued.queued_at + timedelta(seconds=QUEUED_MAX_DWELL_SECONDS + 1)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(
        settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore(), clock=lambda: later
    )

    assert worker.run_once(session) is None

    assert adapter.calls == []
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    assert (execution.status, execution.error_code, execution.active_slot) == ("중단됨", "stale_queued", None)
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.execution_stale_queued_closed"))
    assert event is not None and event.aggregate_id == str(execution_id)
    assert event.actor_kind == "system" and event.claimed_name == settings.worker_id
    assert event.safe_metadata["reclaimed_by"] == "worker_claim"


def test_worker_still_runs_a_queued_execution_inside_the_dwell_limit(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=2)
    response, _ = _create(_service(settings), session, policy_version)
    execution_id = UUID(str(response["execution_id"]))
    queued = session.get(OrderPlanScreeningExecution, execution_id)
    assert queued is not None
    later = queued.queued_at + timedelta(seconds=QUEUED_MAX_DWELL_SECONDS - 1)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(
        settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore(), clock=lambda: later
    )

    result = worker.run_once(session)

    assert result and result["status"] == "성공"
    assert adapter.calls != []


def test_worker_closes_the_stale_running_one_first_then_the_queue_behind_it(tmp_path: Path) -> None:
    """멈춘 `실행 중`을 stale 회수로 닫은 뒤에는 진행 중인 실행이 없으므로 오래된 `대기`도 닫힌다.
    한도 안의 `대기`는 그대로 claim된다."""

    settings, session, policy_version, _, _ = _fixture(tmp_path, count=2)
    service = _service(settings)
    first, _ = _create(service, session, policy_version)
    old, _ = _create(service, session, policy_version)
    running = session.get(OrderPlanScreeningExecution, UUID(str(first["execution_id"])))
    old_queued = session.get(OrderPlanScreeningExecution, UUID(str(old["execution_id"])))
    assert running is not None and old_queued is not None
    later = old_queued.queued_at + timedelta(seconds=QUEUED_MAX_DWELL_SECONDS + 1)
    running.status = "실행 중"
    running.active_slot = 1
    running.started_at = later - timedelta(hours=2)
    running.heartbeat_at = later - timedelta(seconds=settings.c2_worker_stale_seconds + 1)
    session.commit()
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(
        settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore(), clock=lambda: later
    )

    assert worker.run_once(session) is None

    session.expire_all()
    assert (running.status, running.error_code) == ("중단됨", "stale_execution")
    assert (old_queued.status, old_queued.error_code) == ("중단됨", "stale_queued")
    assert adapter.calls == []


def test_worker_keeps_the_queue_while_a_running_execution_heartbeats(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, count=2)
    service = _service(settings)
    first, _ = _create(service, session, policy_version)
    second, _ = _create(service, session, policy_version)
    running = session.get(OrderPlanScreeningExecution, UUID(str(first["execution_id"])))
    waiting = session.get(OrderPlanScreeningExecution, UUID(str(second["execution_id"])))
    assert running is not None and waiting is not None
    later = waiting.queued_at + timedelta(seconds=QUEUED_MAX_DWELL_SECONDS + 1)
    running.status = "실행 중"
    running.active_slot = 1
    running.started_at = later - timedelta(hours=5)
    running.heartbeat_at = later - timedelta(seconds=5)
    session.commit()

    worker = C2ScreeningWorker(settings=settings, clock=lambda: later)
    assert worker.run_once(session) is None

    session.expire_all()
    assert running.status == "실행 중"
    assert (waiting.status, waiting.error_code) == ("대기", None)


@requires_postgres
def test_postgres_heartbeat_guard_allows_active_and_rejects_terminal() -> None:
    with temporary_database() as database_url:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        engine = schema_bound(create_engine(database_url, json_serializer=_json_serializer, future=True))
        now = datetime(2026, 9, 2, tzinfo=UTC)
        with Session(engine) as session:
            session.add(Run(id="run-heartbeat", timezone="Asia/Seoul", generated_at=now))
            session.add(OrderPlanScreeningPolicy(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                policy_version="policy-heartbeat",
                schema_version="bidops.order-plan-screening-policy.v1",
                producer="phase0-contracts",
                consumer="phase1-screening-pipeline",
                policy_status="active",
                decision_scope="c2_order_plan_first_pass",
                policy_payload_jsonb={},
                binding_payload_jsonb={},
                policy_sha256="a" * 64,
                binding_sha256="b" * 64,
                activation_metadata_jsonb={},
                quality_gate_status="not_measured",
                active_slot=1,
                created_by="test",
                created_at=now,
                activated_by="test",
                activated_at=now,
            ))
            session.commit()
            execution = OrderPlanScreeningExecution(
                execution_id=UUID("00000000-0000-0000-0000-000000000002"),
                request_id=UUID("00000000-0000-0000-0000-000000000003"),
                schema_version="bidops.order-plan-screening-execution-row.v1",
                producer="screening-api",
                consumer="screening-worker-and-review-api",
                source_run_id="run-heartbeat",
                source_artifact_name="collected-order-plans.json",
                source_artifact_schema_version="bidops.collected-order-plans.v1",
                source_artifact_sha256="c" * 64,
                input_artifact_sha256="d" * 64,
                population_count=1,
                population_sha256="e" * 64,
                policy_version="policy-heartbeat",
                policy_sha256="a" * 64,
                binding_sha256="b" * 64,
                stage1_binding_version="bm25",
                stage1_binding_sha256="f" * 64,
                stage2_binding_version="qwen",
                stage2_binding_sha256="0" * 64,
                status="대기",
                active_slot=None,
                requested_by="test",
                partial_artifact=False,
                queued_at=now,
                started_at=None,
                heartbeat_at=None,
                finished_at=None,
                created_at=now,
            )
            session.add(execution)
            session.commit()
            execution.status = "실행 중"
            execution.active_slot = 1
            execution.started_at = now
            execution.heartbeat_at = now
            session.commit()
            execution.heartbeat_at = now.replace(second=1)
            session.commit()
            execution.status = "성공"
            execution.active_slot = None
            execution.finished_at = now.replace(second=2)
            session.commit()
            execution.heartbeat_at = now.replace(second=3)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        engine.dispose()


def test_output_items_maps_batch_local_ids_back_onto_plans() -> None:
    """The model answers with item_id; the plan identity is restored by position."""

    expected = ["R26DD001", "R26DD002", "R26DD003"]
    shuffled = {"items": [
        {"item_id": 2, "relevance": "uncertain", "score": .5, "reason": "모호"},
        {"item_id": 0, "relevance": "relevant", "score": .9, "reason": "관련"},
        {"item_id": 1, "relevance": "not_relevant", "score": .1, "reason": "무관"},
    ]}
    rows = C2ScreeningWorker._output_items(shuffled, expected)
    assert [row["plan_id"] for row in rows] == expected
    assert [row["relevance"] for row in rows] == ["relevant", "not_relevant", "uncertain"]


@pytest.mark.parametrize(
    "items,code",
    [
        ([{"item_id": 0, "relevance": "relevant", "score": .9, "reason": "관련"}] * 2, "id_mismatch"),
        ([{"item_id": 0, "relevance": "relevant", "score": .9, "reason": "관련"},
          {"item_id": 5, "relevance": "relevant", "score": .9, "reason": "관련"}], "id_mismatch"),
        ([{"item_id": 0, "relevance": "relevant", "score": .9, "reason": "관련"},
          {"plan_id": "R26DD002", "relevance": "relevant", "score": .9, "reason": "관련"}], "schema_violation"),
    ],
)
def test_output_items_rejects_duplicate_out_of_range_and_legacy_plan_id(items, code) -> None:
    with pytest.raises(C2WorkerError) as error:
        C2ScreeningWorker._output_items({"items": items}, ["R26DD001", "R26DD002"])
    assert error.value.code == code


def test_new_attempt_records_the_generation_identity_it_ran_with(tmp_path: Path) -> None:
    """A recorded generation_config_sha256 must come from the loaded binding."""

    settings, session, policy_version, _, _ = _fixture(tmp_path, count=3)
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    _create(OrderPlanScreeningService(settings), session, policy_version)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    assert worker.run_once(session)
    attempt = session.scalar(select(OrderPlanScreeningBatchAttempt))
    # The fixture re-pins the prompt digests, so read the binding it froze.
    binding = json.loads(Path(str(settings.c2_binding_path)).read_text())
    stage2 = binding["stage2_binding"]
    assert attempt is not None
    assert attempt.generation_config_sha256 == stage2["generation_config_sha256"]
    assert attempt.model_digest == stage2["model_digest"]
    assert attempt.prompt_sha256 == stage2["prompt_sha256"]
    assert attempt.company_profile_sha256 == stage2["company_profile_sha256"]


def test_worker_accepts_a_candidate_file_status_frozen_under_an_active_row(tmp_path: Path) -> None:
    """The file policy_status is a snapshot; the worker only checks file ↔ binding agreement."""

    settings, session, policy_version, _, _ = _fixture(tmp_path, count=3, file_policy_status="activation_candidate")
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    response, _ = _create(OrderPlanScreeningService(settings), session, policy_version)
    worker = C2ScreeningWorker(settings=settings, adapter=FakeAdapter(), raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "성공"
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.status == "성공" and execution.error_code is None


# --- Mac LiteLLM/Ollama artifact set (ADR-0072) --------------------------------


def test_worker_runs_the_published_ollama_binding_end_to_end(tmp_path: Path) -> None:
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    settings, session, policy_version, _, _ = _fixture(
        tmp_path, count=3, artifacts="v5",
        # As published: the file snapshot says candidate while the DB row is
        # active (ADR-0060), which BM25's Ollama guard has to accept.
        file_policy_status="activation_candidate",
    )
    assert policy_version == "c2-order-plan-screening-v5"
    response, _ = _create(OrderPlanScreeningService(settings), session, policy_version)
    worker = C2ScreeningWorker(settings=settings, adapter=FakeAdapter(), raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "성공"
    attempt = session.scalar(select(OrderPlanScreeningBatchAttempt))
    assert attempt is not None
    assert attempt.model_name == "qwen3.8:27b"
    assert attempt.model_digest == "41a558fc459a96edbf0500938edc7d3ddaceedde727d1e7faa8ec4fbc9eb8772"
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.status == "성공" and execution.completed_count == 3


@pytest.mark.parametrize(
    "edit",
    [
        # The Ollama build may not borrow the measured vLLM provider label.
        lambda policy, binding: (
            policy["stage2"].update(provider="approved_private_vllm"),
            binding["stage2_binding"].update(provider="approved_private_vllm"),
        ),
        # Policy and binding must name the same provider.
        lambda policy, binding: policy["stage2"].update(provider="approved_private_vllm"),
    ],
)
def test_worker_rejects_a_provider_that_does_not_match_the_model(tmp_path: Path, edit) -> None:
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    settings, session, policy_version, _, _ = _fixture(tmp_path, count=3, artifacts="v5", file_policy_status="activation_candidate", edit=edit)
    response, _ = _create(OrderPlanScreeningService(settings), session, policy_version)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    worker.run_once(session)
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.status == "실패"
    assert execution.error_code == "binding_mismatch"
    assert adapter.calls == []


# --- Policy-driven stage 1 cut (ADR-0075) ------------------------------------


class AlwaysFailingAdapter(FakeAdapter):
    """Model outage: every attempt of every batch fails with a retryable error."""

    def invoke(self, *, prompt: str, payload: dict[str, object], expected_model: str) -> OrderPlanVllmResponse:
        self.calls.append([int(row["item_id"]) for row in payload["items"]])  # type: ignore[index]
        raise OrderPlanVllmError("timeout", "model_timeout")


def _service(settings):
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    return OrderPlanScreeningService(settings)


@pytest.mark.parametrize(("artifacts", "top_k"), [("v5", 300), ("v6", 150)])
def test_worker_judges_exactly_the_policy_top_k(tmp_path: Path, artifacts: str, top_k: int) -> None:
    settings, session, policy_version, _, _ = _fixture(
        tmp_path, count=400, artifacts=artifacts, file_policy_status="activation_candidate",
    )
    assert policy_version == f"c2-order-plan-screening-{artifacts}"
    response, _ = _create(_service(settings), session, policy_version)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "성공"
    assert [len(batch) for batch in adapter.calls] == [25] * (top_k // 25)
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None
    assert (execution.stage1_selected_count, execution.stage1_filtered_out_count) == (top_k, 400 - top_k)
    rows = {row.stage1_rank: row for row in session.scalars(
        select(OrderPlanScreeningResult).where(OrderPlanScreeningResult.execution_id == execution.execution_id)
    )}
    assert len(rows) == 400
    assert (rows[top_k].stage1_status, rows[top_k].stage2_status) == ("selected", "success")
    assert (rows[top_k + 1].stage1_status, rows[top_k + 1].stage2_status) == ("filtered_out", "not_attempted")


def test_worker_rejects_an_unapproved_top_k_before_any_model_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.screening.services import order_plan_screening

    def top_k_200(policy: dict, binding: dict) -> None:
        policy["stage1"]["top_k"] = 200
        binding["stage1_binding"]["top_k"] = 200

    settings, session, policy_version, _, _ = _fixture(
        tmp_path, count=3, artifacts="v6", file_policy_status="activation_candidate", edit=top_k_200,
    )
    # The service already refuses this row; let it through once so the worker's own check is what runs.
    monkeypatch.setattr(order_plan_screening, "ALLOWED_STAGE1_TOP_K", frozenset({150, 200, 300}))
    response, _ = _create(_service(settings), session, policy_version)
    monkeypatch.undo()
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    worker.run_once(session)
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and (execution.status, execution.error_code) == ("실패", "binding_mismatch")
    assert adapter.calls == []
    assert session.scalar(select(OrderPlanScreeningResult)) is None


def test_a_fully_failed_execution_publishes_ranked_rows_and_ends_failed(tmp_path: Path) -> None:
    """Model outage day: the merge publishes the whole ranked population and the execution ends ``실패``."""

    settings, session, policy_version, _, plans = _fixture(
        tmp_path, count=160, artifacts="v6", file_policy_status="activation_candidate",
    )
    response, _ = _create(_service(settings), session, policy_version)
    adapter = AlwaysFailingAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    result = worker.run_once(session)
    assert result and result["status"] == "실패"
    assert len(adapter.calls) == 6 * 2  # six batches, two attempts each
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None
    assert (execution.status, execution.error_code, execution.partial_artifact) == ("실패", "result_failed", True)
    assert (execution.stage1_selected_count, execution.stage2_failed_count, execution.completed_count) == (150, 150, 0)
    rows = session.scalars(
        select(OrderPlanScreeningResult).where(OrderPlanScreeningResult.execution_id == execution.execution_id)
    ).all()
    assert len(rows) == 160
    assert all(row.stage1_rank is not None and row.stage1_score is not None for row in rows)
    assert {(row.stage1_status, row.stage2_status) for row in rows} == {("selected", "failed"), ("filtered_out", "not_attempted")}
    # The cumulative list shows that day's plans (ADR-0075) — ranked, without a judgment.
    listing = _service(settings).list_order_plans(session, limit=500)
    assert {item["execution_id"] for item in listing["items"]} == {execution.execution_id}
    assert all(item["qwen_relevance"] is None and item["stage1_rank"] is not None for item in listing["items"])
    assert listing["scope"]["policy_versions"] == []


def test_v6_candidate_is_loaded_measured_and_activated_while_v5_keeps_running(tmp_path: Path) -> None:
    """The operator sequence with v5 active: no path change and no restart between steps.

    load → candidate → gate measurement (v5 daily keeps working) → activate (v5 retired) →
    daily switch on v6.  The settings object is never touched after the fixture.
    """

    from decimal import Decimal

    from app.screening.c2_policy import load_policy
    from app.screening.models import (
        OrderPlanScreeningDailyTrigger,
        OrderPlanScreeningQualityEvaluation,
        OrderPlanScreeningQualityGate,
    )
    from app.screening.schemas.order_plan_daily_trigger import DailyTriggerSetRequest
    from app.screening.schemas.order_plan_policies import PolicyActivateRequest, PolicyCandidateRequest
    from app.screening.services.order_plan_daily_trigger import OrderPlanDailyTriggerService, effective_state
    from app.screening.services.order_plan_policy import OrderPlanPolicyService
    from tests.screening.test_order_plan_screening_service import _canonical, _sha

    settings, session, v5, _, _ = _fixture(tmp_path, count=160, artifacts="v5", file_policy_status="activation_candidate")
    settings.c2_daily_trigger_enabled = True
    v5_row = session.scalar(select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == v5))
    assert v5_row is not None
    session.add(OrderPlanScreeningDailyTrigger(
        id=uuid4(), policy_version=v5, policy_sha256=v5_row.policy_sha256, enabled=True, reason=None,
        set_by="operator", set_at=datetime(2026, 9, 2, tzinfo=UTC), request_id=uuid4(),
    ))
    session.commit()

    # Publish v6 next to the configured (v5) files, as the compose mounts do.
    config_dir = Path(str(settings.c2_policy_path)).parent
    policy = json.loads(Path(str(settings.c2_policy_path)).read_bytes())
    binding = json.loads(Path(str(settings.c2_binding_path)).read_bytes())
    policy.update(policy_version="c2-order-plan-screening-v6")
    policy["stage1"]["top_k"] = 150
    policy_bytes = _canonical(policy)
    binding["binding_version"] = "c2-order-plan-screening-binding-v6"
    binding["policy"].update(policy_version="c2-order-plan-screening-v6", sha256=_sha(policy_bytes))
    binding["stage1_binding"]["top_k"] = 150
    (config_dir / "order-plan-screening-policy.v6.json").write_bytes(policy_bytes)
    (config_dir / "order-plan-screening-phase0-binding.v6.json").write_bytes(_canonical(binding))
    configured = (settings.c2_policy_path, settings.c2_binding_path)

    # 1. load (CLI service) → draft row.
    v6_row = load_policy(
        session,
        policy_path=config_dir / "order-plan-screening-policy.v6.json",
        binding_path=config_dir / "order-plan-screening-phase0-binding.v6.json",
        created_by="operator",
    ).row
    session.commit()
    v6 = v6_row.policy_version
    policies = OrderPlanPolicyService(settings)
    # 2. candidate.
    policies.set_candidate(session, PolicyCandidateRequest(
        schema_version="policy-candidate-request.v1", producer="human-review-client", consumer="policy-api",
        request_id=uuid4(), policy_version=v6, base_policy_sha256=v5_row.policy_sha256,
        candidate_sha256=v6_row.policy_sha256, reason="Top150",
    ), "operator")
    inspected = policies.inspect_policy(session, v6)
    assert (inspected["policy_file_present"], inspected["binding_file_present"]) == (True, True)
    assert "policy_file_missing" not in {blocker["code"] for blocker in inspected["blockers"]}
    assert effective_state(session, settings).effective_enabled is True

    # 3. gate measurement of the v6 candidate, then a v5 daily run, with no restart in between.
    gate = OrderPlanScreeningQualityGate(
        gate_id="c2gate-" + "6" * 32, policy_version=v6, policy_sha256=v6_row.policy_sha256,
        binding_sha256=v6_row.binding_sha256, gold_manifest_sha256="1" * 64, gold_artifact_sha256="2" * 64,
        gold_status="queue_human_adjudicated", scoring_input_sha256="3" * 64, evaluation_basis="product_rerun",
        scoring_unit="per_published_day", measurement_run_ids_json=["run-c2"], required_pass_count=2,
        threshold_recall_pct=Decimal("90"), threshold_precision_pct=Decimal("35"),
        threshold_important_missed_max=3, threshold_review_load_max=80,
        created_by="gate-owner", created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    session.add(gate)
    session.commit()
    service = _service(settings)
    adapter = FakeAdapter()
    worker = C2ScreeningWorker(settings=settings, adapter=adapter, raw_response_store=MemoryResponseStore())
    measured, _ = _create(service, session, v6, "gate_measurement")
    assert worker.run_once(session)["status"] == "성공"  # type: ignore[index]
    measured_row = session.get(OrderPlanScreeningExecution, UUID(str(measured["execution_id"])))
    assert measured_row is not None and measured_row.purpose == "gate_measurement"
    assert (measured_row.policy_version, measured_row.stage1_selected_count, measured_row.stage1_filtered_out_count) == (v6, 150, 10)
    daily, _ = _create(service, session, v5, "daily_script")
    assert worker.run_once(session)["status"] == "성공"  # type: ignore[index]
    daily_row = session.get(OrderPlanScreeningExecution, UUID(str(daily["execution_id"])))
    assert daily_row is not None and (daily_row.policy_version, daily_row.stage1_selected_count) == (v5, 160)
    assert [len(batch) for batch in adapter.calls] == [25] * 6 + [25] * 6 + [10]

    # 4. activation (the evaluation is recorded by a person outside this test) retires v5.
    evaluation = OrderPlanScreeningQualityEvaluation(
        evaluation_id="c2gateeval-" + "6" * 32, gate_id=gate.gate_id, revision=1, result_status="통과",
        pass_execution_ids_json={"pass_1": [str(measured_row.execution_id)], "pass_2": []}, metrics_json={},
        reasons_json=[], artifact_sha256="4" * 64, evaluated_by="gate-owner",
        evaluated_at=datetime(2026, 9, 2, 1, tzinfo=UTC),
    )
    session.add(evaluation)
    session.commit()
    policies.activate(session, v6, PolicyActivateRequest(
        schema_version="policy-activate-request.v1", producer="human-review-client", consumer="policy-api",
        request_id=uuid4(), policy_sha256=v6_row.policy_sha256, quality_gate_artifact_sha256="4" * 64,
        explicit_confirmation=True,
    ), "operator")
    session.refresh(v5_row)
    assert v5_row.policy_status == "retired"
    assert effective_state(session, settings).reasons == ("switch_bound_to_other_version",)

    # 5. daily switch on v6, then the next daily run uses v6.
    OrderPlanDailyTriggerService(settings).set_switch(session, DailyTriggerSetRequest(
        schema_version="daily-trigger-set-request.v1", producer="human-review-client", consumer="daily-trigger-api",
        request_id=uuid4(), policy_version=v6, enabled=True, explicit_confirmation=True,
    ), "operator")
    assert effective_state(session, settings).effective_enabled is True
    next_daily, _ = _create(service, session, v6, "daily_script")
    assert worker.run_once(session)["status"] == "성공"  # type: ignore[index]
    next_row = session.get(OrderPlanScreeningExecution, UUID(str(next_daily["execution_id"])))
    assert next_row is not None and (next_row.policy_version, next_row.purpose, next_row.stage1_selected_count) == (v6, "operational", 150)
    assert (settings.c2_policy_path, settings.c2_binding_path) == configured
