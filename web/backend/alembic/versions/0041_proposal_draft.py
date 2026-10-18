"""Add RL-04 proposal draft storage (draft, section revisions, edit overlay, export).

Tables follow RL-04 spec "저장"; CHECK, index and FK declarations are identical
to ``app/deep_review/models.py`` so ``alembic check`` reports no drift.

Triggers (the role-specific rules key on ``current_user`` like 0025, so the
migration owner and test fixtures are only held to the role-agnostic rules):

* ``proposal_draft``: no DELETE; identity columns frozen; ``started_at`` written
  once; ``superseded`` is terminal and only the web role sets it; the worker
  advances ``status`` (never to ``superseded``) along ``queued -> running ->
  completed|partial|failed`` and re-settles a settled draft among those three
  after a regeneration (RL-04 STEP-005), and the ``toc -> draft`` stage;
  the web role advances ``draft -> reviewed -> ready`` only; the web INSERT must
  be ``queued``/``toc``.
* ``proposal_section``: no DELETE; identity columns frozen; every worker result
  column (hashes, payload, error_code, token/latency counters, completed_at) and
  the reviewed pair are written once; status moves only
  ``queued -> running|failed``, ``running -> completed|failed`` (worker) and
  ``completed -> reviewed`` (web); the web INSERT must be an empty ``queued`` row.
* ``proposal_sentence_edit`` and ``proposal_export`` reject every UPDATE/DELETE.

Runtime grants are not issued here: ``scripts/runtime-privileges.sql`` owns them
(column-scoped UPDATE per role; no DELETE for any role).
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0041_proposal_draft"
down_revision = "0040_card_analysis"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-" + uuid5(
    NAMESPACE_URL, f"bidops:db.migration:{revision}"
).hex
_TABLES = ("proposal_export", "proposal_sentence_edit", "proposal_section", "proposal_draft")
_SECTION_KEYS = (
    "overview", "track_record", "strategy", "requirements", "operations_sla", "organization",
)
_SECTION_KEY_SQL = ",".join(f"'{key}'" for key in _SECTION_KEYS)
_HEX = "{c} ~ '^[0-9a-f]{{64}}$'"


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
            "occurred_at": "2026-01-01 00:00:41+00",
            "details": json.dumps(
                {"migration_revision": revision, "action": "upgrade"},
                separators=(",", ":"),
            ),
        },
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "proposal_draft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("verdict_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("policy_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], [f"{SCHEMA}.opportunity.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["notice_id"], [f"{SCHEMA}.notice.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["verdict_attempt_id"], [f"{SCHEMA}.deep_review_attempt.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"], [f"{SCHEMA}.analysis_policy_version.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], [f"{SCHEMA}.transfer_policy_approval.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(_HEX.format(c="policy_sha256"), name="ck_proposal_draft_policy_hash"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','partial','failed','superseded')",
            name="ck_proposal_draft_status",
        ),
        sa.CheckConstraint(
            "stage IN ('toc','draft','reviewed','ready')", name="ck_proposal_draft_stage"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_proposal_draft_opportunity",
        "proposal_draft",
        ["opportunity_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "proposal_section",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("section_key", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("result_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("payload", JSONB(none_as_null=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        _created_at(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["draft_id"], [f"{SCHEMA}.proposal_draft.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "draft_id", "section_key", "revision", name="uq_proposal_section_revision"
        ),
        sa.CheckConstraint(
            f"section_key IN ({_SECTION_KEY_SQL})", name="ck_proposal_section_key"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_proposal_section_revision"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','reviewed')",
            name="ck_proposal_section_status",
        ),
        sa.CheckConstraint(
            "(input_sha256 IS NULL OR (" + _HEX.format(c="input_sha256") + ")) AND "
            "(result_sha256 IS NULL OR (" + _HEX.format(c="result_sha256") + "))",
            name="ck_proposal_section_hashes",
        ),
        sa.CheckConstraint(
            "payload IS NULL OR jsonb_typeof(payload) = 'object'",
            name="ck_proposal_section_payload",
        ),
        sa.CheckConstraint(
            "(reviewed_by IS NULL) = (reviewed_at IS NULL) AND "
            "(status = 'reviewed') = (reviewed_by IS NOT NULL)",
            name="ck_proposal_section_reviewed",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "proposal_sentence_edit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("sentence_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["section_id"], [f"{SCHEMA}.proposal_section.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("request_id", name="uq_proposal_sentence_edit_request"),
        sa.CheckConstraint(
            "length(text) >= 1 AND length(text) <= 400", name="ck_proposal_sentence_edit_text"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_proposal_sentence_edit_sentence",
        "proposal_sentence_edit",
        ["section_id", "sentence_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "proposal_export",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("overlay_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("renderer_version", sa.Text(), nullable=False),
        sa.Column("font_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("content_object_id", sa.Uuid(), nullable=False),
        sa.Column("pdf_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["draft_id"], [f"{SCHEMA}.proposal_draft.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["content_object_id"], [f"{SCHEMA}.content_object.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("draft_id", "overlay_sha256", name="uq_proposal_export_overlay"),
        sa.CheckConstraint(
            _HEX.format(c="overlay_sha256")
            + " AND " + _HEX.format(c="font_sha256")
            + " AND " + _HEX.format(c="pdf_sha256"),
            name="ck_proposal_export_hashes",
        ),
        sa.CheckConstraint("page_count >= 1", name="ck_proposal_export_page_count"),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.tf_proposal_draft_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'proposal drafts are never deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF current_user = 'app' AND (
                    NEW.status <> 'queued' OR NEW.stage <> 'toc'
                    OR NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'a proposal draft is created queued at the toc stage';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.opportunity_id, NEW.notice_id, NEW.verdict_attempt_id,
                NEW.policy_version_id, NEW.policy_sha256, NEW.approval_id,
                NEW.created_by, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.opportunity_id, OLD.notice_id, OLD.verdict_attempt_id,
                OLD.policy_version_id, OLD.policy_sha256, OLD.approval_id,
                OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'proposal draft identity is immutable';
            END IF;
            IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                RAISE EXCEPTION 'proposal draft started_at is written once';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF OLD.status = 'superseded' THEN
                    RAISE EXCEPTION 'a superseded proposal draft cannot change status';
                END IF;
                IF NEW.status = 'queued' THEN
                    RAISE EXCEPTION 'a proposal draft cannot return to queued';
                END IF;
                -- RL-04 STEP-005 state machine: queued -> running (first claim);
                -- running -> completed|partial|failed; a settled draft is re-settled
                -- among completed|partial|failed after a section regeneration;
                -- any unsettled or settled draft -> superseded (web only).
                IF NOT (
                    NEW.status = 'superseded'
                    OR (OLD.status = 'queued' AND NEW.status = 'running')
                    OR (OLD.status IN ('running', 'completed', 'partial', 'failed')
                        AND NEW.status IN ('completed', 'partial', 'failed'))
                ) THEN
                    RAISE EXCEPTION 'invalid proposal draft status transition % -> %',
                        OLD.status, NEW.status;
                END IF;
                IF current_user = 'app' AND NEW.status <> 'superseded' THEN
                    RAISE EXCEPTION 'the web role may only supersede a proposal draft';
                END IF;
                IF current_user = 'worker' AND NEW.status = 'superseded' THEN
                    RAISE EXCEPTION 'the worker cannot supersede a proposal draft';
                END IF;
            END IF;
            IF NEW.stage IS DISTINCT FROM OLD.stage THEN
                IF NOT (
                    (OLD.stage = 'toc' AND NEW.stage = 'draft')
                    OR (OLD.stage = 'draft' AND NEW.stage = 'reviewed')
                    OR (OLD.stage = 'reviewed' AND NEW.stage = 'ready')
                ) THEN
                    RAISE EXCEPTION 'invalid proposal draft stage transition % -> %',
                        OLD.stage, NEW.stage;
                END IF;
                IF current_user = 'app' AND OLD.stage = 'toc' THEN
                    RAISE EXCEPTION 'the web role cannot advance a proposal draft from toc';
                END IF;
                IF current_user = 'worker' AND OLD.stage <> 'toc' THEN
                    RAISE EXCEPTION 'the worker may only advance a proposal draft from toc';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_proposal_draft_guard
        BEFORE INSERT OR UPDATE OR DELETE ON {SCHEMA}.proposal_draft
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_proposal_draft_guard();

        CREATE FUNCTION {SCHEMA}.tf_proposal_section_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'proposal sections are never deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF current_user = 'app' AND (
                    NEW.status <> 'queued'
                    OR NEW.input_sha256 IS NOT NULL OR NEW.result_sha256 IS NOT NULL
                    OR NEW.payload IS NOT NULL OR NEW.error_code IS NOT NULL
                    OR NEW.prompt_tokens IS NOT NULL OR NEW.output_tokens IS NOT NULL
                    OR NEW.latency_ms IS NOT NULL OR NEW.completed_at IS NOT NULL
                    OR NEW.reviewed_by IS NOT NULL OR NEW.reviewed_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'a proposal section is created as an empty queued row';
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.id, NEW.draft_id, NEW.section_key, NEW.revision, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.draft_id, OLD.section_key, OLD.revision, OLD.created_at) THEN
                RAISE EXCEPTION 'proposal section identity is immutable';
            END IF;
            IF (OLD.input_sha256 IS NOT NULL AND NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256)
               OR (OLD.result_sha256 IS NOT NULL AND NEW.result_sha256 IS DISTINCT FROM OLD.result_sha256)
               OR (OLD.payload IS NOT NULL AND NEW.payload IS DISTINCT FROM OLD.payload)
               OR (OLD.error_code IS NOT NULL AND NEW.error_code IS DISTINCT FROM OLD.error_code)
               OR (OLD.prompt_tokens IS NOT NULL AND NEW.prompt_tokens IS DISTINCT FROM OLD.prompt_tokens)
               OR (OLD.output_tokens IS NOT NULL AND NEW.output_tokens IS DISTINCT FROM OLD.output_tokens)
               OR (OLD.latency_ms IS NOT NULL AND NEW.latency_ms IS DISTINCT FROM OLD.latency_ms)
               OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
               OR (OLD.reviewed_by IS NOT NULL AND NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by)
               OR (OLD.reviewed_at IS NOT NULL AND NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at)
            THEN
                RAISE EXCEPTION 'proposal section result columns are written once';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF NOT (
                    (OLD.status = 'queued' AND NEW.status IN ('running', 'failed'))
                    OR (OLD.status = 'running' AND NEW.status IN ('completed', 'failed'))
                    OR (OLD.status = 'completed' AND NEW.status = 'reviewed')
                ) THEN
                    RAISE EXCEPTION 'invalid proposal section status transition % -> %',
                        OLD.status, NEW.status;
                END IF;
                IF current_user = 'app' AND NEW.status <> 'reviewed' THEN
                    RAISE EXCEPTION 'the web role may only review a completed proposal section';
                END IF;
                IF current_user = 'worker' AND NEW.status = 'reviewed' THEN
                    RAISE EXCEPTION 'the worker cannot review a proposal section';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_proposal_section_guard
        BEFORE INSERT OR UPDATE OR DELETE ON {SCHEMA}.proposal_section
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_proposal_section_guard();

        CREATE FUNCTION {SCHEMA}.tf_proposal_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME;
        END;
        $$;
        CREATE TRIGGER tr_proposal_sentence_edit_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.proposal_sentence_edit
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_proposal_append_only();
        CREATE TRIGGER tr_proposal_export_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.proposal_export
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.tf_proposal_append_only();
        """
    )
    _record_migration_marker()


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{table})")):
            raise RuntimeError(f"0041 downgrade refuses to discard {table} rows")

    op.drop_table("proposal_export", schema=SCHEMA)
    op.drop_index(
        "ix_proposal_sentence_edit_sentence", table_name="proposal_sentence_edit", schema=SCHEMA
    )
    op.drop_table("proposal_sentence_edit", schema=SCHEMA)
    op.drop_table("proposal_section", schema=SCHEMA)
    op.drop_index("ix_proposal_draft_opportunity", table_name="proposal_draft", schema=SCHEMA)
    op.drop_table("proposal_draft", schema=SCHEMA)
    op.execute(f"DROP FUNCTION {SCHEMA}.tf_proposal_append_only()")
    op.execute(f"DROP FUNCTION {SCHEMA}.tf_proposal_section_guard()")
    op.execute(f"DROP FUNCTION {SCHEMA}.tf_proposal_draft_guard()")
    bind.execute(
        sa.text(f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id=:event_id"),
        {"event_id": _MIGRATION_EVENT_ID},
    )
