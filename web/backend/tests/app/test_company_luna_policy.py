"""DEMO-03 STEP-004: demo Luna policy and company slice/evidence path (spec T4 input half, T5).

* T5 policy: ``analysis-policy-luna-demo-v1`` is an approved, byte-canonical,
  sha256-pinned file that differs from ``analysis-policy-luna-v4`` only by its
  identity, ``chunking.path_limit_per_requirement``/``profile_characters`` and
  the company/graph input descriptions; it inherits v4 execution (deadline,
  one validation repair) and validation (no v3 validation-off).  Unknown
  identities, mutated bytes and a missing/invalid path limit are rejected; the
  legacy v1-v4 mapping is unchanged.
* T5 output: company slice validation keeps every required guard (dangling
  evidence, considered IDs, coverage, quotes, numbers) and never alters the
  original response.
* T4 input half: slices built from a STEP-003 preview's frozen input cover
  every source unit, carry ``global_path_index`` with the unchanged path, and
  fail closed on tampering.

No model, transport or network is called (the STEP-003 autouse guard applies).
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.model_binding import canonical_json_bytes
from app.core.model_client import build_prompt
from app.deep_review.services import company_deep_review as cdr
from app.deep_review.services import company_knowledge_retrieval as retrieval
from app.deep_review.services.company_analysis_input import COMPANY_ANALYSIS_INPUT_KEYS, COMPANY_ANALYSIS_INPUT_SCHEMA
from app.deep_review.services.company_slices import (
    STAGES,
    check_company_stage_slices,
    company_stage_slices,
    company_validation_profile,
    validate_company_slice_output,
)
from app.deep_review.services.deep_review_validation import DeepReviewValidationError, validate_deep_review_stage
from app.deep_review.services.deep_reviews import _policy_execution_limit, _policy_payload
from app.deep_review.services.input_versions import (
    CANONICAL_POLICY_FILE,
    DEMO_LUNA_POLICY_FILE,
    DEMO_LUNA_POLICY_IDENTITY,
    HP_LUNA_POLICY_FILE,
    LUNA_V5_POLICY_FILE,
    LUNA_V5_POLICY_IDENTITY,
    InputVersionError,
    _approved_policy_path,
    _policy_hash_matches,
    canonical_json_hash,
    import_policy_version,
    load_canonical_policy,
    validate_pinned_policy,
)
from app.deep_review.services.luna_identity import COMPANY_POLICY_IDENTITIES, HP_POLICY_IDENTITY
from app.deep_review.services.narrative_inputs import NarrativeInputError
from tests.app.test_company_deep_review_binding import (  # noqa: F401 - shared fixtures
    LUNA_V4,
    deep_world,
    engine,
    no_model_calls,
    object_store,
    preview,
    service,
    world_session,
    sqlite_engine,
)
from tests.deep_review.test_company_knowledge_retrieval import DOC_ID, PROFILE_ID, RUN_ID, _fixture_graph, _unit


DEMO_SHA256 = "9cb6254ef2f7fa3fbc608d775951aed14d958204f5366b30f92da661a4cbc3b0"
HP_SHA256 = "776c3efc908bf005f57df58d153406add592103d7cd7d3874ae9984cd363184b"
V5_SHA256 = "f575e827d592fbe8c90bb4f2210d242351e805cd0975212559b2fa7a615cce2e"
TEXTS = [
    "데이터 플랫폼 구축 및 데이터 품질·관리 체계 수립을 수행한다.",
    "정보보호 관리 인증 보유 여부를 제출한다.",
    "제안사는 기관 내부망에서 검색 서비스를 구축하고 시험 결과와 운영 매뉴얼을 제출해야 한다.",
]


def demo_policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(DEMO_LUNA_POLICY_FILE)
    return payload


def v4_policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(LUNA_V4)
    return payload


def hp_policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(HP_LUNA_POLICY_FILE)
    return payload


def v5_policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(LUNA_V5_POLICY_FILE)
    return payload


def write_candidate(tmp_path, payload) -> object:
    path = tmp_path / "candidate.json"
    path.write_bytes(canonical_json_bytes(payload))
    return path


# --- T5: policy file, mapping, import ------------------------------------------------


def test_t5_demo_policy_is_canonical_pinned_and_differs_from_v4_only_by_company_inputs() -> None:
    raw = DEMO_LUNA_POLICY_FILE.read_bytes()
    payload, canonical, digest = load_canonical_policy(DEMO_LUNA_POLICY_FILE)
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == DEMO_SHA256
    assert DEMO_LUNA_POLICY_FILE.name == "analysis-policy-luna-demo-v1.json"
    assert payload["policy_identity"] == DEMO_LUNA_POLICY_IDENTITY == "analysis-policy-luna-demo-v1"
    v4 = v4_policy()

    # Inherited unchanged: execution (deadline + one repair), validation (v2 contract, no v3 off), model.
    assert payload["execution"] == v4["execution"] == {
        "automatic_retry": False, "cli_version": "0.155.1", "review_timeout_seconds": 18000,
        "timeout_seconds": 900, "validation_repair_attempts": 1,
    }
    assert payload["validation"] == v4["validation"]
    assert "result_checks" not in payload["validation"]
    for key in ("schema", "stage_schema", "report_schema", "pipeline_version", "model_endpoint_ref",
                "model_name", "generation", "quality_status"):
        assert payload[key] == v4[key], key
    assert payload["quality_status"] == "unmeasured_reference"
    assert payload["stage_schema"] == "bidops.deep-review-stage.v2"
    assert payload["report_schema"] == "bidops.deep-review-report.v2"
    assert _policy_execution_limit(payload, "validation_repair_attempts", default=0, minimum=0, maximum=1) == 1
    assert _policy_execution_limit(payload, "review_timeout_seconds", default=7200, minimum=1, maximum=86400) == 18000

    # The only differences from v4.
    assert set(payload) == set(v4)
    differing = {key for key in payload if payload[key] != v4[key]}
    assert differing == {"policy_identity", "chunking", "prompt_output_contract", "stages"}
    chunking_diff = {key for key in set(payload["chunking"]) | set(v4["chunking"])
                     if payload["chunking"].get(key) != v4["chunking"].get(key)}
    assert chunking_diff == {"path_limit_per_requirement", "profile_characters"}
    assert payload["chunking"]["path_limit_per_requirement"] == 32
    assert payload["chunking"]["profile_characters"] == 8000
    contract, base = payload["prompt_output_contract"], v4["prompt_output_contract"]
    assert {key: contract[key] for key in base} == base
    assert set(contract) - set(base) == {"company_input_rule", "company_evidence_rule"}
    assert [row["stage"] for row in payload["stages"]] == [row["stage"] for row in v4["stages"]] == list(STAGES)
    for row, old in zip(payload["stages"], v4["stages"]):
        assert set(row) == set(old) and row["instruction"].startswith(old["instruction"])
        assert len(row["instruction"]) > len(old["instruction"])

    # Company/graph input descriptions the prompt must carry.
    company = contract["company_input_rule"] + " " + contract["company_evidence_rule"]
    for phrase in ("fictional_scenario", "profile_facts", "profile_evidence", "graph_nodes", "graph_edges",
                   "graph_paths", "direct", "partial", "unmapped", "not a judgment", "unknown",
                   "input limits", "never as mismatch", "considered_claim_ids", "new local IDs",
                   "Cite only supplied references", "fixed_profile_slice", "company_coverage"):
        assert phrase in company, phrase
    assert "검색 결과" in payload["stages"][1]["instruction"]
    assert "판정이 아니" in payload["stages"][1]["instruction"]


@pytest.mark.parametrize(
    ("path", "base_path", "identity", "digest"),
    [
        (HP_LUNA_POLICY_FILE, DEMO_LUNA_POLICY_FILE, HP_POLICY_IDENTITY, HP_SHA256),
        (LUNA_V5_POLICY_FILE, LUNA_V4, LUNA_V5_POLICY_IDENTITY, V5_SHA256),
    ],
)
def test_t3_hp_and_v5_policies_are_canonical_four_key_derivatives(
    path, base_path, identity, digest,
) -> None:
    assert COMPANY_POLICY_IDENTITIES == frozenset({DEMO_LUNA_POLICY_IDENTITY, HP_POLICY_IDENTITY})
    payload, canonical, actual_digest = load_canonical_policy(path)
    base, _base_raw, _base_digest = load_canonical_policy(base_path)
    assert path.read_bytes() == canonical == canonical_json_bytes(payload)
    assert actual_digest == hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert payload["policy_identity"] == identity
    assert payload["model_name"] == "gpt-6-luna"
    assert payload["generation"]["reasoning_effort"] == "high"
    assert payload["execution"]["cli_version"] == "0.162.1"

    expected = deepcopy(base)
    expected["policy_identity"] = identity
    expected["model_name"] = "gpt-6-luna"
    expected["generation"]["reasoning_effort"] = "high"
    expected["execution"]["cli_version"] = "0.162.1"
    assert payload == expected
    assert _approved_policy_path(payload) == path


def test_t5_mapping_rejects_mutation_unknown_identity_and_invalid_path_limit(tmp_path) -> None:
    payload = demo_policy()
    assert _approved_policy_path(payload) == DEMO_LUNA_POLICY_FILE
    assert _approved_policy_path(hp_policy()) == HP_LUNA_POLICY_FILE
    assert _approved_policy_path(v5_policy()) == LUNA_V5_POLICY_FILE
    assert _approved_policy_path(v4_policy()) == LUNA_V4
    for version in ("v1", "v2", "v3"):
        legacy, _raw, _digest = load_canonical_policy(CANONICAL_POLICY_FILE.with_name(f"analysis-policy-luna-{version}.json"))
        assert _approved_policy_path(legacy).name == f"analysis-policy-luna-{version}.json"

    mutated = deepcopy(payload)
    mutated["prompt_output_contract"]["company_input_rule"] += " changed"
    with pytest.raises(InputVersionError, match="승인되지 않은"):
        load_canonical_policy(write_candidate(tmp_path, mutated))
    unknown = deepcopy(payload)
    unknown["policy_identity"] = "analysis-policy-luna-demo-v2"
    with pytest.raises(InputVersionError, match="identity"):
        load_canonical_policy(write_candidate(tmp_path, unknown))
    # A demo identity must never fall back to content-based v1-v3 detection.
    stripped = deepcopy(payload)
    stripped["policy_identity"] = None
    with pytest.raises(InputVersionError):
        load_canonical_policy(write_candidate(tmp_path, stripped))

    for bad in ("missing", 0, -1, True, "32", 1.5, None):
        candidate = deepcopy(payload)
        if bad == "missing":
            del candidate["chunking"]["path_limit_per_requirement"]
        else:
            candidate["chunking"]["path_limit_per_requirement"] = bad
        with pytest.raises(InputVersionError, match="path_limit_per_requirement"):
            load_canonical_policy(write_candidate(tmp_path, candidate))
        hp_candidate = deepcopy(hp_policy())
        if bad == "missing":
            del hp_candidate["chunking"]["path_limit_per_requirement"]
        else:
            hp_candidate["chunking"]["path_limit_per_requirement"] = bad
        with pytest.raises(InputVersionError, match="path_limit_per_requirement"):
            load_canonical_policy(write_candidate(tmp_path, hp_candidate))
    # The same key is not required of v4 (its approved bytes have no such key).
    assert "path_limit_per_requirement" not in v4_policy()["chunking"]
    # Non-canonical bytes of the approved content are rejected too.
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    with pytest.raises(InputVersionError, match="bytes"):
        load_canonical_policy(pretty)


def test_t3_import_seven_luna_policies_creates_distinct_rows(engine) -> None:
    paths = [CANONICAL_POLICY_FILE.with_name(f"analysis-policy-luna-v{version}.json") for version in range(1, 5)]
    paths.extend((DEMO_LUNA_POLICY_FILE, LUNA_V5_POLICY_FILE, HP_LUNA_POLICY_FILE))
    with Session(engine) as session:
        rows = [import_policy_version(session, path, created_by_name="정책 담당자") for path in paths]
        session.commit()
        assert len({row.id for row in rows}) == 7
        assert [row.policy_sha256 for row in rows] == [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        demo, v5, hp = rows[-3:]
        assert demo.policy_sha256 == DEMO_SHA256
        assert import_policy_version(session, DEMO_LUNA_POLICY_FILE, created_by_name="정책 담당자").id == demo.id
        assert import_policy_version(session, LUNA_V5_POLICY_FILE, created_by_name="정책 담당자").id == v5.id
        assert import_policy_version(session, HP_LUNA_POLICY_FILE, created_by_name="정책 담당자").id == hp.id
        assert (demo.model_endpoint_ref, demo.model_name) == ("codex-exec", "gpt-5.6-luna")
        assert (v5.model_endpoint_ref, v5.model_name) == ("codex-exec", "gpt-6-luna")
        assert (hp.model_endpoint_ref, hp.model_name) == ("codex-exec", "gpt-6-luna")
        for row in rows:
            assert _policy_hash_matches(row)
            validate_pinned_policy(row, allow_unmeasured_reference=True)
        snapshot = {key: value for key, value in _policy_payload(demo).items() if key != "policy_sha256"}
        assert snapshot == demo_policy()
        assert "result_checks" not in demo.validation_rules
        # Legacy rows keep their v1-v4 snapshots.
        assert all(_policy_payload(row).get("policy_identity") in {None, "analysis-policy-luna-v4"} for row in rows[:4])


def test_t4_company_deep_policy_checks_runtime_before_company_identity(world_session, monkeypatch) -> None:
    from tests.app.test_company_deep_review_binding import code, deep_configure

    session, world, svc = world_session
    resolved = cdr.resolve_company_deep_policy(session)
    assert resolved.row.id == world.policy_id
    assert resolved.payload["policy_identity"] == HP_POLICY_IDENTITY
    assert (resolved.path_limit_per_requirement, resolved.profile_characters) == (32, 8000)

    demo = import_policy_version(session, DEMO_LUNA_POLICY_FILE, created_by_name="정책 담당자")
    v4 = import_policy_version(session, LUNA_V4, created_by_name="정책 담당자")
    v5 = import_policy_version(session, LUNA_V5_POLICY_FILE, created_by_name="정책 담당자")
    session.commit()
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(demo.id))
    assert code(lambda: preview(session, svc, world)) == "model_binding_invalid"
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(v4.id))
    assert code(lambda: preview(session, svc, world)) == "model_binding_invalid"
    deep_configure(monkeypatch, world, BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID=str(v5.id))
    assert code(lambda: preview(session, svc, world)) == "analysis_policy_unavailable"


# --- T4 input half: slices from a frozen preview input -------------------------------


def _stage_output(stage: str, slices: list[dict]) -> dict:
    """A synthetic validated stage output: one source claim + evidence per unit."""

    claims, evidence = [], []
    for row in slices:
        for unit in row.get("requirements", []):
            if any(unit["requirement_id"] in claim["source_unit_ids"] for claim in claims):
                continue
            eid, cid = str(uuid4()), str(uuid4())
            evidence.append({"evidence_id": eid, "source_kind": "document", "quote": unit["text"][:10],
                             "document_version_id": unit["document_version_id"], "structure_id": unit["structure_id"]})
            claims.append({"claim_id": cid, "evidence_ids": [eid], "source_unit_ids": [unit["requirement_id"]],
                           "requirement_ids": list(unit["document_requirement_ids"]), "body": unit["text"]})
    return {"stage": stage, "claims": claims, "evidence": evidence}


def _unit_ids(frozen: dict) -> set[str]:
    return {unit["requirement_id"] for row in frozen["requirements"] for unit in row["source_units"]}


def _assert_company_slices(frozen: dict, slices: list[dict], policy: dict) -> None:
    paths = frozen["graph_paths"]
    seen = []
    for row in slices:
        assert retrieval.company_context_size(row) <= policy["chunking"]["profile_characters"]
        assert len(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= policy["chunking"]["max_characters"]
        indexes = [path["global_path_index"] for path in row["graph_paths"]]
        assert indexes == sorted(indexes)  # never re-sorted away from the frozen order
        requirement_ids = {item["id"] for item in row["company_requirements"]}
        node_ids = {node["id"] for node in row["graph_nodes"]}
        edge_ids = {edge["id"] for edge in row["graph_edges"]}
        evidence_ids = {item["profile_evidence_id"] for item in row["profile_evidence"]}
        for path in row["graph_paths"]:
            index = path["global_path_index"]
            assert {key: value for key, value in path.items() if key != "global_path_index"} == paths[index]
            assert path["requirement_id"] in requirement_ids and path["relation"] in {"direct", "partial", "unmapped"}
            assert set(path["node_ids"]) <= node_ids and set(path["edge_ids"]) <= edge_ids
            assert set(path["profile_evidence_ids"]) <= evidence_ids
            seen.append(index)
        assert "requirement_ids" not in row  # unit IDs are never offered as document requirement IDs
    assert set(seen) == set(range(len(paths)))
    # Every frozen fact/evidence row reaches a delivery slice (concept-only facts included).
    assert {fact["fact_key"] for row in slices for fact in row["profile_facts"]} == {
        fact["fact_key"] for fact in frozen["profile_facts"]}
    assert {item["profile_evidence_id"] for row in slices for item in row["profile_evidence"]} == {
        item["profile_evidence_id"] for item in frozen["profile_evidence"]}


def test_t4_stage_slices_cover_the_frozen_preview_input(engine, monkeypatch) -> None:
    with Session(engine) as session:
        world = deep_world(session, monkeypatch)
        frozen = preview(session, service(), world)["input"]
    policy = hp_policy()
    assert frozen["policy_sha256"] == HP_SHA256
    assert set(frozen) == COMPANY_ANALYSIS_INPUT_KEYS and frozen["graph_paths"]
    units = _unit_ids(frozen)
    assert units == set(frozen["coverage"]["included_requirement_ids"])

    first = company_stage_slices(STAGES[0], frozen, [], policy)
    assert [row["slice_index"] for row in first] == list(range(len(first)))
    assert {unit["requirement_id"] for row in first for unit in row["requirements"]} == units
    assert all(set(row) == {"slice_index", "requirements"} for row in first)
    stage_one = _stage_output(STAGES[0], first)

    second = company_stage_slices(STAGES[1], frozen, [stage_one], policy)
    assert [row["slice_index"] for row in second] == list(range(len(second)))
    assert {unit["requirement_id"] for row in second for unit in row["requirements"]} == units
    _assert_company_slices(frozen, second, policy)
    for row in second:
        unit_ids = {unit["requirement_id"] for unit in row["requirements"]}
        assert row["verified_claims"] and all(set(claim["source_unit_ids"]) <= unit_ids for claim in row["verified_claims"])
        assert set(row["company_coverage"]) == {"unmapped_requirement_ids", "excluded_fact_keys",
                                               "excluded_path_count_by_requirement"}
        assert len(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= policy["chunking"]["max_characters"]
        # The bounded prompt fits the Luna limit and shows the frozen path order.
        prompt = json.loads(build_prompt(STAGES[1], {**row, "deep_review_id": "r", "attempt_id": "a", "stage": STAGES[1]},
                                         policy, profile={"profile_version_id": PROFILE_ID, "profile_sha256": "x"}, max_chars=100000))
        shown = [(path["requirement_id"], path["node_ids"], path["relation"]) for path in prompt["input_slice"]["graph_paths"]]
        assert shown == [(path["requirement_id"], path["node_ids"], path["relation"]) for path in row["graph_paths"]]
        assert prompt["fixed_profile_slice"]["evidence"] == row["profile_evidence"]
        assert "company_input_rule" in prompt["output_contract"]
    check_company_stage_slices(STAGES[1], frozen, second)
    stage_two = _stage_output(STAGES[1], second)

    third = company_stage_slices(STAGES[2], frozen, [stage_one, stage_two], policy)
    assert {unit for row in third for claim in row["verified_claims"] for unit in claim["source_unit_ids"]} == units
    assert all(row["synthesis_phase"] == "partial" for row in third)
    check_company_stage_slices(STAGES[2], frozen, third)


def pure_frozen(slug: str = "demo-data-ai", texts=TEXTS, *, policy: dict | None = None) -> dict:
    """A CompanyAnalysisInput(deep_review) built from the frozen fixtures without a DB."""

    policy = policy or demo_policy()
    ontology, nodes, edges, profile = _fixture_graph(slug)
    units = [_unit(text, block=index, doc_ids=[f"SFR-{index + 1:03d}"]) for index, text in enumerate(texts)]
    requirements = retrieval.requirements_from_source_units(units, ontology)
    part = retrieval.build_company_retrieval(
        requirements, ontology=ontology, graph_nodes=nodes, graph_edges=edges, profile=profile,
        path_limit_per_requirement=policy["chunking"]["path_limit_per_requirement"],
        profile_budget=policy["chunking"]["profile_characters"],
    )
    value = {
        "schema_version": COMPANY_ANALYSIS_INPUT_SCHEMA, "purpose": "deep_review",
        "execution_nonce": str(uuid4()), "target_review_id": None, "company_id": str(uuid4()),
        "profile_version_id": PROFILE_ID, "profile_sha256": "b" * 64, "graph_version_id": str(uuid4()),
        "graph_sha256": "c" * 64, "ontology_version": "demo-ontology-v1", "ontology_sha256": "d" * 64,
        "notice_id": 1, "document_version_ids": [DOC_ID], "bundle_id": str(uuid4()),
        "overview_run_id": RUN_ID, "overview_sha256": "e" * 64, "policy_version_id": str(uuid4()),
        "policy_sha256": canonical_json_hash(policy), "model_name": policy["model_name"], "model_revision": None,
        "generation_config_sha256": canonical_json_hash(policy["generation"]), **part,
    }
    assert set(value) == COMPANY_ANALYSIS_INPUT_KEYS
    return value


def _code(call) -> str:
    with pytest.raises(NarrativeInputError) as error:
        call()
    return error.value.code


@pytest.mark.parametrize("policy_factory", [demo_policy, hp_policy])
def test_t6_company_policy_payload_with_row_hash_is_accepted_and_slices_are_deterministic(policy_factory) -> None:
    policy = policy_factory()
    frozen = pure_frozen(policy=policy)
    with_hash = {**policy, "policy_sha256": frozen["policy_sha256"]}  # ``_policy_payload`` shape
    first = company_stage_slices(STAGES[0], frozen, [], with_hash)
    stage_one = _stage_output(STAGES[0], first)
    assert company_stage_slices(STAGES[1], frozen, [stage_one], with_hash) == company_stage_slices(STAGES[1], frozen, [stage_one], policy)
    before = deepcopy(frozen)
    company_stage_slices(STAGES[1], frozen, [stage_one], policy)
    assert frozen == before


@pytest.mark.parametrize("slug", ["demo-data-ai", "demo-public-si", "demo-cloud-si"])
def test_t4_profile_characters_8000_keeps_every_path_fact_where_4000_drops_them(slug) -> None:
    """Reason for the demo ``profile_characters`` (v4 had 4000).

    With 4000 the frozen selection drops facts of nodes that lie on retrieved
    paths (e.g. the staff group of a partial path in the STEP-003 notice for
    demo-data-ai).  With 8000 no fact of a path node is excluded for any
    fixture company, and the largest delivery slice still fits
    ``max_characters``.
    """

    labels_ontology, *_rest = _fixture_graph(slug)
    labels = [concept.label for concept in labels_ontology.concepts]
    policy = demo_policy()
    v4_budget = v4_policy()["chunking"]["profile_characters"]
    dropped_at_v4 = 0
    for texts in (TEXTS, labels):
        frozen = pure_frozen(slug, texts)
        path_nodes = {node for path in frozen["graph_paths"] for node in path["node_ids"]}
        assert not set(frozen["coverage"]["excluded_fact_keys"]) & path_nodes
        small = pure_frozen(slug, texts, policy={**policy, "chunking": {**policy["chunking"], "profile_characters": v4_budget}})
        dropped_at_v4 += len(set(small["coverage"]["excluded_fact_keys"]) & path_nodes)
        stage_one = _stage_output(STAGES[0], company_stage_slices(STAGES[0], frozen, [], policy))
        second = company_stage_slices(STAGES[1], frozen, [stage_one], policy)
        _assert_company_slices(frozen, second, policy)
    assert dropped_at_v4 > 0


def test_t4_tampered_frozen_input_fails_closed() -> None:
    policy = demo_policy()
    frozen = pure_frozen()
    stage_one = _stage_output(STAGES[0], company_stage_slices(STAGES[0], frozen, [], policy))

    # A requirement (and its paths) removed while coverage still lists it.
    missing = deepcopy(frozen)
    removed = missing["requirements"].pop()["id"]
    missing["graph_paths"] = [path for path in missing["graph_paths"] if path["requirement_id"] != removed]
    assert removed in missing["coverage"]["included_requirement_ids"]
    orphan = deepcopy(frozen)
    orphan["requirements"].pop()  # its paths now reference a requirement that is not in the input
    assert _code(lambda: company_stage_slices(STAGES[0], orphan, [], policy)) == "company_input_invalid"
    assert _code(lambda: company_stage_slices(STAGES[0], missing, [], policy)) == "slice_coverage_mismatch"
    assert _code(lambda: company_stage_slices(STAGES[1], missing, [stage_one], policy)) == "slice_coverage_mismatch"

    empty = deepcopy(frozen)
    empty["requirements"][0]["source_units"] = []
    assert _code(lambda: company_stage_slices(STAGES[0], empty, [], policy)) == "source_units_empty"

    large = deepcopy(frozen)
    large["requirements"][0]["source_units"][0]["text"] = "가" * policy["chunking"]["source_characters"]
    large["requirements"][0]["text"] = large["requirements"][0]["source_units"][0]["text"]
    for stage, previous in ((STAGES[0], []), (STAGES[1], [stage_one])):
        assert _code(lambda: company_stage_slices(stage, large, previous, policy)) == "source_unit_too_large"

    foreign_node = deepcopy(frozen)
    foreign_node["graph_paths"][0]["node_ids"] = [*foreign_node["graph_paths"][0]["node_ids"], "node-not-in-input"]
    assert _code(lambda: company_stage_slices(STAGES[1], foreign_node, [stage_one], policy)) == "company_input_invalid"
    foreign_requirement = deepcopy(frozen)
    foreign_requirement["graph_paths"][0]["requirement_id"] = "req-not-in-input"
    assert _code(lambda: company_stage_slices(STAGES[1], foreign_requirement, [stage_one], policy)) == "company_input_invalid"

    for key, value in (("purpose", "company_fit"), ("schema_version", "bidops.company-analysis-input.v0")):
        wrong = {**deepcopy(frozen), key: value}
        assert _code(lambda: company_stage_slices(STAGES[0], wrong, [], policy)) == "company_input_invalid"
    extra = {**deepcopy(frozen), "graph_path_indexes": []}
    assert _code(lambda: company_stage_slices(STAGES[0], extra, [], policy)) == "company_input_invalid"

    # Only the frozen demo policy may slice a company input.
    assert _code(lambda: company_stage_slices(STAGES[0], frozen, [], v4_policy())) == "company_policy_invalid"
    other = {**deepcopy(frozen), "policy_sha256": "0" * 64}
    assert _code(lambda: company_stage_slices(STAGES[0], other, [], policy)) == "company_policy_invalid"
    tiny = {**policy, "chunking": {**policy["chunking"], "max_characters": 500}}
    tiny_frozen = {**deepcopy(frozen), "policy_sha256": canonical_json_hash(tiny)}
    assert _code(lambda: company_stage_slices(STAGES[1], tiny_frozen, [stage_one], tiny)) == "slice_too_large"

    # Stage order and the previous outputs are part of the frozen pipeline.
    assert _code(lambda: company_stage_slices(STAGES[1], frozen, [], policy)) == "stage_input_invalid"
    assert _code(lambda: company_stage_slices("unknown_stage", frozen, [], policy)) == "stage_input_invalid"
    second = company_stage_slices(STAGES[1], frozen, [stage_one], policy)
    stage_two = _stage_output(STAGES[1], second)
    uncovered = deepcopy(stage_one)
    uncovered["claims"] = uncovered["claims"][1:]
    assert _code(lambda: company_stage_slices(STAGES[2], frozen, [uncovered, {**stage_two, "claims": []}], policy)) == "slice_coverage_mismatch"

    # Tampered slices (e.g. reloaded from storage) are re-checked.
    out_of_range = deepcopy(second)
    path_slice = next(row for row in out_of_range if row["graph_paths"])
    path_slice["graph_paths"][0]["global_path_index"] = len(frozen["graph_paths"])
    assert _code(lambda: check_company_stage_slices(STAGES[1], frozen, out_of_range)) == "slice_coverage_mismatch"
    reordered = deepcopy(second)
    path_slice = next(row for row in reordered if len(row["graph_paths"]) > 1)
    path_slice["graph_paths"].reverse()
    assert _code(lambda: check_company_stage_slices(STAGES[1], frozen, reordered)) == "slice_coverage_mismatch"
    dropped = deepcopy(second)
    dropped.pop()
    assert _code(lambda: check_company_stage_slices(STAGES[1], frozen, dropped)) == "slice_coverage_mismatch"
    changed_unit = deepcopy(second)
    changed_unit[0]["requirements"][0]["text"] += " 변조"
    assert _code(lambda: check_company_stage_slices(STAGES[1], frozen, changed_unit)) == "slice_coverage_mismatch"
    first = company_stage_slices(STAGES[0], frozen, [], policy)
    assert _code(lambda: check_company_stage_slices(STAGES[0], frozen, first[1:])) == "slice_coverage_mismatch"


# --- T5: company slice output validation ----------------------------------------------


def _company_slice() -> tuple[dict, dict]:
    policy = demo_policy()
    frozen = pure_frozen()
    stage_one = _stage_output(STAGES[0], company_stage_slices(STAGES[0], frozen, [], policy))
    slices = company_stage_slices(STAGES[1], frozen, [stage_one], policy)
    row = next(item for item in slices if item["profile_evidence"] and item["graph_paths"])
    return frozen, row


def _valid_output(row: dict) -> dict:
    unit = row["requirements"][0]
    evidence = row["profile_evidence"][0]
    prior = row["verified_claims"][0]["claim_id"]
    local_evidence = {
        "evidence_id": str(uuid4()), "source_kind": "profile", "document_version_id": None, "structure_id": None,
        "profile_version_id": evidence["profile_version_id"], "profile_evidence_id": evidence["profile_evidence_id"],
        "locator_type": "profile_fact", "locator": dict(evidence["locator"]), "quote": evidence["quote"],
        "confidence": None, "source_sha256": evidence["source_sha256"],
    }
    claim = {
        "claim_id": str(uuid4()), "category": "회사 근거", "claim_type": "fact", "body": evidence["quote"],
        "status": "supported", "formula": None, "premise_claim_ids": [], "reason": None,
        "evidence_ids": [local_evidence["evidence_id"]], "report_section": "company_fit",
        "narrative_role": "company_basis", "topic_key": "company-basis", "source_unit_ids": [unit["requirement_id"]],
        "requirement_ids": list(unit["document_requirement_ids"]), "related_claim_ids": [prior], "is_key_point": False,
    }
    return {
        "schema": "bidops.deep-review-stage.v2", "deep_review_id": str(uuid4()), "attempt_id": str(uuid4()),
        "stage": STAGES[1], "claims": [claim], "evidence": [local_evidence], "unknowns": [], "warnings": [],
        "coverage": [{"source_unit_id": unit["requirement_id"], "status": "reviewed", "claim_ids": [claim["claim_id"]], "reason": None}],
        "considered_claim_ids": [prior],
    }


def _break(output: dict, row: dict, change: str) -> None:
    claim, evidence = output["claims"][0], output["evidence"][0]
    path = row["graph_paths"][0]
    if change == "dangling_evidence":
        claim["evidence_ids"] = [str(uuid4())]
    elif change == "graph_node_as_evidence":
        claim["evidence_ids"] = [path["node_ids"][0]]
    elif change == "graph_edge_as_relation":
        claim["related_claim_ids"] = [path["edge_ids"][0] if path["edge_ids"] else path["node_ids"][0]]
    elif change == "considered_not_supplied":
        output["considered_claim_ids"] = [str(uuid4())]
    elif change == "considered_local":
        output["considered_claim_ids"] = [claim["claim_id"]]
    elif change == "coverage_missing":
        output["coverage"] = []
    elif change == "requirement_missing":
        claim["requirement_ids"] = []
    elif change == "unit_as_requirement":
        claim["requirement_ids"] = [row["requirements"][0]["requirement_id"]]
    elif change == "profile_not_supplied":
        evidence["profile_evidence_id"] = str(uuid4())
    elif change == "profile_quote_changed":
        evidence["quote"] = evidence["quote"] + " 추가 실적"
    elif change == "profile_version_changed":
        evidence["profile_version_id"] = str(uuid4())
    elif change == "profile_hash_changed":
        evidence["source_sha256"] = "0" * 64
    elif change == "profile_locator_changed":
        evidence["locator"] = {"fact_key": "another-fact"}
    else:  # pragma: no cover - parametrize guard
        raise AssertionError(change)


@pytest.mark.parametrize(("change", "expected"), [
    ("dangling_evidence", "evidence_out_of_slice"),
    ("graph_node_as_evidence", "evidence_out_of_slice"),
    ("graph_edge_as_relation", "claim_relation_out_of_slice"),
    ("considered_not_supplied", "considered_claim_out_of_slice"),
    ("considered_local", "considered_claim_out_of_slice"),
    ("coverage_missing", "source_coverage_mismatch"),
    ("requirement_missing", "requirement_coverage_mismatch"),
    ("unit_as_requirement", "requirement_coverage_mismatch"),
    ("profile_not_supplied", "profile_evidence_out_of_slice"),
    ("profile_quote_changed", "profile_evidence_mismatch"),
    ("profile_version_changed", "profile_evidence_mismatch"),
    ("profile_hash_changed", "profile_evidence_mismatch"),
    ("profile_locator_changed", "profile_evidence_mismatch"),
])
def test_t5_company_slice_output_keeps_required_guards_and_the_original(change, expected) -> None:
    _frozen, row = _company_slice()
    valid = _valid_output(row)
    snapshot = deepcopy(valid)
    validate_company_slice_output(valid, row, STAGES[1])
    assert valid == snapshot
    broken = deepcopy(valid)
    _break(broken, row, change)
    original = deepcopy(broken)
    slice_before = deepcopy(row)
    assert _code(lambda: validate_company_slice_output(broken, row, STAGES[1])) == expected
    assert broken == original and row == slice_before  # raw response and frozen slice untouched


def test_t5_company_profile_evidence_cannot_enter_source_or_synthesis_slices() -> None:
    frozen, row = _company_slice()
    output = _valid_output(row)
    policy = demo_policy()
    first = company_stage_slices(STAGES[0], frozen, [], policy)
    source_slice = next(item for item in first if item["requirements"][0]["requirement_id"] == row["requirements"][0]["requirement_id"])
    stage_one = {**deepcopy(output), "stage": STAGES[0], "considered_claim_ids": []}
    stage_one["claims"][0]["related_claim_ids"] = []
    assert _code(lambda: validate_company_slice_output(stage_one, source_slice, STAGES[0])) == "profile_evidence_out_of_slice"


def test_t5_company_fact_numbers_must_appear_in_the_cited_profile_quote() -> None:
    frozen, row = _company_slice()
    output = _valid_output(row)
    profile = company_validation_profile(frozen)
    assert set(profile) == {"profile_version_id", "profile_sha256", "evidence"}
    assert profile["profile_version_id"] == frozen["profile_version_id"]
    assert profile["evidence"] == frozen["profile_evidence"]
    context = {"known_claim_ids": {claim["claim_id"] for claim in row["verified_claims"]}}
    validated = validate_deep_review_stage(output, profile=profile, profile_version_id=frozen["profile_version_id"], **context)
    assert validated == output
    invented = deepcopy(output)
    invented["claims"][0]["body"] = "가상 회사는 관련 인력 987명을 보유한다."
    original = deepcopy(invented)
    with pytest.raises(DeepReviewValidationError, match="fact_number_not_in_evidence"):
        validate_deep_review_stage(invented, profile=profile, profile_version_id=frozen["profile_version_id"], **context)
    assert invented == original
    foreign = deepcopy(output)
    foreign["evidence"][0]["quote"] = "입력에 없는 회사 실적"
    with pytest.raises(DeepReviewValidationError, match="evidence_quote_mismatch"):
        validate_deep_review_stage(foreign, profile=profile, profile_version_id=frozen["profile_version_id"], **context)


def test_t4_frozen_preview_uses_the_hp_policy_identity(world_session) -> None:
    session, world, svc = world_session
    response = preview(session, svc, world)
    frozen = response["input"]
    assert frozen["policy_version_id"] == str(world.policy_id)
    assert frozen["policy_sha256"] == HP_SHA256
    assert UUID(frozen["execution_nonce"]) == UUID(response["preview_id"])
