"""Lease-fenced pre-specification attachment worker."""

from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...core.config import get_settings
from ...core.db import SessionLocal
from ...core.logging_setup import configure
from ..services import assets
from ...core.clamav import ClamAVScanner
from ...core.object_store import ObjectStoreError, assert_object_store_runtime
from ..services.prespec_attachments import (
    AttachmentFetchClaim,
    claim_next,
    fetch_claimed,
    validate_notice_id,
)
from ..services.document_converter import ScratchDocumentProcessor


logger = logging.getLogger(__name__)


def run_once(
    session: Any,
    worker_id: str,
    *,
    connectors: Mapping[str, Any] | None = None,
    lease_seconds: float = 120.0,
    processor: Any = None,
    clamav_checker: Any = None,
    root: Path | None = None,
    notice_id: int | None = None,
) -> bool:
    """Process at most one row; return whether a row was claimed."""

    notice_id = validate_notice_id(notice_id)
    if connectors is None:
        connectors = assets.g2b_attachment_connectors(get_settings())
    # Disabled is the normal default.  Do not even open a database transaction
    # in that mode: an absent connector is an intentional idle state.
    if not connectors:
        return False
    if processor is None:
        processor = ScratchDocumentProcessor(clamav_checker=clamav_checker)
    claim: AttachmentFetchClaim | None = claim_next(
        session,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        notice_id=notice_id,
    )
    if claim is None:
        return False
    fetch_claimed(
        session,
        claim,
        connectors=connectors,
        processor=processor,
        clamav_checker=clamav_checker,
        root=root,
    )
    return True


def _positive_notice_id(value: str) -> int:
    try:
        notice_id = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("notice id must be a positive integer") from error
    try:
        validated = validate_notice_id(notice_id)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    assert validated is not None
    return validated


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="pre-specification attachment worker")
    parser.add_argument("--once", action="store_true", help="claim at most one row and exit")
    parser.add_argument(
        "--notice-id",
        type=_positive_notice_id,
        help="with --once, claim only an attachment owned by this notice",
    )
    args = parser.parse_args(argv)
    if args.notice_id is not None and not args.once:
        parser.error("--notice-id requires --once")

    settings = get_settings()
    configure(settings)
    if settings.prespec_attachment_worker_concurrency != 1:
        raise RuntimeError("pre-specification attachment worker concurrency must remain 1")
    connectors = assets.g2b_attachment_connectors(settings)
    # Fail closed at startup rather than per row: a worker that can reach
    # G2B but cannot write versioned objects would quarantine bytes it
    # cannot preserve.
    if connectors:
        try:
            assert_object_store_runtime(require_model_response=False)
        except ObjectStoreError as error:
            raise RuntimeError("pre-specification attachment worker requires configured document storage") from error
    scanner = ClamAVScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout=settings.clamav_timeout_seconds,
    )
    worker_id = settings.worker_id
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        if connectors:
            try:
                with SessionLocal() as session:
                    try:
                        run_once(
                            session,
                            worker_id,
                            connectors=connectors,
                            lease_seconds=settings.prespec_attachment_lease_seconds,
                            clamav_checker=scanner.scan,
                            notice_id=args.notice_id,
                        )
                    except Exception:
                        session.rollback()
                        logger.warning(
                            "pre-specification attachment job failed",
                            extra={
                                "bidops": {
                                    "event": "prespec_attachment.job_failed",
                                    "worker_id": worker_id,
                                }
                            },
                        )
            except Exception:
                logger.warning(
                    "pre-specification attachment poll failed",
                    extra={
                        "bidops": {
                            "event": "prespec_attachment.poll_failed",
                            "worker_id": worker_id,
                        }
                    },
                )
        if args.once or stopping:
            return
        if not stopping:
            time.sleep(max(settings.prespec_attachment_worker_poll_seconds, 0.1))


if __name__ == "__main__":
    main()
