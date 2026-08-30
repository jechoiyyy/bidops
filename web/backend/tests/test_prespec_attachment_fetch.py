"""T-20b eligibility, queue, and provider-fetch tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import init_db
from app.document_mcp.processor import DocumentProcessor
from app.ingest.loader import _upsert_attachments
from app.models import (
    Attachment,
    AttachmentFetch,
    ContentObjectLocation,
    DocumentVersion,
    Notice,
    Opportunity,
    OpportunityLink,
    OrderPlan,
)
from app.services import assets
from app.services.prespec_attachments import (
    SOURCE_SYSTEM,
    claim_next,
    fetch_claimed,
    parse_attachment_key,
    refresh_fetch_eligibility,
)
from app.workers.prespec_attachment import run_once


G2B_URL = (
    "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
    "?bfSpecRegNo=R26BD00266984&fileType=BFDTL&fileSeq=1"
)
SAFE_PDF = Path(__file__).parent / "fixtures/document_bundles/safe.pdf"
SAFE_HWP = Path(__file__).parent / "fixtures/documents/labor_template.hwp"


def make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def db_session():
    engine = make_engine()
    init_db(engine)
    with Session(engine) as session:
        yield session


class StubConnector:
    source_system = SOURCE_SYSTEM

    def __init__(
        self,
        response: assets.ProviderResponse | None = None,
        error: Exception | None = None,
    ):
        self.response = response
        self.error = error

    def fetch(self, _url: str) -> assets.ProviderResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def add_attachment(
    session: Session,
    *,
    sw_status: str = "Y",
    tracking_status: str | None = None,
    notice_link_status: str | None = None,
    with_order_plan: bool = False,
    source_url: str | None = G2B_URL,
    name: str = "metadata.pdf",
) -> tuple[Notice, Attachment, Opportunity | None]:
    notice = Notice(
        notice_key=f"pre:{session.query(Notice).count() + 1}",
        source_type="pre_spec",
        title="사전규격 테스트",
        qualification_flags_json={"sw_business_status": sw_status},
        raw_source={},
    )
    session.add(notice)
    session.flush()
    attachment = Attachment(
        notice_id=notice.id,
        name=name,
        source_url=source_url,
        source_system=SOURCE_SYSTEM if source_url == G2B_URL else None,
        source_attachment_key=parse_attachment_key(source_url),
        origin="g2b",
    )
    session.add(attachment)
    opportunity = None
    if tracking_status is not None:
        opportunity = Opportunity(
            first_registered_stage="order_plan",
            tracking_status=tracking_status,
            tracking_selected_by=None if tracking_status == "미선택" else "검토자",
            tracking_selected_at=None if tracking_status == "미선택" else datetime.now(UTC),
            tracking_reason=None if tracking_status == "미선택" else "추적 대상",
        )
        session.add(opportunity)
        session.flush()
        if notice_link_status is not None:
            session.add(
                OpportunityLink(
                    opportunity_id=opportunity.id,
                    notice_id=None if notice_link_status == "검색 미확인" else notice.id,
                    stage="notice",
                    link_type="candidate" if notice_link_status != "확정" else "official",
                    status=notice_link_status,
                    evidence_external_no="PRE-1" if notice_link_status == "확정" else None,
                    human_decision="accepted" if notice_link_status == "사람 확인 완료" else None,
                    reviewer_name="검토자" if notice_link_status == "사람 확인 완료" else None,
                    reviewed_at=datetime.now(UTC) if notice_link_status == "사람 확인 완료" else None,
                    review_reason="확인" if notice_link_status == "사람 확인 완료" else None,
                )
            )
        if with_order_plan:
            order_plan = OrderPlan(order_plan_unty_no=f"R26AA{opportunity.id or 1:08d}")
            session.add(order_plan)
            session.flush()
            session.add(
                OpportunityLink(
                    opportunity_id=opportunity.id,
                    order_plan_id=order_plan.id,
                    stage="order_plan",
                    link_type="official",
                    status="확정",
                    evidence_external_no=order_plan.order_plan_unty_no,
                )
            )
    session.flush()
    return notice, attachment, opportunity


def queue_one(session: Session, **kwargs) -> tuple[Notice, Attachment, AttachmentFetch]:
    notice, attachment, _ = add_attachment(session, **kwargs)
    refresh_fetch_eligibility(session, notice_ids=[notice.id])
    fetch = session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id))
    assert fetch is not None
    session.commit()
    return notice, attachment, fetch


def test_parse_measured_g2b_attachment_key():
    assert parse_attachment_key(G2B_URL) == "R26BD00266984:BFDTL:1"


@pytest.mark.parametrize(
    "url",
    [
        G2B_URL.replace("www.g2b.go.kr", "g2b.example.go.kr"),
        G2B_URL.replace("https:", "http:"),
        G2B_URL.replace("/downloadFile.do", "/downloadFile.do/"),
        G2B_URL.replace("&fileSeq=1", ""),
        G2B_URL.replace("fileSeq=1", "fileSeq="),
    ],
)
def test_parse_attachment_key_is_strict(url: str):
    assert parse_attachment_key(url) is None


def test_loader_sets_only_strict_pre_spec_provider_provenance(db_session: Session):
    notice = Notice(notice_key="pre:loader", source_type="pre_spec", raw_source={})
    db_session.add(notice)
    db_session.flush()
    _upsert_attachments(
        db_session,
        notice,
        [
            {"name": "one.pdf", "url": G2B_URL},
            {"name": "two.pdf", "url": "https://other.test/file.pdf"},
        ],
    )
    db_session.flush()
    rows = {row.name: row for row in notice.attachments}
    assert rows["one.pdf"].source_system == "g2b"
    assert rows["one.pdf"].source_attachment_key == "R26BD00266984:BFDTL:1"
    assert rows["two.pdf"].source_system is None
    assert rows["two.pdf"].source_attachment_key is None


def test_sw_business_object_is_queued(db_session: Session):
    _, _, fetch = queue_one(db_session, sw_status="Y")
    assert fetch.status == "대기"
    assert fetch.eligibility_reason == "sw_business_object"


def test_sw_n_without_tracking_is_not_queued(db_session: Session):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)) is None


def test_tracked_candidate_notice_with_order_plan_is_queued(db_session: Session):
    _, _, fetch = queue_one(
        db_session,
        sw_status="N",
        tracking_status="계속 추적",
        notice_link_status="후보 확인 대기",
        with_order_plan=True,
    )
    assert fetch.eligibility_reason == "tracked_order_plan"


@pytest.mark.parametrize("link_status", ["검색 미확인"])
@pytest.mark.parametrize("tracking_status", ["미선택", "종료"])
def test_unconfirmed_or_untracked_path_is_not_queued(
    db_session: Session, link_status: str, tracking_status: str
):
    notice, attachment, _ = add_attachment(
        db_session,
        sw_status="N",
        tracking_status=tracking_status,
        notice_link_status=link_status,
        with_order_plan=True,
    )
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)) is None


def test_order_plan_link_is_required_for_tracked_path(db_session: Session):
    notice, attachment, _ = add_attachment(
        db_session,
        sw_status="N",
        tracking_status="계속 추적",
        notice_link_status="후보 확인 대기",
        with_order_plan=False,
    )
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)) is None


def test_later_tracking_choice_re_evaluates_into_queue(db_session: Session):
    notice, _, opportunity = add_attachment(
        db_session,
        sw_status="N",
        tracking_status="미선택",
        notice_link_status="후보 확인 대기",
        with_order_plan=True,
    )
    assert opportunity is not None
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    opportunity.tracking_status = "계속 추적"
    opportunity.tracking_selected_by = "검토자"
    opportunity.tracking_reason = "추적"
    opportunity.tracking_selected_at = datetime.now(UTC)
    db_session.commit()
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 1
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0


def test_re_evaluation_is_idempotent_and_does_not_revive_terminal_rows(db_session: Session):
    notice, _, fetch = queue_one(db_session, sw_status="Y")
    fetch.status = "차단"
    fetch.last_error_code = "unsupported_extension"
    db_session.commit()
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    refreshed = db_session.get(AttachmentFetch, fetch.id)
    assert refreshed is not None and refreshed.status == "차단"


def test_claim_orders_due_rows_and_increments_fence(db_session: Session):
    _, _, first = queue_one(db_session, sw_status="Y")
    claim = claim_next(
        db_session,
        worker_id="prespec-worker",
        lease_seconds=120,
        now=datetime.now(UTC),
    )
    assert claim is not None
    assert claim.id == first.id
    row = db_session.get(AttachmentFetch, first.id)
    assert row is not None and row.status == "진행" and row.lease_fence == 1


@pytest.mark.parametrize(
    ("filename", "fixture"),
    [("header.pdf", SAFE_PDF), ("header.hwp", SAFE_HWP)],
)
def test_fetch_fixture_completes_with_provider_filename(
    db_session: Session, tmp_path: Path, filename: str, fixture: Path
):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    result = fetch_claimed(
        db_session,
        claim,
        connectors={
            "g2b": StubConnector(
                assets.ProviderResponse(fixture.read_bytes(), G2B_URL, filename)
            )
        },
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )
    assert result is not None and result.status == "완료"
    document = db_session.get(DocumentVersion, result.document_version_id)
    assert document is not None
    assert document.source_kind == "provider"
    assert document.original_filename == filename
    assert document.role == "기타"
    assert db_session.scalar(select(func.count()).select_from(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source")) == 1


def test_same_bytes_reacquisition_does_not_create_version(db_session: Session, tmp_path: Path):
    _, _, fetch = queue_one(db_session, sw_status="Y")
    response = assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "same.pdf")
    connector = {"g2b": StubConnector(response)}
    processor = DocumentProcessor(clamav_checker=lambda _content: True)
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    first = fetch_claimed(db_session, claim, connectors=connector, processor=processor, root=tmp_path)
    assert first is not None and first.document_version_id is not None
    first_document_id = first.document_version_id
    fetch = db_session.get(AttachmentFetch, fetch.id)
    assert fetch is not None
    fetch.status = "대기"
    fetch.document_version_id = None
    fetch.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    fetch.completed_at = None
    db_session.commit()
    claim = claim_next(db_session, worker_id="worker-b", lease_seconds=120)
    assert claim is not None
    second = fetch_claimed(db_session, claim, connectors=connector, processor=processor, root=tmp_path)
    assert second is not None and second.document_version_id == first_document_id
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 1


def test_unsupported_docx_is_blocked_without_consuming_attempt(db_session: Session, tmp_path: Path):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(b"docx", G2B_URL, "bad.docx"))},
        root=tmp_path,
    )
    assert result is not None and result.status == "차단"
    assert result.last_error_code == "unsupported_extension"
    assert result.attempt_count == 0


def test_malware_never_creates_source_location(db_session: Session, tmp_path: Path):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    eicar = (Path(__file__).parent / "fixtures/document_bundles/eicar.pdf").read_bytes()
    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(eicar, G2B_URL, "infected.pdf"))},
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )
    assert result is not None and result.status == "차단"
    assert result.last_error_code == "malware_detected"
    assert db_session.scalar(select(func.count()).select_from(ContentObjectLocation).where(ContentObjectLocation.namespace_key == "source")) == 0


def test_clamav_unavailable_is_retried_with_backoff(db_session: Session, tmp_path: Path):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    before = datetime.now(UTC)
    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "scan.pdf"))},
        processor=DocumentProcessor(),
        root=tmp_path,
    )
    assert result is not None and result.status == "대기"
    assert result.last_error_code == "clamav_unavailable"
    assert result.attempt_count == 1 and result.next_attempt_at > before


def test_max_attempts_exhaustion_is_failed(db_session: Session, tmp_path: Path):
    _, _, fetch = queue_one(db_session, sw_status="Y")
    fetch.max_attempts = 1
    db_session.commit()
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "scan.pdf"))},
        processor=DocumentProcessor(),
        root=tmp_path,
    )
    assert result is not None and result.status == "실패"
    assert result.attempt_count == 1


def test_disabled_worker_is_quiet_and_does_not_claim(db_session: Session):
    _, _, fetch = queue_one(db_session, sw_status="Y")
    assert run_once(db_session, "worker-a", connectors={}) is False
    assert db_session.get(AttachmentFetch, fetch.id).status == "대기"


def test_last_error_code_is_bounded_and_contains_no_exception_details(db_session: Session):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    result = fetch_claimed(
        db_session,
        claim,
        connectors={
            "g2b": StubConnector(
                error=RuntimeError(
                    "https://www.g2b.go.kr/?secret=do-not-store credential=hidden"
                )
            )
        },
    )
    assert result is not None
    assert result.last_error_code == "service_unavailable"
    assert "g2b.go.kr" not in (result.last_error_code or "")
    assert "secret" not in (result.last_error_code or "")
    assert "credential" not in (result.last_error_code or "")
