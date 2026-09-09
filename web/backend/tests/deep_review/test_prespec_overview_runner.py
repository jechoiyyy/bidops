"""개요 검토 모델 실행(binding·큐 유입·lease·runner)의 회귀 검사 (명세 §6.3).

모든 검사는 fake transport와 임시 SQLite로만 돈다. 실제 vLLM·Ollama·나라장터
주소를 부르지 않으며 fixture 문서는 합성 텍스트다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.model_client import ModelClient, ModelIdentity
from app.core.models import AuditEvent
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    PreSpecOverviewAttempt,
    PreSpecOverviewAttemptEvent,
    PreSpecOverviewResult,
    PreSpecOverviewReview,
    PreSpecOverviewSnapshot,
)
from app.deep_review.services.auto_preparation import AUTO_ACTOR_KIND, AUTO_ACTOR_NAME
from app.deep_review.services.prespec_overview import (
    OverviewModelBinding,
    approved_overview_binding,
    build_overview_model_input,
    claim_overview_attempt,
    enqueue_overview_attempt,
    expire_overview_leases,
    load_overview_policy,
    overview_quality_status,
    prepare_overview_review,
)
from app.deep_review.services.prespec_overview_runner import (
    OVERVIEW_LEASE_SECONDS,
    OVERVIEW_STAGE,
    PreSpecOverviewRunner,
)
from app.deep_review.workers.prespec_overview import run_once

from .test_prespec_overview import _block, _engine, _notice, _seed_document


WORKER_ID = "test-analysis-worker"


def _result_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "bidops.prespec-overview-result.v1",
        "recommendation": "추진 검토",
        "summary": "합성 사업개요 범위의 요약",
        "conditions": [],
        "verification_due_at": None,
        "unknowns": [],
        "evidence": [
            {
                "claim": "사업개요 경계",
                "locator": {"block_key": "start", "page": 1, "ordinal": 0},
            }
        ],
        "input_limitations": ["앞부분만 확인했다"],
    }
    payload.update(overrides)
    return payload


class _FakeStore:
    """암호화 model-response 저장소의 계약만 흉내 내는 fake."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str):
        import hashlib

        self.calls.append(data)
        return {
            "encrypted": True,
            "object_key": f"model-response/{uuid4().hex}.bin",
            "object_version_id": "v1",
            "etag": "etag-1",
            "encryption_key_ref": "test-key-ref",
            "plaintext_sha256": hashlib.sha256(data).hexdigest(),
            "plaintext_size_bytes": len(data),
        }


