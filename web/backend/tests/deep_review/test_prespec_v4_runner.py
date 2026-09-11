"""Focused v4 attempt/current projection contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.object_store import FilesystemObjectStore
from app.core.model_client import (
    ModelClient, ModelIdentity, ModelIdentityError, ModelInvocationError,
    PromptTooLargeError,
)
from app.deep_review.document_mcp.processor import ProcessedDocument
from app.deep_review.models import (
    ContentObject, DocumentVersion, PreSpecPageOverview, PrespecOverviewCallEvent,
    PrespecOverviewVerification, PrespecV4Attempt,
)
from app.deep_review.services.page_overview import list_page_overviews
from app.deep_review.services.prespec_v4 import freeze_v4_target, prepare_v4_pdf_snapshot, select_v4_input_range
from app.deep_review.services.prespec_v4_runner import (
    V4_LEGACY_POLICY_PATH,
    V4ModelBinding,
    current_v4_projections,
    enqueue_v4_attempt,
    load_v4_policy,
    PrespecV4OverviewRunner,
    record_v4_preparation_failure,
)
from app.deep_review.services.prespec_v4_ops import (
    ACTIVATION_SCHEMA, _execution_approval, activate_v4, deactivate_v4,
)
import app.deep_review.services.prespec_v4_runner as runner_module

from .test_prespec_v4_preparation import (
    _Converter,
    _engine,
    _processed,
    _selection,
    _sha,
    _source,
    _SOURCE_FONT,
    _SOURCE_RENDERER,
)


class _RawStore:
    def __init__(self):
        self.calls: list[bytes] = []

    def put_encrypted(self, data: bytes, *, retention_days: int, content_type: str):
        del retention_days, content_type
        self.calls.append(data)
        return {
            "object_key": f"model-response/v4-{len(self.calls)}.raw",
            "object_version_id": "v1",
            "etag": _sha(data),
            "plaintext_sha256": _sha(data),
            "plaintext_size_bytes": len(data),
            "encryption_key_ref": "test-key",
        }


class _Client:
    """호출별 응답을 순서대로 낸다. 마지막 응답은 이후 호출에서 반복된다.

    응답 자리에 예외를 두면 그 호출이 그 예외를 던진다.
    """

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.inputs = []
        self.calls = []
        self.model_context_tokens = 262_144

    def invoke(self, stage, input_slice, policy, *, seed=None, correction=None, **_kwargs):
        self.inputs.append((stage, input_slice, policy))
        self.calls.append({"seed": seed, "correction": correction})
        output = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(
            structured_output=output,
            raw_response=_raw(output),
            prompt_tokens=2,
            output_tokens=3,
            latency_ms=4,
        )


def _raw(output):
    return json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _audit_metadata(session, attempt_id):
    from app.core.models import AuditEvent

    rows = list(session.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "prespec_v4.attempt_run", AuditEvent.aggregate_id == str(attempt_id))
    ))
    assert len(rows) == 1
    return rows[0].safe_metadata


def _mislocated(pages):
    payload = _payload()
    payload["business_overview"] = [{"text": "목적", "evidence_pages": [page] } for page in pages]
    return payload


@pytest.fixture(autouse=True)
def _current_model_binding(monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "resolve_model_endpoint",
        lambda _purpose: SimpleNamespace(model_revision="a" * 64),
    )


def _payload():
    return {
        "schema_version": "bidops.prespec-overview-page-review.v3",
        "business_overview": [{"text": "목적", "evidence_pages": [2]}],
        "main_tasks": [{"text": "범위", "evidence_pages": [2]}],
        "budget_and_period": [],
        "important_conditions": [],
        "reviewer_analysis": ["선택 페이지에 한정"],
        "unknowns": ["미확인"],
        "input_limitations": ["page_text_only"],
    }


# 개요 범위가 2~3쪽에 걸친 구조. 검토 페이지가 둘 이상이어야 선언 페이지와 문장 끝
# `(PDF N페이지)` 표기가 갈리는 경고 조건이 성립한다.
_SPREAD_PAGES = (
    "목차\nⅠ. 감리 개요\nⅡ. 제안요청 사항",
    "Ⅰ. 감리 개요\n1. 목적\n본문",
    "2. 범위\n감리 범위\nⅡ. 제안요청 사항\n다음 장",
)


def _spread_processed(source):
    base = _processed(source)
    payload = dict(base)
    payload["pages"] = [
        {"number": number, "width": 612.0, "height": 792.0, "image_content_object_id": None}
        for number, _text in enumerate(_SPREAD_PAGES, 1)
    ]
    payload["blocks"] = [
        {"block_key": f"page-{number}-text", "page": number, "type": "text", "text": text,
         "bbox": [0, 0, 612, 792], "confidence": 1.0, "attributes": {}}
        for number, text in enumerate(_SPREAD_PAGES, 1)
    ]
    return ProcessedDocument(
        payload,
        original_bytes=source,
        converted_pdf_bytes=None,
        pdf_metadata={
            **base.pdf_metadata,
            "page_count": len(_SPREAD_PAGES),
            "pages": [
                {"number": number, "width": 612.0, "height": 792.0, "text_sha256": _sha(text.encode())}
                for number, text in enumerate(_SPREAD_PAGES, 1)
            ],
        },
    )


def _spread_selection(document, source):
    return select_v4_input_range({
        "document_version_id": str(document.id),
        "source_sha256": _sha(source),
        "pages": [{"number": number, "text": text} for number, text in enumerate(_SPREAD_PAGES, 1)],
        "blocks": [],
    })


def _ready_target(tmp_path, *, spread=False):
    source = b"%PDF-1.7\nfixture-original"
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    session = Session(engine)
    document, source_location = _source(session, store, source)
    from app.lifecycle.models import Notice
    session.get(Notice, document.notice_id).source_type = "pre_spec"
    session.commit()
    snapshot = prepare_v4_pdf_snapshot(
        session,
        document_version_id=document.id,
        source_location_id=source_location.id,
        source_bytes=source,
        media_type="application/pdf",
        converter=_Converter(_spread_processed(source) if spread else _processed(source), lambda _value: True),
        store=store,
        options={"prepare_pdf": True},
        renderer=_SOURCE_RENDERER,
        font=_SOURCE_FONT,
        config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
        scanner=lambda _value: True,
    )
    selection = _spread_selection(document, source) if spread else _selection(document, source)
    metadata = store.put("structure", "structure/v4/manifest.json", selection.manifest_bytes, content_type="application/json")
    from app.deep_review.models import ContentObject, ContentObjectLocation

    content = ContentObject(sha256=_sha(selection.manifest_bytes), size_bytes=len(selection.manifest_bytes), detected_mime="application/json", retention_class="prespec-v4-input")
    session.add(content)
    session.flush()
    location = ContentObjectLocation(content_object_id=content.id, namespace_key="structure", object_key=metadata.object_key, object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified")
    session.add(location)
    session.flush()
    target = freeze_v4_target(session, snapshot_id=snapshot.id, observation_kind="explicit_sample", observation_id=None, observation_reference={"sample": "test"}, selection=selection, manifest_content_object_id=content.id, manifest_location_id=location.id, manifest_bytes=selection.manifest_bytes)
    session.commit()
    return engine, session, store, target


def _manifest_fixture(page_texts):
    document_version_id = uuid4()
    pages = [
        {"number": number, "text": value, "text_sha256": _sha(value.encode())}
        for number, value in enumerate(page_texts, 1)
    ]
    input_payload = {
        "schema_version": runner_module.V4_MANIFEST_SCHEMA,
        "document_version_id": str(document_version_id),
        "source_sha256": "a" * 64,
        "pages": pages,
        "block_keys": [],
        "start_locator": {"block_key": "start", "page": 1, "ordinal": 0},
        "end_locator": {"block_key": "end", "page": len(pages), "ordinal": 1},
        "input_limitations": ["page_text_only"],
    }
    manifest = {
        **input_payload,
        "selection_status": "ready",
        "strategy": "fixture",
    }
    raw = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    content = SimpleNamespace(
        id=uuid4(), detected_mime="application/json", size_bytes=len(raw)
    )
    target = SimpleNamespace(
        manifest_content_object_id=content.id,
        manifest_location_id=uuid4(),
        selection_manifest_sha256=_sha(raw),
        input_byte_count=len(raw),
        input_sha256=runner_module._sha256_json(input_payload),
        document_version_id=document_version_id,
    )
    session = SimpleNamespace(get=lambda _model, _id: content)
    return session, target, raw


@pytest.mark.parametrize("blank_page", [" \n\t     ", "\n        "], ids=["8-chars", "9-chars"])
def test_manifest_preserves_one_whitespace_only_page_when_other_page_has_body(
    monkeypatch, blank_page
):
    session, target, raw = _manifest_fixture((blank_page, "본문은 그대로 유지한다."))
    monkeypatch.setattr(runner_module, "_verified_location", lambda *_args: object())
    monkeypatch.setattr(runner_module, "_read_verified_artifact", lambda *_args, **_kwargs: raw)

    manifest, pages = runner_module._load_manifest(session, object(), target)

    assert pages == {1: blank_page, 2: "본문은 그대로 유지한다."}
    assert manifest["pages"][0]["text"] == blank_page
    assert manifest["pages"][0]["text_sha256"] == _sha(blank_page.encode())


def test_manifest_rejects_when_every_selected_page_is_whitespace_only(monkeypatch):
    session, target, raw = _manifest_fixture((" \n\t     ", "\u3000\n"))
    monkeypatch.setattr(runner_module, "_verified_location", lambda *_args: object())
    monkeypatch.setattr(runner_module, "_read_verified_artifact", lambda *_args, **_kwargs: raw)

    with pytest.raises(runner_module.V4AttemptError, match="manifest_invalid"):
        runner_module._load_manifest(session, object(), target)


def _activate_for_target(session, target, binding):
    snapshot = session.get(runner_module.PrespecV4PdfSnapshot, target.snapshot_id)
    assert snapshot is not None
    activate_v4(
        session,
        actor="v4-test",
        mode="explicit_sample",
        artifact={
            "schema": "bidops.prespec-v4-activation.v1",
            "version": 1,
            "samples": [{
                "notice_id": target.notice_id,
                "notice_key": "pre:test",
                "document_version_id": str(target.document_version_id),
                "source_sha256": snapshot.source_sha256,
                "source_size_bytes": snapshot.source_size_bytes,
                "original_filename": "fixture_제안요청서.pdf",
            }],
            "automatic_requirements": {},
        },
        binding=binding,
        settings=SimpleNamespace(reference_workflow_mode=True, analysis_provider="vllm", prespec_overview_policy_path=V4_LEGACY_POLICY_PATH),
    )


def _activate_v5_for_target(session, target, binding, policy):
    snapshot = session.get(runner_module.PrespecV4PdfSnapshot, target.snapshot_id)
    assert snapshot is not None
    activate_v4(
        session, actor="v5-test", mode="explicit_sample",
        artifact={
            "schema": ACTIVATION_SCHEMA, "version": 2,
            "samples": [{
                "notice_id": target.notice_id, "notice_key": "pre:test",
                "document_version_id": str(target.document_version_id),
                "source_sha256": snapshot.source_sha256,
                "source_size_bytes": snapshot.source_size_bytes,
                "target_id": str(target.id), "input_sha256": target.input_sha256,
                "selection_manifest_sha256": target.selection_manifest_sha256,
                "pdf_sha256": snapshot.pdf_sha256,
            }],
            "automatic_requirements": {},
            "execution": _execution_approval(policy),
        },
        binding=binding,
        settings=SimpleNamespace(
            reference_workflow_mode=True, analysis_provider="vllm",
            prespec_overview_policy_path=None,
        ),
    )


def _claims_draft():
    return {
        "schema_version": "bidops.prespec-overview-claims.v1",
        "claims": [
            {"id": "business", "section": "business_overview", "text": "감리 개요",
             "evidence": [{"page": 2, "quote": "감리 개요"}], "quantities": []},
            {"id": "task", "section": "main_tasks", "text": "감리 범위",
             "evidence": [{"page": 2, "quote": "감리 범위"}], "quantities": []},
        ],
        "analysis": [], "unknowns": [],
    }


def _semantic(*, second_status="supported"):
    return {
        "schema_version": "bidops.prespec-overview-semantic.v1",
        "checks": [
            {"claim_id": "business", "status": "supported", "reason_codes": []},
            {"claim_id": "task", "status": second_status,
             "reason_codes": [] if second_status == "supported" else ["insufficient_evidence"]},
        ],
        "analysis_checks": [], "unknown_checks": [],
    }


def _queued_v5(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy()
    binding = V4ModelBinding(
        provider="test", model_name=policy.model_name, model_digest="a" * 64,
        prompt_version=policy.prompt_version, policy_digest=policy.digest,
        reference_only=True,
    )
    _activate_v5_for_target(session, target, binding, policy)
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    return engine, session, store, target, policy, binding, attempt


def test_v4_policy_keeps_reference_instructions_and_examples() -> None:
    root = Path(__file__).resolve().parents[4]
    reference = json.loads(
        (root / "experiments/prespec-overview-pdf-reference/policy.json").read_text(
            encoding="utf-8"
        )
    )
    policy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    for key in (
        "chunking",
        "generation",
        "output_schema",
        "system_prompt",
        "prompt_output_contract",
        "stages",
    ):
        assert policy.document[key] == reference[key]
    assert policy.document["schema"] == "bidops.prespec-overview-policy.v4"
    assert policy.document["model_name"] == "qwen3.8-27B"
    assert policy.document["prompt_version"] == "prespec-overview-v4"
    assert (
        root / "web/backend/app/deep_review/policies/prespec-overview-prompt-v4.md"
    ).read_text(encoding="utf-8") == (
        root / "experiments/prespec-overview-pdf-reference/prompt-v4.md"
    ).read_text(encoding="utf-8")
    assert policy.document["prompt_output_contract"]["few_shot_examples"]
    assert "blocks" in policy.document["prompt_output_contract"]["evidence_rule"]


def test_v4_runner_stores_page_result_and_current_pointer(tmp_path, monkeypatch):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    binding = V4ModelBinding(provider="test", model_name=policy.model_name, model_digest="a" * 64, prompt_version=policy.prompt_version, policy_digest=policy.digest, reference_only=True)
    client = _Client(_payload())
    _activate_for_target(session, target, binding)
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    again = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    assert again.id == attempt.id
    session.commit()

    result = PrespecV4OverviewRunner(client=client, binding=binding, policy=policy, raw_response_store=_RawStore(), object_store=store).run_once(session, "v4-test-worker")
    assert result.status == "completed"
    row = session.scalar(select(PrespecV4Attempt).where(PrespecV4Attempt.id == attempt.id))
    assert row is not None and row.status == "completed" and row.result_id is not None
    assert session.scalar(select(PreSpecPageOverview).where(PreSpecPageOverview.id == row.result_id)) is not None
    assert client.inputs[0][1]["blocks"][0]["pdf_page"] == 2
    assert "source_sha256" not in client.inputs[0][1]
    response = list_page_overviews(session, target.notice_id)
    assert response.current is not None
    assert response.current.status == "completed"
    assert response.current.result_id == row.result_id
    monkeypatch.setattr(
        runner_module,
        "resolve_model_endpoint",
        lambda _purpose: SimpleNamespace(model_revision="b" * 64),
    )
    stale_binding = list_page_overviews(session, target.notice_id).current
    assert stale_binding is not None and stale_binding.status == "stale"
    monkeypatch.setattr(
        runner_module,
        "resolve_model_endpoint",
        lambda _purpose: SimpleNamespace(model_revision="a" * 64),
    )
    document = session.get(DocumentVersion, target.document_version_id)
    assert document is not None
    document.is_current = False
    session.commit()
    stale = list_page_overviews(session, target.notice_id).current
    assert stale is not None and stale.status == "stale" and stale.result_id is None
    session.close()
    engine.dispose()


def test_v4_dispatch_scopes_legacy_exclusion_to_v4_documents(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    session.execute(
        update(runner_module.PrespecV4Target)
        .where(runner_module.PrespecV4Target.id == target.id)
        .values(selection_status="excluded", reason_code="synthetic_exclusion")
    )
    session.commit()

    class _Legacy:
        def __init__(self):
            self.calls = 0
            self.excluded = set()

        def run_once(self, _session, _worker_id, *, excluded_document_version_ids=()):
            self.calls += 1
            self.excluded = set(excluded_document_version_ids)
            return SimpleNamespace(status="legacy", claimed=True)

    legacy = _Legacy()
    result = PrespecV4OverviewRunner(legacy_runner=legacy, object_store=store).run_once(
        session, "v4-test-worker"
    )
    assert result.status == "legacy"
    assert legacy.calls == 1
    assert target.document_version_id in legacy.excluded
    assert session.scalar(select(PrespecV4Attempt).where(PrespecV4Attempt.target_id == target.id)) is None
    session.close()
    engine.dispose()


def test_current_v4_projection_does_not_hide_database_failure() -> None:
    """projection DB 오류를 빈 과거 상태로 낮추지 않고 호출자에게 전파한다."""

    class _BrokenSession:
        def scalars(self, _statement):
            raise SQLAlchemyError("synthetic database failure")

    with pytest.raises(SQLAlchemyError, match="synthetic database failure"):
        current_v4_projections(_BrokenSession(), [101])  # type: ignore[arg-type]


def test_v4_identity_success_cache_is_rebuilt_after_endpoint_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v4 성공 binding도 endpoint fingerprint가 바뀌면 새로 확인한다."""

    policy = load_v4_policy()
    settings = SimpleNamespace(
        vllm_base_url="http://127.0.0.1:8000/v1",
        vllm_allowed_hosts="127.0.0.1",
        vllm_api_key="first-synthetic-key",
        vllm_model_revision="a" * 64,
        vllm_overview_api_dialect="vllm",
    )
    built: list[object] = []
    closed: list[object] = []

    class _IdentityClient:
        def verify_identity(self):
            return ModelIdentity(
                model=policy.model_name,
                revision="a" * 64,
                max_model_len=262_144,
            )

        def close(self):
            closed.append(self)

    def _for_purpose(*_args, **_kwargs):
        client = _IdentityClient()
        built.append(client)
        return client

    monkeypatch.setattr(runner_module.ModelClient, "for_purpose", _for_purpose)
    runner = PrespecV4OverviewRunner(policy=policy, settings=settings)
    first = runner._resolve()
    assert first[0] is not None and first[1] is built[0]
    assert runner._resolve() == first
    assert len(built) == 1

    settings.vllm_api_key = "second-synthetic-key"
    second = runner._resolve()
    assert second[0] is not None and second[1] is built[1]
    assert len(built) == 2
    assert closed == [built[0]]


