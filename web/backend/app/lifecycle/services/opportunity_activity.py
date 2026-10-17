"""사업기회 활동 피드 파생 (RL-02 spec "활동 피드 `GET /api/opportunities/{id}/activity`").

피드는 저장하지 않는다. 이미 append-only인 원본에서 요청마다 파생한다.

| kind | 원본 |
|---|---|
| `order_plan_found`·`pre_spec_opened`·`bid_posted` | 권위 연결(`opportunity_stages.stage_records`)의 `created_at` |
| `notice_corrected` | 권위 연결 공고의 `NoticeObservation` 중 첫 관측을 뺀 것, 추적 필드 교집합이 있을 때 |
| `tracking_decided` | 감사 `opportunity.tracking_status.changed` |
| `recheck_signal` | 감사 `opportunity.recheck_signal.created`·`.acknowledged` |
| `link_reviewed` | `human_decision`이 있는 후보 연결 |
| `briefing_reacted` | `briefing_reaction_event` 중 `new ≠ 대기` |
| `note_added`·`action_added`·`action_done` | `opportunity_note` |
| `verdict_completed`·`draft_prepared` | 확장점 `opportunity_activity_items`(제공자 없으면 0건) |

시스템 처리(수집 회차·변환·모델 호출·정책)는 어떤 kind에도 넣지 않는다 — 위 원본 밖의 감사
action과 회차·경고 테이블은 읽지 않는다. 사업기회 하나의 원본만 상수 회 조회로 읽고, 정렬·
커서·`kinds` 필터는 lifecycle 항목과 확장점 항목을 합친 뒤 한 번에 적용한다.

- `item_id` = `"<kind>:<원본 PK>"`. 정렬은 `at` 내림, 동률이면 `item_id` 내림(문자열).
- 커서 `before` = `"<at ISO>|<item_id>"`. 그 키보다 엄격히 뒤(정렬상 아래)인 항목만 돌려주므로
  같은 시각 묶음 가운데에서 페이지가 끊겨도 빠지거나 겹치지 않는다.
- 병합된 사업기회도 읽는다(`merged_into_opportunity_id`로 화면이 리다이렉트한다).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...core.models import AuditEvent
from ..extensions import extension_registry
from ..models import (
    Briefing,
    BriefingItem,
    BriefingReactionEvent,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OpportunityNote,
)
from ..schemas.opportunity_activity import (
    ACTIVITY_LIMIT_DEFAULT,
    ACTIVITY_LIMIT_MAX,
    OPPORTUNITY_ACTIVITY_KINDS,
    OPPORTUNITY_ACTIVITY_SCHEMA_VERSION,
    ActivityItem,
    ActivityLink,
    OpportunityActivityResponse,
)
from .opportunity_stages import StageRecord, record_title, stage_records, stage_views
from .opportunity_tracking import (
    ACKNOWLEDGED_RECHECK_ACTION,
    HUMAN_TRACKING_ACTION,
    SYSTEM_RECHECK_ACTION,
    OpportunityTrackingError,
)

#: 정정으로 보는 공고 필드와 피드 표시 이름. 순서가 제목의 필드 순서다. 표시 이름은 RL-01
#: Slack 추적 변화 메시지(`briefing_slack`)와 같다.
CORRECTION_FIELD_LABELS: dict[str, str] = {
    "deadline_at": "마감",
    "title": "제목",
    "budget": "예산",
    "estimated_price": "추정가격",
    "method": "계약방법",
}
NOTE_TITLE_MAX_CHARS = 120
_UNSELECTED = "미선택"
_TRACKING_STATUSES = frozenset({"미선택", "계속 추적", "보류", "종료"})
_WAITING_REACTION = "대기"
_DECISION_LABEL = {"accepted": "수락", "rejected": "거절"}
_KIND_SET = frozenset(OPPORTUNITY_ACTIVITY_KINDS)


def _invalid() -> OpportunityTrackingError:
    return OpportunityTrackingError("invalid_request", "요청이 올바르지 않습니다")


# --- 질의 인자 ----------------------------------------------------------------


def parse_kinds(value: str | None) -> tuple[str, ...] | None:
    """`kinds` csv. 비어 있으면 필터 없음(`None`). 모르는 kind가 하나라도 있으면 422."""

    if value is None or not value.strip():
        return None
    kinds: list[str] = []
    for token in value.split(","):
        kind = token.strip()
        if not kind:
            continue
        if kind not in _KIND_SET:
            raise _invalid()
        if kind not in kinds:
            kinds.append(kind)
    if not kinds:
        raise _invalid()
    return tuple(kinds)


def _wire_time(value: datetime) -> str:
    """응답 JSON의 `at`과 같은 모양(UTC, `Z`)의 ISO 문자열."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def cursor_for(item: ActivityItem) -> str:
    return f"{_wire_time(item.at)}|{item.item_id}"


