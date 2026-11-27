"""Audited company-fit card mode switch (PS-01 C4·C8, ADR-0080).

Append-only rows; the latest row is the requested mode. The env value
`BIDOPS_PRESPEC_COMPANY_FIT_CARD_MODE` stays a deployment cap: the mode is effective only when the
cap allows `suggest` and the latest row is `suggest` bound to the current card and prompt.
"""

from alembic import op
import sqlalchemy as sa

revision = "0047_company_fit_mode"
down_revision = "0046_engine_live"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
TABLE = "prespec_company_fit_mode"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("card_version", sa.String(64)),
        sa.Column("card_sha256", sa.String(64)),
        sa.Column("reason", sa.String(200)),
        sa.Column("set_by", sa.String(128), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_prespec_company_fit_mode_request"),
        sa.CheckConstraint("mode IN ('off','suggest')", name="ck_prespec_company_fit_mode_value"),
        sa.CheckConstraint("mode <> 'suggest' OR (card_version IS NOT NULL AND card_sha256 IS NOT NULL)",
                           name="ck_prespec_company_fit_mode_card"),
        sa.CheckConstraint("card_sha256 IS NULL OR card_sha256 ~ '^[0-9a-f]{64}$'",
                           name="ck_prespec_company_fit_mode_sha"),
        sa.CheckConstraint("length(trim(set_by)) > 0 AND length(trim(prompt_version)) > 0 AND "
                           "(reason IS NULL OR length(trim(reason)) > 0)",
                           name="ck_prespec_company_fit_mode_text"),
        schema=SCHEMA,
    )
    op.create_index("ix_bidops_prespec_company_fit_mode_set_at", TABLE, ["set_at", "id"], schema=SCHEMA)
    op.execute("""
        CREATE FUNCTION bidops.guard_prespec_company_fit_mode() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'company fit mode rows are append-only'; END; $$;
    """)
    op.execute(f"""
        CREATE TRIGGER prespec_company_fit_mode_guard BEFORE UPDATE OR DELETE ON bidops.{TABLE}
        FOR EACH ROW EXECUTE FUNCTION bidops.guard_prespec_company_fit_mode()
    """)
    op.execute("""INSERT INTO bidops.screening_audit_event
        (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
        VALUES ('audit-' || replace(gen_random_uuid()::text, '-', ''), 'db.migration', 'system:migration','database',
        '0047_company_fit_mode',CURRENT_TIMESTAMP,'{"migration_revision":"0047_company_fit_mode","action":"upgrade"}')""")


def downgrade():
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bidops.prespec_company_fit_attempt WHERE card_sha256 IS NOT NULL AND input_jsonb->>'judged_by' = 'model')
          THEN RAISE EXCEPTION '0047 downgrade refuses while model card judgments exist'; END IF;
        END $$;
    """)
    op.execute(f"DROP TRIGGER prespec_company_fit_mode_guard ON bidops.{TABLE}")
    op.drop_table(TABLE, schema=SCHEMA)
    op.execute("DROP FUNCTION bidops.guard_prespec_company_fit_mode()")
