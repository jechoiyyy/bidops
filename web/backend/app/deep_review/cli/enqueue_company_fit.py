"""``enqueue-company-fit``: queue one DEMO company-fit attempt (contract §9).

``python -m app.deep_review.cli enqueue-company-fit --company-id <uuid>
--notice-id <int> --actor <name> [--dry-run]`` prints one JSON object
``{company_id, notice_id, attempt_id, input_sha256, created, errors}``.

Run it with the analysis-worker image and the **worker** database role: the
company-fit attempt INSERT is a worker-only grant and is not opened to the app
role.  A real run freezes CompanyAnalysisInput(purpose=company_fit) and
FrozenProvenance and inserts exactly one ``queued`` attempt in one
transaction.  ``--dry-run`` runs the same gates and input build, writes
nothing, and reports ``attempt_id``/``input_sha256`` as null.  No model is
called here; the composed worker slot executes the attempt later.

Gate codes: company_not_found | company_profile_not_ready |
company_input_invalid | analysis_policy_unavailable | model_binding_invalid |
overview_not_completed | effective_grade_ineligible | company_fit_disabled |
active_attempt_exists (exit 2).  ``BIDOPS_DEMO_ENABLED``,
``BIDOPS_PRESPEC_COMPANY_FIT_ENABLED`` or ``BIDOPS_REFERENCE_WORKFLOW_MODE``
false all report ``company_fit_disabled``.  An unparseable company id is
``company_not_found``; a missing or non-SW사업대상=Y notice is
``effective_grade_ineligible``; an invalid actor name is
``company_input_invalid``.  Storage/dependency failure is ``storage_failed``
(exit 1).  stderr carries only the safe code; argparse syntax errors exit 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from ...core.db import SessionLocal, init_db
from ..services.company_fit import CompanyFitGateError, enqueue_company_fit


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "company_id": None, "notice_id": None, "attempt_id": None,
        "input_sha256": None, "created": False, "errors": [],
    }
    value.update(overrides)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli enqueue-company-fit")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--notice-id", type=int, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    company_id = _uuid_or_none(args.company_id)
    known = {"company_id": str(company_id) if company_id is not None else None, "notice_id": args.notice_id}
    try:
        from ..services.company_fit import company_fit_enabled
        from ...core.config import get_settings

        if not company_fit_enabled(get_settings()):
            raise CompanyFitGateError("company_fit_disabled")
        if company_id is None:
            raise CompanyFitGateError("company_not_found")
        init_db()
        with SessionLocal() as session:
            transaction = session.begin()
            try:
                result = enqueue_company_fit(
                    session, company_id=company_id, notice_id=args.notice_id,
                    actor=args.actor, dry_run=args.dry_run,
                )
                if args.dry_run:
                    transaction.rollback()
                else:
                    transaction.commit()
            except BaseException:
                transaction.rollback()
                raise
        _emit(_payload(
            **known,
            attempt_id=str(result.attempt_id) if result.attempt_id is not None else None,
            input_sha256=result.input_sha256,
            created=result.created,
        ))
        return 0
    except CompanyFitGateError as error:
        _emit(_payload(**known, errors=[error.code]), error_code=error.code)
        return 2
    except Exception:  # keep internal paths, SQL, and model details outside the CLI
        _emit(_payload(**known, errors=["storage_failed"]), error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
