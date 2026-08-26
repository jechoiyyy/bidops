"""Focused T5 regression coverage for immutable inputs and fenced analysis."""

from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import init_db
from app.models import (
    AnalysisPolicyVersion,
    AuditEvent,
    Claim,
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    EvidenceRef,
    Judgment,
    Notice,
    ProfileEvidence,
    ProfileVersion,
    Run,
    WorkJob,
)
from app.services.deep_review_validation import DeepReviewValidationError, merge_stage_chunks
from app.services.deep_reviews import DeepReviewService, DeepReviewServiceError, JobClaim, StaleFenceError
from app.services.input_versions import (
    InputVersionError,
    MODEL_NAME,
    canonical_json_bytes,
    bundle_context,
    import_policy_version,
    import_profile_version,
    load_canonical_policy,
    policy_activation_valid,
)
from app.services.ollama_client import InvocationResult, OllamaClient, OllamaInvocationError, build_prompt, sanitize_for_prompt


def _fixture_structure(_session, structure):
    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(structure.id),
        "document_version_id": str(structure.document_version_id),
        "source_sha256": structure.source_sha256,
        "media_type": structure.media_type,
        "extractor": {"name": structure.extractor_name, "version": structure.extractor_version, "upstream_commit": structure.upstream_commit},
        "pages": [{"number": 1, "width": 612, "height": 792, "image_content_object_id": None}],
        "blocks": [], "warnings": [], "created_at": "2026-08-25T00:00:00+09:00",
    }


def _valid_stage_payload(input_slice: dict, stage: str) -> dict:
    """Return the smallest materializable stage fixture for worker tests."""

    claim_id = uuid5(NAMESPACE_URL, f"{input_slice['deep_review_id']}:{input_slice['attempt_id']}:fixture-claim")
    claims = []
    if stage == "requirements_and_evaluation":
        claims = [{
            "claim_id": str(claim_id), "category": "requirements", "claim_type": "unknown",
            "body": "fixture claim is not established", "status": "unknown", "formula": None,
            "premise_claim_ids": [], "reason": "fixture", "evidence_ids": [],
        }]
    return {
        "schema": "bidops.deep-review-stage.v1", "deep_review_id": input_slice["deep_review_id"],
        "attempt_id": input_slice["attempt_id"], "stage": stage, "claims": claims,
        "evidence": [], "unknowns": ["fixture unknown"], "warnings": [],
    }


@pytest.fixture
def engine():
    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    # SQLAlchemy's PostgreSQL-only ``postgresql_where`` is intentionally not
    # emitted by SQLite and otherwise becomes a global unique index.  Mirror
    # the production partial unique semantics in this isolated test dialect;
    # PostgreSQL migrations/models remain unchanged.
    if bind.dialect.name == "sqlite":
        with bind.begin() as connection:
            for index_name in ("uq_deep_review_attempt_active", "uq_work_job_active"):
                connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
            connection.execute(text("CREATE UNIQUE INDEX uq_deep_review_attempt_active ON deep_review_attempt (deep_review_id) WHERE status IN ('queued','running')"))
            connection.execute(text("CREATE UNIQUE INDEX uq_work_job_active ON work_job (job_type, aggregate_type, aggregate_id) WHERE status IN ('queued','running')"))
    return bind


def test_approved_policy_is_byte_canonical():
    path = Path(__file__).parents[1] / "app" / "policies" / "analysis-policy-lean-v1.json"
    raw = path.read_bytes()
    assert raw == canonical_json_bytes(json.loads(raw))
    policy = json.loads(raw)
    assert policy["model_name"] == MODEL_NAME
    assert policy["chunking"]["max_characters"] == 24000
    assert policy["chunking"]["max_requirements"] == 20
    assert policy["chunking"]["retries"] == 2
    assert policy["chunking"]["timeout_seconds"] == 120
    assert policy["stages"][1]["instruction"] == "고정된 요구사항과 회사 profile 근거만 사용해 수행 방안, 위험, 역량 적합성, 금액과 경제성을 분석한다."
    assert raw.hex()[-2:] != "0a"


def test_policy_hash_is_the_approved_literal_hash():
    path = Path(__file__).parents[1] / "app" / "policies" / "analysis-policy-lean-v1.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "1968dd843e6e945d6ca5bec43af808ae6b1c105e0fa9ffbfdde8ed5eba426c17"


def test_profile_policy_import_is_immutable_and_policy_activation_requires_quality(engine):
    with Session(engine) as session:
        profile_path = Path(__file__).parents[3] / "docs" / "reference" / "company-profile.md"
        profile = import_profile_version(session, profile_path, created_by_name="운영자")
        assert len(profile.profile_payload["facts"]) == 39
        assert len({fact["fact_key"] for fact in profile.profile_payload["facts"]}) == 39
        assert import_profile_version(session, profile_path, created_by_name="다른 운영자").id == profile.id
        policy = import_policy_version(session, created_by_name="운영자", sample_hash="a" * 64, required_item_recall=.8, human_agreement=.7, unsupported_false_positive_rate=.1)
        assert policy_activation_valid(policy)
        unmeasured = import_policy_version(session, created_by_name="다른 운영자")
        assert unmeasured.id != policy.id
        assert import_policy_version(session, created_by_name="세 번째 운영자").id == unmeasured.id


@pytest.mark.parametrize("insertion_order", ["unmeasured_then_measured", "measured_then_unmeasured"])
def test_policy_quality_identity_supports_both_insertion_orders_and_measured_replay(engine, insertion_order):
    measured_kwargs = {
        "sample_hash": "c" * 64, "required_item_recall": .8,
        "human_agreement": .7, "unsupported_false_positive_rate": .1,
    }
    with Session(engine) as session:
        if insertion_order == "unmeasured_then_measured":
            unmeasured = import_policy_version(session, created_by_name="운영자")
            measured = import_policy_version(session, created_by_name="운영자", **measured_kwargs)
        else:
            measured = import_policy_version(session, created_by_name="운영자", **measured_kwargs)
            unmeasured = import_policy_version(session, created_by_name="운영자")
        assert measured.id != unmeasured.id
        replay = import_policy_version(session, created_by_name="다른 운영자", **measured_kwargs)
        assert replay.id == measured.id
        assert policy_activation_valid(measured)
        assert not policy_activation_valid(unmeasured)


