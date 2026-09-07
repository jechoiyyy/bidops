"""실제 PostgreSQL에서 회차 통계의 중복 제거와 공고 순서를 검증한다."""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.lifecycle import runs_router
from app.lifecycle.models import Notice, NoticeObservation, Run
from app.screening.models import Judgment, VerificationItem
from tests.postgres import migrated_engine, requires_postgres


@requires_postgres
def test_run_stats_returns_200_and_preserves_order_on_postgres(screening_extensions):
    with migrated_engine() as engine:
        assert engine.get_execution_options()["schema_translate_map"] == {None: "bidops"}
        with Session(engine) as session:
            assert int(session.scalar(text("SHOW server_version_num"))) // 10_000 == 17
            now = datetime(2026, 9, 7, tzinfo=timezone.utc)
            run = Run(id="stats-postgres", generated_at=now)
            other = Run(id="stats-other", generated_at=now - timedelta(days=7))
            session.add_all([run, other])
            notices = [
                Notice(notice_key=f"stats-{index}", sample_role=role, deadline_at=now + timedelta(days=1))
                for index, role in enumerate(("analysis", "analysis", "audit", "analysis"))
            ]
            session.add_all(notices)
            session.flush()
            session.add_all(NoticeObservation(run=run, notice=notice) for notice in notices[:3])
            session.add_all(NoticeObservation(run=other, notice=notice) for notice in notices)
            # 판정 PK와 공고 PK의 순서를 다르게 하여 정렬 기준을 검증한다.
            for index in (3, 2, 1, 0):
                judgment = Judgment(
                    notice=notices[index],
                    grade="우선 검토" if index == 0 else "검토 권장",
                    readiness="부분 확인 필요",
                    primary_focus="AI/데이터",
                )
                judgment.verification_items.append(
                    VerificationItem(item="참가자격", why="확인 필요", blocking=True, status="미확인")
                )
                session.add(judgment)
                session.flush()
            session.commit()
            notice_ids = [notice.id for notice in notices]

            application = FastAPI()
            application.include_router(runs_router)

            def override_db():
                yield session

            application.dependency_overrides[get_db] = override_db
            with TestClient(application, raise_server_exceptions=False) as client:
                response = client.get("/api/runs/stats-postgres/stats")

            assert response.status_code == 200, response.text
            stats = response.json()
            assert stats["sample_count"] == 3
            assert stats["collected_count"] is None
            assert stats["candidate_count"] is None
            assert stats["priority_review_count"] == 1
            assert stats["audit_missed_count"] == 1
            assert [(item["key"], item["count"]) for item in stats["grade_distribution"]] == [
                ("우선 검토", 1), ("검토 권장", 1)
            ]
            assert stats["verification_requests"] == [
                {"item": "참가자격", "count": 2, "notice_pks": notice_ids[:2], "profile_sections": []}
            ]
            assert [notice["id"] for notice in stats["imminent_deadlines"]] == notice_ids[:3]
            assert all(notice["blocking_verification_items"] == ["참가자격"] for notice in stats["imminent_deadlines"])
