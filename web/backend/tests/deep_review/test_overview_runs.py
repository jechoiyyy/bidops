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
from app.core.model_client import ModelClient, ModelIdentityError
from app.core.models import AuditEvent
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
from app.deep_review.services.prespec_overview_claim_policy import CLAIMS_STAGE, LIMITS, load_claims_policy
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


def seed(session, store, *, bundle_ready: bool = True, filename: str = "합성-제안요청서.pdf",
         pages: list[str] | None = None, section_candidates: dict | None = None):
    """`우선 검토` 사전규격 한 건과 동결 스냅샷 하나를 세운다.

    `section_candidates`를 주면 그 산출물까지 함께 동결한다. 스냅샷은
    append-only라 나중에 매달 수 없다.
    """

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
    texts = [PAGE_TEXT] if pages is None else list(pages)
    texts[-1] = f"{texts[-1]}\n합성 공고 식별 문장 {notice.notice_key}."
    page_text = json.dumps(
        {
            "schema": "bidops.prespec-v4-page-text.v1",
            "pages": [
                {"number": number, "text": text, "text_sha256": _digest(text)}
                for number, text in enumerate(texts, 1)
            ],
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    text_content, text_location = _object(
        session, store, namespace="structure", key=f"structure/{uuid4().hex}.json",
        data=page_text, mime="application/json",
    )
    candidate_refs: dict = dict.fromkeys(
        ("section_candidates_content_object_id", "section_candidates_location_id", "section_candidates_sha256")
    )
    if section_candidates is not None:
        candidate_bytes = json.dumps(
            section_candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        candidate_content, candidate_location = _object(
            session, store, namespace="structure", key=f"structure/{uuid4().hex}.json",
            data=candidate_bytes, mime="application/json",
        )
        candidate_refs = {
            "section_candidates_content_object_id": candidate_content.id,
            "section_candidates_location_id": candidate_location.id,
            "section_candidates_sha256": candidate_content.sha256,
        }
    snapshot = PrespecV4PdfSnapshot(
        id=uuid4(), notice_id=notice.id, document_version_id=document.id,
        source_content_object_id=source.id, source_location_id=source_location.id,
        pdf_content_object_id=source.id, pdf_location_id=source_location.id,
        page_text_content_object_id=text_content.id, page_text_location_id=text_location.id,
        source_kind="original", source_sha256=source.sha256, source_size_bytes=source.size_bytes,
        pdf_sha256=source.sha256, pdf_size_bytes=source.size_bytes, pdf_page_count=len(texts),
        page_text_sha256=text_content.sha256, page_text_size_bytes=text_content.size_bytes,
        pdf_metadata_jsonb={"schema": "bidops.pdf-snapshot.v1"}, renderer_jsonb={"source_pdf": True},
        renderer_digest="a" * 64, font_jsonb={"source_pdf": True}, font_digest="b" * 64,
        config_jsonb={"options": {}}, config_sha256="c" * 64, scan_jsonb={"verdict": "clean"},
        binding_sha256="d" * 64, **candidate_refs,
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


def _range_of(session, store, pages: list[str]):
    """자동 선택 한 번의 (선택, 사유 코드)만 본다. 모델은 부르지 않는다."""

    notice, document, snapshot = seed(session, store, pages=pages)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()
    return overview_runs._select_range(session, run, snapshot, document, store=store)


def test_a_too_small_auto_range_is_not_frozen_and_falls_back_to_the_head(context):
    """목차·표제 한 쪽만 고른 자동 선택은 쓰지 않는다 (0911 공고 805)."""

    session, store = context

    selection, codes = _range_of(session, store, [
        "Ⅰ. 사업 개요\n1. 사업 목적\n본문 한 줄이다.\nⅡ. 제안요청 사항\n다음 장",
        "Ⅲ. 그 밖의 사항\n본문",
    ])

    # 목차 사유(`toc_missing`)는 fallback으로 갈 때만 본문 사유 뒤에 붙는다.
    assert codes == ["range_too_small", "toc_missing", "range_fallback_head"]
    assert selection.page_numbers == (1, 2)


def test_a_toc_confirmed_range_keeps_one_page_without_the_minimum_size_rule(context):
    """목차로 확정한 한 쪽짜리 개요 장은 최소 크기 규칙을 타지 않는다 (0916 공고 785)."""

    session, store = context

    selection, codes = _range_of(session, store, [
        "목 차\nⅠ. 사업 안내\t1\n 1. 사업개요\t1\nⅡ. 유지관리 대상\t2\n 1. 시스템 현황\t2\n",
        "Ⅰ. 사업 안내\n1. 사업개요\n짧은 본문이다.",
        "Ⅱ. 유지관리 대상\n1. 시스템 현황\n다음 장 본문이다.",
    ])

    assert selection.strategy == "toc_scope" and selection.page_numbers == (2,)
    assert codes == []


def test_an_over_limit_auto_range_is_clipped_and_stays_auto(context):
    """상한을 넘은 자동 선택은 버리지 않고 상한까지만 잘라 쓴다 (0911 공고 796)."""

    session, store = context
    body = ["Ⅰ. 사업 개요\n1. 사업 목적\n본문", *(["본문 계속"] * LIMITS["max_pages"]), "Ⅱ. 제안요청 사항\n다음 장"]

    selection, codes = _range_of(session, store, body)

    assert codes == ["range_clipped_to_limit"]
    assert "range_fallback_head" not in codes
    assert selection.page_numbers == tuple(range(1, LIMITS["max_pages"] + 1))


def test_quote_not_found_drops_one_claim_and_keeps_the_rest(context):
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

    # 네 주장 중 하나만 어긋났으므로 그 주장만 빼고 개요를 만든다 (2026-09-11).
    assert result.status == "completed"
    row = session.get(PrespecOverviewRun, run.id)
    view = overview_runs.run_view(row)
    failed = view["failed_claims"]
    assert [item["claim_id"] for item in failed] == ["c1"]
    assert "quote_not_found" in failed[0]["reason_codes"]
    assert view["result"]["business_overview"] == []
    assert "claims_dropped" in view["warnings"]


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


# --- claim 상한 --------------------------------------------------------------


def test_a_queued_run_at_the_attempt_cap_is_closed_instead_of_claimed(context):
    """시도를 다 쓴 queued run은 다시 잡지 않고 닫는다 (운영 205회 재점유)."""

    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    job = session.get(WorkJob, run.work_job_id)
    job.attempt_count = int(job.max_attempts)
    session.commit()

    result = overview_runs.run_once(session, "test-worker", settings=get_settings(), store=store)

    assert result.claimed is False and result.status == "idle"
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "failed" and row.reason_codes == ["attempts_exhausted"]
    job = session.get(WorkJob, run.work_job_id)
    assert job.status == "failed" and job.last_error_code == "attempts_exhausted"
    # 다시 잡지 않았으므로 counter는 그대로다.
    assert job.attempt_count == int(job.max_attempts) and job.lease_owner is None
    audits = session.scalars(
        select(AuditEvent).where(AuditEvent.action == overview_runs.ATTEMPTS_EXHAUSTED_ACTION)
    ).all()
    assert len(audits) == 1 and audits[0].aggregate_id == str(run.id)
    assert audits[0].actor_kind == "system" and audits[0].safe_metadata["notice_id"] == notice.id


def test_each_raw_response_ref_carries_the_call_measurements(context):
    """호출별 토큰·지연은 provider가 낸 사실이며 ref에 함께 남는다."""

    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()

    class _WithUsage(MockOverviewTransport):
        def completion_create(self, **request):
            response = super().completion_create(**request)
            response["usage"] = {"prompt_tokens": 1234, "completion_tokens": 56}
            return response

    result = _run(session, store, _WithUsage(load_claims_policy().document["model_name"]))

    assert result.status == "completed"
    refs = session.get(PrespecOverviewRun, run.id).raw_response_refs
    assert [ref["stage"] for ref in refs] == ["draft", "semantic"]
    for ref in refs:
        assert set(ref) == {"stage", "sha256", "prompt_tokens", "output_tokens", "latency_ms"}
        assert (ref["prompt_tokens"], ref["output_tokens"]) == (1234, 56)
        assert isinstance(ref["latency_ms"], int) and ref["latency_ms"] >= 0


def test_release_gives_back_the_attempt_the_claim_took(context):
    """일하지 않고 돌려놓는 release는 시도를 쓴 것이 아니다."""

    session, store = context
    notice, _document, _snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    session.commit()

    claimed = overview_runs._claim_next(session, "test-worker", overview_runs._now)
    assert claimed == run.id and session.get(WorkJob, run.work_job_id).attempt_count == 1

    overview_runs._release(
        session, session.get(PrespecOverviewRun, run.id), session.get(WorkJob, run.work_job_id)
    )
    session.commit()

    job = session.get(WorkJob, run.work_job_id)
    assert job.status == "queued" and job.attempt_count == 0 and job.lease_owner is None
    assert session.get(PrespecOverviewRun, run.id).status == "queued"


def test_identity_failures_spend_attempts_and_close_the_run_at_the_cap(context):
    """모델 신원 확인이 계속 막히면 상한만큼만 다시 잡고 닫는다."""

    session, store = context
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()
    cap = int(session.get(WorkJob, run.work_job_id).max_attempts)

    def factory(_policy):
        raise ModelIdentityError("identity_unavailable", retryable=True)

    results = [
        overview_runs.run_once(
            session, "test-worker", settings=get_settings(), client_factory=factory, store=store
        )
        for _ in range(cap)
    ]

    assert [item.status for item in results] == ["idle"] * (cap - 1) + ["failed"]
    assert all(item.identity_error is not None for item in results)
    assert all(item.identity_error.retryable is True for item in results)
    row = session.get(PrespecOverviewRun, run.id)
    assert row.status == "failed" and row.reason_codes == ["identity_unavailable"]
    job = session.get(WorkJob, run.work_job_id)
    assert job.status == "failed" and job.last_error_code == "identity_unavailable"
    assert job.attempt_count == cap


def test_the_operator_close_command_closes_one_active_run(context, monkeypatch, capsys):
    """`close-overview-run`은 queued를 취소로, running을 실패로 닫는다."""

    from app.core import db as core_db
    from app.deep_review.cli import main as deep_review_cli_main

    session, store = context
    notice, _document, _snapshot = seed(session, store)
    queued = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    session.commit()
    engine = session.get_bind()
    monkeypatch.setattr(core_db, "init_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(core_db, "SessionLocal", lambda: Session(engine))

    code = deep_review_cli_main([
        "close-overview-run", "--run-id", str(queued.id),
        "--reason", "operator_close", "--actor-name", "담당자",
    ])

    assert code == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {
        "notice_id": notice.id, "reason": "operator_close",
        "run_id": str(queued.id), "status": "cancelled",
    }
    session.expire_all()
    row = session.get(PrespecOverviewRun, queued.id)
    assert row.status == "cancelled" and row.reason_codes == ["operator_close"]
    job = session.get(WorkJob, row.work_job_id)
    assert job.status == "cancelled" and job.last_error_code == "operator_close"
    assert job.lease_owner is None and job.lease_expires_at is None
    audit = session.scalars(
        select(AuditEvent).where(AuditEvent.action == overview_runs.OPERATOR_CLOSE_ACTION)
    ).all()
    assert len(audit) == 1 and audit[0].claimed_name == "담당자"

    # 이미 종결된 run은 다시 닫지 않는다.
    assert deep_review_cli_main([
        "close-overview-run", "--run-id", str(queued.id), "--actor-name", "담당자",
    ]) == 2
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"error": "run_not_active"}

    # 실행 중이던 run은 실패로 닫는다 — 반쪽 결과가 남았을 수 있다.
    running = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    assert overview_runs._claim_next(session, "test-worker", overview_runs._now) == running.id
    assert deep_review_cli_main([
        "close-overview-run", "--run-id", str(running.id), "--actor-name", "담당자",
    ]) == 0
    session.expire_all()
    assert session.get(PrespecOverviewRun, running.id).status == "failed"
    assert session.get(WorkJob, running.work_job_id).status == "failed"


# --- 부분 완료 ---------------------------------------------------------------

#: 쪽 안에서 유일하고 서로 부분 문자열이 아닌 주장 후보 12줄.
CLAIM_LINES = [f"합성 개요 문장 {label}이다." for label in "가나다라마바사아자차카타"]


class _TwelveClaims(MockOverviewTransport):
    """12개 주장을 만들고 `broken` 자리만 원문에 없는 인용으로 바꾼다."""

    broken: tuple[int, ...] = ()

    def _draft(self, input_slice):
        sections = ("business_overview", "main_tasks", "budget_and_period")
        page = input_slice["blocks"][0]["pdf_page"]
        claims = [
            {
                "id": f"c{index + 1}", "section": sections[index % len(sections)], "text": line,
                "evidence": [{
                    "page": page,
                    "quote": "원문에 없는 인용 문장이다." if index in self.broken else line,
                }],
                "quantities": [],
            }
            for index, line in enumerate(CLAIM_LINES)
        ]
        return {"schema_version": "bidops.prespec-overview-claims.v1", "claims": claims}


def _run_twelve(session, store, broken: tuple[int, ...]):
    notice, _document, snapshot = seed(session, store, pages=["\n".join(CLAIM_LINES)])
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()
    transport = _TwelveClaims(load_claims_policy().document["model_name"])
    transport.broken = broken
    result = _run(session, store, transport)
    return result, session.get(PrespecOverviewRun, run.id)


def test_two_failed_claims_are_dropped_and_the_rest_completes(context):
    """12개 중 2개만 인용이 어긋나면 그 둘만 빼고 개요를 만든다 (2026-09-11)."""

    session, store = context

    result, row = _run_twelve(session, store, (1, 2))

    assert result.status == "completed"
    view = overview_runs.run_view(row)
    assert [item["claim_id"] for item in view["failed_claims"]] == ["c2", "c3"]
    assert all("quote_not_found" in item["reason_codes"] for item in view["failed_claims"])
    assert "claims_dropped" in set(view["warnings"])
    published = [
        item["claim_id"] for section in ("business_overview", "main_tasks", "budget_and_period")
        for item in view["result"][section]
    ]
    assert sorted(published) == sorted(f"c{n}" for n in range(1, 13) if n not in {2, 3})
    # 개요 결과에는 검토 의견·미확인 key가 없다 (ADR-0057 결정 1).
    assert set(view["result"]) == {
        "business_overview", "main_tasks", "budget_and_period", "input_limitations",
    }


def test_fewer_than_half_passing_claims_still_go_to_human_review(context):
    session, store = context

    result, row = _run_twelve(session, store, (0, 1, 2, 3, 4, 5, 6))

    assert result.status == "needs_human_review"
    assert row.reason_codes == ["deterministic_check_failed"] and row.result_json is None
    assert "claims_dropped" not in (row.warnings_json or [])


class _ExtraSemanticIds(MockOverviewTransport):
    """상한을 채우려고 기대 밖 ID를 덧붙이는 응답 (표본 5건 중 3건의 모양)."""

    def _semantic(self, input_slice):
        output = MockOverviewTransport._semantic(input_slice)
        output["checks"].extend(
            {"claim_id": extra, "status": "insufficient", "reason_codes": ["insufficient_evidence"]}
            for extra in ("A01", "U01")
        )
        return output


class _MissingSemanticId(MockOverviewTransport):
    def _semantic(self, input_slice):
        output = MockOverviewTransport._semantic(input_slice)
        output["checks"].pop()
        return output


class _ContradictedClaim(MockOverviewTransport):
    def _semantic(self, input_slice):
        output = MockOverviewTransport._semantic(input_slice)
        output["checks"][0].update(status="contradicted", reason_codes=["unsupported_fact"])
        return output


def _run_with(session, store, transport_class):
    notice, _document, snapshot = seed(session, store)
    run = overview_runs.enqueue_overview_run(session, notice.id, settings=get_settings())
    run.snapshot_id = snapshot.id
    session.commit()
    result = _run(session, store, transport_class(load_claims_policy().document["model_name"]))
    return result, session.get(PrespecOverviewRun, run.id)


def test_extra_semantic_ids_only_warn_and_the_run_completes(context):
    """기대 ID가 모두 한 번씩 있으면 그 밖의 판정은 무시한다 (ADR-0057 결정 3)."""

    session, store = context

    result, row = _run_with(session, store, _ExtraSemanticIds)

    assert result.status == "completed"
    view = overview_runs.run_view(row)
    assert "semantic_extra_ids" in view["warnings"]
    assert view["failed_claims"] == [] and row.reason_codes == []


def test_a_missing_semantic_id_closes_the_run_with_its_own_reason_code(context):
    session, store = context

    result, row = _run_with(session, store, _MissingSemanticId)

    assert result.status == "failed"
    assert row.reason_codes == ["semantic_missing_ids"] and row.result_json is None


def test_a_contradicted_claim_still_sends_the_run_to_human_review(context):
    session, store = context

    result, row = _run_with(session, store, _ContradictedClaim)

    assert result.status == "needs_human_review"
    assert row.reason_codes == ["semantic_review_failed"] and row.result_json is None
    assert [item["claim_id"] for item in overview_runs.run_view(row)["failed_claims"]] == ["c1"]


def test_range_review_reports_unavailable_candidates(context):
    """0024 이전 스냅샷에는 절 후보가 없다. 없는 것을 부분 후보로 만들지 않는다."""

    session, store = context
    notice, _document, _snapshot = seed(session, store)

    review = overview_runs.overview_envelope(session, notice.id)["range_review"]

    assert review["candidate_status"] == "unavailable" and review["candidates"] == []
    assert review["candidate_count_total"] is None and review["candidate_count_returned"] == 0
    assert review["warning_codes"] == ["section_candidates_unavailable"]
    assert review["reason_code"] == "section_candidates_unavailable"
    # run이 아직 없으므로 확정 대기다.
    assert review["status"] == "pending" and review["target_id"] is None
    assert review["confirmation"] is None
