"""사업기회 노트·다음 행동의 PostgreSQL 변형 (RL-02 spec T4, strict dict).

migration head(0039)와 `scripts/runtime-privileges.sql`을 적용한 일회용 PostgreSQL에서
runtime `app` 역할로 노트 REST를 실제 경로로 부른다(역할 생성·권한 적용은
`test_briefing_api_postgres.py`·`test_runtime_database_privileges.py` 선례). 본문 UPDATE와
DELETE는 DB 권한이 거부해야 하고(`UPDATE (done_at, done_by)`만 열려 있다), CHECK를 어기는
행은 DB가 거부해야 한다.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.models import IdempotencyRecord
from app.lifecycle.models import Opportunity, OpportunityNote
from app.lifecycle.services import opportunity_notes
from app.main import create_app
from tests.app.test_runtime_database_privileges import _ensure_roles
from tests.postgres import migrated_engine, requires_postgres

pytestmark = requires_postgres

ROOT = Path(__file__).resolve().parents[4]
RUNTIME_POLICY = (ROOT / "scripts/runtime-privileges.sql").read_text(encoding="utf-8")
CREATED_AT = datetime(2026, 10, 17, 1, 2, 3, 456789, tzinfo=UTC)
DONE_AT = datetime(2026, 10, 17, 4, 5, 6, 789012, tzinfo=UTC)
KIM = {"X-BidOps-Actor-Name": "kim"}
LEE = {"X-BidOps-Actor-Name": "lee"}


@pytest.fixture(scope="module")
def pg_engine():
    with migrated_engine() as engine:
        _ensure_roles()
        with engine.connect() as connection:
            cursor = connection.connection.driver_connection.cursor()
            try:
                cursor.execute(RUNTIME_POLICY, prepare=False)
            finally:
                cursor.close()
        yield engine


@pytest.fixture
def session(pg_engine):
    with pg_engine.connect() as connection:
        outer = connection.begin()
        # router가 오류에서 rollback해도 바깥 transaction(과 `SET LOCAL ROLE`)이 살아 있게
        # session은 savepoint 안에서만 commit/rollback한다. 검사가 끝나면 바깥을 되돌린다.
        try:
            with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as value:
                yield value
        finally:
            outer.rollback()


@pytest.fixture
def clock(monkeypatch):
    values = {"now": CREATED_AT}
    monkeypatch.setattr(opportunity_notes, "utc_now", lambda: values["now"])
    return values


@pytest.fixture
def seeded(session):
    """소유자 권한으로 사업기회를 심은 뒤 runtime `app` 역할로 바꾼다."""

    live = Opportunity(first_registered_stage="bid_notice")
    survivor = Opportunity(first_registered_stage="bid_notice")
    session.add_all([live, survivor])
    session.flush()
    merged = Opportunity(
        first_registered_stage="bid_notice",
        merged_into_opportunity_id=survivor.id,
        merged_at=CREATED_AT - timedelta(days=1),
        merge_reason="합성 병합",
    )
    session.add(merged)
    session.flush()
    session.commit()
    session.connection().exec_driver_sql("SET LOCAL ROLE app")
    # 역할 전환을 savepoint 밖으로 확정해 router의 오류 rollback이 되돌리지 않게 한다.
    session.commit()
    return {"live": live, "survivor": survivor, "merged": merged}


@contextmanager
def client_for(session):
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


def _error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_t4_create_replay_cross_actor_and_conflict_with_strict_dicts(session, seeded, clock) -> None:
    opportunity_id = seeded["live"].id
    path = f"/api/opportunities/{opportunity_id}/notes"
    request_id = uuid4()
    body = {"kind": "action", "body": "  발주처 질의 정리\n", "owner": "박담당", "request_id": str(request_id)}
    with client_for(session) as client:
        first = client.post(path, json=body, headers=KIM)
        clock["now"] = CREATED_AT + timedelta(minutes=3)
        replay = client.post(path, json=body, headers=KIM)
        conflict = client.post(path, json={**body, "owner": None}, headers=KIM)
        other_actor = client.post(path, json=body, headers=LEE)
        note = client.post(path, json={"kind": "note", "body": "메모", "request_id": str(uuid4())}, headers=KIM)

    assert first.status_code == 201, first.text
    note_id = UUID(first.json()["note_id"])
    assert first.json() == {
        "note_id": str(note_id),
        "kind": "action",
        "body": "발주처 질의 정리",
        "actor": "kim",
        "owner": "박담당",
        "created_at": "2026-10-17T01:02:03.456789Z",
        "done_at": None,
        "done_by": None,
    }
    assert (replay.status_code, replay.json()) == (200, first.json())
    _error(conflict, 409, "idempotency_conflict")
    assert other_actor.status_code == 201
    assert other_actor.json() == {
        **first.json(),
        "note_id": other_actor.json()["note_id"],
        "actor": "lee",
        "created_at": "2026-10-17T01:05:03.456789Z",
    }
    assert other_actor.json()["note_id"] != str(note_id)
    assert note.status_code == 201 and note.json()["owner"] == "kim"

    rows = session.scalars(select(OpportunityNote).order_by(OpportunityNote.created_at, OpportunityNote.kind)).all()
    assert [(row.kind, row.actor, row.owner, row.created_at) for row in rows] == [
        ("action", "kim", "박담당", CREATED_AT),
        ("action", "lee", "박담당", CREATED_AT + timedelta(minutes=3)),
        ("note", "kim", "kim", CREATED_AT + timedelta(minutes=3)),
    ]
    receipts = session.scalars(
        select(IdempotencyRecord).where(IdempotencyRecord.operation == "opportunity_note.create")
        .order_by(IdempotencyRecord.claimed_name, IdempotencyRecord.created_at)
    ).all()
    assert len(receipts) == 3
    assert {(r.aggregate_type, r.aggregate_id, r.response_status) for r in receipts} == {
        ("opportunity", str(opportunity_id), 201),
    }
    assert sorted(r.claimed_name for r in receipts if r.request_id == request_id) == ["kim", "lee"]


def test_t4_done_once_replay_note_not_action_and_errors(session, seeded, clock) -> None:
    opportunity_id = seeded["live"].id
    with client_for(session) as client:
        action = client.post(
            f"/api/opportunities/{opportunity_id}/notes",
            json={"kind": "action", "body": "제안 일정 확인", "request_id": str(uuid4())}, headers=KIM,
        ).json()
        memo = client.post(
            f"/api/opportunities/{opportunity_id}/notes",
            json={"kind": "note", "body": "메모", "request_id": str(uuid4())}, headers=KIM,
        ).json()
        path = f"/api/opportunities/{opportunity_id}/notes/{action['note_id']}/done"
        request = {"request_id": str(uuid4())}
        clock["now"] = DONE_AT
        done = client.patch(path, json=request, headers=LEE)
        clock["now"] = DONE_AT + timedelta(hours=2)
        replay = client.patch(path, json=request, headers=LEE)
        again = client.patch(path, json={"request_id": str(uuid4())}, headers=KIM)
        reused = client.patch(
            f"/api/opportunities/{opportunity_id}/notes/{memo['note_id']}/done", json=request, headers=LEE
        )
        not_action = client.patch(
            f"/api/opportunities/{opportunity_id}/notes/{memo['note_id']}/done",
            json={"request_id": str(uuid4())}, headers=KIM,
        )
        missing_actor = client.patch(path, json={"request_id": str(uuid4())})
        bad_actor = client.patch(path, json={"request_id": str(uuid4())}, headers={"X-BidOps-Actor-Name": "system"})
        merged = client.post(
            f"/api/opportunities/{seeded['merged'].id}/notes",
            json={"kind": "note", "body": "병합됨", "request_id": str(uuid4())}, headers=KIM,
        )
        absent = client.post(
            "/api/opportunities/987654/notes",
            json={"kind": "note", "body": "없음", "request_id": str(uuid4())}, headers=KIM,
        )
        unknown_note = client.patch(
            f"/api/opportunities/{opportunity_id}/notes/{uuid4()}/done", json={"request_id": str(uuid4())}, headers=KIM
        )

    expected = {**action, "done_at": "2026-10-17T04:05:06.789012Z", "done_by": "lee"}
    assert (done.status_code, done.json()) == (200, expected)
    assert (replay.status_code, replay.json()) == (200, expected)
    assert (again.status_code, again.json()) == (200, expected)
    # 종류 검사가 영수증 검사보다 먼저다: 같은 request_id를 노트(`kind=note`)에 쓰면 409 note_not_action.
    _error(reused, 409, "note_not_action")
    _error(not_action, 409, "note_not_action")
    _error(missing_actor, 400, "actor_name_required")
    _error(bad_actor, 400, "actor_name_invalid")
    _error(merged, 409, "opportunity_merged")
    _error(absent, 404, "opportunity_not_found")
    _error(unknown_note, 404, "not_found")
    row = session.get(OpportunityNote, UUID(action["note_id"]), populate_existing=True)
    assert (row.done_at, row.done_by) == (DONE_AT, "lee")
    assert session.scalar(
        select(func.count(IdempotencyRecord.id)).where(IdempotencyRecord.operation == "opportunity_note.done")
    ) == 1


def test_t4_app_role_cannot_rewrite_or_delete_a_note_body(session, seeded, clock) -> None:
    opportunity_id = seeded["live"].id
    with client_for(session) as client:
        created = client.post(
            f"/api/opportunities/{opportunity_id}/notes",
            json={"kind": "action", "body": "원래 본문", "request_id": str(uuid4())}, headers=KIM,
        ).json()
    note_id = created["note_id"]
    assert session.connection().exec_driver_sql("SELECT current_user").scalar() == "app"

    for statement in (
        "UPDATE bidops.opportunity_note SET body = '고친 본문' WHERE id = %(id)s",
        "UPDATE bidops.opportunity_note SET owner = 'lee', kind = 'note' WHERE id = %(id)s",
        "DELETE FROM bidops.opportunity_note WHERE id = %(id)s",
    ):
        with pytest.raises(DBAPIError) as error:
            with session.begin_nested():
                session.connection().exec_driver_sql(statement, {"id": note_id})
        assert getattr(error.value.orig, "sqlstate", None) == "42501"  # insufficient_privilege

    # 완료 두 열은 app 역할로 채울 수 있다(열 단위 UPDATE 권한).
    with session.begin_nested():
        session.connection().exec_driver_sql(
            "UPDATE bidops.opportunity_note SET done_at = %(at)s, done_by = 'lee' WHERE id = %(id)s",
            {"id": note_id, "at": DONE_AT},
        )
    session.connection().exec_driver_sql("RESET ROLE")
    row = session.connection().execute(
        text("SELECT body, owner, kind, done_by FROM bidops.opportunity_note WHERE id = :id"), {"id": note_id}
    ).one()
    assert tuple(row) == ("원래 본문", "kim", "action", "lee")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"kind": "memo"}, id="kind-enum"),
        pytest.param({"done_at": DONE_AT}, id="done-at-without-by"),
        pytest.param({"done_by": "kim"}, id="done-by-without-at"),
        pytest.param({"owner": None}, id="owner-not-null"),
        pytest.param({"opportunity_id": 987654}, id="opportunity-fk"),
    ],
)
def test_t4_database_rejects_check_and_not_null_violations(session, seeded, overrides) -> None:
    values = dict(opportunity_id=seeded["live"].id, kind="note", body="본문", actor="kim", owner="kim")
    values.update(overrides)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(OpportunityNote(**values))
            session.flush()
