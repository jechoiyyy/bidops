"""Store immutable preliminary-assessment inputs and results on overview runs."""
import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0031_prespec_preliminary_assessment"
down_revision = "0030_prespec_review_exclusion"
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
            "occurred_at": "2026-01-01 00:00:31+00",
        },
    )


def upgrade() -> None:
    table = "prespec_overview_run"
    columns = (
        sa.Column("contract_version", sa.String(64), nullable=False, server_default="overview-v1"),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("validator_version", sa.String(128)),
        sa.Column("profile_version_id", sa.Uuid()),
        sa.Column("reused_from_run_id", sa.Uuid()),
        sa.Column("profile_digest", sa.String(64)),
        sa.Column("profile_status", sa.String(32), nullable=False, server_default="not_configured"),
        sa.Column("profile_facts_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("generation_config_json", postgresql.JSONB()),
        sa.Column("generation_config_digest", sa.String(64)),
        sa.Column("input_binding_sha256", sa.String(64)),
        sa.Column("assessment_json", postgresql.JSONB()),
        sa.Column("assessment_checks_json", postgresql.JSONB()),
        sa.Column("assessment_grade", sa.String(16)),
        sa.Column("assessment_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("semantic_status", sa.String(16), nullable=False, server_default="not_run"),
        sa.Column("semantic_scope_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table, schema=SCHEMA)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column, schema=SCHEMA)

    op.create_foreign_key(
        "fk_prespec_overview_run_profile_version",
        table,
        "profile_version",
        ["profile_version_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_prespec_overview_run_reused_from",
        table,
        table,
        ["reused_from_run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_prespec_overview_run_profile_status", table,
        "profile_status IN ('not_configured','ready','invalid')", schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_run_assessment_status", table,
        "assessment_status IN ('none','graded','held')", schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_run_semantic_status", table,
        "semantic_status IN ('not_run','passed','failed')", schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_overview_run_assessment_grade", table,
        "(assessment_status = 'graded' AND assessment_grade IS NOT NULL AND assessment_grade IN "
        "('우선 검토','검토 권장','관찰 대상','제외')) OR "
        "(assessment_status <> 'graded' AND assessment_grade IS NULL)",
        schema=SCHEMA,
    )
    # Extend the table's authoritative hash constraint instead of adding a
    # second migration-only constraint.  Keeping one named constraint makes
    # Alembic's physical-schema comparison agree with the ORM metadata.
    op.drop_constraint(
        "ck_prespec_overview_run_hashes", table, type_="check", schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_prespec_overview_run_hashes", table,
        "(input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$') AND "
        "policy_digest ~ '^[0-9a-f]{64}$' AND "
        "(profile_digest IS NULL OR profile_digest ~ '^[0-9a-f]{64}$') AND "
        "(generation_config_digest IS NULL OR generation_config_digest ~ '^[0-9a-f]{64}$') AND "
        "(input_binding_sha256 IS NULL OR input_binding_sha256 ~ '^[0-9a-f]{64}$')",
        schema=SCHEMA,
    )
    _record_migration_marker()


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; preliminary assessment history must be preserved.")
