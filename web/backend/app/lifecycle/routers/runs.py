"""Run listing, ingest diagnostics, and dashboard summary endpoints."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...core.config import get_settings
from ...core.db import get_db
from ..ingest.loader import discover_run_dirs, ingest_run
from .. import extension_registry
from ..models import IngestWarning, Notice, NoticeObservation, Run
from ..schemas import (
    ArtifactValidationResponse,
    CollectionScopeResponse,
    DeadlineNotice,
    FunnelItem,
    IngestRequest,
    IngestResponse,
    PipelineExecutionResponse,
    PipelineLogResponse,
    PipelineLogLineResponse,
    PipelineRunRequest,
    RunDetailResponse,
    RunListResponse,
    RunStatsResponse,
    PipelineStageResponse,
    WarningListResponse,
    WarningResponse,
)
from ..services.pipeline import (
    PipelineBusyError,
    PipelineInputError,
    PipelineService,
    execution_response,
    log_response,
)
from .common import (
    get_run,
    load_json_file,
    notice_list_item,
    run_directory,
    run_summary,
    warning_counts,
)


router = APIRouter(prefix="/api/runs", tags=["runs"])

pipeline_service = PipelineService()


def _pipeline_service(request: Request) -> PipelineService:
    """Resolve the one pipeline service owned by this application instance.

    The module-level service remains only as a test/import fallback.  Once a
    request has an application state, remember that fallback there as well so
    every run endpoint observes the same in-memory execution registry.
    """

    state = request.app.state
    value = getattr(state, "pipeline_service", None)
    if value is None:
        value = pipeline_service
        state.pipeline_service = value
    return value


def _run_warnings(session: Session, run_id: str) -> list[IngestWarning]:
    return session.scalars(
        select(IngestWarning).where(IngestWarning.run_id == run_id).order_by(IngestWarning.id)
    ).all()


def _warning_response(row: IngestWarning) -> WarningResponse:
    return WarningResponse(
        id=row.id,
        run_id=row.run_id,
        level=row.level,
        code=row.code,
        message=row.message,
        context=row.context_json,
    )


def _artifact_rows(
    run: Run, run_warnings: list[IngestWarning] | None = None
) -> list[ArtifactValidationResponse]:
    directory = run_directory(run)
    expected = {
        "validation-set.json": "bidops.validation-set.v2",
        "screening-results.json": "bidops.screening.v2",
        "screening-decisions.json": "bidops.decisions.v2",
        "collected-notices.json": "bidops.collected.v2",
        "collected-order-plans.json": "bidops.collected-order-plans.v1",
    }
    rows: list[ArtifactValidationResponse] = []
    for name, expected_version in expected.items():
        path = directory / name
        if not path.is_file():
            rows.append(
                ArtifactValidationResponse(
                    name=name,
                    present=False,
                    expected_schema_version=expected_version,
                    valid=None,
                )
            )
            continue
        raw = load_json_file(path)
        actual = raw.get("schema_version") if raw else None
        artifact_warnings: list[str] = []
        valid = actual == expected_version
        if name == "screening-decisions.json" and actual == "bidops.decisions.v1":
            valid = True
            artifact_warnings.append("계약 v1을 호환 적재했습니다. 현재 기준은 v2입니다.")
        elif actual != expected_version:
            artifact_warnings.append(f"예상 스키마 {expected_version}, 실제 스키마 {actual or '없음'}")
        if name == "screening-results.json":
            missing_verification_count = sum(
                warning.code == "verification_items_missing" for warning in (run_warnings or [])
            )
            if missing_verification_count:
                artifact_warnings.append(
                    f"확인 항목(verification_items)이 {missing_verification_count}건에서 누락되었습니다."
                )
        rows.append(
            ArtifactValidationResponse(
                name=name,
                present=True,
                schema_version=actual,
                expected_schema_version=expected_version,
                valid=valid,
                warnings=artifact_warnings,
            )
        )
    return rows


def _scope(run: Run) -> CollectionScopeResponse:
    collection = load_json_file(run_directory(run) / "collected-notices.json") or {}
    raw = load_json_file(run_directory(run) / "validation-set.json") or {}
    selection = raw.get("selection") if isinstance(raw.get("selection"), dict) else {}
    axes = selection.get("analysis_axis_counts")
    pre_spec_count = sum(
        item.get("source_type") == "pre_spec"
        for item in (collection.get("notices") if isinstance(collection.get("notices"), list) else [])
        if isinstance(item, dict)
    )
    return CollectionScopeResponse(
        window_from=run.window_from,
        window_to=run.window_to,
        timezone=run.timezone,
        business_area="용역 본공고",
        pre_spec_available=bool(pre_spec_count),
        pre_spec_reason=(
            None
            if pre_spec_count
            else "사전규격 API 활용신청이 승인되지 않아 이 회차에서는 수집되지 않았습니다."
        ),
        focus_axes=list(axes.keys()) if isinstance(axes, dict) else [],
        performance_reference_count=(
            int(selection["analysis_performance_match_count"])
            if selection.get("analysis_performance_match_count") is not None
            else None
        ),
    )


def _pipeline(
    run: Run,
    artifacts: list[ArtifactValidationResponse],
    service: PipelineService,
) -> list[PipelineStageResponse]:
    present = {row.name: row.present for row in artifacts}
    report_dir = get_settings().bidops_root / "reports" / run_directory(run).name
    definitions = [
        (
            "collect_normalize",
            "complete" if present.get("collected-notices.json") else "not_available",
            "collected-notices.json",
            "collect_notices.py",
            True,
            None,
        ),
        (
            "sample",
            "complete" if present.get("validation-set.json") else "not_available",
            "validation-set.json",
            "select_validation_sample.py",
            True,
            None,
        ),
        (
            "judgment",
            (
                "complete"
                if present.get("screening-results.json") or present.get("screening-decisions.json")
                else "not_available"
            ),
            "screening-results.json",
            "에이전트 작성 · 애플리케이션 실행 없음",
            False,
            "판정은 에이전트가 screening-decisions.json을 직접 작성해야 하므로 여기서 실행하지 않습니다.",
        ),
        (
            "report",
            "complete" if any(report_dir.glob("*.html")) else "not_available",
            "weekly-monitoring.html",
            "render_report.py",
            True,
            None,
        ),
    ]
    rows: list[PipelineStageResponse] = []
    for name, status, artifact, script, execution_allowed, message in definitions:
        stage_key = {"collect_normalize": "collect"}.get(name, name)
        execution = service.latest_for(run.id, stage_key) if execution_allowed else None
        if execution and execution.status in {"pending", "running", "failed"}:
            status = execution.status
        rows.append(
            PipelineStageResponse(
                name=name,
                status=status,
                artifact=artifact,
                script=script,
                execution_id=execution.execution_id if execution else None,
                started_at=execution.started_at if execution else None,
                finished_at=execution.finished_at if execution else None,
                exit_code=execution.exit_code if execution else None,
                execution_allowed=execution_allowed,
                message=message,
            )
        )
    return rows


@router.get("", response_model=RunListResponse)
def list_runs(session: Session = Depends(get_db)) -> RunListResponse:
    runs = session.scalars(select(Run).order_by(Run.generated_at.desc(), Run.id.desc())).all()
    return RunListResponse(items=[run_summary(run) for run in runs], total=len(runs))


@router.post("/ingest", response_model=IngestResponse)
def ingest_selected_run(
    payload: IngestRequest | None = Body(default=None),
    run_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> IngestResponse:
    target = run_id or (payload.run_id if payload else None)
    if not target:
        raise HTTPException(status_code=422, detail="run_id가 필요합니다.")
    settings = get_settings()
    directory_name = target.split("--", 1)[0]
    if Path(directory_name).name != directory_name or directory_name in {"", ".", ".."}:
        raise HTTPException(status_code=404, detail=f"회차 디렉토리를 찾을 수 없습니다: {target}")
    directories = discover_run_dirs(settings.bidops_root / "data", directory_name)
    if not directories:
        raise HTTPException(status_code=404, detail=f"회차 디렉토리를 찾을 수 없습니다: {target}")
    result = ingest_run(directories[0], session, reports_root=settings.bidops_root / "reports")
    warning_rows = _run_warnings(session, result.run_id)
    response_warnings = [_warning_response(row) for row in warning_rows]
    return IngestResponse(
        run_id=result.run_id,
        notices=result.notices,
        order_plans=result.order_plans,
        judgments=result.judgments,
        reviews=result.reviews,
        warnings=response_warnings,
        warning_counts=warning_counts(warning_rows),
    )


@router.post(
    "/{run_id}/pipeline/{stage}",
    response_model=PipelineExecutionResponse,
    status_code=202,
)
def start_pipeline_stage(
    run_id: str,
    stage: str,
    request: Request,
    payload: PipelineRunRequest | None = Body(default=None),
    from_raw: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> PipelineExecutionResponse:
    run = get_run(session, run_id)
    requested_from_raw = from_raw or bool(payload and payload.from_raw)
    try:
        execution = _pipeline_service(request).start(run, stage, from_raw=requested_from_raw)
    except PipelineBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"같은 회차에서 이미 실행 중입니다: {exc.execution_id}",
        ) from exc
    except PipelineInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PipelineExecutionResponse.model_validate(execution_response(execution))


@router.get("/{run_id}/pipeline/logs", response_model=PipelineLogResponse)
def pipeline_logs(
    run_id: str,
    request: Request,
    execution_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> PipelineLogResponse:
    run = get_run(session, run_id)
    executions = _pipeline_service(request).logs_for(run.id, execution_id=execution_id)
    items = [
        PipelineLogLineResponse.model_validate(item)
        for execution in executions
        for item in log_response(execution)
    ]
    return PipelineLogResponse(
        run_id=run.id,
        executions=[PipelineExecutionResponse.model_validate(execution_response(item)) for item in executions],
        items=items,
        total=len(items),
    )


@router.get("/{run_id}/warnings", response_model=WarningListResponse)
def list_run_warnings(
    run_id: str,
    level: str | None = Query(default=None),
    code: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> WarningListResponse:
    run = get_run(session, run_id)
    query = select(IngestWarning).where(IngestWarning.run_id == run.id)
    if level:
        query = query.where(IngestWarning.level == level)
    if code:
        query = query.where(IngestWarning.code == code)
    rows = session.scalars(query.order_by(IngestWarning.id)).all()
    return WarningListResponse(
        run_id=run.id,
        items=[_warning_response(row) for row in rows],
        total=len(rows),
        level=level,
        code=code,
    )


def _optional_count(value: Any) -> int | None:
    """Return a count only when the artifact actually provided one."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.get("/{run_id}/stats", response_model=RunStatsResponse)
