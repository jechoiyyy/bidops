"""사전규격 개요 run의 **읽기 전용** 투영 (MVP 계약).

P1에서는 읽기만 한다. enqueue·claim·모델 호출·상태 전이는 **P2에서 추가**한다.
여기 있는 것은 목록·상세·자동 준비·회사 핏이 "이 공고의 현재 개요가 무엇인가"를
한 번의 batch 조회로 묻는 자리다. 공고 수에 따라 조회를 늘리지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PrespecOverviewRun


def current_runs(
    session: Session, notice_ids: Sequence[int]
) -> dict[int, PrespecOverviewRun | None]:
    """공고별 `created_at` 최신 run. 없는 공고는 ``None``이다.

    조회는 공고 수와 무관하게 한 번이다 (명세 §8의 N+1 금지).
    """

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    latest: dict[int, PrespecOverviewRun] = {}
    for row in session.scalars(
        select(PrespecOverviewRun)
        .where(PrespecOverviewRun.notice_id.in_(ids))
        .order_by(
            PrespecOverviewRun.notice_id.asc(),
            PrespecOverviewRun.created_at.desc(),
            PrespecOverviewRun.id.desc(),
        )
    ).all():
        latest.setdefault(int(row.notice_id), row)
    return {notice_id: latest.get(notice_id) for notice_id in ids}


def overview_status_for(run: PrespecOverviewRun | None) -> str | None:
    """run 상태를 목록 계약의 개요 상태로 그대로 옮긴다.

    run이 없으면 ``None``이다. 없는 것을 실행 중이나 실패로 승격시키지 않는다.
    """

    return str(run.status) if run is not None else None


def completed_result(run: PrespecOverviewRun | None) -> Mapping[str, Any] | None:
    """완료된 run의 `result_json`. 그 밖의 상태에서는 ``None``이다."""

    if run is None or run.status != "completed":
        return None
    result = run.result_json
    return result if isinstance(result, Mapping) else None


__all__ = ["completed_result", "current_runs", "overview_status_for"]
