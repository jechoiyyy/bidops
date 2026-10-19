from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.core.models import AuditEvent
from app.lifecycle.models import OrderPlan, OrderPlanObservation, Run
from app.screening.models import (
    OrderPlanScreeningBatchAttempt,
    OrderPlanScreeningDailyTrigger,
    OrderPlanScreeningExecution,
    OrderPlanScreeningFeedback,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityGate,
    OrderPlanScreeningResult,
)
from app.screening.schemas.order_plans import ExecutionCreateRequest, ExecutionStopRequest, FeedbackCreateRequest
from app.screening.services.order_plan_screening import OrderPlanScreeningError, OrderPlanScreeningService


REPO_ROOT = Path(__file__).resolve().parents[4]


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# (policy, binding, generation config) per published C-2 artifact set.  v2 is
# the measured vLLM binding; v5 is the Mac LiteLLM/Ollama binding (ADR-0072).
C2_ARTIFACT_SETS = {
    "v2": (
        "order-plan-screening-policy.v2.json",
        "order-plan-screening-phase0-binding.v2.json",
        "order-plan-screening-generation-config.v4.json",
    ),
    "v5": (
        "order-plan-screening-policy.v5.json",
        "order-plan-screening-phase0-binding.v5.json",
        "order-plan-screening-generation-config.v6.json",
    ),
}


def _fixture(
    tmp_path: Path,
    count: int = 2,
    *,
    file_policy_status: str = "active",
    binding_status: str = "approved",
    artifacts: str = "v2",
    edit: Callable[[dict, dict], None] | None = None,
) -> tuple[Settings, Session, str, str, list[OrderPlan]]:
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

    policy_file, binding_file, generation_file = C2_ARTIFACT_SETS[artifacts]
    config_dir = REPO_ROOT / "experiments/order-plan-screening/config"
    policy = json.loads((config_dir / policy_file).read_text())
    binding = json.loads((config_dir / binding_file).read_text())
    # Approved prompt bodies are company material kept out of Git (the v3 body
    # was lost with the WSL2 host), so the fixture binds a synthetic prompt and
    # re-pins every digest that names it: generation config, policy, binding.
    prompt_bytes = "합성 C-2 테스트 프롬프트\n".encode()
    prompt_sha = _sha(prompt_bytes)
    generation = json.loads((config_dir / generation_file).read_bytes())
    generation["prompt_sha256"] = prompt_sha
    generation_bytes = _canonical(generation)
    generation_sha = _sha(generation_bytes)
    policy["stage2"]["prompt"]["sha256"] = prompt_sha
    policy["stage2"]["generation_config"]["sha256"] = generation_sha
    policy["bindings"]["prompt_sha256"] = prompt_sha
    policy["bindings"]["generation_config_sha256"] = generation_sha
    binding["stage2_binding"]["prompt_sha256"] = prompt_sha
    binding["stage2_binding"]["generation_config_sha256"] = generation_sha
    binding["review_inputs"]["active_prompt_sha256"] = prompt_sha
    if edit is not None:
        edit(policy, binding)
    # The file policy_status is a publish-time snapshot; the DB row below is
    # the activation authority (ADR-0060).  The binding copy must agree.
    policy["policy_status"] = file_policy_status
    if artifacts == "v2":
        policy["activation"] = {"status": "active", "enabled": True, "approved_by": "approver", "approved_at": "2026-09-02T00:00:00+00:00"}
    binding["status"] = binding_status
    binding["external_transport"]["execution_allowed"] = True
    binding["policy"]["policy_status"] = file_policy_status
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
    # The approved v1 capabilities file is tracked under config/ with the same digest.
    capabilities_path.write_bytes((config_dir / "company-capabilities.json").read_bytes())
    prompt_path.write_bytes(prompt_bytes)
    generation_config_path = root / "generation-config.json"
    generation_config_path.write_bytes(generation_bytes)
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


