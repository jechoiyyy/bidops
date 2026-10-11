"""DEMO-03 company analysis lineage: fit policy, graph scope, frozen provenance.

One revision carries every schema change of the DEMO-03 feature so later steps
need no further migration:

* ``company_fit_policy_version``: append-only ``bidops.company-fit-policy.v2``.
* ``prespec_company_fit_attempt``: purpose-specific policy FK (legacy rows keep
  ``deep_policy_version_id``; company rows use ``company_fit_policy_version_id``),
  ``graph_version_id`` with a (graph, company, profile) composite FK, frozen
  ``provenance_jsonb`` and a nullable ``model_revision`` for company rows whose
  policy declares no revision (legacy rows still require a 64-hex revision).
  The insert guard is replaced by one that keeps the legacy branch byte-for-byte
  and binds a company row to its frozen CompanyAnalysisInput.
* ``deep_review``: ``graph_version_id`` + composite FK; the company partial
  unique key ends with ``graph_version_id``.
* ``deep_review_preview``/``deep_review_approval``: nullable ``company_id``;
  the preview also pins ``graph_version_id`` and ``provenance_jsonb``.
* The MATCH SIMPLE NULL bypass of the profile/company composite FK is closed by
  the existing ``enforce_company_profile_scope`` trigger (0034 already attaches
  it to ``deep_review`` and the fit attempt); this revision attaches it to
  ``deep_review_preview``.

Runtime grants live in ``scripts/runtime-privileges.sql``, not here.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0036_company_analysis"
down_revision = "0035_company_knowledge"
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
            "occurred_at": "2026-01-01 00:00:36+00",
        },
    )


def _hex(column: str) -> str:
    return f"length({column}) = 64 AND {column} ~ '^[0-9a-f]*$'"


_GRAPH_SCOPE_COLUMNS = ["graph_version_id", "company_id", "profile_version_id"]
_GRAPH_SCOPE_TARGET = ["id", "company_id", "profile_version_id"]

_LEGACY_FIT_HASHES = (
    f"{_hex('input_sha256')} AND {_hex('policy_digest')} AND {_hex('model_revision')}"
)
_COMPANY_FIT_HASHES = (
    f"{_hex('input_sha256')} AND {_hex('policy_digest')} AND "
    f"((company_id IS NULL AND model_revision IS NOT NULL AND {_hex('model_revision')}) "
    f"OR (company_id IS NOT NULL AND (model_revision IS NULL OR ({_hex('model_revision')}))))"
)

# 0026's guard, kept verbatim for the legacy branch and for downgrade.
_LEGACY_GUARD = """
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

