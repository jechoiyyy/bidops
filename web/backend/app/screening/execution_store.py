"""State transitions and cooperative worker controls for screening runs."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
import threading
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from ..models import Run, ScreeningExecution
from .queue import (
    ACTIVE,
    INTERRUPTED,
    QUEUED,
    RUNNING,
    STOP_REQUESTED,
    ExecutionConflict,
    ExecutionNotFound,
    QueueValidationError,
    ScreeningQueue,
    STAGES,
    _actor,
    _new_event,
    normalize_utc,
    sanitize_error_summary,
)


_ALLOWED_TERMINAL = frozenset({"성공", "부분 성공", "실패"})


class HeartbeatPump(AbstractContextManager["HeartbeatPump"]):
    """A stoppable heartbeat worker using a fresh DB session per tick."""

    def __init__(
        self,
        store: "ScreeningExecutionStore",
        execution_id: str,
        *,
        interval: float | None = None,
        join_timeout: float = 1.0,
    ) -> None:
        self.store = store
        self.execution_id = execution_id
        configured_interval = getattr(store.settings, "heartbeat_seconds", None)
        if configured_interval is None:
            configured_interval = getattr(store.settings, "screen_heartbeat_seconds", 5)
        self.interval = max(0.01, float(interval if interval is not None else configured_interval))
        self.join_timeout = max(0.01, join_timeout)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> "HeartbeatPump":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name=f"screening-heartbeat-{self.execution_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _run(self) -> None:
        # An immediate tick makes the worker safe even when a call blocks for
        # less than one configured interval and proves fresh-session behavior.
        while not self._stop.is_set():
            try:
                updated = self.store.heartbeat(self.execution_id)
                if not updated:
                    return
            except Exception as exc:  # heartbeat must never kill the caller
                self.last_error = sanitize_error_summary(exc)
            self._stop.wait(self.interval)

    def stop(self, *, timeout: float | None = None) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(self.join_timeout if timeout is None else max(0.01, timeout))

    def __enter__(self) -> "HeartbeatPump":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


class ScreeningExecutionStore(ScreeningQueue):
    """Durable screening execution state machine.

    The inherited queue methods are command-style and use their own sessions.
    Transition methods follow the same rule.  ``should_stop`` and heartbeat
    intentionally re-read in fresh sessions so a worker's long-lived session
    cannot hide a stop request or starve liveness updates.
    """

    def heartbeat_pump(
        self,
        execution_id: str,
        *,
        interval: float | None = None,
        join_timeout: float = 1.0,
    ) -> HeartbeatPump:
        return HeartbeatPump(self, execution_id, interval=interval, join_timeout=join_timeout)

    # Friendly alias for callers that prefer the context-manager noun.
    heartbeat_thread = heartbeat_pump

    def heartbeat(self, execution_id: str, *, now: datetime | None = None) -> bool:
        """Advance liveness only for the matching active execution."""

        execution_id = self._execution_id(execution_id)
        point = normalize_utc(now, default=self.now)

        def command(session: Session) -> bool:
            result = session.execute(
                update(ScreeningExecution)
                .where(
                    ScreeningExecution.execution_id == execution_id,
                    ScreeningExecution.status.in_(ACTIVE),
                    ScreeningExecution.active_slot == 1,
                )
                .values(
                    heartbeat_at=case(
                        (ScreeningExecution.heartbeat_at.is_(None), point),
                        (ScreeningExecution.heartbeat_at < point, point),
                        else_=ScreeningExecution.heartbeat_at,
                    )
                )
            )
            return result.rowcount == 1

        return bool(self._run_command(command, busy_retries=0, busy_timeout_ms=50))

    def should_stop(self, execution_id: str) -> bool:
        """Freshly read whether cooperative interruption was requested."""

        execution_id = self._execution_id(execution_id)

        def command(session: Session) -> bool:
            row = session.scalar(
                select(ScreeningExecution.status).where(ScreeningExecution.execution_id == execution_id)
            )
            if row is None:
                raise ExecutionNotFound("execution does not exist")
            return row == STOP_REQUESTED

        return bool(self._run_command(command))

    stop_requested = should_stop

    def request_stop(self, execution_id: str, actor: str) -> ScreeningExecution:
        """Request or immediately apply a user stop, without touching a call."""

        execution_id = self._execution_id(execution_id)
        actor = _actor(actor, max_length=128)
        point = normalize_utc(None, default=self.now)

        def command(session: Session) -> ScreeningExecution:
            self._begin_immediate(session)
            row = session.scalar(
                select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
            )
            if row is None:
                raise ExecutionNotFound("execution does not exist")
            before = row.status
            if before == QUEUED:
                values = {
                    "status": INTERRUPTED,
                    "active_slot": None,
                    "stop_requested_at": point,
                    "stop_requested_by": actor,
                    "stop_reason": "user_requested",
                    "finished_at": point,
                    "current_notice_id": None,
                    "current_stage": None,
                    "published_run_id": None,
                }
                after = INTERRUPTED
            elif before == RUNNING:
                values = {
                    "status": STOP_REQUESTED,
                    "active_slot": 1,
                    "stop_requested_at": point,
                    "stop_requested_by": actor,
                    "stop_reason": "user_requested",
                    "published_run_id": None,
                }
                after = STOP_REQUESTED
            else:
                raise ExecutionConflict("execution cannot be stopped in its current state")
            changed = session.execute(
                update(ScreeningExecution)
                .where(ScreeningExecution.execution_id == execution_id, ScreeningExecution.status == before)
                .values(**values)
            )
            if changed.rowcount != 1:
                raise ExecutionConflict("execution state changed concurrently")
            session.add(
                _new_event(
                    event_type="screening_execution.stop_requested",
                    actor=actor,
                    target_id=execution_id,
                    details={"status_before": before, "status_after": after, "stop_reason": "user_requested"},
                    occurred_at=point,
                )
            )
            session.flush()
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))

        return self._run_command(command)

    def finish_interrupted(self, execution_id: str, *, now: datetime | None = None) -> ScreeningExecution:
        """Complete a stop-requested execution at the next worker boundary."""

        execution_id = self._execution_id(execution_id)
        point = normalize_utc(now, default=self.now)

        def command(session: Session) -> ScreeningExecution:
            row = self._get(session, execution_id)
            if row.status != STOP_REQUESTED:
                raise ExecutionConflict("execution is not waiting at a stop boundary")
            changed = session.execute(
                update(ScreeningExecution)
                .where(ScreeningExecution.execution_id == execution_id, ScreeningExecution.status == STOP_REQUESTED)
                .values(
                    status=INTERRUPTED,
                    active_slot=None,
                    current_notice_id=None,
                    current_stage=None,
                    finished_at=point,
                    published_run_id=None,
                )
            )
            if changed.rowcount != 1:
                raise ExecutionConflict("execution state changed concurrently")
            session.flush()
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))

        return self._run_command(command)

    def update_progress(
        self,
        execution_id: str,
        *,
        completed_count: int | None = None,
        failure_count: int | None = None,
        candidate_count: int | None = None,
        current_notice_id: str | None = None,
        current_stage: str | None = None,
        error_summary: str | None = None,
    ) -> ScreeningExecution:
        """Persist monotonic worker progress without changing identity fields."""

        execution_id = self._execution_id(execution_id)
        values_in = {
            "candidate_count": candidate_count,
            "completed_count": completed_count,
            "failure_count": failure_count,
        }
        if all(value is None for value in values_in.values()) and current_notice_id is None and current_stage is None and error_summary is None:
            raise QueueValidationError("progress update is empty")
        for label, value in values_in.items():
            if value is not None and (type(value) is not int or value < 0):
                raise QueueValidationError(f"{label} must be a nonnegative integer")
        if current_notice_id is not None:
            current_notice_id = current_notice_id.strip() if isinstance(current_notice_id, str) else None
            if not current_notice_id or len(current_notice_id) > 255:
                raise QueueValidationError("current_notice_id must be nonblank")
        if current_stage is not None:
            current_stage = current_stage.strip() if isinstance(current_stage, str) else None
            if not current_stage or len(current_stage) > 64 or current_stage not in STAGES:
                raise QueueValidationError("current_stage is invalid")
        summary = sanitize_error_summary(error_summary) if error_summary is not None else None

        def command(session: Session) -> ScreeningExecution:
            row = self._get(session, execution_id)
            if row.status not in ACTIVE:
                raise ExecutionConflict("progress requires an active execution")
            candidate = row.candidate_count if candidate_count is None else candidate_count
            completed = row.completed_count if completed_count is None else completed_count
            failures = row.failure_count if failure_count is None else failure_count
            if candidate < row.candidate_count or completed < row.completed_count or failures < row.failure_count:
                raise QueueValidationError("progress counts must be monotonic")
            if completed + failures > candidate:
                raise QueueValidationError("completed and failure counts exceed candidates")
            values: dict[str, Any] = {
                "candidate_count": candidate,
                "completed_count": completed,
                "failure_count": failures,
            }
            if current_notice_id is not None:
                values["current_notice_id"] = current_notice_id
            if current_stage is not None:
                values["current_stage"] = current_stage
            if summary is not None:
                values["error_summary"] = summary
            changed = session.execute(
                update(ScreeningExecution)
                .where(ScreeningExecution.execution_id == execution_id, ScreeningExecution.status.in_(ACTIVE))
                .values(**values)
            )
            if changed.rowcount != 1:
                raise ExecutionConflict("execution state changed concurrently")
            session.flush()
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))

        return self._run_command(command)

    def finish(
        self,
        execution_id: str,
        *,
        status: str,
        completed_count: int | None = None,
        failure_count: int | None = None,
        candidate_count: int | None = None,
        error_summary: str | None = None,
        published_run_id: str | None = None,
        now: datetime | None = None,
    ) -> ScreeningExecution:
        """Transition a running execution to one legal terminal status."""

        execution_id = self._execution_id(execution_id)
        if status not in _ALLOWED_TERMINAL:
            raise QueueValidationError("terminal status is invalid")
        if published_run_id is not None:
            if status not in {"성공", "부분 성공"} or not isinstance(published_run_id, str) or not published_run_id.strip():
                raise QueueValidationError("published_run_id is only valid for successful publication")
        for label, value in {
            "candidate_count": candidate_count,
            "completed_count": completed_count,
            "failure_count": failure_count,
        }.items():
            if value is not None and (type(value) is not int or value < 0):
                raise QueueValidationError(f"{label} must be a nonnegative integer")
        point = normalize_utc(now, default=self.now)
        summary = sanitize_error_summary(error_summary) if error_summary is not None else None

        def command(session: Session) -> ScreeningExecution:
            row = self._get(session, execution_id)
            if row.status != RUNNING:
                raise ExecutionConflict("terminal transition requires a running execution")
            candidate = row.candidate_count if candidate_count is None else candidate_count
            completed = row.completed_count if completed_count is None else completed_count
            failures = row.failure_count if failure_count is None else failure_count
            if candidate < row.candidate_count or completed < row.completed_count or failures < row.failure_count:
                raise QueueValidationError("terminal counts must be monotonic")
            if completed + failures > candidate:
                raise QueueValidationError("completed and failure counts exceed candidates")
            if published_run_id is not None:
                published = session.scalar(select(Run).where(Run.id == published_run_id))
                if published is None:
                    raise QueueValidationError("published run does not exist")
            values: dict[str, Any] = {
                "status": status,
                "active_slot": None,
                "current_notice_id": None,
                "current_stage": None,
                "finished_at": point,
                "candidate_count": candidate,
                "completed_count": completed,
                "failure_count": failures,
                "published_run_id": published_run_id,
            }
            if summary is not None:
                values["error_summary"] = summary
            changed = session.execute(
                update(ScreeningExecution)
                .where(ScreeningExecution.execution_id == execution_id, ScreeningExecution.status == RUNNING)
                .values(**values)
            )
            if changed.rowcount != 1:
                raise ExecutionConflict("execution state changed concurrently")
            session.flush()
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))

        return self._run_command(command)

    def finish_success(self, execution_id: str, **kwargs: Any) -> ScreeningExecution:
        return self.finish(execution_id, status="성공", **kwargs)

    def finish_partial(self, execution_id: str, **kwargs: Any) -> ScreeningExecution:
        return self.finish(execution_id, status="부분 성공", **kwargs)

    def finish_failure(self, execution_id: str, **kwargs: Any) -> ScreeningExecution:
        return self.finish(execution_id, status="실패", **kwargs)

    progress = update_progress
    transition_terminal = finish

    @staticmethod
    def _execution_id(value: Any) -> str:
        from .queue import _EXECUTION_ID

        if not isinstance(value, str) or _EXECUTION_ID.fullmatch(value) is None:
            raise QueueValidationError("execution_id is invalid")
        return value

    @staticmethod
    def _get(session: Session, execution_id: str) -> ScreeningExecution:
        row = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id))
        if row is None:
            raise ExecutionNotFound("execution does not exist")
        return row


ExecutionStore = ScreeningExecutionStore
