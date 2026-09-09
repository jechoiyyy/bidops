"""Focused cohort activation/observation/ops contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuditEvent
from app.deep_review.models import ContentObject, DocumentVersion, PrespecV4Attempt
from app.deep_review.services.prespec_v4_ops import (
    ACTIVATION_SCHEMA,
    V4OpsError,
    _observation_candidate,
    activate_v4,
    active_v4_activation,
    deactivate_v4,
    require_v4_enqueue_enabled,
    prepare_v4_notice,
)
from app.deep_review.services.prespec_v4_runner import V4AttemptError, V4ModelBinding, enqueue_v4_attempt, load_v4_policy
from app.lifecycle.models import Attachment, Notice, NoticeObservation, Run

from .test_prespec_v4_preparation import _Converter, _SOURCE_FONT, _SOURCE_RENDERER, _engine, _processed

from .test_prespec_v4_runner import _ready_target


def _settings():
    return SimpleNamespace(
        reference_workflow_mode=True,
        analysis_provider="vllm",
        prespec_overview_policy_path=None,
    )


def _binding():
    policy = load_v4_policy()
    return V4ModelBinding(
        provider="test",
        model_name=policy.model_name,
        model_digest="a" * 64,
        prompt_version=policy.prompt_version,
        policy_digest=policy.digest,
        reference_only=True,
    )


def _artifact(target, snapshot):
    return {
        "schema": ACTIVATION_SCHEMA,
        "version": 1,
        "samples": [{
            "notice_id": target.notice_id,
            "notice_key": "pre:test",
            "document_version_id": str(target.document_version_id),
            "source_sha256": snapshot.source_sha256,
            "source_size_bytes": snapshot.source_size_bytes,
        }],
        "automatic_requirements": {},
    }


def test_v4_defaults_off_before_enqueue_and_deactivate_blocks_new_attempt(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    binding = _binding()
    with pytest.raises(V4AttemptError, match="v4_disabled"):
        enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    snapshot = session.get(__import__("app.deep_review.models", fromlist=["PrespecV4PdfSnapshot"]).PrespecV4PdfSnapshot, target.snapshot_id)
    assert snapshot is not None
    activation = activate_v4(session, actor="tester", artifact=_artifact(target, snapshot), binding=binding, settings=_settings())
    session.commit()
    assert active_v4_activation(session) is not None
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    assert attempt.status == "queued"
    deactivate_v4(session, actor="tester", reason="bounded test")
    session.commit()
    assert active_v4_activation(session) is None
    session.close()
    engine.dispose()


def test_activation_duplicate_and_retry_append_new_attempt(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    binding = _binding()
    snapshot = session.get(__import__("app.deep_review.models", fromlist=["PrespecV4PdfSnapshot"]).PrespecV4PdfSnapshot, target.snapshot_id)
    assert snapshot is not None
    activate_v4(session, actor="tester", artifact=_artifact(target, snapshot), binding=binding, settings=_settings())
    first = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    assert enqueue_v4_attempt(session, target_id=target.id, binding=binding).id == first.id
    first.status = "failed"
    first.error_code = "controlled_failure"
    first.completed_at = datetime.now(UTC)
    if first.work_job_id is not None:
        job = session.get(__import__("app.deep_review.models", fromlist=["WorkJob"]).WorkJob, first.work_job_id)
        assert job is not None
        job.status = "failed"
        job.completed_at = first.completed_at
    session.commit()
    second = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    assert second.id != first.id and second.sequence == first.sequence + 1
    assert session.scalar(select(PrespecV4Attempt).where(PrespecV4Attempt.id == first.id)).status == "failed"
    session.close()
    engine.dispose()


def test_observation_requires_after_activation_and_detects_metadata_change(tmp_path):
    del tmp_path
    engine = _engine()
    session = Session(engine)
    now = datetime.now(UTC)
    notice = Notice(id=901, notice_key="pre:observation-test", source_type="pre_spec")
    run_before = Run(id="obs-before")
    run_after = Run(id="obs-after")
    session.add_all([notice, run_before, run_after])
    session.flush()
    source = ContentObject(sha256="a" * 64, size_bytes=10, detected_mime="application/x-hwp", retention_class="document-source")
    session.add(source)
    session.flush()
    document = DocumentVersion(
        id=uuid4(), notice_id=notice.id, content_object_id=source.id, version=1,
        source_kind="provider", source_system="provider", source_attachment_key="key-1",
        source_url="https://provider.invalid/attachment/1", original_filename="제안요청서.hwp",
        role="제안요청서", is_current=True, safety_status="safe", needs_human_review=False,
    )
    session.add(document)
    session.add(Attachment(
        notice_id=notice.id, name="제안요청서.hwp", source_url=document.source_url,
        source_system=document.source_system, source_attachment_key=document.source_attachment_key,
        size_bytes=source.size_bytes,
    ))
    before_snapshot = {"attachments": [{
        "name": "제안요청서.hwp", "source_url": document.source_url,
        "source_system": "provider", "source_attachment_key": "key-1", "size_bytes": 10,
    }]}
    session.add(NoticeObservation(
        notice_id=notice.id, run_id=run_before.id, observed_at=now - timedelta(minutes=2),
        changed_fields_json=[], snapshot_schema_version="notice-observation.v1",
        snapshot_jsonb=before_snapshot, source_sha256="b" * 64,
    ))
    session.flush()
    binding = _binding()
    activation = activate_v4(
        session, actor="tester", mode="new_reference", artifact={
            "schema": ACTIVATION_SCHEMA, "version": 1, "samples": [], "automatic_requirements": {},
        }, binding=binding, settings=_settings(), now=now - timedelta(minutes=1),
    )
    with pytest.raises(V4OpsError, match="observation_before_activation"):
        _observation_candidate(session, notice=notice, document=document, activation=activation)
    after_snapshot = {"attachments": [{
        "name": "제안요청서-v2.hwp", "source_url": document.source_url,
        "source_system": "provider", "source_attachment_key": "key-1", "size_bytes": 10,
    }]}
    session.add(NoticeObservation(
        notice_id=notice.id, run_id=run_after.id, observed_at=now,
        changed_fields_json=[], snapshot_schema_version="notice-observation.v1",
        snapshot_jsonb=after_snapshot, source_sha256="c" * 64,
    ))
    session.flush()
    kind, observation, reference = _observation_candidate(session, notice=notice, document=document, activation=activation)
    assert kind == "attachment_change" and observation.id == reference["observation_id"]
    assert reference["attachment_changed"] is True
    session.close()
    engine.dispose()


def test_preparation_boundary_reuses_snapshot_and_can_enqueue_controlled_binding(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    binding = _binding()
    snapshot = session.get(__import__("app.deep_review.models", fromlist=["PrespecV4PdfSnapshot"]).PrespecV4PdfSnapshot, target.snapshot_id)
    assert snapshot is not None
    activate_v4(session, actor="tester", artifact=_artifact(target, snapshot), binding=binding, settings=_settings())
    source = b"%PDF-1.7\nfixture-original"
    from app.deep_review.document_mcp.safety import ProcessorOptions
    options = {"prepare_pdf": True}
    config = {"options": vars(ProcessorOptions.from_mapping(options))}
    converter = _Converter(_processed(source), lambda _value: True)
    outcome = prepare_v4_notice(
        session,
        notice_id=target.notice_id,
        mode="explicit_sample",
        store=store,
        converter=converter,
        options=options,
        renderer=_SOURCE_RENDERER,
        font=_SOURCE_FONT,
        config=config,
        scanner=lambda _value: True,
        binding=binding,
        settings=_settings(),
        enqueue=True,
    )
    session.commit()
    assert outcome.status == "queued" and outcome.target_id == target.id and outcome.attempt_id is not None
    assert converter.calls == 0  # exact source/config/snapshot cache hit
    session.close()
    engine.dispose()
