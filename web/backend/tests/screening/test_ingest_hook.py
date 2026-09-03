"""screening의 회차 적재 hook (명세 §6.2).

C-2 전용 디렉터리의 감지·`source_run_id` 검증과 판정·리뷰 적재는 lifecycle이
아니라 이 hook의 일이다. lifecycle `ingest_run`은 hook에 디렉터리를 보여 주고
돌려받은 건수만 옮긴다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import RunDirectoryClaim, RunIngestCounts, ingest_run
from app.lifecycle.models import IngestWarning, Notice, Run
from app.screening.models import Judgment, JudgmentRevision, Review
from app.screening import ScreeningRunIngestHook
from app.screening.ingest import (
    C2_INPUT_SCHEMA,
    OrderPlanScreeningContractError,
    inspect_c2_directory,
)
from tests.c2_fixtures import write_c2_fixture, write_c2_json


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return Session(engine)


def _notice(notice_id: str = "bid:HOOK:000") -> dict:
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


def _write_run(root: Path, *, with_feedback: bool = True) -> Path:
    run_dir = root / "runs" / "20260817-20260823"
    run_dir.mkdir(parents=True)
    item = _notice()
    window = {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
    (run_dir / "validation-set.json").write_text(
        json.dumps({"schema_version": "bidops.validation-set.v2", "source_window": window, "notices": [item]}, ensure_ascii=False),
        encoding="utf-8",
    )
    judgment = {
        "grade": "우선 검토",
        "readiness": "부분 확인 필요",
        "primary_focus": "AI/데이터",
        "summary": "요약",
        "next_action": "다음",
        "perspectives": [{"name": "기술 적합성", "assessment": "적합", "reason": "이유", "evidence": []}],
        "counterarguments": [],
        "verification_items": [],
    }
    (run_dir / "screening-results.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.screening.v2",
                "generated_at": "2026-08-24T00:00:00+00:00",
                "screening_basis": "메타데이터",
                "source_window": window,
                "results": [{"notice": item, "judgment": judgment}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "screening-decisions.json").write_text(
        json.dumps({"schema_version": "bidops.decisions.v2", "screening_basis": "메타데이터", "judgments": [{"notice_id": item["notice_id"], **judgment}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if with_feedback:
        report_dir = root / "reports" / run_dir.name
        report_dir.mkdir(parents=True)
        (report_dir / "review-feedback.yaml").write_text(
            "schema_version: bidops.feedback.v2\nreviews:\n  - notice_id: bid:HOOK:000\n    disposition: 관찰\n",
            encoding="utf-8",
        )
    return run_dir


def test_inspect_recognises_a_c2_directory_and_names_its_source_run(tmp_path):
    run_dir, source_run_id = write_c2_fixture(tmp_path)

    claim = inspect_c2_directory(run_dir)
    assert isinstance(claim, RunDirectoryClaim)
    assert claim.source_run_id == source_run_id
    assert ScreeningRunIngestHook().inspect_run_directory(run_dir) is not None


def test_inspect_ignores_an_ordinary_run_directory(tmp_path):
    run_dir = _write_run(tmp_path)

    assert inspect_c2_directory(run_dir) is None
    assert ScreeningRunIngestHook().inspect_run_directory(run_dir) is None


def test_inspect_rejects_a_c2_directory_without_a_source_run_id(tmp_path):
    run_dir, _ = write_c2_fixture(tmp_path)
    input_path = run_dir / "screening-input.json"
    value = json.loads(input_path.read_text(encoding="utf-8"))
    assert value["schema_version"] == C2_INPUT_SCHEMA
    value["source_run_id"] = "   "
    write_c2_json(input_path, value)

    with pytest.raises(OrderPlanScreeningContractError):
        inspect_c2_directory(run_dir)


def test_run_ingested_loads_judgments_and_reviews_and_reports_run_scoped_counts(tmp_path, screening_extensions):
    run_dir = _write_run(tmp_path)
    with _session() as session:
        result = ingest_run(run_dir, session, reports_root=tmp_path / "reports")

        assert result.notices == 1 and result.judgments == 1 and result.reviews == 1
        assert not any(item["code"] == "judgment_ingest_skipped" for item in result.warnings)
        run = session.get(Run, result.run_id)
        assert run is not None and run.counts_json["judgments"] == 1 and run.counts_json["reviews"] == 1
        judgment = session.scalar(select(Judgment))
        assert judgment is not None and judgment.grade == "우선 검토"
        assert session.scalar(select(func.count()).select_from(JudgmentRevision)) == 1
        assert session.scalar(select(Review)).disposition == "관찰"

        # hook을 직접 다시 부르면 회차 범위의 누적 건수를 돌려준다 (재적재 멱등).
        counts = ScreeningRunIngestHook().run_ingested(session, result.run_id, run_dir, reports_root=tmp_path / "reports")
        assert isinstance(counts, RunIngestCounts)
        assert counts.judgments == 1 and counts.reviews == 1
        assert counts.generation_config is None
        assert session.scalar(select(func.count()).select_from(Judgment)) == 1


def test_run_ingested_records_judgment_warnings_as_ingest_warnings(tmp_path, screening_extensions):
    run_dir = _write_run(tmp_path, with_feedback=False)
    (run_dir / "screening-results.json").unlink()
    with _session() as session:
        result = ingest_run(run_dir, session, reports_root=tmp_path / "reports")

        assert result.judgments == 0
        codes = session.scalars(select(IngestWarning.code)).all()
        assert "screening_results_missing" in codes
        assert "judgment_ingest_skipped" not in codes
        assert session.scalar(select(func.count()).select_from(Notice)) == 1
