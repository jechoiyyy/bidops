"""Disposable PostgreSQL databases for migration and constraint tests.

PostgreSQL 17 is the canonical store, so the invariants that used to be
SQLite triggers can only be exercised against a real server.  These tests are
opt-in: set ``BIDOPS_TEST_POSTGRES_URL`` to a maintenance URL on a *disposable*
server and each test gets its own freshly created database, migrated to head
and dropped afterwards.  Without the variable the tests skip loudly rather
than silently reporting a pass they did not earn.

``web/run-web-tests.sh`` provisions such a server when Docker is available.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

BACKEND = Path(__file__).resolve().parents[1]
ENV_VAR = "BIDOPS_TEST_POSTGRES_URL"
SKIP_REASON = (
    f"{ENV_VAR} is not set; PostgreSQL migration and constraint tests need a"
    " disposable PostgreSQL 17 server"
)


def maintenance_url() -> str | None:
    return os.environ.get(ENV_VAR) or None


requires_postgres = pytest.mark.skipif(maintenance_url() is None, reason=SKIP_REASON)


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real Alembic CLI against one database."""

    env = os.environ.copy()
    env["BIDOPS_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )


@contextmanager
def temporary_database(*, upgrade_to: str | None = "head") -> Iterator[str]:
    """Create a private database, optionally migrate it, and always drop it."""

    base = maintenance_url()
    if base is None:  # pragma: no cover - guarded by requires_postgres
        pytest.skip(SKIP_REASON)

    name = f"bidops_test_{uuid.uuid4().hex[:16]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        # ``str(URL)`` intentionally redacts the password as ``***``.  The
        # child Alembic process needs the real disposable-server credential.
        database_url = make_url(base).set(database=name).render_as_string(
            hide_password=False
        )
        if upgrade_to is not None:
            result = run_alembic(database_url, "upgrade", upgrade_to)
            assert result.returncode == 0, result.stderr + result.stdout
        yield database_url
    finally:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
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
