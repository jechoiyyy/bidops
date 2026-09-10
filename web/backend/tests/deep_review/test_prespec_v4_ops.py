"""Focused cohort activation/observation/ops contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.model_client import ModelInvocationError
from app.core.models import AuditEvent
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    DocumentVersion,
    PrespecV4Attempt,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
)
from app.deep_review.services.prespec_v4 import freeze_v4_target, select_v4_input_range
from app.deep_review.services.prespec_v4_ops import (
    ACTIVATION_SCHEMA,
    V4OpsError,
    _observation_candidate,
    activate_v4,
    active_v4_activation,
    deactivate_v4,
    require_v4_enqueue_enabled,
    prepare_v4_notice,
    prepare_v4_notice_once,
)
from app.deep_review.services.prespec_v4_range import (
    RANGE_ASSIST_ACTION,
    RANGE_CONFIRMED_ACTION,
    assist_v4_range,
    confirm_v4_range,
    range_review_projection,
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


# --- R7 범위 사람 확인 (선별기 미결정 → needs_human_review → 사람 확정/모델 제안) ---

def _unresolved_processed(source: bytes):
    """같은 준비 경로에, heading 경계를 정할 수 없는 페이지 텍스트를 넣는다."""

    processed = _processed(source)
    texts = ["1. 일반 사항\n본문", "2. 제출 서류\n본문"]
    for block, text in zip(processed["blocks"], texts, strict=True):
        block["text"] = text
    for page, text in zip(processed.pdf_metadata["pages"], texts, strict=True):
        page["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    return processed


def _unresolved_notice(tmp_path):
    from app.core.object_store import FilesystemObjectStore
    from app.deep_review.document_mcp.safety import ProcessorOptions

    from .test_prespec_v4_preparation import _source

    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    session = Session(engine)
    source = b"%PDF-1.7\nfixture-unresolved"
    document, _location = _source(session, store, source)
    session.get(Notice, document.notice_id).source_type = "pre_spec"
    session.commit()
    content = session.get(ContentObject, document.content_object_id)
    binding = _binding()
    activate_v4(session, actor="tester", artifact={
        "schema": ACTIVATION_SCHEMA, "version": 1, "automatic_requirements": {},
        "samples": [{
            "notice_id": document.notice_id, "notice_key": "pre:R26BD00271191",
            "document_version_id": str(document.id), "source_sha256": content.sha256,
            "source_size_bytes": content.size_bytes,
        }],
    }, binding=binding, settings=_settings())
    session.commit()
    kwargs = dict(
        notice_id=document.notice_id, mode="explicit_sample", store=store,
        converter=_Converter(_unresolved_processed(source), lambda _value: True),
        options={"prepare_pdf": True},
        renderer=_SOURCE_RENDERER, font=_SOURCE_FONT,
        config={"options": vars(ProcessorOptions.from_mapping({"prepare_pdf": True}))},
        scanner=lambda _value: True, binding=binding, settings=_settings(),
    )
    return engine, session, store, document, kwargs


def test_undecidable_range_freezes_a_human_review_target_and_never_an_attempt(tmp_path):
    engine, session, store, document, kwargs = _unresolved_notice(tmp_path)

    # `--enqueue`여도 attempt를 만들지 않는다. 자동 실행을 열지 않는 것이 요점이다.
    outcome = prepare_v4_notice(session, **kwargs, enqueue=True)
    session.commit()

    assert outcome.status == "needs_human_review" and outcome.attempt_id is None
    assert outcome.reason_code == "scope_heading_missing"
    target = session.get(PrespecV4Target, outcome.target_id)
    assert target.selection_status == "needs_human_review" and target.reason_code == "scope_heading_missing"
    assert target.selection_strategy == "heading_scope"
    assert target.start_locator is None and target.end_locator is None and target.page_numbers_jsonb is None
    assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0

    key = next(
        location.object_key
        for location in session.scalars(
            select(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "structure")
        )
        if location.object_key.startswith(f"structure/prespec-v4/{document.id}/manifest-")
    )
    review = json.loads(store.get("structure", key)[0])
    assert review["schema_version"] == "bidops.prespec-v4-range-review.v1"
    assert review["candidates_sha256"] is None and review["candidate_count"] == 0
    assert review["reason_code"] == "scope_heading_missing"

    # 같은 상태를 한 번 더 준비해도 실패 attempt로 바뀌지 않는다.
    again = prepare_v4_notice_once(session, **kwargs)
    session.commit()
    assert again.status == "needs_human_review" and again.target_id == target.id
    assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0
    session.close()
    engine.dispose()


def _native_pending(tmp_path, *, candidate_count=2):
    """절 후보를 가진 native snapshot과 확정 대기 target 하나를 만든다."""

    from app.core.object_store import FilesystemObjectStore
    from app.deep_review.document_mcp.native_artifacts import section_candidates_bytes

    from .test_rhwp_snapshot import OPTIONS, NativeConverter, native_processed, prepare, seed_native

    store = FilesystemObjectStore(tmp_path)
    engine = _engine()
    session = Session(engine)
    processed = native_processed(candidates=candidate_count > 0)
    if candidate_count > 0:
        sections = [
            {"index": index, "title": f"{index + 1}. 구간 {index}", "page": 1, "char_count": 10, "truncated": False}
            for index in range(candidate_count)
        ]
        processed.section_candidates = {
            "schema": "bidops.section-candidates.v1", "page_count": 1, "mode": "clause",
            "section_count": candidate_count, "sections": sections,
        }
        processed.section_candidates_bytes = section_candidates_bytes(
            processed.section_candidates, max_output_bytes=OPTIONS.max_output_bytes, page_count=1
        )
    document, location = seed_native(session, store, processed)
    session.get(Notice, document.notice_id).source_type = "pre_spec"
    session.commit()
    snapshot = prepare(session, store, document, location, NativeConverter(processed))
    selection = select_v4_input_range({
        "document_version_id": str(document.id), "source_sha256": snapshot.source_sha256,
        "pages": processed.page_text["pages"], "blocks": [],
    })
    # 이 표본의 물리 쪽 텍스트에는 개요 절 heading이 없다.
    assert selection.status == "needs_human_review"
    target = freeze_v4_target(
        session, snapshot_id=snapshot.id, observation_kind="explicit_sample", observation_id=None,
        observation_reference={"sample": "r7-range"}, selection=selection,
    )
    session.commit()
    return engine, session, store, snapshot, target


def _projection(session, store, notice_id):
    return range_review_projection(session, notice_id, store_factory=lambda: store)


def test_clause_confirmation_freezes_a_ready_target_and_shows_up_in_the_projection(tmp_path):
    engine, session, store, snapshot, target = _native_pending(tmp_path)

    pending = _projection(session, store, snapshot.notice_id)
    assert pending.selection_status == "needs_human_review" and pending.confirmation is None
    assert pending.target_id == target.id and pending.snapshot_id == snapshot.id
    assert pending.reason_code == "scope_heading_missing" and pending.candidates_mode == "clause"
    assert [candidate.index for candidate in pending.candidates] == [0, 1]
    assert pending.assisted is None and pending.pdf_page_count == snapshot.pdf_page_count

    result = confirm_v4_range(
        session, store, notice_id=snapshot.notice_id, target_id=target.id, actor="최정인",
        start_index=0, end_index=1, note="개요 절만 확정",
    )
    session.commit()

    assert result.selection_status == "ready" and result.page_numbers == (1,)
    confirmed = session.get(PrespecV4Target, result.target_id)
    assert confirmed.id != target.id and confirmed.selection_strategy == "human_confirmed"
    assert confirmed.snapshot_id == snapshot.id and confirmed.observation_kind == target.observation_kind
    assert confirmed.page_numbers_jsonb == [1] and confirmed.manifest_content_object_id is not None
    # 확정은 실행을 열지 않는다.
    assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0
    audit = session.scalar(select(AuditEvent).where(
        AuditEvent.action == RANGE_CONFIRMED_ACTION, AuditEvent.aggregate_id == str(confirmed.id)
    ))
    assert audit.actor_kind == "human" and audit.claimed_name == "최정인"
    assert audit.safe_metadata == {
        "from_target_id": str(target.id), "start_index": 0, "end_index": 1,
        "first_page": 1, "last_page": 1, "candidate_count": 2,
    }
    assert "구간" not in json.dumps(audit.safe_metadata, ensure_ascii=False)

    view = _projection(session, store, snapshot.notice_id)
    assert view.selection_status == "ready" and view.target_id == confirmed.id and view.reason_code is None
    assert view.confirmation.confirmed_from_target_id == target.id
    assert (view.confirmation.start_index, view.confirmation.end_index) == (0, 1)
    assert view.confirmation.page_numbers == [1] and view.confirmation.actor == "최정인"
    assert view.confirmation.note == "개요 절만 확정"
    assert [candidate.index for candidate in view.candidates] == [0, 1]

    # 같은 target을 두 번 확정하지 못한다(최신 target이 더 이상 확정 대기가 아니다).
    with pytest.raises(V4OpsError, match="target_not_pending"):
        confirm_v4_range(session, store, notice_id=snapshot.notice_id, target_id=target.id, actor="tester", start_index=0, end_index=1)
    session.close()
    engine.dispose()


def test_page_confirmation_without_candidates_and_rejected_requests(tmp_path):
    engine, session, store, snapshot, target = _native_pending(tmp_path, candidate_count=0)

    pending = _projection(session, store, snapshot.notice_id)
    assert pending.candidates == [] and pending.candidates_mode is None

    # 후보가 없으면 index 확정은 할 수 없고, 쌍 규칙·쪽 범위도 강제된다.
    for kwargs in (
        {"start_index": 0, "end_index": 0},
        {},
        {"first_page": 1, "last_page": 1, "start_index": 0, "end_index": 0},
        {"first_page": 0, "last_page": 1},
        {"first_page": 1, "last_page": snapshot.pdf_page_count + 1},
        {"first_page": 2, "last_page": 1},
        {"first_page": 1, "last_page": 1, "note": "가" * 501},
    ):
        with pytest.raises(V4OpsError, match="range_invalid"):
            confirm_v4_range(session, store, notice_id=snapshot.notice_id, target_id=target.id, actor="tester", **kwargs)
    with pytest.raises(V4OpsError, match="target_not_found"):
        confirm_v4_range(session, store, notice_id=snapshot.notice_id + 1, target_id=target.id, actor="tester", first_page=1, last_page=1)

    result = confirm_v4_range(
        session, store, notice_id=snapshot.notice_id, target_id=target.id, actor="hong",
        first_page=1, last_page=1,
    )
    session.commit()
    confirmed = session.get(PrespecV4Target, result.target_id)
    assert confirmed.start_locator == {"kind": "page", "page": 1} and confirmed.selection_status == "ready"
    view = _projection(session, store, snapshot.notice_id)
    assert view.confirmation.start_index is None and view.confirmation.end_index is None
    assert view.confirmation.first_page == 1 and view.confirmation.last_page == 1
    session.close()
    engine.dispose()


class _AssistClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.prompts: list[str] = []

    def complete_structured(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {"model": "test", "choices": [{"finish_reason": "stop", "message": {"content": self.outcome}}]}


def _assist_settings():
    return SimpleNamespace(
        reference_workflow_mode=True, analysis_provider="vllm", prespec_overview_policy_path=None,
        vllm_base_url="http://127.0.0.1:58765/v1", vllm_allowed_hosts="127.0.0.1",
        vllm_api_key="EMPTY", vllm_model_revision="c" * 64, vllm_overview_api_dialect="vllm",
    )


@pytest.mark.parametrize("outcome,status,reason", [
    ('{"start_index": 0, "end_index": 1, "reason": "개요"}', "suggested", None),
    ('{"start_index": 0, "end_index": 9, "reason": "개요"}', "invalid", "assist_index_out_of_range"),
    (ModelInvocationError("timeout", ()), "failed", "timeout"),
])
def test_range_assist_only_records_an_audit_row(tmp_path, outcome, status, reason):
    engine, session, store, snapshot, target = _native_pending(tmp_path)
    client = _AssistClient(outcome)

    assist = assist_v4_range(
        session, store, target_id=target.id, actor="tester", settings=_assist_settings(), client=client
    )
    session.commit()

    assert assist.status == status and assist.reason_code == reason
    assert assist.quality_status == "unmeasured_reference" and assist.model_revision == "c" * 64
    # 제안은 target도 attempt도 만들지 않는다.
    assert session.scalar(select(func.count()).select_from(PrespecV4Target)) == 1
    assert session.scalar(select(func.count()).select_from(PrespecV4Attempt)) == 0
    audit = session.scalar(select(AuditEvent).where(
        AuditEvent.action == RANGE_ASSIST_ACTION, AuditEvent.aggregate_id == str(target.id)
    ))
    assert audit.safe_metadata["status"] == status and audit.safe_metadata["reason_code"] == reason
    assert audit.safe_metadata["prompt_sha256"] == assist.prompt_sha256
    # 절 제목과 모델 사유 문장은 감사에 남지 않는다.
    assert "구간" not in json.dumps(audit.safe_metadata, ensure_ascii=False)
    assert "개요" not in json.dumps(audit.safe_metadata, ensure_ascii=False)

    view = _projection(session, store, snapshot.notice_id)
    if status == "suggested":
        assert client.prompts and "구간 0" in client.prompts[0]
        assert (view.assisted.start_index, view.assisted.end_index) == (0, 1)
        assert view.assisted.quality_status == "unmeasured_reference"
    else:
        assert view.assisted is None
    if status == "failed":
        # 호출 실패는 재시도를 막지 않는다. 기록된 제안·무효만 한 번으로 묶는다.
        assert assist_v4_range(
            session, store, target_id=target.id, actor="tester", settings=_assist_settings(), client=client
        ).status == "failed"
    else:
        with pytest.raises(V4OpsError, match="assist_already_recorded"):
            assist_v4_range(session, store, target_id=target.id, actor="tester", settings=_assist_settings(), client=client)
    session.close()
    engine.dispose()


def test_range_assist_requires_reference_mode_and_two_candidates(tmp_path):
    engine, session, store, snapshot, target = _native_pending(tmp_path, candidate_count=1)
    client = _AssistClient('{"start_index": 0, "end_index": 0, "reason": "개요"}')

    off = _assist_settings()
    off.reference_workflow_mode = False
    with pytest.raises(V4OpsError, match="reference_workflow_disabled"):
        assist_v4_range(session, store, target_id=target.id, actor="tester", settings=off, client=client)
    with pytest.raises(V4OpsError, match="assist_not_applicable"):
        assist_v4_range(session, store, target_id=target.id, actor="tester", settings=_assist_settings(), client=client)

    empty = _assist_settings()
    empty.vllm_allowed_hosts = ""
    engine2, session2, store2, snapshot2, target2 = _native_pending(tmp_path / "two")
    with pytest.raises(V4OpsError, match="model_binding_unavailable"):
        assist_v4_range(session2, store2, target_id=target2.id, actor="tester", settings=empty, client=client)
    assert session2.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == RANGE_ASSIST_ACTION)) == 0
    assert not client.prompts
    session.close()
    engine.dispose()
    session2.close()
    engine2.dispose()
