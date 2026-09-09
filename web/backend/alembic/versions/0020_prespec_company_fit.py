"""Frozen company-fit inputs and terminal assessment history."""
from alembic import op
import sqlalchemy as sa
import json
from uuid import NAMESPACE_URL, uuid5

revision = "0020_prespec_company_fit"
down_revision = "0019_prespec_page_overview"
branch_labels = None
depends_on = None
MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex


def upgrade() -> None:
    op.execute("""
CREATE TABLE bidops.prespec_company_fit_attempt (
	id UUID NOT NULL, 
	notice_id INTEGER NOT NULL, 
	document_version_id UUID NOT NULL, 
	page_overview_id UUID, 
	overview_result_id UUID, 
	profile_version_id UUID NOT NULL, 
	deep_policy_version_id UUID NOT NULL, 
	input_jsonb JSONB NOT NULL, 
	input_sha256 VARCHAR(64) NOT NULL, 
	policy_digest VARCHAR(64) NOT NULL, 
	model_name VARCHAR(255) NOT NULL, 
	model_revision VARCHAR(64) NOT NULL, 
	quality_status VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	result_jsonb JSONB, 
	result_sha256 VARCHAR(64), 
	raw_response_sha256 VARCHAR(64), 
	error_code VARCHAR(64), 
	lease_owner VARCHAR(255), 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	prompt_tokens INTEGER, 
	output_tokens INTEGER, 
	latency_ms INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_prespec_company_fit_input UNIQUE (input_sha256), 
	CONSTRAINT fk_prespec_company_fit_document_scope FOREIGN KEY(notice_id, document_version_id) REFERENCES bidops.document_version (notice_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_prespec_company_fit_status CHECK (status IN ('queued','running','completed','failed','needs_human_review')), 
	CONSTRAINT ck_prespec_company_fit_quality CHECK (quality_status IN ('unmeasured_reference','mock_reference')), 
	CONSTRAINT ck_prespec_company_fit_source CHECK ((page_overview_id IS NOT NULL AND overview_result_id IS NULL) OR (page_overview_id IS NULL AND overview_result_id IS NOT NULL)), 
	CONSTRAINT ck_prespec_company_fit_result CHECK ((status = 'completed' AND result_jsonb IS NOT NULL AND result_sha256 IS NOT NULL) OR (status <> 'completed' AND result_jsonb IS NULL AND result_sha256 IS NULL)), 
	CONSTRAINT ck_prespec_company_fit_completion CHECK ((status IN ('queued','running') AND completed_at IS NULL) OR (status IN ('completed','failed','needs_human_review') AND completed_at IS NOT NULL)), 
	CONSTRAINT ck_prespec_company_fit_lease CHECK ((status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)), 
	CONSTRAINT ck_prespec_company_fit_hashes CHECK (length(input_sha256) = 64 AND input_sha256 ~ '^[0-9a-f]*$' AND length(policy_digest) = 64 AND policy_digest ~ '^[0-9a-f]*$' AND length(model_revision) = 64 AND model_revision ~ '^[0-9a-f]*$'), 
	FOREIGN KEY(notice_id) REFERENCES bidops.notice (id) ON DELETE RESTRICT, 
	FOREIGN KEY(page_overview_id) REFERENCES bidops.prespec_page_overview (id) ON DELETE RESTRICT, 
	FOREIGN KEY(overview_result_id) REFERENCES bidops.prespec_overview_result (id) ON DELETE RESTRICT, 
	FOREIGN KEY(profile_version_id) REFERENCES bidops.profile_version (id) ON DELETE RESTRICT, 
	FOREIGN KEY(deep_policy_version_id) REFERENCES bidops.analysis_policy_version (id) ON DELETE RESTRICT
)

""")
    op.execute("""CREATE INDEX ix_prespec_company_fit_notice_created ON bidops.prespec_company_fit_attempt (notice_id, created_at)""")
    op.execute("""
CREATE FUNCTION bidops.tf_prespec_company_fit_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'company fit attempts cannot be deleted'; END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.status IN ('completed','failed','needs_human_review') THEN
      RAISE EXCEPTION 'terminal company fit attempts are immutable';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status','result_jsonb','result_sha256','raw_response_sha256','error_code','lease_owner','lease_expires_at','completed_at','prompt_tokens','output_tokens','latency_ms'])
        IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status','result_jsonb','result_sha256','raw_response_sha256','error_code','lease_owner','lease_expires_at','completed_at','prompt_tokens','output_tokens','latency_ms']) THEN
      RAISE EXCEPTION 'company fit inputs are immutable';
    END IF;
    IF NOT ((OLD.status = 'queued' AND NEW.status IN ('running','failed')) OR
            (OLD.status = 'running' AND NEW.status IN ('completed','failed','needs_human_review'))) THEN
      RAISE EXCEPTION 'company fit transition rejected';
    END IF;
  ELSE
    IF NEW.status <> 'queued' THEN RAISE EXCEPTION 'company fit must be queued'; END IF;
    IF (NEW.input_jsonb->>'schema_version') IS DISTINCT FROM 'bidops.prespec-company-fit-input.v1'
      OR (NEW.input_jsonb->>'notice_id') IS DISTINCT FROM NEW.notice_id::text
      OR (NEW.input_jsonb->>'document_version_id') IS DISTINCT FROM NEW.document_version_id::text
      OR (NEW.input_jsonb->>'overview_id') IS DISTINCT FROM COALESCE(NEW.page_overview_id,NEW.overview_result_id)::text
      OR (NEW.input_jsonb->>'profile_version_id') IS DISTINCT FROM NEW.profile_version_id::text
      OR (NEW.input_jsonb->>'deep_policy_version_id') IS DISTINCT FROM NEW.deep_policy_version_id::text
      OR (NEW.input_jsonb->>'policy_digest') IS DISTINCT FROM NEW.policy_digest
      OR (NEW.input_jsonb->>'model_name') IS DISTINCT FROM NEW.model_name
      OR (NEW.input_jsonb->>'model_revision') IS DISTINCT FROM NEW.model_revision
      OR (NEW.input_jsonb->>'quality_status') IS DISTINCT FROM NEW.quality_status THEN
      RAISE EXCEPTION 'company fit input binding rejected';
    END IF;
    IF NEW.page_overview_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_page_overview WHERE id = NEW.page_overview_id
      AND notice_id = NEW.notice_id AND document_version_id = NEW.document_version_id
    ) THEN RAISE EXCEPTION 'company fit page source scope rejected'; END IF;
    IF NEW.overview_result_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_overview_result r
      JOIN bidops.prespec_overview_snapshot s ON s.id = r.snapshot_id
      JOIN bidops.prespec_overview_review v ON v.id = r.review_id
      WHERE r.id = NEW.overview_result_id AND v.notice_id = NEW.notice_id AND s.document_version_id = NEW.document_version_id
    ) THEN RAISE EXCEPTION 'company fit extractive source scope rejected'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_prespec_company_fit_guard BEFORE INSERT OR UPDATE OR DELETE
ON bidops.prespec_company_fit_attempt FOR EACH ROW EXECUTE FUNCTION bidops.tf_prespec_company_fit_guard();
""")
    op.get_bind().execute(sa.text("""
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:20+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""), {"event_id": MIGRATION_EVENT_ID, "revision": revision,
       "details": json.dumps({"migration_revision": revision, "action": "upgrade"}, separators=(",", ":"))})


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM bidops.prespec_company_fit_attempt)")).scalar():
        raise RuntimeError("company fit records exist; downgrade refused")
    op.drop_table("prespec_company_fit_attempt", schema="bidops")
    op.execute("DROP FUNCTION bidops.tf_prespec_company_fit_guard()")
    op.get_bind().execute(sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"), {"event_id": MIGRATION_EVENT_ID})
