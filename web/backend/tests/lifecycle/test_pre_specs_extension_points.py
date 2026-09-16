"""lifecycle의 사전규격 목록·추적 결정이 확장점만 본다 (명세 §6.1·§6.2).

제공자가 없으면 개요 상태는 `null`, 상태별 건수는 열 개 모두 0에 `null` bucket이
전체 건수, 첨부 취득 건수 다섯 개는 0이고 `attachments`만 lifecycle이 직접 센다.
제공자가 있으면 그 값이 그대로 실린다 — 어느 모듈이 제공하는지는 모른다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
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
from app.lifecycle.models import Attachment, Notice, Opportunity
from app.lifecycle.routers.opportunities import update_tracking_status
from app.lifecycle.routers.pre_specs import list_pre_specs
from app.lifecycle.schemas.opportunities import TrackingStatusUpdateRequest

WHEN = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture()
def registry() -> ExtensionRegistry:
    previous = extension_registry()
    try:
        yield reset_extension_registry()
    finally:
        restore_extension_registry(previous)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _pre_spec(session: Session, key: str, *, attachments: int) -> Notice:
    notice = Notice(
        notice_key=key,
        source_type="pre_spec",
        title=f"{key} 제안요청서",
        agency="테스트 기관",
        published_at=WHEN,
        qualification_flags_json={"sw_business_status": "Y"},
    )
    session.add(notice)
    session.flush()
    for index in range(attachments):
        session.add(Attachment(notice=notice, name=f"file-{index}.pdf", origin="g2b"))
    session.commit()
    return notice


def _list(session: Session, **params: Any) -> dict:
    values: dict[str, Any] = {
        "notice_pk": None,
        "sw_only": True,
        "business_division": None,
        "origin": None,
        "q": None,
        "sort": "published",
        "limit": 50,
        "offset": 0,
    }
    values.update(params)
    return list_pre_specs(session=session, **values).model_dump(mode="json", by_alias=True)


def test_without_a_provider_overview_is_null_and_document_counts_are_zero(registry, db_session):
    notice = _pre_spec(db_session, "pre:ABSENT", attachments=2)

    payload = _list(db_session)

    (item,) = payload["items"]
    assert item["notice_pk"] == notice.id
    assert item["overview_review_status"] is None
    assert item["document"] == {
        "attachments": 2,
        "완료": 0,
        "대기": 0,
        "진행": 0,
        "차단": 0,
        "실패": 0,
    }
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}
    assert len(counts) == 11
    assert counts[None] == 1
    assert all(count == 0 for status, count in counts.items() if status is not None)


class _FakeOverviewProjection:
    """lifecycle이 넘긴 id만으로 답하는 가짜 제공자."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    @staticmethod
    def _projected_id(notice_ids: Sequence[int]) -> int | None:
        # 목록은 published/id DESC로 페이지를 정렬하지만, projection 입력은
        # SQL의 무순서 후보 집합이다. ID를 명시적으로 고정해 두어 호출 순서에
        # 결과가 우연히 결합되지 않도록 한다.
        return max(notice_ids) if notice_ids else None

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        self.calls.append(("overview_status", tuple(notice_ids)))
        projected_id = self._projected_id(notice_ids)
        return {projected_id: "completed"} if projected_id is not None else {}

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        self.calls.append(("overview_status_counts", tuple(notice_ids)))
        return {"completed": 1} if notice_ids else {}

    def document_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, PreSpecDocumentCounts]:
        self.calls.append(("document_counts", tuple(notice_ids)))
        projected_id = self._projected_id(notice_ids)
        return (
            {projected_id: PreSpecDocumentCounts(completed=2, blocked=1)}
            if projected_id is not None
            else {}
        )

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        self.calls.append(("prespec_status_fields", tuple(notice_ids)))
        projected_id = self._projected_id(notice_ids)
        if projected_id is None:
            return {}
        return {
            projected_id: {
                "grade": "우선 검토",
                "grade_source": "human_review",
                "auto_preparation_status": "bundle_ready",
                "auto_preparation_reason": None,
                "latest_deep_review_id": None,
            }
        }


