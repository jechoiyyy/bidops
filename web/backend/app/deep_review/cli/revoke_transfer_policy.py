"""``revoke-transfer-policy``: revoke one transfer policy approval (once).

``python -m app.deep_review.cli revoke-transfer-policy --approval-id <uuid>
--actor <name> --reason <text>`` prints ``{approval_id, policy_sha256,
revoked_by, revoked_at, errors}``.  Only the ``revoked_*`` triple is written
(the row stays; RL-03 spec "정책 단위 사전 승인").  After revocation the
automatic path and the worker fail closed with ``policy_not_approved`` before
any call.

Exit 2 codes: not_found | already_revoked | invalid_request (empty or >500
reason, malformed id) | actor_name_required | actor_name_invalid.  Storage
failure is ``storage_failed`` (exit 1).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from ...core.db import SessionLocal, init_db
from ..services.transfer_policy import TransferPolicyError, revoke_transfer_policy


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli revoke-transfer-policy")
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = {"approval_id": args.approval_id, "policy_sha256": None, "revoked_by": None, "revoked_at": None}
    try:
        try:
            approval_id = UUID(args.approval_id)
        except ValueError:
            raise TransferPolicyError("invalid_request") from None
        init_db()
        with SessionLocal() as session:
            transaction = session.begin()
            try:
                result = revoke_transfer_policy(
                    session, approval_id=approval_id, actor=args.actor, reason=args.reason,
                )
                transaction.commit()
            except BaseException:
                transaction.rollback()
                raise
        _emit(result)
        return 0
    except TransferPolicyError as error:
        _emit({**base, "errors": [error.code]}, error_code=error.code)
        return 2
    except Exception:  # keep SQL, paths and settings detail outside the CLI
        _emit({**base, "errors": ["storage_failed"]}, error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
