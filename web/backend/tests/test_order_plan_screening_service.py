from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import (
    AuditEvent,
    Base,
    OrderPlan,
    OrderPlanObservation,
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
    Run,
)
from app.schemas.order_plans import ExecutionCreateRequest, ExecutionStopRequest, FeedbackCreateRequest
from app.services.order_plan_screening import OrderPlanScreeningError, OrderPlanScreeningService


REPO_ROOT = Path(__file__).resolve().parents[3]


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path, count: int = 2) -> tuple[Settings, Session, str, str, list[OrderPlan]]:
    root = tmp_path / "project"
    source_dir = root / "data" / "runs" / "run-c2"
    source_dir.mkdir(parents=True)
    plans = [
        OrderPlan(order_plan_unty_no=f"P-{index}", title=f"데이터 플랫폼 구축 {index}", agency_name="기관")
        for index in range(1, count + 1)
    ]
    source_rows = [
        {
            "order_plan_unty_no": plan.order_plan_unty_no,
            "title": plan.title,
            "source_sha256": _sha(_canonical({"order_plan_unty_no": plan.order_plan_unty_no, "title": plan.title})),
        }
        for plan in plans
    ]
    source = {
        "schema_version": "bidops.collected-order-plans.v1",
        "metadata": {"complete": True},
        "counts": {"total": len(plans)},
        "order_plans": source_rows,
    }
    source_path = source_dir / "collected-order-plans.json"
    source_path.write_bytes(_canonical(source))

    policy = json.loads((REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-policy.v2.json").read_text())
    binding = json.loads((REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v2.json").read_text())
    policy["policy_status"] = "active"
    policy["activation"] = {"status": "active", "enabled": True, "approved_by": "approver", "approved_at": "2026-09-02T00:00:00+00:00"}
    binding["external_transport"]["execution_allowed"] = True
    binding["policy"]["policy_status"] = "active"
    policy_path = root / "policy.json"
    binding_path = root / "binding.json"
    policy_bytes = _canonical(policy)
    binding["policy"]["sha256"] = _sha(policy_bytes)
    binding_bytes = _canonical(binding)
    policy_path.write_bytes(policy_bytes)
    binding_path.write_bytes(binding_bytes)
    capabilities_path = root / "capabilities.json"
    prompt_path = root / "prompt.txt"
    capabilities_path.parent.mkdir(parents=True, exist_ok=True)
    capabilities_path.write_bytes((REPO_ROOT / "experiments/order-plan-screening/review-inputs/company/company-capabilities-v1-approved.json").read_bytes())
    prompt_path.write_bytes((REPO_ROOT / "experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt").read_bytes())
    generation_config_path = root / "generation-config.json"
    generation_config_path.write_bytes((REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-generation-config.v4.json").read_bytes())
    settings = Settings(
        bidops_root=root,
        database_url="sqlite://",
        c2_execution_allowed=True,
        c2_policy_path=policy_path,
        c2_binding_path=binding_path,
        c2_capabilities_path=capabilities_path,
        c2_prompt_path=prompt_path,
        c2_generation_config_path=generation_config_path,
        c2_bm25_script=(REPO_ROOT / "skills/bidops-screen/scripts/rank_order_plans_bm25.py").resolve(),
        c2_merge_script=(REPO_ROOT / "skills/bidops-screen/scripts/build_order_plan_screening_results.py").resolve(),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    run = Run(id="run-c2", timezone="Asia/Seoul", generated_at=datetime(2026, 9, 2, tzinfo=UTC))
    session.add(run)
    for plan, source_row in zip(plans, source_rows):
        plan.source_sha256 = source_row["source_sha256"]
        plan.observations.append(OrderPlanObservation(run=run, observed_at=run.generated_at))
        session.add(plan)
    session.add(OrderPlanScreeningPolicy(
        id=uuid4(),
        policy_version=policy["policy_version"],
        schema_version=policy["schema_version"],
        producer=policy["producer"],
        consumer=policy["consumer"],
        policy_status="active",
        decision_scope=policy["decision_scope"],
        policy_payload_jsonb=policy,
        binding_payload_jsonb=binding,
        policy_sha256=_sha(policy_bytes),
        binding_sha256=_sha(binding_bytes),
        activation_metadata_jsonb=policy["activation"],
        quality_gate_status="passed",
        active_slot=1,
        created_by="phase0-contracts",
        created_at=run.generated_at,
        activated_by="approver",
        activated_at=run.generated_at,
    ))
    session.commit()
    return settings, session, policy["policy_version"], _sha(binding_bytes), plans


def _create(service: OrderPlanScreeningService, session: Session, policy_version: str) -> tuple[dict[str, object], ExecutionCreateRequest]:
    request = ExecutionCreateRequest(
        schema_version="execution-create-request.v1",
        producer="human-review-client",
        consumer="screening-api",
        request_id=uuid4(),
        source_run_id="run-c2",
        policy_version=policy_version,
    )
    return service.create_execution(session, request, "reviewer"), request


def test_create_freezes_input_and_audits_in_same_transaction(tmp_path: Path) -> None:
    settings, session, policy_version, binding_sha, _ = _fixture(tmp_path)
    service = OrderPlanScreeningService(settings)
    response, request = _create(service, session, policy_version)
    replay = service.create_execution(session, request, "reviewer")
    assert replay == response
    execution_id = UUID(str(response["execution_id"]))
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None and execution.status == "대기"
    assert execution.binding_sha256 == binding_sha
    assert session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(execution_id))) is not None
    input_path = next((settings.bidops_root / "data" / "runs").glob("run-c2--c2-*/screening-input.json"))
    assert json.loads(input_path.read_text())["status"] == "frozen"


def test_stop_queued_execution_and_append_feedback_revisions(tmp_path: Path) -> None:
    settings, session, policy_version, binding_sha, plans = _fixture(tmp_path)
    service = OrderPlanScreeningService(settings)
    response, _ = _create(service, session, policy_version)
    execution_id = UUID(str(response["execution_id"]))
    stop = ExecutionStopRequest(
        schema_version="execution-stop-request.v1",
        producer="human-review-client",
        consumer="screening-api",
        request_id=uuid4(),
    )
    stopped = service.stop_execution(session, execution_id, stop, "reviewer")
    assert stopped["status"] == "중단됨"
    assert service.stop_execution(session, execution_id, stop, "reviewer") == stopped

    session.add(OrderPlanScreeningResult(
        id=uuid4(), execution_id=execution_id, source_run_id="run-c2", order_plan_id=plans[0].id,
        schema_version="bidops.order-plan-screening-result-row.v1", producer="order-plan-screening-merge",
        consumer="postgres-loader-and-review-api", input_artifact_sha256="a" * 64, policy_version=policy_version,
        policy_sha256="b" * 64, binding_sha256=binding_sha, result_sha256="c" * 64, stage1_rank=1,
        stage1_score=1, nearest_capability="cap", stage1_status="selected", stage2_status="success",
        qwen_relevance="relevant", qwen_score=.9, qwen_reason="관련 사업", batch_id="batch-0001", attempt_no=1,
        failure_code=None, created_at=datetime(2026, 9, 2, tzinfo=UTC),
    ))
    session.commit()
    first = FeedbackCreateRequest(
        schema_version="feedback-create-request.v1", producer="human-review-client", consumer="review-api",
        request_id=uuid4(), execution_id=execution_id, relevance="relevant", expected_revision=0,
    )
    created = service.create_feedback(session, plans[0].id, first, "reviewer")
    second = first.model_copy(update={"request_id": uuid4(), "relevance": "uncertain", "expected_revision": 1})
    revised = service.create_feedback(session, plans[0].id, second, "reviewer")
    assert created["revision"] == 1 and revised["revision"] == 2
    assert session.scalar(select(OrderPlanScreeningFeedback).where(OrderPlanScreeningFeedback.revision == 1)) is not None


def test_create_fails_closed_for_blocked_transport(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    settings.c2_execution_allowed = False
    service = OrderPlanScreeningService(settings)
    try:
        _create(service, session, policy_version)
    except OrderPlanScreeningError as error:
        assert error.code == "service_unavailable"
        assert error.status_code == 503
    else:
        raise AssertionError("blocked transport must fail closed")


def test_create_requires_a_passed_quality_gate(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    policy = session.scalar(select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == policy_version))
    assert policy is not None
    policy.quality_gate_status = "not_measured"
    session.commit()

    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version)
    assert raised.value.code == "policy_not_active"


def test_create_rejects_a_second_active_execution(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    service = OrderPlanScreeningService(settings)
    first, _ = _create(service, session, policy_version)
    execution = session.get(OrderPlanScreeningExecution, UUID(str(first["execution_id"])))
    assert execution is not None
    execution.status = "실행 중"
    execution.active_slot = 1
    execution.started_at = datetime(2026, 9, 2, tzinfo=UTC)
    session.commit()

    with pytest.raises(OrderPlanScreeningError, match="active_execution_exists"):
        _create(service, session, policy_version)


def test_create_rejects_incomplete_nested_collection_metadata(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    source_path = settings.bidops_root / "data" / "runs" / "run-c2" / "collected-order-plans.json"
    source = json.loads(source_path.read_text())
    source["metadata"]["collection"] = {"complete": False}
    source_path.write_bytes(_canonical(source))

    with pytest.raises(OrderPlanScreeningError, match="source_run_incomplete"):
        _create(OrderPlanScreeningService(settings), session, policy_version)


def test_create_rejects_source_hash_projection_mismatch(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    source_path = settings.bidops_root / "data" / "runs" / "run-c2" / "collected-order-plans.json"
    source = json.loads(source_path.read_text())
    source["order_plans"][0]["source_sha256"] = "f" * 64
    source_path.write_bytes(_canonical(source))

    with pytest.raises(OrderPlanScreeningError, match="source_run_incomplete"):
        _create(OrderPlanScreeningService(settings), session, policy_version)


def test_create_rejects_source_run_symlink_outside_approved_root(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    runs_root = settings.bidops_root / "data" / "runs"
    source_dir = runs_root / "run-c2"
    outside = tmp_path / "outside-run"
    outside.mkdir()
    source_dir.rename(runs_root / "run-c2-real")
    source_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OrderPlanScreeningError, match="source_run_incomplete"):
        _create(OrderPlanScreeningService(settings), session, policy_version)


def test_read_projections_include_plan_fields_history_and_safe_attempts(tmp_path: Path) -> None:
    settings, session, policy_version, binding_sha, plans = _fixture(tmp_path)
    plans[0].budget_amount = Decimal("123.45")
    plans[0].planned_order_year = "2027"
    plans[0].planned_order_month = "09"
    session.commit()
    service = OrderPlanScreeningService(settings)
    response, _ = _create(service, session, policy_version)
    execution_id = UUID(str(response["execution_id"]))
    execution = session.get(OrderPlanScreeningExecution, execution_id)
    assert execution is not None
    execution.status = "부분 성공"
    execution.started_at = datetime(2026, 9, 2, tzinfo=UTC)
    execution.finished_at = datetime(2026, 9, 2, 0, 1, tzinfo=UTC)
    session.commit()

    session.add(OrderPlanScreeningResult(
        id=uuid4(), execution_id=execution_id, source_run_id="run-c2", order_plan_id=plans[0].id,
        schema_version="bidops.order-plan-screening-result-row.v1", producer="order-plan-screening-merge",
        consumer="postgres-loader-and-review-api", input_artifact_sha256="a" * 64, policy_version=policy_version,
        policy_sha256="b" * 64, binding_sha256=binding_sha, result_sha256="c" * 64, stage1_rank=3,
        stage1_score=.7, nearest_capability="데이터 연계", stage1_status="selected", stage2_status="failed",
        qwen_relevance=None, qwen_score=None, qwen_reason=None, batch_id="batch-read-01", attempt_no=1,
        failure_code="qwen_timeout", created_at=datetime(2026, 9, 2, tzinfo=UTC),
    ))
    session.add(OrderPlanScreeningBatchAttempt(
        attempt_id=uuid4(), execution_id=execution_id, batch_id="batch-read-01", sequence=1, attempt_no=1,
        schema_version="bidops.order-plan-screening-batch-attempt-row.v1", producer="screening-worker",
        consumer="screening-merge-and-observability", plan_count=1, plan_ids_jsonb=[plans[0].id],
        plan_ids_sha256="d" * 64, model_name="qwen3.8-27B", model_digest="e" * 64,
        prompt_version="prompt-v3", prompt_sha256="f" * 64, company_profile_version="profile-v1",
        company_profile_sha256="a" * 64, generation_config_sha256="b" * 64, attempt_status="failed",
        failure_type="timeout", failure_code="qwen_timeout", response_object_ref="opaque-ref",
        input_tokens=100, cached_input_tokens=None, output_tokens=None, total_tokens=None, duration_ms=None,
        started_at=datetime(2026, 9, 2, 0, 0, tzinfo=UTC), finished_at=datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
        created_at=datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
    ))
    session.commit()

    item = service.list_order_plans(session, source_run_id="run-c2")["items"][0]
    assert item["budget_amount"] == 123.45
    assert item["planned_order_year"] == "2027"
    assert item["planned_order_month"] == "09"
    assert item["nearest_capability"] == "데이터 연계"

    history = service.screening_history(session, plans[0].id)["items"][0]
    assert history["nearest_capability"] == "데이터 연계"
    assert history["batch_id"] == "batch-read-01"
    assert history["attempt_no"] == 1

    detail = service.execution_detail(session, execution_id)
    attempt = detail["attempts"][0]
    assert attempt["model_name"] == "qwen3.8-27B"
    assert attempt["failure_code"] == "qwen_timeout"
    assert attempt["input_tokens"] == 100
    assert attempt["duration_ms"] is None
    assert "response_object_ref" not in attempt
    assert "plan_ids_jsonb" not in attempt


def test_list_ignores_a_newer_failed_execution_for_the_selected_result(tmp_path: Path) -> None:
    settings, session, policy_version, binding_sha, plans = _fixture(tmp_path, count=1)
    service = OrderPlanScreeningService(settings)
    first_response, _ = _create(service, session, policy_version)
    first_id = UUID(str(first_response["execution_id"]))
    first = session.get(OrderPlanScreeningExecution, first_id)
    assert first is not None
    first.status = "성공"
    first.started_at = datetime(2026, 9, 2, tzinfo=UTC)
    first.finished_at = datetime(2026, 9, 2, 0, 1, tzinfo=UTC)
    session.add(OrderPlanScreeningResult(
        id=uuid4(), execution_id=first_id, source_run_id="run-c2", order_plan_id=plans[0].id,
        schema_version="bidops.order-plan-screening-result-row.v1", producer="order-plan-screening-merge",
        consumer="postgres-loader-and-review-api", input_artifact_sha256="a" * 64, policy_version=policy_version,
        policy_sha256="b" * 64, binding_sha256=binding_sha, result_sha256="c" * 64, stage1_rank=1,
        stage1_score=1, nearest_capability="cap", stage1_status="selected", stage2_status="success",
        qwen_relevance="relevant", qwen_score=.9, qwen_reason="첫 실행 결과", batch_id="batch-first", attempt_no=1,
        failure_code=None, created_at=datetime(2026, 9, 2, 0, 1, tzinfo=UTC),
    ))
    session.commit()

    second_response, _ = _create(service, session, policy_version)
    second_id = UUID(str(second_response["execution_id"]))
    second = session.get(OrderPlanScreeningExecution, second_id)
    assert second is not None
    second.status = "실패"
    second.started_at = datetime(2026, 9, 2, 0, 2, tzinfo=UTC)
    second.finished_at = datetime(2026, 9, 2, 0, 3, tzinfo=UTC)
    session.add(OrderPlanScreeningResult(
        id=uuid4(), execution_id=second_id, source_run_id="run-c2", order_plan_id=plans[0].id,
        schema_version="bidops.order-plan-screening-result-row.v1", producer="order-plan-screening-merge",
        consumer="postgres-loader-and-review-api", input_artifact_sha256="d" * 64, policy_version=policy_version,
        policy_sha256="e" * 64, binding_sha256=binding_sha, result_sha256="f" * 64, stage1_rank=1,
        stage1_score=1, nearest_capability="failed-cap", stage1_status="selected", stage2_status="failed",
        qwen_relevance=None, qwen_score=None, qwen_reason=None, batch_id="batch-second", attempt_no=1,
        failure_code="worker_failed", created_at=datetime(2026, 9, 2, 0, 3, tzinfo=UTC),
    ))
    session.commit()

    item = service.list_order_plans(session, source_run_id="run-c2")["items"][0]
    assert item["stage2_status"] == "success"
    assert item["qwen_relevance"] == "relevant"
    assert item["nearest_capability"] == "cap"


@pytest.mark.parametrize("break_it", ["missing", "symlink", "digest"])
def test_create_fails_closed_when_the_generation_config_is_not_approved(tmp_path: Path, break_it: str) -> None:
    """The generation config is pinned exactly like the prompt and capabilities.

    Without this the runtime records a generation_config_sha256 it never
    opened, which is how the approved thinking switch went missing.
    """

    settings, session, policy_version, _, _ = _fixture(tmp_path)
    path = Path(str(settings.c2_generation_config_path))
    if break_it == "missing":
        path.unlink()
    elif break_it == "symlink":
        target = path.with_suffix(".target.json")
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_bytes(path.read_bytes().replace(b'"batch_size":25', b'"batch_size":26'))

    service = OrderPlanScreeningService(settings)
    with pytest.raises(OrderPlanScreeningError) as error:
        _create(service, session, policy_version)
    assert error.value.code == "binding_mismatch"
