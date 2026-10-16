"""JSON-only CLI boundary for immutable company knowledge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from ...core.api_errors import BundleServiceError
from ...core.db import SessionLocal, init_db
from ..services.company_knowledge import (
    CompanyKnowledgeServiceError,
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge_files,
    status_counts,
)


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _import_payload(**overrides: Any) -> dict[str, Any]:
    # RL-00: ``is_fictional`` and ``status_counts`` are always present and are
    # null in every failure JSON (the activate output keeps its six keys).
    value: dict[str, Any] = {
        "company_id": None,
        "profile_version_id": None,
        "graph_version_id": None,
        "ontology_version": None,
        "source_sha256": None,
        "graph_sha256": None,
        "created": False,
        "activated": False,
        "errors": [],
        "is_fictional": None,
        "status_counts": None,
    }
    value.update(overrides)
    return value


def _activation_payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "company_id": None,
        "graph_version_id": None,
        "profile_version_id": None,
        "revision": None,
        "changed": False,
        "errors": [],
    }
    value.update(overrides)
    return value


def _exit_for(code: str) -> int:
    return 2 if code in {
        "source_invalid",
        "ontology_invalid",
        "ontology_version_conflict",
        "company_identity_conflict",
        "real_company_exists",
        "fictional_requires_demo",
        "company_not_found",
        "graph_not_found",
        "graph_company_mismatch",
        "profile_invalid",
    } else 1


def build_import_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli import-company-knowledge"
    )
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--company", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def import_main(argv: list[str] | None = None) -> int:
    args = build_import_parser().parse_args(argv)
    try:
        prepared = prepare_company_knowledge_files(args.ontology, args.company)
    except CompanyKnowledgeServiceError as error:
        payload = _import_payload(errors=[error.code])
        _emit(payload, error_code=error.code)
        return _exit_for(error.code)

    known = {
        "ontology_version": prepared.ontology.version,
        "source_sha256": prepared.source.source_sha256,
        "graph_sha256": prepared.graph.sha256,
    }
    summary = {
        "is_fictional": prepared.source.company.is_fictional,
        "status_counts": status_counts(prepared.source),
    }
    if args.dry_run:
        _emit(_import_payload(**known, **summary))
        return 0
    try:
        init_db()
        with SessionLocal() as session:
            with session.begin():
                result = import_company_knowledge(session, prepared, actor=args.actor)
        _emit(
            _import_payload(
                company_id=str(result.company_id),
                profile_version_id=str(result.profile_version_id),
                graph_version_id=str(result.graph_version_id),
                ontology_version=result.ontology_version,
                source_sha256=result.source_sha256,
                graph_sha256=result.graph_sha256,
                created=result.created,
                **summary,
            )
        )
        return 0
    except CompanyKnowledgeServiceError as error:
        code = error.code
    except BundleServiceError:
        code = "source_invalid"
    except Exception:  # keep internal paths, SQL, and object details outside the CLI
        code = "storage_failed"
    _emit(_import_payload(**known, errors=[code]), error_code=code)
    return _exit_for(code)


def build_activate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli activate-company-knowledge"
    )
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--graph-version-id", required=True)
    parser.add_argument("--actor", required=True)
    return parser


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def activate_main(argv: list[str] | None = None) -> int:
    args = build_activate_parser().parse_args(argv)
    company_id = _uuid_or_none(args.company_id)
    graph_version_id = _uuid_or_none(args.graph_version_id)
    if company_id is None or graph_version_id is None:
        code = "company_not_found" if company_id is None else "graph_not_found"
        _emit(
            _activation_payload(
                company_id=str(company_id) if company_id is not None else None,
                graph_version_id=(
                    str(graph_version_id) if graph_version_id is not None else None
                ),
                errors=[code],
            ),
            error_code=code,
        )
        return 2
    try:
        init_db()
        with SessionLocal() as session:
            with session.begin():
                result = activate_company_knowledge(
                    session,
                    company_id=company_id,
                    graph_version_id=graph_version_id,
                    actor=args.actor,
                )
        _emit(
            _activation_payload(
                company_id=str(result.company_id),
                graph_version_id=str(result.graph_version_id),
                profile_version_id=str(result.profile_version_id),
                revision=result.revision,
                changed=result.changed,
            )
        )
        return 0
    except CompanyKnowledgeServiceError as error:
        code = error.code
    except BundleServiceError:
        code = "profile_invalid"
    except Exception:  # keep internal paths, SQL, and object details outside the CLI
        code = "storage_failed"
    _emit(
        _activation_payload(
            company_id=str(company_id),
            graph_version_id=str(graph_version_id),
            errors=[code],
        ),
        error_code=code,
    )
    return _exit_for(code)


__all__ = [
    "activate_main",
    "build_activate_parser",
    "build_import_parser",
    "import_main",
]
