"""deep_review가 lifecycle 이벤트 hook으로 첨부 fetch 자격을 갱신한다 (명세 §6.2).

회차 적재됨 → 그 회차의 사전규격 공고만, 추적 결정 변경됨 → 그 사업기회에
연결된 사전규격 공고만 재평가한다. 회차 적재 쪽 실패는 savepoint 안에서 삼키고
오늘 loader가 남기던 것과 같은 경고를 건수로 돌려준다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import RunIngestCounts, RunIngestHook, TrackingDecisionHook
from app.deep_review.models import AttachmentFetch
from app.lifecycle.models import (
    Attachment,
    Notice,
    NoticeObservation,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
from app.deep_review.services import deep_review_hooks
from app.deep_review.services.deep_review_hooks import PreSpecAttachmentEligibilityHook

G2B_URL = (
    "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
    "?bfSpecRegNo=R26HOOK00001&fileType=BFDTL&fileSeq=1"
)
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _notice(session: Session, key: str, *, sw: str | None, source_type: str = "pre_spec") -> Notice:
    flags = {"sw_business_status": sw} if sw is not None else {}
    notice = Notice(
        notice_key=key,
        source_type=source_type,
        title=f"{key} 제안요청서",
        agency="테스트 기관",
        qualification_flags_json=flags,
    )
    session.add(notice)
    session.flush()
    return notice


def _g2b_attachment(session: Session, notice: Notice, seq: int) -> Attachment:
    attachment = Attachment(
        notice=notice,
        name=f"file-{seq}.pdf",
        origin="g2b",
        source_url=G2B_URL.replace("fileSeq=1", f"fileSeq={seq}"),
        source_system="g2b",
        source_attachment_key=f"R26HOOK00001:BFDTL:{seq}",
    )
    session.add(attachment)
    session.flush()
    return attachment


def _observe(session: Session, run: Run, notice: Notice) -> None:
    session.add(
        NoticeObservation(notice_id=notice.id, run_id=run.id, observed_at=WHEN, changed_fields_json=[])
    )
    session.flush()


def _fetch_rows(session: Session) -> list[AttachmentFetch]:
    return list(session.scalars(select(AttachmentFetch).order_by(AttachmentFetch.attachment_id)))


def test_hook_implements_both_lifecycle_protocols():
    hook = PreSpecAttachmentEligibilityHook()
    assert isinstance(hook, RunIngestHook)
    assert isinstance(hook, TrackingDecisionHook)


def test_hook_never_claims_a_run_directory(tmp_path: Path):
    assert PreSpecAttachmentEligibilityHook().inspect_run_directory(tmp_path) is None


def test_run_ingested_refreshes_only_the_runs_pre_spec_notices(db_session: Session, tmp_path: Path):
    run = Run(id="20260901-20260907", timezone="Asia/Seoul", generated_at=WHEN)
    other_run = Run(id="20260825-20260831", timezone="Asia/Seoul", generated_at=WHEN)
    db_session.add_all([run, other_run])
    db_session.flush()
    in_run = _notice(db_session, "pre:IN-RUN", sw="Y")
    other = _notice(db_session, "pre:OTHER-RUN", sw="Y")
    bid = _notice(db_session, "bid:IN-RUN", sw="Y", source_type="bid_notice")
    _observe(db_session, run, in_run)
    _observe(db_session, run, bid)
    _observe(db_session, other_run, other)
    eligible = _g2b_attachment(db_session, in_run, 1)
    _g2b_attachment(db_session, other, 2)
    _g2b_attachment(db_session, bid, 3)

    counts = PreSpecAttachmentEligibilityHook().run_ingested(db_session, run.id, tmp_path)

    assert counts == RunIngestCounts()
    rows = _fetch_rows(db_session)
    assert [row.attachment_id for row in rows] == [eligible.id]
    assert rows[0].status == "대기"
    assert rows[0].eligibility_reason == "sw_business_object"


def test_run_ingested_without_pre_spec_notices_is_a_no_op(db_session: Session, tmp_path: Path):
    run = Run(id="20260901-20260907", timezone="Asia/Seoul", generated_at=WHEN)
    db_session.add(run)
    db_session.flush()
    bid = _notice(db_session, "bid:ONLY", sw="Y", source_type="bid_notice")
    _observe(db_session, run, bid)
    _g2b_attachment(db_session, bid, 1)

    counts = PreSpecAttachmentEligibilityHook().run_ingested(db_session, run.id, tmp_path)

    assert counts == RunIngestCounts()
    assert _fetch_rows(db_session) == []


def test_run_ingested_failure_is_isolated_and_reported_as_the_same_warning(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run = Run(id="20260901-20260907", timezone="Asia/Seoul", generated_at=WHEN)
    db_session.add(run)
    db_session.flush()
    first = _notice(db_session, "pre:FAIL-1", sw="Y")
    second = _notice(db_session, "pre:FAIL-2", sw="Y")
    _observe(db_session, run, first)
    _observe(db_session, run, second)
    _g2b_attachment(db_session, first, 1)

    def explode(session, *, notice_ids=None):  # type: ignore[no-untyped-def]
        session.add(AttachmentFetch(attachment_id=999_999, status="대기", eligibility_reason="both", next_attempt_at=WHEN))
        session.flush()
        raise RuntimeError("dialect issue")

    monkeypatch.setattr(deep_review_hooks, "refresh_fetch_eligibility", explode)

    counts = PreSpecAttachmentEligibilityHook().run_ingested(db_session, run.id, tmp_path)

    assert counts.warnings == (
        {
            "level": "warning",
            "code": "attachment_eligibility_refresh_failed",
            "message": "사전규격 첨부 자격 재평가를 완료하지 못했습니다.",
            "context": {"notice_count": 2},
        },
    )
    assert counts.merged_with(RunIngestCounts()).judgments == 0
    # savepoint가 되돌렸으므로 호출자의 transaction은 계속 쓸 수 있고, 실패한
    # 시도가 남긴 행은 없다.
    db_session.flush()
    assert _fetch_rows(db_session) == []
    db_session.commit()


def _tracked_opportunity(session: Session, notice: Notice, *, tracking_status: str) -> Opportunity:
    opportunity = Opportunity(
        first_registered_stage="order_plan",
        tracking_status=tracking_status,
        tracking_reason="테스트 이유",
        tracking_selected_by="테스트 담당자",
        tracking_selected_at=WHEN,
    )
    session.add(opportunity)
    session.flush()
    plan = OrderPlan(order_plan_unty_no=f"R26HOOK{opportunity.id:08d}")
    session.add(plan)
    session.flush()
    session.add_all(
        [
            OpportunityLink(
                opportunity_id=opportunity.id,
                notice_id=notice.id,
                stage="notice",
                link_type="official",
                status="확정",
                evidence_external_no="PRE-HOOK",
            ),
            OpportunityLink(
                opportunity_id=opportunity.id,
                order_plan_id=plan.id,
                stage="order_plan",
                link_type="official",
                status="확정",
                evidence_external_no=plan.order_plan_unty_no,
            ),
        ]
    )
    session.flush()
    return opportunity


def test_tracking_decision_changed_refreshes_the_linked_pre_spec_notices(db_session: Session):
    tracked = _notice(db_session, "pre:TRACKED", sw="N")
    untouched = _notice(db_session, "pre:UNTOUCHED", sw="N")
    opportunity = _tracked_opportunity(db_session, tracked, tracking_status="계속 추적")
    _tracked_opportunity(db_session, untouched, tracking_status="계속 추적")
    expected = _g2b_attachment(db_session, tracked, 1)
    _g2b_attachment(db_session, untouched, 2)
    db_session.commit()

    PreSpecAttachmentEligibilityHook().tracking_decision_changed(db_session, opportunity.id)

    rows = _fetch_rows(db_session)
    assert [row.attachment_id for row in rows] == [expected.id]
    assert rows[0].eligibility_reason == "tracked_order_plan"


def test_tracking_decision_changed_without_linked_pre_specs_is_a_no_op(db_session: Session):
    opportunity = Opportunity(first_registered_stage="order_plan", tracking_status="미선택")
    db_session.add(opportunity)
    db_session.commit()

    PreSpecAttachmentEligibilityHook().tracking_decision_changed(db_session, opportunity.id)

    assert _fetch_rows(db_session) == []
