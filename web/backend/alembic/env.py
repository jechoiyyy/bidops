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
from sqlalchemy import MetaData, engine_from_config, pool, text

from app.core import ALEMBIC_VERSION_NUM_WIDTH, Base, settings

# 네 모듈의 선언 테이블을 모두 등록해야 ``Base.metadata``가 완전해진다. 명세 §3은
# `alembic/env.py`와 migration revision 파일만 각 모듈의 `models` 하위 모듈을
# 직접 import하도록 허용한다.
from app.core import models as core_models  # noqa: F401
from app.lifecycle import models as lifecycle_models  # noqa: F401
from app.screening import models as screening_models  # noqa: F401
from app.deep_review import models as deep_review_models  # noqa: F401


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

APPLICATION_SCHEMA = "bidops"


def _schema_metadata(source: MetaData) -> MetaData:
    """Return an Alembic-only copy bound to the canonical PG schema.

    The ORM keeps local table keys so isolated SQLite tests remain
    schema-less and PostgreSQL sessions use ``schema_translate_map``.  Alembic
    autogenerate does not apply that execution option while comparing
    metadata, so using the live metadata directly makes every ORM table look
    new in the default schema and every migrated ``bidops`` table look
    removed.  ``Table.to_metadata`` gives Alembic the physical schema without
    mutating the metadata used by ORM mappers and application sessions.
    """

    translated = MetaData(naming_convention=source.naming_convention)
    for table in source.tables.values():
        table.to_metadata(translated, schema=APPLICATION_SCHEMA)
    return translated


target_metadata = _schema_metadata(Base.metadata)


def _include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Keep reflection and drift checks inside the one application schema."""

    if type_ == "schema":
        return name == APPLICATION_SCHEMA
    if type_ == "table":
        return (
            parent_names.get("schema_name") == APPLICATION_SCHEMA
            and name != "alembic_version"
        )
    return True

# Alembic hard-codes ``version_num VARCHAR(32)`` when it creates its version
# table, and two revision identifiers in this project are longer than that.
# PostgreSQL enforces the declared length, so ``alembic upgrade head`` failed
# on the canonical store while SQLite -- which ignores VARCHAR length --
# passed.  The table is therefore created here at a width that fits, before
# Alembic looks for it; ``Table.create(checkfirst=True)`` then leaves the
# existing table alone.  Both statements are idempotent.
#
# The width lives in ``app.core.db`` so ``tests/app/test_db_migrations.py`` can hold
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
        version_table_schema=APPLICATION_SCHEMA,
        include_schemas=True,
        include_name=_include_name,
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
        version_table_schema=APPLICATION_SCHEMA,
        include_schemas=True,
        include_name=_include_name,
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
