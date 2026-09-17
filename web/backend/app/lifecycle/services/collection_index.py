"""수집 색인 쓰기·조회와 선별 통계 (spec §2.1·§2.2).

색인은 수집 회차의 **모든** 레코드를 한 행씩 남기는 검색용 투영이다. 사업기회나
공고가 아니고 원문도 아니다. 이 모듈은 색인 행을 만들고, 공식 키로 최신 행을
찾고, 회차별 선별 통계를 센다. 무엇을 적재할지 고르고 회차 파일에서 레코드를
다시 읽어 적재하는 흐름은 적재기(`ingest/loader.py`)가 맡는다 — 적재 경로
(`_upsert_notice`)와 공식 키 해석이 그쪽에 있기 때문이다.

`null`은 추정으로 채우지 않는다. 조건에 쓰는 값이 비어 있으면 그 조건은 불일치다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import CollectedRecordIndex, CollectedRecordToken, Run
from .name_matching import normalize


RECORD_KINDS = ("order_plan", "pre_spec", "bid_notice")

#: 선별 사유 코드 (spec §2.2). DB CHECK ``ck_collected_record_index_selection_reason``와
#: 같은 닫힌 집합이다.
SELECTION_REASONS = (
    "order_plan_all",
    "pre_spec_sw",
    "pre_spec_referenced",
    "bid_same_notice_no",
    "bid_tracked_reference",
    "bid_sw_prespec_reference",
    "bid_sw_industry_competitive",
    "tracked_backfill",
    "search_result",
)

#: 통계에 늘 싣는 원천별 사유. 추적 보충·찾아보기 사유는 실제로 쓰인 회차에만 나온다.
STATS_REASONS: dict[str, tuple[str, ...]] = {
    "order_plan": ("order_plan_all",),
    "pre_spec": ("pre_spec_sw", "pre_spec_referenced"),
    "bid_notice": (
        "bid_same_notice_no",
        "bid_tracked_reference",
        "bid_sw_prespec_reference",
        "bid_sw_industry_competitive",
    ),
}

#: 입찰공고 선별 ①이 보는 추적 상태 (결정 1).
TRACKED_REFERENCE_STATUSES = ("계속 추적", "보류", "종료")
#: 추적 보충이 보는 추적 상태 (spec §5).
BACKFILL_TRACKING_STATUSES = ("계속 추적", "보류")

TOKEN_MAX_LENGTH = 32
_IN_CHUNK = 500


@dataclass(frozen=True)
class IndexValues:
    """색인 한 행의 값. 원문에 없는 값은 ``None``으로 둔다."""

    record_kind: str
    record_key: str
    title: str | None = None
    agency: str | None = None
    demand_agency: str | None = None
    order_plan_unty_no: str | None = None
    bf_spec_rgst_no: str | None = None
    bid_no: str | None = None
    bid_ord: str | None = None
    sw_business_status: str | None = None
    sw_industry_1468: str | None = None
    contract_method: str | None = None
    published_at: datetime | None = None
    tokens: tuple[str, ...] = field(default_factory=tuple)

    @property
    def identity(self) -> tuple[str, str]:
        return self.record_kind, self.record_key


def index_text(value: Any) -> str | None:
    """Trim a scalar source value; blank and non-scalar values stay ``None``."""

    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        return None
    text = str(value).strip()
    return text or None


def title_normalized(title: str | None) -> str | None:
    """`name_matching.normalize` of a title, ``None`` when nothing remains."""

    if title is None:
        return None
    value = normalize(title)
    return value or None


def split_tokens(value: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a ``bidNtceNoList`` value into stored and unindexable tokens.

    The comma-separated list is trimmed and empty pieces are dropped.  Tokens
    keep their observed spelling; nothing is sliced into a guessed shape.  A
    token longer than the column is returned separately so the caller can
    warn instead of truncating it.
    """

    if isinstance(value, (list, tuple)):
        pieces = [index_text(item) for item in value]
    else:
        text = index_text(value)
        pieces = [item.strip() for item in text.split(",")] if text is not None else []
    stored: list[str] = []
    rejected: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        target = stored if len(piece) <= TOKEN_MAX_LENGTH else rejected
        if piece not in target:
            target.append(piece)
    return tuple(stored), tuple(rejected)