def test_profile_import_integrity_error_savepoint_preserves_caller_pending_work(engine):
    profile_path = Path(__file__).parents[3] / "docs" / "reference" / "company-profile.md"
    calls = {"count": 0}

    def fail_first_profile_insert(_mapper, _connection, _target):
        if calls["count"] == 0:
            calls["count"] += 1
            raise IntegrityError("simulated concurrent version race", {}, RuntimeError("race"))

    event.listen(ProfileVersion, "before_insert", fail_first_profile_insert)
    try:
        with Session(engine) as session:
            pending = Run(id=f"caller-pending-{uuid4()}")
            session.add(pending)
            imported = import_profile_version(session, profile_path, created_by_name="운영자")
            assert calls["count"] == 1
            assert session.get(Run, pending.id) is not None
            # The surrounding caller transaction remains usable after the
            # nested race and can flush/commit unrelated work normally.
            session.flush()
            session.commit()
            assert session.get(ProfileVersion, imported.id) is not None
            assert session.get(Run, pending.id) is not None
    finally:
        event.remove(ProfileVersion, "before_insert", fail_first_profile_insert)


def test_input_imports_preserve_caller_pending_rows_and_reject_tampered_profile(engine):
    with Session(engine) as session:
        pending = Run(id=f"caller-pending-{uuid4()}")
        session.add(pending)
        profile_path = Path(__file__).parents[3] / "docs" / "reference" / "company-profile.md"
        profile = import_profile_version(session, profile_path, created_by_name="운영자")
        assert session.get(Run, pending.id) is not None
        evidence = session.query(ProfileEvidence).filter_by(profile_version_id=profile.id).first()
        assert evidence is not None
        evidence.quote = "tampered"
        with pytest.raises(InputVersionError):
            import_profile_version(session, profile_path, created_by_name="운영자")
        assert session.get(Run, pending.id) is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_hash": "A" * 64, "required_item_recall": .8, "human_agreement": .7, "unsupported_false_positive_rate": .1},
        {"sample_hash": "a" * 64, "required_item_recall": float("nan"), "human_agreement": .7, "unsupported_false_positive_rate": .1},
        {"sample_hash": "a" * 64, "required_item_recall": .8, "human_agreement": float("inf"), "unsupported_false_positive_rate": .1},
        {"sample_hash": "a" * 64, "required_item_recall": 1.1, "human_agreement": .7, "unsupported_false_positive_rate": .1},
        {"sample_hash": "a" * 64, "required_item_recall": .8},
    ],
)
def test_policy_quality_metadata_is_strictly_normalized(engine, kwargs):
    with Session(engine) as session:
        with pytest.raises(InputVersionError):
            import_policy_version(session, **kwargs)


def test_prompt_drops_paths_urls_credentials_and_raw_prompt_text():
    prompt = build_prompt(
        "requirements_and_evaluation",
        {"text": "원문 /srv/private/rfp.pdf https://example.test/key api_key=secret-value", "source_url": "https://secret.test"},
        {"stages": [{"stage": "requirements_and_evaluation", "instruction": "extract"}]},
    )
    assert "/srv/private/rfp.pdf" not in prompt
    assert "https://example.test" not in prompt
    assert "secret-value" not in prompt
    assert "source_url" not in prompt


def test_prompt_preserves_profile_identity_and_evidence_ids_but_redacts_source_metadata():
    selected = {
        "profile_version_id": str(uuid4()), "profile_sha256": "a" * 64,
        "facts": [{"fact_key": "company.employees", "status": "confirmed", "quote": "직원 10명", "source_file": "/srv/company.md"}],
        "evidence": [{"profile_evidence_id": str(uuid4()), "profile_version_id": str(uuid4()), "fact_key": "company.employees", "quote": "직원 10명", "source_url": "https://secret.example/profile"}],
    }
    prompt = build_prompt(
        "delivery_risk_economics",
        {"profile_facts": selected["facts"], "profile_evidence": selected["evidence"]},
        {"stages": [{"stage": "delivery_risk_economics", "instruction": "분석"}]},
        profile=selected,
    )
    assert selected["profile_version_id"] in prompt
    assert selected["evidence"][0]["profile_evidence_id"] in prompt
    assert "source_file" not in prompt and "source_url" not in prompt
    assert "/srv/company.md" not in prompt and "https://secret.example" not in prompt
    assert sanitize_for_prompt({"profile_version_id": "keep", "profile_evidence_id": "keep", "file_path": "drop"}) == {"profile_version_id": "keep", "profile_evidence_id": "keep"}


def test_stage2_prompt_includes_selected_profile_rows_exactly_once_and_keeps_scope_ids():
    profile_version_id = str(uuid4())
    profile_evidence_id = str(uuid4())
    selected_fact = {"fact_key": "company.unique_fact", "status": "confirmed", "value": "fact-value-once", "quote": "quote-value-once"}
    selected_evidence = {
        "profile_evidence_id": profile_evidence_id, "profile_version_id": profile_version_id,
        "fact_key": "company.unique_fact", "quote": "evidence-quote-once", "source_sha256": "a" * 64,
        "locator_type": "profile_fact", "locator": {"fact_key": "company.unique_fact"},
    }
    prompt = build_prompt(
        "delivery_risk_economics",
        {"requirements": [], "profile_facts": [selected_fact], "profile_evidence": [selected_evidence]},
        {"stages": [{"stage": "delivery_risk_economics", "instruction": "분석"}]},
        profile={"profile_version_id": profile_version_id, "profile_sha256": "b" * 64},
    )
    assert prompt.count("fact-value-once") == 1
    assert prompt.count("evidence-quote-once") == 1
    assert prompt.count(profile_version_id) == 2  # fixed-profile ID and evidence scope ID
    assert prompt.count(profile_evidence_id) == 1

    sanitized = sanitize_for_prompt({
        "raw_object_key": "drop-object-key", "encrypted_storage_path": "drop-storage-path",
        "block_key": "keep-block-key", "profile_version_id": "keep-profile-id",
    })
    assert sanitized == {"block_key": "keep-block-key", "profile_version_id": "keep-profile-id"}


