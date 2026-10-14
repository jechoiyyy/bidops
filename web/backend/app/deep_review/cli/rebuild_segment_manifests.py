"""과거 ready 구조에 현재 identity의 segment manifest를 멱등 생성한다.

analysis-worker 이미지에서 worker DB 역할로 실행한다. 구조·원본 객체는 고정
version과 hash를 다시 확인하고, manifest는 구조별 savepoint 안에서 append-only로
생성한다. 내부 예외 본문과 object key는 JSONL이나 stderr에 내보내지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.db import SessionLocal, init_db
from ...core.object_store import ObjectStore, object_store
from ..models import DocumentStructure
from ..services.document_bundles import load_structure_payload
from ..services.document_segments import _manifest_for_structure, store_manifest


def _emit(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _result(
    structure_id: UUID | str | None,
    *,
    created: bool = False,
    manifest_id: UUID | str | None = None,
    errors: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "structure_id": str(structure_id) if structure_id is not None else None,
        "created": created,
        "manifest_id": str(manifest_id) if manifest_id is not None else None,
        "errors": list(errors),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli rebuild-segment-manifests",
        description="ready 문서 구조의 현재 segment manifest를 멱등 생성한다",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--structure-id", type=UUID)
    target.add_argument("--all", action="store_true", dest="all_structures")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def rebuild(
    session: Session,
    store: ObjectStore,
    *,
    structure_id: UUID | None = None,
    all_structures: bool = False,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """대상을 처리하고 ``(JSONL rows, exit code)``를 돌려준다.

    exit 2는 단건 식별자가 없을 때만 쓴다. 구조별 payload 검증·저장 실패는
    다른 구조의 성공을 보존하고 최종 exit 1로 모은다.
    """

    if (structure_id is None) == (not all_structures):
        raise ValueError("exactly one target mode is required")

    if structure_id is not None:
        structure = session.get(DocumentStructure, structure_id)
        if structure is None:
            return [_result(structure_id, errors=("not_found",))], 2
        structures = [structure]
    else:
        structures = list(
            session.scalars(
                select(DocumentStructure)
                .where(DocumentStructure.validation_status == "ready")
                .order_by(DocumentStructure.created_at.asc(), DocumentStructure.id.asc())
            ).all()
        )

    rows: list[dict[str, Any]] = []
    processing_error = False
    for structure in structures:
        current = _manifest_for_structure(session, structure.id)
        if current is not None:
            rows.append(_result(structure.id, manifest_id=current.id))
            continue

        payload = load_structure_payload(
            session,
            structure,
            store,
            allow_unsafe=False,
        )
        if payload is None:
            rows.append(_result(structure.id, errors=("structure_unavailable",)))
            processing_error = True
            continue
        if dry_run:
            rows.append(_result(structure.id))
            continue

        try:
            # Do not use ensure_manifest here: the maintenance command must
            # report a safe error code while preserving sibling savepoints.
            with session.begin_nested():
                manifest = store_manifest(session, payload)
        except Exception:  # noqa: BLE001 - safe CLI processing boundary
            rows.append(_result(structure.id, errors=("processing_failed",)))
            processing_error = True
            continue
        rows.append(_result(structure.id, created=True, manifest_id=manifest.id))

    return rows, 1 if processing_error else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    known_structure_id = args.structure_id
    try:
        init_db()
        store = object_store(
            namespaces=("source", "structure"),
            read_namespaces=("source", "structure"),
        )
        with SessionLocal() as session:
            rows, exit_code = rebuild(
                session,
                store,
                structure_id=args.structure_id,
                all_structures=args.all_structures,
                dry_run=args.dry_run,
            )
            if args.dry_run or exit_code == 2:
                session.rollback()
            else:
                # A processing failure is per-structure. Successful sibling
                # savepoints remain part of this append-only backfill.
                session.commit()
        for row in rows:
            _emit(row)
        return exit_code
    except Exception:  # keep paths, SQL, object keys, and exception text private
        row = _result(known_structure_id, errors=("processing_failed",))
        _emit(row)
        print("processing_failed", file=sys.stderr)
        return 1


__all__ = ["build_parser", "main", "rebuild"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        "이 명령은 `python -m app.deep_review.cli rebuild-segment-manifests <인자>`로 실행한다"
    )
