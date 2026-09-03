"""Quality-gate REST endpoints backed by the immutable gate service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..models import (
    QualityGate,
    QualityGateEvaluation,
    QualityGateReview,
    ScreeningExecution,
)
from ..schemas import (
    QualityGateCreateRequest,
    QualityGateDetailResponse,
    QualityGateEvaluationResponse,
    QualityGateListResponse,
    QualityGateResponse,
    QualityGateReviewResponse,
    QualityGateReviewUpsertRequest,
)
from ..screening.artifacts import ArtifactError, ArtifactStore
from ..core.generation_config import GenerationConfigError, config_from_value, validate_digest
from ..screening.quality_gate import (
    QualityGateConflict,
    QualityGateError,
    QualityGateService,
    QualityGateValidationError,
)
from ..screening.quality_metrics import judgment_digest
from .screening import execution_response


router = APIRouter(prefix="/api/quality-gates", tags=["quality-gates"])


def _generation_binding_response(row: QualityGate) -> tuple[dict, str]:
    try:
        config = config_from_value(row.generation_config_json)
        digest = validate_digest(config, row.generation_config_digest)
        if row.generation_config_json != config.canonical_value():
            raise GenerationConfigError("generation config is not canonical")
    except (GenerationConfigError, TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=500, detail="품질 게이트 generation config 상태를 읽을 수 없습니다.") from None
    return config.canonical_value(), digest


def _evaluation_response(
    row: QualityGateEvaluation,
    *,
    generation_config: dict | None = None,
    generation_digest: str | None = None,
) -> QualityGateEvaluationResponse:
    if generation_config is None:
        generation_config = getattr(row, "generation_config_json", None)
    if generation_digest is None:
        generation_digest = row.generation_config_digest
    if generation_config is None or generation_digest is None:
        raise HTTPException(status_code=500, detail="품질 평가 generation config 상태를 읽을 수 없습니다.")
    return QualityGateEvaluationResponse(
        evaluation_id=row.evaluation_id,
        gate_id=row.gate_id,
        revision=row.revision,
        result_status=row.result_status,
        metrics=row.metrics_json if isinstance(row.metrics_json, dict) else {},
        reasons=row.reasons_json if isinstance(row.reasons_json, list) else [],
        valid_review_count=row.valid_review_count,
        distinct_notice_review_count=row.distinct_notice_review_count,
        generation_config=generation_config,
        generation_config_digest=generation_digest,
        created_at=row.created_at,
    )


def _review_response(row: QualityGateReview) -> QualityGateReviewResponse:
    return QualityGateReviewResponse(
        review_id=row.review_id,
        gate_id=row.gate_id,
        execution_id=row.execution_id,
        notice_id=row.notice_id,
        decision_digest=row.decision_digest,
        reviewer=row.reviewer,
        evidence_judgment=row.evidence_judgment,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _latest(session: Session, gate_id: str) -> QualityGateEvaluation:
    row = session.scalar(
        select(QualityGateEvaluation)
        .where(QualityGateEvaluation.gate_id == gate_id)
        .order_by(QualityGateEvaluation.revision.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=500, detail="품질 게이트 평가 이력이 없습니다.")
    return row


def _gate_response(session: Session, gate: QualityGate) -> QualityGateResponse:
    latest = _latest(session, gate.gate_id)
    generation_config, generation_digest = _generation_binding_response(gate)
    return QualityGateResponse(
        gate_id=gate.gate_id,
        purpose=gate.purpose,
        execution_status=gate.execution_status,
        result_status=gate.result_status,
        baseline_run_id=gate.baseline_run_id,
        sample_artifact_digest=gate.sample_artifact_digest,
        baseline_decisions_digest=gate.baseline_decisions_digest,
        policy_version=gate.policy_version,
        prompt_version=gate.prompt_version,
        model_name=gate.model_name,
        model_digest=gate.model_digest,
        company_profile_version=gate.company_profile_version,
        company_profile_digest=gate.company_profile_digest,
        generation_config=generation_config,
        generation_config_digest=generation_digest,
        pass_a_execution_id=gate.pass_a_execution_id,
        pass_b_execution_id=gate.pass_b_execution_id,
        created_by=gate.created_by,
        created_at=gate.created_at,
        completed_at=gate.completed_at,
        latest_evaluation_id=latest.evaluation_id,
        metrics=gate.metrics_json if isinstance(gate.metrics_json, dict) else {},
        reasons=gate.reasons_json if isinstance(gate.reasons_json, list) else [],
    )


def _maybe_refresh(gate: QualityGate, session: Session) -> None:
    a = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_a_execution_id))
    b = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_b_execution_id))
    if a is None or b is None:
        raise HTTPException(status_code=500, detail="품질 게이트 실행을 찾을 수 없습니다.")
    execution_status = (
        "대기"
        if a.status == b.status == "대기"
        else "중단됨"
        if "중단됨" in {a.status, b.status}
        else "실패"
        if "실패" in {a.status, b.status}
        else "완료"
        if a.status in {"성공", "부분 성공"} and b.status in {"성공", "부분 성공"}
        else "실행 중"
    )
    if execution_status == gate.execution_status:
        return
    try:
        # End the request's read transaction before the service opens its
        # independent lock/refresh transaction; SQLite otherwise may retain a
        # snapshot that predates a worker's terminal transition.
        session.rollback()
        QualityGateService(session_factory=session).refresh(gate.gate_id)
    except QualityGateValidationError as exc:
        raise HTTPException(status_code=404, detail="품질 게이트를 찾을 수 없습니다.") from exc
    except QualityGateError as exc:
        raise HTTPException(status_code=409, detail="품질 게이트 상태를 갱신할 수 없습니다.") from exc
    session.expire_all()


def _detail(session: Session, gate: QualityGate) -> QualityGateDetailResponse:
    _maybe_refresh(gate, session)
    session.refresh(gate)
    pass_a = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_a_execution_id))
    pass_b = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_b_execution_id))
    if pass_a is None or pass_b is None:
        raise HTTPException(status_code=500, detail="품질 게이트 실행을 찾을 수 없습니다.")
    generation_config, generation_digest = _generation_binding_response(gate)
    evaluations = session.scalars(
        select(QualityGateEvaluation)
        .where(QualityGateEvaluation.gate_id == gate.gate_id)
        .order_by(QualityGateEvaluation.revision.asc())
    ).all()
    reviews = session.scalars(
        select(QualityGateReview)
        .where(QualityGateReview.gate_id == gate.gate_id)
        .order_by(QualityGateReview.review_id.asc())
    ).all()
    return QualityGateDetailResponse(
        **_gate_response(session, gate).model_dump(),
        pass_a=execution_response(session, pass_a),
        pass_b=execution_response(session, pass_b),
        evaluations=[
            _evaluation_response(
                item,
                generation_config=generation_config,
                generation_digest=generation_digest,
            )
            for item in evaluations
        ],
        reviews=[_review_response(item) for item in reviews],
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="품질 게이트를 찾을 수 없습니다.")


def _aggregate_execution_status(status_a: str, status_b: str) -> str:
    if status_a == status_b == "대기":
        return "대기"
    if "중단됨" in {status_a, status_b}:
        return "중단됨"
    if "실패" in {status_a, status_b}:
        return "실패"
    if status_a in {"성공", "부분 성공"} and status_b in {"성공", "부분 성공"}:
        return "완료"
    return "실행 중"


def _refresh_stale_gates(session: Session) -> None:
    """Reconcile terminal pass transitions before list filtering/pagination.

    The projection is read once with both pass statuses, stale IDs are
    refreshed through the durable service, and the request transaction is
    explicitly restarted before the caller performs its count/page query.
    This prevents a stale SQLite snapshot from hiding a gate that just became
    terminal.  The service has no bulk operation, so only genuinely stale
    gates incur a refresh transaction; healthy gates are never refreshed per
    response item.
    """

    pass_a = aliased(ScreeningExecution)
    pass_b = aliased(ScreeningExecution)
    rows = session.execute(
        select(
            QualityGate.gate_id,
            QualityGate.execution_status,
            pass_a.status.label("status_a"),
            pass_b.status.label("status_b"),
        )
        .join(pass_a, pass_a.execution_id == QualityGate.pass_a_execution_id)
        .join(pass_b, pass_b.execution_id == QualityGate.pass_b_execution_id)
    ).all()
    stale_ids = [
        gate_id
        for gate_id, projection, status_a, status_b in rows
        if projection != _aggregate_execution_status(status_a, status_b)
    ]
    if not stale_ids:
        return
    # The first projection SELECT may have opened a read transaction.  End it
    # before the service obtains its own write lock, then force another fresh
    # transaction for the count/page query below.
    session.rollback()
    service = QualityGateService(session_factory=session)
    try:
        for gate_id in stale_ids:
            service.refresh(gate_id)
    except QualityGateValidationError as exc:
        raise HTTPException(status_code=409, detail="품질 게이트 상태를 갱신할 수 없습니다.") from exc
    except QualityGateError as exc:
        raise HTTPException(status_code=409, detail="품질 게이트 상태를 갱신할 수 없습니다.") from exc
    session.rollback()
    session.expire_all()


@router.post("", response_model=QualityGateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_quality_gate(
    request: QualityGateCreateRequest,
    session: Session = Depends(get_db),
) -> QualityGateResponse:
    service = QualityGateService(session_factory=session)
    try:
        created = service.create_gate(
            purpose=request.purpose,
            policy_version=request.policy_version,
            profile_source=request.profile_source,
            created_by=request.created_by,
        )
    except QualityGateValidationError as exc:
        message = str(exc)
        if "run or policy is missing" in message or "policy is not selectable" in message:
            raise HTTPException(status_code=404, detail="품질 게이트 회차 또는 정책을 찾을 수 없습니다.") from exc
        raise HTTPException(status_code=422, detail="고정 품질 게이트 입력이 계약에 맞지 않습니다.") from exc
    except QualityGateConflict as exc:
        raise HTTPException(status_code=409, detail="품질 게이트 실행을 생성할 수 없습니다.") from exc
    except Exception as exc:
        # ScreeningCreationError deliberately carries a safe category code;
        # preflight model/tag failures must be surfaced as 503 before a gate
        # or either pass is published.
        if getattr(exc, "code", None) in {"precondition_failed", "model_inspection"}:
            raise HTTPException(status_code=503, detail="모델 사전 확인을 완료할 수 없습니다.") from exc
        raise
    session.expire_all()
    gate = session.get(QualityGate, created.gate_id)
    if gate is None:
        raise HTTPException(status_code=500, detail="품질 게이트 결과를 읽을 수 없습니다.")
    return _gate_response(session, gate)


@router.get("", response_model=QualityGateListResponse)
def list_quality_gates(
    purpose: Literal["model_comparison", "operational_approval"] | None = Query(default=None),
    execution_status: Literal["대기", "실행 중", "완료", "실패", "중단됨"] | None = Query(default=None),
    result_status: Literal["통과", "미달", "미측정", "보류"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> QualityGateListResponse:
    _refresh_stale_gates(session)
    filters = []
    if purpose is not None:
        filters.append(QualityGate.purpose == purpose)
    if execution_status is not None:
        filters.append(QualityGate.execution_status == execution_status)
    if result_status is not None:
        filters.append(QualityGate.result_status == result_status)
    total = int(session.scalar(select(func.count()).select_from(QualityGate).where(*filters)) or 0)
    rows = session.scalars(
        select(QualityGate)
        .where(*filters)
        .order_by(QualityGate.created_at.desc(), QualityGate.gate_id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return QualityGateListResponse(
        items=[_gate_response(session, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{gate_id}", response_model=QualityGateDetailResponse)
def get_quality_gate(
    gate_id: str,
    session: Session = Depends(get_db),
) -> QualityGateDetailResponse:
    gate = session.get(QualityGate, gate_id)
    if gate is None:
        raise _not_found()
    return _detail(session, gate)


def _pass_a_digest(session: Session, gate: QualityGate, notice_id: str) -> str | None:
    execution = session.scalar(select(ScreeningExecution).where(ScreeningExecution.execution_id == gate.pass_a_execution_id))
    if execution is None or execution.status not in {"성공", "부분 성공"}:
        return None
    try:
        value = ArtifactStore(Path(get_settings().bidops_root)).read_json(
            execution.execution_id, "screening-decisions.json"
        )
        judgments = value.get("judgments") if isinstance(value, dict) else None
        if not isinstance(judgments, list):
            return None
        item = next(
            (
                candidate
                for candidate in judgments
                if isinstance(candidate, dict) and candidate.get("notice_id") == notice_id
            ),
            None,
        )
        return judgment_digest(item) if item is not None else None
    except (ArtifactError, TypeError, ValueError, KeyError):
        return None


@router.put("/{gate_id}/reviews/{notice_id}", response_model=QualityGateDetailResponse)
def upsert_quality_gate_review(
    gate_id: str,
    notice_id: str,
    request: QualityGateReviewUpsertRequest,
    session: Session = Depends(get_db),
) -> QualityGateDetailResponse:
    gate = session.get(QualityGate, gate_id)
    if gate is None:
        raise _not_found()
    digest = _pass_a_digest(session, gate, notice_id)
    if digest is None:
        raise HTTPException(status_code=404, detail="품질 게이트의 pass A 공고를 찾을 수 없습니다.")
    service = QualityGateService(session_factory=session)
    try:
        service.upsert_review(
            gate_id,
            notice_id,
            reviewer=request.reviewer,
            evidence_judgment=request.evidence_judgment,
            decision_digest=digest,
            note=request.note,
        )
    except QualityGateValidationError as exc:
        raise HTTPException(status_code=404, detail="품질 게이트의 pass A 공고를 찾을 수 없습니다.") from exc
    except QualityGateConflict as exc:
        raise HTTPException(status_code=409, detail="품질 게이트 리뷰를 갱신할 수 없습니다.") from exc
    session.expire_all()
    refreshed = session.get(QualityGate, gate_id)
    if refreshed is None:
        raise _not_found()
    return _detail(session, refreshed)


__all__ = ["router"]