def test_v4_dispatch_keeps_legacy_default_when_no_v4_boundary(tmp_path):
    engine = _engine()
    session = Session(engine)

    class _Legacy:
        def __init__(self):
            self.excluded = None

        def run_once(self, _session, _worker_id, *, excluded_document_version_ids=()):
            self.excluded = set(excluded_document_version_ids)
            return SimpleNamespace(status="legacy", claimed=True)

    legacy = _Legacy()
    result = PrespecV4OverviewRunner(legacy_runner=legacy).run_once(
        session, "v4-test-worker"
    )
    assert result.status == "legacy"
    assert legacy.excluded == set()
    session.close()
    engine.dispose()


def test_v4_validation_failure_keeps_encrypted_raw_and_no_result(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    binding = V4ModelBinding(provider="test", model_name=policy.model_name, model_digest="a" * 64, prompt_version=policy.prompt_version, policy_digest=policy.digest, reference_only=True)
    _activate_for_target(session, target, binding)
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    run = PrespecV4OverviewRunner(client=_Client({"schema_version": "wrong"}), binding=binding, policy=policy, raw_response_store=_RawStore(), object_store=store).run_once(session, "v4-test-worker")
    assert run.status == "failed"
    row = session.get(PrespecV4Attempt, attempt.id)
    expected_raw = json.dumps({"schema_version": "wrong"}, sort_keys=True, separators=(",", ":")).encode()
    assert row is not None and row.status == "failed" and row.result_id is None and row.raw_response_sha256 == _sha(expected_raw)
    assert session.scalar(select(ContentObject).where(ContentObject.sha256 == row.raw_response_sha256)) is not None
    session.close()
    engine.dispose()


def _queued(tmp_path, *, spread=False):
    engine, session, store, target = _ready_target(tmp_path, spread=spread)
    policy = load_v4_policy(V4_LEGACY_POLICY_PATH)
    binding = V4ModelBinding(provider="test", model_name=policy.model_name, model_digest="a" * 64,
                             prompt_version=policy.prompt_version, policy_digest=policy.digest, reference_only=True)
    _activate_for_target(session, target, binding)
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    return engine, session, store, target, policy, binding, attempt


def _run(session, store, policy, binding, client, raw_store):
    return PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy, raw_response_store=raw_store, object_store=store
    ).run_once(session, "v4-test-worker")


