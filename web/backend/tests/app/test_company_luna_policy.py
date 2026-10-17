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
    RL_LUNA_POLICY_FILE,
    RL_LUNA_POLICY_FILE_V2,
    RL_LUNA_POLICY_FILE_V3,
    RL_LUNA_POLICY_FILE_V4,
    RL_LUNA_POLICY_FILE_V5,
    RL_LUNA_POLICY_FILE_V6,
    InputVersionError,
    _approved_policy_path,
    _policy_hash_matches,
    canonical_json_hash,
    import_policy_version,
    load_canonical_policy,
    resolve_active_versions,
    validate_pinned_policy,
)
from app.deep_review.services import luna_identity
from app.deep_review.services.luna_identity import (
    COMPANY_POLICY_IDENTITIES,
    HP_POLICY_IDENTITY,
    RL_POLICY_IDENTITIES,
    RL_POLICY_IDENTITY,
    RL_POLICY_IDENTITY_V2,
    RL_POLICY_IDENTITY_V3,
    RL_POLICY_IDENTITY_V4,
    RL_POLICY_IDENTITY_V5,
    RL_POLICY_IDENTITY_V6,
)
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
    # RL-03 spec "정책 행·선택" adds the card-v1 identities (v2: 결정 B23, v3: 결정 B30); the two HP-00
    # files are unchanged.
    assert COMPANY_POLICY_IDENTITIES == frozenset({
        DEMO_LUNA_POLICY_IDENTITY, HP_POLICY_IDENTITY, RL_POLICY_IDENTITY, RL_POLICY_IDENTITY_V2,
        RL_POLICY_IDENTITY_V3, RL_POLICY_IDENTITY_V4, RL_POLICY_IDENTITY_V5, RL_POLICY_IDENTITY_V6,
    })
    assert RL_POLICY_IDENTITIES == frozenset({
        "analysis-policy-luna-rl-v1", "analysis-policy-luna-rl-v2", "analysis-policy-luna-rl-v3",
        "analysis-policy-luna-rl-v4", "analysis-policy-luna-rl-v5", "analysis-policy-luna-rl-v6"})
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


# --- RL-03 STEP-001: card-v1 policy identity, closed validator, import, selection env ---

RL_SHA256 = "9687c49be2cfb0400b97aaa038d19536e2b6a7b792ab957569ef9bc319976c4a"
RL_COMPANY_INPUT_RULE = (
    "회사 입력은 실회사 ㈜루트랩의 등록 사실이며 origin은 company_brochure·homepage·user_interview·agent_proposal 중 하나다. "
    "status가 confirmed인 사실만 보유·수행·자격의 근거다. "
    "proposed(에이전트 제안값)와 unknown은 확인되지 않은 값이며 보유·미보유 어느 쪽 근거도 아니다."
)


def rl_policy() -> dict:
    payload, _raw, _digest = load_canonical_policy(RL_LUNA_POLICY_FILE)
    return payload


