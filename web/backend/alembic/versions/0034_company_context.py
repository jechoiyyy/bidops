"""Add company identity and company-scoped tracking lineage."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0034_company_context"
down_revision = "0033_assumption_analysis"
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
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
            "occurred_at": "2026-01-01 00:00:34+00",
        },
    )


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_fictional", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_company_slug"),
        sa.CheckConstraint(
            "slug ~ '^[a-z][a-z0-9-]{1,63}$'", name="ck_company_slug"
        ),
        sa.CheckConstraint(
            "length(slug) BETWEEN 2 AND 64", name="ck_company_slug_length"
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 128", name="ck_company_name"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_opportunity_tracking",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("tracking_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("selected_by", sa.String(128), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("company_id", "opportunity_id"),
        sa.CheckConstraint(
            "tracking_status IN ('미선택', '계속 추적', '보류', '종료')",
            name="ck_company_opportunity_tracking_status",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_company_opportunity_tracking_revision"
        ),
        sa.CheckConstraint(
            "((tracking_status = '미선택' AND reason IS NULL "
            "AND selected_by IS NULL AND selected_at IS NULL) OR "
            "(tracking_status <> '미선택' AND reason IS NOT NULL "
            "AND length(trim(reason)) BETWEEN 1 AND 2000 "
            "AND selected_by IS NOT NULL "
            "AND length(trim(selected_by)) BETWEEN 1 AND 128 "
            "AND selected_at IS NOT NULL))",
            name="ck_company_opportunity_tracking_metadata",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_tracking_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "opportunity_id",
            "revision",
            name="uq_company_tracking_event_revision",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_company_tracking_event_revision"),
        sa.CheckConstraint(
            "previous_status IN ('미선택', '계속 추적', '보류', '종료') "
            "AND new_status IN ('미선택', '계속 추적', '보류', '종료')",
            name="ck_company_tracking_event_statuses",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 2000",
            name="ck_company_tracking_event_reason",
        ),
        sa.CheckConstraint(
            "length(trim(actor)) BETWEEN 1 AND 128",
            name="ck_company_tracking_event_actor",
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_company_tracking_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'company tracking events are append-only';
        END;
        $$;
        CREATE TRIGGER immutable_company_tracking_event
        BEFORE UPDATE OR DELETE ON {SCHEMA}.company_tracking_event
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_company_tracking_event_mutation();
        """
    )

    op.add_column(
        "profile_version", sa.Column("company_id", sa.Uuid(), nullable=True), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_profile_version_company",
        "profile_version",
        "company",
        ["company_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_profile_version_company_scope",
        "profile_version",
        ["id", "company_id"],
        schema=SCHEMA,
    )

    op.add_column(
        "deep_review", sa.Column("company_id", sa.Uuid(), nullable=True), schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_deep_review_company",
        "deep_review",
        "company",
        ["company_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_deep_review_profile_company_scope",
        "deep_review",
        "profile_version",
        ["profile_version_id", "company_id"],
        ["id", "company_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_deep_review_inputs", "deep_review", schema=SCHEMA, type_="unique")
    op.create_index(
        "uq_deep_review_legacy_inputs",
        "deep_review",
        ["notice_id", "bundle_id", "profile_version_id", "policy_version_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("company_id IS NULL"),
    )
    op.create_index(
        "uq_deep_review_company_inputs",
        "deep_review",
        ["company_id", "notice_id", "bundle_id", "profile_version_id", "policy_version_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )

    op.add_column(
        "prespec_company_fit_attempt",
        sa.Column("company_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_prespec_company_fit_company",
        "prespec_company_fit_attempt",
        "company",
        ["company_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_prespec_company_fit_profile_company_scope",
        "prespec_company_fit_attempt",
        "profile_version",
        ["profile_version_id", "company_id"],
        ["id", "company_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_company_scope_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.company_id IS DISTINCT FROM OLD.company_id THEN
                RAISE EXCEPTION 'company scope is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER profile_version_company_scope_immutable
        BEFORE UPDATE OF company_id ON {SCHEMA}.profile_version
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_company_scope_change();
        CREATE TRIGGER deep_review_company_scope_immutable
        BEFORE UPDATE OF company_id ON {SCHEMA}.deep_review
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_company_scope_change();

        CREATE FUNCTION {SCHEMA}.enforce_company_profile_scope()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            profile_company_id uuid;
        BEGIN
            SELECT company_id INTO profile_company_id
            FROM {SCHEMA}.profile_version
            WHERE id = NEW.profile_version_id;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;
            IF profile_company_id IS DISTINCT FROM NEW.company_id THEN
                RAISE EXCEPTION 'profile and analysis company scopes differ'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER deep_review_company_profile_scope
        BEFORE INSERT OR UPDATE OF profile_version_id, company_id
        ON {SCHEMA}.deep_review
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.enforce_company_profile_scope();
        CREATE TRIGGER prespec_company_fit_company_profile_scope
        BEFORE INSERT OR UPDATE OF profile_version_id, company_id
        ON {SCHEMA}.prespec_company_fit_attempt
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.enforce_company_profile_scope();
        """
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            f"""
            SELECT EXISTS (SELECT 1 FROM {SCHEMA}.company)
                OR EXISTS (SELECT 1 FROM {SCHEMA}.deep_review WHERE company_id IS NOT NULL)
                OR EXISTS (
                    SELECT 1 FROM {SCHEMA}.prespec_company_fit_attempt
                    WHERE company_id IS NOT NULL
                )
            """
        )
    ):
        raise RuntimeError("company context history must be preserved")

    op.execute(
        f"""
        DROP TRIGGER prespec_company_fit_company_profile_scope
            ON {SCHEMA}.prespec_company_fit_attempt;
        DROP TRIGGER deep_review_company_profile_scope ON {SCHEMA}.deep_review;
        DROP FUNCTION {SCHEMA}.enforce_company_profile_scope();
        DROP TRIGGER deep_review_company_scope_immutable ON {SCHEMA}.deep_review;
        DROP TRIGGER profile_version_company_scope_immutable
            ON {SCHEMA}.profile_version;
        DROP FUNCTION {SCHEMA}.reject_company_scope_change();
        """
    )
    op.drop_constraint(
        "fk_prespec_company_fit_profile_company_scope",
        "prespec_company_fit_attempt",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_prespec_company_fit_company",
        "prespec_company_fit_attempt",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("prespec_company_fit_attempt", "company_id", schema=SCHEMA)

    op.drop_index("uq_deep_review_company_inputs", table_name="deep_review", schema=SCHEMA)
    op.drop_index("uq_deep_review_legacy_inputs", table_name="deep_review", schema=SCHEMA)
    op.create_unique_constraint(
        "uq_deep_review_inputs",
        "deep_review",
        ["notice_id", "bundle_id", "profile_version_id", "policy_version_id"],
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_deep_review_profile_company_scope",
        "deep_review",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_deep_review_company",
        "deep_review",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("deep_review", "company_id", schema=SCHEMA)

    op.drop_constraint(
        "uq_profile_version_company_scope",
        "profile_version",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_profile_version_company",
        "profile_version",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("profile_version", "company_id", schema=SCHEMA)

    op.execute(
        f"""
        DROP TRIGGER immutable_company_tracking_event ON {SCHEMA}.company_tracking_event;
        DROP FUNCTION {SCHEMA}.reject_company_tracking_event_mutation();
        """
    )
    op.drop_table("company_tracking_event", schema=SCHEMA)
    op.drop_table("company_opportunity_tracking", schema=SCHEMA)
    op.drop_table("company", schema=SCHEMA)
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
