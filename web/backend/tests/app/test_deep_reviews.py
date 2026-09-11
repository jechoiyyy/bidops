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

from app.deep_review.cli.import_profile_policy import import_profile_policy
from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    AnalysisPolicyVersion,
    Claim,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewAttempt,
    DeepReviewStage,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    EvidenceRef,
    ProfileEvidence,
    ProfileVersion,
    WorkJob,
)
from app.lifecycle.models import Notice, Run
from app.screening.models import Judgment
from app.deep_review.services import input_versions
from app.deep_review.services.deep_review_validation import DeepReviewValidationError, merge_stage_chunks
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError, JobClaim, StaleFenceError
from app.deep_review.services.deep_reviews import _resolve_exact_evidence_quotes
from app.core.model_binding import MODEL_NAME, canonical_json_bytes
from app.deep_review.services.input_versions import (
    InputVersionError,
    bundle_context,
    import_policy_version,
    import_profile_version,
    load_canonical_policy,
    policy_activation_valid,
)
from app.core.model_client import InvocationResult, ModelClient, ModelInvocationError, build_prompt, sanitize_for_prompt
from app.core.config import get_settings
from app.core.model_binding import MODEL_ENDPOINT_REF
from app.deep_review.services import deep_reviews as deep_reviews_module
from app.deep_review.services.deep_review_vllm import DEEP_REVIEW_STAGE_CONTRACT
from app.deep_review.services.reports import ReportService
from app.core.object_store import ObjectMetadata


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
    path = Path(__file__).parents[2] / "app" / "deep_review" / "policies" / "analysis-policy-lean-v1.json"
    raw = path.read_bytes()
    assert raw == canonical_json_bytes(json.loads(raw))
    policy = json.loads(raw)
    assert policy["model_name"] == MODEL_NAME
    assert policy["chunking"]["max_characters"] == 24000
    assert policy["chunking"]["max_requirements"] == 20
    assert policy["chunking"]["retries"] == 2
    assert policy["chunking"]["timeout_seconds"] == 300
    assert policy["generation"] == {
        "enable_thinking": False, "max_completion_tokens": 16384, "seed": 0,
        "temperature": 0.7, "top_k": 20, "top_p": 0.8,
    }
    assert policy["stages"][1]["instruction"] == "고정된 요구사항과 회사 profile 근거만 사용해 수행 방안, 위험, 역량 적합성, 금액과 경제성을 분석한다."
    assert raw.hex()[-2:] != "0a"


def test_policy_hash_is_the_approved_literal_hash():
    path = Path(__file__).parents[2] / "app" / "deep_review" / "policies" / "analysis-policy-lean-v1.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "ade63ebfafa2eec424bbb456dea1b5b21da0980eac6c484853612e37dda422e8"


def test_profile_policy_import_is_immutable_and_policy_activation_requires_quality(engine):
    with Session(engine) as session:
        profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
        profile = import_profile_version(session, profile_path, created_by_name="운영자")
        assert len(profile.profile_payload["facts"]) == 43
        assert len({fact["fact_key"] for fact in profile.profile_payload["facts"]}) == 43
        assert import_profile_version(session, profile_path, created_by_name="다른 운영자").id == profile.id
        policy = import_policy_version(session, created_by_name="운영자", sample_hash="a" * 64, required_item_recall=.8, human_agreement=.7, unsupported_false_positive_rate=.1)
        assert policy_activation_valid(policy)
        unmeasured = import_policy_version(session, created_by_name="다른 운영자")
        assert unmeasured.id != policy.id
        assert import_policy_version(session, created_by_name="세 번째 운영자").id == unmeasured.id