def test_rl_card_policy_is_canonical_pinned_and_follows_the_hp03_wire() -> None:
    raw = RL_LUNA_POLICY_FILE.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE)
    assert RL_LUNA_POLICY_FILE.name == "analysis-policy-luna-rl-v1.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_SHA256
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE
    assert set(payload) == {
        "schema", "policy_identity", "pipeline_version", "model_endpoint_ref", "model_name",
        "model_revision", "generation", "quality_status", "chunking", "execution", "card",
        "prompt_output_contract", "stage_schema", "report_schema", "stages", "validation",
    }
    assert payload["schema"] == "bidops.analysis-policy.v2"
    assert payload["policy_identity"] == RL_POLICY_IDENTITY == "analysis-policy-luna-rl-v1"
    assert payload["pipeline_version"] == "card-v1"
    # HP-00 identity is read from the identity module, never a second copy.
    assert payload["model_endpoint_ref"] == luna_identity.PROVIDER
    assert payload["model_name"] == luna_identity.MODEL
    assert payload["generation"] == {"reasoning_effort": luna_identity.REASONING_EFFORT}
    assert payload["execution"] == {
        "automatic_retry": False, "cli_version": luna_identity.CLI_VERSION, "review_timeout_seconds": 3600,
        "timeout_seconds": 900, "validation_repair_attempts": 1,
    }
    assert payload["model_revision"] is None
    assert payload["quality_status"] == "unmeasured_reference"
    assert payload["stage_schema"] == "bidops.requirement-extract.v1"
    assert payload["report_schema"] == "bidops.practitioner-verdict.v1"
    assert payload["card"] == {"batch_size": 8, "batch_max_chars": 12000, "repair_attempts": 1, "target_seconds": 2400}
    assert {key: payload["chunking"][key] for key in ("source_characters", "max_requirements", "timeout_seconds", "path_limit_per_requirement")} == {
        "source_characters": 12000, "max_requirements": 8, "timeout_seconds": 900, "path_limit_per_requirement": 32,
    }
    assert [row["stage"] for row in payload["stages"]] == [
        "extract", "eligibility_economics", "technical_fit", "operations_risk", "synthesis",
    ]
    assert payload["validation"] == {
        "allowed_repair": "syntax_or_schema_only", "company_claims": "supplied_basis_only",
        "evidence": "exact_frozen_quote", "human_decision": "never",
    }
    contract = payload["prompt_output_contract"]
    assert set(contract) == {"input_rule", "evidence_rule", "unknown_rule", "repair_rule", "company_input_rule"}
    assert contract["company_input_rule"] == RL_COMPANY_INPUT_RULE
    # No narrative-v2 claim/recommendation rule and no fictional-company wording.
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("fictional_scenario", "claim_rule", "recommendation", "hp-onweb", "온웹"):
        assert forbidden not in text, forbidden
    assert _policy_execution_limit(payload, "review_timeout_seconds", default=7200, minimum=1, maximum=86400) == 3600
    assert _policy_execution_limit(payload, "validation_repair_attempts", default=0, minimum=0, maximum=1) == 1


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.__setitem__("hp", p.pop("card")), "RL card analysis policy identity"),
        (lambda p: p.__setitem__("pipeline_version", "narrative-v2"), "RL card analysis policy identity"),
        (lambda p: p.__setitem__("model_name", "gpt-5.6-luna"), "RL card analysis policy identity"),
        (lambda p: p["generation"].__setitem__("reasoning_effort", "xhigh"), "RL card analysis policy identity"),
        (lambda p: p.__setitem__("model_revision", "0" * 64), "RL card analysis policy identity"),
        (lambda p: p.__setitem__("quality_status", None), "RL card analysis policy identity"),
        (lambda p: p["card"].__setitem__("batch_size", 9), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("batch_size", True), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("batch_max_chars", 12001), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("repair_attempts", 2), "RL card analysis policy가"),
        (lambda p: p["execution"].__setitem__("cli_version", "0.155.1"), "RL card analysis policy가"),
        (lambda p: p["execution"].__setitem__("review_timeout_seconds", 18000), "RL card analysis policy가"),
        (lambda p: p["prompt_output_contract"].pop("company_input_rule"), "RL card analysis policy가"),
        (lambda p: p["prompt_output_contract"].__setitem__("claim_rule", "x"), "RL card analysis policy가"),
        (lambda p: p["stages"].reverse(), "RL card analysis policy가"),
        (lambda p: p["validation"].__setitem__("human_decision", "auto"), "RL card analysis policy가"),
        (lambda p: p["chunking"].pop("path_limit_per_requirement"), "path_limit_per_requirement"),
        # A closed-valid but unapproved value still differs from the approved bytes.
        (lambda p: p["card"].__setitem__("batch_size", 7), "승인되지 않은"),
        (lambda p: p["prompt_output_contract"].__setitem__("company_input_rule", RL_COMPANY_INPUT_RULE + " "), "승인되지 않은"),
    ],
)
def test_rl_card_policy_rejects_open_or_unapproved_candidates(tmp_path, mutate, match) -> None:
    candidate = deepcopy(rl_policy())
    mutate(candidate)
    with pytest.raises(InputVersionError, match=match):
        load_canonical_policy(write_candidate(tmp_path, candidate))


