"""Lease-fenced analysis worker process with one bounded polling slot."""

from __future__ import annotations

import logging
import signal
import threading
import time
import argparse
from datetime import UTC, datetime

from ..core import (
    GpuRestGate,
    ModelIdentityCheckState,
    ObjectStoreError,
    SessionLocal,
    assert_object_store_runtime,
    configure,
    get_settings,
)
from ..deep_review import (
    PreSpecCompanyFitRunner,
    run_deep_review_once,
    run_assumption_analysis_once,
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
    company_fit_runner = PreSpecCompanyFitRunner(settings=settings)
    # 개요 슬롯의 모델 신원 재확인 상태. 모델이 닿지 않는 동안 poll마다 claim을
    # 되풀이하면 같은 run이 상한까지 순식간에 타 버린다.
    overview_identity = ModelIdentityCheckState()
    stopping = False
    stop_event = threading.Event()
    gate = GpuRestGate(settings.gpu_busy_limit_seconds, settings.gpu_rest_seconds)

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        started = time.monotonic()
        did_work = False
        try:
            with SessionLocal() as session:
                try:
                    # The manual C-2 queue has the same process-level one-slot
                    # guarantee as deep review.  A C-2 claim wins this poll;
                    # the legacy deep-review job is considered only when no
                    # C-2 execution is queued.
                    c2_result = c2_worker.run_once(session)
                    if c2_result is not None:
                        did_work = True
                    elif run_deep_review_once(session, worker_id).claimed:
                        did_work = True
                    elif run_assumption_analysis_once(session, worker_id):
                        did_work = True
                    elif company_fit_runner.run_once(session, worker_id):
                        did_work = True
                    else:
                        # 모델 신원 확인이 막혀 있으면 다음 개요 claim을
                        # 10→30→60→120→300초 뒤로 민다. 설정을 고쳐야 낫는
                        # 실패는 이 runner에서 다시 확인하지 않는다.
                        now = datetime.now(UTC)
                        if overview_identity.should_check(now):
                            overview = run_prespec_overview_once(session, worker_id)
                            if overview.identity_error is not None:
                                overview_identity.record_failure(overview.identity_error, now)
                            elif overview.claimed:
                                overview_identity.record_success()
                                did_work = True
                except Exception:
                    # run_claim commits its own fenced transitions. Any
                    # provider/materializer error not converted there must not
                    # leave a transaction open for the next poll.
                    did_work = True
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
        finished = time.monotonic()
        rest = gate.after_poll(did_work=did_work, work_seconds=finished - started, now=finished)
        if args.once or stopping:
            return
        if rest is not None:
            logger.info(
                "analysis worker resting",
                extra={"bidops": {"event": "worker.gpu_rest", "worker_id": worker_id, "rest_seconds": rest}},
            )
            stop_event.wait(rest)
        else:
            stop_event.wait(max(settings.analysis_worker_poll_seconds, 0.1))


if __name__ == "__main__":
    main()