def run_stats(run_id: str, session: Session = Depends(get_db)) -> RunStatsResponse:
    run = get_run(session, run_id)
    notices = session.scalars(
        select(Notice)
        .join(NoticeObservation, NoticeObservation.notice_id == Notice.id)
        .where(NoticeObservation.run_id == run.id)
        .options(selectinload(Notice.attachments))
    ).all()
    counts = run.counts_json if isinstance(run.counts_json, dict) else {}
    collection = counts.get("collection") if isinstance(counts.get("collection"), dict) else {}
    # collected-notices.json 은 .gitignore 대상이라 없을 수 있다. 파일이 없어
    # 수집 통계를 모르는 상태와 실제로 0건인 상태는 다르게 읽혀야 하므로,
    # 모르는 경우에는 0으로 채우지 않고 None 으로 남긴다.
    collected = _optional_count(collection.get("total"))
    candidate = _optional_count(collection.get("candidate_pool"))

    # 판정이 채우는 부분은 전부 projection이 회차 단위로 한 번에 돌려준다.
    # 제공자가 없으면 빈 mapping이므로 분포는 빈 목록, 건수는 0이 된다(§6.1).
    projection = extension_registry().judgment_projection
    judgment_stats = projection.run_stats(session, run.id)
    fields = projection.notice_fields(session, [notice.id for notice in notices])
    blocking = judgment_stats.get("blocking_verification_items", {})

    imminent: list[DeadlineNotice] = []
    start = run.generated_at
    end = start + timedelta(days=7)
    for notice in sorted(
        (item for item in notices if item.deadline_at is not None),
        # 마감이 같은 공고의 순서는 이전에 조회 반환 순서에 맡겨져 있어 실행마다
        # 달라질 수 있었다. 목록 endpoint 와 같은 기준(마감 → 식별자)으로 고정한다.
        key=lambda item: (item.deadline_at, item.id),
    ):
        if not (start <= notice.deadline_at <= end):
            continue
        item = notice_list_item(notice, run.id, fields.get(notice.id, {}))
        imminent.append(
            DeadlineNotice(
                **item.model_dump(),
                blocking_verification_items=list(blocking.get(notice.id, [])),
            )
        )

    return RunStatsResponse(
        run_id=run.id,
        timezone=run.timezone,
        generated_at=run.generated_at,
        collected_count=collected,
        candidate_count=candidate,
        sample_count=len(notices),
        priority_review_count=int(judgment_stats.get("priority_review_count", 0)),
        audit_missed_count=int(judgment_stats.get("audit_missed_count", 0)),
        funnel=[
            FunnelItem(key="collected", label="수집", count=collected),
            FunnelItem(key="candidate_pool", label="후보", count=candidate),
            FunnelItem(key="sample", label="표본", count=len(notices)),
            *judgment_stats.get("funnel", []),
        ],
        grade_distribution=list(judgment_stats.get("grade_distribution", [])),
        readiness_distribution=list(judgment_stats.get("readiness_distribution", [])),
        focus_distribution=list(judgment_stats.get("focus_distribution", [])),
        verification_requests=list(judgment_stats.get("verification_requests", [])),
        imminent_deadlines=imminent,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
def run_detail(run_id: str, request: Request, session: Session = Depends(get_db)) -> RunDetailResponse:
    run = get_run(session, run_id)
    warnings = _run_warnings(session, run.id)
    artifacts = _artifact_rows(run, warnings)
    return RunDetailResponse(
        **run_summary(run).model_dump(),
        collection_scope=_scope(run),
        pipeline=_pipeline(run, artifacts, _pipeline_service(request)),
        artifacts=artifacts,
        warning_counts=warning_counts(warnings),
    )
