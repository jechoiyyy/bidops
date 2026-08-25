"""SQLAlchemy models for the BidOps Admin data model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    text,
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


# Screening runtime -------------------------------------------------------
#
# These tables intentionally use strings plus database CHECK constraints for
# the domain vocabulary.  A Python enum alone would not protect a SQLite
# database written by an operational tool or a future worker.

class ScreeningExecution(Base):
    __tablename__ = "screening_execution"
    __table_args__ = (
        CheckConstraint(
            "length(execution_id) = 36 AND substr(execution_id, 1, 4) = 'scr-' "
            "AND substr(execution_id, 5) NOT GLOB '*[^0-9a-f]*'",
            name="ck_screening_execution_id",
        ),
        CheckConstraint(
            "trigger IN ('cli_single', 'manual_run', 'quality_gate', 'schedule')",
            name="ck_screening_execution_trigger",
        ),
        CheckConstraint(
            "scope IN ('single_notice', 'full_run', 'quality_sample')",
            name="ck_screening_execution_scope",
        ),
        CheckConstraint(
            "status IN ('대기', '실행 중', '중지 요청', '성공', '부분 성공', '실패', '중단됨')",
            name="ck_screening_execution_status",
        ),
        CheckConstraint("((scope = 'single_notice' AND notice_pk IS NOT NULL AND notice_id IS NOT NULL) OR (scope <> 'single_notice' AND notice_pk IS NULL AND notice_id IS NULL))", name="ck_screening_execution_single_notice"),
        CheckConstraint(
            "((status IN ('실행 중', '중지 요청') AND active_slot = 1) "
            "OR (status NOT IN ('실행 중', '중지 요청') AND active_slot IS NULL))",
            name="ck_screening_execution_active_slot",
        ),
        CheckConstraint(
            "((status IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NOT NULL) OR (status NOT IN ('성공', '부분 성공', '실패', '중단됨') AND finished_at IS NULL))",
            name="ck_screening_execution_terminal",
        ),
        CheckConstraint("stop_reason IS NULL OR stop_reason IN ('user_requested', 'process_interrupted')", name="ck_screening_execution_stop_reason"),
        CheckConstraint("queued_at IS NOT NULL", name="ck_screening_execution_queued_at"),
        CheckConstraint("candidate_count >= 0", name="ck_screening_execution_candidate_count"),
        CheckConstraint("completed_count >= 0", name="ck_screening_execution_completed_count"),
        CheckConstraint("failure_count >= 0", name="ck_screening_execution_failure_count"),
        CheckConstraint("length(trim(requested_by)) > 0", name="ck_screening_execution_requested_by"),
        CheckConstraint("stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0", name="ck_screening_execution_stop_requested_by"),
        CheckConstraint("length(input_artifact_digest) = 64 AND input_artifact_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_input_artifact_digest"),
        CheckConstraint("length(trim(input_artifact_path)) > 0", name="ck_screening_execution_input_artifact_nonempty"),
        CheckConstraint("length(trim(artifact_dir)) > 0", name="ck_screening_execution_artifact_dir_nonempty"),
        CheckConstraint("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_model_digest"),
        CheckConstraint("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_execution_profile_digest"),
        CheckConstraint("length(trim(input_artifact_path)) > 0 AND input_artifact_path NOT LIKE '/%' AND input_artifact_path NOT LIKE '%\\%' AND input_artifact_path <> '..' AND input_artifact_path NOT LIKE '../%' AND input_artifact_path NOT LIKE '%/../%' AND input_artifact_path NOT LIKE '%/..'", name="ck_screening_execution_input_artifact_path"),
        CheckConstraint("length(trim(artifact_dir)) > 0 AND artifact_dir NOT LIKE '/%' AND artifact_dir NOT LIKE '%\\%' AND artifact_dir <> '..' AND artifact_dir NOT LIKE '../%' AND artifact_dir NOT LIKE '%/../%' AND artifact_dir NOT LIKE '%/..'", name="ck_screening_execution_artifact_dir"),
        Index("uq_screening_execution_active_slot", "active_slot", unique=True, sqlite_where=text("active_slot IS NOT NULL")),
    )

    queue_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("run.id", ondelete="RESTRICT"), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    notice_pk: Mapped[int | None] = mapped_column(
        ForeignKey("notice.id", ondelete="RESTRICT"), nullable=True
    )
    notice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="대기")
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    company_profile_version: Mapped[str] = mapped_column(ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=False)
    company_profile_digest: Mapped[str] = mapped_column(ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=False)
    input_artifact_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    input_artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_dir: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    current_notice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stop_requested_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    stop_requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    published_run_id: Mapped[str | None] = mapped_column(ForeignKey("run.id", ondelete="RESTRICT"), unique=True, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScreeningAttempt(Base):
    __tablename__ = "screening_attempt"
    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="ck_screening_attempt_no"),
        CheckConstraint(
            "stage IN ('기술 적합성', '실적 정합성', '공공 SI 적합성', '사업성·자격 제약', '전략 부합', 'counterargument', 'synthesis', 'carried_over_validation')",
            name="ck_screening_attempt_stage",
        ),
        CheckConstraint("status IN ('success', 'failure')", name="ck_screening_attempt_status"),
        CheckConstraint(
            "failure_type IS NULL OR failure_type IN ('timeout', 'truncated_output', 'schema_violation', 'evidence_missing', 'counterargument_repetition')",
            name="ck_screening_attempt_failure_type",
        ),
        CheckConstraint("prompt_eval_count IS NULL OR prompt_eval_count >= 0", name="ck_screening_attempt_prompt_eval_count"),
        CheckConstraint("eval_count IS NULL OR eval_count >= 0", name="ck_screening_attempt_eval_count"),
        CheckConstraint("prompt_eval_duration_ns IS NULL OR prompt_eval_duration_ns >= 0", name="ck_screening_attempt_prompt_eval_duration_ns"),
        CheckConstraint("eval_duration_ns IS NULL OR eval_duration_ns >= 0", name="ck_screening_attempt_eval_duration_ns"),
        CheckConstraint("load_duration_ns IS NULL OR load_duration_ns >= 0", name="ck_screening_attempt_load_duration_ns"),
        CheckConstraint("total_duration_ns IS NULL OR total_duration_ns >= 0", name="ck_screening_attempt_total_duration_ns"),
        CheckConstraint("finished_at >= started_at", name="ck_screening_attempt_finished_after_started"),
        CheckConstraint("response_artifact_path IS NULL OR (response_artifact_path NOT LIKE '/%' AND response_artifact_path NOT LIKE '%\\%' AND response_artifact_path <> '..' AND response_artifact_path NOT LIKE '../%' AND response_artifact_path NOT LIKE '%/../%' AND response_artifact_path NOT LIKE '%/..')", name="ck_screening_attempt_response_artifact_path"),
        CheckConstraint("((status = 'success' AND response_artifact_path IS NOT NULL AND failure_type IS NULL) OR (status = 'failure' AND failure_type IS NOT NULL))", name="ck_screening_attempt_success_artifact"),
        UniqueConstraint("execution_id", "notice_id", "stage", "attempt_no", name="uq_screening_attempt_number"),
        UniqueConstraint("span_id", name="uq_screening_attempt_span"),
    )

    attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("screening_execution.execution_id", ondelete="CASCADE"), nullable=False)
    notice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    span_id: Mapped[str] = mapped_column(String(255), nullable=False)
    done_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_eval_duration_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_duration_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_duration_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    response_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompanyProfileSnapshot(Base):
    __tablename__ = "company_profile_snapshot"
    __table_args__ = (
        CheckConstraint("length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'", name="ck_profile_digest"),
        CheckConstraint("source_kind IN ('working_tree', 'git_blob')", name="ck_profile_source_kind"),
        CheckConstraint("length(trim(source_ref)) > 0", name="ck_profile_source_ref"),
        CheckConstraint("length(trim(artifact_path)) > 0", name="ck_profile_artifact_path_nonempty"),
        CheckConstraint("version = 'company-profile.sha256:' || digest", name="ck_profile_version_digest"),
        CheckConstraint("length(trim(artifact_path)) > 0 AND artifact_path NOT LIKE '/%' AND artifact_path NOT LIKE '%\\%' AND artifact_path <> '..' AND artifact_path NOT LIKE '../%' AND artifact_path NOT LIKE '%/../%' AND artifact_path NOT LIKE '%/..'", name="ck_profile_artifact_path"),
    )

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)


class QualityGate(Base):
    __tablename__ = "quality_gate"
    __table_args__ = (
        CheckConstraint("length(gate_id) = 37 AND substr(gate_id, 1, 5) = 'gate-' AND substr(gate_id, 6) NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_id"),
        CheckConstraint("purpose IN ('model_comparison', 'operational_approval')", name="ck_quality_gate_purpose"),
        CheckConstraint("execution_status IN ('대기', '실행 중', '완료', '실패', '중단됨')", name="ck_quality_gate_execution_status"),
        CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_result_status"),
        CheckConstraint("pass_a_execution_id <> pass_b_execution_id", name="ck_quality_gate_distinct_executions"),
        CheckConstraint("length(trim(created_by)) > 0", name="ck_quality_gate_created_by"),
        CheckConstraint("length(sample_artifact_digest) = 64 AND sample_artifact_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_sample_digest"),
        CheckConstraint("length(baseline_decisions_digest) = 64 AND baseline_decisions_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_baseline_decision_digest"),
        CheckConstraint("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_model_digest"),
        CheckConstraint("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_profile_digest"),
        CheckConstraint("json_valid(metrics_json) AND json_type(metrics_json) = 'object'", name="ck_quality_gate_metrics_json"),
        CheckConstraint("json_valid(reasons_json) AND json_type(reasons_json) = 'array'", name="ck_quality_gate_reasons_json"),
        CheckConstraint("((execution_status IN ('완료', '실패', '중단됨') AND completed_at IS NOT NULL) OR (execution_status NOT IN ('완료', '실패', '중단됨') AND completed_at IS NULL))", name="ck_quality_gate_completed"),
    )

    gate_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_run_id: Mapped[str] = mapped_column(ForeignKey("run.id", ondelete="RESTRICT"), nullable=False)
    sample_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    sample_artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_decisions_path: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_decisions_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    company_profile_version: Mapped[str] = mapped_column(ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=False)
    company_profile_digest: Mapped[str] = mapped_column(ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=False)
    pass_a_execution_id: Mapped[str] = mapped_column(ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), unique=True, nullable=False)
    pass_b_execution_id: Mapped[str] = mapped_column(ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    metrics_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    reasons_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class QualityGateEvaluation(Base):
    __tablename__ = "quality_gate_evaluation"
    __table_args__ = (
        CheckConstraint("length(evaluation_id) = 41 AND substr(evaluation_id, 1, 9) = 'gateeval-' AND substr(evaluation_id, 10) NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_evaluation_id"),
        CheckConstraint("revision >= 1", name="ck_quality_gate_evaluation_revision"),
        CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_evaluation_result_status"),
        CheckConstraint("valid_review_count >= 0", name="ck_quality_gate_evaluation_valid_review_count"),
        CheckConstraint("distinct_notice_review_count >= 0", name="ck_quality_gate_evaluation_distinct_notice_review_count"),
        CheckConstraint("json_valid(metrics_json) AND json_type(metrics_json) = 'object'", name="ck_quality_gate_evaluation_metrics_json"),
        CheckConstraint("json_valid(reasons_json) AND json_type(reasons_json) = 'array'", name="ck_quality_gate_evaluation_reasons_json"),
        UniqueConstraint("gate_id", "revision", name="uq_quality_gate_evaluation_revision"),
    )

    evaluation_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    gate_id: Mapped[str] = mapped_column(ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    metrics_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    reasons_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    valid_review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_notice_review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)


class ScreeningPolicy(Base):
    __tablename__ = "screening_policy"
    __table_args__ = (
        CheckConstraint("schema_version = 'bidops.screening-policy.v1'", name="ck_screening_policy_schema_version"),
        CheckConstraint("status IN ('draft', 'activation_candidate', 'active')", name="ck_screening_policy_status"),
        CheckConstraint("length(trim(prompt_version)) > 0", name="ck_screening_policy_prompt_version"),
        CheckConstraint("length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'", name="ck_screening_policy_content_digest"),
        CheckConstraint("((status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND quality_gate_result_id IS NOT NULL) OR (status <> 'active' AND active_slot IS NULL))", name="ck_screening_policy_active"),
        CheckConstraint("created_by IS NULL OR length(trim(created_by)) > 0", name="ck_screening_policy_created_by"),
        CheckConstraint("activated_by IS NULL OR length(trim(activated_by)) > 0", name="ck_screening_policy_activated_by"),
        CheckConstraint("json_valid(perspective_prompts_json) AND json_type(perspective_prompts_json) = 'object'", name="ck_screening_policy_perspective_json"),
        CheckConstraint("json_valid(counterargument_prompt_json) AND json_type(counterargument_prompt_json) = 'object'", name="ck_screening_policy_counterargument_json"),
        CheckConstraint("json_valid(synthesis_prompt_json) AND json_type(synthesis_prompt_json) = 'object'", name="ck_screening_policy_synthesis_json"),
        CheckConstraint("json_valid(candidate_selection_json) AND json_type(candidate_selection_json) = 'object'", name="ck_screening_policy_candidate_selection_json"),
        CheckConstraint("json_valid(thresholds_json) AND json_type(thresholds_json) = 'object'", name="ck_screening_policy_thresholds_json"),
        Index("uq_screening_policy_active_slot", "active_slot", unique=True, sqlite_where=text("active_slot IS NOT NULL")),
    )

    policy_version: Mapped[str] = mapped_column(String(255), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="bidops.screening-policy.v1")
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perspective_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    counterargument_prompt_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    synthesis_prompt_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    candidate_selection_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    thresholds_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_gate_result_id: Mapped[str | None] = mapped_column(ForeignKey("quality_gate_evaluation.evaluation_id", ondelete="RESTRICT"), nullable=True)


class QualityGateReview(Base):
    __tablename__ = "quality_gate_review"
    __table_args__ = (
        CheckConstraint("evidence_judgment IN ('동의', '근거 부족', '판단 보류')", name="ck_quality_gate_review_judgment"),
        CheckConstraint("length(trim(reviewer)) > 0", name="ck_quality_gate_review_reviewer"),
        CheckConstraint("length(decision_digest) = 64 AND decision_digest NOT GLOB '*[^0-9a-f]*'", name="ck_quality_gate_review_decision_digest"),
        UniqueConstraint("gate_id", "notice_id", "reviewer", name="uq_quality_gate_review_notice_reviewer"),
    )

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gate_id: Mapped[str] = mapped_column(ForeignKey("quality_gate.gate_id", ondelete="CASCADE"), nullable=False)
    execution_id: Mapped[str] = mapped_column(ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    notice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_judgment: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now, onupdate=utc_now)


class ScheduleSetting(Base):
    __tablename__ = "schedule_setting"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_schedule_setting_singleton"),
        CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_setting_timezone"),
        CheckConstraint("daily_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(daily_time, 1, 2) <= '23'", name="ck_schedule_setting_daily_time"),
        CheckConstraint("weekly_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(weekly_time, 1, 2) <= '23'", name="ck_schedule_setting_weekly_time"),
        CheckConstraint("updated_by IS NULL OR length(trim(updated_by)) > 0", name="ck_schedule_setting_updated_by"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(32), nullable=False, default="Asia/Seoul")
    daily_time: Mapped[str] = mapped_column(String(5), nullable=False, default="02:00")
    weekly_time: Mapped[str] = mapped_column(String(5), nullable=False, default="06:00")
    prespec_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system:migration")


class ScheduleReservation(Base):
    __tablename__ = "schedule_reservation"
    __table_args__ = (
        CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_reservation_job_kind"),
        CheckConstraint("window_from <= window_to", name="ck_schedule_reservation_window"),
        CheckConstraint("timezone = 'Asia/Seoul'", name="ck_schedule_reservation_timezone"),
    )

    run_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    window_from: Mapped[date] = mapped_column(Date, nullable=False)
    window_to: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(32), nullable=False, default="Asia/Seoul")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)


class ScheduleExecution(Base):
    __tablename__ = "schedule_execution"
    __table_args__ = (
        CheckConstraint("length(execution_id) = 38 AND substr(execution_id, 1, 6) = 'sched-' AND substr(execution_id, 7) NOT GLOB '*[^0-9a-f]*'", name="ck_schedule_execution_id"),
        CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_execution_job_kind"),
        CheckConstraint("trigger IN ('schedule', 'manual')", name="ck_schedule_execution_trigger"),
        CheckConstraint("status IN ('예약', '실행 중', '성공', '부분 성공', '실패', '건너뜀')", name="ck_schedule_execution_status"),
        CheckConstraint("NOT (duplicate_of_execution_id IS NOT NULL AND recovery_of_execution_id IS NOT NULL)", name="ck_schedule_execution_recovery_one"),
        CheckConstraint("length(trim(requested_by)) > 0", name="ck_schedule_execution_requested_by"),
        CheckConstraint("((status = '건너뜀' AND skip_reason IS NOT NULL) OR (status <> '건너뜀' AND skip_reason IS NULL))", name="ck_schedule_execution_skip_reason"),
        CheckConstraint("candidate_count IS NULL OR candidate_count >= 0", name="ck_schedule_execution_candidate_count"),
        CheckConstraint("result_count IS NULL OR result_count >= 0", name="ck_schedule_execution_result_count"),
        CheckConstraint("failure_count IS NULL OR failure_count >= 0", name="ck_schedule_execution_failure_count"),
    )

    execution_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    run_key: Mapped[str] = mapped_column(
        ForeignKey("schedule_reservation.run_key", ondelete="RESTRICT"), nullable=False
    )
    job_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="예약")
    duplicate_of_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("schedule_execution.execution_id", ondelete="RESTRICT"), nullable=True
    )
    recovery_of_execution_id: Mapped[str | None] = mapped_column(ForeignKey("schedule_execution.execution_id", ondelete="RESTRICT"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("run.id", ondelete="RESTRICT"), nullable=True)
    screening_execution_id: Mapped[str | None] = mapped_column(ForeignKey("screening_execution.execution_id", ondelete="RESTRICT"), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partial_artifact: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_version: Mapped[str | None] = mapped_column(ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company_profile_version: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=True)
    company_profile_digest: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=True)


class AlwaysOnState(Base):
    __tablename__ = "always_on_state"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_always_on_singleton"),
        CheckConstraint("updated_by IS NULL OR length(trim(updated_by)) > 0", name="ck_always_on_updated_by"),
        CheckConstraint("((enabled = 0) OR (quality_gate_result_id IS NOT NULL AND policy_version IS NOT NULL AND model_name IS NOT NULL AND model_digest IS NOT NULL AND prompt_version IS NOT NULL AND company_profile_version IS NOT NULL AND company_profile_digest IS NOT NULL))", name="ck_always_on_enabled_metadata"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_gate_result_id: Mapped[str | None] = mapped_column(ForeignKey("quality_gate_evaluation.evaluation_id", ondelete="RESTRICT"), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(ForeignKey("screening_policy.policy_version", ondelete="RESTRICT"), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_profile_version: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=True)
    company_profile_digest: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system:migration")


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint("length(event_id) = 38 AND substr(event_id, 1, 6) = 'audit-' AND substr(event_id, 7) NOT GLOB '*[^0-9a-f]*'", name="ck_audit_event_id"),
        CheckConstraint("length(trim(event_type)) > 0", name="ck_audit_event_type"),
        CheckConstraint("length(trim(actor)) > 0", name="ck_audit_event_actor"),
        CheckConstraint("length(trim(target_type)) > 0", name="ck_audit_event_target_type"),
        CheckConstraint("length(trim(target_id)) > 0", name="ck_audit_event_target_id"),
        CheckConstraint("json_valid(details_json)", name="ck_audit_event_details_json"),
    )

    event_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    details_json: Mapped[Any] = mapped_column(JSON, nullable=False)
