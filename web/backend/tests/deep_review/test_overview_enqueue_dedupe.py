"""자동 개요 enqueue의 중복 방지 (결정 28, 2026-09-18).

공고 트랙의 4일 창은 같은 사전규격을 최대 4회 재관측한다. 같은 문서 버전으로
이미 결과가 남은 run이 있으면 정책 변경과 무관하게 자동 촉발은 조용히 물러난다.
재시도 대상 종결·문서 변경·사람의 명시적 재실행은 새 run을 만든다.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.core.config import get_settings
from app.deep_review.models import DocumentVersion, PrespecOverviewRun, WorkJob
from app.deep_review.services import overview_runs
from tests.deep_review.test_overview_runs import _object, context, seed  # noqa: F401  (fixture)


def _settle(session, run, status: str, **changes) -> None:
    """enqueue한 run을 주어진 종결 상태로 닫는다. job도 함께 닫아 활성 run이 남지 않게 한다."""

    run.status = status
    if status == "completed":
        run.result_json = {}
    for key, value in changes.items():
        setattr(run, key, value)
    job = session.get(WorkJob, run.work_job_id)
    job.status = "completed" if status in {"completed", "needs_human_review"} else status
    session.commit()


def _enqueue(session, notice_id, **kwargs):
    return overview_runs.enqueue_overview_run(session, notice_id, settings=get_settings(), **kwargs)


@pytest.mark.parametrize("status", ["completed", "needs_human_review"])
def test_a_settled_run_with_a_result_blocks_the_auto_re_enqueue(context, status):
    session, store = context
    notice, _document, _snapshot = seed(session, store)
    _settle(session, _enqueue(session, notice.id), status)

    assert _enqueue(session, notice.id) is None
    assert len(session.query(PrespecOverviewRun).filter_by(notice_id=notice.id).all()) == 1


def test_failed_and_cancelled_runs_are_retried(context):
    session, store = context
    notice, _document, _snapshot = seed(session, store)
    _settle(session, _enqueue(session, notice.id), "failed")
    _settle(session, _enqueue(session, notice.id), "cancelled")

    run = _enqueue(session, notice.id)

    assert run is not None and run.status == "queued"


def test_a_new_document_version_gets_a_new_run(context):
    session, store = context
    notice, document, _snapshot = seed(session, store)
    # 같은 공고의 다른 문서 버전으로 닫힌 run. 지금 ready 묶음의 문서와 다르다.
    content, _location = _object(
        session, store, namespace="source", key=f"source/{uuid4().hex}.pdf",
        data=f"%PDF-1.4 older {uuid4()}".encode("utf-8"), mime="application/pdf",
    )
    older = DocumentVersion(
        id=uuid4(), notice_id=notice.id, content_object_id=content.id, version=2,
        source_kind="manual", original_filename="합성-제안요청서-이전.pdf", role="제안요청서",
        is_current=False, safety_status="safe",
    )
    session.add(older)
    session.flush()
    _settle(session, _enqueue(session, notice.id), "completed", document_version_id=older.id)

    run = _enqueue(session, notice.id)

    assert run is not None and run.document_version_id == document.id


def test_a_changed_policy_digest_does_not_reassess_the_same_document(context):
    session, store = context
    notice, _document, _snapshot = seed(session, store)
    _settle(session, _enqueue(session, notice.id), "completed", policy_digest="e" * 64)

    assert _enqueue(session, notice.id) is None


def test_a_human_range_ignores_the_dedupe(context):
    session, store = context
    notice, _document, _snapshot = seed(session, store)
    _settle(session, _enqueue(session, notice.id), "completed")

    run = _enqueue(
        session, notice.id, range_source="human", page_start=1, page_end=1, actor_name="담당자",
    )

    assert run is not None and run.range_source == "human"