def _create(
    service: OrderPlanScreeningService,
    session: Session,
    policy_version: str,
    trigger: str | None = None,
) -> tuple[dict[str, object], ExecutionCreateRequest]:
    request = ExecutionCreateRequest(
        schema_version="execution-create-request.v1",
        producer="human-review-client",
        consumer="screening-api",
        request_id=uuid4(),
        source_run_id="run-c2",
        policy_version=policy_version,
    )
    return service.create_execution(session, request, "reviewer", trigger=trigger), request


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
    plans[0].contract_method = "일반경쟁"
    plans[0].notice_posted = "Y"
    plans[0].procurement_method = "자체조달"
    plans[0].supervising_agency_name = "조달청"
    plans[0].bid_ntice_no_list = "R26BK01696186000,R26BK01696187000"
    plans[0].published_at = datetime(2026, 9, 1, tzinfo=UTC)
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
    assert (item["contract_method"], item["notice_posted"]) == ("일반경쟁", "Y")

    plan_detail = service.order_plan_detail(session, plans[0].id)
    assert plan_detail["supervising_agency_name"] == "조달청"
    assert plan_detail["procurement_method"] == "자체조달"
    assert plan_detail["contract_method"] == "일반경쟁"
    assert plan_detail["notice_posted"] == "Y"
    # 공고번호가 여럿이면 수집 원문이 한 문자열이다. 서버는 쪼개지 않고 그대로 낸다.
    assert plan_detail["bid_ntice_no_list"] == "R26BK01696186000,R26BK01696187000"
    assert plan_detail["published_at"] == datetime(2026, 9, 1, tzinfo=UTC)

    history = service.screening_history(session, plans[0].id)["items"][0]
    assert history["nearest_capability"] == "데이터 연계"
    assert history["batch_id"] == "batch-read-01"
    assert history["attempt_no"] == 1
    # 이미 읽은 실행 행에서 그대로 꺼낸 값이다(추가 조회 없음).
    assert history["execution_purpose"] == execution.purpose == "operational"
    assert history["execution_started_at"] == execution.started_at
    assert history["execution_finished_at"] == execution.finished_at

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


# --- 실행 게이트 (ADR-0060, contracts "실행 트리거 헤더와 게이트") -------------


def _policy_row(session: Session, policy_version: str) -> OrderPlanScreeningPolicy:
    policy = session.scalar(select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == policy_version))
    assert policy is not None
    return policy


def _make_candidate(session: Session, policy_version: str) -> None:
    policy = _policy_row(session, policy_version)
    policy.policy_status = "activation_candidate"
    policy.quality_gate_status = "not_measured"
    policy.active_slot = None
    policy.activated_by = None
    policy.activated_at = None
    session.commit()


def _add_gate(session: Session, policy_version: str, run_ids: list[str]) -> None:
    policy = _policy_row(session, policy_version)
    session.add(OrderPlanScreeningQualityGate(
        gate_id="c2gate-" + "0" * 32,
        policy_version=policy_version,
        policy_sha256=policy.policy_sha256,
        binding_sha256=policy.binding_sha256,
        gold_manifest_sha256="a" * 64,
        gold_artifact_sha256="b" * 64,
        gold_status="approved",
        scoring_input_sha256="c" * 64,
        evaluation_basis="product_rerun",
        scoring_unit="per_published_day",
        measurement_run_ids_json=run_ids,
        required_pass_count=2,
        created_by="gate-owner",
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    ))
    session.commit()


def _audit_created(session: Session, execution_id: object) -> AuditEvent:
    event = session.scalar(select(AuditEvent).where(
        AuditEvent.action == "c2.execution_created", AuditEvent.aggregate_id == str(execution_id)
    ))
    assert event is not None
    return event


def test_create_ignores_the_file_policy_status_when_the_row_is_active(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, file_policy_status="activation_candidate")
    response, _ = _create(OrderPlanScreeningService(settings), session, policy_version)
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.purpose == "operational"
    event = _audit_created(session, execution.execution_id)
    assert event.actor_kind == "human"
    assert event.safe_metadata["trigger"] is None


def test_create_rejects_file_and_binding_policy_status_disagreement(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, file_policy_status="activation_candidate")
    policy = _policy_row(session, policy_version)
    binding = dict(policy.binding_payload_jsonb)
    binding["policy"] = {**binding["policy"], "policy_status": "active"}
    binding_bytes = _canonical(binding)
    Path(str(settings.c2_binding_path)).write_bytes(binding_bytes)
    policy.binding_payload_jsonb = binding
    policy.binding_sha256 = _sha(binding_bytes)
    session.commit()

    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version)
    assert raised.value.code == "binding_mismatch"


