"""C-2 품질 게이트 저장소·REST·판정 규칙 (docs/contracts.md "품질 게이트 REST", spec §4)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.models import AuditEvent
from app.lifecycle.models import Run
from app.screening.models import (
    OrderPlanScreeningExecution,
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityEvaluation,
)
from app.screening.routers.order_plan_quality_gates import router
from app.screening.schemas.order_plan_quality_gates import (
    QualityEvaluationCreateRequest,
    QualityGateCreateRequest,
)
from app.screening.services.order_plan_quality_gate import OrderPlanQualityGateService
from tests.postgres import migrated_engine, requires_postgres


NOW = datetime(2026, 9, 18, tzinfo=UTC)
POLICY_VERSION = "c2-policy-gate-test"
POLICY_SHA = "a" * 64
BINDING_SHA = "b" * 64
RUNS = ("gate-gold-20260827-plans", "gate-gold-20260828-plans")
OTHER_RUN = "daily-20260918-plans"
BASE = "/api/order-plan-screening/quality-gates"
HEADERS = {"X-BidOps-Actor-Name": "reviewer"}
GOOD = {"recall_pct": 95, "precision_pct": 40.5, "important_missed": 0, "review_load": 30}
THRESHOLDS = {
    "threshold_recall_pct": 90,
    "threshold_precision_pct": 30,
    "threshold_important_missed_max": 0,
    "threshold_review_load_max": 40,
}


def _policy() -> OrderPlanScreeningPolicy:
    return OrderPlanScreeningPolicy(
        id=uuid4(),
        policy_version=POLICY_VERSION,
        schema_version="bidops.order-plan-screening-policy.v1",
        producer="phase0-contracts",
        consumer="phase1-screening-pipeline",
        policy_status="activation_candidate",
        decision_scope="c2_order_plan_first_pass",
        policy_payload_jsonb={"policy_version": POLICY_VERSION},
        binding_payload_jsonb={"binding_version": "binding-test"},
        policy_sha256=POLICY_SHA,
        binding_sha256=BINDING_SHA,
        activation_metadata_jsonb={},
        quality_gate_status=None,
        active_slot=None,
        created_by="phase0-contracts",
        created_at=NOW,
    )


def _seed(session: Session) -> None:
    session.add(_policy())
    for run_id in (*RUNS, OTHER_RUN):
        session.add(Run(id=run_id, timezone="Asia/Seoul", generated_at=NOW))
    session.commit()


def _execution(
    session: Session,
    run_id: str,
    *,
    status: str = "성공",
    purpose: str = "gate_measurement",
    policy_sha256: str = POLICY_SHA,
) -> UUID:
    execution_id = uuid4()
    terminal = status in {"성공", "부분 성공", "실패", "중단됨"}
    running = status in {"실행 중", "중지 요청"}
    session.add(OrderPlanScreeningExecution(
        execution_id=execution_id,
        request_id=uuid4(),
        schema_version="bidops.order-plan-screening-execution-row.v1",
        producer="screening-api",
        consumer="screening-worker-and-review-api",
        source_run_id=run_id,
        source_artifact_name="collected-order-plans.json",
        source_artifact_schema_version="bidops.collected-order-plans.v1",
        source_artifact_sha256="c" * 64,
        input_artifact_sha256="d" * 64,
        population_count=1,
        population_sha256="e" * 64,
        policy_version=POLICY_VERSION,
        policy_sha256=policy_sha256,
        binding_sha256=BINDING_SHA,
        stage1_binding_version="bm25-test",
        stage1_binding_sha256="f" * 64,
        stage2_binding_version="binding-test",
        stage2_binding_sha256=BINDING_SHA,
        status=status,
        active_slot=1 if running else None,
        requested_by="reviewer",
        partial_artifact=status == "부분 성공",
        queued_at=NOW,
        started_at=NOW if terminal or running else None,
        finished_at=NOW if terminal else None,
        created_at=NOW,
        purpose=purpose,
    ))
    session.commit()
    return execution_id


def _pass(session: Session, **overrides: str) -> list[str]:
    return [str(_execution(session, run_id, **overrides)) for run_id in RUNS]


def _gate_body(*, basis: str = "product_rerun", thresholds: dict | None = None, **overrides) -> dict:
    body = {
        "schema_version": "order-plan-quality-gate-create-request.v1",
        "producer": "human-review-client",
        "consumer": "quality-gate-api",
        "request_id": str(uuid4()),
        "policy_version": POLICY_VERSION,
        "policy_sha256": POLICY_SHA,
        "binding_sha256": BINDING_SHA,
        "gold_manifest_sha256": "1" * 64,
        "gold_artifact_sha256": "2" * 64,
        "gold_status": "approved-by-human",
        "scoring_input_sha256": "3" * 64,
        "evaluation_basis": basis,
        "measurement_run_ids": list(RUNS),
        **(THRESHOLDS if thresholds is None else thresholds),
    }
    body.update(overrides)
    return body


def _evaluation_body(pass_ids: dict, pass_metrics: dict, **overrides) -> dict:
    body = {
        "schema_version": "order-plan-quality-evaluation-create-request.v1",
        "producer": "human-review-client",
        "consumer": "quality-gate-api",
        "request_id": str(uuid4()),
        "artifact_sha256": uuid4().hex + uuid4().hex,
        "pass_execution_ids": pass_ids,
        "pass_metrics": pass_metrics,
    }
    body.update(overrides)
    return body


@pytest.fixture
def api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    _seed(session)

    def override_get_db():
        yield session

    # tests/screening은 조립 계층(app.main)을 import하지 않는다. 등록은 tests/app이 본다.
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(application) as client:
            yield client, session
    finally:
        session.close()
        engine.dispose()


def _create_gate(client: TestClient, **kwargs) -> dict:
    response = client.post(BASE, json=_gate_body(**kwargs), headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def _evaluate(client: TestClient, gate_id: str, body: dict, expected: int = 201) -> dict:
    response = client.post(f"{BASE}/{gate_id}/evaluations", json=body, headers=HEADERS)
    assert response.status_code == expected, response.text
    return response.json()


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def test_gate_create_contract_errors_and_idempotency(api) -> None:
    client, session = api
    body = _gate_body(thresholds={key: None for key in THRESHOLDS})
    created = client.post(BASE, json=body, headers=HEADERS)
    assert created.status_code == 201, created.text
    gate = created.json()
    assert gate["schema_version"] == "order-plan-quality-gate-response.v1"
    assert gate["gate_id"].startswith("c2gate-") and len(gate["gate_id"]) == 39
    assert gate["scoring_unit"] == "per_published_day" and gate["required_pass_count"] == 2
    assert gate["measurement_run_ids"] == list(RUNS)
    assert gate["thresholds"] == {"recall_pct": None, "precision_pct": None, "important_missed_max": None, "review_load_max": None}
    assert gate["latest_evaluation"] is None and gate["created_by"] == "reviewer"

    replay = client.post(BASE, json=body, headers=HEADERS)
    assert replay.status_code == 201 and replay.json() == gate
    changed = client.post(BASE, json={**body, "gold_status": "other"}, headers=HEADERS)
    assert changed.status_code == 409 and _error_code(changed) == "idempotency_conflict"

    assert client.post(BASE, json=_gate_body(), headers={}).json()["error"]["code"] == "actor_name_required"
    missing_policy = client.post(BASE, json=_gate_body(policy_version="nope"), headers=HEADERS)
    assert missing_policy.status_code == 404 and _error_code(missing_policy) == "not_found"
    digest = client.post(BASE, json=_gate_body(binding_sha256="9" * 64), headers=HEADERS)
    assert digest.status_code == 409 and _error_code(digest) == "immutable_conflict"
    for overrides in (
        {"measurement_run_ids": [RUNS[0], RUNS[0]]},
        {"measurement_run_ids": ["no-such-run"]},
        {"threshold_recall_pct": 100.5},
        {"threshold_review_load_max": -1},
    ):
        rejected = client.post(BASE, json=_gate_body(**overrides), headers=HEADERS)
        assert rejected.status_code == 422 and _error_code(rejected) == "invalid_request", overrides
    # 네 임계값 key는 값이 null이어도 반드시 있어야 한다(body 검증 → FastAPI 기본 422).
    partial = _gate_body()
    del partial["threshold_recall_pct"]
    assert "detail" in client.post(BASE, json=partial, headers=HEADERS).json()
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.quality_gate_created")) is not None


def test_undecided_thresholds_fix_unmeasured_even_with_good_values(api) -> None:
    client, session = api
    gate = _create_gate(client, thresholds={key: None for key in THRESHOLDS} | {"threshold_recall_pct": 90})
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": _pass(session), "pass_2": _pass(session)},
        {"pass_1": GOOD, "pass_2": GOOD},
    ))
    assert evaluation["result_status"] == "미측정"
    assert evaluation["reasons"] == ["thresholds_undecided"]
    assert evaluation["revision"] == 1


def test_one_pass_is_held(api) -> None:
    client, session = api
    gate = _create_gate(client)
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body({"pass_1": _pass(session)}, {"pass_1": GOOD}))
    assert evaluation["result_status"] == "보류"
    assert evaluation["reasons"] == ["pass_count_below_required"]
    assert evaluation["pass_execution_ids"]["pass_2"] is None and evaluation["metrics"]["pass_2"] is None


def test_partial_success_pass_execution_is_held(api) -> None:
    client, session = api
    gate = _create_gate(client)
    pass_2 = [str(_execution(session, RUNS[0], status="부분 성공")), str(_execution(session, RUNS[1]))]
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": _pass(session), "pass_2": pass_2}, {"pass_1": GOOD, "pass_2": GOOD},
    ))
    assert evaluation["result_status"] == "보류"
    assert evaluation["reasons"] == ["pass_execution_not_success"]


def test_both_passes_met_is_passed_with_human_reasons_kept(api) -> None:
    client, session = api
    gate = _create_gate(client)
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": _pass(session), "pass_2": _pass(session)},
        # 경계값(= 임계값)은 충족이다.
        {"pass_1": GOOD, "pass_2": {"recall_pct": 90, "precision_pct": 30, "important_missed": 0, "review_load": 40}},
        agreement_pct=97.5,
        reference_full_window={"recall_pct": 93.25, "precision_pct": 35, "important_missed": 1, "review_load": 120},
        reasons=["gold v3 기준"],
    ))
    assert evaluation["result_status"] == "통과"
    assert evaluation["reasons"] == ["gold v3 기준"]
    assert evaluation["metrics"]["agreement_pct"] == 97.5
    assert evaluation["metrics"]["reference_full_window"]["review_load"] == 120
    # 나쁜 쪽 값: recall·precision은 작은 값, 누락·검토량은 큰 값.
    assert (
        evaluation["measured_recall_pct"], evaluation["measured_precision_pct"],
        evaluation["measured_important_missed"], evaluation["measured_review_load"],
    ) == (90, 30, 0, 40)
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.quality_evaluation_recorded"))
    assert audit.safe_metadata == {
        "gate_id": gate["gate_id"], "revision": 1, "result_status": "통과",
        "evaluation_basis": "product_rerun", "artifact_sha256": evaluation["artifact_sha256"],
    }


def test_one_pass_below_threshold_fails_with_metric_reasons_and_worst_values(api) -> None:
    client, session = api
    gate = _create_gate(client)
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": _pass(session), "pass_2": _pass(session)},
        {"pass_1": GOOD, "pass_2": {"recall_pct": 88.5, "precision_pct": 50, "important_missed": 0, "review_load": 41}},
    ))
    assert evaluation["result_status"] == "미달"
    assert evaluation["reasons"] == ["threshold_not_met:recall_pct", "threshold_not_met:review_load"]
    assert (
        evaluation["measured_recall_pct"], evaluation["measured_precision_pct"],
        evaluation["measured_important_missed"], evaluation["measured_review_load"],
    ) == (88.5, 40.5, 0, 41)


def test_null_measurement_propagates_to_worst_value_and_holds(api) -> None:
    client, session = api
    gate = _create_gate(client)
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": _pass(session), "pass_2": _pass(session)},
        {"pass_1": GOOD, "pass_2": {"recall_pct": None, "precision_pct": 20, "important_missed": 2, "review_load": 10}},
    ))
    # precision·중요 누락이 미달이어도 계산 불가가 먼저다(보류 > 미달).
    assert evaluation["result_status"] == "보류"
    assert evaluation["reasons"] == ["measurement_missing"]
    assert evaluation["measured_recall_pct"] is None
    assert (evaluation["measured_precision_pct"], evaluation["measured_important_missed"], evaluation["measured_review_load"]) == (20, 2, 30)


def test_linkage_checks_reject_without_recording(api) -> None:
    client, session = api
    gate = _create_gate(client)
    good_pass = _pass(session)
    cases = {
        "operational": _pass(session, purpose="operational"),
        "other policy digest": _pass(session, policy_sha256="9" * 64),
        "missing run": good_pass[:1],
        "extra run": _pass(session) + [str(_execution(session, OTHER_RUN))],
        "one run twice": [str(_execution(session, RUNS[0])), str(_execution(session, RUNS[0]))],
        "unknown execution": [str(uuid4()), good_pass[1]],
    }
    for label, pass_2 in cases.items():
        response = client.post(
            f"{BASE}/{gate['gate_id']}/evaluations",
            json=_evaluation_body({"pass_1": _pass(session), "pass_2": pass_2}, {"pass_1": GOOD, "pass_2": GOOD}),
            headers=HEADERS,
        )
        assert response.status_code == 422 and _error_code(response) == "invalid_request", label
    shared = client.post(
        f"{BASE}/{gate['gate_id']}/evaluations",
        json=_evaluation_body({"pass_1": good_pass, "pass_2": good_pass}, {"pass_1": GOOD, "pass_2": GOOD}),
        headers=HEADERS,
    )
    assert shared.status_code == 422, "한 실행이 두 pass에 나오면 거부"
    orphan_metrics = client.post(
        f"{BASE}/{gate['gate_id']}/evaluations",
        json=_evaluation_body({"pass_1": good_pass}, {"pass_1": GOOD, "pass_2": GOOD}),
        headers=HEADERS,
    )
    assert orphan_metrics.status_code == 422
    missing_gate = client.post(
        f"{BASE}/c2gate-{'0' * 32}/evaluations",
        json=_evaluation_body({"pass_1": good_pass}, {"pass_1": GOOD}),
        headers=HEADERS,
    )
    assert missing_gate.status_code == 404
    assert session.scalars(select(OrderPlanScreeningQualityEvaluation)).all() == []


def test_evaluations_append_revisions_and_artifact_is_unique(api) -> None:
    client, session = api
    gate = _create_gate(client)
    ids = {"pass_1": _pass(session), "pass_2": _pass(session)}
    first_body = _evaluation_body({"pass_1": ids["pass_1"]}, {"pass_1": GOOD})
    first = _evaluate(client, gate["gate_id"], first_body)
    stored_first = session.get(OrderPlanScreeningQualityEvaluation, first["evaluation_id"])
    snapshot = (stored_first.result_status, stored_first.reasons_json, stored_first.metrics_json, stored_first.revision)

    replay = client.post(f"{BASE}/{gate['gate_id']}/evaluations", json=first_body, headers=HEADERS)
    assert replay.status_code == 201 and replay.json() == first
    second = _evaluate(client, gate["gate_id"], _evaluation_body(ids, {"pass_1": GOOD, "pass_2": GOOD}))
    assert (first["revision"], second["revision"]) == (1, 2)
    assert (first["result_status"], second["result_status"]) == ("보류", "통과")
    session.expire_all()
    stored_first = session.get(OrderPlanScreeningQualityEvaluation, first["evaluation_id"])
    assert (stored_first.result_status, stored_first.reasons_json, stored_first.metrics_json, stored_first.revision) == snapshot

    reused = client.post(
        f"{BASE}/{gate['gate_id']}/evaluations",
        json=_evaluation_body(ids, {"pass_1": GOOD, "pass_2": GOOD}, artifact_sha256=first["artifact_sha256"]),
        headers=HEADERS,
    )
    assert reused.status_code == 409 and _error_code(reused) == "immutable_conflict"


def test_reference_rescore_requires_empty_executions_and_adds_reason(api) -> None:
    client, session = api
    gate = _create_gate(client, basis="reference_artifact_rescore")
    with_runs = client.post(
        f"{BASE}/{gate['gate_id']}/evaluations",
        json=_evaluation_body({"pass_1": _pass(session), "pass_2": []}, {"pass_1": GOOD, "pass_2": GOOD}),
        headers=HEADERS,
    )
    assert with_runs.status_code == 422 and _error_code(with_runs) == "invalid_request"
    evaluation = _evaluate(client, gate["gate_id"], _evaluation_body(
        {"pass_1": [], "pass_2": []}, {"pass_1": GOOD, "pass_2": GOOD}, reasons=["ADR-0037 비교용"],
    ))
    # 통과여도 제품 파이프라인 결과가 아니라는 표식이 항상 붙는다(활성화는 열지 못한다).
    assert evaluation["result_status"] == "통과"
    assert evaluation["reasons"] == ["not_product_pipeline_result", "ADR-0037 비교용"]
    assert evaluation["pass_execution_ids"] == {"pass_1": [], "pass_2": []}


def test_gate_list_shows_latest_evaluation_and_measurement_executions(api) -> None:
    client, session = api
    first_gate = _create_gate(client)
    measured = _pass(session)
    _execution(session, RUNS[0], purpose="operational")
    _execution(session, OTHER_RUN)
    running = _execution(session, RUNS[1], status="실행 중")
    _evaluate(client, first_gate["gate_id"], _evaluation_body({"pass_1": measured}, {"pass_1": GOOD}))
    latest = _evaluate(client, first_gate["gate_id"], _evaluation_body({"pass_1": measured}, {"pass_1": GOOD}))
    second_gate = _create_gate(client, measurement_run_ids=[OTHER_RUN])

    listed = client.get(BASE, params={"policy_version": POLICY_VERSION})
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["schema_version"] == "order-plan-quality-gate-list-response.v1"
    items = {item["gate_id"]: item for item in payload["items"]}
    assert set(items) == {first_gate["gate_id"], second_gate["gate_id"]}
    first = items[first_gate["gate_id"]]
    assert first["latest_evaluation"]["revision"] == 2
    assert first["latest_evaluation"]["evaluation_id"] == latest["evaluation_id"]
    executions = first["measurement_executions"]
    assert sorted(item["execution_id"] for item in executions) == sorted([*measured, str(running)])
    assert {item["source_run_id"] for item in executions} == set(RUNS)
    running_view = next(item for item in executions if item["execution_id"] == str(running))
    assert running_view["status"] == "실행 중" and running_view["finished_at"] is None
    assert [item["source_run_id"] for item in items[second_gate["gate_id"]]["measurement_executions"]] == [OTHER_RUN]
    assert items[second_gate["gate_id"]]["latest_evaluation"] is None

    missing = client.get(BASE)
    assert missing.status_code == 422 and _error_code(missing) == "invalid_request"
    unknown = client.get(BASE, params={"policy_version": "nope"})
    assert unknown.status_code == 404 and _error_code(unknown) == "not_found"


@requires_postgres
def test_postgres_evaluation_revisions_are_append_only() -> None:
    service = OrderPlanQualityGateService()
    with migrated_engine() as engine, Session(engine) as session:
        _seed(session)
        gate = service.create_gate(
            session, QualityGateCreateRequest.model_validate(_gate_body()), "reviewer",
        )
        ids = {"pass_1": _pass(session), "pass_2": _pass(session)}
        first = service.create_evaluation(
            session, gate["gate_id"],
            QualityEvaluationCreateRequest.model_validate(_evaluation_body({"pass_1": ids["pass_1"]}, {"pass_1": GOOD})),
            "reviewer",
        )
        second = service.create_evaluation(
            session, gate["gate_id"],
            QualityEvaluationCreateRequest.model_validate(_evaluation_body(ids, {"pass_1": GOOD, "pass_2": GOOD})),
            "reviewer",
        )
        assert (first["revision"], second["revision"]) == (1, 2)
        assert (first["result_status"], second["result_status"]) == ("보류", "통과")
        assert second["measured_precision_pct"] == 40.5

        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(
                text("UPDATE bidops.order_plan_screening_quality_evaluation SET result_status = '통과' WHERE evaluation_id = :id"),
                {"id": first["evaluation_id"]},
            )
        session.rollback()
        stored = session.get(OrderPlanScreeningQualityEvaluation, first["evaluation_id"])
        assert (stored.revision, stored.result_status) == (1, "보류")

        undecided = service.create_gate(
            session,
            QualityGateCreateRequest.model_validate(_gate_body(thresholds={key: None for key in THRESHOLDS})),
            "reviewer",
        )
        measured = service.create_evaluation(
            session, undecided["gate_id"],
            QualityEvaluationCreateRequest.model_validate(
                _evaluation_body({"pass_1": _pass(session), "pass_2": _pass(session)}, {"pass_1": GOOD, "pass_2": GOOD})
            ),
            "reviewer",
        )
        assert measured["result_status"] == "미측정"
