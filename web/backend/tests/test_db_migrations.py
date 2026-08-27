"""PostgreSQL migration contract for the merged screening/deep-review lineage.

The T15 branch built the screening runtime through four SQLite revisions whose
DDL (``RAISE(ABORT)`` triggers, ``PRAGMA writable_schema`` rewrites, and CHECK
constraints calling per-connection Python UDFs) has no PostgreSQL form.  The
merged lineage replaces them with ``0003_screening_runtime_pg``, so these tests
assert what that lineage actually guarantees rather than replaying the removed
incremental SQLite history.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.db import ALEMBIC_HEAD
from app.models import LEGACY_TABLES, NEW_TABLES, SCREENING_RUNTIME_TABLES
from app.screening.generation_config import GenerationConfig, legacy_generation_config
from tests.postgres import migrated_engine, requires_postgres, run_alembic, temporary_database

pytestmark = requires_postgres

LEAN_V1_HEAD = "0002_screening_basis_text"
ALL_TABLES = frozenset(LEGACY_TABLES + NEW_TABLES + SCREENING_RUNTIME_TABLES)


def _scalars(engine, sql: str, **params) -> list:
    with engine.connect() as connection:
        return list(connection.scalars(text(sql), params))


def _scalar(engine, sql: str, **params):
    with engine.connect() as connection:
        return connection.scalar(text(sql), params)


def _tables(engine) -> set[str]:
    return set(
        _scalars(
            engine,
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'bidops'",
        )
    )


def test_clean_database_migrates_to_a_single_head() -> None:
    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == ALEMBIC_HEAD
        assert _tables(engine) == ALL_TABLES | {"alembic_version"}


def test_alembic_reports_exactly_one_head() -> None:
    with temporary_database(upgrade_to=None) as database_url:
        result = run_alembic(database_url, "heads")
        assert result.returncode == 0, result.stderr
        heads = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(heads) == 1, result.stdout
        assert ALEMBIC_HEAD in heads[0]


def test_existing_lean_v1_database_upgrades_without_recreating_tables() -> None:
    """The screening tables belong to 0003 only, so neither path creates them twice."""

    with temporary_database(upgrade_to=LEAN_V1_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        lean_tables = _tables(engine)
        assert lean_tables == set(LEGACY_TABLES + NEW_TABLES) | {"alembic_version"}
        assert not lean_tables & set(SCREENING_RUNTIME_TABLES)

        # A long legacy basis must survive the upgrade untruncated.
        basis = "근거 " * 40
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.run"
                    " (id, window_from, window_to, timezone, generated_at, screening_basis,"
                    "  status, counts_json)"
                    " VALUES ('legacy-run', '2026-08-01', '2026-08-02', 'Asia/Seoul',"
                    "         now(), :basis, 'active', '{}')"
                ),
                {"basis": basis},
            )

        upgraded = run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr

        assert _tables(engine) == ALL_TABLES | {"alembic_version"}
        assert _scalar(engine, "SELECT version_num FROM bidops.alembic_version") == ALEMBIC_HEAD
        assert (
            _scalar(engine, "SELECT screening_basis FROM bidops.run WHERE id = 'legacy-run'")
            == basis
        )
        engine.dispose()


def test_clean_and_upgraded_databases_have_the_same_schema() -> None:
    column_sql = (
        "SELECT table_name || '.' || column_name || ':' || data_type"
        " FROM information_schema.columns WHERE table_schema = 'bidops' ORDER BY 1"
    )
    with migrated_engine() as clean:
        clean_columns = _scalars(clean, column_sql)
    with temporary_database(upgrade_to=LEAN_V1_HEAD) as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        assert run_alembic(database_url, "upgrade", "head").returncode == 0
        upgraded_columns = _scalars(engine, column_sql)
        engine.dispose()
    assert clean_columns == upgraded_columns


def test_fresh_database_seeds_only_the_runtime_singletons() -> None:
    """Migration must not seed policy or portal rows, and always-on stays off."""

    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT count(*) FROM bidops.schedule_setting") == 1
        assert _scalar(engine, "SELECT count(*) FROM bidops.always_on_state") == 1
        assert _scalar(engine, "SELECT bool_or(enabled) FROM bidops.always_on_state") is False
        assert _scalar(engine, "SELECT count(*) FROM bidops.screening_policy") == 0
        assert _scalar(engine, "SELECT count(*) FROM bidops.agency_portal") == 0
        assert _scalar(engine, "SELECT count(*) FROM bidops.screening_execution") == 0


def test_migration_records_a_deterministic_audit_marker() -> None:
    with migrated_engine() as engine:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT event_id, actor, target_type, target_id, details_json"
                    " FROM bidops.screening_audit_event WHERE event_type = 'db.migration'"
                )
            ).one()
        assert row.actor == "system:migration"
        assert row.target_type == "database"
        assert row.target_id == ALEMBIC_HEAD
        assert row.details_json == {
            "migration_revision": ALEMBIC_HEAD,
            "action": "upgrade",
        }


@pytest.mark.parametrize(
    "config", [GenerationConfig(), legacy_generation_config()], ids=["default", "legacy"]
)
def test_database_canonical_json_matches_the_python_contract(config: GenerationConfig) -> None:
    """The digest binding is only fail-closed if both sides agree byte for byte."""

    with migrated_engine() as engine:
        canonical = _scalar(
            engine,
            "SELECT bidops.generation_config_canonical_json(:value)",
            value=config.canonical_json(),
        )
        digest = _scalar(
            engine,
            "SELECT bidops.generation_config_digest(:value)",
            value=config.canonical_json(),
        )
    assert canonical == config.canonical_json()
    assert digest == config.digest()


def test_database_normalises_key_order_and_whitespace_to_one_digest() -> None:
    reordered = (
        '{ "think": false, "stream": false,'
        ' "schema_version": "bidops.generation-config.v1",'
        ' "num_predict": {"synthesis": 4096, "perspective": 2048, "counterargument": 2048},'
        ' "num_ctx": 16384 }'
    )
    with migrated_engine() as engine:
        assert (
            _scalar(engine, "SELECT bidops.generation_config_digest(:value)", value=reordered)
            == GenerationConfig().digest()
        )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('{"num_ctx":16384}', id="missing-keys"),
        pytest.param("not json", id="malformed"),
        pytest.param(
            '{"num_ctx":16384.0,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":false}',
            id="float-num-ctx",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":true}',
            id="think-enabled",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":99999},"schema_version":"bidops.generation-config.v1",'
            '"stream":false,"think":false}',
            id="budget-over-context",
        ),
        pytest.param(
            '{"num_ctx":16384,"num_predict":{"counterargument":2048,"perspective":2048,'
            '"synthesis":4096},"schema_version":"bidops.generation-config.v2",'
            '"stream":false,"think":false}',
            id="unknown-schema",
        ),
    ],
)
def test_database_rejects_non_canonical_generation_config(value: str) -> None:
    with migrated_engine() as engine:
        assert _scalar(engine, "SELECT bidops.generation_config_digest(:value)", value=value) is None


def test_downgrade_removes_only_the_screening_runtime() -> None:
    with temporary_database() as database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, future=True)
        result = run_alembic(database_url, "downgrade", LEAN_V1_HEAD)
        assert result.returncode == 0, result.stderr
        remaining = _tables(engine)
        assert remaining == set(LEGACY_TABLES + NEW_TABLES) | {"alembic_version"}
        assert not remaining & set(SCREENING_RUNTIME_TABLES)
        engine.dispose()
