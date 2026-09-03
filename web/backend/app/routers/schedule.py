"""REST boundary for durable scheduled executions and always-on state."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.db import get_db
from ..screening.models import (
    AlwaysOnState,
    QualityGate,
    QualityGateEvaluation,
    ScheduleExecution,
    ScheduleReservation,
)
from ..schemas import (
    AlwaysOnSwitchResponse,
    AlwaysOnSwitchUpdateRequest,
    ScheduleExecutionCreateRequest,
    ScheduleExecutionListResponse,
    ScheduleExecutionSummary,
    ScheduleExecutionQuery,
    ScheduleSettingsResponse,
    ScheduleSettingsUpdateRequest,
)
from ..services.scheduler import (
    EnvironmentDisabledError,
    ScheduleConflictError,
    ScheduleGateError,
    SchedulerService,
)
from ..core.generation_config import GenerationConfigError, config_from_value, validate_digest


router = APIRouter(prefix="/api/schedule", tags=["schedule"])


def _service(request: Request, session: Session) -> SchedulerService:
    service = getattr(request.app.state, "scheduler_service", None)
    return service if callable(getattr(service, "get_schedule_settings", None)) else SchedulerService(session_factory=session)


def _settings_response(row: Any) -> ScheduleSettingsResponse:
    return ScheduleSettingsResponse.model_validate(row)


def _run_key(window_from: date, window_to: date, job_kind: str) -> str:
    if job_kind == "daily":
        return f"{window_from:%Y%m%d}-{window_to:%Y%m%d}"
    return f"weekly:{window_from:%Y%m%d}-{window_to:%Y%m%d}"


def _generation_binding(
    session: Session,
    row: ScheduleExecution,
    *,
    evaluation: QualityGateEvaluation | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve schedule config from the row or its immutable gate projection."""

    value = getattr(row, "generation_config_json", None)
    digest = row.generation_config_digest
    if value is None and digest is not None:
        gate_query = select(QualityGate).join(
            QualityGateEvaluation, QualityGateEvaluation.gate_id == QualityGate.gate_id
        )
        if evaluation is not None:
            gate_query = gate_query.where(QualityGateEvaluation.evaluation_id == evaluation.evaluation_id)
        else:
            gate_query = gate_query.where(QualityGate.generation_config_digest == digest)
        gate = session.scalars(gate_query.order_by(QualityGate.created_at.desc())).first()
        if gate is not None:
            value = gate.generation_config_json
    if value is None and digest is None:
        return None, None
    try:
        config = config_from_value(value)
        verified = validate_digest(config, digest)
        if value != config.canonical_value():
            raise GenerationConfigError("generation config is not canonical")
    except (GenerationConfigError, TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=500, detail="예약 generation config 상태를 읽을 수 없습니다.") from None
    return config.canonical_value(), verified


def _summary(row: ScheduleExecution, reservation: ScheduleReservation, session: Session | None = None) -> ScheduleExecutionSummary:
    if session is None:
        # Keep direct service-level callers useful while still refusing to
        # manufacture an empty config for a persisted digest.
        value = getattr(row, "generation_config_json", None)
        digest = row.generation_config_digest
        if value is not None and digest is not None:
            try:
                config = config_from_value(value)
                verified = validate_digest(config, digest)
                if value != config.canonical_value():
                    raise GenerationConfigError("generation config is not canonical")
            except (GenerationConfigError, TypeError, ValueError, AttributeError):
                raise HTTPException(status_code=500, detail="예약 generation config 상태를 읽을 수 없습니다.") from None
            generation_config, generation_digest = config.canonical_value(), verified
        elif value is None and digest is None:
            generation_config = generation_digest = None
        else:
            raise HTTPException(status_code=500, detail="예약 generation config 상태를 읽을 수 없습니다.")
    else:
        generation_config, generation_digest = _generation_binding(session, row)
    return ScheduleExecutionSummary.model_validate(
        {
            "run_key": row.run_key,
            "run_id": row.run_id,
            "window_from": reservation.window_from,
            "window_to": reservation.window_to,
            "job_kind": row.job_kind,
            "status": row.status,
            "execution_id": row.execution_id,
            "trigger": row.trigger,
            "duplicate_of_execution_id": row.duplicate_of_execution_id,
            "recovery_of_execution_id": row.recovery_of_execution_id,
            "skip_reason": row.skip_reason,
            "failure_reason": row.failure_reason,
            "requested_by": row.requested_by,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "candidate_count": row.candidate_count,
            "result_count": row.result_count,
            "failure_count": row.failure_count,
            "partial_artifact": row.partial_artifact,
            "policy_version": row.policy_version,
            "model_name": row.model_name,
            "model_digest": row.model_digest,
            "prompt_version": row.prompt_version,
            "company_profile_version": row.company_profile_version,
            "company_profile_digest": row.company_profile_digest,
            "generation_config": generation_config,
            "generation_config_digest": generation_digest,
        }
    )


