"""Add the C-2 execution heartbeat used by stale recovery."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_order_plan_screening_heartbeat"
down_revision = "0016_order_plan_screening"
branch_labels = None
depends_on = None

SCHEMA = "bidops"


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


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS tr_order_plan_screening_execution_heartbeat_guard "
        f"ON {SCHEMA}.order_plan_screening_execution"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.tf_order_plan_screening_execution_heartbeat_guard()"
    )
    op.drop_column("order_plan_screening_execution", "heartbeat_at", schema=SCHEMA)
