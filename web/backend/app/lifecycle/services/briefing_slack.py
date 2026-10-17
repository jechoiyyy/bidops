"""브리핑 Slack 메시지 payload 생성·전송 (RL-01 spec "Slack" 메시지 형식, ui-spec §4.2).

payload는 `build_briefing_messages` 하나가 만든다. 전송(`send_briefing`, `build-briefing
--send`)과 `GET /api/briefings/{date}/slack-preview`가 **같은 함수**의 결과를 쓰고, 전송 전
검사(allowlist·토큰·채널·`BIDOPS_SLACK_ENABLED`)는 core 전송기(`core/slack.py`)가 호출 전에
한다. Socket Mode worker의 `chat.update`도 같은 함수에 `show_reactions=True`만 더해 쓴다.

입력은 응답 DTO(`BriefingView`)다. 응답에는 `score`·`policy_sha256`·`graph_version_id`가
없으므로 payload에도 들어갈 수 없다. payload에는 `item_id`(버튼 값)·제목·기관·금액·마감·
이유 텍스트·링크만 넣고, Block Kit 키는 `SLACK_PAYLOAD_KEYS`만 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.slack import SlackSender, SlackTransportError
from ..models import Briefing, BriefingItem
from ..schemas.briefings import (
    BRIEFING_SLACK_PREVIEW_SCHEMA_VERSION,
    BriefingItemView,
    BriefingSlackPreview,
    BriefingView,
)
from .briefing import KST, BriefingError, get_briefing_view
from .briefing_policy import BriefingPolicyError, load_briefing_policy
from .briefing_rules import DEADLINE_REMINDER_FIELD, korean_amount_text

#: 버튼 action id. Socket Mode worker는 이 값만 처리하고 나머지는 무시·감사한다.
SLACK_REACT_ACTION_ID = "briefing_react"
#: payload에 쓰는 Block Kit 키 전체(T8 허용 키 검사).
SLACK_PAYLOAD_KEYS = frozenset({"type", "text", "elements", "style", "action_id", "value"})
RECOMMENDATION_HEADER = "오늘의 브리핑"
TRACKED_CHANGE_HEADER = "추적 중 사업 변화"
VIEW_ON_SCREEN = "화면에서 보기"
#: 버튼 두 개(ux-review 결정 4). `볼게요`=채택(primary), `무시`=기본 스타일.
SLACK_BUTTONS: tuple[tuple[str, str, str | None], ...] = (
    ("볼게요", "채택", "primary"),
    ("무시", "무시", None),
)
#: 반응 뒤 버튼 자리에 쓰는 표시 이름(ui-spec §4.2 "✓ 이름이 볼게요" + 되돌리기).
REACTION_LABELS = {"채택": "볼게요", "무시": "무시", "나중에": "나중에"}
UNDO_LABEL = "되돌리기"
UNDO_REACTION = "대기"

#: `slack.skipped_reason` 중 브리핑 상태 몫(전송기 몫은 `core.slack.PREFLIGHT_REASONS`).
SKIP_EMPTY = "empty"
SKIP_ALREADY_SENT = "already_sent"
#: 전송 실패 경고 code(CLI `warnings[]`). 브리핑은 그대로 두고 `--send` 재실행이 재전송한다.
WARNING_SLACK_SEND_FAILED = "slack_send_failed"

_WEEKDAY = "월화수목금토일"
_REASON_PREFIX = {"keyword": "키워드 · ", "repeat_agency": "기관 거래 이력 · "}
_CHANGE_FIELD_LABEL = {
    "deadline_at": "마감",
    "title": "제목",
    "budget": "예산",
    "estimated_price": "추정가격",
    "method": "계약방법",
}
#: 마감 알림 사유(RL-02)는 바뀐 필드가 아니므로 "바뀐 항목"과 따로 한 요소로 쓴다.
DEADLINE_REMINDER_LABEL = "마감 임박"


@dataclass(frozen=True)
class SlackMessage:
    """보낼 메시지 하나. `kind`는 `briefing.slack_message_ts`·`tracked_change_message_ts`
    중 어디에 ts를 남길지를 정한다(전송기 몫)."""

    kind: Literal["recommendation", "tracked_change"]
    blocks: list[dict[str, Any]]
    text: str


def _escape(value: str) -> str:
    """Slack mrkdwn 제어 문자(`&`·`<`·`>`)만 바꾼다."""

    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plain(text: str) -> dict[str, Any]:
    return {"type": "plain_text", "text": text}


def _mrkdwn(text: str) -> dict[str, Any]:
    return {"type": "mrkdwn", "text": text}


def _date_label(value: date) -> str:
    return f"{value.month}월 {value.day}일 ({_WEEKDAY[value.weekday()]})"


def _link(base_url: str, path: str, label: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return _escape(label)
    return f"<{base}{path}|{_escape(label)}>"


def _deadline_text(item: BriefingItemView, briefing_date: date, warning_days: int) -> str:
    if item.deadline_at is not None:
        days = (item.deadline_at.astimezone(KST).date() - briefing_date).days
        if days < 0:
            return "마감 지남"
        text = f"마감 D-{days}"
        return f"*{text}*" if days <= warning_days else text
    if item.planned_month is not None:
        return f"발주 예정 {_escape(item.planned_month)}"
    return "마감 미정"


def _reason_text(item: BriefingItemView) -> str:
    labels = []
    for reason in item.reasons:
        if reason.kind == "similar_project":
            labels.append(f"비슷한 실적 {reason.count}건" if reason.count is not None else "비슷한 실적")
        elif reason.text:
            labels.append(f"{_REASON_PREFIX[reason.kind]}{reason.text}")
    return " · ".join(_escape(label) for label in labels)


def subject_particle(name: str) -> str:
    """주격 조사. 한글 음절로 끝나면 받침에 따라 이/가, 그 밖은 spec 문구 그대로 "이"."""

    last = name.strip()[-1:] or " "
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return "가" if (code - 0xAC00) % 28 == 0 else "이"
    return "이"


def _button(label: str, item_id: UUID, reaction: str, style: str | None) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": _plain(label),
        "action_id": SLACK_REACT_ACTION_ID,
        "value": f"{item_id}:{reaction}",
    }
    if style is not None:
        button["style"] = style
    return button


def _item_blocks(
    item: BriefingItemView,
    *,
    briefing_date: date,
    base_url: str,
    warning_days: int,
    with_buttons: bool,
    show_reactions: bool = False,
    note: str | None = None,
) -> list[dict[str, Any]]:
    amount = korean_amount_text(item.amount_krw) if item.amount_krw is not None else "금액 미공개"
    title = _link(base_url, item.record_path, item.title or "제목 없음")
    detail = " · ".join(
        [_escape(item.agency or "기관 미상"), _escape(amount), _deadline_text(item, briefing_date, warning_days)]
    )
    blocks: list[dict[str, Any]] = [{"type": "section", "text": _mrkdwn(f"*{title}*\n{detail}")}]
    context: list[dict[str, Any]] = []
    if with_buttons:
        reasons = _reason_text(item)
        if reasons:
            context.append(_mrkdwn(reasons))
        blocking = " · ".join(_escape(block.text) for block in item.blocking)
        if blocking:
            context.append(_mrkdwn(blocking))
    else:
        changed = " · ".join(
            _CHANGE_FIELD_LABEL.get(name, name) for name in item.change_fields if name != DEADLINE_REMINDER_FIELD
        )
        if changed:
            context.append(_mrkdwn(_escape(f"바뀐 항목: {changed}")))
        if DEADLINE_REMINDER_FIELD in item.change_fields:
            context.append(_mrkdwn(DEADLINE_REMINDER_LABEL))
    if context:
        blocks.append({"type": "context", "elements": context})
    if note:
        blocks.append({"type": "context", "elements": [_mrkdwn(_escape(note))]})
    if with_buttons:
        label = REACTION_LABELS.get(item.reaction or "") if show_reactions else None
        if label is not None:
            # 반응 뒤: 버튼 자리에 "✓ 이름이 볼게요" + 되돌리기(`<item_id>:대기`).
            who = item.reacted_by or "담당자"
            blocks.append(
                {"type": "context", "elements": [_mrkdwn(_escape(f"✓ {who}{subject_particle(who)} {label}"))]}
            )
            blocks.append(
                {"type": "actions", "elements": [_button(UNDO_LABEL, item.item_id, UNDO_REACTION, None)]}
            )
        else:
            buttons = [_button(label, item.item_id, reaction, style) for label, reaction, style in SLACK_BUTTONS]
            blocks.append({"type": "actions", "elements": buttons})
    blocks.append({"type": "divider"})
    return blocks


def _chunks(items: Sequence[BriefingItemView], size: int) -> list[Sequence[BriefingItemView]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_briefing_messages(
    view: BriefingView,
    *,
    base_url: str,
    items_per_message: int,
    deadline_warning_days: int,
    show_reactions: bool = False,
    item_notes: Mapping[UUID, str] | None = None,
) -> list[SlackMessage]:
    """보낼 순서대로의 메시지 목록. 추천 메시지 다음에 추적 변화 메시지다.

    - `status=empty`(추천 0건·수집 정상)이면 아무것도 보내지 않는다(ui-spec §4.2).
    - 추천이 0건이면 추천 메시지가 없다. 메시지당 항목은 `items_per_message` 이하이며
      넘치면 같은 헤더로 나눈다.
    - 처음 보내는 메시지와 미리보기는 반응을 그리지 않는다(payload에 사람 이름이 없다).
      `show_reactions=True`는 Socket Mode worker의 `chat.update` 전용이며, 반응한 항목의
      버튼 자리를 "✓ 이름이 볼게요" + 되돌리기로 바꾼다. `item_notes`는 그 항목 아래에 한 줄을
      더한다("화면에서 먼저 반응했습니다").
    """

    if items_per_message < 1:
        raise ValueError("items_per_message must be positive")
    if view.status == "empty":
        return []
    day = _date_label(view.briefing_date)
    screen_path = f"/briefing?date={view.briefing_date.isoformat()}"
    footer = {"type": "section", "text": _mrkdwn(_link(base_url, screen_path, VIEW_ON_SCREEN))}
    messages: list[SlackMessage] = []
    header_text = f"{RECOMMENDATION_HEADER} · {day} · {len(view.items)}건"
    for chunk in _chunks(view.items, items_per_message):
        blocks: list[dict[str, Any]] = [{"type": "header", "text": _plain(header_text)}]
        for item in chunk:
            blocks.extend(
                _item_blocks(
                    item,
                    briefing_date=view.briefing_date,
                    base_url=base_url,
                    warning_days=deadline_warning_days,
                    with_buttons=True,
                    show_reactions=show_reactions,
                    note=(item_notes or {}).get(item.item_id),
                )
            )
        blocks.append(footer)
        messages.append(SlackMessage(kind="recommendation", blocks=blocks, text=header_text))
    for chunk in _chunks(view.tracked_changes, items_per_message):
        blocks = [{"type": "header", "text": _plain(TRACKED_CHANGE_HEADER)}]
        for item in chunk:
            blocks.extend(
                _item_blocks(
                    item,
                    briefing_date=view.briefing_date,
                    base_url=base_url,
                    warning_days=deadline_warning_days,
                    with_buttons=False,
                )
            )
        blocks.append(footer)
        messages.append(SlackMessage(kind="tracked_change", blocks=blocks, text=TRACKED_CHANGE_HEADER))
    return messages


def slack_preview(
    view: BriefingView,
    *,
    base_url: str,
    items_per_message: int,
    deadline_warning_days: int,
    channel_id_present: bool,
) -> BriefingSlackPreview:
    """`build_briefing_messages`의 결과를 보낼 순서대로 이어 붙인 미리보기.

    `blocks`는 메시지들의 블록을 순서대로 이은 것이고 `text`는 각 메시지 대체 텍스트를
    줄바꿈으로 이은 것이다. 보낼 메시지가 없으면 둘 다 비어 있다.
    """

    messages = build_briefing_messages(
        view,
        base_url=base_url,
        items_per_message=items_per_message,
        deadline_warning_days=deadline_warning_days,
    )
    return BriefingSlackPreview(
        schema_version=BRIEFING_SLACK_PREVIEW_SCHEMA_VERSION,
        channel_id_present=channel_id_present,
        blocks=[block for message in messages for block in message.blocks],
        text="\n".join(message.text for message in messages),
    )


@dataclass(frozen=True)
class _MessageInputs:
    base_url: str
    items_per_message: int
    deadline_warning_days: int
    channel_id_present: bool


def _message_inputs() -> _MessageInputs:
    """메시지당 항목 수·마감 강조 일수는 규칙 파일에서, 링크 기준 주소와 채널 설정 여부는
    설정에서 읽는다. 토큰은 읽지 않는다."""

    from ...core.config import get_settings

    try:
        policy = load_briefing_policy()
    except BriefingPolicyError as error:
        raise BriefingError(error.code) from None
    settings = get_settings()
    return _MessageInputs(
        base_url=settings.public_base_url,
        items_per_message=policy.slack_items_per_message,
        deadline_warning_days=policy.deadline_warning_days,
        channel_id_present=bool(settings.slack_channel_id.strip()),
    )


def briefing_slack_preview(session: Session, briefing_date: date) -> BriefingSlackPreview:
    """`GET /api/briefings/{date}/slack-preview`. 브리핑이 없으면 `briefing_not_found`."""

    view = get_briefing_view(session, briefing_date)
    inputs = _message_inputs()
    return slack_preview(
        view,
        base_url=inputs.base_url,
        items_per_message=inputs.items_per_message,
        deadline_warning_days=inputs.deadline_warning_days,
        channel_id_present=inputs.channel_id_present,
    )


# --- 전송 (`build-briefing --send`) ---------------------------------------------


@dataclass(frozen=True)
class BriefingSendOutcome:
    """CLI `slack` 출력과 경고. `message_ts`는 이번 실행에서 보낸 순서의 ts다."""

    sent: bool
    message_ts: tuple[str, ...] = ()
    skipped_reason: str | None = None
    warning: str | None = None
    error_code: str | None = None


def send_briefing(
    session: Session,
    briefing_date: date,
    sender: SlackSender,
    *,
    now: datetime,
) -> BriefingSendOutcome:
    """기준일 브리핑을 Slack에 한 번 보낸다. 호출자가 성공·실패 모두 commit한다.

    검사 순서(하나라도 걸리면 네트워크에 닿지 않는다): 전송기 검사(`slack_disabled`·
    `token_missing`·`channel_missing`·`host_not_allowed`) → 행 없음·`status=empty`·보낼 메시지
    없음(`empty`) → `slack_sent_at`이 이미 있음(`already_sent`).

    추천 메시지 다음 추적 변화 메시지를 보내고, 보낸 ts를 메시지마다 바로
    `slack_message_ts`·`tracked_change_message_ts`(보낸 순서의 배열)에 덧붙인다. 전부 보낸
    뒤에만 `slack_sent_at`을 남긴다. 중간에 실패하면 `slack_send_failed` 경고와 함께 그때까지
    보낸 ts만 남기며, `--send` 재실행은 이미 ts가 있는 메시지를 건너뛰고 나머지만 보낸다
    (같은 메시지를 두 번 보내지 않는다).
    """

    reason = sender.preflight()
    if reason is not None:
        return BriefingSendOutcome(sent=False, skipped_reason=reason)
    briefing = session.scalar(
        select(Briefing).where(Briefing.briefing_date == briefing_date).with_for_update()
    )
    if briefing is None or briefing.status == "empty":
        return BriefingSendOutcome(sent=False, skipped_reason=SKIP_EMPTY)
    if briefing.slack_sent_at is not None:
        return BriefingSendOutcome(sent=False, skipped_reason=SKIP_ALREADY_SENT)
    view = get_briefing_view(session, briefing_date)
    inputs = _message_inputs()
    messages = build_briefing_messages(
        view,
        base_url=inputs.base_url,
        items_per_message=inputs.items_per_message,
        deadline_warning_days=inputs.deadline_warning_days,
    )
    if not messages:
        return BriefingSendOutcome(sent=False, skipped_reason=SKIP_EMPTY)

    stored = {
        "recommendation": [str(ts) for ts in (briefing.slack_message_ts or [])],
        "tracked_change": [str(ts) for ts in (briefing.tracked_change_message_ts or [])],
    }
    seen = {"recommendation": 0, "tracked_change": 0}
    posted: list[str] = []
    for message in messages:
        index = seen[message.kind]
        seen[message.kind] += 1
        if index < len(stored[message.kind]):
            continue  # 지난 실행에서 이미 보낸 메시지
        try:
            ts = sender.post_message(blocks=message.blocks, text=message.text, allowed_keys=SLACK_PAYLOAD_KEYS)
        except SlackTransportError as error:
            session.flush()
            return BriefingSendOutcome(
                sent=False,
                message_ts=tuple(posted),
                warning=WARNING_SLACK_SEND_FAILED,
                error_code=error.code,
            )
        posted.append(ts)
        stored[message.kind].append(ts)
        # JSON 열은 새 list를 넣어야 변경이 기록된다.
        if message.kind == "recommendation":
            briefing.slack_message_ts = list(stored["recommendation"])
        else:
            briefing.tracked_change_message_ts = list(stored["tracked_change"])
        session.flush()
    briefing.slack_sent_at = now
    session.flush()
    return BriefingSendOutcome(sent=True, message_ts=tuple(posted))


# --- 반응 뒤 메시지 갱신 (Socket Mode worker) -------------------------------------


@dataclass(frozen=True)
class ReactionMessageUpdate:
    """`chat.update` 한 건: 보낸 메시지의 ts와 그 메시지 전체를 현재 반응으로 다시 그린 것."""

    ts: str
    message: SlackMessage


def reaction_update_message(
    session: Session,
    item_id: UUID,
    *,
    item_notes: Mapping[UUID, str] | None = None,
) -> ReactionMessageUpdate | None:
    """항목이 들어 있던 추천 메시지를 현재 DB 반응으로 다시 그린다.

    `chat.update`는 메시지 전체를 바꾸므로, 같은 메시지의 다른 항목도 현재 반응대로 그린다
    (먼저 Slack에서 누른 항목이 버튼으로 되돌아가지 않는다). ts는 이 브리핑이 보낸
    `slack_message_ts`에서만 고른다 — 보낸 적 없는 메시지는 `None`(갱신하지 않는다).
    """

    item = session.get(BriefingItem, item_id)
    if item is None or item.kind != "recommendation":
        return None
    briefing = session.get(Briefing, item.briefing_id)
    if briefing is None:
        return None
    sent = [str(ts) for ts in (briefing.slack_message_ts or [])]
    view = get_briefing_view(session, briefing.briefing_date)
    inputs = _message_inputs()
    position = next((index for index, view_item in enumerate(view.items) if view_item.item_id == item_id), None)
    if position is None:
        return None
    message_index = position // inputs.items_per_message
    if message_index >= len(sent):
        return None
    messages = [
        message
        for message in build_briefing_messages(
            view,
            base_url=inputs.base_url,
            items_per_message=inputs.items_per_message,
            deadline_warning_days=inputs.deadline_warning_days,
            show_reactions=True,
            item_notes=item_notes,
        )
        if message.kind == "recommendation"
    ]
    if message_index >= len(messages):
        return None
    return ReactionMessageUpdate(ts=sent[message_index], message=messages[message_index])


__all__ = [
    "REACTION_LABELS",
    "RECOMMENDATION_HEADER",
    "SKIP_ALREADY_SENT",
    "SKIP_EMPTY",
    "SLACK_BUTTONS",
    "SLACK_PAYLOAD_KEYS",
    "SLACK_REACT_ACTION_ID",
    "TRACKED_CHANGE_HEADER",
    "UNDO_LABEL",
    "UNDO_REACTION",
    "WARNING_SLACK_SEND_FAILED",
    "BriefingSendOutcome",
    "ReactionMessageUpdate",
    "SlackMessage",
    "briefing_slack_preview",
    "build_briefing_messages",
    "reaction_update_message",
    "send_briefing",
    "slack_preview",
]