def test_rl_card_identity_never_falls_back_and_other_identities_keep_their_files(tmp_path) -> None:
    unknown = deepcopy(rl_policy())
    unknown["policy_identity"] = "analysis-policy-luna-rl-v4"
    with pytest.raises(InputVersionError, match="identity"):
        load_canonical_policy(write_candidate(tmp_path, unknown))
    # v1 content under the v2 identity lacks the v2 selector key (결정 B23).
    renamed_v2 = deepcopy(rl_policy())
    renamed_v2["policy_identity"] = RL_POLICY_IDENTITY_V2
    with pytest.raises(InputVersionError, match="RL card analysis policy가"):
        load_canonical_policy(write_candidate(tmp_path, renamed_v2))
    # The RL card content under an existing identity is not that identity's file.
    for identity in (HP_POLICY_IDENTITY, DEMO_LUNA_POLICY_IDENTITY):
        renamed = deepcopy(rl_policy())
        renamed["policy_identity"] = identity
        with pytest.raises(InputVersionError, match="승인되지 않은"):
            load_canonical_policy(write_candidate(tmp_path, renamed))
    assert _approved_policy_path(hp_policy()) == HP_LUNA_POLICY_FILE
    assert _approved_policy_path(demo_policy()) == DEMO_LUNA_POLICY_FILE
    assert _approved_policy_path(v5_policy()) == LUNA_V5_POLICY_FILE


def test_rl_card_policy_imports_as_an_immutable_company_only_row(engine) -> None:
    with Session(engine) as session:
        row = import_policy_version(session, RL_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                    label="analysis-policy-luna-rl-v1")
        session.commit()
        assert row.policy_sha256 == RL_SHA256
        assert (row.model_endpoint_ref, row.model_name) == ("codex-exec", "gpt-6-luna")
        assert row.prompts == rl_policy()["stages"]
        assert luna_identity.policy_reasoning_effort(row) == "high"
        assert luna_identity.matches_runtime(row.model_name, luna_identity.policy_reasoning_effort(row))
        assert _policy_hash_matches(row)
        validate_pinned_policy(row, allow_unmeasured_reference=True)
        snapshot = {key: value for key, value in _policy_payload(row).items() if key != "policy_sha256"}
        assert snapshot == rl_policy()
        # Idempotent replay returns the same immutable row.
        assert import_policy_version(session, RL_LUNA_POLICY_FILE, created_by_name="정책 담당자").id == row.id
        # A company policy can never be the global active deep-review policy.
        profile = import_profile_version_for_global(session)
        with pytest.raises(InputVersionError, match="회사 전용"):
            resolve_active_versions(
                session,
                environ={"BIDOPS_ACTIVE_PROFILE_VERSION_ID": str(profile.id),
                         "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": str(row.id)},
                allow_unmeasured_reference=True,
            )


RL_V2_SHA256 = "e733e94a02b1240794ac50b7397d3974fb241917cf73fdeed009ba4ba0c4ff3b"


def rl_policy_v2() -> dict:
    payload, _raw, _digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V2)
    return payload


def test_rl_card_policy_v2_is_canonical_pinned_and_differs_from_v1_only_by_identity_selector_and_synthesis_rule() -> None:
    # 결정 B23: a new immutable file; v1 bytes and sha are unchanged.  결정 B24: the v2 synthesis
    # instruction also tells the model about missing_sections and the "진행 가능" cap.
    raw = RL_LUNA_POLICY_FILE_V2.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V2)
    assert RL_LUNA_POLICY_FILE_V2.name == "analysis-policy-luna-rl-v2.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_V2_SHA256
    assert hashlib.sha256(RL_LUNA_POLICY_FILE.read_bytes()).hexdigest() == RL_SHA256
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE_V2
    assert payload["policy_identity"] == RL_POLICY_IDENTITY_V2 == "analysis-policy-luna-rl-v2"
    assert payload["pipeline_version"] == "card-v1"
    assert payload["card"] == {"batch_size": 8, "batch_max_chars": 12000, "repair_attempts": 1,
                               "target_seconds": 2400, "selector": "card-sections-v2"}
    expected = deepcopy(rl_policy())
    expected["policy_identity"] = RL_POLICY_IDENTITY_V2
    expected["card"]["selector"] = "card-sections-v2"
    expected["stages"][4]["instruction"] += (
        " The input missing_sections lists the source areas the selector did not find in the notice;"
        " their requirements are unknown. While missing_sections is non-empty the verdict must not be"
        " \"진행 가능\" (the highest allowed verdict is \"조건부 진행\")."
    )
    assert expected["stages"][4]["stage"] == "synthesis"
    assert payload == expected


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p["card"].pop("selector"), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v1"), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v3"), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("selector_extra", "x"), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("batch_size", 7), "승인되지 않은"),
    ],
)
def test_rl_card_policy_v2_rejects_open_or_unapproved_candidates(tmp_path, mutate, match) -> None:
    candidate = deepcopy(rl_policy_v2())
    mutate(candidate)
    with pytest.raises(InputVersionError, match=match):
        load_canonical_policy(write_candidate(tmp_path, candidate))


