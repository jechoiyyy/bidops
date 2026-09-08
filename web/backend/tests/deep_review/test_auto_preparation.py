"""자동 문서 준비의 deep_review 몫 (명세 §6.2·§8).

여기 있는 검사는 **선별 seam 없이** 성립하는 부분만 본다 — 문서 집합 지문,
상태 표, 사전규격이 아닌 공고의 무동작이다. 등급이 실제로 자격을 여는 경로는
판정·리뷰가 선별 소유라 두 모듈이 합쳐지는 자리에 있다
(`tests/app/test_prespec_attachment_fetch.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.deep_review.models import (
    ContentObject,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PreSpecOverviewReview,
    PreSpecOverviewSnapshot,
)
from app.deep_review.services.auto_preparation import (
    AUTO_ACTOR_KIND,
    AUTO_ACTOR_NAME,
    AUTO_CONFIRM_ACTION,
    AUTO_DEEP_REVIEW_ACTION,
    REASON_BLOCKING_ISSUES,
    REASON_BUNDLE_NOT_AUTO_READY,
    REASON_DEEP_REVIEW_EXISTS,
    REASON_GRADE_NOT_PRIORITY,
    REASON_NOT_SW_BUSINESS,
    REASON_OVERVIEW_BUNDLE_MISMATCH,
    REASON_OVERVIEW_CLOSED,
    REASON_OVERVIEW_NOT_COMPLETED,
    _status_for,
    document_fingerprint,
    maybe_auto_prepare,
    maybe_auto_start_deep_review,
)
from app.deep_review.services.effective_grade import EffectiveGrade
from app.lifecycle.models import Attachment, Notice, Opportunity, OpportunityLink

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


def _document(session: Session, notice: Notice, attachment: Attachment, payload: bytes) -> DocumentVersion:
    import hashlib

    content = ContentObject(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id,
        attachment_id=attachment.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename=attachment.name,
        role="기타",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(document)
    session.flush()
    return document


def _notice(session: Session, *, source_type: str = "pre_spec") -> tuple[Notice, Attachment]:
    notice = Notice(
        notice_key=f"key-{uuid4()}",
        source_type=source_type,
        title="자동 준비",
        qualification_flags_json={"sw_business_status": "N"},
    )
    session.add(notice)
    session.flush()
    attachment = Attachment(notice_id=notice.id, name="문서.pdf", origin="manual")
    session.add(attachment)
    session.flush()
    return notice, attachment


# --- 문서 집합 지문 (재수집 규칙) --------------------------------------------


def test_the_fingerprint_is_the_sorted_content_hash_set(db_session: Session):
    notice, attachment = _notice(db_session)
    document = _document(db_session, notice, attachment, b"first bytes")

    first = document_fingerprint(db_session, [document])

    assert len(first) == 1
    # 같은 문서를 다시 물어도 값이 같다 — 재적재가 새 묶음을 만들지 않는 근거다.
    assert document_fingerprint(db_session, [document]) == first


def test_different_bytes_change_the_fingerprint(db_session: Session):
    notice, attachment = _notice(db_session)
    first = _document(db_session, notice, attachment, b"first bytes")
    second_notice, second_attachment = _notice(db_session)
    second = _document(db_session, second_notice, second_attachment, b"other bytes")

    assert document_fingerprint(db_session, [first]) != document_fingerprint(db_session, [second])


def test_an_empty_document_set_has_an_empty_fingerprint(db_session: Session):
    assert document_fingerprint(db_session, []) == ()


# --- 상태 표 (§5의 여덟 값) ---------------------------------------------------

_PRIORITY = EffectiveGrade(notice_id=1, grade="우선 검토", source="screening_judgment")
_OBSERVED = EffectiveGrade(notice_id=1, grade="관찰 대상", source="screening_judgment")
_BLOCKING = [{"code": "attachment_bytes_missing", "blocking": True}]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"is_pre_spec": False}, "not_applicable"),
        ({"grade": _OBSERVED}, "not_applicable"),
        ({"grade": None}, "not_applicable"),
        ({"grade": _PRIORITY, "has_pending_fetch": True}, "waiting_attachments"),
        ({"grade": _PRIORITY}, "waiting_attachments"),
        ({"bundles": [(1, "draft", [], AUTO_ACTOR_NAME)]}, "bundle_draft"),
        ({"bundles": [(1, "draft", _BLOCKING, AUTO_ACTOR_NAME)]}, "blocked"),
        ({"bundles": [(1, "ready", [], AUTO_ACTOR_NAME)]}, "bundle_ready"),
        (
            {"bundles": [(1, "ready", [], AUTO_ACTOR_NAME)], "overview_status": "running"},
            "overview_running",
        ),
        (
            {"bundles": [(1, "ready", [], AUTO_ACTOR_NAME)], "overview_status": "completed"},
            "deep_review_ready_for_click",
        ),
        (
            {
                "bundles": [(1, "ready", [], AUTO_ACTOR_NAME)],
                "overview_status": "needs_human_review",
            },
            "deep_review_ready_for_click",
        ),
        ({"deep_review_id": uuid4()}, "deep_review_started"),
    ],
)
def test_the_status_table_covers_every_contract_value(kwargs: dict, expected: str):
    defaults = {
        "is_pre_spec": True,
        "grade": _PRIORITY,
        "deep_review_id": None,
        "bundles": (),
        "overview_status": None,
        "has_pending_fetch": False,
    }
    defaults.update(kwargs)

    status, _reason = _status_for(**defaults)

    assert status == expected


def test_a_blocked_draft_reports_a_safe_reason_code():
    status, reason = _status_for(
        is_pre_spec=True,
        grade=_PRIORITY,
        deep_review_id=None,
        bundles=[(1, "draft", _BLOCKING, AUTO_ACTOR_NAME)],
        overview_status=None,
        has_pending_fetch=False,
    )
    assert (status, reason) == ("blocked", REASON_BLOCKING_ISSUES)


def test_a_non_priority_grade_reports_a_safe_reason_code():
    status, reason = _status_for(
        is_pre_spec=True,
        grade=_OBSERVED,
        deep_review_id=None,
        bundles=(),
        overview_status=None,
        has_pending_fetch=False,
    )
    assert (status, reason) == ("not_applicable", REASON_GRADE_NOT_PRIORITY)


# --- 무동작 경계 --------------------------------------------------------------


def test_a_bid_notice_is_never_auto_prepared(db_session: Session):
    """사전규격이 아니면 등급을 묻지도 않고 아무것도 만들지 않는다."""

    notice, attachment = _notice(db_session, source_type="bid_notice")
    _document(db_session, notice, attachment, b"bid bytes")
    db_session.commit()

    outcomes = maybe_auto_prepare(db_session, [notice.id])

    assert [outcome.bundle_id for outcome in outcomes] == [None]
    assert [outcome.reason for outcome in outcomes] == [None]
    assert db_session.scalar(select(DocumentBundle)) is None


def test_an_empty_notice_list_does_nothing(db_session: Session):
    assert maybe_auto_prepare(db_session, []) == []


def test_the_audit_action_name_is_the_contract_value():
    """§8이 새로 더한 감사 action. 이름이 바뀌면 소비자 계약이 깨진다."""

    assert AUTO_CONFIRM_ACTION == "document_bundle.auto_confirm"
    assert AUTO_ACTOR_NAME == "auto-preparation"


# --- SW사업대상=Y 자동 심층 검토 시작 (명세 §6.4) -----------------------------
#
# 여기 있는 검사는 **선별 seam 없이** 성립하는 §6.4의 조건만 본다. 실제
# `DeepReviewService.create_review`가 등급·프로필·정책을 고정하고 감사 이벤트를
# 남기는 경로는 판정이 선별 소유라 두 모듈이 합쳐지는 자리에 있다
# (`tests/app/test_auto_deep_review_start.py`).

_PROFILE_ID = uuid4()
_POLICY_ID = uuid4()


class _RecordingDeepReviewService:
    """`DeepReviewService.create_review`의 계약만 흉내 내는 fake.

    모델도 저장소도 부르지 않는다. 자동 시작이 **누구로, 무엇에** 걸었는지와
    몇 번 걸었는지만 기록한다.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    def create_review(
        self,
        session: Session,
        notice_id: int,
        bundle_id,
        actor: str | None,
        request_id,
        *,
        actor_kind: str = "human",
    ) -> dict:
        self.calls.append(
            {
                "notice_id": notice_id,
                "bundle_id": bundle_id,
                "actor": actor,
                "actor_kind": actor_kind,
                "request_id": request_id,
            }
        )
        if self.error is not None:
            raise self.error
        review = DeepReview(
            id=uuid4(),
            notice_id=notice_id,
            bundle_id=bundle_id,
            profile_version_id=_PROFILE_ID,
            policy_version_id=_POLICY_ID,
            effective_grade_at_start="우선 검토",
            status="queued",
            requested_by_name=actor,
        )
        session.add(review)
        # 실제 `create_review`와 같은 계약이다 — 생성은 스스로 commit한다.
        # savepoint session에서는 그 commit이 savepoint를 놓을 뿐이다.
        session.commit()
        return {"id": str(review.id)}