def test_v4_validation_failure_retries_once_with_correction_and_completes(tmp_path):
    engine, session, store, target, policy, binding, attempt = _queued(tmp_path)
    first, raw_store = _mislocated([99]), _RawStore()
    client = _Client(first, _payload())

    result = _run(session, store, policy, binding, client, raw_store)

    assert result.status == "completed"
    row = session.get(PrespecV4Attempt, attempt.id)
    assert row is not None and row.status == "completed" and row.result_id is not None
    # 마지막 응답이 행의 원본이고, 두 응답 모두 암호화 저장을 거쳤다.
    assert row.raw_response_sha256 == _sha(_raw(_payload()))
    assert raw_store.calls == [_raw(first), _raw(_payload())]
    assert len(client.calls) == 2
    assert client.calls[0] == {"seed": None, "correction": None}
    assert client.calls[1]["seed"] == 1
    assert "pdf_locator_mismatch" in client.calls[1]["correction"]
    # 재시도는 같은 입력을 다시 보낸다.
    assert client.inputs[0][1] == client.inputs[1][1]
    retry = _audit_metadata(session, attempt.id)["validation_retry"]
    assert retry == {
        "count": 1,
        "first_error_codes": ["pdf_locator_mismatch"],
        "first_raw_response_sha256": _sha(_raw(first)),
        "seed": 1,
        "correction_sha256": hashlib.sha256(client.calls[1]["correction"].encode("utf-8")).hexdigest(),
    }
    session.close()
    engine.dispose()


