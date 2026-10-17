"""Slack Socket Mode worker (RL-01 spec "Slack" Socket Mode worker, T9).

websocket으로 실제 Slack에 붙지 않는다. Slack 공개 문서의 Socket Mode envelope 모양
(`{"envelope_id", "type": "interactive", "accepts_response_payload", "payload": {block_actions}}`)을
`slack_sdk`의 `SocketModeRequest.from_dict`로 그대로 만들어 listener에 넣고, ack는 가짜 client가
기록한다. `chat.update`는 127.0.0.1 가짜 Slack(`tests/app/slack_fake.py`)으로 `slack_sdk`의 실제
요청 경로를 탄다. DB는 격리 SQLite 파일이다(worker 역할 권한은 PostgreSQL 변형이 본다).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from slack_sdk.socket_mode.request import SocketModeRequest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import init_db
from app.core.models import IdempotencyRecord
from app.core.slack import SlackSender
from app.lifecycle import slack_worker
from app.lifecycle.models import BriefingItem, BriefingReactionEvent, Opportunity
from app.lifecycle.services.briefing import build_briefing, react_to_item
from app.lifecycle.services.briefing_slack import SLACK_PAYLOAD_KEYS, send_briefing
from app.lifecycle.slack_worker import (
    CONFLICT_NOTE,
    SLACK_REACTION_NS,
    SlackReactionHandler,
)
from tests.app.slack_fake import FakeSlack
from tests.lifecycle.briefing_fixtures import BRIEFING_DATE, NOW, FakeOrderPlans, World, register_providers

BOT_TOKEN = "xoxb-000000000000-fixture-bot-secret-7f3a"
APP_TOKEN = "xapp-1-A0FIXTURE-fixture-app-secret-91c2"
VERIFICATION_TOKEN = "fixture-verification-token-5d1e"
CHANNEL = "C0FIXTURE"
REACTED_AT = datetime(2026, 10, 15, 23, 10, tzinfo=UTC)
TRIGGER = "13345224609.738474920.8088930838d88f008e0"


def _walk_keys(value, keys: set[str]) -> set[str]:
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            _walk_keys(item, keys)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item, keys)
    return keys


def envelope(
    item_id: UUID | str,
    reaction: str,
    *,
    message_ts: str,
    trigger_id: str = TRIGGER,
    action_id: str = "briefing_react",
    username: str | None = "kim",
    name: str = "kim.real",
    channel: str = CHANNEL,
    envelope_id: str = "57d6a792-4d35-4d0b-b6aa-3361493e1caf",
) -> dict:
    """Slack Socket Mode `interactive` envelope(block_actions, 메시지 버튼 클릭)."""

    user = {"id": "U0FIXTURE", "name": name, "team_id": "T0FIXTURE"}
    if username is not None:
        user["username"] = username
    return {
        "envelope_id": envelope_id,
        "type": "interactive",
        "accepts_response_payload": False,
        "payload": {
            "type": "block_actions",
            "user": user,
            "api_app_id": "A0FIXTURE",
            "token": VERIFICATION_TOKEN,
            "container": {"type": "message", "message_ts": message_ts, "channel_id": channel, "is_ephemeral": False},
            "trigger_id": trigger_id,
            "team": {"id": "T0FIXTURE", "domain": "fixture"},
            "enterprise": None,
            "is_enterprise_install": False,
            "channel": {"id": channel, "name": "bidops-briefing"},
            "message": {"type": "message", "subtype": "bot_message", "ts": message_ts, "bot_id": "B0FIXTURE",
                        "text": "오늘의 브리핑", "blocks": []},
            "state": {"values": {}},
            "response_url": "https://hooks.slack.com/actions/T0FIXTURE/1/fixture",
            "actions": [
                {
                    "action_id": action_id,
                    "block_id": "Ab1c",
                    "text": {"type": "plain_text", "text": "볼게요", "emoji": True},
                    "value": f"{item_id}:{reaction}",
                    "style": "primary",
                    "type": "button",
                    "action_ts": "1760573000.123456",
                }
            ],
        },
    }


class FakeSocketClient:
    """ack만 기록한다(실제 websocket 없음)."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.responses: list[dict] = []

    def send_socket_mode_response(self, response) -> None:
        self.responses.append(response)
        self.events.append("ack")


