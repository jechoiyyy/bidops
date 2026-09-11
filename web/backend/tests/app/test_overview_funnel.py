"""`scripts/validation/overview_funnel.py`의 단계별 집계 (읽기 전용 검증 스크립트).

이 스크립트는 앱 계약을 바꾸지 않는 진단 도구라 `scripts/validation/`에
있지만, `collect_funnel`은 순수 함수라 기존 in-memory SQLite 픽스처
(`tests/deep_review/test_prespec_projection.py`의 패턴)로 그대로 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.deep_review.models import (
    AttachmentFetch,
    ContentObject,
    DocumentBundle,
    DocumentVersion,
    PrespecOverviewRun,
    WorkJob,
)
from app.lifecycle.models import Attachment, Notice

# 판정·정정 등급은 선별(screening) 소유다. `priority_notice_ids`가 내부에서
# 이 테이블을 읽으므로, `init_db`가 SQLite에 만들 테이블 집합에 들어가도록
# 여기서 먼저 import해 둔다 (tests/app/test_prespec_attachment_fetch.py 선례).
from app.screening.models import Judgment, JudgmentRevision, Review  # noqa: F401

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "validation"))
from overview_funnel import collect_funnel  # noqa: E402

WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def _notice(session: Session, key: str, *, sw_business: bool) -> Notice:
    notice = Notice(
        notice_key=key,
        source_type="pre_spec",
        title=f"{key} 제안요청서",
        agency="테스트 기관",
        qualification_flags_json={"sw_business_status": "Y"} if sw_business else {},
    )
    session.add(notice)
    session.flush()
    return notice


def _document_version(session: Session, notice: Notice) -> DocumentVersion:
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
    session.add(document)
    session.flush()
    return document


def _completed_fetch(session: Session, notice: Notice, document: DocumentVersion) -> None:
    attachment = Attachment(notice_id=notice.id, name="rfp.hwp")
    session.add(attachment)
    session.flush()
    session.add(
        AttachmentFetch(
            attachment_id=attachment.id,
            status="완료",
            eligibility_reason="sw_business_object",
            attempt_count=1,
            max_attempts=3,
            next_attempt_at=WHEN,
            document_version_id=document.id,
            completed_at=WHEN,
        )
    )
    session.flush()


def _ready_bundle(session: Session, notice: Notice) -> None:
    session.add(
        DocumentBundle(
            notice_id=notice.id, revision=1, version=1, status="ready", issues_snapshot=[],
        )
    )
    session.flush()


def _completed_overview_run(session: Session, notice: Notice, document: DocumentVersion) -> None:
    job = WorkJob(
        job_type="prespec_overview", aggregate_type="prespec_overview_run",
        aggregate_id=uuid4(), status="completed",
    )
    session.add(job)
    session.flush()
    session.add(
        PrespecOverviewRun(
            notice_id=notice.id, document_version_id=document.id, work_job_id=job.id,
            status="completed", range_source="auto", range_reason_codes=[],
            policy_digest="0" * 64, model_name="test-model", warnings_json=[],
            reason_codes=[], call_count=1, raw_response_refs=[],
            result_json={"schema_version": "test"},
        )
    )
    session.flush()


@pytest.fixture()
def funnel_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_collect_funnel_stage_counts(funnel_session: Session) -> None:
    session = funnel_session
    qualified = _notice(session, "pre:QUALIFIED", sw_business=True)
    _notice(session, "pre:UNQUALIFIED", sw_business=False)

    document = _document_version(session, qualified)
    _completed_fetch(session, qualified, document)
    _ready_bundle(session, qualified)
    _completed_overview_run(session, qualified, document)
    session.commit()

    result = collect_funnel(session)

    assert result["total_pre_spec"] == 2
    assert result["candidates"]["count"] == 1
    assert result["attachment"]["completed"]["count"] == 1
    assert result["attachment"]["all_terminal_zero_completed"]["count"] == 0
    assert result["bundle_ready"]["count"] == 1
    assert result["overview_run"]["has_run"]["count"] == 1
    assert result["overview_run"]["status_distribution"]["completed"]["count"] == 1
    assert result["overview_run"]["status_distribution"]["failed"]["count"] == 0
    assert result["overview_run"]["range_source_distribution"]["auto"]["count"] == 1
    assert result["deep_review_auto_start"]["total_deep_reviews"] == 0
    assert result["deep_review_auto_start"]["count"] == 0
