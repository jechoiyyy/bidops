"""``import-company-fit-policy``: store an approved DEMO company-fit policy.

Output (stdout, one JSON object, contract §9):
``{policy_version_id, sha256, created, errors}``.  The same canonical hash
returns the existing id with ``created=false``.  Import never activates the
policy; the company path selects it only via
``BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID``.

Exit codes follow contract §8: 0 success, 2 validation (``policy_invalid``,
``policy_unapproved``, ``actor_invalid``), 1 storage (``storage_failed``).
stderr carries only the safe code; argparse syntax errors exit 2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from ...core.db import SessionLocal, init_db
from ..services.company_fit_policy import CompanyFitPolicyError, import_company_fit_policy

_VALIDATION_CODES = frozenset({"policy_invalid", "policy_unapproved", "actor_invalid"})


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"policy_version_id": None, "sha256": None, "created": False, "errors": []}
    value.update(overrides)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli import-company-fit-policy")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        init_db()
        with SessionLocal() as session:
            with session.begin():
                result = import_company_fit_policy(session, args.policy, actor=args.actor)
        _emit(_payload(policy_version_id=str(result.policy_version_id), sha256=result.sha256,
                       created=result.created))
        return 0
    except CompanyFitPolicyError as error:
        code = error.code
    except Exception:  # keep internal paths, SQL, and object details outside the CLI
        code = "storage_failed"
    _emit(_payload(errors=[code]), error_code=code)
    return 2 if code in _VALIDATION_CODES else 1


__all__ = ["build_parser", "main"]
