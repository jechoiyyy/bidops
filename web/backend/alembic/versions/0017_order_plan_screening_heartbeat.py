"""Add the C-2 execution heartbeat used by stale recovery."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "0017_order_plan_screening_heartbeat"
down_revision = "0016_order_plan_screening"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
MIGRATION_EVENT_ID = "audit-1d5e9b3c7a4f2e6d8c0b1a9f5e7d3c2b"


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
            "occurred_at": "2026-01-01 00:00:17+00:00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    op.add_column(
        "order_plan_screening_execution",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.tf_order_plan_screening_execution_heartbeat_guard()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('성공','부분 성공','실패','중단됨')
               AND NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at
            THEN
                RAISE EXCEPTION 'terminal order_plan_screening_execution heartbeat is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_order_plan_screening_execution_heartbeat_guard
        BEFORE UPDATE OF heartbeat_at ON {SCHEMA}.order_plan_screening_execution
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.tf_order_plan_screening_execution_heartbeat_guard();
        """
    )
    _record_migration_marker()


def downgrade() -> None:
    # ``op.execute`` takes the statement alone; bound parameters go through the
    # connection, the same way ``_record_migration_marker`` writes the marker.
    op.get_bind().execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"),
        {"event_id": MIGRATION_EVENT_ID},
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS tr_order_plan_screening_execution_heartbeat_guard "
        f"ON {SCHEMA}.order_plan_screening_execution"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_order_plan_screening_execution_heartbeat_guard()"
    )
    op.drop_column("order_plan_screening_execution", "heartbeat_at", schema=SCHEMA)
