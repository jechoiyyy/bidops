"""``attach-local-original``: connect an operator-held original to an existing G2B attachment row.

``python -m app.deep_review.cli attach-local-original --notice-id N --attachment-id A
--file <path> --expected-sha256 <hex> --actor <name> [--dry-run]`` prints one JSON
object ``{notice_id, attachment_id, content_sha256, size_bytes, provenance,
fetch_status_before, document_version_id, scan_status, preparation, dry_run,
errors}`` (RL-03 결정 B15, spec "인터페이스").

The file must be a regular file (not a symlink) within the attachment size cap and
its sha256 must equal ``--expected-sha256``.  The attachment row must belong to the
notice (a pre-spec), be a current G2B row and have no bytes yet (no document
version, fetch row not ``완료``/``진행``).  Bytes go through the same quarantine →
ClamAV/MIME inspection → source → document → structure path as the G2B fetcher;
then document preparation opens with trigger ``operator_local_original`` (only the
grade/briefing eligibility is bypassed).  One audit
``prespec_attachment.local_original`` records the provenance.  No G2B, model or
network call except the configured ClamAV/converter of the document path.
``--dry-run`` reads the file and checks everything without writing.

Exit 2: refusal codes (``sha256_mismatch``, ``attachment_has_bytes``,
``attachment_notice_mismatch``, ``attachment_source_not_g2b``, ``file_not_regular``,
``malware_detected``, ``mime_mismatch``, …).  Exit 1: a retryable or storage
failure (``clamav_unavailable``, ``service_unavailable``, ``storage_failed``).
stderr carries only the safe code; the local path is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ...core.config import get_settings
from ...core.db import SessionLocal, init_db
from ..services.prespec_attachments import (
    LOCAL_ORIGINAL_PROVENANCE,
    LocalOriginalError,
    attach_local_original,
    read_operator_file,
)


def _emit(payload: dict[str, Any], *, error_code: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if error_code is not None:
        print(error_code, file=sys.stderr)


def _payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "notice_id": None, "attachment_id": None, "content_sha256": None, "size_bytes": None,
        "provenance": LOCAL_ORIGINAL_PROVENANCE, "fetch_status_before": None, "document_version_id": None,
        "scan_status": None, "preparation": None, "dry_run": False, "errors": [],
    }
    value.update(overrides)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deep_review.cli attach-local-original")
    parser.add_argument("--notice-id", type=int, required=True)
    parser.add_argument("--attachment-id", type=int, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _document_processing(settings: Any) -> tuple[Any, Any]:
    """The worker's scanner and scratch converter (same objects as the G2B fetcher)."""

    from ...core.clamav import ClamAVScanner
    from ...core.object_store import assert_object_store_runtime
    from ..services.document_converter import ScratchDocumentProcessor

    # Fail closed before any write: bytes that cannot be preserved are not quarantined.
    assert_object_store_runtime(require_model_response=False)
    scanner = ClamAVScanner(
        host=settings.clamav_host, port=settings.clamav_port, timeout=settings.clamav_timeout_seconds,
    )
    return ScratchDocumentProcessor(clamav_checker=scanner.scan), scanner.scan


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    known = {"notice_id": args.notice_id, "attachment_id": args.attachment_id, "dry_run": bool(args.dry_run)}
    try:
        content = read_operator_file(args.file)
        init_db()
        processor = clamav_checker = None
        if not args.dry_run:
            processor, clamav_checker = _document_processing(get_settings())
        with SessionLocal() as session:
            result = attach_local_original(
                session, notice_id=args.notice_id, attachment_id=args.attachment_id, content=content,
                expected_sha256=args.expected_sha256, actor=args.actor, fallback_filename=args.file.name,
                processor=processor, clamav_checker=clamav_checker, dry_run=args.dry_run,
            )
            if args.dry_run and session.in_transaction():
                session.rollback()
        _emit(result)
        return 0
    except LocalOriginalError as error:
        _emit(_payload(**known, errors=[error.code]), error_code=error.code)
        return 1 if error.retryable else 2
    except Exception:  # keep SQL, paths and settings detail outside the CLI
        _emit(_payload(**known, errors=["storage_failed"]), error_code="storage_failed")
        return 1


__all__ = ["build_parser", "main"]
