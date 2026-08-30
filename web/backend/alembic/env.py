"""Alembic environment for the PostgreSQL 17 ``bidops`` schema.

PostgreSQL is the single canonical store.  The screening runtime constraints
that SQLite could only express through trigger-backed CHECKs are declarative
constraints and plpgsql triggers here, so no autogenerate exclusion list is
needed.  A non-PostgreSQL URL is refused rather than silently migrating a
local file database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.db import ALEMBIC_VERSION_NUM_WIDTH, Base, settings
from app import models  # noqa: F401 - register every declarative table


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Alembic hard-codes ``version_num VARCHAR(32)`` when it creates its version
# table, and two revision identifiers in this project are longer than that.
# PostgreSQL enforces the declared length, so ``alembic upgrade head`` failed
# on the canonical store while SQLite -- which ignores VARCHAR length --
# passed.  The table is therefore created here at a width that fits, before
# Alembic looks for it; ``Table.create(checkfirst=True)`` then leaves the
# existing table alone.  Both statements are idempotent.
#
# The width lives in ``app.db`` so ``tests/test_db_migrations.py`` can hold
# every revision identifier to it without importing this Alembic script.
VERSION_NUM_WIDTH = ALEMBIC_VERSION_NUM_WIDTH
CREATE_VERSION_TABLE = (
    f"CREATE TABLE IF NOT EXISTS bidops.alembic_version ("
    f"version_num VARCHAR({VERSION_NUM_WIDTH}) NOT NULL, "
    f"CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
)
# A version table left at the default width by an earlier run is widened
# before any revision runs, so the first UPDATE of version_num cannot
# truncate.
WIDEN_VERSION_COLUMN = (
    f"ALTER TABLE IF EXISTS bidops.alembic_version "
    f"ALTER COLUMN version_num TYPE VARCHAR({VERSION_NUM_WIDTH})"
)


def _database_url() -> str:
    configured = settings.database_url
    if not configured or not configured.startswith(("postgresql", "postgres")):
        raise RuntimeError("Alembic requires BIDOPS_DATABASE_URL for PostgreSQL 17")
    return configured


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="bidops",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS bidops")
        context.execute(CREATE_VERSION_TABLE)
        context.execute(WIDEN_VERSION_COLUMN)
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="bidops",
        include_schemas=True,
    )
    with context.begin_transaction():
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS bidops"))
        connection.execute(text(CREATE_VERSION_TABLE))
        connection.execute(text(WIDEN_VERSION_COLUMN))
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
