"""Add append-only opportunity notes and next actions (RL-02).

The CHECK and index declarations are identical to ``app/lifecycle/models.py``
so ``alembic check`` reports no drift.  Runtime grants are not issued here:
``scripts/runtime-privileges.sql`` owns them (web: SELECT, INSERT and only
``UPDATE (done_at, done_by)``; worker and ro_backup: SELECT; no DELETE for any
role), so the note body cannot be rewritten through a runtime credential.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0039_opportunity_note"
down_revision = "0038_briefing"
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
            "occurred_at": "2026-01-01 00:00:39+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    op.create_table(
        "opportunity_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "kind IN ('note','action')", name="ck_opportunity_note_kind"
        ),
        sa.CheckConstraint(
            "(done_at IS NULL) = (done_by IS NULL)",
            name="ck_opportunity_note_done_pair",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opportunity_note_opportunity",
        "opportunity_note",
        ["opportunity_id", "created_at"],
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    has_notes = bind.scalar(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.opportunity_note)")
    )
    if has_notes:
        raise RuntimeError("0039 downgrade refuses to discard opportunity notes")

    op.drop_index(
        "ix_opportunity_note_opportunity",
        table_name="opportunity_note",
        schema=SCHEMA,
    )
    op.drop_table("opportunity_note", schema=SCHEMA)
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
