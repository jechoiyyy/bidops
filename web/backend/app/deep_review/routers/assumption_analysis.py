"""No implicit external transfer: preview and human request are separate mutations."""
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ...core.db import get_db
from ..schemas.assumption_analysis import PreviewRequest, CreateRequest, PreviewView, CreatedView, RunView, ListView
from ..services.assumption_analysis import AssumptionAnalysisService
from ..services.deep_reviews import DeepReviewServiceError
from ..services.input_versions import InputVersionError
from ..services.document_bundles import validate_actor, BundleServiceError

router = APIRouter(prefix='/api', tags=['assumption-analysis'])
service = AssumptionAnalysisService()


def execute(session, operation):
    try:
        return operation()
    except (DeepReviewServiceError, InputVersionError, BundleServiceError) as error:
        session.rollback()
        return JSONResponse(status_code=getattr(error, 'status_code', 409), content={
            'error': {'code': error.code, 'message': error.message}})
    except IntegrityError:
        session.rollback()
        return JSONResponse(status_code=409, content={'error': {'code': 'request_conflict', 'message': '입력 또는 실행이 충돌했습니다'}})
    except Exception:
        session.rollback()
        return JSONResponse(status_code=500, content={'error': {'code': 'processing_failed', 'message': '가정 분석을 처리할 수 없습니다'}})


@router.post('/notices/{notice_id}/assumption-analysis-previews', response_model=PreviewView)
def preview(notice_id: int, payload: PreviewRequest, session: Session = Depends(get_db)):
    return execute(session, lambda: service.preview(session, notice_id, payload.bundle_id))


@router.post('/notices/{notice_id}/assumption-analyses', response_model=CreatedView, status_code=202)
def create(notice_id: int, payload: CreateRequest, session: Session = Depends(get_db),
           actor: str | None = Header(None, alias='X-BidOps-Actor-Name'),
           actor_format: str | None = Header(None, alias='X-BidOps-Actor-Name-Format')):
    return execute(session, lambda: service.create(session, notice_id, payload.preview_id,
                   validate_actor(actor, actor_format), payload.request_id))


@router.get('/notices/{notice_id}/assumption-analyses', response_model=ListView)
def listing(notice_id: int, session: Session = Depends(get_db)):
    return execute(session, lambda: service.listing(session, notice_id))


@router.get('/assumption-analyses/{run_id}', response_model=RunView)
def view(run_id: UUID, session: Session = Depends(get_db)):
    return execute(session, lambda: service.view(session, run_id))