def test_measured_profile_policy_import_requires_and_matches_expected_policy_hash(engine, monkeypatch):
    profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
    monkeypatch.setattr(
        input_versions,
        "_store_profile_source",
        lambda raw, digest: (
            f"source/profile-{digest}.md",
            len(raw),
            ObjectMetadata("source", f"source/profile-{digest}.md", digest, digest, len(raw)),
        ),
    )
    metrics = {
        "sample_hash": "a" * 64,
        "required_item_recall": .8,
        "human_agreement": .7,
        "unsupported_false_positive_rate": .1,
    }
    with Session(engine) as session:
        with pytest.raises(InputVersionError):
            import_profile_policy(session, profile_source=profile_path, actor="운영자", **metrics)
        assert session.query(ProfileVersion).count() == 0
        assert session.query(AnalysisPolicyVersion).count() == 0

        with pytest.raises(InputVersionError) as mismatch:
            import_profile_policy(
                session,
                profile_source=profile_path,
                actor="운영자",
                expected_policy_sha256="f" * 64,
                **metrics,
            )
        assert mismatch.value.code == "policy_hash_mismatch"
        assert session.query(ProfileVersion).count() == 0
        assert session.query(AnalysisPolicyVersion).count() == 0

        result = import_profile_policy(
            session,
            profile_source=profile_path,
            actor="운영자",
            expected_policy_sha256="ade63ebfafa2eec424bbb456dea1b5b21da0980eac6c484853612e37dda422e8",
            **metrics,
        )
        assert result["policy_sha256"] == "ade63ebfafa2eec424bbb456dea1b5b21da0980eac6c484853612e37dda422e8"


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
    profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
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
        profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
        profile = import_profile_version(session, profile_path, created_by_name="운영자")
        assert session.get(Run, pending.id) is not None
        evidence = session.query(ProfileEvidence).filter_by(profile_version_id=profile.id).first()
        assert evidence is not None
        evidence.quote = "tampered"
        with pytest.raises(InputVersionError):
            import_profile_version(session, profile_path, created_by_name="운영자")
        assert session.get(Run, pending.id) is not None


def test_profile_context_validates_snapshot_without_private_source_credentials(engine, monkeypatch):
    """The structure-only analysis worker must not need the source namespace."""

    with Session(engine) as session:
        profile_path = Path(__file__).parents[4] / "docs" / "reference" / "company-profile.md"
        profile = import_profile_version(session, profile_path, created_by_name="운영자")
        monkeypatch.setattr(input_versions, "_verified_profile_source", lambda _session, _rows: None)

        context = input_versions.profile_context(session, profile)

        assert context["profile_version_id"] == str(profile.id)
        assert len(context["facts"]) == 43
        assert len(context["evidence"]) > 0


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


def test_vllm_timeout_retries_twice_without_exposing_prompt():
    calls = []

    def completion_create(**kwargs):
        calls.append(kwargs)
        raise TimeoutError

    client = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, completion_create=completion_create)
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("requirements_and_evaluation", {"requirements": [{"text": "safe"}]}, {"chunking": {"retries": 2, "timeout_seconds": 300}, "stages": []})
    assert error.value.code == "timeout"
    assert len(calls) == 3
    assert all(item["timeout"] == 300.0 for item in calls)
    assert "safe" not in str(error.value)


def test_vllm_malformed_json_is_safe_error():
    response = {
        "model": MODEL_NAME,
        "choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}],
    }

    client = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, completion_create=lambda **_kwargs: response)
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("requirements_and_evaluation", {"requirements": []}, {"chunking": {"retries": 0}, "stages": []})
    assert error.value.code == "malformed_json"


def test_vllm_reasoning_is_not_returned_or_hashed():
    content = '{"claims":[],"evidence":[],"unknowns":[],"warnings":[]}'
    response = {
        "model": MODEL_NAME,
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": content, "reasoning": "private chain of thought"},
        }],
        "usage": {"prompt_tokens": 69, "completion_tokens": 48},
    }
    result = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, completion_create=lambda **_kwargs: response).invoke(
        "requirements_and_evaluation",
        {"requirements": []},
        {"chunking": {"retries": 0, "timeout_seconds": 300}, "stages": []},
    )
    assert result.raw_response == content.encode()
    assert b"private chain of thought" not in result.raw_response
    assert result.prompt_tokens == 69 and result.output_tokens == 48