def _dispatch(request: Request, row: ScheduleExecution) -> None:
    """Hand a reservation to the lifespan-owned executor without waiting."""

    dispatch = getattr(request.app.state, "dispatch_schedule", None)
    if callable(dispatch) and row.status == "예약":
        dispatch(row.execution_id, row.job_kind)


@router.get("/settings", response_model=ScheduleSettingsResponse)
def get_schedule_settings(request: Request, session: Session = Depends(get_db)) -> ScheduleSettingsResponse:
    try:
        return _settings_response(_service(request, session).get_schedule_settings())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="예약 설정을 조회할 수 없습니다.") from exc


@router.patch("/settings", response_model=ScheduleSettingsResponse)
def update_schedule_settings(
    request: Request,
    payload: ScheduleSettingsUpdateRequest,
    session: Session = Depends(get_db),
) -> ScheduleSettingsResponse:
    try:
        row = _service(request, session).update_schedule_settings(
            daily_time=payload.daily_time,
            weekly_time=payload.weekly_time,
            prespec_enabled=payload.prespec_enabled,
            updated_by=payload.updated_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="예약 설정이 올바르지 않습니다.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="예약 설정을 저장할 수 없습니다.") from exc
    return _settings_response(row)


@router.post("/executions", response_model=ScheduleExecutionSummary, status_code=202)
def create_schedule_execution(
    request: Request,
    payload: ScheduleExecutionCreateRequest,
    session: Session = Depends(get_db),
) -> ScheduleExecutionSummary:
    service = _service(request, session)
    try:
        if payload.recovery_of_execution_id is not None:
            target = session.get(ScheduleExecution, payload.recovery_of_execution_id)
            target_reservation = session.get(ScheduleReservation, target.run_key) if target else None
            if (
                target is None
                or target_reservation is None
                or target.job_kind != payload.job_kind
                or target_reservation.window_from != payload.window_from
                or target_reservation.window_to != payload.window_to
            ):
                raise ScheduleConflictError("recovery window does not match the original reservation")
            row = service.recover(payload.recovery_of_execution_id, requested_by=payload.requested_by)
        else:
            row = service.reserve(
                run_key=_run_key(payload.window_from, payload.window_to, payload.job_kind),
                job_kind=payload.job_kind,
                window_from=payload.window_from,
                window_to=payload.window_to,
                trigger="manual",
                requested_by=payload.requested_by,
            )
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=409, detail="예약 실행을 생성할 수 없습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="예약 실행 요청이 올바르지 않습니다.") from exc
    if row is None:
        raise HTTPException(status_code=409, detail="예약 실행을 생성할 수 없습니다.")
    reservation = session.get(ScheduleReservation, row.run_key)
    if reservation is None:
        reservation = ScheduleReservation(
            run_key=row.run_key,
            job_kind=payload.job_kind,
            window_from=payload.window_from,
            window_to=payload.window_to,
            timezone="Asia/Seoul",
        )
    result = _summary(row, reservation, session)
    _dispatch(request, row)
    return result


@router.get("/executions", response_model=ScheduleExecutionListResponse)
def list_schedule_executions(
    request: Request,
    job_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ScheduleExecutionListResponse:
    if job_kind is not None and job_kind not in {"daily", "weekly"}:
        raise HTTPException(status_code=422, detail="job_kind이 올바르지 않습니다.")
    if status is not None and status not in {"예약", "실행 중", "성공", "부분 성공", "실패", "건너뜀"}:
        raise HTTPException(status_code=422, detail="status가 올바르지 않습니다.")
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(status_code=422, detail="날짜 범위가 올바르지 않습니다.")
    filters = []
    if job_kind is not None:
        filters.append(ScheduleExecution.job_kind == job_kind)
    if status is not None:
        filters.append(ScheduleExecution.status == status)
    if from_ is not None:
        filters.append(ScheduleReservation.window_to >= from_)
    if to is not None:
        filters.append(ScheduleReservation.window_from <= to)
    query = select(ScheduleExecution).join(ScheduleReservation, ScheduleExecution.run_key == ScheduleReservation.run_key).where(*filters)
    total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = session.scalars(
        query.order_by(ScheduleReservation.window_from.desc(), ScheduleExecution.execution_id.desc()).offset(offset).limit(limit)
    ).all()
    return ScheduleExecutionListResponse(
        items=[_summary(row, session.get(ScheduleReservation, row.run_key), session) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _always_on_response(request: Request, session: Session, state: AlwaysOnState) -> AlwaysOnSwitchResponse:
    evaluation = session.get(QualityGateEvaluation, state.quality_gate_result_id) if state.quality_gate_result_id else None
    generation_value = getattr(state, "generation_config_json", None)
    generation_digest = state.generation_config_digest
    if generation_value is None and evaluation is not None:
        gate = session.get(QualityGate, evaluation.gate_id)
        if gate is not None:
            generation_value = gate.generation_config_json
            if generation_digest is None:
                generation_digest = gate.generation_config_digest
            elif generation_digest != gate.generation_config_digest:
                raise HTTPException(status_code=500, detail="상시 운영 generation config 바인딩이 손상되었습니다.")
    if generation_value is None and generation_digest is None:
        generation_config = None
    else:
        try:
            config = config_from_value(generation_value)
            generation_digest = validate_digest(config, generation_digest)
            if generation_value != config.canonical_value():
                raise GenerationConfigError("generation config is not canonical")
            generation_config = config.canonical_value()
        except (GenerationConfigError, TypeError, ValueError, AttributeError):
            raise HTTPException(status_code=500, detail="상시 운영 generation config 상태를 읽을 수 없습니다.") from None
    effective = False
    rejection: str | None = None
    service = _service(request, session)
    if state.enabled:
        if not get_settings().scheduler_enabled:
            rejection = "environment_disabled"
        else:
            try:
                effective = bool(service.effective_enabled())
            except Exception:
                rejection = "approval_unavailable"
            if not effective and rejection is None:
                rejection = "approval_metadata_mismatch"
    return AlwaysOnSwitchResponse.model_validate(
        {
            "configured_enabled": bool(state.enabled),
            "effective_enabled": effective,
            "environment_enabled": bool(get_settings().scheduler_enabled),
            "quality_gate_status": evaluation.result_status if evaluation else None,
            "quality_gate_result_id": state.quality_gate_result_id,
            "policy_version": state.policy_version,
            "model_name": state.model_name,
            "model_digest": state.model_digest,
            "prompt_version": state.prompt_version,
            "company_profile_version": state.company_profile_version,
            "company_profile_digest": state.company_profile_digest,
            "generation_config": generation_config,
            "generation_config_digest": generation_digest,
            "updated_at": state.updated_at,
            "updated_by": state.updated_by,
            "rejection_reason": rejection,
        }
    )


@router.get("/always-on", response_model=AlwaysOnSwitchResponse)
def get_always_on(request: Request, session: Session = Depends(get_db)) -> AlwaysOnSwitchResponse:
    try:
        state = _service(request, session).get_always_on()
        return _always_on_response(request, session, state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="상시 운영 상태를 조회할 수 없습니다.") from exc


@router.put("/always-on", response_model=AlwaysOnSwitchResponse)
def put_always_on(
    request: Request,
    payload: AlwaysOnSwitchUpdateRequest,
    session: Session = Depends(get_db),
) -> AlwaysOnSwitchResponse:
    service = _service(request, session)
    try:
        service.set_enabled(
            payload.enabled,
            confirmed_by=payload.confirmed_by,
            quality_gate_result_id=payload.quality_gate_result_id,
        )
    except EnvironmentDisabledError as exc:
        raise HTTPException(status_code=409, detail="스케줄러 환경 설정이 비활성화되어 있습니다.") from exc
    except ScheduleGateError as exc:
        raise HTTPException(status_code=409, detail="운영 품질 게이트가 요청과 일치하지 않습니다.") from exc
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=409, detail="상시 운영 상태가 충돌했습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="상시 운영 요청이 올바르지 않습니다.") from exc
    state = service.get_always_on()
    return _always_on_response(request, session, state)


__all__ = ["router"]
