"""T-23 phase-2 lifecycle, strict result, and safe projection regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PreSpecOverviewAttempt,
    PreSpecOverviewAttemptEvent,
    PreSpecOverviewResult,
)
from app.routers.pre_specs import get_pre_spec_overview_reviews_v2
from app.services.prespec_overview import (
    OverviewAttemptError,
    OverviewModelBinding,
    OverviewResultValidationError,
    complete_overview_attempt,
    create_overview_attempt,
    get_overview_reviews_v2,
    prepare_overview_review,
    transition_overview_attempt,
)
from tests.test_prespec_overview import _block, _engine, _notice, _seed_document


def _ready_attempt(tmp_path: Path):
    engine = _engine()
    session = Session(engine)
    notice = _notice(session, "phase2")
    _seed_document(
        session,
        tmp_path,
        notice,
        [
            _block("start", "heading", "사업개요"),
            _block("body", "paragraph", "검토 대상"),
            _block("end", "heading", "과업내용"),
        ],
        source_suffix="phase2",
    )
    review = prepare_overview_review(session, notice.id, root=tmp_path)
    session.commit()
    binding = OverviewModelBinding(
        provider="test-fake",
        model_name="test-model",
        model_digest="a" * 64,
        prompt_version="prompt-v1",
        reference_only=True,
        deployable=False,
    )
    attempt = create_overview_attempt(
        session,
        notice.id,
        review.id,
        review.current_snapshot_id,
        binding=binding,
    )
    session.commit()
    assert attempt is not None
    return engine, session, notice, review, attempt


def _payload(**overrides):
    payload = {
        "schema_version": "bidops.prespec-overview-result.v1",
        "recommendation": "추진 검토",
        "summary": "고정 snapshot 범위 요약",
        "conditions": [],
        "verification_due_at": None,
        "unknowns": [],
        "evidence": [
            {
                "claim": "사업개요 경계",
                "locator": {"block_key": "start", "page": 1, "ordinal": 0},
            }
        ],
        "input_limitations": [],
    }
    payload.update(overrides)
    return payload


def test_result_schema_is_strict_and_conditional_requires_due() -> None:
    common = {
        "schema_version": "bidops.prespec-overview-result.v1",
        "recommendation": "추진 검토",
        "summary": "요약",
        "conditions": [],
        "verification_due_at": None,
        "unknowns": [],
        "evidence": [],
        "input_limitations": [],
    }
    with pytest.raises(ValidationError):
        from app.schemas.pre_specs import PreSpecOverviewResultPayload

        PreSpecOverviewResultPayload.model_validate({**common, "internal": "secret"})
    with pytest.raises(ValidationError):
        from app.schemas.pre_specs import PreSpecOverviewResultPayload

        PreSpecOverviewResultPayload.model_validate(
            {**common, "recommendation": "조건부 추진 검토"}
        )
    with pytest.raises(ValidationError):
        from app.schemas.pre_specs import PreSpecOverviewResultPayload

        PreSpecOverviewResultPayload.model_validate(
            {key: value for key, value in common.items() if key != "evidence"}
        )


def test_no_binding_keeps_awaiting_model_without_attempt(tmp_path: Path) -> None:
    engine = _engine()
    try:
        with Session(engine) as session:
            notice = _notice(session, "no-binding")
            _seed_document(
                session,
                tmp_path,
                notice,
                [
                    _block("start", "heading", "사업개요"),
                    _block("body", "paragraph", "검토 대상"),
                    _block("end", "heading", "과업내용"),
                ],
                source_suffix="no-binding",
            )
            review = prepare_overview_review(session, notice.id, root=tmp_path)
            session.commit()
            assert (
                create_overview_attempt(
                    session,
                    notice.id,
                    review.id,
                    review.current_snapshot_id,
                    binding=None,
                )
                is None
            )
            session.commit()
            assert review.status == "awaiting_model"
            assert session.scalar(select(PreSpecOverviewAttempt.id)) is None
    finally:
        engine.dispose()


def test_lifecycle_event_result_and_v2_projection_are_safe(tmp_path: Path) -> None:
    engine, session, notice, _review, attempt = _ready_attempt(tmp_path)
    try:
        transition_overview_attempt(
            session,
            attempt.id,
            "running",
            actor_id="fake-worker",
            reason_code="started",
        )
        session.commit()
        snapshot = session.get(type(attempt.snapshot), attempt.snapshot_id)
        assert snapshot is not None
        completed = complete_overview_attempt(
            session,
            attempt.id,
            _payload(),
            actor_id="fake-worker",
        )
        session.commit()
        assert completed.status == "completed"
        assert session.scalar(
            select(PreSpecOverviewAttemptEvent).where(
                PreSpecOverviewAttemptEvent.attempt_id == attempt.id
            ).order_by(PreSpecOverviewAttemptEvent.event_sequence.desc())
        ).to_status == "completed"
        assert session.scalar(
            select(PreSpecOverviewResult).where(
                PreSpecOverviewResult.attempt_id == attempt.id
            )
        ) is not None
        projection = get_overview_reviews_v2(session, notice.id, root=tmp_path)
        dumped = projection.model_dump(mode="json")
        review_view = dumped["reviews"][0]
        assert projection.schema_version == "bidops.prespec-overview-reviews.v2"
        assert review_view["result"]["recommendation"] == "추진 검토"
        assert review_view["result_digest"]
        assert review_view["binding_digest"]
        serialized = str(dumped)
        for forbidden in ("provider", "model_name", "prompt_version", "raw_response", "object_path"):
            assert forbidden not in serialized
        routed = get_pre_spec_overview_reviews_v2(notice.id, session)
        assert routed.schema_version == "bidops.prespec-overview-reviews.v2"
    finally:
        session.close()
        engine.dispose()


def test_invalid_evidence_fails_attempt_without_result(tmp_path: Path) -> None:
    engine, session, _notice, _review, attempt = _ready_attempt(tmp_path)
    try:
        transition_overview_attempt(
            session,
            attempt.id,
            "running",
            actor_id="fake-worker",
            reason_code="started",
        )
        session.commit()
        snapshot = session.get(type(attempt.snapshot), attempt.snapshot_id)
        assert snapshot is not None
        with pytest.raises(OverviewResultValidationError) as error:
            complete_overview_attempt(
                session,
                attempt.id,
                _payload(
                    evidence=[
                        {
                            "claim": "범위 밖",
                            "locator": {"block_key": "outside", "page": 1, "ordinal": 2},
                        }
                    ],
                ),
            )
        assert error.value.code == "evidence_out_of_scope"
        session.commit()
        assert attempt.status == "failed"
        assert session.scalar(
            select(PreSpecOverviewResult).where(
                PreSpecOverviewResult.attempt_id == attempt.id
            )
        ) is None
    finally:
        session.close()
        engine.dispose()


def test_terminal_attempt_cannot_reverse_or_be_deleted(tmp_path: Path) -> None:
    engine, session, _notice, _review, attempt = _ready_attempt(tmp_path)
    try:
        transition_overview_attempt(
            session,
            attempt.id,
            "running",
            actor_id="fake-worker",
            reason_code="started",
        )
        transition_overview_attempt(
            session,
            attempt.id,
            "failed",
            actor_id="fake-worker",
            reason_code="failed",
        )
        session.commit()
        with pytest.raises(OverviewAttemptError) as error:
            transition_overview_attempt(
                session,
                attempt.id,
                "running",
                actor_id="fake-worker",
                reason_code="reverse",
            )
        assert error.value.code == "invalid_transition"
        with pytest.raises(ValueError):
            session.delete(attempt)
            session.flush()
        session.rollback()
    finally:
        session.close()
        engine.dispose()