def test_v4_second_validation_failure_stays_failed_with_the_retry_code(tmp_path):
    engine, session, store, target, policy, binding, attempt = _queued(tmp_path)
    first, second, raw_store = _mislocated([99]), _mislocated([98]), _RawStore()

    result = _run(session, store, policy, binding, _Client(first, second), raw_store)

    assert result.status == "failed" and result.reason_code == "pdf_locator_mismatch"
    row = session.get(PrespecV4Attempt, attempt.id)
    assert row is not None and row.status == "failed" and row.result_id is None
    assert row.error_code == "pdf_locator_mismatch"
    assert row.raw_response_sha256 == _sha(_raw(second))
    assert raw_store.calls == [_raw(first), _raw(second)]
    retry = _audit_metadata(session, attempt.id)["validation_retry"]
    assert retry["count"] == 1 and retry["first_raw_response_sha256"] == _sha(_raw(first))
    session.close()
    engine.dispose()


def test_v4_prompt_rejection_and_transport_failure_never_retry(tmp_path):
    from app.core.model_client import ModelInvocationError, PromptTooLargeError

    for failure, code in ((PromptTooLargeError("too large"), "prompt_rejected"),
                          (ModelInvocationError("timeout", ()), "timeout")):
        workspace = tmp_path / code
        workspace.mkdir()
        engine, session, store, target, policy, binding, attempt = _queued(workspace)
        client = _Client(failure)

        result = _run(session, store, policy, binding, client, _RawStore())

        assert result.status == "failed" and result.reason_code == code
        assert len(client.calls) == 1
        row = session.get(PrespecV4Attempt, attempt.id)
        assert row is not None and row.error_code == code and row.result_id is None
        assert _audit_metadata(session, attempt.id)["validation_retry"] is None
        session.close()
        engine.dispose()


