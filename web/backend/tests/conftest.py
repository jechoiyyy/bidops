"""Conditional process-wide isolated backend test environment.

For the full suite, T14, and runs with an explicit PostgreSQL maintenance URL,
this hook runs before test-module collection.  That timing is intentional:
``app.core.db`` creates its process-wide engine at import time, so an ordinary
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
    "BIDOPS_SCHEDULER_ENABLED": "false",
    "BIDOPS_G2B_API_KEY": "",
    "BIDOPS_G2B_ATTACHMENT_ENABLED": "false",
    "BIDOPS_VLLM_BASE_URL": "http://127.0.0.1:9/v1",
    "BIDOPS_VLLM_API_KEY": "EMPTY",
    "BIDOPS_OPENAI_ENABLED": "false",
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


# --- lifecycle 확장점 registry 픽스처 (명세 §6) ------------------------------
# registry는 프로세스 전역 단일 객체이고 조립 계층(`app.main`)이 import 시점에
# 등록한다. 모듈 폴더별 테스트는 그 전역 상태에 기대지 않고 자기 상태를 명시한다:
# lifecycle 테스트는 **빈** registry(제공자 부재), screening 테스트와 두 모듈
# 조합 테스트는 screening만 등록된 registry. 둘 다 끝나면 원래 객체를 되돌려
# 같은 프로세스에서 뒤에 도는 API 테스트가 조립 상태를 잃지 않게 한다.


@pytest.fixture
def empty_extensions():
    """제공자가 하나도 없는 registry. lifecycle 단독 동작을 검사할 때 쓴다."""

    from app.lifecycle import (
        extension_registry,
        reset_extension_registry,
        restore_extension_registry,
    )

    previous = extension_registry()
    try:
        yield reset_extension_registry()
    finally:
        restore_extension_registry(previous)


@pytest.fixture
def screening_extensions():
    """screening의 projection과 회차 적재 hook만 등록된 registry.

    `ingest_run`으로 판정·리뷰·C-2 결과를 적재하거나 판정이 실린 목록·통계를
    읽는 테스트는 이 픽스처를 요구해야 한다. `app.main`을 import한 적이 있는지에
    따라 결과가 달라지는 순서 의존을 여기서 끊는다.
    """

    from app.lifecycle import (
        extension_registry,
        reset_extension_registry,
        restore_extension_registry,
    )
    from app.screening import register_lifecycle_extensions

    previous = extension_registry()
    registry = reset_extension_registry()
    register_lifecycle_extensions(registry)
    try:
        yield registry
    finally:
        restore_extension_registry(previous)
