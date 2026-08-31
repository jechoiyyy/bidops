"""Focused authoritative-link and non-destructive merge regression tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import init_db
from app.ingest.contracts import NoticeContract
from app.ingest.loader import _merge_opportunities, _target_opportunities, _upsert_notice
from app.models import IngestWarning, Notice, Opportunity, OpportunityLink, OrderPlan, Run
from app.services.opportunity_integrity import OpportunityIntegrityError


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return engine


def _candidate(
    opportunity: Opportunity,
    notice: Notice,
    *,
    decision: str | None = None,
) -> OpportunityLink:
    reviewed = decision is not None
    return OpportunityLink(
        opportunity=opportunity,
        notice=notice,
        stage="notice",
        link_type="candidate",
        status="사람 확인 완료" if reviewed else "후보 확인 대기",
        human_decision=decision,
        reviewer_name="검토자" if reviewed else None,
        reviewed_at=(
            datetime(2026, 8, 31, tzinfo=timezone.utc) if reviewed else None
        ),
        review_reason="사람 확인 결과" if reviewed else None,
    )


def test_only_accepted_candidate_owns_target_and_duplicate_authority_is_rejected():
    engine = _engine()
    try:
        with Session(engine) as session:
            notice = Notice(notice_key="pre:AUTHORITY", source_type="pre_spec")
            pending_owner = Opportunity(first_registered_stage="pre_spec")
            rejected_owner = Opportunity(first_registered_stage="pre_spec")
            accepted_owner = Opportunity(first_registered_stage="pre_spec")
            duplicate_owner = Opportunity(first_registered_stage="pre_spec")
            session.add_all(
                [notice, pending_owner, rejected_owner, accepted_owner, duplicate_owner]
            )
            session.flush()
            session.add_all(
                [
                    _candidate(pending_owner, notice),
                    _candidate(rejected_owner, notice, decision="rejected"),
                    _candidate(accepted_owner, notice, decision="accepted"),
                ]
            )
            session.commit()

            owners = _target_opportunities(session, notice=notice)
            assert [item.id for item in owners] == [accepted_owner.id]

            session.add(
                OpportunityLink(
                    opportunity=duplicate_owner,
                    notice=notice,
                    stage="notice",
                    link_type="official",
                    status="확정",
                    evidence_external_no="AUTHORITY",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_merge_preserves_secondary_row_and_rejected_candidate_history():
    engine = _engine()
    try:
        with Session(engine) as session:
            first_notice = Notice(notice_key="bid:MERGE-A", source_type="bid_notice")
            second_notice = Notice(notice_key="bid:MERGE-B", source_type="bid_notice")
            rejected_notice = Notice(notice_key="pre:REJECTED", source_type="pre_spec")
            primary = Opportunity(
                first_registered_stage="bid_notice",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            secondary = Opportunity(
                first_registered_stage="pre_spec",
                created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
            session.add_all(
                [first_notice, second_notice, rejected_notice, primary, secondary]
            )
            session.flush()
            session.add_all(
                [
                    OpportunityLink(
                        opportunity=primary,
                        notice=first_notice,
                        stage="notice",
                        link_type="official",
                        status="확정",
                        evidence_external_no="MERGE-A",
                    ),
                    OpportunityLink(
                        opportunity=secondary,
                        notice=second_notice,
                        stage="notice",
                        link_type="official",
                        status="확정",
                        evidence_external_no="MERGE-B",
                    ),
                    _candidate(secondary, rejected_notice, decision="rejected"),
                ]
            )
            session.flush()

            retained = _merge_opportunities(session, [secondary, primary])
            session.commit()

            assert retained is not None and retained.id == primary.id
            stored_secondary = session.get(Opportunity, secondary.id)
            assert stored_secondary is not None
            assert stored_secondary.merged_into_opportunity_id == primary.id
            assert stored_secondary.merged_at is not None
            assert stored_secondary.merge_reason == "authoritative_lifecycle_link"
            links = session.scalars(select(OpportunityLink)).all()
            assert all(link.opportunity_id == primary.id for link in links)
            assert any(link.human_decision == "rejected" for link in links)
    finally:
        engine.dispose()


def test_recheck_state_blocks_automatic_merge():
    engine = _engine()
    try:
        with Session(engine) as session:
            notice = Notice(notice_key="bid:RECHECK", source_type="bid_notice")
            signaled = Opportunity(first_registered_stage="bid_notice")
            other = Opportunity(first_registered_stage="pre_spec")
            session.add_all([notice, signaled, other])
            session.flush()
            link = OpportunityLink(
                opportunity=signaled,
                notice=notice,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="RECHECK",
            )
            session.add(link)
            session.flush()
            signaled.recheck_signal_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
            signaled.recheck_signal_link_id = link.id
            session.flush()

            with pytest.raises(OpportunityIntegrityError) as caught:
                _merge_opportunities(session, [signaled, other])
            assert caught.value.code == "opportunity_merge_state_conflict"
            assert signaled.merged_into_opportunity_id is None
            assert other.merged_into_opportunity_id is None
    finally:
        engine.dispose()


def test_ingest_merge_conflict_keeps_human_state_and_writes_durable_warning():
    engine = _engine()
    try:
        with Session(engine) as session:
            run = Run(
                id="integrity-warning-run",
                generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            )
            plan = OrderPlan(order_plan_unty_no="R26DD20777777")
            bid = Notice(notice_key="bid:INTEGRITY:000", source_type="bid_notice")
            selected = Opportunity(
                first_registered_stage="order_plan",
                tracking_status="계속 추적",
                tracking_reason="사람이 추적 대상으로 선택",
                tracking_selected_by="담당자",
                tracking_selected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            )
            candidate_owner = Opportunity(first_registered_stage="bid_notice")
            session.add_all([run, plan, bid, selected, candidate_owner])
            session.flush()
            session.add_all(
                [
                    OpportunityLink(
                        opportunity=selected,
                        order_plan=plan,
                        stage="order_plan",
                        link_type="official",
                        status="확정",
                        evidence_external_no=plan.order_plan_unty_no,
                    ),
                    _candidate(candidate_owner, bid, decision="accepted"),
                ]
            )
            session.commit()

            stored = _upsert_notice(
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

            assert stored is not None
            assert selected.tracking_status == "계속 추적"
            assert selected.merged_into_opportunity_id is None
            assert candidate_owner.merged_into_opportunity_id is None
            warning = session.scalar(
                select(IngestWarning).where(
                    IngestWarning.code == "opportunity_merge_state_conflict"
                )
            )
            assert warning is not None
            assert warning.context_json["requires_human_review"] is True
            assert warning.context_json["notice_id"] == bid.notice_key
    finally:
        engine.dispose()
