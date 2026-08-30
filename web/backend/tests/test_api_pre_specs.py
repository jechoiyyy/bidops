"""T-24 cumulative pre-specification list API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import init_db
from app.models import (
    Attachment,
    AttachmentFetch,
    ContentObject,
    DocumentVersion,
    Notice,
    Opportunity,
    OpportunityLink,
    OrderPlan,
)
from app.routers.pre_specs import list_pre_specs


def _add_notice(
    session: Session,
    *,
    key: str,
    title: str,
    agency: str,
    sw_status: str | None,
    business_division: str | None,
    published_at: datetime,
    deadline_at: datetime,
) -> Notice:
    flags: dict[str, str] = {}
    if sw_status is not None:
        flags["sw_business_status"] = sw_status
    if business_division is not None:
        flags["business_division"] = business_division
    notice = Notice(
        notice_key=key,
        source_type="pre_spec",
        title=title,
        agency=agency,
        published_at=published_at,
        deadline_at=deadline_at,
        budget="1234567.00",
        qualification_flags_json=flags,
        lifecycle_json={"pre_spec_no": key.removeprefix("pre:")},
    )
    session.add(notice)
    session.flush()
    return notice


def _add_order_plan_path(
    session: Session,
    notice: Notice,
    *,
    tracking_status: str,
    first_registered_stage: str = "order_plan",
    link_status: str = "후보 확인 대기",
    include_order_plan: bool = True,
) -> Opportunity:
    selected = tracking_status != "미선택"
    opportunity = Opportunity(
        first_registered_stage=first_registered_stage,
        tracking_status=tracking_status,
        tracking_reason="테스트 이유" if selected else None,
        tracking_selected_by="테스트 담당자" if selected else None,
        tracking_selected_at=datetime(2026, 8, 20, tzinfo=UTC) if selected else None,
    )
    session.add(opportunity)
    session.flush()
    session.add(
        OpportunityLink(
            opportunity_id=opportunity.id,
            notice_id=notice.id,
            stage="notice",
            link_type="candidate" if link_status != "확정" else "official",
            status=link_status,
            evidence_external_no="PRE-TEST" if link_status == "확정" else None,
        )
    )
    if include_order_plan:
        plan = OrderPlan(order_plan_unty_no=f"R26T24{opportunity.id:08d}")
        session.add(plan)
        session.flush()
        session.add(
            OpportunityLink(
                opportunity_id=opportunity.id,
                order_plan_id=plan.id,
                stage="order_plan",
                link_type="official",
                status="확정",
                evidence_external_no=plan.order_plan_unty_no,
            )
        )
    session.flush()
    return opportunity


@pytest.fixture
def pre_specs_api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    session = Session(engine)
    base_time = datetime(2026, 8, 20, tzinfo=UTC)

    sw_yes = _add_notice(
        session,
        key="pre:SW-Y",
        title="AI 플랫폼 제안요청서",
        agency="가나다 기관",
        sw_status="Y",
        business_division="일반용역",
        published_at=base_time + timedelta(days=3),
        deadline_at=base_time + timedelta(days=8),
    )
    sw_no = _add_notice(
        session,
        key="pre:SW-N",
        title="행사 운영 제안요청서",
        agency="마바사 기관",
        sw_status="N",
        business_division="일반용역",
        published_at=base_time + timedelta(days=2),
        deadline_at=base_time + timedelta(days=7),
    )
    tracked_no = _add_notice(
        session,
        key="pre:TRACKED-N",
        title="데이터 연계 제안요청서",
        agency="다라마 기관",
        sw_status="N",
        business_division="기술용역",
        published_at=base_time + timedelta(days=1),
        deadline_at=base_time + timedelta(days=2),
    )
    tracked_opportunity = _add_order_plan_path(
        session,
        tracked_no,
        tracking_status="계속 추적",
    )

    null_status = _add_notice(
        session,
        key="pre:NULL",
        title="상태 미확인 제안요청서",
        agency="라바 기관",
        sw_status=None,
        business_division="기술용역",
        published_at=base_time,
        deadline_at=base_time + timedelta(days=20),
    )
    new_origin = _add_notice(
        session,
        key="pre:NEW",
        title="신규 사업 제안요청서",
        agency="사아 기관",
        sw_status="Y",
        business_division="일반용역",
        published_at=base_time - timedelta(days=1),
        deadline_at=base_time + timedelta(days=15),
    )
    new_opportunity = _add_order_plan_path(
        session,
        new_origin,
        tracking_status="미선택",
        first_registered_stage="pre_spec",
        include_order_plan=False,
    )

    search_unconfirmed = _add_notice(
        session,
        key="pre:UNCONFIRMED",
        title="검색 미확인 제안요청서",
        agency="차카 기관",
        sw_status="N",
        business_division="일반용역",
        published_at=base_time - timedelta(days=2),
        deadline_at=base_time + timedelta(days=18),
    )
    search_opportunity = Opportunity(
        first_registered_stage="order_plan",
        tracking_status="계속 추적",
        tracking_reason="테스트 이유",
        tracking_selected_by="테스트 담당자",
        tracking_selected_at=base_time,
    )
    session.add(search_opportunity)
    session.flush()
    session.add(
        OpportunityLink(
            opportunity_id=search_opportunity.id,
            stage="notice",
            link_type="candidate",
            status="검색 미확인",
            search_strategy="full",
        )
    )
    search_plan = OrderPlan(order_plan_unty_no="R26T24UNCONFIRMED")
    session.add(search_plan)
    session.flush()
    session.add(
        OpportunityLink(
            opportunity_id=search_opportunity.id,
            order_plan_id=search_plan.id,
            stage="order_plan",
            link_type="official",
            status="확정",
            evidence_external_no=search_plan.order_plan_unty_no,
        )
    )

    unselected_no = _add_notice(
        session,
        key="pre:UNSELECTED",
        title="미선택 제안요청서",
        agency="타파 기관",
        sw_status="N",
        business_division="일반용역",
        published_at=base_time - timedelta(days=3),
        deadline_at=base_time + timedelta(days=17),
    )
    unselected_opportunity = _add_order_plan_path(
        session,
        unselected_no,
        tracking_status="미선택",
    )
    closed_no = _add_notice(
        session,
        key="pre:CLOSED",
        title="종료 제안요청서",
        agency="하마 기관",
        sw_status="N",
        business_division="일반용역",
        published_at=base_time - timedelta(days=4),
        deadline_at=base_time + timedelta(days=16),
    )
    closed_opportunity = _add_order_plan_path(
        session,
        closed_no,
        tracking_status="종료",
    )
    no_plan_no = _add_notice(
        session,
        key="pre:NO-PLAN",
        title="발주계획 미연결 제안요청서",
        agency="거너 기관",
        sw_status="N",
        business_division="일반용역",
        published_at=base_time - timedelta(days=5),
        deadline_at=base_time + timedelta(days=14),
    )
    no_plan_opportunity = _add_order_plan_path(
        session,
        no_plan_no,
        tracking_status="보류",
        include_order_plan=False,
    )

    non_pre_spec = Notice(
        notice_key="bid:NOT-PRE-SPEC",
        source_type="bid_notice",
        title="입찰공고",
        agency="다른 기관",
        qualification_flags_json={"sw_business_status": "Y"},
    )
    session.add(non_pre_spec)
    session.flush()

    # Exercise every fetch status plus one attachment without a queue row.
    fetch_attachments = [
        Attachment(notice=sw_yes, name="completed.pdf", origin="g2b"),
        Attachment(notice=sw_yes, name="pending.pdf", origin="g2b"),
        Attachment(notice=sw_yes, name="running.pdf", origin="g2b"),
        Attachment(notice=sw_yes, name="blocked.pdf", origin="g2b"),
        Attachment(notice=sw_yes, name="failed.pdf", origin="g2b"),
        Attachment(notice=sw_yes, name="without-queue.pdf", origin="g2b"),
    ]
    session.add_all(fetch_attachments)
    session.flush()
    content = ContentObject(
        sha256="a" * 64,
        size_bytes=10,
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=sw_yes.id,
        attachment_id=fetch_attachments[0].id,
        content_object_id=content.id,
        version=1,
        source_kind="provider",
        source_system="g2b",
        source_attachment_key="T24:completed:1",
        source_url="https://www.g2b.go.kr/internal-test-source",
        original_filename="completed.pdf",
        role="기타",
        is_current=True,
        safety_status="safe",
    )
    session.add(document)
    session.flush()
    statuses = ["완료", "대기", "진행", "차단", "실패"]
    for attachment, status in zip(fetch_attachments[:5], statuses, strict=True):
        session.add(
                AttachmentFetch(
                    attachment_id=attachment.id,
                    status=status,
                    eligibility_reason="sw_business_object",
                    attempt_count=0,
                    max_attempts=3,
                    next_attempt_at=base_time,
                    lease_owner="t24-test" if status == "진행" else None,
                    lease_expires_at=(
                        base_time + timedelta(minutes=10)
                        if status == "진행"
                        else None
                    ),
                    document_version_id=document.id if status == "완료" else None,
                )
        )
    session.commit()

    references = {
        "sw_yes": sw_yes,
        "sw_no": sw_no,
        "tracked_no": tracked_no,
        "tracked_opportunity": tracked_opportunity,
        "null_status": null_status,
        "new_origin": new_origin,
        "new_opportunity": new_opportunity,
        "search_unconfirmed": search_unconfirmed,
        "unselected_no": unselected_no,
        "unselected_opportunity": unselected_opportunity,
        "closed_no": closed_no,
        "closed_opportunity": closed_opportunity,
        "no_plan_no": no_plan_no,
        "no_plan_opportunity": no_plan_opportunity,
        "non_pre_spec": non_pre_spec,
    }
    try:
        yield session, engine, references
    finally:
        session.close()
        engine.dispose()


def _payload(session: Session, **params: object) -> dict:
    """Call the route handler directly; the environment's TestClient is unavailable."""

    values: dict[str, object] = {
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


def _items_by_id(payload: dict) -> dict[int, dict]:
    return {item["notice_pk"]: item for item in payload["items"]}


def test_pre_specs_default_returns_sw_business_object(pre_specs_api):
    session, _engine, refs = pre_specs_api

    response = _payload(session)

    ids = _items_by_id(response)
    assert refs["sw_yes"].id in ids
    assert ids[refs["sw_yes"].id]["kept_by_tracking"] is False


def test_pre_specs_default_excludes_sw_n_without_tracking_link(pre_specs_api):
    session, _engine, refs = pre_specs_api

    ids = _items_by_id(_payload(session))

    assert refs["sw_no"].id not in ids


def test_pre_specs_default_keeps_tracked_sw_n_and_explains_exception(pre_specs_api):
    session, _engine, refs = pre_specs_api

    item = _items_by_id(_payload(session))[refs["tracked_no"].id]

    assert item["opportunity_id"] == refs["tracked_opportunity"].id
    assert item["tracking_status"] == "계속 추적"
    assert item["kept_by_tracking"] is True
    assert item["origin"] == "추적"


def test_pre_specs_search_unconfirmed_untracked_or_missing_order_plan_do_not_bypass_filter(pre_specs_api):
    session, _engine, refs = pre_specs_api

    ids = _items_by_id(_payload(session))

    assert refs["search_unconfirmed"].id not in ids
    assert refs["unselected_no"].id not in ids
    assert refs["closed_no"].id not in ids
    assert refs["no_plan_no"].id not in ids
    assert refs["unselected_opportunity"].id != refs["tracked_opportunity"].id
    assert refs["closed_opportunity"].id != refs["tracked_opportunity"].id


def test_pre_specs_sw_only_false_returns_all_pre_specs(pre_specs_api):
    session, _engine, refs = pre_specs_api

    response = _payload(session, sw_only=False)
    ids = _items_by_id(response)

    assert refs["sw_no"].id in ids
    assert refs["null_status"].id in ids
    assert refs["non_pre_spec"].id not in ids


def test_pre_specs_preserves_missing_sw_status_as_null(pre_specs_api):
    session, _engine, refs = pre_specs_api

    item = _items_by_id(_payload(session, sw_only=False))[refs["null_status"].id]

    assert item["sw_business_status"] is None
    assert item["business_division"] == "기술용역"


def test_pre_specs_origin_uses_first_registered_stage_projection(pre_specs_api):
    session, _engine, refs = pre_specs_api

    items = _items_by_id(_payload(session))

    assert items[refs["tracked_no"].id]["origin"] == "추적"
    assert items[refs["new_origin"].id]["origin"] == "신규"
    assert items[refs["sw_yes"].id]["origin"] is None


def test_pre_specs_business_division_q_sort_and_pagination(pre_specs_api):
    session, _engine, refs = pre_specs_api

    division = _payload(session, sw_only=False, business_division="기술용역")
    assert all(item["business_division"] == "기술용역" for item in division["items"])

    tracked = _payload(session, sw_only=False, origin="추적")
    assert all(item["origin"] == "추적" for item in tracked["items"])
    new = _payload(session, sw_only=False, origin="신규")
    assert [item["notice_pk"] for item in new["items"]] == [refs["new_origin"].id]

    searched = _payload(session, sw_only=False, q="다라마")
    assert [item["notice_pk"] for item in searched["items"]] == [refs["tracked_no"].id]

    deadline = _payload(session, sw_only=False, sort="deadline")
    assert deadline["items"][0]["notice_pk"] == refs["tracked_no"].id

    paged = _payload(session, sw_only=False, sort="published", limit=2, offset=2)
    assert paged["limit"] == 2
    assert paged["offset"] == 2
    assert paged["total"] == 9
    assert len(paged["items"]) == 2


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


def test_pre_specs_response_does_not_expose_storage_metadata(pre_specs_api):
    session, _engine, _refs = pre_specs_api

    body = str(_payload(session))

    for forbidden in ("object_key", "/home/", "internal-test-source", "source_attachment_key", "password"):
        assert forbidden not in body


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

    assert len(statements) <= 2
