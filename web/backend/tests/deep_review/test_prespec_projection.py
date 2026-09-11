"""deep_review가 제공하는 사전규격 개요·문서 projection (명세 §6.1 둘째 행).

lifecycle 목록이 넘긴 `notice_ids` 만큼을 상수 회 조회로 처리하고, 없는 공고는
빠뜨리며(호출부가 `None`/0으로 채운다), 은퇴한 첨부의 취득 상태는 세지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.lifecycle import OverviewDocumentProjection, PreSpecDocumentCounts
from app.deep_review.models import (
    AttachmentFetch,
    ContentObject,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from app.lifecycle.models import Attachment, Notice
from app.deep_review.services.prespec_projection import PreSpecOverviewDocumentProjection


def _notice(session: Session, key: str) -> Notice:
    notice = Notice(
        notice_key=key,
        source_type="pre_spec",
        title=f"{key} 제안요청서",
        agency="테스트 기관",
        qualification_flags_json={"sw_business_status": "Y"},
    )
    session.add(notice)
    session.flush()
    return notice


def _overview_run(session: Session, notice: Notice, status: str) -> PrespecOverviewRun:
    """개요 run 한 건과 그 실행 job·문서를 최소한으로 세운다."""

    content = ContentObject(
        sha256=f"{notice.id:064d}", size_bytes=1, detected_mime="application/pdf",
        retention_class="source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id, content_object_id=content.id, version=1, source_kind="manual",
        original_filename="제안요청서.pdf", role="제안요청서", is_current=True, safety_status="safe",
    )
    job = WorkJob(job_type="prespec_overview", aggregate_type="prespec_overview_run",
                  aggregate_id=uuid4(), status="completed")
    session.add_all([document, job])
    session.flush()
    run = PrespecOverviewRun(
        notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
        status=status, range_source="auto", range_reason_codes=[], policy_digest="0" * 64,
        model_name="test-model", warnings_json=[], reason_codes=[], call_count=0,
        raw_response_refs=[], result_json={"schema_version": "test"} if status == "completed" else None,
    )
    session.add(run)
    session.flush()
    return run


def _fetch(attachment: Attachment, status: str, *, when: datetime) -> AttachmentFetch:
    running = status == "진행"
    return AttachmentFetch(
        attachment_id=attachment.id,
        status=status,
        eligibility_reason="sw_business_object",
        attempt_count=0,
        max_attempts=3,
        next_attempt_at=when,
        lease_owner="projection-test" if running else None,
        lease_expires_at=when + timedelta(minutes=5) if running else None,
    )


@pytest.fixture()
def projection_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    session = Session(engine)
    when = datetime(2026, 9, 1, tzinfo=UTC)

    reviewed = _notice(session, "pre:REVIEWED")
    counted = _notice(session, "pre:COUNTED")
    bare = _notice(session, "pre:BARE")

    _overview_run(session, reviewed, "needs_human_review")
    _overview_run(session, counted, "completed")

    attachments = [
        Attachment(notice=counted, name=f"{status}.pdf", origin="g2b")
        for status in ("대기", "대기", "진행", "차단", "실패")
    ]
    retired = Attachment(
        notice=counted, name="retired.pdf", origin="g2b", retired_at=when, retired_reason="test"
    )
    unqueued = Attachment(notice=counted, name="unqueued.pdf", origin="g2b")
    session.add_all([*attachments, retired, unqueued])
    session.flush()
    for attachment, status in zip(attachments, ("대기", "대기", "진행", "차단", "실패"), strict=True):
        session.add(_fetch(attachment, status, when=when))
    # 은퇴한 첨부의 취득 행은 문서 요약에서 빠져야 한다 (오늘의 outerjoin과 같다).
    session.add(_fetch(retired, "차단", when=when))
    session.commit()

    try:
        yield session, engine, {"reviewed": reviewed, "counted": counted, "bare": bare}
    finally:
        session.close()
        engine.dispose()


def test_projection_satisfies_the_lifecycle_protocol():
    assert isinstance(PreSpecOverviewDocumentProjection(), OverviewDocumentProjection)


def test_overview_status_omits_notices_without_a_review_row(projection_db):
    session, _engine, refs = projection_db
    ids = [refs["reviewed"].id, refs["counted"].id, refs["bare"].id]

    status = PreSpecOverviewDocumentProjection().overview_status(session, ids)

    assert status == {
        refs["reviewed"].id: "needs_human_review",
        refs["counted"].id: "completed",
    }


def test_overview_status_counts_group_only_the_given_notices(projection_db):
    session, _engine, refs = projection_db
    projection = PreSpecOverviewDocumentProjection()

    everything = projection.overview_status_counts(
        session, [refs["reviewed"].id, refs["counted"].id, refs["bare"].id]
    )
    assert everything == {"needs_human_review": 1, "completed": 1}

    narrowed = projection.overview_status_counts(session, [refs["counted"].id, refs["bare"].id])
    assert narrowed == {"completed": 1}


def test_document_counts_ignore_retired_attachments_and_omit_bare_notices(projection_db):
    session, _engine, refs = projection_db

    counts = PreSpecOverviewDocumentProjection().document_counts(
        session, [refs["counted"].id, refs["bare"].id]
    )

    assert counts == {
        refs["counted"].id: PreSpecDocumentCounts(
            completed=0, pending=2, running=1, blocked=1, failed=1
        )
    }


def test_empty_notice_ids_return_empty_mappings_without_querying(projection_db):
    session, engine, _refs = projection_db
    projection = PreSpecOverviewDocumentProjection()
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert projection.overview_status(session, []) == {}
        assert projection.overview_status_counts(session, []) == {}
        assert projection.document_counts(session, []) == {}
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert statements == []


def test_each_projection_method_uses_a_bounded_batch_projection(projection_db):
    session, engine, refs = projection_db
    projection = PreSpecOverviewDocumentProjection()
    ids = [refs["reviewed"].id, refs["counted"].id, refs["bare"].id]
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        projection.overview_status(session, ids)
        projection.overview_status_counts(session, ids)
        projection.document_counts(session, ids)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    # 상태와 건수는 각각 현재 run batch 조회 하나, 문서 건수는 grouped 조회
    # 하나다. 공고 수가 늘어도 이 수는 그대로다.
    assert len(statements) == 3