@pytest.fixture()
def active_versions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(_PROFILE_ID))
    monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(_POLICY_ID))
    return _PROFILE_ID, _POLICY_ID


def _structure(session: Session, document: DocumentVersion) -> DocumentStructure:
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256="a" * 64,
        media_type="application/pdf",
        extractor_name="test",
        extractor_version="1",
        payload_content_object_id=document.content_object_id,
        payload_sha256="b" * 64,
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()
    return structure


def _auto_start_context(
    session: Session,
    *,
    sw_business_status: str = "Y",
    bundle_status: str = "ready",
    confirmed_by: str | None = AUTO_ACTOR_NAME,
    overview_status: str = "completed",
    overview_result: str | None = "추진 검토",
    snapshot_in_bundle: bool = True,
):
    """§6.4의 자동 시작 조건이 모두 성립한 사전규격 하나를 세운다."""

    notice, attachment = _notice(session)
    notice.qualification_flags_json = {"sw_business_status": sw_business_status}
    document = _document(session, notice, attachment, b"prespec bytes")
    structure = _structure(session, document)

    bundle = DocumentBundle(
        notice_id=notice.id,
        revision=1,
        version=1,
        status=bundle_status,
        issues_snapshot=[],
        created_by_name=AUTO_ACTOR_NAME,
        confirmed_by_name=confirmed_by,
        confirmed_at=WHEN if confirmed_by else None,
    )
    session.add(bundle)
    session.flush()
    session.add(
        DocumentBundleItem(
            bundle_id=bundle.id,
            document_version_id=document.id,
            ordinal=0,
            document_version_version=document.version,
            content_object_id=document.content_object_id,
            content_sha256="c" * 64,
            detected_mime="application/pdf",
            size_bytes=1,
            original_filename=document.original_filename,
            source_kind="manual",
            role_at_confirmation="기타",
            is_current_at_confirmation=True,
            safety_status_at_confirmation="safe",
            structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        )
    )

    # 개요 snapshot이 묶음 밖을 가리키는 경우를 만들려면 묶음에 넣지 않은
    # 두 번째 문서가 필요하다. 같은 공고의 다른 첨부에서 온 문서다.
    snapshot_document = document
    if not snapshot_in_bundle:
        other = Attachment(notice_id=notice.id, name="다른문서.pdf", origin="manual")
        session.add(other)
        session.flush()
        snapshot_document = _document(session, notice, other, b"other prespec bytes")
        structure = _structure(session, snapshot_document)

    review = PreSpecOverviewReview(notice_id=notice.id, status="awaiting_model")
    session.add(review)
    session.flush()
    snapshot = PreSpecOverviewSnapshot(
        review_id=review.id,
        notice_id=notice.id,
        document_version_id=snapshot_document.id,
        structure_id=structure.id,
        source_sha256="a" * 64,
        payload_sha256="b" * 64,
        cut_status="ready",
        strategy="topic_heading",
        start_locator={"block_key": "start", "page": 1, "ordinal": 0},
        end_locator={"block_key": "end", "page": 1, "ordinal": 2},
        input_block_keys=["start"],
    )
    session.add(snapshot)
    session.flush()
    review.current_snapshot_id = snapshot.id
    review.status = overview_status
    review.result = overview_result if overview_status == "completed" else None
    review.completed_at = WHEN if overview_status == "completed" else None
    session.commit()
    return notice, bundle


