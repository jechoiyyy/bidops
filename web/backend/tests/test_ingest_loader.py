from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, init_db
from app.ingest.loader import ingest_run
from app.models import (
    Counterargument,
    IngestWarning,
    Judgment,
    Notice,
    Perspective,
    Review,
    Run,
    VerificationItem,
)
from tests.test_screening_orchestrator import _notice as screening_notice


def make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def notice(notice_id: str = "bid:TEST001:000") -> dict:
    return {
        "notice_id": notice_id,
        "source_type": "bid_notice",
        "title": "테스트 공고",
        "agency": "테스트 기관",
        "published_at": "2026-08-24T09:00:00",
        "deadline_at": "2026-08-31T18:00:00",
        "budget": "1000000",
        "estimated_price": "900000",
        "method": "일반경쟁",
        "url": "https://example.test/notice",
        "procurement_class": {"large": "ICT 서비스"},
        "region_limit": {},
        "lifecycle": {},
        "qualification_flags": {},
        "focus_matches": [],
        "performance_matches": [],
        "performance_top_score": 0,
        "candidate_sources": [],
        "collection_bucket": "candidate_pool",
        "unknown_fields": [],
        "raw_source": "raw/test.json",
        "sample_role": "analysis",
        "sample_stratum": "AI/데이터",
    }


def judgment(
    notice_id: str = "bid:TEST001:000",
    *,
    perspectives: list[dict] | None = None,
    grade: str | None = "우선 검토",
    readiness: str | None = "부분 확인 필요",
    counterarguments: list | None = None,
    verification_items: list | None = None,
) -> dict:
    value = {
        "notice_id": notice_id,
        "grade": grade,
        "readiness": readiness,
        "primary_focus": "AI/데이터",
        "summary": "요약",
        "next_action": "다음 행동",
    }
    if perspectives is not None:
        value["perspectives"] = perspectives
    if counterarguments is not None:
        value["counterarguments"] = counterarguments
    if verification_items is not None:
        value["verification_items"] = verification_items
    return value


def write_run(
    root: Path,
    *,
    validation: dict | None = None,
    screening: dict | None = None,
    decisions: dict | None = None,
    feedback: str | None = None,
) -> Path:
    run_dir = root / "runs" / "20260817-20260823"
    run_dir.mkdir(parents=True, exist_ok=True)
    if validation is not None:
        (run_dir / "validation-set.json").write_text(
            json.dumps(validation, ensure_ascii=False), encoding="utf-8"
        )
    if screening is not None:
        (run_dir / "screening-results.json").write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8"
        )
    if decisions is not None:
        (run_dir / "screening-decisions.json").write_text(
            json.dumps(decisions, ensure_ascii=False), encoding="utf-8"
        )
    if feedback is not None:
        report_dir = root / "reports" / run_dir.name
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "review-feedback.yaml").write_text(feedback, encoding="utf-8")
    return run_dir


def base_artifacts(*, generated_at: str = "2026-08-24T00:00:00+00:00") -> tuple[dict, dict, dict]:
    item = notice()
    validation = {
        "schema_version": "bidops.validation-set.v2",
        "source_window": {
            "from": "2026-08-17",
            "to": "2026-08-23",
            "timezone": "Asia/Seoul",
        },
        "notices": [item],
    }
    result_judgment = judgment(
        perspectives=[{"name": "기술 적합성", "assessment": "적합", "reason": "이유", "evidence": []}],
        counterarguments=[],
        verification_items=[],
    )
    screening = {
        "schema_version": "bidops.screening.v2",
        "generated_at": generated_at,
        "screening_basis": "메타데이터",
        "source_window": validation["source_window"],
        "results": [{"notice": item, "judgment": {k: v for k, v in result_judgment.items() if k != "notice_id"}}],
    }
    decisions = {
        "schema_version": "bidops.decisions.v2",
        "screening_basis": "메타데이터",
        "judgments": [result_judgment],
    }
    return validation, screening, decisions


@pytest.fixture
def db_session():
    engine = make_engine()
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_loader_records_contract_gaps_and_keeps_available_rows(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 1
    stored_notice = db_session.scalar(select(Notice))
    assert stored_notice is not None
    assert stored_notice.published_at.tzinfo is not None
    assert db_session.scalar(select(func.count()).select_from(Perspective)) == 1
    assert db_session.scalar(select(func.count()).select_from(Counterargument)) == 0
    assert db_session.scalar(select(func.count()).select_from(VerificationItem)) == 0
    codes = [warning["code"] for warning in result.warnings]
    assert "perspectives_below_contract" in codes
    assert "counterarguments_missing" in codes
    assert "verification_items_missing" in codes


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"{malformed",
        b"{\n  \"schema_version\": \"bidops.screening-input.v1\"\n}",
    ],
)
def test_present_invalid_screening_input_never_falls_back_to_validation(tmp_path, db_session, raw: bytes):
    validation, _screening, _decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation)
    (run_dir / "screening-input.json").write_bytes(raw)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 0 and result.judgments == 0
    assert any(item["code"] == "screening_input_invalid" for item in result.warnings)
    assert db_session.scalar(select(func.count(Notice.id))) == 0


