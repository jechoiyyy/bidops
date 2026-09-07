"""회차 종류는 파일이나 과거 건수가 아니라 DB 관측 자료로 판별한다."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.lifecycle.models import Notice, NoticeObservation, OrderPlan, OrderPlanObservation, Run
from app.lifecycle.routers import common, runs


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


@pytest.fixture
def run_client(tmp_path, monkeypatch, empty_extensions):
    settings = SimpleNamespace(bidops_root=tmp_path)
    monkeypatch.setattr(common, "get_settings", lambda: settings)
    monkeypatch.setattr(runs, "get_settings", lambda: settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    try:
        with Session(engine) as session:
            application = FastAPI()
            application.include_router(runs.router)

            def override_db():
                yield session

            application.dependency_overrides[get_db] = override_db
            with TestClient(application) as client:
                yield client, session, tmp_path
    finally:
        engine.dispose()


def _add_runs(session, *, first=0, count=4):
    expected = {}
    kinds = ("order_plans", "notices", "mixed", "unknown")
    for index in range(first, first + count):
        kind = kinds[index % len(kinds)]
        run_id = f"kind-{index:03d}"
        run = Run(
            id=run_id,
            generated_at=NOW + timedelta(minutes=index),
            # 일부러 실제 관측과 다른 과거 집계를 준다.
            counts_json={"notices": 99, "order_plans": 99},
        )
        session.add(run)
        if kind in {"order_plans", "mixed"}:
            for number in range(2):
                plan = OrderPlan(order_plan_unty_no=f"{run_id}-plan-{number}")
                session.add(OrderPlanObservation(run=run, order_plan=plan))
        if kind in {"notices", "mixed"}:
            for number in range(2):
                notice = Notice(notice_key=f"{run_id}-notice-{number}")
                session.add(NoticeObservation(run=run, notice=notice))
        expected[run_id] = kind
    session.commit()
    return expected


def test_list_and_detail_return_all_four_observation_kinds_without_files(run_client):
    client, session, root = run_client
    expected = _add_runs(session)
    assert not (root / "data" / "runs").exists()

    response = client.get("/api/runs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert [item["run_id"] for item in payload["items"]] == list(reversed(expected))
    assert {item["run_id"]: item["kind"] for item in payload["items"]} == expected
    for run_id, kind in expected.items():
        detail = client.get(f"/api/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["kind"] == kind
        assert all(not artifact["present"] for artifact in detail.json()["artifacts"])


def test_files_do_not_turn_an_unobserved_run_into_a_known_kind(run_client):
    client, session, root = run_client
    _add_runs(session, first=3, count=1)
    directory = root / "data" / "runs" / "kind-003"
    directory.mkdir(parents=True)
    for filename in ("collected-order-plans.json", "collected-notices.json"):
        (directory / filename).write_text("{}", encoding="utf-8")

    assert client.get("/api/runs/kind-003").json()["kind"] == "unknown"
    assert client.get("/api/runs").json()["items"][0]["kind"] == "unknown"


def test_run_list_uses_two_grouped_observation_queries_for_small_and_large_lists(run_client):
    client, session, _root = run_client
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    counts = []
    for first, count in ((0, 4), (4, 17)):
        _add_runs(session, first=first, count=count)
        statements.clear()
        event.listen(session.get_bind(), "before_cursor_execute", record)
        try:
            response = client.get("/api/runs")
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", record)
        assert response.status_code == 200
        assert response.json()["total"] == first + count
        observations = [sql.lower() for sql in statements if "_observation" in sql.lower()]
        assert len(observations) == 2
        assert all("group by" in sql for sql in observations)
        assert sum("order_plan_observation" in sql for sql in observations) == 1
        assert sum("notice_observation" in sql for sql in observations) == 1
        counts.append(len(statements))
    assert counts == [3, 3]


def test_summary_requires_the_caller_to_provide_the_real_kind(run_client):
    _client, session, _root = run_client
    _add_runs(session, count=1)
    with pytest.raises(TypeError):
        common.run_summary(session.get(Run, "kind-000"))


def test_empty_run_list_and_missing_detail_keep_existing_contracts(run_client):
    client, _session, _root = run_client
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert client.get("/api/runs/missing").status_code == 404
