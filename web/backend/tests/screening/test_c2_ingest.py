"""C-2 전용 회차 디렉터리 적재 (명세 §6.2).

lifecycle `ingest_run`은 이 디렉터리를 알아보지 못한다. screening이 등록한 회차
적재 hook이 "이건 내 전용 결과이며 source run은 X"라고 주장했을 때만 적재되며,
불변 계약 위반은 어떤 행도 남기지 않고 거절된다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lifecycle import ingest_run
from app.models import (
    OrderPlan,
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningResult,
    Run,
)
from app.screening.ingest import (
    OrderPlanScreeningConflictError,
    OrderPlanScreeningContractError,
)
from tests.c2_fixtures import write_c2_fixture as _write_c2_fixture, write_c2_json as _write_c2_json
from tests.postgres import migrated_engine, requires_postgres


@pytest.fixture(autouse=True)
def _screening_registered(screening_extensions):
    """C-2 디렉터리 인식은 screening hook이 등록돼 있을 때만 일어난다."""


@requires_postgres
def test_c2_loader_is_full_population_idempotent_and_rolls_back_hash_conflicts(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_c2_fixture(tmp_path)
        session.add(
            Run(
                id=source_run_id,
                timezone="Asia/Seoul",
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        first = ingest_run(run_dir, session)
        assert first.screening_executions == 1
        assert first.screening_attempts == 1
        assert first.screening_results == 1
        assert first.screening_artifacts == 6
        assert first.screening_feedback == 0
        assert session.scalar(select(func.count()).select_from(OrderPlan)) == 1

        second = ingest_run(run_dir, session)
        assert second.screening_executions == 0
        assert second.screening_attempts == 0
        assert second.screening_results == 0
        assert second.screening_artifacts == 0
        assert second.screening_feedback == 0
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 1
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningBatchAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningResult)) == 1
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningArtifact)) == 6

        result_path = run_dir / "screening-results.json"
        result_value = json.loads(result_path.read_text(encoding="utf-8"))
        result_value["items"][0]["qwen_score"] = 0.74
        _write_c2_json(result_path, result_value)
        with pytest.raises(OrderPlanScreeningConflictError):
            ingest_run(run_dir, session)

        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 1
        stored_result = session.scalar(select(OrderPlanScreeningResult))
        assert stored_result is not None and stored_result.qwen_score == Decimal("0.1")


@requires_postgres
def test_c2_loader_keeps_failed_selected_plans_in_the_full_population(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_c2_fixture(tmp_path, failed=True)
        session.add(
            Run(
                id=source_run_id,
                timezone="Asia/Seoul",
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        result = ingest_run(run_dir, session)

        assert result.screening_results == 1
        stored_execution = session.scalar(select(OrderPlanScreeningExecution))
        stored_attempt = session.scalar(select(OrderPlanScreeningBatchAttempt))
        stored_result = session.scalar(select(OrderPlanScreeningResult))
        assert stored_execution is not None and stored_execution.status == "실패"
        assert stored_attempt is not None and stored_attempt.attempt_status == "failed"
        assert stored_result is not None and stored_result.stage2_status == "failed"
        assert stored_result.failure_code == "fixture_timeout"


@requires_postgres
def test_c2_loader_rejects_a_telemetry_final_attempt_status_mismatch(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_c2_fixture(tmp_path)
        session.add(
            Run(
                id=source_run_id,
                timezone="Asia/Seoul",
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        telemetry_path = run_dir / "screening-telemetry.json"
        telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        telemetry["batches"][0]["attempts"][0]["status"] = "failed"
        _write_c2_json(telemetry_path, telemetry)

        with pytest.raises(OrderPlanScreeningContractError):
            ingest_run(run_dir, session)
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 0


@requires_postgres
def test_c2_loader_rejects_duplicate_telemetry_batches(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_c2_fixture(tmp_path)
        session.add(
            Run(
                id=source_run_id,
                timezone="Asia/Seoul",
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        telemetry_path = run_dir / "screening-telemetry.json"
        telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        telemetry["batches"].append(telemetry["batches"][0])
        _write_c2_json(telemetry_path, telemetry)

        with pytest.raises(OrderPlanScreeningContractError):
            ingest_run(run_dir, session)
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 0


@requires_postgres
def test_c2_siblings_do_not_fall_back_to_legacy_ingest_when_schemas_are_corrupt(tmp_path):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_c2_fixture(tmp_path)
        session.add(
            Run(
                id=source_run_id,
                timezone="Asia/Seoul",
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        for filename in ("screening-input.json", "screening-results.json"):
            path = run_dir / filename
            value = json.loads(path.read_text(encoding="utf-8"))
            value["schema_version"] = "corrupted.c2"
            _write_c2_json(path, value)

        with pytest.raises(OrderPlanScreeningContractError):
            ingest_run(run_dir, session)
        assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 0