def test_actual_built_prompt_has_24000_unicode_limit():
    with pytest.raises(ValueError, match="bounded prompt"):
        build_prompt(
            "requirements_and_evaluation",
            {"requirements": [{"requirement_id": "r", "text": "가" * 24000}]},
            {"stages": [{"stage": "requirements_and_evaluation", "instruction": "추출"}]},
        )


def test_ollama_timeout_retries_twice_without_exposing_prompt():
    calls = []

    def transport(request, timeout):
        calls.append((request, timeout))
        raise TimeoutError

    client = OllamaClient(transport=transport)
    with pytest.raises(OllamaInvocationError) as error:
        client.invoke("requirements_and_evaluation", {"requirements": [{"text": "safe"}]}, {"chunking": {"retries": 2, "timeout_seconds": 120}, "stages": []})
    assert error.value.code == "timeout"
    assert len(calls) == 3
    assert all(item[1] == 120.0 for item in calls)
    assert "safe" not in str(error.value)


def test_ollama_malformed_json_is_safe_error():
    def transport(_request, _timeout):
        return b"not-json"

    client = OllamaClient(transport=transport)
    with pytest.raises(OllamaInvocationError) as error:
        client.invoke("requirements_and_evaluation", {"requirements": []}, {"chunking": {"retries": 0}, "stages": []})
    assert error.value.code == "malformed_json"


@pytest.mark.parametrize("endpoint", [
    "https://127.0.0.1:11434/api/generate",
    "http://127.0.0.1/api/generate",
    "http://127.0.0.1:11434/api/tags",
    "http://user:pass@127.0.0.1:11434/api/generate",
    "http://127.0.0.1:11434/api/generate?secret=1",
    "http://127.0.0.1:11434/api/generate#fragment",
])
def test_ollama_endpoint_is_exact_local_generate_url(endpoint):
    with pytest.raises(ValueError):
        OllamaClient(endpoint=endpoint)


