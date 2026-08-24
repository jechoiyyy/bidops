"""Run listing, ingest diagnostics, and dashboard summary endpoints."""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..ingest.loader import discover_run_dirs, ingest_run
from ..models import IngestWarning, Judgment, Notice, Run
from ..schemas import (
    ArtifactValidationResponse,
    CollectionScopeResponse,
    DeadlineNotice,
    DistributionItem,
    FunnelItem,
    IngestRequest,
    IngestResponse,
    RunDetailResponse,
    RunListResponse,
    RunStatsResponse,
    PipelineStageResponse,
    VerificationRequest,
    WarningListResponse,
    WarningResponse,
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

GRADE_ORDER = ["우선 검토", "검토 권장", "관찰 대상", "제외"]
READINESS_ORDER = ["확인 완료", "부분 확인 필요", "참여 불가 확인", "해당 없음"]
FOCUS_ORDER = ["AI/데이터", "블록체인·DID", "공공 SI·통합관리", "해당 없음"]


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


def _artifact_rows(run: Run) -> list[ArtifactValidationResponse]:
    directory = run_directory(run)
    expected = {
        "validation-set.json": "bidops.validation-set.v2",
        "screening-results.json": "bidops.screening.v2",
        "screening-decisions.json": "bidops.decisions.v2",
        "collected-notices.json": "bidops.collected.v2",
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
        warnings: list[str] = []
        valid = actual == expected_version
        if name == "screening-decisions.json" and actual == "bidops.decisions.v1":
            valid = True
            warnings.append("계약 v1을 호환 적재했습니다. 현재 기준은 v2입니다.")
        elif actual != expected_version:
            warnings.append(f"예상 스키마 {expected_version}, 실제 스키마 {actual or '없음'}")
        rows.append(
            ArtifactValidationResponse(
                name=name,
                present=True,
                schema_version=actual,
                expected_schema_version=expected_version,
                valid=valid,
                warnings=warnings,
            )
        )
    return rows


def _scope(run: Run) -> CollectionScopeResponse:
    raw = load_json_file(run_directory(run) / "validation-set.json") or {}
    selection = raw.get("selection") if isinstance(raw.get("selection"), dict) else {}
    axes = selection.get("analysis_axis_counts")
    return CollectionScopeResponse(
        window_from=run.window_from,
        window_to=run.window_to,
        timezone=run.timezone,
        business_area="용역 본공고",
        pre_spec_available=False,
        focus_axes=list(axes.keys()) if isinstance(axes, dict) else [],
        performance_reference_count=(
            int(selection["analysis_performance_match_count"])
            if selection.get("analysis_performance_match_count") is not None
            else None
        ),
    )


def _pipeline(run: Run, artifacts: list[ArtifactValidationResponse]) -> list[PipelineStageResponse]:
    present = {row.name: row.present for row in artifacts}
    report_dir = get_settings().bidops_root / "reports" / run_directory(run).name
    return [
        PipelineStageResponse(
            name="collect_normalize",
            status="complete" if present.get("collected-notices.json") else "not_available",
            artifact="collected-notices.json",
        ),
        PipelineStageResponse(
            name="sample",
            status="complete" if present.get("validation-set.json") else "not_available",
            artifact="validation-set.json",
        ),
        PipelineStageResponse(
            name="judgment",
            status=(
                "complete"
                if present.get("screening-results.json") or present.get("screening-decisions.json")
                else "not_available"
            ),
            artifact="screening-results.json",
        ),
        PipelineStageResponse(
            name="report",
            status="complete" if any(report_dir.glob("*.html")) else "not_available",
            artifact="weekly-monitoring.html",
        ),
    ]


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
        judgments=result.judgments,
        reviews=result.reviews,
        warnings=response_warnings,
        warning_counts=warning_counts(warning_rows),
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


@router.get("/{run_id}/stats", response_model=RunStatsResponse)
def run_stats(run_id: str, session: Session = Depends(get_db)) -> RunStatsResponse:
    run = get_run(session, run_id)
    notices = session.scalars(
        select(Notice)
        .where(Notice.run_id == run.id)
        .options(
            selectinload(Notice.judgment).selectinload(Judgment.verification_items),
            selectinload(Notice.attachments),
        )
    ).all()
    analysis = [notice for notice in notices if notice.sample_role == "analysis"]
    analysis_judgments = [notice.judgment for notice in analysis if notice.judgment is not None]
    counts = run.counts_json if isinstance(run.counts_json, dict) else {}
    collection = counts.get("collection") if isinstance(counts.get("collection"), dict) else {}
    collected = int(collection.get("total") or 0)
    candidate = int(collection.get("candidate_pool") or 0)
    priority = sum(judgment.grade == "우선 검토" for judgment in analysis_judgments)
    audit_missed = sum(
        notice.sample_role == "audit" and notice.judgment is not None and notice.judgment.grade != "제외"
        for notice in notices
    )
    queue_count = sum(
        notice.sample_role == "analysis"
        and notice.judgment is not None
        and notice.judgment.grade != "제외"
        for notice in notices
    )

    def distribution(values: list[str | None], order: list[str]) -> list[DistributionItem]:
        counter = Counter(value or "값 없음" for value in values)
        keys = order + sorted(key for key in counter if key not in order)
        return [DistributionItem(key=key, label=key, count=counter[key]) for key in keys if counter[key]]

    verification: dict[str, dict[str, Any]] = {}
    for notice in notices:
        if notice.sample_role != "analysis" or not notice.judgment:
            continue
        for item in notice.judgment.verification_items:
            if not item.blocking or not item.item:
                continue
            record = verification.setdefault(
                item.item,
                {"count": 0, "notice_pks": [], "profile_sections": []},
            )
            record["count"] += 1
            record["notice_pks"].append(notice.id)
            match = re.search(r"회사 프로필\s+([^ ]+)", item.why or "")
            if match and match.group(1) not in record["profile_sections"]:
                record["profile_sections"].append(match.group(1))

    imminent: list[DeadlineNotice] = []
    start = run.generated_at
    end = start + timedelta(days=7)
    for notice in sorted(
        (item for item in notices if item.deadline_at is not None),
        key=lambda item: item.deadline_at,
    ):
        if not (start <= notice.deadline_at <= end):
            continue
        item = notice_list_item(notice)
        blocking = [
            verification_item.item
            for verification_item in (notice.judgment.verification_items if notice.judgment else [])
            if verification_item.blocking and verification_item.item
        ]
        imminent.append(DeadlineNotice(**item.model_dump(), blocking_verification_items=blocking))

    return RunStatsResponse(
        run_id=run.id,
        timezone=run.timezone,
        collected_count=collected,
        candidate_count=candidate,
        sample_count=len(notices),
        priority_review_count=priority,
        audit_missed_count=audit_missed,
        funnel=[
            FunnelItem(key="collected", label="수집", count=collected),
            FunnelItem(key="candidate_pool", label="후보", count=candidate),
            FunnelItem(key="sample", label="표본", count=len(notices)),
            FunnelItem(key="review_queue", label="검토 대기", count=queue_count),
        ],
        grade_distribution=distribution([judgment.grade for judgment in analysis_judgments], GRADE_ORDER),
        readiness_distribution=distribution([judgment.readiness for judgment in analysis_judgments], READINESS_ORDER),
        focus_distribution=distribution([judgment.primary_focus for judgment in analysis_judgments], FOCUS_ORDER),
        verification_requests=[
            # Sort by volume first so the dashboard can render directly.
            VerificationRequest(
                item=item,
                count=record["count"],
                notice_pks=record["notice_pks"],
                profile_sections=record["profile_sections"],
            )
            for item, record in sorted(verification.items(), key=lambda pair: (-pair[1]["count"], pair[0]))
        ],
        imminent_deadlines=imminent,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
def run_detail(run_id: str, session: Session = Depends(get_db)) -> RunDetailResponse:
    run = get_run(session, run_id)
    warnings = _run_warnings(session, run.id)
    artifacts = _artifact_rows(run)
    return RunDetailResponse(
        **run_summary(run).model_dump(),
        collection_scope=_scope(run),
        pipeline=_pipeline(run, artifacts),
        artifacts=artifacts,
        warning_counts=warning_counts(warnings),
    )