def test_vllm_enforces_the_authoritative_stage_json_schema():
    seen = []
    response = {
        "model": MODEL_NAME,
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": '{"claims":[],"evidence":[],"unknowns":[],"warnings":[]}'},
        }],
    }

    def completion_create(**kwargs):
        seen.append(kwargs)
        return response

    ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, completion_create=completion_create).invoke(
        "requirements_and_evaluation",
        {},
        {"chunking": {"retries": 0, "timeout_seconds": 300}, "stages": []},
    )
    response_format = seen[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["$id"] == "bidops.deep-review-stage.v1"
    provider_evidence = response_format["json_schema"]["schema"]["$defs"]["evidence"]
    assert "allOf" not in provider_evidence
    assert set(provider_evidence["required"]) >= {"source_kind", "document_version_id", "structure_id", "locator_type", "quote", "source_sha256"}
    assert seen[0]["temperature"] == 0.7 and seen[0]["top_p"] == 0.8 and seen[0]["seed"] == 0
    assert seen[0]["extra_body"] == {"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}}


def test_vllm_length_finish_reason_is_safe_truncated_json_error():
    response = {
        "model": MODEL_NAME,
        "choices": [{"finish_reason": "length", "message": {"content": '{"claims":['}}],
    }
    client = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, completion_create=lambda **_kwargs: response)
    with pytest.raises(ModelInvocationError) as error:
        client.invoke("requirements_and_evaluation", {}, {"chunking": {"retries": 0}, "stages": []})
    assert error.value.code == "truncated_json"


@pytest.mark.parametrize("base_url", [
    "http://127.0.0.1:8000/v1/models",
    "http://user:pass@127.0.0.1:8000/v1",
    "http://127.0.0.1:8000/v1?secret=1",
    "http://127.0.0.1:8000/v1#fragment",
])
def test_vllm_base_url_is_exact_openai_compatible_url(base_url):
    with pytest.raises(ValueError):
        ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, base_url=base_url)


@pytest.mark.parametrize("base_url", ["https://127.0.0.1:8000/v1", "http://127.0.0.1/v1"])
def test_vllm_base_url_allows_https_and_the_default_port(base_url):
    """MVP 기간에는 scheme과 명시 포트를 강제하지 않는다 (ADR-0050 완화)."""

    client = ModelClient(
        model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT,
        base_url=base_url, completion_create=lambda **_kwargs: {},
    )
    assert client.base_url == base_url


def test_remote_vllm_ip_must_be_an_exact_explicit_allowlist_entry(monkeypatch):
    base_url = "http://10.23.45.67:58765/v1"
    monkeypatch.setenv("BIDOPS_VLLM_ALLOWED_HOSTS", "10.23.45.68")
    with pytest.raises(ValueError):
        ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, base_url=base_url)

    monkeypatch.setenv("BIDOPS_VLLM_ALLOWED_HOSTS", "10.23.45.67")
    client = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, base_url=base_url, completion_create=lambda **_kwargs: {})
    assert client.base_url == base_url

    # 목록이 비면 제한이 없다(ADR-0050 완화). 승인 경계는 host 방화벽과 overlay다.
    monkeypatch.setenv("BIDOPS_VLLM_ALLOWED_HOSTS", "")
    unrestricted = ModelClient(model=MODEL_NAME, output_contract=DEEP_REVIEW_STAGE_CONTRACT, base_url=base_url, completion_create=lambda **_kwargs: {})
    assert unrestricted.base_url == base_url


def test_vllm_retention_is_clamped_to_one_to_ninety(monkeypatch):
    seen = []

    class Store:
        def put_encrypted(self, data, *, retention_days, content_type):
            seen.append((len(data), retention_days, content_type))
            return {"encrypted": True, "object_key": "model-response/fixture", "encryption_key_ref": "fixture", "plaintext_sha256": hashlib.sha256(data).hexdigest(), "plaintext_size_bytes": len(data)}

    from app.core.model_client import InvocationResult
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
    from app.deep_review.services.deep_reviews import _safe_invocation_metadata
    persisted = [_safe_invocation_metadata(item) for item in safe]
    assert all("locator" not in str(item) and "object_key" not in str(item) for item in persisted)
    # 검증 재시도 관측(seed·보정 digest·사고 블록 길이)은 남고 본문은 남지 않는다.
    observation = {"slice_index": 0, "attempts": [{
        "retry_index": 0, "status": "failed", "error_code": "malformed_json", "latency_ms": 1,
        "seed": 1, "correction_sha256": "c" * 64, "thinking_stripped": True, "thinking_chars": 12,
        "correction": "must-not-persist", "prompt": "must-not-persist",
    }]}
    kept = _safe_invocation_metadata(observation)["attempts"][0]
    assert kept == {
        "retry_index": 0, "status": "failed", "error_code": "malformed_json", "latency_ms": 1,
        "seed": 1, "correction_sha256": "c" * 64, "thinking_stripped": True, "thinking_chars": 12,
    }


