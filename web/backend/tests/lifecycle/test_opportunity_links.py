from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle.ingest.contracts import NoticeContract
from app.lifecycle.ingest.loader import _upsert_notice, resolve_order_plan_opportunity_links
from app.lifecycle.models import (
    CollectedRecordIndex,
    CollectedRecordToken,
    IngestWarning,
    Notice,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from app.lifecycle.services.opportunity_integrity import authoritative_link_predicate


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return engine, Session(engine)


def _run(session: Session, run_id: str = "opportunity-run") -> Run:
    run = Run(id=run_id, generated_at=datetime(2026, 8, 29, tzinfo=timezone.utc))
    session.add(run)
    session.flush()
    return run


def test_official_keys_create_confirmed_links_with_evidence_and_merge_records():
    engine, session = _session()
    try:
        run = _run(session)
        plan = OrderPlan(order_plan_unty_no="R26DD20853714", title="계획")
        pre_spec = Notice(
            notice_key="pre_spec:R26BD00267196",
            source_type="pre_spec",
            title="사전규격",
            lifecycle_json={"pre_spec_no": "R26BD00267196"},
        )
        session.add_all([plan, pre_spec])
        session.flush()

        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id=pre_spec.notice_key,
                source_type="pre_spec",
                lifecycle={"pre_spec_no": "R26BD00267196"},
            ),
            {"source_type": "pre_spec"},
            "Asia/Seoul",
        )
        bid = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                title="본공고",
                lifecycle={
                    "order_plan_no": "R26DD20853714",
                    "pre_spec_no": "R26BD00267196",
                },
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        assert bid is not None
        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 1
        assert opportunities[0].first_registered_stage == "pre_spec"
        links = session.scalars(
            select(OpportunityLink).where(OpportunityLink.opportunity_id == opportunities[0].id)
        ).all()
        assert {link.status for link in links} == {"확정"}
        assert {link.evidence_external_no for link in links} >= {
            "R26DD20853714",
            "R26BD00267196",
        }
        assert any(
            link.notice_id == pre_spec.id and link.evidence_bid_no == bid.bid_no
            for link in links
        )
        assert any(link.order_plan_id == plan.id for link in links)
        assert any(link.notice_id == bid.id for link in links)
        assert any(link.notice_id == pre_spec.id for link in links)
    finally:
        session.close()
        engine.dispose()


def test_bid_key_resolves_the_collector_pre_spec_notice_key():
    """The collector's canonical key is ``pre:<bfSpecRgstNo>``."""
    engine, session = _session()
    try:
        run = _run(session, "collector-key-run")
        plan = OrderPlan(order_plan_unty_no="R26DD20853714", title="계획")
        pre_spec = Notice(
            notice_key="pre:R26BD00267196",
            source_type="pre_spec",
            title="사전규격",
            lifecycle_json={"pre_spec_no": "R26BD00267196"},
        )
        session.add_all([plan, pre_spec])
        session.flush()

        bid = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"pre_spec_no": "R26BD00267196"},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        assert bid is not None
        links = session.scalars(select(OpportunityLink)).all()
        assert any(link.notice_id == pre_spec.id and link.status == "확정" for link in links)
        assert any(link.notice_id == bid.id and link.status == "확정" for link in links)
    finally:
        session.close()
        engine.dispose()


def test_order_plan_is_recorded_as_the_first_registration_stage():
    engine, session = _session()
    try:
        run = _run(session, "plan-origin-run")
        plan = OrderPlan(order_plan_unty_no="R26DD20853714")
        session.add(plan)
        session.flush()

        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": plan.order_plan_unty_no},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        opportunity = session.scalar(select(Opportunity))
        assert opportunity is not None
        assert opportunity.first_registered_stage == "order_plan"
        assert {link.stage for link in opportunity.links} == {"order_plan", "notice"}
    finally:
        session.close()
        engine.dispose()


