"""Ordered daily/weekly work for a durable schedule execution.

This module coordinates existing process runners and the screening FIFO.  It
does not implement a model call and never replaces the screening worker with
an implicit direct Ollama path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import time as _time
from typing import Any, Callable, Mapping

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, get_settings
from ..models import AlwaysOnState, CompanyProfileSnapshot, Run, ScheduleExecution, ScheduleReservation, ScreeningPolicy, utc_now
from ..core.generation_config import (
    GenerationConfigError,
    config_from_value,
    generation_config_from_settings,
    validate_digest,
)
from ..screening.orchestrator import ScreeningOrchestrator
from .scheduler import SchedulerService, previous_week_window


class ScheduledPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class StageResult:
    status: str = "success"
    run_id: str | None = None
    screening_execution_id: str | None = None
    candidate_count: int | None = None
    result_count: int | None = None
    failure_count: int | None = None
    failure_reason: str | None = None
    partial_artifact: bool = False
    value: Any = None


@dataclass(frozen=True)
class ScheduledRunResult:
    execution_id: str
    status: str
    failure_reason: str | None
    run_id: str | None
    screening_execution_id: str | None
    candidate_count: int | None
    result_count: int | None
    failure_count: int | None
    partial_artifact: bool | None


def _factory(value: Any | None) -> sessionmaker[Session]:
    if value is None:
        from ..core.db import SessionLocal

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


def _normal(value: Any) -> StageResult:
    if isinstance(value, StageResult):
        return value
    if value is None:
        return StageResult()
    if isinstance(value, bool):
        return StageResult(status="success" if value else "failed", failure_reason=None if value else "stage_failed", value=value)
    if isinstance(value, Mapping):
        status = str(value.get("status", "success"))
        if status in {"성공", "success", "complete", "completed"}:
            status = "success"
        elif status in {"부분 성공", "partial", "partial_success"}:
            status = "partial"
        elif status in {"중단됨", "interrupted", "cancelled", "canceled"}:
            status = "interrupted"
        else:
            status = "failed"
        return StageResult(
            status=status,
            run_id=value.get("run_id") or value.get("result_run_id"),
            screening_execution_id=value.get("screening_execution_id") or value.get("execution_id"),
            candidate_count=value.get("candidate_count"),
            result_count=_first_not_none(value.get("result_count"), value.get("completed_count")),
            failure_count=value.get("failure_count"),
            failure_reason=value.get("failure_reason") or value.get("error") or value.get("error_code"),
            partial_artifact=bool(value.get("partial_artifact", status == "partial")),
            value=value,
        )
    status = getattr(value, "status", "success")
    mapped = _normal({
        "status": status,
        "run_id": getattr(value, "run_id", None) or getattr(value, "result_run_id", None),
        "screening_execution_id": getattr(value, "screening_execution_id", None),
        "candidate_count": getattr(value, "candidate_count", None),
        "result_count": _first_not_none(getattr(value, "result_count", None), getattr(value, "completed_count", None)),
        "failure_count": getattr(value, "failure_count", None),
        "failure_reason": getattr(value, "failure_reason", None) or getattr(value, "error", None),
        "partial_artifact": getattr(value, "partial_artifact", False),
    })
    return StageResult(**{**mapped.__dict__, "value": value})


def _first_not_none(*values: Any) -> Any:
    """Coalesce counts without treating an explicit zero as missing."""

    for value in values:
        if value is not None:
            return value
    return None


def _is_interrupted(result: StageResult) -> bool:
    return result.status == "interrupted" or result.failure_reason in {
        "interrupted",
        "process_interrupted",
        "user_requested",
    }


def _has_partial_progress(result: StageResult) -> bool:
    """Whether a failed stage left an artifact or any counted work."""

    return bool(
        result.partial_artifact
        or any(
            value is not None and value > 0
            for value in (
                result.candidate_count,
                result.result_count,
                result.failure_count,
            )
        )
    )


_MODEL_PRECONDITION_CODES = frozenset({
    "precondition_failed",
    "model_inspection",
    "model_mismatch",
    "ollama_unavailable",
})


def _model_precondition_failed(exc: BaseException) -> bool:
    """Recognize only allow-listed model precondition failures."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attribute in ("code", "failure_type", "error_code"):
            if getattr(current, attribute, None) in _MODEL_PRECONDITION_CODES:
                return True
        current = current.__cause__ or current.__context__
    return False


