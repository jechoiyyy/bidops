"""이미 적재된 사전규격을 새 자격 규칙으로 한 번에 준비하는 backfill 명령.

MVP 완화(`overview_eligible`)로 `SW사업대상=Y` 사전규격이 자동 준비 자격을
얻었지만, 자동 준비의 촉발 지점은 회차 적재·등급 변경·첨부 취득 종결 셋뿐이다.
그 셋이 이미 지나간 공고는 아무도 다시 깨우지 않으므로 이 명령이 한 번 태운다.

**모델을 부르지 않는다.** 하는 일은 공고마다 사람 경로와 같은 함수
(`maybe_auto_prepare` → 묶음 초안·확정)를 부르는 것뿐이고, 개요 run은 그 안의
ready 훅(`enqueue_overview_run`)이 넣는다. 실행은 analysis worker의 개요 slot이
한다.

자격은 `BIDOPS_PRESPEC_OVERVIEW_ENABLED`가 켜져 있어야 `SW사업대상=Y`까지
넓어진다. 꺼져 있으면 이 명령도 기존 등급 규칙(`우선 검토`)만 본다.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any, Sequence

#: 이미 개요를 한 번 태웠다고 보는 run 상태. 대기·실행 중이거나 완료된 run이
#: 있으면 다시 넣지 않는다 — `needs_human_review`·`failed`·`cancelled`는 다시
#: 태울 수 있는 상태다.
_RUN_EXISTS_STATUSES = ("queued", "running", "completed")

#: 준비가 실제로 끝났다고 세는 결과 코드. `bundle_unchanged`는 같은 문서 집합의
#: 확정 묶음이 이미 있다는 뜻이므로 실패가 아니다.
_PREPARED_REASONS = frozenset({None, "bundle_unchanged"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli prepare-overviews",
        description="자격을 갖춘 사전규격의 자동 준비를 한 번에 돌린다 (개요 backfill)",
    )
    parser.add_argument(
        "--all-eligible",
        action="store_true",
        required=True,
        help="자격을 갖추고 첨부 취득이 끝난 사전규격 전부를 대상으로 한다",
    )
    parser.add_argument("--limit", type=int, help="이번 실행에서 처리할 최대 공고 수")
    parser.add_argument(
        "--dry-run", action="store_true", help="대상 목록과 개수만 내고 아무것도 만들지 않는다"
    )
    return parser


def eligible_notice_ids(session: Any, *, settings: Any = None) -> list[int]:
    """자격을 갖추고 첨부 취득이 끝난 사전규격 공고 id (오름차순).

    조건은 셋이다 — `overview_eligible`이 연 자격, 활성 첨부의 취득 행이 **모두**
    종결(`TERMINAL_FETCH_STATUSES`), 그중 `완료`가 하나 이상. 취득 행이 아예
    없는 공고는 대상이 아니다. 준비할 문서가 하나도 없다는 뜻이기 때문이다.
    """

    from sqlalchemy import select

    from ...lifecycle.models import Attachment, Notice
    from ..models import AttachmentFetch
    from ..services.auto_preparation import TERMINAL_FETCH_STATUSES
    from ..services.effective_grade import overview_eligible

    statuses: dict[int, list[str]] = {}
    for notice_id, status in session.execute(
        select(Attachment.notice_id, AttachmentFetch.status)
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .join(Notice, Notice.id == Attachment.notice_id)
        .where(Notice.source_type == "pre_spec", Attachment.retired_at.is_(None))
    ).all():
        statuses.setdefault(int(notice_id), []).append(str(status))

    settled = [
        notice_id
        for notice_id, values in statuses.items()
        if all(value in TERMINAL_FETCH_STATUSES for value in values) and "완료" in values
    ]
    if not settled:
        return []
    eligible = overview_eligible(session, settled, settings=settings)
    return sorted(notice_id for notice_id in settled if notice_id in eligible)


def notices_with_runs(session: Any, notice_ids: Sequence[int]) -> set[int]:
    """대기·실행 중이거나 완료된 개요 run이 이미 있는 공고 id."""

    from sqlalchemy import select

    from ..models import PrespecOverviewRun

    ids = [int(value) for value in notice_ids]
    if not ids:
        return set()
    return {
        int(value)
        for value in session.scalars(
            select(PrespecOverviewRun.notice_id).where(
                PrespecOverviewRun.notice_id.in_(ids),
                PrespecOverviewRun.status.in_(_RUN_EXISTS_STATUSES),
            )
        ).all()
    }


def run(session: Any, *, limit: int | None = None, dry_run: bool = False, settings: Any = None) -> dict:
    """대상을 고르고(그리고 dry-run이 아니면) 공고마다 자동 준비를 부른다.

    한 공고의 실패가 다음 공고를 막지 않는다. `maybe_auto_prepare`가 이미 실패를
    안전 코드로만 돌려주므로 여기서 예외를 다시 삼키지 않는다.
    """

    from ..services.auto_preparation import maybe_auto_prepare
    from ..services.overview_runs import active_run

    targets = eligible_notice_ids(session, settings=settings)
    skipped: Counter[str] = Counter()

    existing = notices_with_runs(session, targets)
    skipped["run_exists"] = len(existing)
    pending = [notice_id for notice_id in targets if notice_id not in existing]
    if limit is not None and limit >= 0 and len(pending) > limit:
        skipped["limit_reached"] = len(pending) - limit
        pending = pending[:limit]

    summary = {
        "eligible": len(targets),
        "prepared": 0,
        "enqueued": 0,
        "skipped_by_reason": {key: value for key, value in sorted(skipped.items()) if value},
    }
    if dry_run:
        for notice_id in pending:
            print(f"{notice_id}\tdry_run\t-")
        summary["dry_run"] = True
        summary["targets"] = pending
        return summary

    prepared = 0
    enqueued = 0
    for notice_id in pending:
        outcome = maybe_auto_prepare(session, [notice_id])[0]
        session.commit()
        code = outcome.reason or "confirmed"
        if outcome.reason in _PREPARED_REASONS:
            prepared += 1
        else:
            skipped[code] += 1
        has_run = active_run(session, notice_id) is not None
        if has_run:
            enqueued += 1
        print(f"{notice_id}\t{code}\t{'enqueued' if has_run else '-'}")
    summary["prepared"] = prepared
    summary["enqueued"] = enqueued
    summary["skipped_by_reason"] = {
        key: value for key, value in sorted(skipped.items()) if value
    }
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from ...core.config import get_settings
        from ...core.db import SessionLocal, init_db

        settings = get_settings()
        init_db()
        with SessionLocal() as session:
            summary = run(
                session, limit=args.limit, dry_run=args.dry_run, settings=settings
            )
    except Exception:
        # 예외 본문·경로는 내지 않는다. 안정 코드 하나만 남긴다.
        print(json.dumps({"error": "prepare_overviews_failed"}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ["build_parser", "eligible_notice_ids", "main", "notices_with_runs", "run"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("이 명령은 `python -m app.deep_review.cli prepare-overviews <인자>`로 실행한다")
