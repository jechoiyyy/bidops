"""RL-03 결정 B18: the briefing-recommendation preparation with the REAL ``DocumentBundleService``.

A SW사업대상=Y pre-spec without any grade, with the overview flag off, gets a
document that went through the real fetch path (quarantine → scan → source →
structure).  With ``BIDOPS_RL_ANALYSIS_ENABLED`` the ``briefing_recommendation``
trigger creates and confirms the bundle (only the grade gate of bundle creation is
skipped); with RL off, or for SW≠Y, bundle creation is still refused.  SQLite and,
with ``BIDOPS_TEST_POSTGRES_URL``, migrated PostgreSQL 17.  No G2B, model or network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.document_mcp.processor import DocumentProcessor
from app.deep_review.models import AttachmentFetch, DocumentBundle, DocumentStructure, DocumentVersion
from app.deep_review.services import assets, verdict_trigger
from app.deep_review.services.auto_preparation import maybe_auto_prepare
from app.deep_review.services.prespec_attachments import claim_next, fetch_claimed
from app.lifecycle.models import Attachment, Notice
from app.lifecycle.services.opportunity_connections import parse_attachment_key
from app.screening.models import Judgment  # noqa: F401 - grade seam tables
from tests.app.test_prespec_attachment_fetch import G2B_URL, SAFE_PDF, StubConnector, make_engine
from tests.postgres import migrated_engine, requires_postgres


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "sqlite":
        bind = make_engine()
        init_db(bind)
        try:
            yield bind
        finally:
            bind.dispose()
    else:
        with migrated_engine() as bind:
            yield bind


def configure(monkeypatch, *, rl: bool, auto: bool = False, attachments_dir: Path | None = None) -> None:
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_ENABLED", "true" if rl else "false")
    monkeypatch.setenv("BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED", "true" if auto else "false")
    monkeypatch.setenv("BIDOPS_PRESPEC_OVERVIEW_ENABLED", "false")
    monkeypatch.setenv("BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED", "false")
    if attachments_dir is not None:
        monkeypatch.setenv("BIDOPS_ATTACHMENTS_DIR", str(attachments_dir))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def settings_reset():
    yield
    get_settings.cache_clear()


def fetched_notice(session: Session, tmp_path: Path, *, sw: str) -> int:
    """A pre-spec (no grade) whose one G2B attachment was fetched for real; no bundle yet."""

    notice = Notice(notice_key=f"pre:b18:{os.urandom(4).hex()}", source_type="pre_spec", title="브리핑 추천 사전규격",
                    qualification_flags_json={"sw_business_status": sw}, raw_source={})
    session.add(notice)
    session.flush()
    attachment = Attachment(notice_id=notice.id, name="제안요청서.pdf", source_url=G2B_URL, source_system="g2b",
                            source_attachment_key=parse_attachment_key(G2B_URL), origin="g2b")
    session.add(attachment)
    session.flush()
    session.add(AttachmentFetch(attachment_id=attachment.id, status="대기", eligibility_reason="sw_business_object",
                                attempt_count=0, max_attempts=3,
                                next_attempt_at=datetime.now(UTC) - timedelta(seconds=1), lease_fence=0))
    session.commit()
    claim = claim_next(session, worker_id="worker-b18", lease_seconds=120, notice_id=notice.id)
    assert claim is not None
    row = fetch_claimed(
        session, claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "제안요청서.pdf"))},
        processor=DocumentProcessor(clamav_checker=lambda _content: True), root=tmp_path,
    )
    assert row is not None and row.status == "완료"
    session.commit()
    assert bundles(session, notice.id) == []  # the plain trigger did not prepare it (no grade, overview off)
    structure = session.scalar(select(DocumentStructure).join(
        DocumentVersion, DocumentVersion.id == DocumentStructure.document_version_id,
    ).where(DocumentVersion.notice_id == notice.id))
    assert structure is not None and structure.validation_status == "ready"
    return int(notice.id)


def bundles(session: Session, notice_id: int) -> list[tuple[int, str]]:
    return [(row.revision, row.status) for row in session.scalars(
        select(DocumentBundle).where(DocumentBundle.notice_id == notice_id).order_by(DocumentBundle.revision))]


def test_b18_rl_on_sw_y_without_grade_creates_and_confirms_a_real_bundle(engine, monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, rl=False)
    with Session(engine) as session:
        notice_id = fetched_notice(session, tmp_path, sw="Y")
        configure(monkeypatch, rl=True)
        outcome = maybe_auto_prepare(session, [notice_id], trigger="briefing_recommendation", root=tmp_path)[0]
        session.commit()
        assert outcome.confirmed is True and outcome.reason is None
    with Session(engine) as session:  # durable, real service rows
        assert bundles(session, notice_id) == [(1, "ready")]
        create = session.scalar(select(AuditEvent).where(AuditEvent.action == "document_bundle.create"))
        assert create.safe_metadata["trigger"] == "briefing_recommendation"
        assert create.safe_metadata["effective_grade_at_start"] is None  # no grade was invented
        confirm = session.scalar(select(AuditEvent).where(AuditEvent.action == "document_bundle.auto_confirm"))
        assert confirm.safe_metadata["trigger"] == "briefing_recommendation"


def test_b18_hook_with_the_real_bundle_service_prepares_the_notice(engine, monkeypatch, tmp_path: Path) -> None:
    """``on_briefing_recommendation`` (RL auto on, no bundle double) reaches the real service."""

    configure(monkeypatch, rl=False, attachments_dir=tmp_path)
    with Session(engine) as session:
        notice_id = fetched_notice(session, tmp_path, sw="Y")
        configure(monkeypatch, rl=True, auto=True, attachments_dir=tmp_path)
        outcome = verdict_trigger.on_briefing_recommendation(session, notice_id)
        session.commit()
        # no company/policy in this world: the verdict start itself fails closed after the bundle
        assert outcome.attempt_id is None
    with Session(engine) as session:
        assert bundles(session, notice_id) == [(1, "ready")]


def test_b18_rl_off_is_still_refused_by_the_real_bundle_service(engine, monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, rl=False)
    with Session(engine) as session:
        notice_id = fetched_notice(session, tmp_path, sw="Y")
        outcome = maybe_auto_prepare(session, [notice_id], trigger="briefing_recommendation", root=tmp_path)[0]
        session.commit()
        assert outcome.reason == "effective_grade_ineligible" and outcome.confirmed is False
        assert bundles(session, notice_id) == []


def test_b18_sw_not_y_is_never_prepared(engine, monkeypatch, tmp_path: Path) -> None:
    configure(monkeypatch, rl=False)
    with Session(engine) as session:
        notice_id = fetched_notice(session, tmp_path, sw="N")
        configure(monkeypatch, rl=True)
        outcome = maybe_auto_prepare(session, [notice_id], trigger="briefing_recommendation", root=tmp_path)[0]
        session.commit()
        assert outcome.reason == "grade_not_priority" and outcome.confirmed is False
        assert bundles(session, notice_id) == []
        assert session.scalar(select(func.count()).select_from(DocumentBundle)) == 0


def test_b18_unknown_override_value_is_rejected(engine, monkeypatch, tmp_path: Path) -> None:
    from app.core.api_errors import BundleServiceError
    from app.deep_review.services.document_bundles import DocumentBundleService

    configure(monkeypatch, rl=True)
    with Session(engine) as session:
        notice_id = fetched_notice(session, tmp_path, sw="Y")
        with pytest.raises(BundleServiceError) as error:
            DocumentBundleService(root=tmp_path).create_bundle(
                session, notice_id, "auto-preparation", actor_kind="system", eligibility_override="anything",
            )
        assert error.value.code == "invalid_request"
        session.rollback()
        assert bundles(session, notice_id) == []
