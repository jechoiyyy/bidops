"""SQLite mirrors the production active-job slot when an attempt is retried."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import schema_bound
from app.deep_review.models import WorkJob


def test_retry_keeps_terminal_job_and_enforces_single_active_job():
    engine = schema_bound(create_engine("sqlite://"))
    WorkJob.__table__.create(engine)
    target = uuid4()

    def job(status):
        return WorkJob(job_type="prespec_v4_overview", aggregate_type="prespec_v4_target", aggregate_id=target, status=status)

    try:
        with Session(engine) as session, session.begin():
            session.add(job("failed"))
            session.add(job("queued"))
        with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
            session.add(job("running"))
        with Session(engine) as session:
            assert sorted(session.scalars(select(WorkJob.status))) == ["failed", "queued"]
    finally:
        engine.dispose()
