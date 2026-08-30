"""Create the internal opportunity and lifecycle-link tables.

Revision ID: 0005_opportunity_links
Revises: 0004_cumulative_external_identity

The preceding revision made ``notice`` and ``order_plan`` cumulative.  This
revision only adds the internal grouping and relation state; it does not
invent links for existing rows because name-search candidates require a
separate, human-reviewed producer.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_opportunity_links"
down_revision = "0004_cumulative_external_identity"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-85c4a7e1d2f649b0a3c8e7d6f5b41290"


def upgrade() -> None:
    jsonb = postgresql.JSONB()

    # There is intentionally no data migration here.  Existing notices and
    # plans are valid cumulative identities, but no safe opportunity grouping
    # can be inferred without an official key or a person-reviewed candidate.
    op.create_table(
        "opportunity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_registered_stage", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "first_registered_stage IN ('order_plan', 'pre_spec')",
            name="ck_opportunity_first_registered_stage",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "opportunity_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.opportunity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_plan_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.order_plan.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "notice_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.notice.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("link_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_external_no", sa.String(length=255), nullable=True),
        sa.Column("evidence_bid_no", sa.String(length=64), nullable=True),
        sa.Column("search_strategy", sa.String(length=64), nullable=True),
        sa.Column("agency_match", sa.Boolean(), nullable=True),
        sa.Column("last_searched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempted_strategies_json", jsonb, nullable=True),
        sa.Column("human_decision", sa.String(length=16), nullable=True),
        sa.Column("reviewer_name", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('order_plan', 'notice')",
            name="ck_opportunity_link_stage",
        ),
        sa.CheckConstraint(
            "link_type IN ('official', 'candidate')",
            name="ck_opportunity_link_type",
        ),
        sa.CheckConstraint(
            "status IN ('확정', '후보 확인 대기', '사람 확인 완료', '검색 미확인')",
            name="ck_opportunity_link_status",
        ),
        sa.CheckConstraint(
            "search_strategy IS NULL OR search_strategy IN "
            "('full', 'breaking_split', 'normalized', 'longest_fragment', 'prefix12')",
            name="ck_opportunity_link_search_strategy",
        ),
        sa.CheckConstraint(
            "link_type <> 'official' OR status = '확정'",
            name="ck_opportunity_link_official_status",
        ),
        sa.CheckConstraint(
            "link_type <> 'official' OR "
            "(evidence_external_no IS NOT NULL AND length(trim(evidence_external_no)) > 0)",
            name="ck_opportunity_link_official_evidence",
        ),
        sa.CheckConstraint(
            "link_type <> 'candidate' OR status <> '확정'",
            name="ck_opportunity_link_candidate_not_confirmed",
        ),
        sa.CheckConstraint(
            "status = '검색 미확인' OR "
            "((order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
            "(order_plan_id IS NULL AND notice_id IS NOT NULL))",
            name="ck_opportunity_link_one_target",
        ),
        sa.CheckConstraint(
            "status = '검색 미확인' OR "
            "(stage = 'order_plan' AND order_plan_id IS NOT NULL AND notice_id IS NULL) OR "
            "(stage = 'notice' AND order_plan_id IS NULL AND notice_id IS NOT NULL)",
            name="ck_opportunity_link_stage_target",
        ),
        sa.CheckConstraint(
            "status <> '검색 미확인' OR (order_plan_id IS NULL AND notice_id IS NULL)",
            name="ck_opportunity_link_unconfirmed_without_target",
        ),
        sa.CheckConstraint(
            "status <> '검색 미확인' OR (stage = 'notice' AND link_type = 'candidate')",
            name="ck_opportunity_link_search_unconfirmed_kind",
        ),
        sa.CheckConstraint(
            "human_decision IS NULL OR human_decision IN ('accepted', 'rejected')",
            name="ck_opportunity_link_human_decision",
        ),
        sa.CheckConstraint(
            "status <> '사람 확인 완료' OR "
            "(human_decision IS NOT NULL AND reviewer_name IS NOT NULL "
            "AND length(trim(reviewer_name)) > 0 AND reviewed_at IS NOT NULL "
            "AND review_reason IS NOT NULL AND length(trim(review_reason)) > 0)",
            name="ck_opportunity_link_human_review_metadata",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opportunity_link_opportunity",
        "opportunity_link",
        ["opportunity_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opportunity_link_order_plan",
        "opportunity_link",
        ["order_plan_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opportunity_link_notice",
        "opportunity_link",
        ["notice_id"],
        schema=SCHEMA,
    )

    # Migration audit events are append-only.  This marker is distinct from
    # the 0003 and 0004 markers and contains no connection or secret data.
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO bidops.screening_audit_event
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
            "details": '{"migration_revision":"0005_opportunity_links","action":"upgrade"}',
            "occurred_at": "2026-01-01 00:00:02+00",
        },
    )


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM bidops.opportunity_link")):
        raise RuntimeError(
            "0005 downgrade refuses to discard opportunity_link rows; "
            "export or reconcile lifecycle links before retrying"
        )
    if bind.scalar(sa.text("SELECT count(*) FROM bidops.opportunity")):
        raise RuntimeError(
            "0005 downgrade refuses to discard opportunity rows; "
            "export or reconcile opportunities before retrying"
        )


def downgrade() -> None:
    # No row is silently discarded on rollback.  Empty tables are the only
    # safe state in which this additive revision can be removed.
    _assert_downgrade_safe()
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM bidops.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
    op.drop_index(
        "ix_opportunity_link_notice", table_name="opportunity_link", schema=SCHEMA
    )
    op.drop_index(
        "ix_opportunity_link_order_plan", table_name="opportunity_link", schema=SCHEMA
    )
    op.drop_index(
        "ix_opportunity_link_opportunity", table_name="opportunity_link", schema=SCHEMA
    )
    op.drop_table("opportunity_link", schema=SCHEMA)
    op.drop_table("opportunity", schema=SCHEMA)
