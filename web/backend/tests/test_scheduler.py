from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
import pytest

from app.core.db import _json_serializer, schema_bound
from app.core.db import Base
from app.screening.models import (
    AlwaysOnState,
    ScheduleExecution,
    ScheduleReservation,
    ScreeningAuditEvent,
)
from app.services.scheduler import (
    EnvironmentDisabledError,
    ScheduleGateError,
    SchedulerService,
    daily_run_key,
    previous_week_window,
)
from tests.postgres import requires_postgres, temporary_database


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
        assert session.scalar(select(ScreeningAuditEvent).where(ScreeningAuditEvent.event_type == "schedule.execution_skipped_duplicate")) is not None


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


def test_public_reserve_rejects_malformed_and_semantically_mismatched_keys(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True)
    with pytest.raises(ValueError):
        service.reserve(run_key="not-a-run", job_kind="daily", window_from=date(2026, 8, 25), window_to=date(2026, 8, 25))
    with pytest.raises(ValueError):
        service.reserve(run_key="20260825-20260826", job_kind="daily", window_from=date(2026, 8, 25), window_to=date(2026, 8, 26))
    with pytest.raises(ValueError):
        service.reserve(run_key="weekly:20260825-20260831", job_kind="weekly", window_from=date(2026, 8, 25), window_to=date(2026, 8, 31))


def test_catch_up_dispatches_oldest_daily_reservations_to_callback(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True, now=datetime(2026, 8, 28, 3, tzinfo=timezone.utc))
    service.reserve_daily(date(2026, 8, 24))
    service.reserve_daily(date(2026, 8, 25))
    service._effective_enabled = lambda: True
    seen: list[str] = []
    service.on_daily = seen.append
    rows = service.catch_up()
    assert [row.run_key for row in rows if row.job_kind == "daily"] == [
        "20260826-20260826",
        "20260827-20260827",
    ]
    assert seen == [row.execution_id for row in rows if row.job_kind == "daily"]


def test_restart_start_dispatches_catch_up_reservations(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True, now=datetime(2026, 8, 28, 3, tzinfo=timezone.utc))
    service.reserve_daily(date(2026, 8, 24))
    service.reserve_daily(date(2026, 8, 25))

    class FakeScheduler:
        running = True

        def add_job(self, *args, **kwargs):
            return None

        def remove_job(self, _job_id):
            return None

    service.scheduler = FakeScheduler()
    service._effective_enabled = lambda: True
    seen: list[str] = []
    service.on_daily = seen.append
    rows = service.start()
    assert rows is True
    assert len(seen) == 2


def test_first_enable_dispatches_only_the_previous_daily_target(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True, now=datetime(2026, 8, 26, 3, tzinfo=timezone.utc))

    class FakeScheduler:
        running = True

        def add_job(self, *args, **kwargs):
            return None

        def remove_job(self, _job_id):
            return None

    metadata = {
        "quality_gate_result_id": "gateeval-" + "a" * 32,
        "policy_version": "policy-v1",
        "model_name": "qwen3.8:27b",
        "model_digest": "a" * 64,
        "prompt_version": "prompt-v1",
        "company_profile_version": "profile-v1",
        "company_profile_digest": "b" * 64,
    }
    service.scheduler = FakeScheduler()
    service._approval = lambda _session: (metadata, None)
    service._effective_enabled = lambda: True
    seen: list[str] = []
    service.on_daily = seen.append
    service.set_enabled(True, confirmed_by="operator")
    assert len(seen) == 1
    assert service.list_executions()[0].run_key == "20260825-20260825"


def test_first_enable_monday_dispatches_daily_and_weekly_callbacks(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True, now=datetime(2026, 8, 30, 23, tzinfo=timezone.utc))

    class FakeScheduler:
        running = True

        def add_job(self, *args, **kwargs):
            return None

        def remove_job(self, _job_id):
            return None

    metadata = {
        "quality_gate_result_id": "gateeval-" + "a" * 32,
        "policy_version": "policy-v1",
        "model_name": "qwen3.8:27b",
        "model_digest": "a" * 64,
        "prompt_version": "prompt-v1",
        "company_profile_version": "profile-v1",
        "company_profile_digest": "b" * 64,
    }
    service.scheduler = FakeScheduler()
    service._approval = lambda _session: (metadata, None)
    service._effective_enabled = lambda: True
    daily: list[str] = []
    weekly: list[str] = []
    service.on_daily = daily.append
    service.on_weekly = weekly.append
    service.set_enabled(True, confirmed_by="operator")
    assert len(daily) == 1
    assert len(weekly) == 1
    assert {row.run_key for row in service.list_executions()} == {
        "20260830-20260830",
        "weekly:20260824-20260830",
    }


def test_gate_rejection_commits_disable_and_audit_before_raising(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True)
    service._approval = lambda _session: (None, "approval_metadata_mismatch")
    with pytest.raises(ScheduleGateError):
        service.set_enabled(True, confirmed_by="operator")
    with Session(_engine) as session:
        assert session.get(AlwaysOnState, 1).enabled is False
        assert session.scalar(select(ScreeningAuditEvent).where(ScreeningAuditEvent.event_type == "schedule.always_on_enable_rejected")) is not None


def test_repeated_enable_does_not_run_first_enable_catch_up_again(tmp_path: Path):
    _engine, service = _service(tmp_path, enabled=True)
    metadata = {
        "quality_gate_result_id": "gateeval-" + "a" * 32,
        "policy_version": "policy-v1",
        "model_name": "qwen3.8:27b",
        "model_digest": "a" * 64,
        "prompt_version": "prompt-v1",
        "company_profile_version": "profile-v1",
        "company_profile_digest": "b" * 64,
    }
    service._approval = lambda _session: (metadata, None)
    calls: list[bool] = []
    service.catch_up = lambda **kwargs: calls.append(bool(kwargs.get("first_enable"))) or []
    service.set_enabled(True, confirmed_by="operator")
    service.set_enabled(True, confirmed_by="operator")
    assert calls == [True]


@requires_postgres
def test_migrated_postgresql_allows_recovery_of_skipped_execution(tmp_path: Path):
    with temporary_database() as database_url:
        engine = schema_bound(
            create_engine(database_url, future=True, json_serializer=_json_serializer)
        )
        run_key = "20260825-20260825"
        target_id = "sched-" + "1" * 32
        with Session(engine) as session:
            session.add(
                ScheduleReservation(
                    run_key=run_key,
                    job_kind="daily",
                    window_from=date(2026, 8, 25),
                    window_to=date(2026, 8, 25),
                    timezone="Asia/Seoul",
                    created_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
                )
            )
            session.flush()
            session.add(
                ScheduleExecution(
                    execution_id=target_id,
                    run_key=run_key,
                    job_kind="daily",
                    trigger="schedule",
                    status="건너뜀",
                    requested_by="system:scheduler",
                    skip_reason="duplicate_reservation",
                )
            )
            session.commit()
        settings = Settings(
            bidops_root=tmp_path, database_url=database_url, scheduler_enabled=True
        )
        service = SchedulerService(
            settings, session_factory=sessionmaker(bind=engine, expire_on_commit=False)
        )
        recovered = service.recover(target_id, requested_by="operator")
        assert recovered.recovery_of_execution_id == target_id
        engine.dispose()
