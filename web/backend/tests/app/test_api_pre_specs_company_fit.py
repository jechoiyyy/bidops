"""`GET /api/pre-specs`의 회사 핏 요약·`sort=fit`·`company_fit` 필터 (PS-01 C6·C7, T10).

lifecycle 목록 router와 deep_review 개요·문서 projection을 함께 도는 조합 테스트다.
조립 계층(`app.main`)이 확장점을 등록한다. 같은 시나리오를 SQLite와 PostgreSQL 17에서
돌린다(응답 shape 변경, VALUES join 정렬).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app  # noqa: F401 — 조립 계층이 lifecycle 확장점을 등록한다
from app.core.config import get_settings
from app.core.db import init_db
from app.lifecycle.routers import pre_specs as pre_specs_router
from tests.app.test_api_pre_specs import _payload
from tests.deep_review.company_fit_card_fixtures import (
    NOW,
    add_notice,
    add_overview_run,
    card_env,
    card_input,
    card_output,
    store_card_attempt,
)
from tests.postgres import migrated_engine, requires_postgres


@contextmanager
def _sqlite():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _world(session, tmp_path, monkeypatch):
    """네 그룹과 마감 전·경과·미확인을 섞은 공고. 이름 → id."""

    card_env(monkeypatch, tmp_path)
    monkeypatch.setattr(pre_specs_router, "_now_utc", lambda: NOW)
    from app.deep_review.services import auto_preparation

    monkeypatch.setattr(auto_preparation, "effective_grades", lambda s, ids: {})
    day = timedelta(days=1)
    spec = {
        # 이름: (마감, 카드 attempt 상태, 판정)
        "m_soon": (NOW + 2 * day, "completed", "matched"),
        "m_null": (None, "completed", "matched"),
        "m_passed": (NOW - day, "completed", "matched"),
        "u_soon": (NOW + day, "completed", "unknown"),
        "x_soon": (NOW + day, "completed", "mismatch"),
        "p_none": (NOW + timedelta(hours=1), None, None),
        "p_running": (NOW + 3 * day, "running", None),
        "p_failed": (NOW + 4 * day, "failed", None),
        "p_review": (NOW + 5 * day, "needs_human_review", None),
        "p_stale": (None, "completed", "matched"),
    }
    ids: dict[str, int] = {}
    notices = {}
    for name, (deadline, _status, _decision) in spec.items():
        notices[name] = add_notice(session, title=f"카드 {name}", deadline=deadline)
        ids[name] = notices[name].id
    session.commit()
    for name, (_deadline, status, decision) in spec.items():
        if status is None:
            continue
        inputs = card_input(session, notices[name])
        store_card_attempt(session, inputs, status=status,
                           result=card_output(decision) if decision else None)
    # stale: 완료 이후 새 개요 run이 현재가 됐다.
    add_overview_run(session, notices["p_stale"], created_at=NOW + day)
    session.commit()
    get_settings.cache_clear()
    return ids


EXPECTED_ORDER = [
    "m_soon", "m_passed", "m_null",       # matched: 마감 전 asc → 경과 desc → 미확인
    "u_soon",                               # unknown
    "p_none", "p_running", "p_failed", "p_review", "p_stale",  # pending
    "x_soon",                               # mismatch
]


def _check(session, ids):
    by_id = {value: key for key, value in ids.items()}
    names = lambda payload: [by_id[item["notice_pk"]] for item in payload["items"]]  # noqa: E731

    full = _payload(session, sort="fit", limit=500)
    assert names(full) == EXPECTED_ORDER and full["total"] == len(EXPECTED_ORDER)
    # limit 경계를 넘는 페이지가 이어진다.
    pages = [names(_payload(session, sort="fit", limit=4, offset=offset)) for offset in (0, 4, 8)]
    assert sum(pages, []) == EXPECTED_ORDER

    items = {by_id[item["notice_pk"]]: item for item in full["items"]}
    assert items["m_soon"]["company_fit"] == {"group": "matched", "decision": "matched", "status": "completed",
                                              "is_current": True, "engine_suggested": True}
    assert items["x_soon"]["company_fit"]["group"] == "mismatch"
    assert items["x_soon"]["company_fit"]["engine_suggested"] is False
    assert items["p_none"]["company_fit"] == {"group": "pending", "decision": None, "status": None,
                                              "is_current": False, "engine_suggested": False}
    assert items["p_running"]["company_fit"]["status"] == "running"
    assert items["p_review"]["company_fit"]["status"] == "needs_human_review"
    # stale: 판정은 남지만 그룹은 pending이고 추천하지 않는다.
    assert items["p_stale"]["company_fit"] == {"group": "pending", "decision": "matched", "status": "completed",
                                               "is_current": False, "engine_suggested": False}

    pending = _payload(session, company_fit="pending", sort="fit", limit=500)
    assert set(names(pending)) == {"p_none", "p_running", "p_failed", "p_review", "p_stale"}
    assert pending["total"] == 5 and pending["workspace_counts"]["all"] == 5
    matched = _payload(session, company_fit="matched", sort="deadline")
    assert names(matched) == ["m_soon", "m_passed", "m_null"] and matched["total"] == 3
    with pytest.raises(HTTPException) as error:
        _payload(session, company_fit="maybe")
    assert error.value.status_code == 422 and error.value.detail == "company_fit is invalid"
    # 다른 정렬은 그대로다.
    deadline = _payload(session, sort="deadline", limit=500)
    assert names(deadline)[:3] == ["p_none", "u_soon", "x_soon"]


def test_t10_fit_sort_filter_and_summary_sqlite(tmp_path, monkeypatch):
    with _sqlite() as engine, Session(engine) as session:
        _check(session, _world(session, tmp_path, monkeypatch))


@requires_postgres
def test_t10_fit_sort_filter_and_summary_postgres(tmp_path, monkeypatch):
    with migrated_engine() as engine, Session(engine) as session:
        _check(session, _world(session, tmp_path, monkeypatch))


def test_t10_without_the_projection_everything_is_pending(tmp_path, monkeypatch, empty_extensions):
    with _sqlite() as engine, Session(engine) as session:
        ids = _world(session, tmp_path, monkeypatch)
        by_id = {value: key for key, value in ids.items()}
        fit_sorted = _payload(session, sort="fit", limit=500)
        deadline_sorted = _payload(session, sort="deadline", limit=500)
        assert [item["notice_pk"] for item in fit_sorted["items"]] == [
            item["notice_pk"] for item in deadline_sorted["items"]]
        assert all(item["company_fit"] is None for item in fit_sorted["items"])
        assert _payload(session, company_fit="pending")["total"] == len(ids)
        assert _payload(session, company_fit="matched")["total"] == 0
        assert by_id  # 사용한 공고 수 = 전체
