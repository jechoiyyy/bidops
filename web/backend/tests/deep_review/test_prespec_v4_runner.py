"""Focused v4 attempt/current projection contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.object_store import FilesystemObjectStore
from app.deep_review.models import ContentObject, DocumentVersion, PreSpecPageOverview, PrespecV4Attempt
from app.deep_review.services.page_overview import list_page_overviews
from app.deep_review.services.prespec_v4 import freeze_v4_target, prepare_v4_pdf_snapshot
from app.deep_review.services.prespec_v4_runner import (
    V4ModelBinding,
    enqueue_v4_attempt,
    load_v4_policy,
    PrespecV4OverviewRunner,
    record_v4_preparation_failure,
)
from app.deep_review.services.prespec_v4_ops import activate_v4
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

    def invoke(self, stage, input_slice, policy, *, seed=None, correction=None):
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


def _ready_target(tmp_path):
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
        converter=_Converter(_processed(source), lambda _value: True),
        store=store,
        options={"prepare_pdf": True},
        renderer=_SOURCE_RENDERER,
        font=_SOURCE_FONT,
        config={"options": vars(__import__("app.deep_review.document_mcp.safety", fromlist=["ProcessorOptions"]).ProcessorOptions.from_mapping({"prepare_pdf": True}))},
        scanner=lambda _value: True,
    )
    selection = _selection(document, source)
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
        settings=SimpleNamespace(reference_workflow_mode=True, analysis_provider="vllm", prespec_overview_policy_path=None),
    )


def test_v4_policy_keeps_reference_instructions_and_examples() -> None:
    root = Path(__file__).resolve().parents[4]
    reference = json.loads(
        (root / "experiments/prespec-overview-pdf-reference/policy.json").read_text(
            encoding="utf-8"
        )
    )
    policy = load_v4_policy()
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
    policy = load_v4_policy()
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
    policy = load_v4_policy()
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


def _queued(tmp_path):
    engine, session, store, target = _ready_target(tmp_path)
    policy = load_v4_policy()
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
