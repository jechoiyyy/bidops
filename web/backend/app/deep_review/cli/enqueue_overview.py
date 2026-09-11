"""공고 한 건의 개요 run을 손으로 대기열에 넣는 운영 명령.

자동 enqueue 플래그(`BIDOPS_PRESPEC_OVERVIEW_ENABLED`)를 켜지 않고 한 건만
돌려 보고 싶을 때 쓴다. 실행은 여전히 analysis worker의 개요 슬롯이 하며 이
명령은 모델을 부르지 않는다.
"""

from __future__ import annotations

import argparse
import json
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli enqueue-overview",
        description="사전규격 공고 한 건의 개요 run을 대기열에 넣는다",
    )
    parser.add_argument("--notice-id", type=int, required=True)
    parser.add_argument("--page-start", type=int, help="사람이 확정한 첫 물리 PDF 쪽")
    parser.add_argument("--page-end", type=int, help="사람이 확정한 마지막 물리 PDF 쪽")
    parser.add_argument("--actor-name", help="사람 범위 확정 시 담당자 (감사 표식)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from ...core.config import get_settings
        from ...core.db import SessionLocal, init_db
        from ..services.overview_runs import OverviewEnqueueError, enqueue_overview_run

        if (args.page_start is None) != (args.page_end is None):
            raise OverviewEnqueueError("range_invalid")
        settings = get_settings()
        init_db()
        with SessionLocal() as session:
            # 플래그를 켜지 않아도 운영자가 한 건은 넣을 수 있어야 한다.
            # 사람 범위가 없으면 자동 선택으로 넣되 플래그 검사만 건너뛴다.
            run = enqueue_overview_run(
                session,
                args.notice_id,
                range_source="human" if args.page_start is not None else "auto",
                page_start=args.page_start,
                page_end=args.page_end,
                actor_name=args.actor_name,
                settings=_forced(settings),
            )
            session.commit()
            result = (
                {"status": "queued", "run_id": str(run.id), "notice_id": args.notice_id,
                 "range_source": run.range_source}
                if run is not None
                else {"status": "skipped", "run_id": None, "notice_id": args.notice_id,
                      "reason": "not_eligible_or_active_run"}
            )
    except OverviewEnqueueError as error:
        print(json.dumps({"error": error.code}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"error": "enqueue_overview_failed"}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


class _ForcedSettings:
    """`prespec_overview_enabled`만 켠 것으로 보이는 읽기 전용 wrapper.

    설정 자체는 바꾸지 않는다. 이 명령 한 번의 enqueue에만 적용된다.
    """

    def __init__(self, settings) -> None:
        self._settings = settings

    prespec_overview_enabled = True

    def __getattr__(self, name: str):
        return getattr(self._settings, name)


def _forced(settings):
    return _ForcedSettings(settings)


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("이 명령은 `python -m app.deep_review.cli enqueue-overview <인자>`로 실행한다")