@pytest.fixture
def matched_company_fit_gate(monkeypatch):
    # This unit suite isolates creation/idempotency; real evidence and stale gates
    # are exercised in test_company_fit and the PostgreSQL integration test.
    from app.deep_review.services import company_fit
    monkeypatch.setattr(company_fit, "gate_reasons", lambda session, ids: {i: None for i in ids})


def test_sw_y_with_a_positive_overview_starts_exactly_one_deep_review(
    db_session: Session, active_versions, matched_company_fit_gate
):
    """§6.4의 모든 조건이 성립하면 시스템 actor로 한 건만 만든다."""

    notice, bundle = _auto_start_context(db_session)
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert outcome.created is True
    assert outcome.bundle_id == bundle.id
    assert outcome.reason is None
    assert len(service.calls) == 1
    assert service.calls[0]["actor"] == AUTO_ACTOR_NAME
    assert service.calls[0]["actor_kind"] == AUTO_ACTOR_KIND
    assert service.calls[0]["bundle_id"] == bundle.id

    # 같은 (공고, 묶음, active profile, active policy)에 두 번 만들지 않는다.
    again = maybe_auto_start_deep_review(db_session, notice.id, service=service)
    assert again.created is False
    assert again.reason == REASON_DEEP_REVIEW_EXISTS
    assert len(service.calls) == 1
    assert len(db_session.scalars(select(DeepReview)).all()) == 1


