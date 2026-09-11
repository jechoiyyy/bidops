"""개요 run의 enqueue 조건과 한 poll의 실행 계약 (MVP, 2026-09-11).

모델도 객체 저장소도 부르지 않는다. 모델 transport와 원응답 저장소만 fake로
갈아 끼우고 결정적 검증·의미 검토·구성은 실제 함수를 그대로 지난다.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base
from app.core.model_client import ModelClient
from app.core.object_store import ObjectMetadata
from app.deep_review.models import (
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PrespecOverviewRun,
    PrespecV4PdfSnapshot,
    WorkJob,
)
from app.deep_review.services import overview_runs
from app.deep_review.services.effective_grade import EffectiveGrade
from app.deep_review.services.mock_analysis_client import MockOverviewTransport
from app.deep_review.services.prespec_overview_claim_policy import CLAIMS_STAGE, load_claims_policy
from app.lifecycle.models import Notice


PAGE_TEXT = (
    "사업개요는 합성 통합 표준 시스템을 구축하는 것이다.\n"
    "주요 과업은 합성 자료 연계와 화면 개발을 수행하는 것이다.\n"
    # 단위 없는 숫자는 경고로만 남아야 하는 대조다 (MVP 계약).
    "사업 예산과 기간은 평가 배점 80점 기준으로 담당자가 확인한다.\n"
    "입찰 참가 자격은 합성 자리표시자이며 원문 확인이 필요하다."
)


class _FakeStore:
    """object key → bytes만 갖는 fake. socket도 filesystem도 열지 않는다."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, namespace: str, object_key: str, data: bytes, *, content_type: str) -> ObjectMetadata:
        self.objects[object_key] = data
        return ObjectMetadata(namespace, object_key, "v1", "etag-1", len(data))

    def get(self, namespace: str, object_key: str, *, max_bytes: int = 0, version_id: str | None = None):
        data = self.objects[object_key]
        return data, ObjectMetadata(namespace, object_key, version_id or "v1", "etag-1", len(data))


