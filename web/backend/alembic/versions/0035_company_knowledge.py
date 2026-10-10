"""Add immutable company knowledge versions and active bindings."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0035_company_knowledge"
down_revision = "0034_company_context"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, f"bidops:db.migration:{revision}"
).hex


def _record_migration_marker() -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.screening_audit_event
                (event_id, event_type, actor, target_type, target_id,
                 occurred_at, details_json)
            VALUES (:event_id, 'db.migration', 'system:migration', 'database',
                    :revision, CAST(:occurred_at AS timestamptz),
                    CAST(:details AS json))
            ON CONFLICT (event_id) DO NOTHING
            """
        ),
        {
            "event_id": _MIGRATION_EVENT_ID,
            "revision": revision,
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
            "occurred_at": "2026-01-01 00:00:35+00",
        },
    )


def _hash_check(column: str) -> str:
    return f"length({column}) = 64 AND {column} ~ '^[0-9a-f]*$'"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_content_object_location_content_scope",
        "content_object_location",
        ["id", "content_object_id"],
        schema=SCHEMA,
    )
    op.create_table(
        "knowledge_ontology_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_knowledge_ontology_version"),
        sa.UniqueConstraint("sha256", name="uq_knowledge_ontology_sha256"),
        sa.CheckConstraint(_hash_check("sha256"), name="ck_knowledge_ontology_sha256"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_knowledge_ontology_payload"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_source",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_object_id", sa.Uuid(), nullable=False),
        sa.Column("content_location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["content_object_id"], [f"{SCHEMA}.content_object.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["content_location_id", "content_object_id"],
            [
                f"{SCHEMA}.content_object_location.id",
                f"{SCHEMA}.content_object_location.content_object_id",
            ],
            ondelete="RESTRICT",
            name="fk_company_knowledge_source_location_content",
        ),
        sa.UniqueConstraint(
            "company_id", "source_sha256", name="uq_company_knowledge_source_identity"
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_company_knowledge_source_company"),
        sa.CheckConstraint("size_bytes > 0", name="ck_company_knowledge_source_size"),
        sa.CheckConstraint(
            _hash_check("source_sha256"), name="ck_company_knowledge_source_sha256"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("graph_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ontology_id"], [f"{SCHEMA}.knowledge_ontology_version.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id", "company_id"],
            [f"{SCHEMA}.profile_version.id", f"{SCHEMA}.profile_version.company_id"],
            ondelete="RESTRICT",
            name="fk_company_knowledge_version_profile_company",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "company_id"],
            [f"{SCHEMA}.company_knowledge_source.id", f"{SCHEMA}.company_knowledge_source.company_id"],
            ondelete="RESTRICT",
            name="fk_company_knowledge_version_source_company",
        ),
        sa.UniqueConstraint(
            "company_id", "ontology_id", "source_sha256",
            name="uq_company_knowledge_version_identity",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_company_knowledge_version_company"),
        sa.UniqueConstraint(
            "id", "company_id", "profile_version_id",
            name="uq_company_knowledge_version_profile_scope",
        ),
        sa.CheckConstraint(
            _hash_check("source_sha256"), name="ck_company_knowledge_version_source_sha256"
        ),
        sa.CheckConstraint(
            _hash_check("graph_sha256"), name="ck_company_knowledge_version_graph_sha256"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name="ck_company_knowledge_version_snapshot"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_node",
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("graph_version_id", "node_id"),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], [f"{SCHEMA}.company_knowledge_version.id"],
            ondelete="CASCADE", name="fk_company_knowledge_node_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_company_knowledge_node_payload"
        ),
        sa.CheckConstraint(
            "payload->>'id' = node_id", name="ck_company_knowledge_node_payload_id"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_edge",
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("edge_id", sa.String(128), nullable=False),
        sa.Column("from_id", sa.String(128), nullable=False),
        sa.Column("to_id", sa.String(128), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("graph_version_id", "edge_id"),
        sa.ForeignKeyConstraint(
            ["graph_version_id", "from_id"],
            [f"{SCHEMA}.company_knowledge_node.graph_version_id", f"{SCHEMA}.company_knowledge_node.node_id"],
            ondelete="CASCADE", name="fk_company_knowledge_edge_from_node",
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id", "to_id"],
            [f"{SCHEMA}.company_knowledge_node.graph_version_id", f"{SCHEMA}.company_knowledge_node.node_id"],
            ondelete="CASCADE", name="fk_company_knowledge_edge_to_node",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_company_knowledge_edge_payload"
        ),
        sa.CheckConstraint(
            "payload->>'id' = edge_id AND payload->>'from_id' = from_id "
            "AND payload->>'to_id' = to_id",
            name="ck_company_knowledge_edge_payload_identity",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_binding",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("company_id"),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id", "company_id", "profile_version_id"],
            [
                f"{SCHEMA}.company_knowledge_version.id",
                f"{SCHEMA}.company_knowledge_version.company_id",
                f"{SCHEMA}.company_knowledge_version.profile_version_id",
            ],
            ondelete="RESTRICT", name="fk_company_knowledge_binding_version_scope",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_company_knowledge_binding_revision"),
        sa.CheckConstraint(
            "length(trim(actor)) BETWEEN 1 AND 128", name="ck_company_knowledge_binding_actor"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "company_knowledge_binding_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("previous_graph_version_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], [f"{SCHEMA}.company.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id", "company_id", "profile_version_id"],
            [
                f"{SCHEMA}.company_knowledge_version.id",
                f"{SCHEMA}.company_knowledge_version.company_id",
                f"{SCHEMA}.company_knowledge_version.profile_version_id",
            ],
            ondelete="RESTRICT", name="fk_company_knowledge_binding_event_version_scope",
        ),
        sa.ForeignKeyConstraint(
            ["previous_graph_version_id", "company_id"],
            [f"{SCHEMA}.company_knowledge_version.id", f"{SCHEMA}.company_knowledge_version.company_id"],
            ondelete="RESTRICT", name="fk_company_knowledge_binding_event_previous_company",
        ),
        sa.UniqueConstraint(
            "company_id", "revision", name="uq_company_knowledge_binding_event_revision"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_company_knowledge_binding_event_revision"
        ),
        sa.CheckConstraint(
            "length(trim(actor)) BETWEEN 1 AND 128",
            name="ck_company_knowledge_binding_event_actor",
        ),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_company_knowledge_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'company knowledge lineage is append-only';
        END;
        $$;
        """
    )
    for table in (
        "knowledge_ontology_version",
        "company_knowledge_source",
        "company_knowledge_version",
        "company_knowledge_node",
        "company_knowledge_edge",
        "company_knowledge_binding_event",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON "
            f"{SCHEMA}.{table} FOR EACH ROW EXECUTE FUNCTION "
            f"{SCHEMA}.reject_company_knowledge_mutation()"
        )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.guard_company_knowledge_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'company knowledge binding cannot be deleted';
            END IF;
            IF NEW.company_id IS DISTINCT FROM OLD.company_id
               OR NEW.revision <> OLD.revision + 1
               OR (NEW.graph_version_id, NEW.profile_version_id)
                    IS NOT DISTINCT FROM (OLD.graph_version_id, OLD.profile_version_id)
            THEN
                RAISE EXCEPTION 'invalid company knowledge binding transition';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER guarded_company_knowledge_binding
        BEFORE UPDATE OR DELETE ON {SCHEMA}.company_knowledge_binding
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.guard_company_knowledge_binding();
        """
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    if any(
        bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{table})"))
        for table in (
            "company_knowledge_binding_event",
            "company_knowledge_binding",
            "company_knowledge_edge",
            "company_knowledge_node",
            "company_knowledge_version",
            "company_knowledge_source",
            "knowledge_ontology_version",
        )
    ):
        raise RuntimeError("company knowledge history must be preserved")
    op.execute(
        f"DROP TRIGGER guarded_company_knowledge_binding ON {SCHEMA}.company_knowledge_binding"
    )
    op.execute(f"DROP FUNCTION {SCHEMA}.guard_company_knowledge_binding()")
    for table in (
        "company_knowledge_binding_event",
        "company_knowledge_edge",
        "company_knowledge_node",
        "company_knowledge_version",
        "company_knowledge_source",
        "knowledge_ontology_version",
    ):
        op.execute(f"DROP TRIGGER immutable_{table} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.reject_company_knowledge_mutation()")
    for table in (
        "company_knowledge_binding_event",
        "company_knowledge_binding",
        "company_knowledge_edge",
        "company_knowledge_node",
        "company_knowledge_version",
        "company_knowledge_source",
        "knowledge_ontology_version",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.drop_constraint(
        "uq_content_object_location_content_scope",
        "content_object_location",
        schema=SCHEMA,
        type_="unique",
    )
