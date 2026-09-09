"""Append-only descriptive page summaries, separate from recommendation results."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0019_prespec_page_overview"
down_revision = "0018_prespec_auto_preparation_segments"
branch_labels = None
depends_on = None
SCHEMA = "bidops"


def upgrade() -> None:
    op.create_table(
        "prespec_page_overview",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("notice_id", sa.Integer(), sa.ForeignKey("bidops.notice.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("input_location_id", UUID(as_uuid=True), sa.ForeignKey("bidops.content_object_location.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pdf_location_id", UUID(as_uuid=True), sa.ForeignKey("bidops.content_object_location.id", ondelete="RESTRICT"), nullable=False),
        *[sa.Column(name, sa.String(64), nullable=False) for name in (
            "schema_version", "source_sha256", "pdf_sha256", "payload_sha256", "import_sha256", "input_sha256", "model_digest", "policy_digest", "validator_version")],
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(255), nullable=False),
        sa.Column("pdf_page_count", sa.Integer(), nullable=False),
        *[sa.Column(name, JSONB(), nullable=False) for name in (
            "reviewed_pages", "payload_jsonb", "validation_errors", "evidence_check_errors")],
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column("evidence_check_status", sa.String(16), nullable=False),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "notice_id", name="uq_prespec_page_overview_run_notice"),
        sa.ForeignKeyConstraint(["notice_id", "document_version_id"], ["bidops.document_version.notice_id", "bidops.document_version.id"], ondelete="RESTRICT", name="fk_prespec_page_overview_document_scope"),
        sa.CheckConstraint("schema_version = 'bidops.prespec-overview-page-review.v3'", name="ck_prespec_page_overview_schema"),
        sa.CheckConstraint("quality_status IN ('unmeasured_reference','mock_reference')", name="ck_prespec_page_overview_quality"),
        sa.CheckConstraint("validation_status IN ('passed','failed') AND evidence_check_status IN ('passed','failed')", name="ck_prespec_page_overview_validation"),
        sa.CheckConstraint("validation_status <> 'passed' OR evidence_check_status = 'passed'", name="ck_prespec_page_overview_passed"),
        sa.CheckConstraint("pdf_page_count > 0", name="ck_prespec_page_overview_pages"),
        sa.CheckConstraint("jsonb_typeof(payload_jsonb) = 'object'", name="ck_prespec_page_overview_payload"),
        sa.CheckConstraint(" AND ".join(f"{field} ~ '^[0-9a-f]{{64}}$'" for field in ("source_sha256", "pdf_sha256", "payload_sha256", "import_sha256", "input_sha256", "model_digest", "policy_digest")), name="ck_prespec_page_overview_hashes"),
        schema=SCHEMA,
    )
    op.create_index("ix_prespec_page_overview_notice_created", "prespec_page_overview", ["notice_id", "created_at"], schema=SCHEMA)
    op.execute("""
CREATE FUNCTION bidops.tf_prespec_page_overview_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'page overview is append-only'; END $$;
CREATE TRIGGER tr_prespec_page_overview_immutable BEFORE UPDATE OR DELETE
ON bidops.prespec_page_overview FOR EACH ROW
EXECUTE FUNCTION bidops.tf_prespec_page_overview_immutable();
""")


def downgrade() -> None:
    # Never silently discard imported model results on rollback.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM bidops.prespec_page_overview)")).scalar():
        raise RuntimeError("page overview records exist; downgrade refused")
    op.drop_table("prespec_page_overview", schema=SCHEMA)
    op.execute("DROP FUNCTION bidops.tf_prespec_page_overview_immutable()")
