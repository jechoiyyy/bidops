"""Conditional process-wide isolated backend test environment.

For the full suite, T14, and runs with an explicit PostgreSQL maintenance URL,
this hook runs before test-module collection.  That timing is intentional:
``app.db`` creates its process-wide engine at import time, so an ordinary
fixture would be too late to prevent an inherited operator URL or the default
persistent SQLite path from being selected.  Pure unit targets do not enter
the harness, and other targeted ``requires_postgres`` tests skip explicitly
when a maintenance server was not requested.
"""

from __future__ import annotations

import atexit
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile

import pytest

from tests.postgres import (
    BACKEND,
    ENV_VAR,
    PROJECT_ROOT,
    SKIP_REASON,
    PostgresHarnessError,
    postgres_harness_requested,
    temporary_database,
    temporary_postgres_server,
)


_HARNESS: ExitStack | None = None
_TEST_ENVIRONMENT = {
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


def _restore_environment(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _close_harness() -> None:
    global _HARNESS
    if _HARNESS is not None:
        harness, _HARNESS = _HARNESS, None
        harness.close()


def pytest_configure(config: pytest.Config) -> None:
    """Bind a PostgreSQL-requiring pytest process to a fresh migrated DB."""

    global _HARNESS
    if _HARNESS is not None:
        return
    if not postgres_harness_requested(
        config.args,
        invocation_dir=Path(config.invocation_params.dir),
        rootpath=Path(config.rootpath or BACKEND),
    ):
        return

    stack = ExitStack()
    managed_names = {
        *list(_TEST_ENVIRONMENT),
        "BIDOPS_ROOT",
        "BIDOPS_DATA_DIR",
        "BIDOPS_ATTACHMENTS_DIR",
        "BIDOPS_DATABASE_URL",
        ENV_VAR,
    }
    previous = {name: os.environ.get(name) for name in managed_names}
    stack.callback(_restore_environment, previous)

    try:
        runtime_value = stack.enter_context(
            tempfile.TemporaryDirectory(prefix="bidops-backend-pytest-")
        )
        runtime = Path(runtime_value)
        data = runtime / "data"
        attachments = runtime / "attachments"
        data.mkdir()
        attachments.mkdir()
        os.environ.update(
            {
                **_TEST_ENVIRONMENT,
                "BIDOPS_ROOT": str(PROJECT_ROOT),
                "BIDOPS_DATA_DIR": str(data),
                "BIDOPS_ATTACHMENTS_DIR": str(attachments),
            }
        )

        maintenance = stack.enter_context(temporary_postgres_server())
        os.environ[ENV_VAR] = maintenance
        database_url = stack.enter_context(temporary_database(upgrade_to="head"))
        os.environ["BIDOPS_DATABASE_URL"] = database_url
    except (PostgresHarnessError, OSError) as exc:
        stack.close()
        raise pytest.UsageError(
            "Could not create the isolated PostgreSQL 17 backend test harness: "
            f"{exc}"
        ) from None

    _HARNESS = stack


def pytest_unconfigure(config: pytest.Config) -> None:
    """Drop only the database, container, and paths owned by this test run."""

    _close_harness()


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip targeted PostgreSQL tests when no harness/server was requested."""

    if _HARNESS is not None:
        return
    skipped = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("requires_postgres") is not None:
            item.add_marker(skipped)


atexit.register(_close_harness)
