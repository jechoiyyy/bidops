from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.screening import ingest_feedback as feedback_loader
from app.main import app
from app.models import (
    AuditEvent,
    JudgmentRevision,
    Notice,
    NoticeObservation,
    Review,
    ReviewRevision,
    Run,
    ScreeningExecution,
    VerificationAnswer,
)
from app.routers import reviews as reviews_router
from app.core.generation_config import GenerationConfig
from app.services.revisions import append_judgment_revision


NOW = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
PROFILE_VERSION = "company-profile.sha256:" + DIGEST


def _execution(execution_id: str, run_id: str, suffix: str) -> ScreeningExecution:
    config = GenerationConfig()
    return ScreeningExecution(
        execution_id=execution_id,
        trigger="manual_run",
        source_run_id=run_id,
        scope="full_run",
        status="대기",
        requested_by="review-integration-test",
        policy_version="policy-review-test",
        prompt_version="prompt-review-test",
        model_name="qwen3.8:27b",
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


@pytest.fixture
def review_revision_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine, expire_on_commit=False) as session:
        observed_run = Run(id="review-observed", generated_at=NOW)
        other_run = Run(id="review-other", generated_at=NOW)
        notice = Notice(run=observed_run, notice_key="review:revision:one")
        session.add_all([observed_run, other_run, notice])
        session.commit()

        monkeypatch.setattr(
            reviews_router,
            "get_settings",
            lambda: SimpleNamespace(reviewer_name=""),
        )

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, session, notice
        finally:
            app.dependency_overrides.pop(get_db, None)


def _review_body(**changes):
    body = {
        "run_id": "review-observed",
        "disposition": "관찰",
        "system_judgment_review": None,
        "corrected_grade": None,
        "corrected_readiness": None,
        "weakest_perspective": "unknown",
        "reason": None,
        "reviewer": "검토자",
        "verification_answers": [
            {"item": "자격", "answer": None},
            {"item": None, "answer": "unknown"},
        ],
    }
    body.update(changes)
    return body


def test_invalid_notice_run_observation_and_reviewer_make_no_writes(
    review_revision_client,
):
    client, session, notice = review_revision_client

    missing_notice = client.put("/api/notices/999/review", json=_review_body())
    assert missing_notice.status_code == 404
    assert missing_notice.json()["error"]["code"] == "notice_not_found"

    invalid_observation = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(run_id="review-other"),
    )
    assert invalid_observation.status_code == 409
    assert invalid_observation.json()["error"]["code"] == (
        "review_observation_required"
    )

    missing_reviewer = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(reviewer="   "),
    )
    assert missing_reviewer.status_code == 422
    assert missing_reviewer.json()["error"]["code"] == "reviewer_required"

    for model in (Review, ReviewRevision, VerificationAnswer, AuditEvent):
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_configured_reviewer_fallback_is_a_nonblank_audit_label(
    review_revision_client, monkeypatch
):
    client, session, notice = review_revision_client
    monkeypatch.setattr(
        reviews_router,
        "get_settings",
        lambda: SimpleNamespace(reviewer_name="설정 담당자"),
    )

    response = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(reviewer=None),
    )
    assert response.status_code == 200
    assert response.json()["reviewer"] == "설정 담당자"
    audit = session.scalar(select(AuditEvent))
    assert audit is not None
    assert audit.claimed_name == "설정 담당자"
    assert audit.actor_kind == "human"


