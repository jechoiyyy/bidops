"""Immutable v4 PDF preparation snapshot and input manifest."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
import json
from uuid import NAMESPACE_URL, uuid5


revision = "0021_prespec_v4_pdf_contract"
down_revision = "0020_prespec_company_fit"
branch_labels = None
depends_on = None
SCHEMA = "bidops"
MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, "bidops:db.migration:" + revision
).hex


def upgrade() -> None:
    op.create_table(
        "prespec_v4_pdf_snapshot",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("source_content_object_id", sa.UUID(), nullable=False),
        sa.Column("source_location_id", sa.UUID(), nullable=False),
        sa.Column("pdf_content_object_id", sa.UUID(), nullable=False),
        sa.Column("pdf_location_id", sa.UUID(), nullable=False),
        sa.Column("page_text_content_object_id", sa.UUID(), nullable=False),
        sa.Column("page_text_location_id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("pdf_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pdf_page_count", sa.Integer(), nullable=False),
        sa.Column("page_text_sha256", sa.String(64), nullable=False),
        sa.Column("page_text_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pdf_metadata_jsonb", JSONB(), nullable=False),
        sa.Column("renderer_jsonb", JSONB(), nullable=False),
        sa.Column("renderer_digest", sa.String(64), nullable=False),
        sa.Column("font_jsonb", JSONB(), nullable=False),
        sa.Column("font_digest", sa.String(64), nullable=False),
        sa.Column("config_jsonb", JSONB(), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("scan_jsonb", JSONB(), nullable=False),
        sa.Column("binding_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            ["bidops.document_version.notice_id", "bidops.document_version.id"],
            name="fk_prespec_v4_pdf_snapshot_document_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_content_object_id"], ["bidops.content_object.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_location_id"], ["bidops.content_object_location.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pdf_content_object_id"], ["bidops.content_object.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pdf_location_id"], ["bidops.content_object_location.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["page_text_content_object_id"], ["bidops.content_object.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["page_text_location_id"], ["bidops.content_object_location.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "document_version_id", "source_sha256", "config_sha256", "renderer_digest", "font_digest",
            name="uq_prespec_v4_pdf_snapshot_identity",
        ),
        sa.UniqueConstraint("document_version_id", "id", name="uq_prespec_v4_pdf_snapshot_document_scope"),
        sa.CheckConstraint("source_kind IN ('original','generated')", name="ck_prespec_v4_pdf_snapshot_source_kind"),
        sa.CheckConstraint("source_size_bytes > 0 AND pdf_size_bytes > 0", name="ck_prespec_v4_pdf_snapshot_sizes"),
        sa.CheckConstraint("pdf_page_count > 0", name="ck_prespec_v4_pdf_snapshot_pages"),
        sa.CheckConstraint("page_text_size_bytes > 0", name="ck_prespec_v4_pdf_snapshot_page_text_size"),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND source_sha256 ~ '^[0-9a-f]{64}$' AND "
            "length(pdf_sha256) = 64 AND pdf_sha256 ~ '^[0-9a-f]{64}$' AND "
            "length(page_text_sha256) = 64 AND page_text_sha256 ~ '^[0-9a-f]{64}$' AND "
            "length(config_sha256) = 64 AND config_sha256 ~ '^[0-9a-f]{64}$' AND "
            "length(renderer_digest) = 64 AND renderer_digest ~ '^[0-9a-f]{64}$' AND "
            "length(font_digest) = 64 AND font_digest ~ '^[0-9a-f]{64}$' AND "
            "length(binding_sha256) = 64 AND binding_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_prespec_v4_pdf_snapshot_hashes",
        ),
        sa.CheckConstraint("jsonb_typeof(pdf_metadata_jsonb) = 'object'", name="ck_prespec_v4_pdf_snapshot_metadata"),
        sa.CheckConstraint("jsonb_typeof(renderer_jsonb) = 'object'", name="ck_prespec_v4_pdf_snapshot_renderer"),
        sa.CheckConstraint("jsonb_typeof(font_jsonb) = 'object'", name="ck_prespec_v4_pdf_snapshot_font"),
        sa.CheckConstraint("jsonb_typeof(config_jsonb) = 'object'", name="ck_prespec_v4_pdf_snapshot_config"),
        sa.CheckConstraint("jsonb_typeof(scan_jsonb) = 'object'", name="ck_prespec_v4_pdf_snapshot_scan"),
        schema=SCHEMA,
    )

    op.create_table(
        "prespec_v4_target",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("observation_kind", sa.String(32), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=True),
        sa.Column("observation_jsonb", JSONB(), nullable=False),
        sa.Column("selection_status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("selection_strategy", sa.String(64), nullable=True),
        sa.Column("start_locator", JSONB(), nullable=True),
        sa.Column("end_locator", JSONB(), nullable=True),
        sa.Column("page_numbers_jsonb", JSONB(), nullable=True),
        sa.Column("input_text_sha256_jsonb", JSONB(), nullable=True),
        sa.Column("input_sha256", sa.String(64), nullable=True),
        sa.Column("input_byte_count", sa.BigInteger(), nullable=True),
        sa.Column("selection_manifest_sha256", sa.String(64), nullable=True),
        sa.Column("identity_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_content_object_id", sa.UUID(), nullable=True),
        sa.Column("manifest_location_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["notice_id", "document_version_id"],
            ["bidops.document_version.notice_id", "bidops.document_version.id"],
            name="fk_prespec_v4_target_document_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "snapshot_id"],
            ["bidops.prespec_v4_pdf_snapshot.document_version_id", "bidops.prespec_v4_pdf_snapshot.id"],
            name="fk_prespec_v4_target_snapshot_document_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["bidops.notice_observation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manifest_content_object_id"], ["bidops.content_object.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manifest_location_id"], ["bidops.content_object_location.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "snapshot_id", "identity_sha256",
            name="uq_prespec_v4_target_identity",
        ),
        sa.UniqueConstraint("document_version_id", "id", name="uq_prespec_v4_target_document_scope"),
        sa.CheckConstraint("selection_status IN ('ready','needs_human_review','excluded')", name="ck_prespec_v4_target_selection_status"),
        sa.CheckConstraint("observation_kind IN ('explicit_sample','first_observation','attachment_change')", name="ck_prespec_v4_target_observation_kind"),
        sa.CheckConstraint(
            "(observation_kind = 'explicit_sample' AND observation_id IS NULL) OR "
            "(observation_kind <> 'explicit_sample' AND observation_id IS NOT NULL)",
            name="ck_prespec_v4_target_observation_binding",
        ),
        sa.CheckConstraint(
            "((selection_status = 'ready' AND input_sha256 IS NOT NULL AND input_byte_count > 0 "
            "AND selection_manifest_sha256 IS NOT NULL AND manifest_content_object_id IS NOT NULL "
            "AND manifest_location_id IS NOT NULL AND start_locator IS NOT NULL AND end_locator IS NOT NULL "
            "AND page_numbers_jsonb IS NOT NULL) "
            "OR (selection_status IN ('needs_human_review','excluded') AND reason_code IS NOT NULL))",
            name="ck_prespec_v4_target_selection_contract",
        ),
        sa.CheckConstraint("jsonb_typeof(observation_jsonb) = 'object'", name="ck_prespec_v4_target_observation_json"),
        sa.CheckConstraint("start_locator IS NULL OR jsonb_typeof(start_locator) = 'object'", name="ck_prespec_v4_target_start_locator"),
        sa.CheckConstraint("end_locator IS NULL OR jsonb_typeof(end_locator) = 'object'", name="ck_prespec_v4_target_end_locator"),
        sa.CheckConstraint("page_numbers_jsonb IS NULL OR jsonb_typeof(page_numbers_jsonb) = 'array'", name="ck_prespec_v4_target_pages_json"),
        sa.CheckConstraint("input_text_sha256_jsonb IS NULL OR jsonb_typeof(input_text_sha256_jsonb) = 'array'", name="ck_prespec_v4_target_text_hashes_json"),
        sa.CheckConstraint("input_sha256 IS NULL OR (length(input_sha256) = 64 AND input_sha256 ~ '^[0-9a-f]{64}$')", name="ck_prespec_v4_target_input_hash"),
        sa.CheckConstraint("selection_manifest_sha256 IS NULL OR (length(selection_manifest_sha256) = 64 AND selection_manifest_sha256 ~ '^[0-9a-f]{64}$')", name="ck_prespec_v4_target_manifest_hash"),
        sa.CheckConstraint("length(identity_sha256) = 64 AND identity_sha256 ~ '^[0-9a-f]{64}$'", name="ck_prespec_v4_target_identity_hash"),
        schema=SCHEMA,
    )
    op.create_index("ix_prespec_v4_target_notice_created", "prespec_v4_target", ["notice_id", "created_at"], schema=SCHEMA)

    op.execute(
        """
