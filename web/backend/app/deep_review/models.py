"""deep_review가 소유하는 선언적 모델 (명세 §5.1의 38개 테이블).

문서 준비(content_object → document_version → document_structure →
document_bundle), 사전규격 개요 검토, 심층 검토와 claim·evidence·보고서·
최종 의견, 입찰 delta와 최종 결정이 여기 있다.

``Notice``·``Attachment``를 향한 relationship은 소유 모듈인 deep_review가
단방향으로 선언한다. screening은 import하지 않으므로 selection 모듈 없이도
mapper 구성이 성공한다 (명세 §4).
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
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    column,
    event,
    inspect as sa_inspect,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base
from ..core.models import (
    AwareDateTime,
    JSONB_COMPAT,
    JSONB_NULL_COMPAT,
    _fk,
    _table,
    _uuid_column,
    utc_now,
)
from ..core.sql_dialect import DualSQL, dual
# 첨부 취득과 개요 검토가 가리키는 lifecycle 모델. 읽기·join 방향이며 §4가
# 허용한다. import 자체가 relationship 문자열의 등록도 보장한다.
from ..lifecycle.models import Attachment, Notice  # noqa: F401


class AttachmentFetch(Base):
    """Lease-fenced provider fetch state for one current attachment."""

    __tablename__ = "attachment_fetch"
    __table_args__ = (
        UniqueConstraint("attachment_id", name="uq_attachment_fetch_attachment"),
        CheckConstraint(
            "status IN ('대기','진행','완료','차단','실패')",
            name="ck_attachment_fetch_status",
        ),
        CheckConstraint(
            "eligibility_reason IN ('sw_business_object','tracked_order_plan','both',"
            "'priority_grade')",
            name="ck_attachment_fetch_eligibility_reason",
        ),
        CheckConstraint(
            "status <> '완료' OR document_version_id IS NOT NULL",
            name="ck_attachment_fetch_completed_document",
        ),
        CheckConstraint(
            "(status = '진행') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_attachment_fetch_lease",
        ),
        Index("ix_attachment_fetch_status_next_attempt", "status", "next_attempt_at"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    attachment_id: Mapped[int] = mapped_column(
        _fk("attachment.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    eligibility_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3"), nullable=False
    )
    next_attempt_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    lease_fence: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_version_id: Mapped[uuid_module.UUID | None] = mapped_column(
        _fk("document_version.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)

    # 단방향(명세 §4). 첨부 삭제 시 이 행의 제거는 FK ondelete=CASCADE가 맡는다.
    attachment: Mapped["Attachment"] = relationship()
    document_version: Mapped["DocumentVersion | None"] = relationship(
        foreign_keys=[document_version_id]
    )


# ---------------------------------------------------------------------------
# Document (8 tables)
# ---------------------------------------------------------------------------


class ContentObject(Base):
    __tablename__ = "content_object"
    __table_args__ = (UniqueConstraint("sha256", name="uq_content_object_sha256"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(255), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class ContentObjectLocation(Base):
    __tablename__ = "content_object_location"

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    namespace_key: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    object_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    encryption_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class ContentScan(Base):
    __tablename__ = "content_scan"
    __table_args__ = (CheckConstraint("status IN ('pending','clean','infected','unavailable','error')", name="ck_content_scan_status"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    scanner: Mapped[str] = mapped_column(String(128), nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_result: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class DocumentVersion(Base):
    __tablename__ = "document_version"
    __table_args__ = (
        # Composite scope target for immutable overview snapshots.  The UUID
        # primary key already identifies a row, but PostgreSQL needs a unique
        # pair to enforce that a snapshot's document belongs to its notice.
        UniqueConstraint("notice_id", "id", name="uq_document_version_notice_scope"),
        Index(
            "uq_document_version_attachment_version",
            "attachment_id",
            "version",
            unique=True,
            postgresql_where=text("attachment_id IS NOT NULL"),
            sqlite_where=text("attachment_id IS NOT NULL"),
        ),
        Index(
            "uq_document_version_attachment_current",
            "attachment_id",
            unique=True,
            postgresql_where=text(
                "attachment_id IS NOT NULL AND is_current IS TRUE"
            ),
            sqlite_where=text(
                "attachment_id IS NOT NULL AND is_current IS TRUE"
            ),
        ),
        CheckConstraint("source_kind IN ('provider','manual')", name="ck_document_version_source_kind"),
        CheckConstraint("(source_kind = 'provider' AND source_system IS NOT NULL AND length(trim(source_system)) > 0 AND source_attachment_key IS NOT NULL AND length(trim(source_attachment_key)) > 0) OR (source_kind = 'manual' AND source_system IS NULL AND source_attachment_key IS NULL AND source_url IS NULL)", name="ck_document_version_source_provenance"),
        CheckConstraint("role IN ('공고','정정','제안요청서','과업지시서','내역서','제출서식','부록','기타')", name="ck_document_version_role"),
        CheckConstraint("safety_status IN ('quarantined','scanning','safe','blocked')", name="ck_document_version_safety"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id"), nullable=False)
    attachment_id: Mapped[int | None] = mapped_column(_fk("attachment.id", ondelete="SET NULL"), nullable=True)
    content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_attachment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    replaces_document_version_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("document_version.id"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    safety_status: Mapped[str] = mapped_column(String(32), nullable=False)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class DocumentStructure(Base):
    __tablename__ = "document_structure"
    __table_args__ = (
        UniqueConstraint("document_version_id", name="uq_document_structure_document_version"),
        # Composite scope target for snapshots; this prevents a structure
        # from another document version being attached to an otherwise valid
        # snapshot row.
        UniqueConstraint(
            "document_version_id",
            "id",
            name="uq_document_structure_document_version_scope",
        ),
        CheckConstraint("validation_status IN ('pending','processing','ready','failed','needs_review')", name="ck_document_structure_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    upstream_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class DocumentBlock(Base):
    __tablename__ = "document_block"
    __table_args__ = (UniqueConstraint("structure_id", "block_key", name="uq_document_block_key"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    structure_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_structure.id"), nullable=False)
    block_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_block_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    attributes: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)


class DocumentSegmentManifest(Base):
    """한 ``document_structure``의 결정적 segment·요구사항 inventory manifest.

    같은 (structure, taxonomy version, 추출기 binding)으로 다시 계산하면 새 행을
    만들지 않고 이 유일 키의 기존 행을 돌려준다. 행은 만들어진 뒤 갱신·삭제하지
    않으며, 부모 구조·문서 version이 사라질 때만 FK CASCADE로 함께 사라진다.
    """

    __tablename__ = "document_segment_manifest"
    __table_args__ = (
        UniqueConstraint(
            "structure_id",
            "taxonomy_version",
            "extractor_binding_sha256",
            name="uq_document_segment_manifest_identity",
        ),
        # 구조와 문서 version은 반드시 같은 쌍이어야 한다. 다른 문서의 구조가
        # manifest에 붙는 경로를 DB가 직접 막는다.
        ForeignKeyConstraint(
            ["document_version_id", "structure_id"],
            [
                _table("document_structure.document_version_id"),
                _table("document_structure.id"),
            ],
            name="fk_document_segment_manifest_structure_document_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            dual(
                "length(source_sha256) = 64 AND source_sha256 NOT GLOB '*[^0-9a-f]*' "
                "AND length(extractor_binding_sha256) = 64 "
                "AND extractor_binding_sha256 NOT GLOB '*[^0-9a-f]*' "
                "AND length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_document_segment_manifest_hashes",
        ),
        CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name="ck_document_segment_manifest_taxonomy_version",
        ),
        CheckConstraint(
            dual(
                "json_valid(extractor_binding) AND json_type(extractor_binding) = 'object'"
            ),
            name="ck_document_segment_manifest_extractor_binding",
        ),
        CheckConstraint(
            dual(
                "json_valid(inventory_summary) AND json_type(inventory_summary) = 'object'"
            ),
            name="ck_document_segment_manifest_inventory_summary",
        ),
        CheckConstraint(
            dual("json_valid(warnings) AND json_type(warnings) = 'array'"),
            name="ck_document_segment_manifest_warnings",
        ),
        CheckConstraint(
            dual("json_valid(coverage) AND json_type(coverage) = 'object'"),
            name="ck_document_segment_manifest_coverage",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    structure_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_structure.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_version.id", ondelete="CASCADE"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_binding: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    extractor_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    inventory_summary: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    warnings: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    coverage: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    segments: Mapped[list["DocumentSegment"]] = relationship(
        "DocumentSegment",
        foreign_keys="DocumentSegment.manifest_id",
        back_populates="manifest",
        order_by="DocumentSegment.ordinal",
        viewonly=True,
    )
    inventory_items: Mapped[list["RequirementInventoryItem"]] = relationship(
        "RequirementInventoryItem",
        foreign_keys="RequirementInventoryItem.manifest_id",
        back_populates="manifest",
        order_by="RequirementInventoryItem.ordinal",
        viewonly=True,
    )


class DocumentSegment(Base):
    """manifest 하나에 속한 목적별 segment 한 구간 (결정적 분류만).

    분류 규칙이 충돌하거나 label을 정하지 못하면 ``status``는
    ``needs_human_review``로 남고 ``confidence``는 ``null``이다. 모르는 값을
    0이나 빈 값으로 바꾸지 않는다.
    """

    __tablename__ = "document_segment"
    __table_args__ = (
        UniqueConstraint(
            "manifest_id", "segment_id", name="uq_document_segment_segment_id"
        ),
        UniqueConstraint(
            "manifest_id", "ordinal", name="uq_document_segment_ordinal"
        ),
        CheckConstraint("ordinal >= 1", name="ck_document_segment_ordinal"),
        CheckConstraint(
            "length(trim(segment_id)) > 0", name="ck_document_segment_segment_id"
        ),
        CheckConstraint(
            "status IN ('classified','needs_human_review')",
            name="ck_document_segment_status",
        ),
        # 모델 분류는 없다 (명세 §6.7). 값 집합이 하나인 것이 그 규칙이다.
        CheckConstraint(
            "classification_source = 'deterministic'",
            name="ck_document_segment_classification_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_document_segment_confidence_range",
        ),
        # 사람 검토가 필요한 segment는 확신도를 만들어 내지 않는다.
        CheckConstraint(
            "status <> 'needs_human_review' OR confidence IS NULL",
            name="ck_document_segment_needs_review_confidence",
        ),
        CheckConstraint(
            dual(
                "json_valid(taxonomy_labels) AND json_type(taxonomy_labels) = 'array'"
            ),
            name="ck_document_segment_taxonomy_labels",
        ),
        CheckConstraint(
            dual("json_valid(start_locator) AND json_type(start_locator) = 'object'"),
            name="ck_document_segment_start_locator",
        ),
        CheckConstraint(
            dual("json_valid(end_locator) AND json_type(end_locator) = 'object'"),
            name="ck_document_segment_end_locator",
        ),
        CheckConstraint(
            dual(
                "json_valid(requirement_ids) AND json_type(requirement_ids) = 'array'"
            ),
            name="ck_document_segment_requirement_ids",
        ),
        CheckConstraint(
            dual(
                "json_valid(source_block_keys) AND json_type(source_block_keys) = 'array'"
            ),
            name="ck_document_segment_source_block_keys",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    manifest_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_segment_manifest.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    taxonomy_labels: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    end_locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    requirement_ids: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    source_block_keys: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    classification_source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    manifest: Mapped["DocumentSegmentManifest"] = relationship(
        "DocumentSegmentManifest",
        foreign_keys=[manifest_id],
        back_populates="segments",
    )


class RequirementInventoryItem(Base):
    """manifest 하나가 문서에서 결정적으로 뽑은 요구사항 ID 한 건.

    중복 ID는 그대로 보존한다 (요약의 ``duplicate_ids``가 그 사실을 말한다).
    ID 없는 서술형 의무는 만들지 않는다.
    """

    __tablename__ = "requirement_inventory_item"
    __table_args__ = (
        UniqueConstraint(
            "manifest_id", "ordinal", name="uq_requirement_inventory_item_ordinal"
        ),
        CheckConstraint("ordinal >= 1", name="ck_requirement_inventory_item_ordinal"),
        CheckConstraint(
            "length(trim(raw_id)) > 0 AND length(trim(normalized_id)) > 0",
            name="ck_requirement_inventory_item_ids",
        ),
        CheckConstraint(
            dual("json_valid(locator) AND json_type(locator) = 'object'"),
            name="ck_requirement_inventory_item_locator",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    manifest_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_segment_manifest.id", ondelete="CASCADE"), nullable=False
    )
    raw_id: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_id: Mapped[str] = mapped_column(String(255), nullable=False)
    locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    manifest: Mapped["DocumentSegmentManifest"] = relationship(
        "DocumentSegmentManifest",
        foreign_keys=[manifest_id],
        back_populates="inventory_items",
    )


class PreSpecOverviewReview(Base):
    """Mutable current state for the independent pre-spec overview stage.

    The input lineage itself lives in :class:`PreSpecOverviewSnapshot` and is
    append-only.  This row only owns the current stage/status pointer so a
    newly prepared document structure can advance the logical review without
    rewriting a historical input snapshot.
    """

    __tablename__ = "prespec_overview_review"
    __table_args__ = (
        UniqueConstraint("notice_id", name="uq_prespec_overview_review_notice"),
        UniqueConstraint("id", "notice_id", name="uq_prespec_overview_review_scope"),
        ForeignKeyConstraint(
            ["id", "current_snapshot_id"],
            [
                _table("prespec_overview_snapshot.review_id"),
                _table("prespec_overview_snapshot.id"),
            ],
            name="fk_prespec_overview_review_current_snapshot_scope",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN ('awaiting_document','awaiting_structure','preparing',"
            "'awaiting_model','queued','running','needs_human_review','completed',"
            "'failed','cancelled')",
            name="ck_prespec_overview_review_status",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('추진 검토','조건부 추진 검토','보류','검토 종료')",
            name="ck_prespec_overview_review_result",
        ),
        CheckConstraint(
            "((status = 'completed' AND result IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status <> 'completed' AND result IS NULL AND completed_at IS NULL))",
            name="ck_prespec_overview_review_completion",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    current_snapshot_id: Mapped[uuid_module.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="awaiting_document",
        server_default=text("'awaiting_document'"),
    )
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)

    # 단방향(명세 §4). lifecycle의 Notice는 deep_review 모델을 가리키지 않는다.
    notice: Mapped["Notice"] = relationship("Notice", foreign_keys=[notice_id])

    current_snapshot: Mapped["PreSpecOverviewSnapshot | None"] = relationship(
        "PreSpecOverviewSnapshot",
        foreign_keys=[current_snapshot_id],
        primaryjoin="PreSpecOverviewReview.current_snapshot_id == PreSpecOverviewSnapshot.id",
        post_update=True,
    )
    snapshots: Mapped[list["PreSpecOverviewSnapshot"]] = relationship(
        "PreSpecOverviewSnapshot",
        foreign_keys="PreSpecOverviewSnapshot.review_id",
        primaryjoin="PreSpecOverviewReview.id == PreSpecOverviewSnapshot.review_id",
        back_populates="review",
        order_by="PreSpecOverviewSnapshot.created_at",
    )


class PreSpecOverviewSnapshot(Base):
    """Immutable deterministic input cut for one document structure."""

    __tablename__ = "prespec_overview_snapshot"
    __table_args__ = (
        Index(
            "ix_prespec_overview_snapshot_notice",
            "notice_id",
            "created_at",
        ),
        UniqueConstraint(
            "review_id", "document_version_id", "structure_id", "source_sha256", "payload_sha256",
            name="uq_prespec_overview_snapshot_input",
        ),
        UniqueConstraint("review_id", "id", name="uq_prespec_overview_snapshot_review_scope"),
        ForeignKeyConstraint(
            ["review_id", "notice_id"],
            [
                _table("prespec_overview_review.id"),
                _table("prespec_overview_review.notice_id"),
            ],
            name="fk_prespec_overview_snapshot_review_notice_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            [
                _table("document_version.notice_id"),
                _table("document_version.id"),
            ],
            name="fk_prespec_overview_snapshot_document_notice_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "structure_id"],
            [
                _table("document_structure.document_version_id"),
                _table("document_structure.id"),
            ],
            name="fk_prespec_overview_snapshot_structure_document_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("cut_status IN ('pending','ready','unknown','failed')", name="ck_prespec_overview_snapshot_cut_status"),
        CheckConstraint(
            "strategy IS NULL OR strategy IN ('toc_body_match','topic_heading')",
            name="ck_prespec_overview_snapshot_strategy",
        ),
        CheckConstraint(
            "((cut_status = 'ready' AND strategy IS NOT NULL AND start_locator IS NOT NULL AND end_locator IS NOT NULL) "
            "OR (cut_status <> 'ready'))",
            name="ck_prespec_overview_snapshot_ready_inputs",
        ),
        CheckConstraint(
            "((cut_status = 'unknown' AND unknown_reason_code IS NOT NULL AND length(trim(unknown_reason_code)) > 0) "
            "OR (cut_status <> 'unknown' AND unknown_reason_code IS NULL))",
            name="ck_prespec_overview_snapshot_unknown_reason",
        ),
        CheckConstraint(
            dual(
                "length(source_sha256) = 64 AND source_sha256 NOT GLOB '*[^0-9a-f]*' "
                "AND length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_overview_snapshot_hashes",
        ),
        CheckConstraint(
            dual(
                "start_locator IS NULL OR (json_valid(start_locator) AND json_type(start_locator) = 'object')"
            ),
            name="ck_prespec_overview_snapshot_start_locator",
        ),
        CheckConstraint(
            dual(
                "end_locator IS NULL OR (json_valid(end_locator) AND json_type(end_locator) = 'object')"
            ),
            name="ck_prespec_overview_snapshot_end_locator",
        ),
        CheckConstraint(
            dual(
                "input_block_keys IS NULL OR (json_valid(input_block_keys) AND json_type(input_block_keys) = 'array')"
            ),
            name="ck_prespec_overview_snapshot_input_block_keys",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    review_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("prespec_overview_review.id", ondelete="RESTRICT"), nullable=False
    )
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_version.id", ondelete="RESTRICT"), nullable=False
    )
    structure_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("document_structure.id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cut_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_locator: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    end_locator: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    input_block_keys: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    unknown_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)

    review: Mapped["PreSpecOverviewReview"] = relationship(
        "PreSpecOverviewReview",
        foreign_keys=[review_id],
        back_populates="snapshots",
    )
    attempts: Mapped[list["PreSpecOverviewAttempt"]] = relationship(
        "PreSpecOverviewAttempt",
        foreign_keys="PreSpecOverviewAttempt.snapshot_id",
        back_populates="snapshot",
        order_by="PreSpecOverviewAttempt.sequence",
    )


class PreSpecOverviewAttempt(Base):
    """A lifecycle row whose input lineage is immutable to runtime roles.

    Phase 1 created this table as fully append-only.  Phase 2 keeps the
    snapshot/provider binding immutable while allowing only the small set of
    lifecycle columns needed by a worker to advance an attempt.
    """

    __tablename__ = "prespec_overview_attempt"
    __table_args__ = (
        Index(
            "ix_prespec_overview_attempt_snapshot",
            "snapshot_id",
            "created_at",
        ),
        UniqueConstraint("snapshot_id", "sequence", name="uq_prespec_overview_attempt_sequence"),
        UniqueConstraint("id", "snapshot_id", name="uq_prespec_overview_attempt_snapshot_scope"),
        UniqueConstraint("id", "review_id", name="uq_prespec_overview_attempt_review_scope"),
        CheckConstraint("sequence >= 1", name="ck_prespec_overview_attempt_sequence"),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_prespec_overview_attempt_status",
        ),
        CheckConstraint(
            "(NOT reference_only) OR deployable IS FALSE",
            name="ck_prespec_overview_attempt_reference_boundary",
        ),
        # 품질을 아직 재지 않은 실제 모델 실행(``deployable`` false)도 완료될 수
        # 있다. mock 참조 실행(``reference_only`` true)만 완료를 막는다 (명세 §6.3).
        CheckConstraint(
            "status <> 'completed' OR reference_only IS FALSE",
            name="ck_prespec_overview_attempt_completed_binding",
        ),
        CheckConstraint(
            "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status IN ('failed','cancelled') AND completed_at IS NOT NULL AND result_id IS NULL) "
            "OR (status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND result_id IS NOT NULL))",
            name="ck_prespec_overview_attempt_completion",
        ),
        CheckConstraint(
            "review_id IS NULL OR input_sha256 IS NOT NULL",
            name="ck_prespec_overview_attempt_review_input",
        ),
        CheckConstraint(
            dual(
                "input_sha256 IS NULL OR (length(input_sha256) = 64 AND input_sha256 NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_prespec_overview_attempt_input_sha256",
        ),
        CheckConstraint(
            dual(
                "binding_digest IS NULL OR (length(binding_digest) = 64 AND binding_digest NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_prespec_overview_attempt_binding_digest",
        ),
        CheckConstraint(
            "review_id IS NULL OR (binding_digest IS NOT NULL AND provider IS NOT NULL "
            "AND model_name IS NOT NULL AND model_digest IS NOT NULL AND prompt_version IS NOT NULL)",
            name="ck_prespec_overview_attempt_binding_pair",
        ),
        CheckConstraint(
            "result_id IS NULL OR status = 'completed'",
            name="ck_prespec_overview_attempt_result_reference_status",
        ),
        CheckConstraint(
            dual(
                "result_jsonb IS NULL OR (json_valid(result_jsonb) AND json_type(result_jsonb) = 'object')"
            ),
            name="ck_prespec_overview_attempt_result_object",
        ),
        CheckConstraint(
            dual(
                "result_sha256 IS NULL OR (length(result_sha256) = 64 AND result_sha256 NOT GLOB '*[^0-9a-f]*')"
            ),
            name="ck_prespec_overview_attempt_result_sha256",
        ),
        ForeignKeyConstraint(
            ["review_id", "snapshot_id"],
            [
                _table("prespec_overview_snapshot.review_id"),
                _table("prespec_overview_snapshot.id"),
            ],
            name="fk_prespec_overview_attempt_review_snapshot_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["result_id"],
            [_table("prespec_overview_result.id")],
            name="fk_prespec_overview_attempt_result",
            ondelete="RESTRICT",
            use_alter=True,
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    # Nullable only for legacy phase 1 attempts. New phase 2 attempts always
    # set this exact review scope and are protected by the composite FK below.
    review_id: Mapped[uuid_module.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    snapshot_id: Mapped[uuid_module.UUID] = mapped_column(
        _fk("prespec_overview_snapshot.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default=text("'queued'")
    )
    reference_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    deployable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binding_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_id: Mapped[uuid_module.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    result_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    # 합성 worker가 claim한 실행을 표시하는 lease. 만료된 ``running`` attempt는
    # 다음 poll이 ``failed``로 닫고 lease를 비운다 (자동 재시작 없음, 명세 §6.3).
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        AwareDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)

    snapshot: Mapped["PreSpecOverviewSnapshot"] = relationship(
        "PreSpecOverviewSnapshot",
        foreign_keys=[snapshot_id],
        back_populates="attempts",
    )
    result: Mapped["PreSpecOverviewResult | None"] = relationship(
        "PreSpecOverviewResult",
        foreign_keys=[result_id],
        primaryjoin="PreSpecOverviewAttempt.result_id == PreSpecOverviewResult.id",
        uselist=False,
        viewonly=True,
    )


class PreSpecOverviewResult(Base):
    """One validated, immutable result for one overview attempt."""

    __tablename__ = "prespec_overview_result"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_prespec_overview_result_attempt"),
        UniqueConstraint(
            "id", "attempt_id", name="uq_prespec_overview_result_attempt_scope"
        ),
        CheckConstraint(
            "schema_version = 'bidops.prespec-overview-result.v1'",
            name="ck_prespec_overview_result_schema_version",
        ),
        CheckConstraint(
            dual(
                "json_valid(payload_jsonb) AND json_type(payload_jsonb) = 'object'"
            ),
            name="ck_prespec_overview_result_payload_object",
        ),
        CheckConstraint(
            DualSQL(
                "coalesce(json_array_length(json_extract(payload_jsonb, '$.evidence')), 0) >= 1",
                "CASE WHEN jsonb_typeof(payload_jsonb -> 'evidence') = 'array' "
                "THEN jsonb_array_length(payload_jsonb -> 'evidence') >= 1 ELSE FALSE END",
            ),
            name="ck_prespec_overview_result_evidence_nonempty",
        ),
        CheckConstraint(
            dual(
                "length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_overview_result_payload_sha256",
        ),
        CheckConstraint(
            dual(
                "length(source_sha256) = 64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_overview_result_source_sha256",
        ),
        CheckConstraint(
            dual(
                "length(binding_digest) = 64 AND binding_digest NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_overview_result_binding_digest",
        ),
        CheckConstraint(
            "validation_status = 'passed'",
            name="ck_prespec_overview_result_validation_status",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            [_table("prespec_overview_attempt.id")],
            name="fk_prespec_overview_result_attempt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "snapshot_id"],
            [
                _table("prespec_overview_attempt.id"),
                _table("prespec_overview_attempt.snapshot_id"),
            ],
            name="fk_prespec_overview_result_attempt_snapshot_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "review_id"],
            [
                _table("prespec_overview_attempt.id"),
                _table("prespec_overview_attempt.review_id"),
            ],
            name="fk_prespec_overview_result_attempt_review_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_id", "snapshot_id"],
            [
                _table("prespec_overview_snapshot.review_id"),
                _table("prespec_overview_snapshot.id"),
            ],
            name="fk_prespec_overview_result_review_snapshot_scope",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    attempt_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    review_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    snapshot_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="passed", server_default=text("'passed'")
    )
    created_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, nullable=False
    )

    attempt: Mapped["PreSpecOverviewAttempt"] = relationship(
        "PreSpecOverviewAttempt",
        foreign_keys=[attempt_id],
        uselist=False,
        viewonly=True,
    )


class PreSpecOverviewAttemptEvent(Base):
    """Append-only audit row for every attempt status transition."""

    __tablename__ = "prespec_overview_attempt_event"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "event_sequence", name="uq_prespec_overview_attempt_event_sequence"
        ),
        CheckConstraint("event_sequence >= 1", name="ck_prespec_overview_event_sequence"),
        CheckConstraint(
            "from_status <> to_status AND ((from_status = 'queued' AND to_status IN ('running','failed','cancelled')) OR (from_status = 'running' AND to_status IN ('completed','failed','cancelled')))",
            name="ck_prespec_overview_event_transition",
        ),
        CheckConstraint(
            "actor_kind IN ('worker','human','system') AND length(trim(actor_id)) > 0",
            name="ck_prespec_overview_event_actor",
        ),
        CheckConstraint(
            "length(trim(reason_code)) > 0",
            name="ck_prespec_overview_event_reason",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            [_table("prespec_overview_attempt.id")],
            name="fk_prespec_overview_attempt_event_attempt",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    attempt_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        AwareDateTime(), default=utc_now, nullable=False
    )
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)


PRESPEC_OVERVIEW_ATTEMPT_TRANSITIONS = frozenset(
    {
        ("queued", "running"),
        ("queued", "failed"),
        ("queued", "cancelled"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),
    }
)


class DocumentBundle(Base):
    __tablename__ = "document_bundle"
    __table_args__ = (
        UniqueConstraint("notice_id", "revision", name="uq_document_bundle_notice_revision"),
        CheckConstraint("status IN ('draft','processing','needs_review','ready','quarantined','failed','superseded')", name="ck_document_bundle_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_bundle_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("document_bundle.id"), nullable=True)
    issues_snapshot: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class DocumentBundleItem(Base):
    __tablename__ = "document_bundle_item"
    __table_args__ = (
        UniqueConstraint("bundle_id", "document_version_id", "structure_id_at_confirmation", name="uq_bundle_item_scope"),
        UniqueConstraint(
            "bundle_id",
            "ordinal",
            name="uq_document_bundle_item_bundle_ordinal",
        ),
        CheckConstraint("source_kind IN ('provider','manual')", name="ck_bundle_item_source_kind"),
        CheckConstraint("(source_kind = 'provider' AND source_system IS NOT NULL AND length(trim(source_system)) > 0 AND source_attachment_key IS NOT NULL AND length(trim(source_attachment_key)) > 0) OR (source_kind = 'manual' AND source_system IS NULL AND source_attachment_key IS NULL AND source_url IS NULL)", name="ck_bundle_item_source_provenance"),
        CheckConstraint("role_at_confirmation IN ('공고','정정','제안요청서','과업지시서','내역서','제출서식','부록','기타')", name="ck_bundle_item_role"),
        CheckConstraint("safety_status_at_confirmation IN ('quarantined','scanning','safe','blocked')", name="ck_bundle_item_safety"),
    )

    bundle_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_bundle.id"), primary_key=True)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_version_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_attachment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_at_confirmation: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date_at_confirmation: Mapped[date | None] = mapped_column(Date, nullable=True)
    replaces_id_at_confirmation: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    is_current_at_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    safety_status_at_confirmation: Mapped[str] = mapped_column(String(32), nullable=False)
    structure_id_at_confirmation: Mapped[uuid_module.UUID] = mapped_column(_fk("document_structure.id"), nullable=False)
    structure_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------------------
# Knowledge (3 tables)
# ---------------------------------------------------------------------------


class ProfileVersion(Base):
    __tablename__ = "profile_version"
    __table_args__ = (UniqueConstraint("version", name="uq_profile_version_version"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_payload: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class ProfileEvidence(Base):
    __tablename__ = "profile_evidence"
    __table_args__ = (UniqueConstraint("profile_version_id", "id", name="uq_profile_evidence_scope"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    profile_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("profile_version.id"), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by_name: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)


class AnalysisPolicyVersion(Base):
    __tablename__ = "analysis_policy_version"
    __table_args__ = (UniqueConstraint("version", name="uq_analysis_policy_version_version"),)

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    model_endpoint_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompts: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    validation_rules: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


# ---------------------------------------------------------------------------
# Analysis (11 tables)
# ---------------------------------------------------------------------------


class DeepReview(Base):
    __tablename__ = "deep_review"
    __table_args__ = (
        UniqueConstraint("notice_id", "bundle_id", "profile_version_id", "policy_version_id", name="uq_deep_review_inputs"),
        UniqueConstraint("id", "notice_id", name="uq_deep_review_notice_scope"),
        UniqueConstraint("id", "bundle_id", name="uq_deep_review_bundle_scope"),
        UniqueConstraint("id", "profile_version_id", name="uq_deep_review_profile_scope"),
        ForeignKeyConstraint(["id", "current_attempt_id"], [_table("deep_review_attempt.deep_review_id"), _table("deep_review_attempt.id")], name="fk_deep_review_current_attempt_scope", use_alter=True),
        CheckConstraint("status IN ('queued','running','completed','failed')", name="ck_deep_review_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id"), nullable=False)
    bundle_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_bundle.id"), nullable=False)
    profile_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("profile_version.id"), nullable=False)
    policy_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("analysis_policy_version.id"), nullable=False)
    effective_grade_at_start: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_attempt_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    requested_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


class DeepReviewAttempt(Base):
    __tablename__ = "deep_review_attempt"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "sequence", name="uq_deep_review_attempt_sequence"),
        UniqueConstraint("deep_review_id", "id", name="uq_deep_review_attempt_scope"),
        Index("uq_deep_review_attempt_active", "deep_review_id", unique=True, postgresql_where=column("status").in_(["queued", "running"])),
        CheckConstraint("status IN ('queued','running','completed','failed','superseded')", name="ck_deep_review_attempt_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    work_job_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("work_job.id"), nullable=True)
    lease_fence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    requested_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


class DeepReviewStage(Base):
    __tablename__ = "deep_review_stage"
    __table_args__ = (
        UniqueConstraint("attempt_id", "stage", name="uq_deep_review_stage_name"),
        UniqueConstraint("attempt_id", "sequence", name="uq_deep_review_stage_sequence"),
        CheckConstraint("stage IN ('requirements_and_evaluation','delivery_risk_economics','synthesis_and_validation')", name="ck_deep_review_stage_name"),
        CheckConstraint("status IN ('queued','running','completed','failed')", name="ck_deep_review_stage_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    attempt_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review_attempt.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    structured_output: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    invocation_metadata: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    raw_response_content_object_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


class Claim(Base):
    __tablename__ = "claim"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "id", name="uq_claim_scope"),
        CheckConstraint("claim_type IN ('fact','calculation','inference','opinion','unknown')", name="ck_claim_type"),
        CheckConstraint("status IN ('supported','unsupported','conflicting','unknown')", name="ck_claim_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    stage_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review_stage.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    premise_claim_ids: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRef(Base):
    __tablename__ = "evidence_ref"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "id", name="uq_evidence_ref_scope"),
        ForeignKeyConstraint(["deep_review_id", "notice_id"], [_table("deep_review.id"), _table("deep_review.notice_id")], name="fk_evidence_notice_review_scope"),
        ForeignKeyConstraint(["deep_review_id", "bundle_id"], [_table("deep_review.id"), _table("deep_review.bundle_id")], name="fk_evidence_document_review_scope"),
        ForeignKeyConstraint(["bundle_id", "document_version_id", "structure_id"], [_table("document_bundle_item.bundle_id"), _table("document_bundle_item.document_version_id"), _table("document_bundle_item.structure_id_at_confirmation")], name="fk_evidence_document_bundle_scope"),
        ForeignKeyConstraint(["deep_review_id", "profile_version_id"], [_table("deep_review.id"), _table("deep_review.profile_version_id")], name="fk_evidence_profile_review_scope"),
        ForeignKeyConstraint(["profile_version_id", "profile_evidence_id"], [_table("profile_evidence.profile_version_id"), _table("profile_evidence.id")], name="fk_evidence_profile_scope"),
        CheckConstraint("(source_kind = 'document' AND bundle_id IS NOT NULL AND document_version_id IS NOT NULL AND structure_id IS NOT NULL AND profile_version_id IS NULL AND profile_evidence_id IS NULL) OR (source_kind = 'profile' AND bundle_id IS NULL AND document_version_id IS NULL AND structure_id IS NULL AND profile_version_id IS NOT NULL AND profile_evidence_id IS NOT NULL)", name="ck_evidence_ref_source_union"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id"), nullable=False)
    bundle_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    document_version_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    structure_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    profile_version_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    profile_evidence_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    locator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["deep_review_id", "claim_id"], [_table("claim.deep_review_id"), _table("claim.id")], name="fk_claim_evidence_claim_scope"),
        ForeignKeyConstraint(["deep_review_id", "evidence_ref_id"], [_table("evidence_ref.deep_review_id"), _table("evidence_ref.id")], name="fk_claim_evidence_ref_scope"),
    )

    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    claim_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evidence_ref_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ReportRevision(Base):
    __tablename__ = "report_revision"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "sequence", name="uq_report_revision_sequence"),
        UniqueConstraint("deep_review_id", "id", name="uq_report_revision_scope"),
        ForeignKeyConstraint(["deep_review_id", "parent_revision_id"], [_table("report_revision.deep_review_id"), _table("report_revision.id")], name="fk_report_revision_parent_scope"),
        CheckConstraint("origin IN ('machine','human')", name="ck_report_revision_origin"),
        CheckConstraint("(origin = 'machine' AND created_by_name IS NULL AND parent_revision_id IS NULL AND change_reason IS NULL) OR (origin = 'human' AND created_by_name IS NOT NULL AND parent_revision_id IS NOT NULL AND change_reason IS NOT NULL)", name="ck_report_revision_immutability_metadata"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[uuid_module.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    report_payload: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class ReportRevisionEvidence(Base):
    __tablename__ = "report_revision_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["deep_review_id", "report_revision_id"], [_table("report_revision.deep_review_id"), _table("report_revision.id")], name="fk_report_revision_evidence_revision_scope"),
        ForeignKeyConstraint(["deep_review_id", "evidence_ref_id"], [_table("evidence_ref.deep_review_id"), _table("evidence_ref.id")], name="fk_report_revision_evidence_ref_scope"),
    )

    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    report_revision_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    evidence_ref_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)


class ValidationRun(Base):
    __tablename__ = "validation_run"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "sequence", name="uq_validation_run_sequence"),
        UniqueConstraint("deep_review_id", "id", name="uq_validation_run_scope"),
        UniqueConstraint("deep_review_id", "report_revision_id", "id", "status", name="uq_validation_run_revision_status_scope"),
        ForeignKeyConstraint(["deep_review_id", "report_revision_id"], [_table("report_revision.deep_review_id"), _table("report_revision.id")], name="fk_validation_run_revision_scope"),
        UniqueConstraint("id", "status", name="uq_validation_run_status"),
        CheckConstraint("status IN ('passed','failed')", name="ck_validation_run_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    report_revision_id: Mapped[uuid_module.UUID] = mapped_column(_fk("report_revision.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class ValidationCheck(Base):
    __tablename__ = "validation_check"
    __table_args__ = (
        CheckConstraint("status IN ('passed','failed','warning')", name="ck_validation_check_status"),
        CheckConstraint("severity IN ('차단','중대','보통','낮음')", name="ck_validation_check_severity"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    validation_run_id: Mapped[uuid_module.UUID] = mapped_column(_fk("validation_run.id"), nullable=False)
    check_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_claim_ids: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    related_evidence_ids: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)


class FinalOpinion(Base):
    __tablename__ = "final_opinion"
    __table_args__ = (
        UniqueConstraint("deep_review_id", "sequence", name="uq_final_opinion_sequence"),
        ForeignKeyConstraint(["deep_review_id", "report_revision_id"], [_table("report_revision.deep_review_id"), _table("report_revision.id")], name="fk_final_opinion_revision_scope"),
        ForeignKeyConstraint(["validation_run_id", "validation_status_at_opinion"], [_table("validation_run.id"), _table("validation_run.status")], name="fk_final_opinion_validation_snapshot"),
        ForeignKeyConstraint(["deep_review_id", "report_revision_id", "validation_run_id", "validation_status_at_opinion"], [_table("validation_run.deep_review_id"), _table("validation_run.report_revision_id"), _table("validation_run.id"), _table("validation_run.status")], name="fk_final_opinion_validation_revision_scope"),
        CheckConstraint("value IN ('추진','조건부 추진','보류','검토 종료')", name="ck_final_opinion_value"),
        CheckConstraint("(validation_status_at_opinion = 'passed' OR (acknowledged_validation_failure = TRUE AND reason IS NOT NULL AND length(trim(reason)) > 0))", name="ck_final_opinion_failed_ack"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    deep_review_id: Mapped[uuid_module.UUID] = mapped_column(_fk("deep_review.id"), nullable=False)
    report_revision_id: Mapped[uuid_module.UUID] = mapped_column(_fk("report_revision.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    validation_run_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    validation_status_at_opinion: Mapped[str] = mapped_column(String(16), nullable=False)
    acknowledged_validation_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    claimed_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


# ---------------------------------------------------------------------------
# Ops (3 tables)
# ---------------------------------------------------------------------------


class WorkJob(Base):
    __tablename__ = "work_job"
    __table_args__ = (
        Index("uq_work_job_active", "job_type", "aggregate_type", "aggregate_id", unique=True, postgresql_where=column("status").in_(["queued", "running"])),
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_work_job_status"),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    lease_fence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    scheduled_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


# This queue is deliberately separate from the Lean v1 set.  Revision 0001
# creates the original 25-table model; revision 0008 introduces this table so
# an existing 0007 database can be upgraded without recreating its baseline.
ATTACHMENT_FETCH_TABLES = ("attachment_fetch",)


PRESPEC_OVERVIEW_TABLES = (
    "prespec_page_overview",
    "prespec_overview_review",
    "prespec_overview_snapshot",
    "prespec_overview_attempt",
    "prespec_overview_result",
    "prespec_overview_attempt_event",
)


BID_DELTA_TABLES = (
    "bid_delta_comparison", "bid_delta_attempt", "bid_delta_item",
    "bid_delta_evidence", "bid_final_decision",
)


# 0018이 더하는 결정적 segment·요구사항 inventory 저장소. Lean v1 집합과 따로
# 두어 기존 데이터베이스가 재생성 없이 올라간다.
DOCUMENT_SEGMENT_TABLES = (
    "document_segment_manifest",
    "document_segment",
    "requirement_inventory_item",
)


class BidDeltaComparison(Base):
    """An immutable exact document pair used for a bid delta calculation."""

    __tablename__ = "bid_delta_comparison"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "sequence", name="uq_bid_delta_comparison_sequence"
        ),
        UniqueConstraint(
            "id", "opportunity_id", name="uq_bid_delta_comparison_opportunity_scope"
        ),
        UniqueConstraint(
            "opportunity_id",
            "baseline_document_version_id",
            "comparison_document_version_id",
            "category_policy_version",
            name="uq_bid_delta_comparison_inputs",
        ),
        ForeignKeyConstraint(
            ["id", "current_attempt_id"],
            ["bid_delta_attempt.comparison_id", "bid_delta_attempt.id"],
            name="fk_bid_delta_comparison_current_attempt_scope",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["baseline_link_id", "opportunity_id"],
            ["opportunity_link.id", "opportunity_link.opportunity_id"],
            name="fk_bid_delta_comparison_baseline_link_opportunity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["comparison_link_id", "opportunity_id"],
            ["opportunity_link.id", "opportunity_link.opportunity_id"],
            name="fk_bid_delta_comparison_comparison_link_opportunity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["baseline_link_id", "baseline_notice_id"],
            ["opportunity_link.id", "opportunity_link.notice_id"],
            name="fk_bid_delta_comparison_baseline_link_notice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["comparison_link_id", "comparison_notice_id"],
            ["opportunity_link.id", "opportunity_link.notice_id"],
            name="fk_bid_delta_comparison_comparison_link_notice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["baseline_bundle_id", "baseline_notice_id"],
            ["document_bundle.id", "document_bundle.notice_id"],
            name="fk_bid_delta_comparison_baseline_bundle_notice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["comparison_bundle_id", "comparison_notice_id"],
            ["document_bundle.id", "document_bundle.notice_id"],
            name="fk_bid_delta_comparison_comparison_bundle_notice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "baseline_bundle_id",
                "baseline_document_version_id",
                "baseline_structure_id",
            ],
            [
                "document_bundle_item.bundle_id",
                "document_bundle_item.document_version_id",
                "document_bundle_item.structure_id_at_confirmation",
            ],
            name="fk_bid_delta_comparison_baseline_bundle_item_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "comparison_bundle_id",
                "comparison_document_version_id",
                "comparison_structure_id",
            ],
            [
                "document_bundle_item.bundle_id",
                "document_bundle_item.document_version_id",
                "document_bundle_item.structure_id_at_confirmation",
            ],
            name="fk_bid_delta_comparison_comparison_bundle_item_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "baseline_document_version_id <> comparison_document_version_id",
            name="ck_bid_delta_comparison_different_documents",
        ),
        CheckConstraint(
            "calculation_status IN ('pending','running','completed','failed')",
            name="ck_bid_delta_comparison_calculation_status",
        ),
        CheckConstraint(
            "result_status IS NULL OR result_status IN "
            "('changed','unchanged','unknown','failed')",
            name="ck_bid_delta_comparison_result_status",
        ),
        CheckConstraint(
            "materiality IN ('material','non_material','unknown')",
            name="ck_bid_delta_comparison_materiality",
        ),
        CheckConstraint(
            "((calculation_status = 'pending' AND result_status IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL AND result_sha256 IS NULL) "
            "OR (calculation_status = 'running' AND result_status IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND result_sha256 IS NULL) "
            "OR (calculation_status = 'completed' "
            "AND result_status IN ('changed','unchanged','unknown') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND result_sha256 IS NOT NULL AND last_error_code IS NULL) "
            "OR (calculation_status = 'failed' AND result_status = 'failed' "
            "AND completed_at IS NOT NULL AND last_error_code IS NOT NULL "
            "AND result_sha256 IS NULL))",
            name="ck_bid_delta_comparison_lifecycle",
        ),
        CheckConstraint(
            "((result_status = 'unchanged' AND materiality = 'non_material') "
            "OR (result_status IN ('unknown','failed') AND materiality = 'unknown') "
            "OR (result_status = 'changed' AND materiality IN "
            "('material','non_material','unknown')) "
            "OR (result_status IS NULL AND materiality = 'unknown'))",
            name="ck_bid_delta_comparison_result_materiality",
        ),
        CheckConstraint(
            DualSQL(
                "length(baseline_source_sha256) = 64 AND "
                "baseline_source_sha256 NOT GLOB '*[^0-9a-f]*' AND "
                "length(baseline_structure_payload_sha256) = 64 AND "
                "baseline_structure_payload_sha256 NOT GLOB '*[^0-9a-f]*' AND "
                "length(comparison_source_sha256) = 64 AND "
                "comparison_source_sha256 NOT GLOB '*[^0-9a-f]*' AND "
                "length(comparison_structure_payload_sha256) = 64 AND "
                "comparison_structure_payload_sha256 NOT GLOB '*[^0-9a-f]*'",
                "baseline_source_sha256 ~ '^[0-9a-f]{64}$' AND "
                "baseline_structure_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
                "comparison_source_sha256 ~ '^[0-9a-f]{64}$' AND "
                "comparison_structure_payload_sha256 ~ '^[0-9a-f]{64}$'",
            ),
            name="ck_bid_delta_comparison_input_sha256",
        ),
        CheckConstraint(
            DualSQL(
                "result_sha256 IS NULL OR "
                "(length(result_sha256) = 64 AND "
                "result_sha256 NOT GLOB '*[^0-9a-f]*')",
                "result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'",
            ),
            name="ck_bid_delta_comparison_result_sha256",
        ),
        CheckConstraint(
            "length(trim(created_by_name)) > 0",
            name="ck_bid_delta_comparison_created_by_name",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(_fk("opportunity.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    category_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    baseline_link_id: Mapped[int] = mapped_column(_fk("opportunity_link.id", ondelete="RESTRICT"), nullable=False)
    baseline_notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    baseline_bundle_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_bundle.id", ondelete="RESTRICT"), nullable=False)
    baseline_bundle_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_bundle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    baseline_document_version_version: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_structure_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_structure.id", ondelete="RESTRICT"), nullable=False)
    baseline_source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_structure_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    comparison_link_id: Mapped[int] = mapped_column(_fk("opportunity_link.id", ondelete="RESTRICT"), nullable=False)
    comparison_notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    comparison_bundle_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_bundle.id", ondelete="RESTRICT"), nullable=False)
    comparison_bundle_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_bundle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    comparison_document_version_version: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_structure_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_structure.id", ondelete="RESTRICT"), nullable=False)
    comparison_source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    comparison_structure_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    calculation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False)
    current_attempt_id: Mapped[uuid_module.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)


class BidDeltaAttempt(Base):
    """One append-only calculation attempt for a comparison."""

    __tablename__ = "bid_delta_attempt"
    __table_args__ = (
        UniqueConstraint("comparison_id", "sequence", name="uq_bid_delta_attempt_sequence"),
        UniqueConstraint("comparison_id", "id", name="uq_bid_delta_attempt_scope"),
        Index(
            "uq_bid_delta_attempt_active",
            "comparison_id",
            unique=True,
            postgresql_where=column("status").in_(["queued", "running"]),
            sqlite_where=column("status").in_(["queued", "running"]),
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_bid_delta_attempt_status",
        ),
        CheckConstraint(
            "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND last_error_code IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) "
            "OR (status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND last_error_code IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL "
            "AND last_error_code IS NOT NULL))",
            name="ck_bid_delta_attempt_lifecycle",
        ),
        CheckConstraint(
            DualSQL(
                "runtime_binding_digest IS NULL OR "
                "(length(runtime_binding_digest) = 64 AND "
                "runtime_binding_digest NOT GLOB '*[^0-9a-f]*')",
                "runtime_binding_digest IS NULL OR runtime_binding_digest ~ '^[0-9a-f]{64}$'",
            ),
            name="ck_bid_delta_attempt_runtime_binding_digest",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    comparison_id: Mapped[uuid_module.UUID] = mapped_column(_fk("bid_delta_comparison.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    work_job_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("work_job.id", ondelete="RESTRICT"), nullable=True)
    lease_fence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    requested_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_binding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runtime_binding_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class BidDeltaItem(Base):
    """One category result belonging to an immutable attempt."""

    __tablename__ = "bid_delta_item"
    __table_args__ = (
        UniqueConstraint("attempt_id", "category", name="uq_bid_delta_item_category"),
        Index("ix_bid_delta_item_comparison", "comparison_id"),
        UniqueConstraint("attempt_id", "ordinal", name="uq_bid_delta_item_ordinal"),
        UniqueConstraint("id", "attempt_id", name="uq_bid_delta_item_attempt_scope"),
        ForeignKeyConstraint(
            ["attempt_id", "comparison_id"],
            ["bid_delta_attempt.id", "bid_delta_attempt.comparison_id"],
            name="fk_bid_delta_item_attempt_comparison_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "category IN ('budget_and_economics','contract_period_and_schedule',"
            "'eligibility','joint_supply_and_subcontracting','scope_and_requirements',"
            "'evaluation','submission')",
            name="ck_bid_delta_item_category",
        ),
        CheckConstraint(
            "result_status IN ('changed','unchanged','unknown','failed')",
            name="ck_bid_delta_item_result_status",
        ),
        CheckConstraint(
            "materiality IN ('material','non_material','unknown')",
            name="ck_bid_delta_item_materiality",
        ),
        CheckConstraint(
            "((result_status = 'unchanged' AND materiality = 'non_material') "
            "OR (result_status IN ('unknown','failed') AND materiality = 'unknown') "
            "OR (result_status = 'changed' AND materiality IN "
            "('material','non_material','unknown'))) ",
            name="ck_bid_delta_item_result_materiality",
        ),
        CheckConstraint(
            "((result_status IN ('unknown','failed') AND error_code IS NOT NULL "
            "AND length(trim(error_code)) > 0) "
            "OR (result_status IN ('changed','unchanged') AND error_code IS NULL))",
            name="ck_bid_delta_item_error_code",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    comparison_id: Mapped[uuid_module.UUID] = mapped_column(_fk("bid_delta_comparison.id", ondelete="RESTRICT"), nullable=False)
    attempt_id: Mapped[uuid_module.UUID] = mapped_column(_fk("bid_delta_attempt.id", ondelete="RESTRICT"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False)
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class BidDeltaEvidence(Base):
    """A verified or failed locator for one side of a delta item."""

    __tablename__ = "bid_delta_evidence"
    __table_args__ = (
        UniqueConstraint("item_id", "side", "ordinal", name="uq_bid_delta_evidence_scope"),
        CheckConstraint("side IN ('baseline','comparison')", name="ck_bid_delta_evidence_side"),
        CheckConstraint(
            "locator_type IN ('page','paragraph','table_cell','bbox')",
            name="ck_bid_delta_evidence_locator_type",
        ),
        CheckConstraint(
            "verification_status IN ('verified','missing','mismatch')",
            name="ck_bid_delta_evidence_verification_status",
        ),
        CheckConstraint(
            DualSQL(
                "length(source_sha256) = 64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'",
                "source_sha256 ~ '^[0-9a-f]{64}$'",
            ),
            name="ck_bid_delta_evidence_source_sha256",
        ),
        CheckConstraint(
            dual("json_valid(locator) AND json_type(locator) = 'object'"),
            name="ck_bid_delta_evidence_locator_object",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    item_id: Mapped[uuid_module.UUID] = mapped_column(_fk("bid_delta_item.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    structure_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_structure.id", ondelete="RESTRICT"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_type: Mapped[str] = mapped_column(String(16), nullable=False)
    locator: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class BidFinalDecision(Base):
    """An append-only human Go/No-Go decision for a completed comparison."""

    __tablename__ = "bid_final_decision"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "sequence", name="uq_bid_final_decision_sequence"),
        Index("ix_bid_final_decision_comparison", "comparison_id"),
        UniqueConstraint("opportunity_id", "id", name="uq_bid_final_decision_opportunity_scope"),
        UniqueConstraint(
            "opportunity_id",
            "supersedes_final_decision_id",
            name="uq_bid_final_decision_supersession",
        ),
        UniqueConstraint(
            "claimed_name", "opportunity_id", "request_id",
            name="uq_bid_final_decision_idempotency",
        ),
        ForeignKeyConstraint(
            ["opportunity_id", "supersedes_final_decision_id"],
            ["bid_final_decision.opportunity_id", "bid_final_decision.id"],
            name="fk_bid_final_decision_supersedes_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["comparison_id", "opportunity_id"],
            ["bid_delta_comparison.id", "bid_delta_comparison.opportunity_id"],
            name="fk_bid_final_decision_comparison_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision IN ('go','no_go')", name="ck_bid_final_decision_value"),
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_bid_final_decision_reason"
        ),
        CheckConstraint(
            "length(trim(claimed_name)) > 0", name="ck_bid_final_decision_claimed_name"
        ),
        CheckConstraint(
            DualSQL(
                "length(result_sha256) = 64 AND result_sha256 NOT GLOB '*[^0-9a-f]*'",
                "result_sha256 ~ '^[0-9a-f]{64}$'",
            ),
            name="ck_bid_final_decision_result_sha256",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(_fk("opportunity.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_id: Mapped[uuid_module.UUID] = mapped_column(_fk("bid_delta_comparison.id", ondelete="RESTRICT"), nullable=False)
    comparison_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    comparison_document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    supersedes_final_decision_id: Mapped[uuid_module.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    claimed_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[uuid_module.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


_BID_DELTA_COMPARISON_INPUT_FENCE_FIELDS = frozenset(
    {
        "baseline_link_id",
        "baseline_notice_id",
        "baseline_bundle_id",
        "baseline_bundle_revision",
        "baseline_bundle_version",
        "baseline_document_version_id",
        "baseline_document_version_version",
        "baseline_structure_id",
        "baseline_source_sha256",
        "baseline_structure_payload_sha256",
        "comparison_link_id",
        "comparison_notice_id",
        "comparison_bundle_id",
        "comparison_bundle_revision",
        "comparison_bundle_version",
        "comparison_document_version_id",
        "comparison_document_version_version",
        "comparison_structure_id",
        "comparison_source_sha256",
        "comparison_structure_payload_sha256",
        "category_policy_version",
        "opportunity_id",
        "sequence",
        "created_by_name",
        "created_at",
    }
)


@event.listens_for(BidFinalDecision, "before_update")
@event.listens_for(BidFinalDecision, "before_delete")
def _reject_bid_final_decision_mutation(
    _mapper: Any, _connection: Any, _target: BidFinalDecision
) -> None:
    raise ValueError("bid final decisions are append-only")


# segment manifest와 그 자식 행은 갱신·삭제가 없다 (명세 §6.7). 재계산은 새 행이
# 아니라 같은 유일 키의 기존 행을 돌려준다. 부모 구조·문서 version이 사라질 때만
# DB FK ``ondelete=CASCADE``가 함께 지운다 — 그 경로는 ORM을 거치지 않으므로 여기의
# 방어가 cascade를 막지 않는다.
@event.listens_for(DocumentSegmentManifest, "before_update")
@event.listens_for(DocumentSegmentManifest, "before_delete")
@event.listens_for(DocumentSegment, "before_update")
@event.listens_for(DocumentSegment, "before_delete")
@event.listens_for(RequirementInventoryItem, "before_update")
@event.listens_for(RequirementInventoryItem, "before_delete")
def _reject_document_segment_mutation(
    _mapper: Any, _connection: Any, _target: Any
) -> None:
    raise ValueError("document segment manifests are append-only")


@event.listens_for(BidDeltaItem, "before_update")
@event.listens_for(BidDeltaItem, "before_delete")
def _reject_bid_delta_item_mutation(
    _mapper: Any, _connection: Any, _target: BidDeltaItem
) -> None:
    raise ValueError("bid delta items are append-only")


@event.listens_for(BidDeltaEvidence, "before_update")
@event.listens_for(BidDeltaEvidence, "before_delete")
def _reject_bid_delta_evidence_mutation(
    _mapper: Any, _connection: Any, _target: BidDeltaEvidence
) -> None:
    raise ValueError("bid delta evidence is append-only")


@event.listens_for(BidDeltaAttempt, "before_update")
def _validate_bid_delta_attempt_update(
    _mapper: Any, connection: Any, target: BidDeltaAttempt
) -> None:
    state = sa_inspect(target)
    status_history = state.attrs.status.history
    previous = status_history.deleted[-1] if status_history.deleted else connection.execute(
        select(BidDeltaAttempt.status).where(BidDeltaAttempt.id == target.id)
    ).scalar_one_or_none()
    if previous in {"completed", "failed"}:
        raise ValueError("terminal bid delta attempts are immutable")


@event.listens_for(BidDeltaAttempt, "before_delete")
def _reject_bid_delta_attempt_delete(
    _mapper: Any, connection: Any, target: BidDeltaAttempt
) -> None:
    previous = connection.execute(
        select(BidDeltaAttempt.status).where(BidDeltaAttempt.id == target.id)
    ).scalar_one_or_none()
    if previous in {"completed", "failed"}:
        raise ValueError("terminal bid delta attempts are immutable")


@event.listens_for(BidDeltaComparison, "before_update")
def _validate_bid_delta_comparison_update(
    _mapper: Any, connection: Any, target: BidDeltaComparison
) -> None:
    state = sa_inspect(target)
    changed_fence = sorted(
        name
        for name in _BID_DELTA_COMPARISON_INPUT_FENCE_FIELDS
        if state.attrs[name].history.has_changes()
    )
    if changed_fence:
        raise ValueError("bid delta comparison input fence is immutable")

    status_history = state.attrs.calculation_status.history
    previous = status_history.deleted[-1] if status_history.deleted else connection.execute(
        select(BidDeltaComparison.calculation_status).where(
            BidDeltaComparison.id == target.id
        )
    ).scalar_one_or_none()
    if previous == "completed" and any(
        state.attrs[name].history.has_changes()
        for name in (
            "result_status",
            "result_sha256",
            "materiality",
            "calculation_status",
        )
    ):
        raise ValueError("completed bid delta comparison result is immutable")


# ``0001_lean_v1_postgresql``이 만드는 25개 Lean v1 새 테이블 중 deep_review
# 몫이다. 나머지 2개는 core가 ``CORE_LEAN_V1_TABLES``로 갖고 있고, 합집합은
# 그 revision과 테스트가 조립한다 (명세 §5.1).
DEEP_REVIEW_LEAN_V1_TABLES = (
    "content_object", "content_object_location", "content_scan", "document_version", "document_structure",
    "document_block", "document_bundle", "document_bundle_item", "profile_version", "profile_evidence",
    "analysis_policy_version", "deep_review", "deep_review_attempt", "deep_review_stage", "claim", "evidence_ref",
    "claim_evidence", "report_revision", "report_revision_evidence", "validation_run", "validation_check",
    "final_opinion", "work_job",
)


# R-08 합성 FK가 요구하는 대상 범위. 기존 모델 선언을 건드리지 않으려고 여기서
# 덧붙인다 (lifecycle의 OpportunityLink 몫은 app/lifecycle/models.py에 있다).
DocumentBundle.__table__.append_constraint(
    UniqueConstraint("id", "notice_id", name="uq_document_bundle_notice_scope")
)


class PreSpecPageOverview(Base):
    """Append-only descriptive reference, independent of recommendation lifecycle."""
    __tablename__ = "prespec_page_overview"
    __table_args__ = (
        UniqueConstraint("run_id", "notice_id", name="uq_prespec_page_overview_run_notice"),
        Index("ix_prespec_page_overview_notice_created", "notice_id", "created_at"),
        ForeignKeyConstraint(["notice_id", "document_version_id"],
                             [_table("document_version.notice_id"), _table("document_version.id")],
                             ondelete="RESTRICT", name="fk_prespec_page_overview_document_scope"),
        CheckConstraint("schema_version = 'bidops.prespec-overview-page-review.v3'", name="ck_prespec_page_overview_schema"),
        CheckConstraint("quality_status IN ('unmeasured_reference','mock_reference')", name="ck_prespec_page_overview_quality"),
        CheckConstraint("validation_status IN ('passed','failed') AND evidence_check_status IN ('passed','failed')", name="ck_prespec_page_overview_validation"),
        CheckConstraint("validation_status <> 'passed' OR evidence_check_status = 'passed'", name="ck_prespec_page_overview_passed"),
        CheckConstraint("pdf_page_count > 0", name="ck_prespec_page_overview_pages"),
        CheckConstraint(dual(" AND ".join(f"length({field}) = 64 AND {field} NOT GLOB '*[^0-9a-f]*'" for field in ("source_sha256", "pdf_sha256", "payload_sha256", "import_sha256", "input_sha256", "model_digest", "policy_digest"))), name="ck_prespec_page_overview_hashes"),
        CheckConstraint(dual("json_valid(payload_jsonb) AND json_type(payload_jsonb) = 'object'"), name="ck_prespec_page_overview_payload"),
    )
    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    run_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    input_location_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=False)
    pdf_location_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    import_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    pdf_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_pages: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    payload_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_errors: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    evidence_check_status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_check_errors: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    validator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


@event.listens_for(PreSpecPageOverview, "before_update")
@event.listens_for(PreSpecPageOverview, "before_delete")
def _immutable_page_overview(*_args: Any) -> None:
    raise ValueError("page overview is append-only")


class PrespecV4PdfSnapshot(Base):
    """Immutable PDF/source binding owned by the v4 preparation boundary.

    Legacy overview rows remain separate. Native snapshots pin a verified
    ``DocumentStructure`` and its payload location; repeated preparation never
    replaces the structure consumed by existing reviews.
    """

    __tablename__ = "prespec_v4_pdf_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "source_sha256",
            "config_sha256",
            "renderer_digest",
            "font_digest",
            name="uq_prespec_v4_pdf_snapshot_identity",
        ),
        UniqueConstraint(
            "document_version_id", "id", name="uq_prespec_v4_pdf_snapshot_document_scope"
        ),
        ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            [_table("document_version.notice_id"), _table("document_version.id")],
            ondelete="RESTRICT",
            name="fk_prespec_v4_pdf_snapshot_document_scope",
        ),
        CheckConstraint(
            "source_kind IN ('original','generated')",
            name="ck_prespec_v4_pdf_snapshot_source_kind",
        ),
        CheckConstraint("source_size_bytes > 0 AND pdf_size_bytes > 0", name="ck_prespec_v4_pdf_snapshot_sizes"),
        CheckConstraint("pdf_page_count > 0", name="ck_prespec_v4_pdf_snapshot_pages"),
        CheckConstraint(
            dual(
                " AND ".join(
                    f"length({field}) = 64 AND {field} NOT GLOB '*[^0-9a-f]*'"
                    for field in (
                        "source_sha256", "pdf_sha256", "page_text_sha256", "config_sha256",
                        "renderer_digest", "font_digest", "binding_sha256",
                    )
                )
            ),
            name="ck_prespec_v4_pdf_snapshot_hashes",
        ),
        CheckConstraint(
            dual(
                "json_valid(pdf_metadata_jsonb) AND json_type(pdf_metadata_jsonb) = 'object'"
            ),
            name="ck_prespec_v4_pdf_snapshot_metadata",
        ),
        CheckConstraint(
            dual(
                "json_valid(renderer_jsonb) AND json_type(renderer_jsonb) = 'object'"
            ),
            name="ck_prespec_v4_pdf_snapshot_renderer",
        ),
        CheckConstraint(
            dual("json_valid(font_jsonb) AND json_type(font_jsonb) = 'object'"),
            name="ck_prespec_v4_pdf_snapshot_font",
        ),
        CheckConstraint(
            dual("json_valid(config_jsonb) AND json_type(config_jsonb) = 'object'"),
            name="ck_prespec_v4_pdf_snapshot_config",
        ),
        CheckConstraint(
            dual("json_valid(scan_jsonb) AND json_type(scan_jsonb) = 'object'"),
            name="ck_prespec_v4_pdf_snapshot_scan",
        ),
        CheckConstraint(
            dual(
                "length(page_text_sha256) = 64 AND page_text_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_v4_pdf_snapshot_page_text_hash",
        ),
        CheckConstraint(
            "page_text_size_bytes > 0",
            name="ck_prespec_v4_pdf_snapshot_page_text_size",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    source_content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=False)
    source_location_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=False)
    pdf_content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=False)
    pdf_location_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=False)
    page_text_content_object_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=False)
    page_text_location_id: Mapped[uuid_module.UUID] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=False)
    hwpx_content_object_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=True)
    hwpx_location_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=True)
    structure_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("document_structure.id", ondelete="RESTRICT"), nullable=True)
    structure_location_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=True)
    para_page_map_content_object_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=True)
    para_page_map_location_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=True)
    section_candidates_content_object_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=True)
    section_candidates_location_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=True)
    hwpx_verify_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    para_page_map_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_candidates_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rhwp_binary_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rhwp_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pdf_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_text_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pdf_metadata_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    renderer_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    renderer_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    font_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    font_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    config_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class PrespecV4Target(Base):
    """Frozen prepared input for one PDF snapshot.

    This row is deliberately not the later policy/current target.  It exists
    only after a verified snapshot and records the immutable input manifest
    (or a deterministic human-review boundary).  Policy eligibility and model
    attempts belong to a later contract.
    """

    __tablename__ = "prespec_v4_target"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "identity_sha256",
            name="uq_prespec_v4_target_identity",
        ),
        UniqueConstraint("document_version_id", "id", name="uq_prespec_v4_target_document_scope"),
        ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            [_table("document_version.notice_id"), _table("document_version.id")],
            ondelete="RESTRICT",
            name="fk_prespec_v4_target_document_scope",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "snapshot_id"],
            [_table("prespec_v4_pdf_snapshot.document_version_id"), _table("prespec_v4_pdf_snapshot.id")],
            ondelete="RESTRICT",
            name="fk_prespec_v4_target_snapshot_document_scope",
        ),
        CheckConstraint(
            "selection_status IN ('ready','needs_human_review','excluded')",
            name="ck_prespec_v4_target_selection_status",
        ),
        CheckConstraint(
            "observation_kind IN ('explicit_sample','first_observation','attachment_change')",
            name="ck_prespec_v4_target_observation_kind",
        ),
        CheckConstraint(
            "(observation_kind = 'explicit_sample' AND observation_id IS NULL) OR "
            "(observation_kind <> 'explicit_sample' AND observation_id IS NOT NULL)",
            name="ck_prespec_v4_target_observation_binding",
        ),
        CheckConstraint(
            "((selection_status = 'ready' AND input_sha256 IS NOT NULL AND input_byte_count > 0 "
            "AND selection_manifest_sha256 IS NOT NULL AND manifest_content_object_id IS NOT NULL "
            "AND manifest_location_id IS NOT NULL "
            "AND start_locator IS NOT NULL AND end_locator IS NOT NULL AND page_numbers_jsonb IS NOT NULL) "
            "OR (selection_status IN ('needs_human_review','excluded') AND reason_code IS NOT NULL))",
            name="ck_prespec_v4_target_selection_contract",
        ),
        CheckConstraint(
            dual(
                "json_valid(observation_jsonb) AND json_type(observation_jsonb) = 'object'"
            ),
            name="ck_prespec_v4_target_observation_json",
        ),
        CheckConstraint(
            dual(
                "start_locator IS NULL OR (json_valid(start_locator) AND json_type(start_locator) = 'object')"
            ),
            name="ck_prespec_v4_target_start_locator",
        ),
        CheckConstraint(
            dual(
                "end_locator IS NULL OR (json_valid(end_locator) AND json_type(end_locator) = 'object')"
            ),
            name="ck_prespec_v4_target_end_locator",
        ),
        CheckConstraint(
            dual(
                "page_numbers_jsonb IS NULL OR (json_valid(page_numbers_jsonb) AND json_type(page_numbers_jsonb) = 'array')"
            ),
            name="ck_prespec_v4_target_pages_json",
        ),
        CheckConstraint(
            dual(
                "input_text_sha256_jsonb IS NULL OR (json_valid(input_text_sha256_jsonb) AND json_type(input_text_sha256_jsonb) = 'array')"
            ),
            name="ck_prespec_v4_target_text_hashes_json",
        ),
        CheckConstraint(
            dual(
                "length(input_sha256) = 64 AND input_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_v4_target_input_hash",
        ),
        CheckConstraint(
            dual(
                "length(identity_sha256) = 64 AND identity_sha256 NOT GLOB '*[^0-9a-f]*'"
            ),
            name="ck_prespec_v4_target_identity_hash",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("document_version.id", ondelete="RESTRICT"), nullable=False)
    snapshot_id: Mapped[uuid_module.UUID] = mapped_column(_fk("prespec_v4_pdf_snapshot.id", ondelete="RESTRICT"), nullable=False)
    observation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_id: Mapped[int | None] = mapped_column(_fk("notice_observation.id", ondelete="RESTRICT"), nullable=True)
    observation_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    selection_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selection_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_locator: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    end_locator: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    page_numbers_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    input_text_sha256_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_byte_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    selection_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_content_object_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object.id", ondelete="RESTRICT"), nullable=True)
    manifest_location_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("content_object_location.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


class PrespecV4Attempt(Base):
    """One fenced v4 overview execution for one frozen target.

    The target and all input/model binding columns are immutable.  A failed
    preparation is represented by a notice-scoped terminal row with no target;
    this keeps the current API truthful before a PDF input exists without
    pretending that a policy attempt was eligible.
    """

    __tablename__ = "prespec_v4_attempt"
    __table_args__ = (
        Index("ix_prespec_v4_attempt_notice_created", "notice_id", "created_at"),
        Index(
            "uq_prespec_v4_attempt_active_target",
            "target_id",
            unique=True,
            postgresql_where=column("status").in_(["queued", "running"]),
            sqlite_where=column("status").in_(["queued", "running"]),
        ),
        UniqueConstraint("notice_id", "sequence", name="uq_prespec_v4_attempt_notice_sequence"),
        ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            [_table("document_version.notice_id"), _table("document_version.id")],
            ondelete="RESTRICT",
            name="fk_prespec_v4_attempt_document_scope",
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_prespec_v4_attempt_status",
        ),
        CheckConstraint(
            "quality_status IN ('unmeasured_reference','mock_reference')",
            name="ck_prespec_v4_attempt_quality",
        ),
        CheckConstraint(
            "(status IN ('queued','running','completed') AND target_id IS NOT NULL) OR "
            "(status IN ('failed','cancelled'))",
            name="ck_prespec_v4_attempt_target_scope",
        ),
        CheckConstraint(
            "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status IN ('failed','cancelled') AND completed_at IS NOT NULL AND result_id IS NULL) "
            "OR (status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND result_id IS NOT NULL))",
            name="ck_prespec_v4_attempt_completion",
        ),
        CheckConstraint(
            "(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_prespec_v4_attempt_lease",
        ),
        CheckConstraint(
            dual(
                " AND ".join(
                    f"({field} IS NULL OR (length({field}) = 64 AND {field} NOT GLOB '*[^0-9a-f]*'))"
                    for field in (
                        "source_sha256", "pdf_sha256", "input_sha256",
                        "selection_manifest_sha256", "policy_digest", "model_digest",
                        "binding_digest", "result_sha256", "raw_response_sha256",
                    )
                )
            ),
            name="ck_prespec_v4_attempt_hashes",
        ),
        CheckConstraint(
            "result_id IS NULL OR status = 'completed'",
            name="ck_prespec_v4_attempt_result_status",
        ),
        CheckConstraint(
            "(status = 'completed' AND result_id IS NOT NULL AND result_sha256 IS NOT NULL) "
            "OR (status <> 'completed' AND result_id IS NULL AND result_sha256 IS NULL)",
            name="ck_prespec_v4_attempt_result",
        ),
    )

    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID | None] = mapped_column(
        _fk("document_version.id", ondelete="RESTRICT"), nullable=True
    )
    target_id: Mapped[uuid_module.UUID | None] = mapped_column(
        _fk("prespec_v4_target.id", ondelete="RESTRICT"), nullable=True
    )
    work_job_id: Mapped[uuid_module.UUID | None] = mapped_column(
        _fk("work_job.id", ondelete="RESTRICT"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selection_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binding_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unmeasured_reference")
    reference_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deployable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", server_default=text("'queued'"))
    result_id: Mapped[uuid_module.UUID | None] = mapped_column(
        _fk("prespec_page_overview.id", ondelete="RESTRICT"), nullable=True
    )
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_warnings: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)


PRESPEC_V4_TABLES = (
    "prespec_v4_pdf_snapshot",
    "prespec_v4_target",
    "prespec_v4_attempt",
)


@event.listens_for(PrespecV4PdfSnapshot, "before_update")
@event.listens_for(PrespecV4PdfSnapshot, "before_delete")
@event.listens_for(PrespecV4Target, "before_update")
@event.listens_for(PrespecV4Target, "before_delete")
def _reject_prespec_v4_input_mutation(*_args: Any) -> None:
    raise ValueError("v4 PDF inputs are append-only")


@event.listens_for(PrespecV4Attempt, "before_delete")
def _reject_prespec_v4_attempt_delete(*_args: Any) -> None:
    raise ValueError("v4 attempts cannot be deleted")


@event.listens_for(PrespecV4Attempt, "before_insert")
def _check_prespec_v4_attempt_scope(_mapper: Any, connection: Any, target: PrespecV4Attempt) -> None:
    if target.target_id is not None:
        row = connection.execute(
            select(PrespecV4Target.notice_id, PrespecV4Target.document_version_id).where(
                PrespecV4Target.id == target.target_id
            )
        ).first()
        if row is None or row.notice_id != target.notice_id or row.document_version_id != target.document_version_id:
            raise ValueError("v4 attempt target scope mismatch")
    if target.result_id is not None:
        row = connection.execute(
            select(PreSpecPageOverview.notice_id, PreSpecPageOverview.document_version_id).where(
                PreSpecPageOverview.id == target.result_id
            )
        ).first()
        if row is None or row.notice_id != target.notice_id or row.document_version_id != target.document_version_id:
            raise ValueError("v4 attempt result scope mismatch")


@event.listens_for(PrespecV4Attempt, "before_update")
def _guard_prespec_v4_attempt_update(_mapper: Any, connection: Any, target: PrespecV4Attempt) -> None:
    state = sa_inspect(target)
    mutable = {
        "status", "result_id", "result_sha256", "raw_response_sha256", "error_code",
        "lease_owner", "lease_expires_at", "started_at", "completed_at",
        "prompt_tokens", "output_tokens", "latency_ms", "validation_warnings",
    }
    if any(state.attrs[column.key].history.has_changes() for column in target.__table__.columns if column.key not in mutable):
        raise ValueError("v4 attempt inputs are immutable")
    previous = state.attrs.status.history.deleted
    old_status = previous[0] if previous else target.status
    if old_status in {"completed", "failed", "cancelled"}:
        raise ValueError("terminal v4 attempts are immutable")
    if target.target_id is not None:
        row = connection.execute(
            select(PrespecV4Target.notice_id, PrespecV4Target.document_version_id).where(
                PrespecV4Target.id == target.target_id
            )
        ).first()
        if row is None or row.notice_id != target.notice_id or row.document_version_id != target.document_version_id:
            raise ValueError("v4 attempt target scope mismatch")
    if target.result_id is not None:
        row = connection.execute(
            select(PreSpecPageOverview.notice_id, PreSpecPageOverview.document_version_id).where(
                PreSpecPageOverview.id == target.result_id
            )
        ).first()
        if row is None or row.notice_id != target.notice_id or row.document_version_id != target.document_version_id:
            raise ValueError("v4 attempt result scope mismatch")


class PreSpecCompanyFitAttempt(Base):
    """Frozen inputs and a fenced lifecycle; terminal attempts are immutable."""
    __tablename__ = "prespec_company_fit_attempt"
    __table_args__ = (
        UniqueConstraint("input_sha256", name="uq_prespec_company_fit_input"),
        Index("ix_prespec_company_fit_notice_created", "notice_id", "created_at"),
        ForeignKeyConstraint(["notice_id", "document_version_id"],
                             [_table("document_version.notice_id"), _table("document_version.id")],
                             ondelete="RESTRICT", name="fk_prespec_company_fit_document_scope"),
        CheckConstraint("status IN ('queued','running','completed','failed','needs_human_review')", name="ck_prespec_company_fit_status"),
        CheckConstraint("quality_status IN ('unmeasured_reference','mock_reference')", name="ck_prespec_company_fit_quality"),
        CheckConstraint("(page_overview_id IS NOT NULL AND overview_result_id IS NULL) OR (page_overview_id IS NULL AND overview_result_id IS NOT NULL)", name="ck_prespec_company_fit_source"),
        CheckConstraint("(status = 'completed' AND result_jsonb IS NOT NULL AND result_sha256 IS NOT NULL) OR (status <> 'completed' AND result_jsonb IS NULL AND result_sha256 IS NULL)", name="ck_prespec_company_fit_result"),
        CheckConstraint("(status IN ('queued','running') AND completed_at IS NULL) OR (status IN ('completed','failed','needs_human_review') AND completed_at IS NOT NULL)", name="ck_prespec_company_fit_completion"),
        CheckConstraint("(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_prespec_company_fit_lease"),
        CheckConstraint(dual(" AND ".join(f"length({field}) = 64 AND {field} NOT GLOB '*[^0-9a-f]*'" for field in ("input_sha256", "policy_digest", "model_revision"))), name="ck_prespec_company_fit_hashes"),
    )
    id: Mapped[uuid_module.UUID] = _uuid_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(_fk("notice.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[uuid_module.UUID] = mapped_column(nullable=False)
    page_overview_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("prespec_page_overview.id", ondelete="RESTRICT"), nullable=True)
    overview_result_id: Mapped[uuid_module.UUID | None] = mapped_column(_fk("prespec_overview_result.id", ondelete="RESTRICT"), nullable=True)
    profile_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("profile_version.id", ondelete="RESTRICT"), nullable=False)
    deep_policy_version_id: Mapped[uuid_module.UUID] = mapped_column(_fk("analysis_policy_version.id", ondelete="RESTRICT"), nullable=False)
    input_jsonb: Mapped[Any] = mapped_column(JSONB_COMPAT, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    result_jsonb: Mapped[Any] = mapped_column(JSONB_NULL_COMPAT, nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


@event.listens_for(PreSpecCompanyFitAttempt, "before_delete")
def _immutable_company_fit_delete(*_args: Any) -> None:
    raise ValueError("company fit attempts cannot be deleted")


@event.listens_for(PreSpecCompanyFitAttempt, "before_update")
def _immutable_company_fit_input(_mapper: Any, _connection: Any, target: PreSpecCompanyFitAttempt) -> None:
    state = sa_inspect(target)
    mutable = {"status", "result_jsonb", "result_sha256", "raw_response_sha256", "error_code", "lease_owner", "lease_expires_at", "completed_at", "prompt_tokens", "output_tokens", "latency_ms"}
    if any(state.attrs[column.key].history.has_changes() for column in target.__table__.columns if column.key not in mutable):
        raise ValueError("company fit inputs are immutable")
    previous = state.attrs.status.history.deleted
    if (previous[0] if previous else target.status) in {"completed", "failed", "needs_human_review"}:
        raise ValueError("terminal company fit attempts are immutable")