def test_ollama_retention_is_clamped_to_one_to_ninety(monkeypatch):
    seen = []

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            seen.append((len(data), retention_days, content_type))
            return {"encrypted": True, "object_key": "model-response/fixture", "encryption_key_ref": "fixture", "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    from app.services.ollama_client import InvocationResult
    service = DeepReviewService(raw_response_store=Store())
    result = InvocationResult({}, b"{}", "a" * 64, "b" * 64, None, None, 1, ())
    monkeypatch.setenv("BIDOPS_MODEL_RESPONSE_RETENTION_DAYS", "999")
    service._store_raw_aggregate([(result, {"slice_index": 0})])
    monkeypatch.setenv("BIDOPS_MODEL_RESPONSE_RETENTION_DAYS", "0")
    service._store_raw_aggregate([(result, {"slice_index": 0})])
    assert [row[1] for row in seen] == [90, 1]


def test_raw_metadata_rejects_aliases_wrong_types_and_accepts_multiple_locations(engine):
    service = DeepReviewService()
    aggregate = b'{"schema":"aggregate"}'
    valid = {"encrypted": True, "object_key": "model-response/one", "encryption_key_ref": "key-ref", "plaintext_sha256": hashlib.sha256(aggregate).hexdigest(), "plaintext_size_bytes": len(aggregate)}
    assert service._validate_raw_store_metadata(valid, aggregate)["object_key"] == "model-response/one"
    for invalid in (
        {**valid, "plaintext_sha": valid["plaintext_sha256"]},
        {**valid, "plaintext_size_bytes": True},
        {**valid, "encrypted": 1},
        {**valid, "encryption_key_ref": ""},
        {**valid, "object_key": "../escape"},
    ):
        with pytest.raises(Exception):
            service._validate_raw_store_metadata(invalid, aggregate)
    with Session(engine) as session:
        first = service._raw_content_row(session, aggregate, valid)
        second_meta = {**valid, "object_key": "model-response/two"}
        second = service._raw_content_row(session, aggregate, second_meta)
        session.commit()
        assert first.id == second.id
        locations = session.query(ContentObjectLocation).filter_by(content_object_id=first.id, namespace_key="model-response").all()
        assert {location.object_key for location in locations} == {"model-response/one", "model-response/two"}


def test_raw_metadata_rejects_sensitive_key_refs_and_existing_locator_mismatch(engine):
    service = DeepReviewService()
    aggregate = b'{"schema":"aggregate"}'
    valid = {
        "encrypted": True, "object_key": "model-response/exact", "encryption_key_ref": "kms-ref",
        "plaintext_sha256": hashlib.sha256(aggregate).hexdigest(), "plaintext_size_bytes": len(aggregate),
    }
    for value in ("secret-kms-ref", "password-ref", "api-key-ref", "token-ref", "credential-ref"):
        with pytest.raises(DeepReviewServiceError):
            service._validate_raw_store_metadata({**valid, "encryption_key_ref": value}, aggregate)

    with Session(engine) as session:
        content = ContentObject(id=uuid4(), sha256=hashlib.sha256(aggregate).hexdigest(), size_bytes=len(aggregate), detected_mime="application/json", retention_class="model-response-90d")
        session.add(content)
        session.flush()
        session.add(ContentObjectLocation(
            id=uuid4(), content_object_id=content.id, namespace_key="model-response", object_key="model-response/exact",
            status="pending", etag="wrong", encryption_key_ref="other-kms-ref",
        ))
        session.commit()
        with pytest.raises(DeepReviewServiceError):
            service._raw_content_row(session, aggregate, valid)
        session.rollback()


def test_multi_invocation_raw_aggregate_is_complete_sorted_and_metadata_safe():
    service = DeepReviewService()
    records = []
    for slice_index in range(56):
        payload = {"slice": slice_index, "raw_marker": f"response-{slice_index}"}
        raw = json.dumps(payload, sort_keys=True).encode()
        records.append((
            InvocationResult(payload, raw, "a" * 64, hashlib.sha256(raw).hexdigest(), 1, 2, slice_index, ({
                "retry_index": 0, "status": "succeeded", "locator": "must-not-persist", "object_key": "must-not-persist",
            },)),
            {"slice_index": slice_index, "locator": "must-not-persist", "object_key": "must-not-persist"},
        ))
    aggregate = service._raw_aggregate_bytes(list(reversed(records)))
    document = json.loads(aggregate)
    assert [row["slice_index"] for row in document["responses"]] == list(range(56))
    assert [row["raw_response"] for row in document["responses"]] == [json.dumps({"slice": index, "raw_marker": f"response-{index}"}, sort_keys=True) for index in range(56)]
    assert all(row["response_sha256"] == hashlib.sha256(row["raw_response"].encode()).hexdigest() for row in document["responses"])
    metadata = [{"slice_index": index, "attempts": [{"retry_index": 0, "status": "succeeded", "locator": "drop", "object_key": "drop"}]} for index in range(56)]
    safe = [_safe for _safe in metadata]
    # The worker's persisted path uses the same whitelist as failure metadata.
    from app.services.deep_reviews import _safe_invocation_metadata
    persisted = [_safe_invocation_metadata(item) for item in safe]
    assert all("locator" not in str(item) and "object_key" not in str(item) for item in persisted)


def test_lease_budget_and_worker_id_are_bounded():
    service = DeepReviewService(lease_seconds=1)
    assert service.lease_seconds >= 480
    with pytest.raises(Exception):
        service.claim_next_job(None, "worker id with spaces")


def test_requirements_are_bounded_at_20_and_24000_characters():
    service = DeepReviewService()
    blocks = [{"block_key": f"b-{index}", "page": index + 1, "text": "요구사항 " + ("x" * 900)} for index in range(55)]
    bundle = {"documents": [{"ordinal": 0, "document_version_id": str(uuid4()), "structure_id_at_confirmation": "s-1"}]}
    groups = service._requirements(bundle, {"s-1": {"blocks": blocks}})
    assert len(groups) >= 3
    assert all(len(group) <= 20 for group in groups)
    assert all(sum(len(str(item["text"])) for item in group) <= 24000 for group in groups)
    assert [item["requirement_id"] for group in groups for item in group] == sorted(item["requirement_id"] for group in groups for item in group)


def test_injected_structure_loader_cannot_bypass_closed_schema(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    with Session(engine) as session:
        with pytest.raises(InputVersionError, match="structure"):
            bundle_context(session, bundle_id, structure_loader=lambda _session, _structure: {"blocks": []})


def test_stage_slices_keep_all_requirements_and_bounded_prompt_size():
    service = DeepReviewService()
    blocks = [{"block_key": f"b-{index}", "page": index + 1, "text": f"요구사항 {index} " + ("x" * 900)} for index in range(55)]
    bundle = {"documents": [{"ordinal": 0, "document_version_id": str(uuid4()), "structure_id_at_confirmation": "s-1"}]}
    groups = service._stage_slices("requirements_and_evaluation", bundle, {"s-1": {"blocks": blocks}}, {}, [])
    policy = {"stages": [{"stage": "requirements_and_evaluation", "instruction": "추출"}]}
    all_ids = [item["requirement_id"] for group in groups for item in group["requirements"]]
    assert len(all_ids) == 55 and len(set(all_ids)) == 55
    assert all(len(build_prompt("requirements_and_evaluation", {"requirements": group["requirements"]}, policy)) <= 24000 for group in groups)


def test_stage3_slices_include_every_prior_claim_and_each_referenced_evidence_once():
    service = DeepReviewService()
    evidence = [{
        "evidence_id": str(uuid4()), "source_kind": "document", "quote": f"evidence-{index}",
        "document_version_id": str(uuid4()), "structure_id": str(uuid4()), "profile_version_id": None,
        "profile_evidence_id": None, "locator_type": "page", "locator": {"page": 1},
        "confidence": None, "source_sha256": "a" * 64,
    } for index in range(3)]
    claims = [{
        "claim_id": str(uuid4()), "category": "requirements", "claim_type": "unknown", "body": f"claim-{index}",
        "status": "unknown", "formula": None, "premise_claim_ids": [], "reason": "not established",
        "evidence_ids": [evidence[0]["evidence_id"], evidence[1]["evidence_id"]] if index == 1 else [evidence[0]["evidence_id"]] if index == 0 else [],
    } for index in range(3)]
    # evidence[0] is shared by claims 0 and 1; evidence[2] is intentionally
    # unreferenced and must not enter the synthesis prompt.
    previous = [{"claims": claims, "evidence": evidence}]
    slices = service._stage_slices("synthesis_and_validation", {}, {}, {}, previous)
    prompt_documents = [build_prompt("synthesis_and_validation", item, {"stages": [{"stage": "synthesis_and_validation", "instruction": "종합"}]}) for item in slices]
    prompt_inputs = [json.loads(prompt)["input_slice"] for prompt in prompt_documents]
    prompt_claims = [claim for item in prompt_inputs for claim in item["verified_claims"]]
    prompt_evidence = [item for payload in prompt_inputs for item in payload["prior_evidence"]]
    assert [claim["claim_id"] for claim in prompt_claims] == [claim["claim_id"] for claim in claims]
    assert [item["evidence_id"] for item in prompt_evidence] == [evidence[0]["evidence_id"], evidence[1]["evidence_id"]]


def test_deterministic_merge_rejects_duplicate_or_out_of_scope_evidence():
    review_id, attempt_id = str(uuid4()), str(uuid4())
    chunk = {"schema": "bidops.deep-review-stage.v1", "deep_review_id": review_id, "attempt_id": attempt_id, "stage": "requirements_and_evaluation", "claims": [], "evidence": [], "unknowns": [], "warnings": []}
    assert merge_stage_chunks([chunk], expected_claim_ids=[], expected_evidence_ids=[]) == chunk
    out_of_scope = dict(chunk)
    out_of_scope["evidence"] = [{"evidence_id": str(uuid4()), "source_kind": "profile", "document_version_id": None, "structure_id": None, "profile_version_id": str(uuid4()), "profile_evidence_id": str(uuid4()), "locator_type": "profile_fact", "locator": {"fact_key": "x"}, "quote": "x", "confidence": None, "source_sha256": "a" * 64}]
    with pytest.raises(DeepReviewValidationError):
        merge_stage_chunks([out_of_scope], bundle={"status": "ready", "documents": []}, profile={"profile_version_id": str(uuid4()), "evidence": []}, structures={})


def test_stale_fence_rejects_final_write(engine):
    with Session(engine) as session:
        job_id = uuid4()
        session.add(WorkJob(id=job_id, job_type="deep_review", aggregate_type="deep_review", aggregate_id=uuid4(), status="running", lease_owner="worker-a", lease_fence=2))
        session.commit()
        claim = JobClaim(job_id, uuid4(), uuid4(), "worker-b", 2)
        with pytest.raises(StaleFenceError):
            DeepReviewService()._finish_claim(session, claim)


def test_stale_fence_writes_nothing_including_raw_projections_or_failure_audit(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        actual = service.claim_next_job(session, "worker-a")
        assert actual is not None
        stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == actual.attempt_id, DeepReviewStage.sequence == 1))
        assert stage is not None
        stale = JobClaim(actual.job_id, actual.deep_review_id, actual.attempt_id, "worker-stale", actual.fence)
        before = {
            "content": session.query(ContentObject).count(),
            "locations": session.query(ContentObjectLocation).count(),
            "claims": session.query(Claim).count(),
            "evidence": session.query(EvidenceRef).count(),
            "audits": session.query(AuditEvent).count(),
            "stage_output": dict(stage.structured_output),
            "stage_status": stage.status,
        }
        with pytest.raises(StaleFenceError):
            service._persist_stage(
                session, stale, stage,
                {"schema": "bidops.deep-review-stage.v1", "deep_review_id": str(actual.deep_review_id), "attempt_id": str(actual.attempt_id), "stage": stage.stage, "claims": [], "evidence": [], "unknowns": [], "warnings": []},
                [], raw_aggregate=(b"raw", {"object_key": "model-response/raw", "encryption_key_ref": "fixture"}),
            )
        with pytest.raises(StaleFenceError):
            service._fail_claim(session, stale, stage, "stale_failure")
        session.refresh(stage)
        assert session.query(ContentObject).count() == before["content"]
        assert session.query(ContentObjectLocation).count() == before["locations"]
        assert session.query(Claim).count() == before["claims"]
        assert session.query(EvidenceRef).count() == before["evidence"]
        assert session.query(AuditEvent).count() == before["audits"]
        assert stage.structured_output == before["stage_output"] and stage.status == before["stage_status"]
        assert service.view(session, UUID(created["id"]))["status"] == "running"


def test_completed_prefix_requires_current_attempt_and_db_projections(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review = session.get(DeepReview, UUID(created["id"]))
        assert review is not None and review.current_attempt_id is not None
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        assert attempt is not None
        stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == attempt.id, DeepReviewStage.sequence == 1))
        assert stage is not None
        claim_id = uuid4()
        output = {
            "schema": "bidops.deep-review-stage.v1", "deep_review_id": str(review.id), "attempt_id": str(attempt.id),
            "stage": stage.stage, "claims": [{"claim_id": str(claim_id), "category": "requirements", "claim_type": "unknown", "body": "unknown", "status": "unknown", "formula": None, "premise_claim_ids": [], "reason": "not established", "evidence_ids": []}],
            "evidence": [], "unknowns": [], "warnings": [],
        }
        stage.status = "completed"
        stage.structured_output = output
        session.commit()
        stages = service._stages(session, attempt.id)
        with pytest.raises(DeepReviewServiceError, match="attempt scope"):
            service._contiguous_completed_prefix(
                stages, bundle={"status": "ready", "documents": []}, profile={}, profile_version_id=str(review.profile_version_id),
                review_id=str(review.id), structures={}, session=session, attempt_id=str(uuid4()),
            )
        with pytest.raises(DeepReviewServiceError, match="projection"):
            service._contiguous_completed_prefix(
                stages, bundle={"status": "ready", "documents": []}, profile={}, profile_version_id=str(review.profile_version_id),
                review_id=str(review.id), structures={}, session=session, attempt_id=str(attempt.id),
            )
        session.add(Claim(
            id=claim_id, deep_review_id=review.id, stage_id=stage.id, category="requirements", claim_type="unknown",
            body="unknown", status="unknown", formula=None, premise_claim_ids=[], reason="not established",
        ))
        session.commit()
        outputs, claim_ids, evidence_ids = service._contiguous_completed_prefix(
            service._stages(session, attempt.id), bundle={"status": "ready", "documents": []}, profile={},
            profile_version_id=str(review.profile_version_id), review_id=str(review.id), structures={}, session=session,
            attempt_id=str(attempt.id),
        )
        assert outputs[0]["attempt_id"] == str(attempt.id)
        assert claim_ids == {str(claim_id)} and evidence_ids == set()