CREATE FUNCTION bidops.tf_prespec_v4_input_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'v4 PDF inputs are append-only';
END $$;
CREATE TRIGGER tr_prespec_v4_pdf_snapshot_immutable
BEFORE UPDATE OR DELETE ON bidops.prespec_v4_pdf_snapshot
FOR EACH ROW EXECUTE FUNCTION bidops.tf_prespec_v4_input_immutable();
CREATE TRIGGER tr_prespec_v4_target_immutable
BEFORE UPDATE OR DELETE ON bidops.prespec_v4_target
FOR EACH ROW EXECUTE FUNCTION bidops.tf_prespec_v4_input_immutable();
"""
    )
    op.get_bind().execute(
        sa.text(
            """
INSERT INTO bidops.screening_audit_event
    (event_id,event_type,actor,target_type,target_id,occurred_at,details_json)
VALUES (:event_id,'db.migration','system:migration','database',:revision,
        '2026-01-01 00:00:21+00:00'::timestamptz,CAST(:details AS json))
ON CONFLICT (event_id) DO NOTHING
"""
        ),
        {
            "event_id": MIGRATION_EVENT_ID,
            "revision": revision,
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def downgrade() -> None:
    for table in ("prespec_v4_target", "prespec_v4_pdf_snapshot"):
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM bidops.{table})")).scalar():
            raise RuntimeError(f"{table} records exist; downgrade refused")
    op.execute("DROP TRIGGER IF EXISTS tr_prespec_v4_target_immutable ON bidops.prespec_v4_target")
    op.execute("DROP TRIGGER IF EXISTS tr_prespec_v4_pdf_snapshot_immutable ON bidops.prespec_v4_pdf_snapshot")
    op.execute("DROP FUNCTION bidops.tf_prespec_v4_input_immutable()")
    op.drop_table("prespec_v4_target", schema=SCHEMA)
    op.drop_table("prespec_v4_pdf_snapshot", schema=SCHEMA)
    op.get_bind().execute(
        sa.text("DELETE FROM bidops.screening_audit_event WHERE event_id=:event_id"),
        {"event_id": MIGRATION_EVENT_ID},
    )
