from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.lifecycle.models import Notice, NoticeObservation, Run
from app.screening.models import ScreeningExecution
from app.core.generation_config import GenerationConfig
from app.screening.services.revisions import (
    RevisionConflictError,
    RevisionValidationError,
    append_judgment_revision,
    append_review_revision,
    canonical_payload_json,
    canonical_payload_sha256,
    judgment_revision_history,
    origin_execution_for_judgment_revision,
    require_carry_origin_run,
    review_revision_history,
)


NOW = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
PROFILE_VERSION = "company-profile.sha256:" + DIGEST


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _execution(execution_id: str, run_id: str, suffix: str) -> ScreeningExecution:
    config = GenerationConfig()
    return ScreeningExecution(
        execution_id=execution_id,
        trigger="manual_run",
        source_run_id=run_id,
        scope="full_run",
        status="대기",
        requested_by="revision-test",
        policy_version="policy-revision-test",
        prompt_version="prompt-revision-test",
        model_name="qwen3.8-27B",
        model_digest=DIGEST,
        company_profile_version=PROFILE_VERSION,
        company_profile_digest=DIGEST,
        generation_config_json=config.canonical_value(),
        generation_config_digest=config.digest(),
        input_artifact_path=f"runs/{suffix}/input.json",
        input_artifact_digest=DIGEST,
        artifact_dir=f"runs/{suffix}",
        queued_at=NOW,
    )


def _seed(session: Session) -> tuple[Notice, Notice, ScreeningExecution, ScreeningExecution]:
    run = Run(id="revision-run", generated_at=NOW)
    notice = Notice(notice_key="notice:revision:one")
    other = Notice(notice_key="notice:revision:two")
    session.add_all([run, notice, other])
    session.flush()
    session.add_all(
        [
            NoticeObservation(
                notice_id=notice.id,
                run_id=run.id,
                observed_at=NOW,
                changed_fields_json=[],
            ),
            NoticeObservation(
                notice_id=other.id,
                run_id=run.id,
                observed_at=NOW,
                changed_fields_json=[],
            ),
        ]
    )
    first = _execution("scr-" + "1" * 32, run.id, "revision-first")
    second = _execution("scr-" + "2" * 32, run.id, "revision-second")
    session.add_all([first, second])
    session.flush()
    return notice, other, first, second


def test_canonical_payload_hash_is_deterministic_and_preserves_null() -> None:
    payload = {"z": None, "한글": "값", "nested": {"b": 2, "a": 1}}
    encoded = canonical_payload_json(payload)

    assert encoded == '{"nested":{"a":1,"b":2},"z":null,"한글":"값"}'
    assert canonical_payload_sha256(payload) == hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()
    assert canonical_payload_sha256(dict(reversed(list(payload.items())))) == (
        canonical_payload_sha256(payload)
    )


def test_same_execution_exact_replay_is_idempotent_and_difference_conflicts() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, _other, execution, _second = _seed(session)
        payload = {"grade": None, "verification_items": []}
        first = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=execution.execution_id,
            payload=payload,
        )
        replay = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=execution.execution_id,
            payload=dict(payload),
        )

        assert replay.id == first.id
        assert first.sequence == 1
        assert first.payload_jsonb["grade"] is None
        with pytest.raises(RevisionConflictError):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="runtime",
                run_id="revision-run",
                recording_execution_id=execution.execution_id,
                payload={"grade": "changed"},
            )


def test_observed_run_legacy_import_replay_is_idempotent_and_difference_conflicts() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, _other, _execution_row, _second = _seed(session)
        payload = {"grade": None, "unknowns": [None]}
        first = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="legacy_import",
            run_id="revision-run",
            payload=payload,
        )
        replay = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="legacy_import",
            run_id="revision-run",
            payload=dict(payload),
        )

        assert replay.id == first.id
        assert judgment_revision_history(session, notice.id) == [first]
        with pytest.raises(RevisionConflictError, match="legacy import run"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="legacy_import",
                run_id="revision-run",
                payload={"grade": "changed", "unknowns": [None]},
            )
        with pytest.raises(RevisionConflictError, match="legacy import run"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="legacy_import",
                run_id="revision-run",
                payload=payload,
                payload_schema_version="bidops.judgment-revision-payload.v2",
            )


