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
from app.lifecycle import (
    AcquiredAttachmentFile,
    AcquiredAttachmentFilesProvider,
    OverviewDocumentProjection,
    PreSpecDocumentCounts,
)
from app.deep_review.models import (
    AttachmentFetch,
    ContentObject,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from app.lifecycle.models import Attachment, Notice
from app.deep_review.services.prespec_projection import (
    AcquiredAttachmentFiles,
    PreSpecOverviewDocumentProjection,
)


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


def _acquired_document(
    session: Session, attachment: Attachment, filename: str, *, version: int, current: bool, size: int
) -> DocumentVersion:
    content = ContentObject(
        sha256=f"{attachment.id:032d}{version:032d}", size_bytes=size,
        detected_mime="application/octet-stream", retention_class="source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=attachment.notice_id, attachment_id=attachment.id, content_object_id=content.id,
        version=version, source_kind="provider", source_system="g2b",
        source_attachment_key=f"key-{attachment.id}", source_url="https://example.invalid/file",
        original_filename=filename, role="기타", is_current=current, safety_status="safe",
    )
    session.add(document)
    session.flush()
    return document


def test_acquired_files_come_from_the_current_document_version_of_each_attachment(projection_db):
    session, engine, refs = projection_db
    acquired, replaced, no_suffix, pending = [
        Attachment(notice=refs["bare"], name=f"첨부 {index}", origin="g2b") for index in range(1, 5)
    ]
    session.add_all([acquired, replaced, no_suffix, pending])
    session.flush()
    _acquired_document(session, acquired, "제안요청서(고도화).hwpx", version=1, current=True, size=2048)
    # 교체된 옛 version의 이름은 쓰지 않는다. 현재 version 하나만 읽는다.
    _acquired_document(session, replaced, "옛 이름.pdf", version=1, current=False, size=10)
    _acquired_document(session, replaced, "과업지시서.PDF", version=2, current=True, size=4096)
    _acquired_document(session, no_suffix, "붙임", version=1, current=True, size=7)
    session.commit()
    # commit 뒤 만료된 행을 미리 읽어 둔다 — 아래에서 세는 조회에 섞이지 않게.
    acquired_id, replaced_id, no_suffix_id, pending_id = acquired.id, replaced.id, no_suffix.id, pending.id

    provider = AcquiredAttachmentFiles()
    assert isinstance(provider, AcquiredAttachmentFilesProvider)
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        files = provider.acquired_attachment_files(
            session, [acquired_id, replaced_id, no_suffix_id, pending_id, 999_999]
        )
        assert provider.acquired_attachment_files(session, []) == {}
    finally:
        event.remove(engine, "before_cursor_execute", record)

    # 아직 내려받지 않은 첨부와 모르는 첨부는 빠진다 — 호출부가 미확인으로 둔다.
    assert files == {
        acquired_id: AcquiredAttachmentFile("제안요청서(고도화).hwpx", "HWPX", 2048),
        replaced_id: AcquiredAttachmentFile("과업지시서.PDF", "PDF", 4096),
        no_suffix_id: AcquiredAttachmentFile("붙임", None, 7),
    }
    # 첨부 수와 무관하게 조회 한 번이고, 빈 입력은 조회하지 않는다.
    assert len(statements) == 1
