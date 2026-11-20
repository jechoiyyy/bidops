"""일일 수집 기준일 상태의 PostgreSQL 변형 (2026-11-20, strict dict).

migration head를 적용한 일회용 PostgreSQL에서 조립된 앱(`create_app`)의 실제 경로로 부른다.
`timestamptz` 왕복(마이크로초·UTC 표기), 적재 경고 group-by, `superseded` 제외, 자정 직후(한국
시간) 정오 유예를 SQLite가 아닌 운영 DB 방언에서 확인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.lifecycle.models import IngestWarning, Run
from app.lifecycle.services import daily_collection
from app.main import create_app
from tests.postgres import migrated_engine, requires_postgres

pytestmark = requires_postgres


@pytest.fixture(scope="module")
def pg_engine():
    with migrated_engine() as engine:
        yield engine


@pytest.fixture
def session(pg_engine):
    with pg_engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as value:
                yield value
        finally:
            outer.rollback()


def _get(session: Session, now: datetime, monkeypatch) -> dict:
    monkeypatch.setattr(daily_collection, "utc_now", lambda: now)
    application = create_app(modules=("lifecycle",), mount_frontend=False)
    application.dependency_overrides[get_db] = lambda: session
    with TestClient(application) as client:
        response = client.get("/api/daily-collection-status")
    assert response.status_code == 200, response.text
    return response.json()


def test_postgres_states_and_strict_shape(session, monkeypatch) -> None:
    collected = datetime(2026, 11, 19, 21, 30, 1, 123456, tzinfo=UTC)
    plans = "lifecycle-20261119-plans--20261119T213001Z"
    session.add_all([
        Run(id=plans, generated_at=collected, status="active"),
        # 같은 디렉터리를 다시 적재해 밀려난 행은 세지 않는다.
        Run(id="lifecycle-20261119-notices--20261119T200000Z", generated_at=datetime(2026, 11, 19, 20, tzinfo=UTC), status="superseded"),
        Run(id="lifecycle-20261118-notices--20261118T220000Z", generated_at=datetime(2026, 11, 18, 22, tzinfo=UTC), status="active"),
    ])
    session.flush()
    session.add_all([
        IngestWarning(run_id="lifecycle-20261118-notices--20261118T220000Z", level="warning", code="a", message="fixture"),
        IngestWarning(run_id="lifecycle-20261118-notices--20261118T220000Z", level="error", code="b", message="fixture"),
    ])
    session.flush()

    # 00:30 KST 11-20: 공고 전일(11-19) 회차는 밀려난 행뿐이라 정오 전 유예로 11-18을 본다.
    body = _get(session, datetime(2026, 11, 19, 15, 30, tzinfo=UTC), monkeypatch)
    assert body == {
        "schema_version": "bidops.daily-collection-status.v1",
        "generated_at": "2026-11-19T15:30:00Z",
        "timezone": "Asia/Seoul",
        "today": "2026-11-20",
        "tracks": [
            {
                "track": "order-plans",
                "basis_date": "2026-11-19",
                "state": "complete",
                "reasons": [],
                "run_id": plans,
                "collected_at": "2026-11-19T21:30:01.123456Z",
                "warning_count": 0,
                "latest_basis_date": "2026-11-19",
            },
            {
                "track": "notices",
                "basis_date": "2026-11-18",
                "state": "incomplete",
                "reasons": ["ingest_warnings"],
                "run_id": "lifecycle-20261118-notices--20261118T220000Z",
                "collected_at": "2026-11-18T22:00:00Z",
                "warning_count": 2,
                "latest_basis_date": "2026-11-18",
            },
        ],
    }

    # 정오가 지나면 공고도 11-19를 요구하고, 그 기준일의 유효한 회차가 없으면 기록 없음이다.
    body = _get(session, datetime(2026, 11, 20, 3, tzinfo=UTC), monkeypatch)
    notices = body["tracks"][1]
    assert (notices["basis_date"], notices["state"], notices["reasons"], notices["warning_count"]) == (
        "2026-11-19", "missing", ["no_run"], None,
    )
