"""일일 수집 기준일 상태: 서버 판정 규칙과 REST 응답 (2026-11-20).

경계 사례는 계약 `docs/contracts/lifecycle-rest.md` "일일 수집 기준일 상태"의 규칙 그대로다:
자정 전후(한국 시간), 정오 유예, 기록 없음, 적재 경고, 실패(회차 행 없음), 트랙 한쪽만,
같은 디렉터리 재적재(`superseded`), 수동·참조 회차 제외.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.lifecycle.models import IngestWarning, Run
from app.lifecycle.routers import daily_collection as router_module
from app.lifecycle.services import daily_collection
from app.lifecycle.services.daily_collection import daily_collection_status, daily_run_basis_date, target_basis_date


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    try:
        with Session(engine) as value:
            yield value
    finally:
        engine.dispose()


def _run(session: Session, directory: str, generated_at: datetime, *, status: str = "active", warnings: int = 0) -> str:
    run_id = f"{directory}--{generated_at.strftime('%Y%m%dT%H%M%S')}Z"
    session.add(Run(id=run_id, generated_at=generated_at, status=status))
    session.flush()
    for index in range(warnings):
        session.add(IngestWarning(run_id=run_id, level="warning", code=f"fixture_{index}", message="fixture"))
    session.flush()
    return run_id


def _track(response, name):
    return next(item for item in response.tracks if item.track == name)


# --- 기준일 ---------------------------------------------------------------------


def test_daily_run_ids_are_parsed_per_track_and_other_runs_are_not_daily():
    assert daily_run_basis_date("lifecycle-20261118-plans--20261119T063000Z", "order-plans") == date(2026, 11, 18)
    assert daily_run_basis_date("lifecycle-20261118-plans-retry2--20261119T090000Z", "order-plans") == date(2026, 11, 18)
    assert daily_run_basis_date("lifecycle-20261118-notices--20261119T070000Z", "notices") == date(2026, 11, 18)
    assert daily_run_basis_date("lifecycle-20261118-notices--20261119T070000Z", "order-plans") is None
    # 수동 워크플로·참조 실행·게이트 표본 회차는 운영 수집이 아니다.
    for run_id in (
        "order-plans-20260910-20260911--20260912T000000Z",
        "order-plans-20260910-20260911-vllm-reference-8860c6cd--20260912T000000Z",
        "gate-gold-20260827-plans--20260828T000000Z",
        "lifecycle-20261318-plans--20261319T000000Z",  # 날짜가 아니다
    ):
        assert daily_run_basis_date(run_id, "order-plans") is None


@pytest.mark.parametrize(
    ("now", "has_yesterday", "expected"),
    [
        # 23:59:59 KST 11-19 → 전일 11-18(정오가 지났다).
        (datetime(2026, 11, 19, 14, 59, 59, tzinfo=UTC), False, date(2026, 11, 18)),
        # 00:00:00 KST 11-20 → 전일 11-19가 아직 없고 정오 전이라 그저께 11-18.
        (datetime(2026, 11, 19, 15, 0, 0, tzinfo=UTC), False, date(2026, 11, 18)),
        # 같은 시각이라도 전일 회차가 있으면 전일이다.
        (datetime(2026, 11, 19, 15, 0, 0, tzinfo=UTC), True, date(2026, 11, 19)),
        # 11:59:59 KST는 아직 유예, 12:00:00 KST부터는 전일을 요구한다.
        (datetime(2026, 11, 20, 2, 59, 59, tzinfo=UTC), False, date(2026, 11, 18)),
        (datetime(2026, 11, 20, 3, 0, 0, tzinfo=UTC), False, date(2026, 11, 19)),
    ],
)
def test_target_basis_date_is_kst_yesterday_with_morning_grace(now, has_yesterday, expected):
    yesterday = date(2026, 11, 19) if now >= datetime(2026, 11, 19, 15, tzinfo=UTC) else date(2026, 11, 18)
    assert target_basis_date(now, {yesterday} if has_yesterday else set()) == expected


# --- 상태 ------------------------------------------------------------------------


def test_no_records_are_missing_on_both_tracks_not_complete(session):
    response = daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC))
    assert [item.track for item in response.tracks] == ["order-plans", "notices"]
    for item in response.tracks:
        assert item.state == "missing"
        assert item.reasons == ["no_run"]
        assert item.basis_date == date(2026, 11, 19)
        assert item.run_id is None and item.collected_at is None
        assert item.warning_count is None  # 회차가 없으면 0이 아니라 null
        assert item.latest_basis_date is None
    assert response.today == date(2026, 11, 20)


def test_complete_incomplete_and_one_sided_tracks(session):
    plans = _run(session, "lifecycle-20261119-plans", datetime(2026, 11, 19, 21, 30, tzinfo=UTC))
    notices = _run(session, "lifecycle-20261119-notices", datetime(2026, 11, 19, 22, tzinfo=UTC), warnings=2)
    response = daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC))
    plan_status = _track(response, "order-plans")
    assert (plan_status.state, plan_status.reasons, plan_status.run_id, plan_status.warning_count) == ("complete", [], plans, 0)
    notice_status = _track(response, "notices")
    # 적재 경고가 있는 부분 산출물은 완료로 말하지 않는다.
    assert (notice_status.state, notice_status.reasons, notice_status.warning_count) == ("incomplete", ["ingest_warnings"], 2)
    assert notice_status.run_id == notices

    session.delete(session.get(Run, notices))
    session.flush()
    response = daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC))
    assert _track(response, "order-plans").state == "complete"
    assert _track(response, "notices").state == "missing"


def test_failed_collection_leaves_no_row_and_reads_missing_with_latest_basis(session):
    # 11-19 수집이 실패해 회차 행이 없고, 11-18 회차만 있다. 오후라 11-19를 요구한다.
    _run(session, "lifecycle-20261118-plans", datetime(2026, 11, 18, 21, 30, tzinfo=UTC))
    response = daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC))
    status = _track(response, "order-plans")
    assert (status.state, status.basis_date, status.latest_basis_date) == ("missing", date(2026, 11, 19), date(2026, 11, 18))


def test_morning_grace_judges_the_day_before_when_yesterday_is_not_collected_yet(session):
    previous = _run(session, "lifecycle-20261118-plans", datetime(2026, 11, 18, 21, 30, tzinfo=UTC))
    morning = datetime(2026, 11, 19, 22, tzinfo=UTC)  # 07:00 KST 11-20
    status = _track(daily_collection_status(session, now=morning), "order-plans")
    assert (status.state, status.basis_date, status.run_id) == ("complete", date(2026, 11, 18), previous)


def test_superseded_reingest_and_non_daily_runs_are_not_counted_and_latest_retry_wins(session):
    _run(session, "lifecycle-20261119-plans", datetime(2026, 11, 19, 21, tzinfo=UTC), status="superseded", warnings=3)
    _run(session, "order-plans-20261119-20261119", datetime(2026, 11, 19, 23, tzinfo=UTC))
    _run(session, "order-plans-20261119-20261119-vllm-reference-abc", datetime(2026, 11, 19, 23, 30, tzinfo=UTC))
    response = daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC))
    assert _track(response, "order-plans").state == "missing"

    _run(session, "lifecycle-20261119-plans", datetime(2026, 11, 19, 21, 30, tzinfo=UTC), warnings=1)
    retry = _run(session, "lifecycle-20261119-plans-retry1", datetime(2026, 11, 20, 1, tzinfo=UTC))
    status = _track(daily_collection_status(session, now=datetime(2026, 11, 20, 4, tzinfo=UTC)), "order-plans")
    assert (status.state, status.run_id, status.warning_count) == ("complete", retry, 0)


# --- REST ------------------------------------------------------------------------


def test_rest_response_shape_is_strict_and_read_only(session, monkeypatch):
    _run(session, "lifecycle-20261119-notices", datetime(2026, 11, 19, 22, tzinfo=UTC), warnings=1)
    session.commit()
    monkeypatch.setattr(daily_collection, "utc_now", lambda: datetime(2026, 11, 20, 4, tzinfo=UTC))
    application = FastAPI()
    application.include_router(router_module.router)

    def override_db():
        yield session

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as client:
        response = client.get("/api/daily-collection-status")
        assert response.status_code == 200
        assert response.json() == {
            "schema_version": "bidops.daily-collection-status.v1",
            "generated_at": "2026-11-20T04:00:00Z",
            "timezone": "Asia/Seoul",
            "today": "2026-11-20",
            "tracks": [
                {
                    "track": "order-plans",
                    "basis_date": "2026-11-19",
                    "state": "missing",
                    "reasons": ["no_run"],
                    "run_id": None,
                    "collected_at": None,
                    "warning_count": None,
                    "latest_basis_date": None,
                },
                {
                    "track": "notices",
                    "basis_date": "2026-11-19",
                    "state": "incomplete",
                    "reasons": ["ingest_warnings"],
                    "run_id": "lifecycle-20261119-notices--20261119T220000Z",
                    "collected_at": "2026-11-19T22:00:00Z",
                    "warning_count": 1,
                    "latest_basis_date": "2026-11-19",
                },
            ],
        }
        assert client.post("/api/daily-collection-status").status_code == 405
