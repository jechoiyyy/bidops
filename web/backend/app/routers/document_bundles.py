"""The seven approved document/bundle endpoints (registration is T7-owned)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.document_bundles import (
    BundleListResponse,
    BundleView,
    ConfirmRequest,
    DocumentStructure,
    DocumentStructurePageView,
    DocumentVersionView,
    EmptyRequest,
    PatchDocumentVersionRequest,
)
from ..services.document_bundles import BundleServiceError, DocumentBundleService, stable_api_error, validate_actor

router = APIRouter(prefix="/api", tags=["document-bundles"])
service = DocumentBundleService()


def _error_response(error: BundleServiceError) -> JSONResponse:
    code, message = stable_api_error(error.code, error.message if error.code in {
        "invalid_request", "actor_name_required", "actor_name_invalid", "not_found",
        "effective_grade_ineligible", "bundle_not_ready", "bundle_has_blocking_issues",
        "unsafe_document", "structure_unavailable", "version_conflict", "idempotency_conflict",
        "service_unavailable", "processing_failed",
    } else None)
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {"code": code, "message": message, "details": None},
            "request_id": str(error.request_id) if error.request_id else None,
        },
    )


def _unexpected(error: Exception, *, request_id: UUID | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "processing_failed", "message": "문서 작업을 완료할 수 없습니다", "details": None},
            "request_id": str(request_id) if request_id else None,
        },
    )


@router.get("/notices/{notice_id}/document-bundles", response_model=BundleListResponse)
def list_document_bundles(notice_id: int, session: Session = Depends(get_db)) -> BundleListResponse | JSONResponse:
    try:
        return service.list_bundles(session, notice_id)
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)


@router.post("/notices/{notice_id}/document-bundles", response_model=BundleView, status_code=201)
def create_document_bundle(
    notice_id: int,
    _payload: EmptyRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> BundleView | JSONResponse:
    try:
        return service.create_bundle(session, notice_id, validate_actor(actor))
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)


@router.post("/document-bundles/{bundle_id}/documents", response_model=DocumentVersionView, status_code=202)
async def upload_document(
    bundle_id: UUID,
    file: UploadFile = File(...),
    request_id: UUID = Form(...),
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> DocumentVersionView | JSONResponse:
    try:
        return await service.upload_document(session, bundle_id, file, validate_actor(actor), request_id)
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error, request_id=request_id)


@router.patch("/document-versions/{document_version_id}", response_model=DocumentVersionView)
def patch_document_version(
    document_version_id: UUID,
    payload: PatchDocumentVersionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> DocumentVersionView | JSONResponse:
    try:
        return service.patch_document(session, document_version_id, payload, validate_actor(actor))
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)


@router.post("/document-bundles/{bundle_id}/confirm", response_model=BundleView)
def confirm_document_bundle(
    bundle_id: UUID,
    payload: ConfirmRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    session: Session = Depends(get_db),
) -> BundleView | JSONResponse:
    try:
        return service.confirm(session, bundle_id, payload, validate_actor(actor))
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error, request_id=payload.request_id)


@router.get("/document-structures/{structure_id}", response_model=DocumentStructure)
def get_document_structure(structure_id: UUID, session: Session = Depends(get_db)) -> DocumentStructure | JSONResponse:
    try:
        return service.get_structure(session, structure_id)
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)


@router.get("/document-structures/{structure_id}/pages/{page}", response_model=DocumentStructurePageView)
def get_document_structure_page(structure_id: UUID, page: str, session: Session = Depends(get_db)) -> DocumentStructurePageView | JSONResponse:
    try:
        try:
            parsed_page = int(page)
        except (TypeError, ValueError):
            raise BundleServiceError("not_found", "document page를 찾을 수 없습니다", status_code=404) from None
        return service.get_structure_page(session, structure_id, parsed_page)
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)
