"""합성 analysis worker가 개요 슬롯에서 부르는 진입점 (명세 §6.3).

**단독 진입점이 아니다.** `python -m` 대상 module을 만들지 않으며, 이 함수는
`app/workers/analysis.py`의 한 poll 안에서만 불린다. 개요 전용 process를 따로
띄우면 모델 슬롯 1개 보장이 깨진다.

실행 규칙은 전부 `services/overview_runs.py`가 갖는다. 여기 있는 것은 worker
계약(한 poll = 최대 한 건)의 얇은 자리다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..services.overview_runs import OverviewRunResult, run_once as _run_overview_once


def run_once(session: Session, worker_id: str | None = None, **kwargs: Any) -> OverviewRunResult:
    """개요 슬롯의 한 poll. 주입 seam은 그대로 실행기로 넘긴다."""

    return _run_overview_once(session, worker_id, **kwargs)


__all__ = ["OverviewRunResult", "run_once"]