def test_lease_budget_and_worker_id_are_bounded():
    service = DeepReviewService(lease_seconds=1)
    assert service.lease_seconds >= 960
    with pytest.raises(Exception):
        service.claim_next_job(None, "worker id with spaces")


def test_requirements_are_bounded_at_20_and_24000_characters():
    service = DeepReviewService()
    blocks = [{"block_key": f"b-{index}", "page": index + 1, "text": "요구사항 " + ("x" * 900)} for index in range(55)]
    document_version_id = str(uuid4())
    bundle = {"documents": [{"ordinal": 0, "document_version_id": document_version_id, "structure_id_at_confirmation": "s-1", "content_sha256": "c" * 64}]}
    groups = service._requirements(bundle, {"s-1": {"blocks": blocks}})
    assert len(groups) >= 3
    assert all(len(group) <= 20 for group in groups)
    assert all(item["document_version_id"] == document_version_id and item["structure_id"] == "s-1" and item["source_sha256"] == "c" * 64 for group in groups for item in group)
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


def test_document_quote_whitespace_is_resolved_only_for_one_exact_source_span():
    structure_id = str(uuid4())
    payload = {
        "evidence": [{
            "source_kind": "document", "structure_id": structure_id,
            "locator_type": "page", "locator": {"page": 1},
            "quote": "제안서 제출 기한",
        }],
    }
    structures = {
        structure_id: {
            "blocks": [{"page": 1, "block_key": "b-1", "text": "제안서   제출\n기한은 별도 공지"}],
        },
    }

    resolved = _resolve_exact_evidence_quotes(payload, structures)
    assert resolved["evidence"][0]["quote"] == "제안서   제출\n기한"
    assert payload["evidence"][0]["quote"] == "제안서 제출 기한"

    structures[structure_id]["blocks"].append({"page": 1, "block_key": "b-2", "text": "제안서\t제출 기한"})
    ambiguous = _resolve_exact_evidence_quotes(payload, structures)
    assert ambiguous["evidence"][0]["quote"] == "제안서 제출 기한"


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


def _seed_review_context(engine, monkeypatch, *, measured: bool = True):
    with Session(engine) as session:
        run = Run(id=f"t5-{uuid4()}")
        notice = Notice(run=run, notice_key=f"t5-notice-{uuid4()}")
        session.add(Judgment(notice=notice, grade="우선 검토", readiness="확인 완료"))
        session.add_all([run, notice])
        session.flush()
        bundle = DocumentBundle(id=uuid4(), notice_id=notice.id, revision=1, version=1, status="ready", issues_snapshot=[], confirmed_by_name="담당자")
        # profile·policy version은 전역 유일하다. 한 engine에서 여러 번 seed 하는
        # 검사가 있으므로 이미 있는 값 다음 번호를 쓴다.
        next_profile_version = int(session.query(ProfileVersion).count()) + 1
        next_policy_version = int(session.query(AnalysisPolicyVersion).count()) + 1
        profile_hash = hashlib.sha256(f"profile-{next_profile_version}".encode()).hexdigest()
        content_hash = hashlib.sha256(f"content-{next_profile_version}".encode()).hexdigest()
        structure_hash = hashlib.sha256(f"structure-{next_profile_version}".encode()).hexdigest()
        profile = ProfileVersion(id=uuid4(), version=next_profile_version, label="profile", profile_payload={"schema": "bidops.company-profile.v1", "source_file": "docs/reference/company-profile.md", "source_sha256": profile_hash, "facts": [{"fact_key": f"fixture.fact[{index}]", "status": "unknown", "quote": "fixture"} for index in range(39)]}, profile_sha256=profile_hash, source_kind="fixture")
        policy_payload, _canonical, policy_hash = load_canonical_policy()
        # 측정값이 없는 policy는 `import-profile-policy`를 품질 인자 없이 실행한
        # row와 같은 모양이다. 참조 실행 게이트가 그 row를 어떻게 다루는지
        # 확인하려면 두 모양이 다 필요하다.
        quality_rules = {"sample_hash": "b" * 64, "required_item_recall": .8, "human_agreement": .7, "unsupported_false_positive_rate": .1} if measured else {}
        policy = AnalysisPolicyVersion(id=uuid4(), version=next_policy_version, label="policy", model_endpoint_ref="vllm-openai-compatible", model_name=MODEL_NAME, prompts=policy_payload["stages"], validation_rules={**policy_payload["validation"], "generation": policy_payload["generation"], **quality_rules}, policy_sha256=policy_hash)
        content_id = uuid4()
        from app.deep_review.models import ContentObject
        content = ContentObject(id=content_id, sha256=content_hash, size_bytes=0, detected_mime="application/json", retention_class="fixture")
        document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content_id, version=1, source_kind="manual", original_filename="fixture.pdf", role="기타", is_current=True, safety_status="safe")
        structure = DocumentStructure(id=uuid4(), document_version_id=document.id, source_sha256=content_hash, media_type="application/pdf", extractor_name="fixture", extractor_version="1", payload_content_object_id=content_id, payload_sha256=structure_hash, page_count=1, block_count=0, validation_status="ready")
        item = DocumentBundleItem(bundle_id=bundle.id, document_version_id=document.id, ordinal=0, document_version_version=1, content_object_id=content_id, content_sha256=content_hash, detected_mime="application/pdf", size_bytes=0, original_filename="fixture.pdf", source_kind="manual", role_at_confirmation="기타", is_current_at_confirmation=True, safety_status_at_confirmation="safe", structure_id_at_confirmation=structure.id, structure_payload_sha256=structure_hash)
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