def test_plan_bid_reference_is_an_exact_official_reverse_link():
    engine, session = _session()
    try:
        run = _run(session, "reverse-key-run")
        plan = OrderPlan(
            order_plan_unty_no="R26DD20853714",
            bid_ntice_no_list="R26BK01696186000,R26BK99999999000",
        )
        session.add(plan)
        session.flush()

        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        link = session.scalar(
            select(OpportunityLink).where(OpportunityLink.order_plan_id == plan.id)
        )
        assert link is not None
        assert link.status == "확정"
        assert link.evidence_external_no == plan.order_plan_unty_no
        assert link.evidence_bid_no == "R26BK01696186"
    finally:
        session.close()
        engine.dispose()


def test_candidate_is_not_automatically_confirmed_and_rejection_is_retained():
    engine, session = _session()
    try:
        opportunity = Opportunity(first_registered_stage="pre_spec")
        candidate_notice = Notice(
            notice_key="pre_spec:CANDIDATE",
            source_type="pre_spec",
            title="후보",
        )
        session.add_all([opportunity, candidate_notice])
        session.flush()
        candidate = OpportunityLink(
            opportunity=opportunity,
            notice=candidate_notice,
            stage="notice",
            link_type="candidate",
            status="후보 확인 대기",
            search_strategy="longest_fragment",
            agency_match=False,
        )
        session.add(candidate)
        session.commit()

        candidate.status = "사람 확인 완료"
        candidate.human_decision = "rejected"
        candidate.reviewer_name = "담당자"
        candidate.reviewed_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
        candidate.review_reason = "기관이 다름"
        session.commit()

        stored = session.get(OpportunityLink, candidate.id)
        assert stored is not None
        assert stored.status != "확정"
        assert stored.human_decision == "rejected"
        assert stored.notice_id == candidate_notice.id
    finally:
        session.close()
        engine.dispose()


def test_name_search_metadata_does_not_create_an_automatic_link():
    engine, session = _session()
    try:
        run = _run(session, "candidate-source-run")
        bid = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                title="이름 검색 후보가 있는 공고",
                candidate_sources=["full"],
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        assert bid is not None
        opportunity = session.scalar(select(Opportunity))
        assert opportunity is not None
        assert opportunity.first_registered_stage == "bid_notice"
        links = session.scalars(select(OpportunityLink)).all()
        assert len(links) == 1
        assert links[0].link_type == "official"
        assert links[0].notice_id == bid.id
    finally:
        session.close()
        engine.dispose()