class _FakeClient:
    """policy가 지정한 모델을 부른 것처럼 구조화 출력만 돌려준다."""

    def __init__(self, outputs: list[Any], *, model: str = "합성-개요-모델") -> None:
        self.outputs = list(outputs)
        self.model = model
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def verify_identity(self) -> ModelIdentity:
        return ModelIdentity(model=self.model, revision="b" * 64)

    def invoke(self, stage: str, input_slice: Any, policy: Any, **_kwargs: Any):
        self.calls.append((stage, dict(input_slice)))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        import json

        raw = json.dumps(output, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return SimpleNamespace(structured_output=output, raw_response=raw)


def _binding(*, reference_only: bool = False) -> OverviewModelBinding:
    return OverviewModelBinding(
        provider="openai-compatible",
        model_name="합성-개요-모델",
        model_digest="b" * 64,
        prompt_version="prespec-overview-v1",
        reference_only=reference_only,
        deployable=False,
    )


def _ready_review(tmp_path: Path, key: str = "runner"):
    engine = _engine()
    session = Session(engine)
    notice = _notice(session, key)
    _seed_document(
        session,
        tmp_path,
        notice,
        [
            _block("start", "heading", "사업개요"),
            _block("body", "paragraph", "합성 본문 문장"),
            _block("end", "heading", "과업내용"),
        ],
        source_suffix=key,
    )
    review = prepare_overview_review(session, notice.id, root=tmp_path)
    session.commit()
    assert review.status == "awaiting_model"
    return engine, session, notice, review


def _runner(tmp_path: Path, client: Any, *, binding: OverviewModelBinding | None, **kwargs: Any):
    return PreSpecOverviewRunner(
        client=client,
        binding=binding,
        raw_response_store=_FakeStore(),
        root=tmp_path,
        **kwargs,
    )


def test_policy_file_binds_model_prompt_and_output_schema() -> None:
    """policy가 모델명·프롬프트 version·출력 schema·generation 설정을 갖는다."""

    policy = load_overview_policy()
    assert policy is not None
    assert policy.document["schema"] == "bidops.prespec-overview-policy.v1"
    assert policy.model_name and policy.prompt_version
    assert policy.document["model_endpoint_ref"] == "vllm-openai-compatible"
    assert policy.document["chunking"] == {"timeout_seconds": 300, "retries": 2}
    assert policy.document["generation"] == {
        "enable_thinking": False,
        "max_completion_tokens": 16384,
        "seed": 0,
        "temperature": 0.7,
        "top_k": 20,
        "top_p": 0.8,
    }
    assert policy.output_schema["properties"]["schema_version"]["const"] == (
        "bidops.prespec-overview-result.v1"
    )
    assert len(policy.digest) == 64


def test_approved_binding_requires_policy_and_identity() -> None:
    """policy·선언 revision·identity가 모두 있을 때만 binding이 나온다."""

    policy = load_overview_policy()
    binding = approved_overview_binding(
        policy=policy,
        identity=lambda: ModelIdentity(model=policy.model_name, revision="c" * 64),
    )
    assert binding is not None
    assert binding.provider == "openai-compatible"
    assert binding.model_name == policy.model_name
    assert binding.model_digest == "c" * 64
    assert binding.prompt_version == policy.prompt_version
    assert binding.reference_only is False
    assert binding.deployable is False
    assert binding.policy_digest == policy.digest

    def _fail() -> ModelIdentity:
        raise OSError("no route")

    assert approved_overview_binding(policy=policy, identity=_fail) is None
    assert approved_overview_binding(policy=None, identity=_fail) is None


def test_model_input_carries_only_block_text_page_ordinal_and_key(tmp_path: Path) -> None:
    engine, session, _notice_row, review = _ready_review(tmp_path, "input")
    try:
        snapshot = session.get(PreSpecOverviewSnapshot, review.current_snapshot_id)
        blocks = build_overview_model_input(session, snapshot, root=tmp_path)
        assert [item["block_key"] for item in blocks] == ["start", "body"]
        assert [item["ordinal"] for item in blocks] == [0, 1]
        assert all(set(item) == {"block_key", "page", "ordinal", "text"} for item in blocks)
    finally:
        session.close()
        engine.dispose()


def test_frozen_overview_input_needs_only_structure_storage(tmp_path: Path, monkeypatch) -> None:
    from app.deep_review.services import assets
    engine, session, _, review = _ready_review(tmp_path, "structure-only")
    original = assets.read_object
    reads = []
    def structure_only(namespace, *args, **kwargs):
        reads.append(namespace)
        assert namespace == "structure", "analysis worker must not read source bytes"
        return original(namespace, *args, **kwargs)
    monkeypatch.setattr(assets, "read_object", structure_only)
    try:
        snapshot = session.get(PreSpecOverviewSnapshot, review.current_snapshot_id)
        assert build_overview_model_input(session, snapshot, root=tmp_path)
        assert reads == ["structure"]
    finally:
        session.close()
        engine.dispose()


def test_immutable_snapshot_reads_do_not_require_update_privileges(tmp_path: Path) -> None:
    engine, session, _, _ = _ready_review(tmp_path, "snapshot-read-only")
    checked = []
    def check_statement(state):
        if not state.is_select:
            return
        if any(d.get('entity') is PreSpecOverviewSnapshot for d in state.statement.column_descriptions):
            assert state.statement._for_update_arg is None
            checked.append(True)
    event.listen(session, 'do_orm_execute', check_statement)
    try:
        outcome = _runner(tmp_path, _FakeClient([_result_payload()]), binding=_binding()).run_once(session, WORKER_ID)
        assert outcome.status == 'completed'
        assert checked
    finally:
        session.close()
        engine.dispose()


def test_failed_reverification_does_not_reuse_ready_snapshot(tmp_path: Path, monkeypatch) -> None:
    from app.deep_review.services import assets
    engine, session, notice, review = _ready_review(tmp_path, "reverification")
    original_snapshot_id = review.current_snapshot_id
    def unavailable(*args, **kwargs):
        raise assets.AssetError('service_unavailable', 'unavailable')
    monkeypatch.setattr(assets, 'read_object', unavailable)
    try:
        prepared = prepare_overview_review(session, notice.id, root=tmp_path)
        assert prepared.status == 'needs_human_review'
        assert prepared.current_snapshot_id is None
        assert prepared.current_snapshot is None
        assert session.get(PreSpecOverviewSnapshot, original_snapshot_id).cut_status == 'ready'
    finally:
        session.close()
        engine.dispose()


def test_awaiting_model_review_runs_to_completed_without_deployable(tmp_path: Path) -> None:
    """실제 모델의 품질 미측정 실행이 완주한다 (deployable=false)."""

    engine, session, notice, review = _ready_review(tmp_path, "happy")
    client = _FakeClient([_result_payload()])
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.claimed is True
        assert outcome.status == "completed"

        attempt = session.scalar(select(PreSpecOverviewAttempt))
        assert attempt is not None
        assert attempt.status == "completed"
        assert attempt.reference_only is False
        assert attempt.deployable is False
        assert attempt.lease_owner is None and attempt.lease_expires_at is None
        assert overview_quality_status(attempt) == "unmeasured_reference"
        session.refresh(review)
        assert review.status == "completed"
        assert review.result == "추진 검토"
        assert session.scalar(select(PreSpecOverviewResult)) is not None

        statuses = session.scalars(
            select(PreSpecOverviewAttemptEvent.to_status).order_by(
                PreSpecOverviewAttemptEvent.event_sequence
            )
        ).all()
        assert statuses == ["running", "completed"]

        audit = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "prespec_overview.attempt_run")
        ).all()
        assert len(audit) == 1
        metadata = audit[0].safe_metadata
        assert metadata["status"] == "completed"
        assert metadata["quality_status"] == "unmeasured_reference"
        assert metadata["notice_id"] == notice.id
        forbidden = {"object_key", "prompt", "response", "path", "text"}
        assert not forbidden & set(metadata)

        # 원응답은 암호화 저장소로 나가고 DB에는 참조와 hash만 남는다.
        location = session.scalar(
            select(ContentObjectLocation).where(
                ContentObjectLocation.namespace_key == "model-response"
            )
        )
        assert location is not None
        content = session.get(ContentObject, location.content_object_id)
        assert content is not None and len(content.sha256) == 64

        assert client.calls and client.calls[0][0] == OVERVIEW_STAGE
        sent = client.calls[0][1]
        assert set(sent) == {"blocks"}
        assert all(
            set(block) == {"block_key", "page", "ordinal", "text"} for block in sent["blocks"]
        )
    finally:
        session.close()
        engine.dispose()