def _valid_item_id(value: str) -> bool:
    kind, separator, key = value.partition(":")
    return bool(separator) and kind in _KIND_SET and bool(key) and "|" not in value


def parse_cursor(value: str | None) -> tuple[datetime, str] | None:
    """opaque 커서 `"<at ISO>|<item_id>"`. 읽을 수 없으면 422(`invalid_request`)."""

    if value is None:
        return None
    raw_at, separator, item_id = value.partition("|")
    if not separator or not _valid_item_id(item_id):
        raise _invalid()
    try:
        parsed = datetime.fromisoformat(raw_at)
    except ValueError:
        raise _invalid() from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid()
    return parsed.astimezone(UTC), item_id


def _checked_limit(limit: Any) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= ACTIVITY_LIMIT_MAX:
        raise _invalid()
    return limit


# --- 문장 규칙 ------------------------------------------------------------------


def _final_consonant(word: str) -> int | None:
    """마지막 글자가 한글 음절이면 받침 번호(0=없음), 아니면 `None`."""

    if not word:
        return None
    last = word[-1]
    if "가" <= last <= "힣":
        return (ord(last) - ord("가")) % 28
    return None


def _subject(name: str) -> str:
    """`<이름>이`·`<이름>가`. 한글 음절이 아닌 끝 글자는 spec 표기 그대로 `이`를 붙인다."""

    final = _final_consonant(name)
    return f"{name}가" if final == 0 else f"{name}이"


def _toward(word: str) -> str:
    """`<상태>로`·`<상태>으로`(받침이 있고 ㄹ이 아니면 `으로`)."""

    final = _final_consonant(word)
    return f"{word}으로" if final not in (None, 0, 8) else f"{word}로"


def _note_title(body: str) -> str:
    first_line = body.strip().splitlines()[0] if body.strip() else body
    return first_line.strip()[:NOTE_TITLE_MAX_CHARS] or body[:NOTE_TITLE_MAX_CHARS]


