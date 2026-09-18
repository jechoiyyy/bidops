"""C-2 일일 자동 실행 스위치 — 4중 기본-닫힘과 버전 묶임 (contracts "일일 자동 실행 스위치 REST")."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterator
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from app.core.models import AuditEvent
from app.screening.models import OrderPlanScreeningDailyTrigger, OrderPlanScreeningPolicy
from app.screening.services.order_plan_daily_trigger import effective_state
from tests.postgres import requires_postgres
from tests.screening.test_c2_policy_api import (
    ACTOR,
    T0,
    World,
    _activate_body,
    _client,
    _pg_world,
    world,  # noqa: F401 - pytest fixture
)


URL = "/api/order-plan-screening/daily-trigger"


def _activate(client: TestClient, world: World, version: str, **kwargs: Any) -> OrderPlanScreeningPolicy:
    policy, evaluation = world.ready(version, **kwargs)
    response = client.post(
        f"/api/order-plan-screening/policies/{version}/activate",
        json=_activate_body(policy, evaluation.artifact_sha256),
        headers=ACTOR,
    )
    assert response.status_code == 200, response.text
    world.session.refresh(policy)
    return policy


def _set_body(version: str, enabled: bool = True, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "daily-trigger-set-request.v1",
        "producer": "human-review-client",
        "consumer": "daily-trigger-api",
        "request_id": str(uuid4()),
        "policy_version": version,
        "enabled": enabled,
        "reason": "일일 운영 시작",
        "explicit_confirmation": True,
        **extra,
    }


@pytest.fixture
def client(world: World, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:  # noqa: F811
    with _client(world, monkeypatch) as test_client:
        yield test_client


def test_all_conditions_on_enables_and_records_append_only_row(world: World, client: TestClient) -> None:  # noqa: F811
    policy = _activate(client, world, "c2-v3")
    before = client.get(URL).json()
    assert before["effective_enabled"] is False and before["reasons"] == ["switch_off"]
    assert before["policy_version"] == "c2-v3" and before["switch"] is None

    body = _set_body("c2-v3")
    created = client.post(URL, json=body, headers=ACTOR)
    assert created.status_code == 201, created.text
    response = created.json()
    assert response["effective_enabled"] is True and response["reasons"] == []
    assert response["policy_sha256"] == policy.policy_sha256 and response["set_by"] == "approver"
    replay = client.post(URL, json=body, headers=ACTOR)
    assert replay.status_code == 201 and replay.json() == response
    conflict = client.post(URL, json={**body, "enabled": False}, headers=ACTOR)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"

    state = client.get(URL).json()
    assert state["effective_enabled"] is True
    assert state["switch"]["enabled"] is True and state["switch"]["reason"] == "일일 운영 시작"
    assert len(world.session.scalars(select(OrderPlanScreeningDailyTrigger)).all()) == 1
    event = world.session.scalar(select(AuditEvent).where(AuditEvent.action == "c2.daily_trigger_set"))
    assert event.aggregate_id == "c2-v3"
    assert event.safe_metadata == {"enabled": True, "policy_sha256": policy.policy_sha256}

    off = client.post(URL, json=_set_body("c2-v3", enabled=False), headers=ACTOR).json()
    assert off["effective_enabled"] is False and off["reasons"] == ["switch_off"]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("env_cap", ["env_cap_off"]),
        ("gate_status", ["quality_gate_not_passed"]),
        ("env_transport", ["execution_transport_not_allowed"]),
        ("binding_transport", ["execution_transport_not_allowed"]),
        ("policy_file", ["policy_file_missing"]),
        ("binding_file", ["policy_file_missing"]),
    ],
)
def test_each_condition_off_disables(world: World, client: TestClient, condition: str, expected: list[str]) -> None:  # noqa: F811
    policy = _activate(client, world, "c2-v3")
    assert client.post(URL, json=_set_body("c2-v3"), headers=ACTOR).json()["effective_enabled"] is True
    if condition == "env_cap":
        world.settings.c2_daily_trigger_enabled = False
    elif condition == "gate_status":
        # SQLite에는 guard가 없다. active인데 passed가 아닌 행을 흉내 낸다.
        policy.quality_gate_status = "measured"
        world.session.commit()
    elif condition == "env_transport":
        world.settings.c2_execution_allowed = False
    elif condition == "binding_transport":
        binding = dict(policy.binding_payload_jsonb)
        binding["external_transport"] = {**binding["external_transport"], "execution_allowed": False}
        policy.binding_payload_jsonb = binding
        world.session.commit()
    elif condition == "policy_file":
        world.settings.c2_policy_path.unlink()
    elif condition == "binding_file":
        world.settings.c2_binding_path.write_bytes(b"{}")
    state = client.get(URL).json()
    assert state["effective_enabled"] is False
    assert state["reasons"] == expected
    assert effective_state(world.session, world.settings).reasons == tuple(expected)


def test_reason_order_and_no_active_policy(world: World, client: TestClient) -> None:  # noqa: F811
    world.settings.c2_daily_trigger_enabled = False
    assert client.get(URL).json() == {
        "schema_version": "daily-trigger-state-response.v1",
        "producer": "daily-trigger-api",
        "consumer": "human-review-client",
        "effective_enabled": False,
        "policy_version": None,
        "policy_sha256": None,
        "switch": None,
        "reasons": ["env_cap_off", "no_active_policy"],
    }
    _activate(client, world, "c2-v3")
    world.settings.c2_execution_allowed = False
    world.settings.c2_policy_path.unlink()
    assert client.get(URL).json()["reasons"] == [
        "env_cap_off", "switch_off", "execution_transport_not_allowed", "policy_file_missing",
    ]


def test_post_rejects_non_active_version_and_missing_confirmation(world: World, client: TestClient) -> None:  # noqa: F811
    no_active = client.post(URL, json=_set_body("c2-v3"), headers=ACTOR)
    assert no_active.status_code == 422 and no_active.json()["error"]["code"] == "invalid_request"
    _activate(client, world, "c2-v3")
    world.add_policy("c2-v4", status="draft", created_at=T0 + timedelta(days=1))
    other = client.post(URL, json=_set_body("c2-v4"), headers=ACTOR)
    unconfirmed = client.post(URL, json=_set_body("c2-v3", explicit_confirmation=False), headers=ACTOR)
    blank = client.post(URL, json=_set_body("c2-v3", reason="  "), headers=ACTOR)
    missing_actor = client.post(URL, json=_set_body("c2-v3"))
    for response in (other, unconfirmed, blank):
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"
        assert response.json()["error"]["details"] is None
    assert missing_actor.status_code == 400
    assert world.session.scalars(select(OrderPlanScreeningDailyTrigger)).all() == []


def test_policy_replacement_turns_the_switch_off(world: World, client: TestClient) -> None:  # noqa: F811
    _activate(client, world, "c2-v3")
    assert client.post(URL, json=_set_body("c2-v3"), headers=ACTOR).json()["effective_enabled"] is True
    _activate(client, world, "c2-v4", created_at=T0 + timedelta(days=1))
    state = client.get(URL).json()
    assert state["policy_version"] == "c2-v4" and state["switch"] is None
    assert state["effective_enabled"] is False and state["reasons"] == ["switch_bound_to_other_version"]
    turned_on = client.post(URL, json=_set_body("c2-v4"), headers=ACTOR).json()
    assert turned_on["effective_enabled"] is True and turned_on["reasons"] == []


@requires_postgres
def test_postgres_switch_rows_are_append_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _pg_world(tmp_path) as pg_world, _client(pg_world, monkeypatch) as pg_client:
        _activate(pg_client, pg_world, "c2-v3")
        created = pg_client.post(URL, json=_set_body("c2-v3"), headers=ACTOR)
        assert created.status_code == 201, created.text
        assert created.json()["effective_enabled"] is True
        assert pg_client.get(URL).json()["effective_enabled"] is True
        for statement in (
            "UPDATE bidops.order_plan_screening_daily_trigger SET enabled = false",
            "DELETE FROM bidops.order_plan_screening_daily_trigger",
        ):
            with pytest.raises(Exception, match="append-only"):
                pg_world.session.execute(text(statement))
            pg_world.session.rollback()
        assert pg_client.get(URL).json()["switch"]["enabled"] is True
