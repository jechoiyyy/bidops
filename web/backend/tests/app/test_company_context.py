"""DEMO-01 company API and legacy NULL-lineage compatibility."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import quote_from_bytes
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app import lifecycle
from app.core.api_errors import BundleServiceError
from app.core.db import get_db, init_db, schema_bound
from app.core.models import AuditEvent, IdempotencyRecord
from app.deep_review.models import (
    AnalysisPolicyVersion,
    CompanyFitPolicyVersion,
    CompanyKnowledgeSource,
    CompanyKnowledgeVersion,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DocumentBundle,
    DocumentVersion,
    KnowledgeOntologyVersion,
    PreSpecCompanyFitAttempt,
    PrespecOverviewRun,
    ProfileVersion,
    WorkJob,
)
from app.deep_review.services.auto_preparation import auto_preparation_fields
from app.deep_review.services.company_fit import latest_attempts
from app.deep_review.services import company_fit_runner as company_fit_worker
from app.deep_review.services.company_fit_runner import PreSpecCompanyFitRunner
from app.deep_review.services.deep_reviews import DeepReviewService
from app.deep_review.services.input_versions import (
    InputVersionError,
    import_profile_version,
    resolve_active_versions,
)
from app.deep_review.services.opportunity_reviews import opportunity_reviews
from app.deep_review.services.overview_runs import _freeze_assessment_profile
from app.lifecycle.models import (
    Company,
    CompanyOpportunityTracking,
    CompanyTrackingEvent,
    Notice,
    Opportunity,
    OpportunityLink,
)
from app.lifecycle.schemas.companies import CompanyDTO
from app.lifecycle.services.company_context import register_company
from app.lifecycle.services.opportunity_tracking import (
    OpportunityTrackingError,
    set_company_tracking,
)
from tests.app.test_runtime_database_privileges import _apply_policy, _ensure_roles
from tests.postgres import (
    migrated_engine,
    requires_postgres,
    temporary_database,
)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind)
    try:
        yield bind
    finally:
        bind.dispose()


def _application(engine, monkeypatch: pytest.MonkeyPatch, *, enabled: bool):
    sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def request_session():
        with sessions() as session:
            yield session

    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(demo_enabled=enabled),
    )
    application = main_module.create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = request_session
    return application, sessions


def _actor_headers(name: str) -> dict[str, str]:
    encoded = quote_from_bytes(name.encode("utf-8"), safe="")
    return {
        "X-BidOps-Actor-Name": f"UTF-8''{encoded}",
        "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
    }


def _tracking_path(company_id, opportunity_id: int) -> str:
    return f"/api/companies/{company_id}/opportunities/{opportunity_id}/tracking"


def _profile(*, version: int, company_id=None, digest: str) -> ProfileVersion:
    return ProfileVersion(
        id=uuid4(),
        company_id=company_id,
        version=version,
        label=f"profile-{version}",
        profile_payload={"source_sha256": digest},
        profile_sha256=digest,
        source_kind="fixture",
    )


def _policy() -> AnalysisPolicyVersion:
    return AnalysisPolicyVersion(
        id=uuid4(),
        version=1,
        label="fixture",
        model_endpoint_ref="fixture",
        model_name="fixture",
        prompts={},
        validation_rules={},
        policy_sha256="f" * 64,
    )


def test_demo_config_and_disabled_routes_are_guarded_before_validation(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, _sessions = _application(engine, monkeypatch, enabled=False)
    client = TestClient(application)

    assert client.get("/api/demo-config").json() == {"enabled": False}
    for path in (
        "/api/companies",
        "/api/companies/not-a-uuid",
        "/companies",
        "/companies/not-a-uuid",
        "/api/pre-specs/not-an-int/company-comparison",
        "/pre-specs/not-an-int/company-comparison",
    ):
        assert client.get(path).status_code == 404


def test_company_list_and_detail_are_strict_sorted_and_read_only(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch, enabled=True)
    with sessions() as session:
        second = register_company(
            session,
            slug="beta-si",
            name="베타 SI",
            is_fictional=True,
            actor="테스터",
        )
        first = register_company(
            session,
            slug="alpha-si",
            name="알파 SI",
            is_fictional=True,
            actor="테스터",
        )
        session.commit()
        audit_count = session.scalar(select(func.count()).select_from(AuditEvent))

    client = TestClient(application)
    assert client.get("/api/demo-config").json() == {"enabled": True}
    listing = client.get("/api/companies", params={"limit": 1, "offset": 0})
    assert listing.status_code == 200
    assert listing.json() == {
        "items": [
            {
                "company_id": str(first.company_id),
                "slug": "alpha-si",
                "name": "알파 SI",
                "is_fictional": True,
                "created_at": listing.json()["items"][0]["created_at"],
            }
        ],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }
    detail = client.get(f"/api/companies/{second.company_id}")
    assert detail.status_code == 200
    assert set(detail.json()) == {
        "company_id", "slug", "name", "is_fictional", "created_at"
    }
    assert client.get(f"/api/companies/{uuid4()}").status_code == 404
    assert client.get("/api/companies/not-a-uuid").status_code == 422

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 2
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count

    with pytest.raises(ValidationError):
        CompanyDTO.model_validate({**detail.json(), "unexpected": "rejected"})


def test_register_company_is_flush_only_idempotent_and_identity_checked(engine) -> None:
    assert lifecycle.register_company is register_company
    with Session(engine) as session:
        created = register_company(
            session,
            slug="alpha-si",
            name=" 알파 SI ",
            is_fictional=True,
            actor="등록 담당자",
        )
        replay = register_company(
            session,
            slug="alpha-si",
            name="알파 SI",
            is_fictional=True,
            actor="등록 담당자",
        )
        assert created.created is True
        assert replay == type(replay)(company_id=created.company_id, created=False)
        with pytest.raises(BundleServiceError) as conflict:
            register_company(
                session,
                slug="alpha-si",
                name="다른 회사",
                is_fictional=True,
                actor="등록 담당자",
            )
        assert conflict.value.code == "company_identity_conflict"
        session.rollback()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_legacy_profile_resolution_never_promotes_a_company_profile(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = Company(id=uuid4(), slug="alpha-si", name="알파 SI", is_fictional=True)
    profile = _profile(version=1, company_id=company.id, digest="a" * 64)
    policy = _policy()
    with Session(engine) as session:
        session.add(company)
        session.flush()
        session.add_all([profile, policy])
        session.commit()
        environ = {
            "BIDOPS_ACTIVE_PROFILE_VERSION_ID": str(profile.id),
            "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": str(policy.id),
        }
        with pytest.raises(InputVersionError) as error:
            resolve_active_versions(
                session, environ=environ, allow_unmeasured_reference=True
            )
        assert error.value.code == "service_unavailable"

        monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(profile.id))
        assert _freeze_assessment_profile(session) == (None, None, "invalid", [])


def test_legacy_profile_import_does_not_reuse_company_digest(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.deep_review.services import input_versions

    digest = "a" * 64
    payload = {
        "schema": "bidops.company-profile.v1",
        "source_file": "docs/reference/company-profile.md",
        "source_sha256": digest,
        "facts": [],
    }
    metadata = SimpleNamespace(object_version_id="version-1", etag="etag-1")
    monkeypatch.setattr(
        input_versions,
        "_profile_payload_and_facts",
        lambda _path: (payload, [], b"approved legacy profile"),
    )
    monkeypatch.setattr(
        input_versions,
        "_store_profile_source",
        lambda _raw, _digest: ("profiles/legacy", len(b"approved legacy profile"), metadata),
    )

    with Session(engine) as session:
        company = Company(id=uuid4(), slug="alpha-si", name="알파 SI", is_fictional=True)
        company_profile = _profile(version=1, company_id=company.id, digest=digest)
        session.add(company)
        session.flush()
        session.add(company_profile)
        session.flush()
        imported = import_profile_version(
            session,
            Path("ignored.md"),
            created_by_name="등록 담당자",
        )
        assert imported.id != company_profile.id
        assert imported.company_id is None
        assert imported.version == 2


def _company_graph(session: Session, *, company_id, profile_id) -> CompanyKnowledgeVersion:
    """Minimal graph version bound to (company, profile): DEMO-03 (0036) lineage."""

    digest = uuid4().hex * 2
    ontology = KnowledgeOntologyVersion(id=uuid4(), version=f"fixture-{uuid4().hex[:8]}",
                                        sha256=uuid4().hex * 2, payload={"fixture": True})
    content = ContentObject(id=uuid4(), sha256=digest, size_bytes=1, detected_mime="application/json",
                            retention_class="fixture")
    session.add_all([ontology, content])
    session.flush()
    location = ContentObjectLocation(id=uuid4(), content_object_id=content.id, namespace_key="source",
                                     object_key=f"fixture/{uuid4().hex}", status="verified")
    session.add(location)
    session.flush()
    source = CompanyKnowledgeSource(id=uuid4(), company_id=company_id, source_sha256=digest, size_bytes=1,
                                    content_object_id=content.id, content_location_id=location.id)
    session.add(source)
    session.flush()
    graph = CompanyKnowledgeVersion(id=uuid4(), company_id=company_id, ontology_id=ontology.id,
                                    source_id=source.id, profile_version_id=profile_id, source_sha256=digest,
                                    graph_sha256=uuid4().hex * 2, snapshot={"fixture": True})
    session.add(graph)
    session.flush()
    return graph


def _company_fit_attempt(
    session: Session, seeded, document: DocumentVersion, *, input_sha256: str, created_at: datetime
) -> PreSpecCompanyFitAttempt:
    """A DEMO-03 (0036) company fit row: fit policy FK, graph scope, provenance, overview."""

    job = WorkJob(id=uuid4(), job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add(job)
    session.flush()
    run = PrespecOverviewRun(
        id=uuid4(), notice_id=seeded.notice.id, document_version_id=document.id, work_job_id=job.id,
        status="completed", range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="fixture", warnings_json=[], reason_codes=[], call_count=1, raw_response_refs=[],
        result_json={}, checks_json={"overall": "passed"}, completed_at=created_at,
    )
    policy = CompanyFitPolicyVersion(id=uuid4(), sha256=uuid4().hex * 2, payload={"fixture": True})
    session.add_all([run, policy])
    session.flush()
    attempt_id = uuid4()
    identity = {
        "purpose": "company_fit", "bundle_id": None, "company_id": str(seeded.company.id),
        "profile_version_id": str(seeded.company_profile.id),
        "graph_version_id": str(seeded.company_graph.id), "overview_run_id": str(run.id),
        "policy_version_id": str(policy.id), "policy_sha256": policy.sha256,
        "model_name": "fixture", "model_revision": None,
    }
    return PreSpecCompanyFitAttempt(
        id=attempt_id, company_id=seeded.company.id, notice_id=seeded.notice.id,
        document_version_id=document.id, overview_run_id=run.id,
        profile_version_id=seeded.company_profile.id, deep_policy_version_id=None,
        company_fit_policy_version_id=policy.id, graph_version_id=seeded.company_graph.id,
        input_jsonb={
            **identity, "schema_version": "bidops.company-analysis-input.v1",
            "execution_nonce": str(attempt_id), "target_review_id": None,
            "notice_id": seeded.notice.id, "document_version_ids": [str(document.id)],
        },
        input_sha256=input_sha256,
        provenance_jsonb={**identity, "input_sha256": input_sha256,
                          "documents": [{"document_version_id": str(document.id), "source_sha256": "a" * 64}]},
        policy_digest=policy.sha256, model_name="fixture", model_revision=None,
        quality_status="unmeasured_reference", status="queued", created_at=created_at,
    )


def _seed_legacy_and_company_analysis(session: Session):
    notice = Notice(notice_key=f"company-context-{uuid4()}", source_type="pre_spec", title="회사 경계")
    opportunity = Opportunity(first_registered_stage="pre_spec")
    company = Company(id=uuid4(), slug="alpha-si", name="알파 SI", is_fictional=True)
    session.add_all([notice, opportunity, company])
    session.flush()
    session.add(
        OpportunityLink(
            opportunity_id=opportunity.id,
            notice_id=notice.id,
            stage="notice",
            link_type="official",
            status="확정",
            evidence_external_no="fixture-prespec",
        )
    )
    bundle = DocumentBundle(
        id=uuid4(), notice_id=notice.id, revision=1, version=1,
        status="draft", issues_snapshot=[],
    )
    legacy_profile = _profile(version=1, company_id=None, digest="1" * 64)
    company_profile = _profile(version=2, company_id=company.id, digest="2" * 64)
    policy = _policy()
    session.add_all([bundle, legacy_profile, company_profile, policy])
    session.flush()
    company_graph = _company_graph(session, company_id=company.id, profile_id=company_profile.id)
    company_review = DeepReview(
        id=uuid4(), company_id=company.id, notice_id=notice.id, bundle_id=bundle.id,
        profile_version_id=company_profile.id, policy_version_id=policy.id,
        graph_version_id=company_graph.id,
        effective_grade_at_start="unknown", status="queued",
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    legacy_review = DeepReview(
        id=uuid4(), company_id=None, notice_id=notice.id, bundle_id=bundle.id,
        profile_version_id=legacy_profile.id, policy_version_id=policy.id,
        effective_grade_at_start="unknown", status="queued",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    session.add_all([company_review, legacy_review])
    session.flush()
    service = DeepReviewService()
    company_attempt = service._seed_attempt(session, company_review, sequence=1, actor="테스터")
    legacy_attempt = service._seed_attempt(session, legacy_review, sequence=1, actor="테스터")
    session.flush()
    session.get(WorkJob, company_attempt.work_job_id).priority = 100
    session.flush()
    return SimpleNamespace(
        notice=notice,
        opportunity=opportunity,
        company=company,
        company_profile=company_profile,
        company_graph=company_graph,
        legacy_profile=legacy_profile,
        company_review=company_review,
        legacy_review=legacy_review,
        company_job=session.get(WorkJob, company_attempt.work_job_id),
        legacy_job=session.get(WorkJob, legacy_attempt.work_job_id),
        policy=policy,
        service=service,
    )


def test_legacy_lists_projections_and_worker_claim_ignore_company_rows(engine) -> None:
    with Session(engine, expire_on_commit=False) as session:
        seeded = _seed_legacy_and_company_analysis(session)
        session.commit()

        reviews = opportunity_reviews(session, seeded.opportunity.id)
        assert [item["deep_review_id"] for item in reviews["items"]] == [
            str(seeded.legacy_review.id)
        ]
        fields = auto_preparation_fields(session, [seeded.notice.id])
        assert fields[seeded.notice.id]["latest_deep_review_id"] == seeded.legacy_review.id

        claim = seeded.service.claim_next_job(session, "legacy-worker")
        assert claim is not None
        assert claim.deep_review_id == seeded.legacy_review.id
        session.expire_all()
        assert session.get(WorkJob, seeded.company_job.id).status == "queued"


def test_legacy_auto_enqueue_uses_null_scope_beside_a_company_attempt(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        seeded = _seed_legacy_and_company_analysis(session)
        enqueue_profile = _profile(version=3, company_id=None, digest="3" * 64)
        session.add(enqueue_profile)
        content = ContentObject(
            id=uuid4(),
            sha256="4" * 64,
            size_bytes=1,
            detected_mime="application/pdf",
            retention_class="fixture",
        )
        session.add(content)
        session.flush()
        document = DocumentVersion(
            id=uuid4(),
            notice_id=seeded.notice.id,
            content_object_id=content.id,
            version=1,
            source_kind="manual",
            original_filename="enqueue.pdf",
            role="제안요청서",
            is_current=True,
            safety_status="safe",
            needs_human_review=False,
        )
        session.add(document)
        bundle = session.scalar(
            select(DocumentBundle).where(DocumentBundle.notice_id == seeded.notice.id)
        )
        assert bundle is not None
        bundle.status = "ready"
        bundle.confirmed_by_name = "auto-preparation"
        bundle.confirmed_at = datetime(2026, 10, 9, tzinfo=UTC)
        session.flush()

        v1_input = {
            "schema_version": "bidops.prespec-company-fit-input.v1",
            "notice_id": str(seeded.notice.id),
            "document_version_id": str(document.id),
            "overview_id": None,
            "profile_version_id": str(seeded.company_profile.id),
            "deep_policy_version_id": str(seeded.policy.id),
            "policy_digest": "5" * 64,
            "model_name": "fixture",
            "model_revision": "6" * 64,
            "quality_status": "unmeasured_reference",
        }
        company_attempt = _company_fit_attempt(
            session, seeded, document, input_sha256="7" * 64,
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
        session.add(company_attempt)
        session.commit()

        legacy_input = {
            **v1_input,
            "profile_version_id": str(enqueue_profile.id),
            "policy_digest": "8" * 64,
            "model_revision": "9" * 64,
        }
        source = SimpleNamespace(
            id=None,
            document_id=document.id,
            quality_status="unmeasured_reference",
        )
        monkeypatch.setattr(company_fit_worker, "configured_binding", lambda _settings: None)
        monkeypatch.setattr(
            company_fit_worker,
            "resolve_active_versions",
            lambda _session, *, allow_unmeasured_reference: (
                enqueue_profile,
                seeded.policy,
            ),
        )
        monkeypatch.setattr(
            company_fit_worker,
            "priority_notice_ids",
            lambda _session, ids: frozenset(ids),
        )
        monkeypatch.setattr(company_fit_worker, "current_runs", lambda _session, _ids: {})
        monkeypatch.setattr(
            company_fit_worker,
            "overview_inputs",
            lambda _session, _ids, *, runs: {seeded.notice.id: source},
        )
        monkeypatch.setattr(
            company_fit_worker,
            "_auto_start_scope",
            lambda _session, _notice_id, *, require_company_fit, runs: (
                bundle.id,
                None,
            ),
        )
        monkeypatch.setattr(
            company_fit_worker,
            "frozen_input",
            lambda _session, _notice_id, _source, *, settings: legacy_input,
        )
        runner = PreSpecCompanyFitRunner(
            settings=SimpleNamespace(reference_workflow_mode=True)
        )
        runner._enqueue_one(session)

        rows = session.scalars(
            select(PreSpecCompanyFitAttempt)
            .where(PreSpecCompanyFitAttempt.notice_id == seeded.notice.id)
            .order_by(PreSpecCompanyFitAttempt.created_at, PreSpecCompanyFitAttempt.id)
        ).all()
        assert len(rows) == 2
        assert {row.company_id for row in rows} == {seeded.company.id, None}
        legacy = next(row for row in rows if row.company_id is None)
        assert legacy.profile_version_id == enqueue_profile.id
        assert legacy.input_jsonb == legacy_input


def test_company_fit_projection_claim_and_recovery_use_only_null_lineage(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        seeded = _seed_legacy_and_company_analysis(session)
        content = ContentObject(
            id=uuid4(), sha256="3" * 64, size_bytes=1,
            detected_mime="application/pdf", retention_class="fixture",
        )
        session.add(content)
        session.flush()
        document = DocumentVersion(
            id=uuid4(), notice_id=seeded.notice.id, content_object_id=content.id,
            version=1, source_kind="manual", original_filename="fixture.pdf",
            role="제안요청서", is_current=True, safety_status="safe",
            needs_human_review=False,
        )
        session.add(document)
        session.flush()
        legacy_input = {
            "schema_version": "bidops.prespec-company-fit-input.v1",
            "notice_id": str(seeded.notice.id),
            "document_version_id": str(document.id),
            "overview_id": None,
            "profile_version_id": str(seeded.legacy_profile.id),
            "deep_policy_version_id": str(seeded.policy.id),
            "policy_digest": "5" * 64,
            "model_name": "fixture",
            "model_revision": "6" * 64,
            "quality_status": "unmeasured_reference",
        }
        legacy = PreSpecCompanyFitAttempt(
            id=uuid4(), company_id=None, notice_id=seeded.notice.id,
            document_version_id=document.id, profile_version_id=seeded.legacy_profile.id,
            deep_policy_version_id=seeded.policy.id, input_jsonb=legacy_input, input_sha256="4" * 64,
            policy_digest="5" * 64, model_name="fixture", model_revision="6" * 64,
            quality_status="unmeasured_reference", status="queued",
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        company = _company_fit_attempt(
            session, seeded, document, input_sha256="7" * 64,
            created_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=1),
        )
        session.add_all([legacy, company])
        session.flush()
        attempts = latest_attempts(session, [seeded.notice.id])
        assert attempts == {seeded.notice.id: legacy}

        now = datetime(2026, 10, 9, tzinfo=UTC)
        company.status = "running"
        company.lease_owner = "company-worker"
        company.lease_expires_at = now - timedelta(minutes=1)
        session.commit()
        runner = PreSpecCompanyFitRunner(
            settings=SimpleNamespace(
                prespec_company_fit_enabled=True,
                reference_workflow_mode=True,
            ),
            clock=lambda: now,
        )
        monkeypatch.setattr(runner, "_enqueue_one", lambda _session: None)
        monkeypatch.setattr(runner, "_eligible", lambda _session, _row: False)
        assert runner.run_once(session, "legacy-fit-worker") is True
        session.expire_all()
        assert session.get(PreSpecCompanyFitAttempt, company.id).status == "running"
        assert session.get(PreSpecCompanyFitAttempt, legacy.id).status == "failed"


def test_company_tracking_is_independent_replayable_and_leaves_legacy_state(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch, enabled=True)
    legacy_at = datetime(2026, 10, 9, 1, tzinfo=UTC)
    with sessions() as session:
        companies = [
            Company(id=uuid4(), slug=slug, name=name, is_fictional=True)
            for slug, name in (
                ("alpha-si", "알파 SI"),
                ("beta-si", "베타 SI"),
                ("gamma-si", "감마 SI"),
            )
        ]
        opportunity = Opportunity(
            first_registered_stage="pre_spec",
            tracking_status="보류",
            tracking_reason="기존 단일회사 판단",
            tracking_selected_by="기존 담당자",
            tracking_selected_at=legacy_at,
        )
        notice = Notice(
            notice_key=f"company-tracking-{uuid4()}",
            source_type="pre_spec",
            title="회사별 추적",
        )
        session.add_all([*companies, opportunity, notice])
        session.flush()
        link = OpportunityLink(
            opportunity_id=opportunity.id,
            notice_id=notice.id,
            stage="notice",
            link_type="official",
            status="확정",
            evidence_external_no="company-tracking-fixture",
        )
        session.add(link)
        session.flush()
        opportunity.recheck_signal_at = legacy_at + timedelta(hours=1)
        opportunity.recheck_signal_link_id = link.id
        session.commit()
        company_ids = [company.id for company in companies]
        opportunity_id = opportunity.id
        link_id = link.id

    client = TestClient(application)
    for company_id in company_ids:
        response = client.get(_tracking_path(company_id, opportunity_id))
        assert response.status_code == 200
        assert response.json() == {
            "company_id": str(company_id),
            "opportunity_id": opportunity_id,
            "tracking_status": "미선택",
            "reason": None,
            "selected_by": None,
            "selected_at": None,
            "revision": 0,
        }
    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CompanyOpportunityTracking)
        ) == 0
        assert session.scalar(select(func.count()).select_from(CompanyTrackingEvent)) == 0

    first_request_id = uuid4()
    first_payload = {
        "tracking_status": "계속 추적",
        "reason": "  신규 공고를 계속 확인  ",
        "expected_revision": 0,
        "request_id": str(first_request_id),
    }
    first = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json=first_payload,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["reason"] == "신규 공고를 계속 확인"
    assert first_body["selected_by"] == "알파 담당자"
    assert isinstance(first_body["selected_at"], str)
    assert first_body["revision"] == 1

    replay = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json=first_payload,
    )
    assert replay.status_code == 200
    assert replay.json() == first_body

    conflict = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json={**first_payload, "reason": "같은 키의 다른 본문"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    repeated = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json={
            "tracking_status": "계속 추적",
            "reason": "같은 상태를 새 판단으로 저장",
            "expected_revision": 1,
            "request_id": str(uuid4()),
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["tracking_status"] == "계속 추적"
    assert repeated.json()["reason"] == "같은 상태를 새 판단으로 저장"
    assert repeated.json()["revision"] == 2

    beta = client.patch(
        _tracking_path(company_ids[1], opportunity_id),
        headers=_actor_headers("베타 담당자"),
        json={
            "tracking_status": "보류",
            "reason": "파트너 확인 대기",
            "expected_revision": 0,
            "request_id": str(uuid4()),
        },
    )
    assert beta.status_code == 200
    assert beta.json()["tracking_status"] == "보류"
    assert client.get(_tracking_path(company_ids[2], opportunity_id)).json()[
        "revision"
    ] == 0

    stale = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json={
            "tracking_status": "종료",
            "reason": "오래된 화면에서 저장",
            "expected_revision": 0,
            "request_id": str(uuid4()),
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == {
        "code": "version_conflict",
        "message": "회사별 추적 상태가 변경되었습니다",
        "details": {"current_revision": 2},
    }

    reset_request_id = uuid4()
    reset = client.patch(
        _tracking_path(company_ids[0], opportunity_id),
        headers=_actor_headers("알파 담당자"),
        json={
            "tracking_status": "미선택",
            "reason": "회사별 검토 큐로 되돌림",
            "expected_revision": 2,
            "request_id": str(reset_request_id),
        },
    )
    assert reset.status_code == 200
    assert reset.json() == {
        "company_id": str(company_ids[0]),
        "opportunity_id": opportunity_id,
        "tracking_status": "미선택",
        "reason": None,
        "selected_by": None,
        "selected_at": None,
        "revision": 3,
    }

    with sessions() as session:
        stored_legacy = session.get(Opportunity, opportunity_id)
        assert stored_legacy is not None
        assert (
            stored_legacy.tracking_status,
            stored_legacy.tracking_reason,
            stored_legacy.tracking_selected_by,
            stored_legacy.tracking_selected_at,
            stored_legacy.recheck_signal_link_id,
        ) == (
            "보류",
            "기존 단일회사 판단",
            "기존 담당자",
            legacy_at,
            link_id,
        )
        events = session.scalars(
            select(CompanyTrackingEvent)
            .where(CompanyTrackingEvent.company_id == company_ids[0])
            .order_by(CompanyTrackingEvent.revision)
        ).all()
        assert [(event.revision, event.reason, event.actor) for event in events] == [
            (1, "신규 공고를 계속 확인", "알파 담당자"),
            (2, "같은 상태를 새 판단으로 저장", "알파 담당자"),
            (3, "회사별 검토 큐로 되돌림", "알파 담당자"),
        ]
        receipt = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == "company_tracking.set",
                IdempotencyRecord.request_id == first_request_id,
            )
        )
        assert receipt is not None
        assert receipt.response_snapshot == first_body
        assert session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.operation == "company_tracking.set")
        ) == 4


@pytest.mark.parametrize("corrupted_field", ["company_id", "opportunity_id"])
def test_company_tracking_replay_rejects_a_corrupt_loaded_snapshot_without_writes(
    engine, corrupted_field: str
) -> None:
    """Exercise the replay validator without mutating the append-only receipt."""

    with Session(engine) as session:
        company = Company(
            id=uuid4(), slug="receipt-si", name="영수증 SI", is_fictional=True
        )
        opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add_all([company, opportunity])
        session.commit()
        company_id, opportunity_id = company.id, opportunity.id
        request_id = uuid4()
        arguments = {
            "company_id": company_id,
            "opportunity_id": opportunity_id,
            "status": "계속 추적",
            "reason": "영수증 재생 검증",
            "expected_revision": 0,
            "request_id": request_id,
            "selected_by": "재생 담당자",
            "selected_at": datetime(2026, 10, 9, 2, tzinfo=UTC),
        }
        result = set_company_tracking(session, **arguments)
        session.commit()
        assert result.response.revision == 1

        receipt = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == "company_tracking.set",
                IdempotencyRecord.request_id == request_id,
            )
        )
        assert receipt is not None
        corrupt_snapshot = dict(receipt.response_snapshot)
        corrupt_snapshot[corrupted_field] = (
            str(uuid4()) if corrupted_field == "company_id" else opportunity_id + 1
        )
        receipt.response_snapshot = corrupt_snapshot

        with pytest.raises(OpportunityTrackingError) as replay_error:
            set_company_tracking(session, **arguments)
        assert replay_error.value.code == "processing_failed"
        session.rollback()

    with Session(engine) as session:
        current = session.get(
            CompanyOpportunityTracking, (company_id, opportunity_id)
        )
        assert current is not None
        assert current.revision == 1
        assert session.scalar(
            select(func.count()).select_from(CompanyTrackingEvent)
        ) == 1
        stored_receipt = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == "company_tracking.set",
                IdempotencyRecord.request_id == request_id,
            )
        )
        assert stored_receipt is not None
        assert stored_receipt.response_snapshot == result.snapshot


def test_company_tracking_request_is_strict_and_actor_decode_is_reused(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch, enabled=True)
    with sessions() as session:
        company = Company(
            id=uuid4(), slug="strict-si", name="엄격 SI", is_fictional=True
        )
        opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add_all([company, opportunity])
        session.commit()
        company_id, opportunity_id = company.id, opportunity.id

    client = TestClient(application)
    path = _tracking_path(company_id, opportunity_id)
    assert client.get(_tracking_path(uuid4(), opportunity_id)).status_code == 404
    assert client.get(_tracking_path(company_id, opportunity_id + 100_000)).status_code == 404
    base = {
        "tracking_status": "계속 추적",
        "reason": "엄격 요청",
        "expected_revision": 0,
        "request_id": str(uuid4()),
    }
    assert client.patch(
        path,
        headers=_actor_headers("엄격 담당자"),
        json={**base, "unexpected": True},
    ).status_code == 422
    assert client.patch(
        path,
        headers=_actor_headers("엄격 담당자"),
        json={**base, "expected_revision": True},
    ).status_code == 422
    assert client.patch(
        path,
        headers=_actor_headers("엄격 담당자"),
        json={**base, "reason": " "},
    ).json()["error"]["code"] == "tracking_reason_required"
    too_long = client.patch(
        path,
        headers=_actor_headers("엄격 담당자"),
        json={**base, "reason": "가" * 2001},
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "invalid_request"
    malformed_actor = client.patch(
        path,
        headers={
            "X-BidOps-Actor-Name": "UTF-8''%EA%B0",
            "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
        },
        json=base,
    )
    assert malformed_actor.status_code == 400
    assert malformed_actor.json()["error"]["code"] == "actor_name_invalid"
    missing = client.patch(
        _tracking_path(uuid4(), opportunity_id),
        headers=_actor_headers("엄격 담당자"),
        json=base,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    with sessions() as session:
        assert session.get(
            CompanyOpportunityTracking, (company_id, opportunity_id)
        ) is None


def test_company_tracking_unrelated_integrity_failure_rolls_back_current_and_receipt(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, sessions = _application(engine, monkeypatch, enabled=True)
    with sessions() as session:
        company = Company(
            id=uuid4(), slug="atomic-si", name="원자성 SI", is_fictional=True
        )
        opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add_all([company, opportunity])
        session.flush()
        session.add(
            CompanyTrackingEvent(
                company_id=company.id,
                opportunity_id=opportunity.id,
                revision=1,
                previous_status="미선택",
                new_status="계속 추적",
                reason="미리 존재하는 충돌 event",
                actor="기존 담당자",
                request_id=uuid4(),
                created_at=datetime(2026, 10, 9, tzinfo=UTC),
            )
        )
        session.commit()
        company_id, opportunity_id = company.id, opportunity.id

    request_id = uuid4()
    response = TestClient(application).patch(
        _tracking_path(company_id, opportunity_id),
        headers=_actor_headers("새 담당자"),
        json={
            "tracking_status": "계속 추적",
            "reason": "원자적으로 저장",
            "expected_revision": 0,
            "request_id": str(request_id),
        },
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "processing_failed"
    with sessions() as session:
        assert session.get(
            CompanyOpportunityTracking, (company_id, opportunity_id)
        ) is None
        assert session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(
                IdempotencyRecord.operation == "company_tracking.set",
                IdempotencyRecord.request_id == request_id,
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(CompanyTrackingEvent)
        ) == 1


@requires_postgres
def test_company_tracking_app_role_serializes_missing_row_and_replays_winner() -> None:
    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        owner_engine = schema_bound(create_engine(database_url, future=True))
        app_engine = schema_bound(create_engine(database_url, future=True))
        try:
            with Session(owner_engine) as session:
                company = Company(
                    id=uuid4(), slug="race-si", name="경합 SI", is_fictional=True
                )
                opportunities = [
                    Opportunity(first_registered_stage="pre_spec"),
                    Opportunity(first_registered_stage="pre_spec"),
                ]
                session.add_all([company, *opportunities])
                session.commit()
                company_id = company.id
                opportunity_ids = [item.id for item in opportunities]

            def race(
                *,
                opportunity_id: int,
                request_id,
                barrier: Barrier,
            ) -> dict[str, object]:
                with Session(app_engine) as session:
                    session.connection().exec_driver_sql("SET LOCAL ROLE app")
                    barrier.wait(timeout=10)
                    try:
                        result = set_company_tracking(
                            session,
                            company_id=company_id,
                            opportunity_id=opportunity_id,
                            status="계속 추적",
                            reason="동시 최초 저장",
                            expected_revision=0,
                            request_id=request_id,
                            selected_by="경합 담당자",
                        )
                        session.commit()
                        return {
                            "outcome": "ok",
                            "replayed": result.replayed,
                            "snapshot": result.snapshot,
                        }
                    except OpportunityTrackingError as error:
                        session.rollback()
                        return {"outcome": "error", "code": error.code}

            same_request_id = uuid4()
            same_barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as executor:
                same_results = list(
                    executor.map(
                        lambda _index: race(
                            opportunity_id=opportunity_ids[0],
                            request_id=same_request_id,
                            barrier=same_barrier,
                        ),
                        range(2),
                    )
                )
            assert [result["outcome"] for result in same_results] == ["ok", "ok"]
            assert sorted(result["replayed"] for result in same_results) == [False, True]
            assert same_results[0]["snapshot"] == same_results[1]["snapshot"]
            assert isinstance(same_results[0]["snapshot"]["selected_at"], str)

            different_barrier = Barrier(2)
            different_request_ids = [uuid4(), uuid4()]
            with ThreadPoolExecutor(max_workers=2) as executor:
                different_results = list(
                    executor.map(
                        lambda request_id: race(
                            opportunity_id=opportunity_ids[1],
                            request_id=request_id,
                            barrier=different_barrier,
                        ),
                        different_request_ids,
                    )
                )
            assert sorted(result["outcome"] for result in different_results) == [
                "error",
                "ok",
            ]
            assert [
                result.get("code")
                for result in different_results
                if result["outcome"] == "error"
            ] == ["version_conflict"]

            with Session(app_engine) as session:
                session.connection().exec_driver_sql("SET LOCAL ROLE app")
                repeated = set_company_tracking(
                    session,
                    company_id=company_id,
                    opportunity_id=opportunity_ids[0],
                    status="계속 추적",
                    reason="app role의 기존 current 갱신",
                    expected_revision=1,
                    request_id=uuid4(),
                    selected_by="경합 담당자",
                )
                assert repeated.response.revision == 2
                assert repeated.response.reason == "app role의 기존 current 갱신"
                reset = set_company_tracking(
                    session,
                    company_id=company_id,
                    opportunity_id=opportunity_ids[0],
                    status="미선택",
                    reason="app role reset 감사 보존",
                    expected_revision=2,
                    request_id=uuid4(),
                    selected_by="경합 담당자",
                )
                assert reset.response.revision == 3
                assert reset.response.reason is None
                assert reset.response.selected_by is None
                assert reset.response.selected_at is None
                session.commit()

            with Session(owner_engine) as session:
                assert session.scalar(
                    select(func.count()).select_from(CompanyOpportunityTracking)
                ) == 2
                assert session.scalar(
                    select(func.count()).select_from(CompanyTrackingEvent)
                ) == 4
                assert session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.operation == "company_tracking.set")
                ) == 4
                current = session.get(
                    CompanyOpportunityTracking,
                    (company_id, opportunity_ids[0]),
                )
                assert current is not None
                assert (
                    current.tracking_status,
                    current.reason,
                    current.selected_by,
                    current.selected_at,
                    current.revision,
                ) == ("미선택", None, None, None, 3)
                events = session.scalars(
                    select(CompanyTrackingEvent)
                    .where(
                        CompanyTrackingEvent.company_id == company_id,
                        CompanyTrackingEvent.opportunity_id == opportunity_ids[0],
                    )
                    .order_by(CompanyTrackingEvent.revision)
                ).all()
                assert [(event.revision, event.reason) for event in events] == [
                    (1, "동시 최초 저장"),
                    (2, "app role의 기존 current 갱신"),
                    (3, "app role reset 감사 보존"),
                ]
        finally:
            app_engine.dispose()
            owner_engine.dispose()
            policy_engine.dispose()
