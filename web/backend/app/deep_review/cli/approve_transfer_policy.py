"""``approve-transfer-policy``: approve Luna transfer for the selected RL policy row.

``python -m app.deep_review.cli approve-transfer-policy --policy <identity>
--actor <name> --daily-cap N [--request-id <uuid>] [--dry-run]`` prints one
JSON object ``{approval_id, policy_identity, policy_sha256, model_name,
reasoning_effort, cli_version, daily_cap, request_id, created, errors}``
(RL-03 spec "정책 단위 사전 승인").

The policy row is the one selected by ``BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID``;
``policy_sha256`` is that row's canonical sha.  The requested identity, the row
identity, the immutable policy file (``BIDOPS_RL_ANALYSIS_POLICY_PATH``) and the
HP-00 runner identity must all agree.  ``request_id`` is a new ``uuid4()``
unless ``--request-id`` replays an earlier call (``created=false``).

Exit 2 codes: policy_identity_mismatch | analysis_policy_unavailable |
active_approval_exists | invalid_request (daily cap outside 1..50) |
actor_name_required | actor_name_invalid.  Storage failure is
``storage_failed`` (exit 1).  stderr carries only the safe code.  No model or
network is called; this is a human operation that needs a prior confirmation.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from ...core.db import SessionLocal, init_db
from ..services.transfer_policy import DAILY_CAP_DEFAULT, TransferPolicyError, approve_transfer_policy


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "approval_id": None, "policy_identity": None, "policy_sha256": None, "model_name": None,
        "reasoning_effort": None, "cli_version": None, "daily_cap": None, "request_id": None,
        "created": False, "errors": [],
    }
    value.update(overrides)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli approve-transfer-policy")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--daily-cap", type=int, default=DAILY_CAP_DEFAULT)
    parser.add_argument("--request-id", type=UUID, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    known = {"policy_identity": args.policy, "daily_cap": args.daily_cap}
    try:
        init_db()
        with SessionLocal() as session:
            transaction = session.begin()
            try:
                result = approve_transfer_policy(
                    session, policy_identity=args.policy, actor=args.actor, daily_cap=args.daily_cap,
                    request_id=args.request_id, dry_run=args.dry_run,
                )
                if args.dry_run:
                    transaction.rollback()
                else:
                    transaction.commit()
            except BaseException:
                transaction.rollback()
                raise
        _emit(result)
        return 0
    except TransferPolicyError as error:
        _emit(_payload(**known, errors=[error.code]), error_code=error.code)
        return 2
    except Exception:  # keep SQL, paths and settings detail outside the CLI
        _emit(_payload(**known, errors=["storage_failed"]), error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
