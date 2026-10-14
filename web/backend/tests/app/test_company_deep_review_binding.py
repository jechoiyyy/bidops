"""DEMO-03 STEP-003 company Luna preview → approval → review/attempt (spec T2·T3·T6).

The world is the STEP-002 company world (real DEMO-02 registration of the frozen
fixtures, completed v7 overview, SW사업대상=Y notice) plus a ready document
bundle and the approved ``analysis-policy-luna-hp-v1`` row selected by
``BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID``.  No model, transport or network
is called anywhere in this module (an autouse guard fails the test otherwise);
the company job is queued for the shared slot but never claimed here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.model_client import ModelClient
from app.core.models import AuditEvent, IdempotencyRecord
from app.deep_review.models import (
    AnalysisPolicyVersion,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    WorkJob,
)
from app.deep_review.schemas.company_analysis import CompanyReviewView, FrozenProvenance
from app.deep_review.services import company_deep_review as cdr
from app.deep_review.services import company_fit as fit
from app.deep_review.services import luna_inputs
from app.deep_review.services.company_analysis_input import COMPANY_ANALYSIS_INPUT_KEYS
from app.deep_review.services.company_knowledge import activate_company_knowledge, company_knowledge_public_graph
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError
from app.deep_review.services.input_versions import (
    CANONICAL_POLICY_FILE,
    HP_LUNA_POLICY_FILE,
    InputVersionError,
    canonical_json_hash,
    import_policy_version,
)
from app.lifecycle.models import Notice
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_fit_enqueue import (  # noqa: F401 - shared fixtures
    FIXTURES,
    TEXTS,
    World,
    build_world,
    configure,
    import_company,
    object_store,
    ready_bundle,
    structure_payload,
)
from tests.postgres import migrated_engine, requires_postgres


def _sqlite_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.core.db import init_db

    bind = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(bind)
    # ``postgresql_where`` is not emitted by SQLite and would become a global
    # unique index; mirror the production partial semantics (same as
    # tests/app/test_deep_reviews.py) so a retry attempt can be created.
    with bind.begin() as connection:
        for index_name in ("uq_deep_review_attempt_active", "uq_work_job_active"):
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        connection.execute(text("CREATE UNIQUE INDEX uq_deep_review_attempt_active ON deep_review_attempt "
                                "(deep_review_id) WHERE status IN ('queued','running')"))
        connection.execute(text("CREATE UNIQUE INDEX uq_work_job_active ON work_job "
                                "(job_type, aggregate_type, aggregate_id) WHERE status IN ('queued','running')"))
    return bind


@pytest.fixture
def sqlite_engine():
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


LUNA_V4 = CANONICAL_POLICY_FILE.with_name("analysis-policy-luna-v4.json")
LUNA_HP = HP_LUNA_POLICY_FILE


def structure_loader(_session, structure):
    """The deep service's injected loader: the same payload the fixture bundle stored.

    ``ready_bundle`` (shared with the fit tests) stores exactly this payload, so
    the company fit (production loader) and the deep service read one source.
    """

    return structure_payload(structure, TEXTS)


@dataclass(frozen=True)
class DeepWorld:
    fit: World
    company_id: UUID
    notice_id: int
    bundle_id: UUID
    policy_id: UUID
    graph_version_id: UUID
    profile_version_id: UUID


def deep_configure(monkeypatch, world: DeepWorld | World, *, deep_policy_id=None, **overrides) -> None:
    base = world.fit if isinstance(world, DeepWorld) else world
    values = {
        "BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID": str(base.policy_id),
        "BIDOPS_LUNA_DEEP_REVIEW_ENABLED": "true",
        "BIDOPS_ANALYSIS_PROVIDER": "vllm",
        "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED": "false",
    }
    policy = deep_policy_id if deep_policy_id is not None else getattr(world, "policy_id", None)
    if isinstance(world, DeepWorld) or deep_policy_id is not None:
        values["BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID"] = str(policy)
    values.update(overrides)
    configure(monkeypatch, **values)


def deep_world(session: Session, monkeypatch, *, slug: str = "demo-data-ai") -> DeepWorld:
    # One ready bundle (``ready_bundle`` stores its structure payload for real), shared by
    # the deep preview (injected ``structure_loader``, same payload) and any company fit.
    base = build_world(session, monkeypatch, slug=slug, bundle=False)
    bundle_id = ready_bundle(session, base.notice_id, base.document_id)
    policy = import_policy_version(session, LUNA_HP, created_by_name="정책 담당자", label="analysis-policy-luna-hp-v1")
    session.commit()
    world = DeepWorld(fit=base, company_id=base.company_id, notice_id=base.notice_id, bundle_id=bundle_id,
                      policy_id=policy.id, graph_version_id=base.graph_version_id,
                      profile_version_id=base.profile_version_id)
    deep_configure(monkeypatch, world)
    return world


def service() -> DeepReviewService:
    return DeepReviewService(structure_loader=structure_loader, raw_response_store=_FixtureStore())


def preview(session, svc, world, *, company_id=None, notice_id=None, bundle_id=None, review_id=None) -> dict:
    return cdr.preview_company_deep_review(
        svc, session, company_id=company_id or world.company_id,
        notice_id=world.notice_id if notice_id is None else notice_id,
        bundle_id=bundle_id or world.bundle_id, review_id=review_id,
    )


def create(session, svc, world, preview_id, *, request_id=None, company_id=None, bundle_id=None, actor="심층 담당자"):
    return cdr.create_company_review(
        svc, session, company_id=company_id or world.company_id, notice_id=world.notice_id,
        bundle_id=bundle_id or world.bundle_id, preview_id=UUID(str(preview_id)), actor=actor,
        request_id=request_id or uuid4(),
    )


def retry(session, svc, world, review_id, preview_id, *, request_id=None, company_id=None):
    return cdr.create_company_attempt(
        svc, session, company_id=company_id or world.company_id, review_id=UUID(str(review_id)),
        preview_id=UUID(str(preview_id)), actor="심층 담당자", request_id=request_id or uuid4(),
    )


def code(call) -> str:
    with pytest.raises((DeepReviewServiceError, InputVersionError)) as error:
        call()
    return error.value.code


def count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def fail_current_attempt(session: Session, review_id) -> None:
    """Simulate a terminal worker failure (the worker itself is STEP-006)."""

    review = session.get(DeepReview, UUID(str(review_id)))
    attempt = session.get(DeepReviewAttempt, review.current_attempt_id)
    job = session.get(WorkJob, attempt.work_job_id)
    attempt.status = review.status = job.status = "failed"
    attempt.completed_at = job.completed_at = datetime.now(UTC)
    session.commit()


def second_source(slug: str = "demo-data-ai") -> bytes:
    payload = json.loads((FIXTURES / "companies" / f"{slug}.v1.json").read_bytes())
    payload["scenario_version"] = f"{payload['scenario_version']}-rebound"
    return json.dumps(payload, ensure_ascii=False, indent=2).encode()


def new_overview(session: Session, world: DeepWorld) -> None:
    current = session.get(PrespecOverviewRun, world.fit.run_id)
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run", aggregate_id=uuid4(),
                  status="completed")
    session.add(job)
    session.flush()
    result = deepcopy(current.result_json)
    result["business_overview"][0]["text"] = "공공기관 업무 데이터를 통합하고 분석하는 사업이다."
    session.add(PrespecOverviewRun(
        id=uuid4(), notice_id=world.notice_id, document_version_id=world.fit.document_id, work_job_id=job.id,
        status="completed", range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="local-agent-main", warnings_json=[], reason_codes=[], call_count=1, raw_response_refs=[],
        result_json=result, checks_json={"overall": "passed"}, contract_version="overview-v1",
        completed_at=datetime.now(UTC), created_at=current.created_at.replace(year=current.created_at.year + 1),
    ))
    session.commit()


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """Every model/transport entry point fails loudly; teardown asserts zero calls."""

    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("model")
        raise AssertionError("model transport called")

    from app.deep_review.services import luna_client

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(forbidden))
    monkeypatch.setattr(luna_client.LunaClient, "__init__", forbidden)
    yield calls
    assert calls == []
    get_settings.cache_clear()


@pytest.fixture
def world_session(sqlite_engine, monkeypatch):
    with Session(sqlite_engine) as session:
        yield session, deep_world(session, monkeypatch), service()


# --- T2: preview freezes CompanyAnalysisInput + FrozenProvenance --------------------


def test_t2_preview_freezes_company_input_and_provenance(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        response = preview(session, svc, world)

        pid = UUID(response["preview_id"])
        frozen = response["input"]
        assert set(response) == {
            "preview_id", "input_sha256", "provider", "model", "reasoning_effort", "quality_status",
            "source_verification_enabled", "input", "company_id", "profile_version_id", "graph_version_id",
            "graph_sha256", "ontology_version",
        }
        assert (response["provider"], response["model"], response["reasoning_effort"]) == ("codex-exec", "gpt-6-luna", "high")
        assert response["quality_status"] == "unmeasured_reference" and response["source_verification_enabled"] is True
        assert set(frozen) == COMPANY_ANALYSIS_INPUT_KEYS
        assert frozen["purpose"] == "deep_review" and frozen["execution_nonce"] == str(pid)
        assert frozen["target_review_id"] is None and frozen["bundle_id"] == str(world.bundle_id)
        assert frozen["company_id"] == str(world.company_id) == response["company_id"]
        assert frozen["graph_version_id"] == str(world.graph_version_id) == response["graph_version_id"]
        assert frozen["profile_version_id"] == str(world.profile_version_id) == response["profile_version_id"]
        assert frozen["policy_version_id"] == str(world.policy_id) and frozen["model_revision"] is None
        assert frozen["document_version_ids"] == [str(world.fit.document_id)]
        assert frozen["overview_run_id"] == str(world.fit.run_id)
        # Requirements are the existing splitter units (requirement_id format kept).
        assert [row["id"][:4] for row in frozen["requirements"]] == ["req-"] * len(TEXTS)
        assert all(row["id"] == row["source_units"][0]["requirement_id"] for row in frozen["requirements"])
        assert "capability.data-platform" in frozen["requirements"][0]["concept_ids"]
        assert frozen["coverage"]["included_requirement_ids"] == [row["id"] for row in frozen["requirements"]]
        # The full graph version is used, not the truncated REST view.
        nodes, edges = company_knowledge_public_graph(session, company_id=world.company_id,
                                                      graph_version_id=world.graph_version_id)
        assert len(frozen["graph_paths"]) > 0 and len(nodes) >= len(frozen["graph_nodes"])
        assert response["input_sha256"] == canonical_json_hash(frozen)

        session.expire_all()
        row = session.get(DeepReviewPreview, pid)
        assert row.company_id == world.company_id and row.graph_version_id == world.graph_version_id
        assert row.input_snapshot == frozen and row.input_sha256 == response["input_sha256"]
        provenance = FrozenProvenance.model_validate(row.provenance_jsonb)
        assert provenance.input_sha256 == row.input_sha256 and provenance.purpose == "deep_review"
        assert provenance.bundle_id == world.bundle_id and provenance.company_id == world.company_id
        content_sha = session.get(DocumentVersion, world.fit.document_id)
        assert [str(doc.document_version_id) for doc in provenance.documents] == [str(world.fit.document_id)]
        assert provenance.documents[0].source_sha256 == world.fit.content_sha256 and content_sha is not None
        # A preview queues nothing and creates no review.
        assert count(session, WorkJob) == 1  # the seeded completed overview job only
        assert count(session, DeepReview) == 0 and count(session, DeepReviewApproval) == 0
        # Each preview is a new nonce and therefore a new input hash.
        again = preview(session, svc, world)
        assert again["preview_id"] != response["preview_id"] and again["input_sha256"] != response["input_sha256"]


def test_t2_gate_order_matrix_writes_nothing(world_session, monkeypatch) -> None:
    session, world, svc = world_session
    other = import_company(session, "demo-public-si", activate=False)
    session.commit()
    legacy_policy = import_policy_version(session, created_by_name="정책 담당자")
    session.commit()
    notice = session.get(Notice, world.notice_id)
    run = session.get(PrespecOverviewRun, world.fit.run_id)
    bundle = session.get(DocumentBundle, world.bundle_id)

    def gate(company_id=other.company_id) -> str:
        return code(lambda: preview(session, svc, world, company_id=company_id))

    # Break everything, then repair one condition at a time: the codes appear in §9 order.
    deep_configure(monkeypatch, world, BIDOPS_DEMO_ENABLED="false", BIDOPS_REFERENCE_WORKFLOW_MODE="false",
                   BIDOPS_LUNA_DEEP_REVIEW_ENABLED="false", BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID="")
    notice.qualification_flags_json = {"sw_business_status": "N"}
    run.status, run.checks_json = "needs_human_review", None
    bundle.status = "needs_review"
    session.commit()
    observed = [gate()]
    deep_configure(monkeypatch, world, BIDOPS_REFERENCE_WORKFLOW_MODE="false",
                   BIDOPS_LUNA_DEEP_REVIEW_ENABLED="false", BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID="")
    observed.append(gate(company_id=uuid4()))
    observed.append(gate())
    deep_configure(monkeypatch, world, BIDOPS_LUNA_DEEP_REVIEW_ENABLED="false",
                   BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID="")
    observed.append(gate())
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID="")
    observed.append(gate())
    activate_company_knowledge(session, company_id=other.company_id, graph_version_id=other.graph_version_id,
                               actor="활성 담당자")
    session.commit()
    observed.append(gate())
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(uuid4()))
    observed.append(gate())
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(legacy_policy.id))
    observed.append(gate())
    deep_configure(monkeypatch, world, BIDOPS_ANALYSIS_PROVIDER="mock")
    observed.append(gate())
    deep_configure(monkeypatch, world)
    observed.append(gate())
    run.status, run.checks_json = "completed", {"overall": "passed"}
    session.commit()
    observed.append(gate())
    notice.qualification_flags_json = {"sw_business_status": "Y"}
    session.commit()
    observed.append(gate())
    assert observed == [
        "not_found", "not_found", "reference_mode_required", "luna_disabled", "company_profile_not_ready",
        "analysis_policy_unavailable", "analysis_policy_unavailable", "model_binding_invalid",
        "model_binding_invalid", "overview_not_completed", "effective_grade_ineligible", "bundle_not_ready",
    ]
    assert count(session, DeepReviewPreview) == 0 and count(session, DeepReview) == 0
    assert count(session, WorkJob) == 1
    bundle.status = "ready"
    session.commit()
    assert preview(session, svc, world, company_id=other.company_id)["company_id"] == str(other.company_id)
    assert set(cdr.ERROR_STATUS) >= set(observed)


def test_t2_fallback_unit_and_tampered_policy_fail_closed(world_session, monkeypatch) -> None:
    session, world, svc = world_session
    empty = DeepReviewService(structure_loader=lambda s, st: {**structure_loader(s, st), "blocks": []},
                              raw_response_store=_FixtureStore())
    assert code(lambda: preview(session, empty, world)) == "company_input_invalid"
    policy = session.get(AnalysisPolicyVersion, world.policy_id)
    session.execute(text("UPDATE analysis_policy_version SET policy_sha256 = :digest WHERE id = :id"),
                    {"digest": "0" * 64, "id": policy.id.hex})
    session.commit()
    session.expire_all()
    assert code(lambda: preview(session, svc, world)) == "analysis_policy_unavailable"
    assert count(session, DeepReviewPreview) == 0


def test_t2_foreign_and_unknown_ids_are_not_found(world_session, monkeypatch) -> None:
    session, world, svc = world_session
    other = import_company(session, "demo-public-si")
    session.commit()
    first = preview(session, svc, world)
    created = create(session, svc, world, first["preview_id"])
    review_id = created["id"]
    # Another company's preview / review / unknown notice / bundle of another notice.
    assert code(lambda: create(session, svc, world, preview(session, svc, world)["preview_id"],
                               company_id=other.company_id)) == "not_found"
    assert code(lambda: preview(session, svc, world, company_id=other.company_id, review_id=UUID(review_id))) == "not_found"
    fail_current_attempt(session, review_id)
    target = preview(session, svc, world, review_id=UUID(review_id))
    assert code(lambda: retry(session, svc, world, review_id, target["preview_id"], company_id=other.company_id)) == "not_found"
    assert code(lambda: preview(session, svc, world, notice_id=987654)) == "not_found"
    other_bundle = DocumentBundle(id=uuid4(), notice_id=_other_notice(session, world), revision=1, version=1,
                                  status="ready", issues_snapshot=[], created_by_name="준비 담당자")
    session.add(other_bundle)
    session.commit()
    assert code(lambda: preview(session, svc, world, bundle_id=other_bundle.id)) == "not_found"
    assert code(lambda: preview(session, svc, world, bundle_id=uuid4())) == "not_found"
    assert code(lambda: create(session, svc, world, uuid4())) == "preview_required"


def _other_notice(session: Session, world: DeepWorld) -> int:
    notice = Notice(notice_key=f"demo-other:{uuid4()}", source_type="pre_spec", title="다른 사전규격",
                    qualification_flags_json={"sw_business_status": "Y"})
    session.add(notice)
    session.flush()
    return notice.id


def test_t2_replay_preview_used_and_idempotency(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        frozen = preview(session, svc, world)
        request_id = uuid4()
        created = create(session, svc, world, frozen["preview_id"], request_id=request_id)
        replay = create(session, svc, world, frozen["preview_id"], request_id=request_id)
        assert replay == created
        assert count(session, DeepReview) == 1 and count(session, DeepReviewAttempt) == 1
        assert count(session, DeepReviewApproval) == 1
        assert session.scalar(select(func.count()).select_from(WorkJob).where(WorkJob.job_type == "deep_review")) == 1
        assert code(lambda: create(session, svc, world, frozen["preview_id"])) == "preview_used"
        assert code(lambda: create(session, svc, world, preview(session, svc, world)["preview_id"],
                                   request_id=request_id)) == "idempotency_conflict"
        view = CompanyReviewView.model_validate(created)
        assert view.company_id == world.company_id and view.graph_version_id == world.graph_version_id
        assert view.is_current is True and view.current_attempt is not None
        assert view.current_attempt.preview_id == UUID(frozen["preview_id"])
        assert view.input_sha256 == frozen["input_sha256"] == view.provenance.input_sha256
        assert view.quality_status == "unmeasured_reference"
        review = session.get(DeepReview, UUID(created["id"]))
        assert review.company_id == world.company_id and review.graph_version_id == world.graph_version_id
        assert review.effective_grade_at_start == "unknown" and review.current_attempt_id is not None
        approval = session.scalar(select(DeepReviewApproval))
        assert approval.company_id == world.company_id and approval.attempt_id == review.current_attempt_id
        approval_audit = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "deep_review.external_transfer_approved",
            AuditEvent.aggregate_id == str(review.current_attempt_id),
        ))
        assert approval_audit.safe_metadata["model"] == "gpt-6-luna"
        assert approval_audit.safe_metadata["reasoning_effort"] == "high"
        job = session.get(WorkJob, session.get(DeepReviewAttempt, review.current_attempt_id).work_job_id)
        assert (job.job_type, job.aggregate_type, job.aggregate_id, job.status, job.max_attempts) == (
            "deep_review", "deep_review", review.id, "queued", 1)
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.create",
                                                        AuditEvent.aggregate_id == str(review.id)))
        body = json.dumps(audit.safe_metadata, ensure_ascii=False)
        assert audit.safe_metadata["company_id"] == str(world.company_id)
        assert "데이터 플랫폼" not in body and "requirements" not in body
        # With DEMO off the shared slot leaves the company job queued; with DEMO
        # on it is claimed by the same slot (STEP-006, tests/app/test_company_e2e.py).
        deep_configure(monkeypatch, world, BIDOPS_DEMO_ENABLED="false")
        assert service().claim_next_job(session, "legacy-worker") is None
        assert session.get(WorkJob, job.id).status == "queued"


def _measured(fill: str) -> dict:
    """Quality metadata that makes a second, distinct row of the same demo policy bytes."""

    return {"sample_hash": fill * 64, "required_item_recall": 0.8, "human_agreement": 0.7,
            "unsupported_false_positive_rate": 0.1}


def _tamper(session: Session, statement: str, **params) -> None:
    session.execute(text(statement), params)
    session.commit()
    session.expire_all()


@pytest.mark.parametrize("change", ["graph", "policy", "overview", "tampered_input"])
def test_t2_changed_inputs_between_preview_and_approval_are_preview_changed(world_session, monkeypatch, change) -> None:
    session, world, svc = world_session
    frozen = preview(session, svc, world)
    if change == "graph":
        import_company(session, raw=second_source())
        session.commit()
    elif change == "policy":
        policy = import_policy_version(session, LUNA_HP, created_by_name="정책 담당자",
                                       validation_metadata=_measured("c"))
        session.commit()
        assert policy.id != world.policy_id
        deep_configure(monkeypatch, world, deep_policy_id=policy.id,
                       BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(policy.id))
    elif change == "overview":
        new_overview(session, world)
    else:
        snapshot = deepcopy(frozen["input"])
        snapshot["requirements"][0]["text"] = "변조된 요구사항"
        _tamper(session, "UPDATE deep_review_preview SET input_snapshot = :value WHERE id = :id",
                value=json.dumps(snapshot, ensure_ascii=False), id=UUID(frozen["preview_id"]).hex)
    assert code(lambda: create(session, svc, world, frozen["preview_id"])) == "preview_changed"
    assert count(session, DeepReview) == 0 and count(session, DeepReviewApproval) == 0
    assert session.scalar(select(func.count()).select_from(WorkJob).where(WorkJob.job_type == "deep_review")) == 0


def test_t2_superseded_bundle_is_not_ready_and_preview_stays_unused(world_session) -> None:
    session, world, svc = world_session
    frozen = preview(session, svc, world)
    session.get(DocumentBundle, world.bundle_id).status = "superseded"
    session.commit()
    assert code(lambda: create(session, svc, world, frozen["preview_id"])) == "bundle_not_ready"
    assert count(session, DeepReviewApproval) == 0 and count(session, DeepReview) == 0


def test_t2_review_exists_leaves_the_preview_unconsumed(world_session) -> None:
    session, world, svc = world_session
    created = create(session, svc, world, preview(session, svc, world)["preview_id"])
    second = preview(session, svc, world)
    # While the first review is queued a second request is an active attempt.
    assert code(lambda: create(session, svc, world, second["preview_id"])) == "active_attempt_exists"
    fail_current_attempt(session, created["id"])
    assert code(lambda: create(session, svc, world, second["preview_id"])) == "review_exists"
    assert session.scalar(select(DeepReviewApproval.id).where(
        DeepReviewApproval.preview_id == UUID(second["preview_id"]))) is None
    assert count(session, DeepReview) == 1


def test_t2_rest_contract_statuses_and_replay(sqlite_engine, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.db import get_db
    from app.deep_review.routers import company_analysis as router

    with Session(sqlite_engine) as setup:
        world = deep_world(setup, monkeypatch)
    monkeypatch.setattr(router, "service", service())
    app = FastAPI()
    app.include_router(router.router)

    def db():
        with Session(sqlite_engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    base = f"/api/companies/{world.company_id}"
    body = {"bundle_id": str(world.bundle_id), "source_verification_enabled": True}
    response = http.post(f"{base}/pre-specs/{world.notice_id}/deep-review-previews", json=body)
    assert response.status_code == 200, response.text
    frozen = response.json()
    assert frozen["input"]["execution_nonce"] == frozen["preview_id"]
    request = {**body, "preview_id": frozen["preview_id"], "request_id": str(uuid4())}
    headers = {"X-BidOps-Actor-Name": "deep-reviewer"}
    created = http.post(f"{base}/pre-specs/{world.notice_id}/deep-reviews", json=request, headers=headers)
    assert created.status_code == 202, created.text
    assert http.post(f"{base}/pre-specs/{world.notice_id}/deep-reviews", json=request, headers=headers).json() == created.json()
    used = http.post(f"{base}/pre-specs/{world.notice_id}/deep-reviews",
                     json={**request, "request_id": str(uuid4())}, headers=headers)
    assert used.status_code == 409 and used.json()["error"]["code"] == "preview_used"
    assert "input" not in created.json() and created.json()["provenance"]["input_sha256"] == frozen["input_sha256"]
    assert http.post(f"{base}/pre-specs/{world.notice_id}/deep-reviews", json={**request, "request_id": str(uuid4())}
                     ).json()["error"]["code"] == "actor_name_required"
    assert http.post(f"{base}/pre-specs/{world.notice_id}/deep-review-previews",
                     json={**body, "source_verification_enabled": False}).status_code == 422
    assert http.post(f"{base}/pre-specs/{world.notice_id}/deep-review-previews",
                     json={**body, "extra": 1}).status_code == 422
    with Session(sqlite_engine) as session:
        fail_current_attempt(session, created.json()["id"])
    retry_preview = http.post(f"{base}/pre-specs/{world.notice_id}/deep-review-previews",
                              json={**body, "review_id": created.json()["id"]}).json()
    attempt = http.post(f"{base}/deep-reviews/{created.json()['id']}/attempts", headers=headers,
                        json={"preview_id": retry_preview["preview_id"], "source_verification_enabled": True,
                              "request_id": str(uuid4())})
    assert attempt.status_code == 202, attempt.text
    assert attempt.json()["sequence"] == 2 and attempt.json()["preview_id"] == retry_preview["preview_id"]
    statuses = {}
    for name, overrides in {
        "reference_mode_required": {"BIDOPS_REFERENCE_WORKFLOW_MODE": "false"},
        "luna_disabled": {"BIDOPS_LUNA_DEEP_REVIEW_ENABLED": "false"},
        "analysis_policy_unavailable": {"BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID": ""},
        "not_found": {"BIDOPS_DEMO_ENABLED": "false"},
    }.items():
        deep_configure(monkeypatch, world, **overrides)
        reply = http.post(f"{base}/pre-specs/{world.notice_id}/deep-review-previews", json=body)
        statuses[name] = (reply.status_code, reply.json()["error"]["code"])
    assert statuses == {
        "reference_mode_required": (503, "reference_mode_required"), "luna_disabled": (503, "luna_disabled"),
        "analysis_policy_unavailable": (503, "analysis_policy_unavailable"), "not_found": (404, "not_found"),
    }


def test_t2_assembled_app_hides_company_deep_review_routes_when_demo_disabled(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app import deep_review, main as main_module

    assert ("deep_review", "company_analysis_router") in main_module._ROUTER_REGISTRATION
    assert {route.path for route in deep_review.company_analysis_router.routes} == {
        "/api/companies/{company_id}/pre-specs/{notice_id}/deep-review-previews",
        "/api/companies/{company_id}/pre-specs/{notice_id}/deep-reviews",
        "/api/companies/{company_id}/deep-reviews/{review_id}/attempts",
    }
    configure(monkeypatch, BIDOPS_DEMO_ENABLED="false")
    http = TestClient(create_app(mount_frontend=False))
    reply = http.post(f"/api/companies/{uuid4()}/pre-specs/1/deep-review-previews", json={"bundle_id": str(uuid4())})
    assert reply.status_code == 404 and reply.json() == {"detail": "Not Found"}


# --- T3: fit results and the C-1 grade never gate a manual company deep review --------


@pytest.mark.parametrize("decision", ["matched", "mismatch", "unknown", None])
def test_t3_fit_result_or_absence_never_blocks_and_stays_untouched(world_session, monkeypatch, decision) -> None:
    session, world, svc = world_session
    if decision is not None:
        queued = fit.enqueue_company_fit(session, company_id=world.company_id, notice_id=world.notice_id,
                                         actor="핏 담당자")
        session.commit()
        row = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        result = {"schema_version": "bidops.prespec-company-fit-result.v2", "decision": decision}
        row.status, row.result_jsonb, row.result_sha256 = "completed", result, fit.digest(result)
        row.completed_at = datetime.now(UTC)
        session.commit()
    before = [(r.id, r.status, deepcopy(r.result_jsonb), r.input_sha256)
              for r in session.scalars(select(PreSpecCompanyFitAttempt))]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("company-fit state read by the deep-review gate")

    for name in ("company_current_flags", "latest_attempts", "company_fit_view", "current_flags", "gate_reasons"):
        monkeypatch.setattr(fit, name, forbidden)
    created = create(session, svc, world, preview(session, svc, world)["preview_id"])
    assert created["status"] == "queued"
    session.expire_all()
    after = [(r.id, r.status, deepcopy(r.result_jsonb), r.input_sha256)
             for r in session.scalars(select(PreSpecCompanyFitAttempt))]
    assert after == before


def test_t3_sw_y_without_priority_grade_is_eligible_and_sw_n_is_not(world_session, monkeypatch) -> None:
    session, world, svc = world_session
    from app.deep_review.services import effective_grade, input_versions

    def forbidden(*_args, **_kwargs):
        raise AssertionError("C-1 grade consulted on the company path")

    for module, name in ((effective_grade, "priority_notice_ids"), (effective_grade, "effective_grades"),
                         (effective_grade, "eligible_with_grade"), (luna_inputs, "eligible_with_grade"),
                         (input_versions, "effective_grade_basis")):
        monkeypatch.setattr(module, name, forbidden)
    # The notice has no screening judgment at all (no `우선 검토` grade).
    created = create(session, svc, world, preview(session, svc, world)["preview_id"])
    assert created["status"] == "queued"
    session.get(Notice, world.notice_id).qualification_flags_json = {"sw_business_status": "N"}
    session.commit()
    assert code(lambda: preview(session, svc, world)) == "effective_grade_ineligible"


# --- T6: currentness, retry and versioning -------------------------------------------


def test_t6_same_review_retry_creates_a_new_attempt_with_its_own_frozen_provenance(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        first = preview(session, svc, world)
        created = create(session, svc, world, first["preview_id"])
        review_id = UUID(created["id"])
        # A creation preview (no target) is not a retry preview; an active attempt blocks retry.
        target = preview(session, svc, world, review_id=review_id)
        assert target["input"]["target_review_id"] == str(review_id)
        assert target["input"]["execution_nonce"] == target["preview_id"]
        assert code(lambda: retry(session, svc, world, review_id, target["preview_id"])) == "active_attempt_exists"
        fail_current_attempt(session, review_id)
        assert code(lambda: retry(session, svc, world, review_id, preview(session, svc, world)["preview_id"])) == "preview_changed"
        assert code(lambda: create(session, svc, world, target["preview_id"])) == "preview_changed"
        request_id = uuid4()
        attempt = retry(session, svc, world, review_id, target["preview_id"], request_id=request_id)
        assert retry(session, svc, world, review_id, target["preview_id"], request_id=request_id) == attempt
        assert attempt["sequence"] == 2 and attempt["preview_id"] == target["preview_id"]
        assert code(lambda: retry(session, svc, world, review_id, target["preview_id"])) == "active_attempt_exists"
        session.expire_all()
        review = session.get(DeepReview, review_id)
        attempts = session.scalars(select(DeepReviewAttempt).where(DeepReviewAttempt.deep_review_id == review_id)
                                   .order_by(DeepReviewAttempt.sequence)).all()
        assert [a.status for a in attempts] == ["superseded", "queued"]
        assert review.current_attempt_id == attempts[1].id and count(session, DeepReview) == 1
        view = cdr.company_review_view(svc, session, review)
        assert view["current_attempt"]["id"] == str(attempts[1].id)
        assert view["provenance"]["input_sha256"] == target["input_sha256"] == view["input_sha256"]
        first_row = session.get(DeepReviewPreview, UUID(first["preview_id"]))
        second_row = session.get(DeepReviewPreview, UUID(target["preview_id"]))
        assert first_row.provenance_jsonb["input_sha256"] == first["input_sha256"]
        assert {k: v for k, v in first_row.provenance_jsonb.items() if k != "input_sha256"} == {
            k: v for k, v in second_row.provenance_jsonb.items() if k != "input_sha256"}
        # Each attempt's approval binds its own frozen input (worker-side approval check).
        assert luna_inputs.approved_company_input(session, attempts[0].id, review) == first["input"]
        assert luna_inputs.approved_company_input(session, attempts[1].id, review) == target["input"]


def test_t6_new_binding_marks_old_stale_and_needs_a_new_review(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        svc = service()
        first = preview(session, svc, world)
        created = create(session, svc, world, first["preview_id"])
        review_id = UUID(created["id"])
        fail_current_attempt(session, review_id)
        review = session.get(DeepReview, review_id)
        assert cdr.is_company_review_current(session, review) is True
        frozen_rows = _rows(session)

        rebound = import_company(session, raw=second_source())
        session.commit()
        assert rebound.graph_version_id != world.graph_version_id
        session.expire_all()
        review = session.get(DeepReview, review_id)
        assert cdr.is_company_review_current(session, review) is False
        assert _rows(session) == frozen_rows  # old review/preview/approval never rewritten
        stale = cdr.company_review_view(svc, session, review)
        assert stale["is_current"] is False and stale["graph_version_id"] == str(world.graph_version_id)
        # A retry of the old lineage is refused; a new graph is a new review.
        assert code(lambda: preview(session, svc, world, review_id=review_id)) == "version_conflict"
        fresh = preview(session, svc, world)
        assert fresh["graph_version_id"] == str(rebound.graph_version_id)
        new = create(session, svc, world, fresh["preview_id"])
        assert new["id"] != created["id"] and new["graph_version_id"] == str(rebound.graph_version_id)
        assert new["is_current"] is True
        session.expire_all()
        flags = cdr.company_review_current_flags(session, session.scalars(select(DeepReview)).all())
        assert flags == {review_id: False, UUID(new["id"]): True}
        assert session.get(DeepReview, review_id).graph_version_id == world.graph_version_id


def _rows(session: Session):
    session.expire_all()
    return (
        [(r.id, r.company_id, r.graph_version_id, r.profile_version_id, r.policy_version_id, r.bundle_id)
         for r in session.scalars(select(DeepReview).order_by(DeepReview.id))],
        [(r.id, r.input_sha256, deepcopy(r.input_snapshot), deepcopy(r.provenance_jsonb))
         for r in session.scalars(select(DeepReviewPreview).order_by(DeepReviewPreview.id))],
        [(r.id, r.preview_id, r.attempt_id, r.company_id)
         for r in session.scalars(select(DeepReviewApproval).order_by(DeepReviewApproval.id))],
    )


@pytest.mark.parametrize("change", ["policy_setting", "overview", "bundle", "document", "sw", "none"])
def test_t6_currentness_follows_every_input(world_session, monkeypatch, change) -> None:
    session, world, svc = world_session
    created = create(session, svc, world, preview(session, svc, world)["preview_id"])
    review_id = UUID(created["id"])
    before = _rows(session)
    if change == "policy_setting":
        policy = import_policy_version(session, LUNA_HP, created_by_name="정책 담당자",
                                       validation_metadata=_measured("d"))
        session.commit()
        deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(policy.id))
    elif change == "overview":
        new_overview(session, world)
    elif change == "bundle":
        session.get(DocumentBundle, world.bundle_id).status = "superseded"
        session.commit()
    elif change == "document":
        session.get(DocumentVersion, world.fit.document_id).is_current = False
        session.commit()
    elif change == "sw":
        session.get(Notice, world.notice_id).qualification_flags_json = {"sw_business_status": "unknown"}
        session.commit()
    session.expire_all()
    review = session.get(DeepReview, review_id)
    assert cdr.is_company_review_current(session, review) is (change == "none")
    assert _rows(session) == before


def test_t6_approval_invalid_detects_tampered_company_approval(world_session) -> None:
    session, world, svc = world_session
    other = import_company(session, "demo-public-si")
    session.commit()
    frozen = preview(session, svc, world)
    created = create(session, svc, world, frozen["preview_id"])
    review = session.get(DeepReview, UUID(created["id"]))
    attempt_id = review.current_attempt_id
    assert luna_inputs.approved_company_input(session, attempt_id, review) == frozen["input"]
    # The legacy (NULL lineage) check never accepts a company attempt.
    with pytest.raises(InputVersionError) as error:
        luna_inputs.approved_input(session, attempt_id, review)
    assert error.value.code == "approval_invalid"

    def invalid() -> str:
        session.expire_all()
        current = session.get(DeepReview, review.id)
        with pytest.raises(InputVersionError) as raised:
            luna_inputs.approved_company_input(session, attempt_id, current)
        return raised.value.code

    pid = UUID(frozen["preview_id"]).hex
    approval_id = session.scalar(select(DeepReviewApproval.id)).hex
    _tamper(session, "UPDATE deep_review_approval SET company_id = :company WHERE id = :id",
            company=other.company_id.hex, id=approval_id)
    assert invalid() == "approval_invalid"
    _tamper(session, "UPDATE deep_review_approval SET company_id = :company WHERE id = :id",
            company=world.company_id.hex, id=approval_id)
    assert luna_inputs.approved_company_input(session, attempt_id, session.get(DeepReview, review.id)) == frozen["input"]
    snapshot = deepcopy(frozen["input"])
    snapshot["coverage"]["excluded_fact_keys"] = ["tampered"]
    _tamper(session, "UPDATE deep_review_preview SET input_snapshot = :value WHERE id = :id",
            value=json.dumps(snapshot, ensure_ascii=False), id=pid)
    assert invalid() == "approval_invalid"
    rehashed = canonical_json_hash(snapshot)
    _tamper(session, "UPDATE deep_review_preview SET input_sha256 = :digest WHERE id = :id", digest=rehashed, id=pid)
    assert invalid() == "approval_invalid"  # provenance still pins the approved hash
    session.execute(text("DELETE FROM deep_review_approval"))
    session.commit()
    assert invalid() == "approval_invalid"


def test_legacy_luna_paths_never_touch_company_rows(world_session) -> None:
    session, world, svc = world_session
    frozen = preview(session, svc, world)
    created = create(session, svc, world, frozen["preview_id"])
    fail_current_attempt(session, created["id"])
    review_id = UUID(created["id"])
    assert code(lambda: svc.create_attempt(session, review_id, "심층 담당자", uuid4(),
                                           preview_id=UUID(frozen["preview_id"]))) == "not_found"
    assert code(lambda: luna_inputs.preview(svc, session, world.notice_id, world.bundle_id, True, review_id)) == "not_found"
    second = preview(session, svc, world)
    notice = session.get(Notice, world.notice_id)
    assert code(lambda: luna_inputs.check(svc, session, UUID(second["preview_id"]), notice, world.bundle_id,
                                          None, None, True)) == "preview_changed"
    session.rollback()
    assert count(session, DeepReviewAttempt) == 1 and session.scalar(select(DeepReviewApproval.id).where(
        DeepReviewApproval.preview_id == UUID(second["preview_id"]))) is None


def test_company_review_view_rejects_identity_mismatch(world_session) -> None:
    session, world, svc = world_session
    created = create(session, svc, world, preview(session, svc, world)["preview_id"])
    review = session.get(DeepReview, UUID(created["id"]))
    pid = session.scalar(select(DeepReviewApproval.preview_id)).hex
    provenance = deepcopy(session.get(DeepReviewPreview, UUID(pid)).provenance_jsonb)
    provenance["graph_sha256"] = "f" * 64
    _tamper(session, "UPDATE deep_review_preview SET provenance_jsonb = :value WHERE id = :id",
            value=json.dumps(provenance), id=pid)
    assert code(lambda: cdr.company_review_view(svc, session, session.get(DeepReview, review.id))) == "processing_failed"
    with pytest.raises(ValueError):
        CompanyReviewView.model_validate({**created, "graph_sha256": "f" * 64})
    with pytest.raises(ValueError):
        CompanyReviewView.model_validate({**created, "bundle_id": str(uuid4())})


# --- PostgreSQL: constraints behind the service invariants --------------------------


@requires_postgres
def test_pg_company_review_key_includes_graph_and_scope_is_immutable(monkeypatch) -> None:
    with migrated_engine() as engine:
        with Session(engine) as session:
            world = deep_world(session, monkeypatch)
            svc = service()
            created = create(session, svc, world, preview(session, svc, world)["preview_id"])
            review_id = UUID(created["id"])
            rebound = import_company(session, raw=second_source())
            session.commit()
            columns = ("company_id, notice_id, bundle_id, profile_version_id, policy_version_id, "
                       "effective_grade_at_start, status, created_at, graph_version_id")
            insert = (f"INSERT INTO bidops.deep_review (id, {columns}) VALUES (:id, :company, :notice, :bundle, "
                      ":profile, :policy, 'unknown', 'failed', now(), :graph)")
            same = {"company": world.company_id, "notice": world.notice_id, "bundle": world.bundle_id,
                    "profile": world.profile_version_id, "policy": world.policy_id, "graph": world.graph_version_id}
            with pytest.raises(DBAPIError, match="uq_deep_review_company_inputs"):
                with engine.begin() as connection:
                    connection.execute(text(insert), {"id": uuid4(), **same})
            # The same lineage with the new graph/profile of the same company is a distinct review.
            with engine.begin() as connection:
                connection.execute(text(insert), {"id": uuid4(), **same, "graph": rebound.graph_version_id,
                                                  "profile": rebound.profile_version_id})
            # Another company's graph cannot be attached to this company/profile.
            other = import_company(session, "demo-public-si")
            session.commit()
            with pytest.raises(DBAPIError, match="fk_deep_review_graph_scope"):
                with engine.begin() as connection:
                    connection.execute(text(insert), {"id": uuid4(), **same, "graph": other.graph_version_id})
            with pytest.raises(DBAPIError, match="company scope is immutable"):
                with engine.begin() as connection:
                    connection.execute(text("UPDATE bidops.deep_review SET graph_version_id = :graph WHERE id = :id"),
                                       {"graph": rebound.graph_version_id, "id": review_id})
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text("UPDATE bidops.deep_review_preview SET provenance_jsonb = provenance_jsonb"))
            assert session.scalar(text("SELECT company_id FROM bidops.deep_review_approval")) == world.company_id
            assert session.scalar(text(
                "SELECT count(*) FROM bidops.deep_review_preview WHERE company_id IS NOT NULL "
                "AND provenance_jsonb IS NOT NULL AND graph_version_id IS NOT NULL")) == 1
        get_settings.cache_clear()