def test_mock_reference_attempt_still_cannot_complete(tmp_path: Path) -> None:
    engine, session, _notice_row, review = _ready_review(tmp_path, "mock")
    client = _FakeClient([_result_payload()])
    try:
        runner = _runner(tmp_path, client, binding=_binding(reference_only=True))
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.status == "failed"
        attempt = session.scalar(select(PreSpecOverviewAttempt))
        assert attempt is not None
        assert attempt.status == "failed"
        assert overview_quality_status(attempt) == "mock_reference"
        assert session.scalar(select(PreSpecOverviewResult)) is None
        session.refresh(review)
        assert review.status == "failed"
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    [
        ({"schema_version": "bidops.prespec-overview-result.v1"}, "validation_failed"),
        (
            _result_payload(
                evidence=[
                    {
                        "claim": "범위 밖",
                        "locator": {"block_key": "end", "page": 1, "ordinal": 2},
                    }
                ]
            ),
            "evidence_out_of_scope",
        ),
    ],
)
def test_invalid_result_fails_without_auto_correction(
    tmp_path: Path, payload: dict[str, Any], reason_code: str
) -> None:
    engine, session, _notice_row, review = _ready_review(tmp_path, f"invalid-{reason_code}")
    client = _FakeClient([payload])
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.status == "failed"
        attempt = session.scalar(select(PreSpecOverviewAttempt))
        assert attempt is not None and attempt.status == "failed"
        assert session.scalar(select(PreSpecOverviewResult)) is None
        # 자동 보정·재프롬프트로 통과시키지 않으므로 호출은 한 번뿐이다.
        assert len(client.calls) == 1
        event = session.scalars(
            select(PreSpecOverviewAttemptEvent).order_by(
                PreSpecOverviewAttemptEvent.event_sequence.desc()
            )
        ).first()
        assert event is not None and event.reason_code == reason_code
        session.refresh(review)
        assert review.status == "failed"
    finally:
        session.close()
        engine.dispose()


