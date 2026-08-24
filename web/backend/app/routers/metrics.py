"""Validation metric endpoint."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ValidationMetricsResponse
from ..services.metrics import calculate_validation_metrics
from .common import get_run


router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/validation", response_model=ValidationMetricsResponse)
def validation_metrics(
    run_id: str = Query(...),
    session: Session = Depends(get_db),
) -> ValidationMetricsResponse:
    run = get_run(session, run_id)
    return ValidationMetricsResponse(
        run_id=run.id,
        metrics=calculate_validation_metrics(session, run.id),
    )