def chunks(values: Iterable[Any], size: int = _IN_CHUNK) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def upsert_index_rows(
    session: Session,
    run_id: str,
    values: Sequence[IndexValues],
) -> dict[tuple[str, str], CollectedRecordIndex]:
    """Insert missing rows for one run and return every row by identity.

    The unique ``(run_id, record_kind, record_key)`` identity makes a replay a
    no-op: an existing row is returned unchanged, including the selection it
    already recorded.  The first occurrence of a duplicated identity wins; the
    caller decides whether a duplicate is worth a warning.
    """

    rows: dict[tuple[str, str], CollectedRecordIndex] = {
        (row.record_kind, row.record_key): row
        for row in session.scalars(
            select(CollectedRecordIndex).where(CollectedRecordIndex.run_id == run_id)
        )
    }
    for item in values:
        if item.identity in rows:
            continue
        row = CollectedRecordIndex(
            run_id=run_id,
            record_kind=item.record_kind,
            record_key=item.record_key,
            title=item.title,
            title_normalized=title_normalized(item.title),
            agency=item.agency,
            demand_agency=item.demand_agency,
            order_plan_unty_no=item.order_plan_unty_no,
            bf_spec_rgst_no=item.bf_spec_rgst_no,
            bid_no=item.bid_no,
            bid_ord=item.bid_ord,
            sw_business_status=item.sw_business_status,
            sw_industry_1468=item.sw_industry_1468,
            contract_method=item.contract_method,
            published_at=item.published_at,
        )
        row.tokens = [CollectedRecordToken(token=token) for token in item.tokens]
        session.add(row)
        rows[item.identity] = row
    session.flush()
    return rows


def mark_selected(
    row: CollectedRecordIndex,
    reason: str,
    *,
    notice_id: int | None = None,
    order_plan_id: int | None = None,
) -> None:
    """Record the first selection reason and the ingested target on a row."""

    if reason not in SELECTION_REASONS:
        raise ValueError(f"unknown selection reason: {reason}")
    if row.selection_reason is None:
        row.selection_reason = reason
    if notice_id is not None:
        row.ingested_notice_id = notice_id
    if order_plan_id is not None:
        row.ingested_order_plan_id = order_plan_id


def _latest_sort_key(row: CollectedRecordIndex, generated_at: datetime | None) -> tuple[Any, ...]:
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    published = row.published_at
    return (
        published is not None,
        published or epoch,
        generated_at or epoch,
        row.id or 0,
    )


def latest_rows(
    session: Session,
    record_kind: str,
    column: Any,
    values: Iterable[str],
    *,
    extra: ColumnElement[bool] | None = None,
) -> dict[str, CollectedRecordIndex]:
    """Return the newest row per ``column`` value among rows of one kind.

    "Newest" is spec §2.1: ``published_at`` first, then the run's generated
    time.  A row without ``published_at`` never outranks one that has it.
    """

    wanted = sorted({value for value in values if value})
    if not wanted:
        return {}
    best: dict[str, tuple[tuple[Any, ...], CollectedRecordIndex]] = {}
    for batch in chunks(wanted):
        statement = (
            select(CollectedRecordIndex, Run.generated_at)
            .join(Run, Run.id == CollectedRecordIndex.run_id)
            .where(CollectedRecordIndex.record_kind == record_kind, column.in_(batch))
        )
        if extra is not None:
            statement = statement.where(extra)
        for row, generated_at in session.execute(statement):
            key_value = getattr(row, column.key)
            rank = _latest_sort_key(row, generated_at)
            current = best.get(key_value)
            if current is None or rank > current[0]:
                best[key_value] = (rank, row)
    return {key: row for key, (_rank, row) in best.items()}


