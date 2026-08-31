"""SQLAlchemy engine, declarative base, sessions, and DB initialization."""

from __future__ import annotations

import os
import sqlite3
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


def _json_serializer(value: Any) -> str:
    """Use the repository JSON byte contract for SQLAlchemy JSON values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class Base(DeclarativeBase):
    """Base class for all BidOps Admin ORM models."""


settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

DATABASE_URL = settings.database_url or f"sqlite:///{Path(settings.database_path).as_posix()}"

# ``bidops`` is the sole application schema in PostgreSQL.  Alembic binds the
# local declarative table keys to this schema; explicitly-created SQLite test
# engines remain schema-less.
MODEL_SCHEMA = "bidops" if DATABASE_URL.startswith(("postgresql", "postgres")) else None

_ENGINE_OPTIONS: dict[str, Any] = {
    "connect_args": {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    # The repository JSON byte contract is what the generation-config digest is
    # computed over, so every engine must serialize JSON the same way.
    "json_serializer": _json_serializer,
    "future": True,
}


def schema_bound(bind: Engine) -> Engine:
    """Route PostgreSQL table keys to the sole ``bidops`` schema."""

    if bind.dialect.name == "postgresql":
        return bind.execution_options(schema_translate_map={None: "bidops"})
    return bind


# Declarative tables intentionally use local keys so SQLite isolated binds
# remain schema-less. PostgreSQL application sessions are schema-translated.
engine = schema_bound(create_engine(DATABASE_URL, **_ENGINE_OPTIONS))


@event.listens_for(engine, "connect")
def configure_sqlite_connection(dbapi_connection: Any, _connection_record: Any = None) -> None:
    """Enable SQLite safeguards and WAL for every new file-DB connection."""

    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        # SQLite cannot use WAL for an in-memory database.  The pragma is
        # harmless there and returns ``memory``; file-backed databases use WAL.
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()
    # Do this after the connection is opened, not only for ORM sessions: the
    # Alembic and db-admin engines use the same callback as well.
    from .screening.generation_config import register_sqlite_functions

    register_sqlite_functions(dbapi_connection)


_configure_sqlite_connection = configure_sqlite_connection


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# A short alias is useful for dependency providers and keeps the public API
# unsurprising for code that expects a session factory named ``Session``.
SessionFactory = SessionLocal

ALEMBIC_HEAD = "0014_prespec_overview_attempt_result"
# Alembic hard-codes ``version_num VARCHAR(32)`` when it creates its version
# table, and revision identifiers in this lineage are longer than that.  The
# table is created at this width by ``alembic/env.py`` instead; the guard in
# ``tests/test_db_migrations.py`` keeps every identifier inside it.
ALEMBIC_VERSION_NUM_WIDTH = 64
MIGRATION_COMMAND = "docker compose --project-name <isolated> -f docker-compose.t7.yml run --rm migrate"


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_revision(bind: Engine | None = None) -> str | None:
    """Return the single Alembic revision recorded in a database."""

    from alembic.migration import MigrationContext

    target = schema_bound(bind or engine)
    with target.connect() as connection:
        version_schema = "bidops" if target.dialect.name == "postgresql" else None
        return MigrationContext.configure(
            connection, opts={"version_table_schema": version_schema}
        ).get_current_revision()


def isolated_test_boundary_active() -> bool:
    """Return whether the process explicitly opted into SQLite test mode.

    ``PYTEST_CURRENT_TEST`` is present while an individual pytest test is
    running, but it is not guaranteed to be set while a TestClient lifespan
    starts.  The explicit flag is therefore used by the isolated runner for
    application-lifespan tests; it is never set by the production Compose
    template.
    """

    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("BIDOPS_TEST_MODE") == "1"
    )


def ensure_database_current(bind: Engine | None = None) -> None:
    """Refuse to use an empty, unversioned, unknown, or stale database.

    The application process is intentionally not an administrator.  It never
    runs Alembic and never calls ``create_all`` for the configured database.
    PostgreSQL DDL belongs exclusively to Alembic and the ``migrate`` role;
    the runtime ``app``/``worker`` roles do not hold CREATE privileges.
    """

    target = schema_bound(bind or engine)
    if target.dialect.name == "postgresql":
        with target.connect() as connection:
            if connection.scalar(text("SELECT to_regclass('bidops.run')")) is None:
                raise RuntimeError(
                    "Database migration required: the bidops.run table is missing; "
                    f"run `{MIGRATION_COMMAND}` to create the schema."
                )
    inspector = inspect(target)
    schema = "bidops" if target.dialect.name == "postgresql" else None
    tables = set(inspector.get_table_names(schema=schema))
    if "alembic_version" not in tables:
        if not tables:
            raise RuntimeError(
                "Database migration required: database is empty; "
                f"run `{MIGRATION_COMMAND}` to create the schema."
            )
        raise RuntimeError(
            "Database migration required: existing database is unversioned; "
            f"create a backup and run `{MIGRATION_COMMAND}`."
        )
    revision = current_revision(target)
    if revision != ALEMBIC_HEAD:
        value = revision or "none"
        raise RuntimeError(
            f"Database migration required: current revision is {value}, expected {ALEMBIC_HEAD}; "
            f"run `{MIGRATION_COMMAND}` before starting the service."
        )


def init_db(bind: Engine | None = None) -> None:
    """Create isolated-test tables or verify the migrated PostgreSQL schema.

    An explicit ``bind`` is the isolated-test path: the caller owns a private
    SQLite engine and the full declarative table set is created directly.  The
    no-argument application path never creates or migrates anything; it only
    verifies that the configured PostgreSQL database is at the expected head.
    """

    from . import models  # noqa: F401 - register every declarative table

    # pytest's application tests use dependency-overridden isolated SQLite
    # engines. That test-only path is explicit; every non-test process still
    # fails before opening a configured SQLite database.
    if (
        bind is None
        and not DATABASE_URL.startswith(("postgresql", "postgres"))
        and not isolated_test_boundary_active()
    ):
        raise RuntimeError(
            "BidOps application runtime requires PostgreSQL 17; SQLite is only "
            "accepted for isolated tests and one-time migration input"
        )

    target = schema_bound(bind or engine)
    if target.dialect.name == "postgresql":
        # A single known table is not enough: the ordered
        # postgres-init -> migrate gate must have run to completion, so the
        # recorded Alembic revision is checked as well.
        ensure_database_current(target)
    else:
        Base.metadata.create_all(bind=target)


def assert_postgresql_runtime() -> None:
    """Fail fast when a live application is configured with SQLite."""

    if not DATABASE_URL.startswith(("postgresql", "postgres")):
        raise RuntimeError(
            "BIDOPS_DATABASE_URL must point to PostgreSQL 17; live SQLite is forbidden"
        )