def test_deep_review_audit_lineage_is_inherited_by_retry(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    correlation = UUID("33333333-3333-3333-3333-333333333333")
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="document_bundle.create",
            aggregate_type="document_bundle", aggregate_id=str(bundle_id),
            safe_metadata={"correlation_id": str(correlation)},
        ))
        session.commit()
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review_id = UUID(created["id"])
        creation = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.create", AuditEvent.aggregate_id == str(review_id),
        ))
        assert creation is not None
        assert creation.safe_metadata["correlation_id"] == str(correlation)

        review = session.get(DeepReview, review_id)
        assert review is not None and review.current_attempt_id is not None
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        assert attempt is not None
        job = session.get(WorkJob, attempt.work_job_id)
        assert job is not None
        attempt.status = "failed"
        review.status = "failed"
        job.status = "failed"
        session.commit()

        retried = service.create_attempt(session, review_id, "담당자", uuid4())
        assert retried["sequence"] == 2
        retry_audit = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.attempt",
            AuditEvent.aggregate_id == str(review_id),
            AuditEvent.safe_metadata["attempt_id"].as_string() == retried["id"],
        ))
        assert retry_audit is not None
        assert retry_audit.safe_metadata["correlation_id"] == str(correlation)


def test_legacy_bundle_lineage_remains_absent_without_backfill(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="document_bundle.create",
            aggregate_type="document_bundle", aggregate_id=str(bundle_id), safe_metadata={},
        ))
        session.commit()
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        creation = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.create", AuditEvent.aggregate_id == created["id"],
        ))
        assert creation is not None and "correlation_id" not in creation.safe_metadata


def test_invalid_bundle_lineage_fails_closed(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="document_bundle.create",
            aggregate_type="document_bundle", aggregate_id=str(bundle_id),
            safe_metadata={"correlation_id": None},
        ))
        session.commit()
        with pytest.raises(DeepReviewServiceError) as error:
            service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        assert error.value.code == "processing_failed"


def test_retry_rejects_review_and_bundle_lineage_mismatch(engine, monkeypatch):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        session.add(AuditEvent(
            actor_kind="human", claimed_name="담당자", action="document_bundle.create",
            aggregate_type="document_bundle", aggregate_id=str(bundle_id),
            safe_metadata={"correlation_id": str(uuid4())},
        ))
        session.commit()
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        review = session.get(DeepReview, UUID(created["id"]))
        assert review is not None and review.current_attempt_id is not None
        attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
        job = session.get(WorkJob, attempt.work_job_id) if attempt is not None else None
        assert attempt is not None and job is not None
        attempt.status = "failed"
        review.status = "failed"
        job.status = "failed"
        creation = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.create", AuditEvent.aggregate_id == str(review.id),
        ))
        assert creation is not None
        creation.safe_metadata = {"correlation_id": str(uuid4())}
        session.commit()

        with pytest.raises(DeepReviewServiceError) as error:
            service.create_attempt(session, review.id, "담당자", uuid4())
        assert error.value.code == "processing_failed"


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
            from app.core.model_client import InvocationResult
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
            from app.core.model_client import InvocationResult
            if stage == "delivery_risk_economics":
                raise ModelInvocationError("timeout", ({"retry_index": 0, "status": "failed", "error_code": "timeout"},))
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
            from app.core.model_client import InvocationResult
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
            from app.core.model_client import InvocationResult
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


