"""SQLAlchemy engine, declarative base, sessions, and DB initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
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

    target = bind or engine
    Base.metadata.create_all(bind=target)
