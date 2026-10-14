"""Persist requirement-card provenance and page inheritance anchors.

Existing inventory rows retain the column-header source through a server
default.  The nullable JSONB columns preserve absence as SQL NULL.  Runtime
grants are unchanged because this revision adds columns to existing tables.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0037_requirement_card_columns"
down_revision = "0036_company_analysis"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, f"bidops:db.migration:{revision}"
).hex


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
            "occurred_at": "2026-01-01 00:00:37+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    op.add_column(
        "requirement_inventory_item",
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'column_header_table'"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "requirement_inventory_item",
        sa.Column("card", JSONB(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "document_segment",
        sa.Column("page_anchor_block_keys", JSONB(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_requirement_inventory_item_source",
        "requirement_inventory_item",
        "source IN ('column_header_table','label_value_table')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_requirement_inventory_item_card_source",
        "requirement_inventory_item",
        "(source = 'column_header_table' AND card IS NULL) OR "
        "(source = 'label_value_table' AND card IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_requirement_inventory_item_card",
        "requirement_inventory_item",
        "card IS NULL OR jsonb_typeof(card) = 'object'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_document_segment_page_anchor_block_keys",
        "document_segment",
        "page_anchor_block_keys IS NULL OR "
        "jsonb_typeof(page_anchor_block_keys) = 'array'",
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    has_card_data = bind.scalar(
        sa.text(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {SCHEMA}.requirement_inventory_item
                WHERE source <> 'column_header_table' OR card IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM {SCHEMA}.document_segment
                WHERE page_anchor_block_keys IS NOT NULL
            )
            """
        )
    )
    if has_card_data:
        raise RuntimeError(
            "0037 downgrade refuses to discard requirement card or page anchor data"
        )

    op.drop_constraint(
        "ck_document_segment_page_anchor_block_keys",
        "document_segment",
        schema=SCHEMA,
        type_="check",
    )
    for name in (
        "ck_requirement_inventory_item_card",
        "ck_requirement_inventory_item_card_source",
        "ck_requirement_inventory_item_source",
    ):
        op.drop_constraint(
            name,
            "requirement_inventory_item",
            schema=SCHEMA,
            type_="check",
        )
    op.drop_column("document_segment", "page_anchor_block_keys", schema=SCHEMA)
    op.drop_column("requirement_inventory_item", "card", schema=SCHEMA)
    op.drop_column("requirement_inventory_item", "source", schema=SCHEMA)
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
