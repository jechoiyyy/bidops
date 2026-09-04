"""core가 소유하는 선언적 모델과 네 모듈이 함께 쓰는 선언 도구.

core는 도메인 모듈을 알지 못하므로 여기에는 감사 이벤트와 idempotency 기록
두 테이블(명세 §5.1)과, 세 도메인 모듈이 공유하는 선언 도구(``Base``·
``AwareDateTime``·``JSONB_COMPAT``·``_fk``·``utc_now`` 등)만 둔다.

선언 metadata는 local table key를 쓴다. 합성 FK 대상이 연결 이전에 모두
풀리도록 한 것이며, Alembic이 모든 table을 유일한 PostgreSQL ``bidops``
schema에 명시적으로 묶는다.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


# PostgreSQL is authoritative and receives JSONB; explicitly-created SQLite
# test engines use the JSON implementation so legacy compatibility tests do
# not require a PostgreSQL compiler.
JSONB_COMPAT = JSONB().with_variant(JSON(), "sqlite")


# Nullable JSON fields in the T-23 lineage use SQL NULL for an absent value;
# PostgreSQL JSONB and SQLite JSON otherwise encode Python ``None`` as the JSON
# literal ``null``, which would violate the state checks that distinguish an
# absent locator/result from an actual JSON value.
JSONB_NULL_COMPAT = JSONB(none_as_null=True).with_variant(
    JSON(none_as_null=True), "sqlite"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def app_uuid() -> uuid_module.UUID:
    """Application-side UUID default; never a PostgreSQL extension call."""

    return uuid_module.uuid4()


def _table(name: str) -> str:
    # The declarative metadata intentionally uses local table keys so all
    # composite FK targets resolve before a connection exists. Alembic binds
    # every table explicitly to the sole PostgreSQL ``bidops`` schema.
    return name


def _fk(name: str, *, ondelete: str | None = None) -> ForeignKey:
    return ForeignKey(_table(name), ondelete=ondelete)


class AwareDateTime(TypeDecorator[datetime]):
    """Normalize application timestamps to UTC while supporting SQLite tests."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _uuid_column(*, nullable: bool = False, primary_key: bool = False):
    return mapped_column(Uuid(as_uuid=True), default=app_uuid, nullable=nullable, primary_key=primary_key)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (UniqueConstraint("claimed_name", "operation", "aggregate_type", "aggregate_id", "request_id", name="uq_idempotency_scope"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_snapshot: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint("actor_kind IN ('human','system')", name="ck_audit_event_actor_kind"),
        CheckConstraint("actor_kind = 'system' OR (claimed_name IS NOT NULL AND length(trim(claimed_name)) > 0)", name="ck_audit_event_claimed_name"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    claimed_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_metadata: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


# ``0001_lean_v1_postgresql``이 만드는 Lean v1 새 테이블 중 core 몫이다.
# 나머지 23개는 deep_review가 ``DEEP_REVIEW_LEAN_V1_TABLES``로 갖고 있고,
# 합집합은 그 revision과 테스트가 조립한다 (명세 §5.1).
CORE_LEAN_V1_TABLES = ("idempotency_record", "audit_event")
