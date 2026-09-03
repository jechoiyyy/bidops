"""PostgreSQL-only T-23 structural constraints.

The service/cutter tests use isolated SQLite because they do not claim to
exercise PostgreSQL DDL.  These opt-in checks cover the canonical database
constraints when ``BIDOPS_TEST_POSTGRES_URL`` is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.postgres import migrated_engine, requires_postgres


pytestmark = requires_postgres


def _seed_lineage(engine):  # type: ignore[no-untyped-def]
    notice_id = None
    review_id = uuid4()
    snapshot_id = uuid4()
    document_id = uuid4()
    structure_id = uuid4()
    source_id = uuid4()
    payload_id = uuid4()
    now = datetime(2026, 8, 31, tzinfo=UTC)
    with engine.begin() as connection:
        notice_id = connection.scalar(
            text(
                "INSERT INTO bidops.notice (notice_key, source_type) "
                "VALUES (:notice_key, 'pre_spec') RETURNING id"
            ),
            {"notice_key": f"t23-pg-{uuid4()}"},
        )
        for content_id, digest, mime, retention in (
            (source_id, "a" * 64, "application/pdf", "document-source"),
            (payload_id, "b" * 64, "application/json", "document-structure"),
        ):
            connection.execute(
                text(
                    "INSERT INTO bidops.content_object "
                    "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
                    "VALUES (:id, :sha256, 1, :mime, :retention, :created_at)"
                ),
                {
                    "id": content_id,
                    "sha256": digest,
                    "mime": mime,
                    "retention": retention,
                    "created_at": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO bidops.document_version "
                "(id, notice_id, content_object_id, version, source_kind, source_system, "
                "source_attachment_key, original_filename, role, is_current, safety_status, "
                "needs_human_review, created_at) "
                "VALUES (:id, :notice_id, :content_id, 1, 'provider', 'g2b', 't23-pg', "
                "'t23.pdf', '제안요청서', true, 'safe', false, :created_at)"
            ),
            {
                "id": document_id,
                "notice_id": notice_id,
                "content_id": source_id,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO bidops.document_structure "
                "(id, document_version_id, source_sha256, media_type, extractor_name, "
                "extractor_version, payload_content_object_id, payload_sha256, page_count, "
                "block_count, validation_status, created_at) "
                "VALUES (:id, :document_id, :source_sha256, 'application/pdf', 'test', '1', "
                ":payload_id, :payload_sha256, 1, 0, 'ready', :created_at)"
            ),
            {
                "id": structure_id,
                "document_id": document_id,
                "source_sha256": "a" * 64,
                "payload_id": payload_id,
                "payload_sha256": "b" * 64,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_overview_review "
                "(id, notice_id, status, created_at, updated_at) "
                "VALUES (:id, :notice_id, 'awaiting_model', :created_at, :created_at)"
            ),
            {"id": review_id, "notice_id": notice_id, "created_at": now},
        )
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_overview_snapshot "
                "(id, review_id, notice_id, document_version_id, structure_id, source_sha256, "
                "payload_sha256, cut_status, unknown_reason_code, created_at) "
                "VALUES (:id, :review_id, :notice_id, :document_id, :structure_id, :source_sha256, "
                ":payload_sha256, 'unknown', 'no_topic_heading', :created_at)"
            ),
            {
                "id": snapshot_id,
                "review_id": review_id,
                "notice_id": notice_id,
                "document_id": document_id,
                "structure_id": structure_id,
                "source_sha256": "a" * 64,
                "payload_sha256": "b" * 64,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "UPDATE bidops.prespec_overview_review "
                "SET current_snapshot_id = :snapshot_id WHERE id = :review_id"
            ),
            {"snapshot_id": snapshot_id, "review_id": review_id},
        )
    return notice_id, review_id, snapshot_id


def test_t23_postgres_structural_constraints() -> None:
    with migrated_engine() as engine:
        _notice_id, review_id, snapshot_id = _seed_lineage(engine)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_review "
                        "SET status = 'completed' WHERE id = :review_id"
                    ),
                    {"review_id": review_id},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_snapshot "
                        "SET cut_status = 'failed' WHERE id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )

        attempt_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.prespec_overview_attempt "
                    "(id, snapshot_id, sequence, status, reference_only, deployable, created_at) "
                    "VALUES (:id, :snapshot_id, 1, 'queued', true, false, :created_at)"
                ),
                {
                    "id": attempt_id,
                    "snapshot_id": snapshot_id,
                    "created_at": datetime(2026, 8, 31, tzinfo=UTC),
                },
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_attempt "
                        "SET status = 'running' WHERE id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.prespec_overview_attempt "
                        "(id, snapshot_id, sequence, status, reference_only, deployable, created_at) "
                        "VALUES (:id, :snapshot_id, 2, 'queued', true, true, :created_at)"
                    ),
                    {
                        "id": uuid4(),
                        "snapshot_id": snapshot_id,
                        "created_at": datetime(2026, 8, 31, tzinfo=UTC),
                    },
                )


def test_t23_postgres_snapshot_scope_rejects_cross_notice_and_cross_lineage() -> None:
    with migrated_engine() as engine:
        notice_id, review_id, snapshot_id = _seed_lineage(engine)

        with engine.begin() as connection:
            other_notice_id = connection.scalar(
                text(
                    "INSERT INTO bidops.notice (notice_key, source_type) "
                    "VALUES (:notice_key, 'pre_spec') RETURNING id"
                ),
                {"notice_key": f"t23-pg-other-{uuid4()}"},
            )

        # The review belongs to the original notice.  A valid row otherwise
        # must not be able to smuggle a different notice scope into a snapshot.
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.prespec_overview_snapshot "
                        "(id, review_id, notice_id, document_version_id, structure_id, "
                        " source_sha256, payload_sha256, cut_status, unknown_reason_code) "
                        "SELECT :id, :review_id, :other_notice_id, document_version_id, "
                        " structure_id, source_sha256, payload_sha256, 'unknown', "
                        " 'cross_notice' FROM bidops.prespec_overview_snapshot "
                        "WHERE id = :snapshot_id"
                    ),
                    {
                        "id": uuid4(),
                        "review_id": review_id,
                        "other_notice_id": other_notice_id,
                        "snapshot_id": snapshot_id,
                    },
                )

        # The notice/review scope and document scope remain valid, but the
        # structure belongs to a different document version.  This verifies
        # that the second composite FK closes the service-only lineage gap.
        other_document_id = uuid4()
        other_structure_id = uuid4()
        other_source_id = uuid4()
        other_payload_id = uuid4()
        now = datetime(2026, 8, 31, tzinfo=UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.content_object "
                    "(id, sha256, size_bytes, detected_mime, retention_class, created_at) "
                    "VALUES (:id, :sha256, 1, :mime, :retention, :created_at), "
                    "       (:payload_id, :payload_sha256, 1, 'application/json', "
                    "        'document-structure', :created_at)"
                ),
                {
                    "id": other_source_id,
                    "sha256": "c" * 64,
                    "payload_id": other_payload_id,
                    "payload_sha256": "d" * 64,
                    "mime": "application/pdf",
                    "retention": "document-source",
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_version "
                    "(id, notice_id, content_object_id, version, source_kind, source_system, "
                    "source_attachment_key, original_filename, role, is_current, safety_status, "
                    "needs_human_review, created_at) VALUES "
                    "(:id, :notice_id, :content_id, 1, 'provider', 'g2b', 'other', "
                    "'other.pdf', '기타', true, 'safe', false, :created_at)"
                ),
                {
                    "id": other_document_id,
                    "notice_id": notice_id,
                    "content_id": other_source_id,
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.document_structure "
                    "(id, document_version_id, source_sha256, media_type, extractor_name, "
                    "extractor_version, payload_content_object_id, payload_sha256, page_count, "
                    "block_count, validation_status, created_at) VALUES "
                    "(:id, :document_id, :source_sha256, 'application/pdf', 'test', '1', "
                    ":payload_id, :payload_sha256, 1, 0, 'ready', :created_at)"
                ),
                {
                    "id": other_structure_id,
                    "document_id": other_document_id,
                    "source_sha256": "c" * 64,
                    "payload_id": other_payload_id,
                    "payload_sha256": "d" * 64,
                    "created_at": now,
                },
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.prespec_overview_snapshot "
                        "(id, review_id, notice_id, document_version_id, structure_id, "
                        " source_sha256, payload_sha256, cut_status, unknown_reason_code) "
                        "SELECT :id, review_id, notice_id, document_version_id, :other_structure_id, "
                        " source_sha256, payload_sha256, 'unknown', 'cross_lineage' "
                        "FROM bidops.prespec_overview_snapshot WHERE id = :snapshot_id"
                    ),
                    {
                        "id": uuid4(),
                        "other_structure_id": other_structure_id,
                        "snapshot_id": snapshot_id,
                    },
                )