def test_rejected_candidate_does_not_merge_or_own_an_official_target():
    engine, session = _session()
    try:
        run = _run(session, "merge-run")
        plan = OrderPlan(order_plan_unty_no="R26DD20853714")
        pre_spec = Notice(
            notice_key="pre:R26BD00267196",
            source_type="pre_spec",
            lifecycle_json={"pre_spec_no": "R26BD00267196"},
        )
        plan_opportunity = Opportunity(
            first_registered_stage="order_plan",
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        pre_spec_opportunity = Opportunity(
            first_registered_stage="pre_spec",
            created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        session.add_all([plan, pre_spec, plan_opportunity, pre_spec_opportunity])
        session.flush()
        session.add_all([
            OpportunityLink(
                opportunity=plan_opportunity,
                order_plan=plan,
                stage="order_plan",
                link_type="official",
                status="확정",
                evidence_external_no=plan.order_plan_unty_no,
            ),
            OpportunityLink(
                opportunity=pre_spec_opportunity,
                notice=pre_spec,
                stage="notice",
                link_type="candidate",
                status="사람 확인 완료",
                human_decision="rejected",
                reviewer_name="담당자",
                reviewed_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
                review_reason="기관이 다름",
            ),
        ])
        session.flush()

        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={
                    "order_plan_no": plan.order_plan_unty_no,
                    "pre_spec_no": "R26BD00267196",
                },
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 2
        assert all(item.merged_into_opportunity_id is None for item in opportunities)
        links = session.scalars(select(OpportunityLink)).all()
        assert any(link.human_decision == "rejected" for link in links)
        assert sum(link.status == "확정" for link in links) == 3
    finally:
        session.close()
        engine.dispose()


def test_pending_candidate_on_bid_notice_does_not_merge_or_own_it():
    engine, session = _session()
    try:
        run = _run(session, "bid-merge-run")
        plan = OrderPlan(order_plan_unty_no="R26DD20853714")
        bid = Notice(notice_key="bid:R26BK01696186:000", source_type="bid_notice")
        bid_opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add_all([plan, bid, bid_opportunity])
        session.flush()
        session.add(
            OpportunityLink(
                opportunity=bid_opportunity,
                notice=bid,
                stage="notice",
                link_type="candidate",
                status="후보 확인 대기",
                search_strategy="full",
            )
        )
        session.flush()

        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id=bid.notice_key,
                source_type="bid_notice",
                lifecycle={"order_plan_no": plan.order_plan_unty_no},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 2
        assert all(item.merged_into_opportunity_id is None for item in opportunities)
        assert any(
            link.link_type == "official"
            for opportunity in opportunities
            for link in opportunity.links
        )
        assert any(
            link.link_type == "candidate"
            for opportunity in opportunities
            for link in opportunity.links
        )
    finally:
        session.close()
        engine.dispose()


def test_search_unconfirmed_is_not_absence_and_keeps_attempt_metadata():
    engine, session = _session()
    try:
        opportunity = Opportunity(first_registered_stage="order_plan")
        session.add(opportunity)
        session.flush()
        link = OpportunityLink(
            opportunity=opportunity,
            stage="notice",
            link_type="candidate",
            status="검색 미확인",
            last_searched_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            attempted_strategies_json=["full", "breaking_split", "prefix12"],
        )
        session.add(link)
        session.commit()

        stored = session.get(OpportunityLink, link.id)
        assert stored is not None
        assert stored.notice_id is None
        assert stored.order_plan_id is None
        assert stored.status == "검색 미확인"
        assert stored.attempted_strategies_json == ["full", "breaking_split", "prefix12"]
    finally:
        session.close()
        engine.dispose()


def test_missing_target_is_warned_and_reference_is_retained_as_a_deferred_link():
    engine, session = _session()
    try:
        run = _run(session)
        notice = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": "R26DD20999999"},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        assert notice is not None
        opportunity = session.scalar(select(Opportunity))
        assert opportunity is not None
        assert opportunity.first_registered_stage == "bid_notice"
        links = session.scalars(select(OpportunityLink)).all()
        deferred = next(
            link for link in links if link.evidence_external_no == "R26DD20999999"
        )
        assert deferred.status == "확정"
        assert deferred.stage == "order_plan"
        assert deferred.order_plan_id is None
        assert deferred.notice_id is None
        assert any(link.notice_id == notice.id for link in links)
        warning = session.scalar(
            select(IngestWarning).where(IngestWarning.code == "opportunity_link_target_missing")
        )
        assert warning is not None
        assert warning.context_json["external_key"] == "R26DD20999999"
        assert warning.context_json["requires_human_review"] is True
    finally:
        session.close()
        engine.dispose()


def test_nonstandard_order_plan_key_is_safe_and_recorded_as_parse_failure():
    engine, session = _session()
    try:
        run = _run(session)
        _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": "P812026007CB-00"},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        deferred = session.scalar(
            select(OpportunityLink).where(
                OpportunityLink.evidence_external_no == "P812026007CB-00"
            )
        )
        assert deferred is not None
        assert deferred.stage == "order_plan"
        assert deferred.order_plan_id is None
        assert deferred.notice_id is None
        warning = session.scalar(
            select(IngestWarning).where(
                IngestWarning.code == "opportunity_link_key_parse_failed"
            )
        )
        assert warning is not None
        assert warning.context_json["external_key"] == "P812026007CB-00"
        assert warning.context_json["resolution"] == "parse_failed"
    finally:
        session.close()
        engine.dispose()


def test_bid_without_upstream_reference_registers_bid_first_opportunity():
    engine, session = _session()
    try:
        run = _run(session, "bid-first-run")
        bid = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                title="발주계획 없는 공고",
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()

        assert bid is not None
        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 1
        assert opportunities[0].first_registered_stage == "bid_notice"
        links = session.scalars(select(OpportunityLink)).all()
        assert len(links) == 1
        assert links[0].notice_id == bid.id
        assert links[0].order_plan_id is None
    finally:
        session.close()
        engine.dispose()


def test_late_order_plan_attaches_to_waiting_bid_opportunity():
    engine, session = _session()
    try:
        run = _run(session, "deferred-plan-run")
        reference = "R26DD20999999"
        bid = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": reference},
            ),
            {},
            "Asia/Seoul",
        )
        session.commit()
        assert bid is not None

        opportunity_before = session.scalar(select(Opportunity))
        assert opportunity_before is not None
        plan = OrderPlan(order_plan_unty_no=reference, title="늦게 도착한 계획")
        session.add(plan)
        assert resolve_order_plan_opportunity_links(session, plan) == 1
        session.commit()

        assert session.query(Opportunity).count() == 1
        opportunity_after = session.scalar(select(Opportunity))
        assert opportunity_after is not None
        assert opportunity_after.id == opportunity_before.id
        link = session.scalar(
            select(OpportunityLink).where(
                OpportunityLink.evidence_external_no == reference,
                OpportunityLink.stage == "order_plan",
            )
        )
        assert link is not None
        assert link.order_plan_id == plan.id
        assert link.opportunity_id == opportunity_after.id
    finally:
        session.close()
        engine.dispose()


