"""Slack 전송기·`build-briefing --send` (RL-01 spec "CLI·호스트 스크립트" `--send`, "Slack", T8).

실제 Slack은 부르지 않는다. 127.0.0.1의 가짜 Slack(`tests/app/slack_fake.py`)에 `slack_sdk`의
실제 요청 경로를 태우고, CLI는 운영과 같은 설정(`BIDOPS_SLACK_*` 환경 변수 → `get_settings`)
으로 전송기를 만든다. 기준 주소만 코드 상수(`app.core.slack.SLACK_API_BASE_URL`)를 가짜로
바꾼다 — spec 설정 키 표에 기준 주소 키가 없어서다.

검사하는 것:
- 호출 전 검사 순서와 0회 호출: 꺼짐·bot token 없음·채널 없음·허용 밖 host·주말·0건·이미 보냄
- 성공 전송이 ts를 보낸 순서대로 남기고 두 번째 `--send`는 아무것도 보내지 않음
- 메시지당 항목 상한을 넘으면 같은 헤더로 나눔
- 실패는 `slack_send_failed` 경고, 브리핑 유지, 재실행은 남은 메시지만 보냄
- 토큰이 응답·출력·예외·로그 어디에도 없음, payload 키 허용 목록, 다른 채널 갱신 거부,
  Socket Mode websocket 주소의 host 검사
"""

from __future__ import annotations

from datetime import timedelta
import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker

import app.core.slack as slack_module
from app.core.config import Settings, get_settings
from app.core.db import init_db
from app.core.slack import (
    SlackSender,
    SlackSettings,
    SlackTransportError,
    parse_allowed_hosts,
    url_host_allowed,
)
from app.lifecycle.cli import SKIPPED_REASONS, build_briefing_command, build_parser
from app.lifecycle.models import Briefing, BriefingItem
from app.lifecycle.services.briefing import get_briefing_view
from app.lifecycle.services.briefing_policy import load_briefing_policy
from app.lifecycle.services.briefing_slack import SLACK_PAYLOAD_KEYS, build_briefing_messages
from tests.app.slack_fake import FakeSlack
from tests.lifecycle.briefing_fixtures import BRIEFING_DATE, NOW, SATURDAY, FakeOrderPlans, World, register_providers

BOT_TOKEN = "xoxb-000000000000-fixture-bot-secret-7f3a"
APP_TOKEN = "xapp-1-A0FIXTURE-fixture-app-secret-91c2"
SECRET_MARKERS = (BOT_TOKEN, APP_TOKEN, "fixture-bot-secret-7f3a", "fixture-app-secret-91c2")
CHANNEL = "C0FIXTURE"
BASE = "https://bidops.example.invalid"
POLICY_DIR = Path(__file__).resolve().parents[2] / "app/lifecycle/policies"


def _walk_keys(value, keys: set[str]) -> set[str]:
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            _walk_keys(item, keys)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item, keys)
    return keys


def _assert_no_secret(*values) -> None:
    for value in values:
        rendered = value if isinstance(value, str) else repr(value)
        for marker in SECRET_MARKERS:
            assert marker not in rendered


@pytest.fixture
def fake():
    server = FakeSlack(bot_token=BOT_TOKEN, channel=CHANNEL, app_token=APP_TOKEN).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def database(tmp_path, empty_extensions):
    engine = create_engine(f"sqlite:///{tmp_path / 'briefing.db'}")
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    plans = FakeOrderPlans()
    register_providers(empty_extensions, plans=plans)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory, plans
    finally:
        engine.dispose()