def test_job_transition_audits_are_fenced_and_safe(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)

    class Client:
        def invoke(self, stage, input_slice, _policy, **_kwargs):
            payload = _valid_stage_payload(input_slice, stage)
            raw = json.dumps(payload).encode()
            return InvocationResult(payload, raw, "a" * 64, hashlib.sha256(raw).hexdigest(), 1, 1, 1, ({"retry_index": 0, "status": "succeeded", "locator": "drop", "object_key": "drop"},))

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            return {"object_key": f"model-response/{hashlib.sha256(data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    service = DeepReviewService(client=Client(), raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-a")
        assert claim is not None
        first = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(claim.job_id), AuditEvent.action == "deep_review.job.claim"))
        assert first is not None and first.actor_kind == "system" and first.claimed_name is None
        assert set(first.safe_metadata) == {"job_id", "review_id", "attempt_id", "lease_fence", "status"}
        assert first.safe_metadata["status"] == "running"
        job = session.get(WorkJob, claim.job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        reclaimed = service.claim_next_job(session, "worker-b")
        assert reclaimed is not None and reclaimed.fence == claim.fence + 1
        reclaim_audit = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(claim.job_id), AuditEvent.action == "deep_review.job.reclaim"))
        assert reclaim_audit is not None and reclaim_audit.safe_metadata["lease_fence"] == reclaimed.fence
        service.run_claim(session, reclaimed)
        completed = session.scalar(select(AuditEvent).where(AuditEvent.aggregate_id == str(claim.job_id), AuditEvent.action == "deep_review.job.completed").order_by(AuditEvent.created_at.desc()))
        assert completed is not None and completed.safe_metadata["status"] == "completed"
        stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == reclaimed.attempt_id)).all()
        assert all("locator" not in str(stage.invocation_metadata) and "object_key" not in str(stage.invocation_metadata) for stage in stages)
        assert service.view(session, UUID(created["id"]))["status"] == "completed"


