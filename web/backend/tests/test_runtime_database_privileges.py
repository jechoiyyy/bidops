"""Runtime PostgreSQL role allow/deny contract.

The static checks run everywhere.  The role smoke test uses the disposable
PostgreSQL server provided by ``web/run-web-tests.sh`` and proves effective
privileges rather than trusting the grant text alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine, text

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
