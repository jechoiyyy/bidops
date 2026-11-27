"""Add wiki-scoped review requests and immutable human receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0045_engine_review"
down_revision = "0044_company_fit_card_lineage"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
REQUEST = "engine_review_request"
PREVIEW = "engine_review_preview"
APPROVAL = "engine_review_approval"
ACK = "engine_review_acknowledgment"
FETCH_REASON = "ck_attachment_fetch_eligibility_reason"
LEGACY_REASONS = "'sw_business_object','tracked_order_plan','both','priority_grade'"


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _ref(name, target, type_=sa.Uuid()):
    return sa.Column(name, type_, sa.ForeignKey(f"bidops.{target}.id", ondelete="RESTRICT"),
                     nullable=False)


def _time(name, *, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fetch_reasons(reasons):
    op.drop_constraint(FETCH_REASON, "attachment_fetch", type_="check", schema=SCHEMA)
    op.create_check_constraint(FETCH_REASON, "attachment_fetch",
                               f"eligibility_reason IN ({reasons})", schema=SCHEMA)


def upgrade():
    for column in ("company_id", "profile_version_id"):
        op.alter_column("engine_run", column, nullable=True, schema=SCHEMA)
    op.add_column("engine_run", sa.Column("company_bundle_slug", sa.Text()), schema=SCHEMA)
    op.add_column("engine_run", sa.Column("company_bundle_sha256", sa.String(64)), schema=SCHEMA)
    op.create_check_constraint(
        "ck_engine_run_company_scope", "engine_run",
        "(company_id IS NOT NULL AND profile_version_id IS NOT NULL AND "
        "company_bundle_slug IS NULL AND company_bundle_sha256 IS NULL) OR "
        "(company_id IS NULL AND profile_version_id IS NULL AND "
        "company_bundle_slug IS NOT NULL AND company_bundle_sha256 IS NOT NULL)",
        schema=SCHEMA,
    )
    _engine_guard(wiki=True)
    _fetch_reasons(LEGACY_REASONS + ",'engine_review_request'")

    op.create_table(
        REQUEST, _id(), _ref("notice_id", "notice", sa.Integer()),
        _ref("opportunity_id", "opportunity", sa.Integer()),
        sa.Column("company_bundle_slug", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.String(128), nullable=False),
        _time("requested_at"), sa.Column("request_id", sa.Uuid(), nullable=False),
        _time("closed_at", nullable=True),
        sa.Column("closed_reason", sa.String(16)),
        sa.Column("closed_by", sa.String(128)),
        sa.UniqueConstraint("request_id", name="uq_engine_review_request_id"),
        sa.CheckConstraint("origin IN ('tracking_start','manual')", name="ck_engine_review_origin"),
        sa.CheckConstraint(
            "(closed_at IS NULL AND closed_reason IS NULL AND closed_by IS NULL) OR "
            "(closed_at IS NOT NULL AND closed_reason IS NOT NULL AND closed_by IS NOT NULL "
            "AND closed_reason IN ('tracking_ended','dismissed','superseded'))",
            name="ck_engine_review_closed",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_bidops_engine_review_request_notice_id", REQUEST, ["notice_id"], schema=SCHEMA)
    op.create_index("uq_engine_review_open_notice", REQUEST, ["notice_id"], schema=SCHEMA,
                    unique=True, postgresql_where=sa.text("closed_at IS NULL"))

    op.create_table(
        PREVIEW, _id(), _ref("review_request_id", REQUEST), _ref("bundle_id", "document_bundle"),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("planned_calls", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        _time("created_at"), _time("expires_at"),
        sa.UniqueConstraint("review_request_id", "manifest_sha256", name="uq_engine_review_preview_manifest"),
        sa.CheckConstraint("mode IN ('mock_reference','live')", name="ck_engine_review_preview_mode"),
        sa.CheckConstraint("planned_calls >= 0", name="ck_engine_review_preview_calls"),
        schema=SCHEMA,
    )
    op.create_table(
        APPROVAL, _id(), _ref("preview_id", PREVIEW), _ref("engine_run_id", "engine_run"),
        sa.Column("approved_by", sa.String(128), nullable=False), _time("approved_at"),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("preview_id", name="uq_engine_review_approved_preview"),
        sa.UniqueConstraint("request_id", name="uq_engine_review_approval_id"),
        sa.UniqueConstraint("engine_run_id", name="uq_engine_review_approved_run"),
        schema=SCHEMA,
    )
    op.create_table(
        ACK, _id(), _ref("engine_run_id", "engine_run"),
        sa.Column("acknowledged_by", sa.String(128), nullable=False), _time("acknowledged_at"),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_engine_review_acknowledgment_id"),
        sa.UniqueConstraint("engine_run_id", name="uq_engine_review_acknowledged_run"),
        schema=SCHEMA,
    )
    op.execute("""
        CREATE FUNCTION bidops.guard_engine_review_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'engine review receipt immutable';
        END; $$;
    """)
    for table in (PREVIEW, APPROVAL, ACK):
        op.execute(f"""
            CREATE TRIGGER engine_review_receipt_guard BEFORE UPDATE OR DELETE ON bidops.{table}
            FOR EACH ROW EXECUTE FUNCTION bidops.guard_engine_review_receipt()
        """)
    op.execute("""
        CREATE FUNCTION bidops.guard_engine_review_request() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine review request immutable'; END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.closed_at IS NOT NULL THEN RAISE EXCEPTION 'engine review request must start open'; END IF;
            RETURN NEW;
          END IF;
          IF OLD.closed_at IS NOT NULL OR NEW.closed_at IS NULL OR
             (to_jsonb(OLD) - ARRAY['closed_at','closed_reason','closed_by']) IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY['closed_at','closed_reason','closed_by'])
          THEN RAISE EXCEPTION 'engine review request immutable'; END IF;
          RETURN NEW;
        END; $$;
    """)
    op.execute("""
        CREATE TRIGGER engine_review_request_guard BEFORE INSERT OR UPDATE OR DELETE ON bidops.engine_review_request
        FOR EACH ROW EXECUTE FUNCTION bidops.guard_engine_review_request()
    """)
    op.execute("""INSERT INTO bidops.screening_audit_event
        (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
        VALUES ('audit-' || replace(gen_random_uuid()::text, '-', ''), 'db.migration', 'system:migration','database',
        '0045_engine_review',CURRENT_TIMESTAMP,'{"migration_revision":"0045_engine_review","action":"upgrade"}')""")


def downgrade():
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bidops.engine_review_request)
             OR EXISTS (SELECT 1 FROM bidops.engine_review_preview)
             OR EXISTS (SELECT 1 FROM bidops.engine_review_approval)
             OR EXISTS (SELECT 1 FROM bidops.engine_review_acknowledgment)
             OR EXISTS (SELECT 1 FROM bidops.engine_run WHERE company_id IS NULL)
             OR EXISTS (SELECT 1 FROM bidops.attachment_fetch WHERE eligibility_reason = 'engine_review_request')
          THEN RAISE EXCEPTION '0045 downgrade refuses to discard engine review data'; END IF;
        END $$;
    """)
    for table in (ACK, APPROVAL, PREVIEW, REQUEST):
        op.drop_table(table, schema=SCHEMA)
    op.execute("DROP FUNCTION bidops.guard_engine_review_request()")
    op.execute("DROP FUNCTION bidops.guard_engine_review_receipt()")
    _fetch_reasons(LEGACY_REASONS)
    _engine_guard(wiki=False)
    op.drop_constraint("ck_engine_run_company_scope", "engine_run", type_="check", schema=SCHEMA)
    op.drop_column("engine_run", "company_bundle_sha256", schema=SCHEMA)
    op.drop_column("engine_run", "company_bundle_slug", schema=SCHEMA)
    for column in ("company_id", "profile_version_id"):
        op.alter_column("engine_run", column, nullable=False, schema=SCHEMA)


