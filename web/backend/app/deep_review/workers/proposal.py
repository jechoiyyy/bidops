"""Worker entry point of the RL-04 proposal section queue (``job_type="proposal_section"``).

The composed analysis worker (``app/workers/analysis.py``) calls ``run_once`` in
its single slot after the other queues found nothing, so the shared model slot
guarantee (one Luna call at a time) holds.  There is no standalone process
entry point.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..services.proposal_worker import ProposalWorker


def run_once(session: Session, worker_id: str, *, worker: ProposalWorker | None = None) -> bool:
    """Claim and run at most one proposal section job; True when a job was claimed."""

    return (worker or ProposalWorker()).run_once(session, worker_id)


__all__ = ["run_once"]