def test_sw_n_is_always_left_to_a_human_click(db_session: Session, active_versions):
    notice, _bundle = _auto_start_context(db_session, sw_business_status="N")
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_NOT_SW_BUSINESS)
    assert service.calls == []


def test_a_closed_overview_recommendation_is_left_to_a_human_click(
    db_session: Session, active_versions
):
    notice, _bundle = _auto_start_context(db_session, overview_result="검토 종료")
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_OVERVIEW_CLOSED)
    assert service.calls == []


@pytest.mark.parametrize("status", ["needs_human_review", "failed", "awaiting_model"])
def test_an_unsettled_or_failed_overview_is_left_to_a_human_click(
    db_session: Session, active_versions, status: str
):
    notice, _bundle = _auto_start_context(db_session, overview_status=status)
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_OVERVIEW_NOT_COMPLETED)
    assert service.calls == []


def test_an_overview_snapshot_outside_the_bundle_is_not_the_same_bundle(
    db_session: Session, active_versions
):
    """개요 snapshot은 문서 하나에 묶인다 — 그 문서가 묶음에 없으면 다른 묶음이다."""

    notice, _bundle = _auto_start_context(db_session, snapshot_in_bundle=False)
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_OVERVIEW_BUNDLE_MISMATCH)
    assert service.calls == []


def test_a_human_confirmed_bundle_is_left_to_a_human_click(
    db_session: Session, active_versions
):
    notice, _bundle = _auto_start_context(db_session, confirmed_by="담당자")
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_BUNDLE_NOT_AUTO_READY)
    assert service.calls == []


def test_a_draft_bundle_is_not_ready_for_an_automatic_start(
    db_session: Session, active_versions
):
    notice, _bundle = _auto_start_context(
        db_session, bundle_status="draft", confirmed_by=None
    )
    service = _RecordingDeepReviewService()

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, REASON_BUNDLE_NOT_AUTO_READY)
    assert service.calls == []


def test_missing_active_version_ids_fail_closed_with_a_safe_reason(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    """active profile/policy 환경변수가 없으면 만들지 않고 안전 코드만 남긴다."""

    monkeypatch.delenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", raising=False)
    monkeypatch.delenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", raising=False)
    notice, _bundle = _auto_start_context(db_session)

    outcome = maybe_auto_start_deep_review(db_session, notice.id)

    assert (outcome.created, outcome.reason) == (False, "service_unavailable")
    assert db_session.scalar(select(DeepReview)) is None


def test_a_service_failure_leaves_only_a_stable_safe_code(
    db_session: Session, active_versions, matched_company_fit_gate
):
    """예외 본문·경로·비밀값은 사유에 넣지 않는다. 안정 code만 남는다."""

    from app.deep_review.services.deep_reviews import DeepReviewServiceError

    notice, _bundle = _auto_start_context(db_session)
    service = _RecordingDeepReviewService(
        error=DeepReviewServiceError(
            "service_unavailable", "/srv/secret/path 에서 실패", status_code=503
        )
    )

    outcome = maybe_auto_start_deep_review(db_session, notice.id, service=service)

    assert (outcome.created, outcome.reason) == (False, "service_unavailable")
    assert db_session.scalar(select(DeepReview)) is None


def test_the_automatic_start_never_touches_the_tracking_status(
    db_session: Session, active_versions, matched_company_fit_gate
):
    """자동 시작은 사업기회 추적 상태를 바꾸지 않는다 (§6.4)."""

    notice, _bundle = _auto_start_context(db_session)
    opportunity = Opportunity(first_registered_stage="pre_spec")
    db_session.add(opportunity)
    db_session.flush()
    db_session.add(
        OpportunityLink(
            opportunity_id=opportunity.id,
            stage="notice",
            notice_id=notice.id,
            link_type="candidate",
            status="사람 확인 완료",
            human_decision="accepted",
            reviewer_name="담당자",
            reviewed_at=WHEN,
            review_reason="같은 사업으로 확인",
        )
    )
    db_session.commit()

    outcome = maybe_auto_start_deep_review(
        db_session, notice.id, service=_RecordingDeepReviewService()
    )

    assert outcome.created is True
    db_session.refresh(opportunity)
    assert opportunity.tracking_status == "미선택"
    assert opportunity.tracking_selected_by is None


def test_the_auto_create_audit_action_is_the_contract_value():
    """§8이 새로 더한 감사 action. 이름이 바뀌면 소비자 계약이 깨진다."""

    assert AUTO_DEEP_REVIEW_ACTION == "deep_review.auto_create"
