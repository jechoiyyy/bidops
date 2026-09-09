"""Fenced v4 overview attempts and current-result lineage."""

from uuid import NAMESPACE_URL, uuid5
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0022_prespec_v4_attempt"
down_revision = "0021_prespec_v4_pdf_contract"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, "bidops:db.migration:" + revision
).hex


def upgrade() -> None:
    op.create_table(
        "prespec_v4_attempt",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("work_job_id", sa.UUID(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column("input_sha256", sa.String(64), nullable=True),
        sa.Column("selection_manifest_sha256", sa.String(64), nullable=True),
        sa.Column("policy_digest", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("model_digest", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(128), nullable=True),
        sa.Column("binding_digest", sa.String(64), nullable=True),
        sa.Column("generation_jsonb", JSONB(), nullable=True),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("reference_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deployable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("result_id", sa.UUID(), nullable=True),
        sa.Column("result_sha256", sa.String(64), nullable=True),
        sa.Column("raw_response_sha256", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notice_id"], ["bidops.notice.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_version_id"], ["bidops.document_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_id"], ["bidops.prespec_v4_target.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_job_id"], ["bidops.work_job.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_id"], ["bidops.prespec_page_overview.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("notice_id", "sequence", name="uq_prespec_v4_attempt_notice_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_prespec_v4_attempt_sequence"),
        sa.CheckConstraint(
            " AND ".join(
                f"({field} IS NULL OR {field} ~ '^[0-9a-f]{{64}}$')"
                for field in (
                    "source_sha256", "pdf_sha256", "input_sha256",
                    "selection_manifest_sha256", "policy_digest", "model_digest",
                    "binding_digest", "result_sha256", "raw_response_sha256",
                )
            ),
            name="ck_prespec_v4_attempt_hashes",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_prespec_v4_attempt_status",
        ),
        sa.CheckConstraint(
            "quality_status IN ('unmeasured_reference','mock_reference')",
            name="ck_prespec_v4_attempt_quality",
        ),
        sa.CheckConstraint(
            "(status IN ('queued','running','completed') AND target_id IS NOT NULL) OR status IN ('failed','cancelled')",
            name="ck_prespec_v4_attempt_target_scope",
        ),
        sa.CheckConstraint(
            "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND result_id IS NULL) "
            "OR (status IN ('failed','cancelled') AND completed_at IS NOT NULL AND result_id IS NULL) "
            "OR (status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND result_id IS NOT NULL))",
            name="ck_prespec_v4_attempt_completion",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_prespec_v4_attempt_lease",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND result_id IS NOT NULL AND result_sha256 IS NOT NULL) "
            "OR (status <> 'completed' AND result_id IS NULL AND result_sha256 IS NULL)",
            name="ck_prespec_v4_attempt_result",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prespec_v4_attempt_notice_created",
        "prespec_v4_attempt",
        ["notice_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_prespec_v4_attempt_active_target",
        "prespec_v4_attempt",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
        schema=SCHEMA,
    )
    op.execute(
        """
CREATE FUNCTION bidops.tf_prespec_v4_attempt_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'v4 attempts cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'queued' AND NEW.target_id IS NULL THEN
      RAISE EXCEPTION 'queued v4 attempt requires target';
    END IF;
    IF NEW.status = 'failed' AND NEW.target_id IS NULL AND NEW.error_code IS NULL THEN
      RAISE EXCEPTION 'failed preparation requires error code';
    END IF;
    IF NEW.target_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_v4_target t
      WHERE t.id = NEW.target_id
        AND t.notice_id = NEW.notice_id
        AND t.document_version_id = NEW.document_version_id
    ) THEN
      RAISE EXCEPTION 'v4 target scope rejected';
    END IF;
    IF NEW.result_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_page_overview r
      WHERE r.id = NEW.result_id
        AND r.notice_id = NEW.notice_id
        AND r.document_version_id = NEW.document_version_id
    ) THEN
      RAISE EXCEPTION 'v4 result scope rejected';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status IN ('completed','failed','cancelled') THEN
    RAISE EXCEPTION 'terminal v4 attempts are immutable';
  END IF;
  IF (to_jsonb(NEW) - ARRAY[
      'status','result_id','result_sha256','raw_response_sha256','error_code',
      'lease_owner','lease_expires_at','started_at','completed_at',
      'prompt_tokens','output_tokens','latency_ms'
    ]) IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY[
      'status','result_id','result_sha256','raw_response_sha256','error_code',
      'lease_owner','lease_expires_at','started_at','completed_at',
      'prompt_tokens','output_tokens','latency_ms'
    ]) THEN
    RAISE EXCEPTION 'v4 attempt inputs are immutable';
  END IF;
  IF NOT ((OLD.status = 'queued' AND NEW.status IN ('running','failed','cancelled')) OR
          (OLD.status = 'running' AND NEW.status IN ('completed','failed','cancelled'))) THEN
    RAISE EXCEPTION 'v4 attempt transition rejected';
  END IF;
  IF NEW.target_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM bidops.prespec_v4_target t
    WHERE t.id = NEW.target_id
      AND t.notice_id = NEW.notice_id
      AND t.document_version_id = NEW.document_version_id
  ) THEN
    RAISE EXCEPTION 'v4 target scope rejected';
  END IF;
  IF NEW.result_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM bidops.prespec_page_overview r
    WHERE r.id = NEW.result_id
      AND r.notice_id = NEW.notice_id
      AND r.document_version_id = NEW.document_version_id
  ) THEN
    RAISE EXCEPTION 'v4 result scope rejected';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER tr_prespec_v4_attempt_guard
BEFORE INSERT OR UPDATE OR DELETE ON bidops.prespec_v4_attempt
FOR EACH ROW EXECUTE FUNCTION bidops.tf_prespec_v4_attempt_guard();
"""
    )
    op.get_bind().execute(
        sa.text(
            """
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:22+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""
        ),
        {
            "event_id": MIGRATION_EVENT_ID,
            "revision": revision,
            "details": json.dumps({"migration_revision": revision, "action": "upgrade"}, separators=(",", ":")),
        },
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM bidops.prespec_v4_attempt)" )).scalar():
        raise RuntimeError("v4 attempt records exist; downgrade refused")
    op.execute("DROP TRIGGER IF EXISTS tr_prespec_v4_attempt_guard ON bidops.prespec_v4_attempt")
    op.execute("DROP FUNCTION IF EXISTS bidops.tf_prespec_v4_attempt_guard()")
    op.drop_index("uq_prespec_v4_attempt_active_target", table_name="prespec_v4_attempt", schema=SCHEMA)
    op.drop_index("ix_prespec_v4_attempt_notice_created", table_name="prespec_v4_attempt", schema=SCHEMA)
    op.drop_table("prespec_v4_attempt", schema=SCHEMA)
    op.get_bind().execute(
        sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"),
        {"event_id": MIGRATION_EVENT_ID},
    )