def _engine_guard(*, wiki):
    insert_scope = """        IF NEW.company_id IS NULL THEN
          IF NEW.input_payload->>'schema_version' IS DISTINCT FROM 'bidops.engine-input.v3'
             OR NEW.input_payload #>> '{company_bundle,slug}' IS DISTINCT FROM NEW.company_bundle_slug
             OR NEW.input_payload #>> '{company_bundle,bundle_sha256}' IS DISTINCT FROM NEW.company_bundle_sha256
             OR NEW.input_payload ?| ARRAY['company_id','profile_version_id','profile_sha256','graph_version_id','graph_sha256']
          THEN RAISE EXCEPTION 'engine wiki scope mismatch'; END IF;
        ELSIF NOT EXISTS (SELECT 1 FROM bidops.profile_version p
                          WHERE p.id=NEW.profile_version_id AND p.company_id=NEW.company_id)
              OR NEW.input_payload->>'schema_version' = 'bidops.engine-input.v3'
        THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NOT EXISTS (SELECT 1 FROM bidops.document_bundle b WHERE b.id=NEW.bundle_id AND b.notice_id=NEW.notice_id) THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NEW.input_payload->>'company_id' IS DISTINCT FROM NEW.company_id::text OR NEW.input_payload->>'bundle_id' IS DISTINCT FROM NEW.bundle_id::text OR NEW.input_payload->>'notice_id' IS DISTINCT FROM NEW.notice_id::text OR NEW.input_payload->>'profile_version_id' IS DISTINCT FROM NEW.profile_version_id::text OR NEW.input_payload->>'mode' IS DISTINCT FROM 'mock_reference' THEN RAISE EXCEPTION 'engine input scope mismatch'; END IF;
    """ if wiki else """
        IF NOT EXISTS (SELECT 1 FROM bidops.profile_version p WHERE p.id=NEW.profile_version_id AND p.company_id=NEW.company_id) OR NOT EXISTS (SELECT 1 FROM bidops.document_bundle b WHERE b.id=NEW.bundle_id AND b.notice_id=NEW.notice_id) THEN RAISE EXCEPTION 'engine scope mismatch'; END IF;
        IF NEW.input_payload->>'company_id' IS DISTINCT FROM NEW.company_id::text OR NEW.input_payload->>'bundle_id' IS DISTINCT FROM NEW.bundle_id::text OR NEW.input_payload->>'notice_id' IS DISTINCT FROM NEW.notice_id::text OR NEW.input_payload->>'profile_version_id' IS DISTINCT FROM NEW.profile_version_id::text OR NEW.input_payload->>'mode' IS DISTINCT FROM 'mock_reference' THEN RAISE EXCEPTION 'engine input scope mismatch'; END IF;
    """
    op.execute(f"""CREATE OR REPLACE FUNCTION bidops.guard_engine_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine run immutable'; END IF;
      IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.result_payload IS NOT NULL OR NEW.result_sha256 IS NOT NULL OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'invalid engine creation'; END IF;
{insert_scope}        RETURN NEW;
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