def test_rl_card_policy_v1_cannot_carry_a_selector(tmp_path) -> None:
    candidate = deepcopy(rl_policy())
    candidate["card"]["selector"] = "card-sections-v2"
    with pytest.raises(InputVersionError, match="RL card analysis policy가"):
        load_canonical_policy(write_candidate(tmp_path, candidate))


def test_rl_card_policy_v2_imports_beside_v1_and_resolves_its_selector(engine, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.deep_review.services.company_deep_review import resolve_company_deep_policy

    with Session(engine) as session:
        v1 = import_policy_version(session, RL_LUNA_POLICY_FILE, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-rl-v1")
        v2 = import_policy_version(session, RL_LUNA_POLICY_FILE_V2, created_by_name="정책 담당자",
                                   label="analysis-policy-luna-rl-v2")
        session.commit()
        assert v1.id != v2.id and v2.policy_sha256 == RL_V2_SHA256
        assert _policy_hash_matches(v2)
        validate_pinned_policy(v2, allow_unmeasured_reference=True)
        selectors = {}
        for row in (v1, v2):
            settings = SimpleNamespace(rl_deep_review_policy_version_id=row.id, analysis_provider="vllm",
                                       reference_workflow_mode=True)
            resolved = resolve_company_deep_policy(session, settings, rl=True)
            assert resolved.pipeline_version == "card-v1"
            selectors[_policy_payload(row)["policy_identity"]] = resolved.selector_version
        assert selectors == {RL_POLICY_IDENTITY: "card-sections-v1", RL_POLICY_IDENTITY_V2: "card-sections-v2"}


RL_V3_SHA256 = "635f673063ca1a92fb751aea6ffbdb76c54e0d70309b9f0a1e84d961fe192b12"


def rl_policy_v3() -> dict:
    payload, _raw, _digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V3)
    return payload


def test_b30_rl_card_policy_v3_is_pinned_and_differs_from_v2_only_by_identity_selector_and_extract_rule() -> None:
    # 결정 B30: a new immutable file; v1/v2 bytes and shas are unchanged.  Only the extract
    # instruction is rewritten; role and synthesis instructions (incl. B24) are v2's.
    raw = RL_LUNA_POLICY_FILE_V3.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V3)
    assert RL_LUNA_POLICY_FILE_V3.name == "analysis-policy-luna-rl-v3.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_V3_SHA256
    assert hashlib.sha256(RL_LUNA_POLICY_FILE.read_bytes()).hexdigest() == RL_SHA256
    assert hashlib.sha256(RL_LUNA_POLICY_FILE_V2.read_bytes()).hexdigest() == RL_V2_SHA256
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE_V3
    assert payload["policy_identity"] == RL_POLICY_IDENTITY_V3 == "analysis-policy-luna-rl-v3"
    assert payload["card"] == {"batch_size": 8, "batch_max_chars": 12000, "repair_attempts": 1,
                               "target_seconds": 2400, "selector": "card-sections-v3"}
    v2 = rl_policy_v2()
    expected = deepcopy(v2)
    expected["policy_identity"] = RL_POLICY_IDENTITY_V3
    expected["card"]["selector"] = "card-sections-v3"
    expected["stages"][0]["instruction"] = payload["stages"][0]["instruction"]
    assert payload == expected
    assert payload["stages"][1:] == v2["stages"][1:]
    assert "missing_sections" in payload["stages"][4]["instruction"]
    extract = payload["stages"][0]
    assert extract["stage"] == "extract" and extract["instruction"] != v2["stages"][0]["instruction"]
    # the validation contract is stated explicitly (B30 (1))
    for phrase in (
        "exactly one item per input unit, in input order", "Several conditions of one unit",
        "only a title still yields one item", "expected_concepts", "copy every {concept_id, alias_text} pair",
        "Never map text to a concept by meaning", "exact substring", "YYYY-MM-DD", "kind=text",
        "unit=person only for a count written as N명", "이상 or 최소 means gte", "이하, 이내, or 최대 means lte",
        "Never repeat an identical constraint", "fact_key is always null",
    ):
        assert phrase in extract["instruction"], phrase


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p["card"].pop("selector"), "RL card analysis policy가"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v2"), "RL card analysis policy가"),
        (lambda p: p["stages"][0].__setitem__("instruction", ""), "RL card analysis policy가"),
        (lambda p: p["stages"][0].__setitem__("instruction", "Extract."), "승인되지 않은"),
        (lambda p: p["card"].__setitem__("batch_size", 7), "승인되지 않은"),
    ],
)
def test_b30_rl_card_policy_v3_rejects_open_or_unapproved_candidates(tmp_path, mutate, match) -> None:
    candidate = deepcopy(rl_policy_v3())
    mutate(candidate)
    with pytest.raises(InputVersionError, match=match):
        load_canonical_policy(write_candidate(tmp_path, candidate))


