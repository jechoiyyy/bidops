"""REST presenters and controls for the durable screening queue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import ScreeningAttempt, ScreeningExecution
from ..schemas import (
    ScreeningArtifactUrls,
    ScreeningAttemptResponse,
    ScreeningExecutionDetailResponse,
    ScreeningExecutionListResponse,
    ScreeningExecutionResponse,
    ScreeningFailureItem,
    ScreeningStatus,
    ScreeningStopRequest,
)
from ..screening.execution_store import ScreeningExecutionStore
from ..screening.queue import (
    ExecutionConflict,
    ExecutionNotFound,
    QueueValidationError,
)


router = APIRouter(prefix="/api/screening", tags=["screening"])

_ARTIFACTS: dict[str, tuple[str, str]] = {
    "decisions": ("screening-decisions.json", "application/json"),
    "failures": ("screening-failures.json", "application/json"),
    "telemetry": ("screening-telemetry.jsonl", "application/x-ndjson"),
    "screening_result": ("screening-results.json", "application/json"),
}
_PUBLIC_STAGES = {
    "기술 적합성",
    "실적 정합성",
    "공공 SI 적합성",
    "사업성·자격 제약",
    "전략 부합",
    "counterargument",
    "synthesis",
    "merge",
    "publish",
}


def _artifact_file(row: ScreeningExecution, filename: str) -> Path | None:
    """Resolve one known artifact beneath the row's canonical directory."""

    expected_dir = f"data/screening-executions/{row.execution_id}"
    if row.artifact_dir != expected_dir:
        return None
    root = Path(get_settings().bidops_root).resolve()
    artifact_root = root / "data" / "screening-executions"
    directory = root / expected_dir
    try:
        if (
            any(component.is_symlink() for component in (root / "data", artifact_root))
            or artifact_root.resolve(strict=True) != artifact_root
            or directory.is_symlink()
            or not directory.is_dir()
        ):
            return None
        resolved_root = artifact_root.resolve(strict=True)
        resolved_dir = directory.resolve(strict=True)
        resolved_dir.relative_to(resolved_root)
        candidate = directory / filename
        if candidate.is_symlink() or not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_dir)
        return resolved
    except (OSError, ValueError):
        return None


def _artifact_urls(row: ScreeningExecution) -> ScreeningArtifactUrls:
    links: dict[str, str | None] = {
        key: (
            f"/api/screening/executions/{row.execution_id}/artifacts/{key}"
            if _artifact_file(row, filename) is not None
            else None
        )
        for key, (filename, _media_type) in _ARTIFACTS.items()
    }
    links["published_run"] = (
        f"/api/runs/{row.published_run_id}" if row.published_run_id else None
    )
    return ScreeningArtifactUrls.model_validate(links)


def _queue_position(session: Session, row: ScreeningExecution) -> int | None:
    if row.status != "대기":
        return None
    value = session.scalar(
        select(func.count())
        .select_from(ScreeningExecution)
        .where(
            ScreeningExecution.status == "대기",
            ScreeningExecution.queue_no <= row.queue_no,
        )
    )
    return int(value or 0) or None


def execution_response(
    session: Session,
    row: ScreeningExecution,
) -> ScreeningExecutionResponse:
    current_stage: str | None = row.current_stage
    if current_stage not in _PUBLIC_STAGES:
        current_stage = None
    return ScreeningExecutionResponse.model_validate(
        {
            "queue_no": row.queue_no,
            "execution_id": row.execution_id,
            "trigger": row.trigger,
            "source_run_id": row.source_run_id,
            "scope": row.scope,
            "notice_id": row.notice_id,
            "status": row.status,
            "requested_by": row.requested_by,
            "policy_version": row.policy_version,
            "prompt_version": row.prompt_version,
            "model_name": row.model_name,
            "model_digest": row.model_digest,
            "company_profile_version": row.company_profile_version,
            "company_profile_digest": row.company_profile_digest,
            "input_artifact_digest": row.input_artifact_digest,
            "queued_at": row.queued_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "heartbeat_at": row.heartbeat_at,
            "stop_requested_at": row.stop_requested_at,
            "stop_requested_by": row.stop_requested_by,
            "stop_reason": row.stop_reason,
            "candidate_count": row.candidate_count,
            "completed_count": row.completed_count,
            "failure_count": row.failure_count,
            "published_run_id": row.published_run_id,
            "error_summary": row.error_summary,
            "queue_position": _queue_position(session, row),
            "current_notice_id": row.current_notice_id,
            "current_stage": current_stage,
            "result_urls": _artifact_urls(row),
        }
    )


