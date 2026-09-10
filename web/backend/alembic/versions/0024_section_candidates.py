"""Nullable section candidate references on immutable v4 snapshots."""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "0024_section_candidates"
down_revision = "0023_rhwp_snapshot"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
TABLE = "prespec_v4_pdf_snapshot"
REFERENCES = {
    "section_candidates_content_object_id": "content_object",
    "section_candidates_location_id": "content_object_location",
}
EXTRA_COLUMNS = ("section_candidates_sha256",)
MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex


def upgrade() -> None:
    # Nullable only: snapshots frozen before this revision keep three NULLs and
    # stay reusable.  The existing UPDATE/DELETE immutability triggers and the
    # table-level worker INSERT grant cover the new columns unchanged.
    for column, target in REFERENCES.items():
        op.add_column(TABLE, sa.Column(column, sa.UUID(), nullable=True), schema=SCHEMA)
        op.create_foreign_key(f"fk_section_candidates_{column}", TABLE, target, [column], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT")
    for column in EXTRA_COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.String(64), nullable=True), schema=SCHEMA)
    op.get_bind().execute(sa.text("""
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:24+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""), {"event_id": MIGRATION_EVENT_ID, "revision": revision, "details": json.dumps({"migration_revision": revision, "action": "upgrade"})})


def downgrade() -> None:
    populated = " OR ".join(f"{column} IS NOT NULL" for column in (*REFERENCES, *EXTRA_COLUMNS))
    if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM bidops.{TABLE} WHERE {populated})")):
        raise RuntimeError("section candidate references exist; downgrade refused")
    for column in EXTRA_COLUMNS:
        op.drop_column(TABLE, column, schema=SCHEMA)
    for column in reversed(REFERENCES):
        op.drop_constraint(f"fk_section_candidates_{column}", TABLE, type_="foreignkey", schema=SCHEMA)
        op.drop_column(TABLE, column, schema=SCHEMA)
    op.get_bind().execute(sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"), {"event_id": MIGRATION_EVENT_ID})
