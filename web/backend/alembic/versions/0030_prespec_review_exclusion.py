"""Persist human pre-spec review exclusions independently of source observations."""
import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "0030_prespec_review_exclusion"
down_revision = "0029_c2_quality_gate"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex


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
            "occurred_at": "2026-01-01 00:00:30+00",
        },
    )


def upgrade() -> None:
    # Legacy bootstrap migrations create Notice from current metadata. A fresh
    # DB can already have these columns; an existing 0029 DB does not.
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("notice", schema="bidops")}
    for column in (
        sa.Column("review_exclusion_status", sa.String(16), nullable=False, server_default="included"),
        sa.Column("review_exclusion_actor_name", sa.String(128)),
        sa.Column("review_exclusion_reason", sa.Text()),
        sa.Column("review_exclusion_changed_at", sa.DateTime(timezone=True)),
    ):
        if column.name not in existing:
            op.add_column("notice", column, schema="bidops")
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("notice", schema="bidops")}
    for name in ("ck_notice_review_exclusion_status", "ck_notice_review_exclusion_metadata"):
        if name in checks:
            op.drop_constraint(name, "notice", type_="check", schema="bidops")
    op.create_check_constraint("ck_notice_review_exclusion_status", "notice", "review_exclusion_status IN ('included','excluded')", schema="bidops")
    op.create_check_constraint(
        "ck_notice_review_exclusion_metadata", "notice",
        "(review_exclusion_status = 'included' AND review_exclusion_actor_name IS NULL "
        "AND review_exclusion_reason IS NULL AND review_exclusion_changed_at IS NULL) OR "
        "(review_exclusion_actor_name IS NOT NULL AND length(trim(review_exclusion_actor_name)) BETWEEN 1 AND 128 "
        "AND review_exclusion_reason IS NOT NULL AND length(trim(review_exclusion_reason)) BETWEEN 1 AND 2000 "
        "AND review_exclusion_changed_at IS NOT NULL AND source_type = 'pre_spec')",
        schema="bidops",
    )

    _record_migration_marker()


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; human review exclusion history must be preserved.")
