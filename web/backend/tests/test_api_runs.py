from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.models import IngestWarning, Judgment, Notice, Run


@pytest.fixture
def runs_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="runs-test",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            counts_json={
                "notices": 3,
                "judgments": 3,
                "collection": {"total": 100, "candidate_pool": 20, "audit_pool": 80},
            },
        )
        for index, (role, grade) in enumerate(
            [("analysis", "우선 검토"), ("analysis", "제외"), ("audit", "검토 권장")],
            start=1,
        ):
            notice = Notice(
                run=run,
                notice_key=f"bid:RUN:{index:03d}",
                title=f"공고 {index}",
                agency="기관",
                sample_role=role,
                deadline_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            )
            session.add(Judgment(notice=notice, grade=grade, readiness="부분 확인 필요"))
        session.add(run)
        session.flush()
        session.add(
            IngestWarning(
                run_id=run.id,
                level="warning",
                code="test_warning",
                message="테스트 경고",
                context_json={"field": "x"},
            )
        )
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_run_list_detail_warnings_and_stats(runs_client):
    assert runs_client.get("/api/runs").json()["total"] == 1
    detail = runs_client.get("/api/runs/runs-test")
    assert detail.status_code == 200
    assert detail.json()["counts"]["collection"]["candidate_pool"] == 20
    assert runs_client.get("/api/runs/runs-test/warnings?level=warning").json()["total"] == 1
    stats = runs_client.get("/api/runs/runs-test/stats").json()
    assert stats["collected_count"] == 100
    assert stats["priority_review_count"] == 1
    assert stats["audit_missed_count"] == 1


def test_missing_run_is_404(runs_client):
    assert runs_client.get("/api/runs/does-not-exist").status_code == 404
    assert runs_client.get("/api/metrics/validation?run_id=does-not-exist").status_code == 404
