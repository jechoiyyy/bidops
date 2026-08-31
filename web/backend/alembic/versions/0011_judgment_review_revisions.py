"""Add immutable judgment and human-review revision history.

Revision ID: 0011_judgment_review_revisions
Revises: 0010_opportunity_link_integrity

The legacy projection rows remain in place.  This revision first rejects any
review whose stated run did not observe the same notice, then captures one
ID-free sequence-1 snapshot for every existing judgment and review.  Missing
execution, parent, judgment alignment, and original judgment time are not
inferred.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_judgment_review_revisions"
down_revision = "0010_opportunity_link_integrity"
branch_labels = None
depends_on = None

SCHEMA = "bidops"
_MIGRATION_EVENT_ID = "audit-5d8f2a1c7e4b4096a3f1d2c8b76509ea"
JUDGMENT_PAYLOAD_SCHEMA = "bidops.judgment-revision-payload.v1"
REVIEW_PAYLOAD_SCHEMA = "bidops.review-revision-payload.v1"


def _preflight_review_observation_provenance() -> None:
    rows = op.get_bind().execute(
        sa.text(
            f"""
            SELECT review.id, review.notice_id, review.run_id
            FROM {SCHEMA}.review AS review
            LEFT JOIN {SCHEMA}.notice_observation AS observation
              ON observation.notice_id = review.notice_id
             AND observation.run_id = review.run_id
            WHERE review.run_id IS NOT NULL
              AND observation.id IS NULL
            ORDER BY review.id
            LIMIT 50
            """
        )
    ).all()
    if rows:
        detail = "; ".join(
            f"review_id={row.id} notice_id={row.notice_id} run_id={row.run_id!r}"
            for row in rows
        )
        raise RuntimeError(
            "0011 upgrade found review run provenance that did not observe the same "
            "notice; reconcile these rows without guessing, then retry: " + detail
        )


def _create_tables() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "judgment_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=True),
        sa.Column("recording_execution_id", sa.String(length=36), nullable=True),
        sa.Column("source_revision_id", sa.Integer(), nullable=True),
        sa.Column("payload_schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload_jsonb", jsonb, nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_judgment_revision_sequence"),
        sa.CheckConstraint(
            "source_kind IN ('runtime', 'legacy_import', 'carry_over')",
            name="ck_judgment_revision_source_kind",
        ),
        sa.CheckConstraint(
            "((source_kind = 'runtime' AND run_id IS NOT NULL "
            "AND recording_execution_id IS NOT NULL AND source_revision_id IS NULL) OR "
            "(source_kind = 'carry_over' AND run_id IS NOT NULL "
            "AND recording_execution_id IS NOT NULL AND source_revision_id IS NOT NULL) OR "
            "(source_kind = 'legacy_import' AND recording_execution_id IS NULL "
            "AND source_revision_id IS NULL))",
            name="ck_judgment_revision_source_lineage",
        ),
        sa.CheckConstraint(
            "source_revision_id IS NULL OR source_revision_id <> id",
            name="ck_judgment_revision_parent_not_self",
        ),
        sa.CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_judgment_revision_payload_schema_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_jsonb) = 'object'",
            name="ck_judgment_revision_payload_object",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_judgment_revision_payload_sha256",
        ),
        sa.UniqueConstraint(
            "notice_id", "sequence", name="uq_judgment_revision_notice_sequence"
        ),
        sa.UniqueConstraint(
            "notice_id", "id", name="uq_judgment_revision_notice_id"
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_judgment_revision_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "run_id"],
            [
                f"{SCHEMA}.notice_observation.notice_id",
                f"{SCHEMA}.notice_observation.run_id",
            ],
            name="fk_judgment_revision_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recording_execution_id"],
            [f"{SCHEMA}.screening_execution.execution_id"],
            name="fk_judgment_revision_execution",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "source_revision_id"],
            [
                f"{SCHEMA}.judgment_revision.notice_id",
                f"{SCHEMA}.judgment_revision.id",
            ],
            name="fk_judgment_revision_parent_scope",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_judgment_revision_execution_notice",
        "judgment_revision",
        ["recording_execution_id", "notice_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("recording_execution_id IS NOT NULL"),
    )

    op.create_table(
        "review_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=True),
        sa.Column("judgment_revision_id", sa.Integer(), nullable=True),
        sa.Column("payload_schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload_jsonb", jsonb, nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_review_revision_sequence"),
        sa.CheckConstraint(
            "source_kind IN ('human', 'legacy_import')",
            name="ck_review_revision_source_kind",
        ),
        sa.CheckConstraint(
            "source_kind <> 'human' OR run_id IS NOT NULL",
            name="ck_review_revision_human_run",
        ),
        sa.CheckConstraint(
            "length(trim(payload_schema_version)) > 0",
            name="ck_review_revision_payload_schema_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_jsonb) = 'object'",
            name="ck_review_revision_payload_object",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_review_revision_payload_sha256",
        ),
        sa.UniqueConstraint(
            "notice_id", "sequence", name="uq_review_revision_notice_sequence"
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            [f"{SCHEMA}.notice.id"],
            name="fk_review_revision_notice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "run_id"],
            [
                f"{SCHEMA}.notice_observation.notice_id",
                f"{SCHEMA}.notice_observation.run_id",
            ],
            name="fk_review_revision_observation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "judgment_revision_id"],
            [
                f"{SCHEMA}.judgment_revision.notice_id",
                f"{SCHEMA}.judgment_revision.id",
            ],
            name="fk_review_revision_judgment_scope",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )


def _create_canonical_json_function() -> None:
    op.get_bind().exec_driver_sql(
        f"""
