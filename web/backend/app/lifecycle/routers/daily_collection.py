"""일일 수집 기준일 상태 조회 (읽기 전용)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ..schemas.daily_collection import DailyCollectionStatusResponse
from ..services.daily_collection import daily_collection_status

router = APIRouter(prefix="/api/daily-collection-status", tags=["runs"])


@router.get("", response_model=DailyCollectionStatusResponse)
def get_daily_collection_status(session: Session = Depends(get_db)) -> DailyCollectionStatusResponse:
    return daily_collection_status(session)
