from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import AuditEvent, Base, ScheduleExecution, ScheduleReservation
from app.services.scheduler import (
    EnvironmentDisabledError,
    SchedulerService,
    daily_run_key,
    previous_week_window,
)


def _service(tmp_path: Path, *, enabled: bool = False, now: datetime | None = None):
    engine = create_engine(f"sqlite:///{tmp_path / 'schedule.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(bidops_root=tmp_path, database_url=f"sqlite:///{tmp_path / 'schedule.db'}", scheduler_enabled=enabled)
    return engine, SchedulerService(settings, session_factory=factory, clock=lambda: now or datetime(2026, 8, 26, 3, tzinfo=timezone.utc))


def test_reservation_pk_and_duplicate_execution_are_transactional(tmp_path: Path):
    engine, service = _service(tmp_path)
    first = service.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    duplicate = service.reserve_daily(date(2026, 8, 25), trigger="manual", requested_by="tester")
    assert first is not None and first.status == "예약"
    assert duplicate is not None and duplicate.status == "건너뜀"
    with Session(engine) as session:
        assert session.get(ScheduleReservation, daily_run_key(date(2026, 8, 25))) is not None
        assert session.scalar(select(ScheduleExecution).where(ScheduleExecution.status == "예약")).execution_id == duplicate.duplicate_of_execution_id
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "schedule.execution_skipped_duplicate")) is not None


def test_environment_false_creates_no_automatic_reservation_and_rejects_enable(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=False)
    assert service.reserve_daily(date(2026, 8, 25)) is None
    try:
        service.set_enabled(True, confirmed_by="operator")
    except EnvironmentDisabledError as exc:
        assert str(exc) == "environment_disabled"
    else:  # pragma: no cover
        raise AssertionError("enable must be rejected by environment cap")


def test_seoul_date_and_monday_boundary_are_frozen(tmp_path: Path):
    now = datetime(2026, 8, 30, 15, 30, tzinfo=timezone.utc)  # Monday 00:30 KST
    _engine, service = _service(tmp_path, now=now)
    assert previous_week_window(now) == (date(2026, 8, 24), date(2026, 8, 30))
    assert daily_run_key(date(2026, 8, 30)) == "20260830-20260830"
    assert service.get_schedule_settings().timezone == "Asia/Seoul"
