"""lifecycle 운영 명령 (`python -m app.lifecycle.cli <하위 명령>`).

`build-briefing`은 평일 브리핑을 하루 1회 만든다(RL-01 spec "CLI·호스트 스크립트").
`--date`는 브리핑 날짜 D(기본값 오늘 KST)이고 수집 회차는 D-1이다. 같은 날 재실행은
기존 행을 그대로 두며(`created=false`), 재생성·삭제 옵션은 없다.

브리핑 규칙은 회사 사실(deep_review)과 발주계획 후보(screening)를 **확장점으로만**
받는다. 그래서 이 진입점도 적재 CLI(`app.lifecycle.ingest.cli`)와 같은
`register_configured_extensions()`로 `BIDOPS_MODULES`가 고른 모듈의 제공자를 등록한다 —
`create_app`과 같은 선택이라 CLI와 web이 같은 제공자를 본다. 등록이 없으면 회사 사실이
없어 `company_not_registered`(exit 1)로 끝난다(조용히 0건 브리핑을 만들지 않는다).

종료 코드: 0 성공(주말·이미 있는 날 포함), 1 생성 실패(`company_not_registered` 등),
2 인자 오류. stdout은 JSON 한 개다(`--json`이면 한 줄). 진단은 stderr로 낸다.

`--send`는 `core/slack.py` 전송기가 호출 전에 `BIDOPS_SLACK_ENABLED`·토큰·채널·허용 host를
검사한 뒤에만 보낸다. 전송 실패는 `warnings[]`의 `slack_send_failed`이고 종료 코드는 0이다
(브리핑은 그대로이며 `--send` 재실행이 남은 메시지만 다시 보낸다). `slack.skipped_reason`:

- `weekend` 토·일(행 없음) · `dry_run` `--dry-run` · `not_requested` `--send` 없음
- `slack_disabled` · `token_missing` · `channel_missing` · `host_not_allowed` 전송기 검사
- `empty` 보낼 메시지 없음(`status=empty`, 추천·추적 변화 0건, 또는 생성 실패로 행 없음)
- `already_sent` `slack_sent_at`이 이미 있음
- `null` 전송을 시도함(`sent=true`, 또는 실패해 `slack_send_failed`)

`slack-worker`는 Socket Mode worker(`app.lifecycle.slack_worker`)를 띄운다.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from ..core.db import SessionFactory, init_db
from ..core.slack import (
    SKIP_CHANNEL_MISSING,
    SKIP_HOST_NOT_ALLOWED,
    SKIP_SLACK_DISABLED,
    SKIP_TOKEN_MISSING,
    SlackSender,
)
from .ingest.cli import register_configured_extensions

#: `slack.skipped_reason` 값 전체(위 docstring 표와 같다).
SKIPPED_WEEKEND = "weekend"
SKIPPED_DRY_RUN = "dry_run"
SKIPPED_NOT_REQUESTED = "not_requested"
SKIPPED_SLACK_DISABLED = SKIP_SLACK_DISABLED
SKIPPED_TOKEN_MISSING = SKIP_TOKEN_MISSING
SKIPPED_CHANNEL_MISSING = SKIP_CHANNEL_MISSING
SKIPPED_HOST_NOT_ALLOWED = SKIP_HOST_NOT_ALLOWED
SKIPPED_EMPTY = "empty"
SKIPPED_ALREADY_SENT = "already_sent"
SKIPPED_REASONS = (
    SKIPPED_WEEKEND,
    SKIPPED_DRY_RUN,
    SKIPPED_NOT_REQUESTED,
    SKIPPED_SLACK_DISABLED,
    SKIPPED_TOKEN_MISSING,
    SKIPPED_CHANNEL_MISSING,
    SKIPPED_HOST_NOT_ALLOWED,
    SKIPPED_EMPTY,
    SKIPPED_ALREADY_SENT,
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("YYYY-MM-DD 형식의 날짜가 필요합니다") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.lifecycle.cli",
        description="BidOps lifecycle 운영 명령",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build-briefing",
        help="평일 브리핑을 하루 1회 만든다(같은 날 재실행은 기존 행 유지)",
        description="평일 브리핑을 하루 1회 만든다. --date는 브리핑 날짜 D이며 수집 회차는 D-1이다.",
    )
    build.add_argument("--date", type=_iso_date, help="브리핑 날짜 YYYY-MM-DD (기본값 오늘 KST)")
    build.add_argument("--send", action="store_true", help="Slack 전송을 요청한다")
    build.add_argument("--dry-run", action="store_true", help="계산만 하고 행을 쓰지 않는다")
    build.add_argument("--json", action="store_true", help="JSON을 한 줄로 출력한다")
    commands.add_parser(
        "slack-worker",
        help="Slack Socket Mode worker(버튼 반응 수신)를 띄운다",
        description=(
            "Slack Socket Mode worker. BIDOPS_SLACK_ENABLED가 꺼져 있으면 아무것도 연결하지 않고 0으로 "
            "끝나며, 켜 놓고 토큰·채널·허용 host가 어긋나면 연결 전에 1로 끝난다."
        ),
    )
    return parser


def _slack(
    skipped_reason: str | None, *, sent: bool = False, message_ts: tuple[str, ...] | list[str] = ()
) -> dict[str, Any]:
    return {"sent": sent, "message_ts": list(message_ts), "skipped_reason": skipped_reason}


def _default_sender() -> SlackSender:
    from ..core.config import get_settings

    return SlackSender.from_settings(get_settings())


def _output(
    *,
    briefing_date: date,
    status: str | None,
    created: bool,
    item_count: int,
    tracked_change_count: int,
    excluded: dict[str, int],
    warnings: list[str],
    slack: dict[str, Any],
) -> dict[str, Any]:
    """spec의 출력 키 그대로(더하거나 빼지 않는다)."""

    return {
        "briefing_date": briefing_date.isoformat(),
        "status": status,
        "created": created,
        "item_count": item_count,
        "tracked_change_count": tracked_change_count,
        "excluded": excluded,
        "warnings": warnings,
        "slack": slack,
    }


def _print(value: dict[str, Any], *, compact: bool) -> None:
    if compact:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def build_briefing_command(
    args: argparse.Namespace,
    *,
    now: datetime | None = None,
    session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    sender: SlackSender | None = None,
) -> int:
    """`build-briefing`. `session_factory`를 넘기면 호출자가 DB·확장점 등록을 소유한다
    (격리 검사용). 넘기지 않으면 운영 경로대로 `BIDOPS_MODULES` 제공자를 등록하고 `init_db`
    뒤 기본 session을 쓴다."""

    from .services.briefing import BriefingError, build_briefing, is_weekday, today_kst
    from .services.briefing_slack import send_briefing

    current = now or datetime.now(UTC)
    briefing_date = args.date or today_kst(current)
    if not is_weekday(briefing_date):
        # 주말: 행을 만들지 않고 DB에도 닿지 않는다.
        _print(
            _output(
                briefing_date=briefing_date,
                status=None,
                created=False,
                item_count=0,
                tracked_change_count=0,
                excluded={},
                warnings=[],
                slack=_slack(SKIPPED_WEEKEND),
            ),
            compact=args.json,
        )
        return 0
    if session_factory is None:
        # 등록은 DB 접속 전에 한다. 등록이 모듈 `models`를 들이므로 격리 SQLite 경계에서
        # `init_db`가 만드는 table 집합도 web 프로세스와 같아진다.
        registered = register_configured_extensions()
        print(f"extensions: {', '.join(registered) or '(없음)'}", file=sys.stderr)
        init_db()
        session_factory = SessionFactory
    active_sender: SlackSender | None = None
    if args.send and not args.dry_run:
        active_sender = sender or _default_sender()
    with session_factory() as session:
        try:
            result = build_briefing(
                session, briefing_date, now=current, persist=not args.dry_run
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except BriefingError as error:
            session.rollback()
            print(f"build-briefing failed: {error.code}", file=sys.stderr)
            if active_sender is not None:
                # 행이 없으니 보낼 것이 없다. 전송기 검사가 먼저 걸리면 그 사유를 쓴다.
                failed_reason = active_sender.preflight() or SKIPPED_EMPTY
            else:
                failed_reason = SKIPPED_DRY_RUN if args.dry_run else SKIPPED_NOT_REQUESTED
            _print(
                _output(
                    briefing_date=briefing_date,
                    status=None,
                    created=False,
                    item_count=0,
                    tracked_change_count=0,
                    excluded={},
                    warnings=[error.code],
                    slack=_slack(failed_reason),
                ),
                compact=args.json,
            )
            return 1
        except Exception:
            session.rollback()
            raise
        warnings = list(result.warnings)
        if args.dry_run:
            slack = _slack(SKIPPED_DRY_RUN)
        elif active_sender is None:
            slack = _slack(SKIPPED_NOT_REQUESTED)
        else:
            try:
                outcome = send_briefing(session, result.briefing_date, active_sender, now=current)
                # 실패해도 그때까지 보낸 ts는 남긴다(재실행이 같은 메시지를 다시 보내지 않게).
                session.commit()
            except Exception:
                session.rollback()
                raise
            if outcome.warning is not None:
                print(f"build-briefing slack: {outcome.warning} ({outcome.error_code})", file=sys.stderr)
                if outcome.warning not in warnings:
                    warnings.append(outcome.warning)
            slack = _slack(outcome.skipped_reason, sent=outcome.sent, message_ts=outcome.message_ts)
    _print(
        _output(
            briefing_date=result.briefing_date,
            status=result.status,
            created=result.created,
            item_count=result.item_count,
            tracked_change_count=result.tracked_change_count,
            excluded=dict(result.excluded),
            warnings=warnings,
            slack=slack,
        ),
        compact=args.json,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build-briefing":
        return build_briefing_command(args)
    if args.command == "slack-worker":
        from .slack_worker import run_slack_worker

        return run_slack_worker()
    raise AssertionError(f"unknown command {args.command}")  # pragma: no cover - argparse가 막는다


if __name__ == "__main__":
    raise SystemExit(main())