def test_preparation_failure_is_the_current_safe_state(tmp_path):
    engine = _engine()
    store = FilesystemObjectStore(tmp_path)
    session = Session(engine)
    document, _location = _source(session, store, b"%PDF-1.7\nnot-prepared")
    from app.lifecycle.models import Notice
    session.get(Notice, document.notice_id).source_type = "pre_spec"
    failed = record_v4_preparation_failure(session, notice_id=document.notice_id, document_version_id=document.id, error_code="pdf_preparation_failed")
    session.commit()
    current = list_page_overviews(session, document.notice_id).current
    assert current is not None and current.attempt_id == failed.id and current.status == "failed" and current.result_id is None
    assert current.reason_code == "pdf_preparation_failed"
    session.close()
    engine.dispose()


def test_v4_completed_attempt_keeps_inline_locator_warning(tmp_path):
    engine, session, store, target, policy, binding, attempt = _queued(tmp_path, spread=True)
    payload = _payload()
    # 선언 페이지는 2쪽, 읽기용 표기는 3쪽이다. 둘 다 검토한 페이지 안이므로 실패가 아니라 경고다.
    payload["business_overview"] = [{"text": "목적 (PDF 3페이지)", "evidence_pages": [2]}]
    payload["main_tasks"] = [{"text": "범위", "evidence_pages": [3]}]
    client = _Client(payload)

    result = _run(session, store, policy, binding, client, _RawStore())

    assert result.status == "completed"
    assert len(client.calls) == 1
    row = session.get(PrespecV4Attempt, attempt.id)
    assert row is not None and row.status == "completed" and row.result_id is not None
    assert row.validation_warnings == ["pdf_inline_locator_normalized"]
    assert _audit_metadata(session, attempt.id)["validation_warnings"] == ["pdf_inline_locator_normalized"]
    session.close()
    engine.dispose()


