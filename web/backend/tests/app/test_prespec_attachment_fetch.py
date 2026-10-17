"""T-20b eligibility, queue, and provider-fetch tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.constants import (
    UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS,
    UNSUPPORTED_ATTACHMENT_ISSUE_CODE,
)
from app.core.db import init_db
from app.deep_review.document_mcp.errors import DocumentProcessingError
from app.deep_review.document_mcp.processor import DocumentProcessor
from app.lifecycle.ingest.loader import ObservationSnapshotConflictError, _upsert_attachments
from app.core.models import AuditEvent
from app.deep_review.services.auto_preparation import (
    auto_preparation_fields,
    maybe_auto_prepare,
)
from app.deep_review.models import (
    AttachmentFetch,
    DocumentBundle,
    DocumentBundleItem,
    ContentObject,
    ContentObjectLocation,
    DocumentBlock,
    DocumentStructure,
    DocumentVersion,
)
from app.lifecycle.models import (
    Attachment,
    Notice,
    Opportunity,
    OpportunityLink,
    OrderPlan,
    Run,
)
# 판정·정정 등급은 선별 소유다. 두 모듈이 합쳐지는 검사라 `tests/app/`에 있고,
# 이 import가 `init_db`보다 먼저 선별 테이블을 metadata에 등록한다.
from app.screening.models import Judgment, Review
from app.deep_review.services import assets, prespec_attachments
from app.lifecycle.services.opportunity_connections import (
    parse_attachment_key,
    tracked_order_plan_connection,
)
from app.deep_review.services.prespec_attachments import (
    SOURCE_SYSTEM,
    claim_next,
    fetch_claimed,
    refresh_fetch_eligibility,
)
from app.deep_review.services.deep_review_hooks import PreSpecAttachmentEligibilityHook
from app.deep_review.workers import prespec_attachment as prespec_attachment_worker
from app.deep_review.workers.prespec_attachment import run_once


G2B_URL = (
    "https://www.g2b.go.kr/pn/pnz/pnza/UntyAtchFile/downloadFile.do"
    "?bfSpecRegNo=R26BD00266984&fileType=BFDTL&fileSeq=1"
)
SAFE_PDF = Path(__file__).parents[1] / "fixtures/document_bundles/safe.pdf"
SAFE_HWP = Path(__file__).parents[1] / "fixtures/documents/labor_template.hwp"


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
    notice_human_decision: str | None = None,
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
            human_decision = notice_human_decision
            if human_decision is None and notice_link_status == "사람 확인 완료":
                human_decision = "accepted"
            session.add(
                OpportunityLink(
                    opportunity_id=opportunity.id,
                    notice_id=None if notice_link_status == "검색 미확인" else notice.id,
                    stage="notice",
                    link_type="candidate" if notice_link_status != "확정" else "official",
                    status=notice_link_status,
                    evidence_external_no="PRE-1" if notice_link_status == "확정" else None,
                    human_decision=human_decision,
                    reviewer_name="검토자" if human_decision is not None else None,
                    reviewed_at=datetime.now(UTC) if human_decision is not None else None,
                    review_reason="확인" if human_decision is not None else None,
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


def test_loader_accepts_explicit_provider_identity_only_when_url_proves_it(
    db_session: Session,
):
    notice = Notice(notice_key="pre:explicit", source_type="pre_spec", raw_source={})
    db_session.add(notice)
    db_session.flush()
    source_key = "R26BD00266984:BFDTL:1"
    _upsert_attachments(
        db_session,
        notice,
        [
            {
                "name": "explicit.pdf",
                "url": G2B_URL,
                "source_system": "g2b",
                "source_attachment_key": source_key,
            }
        ],
    )
    db_session.flush()
    stored = db_session.scalar(select(Attachment))
    assert stored is not None and stored.source_attachment_key == source_key

    with pytest.raises(ObservationSnapshotConflictError):
        _upsert_attachments(
            db_session,
            notice,
            [
                {
                    "name": "conflict.pdf",
                    "url": G2B_URL,
                    "source_system": "g2b",
                    "source_attachment_key": "different-key",
                }
            ],
        )


def test_loader_retires_missing_provider_attachment_and_revives_same_source_key(
    db_session: Session,
):
    first_seen = datetime(2026, 8, 29, 1, tzinfo=UTC)
    retired_at = first_seen + timedelta(days=1)
    seen_again = retired_at + timedelta(days=1)
    notice = Notice(notice_key="pre:retention", source_type="pre_spec", raw_source={})
    manual = Attachment(
        notice=notice,
        name="manual.pdf",
        source_url=None,
        origin="manual",
    )
    db_session.add_all([notice, manual])
    db_session.flush()

    _upsert_attachments(
        db_session,
        notice,
        [{"name": "provider-v1.pdf", "url": G2B_URL}],
        observed_at=first_seen,
    )
    db_session.flush()
    provider = db_session.scalar(
        select(Attachment).where(Attachment.source_attachment_key.is_not(None))
    )
    assert provider is not None
    provider_id = provider.id
    assert provider.last_seen_at == first_seen

    _upsert_attachments(db_session, notice, [], observed_at=retired_at)
    db_session.flush()
    assert db_session.get(Attachment, provider_id) is provider
    assert provider.retired_at == retired_at
    assert provider.retired_reason == "not_seen_in_source"
    assert manual.retired_at is None

    changed_url = G2B_URL + "&downloadToken=rotated"
    _upsert_attachments(
        db_session,
        notice,
        [{"name": "provider-v2.pdf", "url": changed_url}],
        observed_at=seen_again,
    )
    db_session.flush()

    current = db_session.scalar(
        select(Attachment).where(Attachment.source_attachment_key.is_not(None))
    )
    assert current is not None and current.id == provider_id
    assert current.name == "provider-v2.pdf"
    assert current.source_url == changed_url
    assert current.last_seen_at == seen_again
    assert current.retired_at is None
    assert current.retired_reason is None
    assert db_session.scalar(select(func.count(Attachment.id))) == 2


def test_sw_business_object_is_queued(db_session: Session):
    _, _, fetch = queue_one(db_session, sw_status="Y")
    assert fetch.status == "대기"
    assert fetch.eligibility_reason == "sw_business_object"


def test_sw_n_without_tracking_is_not_queued(db_session: Session):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)) is None


@pytest.mark.parametrize(
    ("link_status", "human_decision", "expected"),
    [
        ("후보 확인 대기", None, False),
        ("사람 확인 완료", "rejected", False),
        ("사람 확인 완료", "accepted", True),
        ("확정", None, True),
    ],
)
def test_only_authoritative_notice_link_grants_tracked_order_plan_exception(
    db_session: Session,
    link_status: str,
    human_decision: str | None,
    expected: bool,
):
    notice, attachment, _ = add_attachment(
        db_session,
        sw_status="N",
        tracking_status="계속 추적",
        notice_link_status=link_status,
        notice_human_decision=human_decision,
        with_order_plan=True,
    )

    assert tracked_order_plan_connection(db_session, notice.id) is expected
    created = refresh_fetch_eligibility(db_session, notice_ids=[notice.id])
    fetch = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    )
    assert created == int(expected)
    assert (fetch is not None) is expected
    if fetch is not None:
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
        notice_link_status="사람 확인 완료",
        with_order_plan=False,
    )
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)) is None


def test_later_tracking_choice_re_evaluates_into_queue(db_session: Session):
    notice, _, opportunity = add_attachment(
        db_session,
        sw_status="N",
        tracking_status="미선택",
        notice_link_status="사람 확인 완료",
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
    _, _, second = queue_one(db_session, sw_status="Y")
    current_time = datetime.now(UTC)
    first.next_attempt_at = current_time - timedelta(minutes=2)
    second.next_attempt_at = current_time - timedelta(minutes=1)
    db_session.commit()
    claim = claim_next(
        db_session,
        worker_id="prespec-worker",
        lease_seconds=120,
        now=current_time,
    )
    assert claim is not None
    assert claim.id == first.id
    row = db_session.get(AttachmentFetch, first.id)
    assert row is not None and row.status == "진행" and row.lease_fence == 1
    assert db_session.get(AttachmentFetch, second.id).status == "대기"


def test_targeted_run_skips_an_earlier_foreign_queue_row(
    db_session: Session,
    tmp_path: Path,
):
    _, _, foreign = queue_one(db_session, sw_status="Y")
    target_notice, _, target = queue_one(db_session, sw_status="Y")
    current_time = datetime.now(UTC)
    foreign.next_attempt_at = current_time - timedelta(minutes=2)
    target.next_attempt_at = current_time - timedelta(minutes=1)
    db_session.commit()

    assert run_once(
        db_session,
        "worker-targeted",
        notice_id=target_notice.id,
        connectors={
            "g2b": StubConnector(
                assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "target.pdf")
            )
        },
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )

    assert db_session.get(AttachmentFetch, foreign.id).status == "대기"
    assert db_session.get(AttachmentFetch, foreign.id).lease_fence == 0
    assert db_session.get(AttachmentFetch, target.id).status == "완료"


def test_targeted_claim_reclaims_an_expired_lease(db_session: Session):
    target_notice, _, target = queue_one(db_session, sw_status="Y")
    current_time = datetime.now(UTC)
    target.status = "진행"
    target.lease_owner = "worker-expired"
    target.lease_expires_at = current_time - timedelta(seconds=1)
    target.lease_fence = 4
    db_session.commit()

    claim = claim_next(
        db_session,
        worker_id="worker-recovery",
        lease_seconds=120,
        now=current_time,
        notice_id=target_notice.id,
    )

    assert claim is not None
    assert claim.id == target.id
    assert claim.lease_fence == 5
    refreshed = db_session.get(AttachmentFetch, target.id)
    assert refreshed is not None
    assert refreshed.status == "진행"
    assert refreshed.lease_owner == "worker-recovery"


def test_target_with_no_eligible_row_does_not_claim_other_notice(
    db_session: Session,
):
    target_notice, _, failed = queue_one(db_session, sw_status="Y")
    failed.status = "실패"
    failed.last_error_code = "service_unavailable"
    _, _, foreign = queue_one(db_session, sw_status="Y")
    db_session.commit()

    assert claim_next(
        db_session,
        worker_id="worker-targeted",
        lease_seconds=120,
        notice_id=target_notice.id,
    ) is None
    assert db_session.get(AttachmentFetch, failed.id).status == "실패"
    assert db_session.get(AttachmentFetch, failed.id).lease_fence == 0
    assert db_session.get(AttachmentFetch, foreign.id).status == "대기"


@pytest.mark.parametrize("invalid_notice_id", [0, -1, True, "1"])
def test_claim_rejects_invalid_notice_id_before_database_access(invalid_notice_id):
    class NoDatabaseAccess:
        def in_transaction(self):
            raise AssertionError("database access must not occur")

    with pytest.raises(ValueError, match="notice_id must be a positive integer"):
        claim_next(
            NoDatabaseAccess(),
            worker_id="worker-targeted",
            lease_seconds=120,
            notice_id=invalid_notice_id,
        )


def test_run_once_rejects_invalid_notice_id_before_connector_setup(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_connector_setup(_settings):
        raise AssertionError("connector setup must not occur")

    monkeypatch.setattr(
        prespec_attachment_worker.assets,
        "g2b_attachment_connectors",
        fail_connector_setup,
    )
    with pytest.raises(ValueError, match="notice_id must be a positive integer"):
        run_once(object(), "worker-targeted", notice_id=0)


def test_cli_rejects_invalid_notice_id_before_runtime_setup(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        prespec_attachment_worker,
        "get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("runtime setup must not occur")),
    )
    with pytest.raises(SystemExit) as error:
        prespec_attachment_worker.main(["--once", "--notice-id", "0"])
    assert error.value.code == 2


def test_cli_passes_notice_id_to_one_shot_worker(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str, dict[str, object]]] = []
    session = object()

    class SessionContext:
        def __enter__(self):
            return session

        def __exit__(self, *_exc):
            return False

    class Scanner:
        def __init__(self, **_kwargs):
            pass

        def scan(self, _content):
            return True

    settings = SimpleNamespace(
        prespec_attachment_worker_concurrency=1,
        clamav_host="clamav",
        clamav_port=3310,
        clamav_timeout_seconds=30.0,
        worker_id="worker-targeted",
        prespec_attachment_lease_seconds=120.0,
    )
    connectors = {"g2b": object()}

    monkeypatch.setattr(prespec_attachment_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(prespec_attachment_worker, "configure", lambda _settings: None)
    monkeypatch.setattr(
        prespec_attachment_worker.assets,
        "g2b_attachment_connectors",
        lambda _settings: connectors,
    )
    monkeypatch.setattr(
        prespec_attachment_worker,
        "assert_object_store_runtime",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(prespec_attachment_worker, "ClamAVScanner", Scanner)
    monkeypatch.setattr(prespec_attachment_worker, "SessionLocal", SessionContext)
    monkeypatch.setattr(prespec_attachment_worker.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        prespec_attachment_worker,
        "run_once",
        lambda actual_session, worker_id, **kwargs: calls.append(
            (actual_session, worker_id, kwargs)
        ),
    )

    prespec_attachment_worker.main(["--once", "--notice-id", "179"])

    assert len(calls) == 1
    actual_session, worker_id, kwargs = calls[0]
    assert actual_session is session
    assert worker_id == "worker-targeted"
    assert kwargs["notice_id"] == 179
    assert kwargs["connectors"] is connectors


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


def test_clean_fetch_materializes_canonical_structure_and_blocks(
    db_session: Session, tmp_path: Path
):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    result = fetch_claimed(
        db_session,
        claim,
        connectors={
            "g2b": StubConnector(
                assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "clean.pdf")
            )
        },
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )
    assert result is not None and result.status == "완료"
    document = db_session.get(DocumentVersion, result.document_version_id)
    assert document is not None
    structure = db_session.scalar(
        select(DocumentStructure).where(DocumentStructure.document_version_id == document.id)
    )
    assert structure is not None
    expected_source_hash = hashlib.sha256(SAFE_PDF.read_bytes()).hexdigest()
    assert structure.source_sha256 == expected_source_hash
    blocks = db_session.scalars(
        select(DocumentBlock).where(DocumentBlock.structure_id == structure.id)
    ).all()
    assert len(blocks) == structure.block_count
    assert blocks
    payload_location = db_session.scalar(
        select(ContentObjectLocation).where(
            ContentObjectLocation.content_object_id == structure.payload_content_object_id,
            ContentObjectLocation.namespace_key == "structure",
        )
    )
    assert payload_location is not None
    raw, _metadata = assets.read_object("structure", payload_location.object_key, root=tmp_path)
    assert hashlib.sha256(raw).hexdigest() == structure.payload_sha256
    payload = json.loads(raw)
    assert payload["document_version_id"] == str(document.id)
    assert payload["source_sha256"] == expected_source_hash


def test_lost_lease_cleans_source_without_materializing_structure(
    db_session: Session, tmp_path: Path
):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None

    class LeaseLostConnector(StubConnector):
        def fetch(self, _url: str) -> assets.ProviderResponse:
            row = db_session.get(AttachmentFetch, claim.id)
            assert row is not None
            row.status = "차단"
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error_code = "service_unavailable"
            db_session.commit()
            return assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "lost-lease.pdf")

    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": LeaseLostConnector()},
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )
    assert result is None
    assert not list((assets.asset_root(tmp_path) / "source").iterdir())
    assert not list((assets.asset_root(tmp_path) / "structure").iterdir())
    assert db_session.scalar(select(func.count()).select_from(DocumentStructure)) == 0
    assert db_session.scalar(select(func.count()).select_from(DocumentBlock)) == 0


def test_structure_failure_rolls_back_safe_promotion_and_blocks_claim(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None

    def fail_materialize(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise DocumentProcessingError("invalid_structure", "구조 계약 검증에 실패했습니다")

    monkeypatch.setattr(prespec_attachments, "materialize_structure", fail_materialize)
    result = fetch_claimed(
        db_session,
        claim,
        connectors={
            "g2b": StubConnector(
                assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "invalid-structure.pdf")
            )
        },
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )

    assert result is not None
    assert result.status == "차단"
    assert result.last_error_code == "invalid_structure"
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
    assert db_session.scalar(select(func.count()).select_from(DocumentStructure)) == 0
    assert db_session.scalar(select(func.count()).select_from(DocumentBlock)) == 0
    assert db_session.scalar(select(func.count()).select_from(ContentObject)) == 0
    assert db_session.scalar(select(func.count()).select_from(ContentObjectLocation)) == 0
    asset_root = assets.asset_root(tmp_path)
    assert not list((asset_root / "source").iterdir())
    assert not list((asset_root / "structure").iterdir())


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


def test_changed_bytes_reacquisition_creates_v2_and_demotes_v1(
    db_session: Session,
    tmp_path: Path,
):
    _, attachment, fetch = queue_one(db_session, sw_status="Y")
    bodies = [SAFE_PDF.read_bytes(), SAFE_PDF.read_bytes() + b"\n"]

    class ChangingBytesConnector:
        source_system = SOURCE_SYSTEM

        def fetch(self, _url: str) -> assets.ProviderResponse:
            return assets.ProviderResponse(bodies.pop(0), G2B_URL, "changed.pdf")

    connector = {"g2b": ChangingBytesConnector()}
    processor = DocumentProcessor(clamav_checker=lambda _content: True)
    first_claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert first_claim is not None
    first = fetch_claimed(
        db_session,
        first_claim,
        connectors=connector,
        processor=processor,
        root=tmp_path,
    )
    assert first is not None and first.document_version_id is not None

    fetch = db_session.get(AttachmentFetch, fetch.id)
    assert fetch is not None
    fetch.status = "대기"
    fetch.document_version_id = None
    fetch.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    fetch.completed_at = None
    db_session.commit()

    second_claim = claim_next(db_session, worker_id="worker-b", lease_seconds=120)
    assert second_claim is not None
    second = fetch_claimed(
        db_session,
        second_claim,
        connectors=connector,
        processor=processor,
        root=tmp_path,
    )

    assert second is not None and second.document_version_id is not None
    versions = db_session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.attachment_id == attachment.id)
        .order_by(DocumentVersion.version.asc())
    ).all()
    assert [row.version for row in versions] == [1, 2]
    assert [row.is_current for row in versions] == [False, True]
    assert versions[1].replaces_document_version_id == versions[0].id
    assert second.document_version_id == versions[1].id


def test_safe_fetch_revalidates_locked_attachment_provenance_after_io(
    db_session: Session,
    tmp_path: Path,
):
    _, attachment, fetch = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None

    class ProvenanceChangingConnector:
        source_system = SOURCE_SYSTEM

        def fetch(self, _url: str) -> assets.ProviderResponse:
            current = db_session.get(Attachment, attachment.id)
            assert current is not None
            current.source_url = G2B_URL + "&downloadToken=rotated"
            db_session.commit()
            return assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "race.pdf")

    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": ProvenanceChangingConnector()},
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )

    assert result is None
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 0
    stored_fetch = db_session.get(AttachmentFetch, fetch.id)
    assert stored_fetch is not None
    assert stored_fetch.status == "진행"
    assert stored_fetch.document_version_id is None
    assert not list((assets.asset_root(tmp_path) / "source").iterdir())
    assert not list((assets.asset_root(tmp_path) / "structure").iterdir())


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
    eicar = (Path(__file__).parents[1] / "fixtures/document_bundles/eicar.pdf").read_bytes()
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
    assert db_session.scalar(select(func.count()).select_from(DocumentStructure)) == 0
    assert db_session.scalar(select(func.count()).select_from(DocumentBlock)) == 0


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


def test_backoff_seconds_schedule():
    assert prespec_attachments._backoff_seconds(1) == 60
    assert prespec_attachments._backoff_seconds(2) == 300
    assert prespec_attachments._backoff_seconds(3) == 900
    assert prespec_attachments._backoff_seconds(4) == 900


def test_converter_unavailable_is_retried_with_backoff(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, _, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None

    def fail_materialize(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise DocumentProcessingError("converter_unavailable", "변환기를 사용할 수 없습니다")

    monkeypatch.setattr(prespec_attachments, "materialize_structure", fail_materialize)
    before = datetime.now(UTC)
    result = fetch_claimed(
        db_session,
        claim,
        connectors={
            "g2b": StubConnector(
                assets.ProviderResponse(SAFE_PDF.read_bytes(), G2B_URL, "converter.pdf")
            )
        },
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )

    assert result is not None and result.status == "대기"
    assert result.last_error_code == "converter_unavailable"
    assert result.attempt_count == 1
    assert result.next_attempt_at is not None and result.next_attempt_at > before


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


# --- 판정 등급이 여는 취득 자격 (명세 §6.2 "자격", 결합 규칙 §5) --------------


def _grade(session: Session, notice: Notice, grade: str) -> None:
    """1차 판정 등급을 심는다. 선별 소유 테이블이라 두 모듈 조합 테스트에서만 쓴다."""

    session.add(Judgment(notice_id=notice.id, grade=grade, readiness="확인 완료"))
    session.flush()


def _corrected(session: Session, notice: Notice, grade: str | None) -> None:
    """사람 정정 등급을 심는다."""

    session.add(Review(notice_id=notice.id, corrected_grade=grade, reviewer_snapshot="검토자"))
    session.flush()


def test_priority_grade_alone_opens_attachment_fetch_for_a_non_sw_untracked_notice(
    db_session: Session,
):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    _grade(db_session, notice, "우선 검토")

    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 1

    row = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    )
    assert row is not None
    assert row.status == "대기"
    assert row.eligibility_reason == "priority_grade"


@pytest.mark.parametrize(
    ("grade", "expected"),
    [("검토 권장", None), ("관찰 대상", None), ("제외", None), ("우선 검토", "priority_grade")],
)
def test_only_the_priority_grade_opens_eligibility(
    db_session: Session, grade: str, expected: str | None
):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    _grade(db_session, notice, grade)

    refresh_fetch_eligibility(db_session, notice_ids=[notice.id])

    row = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    )
    assert (row.eligibility_reason if row is not None else None) == expected


def test_existing_reasons_win_over_the_grade_reason(db_session: Session):
    """§5 결합 규칙: 등급+SW는 `sw_business_object`, 등급+추적은 `tracked_order_plan`."""

    sw_notice, sw_attachment, _ = add_attachment(db_session, sw_status="Y")
    _grade(db_session, sw_notice, "우선 검토")
    tracked_notice, tracked_attachment, _ = add_attachment(
        db_session,
        sw_status="N",
        tracking_status="계속 추적",
        notice_link_status="확정",
        with_order_plan=True,
    )
    _grade(db_session, tracked_notice, "우선 검토")
    both_notice, both_attachment, _ = add_attachment(
        db_session,
        sw_status="Y",
        tracking_status="계속 추적",
        notice_link_status="확정",
        with_order_plan=True,
    )
    _grade(db_session, both_notice, "우선 검토")

    refresh_fetch_eligibility(
        db_session, notice_ids=[sw_notice.id, tracked_notice.id, both_notice.id]
    )

    reasons = {
        row.attachment_id: row.eligibility_reason
        for row in db_session.scalars(select(AttachmentFetch))
    }
    assert reasons[sw_attachment.id] == "sw_business_object"
    assert reasons[tracked_attachment.id] == "tracked_order_plan"
    assert reasons[both_attachment.id] == "both"


def test_a_human_correction_up_to_priority_creates_the_fetch_row(db_session: Session):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    _grade(db_session, notice, "관찰 대상")

    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0

    _corrected(db_session, notice, "우선 검토")

    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 1
    row = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    )
    assert row.eligibility_reason == "priority_grade"


def test_a_correction_down_from_priority_leaves_the_existing_row_untouched(
    db_session: Session,
):
    """등급이 내려가도 이미 만들어진 취득 행은 취소하지 않는다 (명세 §6.2)."""

    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    _grade(db_session, notice, "우선 검토")
    refresh_fetch_eligibility(db_session, notice_ids=[notice.id])
    row = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachment.id)
    )
    before = (row.id, row.status, row.eligibility_reason)

    _corrected(db_session, notice, "제외")
    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0

    db_session.refresh(row)
    assert (row.id, row.status, row.eligibility_reason) == before


def test_grade_eligibility_is_not_extended_to_bid_notices(db_session: Session):
    notice, attachment, _ = add_attachment(db_session, sw_status="N")
    notice.source_type = "bid_notice"
    db_session.flush()
    _grade(db_session, notice, "우선 검토")

    assert refresh_fetch_eligibility(db_session, notice_ids=[notice.id]) == 0
    assert db_session.scalar(select(func.count(AttachmentFetch.id))) == 0


def test_unsupported_extension_marks_the_attachment_as_excluded_not_failed(
    db_session: Session, tmp_path: Path
):
    """형식 밖 첨부는 `차단`이지만 묶음 확정을 막지 않는 `extract_status`를 남긴다 (§6.2)."""

    _, attachment, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None

    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(b"zip", G2B_URL, "붙임.zip"))},
        root=tmp_path,
    )

    assert result is not None and result.status == "차단"
    assert result.last_error_code == "unsupported_extension"
    db_session.refresh(attachment)
    assert attachment.extract_status == UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS


def test_other_terminal_codes_do_not_mark_the_attachment_as_excluded(
    db_session: Session, tmp_path: Path
):
    _, attachment, _ = queue_one(db_session, sw_status="Y")
    claim = claim_next(db_session, worker_id="worker-a", lease_seconds=120)
    assert claim is not None
    eicar = (Path(__file__).parents[1] / "fixtures/document_bundles/eicar.pdf").read_bytes()

    result = fetch_claimed(
        db_session,
        claim,
        connectors={"g2b": StubConnector(assets.ProviderResponse(eicar, G2B_URL, "infected.pdf"))},
        processor=DocumentProcessor(clamav_checker=lambda _content: True),
        root=tmp_path,
    )

    assert result is not None and result.status == "차단"
    db_session.refresh(attachment)
    assert attachment.extract_status != UNSUPPORTED_ATTACHMENT_EXTRACT_STATUS


# --- 자동 문서 준비 (명세 §6.2) ----------------------------------------------


class MapConnector:
    """URL마다 다른 응답을 주는 stub. 첨부가 둘 이상인 공고를 세울 때 쓴다."""

    source_system = SOURCE_SYSTEM

    def __init__(self, responses: dict[str, assets.ProviderResponse]):
        self.responses = responses

    def fetch(self, url: str) -> assets.ProviderResponse:
        response = self.responses.get(url)
        assert response is not None, url
        return response


def _variant_pdf() -> bytes:
    """같은 구조·같은 크기, 다른 bytes인 PDF. 재수집 규칙 검사에 쓴다."""

    return SAFE_PDF.read_bytes().replace(b"T3 fixture", b"T6 fixture")


def _priority_notice(session: Session, names: list[str]) -> tuple[Notice, list[Attachment]]:
    """`우선 검토` 판정만으로 자격을 얻는 사전규격과 그 첨부들."""

    notice = Notice(
        notice_key=f"pre:auto-{session.query(Notice).count() + 1}",
        source_type="pre_spec",
        title="자동 준비 사전규격",
        qualification_flags_json={"sw_business_status": "N"},
        raw_source={},
    )
    session.add(notice)
    session.flush()
    session.add(Judgment(notice_id=notice.id, grade="우선 검토", readiness="확인 완료"))
    attachments: list[Attachment] = []
    for seq, name in enumerate(names, start=1):
        url = G2B_URL.replace("fileSeq=1", f"fileSeq={seq}")
        attachment = Attachment(
            notice_id=notice.id,
            name=name,
            origin="g2b",
            source_url=url,
            source_system=SOURCE_SYSTEM,
            source_attachment_key=parse_attachment_key(url),
        )
        session.add(attachment)
        attachments.append(attachment)
    session.flush()
    refresh_fetch_eligibility(session, notice_ids=[notice.id])
    session.commit()
    return notice, attachments


def _drain_queue(session: Session, connector: MapConnector, tmp_path: Path | None) -> None:
    """큐가 빌 때까지 취득한다. `tmp_path`가 `None`이면 설정된 기본 보관소를 쓴다."""

    while True:
        claim = claim_next(session, worker_id="worker-auto", lease_seconds=120)
        if claim is None:
            return
        fetch_claimed(
            session,
            claim,
            connectors={"g2b": connector},
            processor=DocumentProcessor(clamav_checker=lambda _content: True),
            root=tmp_path,
        )


def _responses(session: Session, attachments: list[Attachment], payloads: list[bytes]):
    return MapConnector(
        {
            attachment.source_url: assets.ProviderResponse(
                payload, attachment.source_url, attachment.name
            )
            for attachment, payload in zip(attachments, payloads, strict=True)
        }
    )


def _bundles(session: Session, notice: Notice) -> list[DocumentBundle]:
    return list(
        session.scalars(
            select(DocumentBundle)
            .where(DocumentBundle.notice_id == notice.id)
            .order_by(DocumentBundle.revision.asc())
        )
    )


def _audit_actions(session: Session, bundle_id) -> dict[str, AuditEvent]:
    return {
        row.action: row
        for row in session.scalars(
            select(AuditEvent).where(AuditEvent.aggregate_id == str(bundle_id))
        )
    }


def test_terminal_fetch_creates_and_confirms_the_bundle_as_a_system_actor(
    db_session: Session, tmp_path: Path
):
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])

    _drain_queue(db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), tmp_path)

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "ready")]
    assert bundles[0].created_by_name == "auto-preparation"
    assert bundles[0].confirmed_by_name == "auto-preparation"
    actions = _audit_actions(db_session, bundles[0].id)
    assert set(actions) == {
        "document_bundle.create",
        "document_bundle.confirm",
        "document_bundle.auto_confirm",
    }
    for action in actions.values():
        assert action.actor_kind == "system"
        assert action.claimed_name == "auto-preparation"
    assert actions["document_bundle.create"].safe_metadata["trigger"] == "priority_grade"
    assert actions["document_bundle.auto_confirm"].safe_metadata["notice_id"] == notice.id


def test_the_automatic_confirmation_refreshes_bundle_items_in_place(
    db_session: Session, tmp_path: Path
):
    """자동 준비의 확정은 draft item을 지우지 않는다.

    묶음 생성 시점과 확정 시점의 문서 집합·순서가 같으므로 `_seed_bundle_items`가
    제자리 갱신을 고른다. 취득 worker는 `document_bundle_item` DELETE 권한이 없고
    (`scripts/runtime-privileges.sql`), 이 경로가 그 권한 없이 끝나야 한다.
    """

    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.split()))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        _drain_queue(
            db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), tmp_path
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "ready")]
    verbs = [
        statement.split()[0].upper()
        for statement in statements
        if "document_bundle_item" in statement
    ]
    # 항목 행은 묶음 생성 때 한 번 들어가고 확정은 그 행을 지우지 않는다 —
    # 확정 뒤에 남은 행이 생성 때 넣은 바로 그 행이라는 뜻이다.
    assert verbs.count("DELETE") == 0
    assert verbs.count("INSERT") == 1
    actions = _audit_actions(db_session, bundles[0].id)
    assert actions["document_bundle.confirm"].safe_metadata["item_refresh"] == "in_place"

    document = db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.notice_id == notice.id)
    )
    items = db_session.scalars(
        select(DocumentBundleItem).where(DocumentBundleItem.bundle_id == bundles[0].id)
    ).all()
    assert [(item.document_version_id, item.ordinal) for item in items] == [(document.id, 0)]
    assert items[0].content_object_id == document.content_object_id
    assert items[0].safety_status_at_confirmation == "safe"
    assert items[0].structure_id_at_confirmation is not None


def test_an_unsupported_attachment_does_not_stop_the_automatic_confirmation(
    db_session: Session, tmp_path: Path
):
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf", "붙임자료.zip"])

    _drain_queue(
        db_session,
        _responses(db_session, attachments, [SAFE_PDF.read_bytes(), b"PK\x03\x04zip"]),
        tmp_path,
    )

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "ready")]
    codes = {issue["code"]: issue for issue in bundles[0].issues_snapshot}
    assert codes[UNSUPPORTED_ATTACHMENT_ISSUE_CODE]["blocking"] is False
    assert codes[UNSUPPORTED_ATTACHMENT_ISSUE_CODE]["severity"] == "보통"
    assert not [issue for issue in bundles[0].issues_snapshot if issue["blocking"]]


def test_a_scan_failure_leaves_the_automatic_bundle_in_draft(
    db_session: Session, tmp_path: Path
):
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf", "감염.pdf"])
    eicar = (Path(__file__).parents[1] / "fixtures/document_bundles/eicar.pdf").read_bytes()

    _drain_queue(
        db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes(), eicar]), tmp_path
    )

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "draft")]
    assert [issue["code"] for issue in bundles[0].issues_snapshot if issue["blocking"]]
    fields = auto_preparation_fields(db_session, [notice.id])[notice.id]
    assert fields["auto_preparation_status"] == "blocked"
    assert fields["auto_preparation_reason"] == "bundle_has_blocking_issues"


def test_the_same_document_set_never_creates_a_second_bundle(
    db_session: Session, tmp_path: Path
):
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])
    _drain_queue(db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), tmp_path)

    outcomes = maybe_auto_prepare(db_session, [notice.id], root=tmp_path)

    assert [outcome.reason for outcome in outcomes] == ["bundle_unchanged"]
    assert [(bundle.revision, bundle.status) for bundle in _bundles(db_session, notice)] == [
        (1, "ready")
    ]


def test_new_attachment_bytes_create_a_new_confirmed_revision(
    db_session: Session, tmp_path: Path
):
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])
    _drain_queue(db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), tmp_path)
    first = _bundles(db_session, notice)[0]

    # 같은 첨부가 다른 bytes로 다시 취득된다.
    row = db_session.scalar(
        select(AttachmentFetch).where(AttachmentFetch.attachment_id == attachments[0].id)
    )
    row.status = "대기"
    row.completed_at = None
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    _drain_queue(db_session, _responses(db_session, attachments, [_variant_pdf()]), tmp_path)

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [
        (1, "superseded"),
        (2, "ready"),
    ]
    # 이전 묶음의 item snapshot은 그대로 남는다.
    assert db_session.scalar(
        select(func.count())
        .select_from(DocumentBundleItem)
        .where(DocumentBundleItem.bundle_id == first.id)
    ) == 1


def test_the_grade_hook_prepares_inside_the_callers_transaction(
    db_session: Session, tmp_path: Path
):
    """등급 변경 hook의 묶음 생성·확정은 호출자의 transaction 안에서 일어난다.

    `create_bundle`·`confirm`은 스스로 commit하므로, 그 commit이 리뷰 저장이나
    회차 적재를 앞당겨 끝내면 안 된다. 호출자가 rollback하면 자동 준비 결과도
    함께 사라져야 한다 — 그것이 "같은 transaction"의 증거다.
    """

    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])
    # 판정 등급을 내려 자동 준비가 아직 열리지 않은 상태로 취득만 끝낸다.
    judgment = db_session.scalar(select(Judgment).where(Judgment.notice_id == notice.id))
    judgment.grade = "관찰 대상"
    db_session.commit()
    # hook은 확장점 서명상 보관소 경로를 받지 않고 **설정된 기본 보관소**를 쓴다.
    # 그래서 이 검사만 취득도 같은 기본 보관소에서 한다.
    _drain_queue(db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), None)
    assert _bundles(db_session, notice) == []

    # 사람이 등급을 `우선 검토`로 정정한 뒤, 아직 커밋되지 않은 같은 transaction에서
    # hook이 불린다.
    db_session.add(
        Review(notice_id=notice.id, corrected_grade="우선 검토", reviewer_snapshot="검토자")
    )
    db_session.flush()
    PreSpecAttachmentEligibilityHook().effective_grade_changed(db_session, [notice.id])

    assert [(bundle.revision, bundle.status) for bundle in _bundles(db_session, notice)] == [
        (1, "ready")
    ]
    assert db_session.in_transaction()

    db_session.rollback()

    assert _bundles(db_session, notice) == []
    assert db_session.scalar(select(Review).where(Review.notice_id == notice.id)) is None


def test_the_grade_hook_records_the_triggering_run_and_review(
    db_session: Session, tmp_path: Path
):
    """등급 변경으로 촉발된 자동 준비는 **어느 회차·어느 리뷰가** 열었는지 남긴다.

    명세 §6.2는 자동 생성·확정 감사 이벤트에 `trigger=priority_grade`와 함께
    촉발 회차·리뷰 식별자를 요구한다. 등급 변경 hook은 확장점 서명상 그 식별자를
    받지 않으므로, effective grade가 자기 출처(정정 리뷰)를 실어 나른다.
    """

    run = Run(id="20260901-20260907", timezone="Asia/Seoul")
    db_session.add(run)
    db_session.flush()
    notice, attachments = _priority_notice(db_session, ["제안요청서.pdf"])
    judgment = db_session.scalar(select(Judgment).where(Judgment.notice_id == notice.id))
    judgment.grade = "관찰 대상"
    db_session.commit()
    # hook은 설정된 기본 보관소를 쓰므로 취득도 같은 보관소에서 한다.
    _drain_queue(db_session, _responses(db_session, attachments, [SAFE_PDF.read_bytes()]), None)
    assert _bundles(db_session, notice) == []

    review = Review(
        notice_id=notice.id,
        run_id=run.id,
        corrected_grade="우선 검토",
        reviewer_snapshot="검토자",
    )
    db_session.add(review)
    db_session.flush()
    PreSpecAttachmentEligibilityHook().effective_grade_changed(db_session, [notice.id])

    bundles = _bundles(db_session, notice)
    assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "ready")]
    actions = _audit_actions(db_session, bundles[0].id)
    assert set(actions) == {
        "document_bundle.create",
        "document_bundle.confirm",
        "document_bundle.auto_confirm",
    }
    for action in actions.values():
        assert action.safe_metadata["trigger"] == "priority_grade"
        assert action.safe_metadata["trigger_run_id"] == run.id
        assert action.safe_metadata["trigger_review_id"] == review.id
    db_session.rollback()


def _statements(session: Session, action) -> list[str]:
    """`action`이 도는 동안 실제로 나간 SQL 문. savepoint도 여기 잡힌다."""

    engine = session.get_bind()
    captured: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        captured.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return captured


def _non_priority_pre_specs(session: Session, count: int) -> list[int]:
    """`우선 검토`가 아닌 사전규격 여러 건. 회차 적재 hook이 보는 흔한 경우다."""

    ids: list[int] = []
    for _index in range(count):
        notice = Notice(
            notice_key=f"pre:batch-{session.query(Notice).count() + 1}",
            source_type="pre_spec",
            title="대량 사전규격",
            qualification_flags_json={"sw_business_status": "N"},
            raw_source={},
        )
        session.add(notice)
        session.flush()
        session.add(Judgment(notice_id=notice.id, grade="관찰 대상", readiness="확인 완료"))
        ids.append(notice.id)
    session.commit()
    return ids


def test_auto_preparation_query_count_does_not_grow_with_the_batch(db_session: Session):
    """회차 적재 hook은 사전규격 전부를 한 번에 넘긴다 (3일 약 1,200건).

    등급을 공고당 묻거나 공고당 savepoint를 열면 회차 적재 transaction 하나에
    수천 번의 왕복과 수천 개의 하위 transaction이 쌓인다. 할 일이 없는 공고의
    비용은 건수와 무관한 상수여야 한다.
    """

    few = _non_priority_pre_specs(db_session, 3)
    many = _non_priority_pre_specs(db_session, 30)

    small = _statements(db_session, lambda: maybe_auto_prepare(db_session, few))
    db_session.rollback()
    large = _statements(db_session, lambda: maybe_auto_prepare(db_session, many))
    db_session.rollback()

    assert len(small) == len(large)
    # 사전규격 선별 한 번 + 등급 seam(정정·판정·개정) 세 번이 전부다.
    assert len(large) <= 5
    # 할 일이 없으면 작업 session도 savepoint도 만들지 않는다.
    assert not [line for line in large if "SAVEPOINT" in line.upper()]
    assert [outcome.reason for outcome in maybe_auto_prepare(db_session, many)] == [
        "grade_not_priority"
    ] * len(many)


def test_worker_once_session_keeps_the_automatic_bundle_after_it_closes(tmp_path: Path):
    """``main`` runs each poll in ``with SessionLocal() as session`` and closes it.

    The automatic preparation after a terminal fetch must be durable when that
    session closes -- not left in the read transaction its eligibility queries
    opened (the bundle work runs on a savepoint of it).
    """

    engine = make_engine()
    init_db(engine)
    try:
        with Session(engine) as session:
            notice, attachments = _priority_notice(session, ["제안요청서.pdf"])
            notice_id = notice.id
            connector = _responses(session, attachments, [SAFE_PDF.read_bytes()])
        with Session(engine) as session:  # the worker's per-poll session
            assert run_once(
                session, "worker-once", connectors={"g2b": connector},
                processor=DocumentProcessor(clamav_checker=lambda _content: True), root=tmp_path,
                notice_id=notice_id,
            ) is True
        with Session(engine) as session:
            bundles = list(session.scalars(select(DocumentBundle).where(DocumentBundle.notice_id == notice_id)))
            assert [(bundle.revision, bundle.status) for bundle in bundles] == [(1, "ready")]
            assert session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "document_bundle.auto_confirm")) == 1
    finally:
        engine.dispose()
