"""Add the immutable bid delta and final decision database layer.

Revision ID: 0015_bid_delta_final_decision
Revises: 0014_prespec_overview_attempt_result

This revision only creates storage and database guards.  It does not seed a
policy, invoke a model, or start a calculation.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_bid_delta_final_decision"
down_revision = "0014_prespec_overview_attempt_result"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-0f6e8d2c4b1a9078563412fedcba0987"


def _ensure_unique_constraint(table: str, name: str, columns: list[str]) -> None:
    """Add a composite-FK target when upgrading an older 0014 database."""

    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_unique_constraints(table, schema=SCHEMA)
    if any(
        constraint.get("name") == name
        or constraint.get("column_names") == columns
        for constraint in existing
    ):
        return
    op.create_unique_constraint(name, table, columns, schema=SCHEMA)


def _create_shared_fk_targets() -> None:
    # The current declarative metadata already includes these on a fresh
    # install.  Existing databases upgraded from 0014 need them before the
    # new composite foreign keys can be created.
    _ensure_unique_constraint(
        "opportunity_link",
        "uq_opportunity_link_opportunity_scope",
        ["id", "opportunity_id"],
    )
    _ensure_unique_constraint(
        "opportunity_link",
        "uq_opportunity_link_notice_scope",
        ["id", "notice_id"],
    )
    _ensure_unique_constraint(
        "document_bundle",
        "uq_document_bundle_notice_scope",
        ["id", "notice_id"],
    )


def _create_comparison_table(uuid: sa.TypeEngine) -> None:
    op.create_table(
        "bid_delta_comparison",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("category_policy_version", sa.String(length=64), nullable=False),
        sa.Column("baseline_link_id", sa.Integer(), nullable=False),
        sa.Column("baseline_notice_id", sa.Integer(), nullable=False),
        sa.Column("baseline_bundle_id", uuid, nullable=False),
        sa.Column("baseline_bundle_revision", sa.Integer(), nullable=False),
        sa.Column("baseline_bundle_version", sa.Integer(), nullable=False),
        sa.Column("baseline_document_version_id", uuid, nullable=False),
        sa.Column("baseline_document_version_version", sa.Integer(), nullable=False),
        sa.Column("baseline_structure_id", uuid, nullable=False),
        sa.Column("baseline_source_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "baseline_structure_payload_sha256", sa.String(length=64), nullable=False
        ),
        sa.Column("comparison_link_id", sa.Integer(), nullable=False),
        sa.Column("comparison_notice_id", sa.Integer(), nullable=False),
        sa.Column("comparison_bundle_id", uuid, nullable=False),
        sa.Column("comparison_bundle_revision", sa.Integer(), nullable=False),
        sa.Column("comparison_bundle_version", sa.Integer(), nullable=False),
        sa.Column("comparison_document_version_id", uuid, nullable=False),
        sa.Column("comparison_document_version_version", sa.Integer(), nullable=False),
        sa.Column("comparison_structure_id", uuid, nullable=False),
        sa.Column("comparison_source_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "comparison_structure_payload_sha256", sa.String(length=64), nullable=False
        ),
        sa.Column("calculation_status", sa.String(length=16), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=True),
        sa.Column("materiality", sa.String(length=16), nullable=False),
        sa.Column("current_attempt_id", uuid, nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("created_by_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "opportunity_id", "sequence", name="uq_bid_delta_comparison_sequence"
        ),
        sa.UniqueConstraint(
            "id", "opportunity_id", name="uq_bid_delta_comparison_opportunity_scope"
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "baseline_document_version_id",
            "comparison_document_version_id",
            "category_policy_version",
            name="uq_bid_delta_comparison_inputs",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            [f"{SCHEMA}.opportunity.id"],
            name="fk_bid_delta_comparison_opportunity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_link_id"],
            [f"{SCHEMA}.opportunity_link.id"],
            name="fk_bid_delta_comparison_baseline_link",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_bid_delta_comparison_baseline_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_bundle_id"],
            [f"{SCHEMA}.document_bundle.id"],
            name="fk_bid_delta_comparison_baseline_bundle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_bid_delta_comparison_baseline_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_structure_id"],
            [f"{SCHEMA}.document_structure.id"],
            name="fk_bid_delta_comparison_baseline_structure",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_link_id"],
            [f"{SCHEMA}.opportunity_link.id"],
            name="fk_bid_delta_comparison_comparison_link",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_bid_delta_comparison_comparison_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_bundle_id"],
            [f"{SCHEMA}.document_bundle.id"],
            name="fk_bid_delta_comparison_comparison_bundle",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_bid_delta_comparison_comparison_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_structure_id"],
            [f"{SCHEMA}.document_structure.id"],
            name="fk_bid_delta_comparison_comparison_structure",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_link_id", "opportunity_id"],
            [
                f"{SCHEMA}.opportunity_link.id",
                f"{SCHEMA}.opportunity_link.opportunity_id",
            ],
            name="fk_bid_delta_comparison_baseline_link_opportunity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_link_id", "opportunity_id"],
            [
                f"{SCHEMA}.opportunity_link.id",
                f"{SCHEMA}.opportunity_link.opportunity_id",
            ],
            name="fk_bid_delta_comparison_comparison_link_opportunity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_link_id", "baseline_notice_id"],
            [f"{SCHEMA}.opportunity_link.id", f"{SCHEMA}.opportunity_link.notice_id"],
            name="fk_bid_delta_comparison_baseline_link_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_link_id", "comparison_notice_id"],
            [f"{SCHEMA}.opportunity_link.id", f"{SCHEMA}.opportunity_link.notice_id"],
            name="fk_bid_delta_comparison_comparison_link_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_bundle_id", "baseline_notice_id"],
            [f"{SCHEMA}.document_bundle.id", f"{SCHEMA}.document_bundle.notice_id"],
            name="fk_bid_delta_comparison_baseline_bundle_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_bundle_id", "comparison_notice_id"],
            [f"{SCHEMA}.document_bundle.id", f"{SCHEMA}.document_bundle.notice_id"],
            name="fk_bid_delta_comparison_comparison_bundle_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "baseline_bundle_id",
                "baseline_document_version_id",
                "baseline_structure_id",
            ],
            [
                f"{SCHEMA}.document_bundle_item.bundle_id",
                f"{SCHEMA}.document_bundle_item.document_version_id",
                f"{SCHEMA}.document_bundle_item.structure_id_at_confirmation",
            ],
            name="fk_bid_delta_comparison_baseline_bundle_item_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "comparison_bundle_id",
                "comparison_document_version_id",
                "comparison_structure_id",
            ],
            [
                f"{SCHEMA}.document_bundle_item.bundle_id",
                f"{SCHEMA}.document_bundle_item.document_version_id",
                f"{SCHEMA}.document_bundle_item.structure_id_at_confirmation",
            ],
            name="fk_bid_delta_comparison_comparison_bundle_item_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_attempt_id"],
            [f"{SCHEMA}.bid_delta_attempt.comparison_id", f"{SCHEMA}.bid_delta_attempt.id"],
            name="fk_bid_delta_comparison_current_attempt_scope",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.CheckConstraint(
            "baseline_document_version_id <> comparison_document_version_id",
            name="ck_bid_delta_comparison_different_documents",
        ),
        sa.CheckConstraint(
            "calculation_status IN ('pending','running','completed','failed')",
            name="ck_bid_delta_comparison_calculation_status",
        ),
        sa.CheckConstraint(
            "result_status IS NULL OR result_status IN ('changed','unchanged','unknown','failed')",
            name="ck_bid_delta_comparison_result_status",
        ),
        sa.CheckConstraint(
            "materiality IN ('material','non_material','unknown')",
            name="ck_bid_delta_comparison_materiality",
        ),
        sa.CheckConstraint(
            "((calculation_status = 'pending' AND result_status IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL AND result_sha256 IS NULL) "
            "OR (calculation_status = 'running' AND result_status IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND result_sha256 IS NULL) "
            "OR (calculation_status = 'completed' "
            "AND result_status IN ('changed','unchanged','unknown') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND result_sha256 IS NOT NULL AND last_error_code IS NULL) "
            "OR (calculation_status = 'failed' AND result_status = 'failed' "
            "AND completed_at IS NOT NULL AND last_error_code IS NOT NULL "
            "AND result_sha256 IS NULL))",
            name="ck_bid_delta_comparison_lifecycle",
        ),
        sa.CheckConstraint(
            "((result_status = 'unchanged' AND materiality = 'non_material') "
            "OR (result_status IN ('unknown','failed') AND materiality = 'unknown') "
            "OR (result_status = 'changed' AND materiality IN ('material','non_material','unknown')) "
            "OR (result_status IS NULL AND materiality = 'unknown'))",
            name="ck_bid_delta_comparison_result_materiality",
        ),
        sa.CheckConstraint(
            "baseline_source_sha256 ~ '^[0-9a-f]{64}$' AND "
            "baseline_structure_payload_sha256 ~ '^[0-9a-f]{64}$' AND "
            "comparison_source_sha256 ~ '^[0-9a-f]{64}$' AND "
            "comparison_structure_payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_bid_delta_comparison_input_sha256",
        ),
        sa.CheckConstraint(
            "result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_bid_delta_comparison_result_sha256",
        ),
        sa.CheckConstraint(
            "length(trim(created_by_name)) > 0",
            name="ck_bid_delta_comparison_created_by_name",
        ),
        schema=SCHEMA,
    )


def _create_attempt_table(uuid: sa.TypeEngine) -> None:
    op.create_table(
        "bid_delta_attempt",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("comparison_id", uuid, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("work_job_id", uuid, nullable=True),
        sa.Column(
            "lease_fence", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("requested_by_name", sa.String(length=128), nullable=True),
        sa.Column("runtime_binding_id", sa.String(length=255), nullable=True),
        sa.Column("runtime_binding_digest", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("comparison_id", "sequence", name="uq_bid_delta_attempt_sequence"),
        sa.UniqueConstraint("comparison_id", "id", name="uq_bid_delta_attempt_scope"),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            [f"{SCHEMA}.bid_delta_comparison.id"],
            name="fk_bid_delta_attempt_comparison",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_job_id"],
            [f"{SCHEMA}.work_job.id"],
            name="fk_bid_delta_attempt_work_job",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_bid_delta_attempt_status",
        ),
        sa.CheckConstraint(
            "((status = 'queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND last_error_code IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) "
            "OR (status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND last_error_code IS NULL) "
            "OR (status = 'failed' AND completed_at IS NOT NULL "
            "AND last_error_code IS NOT NULL))",
            name="ck_bid_delta_attempt_lifecycle",
        ),
        sa.CheckConstraint(
            "runtime_binding_digest IS NULL OR runtime_binding_digest ~ '^[0-9a-f]{64}$'",
            name="ck_bid_delta_attempt_runtime_binding_digest",
        ),
        schema=SCHEMA,
    )


def _create_current_attempt_fk() -> None:
    op.create_foreign_key(
        "fk_bid_delta_comparison_current_attempt_scope",
        "bid_delta_comparison",
        "bid_delta_attempt",
        ["id", "current_attempt_id"],
        ["comparison_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def _create_item_table(uuid: sa.TypeEngine) -> None:
    op.create_table(
        "bid_delta_item",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("comparison_id", uuid, nullable=False),
        sa.Column("attempt_id", uuid, nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("materiality", sa.String(length=16), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=True),
        sa.Column("after_value", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("attempt_id", "category", name="uq_bid_delta_item_category"),
        sa.UniqueConstraint("attempt_id", "ordinal", name="uq_bid_delta_item_ordinal"),
        sa.UniqueConstraint("id", "attempt_id", name="uq_bid_delta_item_attempt_scope"),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            [f"{SCHEMA}.bid_delta_comparison.id"],
            name="fk_bid_delta_item_comparison",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            [f"{SCHEMA}.bid_delta_attempt.id"],
            name="fk_bid_delta_item_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "comparison_id"],
            [f"{SCHEMA}.bid_delta_attempt.id", f"{SCHEMA}.bid_delta_attempt.comparison_id"],
            name="fk_bid_delta_item_attempt_comparison_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "category IN ('budget_and_economics','contract_period_and_schedule',"
            "'eligibility','joint_supply_and_subcontracting','scope_and_requirements',"
            "'evaluation','submission')",
            name="ck_bid_delta_item_category",
        ),
        sa.CheckConstraint(
            "result_status IN ('changed','unchanged','unknown','failed')",
            name="ck_bid_delta_item_result_status",
        ),
        sa.CheckConstraint(
            "materiality IN ('material','non_material','unknown')",
            name="ck_bid_delta_item_materiality",
        ),
        sa.CheckConstraint(
            "((result_status = 'unchanged' AND materiality = 'non_material') "
            "OR (result_status IN ('unknown','failed') AND materiality = 'unknown') "
            "OR (result_status = 'changed' AND materiality IN ('material','non_material','unknown')))" ,
            name="ck_bid_delta_item_result_materiality",
        ),
        sa.CheckConstraint(
            "((result_status IN ('unknown','failed') AND error_code IS NOT NULL "
            "AND length(trim(error_code)) > 0) "
            "OR (result_status IN ('changed','unchanged') AND error_code IS NULL))",
            name="ck_bid_delta_item_error_code",
        ),
        schema=SCHEMA,
    )


def _create_evidence_table(uuid: sa.TypeEngine) -> None:
    op.create_table(
        "bid_delta_evidence",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("item_id", uuid, nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("document_version_id", uuid, nullable=False),
        sa.Column("structure_id", uuid, nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("locator_type", sa.String(length=16), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "side", "ordinal", name="uq_bid_delta_evidence_scope"),
        sa.ForeignKeyConstraint(
            ["item_id"],
            [f"{SCHEMA}.bid_delta_item.id"],
            name="fk_bid_delta_evidence_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_bid_delta_evidence_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["structure_id"],
            [f"{SCHEMA}.document_structure.id"],
            name="fk_bid_delta_evidence_structure",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "side IN ('baseline','comparison')", name="ck_bid_delta_evidence_side"
        ),
        sa.CheckConstraint(
            "locator_type IN ('page','paragraph','table_cell','bbox')",
            name="ck_bid_delta_evidence_locator_type",
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified','missing','mismatch')",
            name="ck_bid_delta_evidence_verification_status",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_bid_delta_evidence_source_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locator) = 'object'",
            name="ck_bid_delta_evidence_locator_object",
        ),
        schema=SCHEMA,
    )


def _create_final_decision_table(uuid: sa.TypeEngine) -> None:
    op.create_table(
        "bid_final_decision",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("comparison_id", uuid, nullable=False),
        sa.Column("comparison_version", sa.Integer(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("baseline_document_version_id", uuid, nullable=False),
        sa.Column("comparison_document_version_id", uuid, nullable=False),
        sa.Column("supersedes_final_decision_id", uuid, nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("claimed_name", sa.String(length=128), nullable=False),
        sa.Column("request_id", uuid, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "opportunity_id", "sequence", name="uq_bid_final_decision_sequence"
        ),
        sa.UniqueConstraint(
            "opportunity_id", "id", name="uq_bid_final_decision_opportunity_scope"
        ),
        sa.UniqueConstraint(
            "opportunity_id",
            "supersedes_final_decision_id",
            name="uq_bid_final_decision_supersession",
        ),
        sa.UniqueConstraint(
            "claimed_name", "opportunity_id", "request_id",
            name="uq_bid_final_decision_idempotency",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            [f"{SCHEMA}.opportunity.id"],
            name="fk_bid_final_decision_opportunity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            [f"{SCHEMA}.bid_delta_comparison.id"],
            name="fk_bid_final_decision_comparison",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_bid_final_decision_baseline_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_document_version_id"],
            [f"{SCHEMA}.document_version.id"],
            name="fk_bid_final_decision_comparison_document_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "supersedes_final_decision_id"],
            [
                f"{SCHEMA}.bid_final_decision.opportunity_id",
                f"{SCHEMA}.bid_final_decision.id",
            ],
            name="fk_bid_final_decision_supersedes_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id", "opportunity_id"],
            [
                f"{SCHEMA}.bid_delta_comparison.id",
                f"{SCHEMA}.bid_delta_comparison.opportunity_id",
            ],
            name="fk_bid_final_decision_comparison_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "decision IN ('go','no_go')", name="ck_bid_final_decision_value"
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_bid_final_decision_reason"
        ),
        sa.CheckConstraint(
            "length(trim(claimed_name)) > 0",
            name="ck_bid_final_decision_claimed_name",
        ),
        sa.CheckConstraint(
            "result_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_bid_final_decision_result_sha256",
        ),
        schema=SCHEMA,
    )


def _create_indexes() -> None:
    op.create_index(
        "uq_bid_delta_attempt_active",
        "bid_delta_attempt",
        ["comparison_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_bid_delta_item_comparison",
        "bid_delta_item",
        ["comparison_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_bid_final_decision_comparison",
        "bid_final_decision",
        ["comparison_id"],
        schema=SCHEMA,
    )


def _create_triggers() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.tf_bid_delta_append_only() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'bid_delta_append_only_violation'
        USING ERRCODE = 'check_violation';
END
$function$;
CREATE FUNCTION {SCHEMA}.tf_bid_delta_attempt_terminal() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.status IN ('completed','failed') THEN
        RAISE EXCEPTION 'bid_delta_terminal_attempt_violation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
CREATE FUNCTION {SCHEMA}.tf_bid_delta_attempt_terminal_delete() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.status IN ('completed','failed') THEN
        RAISE EXCEPTION 'bid_delta_terminal_attempt_violation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
END
$function$;
CREATE FUNCTION {SCHEMA}.tf_bid_delta_comparison_fence() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    IF NEW.baseline_link_id IS DISTINCT FROM OLD.baseline_link_id
       OR NEW.baseline_notice_id IS DISTINCT FROM OLD.baseline_notice_id
       OR NEW.baseline_bundle_id IS DISTINCT FROM OLD.baseline_bundle_id
       OR NEW.baseline_bundle_revision IS DISTINCT FROM OLD.baseline_bundle_revision
       OR NEW.baseline_bundle_version IS DISTINCT FROM OLD.baseline_bundle_version
       OR NEW.baseline_document_version_id IS DISTINCT FROM OLD.baseline_document_version_id
       OR NEW.baseline_document_version_version IS DISTINCT FROM OLD.baseline_document_version_version
       OR NEW.baseline_structure_id IS DISTINCT FROM OLD.baseline_structure_id
       OR NEW.baseline_source_sha256 IS DISTINCT FROM OLD.baseline_source_sha256
       OR NEW.baseline_structure_payload_sha256 IS DISTINCT FROM OLD.baseline_structure_payload_sha256
       OR NEW.comparison_link_id IS DISTINCT FROM OLD.comparison_link_id
       OR NEW.comparison_notice_id IS DISTINCT FROM OLD.comparison_notice_id
       OR NEW.comparison_bundle_id IS DISTINCT FROM OLD.comparison_bundle_id
       OR NEW.comparison_bundle_revision IS DISTINCT FROM OLD.comparison_bundle_revision
       OR NEW.comparison_bundle_version IS DISTINCT FROM OLD.comparison_bundle_version
       OR NEW.comparison_document_version_id IS DISTINCT FROM OLD.comparison_document_version_id
       OR NEW.comparison_document_version_version IS DISTINCT FROM OLD.comparison_document_version_version
       OR NEW.comparison_structure_id IS DISTINCT FROM OLD.comparison_structure_id
       OR NEW.comparison_source_sha256 IS DISTINCT FROM OLD.comparison_source_sha256
       OR NEW.comparison_structure_payload_sha256 IS DISTINCT FROM OLD.comparison_structure_payload_sha256
       OR NEW.category_policy_version IS DISTINCT FROM OLD.category_policy_version
       OR NEW.opportunity_id IS DISTINCT FROM OLD.opportunity_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence
       OR NEW.created_by_name IS DISTINCT FROM OLD.created_by_name
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'bid_delta_comparison_input_fence_violation'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.calculation_status = 'completed'
       AND (NEW.result_status IS DISTINCT FROM OLD.result_status
            OR NEW.result_sha256 IS DISTINCT FROM OLD.result_sha256
            OR NEW.materiality IS DISTINCT FROM OLD.materiality
            OR NEW.calculation_status IS DISTINCT FROM OLD.calculation_status) THEN
        RAISE EXCEPTION 'bid_delta_completed_result_violation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER tr_bid_delta_final_decision_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.bid_final_decision
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_append_only();
CREATE TRIGGER tr_bid_delta_item_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.bid_delta_item
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_append_only();
CREATE TRIGGER tr_bid_delta_evidence_append_only
BEFORE UPDATE OR DELETE ON {SCHEMA}.bid_delta_evidence
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_append_only();
CREATE TRIGGER tr_bid_delta_attempt_terminal
BEFORE UPDATE ON {SCHEMA}.bid_delta_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_attempt_terminal();
CREATE TRIGGER tr_bid_delta_attempt_terminal_delete
BEFORE DELETE ON {SCHEMA}.bid_delta_attempt
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_attempt_terminal_delete();
CREATE TRIGGER tr_bid_delta_comparison_fence
BEFORE UPDATE ON {SCHEMA}.bid_delta_comparison
FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_bid_delta_comparison_fence();
"""
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
            "occurred_at": "2026-01-01 00:00:12+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    _create_shared_fk_targets()
    uuid = postgresql.UUID(as_uuid=True)
    _create_comparison_table(uuid)
    _create_attempt_table(uuid)
    _create_current_attempt_fk()
    _create_item_table(uuid)
    _create_evidence_table(uuid)
    _create_final_decision_table(uuid)
    _create_indexes()
    _create_triggers()
    _record_migration_marker()


