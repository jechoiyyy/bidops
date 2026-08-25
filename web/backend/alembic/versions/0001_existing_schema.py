"""Reproduce the pre-Alembic SQLAlchemy schema exactly."""

from alembic import op
import sqlalchemy as sa

revision = "0001_existing_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("window_from", sa.Date(), nullable=True),
        sa.Column("window_to", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("screening_basis", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("superseded_by", sa.String(length=160), sa.ForeignKey("run.id", ondelete="SET NULL"), nullable=True),
        sa.Column("counts_json", sa.JSON(), nullable=True),
    )
    op.create_table(
        "notice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=160), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notice_key", sa.String(length=255), nullable=False),
        sa.Column("bid_no", sa.String(length=64), nullable=True),
        sa.Column("bid_ord", sa.String(length=32), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("agency", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("budget", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("estimated_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("method", sa.String(length=128), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("sample_role", sa.String(length=64), nullable=True),
        sa.Column("sample_stratum", sa.String(length=128), nullable=True),
        sa.Column("collection_bucket", sa.String(length=64), nullable=True),
        sa.Column("procurement_class_json", sa.JSON(), nullable=True),
        sa.Column("region_limit_json", sa.JSON(), nullable=True),
        sa.Column("lifecycle_json", sa.JSON(), nullable=True),
        sa.Column("qualification_flags_json", sa.JSON(), nullable=True),
        sa.Column("focus_matches_json", sa.JSON(), nullable=True),
        sa.Column("performance_matches_json", sa.JSON(), nullable=True),
        sa.Column("performance_top_score", sa.Float(), nullable=True),
        sa.Column("candidate_sources_json", sa.JSON(), nullable=True),
        sa.Column("unknown_fields_json", sa.JSON(), nullable=True),
        sa.Column("raw_source", sa.JSON(), nullable=True),
        sa.UniqueConstraint("run_id", "notice_key", name="uq_notice_run_key"),
    )
    op.create_index("ix_notice_run_collection_sample", "notice", ["run_id", "collection_bucket", "sample_role"])
    op.create_index("ix_notice_notice_key", "notice", ["notice_key"])
    op.create_index("ix_notice_deadline_at", "notice", ["deadline_at"])
    op.create_table(
        "judgment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notice_pk", sa.Integer(), sa.ForeignKey("notice.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=True),
        sa.Column("grade", sa.String(length=32), nullable=True),
        sa.Column("readiness", sa.String(length=32), nullable=True),
        sa.Column("primary_focus", sa.String(length=128), nullable=True),
        sa.Column("exclusion_category", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.UniqueConstraint("notice_pk", name="uq_judgment_notice_pk"),
    )
    op.create_table(
        "perspective",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judgment_id", sa.Integer(), sa.ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("perspective_id", sa.Integer(), sa.ForeignKey("perspective.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("fact", sa.Text(), nullable=True),
    )
    op.create_table(
        "counterargument",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judgment_id", sa.Integer(), sa.ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
    )
    op.create_table(
        "verification_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judgment_id", sa.Integer(), sa.ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item", sa.Text(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "matched_performance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judgment_id", sa.Integer(), sa.ForeignKey("judgment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("mismatch_or_limit", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notice_pk", sa.Integer(), sa.ForeignKey("notice.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=True),
        sa.Column("file_ext", sa.String(length=16), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("stored_path", sa.Text(), nullable=True),
        sa.Column("extract_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agency_portal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_pattern", sa.String(length=255), nullable=False),
        sa.Column("system_name", sa.String(length=255), nullable=False),
        sa.Column("search_url_template", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notice_pk", sa.Integer(), sa.ForeignKey("notice.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(length=160), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("disposition", sa.String(length=64), nullable=True),
        sa.Column("system_judgment_review", sa.Text(), nullable=True),
        sa.Column("corrected_grade", sa.String(length=32), nullable=True),
        sa.Column("corrected_readiness", sa.String(length=32), nullable=True),
        sa.Column("weakest_perspective", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("notice_pk", "run_id", name="uq_review_notice_run"),
    )
    op.create_table(
        "verification_answer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("review.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
    )
    op.create_table(
        "ingest_warning",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=160), sa.ForeignKey("run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingest_warning")
    op.drop_table("verification_answer")
    op.drop_table("review")
    op.drop_table("agency_portal")
    op.drop_table("attachment")
    op.drop_table("matched_performance")
    op.drop_table("verification_item")
    op.drop_table("counterargument")
    op.drop_table("evidence")
    op.drop_table("perspective")
    op.drop_table("judgment")
    op.drop_index("ix_notice_deadline_at", table_name="notice")
    op.drop_index("ix_notice_notice_key", table_name="notice")
    op.drop_index("ix_notice_run_collection_sample", table_name="notice")
    op.drop_table("notice")
    op.drop_table("run")
