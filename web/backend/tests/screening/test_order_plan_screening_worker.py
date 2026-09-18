from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

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
    binding = json.loads((REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v2.json").read_text())
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
