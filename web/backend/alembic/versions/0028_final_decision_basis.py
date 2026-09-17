"""최종 결정 근거를 비교와 분리한다 (ADR-0058, spec §9.2).

Revision ID: 0028_final_decision_basis
Revises: 0027_collection_index_and_linkage

- ``bid_final_decision``의 비교 5열(``comparison_id``, ``comparison_version``,
  ``result_sha256``, 양쪽 document version ID)을 nullable로 바꾼다.
- ``basis_kind``(``comparison`` | ``notice_conditions``), ``basis_notice_id``(FK
  ``notice``), ``basis_observation_sha256``을 더한다. 기존 행은 ``comparison``이다.
- 한 행의 근거는 한쪽뿐이다. 비교 근거면 비교 5열이 모두 있고 basis 열이 비며,
  공고 조건 근거면 그 반대다.

append-only trigger·unique·supersession FK는 그대로다. 기존 행은 UPDATE하지 않는다.
``ADD COLUMN ... DEFAULT``가 기존 행을 채우므로 append-only trigger가 발동하지 않고,
기본값은 바로 지워 새 INSERT가 근거를 명시하게 한다.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_final_decision_basis"
down_revision = "0027_collection_index_and_linkage"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
TABLE = "bid_final_decision"
_MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex

_COMPARISON_COLUMNS = (
    ("comparison_id", "uuid"),
    ("comparison_version", "integer"),
    ("result_sha256", "varchar64"),
    ("baseline_document_version_id", "uuid"),
    ("comparison_document_version_id", "uuid"),
)

_BASIS_KIND = "basis_kind IN ('comparison','notice_conditions')"
_BASIS_FIELDS = (
    "(basis_kind = 'comparison' AND comparison_id IS NOT NULL "
    "AND comparison_version IS NOT NULL AND result_sha256 IS NOT NULL "
    "AND baseline_document_version_id IS NOT NULL "
    "AND comparison_document_version_id IS NOT NULL "
    "AND basis_notice_id IS NULL AND basis_observation_sha256 IS NULL) "
    "OR (basis_kind = 'notice_conditions' AND comparison_id IS NULL "
    "AND comparison_version IS NULL AND result_sha256 IS NULL "
    "AND baseline_document_version_id IS NULL "
    "AND comparison_document_version_id IS NULL "
    "AND basis_notice_id IS NOT NULL AND basis_observation_sha256 IS NOT NULL)"
)
_BASIS_OBSERVATION_SHA256 = (
    "basis_observation_sha256 IS NULL OR basis_observation_sha256 ~ '^[0-9a-f]{64}$'"
)


def _column_type(kind: str) -> sa.types.TypeEngine:
    if kind == "uuid":
        return postgresql.UUID(as_uuid=True)
    if kind == "integer":
        return sa.Integer()
    return sa.String(length=64)


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
            "event_id": _MIGRATION_EVENT_ID,
            "revision": revision,
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
            "occurred_at": "2026-01-01 00:00:28+00",
        },
    )


def upgrade() -> None:
    for column, kind in _COMPARISON_COLUMNS:
        op.alter_column(
            TABLE, column, existing_type=_column_type(kind), nullable=True, schema=SCHEMA
        )
    op.add_column(
        TABLE,
        sa.Column(
            "basis_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'comparison'"),
        ),
        schema=SCHEMA,
    )
    op.alter_column(
        TABLE,
        "basis_kind",
        existing_type=sa.String(length=32),
        server_default=None,
        schema=SCHEMA,
    )
    op.add_column(
        TABLE, sa.Column("basis_notice_id", sa.Integer(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        TABLE,
        sa.Column("basis_observation_sha256", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_bid_final_decision_basis_notice",
        TABLE,
        "notice",
        ["basis_notice_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_bid_final_decision_basis_kind", TABLE, _BASIS_KIND, schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_bid_final_decision_basis_fields", TABLE, _BASIS_FIELDS, schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_bid_final_decision_basis_observation_sha256",
        TABLE,
        _BASIS_OBSERVATION_SHA256,
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    blocker = bind.scalar(
        sa.text(
            f"SELECT 1 FROM {SCHEMA}.{TABLE} WHERE basis_kind = 'notice_conditions' LIMIT 1"
        )
    )
    if blocker is not None:
        raise RuntimeError(
            "0028 downgrade refuses to discard notice_conditions final decisions; "
            "restore from backup instead (bid_final_decision.basis_kind)"
        )
    for name in (
        "ck_bid_final_decision_basis_observation_sha256",
        "ck_bid_final_decision_basis_fields",
        "ck_bid_final_decision_basis_kind",
    ):
        op.drop_constraint(name, table_name=TABLE, schema=SCHEMA, type_="check")
    op.drop_constraint(
        "fk_bid_final_decision_basis_notice",
        table_name=TABLE,
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column(TABLE, "basis_observation_sha256", schema=SCHEMA)
    op.drop_column(TABLE, "basis_notice_id", schema=SCHEMA)
    op.drop_column(TABLE, "basis_kind", schema=SCHEMA)
    # Every remaining row was a comparison basis, which the dropped CHECK kept
    # complete, so restoring NOT NULL cannot fail on existing data.
    for column, kind in _COMPARISON_COLUMNS:
        op.alter_column(
            TABLE, column, existing_type=_column_type(kind), nullable=False, schema=SCHEMA
        )
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
