"""Alembic environment for the BidOps SQLite database."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base, configure_sqlite_connection

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


_GENERATION_CONSTRAINT_PREFIXES = (
    "ck_screening_execution_generation_config",
    "ck_screening_attempt_generation_config",
    "ck_quality_gate_generation_config",
    "ck_quality_gate_evaluation_generation_config",
    "ck_schedule_execution_generation_config",
    "ck_always_on_generation_config",
)


def _include_object(object_: object, name: str | None, type_: str, reflected: bool, compare_to: object | None) -> bool:
    """Keep SQLite trigger-backed generation checks out of autogenerate noise."""

    if type_ == "check_constraint" and isinstance(name, str) and name.startswith(_GENERATION_CONSTRAINT_PREFIXES):
        return False
    return True


def _database_url() -> str:
    settings = get_settings()
    return settings.database_url or f"sqlite:///{settings.database_path.as_posix()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        include_object=_include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # ``engine_from_config`` creates a separate Alembic engine rather than
    # reusing app.db.engine.  Install the same SQLite UDF/PRAGMA callback so
    # migration DDL and backfills cannot bypass the DB validator.
    event.listen(connectable, "connect", configure_sqlite_connection)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=_include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