def test_standalone_order_plan_gets_an_order_plan_opportunity():
    engine, session = _session()
    try:
        plan = OrderPlan(order_plan_unty_no="R26DD20999999")
        session.add(plan)
        assert resolve_order_plan_opportunity_links(session, plan) == 0
        session.commit()

        opportunity = session.scalar(select(Opportunity))
        assert opportunity is not None
        assert opportunity.first_registered_stage == "order_plan"
        link = session.scalar(
            select(OpportunityLink).where(OpportunityLink.order_plan_id == plan.id)
        )
        assert link is not None
        assert link.status == "확정"
    finally:
        session.close()
        engine.dispose()


def test_same_official_reference_merges_opportunities_and_preserves_rejection():
    engine, session = _session()
    try:
        run = _run(session, "official-merge-run")
        reference = "R26DD20999999"
        first = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696186:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": reference},
            ),
            {},
            "Asia/Seoul",
        )
        second = _upsert_notice(
            session,
            run.id,
            NoticeContract(
                notice_id="bid:R26BK01696187:000",
                source_type="bid_notice",
                lifecycle={"order_plan_no": reference},
            ),
            {},
            "Asia/Seoul",
        )
        assert first is not None and second is not None
        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 2
        rejected = OpportunityLink(
            opportunity=opportunities[1],
            notice=second,
            stage="notice",
            link_type="candidate",
            status="사람 확인 완료",
            human_decision="rejected",
            reviewer_name="검토자",
            reviewed_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            review_reason="동일 사업 아님",
        )
        session.add(rejected)
        session.flush()

        plan = OrderPlan(order_plan_unty_no=reference)
        session.add(plan)
        session.flush()
        assert resolve_order_plan_opportunity_links(session, plan) == 1
        session.commit()

        assert session.query(Opportunity).count() == 2
        active = session.scalars(
            select(Opportunity).where(Opportunity.merged_into_opportunity_id.is_(None))
        ).all()
        merged = session.scalars(
            select(Opportunity).where(Opportunity.merged_into_opportunity_id.is_not(None))
        ).all()
        assert len(active) == len(merged) == 1
        assert merged[0].merged_into_opportunity_id == active[0].id
        assert merged[0].merged_at is not None
        assert merged[0].merge_reason == "authoritative_lifecycle_link"
        links = session.scalars(select(OpportunityLink)).all()
        assert any(link.human_decision == "rejected" for link in links)
        assert sum(link.order_plan_id == plan.id for link in links) == 1
        assert all(link.opportunity_id == active[0].id for link in links)
    finally:
        session.close()
        engine.dispose()


