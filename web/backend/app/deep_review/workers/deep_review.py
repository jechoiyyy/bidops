"""Worker entry points for the lease-fenced deep-review job queue."""

from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from ..services.deep_reviews import DeepReviewService


@dataclass(frozen=True)
class WorkerResult:
    claimed: bool
    job_id: str | None = None
    attempt_id: str | None = None
    status: str = "idle"


def run_once(session: Session, worker_id: str, *, service: DeepReviewService | None = None) -> WorkerResult:
    """Claim exactly one job and execute it after the claim commit."""

    worker = service or DeepReviewService()
    claim = worker.claim_next_job(session, worker_id)
    if claim is None:
        return WorkerResult(False)
    worker.run_claim(session, claim)
    return WorkerResult(True, str(claim.job_id), str(claim.attempt_id), "completed")


run_deep_review = run_once


class DeepReviewWorker:
    def __init__(self, service: DeepReviewService | None = None) -> None:
        self.service = service or DeepReviewService()

    def run_once(self, session: Session, worker_id: str) -> WorkerResult:
        return run_once(session, worker_id, service=self.service)


__all__ = ["DeepReviewWorker", "WorkerResult", "run_deep_review", "run_once"]
