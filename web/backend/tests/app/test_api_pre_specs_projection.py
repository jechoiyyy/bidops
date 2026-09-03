"""`GET /api/pre-specs`가 개요·문서 projection(deep_review)과 결합된 결과 (명세 §6.1).

lifecycle 목록 router와 deep_review가 제공하는 projection을 함께 도는 두 모듈
조합 테스트다. 조립 계층(`app.main`)이 확장점을 등록해야 projection이 붙으므로
여기서 앱 모듈을 import한다.

`test_pre_specs_list_matches_captured_baseline`은 projection으로 뒤집기 **전**의
router가 같은 fixture로 낸 응답(`tests/fixtures/pre_specs_list_baseline.json`)과
지금 응답이 정확히 같다는 근거다. 목록·그룹핑·필터·페이지네이션 출력이 바뀌지
않았음을 이 한 테스트가 보증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import event

from app.main import app  # noqa: F401 — 조립 계층이 lifecycle 확장점을 등록한다
from app.models import PreSpecOverviewReview
from tests.test_api_pre_specs import _items_by_id, _payload, pre_specs_api  # noqa: F401

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pre_specs_list_baseline.json"

_ALL_OVERVIEW_STATUSES = (
    "awaiting_document",
    "awaiting_structure",
    "preparing",
    "awaiting_model",
    "queued",
    "running",
    "needs_human_review",
    "completed",
    "failed",
    "cancelled",
)


def _add_overview_rows(session, refs) -> None:
    session.add(
        PreSpecOverviewReview(notice_id=refs["sw_yes"].id, status="needs_human_review")
    )
    session.add(
        PreSpecOverviewReview(
            notice_id=refs["sw_no"].id,
            status="completed",
            result="추진 검토",
            completed_at=datetime(2026, 8, 25, tzinfo=UTC),
        )
    )
    session.commit()


def capture_scenarios(session, refs) -> dict[str, dict]:
    """기준선 파일과 같은 순서로 목록 응답을 모은다.

    앞부분은 개요 검토 행이 없는 상태, `reviewed_*`는 두 공고에 개요 검토 행을
    넣은 뒤의 응답이다. 같은 fixture에서 id가 결정적이므로 응답을 그대로 비교한다.
    """

    scenarios: dict[str, dict] = {
        "default": {},
        "all": {"sw_only": False},
        "notice_pk": {"notice_pk": refs["sw_no"].id},
        "division": {"sw_only": False, "business_division": "기술용역"},
        "origin_tracked": {"sw_only": False, "origin": "추적"},
        "origin_new": {"sw_only": False, "origin": "신규"},
        "search": {"sw_only": False, "q": "다라마"},
        "deadline": {"sw_only": False, "sort": "deadline"},
        "page": {"sw_only": False, "sort": "published", "limit": 2, "offset": 2},
    }
    captured = {name: _payload(session, **params) for name, params in scenarios.items()}
    _add_overview_rows(session, refs)
    reviewed: dict[str, dict] = {
        "reviewed_default": {},
        "reviewed_all": {"sw_only": False},
        "reviewed_page": {"sw_only": False, "limit": 1},
    }
    captured.update({name: _payload(session, **params) for name, params in reviewed.items()})
    return captured


def test_pre_specs_list_matches_captured_baseline(pre_specs_api):
    session, _engine, refs = pre_specs_api

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    assert capture_scenarios(session, refs) == baseline


def test_pre_specs_document_counts_fetch_statuses_and_unqueued_attachments(pre_specs_api):
    session, _engine, refs = pre_specs_api

    item = _items_by_id(_payload(session))[refs["sw_yes"].id]

    assert item["document"] == {
        "attachments": 6,
        "완료": 1,
        "대기": 1,
        "진행": 1,
        "차단": 1,
        "실패": 1,
    }


def test_pre_specs_overview_review_status_projects_from_review_row(pre_specs_api):
    session, _engine, refs = pre_specs_api
    session.add(
        PreSpecOverviewReview(notice_id=refs["sw_yes"].id, status="needs_human_review")
    )
    session.commit()

    items = _items_by_id(_payload(session, sw_only=False))
    assert items[refs["sw_yes"].id]["overview_review_status"] == "needs_human_review"
    # 개요 검토 행이 없는 공고는 null이다. awaiting_document로 접지 않는다
    # (CLAUDE.md unknown/null 보존 게이트).
    assert items[refs["sw_no"].id]["overview_review_status"] is None


def test_pre_specs_overview_status_counts_always_lists_all_ten_values_plus_null(pre_specs_api):
    session, _engine, refs = pre_specs_api
    _add_overview_rows(session, refs)

    payload = _payload(session, sw_only=False)
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}

    # 열 개 계약 상태는 0이어도 모두 나오고, 검토 행이 없는 공고는 별도의 null
    # bucket이다.
    assert set(counts) == set(_ALL_OVERVIEW_STATUSES) | {None}
    assert counts["needs_human_review"] == 1
    assert counts["completed"] == 1
    assert counts["failed"] == 0
    # fixture의 pre_spec 공고 9건 중 2건에 검토 행이 있다.
    assert counts[None] == payload["total"] - 2
    assert sum(counts.values()) == payload["total"]


def test_pre_specs_overview_status_counts_reflect_full_filtered_set_not_just_the_page(
    pre_specs_api,
):
    session, _engine, refs = pre_specs_api
    session.add(
        PreSpecOverviewReview(notice_id=refs["sw_yes"].id, status="needs_human_review")
    )
    session.commit()

    payload = _payload(session, sw_only=False, limit=1)
    assert len(payload["items"]) == 1
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}
    # 페이지는 한 건으로 잘렸지만 그룹 건수는 필터 전체를 설명한다.
    assert counts["needs_human_review"] == 1
    assert sum(counts.values()) == payload["total"]


def test_pre_specs_list_uses_constant_query_count(pre_specs_api):
    session, engine, _refs = pre_specs_api
    statements: list[str] = []

    def count_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = _payload(session, sw_only=False)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    # lifecycle 몫(필터된 공고 id 집합, 페이지)과 projection 몫(개요 상태, 상태별
    # 건수, 첨부 취득 건수)을 합쳐도 상수 회다. 공고당 조회는 없다.
    assert len(statements) <= 5
    assert response["total"] == 9
