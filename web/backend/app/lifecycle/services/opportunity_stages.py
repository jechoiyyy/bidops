"""사업기회 레코드의 단계 바 6단계와 레코드 제목 규칙 (RL-02 spec "단계 바"·"레코드 헤더").

순수 함수다. DB를 조회하지 않고, 호출자가 넘긴 연결(이미 적재된 대상 레코드 포함)과 기준
시각만 본다.

- 권위 연결 = contracts "마감 임박 창"의 정의(`official`·`확정` 또는 `candidate`·
  `사람 확인 완료`·`accepted`). Python 쪽 판정은 `is_authoritative_link` 하나다.
- 단계 구분: 발주계획 = `stage=order_plan`; 사전규격 = `stage=notice` ∧
  `Notice.source_type ∈ PRE_SPEC_SOURCE_TYPES`; 입찰공고 = `stage=notice` ∧
  `source_type='bid_notice'`. 그 밖의 공고 종류와 대상이 아직 적재되지 않은 공식 연결은
  단계를 정하지 않는다(추정하지 않는다).
- 한 단계에 권위 연결이 여럿이면 연결 시각(`created_at`)이 가장 늦은 것, 같으면 연결 id가
  큰 것이 그 단계를 대표한다(제목·마감·개찰). 응답 `stages[].link_id`가 그 대표 연결 id이며
  (마감·개찰은 입찰공고 대표), 화면은 이 규칙을 다시 만들지 않고 그 id로 연결을 찾는다.
- 개찰은 입찰공고 `lifecycle_json.opening_at`(timezone-aware ISO)만 읽는다. 키가 없거나
  `null`이거나 시간대 없는 값이면 미확인이다. 계약은 데이터가 없으므로 언제나 미확인이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from ..models import OpportunityLink
from ..schemas.opportunity_activity import OpportunityStageView
from .opportunity_candidates import PRE_SPEC_SOURCE_TYPES
from .opportunity_integrity import is_authoritative_link

RecordStage = Literal["order_plan", "pre_spec", "bid_notice"]
#: 연결 단계의 앞→뒤 순서. 제목·현재 단계는 이 순서의 가장 뒤 단계다.
RECORD_STAGES: tuple[RecordStage, ...] = ("order_plan", "pre_spec", "bid_notice")
BID_NOTICE_SOURCE_TYPE = "bid_notice"


@dataclass(frozen=True)
class StageRecord:
    """권위 연결 하나를 단계 판정에 필요한 값만으로 줄인 것."""

    stage: RecordStage
    link_id: int
    #: 연결 시각(`OpportunityLink.created_at`). 단계 `at`과 활동 피드 시각이 같은 값을 쓴다.
    linked_at: datetime
    title: str | None
    #: 입찰공고·사전규격의 `Notice.deadline_at`. 마감 단계는 입찰공고 값만 본다.
    deadline_at: datetime | None = None
    #: 입찰공고 `lifecycle_json.opening_at`(aware ISO만).
    opening_at: datetime | None = None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        # 저장 계층은 aware 시각만 돌려준다. 시간대 없는 값은 시각을 추정하지 않는다.
        return None
    return value.astimezone(UTC)


def opening_at_from_lifecycle(lifecycle: Any) -> datetime | None:
    """`lifecycle_json.opening_at`의 aware ISO 값. 없거나 읽을 수 없으면 `None`(미확인)."""

    if not isinstance(lifecycle, Mapping):
        return None
    value = lifecycle.get("opening_at")
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _utc(parsed)


def record_stage(link: OpportunityLink) -> RecordStage | None:
    """권위 연결의 레코드 단계. 권위 연결이 아니거나 대상이 없으면 `None`."""

    if not is_authoritative_link(link):
        return None
    if link.stage == "order_plan":
        return "order_plan" if link.order_plan is not None else None
    if link.stage != "notice" or link.notice is None:
        return None
    source_type = link.notice.source_type
    if source_type in PRE_SPEC_SOURCE_TYPES:
        return "pre_spec"
    if source_type == BID_NOTICE_SOURCE_TYPE:
        return "bid_notice"
    return None


def stage_records(links: Iterable[OpportunityLink]) -> tuple[StageRecord, ...]:
    """연결 목록에서 단계가 정해지는 권위 연결만 골라 단계 순서·연결 순서로 돌려준다."""

    records: list[StageRecord] = []
    for link in links:
        stage = record_stage(link)
        if stage is None:
            continue
        linked_at = _utc(link.created_at)
        if linked_at is None:
            continue
        if stage == "order_plan":
            plan = link.order_plan
            records.append(StageRecord(stage=stage, link_id=link.id, linked_at=linked_at, title=plan.title))
            continue
        notice = link.notice
        records.append(
            StageRecord(
                stage=stage,
                link_id=link.id,
                linked_at=linked_at,
                title=notice.title,
                deadline_at=_utc(notice.deadline_at),
                opening_at=(
                    opening_at_from_lifecycle(notice.lifecycle_json)
                    if stage == "bid_notice"
                    else None
                ),
            )
        )
    order = {stage: index for index, stage in enumerate(RECORD_STAGES)}
    records.sort(key=lambda record: (order[record.stage], record.linked_at, record.link_id))
    return tuple(records)


def representatives(records: Iterable[StageRecord]) -> dict[RecordStage, StageRecord]:
    """단계별 대표 연결: 연결 시각이 가장 늦은 것, 같으면 연결 id가 큰 것."""

    chosen: dict[RecordStage, StageRecord] = {}
    for record in records:
        current = chosen.get(record.stage)
        if current is None or (record.linked_at, record.link_id) > (current.linked_at, current.link_id):
            chosen[record.stage] = record
    return chosen


def current_stage(records: Iterable[StageRecord]) -> RecordStage | None:
    """권위 연결 중 가장 뒤 단계. 연결이 없으면 `None`."""

    present = representatives(records)
    for stage in reversed(RECORD_STAGES):
        if stage in present:
            return stage
    return None


def record_title(records: Iterable[StageRecord]) -> str | None:
    """가장 뒤 단계 대표 연결의 제목. 없거나 비어 있으면 `None`(호출자가 `#<id>`를 쓴다)."""

    present = representatives(records)
    stage = current_stage(present.values())
    if stage is None:
        return None
    title = present[stage].title
    if not isinstance(title, str) or not title.strip():
        return None
    return title.strip()


def _view(key: str, state: str, at: datetime | None, link_id: int | None) -> OpportunityStageView:
    return OpportunityStageView(key=key, state=state, at=at, link_id=link_id)


def stage_views(records: Sequence[StageRecord] | Iterable[StageRecord], *, now: datetime) -> list[OpportunityStageView]:
    """6단계 state와 시각. spec 표를 그대로 옮기고, 표에 맞지 않는 칸은 "그 밖" 규칙을 쓴다."""

    reference = _utc(now)
    if reference is None:
        raise ValueError("now must be timezone-aware")
    present = representatives(records)
    latest = current_stage(present.values())
    bid = present.get("bid_notice")

    # (key, state | None, at, link_id). state None은 표의 어느 칸에도 맞지 않아 "그 밖" 규칙으로
    # 정한다. link_id는 그 단계를 대표하는 권위 연결이고 마감·개찰은 입찰공고 대표를 따른다.
    cells: list[tuple[str, str | None, datetime | None, int | None]] = []
    for stage in RECORD_STAGES:
        record = present.get(stage)
        if record is None:
            cells.append((stage, None, None, None))
            continue
        if stage != latest:
            cells.append((stage, "done", record.linked_at, record.link_id))
        elif stage == "bid_notice" and record.deadline_at is not None and record.deadline_at < reference:
            # 가장 뒤 단계지만 마감이 지났다 — 입찰공고는 끝났고 마감 단계가 done이다.
            cells.append((stage, "done", record.linked_at, record.link_id))
        else:
            cells.append((stage, "current", record.linked_at, record.link_id))

    bid_link_id = bid.link_id if bid is not None else None
    if bid is None or bid.deadline_at is None:
        cells.append(("deadline", "unknown", None, bid_link_id))
    elif bid.deadline_at < reference:
        cells.append(("deadline", "done", bid.deadline_at, bid_link_id))
    else:
        cells.append(("deadline", "upcoming_deadline", bid.deadline_at, bid_link_id))

    if bid is None or bid.opening_at is None:
        cells.append(("opening", "unknown", None, bid_link_id))
    elif bid.opening_at < reference:
        cells.append(("opening", "done", bid.opening_at, bid_link_id))
    else:
        cells.append(("opening", "upcoming_deadline", bid.opening_at, bid_link_id))

    cells.append(("contract", "unknown", None, None))

    views: list[OpportunityStageView] = []
    for index, (key, state, at, link_id) in enumerate(cells):
        if state is None:
            later_reached = any(later in {"done", "current"} for _, later, _, _ in cells[index + 1 :])
            # 뒤 단계가 이미 왔으면 건너뛴 단계다. 있었는지 추정하지 않는다.
            state = "unknown" if later_reached else "pending"
        views.append(_view(key, state, at, link_id))
    return views


__all__ = [
    "BID_NOTICE_SOURCE_TYPE",
    "RECORD_STAGES",
    "RecordStage",
    "StageRecord",
    "current_stage",
    "opening_at_from_lifecycle",
    "record_stage",
    "record_title",
    "representatives",
    "stage_records",
    "stage_views",
]