def latest_row_per_identity(
    session: Session,
    rows: Iterable[CollectedRecordIndex],
) -> list[CollectedRecordIndex]:
    """Collapse rows of several runs to the newest row per record identity."""

    by_identity: dict[tuple[str, str], list[CollectedRecordIndex]] = {}
    for row in rows:
        by_identity.setdefault((row.record_kind, row.record_key), []).append(row)
    if not by_identity:
        return []
    run_ids = sorted({row.run_id for group in by_identity.values() for row in group})
    generated: dict[str, datetime] = {}
    for batch in chunks(run_ids):
        for run_id, generated_at in session.execute(
            select(Run.id, Run.generated_at).where(Run.id.in_(batch))
        ):
            generated[run_id] = generated_at
    result = [
        max(group, key=lambda row: _latest_sort_key(row, generated.get(row.run_id)))
        for group in by_identity.values()
    ]
    return sorted(result, key=lambda row: (RECORD_KINDS.index(row.record_kind), row.record_key))


def tokens_for(
    session: Session,
    record_kind: str,
    column: Any,
    values: Iterable[str],
) -> set[str]:
    """Every stored token of index rows of one kind whose ``column`` matches."""

    wanted = sorted({value for value in values if value})
    tokens: set[str] = set()
    for batch in chunks(wanted):
        tokens.update(
            session.scalars(
                select(CollectedRecordToken.token)
                .join(
                    CollectedRecordIndex,
                    CollectedRecordIndex.id == CollectedRecordToken.index_id,
                )
                .where(CollectedRecordIndex.record_kind == record_kind, column.in_(batch))
            )
        )
    return tokens


def rows_with_tokens(
    session: Session,
    record_kind: str,
    tokens: Iterable[str],
) -> list[CollectedRecordIndex]:
    """Index rows of one kind that carry any of ``tokens``."""

    wanted = sorted({token for token in tokens if token})
    found: dict[int, CollectedRecordIndex] = {}
    for batch in chunks(wanted):
        for row in session.scalars(
            select(CollectedRecordIndex)
            .join(
                CollectedRecordToken,
                CollectedRecordToken.index_id == CollectedRecordIndex.id,
            )
            .where(
                CollectedRecordIndex.record_kind == record_kind,
                CollectedRecordToken.token.in_(batch),
            )
        ):
            found[row.id] = row
    return list(found.values())


def selection_stats(session: Session, run_id: str) -> dict[str, dict[str, Any]]:
    """원천별 ``collected``·사유별 ``selected``·``skipped`` (spec §2.2).

    ``collected = sum(selected) + skipped``가 늘 성립한다. 제외는 경고가 아니므로
    경고 표가 아니라 이 통계로만 남는다.
    """

    session.flush()
    stats: dict[str, dict[str, Any]] = {
        kind: {
            "collected": 0,
            "selected": {reason: 0 for reason in STATS_REASONS[kind]},
            "skipped": 0,
        }
        for kind in RECORD_KINDS
    }
    for kind, reason, count in session.execute(
        select(
            CollectedRecordIndex.record_kind,
            CollectedRecordIndex.selection_reason,
            func.count(),
        )
        .where(CollectedRecordIndex.run_id == run_id)
        .group_by(CollectedRecordIndex.record_kind, CollectedRecordIndex.selection_reason)
    ):
        bucket = stats[kind]
        bucket["collected"] += int(count)
        if reason is None:
            bucket["skipped"] += int(count)
        else:
            bucket["selected"][reason] = bucket["selected"].get(reason, 0) + int(count)
    return stats


__all__ = [
    "BACKFILL_TRACKING_STATUSES",
    "IndexValues",
    "RECORD_KINDS",
    "SELECTION_REASONS",
    "STATS_REASONS",
    "TOKEN_MAX_LENGTH",
    "TRACKED_REFERENCE_STATUSES",
    "chunks",
    "index_text",
    "latest_row_per_identity",
    "latest_rows",
    "mark_selected",
    "rows_with_tokens",
    "selection_stats",
    "split_tokens",
    "title_normalized",
    "tokens_for",
    "upsert_index_rows",
]
