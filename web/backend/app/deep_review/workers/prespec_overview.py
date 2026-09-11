"""합성 analysis worker가 개요 슬롯에서 부르는 진입점 (명세 §6.3).

**단독 진입점이 아니다.** `python -m` 대상 module을 만들지 않으며, 이 함수는
`app/workers/analysis.py`의 한 poll 안에서만 불린다. 개요 전용 process를 따로
띄우면 모델 슬롯 1개 보장이 깨진다.

지금은 **아무것도 하지 않는 자리**다. 옛 개요 실행 스택(v3·legacy v4·v5)은
철거됐고, 새 계약의 enqueue·claim·실행은 P2에서 이 함수 뒤에 붙는다. 그때까지
한 poll은 언제나 "할 일 없음"으로 닫힌다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class OverviewRunResult:
    """한 poll이 개요 슬롯에서 한 일. 원문·응답·경로는 담지 않는다."""

    claimed: bool
    attempt_id: UUID | None = None
    status: str = "idle"
    reason_code: str | None = None
    expired_leases: int = 0


def run_once(session: Session, worker_id: str | None = None, **_kwargs: Any) -> OverviewRunResult:
    """개요 슬롯을 닫는다. P2가 실제 실행을 여기 붙인다."""

    return OverviewRunResult(claimed=False, status="idle", reason_code="overview_runner_absent")


__all__ = ["OverviewRunResult", "run_once"]