# --- 참조 실행 모드(§6.5)와 quality_status(§8) ---------------------------------
#
# 아래 검사는 **fake transport**만 쓴다. 실제 vLLM·Ollama 주소를 부르지 않고,
# `ModelClient`의 요청 조립·identity 확인·응답 해석 경로는 그대로 통과시킨다.

_DEEP_REVIEW_REVISION = "c" * 64


class _FixtureStore:
    def put_encrypted(self, data, *, retention_days, content_type):
        digest = hashlib.sha256(data).hexdigest()
        return {"object_key": f"model-response/{digest}", "encryption_key_ref": "fixture", "encrypted": True, "plaintext_sha256": digest, "plaintext_size_bytes": len(data)}


def _fake_chat_completion(**kwargs):
    """`/v1/chat/completions` 응답 모양만 흉내 내는 fake 전송이다."""

    prompt = json.loads(kwargs["messages"][1]["content"])
    payload = _valid_stage_payload(prompt["input_slice"], prompt["stage"])
    return {
        "model": kwargs["model"],
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _fake_model_client_class(served: list[str] | None = None):
    """용도별 설정 해석과 identity 확인은 진짜로 하고 전송만 fake로 바꾼다."""

    class FakeTransportModelClient(ModelClient):
        @classmethod
        def for_purpose(cls, purpose, *, model, output_contract, **kwargs):
            kwargs.setdefault("completion_create", _fake_chat_completion)
            kwargs.setdefault("models_list", lambda: {"data": [{"id": name} for name in (served if served is not None else [model])]})
            return super().for_purpose(purpose, model=model, output_contract=output_contract, **kwargs)

    return FakeTransportModelClient


def _vllm_env(
    monkeypatch,
    *,
    reference: bool,
    allowed_hosts: str = "127.0.0.1",
    revision: str = _DEEP_REVIEW_REVISION,
    base_url: str = "http://127.0.0.1:8000/v1",
):
    monkeypatch.setenv("BIDOPS_ANALYSIS_PROVIDER", "vllm")
    monkeypatch.setenv("BIDOPS_OPENAI_ENABLED", "false")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true" if reference else "false")
    monkeypatch.setenv("BIDOPS_VLLM_ALLOWED_HOSTS", "")
    monkeypatch.setenv("BIDOPS_VLLM_MODEL_REVISION", "")
    monkeypatch.setenv("BIDOPS_VLLM_DEEP_REVIEW_BASE_URL", base_url)
    monkeypatch.setenv("BIDOPS_VLLM_DEEP_REVIEW_ALLOWED_HOSTS", allowed_hosts)
    monkeypatch.setenv("BIDOPS_VLLM_DEEP_REVIEW_MODEL_REVISION", revision)
    get_settings.cache_clear()


@pytest.fixture
def clear_settings_cache():
    yield
    get_settings.cache_clear()


def test_reference_mode_runs_unmeasured_policy_through_vllm_to_a_report(engine, monkeypatch, clear_settings_cache):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch, measured=False)
    _vllm_env(monkeypatch, reference=True)
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class())
    service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    assert service.reference_workflow_mode is True
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        creation = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.create", AuditEvent.aggregate_id == created["id"],
        ))
        assert creation is not None
        assert creation.safe_metadata["policy_quality"] == {"status": "reference_workflow_unmeasured", "deployable": False}
        assert creation.safe_metadata["analysis_provider"] == MODEL_ENDPOINT_REF
        assert creation.safe_metadata["runtime_model"] == MODEL_NAME
        assert creation.safe_metadata["reference_workflow_mode"] is True
        claim = service.claim_next_job(session, "worker-reference")
        assert claim is not None
        service.run_claim(session, claim)
        view = service.view(session, UUID(created["id"]))
        assert view["status"] == "completed"
        assert view["quality_status"] == "unmeasured_reference"
        assert [stage["status"] for stage in view["current_attempt"]["stages"]] == ["completed"] * 3
        report = ReportService().get_report(session, UUID(created["id"]))
        assert report["report"]["quality_status"] == "unmeasured_reference"


