"""Durable periodic-job scheduling.

APScheduler is only a clock/wakeup source here.  Reservation ownership and
duplicate handling are decided by SQLite constraints and transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import logging
import re
import time as _time
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..models import (
    AlwaysOnState,
    ScreeningAuditEvent,
    QualityGate,
    QualityGateEvaluation,
    ScheduleExecution,
    ScheduleReservation,
    ScheduleSetting,
    ScreeningPolicy,
    ScreeningExecution,
    utc_now,
)
from ..screening.ollama import OllamaClient
from ..screening.generation_config import (
    GenerationConfigError,
    config_from_value,
    generation_config_from_settings,
    validate_digest,
)
from ..screening.profile_snapshot import read_working_tree_source


logger = logging.getLogger(__name__)


TIMEZONE = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
DAILY_JOB_ID = "bidops-daily"
WEEKLY_JOB_ID = "bidops-weekly"
_HHMM = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class ScheduleError(RuntimeError):
    """Safe domain error raised by the schedule boundary."""


class EnvironmentDisabledError(ScheduleError):
    code = "environment_disabled"


class ScheduleConflictError(ScheduleError):
    pass


class ScheduleGateError(ScheduleError):
    code = "gate_mismatch"


def _validated_generation_binding(row: Any) -> tuple[Any, str]:
    """Parse and verify one persisted generation binding.

    Schedule rows historically carried only a digest. New rows may carry the
    canonical JSON object too; when it is present, accepting a digest without
    validating the object would make a tampered projection schedulable.
    """

    value = getattr(row, "generation_config_json", None)
    digest = getattr(row, "generation_config_digest", None)
    if value is None or digest is None:
        raise GenerationConfigError("generation config binding is missing")
    config = config_from_value(value)
    validate_digest(config, digest)
    if value != config.canonical_value():
        raise GenerationConfigError("generation config is not canonical")
    return config, digest


@dataclass(frozen=True)
class EnableResult:
    enabled: bool
    quality_gate_result_id: str | None = None
    policy_version: str | None = None
    model_name: str | None = None
    model_digest: str | None = None
    prompt_version: str | None = None
    company_profile_version: str | None = None
    company_profile_digest: str | None = None
    generation_config_digest: str | None = None
    rejection_reason: str | None = None


def _factory(value: Any | None) -> sessionmaker[Session]:
    if value is None:
        from ..db import SessionLocal

        return SessionLocal
    if isinstance(value, Engine):
        return sessionmaker(bind=value, class_=Session, autoflush=False, expire_on_commit=False)
    if isinstance(value, Session):
        bind = value.get_bind()
        if not isinstance(bind, Engine):
            raise TypeError("session must be bound to an Engine")
        return sessionmaker(bind=bind, class_=Session, autoflush=False, expire_on_commit=False)
    if callable(value):
        return value
    raise TypeError("session_factory must be an Engine, Session, or callable")


def _local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(TIMEZONE)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(UTC)


def _clock_time(value: str) -> time:
    if not isinstance(value, str) or _HHMM.fullmatch(value) is None:
        raise ValueError("time must use HH:MM")
    hour, minute = (int(v) for v in value.split(":"))
    return time(hour, minute)


def daily_run_key(day: date) -> str:
    return f"{day:%Y%m%d}-{day:%Y%m%d}"


def weekly_run_key(start: date, end: date) -> str:
    return f"weekly:{start:%Y%m%d}-{end:%Y%m%d}"


def _validate_reservation_identity(
    *, run_key: str, job_kind: str, window_from: date, window_to: date
) -> None:
    """Reject malformed or semantically mismatched public reservations."""

    if not isinstance(run_key, str) or not run_key.strip():
        raise ValueError("run_key is required")
    if type(window_from) is not date or type(window_to) is not date:
        raise ValueError("reservation window must contain dates")
    if window_from > window_to:
        raise ValueError("window_from must not be after window_to")
    if job_kind == "daily":
        if run_key != daily_run_key(window_from) or window_from != window_to:
            raise ValueError("daily run_key/window mismatch")
    elif job_kind == "weekly":
        if window_from.weekday() != 0 or window_to != window_from + timedelta(days=6):
            raise ValueError("weekly window must be Monday through Sunday")
        if run_key != weekly_run_key(window_from, window_to):
            raise ValueError("weekly run_key/window mismatch")
    else:
        raise ValueError("invalid job_kind")


def previous_daily_target(now: datetime) -> date:
    return _local(now).date() - timedelta(days=1)


def previous_week_window(now: datetime) -> tuple[date, date]:
    current = _local(now).date()
    monday = current - timedelta(days=current.weekday())
    end = monday - timedelta(days=1)
    return end - timedelta(days=6), end


class SchedulerService:
    """Own schedule settings, APScheduler jobs, reservations and gate checks."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any | None = None,
        engine: Engine | None = None,
        scheduler: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        ollama: Any | None = None,
        on_daily: Callable[[str], Any] | None = None,
        on_weekly: Callable[[str], Any] | None = None,
    ) -> None:
        if session_factory is not None and engine is not None:
            raise TypeError("provide one of engine or session_factory")
        self.settings = settings or get_settings()
        self.session_factory = _factory(session_factory or engine)
        self.scheduler = scheduler or BackgroundScheduler(timezone=TIMEZONE)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ollama = ollama
        self.on_daily = on_daily
        self.on_weekly = on_weekly

    @property
    def apscheduler(self) -> Any:
        return self.scheduler

    def _run(self, fn: Callable[[Session], Any]) -> Any:
        for attempt in range(7):
            session = self.session_factory()
            if not isinstance(session, Session):
                raise TypeError("session factory did not return Session")
            try:
                result = fn(session)
                session.commit()
                return result
            except OperationalError as exc:
                session.rollback()
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                if attempt == 6:
                    raise ScheduleConflictError("database remained busy") from None
                _time.sleep(0.01 * (attempt + 1))
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        raise ScheduleConflictError("database remained busy")

    def _now(self) -> datetime:
        return _utc(self.clock())

    # Settings and APScheduler ---------------------------------------
    def get_schedule_settings(self) -> ScheduleSetting:
        def fn(session: Session) -> ScheduleSetting:
            row = session.get(ScheduleSetting, 1)
            if row is None:
                row = ScheduleSetting(
                    singleton_id=1,
                    timezone="Asia/Seoul",
                    daily_time=self.settings.schedule_daily_time,
                    weekly_time=self.settings.schedule_weekly_time,
                    prespec_enabled=self.settings.schedule_prespec,
                    updated_at=self._now(),
                    updated_by="system:scheduler",
                )
                session.add(row)
                session.flush()
            return row

        return self._run(fn)

    get_settings = get_schedule_settings
    get = get_schedule_settings

    def update_schedule_settings(
        self,
        *,
        daily_time: str | None = None,
        weekly_time: str | None = None,
        prespec_enabled: bool | None = None,
        updated_by: str,
    ) -> ScheduleSetting:
        if not isinstance(updated_by, str) or not updated_by.strip():
            raise ValueError("updated_by is required")
        if daily_time is not None:
            _clock_time(daily_time)
        if weekly_time is not None:
            _clock_time(weekly_time)
        if prespec_enabled is not None and type(prespec_enabled) is not bool:
            raise ValueError("prespec_enabled must be boolean")

        def fn(session: Session) -> ScheduleSetting:
            row = session.get(ScheduleSetting, 1)
            if row is None:
                row = ScheduleSetting(
                    singleton_id=1,
                    timezone="Asia/Seoul",
                    daily_time=daily_time or self.settings.schedule_daily_time,
                    weekly_time=weekly_time or self.settings.schedule_weekly_time,
                    prespec_enabled=self.settings.schedule_prespec if prespec_enabled is None else prespec_enabled,
                    updated_at=self._now(),
                    updated_by=updated_by.strip(),
                )
                session.add(row)
            else:
                if daily_time is not None:
                    row.daily_time = daily_time
                if weekly_time is not None:
                    row.weekly_time = weekly_time
                if prespec_enabled is not None:
                    row.prespec_enabled = prespec_enabled
                row.updated_at = self._now()
                row.updated_by = updated_by.strip()
            self._audit(
                session,
                "schedule.settings_updated",
                "1",
                {
                    "daily_time": row.daily_time,
                    "weekly_time": row.weekly_time,
                    "prespec_enabled": bool(row.prespec_enabled),
                },
                actor=updated_by.strip(),
            )
            session.flush()
            return row

        result = self._run(fn)
        self.reschedule()
        return result

    update_settings = update_schedule_settings
    update = update_schedule_settings

    def _remove_jobs(self) -> None:
        remove = getattr(self.scheduler, "remove_job", None)
        if remove is None:
            return
        for job_id in (DAILY_JOB_ID, WEEKLY_JOB_ID):
            try:
                remove(job_id)
            except Exception:
                logger.warning(
                    "scheduler job removal failed",
                    extra={
                        "bidops": {
                            "event": "scheduler.job_remove_failed",
                            "job_id": job_id,
                        }
                    },
                    exc_info=True,
                )

    def reschedule(self) -> None:
        if not self.settings.scheduler_enabled:
            self._remove_jobs()
            return
        setting = self.get_schedule_settings()
        daily = _clock_time(setting.daily_time)
        weekly = _clock_time(setting.weekly_time)
        add = self.scheduler.add_job
        add(self._daily_callback, trigger="cron", hour=daily.hour, minute=daily.minute, timezone=TIMEZONE, id=DAILY_JOB_ID, replace_existing=True, coalesce=True, max_instances=1)
        add(self._weekly_callback, trigger="cron", day_of_week="mon", hour=weekly.hour, minute=weekly.minute, timezone=TIMEZONE, id=WEEKLY_JOB_ID, replace_existing=True, coalesce=True, max_instances=1)

    def start(self) -> bool:
        if not self.settings.scheduler_enabled:
            self._remove_jobs()
            return False
        self.reschedule()
        if not getattr(self.scheduler, "running", False):
            self.scheduler.start()
        self.catch_up()
        return True

    start_scheduler = start

    def shutdown(self, *, wait: bool = False) -> None:
        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=wait)

    stop = shutdown

    # Durable reservations -------------------------------------------
    def reserve_daily(self, day: date, **kwargs: Any) -> ScheduleExecution | None:
        return self.reserve(run_key=daily_run_key(day), job_kind="daily", window_from=day, window_to=day, **kwargs)

    def reserve_weekly(self, start: date, end: date, **kwargs: Any) -> ScheduleExecution | None:
        return self.reserve(run_key=weekly_run_key(start, end), job_kind="weekly", window_from=start, window_to=end, **kwargs)

    def reserve(
        self,
        *,
        run_key: str,
        job_kind: str,
        window_from: date,
        window_to: date,
        trigger: str = "schedule",
        requested_by: str = "system:scheduler",
        recovery_of: str | None = None,
    ) -> ScheduleExecution | None:
        _validate_reservation_identity(
            run_key=run_key,
            job_kind=job_kind,
            window_from=window_from,
            window_to=window_to,
        )
        if trigger not in {"schedule", "manual"}:
            raise ValueError("invalid schedule request")
        if trigger == "schedule" and (not self.settings.scheduler_enabled or requested_by != "system:scheduler"):
            return None if not self.settings.scheduler_enabled else (_ for _ in ()).throw(ValueError("invalid scheduler actor"))
        if not isinstance(requested_by, str) or not requested_by.strip():
            raise ValueError("invalid reservation")

        def fn(session: Session) -> ScheduleExecution:
            # A durable always-on projection is the source of the schedule
            # identity. Check its frozen generation binding before creating a
            # reservation or execution row. This path deliberately does not
            # inspect Ollama; config drift must be observable without a model
            # call and must fail closed first.
            self._assert_generation_for_reservation(session)
            reservation = session.get(ScheduleReservation, run_key)
            if reservation is None:
                if recovery_of is not None:
                    raise ScheduleConflictError("recovery requires an existing reservation")
                reservation = ScheduleReservation(run_key=run_key, job_kind=job_kind, window_from=window_from, window_to=window_to, timezone="Asia/Seoul", created_at=self._now())
                session.add(reservation)
                session.flush()
                row = ScheduleExecution(
                    execution_id="sched-" + uuid4().hex,
                    run_key=run_key,
                    job_kind=job_kind,
                    trigger=trigger,
                    status="예약",
                    requested_by=requested_by.strip(),
                    **self._schedule_generation_fields(session),
                )
                session.add(row)
                session.flush()
                self._audit(session, "schedule.execution_reserved", row.execution_id, {"run_key": run_key}, actor=requested_by.strip())
                return row
            if reservation.job_kind != job_kind or reservation.window_from != window_from or reservation.window_to != window_to:
                raise ScheduleConflictError("reservation identity mismatch")
            if recovery_of is not None:
                target = session.get(ScheduleExecution, recovery_of)
                if target is None or target.run_key != run_key or target.status not in {"실패", "부분 성공", "건너뜀"}:
                    raise ScheduleConflictError("only failed, partial, or skipped execution may be recovered")
                row = ScheduleExecution(
                    execution_id="sched-" + uuid4().hex,
                    run_key=run_key,
                    job_kind=job_kind,
                    trigger="manual",
                    status="예약",
                    recovery_of_execution_id=target.execution_id,
                    requested_by=requested_by.strip(),
                    **self._schedule_generation_fields(session, target=target),
                )
                session.add(row)
                session.flush()
                self._audit(session, "schedule.execution_recovered", row.execution_id, {"run_key": run_key}, actor=requested_by.strip())
                return row
            existing = session.scalar(select(ScheduleExecution).where(ScheduleExecution.run_key == run_key, ScheduleExecution.duplicate_of_execution_id.is_(None)).order_by(ScheduleExecution.execution_id.asc()).limit(1))
            if existing is None:
                raise ScheduleConflictError("reservation has no execution")
            row = ScheduleExecution(
                execution_id="sched-" + uuid4().hex,
                run_key=run_key,
                job_kind=job_kind,
                trigger=trigger,
                status="건너뜀",
                duplicate_of_execution_id=existing.execution_id,
                skip_reason="duplicate_reservation",
                requested_by=requested_by.strip(),
                **self._schedule_generation_fields(session),
            )
            session.add(row)
            session.flush()
            self._audit(session, "schedule.execution_skipped_duplicate", row.execution_id, {"run_key": run_key, "duplicate_of": existing.execution_id, "skip_reason": "duplicate_reservation"}, actor=requested_by.strip())
            return row

        try:
            return self._run(fn)
        except IntegrityError:
            if recovery_of is not None:
                raise ScheduleConflictError("reservation race during recovery") from None
            # The PK winner is now visible to a fresh transaction.  Record the
            # loser as a skipped execution and do not update the winner.
            def loser(session: Session) -> ScheduleExecution:
                existing = session.scalar(select(ScheduleExecution).where(ScheduleExecution.run_key == run_key, ScheduleExecution.duplicate_of_execution_id.is_(None)).order_by(ScheduleExecution.execution_id.asc()).limit(1))
                if existing is None:
                    raise ScheduleConflictError("reservation race unresolved")
                row = ScheduleExecution(
                    execution_id="sched-" + uuid4().hex,
                    run_key=run_key,
                    job_kind=job_kind,
                    trigger=trigger,
                    status="건너뜀",
                    duplicate_of_execution_id=existing.execution_id,
                    skip_reason="duplicate_reservation",
                    requested_by=requested_by.strip(),
                    **self._schedule_generation_fields(session),
                )
                session.add(row)
                session.flush()
                self._audit(session, "schedule.execution_skipped_duplicate", row.execution_id, {"run_key": run_key, "duplicate_of": existing.execution_id, "skip_reason": "duplicate_reservation"}, actor=requested_by.strip())
                return row

            return self._run(loser)

    create_reservation = reserve
    reserve_run = reserve

    def recover(self, execution_id: str, *, requested_by: str) -> ScheduleExecution:
        if not isinstance(requested_by, str) or not requested_by.strip():
            raise ValueError("requested_by is required")
        def fn(session: Session) -> ScheduleExecution:
            target = session.get(ScheduleExecution, execution_id)
            if target is None:
                raise ScheduleConflictError("execution not found")
            reservation = session.get(ScheduleReservation, target.run_key)
            if reservation is None:
                raise ScheduleConflictError("reservation not found")
            if target.status not in {"실패", "부분 성공", "건너뜀"}:
                raise ScheduleConflictError("successful execution cannot be recovered")
            self._assert_generation_for_reservation(session, target=target)
            row = ScheduleExecution(
                execution_id="sched-" + uuid4().hex,
                run_key=target.run_key,
                job_kind=target.job_kind,
                trigger="manual",
                status="예약",
                recovery_of_execution_id=target.execution_id,
                requested_by=requested_by.strip(),
                **self._schedule_generation_fields(session, target=target),
            )
            session.add(row)
            session.flush()
            self._audit(session, "schedule.execution_recovered", row.execution_id, {"run_key": target.run_key}, actor=requested_by.strip())
            return row

        return self._run(fn)

    def _assert_generation_for_reservation(
        self,
        session: Session,
        *,
        target: ScheduleExecution | None = None,
    ) -> None:
        """Reject environment drift before a reservation/recovery is added.

        Manual schedule fixtures from before generation binding can still be
        inspected when always-on is disabled. Once an always-on projection is
        enabled, however, every scheduled or recovered row must carry the
        same canonical generation identity as the current process settings.
        """

        try:
            current = generation_config_from_settings(self.settings)
            target_digest = getattr(target, "generation_config_digest", None) if target is not None else None
            if target_digest is not None and target_digest != current.digest():
                raise GenerationConfigError("schedule execution generation config differs from current settings")
            if target is not None and getattr(target, "generation_config_json", None) is not None:
                target_config, verified_target_digest = _validated_generation_binding(target)
                if verified_target_digest != current.digest() or target_config.digest() != current.digest():
                    raise GenerationConfigError("schedule execution generation config differs from current settings")
            state = session.get(AlwaysOnState, 1)
            if state is None or not bool(state.enabled):
                return
            expected_digest = target_digest or state.generation_config_digest
            # A projection produced by the new binding migration has a
            # digest. Keep disabled/legacy fixtures readable, but once a
            # binding is present it is an exact environment contract.
            if expected_digest is None:
                return
            if expected_digest != current.digest():
                raise GenerationConfigError("generation config differs from current settings")
            state_value = getattr(state, "generation_config_json", None)
            if state_value is not None:
                state_config = config_from_value(state_value)
                validate_digest(state_config, state.generation_config_digest)
                if state_config.digest() != current.digest():
                    raise GenerationConfigError("always-on generation config differs from current settings")
        except (GenerationConfigError, TypeError, ValueError):
            self._audit(
                session,
                "schedule.execution_rejected",
                getattr(target, "execution_id", "reservation"),
                {"reason": "generation_config_mismatch"},
            )
            raise ScheduleConflictError("generation_config_mismatch") from None

    @staticmethod
    def _schedule_generation_fields(
        session: Session,
        *,
        target: ScheduleExecution | None = None,
    ) -> dict[str, Any]:
        """Copy the approved binding into a newly durable schedule row."""

        if target is not None and getattr(target, "generation_config_digest", None) is not None:
            fields: dict[str, Any] = {"generation_config_digest": target.generation_config_digest}
            target_value = getattr(target, "generation_config_json", None)
            if target_value is not None and hasattr(ScheduleExecution, "generation_config_json"):
                fields["generation_config_json"] = target_value
            return fields
        state = session.get(AlwaysOnState, 1)
        if state is None or not bool(state.enabled):
            return {}
        fields: dict[str, Any] = {"generation_config_digest": state.generation_config_digest}
        state_value = getattr(state, "generation_config_json", None)
        if state_value is not None and hasattr(ScheduleExecution, "generation_config_json"):
            fields["generation_config_json"] = state_value
        return fields

    manual_recovery = recover
    recover_execution = recover

    def get_execution(self, execution_id: str) -> ScheduleExecution | None:
        return self._run(lambda session: session.get(ScheduleExecution, execution_id))

    def list_executions(self, *, status: str | None = None, from_date: date | None = None, to_date: date | None = None, limit: int = 100, offset: int = 0) -> list[ScheduleExecution]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("invalid pagination")

        def fn(session: Session) -> list[ScheduleExecution]:
            stmt = select(ScheduleExecution).join(ScheduleReservation, ScheduleExecution.run_key == ScheduleReservation.run_key)
            if status is not None:
                stmt = stmt.where(ScheduleExecution.status == status)
            if from_date is not None:
                stmt = stmt.where(ScheduleReservation.window_to >= from_date)
            if to_date is not None:
                stmt = stmt.where(ScheduleReservation.window_from <= to_date)
            return list(session.scalars(stmt.order_by(ScheduleReservation.window_from.desc(), ScheduleExecution.execution_id.desc()).limit(limit).offset(offset)))

        return self._run(fn)

    # Always-on switch and gate --------------------------------------
    def get_always_on(self) -> AlwaysOnState:
        return self._run(lambda session: self._ensure_switch(session))

    get_always_on_state = get_always_on

    def set_enabled(
        self,
        enabled: bool,
        *,
        confirmed_by: str | None = None,
        updated_by: str | None = None,
        quality_gate_result_id: str | None = None,
    ) -> EnableResult:
        confirmed_by = confirmed_by or updated_by
        if type(enabled) is not bool or not isinstance(confirmed_by, str) or not confirmed_by.strip():
            raise ValueError("invalid always-on request")
        if enabled and not self.settings.scheduler_enabled:
            self._reject_environment(actor=confirmed_by.strip())
            raise EnvironmentDisabledError("environment_disabled")

        was_enabled = False

        def fn(session: Session) -> EnableResult:
            nonlocal was_enabled
            state = self._ensure_switch(session)
            if not enabled:
                state.enabled = False
                state.updated_at = self._now()
                state.updated_by = confirmed_by.strip()
                self._audit(session, "schedule.always_on_disabled", "1", {"reason": "operator_disabled"}, actor=confirmed_by.strip())
                return self._result(state)
            was_enabled = bool(state.enabled)
            metadata, reason = self._approval(session)
            # The caller must submit the immutable evaluation revision that is
            # currently operationally approved.  Looking up "some" latest
            # passing evaluation here would allow a stale UI to activate a
            # different policy/model/profile combination.
            if metadata is not None and quality_gate_result_id is not None and quality_gate_result_id != metadata.get("quality_gate_result_id"):
                metadata = None
                reason = "quality_gate_result_mismatch"
            if metadata is None:
                state.enabled = False
                state.updated_at = self._now()
                state.updated_by = "system:quality-gate"
                self._audit(session, "schedule.always_on_enable_rejected", "1", {"reason": reason or "gate_mismatch"})
                # Return a committed rejection projection.  Raising inside
                # this transaction would roll back the required disable and
                # its audit event.
                return EnableResult(
                    enabled=False,
                    quality_gate_result_id=state.quality_gate_result_id,
                    policy_version=state.policy_version,
                    model_name=state.model_name,
                    model_digest=state.model_digest,
                    prompt_version=state.prompt_version,
                    company_profile_version=state.company_profile_version,
                    company_profile_digest=state.company_profile_digest,
                    rejection_reason=reason or "gate_mismatch",
                )
            # Compatibility for test/dry-run approval adapters that predate
            # the explicit field. Real `_approval` always returns this exact
            # binding; synthesize only the current settings here so the DB
            # enabled-metadata constraint cannot be bypassed with NULL.
            if "generation_config_digest" not in metadata:
                try:
                    current = generation_config_from_settings(self.settings)
                except (GenerationConfigError, TypeError, ValueError):
                    metadata = None
                    reason = "generation_config_mismatch"
                else:
                    metadata = dict(metadata)
                    metadata["generation_config_digest"] = current.digest()
                    if hasattr(state, "generation_config_json"):
                        metadata["generation_config_json"] = current.canonical_value()
            if metadata is None:
                state.enabled = False
                state.updated_at = self._now()
                state.updated_by = "system:quality-gate"
                self._audit(session, "schedule.always_on_enable_rejected", "1", {"reason": reason or "generation_config_mismatch"})
                return EnableResult(enabled=False, rejection_reason=reason or "generation_config_mismatch")
            for key, value in metadata.items():
                setattr(state, key, value)
            state.enabled = True
            state.updated_at = self._now()
            state.updated_by = confirmed_by.strip()
            self._audit(session, "schedule.always_on_enabled", "1", {"quality_gate_result_id": state.quality_gate_result_id, "policy_version": state.policy_version, "prompt_version": state.prompt_version}, actor=confirmed_by.strip())
            return self._result(state)

        result = self._run(fn)
        if enabled and result.rejection_reason:
            raise ScheduleGateError(result.rejection_reason)
        self.reschedule()
        if enabled and not was_enabled:
            self.catch_up(first_enable=True)
        return result

    set_always_on = set_enabled
    update_always_on = set_enabled

    def _effective_enabled(self) -> bool:
        if not self.settings.scheduler_enabled:
            return False

        def fn(session: Session) -> bool:
            state = self._ensure_switch(session)
            if not state.enabled:
                return False
            metadata, reason = self._approval(session)
            if metadata is None or any(getattr(state, key) != value for key, value in metadata.items()):
                state.enabled = False
                state.updated_at = self._now()
                state.updated_by = "system:quality-gate"
                self._audit(session, "schedule.always_on_disabled", "1", {"reason": reason or "approval_metadata_mismatch"})
                return False
            return True

        return bool(self._run(fn))

    effective_enabled = _effective_enabled
    is_effectively_enabled = _effective_enabled

    def _profile_identity(self, session: Session) -> tuple[str, str] | None:
        try:
            digest = read_working_tree_source(Path(self.settings.bidops_root)).digest
        except Exception:
            # A DB snapshot without readable current bytes is not proof that
            # the current profile is unchanged.  Disable automatic scheduling
            # rather than silently approving a stale profile.
            return None
        return f"company-profile.sha256:{digest}", digest

    def _approval(self, session: Session) -> tuple[dict[str, Any] | None, str | None]:
        policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.status == "active", ScreeningPolicy.active_slot == 1))
        if policy is None:
            return None, "active_policy_missing"
        profile = self._profile_identity(session)
        if profile is None:
            return None, "profile_unavailable"
        evaluation = session.scalar(select(QualityGateEvaluation).join(QualityGate, QualityGate.gate_id == QualityGateEvaluation.gate_id).where(QualityGate.purpose == "operational_approval", QualityGate.execution_status == "완료", QualityGateEvaluation.result_status == "통과").order_by(QualityGateEvaluation.created_at.desc(), QualityGateEvaluation.revision.desc()).limit(1))
        if evaluation is None:
            return None, "operational_approval_missing"
        gate = session.get(QualityGate, evaluation.gate_id)
        # The immutable evaluation is authoritative.  ``quality_gate`` is a
        # projection and may be updated by a trigger after the evaluation is
        # appended, so its result label is not an approval source.
        if gate is None or gate.execution_status != "완료":
            return None, "operational_approval_invalid"
        latest = session.scalar(select(QualityGateEvaluation.revision).where(QualityGateEvaluation.gate_id == gate.gate_id).order_by(QualityGateEvaluation.revision.desc()).limit(1))
        if latest != evaluation.revision:
            return None, "operational_approval_not_latest"
        if (gate.policy_version != policy.policy_version or gate.prompt_version != policy.prompt_version or gate.company_profile_version != profile[0] or gate.company_profile_digest != profile[1] or policy.quality_gate_result_id != evaluation.evaluation_id):
            return None, "approval_metadata_mismatch"
        try:
            gate_config, gate_digest = _validated_generation_binding(gate)
            if gate_digest != evaluation.generation_config_digest:
                return None, "generation_config_mismatch"
            evaluation_value = getattr(evaluation, "generation_config_json", None)
            if evaluation_value is not None:
                evaluation_config = config_from_value(evaluation_value)
                validate_digest(evaluation_config, evaluation.generation_config_digest)
                if evaluation_value != evaluation_config.canonical_value() or evaluation_config.canonical_value() != gate_config.canonical_value():
                    return None, "generation_config_mismatch"
        except (GenerationConfigError, TypeError, ValueError):
            return None, "generation_config_mismatch"
        passes = [
            session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))
            for execution_id in (gate.pass_a_execution_id, gate.pass_b_execution_id)
        ]
        try:
            pass_bindings = [_validated_generation_binding(row) for row in passes]
        except (GenerationConfigError, TypeError, ValueError):
            return None, "generation_config_mismatch"
        if any(
            digest != gate_digest or config.canonical_value() != gate_config.canonical_value()
            for config, digest in pass_bindings
        ):
            return None, "generation_config_mismatch"
        # A scheduler enable is an approval for subsequent executions.  Bind
        # the current process settings to that approval now; a changed env
        # budget must fail closed before any reservation can invoke a worker.
        try:
            current_generation = generation_config_from_settings(self.settings)
        except (GenerationConfigError, TypeError, ValueError):
            return None, "generation_config_mismatch"
        # The process environment is part of the approval boundary. Legacy
        # all-2048 rows have no intentional scheduled execution path and are
        # therefore rejected instead of being treated as an exception.
        if current_generation.digest() != gate_digest:
            return None, "generation_config_mismatch"
        inspector = self.ollama or OllamaClient(settings=self.settings)
        try:
            identity = inspector.inspect_model(refresh=True)
        except Exception:
            return None, "ollama_unavailable"
        model_name = getattr(identity, "model_name", None)
        model_digest = getattr(identity, "digest", None)
        if isinstance(identity, dict):
            model_name = identity.get("model_name") or identity.get("name")
            model_digest = identity.get("digest") or identity.get("model_digest")
        if model_name != self.settings.model_name or model_name != gate.model_name or model_digest != gate.model_digest:
            return None, "model_identity_mismatch"
        metadata = {
            "quality_gate_result_id": evaluation.evaluation_id,
            "policy_version": policy.policy_version,
            "model_name": gate.model_name,
            "model_digest": gate.model_digest,
            "prompt_version": policy.prompt_version,
            "company_profile_version": profile[0],
            "company_profile_digest": profile[1],
            "generation_config_digest": gate_digest,
        }
        if hasattr(AlwaysOnState, "generation_config_json"):
            metadata["generation_config_json"] = gate_config.canonical_value()
        return metadata, None

    # Catch-up and callbacks -----------------------------------------
    def _daily_callback(self) -> Any:
        if not self._effective_enabled():
            return None
        row = self.reserve_daily(previous_daily_target(self.clock()))
        if row is not None and row.status == "예약":
            if self.on_daily:
                return self.on_daily(row.execution_id)
        return row

    def _weekly_callback(self) -> Any:
        if not self._effective_enabled():
            return None
        start, end = previous_week_window(self.clock())
        row = self.reserve_weekly(start, end)
        if row is not None and row.status == "예약":
            if self.on_weekly:
                return self.on_weekly(row.execution_id)
        return row

    def catch_up(self, *, first_enable: bool = False) -> list[ScheduleExecution]:
        # A stale/mismatched projection is disabled before any reservation is
        # created.  This keeps restart catch-up subject to the same approval
        # boundary as the cron callbacks.
        if not self.settings.scheduler_enabled or not self._effective_enabled():
            return []
        now = _local(self.clock())
        rows: list[ScheduleExecution] = []
        setting = self.get_schedule_settings()
        yesterday = now.date() - timedelta(days=1)
        if first_enable:
            if now.time().replace(tzinfo=None) >= _clock_time(setting.daily_time):
                row = self.reserve_daily(yesterday)
                if row is not None and row.status == "예약":
                    rows.append(row)
        else:
            existing = self._run(lambda s: list(s.scalars(select(ScheduleReservation).where(ScheduleReservation.job_kind == "daily", ScheduleReservation.window_to <= yesterday).order_by(ScheduleReservation.window_to.asc()))))
            if existing:
                day = max(x.window_to for x in existing) + timedelta(days=1)
                while day <= yesterday:
                    row = self.reserve_daily(day)
                    if row is not None and row.status == "예약":
                        rows.append(row)
                    day += timedelta(days=1)
        monday = now.date() - timedelta(days=now.date().weekday())
        if first_enable and now.date().weekday() == 0 and now.time().replace(tzinfo=None) >= _clock_time(setting.weekly_time):
            start, end = monday - timedelta(days=7), monday - timedelta(days=1)
            if not self._weekly_exists(start, end):
                row = self.reserve_weekly(start, end)
                if row is not None and row.status == "예약":
                    rows.append(row)
        elif not first_enable:
            start, end = monday - timedelta(days=7), monday - timedelta(days=1)
            if not self._weekly_exists(start, end):
                row = self.reserve_weekly(start, end)
                if row is not None and row.status == "예약":
                    rows.append(row)
        # Reservations are created before callbacks are invoked.  This makes
        # a callback crash unable to create a second reservation on restart,
        # while preserving an oldest-first execution order.
        rows.sort(key=lambda row: (0 if row.job_kind == "daily" else 1, row.run_key))
        for row in rows:
            callback = self.on_daily if row.job_kind == "daily" else self.on_weekly
            if callback is not None:
                callback(row.execution_id)
        return rows

    def _switch_enabled(self) -> bool:
        return bool(self._run(lambda s: self._ensure_switch(s).enabled))

    def _weekly_exists(self, start: date, end: date) -> bool:
        return bool(self._run(lambda s: s.get(ScheduleReservation, weekly_run_key(start, end)) is not None))

    # Helpers ---------------------------------------------------------
    def _ensure_switch(self, session: Session) -> AlwaysOnState:
        row = session.get(AlwaysOnState, 1)
        if row is None:
            row = AlwaysOnState(singleton_id=1, enabled=False, updated_at=self._now(), updated_by="system:scheduler")
            session.add(row)
            session.flush()
        return row

    @staticmethod
    def _audit(session: Session, event_type: str, target_id: str, details: dict[str, Any], *, actor: str = "system:scheduler") -> None:
        allowed = {
            "reason",
            "run_key",
            "duplicate_of",
            "skip_reason",
            "quality_gate_result_id",
            "policy_version",
            "prompt_version",
            "daily_time",
            "weekly_time",
            "prespec_enabled",
        }
        session.add(ScreeningAuditEvent(event_id="audit-" + uuid4().hex, event_type=event_type, actor=actor, target_type="schedule", target_id=target_id, occurred_at=utc_now(), details_json={k: v for k, v in details.items() if k in allowed}))

    @staticmethod
    def _result(state: AlwaysOnState) -> EnableResult:
        return EnableResult(state.enabled, state.quality_gate_result_id, state.policy_version, state.model_name, state.model_digest, state.prompt_version, state.company_profile_version, state.company_profile_digest, state.generation_config_digest)

    def _reject_environment(self, *, actor: str = "system:scheduler") -> None:
        self._run(lambda s: self._audit(s, "schedule.always_on_enable_rejected", "1", {"reason": "environment_disabled"}, actor=actor))


ScheduleService = SchedulerService
Scheduler = SchedulerService
ScheduleReservationService = SchedulerService

__all__ = [
    "DAILY_JOB_ID", "WEEKLY_JOB_ID", "EnableResult", "EnvironmentDisabledError",
    "ScheduleConflictError", "ScheduleError", "ScheduleGateError", "ScheduleService",
    "Scheduler", "SchedulerService", "ScheduleReservationService", "TIMEZONE", "daily_run_key", "weekly_run_key",
    "previous_daily_target", "previous_week_window",
]
