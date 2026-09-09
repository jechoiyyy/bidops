"""합성 analysis worker가 개요 슬롯에서 부르는 진입점 (명세 §6.3).

**단독 진입점이 아니다.** `python -m` 대상 module을 만들지 않으며, 이 함수는
`app/workers/analysis.py`의 한 poll 안에서만 불린다. 개요 전용 process를 따로
띄우면 모델 슬롯 1개 보장이 깨진다.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from ..services.prespec_overview_runner import OverviewRunResult, PreSpecOverviewRunner
from ..services.prespec_v4_runner import PrespecV4OverviewRunner, V4RunResult


def run_once(
    session: Session,
    worker_id: str,
    *,
    runner: Any | None = None,
) -> OverviewRunResult | V4RunResult:
    """개요 attempt를 최대 하나 진행시킨다."""

    return (runner or PreSpecOverviewRunner()).run_once(session, worker_id)


__all__ = ["OverviewRunResult", "PreSpecOverviewRunner", "PrespecV4OverviewRunner", "V4RunResult", "run_once"]