def test_timeout_fails_after_the_bounded_retries(tmp_path: Path) -> None:
    """호출 timeout은 정책 상한(1+2회)까지만 재시도하고 failed로 닫는다."""

    engine, session, _notice_row, _review = _ready_review(tmp_path, "timeout")
    policy = load_overview_policy()
    calls: list[int] = []

    def _completion_create(**_kwargs: Any):
        calls.append(1)
        raise TimeoutError("synthetic timeout")

    client = ModelClient(
        model=policy.model_name,
        output_contract=policy.output_contract,
        allowed_hosts="127.0.0.1",
        completion_create=_completion_create,
        models_list=lambda: {"data": [{"id": policy.model_name}]},
    )
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.status == "failed"
        assert len(calls) == 3
        attempt = session.scalar(select(PreSpecOverviewAttempt))
        assert attempt is not None and attempt.status == "failed"
        assert attempt.lease_owner is None and attempt.lease_expires_at is None
        event = session.scalars(
            select(PreSpecOverviewAttemptEvent).order_by(
                PreSpecOverviewAttemptEvent.event_sequence.desc()
            )
        ).first()
        assert event is not None and event.reason_code == "timeout"
    finally:
        session.close()
        engine.dispose()


def test_missing_binding_keeps_the_review_awaiting_model(tmp_path: Path) -> None:
    engine, session, _notice_row, review = _ready_review(tmp_path, "nobinding")
    try:
        runner = _runner(tmp_path, None, binding=None)
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.claimed is False
        session.refresh(review)
        assert review.status == "awaiting_model"
        assert session.scalar(select(PreSpecOverviewAttempt)) is None
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("status", ["needs_human_review", "failed", "cancelled"])
def test_human_and_terminal_reviews_are_not_queued(tmp_path: Path, status: str) -> None:
    engine, session, _notice_row, review = _ready_review(tmp_path, f"skip-{status}")
    try:
        review.status = status
        session.flush()
        session.commit()
        assert enqueue_overview_attempt(session, _binding()) is None
        session.commit()
        assert session.scalar(select(PreSpecOverviewAttempt)) is None
    finally:
        session.close()
        engine.dispose()


def test_queue_intake_skips_a_snapshot_that_already_has_an_active_attempt(
    tmp_path: Path,
) -> None:
    engine, session, _notice_row, _review = _ready_review(tmp_path, "duplicate")
    try:
        first = enqueue_overview_attempt(session, _binding())
        session.commit()
        assert first is not None
        assert enqueue_overview_attempt(session, _binding()) is None
        session.commit()
        assert len(session.scalars(select(PreSpecOverviewAttempt)).all()) == 1
    finally:
        session.close()
        engine.dispose()


def test_claim_sets_the_lease_and_expiry_closes_it_as_failed(tmp_path: Path) -> None:
    """만료된 lease는 다음 poll이 failed(lease_expired)로 닫고 재시작하지 않는다."""

    engine, session, _notice_row, review = _ready_review(tmp_path, "lease")
    try:
        attempt = enqueue_overview_attempt(session, _binding())
        session.commit()
        assert attempt is not None
        started = attempt.created_at + timedelta(seconds=5)
        claimed = claim_overview_attempt(
            session, WORKER_ID, lease_seconds=OVERVIEW_LEASE_SECONDS, now=started
        )
        session.commit()
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.started_at == started
        assert claimed.lease_owner == WORKER_ID
        assert claimed.lease_expires_at == started + timedelta(seconds=OVERVIEW_LEASE_SECONDS)
        # 아직 살아 있는 lease는 회수하지 않는다.
        assert expire_overview_leases(session, now=started + timedelta(seconds=1)) == []

        expired = expire_overview_leases(
            session, now=started + timedelta(seconds=OVERVIEW_LEASE_SECONDS + 1)
        )
        session.commit()
        assert expired == [claimed.id]
        session.refresh(claimed)
        assert claimed.status == "failed"
        assert claimed.lease_owner is None and claimed.lease_expires_at is None
        event = session.scalars(
            select(PreSpecOverviewAttemptEvent).order_by(
                PreSpecOverviewAttemptEvent.event_sequence.desc()
            )
        ).first()
        assert event is not None and event.reason_code == "lease_expired"
        session.refresh(review)
        assert review.status == "failed"
        # 자동 재시작은 없다 — 다음 poll이 같은 review를 다시 큐에 넣지 않는다.
        assert enqueue_overview_attempt(session, _binding()) is None
    finally:
        session.close()
        engine.dispose()


