from datetime import date, datetime, timezone
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.lifecycle import (
    extension_registry,
    reset_extension_registry,
    restore_extension_registry,
)
from app.lifecycle.models import Attachment, Notice, Run
from app.deep_review.models import AttachmentFetch
from app.screening.models import Judgment, Review, VerificationAnswer


@pytest.fixture
def reviews_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        run = Run(
            id="review-run",
            window_from=date(2026, 8, 17),
            window_to=date(2026, 8, 23),
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        notice = Notice(
            run=run,
            notice_key="bid:REVIEW:000",
            title="리뷰 테스트 공고",
            sample_role="analysis",
        )
        session.add(Judgment(notice=notice, grade="우선 검토", readiness="부분 확인 필요"))
        session.add(run)
        session.commit()

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, session
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_review_save_and_update_is_idempotent_and_replaces_answers(reviews_client):
    client, session = reviews_client
    first = client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "심층 검토 진행",
            "system_judgment_review": "동의",
            "reason": "첫 번째 기록",
            "reviewer": "테스트 담당자",
            "verification_answers": [
                {"item": "참가자격", "answer": "확인 중"},
                {"item": "과업 범위", "answer": ""},
            ],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    first_id = first_payload["id"]
    first_updated_at = first_payload["updated_at"]
    assert first_payload["reviewer"] == "테스트 담당자"
    assert first_payload["answers"][1]["answer"] is None

    time.sleep(0.001)
    second = client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "관찰",
            "system_judgment_review": "근거 부족",
            "corrected_grade": "검토 권장",
            "reason": "수정 기록",
            "reviewer": "테스트 담당자",
            "verification_answers": [{"item": "과업 범위", "answer": "확인 완료"}],
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["id"] == first_id
    assert second_payload["updated_at"] != first_updated_at
    assert second_payload["answers"] == [
        {"id": second_payload["answers"][0]["id"], "item": "과업 범위", "answer": "확인 완료"}
    ]
    assert session.scalar(select(func.count()).select_from(Review)) == 1
    assert session.scalar(select(func.count()).select_from(VerificationAnswer)) == 1

    listed = client.get("/api/reviews", params={"run_id": "review-run"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == first_id


def test_review_export_preserves_feedback_v2_shape(reviews_client):
    client, _session = reviews_client
    client.put(
        "/api/notices/1/review",
        json={
            "run_id": "review-run",
            "disposition": "관찰",
            "reason": "메모",
            "reviewer": "테스트 담당자",
            "verification_answers": [{"item": "참가자격", "answer": "확인 완료"}],
        },
    )

    response = client.get("/api/reviews/export", params={"run_id": "review-run"})
    assert response.status_code == 200
    assert "review-feedback.yaml" in response.headers["content-disposition"]
    document = yaml.safe_load(response.text)
    assert document["schema_version"] == "bidops.feedback.v2"
    assert document["reviews"] == [
        {
            "notice_id": "bid:REVIEW:000",
            "disposition": "관찰",
            "system_judgment_review": None,
            "corrected_grade": None,
            "corrected_readiness": None,
            "weakest_perspective": None,
            "reason": "메모",
            "verification_answers": [{"item": "참가자격", "answer": "확인 완료"}],
        }
    ]


# --- 정정 등급 변경이 lifecycle 확장점을 부른다 (명세 §6.2 둘째 촉발) ---------

G2B_PRE_SPEC_URL = (
    "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
    "?bfSpecRegNo=R26RV00000001&fileType=BFDTL&fileSeq=1"
)


def _add_pre_spec(session: Session) -> Notice:
    """SW=N·추적 없음인 사전규격. 자격을 여는 것은 오직 등급뿐이다."""

    run = session.get(Run, "review-run")
    notice = Notice(
        run=run,
        notice_key="pre:REVIEW-GRADE",
        source_type="pre_spec",
        title="정정 등급 사전규격",
        qualification_flags_json={"sw_business_status": "N"},
    )
    session.add(notice)
    session.flush()
    session.add(
        Attachment(
            notice_id=notice.id,
            name="제안요청서.pdf",
            origin="g2b",
            source_url=G2B_PRE_SPEC_URL,
            source_system="g2b",
            source_attachment_key="R26RV00000001:BFDTL:1",
        )
    )
    session.commit()
    return notice


def _put_review(client, notice_pk: int, grade: str | None):
    return client.put(
        f"/api/notices/{notice_pk}/review",
        json={
            "run_id": "review-run",
            "disposition": "심층 검토 진행",
            "corrected_grade": grade,
            "reason": "등급 정정",
            "reviewer": "테스트 담당자",
            "verification_answers": [],
        },
    )


def test_correcting_the_grade_up_to_priority_creates_the_fetch_row(reviews_client):
    client, session = reviews_client
    notice = _add_pre_spec(session)

    assert session.scalar(select(func.count(AttachmentFetch.id))) == 0
    assert _put_review(client, notice.id, "우선 검토").status_code == 200

    rows = list(session.scalars(select(AttachmentFetch)))
    assert [row.eligibility_reason for row in rows] == ["priority_grade"]
    assert rows[0].status == "대기"


def test_correcting_the_grade_down_leaves_the_existing_fetch_row(reviews_client):
    client, session = reviews_client
    notice = _add_pre_spec(session)
    assert _put_review(client, notice.id, "우선 검토").status_code == 200
    row = session.scalar(select(AttachmentFetch))
    before = (row.id, row.status, row.eligibility_reason)

    assert _put_review(client, notice.id, "제외").status_code == 200

    session.expire_all()
    rows = list(session.scalars(select(AttachmentFetch)))
    assert len(rows) == 1
    assert (rows[0].id, rows[0].status, rows[0].eligibility_reason) == before


def test_saving_the_same_grade_again_does_not_call_the_hook(reviews_client):
    client, session = reviews_client
    notice = _add_pre_spec(session)
    calls: list[list[int]] = []

    class _Recorder:
        def effective_grade_changed(self, _session, notice_ids) -> None:
            calls.append([int(value) for value in notice_ids])

    original = reset_extension_registry()
    try:
        registry = extension_registry()
        registry.register_effective_grade_changed_hook(_Recorder(), owner="test")
        assert _put_review(client, notice.id, "검토 권장").status_code == 200
        assert _put_review(client, notice.id, "검토 권장").status_code == 200
    finally:
        restore_extension_registry(original)

    assert calls == [[notice.id]]


def test_a_failing_hook_does_not_roll_back_the_review(reviews_client):
    client, session = reviews_client
    notice = _add_pre_spec(session)

    class _Broken:
        def effective_grade_changed(self, _session, _notice_ids) -> None:
            raise RuntimeError("확장점 구현이 깨졌다")

    original = reset_extension_registry()
    try:
        extension_registry().register_effective_grade_changed_hook(_Broken(), owner="test")
        response = _put_review(client, notice.id, "우선 검토")
    finally:
        restore_extension_registry(original)

    assert response.status_code == 200
    saved = session.scalar(select(Review).where(Review.notice_id == notice.id))
    assert saved is not None
    assert saved.corrected_grade == "우선 검토"
