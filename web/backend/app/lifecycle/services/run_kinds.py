"""회차별 관측 존재 여부를 두 번의 일괄 조회로 분류한다."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NoticeObservation, OrderPlanObservation
from ..schemas import RunKind


def kinds_for_runs(session: Session, run_ids: Sequence[str]) -> dict[str, RunKind]:
    ids = tuple(dict.fromkeys(run_ids))
    if not ids:
        return {}

    order_plan_runs = set(session.scalars(
        select(OrderPlanObservation.run_id)
        .where(OrderPlanObservation.run_id.in_(ids))
        .group_by(OrderPlanObservation.run_id)
    ))
    notice_runs = set(session.scalars(
        select(NoticeObservation.run_id)
        .where(NoticeObservation.run_id.in_(ids))
        .group_by(NoticeObservation.run_id)
    ))
    kinds: dict[str, RunKind] = {}
    for run_id in ids:
        if run_id in order_plan_runs and run_id in notice_runs:
            kinds[run_id] = "mixed"
        elif run_id in order_plan_runs:
            kinds[run_id] = "order_plans"
        elif run_id in notice_runs:
            kinds[run_id] = "notices"
        else:
            kinds[run_id] = "unknown"
    return kinds
