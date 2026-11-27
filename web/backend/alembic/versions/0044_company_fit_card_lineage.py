"""PS-01 business scope card lineage on ``prespec_company_fit_attempt``.

The attempt table now carries three lineages:

* profile (``company_id IS NULL AND card_sha256 IS NULL``) -- unchanged v1 rows;
* business scope card (``company_id IS NULL AND card_sha256 IS NOT NULL``) --
  ``bidops.prespec-company-fit-input.v2`` frozen against a card file hash, with
  no profile, analysis policy, company-fit policy or graph;
* company (``company_id IS NOT NULL``) -- DEMO-03, unchanged.

Changes: ``card_version``/``card_sha256`` columns, nullable
``profile_version_id``, the rebuilt ``ck_prespec_company_fit_policy_scope`` and
an insert guard whose ``company_id IS NULL`` branch is split into the v1 branch
(kept byte-for-byte) and a new card branch.  UPDATE/DELETE rules are unchanged.
MVP scope (spec "MVP 범위" 1): no mode table.  Runtime grants are unchanged --
the attempt table already has table-level INSERT and the terminal-update column
list deliberately excludes the frozen card columns.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0044_company_fit_card_lineage"
down_revision = "0043_company_wiki_ingest"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
TABLE = "prespec_company_fit_attempt"
_MIGRATION_EVENT_ID = "audit-" + uuid5(NAMESPACE_URL, f"bidops:db.migration:{revision}").hex

_OLD_POLICY_SCOPE = (
    "(company_id IS NULL AND deep_policy_version_id IS NOT NULL AND company_fit_policy_version_id IS NULL) "
    "OR (company_id IS NOT NULL AND deep_policy_version_id IS NULL AND company_fit_policy_version_id IS NOT NULL)"
)
# Same text as ``deep_review.models.PRESPEC_COMPANY_FIT_POLICY_SCOPE_SQL``; a
# revision file never imports the moving model definition.
_POLICY_SCOPE = (
    "(company_id IS NULL AND card_sha256 IS NULL"
    " AND profile_version_id IS NOT NULL AND deep_policy_version_id IS NOT NULL"
    " AND company_fit_policy_version_id IS NULL AND card_version IS NULL)"
    " OR (company_id IS NULL AND card_sha256 IS NOT NULL"
    " AND card_version IS NOT NULL AND length(card_sha256) = 64"
    " AND profile_version_id IS NULL AND deep_policy_version_id IS NULL"
    " AND company_fit_policy_version_id IS NULL AND graph_version_id IS NULL)"
    " OR (company_id IS NOT NULL AND card_sha256 IS NULL AND card_version IS NULL"
    " AND deep_policy_version_id IS NULL AND company_fit_policy_version_id IS NOT NULL)"
)

_UPDATE_BRANCH = """
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
"""

_LEGACY_INSERT = """
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
"""

_CARD_INSERT = """
      IF NEW.overview_run_id IS NULL
        OR (NEW.input_jsonb->>'schema_version') IS DISTINCT FROM 'bidops.prespec-company-fit-input.v2'
        OR (NEW.input_jsonb->>'notice_id') IS DISTINCT FROM NEW.notice_id::text
        OR (NEW.input_jsonb->>'document_version_id') IS DISTINCT FROM NEW.document_version_id::text
        OR (NEW.input_jsonb->>'overview_id') IS DISTINCT FROM NEW.overview_run_id::text
        OR (NEW.input_jsonb->>'card_version') IS DISTINCT FROM NEW.card_version
        OR (NEW.input_jsonb->>'card_sha256') IS DISTINCT FROM NEW.card_sha256
        OR (NEW.input_jsonb->>'model_name') IS DISTINCT FROM NEW.model_name
        OR (NEW.input_jsonb->>'model_revision') IS DISTINCT FROM NEW.model_revision
        OR (NEW.input_jsonb->>'quality_status') IS DISTINCT FROM NEW.quality_status
        OR (NEW.input_jsonb->>'policy_digest') IS DISTINCT FROM NEW.policy_digest
        OR (NEW.input_jsonb->>'prompt_version') IS DISTINCT FROM 'prespec-company-fit-v3.1'
        OR (NEW.input_jsonb->>'judged_by') IS NULL
        OR (NEW.input_jsonb->>'judged_by') NOT IN ('model', 'claude_reference')
        OR NEW.card_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'company fit card input scope rejected';
      END IF;
"""

_COMPANY_INSERT = """
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
"""

_SOURCE_SCOPE = """
    IF NEW.overview_run_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM bidops.prespec_overview_run r WHERE r.id = NEW.overview_run_id
      AND r.notice_id = NEW.notice_id AND r.document_version_id = NEW.document_version_id
      AND r.status = 'completed'
    ) THEN RAISE EXCEPTION 'company fit overview source scope rejected'; END IF;
  END IF;
  RETURN NEW;
END $$;
"""

_HEADER = """
CREATE OR REPLACE FUNCTION bidops.tf_prespec_company_fit_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
"""

# 0036's guard (downgrade target): v1 branch for company_id IS NULL.
_GUARD_0036 = (
    _HEADER + _UPDATE_BRANCH
    + "    IF NEW.company_id IS NULL THEN\n" + _LEGACY_INSERT
    + "    ELSE\n" + _COMPANY_INSERT + "    END IF;\n"
    + _SOURCE_SCOPE
)

_GUARD_0044 = (
    _HEADER + _UPDATE_BRANCH
    + "    IF NEW.company_id IS NULL AND NEW.card_sha256 IS NULL THEN\n" + _LEGACY_INSERT
    + "    ELSIF NEW.company_id IS NULL THEN\n" + _CARD_INSERT
    + "    ELSE\n" + _COMPANY_INSERT + "    END IF;\n"
    + _SOURCE_SCOPE
)


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
            "details": json.dumps({"migration_revision": revision, "action": "upgrade"}, separators=(",", ":")),
            "occurred_at": "2026-01-01 00:00:44+00",
        },
    )


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("card_version", sa.String(64), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("card_sha256", sa.String(64), nullable=True), schema=SCHEMA)
    op.alter_column(TABLE, "profile_version_id", existing_type=sa.Uuid(), nullable=True, schema=SCHEMA)
    op.drop_constraint("ck_prespec_company_fit_policy_scope", TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_prespec_company_fit_policy_scope", TABLE, _POLICY_SCOPE, schema=SCHEMA)
    op.execute(_GUARD_0044)
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text(
        f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{TABLE} WHERE card_sha256 IS NOT NULL)"
    )):
        raise RuntimeError("company fit card lineage history must be preserved")
    op.execute(_GUARD_0036)
    op.drop_constraint("ck_prespec_company_fit_policy_scope", TABLE, schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_prespec_company_fit_policy_scope", TABLE, _OLD_POLICY_SCOPE, schema=SCHEMA)
    op.alter_column(TABLE, "profile_version_id", existing_type=sa.Uuid(), nullable=False, schema=SCHEMA)
    op.drop_column(TABLE, "card_sha256", schema=SCHEMA)
    op.drop_column(TABLE, "card_version", schema=SCHEMA)
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
