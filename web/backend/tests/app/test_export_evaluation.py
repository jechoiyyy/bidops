"""RL-05 STEP-002 T2: ``export-evaluation --cards|--actual`` (read-only gold acceptance export).

World: a synthetic real company (``tests.deep_review.test_company_knowledge._prepared_real``,
contract-shaped values, no company data) registered and activated, pre-specs with a
stored structure + HP-01 manifest (``tests.app.test_transfer_policy._seed_notice``), an
authoritative opportunity link and a ready bundle.  RL card-v1 attempts are inserted as
rows (review → attempt → approved preview → validated ``card_analysis_stage`` rows ->
creation audit) exactly as the verdict view reads them; no worker, model or network runs.

The cards pack is cross-checked with the STEP-001 consumer ``scripts/rl-gold.py``
(``export_cards``/``check_prediction_shape``), read from the worktree, never edited.
SQLite throughout; one PostgreSQL 17 variant (attempt + stage rows) runs with
``BIDOPS_TEST_POSTGRES_URL``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import AuditEvent
from app.deep_review.cli import export_evaluation as cli
from app.deep_review.models import (
    CardAnalysisStage,
    CompanyKnowledgeBinding,
    CompanyKnowledgeVersion,
    ContentObject,
    ContentObjectLocation,
    DeepReview,
    DeepReviewApproval,
    DeepReviewAttempt,
    DeepReviewPreview,
    DocumentSegmentManifest,
    DocumentStructure,
    KnowledgeOntologyVersion,
    PrespecV4PdfSnapshot,
    ProfileVersion,
    VerdictRequest,
)
from app.deep_review.services import assets
from app.deep_review.services.company_knowledge import activate_company_knowledge, import_company_knowledge
from app.deep_review.services.input_versions import (
    HP_LUNA_POLICY_FILE,
    RL_LUNA_POLICY_FILE_V8,
    RL_LUNA_POLICY_FILE_V9,
    import_policy_version,
)
from app.deep_review.services.transfer_policy import SYSTEM_ACTOR
from app.lifecycle.models import Opportunity, OpportunityLink
from tests.app import test_transfer_policy as tp
from tests.deep_review import test_company_knowledge as ck
from tests.deep_review.test_company_fit_enqueue import ready_bundle
from tests.deep_review.test_company_knowledge import object_store  # noqa: F401 - in-memory object store
from tests.postgres import migrated_engine, requires_postgres


REPO_ROOT = Path(__file__).resolve().parents[4]
RL_GOLD = REPO_ROOT / "scripts" / "rl-gold.py"
T0 = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)
HEX = "a" * 64


# --- world -------------------------------------------------------------------------------------


@pytest.fixture
def engine():
    bind = tp._sqlite_engine()
    try:
        yield bind
    finally:
        bind.dispose()


def _rl_gold():
    spec = importlib.util.spec_from_file_location("rl_gold_for_export_test", RL_GOLD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_world(session: Session) -> SimpleNamespace:
    imported = import_company_knowledge(session, ck._prepared_real(), actor="등록 담당자")
    activate_company_knowledge(session, company_id=imported.company_id,
                               graph_version_id=imported.graph_version_id, actor="활성 담당자")
    session.flush()
    binding = session.get(CompanyKnowledgeBinding, imported.company_id)
    graph = session.get(CompanyKnowledgeVersion, binding.graph_version_id)
    ontology = session.get(KnowledgeOntologyVersion, graph.ontology_id)
    profile = session.get(ProfileVersion, binding.profile_version_id)
    policies = {
        name: import_policy_version(session, path, created_by_name="정책 담당자", label=name)
        for name, path in (("rl-v9", RL_LUNA_POLICY_FILE_V9), ("rl-v8", RL_LUNA_POLICY_FILE_V8),
                           ("hp", HP_LUNA_POLICY_FILE))
    }
    # Plain values: the world outlives the session that built it.
    world = SimpleNamespace(
        company_id=imported.company_id,
        graph=SimpleNamespace(id=graph.id, graph_sha256=graph.graph_sha256),
        ontology=SimpleNamespace(version=ontology.version, sha256=ontology.sha256),
        profile=SimpleNamespace(id=profile.id, profile_sha256=profile.profile_sha256),
        policies={name: SimpleNamespace(id=row.id, policy_sha256=row.policy_sha256, model_name=row.model_name)
                  for name, row in policies.items()},
    )
    session.commit()
    return world


def _page_map_payload(block_keys: list[str]) -> dict:
    mapped = [{"block_key": block_keys[0], "section": 0, "para_index": 0, "page_first": 1, "page_last": 1,
               "match": "exact"}]
    unmapped = block_keys[1:]
    return {
        "schema": "bidops.para-page-map.v1", "page_count": 3, "paragraph_count": 1,
        "paragraphs": [{"section": 0, "para_index": 0, "page_first": 1, "page_last": 1, "kind": "fullParagraph"}],
        "blocks": mapped, "unmapped_block_keys": unmapped,
        "mapping": {"blocks_total": len(block_keys), "blocks_mapped": 1, "blocks_unmapped": len(unmapped),
                    "rule": "para-page-align.v1"},
    }


def _store(session: Session, namespace: str, raw: bytes, mime: str) -> tuple[ContentObject, ContentObjectLocation]:
    digest = hashlib.sha256(raw).hexdigest()
    _path, metadata = assets.store_named(namespace, f"{namespace}/export-test/{digest}", raw, content_type=mime)
    content = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(raw), detected_mime=mime,
                            retention_class="structure" if namespace == "structure" else "document-source")
    session.add(content)
    session.flush()
    location = ContentObjectLocation(
        content_object_id=content.id, namespace_key=namespace, object_key=metadata.object_key,
        object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified",
        verified_at=datetime.now(UTC),
    )
    session.add(location)
    session.flush()
    return content, location


def _add_page_map(session: Session, document, structure: DocumentStructure) -> str:
    raw = json.dumps(_page_map_payload([block["block_key"] for block in tp._structure_blocks()]),
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    page_map, page_map_location = _store(session, "structure", raw, "application/json")
    pdf, pdf_location = _store(session, "source", b"%PDF-1.7\n% synthetic\n", "application/pdf")
    session.add(PrespecV4PdfSnapshot(
        notice_id=document.notice_id, document_version_id=document.id,
        source_content_object_id=document.content_object_id, source_location_id=pdf_location.id,
        pdf_content_object_id=pdf.id, pdf_location_id=pdf_location.id,
        page_text_content_object_id=page_map.id, page_text_location_id=page_map_location.id,
        structure_id=structure.id, para_page_map_content_object_id=page_map.id,
        para_page_map_location_id=page_map_location.id, para_page_map_sha256=page_map.sha256,
        rhwp_binary_sha256=HEX, rhwp_version="0.8.6", source_kind="original",
        source_sha256=structure.source_sha256, source_size_bytes=10, pdf_sha256=pdf.sha256,
        pdf_size_bytes=pdf.size_bytes, pdf_page_count=3, page_text_sha256=page_map.sha256,
        page_text_size_bytes=page_map.size_bytes,
        pdf_metadata_jsonb={"schema": "bidops.rhwp-pdf-snapshot.v1", "renderer": "rhwp-svg-pdf", "page_count": 3},
        renderer_jsonb={"renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6"}, renderer_digest="b" * 64,
        font_jsonb={"font_manifest_sha256": "c" * 64}, font_digest="c" * 64, config_jsonb={"options": {}},
        config_sha256="d" * 64, scan_jsonb={"status": "clean"}, binding_sha256="e" * 64,
    ))
    session.flush()
    return page_map.sha256


def seed_document(session: Session, document_id: str, *, page_map: bool = True) -> SimpleNamespace:
    notice, document = tp._seed_notice(session)
    structure = session.scalar(select(DocumentStructure).where(DocumentStructure.document_version_id == document.id))
    manifest = session.scalar(select(DocumentSegmentManifest).where(DocumentSegmentManifest.structure_id == structure.id))
    opportunity = Opportunity(first_registered_stage="pre_spec")
    session.add(opportunity)
    session.flush()
    session.add(OpportunityLink(opportunity_id=opportunity.id, notice_id=notice.id, stage="notice",
                                link_type="official", status="확정", evidence_external_no=f"R26BD{notice.id:08d}"))
    session.flush()
    bundle_id = ready_bundle(session, notice.id, document.id)
    page_map_sha256 = _add_page_map(session, document, structure) if page_map else None
    session.commit()
    return SimpleNamespace(
        document_id=document_id, notice_id=notice.id, opportunity_id=opportunity.id, bundle_id=bundle_id,
        source_sha256=structure.source_sha256, structure_id=structure.id, manifest_id=manifest.id,
        structure_sha256=structure.payload_sha256, page_map_sha256=page_map_sha256,
        segment_eligibility=f"segment:{structure.source_sha256}:{uuid4()}",
        segment_overview=f"segment:{structure.source_sha256}:{uuid4()}",
    )


def selection_payload(world, documents, **overrides) -> dict:
    value = {
        "schema_version": "bidops.rl-evaluation-selection.v1",
        "documents": [
            {"document_id": d.document_id, "notice_id": d.notice_id, "opportunity_id": d.opportunity_id,
             "source_sha256": d.source_sha256, "structure_id": str(d.structure_id),
             "manifest_id": str(d.manifest_id), "title": "합성 사전규격", "agency": "합성 기관"}
            for d in documents
        ],
        "company_sha256": world.graph.graph_sha256,
        "ontology_sha256": world.ontology.sha256,
        "selected_on": "2026-10-19",
    }
    value.update(overrides)
    return value


def _unit(doc, unit_id: str, *, kind: str, ordinal: int, blocks: list[tuple[str, str]],
          sections: list[str] | None = None, source_sha256: str | None = None) -> dict:
    return {
        "unit_id": unit_id, "source_sha256": source_sha256 or doc.source_sha256,
        "document_version_id": str(uuid4()), "structure_id": str(doc.structure_id),
        "manifest_id": str(doc.manifest_id), "kind": kind, "ordinal": ordinal,
        "normalized_id": "SFR-001" if kind == "card" else None, "section_kinds": sections or [],
        "blocks": [{"block_key": key, "text": value} for key, value in blocks],
        "page_range": None, "mapping_status": "unavailable",
    }


def card_input(world, doc, *, foreign_source: bool = False) -> dict:
    card_id = f"card:{doc.source_sha256}:1:SFR-001"
    units = [
        _unit(doc, card_id, kind="card", ordinal=1, blocks=[("card-table-1-r1-c1", "SFR-001")]),
        _unit(doc, doc.segment_eligibility, kind="segment", ordinal=2, sections=["eligibility"],
              blocks=[("h-eligibility", "제2장 입찰참가자격"), ("b-eligibility", "소프트웨어사업자로 신고한 자"),
                      ("blank-eligibility", "   ")]),
        _unit(doc, doc.segment_overview, kind="segment", ordinal=3, sections=["overview"],
              blocks=[("h-overview", "제1장 사업개요"), ("b-overview", "유지관리 용역의 목적")]),
    ]
    if foreign_source:
        other = "f" * 64
        units[2] = _unit(doc, f"segment:{other}:{doc.segment_overview.rsplit(':', 1)[1]}", kind="segment",
                         ordinal=3, sections=["overview"], blocks=[("h-overview", "제1장 사업개요")],
                         source_sha256=other)
    return {
        "schema_version": "bidops.card-analysis-input.v1",
        "company_binding": {
            "graph_version_id": str(world.graph.id), "graph_sha256": world.graph.graph_sha256,
            "profile_version_id": str(world.profile.id), "profile_sha256": world.profile.profile_sha256,
            "ontology_version": world.ontology.version, "ontology_sha256": world.ontology.sha256,
        },
        "units": units,
        "batches": [{"batch_index": 0, "unit_ids": [unit["unit_id"] for unit in units], "source_characters": 40}],
        "missing_sections": [],
        "selector": {"version": "card-sections-v1", "sha256": HEX, "candidate_blocks": [], "selected_blocks": []},
    }


def _evidence(doc, block_key: str, quote: str) -> dict:
    return {"source_sha256": doc.source_sha256, "block_key": block_key, "quote": quote}


def stage_payloads(doc, units: list[dict]) -> dict[tuple[str, str], dict]:
    card_id, eligibility, overview = (unit["unit_id"] for unit in units)
    rows = [
        (card_id, "기능", "통합 검색 제공", None, "unknown", ["unknown_fact"], ("card-table-1-r1-c1", "SFR-001")),
        (eligibility, "자격", "소프트웨어사업자 신고", True, "gap", ["confirmed_contradiction"],
         ("b-eligibility", "소프트웨어사업자로 신고한 자")),
        (overview, "운영", "유지관리 수행", False, "met", ["confirmed_match"], ("b-overview", "유지관리 용역의 목적")),
    ]
    extract = {"schema_version": "bidops.requirement-extract.v1", "rejected_units": [], "items": [
        {"unit_id": unit_id, "type": type_, "normalized_requirement": text_, "mandatory": mandatory,
         "constraints": [], "concept_candidates": [], "unknowns": [], "evidence": [_evidence(doc, *quote)]}
        for unit_id, type_, text_, mandatory, _fit, _reasons, quote in rows
    ]}
    compare = {"schema_version": "bidops.requirement-compare.v1", "items": [
        {"unit_id": unit_id, "fit_status": fit, "constraint_results": [], "evidence_ids": [], "reason_codes": reasons}
        for unit_id, _type, _text, _mandatory, fit, reasons, _quote in rows
    ]}
    synthesis = {
        "verdict": "진행 어려움", "reason": "필수 자격 미충족", "blocking_condition_ids": [eligibility],
        "checklist": [], "cautions": [], "conflicts": [], "next_actions": [], "missing_sections": [],
        "rejected_units": [],
        "matrix": [{"unit_id": unit_id, "type": type_, "fit_status": fit, "role_findings": []}
                   for unit_id, type_, _text, _mandatory, fit, _reasons, _quote in rows],
    }
    return {("extract", "0"): extract, ("compare", "0"): compare, ("synthesis", "final"): synthesis}


def add_review(session: Session, world, doc, *, policy: str = "rl-v9", created_at: datetime = T0,
               quality: str = "reference") -> DeepReview:
    row = world.policies[policy]
    review = DeepReview(
        id=uuid4(), company_id=world.company_id, notice_id=doc.notice_id, bundle_id=doc.bundle_id,
        profile_version_id=world.profile.id, policy_version_id=row.id, graph_version_id=world.graph.id,
        effective_grade_at_start="우선 검토", status="completed", created_at=created_at,
    )
    session.add(review)
    metadata = {"reference_workflow_mode": True} if quality == "reference" else {"analysis_provider": "mock-analysis"}
    session.add(AuditEvent(actor_kind="system", action="deep_review.auto_create", aggregate_type="deep_review",
                           aggregate_id=str(review.id), safe_metadata=metadata, created_at=created_at))
    session.flush()
    return review


def add_attempt(session: Session, world, doc, review: DeepReview, *, sequence: int = 1, status: str = "completed",
                approved_at: datetime = T0, stages: bool = True, manual: bool = False,
                foreign_source: bool = False) -> DeepReviewAttempt:
    attempt = DeepReviewAttempt(id=uuid4(), deep_review_id=review.id, sequence=sequence, status=status,
                                lease_fence=0, started_at=approved_at,
                                completed_at=approved_at if status == "completed" else None)
    session.add(attempt)
    session.flush()
    frozen = {"card_analysis": card_input(world, doc, foreign_source=foreign_source), "graph_nodes": []}
    input_sha256 = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    policy = world.policies[next(key for key, row in world.policies.items() if row.id == review.policy_version_id)]
    preview = DeepReviewPreview(
        id=uuid4(), notice_id=doc.notice_id, bundle_id=doc.bundle_id, profile_version_id=world.profile.id,
        policy_version_id=policy.id, input_sha256=input_sha256, input_snapshot=frozen,
        company_id=world.company_id, graph_version_id=world.graph.id,
        provenance_jsonb={
            "input_sha256": input_sha256, "purpose": "deep_review", "company_id": str(world.company_id),
            "graph_version_id": str(world.graph.id), "graph_sha256": world.graph.graph_sha256,
            "ontology_sha256": world.ontology.sha256, "policy_version_id": str(policy.id),
            "policy_sha256": policy.policy_sha256, "model_name": policy.model_name,
        },
    )
    session.add(preview)
    session.flush()
    session.add(DeepReviewApproval(id=uuid4(), preview_id=preview.id, attempt_id=attempt.id,
                                   claimed_name=SYSTEM_ACTOR, request_id=uuid4(), approved_at=approved_at,
                                   company_id=world.company_id))
    if stages:
        for (stage, key), payload in stage_payloads(doc, frozen["card_analysis"]["units"]).items():
            session.add(CardAnalysisStage(id=uuid4(), attempt_id=attempt.id, stage=stage, stage_key=key,
                                          input_sha256=HEX, result_sha256=HEX, payload=payload))
    if manual:
        session.add(VerdictRequest(id=uuid4(), opportunity_id=doc.opportunity_id, notice_id=doc.notice_id,
                                   actor="jechoi", request_id=uuid4(), status="started", reason="manual",
                                   started_attempt_id=attempt.id))
    session.flush()
    return attempt


def gold_payload(world, documents, *, authored_at: str, conditions: dict | None = None) -> dict:
    conditions = conditions or {}
    return {
        "schema_version": "bidops.rl-human-gold.v1", "status": "human_completed", "annotator": "사람 평가자",
        "authored_at": authored_at, "written_before_model_output": True,
        "company_sha256": world.graph.graph_sha256, "ontology_sha256": world.ontology.sha256,
        "documents": [
            {"document_id": d.document_id, "source_sha256": d.source_sha256,
             "sources_sha256": cli.sources_sha256(d.structure_sha256, d.page_map_sha256),
             "blocking_conditions": conditions.get(d.document_id, [])}
            for d in documents
        ],
    }


def write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def run_cli(monkeypatch, engine, capsys, *argv) -> tuple[int, dict]:
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(cli, "init_db", lambda: None)
    code = cli.main([str(value) for value in argv])
    return code, json.loads(capsys.readouterr().out)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- --cards ------------------------------------------------------------------------------------


def test_cards_pack_is_verbatim_structure_and_page_map_and_feeds_rl_gold(engine, object_store, monkeypatch,  # noqa: F811
                                                                         capsys, tmp_path) -> None:
    with Session(engine) as session:
        world = build_world(session)
        mapped = seed_document(session, "doc-a", page_map=True)
        unmapped = seed_document(session, "doc-b", page_map=False)
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [mapped, unmapped]))
    pack = tmp_path / "cards"

    code, summary = run_cli(monkeypatch, engine, capsys, "--cards", "--selection", selection, "--out", pack)
    assert code == 0, summary
    assert summary == {"mode": "cards", "documents": 2, "without_page_map": ["doc-b"],
                       "files": ["doc-a.structure.json", "doc-a.para_page_map.json", "doc-b.structure.json"]}
    assert sorted(path.name for path in pack.iterdir()) == sorted(summary["files"])
    assert sha(pack / "doc-a.structure.json") == mapped.structure_sha256
    assert sha(pack / "doc-a.para_page_map.json") == mapped.page_map_sha256
    assert sha(pack / "doc-b.structure.json") == unmapped.structure_sha256
    assert all(oct(path.stat().st_mode & 0o777) == "0o600" for path in pack.iterdir())

    # The STEP-001 consumer reads exactly these files; its source binding equals the export's.
    exported = {row["document_id"]: row for row in _rl_gold().export_cards(pack)["documents"]}
    assert exported["doc-a"]["sources_sha256"] == cli.sources_sha256(mapped.structure_sha256, mapped.page_map_sha256)
    assert exported["doc-b"]["sources_sha256"] == cli.sources_sha256(unmapped.structure_sha256, None)
    assert exported["doc-b"]["source_documents"][0]["page_map_sha256"] is None

    # Exclusive create: a second run into the same directory writes nothing.
    before = {path.name: sha(path) for path in pack.iterdir()}
    code, summary = run_cli(monkeypatch, engine, capsys, "--cards", "--selection", selection, "--out", pack)
    assert (code, summary) == (2, {"error": "output_exists"})
    assert {path.name: sha(path) for path in pack.iterdir()} == before


@pytest.mark.parametrize("change, code", [
    ({"company_sha256": "b" * 64}, "binding_mismatch"),
    ({"ontology_sha256": "b" * 64}, "binding_mismatch"),
    ({"doc": {"source_sha256": "b" * 64}}, "selection_mismatch"),
    ({"doc": {"opportunity_id": 999_999}}, "selection_mismatch"),
    ({"doc": {"manifest_id": str(uuid4())}}, "selection_mismatch"),
    ({"doc": {"document_id": "../escape"}}, "invalid_selection"),
    ({"doc": {"notice_id": True}}, "invalid_selection"),
])
def test_cards_refuses_selection_that_disagrees_with_db(engine, object_store, monkeypatch, capsys, tmp_path,  # noqa: F811
                                                        change, code) -> None:
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
    payload = selection_payload(world, [doc], **{k: v for k, v in change.items() if k != "doc"})
    payload["documents"][0].update(change.get("doc", {}))
    selection = write_json(tmp_path / "selection.v1.json", payload)
    result = run_cli(monkeypatch, engine, capsys, "--cards", "--selection", selection, "--out", tmp_path / "cards")
    assert result == (2, {"error": code})
    assert not (tmp_path / "cards").exists()


def test_output_inside_worktree_must_be_git_ignored(engine, object_store, monkeypatch, capsys, tmp_path) -> None:  # noqa: F811
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    tracked = REPO_ROOT / "web" / "backend" / "tests" / f"export-eval-{uuid4().hex}"
    assert run_cli(monkeypatch, engine, capsys, "--cards", "--selection", selection, "--out", tracked) == (
        2, {"error": "output_not_ignored"})
    assert not tracked.exists()
    ignored = REPO_ROOT / ".sdlc" / "local-runtime" / f"pytest-export-eval-{uuid4().hex}"
    try:
        code, summary = run_cli(monkeypatch, engine, capsys, "--cards", "--selection", selection, "--out", ignored)
        assert code == 0 and (ignored / "doc-a.structure.json").is_file()
    finally:
        for path in ignored.glob("*"):
            path.unlink()
        if ignored.exists():
            ignored.rmdir()


@pytest.mark.parametrize("argv", [
    ["--cards", "--gold", "g.json", "--condition-alignment", "a.json"],  # gold belongs to --actual
    ["--actual", "--gold", "g.json"],  # HP-06: gold and alignment come as a pair
    ["--actual", "--condition-alignment", "a.json"],
    ["--cards", "--actual"],
])
def test_usage_errors_exit_2_with_code_only(capsys, tmp_path, argv) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main([*argv, "--selection", str(tmp_path / "s.json"), "--out", str(tmp_path / "o")])
    assert exited.value.code == 2
    assert json.loads(capsys.readouterr().out) == {"error": "usage"}
    assert not (tmp_path / "o").exists()


# --- --actual -----------------------------------------------------------------------------------


def _attempt_world(session: Session):
    world = build_world(session)
    doc = seed_document(session, "doc-a")
    main = add_review(session, world, doc, created_at=T0)
    # An older eligible completed attempt (the newest approved_at wins) ...
    add_attempt(session, world, doc, main, sequence=1, approved_at=T0 + timedelta(minutes=1))
    chosen = add_attempt(session, world, doc, main, sequence=2, approved_at=T0 + timedelta(minutes=2), manual=True)
    # ... and newer superseded/running attempts that are never scored.
    add_attempt(session, world, doc, main, sequence=3, status="superseded",
                approved_at=T0 + timedelta(minutes=3), stages=False)
    running = add_attempt(session, world, doc, main, sequence=4, status="running",
                          approved_at=T0 + timedelta(minutes=3, seconds=30), stages=False)
    mock = add_review(session, world, doc, policy="rl-v8", created_at=T0 + timedelta(minutes=4), quality="mock")
    add_attempt(session, world, doc, mock, approved_at=T0 + timedelta(minutes=4))
    other = add_review(session, world, doc, policy="hp", created_at=T0 + timedelta(minutes=5))
    add_attempt(session, world, doc, other, approved_at=T0 + timedelta(minutes=5))
    session.commit()
    return world, doc, SimpleNamespace(id=chosen.id), SimpleNamespace(id=running.id)


def test_actual_derives_latest_eligible_attempt_and_separates_the_rest(engine, object_store, monkeypatch,  # noqa: F811
                                                                      capsys, tmp_path) -> None:
    with Session(engine) as session:
        world, doc, chosen, _running = _attempt_world(session)
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    out = tmp_path / "draft"
    code, summary = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", out)
    assert code == 0, summary
    # superseded, running → status; rl-v8 mock → quality_status; hp → policy; never scored.
    assert summary["attempt_ids"] == {"doc-a": str(chosen.id)}
    assert summary["excluded_attempts"] == {"doc-a": {"policy": 1, "status": 2, "quality_status": 1}}
    assert summary["independence_checked"] is False and summary["files"] == ["actual.v1.json"]
    assert sorted(path.name for path in out.iterdir()) == ["actual.v1.json"]
    actual = json.loads((out / "actual.v1.json").read_text(encoding="utf-8"))
    assert set(actual) == {"schema_version", "company_sha256", "ontology_sha256", "selection_sha256", "documents",
                           "export_tool_sha256"}
    assert actual["schema_version"] == "bidops.rl-evaluation-actual.v1"
    assert actual["selection_sha256"] == sha(selection) and summary["actual_sha256"] == sha(out / "actual.v1.json")
    assert (actual["company_sha256"], actual["ontology_sha256"]) == (world.graph.graph_sha256, world.ontology.sha256)
    (row,) = actual["documents"]
    assert set(row) == {"document_id", "source_sha256", "sources_sha256", "attempt_id", "policy_id", "policy_sha256",
                        "model", "reasoning_effort", "cli_version", "quality_status", "status", "verdict", "met",
                        "gap", "card_states", "blocking_units", "unit_sources", "unit_decisions"}
    card_id = f"card:{doc.source_sha256}:1:SFR-001"
    block = f"block:{doc.source_sha256}:"
    assert row["attempt_id"] == str(chosen.id) and row["policy_id"] == "analysis-policy-luna-rl-v9"
    assert row["policy_sha256"] == world.policies["rl-v9"].policy_sha256
    assert (row["model"], row["reasoning_effort"], row["cli_version"]) == ("gpt-6-luna", "high", "0.162.1")
    assert (row["quality_status"], row["status"], row["verdict"]) == ("unmeasured_reference", "completed", "진행 어려움")
    assert row["sources_sha256"] == cli.sources_sha256(doc.structure_sha256, doc.page_map_sha256)
    # met/gap use the gold universe (blocks with text); unit_sources keep every owned block.
    assert row["met"] == [f"{block}h-overview", f"{block}b-overview"]
    assert row["gap"] == [f"{block}h-eligibility", f"{block}b-eligibility"]
    assert row["card_states"] == [{"unit_id": card_id, "status": "unknown"}]
    assert row["blocking_units"] == [doc.segment_eligibility]
    assert row["unit_sources"][1] == {"unit_id": doc.segment_eligibility, "source_unit_ids": [
        f"{block}h-eligibility", f"{block}b-eligibility", f"{block}blank-eligibility"]}
    assert row["unit_sources"][0] == {"unit_id": card_id, "source_unit_ids": [card_id]}
    assert row["unit_decisions"][1] == {
        "unit_id": doc.segment_eligibility, "normalized_requirement": "소프트웨어사업자 신고", "mandatory": True,
        "fit_status": "gap", "reason_codes": ["confirmed_contradiction"],
        "evidence_refs": [_evidence(doc, "b-eligibility", "소프트웨어사업자로 신고한 자")]}
    assert row["unit_decisions"][0]["mandatory"] is None  # unknown stays null, not false

    # Deterministic: the same inputs give byte-identical actual (the alignment names its sha).
    code, again = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", tmp_path / "x")
    assert code == 0 and again["actual_sha256"] == summary["actual_sha256"]


def test_actual_missing_attempt_when_only_mock_other_policy_or_running(engine, object_store, monkeypatch,  # noqa: F811
                                                                      capsys, tmp_path) -> None:
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
        main = add_review(session, world, doc)
        add_attempt(session, world, doc, main, status="running", stages=False)
        mock = add_review(session, world, doc, policy="rl-v8", quality="mock")
        add_attempt(session, world, doc, mock)
        other = add_review(session, world, doc, policy="hp")
        add_attempt(session, world, doc, other)
        session.commit()
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", tmp_path / "o") == (
        2, {"error": "missing_attempt"})
    assert not (tmp_path / "o").exists()


def test_actual_refuses_attempt_whose_units_leave_the_selected_source(engine, object_store, monkeypatch,  # noqa: F811
                                                                     capsys, tmp_path) -> None:
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
        add_attempt(session, world, doc, add_review(session, world, doc), foreign_source=True)
        session.commit()
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", tmp_path / "o") == (
        2, {"error": "selection_mismatch"})


def _gold_and_alignment(tmp_path: Path, world, doc, actual_sha256: str, *, authored_at: str,
                        mappings: list[dict] | None = None, gold_sha256: str | None = None) -> tuple[Path, Path]:
    conditions = {doc.document_id: [
        {"condition_id": "C1", "text": "소프트웨어사업자", "source_unit_ids": [f"block:{doc.source_sha256}:b-eligibility"]},
        {"condition_id": "C2", "text": "개요", "source_unit_ids": [f"block:{doc.source_sha256}:b-overview"]},
    ]}
    gold = write_json(tmp_path / f"gold-{uuid4().hex}.json",
                      gold_payload(world, [doc], authored_at=authored_at, conditions=conditions))
    alignment = {
        "schema_version": "bidops.rl-condition-alignment.v1", "gold_sha256": gold_sha256 or sha(gold),
        "actual_sha256": actual_sha256, "annotator": "사람 평가자", "authored_at": "2026-10-19T12:00:00+09:00",
        "documents": [{"document_id": doc.document_id, "mappings": mappings if mappings is not None else [
            {"model_unit_id": doc.segment_eligibility, "gold_condition_ids": ["C1"], "reason": "같은 자격 조건"}]}],
    }
    return gold, write_json(tmp_path / f"alignment-{uuid4().hex}.json", alignment)


def test_actual_with_gold_and_alignment_writes_prediction_and_receipt(engine, object_store, monkeypatch,  # noqa: F811
                                                                     capsys, tmp_path) -> None:
    with Session(engine) as session:
        world, doc, chosen, _running = _attempt_world(session)
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    code, draft = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", tmp_path / "d")
    assert code == 0
    # Gold written before the first RL review (T0) → independent.
    gold, alignment = _gold_and_alignment(tmp_path, world, doc, draft["actual_sha256"],
                                          authored_at="2026-10-19T09:59:59+09:00")
    out = tmp_path / "final"
    code, summary = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold,
                            "--condition-alignment", alignment, "--out", out)
    assert code == 0, summary
    assert summary["files"] == ["actual.v1.json", "prediction.v1.json", "receipt.json"]
    assert summary["independence_checked"] is True and summary["actual_sha256"] == draft["actual_sha256"]
    prediction = json.loads((out / "prediction.v1.json").read_text(encoding="utf-8"))
    rl_gold = _rl_gold()
    rl_gold.check_prediction_shape(prediction)  # the scorer's exact key sets
    (row,) = prediction["documents"]
    assert row["blocking_condition_ids"] == ["C1"]
    assert row["sources_sha256"] == gold_payload(world, [doc], authored_at="x")["documents"][0]["sources_sha256"]
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert receipt == {
        "schema_version": "bidops.rl-evaluation-export-receipt.v1", "gold_sha256": sha(gold),
        "actual_sha256": sha(out / "actual.v1.json"), "alignment_sha256": sha(alignment),
        "prediction_sha256": sha(out / "prediction.v1.json"),
        "tool_sha256": hashlib.sha256(Path(cli.__file__).read_bytes()).hexdigest(),
        "selection_sha256": sha(selection),
    }

    # An unmatched model blocking unit stays a false positive, never a found gold condition.
    gold2, alignment2 = _gold_and_alignment(tmp_path, world, doc, draft["actual_sha256"],
                                            authored_at="2026-10-19T09:00:00+09:00", mappings=[
        {"model_unit_id": doc.segment_eligibility, "gold_condition_ids": [], "reason": "다른 조건"}])
    code, _summary = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold2,
                             "--condition-alignment", alignment2, "--out", tmp_path / "unmatched")
    assert code == 0
    unmatched = json.loads((tmp_path / "unmatched" / "prediction.v1.json").read_text(encoding="utf-8"))
    assert unmatched["documents"][0]["blocking_condition_ids"] == [f"unmatched:{doc.segment_eligibility}"]


@pytest.mark.parametrize("case", ["other_actual", "other_gold", "missing_mapping", "no_source_overlap",
                                  "unknown_gold_id", "empty_reason"])
def test_alignment_is_refused_when_not_bound_or_incomplete(engine, object_store, monkeypatch, capsys,  # noqa: F811
                                                           tmp_path, case) -> None:
    with Session(engine) as session:
        world, doc, _chosen, _running = _attempt_world(session)
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    code, draft = run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--out", tmp_path / "d")
    assert code == 0
    mapping = {"model_unit_id": doc.segment_eligibility, "gold_condition_ids": ["C1"], "reason": "같은 조건"}
    kwargs: dict = {}
    actual_sha256 = draft["actual_sha256"]
    if case == "other_actual":
        actual_sha256 = "b" * 64
    elif case == "other_gold":
        kwargs["gold_sha256"] = "b" * 64
    elif case == "missing_mapping":
        kwargs["mappings"] = []
    elif case == "no_source_overlap":
        kwargs["mappings"] = [{**mapping, "gold_condition_ids": ["C2"]}]
    elif case == "unknown_gold_id":
        kwargs["mappings"] = [{**mapping, "gold_condition_ids": ["C9"]}]
    else:
        kwargs["mappings"] = [{**mapping, "reason": " "}]
    gold, alignment = _gold_and_alignment(tmp_path, world, doc, actual_sha256,
                                          authored_at="2026-10-19T09:00:00+09:00", **kwargs)
    out = tmp_path / "final"
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold,
                   "--condition-alignment", alignment, "--out", out) == (2, {"error": "invalid_alignment"})
    assert not out.exists()


@pytest.mark.parametrize("authored_at", ["2026-10-19T10:00:00+09:00", "2026-10-19T10:30:00+09:00"])
def test_gold_after_model_when_a_person_requested_the_model_before_the_gold(engine, object_store, monkeypatch,  # noqa: F811
                                                                           capsys, tmp_path, authored_at) -> None:
    # T0 = 10:00 KST: equal or later authored_at is not "before the model output".
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
        add_attempt(session, world, doc, add_review(session, world, doc, created_at=T0), manual=True)
        session.commit()
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    gold, alignment = _gold_and_alignment(tmp_path, world, doc, "b" * 64, authored_at=authored_at)
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold,
                   "--condition-alignment", alignment, "--out", tmp_path / "o") == (2, {"error": "gold_after_model"})
    assert not (tmp_path / "o").exists()


def test_holdout_violated_when_an_automatic_rl_review_precedes_the_gold(engine, object_store, monkeypatch,  # noqa: F811
                                                                        capsys, tmp_path) -> None:
    with Session(engine) as session:
        world = build_world(session)
        doc = seed_document(session, "doc-a")
        session.add(VerdictRequest(id=uuid4(), opportunity_id=doc.opportunity_id, notice_id=doc.notice_id,
                                   actor="jechoi", request_id=uuid4(), status="rejected", reason="gold_holdout"))
        # An automatic mock RL review before the gold (any status/quality counts) ...
        early = add_review(session, world, doc, policy="rl-v8", created_at=T0 - timedelta(hours=1), quality="mock")
        add_attempt(session, world, doc, early, status="failed", stages=False)
        # ... and a later, manually requested scored attempt.
        add_attempt(session, world, doc, add_review(session, world, doc, created_at=T0 + timedelta(hours=1)),
                    approved_at=T0 + timedelta(hours=1), manual=True)
        session.commit()
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    gold, alignment = _gold_and_alignment(tmp_path, world, doc, "b" * 64, authored_at="2026-10-19T10:00:00+09:00")
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold,
                   "--condition-alignment", alignment, "--out", tmp_path / "o") == (2, {"error": "holdout_violated"})


@pytest.mark.parametrize("change, code", [
    ({"authored_at": "2026-10-19T09:00:00"}, "invalid_gold"),
    ({"written_before_model_output": False}, "invalid_gold"),
    ({"company_sha256": "b" * 64}, "selection_mismatch"),
    ({"doc": {"sources_sha256": "b" * 64}}, "binding_mismatch"),
    ({"doc": {"blocking_conditions": None}}, "invalid_gold"),
    ({"doc": {"blocking_conditions": [{"condition_id": "unmatched:x", "text": "t", "source_unit_ids": ["a"]}]}},
     "invalid_gold"),
])
def test_gold_is_checked_before_any_output(engine, object_store, monkeypatch, capsys, tmp_path,  # noqa: F811
                                           change, code) -> None:
    with Session(engine) as session:
        world, doc, _chosen, _running = _attempt_world(session)
    selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
    payload = gold_payload(world, [doc], authored_at="2026-10-19T09:00:00+09:00")
    payload.update({k: v for k, v in change.items() if k != "doc"})
    payload["documents"][0].update(change.get("doc", {}))
    gold = write_json(tmp_path / "gold.json", payload)
    _unused, alignment = _gold_and_alignment(tmp_path, world, doc, "b" * 64, authored_at="2026-10-19T09:00:00+09:00")
    assert run_cli(monkeypatch, engine, capsys, "--actual", "--selection", selection, "--gold", gold,
                   "--condition-alignment", alignment, "--out", tmp_path / "o") == (2, {"error": code})
    assert not (tmp_path / "o").exists()


# --- PostgreSQL ---------------------------------------------------------------------------------


@requires_postgres
def test_postgres_actual_with_attempt_and_stage_rows(object_store, monkeypatch, capsys, tmp_path) -> None:  # noqa: F811
    with migrated_engine() as bind:
        with Session(bind) as session:
            world, doc, chosen, _running = _attempt_world(session)
            before = _row_counts(session)
        selection = write_json(tmp_path / "selection.v1.json", selection_payload(world, [doc]))
        code, draft = run_cli(monkeypatch, bind, capsys, "--actual", "--selection", selection, "--out", tmp_path / "d")
        assert code == 0, draft
        assert draft["attempt_ids"] == {"doc-a": str(chosen.id)}
        assert draft["excluded_attempts"] == {"doc-a": {"policy": 1, "status": 2, "quality_status": 1}}
        gold, alignment = _gold_and_alignment(tmp_path, world, doc, draft["actual_sha256"],
                                              authored_at="2026-10-19T09:00:00+09:00")
        code, summary = run_cli(monkeypatch, bind, capsys, "--actual", "--selection", selection, "--gold", gold,
                                "--condition-alignment", alignment, "--out", tmp_path / "final")
        assert code == 0, summary
        assert summary["actual_sha256"] == draft["actual_sha256"]
        prediction = json.loads((tmp_path / "final" / "prediction.v1.json").read_text(encoding="utf-8"))
        assert prediction["documents"][0]["blocking_condition_ids"] == ["C1"]
        code, cards = run_cli(monkeypatch, bind, capsys, "--cards", "--selection", selection, "--out", tmp_path / "c")
        assert code == 0 and sha(tmp_path / "c" / "doc-a.para_page_map.json") == doc.page_map_sha256
        # Read only: the exports added or changed no row.
        with Session(bind) as session:
            assert _row_counts(session) == before
            assert session.scalar(select(DeepReviewAttempt.status).where(DeepReviewAttempt.id == chosen.id)) == "completed"


def _row_counts(session: Session) -> dict[str, int]:
    tables = (DeepReview, DeepReviewAttempt, DeepReviewApproval, DeepReviewPreview, CardAnalysisStage,
              VerdictRequest, AuditEvent, ContentObject, ContentObjectLocation)
    return {table.__tablename__: len(session.scalars(select(table.id)).all()) for table in tables}
