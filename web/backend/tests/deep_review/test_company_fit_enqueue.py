"""DEMO-03 STEP-002/STEP-008 company-fit policy import and enqueue gates (spec T2·T4·T8).

The world is built through the real DEMO-02 registration services from the
frozen ``docs/demo-fixtures`` ontology and company source, plus a ready
document bundle whose structure payload is really stored (in-memory object
store) and read back by the production loader.  No model or network is
called: every test here stops before the runner.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    CompanyFitPolicyVersion,
    ContentObject,
    ContentObjectLocation,
    DocumentBundle,
    DocumentBundleItem,
    DocumentSegmentManifest,
    DocumentStructure,
    DocumentVersion,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    WorkJob,
)
from app.deep_review.services import assets, document_segments
from app.deep_review.services import company_fit as fit
from app.deep_review.services import company_fit_policy as fit_policy
from app.deep_review.services.company_fit_policy import (
    CompanyFitPolicyError,
    build_demo_policy_payload,
    import_company_fit_policy,
    load_company_fit_policy_file,
    validate_company_fit_policy,
)
from app.deep_review.services.company_knowledge_retrieval import validate_source_unit
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
    prepare_company_knowledge,
    prepare_company_knowledge_files,
)
from app.deep_review.services.input_versions import canonical_json_hash
from app.lifecycle import register_company
from app.lifecycle.models import Notice
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - shared fixtures
    engine,
    object_store,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parents[1]
FIXTURES = PROJECT_ROOT / "docs" / "demo-fixtures"
ONTOLOGY_FILE = FIXTURES / "ontology.v1.json"
DEFAULT_COMPANY = "demo-data-ai"
POLICY_DIR = BACKEND_ROOT / "app" / "deep_review" / "policies"
#: v2 is kept history (importable, never selected by a new enqueue); v3 adds
#: ``chunking.source_characters`` (contract §9, 2026-10-11).
POLICY_V2_FILE = POLICY_DIR / "company-fit-demo-v2.json"
POLICY_V3_FILE = POLICY_DIR / "company-fit-demo-v3.json"
SCHEMA_V2 = "bidops.company-fit-policy.v2"
SCHEMA_V3 = "bidops.company-fit-policy.v3"
SOURCE_CHARACTERS = 6000

#: Source text of the fixture document (page -> one paragraph block).  The
#: company deep-review fixtures reuse this text, so fit and deep units of one
#: bundle are the same splitter output.  Overview evidence page 4 has no block.
TEXTS = {
    1: "데이터 플랫폼 구축 및 데이터 품질·관리 체계 수립을 수행한다.",
    2: "정보보호 관리 인증 보유 여부를 제출한다.",
    3: "제안사는 기관 내부망에서 검색 서비스를 구축하고 시험 결과와 운영 매뉴얼을 제출해야 한다.",
}
#: Same pages with leading requirement ids: three leading occurrences confirm
#: the ``SFR`` prefix in the real segment-manifest builder.
REQUIREMENT_TEXTS = {page: f"SFR-00{page} {body}" for page, body in TEXTS.items()}

OVERVIEW_RESULT = {
    "schema_version": "bidops.prespec-overview-claims.v2",
    "business_overview": [
        {"claim_id": "c1", "text": "공공기관 업무 데이터를 통합하는 사업이다.",
         "evidence": [{"page": 1, "quote": "업무 데이터를 통합"}]},
    ],
    "main_tasks": [
        {"claim_id": "c2", "text": "데이터 플랫폼 구축과 데이터 품질·관리 체계 수립을 수행한다.",
         "evidence": [{"page": 2, "quote": "데이터 플랫폼 구축"}]},
        {"claim_id": "c3", "text": "정보보호 관리 인증 보유 여부를 확인한다.",
         "evidence": [{"page": 3, "quote": "정보보호 관리 인증"}]},
    ],
    "budget_and_period": [
        {"claim_id": "c4", "text": "사업 기간은 6개월이다.", "evidence": [{"page": 4, "quote": "6개월"}]},
    ],
    "input_limitations": [],
}

ENQUEUE_KEYS = {"company_id", "notice_id", "attempt_id", "input_sha256", "created", "errors"}
POLICY_KEYS = {"policy_version_id", "sha256", "created", "errors"}


def configure(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    values: dict[str, str | None] = {
        "BIDOPS_DEMO_ENABLED": "true",
        "BIDOPS_PRESPEC_COMPANY_FIT_ENABLED": "true",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
        "BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://127.0.0.1:9/v1",
        "BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS": "127.0.0.1",
        "BIDOPS_VLLM_OVERVIEW_API_DIALECT": "litellm",
        "BIDOPS_VLLM_OVERVIEW_MODEL_REVISION": "",
        # The legacy single-company automation stays unconfigured in this world.
        "BIDOPS_PRESPEC_COMPANY_FIT_MODEL": None,
        "BIDOPS_ACTIVE_PROFILE_VERSION_ID": None,
        "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": None,
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@dataclass(frozen=True)
class World:
    company_id: UUID
    graph_version_id: UUID
    profile_version_id: UUID
    notice_id: int
    run_id: UUID
    document_id: UUID
    content_sha256: str
    policy_id: UUID
    policy_sha256: str
    bundle_id: UUID | None = None


def structure_payload(structure: DocumentStructure, texts: dict[int, str] = TEXTS) -> dict:
    """A closed ``bidops.document-structure.v1`` payload: one paragraph block per page."""

    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(structure.id),
        "document_version_id": str(structure.document_version_id),
        "source_sha256": structure.source_sha256,
        "media_type": structure.media_type,
        "extractor": {"name": structure.extractor_name, "version": structure.extractor_version,
                      "upstream_commit": structure.upstream_commit},
        "pages": [{"number": page, "width": 612, "height": 792, "image_content_object_id": None} for page in texts],
        "blocks": [{"block_key": f"source-{page}", "parent_block_key": None, "type": "paragraph", "page": page,
                    "bbox": None, "text": body, "confidence": None, "attributes": {}} for page, body in texts.items()],
        "warnings": [], "created_at": "2026-10-09T00:00:00+09:00",
    }


def store_structure(session: Session, document: DocumentVersion, texts: dict[int, str] = TEXTS, *,
                    manifest: bool = False) -> DocumentStructure:
    """A ready structure whose payload object is stored and readable by the production loader.

    The payload goes through ``assets.store_named`` (the autouse in-memory
    ``object_store`` fixture) with a verified ``structure`` location, exactly
    what ``input_versions._structure_payload`` reads back.  ``manifest=True``
    also stores the real deterministic segment manifest of that payload.
    """

    content = session.get(ContentObject, document.content_object_id)
    structure = DocumentStructure(
        id=uuid4(), document_version_id=document.id, source_sha256=content.sha256,
        extractor_name="fixture", extractor_version="1", upstream_commit=None, page_count=len(texts),
        block_count=len(texts), validation_status="ready", media_type="application/pdf",
    )
    payload = structure_payload(structure, texts)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    _path, metadata = assets.store_named("structure", f"structure/{digest}.json", raw, content_type="application/json")
    stored = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(raw), detected_mime="application/json",
                           retention_class="document-structure")
    session.add(stored)
    session.flush()
    session.add(ContentObjectLocation(
        content_object_id=stored.id, namespace_key="structure", object_key=metadata.object_key,
        object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified",
        verified_at=datetime.now(UTC),
    ))
    structure.payload_content_object_id, structure.payload_sha256 = stored.id, digest
    session.add(structure)
    session.flush()
    if manifest:
        document_segments.store_manifest(session, payload)
    return structure


def ready_bundle(session: Session, notice_id: int, document_id: UUID, *, revision: int = 1,
                 texts: dict[int, str] = TEXTS, manifest: bool = False) -> UUID:
    """A confirmed ready bundle over one document with a really stored structure.

    A document version has one structure; a later bundle revision reuses it.
    """

    document = session.get(DocumentVersion, document_id)
    content = session.get(ContentObject, document.content_object_id)
    structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
    if structure is None:
        structure = store_structure(session, document, texts, manifest=manifest)
    bundle = DocumentBundle(id=uuid4(), notice_id=notice_id, revision=revision, version=1, status="ready",
                            issues_snapshot=[], created_by_name="준비 담당자", confirmed_by_name="준비 담당자",
                            confirmed_at=datetime.now(UTC))
    session.add(bundle)
    session.flush()
    session.add(DocumentBundleItem(
        bundle_id=bundle.id, document_version_id=document.id, ordinal=0, document_version_version=1,
        content_object_id=content.id, content_sha256=content.sha256, detected_mime="application/pdf",
        size_bytes=10, original_filename="제안요청서.pdf", source_kind="manual", role_at_confirmation="제안요청서",
        is_current_at_confirmation=True, safety_status_at_confirmation="safe",
        structure_id_at_confirmation=structure.id, structure_payload_sha256=structure.payload_sha256,
    ))
    session.flush()
    return bundle.id


def import_company(session: Session, slug: str = DEFAULT_COMPANY, *, activate: bool = True, raw: bytes | None = None):
    if raw is None:
        prepared = prepare_company_knowledge_files(ONTOLOGY_FILE, FIXTURES / "companies" / f"{slug}.v1.json")
    else:
        prepared = prepare_company_knowledge(ONTOLOGY_FILE.read_bytes(), raw)
    imported = import_company_knowledge(session, prepared, actor="등록 담당자")
    if activate:
        activate_company_knowledge(
            session, company_id=imported.company_id,
            graph_version_id=imported.graph_version_id, actor="활성 담당자",
        )
    session.flush()
    return imported


def seed_notice(session: Session, *, sw: str = "Y", result: dict | None = None,
                status: str = "completed", contract_version: str = "overview-v1"):
    notice = Notice(notice_key=f"demo-fit:{uuid4()}", source_type="pre_spec", title="데모 사전규격",
                    qualification_flags_json={"sw_business_status": sw})
    session.add(notice)
    session.flush()
    digest = uuid4().hex + uuid4().hex
    content = ContentObject(id=uuid4(), sha256=digest, size_bytes=10,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add(content)
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=1,
                               source_kind="manual", original_filename="제안요청서.pdf", role="제안요청서",
                               is_current=True, safety_status="safe")
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    completed = status == "completed"
    run = PrespecOverviewRun(
        id=uuid4(), notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
        status=status, range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="local-agent-main", warnings_json=[], reason_codes=[], call_count=1,
        raw_response_refs=[], result_json=deepcopy(result or OVERVIEW_RESULT) if completed else None,
        checks_json={"overall": "passed"} if completed else None,
        contract_version=contract_version,
        completed_at=datetime.now(UTC) if completed else None,
    )
    session.add(run)
    session.flush()
    return notice, document, content, run


def build_world(session: Session, monkeypatch: pytest.MonkeyPatch, *, slug: str = DEFAULT_COMPANY,
                sw: str = "Y", activate: bool = True, bundle: bool = True,
                texts: dict[int, str] = TEXTS, manifest: bool = False,
                policy_file: Path = POLICY_V3_FILE) -> World:
    """The company-fit world: company, SW=Y notice + completed v7 overview, v3 fit policy.

    ``bundle=True`` (default) adds the ready bundle a fit requires (contract §9,
    2026-10-11); deep-review worlds pass ``bundle=False`` and build their own.
    """

    configure(monkeypatch)
    imported = import_company(session, slug, activate=activate)
    notice, document, content, run = seed_notice(session, sw=sw)
    bundle_id = ready_bundle(session, notice.id, document.id, texts=texts, manifest=manifest) if bundle else None
    policy = import_company_fit_policy(session, policy_file, actor="정책 담당자")
    session.commit()
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(policy.policy_version_id))
    return World(
        company_id=imported.company_id, graph_version_id=imported.graph_version_id,
        profile_version_id=imported.profile_version_id, notice_id=notice.id, run_id=run.id,
        document_id=document.id, content_sha256=content.sha256,
        policy_id=policy.policy_version_id, policy_sha256=policy.sha256, bundle_id=bundle_id,
    )


def enqueue(session: Session, world: World, *, dry_run: bool = False, company_id: UUID | None = None,
            notice_id: int | None = None, actor: str = "핏 담당자"):
    result = fit.enqueue_company_fit(
        session, company_id=company_id or world.company_id,
        notice_id=world.notice_id if notice_id is None else notice_id,
        actor=actor, dry_run=dry_run,
    )
    session.commit()
    return result


def gate_code(session: Session, world: World, **kwargs) -> str:
    with pytest.raises(fit.CompanyFitGateError) as error:
        fit.enqueue_company_fit(
            session, company_id=kwargs.pop("company_id", world.company_id),
            notice_id=kwargs.pop("notice_id", world.notice_id), actor=kwargs.pop("actor", "핏 담당자"),
            dry_run=kwargs.pop("dry_run", False),
        )
    session.rollback()
    return error.value.code


def counts(session: Session) -> tuple[int, int]:
    return (
        int(session.scalar(select(func.count()).select_from(PreSpecCompanyFitAttempt)) or 0),
        int(session.scalar(select(func.count()).select_from(AuditEvent)) or 0),
    )


@pytest.fixture
def sqlite_engine():
    """Isolated SQLite for the gate matrix; PostgreSQL runs the E2E (``engine``)."""

    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture
def world_session(sqlite_engine, monkeypatch):
    with Session(sqlite_engine) as session:
        yield session, build_world(session, monkeypatch)
    get_settings.cache_clear()


# --- policy file and loader -------------------------------------------------------


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_demo_policy_file_is_canonical_and_built_from_the_v1_fit_policy() -> None:
    raw = POLICY_V3_FILE.read_bytes()
    payload = json.loads(raw)
    assert raw == _canonical(payload)
    assert payload == build_demo_policy_payload()
    assert set(payload) == {
        "schema_version", "model_name", "model_revision", "prompt_version", "generation",
        "stages", "system_prompt", "prompt_output_contract", "chunking",
    }
    assert payload["schema_version"] == SCHEMA_V3
    assert payload["model_name"] == "local-agent-main"
    assert payload["model_revision"] is None
    assert payload["chunking"]["path_limit_per_requirement"] == 32
    assert payload["chunking"]["retries"] == 0 and payload["chunking"]["timeout_seconds"] == 300
    assert payload["chunking"]["profile_characters"] >= 4000
    # Same splitter setting as the demo Luna policy, so fit and deep unit ids match.
    luna = json.loads((POLICY_DIR / "analysis-policy-luna-demo-v1.json").read_bytes())
    assert payload["chunking"]["source_characters"] == SOURCE_CHARACTERS == luna["chunking"]["source_characters"]
    # The v1 rules survive; graph paths are described as retrieval, never fulfilment.
    instruction = payload["stages"][0]["instruction"]
    assert payload["stages"][0]["stage"] == "company_fit"
    assert fit.INSTRUCTION.splitlines()[0] in instruction
    assert "graph_path_indexes" in instruction and "graph_paths" in instruction
    assert payload["prompt_output_contract"]["properties"]["schema_version"]["const"] == (
        "bidops.prespec-company-fit-result.v2"
    )
    loaded, canonical, digest = load_company_fit_policy_file(POLICY_V3_FILE)
    assert loaded == payload and canonical == raw and digest == canonical_json_hash(payload)


def test_v2_policy_file_is_unchanged_history_and_v3_differs_only_by_schema_and_source_characters() -> None:
    v2 = json.loads(POLICY_V2_FILE.read_bytes())
    v3 = json.loads(POLICY_V3_FILE.read_bytes())
    assert POLICY_V2_FILE.read_bytes() == _canonical(v2)
    assert v2 == build_demo_policy_payload(SCHEMA_V2)
    assert v2["schema_version"] == SCHEMA_V2 and "source_characters" not in v2["chunking"]
    expected = deepcopy(v2)
    expected["schema_version"] = SCHEMA_V3
    expected["chunking"]["source_characters"] = SOURCE_CHARACTERS
    assert v3 == expected
    # Both files are approved import files; v2 stays loadable (history).
    assert fit_policy.APPROVED_POLICY_FILES == (POLICY_V2_FILE, POLICY_V3_FILE)
    assert load_company_fit_policy_file(POLICY_V2_FILE)[0] == v2
    assert load_company_fit_policy_file(POLICY_V3_FILE)[0] == v3
    assert canonical_json_hash(v2) != canonical_json_hash(v3)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(schema_version="bidops.company-fit-policy.v1"),
    lambda p: p.update(schema_version="bidops.company-fit-policy.v4"),
    lambda p: p.update(extra=True),
    lambda p: p.pop("model_revision"),
    lambda p: p["chunking"].update(path_limit_per_requirement=0),
    lambda p: p["chunking"].update(path_limit_per_requirement="32"),
    lambda p: p["chunking"].update(path_limit_per_requirement=True),
    lambda p: p["chunking"].pop("path_limit_per_requirement"),
    # v3 requires a positive integer source_characters (no default).
    lambda p: p["chunking"].pop("source_characters"),
    lambda p: p["chunking"].update(source_characters=0),
    lambda p: p["chunking"].update(source_characters="6000"),
    lambda p: p["chunking"].update(source_characters=True),
    lambda p: p["chunking"].update(source_characters=None),
    # v2 keeps its exact chunking key set; the v3 key is not accepted there.
    lambda p: p.update(schema_version=SCHEMA_V2),
    lambda p: p.update(model_name="local agent"),
    lambda p: p.update(model_name=""),
    lambda p: p.update(model_revision="not-a-digest"),
    lambda p: p["chunking"].update(timeout_seconds=30),
    lambda p: p["generation"].update(temperature=0.1),
    lambda p: p.update(prompt_output_contract={"type": "object"}),
    lambda p: p.update(stages=[]),
])
def test_policy_loader_rejects_invalid_payloads(mutate) -> None:
    payload = deepcopy(build_demo_policy_payload())
    mutate(payload)
    with pytest.raises(CompanyFitPolicyError) as error:
        validate_company_fit_policy(payload)
    assert error.value.code == "policy_invalid"


def test_v2_payload_validates_without_source_characters_only() -> None:
    v2 = build_demo_policy_payload(SCHEMA_V2)
    assert validate_company_fit_policy(v2) == v2
    with_key = deepcopy(v2)
    with_key["chunking"]["source_characters"] = SOURCE_CHARACTERS
    with pytest.raises(CompanyFitPolicyError):
        validate_company_fit_policy(with_key)


def test_policy_file_bytes_must_be_canonical_and_approved(tmp_path: Path) -> None:
    payload = build_demo_policy_payload()
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(CompanyFitPolicyError) as error:
        load_company_fit_policy_file(pretty)
    assert error.value.code == "policy_invalid"
    unapproved = deepcopy(payload)
    unapproved["prompt_version"] = "prespec-company-fit-demo-v2-unapproved"
    path = tmp_path / "unapproved.json"
    path.write_bytes(_canonical(unapproved))
    with pytest.raises(CompanyFitPolicyError) as error:
        load_company_fit_policy_file(path)
    assert error.value.code == "policy_unapproved"
    # A valid but different split size is not the approved v3 file.
    tampered = deepcopy(payload)
    tampered["chunking"]["source_characters"] = 5000
    path.write_bytes(_canonical(tampered))
    with pytest.raises(CompanyFitPolicyError) as error:
        load_company_fit_policy_file(path)
    assert error.value.code == "policy_unapproved"


def test_policy_import_is_idempotent_append_only_and_activates_nothing(sqlite_engine, monkeypatch) -> None:
    configure(monkeypatch)
    with Session(sqlite_engine) as session:
        first = import_company_fit_policy(session, POLICY_V3_FILE, actor="정책 담당자")
        session.commit()
        second = import_company_fit_policy(session, POLICY_V3_FILE, actor="다른 담당자")
        session.commit()
        assert first.created is True and second.created is False
        assert first.policy_version_id == second.policy_version_id and first.sha256 == second.sha256
        row = session.get(CompanyFitPolicyVersion, first.policy_version_id)
        assert row.sha256 == canonical_json_hash(row.payload) == first.sha256
        assert session.scalar(select(func.count()).select_from(CompanyFitPolicyVersion)) == 1
        audits = session.scalars(select(AuditEvent).where(AuditEvent.action == "company_fit_policy.import")).all()
        assert {audit.safe_metadata["schema_version"] for audit in audits} == {SCHEMA_V3}
        # The v2 history file is still importable as its own row.
        history = import_company_fit_policy(session, POLICY_V2_FILE, actor="정책 담당자")
        session.commit()
        assert history.created is True and history.policy_version_id != first.policy_version_id
        assert session.get(CompanyFitPolicyVersion, history.policy_version_id).payload["schema_version"] == SCHEMA_V2
        # Importing never selects the policy for execution.
        assert get_settings().demo_company_fit_policy_version_id is None
        row.payload = {"changed": True}
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()
        with pytest.raises(ValueError, match="append-only"):
            session.delete(session.get(CompanyFitPolicyVersion, first.policy_version_id))
            session.flush()
    get_settings.cache_clear()


def test_settings_accept_empty_policy_ids_as_unset(monkeypatch) -> None:
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID="", BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=" ")
    settings = get_settings()
    assert settings.demo_company_fit_policy_version_id is None
    assert settings.demo_deep_review_policy_version_id is None
    value = uuid4()
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(value),
              BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=None)
    assert get_settings().demo_company_fit_policy_version_id == value
    get_settings.cache_clear()


# --- T2 enqueue gates --------------------------------------------------------------


def test_t2_enqueue_freezes_one_queued_company_attempt_with_provenance(world_session) -> None:
    session, world = world_session
    before = counts(session)
    result = enqueue(session, world)
    assert result.created is True and result.company_id == world.company_id and result.notice_id == world.notice_id
    row = session.get(PreSpecCompanyFitAttempt, result.attempt_id)
    assert counts(session) == (before[0] + 1, before[1] + 1)
    assert row.status == "queued" and row.company_id == world.company_id
    assert row.graph_version_id == world.graph_version_id and row.profile_version_id == world.profile_version_id
    assert row.company_fit_policy_version_id == world.policy_id and row.deep_policy_version_id is None
    assert row.overview_run_id == world.run_id and row.document_version_id == world.document_id
    assert row.policy_digest == world.policy_sha256 and row.model_name == "local-agent-main"
    assert row.model_revision is None and row.quality_status == "unmeasured_reference"
    inputs = row.input_jsonb
    assert row.input_sha256 == result.input_sha256 == fit.digest(inputs)
    assert inputs["schema_version"] == "bidops.company-analysis-input.v1"
    assert inputs["purpose"] == "company_fit" and inputs["execution_nonce"] == str(row.id)
    assert inputs["target_review_id"] is None and inputs["bundle_id"] is None
    assert inputs["company_id"] == str(world.company_id)
    assert inputs["graph_version_id"] == str(world.graph_version_id)
    assert inputs["policy_version_id"] == str(world.policy_id) and inputs["policy_sha256"] == world.policy_sha256
    assert inputs["document_version_ids"] == [str(world.document_id)]
    assert inputs["overview_run_id"] == str(world.run_id)
    assert inputs["model_name"] == "local-agent-main" and inputs["model_revision"] is None
    assert inputs["ontology_version"] == json.loads(ONTOLOGY_FILE.read_bytes())["version"]
    requirement_ids = [item["id"] for item in inputs["requirements"]]
    assert requirement_ids[0] == f"overview:{world.run_id}:business_overview:0"
    assert f"overview:{world.run_id}:main_tasks:1" in requirement_ids
    main = next(item for item in inputs["requirements"] if item["id"].endswith("main_tasks:0"))
    assert {"capability.data-platform", "capability.data-quality"} <= set(main["concept_ids"])
    assert any(path["relation"] == "direct" and path["requirement_id"] == main["id"] for path in inputs["graph_paths"])
    # Unknown/qualification facts are always present and remain unknown.
    qualification = next(fact for fact in inputs["profile_facts"] if fact["fact_key"] == "qualification-security-management")
    assert qualification["status"] == "unknown" and qualification["value"] is None
    assert set(inputs["coverage"]) == {
        "included_requirement_ids", "unmapped_requirement_ids", "excluded_fact_keys",
        "excluded_path_count_by_requirement",
    }
    assert sorted(requirement_ids) == inputs["coverage"]["included_requirement_ids"]
    provenance = row.provenance_jsonb
    assert provenance == {
        "input_sha256": row.input_sha256, "purpose": "company_fit", "company_id": str(world.company_id),
        "profile_version_id": str(world.profile_version_id), "profile_sha256": inputs["profile_sha256"],
        "graph_version_id": str(world.graph_version_id), "graph_sha256": inputs["graph_sha256"],
        "ontology_version": inputs["ontology_version"], "ontology_sha256": inputs["ontology_sha256"],
        "documents": [{"document_version_id": str(world.document_id), "source_sha256": world.content_sha256}],
        "overview_run_id": str(world.run_id), "overview_sha256": inputs["overview_sha256"], "bundle_id": None,
        "policy_version_id": str(world.policy_id), "policy_sha256": world.policy_sha256,
        "model_name": "local-agent-main", "model_revision": None,
        "generation_config_sha256": inputs["generation_config_sha256"],
    }
    # STEP-008 (contract §9, 2026-10-11): each overview row carries the existing
    # splitter's units of the overview document on its integer evidence pages.
    from app.deep_review.services.deep_reviews import DeepReviewService
    from app.deep_review.services.input_versions import bundle_context

    item = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == world.bundle_id)).one()
    pinned, structures = bundle_context(session, world.bundle_id)  # production loader (stored payload)
    splitter = [unit for group in DeepReviewService._requirements(
        pinned, structures, max_characters=SOURCE_CHARACTERS, max_requirements=1) for unit in group]
    assert [unit["page"] for unit in splitter] == sorted(TEXTS)
    by_id = {requirement["id"]: requirement for requirement in inputs["requirements"]}
    evidence_pages = {"business_overview:0": 1, "main_tasks:0": 2, "main_tasks:1": 3, "budget_and_period:0": 4}
    for suffix, page in evidence_pages.items():
        requirement = by_id[f"overview:{world.run_id}:{suffix}"]
        expected = [{**unit, "document_requirement_ids": []} for unit in splitter if unit["page"] == page]
        assert requirement["source_units"] == expected, suffix
        assert requirement["document_requirement_ids"] == []
        for unit in requirement["source_units"]:
            assert validate_source_unit(unit) == unit
            assert unit["text"] == TEXTS[page] and unit["locator"] == {"page": page}
            assert unit["document_version_id"] == str(world.document_id)
            assert unit["structure_id"] == str(item.structure_id_at_confirmation)
            assert unit["source_sha256"] == world.content_sha256
            assert unit["requirement_id"].startswith(f"req-0000-{page:04d}-")
    # Evidence page 4 has no unit: the row stays empty (visible in coverage), nothing is invented.
    assert by_id[f"overview:{world.run_id}:budget_and_period:0"]["source_units"] == []
    assert sum(len(requirement["source_units"]) for requirement in inputs["requirements"]) == 3
    assert inputs["bundle_id"] is None  # 0036 guard: the fit input never names a bundle
    audit = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(row.id))).one()
    assert audit.actor_kind == "human" and audit.claimed_name == "핏 담당자"
    body = json.dumps(audit.safe_metadata, ensure_ascii=False)
    assert audit.safe_metadata["company_id"] == str(world.company_id)
    assert audit.safe_metadata["input_sha256"] == row.input_sha256
    for forbidden in ("데이터 플랫폼", "주력 역량", "requirements", "graph_paths", "quote"):
        assert forbidden not in body


def test_t2_dry_run_checks_every_gate_and_writes_nothing(world_session) -> None:
    session, world = world_session
    before = counts(session)
    result = enqueue(session, world, dry_run=True)
    assert result.created is False and result.attempt_id is None and result.input_sha256 is None
    assert counts(session) == before
    assert gate_code(session, world, dry_run=True, company_id=uuid4()) == "company_not_found"
    assert counts(session) == before


def test_t2_active_attempt_blocks_a_second_enqueue_until_terminal(world_session) -> None:
    session, world = world_session
    first = enqueue(session, world)
    assert gate_code(session, world) == "active_attempt_exists"
    assert gate_code(session, world, dry_run=True) == "active_attempt_exists"
    row = session.get(PreSpecCompanyFitAttempt, first.attempt_id)
    row.status, row.lease_owner = "running", "worker"
    row.lease_expires_at = datetime.now(UTC)
    session.commit()
    assert gate_code(session, world) == "active_attempt_exists"
    # The rollback above expired the row; load it so the ORM sees running -> failed.
    session.refresh(row)
    row.status, row.lease_owner, row.lease_expires_at = "failed", None, None
    row.error_code, row.completed_at = "company_fit_execution_failed", datetime.now(UTC)
    session.commit()
    second = enqueue(session, world)
    assert second.attempt_id != first.attempt_id
    # Same company knowledge, same overview, new execution nonce -> new frozen hash.
    assert second.input_sha256 != first.input_sha256


def test_t2_unknown_or_unready_company_fails_before_any_write(world_session) -> None:
    session, world = world_session
    before = counts(session)
    assert gate_code(session, world, company_id=uuid4()) == "company_not_found"
    assert counts(session) == before
    registered = register_company(session, slug="demo-cloud-si", name="데모 클라우드SI", is_fictional=True, actor="등록 담당자")
    session.commit()
    before = counts(session)
    assert gate_code(session, world, company_id=registered.company_id) == "company_profile_not_ready"
    assert counts(session) == before


def test_t2_imported_but_unbound_company_is_not_ready(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, activate=False)
        assert gate_code(session, world) == "company_profile_not_ready"
    get_settings.cache_clear()


@pytest.mark.parametrize("overrides", [
    {"BIDOPS_DEMO_ENABLED": "false"},
    {"BIDOPS_PRESPEC_COMPANY_FIT_ENABLED": "false"},
    {"BIDOPS_REFERENCE_WORKFLOW_MODE": "false"},
])
def test_t2_disabled_flags_fail_closed(world_session, monkeypatch, overrides) -> None:
    session, world = world_session
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id), **overrides)
    assert gate_code(session, world) == "company_fit_disabled"


@pytest.mark.parametrize("policy_id", [None, "", "random"])
def test_t2_policy_must_be_explicitly_configured(world_session, monkeypatch, policy_id) -> None:
    session, world = world_session
    value = str(uuid4()) if policy_id == "random" else policy_id
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=value)
    assert gate_code(session, world) == "analysis_policy_unavailable"


def test_t2_tampered_policy_row_is_unavailable(world_session) -> None:
    session, world = world_session
    session.execute(
        text("UPDATE company_fit_policy_version SET payload = :payload WHERE id = :id"),
        {"payload": json.dumps({"schema_version": "tampered"}), "id": world.policy_id.hex},
    )
    session.commit()
    assert gate_code(session, world) == "analysis_policy_unavailable"


@pytest.mark.parametrize("overrides", [
    {"BIDOPS_VLLM_OVERVIEW_API_DIALECT": "vllm"},
    {"BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://192.0.2.10/v1"},
    {"BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://other.example/v1",
     "BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS": "approved.invalid"},
    {"BIDOPS_VLLM_OVERVIEW_BASE_URL": "http://127.0.0.1:9/not-v1"},
    {"BIDOPS_VLLM_OVERVIEW_MODEL_REVISION": "not-a-digest"},
])
def test_t2_model_binding_is_checked_before_any_write(world_session, monkeypatch, overrides) -> None:
    session, world = world_session
    before = counts(session)
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id), **overrides)
    assert gate_code(session, world) == "model_binding_invalid"
    assert counts(session) == before


def test_t2_mvp_relaxation_allows_empty_hosts_and_revision(world_session, monkeypatch) -> None:
    session, world = world_session
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id),
              BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS="", BIDOPS_VLLM_OVERVIEW_MODEL_REVISION="")
    assert enqueue(session, world, dry_run=True).created is False


def test_t2_sw_business_flag_is_the_only_grade_gate(world_session, monkeypatch) -> None:
    session, world = world_session
    from app.deep_review.services import effective_grade

    # The C-1 `우선 검토` grade is never consulted on the company path.
    monkeypatch.setattr(effective_grade, "priority_notice_ids", lambda *_args: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(effective_grade, "effective_grades", lambda *_args: (_ for _ in ()).throw(AssertionError))
    assert enqueue(session, world, dry_run=True).created is False
    notice = session.get(Notice, world.notice_id)
    notice.qualification_flags_json = {"sw_business_status": "N"}
    session.commit()
    assert gate_code(session, world) == "effective_grade_ineligible"
    notice.qualification_flags_json = {"sw_business_status": "unknown"}
    session.commit()
    assert gate_code(session, world) == "effective_grade_ineligible"
    assert gate_code(session, world, notice_id=987654) == "effective_grade_ineligible"


@pytest.mark.parametrize("change", ["running", "needs_human_review", "assessment", "stale_document", "unchecked"])
def test_t2_only_a_completed_current_v7_overview_is_an_input(world_session, change) -> None:
    session, world = world_session
    run = session.get(PrespecOverviewRun, world.run_id)
    if change == "running":
        run.status, run.result_json, run.checks_json, run.completed_at = "running", None, None, None
    elif change == "needs_human_review":
        run.status, run.result_json = "needs_human_review", None
    elif change == "assessment":
        run.contract_version = "overview-assessment-v1"
    elif change == "stale_document":
        session.get(DocumentVersion, world.document_id).is_current = False
    else:
        run.checks_json = {"overall": "failed"}
    session.commit()
    assert gate_code(session, world) == "overview_not_completed"


def test_t2_malformed_overview_or_actor_is_company_input_invalid(world_session) -> None:
    session, world = world_session
    assert gate_code(session, world, actor="  ") == "company_input_invalid"
    run = session.get(PrespecOverviewRun, world.run_id)
    result = deepcopy(OVERVIEW_RESULT)
    result["main_tasks"][0] = {"claim_id": "c2", "text": 7, "evidence": []}
    run.result_json = result
    session.commit()
    assert gate_code(session, world) == "company_input_invalid"


def test_t2_tampered_company_lineage_is_company_input_invalid(world_session) -> None:
    session, world = world_session
    session.execute(
        text("UPDATE profile_version SET profile_sha256 = :digest WHERE id = :id"),
        {"digest": "0" * 64, "id": world.profile_version_id.hex},
    )
    session.commit()
    assert gate_code(session, world) == "company_input_invalid"


# --- STEP-008: v3 policy, ready bundle and source units (contract §9, 2026-10-11) ----------


def test_t2_selected_v2_fit_policy_is_unavailable_for_enqueue(world_session, monkeypatch) -> None:
    session, world = world_session
    history = import_company_fit_policy(session, POLICY_V2_FILE, actor="정책 담당자")
    session.commit()
    before = counts(session)
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(history.policy_version_id))
    assert gate_code(session, world) == "analysis_policy_unavailable"
    assert gate_code(session, world, dry_run=True) == "analysis_policy_unavailable"
    assert counts(session) == before
    # The v2 row stays a valid stored policy (history); it is only not selectable for a new enqueue.
    row = session.get(CompanyFitPolicyVersion, history.policy_version_id)
    assert fit_policy.policy_row_payload(row)["schema_version"] == SCHEMA_V2
    configure(monkeypatch, BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID=str(world.policy_id))
    assert enqueue(session, world, dry_run=True).created is False


def _structure_key(session: Session, bundle_id: UUID) -> tuple[str, str]:
    item = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundle_id)).one()
    structure = session.get(DocumentStructure, item.structure_id_at_confirmation)
    location = session.scalars(select(ContentObjectLocation).where(
        ContentObjectLocation.content_object_id == structure.payload_content_object_id)).one()
    return location.namespace_key, location.object_key


def test_t2_ready_bundle_is_required_after_the_overview_gate(sqlite_engine, monkeypatch, object_store) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, bundle=False)
        before = counts(session)
        assert gate_code(session, world) == "bundle_not_ready"
        assert gate_code(session, world, dry_run=True) == "bundle_not_ready"
        assert counts(session) == before
        # Gate order (§9): an incomplete overview is reported before the bundle.
        run = session.get(PrespecOverviewRun, world.run_id)
        run.checks_json = {"overall": "failed"}
        session.commit()
        assert gate_code(session, world) == "overview_not_completed"
        run.checks_json = {"overall": "passed"}
        session.commit()
        # Only a ``ready`` bundle counts; a superseded one does not fall back to current documents.
        superseded = ready_bundle(session, world.notice_id, world.document_id)
        session.get(DocumentBundle, superseded).status = "superseded"
        session.commit()
        assert gate_code(session, world) == "bundle_not_ready"
        # The latest ready bundle's pinned structure snapshot must be readable and intact.
        latest = ready_bundle(session, world.notice_id, world.document_id, revision=2)
        session.commit()
        key = _structure_key(session, latest)
        data, metadata = object_store[key]
        object_store[key] = (data.replace("데이터".encode(), "자료".encode()), metadata)
        assert gate_code(session, world) == "bundle_not_ready"
        assert counts(session) == before
        object_store[key] = (data, metadata)
        assert enqueue(session, world).created is True
    get_settings.cache_clear()


def test_t2_inventory_ids_link_to_overview_rows(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, texts=REQUIREMENT_TEXTS, manifest=True)
        queued = enqueue(session, world)
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        by_id = {requirement["id"]: requirement for requirement in row.input_jsonb["requirements"]}
        expected = {"business_overview:0": ["SFR-1"], "main_tasks:0": ["SFR-2"], "main_tasks:1": ["SFR-3"],
                    "budget_and_period:0": []}
        for suffix, ids in expected.items():
            requirement = by_id[f"overview:{world.run_id}:{suffix}"]
            assert requirement["document_requirement_ids"] == ids, suffix
            assert [unit["document_requirement_ids"] for unit in requirement["source_units"]] == ([ids] if ids else [])
            # Raw ids stay in the unit text ("SFR-001"); the inventory ids are normalized ("SFR-1").
            assert all(unit["text"] == REQUIREMENT_TEXTS[unit["page"]] for unit in requirement["source_units"])
    get_settings.cache_clear()


def test_t2_inventory_mismatch_is_company_input_invalid_and_writes_nothing(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, texts=REQUIREMENT_TEXTS)
        # The stored inventory expects an id the source text does not contain:
        # the same strict rule as the deep path (no relaxation).
        item = session.scalars(select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == world.bundle_id)).one()
        session.add(DocumentSegmentManifest(
            structure_id=item.structure_id_at_confirmation, document_version_id=world.document_id,
            source_sha256=world.content_sha256, taxonomy_version=document_segments.TAXONOMY_VERSION,
            extractor_binding=dict(document_segments.EXTRACTOR_BINDING),
            extractor_binding_sha256=document_segments.EXTRACTOR_BINDING_SHA256,
            inventory_summary={"expected_ids": ["SFR-1", "SFR-2", "SFR-3", "SFR-4"], "duplicate_ids": [],
                               "ambiguous_items": [], "prefixes": ["SFR"], "item_count": 4},
            warnings=[], coverage={"gap_count": 0, "overlap_count": 0, "needs_human_review_count": 0},
            payload_sha256="1" * 64,
        ))
        session.commit()
        before = counts(session)
        assert gate_code(session, world) == "company_input_invalid"
        assert gate_code(session, world, dry_run=True) == "company_input_invalid"
        assert counts(session) == before
    get_settings.cache_clear()


def test_t2_bundle_units_are_the_deep_path_units(sqlite_engine, monkeypatch) -> None:
    """Fit and deep share one splitter helper; the deep wrapper keeps its own error type."""

    from app.deep_review.services import company_deep_review as cdr
    from app.deep_review.services.company_analysis_input import CompanyAnalysisError
    from app.deep_review.services.company_source_units import bundle_source_units
    from app.deep_review.services.deep_reviews import DeepReviewServiceError
    from app.deep_review.services.input_versions import bundle_context

    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, texts=REQUIREMENT_TEXTS, manifest=True)
        pinned, structures = bundle_context(session, world.bundle_id)
        shared = bundle_source_units(session, pinned, structures, source_characters=SOURCE_CHARACTERS)
        deep = cdr.company_source_units(session, pinned, structures, source_characters=SOURCE_CHARACTERS)
        assert shared == deep and [unit["document_requirement_ids"] for unit in shared] == [["SFR-1"], ["SFR-2"], ["SFR-3"]]
        tampered = {**structures}
        key = next(iter(tampered))
        tampered[key] = {**tampered[key], "blocks": tampered[key]["blocks"][:2]}
        with pytest.raises(CompanyAnalysisError) as error:
            bundle_source_units(session, pinned, tampered, source_characters=SOURCE_CHARACTERS)
        assert error.value.code == "company_input_invalid"
        with pytest.raises(DeepReviewServiceError) as error:
            cdr.company_source_units(session, pinned, tampered, source_characters=SOURCE_CHARACTERS)
        assert error.value.code == "company_input_invalid" and error.value.status_code == 409
    get_settings.cache_clear()


# --- CLI (fresh process) ------------------------------------------------------------


def _environment(tmp_path: Path, **extra: str) -> dict[str, str]:
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith("BIDOPS_"):
            environment.pop(key)
    environment.update({
        "BIDOPS_ROOT": str(PROJECT_ROOT),
        "BIDOPS_DATA_DIR": str(tmp_path / "data"),
        "BIDOPS_ATTACHMENTS_DIR": str(tmp_path / "attachments"),
        "BIDOPS_DATABASE_URL": f"sqlite:///{tmp_path / 'company-fit.db'}",
        "BIDOPS_OBJECT_STORE_BACKEND": "filesystem",
        "BIDOPS_TEST_MODE": "1",
        "BIDOPS_OPENAI_ENABLED": "false",
        "BIDOPS_PRESPEC_OVERVIEW_ENABLED": "false",
        "PYTHONPATH": str(BACKEND_ROOT),
    })
    environment.update(extra)
    return environment


def _run(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.deep_review.cli", *arguments],
        cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=180,
    )


def test_import_policy_cli_is_json_only_and_idempotent(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    first = _run(environment, "import-company-fit-policy", "--policy", str(POLICY_V3_FILE), "--actor", "정책 담당자")
    assert first.returncode == 0, first.stderr
    body = json.loads(first.stdout)
    assert set(body) == POLICY_KEYS and body["created"] is True and body["errors"] == []
    assert body["sha256"] == canonical_json_hash(json.loads(POLICY_V3_FILE.read_bytes()))
    second = _run(environment, "import-company-fit-policy", "--policy", str(POLICY_V3_FILE), "--actor", "정책 담당자")
    assert second.returncode == 0
    replay = json.loads(second.stdout)
    assert replay["created"] is False and replay["policy_version_id"] == body["policy_version_id"]
    # The v2 history file stays importable as a separate row.
    history = _run(environment, "import-company-fit-policy", "--policy", str(POLICY_V2_FILE), "--actor", "정책 담당자")
    assert history.returncode == 0, history.stderr
    assert json.loads(history.stdout)["created"] is True
    assert json.loads(history.stdout)["policy_version_id"] != body["policy_version_id"]
    # A canonical but tampered v3 file (other split size) is not an approved file.
    tampered_payload = json.loads(POLICY_V3_FILE.read_bytes())
    tampered_payload["chunking"]["source_characters"] = 5000
    tampered = tmp_path / "company-fit-demo-v3.json"
    tampered.write_bytes(_canonical(tampered_payload))
    rejected = _run(environment, "import-company-fit-policy", "--policy", str(tampered), "--actor", "정책 담당자")
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["errors"] == ["policy_unapproved"]
    assert rejected.stderr.strip() == "policy_unapproved"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    failed = _run(environment, "import-company-fit-policy", "--policy", str(broken), "--actor", "정책 담당자")
    assert failed.returncode == 2
    failure = json.loads(failed.stdout)
    assert set(failure) == POLICY_KEYS and failure["errors"] == ["policy_invalid"]
    assert failure["policy_version_id"] is None and failure["created"] is False
    assert failed.stderr.strip() == "policy_invalid"
    assert str(broken) not in failed.stdout + failed.stderr


def test_enqueue_cli_reports_safe_gate_codes(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    disabled = _run(environment, "enqueue-company-fit", "--company-id", str(uuid4()),
                    "--notice-id", "1", "--actor", "핏 담당자", "--dry-run")
    assert disabled.returncode == 2
    body = json.loads(disabled.stdout)
    assert set(body) == ENQUEUE_KEYS
    assert body["errors"] == ["company_fit_disabled"] and body["created"] is False
    assert body["attempt_id"] is None and body["input_sha256"] is None
    assert disabled.stderr.strip() == "company_fit_disabled"
    enabled = _environment(
        tmp_path, BIDOPS_DEMO_ENABLED="true", BIDOPS_PRESPEC_COMPANY_FIT_ENABLED="true",
        BIDOPS_REFERENCE_WORKFLOW_MODE="true",
    )
    missing = _run(enabled, "enqueue-company-fit", "--company-id", "not-a-uuid",
                   "--notice-id", "1", "--actor", "핏 담당자")
    assert missing.returncode == 2
    body = json.loads(missing.stdout)
    assert body["errors"] == ["company_not_found"] and body["company_id"] is None and body["notice_id"] == 1
    syntax = _run(enabled, "enqueue-company-fit", "--company-id", str(uuid4()), "--notice-id", "x", "--actor", "a")
    assert syntax.returncode == 2 and syntax.stdout == ""


def test_enqueue_cli_main_success_dry_run_and_duplicate(world_session, monkeypatch, capsys) -> None:
    """The CLI module wraps the same service with its own transaction."""

    session, world = world_session
    from app.deep_review.cli import enqueue_company_fit as cli
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=session.get_bind(), class_=Session))
    argv = ["--company-id", str(world.company_id), "--notice-id", str(world.notice_id), "--actor", "핏 담당자"]
    assert cli.main([*argv, "--dry-run"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry == {"company_id": str(world.company_id), "notice_id": world.notice_id, "attempt_id": None,
                   "input_sha256": None, "created": False, "errors": []}
    assert counts(session)[0] == 0
    assert cli.main(argv) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["created"] is True and UUID(created["attempt_id"])
    assert len(created["input_sha256"]) == 64 and created["errors"] == []
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    duplicate = json.loads(captured.out)
    assert duplicate["errors"] == ["active_attempt_exists"] and duplicate["attempt_id"] is None
    assert captured.err.strip() == "active_attempt_exists"
    session.expire_all()
    assert counts(session)[0] == 1
    # The CLI path freezes source units read through the production structure loader.
    frozen = session.get(PreSpecCompanyFitAttempt, UUID(created["attempt_id"])).input_jsonb
    assert [len(row["source_units"]) for row in frozen["requirements"]] == [1, 1, 1, 0]


def test_enqueue_cli_reports_bundle_not_ready(sqlite_engine, monkeypatch, capsys) -> None:
    from app.deep_review.cli import enqueue_company_fit as cli
    from sqlalchemy.orm import sessionmaker

    with Session(sqlite_engine) as session:
        world = build_world(session, monkeypatch, bundle=False)
        monkeypatch.setattr(cli, "init_db", lambda: None)
        monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=session.get_bind(), class_=Session))
        argv = ["--company-id", str(world.company_id), "--notice-id", str(world.notice_id), "--actor", "핏 담당자"]
        assert cli.main(argv) == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out)["errors"] == ["bundle_not_ready"] and captured.err.strip() == "bundle_not_ready"
        assert counts(session)[0] == 0
    get_settings.cache_clear()
