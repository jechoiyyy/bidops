"""screening이 제공하는 lifecycle 확장점 `briefing_order_plan_candidates` (RL-01 spec).

relevant 판정 = 누적 실행(활성화된 적 있는 policy의 운영 목적 완료 실행)에서
발주계획별 **최신** 결과다. 목록 누적 모드(`list_order_plans`)와 같은 순서 규칙
(`finished_at` 내림·`execution_id` 내림)을 쓴다. 창은 `first_discovered_at ∈ (since, until]`.

실행 행은 서비스 생성 경로 대신 직접 넣는다. 생성 경로는 gitignore된 승인 프롬프트·회사
역량 파일을 읽으므로(engineering-notes "회차 원본 밖의 gitignore 된 입력") 이 검사가 그
파일 유무에 묶이지 않게 한다. 여기서 보는 것은 실행 범위·최신 결과·창 판정뿐이다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.lifecycle import ExtensionRegistry
from app.lifecycle.models import OrderPlan, OrderPlanObservation, Run
from app.screening import register_lifecycle_extensions
from app.screening.models import (
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
)
from app.screening.projection import ScreeningBriefingOrderPlanCandidates
from app.screening.services.order_plan_screening import OrderPlanScreeningService

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG = REPO_ROOT / "experiments/order-plan-screening/config"
NOW = datetime(2026, 10, 1, tzinfo=UTC)
SINCE = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)
UNTIL = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)
HEX = "a" * 64


def _policy_row(*, activated: bool) -> OrderPlanScreeningPolicy:
    policy = json.loads((CONFIG / "order-plan-screening-policy.v2.json").read_text())
    binding = json.loads((CONFIG / "order-plan-screening-phase0-binding.v2.json").read_text())
    version = policy["policy_version"] + ("" if activated else "-draft")
    return OrderPlanScreeningPolicy(
        id=uuid4(),
        policy_version=version,
        schema_version=policy["schema_version"],
        producer=policy["producer"],
        consumer=policy["consumer"],
        policy_status="active" if activated else "draft",
        decision_scope=policy["decision_scope"],
        policy_payload_jsonb=policy,
        binding_payload_jsonb=binding,
        policy_sha256=hashlib.sha256(version.encode()).hexdigest(),
        binding_sha256=HEX,
        activation_metadata_jsonb=policy.get("activation") or {},
        quality_gate_status="passed" if activated else "not_measured",
        active_slot=1 if activated else None,
        created_by="test",
        created_at=NOW,
        activated_by="approver" if activated else None,
        activated_at=NOW if activated else None,
    )


@pytest.fixture
def c2():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    run = Run(id="run-c2", timezone="Asia/Seoul", generated_at=NOW)
    session.add(run)
    plans = [
        OrderPlan(order_plan_unty_no=f"P-{index}", title=f"연차 사업 {index}", agency_name="기관",
                  first_discovered_at=SINCE + timedelta(hours=3))
        for index in range(7)
    ]
    for plan in plans:
        plan.observations.append(OrderPlanObservation(run=run, observed_at=NOW))
        session.add(plan)
    active, draft = _policy_row(activated=True), _policy_row(activated=False)
    session.add_all([active, draft])
    session.commit()
    try:
        yield session, plans, active.policy_version, draft.policy_version
    finally:
        session.close()
        engine.dispose()


def _execution(session, policy_version, *, status="성공", minute=1, purpose="operational"):
    finished = status in {"성공", "부분 성공", "실패", "중단됨"}
    row = OrderPlanScreeningExecution(
        execution_id=uuid4(), request_id=uuid4(),
        schema_version="bidops.order-plan-screening-execution-row.v1",
        producer="screening-api", consumer="screening-worker-and-review-api",
        source_run_id="run-c2", source_artifact_name="collected-order-plans.json",
        source_artifact_schema_version="bidops.collected-order-plans.v1",
        source_artifact_sha256=HEX, input_artifact_sha256=HEX,
        population_count=7, population_sha256=HEX,
        policy_version=policy_version, policy_sha256=HEX, binding_sha256=HEX,
        stage1_binding_version="s1", stage1_binding_sha256=HEX,
        stage2_binding_version="s2", stage2_binding_sha256=HEX,
        status=status, active_slot=None, requested_by="reviewer",
        partial_artifact=status != "성공",
        queued_at=NOW, started_at=NOW if finished else None,
        finished_at=NOW + timedelta(minutes=minute) if finished else None,
        created_at=NOW, purpose=purpose,
    )
    session.add(row)
    session.flush()
    return row


def _result(session, execution, plan, *, relevance="relevant", stage2="success"):
    success = stage2 == "success"
    session.add(OrderPlanScreeningResult(
        id=uuid4(), execution_id=execution.execution_id, source_run_id=execution.source_run_id,
        order_plan_id=plan.id, schema_version="bidops.order-plan-screening-result-row.v1",
        producer="order-plan-screening-merge", consumer="postgres-loader-and-review-api",
        input_artifact_sha256=HEX, policy_version=execution.policy_version,
        policy_sha256=HEX, binding_sha256=HEX, result_sha256=HEX,
        stage1_status="selected", stage1_rank=1, stage1_score=1, nearest_capability="데이터",
        stage2_status=stage2, qwen_relevance=relevance if success else None,
        qwen_score=.8 if success else None, qwen_reason="제목 근거" if success else None,
        batch_id="batch-1" if success else None, attempt_no=1 if success else None,
        failure_code=None if success else "test_failure",
        created_at=execution.finished_at or NOW,
    ))
    session.flush()


def _found(session):
    provider = ScreeningBriefingOrderPlanCandidates()
    return list(provider.briefing_order_plan_candidates(session, SINCE, UNTIL))


def test_latest_cumulative_result_must_be_relevant_inside_the_window(c2) -> None:
    session, plans, policy, _ = c2
    plans[4].first_discovered_at = SINCE - timedelta(minutes=1)   # 창 밖(이전)
    plans[5].first_discovered_at = SINCE                          # 하한은 배타
    plans[6].first_discovered_at = UNTIL                          # 상한은 포함
    old = _execution(session, policy, minute=1)
    _result(session, old, plans[0], relevance="relevant")         # 뒤 실행이 not_relevant
    _result(session, old, plans[1], relevance="not_relevant")     # 뒤 실행이 relevant
    _result(session, old, plans[2], relevance="relevant")         # 최신이 그대로 relevant
    new = _execution(session, policy, status="부분 성공", minute=2)
    _result(session, new, plans[0], relevance="not_relevant")
    _result(session, new, plans[1], relevance="relevant")
    for plan in plans[4:]:
        _result(session, new, plan, relevance="relevant")
    # 완료되지 않은 실행의 결과는 빌리지 않는다.
    failed = _execution(session, policy, status="실패", minute=3)
    _result(session, failed, plans[2], stage2="failed")
    _result(session, failed, plans[3], relevance="relevant")
    session.commit()

    assert _found(session) == sorted([plans[1].id, plans[2].id, plans[6].id])
    # 목록 누적 모드와 같은 최신 결과 규칙이다(창 조건만 다르다).
    listed = OrderPlanScreeningService().list_order_plans(session, qwen_relevance="relevant", limit=100)
    assert sorted(item["order_plan_pk"] for item in listed["items"]) == sorted(
        [plans[1].id, plans[2].id, plans[4].id, plans[5].id, plans[6].id]
    )


def test_uncertain_and_failed_latest_results_are_not_candidates(c2) -> None:
    session, plans, policy, _ = c2
    first = _execution(session, policy, minute=1)
    _result(session, first, plans[0], relevance="relevant")
    _result(session, first, plans[1], relevance="relevant")
    second = _execution(session, policy, minute=2)
    _result(session, second, plans[0], relevance="uncertain")
    _result(session, second, plans[1], stage2="failed")
    session.commit()
    assert _found(session) == []


def test_gate_measurement_and_never_activated_policies_are_outside_the_scope(c2) -> None:
    session, plans, policy, draft = c2
    gate = _execution(session, policy, purpose="gate_measurement")
    _result(session, gate, plans[0], relevance="relevant")
    unapproved = _execution(session, draft)
    _result(session, unapproved, plans[1], relevance="relevant")
    stopped = _execution(session, policy, status="중단됨")
    _result(session, stopped, plans[2], relevance="relevant")
    session.commit()
    assert _found(session) == []


def test_window_bounds_must_be_timezone_aware(c2) -> None:
    session, _, _, _ = c2
    with pytest.raises(ValueError):
        ScreeningBriefingOrderPlanCandidates().briefing_order_plan_candidates(
            session, SINCE.replace(tzinfo=None), UNTIL
        )


def test_screening_registers_the_briefing_order_plan_provider(c2) -> None:
    session, plans, policy, _ = c2
    done = _execution(session, policy)
    _result(session, done, plans[0], relevance="relevant")
    session.commit()

    registry = register_lifecycle_extensions(ExtensionRegistry())
    register_lifecycle_extensions(registry)  # 같은 owner 재등록은 제자리 교체다.
    assert registry.briefing_order_plan_candidates_supported is True
    assert list(registry.briefing_order_plan_candidates(session, SINCE, UNTIL)) == [plans[0].id]
