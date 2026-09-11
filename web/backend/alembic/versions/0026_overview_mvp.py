"""폐기된 개요 스택(v3·legacy v4·v5) 철거와 MVP `prespec_overview_run` 도입."""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026_overview_mvp"
down_revision = "0025_overview_claim_ledger"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex

#: 의존 순서대로 지운다. 참조하는 쪽이 먼저다.
DROPPED_TABLES = (
    "prespec_overview_verification",
    "prespec_overview_call_event",
    "prespec_v4_attempt",
    "prespec_v4_target",
    "prespec_page_overview",
    "prespec_overview_attempt_event",
    "prespec_overview_result",
    "prespec_overview_attempt",
    "prespec_overview_snapshot",
    "prespec_overview_review",
)

#: 지운 테이블만 쓰던 trigger 함수. 테이블에 붙은 trigger는 DROP TABLE이 함께
#: 지우지만 함수는 남으므로 여기서 정리한다.
DROPPED_FUNCTIONS = (
    "tf_prespec_v4_attempt_guard()",
    "tf_prespec_page_overview_immutable()",
    "tf_prespec_overview_attempt_transition()",
    "tf_prespec_overview_snapshot_append_only()",
    "tf_prespec_overview_attempt_append_only()",
    "tf_overview_publication_atomic()",
    "assert_overview_publication(uuid)",
    "tf_overview_result_guard()",
    "tf_overview_verification_guard()",
    "tf_overview_call_guard()",
    "tf_overview_activation_guard()",
    "tf_overview_record_immutable()",
)

#: 회사 핏 행이 개요 run 하나를 가리키도록 고친 guard. 원본은 0020에 있고
#: 여기서 바뀌는 것은 개요 출처 컬럼과 그 scope 검사뿐이다.
COMPANY_FIT_GUARD = """
CREATE OR REPLACE FUNCTION bidops.tf_prespec_company_fit_guard() RETURNS trigger
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
      OR (NEW.input_jsonb->>'overview_id') IS DISTINCT FROM NEW.overview_run_id::text
      OR (NEW.input_jsonb->>'profile_version_id') IS DISTINCT FROM NEW.profile_version_id::text
      OR (NEW.input_jsonb->>'deep_policy_version_id') IS DISTINCT FROM NEW.deep_policy_version_id::text
      OR (NEW.input_jsonb->>'policy_digest') IS DISTINCT FROM NEW.policy_digest
      OR (NEW.input_jsonb->>'model_name') IS DISTINCT FROM NEW.model_name
      OR (NEW.input_jsonb->>'model_revision') IS DISTINCT FROM NEW.model_revision
      OR (NEW.input_jsonb->>'quality_status') IS DISTINCT FROM NEW.quality_status THEN
      RAISE EXCEPTION 'company fit input binding rejected';
    END IF;
    IF NEW.overview_run_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_overview_run r WHERE r.id = NEW.overview_run_id
      AND r.notice_id = NEW.notice_id AND r.document_version_id = NEW.document_version_id
      AND r.status = 'completed'
    ) THEN RAISE EXCEPTION 'company fit overview source scope rejected'; END IF;
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    # work_job에 붙은 개요 trigger는 테이블이 남으므로 따로 떼어 낸다.
    op.execute("DROP TRIGGER IF EXISTS tr_overview_job_atomic ON bidops.work_job")
    for table in DROPPED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table} CASCADE")
    for function in DROPPED_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{function}")
    op.create_table(
        "prespec_overview_run",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), sa.ForeignKey("bidops.notice.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), sa.ForeignKey("bidops.prespec_v4_pdf_snapshot.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("work_job_id", sa.UUID(), sa.ForeignKey("bidops.work_job.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("range_source", sa.String(16), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("range_reason_codes", JSONB(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=True),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("draft_json", JSONB(), nullable=True),
        sa.Column("checks_json", JSONB(), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("warnings_json", JSONB(), nullable=False),
        sa.Column("reason_codes", JSONB(), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False),
        sa.Column("raw_response_refs", JSONB(), nullable=False),
        sa.Column("actor_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            ["bidops.document_version.notice_id", "bidops.document_version.id"],
            ondelete="RESTRICT",
            name="fk_prespec_overview_run_document_scope",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','needs_human_review','failed','cancelled')",
            name="ck_prespec_overview_run_status",
        ),
        sa.CheckConstraint("range_source IN ('auto','fallback','human')", name="ck_prespec_overview_run_range_source"),
        sa.CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR (page_start >= 1 AND page_end >= page_start)",
            name="ck_prespec_overview_run_pages",
        ),
        sa.CheckConstraint("call_count >= 0", name="ck_prespec_overview_run_call_count"),
        sa.CheckConstraint(
            "(status = 'completed' AND result_json IS NOT NULL) OR status <> 'completed'",
            name="ck_prespec_overview_run_result",
        ),
        sa.CheckConstraint(
            "(input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$') AND policy_digest ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_overview_run_hashes",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prespec_overview_run_notice_created",
        "prespec_overview_run",
        ["notice_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_prespec_overview_run_active",
        "prespec_overview_run",
        ["notice_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
        schema=SCHEMA,
    )
    op.drop_constraint("ck_prespec_company_fit_source", "prespec_company_fit_attempt", schema=SCHEMA)
    op.drop_column("prespec_company_fit_attempt", "page_overview_id", schema=SCHEMA)
    op.drop_column("prespec_company_fit_attempt", "overview_result_id", schema=SCHEMA)
    op.add_column("prespec_company_fit_attempt", sa.Column("overview_run_id", sa.UUID(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_prespec_company_fit_overview_run",
        "prespec_company_fit_attempt",
        "prespec_overview_run",
        ["overview_run_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(COMPANY_FIT_GUARD)
    op.get_bind().execute(sa.text("""
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:26+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""), {"event_id": MIGRATION_EVENT_ID, "revision": revision,
       "details": json.dumps({"migration_revision": revision, "action": "upgrade"}, separators=(",", ":"))})


def downgrade() -> None:
    raise NotImplementedError("0026은 되돌리지 않는다; 백업으로 복구")