def test_b30_v2_content_under_the_v3_identity_is_rejected(tmp_path) -> None:
    renamed = deepcopy(rl_policy_v2())
    renamed["policy_identity"] = RL_POLICY_IDENTITY_V3
    with pytest.raises(InputVersionError, match="RL card analysis policy가"):
        load_canonical_policy(write_candidate(tmp_path, renamed))
    renamed["card"]["selector"] = "card-sections-v3"
    with pytest.raises(InputVersionError, match="승인되지 않은"):
        load_canonical_policy(write_candidate(tmp_path, renamed))


def test_b30_rl_card_policy_v3_imports_beside_v1_v2_and_resolves_its_selector(engine) -> None:
    from types import SimpleNamespace

    from app.deep_review.services.company_deep_review import resolve_company_deep_policy

    with Session(engine) as session:
        rows = [
            import_policy_version(session, path, created_by_name="정책 담당자", label=label)
            for path, label in ((RL_LUNA_POLICY_FILE, "analysis-policy-luna-rl-v1"),
                                (RL_LUNA_POLICY_FILE_V2, "analysis-policy-luna-rl-v2"),
                                (RL_LUNA_POLICY_FILE_V3, "analysis-policy-luna-rl-v3"))
        ]
        session.commit()
        assert len({row.id for row in rows}) == 3 and rows[2].policy_sha256 == RL_V3_SHA256
        assert _policy_hash_matches(rows[2])
        validate_pinned_policy(rows[2], allow_unmeasured_reference=True)
        selectors = {}
        for row in rows:
            settings = SimpleNamespace(rl_deep_review_policy_version_id=row.id, analysis_provider="vllm",
                                       reference_workflow_mode=True)
            resolved = resolve_company_deep_policy(session, settings, rl=True)
            assert resolved.pipeline_version == "card-v1"
            selectors[_policy_payload(row)["policy_identity"]] = resolved.selector_version
        assert selectors == {RL_POLICY_IDENTITY: "card-sections-v1", RL_POLICY_IDENTITY_V2: "card-sections-v2",
                             RL_POLICY_IDENTITY_V3: "card-sections-v3"}


RL_V4_SHA256 = "8cc623f280ca5d155073ecd261f5a2a1ecd3a8d497fc5aec9c815537923183d7"


def rl_policy_v4() -> dict:
    payload, _raw, _digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V4)
    return payload