def test_similar_names_do_not_merge_without_an_official_reference():
    engine, session = _session()
    try:
        run = _run(session, "no-name-merge-run")
        # Different bid numbers: another order of the same bid number is an
        # official identity and is covered separately below.
        for bid_no in ("R26BK01696186", "R26BK01696199"):
            bid = _upsert_notice(
                session,
                run.id,
                NoticeContract(
                    notice_id=f"bid:{bid_no}:000",
                    source_type="bid_notice",
                    title="비슷한 사업명",
                ),
                {},
                "Asia/Seoul",
            )
            assert bid is not None
        session.commit()

        opportunities = session.scalars(select(Opportunity)).all()
        assert len(opportunities) == 2
        assert {
            link.notice_id
            for link in session.scalars(select(OpportunityLink)).all()
        } == {1, 2}
    finally:
        session.close()
        engine.dispose()


def test_candidate_link_cannot_be_confirmed():
    engine, session = _session()
    try:
        opportunity = Opportunity(first_registered_stage="bid_notice")
        notice = Notice(notice_key="pre:CANDIDATE", source_type="pre_spec")
        session.add_all([opportunity, notice])
        session.flush()
        session.add(
            OpportunityLink(
                opportunity=opportunity,
                notice=notice,
                stage="notice",
                link_type="candidate",
                status="확정",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    finally:
        session.close()
        engine.dispose()


def _upsert(session: Session, run_id: str, notice_id: str, source_type: str, **lifecycle):
    stored = _upsert_notice(
        session,
        run_id,
        NoticeContract(
            notice_id=notice_id,
            source_type=source_type,
            lifecycle=lifecycle or None,
        ),
        {},
        "Asia/Seoul",
    )
    assert stored is not None
    return stored


def _owner_id(session: Session, *, notice=None, order_plan=None) -> int:
    statement = (
        select(OpportunityLink.opportunity_id)
        .join(Opportunity, Opportunity.id == OpportunityLink.opportunity_id)
        .where(
            authoritative_link_predicate(OpportunityLink),
            Opportunity.merged_into_opportunity_id.is_(None),
        )
    )
    if order_plan is not None:
        statement = statement.where(OpportunityLink.order_plan_id == order_plan.id)
    else:
        statement = statement.where(OpportunityLink.notice_id == notice.id)
    return session.scalars(statement).one()


def _index_row(session: Session, run_id: str, kind: str, key: str, tokens: list[str], **values):
    row = CollectedRecordIndex(run_id=run_id, record_kind=kind, record_key=key, **values)
    row.tokens = [CollectedRecordToken(token=token) for token in tokens]
    session.add(row)
    session.flush()
    return row


def test_another_order_of_the_same_bid_number_joins_the_same_opportunity():
    engine, session = _session()
    try:
        run = _run(session, "bid-order-run")
        first = _upsert(session, run.id, "bid:R26BK01696186:000", "bid_notice")
        second = _upsert(session, run.id, "bid:R26BK01696186:001", "bid_notice")
        session.commit()

        assert session.query(Opportunity).count() == 1
        assert _owner_id(session, notice=first) == _owner_id(session, notice=second)
    finally:
        session.close()
        engine.dispose()


def test_plan_bid_reference_is_found_through_the_collection_token_index():
    engine, session = _session()
    try:
        run = _run(session, "token-index-run")
        # The stored plan no longer repeats the list; the index row of its
        # observation does.
        plan = OrderPlan(order_plan_unty_no="R26DD20853714", bid_ntice_no_list=None)
        session.add(plan)
        _index_row(session, run.id, "order_plan", plan.order_plan_unty_no, ["R26BK01696186000"])
        session.flush()

        bid = _upsert(session, run.id, "bid:R26BK01696186:000", "bid_notice")
        session.commit()

        link = session.scalars(
            select(OpportunityLink).where(OpportunityLink.order_plan_id == plan.id)
        ).one()
        assert link.status == "확정" and link.evidence_bid_no == "R26BK01696186"
        assert link.opportunity_id == _owner_id(session, notice=bid)
    finally:
        session.close()
        engine.dispose()


def test_ambiguous_plan_bid_reference_is_not_linked_and_is_warned():
    engine, session = _session()
    try:
        run = _run(session, "ambiguous-plan-run")
        indexed = OrderPlan(order_plan_unty_no="R26DD20853714")
        # No index rows: its stored list is narrowed in SQL and parsed.
        unindexed = OrderPlan(
            order_plan_unty_no="R26DD20853715",
            bid_ntice_no_list="R26BK01696186000",
        )
        session.add_all([indexed, unindexed])
        _index_row(session, run.id, "order_plan", indexed.order_plan_unty_no, ["R26BK01696186000"])
        session.flush()

        _upsert(session, run.id, "bid:R26BK01696186:000", "bid_notice")
        session.commit()

        assert session.scalar(
            select(OpportunityLink).where(OpportunityLink.order_plan_id.is_not(None))
        ) is None
        warning = session.scalar(
            select(IngestWarning).where(
                IngestWarning.code == "opportunity_link_reference_ambiguous"
            )
        )
        assert warning is not None
        assert warning.context_json["target_type"] == "order_plan"
        assert warning.context_json["external_key"] == "R26BK01696186000"
    finally:
        session.close()
        engine.dispose()


def test_bid_without_pre_spec_key_joins_the_pre_spec_whose_token_names_it():
    engine, session = _session()
    try:
        run = _run(session, "pre-spec-token-run")
        pre_spec = _upsert(
            session,
            run.id,
            "pre:R26BD00267196",
            "pre_spec",
            pre_spec_no="R26BD00267196",
            bid_ntice_no_list="R26BK01696186,R26BK01690000",
        )
        bid = _upsert(session, run.id, "bid:R26BK01696186:000", "bid_notice")
        session.commit()

        assert session.query(Opportunity).count() == 1
        link = session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.notice_id == pre_spec.id,
                authoritative_link_predicate(OpportunityLink),
            )
        ).one()
        assert link.evidence_external_no == "R26BD00267196"
        assert link.evidence_bid_no == "R26BK01696186"
        assert _owner_id(session, notice=bid) == link.opportunity_id
        assert session.get(Opportunity, link.opportunity_id).first_registered_stage == "pre_spec"
    finally:
        session.close()
        engine.dispose()


