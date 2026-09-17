"""SW=Y 사전규격 자동 후보·찾아보기·사전규격 후보 조회·오래된 후보 수락 (spec §4, P2b 위험).

lifecycle 단독 동작을 보므로 확장점은 비워 둔다(`empty_extensions`). 회차 파일은
수집기 현재 출력 모양을 `test_collection_ingest`의 도우미로 만든다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.models import AuditEvent
from app.lifecycle import ingest_run
from app.lifecycle.ingest import loader as loader_module
from app.lifecycle.models import (
    CollectedRecordIndex,
    IngestWarning,
    Notice,
    Opportunity,
    OpportunityLink,
    OrderPlan,
)
from app.lifecycle.services.opportunity_candidates import (
    SEARCH_PERFORMED_ACTION,
    create_pre_spec_auto_candidates,
    pre_spec_order_plan_candidates,
    search_opportunity_records,
)
from app.lifecycle.services.opportunity_integrity import (
    HUMAN_MERGE_ACTION,
    record_candidate_decision,
)
from app.lifecycle.services.opportunity_tracking import OpportunityTrackingError
from tests.lifecycle.test_collection_ingest import (
    _bid,
    _notice,
    _owner,
    _plan,
    _pre_spec,
    _session,
    _write_run,
)


SEARCHED_AT = datetime(2026, 9, 17, 1, 2, 3, 456789, tzinfo=timezone.utc)
_numbers = count(1)


def _add_plan(
    session: Session,
    *,
    title: str,
    agency: str | None = "테스트 발주기관",
    published_at: datetime | None = datetime(2026, 9, 1, tzinfo=timezone.utc),
) -> tuple[OrderPlan, Opportunity]:
    number = f"R26DD2{next(_numbers):07d}"
    plan = OrderPlan(
        order_plan_unty_no=number, title=title, agency_name=agency, published_at=published_at
    )
    owner = Opportunity(first_registered_stage="order_plan")
    session.add_all([plan, owner])
    session.flush()
    session.add(
        OpportunityLink(
            opportunity=owner, order_plan=plan, stage="order_plan", link_type="official",
            status="확정", evidence_external_no=number,
        )
    )
    session.flush()
    return plan, owner


def _add_pre_spec(
    session: Session,
    *,
    title: str,
    agency: str | None = "조달청",
    demand_agency: str | None = None,
    owner: Opportunity | None = None,
) -> Notice:
    number = f"R26BD0{next(_numbers):07d}"
    notice = Notice(
        notice_key=f"pre:{number}", source_type="pre_spec", title=title, agency=agency,
        demand_agency=demand_agency, lifecycle_json={"pre_spec_no": number},
    )
    owner = owner or Opportunity(first_registered_stage="pre_spec")
    session.add_all([notice, owner])
    session.flush()
    session.add(
        OpportunityLink(
            opportunity=owner, notice=notice, stage="notice", link_type="official",
            status="확정", evidence_external_no=number,
        )
    )
    session.flush()
    return notice


def _candidates(session: Session, notice: Notice) -> dict[int, OpportunityLink]:
    return {
        link.opportunity_id: link
        for link in session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.notice_id == notice.id,
                OpportunityLink.link_type == "candidate",
            )
        )
    }


# ---------------------------------------------------------------------------
# §4.2 자동 후보
# ---------------------------------------------------------------------------


def test_auto_candidates_match_the_demand_agency_and_record_the_ladder_strategy(empty_extensions):
    with _session() as session:
        full_plan, full_owner = _add_plan(session, title="통합 행정 플랫폼 구축")
        split_plan, split_owner = _add_plan(session, title="민원·행정 플랫폼 구축")
        _other_agency, other_agency_owner = _add_plan(session, title="통합 행정 플랫폼 구축", agency="다른 기관")
        _superset, superset_owner = _add_plan(session, title="통합 행정 플랫폼 구축", agency="테스트 발주기관 분소")
        _unrelated, unrelated_owner = _add_plan(session, title="도로 포장 공사 설계 용역")
        for index in range(20):
            _add_plan(session, title="통합 행정 플랫폼 구축", agency=f"먼 기관 {index}")
        pre_spec = _add_pre_spec(
            session,
            title="2026년 통합 행정 플랫폼 구축 사전규격",
            agency="조달청 경기지방조달청",
            demand_agency="  테스트   발주기관 ",
        )
        full_id, split_id = full_owner.id, split_owner.id
        excluded_ids = {other_agency_owner.id, superset_owner.id, unrelated_owner.id}
        pre_spec_id = pre_spec.id
        session.commit()
        session.expunge_all()
        pre_spec = session.get(Notice, pre_spec_id)

        result = create_pre_spec_auto_candidates(session, pre_spec, searched_at=SEARCHED_AT)

        # 기관이 다른 발주계획은 SQL에서 걸러져 Python으로 올라오지 않는다.
        loaded_agencies = {
            item.agency_name for item in session.identity_map.values() if isinstance(item, OrderPlan)
        }
        assert loaded_agencies <= {"테스트 발주기관", "테스트 발주기관 분소"}
        assert (result.matched, result.created) == (2, 2)
        links = _candidates(session, pre_spec)
        assert set(links) == {full_id, split_id}
        assert not excluded_ids & set(links)
        full = links[full_id]
        assert (full.status, full.stage, full.search_strategy, full.agency_match) == (
            "후보 확인 대기", "notice", "full", True,
        )
        assert full.attempted_strategies_json == ["full"]
        assert full.last_searched_at == SEARCHED_AT
        split = links[split_id]
        assert split.search_strategy == "breaking_split"
        assert split.attempted_strategies_json == ["full", "breaking_split"]
        session.commit()

        # 같은 owner+target 행은 상태와 무관하게 다시 만들지 않는다(기각 포함).
        assert create_pre_spec_auto_candidates(session, pre_spec).created == 0
        record_candidate_decision(
            session, full, decision="rejected", reason="다른 사업", reviewer_name="담당자",
            reviewed_at=SEARCHED_AT,
        )
        session.commit()
        assert create_pre_spec_auto_candidates(session, pre_spec).created == 0
        assert len(_candidates(session, pre_spec)) == 2

        nothing = _add_pre_spec(session, title="전혀 다른 청사 보수 공사", demand_agency="테스트 발주기관")
        before = session.scalar(select(func.count(OpportunityLink.id)))
        assert create_pre_spec_auto_candidates(session, nothing) == type(result)(0, 0)
        assert session.scalar(select(func.count(OpportunityLink.id))) == before


def test_auto_candidates_cap_five_by_precision_then_newest_and_skip_owners_with_a_pre_spec(
    empty_extensions,
):
    with _session() as session:
        day = lambda number: datetime(2026, 9, number, tzinfo=timezone.utc)
        full_owners = {
            number: _add_plan(session, title="통합 행정 플랫폼 구축", published_at=day(number))[1]
            for number in range(1, 7)
        }
        _undated, undated_owner = _add_plan(session, title="통합 행정 플랫폼 구축", published_at=None)
        _split, split_owner = _add_plan(session, title="민원·행정 플랫폼 구축", published_at=day(9))
        _tracked, owner_with_pre_spec = _add_plan(session, title="통합 행정 플랫폼 구축", published_at=day(10))
        _add_pre_spec(session, title="이미 연결된 사전규격", owner=owner_with_pre_spec)
        pre_spec = _add_pre_spec(
            session, title="통합 행정 플랫폼 구축 사전규격", agency="테스트 발주기관"
        )
        session.commit()

        result = create_pre_spec_auto_candidates(session, pre_spec)

        assert (result.matched, result.created) == (8, 5)
        expected = {full_owners[number].id for number in (6, 5, 4, 3, 2)}
        assert set(_candidates(session, pre_spec)) == expected
        assert not {undated_owner.id, split_owner.id, owner_with_pre_spec.id} & set(
            _candidates(session, pre_spec)
        )


def test_collection_ingest_proposes_candidates_only_for_sw_pre_specs_and_failures_only_warn(
    tmp_path, empty_extensions, monkeypatch
):
    plan_no, sw_no, non_sw_no = "R26DD20859101", "R26BD00279101", "R26BD00279102"
    notices = [
        _pre_spec(sw_no, title="통합 행정 플랫폼 구축 사전규격", demand_agency=None),
        _pre_spec(non_sw_no, sw="N", title="통합 행정 플랫폼 구축 2차 사전규격"),
    ]
    run_dir = _write_run(
        tmp_path, "lifecycle-20260916-notices",
        plans=[_plan(plan_no, title="통합 행정 플랫폼 구축")], notices=notices,
    )
    with _session() as session:
        ingested = ingest_run(run_dir, session, selection="collection")
        plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
        plan_owner = _owner(session, order_plan=plan)
        sw_pre_spec = _notice(session, f"pre:{sw_no}")
        assert _notice(session, f"pre:{non_sw_no}") is None
        links = _candidates(session, sw_pre_spec)
        assert set(links) == {plan_owner.id}
        assert links[plan_owner.id].search_strategy == "full"
        # 같은 회차 재적재는 후보를 늘리지 않는다.
        ingest_run(run_dir, session, selection="collection")
        assert len(_candidates(session, sw_pre_spec)) == 1
        assert not session.scalars(
            select(IngestWarning).where(IngestWarning.code == "opportunity_candidate_match_failed")
        ).all()
        assert ingested.run_id

    failing_dir = _write_run(
        tmp_path, "lifecycle-20260917-notices",
        plans=[_plan(plan_no, title="통합 행정 플랫폼 구축")],
        notices=[_pre_spec(sw_no, title="통합 행정 플랫폼 구축 사전규격")],
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("/private/path secret")

    monkeypatch.setattr(loader_module, "create_pre_spec_auto_candidates", fail)
    with _session() as session:
        failed = ingest_run(failing_dir, session, selection="collection")
        assert _notice(session, f"pre:{sw_no}") is not None
        warning = session.scalar(
            select(IngestWarning).where(
                IngestWarning.run_id == failed.run_id,
                IngestWarning.code == "opportunity_candidate_match_failed",
            )
        )
        assert warning is not None and warning.level == "warning"
        assert warning.context_json == {"notice_id": f"pre:{sw_no}", "failure_type": "RuntimeError"}
        assert "/private/path" not in warning.message
        assert session.scalar(
            select(func.count(OpportunityLink.id)).where(OpportunityLink.link_type == "candidate")
        ) == 0


def test_a_merge_later_in_the_same_ingest_moves_the_new_candidate_with_its_owner(
    tmp_path, empty_extensions
):
    plan_no, pre_no, bid_no = "R26DD20859151", "R26BD00279151", "R26BK01699151"
    first = _write_run(
        tmp_path, "lifecycle-20260915-notices", generated_at="2026-09-15T00:00:00+00:00",
        notices=[_pre_spec(pre_no, title="통합 행정 플랫폼 구축 사전규격")],
    )
    second = _write_run(
        tmp_path, "lifecycle-20260916-notices",
        plans=[_plan(plan_no, title="통합 행정 플랫폼 구축")],
        notices=[
            _pre_spec(pre_no, title="통합 행정 플랫폼 구축 사전규격"),
            _bid(bid_no, title="통합 행정 플랫폼 구축", order_plan_no=plan_no, pre_spec_no=pre_no),
        ],
    )
    with _session() as session:
        ingest_run(first, session, selection="collection")
        pre_spec_owner = _owner(session, notice=_notice(session, f"pre:{pre_no}")).id
        ingest_run(second, session, selection="collection")
        session.expire_all()

        merged_ids = set(
            session.scalars(
                select(Opportunity.id).where(Opportunity.merged_into_opportunity_id.is_not(None))
            )
        )
        assert merged_ids, "the bid must merge the plan owner into the older pre-spec owner"
        assert session.scalar(
            select(func.count(OpportunityLink.id)).where(OpportunityLink.opportunity_id.in_(merged_ids))
        ) == 0
        candidates = session.scalars(
            select(OpportunityLink).where(OpportunityLink.link_type == "candidate")
        ).all()
        assert [link.opportunity_id for link in candidates] == [pre_spec_owner]
        # 병합으로 대상이 소유자 것이 되었으므로 사전규격 후보 목록에도 나오지 않는다.
        assert pre_spec_order_plan_candidates(session, candidates[0].notice_id).items == []


# ---------------------------------------------------------------------------
# §4.3 찾아보기
# ---------------------------------------------------------------------------


def test_search_pre_spec_loads_index_only_records_orders_by_agency_and_excludes_rejections(
    tmp_path, empty_extensions
):
    plan_no = "R26DD20859201"
    far_no, near_no = "R26BD00279201", "R26BD00279202"
    far = _pre_spec(far_no, sw="N", title="통합 행정 플랫폼 구축 사전규격")
    far["agency"] = "다른 발주기관"
    near = _pre_spec(near_no, sw="N", title="2차 통합 행정 플랫폼 구축")
    run_dir = _write_run(
        tmp_path, "lifecycle-20260916-notices",
        plans=[_plan(plan_no, title="통합 행정 플랫폼 구축")],
        notices=[far, near, _pre_spec("R26BD00279203", sw="N", title="청사 보수 공사")],
    )
    with _session() as session:
        ingest_run(run_dir, session, selection="collection")
        plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
        owner_id = _owner(session, order_plan=plan).id
        assert _notice(session, f"pre:{far_no}") is None

        outcome = search_opportunity_records(
            session, owner_id, target="pre_spec", searched_by="찾는 담당자",
            runs_root=run_dir.parent, searched_at=SEARCHED_AT,
        )
        session.commit()

        response = outcome.response
        assert response.search_unconfirmed is False
        assert response.attempted_strategies == ["full"]
        assert response.searched_at == SEARCHED_AT and response.target == "pre_spec"
        assert [item.record_external_id for item in response.candidates] == [f"pre:{near_no}", f"pre:{far_no}"]
        assert [item.agency_match for item in response.candidates] == [True, False]
        assert {item.status for item in response.candidates} == {"후보 확인 대기"}
        assert outcome.loaded_count == 2 and outcome.owner_opportunity_id == owner_id
        for number in (far_no, near_no):
            notice = _notice(session, f"pre:{number}")
            row = session.scalar(
                select(CollectedRecordIndex).where(CollectedRecordIndex.record_key == f"pre:{number}")
            )
            assert row.selection_reason == "search_result" and row.ingested_notice_id == notice.id
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == SEARCH_PERFORMED_ACTION))
        assert audit.claimed_name == "찾는 담당자" and audit.aggregate_id == str(owner_id)
        assert audit.safe_metadata == {
            "opportunity_id": owner_id, "target": "pre_spec", "matched_count": 2,
            "candidate_count": 2, "created_candidate_count": 2, "owned_count": 0,
            "loaded_count": 2, "unavailable_count": 0, "search_unconfirmed": False,
        }

        # 다시 찾으면 대기 후보를 재사용하고, 기각 쌍은 빠진다.
        again = search_opportunity_records(
            session, owner_id, target="pre_spec", searched_by="찾는 담당자",
            runs_root=run_dir.parent, searched_at=SEARCHED_AT + timedelta(hours=1),
        )
        assert [item.id for item in again.response.candidates] == [item.id for item in response.candidates]
        assert again.loaded_count == 0
        assert all(item.last_searched_at == SEARCHED_AT + timedelta(hours=1) for item in again.response.candidates)
        record_candidate_decision(
            session, response.candidates[1].id, decision="rejected", reason="다른 사업",
            reviewer_name="찾는 담당자", reviewed_at=SEARCHED_AT,
        )
        session.commit()
        third = search_opportunity_records(
            session, owner_id, target="pre_spec", searched_by="찾는 담당자",
            runs_root=run_dir.parent, searched_at=SEARCHED_AT,
        )
        assert [item.record_external_id for item in third.response.candidates] == [f"pre:{near_no}"]
        assert session.scalar(
            select(func.count(OpportunityLink.id)).where(
                OpportunityLink.opportunity_id == owner_id, OpportunityLink.link_type == "candidate"
            )
        ) == 2


def test_search_bid_notice_starts_from_the_owned_pre_spec_and_unconfirmed_is_kept(
    tmp_path, empty_extensions
):
    plan_no, pre_no, bid_no = "R26DD20859301", "R26BD00279301", "R26BK01699301"
    run_dir = _write_run(
        tmp_path, "lifecycle-20260916-notices",
        plans=[_plan(plan_no, title="청사 보수 공사 설계")],
        notices=[
            _pre_spec(pre_no, title="지능형 교통 관제 시스템 고도화"),
            _bid(bid_no, title="지능형 교통 관제 시스템 고도화 용역", sw_industry_1468="N"),
        ],
    )
    with _session() as session:
        ingest_run(run_dir, session, selection="collection")
        pre_spec_owner = _owner(session, notice=_notice(session, f"pre:{pre_no}")).id
        plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
        plan_owner = _owner(session, order_plan=plan).id
        assert _notice(session, f"bid:{bid_no}:000") is None

        found = search_opportunity_records(
            session, pre_spec_owner, target="bid_notice", searched_by="담당자",
            runs_root=run_dir.parent, searched_at=SEARCHED_AT,
        ).response
        assert [item.record_external_id for item in found.candidates] == [f"bid:{bid_no}:000"]
        # 사전규격 발주기관과 입찰공고 수요기관은 이 fixture에서 다르다.
        assert found.candidates[0].agency_match is False
        assert found.candidates[0].search_strategy == "full"

        for hour in (0, 1):
            missing = search_opportunity_records(
                session, plan_owner, target="bid_notice", searched_by="담당자",
                runs_root=run_dir.parent, searched_at=SEARCHED_AT + timedelta(hours=hour),
            ).response
            assert missing.candidates == [] and missing.search_unconfirmed is True
        session.commit()
        rows = session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.opportunity_id == plan_owner,
                OpportunityLink.status == "검색 미확인",
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].search_target_kind == "bid_notice"
        assert rows[0].last_searched_at == SEARCHED_AT + timedelta(hours=1)
        assert rows[0].attempted_strategies_json == missing.attempted_strategies == ["full"]
        assert (rows[0].notice_id, rows[0].order_plan_id) == (None, None)


def test_a_searched_record_that_joins_by_official_key_needs_no_candidate(tmp_path, empty_extensions):
    plan_no, bid_no = "R26DD20859401", "R26BK01699401"
    run_dir = _write_run(
        tmp_path, "lifecycle-20260916-notices",
        plans=[_plan(plan_no, title="스마트 물류 센터 구축")],
        notices=[_bid(bid_no, title="스마트 물류 센터 구축 용역", order_plan_no=plan_no, sw_industry_1468="N")],
    )
    with _session() as session:
        ingest_run(run_dir, session, selection="collection")
        plan = session.scalar(select(OrderPlan).where(OrderPlan.order_plan_unty_no == plan_no))
        owner_id = _owner(session, order_plan=plan).id

        outcome = search_opportunity_records(
            session, owner_id, target="bid_notice", searched_by="담당자",
            runs_root=run_dir.parent, searched_at=SEARCHED_AT,
        )

        assert outcome.response.candidates == [] and outcome.response.search_unconfirmed is False
        assert outcome.loaded_count == 1
        assert _owner(session, notice=_notice(session, f"bid:{bid_no}:000")).id == owner_id
        assert session.scalar(
            select(func.count(OpportunityLink.id)).where(OpportunityLink.status == "검색 미확인")
        ) == 0


def test_search_refuses_missing_sources_unknown_and_merged_opportunities(empty_extensions, tmp_path):
    with _session() as session:
        bid = Notice(notice_key="bid:R26BK01699501:000", source_type="bid_notice", title="입찰공고만 있는 사업")
        bid_owner = Opportunity(first_registered_stage="bid_notice")
        session.add_all([bid, bid_owner])
        session.flush()
        session.add(OpportunityLink(opportunity=bid_owner, notice=bid, stage="notice", link_type="official",
                                    status="확정", evidence_external_no="R26BK01699501"))
        _plan_row, plan_owner = _add_plan(session, title="통합 행정 플랫폼 구축")
        merged = Opportunity(first_registered_stage="order_plan", merged_into_opportunity_id=plan_owner.id,
                             merged_at=SEARCHED_AT, merge_reason="fixture")
        session.add(merged)
        session.commit()
        search = lambda pk, target: search_opportunity_records(
            session, pk, target=target, searched_by="담당자", runs_root=tmp_path
        )
        for target in ("pre_spec", "bid_notice"):
            with pytest.raises(OpportunityTrackingError) as missing:
                search(bid_owner.id, target)
            assert missing.value.code == "search_source_missing"
            assert missing.value.details == {"target": target}
            session.rollback()
        with pytest.raises(OpportunityTrackingError) as unknown:
            search(999_999, "pre_spec")
        assert unknown.value.code == "opportunity_not_found"
        with pytest.raises(OpportunityTrackingError) as merged_error:
            search(merged.id, "pre_spec")
        assert merged_error.value.code == "opportunity_merged"
        assert session.scalar(select(func.count(AuditEvent.id))) == 0


# ---------------------------------------------------------------------------
# §4.4 사전규격 후보 조회와 오래된 후보 수락 (P2b 위험)
# ---------------------------------------------------------------------------


def test_pre_spec_candidate_list_is_constant_query_and_hides_stale_candidates(empty_extensions):
    with _session() as session:
        pre_spec = _add_pre_spec(session, title="통합 행정 플랫폼 구축 사전규격", agency="테스트 발주기관")
        pre_spec_id = pre_spec.id
        engine = session.get_bind()
        query_counts = []
        for size in (1, 4):
            pre_spec = session.get(Notice, pre_spec_id)
            while len(_candidates(session, pre_spec)) < size:
                plan, owner = _add_plan(session, title="통합 행정 플랫폼 구축")
                plan.budget_amount = 123_456_789
                plan.planned_order_year, plan.planned_order_month = "2026", "2026-10"
                create_pre_spec_auto_candidates(session, pre_spec)
            session.commit()
            session.expunge_all()
            statements = []
            capture = lambda *args: statements.append(args[2])
            event.listen(engine, "before_cursor_execute", capture)
            try:
                response = pre_spec_order_plan_candidates(session, pre_spec_id)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            assert len(response.items) == size
            query_counts.append(len(statements))
        assert query_counts[0] == query_counts[1] <= 3
        item = response.items[0]
        assert item.link.status == "후보 확인 대기" and item.link.notice_id == pre_spec_id
        assert item.tracking_status == "미선택"
        assert [plan.title for plan in item.order_plans] == ["통합 행정 플랫폼 구축"]
        assert item.order_plans[0].budget_amount == 123456789.0
        assert (item.order_plans[0].planned_order_year, item.order_plans[0].planned_order_month) == ("2026", "2026-10")

        # 소유자가 이미 그 사전규격을 소유하게 된 후보는 목록에서 빠진다.
        pre_spec_owner_link = session.scalar(
            select(OpportunityLink).where(OpportunityLink.notice_id == pre_spec_id,
                                          OpportunityLink.link_type == "official")
        )
        pre_spec_owner_link.opportunity_id = item.opportunity_id
        session.commit()
        listed = pre_spec_order_plan_candidates(session, pre_spec_id)
        assert item.opportunity_id not in {entry.opportunity_id for entry in listed.items}
        assert len(listed.items) == 3

        bid = Notice(notice_key="bid:R26BK01699601:000", source_type="bid_notice")
        session.add(bid)
        session.commit()
        assert pre_spec_order_plan_candidates(session, bid.id) is None
        assert pre_spec_order_plan_candidates(session, 999_999) is None


def test_accepting_a_stale_candidate_records_the_decision_without_merging(empty_extensions):
    with _session() as session:
        _plan_row, owner = _add_plan(session, title="통합 행정 플랫폼 구축")
        other_owner = Opportunity(first_registered_stage="pre_spec")
        session.add(other_owner)
        pre_spec = _add_pre_spec(session, title="통합 행정 플랫폼 구축 사전규격", agency="테스트 발주기관")
        create_pre_spec_auto_candidates(session, pre_spec)
        candidate = _candidates(session, pre_spec)[owner.id]
        # 뒤의 공식 연결이 같은 사전규격을 owner에게 준 상태를 만든다.
        official = session.scalar(
            select(OpportunityLink).where(OpportunityLink.notice_id == pre_spec.id,
                                          OpportunityLink.link_type == "official")
        )
        official.opportunity = owner
        session.commit()
        opportunities_before = session.scalar(select(func.count(Opportunity.id)))

        outcome = record_candidate_decision(
            session, candidate.id, decision="accepted", reason="이미 같은 사업", reviewer_name="담당자",
            reviewed_at=SEARCHED_AT,
        )
        session.commit()

        assert outcome.merged is False and outcome.replayed is False
        session.refresh(candidate)
        assert (candidate.status, candidate.human_decision) == ("사람 확인 병합", "accepted")
        assert (candidate.reviewer_name, candidate.review_reason) == ("담당자", "이미 같은 사업")
        assert _owner(session, notice=pre_spec).id == owner.id
        assert session.scalar(select(func.count(Opportunity.id))) == opportunities_before
        assert session.scalar(
            select(func.count(Opportunity.id)).where(Opportunity.merged_into_opportunity_id.is_not(None))
        ) == 0
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == HUMAN_MERGE_ACTION)) is None
        replay = record_candidate_decision(
            session, candidate.id, decision="accepted", reason="이미 같은 사업", reviewer_name="담당자",
        )
        assert replay.replayed is True
