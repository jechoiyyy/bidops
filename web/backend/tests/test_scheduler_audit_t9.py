from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.screening.models import ScreeningAuditEvent
from app.services.scheduler import SchedulerService


def test_schedule_settings_audit_keeps_safe_values_and_actor() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = SchedulerService(Settings(), engine=engine)
    service.update_schedule_settings(
        daily_time="03:15",
        weekly_time="07:20",
        prespec_enabled=True,
        updated_by="operator:test",
    )
    with Session(engine) as session:
        event = session.scalar(
            select(ScreeningAuditEvent).where(ScreeningAuditEvent.event_type == "schedule.settings_updated")
        )
        assert event is not None
        assert event.actor == "operator:test"
        assert event.details_json == {
            "daily_time": "03:15",
            "weekly_time": "07:20",
            "prespec_enabled": True,
        }
        assert "secret" not in str(event.details_json).lower()
