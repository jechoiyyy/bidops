"""Preserve normalized collection snapshots on run observations.

Revision ID: 0009_observation_snapshot_retention
Revises: 0008_prespec_attachment_fetch

Existing observations deliberately remain legacy rows with all three snapshot
columns null.  Current producers create the three values together and the
database checks both that pairing and the lowercase SHA-256 shape.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_observation_snapshot_retention"
down_revision = "0008_prespec_attachment_fetch"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-8c19ef4a7b2d4650a13f9e6c4d0872ab"
_OBSERVATION_TABLES = ("notice_observation", "order_plan_observation")


def _qualified(table_name: str) -> str:
    return f"{SCHEMA}.{table_name}"


def _snapshot_pair_check() -> str:
    return (
        "((snapshot_schema_version IS NULL AND snapshot_jsonb IS NULL "
        "AND source_sha256 IS NULL) OR "
        "(snapshot_schema_version IS NOT NULL "
        "AND length(trim(snapshot_schema_version)) > 0 "
        "AND snapshot_jsonb IS NOT NULL AND source_sha256 IS NOT NULL))"
    )


def _source_sha256_check() -> str:
    return (
        "source_sha256 IS NULL OR "
        "(length(source_sha256) = 64 AND source_sha256 ~ '^[0-9a-f]{64}$')"
    )


def _snapshot_object_check() -> str:
    return "snapshot_jsonb IS NULL OR jsonb_typeof(snapshot_jsonb) = 'object'"


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
                '{"migration_revision":"0009_observation_snapshot_retention",'
                '"action":"upgrade"}'
            ),
            "occurred_at": "2026-01-01 00:00:06+00",
        },
    )


def upgrade() -> None:
    for table_name in _OBSERVATION_TABLES:
        op.add_column(
            table_name,
            sa.Column("snapshot_schema_version", sa.String(length=64), nullable=True),
            schema=SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column(
                "snapshot_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            schema=SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("source_sha256", sa.String(length=64), nullable=True),
            schema=SCHEMA,
        )
        op.create_check_constraint(
            f"ck_{table_name}_snapshot_pair",
            table_name,
            _snapshot_pair_check(),
            schema=SCHEMA,
        )
        op.create_check_constraint(
            f"ck_{table_name}_source_sha256",
            table_name,
            _source_sha256_check(),
            schema=SCHEMA,
        )
        op.create_check_constraint(
            f"ck_{table_name}_snapshot_object",
            table_name,
            _snapshot_object_check(),
            schema=SCHEMA,
        )
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    for table_name in _OBSERVATION_TABLES:
        populated = op.get_bind().scalar(
            sa.text(
                f"SELECT 1 FROM {_qualified(table_name)} "
                "WHERE snapshot_jsonb IS NOT NULL OR source_sha256 IS NOT NULL "
                "OR snapshot_schema_version IS NOT NULL LIMIT 1"
            )
        )
        if populated is not None:
            raise RuntimeError(
                "0009 downgrade refuses to discard immutable observation snapshots; "
                "export or reconcile them before retrying"
            )


def downgrade() -> None:
    _assert_downgrade_safe()
    for table_name in reversed(_OBSERVATION_TABLES):
        op.drop_constraint(
            f"ck_{table_name}_snapshot_object",
            table_name,
            type_="check",
            schema=SCHEMA,
        )
        op.drop_constraint(
            f"ck_{table_name}_source_sha256",
            table_name,
            type_="check",
            schema=SCHEMA,
        )
        op.drop_constraint(
            f"ck_{table_name}_snapshot_pair",
            table_name,
            type_="check",
            schema=SCHEMA,
        )
        op.drop_column(table_name, "source_sha256", schema=SCHEMA)
        op.drop_column(table_name, "snapshot_jsonb", schema=SCHEMA)
        op.drop_column(table_name, "snapshot_schema_version", schema=SCHEMA)
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