def test_worker_entry_point_runs_one_attempt_per_poll(tmp_path: Path) -> None:
    engine, session, _notice_row, _review = _ready_review(tmp_path, "worker")
    client = _FakeClient([_result_payload()])
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        first = run_once(session, WORKER_ID, runner=runner)
        session.commit()
        assert first.claimed is True
        second = run_once(session, WORKER_ID, runner=runner)
        session.commit()
        assert second.claimed is False
        assert len(session.scalars(select(PreSpecOverviewAttempt)).all()) == 1
    finally:
        session.close()
        engine.dispose()


def test_review_v2_projection_carries_quality_status(tmp_path: Path) -> None:
    from app.deep_review.services.prespec_overview import get_overview_reviews_v2

    engine, session, notice, _review = _ready_review(tmp_path, "quality")
    client = _FakeClient([_result_payload()])
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        runner.run_once(session, WORKER_ID)
        session.commit()
        response = get_overview_reviews_v2(session, notice.id, root=tmp_path)
        view = response.reviews[0]
        assert view.quality_status == "unmeasured_reference"
        assert view.attempts[0].quality_status == "unmeasured_reference"
    finally:
        session.close()
        engine.dispose()


def test_review_rows_are_untouched_when_no_review_is_ready(tmp_path: Path) -> None:
    engine = _engine()
    session = Session(engine)
    client = _FakeClient([])
    try:
        runner = _runner(tmp_path, client, binding=_binding())
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.claimed is False
        assert session.scalar(select(PreSpecOverviewReview)) is None
        assert client.calls == []
    finally:
        session.close()
        engine.dispose()


# --- 개요 완료 → SW사업대상=Y 자동 심층 검토 시작 (명세 §6.4) -----------------


