"""DEMO-01 STEP-001 company identity and PostgreSQL scope constraints."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.core.db import ALEMBIC_HEAD
from app.deep_review.models import DeepReview, PreSpecCompanyFitAttempt, ProfileVersion
from app.lifecycle.models import (
    Company,
    CompanyOpportunityTracking,
    CompanyTrackingEvent,
    Notice,
    Opportunity,
)
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database


pytestmark = requires_postgres
PREVIOUS_HEAD = "0033_assumption_analysis"
ROOT = Path(__file__).resolve().parents[4]


def _seed_dependencies(connection) -> dict[str, object]:  # type: ignore[no-untyped-def]
    notice_id = connection.scalar(
        text(
            "INSERT INTO bidops.notice (notice_key, source_type, title) "
            "VALUES (:key, 'pre_spec', '회사 문맥 제약 검사') RETURNING id"
        ),
        {"key": f"company-context:{uuid4()}"},
    )
    content_id = uuid4()
    document_id = uuid4()
    bundle_id = uuid4()
    policy_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO bidops.content_object "
            "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
            "VALUES (:id, :sha, 1, 'application/pdf', 'fixture', now())"
        ),
        {"id": content_id, "sha": uuid4().hex * 2},
    )
    connection.execute(
        text(
            "INSERT INTO bidops.document_version "
            "(id, notice_id, content_object_id, version, source_kind, original_filename, "
            " role, is_current, safety_status, needs_human_review, created_at) "
            "VALUES (:id, :notice_id, :content_id, 1, 'manual', 'fixture.pdf', "
            " '제안요청서', true, 'safe', false, now())"
        ),
        {"id": document_id, "notice_id": notice_id, "content_id": content_id},
    )
    connection.execute(
        text(
            "INSERT INTO bidops.document_bundle "
            "(id, notice_id, revision, version, status, issues_snapshot, created_at) "
            "VALUES (:id, :notice_id, 1, 1, 'ready', '[]'::jsonb, now())"
        ),
        {"id": bundle_id, "notice_id": notice_id},
    )
    connection.execute(
        text(
            "INSERT INTO bidops.analysis_policy_version "
            "(id, version, label, model_endpoint_ref, model_name, prompts, "
            " validation_rules, policy_sha256, created_at) "
            "VALUES (:id, 1, 'fixture', 'fixture', 'fixture', '{}'::jsonb, "
            " '{}'::jsonb, :sha, now())"
        ),
        {"id": policy_id, "sha": "f" * 64},
    )
    return {
        "notice_id": notice_id,
        "document_id": document_id,
        "bundle_id": bundle_id,
        "policy_id": policy_id,
    }


def _insert_profile(connection, *, version: int, company_id: UUID | None) -> UUID:  # type: ignore[no-untyped-def]
    profile_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO bidops.profile_version "
            "(id, company_id, version, label, profile_payload, profile_sha256, "
            " source_kind, created_at) "
            "VALUES (:id, :company_id, :version, :label, '{}'::jsonb, :sha, "
            " 'fixture', now())"
        ),
        {
            "id": profile_id,
            "company_id": company_id,
            "version": version,
            "label": f"profile-{version}",
            "sha": f"{version:x}" * 64,
        },
    )
    return profile_id


def _seed_company_lineage(
    connection,  # type: ignore[no-untyped-def]
    dependencies: dict[str, object],
) -> dict[str, object]:
    """DEMO-03 (0036) company-row dependencies: a completed overview and a fit policy."""

    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.deep_review.models import CompanyFitPolicyVersion, PrespecOverviewRun, WorkJob

    session = Session(bind=connection)
    job = WorkJob(id=uuid4(), job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add(job)
    session.flush()
    run = PrespecOverviewRun(
        id=uuid4(), notice_id=dependencies["notice_id"], document_version_id=dependencies["document_id"],
        work_job_id=job.id, status="completed", range_source="auto", range_reason_codes=[],
        policy_digest="0" * 64, model_name="fixture", warnings_json=[], reason_codes=[], call_count=1,
        raw_response_refs=[], result_json={}, checks_json={"overall": "passed"},
        completed_at=datetime.now(UTC),
    )
    policy = CompanyFitPolicyVersion(id=uuid4(), sha256=uuid4().hex * 2, payload={"fixture": True})
    session.add_all([run, policy])
    session.flush()
    session.close()
    return {**dependencies, "overview_run_id": run.id, "fit_policy_id": policy.id, "fit_policy_sha": policy.sha256}


def _insert_graph(connection, *, company_id: UUID, profile_id: UUID) -> UUID:  # type: ignore[no-untyped-def]
    """A company knowledge graph version bound to (company, profile) (0035/0036 scope)."""

    from sqlalchemy.orm import Session

    from app.deep_review.models import (
        CompanyKnowledgeSource,
        CompanyKnowledgeVersion,
        ContentObject,
        ContentObjectLocation,
        KnowledgeOntologyVersion,
    )

    session = Session(bind=connection)
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
    session.close()
    return graph.id


def _insert_review(
    connection,  # type: ignore[no-untyped-def]
    *,
    company_id: UUID | None,
    profile_id: UUID,
    dependencies: dict[str, object],
    graph_id: UUID | None = None,
) -> UUID:
    review_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO bidops.deep_review "
            "(id, company_id, notice_id, bundle_id, profile_version_id, "
            " policy_version_id, effective_grade_at_start, status, created_at, graph_version_id) "
            "VALUES (:id, :company_id, :notice_id, :bundle_id, :profile_id, "
            " :policy_id, '우선 검토', 'queued', now(), :graph_id)"
        ),
        {
            "id": review_id,
            "company_id": company_id,
            "profile_id": profile_id,
            "graph_id": graph_id,
            **{key: dependencies[key] for key in ("notice_id", "bundle_id", "policy_id")},
        },
    )
    return review_id


def _insert_company_fit(
    connection,  # type: ignore[no-untyped-def]
    *,
    company_id: UUID,
    profile_id: UUID,
    graph_id: UUID | None,
    dependencies: dict[str, object],
    digest_digit: str,
) -> UUID:
    """A DEMO-03 company fit row: company-fit policy FK, graph scope, frozen provenance."""

    attempt_id = uuid4()
    identity = {
        "purpose": "company_fit", "bundle_id": None, "company_id": str(company_id),
        "profile_version_id": str(profile_id),
        "graph_version_id": None if graph_id is None else str(graph_id),
        "overview_run_id": str(dependencies["overview_run_id"]),
        "policy_version_id": str(dependencies["fit_policy_id"]),
        "policy_sha256": dependencies["fit_policy_sha"], "model_name": "fixture", "model_revision": None,
    }
    input_payload = {
        **identity,
        "schema_version": "bidops.company-analysis-input.v1", "execution_nonce": str(attempt_id),
        "target_review_id": None, "notice_id": dependencies["notice_id"],
        "document_version_ids": [str(dependencies["document_id"])],
    }
    provenance = {**identity, "input_sha256": digest_digit * 64,
                  "documents": [{"document_version_id": str(dependencies["document_id"]), "source_sha256": "a" * 64}]}
    connection.execute(
        text(
            "INSERT INTO bidops.prespec_company_fit_attempt "
            "(id, company_id, notice_id, document_version_id, overview_run_id, "
            " profile_version_id, deep_policy_version_id, company_fit_policy_version_id, graph_version_id, "
            " input_jsonb, input_sha256, provenance_jsonb, "
            " policy_digest, model_name, model_revision, quality_status, status, created_at) "
            "VALUES (:id, :company_id, :notice_id, :document_id, :overview_run_id, :profile_id, "
            " NULL, :fit_policy_id, :graph_id, CAST(:input_payload AS jsonb), :input_sha256, "
            " CAST(:provenance AS jsonb), :fit_policy_sha, 'fixture', NULL, 'unmeasured_reference', "
            " 'queued', now())"
        ),
        {
            "id": attempt_id,
            "company_id": company_id,
            "profile_id": profile_id,
            "graph_id": graph_id,
            "input_payload": json.dumps(input_payload, ensure_ascii=False),
            "input_sha256": digest_digit * 64,
            "provenance": json.dumps(provenance, ensure_ascii=False),
            **{key: dependencies[key] for key in (
                "notice_id", "document_id", "overview_run_id", "fit_policy_id", "fit_policy_sha")},
        },
    )
    return attempt_id


def _insert_fit(
    connection,  # type: ignore[no-untyped-def]
    *,
    company_id: UUID | None,
    profile_id: UUID,
    dependencies: dict[str, object],
    digest_digit: str,
) -> UUID:
    attempt_id = uuid4()
    input_payload = {
        "schema_version": "bidops.prespec-company-fit-input.v1",
        "notice_id": str(dependencies["notice_id"]),
        "document_version_id": str(dependencies["document_id"]),
        "overview_id": None,
        "profile_version_id": str(profile_id),
        "deep_policy_version_id": str(dependencies["policy_id"]),
        "policy_digest": "a" * 64,
        "model_name": "fixture",
        "model_revision": "b" * 64,
        "quality_status": "unmeasured_reference",
    }
    connection.execute(
        text(
            "INSERT INTO bidops.prespec_company_fit_attempt "
            "(id, company_id, notice_id, document_version_id, overview_run_id, "
            " profile_version_id, deep_policy_version_id, input_jsonb, input_sha256, "
            " policy_digest, model_name, model_revision, quality_status, status, created_at) "
            "VALUES (:id, :company_id, :notice_id, :document_id, NULL, :profile_id, "
            " :policy_id, CAST(:input_payload AS jsonb), :input_sha256, :policy_digest, "
            " :model_name, :model_revision, :quality_status, 'queued', now())"
        ),
        {
            "id": attempt_id,
            "company_id": company_id,
            "profile_id": profile_id,
            "input_payload": json.dumps(input_payload, ensure_ascii=False),
            "input_sha256": digest_digit * 64,
            **input_payload,
            **dependencies,
        },
    )
    return attempt_id


def test_company_models_belong_to_lifecycle_and_sources_remain_shared() -> None:
    assert Company.__table__.fullname == "company"
    assert CompanyOpportunityTracking.__table__.fullname == "company_opportunity_tracking"
    assert CompanyTrackingEvent.__table__.fullname == "company_tracking_event"
    assert "company_id" not in Notice.__table__.columns
    assert "company_id" not in Opportunity.__table__.columns
    assert ProfileVersion.__table__.c.company_id.nullable
    assert DeepReview.__table__.c.company_id.nullable
    assert PreSpecCompanyFitAttempt.__table__.c.company_id.nullable


def test_company_context_migration_has_no_grants_and_runtime_head_matches() -> None:
    migration = (
        ROOT / "web/backend/alembic/versions/0034_company_context.py"
    ).read_text(encoding="utf-8")
    assert "GRANT " not in migration
    # DEMO-02(0035)·DEMO-03(0036)이 뒤에 쌓이므로 고정 문자열 대신 체인의 유일한
    # head가 런타임 상수와 같은지 확인한다.
    revisions: dict[str, str | None] = {}
    for path in (ROOT / "web/backend/alembic/versions").glob("[0-9]*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
        down = re.search(
            r"^down_revision\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", text, re.MULTILINE
        )
        assert revision is not None, path
        revisions[revision.group(1)] = down.group(1) if down and down.group(1) else None
    assert "0034_company_context" in revisions
    parents = {parent for parent in revisions.values() if parent}
    heads = sorted(set(revisions) - parents)
    assert heads == [ALEMBIC_HEAD], heads


def test_0034_preserves_existing_null_lineage_without_backfill() -> None:
    with temporary_database(upgrade_to=PREVIOUS_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        legacy_profile_id = uuid4()
        legacy_review_id = uuid4()
        legacy_fit_id = uuid4()
        with engine.begin() as connection:
            dependencies = _seed_dependencies(connection)
            connection.execute(
                text(
                    "INSERT INTO bidops.profile_version "
                    "(id, version, label, profile_payload, profile_sha256, source_kind, created_at) "
                    "VALUES (:id, 1, 'legacy', '{}'::jsonb, :sha, 'fixture', now())"
                ),
                {"id": legacy_profile_id, "sha": "c" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.deep_review "
                    "(id, notice_id, bundle_id, profile_version_id, policy_version_id, "
                    " effective_grade_at_start, status, created_at) "
                    "VALUES (:id, :notice_id, :bundle_id, :profile_id, :policy_id, "
                    " '우선 검토', 'queued', now())"
                ),
                {"id": legacy_review_id, "profile_id": legacy_profile_id, **dependencies},
            )
            input_payload = {
                "schema_version": "bidops.prespec-company-fit-input.v1",
                "notice_id": str(dependencies["notice_id"]),
                "document_version_id": str(dependencies["document_id"]),
                "overview_id": None,
                "profile_version_id": str(legacy_profile_id),
                "deep_policy_version_id": str(dependencies["policy_id"]),
                "policy_digest": "a" * 64,
                "model_name": "fixture",
                "model_revision": "b" * 64,
                "quality_status": "unmeasured_reference",
            }
            connection.execute(
                text(
                    "INSERT INTO bidops.prespec_company_fit_attempt "
                    "(id, notice_id, document_version_id, overview_run_id, profile_version_id, "
                    " deep_policy_version_id, input_jsonb, input_sha256, policy_digest, "
                    " model_name, model_revision, quality_status, status, created_at) "
                    "VALUES (:id, :notice_id, :document_id, NULL, :profile_id, :policy_id, "
                    " CAST(:input_payload AS jsonb), :input_sha256, :policy_digest, "
                    " :model_name, :model_revision, :quality_status, 'queued', now())"
                ),
                {
                    "id": legacy_fit_id,
                    "profile_id": legacy_profile_id,
                    "input_payload": json.dumps(input_payload, ensure_ascii=False),
                    "input_sha256": "d" * 64,
                    **input_payload,
                    **dependencies,
                },
            )

        upgraded = run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT company_id FROM bidops.profile_version WHERE id=:id"),
                {"id": legacy_profile_id},
            ) is None
            assert connection.scalar(
                text("SELECT company_id FROM bidops.deep_review WHERE id=:id"),
                {"id": legacy_review_id},
            ) is None
            assert connection.scalar(
                text(
                    "SELECT company_id FROM bidops.prespec_company_fit_attempt WHERE id=:id"
                ),
                {"id": legacy_fit_id},
            ) is None
        engine.dispose()


def test_0034_empty_downgrade_restores_the_previous_schema() -> None:
    with temporary_database() as database_url:
        from sqlalchemy import create_engine

        downgraded = run_alembic(database_url, "downgrade", PREVIOUS_HEAD)
        assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
        engine = create_engine(database_url, future=True)
        inspector = inspect(engine)
        assert not {
            "company",
            "company_opportunity_tracking",
            "company_tracking_event",
        } & set(inspector.get_table_names(schema="bidops"))
        for table in ("profile_version", "deep_review", "prespec_company_fit_attempt"):
            assert "company_id" not in {
                column["name"]
                for column in inspector.get_columns(table, schema="bidops")
            }
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM bidops.alembic_version")
            ) == PREVIOUS_HEAD
        engine.dispose()


@pytest.mark.parametrize(
    ("analysis_company", "profile_company", "allowed"),
    [
        pytest.param("a", "a", True, id="same-company"),
        pytest.param("a", "b", False, id="cross-company"),
        pytest.param("a", None, False, id="company-to-legacy"),
        pytest.param(None, "a", False, id="legacy-to-company"),
        pytest.param(None, None, True, id="legacy-null-lineage"),
    ],
)
def test_review_and_fit_profile_company_scope_is_database_enforced(
    analysis_company: str | None,
    profile_company: str | None,
    allowed: bool,
) -> None:
    with migrated_engine() as engine:
        company_ids = {"a": uuid4(), "b": uuid4()}
        with engine.begin() as connection:
            dependencies = _seed_dependencies(connection)
            connection.execute(
                text(
                    "INSERT INTO bidops.company (id, slug, name, is_fictional, created_at) "
                    "VALUES (:a, 'alpha-si', '알파 SI', true, now()), "
                    "(:b, 'beta-si', '베타 SI', true, now())"
                ),
                company_ids,
            )
            profile_id = _insert_profile(
                connection,
                version=1,
                company_id=company_ids.get(profile_company),
            )
            dependencies = _seed_company_lineage(connection, dependencies)
            # DEMO-03 (0036): a company row also pins the graph bound to its
            # profile; the graph belongs to the profile's company.
            graph_id = (
                _insert_graph(connection, company_id=company_ids[profile_company], profile_id=profile_id)
                if profile_company is not None
                else None
            )

        company_id = company_ids.get(analysis_company)

        def insert_fit(connection, digit: str) -> None:  # type: ignore[no-untyped-def]
            if company_id is None:
                _insert_fit(connection, company_id=None, profile_id=profile_id,
                            dependencies=dependencies, digest_digit=digit)
            else:
                _insert_company_fit(connection, company_id=company_id, profile_id=profile_id,
                                    graph_id=graph_id, dependencies=dependencies, digest_digit=digit)

        review_graph = graph_id if company_id is not None else None
        if allowed:
            with engine.begin() as connection:
                _insert_review(
                    connection,
                    company_id=company_id,
                    profile_id=profile_id,
                    dependencies=dependencies,
                    graph_id=review_graph,
                )
            with engine.begin() as connection:
                insert_fit(connection, "1")
        else:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    _insert_review(
                        connection,
                        company_id=company_id,
                        profile_id=profile_id,
                        dependencies=dependencies,
                        graph_id=review_graph,
                    )
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    insert_fit(connection, "2")


def test_profile_review_and_fit_company_scope_cannot_be_reassigned() -> None:
    with migrated_engine() as engine:
        company_id = uuid4()
        other_company_id = uuid4()
        with engine.begin() as connection:
            dependencies = _seed_dependencies(connection)
            connection.execute(
                text(
                    "INSERT INTO bidops.company (id, slug, name, is_fictional, created_at) "
                    "VALUES (:id, 'immutable-si', '불변 SI', true, now()), "
                    "(:other_id, 'other-si', '다른 SI', true, now())"
                ),
                {"id": company_id, "other_id": other_company_id},
            )
            profile_id = _insert_profile(
                connection, version=1, company_id=company_id
            )
            other_profile_id = _insert_profile(
                connection, version=2, company_id=other_company_id
            )
            legacy_profile_id = _insert_profile(
                connection, version=3, company_id=None
            )
            dependencies = _seed_company_lineage(connection, dependencies)
            graph_id = _insert_graph(connection, company_id=company_id, profile_id=profile_id)
            review_id = _insert_review(
                connection,
                company_id=company_id,
                profile_id=profile_id,
                dependencies=dependencies,
                graph_id=graph_id,
            )
            fit_id = _insert_company_fit(
                connection,
                company_id=company_id,
                profile_id=profile_id,
                graph_id=graph_id,
                dependencies=dependencies,
                digest_digit="3",
            )

        changes = (
            (
                "UPDATE bidops.profile_version SET company_id=:company_id WHERE id=:id",
                {"id": legacy_profile_id, "company_id": company_id},
            ),
            (
                "UPDATE bidops.deep_review SET company_id=:company_id, "
                "profile_version_id=:profile_id WHERE id=:id",
                {
                    "id": review_id,
                    "company_id": other_company_id,
                    "profile_id": other_profile_id,
                },
            ),
            (
                "UPDATE bidops.prespec_company_fit_attempt SET company_id=:company_id, "
                "profile_version_id=:profile_id WHERE id=:id",
                {
                    "id": fit_id,
                    "company_id": other_company_id,
                    "profile_id": other_profile_id,
                },
            ),
        )
        for statement, params in changes:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(statement), params)


def test_company_tracking_schema_enforces_revision_metadata_and_append_only_events() -> None:
    with migrated_engine() as engine:
        company_id = uuid4()
        event_id = uuid4()
        with engine.begin() as connection:
            opportunity_id = connection.scalar(
                text(
                    "INSERT INTO bidops.opportunity (first_registered_stage, created_at) "
                    "VALUES ('pre_spec', now()) RETURNING id"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.company (id, slug, name, is_fictional, created_at) "
                    "VALUES (:id, 'tracking-si', '추적 SI', true, now())"
                ),
                {"id": company_id},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.company_opportunity_tracking "
                    "(company_id, opportunity_id, tracking_status, reason, selected_by, "
                    " selected_at, revision) "
                    "VALUES (:company_id, :opportunity_id, '계속 추적', '검토 계속', "
                    " '담당자', now(), 1)"
                ),
                {"company_id": company_id, "opportunity_id": opportunity_id},
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.company_tracking_event "
                    "(id, company_id, opportunity_id, revision, previous_status, new_status, "
                    " reason, actor, request_id, created_at) "
                    "VALUES (:id, :company_id, :opportunity_id, 1, '미선택', '계속 추적', "
                    " '검토 계속', '담당자', :request_id, now())"
                ),
                {
                    "id": event_id,
                    "company_id": company_id,
                    "opportunity_id": opportunity_id,
                    "request_id": uuid4(),
                },
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.company_tracking_event SET reason='변경' WHERE id=:id"
                    ),
                    {"id": event_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                second_opportunity_id = connection.scalar(
                    text(
                        "INSERT INTO bidops.opportunity "
                        "(first_registered_stage, created_at) "
                        "VALUES ('pre_spec', now()) RETURNING id"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO bidops.company_opportunity_tracking "
                        "(company_id, opportunity_id, tracking_status, reason, selected_by, "
                        " selected_at, revision) "
                        "VALUES (:company_id, :opportunity_id, '미선택', '남은 사유', "
                        " NULL, NULL, 1)"
                    ),
                    {
                        "company_id": company_id,
                        "opportunity_id": second_opportunity_id,
                    },
                )


def test_company_context_tables_and_columns_exist_at_the_single_head() -> None:
    with migrated_engine() as engine:
        inspector = inspect(engine)
        assert {
            "company",
            "company_opportunity_tracking",
            "company_tracking_event",
        } <= set(inspector.get_table_names(schema="bidops"))
        assert "company_id" not in {
            column["name"] for column in inspector.get_columns("notice", schema="bidops")
        }
        assert "company_id" not in {
            column["name"] for column in inspector.get_columns("opportunity", schema="bidops")
        }
        for table in ("profile_version", "deep_review", "prespec_company_fit_attempt"):
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table, schema="bidops")
            }
            assert columns["company_id"]["nullable"] is True
        fit_uniques = {
            constraint["name"]: constraint["column_names"]
            for constraint in inspector.get_unique_constraints(
                "prespec_company_fit_attempt", schema="bidops"
            )
        }
        assert fit_uniques["uq_prespec_company_fit_input"] == ["input_sha256"]
        review_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("deep_review", schema="bidops")
        }
        assert review_indexes["uq_deep_review_legacy_inputs"]["unique"]
        assert review_indexes["uq_deep_review_company_inputs"]["unique"]
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM bidops.alembic_version")
            ) == ALEMBIC_HEAD
