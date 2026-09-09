"""C-2 전용 회차 디렉터리 적재 (명세 §6.2).

lifecycle `ingest_run`은 이 디렉터리를 알아보지 못한다. screening이 등록한 회차
적재 hook이 "이건 내 전용 결과이며 source run은 X"라고 주장했을 때만 적재되며,
불변 계약 위반은 어떤 행도 남기지 않고 거절된다.
"""

from __future__ import annotations

import json
import copy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lifecycle import ingest_run
from app.lifecycle.models import OrderPlan, Run
from app.screening.models import (
    OrderPlanScreeningArtifact,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningResult,
    OrderPlanScreeningPolicy,
)
from app.screening.ingest import (
    OrderPlanScreeningConflictError,
    OrderPlanScreeningContractError,
)
from tests.c2_fixtures import write_c2_fixture as _write_c2_fixture, write_c2_json as _write_c2_json
from tests.postgres import migrated_engine, requires_postgres


def test_c2_rank_order_can_differ_from_source_order(tmp_path):
    from app.screening.ingest import _c2_check_siblings

    run_dir, _ = _write_c2_fixture(tmp_path)
    names = ["input", "ranking", "decisions", "failures", "telemetry", "results"]
    docs = [json.loads((run_dir / f"screening-{name}.json").read_bytes()) for name in names]
    frozen, ranking, decisions, _, _, result = docs
    original = frozen["items"][0]["plan_id"]
    second = original + "-second"
    for doc in [frozen, ranking, decisions, result]:
        extra = copy.deepcopy(doc["items"][0])
        extra["plan_id"] = second
        doc["items"].append(extra)
    frozen["population_count"] = ranking["population_count"] = ranking["selected_count"] = 2
    decisions["candidate_count"] = 2
    ranking["items"][0]["rank"] = 2
    ranking["items"][1]["rank"] = 1
    ranking["items"].reverse()
    decisions["batches"][0]["plan_ids"] = [second, original]
    input_digest = ranking["input_artifact_sha256"]
    ranking_digest = decisions["ranking_artifact_sha256"]
    _c2_check_siblings(*docs, input_digest, ranking_digest)
    ranking["items"][0]["plan_id"] = "foreign-plan"
    with pytest.raises(OrderPlanScreeningContractError, match="same full population"):
        _c2_check_siblings(*docs, input_digest, ranking_digest)


def _write_ollama_reference_fixture(tmp_path, *, measured=False):
    run_dir, source_run_id = _write_c2_fixture(tmp_path)
    root = Path(__file__).resolve().parents[4]
    config = root / "experiments/order-plan-screening/config"
    policy = json.loads((config / "order-plan-screening-policy.v1.json").read_bytes())
    binding = json.loads((config / "order-plan-screening-phase0-binding.v1.json").read_bytes())
    policy["policy_version"] = "ollama-unmeasured-reference-test"
    policy["policy_status"] = "activation_candidate"
    policy["quality_gate"]["status"] = "passed" if measured else "not_measured"
    policy["stage2"].update(provider="approved_private_ollama", model_name="qwen3.8:27b")
    policy_sha = _write_c2_json(run_dir / "policy.json", policy)
    binding["policy"].update(policy_version=policy["policy_version"], sha256=policy_sha,
                            policy_status=policy["policy_status"])
    binding["stage2_binding"].update(provider="approved_private_ollama", model_name="qwen3.8:27b")
    binding_sha = _write_c2_json(run_dir / "binding.json", binding)
    frozen = json.loads((run_dir / "screening-input.json").read_bytes())
    frozen["policy"].update(version=policy["policy_version"], sha256=policy_sha)
    frozen["stage2_binding"]["sha256"] = binding_sha
    input_sha = _write_c2_json(run_dir / "screening-input.json", frozen)
    ranking = json.loads((run_dir / "screening-ranking.json").read_bytes())
    ranking.update(input_artifact_sha256=input_sha, policy_version=policy["policy_version"], policy_sha256=policy_sha)
    ranking_sha = _write_c2_json(run_dir / "screening-ranking.json", ranking)
    decisions = json.loads((run_dir / "screening-decisions.json").read_bytes())
    decisions.update(input_artifact_sha256=input_sha, ranking_artifact_sha256=ranking_sha)
    decisions["binding"]["model_name"] = "qwen3.8:27b"
    _write_c2_json(run_dir / "screening-decisions.json", decisions)
    result = json.loads((run_dir / "screening-results.json").read_bytes())
    result.update(input_artifact_sha256=input_sha, policy_version=policy["policy_version"], policy_sha256=policy_sha)
    _write_c2_json(run_dir / "screening-results.json", result)
    return run_dir, source_run_id


@requires_postgres
@pytest.mark.parametrize("measured", [False, True])
def test_ollama_reference_import_cannot_activate_or_claim_measured_quality(tmp_path, measured):
    with migrated_engine() as engine, Session(engine) as session:
        run_dir, source_run_id = _write_ollama_reference_fixture(tmp_path, measured=measured)
        session.add(Run(id=source_run_id, timezone="Asia/Seoul",
                        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
        session.commit()
        if measured:
            with pytest.raises(OrderPlanScreeningContractError, match="unmeasured reference"):
                ingest_run(run_dir, session)
            assert session.scalar(select(func.count()).select_from(OrderPlanScreeningExecution)) == 0
        else:
            assert ingest_run(run_dir, session).screening_results == 1
            assert ingest_run(run_dir, session).screening_results == 0
            policy = session.scalar(select(OrderPlanScreeningPolicy))
            assert policy.quality_gate_status == "not_measured"
            assert policy.active_slot is None and policy.activated_at is None
            attempt = session.scalar(select(OrderPlanScreeningBatchAttempt))
            assert attempt.model_name == "qwen3.8:27b"


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

        stored_result = session.scalar(select(OrderPlanScreeningResult))
        assert stored_result.stage1_score == Decimal("1.1234567890")
        # Even a source change below the DB scale remains an immutable conflict.
        exact_path = run_dir / "screening-results.json"
        exact_raw = exact_path.read_bytes()
        changed = json.loads(exact_raw)
        changed["items"][0]["stage1_score"] = 1.1234567890124
        _write_c2_json(exact_path, changed)
        with pytest.raises(OrderPlanScreeningConflictError):
            ingest_run(run_dir, session)
        exact_path.write_bytes(exact_raw)

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