def test_reobserved_pre_spec_token_attaches_a_stored_bid_both_ways():
    engine, session = _session()
    try:
        first_run = _run(session, "bid-before-pre-spec-run")
        bid = _upsert(session, first_run.id, "bid:R26BK01696186:000", "bid_notice")
        # A bid carrying its own bfSpecRgstNo keeps that authoritative key.
        keyed = _upsert(
            session,
            first_run.id,
            "bid:R26BK01696186:001",
            "bid_notice",
            pre_spec_no="R26BD00999999",
        )
        session.commit()
        bid_owner = _owner_id(session, notice=bid)
        assert _owner_id(session, notice=keyed) == bid_owner

        second_run = Run(
            id="pre-spec-after-bid-run",
            generated_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        session.add(second_run)
        session.flush()
        pre_spec = _upsert(
            session,
            second_run.id,
            "pre:R26BD00267196",
            "pre_spec",
            pre_spec_no="R26BD00267196",
            bid_ntice_no_list="R26BK01696186",
        )
        session.commit()

        assert _owner_id(session, notice=pre_spec) == bid_owner
        link = session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.notice_id == pre_spec.id,
                authoritative_link_predicate(OpportunityLink),
            )
        ).one()
        assert link.evidence_bid_no == "R26BK01696186"
        stored = session.get(Opportunity, bid_owner)
        assert stored.first_registered_stage == "pre_spec"
        # Only the keyed bid's missing pre-spec is warned; the token link is
        # neither ambiguous nor a refused merge.
        assert set(session.scalars(select(IngestWarning.code))) == {
            "opportunity_link_target_missing"
        }
    finally:
        session.close()
        engine.dispose()


