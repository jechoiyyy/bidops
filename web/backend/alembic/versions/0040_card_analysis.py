"""Add RL-03 card analysis storage (transfer approval, stages, requests, feedback).

Tables follow RL-03 spec "저장" and the HP-03 stage definition; CHECK, index
and FK declarations are identical to ``app/deep_review/models.py`` so
``alembic check`` reports no drift.  ``briefing_item.slack_message_ts`` is an
additive nullable column (RL-01 schema, spec "연결").

Append-only triggers: ``transfer_policy_approval`` accepts only a one-time fill
of ``revoked_by``/``revoked_at``/``revoke_reason`` and no DELETE;
``card_analysis_stage`` and ``verdict_feedback`` reject every UPDATE/DELETE.
Runtime grants are not issued here: ``scripts/runtime-privileges.sql`` owns
them (worker INSERT/SELECT on stages and the five deep-review rows for the
automatic path, worker INSERT/UPDATE(status) on requests, web INSERT on
requests/feedback/approvals and only ``UPDATE (revoked_by, revoked_at,
revoke_reason)`` on approvals; no DELETE for any role).
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0040_card_analysis"
down_revision = "0039_opportunity_note"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, f"bidops:db.migration:{revision}"
).hex
_TABLES = ("verdict_feedback", "verdict_request", "card_analysis_stage", "transfer_policy_approval")


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
            "occurred_at": "2026-01-01 00:00:40+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "transfer_policy_approval",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_identity", sa.Text(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("policy_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("reasoning_effort", sa.Text(), nullable=False),
        sa.Column("cli_version", sa.Text(), nullable=False),
        sa.Column("scope", JSONB(), nullable=False),
        sa.Column("daily_cap", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("revoked_by", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            [f"{SCHEMA}.analysis_policy_version.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_id", name="uq_transfer_policy_approval_request"),
        sa.CheckConstraint(
            "policy_sha256 ~ '^[0-9a-f]{64}$'", name="ck_transfer_policy_approval_hash"
        ),
        sa.CheckConstraint(
            "daily_cap >= 1 AND daily_cap <= 50", name="ck_transfer_policy_approval_daily_cap"
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL) AND "
            "(revoked_at IS NULL) = (revoke_reason IS NULL)",
            name="ck_transfer_policy_approval_revoked",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope) = 'object'", name="ck_transfer_policy_approval_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_transfer_policy_approval_active",
        "transfer_policy_approval",
        ["policy_sha256"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "card_analysis_stage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("stage_key", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("result_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], [f"{SCHEMA}.deep_review_attempt.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "attempt_id", "stage", "stage_key", name="uq_card_analysis_stage_identity"
        ),
        sa.CheckConstraint(
            "stage IN ('extract','compare','role','synthesis')",
            name="ck_card_analysis_stage_name",
        ),
        sa.CheckConstraint(
            "((stage IN ('extract','compare') AND "
            "stage_key ~ '^(0|[1-9][0-9]*)$') "
            "OR (stage = 'role' AND stage_key IN "
            "('eligibility_economics','technical_fit','operations_risk')) "
            "OR (stage = 'synthesis' AND stage_key = 'final'))",
            name="ck_card_analysis_stage_key",
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_card_analysis_stage_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_card_analysis_stage_payload"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "verdict_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        _created_at(),
        sa.Column("started_attempt_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["notice_id"], [f"{SCHEMA}.notice.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["started_attempt_id"], [f"{SCHEMA}.deep_review_attempt.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("request_id", name="uq_verdict_request_request"),
        sa.CheckConstraint(
            "status IN ('queued','started','rejected')", name="ck_verdict_request_status"
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('daily_cap_reached','gold_holdout','manual')",
            name="ck_verdict_request_reason",
        ),
        sa.CheckConstraint(
            "started_attempt_id IS NULL OR status = 'started'",
            name="ck_verdict_request_started_attempt",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verdict_request_notice",
        "verdict_request",
        ["notice_id", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "verdict_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], [f"{SCHEMA}.deep_review_attempt.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("request_id", name="uq_verdict_feedback_request"),
        sa.CheckConstraint(
            "kind IN ('wrong_verdict','wrong_unit','not_requirement','source_mismatch')",
            name="ck_verdict_feedback_kind",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) <= 500", name="ck_verdict_feedback_note"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verdict_feedback_attempt",
        "verdict_feedback",
        ["attempt_id"],
        schema=SCHEMA,
    )

    op.add_column(
        "briefing_item",
        sa.Column("slack_message_ts", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.tf_transfer_policy_approval_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'transfer policy approvals are append-only';
            END IF;
            IF OLD.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'transfer policy approval is already revoked';
            END IF;
            IF (NEW.id, NEW.policy_identity, NEW.policy_version_id, NEW.policy_sha256,
                NEW.model_name, NEW.reasoning_effort, NEW.cli_version, NEW.scope,
                NEW.daily_cap, NEW.approved_by, NEW.approved_at, NEW.request_id)
               IS DISTINCT FROM
               (OLD.id, OLD.policy_identity, OLD.policy_version_id, OLD.policy_sha256,
                OLD.model_name, OLD.reasoning_effort, OLD.cli_version, OLD.scope,
                OLD.daily_cap, OLD.approved_by, OLD.approved_at, OLD.request_id) THEN
                RAISE EXCEPTION 'transfer policy approvals are append-only';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_transfer_policy_approval_guard
        BEFORE UPDATE OR DELETE ON {SCHEMA}.transfer_policy_approval
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_transfer_policy_approval_guard();

        CREATE FUNCTION {SCHEMA}.tf_card_analysis_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME;
        END;
        $$;
        CREATE TRIGGER tr_card_analysis_stage_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.card_analysis_stage
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_card_analysis_append_only();
        CREATE TRIGGER tr_verdict_feedback_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.verdict_feedback
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_card_analysis_append_only();
        """
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{table})")):
            raise RuntimeError(f"0040 downgrade refuses to discard {table} rows")
    if bind.scalar(
        sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.briefing_item "
            "WHERE slack_message_ts IS NOT NULL)"
        )
    ):
        raise RuntimeError("0040 downgrade refuses to discard briefing Slack message ids")

    op.drop_column("briefing_item", "slack_message_ts", schema=SCHEMA)
    op.drop_index("ix_verdict_feedback_attempt", table_name="verdict_feedback", schema=SCHEMA)
    op.drop_table("verdict_feedback", schema=SCHEMA)
    op.drop_index("ix_verdict_request_notice", table_name="verdict_request", schema=SCHEMA)
    op.drop_table("verdict_request", schema=SCHEMA)
    op.drop_table("card_analysis_stage", schema=SCHEMA)
    op.drop_index(
        "uq_transfer_policy_approval_active",
        table_name="transfer_policy_approval",
        schema=SCHEMA,
    )
    op.drop_table("transfer_policy_approval", schema=SCHEMA)
    op.execute(f"DROP FUNCTION {SCHEMA}.tf_card_analysis_append_only()")
    op.execute(f"DROP FUNCTION {SCHEMA}.tf_transfer_policy_approval_guard()")
    bind.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
