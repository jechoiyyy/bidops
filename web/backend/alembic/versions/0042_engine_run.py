"""Add extracted-engine immutable reference run envelope; reuse WorkJob."""

from uuid import uuid4
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0042_engine_run"
down_revision = "0041_proposal_draft"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "engine_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("bidops.company.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "notice_id",
            sa.Integer(),
            sa.ForeignKey("bidops.notice.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "bundle_id",
            sa.Uuid(),
            sa.ForeignKey("bidops.document_bundle.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "profile_version_id",
            sa.Uuid(),
            sa.ForeignKey("bidops.profile_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", JSONB(), nullable=False),
        sa.Column("result_payload", JSONB(), nullable=True),
        sa.Column("result_sha256", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("request_id", name="uq_engine_run_request"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','partial','failed')",
            name="ck_engine_run_status",
        ),
        sa.CheckConstraint(
            "quality_status = 'mock_reference'", name="ck_engine_run_quality"
        ),
        schema="bidops",
    )
    op.execute("""CREATE FUNCTION bidops.guard_engine_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine run immutable'; END IF;
      IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.result_payload IS NOT NULL OR NEW.result_sha256 IS NOT NULL OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'invalid engine creation'; END IF;
        IF NOT EXISTS (SELECT 1 FROM bidops.profile_version p WHERE p.id=NEW.profile_version_id AND p.company_id=NEW.company_id) OR NOT EXISTS (SELECT 1 FROM bidops.document_bundle b WHERE b.id=NEW.bundle_id AND b.notice_id=NEW.notice_id) THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NEW.input_payload->>'company_id' IS DISTINCT FROM NEW.company_id::text OR NEW.input_payload->>'bundle_id' IS DISTINCT FROM NEW.bundle_id::text OR NEW.input_payload->>'notice_id' IS DISTINCT FROM NEW.notice_id::text OR NEW.input_payload->>'profile_version_id' IS DISTINCT FROM NEW.profile_version_id::text OR NEW.input_payload->>'mode' IS DISTINCT FROM 'mock_reference' THEN RAISE EXCEPTION 'engine input scope mismatch'; END IF;
        RETURN NEW;
      END IF;
      IF (to_jsonb(NEW) - ARRAY['status','result_payload','result_sha256','error_code','started_at','completed_at']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','result_payload','result_sha256','error_code','started_at','completed_at']) THEN RAISE EXCEPTION 'engine input immutable'; END IF;
      IF OLD.status IN ('completed','partial','failed') THEN RAISE EXCEPTION 'engine result immutable'; END IF;
      IF NOT ((OLD.status='queued' AND NEW.status IN ('running','failed')) OR (OLD.status='running' AND NEW.status IN ('completed','partial','failed'))) THEN RAISE EXCEPTION 'invalid engine transition'; END IF;
      IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN RAISE EXCEPTION 'engine start immutable'; END IF;
      IF NEW.status IN ('completed','partial') AND (NEW.result_payload IS NULL OR NEW.result_sha256 IS NULL OR NEW.completed_at IS NULL) THEN RAISE EXCEPTION 'engine result missing'; END IF;
      IF NEW.status='running' AND NEW.started_at IS NULL THEN RAISE EXCEPTION 'engine start missing'; END IF;
      IF NEW.status='failed' AND (NEW.error_code IS NULL OR NEW.completed_at IS NULL) THEN RAISE EXCEPTION 'engine failure missing'; END IF;
      RETURN NEW;
    END; $$""")
    op.execute(
        "CREATE TRIGGER engine_run_guard BEFORE INSERT OR UPDATE OR DELETE ON bidops.engine_run FOR EACH ROW EXECUTE FUNCTION bidops.guard_engine_run()"
    )
    op.execute(
        f"INSERT INTO bidops.screening_audit_event (event_id,event_type,actor,target_type,target_id,occurred_at,details_json) VALUES ('audit-{uuid4().hex}','db.migration','system:migration','database','0042_engine_run',CURRENT_TIMESTAMP,'{{\"migration_revision\":\"0042_engine_run\",\"action\":\"upgrade\"}}'::json)"
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM bidops.engine_run) THEN RAISE EXCEPTION '0042 downgrade refuses to discard engine runs'; END IF; END $$"
    )
    op.drop_table("engine_run", schema="bidops")
    op.execute("DROP FUNCTION bidops.guard_engine_run()")