def test_save_change_and_exact_replay_preserve_history_and_current_shape(
    review_revision_client,
):
    client, session, notice = review_revision_client
    first = client.put(f"/api/notices/{notice.id}/review", json=_review_body())
    assert first.status_code == 200
    first_response = first.json()
    first_answer_ids = [answer["id"] for answer in first_response["answers"]]
    first_updated_at = first_response["updated_at"]

    first_revision = session.scalar(select(ReviewRevision))
    assert first_revision is not None
    assert first_revision.judgment_revision_id is None
    assert first_revision.payload_jsonb == {
        "disposition": "관찰",
        "system_judgment_review": None,
        "corrected_grade": None,
        "corrected_readiness": None,
        "weakest_perspective": "unknown",
        "reason": None,
        "reviewer": "검토자",
        "verification_answers": [
            {"item": "자격", "answer": None},
            {"item": None, "answer": "unknown"},
        ],
    }
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1

    changed = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(
            reason="값 변경",
            verification_answers=[{"item": "자격", "answer": "확인"}],
        ),
    )
    assert changed.status_code == 200
    changed_response = changed.json()
    assert changed_response["id"] == first_response["id"]
    assert changed_response["updated_at"] != first_updated_at
    assert [answer["id"] for answer in changed_response["answers"]] != (
        first_answer_ids
    )

    revisions = session.scalars(
        select(ReviewRevision).order_by(ReviewRevision.sequence)
    ).all()
    assert len(revisions) == 2
    assert revisions[0].payload_jsonb["verification_answers"][1]["answer"] == (
        "unknown"
    )
    assert revisions[1].payload_jsonb["verification_answers"] == [
        {"item": "자격", "answer": "확인"}
    ]
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2

    replay = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(
            reason="값 변경",
            verification_answers=[{"item": "자격", "answer": "확인"}],
        ),
    )
    assert replay.status_code == 200
    assert replay.json()["updated_at"] == changed_response["updated_at"]
    assert replay.json()["answers"] == changed_response["answers"]
    assert session.scalar(select(func.count()).select_from(ReviewRevision)) == 2
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2


def test_review_pins_current_judgment_and_history_resolves_carry_origin(
    review_revision_client, monkeypatch
):
    client, session, notice = review_revision_client
    second_run = session.get(Run, "review-other")
    assert second_run is not None
    session.add(
        NoticeObservation(
            notice_id=notice.id,
            run_id=second_run.id,
            observed_at=NOW,
            changed_fields_json=[],
        )
    )
    origin_execution = _execution(
        "scr-" + "1" * 32, "review-observed", "review-origin"
    )
    carried_execution = _execution(
        "scr-" + "2" * 32, "review-other", "review-carried"
    )
    session.add_all([origin_execution, carried_execution])
    session.flush()
    origin = append_judgment_revision(
        session,
        notice_id=notice.id,
        source_kind="runtime",
        run_id="review-observed",
        recording_execution_id=origin_execution.execution_id,
        payload={"grade": "우선 검토", "unknown": None},
    )
    carried = append_judgment_revision(
        session,
        notice_id=notice.id,
        source_kind="carry_over",
        run_id="review-other",
        recording_execution_id=carried_execution.execution_id,
        source_revision_id=origin.id,
        payload={"grade": "우선 검토", "unknown": None},
    )
    session.commit()

    saved = client.put(
        f"/api/notices/{notice.id}/review",
        json=_review_body(run_id="review-other"),
    )
    assert saved.status_code == 200
    review_revision = session.scalar(select(ReviewRevision))
    assert review_revision is not None
    assert review_revision.judgment_revision_id == carried.id

    response = client.get(f"/api/notices/{notice.id}/revision-history")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"notice_pk", "judgments", "reviews"}
    assert set(body["judgments"][0]) == {
        "id",
        "sequence",
        "source_kind",
        "run_id",
        "recording_execution_id",
        "source_revision_id",
        "origin_execution_id",
        "payload_schema_version",
        "payload",
        "payload_sha256",
        "captured_at",
    }
    assert set(body["reviews"][0]) == {
        "id",
        "sequence",
        "source_kind",
        "run_id",
        "judgment_revision_id",
        "origin_execution_id",
        "payload_schema_version",
        "payload",
        "payload_sha256",
        "captured_at",
    }
    assert body["notice_pk"] == notice.id
    assert [item["sequence"] for item in body["judgments"]] == [1, 2]
    assert body["judgments"][1]["source_revision_id"] == origin.id
    assert {
        item["origin_execution_id"] for item in body["judgments"]
    } == {origin_execution.execution_id}
    assert body["reviews"][0]["judgment_revision_id"] == carried.id
    assert body["reviews"][0]["origin_execution_id"] == (
        origin_execution.execution_id
    )
    assert body["reviews"][0]["payload"]["weakest_perspective"] == "unknown"

    missing = client.get("/api/notices/999/revision-history")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "notice_not_found",
            "message": "공고를 찾을 수 없습니다",
            "details": None,
        },
        "request_id": None,
    }

    # Simulate persisted lineage corruption in this isolated SQLite fixture.
    # PostgreSQL append-only/FK guards prevent this write in production; the
    # read boundary must still fail closed without leaking storage details.
    carried_id = carried.id
    session.rollback()
    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.execute(
        text(
            "UPDATE judgment_revision SET source_revision_id = 999999 "
            "WHERE id = :revision_id"
        ),
        {"revision_id": carried_id},
    )
    session.commit()
    session.expire_all()
    corrupted = client.get(f"/api/notices/{notice.id}/revision-history")
    assert corrupted.status_code == 409
    assert corrupted.json() == {
        "error": {
            "code": "revision_history_conflict",
            "message": "리비전 계보를 확인할 수 없습니다",
            "details": None,
        },
        "request_id": None,
    }

    def unexpected_history_failure(*_args, **_kwargs):
        raise RuntimeError("internal database detail")

    monkeypatch.setattr(
        reviews_router.review_service,
        "get_revision_history",
        unexpected_history_failure,
    )
    failed = client.get(f"/api/notices/{notice.id}/revision-history")
    assert failed.status_code == 500
    assert failed.json() == {
        "error": {
            "code": "processing_failed",
            "message": "리뷰 작업을 완료할 수 없습니다",
            "details": None,
        },
        "request_id": None,
    }
    assert "internal database detail" not in failed.text


