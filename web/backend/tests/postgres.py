"""Disposable PostgreSQL 17 servers and databases for backend tests.

When the selected tests require PostgreSQL, ``tests/conftest.py`` uses these
helpers before collection so imports of ``app.db`` cannot bind to an operator
database or a persistent SQLite file.  A caller may provide
``BIDOPS_TEST_POSTGRES_URL`` for a disposable maintenance server; otherwise the
pytest harness owns a short-lived Docker container.  Every database created
here has a random test-only name, is migrated explicitly, and is dropped on
exit.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

BACKEND = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND.parents[1]
TESTS_ROOT = BACKEND / "tests"
T14_TEST = TESTS_ROOT / "test_integration_t14.py"
ENV_VAR = "BIDOPS_TEST_POSTGRES_URL"
POSTGRES_IMAGE = "postgres:17.11"
POSTGRES_CONTAINER_PREFIX = "bidops-pytest-pg-"
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}")
SKIP_REASON = (
    f"{ENV_VAR} is not set; PostgreSQL migration and constraint tests need a"
    " disposable PostgreSQL 17 server"
)


class PostgresHarnessError(RuntimeError):
    """Raised when the isolated PostgreSQL test boundary cannot be created."""


def maintenance_url() -> str | None:
    return os.environ.get(ENV_VAR) or None


# Kept as the stable decorator imported by PostgreSQL-specific test modules.
# The collection hook runs it against an active harness or adds an explicit
# skip when a targeted invocation did not provide a maintenance server.
requires_postgres = pytest.mark.requires_postgres


def _resolve_collection_path(
    value: str,
    *,
    invocation_dir: Path,
    rootpath: Path,
) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    invoked = (invocation_dir / candidate).resolve()
    rooted = (rootpath / candidate).resolve()
    if invoked.exists() or not rooted.exists():
        return invoked
    return rooted


def postgres_harness_requested(
    selections: Sequence[str],
    *,
    invocation_dir: Path,
    rootpath: Path = BACKEND,
) -> bool:
    """Return whether pre-collection PostgreSQL setup is required.

    An explicit maintenance URL, an empty selection, and the whole backend
    tests directory activate the harness.  Among individual targets, only T14
    activates automatically; marked PostgreSQL tests without a server are
    skipped explicitly by ``tests/conftest.py`` after collection.
    """

    if maintenance_url() is not None:
        return True
    if not selections:
        return True

    for raw_selection in selections:
        path_text = str(raw_selection).split("::", 1)[0]
        if Path(path_text).name == T14_TEST.name:
            return True
        path = _resolve_collection_path(
            path_text,
            invocation_dir=invocation_dir,
            rootpath=rootpath,
        )
        if path == TESTS_ROOT:
            return True
    return False


def _alembic_environment(database_url: str) -> dict[str, str]:
    """Build a minimal child environment without forwarding test-run secrets."""

    required = ("BIDOPS_ROOT", "BIDOPS_DATA_DIR", "BIDOPS_ATTACHMENTS_DIR")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise PostgresHarnessError(
            "PostgreSQL test harness did not configure required paths: "
            + ", ".join(missing)
        )

    env = {
        "BIDOPS_ROOT": os.environ["BIDOPS_ROOT"],
        "BIDOPS_DATA_DIR": os.environ["BIDOPS_DATA_DIR"],
        "BIDOPS_ATTACHMENTS_DIR": os.environ["BIDOPS_ATTACHMENTS_DIR"],
        "BIDOPS_DATABASE_URL": database_url,
        "BIDOPS_OLLAMA_BASE_URL": "http://127.0.0.1:9",
        "BIDOPS_SCHEDULER_ENABLED": "false",
        "BIDOPS_LIVE_OLLAMA_TEST": "false",
        "BIDOPS_G2B_API_KEY": "",
        "BIDOPS_G2B_ATTACHMENT_ENABLED": "false",
        "BIDOPS_VLLM_BASE_URL": "http://127.0.0.1:9/v1",
        "BIDOPS_VLLM_API_KEY": "EMPTY",
        "BIDOPS_OPENAI_ENABLED": "false",
        "BIDOPS_CODEX_EXEC_ENABLED": "false",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "false",
    }
    for name in ("PATH", "LANG", "LC_ALL", "TZ"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real Alembic CLI against one database."""

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=_alembic_environment(database_url),
        text=True,
        capture_output=True,
    )