@pytest.fixture
def fake():
    server = FakeSlack(bot_token=BOT_TOKEN, channel=CHANNEL, app_token=APP_TOKEN).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def world(tmp_path, empty_extensions, monkeypatch, fake):
    for name in ("BIDOPS_BRIEFING_POLICY_PATH", "BIDOPS_SLACK_CHANNEL_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BIDOPS_PUBLIC_BASE_URL", "https://bidops.example.invalid")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    init_db(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    plans = FakeOrderPlans()
    register_providers(empty_extensions, plans=plans)
    sender = SlackSender.from_settings(
        Settings(
            _env_file=None,
            BIDOPS_SLACK_ENABLED=True,
            BIDOPS_SLACK_BOT_TOKEN=BOT_TOKEN,
            BIDOPS_SLACK_APP_TOKEN=APP_TOKEN,
            BIDOPS_SLACK_CHANNEL_ID=CHANNEL,
            BIDOPS_SLACK_ALLOWED_HOSTS="127.0.0.1",
        ),
        base_url=fake.base_url,
    )
    with factory() as session:
        seed = World(session)
        seed.collection_run()
        pre_spec = seed.notice("홈페이지 유지관리 용역", deadline_at=NOW + timedelta(days=3), agency="대구광역시")
        bid = seed.notice("데이터 플랫폼 구축", source_type="bid_notice", sw=None,
                          deadline_at=NOW + timedelta(days=20), agency="경상북도")
        session.commit()
        assert build_briefing(session, BRIEFING_DATE, now=NOW).item_count == 2
        session.commit()
        outcome = send_briefing(session, BRIEFING_DATE, sender, now=NOW)
        session.commit()
        assert outcome.sent is True
        items = {
            row.notice_id: row.id for row in session.scalars(select(BriefingItem))
        }
    events: list[str] = []
    original_update = sender.update_message

    def recording_update(**kwargs):
        events.append("chat.update")
        return original_update(**kwargs)

    sender.update_message = recording_update  # type: ignore[method-assign]
    handler = SlackReactionHandler(sender, factory, clock=lambda: REACTED_AT)
    try:
        yield {
            "factory": factory, "fake": fake, "sender": sender, "handler": handler, "events": events,
            "client": FakeSocketClient(events), "ts": outcome.message_ts[0],
            "pre_spec": items[pre_spec.id], "bid": items[bid.id],
        }
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.fixture
def counted(monkeypatch, world):
    """저장 직전 revision 조회와 service 호출을 사건 목록에 남긴다(ack 순서·재조회 횟수)."""

    reads: list[UUID] = []
    real_read = slack_worker.current_revision
    real_react = slack_worker.react_to_item

    def read(session, item_id):
        reads.append(item_id)
        world["events"].append("read")
        return real_read(session, item_id)

    def react(session, **kwargs):
        world["events"].append("react")
        return real_react(session, **kwargs)

    monkeypatch.setattr(slack_worker, "current_revision", read)
    monkeypatch.setattr(slack_worker, "react_to_item", react)
    return reads


def _deliver(world, raw: dict) -> None:
    request = SocketModeRequest.from_dict(raw)
    assert request is not None
    world["handler"](world["client"], request)


def _item(world, item_id) -> BriefingItem:
    with world["factory"]() as session:
        return session.get(BriefingItem, item_id)


def _events(world, item_id) -> list[BriefingReactionEvent]:
    with world["factory"]() as session:
        return list(
            session.scalars(
                select(BriefingReactionEvent)
                .where(BriefingReactionEvent.item_id == item_id)
                .order_by(BriefingReactionEvent.revision)
            )
        )


def _update_blocks(world, index: int = -1) -> list[dict]:
    return world["fake"].calls("chat.update")[index].body["blocks"]


def _item_lines(blocks: list[dict], item_id) -> list[str]:
    """그 항목의 버튼 값 줄과 그 바로 앞 context 문구를 돌려준다."""

    lines: list[str] = []
    for index, block in enumerate(blocks):
        if block["type"] != "actions":
            continue
        values = [element["value"] for element in block["elements"]]
        if not all(value.startswith(f"{item_id}:") for value in values):
            continue
        previous = blocks[index - 1]
        if previous["type"] == "context":
            lines.extend(element["text"] for element in previous["elements"])
        lines.extend(values)
    return lines


def test_namespace_is_the_spec_constant() -> None:
    assert SLACK_REACTION_NS == uuid5(NAMESPACE_URL, "bidops:slack-reaction")


def test_block_action_acks_first_saves_once_and_updates_the_message(world, counted, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    item_id = world["pre_spec"]
    _deliver(world, envelope(item_id, "채택", message_ts=world["ts"]))

    # ack가 조회·저장·갱신보다 먼저다.
    assert world["events"] == ["ack", "read", "react", "chat.update"]
    assert world["client"].responses == [{"envelope_id": "57d6a792-4d35-4d0b-b6aa-3361493e1caf"}]
    item = _item(world, item_id)
    assert (item.reaction, item.reacted_by, item.reacted_via, item.revision) == ("채택", "kim", "slack", 1)
    assert item.reacted_at == REACTED_AT
    (event,) = _events(world, item_id)
    assert (event.previous, event.new, event.actor, event.via) == ("대기", "채택", "kim", "slack")
    assert event.request_id == uuid5(SLACK_REACTION_NS, TRIGGER)
    with world["factory"]() as session:
        assert session.scalar(select(func.count(IdempotencyRecord.id))) == 1
        # 반응은 추적 상태를 바꾸지 않는다.
        assert {row.tracking_status for row in session.scalars(select(Opportunity))} == {"미선택"}

    calls = world["fake"].calls()
    assert [call.method for call in calls] == ["chat.postMessage", "chat.update"]  # users.info 없음
    update = calls[-1]
    assert update.authorization == f"Bearer {BOT_TOKEN}"
    assert set(update.body) == {"channel", "ts", "blocks", "text"}
    assert (update.body["channel"], update.body["ts"]) == (CHANNEL, world["ts"])
    blocks = update.body["blocks"]
    assert _walk_keys(blocks, set()) <= SLACK_PAYLOAD_KEYS
    assert _item_lines(blocks, item_id) == ["✓ kim이 볼게요", f"{item_id}:대기"]
    undo = next(
        element for block in blocks if block["type"] == "actions" for element in block["elements"]
        if element["value"] == f"{item_id}:대기"
    )
    assert (undo["text"]["text"], undo["action_id"]) == ("되돌리기", "briefing_react")
    # 같은 메시지의 다른 항목은 버튼 그대로다.
    other = world["bid"]
    assert _item_lines(blocks, other)[-2:] == [f"{other}:채택", f"{other}:무시"]
    for secret in (BOT_TOKEN, APP_TOKEN, VERIFICATION_TOKEN, "kim.real"):
        assert secret not in caplog.text


def test_username_falls_back_to_name_and_undo_restores_the_buttons(world, counted) -> None:
    item_id = world["pre_spec"]
    _deliver(world, envelope(item_id, "무시", message_ts=world["ts"], username=None, name="lee"))
    assert _item(world, item_id).reacted_by == "lee"
    assert _item_lines(_update_blocks(world), item_id) == ["✓ lee이 무시", f"{item_id}:대기"]

    _deliver(world, envelope(item_id, "대기", message_ts=world["ts"], username=None, name="lee",
                             trigger_id="13345224609.738474920.second", envelope_id="env-2"))

    item = _item(world, item_id)
    assert (item.reaction, item.revision) == ("대기", 2)
    assert [(event.previous, event.new) for event in _events(world, item_id)] == [("대기", "무시"), ("무시", "대기")]
    assert _item_lines(_update_blocks(world), item_id)[-2:] == [f"{item_id}:채택", f"{item_id}:무시"]
    assert len(world["fake"].calls("chat.update")) == 2


def test_duplicate_delivery_is_one_reaction_and_one_update(world, counted) -> None:
    item_id = world["pre_spec"]
    raw = envelope(item_id, "채택", message_ts=world["ts"])

    _deliver(world, raw)
    _deliver(world, raw)  # Slack 재전달: 같은 envelope·같은 trigger

    assert world["events"].count("ack") == 2
    assert len(_events(world, item_id)) == 1
    assert _item(world, item_id).revision == 1
    assert len(world["fake"].calls("chat.update")) == 1


def test_duplicate_delivery_read_before_the_first_commit_replays(world, monkeypatch) -> None:
    """두 전달이 같은 revision을 읽었으면 같은 요청이라 저장 snapshot 재생이다(갱신 없음)."""

    item_id = world["pre_spec"]
    monkeypatch.setattr(slack_worker, "current_revision", lambda session, target: 0)
    raw = envelope(item_id, "채택", message_ts=world["ts"])

    _deliver(world, raw)
    first = world["handler"].handle_payload(raw["payload"])

    assert first.status == "replayed" and first.updated is False
    assert len(_events(world, item_id)) == 1
    assert len(world["fake"].calls("chat.update")) == 1


def test_other_action_ids_and_envelopes_are_ignored_with_an_audit_line(world, counted, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.lifecycle.slack_worker")
    item_id = world["pre_spec"]

    _deliver(world, envelope(item_id, "채택", message_ts=world["ts"], action_id="other_action"))
    _deliver(world, envelope(item_id, "나중에", message_ts=world["ts"], envelope_id="env-later"))
    _deliver(world, envelope(item_id, "채택", message_ts=world["ts"], channel="C0OTHER", envelope_id="env-chan"))
    _deliver(world, envelope("not-a-uuid", "채택", message_ts=world["ts"], envelope_id="env-bad"))
    events_api = {"envelope_id": "env-events", "type": "events_api", "accepts_response_payload": False,
                  "payload": {"type": "event_callback", "token": VERIFICATION_TOKEN}}
    _deliver(world, events_api)

    assert world["events"] == ["ack"] * 5  # 모두 ack만 하고 조회·저장·갱신 없음
    assert counted == []
    assert _events(world, item_id) == []
    assert world["fake"].calls("chat.update") == []
    audits = [
        (record.bidops.get("event"), record.bidops.get("error_code"))
        for record in caplog.records
        if record.name == "app.lifecycle.slack_worker"
    ]
    assert audits == [
        ("slack_worker.action_ignored", "unknown_action"),
        ("slack_worker.action_ignored", "value_invalid"),
        ("slack_worker.action_ignored", "channel_not_allowed"),
        ("slack_worker.action_ignored", "value_invalid"),
        ("slack_worker.envelope_ignored", "not_interactive"),
    ]
    for secret in (BOT_TOKEN, APP_TOKEN, VERIFICATION_TOKEN, "kim", str(item_id)):
        assert secret not in caplog.text


def _screen(world, item_id, reaction: str, actor: str) -> None:
    with world["factory"]() as session:
        current = session.get(BriefingItem, item_id).revision
        react_to_item(session, item_id=item_id, reaction=reaction, expected_revision=current,
                      request_id=uuid4(), actor=actor, via="screen")
        session.commit()


def test_screen_race_conflict_rereads_once_and_retry_succeeds(world, counted, monkeypatch) -> None:
    item_id = world["pre_spec"]
    real = slack_worker.react_to_item
    calls = {"count": 0}

    def racing(session, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            _screen(world, item_id, "무시", "lee")  # 조회 뒤·저장 전 화면이 먼저 누른다
        return real(session, **kwargs)

    monkeypatch.setattr(slack_worker, "react_to_item", racing)

    _deliver(world, envelope(item_id, "채택", message_ts=world["ts"]))

    assert counted == [item_id, item_id]  # 409 뒤 재조회 1회
    assert calls["count"] == 2
    item = _item(world, item_id)
    assert (item.reaction, item.reacted_via, item.revision) == ("채택", "slack", 2)
    assert [(event.via, event.new) for event in _events(world, item_id)] == [("screen", "무시"), ("slack", "채택")]
    blocks = _update_blocks(world)
    assert _item_lines(blocks, item_id) == ["✓ kim이 볼게요", f"{item_id}:대기"]
    assert CONFLICT_NOTE not in str(blocks)
    assert len(world["fake"].calls("chat.update")) == 1


def test_second_conflict_shows_the_screen_reacted_first_note(world, counted, monkeypatch) -> None:
    item_id = world["pre_spec"]
    real = slack_worker.react_to_item
    screen_reactions = iter([("무시", "lee"), ("나중에", "park")])

    def racing(session, **kwargs):
        reaction, actor = next(screen_reactions)
        _screen(world, item_id, reaction, actor)
        return real(session, **kwargs)

    monkeypatch.setattr(slack_worker, "react_to_item", racing)

    result_raw = envelope(item_id, "채택", message_ts=world["ts"])
    _deliver(world, result_raw)

    assert counted == [item_id, item_id]  # 재시도는 1회뿐
    item = _item(world, item_id)
    assert (item.reaction, item.reacted_by, item.reacted_via, item.revision) == ("나중에", "park", "screen", 2)
    assert [event.via for event in _events(world, item_id)] == ["screen", "screen"]
    (update,) = world["fake"].calls("chat.update")
    lines = _item_lines(update.body["blocks"], item_id)
    # 화면 반응을 그대로 보이고 그 위에 "화면에서 먼저 반응했습니다"를 단다.
    assert lines == ["✓ park이 나중에", f"{item_id}:대기"]
    contexts = [element["text"] for block in update.body["blocks"] if block["type"] == "context"
                for element in block["elements"]]
    assert CONFLICT_NOTE in contexts


def test_a_message_this_briefing_never_sent_is_not_updated(world, counted) -> None:
    item_id = world["pre_spec"]
    _deliver(world, envelope(item_id, "채택", message_ts="1760572800.999999"))

    assert _item(world, item_id).reaction == "채택"  # 클릭은 기록한다
    assert world["fake"].calls("chat.update") == []


def test_worker_exits_without_connecting_when_disabled_or_misconfigured(monkeypatch, fake) -> None:
    import app.core.logging_setup as logging_setup

    monkeypatch.setattr(logging_setup, "configure", lambda settings=None: None)
    disabled = SlackSender.from_settings(Settings(_env_file=None), base_url=fake.base_url)
    assert slack_worker.run_slack_worker(sender=disabled, session_factory=lambda: None) == 0
    missing_app = SlackSender.from_settings(
        Settings(_env_file=None, BIDOPS_SLACK_ENABLED=True, BIDOPS_SLACK_BOT_TOKEN=BOT_TOKEN,
                 BIDOPS_SLACK_CHANNEL_ID=CHANNEL, BIDOPS_SLACK_ALLOWED_HOSTS="127.0.0.1"),
        base_url=fake.base_url,
    )
    assert slack_worker.run_slack_worker(sender=missing_app, session_factory=lambda: None) == 1
    assert fake.requests == []


def test_reaction_line_uses_the_korean_subject_particle() -> None:
    from app.lifecycle.services.briefing_slack import subject_particle

    assert subject_particle("최담당") == "이"  # 받침 있음
    assert subject_particle("김다희") == "가"  # 받침 없음
    assert subject_particle("kim") == "이"  # 한글이 아니면 spec 문구 그대로
