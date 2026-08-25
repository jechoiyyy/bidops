"""Durable FIFO queue primitives for screening executions.

The queue is deliberately small.  It owns persistence and claiming only; it
never imports the model client and it never starts a screening call.  Every
command opens its own session so a request-scoped transaction cannot be
silently committed or rolled back by a queue operation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import re
import time
from typing import Any, Final
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..models import (
    AuditEvent,
    CompanyProfileSnapshot,
    Notice,
    Run,
    ScreeningExecution,
    ScreeningPolicy,
    utc_now,
)


TRIGGERS: Final[frozenset[str]] = frozenset(
    {"cli_single", "manual_run", "quality_gate", "schedule"}
)
MODEL_NAME: Final[str] = "qwen3.8:27b"
TRIGGER_SCOPES: Final[dict[str, str]] = {
    "cli_single": "single_notice",
    "manual_run": "full_run",
    "quality_gate": "quality_sample",
    "schedule": "full_run",
}
SCOPES: Final[frozenset[str]] = frozenset(
    {"single_notice", "full_run", "quality_sample"}
)
QUEUED: Final[str] = "대기"
RUNNING: Final[str] = "실행 중"
STOP_REQUESTED: Final[str] = "중지 요청"
INTERRUPTED: Final[str] = "중단됨"
TERMINAL: Final[frozenset[str]] = frozenset({"성공", "부분 성공", "실패", INTERRUPTED})
ACTIVE: Final[frozenset[str]] = frozenset({RUNNING, STOP_REQUESTED})
STAGES: Final[frozenset[str]] = frozenset(
    {
        "기술 적합성",
        "실적 정합성",
        "공공 SI 적합성",
        "사업성·자격 제약",
        "전략 부합",
        "counterargument",
        "synthesis",
        "carried_over_validation",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EXECUTION_ID = re.compile(r"^scr-[0-9a-f]{32}$")
_SAFE_PATH_PART = re.compile(r"^[^\x00]+$")
ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "execution_failure",
        "timeout",
        "truncated_output",
        "schema_violation",
        "evidence_missing",
        "counterargument_repetition",
        "model_inspection",
        "transport_failure",
        "database_busy",
        "invalid_state",
        "interrupted",
    }
)
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ScreeningQueueError(RuntimeError):
    """Base class for safe, operator-facing queue errors."""


class QueueValidationError(ScreeningQueueError, ValueError):
    """An enqueue or progress value violates the runtime contract."""


class ExecutionNotFound(ScreeningQueueError):
    """The requested execution does not exist."""


class ExecutionConflict(ScreeningQueueError):
    """A state transition conflicts with the durable execution state."""


class QueueBusy(ScreeningQueueError):
    """SQLite remained busy after the bounded retry policy."""


class QueueDatabaseError(ScreeningQueueError):
    """A non-busy database failure with SQL details deliberately removed."""


def normalize_utc(value: datetime | None, *, default: Callable[[], datetime] = utc_now) -> datetime:
    """Normalize an aware timestamp to UTC, rejecting naive timestamps."""

    result = default() if value is None else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise QueueValidationError("timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _text(value: Any, label: str, *, max_length: int = 255) -> str:
    if not isinstance(value, str):
        raise QueueValidationError(f"{label} must be text")
    result = value.strip()
    if not result:
        raise QueueValidationError(f"{label} must be nonblank")
    if len(result) > max_length:
        raise QueueValidationError(f"{label} is too long")
    return result


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise QueueValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def safe_relative_path(value: Any, label: str) -> str:
    """Validate a persisted path without resolving it against the filesystem."""

    result = _text(value, label, max_length=4096)
    if (
        result.startswith("/")
        or "\\" in result
        or not _SAFE_PATH_PART.fullmatch(result)
        or result in {".", ".."}
    ):
        raise QueueValidationError(f"{label} must be a safe relative path")
    parts = result.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise QueueValidationError(f"{label} must be a safe relative path")
    # A colon is not a valid portable relative artifact name and catches drive
    # prefixes without relying on the host operating system.
    if any(":" in part for part in parts):
        raise QueueValidationError(f"{label} must be a safe relative path")
    return result


def sanitize_error_summary(value: Any) -> str:
    """Keep only a short category-like error summary.

    Only an explicit, documented category code is persisted.  Natural-language
    text, URLs, base64, prompts, profile material, and model output all become
    the fixed ``execution_failure`` code.
    """

    if isinstance(value, str) and len(value) <= 64 and _ERROR_CODE.fullmatch(value):
        if value in ERROR_CODES:
            return value
    return "execution_failure"


def _actor(value: Any, *, max_length: int = 128) -> str:
    return _text(value, "actor", max_length=max_length)


def _new_event(
    *,
    event_type: str,
    actor: str,
    target_id: str,
    details: dict[str, Any],
    occurred_at: datetime,
) -> AuditEvent:
    # Callers pass metadata-only dictionaries.  This helper is intentionally
    # not generic JSON logging: prompt/profile/model bodies have no route here.
    return AuditEvent(
        event_id="audit-" + uuid4().hex,
        event_type=event_type,
        actor=actor,
        target_type="screening_execution",
        target_id=target_id,
        occurred_at=occurred_at,
        details_json=details,
    )


def _session_factory(value: Any | None) -> sessionmaker[Session]:
    """Turn an engine, sessionmaker, or Session into a fresh-session factory."""

    if value is None:
        from ..db import SessionLocal

        return SessionLocal
    if isinstance(value, Session):
        bind = value.get_bind()
        if isinstance(bind, Connection):
            raise TypeError(
                "connection-bound sessions are unsafe; provide the owning Engine"
            )
        if not isinstance(bind, Engine):
            raise TypeError("session has no bind")
        return sessionmaker(bind=bind, class_=Session, autoflush=False, expire_on_commit=False)
    if isinstance(value, Engine):
        return sessionmaker(bind=value, class_=Session, autoflush=False, expire_on_commit=False)
    if callable(value):
        return value
    raise TypeError("session_factory must be a Session, Engine, or session factory")


class ScreeningQueue:
    """FIFO enqueue/claim/recovery repository.

    ``session_factory`` may be an SQLAlchemy ``sessionmaker`` or an Engine.
    Methods are command boundaries and commit only the fresh session they
    opened.  No process-local lock is used for correctness.
    """

    def __init__(
        self,
        session_factory: Any | None = None,
        *,
        engine: Engine | None = None,
        session: Session | None = None,
        now: Callable[[], datetime] = utc_now,
        clock: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
        busy_retries: int = 6,
        busy_sleep: float = 0.025,
        busy_timeout_ms: int = 500,
    ) -> None:
        supplied = [value for value in (session_factory, engine, session) if value is not None]
        if len(supplied) > 1:
            raise TypeError("provide only one of session_factory, engine, or session")
        self.session_factory = _session_factory(supplied[0] if supplied else None)
        self.now = clock or now
        self.settings = settings or get_settings()
        self.busy_retries = max(0, busy_retries)
        self.busy_sleep = max(0.0, busy_sleep)
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))

    def _session(self, *, busy_timeout_ms: int | None = None) -> Session:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("session factory did not return a SQLAlchemy Session")
        bind = session.get_bind()
        if isinstance(bind, Connection):
            session.close()
            raise TypeError(
                "connection-bound sessions are unsafe; provide the owning Engine"
            )
        if not isinstance(bind, Engine):
            session.close()
            raise TypeError("session has no Engine bind")
        # Command results are returned after this session closes.  Prevent a
        # caller-supplied sessionmaker's default expiration from turning a
        # perfectly valid claimed row into a detached-instance error.
        session.expire_on_commit = False
        if bind.dialect.name == "sqlite":
            # Do not inherit an unbounded driver default.  The command-level
            # retry loop below owns the bounded wait policy.
            session.connection().exec_driver_sql(
                f"PRAGMA busy_timeout = {self.busy_timeout_ms if busy_timeout_ms is None else max(1, int(busy_timeout_ms))}"
            )
        return session

    def _run_command(
        self,
        operation: Callable[[Session], Any],
        *,
        busy_retries: int | None = None,
        busy_timeout_ms: int | None = None,
    ) -> Any:
        """Run a command with bounded retry for SQLite's transient busy state."""

        retries = self.busy_retries if busy_retries is None else max(0, busy_retries)
        for attempt in range(retries + 1):
            session = self._session(busy_timeout_ms=busy_timeout_ms)
            try:
                result = operation(session)
                session.commit()
                return result
            except OperationalError as exc:
                session.rollback()
                message = str(exc).lower()
                is_busy = "database is locked" in message or "database is busy" in message
                if not is_busy or attempt >= retries:
                    if is_busy:
                        raise QueueBusy("database remained busy") from None
                    raise QueueDatabaseError("database operation failed") from None
                time.sleep(self.busy_sleep * (attempt + 1))
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        raise QueueBusy("database remained busy") from None

    @staticmethod
    def _begin_immediate(session: Session) -> None:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def enqueue(
        self,
        *,
        execution_id: str | None = None,
        trigger: str,
        source_run_id: str,
        scope: str,
        requested_by: str,
        policy_version: str,
        prompt_version: str,
        model_name: str,
        model_digest: str,
        company_profile_version: str,
        company_profile_digest: str,
        input_artifact_path: str,
        input_artifact_digest: str,
        artifact_dir: str,
        notice_pk: int | None = None,
        notice_id: str | None = None,
        candidate_count: int = 0,
        queued_at: datetime | None = None,
    ) -> ScreeningExecution:
        """Validate and durably append one queued execution.

        This method performs no model inspection or network request.  Model
        identity is persisted exactly as supplied after strict digest/name
        validation; the Ollama boundary belongs to the worker.
        """

        trigger = _text(trigger, "trigger", max_length=32)
        if trigger not in TRIGGERS:
            raise QueueValidationError("trigger is invalid")
        scope = _text(scope, "scope", max_length=32)
        if scope not in SCOPES:
            raise QueueValidationError("scope is invalid")
        if TRIGGER_SCOPES[trigger] != scope:
            raise QueueValidationError("trigger and scope do not match")
        source_run_id = _text(source_run_id, "source_run_id", max_length=160)
        requested_by = _actor(requested_by, max_length=128)
        policy_version = _text(policy_version, "policy_version")
        prompt_version = _text(prompt_version, "prompt_version")
        model_name = _text(model_name, "model_name")
        if model_name != MODEL_NAME:
            raise QueueValidationError("model_name is not the approved model")
        model_digest = _digest(model_digest, "model_digest")
        company_profile_version = _text(company_profile_version, "company_profile_version", max_length=128)
        company_profile_digest = _digest(company_profile_digest, "company_profile_digest")
        input_artifact_path = safe_relative_path(input_artifact_path, "input_artifact_path")
        input_artifact_digest = _digest(input_artifact_digest, "input_artifact_digest")
        artifact_dir = safe_relative_path(artifact_dir, "artifact_dir")
        if type(candidate_count) is not int or candidate_count < 0:
            raise QueueValidationError("candidate_count must be a nonnegative integer")
        if scope == "single_notice":
            if type(notice_pk) is not int or notice_pk < 1 or not isinstance(notice_id, str) or not notice_id.strip():
                raise QueueValidationError("single_notice requires notice_pk and notice_id")
            notice_id = _text(notice_id, "notice_id", max_length=255)
        elif notice_pk is not None or notice_id is not None:
            raise QueueValidationError("full_run and quality_sample cannot include a notice")
        queued_at = normalize_utc(queued_at, default=self.now)
        if execution_id is not None:
            if not isinstance(execution_id, str) or _EXECUTION_ID.fullmatch(execution_id) is None:
                raise QueueValidationError("execution_id is invalid")

        def command(session: Session) -> ScreeningExecution:
            if session.scalar(select(Run.id).where(Run.id == source_run_id)) is None:
                raise QueueValidationError("source run does not exist")
            policy = session.scalar(select(ScreeningPolicy).where(ScreeningPolicy.policy_version == policy_version))
            if policy is None:
                raise QueueValidationError("policy version does not exist")
            if policy.prompt_version != prompt_version:
                raise QueueValidationError("policy and prompt identities do not match")
            allowed_policy_statuses = {
                "schedule": {"active"},
                "cli_single": {"activation_candidate", "active"},
                "manual_run": {"activation_candidate", "active"},
                "quality_gate": {"activation_candidate", "active"},
            }
            if policy.status not in allowed_policy_statuses[trigger]:
                raise QueueValidationError("policy status is not selectable for this trigger")
            profile = session.scalar(select(CompanyProfileSnapshot).where(CompanyProfileSnapshot.version == company_profile_version))
            if profile is None or profile.digest != company_profile_digest:
                raise QueueValidationError("company profile identity does not match")
            if scope == "single_notice":
                notice = session.scalar(select(Notice).where(Notice.id == notice_pk))
                if notice is None or notice.run_id != source_run_id or notice.notice_key != notice_id:
                    raise QueueValidationError("single notice identity does not match source run")
            execution = ScreeningExecution(
                execution_id=execution_id or ("scr-" + uuid4().hex),
                trigger=trigger,
                source_run_id=source_run_id,
                scope=scope,
                notice_pk=notice_pk,
                notice_id=notice_id,
                status=QUEUED,
                active_slot=None,
                requested_by=requested_by,
                policy_version=policy_version,
                prompt_version=prompt_version,
                model_name=model_name,
                model_digest=model_digest,
                company_profile_version=company_profile_version,
                company_profile_digest=company_profile_digest,
                input_artifact_path=input_artifact_path,
                input_artifact_digest=input_artifact_digest,
                artifact_dir=artifact_dir,
                queued_at=queued_at,
                candidate_count=candidate_count,
                completed_count=0,
                failure_count=0,
            )
            session.add(execution)
            session.flush()
            return execution

        try:
            return self._run_command(command)
        except IntegrityError:
            # Constraints remain the final arbiter.  Convert expected identity
            # races/duplicates into a stable conflict without leaking SQL.
            raise ExecutionConflict("execution identity conflicts with an existing row") from None

    def _recover_stale_locked(self, session: Session, *, now: datetime) -> list[str]:
        stale_seconds = getattr(self.settings, "stale_seconds", None)
        if stale_seconds is None:
            stale_seconds = getattr(self.settings, "screen_stale_after_seconds", 60)
        cutoff = now - timedelta(seconds=stale_seconds)
        stale = list(
            session.scalars(
                select(ScreeningExecution).where(
                    ScreeningExecution.status.in_(ACTIVE),
                    ScreeningExecution.active_slot == 1,
                    ScreeningExecution.heartbeat_at.is_not(None),
                    ScreeningExecution.heartbeat_at < cutoff,
                )
                .order_by(ScreeningExecution.queue_no.asc())
            )
        )
        recovered: list[str] = []
        for row in stale:
            status_before = row.status
            # A conditional update makes a concurrent/manual recovery a safe
            # no-op even if the row was changed after it was selected.
            result = session.execute(
                update(ScreeningExecution)
                .where(
                    ScreeningExecution.execution_id == row.execution_id,
                    ScreeningExecution.status.in_(ACTIVE),
                    ScreeningExecution.active_slot == 1,
                    ScreeningExecution.heartbeat_at < cutoff,
                )
                .execution_options(synchronize_session=False)
                .values(
                    status=INTERRUPTED,
                    active_slot=None,
                    current_notice_id=None,
                    current_stage=None,
                    stop_reason="process_interrupted",
                    finished_at=now,
                )
            )
            if result.rowcount:
                recovered.append(row.execution_id)
                session.add(
                    _new_event(
                        event_type="screening_execution.recovered",
                        actor="system:screening-recovery",
                        target_id=row.execution_id,
                        details={
                            "status_before": status_before,
                            "status_after": INTERRUPTED,
                            "stop_reason": "process_interrupted",
                        },
                        occurred_at=now,
                    )
                )
        return recovered

    def recover_stale(self, *, now: datetime | None = None) -> list[str]:
        """Interrupt strictly stale active rows and return execution IDs."""

        point = normalize_utc(now, default=self.now)

        def command(session: Session) -> list[str]:
            self._begin_immediate(session)
            return self._recover_stale_locked(session, now=point)

        return self._run_command(command)

    def claim(self, *, now: datetime | None = None) -> ScreeningExecution | None:
        """Claim only the oldest queued row while holding SQLite's write lock."""

        point = normalize_utc(now, default=self.now)

        def command(session: Session) -> ScreeningExecution | None:
            self._begin_immediate(session)
            self._recover_stale_locked(session, now=point)
            # A live active row blocks the global worker slot.  Checking this
            # explicitly is important: otherwise a second claimant could
            # select the next FIFO row and only discover the slot through the
            # unique index after attempting to mutate it.
            if session.scalar(
                select(ScreeningExecution.queue_no).where(
                    ScreeningExecution.status.in_(ACTIVE),
                    ScreeningExecution.active_slot == 1,
                )
            ) is not None:
                return None
            row = session.scalar(
                select(ScreeningExecution)
                .where(ScreeningExecution.status == QUEUED, ScreeningExecution.active_slot.is_(None))
                .order_by(ScreeningExecution.queue_no.asc())
                .limit(1)
            )
            if row is None:
                return None
            result = session.execute(
                update(ScreeningExecution)
                .where(
                    ScreeningExecution.execution_id == row.execution_id,
                    ScreeningExecution.status == QUEUED,
                    ScreeningExecution.active_slot.is_(None),
                )
                .values(
                    status=RUNNING,
                    active_slot=1,
                    started_at=point,
                    heartbeat_at=point,
                    current_notice_id=None,
                    current_stage=None,
                )
            )
            if result.rowcount != 1:
                return None
            session.flush()
            return session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == row.execution_id))

        try:
            return self._run_command(command)
        except IntegrityError as exc:
            # The partial unique active-slot index remains the final arbiter
            # for an out-of-band writer.  A concurrent claimant simply loses
            # the race and must not leak an IntegrityError to the worker.
            if "active_slot" in str(exc).lower():
                return None
            raise ExecutionConflict("claim conflicts with durable execution state") from None

    enqueue_execution = enqueue
    claim_next = claim
    acquire = claim
    acquire_next = claim
    recover = recover_stale


# Descriptive aliases make the small repository convenient to discover while
# retaining one implementation and one durable state machine.
QueueRepository = ScreeningQueue
