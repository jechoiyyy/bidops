"""SQLAlchemy models for the BidOps Admin data model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-managed timestamps."""

    return datetime.now(timezone.utc)


class AwareDateTime(TypeDecorator[datetime]):
    """SQLite-compatible timezone-aware datetime.

    SQLite does not retain the timezone flag of its ``DATETIME`` affinity on
    its own.  Values are normalized to UTC before binding and naive values
    returned by SQLite are explicitly marked as UTC on the way out.
    """

    impl = DateTime
    cache_ok = True
    timezone = True

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
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Run(Base):
    __tablename__ = "run"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, nullable=False
    )
    screening_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL"), nullable=True
    )
    counts_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)

    notices: Mapped[list["Notice"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    warnings: Mapped[list["IngestWarning"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class Notice(Base):
    __tablename__ = "notice"
    __table_args__ = (
        Index(
            "ix_notice_run_collection_sample",
            "run_id",
            "collection_bucket",
            "sample_role",
        ),
        Index("ix_notice_notice_key", "notice_key"),
        Index("ix_notice_deadline_at", "deadline_at"),
        # 회차 안에서 같은 공고가 중복 적재되지 않도록 막는다. Step 2의 재적재
        # 멱등성은 이 제약을 upsert 대상으로 삼아 보장한다.
        UniqueConstraint("run_id", "notice_key", name="uq_notice_run_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    notice_key: Mapped[str] = mapped_column(String(255), nullable=False)
    bid_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_ord: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        AwareDateTime(), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estimated_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_stratum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    collection_bucket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    procurement_class_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    region_limit_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    lifecycle_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    qualification_flags_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    focus_matches_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    performance_matches_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    performance_top_score: Mapped[float | None] = mapped_column(nullable=True)
    candidate_sources_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    unknown_fields_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    raw_source: Mapped[Any] = mapped_column(JSON, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="notices")
    judgment: Mapped["Judgment | None"] = relationship(
        back_populates="notice",
        uselist=False,
        cascade="all, delete-orphan",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="notice",
        cascade="all, delete-orphan",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="notice",
        cascade="all, delete-orphan",
    )


class Judgment(Base):
    __tablename__ = "judgment"
    __table_args__ = (UniqueConstraint("notice_pk", name="uq_judgment_notice_pk"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_pk: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    readiness: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_focus: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exclusion_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    notice: Mapped["Notice"] = relationship(back_populates="judgment")
    perspectives: Mapped[list["Perspective"]] = relationship(
        back_populates="judgment",
        cascade="all, delete-orphan",
    )
    counterarguments: Mapped[list["Counterargument"]] = relationship(
        back_populates="judgment",
        cascade="all, delete-orphan",
    )
    verification_items: Mapped[list["VerificationItem"]] = relationship(
        back_populates="judgment",
        cascade="all, delete-orphan",
    )
    matched_performances: Mapped[list["MatchedPerformance"]] = relationship(
        back_populates="judgment",
        cascade="all, delete-orphan",
    )


class Perspective(Base):
    __tablename__ = "perspective"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    judgment: Mapped["Judgment"] = relationship(back_populates="perspectives")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="perspective",
        cascade="all, delete-orphan",
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perspective_id: Mapped[int] = mapped_column(
        ForeignKey("perspective.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fact: Mapped[str | None] = mapped_column(Text, nullable=True)

    perspective: Mapped["Perspective"] = relationship(back_populates="evidence")


class Counterargument(Base):
    __tablename__ = "counterargument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    judgment: Mapped["Judgment"] = relationship(back_populates="counterarguments")


class VerificationItem(Base):
    __tablename__ = "verification_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False
    )
    item: Mapped[str | None] = mapped_column(Text, nullable=True)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    judgment: Mapped["Judgment"] = relationship(back_populates="verification_items")


class MatchedPerformance(Base):
    __tablename__ = "matched_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismatch_or_limit: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    judgment: Mapped["Judgment"] = relationship(back_populates="matched_performances")


class Attachment(Base):
    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_pk: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stored_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, nullable=False
    )

    notice: Mapped["Notice"] = relationship(back_populates="attachments")


class AgencyPortal(Base):
    __tablename__ = "agency_portal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    system_name: Mapped[str] = mapped_column(String(255), nullable=False)
    search_url_template: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Review(Base):
    __tablename__ = "review"
    __table_args__ = (
        UniqueConstraint("notice_pk", "run_id", name="uq_review_notice_run"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_pk: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    disposition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_judgment_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    corrected_readiness: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weakest_perspective: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    notice: Mapped["Notice"] = relationship(back_populates="reviews")
    run: Mapped["Run"] = relationship(back_populates="reviews")
    answers: Mapped[list["VerificationAnswer"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )


class VerificationAnswer(Base):
    __tablename__ = "verification_answer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("review.id", ondelete="CASCADE"), nullable=False
    )
    item: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    review: Mapped["Review"] = relationship(back_populates="answers")


class IngestWarning(Base):
    __tablename__ = "ingest_warning"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[Any] = mapped_column(JSON, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="warnings")
