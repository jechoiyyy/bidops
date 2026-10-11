"""Read-only diagnostic: replay the company deep-review preview preparation step by step.

Prints only step names, counts, error codes and code locations. No document text,
company facts, secrets or SQL rows are printed. Nothing is written to the database.
"""
from __future__ import annotations

import sys
import traceback
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
import app.deep_review.services.company_deep_review as cdr
import app.deep_review.services.company_analysis_input as cai
import app.deep_review.services.company_knowledge_retrieval as ckr
from app.deep_review.services import document_segments
from app.deep_review.services.deep_reviews import DeepReviewService

company_id = UUID(sys.argv[1])
notice_id = int(sys.argv[2])
bundle_id = UUID(sys.argv[3])


def where(exc: BaseException) -> str:
    tb = traceback.extract_tb(exc.__traceback__)
    frames = [f"{fr.filename.rsplit('/app/web/backend/', 1)[-1]}:{fr.lineno}:{fr.name}" for fr in tb]
    return " <- ".join(reversed(frames[-6:]))


def step(name, fn):
    try:
        value = fn()
        print(f"OK   {name}")
        return value
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        code = getattr(exc, "code", None)
        print(f"FAIL {name}: {type(exc).__name__} code={code!r} at {where(exc)}")
        raise SystemExit(1)


init_db()
settings = get_settings()
service = DeepReviewService()
with SessionLocal() as session:
    step("gate_company", lambda: cdr._gate_company(session, company_id, settings))
    knowledge = step("knowledge_context", lambda: cai.resolve_company_knowledge_context(session, company_id))
    print(f"     nodes={len(knowledge.graph_nodes)} edges={len(knowledge.graph_edges)} ontology={knowledge.ontology.version}")
    policy = step("deep_policy", lambda: cdr.resolve_company_deep_policy(session, settings))
    print(f"     source_characters={policy.source_characters} profile_characters={policy.profile_characters} path_limit={policy.path_limit_per_requirement}")
    overview = step("overview", lambda: cdr.current_company_overviews(session, [notice_id]).get(notice_id))
    print(f"     overview_found={overview is not None}")
    sw = step("sw_business", lambda: cdr.sw_business_notice_ids(session, [notice_id]))
    print(f"     sw={notice_id in sw}")
    bundle, structures = step("ready_bundle", lambda: cdr._ready_bundle(service, session, notice_id, bundle_id))
    docs = bundle.get("documents", [])
    print(f"     documents={len(docs)} structures={len(structures)}")
    for doc in docs:
        structure = structures.get(doc.get("structure_id_at_confirmation"), {})
        blocks = structure.get("blocks", []) if isinstance(structure, dict) else []
        pages = {b.get("page") for b in blocks if isinstance(b, dict)}
        text_chars = sum(len(str(b.get("text", ""))) for b in blocks if isinstance(b, dict))
        print(f"     doc ordinal={doc.get('ordinal')} has_content_sha256={bool(doc.get('content_sha256'))} "
              f"structure_source_sha256={bool(structure.get('source_sha256')) if isinstance(structure, dict) else None} "
              f"blocks={len(blocks)} pages={len(pages)} text_chars={text_chars}")

    # --- company_source_units internals -------------------------------------
    groups = step("splitter", lambda: DeepReviewService._requirements(
        bundle, structures, max_characters=policy.source_characters, max_requirements=1))
    units = [row for group in groups for row in group]
    fallback = sum(1 for u in units if u.get("requirement_id") == "req-unknown-0000")
    empty = sum(1 for u in units if not u.get("document_version_id") or not u.get("structure_id") or not u.get("source_sha256"))
    print(f"     units={len(units)} fallback={fallback} missing_ids_or_sha={empty} "
          f"max_unit_chars={max((len(u.get('text', '')) for u in units), default=0)}")
    inventory = step("inventory", lambda: document_segments.inventory_context(
        session, [UUID(str(row["structure_id_at_confirmation"])) for row in docs]))
    prefixes = inventory.get("prefixes", [])
    expected = set(inventory.get("expected_ids", []))
    observed = set()
    for unit in units:
        observed.update(document_segments.observed_requirement_ids([str(unit.get("text", ""))], prefixes))
    print(f"     manifest_count={inventory.get('manifest_count')} prefixes={sorted(prefixes)} expected={len(expected)} observed={len(observed)} "
          f"expected_only={sorted(expected - observed)[:8]} observed_only={sorted(observed - expected)[:8]}")
    units = step("company_source_units", lambda: cdr.company_source_units(
        session, bundle, structures, source_characters=policy.source_characters))
    requirements = step("requirements_from_source_units", lambda: ckr.requirements_from_source_units(units, knowledge.ontology))
    mapped = sum(1 for r in requirements if r.get("concept_ids"))
    print(f"     requirements={len(requirements)} with_concepts={mapped}")
    document_ids = [UUID(str(row["document_version_id"])) for row in docs]
    run, result, _document = overview
    value = step("build_company_analysis_input", lambda: cai.build_company_analysis_input(
        purpose="deep_review", execution_nonce=uuid4(), knowledge=knowledge, notice_id=notice_id,
        document_version_ids=document_ids, overview_run_id=run.id, overview_sha256=cdr.overview_digest(result),
        policy_version_id=policy.row.id, policy_sha256=policy.row.policy_sha256, model_name=policy.row.model_name,
        model_revision=policy.model_revision, generation=policy.generation, requirements=requirements,
        path_limit_per_requirement=policy.path_limit_per_requirement, profile_characters=policy.profile_characters,
        bundle_id=bundle_id, target_review_id=None))
    paths = value.get("graph_paths", [])
    rel = {}
    for p in paths:
        rel[p.get("relation")] = rel.get(p.get("relation"), 0) + 1
    print(f"     graph_paths={len(paths)} by_relation={rel} profile_facts={len(value.get('profile_facts', []))} "
          f"profile_evidence={len(value.get('profile_evidence', []))} coverage_keys={sorted((value.get('coverage') or {}).keys())}")
    safe = step("prompt_safe", lambda: cai.company_part_is_prompt_safe(value))
    print(f"     prompt_safe={safe}")
    input_hash = cai.canonical_json_hash(value)
    provenance = step("frozen_provenance", lambda: cai.frozen_provenance(
        value, input_sha256=input_hash, documents=cai.document_provenance(session, document_ids)))
    step("FrozenProvenance.validate", lambda: cdr.FrozenProvenance.model_validate(provenance))
    print("DONE all steps passed")
