"""Separate append-only assumptions, consent and invocation results."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0033_assumption_analysis'
down_revision = '0032_luna_deep_review'
branch_labels = depends_on = None


def fk(name, target):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey('bidops.' + target, ondelete='RESTRICT'), nullable=False)


def upgrade():
    op.create_table('assumption_input_version',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('notice_id', sa.Integer(), sa.ForeignKey('bidops.notice.id', ondelete='RESTRICT'), nullable=False),
        fk('bundle_id', 'document_bundle.id'), fk('profile_version_id', 'profile_version.id'),
        sa.Column('input_sha256', sa.String(64), nullable=False),
        sa.Column('input_snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(input_sha256) = 64', name='ck_assumption_input_hash'), schema='bidops')
    op.create_table('assumption_run',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('notice_id', sa.Integer(), sa.ForeignKey('bidops.notice.id', ondelete='RESTRICT'), nullable=False),
        fk('input_version_id', 'assumption_input_version.id'), fk('work_job_id', 'work_job.id'),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('claimed_name', sa.String(128), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('input_version_id'), sa.UniqueConstraint('work_job_id'), sa.UniqueConstraint('request_id'), schema='bidops')
    op.create_table('assumption_stage',
        sa.Column('id', sa.Uuid(), primary_key=True), fk('run_id', 'assumption_run.id'),
        sa.Column('stage', sa.String(16), nullable=False), sa.Column('part', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.String(64)), sa.Column('result', postgresql.JSONB()),
        sa.Column('raw_content_object_id', sa.Uuid(), sa.ForeignKey('bidops.content_object.id', ondelete='RESTRICT')),
        sa.UniqueConstraint('run_id', 'stage', 'part', name='uq_assumption_stage_part'),
        sa.CheckConstraint("stage IN ('business','company','decision')", name='ck_assumption_stage_name'),
        sa.CheckConstraint("status IN ('completed','failed')", name='ck_assumption_stage_status'),
        sa.CheckConstraint('part >= 0 AND latency_ms >= 0', name='ck_assumption_stage_numbers'), schema='bidops')
    for table in ('assumption_input_version', 'assumption_run', 'assumption_stage'):
        op.execute(f'CREATE TRIGGER immutable_assumption BEFORE UPDATE OR DELETE ON bidops.{table} FOR EACH ROW EXECUTE FUNCTION bidops.reject_luna_mutation()')


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM bidops.assumption_run')):
        raise RuntimeError('assumption approvals must be preserved')
    for table in ('assumption_stage', 'assumption_run', 'assumption_input_version'):
        op.drop_table(table, schema='bidops')
