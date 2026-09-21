"""PostgreSQL contract for the additive preliminary-assessment migration."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.postgres import requires_postgres, run_alembic, temporary_database


pytestmark = requires_postgres

BASE = "0030_prespec_review_exclusion"
HEAD = "0031_prespec_preliminary_assessment"
NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _seed_v1_run(engine) -> object:
    content_id = uuid4()
    document_id = uuid4()
    run_id = uuid4()
    job_id = uuid4()
    with engine.begin() as connection:
        notice_id = connection.scalar(text(
            "INSERT INTO bidops.notice (notice_key, source_type) "
            "VALUES (:key, 'pre_spec') RETURNING id"
        ), {"key": f"preliminary-migration:{uuid4()}"})
        connection.execute(text(
            "INSERT INTO bidops.content_object "
            "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
            "VALUES (:id, :sha, 1, 'application/pdf', 'document-source', :created_at)"
        ), {"id": content_id, "sha": "a" * 64, "created_at": NOW})
        connection.execute(text(
            "INSERT INTO bidops.document_version "
            "(id, notice_id, content_object_id, version, source_kind, original_filename, "
            "role, is_current, safety_status, needs_human_review, created_at) "
            "VALUES (:id, :notice_id, :content_id, 1, 'manual', 'old.pdf', "
            "'제안요청서', true, 'safe', false, :created_at)"
        ), {
            "id": document_id, "notice_id": notice_id,
            "content_id": content_id, "created_at": NOW,
        })
        connection.execute(text(
            "INSERT INTO bidops.work_job "
            "(id, job_type, aggregate_type, aggregate_id, status, priority, lease_fence, "
            "attempt_count, max_attempts, scheduled_at, created_at) "
            "VALUES (:id, 'prespec_overview', 'prespec_overview_run', :aggregate_id, "
            "'completed', 0, 0, 1, 3, :created_at, :created_at)"
        ), {"id": job_id, "aggregate_id": run_id, "created_at": NOW})
        connection.execute(text(
            "INSERT INTO bidops.prespec_overview_run "
            "(id, notice_id, document_version_id, work_job_id, status, range_source, "
            "range_reason_codes, policy_digest, model_name, warnings_json, reason_codes, "
            "call_count, raw_response_refs, created_at) "
            "VALUES (:id, :notice_id, :document_id, :job_id, 'needs_human_review', 'auto', "
            "'[]'::jsonb, :policy_digest, 'old-model', '[]'::jsonb, '[]'::jsonb, "
            "1, '[]'::jsonb, :created_at)"
        ), {
            "id": run_id, "notice_id": notice_id, "document_id": document_id,
            "job_id": job_id, "policy_digest": "b" * 64, "created_at": NOW,
        })
    return run_id


def test_0031_preserves_v1_rows_and_enforces_new_bindings() -> None:
    with temporary_database(upgrade_to=BASE) as database_url:
        engine = create_engine(database_url, future=True)
        try:
            run_id = _seed_v1_run(engine)
            upgraded = run_alembic(database_url, "upgrade", HEAD)
            assert upgraded.returncode == 0, upgraded.stderr

            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT contract_version, profile_status, profile_facts_json, "
                    "assessment_status, assessment_grade, semantic_status, semantic_scope_json "
                    "FROM bidops.prespec_overview_run WHERE id = :id"
                ), {"id": run_id}).mappings().one()
            assert dict(row) == {
                "contract_version": "overview-v1",
                "profile_status": "not_configured",
                "profile_facts_json": [],
                "assessment_status": "none",
                "assessment_grade": None,
                "semantic_status": "not_run",
                "semantic_scope_json": [],
            }

            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text(
                        "UPDATE bidops.prespec_overview_run SET assessment_status='graded' "
                        "WHERE id=:id"
                    ), {"id": run_id})
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text(
                        "UPDATE bidops.prespec_overview_run SET input_binding_sha256='bad' "
                        "WHERE id=:id"
                    ), {"id": run_id})
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text(
                        "UPDATE bidops.prespec_overview_run SET reused_from_run_id=:missing "
                        "WHERE id=:id"
                    ), {"id": run_id, "missing": uuid4()})

            # Reapplying the target is a no-op and does not replace the old row.
            reapplied = run_alembic(database_url, "upgrade", HEAD)
            assert reapplied.returncode == 0, reapplied.stderr
            with engine.connect() as connection:
                assert connection.scalar(text(
                    "SELECT count(*) FROM bidops.prespec_overview_run WHERE id=:id"
                ), {"id": run_id}) == 1

            downgraded = run_alembic(database_url, "downgrade", BASE)
            assert downgraded.returncode != 0
            assert "preliminary assessment history must be preserved" in downgraded.stderr
            with engine.connect() as connection:
                assert connection.scalar(text(
                    "SELECT version_num FROM bidops.alembic_version"
                )) == HEAD
        finally:
            engine.dispose()