def test_feedback_import_adds_one_unaligned_legacy_snapshot_on_retry(
    tmp_path, monkeypatch
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    feedback_path = tmp_path / "review-feedback.yaml"
    feedback_path.write_text(
        """schema_version: bidops.feedback.v2
reviews:
  - notice_id: review:feedback:one
    disposition: 관찰
    system_judgment_review: null
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: unknown
    reason: null
    verification_answers:
      - item: 자격
        answer: null
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIDOPS_REVIEWER_NAME", "현재 설정 담당자")

    with Session(engine, expire_on_commit=False) as session:
        run = Run(id="feedback-revision-run", generated_at=NOW)
        notice = Notice(run=run, notice_key="review:feedback:one")
        session.add_all([run, notice])
        session.commit()

        assert feedback_loader.load_feedback(
            session, run, {notice.notice_key: notice}, feedback_path
        ) == 1
        session.commit()
        revision = session.scalar(select(ReviewRevision))
        assert revision is not None
        assert revision.source_kind == "legacy_import"
        assert revision.run_id == run.id
        assert revision.judgment_revision_id is None
        assert revision.payload_jsonb["reviewer"] is None
        assert revision.payload_jsonb["weakest_perspective"] == "unknown"
        assert revision.payload_jsonb["verification_answers"] == [
            {"item": "자격", "answer": None}
        ]
        assert session.scalar(select(Review)).reviewer is None

        feedback_path.write_text(
            feedback_path.read_text(encoding="utf-8").replace("관찰", "제외"),
            encoding="utf-8",
        )
        assert feedback_loader.load_feedback(
            session, run, {notice.notice_key: notice}, feedback_path
        ) == 0
        session.commit()
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(select(func.count()).select_from(ReviewRevision)) == 1
        assert session.scalar(select(Review)).disposition == "관찰"