def _external_link(url: Any, label: str) -> ActivityLink | None:
    """공고 외부 URL. http(s)가 아닌 값은 링크로 내보내지 않는다."""

    if not isinstance(url, str):
        return None
    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return ActivityLink(label=label, path=candidate)


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _changed_names(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {name for name in value if isinstance(name, str)}
    if isinstance(value, (list, tuple)):
        return {name for name in value if isinstance(name, str)}
    return set()


# --- 원본별 파생 ----------------------------------------------------------------


def _record_items(records: Sequence[StageRecord], links: Mapping[int, OpportunityLink]) -> list[ActivityItem]:
    items: list[ActivityItem] = []
    for record in records:
        link = links[record.link_id]
        if record.stage == "order_plan":
            agency = (link.order_plan.agency_name or "").strip()
            items.append(
                ActivityItem(
                    item_id=f"order_plan_found:{link.id}",
                    kind="order_plan_found",
                    at=record.linked_at,
                    title=f"발주계획 발견 · {agency}" if agency else "발주계획 발견",
                    link=ActivityLink(label="발주계획 보기", path=f"/order-plans/{link.order_plan_id}"),
                )
            )
        elif record.stage == "pre_spec":
            items.append(
                ActivityItem(
                    item_id=f"pre_spec_opened:{link.id}",
                    kind="pre_spec_opened",
                    at=record.linked_at,
                    title="사전규격 공개",
                    link=ActivityLink(label="사전규격 보기", path=f"/pre-specs/{link.notice_id}"),
                )
            )
        else:
            items.append(
                ActivityItem(
                    item_id=f"bid_posted:{link.id}",
                    kind="bid_posted",
                    at=record.linked_at,
                    title="입찰공고 게시",
                    # 내부 입찰공고 상세 라우트는 없다. 공고 외부 URL을 새 창으로 연다.
                    link=_external_link(link.notice.url, "공고 원문"),
                )
            )
    return items


def _correction_items(
    session: Session, records: Sequence[StageRecord], links: Mapping[int, OpportunityLink]
) -> list[ActivityItem]:
    notice_stage: dict[int, tuple[str, OpportunityLink]] = {}
    for record in records:
        if record.stage in {"pre_spec", "bid_notice"}:
            link = links[record.link_id]
            notice_stage[link.notice_id] = (record.stage, link)
    if not notice_stage:
        return []
    observations = session.scalars(
        select(NoticeObservation)
        .where(NoticeObservation.notice_id.in_(sorted(notice_stage)))
        # 적재기는 적재 순서로 `is_new`를 정한다(옛 회차가 나중에 적재돼도 먼저 적재된 관측이
        # 첫 관측이다). 그래서 첫 관측은 `observed_at`이 아니라 관측 id(적재 순서)로 고른다.
        .order_by(NoticeObservation.notice_id, NoticeObservation.id)
    ).all()
    items: list[ActivityItem] = []
    seen_first: set[int] = set()
    for observation in observations:
        if observation.notice_id not in seen_first:
            # 첫 관측(`is_new`)은 정정이 아니다. 바뀐 필드가 적혀 있어도 뺀다.
            seen_first.add(observation.notice_id)
            continue
        changed = _changed_names(observation.changed_fields_json)
        fields = [name for name in CORRECTION_FIELD_LABELS if name in changed]
        observed_at = _utc(observation.observed_at)
        if not fields or observed_at is None:
            continue
        stage, link = notice_stage[observation.notice_id]
        target = (
            ActivityLink(label="변경 이력", path=f"/pre-specs/{link.notice_id}#ps-record-history")
            if stage == "pre_spec"
            else _external_link(link.notice.url, "공고 원문")
        )
        items.append(
            ActivityItem(
                item_id=f"notice_corrected:{observation.id}",
                kind="notice_corrected",
                at=observed_at,
                title="정정 · " + ", ".join(CORRECTION_FIELD_LABELS[name] for name in fields),
                link=target,
            )
        )
    return items


def _audit_items(session: Session, opportunity_id: int) -> list[ActivityItem]:
    audits = session.scalars(
        select(AuditEvent).where(
            AuditEvent.action.in_((HUMAN_TRACKING_ACTION, SYSTEM_RECHECK_ACTION, ACKNOWLEDGED_RECHECK_ACTION)),
            AuditEvent.aggregate_type == "opportunity",
            AuditEvent.aggregate_id == str(opportunity_id),
        )
    ).all()
    items: list[ActivityItem] = []
    for audit in audits:
        event_at = _utc(audit.created_at)
        if event_at is None:
            continue
        name = audit.claimed_name.strip() if isinstance(audit.claimed_name, str) and audit.claimed_name.strip() else None
        if audit.action == HUMAN_TRACKING_ACTION:
            metadata = audit.safe_metadata if isinstance(audit.safe_metadata, Mapping) else {}
            status = metadata.get("tracking_status")
            if status not in _TRACKING_STATUSES or name is None:
                continue
            if status == _UNSELECTED:
                reason = metadata.get("reason")
                title, detail = f"{_subject(name)} 추적 되돌림", reason if isinstance(reason, str) and reason else None
            else:
                title, detail = f"{_subject(name)} {_toward(status)} 결정", None
            items.append(
                ActivityItem(
                    item_id=f"tracking_decided:{audit.id}",
                    kind="tracking_decided",
                    at=event_at,
                    actor=name,
                    title=title,
                    detail=detail,
                )
            )
        elif audit.action == SYSTEM_RECHECK_ACTION:
            items.append(
                ActivityItem(item_id=f"recheck_signal:{audit.id}", kind="recheck_signal", at=event_at, title="재확인 신호")
            )
        else:
            items.append(
                ActivityItem(
                    item_id=f"recheck_signal:{audit.id}",
                    kind="recheck_signal",
                    at=event_at,
                    actor=name,
                    title=f"{_subject(name)} 신호 확인" if name else "신호 확인",
                )
            )
    return items


def _review_items(links: Iterable[OpportunityLink]) -> list[ActivityItem]:
    items: list[ActivityItem] = []
    for link in links:
        reviewed_at = _utc(link.reviewed_at)
        reviewer = link.reviewer_name.strip() if isinstance(link.reviewer_name, str) else ""
        if (
            link.link_type != "candidate"
            or link.human_decision not in _DECISION_LABEL
            or reviewed_at is None
            or not reviewer
        ):
            continue
        items.append(
            ActivityItem(
                item_id=f"link_reviewed:{link.id}",
                kind="link_reviewed",
                at=reviewed_at,
                actor=reviewer,
                title=f"{_subject(reviewer)} 연결 후보 {_DECISION_LABEL[link.human_decision]}",
            )
        )
    return items


def _reaction_items(session: Session, opportunity_id: int) -> list[ActivityItem]:
    rows = session.execute(
        select(BriefingReactionEvent, BriefingItem.id, Briefing.briefing_date)
        .join(BriefingItem, BriefingItem.id == BriefingReactionEvent.item_id)
        .join(Briefing, Briefing.id == BriefingItem.briefing_id)
        .where(BriefingItem.opportunity_id == opportunity_id, BriefingReactionEvent.new != _WAITING_REACTION)
    ).all()
    items: list[ActivityItem] = []
    for event, briefing_item_id, briefing_date in rows:
        event_at = _utc(event.created_at)
        if event_at is None:
            continue
        items.append(
            ActivityItem(
                item_id=f"briefing_reacted:{event.id}",
                kind="briefing_reacted",
                at=event_at,
                actor=event.actor,
                title=f"{_subject(event.actor)} {event.new}",
                link=ActivityLink(
                    label="브리핑 보기",
                    path=f"/briefing?date={briefing_date.isoformat()}&selected={briefing_item_id}",
                ),
                status_pill=event.new,
            )
        )
    return items


def _note_items(session: Session, opportunity_id: int) -> list[ActivityItem]:
    notes = session.scalars(select(OpportunityNote).where(OpportunityNote.opportunity_id == opportunity_id)).all()
    items: list[ActivityItem] = []
    for note in notes:
        created_at = _utc(note.created_at)
        if created_at is None:
            continue
        if note.kind == "note":
            items.append(
                ActivityItem(
                    item_id=f"note_added:{note.id}",
                    kind="note_added",
                    at=created_at,
                    actor=note.actor,
                    title=_note_title(note.body),
                )
            )
            continue
        if note.kind != "action":
            continue
        # 다음 행동 제목은 spec 표대로 본문 그대로다(서비스가 이미 trim·2000자로 막는다).
        # 담당은 새 응답 키 없이 `detail="담당 <owner>"`로 싣는다(리더 결정, 화면 NextActions가 읽는다).
        items.append(
            ActivityItem(
                item_id=f"action_added:{note.id}",
                kind="action_added",
                at=created_at,
                actor=note.actor,
                title=f"다음 행동: {note.body}",
                detail=f"담당 {note.owner}" if note.owner else None,
            )
        )
        done_at = _utc(note.done_at)
        if done_at is not None and note.done_by:
            items.append(
                ActivityItem(
                    item_id=f"action_done:{note.id}",
                    kind="action_done",
                    at=done_at,
                    actor=note.done_by,
                    title=f"{_subject(note.done_by)} 완료: {note.body}",
                )
            )
    return items


def _hook_items(session: Session, opportunity_id: int) -> list[ActivityItem]:
    items = extension_registry().opportunity_activity_items(session, opportunity_id)
    return [item.model_copy(update={"at": item.at.astimezone(UTC)}) for item in items]


# --- 조립 -----------------------------------------------------------------------


def _sort_key(item: ActivityItem) -> tuple[datetime, str]:
    return (item.at.astimezone(UTC), item.item_id)


def derive_activity_items(session: Session, opportunity: Opportunity, links: Sequence[OpportunityLink]) -> list[ActivityItem]:
    """사업기회 하나의 모든 활동 항목(정렬 전). lifecycle 원본 + 확장점 제공자."""

    records = stage_records(links)
    by_id = {link.id: link for link in links}
    return [
        *_record_items(records, by_id),
        *_correction_items(session, records, by_id),
        *_audit_items(session, opportunity.id),
        *_review_items(links),
        *_reaction_items(session, opportunity.id),
        *_note_items(session, opportunity.id),
        *_hook_items(session, opportunity.id),
    ]


def opportunity_activity(
    session: Session,
    opportunity_id: int,
    *,
    kinds: Sequence[str] | None = None,
    limit: int = ACTIVITY_LIMIT_DEFAULT,
    before: str | None = None,
    now: datetime,
) -> OpportunityActivityResponse:
    """활동 피드 응답: 제목·6단계·한 페이지의 항목과 다음 커서."""

    page_size = _checked_limit(limit)
    cursor = parse_cursor(before)
    if kinds is not None and any(kind not in _KIND_SET for kind in kinds):
        raise _invalid()
    if not isinstance(opportunity_id, int) or isinstance(opportunity_id, bool):
        raise OpportunityTrackingError("opportunity_not_found", "사업기회를 찾을 수 없습니다")
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise OpportunityTrackingError("opportunity_not_found", "사업기회를 찾을 수 없습니다")
    links = list(
        session.scalars(
            select(OpportunityLink)
            .where(OpportunityLink.opportunity_id == opportunity.id)
            .options(selectinload(OpportunityLink.notice), selectinload(OpportunityLink.order_plan))
            .order_by(OpportunityLink.id)
        ).all()
    )
    records = stage_records(links)

    items = derive_activity_items(session, opportunity, links)
    if kinds is not None:
        wanted = set(kinds)
        items = [item for item in items if item.kind in wanted]
    items.sort(key=_sort_key, reverse=True)
    if cursor is not None:
        items = [item for item in items if _sort_key(item) < cursor]
    page = items[:page_size]
    next_before = cursor_for(page[-1]) if len(items) > page_size else None

    return OpportunityActivityResponse(
        schema_version=OPPORTUNITY_ACTIVITY_SCHEMA_VERSION,
        opportunity_id=opportunity.id,
        merged_into_opportunity_id=opportunity.merged_into_opportunity_id,
        title=record_title(records) or f"#{opportunity.id}",
        stages=stage_views(records, now=now),
        items=page,
        next_before=next_before,
    )


__all__ = [
    "CORRECTION_FIELD_LABELS",
    "NOTE_TITLE_MAX_CHARS",
    "cursor_for",
    "derive_activity_items",
    "opportunity_activity",
    "parse_cursor",
    "parse_kinds",
]