def _drop_trigger(name: str, table: str) -> None:
    op.get_bind().exec_driver_sql(
        f"DROP TRIGGER IF EXISTS {name} ON {SCHEMA}.{table}"
    )


def downgrade() -> None:
    # WARNING: this downgrade drops the R-08 tables and therefore their data;
    # use it only after exporting or reconciling disposable validation data.
    bind = op.get_bind()
    for name, table in (
        ("tr_bid_delta_comparison_fence", "bid_delta_comparison"),
        ("tr_bid_delta_attempt_terminal_delete", "bid_delta_attempt"),
        ("tr_bid_delta_attempt_terminal", "bid_delta_attempt"),
        ("tr_bid_delta_evidence_append_only", "bid_delta_evidence"),
        ("tr_bid_delta_item_append_only", "bid_delta_item"),
        ("tr_bid_delta_final_decision_append_only", "bid_final_decision"),
    ):
        _drop_trigger(name, table)
    for function in (
        "tf_bid_delta_comparison_fence",
        "tf_bid_delta_attempt_terminal_delete",
        "tf_bid_delta_attempt_terminal",
        "tf_bid_delta_append_only",
    ):
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.{function}()")

    # The comparison owns the deferred current-attempt FK, so remove that
    # edge before dropping the referenced attempt table.
    op.drop_constraint(
        "fk_bid_delta_comparison_current_attempt_scope",
        table_name="bid_delta_comparison",
        type_="foreignkey",
        schema=SCHEMA,
    )
    for table in (
        "bid_final_decision",
        "bid_delta_evidence",
        "bid_delta_item",
        "bid_delta_attempt",
        "bid_delta_comparison",
    ):
        op.drop_table(table, schema=SCHEMA)
    # These target keys are introduced only so the R-08 scoped foreign keys
    # can be declared on the existing lineage tables.  Remove them after the
    # referencing tables are gone.
    for table, name in (
        ("document_bundle", "uq_document_bundle_notice_scope"),
        ("opportunity_link", "uq_opportunity_link_notice_scope"),
        ("opportunity_link", "uq_opportunity_link_opportunity_scope"),
    ):
        op.drop_constraint(name, table_name=table, type_="unique", schema=SCHEMA)
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
