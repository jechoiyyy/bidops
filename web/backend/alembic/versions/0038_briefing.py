"""Add the weekday briefing, its items, and append-only reaction events (RL-01).

The CHECK and partial UNIQUE declarations are identical to
``app/lifecycle/models.py`` so ``alembic check`` reports no drift.  Runtime
grants are not issued here: ``scripts/runtime-privileges.sql`` owns them
(web: SELECT/INSERT/UPDATE briefing and briefing_item, SELECT/INSERT reaction
events; worker: column-scoped reaction UPDATE; no DELETE for any role).
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0038_briefing"
down_revision = "0037_requirement_card_columns"
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
            "occurred_at": "2026-01-01 00:00:38+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    op.create_table(
        "briefing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_sha256", sa.CHAR(64), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("excluded_counts", JSONB(), nullable=False),
        sa.Column("warnings", JSONB(), nullable=False),
        sa.Column("slack_message_ts", JSONB(), nullable=True),
        sa.Column("slack_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracked_change_message_ts", JSONB(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_date", name="uq_briefing_date"),
        sa.CheckConstraint(
            "status IN ('generated','empty','collection_incomplete')",
            name="ck_briefing_status",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "briefing_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("briefing_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=True),
        sa.Column("order_plan_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(6, 2), nullable=True),
        sa.Column("reasons", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("blocking", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("change_fields", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_kind", sa.String(32), nullable=True),
        sa.Column("planned_month", sa.Text(), nullable=True),
        sa.Column("amount_krw", sa.BigInteger(), nullable=True),
        sa.Column("reaction", sa.Text(), nullable=True),
        sa.Column("reacted_by", sa.Text(), nullable=True),
        sa.Column("reacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reacted_via", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["briefing_id"], [f"{SCHEMA}.briefing.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"], [f"{SCHEMA}.notice.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["order_plan_id"], [f"{SCHEMA}.order_plan.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "(notice_id IS NULL) <> (order_plan_id IS NULL)",
            name="ck_briefing_item_one_target",
        ),
        sa.CheckConstraint(
            "kind IN ('recommendation','tracked_change')",
            name="ck_briefing_item_kind",
        ),
        sa.CheckConstraint(
            "stage IN ('pre_spec','bid_notice','order_plan')",
            name="ck_briefing_item_stage",
        ),
        sa.CheckConstraint(
            "deadline_kind IS NULL OR deadline_kind IN ('bid_close','opinion_close','planned_month')",
            name="ck_briefing_item_deadline_kind",
        ),
        sa.CheckConstraint(
            "reaction IS NULL OR reaction IN ('대기','채택','무시','나중에')",
            name="ck_briefing_item_reaction",
        ),
        sa.CheckConstraint(
            "reacted_via IS NULL OR reacted_via IN ('screen','slack')",
            name="ck_briefing_item_reacted_via",
        ),
        sa.CheckConstraint(
            "(kind = 'recommendation' AND rank IS NOT NULL AND reaction IS NOT NULL) OR "
            "(kind = 'tracked_change' AND rank IS NULL AND reaction IS NULL)",
            name="ck_briefing_item_kind_shape",
        ),
        sa.CheckConstraint(
            "(reacted_by IS NULL) = (reacted_at IS NULL) AND "
            "(reacted_by IS NULL) = (reacted_via IS NULL)",
            name="ck_briefing_item_reacted_triple",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_briefing_item_notice",
        "briefing_item",
        ["briefing_id", "notice_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("notice_id IS NOT NULL"),
    )
    op.create_index(
        "uq_briefing_item_order_plan",
        "briefing_item",
        ["briefing_id", "order_plan_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("order_plan_id IS NOT NULL"),
    )
    op.create_index(
        "uq_briefing_item_rank",
        "briefing_item",
        ["briefing_id", "rank"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("rank IS NOT NULL"),
    )
    op.create_table(
        "briefing_reaction_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous", sa.Text(), nullable=False),
        sa.Column("new", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("via", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["item_id"], [f"{SCHEMA}.briefing_item.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "item_id", "revision", name="uq_briefing_reaction_event_revision"
        ),
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    has_briefing_data = bind.scalar(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.briefing)")
    )
    if has_briefing_data:
        raise RuntimeError("0038 downgrade refuses to discard briefing history")

    op.drop_table("briefing_reaction_event", schema=SCHEMA)
    for name in (
        "uq_briefing_item_rank",
        "uq_briefing_item_order_plan",
        "uq_briefing_item_notice",
    ):
        op.drop_index(name, table_name="briefing_item", schema=SCHEMA)
    op.drop_table("briefing_item", schema=SCHEMA)
    op.drop_table("briefing", schema=SCHEMA)
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
