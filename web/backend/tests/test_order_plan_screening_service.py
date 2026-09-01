from __future__ import annotations

from datetime import UTC, datetime
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
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
    Run,
)
from app.schemas.order_plans import ExecutionCreateRequest, ExecutionStopRequest, FeedbackCreateRequest
from app.services.order_plan_screening import OrderPlanScreeningError, OrderPlanScreeningService


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
    source = {
        "schema_version": "bidops.collected-order-plans.v1",
        "metadata": {"complete": True},
        "counts": {"total": len(plans)},
        "order_plans": [{"order_plan_unty_no": plan.order_plan_unty_no, "title": plan.title} for plan in plans],
    }
    source_path = source_dir / "collected-order-plans.json"
    source_path.write_bytes(_canonical(source))

    policy = json.loads(Path("experiments/order-plan-screening/config/order-plan-screening-policy.v1.json").read_text())
    binding = json.loads(Path("experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json").read_text())
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
    capabilities_path.write_bytes(Path("experiments/order-plan-screening/review-inputs/company/company-capabilities-v1-approved.json").read_bytes())
    prompt_path.write_bytes(Path("experiments/order-plan-screening/review-inputs/prompts/order-plan-batch-relevance-v3-approved.txt").read_bytes())
    settings = Settings(
        bidops_root=root,
        database_url="sqlite://",
        c2_execution_allowed=True,
        c2_policy_path=policy_path,
        c2_binding_path=binding_path,
        c2_capabilities_path=capabilities_path,
        c2_prompt_path=prompt_path,
        c2_bm25_script=Path("skills/bidops-screen/scripts/rank_order_plans_bm25.py").resolve(),
        c2_merge_script=Path("skills/bidops-screen/scripts/build_order_plan_screening_results.py").resolve(),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    run = Run(id="run-c2", timezone="Asia/Seoul", generated_at=datetime(2026, 9, 2, tzinfo=UTC))
    session.add(run)
    for plan in plans:
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
        quality_gate_status="not_measured",
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