def test_unmeasured_policy_without_reference_mode_stays_service_unavailable(engine, monkeypatch, clear_settings_cache):
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch, measured=False)
    _vllm_env(monkeypatch, reference=False)
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class())
    service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    assert service.reference_workflow_mode is False
    with Session(engine) as session:
        with pytest.raises(InputVersionError) as error:
            service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        assert error.value.code == "service_unavailable"
        assert session.query(DeepReview).count() == 0


def test_reference_created_review_fails_closed_when_the_runner_is_not_in_reference_mode(engine, monkeypatch, clear_settings_cache):
    # 측정값이 있는 policy로 만들어 "생성과 실행의 모드가 다르다"만 실패 사유로 남긴다.
    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    _vllm_env(monkeypatch, reference=True)
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class())
    service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-reference")
        assert claim is not None
        _vllm_env(monkeypatch, reference=False)
        runner = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
        assert runner.reference_workflow_mode is False
        with pytest.raises(DeepReviewServiceError) as error:
            runner.run_claim(session, claim)
        assert error.value.code == "service_unavailable" and error.value.status_code == 503
        assert service.view(session, UUID(created["id"]))["status"] == "failed"


def test_quality_status_separates_measured_reference_and_mock_runs(engine, monkeypatch, clear_settings_cache):
    measured_notice, measured_bundle, _p, _q = _seed_review_context(engine, monkeypatch)
    _vllm_env(monkeypatch, reference=False)
    measured_service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        measured = measured_service.create_review(session, measured_notice, measured_bundle, "담당자", uuid4())
        assert measured_service.view(session, UUID(measured["id"]))["quality_status"] == "measured"

    reference_notice, reference_bundle, _p, _q = _seed_review_context(engine, monkeypatch, measured=False)
    _vllm_env(monkeypatch, reference=True)
    reference_service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        reference = reference_service.create_review(session, reference_notice, reference_bundle, "담당자", uuid4())
        assert reference_service.view(session, UUID(reference["id"]))["quality_status"] == "unmeasured_reference"

    mock_notice, mock_bundle, _p, _q = _seed_review_context(engine, monkeypatch, measured=False)
    monkeypatch.setenv("BIDOPS_ANALYSIS_PROVIDER", "mock")
    monkeypatch.setenv("BIDOPS_REFERENCE_WORKFLOW_MODE", "true")
    get_settings.cache_clear()
    mock_service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        mocked = mock_service.create_review(session, mock_notice, mock_bundle, "담당자", uuid4())
        assert mock_service.view(session, UUID(mocked["id"]))["quality_status"] == "mock_reference"


def test_deep_review_model_client_is_built_for_its_own_purpose_and_rejects_wrong_values(engine, monkeypatch, clear_settings_cache):
    """용도별 설정이 어긋나면 호출 전에 멈춘다.

    MVP 기간에는 허용 host와 선언 revision이 **비어 있는** 것은 통과하지만
    (ADR-0050 완화), 목록 밖의 host와 64자가 아닌 revision은 그대로 막힌다.
    identity 확인(`model_not_served`)도 완화하지 않는다.
    """

    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    # loopback은 언제나 허용되므로 목록 밖 host는 loopback이 아닌 주소로 본다.
    _vllm_env(
        monkeypatch, reference=False,
        base_url="http://10.23.45.68:8000/v1", allowed_hosts="10.23.45.67",
    )
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class())
    service = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        claim = service.claim_next_job(session, "worker-wrong-host")
        assert claim is not None
        with pytest.raises(DeepReviewServiceError) as error:
            service.run_claim(session, claim)
        assert error.value.code == "service_unavailable" and error.value.status_code == 503

    other_notice, other_bundle, _p, _q = _seed_review_context(engine, monkeypatch)
    _vllm_env(monkeypatch, reference=False, revision="not-a-digest")
    bad_revision = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        bad_revision.create_review(session, other_notice, other_bundle, "담당자", uuid4())
        claim = bad_revision.claim_next_job(session, "worker-bad-revision")
        assert claim is not None
        with pytest.raises(DeepReviewServiceError) as error:
            bad_revision.run_claim(session, claim)
        assert error.value.code == "service_unavailable"

    served_notice, served_bundle, _p, _q = _seed_review_context(engine, monkeypatch)
    # 두 값이 비어 있어도 설정 해석은 통과하고 identity 확인까지 간다.
    _vllm_env(monkeypatch, reference=False, allowed_hosts="", revision="")
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class(served=["다른-모델"]))
    identity = DeepReviewService(raw_response_store=_FixtureStore(), structure_loader=_fixture_structure)
    with Session(engine) as session:
        identity.create_review(session, served_notice, served_bundle, "담당자", uuid4())
        claim = identity.claim_next_job(session, "worker-not-served")
        assert claim is not None
        with pytest.raises(DeepReviewServiceError) as error:
            identity.run_claim(session, claim)
        assert error.value.code == "model_not_served"