def test_with_a_provider_the_projection_values_are_carried_into_the_response(registry, db_session):
    first = _pre_spec(db_session, "pre:FIRST", attachments=3)
    second = _pre_spec(db_session, "pre:SECOND", attachments=0)
    projection = _FakeOverviewProjection()
    registry.register_overview_document_projection(projection, owner="test")

    payload = _list(db_session)

    by_id = {item["notice_pk"]: item for item in payload["items"]}
    calls = dict(projection.calls)
    # 가짜 제공자는 안정적으로 가장 큰 ID의 공고에만 값을 준다.
    projected_id = max(calls["overview_status"])
    assert projected_id in {first.id, second.id}
    assert calls["document_counts"][0] == projected_id
    assert by_id[projected_id]["overview_review_status"] == "completed"
    assert by_id[projected_id]["document"]["완료"] == 2
    assert by_id[projected_id]["document"]["차단"] == 1
    # 등급·자동 준비도 같은 확장점에서 온다. 제공자가 값을 주지 않은 공고는
    # 등급 `null`과 `not_applicable`로 남는다 — lifecycle이 만들어 내지 않는다.
    assert by_id[projected_id]["grade"] == "우선 검토"
    assert by_id[projected_id]["grade_source"] == "human_review"
    assert by_id[projected_id]["auto_preparation_status"] == "bundle_ready"
    other_id = next(value for value in by_id if value != projected_id)
    assert by_id[other_id]["grade"] is None
    assert by_id[other_id]["grade_source"] is None
    assert by_id[other_id]["auto_preparation_status"] == "not_applicable"
    # attachments는 lifecycle이 자기 테이블에서 센다. projection이 준 값이 아니다.
    assert by_id[first.id]["document"]["attachments"] == 3
    assert by_id[second.id]["document"]["attachments"] == 0
    counts = {row["status"]: row["count"] for row in payload["overview_status_counts"]}
    assert counts["completed"] == 1
    assert counts[None] == 1
    # 상태·필드 필터와 집계를 위해 전체 후보를 먼저 받고, 문서 상세 건수만
    # 반환 페이지를 받는다. 각 확장점은 여전히 공고당 조회를 만들지 않는다.
    assert [name for name, _ids in projection.calls] == [
        "overview_status",
        "prespec_status_fields",
        "overview_status_counts",
        "document_counts",
    ]
    assert all(set(ids) == {first.id, second.id} for _name, ids in projection.calls)


def test_projection_receives_only_the_page_for_per_notice_values(registry, db_session):
    notices = [_pre_spec(db_session, f"pre:PAGE-{index}", attachments=0) for index in range(3)]
    projection = _FakeOverviewProjection()
    registry.register_overview_document_projection(projection, owner="test")

    payload = _list(db_session, limit=1, offset=1)

    assert len(payload["items"]) == 1
    page_id = payload["items"][0]["notice_pk"]
    calls = dict(projection.calls)
    assert set(calls["overview_status_counts"]) == {notice.id for notice in notices}
    assert set(calls["overview_status"]) == {notice.id for notice in notices}
    assert set(calls["prespec_status_fields"]) == {notice.id for notice in notices}
    assert calls["document_counts"] == (page_id,)


class _RecordingTrackingHook:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        self.calls.append((session, opportunity_id))


def _opportunity(session: Session) -> Opportunity:
    opportunity = Opportunity(first_registered_stage="order_plan", tracking_status="미선택")
    session.add(opportunity)
    session.commit()
    return opportunity


def _patch(session: Session, opportunity_id: int):
    return update_tracking_status(
        opportunity_id,
        TrackingStatusUpdateRequest(tracking_status="계속 추적", reason="테스트 이유"),
        actor="tester",
        actor_format=None,
        session=session,
    )


def test_tracking_status_change_without_a_hook_still_succeeds(registry, db_session):
    opportunity = _opportunity(db_session)

    response = _patch(db_session, opportunity.id)

    assert response.tracking_status == "계속 추적"


def test_tracking_status_change_notifies_the_registered_hook_with_the_opportunity(registry, db_session):
    opportunity = _opportunity(db_session)
    hook = _RecordingTrackingHook()
    registry.register_tracking_decision_hook(hook, owner="test")

    response = _patch(db_session, opportunity.id)

    assert response.tracking_status == "계속 추적"
    assert [opportunity_id for _session, opportunity_id in hook.calls] == [opportunity.id]
    assert hook.calls[0][0] is db_session


class _ExplodingTrackingHook:
    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        raise RuntimeError("refresh failed")


def test_hook_failure_does_not_undo_the_human_decision(registry, db_session):
    opportunity = _opportunity(db_session)
    registry.register_tracking_decision_hook(_ExplodingTrackingHook(), owner="test")

    response = _patch(db_session, opportunity.id)

    assert response.tracking_status == "계속 추적"
    db_session.expire_all()
    assert db_session.get(Opportunity, opportunity.id).tracking_status == "계속 추적"