def test_create_rejects_a_blocked_binding_that_allows_execution(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path, binding_status="blocked")
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version)
    assert raised.value.code == "binding_mismatch"


def test_create_requires_the_mounted_policy_file(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    Path(str(settings.c2_policy_path)).unlink()
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version)
    assert raised.value.code == "binding_mismatch"


@pytest.mark.parametrize("trigger", ["daily_script", "manual_resume"])
def test_daily_triggers_recheck_the_daily_switch(tmp_path: Path, trigger: str) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version, trigger)
    assert raised.value.code == "daily_trigger_off"
    assert raised.value.status_code == 409
    assert raised.value.details == {"reasons": ["env_cap_off", "switch_off"]}  # type: ignore[attr-defined]
    assert session.scalar(select(OrderPlanScreeningExecution)) is None


@pytest.mark.parametrize("trigger", ["daily_script", "manual_resume"])
def test_daily_triggers_report_transport_unavailable_before_the_switch(tmp_path: Path, trigger: str) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    settings.c2_execution_allowed = False
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version, trigger)
    assert raised.value.code == "service_unavailable"
    assert raised.value.status_code == 503


def test_daily_script_runs_when_the_switch_is_effective(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    settings.c2_daily_trigger_enabled = True
    policy = _policy_row(session, policy_version)
    session.add(OrderPlanScreeningDailyTrigger(
        id=uuid4(), policy_version=policy_version, policy_sha256=policy.policy_sha256, enabled=True,
        reason=None, set_by="operator", set_at=datetime(2026, 9, 2, tzinfo=UTC), request_id=uuid4(),
    ))
    session.commit()
    service = OrderPlanScreeningService(settings)

    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(service, session, "c2-order-plan-screening-other", "daily_script")
    assert raised.value.code == "policy_not_active"

    response, _ = _create(service, session, policy_version, "daily_script")
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.purpose == "operational"
    assert _audit_created(session, execution.execution_id).safe_metadata["trigger"] == "daily_script"


def test_gate_measurement_runs_a_candidate_policy_on_a_measurement_run(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    _make_candidate(session, policy_version)
    _add_gate(session, policy_version, ["gate-gold-20260827-plans", "run-c2"])
    service = OrderPlanScreeningService(settings)

    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(service, session, policy_version)
    assert raised.value.code == "policy_not_active"

    response, _ = _create(service, session, policy_version, "gate_measurement")
    execution = session.get(OrderPlanScreeningExecution, UUID(str(response["execution_id"])))
    assert execution is not None and execution.purpose == "gate_measurement"
    event = _audit_created(session, execution.execution_id)
    assert event.safe_metadata["trigger"] == "gate_measurement"
    detail = service.execution_detail(session, execution.execution_id)
    assert detail["schema_version"] == "execution-detail-response.v2"
    assert detail["purpose"] == "gate_measurement"


def test_gate_measurement_rejects_a_run_outside_the_gate(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    _make_candidate(session, policy_version)
    _add_gate(session, policy_version, ["gate-gold-20260827-plans"])
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version, "gate_measurement")
    assert raised.value.code == "invalid_request"
    assert raised.value.status_code == 422
    assert session.scalar(select(OrderPlanScreeningExecution)) is None


def test_gate_measurement_still_needs_transport_approval(tmp_path: Path) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    _make_candidate(session, policy_version)
    _add_gate(session, policy_version, ["run-c2"])
    settings.c2_execution_allowed = False
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version, "gate_measurement")
    assert raised.value.code == "service_unavailable"
    assert raised.value.status_code == 503


@pytest.mark.parametrize("trigger", ["", "cron", "GATE_MEASUREMENT"])
def test_create_rejects_an_unknown_trigger(tmp_path: Path, trigger: str) -> None:
    settings, session, policy_version, _, _ = _fixture(tmp_path)
    with pytest.raises(OrderPlanScreeningError) as raised:
        _create(OrderPlanScreeningService(settings), session, policy_version, trigger)
    assert raised.value.code == "invalid_request"
    assert raised.value.status_code == 422
