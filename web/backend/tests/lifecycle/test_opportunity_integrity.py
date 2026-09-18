"""Focused authoritative-link and non-destructive merge regression tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.models import AuditEvent
from app.lifecycle.ingest.contracts import NoticeContract
from app.lifecycle.ingest.loader import _merge_opportunities, _target_opportunities, _upsert_notice
from app.lifecycle.models import IngestWarning, Notice, Opportunity, OpportunityLink, OrderPlan, Run
from app.lifecycle.services.opportunity_integrity import (
    OpportunityIntegrityError,
    authoritative_link_predicate,
    decide_candidate_link,
    record_candidate_decision,
)
from tests.postgres import migrated_engine, requires_postgres


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


def _official(opportunity, *, notice=None, order_plan=None, evidence="EVIDENCE"):
    return OpportunityLink(
        opportunity=opportunity,
        notice=notice,
        order_plan=order_plan,
        stage="order_plan" if order_plan is not None else "notice",
        link_type="official",
        status="확정",
        evidence_external_no=evidence,
    )


def _tracked(stage: str, status: str, *, created_hour: int = 0, name: str = "담당자"):
    return Opportunity(
        first_registered_stage=stage,
        tracking_status=status,
        tracking_reason="사람이 고른 추적 상태",
        tracking_selected_by=name,
        tracking_selected_at=datetime(2026, 8, 30, created_hour, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 30, created_hour, tzinfo=timezone.utc),
    )


def _owner_of(session: Session, notice: Notice) -> Opportunity:
    return session.scalars(
        select(Opportunity)
        .join(OpportunityLink, OpportunityLink.opportunity_id == Opportunity.id)
        .where(
            OpportunityLink.notice_id == notice.id,
            authoritative_link_predicate(OpportunityLink),
        )
    ).one()


def test_single_recheck_state_is_retained_and_takes_the_earliest_stage():
    engine = _engine()
    try:
        with Session(engine) as session:
            notice = Notice(notice_key="bid:RECHECK", source_type="bid_notice")
            older_notice = Notice(notice_key="pre:OLDER", source_type="pre_spec")
            signaled = Opportunity(
                first_registered_stage="bid_notice",
                created_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            )
            other = Opportunity(
                first_registered_stage="pre_spec",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            session.add_all([notice, older_notice, signaled, other])
            session.flush()
            link = _official(signaled, notice=notice, evidence="RECHECK")
            moved = _official(other, notice=older_notice, evidence="OLDER")
            session.add_all([link, moved])
            session.flush()
            signal_at = datetime(2026, 8, 31, 1, 2, 3, 456789, tzinfo=timezone.utc)
            signaled.recheck_signal_at = signal_at
            signaled.recheck_signal_link_id = link.id
            session.flush()

            retained = _merge_opportunities(session, [other, signaled])
            session.commit()

            # A recheck signal is human-facing state: the signaled row wins
            # over the older untouched row and keeps its signal as it was.
            assert retained is not None and retained.id == signaled.id
            assert retained.first_registered_stage == "pre_spec"
            assert retained.recheck_signal_at == signal_at
            assert retained.recheck_signal_link_id == link.id
            assert retained.merged_into_opportunity_id is None
            stored_other = session.get(Opportunity, other.id)
            assert stored_other.merged_into_opportunity_id == signaled.id
            assert stored_other.merged_at.tzinfo is not None
            assert stored_other.first_registered_stage == "pre_spec"
            assert session.get(OpportunityLink, moved.id).opportunity_id == signaled.id
    finally:
        engine.dispose()


def test_two_human_states_refuse_merge_without_writing():
    engine = _engine()
    try:
        with Session(engine) as session:
            notice = Notice(notice_key="bid:REFUSED", source_type="bid_notice")
            tracked = _tracked("order_plan", "계속 추적", created_hour=1)
            signaled = Opportunity(first_registered_stage="bid_notice")
            session.add_all([notice, tracked, signaled])
            session.flush()
            link = _official(signaled, notice=notice, evidence="REFUSED")
            session.add(link)
            session.flush()
            signaled.recheck_signal_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
            signaled.recheck_signal_link_id = link.id
            session.commit()

            with pytest.raises(OpportunityIntegrityError) as caught:
                _merge_opportunities(session, [signaled, tracked])
            assert caught.value.code == "opportunity_merge_state_conflict"
            assert caught.value.details == {
                "opportunity_ids": sorted([tracked.id, signaled.id])
            }
            assert not session.dirty and not session.new
            assert signaled.merged_into_opportunity_id is None
            assert tracked.merged_into_opportunity_id is None
            assert link.opportunity_id == signaled.id
    finally:
        engine.dispose()


def test_ingest_merge_retains_the_tracked_plan_and_signals_the_arriving_bid():
    """Tracked plan + untouched pre-spec + a bid naming both official keys."""

    engine = _engine()
    try:
        with Session(engine) as session:
            run = Run(
                id="integrity-merge-run",
                generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            )
            plan = OrderPlan(order_plan_unty_no="R26DD20777777")
            pre_spec = Notice(
                notice_key="pre:R26BD00277777",
                source_type="pre_spec",
                lifecycle_json={"pre_spec_no": "R26BD00277777"},
            )
            selected = _tracked("order_plan", "계속 추적", created_hour=5)
            untouched = Opportunity(
                first_registered_stage="pre_spec",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            session.add_all([run, plan, pre_spec, selected, untouched])
            session.flush()
            session.add_all(
                [
                    _official(selected, order_plan=plan, evidence=plan.order_plan_unty_no),
                    _official(untouched, notice=pre_spec, evidence="R26BD00277777"),
                ]
            )
            session.commit()
            selected_state = (
                selected.tracking_status,
                selected.tracking_reason,
                selected.tracking_selected_by,
                selected.tracking_selected_at,
            )

            bid = _upsert_notice(
                session,
                run.id,
                NoticeContract(
                    notice_id="bid:R26BK01697777:000",
                    source_type="bid_notice",
                    lifecycle={
                        "order_plan_no": plan.order_plan_unty_no,
                        "pre_spec_no": "R26BD00277777",
                    },
                ),
                {},
                "Asia/Seoul",
            )
            session.commit()

            assert bid is not None
            stored = session.get(Opportunity, selected.id)
            assert stored.merged_into_opportunity_id is None
            assert (
                stored.tracking_status,
                stored.tracking_reason,
                stored.tracking_selected_by,
                stored.tracking_selected_at,
            ) == selected_state
            assert stored.first_registered_stage == "order_plan"
            assert session.get(Opportunity, untouched.id).merged_into_opportunity_id == selected.id
            assert _owner_of(session, bid).id == selected.id
            assert _owner_of(session, pre_spec).id == selected.id
            bid_link = session.scalars(
                select(OpportunityLink).where(OpportunityLink.notice_id == bid.id)
            ).one()
            assert stored.recheck_signal_link_id == bid_link.id
            assert stored.recheck_signal_at is not None
            assert stored.recheck_signal_at.tzinfo is not None
            events = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "opportunity.recheck_signal.created",
                    AuditEvent.aggregate_id == str(selected.id),
                )
            ).all()
            assert [event.safe_metadata["link_id"] for event in events] == [bid_link.id]
            assert session.scalar(select(func.count()).select_from(IngestWarning)) == 0
    finally:
        engine.dispose()


def test_ingest_between_two_human_selected_opportunities_asks_for_merge_confirmation():
    engine = _engine()
    try:
        with Session(engine) as session:
            runs = [
                Run(
                    id=f"integrity-confirm-run-{index}",
                    generated_at=datetime(2026, 8, 31, index, tzinfo=timezone.utc),
                )
                for index in (1, 2)
            ]
            plan = OrderPlan(order_plan_unty_no="R26DD20788888")
            pre_spec = Notice(
                notice_key="pre:R26BD00288888",
                source_type="pre_spec",
                lifecycle_json={"pre_spec_no": "R26BD00288888"},
            )
            plan_owner = _tracked("order_plan", "계속 추적", created_hour=1, name="계획 담당자")
            pre_spec_owner = _tracked("pre_spec", "보류", created_hour=2, name="규격 담당자")
            session.add_all([*runs, plan, pre_spec, plan_owner, pre_spec_owner])
            session.flush()
            session.add_all(
                [
                    _official(plan_owner, order_plan=plan, evidence=plan.order_plan_unty_no),
                    _official(pre_spec_owner, notice=pre_spec, evidence="R26BD00288888"),
                ]
            )
            session.commit()
            contract = NoticeContract(
                notice_id="bid:R26BK01698888:000",
                source_type="bid_notice",
                lifecycle={
                    "order_plan_no": plan.order_plan_unty_no,
                    "pre_spec_no": "R26BD00288888",
                },
            )

            bid = _upsert_notice(session, runs[0].id, contract, {}, "Asia/Seoul")
            session.commit()

            assert bid is not None
            # The bid is never left without an owner.
            bid_owner = _owner_of(session, bid)
            assert bid_owner.id not in {plan_owner.id, pre_spec_owner.id}
            assert bid_owner.first_registered_stage == "bid_notice"
            assert bid_owner.tracking_status == "미선택"
            assert bid_owner.recheck_signal_at is None
            for owner in (plan_owner, pre_spec_owner):
                session.refresh(owner)
                assert owner.merged_into_opportunity_id is None
                assert owner.recheck_signal_at is None
            candidates = session.scalars(
                select(OpportunityLink)
                .where(OpportunityLink.search_strategy == "merge_confirmation")
                .order_by(OpportunityLink.opportunity_id)
            ).all()
            assert [
                (item.opportunity_id, item.notice_id, item.stage, item.link_type, item.status)
                for item in candidates
            ] == [
                (plan_owner.id, bid.id, "notice", "candidate", "후보 확인 대기"),
                (pre_spec_owner.id, bid.id, "notice", "candidate", "후보 확인 대기"),
            ]
            # The disputed upstream records stay with their owners.
            assert _owner_of(session, pre_spec).id == pre_spec_owner.id
            warnings = session.scalars(
                select(IngestWarning).where(IngestWarning.run_id == runs[0].id)
            ).all()
            assert [item.code for item in warnings] == ["opportunity_merge_confirmation_required"]
            assert warnings[0].context_json["notice_id"] == bid.notice_key
            assert warnings[0].context_json["held_opportunity_ids"] == sorted(
                [plan_owner.id, pre_spec_owner.id]
            )
            assert warnings[0].context_json["created_candidate_count"] == 2
            assert warnings[0].context_json["requires_human_review"] is True

            # A rejected answer and a pending question are both kept as they
            # are when the same bid is observed again.
            decide_candidate_link(
                session,
                candidates[0].id,
                decision="rejected",
                reason="다른 사업",
                reviewer_name="계획 담당자",
                reviewed_at=datetime(2026, 8, 31, 3, tzinfo=timezone.utc),
            )
            session.commit()
            again = _upsert_notice(
                session,
                runs[1].id,
                contract.model_copy(update={"title": "재관측"}),
                {},
                "Asia/Seoul",
            )
            session.commit()

            assert again is not None and _owner_of(session, again).id == bid_owner.id
            assert session.scalar(
                select(func.count())
                .select_from(OpportunityLink)
                .where(OpportunityLink.search_strategy == "merge_confirmation")
            ) == 2
            second = session.scalars(
                select(IngestWarning).where(IngestWarning.run_id == runs[1].id)
            ).all()
            assert [item.code for item in second] == ["opportunity_merge_confirmation_required"]
            assert second[0].context_json["created_candidate_count"] == 0
            assert session.scalar(
                select(IngestWarning).where(
                    IngestWarning.code == "opportunity_merge_state_conflict"
                )
            ) is None
    finally:
        engine.dispose()


def _candidate_merge_fixture(session: Session, *, candidate_owner_status: str | None):
    target = Notice(notice_key="pre:R26BD00299999", source_type="pre_spec")
    candidate_owner = (
        _tracked("order_plan", candidate_owner_status, created_hour=3, name="후보 담당자")
        if candidate_owner_status is not None
        else Opportunity(first_registered_stage="order_plan")
    )
    target_owner = _tracked("pre_spec", "보류", created_hour=1, name="규격 담당자")
    session.add_all([target, candidate_owner, target_owner])
    session.flush()
    official = _official(target_owner, notice=target, evidence="R26BD00299999")
    candidate = OpportunityLink(
        opportunity=candidate_owner,
        notice=target,
        stage="notice",
        link_type="candidate",
        status="후보 확인 대기",
        search_strategy="full",
    )
    session.add_all([official, candidate])
    session.commit()
    return target, candidate_owner, target_owner, official, candidate


def test_accepting_candidate_owned_elsewhere_merges_by_the_rule_without_signal():
    engine = _engine()
    try:
        with Session(engine) as session:
            target, candidate_owner, target_owner, official, candidate = _candidate_merge_fixture(
                session, candidate_owner_status=None
            )
            reviewed_at = datetime(2026, 9, 1, 2, 3, 4, 567890, tzinfo=timezone.utc)

            outcome = record_candidate_decision(
                session,
                candidate.id,
                decision="accepted",
                reason="같은 사업으로 확인",
                reviewer_name="검토자",
                reviewed_at=reviewed_at,
            )
            session.commit()

            # Only the target owner holds human state, so it is retained even
            # though the candidate belonged to the other opportunity.
            assert outcome.merged
            assert outcome.retained_opportunity_id == target_owner.id
            assert outcome.secondary_opportunity_id == candidate_owner.id
            stored_candidate = session.get(OpportunityLink, candidate.id)
            assert stored_candidate.status == "사람 확인 병합"
            assert stored_candidate.human_decision == "accepted"
            assert stored_candidate.opportunity_id == target_owner.id
            assert stored_candidate.reviewed_at == reviewed_at
            assert session.get(OpportunityLink, official.id).opportunity_id == target_owner.id
            assert _owner_of(session, target).id == target_owner.id
            retained = session.get(Opportunity, target_owner.id)
            assert retained.tracking_status == "보류"
            assert retained.tracking_selected_by == "규격 담당자"
            assert retained.first_registered_stage == "order_plan"
            assert retained.recheck_signal_at is None
            secondary = session.get(Opportunity, candidate_owner.id)
            assert secondary.merged_into_opportunity_id == target_owner.id
            assert secondary.merge_reason == "human_confirmed_candidate"
            assert secondary.merged_at == reviewed_at
            merged_audit = session.scalars(
                select(AuditEvent).where(AuditEvent.action == "opportunity.merged.human_confirmed")
            ).one()
            assert merged_audit.actor_kind == "human"
            assert merged_audit.claimed_name == "검토자"
            assert merged_audit.safe_metadata == {
                "retained_opportunity_id": target_owner.id,
                "secondary_opportunity_id": candidate_owner.id,
                "opportunity_link_id": candidate.id,
            }
            assert session.scalar(
                select(AuditEvent).where(AuditEvent.action == "opportunity.recheck_signal.created")
            ) is None

            replay = record_candidate_decision(
                session,
                candidate.id,
                decision="accepted",
                reason="같은 사업으로 확인",
                reviewer_name="검토자",
            )
            assert replay.replayed and not replay.merged
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == 2
    finally:
        engine.dispose()


def test_accepting_candidate_between_two_human_states_is_refused_with_both_states():
    engine = _engine()
    try:
        with Session(engine) as session:
            _target, candidate_owner, target_owner, official, candidate = _candidate_merge_fixture(
                session, candidate_owner_status="계속 추적"
            )

            with pytest.raises(OpportunityIntegrityError) as caught:
                record_candidate_decision(
                    session,
                    candidate.id,
                    decision="accepted",
                    reason="같은 사업으로 확인",
                    reviewer_name="검토자",
                )
            session.rollback()

            assert caught.value.code == "candidate_merge_state_conflict"
            assert caught.value.details == {
                "opportunities": [
                    {
                        "id": candidate_owner.id,
                        "tracking_status": "계속 추적",
                        "tracking_selected_by": "후보 담당자",
                        "tracking_selected_at": "2026-08-30T03:00:00+00:00",
                        "recheck_signal": False,
                    },
                    {
                        "id": target_owner.id,
                        "tracking_status": "보류",
                        "tracking_selected_by": "규격 담당자",
                        "tracking_selected_at": "2026-08-30T01:00:00+00:00",
                        "recheck_signal": False,
                    },
                ]
            }
            stored = session.get(OpportunityLink, candidate.id)
            assert stored.status == "후보 확인 대기" and stored.human_decision is None
            assert session.get(OpportunityLink, official.id).opportunity_id == target_owner.id
            assert session.get(Opportunity, candidate_owner.id).merged_into_opportunity_id is None
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    finally:
        engine.dispose()


@requires_postgres
def test_accepted_merge_candidate_passes_the_authoritative_unique_index_on_postgresql():
    with migrated_engine() as engine:
        with Session(engine) as session:
            _target, candidate_owner, target_owner, official, candidate = _candidate_merge_fixture(
                session, candidate_owner_status=None
            )
            ids = {
                "notice": official.notice_id,
                "official": official.id,
                "candidate": candidate.id,
                "candidate_owner": candidate_owner.id,
                "target_owner": target_owner.id,
            }
            record_candidate_decision(
                session,
                ids["candidate"],
                decision="accepted",
                reason="같은 사업으로 확인",
                reviewer_name="검토자",
                reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            session.commit()

        with Session(engine) as session:
            rows = session.execute(
                select(OpportunityLink.id, OpportunityLink.opportunity_id, OpportunityLink.status)
                .where(OpportunityLink.notice_id == ids["notice"])
                .order_by(OpportunityLink.id)
            ).all()
            assert [tuple(row) for row in rows] == [
                (ids["official"], ids["target_owner"], "확정"),
                (ids["candidate"], ids["target_owner"], "사람 확인 병합"),
            ]
            merged = session.get(Opportunity, ids["candidate_owner"])
            assert merged.merged_into_opportunity_id == ids["target_owner"]
            assert merged.merged_at.tzinfo is not None
            # The index still admits exactly one authoritative owner.
            session.add(
                _official(session.get(Opportunity, ids["target_owner"]),
                          notice=session.get(Notice, ids["notice"]),
                          evidence="DUPLICATE")
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
