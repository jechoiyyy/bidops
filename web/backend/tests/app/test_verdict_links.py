"""RL-03 STEP-008 T8: 활동 `verdict_completed`·브리핑 `verdict_display`(v2)·Slack 스레드 답글.

실제 FastAPI 앱(`lifecycle` + `deep_review`)과 실제 worker(가짜 Luna)로 card-v1 attempt를 끝낸 뒤:

- 활동 피드(`GET /api/opportunities/{id}/activity`): completed attempt 1건 → `verdict_completed`
  1건(제목 "판정 완료 · <판정>", 판정 탭 링크, actor 없음). 검증 실패 attempt → 0건. RL 비활성 → 0건.
- 브리핑(`GET /api/briefings/{date}`, `bidops.briefing.v2`): 사전규격 항목은 분석 대기 → 분석 중 →
  판정 이름, 같은 사업기회 입찰공고 항목은 "사전규격 판정 참조", 연결 사전규격이 없는 입찰공고는
  "판정 대상 아님". RL 비활성이면 RL-01 v1 규칙("분석 대기").
- Slack 스레드(127.0.0.1 가짜 Slack, `tests/app/slack_fake.py`): 브리핑 항목 `slack_message_ts`가
  있으면 그 메시지 스레드에 "판정 완료 · <판정> · 확인할 것 n" 1건; null이면 0건·오류 없음;
  실패 attempt는 0건; Slack이 꺼져 있으면 호출 전에 멈춘다. 토큰은 어디에도 없다.

실제 Slack·모델은 부르지 않는다(D5: 실제 Slack 게시 증명이 아니다). SQLite와, 설정되면
PostgreSQL 17 양쪽에서 돈다.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.deep_review.models import DeepReview, DeepReviewAttempt
from app.deep_review.services import verdict_links
from app.deep_review.services.deep_reviews import DeepReviewService
from app.lifecycle.models import BriefingItem, Notice, OpportunityLink
from tests.app import test_card_analysis_postgres as cap
from tests.app import test_transfer_policy as tp
from tests.app import test_verdict_trigger_postgres as vt
from tests.app.test_deep_reviews import _FixtureStore
from tests.app.test_slack_transport import APP_TOKEN, BOT_TOKEN, CHANNEL, SECRET_MARKERS, _sender, fake  # noqa: F401
from tests.app.test_verdict_api import client_for, start, started_world  # noqa: F401
from tests.app.test_verdict_trigger_postgres import flow_engine, no_model_transport  # noqa: F401
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store


pytestmark = tp.needs_rootlab

BRIEFING_DATE = "2026-10-16"


def _worker(session: Session, *, notifier=None, overrides=None) -> DeepReviewService:
    company_id = session.scalar(select(DeepReview.company_id).limit(1))
    knowledge = cap.resolve_company_knowledge_context(session, company_id)
    return DeepReviewService(
        client=cap.FakeLuna(knowledge.ontology, overrides), structure_loader=tp._structure_loader,
        raw_response_store=_FixtureStore(), verdict_completed_notifier=notifier,
    )


class _Recorder:
    """worker가 부른 notifier 호출을 기록하고 실제 notify에 가짜 전송기를 묶는다."""

    def __init__(self, sender=None) -> None:
        self.sender = sender
        self.calls: list = []
        self.outcomes: list[str] = []

    def __call__(self, session: Session, attempt_id) -> None:
        self.calls.append(attempt_id)
        self.outcomes.append(verdict_links.notify_verdict_completed(session, attempt_id, sender=self.sender))


def _complete(session: Session, world, seeded, notifier=None):
    started = start(session, world, seeded)
    cap.run(session, _worker(session, notifier=notifier))
    session.commit()
    assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
    return started


def _verdict_body(client, opportunity_id: int) -> dict:
    body = client.get(f"/api/opportunities/{opportunity_id}/verdict").json()
    assert body["availability"] == "completed"
    return body


def _rl_off(monkeypatch) -> None:
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "false")
    get_settings.cache_clear()


def _bid_notice_on(session: Session, opportunity_id: int) -> SimpleNamespace:
    """같은 사업기회에 권위 연결된 입찰공고(문서 없음)."""

    notice = Notice(notice_key=f"rl-links:bid:{opportunity_id}", source_type="bid_notice", title="루트랩 입찰공고")
    session.add(notice)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity_id, notice_id=notice.id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"R26BK{notice.id:08d}"))
    session.commit()
    return SimpleNamespace(notice_id=notice.id, opportunity_id=opportunity_id)


def _assert_no_secret(*values) -> None:
    for value in values:
        rendered = value if isinstance(value, str) else repr(value)
        for marker in SECRET_MARKERS:
            assert marker not in rendered


# --- 활동 피드 ------------------------------------------------------------------------------


def test_t8_activity_verdict_completed_once_per_completed_attempt(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, _item = started_world(session, monkeypatch)
        client = client_for(session)
        url = f"/api/opportunities/{seeded.opportunity_id}/activity"

        def verdict_items() -> list[dict]:
            response = client.get(url, params={"kinds": "verdict_completed"})
            assert response.status_code == 200
            return response.json()["items"]

        assert verdict_items() == []
        started = start(session, world, seeded)
        assert verdict_items() == []  # 대기 중 attempt는 사건이 아니다

        cap.run(session, _worker(session))
        session.commit()
        attempt = session.get(DeepReviewAttempt, started.attempt_id)
        verdict = _verdict_body(client, seeded.opportunity_id)["result"]["verdict"]
        items = verdict_items()
        assert len(items) == 1
        (item,) = items
        assert item["item_id"] == f"verdict_completed:{started.attempt_id}"
        assert (item["kind"], item["actor"], item["title"], item["detail"], item["status_pill"]) == (
            "verdict_completed", None, f"판정 완료 · {verdict}", None, None,
        )
        assert item["link"] == {"label": "판정 보기", "path": f"/opportunities/{seeded.opportunity_id}/verdict"}
        assert item["at"].startswith(attempt.completed_at.isoformat()[:16])
        # 전체 피드에도 같은 1건이 lifecycle 항목과 함께 실린다.
        everything = client.get(url).json()["items"]
        assert [row["item_id"] for row in everything if row["kind"] == "verdict_completed"] == [item["item_id"]]

        _rl_off(monkeypatch)
        assert verdict_items() == []


def test_t8_activity_has_no_item_for_a_failed_attempt(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, _item = started_world(session, monkeypatch)
        client = client_for(session)
        recorder = _Recorder()
        start(session, world, seeded)
        assert cap.run_code(
            session, _worker(session, notifier=recorder, overrides={("technical_fit", 0): cap._upgrade_unknown}),
        ) == "card_role_invalid"
        session.rollback()

        response = client.get(f"/api/opportunities/{seeded.opportunity_id}/activity",
                              params={"kinds": "verdict_completed"})
        assert response.status_code == 200 and response.json()["items"] == []
        # 실패한 attempt는 완료 답글 경로를 부르지 않는다.
        assert recorder.calls == []


# --- 브리핑 verdict_display (bidops.briefing.v2) ---------------------------------------------


def test_t8_briefing_verdict_display_follows_the_card_attempt(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        same_opportunity_bid = _bid_notice_on(session, seeded.opportunity_id)
        bid_item = vt.recommend(session, same_opportunity_bid, stage="bid_notice")
        lone_bid = vt.seed_pre_spec(session, source_type="bid_notice")
        lone_item = vt.recommend(session, lone_bid, stage="bid_notice")
        client = client_for(session)

        def displays() -> dict[str, str]:
            response = client.get(f"/api/briefings/{BRIEFING_DATE}")
            assert response.status_code == 200
            body = response.json()
            assert body["schema_version"] == "bidops.briefing.v2"
            return {row["item_id"]: row["verdict_display"] for row in body["items"]}

        assert displays() == {
            str(item.id): "분석 대기", str(bid_item.id): "판정 대상 아님", str(lone_item.id): "판정 대상 아님",
        }

        start(session, world, seeded)
        assert displays() == {
            str(item.id): "분석 중", str(bid_item.id): "판정 대상 아님", str(lone_item.id): "판정 대상 아님",
        }

        cap.run(session, _worker(session))
        session.commit()
        verdict = _verdict_body(client, seeded.opportunity_id)["result"]["verdict"]
        assert verdict in {"진행 가능", "조건부 진행", "진행 어려움", "판단 불가"}
        assert displays() == {
            str(item.id): verdict, str(bid_item.id): "사전규격 판정 참조", str(lone_item.id): "판정 대상 아님",
        }

        # RL 경로가 꺼지면 제공자는 아무것도 주지 않고 RL-01 v1 규칙으로 돌아간다.
        _rl_off(monkeypatch)
        assert displays() == {
            str(item.id): "분석 대기", str(bid_item.id): "분석 대기", str(lone_item.id): "분석 대기",
        }


def test_t8_briefing_verdict_display_keeps_a_completed_verdict_while_a_failed_retry_waits(
    flow_engine, monkeypatch, client_for
) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        _complete(session, world, seeded)
        verdict = _verdict_body(client, seeded.opportunity_id)["result"]["verdict"]
        # 수동 "다시 판정"이 검증에서 실패해도 최신 completed 판정을 보여 준다.
        start(session, world, seeded)
        assert cap.run_code(
            session, _worker(session, overrides={("technical_fit", 0): cap._upgrade_unknown}),
        ) == "card_role_invalid"
        session.rollback()
        body = client.get(f"/api/briefings/{BRIEFING_DATE}").json()
        assert [row["verdict_display"] for row in body["items"] if row["item_id"] == str(item.id)] == [verdict]


# --- Slack 스레드 답글 ------------------------------------------------------------------------


def test_t8_completed_attempt_replies_once_in_the_briefing_message_thread(
    flow_engine, monkeypatch, client_for, fake, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        sender = _sender(fake)
        # 브리핑 메시지가 실제로 게시돼 있고(가짜 Slack) 항목이 그 ts를 들고 있다(`--send`가 남김).
        message_ts = sender.post_message(
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "오늘의 브리핑"}}], text="오늘의 브리핑",
            allowed_keys=frozenset({"type", "text"}),
        )
        session.execute(update(BriefingItem).where(BriefingItem.id == item.id).values(slack_message_ts=message_ts))
        session.commit()
        recorder = _Recorder(sender)

        started = _complete(session, world, seeded, notifier=recorder)

        assert recorder.calls == [started.attempt_id]
        assert recorder.outcomes == ["posted"]
        result = _verdict_body(client, seeded.opportunity_id)["result"]
        unknown = sum(1 for row in result["matrix"] if row["fit_status"] == "unknown")
        replies = [call for call in fake.calls("chat.postMessage") if "thread_ts" in call.body]
        assert len(replies) == 1
        (reply,) = replies
        assert set(reply.body) == {"channel", "thread_ts", "text"}
        assert (reply.body["channel"], reply.body["thread_ts"]) == (CHANNEL, message_ts)
        assert reply.body["text"] == f"판정 완료 · {result['verdict']} · 확인할 것 {unknown}"
        assert reply.authorization == f"Bearer {BOT_TOKEN}"
        _assert_no_secret(reply.body, caplog.text, recorder.outcomes)


def test_t8_null_message_ts_skips_the_reply_without_error(flow_engine, monkeypatch, fake) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        assert item.slack_message_ts is None
        recorder = _Recorder(_sender(fake))

        started = _complete(session, world, seeded, notifier=recorder)

        assert recorder.calls == [started.attempt_id]
        assert recorder.outcomes == [verdict_links.NOTIFY_NOT_POSTED]
        assert fake.requests == []
        # 답글을 건너뛰어도 판정은 그대로 completed다.
        assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"


def test_t8_reply_is_refused_before_any_call_when_slack_is_off_or_misconfigured(
    flow_engine, monkeypatch, fake
) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        started = _complete(session, world, seeded)
        session.execute(update(BriefingItem).where(BriefingItem.id == item.id).values(slack_message_ts="1760572800.000001"))
        session.commit()

        # 운영 기본 설정(`BIDOPS_SLACK_ENABLED=false`)은 전송기를 만들어도 네트워크 전에 멈춘다.
        assert verdict_links.notify_verdict_completed(session, started.attempt_id) == "slack_disabled"
        for overrides, reason in (
            ({"enabled": False}, "slack_disabled"),
            ({"bot_token": ""}, "token_missing"),
            ({"channel_id": ""}, "channel_missing"),
            ({"allowed_hosts": "slack.com"}, "host_not_allowed"),
        ):
            assert verdict_links.notify_verdict_completed(
                session, started.attempt_id, sender=_sender(fake, **overrides),
            ) == reason
        assert fake.requests == []

        # Slack 오류는 안전한 code로만 남고 예외가 나가지 않는다.
        fake.failures = [(200, {"ok": False, "error": "internal_error"})]
        assert verdict_links.notify_verdict_completed(
            session, started.attempt_id, sender=_sender(fake),
        ) == "slack_api_error:internal_error"
        # completed가 아닌 attempt는 답글 대상이 아니다.
        assert verdict_links.notify_verdict_completed(session, item.id) == verdict_links.NOTIFY_NOT_COMPLETED