@pytest.fixture
def slack_env(monkeypatch, fake):
    """운영과 같은 설정 경로. 기본은 전송 가능한 값이고 검사마다 하나씩 뺀다."""

    for name in (
        "BIDOPS_SLACK_ENABLED", "BIDOPS_SLACK_BOT_TOKEN", "BIDOPS_SLACK_APP_TOKEN", "BIDOPS_SLACK_CHANNEL_ID",
        "BIDOPS_SLACK_ALLOWED_HOSTS", "BIDOPS_PUBLIC_BASE_URL", "BIDOPS_BRIEFING_POLICY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BIDOPS_SLACK_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_SLACK_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("BIDOPS_SLACK_APP_TOKEN", APP_TOKEN)
    monkeypatch.setenv("BIDOPS_SLACK_CHANNEL_ID", CHANNEL)
    monkeypatch.setenv("BIDOPS_SLACK_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("BIDOPS_PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(slack_module, "SLACK_API_BASE_URL", fake.base_url)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _set(monkeypatch, **values: str | None) -> None:
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def _seed(factory, plans) -> dict:
    """추천 3건(사전규격·입찰공고·발주계획)과 추적 변화 1건."""

    with factory() as session:
        world = World(session)
        world.collection_run()
        world.notice("홈페이지 유지관리 용역", deadline_at=NOW + timedelta(days=3),
                     estimated_price=2_500_000_000, agency="대구광역시")
        world.notice("데이터 플랫폼 구축", source_type="bid_notice", sw=None,
                     deadline_at=NOW + timedelta(days=20), agency="경상북도")
        plan = world.plan("스마트 관광 플랫폼 고도화 용역 3차")
        plans.ids = [plan.id]
        tracked_owner = world.opportunity(tracking_status="계속 추적")
        tracked = world.notice("추적 중 통합 시스템", owner=tracked_owner, observed_at=NOW - timedelta(days=10),
                               deadline_at=NOW + timedelta(days=12))
        world.observe(tracked, NOW - timedelta(hours=1), ["deadline_at"])
        session.commit()
    return {}


def _cli(factory, capsys, *args: str) -> tuple[int, dict, str]:
    parsed = build_parser().parse_args(["build-briefing", *args, "--json"])
    code = build_briefing_command(parsed, now=NOW, session_factory=factory)
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1, captured.out
    return code, json.loads(lines[0]), captured.out + captured.err


def _briefing(factory) -> Briefing:
    with factory() as session:
        return session.scalars(select(Briefing)).one()


def _item_ts(factory) -> dict[str, list[str | None]]:
    """항목별 `slack_message_ts`(RL-03 추가형 열). 추천은 순위 순, 추적 변화는 공고 순."""

    with factory() as session:
        rows = session.scalars(
            select(BriefingItem).order_by(BriefingItem.kind, BriefingItem.rank, BriefingItem.notice_id)
        ).all()
    out: dict[str, list[str | None]] = {"recommendation": [], "tracked_change": []}
    for row in rows:
        out[row.kind].append(row.slack_message_ts)
    return out


# --- 전송기 단위 검사 ------------------------------------------------------------


@pytest.mark.parametrize(
    "url, allowed, ok",
    [
        ("https://slack.com/api/", ("slack.com",), True),
        ("https://SLACK.com/api/", ("slack.com",), True),
        ("https://evil.slack.com/api/", ("slack.com",), False),
        ("https://slack.com.evil.example/api/", ("slack.com",), False),
        ("https://user:pw@slack.com/api/", ("slack.com",), False),
        ("http://slack.com/api/", ("slack.com",), False),
        ("https://hooks.slack.com/actions/x", ("slack.com", "wss-primary.slack.com"), False),
        ("http://127.0.0.1:9/api/", ("127.0.0.1",), True),
        ("http://127.0.0.1:9/api/", ("slack.com",), False),
        ("https://slack.com/api/", (), False),
    ],
)
def test_url_host_allowlist_is_exact_and_https_only_outside_loopback(url, allowed, ok) -> None:
    assert url_host_allowed(url, allowed, secure_scheme="https") is ok


def test_allowed_hosts_default_and_parse() -> None:
    settings = Settings(_env_file=None)
    assert settings.slack_enabled is False
    assert parse_allowed_hosts(settings.slack_allowed_hosts) == ("slack.com", "wss-primary.slack.com")
    assert parse_allowed_hosts(" Slack.com, ,wss-primary.slack.com.,slack.com") == (
        "slack.com", "wss-primary.slack.com",
    )
    assert parse_allowed_hosts("") == ()


def _sender(fake, **overrides) -> SlackSender:
    values = dict(
        enabled=True, bot_token=BOT_TOKEN, app_token=APP_TOKEN, channel_id=CHANNEL, allowed_hosts="127.0.0.1",
    )
    values.update(overrides)
    settings = Settings(
        _env_file=None,
        BIDOPS_SLACK_ENABLED=values["enabled"],
        BIDOPS_SLACK_BOT_TOKEN=values["bot_token"],
        BIDOPS_SLACK_APP_TOKEN=values["app_token"],
        BIDOPS_SLACK_CHANNEL_ID=values["channel_id"],
        BIDOPS_SLACK_ALLOWED_HOSTS=values["allowed_hosts"],
    )
    return SlackSender.from_settings(settings, base_url=values.get("base_url", fake.base_url))


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"enabled": False}, "slack_disabled"),
        ({"bot_token": ""}, "token_missing"),
        ({"bot_token": "   "}, "token_missing"),
        ({"channel_id": ""}, "channel_missing"),
        ({"allowed_hosts": "slack.com,wss-primary.slack.com"}, "host_not_allowed"),
        ({"allowed_hosts": ""}, "host_not_allowed"),
    ],
)
def test_sender_checks_before_any_call(fake, overrides, reason) -> None:
    sender = _sender(fake, **overrides)
    assert sender.preflight() == reason
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}]
    with pytest.raises(SlackTransportError) as raised:
        sender.post_message(blocks=blocks, text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    assert raised.value.code == reason
    with pytest.raises(SlackTransportError):
        sender.update_message(channel=CHANNEL, ts="1.1", blocks=blocks, text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    # RL-03 스레드 답글도 같은 검사를 먼저 지난다.
    with pytest.raises(SlackTransportError) as reply:
        sender.post_thread_reply(channel=CHANNEL, thread_ts="1.1", text="x")
    assert reply.value.code == reason
    assert fake.requests == []


def test_socket_mode_needs_the_app_token_before_any_call(fake) -> None:
    sender = _sender(fake, app_token="")
    assert sender.preflight() is None
    assert sender.preflight(require_app_token=True) == "token_missing"
    with pytest.raises(SlackTransportError) as raised:
        sender.socket_mode_client(lambda client, request: None)
    assert raised.value.code == "token_missing"
    assert fake.requests == []


def test_socket_mode_refuses_a_websocket_host_outside_the_allowlist(fake) -> None:
    fake.wss_url = "wss://wss-primary.slack.com.evil.example/link/?ticket=fixture-ticket"
    sender = _sender(fake)
    client = sender.socket_mode_client(lambda client, request: None)
    try:
        with pytest.raises(SlackTransportError) as raised:
            client.connect()
    finally:
        client.close()
    assert raised.value.code == "host_not_allowed"
    calls = fake.calls()
    # apps.connections.open만 app token으로 불렀고 websocket에는 닿지 않았다.
    assert [call.method for call in calls] == ["apps.connections.open"]
    assert calls[0].authorization == f"Bearer {APP_TOKEN}"
    assert "token" not in calls[0].body
    _assert_no_secret(raised.value, str(raised.value))


def test_payload_with_a_key_outside_the_allowlist_is_refused_before_the_call(fake) -> None:
    sender = _sender(fake)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "x"},
               "accessory": {"type": "image", "image_url": "https://x"}}]
    with pytest.raises(SlackTransportError) as raised:
        sender.post_message(blocks=blocks, text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    assert raised.value.code == "payload_key_not_allowed"
    assert fake.requests == []


def test_update_to_another_channel_is_refused_before_the_call(fake) -> None:
    sender = _sender(fake)
    with pytest.raises(SlackTransportError) as raised:
        sender.update_message(channel="C0OTHER", ts="1.1", blocks=[], text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    assert raised.value.code == "channel_not_allowed"
    assert fake.requests == []


def test_thread_reply_posts_one_line_into_the_thread_of_a_sent_message(fake, caplog) -> None:
    """RL-03 `post_thread_reply`: 설정 채널·`thread_ts`·텍스트만 보내고 답글 ts를 돌려준다."""

    caplog.set_level(logging.DEBUG)
    sender = _sender(fake)
    parent = sender.post_message(
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}], text="x",
        allowed_keys=SLACK_PAYLOAD_KEYS,
    )

    reply_ts = sender.post_thread_reply(channel=CHANNEL, thread_ts=parent, text="판정 완료 · 조건부 진행 · 확인할 것 2")

    call = fake.calls("chat.postMessage")[-1]
    assert set(call.body) == {"channel", "thread_ts", "text"}
    assert call.body == {"channel": CHANNEL, "thread_ts": parent, "text": "판정 완료 · 조건부 진행 · 확인할 것 2"}
    assert call.authorization == f"Bearer {BOT_TOKEN}" and "token" not in call.body
    assert reply_ts in fake.posted and reply_ts != parent
    _assert_no_secret(caplog.text, call.raw)


