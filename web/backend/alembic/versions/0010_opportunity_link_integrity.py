"""Enforce authoritative opportunity ownership and retain merge history.

Revision ID: 0010_opportunity_link_integrity
Revises: 0009_observation_snapshot_retention

The migration never guesses which duplicate ownership row is correct.  It
preflights both external target types and stops with the conflicting target
and link IDs before adding the partial unique indexes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_opportunity_link_integrity"
down_revision = "0009_observation_snapshot_retention"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-31a6e4f8c2d94750b1a3e7d9f40628bc"
_AUTHORITATIVE = (
    "((link_type = 'official' AND status = '확정') OR "
    "(link_type = 'candidate' AND status = '사람 확인 완료' "
    "AND human_decision = 'accepted'))"
)
_MERGE_METADATA = (
    "((merged_into_opportunity_id IS NULL AND merged_at IS NULL "
    "AND merge_reason IS NULL) OR "
    "(merged_into_opportunity_id IS NOT NULL AND merged_at IS NOT NULL "
    "AND merge_reason IS NOT NULL AND length(trim(merge_reason)) > 0))"
)


def _preflight_authoritative_duplicates() -> None:
    bind = op.get_bind()
    conflicts: list[str] = []
    for target_column in ("order_plan_id", "notice_id"):
        rows = bind.execute(
            sa.text(
                f"SELECT {target_column}, array_agg(id ORDER BY id) AS link_ids "
                f"FROM {SCHEMA}.opportunity_link "
                f"WHERE {target_column} IS NOT NULL AND {_AUTHORITATIVE} "
                f"GROUP BY {target_column} HAVING count(*) > 1 "
                f"ORDER BY {target_column} LIMIT 20"
            )
        ).all()
        conflicts.extend(
            f"{target_column}={row[0]} link_ids={list(row[1])}" for row in rows
        )
    if conflicts:
        detail = "; ".join(conflicts)
        raise RuntimeError(
            "0010 upgrade found duplicate authoritative opportunity links; "
            "review and reconcile these rows without guessing, then retry: "
            f"{detail}"
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
            "event_id": _MIGRATION_EVENT_ID,
            "revision": revision,
            "details": (
                '{"migration_revision":"0010_opportunity_link_integrity",'
                '"action":"upgrade"}'
            ),
            "occurred_at": "2026-01-01 00:00:07+00",
        },
    )


def upgrade() -> None:
    _preflight_authoritative_duplicates()
    op.add_column(
        "opportunity",
        sa.Column("merged_into_opportunity_id", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "opportunity",
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "opportunity",
        sa.Column("merge_reason", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_opportunity_merged_into",
        "opportunity",
        "opportunity",
        ["merged_into_opportunity_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_opportunity_merge_metadata",
        "opportunity",
        _MERGE_METADATA,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_opportunity_not_merged_into_self",
        "opportunity",
        "merged_into_opportunity_id IS NULL OR merged_into_opportunity_id <> id",
        schema=SCHEMA,
    )
    op.create_index(
        "uq_opportunity_link_authoritative_order_plan",
        "opportunity_link",
        ["order_plan_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(
            f"order_plan_id IS NOT NULL AND {_AUTHORITATIVE}"
        ),
    )
    op.create_index(
        "uq_opportunity_link_authoritative_notice",
        "opportunity_link",
        ["notice_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(f"notice_id IS NOT NULL AND {_AUTHORITATIVE}"),
    )
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    if op.get_bind().scalar(
        sa.text(
            f"SELECT 1 FROM {SCHEMA}.opportunity "
            "WHERE merged_into_opportunity_id IS NOT NULL OR merged_at IS NOT NULL "
            "OR merge_reason IS NOT NULL LIMIT 1"
        )
    ) is not None:
        raise RuntimeError(
            "0010 downgrade refuses to discard opportunity merge history; "
            "export or reconcile merged rows before retrying"
        )


def downgrade() -> None:
    _assert_downgrade_safe()
    op.drop_index(
        "uq_opportunity_link_authoritative_notice",
        table_name="opportunity_link",
        schema=SCHEMA,
    )
    op.drop_index(
        "uq_opportunity_link_authoritative_order_plan",
        table_name="opportunity_link",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_opportunity_not_merged_into_self",
        table_name="opportunity",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_opportunity_merge_metadata",
        table_name="opportunity",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_opportunity_merged_into",
        table_name="opportunity",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_column("opportunity", "merge_reason", schema=SCHEMA)
    op.drop_column("opportunity", "merged_at", schema=SCHEMA)
    op.drop_column("opportunity", "merged_into_opportunity_id", schema=SCHEMA)
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event "
            "WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
