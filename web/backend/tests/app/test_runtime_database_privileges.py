"""Runtime PostgreSQL role allow/deny contract.

The static checks run everywhere.  The role smoke test uses the disposable
PostgreSQL server provided by ``web/run-web-tests.sh`` and proves effective
privileges rather than trusting the grant text alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.db import schema_bound
from app.lifecycle import ingest_run
from app.lifecycle.models import Run
from app.screening.models import OrderPlanScreeningExecution
from tests.postgres import maintenance_url, requires_postgres, temporary_database


ROOT = Path(__file__).resolve().parents[4]
MIGRATE = (ROOT / "scripts/migrate.sh").read_text(encoding="utf-8")
POLICY_PATH = ROOT / "scripts/runtime-privileges.sql"
POLICY = POLICY_PATH.read_text(encoding="utf-8")


def _table_grants(role: str, privilege: str) -> set[str]:
    pattern = re.compile(
        rf"GRANT\s+{privilege}\s+ON\s+TABLE\s+([^;]*?)\s+TO\s+{role};",
        re.DOTALL,
    )
    return {
        table.removeprefix("bidops.")
        for match in pattern.finditer(POLICY)
        for table in (part.strip() for part in match.group(1).split(","))
    }


def _column_update_grant(role: str, table: str) -> set[str]:
    match = re.search(
        rf"GRANT\s+UPDATE\s*\(([^)]*)\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
        POLICY,
    )
    assert match is not None
    return {column.strip() for column in match.group(1).split(",")}


def test_migrate_uses_a_separate_fail_closed_privilege_policy() -> None:
    assert "runtime-privileges.sql" in MIGRATE
    assert "SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in MIGRATE
    assert "SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in POLICY
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in POLICY
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops REVOKE ALL" in POLICY
    default_grants = [
        line
        for line in POLICY.splitlines()
        if line.startswith("ALTER DEFAULT PRIVILEGES") and " GRANT " in line
    ]
    assert default_grants == [
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON SEQUENCES TO ro_backup;",
    ]


def test_sensitive_rows_are_not_in_broad_update_or_delete_groups() -> None:
    broad_mutation_section = POLICY.split(
        "-- Service-owned mutable state.", 1
    )[1].split("-- Deletes are limited", 1)[0]
    delete_section = POLICY.split("-- Deletes are limited", 1)[1].split(
        "-- Current integer identity", 1
    )[0]
    for table in (
        "notice_observation",
        "order_plan_observation",
        "profile_version",
        "profile_evidence",
        "analysis_policy_version",
        "company_profile_snapshot",
        "review",
        "judgment_revision",
        "review_revision",
        "quality_gate_review",
        "report_revision",
        "report_revision_evidence",
        "final_opinion",
        "audit_event",
        "screening_audit_event",
        "prespec_v4_pdf_snapshot",
    ):
        assert f"bidops.{table}" not in broad_mutation_section
        assert f"bidops.{table}" not in delete_section


def test_prespec_overview_run_grants_match_reviewed_runtime_paths() -> None:
    """개요 run은 두 runtime role이 읽고 쓴다. enqueue는 app, 실행은 worker다."""

    for role in ("app", "worker"):
        assert "prespec_overview_run" in _table_grants(role, "SELECT")
        assert "prespec_overview_run" in _table_grants(role, "INSERT")
        assert "prespec_overview_run" in _table_grants(role, "UPDATE")
        assert "prespec_overview_run" not in _table_grants(role, "DELETE")


def test_overview_worker_update_stays_column_scoped_for_source_rows() -> None:
    """Guard the worker grant against a future table-wide UPDATE expansion."""

    worker_updates = _table_grants("worker", "UPDATE")
    assert _column_update_grant("worker", "notice") == {"id"}
    assert _column_update_grant("worker", "attachment") == {"extract_status"}
    assert _column_update_grant("worker", "document_version") == {"is_current"}
    assert not {"notice", "attachment", "document_version"} & worker_updates
    # 준비 스냅샷은 append-only다. 어느 role도 UPDATE·DELETE를 갖지 않는다.
    for role in ("app", "worker"):
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "UPDATE")
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "DELETE")


def test_document_segment_grants_are_append_only_for_both_runtime_roles() -> None:
    """결정적 segment 저장소는 두 runtime role 모두 insert·select만 갖는다."""

    segment_tables = {
        "document_segment_manifest",
        "document_segment",
        "requirement_inventory_item",
    }
    for role in ("app", "worker"):
        assert segment_tables <= _table_grants(role, "SELECT")
        assert segment_tables <= _table_grants(role, "INSERT")
        assert not segment_tables & _table_grants(role, "UPDATE")
        assert not segment_tables & _table_grants(role, "DELETE")
        for table in sorted(segment_tables):
            assert (
                re.search(
                    rf"GRANT\s+UPDATE\s*\([^)]*\)\s+ON\s+bidops\.{table}\s+TO\s+{role};",
                    POLICY,
                )
                is None
            )


def test_c2_runtime_grants_are_role_specific_and_column_scoped() -> None:
    app_selects = _table_grants("app", "SELECT")
    app_inserts = _table_grants("app", "INSERT")
    app_deletes = _table_grants("app", "DELETE")
    worker_selects = _table_grants("worker", "SELECT")
    worker_inserts = _table_grants("worker", "INSERT")
    worker_deletes = _table_grants("worker", "DELETE")

    assert {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } <= app_selects
    assert {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } <= app_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } & app_deletes

    assert {
        "order_plan",
        "order_plan_observation",
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_artifact",
    } <= worker_selects
    assert {
        "order_plan_screening_batch_attempt",
        "order_plan_screening_artifact",
        "order_plan_screening_result",
    } <= worker_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_feedback",
    } & worker_inserts
    assert not {
        "order_plan_screening_policy",
        "order_plan_screening_execution",
        "order_plan_screening_batch_attempt",
        "order_plan_screening_result",
        "order_plan_screening_artifact",
        "order_plan_screening_feedback",
    } & worker_deletes

    assert _column_update_grant("app", "order_plan_screening_policy") == {
        "policy_status", "active_slot", "activated_at", "activated_by"
    }
    assert _column_update_grant("app", "order_plan_screening_execution") == {
        "status", "active_slot", "partial_artifact", "candidate_count",
        "completed_count", "failure_count", "stage1_selected_count",
        "stage1_filtered_out_count", "stage1_failed_count", "stage2_relevant_count",
        "stage2_not_relevant_count", "stage2_uncertain_count", "stage2_failed_count",
        "stage2_rejected_count", "human_review_count", "error_code",
        "started_at", "finished_at",
    }
    assert _column_update_grant("worker", "order_plan_screening_batch_attempt") == {
        "attempt_status", "failure_type", "failure_code", "response_object_ref",
        "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens",
        "duration_ms", "started_at", "finished_at",
    }
    assert _column_update_grant("worker", "order_plan_screening_execution") == {
        "status", "active_slot", "partial_artifact", "candidate_count",
        "completed_count", "failure_count", "stage1_selected_count",
        "stage1_filtered_out_count", "stage1_failed_count", "stage2_relevant_count",
        "stage2_not_relevant_count", "stage2_uncertain_count", "stage2_failed_count",
        "stage2_rejected_count", "human_review_count", "error_code",
        "started_at", "finished_at", "heartbeat_at",
    }



@pytest.fixture(autouse=True)
def _screening_registered(screening_extensions):
    """C-2 전용 디렉터리 인식과 적재는 screening hook이 등록돼 있을 때만 일어난다(명세 §6.2)."""


def _ensure_roles() -> None:
    url = maintenance_url()
    assert url is not None
    admin = create_engine(url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as connection:
            for role in ("app", "worker", "ro_backup"):
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                    {"role": role},
                )
                if exists is None:
                    connection.exec_driver_sql(f'CREATE ROLE "{role}"')
    finally:
        admin.dispose()


def _apply_policy(database_url: str):  # type: ignore[no-untyped-def]
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        cursor = connection.connection.driver_connection.cursor()
        try:
            # Exercise the same atomic multi-statement file that psql runs.
            cursor.execute(POLICY, prepare=False)
        finally:
            cursor.close()
    return engine


def _table_privilege(connection, role: str, table: str, privilege: str) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.scalar(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": role, "table": f"bidops.{table}", "privilege": privilege},
        )
    )


def _column_privilege(
    connection, role: str, table: str, column: str, privilege: str  # type: ignore[no-untyped-def]
) -> bool:
    return bool(
        connection.scalar(
            text(
                "SELECT has_column_privilege(:role, :table, :column, :privilege)"
            ),
            {
                "role": role,
                "table": f"bidops.{table}",
                "column": column,
                "privilege": privilege,
            },
        )
    )


@requires_postgres
def test_backup_reads_existing_and_future_sequences_without_mutation() -> None:
    from sqlalchemy.exc import DBAPIError

    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("CREATE SEQUENCE bidops.future_backup_probe START 41")
                sequences = conn.execute(text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='bidops' AND c.relkind='S' ORDER BY c.relname"
                )).scalars().all()
                assert "notice_id_seq" in sequences
                assert "future_backup_probe" in sequences
                for name in sequences:
                    privileges = conn.execute(text(
                        "SELECT has_sequence_privilege('ro_backup', :sequence, 'SELECT'), "
                        "has_sequence_privilege('ro_backup', :sequence, 'USAGE'), "
                        "has_sequence_privilege('ro_backup', :sequence, 'UPDATE')"
                    ), {"sequence": f"bidops.{name}"}).one()
                    assert privileges == (True, False, False)
                conn.exec_driver_sql("SET LOCAL ROLE ro_backup")
                for name in sequences:
                    assert conn.exec_driver_sql(
                        f'SELECT last_value, is_called FROM bidops."{name}"'
                    ).one() is not None
            for name in ("notice_id_seq", "future_backup_probe"):
                for operation in ("nextval(:sequence)", "setval(:sequence, 99)"):
                    with pytest.raises(DBAPIError) as error, engine.begin() as conn:
                        conn.exec_driver_sql("SET LOCAL ROLE ro_backup")
                        conn.execute(text(f"SELECT {operation}"), {"sequence": f"bidops.{name}"})
                    assert error.value.orig.sqlstate == "42501"
            with engine.begin() as conn:
                assert conn.exec_driver_sql(
                    "SELECT last_value, is_called FROM bidops.future_backup_probe"
                ).one() == (41, False)
                for role in ("app", "worker"):
                    assert conn.scalar(text(
                        "SELECT has_sequence_privilege(:role, 'bidops.future_backup_probe', 'USAGE,SELECT,UPDATE')"
                    ), {"role": role}) is False
        finally:
            engine.dispose()


@requires_postgres
def test_claim_ledger_effective_roles_and_app_stop() -> None:
    from sqlalchemy.exc import DBAPIError
    from tests.deep_review.test_overview_claim_ledger_postgres import (
        _dispatch, _finish, _response, _seed_attempt, _start, _verification,
    )

    _ensure_roles()
    with temporary_database() as database_url:
        engine = schema_bound(_apply_policy(database_url))
        try:
            attempt = _seed_attempt(engine)
            # App may pin/enqueue but cannot claim, rewrite an activation, or
            # gain machine-record INSERT through a table-wide grant.
            for statement in (
                "UPDATE bidops.prespec_v4_attempt SET status='failed',completed_at=now() WHERE id=:id",
                "UPDATE bidops.prespec_v4_attempt SET activation_id=NULL WHERE id=:id",
                "INSERT INTO bidops.prespec_overview_call_event DEFAULT VALUES",
                "INSERT INTO bidops.prespec_overview_verification DEFAULT VALUES",
            ):
                with pytest.raises(DBAPIError), engine.begin() as conn:
                    conn.execute(text("SET LOCAL ROLE app"))
                    conn.execute(text(statement), {"id": attempt})
            _start(engine, attempt)
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL ROLE worker"))
                call = _dispatch(session, attempt)
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL ROLE app"))
                conn.execute(text("UPDATE bidops.prespec_v4_attempt SET status='cancelled',completed_at=now(),error_code='v4_disabled',lease_owner=NULL,lease_expires_at=NULL WHERE id=:id"), {"id": attempt})
                conn.execute(text("UPDATE bidops.work_job SET status='cancelled',completed_at=now(),last_error_code='v4_disabled',lease_owner=NULL,lease_expires_at=NULL WHERE id=(SELECT work_job_id FROM bidops.prespec_v4_attempt WHERE id=:id)"), {"id": attempt})
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL ROLE worker"))
                _response(session, attempt, call)
            for role in ("app", "worker", "ro_backup"):
                with engine.begin() as conn:
                    conn.execute(text(f"SET LOCAL ROLE {role}"))
                    assert conn.scalar(text("SELECT count(*) FROM bidops.prespec_overview_call_event")) == 2
                    assert conn.scalar(text("SELECT count(*) FROM bidops.prespec_overview_verification")) == 0
                for table in ("prespec_overview_call_event", "prespec_overview_verification"):
                    for operation in (f"DELETE FROM bidops.{table}", f"UPDATE bidops.{table} SET created_at=created_at"):
                        with pytest.raises(DBAPIError), engine.begin() as conn:
                            conn.execute(text(f"SET LOCAL ROLE {role}"))
                            conn.execute(text(operation))
            human_review = _seed_attempt(engine)
            _start(engine, human_review)
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL ROLE worker"))
                _verification(session, human_review, passed=False)
                _finish(session, human_review, "needs_human_review")
        finally:
            engine.dispose()


@requires_postgres
def test_effective_runtime_role_matrix_and_future_defaults() -> None:
    _ensure_roles()
    with temporary_database() as database_url:
        engine = _apply_policy(database_url)
        try:
            with engine.begin() as connection:
                # App can create human and append-only history rows, but broad
                # mutation of those rows is absent.
                for table in (
                    "review",
                    "judgment_revision",
                    "review_revision",
                    "quality_gate_review",
                    "report_revision",
                    "final_opinion",
                    "audit_event",
                    "screening_audit_event",
                ):
                    assert _table_privilege(connection, "app", table, "INSERT")
                assert not _table_privilege(connection, "app", "review", "UPDATE")
                assert _column_privilege(
                    connection, "app", "review", "disposition", "UPDATE"
                )
                assert not _table_privilege(
                    connection, "app", "quality_gate_review", "UPDATE"
                )
                assert _column_privilege(
                    connection,
                    "app",
                    "quality_gate_review",
                    "evidence_judgment",
                    "UPDATE",
                )
                assert not _table_privilege(
                    connection, "app", "screening_policy", "UPDATE"
                )
                assert _column_privilege(
                    connection, "app", "screening_policy", "status", "UPDATE"
                )
                assert _column_privilege(
                    connection, "app", "notice", "title", "UPDATE"
                )
                for table, column in (("notice", "id"), ("attachment", "extract_status"), ("document_version", "is_current")):
                    assert _column_privilege(connection, "worker", table, column, "UPDATE")
                    assert not _table_privilege(connection, "worker", table, "UPDATE")
                for table, column in (("notice", "title"), ("attachment", "source_url"), ("document_version", "source_url")):
                    assert not _column_privilege(connection, "worker", table, column, "UPDATE")
                for table in (
                    "prespec_overview_review",
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                ):
                    assert _table_privilege(connection, "app", table, "SELECT")
                for table in (
                    "prespec_overview_review",
                    "prespec_overview_snapshot",
                ):
                    assert _table_privilege(connection, "app", table, "INSERT")
                assert not _table_privilege(
                    connection, "app", "prespec_overview_attempt", "INSERT"
                )
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert _table_privilege(connection, "app", table, "SELECT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert _table_privilege(connection, "app", table, "INSERT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "app", table, "DELETE")
                assert not _table_privilege(
                    connection, "app", "prespec_overview_review", "UPDATE"
                )
                for column in (
                    "current_snapshot_id",
                    "status",
                    "result",
                    "completed_at",
                    "updated_at",
                ):
                    assert _column_privilege(
                        connection,
                        "app",
                        "prespec_overview_review",
                        column,
                        "UPDATE",
                    )
                assert not _column_privilege(
                    connection,
                    "app",
                    "prespec_overview_review",
                    "notice_id",
                    "UPDATE",
                )
                for table in (
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                for table in (
                    "prespec_overview_review",
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert not _table_privilege(connection, "app", table, "DELETE")
                for table in (
                    "notice_observation",
                    "judgment_revision",
                    "review_revision",
                    "profile_version",
                    "company_profile_snapshot",
                    "report_revision",
                    "final_opinion",
                    "audit_event",
                ):
                    assert not _table_privilege(connection, "app", table, "UPDATE")
                    assert not _table_privilege(connection, "app", table, "DELETE")

                # Worker writes only queue/stage/artifact results.  Its audit
                # and report history writes are append-only.
                for table in (
                    "attachment_fetch",
                    "deep_review",
                    "deep_review_attempt",
                    "deep_review_stage",
                    "work_job",
                ):
                    assert _table_privilege(connection, "worker", table, "UPDATE")
                for table in (
                    "content_object",
                    "document_structure",
                    "document_block",
                    "claim",
                    "evidence_ref",
                    "report_revision",
                    "validation_run",
                    "validation_check",
                    "audit_event",
                ):
                    assert _table_privilege(connection, "worker", table, "INSERT")
                assert not _table_privilege(
                    connection, "worker", "document_version", "UPDATE"
                )
                assert _column_privilege(
                    connection, "worker", "document_version", "is_current", "UPDATE"
                )
                for table in (
                    "prespec_overview_review",
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                for table in (
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert _table_privilege(connection, "worker", table, "INSERT")
                for table in (
                    "order_plan",
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_artifact",
                ):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                for table in (
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_artifact",
                    "order_plan_screening_result",
                ):
                    assert _table_privilege(connection, "worker", table, "INSERT")
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "worker", table, "INSERT")
                assert not _table_privilege(
                    connection, "worker", "order_plan_screening_feedback", "SELECT"
                )
                for table in (
                    "order_plan_screening_policy",
                    "order_plan_screening_execution",
                    "order_plan_screening_batch_attempt",
                    "order_plan_screening_result",
                    "order_plan_screening_artifact",
                    "order_plan_screening_feedback",
                ):
                    assert not _table_privilege(connection, "worker", table, "DELETE")
                assert not _table_privilege(
                    connection, "worker", "prespec_overview_review", "UPDATE"
                )
                for column in (
                    "current_snapshot_id",
                    "status",
                    "result",
                    "completed_at",
                    "updated_at",
                ):
                    assert _column_privilege(
                        connection,
                        "worker",
                        "prespec_overview_review",
                        column,
                        "UPDATE",
                    )
                for column in (
                    "status",
                    "started_at",
                    "completed_at",
                    "result_id",
                    "lease_owner",
                    "lease_expires_at",
                ):
                    assert _column_privilege(
                        connection,
                        "worker",
                        "prespec_overview_attempt",
                        column,
                        "UPDATE",
                    )
                for column in (
                    "review_id",
                    "snapshot_id",
                    "input_sha256",
                    "provider",
                    "model_name",
                    "model_digest",
                    "prompt_version",
                    "binding_digest",
                ):
                    assert not _column_privilege(
                        connection,
                        "worker",
                        "prespec_overview_attempt",
                        column,
                        "UPDATE",
                    )
                assert not _column_privilege(
                    connection,
                    "worker",
                    "prespec_overview_review",
                    "notice_id",
                    "UPDATE",
                )
                for table in (
                    "document_segment_manifest",
                    "document_segment",
                    "requirement_inventory_item",
                ):
                    for role in ("app", "worker"):
                        assert _table_privilege(connection, role, table, "SELECT")
                        assert _table_privilege(connection, role, table, "INSERT")
                        assert not _table_privilege(connection, role, table, "UPDATE")
                        assert not _table_privilege(connection, role, table, "DELETE")
                for table in (
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert not _table_privilege(
                        connection, "worker", table, "UPDATE"
                    )
                for table in (
                    "prespec_overview_review",
                    "prespec_overview_snapshot",
                    "prespec_overview_attempt",
                    "prespec_overview_result",
                    "prespec_overview_attempt_event",
                ):
                    assert not _table_privilege(connection, "worker", table, "DELETE")
                for table in (
                    "review",
                    "judgment_revision",
                    "review_revision",
                    "quality_gate_review",
                    "final_opinion",
                    "screening_policy",
                    "analysis_policy_version",
                    "profile_version",
                    "company_profile_snapshot",
                    "notice",
                    "notice_observation",
                ):
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(
                            connection, "worker", table, privilege
                        )
                for table in ("judgment", "judgment_revision", "review", "review_revision"):
                    assert _table_privilege(connection, "worker", table, "SELECT")
                assert _table_privilege(connection, "app", "prespec_v4_attempt", "INSERT")
                assert not _table_privilege(connection, "worker", "prespec_v4_attempt", "INSERT")
                for table in (
                    "report_revision",
                    "audit_event",
                    "screening_audit_event",
                ):
                    assert not _table_privilege(
                        connection, "worker", table, "UPDATE"
                    )
                    assert not _table_privilege(
                        connection, "worker", table, "DELETE"
                    )
                worker_deletes = connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.role_table_grants "
                        "WHERE grantee = 'worker' AND table_schema = 'bidops' "
                        "AND privilege_type = 'DELETE'"
                    )
                )
                assert worker_deletes == 0

                # Policy defaults are fail closed for runtime roles and
                # read-only for backup when a future migration adds a table.
                connection.exec_driver_sql(
                    "CREATE TABLE bidops.future_privilege_probe (id integer)"
                )
                for role in ("app", "worker"):
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        assert not _table_privilege(
                            connection, role, "future_privilege_probe", privilege
                        )
                assert _table_privilege(
                    connection, "ro_backup", "future_privilege_probe", "SELECT"
                )
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    assert not _table_privilege(
                        connection, "ro_backup", "future_privilege_probe", privilege
                    )
        finally:
            engine.dispose()


@requires_postgres
def test_c2_ingest_completes_with_the_app_runtime_role(tmp_path) -> None:
    """The credential used by the ingest path can append the complete C-2 set."""

    from tests.c2_fixtures import write_c2_fixture as _write_c2_fixture

    _ensure_roles()
    with temporary_database() as database_url:
        owner_engine = schema_bound(create_engine(database_url, future=True))
        policy_engine = _apply_policy(database_url)
        try:
            run_dir, source_run_id = _write_c2_fixture(tmp_path)
            with Session(owner_engine) as session:
                session.add(
                    Run(
                        id=source_run_id,
                        timezone="Asia/Seoul",
                        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    )
                )
                session.commit()

            app_engine = schema_bound(create_engine(database_url, future=True))
            try:
                with Session(app_engine) as session:
                    session.connection().exec_driver_sql("SET ROLE app")
                    result = ingest_run(run_dir, session)
                assert result.screening_executions == 1
                assert result.screening_attempts == 1
                assert result.screening_results == 1
                assert result.screening_artifacts == 6
            finally:
                app_engine.dispose()

            with Session(owner_engine) as session:
                assert session.scalar(
                    select(func.count()).select_from(OrderPlanScreeningExecution)
                ) == 1
        finally:
            policy_engine.dispose()
            owner_engine.dispose()


def test_company_fit_runtime_privileges():
    assert "prespec_company_fit_attempt" in _table_grants("app", "SELECT")
    assert "prespec_company_fit_attempt" not in _table_grants("app", "INSERT")
    assert "prespec_company_fit_attempt" in _table_grants("worker", "SELECT")
    assert "prespec_company_fit_attempt" in _table_grants("worker", "INSERT")
    for role in ("app", "worker"):
        assert "prespec_company_fit_attempt" not in _table_grants(role, "UPDATE")
        assert "prespec_company_fit_attempt" not in _table_grants(role, "DELETE")


def test_v4_snapshot_runtime_privileges():
    assert "prespec_v4_pdf_snapshot" in _table_grants("app", "SELECT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("worker", "SELECT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("app", "INSERT")
    assert "prespec_v4_pdf_snapshot" in _table_grants("worker", "INSERT")
    for role in ("app", "worker"):
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "UPDATE")
        assert "prespec_v4_pdf_snapshot" not in _table_grants(role, "DELETE")
