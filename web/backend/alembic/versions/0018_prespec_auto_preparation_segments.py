"""사전규격 자동 준비와 결정적 segment 저장소를 위한 스키마.

Revision ID: 0018_prespec_auto_preparation_segments
Revises: 0017_order_plan_screening_heartbeat

이 revision은 스키마만 바꾼다. 자격 계산, worker lease 사용, segment 추출은
각각 T6·T4·T8이 만든다. 여기서는 어떤 모델·외부 서버도 부르지 않는다.

담는 것 (명세 §7):

* ``attachment_fetch.ck_attachment_fetch_eligibility_reason``에 ``priority_grade``
  자격 사유를 더한다.
* ``prespec_overview_attempt``의 완료 CHECK를
  "``status <> 'completed' OR reference_only IS FALSE``"로 바꾼다. 품질을 아직
  재지 않은 실제 모델 실행(``deployable=false``)도 완료될 수 있고 mock 참조
  실행(``reference_only=true``)만 완료를 막는다는 뜻이다 (명세 §6.3).
  상태 전이 trigger는 그대로 둔다.
* 같은 표에 ``lease_owner``·``lease_expires_at``(둘 다 nullable)을 더한다.
* 결정적 segment·요구사항 inventory 저장소 세 표를 만든다 (명세 §6.7).

명세가 이름으로 가리킨 CHECK는 ``ck_prespec_overview_attempt_completion``이지만
"완료는 배포 가능 binding만"을 실제로 강제하는 것은
``ck_prespec_overview_attempt_completed_binding``이고, 명세가 인용한 새 본문도
그 CHECK의 모양이다. ``..._completion``은 status·시각·result 참조의 생애주기
불변식이라 그 본문으로 바꾸면 §7이 건드리지 말라고 한 불변식이 사라진다.
따라서 이름이 아니라 인용된 본문을 정본으로 읽어 ``..._completed_binding``을
교체한다.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_prespec_auto_preparation_segments"
down_revision = "0017_order_plan_screening_heartbeat"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
MIGRATION_EVENT_ID = "audit-6b3c8d0e5f14729a3b6c9d2e5f814703"

SEGMENT_TABLES = (
    "requirement_inventory_item",
    "document_segment",
    "document_segment_manifest",
)

_ELIGIBILITY_BEFORE = "eligibility_reason IN ('sw_business_object','tracked_order_plan','both')"
_ELIGIBILITY_AFTER = (
    "eligibility_reason IN ('sw_business_object','tracked_order_plan','both','priority_grade')"
)
_COMPLETED_BINDING_BEFORE = (
    "status <> 'completed' OR (reference_only IS FALSE AND deployable IS TRUE)"
)
_COMPLETED_BINDING_AFTER = "status <> 'completed' OR reference_only IS FALSE"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table_name=table, type_="check", schema=SCHEMA)
    op.create_check_constraint(name, table, condition, schema=SCHEMA)


def _create_segment_tables() -> None:
    op.create_table(
        "document_segment_manifest",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("structure_id", UUID, nullable=False),
        sa.Column("document_version_id", UUID, nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=64), nullable=False),
        sa.Column("extractor_binding", JSONB, nullable=False),
        sa.Column("extractor_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("inventory_summary", JSONB, nullable=False),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("coverage", JSONB, nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        # 재계산은 새 행이 아니라 같은 키의 기존 행을 돌려준다 (명세 §6.7).
        sa.UniqueConstraint(
            "structure_id",
            "taxonomy_version",
            "extractor_binding_sha256",
            name="uq_document_segment_manifest_identity",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$' "
            "AND extractor_binding_sha256 ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_segment_manifest_hashes",
        ),
        sa.CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name="ck_document_segment_manifest_taxonomy_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(extractor_binding) = 'object'",
            name="ck_document_segment_manifest_extractor_binding",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(inventory_summary) = 'object'",
            name="ck_document_segment_manifest_inventory_summary",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(warnings) = 'array'",
            name="ck_document_segment_manifest_warnings",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(coverage) = 'object'",
            name="ck_document_segment_manifest_coverage",
        ),
        sa.ForeignKeyConstraint(
            ["structure_id"],
            [f"{SCHEMA}.document_structure.id"],
            name="fk_document_segment_manifest_structure",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_document_segment_manifest_document_version",
            ondelete="CASCADE",
        ),
        # 다른 문서의 구조가 manifest에 붙는 경로를 DB가 직접 막는다.
        sa.ForeignKeyConstraint(
            ["document_version_id", "structure_id"],
            [
                f"{SCHEMA}.document_structure.document_version_id",
                f"{SCHEMA}.document_structure.id",
            ],
            name="fk_document_segment_manifest_structure_document_scope",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "document_segment",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("manifest_id", UUID, nullable=False),
        sa.Column("segment_id", sa.String(length=255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("taxonomy_labels", JSONB, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("start_locator", JSONB, nullable=False),
        sa.Column("end_locator", JSONB, nullable=False),
        sa.Column("requirement_ids", JSONB, nullable=False),
        sa.Column("source_block_keys", JSONB, nullable=False),
        sa.Column("classification_source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.UniqueConstraint(
            "manifest_id", "segment_id", name="uq_document_segment_segment_id"
        ),
        sa.UniqueConstraint(
            "manifest_id", "ordinal", name="uq_document_segment_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_document_segment_ordinal"),
        sa.CheckConstraint(
            "length(trim(segment_id)) > 0", name="ck_document_segment_segment_id"
        ),
        sa.CheckConstraint(
            "status IN ('classified','needs_human_review')",
            name="ck_document_segment_status",
        ),
        # 모델 분류는 없다 (명세 §6.7).
        sa.CheckConstraint(
            "classification_source = 'deterministic'",
            name="ck_document_segment_classification_source",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_document_segment_confidence_range",
        ),
        # 사람 검토가 필요한 segment는 확신도를 만들어 내지 않는다.
        sa.CheckConstraint(
            "status <> 'needs_human_review' OR confidence IS NULL",
            name="ck_document_segment_needs_review_confidence",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(taxonomy_labels) = 'array'",
            name="ck_document_segment_taxonomy_labels",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(start_locator) = 'object'",
            name="ck_document_segment_start_locator",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(end_locator) = 'object'",
            name="ck_document_segment_end_locator",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requirement_ids) = 'array'",
            name="ck_document_segment_requirement_ids",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_block_keys) = 'array'",
            name="ck_document_segment_source_block_keys",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_id"],
            [f"{SCHEMA}.document_segment_manifest.id"],
            name="fk_document_segment_manifest",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "requirement_inventory_item",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("manifest_id", UUID, nullable=False),
        sa.Column("raw_id", sa.String(length=255), nullable=False),
        sa.Column("normalized_id", sa.String(length=255), nullable=False),
        sa.Column("locator", JSONB, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # 중복 ID는 그대로 보존한다. 유일한 것은 문서 안의 순서뿐이다.
        sa.UniqueConstraint(
            "manifest_id", "ordinal", name="uq_requirement_inventory_item_ordinal"
        ),
        sa.CheckConstraint(
            "ordinal >= 1", name="ck_requirement_inventory_item_ordinal"
        ),
        sa.CheckConstraint(
            "length(trim(raw_id)) > 0 AND length(trim(normalized_id)) > 0",
            name="ck_requirement_inventory_item_ids",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locator) = 'object'",
            name="ck_requirement_inventory_item_locator",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_id"],
            [f"{SCHEMA}.document_segment_manifest.id"],
            name="fk_requirement_inventory_item_manifest",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )


def _record_migration_marker() -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.screening_audit_event
                (event_id, event_type, actor, target_type, target_id,
                 occurred_at, details_json)
            VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                    :revision, CAST(:occurred_at AS timestamptz),
                    CAST(:details AS json))
            ON CONFLICT (event_id) DO NOTHING
            """
        ),
        {
            "event_id": MIGRATION_EVENT_ID,
            "revision": revision,
            "occurred_at": "2026-01-01 00:00:18+00:00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    _replace_check(
        "attachment_fetch",
        "ck_attachment_fetch_eligibility_reason",
        _ELIGIBILITY_AFTER,
    )
    _replace_check(
        "prespec_overview_attempt",
        "ck_prespec_overview_attempt_completed_binding",
        _COMPLETED_BINDING_AFTER,
    )
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "prespec_overview_attempt",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    _create_segment_tables()
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    """되돌리기가 조용히 데이터를 잃지 않게 막는다.

    0017로 돌아가면 ``priority_grade`` 자격 행과 품질 미측정 완료 attempt는
    복원되는 CHECK를 통과할 수 없고, segment manifest 세 표는 통째로 사라진다.
    셋 중 하나라도 행이 있으면 되돌리지 않고 실패한다. 사람이 내보내거나
    정리한 뒤에 다시 시도한다.
    """

    bind = op.get_bind()
    priority_grade, unmeasured_completed, manifest, segment, inventory = bind.execute(
        sa.text(
            f"""
            SELECT
                (SELECT count(*) FROM {SCHEMA}.attachment_fetch
                  WHERE eligibility_reason = 'priority_grade'),
                (SELECT count(*) FROM {SCHEMA}.prespec_overview_attempt
                  WHERE status = 'completed' AND deployable IS FALSE),
                (SELECT count(*) FROM {SCHEMA}.document_segment_manifest),
                (SELECT count(*) FROM {SCHEMA}.document_segment),
                (SELECT count(*) FROM {SCHEMA}.requirement_inventory_item)
            """
        )
    ).one()
    blocking = {
        "attachment_fetch.eligibility_reason='priority_grade'": priority_grade,
        "prespec_overview_attempt completed with deployable=false": unmeasured_completed,
        "document_segment_manifest": manifest,
        "document_segment": segment,
        "requirement_inventory_item": inventory,
    }
    offenders = {name: count for name, count in blocking.items() if count}
    if offenders:
        detail = "; ".join(f"{name}={count}" for name, count in sorted(offenders.items()))
        raise RuntimeError(
            "0018 downgrade refuses to discard rows the restored constraints and dropped "
            "tables cannot hold; export or reconcile them before retrying: " + detail
        )


def downgrade() -> None:
    _assert_downgrade_safe()
    for table in SEGMENT_TABLES:
        op.drop_table(table, schema=SCHEMA)
    op.drop_column("prespec_overview_attempt", "lease_expires_at", schema=SCHEMA)
    op.drop_column("prespec_overview_attempt", "lease_owner", schema=SCHEMA)
    _replace_check(
        "prespec_overview_attempt",
        "ck_prespec_overview_attempt_completed_binding",
        _COMPLETED_BINDING_BEFORE,
    )
    _replace_check(
        "attachment_fetch",
        "ck_attachment_fetch_eligibility_reason",
        _ELIGIBILITY_BEFORE,
    )
    op.get_bind().execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"),
        {"event_id": MIGRATION_EVENT_ID},
    )
