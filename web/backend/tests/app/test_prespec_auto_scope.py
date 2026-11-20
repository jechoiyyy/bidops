"""사전규격 자동 처리 범위 (2026-11-19 사전규격 단계 수정안 §3 A·§7).

자동 경로 셋 — 첨부 취득 claim, 자동 문서 준비, 자동 개요 enqueue — 은 의견 마감이
지나지 않았거나(마감 미확인 포함) 사업기회가 `추적 중`(계속 추적·보류)인 사전규격만
처리한다. 마감이 지났고 추적 중이 아닌 공고는 사람이 추적을 시작할 때 같은 경로를 탄다.

각 진입점마다 네 경우(마감 전 / 마감 경과·미추적 / 마감 경과·추적 / 마감 미확인)를
같은 표로 확인한다. 진입점 셋이 같은 규칙(`effective_grade.auto_processing_predicate`)을
읽는지가 이 파일의 요점이다. SQLite와 PostgreSQL 두 변형으로 돈다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import init_db
from app.deep_review.models import AttachmentFetch, DocumentBundle, PrespecOverviewRun
from app.deep_review.services import auto_preparation, deep_review_hooks, overview_runs
from app.deep_review.services.auto_preparation import (
    REASON_DEADLINE_PASSED_UNTRACKED,
    REASON_GRADE_NOT_PRIORITY,
    REASON_NO_READY_DOCUMENT,
    auto_preparation_fields,
    maybe_auto_prepare,
)
from app.deep_review.services.deep_review_hooks import PreSpecAttachmentEligibilityHook
from app.deep_review.services.effective_grade import EffectiveGrade, overview_eligible
from app.deep_review.services.prespec_attachments import SOURCE_SYSTEM, claim_next
from app.lifecycle.models import Attachment, Briefing, BriefingItem, Notice, Opportunity, OpportunityLink
from app.lifecycle.services.opportunity_connections import parse_attachment_key
from tests.postgres import migrated_engine, requires_postgres

# SQLite `init_db`는 import된 모델의 테이블만 만든다. 조립된 앱(PATCH 진입점)의 판정
# projection이 읽는 screening 테이블도 세운다.
import app.screening.models  # noqa: E402,F401

G2B_URL = (
    "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
    "?bfSpecRegNo=R26BD00266984&fileType=BFDTL&fileSeq={seq}"
)
NOW = datetime.now(UTC)

#: (이름, 마감, 추적 상태 또는 None, 자동 처리 범위 안인가)
CASES = (
    ("open", NOW + timedelta(days=2), None, True),
    ("passed_untracked", NOW - timedelta(days=1), None, False),
    ("passed_tracked", NOW - timedelta(days=1), "계속 추적", True),
    ("passed_held", NOW - timedelta(days=1), "보류", True),
    ("passed_ended", NOW - timedelta(days=1), "종료", False),
    ("passed_unselected", NOW - timedelta(days=1), "미선택", False),
    ("unknown_deadline", None, None, True),
)
CASE_IDS = tuple(case[0] for case in CASES)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def db(request, monkeypatch):
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "true")
    get_settings.cache_clear()
    if request.param == "postgres":
        with migrated_engine() as engine, Session(engine) as session:
            yield session
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        init_db(engine)
        with Session(engine) as session:
            yield session
        engine.dispose()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_grades(monkeypatch):
    """C-1 판정이 없는 운영 상태: 자격은 개요 플래그의 SW사업대상 완화에서만 온다."""

    for module in (auto_preparation, overview_runs):
        monkeypatch.setattr(module, "effective_grades", lambda _session, _ids: {})


def _notice(session: Session, key: str, *, deadline_at, tracking: str | None, sw: str = "Y") -> Notice:
    notice = Notice(
        notice_key=f"scope:{key}:{uuid4().hex[:8]}",
        source_type="pre_spec",
        title=f"{key} 사전규격",
        deadline_at=deadline_at,
        qualification_flags_json={"sw_business_status": sw},
        raw_source={},
    )
    session.add(notice)
    session.flush()
    if tracking is not None:
        _track(session, notice, tracking)
    return notice


def _track(session: Session, notice: Notice, status: str) -> Opportunity:
    selected = status != "미선택"
    opportunity = Opportunity(
        first_registered_stage="pre_spec",
        tracking_status=status,
        tracking_reason="추적 이유" if selected else None,
        tracking_selected_by="담당자" if selected else None,
        tracking_selected_at=NOW if selected else None,
    )
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(
        opportunity_id=opportunity.id, notice_id=notice.id, stage="notice",
        link_type="official", status="확정", evidence_external_no=notice.notice_key,
    ))
    session.flush()
    return opportunity


def _pending_fetch(session: Session, notice: Notice, *, reason: str = "sw_business_object",
                   status: str = "대기") -> AttachmentFetch:
    seq = session.scalar(select(Attachment.id).order_by(Attachment.id.desc()).limit(1)) or 0
    url = G2B_URL.format(seq=seq + 1)
    attachment = Attachment(
        notice_id=notice.id, name="제안요청서.pdf", source_url=url, source_system=SOURCE_SYSTEM,
        source_attachment_key=parse_attachment_key(url), origin="g2b",
    )
    session.add(attachment)
    session.flush()
    fetch = AttachmentFetch(
        attachment_id=attachment.id, status=status, eligibility_reason=reason,
        attempt_count=0, max_attempts=3, next_attempt_at=NOW - timedelta(minutes=1), lease_fence=0,
    )
    if status == "진행":
        fetch.lease_owner = "dead-worker"
        fetch.lease_expires_at = NOW - timedelta(minutes=1)
        fetch.lease_fence = 1
    session.add(fetch)
    session.flush()
    return fetch


def _claim_all(session: Session) -> set[int]:
    claimed: set[int] = set()
    while (claim := claim_next(session, worker_id="scope-worker", lease_seconds=60)) is not None:
        claimed.add(claim.attachment_id)
    return claimed


# --- 진입점 1: 첨부 취득 worker의 claim ------------------------------------------


def test_claim_takes_only_rows_inside_the_auto_scope(db):
    fetches = {}
    for name, deadline, tracking, _expected in CASES:
        fetches[name] = _pending_fetch(db, _notice(db, name, deadline_at=deadline, tracking=tracking))
    db.commit()
    expected = {fetches[name].attachment_id for name, _d, _t, inside in CASES if inside}

    assert _claim_all(db) == expected

    # 범위 밖의 행은 지우지도 상태를 바꾸지도 않는다. `대기` 그대로이고 시도 횟수도 그대로다.
    for name, _d, _t, inside in CASES:
        row = db.get(AttachmentFetch, fetches[name].id)
        db.refresh(row)
        if inside:
            assert row.status == "진행"
        else:
            assert (row.status, row.attempt_count, row.lease_owner) == ("대기", 0, None)


def test_claim_keeps_the_grade_and_briefing_exceptions_and_finishes_started_rows(db):
    """`우선 검토` 등급 행·브리핑 추천(B18)·이미 시작된 `진행` 행은 범위와 무관하게 claim된다."""

    passed = NOW - timedelta(days=3)
    graded = _pending_fetch(
        db, _notice(db, "graded", deadline_at=passed, tracking=None, sw="N"), reason="priority_grade",
    )
    recommended_notice = _notice(db, "recommended", deadline_at=passed, tracking=None)
    recommended = _pending_fetch(db, recommended_notice)
    briefing = Briefing(briefing_date=date(2026, 11, 18), status="generated", generated_at=NOW,
                        policy_sha256="a" * 64, graph_version_id=uuid4(), item_count=1,
                        excluded_counts={}, warnings=[], created_by="system:test")
    db.add(briefing)
    db.flush()
    owner = Opportunity(first_registered_stage="pre_spec")
    db.add(owner)
    db.flush()
    db.add(BriefingItem(briefing_id=briefing.id, kind="recommendation", rank=1, stage="pre_spec",
                        notice_id=recommended_notice.id, opportunity_id=owner.id, score=Decimal("50"),
                        reasons=[], blocking=[], change_fields=[], reaction="대기", revision=0))
    started = _pending_fetch(
        db, _notice(db, "started", deadline_at=passed, tracking=None), status="진행",
    )
    untouched = _pending_fetch(db, _notice(db, "untouched", deadline_at=passed, tracking=None))
    db.commit()

    assert _claim_all(db) == {graded.attachment_id, recommended.attachment_id, started.attachment_id}
    assert db.get(AttachmentFetch, untouched.id).status == "대기"


# --- 진입점 2: 자동 문서 준비 ----------------------------------------------------


@pytest.mark.parametrize(("name", "deadline", "tracking", "inside"), CASES, ids=CASE_IDS)
def test_auto_preparation_opens_only_inside_the_auto_scope(db, name, deadline, tracking, inside):
    notice = _notice(db, name, deadline_at=deadline, tracking=tracking)
    db.commit()

    outcome = maybe_auto_prepare(db, [notice.id])[0]
    fields = auto_preparation_fields(db, [notice.id])[notice.id]

    # 범위 안이면 자격을 지나 다음 조건(준비된 문서 없음)에서 멈춘다. 범위 밖이면 자격에서
    # `deadline_passed_untracked`로 멈추고 목록 투영도 같은 사유를 말한다.
    expected = REASON_NO_READY_DOCUMENT if inside else REASON_DEADLINE_PASSED_UNTRACKED
    assert outcome.reason == expected
    assert fields["auto_preparation_reason"] == expected
    assert fields["auto_preparation_status"] == ("waiting_attachments" if inside else "not_applicable")
    assert db.scalar(select(DocumentBundle.id).where(DocumentBundle.notice_id == notice.id)) is None


def test_out_of_scope_reason_is_only_for_the_flag_relaxation(db, monkeypatch):
    """SW=N이나 플래그 off는 지금처럼 `grade_not_priority`다 — 범위 사유로 바꾸지 않는다."""

    passed = NOW - timedelta(days=1)
    sw_no = _notice(db, "sw-no", deadline_at=passed, tracking=None, sw="N")
    db.commit()
    assert maybe_auto_prepare(db, [sw_no.id])[0].reason == REASON_GRADE_NOT_PRIORITY

    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    get_settings.cache_clear()
    sw_yes = _notice(db, "flag-off", deadline_at=passed, tracking=None)
    db.commit()
    assert maybe_auto_prepare(db, [sw_yes.id])[0].reason == REASON_GRADE_NOT_PRIORITY


def test_priority_grade_ignores_the_scope_and_manual_paths_ignore_it_too(db, monkeypatch):
    passed = NOW - timedelta(days=1)
    graded = _notice(db, "graded", deadline_at=passed, tracking=None)
    plain = _notice(db, "plain", deadline_at=passed, tracking=None)
    db.commit()
    grades = {graded.id: EffectiveGrade(graded.id, "우선 검토", "screening_judgment")}

    assert overview_eligible(db, [graded.id, plain.id], grades=grades) == frozenset({graded.id})
    # 사람이 누르는 경로(묶음 생성·심층 검토 생성)는 범위를 보지 않는다.
    assert overview_eligible(db, [graded.id, plain.id], grades=grades, automatic=False) == frozenset(
        {graded.id, plain.id}
    )


# --- 진입점 3: 자동 개요 enqueue -------------------------------------------------


@pytest.mark.parametrize(("name", "deadline", "tracking", "inside"), CASES, ids=CASE_IDS)
def test_auto_overview_enqueue_respects_the_scope_and_human_range_does_not(
    db, monkeypatch, name, deadline, tracking, inside
):
    notice = _notice(db, name, deadline_at=deadline, tracking=tracking)
    db.commit()
    # 묶음·제안요청서 문서·정책 적재는 이 규칙의 대상이 아니다. 자격을 지나면 run을
    # 넣는 자리까지 가는지만 본다 — 문서가 있다고 두고 정책은 읽지 않는다.
    marker = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(overview_runs, "active_run", lambda _s, _n: None)
    monkeypatch.setattr(overview_runs, "ready_bundle_document", lambda _s, _n: marker)

    class _Reached(Exception):
        pass

    def _policy(_path):
        raise _Reached()

    monkeypatch.setattr(overview_runs, "load_claims_policy", _policy)

    def _reaches(**kwargs) -> bool:
        try:
            result = overview_runs.enqueue_overview_run(db, notice.id, settings=get_settings(), **kwargs)
        except _Reached:
            return True
        assert result is None
        return False

    assert _reaches() is inside
    # 운영자 단건 CLI(`automatic=False`)와 사람의 범위 확정 재실행은 범위를 보지 않는다.
    assert _reaches(automatic=False) is True
    assert _reaches(range_source="human", page_start=1, page_end=2, actor_name="담당자") is True
    assert db.scalar(select(PrespecOverviewRun.id).where(PrespecOverviewRun.notice_id == notice.id)) is None


# --- 사람이 추적을 시작하면 같은 경로가 다시 열린다 ---------------------------------


def test_starting_tracking_reopens_claim_and_preparation_for_a_passed_notice(db, monkeypatch):
    notice = _notice(db, "late", deadline_at=NOW - timedelta(days=2), tracking=None)
    opportunity = _track(db, notice, "미선택")
    fetch = _pending_fetch(db, notice)
    db.commit()
    assert _claim_all(db) == set()
    assert maybe_auto_prepare(db, [notice.id])[0].reason == REASON_DEADLINE_PASSED_UNTRACKED

    outcomes = []
    original = deep_review_hooks.maybe_auto_prepare

    def _spy(session, notice_ids, **kwargs):
        result = original(session, notice_ids, **kwargs)
        outcomes.extend(result)
        return result

    monkeypatch.setattr(deep_review_hooks, "maybe_auto_prepare", _spy)
    opportunity.tracking_status = "계속 추적"
    opportunity.tracking_reason = "늦게 발견"
    opportunity.tracking_selected_by = "담당자"
    opportunity.tracking_selected_at = NOW
    db.commit()

    PreSpecAttachmentEligibilityHook().tracking_decision_changed(db, opportunity.id)
    db.commit()

    # 자동 준비가 같은 hook에서 다시 불렸고 이번에는 자격을 지났다(첨부가 아직 `대기`).
    assert [(row.notice_id, row.reason) for row in outcomes] == [(notice.id, "awaiting_fetch")]
    # 남아 있던 `대기` 행은 다음 claim에서 잡힌다.
    assert _claim_all(db) == {fetch.attachment_id}


def test_the_tracking_status_patch_entry_point_reopens_the_claim(db):
    """진입점별 검사: 조립된 앱의 `PATCH /api/opportunities/{id}/tracking-status`가 같은 hook을 부른다.

    일괄 추적(`order_plan_bulk_tracking._post_commit_hooks`)도 같은 registry 호출이며 그 호출
    자체는 `tests/lifecycle/test_order_plan_bulk_tracking.py`가 owner마다 검사한다.
    """

    from urllib.parse import quote

    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.lifecycle import extension_registry, restore_extension_registry
    from app.main import create_app

    notice = _notice(db, "patched", deadline_at=NOW - timedelta(days=2), tracking=None)
    opportunity = _track(db, notice, "미선택")
    fetch = _pending_fetch(db, notice)
    db.commit()
    assert _claim_all(db) == set()

    previous = extension_registry()
    try:
        application = create_app(modules=("lifecycle", "screening", "deep_review"), mount_frontend=False)
        application.dependency_overrides[get_db] = lambda: db
        with TestClient(application) as client:
            response = client.patch(
                f"/api/opportunities/{opportunity.id}/tracking-status",
                json={"tracking_status": "계속 추적", "reason": "늦게 발견한 사업"},
                headers={
                    "X-BidOps-Actor-Name": f"UTF-8''{quote('담당자', safe='')}",
                    "X-BidOps-Actor-Name-Format": "utf-8-percent-v1",
                },
            )
        assert response.status_code == 200, response.text
    finally:
        restore_extension_registry(previous)

    assert _claim_all(db) == {fetch.attachment_id}
