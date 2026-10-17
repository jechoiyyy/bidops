"""RL-03 STEP-006 T4: automatic card verdict trigger, daily-cap queue and drain.

World: the real Rootlab v2 company (outside Git) with the approved
``analysis-policy-luna-rl-v1`` row and a policy transfer approval, SW=Y
pre-specs whose attachment fetch finished with a safe document and a stored
structure (six heading sections + one requirement card), an authoritative
opportunity link and a weekday briefing recommendation item.  **No overview
run exists anywhere.**

The briefing hook asks the automatic preparation to build the bundle (a fake
bundle service that only flips draft → ready, like the existing auto-start
suite), the ready-transition hook then creates preview → review → attempt →
approval with ``actor_kind=system``.  Completed/failed attempts come from the
real worker with the scripted fake Luna of the T5 suite.

Each case runs on SQLite and, with ``BIDOPS_TEST_POSTGRES_URL``, on a migrated
PostgreSQL 17 database; the concurrency case (advisory lock, decision B8) and
the worker-credential case (``scripts/runtime-privileges.sql`` + ``SET ROLE
worker``) are PostgreSQL only.  No model transport or network is used.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import threading
import time as time_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.db import _json_serializer, schema_bound
from app.core.model_client import ModelClient
from app.core.models import AuditEvent
from app.deep_review.models import (
    AttachmentFetch,
    ContentObject,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentVersion,
    PrespecOverviewRun,
    VerdictRequest,
    WorkJob,
)
from app.deep_review.services import transfer_policy, verdict_trigger
from app.deep_review.services.deep_reviews import CREATION_ACTION_BY_ACTOR_KIND, DeepReviewService
from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE, import_policy_version
from app.lifecycle.models import Attachment, Briefing, BriefingItem, Notice, Opportunity, OpportunityLink
from tests.app import test_card_analysis_postgres as cap
from tests.app import test_transfer_policy as tp
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_fit_enqueue import ready_bundle
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store
from tests.postgres import migrated_engine, requires_postgres, temporary_database


pytestmark = tp.needs_rootlab

KST = transfer_policy.KST
WHEN = datetime(2026, 10, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_model_transport(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("model transport called")

    from app.deep_review.services import luna_client

    monkeypatch.setattr(ModelClient, "for_purpose", classmethod(forbidden))
    monkeypatch.setattr(luna_client.LunaClient, "__init__", forbidden)
    yield
    # monkeypatch restores the RL env afterwards; do not leave cached RL settings behind
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def flow_engine(request):
    if request.param == "sqlite":
        bind = tp._sqlite_engine()
        try:
            yield bind
        finally:
            bind.dispose()
    else:
        with migrated_engine() as bind:
            yield bind


# --- world ------------------------------------------------------------------------------


def auto_world(session: Session, monkeypatch, *, daily_cap: int = 10, approve: bool = True) -> SimpleNamespace:
    tp.configure(monkeypatch)
    imported = tp._import_rootlab(session)
    policy = import_policy_version(session, RL_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-rl-v1")
    session.commit()
    tp.configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(policy.id),
                 BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED="true")
    approval = tp.approve(session, daily_cap=daily_cap) if approve else None
    return SimpleNamespace(company_id=imported.company_id, policy_id=policy.id, approval=approval)


def seed_pre_spec(session: Session, *, sw: str = "Y", source_type: str = "pre_spec",
                  with_bundle: bool = False) -> SimpleNamespace:
    """A notice whose fetch finished with one safe document and a stored structure."""

    notice = Notice(notice_key=f"rl-trigger:{uuid4()}", source_type=source_type, title="루트랩 자동 판정",
                    qualification_flags_json={"sw_business_status": sw})
    session.add(notice)
    session.flush()
    attachment = Attachment(notice_id=notice.id, name="제안요청서.hwp", origin="g2b")
    content = ContentObject(id=uuid4(), sha256=uuid4().hex + uuid4().hex, size_bytes=10,
                            detected_mime="application/pdf", retention_class="document-source")
    session.add_all([attachment, content])
    session.flush()
    document = DocumentVersion(id=uuid4(), notice_id=notice.id, attachment_id=attachment.id,
                               content_object_id=content.id, version=1, source_kind="manual",
                               original_filename="제안요청서.hwp", role="제안요청서", is_current=True,
                               safety_status="safe")
    session.add(document)
    session.flush()
    session.add(AttachmentFetch(attachment_id=attachment.id, status="완료", eligibility_reason="sw_business_object",
                                next_attempt_at=WHEN, completed_at=WHEN, document_version_id=document.id))
    tp._store_structure(session, document)
    opportunity = Opportunity(first_registered_stage="pre_spec" if source_type == "pre_spec" else "bid_notice")
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=notice.id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"R26BD{notice.id:08d}"))
    session.flush()
    bundle_id = ready_bundle(session, notice.id, document.id) if with_bundle else None
    session.commit()
    return SimpleNamespace(notice_id=notice.id, document_id=document.id, opportunity_id=opportunity.id,
                           bundle_id=bundle_id)


def recommend(session: Session, seeded: SimpleNamespace, *, briefing_date: date = date(2026, 10, 16),
              stage: str = "pre_spec") -> BriefingItem:
    briefing = session.scalar(select(Briefing).where(Briefing.briefing_date == briefing_date))
    if briefing is None:
        briefing = Briefing(briefing_date=briefing_date, status="generated", generated_at=WHEN,
                            policy_sha256="a" * 64, graph_version_id=uuid4(), item_count=0, excluded_counts={},
                            warnings=[], created_by="system:build-briefing")
        session.add(briefing)
        session.flush()
    rank = int(session.scalar(select(func.count()).select_from(BriefingItem).where(
        BriefingItem.briefing_id == briefing.id)) or 0) + 1
    item = BriefingItem(briefing_id=briefing.id, kind="recommendation", rank=rank, stage=stage,
                        notice_id=seeded.notice_id, opportunity_id=seeded.opportunity_id, score=Decimal("50"),
                        reasons=[], blocking=[], change_fields=[], reaction="대기", revision=0)
    session.add(item)
    session.commit()
    return item


class FakeBundleService:
    """``DocumentBundleService`` auto-preparation double: a draft over the document, then ``ready``."""

    def __init__(self, document_id) -> None:
        self.document_id = document_id
        self.created = 0

    def create_bundle(self, session: Session, notice_id: int, actor: str, **_kwargs):
        bundle_id = ready_bundle(session, notice_id, self.document_id)
        bundle = session.get(DocumentBundle, bundle_id)
        bundle.status, bundle.created_by_name = "draft", actor
        bundle.confirmed_by_name = bundle.confirmed_at = None
        session.commit()
        self.created += 1
        return SimpleNamespace(id=bundle.id, version=bundle.version, revision=bundle.revision)

    def confirm(self, session: Session, bundle_id, request, actor: str, **_kwargs):
        bundle = session.get(DocumentBundle, bundle_id)
        bundle.status, bundle.confirmed_by_name, bundle.confirmed_at = "ready", actor, WHEN
        session.commit()
        return SimpleNamespace(id=bundle.id, version=bundle.version, revision=bundle.revision,
                               documents=[self.document_id])


def count(session: Session, model, *conditions) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def deep_review_jobs(session: Session) -> int:
    return count(session, WorkJob, WorkJob.job_type == "deep_review")


# --- T4: recommendation → preparation → ready hook → system attempt -----------------------


def test_t4_recommendation_prepares_documents_and_the_ready_hook_starts_a_system_attempt(
    flow_engine, monkeypatch
) -> None:
    with Session(flow_engine) as session:
        world = auto_world(session, monkeypatch)
        seeded = seed_pre_spec(session)
        item = recommend(session, seeded)
        bundles = FakeBundleService(seeded.document_id)

        outcome = verdict_trigger.on_briefing_recommendation(
            session, seeded.notice_id, item.id, service=tp.service(), bundle_service=bundles,
        )

        assert outcome.reason is None and outcome.attempt_id is not None and not outcome.queued
        assert bundles.created == 1
        assert count(session, DocumentBundle, DocumentBundle.status == "ready") == 1
        review = session.scalar(select(DeepReview))
        attempt = session.get(DeepReviewAttempt, outcome.attempt_id)
        assert (review.company_id, review.notice_id, review.requested_by_name) == (
            world.company_id, seeded.notice_id, transfer_policy.SYSTEM_ACTOR)
        assert attempt.deep_review_id == review.id and attempt.status == "queued"
        assert deep_review_jobs(session) == 1
        approval = session.scalar(select(DeepReviewApproval))
        assert approval.attempt_id == attempt.id and approval.claimed_name == transfer_policy.SYSTEM_ACTOR
        creation = session.scalars(select(AuditEvent).where(
            AuditEvent.action == CREATION_ACTION_BY_ACTOR_KIND["system"])).all()
        assert [(row.actor_kind, row.claimed_name) for row in creation] == [("system", transfer_policy.SYSTEM_ACTOR)]
        preview = session.get(DeepReviewPreview, approval.preview_id)
        assert preview.input_snapshot["overview_run_id"] is None and preview.input_snapshot["overview_sha256"] is None
        # the bundle audit names the briefing trigger; no overview run, no queue entry
        confirms = session.scalars(select(AuditEvent).where(AuditEvent.action == "document_bundle.auto_confirm")).all()
        assert [row.safe_metadata["trigger"] for row in confirms] == ["briefing_recommendation"]
        assert count(session, PrespecOverviewRun) == 0
        assert count(session, VerdictRequest) == 0

        # the same recommendation again (bundle now ready): the active attempt blocks a second one
        again = verdict_trigger.on_briefing_recommendation(session, seeded.notice_id, item.id, service=tp.service())
        assert again.reason == "active_attempt_exists"
        assert count(session, DeepReviewAttempt) == 1 and deep_review_jobs(session) == 1


def test_t4_documents_arriving_after_the_briefing_still_prepare_and_start(flow_engine, monkeypatch) -> None:
    """Fetch still running at briefing time → the fetch-completion preparation continues (RL auto on)."""

    from app.deep_review.services.auto_preparation import maybe_auto_prepare

    with Session(flow_engine) as session:
        auto_world(session, monkeypatch)
        seeded = seed_pre_spec(session)
        fetch = session.scalar(select(AttachmentFetch))
        fetch.status, fetch.completed_at = "대기", None
        session.commit()
        item = recommend(session, seeded)
        bundles = FakeBundleService(seeded.document_id)

        waiting = verdict_trigger.on_briefing_recommendation(
            session, seeded.notice_id, item.id, service=tp.service(), bundle_service=bundles,
        )
        assert waiting.reason == "preparation_requested" and bundles.created == 0

        fetch = session.scalar(select(AttachmentFetch))
        fetch.status, fetch.completed_at = "완료", WHEN
        session.commit()
        # the attachment worker's call (no trigger): the recommendation keeps the SW=Y notice eligible
        outcomes = maybe_auto_prepare(session, [seeded.notice_id], service=bundles, deep_review_service=tp.service())

        assert outcomes[0].confirmed and outcomes[0].rl_verdict.reason is None
        assert count(session, DeepReviewAttempt) == 1 and count(session, PrespecOverviewRun) == 0

        # without the RL auto flag the same call keeps the old eligibility (grade/overview only)
        other = seed_pre_spec(session)
        recommend(session, other)
        tp.configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(
            transfer_policy.selected_rl_policy_row(session).id))
        untouched = maybe_auto_prepare(session, [other.notice_id], service=FakeBundleService(other.document_id))
        assert untouched[0].reason == "grade_not_priority" and untouched[0].rl_verdict is None


def test_t4_completed_combination_is_not_retriggered_and_a_failure_waits_for_people(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        auto_world(session, monkeypatch)
        done = seed_pre_spec(session, with_bundle=True)
        failing = seed_pre_spec(session, with_bundle=True)
        recommend(session, done)
        recommend(session, failing)
        knowledge = cap.resolve_company_knowledge_context(session, verdict_trigger.real_company(session).id)

        first = verdict_trigger.on_bundle_ready(session, done.notice_id, service=tp.service())
        assert first.reason is None
        good = DeepReviewService(client=cap.FakeLuna(knowledge.ontology), structure_loader=tp._structure_loader,
                                 raw_response_store=_FixtureStore())
        cap.run(session, good)
        assert session.get(DeepReviewAttempt, first.attempt_id).status == "completed"

        # current completed attempt of the same (notice, fingerprint, graph, policy sha): no new attempt
        again = verdict_trigger.on_bundle_ready(session, done.notice_id, service=tp.service())
        assert again.reason == "verdict_current"
        assert count(session, DeepReviewAttempt) == 1

        second = verdict_trigger.on_bundle_ready(session, failing.notice_id, service=tp.service())
        assert second.reason is None
        bad = DeepReviewService(client=cap.FakeLuna(knowledge.ontology, {("extract", 0): cap._bad_quote}),
                                structure_loader=tp._structure_loader, raw_response_store=_FixtureStore())
        assert cap.run_code(session, bad) == "card_extract_invalid"
        session.rollback()
        assert session.get(DeepReviewAttempt, second.attempt_id).status == "failed"

        # no automatic retry of a failed combination (intent "실패 보존"): a person asks again
        retry = verdict_trigger.on_bundle_ready(session, failing.notice_id, service=tp.service())
        assert retry.reason == "manual_request_required"
        assert count(session, DeepReviewAttempt) == 2 and deep_review_jobs(session) == 2


def test_t4_daily_cap_queues_without_a_job_and_the_next_day_drain_starts_oldest_first(
    flow_engine, monkeypatch
) -> None:
    with Session(flow_engine) as session:
        auto_world(session, monkeypatch, daily_cap=1)
        first, second, third = (seed_pre_spec(session, with_bundle=True) for _ in range(3))
        for seeded in (first, second, third):
            recommend(session, seeded)

        started = verdict_trigger.on_bundle_ready(session, first.notice_id, service=tp.service())
        assert started.reason is None
        capped = verdict_trigger.on_bundle_ready(session, second.notice_id, service=tp.service())
        assert capped.reason == "daily_cap_reached" and capped.queued and capped.attempt_id is None
        later = verdict_trigger.on_bundle_ready(session, third.notice_id, service=tp.service())
        assert later.queued
        # a repeated trigger does not add a second queue row for the same notice
        repeat = verdict_trigger.on_bundle_ready(session, second.notice_id, service=tp.service())
        assert repeat.queued and repeat.request_row_id == capped.request_row_id
        rows = session.scalars(select(VerdictRequest).order_by(VerdictRequest.created_at, VerdictRequest.id)).all()
        assert [(row.notice_id, row.status, row.reason, row.actor, row.started_attempt_id) for row in rows] == [
            (second.notice_id, "queued", "daily_cap_reached", transfer_policy.SYSTEM_ACTOR, None),
            (third.notice_id, "queued", "daily_cap_reached", transfer_policy.SYSTEM_ACTOR, None),
        ]
        assert rows[0].opportunity_id == second.opportunity_id
        assert count(session, DeepReviewAttempt) == 1 and deep_review_jobs(session) == 1  # no WorkJob for the queue

        # same day: rows queued today are not drained (the cap is spent anyway)
        same_day = verdict_trigger.drain_verdict_queue(session, service=tp.service())
        assert same_day.started == [] and same_day.remaining == 2 and same_day.stopped_reason is None
        session.commit()

        # "next day": the two rows were queued yesterday (KST) and the new day's cap has one
        # free slot (cap 2 with today's one start). One pass, oldest first, then stop at the cap.
        yesterday = datetime.now(KST) - timedelta(days=1)
        for offset, row in enumerate(rows):
            row.created_at = yesterday + timedelta(minutes=offset)
        session.commit()
        active = transfer_policy.active_approval(session)
        transfer_policy.revoke_transfer_policy(session, approval_id=active.id, actor="jechoi", reason="cap 2")
        session.commit()
        tp.approve(session, daily_cap=2)

        result = verdict_trigger.drain_verdict_queue(session, service=tp.service())

        session.expire_all()
        rows = session.scalars(select(VerdictRequest).order_by(VerdictRequest.created_at, VerdictRequest.id)).all()
        assert len(result.started) == 1 and result.stopped_reason == "daily_cap_reached" and result.remaining == 1
        assert (rows[0].notice_id, rows[0].status, rows[0].started_attempt_id) == (
            second.notice_id, "started", result.started[0])
        assert (rows[1].notice_id, rows[1].status, rows[1].started_attempt_id) == (third.notice_id, "queued", None)
        attempt = session.get(DeepReviewAttempt, result.started[0])
        assert session.get(DeepReview, attempt.deep_review_id).notice_id == second.notice_id
        assert count(session, DeepReviewAttempt) == 2 and deep_review_jobs(session) == 2


def test_t4_bid_notice_sw_n_holdout_and_disabled_flags_never_start(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        auto_world(session, monkeypatch)
        bid = seed_pre_spec(session, source_type="bid_notice")
        sw_n = seed_pre_spec(session, sw="N")
        held = seed_pre_spec(session, with_bundle=True)
        plain = seed_pre_spec(session, with_bundle=True)
        bid_item = recommend(session, bid, stage="bid_notice")
        sw_item = recommend(session, sw_n)
        recommend(session, held)
        recommend(session, plain)
        bundles = FakeBundleService(sw_n.document_id)

        assert verdict_trigger.on_briefing_recommendation(
            session, bid.notice_id, bid_item.id, service=tp.service()).reason == "not_pre_spec"
        assert verdict_trigger.on_briefing_recommendation(
            session, sw_n.notice_id, sw_item.id, service=tp.service(), bundle_service=bundles,
        ).reason == "effective_grade_ineligible"
        assert bundles.created == 0  # SW≠Y is never prepared for a verdict

        result = verdict_trigger.hold_notices(session, [held.notice_id], actor="jechoi")
        session.commit()
        assert result == {"held": [held.notice_id], "already_held": []}
        assert verdict_trigger.hold_notices(session, [held.notice_id], actor="jechoi") == {
            "held": [], "already_held": [held.notice_id]}
        session.commit()
        assert verdict_trigger.on_bundle_ready(session, held.notice_id, service=tp.service()).reason == "gold_holdout"

        tp.configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(
            transfer_policy.selected_rl_policy_row(session).id))  # auto start back to the default false
        assert verdict_trigger.on_bundle_ready(session, plain.notice_id, service=tp.service()).reason == (
            "auto_start_disabled")
        assert verdict_trigger.drain_verdict_queue(session, service=tp.service()).stopped_reason == (
            "auto_start_disabled")

        assert count(session, DeepReviewAttempt) == 0 and deep_review_jobs(session) == 0
        assert count(session, PrespecOverviewRun) == 0


def test_t4_no_approval_creates_nothing_and_does_not_queue(flow_engine, monkeypatch) -> None:
    with Session(flow_engine) as session:
        auto_world(session, monkeypatch, approve=False)
        seeded = seed_pre_spec(session, with_bundle=True)
        recommend(session, seeded)

        outcome = verdict_trigger.on_bundle_ready(session, seeded.notice_id, service=tp.service())

        assert outcome.reason == "policy_not_approved" and not outcome.queued
        for model in (DeepReviewPreview, DeepReview, DeepReviewAttempt, DeepReviewApproval, VerdictRequest):
            assert count(session, model) == 0


# --- B8: concurrent starts cannot exceed the daily cap (PostgreSQL advisory lock) ---------


@requires_postgres
def test_t4_concurrent_starts_are_serialized_by_the_advisory_lock(monkeypatch) -> None:
    with migrated_engine() as bind:
        with Session(bind) as session:
            auto_world(session, monkeypatch, daily_cap=1)
            first = seed_pre_spec(session, with_bundle=True)
            second = seed_pre_spec(session, with_bundle=True)
            recommend(session, first)
            recommend(session, second)

        original = transfer_policy.today_used

        def slow_today_used(session, *, now=None):
            used = original(session, now=now)
            time_module.sleep(0.6)  # widen the count → insert window
            return used

        monkeypatch.setattr(transfer_policy, "today_used", slow_today_used)
        barrier = threading.Barrier(2)
        outcomes: dict[int, object] = {}
        errors: list[BaseException] = []

        def trigger(notice_id: int) -> None:
            try:
                with Session(bind) as own:
                    barrier.wait(timeout=10)
                    outcomes[notice_id] = verdict_trigger.on_bundle_ready(own, notice_id, service=tp.service())
            except BaseException as error:  # pragma: no cover - surfaced below
                errors.append(error)

        threads = [threading.Thread(target=trigger, args=(seeded.notice_id,)) for seeded in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not errors
        reasons = sorted(str(outcome.reason) for outcome in outcomes.values())
        assert reasons == ["None", "daily_cap_reached"]
        with Session(bind) as session:
            assert count(session, DeepReviewAttempt) == 1
            assert count(session, VerdictRequest, VerdictRequest.status == "queued") == 1


# --- worker credential: the ready hook runs in the attachment/document worker -------------


@requires_postgres
def test_t4_ready_hook_creates_the_rows_with_the_worker_runtime_role(monkeypatch) -> None:
    from tests.app.test_runtime_database_privileges import _apply_policy, _ensure_roles

    _ensure_roles()
    with temporary_database() as database_url:
        policy_engine = _apply_policy(database_url)
        owner = schema_bound(create_engine(database_url, json_serializer=_json_serializer, future=True))
        worker_base = create_engine(database_url, json_serializer=_json_serializer, future=True)

        @event.listens_for(worker_base, "connect")
        def _worker_role(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("SET ROLE worker")
            cursor.close()
            dbapi_connection.commit()

        worker = schema_bound(worker_base)
        try:
            with Session(owner) as session:
                auto_world(session, monkeypatch, daily_cap=1)
                seeded = seed_pre_spec(session, with_bundle=True)
                recommend(session, seeded)
                other = seed_pre_spec(session, with_bundle=True)
                recommend(session, other)
            with Session(worker) as session:
                assert session.execute(select(func.current_user())).scalar() == "worker"
                outcome = verdict_trigger.on_bundle_ready(session, seeded.notice_id, service=tp.service())
                capped = verdict_trigger.on_bundle_ready(session, other.notice_id, service=tp.service())
                # the identity query opened the caller's transaction, so the hook worked in a
                # savepoint of it; the caller (worker loop) owns the commit
                session.commit()
            assert outcome.reason is None and outcome.attempt_id is not None
            assert capped.reason == "daily_cap_reached" and capped.queued
            with Session(owner) as session:
                assert count(session, DeepReviewPreview) == 1 and count(session, DeepReviewApproval) == 1
                assert session.get(DeepReviewAttempt, outcome.attempt_id).status == "queued"
                assert count(session, VerdictRequest, VerdictRequest.status == "queued") == 1
        finally:
            worker_base.dispose()
            owner.dispose()
            policy_engine.dispose()


# --- CLI: drain-verdict-queue [--date] / --hold <ids> --reason gold_holdout --------------


def test_t4_drain_cli_holds_and_drains(flow_engine, monkeypatch, capsys) -> None:
    from app.deep_review.cli import drain_verdict_queue as drain_cli

    with Session(flow_engine) as session:
        auto_world(session, monkeypatch)
        seeded = seed_pre_spec(session, with_bundle=True)

    code, payload, err = tp._cli(monkeypatch, flow_engine, drain_cli, "--hold", str(seeded.notice_id),
                                 "--reason", "gold_holdout", "--actor", "jechoi", capsys=capsys)
    assert (code, payload, err) == (0, {"mode": "hold", "held": [seeded.notice_id], "already_held": [],
                                        "errors": []}, "")
    code, payload, err = tp._cli(monkeypatch, flow_engine, drain_cli, "--hold", "999999",
                                 "--reason", "gold_holdout", "--actor", "jechoi", capsys=capsys)
    assert (code, payload, err) == (2, {"mode": "hold", "errors": ["not_found"]}, "not_found")
    code, payload, err = tp._cli(monkeypatch, flow_engine, drain_cli, "--hold", str(seeded.notice_id),
                                 "--reason", "gold_holdout", "--actor", "system:x", capsys=capsys)
    assert (code, err) == (2, "actor_name_invalid")

    code, payload, err = tp._cli(monkeypatch, flow_engine, drain_cli, "--date", "2026-10-19", capsys=capsys)
    assert (code, payload) == (0, {"mode": "drain", "as_of": "2026-10-19", "started": 0, "started_attempt_ids": [],
                                   "rejected": 0, "remaining": 0, "stopped_reason": None, "errors": []})
    with Session(flow_engine) as session:
        rows = session.scalars(select(VerdictRequest)).all()
        assert [(row.notice_id, row.status, row.reason, row.actor) for row in rows] == [
            (seeded.notice_id, "rejected", "gold_holdout", "jechoi")]
        assert rows[0].opportunity_id == seeded.opportunity_id
