"""대기 업무 건수 조회."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.workload import WorkloadResponse
from ..services.workload import get_workload

router = APIRouter(prefix="/api/workload", tags=["workload"])


@router.get("", response_model=WorkloadResponse)
def workload(session: Session = Depends(get_db)) -> WorkloadResponse:
    return get_workload(session)
