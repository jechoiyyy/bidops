"""활성 개요 run 하나를 사람이 닫는 운영 명령.

모델이 오래 막혀 있거나 잘못 넣은 run이 대기열 앞을 잡고 있을 때 쓴다. 이
명령은 모델도 객체 저장소도 부르지 않고 run·job의 상태 전이와 감사 행만
남긴다. 이미 종결된 run은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
from typing import Sequence
from uuid import UUID


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli close-overview-run",
        description="활성 사전규격 개요 run 하나를 닫는다",
    )
    parser.add_argument("--run-id", type=UUID, required=True, help="닫을 개요 run id")
    parser.add_argument(
        "--reason",
        default="operator_close",
        choices=("operator_close",),
        help="종결 사유 코드 (현재는 operator_close 하나뿐이다)",
    )
    parser.add_argument("--actor-name", required=True, help="담당자 이름 (감사 표식)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from ...core.db import SessionLocal, init_db
        from ..services.overview_runs import OverviewRequestError, close_run

        init_db()
        with SessionLocal() as session:
            try:
                result = close_run(
                    session, args.run_id, actor_name=args.actor_name, reason=args.reason
                )
            except OverviewRequestError as error:
                session.rollback()
                print(json.dumps({"error": error.code}, ensure_ascii=False, sort_keys=True))
                return 2
            session.commit()
    except Exception:
        # 코드만 남긴다. 예외 본문에는 DSN·경로가 섞일 수 있다.
        print(json.dumps({"error": "close_overview_run_failed"}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("이 명령은 `python -m app.deep_review.cli close-overview-run <인자>`로 실행한다")