class _RecordingDeepReviewService:
    """`DeepReviewService.create_review` 계약만 흉내 내는 fake."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[int, Any, str | None, str]] = []
        self.error = error

    def create_review(
        self,
        session: Session,
        notice_id: int,
        bundle_id: Any,
        actor: str | None,
        request_id: Any,
        *,
        actor_kind: str = "human",
    ) -> dict[str, Any]:
        self.calls.append((notice_id, bundle_id, actor, actor_kind))
        if self.error is not None:
            raise self.error
        review = DeepReview(
            notice_id=notice_id,
            bundle_id=bundle_id,
            profile_version_id=_AUTO_PROFILE_ID,
            policy_version_id=_AUTO_POLICY_ID,
            effective_grade_at_start="우선 검토",
            status="queued",
            requested_by_name=actor,
        )
        session.add(review)
        session.commit()
        return {"id": str(review.id)}


_AUTO_PROFILE_ID = uuid4()
_AUTO_POLICY_ID = uuid4()


def _auto_start_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    *,
    sw_business_status: str = "Y",
):
    """개요만 끝나면 §6.4가 성립하도록 세운 사전규격 하나."""

    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(_AUTO_PROFILE_ID))
    monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(_AUTO_POLICY_ID))
    engine = _engine()
    session = Session(engine)
    notice = _notice(session, key)
    notice.qualification_flags_json = {"sw_business_status": sw_business_status}
    document, structure, _source, _payload = _seed_document(
        session,
        tmp_path,
        notice,
        [
            _block("start", "heading", "사업개요"),
            _block("body", "paragraph", "합성 본문 문장"),
            _block("end", "heading", "과업내용"),
        ],
        source_suffix=key,
    )
    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
        created_by_name=AUTO_ACTOR_NAME,
        confirmed_by_name=AUTO_ACTOR_NAME,
        confirmed_at=datetime.now(UTC),
    )
    session.add(bundle)
    session.flush()
    session.add(
        DocumentBundleItem(
            bundle_id=bundle.id,
            document_version_id=document.id,
            ordinal=0,
            document_version_version=document.version,
            content_object_id=document.content_object_id,
            content_sha256=structure.source_sha256,
            detected_mime="application/pdf",
            size_bytes=1,
            original_filename=document.original_filename,
            source_kind="provider",
            source_system="g2b",
            source_attachment_key=document.source_attachment_key,
            role_at_confirmation="제안요청서",
            is_current_at_confirmation=True,
            safety_status_at_confirmation="safe",
            structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        )
    )
    review = prepare_overview_review(session, notice.id, root=tmp_path)
    session.commit()
    assert review.status == "awaiting_model"
    return engine, session, notice, bundle, review


def test_a_completed_overview_waits_for_company_fit_before_deep_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """개요 완료만으로는 회사 핏 게이트를 통과하지 않는다."""

    engine, session, notice, bundle, review = _auto_start_ready(
        tmp_path, monkeypatch, "autostart"
    )
    deep_reviews = _RecordingDeepReviewService()
    try:
        runner = _runner(
            tmp_path,
            _FakeClient([_result_payload()]),
            binding=_binding(),
            deep_review_service=deep_reviews,
        )
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()

        assert outcome.status == "completed"
        assert deep_reviews.calls == []
        assert len(session.scalars(select(DeepReview)).all()) == 0
        session.refresh(review)
        assert review.status == "completed"
    finally:
        session.close()
        engine.dispose()


def test_an_sw_n_pre_spec_completes_the_overview_without_a_deep_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, session, _notice_row, _bundle, review = _auto_start_ready(
        tmp_path, monkeypatch, "autostart-n", sw_business_status="N"
    )
    deep_reviews = _RecordingDeepReviewService()
    try:
        runner = _runner(
            tmp_path,
            _FakeClient([_result_payload()]),
            binding=_binding(),
            deep_review_service=deep_reviews,
        )
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()

        assert outcome.status == "completed"
        assert deep_reviews.calls == []
        assert session.scalar(select(DeepReview)) is None
    finally:
        session.close()
        engine.dispose()


def test_a_failing_auto_start_does_not_undo_the_completed_overview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hook 실패가 개요 완료를 되돌리면 안 된다."""

    from app.deep_review.services import company_fit
    monkeypatch.setattr(
        company_fit,
        "gate_reasons",
        lambda session, ids, *, current_v4=None: {i: None for i in ids},
    )
    engine, session, _notice_row, _bundle, review = _auto_start_ready(
        tmp_path, monkeypatch, "autostart-fail"
    )
    deep_reviews = _RecordingDeepReviewService(error=RuntimeError("생성 실패"))
    try:
        runner = _runner(
            tmp_path,
            _FakeClient([_result_payload()]),
            binding=_binding(),
            deep_review_service=deep_reviews,
        )
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()

        assert outcome.status == "completed"
        assert len(deep_reviews.calls) == 1
        assert session.scalar(select(DeepReview)) is None
        attempt = session.scalar(select(PreSpecOverviewAttempt))
        assert attempt is not None and attempt.status == "completed"
        session.refresh(review)
        assert review.status == "completed"
        assert review.result == "추진 검토"
    finally:
        session.close()
        engine.dispose()


# --- 빈 poll의 비용과 유입 실패의 회복 (명세 §6.3) ---------------------------


def _seed_ready_review(session: Session, tmp_path: Path, key: str):
    """이미 열린 session에 ``awaiting_model`` review 하나를 더 심는다."""

    notice = _notice(session, key)
    _seed_document(
        session,
        tmp_path,
        notice,
        [
            _block("start", "heading", "사업개요"),
            _block("body", "paragraph", "합성 본문 문장"),
            _block("end", "heading", "과업내용"),
        ],
        source_suffix=key,
    )
    review = prepare_overview_review(session, notice.id, root=tmp_path)
    session.commit()
    assert review.status == "awaiting_model"
    return notice, review


