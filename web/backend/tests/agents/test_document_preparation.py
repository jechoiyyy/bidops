"""DocumentPreparationAgent command, projection, and lineage contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.agents.common import (
    AgentAction,
    AgentActorRef,
    AgentAggregateRef,
    AgentAggregateType,
    AgentArtifactRef,
    AgentArtifactType,
    AgentName,
    AgentRunStatus,
)
from app.agents.document_preparation import (
    ConfirmReadyCommand,
    ConfirmReadyPayload,
    DocumentPreparationAgent,
    RegisterDocumentCommand,
    StartBundleCommand,
    StartBundlePayload,
    UpdateDocumentMetadataCommand,
    UpdateDocumentMetadataPayload,
    project_document_preparation,
)
from app.core.db import init_db
from app.document_mcp.processor import DocumentProcessor
from app.models import AuditEvent, DocumentBundle, DocumentBundleItem, DocumentVersion, Judgment, Notice, Run
from app.schemas.document_bundles import BundleView, DocumentVersionView
from app.services.document_bundles import BundleServiceError, DocumentBundleService


FIXTURES = Path(__file__).parents[1] / "fixtures" / "document_bundles"


class MemoryUpload:
    def __init__(self, content: bytes, filename: str = "요청서.pdf") -> None:
        self.content = content
        self.offset = 0
        self.filename = filename
        self.content_type = "application/pdf"

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.content)
        chunk = self.content[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    async def close(self) -> None:
        return None


@pytest.fixture
def agent_context(tmp_path: Path) -> tuple[object, DocumentBundleService, int]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    service = DocumentBundleService(
        root=tmp_path / "assets",
        processor=DocumentProcessor(clamav_checker=lambda _data: True),
    )
    with Session(engine) as session:
        run = Run(id=f"agent-{uuid4()}")
        notice = Notice(run=run, notice_key=f"notice-{uuid4()}", title="agent", sample_role="analysis")
        notice.judgment = Judgment(grade="우선 검토", readiness="확인")
        session.add(run)
        session.commit()
        notice_id = notice.id
    return engine, service, notice_id


def actor() -> AgentActorRef:
    return AgentActorRef(actor_kind="human", claimed_name="담당자")


def start_command(notice_id: int) -> StartBundleCommand:
    return StartBundleCommand(
        schema="bidops.agent-command.v1",
        agent_name=AgentName.document_preparation,
        action=AgentAction.start_bundle,
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.notice, aggregate_id=str(notice_id)),
        actor=actor(),
        request_id=None,
        expected_version=None,
        input_refs=[],
        payload=StartBundlePayload(),
    )


def register_command(bundle_id: UUID, request_id: UUID | None = None) -> RegisterDocumentCommand:
    return RegisterDocumentCommand(
        schema="bidops.agent-command.v1",
        agent_name=AgentName.document_preparation,
        action=AgentAction.register_document,
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.document_bundle, aggregate_id=str(bundle_id)),
        actor=actor(),
        request_id=request_id or uuid4(),
        expected_version=None,
        input_refs=[],
        payload={},
    )


def metadata_command(
    document_id: UUID,
    version: int,
    bundle_id: UUID,
    *,
    bundle_version: int | None = None,
) -> UpdateDocumentMetadataCommand:
    return UpdateDocumentMetadataCommand(
        schema="bidops.agent-command.v1",
        agent_name=AgentName.document_preparation,
        action=AgentAction.update_document_metadata,
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.document_version, aggregate_id=str(document_id)),
        actor=actor(),
        request_id=None,
        expected_version=version,
        input_refs=[
            AgentArtifactRef(
                artifact_type=AgentArtifactType.document_bundle,
                artifact_id=str(bundle_id),
                version=bundle_version,
            )
        ],
        payload=UpdateDocumentMetadataPayload(
            role="제안요청서",
            effective_date=None,
            replaces_document_version_id=None,
            is_current=True,
        ),
    )


def confirm_command(bundle_id: UUID, bundle_version: int, document_id: UUID, document_version: int) -> ConfirmReadyCommand:
    return ConfirmReadyCommand(
        schema="bidops.agent-command.v1",
        agent_name=AgentName.document_preparation,
        action=AgentAction.confirm_ready,
        aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.document_bundle, aggregate_id=str(bundle_id)),
        actor=actor(),
        request_id=uuid4(),
        expected_version=bundle_version,
        input_refs=[
            AgentArtifactRef(
                artifact_type=AgentArtifactType.document_version,
                artifact_id=str(document_id),
                version=document_version,
            )
        ],
        payload=ConfirmReadyPayload(
            confirmed_documents=[{"document_version_id": document_id, "version": document_version}]
        ),
    )


def test_action_commands_close_the_four_envelopes() -> None:
    bundle_id = uuid4()
    document_id = uuid4()
    with pytest.raises(ValidationError):
        StartBundleCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action="start_bundle",
            aggregate={"aggregate_type": "notice", "aggregate_id": "1"},
            actor={"actor_kind": "human", "claimed_name": "담당자"},
            request_id=uuid4(),
            payload={},
        )
    with pytest.raises(ValidationError):
        RegisterDocumentCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action="register_document",
            aggregate={"aggregate_type": "document_bundle", "aggregate_id": str(bundle_id)},
            actor={"actor_kind": "human", "claimed_name": "담당자"},
            request_id=uuid4(),
            payload={"upload": "must stay outside command"},
        )
    with pytest.raises(ValidationError):
        UpdateDocumentMetadataCommand(
            schema="bidops.agent-command.v1",
            agent_name="document_preparation",
            action="update_document_metadata",
            aggregate={"aggregate_type": "document_version", "aggregate_id": str(document_id)},
            actor={"actor_kind": "human", "claimed_name": "담당자"},
            expected_version=1,
            input_refs=[],
            payload={"role": "기타", "effective_date": None, "replaces_document_version_id": None, "is_current": True},
        )
    with pytest.raises(ValidationError):
        ConfirmReadyCommand.model_validate(
            {
                **confirm_command(bundle_id, 1, document_id, 1).model_dump(),
                "input_refs": [
                    AgentArtifactRef(
                        artifact_type=AgentArtifactType.document_version,
                        artifact_id=str(uuid4()),
                        version=1,
                    )
                ],
            }
        )


def test_agent_lifecycle_uses_existing_views_and_creation_lineage(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)

    with Session(engine) as session:  # type: ignore[arg-type]
        started = agent.start(session, start_command(notice_id))
        assert isinstance(started.result, BundleView)
        assert started.run.status is AgentRunStatus.waiting_human
        assert started.run.input_refs[0].artifact_type is AgentArtifactType.effective_grade_snapshot
        assert started.run.input_refs[0].sha256 is not None
        bundle_id = started.result.id
        correlation_id = started.run.correlation_id
        assert correlation_id is not None
        creation = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "document_bundle.create",
                AuditEvent.aggregate_id == str(bundle_id),
            )
        )
        assert creation is not None
        assert set(creation.safe_metadata) == {
            "notice_id",
            "revision",
            "effective_grade_at_start",
            "correlation_id",
        }
        assert UUID(str(creation.safe_metadata["correlation_id"])) == correlation_id

        uploaded = asyncio.run(agent.register_document(session, register_command(bundle_id), upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes())))
        assert isinstance(uploaded.result, DocumentVersionView)
        assert uploaded.run.status is AgentRunStatus.waiting_human
        assert AgentAction.update_document_metadata in uploaded.run.available_actions
        document = uploaded.result

        patched = agent.update_document_metadata(
            session,
            metadata_command(document.id, document.version, bundle_id, bundle_version=started.result.version),
        )
        assert isinstance(patched.result, DocumentVersionView)
        assert patched.result.version == document.version + 1
        confirmed = agent.confirm_ready(
            session,
            confirm_command(bundle_id, started.result.version, patched.result.id, patched.result.version),
        )
        assert isinstance(confirmed.result, BundleView)
        assert confirmed.run.status is AgentRunStatus.completed
        assert confirmed.run.outcome_code == "ready_bundle"
        assert [ref.artifact_type for ref in confirmed.run.output_refs] == [
            AgentArtifactType.document_structure,
            AgentArtifactType.document_bundle,
        ]
        assert confirmed.run.output_refs[0].sha256
        assert confirmed.run.output_refs[-1].sha256

        followups = session.scalars(
            select(AuditEvent).where(
                AuditEvent.aggregate_id.in_([str(bundle_id), str(patched.result.id)])
            )
        ).all()
        for audit in followups:
            if audit.action != "document_bundle.create":
                assert audit.safe_metadata.get("correlation_id") == str(correlation_id)


def test_duplicate_upload_and_stale_metadata_preserve_service_fences(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)
    with Session(engine) as session:  # type: ignore[arg-type]
        started = agent.start(session, start_command(notice_id))
        bundle_id = started.result.id
        request_id = uuid4()
        first = asyncio.run(agent.register_document(session, register_command(bundle_id, request_id), upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes(), "same.pdf")))
        replay = asyncio.run(agent.register_document(session, register_command(bundle_id, request_id), upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes(), "same.pdf")))
        assert first.result == replay.result
        document = first.result
        agent.update_document_metadata(session, metadata_command(document.id, document.version, bundle_id, bundle_version=started.result.version))
        with pytest.raises(BundleServiceError) as conflict:
            agent.update_document_metadata(session, metadata_command(document.id, document.version, bundle_id, bundle_version=started.result.version))
        assert conflict.value.code == "version_conflict"


def test_metadata_update_rejects_ref_superseded_by_new_bundle(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)
    with Session(engine) as session:  # type: ignore[arg-type]
        started = agent.start(session, start_command(notice_id))
        document = asyncio.run(
            agent.register_document(
                session,
                register_command(started.result.id),
                upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes(), "stale-ref.pdf"),
            )
        ).result
        stale = metadata_command(
            document.id,
            document.version,
            started.result.id,
            bundle_version=started.result.version,
        )
        successor = agent.start(session, start_command(notice_id))
        assert successor.result.id != started.result.id

        with pytest.raises(BundleServiceError) as conflict:
            agent.update_document_metadata(session, stale)

        assert conflict.value.code == "version_conflict"
        persisted = session.get(DocumentVersion, document.id)
        assert persisted is not None
        assert persisted.version == document.version
        assert persisted.role == document.role


def test_unsafe_document_fails_projection_and_never_exposes_confirm(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)
    with Session(engine) as session:  # type: ignore[arg-type]
        started = agent.start(session, start_command(notice_id))
        uploaded = asyncio.run(
            agent.register_document(
                session,
                register_command(started.result.id),
                upload=MemoryUpload((FIXTURES / "eicar.pdf").read_bytes(), "unsafe.pdf"),
            )
        )
        assert uploaded.run.status is AgentRunStatus.failed
        assert uploaded.run.error is not None
        assert uploaded.run.error.code.value == "unsafe_document"
        assert AgentAction.confirm_ready not in uploaded.run.available_actions


def test_legacy_creation_without_lineage_stays_null(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    with Session(engine) as session:  # type: ignore[arg-type]
        bundle = service.create_bundle(session, notice_id, "담당자")
        document = asyncio.run(service.upload_document(session, bundle.id, MemoryUpload((FIXTURES / "safe.pdf").read_bytes()), "담당자", uuid4()))
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "document.upload", AuditEvent.aggregate_id == str(document.id)))
        assert audit is not None
        assert audit.safe_metadata.get("correlation_id") is None
        projected = DocumentPreparationAgent(service).status(
            session,
            AgentAggregateRef(aggregate_type=AgentAggregateType.document_bundle, aggregate_id=str(bundle.id)),
        )
        assert projected.correlation_id is None


def test_new_ready_attachment_gets_new_run_and_lineage(agent_context: tuple[object, DocumentBundleService, int]) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)
    with Session(engine) as session:  # type: ignore[arg-type]
        first = agent.start(session, start_command(notice_id))
        first_document = asyncio.run(
            agent.register_document(
                session,
                register_command(first.result.id),
                upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes(), "first.pdf"),
            )
        ).result
        first_ready = agent.confirm_ready(
            session,
            confirm_command(first.result.id, first.result.version, first_document.id, first_document.version),
        )
        second = agent.start(session, start_command(notice_id))
        assert second.result.id != first.result.id
        assert second.run.run_id != first_ready.run.run_id
        assert second.run.correlation_id != first_ready.run.correlation_id
        second_document = asyncio.run(
            agent.register_document(
                session,
                register_command(second.result.id),
                upload=MemoryUpload((FIXTURES / "safe.pdf").read_bytes(), "second.pdf"),
            )
        ).result
        ready = agent.confirm_ready(
            session,
            ConfirmReadyCommand(
                schema="bidops.agent-command.v1",
                agent_name=AgentName.document_preparation,
                action=AgentAction.confirm_ready,
                aggregate=AgentAggregateRef(aggregate_type=AgentAggregateType.document_bundle, aggregate_id=str(second.result.id)),
                actor=actor(),
                request_id=uuid4(),
                expected_version=second.result.version,
                input_refs=[
                    AgentArtifactRef(artifact_type=AgentArtifactType.document_version, artifact_id=str(first_document.id), version=first_document.version),
                    AgentArtifactRef(artifact_type=AgentArtifactType.document_version, artifact_id=str(second_document.id), version=second_document.version),
                ],
                payload={
                    "confirmed_documents": [
                        {"document_version_id": first_document.id, "version": first_document.version},
                        {"document_version_id": second_document.id, "version": second_document.version},
                    ]
                },
            ),
        )
        assert ready.result.status == "ready"
        old = session.get(DocumentBundle, first.result.id)
        assert old is not None and old.status == "superseded"
        old_run = agent.status(session, AgentAggregateRef(aggregate_type="document_bundle", aggregate_id=str(old.id)))
        assert old_run.status is AgentRunStatus.superseded
        assert old_run.output_refs
        assert old_run.output_refs[-1].sha256 == first_ready.run.output_refs[-1].sha256


def test_status_projection_is_repeatable_and_write_free(agent_context: tuple[object, DocumentBundleService, int], monkeypatch: pytest.MonkeyPatch) -> None:
    engine, service, notice_id = agent_context
    agent = DocumentPreparationAgent(service)
    with Session(engine) as session:  # type: ignore[arg-type]
        started = agent.start(session, start_command(notice_id))
        count_before = session.scalar(select(__import__("sqlalchemy").func.count(AuditEvent.id)))
        monkeypatch.setattr("app.services.document_bundles._now", lambda: (_ for _ in ()).throw(AssertionError("projection clock")))
        first = agent.status(session, AgentAggregateRef(aggregate_type="document_bundle", aggregate_id=str(started.result.id)))
        second = agent.status(session, AgentAggregateRef(aggregate_type="document_bundle", aggregate_id=str(started.result.id)))
        count_after = session.scalar(select(__import__("sqlalchemy").func.count(AuditEvent.id)))
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert count_before == count_after


def test_projection_uses_persisted_timestamps_only() -> None:
    from datetime import UTC, datetime

    created = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    bundle = {"id": "bundle-1", "notice_id": 1, "version": 3, "status": "draft", "created_at": created, "confirmed_at": None}
    run = project_document_preparation(bundle, documents=[], timestamps=[later])
    assert run.created_at == created
    assert run.updated_at == later
    assert run.status is AgentRunStatus.waiting_human
