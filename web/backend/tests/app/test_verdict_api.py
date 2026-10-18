"""RL-03 STEP-007 T6: practitioner verdict REST (HP-04 T1·T2 + RL additions).

Through the real FastAPI app (``lifecycle`` + ``deep_review``) with the test
session: the company verdict view and its opportunity alias (strict dicts for
none / pending / completed / needs_human_review / legacy), attempt selection
and 404/422, the opportunity alias rules (two linked pre-specs → newest link,
none → ``availability=none`` with ``notice_id=null``, merged → retained
opportunity), ``source_binding.company_sha256`` = frozen graph sha with the
bundle structure ids (B4), the B4 matrix keys, ``card-v1`` currentness without
any overview run (bundle/document/SW changes are stale), the manual request
(202 receipt, replay, idempotency conflict, cap/approval/SW/active codes,
gold-holdout release), feedback POST, the transfer-policy read and the
middleware guard with ``BIDOPS_RL_ANALYSIS_ENABLED`` on/off.

Runs on SQLite and, with ``BIDOPS_TEST_POSTGRES_URL``, on migrated PostgreSQL
17 (the strict dict comparisons run on both).  Completed/failed attempts come
from the real worker with the scripted fake Luna; no model transport or
network is used.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.models import AuditEvent
from app.deep_review.models import (
    CardAnalysisStage,
    CompanyKnowledgeVersion,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentBundle,
    DocumentBundleItem,
    VerdictFeedback,
    VerdictRequest,
    WorkJob,
)
from app.deep_review.routers import verdicts as verdicts_router
from app.deep_review.services import company_deep_review as cdr
from app.deep_review.services import transfer_policy
from app.deep_review.services.deep_reviews import DeepReviewService
from app.deep_review.services.input_versions import DEMO_LUNA_POLICY_FILE, import_policy_version
from app.lifecycle.models import Notice, Opportunity, OpportunityLink
from app.main import create_app
from tests.app import test_card_analysis_postgres as cap
from tests.app import test_transfer_policy as tp
from tests.app import test_verdict_trigger_postgres as vt
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store
from tests.app.test_verdict_trigger_postgres import flow_engine, no_model_transport  # noqa: F401


pytestmark = tp.needs_rootlab

ACTOR = {"X-BidOps-Actor-Name": "jechoi"}
VIEW_KEYS = {
    "schema_version", "company_id", "notice_id", "attempt_id", "availability", "is_current", "stale_reasons",
    "quality_status", "identity", "source_binding", "result", "partial_stage_ids", "error_code",
    "missing_sections", "started_at", "finished_at", "partial_matrix", "briefing_item_id", "opportunity_id",
    "rejected_units",  # 결정 B51 (additive)
}
FIT_ORDER = {"gap": 0, "unknown": 1, "met": 2}


@pytest.fixture
def client_for(monkeypatch):
    monkeypatch.setattr(verdicts_router, "service", tp.service())
    clients = []

    def make(session: Session) -> TestClient:
        application = create_app(modules=("lifecycle", "deep_review"), mount_frontend=False)
        application.dependency_overrides[get_db] = lambda: session
        client = TestClient(application)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


# --- world helpers -----------------------------------------------------------------------


def started_world(session: Session, monkeypatch, *, daily_cap: int = 10, approve: bool = True):
    world = vt.auto_world(session, monkeypatch, daily_cap=daily_cap, approve=approve)
    tp.configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(world.policy_id))  # auto start off
    seeded = vt.seed_pre_spec(session, with_bundle=True)
    item = vt.recommend(session, seeded)
    return world, seeded, item


def start(session: Session, world, seeded) -> cdr.RLVerdictStart:
    started = cdr.start_rl_verdict(tp.service(), session, company_id=world.company_id,
                                   notice_id=seeded.notice_id, bundle_id=seeded.bundle_id)
    session.commit()
    return started


def worker(session: Session, overrides=None) -> DeepReviewService:
    company = session.scalar(select(DeepReview.company_id).limit(1))
    knowledge = cap.resolve_company_knowledge_context(session, company)
    return DeepReviewService(client=cap.FakeLuna(knowledge.ontology, overrides), structure_loader=tp._structure_loader,
                             raw_response_store=_FixtureStore())


def run_completed(session: Session, world, seeded) -> cdr.RLVerdictStart:
    started = start(session, world, seeded)
    cap.run(session, worker(session))
    session.commit()
    assert session.get(DeepReviewAttempt, started.attempt_id).status == "completed"
    return started


def company_url(world, seeded, suffix: str = "verdict") -> str:
    return f"/api/companies/{world.company_id}/pre-specs/{seeded.notice_id}/{suffix}"


def iso(value):
    return value.isoformat() if value is not None else None


def stage_rows(session: Session, attempt_id) -> list[CardAnalysisStage]:
    rows = session.scalars(select(CardAnalysisStage).where(CardAnalysisStage.attempt_id == attempt_id)).all()
    order = {"extract": 0, "compare": 1, "role": 2, "synthesis": 3}
    roles = ("eligibility_economics", "technical_fit", "operations_risk")
    return sorted(rows, key=lambda row: (
        int(row.stage_key) if row.stage in {"extract", "compare"} else 10**9, order[row.stage],
        roles.index(row.stage_key) if row.stage == "role" else 0, str(row.id)))


def expected_rows(session: Session, attempt_id, rows_source: str) -> list[dict]:
    """Matrix rows rebuilt from the stored stage payloads and the frozen units (independent of the service)."""

    preview = session.scalar(select(DeepReviewPreview).join(
        DeepReviewApproval, DeepReviewApproval.preview_id == DeepReviewPreview.id,
    ).where(DeepReviewApproval.attempt_id == attempt_id))
    frozen = preview.input_snapshot
    units = {unit["unit_id"]: unit for unit in frozen["card_analysis"]["units"]}
    order = {unit["unit_id"]: index for index, unit in enumerate(frozen["card_analysis"]["units"])}
    labels = {node["id"]: node["label"] for node in frozen["graph_nodes"] if node.get("label")}
    rows = stage_rows(session, attempt_id)
    extract = {item["unit_id"]: item for row in rows if row.stage == "extract" for item in row.payload["items"]}
    compare = {item["unit_id"]: item for row in rows if row.stage == "compare" for item in row.payload["items"]}
    roles = {row.stage_key: row.payload for row in rows if row.stage == "role"}

    def enrich(unit_id, type_, fit, findings):
        facts = []
        for result in compare.get(unit_id, {}).get("constraint_results", []):
            for fact_id in result["fact_ids"]:
                if fact_id in labels and labels[fact_id] not in facts:
                    facts.append(labels[fact_id])
        item = extract.get(unit_id)
        return {
            "unit_id": unit_id, "type": type_, "fit_status": fit, "role_findings": findings,
            "evidence_refs": item["evidence"] if item else [], "page_range": units[unit_id]["page_range"],
            "mapping_status": units[unit_id]["mapping_status"],
            "normalized_requirement": item["normalized_requirement"] if item else None,
            "mandatory": item["mandatory"] if item else None, "fact_labels": facts,
            "rejected_rule_codes": [],  # 결정 B51 (additive; no rejected unit in these worlds)
        }

    if rows_source == "final":
        final = next(row.payload for row in rows if row.stage == "synthesis")
        built = [enrich(row["unit_id"], row["type"], row["fit_status"], row["role_findings"]) for row in final["matrix"]]
    else:
        built = []
        for unit_id, item in compare.items():
            findings = [
                {"role": role, **{key: finding[key] for key in ("assessment", "reason", "evidence_refs")}}
                for role in ("eligibility_economics", "technical_fit", "operations_risk") if role in roles
                for finding in roles[role]["unit_findings"] if finding["unit_id"] == unit_id
            ]
            built.append(enrich(unit_id, extract[unit_id]["type"], item["fit_status"], findings))
    return sorted(built, key=lambda row: (FIT_ORDER[row["fit_status"]], order[row["unit_id"]]))


def expected_view(session: Session, world, seeded, item, started, *, availability: str, is_current: bool,
                  stale_reasons: list[str], error_code=None, opportunity_id=None) -> dict:
    attempt = session.get(DeepReviewAttempt, started.attempt_id)
    preview = session.get(DeepReviewPreview, started.preview_id)
    frozen, provenance = preview.input_snapshot, preview.provenance_jsonb
    graph = session.get(CompanyKnowledgeVersion, UUID(frozen["graph_version_id"]))
    structures = dict(session.execute(select(
        DocumentBundleItem.document_version_id, DocumentBundleItem.structure_id_at_confirmation,
    ).where(DocumentBundleItem.bundle_id == seeded.bundle_id)).all())
    rows = stage_rows(session, started.attempt_id)
    final = next((row.payload for row in rows if row.stage == "synthesis"), None)
    completed = availability == "completed"
    return {
        "schema_version": "bidops.practitioner-verdict-view.v1",
        "company_id": str(world.company_id), "notice_id": seeded.notice_id,
        "attempt_id": str(started.attempt_id), "availability": availability, "is_current": is_current,
        "stale_reasons": stale_reasons, "quality_status": "unmeasured_reference",
        "identity": {"policy_id": str(world.policy_id), "policy_sha256": frozen["policy_sha256"],
                     "model": "gpt-6-luna", "reasoning_effort": "high", "cli_version": "0.162.1"},
        "source_binding": {
            "document_versions": [
                {"document_version_id": row["document_version_id"], "source_sha256": row["source_sha256"],
                 "structure_id": str(structures[seeded.document_id])}
                for row in provenance["documents"]
            ],
            "company_version_id": str(graph.id), "company_sha256": graph.graph_sha256,
            "ontology_sha256": frozen["ontology_sha256"],
        },
        "result": None if not completed else {
            "verdict": final["verdict"], "reason": final["reason"],
            "blocking_condition_ids": final["blocking_condition_ids"], "checklist": final["checklist"],
            "matrix": expected_rows(session, started.attempt_id, "final"), "cautions": final["cautions"],
            "conflicts": final["conflicts"],
            # 결정 B55: the view always carries ``origin`` (null on rows stored before policy v9)
            "next_actions": [{**row, "origin": row.get("origin")} for row in final["next_actions"]],
        },
        "partial_stage_ids": [] if completed else [str(row.id) for row in rows],
        "error_code": error_code,
        "missing_sections": frozen["card_analysis"]["missing_sections"],
        "started_at": iso(attempt.started_at), "finished_at": iso(attempt.completed_at),
        "partial_matrix": [] if completed else expected_rows(session, started.attempt_id, "partial"),
        "briefing_item_id": str(item.id),
        "opportunity_id": opportunity_id if opportunity_id is not None else seeded.opportunity_id,
        "rejected_units": [],
    }


# --- HP-04 T1·T2 + alias ------------------------------------------------------------------


def test_t6_none_pending_completed_strict_dicts_and_the_opportunity_alias(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)

        none = client.get(company_url(world, seeded))
        assert none.status_code == 200
        assert none.json() == {
            "schema_version": "bidops.practitioner-verdict-view.v1", "company_id": str(world.company_id),
            "notice_id": seeded.notice_id, "attempt_id": None, "availability": "none", "is_current": False,
            "stale_reasons": [], "quality_status": None, "identity": None, "source_binding": None, "result": None,
            "partial_stage_ids": [], "error_code": None, "missing_sections": [], "started_at": None,
            "finished_at": None, "partial_matrix": [], "briefing_item_id": str(item.id),
            "opportunity_id": seeded.opportunity_id, "rejected_units": [],
        }
        assert client.get(f"/api/opportunities/{seeded.opportunity_id}/verdict").json() == none.json()

        started = start(session, world, seeded)
        pending = client.get(company_url(world, seeded)).json()
        assert pending == expected_view(session, world, seeded, item, started, availability="pending",
                                        is_current=True, stale_reasons=[])
        assert pending["partial_matrix"] == [] and pending["partial_stage_ids"] == []

        cap.run(session, worker(session))
        session.commit()
        completed = client.get(company_url(world, seeded))
        assert completed.status_code == 200
        body = completed.json()
        assert set(body) == VIEW_KEYS
        assert body == expected_view(session, world, seeded, item, started, availability="completed",
                                     is_current=True, stale_reasons=[])
        # card-v1 is current without any overview run; company_sha256 is the frozen graph sha
        frozen = session.get(DeepReviewPreview, started.preview_id).input_snapshot
        assert frozen["overview_run_id"] is None
        assert body["source_binding"]["company_sha256"] == frozen["graph_sha256"]
        assert [row["key"] for row in body["result"]["checklist"]] == [
            "qualification_track_record", "staffing_onsite", "amount_period", "technology", "operations_sla_security"]
        assert sorted(row["unit_id"] for row in body["result"]["matrix"]) == sorted(
            unit["unit_id"] for unit in frozen["card_analysis"]["units"])
        assert all(row["normalized_requirement"] and "mandatory" in row and isinstance(row["fact_labels"], list)
                   for row in body["result"]["matrix"])
        alias = client.get(f"/api/opportunities/{seeded.opportunity_id}/verdict")
        assert alias.status_code == 200 and alias.json() == body
        explicit = client.get(company_url(world, seeded), params={"attempt_id": str(started.attempt_id)}).json()
        assert explicit == body
        # GET creates nothing
        assert session.scalar(select(DeepReviewAttempt.id).where(DeepReviewAttempt.id != started.attempt_id)) is None


def test_t6_failed_validation_is_needs_human_review_with_the_validated_partial_table(
    flow_engine, monkeypatch, client_for
) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        started = start(session, world, seeded)
        assert cap.run_code(session, worker(session, {("technical_fit", 0): cap._upgrade_unknown})) == (
            "card_role_invalid")
        session.rollback()

        body = client.get(company_url(world, seeded)).json()

        assert body == expected_view(session, world, seeded, item, started, availability="needs_human_review",
                                     is_current=True, stale_reasons=[], error_code="card_role_invalid")
        assert body["result"] is None and body["partial_matrix"]
        assert {finding["role"] for row in body["partial_matrix"] for finding in row["role_findings"]} == {
            "eligibility_economics"}
        assert len(body["partial_stage_ids"]) == len(stage_rows(session, started.attempt_id))

        # an infrastructure failure that is not a validation code stays "failed"
        session.execute(update(WorkJob).where(
            WorkJob.id == session.get(DeepReviewAttempt, started.attempt_id).work_job_id,
        ).values(last_error_code="runner_unavailable"))
        session.commit()
        failed = client.get(company_url(world, seeded)).json()
        assert (failed["availability"], failed["error_code"]) == ("failed", "runner_unavailable")


def test_t6_attempt_selection_legacy_and_errors(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        other = vt.seed_pre_spec(session, with_bundle=True)
        client = client_for(session)
        first = run_completed(session, world, seeded)
        second = start(session, world, seeded)  # same lineage → new attempt of the same review

        latest = client.get(company_url(world, seeded)).json()
        assert (latest["attempt_id"], latest["availability"]) == (str(second.attempt_id), "pending")
        older = client.get(company_url(world, seeded), params={"attempt_id": str(first.attempt_id)}).json()
        # an explicitly selected older attempt keeps its result and is stale (superseded)
        assert older["availability"] == "completed" and older["result"] is not None
        assert (older["is_current"], older["stale_reasons"]) == (False, ["superseded"])

        # a narrative (legacy) attempt of the company is only shown when explicitly selected
        legacy_policy = import_policy_version(session, DEMO_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                              label="legacy")
        review = session.get(DeepReview, first.review_id)
        legacy_review = DeepReview(
            id=uuid4(), company_id=world.company_id, graph_version_id=review.graph_version_id,
            notice_id=other.notice_id, bundle_id=other.bundle_id, profile_version_id=review.profile_version_id,
            policy_version_id=legacy_policy.id, effective_grade_at_start="unknown", status="completed",
            requested_by_name="담당자",
        )
        session.add(legacy_review)
        session.flush()
        stamp = datetime(2026, 10, 1, tzinfo=UTC)
        legacy_attempt = DeepReviewAttempt(id=uuid4(), deep_review_id=legacy_review.id, sequence=1, status="completed",
                                           lease_fence=0, requested_by_name="담당자", started_at=stamp,
                                           completed_at=stamp + timedelta(minutes=5))
        session.add(legacy_attempt)
        session.commit()
        other_url = f"/api/companies/{world.company_id}/pre-specs/{other.notice_id}/verdict"
        assert client.get(other_url).json()["availability"] == "none"
        legacy = client.get(other_url, params={"attempt_id": str(legacy_attempt.id)}).json()
        assert legacy == {
            "schema_version": "bidops.practitioner-verdict-view.v1", "company_id": str(world.company_id),
            "notice_id": other.notice_id, "attempt_id": str(legacy_attempt.id), "availability": "legacy",
            "is_current": False, "stale_reasons": [], "quality_status": None, "identity": None,
            "source_binding": None, "result": None, "partial_stage_ids": [], "error_code": None,
            "missing_sections": [], "started_at": stamp.isoformat(),
            "finished_at": (stamp + timedelta(minutes=5)).isoformat(), "partial_matrix": [],
            "briefing_item_id": None, "opportunity_id": other.opportunity_id, "rejected_units": [],
        }

        # another notice's attempt, unknown attempt, unknown company/notice → 404; bad query → 422
        assert client.get(other_url, params={"attempt_id": str(first.attempt_id)}).status_code == 404
        assert client.get(company_url(world, seeded), params={"attempt_id": str(uuid4())}).status_code == 404
        missing = client.get(f"/api/companies/{uuid4()}/pre-specs/{seeded.notice_id}/verdict")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
        assert client.get(f"/api/companies/{world.company_id}/pre-specs/999999/verdict").status_code == 404
        assert client.get(company_url(world, seeded), params={"attempt_id": "not-a-uuid"}).status_code == 422
        unknown_opportunity = client.get("/api/opportunities/999999/verdict")
        assert unknown_opportunity.status_code == 404
        assert unknown_opportunity.json()["error"]["code"] == "opportunity_not_found"


def test_t6_opportunity_alias_newest_pre_spec_none_and_merged(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        newer = vt.seed_pre_spec(session, with_bundle=True)
        opportunity = session.get(Opportunity, seeded.opportunity_id)
        # move the second pre-spec onto the same opportunity with a later link time
        session.execute(update(OpportunityLink).where(OpportunityLink.notice_id == newer.notice_id).values(
            opportunity_id=opportunity.id, created_at=datetime.now(UTC) + timedelta(hours=1)))
        session.commit()
        body = client.get(f"/api/opportunities/{opportunity.id}/verdict").json()
        assert (body["notice_id"], body["availability"], body["opportunity_id"]) == (
            newer.notice_id, "none", opportunity.id)

        empty = Opportunity(first_registered_stage="order_plan")
        session.add(empty)
        session.commit()
        none = client.get(f"/api/opportunities/{empty.id}/verdict")
        assert none.status_code == 200
        assert none.json() == {
            "schema_version": "bidops.practitioner-verdict-view.v1", "company_id": str(world.company_id),
            "notice_id": None, "attempt_id": None, "availability": "none", "is_current": False,
            "stale_reasons": [], "quality_status": None, "identity": None, "source_binding": None, "result": None,
            "partial_stage_ids": [], "error_code": None, "missing_sections": [], "started_at": None,
            "finished_at": None, "partial_matrix": [], "briefing_item_id": None, "opportunity_id": empty.id,
            "rejected_units": [],
        }

        merged = Opportunity(first_registered_stage="pre_spec", merged_into_opportunity_id=opportunity.id,
                             merged_at=datetime.now(UTC), merge_reason="중복")
        session.add(merged)
        session.commit()
        assert client.get(f"/api/opportunities/{merged.id}/verdict").json() == body


def test_t6_currentness_bundle_document_and_sw_changes(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        run_completed(session, world, seeded)
        assert client.get(company_url(world, seeded)).json()["is_current"] is True

        notice = session.get(Notice, seeded.notice_id)
        notice.qualification_flags_json = {"sw_business_status": "N"}
        session.commit()
        sw = client.get(company_url(world, seeded)).json()
        # not current, but HP-04 has no SW stale reason value
        assert (sw["availability"], sw["is_current"], sw["stale_reasons"]) == ("completed", False, [])
        notice.qualification_flags_json = {"sw_business_status": "Y"}
        session.commit()

        session.execute(update(DocumentBundle).where(DocumentBundle.id == seeded.bundle_id).values(status="superseded"))
        session.commit()
        stale = client.get(company_url(world, seeded)).json()
        assert (stale["is_current"], stale["stale_reasons"], stale["result"] is not None) == (
            False, ["documents_changed"], True)


def test_t6_manual_request_receipt_replay_codes_and_holdout_release(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch, daily_cap=2)
        client = client_for(session)
        url = f"/api/opportunities/{seeded.opportunity_id}/verdict-requests"
        from app.deep_review.services import verdict_trigger

        verdict_trigger.hold_notices(session, [seeded.notice_id], actor="jechoi")
        session.commit()

        assert client.post(url, json={"request_id": str(uuid4())}).status_code == 400  # actor header
        assert client.post(url, json={"request_id": "x"}, headers=ACTOR).status_code == 422
        assert client.post(url, json={"request_id": str(uuid4()), "extra": 1}, headers=ACTOR).status_code == 422

        request_id = uuid4()
        created = client.post(url, json={"request_id": str(request_id)}, headers=ACTOR)
        assert created.status_code == 202
        receipt = created.json()
        assert set(receipt) == {"request_id", "attempt_id", "status"} and receipt["status"] == "queued"
        assert receipt["request_id"] == str(request_id)
        attempt = session.get(DeepReviewAttempt, UUID(receipt["attempt_id"]))
        assert attempt.status == "queued"
        rows = {row.reason: row for row in session.scalars(select(VerdictRequest)).all()}
        assert (rows["manual"].status, rows["manual"].actor, str(rows["manual"].started_attempt_id)) == (
            "started", "jechoi", receipt["attempt_id"])
        # the manual request released the gold holdout marker (B1)
        assert (rows["gold_holdout"].status, str(rows["gold_holdout"].started_attempt_id)) == (
            "started", receipt["attempt_id"])
        audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "verdict.request.manual"))
        assert (audit.actor_kind, audit.claimed_name, audit.safe_metadata["released_count"]) == ("human", "jechoi", 1)

        assert client.post(url, json={"request_id": str(request_id)}, headers=ACTOR).json() == receipt
        conflict = client.post(url, json={"request_id": str(request_id)},
                               headers={"X-BidOps-Actor-Name": "other-actor"})
        assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "idempotency_conflict")
        busy = client.post(url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert (busy.status_code, busy.json()["error"]["code"]) == (409, "active_attempt_exists")

        cap.run(session, worker(session))
        session.commit()
        again = client.post(url, json={"request_id": str(uuid4())}, headers=ACTOR)  # always a new attempt
        assert again.status_code == 202 and again.json()["attempt_id"] != receipt["attempt_id"]
        cap.run(session, worker(session))
        session.commit()
        capped = client.post(url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert (capped.status_code, capped.json()["error"]["code"]) == (409, "daily_cap_reached")
        assert session.scalar(select(VerdictRequest.id).where(VerdictRequest.status == "queued")) is None

        sw_n = vt.seed_pre_spec(session, sw="N", with_bundle=True)
        active = transfer_policy.active_approval(session)
        transfer_policy.revoke_transfer_policy(session, approval_id=active.id, actor="jechoi", reason="재승인")
        session.commit()
        none_url = f"/api/opportunities/{sw_n.opportunity_id}/verdict-requests"
        unapproved = client.post(none_url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert (unapproved.status_code, unapproved.json()["error"]["code"]) == (409, "policy_not_approved")
        tp.approve(session, daily_cap=10)
        ineligible = client.post(none_url, json={"request_id": str(uuid4())}, headers=ACTOR)
        assert (ineligible.status_code, ineligible.json()["error"]["code"]) == (403, "effective_grade_ineligible")
        missing = client.post("/api/opportunities/999999/verdict-requests", json={"request_id": str(uuid4())},
                              headers=ACTOR)
        assert (missing.status_code, missing.json()["error"]["code"]) == (404, "opportunity_not_found")


def test_t6_feedback_post_is_append_only_and_idempotent(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        started = run_completed(session, world, seeded)
        unit_id = session.get(DeepReviewPreview, started.preview_id).input_snapshot["card_analysis"]["units"][0][
            "unit_id"]
        url = company_url(world, seeded, "verdict-feedback")
        body = {"attempt_id": str(started.attempt_id), "kind": "not_requirement", "unit_id": unit_id,
                "note": "요구사항이 아닌 안내 문장", "request_id": str(uuid4())}

        created = client.post(url, json=body, headers=ACTOR)
        assert created.status_code == 201 and set(created.json()) == {"feedback_id"}
        row = session.get(VerdictFeedback, UUID(created.json()["feedback_id"]))
        assert (row.kind, row.unit_id, row.actor, row.attempt_id) == ("not_requirement", unit_id, "jechoi",
                                                                      started.attempt_id)
        assert client.post(url, json=body, headers=ACTOR).json() == created.json()
        changed = client.post(url, json={**body, "kind": "source_mismatch"}, headers=ACTOR)
        assert (changed.status_code, changed.json()["error"]["code"]) == (409, "idempotency_conflict")
        assert client.post(url, json={**body, "request_id": str(uuid4()), "unit_id": "card:nope"},
                           headers=ACTOR).status_code == 422
        assert client.post(url, json={**body, "request_id": str(uuid4()), "note": "x" * 501},
                           headers=ACTOR).status_code == 422
        assert client.post(url, json={**body, "request_id": str(uuid4()), "attempt_id": str(uuid4())},
                           headers=ACTOR).status_code == 404
        assert client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 400
        minimal = client.post(url, json={"attempt_id": str(started.attempt_id), "kind": "wrong_verdict",
                                         "request_id": str(uuid4())}, headers=ACTOR)
        assert minimal.status_code == 201
        assert len(session.scalars(select(VerdictFeedback)).all()) == 2


def test_t6_transfer_policy_read_and_middleware_guard(flow_engine, monkeypatch, client_for) -> None:
    with Session(flow_engine) as session:
        world, seeded, item = started_world(session, monkeypatch)
        client = client_for(session)
        start(session, world, seeded)

        policy = client.get("/api/analysis/transfer-policy")
        assert policy.status_code == 200
        active = transfer_policy.active_approval(session)
        # 결정 B17: the started attempt is queued and has not transmitted, so today_used is 0.
        assert policy.json() == {
            "schema_version": "bidops.transfer-policy.v1",
            "active": {
                "approval_id": str(active.id), "policy_identity": "analysis-policy-luna-rl-v1",
                "policy_sha256": active.policy_sha256, "daily_cap": 10,
                "approved_at": policy.json()["active"]["approved_at"], "approved_by": "jechoi", "today_used": 0,
            },
        }
        datetime.fromisoformat(policy.json()["active"]["approved_at"].replace("Z", "+00:00"))

        # RL on (demo off): verdict paths open, the other company paths stay hidden
        assert client.get(company_url(world, seeded)).status_code == 200
        assert client.get(f"/api/companies/{world.company_id}/pre-specs").status_code == 404
        assert client.post(f"/api/companies/{world.company_id}/pre-specs/{seeded.notice_id}/deep-review-previews",
                           json={"bundle_id": str(seeded.bundle_id)}).status_code == 404

        # RL off: every RL path looks absent (route-level 404 before the service)
        tp.configure(monkeypatch, BIDOPS_RL_ANALYSIS_ENABLED="false",
                     BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(world.policy_id))
        for method, path in (
            ("GET", company_url(world, seeded)),
            ("POST", company_url(world, seeded, "verdict-feedback")),
            ("GET", f"/api/opportunities/{seeded.opportunity_id}/verdict"),
            ("POST", f"/api/opportunities/{seeded.opportunity_id}/verdict-requests"),
            ("GET", "/api/analysis/transfer-policy"),
        ):
            response = client.request(method, path, json={"request_id": str(uuid4())}, headers=ACTOR)
            assert (response.status_code, response.json()) == (404, {"detail": "Not Found"}), path
        # other opportunity routes are unaffected
        assert client.get(f"/api/opportunities/{seeded.opportunity_id}").status_code == 200


# --- 결정 B55 (T20): synthesis-only resume through the manual request ----------------------


def test_b55_manual_request_resume_option_receipt_replay_and_codes(flow_engine, monkeypatch, client_for) -> None:
    from app.deep_review.services.input_versions import RL_LUNA_POLICY_FILE_V8

    with Session(flow_engine) as session:
        tp.configure(monkeypatch, BIDOPS_RL_ANALYSIS_POLICY_PATH=str(RL_LUNA_POLICY_FILE_V8))
        imported = tp._import_rootlab(session)
        v8 = import_policy_version(session, RL_LUNA_POLICY_FILE_V8, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-rl-v8")
        session.commit()
        tp.configure(monkeypatch, BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID=str(v8.id),
                     BIDOPS_RL_ANALYSIS_POLICY_PATH=str(RL_LUNA_POLICY_FILE_V8))
        tp.approve(session, policy_identity="analysis-policy-luna-rl-v8")
        seeded = vt.seed_pre_spec(session, with_bundle=True)
        source = cdr.start_rl_verdict(tp.service(), session, company_id=imported.company_id,
                                      notice_id=seeded.notice_id, bundle_id=seeded.bundle_id)
        session.commit()
        failure = cap.SchemaFailure()
        assert cap.run_code(session, worker(session, {("synthesis", 0): failure, ("synthesis", 1): failure})) == (
            "card_synthesis_invalid")
        session.commit()
        cap._select_policy(session, monkeypatch, cap.RL_V9)
        client = client_for(session)
        url = f"/api/opportunities/{seeded.opportunity_id}/verdict-requests"

        assert client.post(url, json={"request_id": str(uuid4()), "resume_from_attempt_id": "x"},
                           headers=ACTOR).status_code == 422
        attempts_before = session.scalar(select(func.count()).select_from(DeepReviewAttempt))
        invalid = client.post(url, json={"request_id": str(uuid4()), "resume_from_attempt_id": str(uuid4())},
                              headers=ACTOR)
        assert (invalid.status_code, invalid.json()["error"]["code"]) == (409, "resume_source_invalid")
        assert session.scalar(select(func.count()).select_from(DeepReviewAttempt)) == attempts_before

        request_id = uuid4()
        body = {"request_id": str(request_id), "resume_from_attempt_id": str(source.attempt_id)}
        created = client.post(url, json=body, headers=ACTOR)
        assert created.status_code == 202
        receipt = created.json()
        assert set(receipt) == {"request_id", "attempt_id", "status"} and receipt["status"] == "queued"
        assert client.post(url, json=body, headers=ACTOR).json() == receipt  # replay
        conflict = client.post(url, json={"request_id": str(request_id)}, headers=ACTOR)  # same id, no resume
        assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "idempotency_conflict")
        manual = session.scalar(select(AuditEvent).where(AuditEvent.action == "verdict.request.manual"))
        assert manual.safe_metadata["resume_from_attempt_id"] == str(source.attempt_id)
        link = session.scalars(select(AuditEvent).where(AuditEvent.action == "card.resume.requested")).all()
        assert [(row.aggregate_id, row.safe_metadata["source_attempt_id"]) for row in link] == [
            (receipt["attempt_id"], str(source.attempt_id))]

        fake_worker = worker(session)
        cap.run(session, fake_worker)
        session.commit()
        assert session.get(DeepReviewAttempt, UUID(receipt["attempt_id"])).status == "completed"
        assert fake_worker._client.calls == [("card-synthesis-v2", "synthesis", False)]
        view = client.get(f"/api/opportunities/{seeded.opportunity_id}/verdict").json()
        assert view["availability"] == "completed" and view["attempt_id"] == receipt["attempt_id"]
        assert all(set(row) == {"unit_id", "owner", "action", "evidence_refs", "origin"}
                   for row in view["result"]["next_actions"])
        # the completed resume is no source for another resume
        again = client.post(url, json={"request_id": str(uuid4()), "resume_from_attempt_id": receipt["attempt_id"]},
                            headers=ACTOR)
        assert (again.status_code, again.json()["error"]["code"]) == (409, "resume_source_invalid")
