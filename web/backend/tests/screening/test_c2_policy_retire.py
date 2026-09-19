"""C-2 policy `retire` — 교체 없이 active 행을 내리는 예외 운영 명령.

활성화(`test_c2_policy_api.py`)가 이전 active를 같은 transaction에서 내리는 정상 경로와
달리, 이 명령은 대체 버전 없이 자리를 비운다. 세계 구성은 활성화 테스트의 `World`를
그대로 쓴다 — 같은 policy·binding 파일과 같은 게이트 모양이어야 4번 검사가 실제
활성화 경로를 증명한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.db as core_db
from app.core.db import Base
from app.core.models import AuditEvent
from app.screening.c2_policy import main
from app.screening.models import OrderPlanScreeningPolicy
from app.screening.services.order_plan_policy import retire_policy
from tests.postgres import requires_postgres
from tests.screening.test_c2_policy_api import (
    ACTOR,
    T0,
    World,
    _activate_body,
    _candidate_body,
    _client,
    _pg_world,
)


REASON = "배포 때 교체 없이 내린다"
VERSION = "c2-order-plan-screening-v2"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[World, sessionmaker]]:
    """SQLite 세계와 CLI가 열 세션 factory(같은 엔진)."""

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with Session(engine) as session:
        yield World(tmp_path, session), factory
    engine.dispose()


def _active(world: World, version: str = VERSION) -> OrderPlanScreeningPolicy:
    """운영 DB의 v2와 같은 모양 — active·passed·slot 1인 행."""

    # 행 CHECK(`..._active_metadata`)가 active·slot·provenance를 같이 요구하므로
    # draft로 만든 뒤 한 UPDATE로 올린다.
    row = world.add_policy(version, status="draft")
    row.policy_status = "active"
    row.active_slot = 1
    row.quality_gate_status = "passed"
    row.activated_by = "종단확인"
    row.activated_at = T0
    world.session.commit()
    return row


def _argv(*, version: str = VERSION, reason: str = REASON) -> list[str]:
    return ["retire", "--policy-version", version, "--retired-by", "담당자", "--reason", reason]


def _events(session: Session) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).where(AuditEvent.action == "c2.policy_retired")))


def test_active_row_retires_and_leaves_one_audit_event(world: tuple[World, sessionmaker]) -> None:
    instance, _ = world
    row = _active(instance)

    result = retire_policy(instance.session, policy_version=VERSION, retired_by="담당자", reason=REASON)
    instance.session.commit()

    assert result.changed is True
    instance.session.refresh(row)
    assert (row.policy_status, row.active_slot) == ("retired", None)
    # 이력은 보존한다 — 누적 범위 판정이 활성화 provenance를 읽는다.
    assert row.quality_gate_status == "passed"
    assert row.activated_by == "종단확인" and row.activated_at == T0

    events = _events(instance.session)
    assert len(events) == 1
    event = events[0]
    assert (event.actor_kind, event.claimed_name) == ("human", "담당자")
    assert (event.aggregate_type, event.aggregate_id) == ("order_plan_screening_policy", VERSION)
    assert event.request_id is None
    assert event.safe_metadata == {
        "from_status": "active",
        "to_status": "retired",
        "replaced_by_policy_version": None,
        "reason": REASON,
        "via": "cli",
    }


@pytest.mark.parametrize("status", ["draft", "activation_candidate"])
def test_non_active_row_is_rejected_and_unchanged(
    world: tuple[World, sessionmaker],
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, factory = world
    row = instance.add_policy(VERSION, status=status)
    monkeypatch.setattr(core_db, "SessionLocal", factory)

    assert main(_argv()) == 2

    assert capsys.readouterr().err.strip() == f"c2 policy retire failed: policy_not_active (policy_status={status})"
    instance.session.expire_all()
    instance.session.refresh(row)
    assert (row.policy_status, row.active_slot) == (status, None)
    assert _events(instance.session) == []


def test_missing_row_and_blank_reason_are_rejected(
    world: tuple[World, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, factory = world
    _active(instance)
    monkeypatch.setattr(core_db, "SessionLocal", factory)

    assert main(_argv(version="c2-없는버전")) == 2
    assert capsys.readouterr().err.strip() == "c2 policy retire failed: not_found"
    assert main(_argv(reason="   ")) == 2
    assert capsys.readouterr().err.strip() == "c2 policy retire failed: invalid_request"
    assert main(["retire", "--policy-version", VERSION, "--retired-by", "system", "--reason", REASON]) == 2
    assert capsys.readouterr().err.strip() == "c2 policy retire failed: actor_name_invalid"

    instance.session.expire_all()
    row = instance.session.scalar(
        select(OrderPlanScreeningPolicy).where(OrderPlanScreeningPolicy.policy_version == VERSION)
    )
    assert (row.policy_status, row.active_slot) == ("active", 1)
    assert _events(instance.session) == []


def test_second_retire_changes_nothing_and_adds_no_audit_event(
    world: tuple[World, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instance, factory = world
    _active(instance)
    monkeypatch.setattr(core_db, "SessionLocal", factory)

    assert main(_argv()) == 0
    assert main(_argv()) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[1] == "retired" and lines[0].endswith(" retired")
    assert lines[1].endswith(" already_retired")
    instance.session.expire_all()
    assert len(_events(instance.session)) == 1


@requires_postgres
def test_postgres_retire_frees_the_slot_for_the_next_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _pg_world(tmp_path) as instance:
        old = instance.add_policy("c2-v2", status="draft", created_at=T0)
        old_evaluation = instance.add_evaluation(instance.add_gate(old), "통과")
        with _client(instance, monkeypatch) as client:
            assert client.post(
                "/api/order-plan-screening/policies/candidate", json=_candidate_body(old, None), headers=ACTOR
            ).status_code == 201
            assert client.post(
                "/api/order-plan-screening/policies/c2-v2/activate",
                json=_activate_body(old, old_evaluation.artifact_sha256),
                headers=ACTOR,
            ).status_code == 200

            # 교체 없이 내린다. DB guard(0029)가 provenance 보존과 slot 해제를 검사한다.
            assert retire_policy(
                instance.session, policy_version="c2-v2", retired_by="담당자", reason=REASON
            ).changed is True
            instance.session.commit()

            new = instance.add_policy("c2-v3", status="draft", created_at=T0 + timedelta(days=1))
            new_evaluation = instance.add_evaluation(
                instance.add_gate(new, created_at=T0 + timedelta(days=1)), "통과"
            )
            # active가 없으므로 후보 지정의 기준 digest는 ``None``이다.
            assert client.post(
                "/api/order-plan-screening/policies/candidate", json=_candidate_body(new, None), headers=ACTOR
            ).status_code == 201
            activated = client.post(
                "/api/order-plan-screening/policies/c2-v3/activate",
                json=_activate_body(new, new_evaluation.artifact_sha256),
                headers=ACTOR,
            )

        assert activated.status_code == 200, activated.text
        assert activated.json()["previous_active_policy_version"] is None
        instance.session.expire_all()
        rows = {
            row.policy_version: row
            for row in instance.session.scalars(select(OrderPlanScreeningPolicy))
        }
        assert (rows["c2-v2"].policy_status, rows["c2-v2"].active_slot) == ("retired", None)
        assert rows["c2-v2"].quality_gate_status == "passed" and rows["c2-v2"].activated_at is not None
        assert (rows["c2-v3"].policy_status, rows["c2-v3"].active_slot) == ("active", 1)