def test_b33_rl_card_policy_v4_is_pinned_and_differs_from_v3_only_by_identity_stage_schema_and_extract_rule() -> None:
    raw = RL_LUNA_POLICY_FILE_V4.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V4)
    assert RL_LUNA_POLICY_FILE_V4.name == "analysis-policy-luna-rl-v4.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_V4_SHA256
    for path, sha in ((RL_LUNA_POLICY_FILE, RL_SHA256), (RL_LUNA_POLICY_FILE_V2, RL_V2_SHA256),
                      (RL_LUNA_POLICY_FILE_V3, RL_V3_SHA256)):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE_V4
    assert payload["policy_identity"] == RL_POLICY_IDENTITY_V4 == "analysis-policy-luna-rl-v4"
    assert payload["stage_schema"] == "bidops.requirement-extract.v2"
    assert payload["card"]["selector"] == "card-sections-v3"
    v3 = rl_policy_v3()
    expected = deepcopy(v3)
    expected["policy_identity"] = RL_POLICY_IDENTITY_V4
    expected["stage_schema"] = "bidops.requirement-extract.v2"
    expected["stages"][0]["instruction"] = payload["stages"][0]["instruction"]
    assert payload == expected
    assert payload["stages"][1:] == v3["stages"][1:]  # role and synthesis (incl. B24) unchanged
    extract = payload["stages"][0]["instruction"]
    assert extract != v3["stages"][0]["instruction"]
    for phrase in (
        "bidops.requirement-extract.v2", "exactly one item per input unit, in input order",
        "Do not output ontology concepts or constraint operators", "kind/unit table",
        "count = unit person only for N명, otherwise unit null", "date = unit null, value YYYY-MM-DD",
        "N시간", "N일 이내", "다음 달 N일까지", "kind=text with unit null",
        "quotes the shortest exact substring that holds only that number", "fact_key is always null",
        "Never repeat an identical constraint",
    ):
        assert phrase in extract, phrase
    assert "expected_concepts" not in extract and "concept_candidates" not in extract


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.__setitem__("stage_schema", "bidops.requirement-extract.v1"), "RL card analysis policy identity"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v2"), "RL card analysis policy가"),
        (lambda p: p["card"].pop("selector"), "RL card analysis policy가"),
        (lambda p: p["stages"][0].__setitem__("instruction", "Extract."), "승인되지 않은"),
    ],
)
def test_b33_rl_card_policy_v4_rejects_open_or_unapproved_candidates(tmp_path, mutate, match) -> None:
    candidate = deepcopy(rl_policy_v4())
    mutate(candidate)
    with pytest.raises(InputVersionError, match=match):
        load_canonical_policy(write_candidate(tmp_path, candidate))


def test_b33_stage_schema_is_bound_to_the_identity(tmp_path) -> None:
    # the v2 output contract under the v3 identity, or v3 content under the v4 identity, never loads
    v3_with_v2 = deepcopy(rl_policy_v3())
    v3_with_v2["stage_schema"] = "bidops.requirement-extract.v2"
    with pytest.raises(InputVersionError, match="RL card analysis policy identity"):
        load_canonical_policy(write_candidate(tmp_path, v3_with_v2))
    v3_as_v4 = deepcopy(rl_policy_v3())
    v3_as_v4["policy_identity"] = RL_POLICY_IDENTITY_V4
    with pytest.raises(InputVersionError, match="RL card analysis policy identity"):
        load_canonical_policy(write_candidate(tmp_path, v3_as_v4))


def test_b33_rl_card_policy_v4_imports_beside_v1_to_v3_and_resolves_selector_v3(engine) -> None:
    from types import SimpleNamespace

    from app.deep_review.services.company_deep_review import resolve_company_deep_policy

    with Session(engine) as session:
        rows = [
            import_policy_version(session, path, created_by_name="정책 담당자", label=path.stem)
            for path in (RL_LUNA_POLICY_FILE, RL_LUNA_POLICY_FILE_V2, RL_LUNA_POLICY_FILE_V3, RL_LUNA_POLICY_FILE_V4)
        ]
        session.commit()
        assert len({row.id for row in rows}) == 4 and rows[3].policy_sha256 == RL_V4_SHA256
        validate_pinned_policy(rows[3], allow_unmeasured_reference=True)
        settings = SimpleNamespace(rl_deep_review_policy_version_id=rows[3].id, analysis_provider="vllm",
                                   reference_workflow_mode=True)
        resolved = resolve_company_deep_policy(session, settings, rl=True)
        assert resolved.pipeline_version == "card-v1" and resolved.selector_version == "card-sections-v3"
        assert _policy_payload(rows[3])["stage_schema"] == "bidops.requirement-extract.v2"


RL_V5_SHA256 = "19d7ff26fb9899f95237ec931c440bfad89feb42e3626fba89c33132f42928b2"