def test_bid_number_claimed_by_two_pre_specs_stays_unlinked_with_a_warning():
    engine, session = _session()
    try:
        run = _run(session, "ambiguous-pre-spec-run")
        for number in ("R26BD00267196", "R26BD00267197"):
            _upsert(
                session,
                run.id,
                f"pre:{number}",
                "pre_spec",
                pre_spec_no=number,
                bid_ntice_no_list="R26BK01696186",
            )
        bid = _upsert(session, run.id, "bid:R26BK01696186:000", "bid_notice")
        session.commit()

        assert session.get(Opportunity, _owner_id(session, notice=bid)).first_registered_stage == "bid_notice"
        assert session.query(Opportunity).count() == 3
        warning = session.scalar(
            select(IngestWarning).where(
                IngestWarning.code == "opportunity_link_reference_ambiguous",
                IngestWarning.context_json["target_type"].as_string() == "pre_spec",
            )
        )
        assert warning is not None
        assert warning.context_json["external_key"] == "R26BK01696186"
    finally:
        session.close()
        engine.dispose()


def test_late_plan_between_two_tracked_waiting_opportunities_gets_its_own_owner():
    engine, session = _session()
    try:
        run = _run(session, "plan-confirmation-run")
        reference = "R26DD20999999"
        owners = []
        for bid_no, status in (("R26BK01696186", "계속 추적"), ("R26BK01696187", "보류")):
            bid = _upsert(session, run.id, f"bid:{bid_no}:000", "bid_notice", order_plan_no=reference)
            owner = session.get(Opportunity, _owner_id(session, notice=bid))
            owner.tracking_status = status
            owner.tracking_reason = "사람 선택"
            owner.tracking_selected_by = "담당자"
            owner.tracking_selected_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
            owners.append(owner)
        session.commit()

        plan = OrderPlan(order_plan_unty_no=reference)
        session.add(plan)
        assert resolve_order_plan_opportunity_links(session, plan, run_id=run.id) == 0
        session.commit()

        plan_owner = session.get(Opportunity, _owner_id(session, order_plan=plan))
        assert plan_owner.id not in {item.id for item in owners}
        assert plan_owner.first_registered_stage == "order_plan"
        assert all(item.merged_into_opportunity_id is None for item in owners)
        candidates = session.scalars(
            select(OpportunityLink)
            .where(OpportunityLink.search_strategy == "merge_confirmation")
            .order_by(OpportunityLink.opportunity_id)
        ).all()
        assert [
            (item.opportunity_id, item.order_plan_id, item.stage, item.status)
            for item in candidates
        ] == [
            (owners[0].id, plan.id, "order_plan", "후보 확인 대기"),
            (owners[1].id, plan.id, "order_plan", "후보 확인 대기"),
        ]
        # The waiting references stay with the people who own them.
        waiting = session.scalars(
            select(OpportunityLink).where(
                OpportunityLink.evidence_external_no == reference,
                OpportunityLink.order_plan_id.is_(None),
            )
        ).all()
        assert {item.opportunity_id for item in waiting} == {item.id for item in owners}
        warning = session.scalars(
            select(IngestWarning).where(
                IngestWarning.code == "opportunity_merge_confirmation_required"
            )
        ).one()
        assert warning.context_json["order_plan_no"] == reference
    finally:
        session.close()
        engine.dispose()
