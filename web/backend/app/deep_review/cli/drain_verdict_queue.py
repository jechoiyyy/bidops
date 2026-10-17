"""``drain-verdict-queue``: start RL verdict requests queued by the daily cap, or mark gold holdouts.

``python -m app.deep_review.cli drain-verdict-queue [--date YYYY-MM-DD]`` starts,
oldest first and within today's cap, the ``verdict_request`` rows that the
automatic trigger queued (``queued``/``daily_cap_reached``) before ``--date``
(KST day, default today).  ``build-briefing`` runs the same service function
right after a new briefing is created (lifecycle hook ``on_briefing_recommendation``).
One pass only -- no catch-up loop.  Requires ``BIDOPS_RL_ANALYSIS_ENABLED`` and
``BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED``; otherwise nothing is read or written
(``stopped_reason=auto_start_disabled``).

``drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor <name>``
records the RL-05 gold holdout markers (``rejected``/``gold_holdout``) that keep
the automatic trigger away from those pre-specs; a manual request releases them.

Output: one JSON object.  Exit 0 on success, 2 for a safe input code
(``invalid_request``·``not_found``·``actor_name_*``), 1 for a storage failure.
No model or network is called here (the started attempts run in the shared
analysis slot).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from ...core.db import SessionLocal, init_db
from ..services.transfer_policy import TransferPolicyError
from ..services.verdict_trigger import VerdictRequestError, drain_verdict_queue, hold_notices


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _notice_ids(value: str) -> list[int]:
    try:
        ids = [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("notice ids must be integers") from None
    if not ids or any(item < 1 for item in ids):
        raise argparse.ArgumentTypeError("notice ids must be positive integers")
    return ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli drain-verdict-queue")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--hold", type=_notice_ids, default=None)
    parser.add_argument("--reason", choices=("gold_holdout",), default=None)
    parser.add_argument("--actor", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.hold is not None and args.reason != "gold_holdout":
        parser.error("--hold requires --reason gold_holdout")
    if args.hold is None and (args.reason is not None or args.actor is not None):
        parser.error("--reason/--actor are only valid with --hold")
    try:
        init_db()
        with SessionLocal() as session:
            try:
                if args.hold is not None:
                    result = {"mode": "hold", **hold_notices(session, args.hold, actor=args.actor), "errors": []}
                    session.commit()
                else:
                    result = {"mode": "drain", **drain_verdict_queue(session, as_of=args.date).as_dict(),
                              "errors": []}
                    session.commit()
            except BaseException:
                session.rollback()
                raise
        _emit(result)
        return 0
    except (VerdictRequestError, TransferPolicyError) as error:
        _emit({"mode": "hold" if args.hold is not None else "drain", "errors": [error.code]},
              error_code=error.code)
        return 2
    except Exception:  # keep SQL, paths and settings detail outside the CLI
        _emit({"mode": "hold" if args.hold is not None else "drain", "errors": ["storage_failed"]},
              error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
