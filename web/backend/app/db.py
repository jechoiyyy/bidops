"""SQLAlchemy engine, declarative base, sessions, and DB initialization."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


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


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind: Engine | None = None) -> None:
    """Create all declared tables.

    ``bind`` is optional to make isolated in-memory test databases possible;
    normal application code uses the configured file-backed engine.
    """

    # Importing here avoids a Base/models import cycle while ensuring all
    # declarative classes are registered before create_all runs.
    from . import models  # noqa: F401

    # pytest's application tests use dependency-overridden isolated SQLite
    # engines. That test-only path is explicit; every non-test process still
    # fails before opening the configured live SQLite database.
    if (
        bind is None
        and not DATABASE_URL.startswith(("postgresql", "postgres"))
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        raise RuntimeError(
            "BidOps application runtime requires PostgreSQL 17; SQLite is only "
            "accepted for isolated tests and one-time migration input"
        )

    target = schema_bound(bind or engine)
    if target.dialect.name == "postgresql":
        with target.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS bidops"))
            Base.metadata.create_all(bind=connection)
    else:
        Base.metadata.create_all(bind=target)


def assert_postgresql_runtime() -> None:
    """Fail fast when a live application is configured with SQLite."""

    if not DATABASE_URL.startswith(("postgresql", "postgres")):
        raise RuntimeError(
            "BIDOPS_DATABASE_URL must point to PostgreSQL 17; live SQLite is forbidden"
        )
