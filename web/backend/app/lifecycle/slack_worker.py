"""Slack Socket Mode worker (RL-01 spec "Slack" Socket Mode worker, T9).

`python -m app.lifecycle.cli slack-worker`로 뜨는 별도 프로세스다(compose 서비스
`slack-worker`, profile `slack`, worker DB 자격). 공개 HTTPS endpoint 없이 Slack이 여는
websocket으로 버튼 클릭(`block_actions`)을 받는다.

한 envelope의 처리 순서:

1. **ack 먼저**(Slack은 3초 안의 ack를 요구한다). 처리 결과와 상관없이 envelope마다 한 번.
2. `action_id="briefing_react"`만 처리한다. 다른 action·다른 이벤트는 무시하고 감사 로그 한 줄
   (토큰·payload·사람 이름 없이 사유 code만).
3. `value="<item_id>:<반응>"`(반응 `채택|무시|대기`)을 파싱하고, 설정한 채널에서 온 클릭인지
   본다.
4. 화면과 **같은 service 함수**(`react_to_item`, `via="slack"`)로 저장한다.
   `request_id = uuid5(SLACK_REACTION_NS, trigger_id)`라 같은 클릭의 중복 전달은 반응 1회다.
   `expected_revision`은 저장 직전에 읽은 현재 값이고, 409 `version_conflict`면 다시 읽어
   **1회만** 재시도한다. 또 실패하면 메시지에 "화면에서 먼저 반응했습니다"를 단다.
5. `chat.update`로 그 메시지를 현재 반응으로 다시 그린다(반응한 항목은 버튼 자리에
   "✓ 이름이 볼게요" + 되돌리기 `<item_id>:대기`). 중복 전달(재생·같은 key 다른 요청)은
   갱신하지 않는다 — 클릭 하나에 `chat.update` 한 번.

`reacted_by`는 interaction payload의 `user.username`, 없으면 `user.name`이다(`users.info`를
부르지 않는다). 반응은 추적 상태·Go/No-Go를 바꾸지 않는다(service 계약).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import signal
import threading
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.slack import SKIP_SLACK_DISABLED, SlackSender, SlackTransportError
from .models import BriefingItem
from .services.briefing import BriefingError, react_to_item
from .services.briefing_slack import (
    SLACK_PAYLOAD_KEYS,
    SLACK_REACT_ACTION_ID,
    reaction_update_message,
)

logger = logging.getLogger(__name__)

#: 클릭(trigger) 하나를 반응 요청 하나로 고정하는 이름공간(spec 상수).
SLACK_REACTION_NS = uuid5(NAMESPACE_URL, "bidops:slack-reaction")
#: Slack 버튼이 보낼 수 있는 반응. `나중에`는 화면 전용이다.
SLACK_REACTIONS = ("채택", "무시", "대기")
CONFLICT_NOTE = "화면에서 먼저 반응했습니다"

#: 처리 결과 code. 감사 로그 `status`와 검사가 읽는다.
RESULT_SAVED = "saved"
RESULT_REPLAYED = "replayed"
RESULT_DUPLICATE = "duplicate"
RESULT_CONFLICT = "conflict"
RESULT_IGNORED = "ignored"
RESULT_FAILED = "failed"

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class BlockActionResult:
    status: str
    reason: str | None = None
    item_id: UUID | None = None
    updated: bool = False


def _audit(event: str, *, status: str, reason: str | None = None) -> None:
    """감사 로그 한 줄. 사유 code만 남긴다(토큰·payload·이름·채널 값 없음)."""

    fields: dict[str, Any] = {"event": event, "status": status}
    if reason is not None:
        fields["error_code"] = reason
    logger.info("slack worker %s", event, extra={"bidops": fields})


def parse_action_value(value: Any) -> tuple[UUID, str] | None:
    """`"<item_id>:<반응>"` → `(UUID, 반응)`. 형식이 다르거나 반응이 허용 밖이면 `None`."""

    if not isinstance(value, str) or ":" not in value:
        return None
    raw_id, reaction = value.split(":", 1)
    if reaction not in SLACK_REACTIONS:
        return None
    try:
        return UUID(raw_id), reaction
    except ValueError:
        return None


def reaction_request_id(trigger_id: str) -> UUID:
    return uuid5(SLACK_REACTION_NS, trigger_id)


def current_revision(session: Session, item_id: UUID) -> int | None:
    """저장 직전에 읽는 현재 `revision`(`expected_revision`). 항목이 없으면 `None`."""

    return session.scalar(select(BriefingItem.revision).where(BriefingItem.id == item_id))


def _actor(payload: Mapping[str, Any]) -> str | None:
    user = payload.get("user")
    if not isinstance(user, Mapping):
        return None
    for key in ("username", "name"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _channel_and_ts(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    container = payload.get("container") if isinstance(payload.get("container"), Mapping) else {}
    channel = container.get("channel_id")
    if not channel and isinstance(payload.get("channel"), Mapping):
        channel = payload["channel"].get("id")
    ts = container.get("message_ts")
    if not ts and isinstance(payload.get("message"), Mapping):
        ts = payload["message"].get("ts")
    return (channel if isinstance(channel, str) else None, ts if isinstance(ts, str) else None)


class SlackReactionHandler:
    """Socket Mode request listener. `client.socket_mode_request_listeners`에 들어간다."""

    def __init__(
        self,
        sender: SlackSender,
        session_factory: SessionFactory,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sender = sender
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # --- Socket Mode listener -------------------------------------------------

    def __call__(self, client: Any, request: Any) -> None:
        self.ack(client, request)
        if getattr(request, "type", None) != "interactive":
            _audit("slack_worker.envelope_ignored", status=RESULT_IGNORED, reason="not_interactive")
            return
        payload = getattr(request, "payload", None)
        if not isinstance(payload, Mapping):
            _audit("slack_worker.envelope_ignored", status=RESULT_IGNORED, reason="payload_invalid")
            return
        self.handle_payload(payload)

    @staticmethod
    def ack(client: Any, request: Any) -> None:
        """작업 전에 envelope를 ack한다. ack 실패는 처리를 막지 않는다(재전달은 멱등)."""

        envelope_id = getattr(request, "envelope_id", None)
        if not isinstance(envelope_id, str) or not envelope_id:
            return
        try:
            client.send_socket_mode_response({"envelope_id": envelope_id})
        except Exception:
            _audit("slack_worker.ack_failed", status=RESULT_FAILED, reason="ack_failed")

    # --- block_actions --------------------------------------------------------

    def handle_payload(self, payload: Mapping[str, Any]) -> BlockActionResult:
        if payload.get("type") != "block_actions":
            return self._ignored("not_block_actions")
        actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        action = None
        audited = False
        for candidate in actions:
            if (
                action is None
                and isinstance(candidate, Mapping)
                and candidate.get("action_id") == SLACK_REACT_ACTION_ID
            ):
                action = candidate
            else:
                # 클릭 한 번에 한 action만 처리한다. 나머지는 무시·감사.
                _audit("slack_worker.action_ignored", status=RESULT_IGNORED, reason="unknown_action")
                audited = True
        if action is None:
            return self._ignored("unknown_action", audited=audited)
        parsed = parse_action_value(action.get("value"))
        if parsed is None:
            return self._ignored("value_invalid")
        item_id, reaction = parsed
        trigger_id = payload.get("trigger_id")
        if not isinstance(trigger_id, str) or not trigger_id.strip():
            return self._ignored("trigger_missing")
        actor = _actor(payload)
        if actor is None:
            return self._ignored("user_missing")
        channel, message_ts = _channel_and_ts(payload)
        if channel is None or channel != self._sender.channel_id:
            return self._ignored("channel_not_allowed")

        status = self._save(item_id, reaction, actor, reaction_request_id(trigger_id))
        if status in (RESULT_REPLAYED, RESULT_DUPLICATE):
            _audit("slack_worker.duplicate", status=status)
            return BlockActionResult(status=status, item_id=item_id)
        if status not in (RESULT_SAVED, RESULT_CONFLICT):
            _audit("slack_worker.reaction_failed", status=RESULT_FAILED, reason=status)
            return BlockActionResult(status=RESULT_FAILED, reason=status, item_id=item_id)
        notes = {item_id: CONFLICT_NOTE} if status == RESULT_CONFLICT else None
        updated = self._update(item_id, channel=channel, message_ts=message_ts, notes=notes)
        _audit("slack_worker.reaction", status=status)
        return BlockActionResult(status=status, item_id=item_id, updated=updated)

    @staticmethod
    def _ignored(reason: str, *, audited: bool = False) -> BlockActionResult:
        if not audited:
            _audit("slack_worker.action_ignored", status=RESULT_IGNORED, reason=reason)
        return BlockActionResult(status=RESULT_IGNORED, reason=reason)

    def _save(self, item_id: UUID, reaction: str, actor: str, request_id: UUID) -> str:
        """저장 결과 code. `version_conflict`는 다시 읽어 1회만 재시도한다."""

        for attempt in range(2):
            with self._session_factory() as session:
                try:
                    expected = current_revision(session, item_id)
                    if expected is None:
                        return "briefing_item_not_found"
                    result = react_to_item(
                        session,
                        item_id=item_id,
                        reaction=reaction,
                        expected_revision=expected,
                        request_id=request_id,
                        actor=actor,
                        via="slack",
                        reacted_at=self._clock(),
                    )
                    session.commit()
                    return RESULT_REPLAYED if result.replayed else RESULT_SAVED
                except BriefingError as error:
                    session.rollback()
                    if error.code == "version_conflict":
                        if attempt == 0:
                            _audit("slack_worker.retry", status="retry", reason="version_conflict")
                            continue
                        return RESULT_CONFLICT
                    if error.code == "idempotency_conflict":
                        # 같은 클릭(trigger)이 이미 다른 revision에서 저장됐다 = 중복 전달.
                        return RESULT_DUPLICATE
                    return error.code
                except Exception:
                    session.rollback()
                    return RESULT_FAILED
        return RESULT_CONFLICT  # pragma: no cover - 위 반복이 언제나 return한다

    def _update(
        self,
        item_id: UUID,
        *,
        channel: str,
        message_ts: str | None,
        notes: Mapping[UUID, str] | None,
    ) -> bool:
        try:
            with self._session_factory() as session:
                update = reaction_update_message(session, item_id, item_notes=notes)
                session.rollback()
        except Exception:
            _audit("slack_worker.update_skipped", status=RESULT_FAILED, reason="render_failed")
            return False
        if update is None:
            _audit("slack_worker.update_skipped", status=RESULT_IGNORED, reason="message_not_sent")
            return False
        if message_ts is not None and message_ts != update.ts:
            _audit("slack_worker.update_skipped", status=RESULT_IGNORED, reason="message_mismatch")
            return False
        try:
            self._sender.update_message(
                channel=channel,
                ts=update.ts,
                blocks=update.message.blocks,
                text=update.message.text,
                allowed_keys=SLACK_PAYLOAD_KEYS,
            )
        except SlackTransportError as error:
            _audit("slack_worker.update_failed", status=RESULT_FAILED, reason=error.code)
            return False
        return True


def run_slack_worker(
    *,
    sender: SlackSender | None = None,
    session_factory: SessionFactory | None = None,
    stop_event: threading.Event | None = None,
) -> int:
    """worker 본체. 종료 코드: 0 정상 종료·비활성(`slack_disabled`), 1 설정 오류·연결 실패.

    검사(토큰·app token·채널·허용 host)는 연결 전에 한다. 비활성은 의도한 기본 상태라 0으로
    끝나고, 켜 놓고 값이 빠진 것은 1이다(compose `restart: on-failure`가 드러낸다).
    """

    from ..core.config import get_settings
    from ..core.logging_setup import configure

    settings = get_settings()
    configure(settings)
    active_sender = sender or SlackSender.from_settings(settings)
    reason = active_sender.preflight(require_app_token=True)
    if reason == SKIP_SLACK_DISABLED:
        _audit("slack_worker.idle", status="disabled", reason=reason)
        return 0
    if reason is not None:
        _audit("slack_worker.not_started", status=RESULT_FAILED, reason=reason)
        return 1
    if session_factory is None:
        from ..core.db import SessionFactory as default_factory, init_db

        init_db()
        session_factory = default_factory
    handler = SlackReactionHandler(active_sender, session_factory)
    stop = stop_event or threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop.set()

    if stop_event is None:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    try:
        client = active_sender.socket_mode_client(handler)
    except SlackTransportError as error:
        _audit("slack_worker.not_started", status=RESULT_FAILED, reason=error.code)
        return 1
    try:
        try:
            client.connect()
        except SlackTransportError as error:
            _audit("slack_worker.not_started", status=RESULT_FAILED, reason=error.code)
            return 1
        except Exception:
            _audit("slack_worker.not_started", status=RESULT_FAILED, reason="connect_failed")
            return 1
        _audit("slack_worker.connected", status="connected")
        while not stop.wait(1.0):
            pass
        return 0
    finally:
        client.close()


__all__ = [
    "CONFLICT_NOTE",
    "SLACK_REACTIONS",
    "SLACK_REACTION_NS",
    "BlockActionResult",
    "SlackReactionHandler",
    "current_revision",
    "parse_action_value",
    "reaction_request_id",
    "run_slack_worker",
]
