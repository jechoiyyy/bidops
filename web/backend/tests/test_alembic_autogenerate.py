"""Alembic drift checks compare ORM metadata to the physical bidops schema."""

from __future__ import annotations

from tests.postgres import requires_postgres, run_alembic, temporary_database


@requires_postgres
def test_alembic_check_has_no_default_schema_bidops_mirror_drift() -> None:
    with temporary_database() as database_url:
        result = run_alembic(database_url, "check")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "No new upgrade operations detected" in output
    assert "Detected added table" not in output
    assert "Detected removed table" not in output
