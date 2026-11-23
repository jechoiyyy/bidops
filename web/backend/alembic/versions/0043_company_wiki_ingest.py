"""Company wiki ingest envelope and transition fence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0043_company_wiki_ingest"
down_revision = "0042_engine_run"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_wiki_ingest_run",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("project_title", sa.Text(), nullable=False),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("source_object_version", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source_media_type", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("created_by_name", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("wiki_sha256_before", sa.Text(), nullable=True),
        sa.Column("wiki_sha256_after", sa.Text(), nullable=True),
        sa.Column("backup_name", sa.Text(), nullable=True),
        sa.Column("decided_by_name", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("classification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requirement_count", sa.Integer(), nullable=True),
        sa.Column("document_requirement_ids_unlisted", sa.Integer(), nullable=True),
        sa.Column("mapping", JSONB(), nullable=True),
        sa.Column("review_input", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','extracting','classifying','awaiting_review','approved','applying','applied','failed','rejected','aborted')", name="ck_wiki_ingest_status"),
        sa.CheckConstraint("quality_status = 'mock_reference'", name="ck_wiki_ingest_quality"),
        sa.CheckConstraint("project_id ~ '^P[0-9]{4}-[0-9]{2}$'", name="ck_wiki_ingest_project"),
        sa.UniqueConstraint("request_id", name="uq_wiki_ingest_request"),
        schema="bidops",
    )
    op.create_index("uq_wiki_ingest_project", "company_wiki_ingest_run", ["project_id"], schema="bidops",
                    unique=True, postgresql_where=sa.text("status NOT IN ('applied','failed','rejected','aborted')"))
    op.create_index("uq_wiki_ingest_applying", "company_wiki_ingest_run", ["status"], schema="bidops",
                    unique=True, postgresql_where=sa.text("status = 'applying'"))
    op.execute("""CREATE FUNCTION bidops.guard_wiki_ingest() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable ingest'; END IF;
      IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' THEN RAISE EXCEPTION 'invalid initial status'; END IF;
        RETURN NEW;
      END IF;
      IF OLD.status IN ('applied','failed','rejected','aborted') OR
         (to_jsonb(NEW) - ARRAY['status','updated_at','error_code','requirement_count',
         'document_requirement_ids_unlisted','classification_attempts','mapping','review_input',
         'wiki_sha256_before','wiki_sha256_after','backup_name','decided_by_name','decided_at',
         'decision_reason','applied_at','heartbeat_at','worker_id']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','updated_at','error_code','requirement_count',
         'document_requirement_ids_unlisted','classification_attempts','mapping','review_input',
         'wiki_sha256_before','wiki_sha256_after','backup_name','decided_by_name','decided_at',
         'decision_reason','applied_at','heartbeat_at','worker_id'])
      THEN RAISE EXCEPTION 'immutable ingest'; END IF;
      IF NOT ((OLD.status='queued' AND NEW.status='extracting')
        OR (OLD.status='extracting' AND NEW.status='classifying')
        OR (OLD.status='classifying' AND NEW.status='awaiting_review')
        OR (OLD.status='awaiting_review' AND NEW.status IN ('approved','rejected'))
        OR (OLD.status='approved' AND NEW.status='applying')
        OR (OLD.status='applying' AND NEW.status IN ('applying','applied'))
        OR (OLD.status IN ('extracting','classifying','applying') AND NEW.status IN ('failed','aborted')))
      THEN RAISE EXCEPTION 'invalid ingest transition'; END IF;
      RETURN NEW;
    END; $$""")
    op.execute("""CREATE TRIGGER wiki_ingest_guard BEFORE INSERT OR UPDATE OR DELETE ON
        bidops.company_wiki_ingest_run FOR EACH ROW EXECUTE FUNCTION bidops.guard_wiki_ingest()""")
    op.execute("""INSERT INTO bidops.screening_audit_event
        (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
        VALUES ('audit-' || replace(gen_random_uuid()::text, '-', ''), 'db.migration', 'system:migration','database',
        '0043_company_wiki_ingest',CURRENT_TIMESTAMP,'{"migration_revision":"0043_company_wiki_ingest","action":"upgrade"}')""")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM bidops.company_wiki_ingest_run)
        THEN RAISE EXCEPTION '0043 downgrade refuses to discard ingests'; END IF; END $$""")
    op.drop_table("company_wiki_ingest_run", schema="bidops")
    op.execute("DROP FUNCTION bidops.guard_wiki_ingest()")