class ScheduledPipeline:
    """Run one immutable reservation in the prescribed stage order."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: Any | None = None,
        engine: Engine | None = None,
        scheduler: SchedulerService | None = None,
        pipeline: Any | None = None,
        runner: Any | None = None,
        stage_runner: Any | None = None,
        orchestrator: Any | None = None,
        screening_orchestrator: Any | None = None,
        worker: Any | None = None,
        ollama: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if session_factory is not None and engine is not None:
            raise TypeError("provide one of engine or session_factory")
        self.settings = settings or get_settings()
        self.session_factory = _factory(session_factory or engine)
        self.scheduler = scheduler
        self.pipeline = pipeline or runner or stage_runner
        self.orchestrator = orchestrator or screening_orchestrator
        self.worker = worker
        self.ollama = ollama
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _run(self, fn: Callable[[Session], Any]) -> Any:
        for attempt in range(7):
            session = self.session_factory()
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
                    raise
                _time.sleep(0.01 * (attempt + 1))
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        raise ScheduledPipelineError("database remained busy")

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return value.astimezone(timezone.utc)

    def _execution(self, execution_id: str) -> ScheduleExecution:
        row = self._run(lambda s: s.get(ScheduleExecution, execution_id))
        if row is None:
            raise ScheduledPipelineError("schedule execution not found")
        return row

    def _start(self, execution_id: str) -> ScheduleExecution | None:
        def fn(session: Session) -> ScheduleExecution | None:
            claimed_at = self._now()
            claimed = session.execute(
                update(ScheduleExecution)
                .where(
                    ScheduleExecution.execution_id == execution_id,
                    ScheduleExecution.status == "예약",
                )
                .values(status="실행 중", started_at=claimed_at)
            )
            if claimed.rowcount != 1:
                # A loser must not execute any stage.  The caller performs a
                # fresh read and returns the current durable state.
                return None
            row = session.get(ScheduleExecution, execution_id)
            if row is None:  # pragma: no cover - the conditional update claimed it
                raise ScheduledPipelineError("schedule execution not found")
            if row.policy_version is None:
                state = session.get(AlwaysOnState, 1)
                if state is not None:
                    # Foreign-key fields are filled only when the immutable
                    # identity rows are present.  A test/fake runner may use
                    # a reservation without a gate projection; that remains
                    # a safely schedulable row and fails at preflight.
                    if state.policy_version and session.get(ScreeningPolicy, state.policy_version) is not None:
                        row.policy_version = state.policy_version
                    row.model_name = state.model_name
                    row.model_digest = state.model_digest
                    row.prompt_version = state.prompt_version
                    row.generation_config_digest = state.generation_config_digest
                    if hasattr(row, "generation_config_json"):
                        row.generation_config_json = getattr(state, "generation_config_json", None)
                    if state.company_profile_version and session.scalar(select(CompanyProfileSnapshot.version).where(CompanyProfileSnapshot.version == state.company_profile_version)):
                        row.company_profile_version = state.company_profile_version
                    row.company_profile_digest = state.company_profile_digest
            return row

        return self._run(fn)

    def _finish(self, execution_id: str, *, status: str, failure_reason: str | None = None, run_id: str | None = None, screening_execution_id: str | None = None, candidate_count: int | None = None, result_count: int | None = None, failure_count: int | None = None, partial_artifact: bool | None = None) -> ScheduledRunResult:
        def fn(session: Session) -> ScheduleExecution:
            row = session.get(ScheduleExecution, execution_id)
            if row is None:
                raise ScheduledPipelineError("schedule execution not found")
            if row.status in {"성공", "부분 성공", "실패", "건너뜀"}:
                return row
            row.status = status
            row.failure_reason = failure_reason
            if run_id and session.get(Run, run_id) is not None:
                row.run_id = run_id
            if screening_execution_id:
                from ..models import ScreeningExecution

                if session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == screening_execution_id)) is not None:
                    row.screening_execution_id = screening_execution_id
            row.candidate_count = candidate_count if candidate_count is not None else row.candidate_count
            row.result_count = result_count if result_count is not None else row.result_count
            row.failure_count = failure_count if failure_count is not None else row.failure_count
            row.partial_artifact = partial_artifact if partial_artifact is not None else row.partial_artifact
            row.finished_at = self._now()
            return row

        row = self._run(fn)
        return self._result(row)

    @staticmethod
    def _result(row: ScheduleExecution) -> ScheduledRunResult:
        return ScheduledRunResult(row.execution_id, row.status, row.failure_reason, row.run_id, row.screening_execution_id, row.candidate_count, row.result_count, row.failure_count, row.partial_artifact)

    def _stage(self, stage: str, **kwargs: Any) -> StageResult:
        runner = self.pipeline
        if runner is None:
            return StageResult(status="failed", failure_reason=f"{stage}_runner_unavailable")
        candidates = [f"run_{stage}", stage, f"execute_{stage}"]
        if stage == "merge_load":
            candidates += ["merge_and_load", "merge", "load"]
        if stage == "weekly_report":
            candidates += ["run_report", "report"]
        callback = next((getattr(runner, name, None) for name in candidates if callable(getattr(runner, name, None))), None)
        if callback is None and callable(getattr(runner, "run_stage", None)):
            callback = lambda **kw: runner.run_stage(stage, **kw)
        if callback is None:
            return StageResult(status="failed", failure_reason=f"{stage}_runner_unavailable")
        try:
            return _normal(callback(**kwargs))
        except Exception as exc:
            reason = getattr(exc, "failure_reason", None) or getattr(exc, "code", None)
            if isinstance(exc, InterruptedError) or reason in {"interrupted", "process_interrupted", "user_requested"} or "interrupt" in type(exc).__name__.lower():
                return StageResult(status="interrupted", failure_reason="interrupted", value=exc)
            return StageResult(status="failed", failure_reason=f"{stage}_failed", value=exc)

    def _model_identity(self, execution: ScheduleExecution) -> tuple[str, str] | None:
        inspector = self.ollama
        if inspector is None and self.orchestrator is not None:
            inspector = getattr(self.orchestrator, "ollama", None)
        if inspector is None:
            return None
        try:
            identity = inspector.inspect_model(refresh=True)
        except Exception:
            return None
        model_name = getattr(identity, "model_name", None)
        digest = getattr(identity, "digest", None)
        if not model_name and isinstance(identity, Mapping):
            model_name, digest = identity.get("model_name"), identity.get("digest") or identity.get("model_digest")
        if not isinstance(model_name, str) or not isinstance(digest, str):
            return None
        expected_name = execution.model_name
        expected_digest = execution.model_digest
        if not expected_name or not expected_digest:
            return None
        if model_name != expected_name or model_name != self.settings.model_name or digest != expected_digest:
            return None
        return model_name, digest

    def _generation_identity_matches_environment(self, execution: ScheduleExecution) -> bool:
        """Validate the frozen schedule binding before any model inspection."""

        try:
            current = generation_config_from_settings(self.settings)
            expected_digest = getattr(execution, "generation_config_digest", None)
            # Generic manual fixtures may predate this binding. Scheduled
            # rows and explicit recovery rows may not: those paths are the
            # durable always-on boundary and fail closed when absent.
            if expected_digest is None:
                if execution.trigger == "schedule" or execution.recovery_of_execution_id is not None:
                    return False
                return True
            if not isinstance(expected_digest, str) or expected_digest != current.digest():
                return False
            persisted = getattr(execution, "generation_config_json", None)
            if persisted is not None:
                config = config_from_value(persisted)
                validate_digest(config, expected_digest)
                if persisted != config.canonical_value() or config.digest() != current.digest():
                    return False
            return True
        except (GenerationConfigError, TypeError, ValueError):
            return False

    def _judgment(self, execution: ScheduleExecution, *, run_id: str) -> StageResult:
        # Generation config is checked first. This guarantees an environment
        # drift exits without model inspection, queue-row creation, or model
        # work. No legacy digest exception is available for scheduled runs.
        if not self._generation_identity_matches_environment(execution):
            return StageResult(status="failed", failure_reason="generation_config_mismatch")
        # Exact model tag/digest inspection is a precondition to enqueue. No
        # screening row is created when it fails and there is no fallback.
        if self._model_identity(execution) is None:
            return StageResult(status="failed", failure_reason="ollama_unavailable")
        orchestrator = self.orchestrator
        if orchestrator is None:
            result = self._stage("judgment", execution=execution, run_id=run_id)
            if result.status == "success" and result.value is None:
                return StageResult(status="failed", failure_reason="judgment_incomplete")
            return result
        if not execution.policy_version:
            return StageResult(status="failed", failure_reason="policy_unavailable")
        try:
            created = orchestrator.create_execution(
                run_id=run_id,
                policy_version=execution.policy_version,
                profile_source="current",
                requested_by="system:scheduler",
                scope="full_run",
                trigger="schedule",
            )
        except Exception as exc:
            # Model inspection/preflight failure is deliberately represented by
            # a stable safe category, not a model response or endpoint body.
            model_failure = _model_precondition_failed(exc)
            return StageResult(status="failed", failure_reason="ollama_unavailable" if model_failure else "judgment_failed", value=exc)
        screening_id = getattr(created, "execution_id", None) or (created.get("execution_id") if isinstance(created, Mapping) else None)
        if not screening_id:
            return StageResult(status="failed", failure_reason="judgment_failed")
        created_generation_digest = getattr(created, "generation_config_digest", None) or (created.get("generation_config_digest") if isinstance(created, Mapping) else None)
        if created_generation_digest != execution.generation_config_digest:
            return StageResult(status="failed", screening_execution_id=screening_id, failure_reason="generation_config_mismatch")
        if self.worker is not None and callable(getattr(self.worker, "run_until", None)):
            try:
                final = self.worker.run_until(screening_id)
            except Exception:
                return StageResult(status="failed", screening_execution_id=screening_id, failure_reason="judgment_failed")
            if final is None:
                return StageResult(status="failed", screening_execution_id=screening_id, failure_reason="judgment_incomplete")
            result = _normal(final)
            if result.status == "interrupted" or result.failure_reason in {"judgment_interrupted", "process_interrupted", "user_requested"}:
                return StageResult(status="interrupted", screening_execution_id=screening_id, failure_reason="judgment_interrupted", candidate_count=result.candidate_count, result_count=result.result_count, failure_count=result.failure_count, partial_artifact=result.partial_artifact)
            return StageResult(status=result.status, screening_execution_id=screening_id, candidate_count=result.candidate_count, result_count=result.result_count, failure_count=result.failure_count, failure_reason=result.failure_reason, partial_artifact=result.partial_artifact)
        # Enqueueing a FIFO row is not completion.  Without a worker (or an
        # explicit completion handoff) it is unsafe to merge/load as success.
        return StageResult(status="failed", screening_execution_id=screening_id, failure_reason="judgment_incomplete")

    def run_daily(self, execution_id: str) -> ScheduledRunResult:
        started = self._start(execution_id)
        if started is None:
            return self._result(self._execution(execution_id))
        reservation = self._run(lambda s: s.get(ScheduleReservation, started.run_key))
        if reservation is None:
            return self._finish(execution_id, status="실패", failure_reason="reservation_missing")
        common = {"execution": started, "reservation": reservation, "run_key": started.run_key, "window_from": reservation.window_from, "window_to": reservation.window_to}
        collect = self._stage("collect", **common)
        run_id = collect.run_id or started.run_key
        if _is_interrupted(collect):
            return self._finish(execution_id, status="실패", failure_reason="collect_interrupted", run_id=run_id, partial_artifact=collect.partial_artifact)
        if collect.status == "failed":
            return self._finish(execution_id, status="실패", failure_reason="collect_failed", run_id=run_id, partial_artifact=collect.partial_artifact)
        sample = self._stage("sample", **{**common, "run_id": run_id, "collect": collect})
        if _is_interrupted(sample):
            return self._finish(execution_id, status="실패", failure_reason="sample_interrupted", run_id=run_id, partial_artifact=sample.partial_artifact or collect.partial_artifact)
        if sample.status == "failed":
            return self._finish(execution_id, status="실패", failure_reason="sample_failed", run_id=run_id, partial_artifact=sample.partial_artifact or collect.partial_artifact)
        judgment = self._judgment(started, run_id=run_id)
        screening_id = judgment.screening_execution_id
        if judgment.status == "interrupted":
            return self._finish(execution_id, status="실패", failure_reason="judgment_interrupted", run_id=run_id, screening_execution_id=screening_id, candidate_count=judgment.candidate_count, result_count=judgment.result_count, failure_count=judgment.failure_count, partial_artifact=judgment.partial_artifact)
        if judgment.status == "failed":
            partial = _has_partial_progress(judgment)
            return self._finish(execution_id, status="부분 성공" if partial else "실패", failure_reason=judgment.failure_reason or "judgment_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=judgment.candidate_count, result_count=judgment.result_count, failure_count=judgment.failure_count, partial_artifact=judgment.partial_artifact)
        if judgment.status == "success" and (
            judgment.result_count == 0
            or (judgment.candidate_count == 0 and judgment.result_count is None)
        ):
            return self._finish(execution_id, status="실패", failure_reason="judgment_zero_result", run_id=run_id, screening_execution_id=screening_id, candidate_count=judgment.candidate_count, result_count=judgment.result_count, failure_count=judgment.failure_count, partial_artifact=judgment.partial_artifact)
        merge = self._stage("merge_load", **{**common, "run_id": run_id, "judgment": judgment, "screening_execution_id": screening_id})
        if _is_interrupted(merge):
            partial = _has_partial_progress(merge) or _has_partial_progress(judgment)
            return self._finish(execution_id, status="부분 성공" if partial else "실패", failure_reason="merge_load_interrupted", run_id=run_id, screening_execution_id=screening_id, candidate_count=_first_not_none(judgment.candidate_count, merge.candidate_count), result_count=_first_not_none(judgment.result_count, merge.result_count), failure_count=_first_not_none(judgment.failure_count, merge.failure_count), partial_artifact=partial)
        if merge.status == "failed":
            partial = _has_partial_progress(merge) or _has_partial_progress(judgment)
            return self._finish(execution_id, status="부분 성공" if partial else "실패", failure_reason="merge_load_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=_first_not_none(judgment.candidate_count, merge.candidate_count), result_count=_first_not_none(judgment.result_count, merge.result_count), failure_count=_first_not_none(judgment.failure_count, merge.failure_count), partial_artifact=partial)
        report = self._stage("report", **{**common, "run_id": run_id, "judgment": judgment, "merge": merge, "mode": "daily"})
        if _is_interrupted(report):
            return self._finish(execution_id, status="부분 성공", failure_reason="report_interrupted", run_id=run_id, screening_execution_id=screening_id, candidate_count=_first_not_none(judgment.candidate_count, merge.candidate_count), result_count=_first_not_none(judgment.result_count, merge.result_count), failure_count=_first_not_none(judgment.failure_count, merge.failure_count), partial_artifact=True)
        if report.status == "failed":
            return self._finish(execution_id, status="부분 성공", failure_reason="report_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=_first_not_none(judgment.candidate_count, merge.candidate_count), result_count=_first_not_none(judgment.result_count, merge.result_count), failure_count=_first_not_none(judgment.failure_count, merge.failure_count), partial_artifact=True)
        partial = bool(collect.partial_artifact or sample.partial_artifact or judgment.partial_artifact or merge.partial_artifact or report.partial_artifact or collect.status == "partial" or sample.status == "partial" or judgment.status == "partial" or merge.status == "partial" or report.status == "partial")
        return self._finish(execution_id, status="부분 성공" if partial else "성공", run_id=run_id, screening_execution_id=screening_id, candidate_count=_first_not_none(judgment.candidate_count, merge.candidate_count, sample.candidate_count, collect.candidate_count), result_count=_first_not_none(judgment.result_count, merge.result_count), failure_count=_first_not_none(judgment.failure_count, merge.failure_count), partial_artifact=partial)

    execute_daily = run_daily

    def run_weekly(self, execution_id: str) -> ScheduledRunResult:
        started = self._start(execution_id)
        if started is None:
            return self._result(self._execution(execution_id))
        reservation = self._run(lambda s: s.get(ScheduleReservation, started.run_key))
        if reservation is None:
            return self._finish(execution_id, status="실패", failure_reason="reservation_missing")
        completed_daily = self._latest_completed_daily(reservation)
        report = self._stage("weekly_report", execution=started, reservation=reservation, daily_executions=completed_daily, mode="weekly")
        if _is_interrupted(report):
            partial = bool(completed_daily or report.partial_artifact)
            return self._finish(
                execution_id,
                status="부분 성공" if partial else "실패",
                failure_reason="weekly_report_interrupted",
                result_count=report.result_count,
                failure_count=report.failure_count,
                partial_artifact=partial,
            )
        if report.status == "failed":
            partial = bool(completed_daily or report.partial_artifact)
            return self._finish(
                execution_id,
                status="부분 성공" if partial else "실패",
                failure_reason="weekly_report_failed",
                result_count=report.result_count,
                failure_count=report.failure_count,
                partial_artifact=partial,
            )
        partial = bool(report.partial_artifact or report.status == "partial" or len(completed_daily) < 7)
        return self._finish(execution_id, status="부분 성공" if partial else "성공", result_count=report.result_count, failure_count=report.failure_count, partial_artifact=partial)

    def _latest_completed_daily(self, weekly: ScheduleReservation) -> list[ScheduleExecution]:
        """Select one valid completed daily execution per calendar date.

        A recovery is a new execution for the same reservation.  Grouping by
        ``window_from`` prevents the original partial result and its recovery
        from being counted twice.  Failed/skip attempts are not valid weekly
        inputs and therefore do not hide an earlier valid result for that
        date.
        """

        def fn(session: Session) -> list[ScheduleExecution]:
            rows = list(
                session.scalars(
                    select(ScheduleExecution)
                    .join(ScheduleReservation, ScheduleExecution.run_key == ScheduleReservation.run_key)
                    .where(
                        ScheduleReservation.job_kind == "daily",
                        ScheduleReservation.window_from >= weekly.window_from,
                        ScheduleReservation.window_to <= weekly.window_to,
                    )
                )
            )
            by_run_key = {row.execution_id: row for row in rows}
            by_day: dict[date, list[ScheduleExecution]] = {}
            for row in rows:
                reservation = session.get(ScheduleReservation, row.run_key)
                if reservation is None:
                    continue
                by_day.setdefault(reservation.window_from, []).append(row)

            def depth(row: ScheduleExecution) -> int:
                value = 0
                seen: set[str] = set()
                current = row
                while current.recovery_of_execution_id and current.recovery_of_execution_id not in seen:
                    seen.add(current.recovery_of_execution_id)
                    value += 1
                    parent = by_run_key.get(current.recovery_of_execution_id)
                    if parent is None:
                        break
                    current = parent
                return value

            selected: dict[date, ScheduleExecution] = {}
            for day, candidates in by_day.items():
                valid = [row for row in candidates if row.status in {"성공", "부분 성공"}]
                if valid:
                    selected[day] = max(
                        valid,
                        key=lambda row: (
                            depth(row),
                            row.finished_at or datetime.min.replace(tzinfo=timezone.utc),
                            row.execution_id,
                        ),
                    )
            return [selected[day] for day in sorted(selected)]

        return self._run(fn)

    execute_weekly = run_weekly


ScheduledPipelineService = ScheduledPipeline
__all__ = ["ScheduledPipeline", "ScheduledPipelineError", "ScheduledPipelineService", "ScheduledRunResult", "StageResult"]
