"""DEMO-03 STEP-006 cross-path integration with a fake Luna runner (spec T2~T8).

A company deep review now runs through the existing shared analysis slot:
preview → approval/create → ``claim_next_job`` → three stages through the real
``LunaClient`` over an ``httpx.MockTransport`` that implements the internal
codex-runner wire contract (``POST /calls`` → ``GET /calls/{id}`` →
``DELETE``) → materialized report → company report/detail/evidence/comparison
reads.  The fake runner answers from the prompt alone and cites only the
supplied source units and profile evidence, so every deterministic validator
runs unchanged.  STEP-007's real run replaces only the transport.

No network, no real model: the Luna transport is the in-process fake, the fit
transport is the existing fake LiteLLM.  PostgreSQL variants run with
``BIDOPS_TEST_POSTGRES_URL`` (disposable postgres:17.11).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
from threading import Barrier
import time
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import get_db
from app.core.model_client import ModelClient
from app.core.models import AuditEvent
from app.deep_review.models import (
    ContentObject,
    ContentScan,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DeepReviewStage,
    DocumentBlock,
    DocumentBundle,
    DocumentBundleItem,
    DocumentStructure,
    DocumentVersion,
    EvidenceRef,
    PreSpecCompanyFitAttempt,
    ReportRevision,
    ValidationRun,
    WorkJob,
)
from app.deep_review.services import company_fit as fit
from app.deep_review.services import company_fit_runner as fit_worker
from app.deep_review.services import company_projection as projection
from app.deep_review.services.deep_reviews import DeepReviewService, DeepReviewServiceError
from app.deep_review.services.evidence import EvidenceService
from app.deep_review.services.input_versions import (
    CANONICAL_POLICY_FILE,
    HP_LUNA_POLICY_FILE,
    import_policy_version,
)
from app.deep_review.services.luna_client import LunaClient
from app.deep_review.services.luna_identity import CLI_VERSION
from app.deep_review.services.reports import ReportService
from app.deep_review.workers.deep_review import run_once as run_deep_review_once
from tests.app.test_company_analysis import FakeLiteLLM, valid_payload
from tests.app.test_company_deep_review_binding import (
    TEXTS,
    DeepWorld,
    _sqlite_engine,
    create,
    deep_configure,
    preview,
    retry,
    structure_loader,
)
from tests.app.test_company_reads import add_document
from tests.app.test_deep_reviews import _FixtureStore
from tests.deep_review.test_company_fit import _FakeStore
from tests.deep_review.test_company_fit_enqueue import (  # noqa: F401 - shared fixtures
    build_world,
    import_company,
    object_store,
    store_structure,
)
from tests.postgres import migrated_engine, requires_postgres


STAGE_NAMES = ("requirements_and_evaluation", "delivery_risk_economics", "synthesis_and_validation")


@pytest.fixture
def sqlite_engine():
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request):
    if request.param == "postgres":
        with migrated_engine() as bind:
            yield bind
        return
    bind = _sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


@pytest.fixture(autouse=True)
def _clear_settings():
    yield
    get_settings.cache_clear()


# --- fake Luna runner (internal codex-runner wire contract) -----------------------------


class FakeLunaRunner:
    """``httpx`` handler for ``LunaClient``: the codex-runner contract, answered offline.

    Wire contract (``LunaClient.invoke_prompt``): ``POST /calls {"prompt"}`` →
    202 ``{"call_id"}``; ``GET /calls/{id}`` → ``{"status": "completed",
    "raw_response", "cli_version": "0.162.1", "input_sha256": sha256(prompt),
    "latency_ms"}``; ``DELETE /calls/{id}``.  The answer is a
    ``bidops.deep-review-stage.v2`` payload built only from the prompt: one
    document claim per supplied unit (quote = the unit text, locator copied),
    a company-basis claim citing the first supplied profile evidence row
    exactly, and the synthesis claims over the supplied verified claims.
    ``mutate(stage, prompt, output, call_number)`` may replace the output to
    simulate a bad model answer.  ``prompts`` keeps every parsed prompt.
    """

    def __init__(self, mutate=None) -> None:
        self.mutate = mutate
        self.prompts: list[dict] = []
        self.raw_prompts: list[str] = []
        self.results: dict[str, dict] = {}
        self.deleted: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/calls"
            prompt = json.loads(request.content)["prompt"]
            payload = json.loads(prompt)
            self.prompts.append(payload)
            self.raw_prompts.append(prompt)
            output = stage_output(payload)
            if self.mutate is not None:
                output = self.mutate(payload["stage"], payload, output, len(self.prompts))
            call_id = str(uuid4())
            self.results[call_id] = {
                "status": "completed", "raw_response": json.dumps(output, ensure_ascii=False),
                "cli_version": CLI_VERSION, "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "latency_ms": 1,
            }
            return httpx.Response(202, json={"call_id": call_id})
        call_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=self.results[call_id])
        self.deleted.append(call_id)
        return httpx.Response(200, json={})

    def stage_prompts(self, stage: str) -> list[dict]:
        return [row for row in self.prompts if row["stage"] == stage]


def stage_output(prompt: dict) -> dict:
    stage = prompt["stage"]
    slice_ = prompt["input_slice"]
    units = slice_.get("requirements", [])
    unit_ids = [unit["requirement_id"] for unit in units]
    requirement_ids = sorted({rid for unit in units for rid in unit["document_requirement_ids"]})
    prior_ids = [row["claim_id"] for row in slice_.get("verified_claims", [])]
    prior_refs = [row["evidence_id"] for row in slice_.get("prior_evidence", [])]
    claims: list[dict] = []
    evidence: list[dict] = []

    def claim(section, role, body, *, kind="opinion", evidence_ids=(), title="판단 근거", key=False,
              related=True) -> None:
        claims.append({
            "claim_id": str(uuid4()), "category": title, "claim_type": kind, "body": body,
            "status": "unknown" if kind == "unknown" else "supported", "formula": None,
            "premise_claim_ids": prior_ids if kind == "inference" else [],
            "reason": None if kind == "fact" else "제공된 원문과 회사 근거 범위에서만 판단했습니다.",
            "evidence_ids": list(evidence_ids), "report_section": section, "narrative_role": role,
            "topic_key": "company-demo", "source_unit_ids": unit_ids, "requirement_ids": requirement_ids,
            "related_claim_ids": prior_ids if related else [], "is_key_point": key,
        })

    if stage == STAGE_NAMES[0]:
        for unit in units:
            eid = str(uuid4())
            evidence.append({
                "evidence_id": eid, "source_kind": "document", "document_version_id": unit["document_version_id"],
                "structure_id": unit["structure_id"], "profile_version_id": None, "profile_evidence_id": None,
                "locator_type": unit["locator_type"], "locator": dict(unit["locator"]), "quote": unit["text"],
                "confidence": None, "source_sha256": unit["source_sha256"],
            })
            claim("scope", "source", unit["text"], kind="fact", evidence_ids=[eid], title="과업 원문")
    elif stage == STAGE_NAMES[1]:
        claim("delivery", "impact", "원문 과업을 수행하려면 착수 전에 수행 범위와 검수 기준을 확인해야 한다.",
              kind="inference", evidence_ids=prior_refs, key=True, title="수행 조건")
        supplied = (prompt.get("fixed_profile_slice") or {}).get("evidence") or []
        if supplied:
            row = supplied[0]
            eid = str(uuid4())
            evidence.append({
                "evidence_id": eid, "source_kind": "profile", "document_version_id": None, "structure_id": None,
                "profile_version_id": row["profile_version_id"], "profile_evidence_id": row["profile_evidence_id"],
                "locator_type": "profile_fact", "locator": dict(row["locator"]), "quote": row["quote"],
                "confidence": None, "source_sha256": row["source_sha256"],
            })
            claim("company_fit", "company_basis", "가상 회사 프로필에 이 요구와 연결되는 기록이 있다.",
                  kind="fact", evidence_ids=[eid], title="회사 근거", related=False)
    else:
        if slice_["synthesis_phase"] == "global":
            claim("assessment", "recommendation", "조건부 추진 검토", evidence_ids=prior_refs, key=True,
                  title="system_recommendation")
        else:
            claim("assessment", "synthesis", "원문 과업과 회사 근거를 대조한 결과 착수 전 확인할 조건이 남아 있다.",
                  evidence_ids=prior_refs, key=True, title="먼저 확인할 판단 조건")
    return {
        "schema": "bidops.deep-review-stage.v2", "deep_review_id": slice_["deep_review_id"],
        "attempt_id": slice_["attempt_id"], "stage": stage, "claims": claims, "evidence": evidence,
        "unknowns": ["회사 실적의 세부 범위는 추가 확인이 필요합니다."], "warnings": [],
        "coverage": [{"source_unit_id": uid, "status": "reviewed", "claim_ids": [row["claim_id"] for row in claims],
                      "reason": None} for uid in unit_ids] if stage != STAGE_NAMES[2] else [],
        "considered_claim_ids": prior_ids if stage == STAGE_NAMES[2] else [],
    }


def luna_service(runner: FakeLunaRunner, **kwargs) -> DeepReviewService:
    client = LunaClient("http://codex-runner:8091", lambda: None, time.monotonic() + 600,
                        transport=httpx.MockTransport(runner))
    return DeepReviewService(client=client, structure_loader=structure_loader,
                             raw_response_store=kwargs.pop("store", _FixtureStore()), **kwargs)


# --- world -----------------------------------------------------------------------------------


def ready_bundle_with_blocks(session: Session, notice_id: int, document_ids, *, revision: int = 1) -> UUID:
    """A ready bundle over the documents; each has a pinned structure and DB blocks (= TEXTS).

    The structure payload is stored for real (``store_structure``) so the company
    fit reads it through the production loader; the deep service's injected
    ``structure_loader`` returns the same payload.
    """

    bundle = DocumentBundle(id=uuid4(), notice_id=notice_id, revision=revision, version=1, status="ready",
                            issues_snapshot=[], created_by_name="준비 담당자", confirmed_by_name="준비 담당자",
                            confirmed_at=datetime.now(UTC))
    session.add(bundle)
    session.flush()
    for ordinal, document_id in enumerate(document_ids):
        document = session.get(DocumentVersion, document_id)
        content = session.get(ContentObject, document.content_object_id)
        structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
        if structure is None:
            structure = store_structure(session, document, TEXTS)
            for page, body in TEXTS.items():
                session.add(DocumentBlock(structure_id=structure.id, block_key=f"source-{page}", page=page,
                                          block_type="paragraph", content=body, attributes={}))
        if session.scalar(select(ContentScan.id).where(ContentScan.content_object_id == content.id)) is None:
            session.add(ContentScan(content_object_id=content.id, scanner="fixture", scanner_version="1",
                                    status="clean", safe_result={}))
        session.add(DocumentBundleItem(
            bundle_id=bundle.id, document_version_id=document.id, ordinal=ordinal, document_version_version=1,
            content_object_id=content.id, content_sha256=content.sha256, detected_mime="application/pdf",
            size_bytes=10, original_filename=document.original_filename, source_kind="manual",
            role_at_confirmation=document.role, is_current_at_confirmation=True,
            safety_status_at_confirmation="safe", structure_id_at_confirmation=structure.id,
            structure_payload_sha256=structure.payload_sha256,
        ))
    session.flush()
    return bundle.id


@dataclass(frozen=True)
class E2EWorld:
    deep: DeepWorld
    document_ids: tuple[UUID, ...]

    @property
    def company_id(self) -> UUID:
        return self.deep.company_id


def e2e_world(session: Session, monkeypatch, *, documents: int = 1) -> E2EWorld:
    base = build_world(session, monkeypatch, bundle=False)
    document_ids = [base.document_id] + [add_document(session, base.notice_id).id for _ in range(documents - 1)]
    bundle_id = ready_bundle_with_blocks(session, base.notice_id, document_ids)
    policy = import_policy_version(session, HP_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-hp-v1")
    session.commit()
    deep = DeepWorld(fit=base, company_id=base.company_id, notice_id=base.notice_id, bundle_id=bundle_id,
                     policy_id=policy.id, graph_version_id=base.graph_version_id,
                     profile_version_id=base.profile_version_id)
    deep_configure(monkeypatch, deep)
    return E2EWorld(deep=deep, document_ids=tuple(document_ids))


def queue_review(session: Session, svc: DeepReviewService, world: E2EWorld) -> tuple[dict, dict]:
    frozen = preview(session, svc, world.deep)
    return frozen, create(session, svc, world.deep, frozen["preview_id"])


def attempt_of(session: Session, review_id) -> DeepReviewAttempt:
    review = session.get(DeepReview, UUID(str(review_id)))
    return session.get(DeepReviewAttempt, review.current_attempt_id)


def job_of(session: Session, review_id) -> WorkJob:
    return session.get(WorkJob, attempt_of(session, review_id).work_job_id)


def count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _tamper(session: Session, statement: str, **params) -> None:
    session.execute(text(statement), params)
    session.commit()
    session.expire_all()


def _sensitive_strings(frozen_input: dict) -> list[str]:
    quotes = [fact["quote"] for fact in frozen_input["profile_facts"] if len(fact["quote"]) >= 6]
    return [*TEXTS.values(), *quotes[:5]]


# --- T4: company deep review end to end through the shared slot --------------------------------


def test_t4_company_deep_review_runs_end_to_end_through_the_shared_slot(engine, monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with Session(engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner()
        store = _FixtureStore()
        svc = luna_service(runner, store=store)
        frozen, created = queue_review(session, svc, world)
        review_id = UUID(created["id"])
        approved = session.get(DeepReviewPreview, UUID(frozen["preview_id"]))
        approved_input, approved_provenance = deepcopy(approved.input_snapshot), deepcopy(approved.provenance_jsonb)

        result = run_deep_review_once(session, "company-e2e-worker", service=svc)
        assert result.claimed and result.status == "completed"
        session.expire_all()
        review = session.get(DeepReview, review_id)
        attempt = attempt_of(session, review_id)
        assert review.status == attempt.status == job_of(session, review_id).status == "completed"
        stages = session.scalars(select(DeepReviewStage).where(DeepReviewStage.attempt_id == attempt.id)
                                 .order_by(DeepReviewStage.sequence)).all()
        assert [(row.stage, row.status) for row in stages] == [(name, "completed") for name in STAGE_NAMES]
        assert all(row.raw_response_content_object_id is not None for row in stages)
        # The approved frozen input was used as is and never changed.
        assert approved.input_snapshot == approved_input and approved.provenance_jsonb == approved_provenance

        # Every prompt carries only the frozen input: units, paths, profile evidence.
        units = {unit["requirement_id"]: unit for row in approved_input["requirements"] for unit in row["source_units"]}
        first = runner.stage_prompts(STAGE_NAMES[0])
        assert sorted(unit["requirement_id"] for row in first for unit in row["input_slice"]["requirements"]) == sorted(units)
        assert all("graph_paths" not in row["input_slice"] and "fixed_profile_slice" not in row for row in first)
        second = runner.stage_prompts(STAGE_NAMES[1])
        assert {unit["requirement_id"] for row in second for unit in row["input_slice"]["requirements"]} == set(units)
        frozen_evidence = {row["profile_evidence_id"]: row for row in approved_input["profile_evidence"]}
        for prompt in second:
            assert prompt["input_slice"]["company_requirements"] and "graph_paths" in prompt["input_slice"]
            fixed = prompt["fixed_profile_slice"]
            assert fixed["profile_version_id"] == str(world.deep.profile_version_id)
            assert all(frozen_evidence[row["profile_evidence_id"]] == row for row in fixed["evidence"])
            shown = [(path["requirement_id"], path["node_ids"]) for path in prompt["input_slice"]["graph_paths"]]
            frozen_paths = [(path["requirement_id"], path["node_ids"]) for path in approved_input["graph_paths"]]
            assert all(item in frozen_paths for item in shown)
        third = runner.stage_prompts(STAGE_NAMES[2])
        assert third[-1]["input_slice"]["synthesis_phase"] == "global"
        assert len(runner.deleted) == len(runner.prompts)

        # Report, evidence and company identity.
        reports = ReportService()
        wrapper = projection.company_report(reports, session, company_id=world.company_id, review_id=review_id)
        assert (wrapper["company_id"], wrapper["graph_version_id"], wrapper["profile_version_id"]) == (
            str(world.company_id), str(world.deep.graph_version_id), str(world.deep.profile_version_id))
        assert wrapper["graph_sha256"] == approved_input["graph_sha256"]
        assert wrapper["ontology_version"] == approved_input["ontology_version"]
        report = wrapper["view"]["report"]
        assert report["schema"] == "bidops.deep-review-report.v2"
        assert report["quality_status"] == "unmeasured_reference"
        assert report["validation_summary"]["status"] == "passed"
        assert report["policy_version_id"] == str(world.deep.policy_id)
        assert wrapper["view"]["validation"]["status"] == "passed"
        company_claims = [row for row in report["claims"] if row["report_section"] == "company_fit"]
        assert company_claims
        refs = session.scalars(select(EvidenceRef).where(EvidenceRef.deep_review_id == review_id)).all()
        profile_refs = [row for row in refs if row.source_kind == "profile"]
        document_refs = [row for row in refs if row.source_kind == "document"]
        assert profile_refs and document_refs
        # Lineage of report/evidence rows: EvidenceRef.deep_review_id → the company review;
        # profile rows pin the review's company profile and frozen evidence ids,
        # document rows the review's bundle and its frozen documents.
        for row in profile_refs:
            assert row.profile_version_id == world.deep.profile_version_id
            assert str(row.profile_evidence_id) in frozen_evidence
            assert row.quote == frozen_evidence[str(row.profile_evidence_id)]["quote"]
        for row in document_refs:
            assert row.bundle_id == world.deep.bundle_id
            assert str(row.document_version_id) in approved_input["document_version_ids"]
            assert row.quote in TEXTS.values()
        evidence_service = EvidenceService()
        profile_view = projection.company_evidence(evidence_service, session, company_id=world.company_id,
                                                   review_id=review_id, evidence_id=profile_refs[0].id)
        assert profile_view["source_kind"] == "profile"
        assert profile_view["profile_version_id"] == str(world.deep.profile_version_id)
        from app.deep_review.schemas.document_bundles import DocumentStructure as StructureSchema
        monkeypatch.setattr(evidence_service.document_service, "get_structure", lambda s, sid: StructureSchema.model_validate(
            structure_loader(s, s.get(DocumentStructure, sid))))
        document_view = projection.company_evidence(evidence_service, session, company_id=world.company_id,
                                                    review_id=review_id, evidence_id=document_refs[0].id)
        assert document_view["quote"] == document_refs[0].quote

        detail = projection.company_review_detail(svc, session, company_id=world.company_id, review_id=review_id)
        assert detail["status"] == "completed" and detail["is_current"] is True
        assert detail["current_attempt"]["id"] == str(attempt.id)
        assert detail["current_attempt"]["preview_id"] == frozen["preview_id"]
        assert detail["provenance"] == json.loads(json.dumps(approved_provenance))
        assert detail["input_sha256"] == frozen["input_sha256"] == detail["provenance"]["input_sha256"]
        assert detail["quality_status"] == "unmeasured_reference"
        comparison = projection.company_comparison(session, notice_id=world.deep.notice_id)
        item = next(row for row in comparison["items"] if row["company"]["company_id"] == str(world.company_id))
        assert item["review"] == {"review_id": str(review_id), "status": "completed", "is_current": True}
        assert item["graph_version_id"] == str(world.deep.graph_version_id)
        assert item["comparison_status"] == "missing"  # no company fit yet

        # The worker audit and logs carry identities only, never model input or profile text.
        audits = session.scalars(select(AuditEvent).where(AuditEvent.action.like("deep_review.job.%"))).all()
        body = json.dumps([row.safe_metadata for row in audits], ensure_ascii=False)
        for value in _sensitive_strings(approved_input):
            assert value not in body
            assert value not in caplog.text
        assert not run_deep_review_once(session, "company-e2e-worker", service=svc).claimed


def test_t4_fit_and_review_of_a_multi_document_notice_are_comparable(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = e2e_world(session, monkeypatch, documents=2)
        expected = sorted(str(value) for value in world.document_ids)
        # Company fit (LiteLLM fake): enqueue freezes the notice's whole current document set.
        litellm = FakeLiteLLM()
        real = ModelClient.for_purpose.__func__

        def for_purpose(cls, purpose, **kwargs):
            assert purpose == "overview"
            return real(cls, purpose, completion_create=litellm.create, models_list=litellm.models,
                        model_info_list=litellm.model_info, **kwargs)

        monkeypatch.setattr(ModelClient, "for_purpose", classmethod(for_purpose))
        queued = fit.enqueue_company_fit(session, company_id=world.company_id, notice_id=world.deep.notice_id,
                                         actor="핏 담당자")
        session.commit()
        attempt = session.get(PreSpecCompanyFitAttempt, queued.attempt_id)
        assert attempt.input_jsonb["document_version_ids"] == expected
        assert [row["document_version_id"] for row in attempt.provenance_jsonb["documents"]] == expected
        assert attempt.document_version_id == world.deep.fit.document_id and attempt.provenance_jsonb["bundle_id"] is None
        litellm.responses.append(valid_payload(attempt.input_jsonb))
        assert fit_worker.PreSpecCompanyFitRunner(raw_response_store=_FakeStore()).run_once(session, "fit-worker")
        session.expire_all()
        assert session.get(PreSpecCompanyFitAttempt, queued.attempt_id).status == "completed"
        assert litellm.requests and len(litellm.requests) == 1
        # Company deep review (Luna fake) over the same ready bundle.
        runner = FakeLunaRunner()
        svc = luna_service(runner)
        frozen, created = queue_review(session, svc, world)
        assert frozen["input"]["document_version_ids"] == [str(value) for value in world.document_ids]
        assert run_deep_review_once(session, "company-e2e-worker", service=svc).claimed
        session.expire_all()
        assert session.get(DeepReview, UUID(created["id"])).status == "completed"
        units = {unit["document_version_id"] for row in frozen["input"]["requirements"] for unit in row["source_units"]}
        assert units == set(expected)
        # STEP-008 (§9, 2026-10-11): the fit's overview rows carry the very splitter units of
        # the deep preview (v3 source_characters = demo Luna source_characters), limited to
        # the overview document and each row's evidence pages.
        fitted = session.get(PreSpecCompanyFitAttempt, queued.attempt_id).input_jsonb
        deep_units = {unit["requirement_id"]: unit for row in frozen["input"]["requirements"]
                      for unit in row["source_units"]}
        fit_units = [unit for row in fitted["requirements"] for unit in row["source_units"]]
        assert len(fit_units) == len(TEXTS)
        assert all(deep_units[unit["requirement_id"]] == unit for unit in fit_units)
        assert {unit["document_version_id"] for unit in fit_units} == {str(world.deep.fit.document_id)}

        comparison = projection.company_comparison(session, notice_id=world.deep.notice_id)
        assert comparison["document_version_ids"] == expected
        item = next(row for row in comparison["items"] if row["company"]["company_id"] == str(world.company_id))
        assert item["comparison_status"] == "comparable"
        assert item["fit"]["status"] == "completed" and item["fit"]["is_current"] is True
        assert item["review"]["status"] == "completed" and item["review"]["is_current"] is True
        fits = projection.company_fit_attempts(session, company_id=world.company_id, notice_id=world.deep.notice_id)
        review = projection.company_review_detail(svc, session, company_id=world.company_id, review_id=UUID(created["id"]))
        assert [row["document_version_id"] for row in fits["attempts"][0]["provenance"]["documents"]] == expected
        assert [row["document_version_id"] for row in review["provenance"]["documents"]] == expected
        assert fits["attempts"][0]["provenance"]["bundle_id"] is None
        assert review["provenance"]["bundle_id"] == str(world.deep.bundle_id)
        for key in ("company_id", "profile_version_id", "graph_version_id", "graph_sha256", "ontology_version",
                    "ontology_sha256", "overview_run_id", "overview_sha256"):
            assert fits["attempts"][0]["provenance"][key] == review["provenance"][key], key
        # A new document set makes both executions a different input.
        extra = add_document(session, world.deep.notice_id)
        session.get(DocumentBundle, world.deep.bundle_id).status = "superseded"
        session.commit()
        ready_bundle_with_blocks(session, world.deep.notice_id, [*world.document_ids, extra.id], revision=2)
        session.commit()
        item = next(row for row in projection.company_comparison(session, notice_id=world.deep.notice_id)["items"]
                    if row["company"]["company_id"] == str(world.company_id))
        assert item["comparison_status"] == "different_input"
        assert item["fit"]["is_current"] is False and item["review"]["is_current"] is False


def test_b2_fit_freezes_the_ready_bundle_document_set_and_requires_the_overview_document(sqlite_engine, monkeypatch) -> None:
    """Fit provenance documents = the latest ready bundle's set (§9, 2026-10-11: bundle required).

    Before STEP-008 a notice without a ready bundle fell back to its
    ``is_current`` documents; the amended contract removes that fallback.
    """

    with Session(sqlite_engine) as session:
        base = build_world(session, monkeypatch, bundle=False)
        extra = add_document(session, base.notice_id)
        both = sorted([str(base.document_id), str(extra.id)])
        # No ready bundle: fail closed before any write (no current-document fallback).
        before = count(session, PreSpecCompanyFitAttempt)
        with pytest.raises(fit.CompanyFitGateError) as error:
            fit.enqueue_company_fit(session, company_id=base.company_id, notice_id=base.notice_id, actor="핏 담당자")
        assert error.value.code == "bundle_not_ready"
        session.rollback()
        assert count(session, PreSpecCompanyFitAttempt) == before
        # A ready bundle over both documents is the frozen set.
        ready_bundle_with_blocks(session, base.notice_id, [base.document_id, extra.id])
        session.commit()
        first = fit.enqueue_company_fit(session, company_id=base.company_id, notice_id=base.notice_id, actor="핏 담당자")
        session.commit()
        row = session.get(PreSpecCompanyFitAttempt, first.attempt_id)
        assert row.input_jsonb["document_version_ids"] == both
        assert [item["document_version_id"] for item in row.provenance_jsonb["documents"]] == both
        assert row.document_version_id == base.document_id  # the overview's document column is unchanged
        assert fit.company_current_flags(session, [row]) == {row.id: True}
        # Only the overview document's units are linked to overview rows.
        linked = {unit["document_version_id"] for item in row.input_jsonb["requirements"] for unit in item["source_units"]}
        assert linked == {str(base.document_id)}
        # A newer ready bundle with another set makes the frozen fit stale (old row unchanged).
        bundle_id = ready_bundle_with_blocks(session, base.notice_id, [base.document_id], revision=2)
        session.commit()
        assert fit.company_current_flags(session, [row]) == {row.id: False}
        row.status, row.error_code, row.completed_at = "failed", "company_fit_execution_failed", datetime.now(UTC)
        session.commit()
        second = fit.enqueue_company_fit(session, company_id=base.company_id, notice_id=base.notice_id, actor="핏 담당자")
        session.commit()
        fresh = session.get(PreSpecCompanyFitAttempt, second.attempt_id)
        assert fresh.input_jsonb["document_version_ids"] == [str(base.document_id)]
        assert fit.company_current_flags(session, [fresh]) == {fresh.id: True}
        # The overview's document must belong to the frozen set.
        fresh.status, fresh.completed_at = "failed", datetime.now(UTC)
        session.get(DocumentBundle, bundle_id).status = "superseded"
        session.commit()
        ready_bundle_with_blocks(session, base.notice_id, [extra.id], revision=3)
        session.commit()
        before = count(session, PreSpecCompanyFitAttempt)
        with pytest.raises(fit.CompanyFitGateError) as error:
            fit.enqueue_company_fit(session, company_id=base.company_id, notice_id=base.notice_id, actor="핏 담당자")
        assert error.value.code == "company_input_invalid"
        session.rollback()
        assert count(session, PreSpecCompanyFitAttempt) == before


def test_d_shared_analysis_worker_entry_point_runs_the_company_deep_review(sqlite_engine, monkeypatch) -> None:
    """``python -m app.workers.analysis`` slot order: C-2 → deep review (company too) → … ."""

    from types import SimpleNamespace

    from app.deep_review.workers import deep_review as deep_review_worker
    from app.workers import analysis

    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner()
        svc = luna_service(runner)
        _frozen, created = queue_review(session, svc, world)
    calls = {"c2": 0, "fit": 0, "assumption": 0, "overview": 0}

    class _C2:
        def __init__(self, **_kwargs):
            pass

        def run_once(self, _session):
            calls["c2"] += 1
            return None

    class _Fit:
        def __init__(self, **_kwargs):
            pass

        def run_once(self, _session, _worker_id):
            calls["fit"] += 1
            return False

    def _never(name):
        def call(*_args, **_kwargs):
            calls[name] += 1
            return SimpleNamespace(claimed=False, identity_error=None)
        return call

    monkeypatch.setattr(analysis, "SessionLocal", sessionmaker(bind=sqlite_engine))
    monkeypatch.setattr(analysis, "configure", lambda _settings: None)
    monkeypatch.setattr(analysis, "assert_object_store_runtime", lambda **_kwargs: None)
    monkeypatch.setattr(analysis, "C2ScreeningWorker", _C2)
    monkeypatch.setattr(analysis, "PreSpecCompanyFitRunner", _Fit)
    monkeypatch.setattr(analysis, "run_assumption_analysis_once", _never("assumption"))
    monkeypatch.setattr(analysis, "run_prespec_overview_once", _never("overview"))
    # The real slot function builds its own service; only the transport is the fake.
    monkeypatch.setattr(deep_review_worker, "DeepReviewService", lambda: svc)
    monkeypatch.setattr("sys.argv", ["analysis", "--once"])
    analysis.main()
    assert calls == {"c2": 1, "fit": 0, "assumption": 0, "overview": 0}
    with Session(sqlite_engine) as session:
        assert session.get(DeepReview, UUID(created["id"])).status == "completed"
    assert {row["stage"] for row in runner.prompts} == set(STAGE_NAMES)


# --- T8: approval, scope and slot guards before any model call ---------------------------------


def _no_report(session: Session, review_id) -> None:
    assert session.scalar(select(func.count()).select_from(ReportRevision).where(
        ReportRevision.deep_review_id == UUID(str(review_id)))) == 0


@pytest.mark.parametrize("change", [
    "preview_hash", "approval_missing", "approval_foreign_company", "creation_audit", "approval_audit",
    "source_text", "frozen_unit",
])
def test_t8_invalid_approval_fails_closed_with_zero_transport_calls(sqlite_engine, monkeypatch, change) -> None:
    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner()
        svc = luna_service(runner)
        frozen, created = queue_review(session, svc, world)
        review_id = UUID(created["id"])
        attempt_id = attempt_of(session, review_id).id
        pid = frozen["preview_id"]
        if change == "preview_hash":
            snapshot = deepcopy(frozen["input"])
            snapshot["requirements"][0]["text"] += " 변조"
            _tamper(session, "UPDATE deep_review_preview SET input_snapshot = :value WHERE id = :id",
                    value=json.dumps(snapshot, ensure_ascii=False), id=UUID(pid).hex)
        elif change == "approval_missing":
            _tamper(session, "DELETE FROM deep_review_approval WHERE attempt_id = :id", id=attempt_id.hex)
        elif change == "approval_foreign_company":
            other = import_company(session, "demo-public-si")
            session.commit()
            _tamper(session, "UPDATE deep_review_approval SET company_id = :company WHERE attempt_id = :id",
                    company=other.company_id.hex, id=attempt_id.hex)
        elif change in {"creation_audit", "approval_audit"}:
            action = "deep_review.create" if change == "creation_audit" else "deep_review.external_transfer_approved"
            row = session.scalar(select(AuditEvent).where(AuditEvent.action == action))
            metadata = {**row.safe_metadata, "graph_version_id": str(uuid4())}
            _tamper(session, "UPDATE audit_event SET safe_metadata = :value WHERE id = :id",
                    value=json.dumps(metadata), id=row.id.hex)
        elif change == "source_text":
            # The pinned structure no longer re-splits into the approved units.
            changed = {page: body + " 추가 문장" if page == 1 else body for page, body in TEXTS.items()}

            def loader(_session, structure):
                payload = structure_loader(_session, structure)
                for block in payload["blocks"]:
                    block["text"] = changed[block["page"]]
                return payload

            svc.structure_loader = loader
        else:
            # A frozen unit that the preview never produced (hash recomputed consistently).
            snapshot = deepcopy(frozen["input"])
            snapshot["requirements"][0]["source_units"][0]["text"] += " 변조"
            from app.deep_review.services.input_versions import canonical_json_hash

            digest = canonical_json_hash(snapshot)
            provenance = {**session.get(DeepReviewPreview, UUID(pid)).provenance_jsonb, "input_sha256": digest}
            _tamper(session, "UPDATE deep_review_preview SET input_snapshot = :value, input_sha256 = :digest, "
                             "provenance_jsonb = :provenance WHERE id = :id",
                    value=json.dumps(snapshot, ensure_ascii=False), digest=digest,
                    provenance=json.dumps(provenance), id=UUID(pid).hex)
            for action in ("deep_review.create", "deep_review.external_transfer_approved"):
                row = session.scalar(select(AuditEvent).where(AuditEvent.action == action))
                _tamper(session, "UPDATE audit_event SET safe_metadata = :value WHERE id = :id",
                        value=json.dumps({**row.safe_metadata, "input_sha256": digest}), id=row.id.hex)
        claim = svc.claim_next_job(session, "company-e2e-worker")
        assert claim is not None and claim.deep_review_id == review_id
        with pytest.raises(DeepReviewServiceError) as error:
            svc.run_claim(session, claim)
        assert error.value.code == "approval_invalid"
        session.expire_all()
        assert runner.prompts == []
        assert session.get(DeepReview, review_id).status == "failed"
        assert session.get(DeepReviewAttempt, attempt_id).status == "failed"
        assert session.get(WorkJob, claim.job_id).last_error_code == "approval_invalid"
        _no_report(session, review_id)


def test_t8_company_row_on_a_non_demo_policy_is_refused_before_any_call(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner()
        svc = luna_service(runner)
        _frozen, created = queue_review(session, svc, world)
        review_id = UUID(created["id"])
        v5 = import_policy_version(session, CANONICAL_POLICY_FILE.with_name("analysis-policy-luna-v5.json"),
                                   created_by_name="정책 담당자")
        session.commit()
        _tamper(session, "UPDATE deep_review SET policy_version_id = :policy WHERE id = :id",
                policy=v5.id.hex, id=review_id.hex)
        claim = svc.claim_next_job(session, "company-e2e-worker")
        with pytest.raises(DeepReviewServiceError) as error:
            svc.run_claim(session, claim)
        assert error.value.code == "company_policy_invalid"
        session.expire_all()
        assert runner.prompts == []
        assert session.get(WorkJob, claim.job_id).last_error_code == "company_policy_invalid"
        assert session.get(DeepReview, review_id).status == "failed"
        _no_report(session, review_id)


def test_t8_company_jobs_are_left_untouched_while_demo_is_off(sqlite_engine, monkeypatch) -> None:
    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner()
        _frozen, created = queue_review(session, luna_service(runner), world)
        job_id = job_of(session, created["id"]).id
        deep_configure(monkeypatch, world.deep, BIDOPS_DEMO_ENABLED="false")
        off = luna_service(runner)
        assert off.settings.demo_enabled is False
        assert off.claim_next_job(session, "company-e2e-worker") is None
        assert not run_deep_review_once(session, "company-e2e-worker", service=off).claimed
        session.expire_all()
        job = session.get(WorkJob, job_id)
        assert (job.status, job.lease_owner, job.attempt_count) == ("queued", None, 0)
        assert attempt_of(session, created["id"]).status == "queued" and runner.prompts == []
        deep_configure(monkeypatch, world.deep)
        assert luna_service(runner).claim_next_job(session, "company-e2e-worker").job_id == job_id


def test_t8_logs_and_failure_metadata_never_carry_model_input_or_output(sqlite_engine, monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)

    def broken(stage, _prompt, output, _number):
        if stage == STAGE_NAMES[1]:
            output = deepcopy(output)
            output["claims"][0]["body"] = "모델 출력 비밀 문장은 로그에 남지 않는다 7777"
            output["claims"][0]["evidence_ids"] = [str(uuid4())]
        return output

    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner(mutate=broken)
        store = _CapturingStore()
        svc = luna_service(runner, store=store)
        frozen, created = queue_review(session, svc, world)
        claim = svc.claim_next_job(session, "company-e2e-worker")
        with pytest.raises(DeepReviewServiceError):
            svc.run_claim(session, claim)
        session.expire_all()
        stage = session.scalar(select(DeepReviewStage).where(
            DeepReviewStage.attempt_id == claim.attempt_id, DeepReviewStage.stage == STAGE_NAMES[1]))
        assert stage.status == "failed" and stage.raw_response_content_object_id is not None
        # One validation repair (v4/demo policy), then fail closed; codes and paths only.
        failed = [row for row in stage.invocation_metadata if row.get("status") == "validation_failed"]
        assert [row["validation_repair_attempt"] for row in failed] == [0, 1]
        assert session.get(WorkJob, claim.job_id).last_error_code == "validation_failed"
        metadata = json.dumps(stage.invocation_metadata, ensure_ascii=False)
        sensitive = [*_sensitive_strings(frozen["input"]), "모델 출력 비밀 문장"]
        for value in sensitive:
            assert value not in metadata
            assert value not in caplog.text
        # The original (rejected) responses are kept verbatim, encrypted, never repaired.
        stored = session.get(ContentObject, stage.raw_response_content_object_id)
        aggregate = json.loads(store.by_sha256[stored.sha256])
        failed_slice = failed[0]["slice_index"]
        originals = [row["raw_response"] for row in aggregate["responses"] if row["slice_index"] == failed_slice]
        assert len(originals) == 2 and all("모델 출력 비밀 문장" in row for row in originals)
        _no_report(session, created["id"])


class _CapturingStore:
    """Encrypted model-response store contract (``put_encrypted``) that keeps the plaintext."""

    def __init__(self) -> None:
        self.by_sha256: dict[str, bytes] = {}

    def put_encrypted(self, data, *, retention_days, content_type):
        digest = hashlib.sha256(data).hexdigest()
        self.by_sha256[digest] = data
        return {"object_key": f"model-response/{digest}", "encryption_key_ref": "fixture", "encrypted": True,
                "plaintext_sha256": digest, "plaintext_size_bytes": len(data)}


def test_t5_profile_evidence_mismatch_is_repaired_once_with_code_and_path_only(sqlite_engine, monkeypatch) -> None:
    calls = {"n": 0}

    def altered(stage, _prompt, output, _number):
        profile = [row for row in output["evidence"] if row["source_kind"] == "profile"]
        if stage == STAGE_NAMES[1] and profile and calls["n"] == 0:
            calls["n"] += 1
            output = deepcopy(output)
            next(row for row in output["evidence"] if row["source_kind"] == "profile")["quote"] += " 추가 실적"
        return output

    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner(mutate=altered)
        svc = luna_service(runner)
        _frozen, created = queue_review(session, svc, world)
        assert run_deep_review_once(session, "company-e2e-worker", service=svc).claimed
        session.expire_all()
        assert session.get(DeepReview, UUID(created["id"])).status == "completed" and calls["n"] == 1
        repairs = [row["input_slice"]["validation_repair"] for row in runner.stage_prompts(STAGE_NAMES[1])
                   if "validation_repair" in row["input_slice"]]
        assert len(repairs) == 1 and repairs[0]["attempt"] == 1
        # The prompt sanitizer drops ``path`` keys (as on the legacy path); the
        # persisted diagnostics keep code + field path only.
        assert repairs[0]["issues"] == [{"code": "narrative:profile_evidence_mismatch"}]
        attempt = attempt_of(session, created["id"])
        stage = session.scalar(select(DeepReviewStage).where(
            DeepReviewStage.attempt_id == attempt.id, DeepReviewStage.stage == STAGE_NAMES[1]))
        issues = [issue for row in stage.invocation_metadata for issue in row.get("validation_repair_issues", [])]
        assert issues and all(issue == {"code": "narrative:profile_evidence_mismatch", "path": "$.evidence[*]"}
                              for issue in issues)
        report = projection.company_report(ReportService(), session, company_id=world.company_id,
                                           review_id=UUID(created["id"]))
        checks = [row for row in report["view"]["validation"]["checks"] if row["check_type"] == "validation_repair_applied"]
        assert len(checks) == 1 and checks[0]["status"] == "warning"


def test_t5_missing_source_coverage_never_publishes_a_report(sqlite_engine, monkeypatch) -> None:
    def uncovered(stage, _prompt, output, _number):
        if stage == STAGE_NAMES[0]:
            output = deepcopy(output)
            output["coverage"] = []
        return output

    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        runner = FakeLunaRunner(mutate=uncovered)
        svc = luna_service(runner)
        _frozen, created = queue_review(session, svc, world)
        with pytest.raises(DeepReviewServiceError) as error:
            run_deep_review_once(session, "company-e2e-worker", service=svc)
        assert error.value.code == "validation_failed"
        session.expire_all()
        review_id = UUID(created["id"])
        assert session.get(DeepReview, review_id).status == "failed"
        assert len(runner.stage_prompts(STAGE_NAMES[0])) == 2 and not runner.stage_prompts(STAGE_NAMES[1])
        _no_report(session, review_id)


@requires_postgres
def test_t8_one_slot_under_concurrency(monkeypatch) -> None:
    with migrated_engine() as engine:
        with Session(engine) as session:
            world = e2e_world(session, monkeypatch)
            runner = FakeLunaRunner()
            svc = luna_service(runner)
            first = preview(session, svc, world.deep)
            second = preview(session, svc, world.deep)
        barrier = Barrier(2)

        def submit(pid):
            with Session(engine) as session:
                barrier.wait()
                try:
                    return create(session, luna_service(runner), world.deep, pid)["status"]
                except DeepReviewServiceError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, [first["preview_id"], second["preview_id"]]))
        assert sorted(outcomes) == ["active_attempt_exists", "queued"]
        with Session(engine) as session:
            assert count(session, DeepReviewApproval) == 1
            assert session.scalar(select(func.count()).select_from(WorkJob).where(WorkJob.job_type == "deep_review")) == 1

        claim_barrier = Barrier(2)

        def claim(worker):
            with Session(engine) as session:
                claim_barrier.wait()
                result = luna_service(runner).claim_next_job(session, worker)
                return None if result is None else str(result.job_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, ["slot-a", "slot-b"]))
        assert sorted(claims, key=lambda value: value is None)[1] is None and any(claims)
        with Session(engine) as session:
            job = session.scalar(select(WorkJob).where(WorkJob.job_type == "deep_review"))
            assert job.status == "running" and job.attempt_count == 1 and job.lease_owner in {"slot-a", "slot-b"}
        assert runner.prompts == []


# --- T6: failed attempt → retry preview → new attempt completes ---------------------------------


def test_t6_retry_after_a_failed_attempt_completes_and_switches_current_attempt(engine, monkeypatch) -> None:
    def broken(stage, _prompt, output, _number):
        if stage == STAGE_NAMES[1]:
            output = deepcopy(output)
            output["claims"][0]["evidence_ids"] = [str(uuid4())]
        return output

    with Session(engine) as session:
        world = e2e_world(session, monkeypatch)
        failing = FakeLunaRunner(mutate=broken)
        svc = luna_service(failing)
        first, created = queue_review(session, svc, world)
        review_id = UUID(created["id"])
        first_attempt = attempt_of(session, review_id).id
        with pytest.raises(DeepReviewServiceError):
            run_deep_review_once(session, "company-e2e-worker", service=svc)
        session.expire_all()
        assert session.get(DeepReview, review_id).status == "failed"
        _no_report(session, review_id)

        target = preview(session, svc, world.deep, review_id=review_id)
        assert target["input"]["target_review_id"] == str(review_id)
        attempt = retry(session, svc, world.deep, review_id, target["preview_id"])
        assert attempt["sequence"] == 2
        runner = FakeLunaRunner()
        good = luna_service(runner)
        assert run_deep_review_once(session, "company-e2e-worker", service=good).claimed
        session.expire_all()
        review = session.get(DeepReview, review_id)
        assert review.status == "completed" and str(review.current_attempt_id) == attempt["id"]
        assert session.get(DeepReviewAttempt, first_attempt).status == "superseded"
        approval = session.scalar(select(DeepReviewApproval).where(DeepReviewApproval.attempt_id == review.current_attempt_id))
        assert str(approval.preview_id) == target["preview_id"] and approval.company_id == world.company_id
        detail = projection.company_review_detail(good, session, company_id=world.company_id, review_id=review_id)
        assert detail["current_attempt"]["id"] == attempt["id"] and detail["is_current"] is True
        stored = session.get(DeepReviewPreview, UUID(target["preview_id"])).provenance_jsonb
        assert detail["provenance"] == json.loads(json.dumps(stored))
        assert detail["input_sha256"] == target["input_sha256"] != first["input_sha256"]
        report = projection.company_report(ReportService(), session, company_id=world.company_id, review_id=review_id)
        assert report["view"]["report"]["validation_summary"]["status"] == "passed"
        # The retry prompts are the retry preview's frozen input (target_review_id bound).
        assert {unit["requirement_id"] for row in runner.stage_prompts(STAGE_NAMES[0])
                for unit in row["input_slice"]["requirements"]} == {
            unit["requirement_id"] for row in target["input"]["requirements"] for unit in row["source_units"]}


# --- legacy writers refuse company reviews --------------------------------------------------------


def _completed_company_review(session: Session, monkeypatch) -> tuple[E2EWorld, UUID]:
    world = e2e_world(session, monkeypatch)
    svc = luna_service(FakeLunaRunner())
    _frozen, created = queue_review(session, svc, world)
    assert run_deep_review_once(session, "company-e2e-worker", service=svc).claimed
    session.expire_all()
    return world, UUID(created["id"])


def test_legacy_report_writers_refuse_company_reviews(sqlite_engine, monkeypatch) -> None:
    from app.deep_review.routers import reports as legacy_reports

    with Session(sqlite_engine) as session:
        world, review_id = _completed_company_review(session, monkeypatch)
        view = ReportService().get_report(session, review_id)
        revision = session.scalar(select(ReportRevision).where(ReportRevision.deep_review_id == review_id))
        validation = session.scalar(select(ValidationRun).where(ValidationRun.deep_review_id == review_id))
        before = (count(session, ReportRevision), count(session, ValidationRun), count(session, AuditEvent))
    app = FastAPI()
    app.include_router(legacy_reports.router)

    def db():
        with Session(sqlite_engine) as fresh:
            yield fresh

    app.dependency_overrides[get_db] = db
    http = TestClient(app)
    headers = {"X-BidOps-Actor-Name": "reviewer"}
    revision_body = {"request_id": str(uuid4()), "base_revision_id": str(revision.id), "report": view["report"],
                     "reason": "회사 보고서 수정 시도", "factual_change_evidence_ids": []}
    opinion_body = {"request_id": str(uuid4()), "report_revision_id": str(revision.id),
                    "validation_run_id": str(validation.id), "value": "보류", "reason": "회사 보고서 의견 시도",
                    "acknowledged_validation_failure": False}
    for path, body in ((f"/api/deep-reviews/{review_id}/report-revisions", revision_body),
                       (f"/api/deep-reviews/{review_id}/final-opinions", opinion_body)):
        reply = http.post(path, json=body, headers=headers)
        assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found", (path, reply.text)
    with Session(sqlite_engine) as session:
        assert (count(session, ReportRevision), count(session, ValidationRun), count(session, AuditEvent)) == before
        from app.deep_review.models import FinalOpinion

        assert count(session, FinalOpinion) == 0


def test_legacy_close_cli_refuses_company_reviews(sqlite_engine, monkeypatch, capsys) -> None:
    from app.deep_review.cli import close_deep_review

    with Session(sqlite_engine) as session:
        world = e2e_world(session, monkeypatch)
        _frozen, created = queue_review(session, luna_service(FakeLunaRunner()), world)
        review_id = UUID(created["id"])
        with pytest.raises(DeepReviewServiceError) as error:
            close_deep_review.close_queued(session, review_id, "운영 담당자")
        assert error.value.code == "not_found"
        session.rollback()
        assert session.get(DeepReview, review_id).status == "queued"
    import app.core.db as core_db

    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=sqlite_engine))
    exit_code = close_deep_review.main(["--review-id", str(review_id), "--actor-name", "운영 담당자"])
    assert exit_code == 2 and json.loads(capsys.readouterr().out) == {"error": "not_found"}
    with Session(sqlite_engine) as session:
        assert session.get(DeepReview, review_id).status == "queued"
        assert job_of(session, review_id).status == "queued"
        assert session.scalar(select(AuditEvent).where(AuditEvent.action == "deep_review.operator_close")) is None

