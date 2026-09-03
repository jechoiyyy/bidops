"""공고 삭제 시 판정·리뷰 행 제거는 DB FK `ondelete=CASCADE`가 맡는다 (명세 §4).

`Notice.judgment`·`Notice.reviews`의 ORM cascade(`all, delete-orphan`)를 없앴으므로
lifecycle의 `notice`를 지울 때 screening의 `judgment`·`review` 행이 남지 않는 것은
이제 데이터베이스가 보장해야 한다. `Attachment.fetch`를 같은 이유로 검사하는
`test_attachment_fetch_cascade.py`와 같은 짜임이며, 대조군으로 "FK를 끄면 행이
남는다"를 함께 둬서 통과의 근거가 ORM cascade가 아님을 보인다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle.models import Notice, Run
from app.screening.models import Judgment, Review
from tests.postgres import migrated_engine, requires_postgres

WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def _seed_notice_with_judgment_and_review(session: Session) -> int:
    run = Run(id="2026-09-01-cascade", timezone="Asia/Seoul", generated_at=WHEN)
    session.add(run)
    notice = Notice(
        notice_key="pre:JUDGMENT-CASCADE",
        source_type="pre_spec",
        title="cascade 제안요청서",
        agency="테스트 기관",
        qualification_flags_json={"sw_business_status": "Y"},
    )
    session.add(notice)
    session.flush()
    session.add(
        Judgment(
            notice_id=notice.id,
            grade="우선 검토",
            readiness="가능",
            primary_focus="사업 적합성",
        )
    )
    session.add(
        Review(
            notice_id=notice.id,
            run_id=run.id,
            reviewer_snapshot="검수자",
            corrected_grade="검토",
        )
    )
    session.commit()
    return notice.id


def _judgment_and_review_rows(session: Session, notice_id: int) -> tuple[int, int]:
    judgments = int(
        session.scalar(
            select(func.count()).select_from(Judgment).where(Judgment.notice_id == notice_id)
        )
        or 0
    )
    reviews = int(
        session.scalar(
            select(func.count()).select_from(Review).where(Review.notice_id == notice_id)
        )
        or 0
    )
    return judgments, reviews


def _delete_and_count(session: Session, notice_id: int) -> tuple[int, int]:
    notice = session.get(Notice, notice_id)
    assert notice is not None
    assert _judgment_and_review_rows(session, notice_id) == (1, 1)
    session.delete(notice)
    session.commit()
    return _judgment_and_review_rows(session, notice_id)


def _sqlite_engine(*, foreign_keys: bool):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    if foreign_keys:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    init_db(engine)
    return engine


def test_sqlite_foreign_key_cascade_removes_judgment_and_review():
    engine = _sqlite_engine(foreign_keys=True)
    try:
        with Session(engine) as session:
            notice_id = _seed_notice_with_judgment_and_review(session)
            assert _delete_and_count(session, notice_id) == (0, 0)
    finally:
        engine.dispose()


@requires_postgres
def test_postgres_foreign_key_cascade_removes_judgment_and_review():
    with migrated_engine() as engine, Session(engine) as session:
        notice_id = _seed_notice_with_judgment_and_review(session)
        assert _delete_and_count(session, notice_id) == (0, 0)


def test_sqlite_without_foreign_keys_would_leave_the_rows():
    """검사 자체의 근거: PRAGMA를 끄면 행이 남는다.

    위 SQLite 테스트가 통과하는 이유가 ORM cascade가 아니라 FK라는 것을 이
    대조군이 보여 준다. ORM cascade가 다시 생기면 이 테스트가 깨진다.
    """

    engine = _sqlite_engine(foreign_keys=False)
    try:
        with Session(engine) as session:
            notice_id = _seed_notice_with_judgment_and_review(session)
            assert _delete_and_count(session, notice_id) == (1, 1)
    finally:
        engine.dispose()