def test_carry_over_requires_same_notice_parent_and_resolves_origin_execution() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, other, first_execution, second_execution = _seed(session)
        origin = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=first_execution.execution_id,
            payload={"grade": "우선 검토"},
        )
        other_origin = append_judgment_revision(
            session,
            notice_id=other.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=first_execution.execution_id,
            payload={"grade": None},
        )
        with pytest.raises(RevisionValidationError, match="payload and schema exactly"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="carry_over",
                run_id="revision-run",
                recording_execution_id=second_execution.execution_id,
                source_revision_id=origin.id,
                payload={"grade": "검토 권장"},
            )
        with pytest.raises(RevisionValidationError, match="payload and schema exactly"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="carry_over",
                run_id="revision-run",
                recording_execution_id=second_execution.execution_id,
                source_revision_id=origin.id,
                payload={"grade": "우선 검토"},
                payload_schema_version="bidops.judgment-revision-payload.v2",
            )
        carried = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="carry_over",
            run_id="revision-run",
            recording_execution_id=second_execution.execution_id,
            source_revision_id=origin.id,
            payload={"grade": "우선 검토"},
        )

        assert carried.sequence == 2
        assert origin_execution_for_judgment_revision(session, carried).execution_id == (
            first_execution.execution_id
        )
        assert [row.id for row in judgment_revision_history(session, notice.id)] == [
            origin.id,
            carried.id,
        ]
        with pytest.raises(RevisionValidationError, match="same notice"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="carry_over",
                run_id="revision-run",
                recording_execution_id=second_execution.execution_id,
                source_revision_id=other_origin.id,
                payload={"grade": None},
            )


def test_carry_parent_origin_must_match_declared_run_even_for_same_payload() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, other, first_execution, _second = _seed(session)
        payload = {
            "grade": "우선 검토",
            "counterargument_resolutions": [
                {
                    "counterargument": "범위 확인",
                    "status": "추가 확인",
                    "reflection": "원문에서 확인",
                }
            ],
        }
        declared_origin = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=first_execution.execution_id,
            payload=payload,
        )
        wrong_run = Run(id="wrong-origin-run", generated_at=NOW)
        wrong_execution = _execution(
            "scr-" + "3" * 32, wrong_run.id, "revision-wrong-origin"
        )
        session.add_all(
            [
                wrong_run,
                NoticeObservation(
                    notice_id=notice.id,
                    run_id=wrong_run.id,
                    observed_at=NOW,
                    changed_fields_json=[],
                ),
                wrong_execution,
            ]
        )
        session.flush()
        same_payload_wrong_origin = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id=wrong_run.id,
            recording_execution_id=wrong_execution.execution_id,
            payload=payload,
        )
        legacy_unknown_origin = append_judgment_revision(
            session,
            notice_id=other.id,
            source_kind="legacy_import",
            payload=payload,
        )

        assert require_carry_origin_run(
            session,
            declared_origin,
            expected_source_run_id="revision-run",
        ).execution_id == first_execution.execution_id
        with pytest.raises(RevisionValidationError, match="rejudgment is required"):
            require_carry_origin_run(
                session,
                same_payload_wrong_origin,
                expected_source_run_id="revision-run",
            )
        with pytest.raises(RevisionValidationError, match="rejudgment is required"):
            require_carry_origin_run(
                session,
                legacy_unknown_origin,
                expected_source_run_id="revision-run",
            )


def test_human_review_pins_only_a_same_notice_judgment_revision() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, other, execution, _second = _seed(session)
        judgment = append_judgment_revision(
            session,
            notice_id=notice.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=execution.execution_id,
            payload={"grade": None},
        )
        other_judgment = append_judgment_revision(
            session,
            notice_id=other.id,
            source_kind="runtime",
            run_id="revision-run",
            recording_execution_id=execution.execution_id,
            payload={"grade": None},
        )
        payload = {"disposition": None, "verification_answers": []}
        review = append_review_revision(
            session,
            notice_id=notice.id,
            source_kind="human",
            run_id="revision-run",
            judgment_revision_id=judgment.id,
            payload=payload,
        )
        replay = append_review_revision(
            session,
            notice_id=notice.id,
            source_kind="human",
            run_id="revision-run",
            judgment_revision_id=judgment.id,
            payload=payload,
        )

        assert replay.id == review.id
        assert review.judgment_revision_id == judgment.id
        assert review.payload_jsonb["disposition"] is None
        assert review_revision_history(session, notice.id) == [review]
        with pytest.raises(RevisionValidationError, match="same notice"):
            append_review_revision(
                session,
                notice_id=notice.id,
                source_kind="human",
                run_id="revision-run",
                judgment_revision_id=other_judgment.id,
                payload=payload,
            )


def test_run_provenance_and_aware_capture_are_fail_closed() -> None:
    engine = _engine()
    with Session(engine) as session:
        notice, _other, execution, _second = _seed(session)
        with pytest.raises(RevisionValidationError, match="did not observe"):
            append_judgment_revision(
                session,
                notice_id=notice.id,
                source_kind="runtime",
                run_id="missing-run",
                recording_execution_id=execution.execution_id,
                payload={},
            )
        with pytest.raises(RevisionValidationError, match="timezone-aware"):
            append_review_revision(
                session,
                notice_id=notice.id,
                source_kind="human",
                run_id="revision-run",
                payload={},
                captured_at=datetime(2026, 8, 31, 3, 0),
            )
