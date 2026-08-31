"""PostgreSQL-only T-23 phase-2 lifecycle and result guards."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.postgres import migrated_engine, requires_postgres
from tests.test_prespec_overview_postgres import _seed_lineage


pytestmark = requires_postgres


def _seed_phase2_attempt(engine):  # type: ignore[no-untyped-def]
    notice_id, review_id, old_snapshot_id = _seed_lineage(engine)
    snapshot_id = uuid4()
    now = datetime(2026, 8, 31, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_overview_snapshot "
                "(id, review_id, notice_id, document_version_id, structure_id, "
                " source_sha256, payload_sha256, cut_status, strategy, "
                " start_locator, end_locator, input_block_keys, created_at) "
                "SELECT :id, review_id, notice_id, document_version_id, structure_id, "
                " source_sha256, :payload_sha256, 'ready', 'topic_heading', "
                " jsonb_build_object('block_key','start','page',1,'ordinal',0), "
                " jsonb_build_object('block_key','end','page',1,'ordinal',1), "
                " jsonb_build_array('start'), :created_at "
                "FROM bidops.prespec_overview_snapshot WHERE id = :old_snapshot"
            ),
            {
                "id": snapshot_id,
                "payload_sha256": "c" * 64,
                "created_at": now,
                "old_snapshot": old_snapshot_id,
            },
        )
        connection.execute(
            text(
                "UPDATE bidops.prespec_overview_review SET current_snapshot_id = :snapshot_id "
                "WHERE id = :review_id"
            ),
            {"snapshot_id": snapshot_id, "review_id": review_id},
        )
    attempt_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_overview_attempt "
                "(id, review_id, snapshot_id, sequence, status, reference_only, deployable, "
                " input_sha256, provider, model_name, model_digest, prompt_version, binding_digest, created_at) "
                "VALUES (:id, :review_id, :snapshot_id, 1, 'queued', true, false, "
                " :input_sha256, 'test-fake', 'test-model', :model_digest, 'prompt-v1', "
                " :binding_digest, :created_at)"
            ),
            {
                "id": attempt_id,
                "review_id": review_id,
                "snapshot_id": snapshot_id,
                "input_sha256": "d" * 64,
                "model_digest": "e" * 64,
                "binding_digest": "f" * 64,
                "created_at": now,
            },
        )
    return attempt_id, review_id, snapshot_id


def test_phase2_requires_audited_transition_and_keeps_rows_immutable() -> None:
    with migrated_engine() as engine:
        attempt_id, review_id, snapshot_id = _seed_phase2_attempt(engine)
        now = datetime(2026, 8, 31, 0, 1, tzinfo=UTC)
        event_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.prespec_overview_attempt_event "
                    "(id, attempt_id, event_sequence, from_status, to_status, occurred_at, "
                    " actor_kind, actor_id, reason_code) VALUES "
                    "(:id, :attempt_id, 1, 'queued', 'running', :occurred_at, 'worker', "
                    " 'worker-1', 'started')"
                ),
                {"id": event_id, "attempt_id": attempt_id, "occurred_at": now},
            )
            connection.execute(
                text(
                    "UPDATE bidops.prespec_overview_attempt SET status = 'running', started_at = :started_at "
                    "WHERE id = :attempt_id"
                ),
                {"attempt_id": attempt_id, "started_at": now},
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_attempt SET provider = 'tampered' "
                        "WHERE id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id},
                )

        result_id = uuid4()
        payload = {
            "schema_version": "bidops.prespec-overview-result.v1",
            "recommendation": "추진 검토",
            "summary": "검증된 결과",
            "conditions": [],
            "verification_due_at": None,
            "unknowns": [],
            "evidence": [],
            "input_limitations": [],
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bidops.prespec_overview_result "
                    "(id, attempt_id, review_id, snapshot_id, schema_version, payload_jsonb, "
                    " payload_sha256, source_sha256, binding_digest, validation_status, created_at) "
                    "VALUES (:id, :attempt_id, :review_id, :snapshot_id, "
                    " 'bidops.prespec-overview-result.v1', CAST(:payload AS jsonb), :payload_sha256, "
                    " 'a' || repeat('a', 63), 'f' || repeat('f', 63), 'passed', :created_at)"
                ),
                {
                    "id": result_id,
                    "attempt_id": attempt_id,
                    "review_id": review_id,
                    "snapshot_id": snapshot_id,
                    "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "payload_sha256": "1" * 64,
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO bidops.prespec_overview_attempt_event "
                    "(id, attempt_id, event_sequence, from_status, to_status, occurred_at, "
                    " actor_kind, actor_id, reason_code) VALUES "
                    "(:id, :attempt_id, 2, 'running', 'completed', :occurred_at, 'worker', "
                    " 'worker-1', 'completed')"
                ),
                {"id": uuid4(), "attempt_id": attempt_id, "occurred_at": now},
            )
            connection.execute(
                text(
                    "UPDATE bidops.prespec_overview_attempt SET status = 'completed', "
                    " completed_at = :completed_at, result_id = :result_id WHERE id = :attempt_id"
                ),
                {"attempt_id": attempt_id, "result_id": result_id, "completed_at": now},
            )

        for table, row_id in (
            ("prespec_overview_result", result_id),
            ("prespec_overview_attempt_event", event_id),
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(f"UPDATE bidops.{table} SET id = id WHERE id = :id"),
                        {"id": row_id},
                    )
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(f"DELETE FROM bidops.{table} WHERE id = :id"),
                        {"id": row_id},
                    )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.prespec_overview_attempt_event "
                        "(id, attempt_id, event_sequence, from_status, to_status, actor_kind, "
                        "actor_id, reason_code) VALUES (:id, :attempt_id, 3, 'completed', "
                        "'queued', 'worker', 'worker-1', 'reverse')"
                    ),
                    {"id": uuid4(), "attempt_id": attempt_id},
                )


def test_phase2_result_scope_is_fail_closed() -> None:
    with migrated_engine() as engine:
        attempt_id, review_id, snapshot_id = _seed_phase2_attempt(engine)
        wrong_result_id = uuid4()
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO bidops.prespec_overview_result "
                        "(id, attempt_id, review_id, snapshot_id, schema_version, payload_jsonb, "
                        " payload_sha256, source_sha256, binding_digest, validation_status) VALUES "
                        "(:id, :attempt_id, :review_id, :snapshot_id, 'bidops.prespec-overview-result.v1', "
                        " '{}'::jsonb, :payload_sha256, :source_sha256, :binding_digest, 'passed')"
                    ),
                    {
                        "id": wrong_result_id,
                        "attempt_id": attempt_id,
                        "review_id": review_id,
                        "snapshot_id": snapshot_id,
                        "payload_sha256": "1" * 64,
                        "source_sha256": "9" * 64,
                        "binding_digest": "f" * 64,
                    },
                )
