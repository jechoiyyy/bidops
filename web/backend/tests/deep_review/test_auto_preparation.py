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
    DocumentBundle,
    DocumentVersion,
)
from app.deep_review.services.auto_preparation import (
    AUTO_ACTOR_NAME,
    AUTO_CONFIRM_ACTION,
    REASON_BLOCKING_ISSUES,
    REASON_GRADE_NOT_PRIORITY,
    _status_for,
    document_fingerprint,
    maybe_auto_prepare,
)
from app.deep_review.services.effective_grade import EffectiveGrade
from app.lifecycle.models import Attachment, Notice

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