CREATE FUNCTION {SCHEMA}.revision_canonical_json(value jsonb)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $function$
DECLARE
    rendered text;
BEGIN
    CASE jsonb_typeof(value)
    WHEN 'object' THEN
        SELECT '{{' || COALESCE(
            string_agg(
                to_jsonb(entry.key)::text || ':' ||
                {SCHEMA}.revision_canonical_json(entry.value),
                ',' ORDER BY entry.key COLLATE "C"
            ), ''
        ) || '}}'
        INTO rendered
        FROM jsonb_each(value) AS entry;
    WHEN 'array' THEN
        SELECT '[' || COALESCE(
            string_agg(
                {SCHEMA}.revision_canonical_json(element.value),
                ',' ORDER BY element.ordinality
            ), ''
        ) || ']'
        INTO rendered
        FROM jsonb_array_elements(value) WITH ORDINALITY AS element(value, ordinality);
    ELSE
        rendered := value::text;
    END CASE;
    RETURN rendered;
END
$function$;
"""
    )


def _backfill_judgments() -> None:
    op.execute(
        sa.text(
            f"""
            WITH payloads AS (
                SELECT
                    judgment.notice_id,
                    jsonb_build_object(
                        'schema_version', judgment.schema_version,
                        'grade', judgment.grade,
                        'readiness', judgment.readiness,
                        'primary_focus', judgment.primary_focus,
                        'exclusion_category', judgment.exclusion_category,
                        'summary', judgment.summary,
                        'next_action', judgment.next_action,
                        'perspectives', COALESCE((
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'position', perspective.position,
                                    'name', perspective.name,
                                    'assessment', perspective.assessment,
                                    'reason', perspective.reason,
                                    'evidence', COALESCE((
                                        SELECT jsonb_agg(
                                            jsonb_build_object(
                                                'source', evidence.source,
                                                'status', evidence.status,
                                                'fact', evidence.fact
                                            ) ORDER BY evidence.id
                                        )
                                        FROM {SCHEMA}.screening_evidence AS evidence
                                        WHERE evidence.perspective_id = perspective.id
                                    ), '[]'::jsonb)
                                ) ORDER BY perspective.position NULLS LAST, perspective.id
                            )
                            FROM {SCHEMA}.perspective AS perspective
                            WHERE perspective.judgment_id = judgment.id
                        ), '[]'::jsonb),
                        'counterarguments', COALESCE((
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'position', counterargument.position,
                                    'text', counterargument.body
                                ) ORDER BY counterargument.position NULLS LAST, counterargument.id
                            )
                            FROM {SCHEMA}.counterargument AS counterargument
                            WHERE counterargument.judgment_id = judgment.id
                        ), '[]'::jsonb),
                        'counterargument_resolutions', NULL,
                        'verification_items', COALESCE((
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'item', verification_item.item,
                                    'why', verification_item.why,
                                    'blocking', verification_item.blocking,
                                    'status', verification_item.status
                                ) ORDER BY verification_item.id
                            )
                            FROM {SCHEMA}.verification_item AS verification_item
                            WHERE verification_item.judgment_id = judgment.id
                        ), '[]'::jsonb),
                        'matched_performances', COALESCE((
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'name', matched.name,
                                    'match_reason', matched.match_reason,
                                    'mismatch_or_limit', matched.mismatch_or_limit,
                                    'source', matched.source,
                                    'status', matched.status
                                ) ORDER BY matched.id
                            )
                            FROM {SCHEMA}.matched_performance AS matched
                            WHERE matched.judgment_id = judgment.id
                        ), '[]'::jsonb)
                    ) AS payload
                FROM {SCHEMA}.judgment AS judgment
            )
            INSERT INTO {SCHEMA}.judgment_revision
                (notice_id, sequence, source_kind, run_id,
                 recording_execution_id, source_revision_id,
                 payload_schema_version, payload_jsonb, payload_sha256, captured_at)
            SELECT
                payloads.notice_id,
                1,
                'legacy_import',
                NULL,
                NULL,
                NULL,
                :payload_schema_version,
                payloads.payload,
                encode(
                    sha256(convert_to(
                        {SCHEMA}.revision_canonical_json(payloads.payload), 'UTF8'
                    )),
                    'hex'
                ),
                CURRENT_TIMESTAMP
            FROM payloads
            """
        ).bindparams(payload_schema_version=JUDGMENT_PAYLOAD_SCHEMA)
    )


def _backfill_reviews() -> None:
    op.execute(
        sa.text(
            f"""
            WITH payloads AS (
                SELECT
                    review.notice_id,
                    review.run_id,
                    review.updated_at,
                    jsonb_build_object(
                        'disposition', review.disposition,
                        'system_judgment_review', review.system_judgment_review,
                        'corrected_grade', review.corrected_grade,
                        'corrected_readiness', review.corrected_readiness,
                        'weakest_perspective', review.weakest_perspective,
                        'reason', review.reason,
                        'reviewer', review.reviewer_snapshot,
                        'verification_answers', COALESCE((
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'item', answer.item,
                                    'answer', answer.answer
                                ) ORDER BY answer.id
                            )
                            FROM {SCHEMA}.verification_answer AS answer
                            WHERE answer.review_id = review.id
                        ), '[]'::jsonb)
                    ) AS payload
                FROM {SCHEMA}.review AS review
            )
            INSERT INTO {SCHEMA}.review_revision
                (notice_id, sequence, source_kind, run_id,
                 judgment_revision_id, payload_schema_version,
                 payload_jsonb, payload_sha256, captured_at)
            SELECT
                payloads.notice_id,
                1,
                'legacy_import',
                payloads.run_id,
                NULL,
                :payload_schema_version,
                payloads.payload,
                encode(
                    sha256(convert_to(
                        {SCHEMA}.revision_canonical_json(payloads.payload), 'UTF8'
                    )),
                    'hex'
                ),
                payloads.updated_at
            FROM payloads
            """
        ).bindparams(payload_schema_version=REVIEW_PAYLOAD_SCHEMA)
    )


def _create_append_only_guards() -> None:
    for table in ("judgment_revision", "review_revision"):
        function = f"tf_{table}_append_only"
        trigger = f"tr_{table}_append_only"
        op.get_bind().exec_driver_sql(
            f"""