def _attempt_response(row: ScreeningAttempt) -> ScreeningAttemptResponse:
    return ScreeningAttemptResponse.model_validate(
        {
            "attempt_id": row.attempt_id,
            "execution_id": row.execution_id,
            "notice_id": row.notice_id,
            "stage": row.stage,
            "attempt_no": row.attempt_no,
            "status": row.status,
            "failure_type": row.failure_type,
            "done_reason": row.done_reason,
            "trace_id": row.trace_id,
            "span_id": row.span_id,
            "prompt_eval_count": row.prompt_eval_count,
            "eval_count": row.eval_count,
            "prompt_eval_duration_ns": row.prompt_eval_duration_ns,
            "eval_duration_ns": row.eval_duration_ns,
            "load_duration_ns": row.load_duration_ns,
            "total_duration_ns": row.total_duration_ns,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "error_summary": row.error_summary,
        }
    )


def _failure_items(row: ScreeningExecution) -> list[ScreeningFailureItem]:
    path = _artifact_file(row, "screening-failures.json")
    if path is None:
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        failures = value.get("failures") if isinstance(value, dict) else None
        if not isinstance(failures, list):
            return []
        return [ScreeningFailureItem.model_validate(item) for item in failures]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        # A malformed private artifact is not allowed to become an arbitrary
        # response object.  The artifact endpoint remains available for the
        # operator to diagnose it, subject to the same path checks.
        return []


def execution_detail(
    session: Session,
    row: ScreeningExecution,
) -> ScreeningExecutionDetailResponse:
    attempts = session.scalars(
        select(ScreeningAttempt)
        .where(ScreeningAttempt.execution_id == row.execution_id)
        .order_by(ScreeningAttempt.attempt_id.asc())
    ).all()
    return ScreeningExecutionDetailResponse.model_validate(
        {
            **execution_response(session, row).model_dump(),
            "attempts": [_attempt_response(item) for item in attempts],
            "failures": _failure_items(row),
        }
    )


@router.get("/executions", response_model=ScreeningExecutionListResponse)
def list_executions(
    status: ScreeningStatus | None = Query(default=None),
    trigger: Literal["cli_single", "manual_run", "quality_gate", "schedule"] | None = Query(default=None),
    run_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ScreeningExecutionListResponse:
    filters = []
    if status is not None:
        filters.append(ScreeningExecution.status == status)
    if trigger is not None:
        filters.append(ScreeningExecution.trigger == trigger)
    if run_id is not None:
        filters.append(ScreeningExecution.source_run_id == run_id.strip())
    total = int(session.scalar(select(func.count()).select_from(ScreeningExecution).where(*filters)) or 0)
    rows = session.scalars(
        select(ScreeningExecution)
        .where(*filters)
        .order_by(ScreeningExecution.queue_no.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return ScreeningExecutionListResponse(
        items=[execution_response(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/executions/{execution_id}", response_model=ScreeningExecutionDetailResponse)
def get_execution(
    execution_id: str,
    session: Session = Depends(get_db),
) -> ScreeningExecutionDetailResponse:
    row = session.scalar(
        select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="판정 실행을 찾을 수 없습니다.")
    return execution_detail(session, row)


@router.post("/executions/{execution_id}/stop", response_model=ScreeningExecutionResponse)
def stop_execution(
    execution_id: str,
    request: ScreeningStopRequest,
    session: Session = Depends(get_db),
) -> ScreeningExecutionResponse:
    store = ScreeningExecutionStore(session_factory=session)
    try:
        row = store.request_stop(execution_id, request.requested_by)
    except ExecutionNotFound as exc:
        raise HTTPException(status_code=404, detail="판정 실행을 찾을 수 없습니다.") from exc
    except ExecutionConflict as exc:
        raise HTTPException(status_code=409, detail="종결된 판정 실행은 중지할 수 없습니다.") from exc
    except QueueValidationError as exc:
        raise HTTPException(status_code=422, detail="판정 실행 또는 담당자 입력이 올바르지 않습니다.") from exc
    return execution_response(session, row)


@router.get("/executions/{execution_id}/artifacts/{kind}")
def get_artifact(
    execution_id: str,
    kind: Literal["decisions", "failures", "telemetry", "screening_result"],
    session: Session = Depends(get_db),
) -> FileResponse:
    row = session.scalar(
        select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="판정 실행을 찾을 수 없습니다.")
    filename, media_type = _ARTIFACTS[kind]
    path = _artifact_file(row, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="판정 산출물을 찾을 수 없습니다.")
    return FileResponse(path, media_type=media_type)


__all__ = ["execution_detail", "execution_response", "router"]
