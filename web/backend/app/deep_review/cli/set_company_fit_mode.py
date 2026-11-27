"""``set-company-fit-mode``: record the company-fit card mode (PS-01 C8, ADR-0080).

``python -m app.deep_review.cli set-company-fit-mode --mode off|suggest --actor <name>
[--reason <text>] [--request-id <uuid>]`` prints the C4 state after the call as one JSON line.
It calls the same service as ``POST /api/pre-specs/company-fit/mode``. Run it in the **web**
container (app DB role: INSERT on ``prespec_company_fit_mode``). Without ``--request-id`` every
run is a new row. Exit codes: 0 success, 2 input or prerequisite refusal (code on stderr), 1
internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID, uuid4

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import SessionLocal, init_db
from ..services.company_fit_mode import CompanyFitModeError, set_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli set-company-fit-mode")
    parser.add_argument("--mode", required=True, choices=("off", "suggest", "auto_request"))
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--request-id", type=UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        actor = validate_actor(args.actor)
        init_db()
        with SessionLocal() as session:
            state, created = set_mode(session, mode=args.mode, reason=args.reason,
                                      request_id=args.request_id or uuid4(), actor=actor)
    except (CompanyFitModeError, BundleServiceError) as error:
        detail = getattr(error, "details", None) or {}
        print(error.code + (f" {detail['reason_code']}" if "reason_code" in detail else ""), file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"internal_error {type(error).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({**state, "set_at": state["set_at"].isoformat() if state["set_at"] else None,
                      "created": created}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