class _FakeResponseStore:
    """암호화 원응답 저장소의 계약만 흉내 내는 fake."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str):
        self.calls.append(data)
        return {
            "object_key": f"model-response/{uuid4().hex}.bin",
            "object_version_id": "v1",
            "etag": "etag-1",
            "encryption_key_ref": "test-key-ref",
            "plaintext_sha256": hashlib.sha256(data).hexdigest(),
            "plaintext_size_bytes": len(data),
        }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(session, store, *, namespace: str, key: str, data: bytes, mime: str):
    content = ContentObject(
        id=uuid4(), sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
        detected_mime=mime, retention_class="document-source",
    )
    session.add(content)
    session.flush()
    metadata = store.put(namespace, key, data, content_type=mime)
    location = ContentObjectLocation(
        id=uuid4(), content_object_id=content.id, namespace_key=namespace, object_key=key,
        object_version_id=metadata.object_version_id, status="verified", etag=metadata.etag,
    )
    session.add(location)
    session.flush()
    return content, location


def seed(session, store, *, bundle_ready: bool = True, filename: str = "합성-제안요청서.pdf"):
    """`우선 검토` 사전규격 한 건과 동결 스냅샷 하나를 세운다."""

    notice = Notice(notice_key=f"ov:{uuid4()}", source_type="pre_spec", title="합성 사전규격")
    session.add(notice)
    session.flush()
    source, source_location = _object(
        session, store, namespace="source", key=f"source/{uuid4().hex}.pdf",
        data=f"%PDF-1.4 synthetic {uuid4()}".encode("utf-8"), mime="application/pdf",
    )
    document = DocumentVersion(
        id=uuid4(), notice_id=notice.id, content_object_id=source.id, version=1,
        source_kind="manual", original_filename=filename, role="제안요청서",
        is_current=True, safety_status="safe",
    )
    session.add(document)
    session.flush()
    structure = DocumentStructure(
        document_version_id=document.id, source_sha256=source.sha256, media_type="application/pdf",
        extractor_name="test", extractor_version="1", payload_content_object_id=source.id,
        payload_sha256=source.sha256, page_count=1, block_count=1, validation_status="ready",
    )
    session.add(structure)
    session.flush()
    if bundle_ready:
        bundle = DocumentBundle(
            id=uuid4(), notice_id=notice.id, revision=1, version=1, status="ready",
            created_by_name="auto-preparation", confirmed_by_name="auto-preparation",
            issues_snapshot=[],
        )
        session.add(bundle)
        session.flush()
        session.add(DocumentBundleItem(
            bundle_id=bundle.id, document_version_id=document.id, ordinal=1,
            document_version_version=document.version, content_object_id=source.id,
            content_sha256=source.sha256, detected_mime=source.detected_mime,
            size_bytes=source.size_bytes, original_filename=document.original_filename,
            source_kind=document.source_kind, role_at_confirmation=document.role,
            is_current_at_confirmation=True, safety_status_at_confirmation="safe",
            structure_id_at_confirmation=structure.id, structure_payload_sha256=structure.payload_sha256,
        ))
        session.flush()
    # 공고마다 한 줄을 다르게 둔다. `content_object.sha256`이 유니크하므로 두
    # 공고가 글자까지 같은 쪽 텍스트를 가질 수는 없다.
    text = f"{PAGE_TEXT}\n합성 공고 식별 문장 {notice.notice_key}."
    page_text = json.dumps(
        {
            "schema": "bidops.prespec-v4-page-text.v1",
            "pages": [{"number": 1, "text": text, "text_sha256": _digest(text)}],
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    text_content, text_location = _object(
        session, store, namespace="structure", key=f"structure/{uuid4().hex}.json",
        data=page_text, mime="application/json",
    )
    snapshot = PrespecV4PdfSnapshot(
        id=uuid4(), notice_id=notice.id, document_version_id=document.id,
        source_content_object_id=source.id, source_location_id=source_location.id,
        pdf_content_object_id=source.id, pdf_location_id=source_location.id,
        page_text_content_object_id=text_content.id, page_text_location_id=text_location.id,
        source_kind="original", source_sha256=source.sha256, source_size_bytes=source.size_bytes,
        pdf_sha256=source.sha256, pdf_size_bytes=source.size_bytes, pdf_page_count=1,
        page_text_sha256=text_content.sha256, page_text_size_bytes=text_content.size_bytes,
        pdf_metadata_jsonb={"schema": "bidops.pdf-snapshot.v1"}, renderer_jsonb={"source_pdf": True},
        renderer_digest="a" * 64, font_jsonb={"source_pdf": True}, font_digest="b" * 64,
        config_jsonb={"options": {}}, config_sha256="c" * 64, scan_jsonb={"verdict": "clean"},
        binding_sha256="d" * 64,
    )
    session.add(snapshot)
    session.commit()
    return notice, document, snapshot


def _client_factory(transport: MockOverviewTransport):
    def factory(policy):
        return ModelClient.for_purpose(
            "overview",
            model=str(policy.document["model_name"]),
            output_contract=policy.structured_output_contract(CLAIMS_STAGE),
            settings=get_settings(),
            completion_create=transport.completion_create,
            models_list=transport.models_list,
        )
    return factory


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("BIDOPS_VLLM_OVERVIEW_MODEL_REVISION", "b" * 64)
    monkeypatch.setenv("BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY", "0" * 44)
    monkeypatch.setenv("BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY_REF", "test-key-ref")
    get_settings.cache_clear()
    monkeypatch.setattr(
        overview_runs, "effective_grades",
        lambda session, ids: {
            int(value): EffectiveGrade(int(value), "우선 검토", "screening_judgment")
            for value in ids
        },
    )
    monkeypatch.setattr(overview_runs, "EncryptedModelResponseStore", lambda _settings: _FakeResponseStore())
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    store = _FakeStore()
    with Session(engine) as session:
        yield session, store
    get_settings.cache_clear()
    engine.dispose()


def _run(session, store, transport, **kwargs):
    return overview_runs.run_once(
        session, "test-worker",
        settings=get_settings(),
        client_factory=_client_factory(transport),
        store=store,
        **kwargs,
    )


# --- enqueue -----------------------------------------------------------------


def test_enqueue_requires_flag_grade_bundle_and_no_active_run(context, monkeypatch):
    session, store = context
    notice, _document, _snapshot = seed(session, store)

    # (1) 플래그 off
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    assert overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings()) is None
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    get_settings.cache_clear()

    # (2) 등급이 `우선 검토`가 아니다
    monkeypatch.setattr(overview_runs, "effective_grades", lambda session, ids: {})
    assert overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings()) is None
    monkeypatch.setattr(
        overview_runs, "effective_grades",
        lambda session, ids: {
            int(value): EffectiveGrade(int(value), "우선 검토", "screening_judgment")
            for value in ids
        },
    )

    # (3) ready 묶음에 제안요청서가 없다
    other, _doc, _snap = seed(session, store, filename="합성-과업내용서.hwpx")
    assert overview_runs.enqueue_overview_run(session, other.id, settings=get_settings()) is None

    # (4) 네 조건이 모두 성립하면 run과 job이 함께 생긴다
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    session.commit()
    assert run is not None and run.status == "queued" and run.range_source == "auto"
    job = session.get(WorkJob, run.work_job_id)
    assert (job.job_type, job.aggregate_type, job.status) == ("prespec_overview", "prespec_overview_run", "queued")
    assert job.aggregate_id == run.id
    # 활성 run이 있으면 다시 넣지 않는다
    assert overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings()) is None


def test_the_flag_makes_sw_business_eligible_without_a_grade(context, monkeypatch):
    """MVP 완화: 플래그가 켜져 있으면 `SW사업대상=Y`도 자격이다 (2026-09-11).

    운영 DB에 C-1 판정이 0건이라 `우선 검토`가 한 건도 없다. 플래그가 꺼져 있으면
    완화는 없다.
    """

    session, store = context
    notice, _document, _snapshot = seed(session, store)
    notice.qualification_flags_json = {"sw_business_status": "Y"}
    session.commit()
    # 판정도 정정도 없는 상태를 만든다.
    monkeypatch.setattr(overview_runs, "effective_grades", lambda session, ids: {})

    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    session.commit()

    assert run is not None and run.status == "queued"

    # 플래그가 꺼지면 같은 공고가 다시는 자격을 얻지 못한다.
    session.delete(run)
    session.commit()
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    assert overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings()) is None


# --- 실행 --------------------------------------------------------------------


def test_run_once_completes_with_warnings_only_checks(context):
    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()

    result = _run(session, store, MockOverviewTransport(load_claims_policy().document["model_name"]))

    assert result.claimed is True and result.status == "completed"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "completed" and row.reason_codes == []
    assert row.range_source == "fallback"
    assert row.range_reason_codes[-1] == "range_fallback_head"
    assert (row.page_start, row.page_end) == (1, 1)
    assert row.call_count == 2 and len(row.raw_response_refs) == 2
    view = overview_runs.run_view(row)
    assert view["result"]["business_overview"][0]["evidence"][0]["page"] == 1
    assert view["failed_claims"] == []
    # 단위 없는 숫자 대조는 경고로만 남고 완료를 막지 않는다.
    # `context_unverified`는 mock 서버가 문맥 상한을 내지 않아서 붙는 표시다.
    assert view["warnings"] == ["context_unverified", "quantity_unit_missing"]
    assert row.checks_json["checks"][2]["deterministic"]["status"] == "passed"
    assert session.get(WorkJob, row.work_job_id).status == "completed"


def test_quote_not_found_sends_the_run_to_human_review(context):
    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()

    class _WrongQuote(MockOverviewTransport):
        def _draft(self, input_slice):
            draft = super()._draft(input_slice)
            draft["claims"][0]["evidence"][0]["quote"] = "원문에 없는 인용 문장이다."
            return draft

    result = _run(session, store, _WrongQuote(load_claims_policy().document["model_name"]))

    assert result.status == "needs_human_review"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "needs_human_review" and row.result_json is None
    failed = overview_runs.run_view(row)["failed_claims"]
    assert [item["claim_id"] for item in failed] == ["c1"]
    assert "quote_not_found" in failed[0]["reason_codes"]


def test_two_malformed_drafts_exhaust_the_format_retry(context):
    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()

    class _Malformed(MockOverviewTransport):
        def completion_create(self, **request):
            response = super().completion_create(**request)
            response["choices"][0]["message"]["content"] = "{"
            return response

    result = _run(session, store, _Malformed(load_claims_policy().document["model_name"]))

    assert result.status == "failed"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.reason_codes == ["draft_format_retry_exhausted"] and row.call_count == 2


def test_disabled_flag_cancels_queued_runs_without_touching_running(context, monkeypatch):
    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    session.commit()

    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    result = overview_runs.run_once(session, "test-worker", settings=get_settings(), store=store)

    assert result.claimed is False and result.reason_code == "overview_disabled"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "cancelled" and row.reason_codes == ["overview_disabled"]
    assert session.get(WorkJob, row.work_job_id).status == "cancelled"


def test_human_confirmed_range_is_used_verbatim(context):
    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(
        session, notice.id, range_source="human", page_start=1, page_end=1,
        actor_name="담당자", settings=get_settings(),
    )
    run.snapshot_id = snapshot.id
    session.commit()

    result = _run(session, store, MockOverviewTransport(load_claims_policy().document["model_name"]))

    assert result.status == "completed"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.range_source == "human" and row.range_reason_codes == []
    assert row.actor_name == "담당자"
    assert overview_runs.overview_envelope(session, notice.id)["current"]["id"] == str(row.id)


def test_enqueue_rejects_an_invalid_human_range(context):
    session, store = context
    notice, _document, _snapshot = seed(session, store)
    with pytest.raises(overview_runs.OverviewEnqueueError):
        overview_runs.enqueue_overview_run(
            session, notice.id, range_source="human", page_start=3, page_end=1,
            settings=get_settings(),
        )


def test_expired_lease_closes_the_running_run(context):
    session, store = context
    from datetime import UTC, datetime, timedelta

    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    job = session.get(WorkJob, run.work_job_id)
    run.status = "running"
    job.status = "running"
    job.lease_owner = "gone"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    session.commit()

    result = overview_runs.run_once(session, "test-worker", settings=get_settings(), store=store)

    assert result.expired_leases == 1
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "failed" and row.reason_codes == ["lease_expired"]
    assert not session.scalars(
        select(PrespecOverviewRun).where(PrespecOverviewRun.status.in_(overview_runs.ACTIVE_STATUSES))
    ).all()