@pytest.mark.parametrize(
    "channel, thread_ts, text, code",
    [
        ("C0OTHER", "1.1", "x", "channel_not_allowed"),
        (CHANNEL, "", "x", "payload_invalid"),
        (CHANNEL, "  ", "x", "payload_invalid"),
        (CHANNEL, None, "x", "payload_invalid"),
        (CHANNEL, "1.1", "", "payload_invalid"),
    ],
)
def test_thread_reply_to_another_channel_or_without_ts_is_refused_before_the_call(
    fake, channel, thread_ts, text, code
) -> None:
    with pytest.raises(SlackTransportError) as raised:
        _sender(fake).post_thread_reply(channel=channel, thread_ts=thread_ts, text=text)
    assert raised.value.code == code
    assert fake.requests == []


def test_token_never_appears_in_errors_reprs_or_logs(fake, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("slack_sdk", "app.core.slack.sdk", "app.core.slack.socket"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    wrong = _sender(fake, bot_token=BOT_TOKEN + "-wrong")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}]
    with pytest.raises(SlackTransportError) as rejected:
        wrong.post_message(blocks=blocks, text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    assert rejected.value.code == "slack_api_error:invalid_auth"
    # 서버가 끊긴 경우(연결 거부)도 안전한 code뿐이다.
    unreachable = _sender(fake, base_url="http://127.0.0.1:9/api/")
    with pytest.raises(SlackTransportError) as refused:
        unreachable.post_message(blocks=blocks, text="x", allowed_keys=SLACK_PAYLOAD_KEYS)
    assert refused.value.code == "slack_transport_error"
    for error in (rejected.value, refused.value):
        assert error.__cause__ is None and error.__context__ is None
        _assert_no_secret(str(error), repr(error), error.args)
    sender = _sender(fake)
    settings = Settings(_env_file=None, BIDOPS_SLACK_BOT_TOKEN=BOT_TOKEN, BIDOPS_SLACK_APP_TOKEN=APP_TOKEN)
    _assert_no_secret(
        repr(sender), str(sender), repr(SlackSettings.from_settings(settings)), repr(settings),
        settings.model_dump_json(),
    )
    # 실제 요청은 헤더로만 토큰을 실었다(본문·query 없음).
    assert fake.calls("chat.postMessage")[0].authorization == f"Bearer {BOT_TOKEN}-wrong"
    assert all("token" not in call.body and BOT_TOKEN not in call.raw for call in fake.requests)
    _assert_no_secret(caplog.text, *(record.getMessage() for record in caplog.records))


# --- `build-briefing --send` ---------------------------------------------------


@pytest.mark.parametrize(
    "env, reason",
    [
        ({"BIDOPS_SLACK_ENABLED": None}, "slack_disabled"),
        ({"BIDOPS_SLACK_ENABLED": "false"}, "slack_disabled"),
        ({"BIDOPS_SLACK_BOT_TOKEN": None}, "token_missing"),
        ({"BIDOPS_SLACK_CHANNEL_ID": ""}, "channel_missing"),
        ({"BIDOPS_SLACK_ALLOWED_HOSTS": None}, "host_not_allowed"),
        ({"BIDOPS_SLACK_ALLOWED_HOSTS": "slack.com"}, "host_not_allowed"),
    ],
)
def test_send_is_skipped_before_any_call(database, slack_env, fake, capsys, env, reason) -> None:
    factory, plans = database
    _seed(factory, plans)
    _set(slack_env, **env)

    code, output, printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0
    assert (output["status"], output["created"]) == ("generated", True)
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": reason}
    assert "slack_send_failed" not in output["warnings"]
    assert fake.requests == []
    assert _briefing(factory).slack_sent_at is None
    _assert_no_secret(printed)


def test_weekend_send_touches_neither_db_nor_slack(database, slack_env, fake, capsys) -> None:
    factory, plans = database
    _seed(factory, plans)

    code, output, _printed = _cli(factory, capsys, "--date", SATURDAY.isoformat(), "--send")

    assert code == 0
    assert (output["status"], output["created"]) == (None, False)
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": "weekend"}
    assert fake.requests == []
    with factory() as session:
        assert session.scalars(select(Briefing)).all() == []


def test_empty_briefing_sends_nothing(database, slack_env, fake, capsys) -> None:
    factory, _plans = database
    with factory() as session:
        world = World(session)
        world.collection_run()
        world.notice("하드웨어 장비 구매")
        session.commit()

    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0
    assert output["status"] == "empty"
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": "empty"}
    assert fake.requests == []
    assert _briefing(factory).slack_sent_at is None


def test_dry_run_send_and_generation_failure_send_nothing(database, slack_env, fake, capsys, empty_extensions) -> None:
    factory, plans = database
    _seed(factory, plans)
    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send", "--dry-run")
    assert (code, output["slack"]["skipped_reason"]) == (0, "dry_run")

    # 회사 사실 제공자가 없으면 생성 실패(exit 1, 행 없음) — 보낼 것이 없다.
    from app.lifecycle import reset_extension_registry

    reset_extension_registry()
    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")
    assert code == 1
    assert output["warnings"] == ["company_not_registered"]
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": "empty"}
    _set(slack_env, BIDOPS_SLACK_ENABLED="false")
    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")
    assert (code, output["slack"]["skipped_reason"]) == (1, "slack_disabled")
    assert fake.requests == []


def test_send_persists_ts_in_send_order_and_a_second_send_sends_nothing(database, slack_env, fake, capsys) -> None:
    factory, plans = database
    _seed(factory, plans)

    code, output, printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0
    calls = fake.calls()
    assert [call.method for call in calls] == ["chat.postMessage", "chat.postMessage"]
    for call in calls:
        assert call.authorization == f"Bearer {BOT_TOKEN}"
        # 전송 본문은 채널·블록·대체 텍스트뿐이고 블록은 허용 키만 쓴다.
        assert set(call.body) == {"channel", "blocks", "text"}
        assert call.body["channel"] == CHANNEL
        assert _walk_keys(call.body["blocks"], set()) <= SLACK_PAYLOAD_KEYS
    first_ts, second_ts = sorted(fake.posted)
    assert output["slack"] == {"sent": True, "message_ts": [first_ts, second_ts], "skipped_reason": None}
    assert output["warnings"] == []
    briefing = _briefing(factory)
    assert briefing.slack_message_ts == [first_ts]
    assert briefing.tracked_change_message_ts == [second_ts]
    assert briefing.slack_sent_at == NOW
    # RL-03(추가형 열): 항목마다 자기가 실린 메시지 ts(판정 완료 스레드 답글의 thread_ts).
    assert _item_ts(factory) == {"recommendation": [first_ts] * 3, "tracked_change": [second_ts]}
    # 보낸 블록 = 미리보기와 같은 함수의 결과(추천 메시지 다음 추적 변화 메시지).
    policy = load_briefing_policy()
    with factory() as session:
        messages = build_briefing_messages(
            get_briefing_view(session, BRIEFING_DATE), base_url=BASE,
            items_per_message=policy.slack_items_per_message, deadline_warning_days=policy.deadline_warning_days,
        )
    assert [message.kind for message in messages] == ["recommendation", "tracked_change"]
    assert [call.body["blocks"] for call in calls] == [message.blocks for message in messages]
    assert [call.body["text"] for call in calls] == [message.text for message in messages]
    raw = json.dumps([call.body for call in calls], ensure_ascii=False)
    for forbidden in ("score", briefing.policy_sha256, str(briefing.graph_version_id), "policy"):
        assert forbidden not in raw
    _assert_no_secret(printed)

    again_code, again, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")
    assert again_code == 0
    assert (again["created"], again["slack"]) == (
        False, {"sent": False, "message_ts": [], "skipped_reason": "already_sent"},
    )
    assert len(fake.calls()) == 2
    assert _briefing(factory).slack_sent_at == NOW


def test_messages_over_the_per_message_cap_are_split_under_the_same_header(
    database, slack_env, fake, capsys, tmp_path
) -> None:
    factory, plans = database
    policy = json.loads((POLICY_DIR / "briefing-policy-v1.json").read_text(encoding="utf-8"))
    policy["slack_items_per_message"] = 2
    path = tmp_path / "briefing-policy-split.json"
    path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    _set(slack_env, BIDOPS_BRIEFING_POLICY_PATH=str(path))
    _seed(factory, plans)

    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0 and output["slack"]["sent"] is True
    calls = fake.calls("chat.postMessage")
    headers = [call.body["blocks"][0]["text"]["text"] for call in calls]
    assert headers == ["오늘의 브리핑 · 10월 16일 (금) · 3건"] * 2 + ["추적 중 사업 변화"]
    buttons = [
        [element["value"] for block in call.body["blocks"] if block["type"] == "actions" for element in block["elements"]]
        for call in calls
    ]
    assert [len(values) for values in buttons] == [4, 2, 0]
    briefing = _briefing(factory)
    ts = [call_ts for call_ts in sorted(fake.posted)]
    assert briefing.slack_message_ts == ts[:2]
    assert briefing.tracked_change_message_ts == ts[2:]
    assert output["slack"]["message_ts"] == ts
    # 나뉜 메시지마다 그 메시지에 실린 항목만 같은 ts를 갖는다(순위 1·2 → 첫 메시지, 3 → 둘째).
    assert _item_ts(factory) == {"recommendation": [ts[0], ts[0], ts[1]], "tracked_change": [ts[2]]}


def test_failure_keeps_the_briefing_and_a_rerun_sends_only_the_rest(database, slack_env, fake, capsys, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    factory, plans = database
    _seed(factory, plans)
    # 첫 메시지는 성공, 둘째(추적 변화)는 Slack이 rate limit(HTTP 429)으로 거부한다.
    original = fake._respond
    state = {"count": 0}

    def flaky(request):
        if request.method == "chat.postMessage":
            state["count"] += 1
            if state["count"] == 2:
                return 429, {"ok": False, "error": "ratelimited"}, {"Retry-After": "30"}
        return original(request)

    fake._respond = flaky

    code, output, printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0
    assert output["status"] == "generated" and output["created"] is True
    assert output["warnings"] == ["slack_send_failed"]
    (first_ts,) = fake.posted
    assert output["slack"] == {"sent": False, "message_ts": [first_ts], "skipped_reason": None}
    briefing = _briefing(factory)
    assert (briefing.slack_message_ts, briefing.tracked_change_message_ts, briefing.slack_sent_at) == (
        [first_ts], None, None,
    )
    # 보낸 메시지의 항목만 ts를 갖고, 못 보낸 추적 변화 항목은 null이다(답글을 건너뛴다).
    assert _item_ts(factory) == {"recommendation": [first_ts] * 3, "tracked_change": [None]}
    assert "slack_api_error:ratelimited" in printed
    _assert_no_secret(printed, caplog.text)
    # 열이 생기기 전에 보낸 메시지처럼 항목 ts를 비워 두면 재실행이 그 메시지 ts로 채운다(재전송 없이).
    with factory() as session:
        session.execute(update(BriefingItem).where(BriefingItem.kind == "recommendation").values(slack_message_ts=None))
        session.commit()

    retry_code, retry, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert retry_code == 0
    assert retry["created"] is False and retry["warnings"] == []
    calls = fake.calls("chat.postMessage")
    assert len(calls) == 3
    # 재실행은 이미 ts가 있는 추천 메시지를 다시 보내지 않고 추적 변화 메시지만 보낸다.
    assert calls[2].body["blocks"][0]["text"]["text"] == "추적 중 사업 변화"
    second_ts = sorted(fake.posted)[1]
    assert retry["slack"] == {"sent": True, "message_ts": [second_ts], "skipped_reason": None}
    briefing = _briefing(factory)
    assert (briefing.slack_message_ts, briefing.tracked_change_message_ts, briefing.slack_sent_at) == (
        [first_ts], [second_ts], NOW,
    )
    assert _item_ts(factory) == {"recommendation": [first_ts] * 3, "tracked_change": [second_ts]}


def test_total_failure_then_retry_sends_everything_once(database, slack_env, fake, capsys) -> None:
    factory, plans = database
    _seed(factory, plans)
    fake.failures = [(200, {"ok": False, "error": "internal_error"})]

    code, output, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert code == 0
    assert output["warnings"] == ["slack_send_failed"]
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": None}
    briefing = _briefing(factory)
    assert (briefing.slack_message_ts, briefing.slack_sent_at) == (None, None)

    _code, retry, _printed = _cli(factory, capsys, "--date", "2026-10-16", "--send")

    assert retry["slack"]["sent"] is True and len(retry["slack"]["message_ts"]) == 2
    assert len(fake.calls("chat.postMessage")) == 3
    assert _briefing(factory).slack_sent_at == NOW


def test_skipped_reason_vocabulary_is_closed() -> None:
    assert SKIPPED_REASONS == (
        "weekend", "dry_run", "not_requested", "slack_disabled", "token_missing", "channel_missing",
        "host_not_allowed", "empty", "already_sent",
    )