# The UPDATE/DELETE branch and the legacy INSERT branch are unchanged.  A
# company row must be the frozen CompanyAnalysisInput(purpose=company_fit) of
# this very row (execution_nonce = id) with the matching provenance snapshot.
# The frozen document list is the notice's current document-version set; the
# row's overview document must be one of them (input and provenance).
_COMPANY_GUARD = """
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
    IF NEW.company_id IS NULL THEN
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
    ELSE
      IF NEW.overview_run_id IS NULL
        OR (NEW.input_jsonb->>'schema_version') IS DISTINCT FROM 'bidops.company-analysis-input.v1'
        OR (NEW.input_jsonb->>'purpose') IS DISTINCT FROM 'company_fit'
        OR (NEW.input_jsonb->>'execution_nonce') IS DISTINCT FROM NEW.id::text
        OR (NEW.input_jsonb->'target_review_id') IS DISTINCT FROM 'null'::jsonb
        OR (NEW.input_jsonb->'bundle_id') IS DISTINCT FROM 'null'::jsonb
        OR (NEW.input_jsonb->>'company_id') IS DISTINCT FROM NEW.company_id::text
        OR (NEW.input_jsonb->>'notice_id') IS DISTINCT FROM NEW.notice_id::text
        OR jsonb_typeof(NEW.input_jsonb->'document_version_ids') IS DISTINCT FROM 'array'
        OR ((NEW.input_jsonb->'document_version_ids') @> jsonb_build_array(NEW.document_version_id::text)) IS NOT TRUE
        OR jsonb_typeof(NEW.provenance_jsonb->'documents') IS DISTINCT FROM 'array'
        OR ((NEW.provenance_jsonb->'documents')
            @> jsonb_build_array(jsonb_build_object('document_version_id', NEW.document_version_id::text))) IS NOT TRUE
        OR (NEW.input_jsonb->>'overview_run_id') IS DISTINCT FROM NEW.overview_run_id::text
        OR (NEW.input_jsonb->>'profile_version_id') IS DISTINCT FROM NEW.profile_version_id::text
        OR (NEW.input_jsonb->>'graph_version_id') IS DISTINCT FROM NEW.graph_version_id::text
        OR (NEW.input_jsonb->>'policy_version_id') IS DISTINCT FROM NEW.company_fit_policy_version_id::text
        OR (NEW.input_jsonb->>'policy_sha256') IS DISTINCT FROM NEW.policy_digest
        OR (NEW.input_jsonb->>'model_name') IS DISTINCT FROM NEW.model_name
        OR (NEW.input_jsonb->>'model_revision') IS DISTINCT FROM NEW.model_revision
        OR (NEW.provenance_jsonb->>'input_sha256') IS DISTINCT FROM NEW.input_sha256
        OR (NEW.provenance_jsonb->>'purpose') IS DISTINCT FROM 'company_fit'
        OR (NEW.provenance_jsonb->'bundle_id') IS DISTINCT FROM 'null'::jsonb
        OR (NEW.provenance_jsonb->>'company_id') IS DISTINCT FROM NEW.company_id::text
        OR (NEW.provenance_jsonb->>'profile_version_id') IS DISTINCT FROM NEW.profile_version_id::text
        OR (NEW.provenance_jsonb->>'graph_version_id') IS DISTINCT FROM NEW.graph_version_id::text
        OR (NEW.provenance_jsonb->>'overview_run_id') IS DISTINCT FROM NEW.overview_run_id::text
        OR (NEW.provenance_jsonb->>'policy_version_id') IS DISTINCT FROM NEW.company_fit_policy_version_id::text
        OR (NEW.provenance_jsonb->>'policy_sha256') IS DISTINCT FROM NEW.policy_digest
        OR (NEW.provenance_jsonb->>'model_name') IS DISTINCT FROM NEW.model_name
        OR (NEW.provenance_jsonb->>'model_revision') IS DISTINCT FROM NEW.model_revision THEN
        RAISE EXCEPTION 'company fit input binding rejected';
      END IF;
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


def _graph_scope_fk(name: str, table: str) -> None:
    op.create_foreign_key(
        name, table, "company_knowledge_version",
        _GRAPH_SCOPE_COLUMNS, _GRAPH_SCOPE_TARGET,
        source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT",
    )


def upgrade() -> None:
    bind = op.get_bind()
    # Earlier company rows (if any) carry no graph lineage and cannot be
    # back-filled without guessing; refuse rather than invent a binding.
    if bind.scalar(sa.text(
        f"""
        SELECT EXISTS (SELECT 1 FROM {SCHEMA}.deep_review WHERE company_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM {SCHEMA}.prespec_company_fit_attempt WHERE company_id IS NOT NULL)
        """
    )):
        raise RuntimeError("company analysis rows without graph lineage must be resolved first")

    op.create_table(
        "company_fit_policy_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_company_fit_policy_version_sha256"),
        sa.CheckConstraint(_hex("sha256"), name="ck_company_fit_policy_version_sha256"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_company_fit_policy_version_payload"
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_company_fit_policy_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'company fit policy versions are append-only';
        END;
        $$;
        CREATE TRIGGER immutable_company_fit_policy_version
        BEFORE UPDATE OR DELETE ON {SCHEMA}.company_fit_policy_version
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_company_fit_policy_mutation();
        """
    )

    # --- company fit attempt -------------------------------------------------
    table = "prespec_company_fit_attempt"
    op.alter_column(table, "deep_policy_version_id", existing_type=sa.Uuid(), nullable=True, schema=SCHEMA)
    op.alter_column(table, "model_revision", existing_type=sa.String(64), nullable=True, schema=SCHEMA)
    op.add_column(table, sa.Column("company_fit_policy_version_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column(table, sa.Column("graph_version_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column(table, sa.Column("provenance_jsonb", JSONB(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_prespec_company_fit_policy_version", table, "company_fit_policy_version",
        ["company_fit_policy_version_id"], ["id"],
        source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT",
    )
    _graph_scope_fk("fk_prespec_company_fit_graph_scope", table)
    op.create_check_constraint(
        "ck_prespec_company_fit_policy_scope", table,
        "(company_id IS NULL AND deep_policy_version_id IS NOT NULL AND company_fit_policy_version_id IS NULL) "
        "OR (company_id IS NOT NULL AND deep_policy_version_id IS NULL AND company_fit_policy_version_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_company_fit_graph_scope", table,
        "(company_id IS NULL) = (graph_version_id IS NULL)", schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_prespec_company_fit_provenance", table,
        "company_id IS NULL OR provenance_jsonb IS NOT NULL", schema=SCHEMA,
    )
    op.drop_constraint("ck_prespec_company_fit_hashes", table, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_prespec_company_fit_hashes", table, _COMPANY_FIT_HASHES, schema=SCHEMA)
    op.execute(_COMPANY_GUARD)

    # --- deep review -----------------------------------------------------------
    op.add_column("deep_review", sa.Column("graph_version_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    _graph_scope_fk("fk_deep_review_graph_scope", "deep_review")
    op.create_check_constraint(
        "ck_deep_review_graph_scope", "deep_review",
        "(company_id IS NULL) = (graph_version_id IS NULL)", schema=SCHEMA,
    )
    op.drop_index("uq_deep_review_company_inputs", table_name="deep_review", schema=SCHEMA)
    op.create_index(
        "uq_deep_review_company_inputs",
        "deep_review",
        ["company_id", "notice_id", "bundle_id", "profile_version_id", "policy_version_id", "graph_version_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_graph_scope_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.graph_version_id IS DISTINCT FROM OLD.graph_version_id THEN
                RAISE EXCEPTION 'company scope is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER deep_review_graph_scope_immutable
        BEFORE UPDATE OF graph_version_id ON {SCHEMA}.deep_review
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_graph_scope_change();
        """
    )

    # --- Luna preview / approval ----------------------------------------------
    op.add_column("deep_review_preview", sa.Column("company_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column("deep_review_preview", sa.Column("graph_version_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column("deep_review_preview", sa.Column("provenance_jsonb", JSONB(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_deep_review_preview_company", "deep_review_preview", "company",
        ["company_id"], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT",
    )
    _graph_scope_fk("fk_deep_review_preview_graph_scope", "deep_review_preview")
    op.create_check_constraint(
        "ck_deep_review_preview_graph_scope", "deep_review_preview",
        "(company_id IS NULL) = (graph_version_id IS NULL)", schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_deep_review_preview_provenance", "deep_review_preview",
        "company_id IS NULL OR provenance_jsonb IS NOT NULL", schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER deep_review_preview_company_profile_scope
        BEFORE INSERT ON {SCHEMA}.deep_review_preview
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.enforce_company_profile_scope();
        """
    )
    op.add_column("deep_review_approval", sa.Column("company_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_deep_review_approval_company", "deep_review_approval", "company",
        ["company_id"], ["id"], source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="RESTRICT",
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text(
        f"""
        SELECT EXISTS (SELECT 1 FROM {SCHEMA}.company_fit_policy_version)
            OR EXISTS (SELECT 1 FROM {SCHEMA}.prespec_company_fit_attempt WHERE company_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM {SCHEMA}.deep_review WHERE company_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM {SCHEMA}.deep_review_preview WHERE company_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM {SCHEMA}.deep_review_approval WHERE company_id IS NOT NULL)
        """
    )):
        raise RuntimeError("company analysis history must be preserved")

    op.drop_constraint("fk_deep_review_approval_company", "deep_review_approval", schema=SCHEMA, type_="foreignkey")
    op.drop_column("deep_review_approval", "company_id", schema=SCHEMA)
    op.execute(f"DROP TRIGGER deep_review_preview_company_profile_scope ON {SCHEMA}.deep_review_preview")
    for name in ("ck_deep_review_preview_provenance", "ck_deep_review_preview_graph_scope"):
        op.drop_constraint(name, "deep_review_preview", schema=SCHEMA, type_="check")
    for name in ("fk_deep_review_preview_graph_scope", "fk_deep_review_preview_company"):
        op.drop_constraint(name, "deep_review_preview", schema=SCHEMA, type_="foreignkey")
    for column in ("provenance_jsonb", "graph_version_id", "company_id"):
        op.drop_column("deep_review_preview", column, schema=SCHEMA)

    op.execute(
        f"""
        DROP TRIGGER deep_review_graph_scope_immutable ON {SCHEMA}.deep_review;
        DROP FUNCTION {SCHEMA}.reject_graph_scope_change();
        """
    )
    op.drop_index("uq_deep_review_company_inputs", table_name="deep_review", schema=SCHEMA)
    op.create_index(
        "uq_deep_review_company_inputs",
        "deep_review",
        ["company_id", "notice_id", "bundle_id", "profile_version_id", "policy_version_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )
    op.drop_constraint("ck_deep_review_graph_scope", "deep_review", schema=SCHEMA, type_="check")
    op.drop_constraint("fk_deep_review_graph_scope", "deep_review", schema=SCHEMA, type_="foreignkey")
    op.drop_column("deep_review", "graph_version_id", schema=SCHEMA)

    table = "prespec_company_fit_attempt"
    op.execute(_LEGACY_GUARD)
    op.drop_constraint("ck_prespec_company_fit_hashes", table, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_prespec_company_fit_hashes", table, _LEGACY_FIT_HASHES, schema=SCHEMA)
    for name in (
        "ck_prespec_company_fit_provenance",
        "ck_prespec_company_fit_graph_scope",
        "ck_prespec_company_fit_policy_scope",
    ):
        op.drop_constraint(name, table, schema=SCHEMA, type_="check")
    for name in ("fk_prespec_company_fit_graph_scope", "fk_prespec_company_fit_policy_version"):
        op.drop_constraint(name, table, schema=SCHEMA, type_="foreignkey")
    for column in ("provenance_jsonb", "graph_version_id", "company_fit_policy_version_id"):
        op.drop_column(table, column, schema=SCHEMA)
    op.alter_column(table, "model_revision", existing_type=sa.String(64), nullable=False, schema=SCHEMA)
    op.alter_column(table, "deep_policy_version_id", existing_type=sa.Uuid(), nullable=False, schema=SCHEMA)

    op.execute(
        f"""
        DROP TRIGGER immutable_company_fit_policy_version ON {SCHEMA}.company_fit_policy_version;
        DROP FUNCTION {SCHEMA}.reject_company_fit_policy_mutation();
        """
    )
    op.drop_table("company_fit_policy_version", schema=SCHEMA)
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