def test_an_idle_poll_never_reaches_the_model_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """큐가 비면 client를 만들지도 `/models`를 부르지도 않는다 (명세 §6.3).

    합성 worker는 1초마다 이 슬롯을 돈다. 할 일이 없는데 binding을 해석하면
    idle worker가 하루 8만여 번 승인 경계 밖으로 identity 요청을 내고, 그
    호출이 느리면 같은 loop의 C-2·심층 검토 슬롯까지 굶는다.
    """

    from app.deep_review.services import prespec_overview_runner as runner_module

    policy = load_overview_policy()
    assert policy is not None
    built: list[str] = []
    identity_calls: list[str] = []

    class _SpyClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__([_result_payload()], model=policy.model_name)

        def verify_identity(self) -> ModelIdentity:
            identity_calls.append("models")
            return ModelIdentity(model=policy.model_name, revision="d" * 64)

    def _for_purpose(*_args: Any, **_kwargs: Any) -> _SpyClient:
        built.append("client")
        return _SpyClient()

    monkeypatch.setattr(runner_module.ModelClient, "for_purpose", _for_purpose)

    engine = _engine()
    session = Session(engine)
    try:
        runner = PreSpecOverviewRunner(raw_response_store=_FakeStore(), root=tmp_path)
        outcome = runner.run_once(session, WORKER_ID)
        session.commit()
        assert outcome.claimed is False
        # 이것이 이 검사의 전부다. 큐가 비면 provider를 만지지 않는다.
        assert built == []
        assert identity_calls == []

        # 검사가 공허하지 않다는 확인: 할 일이 생기면 그때 해석한다.
        _seed_ready_review(session, tmp_path, "idle-probe")
        runner.run_once(session, WORKER_ID)
        session.commit()
        assert built == ["client"]
        assert identity_calls == ["models"]
    finally:
        session.close()
        engine.dispose()


def test_a_resolved_runner_does_not_rebuild_its_client_on_later_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 번 해석한 binding·client는 poll을 넘겨 산다 (명세 §6.3)."""

    from app.deep_review.services import prespec_overview_runner as runner_module

    policy = load_overview_policy()
    assert policy is not None
    built: list[str] = []

    class _SpyClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__(
                [_result_payload(), _result_payload()], model=policy.model_name
            )

        def verify_identity(self) -> ModelIdentity:
            return ModelIdentity(model=policy.model_name, revision="d" * 64)

    def _for_purpose(*_args: Any, **_kwargs: Any) -> _SpyClient:
        built.append("client")
        return _SpyClient()

    monkeypatch.setattr(runner_module.ModelClient, "for_purpose", _for_purpose)

    engine = _engine()
    session = Session(engine)
    try:
        runner = PreSpecOverviewRunner(raw_response_store=_FakeStore(), root=tmp_path)
        _seed_ready_review(session, tmp_path, "cache-first")
        assert runner.run_once(session, WORKER_ID).status == "completed"
        session.commit()
        assert built == ["client"]

        _seed_ready_review(session, tmp_path, "cache-second")
        runner.run_once(session, WORKER_ID)
        session.commit()
        # 두 번째 poll은 캐시된 client를 그대로 쓴다.
        assert built == ["client"]
    finally:
        session.close()
        engine.dispose()


def test_a_review_that_cannot_produce_an_attempt_is_closed_and_the_slot_moves_on(
    tmp_path: Path,
) -> None:
    """유입이 거부된 review를 닫고 다음 poll이 건강한 review를 처리한다.

    유입 후보는 ``updated_at ASC``로 뽑히므로, 닫지 않으면 같은 review가 1초마다
    영원히 다시 뽑혀 개요 슬롯이 그 한 건에 막힌다.
    """

    engine = _engine()
    session = Session(engine)
    client = _FakeClient([_result_payload()])
    try:
        poison_notice, poison = _seed_ready_review(session, tmp_path, "poison")
        # snapshot을 쓸 수 없게 만든다 — 범위가 어긋난 review다.
        poison_notice.source_type = "notice"
        session.flush()
        session.commit()
        _healthy_notice, healthy = _seed_ready_review(session, tmp_path, "healthy")

        runner = _runner(tmp_path, client, binding=_binding())
        first = runner.run_once(session, WORKER_ID)
        assert first.status == "failed"
        assert first.reason_code == "scope_mismatch"
        assert client.calls == []
        session.refresh(poison)
        assert poison.status == "failed"
        audit = session.scalars(
            select(AuditEvent).where(
                AuditEvent.aggregate_type == "prespec_overview_review"
            )
        ).all()
        assert len(audit) == 1
        assert audit[0].safe_metadata["reason_code"] == "scope_mismatch"
        assert audit[0].safe_metadata["status"] == "failed"

        # 슬롯이 막히지 않았다 — 다음 poll이 건강한 review를 끝까지 돈다.
        second = runner.run_once(session, WORKER_ID)
        session.commit()
        assert second.claimed is True
        assert second.status == "completed"
        session.refresh(healthy)
        assert healthy.status == "completed"
    finally:
        session.close()
        engine.dispose()