def test_the_analysis_client_cache_is_keyed_on_the_policy_model_name(
    monkeypatch, clear_settings_cache
):
    """policy가 다른 모델을 지정하면 다른 client를 묶는다 (명세 §6.6).

    `DeepReviewWorker`는 서비스 하나를 job 사이에 들고 있다. 캐시가 모델명을
    무시하면 policy A로 만든 client가 policy B에 고정된 job에 그대로 돌아가고,
    `_runtime_identity`도 그 client의 모델명을 감사에 남긴다.
    """

    from types import SimpleNamespace

    _vllm_env(monkeypatch, reference=False)
    monkeypatch.setattr(deep_reviews_module, "ModelClient", _fake_model_client_class())
    service = DeepReviewService(
        raw_response_store=_FixtureStore(), structure_loader=_fixture_structure
    )
    assert service.client is None

    first = service._bind_client("합성-모델-a")
    assert first.model == "합성-모델-a"
    # 같은 모델명이면 다시 만들지 않는다.
    assert service._bind_client("합성-모델-a") is first

    second = service._bind_client("합성-모델-b")
    assert second is not first
    assert second.model == "합성-모델-b"

    # 감사에 남길 identity는 policy가 고정한 모델을 따라간다.
    assert service._runtime_identity(SimpleNamespace(model_name="합성-모델-a"))[1] == "합성-모델-a"
    assert service._runtime_identity(SimpleNamespace(model_name="합성-모델-b"))[1] == "합성-모델-b"


def test_an_injected_client_is_never_rebound_by_the_model_name(monkeypatch, clear_settings_cache):
    """주입·mock client는 호출자의 계약이므로 모델명으로 갈아 끼우지 않는다."""

    _vllm_env(monkeypatch, reference=False)

    class _Injected:
        model = "주입된-모델"
        provider_name = "injected-analysis-client"

    injected = _Injected()
    service = DeepReviewService(
        client=injected, raw_response_store=_FixtureStore(), structure_loader=_fixture_structure
    )
    assert service._bind_client("합성-모델-a") is injected
    assert service._bind_client("합성-모델-b") is injected


def test_the_overview_flag_makes_sw_business_eligible_without_a_grade(
    engine, monkeypatch, clear_settings_cache
):
    """MVP 완화(2026-09-11): 플래그가 켜져 있으면 `SW사업대상=Y`도 심층 자격이다.

    자격만 넓히고 등급은 접지 않는다 — `effective_grade_at_start`는 등급 없음
    표식 그대로 남는다. 플래그가 꺼지면 같은 공고가 다시 403이다.
    """

    notice_id, bundle_id, _profile_id, _policy_id = _seed_review_context(engine, monkeypatch)
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    get_settings.cache_clear()
    with Session(engine) as session:
        judgment = session.scalar(select(Judgment).where(Judgment.notice_id == notice_id))
        session.delete(judgment)
        notice = session.get(Notice, notice_id)
        notice.source_type = "pre_spec"
        notice.qualification_flags_json = {"sw_business_status": "Y"}
        session.commit()

    service = DeepReviewService(structure_loader=_fixture_structure)
    with Session(engine) as session:
        created = service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
        row = session.get(DeepReview, UUID(created["id"]))
        assert row is not None and row.effective_grade_at_start == "unknown"

    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    with Session(engine) as session:
        with pytest.raises(DeepReviewServiceError) as error:
            service.create_review(session, notice_id, bundle_id, "담당자", uuid4())
    assert error.value.code == "effective_grade_ineligible"
