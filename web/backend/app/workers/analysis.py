"""Lease-fenced analysis worker process with one bounded polling slot."""

from __future__ import annotations

import logging
import signal
import time
import argparse

from ..config import get_settings
from ..db import SessionLocal
from ..logging_setup import configure
from ..services.object_store import ObjectStoreError, assert_object_store_runtime
from .deep_review import run_once


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="lease-fenced analysis worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    args = parser.parse_args()
    settings = get_settings()
    configure(settings)
    if settings.analysis_worker_concurrency != 1:
        raise RuntimeError("analysis worker concurrency must remain 1")
    try:
        assert_object_store_runtime(require_model_response=True)
    except ObjectStoreError as error:
        raise RuntimeError("analysis worker requires configured MinIO model-response storage") from error
    worker_id = settings.worker_id
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            with SessionLocal() as session:
                try:
                    run_once(session, worker_id)
                except Exception:
                    # run_claim commits its own fenced transitions. Any
                    # provider/materializer error not converted there must not
                    # leave a transaction open for the next poll.
                    session.rollback()
                    logger.warning(
                        "analysis worker job failed",
                        extra={
                            "bidops": {
                                "event": "worker.job_failed",
                                "worker_id": worker_id,
                            }
                        },
                        exc_info=True,
                    )
        except Exception:
            # Connection/claim failures are retried on the bounded interval.
            # Exception contents may carry DSN material or provider details, so
            # only a fixed message and the worker id go out at WARNING; the
            # traceback is rendered solely when BIDOPS_LOG_TRACEBACK is on, and
            # the masking filter redacts it on the way out.
            logger.warning(
                "analysis worker poll failed",
                extra={
                    "bidops": {
                        "event": "worker.poll_failed",
                        "worker_id": worker_id,
                    }
                },
                exc_info=True,
            )
        if args.once or stopping:
            return
        if not stopping:
            time.sleep(max(settings.analysis_worker_poll_seconds, 0.1))


if __name__ == "__main__":
    main()
