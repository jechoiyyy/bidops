"""C-2 policy REST — 런타임 blocker, 후보 지정, 활성화 (contracts "policy REST")."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base, get_db
from app.core.models import AuditEvent
from app.lifecycle.models import Run  # noqa: F401 - create_all이 FK 대상 테이블을 알게 한다
from app.screening.models import (
    OrderPlanScreeningPolicy,
    OrderPlanScreeningQualityEvaluation,
    OrderPlanScreeningQualityGate,
)
from app.screening.routers import order_plan_daily_trigger as daily_router
from app.screening.routers import order_plan_policies as policy_router
from app.screening.services.order_plan_daily_trigger import OrderPlanDailyTriggerService
from app.screening.services.order_plan_policy import OrderPlanPolicyService
from tests.postgres import migrated_engine, requires_postgres


REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG = REPO_ROOT / "experiments/order-plan-screening/config"
ACTOR = {"X-BidOps-Actor-Name": "approver"}
T0 = datetime(2026, 9, 18, tzinfo=UTC)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex32() -> str:
    return uuid4().hex


class World:
    """policy·binding 파일, 행, gate·evaluation을 만드는 테스트 도우미."""

    def __init__(self, root: Path, session: Session) -> None:
        self.root = root
        self.session = session
        self.settings = Settings(
            bidops_root=root,
            database_url="sqlite://",
            c2_execution_allowed=True,
            c2_daily_trigger_enabled=True,
            c2_policy_path=root / "policy.json",
            c2_binding_path=root / "binding.json",
        )

    def add_policy(
        self,
        version: str,
        *,
        status: str = "activation_candidate",
        created_at: datetime = T0,
        policy_edit: Callable[[dict[str, Any]], None] | None = None,
        binding_edit: Callable[[dict[str, Any]], None] | None = None,
        mount: bool = True,
    ) -> OrderPlanScreeningPolicy:
        policy = json.loads((CONFIG / "order-plan-screening-policy.v2.json").read_text())
        binding = json.loads((CONFIG / "order-plan-screening-phase0-binding.v2.json").read_text())
        policy["policy_version"] = version
        # 파일의 상태성 필드는 발행 시점 스냅샷 그대로 둔다 — v2 payload는 여전히
        # `activation.blockers`와 `quality_gate.activation_eligible=false`를 싣는다.
        policy["audit_sample"].update({"enabled": True, "max_per_execution": 20, "review_cadence": "weekly"})
        if policy_edit:
            policy_edit(policy)
        # 파일 bytes는 canonical이 아니다(들여쓰기). digest는 bytes 기준이어야 한다.
        policy_bytes = json.dumps(policy, ensure_ascii=False, indent=2).encode()
        binding["status"] = "activation_candidate"
        binding["policy"].update({"policy_version": version, "sha256": _sha(policy_bytes)})
        binding["external_transport"].update({
            "execution_allowed": True,
            "approval_scope": "per_binding",
            "approved_by": "transport-approver",
            "approved_at": "2026-09-18T00:00:00+09:00",
            "approval_required_per_execution": False,
        })
        if binding_edit:
            binding_edit(binding)
        binding_bytes = json.dumps(binding, ensure_ascii=False, indent=2).encode()
        if mount:
            self.settings.c2_policy_path.write_bytes(policy_bytes)
            self.settings.c2_binding_path.write_bytes(binding_bytes)
        row = OrderPlanScreeningPolicy(
            id=uuid4(),
            policy_version=version,
            schema_version=policy["schema_version"],
            producer=policy["producer"],
            consumer=policy["consumer"],
            policy_status=status,
            decision_scope=policy["decision_scope"],
            policy_payload_jsonb=policy,
            binding_payload_jsonb=binding,
            policy_sha256=_sha(policy_bytes),
            binding_sha256=_sha(binding_bytes),
            activation_metadata_jsonb=policy["activation"],
            quality_gate_status="not_measured",
            active_slot=None,
            created_by="loader",
            created_at=created_at,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def add_gate(
        self,
        policy: OrderPlanScreeningPolicy,
        *,
        basis: str = "product_rerun",
        thresholds: bool = True,
        created_at: datetime = T0,
        binding_sha256: str | None = None,
    ) -> OrderPlanScreeningQualityGate:
        gate = OrderPlanScreeningQualityGate(
            gate_id="c2gate-" + _hex32(),
            policy_version=policy.policy_version,
            policy_sha256=policy.policy_sha256,
            binding_sha256=binding_sha256 or policy.binding_sha256,
            gold_manifest_sha256="1" * 64,
            gold_artifact_sha256="2" * 64,
            gold_status="fully_human_adjudicated",
            scoring_input_sha256="3" * 64,
            evaluation_basis=basis,
            scoring_unit="per_published_day",
            measurement_run_ids_json=["run-a", "run-b"],
            required_pass_count=2,
            threshold_recall_pct=Decimal("90") if thresholds else None,
            threshold_precision_pct=Decimal("30") if thresholds else None,
            threshold_important_missed_max=0 if thresholds else None,
            threshold_review_load_max=60 if thresholds else None,
            created_by="gate-author",
            created_at=created_at,
        )
        self.session.add(gate)
        self.session.commit()
        return gate

    def add_evaluation(self, gate: OrderPlanScreeningQualityGate, result: str, revision: int = 1) -> OrderPlanScreeningQualityEvaluation:
        evaluation = OrderPlanScreeningQualityEvaluation(
            evaluation_id="c2gateeval-" + _hex32(),
            gate_id=gate.gate_id,
            revision=revision,
            result_status=result,
            pass_execution_ids_json={"pass_1": [], "pass_2": []},
            metrics_json={},
            reasons_json=[],
            artifact_sha256=_sha(uuid4().bytes),
            evaluated_by="gate-author",
            evaluated_at=T0 + timedelta(minutes=revision),
        )
        self.session.add(evaluation)
        self.session.commit()
        return evaluation

    def ready(self, version: str = "c2-v3", **kwargs: Any) -> tuple[OrderPlanScreeningPolicy, OrderPlanScreeningQualityEvaluation]:
        policy = self.add_policy(version, **kwargs)
        evaluation = self.add_evaluation(self.add_gate(policy), "통과")
        return policy, evaluation


@contextmanager
def _sqlite_session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@contextmanager
def _client(world: World, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(policy_router, "service", OrderPlanPolicyService(world.settings))
    monkeypatch.setattr(daily_router, "service", OrderPlanDailyTriggerService(world.settings))
    application = FastAPI()
    application.include_router(policy_router.router)
    application.include_router(daily_router.router)

    def override_db() -> Iterator[Session]:
        yield world.session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with _sqlite_session() as session:
        yield World(tmp_path, session)


def _activate_body(policy: OrderPlanScreeningPolicy, artifact: str, *, confirm: bool = True, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "policy-activate-request.v1",
        "producer": "human-review-client",
        "consumer": "policy-api",
        "request_id": str(uuid4()),
        "policy_sha256": policy.policy_sha256,
        "quality_gate_artifact_sha256": artifact,
        "explicit_confirmation": confirm,
        **extra,
    }


def _candidate_body(policy: OrderPlanScreeningPolicy, base: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "policy-candidate-request.v1",
        "producer": "human-review-client",
        "consumer": "policy-api",
        "request_id": str(uuid4()),
        "policy_version": policy.policy_version,
        "base_policy_sha256": base,
        "candidate_sha256": policy.policy_sha256,
        "reason": "v3 발행",
        **extra,
    }


def _pairs(blockers: list[dict[str, Any]]) -> set[tuple[str, Any]]:
    return {(item["code"], item.get("detail")) for item in blockers}


def _no_audit_sample(policy: dict[str, Any]) -> None:
    policy["audit_sample"]["enabled"] = False


def _no_transport_approver(binding: dict[str, Any]) -> None:
    binding["external_transport"]["approved_by"] = None


def _blocked_but_allowed(binding: dict[str, Any]) -> None:
    binding["status"] = "blocked"


# 각 blocker 하나만 켜지는 세계와 기대 blocker. 조회와 활성화 요청(선택된 게이트의 최신
# artifact)의 답이 같아야 한다. 순서는 두 표가 다르므로 집합으로 비교한다.
BLOCKER_CASES = {
    "thresholds_undecided": ({"thresholds": False, "result": "미측정"},
                             {("quality_gate_thresholds_undecided", None), ("quality_gate_not_passed", "미측정")}),
    "not_passed_미달": ({"result": "미달"}, {("quality_gate_not_passed", "미달")}),
    "not_passed_보류": ({"result": "보류"}, {("quality_gate_not_passed", "보류")}),
    "audit_sample": ({"policy_edit": _no_audit_sample}, {("audit_sample_policy_unapproved", None)}),
    "transport": ({"binding_edit": _no_transport_approver}, {("execution_transport_not_allowed", None)}),
    "binding_mismatch": ({"binding_edit": _blocked_but_allowed}, {("binding_digest_mismatch", None)}),
    "policy_file_missing": ({"unmount": ("policy",)}, {("policy_file_missing", "policy")}),
    "both_files_missing": ({"unmount": ("policy", "binding")}, {("policy_file_missing", "both")}),
}


@pytest.mark.parametrize("case", sorted(BLOCKER_CASES))
def test_runtime_blocker_is_the_same_for_get_and_activate(world: World, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    setup, expected = BLOCKER_CASES[case]
    policy = world.add_policy(
        "c2-v3", policy_edit=setup.get("policy_edit"), binding_edit=setup.get("binding_edit")
    )
    gate = world.add_gate(policy, thresholds=setup.get("thresholds", True))
    evaluation = world.add_evaluation(gate, setup.get("result", "통과"))
    for name in setup.get("unmount", ()):
        (world.settings.c2_policy_path if name == "policy" else world.settings.c2_binding_path).unlink()
    with _client(world, monkeypatch) as client:
        inspected = client.get("/api/order-plan-screening/policies/c2-v3")
        assert inspected.status_code == 200, inspected.text
        body = inspected.json()
        assert body["activation_allowed"] is False
        assert _pairs(body["blockers"]) == expected
        assert body["quality_gate"]["latest_evaluation"]["artifact_sha256"] == evaluation.artifact_sha256
        activated = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
            headers=ACTOR,
        )
    assert activated.status_code == 409, activated.text
    error = activated.json()["error"]
    assert error["code"] == "activation_blocked"
    assert _pairs(error["details"]["blockers"]) == expected
    world.session.refresh(policy)
    assert policy.policy_status == "activation_candidate" and policy.active_slot is None


def test_get_blocker_order_follows_the_contract_table(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = world.add_policy("c2-v3", policy_edit=_no_audit_sample, binding_edit=_no_transport_approver)
    world.add_evaluation(world.add_gate(policy, thresholds=False), "미측정")
    world.settings.c2_binding_path.unlink()
    with _client(world, monkeypatch) as client:
        blockers = client.get("/api/order-plan-screening/policies/c2-v3").json()["blockers"]
    assert blockers == [
        {"code": "quality_gate_thresholds_undecided", "detail": None},
        {"code": "quality_gate_not_passed", "detail": "미측정"},
        {"code": "audit_sample_policy_unapproved", "detail": None},
        {"code": "execution_transport_not_allowed", "detail": None},
        {"code": "policy_file_missing", "detail": "binding"},
    ]


def test_missing_gate_and_gate_without_evaluation(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = world.add_policy("c2-v3")
    with _client(world, monkeypatch) as client:
        body = client.get("/api/order-plan-screening/policies/c2-v3").json()
        assert body["quality_gate"] is None
        assert body["blockers"] == [{"code": "quality_gate_missing", "detail": None}]
        # 조회에는 없는 artifact다. 활성화 요청은 그 artifact를 특정하지 못한다.
        activated = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, "f" * 64),
            headers=ACTOR,
        )
        assert activated.status_code == 409
        assert activated.json()["error"]["details"]["blockers"] == [
            {"code": "quality_gate_artifact_unknown", "detail": None}
        ]
        world.add_gate(policy)
        body = client.get("/api/order-plan-screening/policies/c2-v3").json()
    assert body["blockers"] == [{"code": "quality_gate_not_passed", "detail": "none"}]
    assert body["quality_gate"]["latest_evaluation"] is None


def test_payload_blockers_do_not_block_when_runtime_conditions_hold(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, evaluation = world.ready()
    assert policy.policy_payload_jsonb["activation"]["blockers"]
    assert policy.policy_payload_jsonb["quality_gate"]["activation_eligible"] is False
    body = _activate_body(policy, evaluation.artifact_sha256)
    with _client(world, monkeypatch) as client:
        inspected = client.get("/api/order-plan-screening/policies/c2-v3").json()
        assert inspected["activation_allowed"] is True and inspected["blockers"] == []
        assert inspected["policy_file_present"] is True and inspected["binding_file_present"] is True
        assert inspected["external_transport"]["approval_scope"] == "per_binding"
        assert inspected["audit_sample"] == {"enabled": True, "max_per_execution": 20, "review_cadence": "weekly"}
        activated = client.post("/api/order-plan-screening/policies/c2-v3/activate", json=body, headers=ACTOR)
        assert activated.status_code == 200, activated.text
        response = activated.json()
        assert response["policy_status"] == "active" and response["quality_gate_status"] == "passed"
        assert response["evaluation_id"] == evaluation.evaluation_id
        assert response["previous_active_policy_version"] is None
        replay = client.post("/api/order-plan-screening/policies/c2-v3/activate", json=body, headers=ACTOR)
        assert replay.status_code == 200 and replay.json() == response
        conflict = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json={**body, "explicit_confirmation": False},
            headers=ACTOR,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        listed = client.get("/api/order-plan-screening/policies").json()
    assert listed["total"] == 1 and listed["items"][0]["policy_status"] == "active"
    assert listed["items"][0]["activated_by"] == "approver"


def test_rescore_gate_pass_cannot_activate(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = world.add_policy("c2-v3")
    evaluation = world.add_evaluation(world.add_gate(policy, basis="reference_artifact_rescore"), "통과")
    with _client(world, monkeypatch) as client:
        body = client.get("/api/order-plan-screening/policies/c2-v3").json()
        assert body["blockers"] == [{"code": "quality_gate_missing", "detail": None}]
        activated = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
            headers=ACTOR,
        )
    assert activated.status_code == 409
    assert activated.json()["error"]["details"]["blockers"] == [
        {"code": "quality_gate_basis_not_product_rerun", "detail": None}
    ]


def test_gate_with_other_binding_digest_is_not_selected_and_blocks(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = world.add_policy("c2-v3")
    evaluation = world.add_evaluation(world.add_gate(policy, binding_sha256="9" * 64), "통과")
    with _client(world, monkeypatch) as client:
        assert client.get("/api/order-plan-screening/policies/c2-v3").json()["blockers"] == [
            {"code": "quality_gate_missing", "detail": None}
        ]
        activated = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
            headers=ACTOR,
        )
    assert activated.json()["error"]["details"]["blockers"] == [{"code": "quality_gate_digest_mismatch", "detail": None}]


def test_policy_digest_mismatch_is_immutable_conflict(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, evaluation = world.ready()
    body = _activate_body(policy, evaluation.artifact_sha256, policy_sha256="0" * 64)
    with _client(world, monkeypatch) as client:
        response = client.post("/api/order-plan-screening/policies/c2-v3/activate", json=body, headers=ACTOR)
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "immutable_conflict",
        "message": policy_router.MESSAGES["immutable_conflict"],
        "details": None,
    }


def test_not_latest_evaluation_is_blocked(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = world.add_policy("c2-v3")
    gate = world.add_gate(policy)
    first = world.add_evaluation(gate, "통과", revision=1)
    world.add_evaluation(gate, "미달", revision=2)
    with _client(world, monkeypatch) as client:
        response = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, first.artifact_sha256),
            headers=ACTOR,
        )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["blockers"] == [
        {"code": "quality_gate_evaluation_not_latest", "detail": None}
    ]


def test_explicit_confirmation_false_is_invalid_only_after_blockers(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, evaluation = world.ready()
    with _client(world, monkeypatch) as client:
        rejected = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256, confirm=False),
            headers=ACTOR,
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "invalid_request"
        world.settings.c2_policy_path.unlink()
        blocked = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256, confirm=False),
            headers=ACTOR,
        )
        missing_actor = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
        )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "activation_blocked"
    assert missing_actor.status_code == 400 and missing_actor.json()["error"]["code"] == "actor_name_required"


def test_activation_of_non_candidate_and_unknown_version(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    policy, evaluation = world.ready(status="draft")
    with _client(world, monkeypatch) as client:
        draft = client.post(
            "/api/order-plan-screening/policies/c2-v3/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
            headers=ACTOR,
        )
        missing = client.post(
            "/api/order-plan-screening/policies/nope/activate",
            json=_activate_body(policy, evaluation.artifact_sha256),
            headers=ACTOR,
        )
        inspected = client.get("/api/order-plan-screening/policies/c2-v3").json()
    assert draft.json()["error"]["details"]["blockers"] == [{"code": "policy_not_candidate", "detail": "draft"}]
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    # 조건은 다 맞아도 draft면 활성화 가능이 아니다.
    assert inspected["blockers"] == [] and inspected["activation_allowed"] is False


def test_candidate_transition_rules(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = world.add_policy("c2-v3", status="draft")
    with _client(world, monkeypatch) as client:
        wrong_candidate = client.post(
            "/api/order-plan-screening/policies/candidate",
            json=_candidate_body(draft, None, candidate_sha256="0" * 64),
            headers=ACTOR,
        )
        wrong_base = client.post(
            "/api/order-plan-screening/policies/candidate",
            json=_candidate_body(draft, "0" * 64),
            headers=ACTOR,
        )
        blank = client.post(
            "/api/order-plan-screening/policies/candidate",
            json=_candidate_body(draft, None, reason="   "),
            headers=ACTOR,
        )
        body = _candidate_body(draft, None)
        created = client.post("/api/order-plan-screening/policies/candidate", json=body, headers=ACTOR)
        replay = client.post("/api/order-plan-screening/policies/candidate", json=body, headers=ACTOR)
        again = client.post("/api/order-plan-screening/policies/candidate", json=_candidate_body(draft, None), headers=ACTOR)
    assert wrong_candidate.status_code == 409 and wrong_candidate.json()["error"]["code"] == "immutable_conflict"
    assert wrong_base.status_code == 409 and wrong_base.json()["error"]["code"] == "immutable_conflict"
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "invalid_request"
    assert created.status_code == 201, created.text
    assert created.json()["policy_status"] == "activation_candidate"
    assert replay.status_code == 201 and replay.json() == created.json()
    # 이미 후보다 — draft가 아니다.
    assert again.status_code == 409 and again.json()["error"]["code"] == "immutable_conflict"
    world.session.refresh(draft)
    assert draft.policy_status == "activation_candidate"
    events = world.session.scalars(select(AuditEvent).where(AuditEvent.action == "c2.policy_candidate_set")).all()
    assert len(events) == 1 and events[0].safe_metadata["to_status"] == "activation_candidate"


@contextmanager
def _pg_world(tmp_path: Path) -> Iterator[World]:
    with migrated_engine() as engine, Session(engine) as session:
        yield World(tmp_path, session)


@requires_postgres
def test_postgres_candidate_activate_and_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _pg_world(tmp_path) as world:
        v1 = world.add_policy("c2-v3", status="draft", created_at=T0)
        evaluation_v1 = world.add_evaluation(world.add_gate(v1), "통과")
        with _client(world, monkeypatch) as client:
            assert client.post(
                "/api/order-plan-screening/policies/candidate", json=_candidate_body(v1, None), headers=ACTOR
            ).status_code == 201
            first = client.post(
                "/api/order-plan-screening/policies/c2-v3/activate",
                json=_activate_body(v1, evaluation_v1.artifact_sha256),
                headers=ACTOR,
            )
            assert first.status_code == 200, first.text

            # 새 버전은 파일을 다시 마운트한다. 후보 지정은 현재 active digest를 기준으로 한다.
            v2 = world.add_policy("c2-v4", status="draft", created_at=T0 + timedelta(days=1))
            evaluation_v2 = world.add_evaluation(world.add_gate(v2, created_at=T0 + timedelta(days=1)), "통과")
            stale = client.post(
                "/api/order-plan-screening/policies/candidate", json=_candidate_body(v2, None), headers=ACTOR
            )
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "immutable_conflict"
            assert client.post(
                "/api/order-plan-screening/policies/candidate",
                json=_candidate_body(v2, v1.policy_sha256),
                headers=ACTOR,
            ).status_code == 201
            second = client.post(
                "/api/order-plan-screening/policies/c2-v4/activate",
                json=_activate_body(v2, evaluation_v2.artifact_sha256),
                headers=ACTOR,
            )
            assert second.status_code == 200, second.text
            assert second.json()["previous_active_policy_version"] == "c2-v3"
            listed = client.get("/api/order-plan-screening/policies").json()

        assert [item["policy_version"] for item in listed["items"]] == ["c2-v4", "c2-v3"]
        world.session.expire_all()
        old = world.session.scalar(select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == "c2-v3"))
        new = world.session.scalar(select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == "c2-v4"))
        assert (old.policy_status, old.active_slot, old.quality_gate_status) == ("retired", None, "passed")
        assert old.activated_at is not None  # retire 뒤에도 남는다(누적 범위 판정)
        assert (new.policy_status, new.active_slot, new.quality_gate_status) == ("active", 1, "passed")
        events = world.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.request_id == second.json()["request_id"])
            .order_by(AuditEvent.action)
        ).all()
        assert [(event.action, event.aggregate_id) for event in events] == [
            ("c2.policy_activated", "c2-v4"),
            ("c2.policy_retired", "c2-v3"),
        ]
        assert events[0].safe_metadata["previous_active_policy_version"] == "c2-v3"
        assert events[0].safe_metadata["quality_gate_artifact_sha256"] == evaluation_v2.artifact_sha256
        assert events[1].safe_metadata == {
            "from_status": "active", "to_status": "retired", "replaced_by_policy_version": "c2-v4",
        }
        # DB guard: 활성화 전이 밖에서 quality_gate_status를 바꿀 수 없다.
        with pytest.raises(Exception, match="written only on activation"):
            world.session.execute(
                text("UPDATE bidops.order_plan_screening_policy SET quality_gate_status = 'failed' WHERE policy_version = 'c2-v4'")
            )
            world.session.flush()
        world.session.rollback()
