"""REST presenters and controls for the durable screening queue."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..screening.models import ScreeningAttempt, ScreeningExecution, ScreeningPolicy
from ..schemas import (
    JudgmentExecutionCreateRequest,
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
from ..core.generation_config import GenerationConfigError, config_from_value, validate_digest
from ..screening.ollama import ModelInspectionError
from ..screening.orchestrator import ScreeningCreationError, ScreeningOrchestrator
from ..screening.queue import (
    ExecutionConflict,
    ExecutionNotFound,
    QueueValidationError,
)
# 회차 조회 규칙(사람이 읽는 디렉터리 이름 허용, 없으면 404)은 lifecycle의 것이다.
# 같은 규칙을 다시 구현하지 않고 그 helper를 쓴다(§4의 허용 방향).
from .common import get_run


router = APIRouter(prefix="/api/screening", tags=["screening"])
# 판정 실행은 회차 경로 아래에 있지만 제공 모듈은 screening이다(명세 §5.3).
# 경로와 응답은 그대로 두고 소유 모듈만 옮겼으므로 prefix가 다른 router를 하나 더
# 둔다. 조립 계층이 두 router를 함께 등록한다.
run_router = APIRouter(prefix="/api/runs", tags=["screening"])

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


def _generation_binding_response(row: ScreeningExecution) -> tuple[dict, str]:
    """Validate persisted generation JSON before exposing it over REST."""

    try:
        config = config_from_value(row.generation_config_json)
        digest = validate_digest(config, row.generation_config_digest)
        if row.generation_config_json != config.canonical_value():
            raise GenerationConfigError("generation config is not canonical")
    except (GenerationConfigError, TypeError, ValueError, AttributeError):
        # A malformed persisted binding is a server/data integrity failure;
        # never replace it with an empty object or a caller-supplied default.
        raise HTTPException(status_code=500, detail="스크리닝 generation config 상태를 읽을 수 없습니다.") from None
    return config.canonical_value(), digest


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


def _open_artifact_fd(row: ScreeningExecution, filename: str) -> tuple[int, int] | None:
    """Open an artifact through a no-follow descriptor chain.

    The returned descriptor is the authority used by the response stream;
    callers must not re-open the pathname after this function returns.  This
    closes the usual validate-then-open race where an attacker swaps the
    artifact name for a symlink between a path check and ``FileResponse``.
    """

    expected_dir = f"data/screening-executions/{row.execution_id}"
    if row.artifact_dir != expected_dir:
        return None
    root = Path(get_settings().bidops_root)
    if not root.is_dir() or root.is_symlink():
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    descriptors: list[int] = []
    try:
        root_fd = os.open(root, directory_flags)
        descriptors.append(root_fd)
        data_fd = os.open("data", directory_flags, dir_fd=root_fd)
        descriptors.append(data_fd)
        artifacts_fd = os.open("screening-executions", directory_flags, dir_fd=data_fd)
        descriptors.append(artifacts_fd)
        execution_fd = os.open(row.execution_id, directory_flags, dir_fd=artifacts_fd)
        descriptors.append(execution_fd)
        artifact_fd = os.open(filename, flags, dir_fd=execution_fd)
        descriptors.append(artifact_fd)
        metadata = os.fstat(artifact_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("artifact is not a regular file")
        # ArtifactStore leaves content-addressed files with one link.  A link
        # to an unrelated file (for example /etc/passwd) has nlink >= 2 and
        # is rejected as a hard escape even though its pathname is beneath
        # the execution directory.
        if metadata.st_nlink != 1:
            raise OSError("artifact has an unexpected hard-link count")
        for descriptor in descriptors[:-1]:
            os.close(descriptor)
        return artifact_fd, metadata.st_size
    except (OSError, ValueError):
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        return None


class _ArtifactFdOwner:
    """Own one validated descriptor and close it exactly once.

    The lock is held across ``read`` so cancellation cleanup cannot close and
    allow the integer descriptor to be reused while a worker-thread read is
    still in flight.  Both the iterator and response call ``close``; the
    owner makes that pair idempotent and is the only code that calls
    ``os.close`` for the artifact descriptor.
    """

    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor
        self._lock = threading.Lock()

    def read(self) -> bytes:
        with self._lock:
            if self._descriptor is None:
                return b""
            return os.read(self._descriptor, 1024 * 1024)

    def close(self) -> None:
        with self._lock:
            descriptor = self._descriptor
            self._descriptor = None
            if descriptor is None:
                return
            try:
                os.close(descriptor)
            except OSError:
                pass

    @property
    def descriptor(self) -> int | None:
        with self._lock:
            return self._descriptor


def _stream_fd(owner: _ArtifactFdOwner):  # type: ignore[no-untyped-def]
    try:
        while True:
            chunk = owner.read()
            if not chunk:
                break
            yield chunk
    finally:
        owner.close()


class _ArtifactFdResponse(StreamingResponse):
    """Stream a validated artifact while owning cleanup for the whole call."""

    def __init__(self, owner: _ArtifactFdOwner, size: int, media_type: str) -> None:
        self._owner = owner
        try:
            super().__init__(
                _stream_fd(owner),
                media_type=media_type,
                headers={"Content-Length": str(size)},
            )
        except BaseException:
            owner.close()
            raise

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        try:
            await super().__call__(scope, receive, send)
        finally:
            # This covers normal completion, disconnect/send errors,
            # cancellation, and iterator read errors.  The owner also closes
            # from the iterator's finally, but duplicate close is harmless.
            self._owner.close()


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
    generation_config, generation_digest = _generation_binding_response(row)
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
            "generation_config": generation_config,
            "generation_config_digest": generation_digest,
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
            "generation_config_digest": row.generation_config_digest,
            "num_ctx": row.num_ctx,
            "num_predict": row.num_predict,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "error_summary": row.error_summary,
        }
    )


def _failure_items(row: ScreeningExecution) -> list[ScreeningFailureItem]:
    opened = _open_artifact_fd(row, "screening-failures.json")
    if opened is None:
        return []
    descriptor, _size = opened
    owner = _ArtifactFdOwner(descriptor)
    try:
        raw = b""
        while True:
            chunk = owner.read()
            if not chunk:
                break
            raw += chunk
        value = json.loads(raw.decode("utf-8"))
        failures = value.get("failures") if isinstance(value, dict) else None
        if not isinstance(failures, list):
            return []
        return [ScreeningFailureItem.model_validate(item) for item in failures]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        # A malformed private artifact is not allowed to become an arbitrary
        # response object.  The artifact endpoint remains available for the
        # operator to diagnose it, subject to the same path checks.
        return []
    finally:
        owner.close()


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
) -> StreamingResponse:
    row = session.scalar(
        select(ScreeningExecution).where(ScreeningExecution.execution_id == execution_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="판정 실행을 찾을 수 없습니다.")
    filename, media_type = _ARTIFACTS[kind]
    opened = _open_artifact_fd(row, filename)
    if opened is None:
        raise HTTPException(status_code=404, detail="판정 산출물을 찾을 수 없습니다.")
    descriptor, size = opened
    owner = _ArtifactFdOwner(descriptor)
    try:
        return _ArtifactFdResponse(owner, size, media_type)
    except BaseException:
        owner.close()
        raise


__all__ = ["execution_detail", "execution_response", "router"]


def _screening_orchestrator(request: Request, session: Session) -> ScreeningOrchestrator:
    value = getattr(request.app.state, "screening_orchestrator", None)
    if callable(getattr(value, "create_execution", None)):
        return value
    return ScreeningOrchestrator(session_factory=session)


@run_router.post(
    "/{run_id}/pipeline/judgment",
    response_model=ScreeningExecutionResponse,
    status_code=202,
)
def start_judgment_pipeline(
    run_id: str,
    payload: JudgmentExecutionCreateRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> ScreeningExecutionResponse:
    """Enqueue one immutable full-run judgment and return immediately."""

    run = get_run(session, run_id)
    orchestrator = _screening_orchestrator(request, session)
    try:
        # A fresh tags inspection is deliberately done before any artifact or
        # queue write.  The orchestrator repeats the binding while preparing
        # the frozen input, so a changed model cannot be silently accepted.
        ollama = getattr(orchestrator, "ollama", None)
        if ollama is not None:
            ollama.inspect_model(refresh=True)
        created = orchestrator.create_execution(
            run_id=run.id,
            policy_version=payload.policy_version,
            profile_source=payload.profile_source,
            requested_by=payload.requested_by,
            scope="full_run",
            trigger="manual_run",
        )
    except ModelInspectionError as exc:
        raise HTTPException(status_code=503, detail="모델 사전 확인을 완료할 수 없습니다.") from exc
    except ScreeningCreationError as exc:
        if exc.code in {"precondition_failed", "model_inspection", "ollama_unavailable"}:
            raise HTTPException(status_code=503, detail="모델 사전 확인을 완료할 수 없습니다.") from exc
        if exc.code == "profile_snapshot":
            raise HTTPException(status_code=400, detail="회사 프로필 스냅샷을 준비할 수 없습니다.") from exc
        if exc.code in {"policy_mismatch", "input_error"}:
            # Missing policy/profile and malformed frozen input are reported
            # without exposing filesystem paths or policy/profile contents.
            if exc.code == "policy_mismatch" and session.get(ScreeningPolicy, payload.policy_version) is None:
                raise HTTPException(status_code=404, detail="정책 버전을 찾을 수 없습니다.") from exc
            raise HTTPException(status_code=400, detail="판정 입력을 준비할 수 없습니다.") from exc
        raise HTTPException(status_code=400, detail="판정 실행을 준비할 수 없습니다.") from exc
    except (OSError, ConnectionError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="모델 사전 확인을 완료할 수 없습니다.") from exc
    session.rollback()
    row = session.scalar(
        select(ScreeningExecution).where(ScreeningExecution.execution_id == created.execution_id)
    )
    if row is None:
        raise HTTPException(status_code=500, detail="판정 실행을 읽을 수 없습니다.")
    return execution_response(session, row)