def test_b35_rl_card_policy_v5_is_pinned_and_differs_from_v4_only_by_identity_and_extract_rule(tmp_path, engine) -> None:
    from types import SimpleNamespace

    from app.deep_review.services.company_deep_review import resolve_company_deep_policy

    raw = RL_LUNA_POLICY_FILE_V5.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V5)
    assert RL_LUNA_POLICY_FILE_V5.name == "analysis-policy-luna-rl-v5.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_V5_SHA256
    assert hashlib.sha256(RL_LUNA_POLICY_FILE_V4.read_bytes()).hexdigest() == RL_V4_SHA256
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE_V5
    v4 = rl_policy_v4()
    expected = deepcopy(v4)
    expected["policy_identity"] = RL_POLICY_IDENTITY_V5 == "analysis-policy-luna-rl-v5" and RL_POLICY_IDENTITY_V5
    expected["stages"][0]["instruction"] = payload["stages"][0]["instruction"]
    assert payload == expected  # same v2 wire (stage_schema) and selector card-sections-v3
    assert payload["stage_schema"] == "bidops.requirement-extract.v2" and payload["card"]["selector"] == "card-sections-v3"
    assert payload["stages"][1:] == v4["stages"][1:]
    extract = payload["stages"][0]["instruction"]
    assert extract != v4["stages"][0]["instruction"]
    for phrase in (
        "quotes the number together with its unit word and any comparator attached",
        "5일 이상", "9글자 이상", "90%를 초과", "3회 미만", "3초 내에", "4시간 이내",
        "Never quote a bare number", "N분, N초, N글자", "N시간", "10분 간격", "kind=text with unit null",
        "exactly one item per input unit, in input order", "fact_key is always null",
        "count = unit person only for N명",
    ):
        assert phrase in extract, phrase
    assert "shortest exact substring" not in extract  # the v4 wording that induced bare numbers
    for mutate, match in (
        (lambda p: p.__setitem__("stage_schema", "bidops.requirement-extract.v1"), "RL card analysis policy identity"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v2"), "RL card analysis policy가"),
        (lambda p: p["stages"][0].__setitem__("instruction", "Extract."), "승인되지 않은"),
    ):
        candidate = deepcopy(payload)
        mutate(candidate)
        with pytest.raises(InputVersionError, match=match):
            load_canonical_policy(write_candidate(tmp_path, candidate))
    with Session(engine) as session:
        row = import_policy_version(session, RL_LUNA_POLICY_FILE_V5, created_by_name="정책 담당자",
                                    label="analysis-policy-luna-rl-v5")
        session.commit()
        assert row.policy_sha256 == RL_V5_SHA256
        validate_pinned_policy(row, allow_unmeasured_reference=True)
        settings = SimpleNamespace(rl_deep_review_policy_version_id=row.id, analysis_provider="vllm",
                                   reference_workflow_mode=True)
        resolved = resolve_company_deep_policy(session, settings, rl=True)
        assert resolved.pipeline_version == "card-v1" and resolved.selector_version == "card-sections-v3"


RL_V6_SHA256 = "84e94954c08a43e5751d1514cf1a02e6865c9d6f05c6483777785e29faf8534a"


def test_b37_rl_card_policy_v6_is_pinned_and_differs_from_v5_only_by_identity_and_extract_rule(tmp_path, engine) -> None:
    from types import SimpleNamespace

    from app.deep_review.services.company_deep_review import resolve_company_deep_policy

    raw = RL_LUNA_POLICY_FILE_V6.read_bytes()
    payload, canonical, digest = load_canonical_policy(RL_LUNA_POLICY_FILE_V6)
    assert RL_LUNA_POLICY_FILE_V6.name == "analysis-policy-luna-rl-v6.json"
    assert raw == canonical == canonical_json_bytes(payload)
    assert digest == hashlib.sha256(raw).hexdigest() == RL_V6_SHA256
    assert hashlib.sha256(RL_LUNA_POLICY_FILE_V5.read_bytes()).hexdigest() == RL_V5_SHA256
    assert _approved_policy_path(payload) == RL_LUNA_POLICY_FILE_V6
    v5, _raw5, _digest5 = load_canonical_policy(RL_LUNA_POLICY_FILE_V5)
    expected = deepcopy(v5)
    expected["policy_identity"] = RL_POLICY_IDENTITY_V6
    expected["stages"][0]["instruction"] = payload["stages"][0]["instruction"]
    assert payload == expected and RL_POLICY_IDENTITY_V6 == "analysis-policy-luna-rl-v6"
    assert payload["stages"][1:] == v5["stages"][1:]
    extract = payload["stages"][0]["instruction"]
    # v6 = v5 with sentences inserted at the end of rule (4); every v5 sentence is kept in order
    anchor = "and it is never repaired. "
    head, tail = v5["stages"][0]["instruction"].split(anchor)
    assert extract.startswith(head + anchor) and extract.endswith(tail)
    added = extract[len(head + anchor):len(extract) - len(tail)]
    assert added.startswith("A numeric quote must occur exactly once") and tail.startswith("(5) Constraints")
    for phrase in (
        "A numeric quote must occur exactly once in its block",
        "extend the quote with the adjacent words on its left until it is unique",
        "월 1회", "연 1회 이상", "a repeated quote is rejected and never repaired",
        "A date range written as A ～ B", "is kind=text with the range copied verbatim",
        "never compute a duration, count, or any other number that is not written in the quote",
        "5일 이상", "90%를 초과", "fact_key is always null",
    ):
        assert phrase in extract, phrase
    for mutate, match in (
        (lambda p: p.__setitem__("stage_schema", "bidops.requirement-extract.v1"), "RL card analysis policy identity"),
        (lambda p: p["card"].__setitem__("selector", "card-sections-v2"), "RL card analysis policy가"),
        (lambda p: p["stages"][0].__setitem__("instruction", "Extract."), "승인되지 않은"),
    ):
        candidate = deepcopy(payload)
        mutate(candidate)
        with pytest.raises(InputVersionError, match=match):
            load_canonical_policy(write_candidate(tmp_path, candidate))
    with Session(engine) as session:
        row = import_policy_version(session, RL_LUNA_POLICY_FILE_V6, created_by_name="정책 담당자",
                                    label="analysis-policy-luna-rl-v6")
        session.commit()
        assert row.policy_sha256 == RL_V6_SHA256
        validate_pinned_policy(row, allow_unmeasured_reference=True)
        settings = SimpleNamespace(rl_deep_review_policy_version_id=row.id, analysis_provider="vllm",
                                   reference_workflow_mode=True)
        resolved = resolve_company_deep_policy(session, settings, rl=True)
        assert resolved.pipeline_version == "card-v1" and resolved.selector_version == "card-sections-v3"


def import_profile_version_for_global(session):
    from app.deep_review.services.input_versions import import_profile_version

    profile = import_profile_version(session, created_by_name="정책 담당자", label="company-profile")
    session.commit()
    return profile


def test_rl_selection_env_is_separate_from_demo_and_defaults_closed(monkeypatch) -> None:
    from app.core.config import DEFAULT_RL_ANALYSIS_POLICY_PATH, Settings

    for name in ("BIDOPS_RL_ANALYSIS_ENABLED", "BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED",
                 "BIDOPS_RL_ANALYSIS_POLICY_PATH", "BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID",
                 "BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.rl_analysis_enabled is False
    assert settings.rl_analysis_auto_start_enabled is False
    assert settings.rl_deep_review_policy_version_id is None
    assert settings.rl_analysis_policy_path == DEFAULT_RL_ANALYSIS_POLICY_PATH
    # 결정 B37: new imports default to the v6 file; v1-v5 stay importable by path.
    assert DEFAULT_RL_ANALYSIS_POLICY_PATH.resolve() == RL_LUNA_POLICY_FILE_V6.resolve()
    assert RL_LUNA_POLICY_FILE_V4.is_file() and RL_LUNA_POLICY_FILE_V5.is_file()
    assert RL_LUNA_POLICY_FILE.is_file() and RL_LUNA_POLICY_FILE_V2.is_file() and RL_LUNA_POLICY_FILE_V3.is_file()
    assert Settings.model_fields["rl_deep_review_policy_version_id"].validation_alias == "BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID"

    selected = uuid4()
    monkeypatch.setenv("BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID", str(selected))
    settings = Settings()
    assert settings.rl_deep_review_policy_version_id == selected
    assert settings.demo_deep_review_policy_version_id is None
    monkeypatch.setenv("BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID", "  ")
    assert Settings().rl_deep_review_policy_version_id is None
    monkeypatch.setenv("BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID", "not-a-uuid")
    with pytest.raises(ValueError):
        Settings()
