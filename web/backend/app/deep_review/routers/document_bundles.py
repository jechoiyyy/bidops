"""The seven approved document/bundle endpoints (registration is owned by the deep_review module)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents import (
    AgentAction,
    AgentActorKind,
    AgentActorRef,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    ConfirmReadyCommand,
    ConfirmReadyPayload,
    DocumentPreparationAgent,
    RegisterDocumentCommand,
    RegisterDocumentPayload,
    StartBundleCommand,
    StartBundlePayload,
    UpdateDocumentMetadataCommand,
    UpdateDocumentMetadataPayload,
    bundle_artifact_ref,
)
from ...core.db import get_db
from ..models import DocumentBundle, DocumentBundleItem, DocumentVersion
from ..schemas.document_bundles import (
    BundleListResponse,
    BundleView,
    ConfirmRequest,
    DocumentSegmentsView,
    DocumentStructure,
    DocumentStructurePageView,
    DocumentVersionView,
    EmptyRequest,
    PatchDocumentVersionRequest,
)
from ..services import document_segments
from ..services.document_bundles import BundleServiceError, DocumentBundleService, stable_api_error, validate_actor

router = APIRouter(prefix="/api", tags=["document-bundles"])
service = DocumentBundleService()


def _actor_ref(actor: str | None, actor_format: str | None = None) -> AgentActorRef:
    """Build the strict human actor after preserving the legacy validation."""

    claimed_name = validate_actor(actor, actor_format)
    try:
        return AgentActorRef(
            actor_kind=AgentActorKind.human,
            claimed_name=claimed_name,
        )
    except ValidationError as error:
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400) from error


def _bundle_ref(session: Session, bundle: DocumentBundle) -> AgentArtifactRef:
    """Build the persisted bundle ref used by metadata mutation commands."""

    if bundle.status in {"ready", "superseded"}:
        items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == bundle.id)
            .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
        ).all()
        return bundle_artifact_ref(bundle, items)
    return AgentArtifactRef(
        artifact_type=AgentArtifactType.document_bundle,
        artifact_id=str(bundle.id),
        version=bundle.version,
    )


def _latest_bundle_ref(session: Session, document_id: UUID) -> AgentArtifactRef:
    document = session.get(DocumentVersion, document_id)
    if document is None:
        raise BundleServiceError("not_found", "document version을 찾을 수 없습니다", status_code=404)
    bundle = session.scalar(
        select(DocumentBundle)
        .where(DocumentBundle.notice_id == document.notice_id)
        .order_by(DocumentBundle.revision.desc(), DocumentBundle.id.desc())
        .limit(1)
    )
    if bundle is None:
        raise BundleServiceError("not_found", "document bundle을 찾을 수 없습니다", status_code=404)
    return _bundle_ref(session, bundle)


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
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> BundleView | JSONResponse:
    try:
        command = StartBundleCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action=AgentAction.start_bundle,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.notice,
                aggregate_id=str(notice_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=None,
            correlation_id=None,
            expected_version=None,
            input_refs=[],
            payload=StartBundlePayload(),
        )
        return DocumentPreparationAgent(service).start(session, command).result
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
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> DocumentVersionView | JSONResponse:
    try:
        command = RegisterDocumentCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action=AgentAction.register_document,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.document_bundle,
                aggregate_id=str(bundle_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=request_id,
            correlation_id=None,
            expected_version=None,
            input_refs=[],
            payload=RegisterDocumentPayload(),
        )
        return (await DocumentPreparationAgent(service).register_document(session, command, upload=file)).result
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error, request_id=request_id)


@router.patch("/document-versions/{document_version_id}", response_model=DocumentVersionView)
def patch_document_version(
    document_version_id: UUID,
    payload: PatchDocumentVersionRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> DocumentVersionView | JSONResponse:
    try:
        command = UpdateDocumentMetadataCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action=AgentAction.update_document_metadata,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.document_version,
                aggregate_id=str(document_version_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=None,
            correlation_id=None,
            expected_version=payload.version,
            input_refs=[_latest_bundle_ref(session, document_version_id)],
            payload=UpdateDocumentMetadataPayload(
                role=payload.role,
                effective_date=payload.effective_date,
                replaces_document_version_id=payload.replaces_document_version_id,
                is_current=payload.is_current,
            ),
        )
        return DocumentPreparationAgent(service).update_document_metadata(session, command).result
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)


@router.post("/document-bundles/{bundle_id}/confirm", response_model=BundleView)
def confirm_document_bundle(
    bundle_id: UUID,
    payload: ConfirmRequest,
    actor: Annotated[str | None, Header(alias="X-BidOps-Actor-Name")] = None,
    actor_format: Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")] = None,
    session: Session = Depends(get_db),
) -> BundleView | JSONResponse:
    try:
        document_ids = [item.document_version_id for item in payload.confirmed_documents]
        if len(document_ids) != len(set(document_ids)):
            # The legacy service reports duplicate confirmation IDs as a
            # blocking bundle issue.  The closed command intentionally rejects
            # duplicates, so preserve that API result before constructing it.
            raise BundleServiceError(
                "bundle_has_blocking_issues",
                "확인 문서 ID가 중복되었습니다",
                status_code=409,
                request_id=payload.request_id,
            )
        command = ConfirmReadyCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action=AgentAction.confirm_ready,
            aggregate=AgentAggregateRef(
                aggregate_type=AgentAggregateType.document_bundle,
                aggregate_id=str(bundle_id),
            ),
            actor=_actor_ref(actor, actor_format),
            request_id=payload.request_id,
            correlation_id=None,
            expected_version=payload.version,
            input_refs=[
                AgentArtifactRef(
                    artifact_type=AgentArtifactType.document_version,
                    artifact_id=str(item.document_version_id),
                    version=item.version,
                )
                for item in payload.confirmed_documents
            ],
            payload=ConfirmReadyPayload(
                confirmed_documents=[
                    {
                        "document_version_id": item.document_version_id,
                        "version": item.version,
                    }
                    for item in payload.confirmed_documents
                ]
            ),
        )
        return DocumentPreparationAgent(service).confirm_ready(session, command).result
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


@router.get("/document-structures/{structure_id}/segments", response_model=DocumentSegmentsView)
def get_document_structure_segments(structure_id: UUID, session: Session = Depends(get_db)) -> DocumentSegmentsView | JSONResponse:
    """저장된 결정적 segment manifest를 읽는다 (원문 text 없음)."""

    try:
        return DocumentSegmentsView.model_validate(document_segments.segments_view(session, structure_id))
    except document_segments.SegmentViewError as error:
        return _error_response(BundleServiceError(error.code, error.message, status_code=error.status_code))
    except BundleServiceError as error:
        return _error_response(error)
    except Exception as error:  # pragma: no cover - defensive API boundary
        return _unexpected(error)