def test_v4_completed_attempt_records_empty_warning_list(tmp_path):
    engine, session, store, target, policy, binding, attempt = _queued(tmp_path)

    result = _run(session, store, policy, binding, _Client(_payload()), _RawStore())

    assert result.status == "completed"
    row = session.get(PrespecV4Attempt, attempt.id)
    assert row is not None and row.status == "completed"
    assert row.validation_warnings == []
    assert _audit_metadata(session, attempt.id)["validation_warnings"] == []
    session.close()
    engine.dispose()


def test_v5_claims_semantic_and_compose_are_ledgered_atomically(tmp_path):
    engine, session, store, target, policy, binding, attempt = _queued_v5(tmp_path)
    client = _Client(_claims_draft(), _semantic())

    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    assert result.status == "completed"
    row = session.get(PrespecV4Attempt, attempt.id)
    verification = session.scalar(select(PrespecOverviewVerification).where(
        PrespecOverviewVerification.attempt_id == attempt.id
    ))
    overview = session.get(PreSpecPageOverview, row.result_id)
    events = session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id
    ).order_by(PrespecOverviewCallEvent.ordinal, PrespecOverviewCallEvent.event_kind)).all()
    assert row.status == "completed" and row.activation_id is not None
    assert verification is not None and verification.overall == "passed"
    assert overview is not None and overview.schema_version == "bidops.prespec-overview-page-review.v4"
    assert overview.input_sha256 == attempt.input_sha256
    assert [(event.ordinal, event.stage, event.event_kind) for event in events] == [
        (1, "draft", "dispatch"), (1, "draft", "response"),
        (2, "semantic", "dispatch"), (2, "semantic", "response"),
    ]
    assert all(event.input_sha256 == attempt.input_sha256 for event in events)
    assert len({event.prompt_sha256 for event in events if event.event_kind == "dispatch"}) == 2
    current = runner_module.current_v4_projection(session, target.notice_id)
    assert current is not None
    assert current["status"] == "completed" and current["result_id"] == overview.id
    session.close()
    engine.dispose()


def test_v5_factual_failure_stops_before_semantic_and_needs_human(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    draft = _claims_draft()
    draft["claims"][0]["evidence"][0]["quote"] = "없는 문장"
    client = _Client(draft)

    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    verification = session.scalar(select(PrespecOverviewVerification).where(
        PrespecOverviewVerification.attempt_id == attempt.id
    ))
    assert result.status == "needs_human_review"
    assert row.status == "needs_human_review" and row.result_id is None
    assert verification is not None and verification.overall == "needs_human_review"
    assert len(client.calls) == 1
    session.close()
    engine.dispose()


def test_v5_format_only_retry_is_bounded_to_three_total_calls(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    malformed = {**_claims_draft(), "unexpected": True}
    client = _Client(malformed, _claims_draft(), _semantic())

    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    assert result.status == "completed" and len(client.calls) == 3
    dispatches = session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id,
        PrespecOverviewCallEvent.event_kind == "dispatch",
    ).order_by(PrespecOverviewCallEvent.ordinal)).all()
    assert [(event.ordinal, event.stage) for event in dispatches] == [
        (1, "draft"), (2, "draft"), (3, "semantic")
    ]
    session.close()
    engine.dispose()


