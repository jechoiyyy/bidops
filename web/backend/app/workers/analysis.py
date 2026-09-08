"""Lease-fenced analysis worker process with one bounded polling slot."""

from __future__ import annotations

import logging
import signal
import time
import argparse

from ..core import (
    ObjectStoreError,
    SessionLocal,
    assert_object_store_runtime,
    configure,
    get_settings,
)
from ..deep_review import (
    PreSpecOverviewRunner,
    PreSpecCompanyFitRunner,
    run_deep_review_once,
    run_prespec_overview_once,
)
from ..screening import C2ScreeningWorker


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
    c2_worker = C2ScreeningWorker(settings=settings)
    # 개요 runner도 C-2 worker와 같이 loop **밖에서** 한 번 만든다. poll마다
    # 새로 만들면 binding 해석 캐시가 매번 비어 있어, 큐가 비었을 때도 policy를
    # 다시 읽고 `/models`를 부르게 된다 (명세 §6.3).
    overview_runner = PreSpecOverviewRunner()
    company_fit_runner = PreSpecCompanyFitRunner(settings=settings)
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
                    # The manual C-2 queue has the same process-level one-slot
                    # guarantee as deep review.  A C-2 claim wins this poll;
                    # the legacy deep-review job is considered only when no
                    # C-2 execution is queued.
                    c2_result = c2_worker.run_once(session)
                    if c2_result is None:
                        # 한 poll은 C-2·심층 검토·회사 핏·개요 중
                        # 하나만 잡는다. 회사 핏도 같은 모델 슬롯을 쓴다.
                        if not run_deep_review_once(session, worker_id).claimed and not company_fit_runner.run_once(session, worker_id):
                            run_prespec_overview_once(
                                session, worker_id, runner=overview_runner
                            )
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
