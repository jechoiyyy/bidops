"""DocumentPreparationAgent adapter over ``DocumentBundleService``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..common import (
    AgentAction,
    AgentActionResult,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactType,
    AgentCommand,
    AgentName,
    AgentRunView,
)
from ...services.document_bundles import (
    BundleServiceError,
    DocumentBundleService,
    document_bundle_snapshot_hash,
)
from ...core.models import AuditEvent
from ...deep_review.models import (
    ContentObject,
    ContentScan,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
)
from ...lifecycle.models import Attachment
from ...schemas.document_bundles import (
    BundleView,
    ConfirmRequest,
    DocumentVersionView,
    PatchDocumentVersionRequest,
)
from .commands import (
    ConfirmReadyCommand,
    DocumentPreparationActionCommand,
    RegisterDocumentCommand,
    StartBundleCommand,
    UpdateDocumentMetadataCommand,
)
from .projection import project_document_preparation


CommandT = TypeVar("CommandT", bound=BaseModel)


class DocumentPreparationAgent:
    """Typed action boundary; domain transitions remain service-owned."""

    name = AgentName.document_preparation

    def __init__(
        self,
        service: DocumentBundleService | None = None,
        *,
        session: Session | None = None,
    ) -> None:
        self.service = service or DocumentBundleService()
        self._session = session

    @staticmethod
    def _invalid(message: str = "document preparation command is invalid", *, request_id: UUID | None = None) -> BundleServiceError:
        return BundleServiceError("invalid_request", message, status_code=400, request_id=request_id)

    @classmethod
    def _command(cls, command: object, command_type: type[CommandT]) -> CommandT:
        try:
            if isinstance(command, command_type):
                return command
            if isinstance(command, BaseModel):
                return command_type.model_validate(command.model_dump())
            return command_type.model_validate(command)
        except ValidationError as exc:
            request_id = getattr(command, "request_id", None)
            raise cls._invalid(request_id=request_id if isinstance(request_id, UUID) else None) from exc

    def _bind(self, session: Session | None, command: object | None) -> tuple[Session, object]:
        if session is None:
            session = self._session
        if session is None or command is None:
            raise self._invalid()
        return session, command

    @staticmethod
    def _notice_id(command: AgentCommand[BaseModel]) -> int:
        try:
            value = int(command.aggregate.aggregate_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise BundleServiceError("invalid_request", "notice aggregate가 올바르지 않습니다", status_code=400) from exc
        if value < 1:
            raise BundleServiceError("invalid_request", "notice aggregate가 올바르지 않습니다", status_code=400)
        return value

    @staticmethod
    def _uuid(value: object, *, request_id: UUID | None = None) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise BundleServiceError("invalid_request", "aggregate ID가 올바르지 않습니다", status_code=400, request_id=request_id) from exc

    @staticmethod
    def _actor(command: AgentCommand[BaseModel]) -> str | None:
        # A system actor has no claimed name and is intentionally rejected by
        # the existing service actor boundary.  The service performs the
        # canonical validation again instead of trusting this adapter.
        return command.actor.claimed_name

    @staticmethod
    def _bundle_sha256(bundle: DocumentBundle, items: list[DocumentBundleItem]) -> str | None:
        return document_bundle_snapshot_hash(bundle, items)

    def _bundle_snapshot(
        self,
        session: Session,
        bundle_id: UUID,
    ) -> tuple[DocumentBundle, BundleView, list[object], list[object], list[datetime | None], AuditEvent | None, UUID | None]:
        bundle = session.scalar(
            select(DocumentBundle)
            .where(DocumentBundle.id == bundle_id)
            .execution_options(populate_existing=True)
        )
        if bundle is None:
            raise BundleServiceError("not_found", "문서 bundle을 찾을 수 없습니다", status_code=404)

        # This is a read-only adapter projection.  The service remains the
        # single owner of the safe live/immutable BundleView semantics.
        view = self.service._bundle_view(session, bundle)
        items = session.scalars(
            select(DocumentBundleItem)
            .where(DocumentBundleItem.bundle_id == bundle.id)
            .order_by(DocumentBundleItem.ordinal.asc(), DocumentBundleItem.document_version_id.asc())
        ).all()

        if bundle.status in {"ready", "superseded"}:
            item_document_rows = {
                row.id: row
                for row in session.scalars(
                    select(DocumentVersion).where(
                        DocumentVersion.id.in_([item.document_version_id for item in items])
                    )
                ).all()
            } if items else {}
            documents: list[object] = [
                {
                    "document_version_id": item.document_version_id,
                    "document_version_version": item.document_version_version,
                    "content_sha256": item.content_sha256,
                    "safety_status": item.safety_status_at_confirmation,
                    "structure_status": "ready" if item.structure_id_at_confirmation and item.structure_payload_sha256 else "failed",
                    "needs_human_review": False,
                    "ordinal": item.ordinal,
                    "created_at": getattr(item_document_rows.get(item.document_version_id), "created_at", None),
                }
                for item in items
            ]
            structures = session.scalars(
                select(DocumentStructure)
                .where(DocumentStructure.id.in_([item.structure_id_at_confirmation for item in items]))
            ).all() if items else []
        else:
            live_documents = session.scalars(
                select(DocumentVersion)
                .join(Attachment, Attachment.id == DocumentVersion.attachment_id)
                .where(
                    DocumentVersion.notice_id == bundle.notice_id,
                    DocumentVersion.is_current.is_(True),
                    Attachment.retired_at.is_(None),
                )
                .order_by(DocumentVersion.created_at.asc(), DocumentVersion.id.asc())
            ).all()
            content_by_id = {
                content.id: content
                for content in session.scalars(
                    select(ContentObject).where(
                        ContentObject.id.in_([document.content_object_id for document in live_documents])
                    )
                ).all()
            } if live_documents else {}
            documents = [
                {
                    "document_version_id": document.id,
                    "version": document.version,
                    "content_object_id": document.content_object_id,
                    "content_sha256": getattr(content_by_id.get(document.content_object_id), "sha256", None),
                    "safety_status": document.safety_status,
                    "needs_human_review": document.needs_human_review,
                    "created_at": document.created_at,
                }
                for document in live_documents
            ]
            structures = session.scalars(
                select(DocumentStructure).where(
                    DocumentStructure.document_version_id.in_([document.id for document in live_documents])
                )
            ).all() if live_documents else []

        creation = self.service._bundle_creation_audit(session, bundle)
        correlation_id = self.service._bundle_correlation_id(session, bundle)
        metadata = creation.safe_metadata if creation is not None and isinstance(creation.safe_metadata, Mapping) else {}
        document_ids = [str(_get_document_id(document)) for document in documents]
        timestamps: list[Any] = [bundle.created_at, bundle.confirmed_at]
        timestamps.extend(document.get("created_at") for document in documents if isinstance(document, Mapping))
        timestamps.extend(structure.created_at for structure in structures)
        timestamps.extend(
            row.created_at
            for row in session.scalars(
                select(AuditEvent).where(
                    or_(
                        (AuditEvent.aggregate_type == "document_bundle") & (AuditEvent.aggregate_id == str(bundle.id)),
                        (AuditEvent.aggregate_type == "document_version") & AuditEvent.aggregate_id.in_(document_ids) if document_ids else False,
                    )
                )
            ).all()
        )
        content_ids = [
            _get_object_id(document)
            for document in documents
            if _get_object_id(document) is not None
        ]
        if content_ids:
            timestamps.extend(
                row.created_at
                for row in session.scalars(select(ContentObject).where(ContentObject.id.in_(content_ids))).all()
            )
            timestamps.extend(
                row.scanned_at
                for row in session.scalars(select(ContentScan).where(ContentScan.content_object_id.in_(content_ids))).all()
            )

        return bundle, view, documents, [*structures, *items], timestamps, creation, correlation_id

    def _project(self, session: Session, bundle_id: UUID) -> AgentRunView:
        bundle, view, documents, structure_and_items, timestamps, creation, correlation_id = self._bundle_snapshot(session, bundle_id)
        structures = [row for row in structure_and_items if isinstance(row, DocumentStructure)]
        items = [row for row in structure_and_items if isinstance(row, DocumentBundleItem)]
        metadata = creation.safe_metadata if creation is not None and isinstance(creation.safe_metadata, Mapping) else {}
        grade = metadata.get("effective_grade_at_start") if "effective_grade_at_start" in metadata else None
        grade = grade if isinstance(grade, str) and grade else None
        bundle_sha256 = self._bundle_sha256(bundle, items)
        return project_document_preparation(
            bundle,
            documents=documents,
            structures=structures,
            issues=view.issues,
            bundle_items=items,
            creation_audit_id=str(creation.id) if creation is not None else None,
            effective_grade_at_start=grade,
            correlation_id=correlation_id,
            bundle_sha256=bundle_sha256,
            persisted_timestamps=timestamps,
        )

    def start(
        self,
        session: Session | StartBundleCommand | None,
        command: StartBundleCommand | None = None,
    ) -> AgentActionResult[BundleView]:
        if command is None and isinstance(session, StartBundleCommand):
            command, session = session, self._session
        current_session, raw_command = self._bind(session if isinstance(session, Session) else None, command)
        typed = self._command(raw_command, StartBundleCommand)
        notice_id = self._notice_id(typed)
        actor = self._actor(typed)
        # start_bundle is the sole allocation point for a new correlation.  It
        # is created before the service call and passed explicitly so the
        # bundle row and its creation audit share one transaction.
        correlation_id = uuid4()
        result = self.service.create_bundle(
            current_session,
            notice_id,
            actor,  # type: ignore[arg-type]
            correlation_id=correlation_id,
        )
        run = self._project(current_session, result.id)
        return AgentActionResult[BundleView](run=run, result=result)

    async def act(
        self,
        session: Session | DocumentPreparationActionCommand | None,
        command: DocumentPreparationActionCommand | None = None,
        *,
        upload: Any = None,
    ) -> AgentActionResult[BundleView | DocumentVersionView]:
        if command is None and isinstance(session, BaseModel):
            command, session = session, self._session
        current_session, raw_command = self._bind(session if isinstance(session, Session) else None, command)
        if not isinstance(raw_command, BaseModel):
            raise self._invalid()
        action = getattr(raw_command, "action", None)
        if action is AgentAction.register_document or action == AgentAction.register_document.value:
            return await self.register_document(current_session, raw_command, upload=upload)
        if action is AgentAction.update_document_metadata or action == AgentAction.update_document_metadata.value:
            return self.update_document_metadata(current_session, raw_command)
        if action is AgentAction.confirm_ready or action == AgentAction.confirm_ready.value:
            return self.confirm_ready(current_session, raw_command)
        raise self._invalid()

    async def register_document(
        self,
        session: Session,
        command: RegisterDocumentCommand | AgentCommand[BaseModel],
        *,
        upload: Any = None,
    ) -> AgentActionResult[BundleView | DocumentVersionView]:
        typed = self._command(command, RegisterDocumentCommand)
        if upload is None:
            raise self._invalid("register_document requires a request-scoped upload capability", request_id=typed.request_id)
        bundle_id = self._uuid(typed.aggregate.aggregate_id, request_id=typed.request_id)
        result = await self.service.upload_document(
            session,
            bundle_id,
            upload,
            self._actor(typed),  # type: ignore[arg-type]
            typed.request_id,
        )
        run = self._project(session, bundle_id)
        return AgentActionResult[BundleView | DocumentVersionView](run=run, result=result)

    def update_document_metadata(
        self,
        session: Session,
        command: UpdateDocumentMetadataCommand | AgentCommand[BaseModel],
    ) -> AgentActionResult[BundleView | DocumentVersionView]:
        typed = self._command(command, UpdateDocumentMetadataCommand)
        document_id = self._uuid(typed.aggregate.aggregate_id)
        ref = typed.input_refs[0]
        if ref.artifact_type is not AgentArtifactType.document_bundle:
            raise self._invalid("최신 document bundle ref가 필요합니다")
        payload = typed.payload
        result = self.service.patch_document(
            session,
            document_id,
            PatchDocumentVersionRequest(
                role=payload.role,
                effective_date=payload.effective_date,
                replaces_document_version_id=payload.replaces_document_version_id,
                is_current=payload.is_current,
                version=typed.expected_version,  # type: ignore[arg-type]
            ),
            self._actor(typed),  # type: ignore[arg-type]
            expected_bundle_id=self._uuid(ref.artifact_id),
            expected_bundle_version=ref.version,
            expected_bundle_sha256=ref.sha256,
        )
        run = self._project(session, result.bundle_id)
        return AgentActionResult[BundleView | DocumentVersionView](run=run, result=result)

    def confirm_ready(
        self,
        session: Session,
        command: ConfirmReadyCommand | AgentCommand[BaseModel],
    ) -> AgentActionResult[BundleView]:
        typed = self._command(command, ConfirmReadyCommand)
        bundle_id = self._uuid(typed.aggregate.aggregate_id, request_id=typed.request_id)
        request = ConfirmRequest(
            request_id=typed.request_id,
            version=typed.expected_version,
            confirmed_documents=[
                {
                    "document_version_id": item.document_version_id,
                    "version": item.version,
                }
                for item in typed.payload.confirmed_documents
            ],
        )
        result = self.service.confirm(session, bundle_id, request, self._actor(typed))  # type: ignore[arg-type]
        run = self._project(session, bundle_id)
        return AgentActionResult[BundleView](run=run, result=result)

    def status(self, session: Session | AgentAggregateRef | None, aggregate: AgentAggregateRef | None = None) -> AgentRunView:
        if aggregate is None and isinstance(session, AgentAggregateRef):
            aggregate, session = session, self._session
        if not isinstance(aggregate, AgentAggregateRef) or not isinstance(session, Session):
            raise self._invalid()
        if aggregate.aggregate_type is not AgentAggregateType.document_bundle:
            raise self._invalid("document preparation status는 document bundle aggregate가 필요합니다")
        bundle_id = self._uuid(aggregate.aggregate_id)
        return self._project(session, bundle_id)


def _get_document_id(document: object) -> object:
    if isinstance(document, Mapping):
        return document.get("document_version_id", document.get("id"))
    return getattr(document, "document_version_id", getattr(document, "id", None))


def _get_object_id(document: object) -> object | None:
    if isinstance(document, Mapping):
        return document.get("content_object_id")
    return getattr(document, "content_object_id", None)


__all__ = ["DocumentPreparationAgent"]