def _seed_review_context(engine, monkeypatch):
    with Session(engine) as session:
        run = Run(id=f"t5-{uuid4()}")
        notice = Notice(run=run, notice_key=f"t5-notice-{uuid4()}")
        notice.judgment = Judgment(grade="우선 검토", readiness="확인 완료")
        session.add_all([run, notice])
        session.flush()
        bundle = DocumentBundle(id=uuid4(), notice_id=notice.id, revision=1, version=1, status="ready", issues_snapshot=[], confirmed_by_name="담당자")
        profile = ProfileVersion(id=uuid4(), version=1, label="profile", profile_payload={"schema": "bidops.company-profile.v1", "source_file": "docs/reference/company-profile.md", "source_sha256": "a" * 64, "facts": [{"fact_key": f"fixture.fact[{index}]", "status": "unknown", "quote": "fixture"} for index in range(39)]}, profile_sha256="a" * 64, source_kind="fixture")
        policy_payload, _canonical, policy_hash = load_canonical_policy()
        policy = AnalysisPolicyVersion(id=uuid4(), version=1, label="policy", model_endpoint_ref="ollama-local", model_name=MODEL_NAME, prompts=policy_payload["stages"], validation_rules={**policy_payload["validation"], "sample_hash": "b" * 64, "required_item_recall": .8, "human_agreement": .7, "unsupported_false_positive_rate": .1}, policy_sha256=policy_hash)
        content_id = uuid4()
        from app.models import ContentObject
        content = ContentObject(id=content_id, sha256="d" * 64, size_bytes=0, detected_mime="application/json", retention_class="fixture")
        document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content_id, version=1, source_kind="manual", original_filename="fixture.pdf", role="기타", is_current=True, safety_status="safe")
        structure = DocumentStructure(id=uuid4(), document_version_id=document.id, source_sha256="d" * 64, media_type="application/pdf", extractor_name="fixture", extractor_version="1", payload_content_object_id=content_id, payload_sha256="e" * 64, page_count=1, block_count=0, validation_status="ready")
        item = DocumentBundleItem(bundle_id=bundle.id, document_version_id=document.id, ordinal=0, document_version_version=1, content_object_id=content_id, content_sha256="d" * 64, detected_mime="application/pdf", size_bytes=0, original_filename="fixture.pdf", source_kind="manual", role_at_confirmation="기타", is_current_at_confirmation=True, safety_status_at_confirmation="safe", structure_id_at_confirmation=structure.id, structure_payload_sha256="e" * 64)
        session.add_all([bundle, profile, policy, content, document, structure, item])
        session.commit()
        monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(profile.id))
        monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(policy.id))
        return notice.id, bundle.id, profile.id, policy.id


def test_duplicate_request_and_active_setting_change_keep_started_inputs(engine, monkeypatch):
    notice_id, bundle_id, profile_id, policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    request_id = uuid4()
    with Session(engine) as session:
        first = service.create_review(session, notice_id, bundle_id, "담당자", request_id)
        assert service.create_review(session, notice_id, bundle_id, "담당자", request_id) == first
        with pytest.raises(Exception):
            service.create_review(session, notice_id, uuid4(), "담당자", request_id)
        monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(uuid4()))
        monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(uuid4()))
        row = session.get(DeepReview, UUID(first["id"]))
        assert row is not None
        assert row.profile_version_id == profile_id
        assert row.policy_version_id == policy_id