@contextmanager
def temporary_postgres_server() -> Iterator[str]:
    """Yield a PostgreSQL maintenance URL, starting Docker when necessary."""

    configured = maintenance_url()
    if configured is not None:
        yield configured
        return

    docker = shutil.which("docker")
    if docker is None:
        raise PostgresHarnessError(
            f"{ENV_VAR} is required when Docker is unavailable; provide a "
            "disposable PostgreSQL 17 maintenance URL"
        )

    try:
        available = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        available = None
    if available is None or available.returncode != 0:
        raise PostgresHarnessError(
            f"{ENV_VAR} is required because the Docker daemon is unavailable; "
            "provide a disposable PostgreSQL 17 maintenance URL"
        )

    container_name = POSTGRES_CONTAINER_PREFIX + uuid.uuid4().hex[:16]
    container_id: str | None = None
    run_attempted = False
    try:
        run_attempted = True
        try:
            started = subprocess.run(
                [
                    docker,
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    container_name,
                    "-e",
                    "POSTGRES_DB=postgres",
                    "-e",
                    "POSTGRES_USER=owner",
                    "-e",
                    "POSTGRES_PASSWORD=verify-only",
                    "-p",
                    "127.0.0.1::5432",
                    POSTGRES_IMAGE,
                ],
                text=True,
                capture_output=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PostgresHarnessError(
                f"could not start the isolated {POSTGRES_IMAGE} test container"
            ) from exc
        candidate = started.stdout.strip()
        if started.returncode != 0 or not _CONTAINER_ID.fullmatch(candidate):
            raise PostgresHarnessError(
                f"could not start the isolated {POSTGRES_IMAGE} test container"
            )
        container_id = candidate

        ready = False
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [
                    docker,
                    "exec",
                    container_id,
                    "pg_isready",
                    "-U",
                    "owner",
                    "-d",
                    "postgres",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if probe.returncode == 0:
                ready = True
                break
            time.sleep(0.5)
        if not ready:
            raise PostgresHarnessError(
                f"isolated {POSTGRES_IMAGE} test container did not become ready"
            )

        port_result = subprocess.run(
            [docker, "port", container_id, "5432/tcp"],
            text=True,
            capture_output=True,
            timeout=10,
        )
        port = port_result.stdout.strip().rsplit(":", 1)[-1]
        if port_result.returncode != 0 or not port.isdigit():
            raise PostgresHarnessError(
                "could not resolve the isolated PostgreSQL test port"
            )
        yield f"postgresql+psycopg://owner:verify-only@127.0.0.1:{port}/postgres"
    finally:
        # The random, validated name is owned by this context even if `docker
        # run` timed out after creating the container but before returning its ID.
        if run_attempted and container_name.startswith(POSTGRES_CONTAINER_PREFIX):
            try:
                subprocess.run(
                    [docker, "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PostgresHarnessError(
                    "could not remove the owned PostgreSQL test container"
                ) from exc


@contextmanager
def temporary_database(*, upgrade_to: str | None = "head") -> Iterator[str]:
    """Create a private database, optionally migrate it, and always drop it."""

    base = maintenance_url()
    if base is None:  # pragma: no cover - guarded by requires_postgres
        pytest.skip(SKIP_REASON)

    name = f"bidops_test_{uuid.uuid4().hex[:16]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT", future=True)
    created = False
    try:
        try:
            with admin.connect() as connection:
                version = int(connection.scalar(text("SHOW server_version_num")))
                if version // 10_000 != 17:
                    raise PostgresHarnessError(
                        "PostgreSQL test harness requires server major version 17"
                    )
                connection.execute(text(f'CREATE DATABASE "{name}"'))
                created = True
        except PostgresHarnessError:
            raise
        except (SQLAlchemyError, TypeError, ValueError):
            raise PostgresHarnessError(
                "could not create a database on the disposable PostgreSQL 17 server"
            ) from None
        # ``str(URL)`` intentionally redacts the password as ``***``.  The
        # child Alembic process needs the real disposable-server credential.
        database_url = make_url(base).set(database=name).render_as_string(
            hide_password=False
        )
        if upgrade_to is not None:
            result = run_alembic(database_url, "upgrade", upgrade_to)
            if result.returncode != 0:
                raise PostgresHarnessError(
                    "Alembic failed to migrate the isolated PostgreSQL 17 test database"
                )
        yield database_url
    finally:
        try:
            if created:
                try:
                    with admin.connect() as connection:
                        connection.execute(
                            text(
                                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                                " WHERE datname = :name AND pid <> pg_backend_pid()"
                            ),
                            {"name": name},
                        )
                        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
                except SQLAlchemyError:
                    raise PostgresHarnessError(
                        "could not drop the owned PostgreSQL test database"
                    ) from None
        finally:
            admin.dispose()


@contextmanager
def migrated_engine(*, upgrade_to: str | None = "head") -> Iterator[Engine]:
    """Yield an engine bound to a freshly migrated disposable database."""

    from app.db import _json_serializer, schema_bound

    with temporary_database(upgrade_to=upgrade_to) as database_url:
        engine = schema_bound(
            create_engine(database_url, json_serializer=_json_serializer, future=True)
        )
        try:
            yield engine
        finally:
            engine.dispose()