def test_v5_second_draft_factual_failure_becomes_human_review(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    malformed = {**_claims_draft(), "unexpected": True}
    factual_failure = {
        "schema_version": "bidops.prespec-overview-claims.v1",
        "claims": [], "analysis": [], "unknowns": [],
    }
    client = _Client(malformed, factual_failure)

    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    assert result.status == "needs_human_review"
    assert row.status == "needs_human_review" and row.result_id is None
    assert len(client.calls) == 2
    session.close()
    engine.dispose()


def test_v5_real_model_client_retries_malformed_draft_once(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    contents = ["not-json", _raw(_claims_draft()).decode(), _raw(_semantic()).decode()]
    schemas = []

    def _completion_create(**kwargs):
        schemas.append(kwargs["response_format"]["json_schema"]["name"])
        return {
            "model": policy.model_name,
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": contents.pop(0)},
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }

    client = ModelClient(
        model=policy.model_name, model_revision="a" * 64,
        output_contract=policy.output_contract,
        allowed_hosts="127.0.0.1", completion_create=_completion_create,
    )
    # The injected binding stands in for identity verification in this transport
    # fixture; provide its confirmed context too, without a live /models call.
    client.model_context_tokens = 262_144
    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    assert result.status == "completed"
    assert len(schemas) == 3
    assert schemas[0] == schemas[1] and schemas[2] != schemas[0]
    session.close()
    engine.dispose()


@pytest.mark.parametrize(
    "semantic,status,reason",
    [
        ({"schema_version": "wrong", "checks": []}, "failed", "semantic_response_invalid"),
        (_semantic(second_status="insufficient"), "needs_human_review", "claim_verification_required"),
    ],
)
def test_v5_semantic_failure_classification(tmp_path, semantic, status, reason):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    result = PrespecV4OverviewRunner(
        client=_Client(_claims_draft(), semantic), binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    assert result.status == status and result.reason_code == reason
    assert row.status == status and row.result_id is None
    session.close()
    engine.dispose()


@pytest.mark.parametrize(
    "client,raw_store,reason",
    [
        (_Client(ModelInvocationError("timeout", ())), _RawStore(), "timeout"),
        (_Client(_claims_draft()), SimpleNamespace(put_encrypted=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic"))), "response_store_unavailable"),
    ],
)
def test_v5_transport_and_raw_store_fail_without_retry(tmp_path, client, raw_store, reason):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=raw_store, object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    assert result.status == "failed" and result.reason_code == reason
    assert row.status == "failed" and row.result_id is None
    assert len(client.calls) == 1
    session.close()
    engine.dispose()


@pytest.mark.parametrize("store_failure", [False, True])
def test_v5_format_error_without_preserved_raw_never_retries(tmp_path, store_failure):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)

    class FirstStoreFails(_RawStore):
        def __init__(self):
            super().__init__()
            self.writes = 0

        def put_encrypted(self, *args, **kwargs):
            self.writes += 1
            if self.writes == 1:
                raise OSError("private storage path must not escape")
            return super().put_encrypted(*args, **kwargs)

    client = _Client(ModelInvocationError("malformed_json", (),
        raw_response=b'{"claims":' if store_failure else None), _claims_draft(), _semantic())
    result = PrespecV4OverviewRunner(client=client, binding=binding, policy=policy,
        raw_response_store=FirstStoreFails() if store_failure else _RawStore(), object_store=store).run_once(session, "v5-worker")
    expected = "response_store_unavailable" if store_failure else "malformed_json"
    assert result.status == "failed" and result.reason_code == expected
    assert len(client.calls) == 1 and session.get(PrespecV4Attempt, attempt.id).result_id is None
    errors = session.scalars(select(PrespecOverviewCallEvent).where(PrespecOverviewCallEvent.event_kind == "error")).all()
    assert len(errors) == 1 and errors[0].error_code == expected and errors[0].raw_response_sha256 is None
    session.close()
    engine.dispose()


def test_v5_unexpected_validation_text_never_becomes_a_public_reason(tmp_path, monkeypatch):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    runner = PrespecV4OverviewRunner(client=_Client(_claims_draft()), binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store)

    def bad_input(*args, **kwargs):
        raise ValueError("private /storage/path with confidential source text")

    monkeypatch.setattr(runner, "_load_input", bad_input)
    result = runner.run_once(session, "v5-worker")
    assert result.reason_code == "runner_failed"
    assert session.get(PrespecV4Attempt, attempt.id).error_code == "runner_failed"
    assert "private" not in str(_audit_metadata(session, attempt.id))
    session.close()
    engine.dispose()


def test_v5_stop_during_http_preserves_late_response_only(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)

    class _Legacy:
        def __init__(self):
            self.calls = 0

        def run_once(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(status="legacy", claimed=True)

    legacy = _Legacy()

    class _StoppingClient(_Client):
        def invoke(self, stage, input_slice, stage_policy, **kwargs):
            response = super().invoke(stage, input_slice, stage_policy, **kwargs)
            deactivate_v4(session, actor="operator", reason="operator_requested")
            session.commit()
            return response

    runner = PrespecV4OverviewRunner(
        client=_StoppingClient(_claims_draft()), binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store, legacy_runner=legacy,
    )
    result = runner.run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    assert result.status == "stale"
    assert row.status == "cancelled" and row.result_id is None
    assert session.scalar(select(PrespecOverviewVerification).where(
        PrespecOverviewVerification.attempt_id == attempt.id
    )) is None
    events = session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id
    )).all()
    assert {event.event_kind for event in events} == {"dispatch", "response"}
    assert legacy.calls == 0
    assert runner.run_once(session, "v5-worker").status == "legacy"
    assert legacy.calls == 1
    session.close()
    engine.dispose()


def test_v5_late_response_cannot_publish_for_a_different_lease_owner(tmp_path):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)

    class _ReassignedClient(_Client):
        def invoke(self, stage, input_slice, stage_policy, **kwargs):
            response = super().invoke(stage, input_slice, stage_policy, **kwargs)
            session.execute(
                update(PrespecV4Attempt)
                .where(PrespecV4Attempt.id == attempt.id)
                .values(lease_owner="replacement-worker")
            )
            session.commit()
            return response

    result = PrespecV4OverviewRunner(
        client=_ReassignedClient(_claims_draft()), binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    assert result.status == "stale"
    assert row.status == "running" and row.lease_owner == "replacement-worker"
    assert row.result_id is None
    assert session.scalar(select(PrespecOverviewVerification).where(
        PrespecOverviewVerification.attempt_id == attempt.id
    )) is None
    session.close()
    engine.dispose()


def test_v5_identity_recovers_before_claim_without_sending_payload(
    tmp_path, monkeypatch
):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy()
    binding = V4ModelBinding(
        provider="openai-compatible", model_name=policy.model_name,
        model_digest="a" * 64, prompt_version=policy.prompt_version,
        policy_digest=policy.digest, reference_only=True,
    )
    _activate_v5_for_target(session, target, binding, policy)
    attempt = enqueue_v4_attempt(session, target_id=target.id, binding=binding)
    session.commit()
    now = [datetime.now(UTC)]
    built = []

    class _IdentityClient(_Client):
        def __init__(self, succeeds):
            super().__init__(_claims_draft(), _semantic())
            self.succeeds = succeeds

        def verify_identity(self):
            if not self.succeeds:
                raise ModelIdentityError("identity_unavailable", retryable=True)
            return ModelIdentity(
                model=policy.model_name,
                revision="a" * 64,
                max_model_len=262_144,
            )

        def close(self):
            return None

    def _for_purpose(*_args, **_kwargs):
        client = _IdentityClient(succeeds=bool(built))
        built.append(client)
        return client

    monkeypatch.setattr(runner_module.ModelClient, "for_purpose", _for_purpose)
    runner = PrespecV4OverviewRunner(
        policy=policy, raw_response_store=_RawStore(), object_store=store,
        clock=lambda: now[0],
    )

    first = runner.run_once(session, "v5-worker")
    assert first.status == "awaiting_model"
    assert built[0].calls == []
    assert session.get(PrespecV4Attempt, attempt.id).status == "queued"
    now[0] += timedelta(seconds=10)
    second = runner.run_once(session, "v5-worker")
    assert second.status == "completed"
    assert len(built) == 2 and len(built[1].calls) == 2
    session.close()
    engine.dispose()


@pytest.mark.parametrize(
    "elapsed_seconds,expected_code",
    [(900, "lease_budget_exhausted"), (1201, "lease_expired")],
)
def test_v5_does_not_dispatch_semantic_without_remaining_lease(
    tmp_path, elapsed_seconds, expected_code
):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    now = [datetime.now(UTC)]

    class _AdvancingClient(_Client):
        def invoke(self, stage, input_slice, stage_policy, **kwargs):
            response = super().invoke(stage, input_slice, stage_policy, **kwargs)
            now[0] += timedelta(seconds=elapsed_seconds)
            return response

    client = _AdvancingClient(_claims_draft())
    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
        clock=lambda: now[0],
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    dispatches = session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id,
        PrespecOverviewCallEvent.event_kind == "dispatch",
    )).all()
    assert result.status == "failed" and result.reason_code == expected_code
    assert row.status == "failed" and row.error_code == expected_code
    assert len(client.calls) == 1
    assert [(event.ordinal, event.stage) for event in dispatches] == [(1, "draft")]
    session.close()
    engine.dispose()


@pytest.mark.parametrize("reported_context", [None, 1])
def test_v5_capacity_failure_stops_before_dispatch_and_http(
    tmp_path, reported_context
):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    client = _Client(_claims_draft(), _semantic())
    client.model_context_tokens = reported_context

    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    events = list(session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id
    )))
    assert result.status == "failed"
    assert result.reason_code == "input_capacity_exceeded"
    assert row.status == "failed" and row.error_code == "input_capacity_exceeded"
    assert client.calls == []
    assert events == []
    session.close()
    engine.dispose()