def test_failed_attempt_can_create_a_new_fenced_attempt(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        first = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review_id = UUID(first["id"])
        review = session.get(DeepReview, review_id)
        assert review is not None and review.current_attempt_id is not None
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        assert attempt is not None
        attempt.status = "failed"
        job = session.get(WorkJob, attempt.work_job_id)
        assert job is not None
        job.status = "failed"
        review.status = "failed"
        session.commit()
        retried = service.create_attempt(session, review_id, "담당자", uuid4())
        assert retried["sequence"] == 2


@pytest.mark.parametrize("pointer_state,expected", [
    ("missing", "review_not_ready"),
    ("foreign", "review_not_ready"),
    ("superseded", "review_not_ready"),
    ("queued", "active_attempt_exists"),
    ("running", "active_attempt_exists"),
    ("failed", "allowed"),
    ("completed", "allowed"),
])
def test_create_attempt_pointer_state_contract_table(engine, monkeypatch, pointer_state, expected):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review_id = UUID(created["id"])
        review = session.get(DeepReview, review_id)
        assert review is not None and review.current_attempt_id is not None
        current = session.get(DeepReviewAttempt, review.current_attempt_id)
        assert current is not None
        if pointer_state == "missing":
            review.current_attempt_id = None
            session.commit()
        elif pointer_state == "foreign":
            review.current_attempt_id = uuid4()
            session.commit()
        elif pointer_state == "superseded":
            current.status = "superseded"
            review.status = "failed"
            job = session.get(WorkJob, current.work_job_id)
            assert job is not None
            job.status = "failed"
            session.commit()
        elif pointer_state == "running":
            assert service.claim_next_job(session, "worker-running") is not None
        elif pointer_state in {"failed", "completed"}:
            current.status = pointer_state
            review.status = pointer_state
            job = session.get(WorkJob, current.work_job_id)
            assert job is not None
            job.status = pointer_state
            session.commit()

        if expected == "allowed":
            retried = service.create_attempt(session, review_id, "담당자", uuid4())
            assert retried["sequence"] == 2
        else:
            with pytest.raises(DeepReviewServiceError) as error:
                service.create_attempt(session, review_id, "담당자", uuid4())
            assert error.value.code == expected


def test_stage_transition_guards_mark_running_persist_running_and_finish_exactly_three(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-a")
        assert claim is not None
        stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.sequence == 1))
        assert stage is not None and stage.status == "queued"
        with pytest.raises(StaleFenceError):
            service._persist_stage(session, claim, stage, {"queued": True}, [], raw_aggregate=None)
        assert session.get(DeepReviewStage, stage.id).status == "queued"

        service._mark_running(session, claim, stage)
        assert session.get(DeepReviewStage, stage.id).status == "running"
        with pytest.raises(StaleFenceError):
            service._mark_running(session, claim, stage)
        session.rollback()

        stage = session.get(DeepReviewStage, stage.id)
        assert stage is not None and stage.status == "running"
        service._persist_stage(session, claim, stage, {"completed": True}, [], raw_aggregate=None)
        assert session.get(DeepReviewStage, stage.id).status == "completed"
        with pytest.raises(StaleFenceError):
            service._persist_stage(session, claim, stage, {"second": True}, [], raw_aggregate=None)
        assert session.get(DeepReviewStage, stage.id).structured_output == {"completed": True}

        with pytest.raises(StaleFenceError):
            service._finish_claim(session, claim)
        assert service.view(session, UUID(created["id"]))["status"] == "running"


def test_completed_attempt_is_immutable_when_a_new_attempt_is_created(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review = session.get(DeepReview, UUID(created["id"]))
        assert review is not None and review.current_attempt_id is not None
        old_attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        assert old_attempt is not None
        old_attempt.status = "completed"
        review.status = "completed"
        job = session.get(WorkJob, old_attempt.work_job_id)
        assert job is not None
        job.status = "completed"
        session.commit()
        retried = service.create_attempt(session, review.id, "담당자", uuid4())
        assert retried["sequence"] == 2
        assert session.get(DeepReviewAttempt, old_attempt.id).status == "completed"


def test_expired_reclaim_refences_inflight_stage_and_rejects_old_worker(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)

    class Client:
        def invoke(self, stage, input_slice, _policy, **_kwargs):
            from app.services.ollama_client import InvocationResult
            payload = _valid_stage_payload(input_slice, stage)
            raw = json.dumps(payload).encode()
            return InvocationResult(payload, raw, "a" * 64, "b" * 64, 1, 1, 1, ({"retry_index": 0, "status": "succeeded"},))

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            return {"object_key": f"model-response/{hashlib.sha256(data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    service = DeepReviewService(client=Client(), raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        old_claim = service.claim_next_job(session, "worker-old")
        assert old_claim is not None
        stage = session.scalar(select(DeepReviewStage).where(DeepReviewStage.attempt_id == old_claim.attempt_id, DeepReviewStage.sequence == 1))
        job = session.get(WorkJob, old_claim.job_id)
        assert stage is not None and job is not None
        stage.status = "running"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        new_claim = service.claim_next_job(session, "worker-new")
        assert new_claim is not None and new_claim.fence == old_claim.fence + 1
        assert session.get(DeepReviewStage, stage.id).status == "queued"
        with pytest.raises(StaleFenceError):
            service._renew_lease(session, old_claim)
        service.run_claim(session, new_claim)
        assert service.view(session, UUID(created["id"]))["status"] == "completed"


def test_failure_after_completed_stage_keeps_completed_stage_and_allows_new_attempt(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)

    class Client:
        def invoke(self, stage, input_slice, _policy, **_kwargs):
            from app.services.ollama_client import InvocationResult
            if stage == "delivery_risk_economics":
                raise OllamaInvocationError("timeout", ({"retry_index": 0, "status": "failed", "error_code": "timeout"},))
            payload = {"schema": "bidops.deep-review-stage.v1", "deep_review_id": input_slice["deep_review_id"], "attempt_id": input_slice["attempt_id"], "stage": stage, "claims": [], "evidence": [], "unknowns": [], "warnings": []}
            raw = json.dumps(payload).encode()
            return InvocationResult(payload, raw, "a" * 64, "b" * 64, 1, 1, 1, ({"retry_index": 0, "status": "succeeded"},))

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            return {"object_key": f"model-response/{hashlib.sha256(data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    service = DeepReviewService(client=Client(), raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-a")
        assert claim is not None
        with pytest.raises(DeepReviewServiceError):
            service.run_claim(session, claim)
        attempt = session.get(DeepReviewAttempt, claim.attempt_id)
        assert attempt is not None and attempt.status == "failed"
        stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == claim.attempt_id).order_by(DeepReviewStage.sequence)).all()
        assert stages[0].status == "completed" and stages[1].status == "failed"
        assert service.create_attempt(session, UUID(created["id"]), "담당자", uuid4())["sequence"] == 2


