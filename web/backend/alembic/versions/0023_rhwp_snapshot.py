"""Nullable native rhwp artifacts on immutable v4 snapshots."""

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023_rhwp_snapshot"
down_revision = "0022_prespec_v4_attempt"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
TABLE = "prespec_v4_pdf_snapshot"
REFERENCES = {
    "hwpx_content_object_id": "content_object",
    "hwpx_location_id": "content_object_location",
    "structure_id": "document_structure",
    "structure_location_id": "content_object_location",
    "para_page_map_content_object_id": "content_object",
    "para_page_map_location_id": "content_object_location",
}
EXTRA_COLUMNS = ("hwpx_verify_jsonb", "para_page_map_sha256", "rhwp_binary_sha256", "rhwp_version")
MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, "bidops:db.migration:" + revision).hex


def _attempt_guard(*, upgrade: bool) -> None:
    # Preserve the existing scope/transition/terminal guards verbatim; extend
    # only the two outcome-column lists in the installed 0022 function.
    definition = op.get_bind().scalar(sa.text(
        "SELECT pg_get_functiondef('bidops.tf_prespec_v4_attempt_guard()'::regprocedure)"
    ))
    old = "'prompt_tokens','output_tokens','latency_ms'"
    new = old + ",'validation_warnings'"
    before, after = (old, new) if upgrade else (new, old)
    if definition.count(before) != 2:
        raise RuntimeError("unexpected v4 attempt guard; migration refused")
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    for column, target in REFERENCES.items():
        op.add_column(TABLE, sa.Column(column, sa.UUID(), nullable=True), schema=SCHEMA)
        op.create_foreign_key(f"fk_rhwp_snapshot_{column}", TABLE, target, [column], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT")
    op.add_column(TABLE, sa.Column("hwpx_verify_jsonb", JSONB(none_as_null=True), nullable=True), schema=SCHEMA)
    for column, length in (("para_page_map_sha256", 64), ("rhwp_binary_sha256", 64), ("rhwp_version", 32)):
        op.add_column(TABLE, sa.Column(column, sa.String(length), nullable=True), schema=SCHEMA)
    op.add_column("prespec_v4_attempt", sa.Column("validation_warnings", JSONB(none_as_null=True), nullable=True), schema=SCHEMA)
    _attempt_guard(upgrade=True)
    op.get_bind().execute(sa.text("""
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:23+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""), {"event_id": MIGRATION_EVENT_ID, "revision": revision, "details": json.dumps({"migration_revision": revision, "action": "upgrade"})})


def downgrade() -> None:
    populated = " OR ".join(f"{column} IS NOT NULL" for column in (*REFERENCES, *EXTRA_COLUMNS))
    if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM bidops.{TABLE} WHERE {populated}) OR EXISTS (SELECT 1 FROM bidops.prespec_v4_attempt WHERE validation_warnings IS NOT NULL)")):
        raise RuntimeError("rhwp snapshot or validation warnings exist; downgrade refused")
    _attempt_guard(upgrade=False)
    op.drop_column("prespec_v4_attempt", "validation_warnings", schema=SCHEMA)
    for column in EXTRA_COLUMNS:
        op.drop_column(TABLE, column, schema=SCHEMA)
    for column in reversed(REFERENCES):
        op.drop_constraint(f"fk_rhwp_snapshot_{column}", TABLE, type_="foreignkey", schema=SCHEMA)
        op.drop_column(TABLE, column, schema=SCHEMA)
    op.get_bind().execute(sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"), {"event_id": MIGRATION_EVENT_ID})
