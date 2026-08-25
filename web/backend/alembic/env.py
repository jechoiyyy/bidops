"""Alembic environment for the PostgreSQL 17 ``bidops`` schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.db import Base, settings
from app import models  # noqa: F401 - register every declarative table


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


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
