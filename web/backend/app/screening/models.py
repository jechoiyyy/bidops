"""screening이 소유하는 선언적 모델 (명세 §5.1의 28개 테이블).

C-1 공고 판정과 그 사람 리뷰, 판정 실행 런타임, 품질 게이트, 정책, 스케줄,
프로필 snapshot, C-2 발주계획 선별이 여기 있다.

``Notice``·``Run``을 향한 relationship은 소유 모듈인 screening이 단방향으로
선언한다. lifecycle 모델은 반대 방향을 갖지 않으므로 screening을 import하지
않아도 lifecycle의 mapper 구성이 성공한다 (명세 §4).
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, synonym

from ..core.db import Base
from ..core.generation_config import GenerationConfig
from ..core.models import AwareDateTime, JSONB_COMPAT, _fk, _uuid_column, utc_now
from ..core.sql_dialect import DualSQL, dual
# 판정·리뷰가 가리키는 lifecycle 모델. 읽기·join 방향이며 §4가 허용한다.
# import 자체가 relationship 문자열("Notice")의 등록도 보장한다.
from ..lifecycle.models import Notice, Run  # noqa: F401


_DEFAULT_GENERATION_CONFIG = GenerationConfig()


_DEFAULT_GENERATION_CONFIG_VALUE = _DEFAULT_GENERATION_CONFIG.canonical_value()


_DEFAULT_GENERATION_CONFIG_DIGEST = _DEFAULT_GENERATION_CONFIG.digest()


def _json_server_default(value: str) -> str:
    # SQLAlchemy quotes string server defaults itself. Passing raw JSON through
    # ``sa.text`` makes tokens such as ``:16384`` and ``:false`` look like bind
    # parameters in some SQLAlchemy versions. This keeps SQLite bytes exact.
    return value


_DEFAULT_GENERATION_CONFIG_SERVER_DEFAULT = _json_server_default(_DEFAULT_GENERATION_CONFIG.canonical_json())


class Judgment(Base):
    __tablename__ = "judgment"
    __table_args__ = (UniqueConstraint("notice_id", name="uq_judgment_notice_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        _fk("notice.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    readiness: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_focus: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exclusion_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    notice_pk = synonym("notice_id")
    notice: Mapped["Notice"] = relationship()
    perspectives: Mapped[list["Perspective"]] = relationship(back_populates="judgment", cascade="all, delete-orphan")
    counterarguments: Mapped[list["Counterargument"]] = relationship(back_populates="judgment", cascade="all, delete-orphan")
    verification_items: Mapped[list["VerificationItem"]] = relationship(back_populates="judgment", cascade="all, delete-orphan")
    matched_performances: Mapped[list["MatchedPerformance"]] = relationship(back_populates="judgment", cascade="all, delete-orphan")


class JudgmentRevision(Base):
    """Immutable, notice-scoped snapshot of the judgment projection."""

    __tablename__ = "judgment_revision"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_judgment_revision_sequence"),
        CheckConstraint(
            "source_kind IN ('runtime', 'legacy_import', 'carry_over')",
            name="ck_judgment_revision_source_kind",
        ),
        CheckConstraint(
            "((source_kind = 'runtime' AND run_id IS NOT NULL "
            "AND recording_execution_id IS NOT NULL AND source_revision_id IS NULL) OR "
            "(source_kind = 'carry_over' AND run_id IS NOT NULL "
            "AND recording_execution_id IS NOT NULL AND source_revision_id IS NOT NULL) OR "
            "(source_kind = 'legacy_import' AND recording_execution_id IS NULL "
            "AND source_revision_id IS NULL))",
            name="ck_judgment_revision_source_lineage",
        ),
        CheckConstraint(
            "source_revision_id IS NULL OR source_revision_id <> id",
            name="ck_judgment_revision_parent_not_self",
        ),
        CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_judgment_revision_payload_schema_nonblank",
        ),
        CheckConstraint(
            dual(
                "json_valid(payload_jsonb) AND json_type(payload_jsonb) = 'object'"
            ),
            name="ck_judgment_revision_payload_object",
        ),
        CheckConstraint(
            dual(
                "length(payload_sha256) = 64 "
                "AND payload_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_judgment_revision_payload_sha256",
        ),
        UniqueConstraint(
            "notice_id", "sequence", name="uq_judgment_revision_notice_sequence"
        ),
        UniqueConstraint(
            "notice_id", "id", name="uq_judgment_revision_notice_id"
        ),
        ForeignKeyConstraint(
            ["notice_id", "run_id"],
            ["notice_observation.notice_id", "notice_observation.run_id"],
            name="fk_judgment_revision_observation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["notice_id", "source_revision_id"],
            ["judgment_revision.notice_id", "judgment_revision.id"],
            name="fk_judgment_revision_parent_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_judgment_revision_execution_notice",
            "recording_execution_id",
            "notice_id",
            unique=True,
            sqlite_where=text("recording_execution_id IS NOT NULL"),
            postgresql_where=text("recording_execution_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        _fk("notice.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    recording_execution_id: Mapped[str | None] = mapped_column(
        _fk("screening_execution.execution_id", ondelete="RESTRICT"), nullable=True
    )
    source_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    notice: Mapped["Notice"] = relationship(foreign_keys=[notice_id])
    run: Mapped["Run | None"] = relationship(
        primaryjoin=lambda: foreign(JudgmentRevision.run_id) == Run.id,
        viewonly=True,
    )
    recording_execution: Mapped["ScreeningExecution | None"] = relationship(
        back_populates="recorded_judgment_revisions",
        foreign_keys=[recording_execution_id],
    )
    source_revision: Mapped["JudgmentRevision | None"] = relationship(
        remote_side=[notice_id, id],
        foreign_keys=[notice_id, source_revision_id],
        back_populates="derived_revisions",
        viewonly=True,
    )
    derived_revisions: Mapped[list["JudgmentRevision"]] = relationship(
        foreign_keys=[notice_id, source_revision_id],
        back_populates="source_revision",
        viewonly=True,
    )
    review_revisions: Mapped[list["ReviewRevision"]] = relationship(
        back_populates="judgment_revision", viewonly=True
    )


class Perspective(Base):
    __tablename__ = "perspective"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(_fk("judgment.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    judgment: Mapped["Judgment"] = relationship(back_populates="perspectives")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="perspective", cascade="all, delete-orphan")


class Evidence(Base):
    """Legacy screening evidence; canonical PostgreSQL table name."""

    __tablename__ = "screening_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perspective_id: Mapped[int] = mapped_column(_fk("perspective.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fact: Mapped[str | None] = mapped_column(Text, nullable=True)
    perspective: Mapped["Perspective"] = relationship(back_populates="evidence")


ScreeningEvidence = Evidence


class Counterargument(Base):
    __tablename__ = "counterargument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(_fk("judgment.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    text = synonym("body")
    judgment: Mapped["Judgment"] = relationship(back_populates="counterarguments")


class VerificationItem(Base):
    __tablename__ = "verification_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(_fk("judgment.id", ondelete="CASCADE"), nullable=False)
    item: Mapped[str | None] = mapped_column(Text, nullable=True)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    judgment: Mapped["Judgment"] = relationship(back_populates="verification_items")


class MatchedPerformance(Base):
    __tablename__ = "matched_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(_fk("judgment.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismatch_or_limit: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    judgment: Mapped["Judgment"] = relationship(back_populates="matched_performances")


class Review(Base):
    __tablename__ = "review"
    # A human decision belongs to the cumulative notice.  ``run_id`` is only
    # provenance for the observation in which the decision was written and is
    # nullable, so a composite unique constraint would allow multiple
    # run-less reviews in PostgreSQL.
    __table_args__ = (UniqueConstraint("notice_id", name="uq_review_notice"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        _fk("notice.id", ondelete="CASCADE"), nullable=False
    )
    # A review remains a durable human decision even if the observation run is
    # removed; this is provenance, not ownership.
    run_id: Mapped[str | None] = mapped_column(_fk("run.id", ondelete="SET NULL"), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_judgment_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    corrected_readiness: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weakest_perspective: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_snapshot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, onupdate=utc_now, nullable=False)

    notice_pk = synonym("notice_id")
    reviewer = synonym("reviewer_snapshot")
    notice: Mapped["Notice"] = relationship()
    run: Mapped["Run"] = relationship()
    answers: Mapped[list["VerificationAnswer"]] = relationship(back_populates="review", cascade="all, delete-orphan")


class ReviewRevision(Base):
    """Immutable, notice-scoped snapshot of a human review projection."""

    __tablename__ = "review_revision"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_review_revision_sequence"),
        CheckConstraint(
            "source_kind IN ('human', 'legacy_import')",
            name="ck_review_revision_source_kind",
        ),
        CheckConstraint(
            "source_kind <> 'human' OR run_id IS NOT NULL",
            name="ck_review_revision_human_run",
        ),
        CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_review_revision_payload_schema_nonblank",
        ),
        CheckConstraint(
            dual(
                "json_valid(payload_jsonb) AND json_type(payload_jsonb) = 'object'"
            ),
            name="ck_review_revision_payload_object",
        ),
        CheckConstraint(
            dual(
                "length(payload_sha256) = 64 "
                "AND payload_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_review_revision_payload_sha256",
        ),
        UniqueConstraint(
            "notice_id", "sequence", name="uq_review_revision_notice_sequence"
        ),
        ForeignKeyConstraint(
            ["notice_id", "run_id"],
            ["notice_observation.notice_id", "notice_observation.run_id"],
            name="fk_review_revision_observation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["notice_id", "judgment_revision_id"],
            ["judgment_revision.notice_id", "judgment_revision.id"],
            name="fk_review_revision_judgment_scope",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        _fk("notice.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    judgment_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    notice: Mapped["Notice"] = relationship(foreign_keys=[notice_id])
    run: Mapped["Run | None"] = relationship(
        primaryjoin=lambda: foreign(ReviewRevision.run_id) == Run.id,
        viewonly=True,
    )
    judgment_revision: Mapped["JudgmentRevision | None"] = relationship(
        back_populates="review_revisions",
        foreign_keys=[notice_id, judgment_revision_id],
        viewonly=True,
    )


class VerificationAnswer(Base):
    __tablename__ = "verification_answer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(_fk("review.id", ondelete="CASCADE"), nullable=False)
    item: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    review: Mapped["Review"] = relationship(back_populates="answers")


# Screening runtime -------------------------------------------------------
#
# These tables intentionally use strings plus database CHECK constraints for
# the domain vocabulary.  A Python enum alone would not protect a SQLite
# database written by an operational tool or a future worker.

class ScreeningExecution(Base):
    __tablename__ = "screening_execution"
    __table_args__ = (
        CheckConstraint(
            dual(
                "length(execution_id) = 36 AND substr(execution_id, 1, 4) = 'scr-' "
                "AND substr(execution_id, 5) NOT GLOB '*[^0-9a-f]*'"
            ),
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
        CheckConstraint("candidate_count >= 0 AND completed_count >= 0 AND failure_count >= 0", name="ck_screening_execution_counts"),
        CheckConstraint("length(trim(requested_by)) > 0", name="ck_screening_execution_requested_by"),
        CheckConstraint("stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0", name="ck_screening_execution_stop_requested_by"),
        CheckConstraint("(stop_requested_at IS NULL AND stop_requested_by IS NULL) OR (stop_requested_at IS NOT NULL AND stop_requested_by IS NOT NULL)", name="ck_screening_execution_stop_pair"),
        CheckConstraint("status <> '중지 요청' OR (stop_requested_at IS NOT NULL AND stop_requested_by IS NOT NULL)", name="ck_screening_execution_stop_requested"),
        CheckConstraint("stop_reason <> 'user_requested' OR (stop_requested_at IS NOT NULL AND stop_requested_by IS NOT NULL)", name="ck_screening_execution_user_stop_pair"),
        CheckConstraint("length(trim(source_run_id)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(model_name)) > 0 AND length(trim(company_profile_version)) > 0 AND (notice_id IS NULL OR length(trim(notice_id)) > 0) AND (current_notice_id IS NULL OR length(trim(current_notice_id)) > 0) AND (current_stage IS NULL OR length(trim(current_stage)) > 0) AND (stop_requested_by IS NULL OR length(trim(stop_requested_by)) > 0) AND (error_summary IS NULL OR length(trim(error_summary)) > 0)", name="ck_screening_execution_strings"),
        CheckConstraint(dual("length(input_artifact_digest) = 64 AND input_artifact_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_execution_input_artifact_digest"),
        CheckConstraint("length(trim(input_artifact_path)) > 0", name="ck_screening_execution_input_artifact_nonempty"),
        CheckConstraint("length(trim(artifact_dir)) > 0", name="ck_screening_execution_artifact_dir_nonempty"),
        CheckConstraint(dual("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_execution_model_digest"),
        CheckConstraint(dual("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_execution_profile_digest"),
        CheckConstraint(dual("length(trim(input_artifact_path)) > 0 AND input_artifact_path NOT LIKE '/%' AND input_artifact_path NOT LIKE '%\\%' AND input_artifact_path <> '..' AND input_artifact_path NOT LIKE '../%' AND input_artifact_path NOT LIKE '%/../%' AND input_artifact_path NOT LIKE '%/..'"), name="ck_screening_execution_input_artifact_path"),
        CheckConstraint(dual("length(trim(artifact_dir)) > 0 AND artifact_dir NOT LIKE '/%' AND artifact_dir NOT LIKE '%\\%' AND artifact_dir <> '..' AND artifact_dir NOT LIKE '../%' AND artifact_dir NOT LIKE '%/../%' AND artifact_dir NOT LIKE '%/..'"), name="ck_screening_execution_artifact_dir"),
        CheckConstraint(dual("json_valid(generation_config_json) AND json_type(generation_config_json) = 'object'"), name="ck_screening_execution_generation_config_json"),
        CheckConstraint(dual("length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_execution_generation_config_digest"),
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
    generation_config_json: Mapped[Any] = mapped_column(JSON, nullable=False, default=_DEFAULT_GENERATION_CONFIG_VALUE, server_default=_DEFAULT_GENERATION_CONFIG_SERVER_DEFAULT)
    generation_config_digest: Mapped[str] = mapped_column(String(64), nullable=False, default=_DEFAULT_GENERATION_CONFIG_DIGEST, server_default=_DEFAULT_GENERATION_CONFIG_DIGEST)
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
    recorded_judgment_revisions: Mapped[list["JudgmentRevision"]] = relationship(
        back_populates="recording_execution", passive_deletes="all"
    )


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
        CheckConstraint(dual("generation_config_digest IS NULL OR (length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*')"), name="ck_screening_attempt_generation_config_digest"),
        CheckConstraint("finished_at >= started_at", name="ck_screening_attempt_finished_after_started"),
        CheckConstraint("length(trim(execution_id)) > 0 AND length(trim(notice_id)) > 0 AND length(trim(stage)) > 0 AND length(trim(status)) > 0 AND (failure_type IS NULL OR length(trim(failure_type)) > 0) AND length(trim(trace_id)) > 0 AND length(trim(span_id)) > 0 AND (done_reason IS NULL OR length(trim(done_reason)) > 0) AND (response_artifact_path IS NULL OR length(trim(response_artifact_path)) > 0) AND (error_summary IS NULL OR length(trim(error_summary)) > 0)", name="ck_screening_attempt_strings"),
        CheckConstraint(dual("response_artifact_path IS NULL OR (response_artifact_path NOT LIKE '/%' AND response_artifact_path NOT LIKE '%\\%' AND response_artifact_path <> '..' AND response_artifact_path NOT LIKE '../%' AND response_artifact_path NOT LIKE '%/../%' AND response_artifact_path NOT LIKE '%/..')"), name="ck_screening_attempt_response_artifact_path"),
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
    generation_config_digest: Mapped[str | None] = mapped_column(String(64), nullable=True, default=_DEFAULT_GENERATION_CONFIG_DIGEST, server_default=_DEFAULT_GENERATION_CONFIG_DIGEST)
    num_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_predict: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    response_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompanyProfileSnapshot(Base):
    __tablename__ = "company_profile_snapshot"
    __table_args__ = (
        CheckConstraint(dual("length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'"), name="ck_profile_digest"),
        CheckConstraint("source_kind IN ('working_tree', 'git_blob')", name="ck_profile_source_kind"),
        CheckConstraint(dual("(source_kind = 'working_tree' AND length(trim(source_ref)) > 0 AND source_ref NOT LIKE '/%' AND source_ref NOT LIKE '%' || char(92) || '%' AND source_ref <> '..' AND source_ref NOT LIKE '../%' AND source_ref NOT LIKE '%/../%' AND source_ref NOT LIKE '%/..') OR (source_kind = 'git_blob' AND length(source_ref) = 40 AND source_ref NOT GLOB '*[^0-9a-f]*')"), name="ck_profile_source_ref"),
        CheckConstraint("artifact_path = 'web/data/profile-snapshots/' || digest || '.md'", name="ck_profile_artifact_path_exact"),
        CheckConstraint("version = 'company-profile.sha256:' || digest", name="ck_profile_version_digest"),
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
        CheckConstraint(dual("length(gate_id) = 37 AND substr(gate_id, 1, 5) = 'gate-' AND substr(gate_id, 6) NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_id"),
        CheckConstraint("purpose IN ('model_comparison', 'operational_approval')", name="ck_quality_gate_purpose"),
        CheckConstraint("execution_status IN ('대기', '실행 중', '완료', '실패', '중단됨')", name="ck_quality_gate_execution_status"),
        CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_result_status"),
        CheckConstraint("pass_a_execution_id <> pass_b_execution_id", name="ck_quality_gate_distinct_executions"),
        CheckConstraint("length(trim(created_by)) > 0", name="ck_quality_gate_created_by"),
        CheckConstraint("length(trim(baseline_run_id)) > 0 AND length(trim(sample_artifact_path)) > 0 AND length(trim(baseline_decisions_path)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(model_name)) > 0 AND length(trim(company_profile_version)) > 0 AND length(trim(pass_a_execution_id)) > 0 AND length(trim(pass_b_execution_id)) > 0", name="ck_quality_gate_strings"),
        CheckConstraint(dual("sample_artifact_path NOT LIKE '/%' AND sample_artifact_path NOT LIKE '%' || char(92) || '%' AND sample_artifact_path <> '..' AND sample_artifact_path NOT LIKE '../%' AND sample_artifact_path NOT LIKE '%/../%' AND sample_artifact_path NOT LIKE '%/..'"), name="ck_quality_gate_sample_artifact_path"),
        CheckConstraint(dual("baseline_decisions_path NOT LIKE '/%' AND baseline_decisions_path NOT LIKE '%' || char(92) || '%' AND baseline_decisions_path <> '..' AND baseline_decisions_path NOT LIKE '../%' AND baseline_decisions_path NOT LIKE '%/../%' AND baseline_decisions_path NOT LIKE '%/..'"), name="ck_quality_gate_baseline_decisions_path"),
        CheckConstraint(dual("length(sample_artifact_digest) = 64 AND sample_artifact_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_sample_digest"),
        CheckConstraint(dual("length(baseline_decisions_digest) = 64 AND baseline_decisions_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_baseline_decision_digest"),
        CheckConstraint(dual("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_model_digest"),
        CheckConstraint(dual("json_valid(generation_config_json) AND json_type(generation_config_json) = 'object'"), name="ck_quality_gate_generation_config_json"),
        CheckConstraint(dual("length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_generation_config_digest"),
        CheckConstraint(dual("length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_profile_digest"),
        CheckConstraint(dual("json_valid(metrics_json) AND json_type(metrics_json) = 'object'"), name="ck_quality_gate_metrics_json"),
        CheckConstraint(dual("json_valid(reasons_json) AND json_type(reasons_json) = 'array'"), name="ck_quality_gate_reasons_json"),
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
    generation_config_json: Mapped[Any] = mapped_column(JSON, nullable=False, default=_DEFAULT_GENERATION_CONFIG_VALUE, server_default=_DEFAULT_GENERATION_CONFIG_SERVER_DEFAULT)
    generation_config_digest: Mapped[str] = mapped_column(String(64), nullable=False, default=_DEFAULT_GENERATION_CONFIG_DIGEST, server_default=_DEFAULT_GENERATION_CONFIG_DIGEST)
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
        CheckConstraint(dual("length(evaluation_id) = 41 AND substr(evaluation_id, 1, 9) = 'gateeval-' AND substr(evaluation_id, 10) NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_evaluation_id"),
        CheckConstraint("revision >= 1", name="ck_quality_gate_evaluation_revision"),
        CheckConstraint("result_status IN ('통과', '미달', '미측정', '보류')", name="ck_quality_gate_evaluation_result_status"),
        CheckConstraint("length(trim(gate_id)) > 0", name="ck_quality_gate_evaluation_strings"),
        CheckConstraint("valid_review_count >= 0 AND distinct_notice_review_count >= 0", name="ck_quality_gate_evaluation_counts"),
        CheckConstraint(dual("generation_config_digest IS NULL OR (length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*')"), name="ck_quality_gate_evaluation_generation_config_digest"),
        CheckConstraint(dual("json_valid(metrics_json) AND json_type(metrics_json) = 'object'"), name="ck_quality_gate_evaluation_metrics_json"),
        CheckConstraint(dual("json_valid(reasons_json) AND json_type(reasons_json) = 'array'"), name="ck_quality_gate_evaluation_reasons_json"),
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
    generation_config_digest: Mapped[str | None] = mapped_column(String(64), nullable=False, default=_DEFAULT_GENERATION_CONFIG_DIGEST, server_default=_DEFAULT_GENERATION_CONFIG_DIGEST)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)


class ScreeningPolicy(Base):
    __tablename__ = "screening_policy"
    __table_args__ = (
        CheckConstraint("schema_version = 'bidops.screening-policy.v1'", name="ck_screening_policy_schema_version"),
        CheckConstraint("status IN ('draft', 'activation_candidate', 'active')", name="ck_screening_policy_status"),
        CheckConstraint("length(trim(prompt_version)) > 0 AND length(trim(created_by)) > 0", name="ck_screening_policy_actor_fields"),
        CheckConstraint("length(trim(policy_version)) > 0 AND length(trim(schema_version)) > 0 AND length(trim(status)) > 0", name="ck_screening_policy_strings"),
        CheckConstraint(dual("length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_policy_content_digest"),
        CheckConstraint("((status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND quality_gate_result_id IS NOT NULL) OR (status <> 'active' AND active_slot IS NULL))", name="ck_screening_policy_active"),
        CheckConstraint("activated_by IS NULL OR length(trim(activated_by)) > 0", name="ck_screening_policy_activated_by"),
        CheckConstraint(dual("json_valid(perspective_prompts_json) AND json_type(perspective_prompts_json) = 'object'"), name="ck_screening_policy_perspective_json"),
        CheckConstraint(dual("json_valid(counterargument_prompt_json) AND json_type(counterargument_prompt_json) = 'object'"), name="ck_screening_policy_counterargument_json"),
        CheckConstraint(dual("json_valid(synthesis_prompt_json) AND json_type(synthesis_prompt_json) = 'object'"), name="ck_screening_policy_synthesis_json"),
        CheckConstraint(dual("json_valid(candidate_selection_json) AND json_type(candidate_selection_json) = 'object'"), name="ck_screening_policy_candidate_selection_json"),
        CheckConstraint(dual("json_valid(thresholds_json) AND json_type(thresholds_json) = 'object'"), name="ck_screening_policy_thresholds_json"),
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
        CheckConstraint("length(trim(gate_id)) > 0 AND length(trim(execution_id)) > 0 AND length(trim(notice_id)) > 0 AND length(trim(reviewer)) > 0 AND length(trim(evidence_judgment)) > 0 AND (note IS NULL OR length(trim(note)) > 0)", name="ck_quality_gate_review_strings"),
        CheckConstraint(dual("length(decision_digest) = 64 AND decision_digest NOT GLOB '*[^0-9a-f]*'"), name="ck_quality_gate_review_decision_digest"),
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
        CheckConstraint(dual("daily_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(daily_time, 1, 2) <= '23'"), name="ck_schedule_setting_daily_time"),
        CheckConstraint(dual("weekly_time GLOB '[0-2][0-9]:[0-5][0-9]' AND substr(weekly_time, 1, 2) <= '23'"), name="ck_schedule_setting_weekly_time"),
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
        CheckConstraint("length(trim(run_key)) > 0 AND length(trim(job_kind)) > 0 AND length(trim(timezone)) > 0", name="ck_schedule_reservation_strings"),
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
        CheckConstraint(dual("length(execution_id) = 38 AND substr(execution_id, 1, 6) = 'sched-' AND substr(execution_id, 7) NOT GLOB '*[^0-9a-f]*'"), name="ck_schedule_execution_id"),
        CheckConstraint("job_kind IN ('daily', 'weekly')", name="ck_schedule_execution_job_kind"),
        CheckConstraint("trigger IN ('schedule', 'manual')", name="ck_schedule_execution_trigger"),
        CheckConstraint("status IN ('예약', '실행 중', '성공', '부분 성공', '실패', '건너뜀')", name="ck_schedule_execution_status"),
        CheckConstraint("NOT (duplicate_of_execution_id IS NOT NULL AND recovery_of_execution_id IS NOT NULL)", name="ck_schedule_execution_recovery_one"),
        CheckConstraint("duplicate_of_execution_id IS NULL OR status = '건너뜀'", name="ck_schedule_execution_duplicate_status"),
        CheckConstraint("recovery_of_execution_id IS NULL OR trigger = 'manual'", name="ck_schedule_execution_recovery_trigger"),
        CheckConstraint("trigger <> 'schedule' OR requested_by = 'system:scheduler'", name="ck_schedule_execution_scheduler_actor"),
        CheckConstraint("length(trim(requested_by)) > 0", name="ck_schedule_execution_requested_by"),
        CheckConstraint("length(trim(run_key)) > 0 AND length(trim(job_kind)) > 0 AND length(trim(trigger)) > 0 AND length(trim(status)) > 0 AND (duplicate_of_execution_id IS NULL OR length(trim(duplicate_of_execution_id)) > 0) AND (recovery_of_execution_id IS NULL OR length(trim(recovery_of_execution_id)) > 0) AND (skip_reason IS NULL OR length(trim(skip_reason)) > 0) AND (failure_reason IS NULL OR length(trim(failure_reason)) > 0) AND (policy_version IS NULL OR length(trim(policy_version)) > 0) AND (prompt_version IS NULL OR length(trim(prompt_version)) > 0) AND (model_name IS NULL OR length(trim(model_name)) > 0) AND (company_profile_version IS NULL OR length(trim(company_profile_version)) > 0)", name="ck_schedule_execution_strings"),
        CheckConstraint(dual("(run_id IS NULL OR length(trim(run_id)) > 0) AND (screening_execution_id IS NULL OR length(trim(screening_execution_id)) > 0) AND (model_digest IS NULL OR (length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*')) AND (company_profile_digest IS NULL OR (length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'))"), name="ck_schedule_execution_digests"),
        CheckConstraint(dual("generation_config_digest IS NULL OR (length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*')"), name="ck_schedule_execution_generation_config_digest"),
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
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_profile_version: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.version", ondelete="RESTRICT"), nullable=True)
    company_profile_digest: Mapped[str | None] = mapped_column(ForeignKey("company_profile_snapshot.digest", ondelete="RESTRICT"), nullable=True)
    generation_config_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AlwaysOnState(Base):
    __tablename__ = "always_on_state"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_always_on_singleton"),
        CheckConstraint("updated_by IS NULL OR length(trim(updated_by)) > 0", name="ck_always_on_updated_by"),
        CheckConstraint("(quality_gate_result_id IS NULL OR length(trim(quality_gate_result_id)) > 0) AND (policy_version IS NULL OR length(trim(policy_version)) > 0) AND (model_name IS NULL OR length(trim(model_name)) > 0) AND (prompt_version IS NULL OR length(trim(prompt_version)) > 0) AND (company_profile_version IS NULL OR length(trim(company_profile_version)) > 0)", name="ck_always_on_strings"),
        CheckConstraint(dual("(model_digest IS NULL OR (length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*')) AND (company_profile_digest IS NULL OR (length(company_profile_digest) = 64 AND company_profile_digest NOT GLOB '*[^0-9a-f]*'))"), name="ck_always_on_digests"),
        CheckConstraint(dual("generation_config_digest IS NULL OR (length(generation_config_digest) = 64 AND generation_config_digest NOT GLOB '*[^0-9a-f]*')"), name="ck_always_on_generation_config_digest"),
        CheckConstraint("((NOT enabled) OR (quality_gate_result_id IS NOT NULL AND policy_version IS NOT NULL AND model_name IS NOT NULL AND model_digest IS NOT NULL AND prompt_version IS NOT NULL AND company_profile_version IS NOT NULL AND company_profile_digest IS NOT NULL AND generation_config_digest IS NOT NULL))", name="ck_always_on_enabled_metadata"),
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
    generation_config_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system:migration")


# C-2 order-plan screening -------------------------------------------------
#
# These tables deliberately do not reuse the notice-screening runtime tables
# above.  The C-2 file contract has a different result vocabulary and its
# source/binding snapshot must remain independent of the older workflow.


class OrderPlanScreeningPolicy(Base):
    __tablename__ = "order_plan_screening_policy"
    __table_args__ = (
        UniqueConstraint("policy_version", name="uq_order_plan_screening_policy_version"),
        Index(
            "uq_order_plan_screening_policy_active",
            "active_slot",
            unique=True,
            sqlite_where=text("active_slot IS NOT NULL"),
            postgresql_where=text("active_slot IS NOT NULL"),
        ),
        CheckConstraint(
            "schema_version = 'bidops.order-plan-screening-policy.v1'",
            name="ck_order_plan_screening_policy_schema_version",
        ),
        CheckConstraint(
            "producer = 'phase0-contracts' AND consumer = 'phase1-screening-pipeline'",
            name="ck_order_plan_screening_policy_provenance",
        ),
        CheckConstraint(
            "policy_status IN ('draft','activation_candidate','active','retired')",
            name="ck_order_plan_screening_policy_status",
        ),
        CheckConstraint(
            "decision_scope = 'c2_order_plan_first_pass'",
            name="ck_order_plan_screening_policy_scope",
        ),
        CheckConstraint(
            dual("length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_policy_sha256",
        ),
        CheckConstraint(
            dual("length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_policy_binding_sha256",
        ),
        CheckConstraint(
            DualSQL(
                "json_valid(policy_payload_jsonb) AND json_type(policy_payload_jsonb) = 'object'",
                "jsonb_typeof(policy_payload_jsonb) = 'object'",
            ),
            name="ck_order_plan_screening_policy_payload_object",
        ),
        CheckConstraint(
            DualSQL(
                "json_valid(binding_payload_jsonb) AND json_type(binding_payload_jsonb) = 'object'",
                "jsonb_typeof(binding_payload_jsonb) = 'object'",
            ),
            name="ck_order_plan_screening_policy_binding_object",
        ),
        CheckConstraint(
            "((policy_status = 'active' AND active_slot = 1 AND activated_at IS NOT NULL AND activated_by IS NOT NULL AND length(trim(activated_by)) > 0) OR (policy_status <> 'active' AND active_slot IS NULL))",
            name="ck_order_plan_screening_policy_active_metadata",
        ),
        CheckConstraint(
            "quality_gate_status IS NULL OR quality_gate_status IN ('not_measured','measured','passed','failed')",
            name="ck_order_plan_screening_policy_quality_gate_status",
        ),
        CheckConstraint(
            "length(trim(policy_version)) > 0 AND length(trim(created_by)) > 0",
            name="ck_order_plan_screening_policy_strings",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_payload_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    binding_payload_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_metadata_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    quality_gate_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    activated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    # Small naming aliases keep the storage vocabulary close to the contract
    # wording without creating duplicate columns.
    policy_jsonb = synonym("policy_payload_jsonb")
    binding_jsonb = synonym("binding_payload_jsonb")


class OrderPlanScreeningExecution(Base):
    __tablename__ = "order_plan_screening_execution"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_order_plan_screening_execution_request"),
        Index(
            "uq_order_plan_screening_execution_active",
            "active_slot",
            unique=True,
            sqlite_where=text("active_slot IS NOT NULL"),
            postgresql_where=text("status IN ('실행 중', '중지 요청')"),
        ),
        CheckConstraint(
            "schema_version = 'bidops.order-plan-screening-execution-row.v1'",
            name="ck_order_plan_screening_execution_schema_version",
        ),
        CheckConstraint(
            "producer = 'screening-api' AND consumer = 'screening-worker-and-review-api'",
            name="ck_order_plan_screening_execution_provenance",
        ),
        CheckConstraint(
            "status IN ('대기','실행 중','중지 요청','성공','부분 성공','실패','중단됨')",
            name="ck_order_plan_screening_execution_status",
        ),
        CheckConstraint(
            "((status IN ('실행 중','중지 요청') AND active_slot = 1) OR (status NOT IN ('실행 중','중지 요청') AND active_slot IS NULL))",
            name="ck_order_plan_screening_execution_active_slot",
        ),
        CheckConstraint(
            "((status IN ('성공','부분 성공','실패','중단됨') AND started_at IS NOT NULL AND finished_at IS NOT NULL) OR (status IN ('실행 중','중지 요청') AND started_at IS NOT NULL AND finished_at IS NULL) OR (status = '대기' AND started_at IS NULL AND finished_at IS NULL))",
            name="ck_order_plan_screening_execution_lifecycle",
        ),
        CheckConstraint(
            "population_count >= 1 AND population_sha256 IS NOT NULL",
            name="ck_order_plan_screening_execution_population",
        ),
        CheckConstraint(
            "candidate_count >= 0 AND completed_count >= 0 AND failure_count >= 0 AND stage1_selected_count >= 0 AND stage1_filtered_out_count >= 0 AND stage1_failed_count >= 0 AND stage2_relevant_count >= 0 AND stage2_not_relevant_count >= 0 AND stage2_uncertain_count >= 0 AND stage2_failed_count >= 0 AND stage2_rejected_count >= 0 AND human_review_count >= 0",
            name="ck_order_plan_screening_execution_counts",
        ),
        CheckConstraint(
            dual("length(source_artifact_sha256) = 64 AND source_artifact_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_execution_source_sha256",
        ),
        CheckConstraint(
            dual("length(input_artifact_sha256) = 64 AND input_artifact_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_execution_input_sha256",
        ),
        CheckConstraint(
            dual("length(population_sha256) = 64 AND population_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_execution_population_sha256",
        ),
        CheckConstraint(
            dual("length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_execution_policy_sha256",
        ),
        CheckConstraint(
            dual("length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_execution_binding_sha256",
        ),
        CheckConstraint(
            DualSQL(
                "length(trim(source_artifact_name)) > 0 AND source_artifact_name NOT LIKE '/%' AND source_artifact_name NOT LIKE '%\\%' AND source_artifact_name <> '..' AND source_artifact_name NOT LIKE '../%' AND source_artifact_name NOT LIKE '%/../%' AND source_artifact_name NOT LIKE '%/..'",
                "length(trim(source_artifact_name)) > 0 AND source_artifact_name NOT LIKE '/%' AND position(chr(92) in source_artifact_name) = 0 AND source_artifact_name <> '..' AND source_artifact_name NOT LIKE '../%' AND source_artifact_name NOT LIKE '%/../%' AND source_artifact_name NOT LIKE '%/..'",
            ),
            name="ck_order_plan_screening_execution_source_artifact_name",
        ),
        CheckConstraint(
            "length(trim(requested_by)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(stage1_binding_version)) > 0 AND length(trim(stage2_binding_version)) > 0",
            name="ck_order_plan_screening_execution_strings",
        ),
        CheckConstraint(
            "purpose IN ('operational','gate_measurement')",
            name="ck_order_plan_screening_execution_purpose",
        ),
    )

    execution_id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    request_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    source_run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="RESTRICT"), nullable=False)
    source_artifact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_artifact_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    population_count: Mapped[int] = mapped_column(Integer, nullable=False)
    population_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(_fk("order_plan_screening_policy.policy_version", ondelete="RESTRICT"), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    stage1_binding_version: Mapped[str] = mapped_column(String(128), nullable=False)
    stage1_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    stage2_binding_version: Mapped[str] = mapped_column(String(128), nullable=False)
    stage2_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    partial_artifact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage1_selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage1_filtered_out_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage1_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_relevant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_not_relevant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_uncertain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage2_rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    # 품질 게이트 측정 전용 실행(명세 §4.1)은 누적 투영·워크로드·감사 표본에서 빠진다.
    # INSERT 때만 정하고 DB trigger가 이후 변경을 거부한다.
    purpose: Mapped[str] = mapped_column(
        String(24), nullable=False, default="operational", server_default=text("'operational'")
    )


class OrderPlanScreeningBatchAttempt(Base):
    __tablename__ = "order_plan_screening_batch_attempt"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "batch_id", "attempt_no",
            name="uq_order_plan_screening_batch_attempt_scope",
        ),
        CheckConstraint(
            "schema_version = 'bidops.order-plan-screening-batch-attempt-row.v1'",
            name="ck_order_plan_screening_batch_attempt_schema_version",
        ),
        CheckConstraint(
            "producer = 'screening-worker' AND consumer = 'screening-merge-and-observability'",
            name="ck_order_plan_screening_batch_attempt_provenance",
        ),
        CheckConstraint("sequence >= 1 AND attempt_no BETWEEN 1 AND 2 AND plan_count >= 1", name="ck_order_plan_screening_batch_attempt_numbers"),
        CheckConstraint("attempt_status IN ('running','success','failed','rejected')", name="ck_order_plan_screening_batch_attempt_status"),
        CheckConstraint(
            "((attempt_status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (attempt_status IN ('success','failed','rejected') AND finished_at IS NOT NULL))",
            name="ck_order_plan_screening_batch_attempt_lifecycle",
        ),
        CheckConstraint(
            "failure_type IS NULL OR failure_type IN ('timeout','truncated_output','schema_violation','id_mismatch','model_mismatch','binding_mismatch','payload_not_approved','transport','policy_rejected','unknown')",
            name="ck_order_plan_screening_batch_attempt_failure_type",
        ),
        CheckConstraint(
            "((attempt_status = 'success' AND failure_type IS NULL AND failure_code IS NULL) OR (attempt_status IN ('failed','rejected') AND failure_type IS NOT NULL AND failure_code IS NOT NULL AND length(trim(failure_code)) > 0) OR attempt_status = 'running')",
            name="ck_order_plan_screening_batch_attempt_failure_pair",
        ),
        CheckConstraint("plan_ids_jsonb IS NOT NULL", name="ck_order_plan_screening_batch_attempt_plan_ids_present"),
        CheckConstraint(
            DualSQL(
                "json_valid(plan_ids_jsonb) AND json_type(plan_ids_jsonb) = 'array'",
                "jsonb_typeof(plan_ids_jsonb) = 'array'",
            ),
            name="ck_order_plan_screening_batch_attempt_plan_ids_array",
        ),
        CheckConstraint(
            dual("length(plan_ids_sha256) = 64 AND plan_ids_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_batch_attempt_plan_ids_sha256",
        ),
        CheckConstraint(
            dual("length(model_digest) = 64 AND model_digest NOT GLOB '*[^0-9a-f]*' AND length(prompt_sha256) = 64 AND prompt_sha256 NOT GLOB '*[^0-9a-f]*' AND length(company_profile_sha256) = 64 AND company_profile_sha256 NOT GLOB '*[^0-9a-f]*' AND length(generation_config_sha256) = 64 AND generation_config_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_batch_attempt_binding_sha256",
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_order_plan_screening_batch_attempt_input_tokens"),
        CheckConstraint("cached_input_tokens IS NULL OR cached_input_tokens >= 0", name="ck_order_plan_screening_batch_attempt_cached_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_order_plan_screening_batch_attempt_output_tokens"),
        CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ck_order_plan_screening_batch_attempt_total_tokens"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_order_plan_screening_batch_attempt_duration"),
        CheckConstraint("length(trim(batch_id)) > 0 AND length(trim(model_name)) > 0 AND length(trim(prompt_version)) > 0 AND length(trim(company_profile_version)) > 0", name="ck_order_plan_screening_batch_attempt_strings"),
    )

    attempt_id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    execution_id: Mapped[uuid_module.UUID] = mapped_column(_fk("order_plan_screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_count: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_ids_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    plan_ids_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    company_profile_version: Mapped[str] = mapped_column(String(128), nullable=False)
    company_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_status: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_object_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class OrderPlanScreeningResult(Base):
    __tablename__ = "order_plan_screening_result"
    __table_args__ = (
        UniqueConstraint("execution_id", "order_plan_id", name="uq_order_plan_screening_result_plan"),
        CheckConstraint("schema_version = 'bidops.order-plan-screening-result-row.v1'", name="ck_order_plan_screening_result_schema_version"),
        CheckConstraint("producer = 'order-plan-screening-merge' AND consumer = 'postgres-loader-and-review-api'", name="ck_order_plan_screening_result_provenance"),
        CheckConstraint("stage1_status IN ('selected','filtered_out','failed','rejected')", name="ck_order_plan_screening_result_stage1_status"),
        CheckConstraint("stage2_status IN ('not_attempted','success','failed','rejected','unknown')", name="ck_order_plan_screening_result_stage2_status"),
        CheckConstraint("stage1_rank IS NULL OR stage1_rank >= 1", name="ck_order_plan_screening_result_stage1_rank"),
        CheckConstraint("stage1_score IS NULL OR stage1_score >= 0", name="ck_order_plan_screening_result_stage1_score"),
        CheckConstraint("qwen_score IS NULL OR (qwen_score >= 0 AND qwen_score <= 1)", name="ck_order_plan_screening_result_qwen_score"),
        CheckConstraint("attempt_no IS NULL OR attempt_no BETWEEN 1 AND 2", name="ck_order_plan_screening_result_attempt_no"),
        CheckConstraint("(batch_id IS NULL) = (attempt_no IS NULL)", name="ck_order_plan_screening_result_batch_attempt_pair"),
        CheckConstraint(
            "((stage1_status IN ('failed','rejected') AND stage1_rank IS NULL AND stage1_score IS NULL AND nearest_capability IS NULL AND stage2_status = 'not_attempted') OR (stage1_status = 'filtered_out' AND stage1_rank IS NOT NULL AND stage1_score IS NOT NULL AND stage2_status = 'not_attempted') OR (stage1_status = 'selected' AND stage1_rank IS NOT NULL AND stage1_score IS NOT NULL))",
            name="ck_order_plan_screening_result_stage1_fields",
        ),
        CheckConstraint(
            "((stage2_status = 'not_attempted' AND qwen_relevance IS NULL AND qwen_score IS NULL AND qwen_reason IS NULL AND batch_id IS NULL AND attempt_no IS NULL AND failure_code IS NULL) OR (stage2_status = 'success' AND qwen_relevance IN ('relevant','not_relevant','uncertain') AND qwen_score IS NOT NULL AND qwen_reason IS NOT NULL AND length(trim(qwen_reason)) > 0 AND length(qwen_reason) <= 500 AND batch_id IS NOT NULL AND attempt_no IS NOT NULL AND failure_code IS NULL) OR (stage2_status IN ('failed','rejected','unknown') AND qwen_relevance IS NULL AND qwen_score IS NULL AND qwen_reason IS NULL AND failure_code IS NOT NULL AND length(trim(failure_code)) > 0))",
            name="ck_order_plan_screening_result_stage2_fields",
        ),
        CheckConstraint(
            dual("length(input_artifact_sha256) = 64 AND input_artifact_sha256 NOT GLOB '*[^0-9a-f]*' AND length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*' AND length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*' AND length(result_sha256) = 64 AND result_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_result_hashes",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    execution_id: Mapped[uuid_module.UUID] = mapped_column(_fk("order_plan_screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    source_run_id: Mapped[str] = mapped_column(_fk("run.id", ondelete="RESTRICT"), nullable=False)
    order_plan_id: Mapped[int] = mapped_column(_fk("order_plan.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    input_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    stage1_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage1_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    nearest_capability: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage1_status: Mapped[str] = mapped_column(String(16), nullable=False)
    stage2_status: Mapped[str] = mapped_column(String(16), nullable=False)
    qwen_relevance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    qwen_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    qwen_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class OrderPlanScreeningArtifact(Base):
    __tablename__ = "order_plan_screening_artifact"
    __table_args__ = (
        UniqueConstraint("execution_id", "kind", name="uq_order_plan_screening_artifact_kind"),
        CheckConstraint("kind IN ('input','ranking','decisions','failures','telemetry','result','feedback')", name="ck_order_plan_screening_artifact_kind"),
        CheckConstraint("validation_status IN ('pending','valid','invalid')", name="ck_order_plan_screening_artifact_validation_status"),
        CheckConstraint("byte_count >= 0", name="ck_order_plan_screening_artifact_byte_count"),
        CheckConstraint("schema_version IS NOT NULL AND length(trim(schema_version)) > 0 AND length(trim(producer)) > 0 AND length(trim(consumer)) > 0", name="ck_order_plan_screening_artifact_provenance"),
        CheckConstraint(dual("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'"), name="ck_order_plan_screening_artifact_sha256"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    execution_id: Mapped[uuid_module.UUID] = mapped_column(_fk("order_plan_screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    object_version_ref = synonym("object_version")


class OrderPlanScreeningFeedback(Base):
    __tablename__ = "order_plan_screening_feedback"
    __table_args__ = (
        UniqueConstraint("execution_id", "order_plan_id", "revision", name="uq_order_plan_screening_feedback_revision"),
        CheckConstraint("schema_version = 'bidops.order-plan-screening-feedback.v1'", name="ck_order_plan_screening_feedback_schema_version"),
        CheckConstraint("producer = 'human-review-api' AND consumer = 'postgres-review-history'", name="ck_order_plan_screening_feedback_provenance"),
        CheckConstraint("actor_kind = 'human'", name="ck_order_plan_screening_feedback_actor_kind"),
        CheckConstraint("relevance IN ('relevant','not_relevant','uncertain')", name="ck_order_plan_screening_feedback_relevance"),
        CheckConstraint("priority IS NULL OR priority IN ('high','medium','low')", name="ck_order_plan_screening_feedback_priority"),
        CheckConstraint("revision >= 1", name="ck_order_plan_screening_feedback_revision"),
        CheckConstraint("length(trim(claimed_name)) > 0 AND (memo IS NULL OR length(trim(memo)) > 0)", name="ck_order_plan_screening_feedback_strings"),
    )

    feedback_id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    execution_id: Mapped[uuid_module.UUID] = mapped_column(_fk("order_plan_screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    order_plan_id: Mapped[int] = mapped_column(_fk("order_plan.id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    claimed_name: Mapped[str] = mapped_column(String(128), nullable=False)
    relevance: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_feedback_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("order_plan_screening_feedback.feedback_id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


# C-2 품질 게이트·감사 표본·일일 스위치 (``0029_c2_quality_gate``, 명세 §2.1).
# 넷 다 PostgreSQL trigger가 UPDATE·DELETE를 거부한다. 임계값이 NULL이면 evaluation이
# ``미측정``만 받는 규칙은 두 테이블에 걸쳐 있어 PostgreSQL BEFORE INSERT trigger만
# 강제한다. SQLite 격리 테스트의 ``create_all``에는 이 trigger들이 없다.


def _c2_pct(column: str) -> str:
    return f"{column} IS NULL OR ({column} >= 0 AND {column} <= 100)"


class OrderPlanScreeningQualityGate(Base):
    __tablename__ = "order_plan_screening_quality_gate"
    __table_args__ = (
        CheckConstraint(
            dual("length(gate_id) = 39 AND substr(gate_id, 1, 7) = 'c2gate-' AND substr(gate_id, 8) NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_quality_gate_id",
        ),
        CheckConstraint(
            dual("length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*' AND length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*' AND length(gold_manifest_sha256) = 64 AND gold_manifest_sha256 NOT GLOB '*[^0-9a-f]*' AND length(gold_artifact_sha256) = 64 AND gold_artifact_sha256 NOT GLOB '*[^0-9a-f]*' AND length(scoring_input_sha256) = 64 AND scoring_input_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_quality_gate_hashes",
        ),
        CheckConstraint(
            "evaluation_basis IN ('product_rerun','reference_artifact_rescore')",
            name="ck_order_plan_screening_quality_gate_basis",
        ),
        CheckConstraint("scoring_unit = 'per_published_day'", name="ck_order_plan_screening_quality_gate_scoring_unit"),
        CheckConstraint("required_pass_count = 2", name="ck_order_plan_screening_quality_gate_pass_count"),
        CheckConstraint(
            DualSQL(
                "json_valid(measurement_run_ids_json) AND json_type(measurement_run_ids_json) = 'array'",
                "jsonb_typeof(measurement_run_ids_json) = 'array'",
            ),
            name="ck_order_plan_screening_quality_gate_run_ids",
        ),
        CheckConstraint(
            f"({_c2_pct('threshold_recall_pct')}) AND ({_c2_pct('threshold_precision_pct')}) "
            "AND (threshold_important_missed_max IS NULL OR threshold_important_missed_max >= 0) "
            "AND (threshold_review_load_max IS NULL OR threshold_review_load_max >= 0)",
            name="ck_order_plan_screening_quality_gate_thresholds",
        ),
        CheckConstraint(
            "length(trim(gold_status)) > 0 AND length(trim(created_by)) > 0",
            name="ck_order_plan_screening_quality_gate_strings",
        ),
    )

    gate_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    policy_version: Mapped[str] = mapped_column(_fk("order_plan_screening_policy.policy_version", ondelete="RESTRICT"), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    gold_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    gold_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    gold_status: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement_run_ids_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    required_pass_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL = 사람 결정(D-b) 전. 임계값의 정본이 이 행이다(명세 §1.1).
    threshold_recall_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    threshold_precision_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    threshold_important_missed_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold_review_load_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class OrderPlanScreeningQualityEvaluation(Base):
    __tablename__ = "order_plan_screening_quality_evaluation"
    __table_args__ = (
        UniqueConstraint("gate_id", "revision", name="uq_order_plan_screening_quality_evaluation_revision"),
        CheckConstraint(
            dual("length(evaluation_id) = 43 AND substr(evaluation_id, 1, 11) = 'c2gateeval-' AND substr(evaluation_id, 12) NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_quality_evaluation_id",
        ),
        CheckConstraint("revision >= 1", name="ck_order_plan_screening_quality_evaluation_revision"),
        CheckConstraint(
            "result_status IN ('통과','미달','미측정','보류')",
            name="ck_order_plan_screening_quality_evaluation_status",
        ),
        CheckConstraint(
            DualSQL(
                "json_valid(pass_execution_ids_json) AND json_type(pass_execution_ids_json) = 'object' AND json_valid(metrics_json) AND json_type(metrics_json) = 'object' AND json_valid(reasons_json) AND json_type(reasons_json) = 'array'",
                "jsonb_typeof(pass_execution_ids_json) = 'object' AND jsonb_typeof(metrics_json) = 'object' AND jsonb_typeof(reasons_json) = 'array'",
            ),
            name="ck_order_plan_screening_quality_evaluation_json",
        ),
        CheckConstraint(
            f"({_c2_pct('measured_recall_pct')}) AND ({_c2_pct('measured_precision_pct')}) "
            "AND (measured_important_missed IS NULL OR measured_important_missed >= 0) "
            "AND (measured_review_load IS NULL OR measured_review_load >= 0)",
            name="ck_order_plan_screening_quality_evaluation_measured",
        ),
        CheckConstraint(
            dual("length(artifact_sha256) = 64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_quality_evaluation_artifact",
        ),
        CheckConstraint("length(trim(evaluated_by)) > 0", name="ck_order_plan_screening_quality_evaluation_strings"),
    )

    evaluation_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    gate_id: Mapped[str] = mapped_column(_fk("order_plan_screening_quality_gate.gate_id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    pass_execution_ids_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    # 두 pass 중 나쁜 쪽 값(명세 §2.1). 계산할 수 없으면 NULL로 남긴다.
    measured_recall_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    measured_precision_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    measured_important_missed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    measured_review_load: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    reasons_json: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class OrderPlanScreeningAuditSample(Base):
    __tablename__ = "order_plan_screening_audit_sample"
    __table_args__ = (
        # 무복원 추출의 근거(명세 §5 ``replacement: none``).
        UniqueConstraint("execution_id", "order_plan_id", name="uq_order_plan_screening_audit_sample_plan"),
        CheckConstraint(
            "stratum IN ('classification_proximity','performance_similarity_proximity','uniform_hash')",
            name="ck_order_plan_screening_audit_sample_stratum",
        ),
        CheckConstraint(
            "selection_rank >= 1 AND filtered_out_count >= 0 AND max_per_execution >= 1",
            name="ck_order_plan_screening_audit_sample_numbers",
        ),
        CheckConstraint(
            dual("length(plan_id_sha256) = 64 AND plan_id_sha256 NOT GLOB '*[^0-9a-f]*' AND length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_audit_sample_hashes",
        ),
        CheckConstraint(
            "length(trim(review_cadence)) > 0 AND length(trim(policy_version)) > 0 AND length(trim(drawn_by)) > 0",
            name="ck_order_plan_screening_audit_sample_strings",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    execution_id: Mapped[uuid_module.UUID] = mapped_column(_fk("order_plan_screening_execution.execution_id", ondelete="RESTRICT"), nullable=False)
    order_plan_id: Mapped[int] = mapped_column(_fk("order_plan.id", ondelete="RESTRICT"), nullable=False)
    stratum: Mapped[str] = mapped_column(String(48), nullable=False)
    selection_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filtered_out_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_per_execution: Mapped[int] = mapped_column(Integer, nullable=False)
    review_cadence: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    drawn_by: Mapped[str] = mapped_column(String(128), nullable=False)
    drawn_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class OrderPlanScreeningDailyTrigger(Base):
    """일일 자동 실행 스위치(결정 21). 현재 값은 그 policy_version의 최신 행이다."""

    __tablename__ = "order_plan_screening_daily_trigger"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_order_plan_screening_daily_trigger_request"),
        Index("ix_order_plan_screening_daily_trigger_latest", "policy_version", "set_at"),
        CheckConstraint(
            dual("length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'"),
            name="ck_order_plan_screening_daily_trigger_policy_sha256",
        ),
        CheckConstraint(
            "length(trim(set_by)) > 0 AND (reason IS NULL OR length(trim(reason)) > 0)",
            name="ck_order_plan_screening_daily_trigger_strings",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    policy_version: Mapped[str] = mapped_column(_fk("order_plan_screening_policy.policy_version", ondelete="RESTRICT"), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    set_by: Mapped[str] = mapped_column(String(128), nullable=False)
    set_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    request_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


ORDER_PLAN_SCREENING_TABLES = (
    "order_plan_screening_policy",
    "order_plan_screening_execution",
    "order_plan_screening_batch_attempt",
    "order_plan_screening_result",
    "order_plan_screening_artifact",
    "order_plan_screening_feedback",
    "order_plan_screening_quality_gate",
    "order_plan_screening_quality_evaluation",
    "order_plan_screening_audit_sample",
    "order_plan_screening_daily_trigger",
)


REVISION_TABLES = ("judgment_revision", "review_revision")


class ScreeningAuditEvent(Base):
    """Append-only screening runtime and scheduler audit log.

    Separate from :class:`AuditEvent`, which records the Lean v1 mutation
    boundary with a claimed actor name.  This log is written by screening
    services and by the database triggers that disable always-on operation,
    and it keeps the ``audit-<32 hex>`` event id contract.
    """

    __tablename__ = "screening_audit_event"
    __table_args__ = (
        CheckConstraint(dual("length(event_id) = 38 AND substr(event_id, 1, 6) = 'audit-' AND substr(event_id, 7) NOT GLOB '*[^0-9a-f]*'"), name="ck_screening_audit_event_id"),
        CheckConstraint("length(trim(event_type)) > 0 AND length(trim(actor)) > 0 AND length(trim(target_type)) > 0 AND length(trim(target_id)) > 0", name="ck_screening_audit_event_strings"),
        CheckConstraint(dual("json_valid(details_json) AND json_type(details_json) = 'object'"), name="ck_screening_audit_event_details_json"),
    )

    event_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False, default=utc_now)
    details_json: Mapped[Any] = mapped_column(JSON, nullable=False)


# The screening runtime tables are created by
# ``0003_screening_runtime_pg``; the Lean v1 sets above are created by
# ``0001_lean_v1_postgresql``.  Keeping the three tuples disjoint is what stops
# a revision from creating the same table twice.
SCREENING_RUNTIME_TABLES = (
    "screening_execution", "screening_attempt", "company_profile_snapshot", "quality_gate",
    "quality_gate_evaluation", "screening_policy", "quality_gate_review", "schedule_setting",
    "schedule_reservation", "schedule_execution", "always_on_state", "screening_audit_event",
)


# ``0001_lean_v1_postgresql``이 만드는 13개 legacy 투영 중 screening 몫이다.
# 나머지 5개는 lifecycle이 ``LIFECYCLE_LEGACY_TABLES``로 갖고 있다 (명세 §5.1).
SCREENING_LEGACY_TABLES = (
    "judgment", "perspective", "screening_evidence", "counterargument",
    "verification_item", "matched_performance", "review", "verification_answer",
)
