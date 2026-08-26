"""SQLAlchemy engine, declarative base, sessions, and DB initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Base class for all BidOps Admin ORM models."""


settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

DATABASE_URL = settings.database_url or f"sqlite:///{Path(settings.database_path).as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection: Any, _connection_record: Any) -> None:
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

ALEMBIC_HEAD = "0004_migration_audit"
MIGRATION_COMMAND = "cd web/backend && alembic upgrade head"


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

    target = bind or engine
    with target.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def ensure_database_current(bind: Engine | None = None) -> None:
    """Refuse to use an empty, unversioned, unknown, or stale database.

    The application process is intentionally not an administrator.  It never
    runs Alembic and never calls ``create_all`` for the configured database.
    """

    target = bind or engine
    if target.url.get_backend_name() == "sqlite":
        database_name = target.url.database
        if bind is None and database_name in (None, ":memory:"):
            raise RuntimeError(
                "Database migration required: a file-backed SQLite database is required; "
                f"run `{MIGRATION_COMMAND}` for a new database."
            )
        if database_name not in (None, ":memory:"):
            database_path = Path(database_name)
            if not database_path.is_absolute():
                database_path = Path.cwd() / database_path
        else:
            database_path = None
        if database_path is not None and not database_path.exists():
            raise RuntimeError(
                "Database migration required: database file does not exist; "
                f"run `{MIGRATION_COMMAND}` to create a new database."
            )
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        if not tables:
            raise RuntimeError(
                "Database migration required: database is empty; "
                "run alembic upgrade head to create the schema."
            )
        raise RuntimeError(
            "Database migration required: existing database is unversioned; "
            "create a backup and run `python -m app.db_admin migrate --backup-manifest "
            "<backup.db.manifest.json> --confirm-service-stopped`."
        )
    revision = current_revision(target)
    if revision != ALEMBIC_HEAD:
        value = revision or "none"
        raise RuntimeError(
            f"Database migration required: current revision is {value}, expected {ALEMBIC_HEAD}; "
            f"run `{MIGRATION_COMMAND}` before starting the service."
        )


def init_db(bind: Engine | None = None) -> None:
    """Initialize an isolated legacy test engine or validate the app DB.

    Existing unit tests pass an explicit in-memory engine.  That narrow path
    remains a fixture convenience and only creates the pre-Alembic tables.
    The no-argument application path performs a read-only revision check.
    """

    from . import models  # noqa: F401

    if bind is None:
        ensure_database_current()
        return

    legacy_tables = [
        Base.metadata.tables[name]
        for name in (
            "run",
            "notice",
            "judgment",
            "perspective",
            "evidence",
            "counterargument",
            "verification_item",
            "matched_performance",
            "attachment",
            "agency_portal",
            "review",
            "verification_answer",
            "ingest_warning",
        )
    ]
    Base.metadata.create_all(bind=bind, tables=legacy_tables)
