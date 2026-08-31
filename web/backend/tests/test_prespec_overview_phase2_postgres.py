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


def _seed_phase2_attempt(
    engine, *, reference_only: bool = False, deployable: bool = True
):  # type: ignore[no-untyped-def]
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
                "VALUES (:id, :review_id, :snapshot_id, 1, 'queued', :reference_only, :deployable, "
                " :input_sha256, 'test-fake', 'test-model', :model_digest, 'prompt-v1', "
                " :binding_digest, :created_at)"
            ),
            {
                "id": attempt_id,
                "review_id": review_id,
                "snapshot_id": snapshot_id,
                "reference_only": reference_only,
                "deployable": deployable,
                "input_sha256": "d" * 64,
                "model_digest": "e" * 64,
                "binding_digest": "f" * 64,
                "created_at": now,
            },
        )
    return attempt_id, review_id, snapshot_id


def _start_phase2_attempt(engine, attempt_id, *, now):  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE bidops.prespec_overview_attempt SET status = 'running', "
                " started_at = :started_at WHERE id = :attempt_id"
            ),
            {"attempt_id": attempt_id, "started_at": now},
        )


def _valid_result_payload(*, evidence: list | None = None) -> str:
    return json.dumps(
        {
            "schema_version": "bidops.prespec-overview-result.v1",
            "recommendation": "추진 검토",
            "summary": "검증된 결과",
            "conditions": [],
            "verification_due_at": None,
            "unknowns": [],
            "evidence": evidence
            if evidence is not None
            else [
                {
                    "claim": "사업개요 경계",
                    "locator": {"block_key": "start", "page": 1, "ordinal": 0},
                }
            ],
            "input_limitations": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _insert_result(
    engine,
    *,
    attempt_id,
    review_id,
    snapshot_id,
    result_id=None,
    payload=None,
    created_at=None,
):  # type: ignore[no-untyped-def]
    result_id = result_id or uuid4()
    created_at = created_at or datetime(2026, 8, 31, 0, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO bidops.prespec_overview_result "
                "(id, attempt_id, review_id, snapshot_id, schema_version, payload_jsonb, "
                " payload_sha256, source_sha256, binding_digest, validation_status, created_at) "
                "VALUES (:id, :attempt_id, :review_id, :snapshot_id, "
                " 'bidops.prespec-overview-result.v1', CAST(:payload AS jsonb), "
                " :payload_sha256, :source_sha256, :binding_digest, 'passed', :created_at)"
            ),
            {
                "id": result_id,
                "attempt_id": attempt_id,
                "review_id": review_id,
                "snapshot_id": snapshot_id,
                "payload": payload or _valid_result_payload(),
                "payload_sha256": "1" * 64,
                "source_sha256": "a" * 64,
                "binding_digest": "f" * 64,
                "created_at": created_at,
            },
        )
    return result_id


def test_postgres_direct_attempt_transitions_require_no_event_but_reject_invalid_edges() -> None:
    with migrated_engine() as engine:
        attempt_id, _review_id, _snapshot_id = _seed_phase2_attempt(engine)
        started_at = datetime(2026, 8, 31, 0, 1, tzinfo=UTC)
        finished_at = datetime(2026, 8, 31, 0, 2, tzinfo=UTC)
        # The status trigger checks only the lifecycle edge.  A direct valid
        # update is therefore independent of an event row; the service adds
        # both rows in one transaction when handling real work.
        _start_phase2_attempt(engine, attempt_id, now=started_at)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_attempt SET status = 'queued' "
                        "WHERE id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id},
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bidops.prespec_overview_attempt SET status = 'failed', "
                    " completed_at = :completed_at WHERE id = :attempt_id"
                ),
                {"attempt_id": attempt_id, "completed_at": finished_at},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_attempt SET status = 'running', "
                        " started_at = :started_at WHERE id = :attempt_id"
                    ),
                    {"attempt_id": attempt_id, "started_at": finished_at},
                )
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT status FROM bidops.prespec_overview_attempt WHERE id = :id"),
                {"id": attempt_id},
            ) == "failed"
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM bidops.prespec_overview_attempt_event "
                    "WHERE attempt_id = :attempt_id"
                ),
                {"attempt_id": attempt_id},
            ) == 0


def test_postgres_attempt_constraints_keep_binding_and_result_evidence_strict() -> None:
    with migrated_engine() as engine:
        attempt_id, review_id, snapshot_id = _seed_phase2_attempt(
            engine, reference_only=True, deployable=False
        )
        now = datetime(2026, 8, 31, 0, 1, tzinfo=UTC)
        _start_phase2_attempt(engine, attempt_id, now=now)
        result_id = _insert_result(
            engine,
            attempt_id=attempt_id,
            review_id=review_id,
            snapshot_id=snapshot_id,
            created_at=now,
        )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bidops.prespec_overview_attempt SET status = 'completed', "
                        " completed_at = :completed_at, result_id = :result_id "
                        "WHERE id = :attempt_id"
                    ),
                    {
                        "attempt_id": attempt_id,
                        "result_id": result_id,
                        "completed_at": now,
                    },
                )
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM bidops.prespec_overview_result "
                    "WHERE attempt_id = :attempt_id"
                ),
                {"attempt_id": attempt_id},
            ) == 1

    with migrated_engine() as engine:
        second_id, second_review_id, second_snapshot_id = _seed_phase2_attempt(engine)
        _start_phase2_attempt(engine, second_id, now=now)
        with pytest.raises(IntegrityError):
            _insert_result(
                engine,
                attempt_id=second_id,
                review_id=second_review_id,
                snapshot_id=second_snapshot_id,
                payload=_valid_result_payload(evidence=[]),
                created_at=now,
            )
