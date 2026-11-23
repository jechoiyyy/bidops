from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.config import get_settings
from ...core.db import get_db
from ..schemas import company_wiki_ingests as dto
from ..services import company_wiki_ingests as service


def error(status, code):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": "실적 넣기 요청을 처리할 수 없습니다", "details": None}})


class IngestRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            if not get_settings().company_wiki_ingest_enabled:
                return error(404, "company_wiki_ingest_disabled")
            try:
                return await handler(request)
            except RequestValidationError:
                return error(422, "invalid_request")
            except HTTPException as exc:
                return error(exc.status_code, "invalid_request")
            except BundleServiceError as exc:
                return error(exc.status_code, exc.code)
            except service.WikiError as exc:
                return error(exc.status, exc.code)
            except Exception:
                return error(503, "ingest_unavailable")
        return handle


router = APIRouter(prefix="/api/company-wiki/ingests", tags=["company-wiki"], route_class=IngestRoute)


def actor(name: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
          fmt: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None):
    return validate_actor(name, fmt)


@router.post("", response_model=dto.IngestDetail, status_code=202)
def create(project_id: Annotated[str, Form()], file: Annotated[UploadFile, File()],
           request_id: Annotated[UUID, Header(alias="Idempotency-Key")],
           name=Depends(actor), session=Depends(get_db)):
    return service.create(session, project_id, file, request_id, name)


@router.get("", response_model=dto.IngestList)
def list_runs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), session=Depends(get_db)):
    return service.list_runs(session, limit, offset)


@router.get("/{run_id}", response_model=dto.IngestDetail)
def get(run_id: UUID, session=Depends(get_db)):
    return service.detail(service.get_run(session, run_id))


@router.post("/{run_id}/approve", response_model=dto.IngestDetail)
def approve(run_id: UUID, payload: dto.Approval, name=Depends(actor), session=Depends(get_db)):
    return service.decide(session, run_id, payload, name, approve=True)


@router.post("/{run_id}/reject", response_model=dto.IngestDetail)
def reject(run_id: UUID, payload: dto.Rejection, name=Depends(actor), session=Depends(get_db)):
    return service.decide(session, run_id, payload, name, approve=False)