def test_malformed_mid_stage_fails_then_new_attempt_runs_successfully(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)

    class Client:
        def __init__(self):
            self.fail_mid_stage = True

        def invoke(self, stage, input_slice, _policy, **_kwargs):
            if self.fail_mid_stage and stage == "delivery_risk_economics":
                payload = {"malformed": True}
            else:
                payload = _valid_stage_payload(input_slice, stage)
            raw = json.dumps(payload).encode()
            return InvocationResult(payload, raw, "a" * 64, hashlib.sha256(raw).hexdigest(), 1, 1, 1, ({"retry_index": 0, "status": "succeeded"},))

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            return {"object_key": f"model-response/{hashlib.sha256(data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    client = Client()
    service = DeepReviewService(client=client, raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        first_claim = service.claim_next_job(session, "worker-first")
        assert first_claim is not None
        with pytest.raises(DeepReviewServiceError):
            service.run_claim(session, first_claim)
        first_attempt = session.get(DeepReviewAttempt, first_claim.attempt_id)
        assert first_attempt is not None and first_attempt.status == "failed"
        assert service.view(session, UUID(created["id"]))["status"] == "failed"
        failed_stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == first_claim.attempt_id).order_by(DeepReviewStage.sequence)).all()
        assert failed_stages[0].status == "completed" and failed_stages[1].status == "failed"

        retry = service.create_attempt(session, UUID(created["id"]), "담당자", uuid4())
        assert retry["sequence"] == 2
        client.fail_mid_stage = False
        second_claim = service.claim_next_job(session, "worker-second")
        assert second_claim is not None
        service.run_claim(session, second_claim)
        assert service.view(session, UUID(created["id"]))["status"] == "completed"
        assert session.get(DeepReviewAttempt, first_claim.attempt_id).status == "superseded"


def test_reclaim_resumes_after_immutable_stage_one_prefix_and_rejects_noncontiguous_state(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    calls = []

    class Client:
        def invoke(self, stage, input_slice, _policy, **_kwargs):
            from app.services.ollama_client import InvocationResult
            calls.append(stage)
            payload = _valid_stage_payload(input_slice, stage)
            raw = json.dumps(payload).encode()
            return InvocationResult(payload, raw, "a" * 64, "b" * 64, 1, 1, 1, ({"retry_index": 0, "status": "succeeded"},))

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            return {"object_key": f"model-response/{hashlib.sha256(data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    service = DeepReviewService(client=Client(), raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        old_claim = service.claim_next_job(session, "worker-old")
        assert old_claim is not None
        stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == old_claim.attempt_id).order_by(DeepReviewStage.sequence)).all()
        prefix_output = _valid_stage_payload({"deep_review_id": str(old_claim.deep_review_id), "attempt_id": str(old_claim.attempt_id)}, stages[0].stage)
        raw_object = ContentObject(id=uuid4(), sha256="c" * 64, size_bytes=2, detected_mime="application/json", retention_class="model-response-90d")
        session.add(raw_object)
        stages[0].status = "completed"
        stages[0].structured_output = prefix_output
        stages[0].completed_at = datetime.now(UTC)
        stages[0].raw_response_content_object_id = raw_object.id
        prefix_claim_id = UUID(prefix_output["claims"][0]["claim_id"])
        session.add(Claim(
            id=prefix_claim_id, deep_review_id=old_claim.deep_review_id, stage_id=stages[0].id,
            category="requirements", claim_type="unknown", body="fixture claim is not established",
            status="unknown", formula=None, premise_claim_ids=[], reason="fixture",
        ))
        stages[1].status = "running"
        job = session.get(WorkJob, old_claim.job_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        new_claim = service.claim_next_job(session, "worker-new")
        assert new_claim is not None
        assert session.get(DeepReviewStage, stages[0].id).status == "completed"
        assert session.get(DeepReviewStage, stages[0].id).raw_response_content_object_id == raw_object.id
        service.run_claim(session, new_claim)
        assert calls[0] == stages[1].stage and calls[-1] == stages[2].stage
        assert stages[0].stage not in calls
        assert session.get(DeepReviewStage, stages[0].id).structured_output == prefix_output
        assert session.get(DeepReviewStage, stages[0].id).raw_response_content_object_id == raw_object.id

    # A completed stage after a queued stage is corruption, not a resumable
    # prefix.  The worker fails cleanly instead of skipping ahead.
    calls.clear()
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        # The immutable input tuple is already used; create a new attempt on
        # the same review after the successful run above.
        review = session.get(DeepReview, UUID(created["id"]))
        assert review is not None and review.status == "completed"
        retry = service.create_attempt(session, review.id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-corrupt")
        assert claim is not None
        corrupt_stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == claim.attempt_id).order_by(DeepReviewStage.sequence)).all()
        corrupt_stages[1].status = "completed"
        corrupt_stages[1].structured_output = {"schema": "bidops.deep-review-stage.v1", "deep_review_id": str(claim.deep_review_id), "attempt_id": str(claim.attempt_id), "stage": corrupt_stages[1].stage, "claims": [], "evidence": [], "unknowns": [], "warnings": []}
        session.commit()
        with pytest.raises(DeepReviewServiceError):
            service.run_claim(session, claim)
        assert session.get(DeepReviewAttempt, claim.attempt_id).status == "failed"


def test_normal_worker_runs_exactly_three_ordered_stages(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)

    class Client:
        def invoke(self, stage, input_slice, _policy, **_kwargs):
            from app.services.ollama_client import InvocationResult
            payload = _valid_stage_payload(input_slice, stage)
            raw = json.dumps(payload, ensure_ascii=False).encode()
            return InvocationResult(payload, raw, "a" * 64, "b" * 64, 1, 1, 1, ({"retry_index": 0, "status": "succeeded"},))

    class Store:
        def put_encrypted(self, _data, *, retention_days, content_type):
            assert retention_days == 90 and content_type == "application/json"
            return {"object_key": f"model-response/{hashlib.sha256(_data).hexdigest()}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": hashlib.sha256(_data).hexdigest(), "plaintext_size_bytes": len(_data)}

    service = DeepReviewService(client=Client(), raw_response_store=Store(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-a")
        assert claim is not None
        service.run_claim(session, claim)
        view = service.view(session, UUID(created["id"]))
        assert view["status"] == "completed"
        assert [stage["stage"] for stage in view["current_attempt"]["stages"]] == [
            "requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation"
        ]
        assert all(stage["status"] == "completed" for stage in view["current_attempt"]["stages"])