CREATE FUNCTION {SCHEMA}.{function}() RETURNS trigger
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION '{table} is append-only'
        USING ERRCODE = 'check_violation';
END
$function$;
"""
        )
        op.get_bind().exec_driver_sql(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE "
            f"ON {SCHEMA}.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION {SCHEMA}.{function}();"
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
            "occurred_at": "2026-01-01 00:00:08+00",
            "details": (
                '{"migration_revision":"0011_judgment_review_revisions",'
                '"action":"upgrade"}'
            ),
        },
    )


def upgrade() -> None:
    _preflight_review_observation_provenance()
    _create_tables()
    _create_canonical_json_function()
    _backfill_judgments()
    _backfill_reviews()
    op.execute(sa.text(f"DROP FUNCTION {SCHEMA}.revision_canonical_json(jsonb)"))
    _create_append_only_guards()
    _record_migration_marker()


def _assert_downgrade_safe() -> None:
    counts = op.get_bind().execute(
        sa.text(
            f"""
            SELECT
                (SELECT count(*) FROM {SCHEMA}.judgment_revision),
                (SELECT count(*) FROM {SCHEMA}.review_revision)
            """
        )
    ).one()
    if counts[0] or counts[1]:
        raise RuntimeError(
            "0011 downgrade refuses to discard judgment or review revision history; "
            "export or reconcile revision rows before retrying"
        )


def downgrade() -> None:
    _assert_downgrade_safe()
    for table in ("review_revision", "judgment_revision"):
        trigger = f"tr_{table}_append_only"
        function = f"tf_{table}_append_only"
        op.execute(sa.text(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}"))
        op.execute(sa.text(f"DROP FUNCTION {SCHEMA}.{function}()"))
    op.drop_table("review_revision", schema=SCHEMA)
    op.drop_index(
        "uq_judgment_revision_execution_notice",
        table_name="judgment_revision",
        schema=SCHEMA,
    )
    op.drop_table("judgment_revision", schema=SCHEMA)
    op.get_bind().execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.screening_audit_event WHERE event_id = :event_id"
        ),
        {"event_id": _MIGRATION_EVENT_ID},
    )
