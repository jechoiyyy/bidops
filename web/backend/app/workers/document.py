"""Credential-free document worker.

FastAPI is the trusted producer: it scans bytes and writes the hash-bound
scratch request. This worker only claims requests atomically and runs the
bounded converter; its Compose service has no network or environment secrets.
Two Compose replicas provide the approved document-worker concurrency of two.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from pathlib import Path

from ..config import get_settings
from ..logging_setup import configure
from .document_protocol import convert_one


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="credential-free document worker")
    parser.add_argument("--once", action="store_true", help="process one scratch request and exit")
    args = parser.parse_args()
    settings = get_settings()
    configure(settings)
    if settings.document_worker_concurrency != 2:
        raise RuntimeError("document worker concurrency must remain 2")
    scratch_root = Path(os.getenv("BIDOPS_DOCUMENT_SCRATCH_DIR", str(settings.document_scratch_dir)))
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # FastAPI is the trusted producer and owns DB/object/scanner capabilities;
    # this worker has no credentials/network and can only consume an atomic
    # request from this scoped scratch volume.
    while not stopping:
        # convert_one owns per-request logging: it is the only place that knows
        # which request this replica actually claimed.  Anything escaping it is
        # unexpected and kills the process, so it is recorded before it does.
        try:
            processed = convert_one(scratch_root)
        except Exception:
            logger.error(
                "document worker stopped on an unhandled error",
                extra={"bidops": {"event": "document.worker_crashed"}},
                exc_info=True,
            )
            raise
        if args.once:
            return
        if not processed:
            time.sleep(max(settings.document_worker_poll_seconds, 0.1))


if __name__ == "__main__":
    main()
