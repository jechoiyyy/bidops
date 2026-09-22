"""Immutable per-attempt Luna source previews and transfer approvals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_luna_deep_review"
down_revision = "0031_prespec_preliminary_assessment"
branch_labels = depends_on = None


def upgrade():
    op.create_table("deep_review_preview",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), sa.ForeignKey("bidops.notice.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("bidops.document_bundle.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), sa.ForeignKey("bidops.profile_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), sa.ForeignKey("bidops.analysis_policy_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(input_sha256) = 64", name="ck_deep_review_preview_hash"), schema="bidops")
    op.create_table("deep_review_approval",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("preview_id", sa.Uuid(), sa.ForeignKey("bidops.deep_review_preview.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("bidops.deep_review_attempt.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("claimed_name", sa.String(128), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("preview_id", name="uq_deep_review_approval_preview"),
        sa.UniqueConstraint("attempt_id", name="uq_deep_review_approval_attempt"), schema="bidops")
    op.execute("""CREATE FUNCTION bidops.reject_luna_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'immutable Luna consent'; END $$""")
    for table in ("deep_review_preview", "deep_review_approval"):
        op.execute(f"CREATE TRIGGER immutable_luna BEFORE UPDATE OR DELETE ON bidops.{table} FOR EACH ROW EXECUTE FUNCTION bidops.reject_luna_mutation()")


def downgrade():
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM bidops.deep_review_approval"))
    if count:
        raise RuntimeError("Luna approvals must be preserved")
    op.drop_table("deep_review_approval", schema="bidops")
    op.drop_table("deep_review_preview", schema="bidops")
    op.execute("DROP FUNCTION bidops.reject_luna_mutation()")
