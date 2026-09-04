"""Regression tests for the process-wide PostgreSQL isolation harness."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from tests import postgres


def test_alembic_child_environment_does_not_forward_unrelated_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HARNESS_SENTINEL_SECRET", "must-not-be-forwarded")
    monkeypatch.setenv("BIDOPS_ROOT", str(postgres.PROJECT_ROOT))
    monkeypatch.setenv("BIDOPS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BIDOPS_ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(postgres.subprocess, "run", fake_run)
    result = postgres.run_alembic("postgresql+psycopg://test.invalid/test", "heads")

    assert result.returncode == 0
    child = captured["env"]
    assert isinstance(child, dict)
    assert "HARNESS_SENTINEL_SECRET" not in child
    assert child["BIDOPS_ROOT"] == str(postgres.PROJECT_ROOT)
    assert child["BIDOPS_G2B_API_KEY"] == ""
    assert child["BIDOPS_OLLAMA_BASE_URL"] == "http://127.0.0.1:9"


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ((), True),
        (("tests",), True),
        (("tests/app/test_integration_t14.py",), True),
        (("tests/app/test_db_migrations.py",), False),
        (("tests/screening/test_profile.py",), False),
        (
            (
                "tests/screening/test_scheduler.py::"
                "test_reservation_pk_and_duplicate_execution_are_transactional",
            ),
            False,
        ),
        (
            (
                "tests/screening/test_scheduler.py::"
                "test_migrated_postgresql_allows_recovery_of_skipped_execution",
            ),
            False,
        ),
    ],
)
def test_harness_activation_matches_collection_selection(
    selection: tuple[str, ...],
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(postgres.ENV_VAR, raising=False)
    assert (
        postgres.postgres_harness_requested(
            selection,
            invocation_dir=postgres.BACKEND,
            rootpath=postgres.BACKEND,
        )
        is expected
    )


def test_explicit_maintenance_url_activates_targeted_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        postgres.ENV_VAR,
        "postgresql+psycopg://test.invalid/postgres",
    )

    assert postgres.postgres_harness_requested(
        ("tests/app/test_db_migrations.py",),
        invocation_dir=postgres.BACKEND,
        rootpath=postgres.BACKEND,
    )


def test_requires_postgres_marker_is_registered(pytestconfig: pytest.Config) -> None:
    assert any(
        marker.startswith("requires_postgres:")
        for marker in pytestconfig.getini("markers")
    )


def test_profile_target_runs_without_docker() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/screening/test_profile.py"],
        cwd=postgres.BACKEND,
        env={
            "PATH": "/nonexistent",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "3 passed" in result.stdout


def test_targeted_postgres_without_server_is_explicitly_skipped() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/app/test_alembic_autogenerate.py",
        ],
        cwd=postgres.BACKEND,
        env={
            "PATH": "/nonexistent",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "1 skipped" in result.stdout


def test_configured_maintenance_server_does_not_start_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = "postgresql+psycopg://test.invalid/postgres"
    monkeypatch.setenv(postgres.ENV_VAR, configured)
    monkeypatch.setattr(
        postgres.shutil,
        "which",
        lambda _name: pytest.fail("Docker discovery must not run for an explicit server"),
    )

    with postgres.temporary_postgres_server() as yielded:
        assert yielded == configured


def test_missing_docker_has_actionable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(postgres.ENV_VAR, raising=False)
    monkeypatch.setattr(postgres.shutil, "which", lambda _name: None)

    with pytest.raises(
        postgres.PostgresHarnessError,
        match="BIDOPS_TEST_POSTGRES_URL is required when Docker is unavailable",
    ):
        with postgres.temporary_postgres_server():
            pass


def test_missing_server_skips_database_helper_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(postgres.ENV_VAR, raising=False)

    with pytest.raises(pytest.skip.Exception, match=postgres.SKIP_REASON):
        with postgres.temporary_database():
            pass