def test_loader_v3_input_is_fail_closed_for_duplicate_and_invalid_identity(tmp_path, db_session):
    run_dir = tmp_path / "runs" / "screen-run"
    run_dir.mkdir(parents=True)
    first = screening_notice("candidate-1")
    first.update({"judgment_mode": "신규", "carry_over_from": None, "rejudge_reason": None})
    value = {
        "schema_version": "bidops.screening-input.v1",
        "execution_id": "scr-" + "a" * 32,
        "run_id": "source-run",
        "generated_at": "2026-08-26T01:00:00+00:00",
        "source_window": {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"},
        "policy_version": "policy-v1", "prompt_version": "prompt-v1",
        "company_profile_version": "company-profile.sha256:" + "b" * 64,
        "company_profile_digest": "b" * 64,
        "candidate_count": 2,
        "notices": [first, {**first}],
    }
    (run_dir / "screening-input.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    assert result.notices == 0
    assert db_session.scalar(select(func.count()).select_from(Notice)) == 0
    assert any(item["code"] == "screening_input_invalid" for item in result.warnings)


def test_v1_schema_gap_is_a_warning_and_legacy_judgment_is_loaded(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    decisions["schema_version"] = "bidops.decisions.v1"
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.judgments == 1
    schema_warning = next(item for item in result.warnings if item["code"] == "decisions_schema_gap")
    assert schema_warning["context"] == {
        "actual": "bidops.decisions.v1",
        "expected": "bidops.decisions.v2",
    }
    perspective_warning = next(
        item for item in result.warnings if item["code"] == "perspectives_below_contract"
    )
    assert perspective_warning["context"]["schema_version"] == "bidops.decisions.v1"


def test_missing_core_judgment_field_is_not_loaded(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    screening["results"][0]["judgment"]["grade"] = None
    decisions["judgments"][0]["grade"] = None
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)

    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 0
    warning = next(item for item in result.warnings if item["code"] == "judgment_required_field_missing")
    assert warning["level"] == "error"
    assert warning["context"]["fields"] == ["grade"]


def test_missing_validation_stops_after_recording_error(tmp_path, db_session):
    run_dir = write_run(tmp_path)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 0
    assert result.judgments == 0
    assert any(item["code"] == "validation_missing" for item in result.warnings)
    assert db_session.scalar(select(func.count()).select_from(Run)) == 1


def test_missing_screening_loads_notices_only(tmp_path, db_session):
    validation, _, _ = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation)
    result = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert result.notices == 1
    assert result.judgments == 0
    assert any(item["code"] == "screening_results_missing" for item in result.warnings)


def test_reingest_is_idempotent_and_cleans_old_warnings(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    first_counts = {
        model.__tablename__: db_session.scalar(select(func.count()).select_from(model))
        for model in (Notice, Judgment, Perspective, Counterargument, VerificationItem, IngestWarning)
    }
    second = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    second_counts = {
        model.__tablename__: db_session.scalar(select(func.count()).select_from(model))
        for model in (Notice, Judgment, Perspective, Counterargument, VerificationItem, IngestWarning)
    }

    assert first.run_id == second.run_id
    assert first_counts == second_counts
    assert second_counts["ingest_warning"] == len(second.warnings)


def test_feedback_only_creates_nonempty_review_and_does_not_overwrite_it(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    feedback = """schema_version: bidops.feedback.v2
reviews:
  - notice_id: bid:TEST001:000
    disposition: 관찰
    system_judgment_review: null
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: null
    reason: ""
    verification_answers: []
  - notice_id: bid:TEST001:000
    disposition: null
    system_judgment_review: null
    corrected_grade: null
    corrected_readiness: null
    weakest_perspective: null
    reason: ""
    verification_answers: []
"""
    run_dir = write_run(
        tmp_path,
        validation=validation,
        screening=screening,
        decisions=decisions,
        feedback=feedback,
    )
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    review = db_session.scalar(select(Review))
    assert first.reviews == 1
    assert review is not None and review.disposition == "관찰"

    (tmp_path / "reports" / run_dir.name / "review-feedback.yaml").write_text(
        feedback.replace("disposition: 관찰", "disposition: 제외"), encoding="utf-8"
    )
    ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    db_session.refresh(review)
    assert review.disposition == "관찰"
    assert db_session.scalar(select(func.count()).select_from(Review)) == 1


def test_new_generated_at_creates_snapshot_and_supersedes_previous(tmp_path, db_session):
    validation, screening, decisions = base_artifacts()
    run_dir = write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    first = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")
    screening["generated_at"] = "2026-08-24T01:00:00+00:00"
    write_run(tmp_path, validation=validation, screening=screening, decisions=decisions)
    second = ingest_run(run_dir, db_session, reports_root=tmp_path / "reports")

    assert first.run_id != second.run_id
    runs = db_session.scalars(select(Run).order_by(Run.id)).all()
    assert runs[0].status == "superseded"
    assert runs[0].superseded_by == runs[1].id
    assert db_session.scalar(select(func.count()).select_from(Notice)) == 2


def test_real_run_integration_if_artifacts_are_available(tmp_path, db_session):
    project_root = Path(__file__).resolve().parents[3]
    run_dir = project_root / "data" / "runs" / "20260817-20260823"
    if not all((run_dir / name).is_file() for name in ("validation-set.json", "screening-results.json")):
        pytest.skip("실제 회차 산출물이 없습니다")

    result = ingest_run(run_dir, db_session, reports_root=project_root / "reports")

    assert result.notices == 40
    assert result.judgments == 40
    assert db_session.scalar(select(func.count()).select_from(IngestWarning)) >= 0
