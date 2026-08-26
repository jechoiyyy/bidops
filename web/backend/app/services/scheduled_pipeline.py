"""Ordered daily/weekly work for a durable schedule execution.

This module coordinates existing process runners and the screening FIFO.  It
does not implement a model call and never replaces the screening worker with
an implicit direct Ollama path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, get_settings
from ..models import AlwaysOnState, CompanyProfileSnapshot, Run, ScheduleExecution, ScheduleReservation, ScreeningPolicy, utc_now
from ..screening.orchestrator import ScreeningCreationError, ScreeningOrchestrator
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


def _normal(value: Any) -> StageResult:
    if isinstance(value, StageResult):
        return value
    if value is None:
        return StageResult()
    if isinstance(value, bool):
        return StageResult(status="success" if value else "failed", failure_reason=None if value else "stage_failed")
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
            result_count=value.get("result_count") or value.get("completed_count"),
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
        "result_count": getattr(value, "result_count", None) or getattr(value, "completed_count", None),
        "failure_count": getattr(value, "failure_count", None),
        "failure_reason": getattr(value, "failure_reason", None) or getattr(value, "error", None),
        "partial_artifact": getattr(value, "partial_artifact", False),
    })
    return StageResult(**{**mapped.__dict__, "value": value})


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
        session = self.session_factory()
        try:
            result = fn(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

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
            row = session.get(ScheduleExecution, execution_id)
            if row is None:
                raise ScheduledPipelineError("schedule execution not found")
            if row.status != "예약":
                return None
            row.status = "실행 중"
            row.started_at = self._now()
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

                if session.get(ScreeningExecution, screening_execution_id) is not None:
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
            return StageResult(status="failed", failure_reason=f"{stage}_failed", value=exc)

    def _model_identity(self, execution: ScheduleExecution) -> tuple[str, str] | None:
        inspector = self.ollama
        if inspector is None and self.orchestrator is not None:
            inspector = getattr(self.orchestrator, "ollama", None)
        if inspector is None:
            return None
        try:
            identity = inspector.inspect_model()
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
        if model_name != expected_name or digest != expected_digest:
            return None
        return model_name, digest

    def _judgment(self, execution: ScheduleExecution, *, run_id: str) -> StageResult:
        # Exact model tag/digest inspection is a precondition to enqueue.  No
        # screening row is created when it fails and there is no fallback.
        if self._model_identity(execution) is None:
            return StageResult(status="failed", failure_reason="ollama_unavailable")
        orchestrator = self.orchestrator
        if orchestrator is None:
            result = self._stage("judgment", execution=execution, run_id=run_id)
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
            return StageResult(status="failed", failure_reason="ollama_unavailable" if "model" in type(exc).__name__.lower() else "judgment_failed", value=exc)
        screening_id = getattr(created, "execution_id", None) or (created.get("execution_id") if isinstance(created, Mapping) else None)
        if not screening_id:
            return StageResult(status="failed", failure_reason="judgment_failed")
        if self.worker is not None and callable(getattr(self.worker, "run_until", None)):
            try:
                final = self.worker.run_until(screening_id)
            except Exception:
                return StageResult(status="failed", screening_execution_id=screening_id, failure_reason="judgment_failed")
            result = _normal(final)
            if result.status == "interrupted" or result.failure_reason in {"judgment_interrupted", "process_interrupted", "user_requested"}:
                return StageResult(status="interrupted", screening_execution_id=screening_id, failure_reason="judgment_interrupted", candidate_count=result.candidate_count, result_count=result.result_count, failure_count=result.failure_count)
            return StageResult(status=result.status, screening_execution_id=screening_id, candidate_count=result.candidate_count, result_count=result.result_count, failure_count=result.failure_count, failure_reason=result.failure_reason, partial_artifact=result.partial_artifact)
        return StageResult(status="success", screening_execution_id=screening_id)

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
        if collect.status == "failed":
            return self._finish(execution_id, status="실패", failure_reason="collect_failed", run_id=run_id, partial_artifact=collect.partial_artifact)
        sample = self._stage("sample", **{**common, "run_id": run_id, "collect": collect})
        if sample.status == "failed":
            return self._finish(execution_id, status="실패", failure_reason="sample_failed", run_id=run_id, partial_artifact=sample.partial_artifact or collect.partial_artifact)
        judgment = self._judgment(started, run_id=run_id)
        screening_id = judgment.screening_execution_id
        if judgment.status == "interrupted":
            return self._finish(execution_id, status="실패", failure_reason="judgment_interrupted", run_id=run_id, screening_execution_id=screening_id, candidate_count=judgment.candidate_count, result_count=judgment.result_count, failure_count=judgment.failure_count)
        if judgment.status == "failed":
            return self._finish(execution_id, status="실패", failure_reason=judgment.failure_reason or "judgment_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=judgment.candidate_count, result_count=judgment.result_count, failure_count=judgment.failure_count)
        merge = self._stage("merge_load", **{**common, "run_id": run_id, "judgment": judgment, "screening_execution_id": screening_id})
        if merge.status == "failed":
            partial = bool(merge.partial_artifact or (merge.result_count or 0) > 0)
            return self._finish(execution_id, status="부분 성공" if partial else "실패", failure_reason="merge_load_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=merge.candidate_count or judgment.candidate_count, result_count=merge.result_count or judgment.result_count, failure_count=merge.failure_count, partial_artifact=partial)
        report = self._stage("report", **{**common, "run_id": run_id, "judgment": judgment, "merge": merge, "mode": "daily"})
        if report.status == "failed":
            return self._finish(execution_id, status="부분 성공", failure_reason="report_failed", run_id=run_id, screening_execution_id=screening_id, candidate_count=merge.candidate_count or judgment.candidate_count, result_count=merge.result_count or judgment.result_count, failure_count=merge.failure_count or judgment.failure_count, partial_artifact=True)
        partial = bool(collect.partial_artifact or sample.partial_artifact or judgment.partial_artifact or merge.partial_artifact or report.partial_artifact or collect.status == "partial" or sample.status == "partial" or judgment.status == "partial" or merge.status == "partial" or report.status == "partial")
        return self._finish(execution_id, status="부분 성공" if partial else "성공", run_id=run_id, screening_execution_id=screening_id, candidate_count=merge.candidate_count or judgment.candidate_count or sample.candidate_count or collect.candidate_count, result_count=merge.result_count or judgment.result_count, failure_count=merge.failure_count or judgment.failure_count, partial_artifact=partial)

    execute_daily = run_daily

    def run_weekly(self, execution_id: str) -> ScheduledRunResult:
        started = self._start(execution_id)
        if started is None:
            return self._result(self._execution(execution_id))
        reservation = self._run(lambda s: s.get(ScheduleReservation, started.run_key))
        if reservation is None:
            return self._finish(execution_id, status="실패", failure_reason="reservation_missing")
        completed_daily = self._run(lambda s: list(s.scalars(select(ScheduleExecution).join(ScheduleReservation, ScheduleExecution.run_key == ScheduleReservation.run_key).where(ScheduleReservation.job_kind == "daily", ScheduleReservation.window_from >= reservation.window_from, ScheduleReservation.window_to <= reservation.window_to, ScheduleExecution.status.in_(["성공", "부분 성공"])).order_by(ScheduleReservation.window_from.asc()))))
        report = self._stage("weekly_report", execution=started, reservation=reservation, daily_executions=completed_daily, mode="weekly")
        if report.status == "failed":
            return self._finish(execution_id, status="부분 성공" if completed_daily else "실패", failure_reason="weekly_report_failed", partial_artifact=bool(completed_daily and report.partial_artifact))
        partial = bool(report.partial_artifact or report.status == "partial" or len(completed_daily) < 7)
        return self._finish(execution_id, status="부분 성공" if partial else "성공", result_count=report.result_count, failure_count=report.failure_count, partial_artifact=partial)

    execute_weekly = run_weekly


ScheduledPipelineService = ScheduledPipeline
__all__ = ["ScheduledPipeline", "ScheduledPipelineError", "ScheduledPipelineService", "ScheduledRunResult", "StageResult"]
