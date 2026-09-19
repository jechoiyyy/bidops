"""C-2 감사 표본 산출·기록 계약 (spec §5, contracts "감사 표본 REST")."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.models import AuditEvent, IdempotencyRecord
from app.lifecycle.models import OrderPlan, Run
from app.screening.models import (
    OrderPlanScreeningAuditSample,
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningResult,
)
from app.screening.routers import order_plan_audit_sample as routes
from app.screening.schemas.order_plan_audit_sample import AuditSampleDrawRequest
from app.screening.services.order_plan_audit_sample import (
    OrderPlanAuditSampleService,
    compute_sample,
    plan_id_sha256,
)
from app.screening.services.order_plan_screening import _canonical
from tests.postgres import migrated_engine, requires_postgres


REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 18, tzinfo=UTC)
TOP_K = 300
URL = "/api/order-plan-screening/executions/{}/audit-sample"
ACTOR = {"X-BidOps-Actor-Name": "reviewer"}
RULES = {
    "classification_proximity": {"field": "service_type_code", "values": ["SW"]},
    "performance_similarity_proximity": {"rank_window": 3},
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _policy_payload(**audit: object) -> dict:
    policy = json.loads((REPO_ROOT / "experiments/order-plan-screening/config/order-plan-screening-policy.v2.json").read_text())
    policy["policy_version"] = "c2-audit-test"
    policy["audit_sample"].update({"sample_size": None, "enabled": True, "max_per_execution": 5, "review_cadence": "weekday"})
    policy["audit_sample"].update(audit)
    for key in [key for key, value in audit.items() if value is _DROP]:
        policy["audit_sample"].pop(key)
    return policy


_DROP = object()


def _seed(session: Session, policy: dict, *, codes: list[str | None], status: str = "성공",
          purpose: str = "operational", population: int = 320) -> OrderPlanScreeningExecution:
    """``codes[i]``는 i번째 탈락 건의 ``service_type_code``이고 stage1 순위는 301부터다."""

    policy_bytes = _canonical(policy)
    session.add(Run(id="run-c2", timezone="Asia/Seoul", generated_at=NOW))
    session.add(OrderPlanScreeningPolicy(
        id=uuid4(), policy_version=policy["policy_version"], schema_version=policy["schema_version"],
        producer=policy["producer"], consumer=policy["consumer"], policy_status="active",
        decision_scope=policy["decision_scope"], policy_payload_jsonb=policy, binding_payload_jsonb={"binding": True},
        policy_sha256=_sha(policy_bytes), binding_sha256="c" * 64, activation_metadata_jsonb={},
        quality_gate_status="passed", active_slot=1, created_by="phase0-contracts", created_at=NOW,
        activated_by="approver", activated_at=NOW,
    ))
    session.flush()
    execution = OrderPlanScreeningExecution(
        execution_id=uuid4(), request_id=uuid4(), schema_version="bidops.order-plan-screening-execution-row.v1",
        producer="screening-api", consumer="screening-worker-and-review-api", source_run_id="run-c2",
        source_artifact_name="collected-order-plans.json", source_artifact_schema_version="bidops.collected-order-plans.v1",
        source_artifact_sha256="a" * 64, input_artifact_sha256="a" * 64, population_count=population,
        population_sha256="a" * 64, policy_version=policy["policy_version"], policy_sha256=_sha(policy_bytes),
        binding_sha256="c" * 64, stage1_binding_version="bm25", stage1_binding_sha256="d" * 64,
        stage2_binding_version="qwen", stage2_binding_sha256="e" * 64, status=status,
        active_slot=1 if status in {"실행 중", "중지 요청"} else None, requested_by="reviewer",
        partial_artifact=status != "성공", stage1_filtered_out_count=len(codes), queued_at=NOW,
        started_at=None if status == "대기" else NOW,
        finished_at=NOW + timedelta(minutes=5) if status in {"성공", "부분 성공", "실패", "중단됨"} else None,
        created_at=NOW, purpose=purpose,
    )
    session.add(execution)
    selected = OrderPlan(order_plan_unty_no="P-selected", title="선택된 계획", service_type_code="SW")
    plans = [OrderPlan(order_plan_unty_no=f"P-{index:03d}", title=f"탈락 계획 {index}", service_type_code=code)
             for index, code in enumerate(codes)]
    session.add_all([selected, *plans])
    session.flush()
    rows = [(selected, "selected", 1)] + [(plan, "filtered_out", TOP_K + 1 + index) for index, plan in enumerate(plans)]
    for plan, stage1, rank in rows:
        session.add(OrderPlanScreeningResult(
            id=uuid4(), execution_id=execution.execution_id, source_run_id="run-c2", order_plan_id=plan.id,
            schema_version="bidops.order-plan-screening-result-row.v1", producer="order-plan-screening-merge",
            consumer="postgres-loader-and-review-api", input_artifact_sha256="a" * 64,
            policy_version=policy["policy_version"], policy_sha256=_sha(policy_bytes), binding_sha256="c" * 64,
            result_sha256="f" * 64, stage1_status=stage1, stage1_rank=rank, stage1_score=10 - rank / 1000,
            nearest_capability="데이터 플랫폼", stage2_status="not_attempted", created_at=NOW,
        ))
    session.commit()
    return execution


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield session, client
    session.close()
    engine.dispose()


def _body(request_id: UUID | None = None) -> dict:
    return {"schema_version": "audit-sample-draw-request.v1", "producer": "human-review-client",
            "consumer": "audit-sample-api", "request_id": str(request_id or uuid4())}


def _rows(session: Session, execution_id: UUID) -> list[tuple]:
    return list(session.execute(
        select(OrderPlanScreeningAuditSample.order_plan_id, OrderPlanScreeningAuditSample.stratum,
               OrderPlanScreeningAuditSample.selection_rank, OrderPlanScreeningAuditSample.drawn_at)
        .where(OrderPlanScreeningAuditSample.execution_id == execution_id)
        .order_by(OrderPlanScreeningAuditSample.selection_rank)
    ).all())


def test_same_input_draws_byte_identical_sample(api):
    session, client = api
    execution = _seed(session, _policy_payload(max_per_execution=4, strata_rules=RULES),
                      codes=["SW", None, "SW", None, None, "HW", None, "SW"])
    first = client.get(URL.format(execution.execution_id))
    second = client.get(URL.format(execution.execution_id))
    assert first.status_code == 200 and first.json()["status"] == "preview"
    assert first.content == second.content
    # DB가 돌려준 순서와 무관하다.
    service = OrderPlanAuditSampleService()
    candidates = service._candidates(session, execution.execution_id)
    audit = session.scalar(select(OrderPlanScreeningPolicy)).policy_payload_jsonb["audit_sample"]
    forward = compute_sample(candidates, audit, top_k=TOP_K, max_per_execution=4)
    backward = compute_sample(list(reversed(candidates)), audit, top_k=TOP_K, max_per_execution=4)
    assert _canonical(forward) == _canonical(backward)


def test_missing_max_per_execution_is_pending_human_approval(api):
    session, client = api
    execution = _seed(session, _policy_payload(max_per_execution=None), codes=[None] * 3)
    body = client.get(URL.format(execution.execution_id)).json()
    assert body["status"] == "pending_human_approval"
    assert body["pending_decision"] == "max_per_execution_and_review_cadence"
    assert body["sample"] is None and body["max_per_execution"] is None
    drawn = client.post(URL.format(execution.execution_id), json=_body(), headers=ACTOR)
    assert drawn.status_code == 200 and drawn.json()["status"] == "pending_human_approval"
    assert _rows(session, execution.execution_id) == []
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [({"population": TOP_K}, "stage1.population.at_or_below_top_k"),
     ({"purpose": "gate_measurement"}, "execution.purpose.gate_measurement")],
)
def test_not_applicable(api, kwargs, reason):
    session, client = api
    execution = _seed(session, _policy_payload(strata_rules=RULES), codes=[None] * 3, **kwargs)
    body = client.get(URL.format(execution.execution_id)).json()
    assert (body["status"], body["reason"], body["sample"]) == ("not_applicable", reason, None)
    drawn = client.post(URL.format(execution.execution_id), json=_body(), headers=ACTOR)
    assert drawn.status_code == 200 and drawn.json()["status"] == "not_applicable"
    assert _rows(session, execution.execution_id) == []


def test_execution_not_completed_is_409_and_unknown_is_404(api):
    session, client = api
    execution = _seed(session, _policy_payload(), codes=[None], status="실행 중")
    for response in (client.get(URL.format(execution.execution_id)),
                     client.post(URL.format(execution.execution_id), json=_body(), headers=ACTOR)):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "execution_not_completed"
    assert client.get(URL.format(uuid4())).json()["error"]["code"] == "not_found"


def test_at_or_below_cap_takes_every_filtered_out_plan(api):
    session, client = api
    execution = _seed(session, _policy_payload(max_per_execution=5), codes=["SW", None, "HW"])
    body = client.get(URL.format(execution.execution_id)).json()
    assert body["filtered_out_count"] == 3
    assert len(body["sample"]) == 3
    # 규칙이 없으면 전건을 한 층으로 둔다.
    assert {item["stratum"] for item in body["sample"]} == {"uniform_hash"}
    assert [item["plan_id_sha256"] for item in body["sample"]] == sorted(item["plan_id_sha256"] for item in body["sample"])
    assert all(item["plan_id_sha256"] == plan_id_sha256(item["order_plan_unty_no"]) for item in body["sample"])
    assert "P-selected" not in {item["order_plan_unty_no"] for item in body["sample"]}


def test_above_cap_fills_by_stratum_priority_and_assigns_one_stratum(api):
    session, client = api
    # 순위 301~303이 성과 유사 구간(W=3). 301·303은 분류도 일치하므로 분류 층에만 들어간다.
    codes = ["SW", None, "SW", None, "SW", None, None, None]
    execution = _seed(session, _policy_payload(max_per_execution=5, strata_rules=RULES), codes=codes)
    sample = client.get(URL.format(execution.execution_id)).json()["sample"]
    assert len(sample) == 5
    assert [item["selection_rank"] for item in sample] == [1, 2, 3, 4, 5]
    strata = [item["stratum"] for item in sample]
    assert strata == ["classification_proximity"] * 3 + ["performance_similarity_proximity", "uniform_hash"]
    classified = [item for item in sample if item["stratum"] == "classification_proximity"]
    assert {item["stage1_rank"] for item in classified} == {301, 303, 305}
    assert [item["plan_id_sha256"] for item in classified] == sorted(item["plan_id_sha256"] for item in classified)
    assert [item["stage1_rank"] for item in sample if item["stratum"] == "performance_similarity_proximity"] == [302]
    assert len({item["order_plan_pk"] for item in sample}) == 5
    uniform_pool = sorted(plan_id_sha256(f"P-{index:03d}") for index in (3, 5, 6, 7))
    assert sample[-1]["plan_id_sha256"] == uniform_pool[0]


@pytest.mark.parametrize("rules", [_DROP, {"classification_proximity": RULES["classification_proximity"]},
                                   {**RULES, "classification_proximity": {"field": "title", "values": ["SW"]}},
                                   {**RULES, "performance_similarity_proximity": {"rank_window": 0}}])
def test_above_cap_without_valid_strata_rules_is_pending(api, rules):
    session, client = api
    execution = _seed(session, _policy_payload(max_per_execution=2, strata_rules=rules), codes=[None] * 3)
    body = client.get(URL.format(execution.execution_id)).json()
    assert body["status"] == "pending_human_approval"
    assert body["pending_decision"] == "audit_sample_strata_rules"
    assert body["sample"] is None and body["max_per_execution"] == 2


def test_post_records_once_audits_trigger_and_replays(api):
    session, client = api
    execution = _seed(session, _policy_payload(max_per_execution=5, strata_rules=RULES), codes=["SW", None, "HW"])
    url = URL.format(execution.execution_id)
    preview = client.get(url).json()
    request_id = uuid4()
    first = client.post(url, json=_body(request_id), headers={**ACTOR, "X-BidOps-Trigger": "daily_script"})
    assert first.status_code == 201, first.text
    drawn = first.json()
    assert drawn["status"] == "drawn" and drawn["drawn_by"] == "reviewer"
    assert drawn["sample"] == preview["sample"]
    rows = _rows(session, execution.execution_id)
    assert len(rows) == 3
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.audit_sample_drawn"))
    assert str(event.id) == drawn["audit_event_id"]
    assert event.aggregate_type == "order_plan_screening_execution"
    assert event.aggregate_id == str(execution.execution_id)
    assert event.safe_metadata == {"trigger": "daily_script", "sample_count": 3, "filtered_out_count": 3,
                                   "max_per_execution": 5, "review_cadence": "weekday",
                                   "policy_version": "c2-audit-test"}

    replay = client.post(url, json=_body(request_id), headers=ACTOR)
    assert (replay.status_code, replay.json()) == (201, drawn)

    second = client.post(url, json=_body(), headers=ACTOR)
    assert second.status_code == 200
    assert second.json()["status"] == "drawn" and second.json()["sample"] == drawn["sample"]
    assert second.json()["audit_event_id"] is None
    assert client.get(url).json()["status"] == "drawn"
    assert _rows(session, execution.execution_id) == rows
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1

    other = _seed_second_execution(session, execution)
    conflict = client.post(URL.format(other), json=_body(request_id), headers=ACTOR)
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "idempotency_conflict")


def _seed_second_execution(session: Session, execution: OrderPlanScreeningExecution) -> UUID:
    clone = OrderPlanScreeningExecution(**{
        column.key: getattr(execution, column.key) for column in OrderPlanScreeningExecution.__table__.columns
    })
    clone.execution_id = uuid4()
    clone.request_id = uuid4()
    session.add(clone)
    session.commit()
    return clone.execution_id


def test_post_header_and_actor_errors(api):
    session, client = api
    execution = _seed(session, _policy_payload(), codes=[None])
    url = URL.format(execution.execution_id)
    for value in ("", "gate_measurement"):
        bad = client.post(url, json=_body(), headers={**ACTOR, "X-BidOps-Trigger": value})
        assert (bad.status_code, bad.json()["error"]["code"]) == (422, "invalid_request")
    missing = client.post(url, json=_body())
    assert (missing.status_code, missing.json()["error"]["code"]) == (400, "actor_name_required")
    extra = client.post(url, json={**_body(), "actor": "x"}, headers=ACTOR)
    assert extra.status_code == 422 and "detail" in extra.json()
    assert _rows(session, execution.execution_id) == []


@requires_postgres
def test_postgres_append_only_and_unique():
    with migrated_engine() as engine, Session(engine) as session:
        execution = _seed(session, _policy_payload(max_per_execution=5, strata_rules=RULES), codes=["SW", None, "HW"])
        service = OrderPlanAuditSampleService()
        status, drawn = service.draw(session, execution.execution_id, AuditSampleDrawRequest(**_body()), "reviewer")
        assert status == 201 and len(drawn["sample"]) == 3
        status, again = service.draw(session, execution.execution_id, AuditSampleDrawRequest(**_body()), "reviewer")
        assert status == 200 and again["sample"] == drawn["sample"]
        assert service.preview(session, execution.execution_id)["sample"] == drawn["sample"]
        row = session.scalar(select(OrderPlanScreeningAuditSample).order_by(OrderPlanScreeningAuditSample.selection_rank))
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(update(OrderPlanScreeningAuditSample).where(OrderPlanScreeningAuditSample.id == row.id).values(selection_rank=9))
        session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(delete(OrderPlanScreeningAuditSample).where(OrderPlanScreeningAuditSample.id == row.id))
        session.rollback()
        duplicate = OrderPlanScreeningAuditSample(**{
            column.key: getattr(row, column.key) for column in OrderPlanScreeningAuditSample.__table__.columns
        })
        duplicate.id = uuid4()
        duplicate.selection_rank = 99
        session.add(duplicate)
        with pytest.raises(IntegrityError, match="uq_order_plan_screening_audit_sample_plan"):
            session.commit()
        session.rollback()
