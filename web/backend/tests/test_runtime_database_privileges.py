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
from app.models import OrderPlanScreeningExecution, Run
from tests.postgres import maintenance_url, requires_postgres, temporary_database


ROOT = Path(__file__).resolve().parents[3]
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
        "ALTER DEFAULT PRIVILEGES IN SCHEMA bidops GRANT SELECT ON TABLES TO ro_backup;"
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
        "prespec_overview_review",
        "prespec_overview_snapshot",
        "prespec_overview_attempt",
        "prespec_overview_result",
        "prespec_overview_attempt_event",
    ):
        assert f"bidops.{table}" not in broad_mutation_section
        assert f"bidops.{table}" not in delete_section


def test_prespec_overview_grants_match_reviewed_runtime_paths() -> None:
    app_selects = _table_grants("app", "SELECT")
    worker_selects = _table_grants("worker", "SELECT")
    app_inserts = _table_grants("app", "INSERT")
    worker_inserts = _table_grants("worker", "INSERT")
    assert {
        "prespec_overview_review",
        "prespec_overview_snapshot",
        "prespec_overview_attempt",
        "prespec_overview_result",
    } <= app_selects
    assert {
        "prespec_overview_review",
        "prespec_overview_snapshot",
        "prespec_overview_attempt",
        "prespec_overview_result",
        "prespec_overview_attempt_event",
    } <= worker_selects
    assert "prespec_overview_attempt" in app_selects
    assert "prespec_overview_attempt" in worker_selects
    for role_inserts in (app_inserts, worker_inserts):
        assert {"prespec_overview_review", "prespec_overview_snapshot"} <= role_inserts
    assert {
        "prespec_overview_attempt",
        "prespec_overview_result",
        "prespec_overview_attempt_event",
    } <= worker_inserts
    assert "prespec_overview_attempt" not in app_inserts

    allowed_review_updates = {
        "current_snapshot_id",
        "status",
        "result",
        "completed_at",
        "updated_at",
    }
    broad_updates = {
        "app": _table_grants("app", "UPDATE"),
        "worker": _table_grants("worker", "UPDATE"),
    }
    deletes = {
        "app": _table_grants("app", "DELETE"),
        "worker": _table_grants("worker", "DELETE"),
    }
    for role in ("app", "worker"):
        assert _column_update_grant(role, "prespec_overview_review") == (
            allowed_review_updates
        )
        assert not {
            "prespec_overview_review",
            "prespec_overview_snapshot",
            "prespec_overview_attempt",
        } & broad_updates[role]
        assert not {
            "prespec_overview_review",
            "prespec_overview_snapshot",
            "prespec_overview_attempt",
        } & deletes[role]


def test_overview_worker_update_stays_column_scoped_and_snapshot_immutable() -> None:
    """Guard the worker grant against a future table-wide UPDATE expansion."""

    worker_updates = _table_grants("worker", "UPDATE")
    app_updates = _table_grants("app", "UPDATE")
    for broad_updates in (app_updates, worker_updates):
        assert "prespec_overview_review" not in broad_updates
        assert "prespec_overview_snapshot" not in broad_updates

    allowed_review_updates = {
        "current_snapshot_id",
        "status",
        "result",
        "completed_at",
        "updated_at",
    }
    assert _column_update_grant("app", "prespec_overview_review") == allowed_review_updates
    assert _column_update_grant("worker", "prespec_overview_review") == allowed_review_updates


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
                for column in ("status", "started_at", "completed_at", "result_id"):
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
                for table in ("judgment_revision", "review_revision"):
                    assert not _table_privilege(connection, "worker", table, "SELECT")
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
