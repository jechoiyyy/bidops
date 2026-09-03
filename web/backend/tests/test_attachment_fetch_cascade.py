"""첨부 삭제 시 `attachment_fetch` 행 제거는 DB FK `ondelete=CASCADE`가 맡는다 (명세 §4).

`Attachment.fetch`의 ORM cascade(`all, delete-orphan`)를 없앴으므로 lifecycle의
`attachment`(lifecycle 테이블)를 지울 때 deep_review의 `attachment_fetch` 행이
남지 않는 것은 이제 데이터베이스가 보장해야 한다. PostgreSQL과 SQLite
(`PRAGMA foreign_keys=ON`) 양쪽에서 확인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import delete_manual_attachment, register_manual_attachment
from app.deep_review.models import AttachmentFetch
from app.lifecycle.models import Notice
from tests.postgres import migrated_engine, requires_postgres

WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def _seed_attachment_with_fetch(session: Session) -> int:
    notice = Notice(
        notice_key="pre:CASCADE",
        source_type="pre_spec",
        title="cascade 제안요청서",
        agency="테스트 기관",
        qualification_flags_json={"sw_business_status": "Y"},
    )
    session.add(notice)
    session.flush()
    attachment = register_manual_attachment(
        session,
        notice,
        name="manual.pdf",
        file_ext="PDF",
        size_bytes=10,
        stored_path="attachments/cascade/manual.pdf",
    )
    session.flush()
    session.add(
        AttachmentFetch(
            attachment_id=attachment.id,
            status="대기",
            eligibility_reason="sw_business_object",
            attempt_count=0,
            max_attempts=3,
            next_attempt_at=WHEN,
        )
    )
    session.commit()
    return attachment.id


def _fetch_rows(session: Session, attachment_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(AttachmentFetch).where(
                AttachmentFetch.attachment_id == attachment_id
            )
        )
        or 0
    )


def _delete_and_count(session: Session, attachment_id: int) -> int:
    from app.lifecycle.models import Attachment

    attachment = session.get(Attachment, attachment_id)
    assert attachment is not None
    assert _fetch_rows(session, attachment_id) == 1
    delete_manual_attachment(session, attachment)
    session.commit()
    return _fetch_rows(session, attachment_id)


def test_sqlite_foreign_key_cascade_removes_the_fetch_row():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    init_db(engine)
    try:
        with Session(engine) as session:
            attachment_id = _seed_attachment_with_fetch(session)
            assert _delete_and_count(session, attachment_id) == 0
    finally:
        engine.dispose()


@requires_postgres
def test_postgres_foreign_key_cascade_removes_the_fetch_row():
    with migrated_engine() as engine, Session(engine) as session:
        attachment_id = _seed_attachment_with_fetch(session)
        assert _delete_and_count(session, attachment_id) == 0


def test_sqlite_without_foreign_keys_would_leave_the_row():
    """검사 자체의 근거: PRAGMA를 끄면 행이 남는다.

    위 SQLite 테스트가 통과하는 이유가 ORM cascade가 아니라 FK라는 것을 이
    대조군이 보여 준다. ORM cascade가 다시 생기면 이 테스트가 깨진다.
    """

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    try:
        with Session(engine) as session:
            attachment_id = _seed_attachment_with_fetch(session)
            assert _delete_and_count(session, attachment_id) == 1
    finally:
        engine.dispose()
