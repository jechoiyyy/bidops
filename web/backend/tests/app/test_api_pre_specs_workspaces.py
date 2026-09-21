"""Cumulative pre-spec workspace/filter contract tests.

These tests deliberately call the lifecycle router with a small in-memory DB.
The projection fake is batch-only so the cases exercise filtering, counts, and
pagination without coupling the lifecycle contract to deep_review storage.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import (
    ExtensionRegistry,
    PreSpecDocumentCounts,
    extension_registry,
    reset_extension_registry,
    restore_extension_registry,
)
from app.lifecycle.models import Notice, NoticeObservation, Opportunity, OpportunityLink, Run
from app.lifecycle.routers import pre_specs as pre_specs_router
from app.lifecycle.routers.pre_specs import list_pre_specs


SEOUL_RECENT_NOW = datetime(2026, 9, 16, 3, 0, tzinfo=UTC)


class _Projection:
    """Deterministic batch projection used by the lifecycle tests."""

    def __init__(self) -> None:
        self.statuses: dict[int, str] = {}
        self.fields: dict[int, Mapping[str, Any]] = {}
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        ids = tuple(int(value) for value in notice_ids)
        self.calls.append(("overview_status", ids))
        return {notice_id: self.statuses[notice_id] for notice_id in ids if notice_id in self.statuses}

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        ids = tuple(int(value) for value in notice_ids)
        self.calls.append(("overview_status_counts", ids))
        return Counter(self.statuses[notice_id] for notice_id in ids if notice_id in self.statuses)

    def document_counts(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, PreSpecDocumentCounts]:
        ids = tuple(int(value) for value in notice_ids)
        self.calls.append(("document_counts", ids))
        return {}

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        ids = tuple(int(value) for value in notice_ids)
        self.calls.append(("prespec_status_fields", ids))
        return {notice_id: self.fields[notice_id] for notice_id in ids if notice_id in self.fields}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def registry() -> ExtensionRegistry:
    previous = extension_registry()
    try:
        yield reset_extension_registry()
    finally:
        restore_extension_registry(previous)


def _list(session: Session, **params: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "notice_pk": None,
        "sw_only": False,
        "business_division": None,
        "origin": None,
        "auto_preparation_status": None,
        "workspace": "all",
        "overview_view": "all",
        "grade": None,
        "tracking_decision": None,
        "tracking_status": None,
        "source_run_id": None,
        "observed_from": None,
        "observed_to": None,
        "deadline_status": None,
        "q": None,
        "sort": "published",
        "limit": 50,
        "offset": 0,
    }
    values.update(params)
    return list_pre_specs(session=session, **values).model_dump(mode="json", by_alias=True)


def _notice(
    session: Session,
    key: str,
    *,
    deadline_at: datetime | None = None,
    published_at: datetime | None = None,
    sw_status: str | None = "Y",
) -> Notice:
    flags = {"sw_business_status": sw_status} if sw_status is not None else {}
    notice = Notice(
        notice_key=f"pre:{key}",
        source_type="pre_spec",
        title=f"{key} 제안요청서",
        agency="테스트 기관",
        published_at=published_at or datetime(2026, 9, 1, tzinfo=UTC),
        deadline_at=deadline_at,
        qualification_flags_json=flags,
        lifecycle_json={"pre_spec_no": key},
    )
    session.add(notice)
    session.flush()
    return notice


def _run(session: Session, run_id: str) -> Run:
    run = Run(id=run_id, generated_at=datetime(2026, 9, 1, tzinfo=UTC))
    session.add(run)
    session.flush()
    return run


def _observe(session: Session, notice: Notice, run: Run, observed_at: datetime) -> None:
    session.add(
        NoticeObservation(notice_id=notice.id, run_id=run.id, observed_at=observed_at)
    )
    session.flush()


def _tracking_link(
    session: Session,
    notice: Notice,
    *,
    first_stage: str = "pre_spec",
    tracking_status: str = "미선택",
) -> Opportunity:
    selected = tracking_status != "미선택"
    opportunity = Opportunity(
        first_registered_stage=first_stage,
        tracking_status=tracking_status,
        tracking_reason="테스트 추적 이유" if selected else None,
        tracking_selected_by="테스트 담당자" if selected else None,
        tracking_selected_at=(
            datetime(2026, 9, 1, tzinfo=UTC) if selected else None
        ),
    )
    session.add(opportunity)
    session.flush()
    session.add(
        OpportunityLink(
            opportunity_id=opportunity.id,
            notice_id=notice.id,
            stage="notice",
            link_type="official",
            status="확정",
            evidence_external_no=f"PRE-{notice.id}",
        )
    )
    session.flush()
    return opportunity


def test_provider_absent_is_null_and_actionable_fails_closed(db_session, registry):
    notice = _notice(db_session, "NO-PROVIDER")

    actionable = _list(db_session, workspace="actionable")
    not_started = _list(db_session, overview_view="not_started")

    assert actionable["total"] == 0
    assert actionable["items"] == []
    assert actionable["workspace_counts"] == {
        "actionable": 0,
        "recent": 0,
        "tracking": 0,
        "all": 1,
    }
    assert not_started["total"] == 1
    assert not_started["items"][0]["notice_pk"] == notice.id
    assert not_started["items"][0]["overview_review_status"] is None
    assert not_started["items"][0]["next_action"] is None
    # 기존 auto-preparation 필터의 제공자 부재 fail-closed 계약도 유지한다.
    assert _list(db_session, auto_preparation_status="not_applicable")["total"] == 0


def test_two_hundred_first_page_filters_before_paging(db_session, registry):
    projection = _Projection()
    registry.register_overview_document_projection(projection, owner="test")
    notices = [_notice(db_session, f"PAGE-{index:03d}") for index in range(201)]
    for index, notice in enumerate(notices):
        projection.statuses[notice.id] = "completed"
        projection.fields[notice.id] = {
            "grade": "우선 검토" if index < 2 else "제외",
            "grade_source": "screening_judgment",
            "auto_preparation_status": "not_applicable",
        }
    db_session.commit()

    page = _list(db_session, limit=200, offset=0)
    narrowed = _list(db_session, grade="우선 검토", limit=200, offset=0)

    assert page["total"] == 201
    assert len(page["items"]) == 200
    assert page["workspace_counts"]["all"] == 201
    assert narrowed["total"] == 2
    assert len(narrowed["items"]) == 2
    assert {item["grade"] for item in narrowed["items"]} == {"우선 검토"}


def test_observation_runs_overlap_and_keep_current_notice_data(db_session, registry):
    first_run = _run(db_session, "run-old")
    second_run = _run(db_session, "run-new")
    old_only = _notice(db_session, "OLD-ONLY")
    overlapping = _notice(db_session, "OVERLAP")
    _observe(db_session, old_only, first_run, datetime(2026, 9, 9, 14, 59, tzinfo=UTC))
    _observe(db_session, overlapping, first_run, datetime(2026, 9, 9, 14, 59, tzinfo=UTC))
    # 2026-09-09 15:00 UTC is exactly 2026-09-10 00:00 in Seoul and must be
    # included by an observed_from/to range for that calendar date.
    _observe(db_session, overlapping, second_run, datetime(2026, 9, 9, 15, 0, tzinfo=UTC))
    overlapping.title = "현재 공고 제목"
    db_session.commit()

    in_day = _list(
        db_session,
        observed_from=date(2026, 9, 10),
        observed_to=date(2026, 9, 10),
    )
    run_old = _list(
        db_session,
        source_run_id="run-old",
        observed_from="2026-09-10",
        observed_to="2026-09-10",
    )
    run_new = _list(db_session, source_run_id="run-new")

    assert [item["notice_pk"] for item in in_day["items"]] == [overlapping.id]
    assert run_old["total"] == 0
    assert run_new["total"] == 1
    item = run_new["items"][0]
    assert item["title"] == "현재 공고 제목"
    assert item["first_observed_at"].startswith("2026-09-09T14:59")
    assert item["last_observed_at"].startswith("2026-09-09T15:00")


def test_recent_uses_any_observation_and_source_run_for_workspace_count(db_session, registry, monkeypatch):
    monkeypatch.setattr(pre_specs_router, "_now_utc", lambda: SEOUL_RECENT_NOW)
    recent = _notice(db_session, "RECENT")
    old = _notice(db_session, "OLD")
    no_observation = _notice(db_session, "NONE")
    recent_run = _run(db_session, "run-recent")
    old_run = _run(db_session, "run-old")
    _observe(db_session, recent, old_run, datetime(2026, 9, 9, 14, 59, tzinfo=UTC))
    _observe(db_session, recent, recent_run, datetime(2026, 9, 10, 15, 1, tzinfo=UTC))
    _observe(db_session, old, old_run, datetime(2026, 9, 9, 14, 59, tzinfo=UTC))
    db_session.commit()

    recent_payload = _list(db_session, workspace="recent")
    recent_run_payload = _list(
        db_session,
        workspace="recent",
        source_run_id="run-recent",
    )
    all_payload = _list(db_session)

    assert [item["notice_pk"] for item in recent_payload["items"]] == [recent.id]
    assert [item["notice_pk"] for item in recent_run_payload["items"]] == [recent.id]
    assert all_payload["workspace_counts"] == {
        "actionable": 0,
        "recent": 1,
        "tracking": 0,
        "all": 3,
    }
    assert recent_payload["workspace_counts"]["all"] == 3


def test_actionable_union_next_action_and_compact_overview_views(db_session, registry):
    projection = _Projection()
    registry.register_overview_document_projection(projection, owner="test")
    attention = _notice(db_session, "ATTENTION")
    deep_review = _notice(db_session, "DEEP-REVIEW")
    decision = _notice(db_session, "DECISION")
    tracked = _notice(db_session, "TRACKED")
    pending = _notice(db_session, "PENDING")
    not_started = _notice(db_session, "NOT-STARTED")
    _tracking_link(db_session, decision, tracking_status="미선택")
    _tracking_link(db_session, tracked, tracking_status="계속 추적")
    projection.statuses.update(
        {
            attention.id: "needs_human_review",
            deep_review.id: "running",
            decision.id: "completed",
            tracked.id: "completed",
            pending.id: "queued",
        }
    )
    projection.fields.update(
        {
            attention.id: {"auto_preparation_status": "bundle_ready"},
            deep_review.id: {"auto_preparation_status": "deep_review_ready_for_click"},
            decision.id: {"auto_preparation_status": "not_applicable"},
            tracked.id: {"auto_preparation_status": "not_applicable"},
            pending.id: {"auto_preparation_status": "not_applicable"},
        }
    )
    db_session.commit()

    actionable = _list(db_session, workspace="actionable")
    pending_view = _list(db_session, overview_view="pending")
    completed_view = _list(db_session, overview_view="completed")
    not_started_view = _list(db_session, overview_view="not_started")

    actionable_by_id = {item["notice_pk"]: item for item in actionable["items"]}
    assert set(actionable_by_id) == {attention.id, deep_review.id, decision.id}
    assert actionable_by_id[attention.id]["next_action"] == "confirm_overview"
    assert actionable_by_id[deep_review.id]["next_action"] == "open_deep_review"
    assert actionable_by_id[decision.id]["next_action"] == "decide_tracking"
    assert [item["notice_pk"] for item in pending_view["items"]] == [pending.id, deep_review.id]
    assert {item["notice_pk"] for item in completed_view["items"]} == {decision.id, tracked.id}
    assert [item["notice_pk"] for item in not_started_view["items"]] == [not_started.id]


def test_tracking_decision_grade_and_tracking_workspace_filters(db_session, registry):
    projection = _Projection()
    registry.register_overview_document_projection(projection, owner="test")
    pending = _notice(db_session, "TRACKING-PENDING")
    held = _notice(db_session, "TRACKING-HELD")
    closed = _notice(db_session, "TRACKING-CLOSED")
    no_grade = _notice(db_session, "NO-GRADE")
    _tracking_link(db_session, pending, tracking_status="미선택")
    _tracking_link(db_session, held, tracking_status="보류")
    _tracking_link(db_session, closed, tracking_status="종료")
    projection.fields[no_grade.id] = {"grade": None}
    projection.fields[pending.id] = {"grade": "우선 검토"}
    projection.fields[held.id] = {"grade": "검토 권장"}
    projection.fields[closed.id] = {"grade": "제외"}
    db_session.commit()

    pending_payload = _list(db_session, tracking_decision="pending")
    tracking_payload = _list(db_session, workspace="tracking")
    grade_payload = _list(db_session, grade="판정 없음")

    assert [item["notice_pk"] for item in pending_payload["items"]] == [pending.id]
    assert {item["notice_pk"] for item in tracking_payload["items"]} == {held.id}
    assert [item["notice_pk"] for item in _list(db_session, tracking_status="보류")["items"]] == [held.id]
    assert [item["notice_pk"] for item in grade_payload["items"]] == [no_grade.id]


def test_deadline_and_observed_sorts_and_deadline_buckets(db_session, registry, monkeypatch):
    monkeypatch.setattr(pre_specs_router, "_now_utc", lambda: SEOUL_RECENT_NOW)
    future_near = _notice(
        db_session, "FUTURE-NEAR", deadline_at=SEOUL_RECENT_NOW + timedelta(days=1)
    )
    future_far = _notice(
        db_session, "FUTURE-FAR", deadline_at=SEOUL_RECENT_NOW + timedelta(days=2)
    )
    past_old = _notice(
        db_session, "PAST-OLD", deadline_at=SEOUL_RECENT_NOW - timedelta(days=2)
    )
    past_recent = _notice(
        db_session, "PAST-RECENT", deadline_at=SEOUL_RECENT_NOW - timedelta(days=1)
    )
    unknown = _notice(db_session, "DEADLINE-UNKNOWN", deadline_at=None)
    run = _run(db_session, "observed-sort")
    _observe(db_session, future_far, run, datetime(2026, 9, 12, tzinfo=UTC))
    _observe(db_session, future_near, run, datetime(2026, 9, 14, tzinfo=UTC))
    _observe(db_session, unknown, run, datetime(2026, 9, 13, tzinfo=UTC))
    db_session.commit()

    deadline = _list(db_session, sort="deadline")
    observed = _list(db_session, sort="observed")
    assert [item["notice_pk"] for item in deadline["items"]] == [
        future_near.id,
        future_far.id,
        past_recent.id,
        past_old.id,
        unknown.id,
    ]
    assert [item["notice_pk"] for item in observed["items"]][:3] == [
        future_near.id,
        unknown.id,
        future_far.id,
    ]
    assert {item["notice_pk"] for item in _list(db_session, deadline_status="open")["items"]} == {
        future_near.id,
        future_far.id,
    }
    assert {item["notice_pk"] for item in _list(db_session, deadline_status="passed")["items"]} == {
        past_old.id,
        past_recent.id,
    }
    assert [item["notice_pk"] for item in _list(db_session, deadline_status="unknown")["items"]] == [
        unknown.id
    ]


def _scope_fixture(db_session, registry):
    """ADR-0064 구간 분할용 고정 표본.

    actionable 3건(미래 마감·과거 마감·마감 미확인)과, 구간 분할의 분모에 들어가서는
    안 되는 검토 제외 actionable 1건, actionable이 아닌 과거 마감 1건이다.
    """

    projection = _Projection()
    registry.register_overview_document_projection(projection, owner="test")
    future = _notice(
        db_session, "SCOPE-FUTURE", deadline_at=SEOUL_RECENT_NOW + timedelta(days=1)
    )
    past = _notice(db_session, "SCOPE-PAST", deadline_at=SEOUL_RECENT_NOW - timedelta(days=1))
    unknown = _notice(db_session, "SCOPE-UNKNOWN", deadline_at=None)
    excluded = _notice(
        db_session, "SCOPE-EXCLUDED", deadline_at=SEOUL_RECENT_NOW - timedelta(days=2)
    )
    # 제외 행은 `ck_notice_review_exclusion_metadata`가 요구하는 담당자·사유·시각을
    # 함께 채워야 한다. 담당자 이름은 감사 표식이지 인증이 아니다.
    excluded.review_exclusion_status = "excluded"
    excluded.review_exclusion_actor_name = "테스트 담당자"
    excluded.review_exclusion_reason = "구간 분할 분모 제외 확인"
    excluded.review_exclusion_changed_at = SEOUL_RECENT_NOW
    inactive = _notice(
        db_session, "SCOPE-INACTIVE", deadline_at=SEOUL_RECENT_NOW - timedelta(days=3)
    )
    for notice in (future, past, unknown, excluded):
        projection.statuses[notice.id] = "needs_human_review"
        projection.fields[notice.id] = {"auto_preparation_status": "bundle_ready"}
    projection.statuses[inactive.id] = "queued"
    projection.fields[inactive.id] = {"auto_preparation_status": "not_applicable"}
    db_session.commit()
    return projection, future, past, unknown, excluded, inactive


def test_deadline_scope_splits_actionable_only_and_keeps_unknown(
    db_session, registry, monkeypatch
):
    monkeypatch.setattr(pre_specs_router, "_now_utc", lambda: SEOUL_RECENT_NOW)
    _projection, future, past, unknown, excluded, inactive = _scope_fixture(db_session, registry)

    current = _list(db_session, workspace="actionable", deadline_scope="current")
    passed = _list(db_session, workspace="actionable", deadline_scope="passed")
    # 인자를 생략하면 기본 `all`이고 구간 이전의 actionable 전체가 남는다.
    default = _list(db_session, workspace="actionable")

    assert {item["notice_pk"] for item in current["items"]} == {future.id, unknown.id}
    assert current["total"] == 2
    assert [item["notice_pk"] for item in passed["items"]] == [past.id]
    assert passed["total"] == 1
    assert {item["notice_pk"] for item in default["items"]} == {future.id, past.id, unknown.id}
    assert default["total"] == 3

    # deadline_scope_counts는 구간 적용 **전** actionable을 둘로 나눈 값이라
    # 활성 구간이 무엇이든 세 호출에서 같다.
    for payload in (current, passed, default):
        assert payload["deadline_scope_counts"] == {"current": 2, "passed": 1}
        # 계약 항등식: 두 칸의 합 == 구간 미적용 actionable 건수.
        assert (
            payload["deadline_scope_counts"]["current"]
            + payload["deadline_scope_counts"]["passed"]
            == default["total"]
        )

    # actionable 칸만 구간을 따라 움직이고 나머지 세 칸은 구조적으로 불변이다.
    assert current["workspace_counts"]["actionable"] == 2
    assert passed["workspace_counts"]["actionable"] == 1
    assert default["workspace_counts"]["actionable"] == 3
    assert current["workspace_counts"]["actionable"] == current["deadline_scope_counts"]["current"]
    for key in ("recent", "tracking", "all"):
        assert (
            current["workspace_counts"][key]
            == passed["workspace_counts"][key]
            == default["workspace_counts"][key]
        )

    # 다른 workspace의 items·total은 구간에 영향받지 않지만 actionable 칸은 적용된다.
    all_default = _list(db_session, workspace="all")
    all_current = _list(db_session, workspace="all", deadline_scope="current")
    assert [item["notice_pk"] for item in all_current["items"]] == [
        item["notice_pk"] for item in all_default["items"]
    ]
    assert all_current["total"] == all_default["total"] == 5
    assert all_current["workspace_counts"]["actionable"] == 2

    # 검토 제외 건은 어느 구간에도, deadline_scope_counts 어느 칸에도 없다.
    excluded_ids = {excluded.id}
    for payload in (current, passed, default):
        assert excluded_ids.isdisjoint({item["notice_pk"] for item in payload["items"]})
    assert inactive.id not in {item["notice_pk"] for item in default["items"]}
    assert all_current["deadline_scope_counts"] == {"current": 2, "passed": 1}

    for payload in (current, passed, default):
        assert sum(entry["count"] for entry in payload["overview_status_counts"]) == payload["total"]


def test_deadline_scope_pages_and_sorts_before_pagination(db_session, registry, monkeypatch):
    monkeypatch.setattr(pre_specs_router, "_now_utc", lambda: SEOUL_RECENT_NOW)
    projection, future, past, unknown, _excluded, _inactive = _scope_fixture(db_session, registry)
    # 마감 경과 구간의 정렬(최근 경과순)을 실제로 증명하려면 경과 actionable이 둘 필요하다.
    older_past = _notice(
        db_session, "SCOPE-PAST-OLD", deadline_at=SEOUL_RECENT_NOW - timedelta(days=5)
    )
    projection.statuses[older_past.id] = "needs_human_review"
    projection.fields[older_past.id] = {"auto_preparation_status": "bundle_ready"}
    db_session.commit()

    second_page = _list(
        db_session,
        workspace="actionable",
        deadline_scope="current",
        sort="deadline",
        limit=1,
        offset=1,
    )
    # 구간은 페이지 분할 전에 적용된다 — total은 구간 건수 그대로이고 두 번째 행이 나온다.
    assert second_page["total"] == 2
    assert [item["notice_pk"] for item in second_page["items"]] == [unknown.id]
    assert second_page["deadline_scope_counts"] == {"current": 2, "passed": 2}

    first_page = _list(
        db_session,
        workspace="actionable",
        deadline_scope="current",
        sort="deadline",
        limit=1,
        offset=0,
    )
    assert [item["notice_pk"] for item in first_page["items"]] == [future.id]

    # 마감 경과 구간은 기존 정렬 규칙대로 최근 경과순이다.
    passed_sorted = _list(
        db_session, workspace="actionable", deadline_scope="passed", sort="deadline"
    )
    assert [item["notice_pk"] for item in passed_sorted["items"]] == [past.id, older_past.id]

    # deadline_status는 여전히 모든 집계에 걸리는 전역 필터다. 구간과 모순되면 0건이지만
    # deadline_scope_counts는 그 전역 필터를 반영한 채로 분할을 유지한다.
    contradiction = _list(
        db_session,
        workspace="actionable",
        deadline_status="passed",
        deadline_scope="current",
    )
    assert contradiction["total"] == 0
    assert contradiction["deadline_scope_counts"] == {"current": 0, "passed": 2}

    with pytest.raises(HTTPException) as invalid:
        _list(db_session, deadline_scope="bogus")
    assert invalid.value.status_code == 422
    assert invalid.value.detail == "deadline_scope is invalid"
