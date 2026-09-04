"""회차 적재 hook이 없을 때의 `ingest_run` (명세 §6.2 "제공자 부재 시").

screening이 등록되지 않으면 lifecycle은 공고·발주계획·첨부 메타만 적재한다.
판정·리뷰 건수는 0이고 warnings에 건너뛰었음이 남으며, C-2 전용 디렉터리는
인식되지 않아 일반 회차 디렉터리로 처리된다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import ingest_run
from app.lifecycle.models import IngestWarning, Notice, Run
from tests.c2_fixtures import write_c2_fixture


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return Session(engine)


def _notice(notice_id: str = "bid:LC:000") -> dict:
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


def _write_run_with_judgment(root: Path) -> Path:
    run_dir = root / "runs" / "20260817-20260823"
    run_dir.mkdir(parents=True)
    item = _notice()
    window = {"from": "2026-08-17", "to": "2026-08-23", "timezone": "Asia/Seoul"}
    (run_dir / "validation-set.json").write_text(
        json.dumps({"schema_version": "bidops.validation-set.v2", "source_window": window, "notices": [item]}, ensure_ascii=False),
        encoding="utf-8",
    )
    judgment = {"grade": "우선 검토", "readiness": "부분 확인 필요", "primary_focus": "AI/데이터", "summary": "요약", "next_action": "다음"}
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
    report_dir = root / "reports" / run_dir.name
    report_dir.mkdir(parents=True)
    (report_dir / "review-feedback.yaml").write_text(
        "schema_version: bidops.feedback.v2\nreviews:\n  - notice_id: bid:LC:000\n    disposition: 관찰\n",
        encoding="utf-8",
    )
    return run_dir


def test_judgment_ingest_is_skipped_with_a_warning_when_no_hook_is_registered(tmp_path, empty_extensions):
    run_dir = _write_run_with_judgment(tmp_path)
    with _session() as session:
        result = ingest_run(run_dir, session, reports_root=tmp_path / "reports")

        assert result.notices == 1
        assert result.judgments == 0
        assert result.reviews == 0
        assert result.generation_config is None
        skipped = [item for item in result.warnings if item["code"] == "judgment_ingest_skipped"]
        assert len(skipped) == 1 and skipped[0]["level"] == "warning"
        # 판정 계약 파싱은 lifecycle의 일이 아니므로 판정 관련 경고는 하나도 없다.
        assert not any(item["code"].startswith("judgment") and item["code"] != "judgment_ingest_skipped" for item in result.warnings)
        assert not any(item["code"] == "screening_results_missing" for item in result.warnings)
        run = session.get(Run, result.run_id)
        assert run is not None
        assert run.counts_json["notices"] == 1
        assert run.counts_json["judgments"] == 0 and run.counts_json["reviews"] == 0
        assert session.scalar(select(func.count()).select_from(Notice)) == 1
        stored = session.scalars(select(IngestWarning.code)).all()
        assert "judgment_ingest_skipped" in stored


def test_c2_only_directory_is_an_ordinary_run_directory_without_the_screening_hook(tmp_path, empty_extensions):
    run_dir, source_run_id = write_c2_fixture(tmp_path)
    with _session() as session:
        session.add(Run(id=source_run_id, timezone="Asia/Seoul", generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
        session.commit()

        result = ingest_run(run_dir, session)

        # C-2 결과로 인식되지 않았다: source run이 아니라 이 디렉터리 자신의 회차가 생긴다.
        assert result.run_id != source_run_id
        assert result.run_id.startswith(run_dir.name + "--")
        assert result.screening_executions == 0
        assert result.screening_results == 0
        assert result.screening_artifacts == 0
        assert session.get(Run, result.run_id) is not None
        assert session.scalar(select(func.count()).select_from(Notice)) == 0
        assert any(item["code"] == "judgment_ingest_skipped" for item in result.warnings)
