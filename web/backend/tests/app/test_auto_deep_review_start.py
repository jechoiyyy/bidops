"""SW사업대상=Y 자동 심층 검토 시작의 통합 검사 (명세 §6.4·§8).

여기 있는 검사는 **판정(선별)과 심층 검토(deep_review)가 합쳐지는 자리**를 본다.
등급은 선별 소유라 `tests/deep_review/`에서는 세울 수 없고, 자동 시작이 사람
경로와 같은 불변 입력·감사 모양을 남기는지는 실제 `DeepReviewService`로만
확인할 수 있기 때문이다.

모델도 나라장터도 부르지 않는다. 문서 structure는 합성 payload이고 분석 실행은
시작하지 않는다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import init_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    AnalysisPolicyVersion,
    AttachmentFetch,
    ContentObject,
    DeepReview,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    PreSpecOverviewReview,
    PreSpecOverviewSnapshot,
    ProfileVersion,
)
from app.deep_review.services.auto_preparation import (
    AUTO_ACTOR_KIND,
    AUTO_ACTOR_NAME,
    AUTO_DEEP_REVIEW_ACTION,
    REASON_BUNDLE_UNCHANGED,
    maybe_auto_prepare,
    maybe_auto_start_deep_review,
)
from app.deep_review.services.deep_reviews import DeepReviewService, quality_status_for_review
from app.deep_review.services.input_versions import load_canonical_policy
from app.core.model_binding import MODEL_NAME
from app.lifecycle.models import Attachment, Notice, Opportunity, Run
from app.screening.models import Judgment

WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def _fixture_structure(_session, structure):
    return {
        "schema": "bidops.document-structure.v1",
        "structure_id": str(structure.id),
        "document_version_id": str(structure.document_version_id),
        "source_sha256": structure.source_sha256,
        "media_type": structure.media_type,
        "extractor": {
            "name": structure.extractor_name,
            "version": structure.extractor_version,
            "upstream_commit": structure.upstream_commit,
        },
        "pages": [{"number": 1, "width": 612, "height": 792, "image_content_object_id": None}],
        "blocks": [],
        "warnings": [],
        "created_at": "2026-09-01T00:00:00+09:00",
    }


@pytest.fixture()
def engine():
    bind = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(bind)
    # PostgreSQL 전용 부분 unique index는 SQLite에서 전역 unique가 된다.
    # 격리 test dialect에서 운영과 같은 의미로 다시 만든다.
    with bind.begin() as connection:
        for index_name in ("uq_deep_review_attempt_active", "uq_work_job_active"):
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_deep_review_attempt_active ON deep_review_attempt "
                "(deep_review_id) WHERE status IN ('queued','running')"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_work_job_active ON work_job "
                "(job_type, aggregate_type, aggregate_id) WHERE status IN ('queued','running')"
            )
        )
    return bind


def _seed(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sw_business_status: str = "Y",
    grade: str = "우선 검토",
    overview_result: str = "추진 검토",
    with_bundle: bool = True,
) -> SimpleNamespace:
    """§6.4가 성립하는 사전규격 하나를 세우고 active 설정을 가리킨다."""

    run = Run(id=f"auto-{uuid4()}")
    notice = Notice(
        run=run,
        notice_key=f"auto-{uuid4()}",
        source_type="pre_spec",
        title="자동 심층 시작",
        qualification_flags_json={"sw_business_status": sw_business_status},
    )
    session.add_all([run, notice])
    session.add(Judgment(notice=notice, grade=grade, readiness="확인 완료"))
    session.flush()
    attachment = Attachment(notice_id=notice.id, name="제안요청서.pdf", origin="g2b")
    session.add(attachment)
    session.flush()
    payload = b"synthetic prespec bytes"
    content_hash = hashlib.sha256(payload).hexdigest()
    structure_hash = hashlib.sha256(b"synthetic structure").hexdigest()
    content = ContentObject(
        sha256=content_hash,
        size_bytes=len(payload),
        detected_mime="application/pdf",
        retention_class="document-source",
    )
    session.add(content)
    session.flush()
    document = DocumentVersion(
        notice_id=notice.id,
        attachment_id=attachment.id,
        content_object_id=content.id,
        version=1,
        source_kind="manual",
        original_filename="제안요청서.pdf",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add(document)
    session.flush()
    session.add(
        AttachmentFetch(
            attachment_id=attachment.id,
            status="완료",
            eligibility_reason="sw_business_object",
            next_attempt_at=WHEN,
            completed_at=WHEN,
            document_version_id=document.id,
        )
    )
    structure = DocumentStructure(
        document_version_id=document.id,
        source_sha256=content_hash,
        media_type="application/pdf",
        extractor_name="test",
        extractor_version="1",
        payload_content_object_id=content.id,
        payload_sha256=structure_hash,
        page_count=1,
        block_count=0,
        validation_status="ready",
    )
    session.add(structure)
    session.flush()

    bundle = None
    if with_bundle:
        bundle = _confirmed_bundle(session, document, structure, revision=1)

    review = PreSpecOverviewReview(notice_id=notice.id, status="awaiting_model")
    session.add(review)
    session.flush()
    snapshot = PreSpecOverviewSnapshot(
        review_id=review.id,
        notice_id=notice.id,
        document_version_id=document.id,
        structure_id=structure.id,
        source_sha256=content_hash,
        payload_sha256=structure_hash,
        cut_status="ready",
        strategy="topic_heading",
        start_locator={"block_key": "start", "page": 1, "ordinal": 0},
        end_locator={"block_key": "end", "page": 1, "ordinal": 2},
        input_block_keys=["start"],
    )
    session.add(snapshot)
    session.flush()
    review.current_snapshot_id = snapshot.id
    review.status = "completed"
    review.result = overview_result
    review.completed_at = WHEN

    profile_hash = hashlib.sha256(f"profile-{uuid4()}".encode()).hexdigest()
    profile = ProfileVersion(
        id=uuid4(),
        version=int(session.query(ProfileVersion).count()) + 1,
        label="profile",
        profile_payload={
            "schema": "bidops.company-profile.v1",
            "source_file": "docs/reference/company-profile.md",
            "source_sha256": profile_hash,
            "facts": [
                {"fact_key": f"fixture.fact[{index}]", "status": "unknown", "quote": "fixture"}
                for index in range(39)
            ],
        },
        profile_sha256=profile_hash,
        source_kind="fixture",
    )
    policy_payload, _canonical, policy_hash = load_canonical_policy()
    policy = AnalysisPolicyVersion(
        id=uuid4(),
        version=int(session.query(AnalysisPolicyVersion).count()) + 1,
        label="policy",
        model_endpoint_ref="vllm-openai-compatible",
        model_name=MODEL_NAME,
        prompts=policy_payload["stages"],
        validation_rules={
            **policy_payload["validation"],
            "generation": policy_payload["generation"],
            "sample_hash": "b" * 64,
            "required_item_recall": 0.8,
            "human_agreement": 0.7,
            "unsupported_false_positive_rate": 0.1,
        },
        policy_sha256=policy_hash,
    )
    session.add_all([profile, policy])
    session.commit()
    monkeypatch.setenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", str(profile.id))
    monkeypatch.setenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", str(policy.id))
    return SimpleNamespace(
        notice_id=notice.id, bundle=bundle, document=document, structure=structure
    )


def _confirmed_bundle(
    session: Session,
    document: DocumentVersion,
    structure: DocumentStructure,
    *,
    revision: int,
) -> DocumentBundle:
    """자동 확정된 `ready` 묶음 하나. 사람 경로와 같은 item snapshot을 갖는다."""

    content = session.get(ContentObject, document.content_object_id)
    bundle = DocumentBundle(
        notice_id=document.notice_id,
        revision=revision,
        version=1,
        status="ready",
        issues_snapshot=[],
        created_by_name=AUTO_ACTOR_NAME,
        confirmed_by_name=AUTO_ACTOR_NAME,
        confirmed_at=WHEN,
    )
    session.add(bundle)
    session.flush()
    session.add(
        DocumentBundleItem(
            bundle_id=bundle.id,
            document_version_id=document.id,
            ordinal=0,
            document_version_version=document.version,
            content_object_id=content.id,
            content_sha256=content.sha256,
            detected_mime="application/pdf",
            size_bytes=content.size_bytes,
            original_filename=document.original_filename,
            source_kind="manual",
            role_at_confirmation="제안요청서",
            is_current_at_confirmation=True,
            safety_status_at_confirmation="safe",
            structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        )
    )
    session.flush()
    return bundle


def _service() -> DeepReviewService:
    return DeepReviewService(structure_loader=_fixture_structure)


def test_the_automatic_start_leaves_the_same_audit_shape_as_a_human_click(
    engine, monkeypatch: pytest.MonkeyPatch
):
    """§8: `quality_status`는 두 생성 action 모두에서 계산돼야 한다."""

    with Session(engine) as session:
        seeded = _seed(session, monkeypatch)

        outcome = maybe_auto_start_deep_review(session, seeded.notice_id, service=_service())

        assert outcome.created is True
        review = session.scalar(select(DeepReview))
        assert review is not None
        assert review.bundle_id == seeded.bundle.id
        assert review.requested_by_name == AUTO_ACTOR_NAME
        assert review.effective_grade_at_start == "우선 검토"

        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.aggregate_type == "deep_review")
        )
        assert audit is not None
        assert audit.action == AUTO_DEEP_REVIEW_ACTION
        assert audit.actor_kind == AUTO_ACTOR_KIND
        assert audit.claimed_name == AUTO_ACTOR_NAME
        # 사람 경로와 같은 모양이라 품질 표식이 계산된다.
        assert quality_status_for_review(session, review.id) == "measured"
        assert audit.safe_metadata["effective_grade"] == "우선 검토"
        assert audit.safe_metadata["grade_source"] == "screening_judgment"


def test_the_same_immutable_inputs_never_create_a_second_deep_review(
    engine, monkeypatch: pytest.MonkeyPatch
):
    with Session(engine) as session:
        seeded = _seed(session, monkeypatch)

        first = maybe_auto_start_deep_review(session, seeded.notice_id, service=_service())
        second = maybe_auto_start_deep_review(session, seeded.notice_id, service=_service())

        assert first.created is True
        assert second.created is False
        assert len(session.scalars(select(DeepReview)).all()) == 1


def test_a_non_priority_grade_fails_closed_without_creating_anything(
    engine, monkeypatch: pytest.MonkeyPatch
):
    """등급 검사는 생성 경로가 갖는다. 자동 시작이 그것을 우회하지 않는다."""

    with Session(engine) as session:
        seeded = _seed(session, monkeypatch, grade="관찰 대상")

        outcome = maybe_auto_start_deep_review(session, seeded.notice_id, service=_service())

        assert (outcome.created, outcome.reason) == (False, "effective_grade_ineligible")
        assert session.scalar(select(DeepReview)) is None


def test_missing_active_versions_fail_closed_with_a_safe_reason(
    engine, monkeypatch: pytest.MonkeyPatch
):
    with Session(engine) as session:
        seeded = _seed(session, monkeypatch)
        monkeypatch.delenv("BIDOPS_ACTIVE_PROFILE_VERSION_ID", raising=False)
        monkeypatch.delenv("BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID", raising=False)

        outcome = maybe_auto_start_deep_review(session, seeded.notice_id, service=_service())

        assert (outcome.created, outcome.reason) == (False, "service_unavailable")
        assert session.scalar(select(DeepReview)) is None
        assert session.scalar(select(AuditEvent)) is None


def test_the_run_ingest_trigger_retries_the_start_on_an_unchanged_bundle(
    engine, monkeypatch: pytest.MonkeyPatch
):
    """문서 집합이 그대로여도 다음 촉발에서 §6.4를 다시 판단한다."""

    with Session(engine) as session:
        seeded = _seed(session, monkeypatch)

        outcomes = maybe_auto_prepare(
            session, [seeded.notice_id], deep_review_service=_service()
        )

        assert [outcome.reason for outcome in outcomes] == [REASON_BUNDLE_UNCHANGED]
        review = session.scalar(select(DeepReview))
        assert review is not None and review.bundle_id == seeded.bundle.id
        # 자동 준비는 새 묶음을 만들지 않았다.
        assert len(session.scalars(select(DocumentBundle)).all()) == 1


def test_the_automatic_start_does_not_change_the_tracking_status(
    engine, monkeypatch: pytest.MonkeyPatch
):
    with Session(engine) as session:
        seeded = _seed(session, monkeypatch)
        opportunity = Opportunity(first_registered_stage="pre_spec")
        session.add(opportunity)
        session.commit()

        assert maybe_auto_start_deep_review(session, seeded.notice_id, service=_service()).created

        session.refresh(opportunity)
        assert opportunity.tracking_status == "미선택"
        assert opportunity.tracking_selected_by is None
        assert opportunity.tracking_selected_at is None


class _FakeBundleService:
    """`DocumentBundleService`의 자동 준비 계약만 흉내 내는 fake.

    실제 확정 fence(최신 document version·clean scan·불변 structure snapshot)는
    §6.2의 검사가 이미 본다. 여기서 보려는 것은 **확정 직후에 §6.4가 걸리는가**
    하나뿐이므로, 이 fake는 사람 경로와 같은 모양의 `ready` 묶음만 만든다.
    """

    def __init__(self, document: DocumentVersion, structure: DocumentStructure) -> None:
        self.document = document
        self.structure = structure
        self.bundle_id = None

    def create_bundle(self, session: Session, notice_id: int, actor: str, **_kwargs: Any):
        bundle = _confirmed_bundle(session, self.document, self.structure, revision=1)
        bundle.status = "draft"
        bundle.confirmed_by_name = None
        bundle.confirmed_at = None
        session.commit()
        self.bundle_id = bundle.id
        return SimpleNamespace(id=bundle.id, version=bundle.version, revision=bundle.revision)

    def confirm(self, session: Session, bundle_id, request, actor: str, **_kwargs: Any):
        bundle = session.get(DocumentBundle, bundle_id)
        bundle.status = "ready"
        bundle.confirmed_by_name = actor
        bundle.confirmed_at = WHEN
        session.commit()
        return SimpleNamespace(
            id=bundle.id, version=bundle.version, revision=bundle.revision, documents=[self.document.id]
        )


def test_a_freshly_confirmed_bundle_starts_the_deep_review_in_the_same_pass(
    engine, monkeypatch: pytest.MonkeyPatch
):
    """묶음 확정 직후에 개요가 이미 완료돼 있으면 같은 촉발에서 시작한다."""

    with Session(engine) as session:
        seeded = _seed(session, monkeypatch, with_bundle=False)
        bundles = _FakeBundleService(seeded.document, seeded.structure)

        outcomes = maybe_auto_prepare(
            session,
            [seeded.notice_id],
            service=bundles,
            deep_review_service=_service(),
        )

        assert [outcome.confirmed for outcome in outcomes] == [True]
        review = session.scalar(select(DeepReview))
        assert review is not None
        assert review.bundle_id == bundles.bundle_id
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.aggregate_type == "deep_review")
        )
        assert audit is not None and audit.action == AUTO_DEEP_REVIEW_ACTION
