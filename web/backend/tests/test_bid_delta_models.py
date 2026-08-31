"""SQLite isolation tests for the R-08 bid delta database layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    BidDeltaAttempt,
    BidDeltaComparison,
    BidDeltaEvidence,
    BidDeltaItem,
    BidFinalDecision,
    ContentObject,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    Notice,
    Opportunity,
    OpportunityLink,
)


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _scope(
    session: Session,
    label: str,
    *,
    sequence: int = 1,
    calculation_status: str = "completed",
):
    hashes = {
        name: hashlib.sha256(f"{label}:{name}".encode()).hexdigest()
        for name in ("baseline_source", "baseline_payload", "comparison_source", "comparison_payload")
    }
    baseline_notice = Notice(
        notice_key=f"bid-delta:{label}:baseline:{uuid4()}", source_type="pre_spec"
    )
    comparison_notice = Notice(
        notice_key=f"bid-delta:{label}:comparison:{uuid4()}", source_type="bid_notice"
    )
    opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add_all([baseline_notice, comparison_notice, opportunity])
    session.flush()

    baseline_link = OpportunityLink(
        opportunity_id=opportunity.id,
        notice_id=baseline_notice.id,
        stage="notice",
        link_type="official",
        status="확정",
        evidence_external_no=f"baseline-{label}",
    )
    comparison_link = OpportunityLink(
        opportunity_id=opportunity.id,
        notice_id=comparison_notice.id,
        stage="notice",
        link_type="official",
        status="확정",
        evidence_external_no=f"comparison-{label}",
    )
    session.add_all([baseline_link, comparison_link])
    session.flush()

    baseline_content = ContentObject(
        sha256=hashes["baseline_source"], size_bytes=10, detected_mime="application/pdf", retention_class="document-source"
    )
    comparison_content = ContentObject(
        sha256=hashes["comparison_source"], size_bytes=11, detected_mime="application/pdf", retention_class="document-source"
    )
    session.add_all([baseline_content, comparison_content])
    session.flush()

    baseline_document = DocumentVersion(
        notice_id=baseline_notice.id,
        content_object_id=baseline_content.id,
        version=1,
        source_kind="manual",
        original_filename="baseline.pdf",
        role="제안요청서",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    comparison_document = DocumentVersion(
        notice_id=comparison_notice.id,
        content_object_id=comparison_content.id,
        version=1,
        source_kind="manual",
        original_filename="comparison.pdf",
        role="공고",
        is_current=True,
        safety_status="safe",
        needs_human_review=False,
    )
    session.add_all([baseline_document, comparison_document])
    session.flush()

    baseline_structure = DocumentStructure(
        document_version_id=baseline_document.id,
        source_sha256=hashes["baseline_source"],
        media_type="application/pdf",
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=baseline_content.id,
        payload_sha256=hashes["baseline_payload"],
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    comparison_structure = DocumentStructure(
        document_version_id=comparison_document.id,
        source_sha256=hashes["comparison_source"],
        media_type="application/pdf",
        extractor_name="fixture",
        extractor_version="1",
        payload_content_object_id=comparison_content.id,
        payload_sha256=hashes["comparison_payload"],
        page_count=1,
        block_count=1,
        validation_status="ready",
    )
    session.add_all([baseline_structure, comparison_structure])
    session.flush()

    baseline_bundle = DocumentBundle(
        notice_id=baseline_notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
    )
    comparison_bundle = DocumentBundle(
        notice_id=comparison_notice.id,
        revision=1,
        version=1,
        status="ready",
        issues_snapshot=[],
    )
    session.add_all([baseline_bundle, comparison_bundle])
    session.flush()
    session.add_all(
        [
            DocumentBundleItem(
                bundle_id=baseline_bundle.id,
                document_version_id=baseline_document.id,
                ordinal=1,
                document_version_version=1,
                content_object_id=baseline_content.id,
                content_sha256=hashes["baseline_source"],
                detected_mime="application/pdf",
                size_bytes=10,
                original_filename="baseline.pdf",
                source_kind="manual",
                role_at_confirmation="제안요청서",
                is_current_at_confirmation=True,
                safety_status_at_confirmation="safe",
                structure_id_at_confirmation=baseline_structure.id,
                structure_payload_sha256=hashes["baseline_payload"],
            ),
            DocumentBundleItem(
                bundle_id=comparison_bundle.id,
                document_version_id=comparison_document.id,
                ordinal=1,
                document_version_version=1,
                content_object_id=comparison_content.id,
                content_sha256=hashes["comparison_source"],
                detected_mime="application/pdf",
                size_bytes=11,
                original_filename="comparison.pdf",
                source_kind="manual",
                role_at_confirmation="공고",
                is_current_at_confirmation=True,
                safety_status_at_confirmation="safe",
                structure_id_at_confirmation=comparison_structure.id,
                structure_payload_sha256=hashes["comparison_payload"],
            ),
        ]
    )
    session.flush()

    comparison = BidDeltaComparison(
        opportunity_id=opportunity.id,
        sequence=sequence,
        category_policy_version=f"bid-delta-policy-{label}",
        baseline_link_id=baseline_link.id,
        baseline_notice_id=baseline_notice.id,
        baseline_bundle_id=baseline_bundle.id,
        baseline_bundle_revision=1,
        baseline_bundle_version=1,
        baseline_document_version_id=baseline_document.id,
        baseline_document_version_version=1,
        baseline_structure_id=baseline_structure.id,
        baseline_source_sha256=hashes["baseline_source"],
        baseline_structure_payload_sha256=hashes["baseline_payload"],
        comparison_link_id=comparison_link.id,
        comparison_notice_id=comparison_notice.id,
        comparison_bundle_id=comparison_bundle.id,
        comparison_bundle_revision=1,
        comparison_bundle_version=1,
        comparison_document_version_id=comparison_document.id,
        comparison_document_version_version=1,
        comparison_structure_id=comparison_structure.id,
        comparison_source_sha256=hashes["comparison_source"],
        comparison_structure_payload_sha256=hashes["comparison_payload"],
        calculation_status=calculation_status,
        result_status="failed" if calculation_status == "failed" else "unchanged",
        materiality="unknown" if calculation_status == "failed" else "non_material",
        result_sha256=None if calculation_status == "failed" else SHA_A,
        last_error_code="calculation_failed" if calculation_status == "failed" else None,
        created_by_name="reviewer",
        created_at=NOW,
        started_at=None if calculation_status == "failed" else NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )
    session.add(comparison)
    session.flush()
    return {
        "opportunity": opportunity,
        "baseline_notice": baseline_notice,
        "comparison_notice": comparison_notice,
        "baseline_link": baseline_link,
        "comparison_link": comparison_link,
        "baseline_bundle": baseline_bundle,
        "comparison_bundle": comparison_bundle,
        "baseline_document": baseline_document,
        "comparison_document": comparison_document,
        "baseline_structure": baseline_structure,
        "comparison_structure": comparison_structure,
        "hashes": hashes,
        "comparison": comparison,
    }


def _attempt(session: Session, comparison: BidDeltaComparison, *, status="completed"):
    attempt = BidDeltaAttempt(
        comparison_id=comparison.id,
        sequence=1,
        status=status,
        runtime_binding_id="internal-binding-v1",
        runtime_binding_digest=SHA_A,
        created_at=NOW,
        started_at=NOW + timedelta(seconds=1) if status == "completed" else None,
        completed_at=NOW + timedelta(seconds=2) if status == "completed" else None,
    )
    if status == "failed":
        attempt.last_error_code = "worker_failed"
        attempt.completed_at = NOW + timedelta(seconds=2)
        attempt.started_at = None
    session.add(attempt)
    session.flush()
    return attempt


def _item(session: Session, scope, attempt: BidDeltaAttempt, *, result="changed", material="material", error=None):
    item = BidDeltaItem(
        comparison_id=scope["comparison"].id,
        attempt_id=attempt.id,
        category="eligibility",
        ordinal=1,
        result_status=result,
        materiality=material,
        before_value="before",
        after_value="after",
        summary="summary",
        error_code=error,
        created_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


def _evidence(session: Session, scope, item: BidDeltaItem, side: str):
    evidence = BidDeltaEvidence(
        item_id=item.id,
        side=side,
        ordinal=1,
        document_version_id=scope[f"{side}_document"].id,
        structure_id=scope[f"{side}_structure"].id,
        source_sha256=scope["hashes"][f"{side}_source"],
        locator_type="page",
        locator={"page": 1},
        quote="verified quote",
        verification_status="verified",
        created_at=NOW,
    )
    session.add(evidence)
    session.flush()
    return evidence


def test_normal_comparison_attempt_item_evidence_and_final_decision_insert():
    engine = _engine()
    with Session(engine) as session:
        scope = _scope(session, "normal")
        attempt = _attempt(session, scope["comparison"])
        item = _item(session, scope, attempt)
        _evidence(session, scope, item, "baseline")
        _evidence(session, scope, item, "comparison")
        decision = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=1,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            decision="go",
            reason="검토 완료",
            claimed_name="홍길동",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(decision)
        session.commit()
        assert decision.id is not None


def test_comparison_checks_reject_same_document_and_invalid_lifecycle():
    engine = _engine()
    with Session(engine) as session:
        scope = _scope(session, "comparison-check")
        values = {
            column.name: getattr(scope["comparison"], column.name)
            for column in BidDeltaComparison.__table__.columns
        }
        values.update(
            id=uuid4(),
            sequence=2,
            comparison_document_version_id=scope["baseline_document"].id,
        )
        session.add(BidDeltaComparison(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        values = {
            column.name: getattr(scope["comparison"], column.name)
            for column in BidDeltaComparison.__table__.columns
        }
        values.update(
            id=uuid4(),
            sequence=3,
            result_status="changed",
            result_sha256=None,
            calculation_status="pending",
            started_at=None,
            completed_at=None,
        )
        session.add(BidDeltaComparison(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        values = {
            column.name: getattr(scope["comparison"], column.name)
            for column in BidDeltaComparison.__table__.columns
        }
        values.update(id=uuid4(), sequence=4, result_sha256=None)
        session.add(BidDeltaComparison(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    ("result", "material", "error"),
    [
        ("unchanged", "material", None),
        ("unknown", "non_material", "unknown_value"),
        ("unknown", "unknown", None),
        ("failed", "unknown", ""),
    ],
)
def test_item_result_materiality_and_error_contract(result, material, error):
    engine = _engine()
    with Session(engine) as session:
        scope = _scope(session, f"item-{result}-{material}-{error}")
        attempt = _attempt(session, scope["comparison"])
        with pytest.raises(IntegrityError):
            _item(session, scope, attempt, result=result, material=material, error=error)
            session.commit()


def test_orm_append_only_guards_and_failed_retry_transition():
    engine = _engine()
    with Session(engine) as session:
        scope = _scope(session, "append-only")
        attempt = _attempt(session, scope["comparison"])
        item = _item(session, scope, attempt)
        evidence = _evidence(session, scope, item, "baseline")
        _evidence(session, scope, item, "comparison")
        decision = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=1,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            decision="go",
            reason="reason",
            claimed_name="actor",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(decision)
        session.commit()

        for row, field, value in (
            (decision, "decision", "no_go"),
            (item, "summary", "changed"),
            (evidence, "quote", "changed"),
        ):
            setattr(row, field, value)
            with pytest.raises(ValueError):
                session.commit()
            session.rollback()
            session.refresh(row)

        session.delete(decision)
        with pytest.raises(ValueError):
            session.commit()
        session.rollback()
        session.refresh(decision)

        attempt.lease_fence = 2
        with pytest.raises(ValueError):
            session.commit()
        session.rollback()
        session.refresh(attempt)
        session.delete(attempt)
        with pytest.raises(ValueError):
            session.commit()
        session.rollback()

        scope["comparison"].baseline_bundle_version = 2
        with pytest.raises(ValueError):
            session.commit()
        session.rollback()
        session.refresh(scope["comparison"])

        failed_scope = _scope(
            session, "retry", sequence=2, calculation_status="failed"
        )
        failed = _attempt(session, failed_scope["comparison"], status="failed")
        session.commit()
        failed_scope["comparison"].calculation_status = "pending"
        failed_scope["comparison"].result_status = None
        failed_scope["comparison"].completed_at = None
        failed_scope["comparison"].last_error_code = None
        session.commit()
        assert failed.status == "failed"


def test_final_decision_enum_idempotency_and_supersession_uniques():
    engine = _engine()
    with Session(engine) as session:
        scope = _scope(session, "decision-uniques")
        first = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=1,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            decision="go",
            reason="reason",
            claimed_name="actor",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(first)
        session.commit()

        duplicate = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=2,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            decision="go",
            reason="different row",
            claimed_name="actor",
            request_id=first.request_id,
            created_at=NOW,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        invalid = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=2,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            decision="hold",
            reason="reason",
            claimed_name="other-actor",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        superseding = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=2,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            supersedes_final_decision_id=first.id,
            decision="no_go",
            reason="new decision",
            claimed_name="other-actor",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(superseding)
        session.commit()

        branch = BidFinalDecision(
            opportunity_id=scope["opportunity"].id,
            sequence=3,
            comparison_id=scope["comparison"].id,
            comparison_version=1,
            result_sha256=SHA_A,
            baseline_document_version_id=scope["baseline_document"].id,
            comparison_document_version_id=scope["comparison_document"].id,
            supersedes_final_decision_id=first.id,
            decision="go",
            reason="branch",
            claimed_name="third-actor",
            request_id=uuid4(),
            created_at=NOW,
        )
        session.add(branch)
        with pytest.raises(IntegrityError):
            session.commit()