@pytest.mark.parametrize("failure_kind", ["page_limit", "prompt_limit", "raw_limit"])
def test_v5_legacy_input_limits_use_capacity_failure_code(
    tmp_path, monkeypatch, failure_kind
):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    client = _Client(_claims_draft(), _semantic())
    runner = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    )
    if failure_kind == "page_limit":
        monkeypatch.setattr(
            runner_module, "build_claims_stage_input",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("input_limit_exceeded")
            ),
        )
    elif failure_kind == "prompt_limit":
        monkeypatch.setattr(
            runner_module, "build_claims_prompt",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PromptTooLargeError("bounded prompt exceeds the local analysis limit")
            ),
        )
    else:
        monkeypatch.setattr(
            runner, "_load_input",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                runner_module.V4AttemptError("input_too_large")
            ),
        )

    result = runner.run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    events = list(session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id
    )))
    assert result.status == "failed"
    assert result.reason_code == "input_capacity_exceeded"
    assert row.status == "failed" and row.error_code == "input_capacity_exceeded"
    assert client.calls == [] and events == []
    session.close()
    engine.dispose()


def test_v5_semantic_capacity_is_rechecked_before_dispatch_and_http(
    tmp_path, monkeypatch
):
    engine, session, store, _target, policy, binding, attempt = _queued_v5(tmp_path)
    client = _Client(_claims_draft(), _semantic())
    checked_stages = []

    def _capacity(**kwargs):
        checked_stages.append(json.loads(kwargs["prompt"])["stage"])
        if len(checked_stages) == 2:
            raise ModelInvocationError("input_capacity_exceeded", ())
        return SimpleNamespace(total_token_upper_bound=1)

    monkeypatch.setattr(runner_module, "structured_request_capacity", _capacity)
    result = PrespecV4OverviewRunner(
        client=client, binding=binding, policy=policy,
        raw_response_store=_RawStore(), object_store=store,
    ).run_once(session, "v5-worker")

    row = session.get(PrespecV4Attempt, attempt.id)
    dispatches = list(session.scalars(select(PrespecOverviewCallEvent).where(
        PrespecOverviewCallEvent.attempt_id == attempt.id,
        PrespecOverviewCallEvent.event_kind == "dispatch",
    )))
    assert checked_stages == ["prespec_overview_claims", "prespec_overview_semantic"]
    assert result.status == "failed" and result.reason_code == "input_capacity_exceeded"
    assert row.status == "failed" and row.error_code == "input_capacity_exceeded"
    assert len(client.calls) == 1
    assert [(event.ordinal, event.stage) for event in dispatches] == [(1, "draft")]
    session.close()
    engine.dispose()
