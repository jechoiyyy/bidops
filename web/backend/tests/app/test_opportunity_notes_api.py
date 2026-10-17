"""사업기회 노트·다음 행동 REST (RL-02 spec "노트·다음 행동", T4의 SQLite 부분).

SQLite 격리 DB에서 조립 앱(lifecycle)을 띄워 실제 경로로 부른다. runtime 역할의 DB 권한
거부(본문 UPDATE)와 strict dict는 `test_opportunity_notes_api_postgres.py`가 갖는다.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_from_bytes
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.core.models import IdempotencyRecord
from app.lifecycle.models import Opportunity, OpportunityNote
from app.lifecycle.services import opportunity_notes
from app.lifecycle.services.opportunity_notes import OpportunityNoteError, complete_note, create_note
from app.main import create_app

KIM = {"X-BidOps-Actor-Name": "kim"}
LEE = {"X-BidOps-Actor-Name": "lee"}
NOTE_KEYS = {"note_id", "kind", "body", "actor", "owner", "created_at", "done_at", "done_by"}
CREATED_AT = datetime(2026, 10, 17, 1, 2, 3, 456789, tzinfo=UTC)
DONE_AT = datetime(2026, 10, 17, 4, 5, 6, 789012, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    with Session(engine, expire_on_commit=False) as value:
        yield value
    engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    """서비스 시계를 고정한다. 생성은 CREATED_AT, 완료는 DONE_AT."""

    values = {"now": CREATED_AT}
    monkeypatch.setattr(opportunity_notes, "utc_now", lambda: values["now"])
    return values


@contextmanager
def client_for(session):
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        yield client


def _opportunity(session, **values) -> Opportunity:
    row = Opportunity(first_registered_stage="bid_notice", **values)
    session.add(row)
    session.flush()
    return row


def _merged(session) -> tuple[Opportunity, Opportunity]:
    survivor = _opportunity(session)
    merged = _opportunity(session)
    merged.merged_into_opportunity_id = survivor.id
    merged.merged_at = CREATED_AT - timedelta(days=1)
    merged.merge_reason = "합성 병합"
    session.flush()
    return survivor, merged


def _body(kind="note", body="첫 줄\n둘째 줄", **extra):
    return {"kind": kind, "body": body, "request_id": str(extra.pop("request_id", uuid4())), **extra}


def _error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    payload = response.json()
    assert payload["error"]["code"] == code
    assert set(payload["error"]) == {"code", "message", "details"}


def _notes(session) -> list[OpportunityNote]:
    session.expire_all()
    return session.scalars(select(OpportunityNote).order_by(OpportunityNote.created_at, OpportunityNote.id)).all()


# --- 생성 ---------------------------------------------------------------------


def test_create_note_returns_201_note_view_and_owner_defaults_to_the_actor(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    with client_for(session) as client:
        response = client.post(
            f"/api/opportunities/{opportunity.id}/notes", json=_body(body="  메모 본문  \n"), headers=KIM
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert set(payload) == NOTE_KEYS
    (note,) = _notes(session)
    assert payload == {
        "note_id": str(note.id),
        "kind": "note",
        "body": "메모 본문",
        "actor": "kim",
        "owner": "kim",
        "created_at": "2026-10-17T01:02:03.456789Z",
        "done_at": None,
        "done_by": None,
    }
    assert (note.opportunity_id, note.body, note.owner, note.done_at, note.done_by) == (
        opportunity.id, "메모 본문", "kim", None, None,
    )


def test_create_action_keeps_the_named_owner_and_a_blank_owner_falls_back(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    with client_for(session) as client:
        named = client.post(
            f"/api/opportunities/{opportunity.id}/notes",
            json=_body(kind="action", body="발주처 질의 정리", owner=" 박담당 "), headers=KIM,
        )
        blank = client.post(
            f"/api/opportunities/{opportunity.id}/notes",
            json=_body(kind="action", body="제안 일정 확인", owner="   "), headers=KIM,
        )
    assert named.status_code == 201 and blank.status_code == 201
    assert (named.json()["kind"], named.json()["owner"], named.json()["actor"]) == ("action", "박담당", "kim")
    assert blank.json()["owner"] == "kim"


def test_create_replays_the_same_request_and_rejects_a_changed_one(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    body = _body(kind="action", body="질의 회신 확인", owner="박담당")
    with client_for(session) as client:
        first = client.post(f"/api/opportunities/{opportunity.id}/notes", json=body, headers=KIM)
        clock["now"] = CREATED_AT + timedelta(minutes=5)
        replay = client.post(f"/api/opportunities/{opportunity.id}/notes", json=body, headers=KIM)
        changed = client.post(
            f"/api/opportunities/{opportunity.id}/notes", json={**body, "body": "다른 본문"}, headers=KIM
        )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    _error(changed, 409, "idempotency_conflict")
    assert len(_notes(session)) == 1
    (receipt,) = session.scalars(select(IdempotencyRecord)).all()
    assert (receipt.operation, receipt.aggregate_type, receipt.aggregate_id, receipt.claimed_name) == (
        "opportunity_note.create", "opportunity", str(opportunity.id), "kim",
    )
    assert (receipt.request_id, receipt.response_status) == (UUID(body["request_id"]), 201)
    assert receipt.response_snapshot == first.json()


def test_same_request_id_from_another_actor_is_a_distinct_note(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    body = _body(body="같은 요청 id")
    with client_for(session) as client:
        kim = client.post(f"/api/opportunities/{opportunity.id}/notes", json=body, headers=KIM)
        lee = client.post(f"/api/opportunities/{opportunity.id}/notes", json=body, headers=LEE)
    assert (kim.status_code, lee.status_code) == (201, 201)
    assert kim.json()["note_id"] != lee.json()["note_id"]
    assert (kim.json()["actor"], lee.json()["actor"]) == ("kim", "lee")
    assert len(_notes(session)) == 2


def test_create_errors_404_409_400_and_422(session, clock) -> None:
    opportunity = _opportunity(session)
    _, merged = _merged(session)
    session.commit()
    path = f"/api/opportunities/{opportunity.id}/notes"
    with client_for(session) as client:
        _error(client.post("/api/opportunities/999999/notes", json=_body(), headers=KIM), 404, "opportunity_not_found")
        _error(client.post(f"/api/opportunities/{merged.id}/notes", json=_body(), headers=KIM), 409, "opportunity_merged")
        _error(client.post(path, json=_body()), 400, "actor_name_required")
        _error(client.post(path, json=_body(), headers={"X-BidOps-Actor-Name": "  "}), 400, "actor_name_required")
        _error(client.post(path, json=_body(), headers={"X-BidOps-Actor-Name": "system"}), 400, "actor_name_invalid")
        _error(
            client.post(path, json=_body(), headers={**KIM, "X-BidOps-Actor-Name-Format": "latin-1"}),
            400, "actor_name_invalid",
        )
        invalid = [
            _body(body=""),
            _body(body="   \n "),
            _body(body="가" * 2001),
            _body(body="널\x00문자"),
            _body(kind="memo"),
            _body(owner="x" * 129),
            _body(owner="제어\x07문자"),
            {**_body(), "extra": 1},
            {"kind": "note", "body": "request_id 없음"},
            {**_body(), "request_id": "not-a-uuid"},
            {**_body(), "body": 7},
        ]
        responses = [client.post(path, json=payload, headers=KIM) for payload in invalid]
        exact = client.post(path, json=_body(body="  " + "가" * 2000 + "  "), headers=KIM)
    for response in responses:
        assert response.status_code == 422, response.text
    assert exact.status_code == 201 and len(exact.json()["body"]) == 2000
    assert len(_notes(session)) == 1


def test_utf8_actor_header_is_decoded(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    encoded = "UTF-8''" + quote_from_bytes("김담당".encode("utf-8"), safe="")
    headers = {"X-BidOps-Actor-Name": encoded, "X-BidOps-Actor-Name-Format": "utf-8-percent-v1"}
    with client_for(session) as client:
        response = client.post(f"/api/opportunities/{opportunity.id}/notes", json=_body(kind="action"), headers=headers)
    assert response.status_code == 201
    assert (response.json()["actor"], response.json()["owner"]) == ("김담당", "김담당")


# --- 완료 ---------------------------------------------------------------------


def _create(client, opportunity_id: int, kind: str = "action", headers=KIM, **extra) -> dict:
    response = client.post(
        f"/api/opportunities/{opportunity_id}/notes", json=_body(kind=kind, body="해야 할 일", **extra), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_done_fills_the_pair_once_replays_and_stays_unchanged(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    with client_for(session) as client:
        action = _create(client, opportunity.id, owner="박담당")
        path = f"/api/opportunities/{opportunity.id}/notes/{action['note_id']}/done"
        clock["now"] = DONE_AT
        request = {"request_id": str(uuid4())}
        done = client.patch(path, json=request, headers=LEE)
        clock["now"] = DONE_AT + timedelta(hours=1)
        replay = client.patch(path, json=request, headers=LEE)
        again = client.patch(path, json={"request_id": str(uuid4())}, headers=KIM)

    assert done.status_code == 200, done.text
    assert done.json() == {
        **action,
        "done_at": "2026-10-17T04:05:06.789012Z",
        "done_by": "lee",
    }
    assert replay.status_code == 200 and replay.json() == done.json()
    # 이미 완료된 행동은 다른 사람·다른 요청이어도 바뀌지 않는다(멱등).
    assert again.status_code == 200 and again.json() == done.json()
    (note,) = _notes(session)
    assert (note.done_at, note.done_by, note.body, note.owner) == (DONE_AT, "lee", "해야 할 일", "박담당")
    receipts = session.scalars(
        select(IdempotencyRecord).where(IdempotencyRecord.operation == "opportunity_note.done")
    ).all()
    assert [(r.aggregate_type, r.aggregate_id, r.claimed_name, r.response_status) for r in receipts] == [
        ("opportunity", str(opportunity.id), "lee", 200),
    ]


def test_done_request_id_reused_for_another_note_is_a_conflict(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    request = {"request_id": str(uuid4())}
    with client_for(session) as client:
        first = _create(client, opportunity.id)
        second = _create(client, opportunity.id)
        ok = client.patch(f"/api/opportunities/{opportunity.id}/notes/{first['note_id']}/done", json=request, headers=KIM)
        reused = client.patch(
            f"/api/opportunities/{opportunity.id}/notes/{second['note_id']}/done", json=request, headers=KIM
        )
    assert ok.status_code == 200
    _error(reused, 409, "idempotency_conflict")
    assert [note.done_by for note in _notes(session)].count(None) == 1


def test_done_errors_note_not_action_404_409_400_and_422(session, clock) -> None:
    opportunity = _opportunity(session)
    other = _opportunity(session)
    session.commit()
    with client_for(session) as client:
        note = _create(client, opportunity.id, kind="note")
        action = _create(client, opportunity.id)
        foreign = _create(client, other.id)
        done = lambda opp, note_id, body=None, headers=KIM: client.patch(  # noqa: E731
            f"/api/opportunities/{opp}/notes/{note_id}/done",
            json=body if body is not None else {"request_id": str(uuid4())}, headers=headers,
        )
        _error(done(opportunity.id, note["note_id"]), 409, "note_not_action")
        _error(done(999999, action["note_id"]), 404, "opportunity_not_found")
        _error(done(opportunity.id, foreign["note_id"]), 404, "not_found")
        _error(done(opportunity.id, uuid4()), 404, "not_found")
        _error(done(opportunity.id, action["note_id"], headers={}), 400, "actor_name_required")
        _error(done(opportunity.id, action["note_id"], headers={"X-BidOps-Actor-Name": "a\x01b"}), 400, "actor_name_invalid")
        assert done(opportunity.id, action["note_id"], body={}).status_code == 422
        assert done(opportunity.id, action["note_id"], body={"request_id": "x"}).status_code == 422
        assert done(opportunity.id, action["note_id"], body={"request_id": str(uuid4()), "done_by": "x"}).status_code == 422
        assert client.patch(f"/api/opportunities/{opportunity.id}/notes/not-a-uuid/done",
                            json={"request_id": str(uuid4())}, headers=KIM).status_code == 422
        # 병합된 사업기회에는 완료도 쓸 수 없다.
        survivor_id = other.id
        merged = session.get(Opportunity, opportunity.id)
        merged.merged_into_opportunity_id = survivor_id
        merged.merged_at = CREATED_AT
        merged.merge_reason = "합성 병합"
        session.commit()
        _error(done(opportunity.id, action["note_id"]), 409, "opportunity_merged")
    assert all(note.done_at is None for note in _notes(session))


# --- 서비스·ORM 경계 -----------------------------------------------------------


def test_service_validates_inputs_without_the_router(session, clock) -> None:
    opportunity = _opportunity(session)
    session.commit()
    with pytest.raises(OpportunityNoteError) as error:
        create_note(session, opportunity.id, kind="note", body=" ", owner=None, request_id=uuid4(), actor="kim")
    assert error.value.code == "invalid_request"
    with pytest.raises(OpportunityNoteError) as error:
        create_note(session, opportunity.id, kind="note", body="본문", owner=None, request_id=uuid4(), actor=" ")
    assert error.value.code == "actor_name_required"
    with pytest.raises(OpportunityNoteError) as error:
        complete_note(session, opportunity.id, "not-a-uuid", request_id=uuid4(), actor="kim")  # type: ignore[arg-type]
    assert error.value.code == "invalid_request"


def test_orm_guard_keeps_the_body_append_only_and_completion_once(session, clock) -> None:
    opportunity = _opportunity(session)
    result = create_note(session, opportunity.id, kind="action", body="원래 본문", owner=None, request_id=uuid4(), actor="kim")
    session.commit()
    note = session.get(OpportunityNote, result.response.note_id)
    for column, value in (("body", "고친 본문"), ("owner", "다른 사람"), ("kind", "note"), ("actor", "lee")):
        setattr(note, column, value)
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()
    clock["now"] = DONE_AT
    complete_note(session, opportunity.id, note.id, request_id=uuid4(), actor="lee")
    session.commit()
    note = session.get(OpportunityNote, note.id)
    note.done_by = "kim"
    with pytest.raises(ValueError, match="once"):
        session.flush()
    session.rollback()
    note = session.get(OpportunityNote, note.id)
    session.delete(note)
    with pytest.raises(ValueError, match="append-only"):
        session.flush()
    session.rollback()
    assert session.scalar(select(func.count(OpportunityNote.id))) == 1


def test_database_rejects_the_kind_and_done_pair_checks(session) -> None:
    from sqlalchemy.exc import IntegrityError

    opportunity = _opportunity(session)
    session.commit()
    base = dict(opportunity_id=opportunity.id, kind="note", body="본문", actor="kim", owner="kim")
    for overrides in ({"kind": "memo"}, {"done_at": DONE_AT}, {"done_by": "kim"}):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(OpportunityNote(**{**base, **overrides}))
                session.flush()
        session.rollback()
