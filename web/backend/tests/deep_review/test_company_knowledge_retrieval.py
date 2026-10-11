"""DEMO-03 STEP-001 (spec T1): concept mapping, graph paths, coverage, slices.

All cases are pure: no DB session, no network, no model.  The frozen DEMO-02
fixtures are parsed through the real core validators so node/edge shapes are
the registered ones; small hand-written graphs cover edge cases.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from app.core.company_ontology import (
    OntologyConcept,
    build_graph_snapshot,
    parse_company_knowledge_source,
    parse_ontology,
)
from app.deep_review.services import company_knowledge_retrieval as retrieval
from app.deep_review.services.company_knowledge_retrieval import CompanyRetrievalError
from app.deep_review.services.narrative_inputs import NarrativeInputError


FIXTURES = Path(__file__).parents[4] / "docs" / "demo-fixtures"
RELATIONS = [
    ("has_capability", ["company"], ["capability"]),
    ("uses_technology", ["project", "capability"], ["technology"]),
    ("operates_in", ["company", "project"], ["domain"]),
    ("has_staff", ["company"], ["staff_group"]),
    ("performed", ["company"], ["project"]),
    ("supports_capability", ["project", "staff_group"], ["capability"]),
    ("holds_qualification", ["company"], ["qualification"]),
    (
        "supported_by",
        ["company", "capability", "technology", "domain", "staff_group", "project", "qualification", "requirement"],
        ["evidence"],
    ),
    ("has_requirement", ["notice"], ["requirement"]),
    ("requires_capability", ["requirement"], ["capability"]),
    ("requires_qualification", ["requirement"], ["qualification"]),
]
DOC_ID = "11111111-1111-4111-8111-111111111111"
STRUCTURE_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_SHA = "a" * 64
PROFILE_ID = "33333333-3333-4333-8333-333333333333"
RUN_ID = "44444444-4444-4444-8444-444444444444"


# --- helpers -----------------------------------------------------------------


def _ontology(concepts: list[dict]) -> object:
    payload = {
        "schema_version": "bidops.company-ontology.v1",
        "version": "test-ontology-v1",
        "concepts": concepts,
        "relations": [
            {"type": kind, "from_types": src, "to_types": dst, "evidence_required": True}
            for kind, src, dst in RELATIONS
        ],
    }
    return parse_ontology(json.dumps(payload, ensure_ascii=False).encode())


HAND_ONTOLOGY = _ontology(
    [
        {"id": "capability.ai", "label": "업무형 AI 적용", "aliases": ["AI", "인공지능"], "kind": "capability"},
        {"id": "capability.mail", "label": "전자우편 시스템", "aliases": ["mail server"], "kind": "capability"},
        {"id": "capability.platform", "label": "데이터 플랫폼", "aliases": ["데이터플랫폼"], "kind": "capability"},
        {"id": "qualification.isms", "label": "정보보호 관리체계 인증", "aliases": ["ISMS"], "kind": "qualification"},
        {"id": "technology.k8s", "label": "쿠버네티스", "aliases": ["k8s"], "kind": "technology"},
        {"id": "domain.public", "label": "공공 행정", "aliases": [], "kind": "domain"},
    ]
)


def _evidence_id(fact_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"profile-evidence:{fact_key}"))


def _fixture_graph(slug: str) -> tuple[object, list[dict], list[dict], dict]:
    """Return (ontology, public nodes, public edges, profile context) for a fixture."""

    ontology = parse_ontology((FIXTURES / "ontology.v1.json").read_bytes())
    source = parse_company_knowledge_source(
        (FIXTURES / "companies" / f"{slug}.v1.json").read_bytes(), ontology=ontology
    )
    snapshot = build_graph_snapshot(source, ontology=ontology).payload
    by_ref: dict[tuple[str, str], str] = {}
    facts, evidence = [], []
    for node in snapshot["nodes"]:
        if node["type"] == "evidence":
            continue
        facts.append({
            "fact_key": node["id"], "status": node["status"], "value": node["value"],
            "section_id": node["type"], "section_number": None,
            "locator": {"fact_key": node["id"]},
            "quote": "" if node["status"] == "unknown" else node["source_refs"][0]["quote"],
            "origin": "fictional_scenario",
        })
        if node["status"] != "unknown":
            ref = node["source_refs"][0]
            by_ref[(ref["locator"]["json_pointer"], ref["quote"])] = node["id"]
            evidence.append({
                "profile_evidence_id": _evidence_id(node["id"]), "profile_version_id": PROFILE_ID,
                "fact_key": node["id"], "source_sha256": snapshot["source_sha256"],
                "locator_type": "profile_fact", "locator": {"fact_key": node["id"]}, "quote": ref["quote"],
            })

    def ids(item: dict) -> list[str]:
        if item["type"] != "evidence" and "from_id" not in item:
            return [] if item["status"] == "unknown" else [_evidence_id(item["id"])]
        out: list[str] = []
        for ref in item["source_refs"]:
            value = _evidence_id(by_ref[(ref["locator"]["json_pointer"], ref["quote"])])
            if value not in out:
                out.append(value)
        return out

    nodes = [
        {key: node[key] for key in ("id", "type", "label", "concept_id", "status", "origin", "value")}
        | {"evidence_ids": ids(node)}
        for node in snapshot["nodes"]
    ]
    edges = [
        {key: edge[key] for key in ("id", "type", "from_id", "to_id", "status", "origin")}
        | {"evidence_ids": ids(edge)}
        for edge in snapshot["edges"]
    ]
    profile = {"profile_version_id": PROFILE_ID, "facts": facts, "evidence": evidence}
    return ontology, nodes, edges, profile


def _unit(text: str, *, block: int = 0, page: int = 1, ordinal: int = 1, doc_ids: list[str] | None = None) -> dict:
    return {
        "requirement_id": f"req-{ordinal:04d}-{page:04d}-{block:06d}-{block:010d}",
        "document_version_id": DOC_ID,
        "structure_id": STRUCTURE_ID,
        "source_sha256": SOURCE_SHA,
        "document_ordinal": ordinal,
        "page": page,
        "block_order": block,
        "locator_type": "page",
        "locator": {"page": page},
        "text": text,
        "document_requirement_ids": list(doc_ids or []),
    }


def _node(node_id: str, node_type: str, *, concept: str | None = None, status: str = "confirmed", value=None) -> dict:
    return {
        "id": node_id, "type": node_type, "label": node_id, "concept_id": concept,
        "status": status, "origin": "fictional_scenario", "value": value,
        "evidence_ids": [] if status == "unknown" or node_type == "evidence" else [_evidence_id(node_id)],
    }


def _edge(edge_id: str, kind: str, src: str, dst: str, *, status: str = "confirmed", evidence_of: str | None = None) -> dict:
    return {
        "id": edge_id, "type": kind, "from_id": src, "to_id": dst, "status": status,
        "origin": "fictional_scenario",
        "evidence_ids": [] if status == "unknown" else [_evidence_id(evidence_of or dst)],
    }


def _profile_for(nodes: list[dict]) -> dict:
    facts, evidence = [], []
    for node in nodes:
        if node["type"] == "evidence":
            continue
        unknown = node["status"] == "unknown"
        facts.append({
            "fact_key": node["id"], "status": node["status"], "value": node["value"],
            "section_id": node["type"], "section_number": None, "locator": {"fact_key": node["id"]},
            "quote": "" if unknown else f"quote {node['id']}", "origin": "fictional_scenario",
        })
        if not unknown:
            evidence.append({
                "profile_evidence_id": _evidence_id(node["id"]), "profile_version_id": PROFILE_ID,
                "fact_key": node["id"], "source_sha256": SOURCE_SHA, "locator_type": "profile_fact",
                "locator": {"fact_key": node["id"]}, "quote": f"quote {node['id']}",
            })
    return {"profile_version_id": PROFILE_ID, "facts": facts, "evidence": evidence}


def _hand_graph(project_count: int = 2) -> tuple[list[dict], list[dict]]:
    nodes = [
        _node("company", "company", value="가상 회사"),
        _node("cap-ai", "capability", concept="capability.ai", value={"scope": "core", "description": "AI"}),
        _node("cap-mail", "capability", concept="capability.mail", value={"scope": "non_core", "description": "mail"}),
        _node("qual-isms", "qualification", concept="qualification.isms", status="unknown"),
        _node("tech-k8s", "technology", concept="technology.k8s", value="쿠버네티스"),
        _node("staff-ai", "staff_group", value={"role": "AI", "total": 3, "available": None, "as_of": None}),
    ]
    edges = [
        _edge("e-company-cap-ai", "has_capability", "company", "cap-ai"),
        _edge("e-company-cap-mail", "has_capability", "company", "cap-mail"),
        _edge("e-company-qual-isms", "holds_qualification", "company", "qual-isms", status="unknown"),
        _edge("e-company-staff-ai", "has_staff", "company", "staff-ai"),
        _edge("e-staff-ai-cap-ai", "supports_capability", "staff-ai", "cap-ai", evidence_of="staff-ai"),
    ]
    for index in range(project_count):
        project = f"project-{index:02d}"
        nodes.append(_node(project, "project", value={"role": "r", "scope": "s", "amount_krw": None, "started_on": None, "ended_on": None}))
        edges.append(_edge(f"e-company-{project}", "performed", "company", project))
        edges.append(_edge(f"e-{project}-cap-ai", "supports_capability", project, "cap-ai", evidence_of=project))
        edges.append(_edge(f"e-{project}-k8s", "uses_technology", project, "tech-k8s", evidence_of=project))
    return nodes, edges


def _build(units: list[dict], *, nodes=None, edges=None, profile=None, limit: int = 32, budget: int = 100000, ontology=HAND_ONTOLOGY) -> dict:
    if nodes is None:
        nodes, edges = _hand_graph()
    requirements = retrieval.requirements_from_source_units(units, ontology)
    return retrieval.build_company_retrieval(
        requirements,
        ontology=ontology,
        graph_nodes=nodes,
        graph_edges=edges,
        profile=profile if profile is not None else _profile_for(nodes),
        path_limit_per_requirement=limit,
        profile_budget=budget,
    )


# --- term matching ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AI 기반 분석", ["capability.ai"]),
        ("(AI) 활용", ["capability.ai"]),
        ("ai/ml 파이프라인", ["capability.ai"]),
        ("AI기반 서비스", ["capability.ai"]),
        ("ＡＩ 전환", ["capability.ai"]),  # NFKC full-width
        ("mail 발송 기능", []),
        ("메일 시스템 mail server 구축", ["capability.mail"]),
        ("openai 연동과 aim 지표", []),
        ("a.i. 적용", []),
        ("데이터 플랫폼을 구축한다", ["capability.platform"]),  # 조사
        ("빅데이터플랫폼고도화 사업", ["capability.platform"]),  # 복합어 (alias)
        ("데이터   플랫폼\n고도화", ["capability.platform"]),  # whitespace collapse
        ("인공지능과 데이터 플랫폼, ISMS 보유", ["capability.ai", "capability.platform", "qualification.isms"]),
        ("K8S 기반 운영", ["technology.k8s"]),
        ("k8sx 운영", []),
        ("머신러닝 모델 개발", []),  # no synonym expansion
        ("", []),
    ],
)
def test_match_concepts_uses_only_dictionary_terms_with_hangul_substring_and_ascii_boundaries(text, expected):
    assert retrieval.match_concepts(text, HAND_ONTOLOGY) == expected


def test_match_concepts_never_matches_single_character_terms_even_if_given():
    concepts = [
        OntologyConcept(id="capability.one", label="망", aliases=("x", "망구축"), kind="capability"),
    ]
    assert retrieval.match_concepts("망 x 연결", concepts) == []
    assert retrieval.match_concepts("내부망구축 사업", concepts) == ["capability.one"]


def test_match_concepts_keeps_every_ambiguous_concept_sorted_unique():
    text = "업무형 AI 적용과 인공지능, AI 그리고 데이터플랫폼 데이터 플랫폼"
    assert retrieval.match_concepts(text, HAND_ONTOLOGY) == ["capability.ai", "capability.platform"]


def test_match_concepts_rejects_non_text_input():
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.match_concepts(None, HAND_ONTOLOGY)  # type: ignore[arg-type]
    assert error.value.code == "company_input_invalid"


# --- requirement construction ----------------------------------------------------


def test_source_unit_requirements_preserve_splitter_order_ids_and_document_requirement_ids():
    units = [
        _unit("ISMS 인증 보유 필수", block=5, doc_ids=["SFR-002"]),
        _unit("AI 기반 분석", block=1, doc_ids=["SFR-001", "SFR-010"]),
    ]
    original = deepcopy(units)
    requirements = retrieval.requirements_from_source_units(units, HAND_ONTOLOGY)

    assert units == original  # not mutated
    assert [row["id"] for row in requirements] == [units[0]["requirement_id"], units[1]["requirement_id"]]
    assert requirements[0] == {
        "id": units[0]["requirement_id"],
        "text": "ISMS 인증 보유 필수",
        "concept_ids": ["qualification.isms"],
        "mandatory": None,
        "source_units": [units[0]],
        "document_requirement_ids": ["SFR-002"],
    }
    assert requirements[1]["document_requirement_ids"] == ["SFR-001", "SFR-010"]
    requirements[1]["source_units"][0]["text"] = "changed"
    assert units[1]["text"] == "AI 기반 분석"


@pytest.mark.parametrize(
    "broken",
    [
        # Splitter fallback when no blocks exist: no document/structure/hash.
        {"requirement_id": "req-unknown-0000", "document_ordinal": 0, "page": 1, "block_order": 0,
         "locator_type": "page", "locator": {"page": 1}, "text": "", "document_requirement_ids": []},
        _unit("x") | {"document_version_id": ""},
        _unit("x") | {"structure_id": ""},
        _unit("x") | {"source_sha256": ""},
        _unit("x") | {"source_sha256": "z" * 64},
        _unit("x") | {"document_version_id": "not-a-uuid"},
        _unit("x") | {"document_version_id": DOC_ID.upper()},  # not the canonical splitter string
        _unit("x") | {"text": "   "},
        _unit("x") | {"page": 0, "locator": {"page": 0}},
        _unit("x") | {"locator": {"page": 2}},
        _unit("x") | {"locator_type": "block"},
        _unit("x") | {"page": True},
        _unit("x") | {"document_requirement_ids": "SFR-001"},
        {k: v for k, v in _unit("x").items() if k != "document_requirement_ids"},
        _unit("x") | {"source_path": "/etc/passwd"},
    ],
)
def test_fallback_or_malformed_units_fail_with_company_input_invalid(broken):
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.requirements_from_source_units([_unit("AI 분석"), broken], HAND_ONTOLOGY)
    assert error.value.code == "company_input_invalid"
    assert isinstance(error.value, NarrativeInputError)
    assert str(error.value) == "company_input_invalid"


def test_duplicate_or_empty_source_units_are_rejected():
    with pytest.raises(CompanyRetrievalError) as duplicate:
        retrieval.requirements_from_source_units([_unit("a"), _unit("b")], HAND_ONTOLOGY)
    assert duplicate.value.code == "company_input_invalid"
    with pytest.raises(CompanyRetrievalError) as empty:
        retrieval.requirements_from_source_units([], HAND_ONTOLOGY)
    assert empty.value.code == "company_input_invalid"


def test_overview_requirements_use_overview_namespace_and_link_units_by_page():
    result = {
        "business_overview": [{"text": "AI 기반 민원 분석", "evidence": [{"page": 2, "quote": "q"}]}],
        "main_tasks": [
            {"text": "데이터 플랫폼 구축", "evidence": [{"page": 3}, {"page": 2}]},
            {"text": "회의실 임차", "evidence": []},
        ],
        "budget_and_period": [],
    }
    units = [_unit("p2", page=2, block=0, doc_ids=["SFR-1"]), _unit("p3", page=3, block=0, doc_ids=["SFR-2", "SFR-1"])]
    requirements = retrieval.requirements_from_overview(RUN_ID, result, HAND_ONTOLOGY, source_units=units)

    assert [row["id"] for row in requirements] == [
        f"overview:{RUN_ID}:business_overview:0",
        f"overview:{RUN_ID}:main_tasks:0",
        f"overview:{RUN_ID}:main_tasks:1",
    ]
    assert requirements[0]["concept_ids"] == ["capability.ai"]
    assert [unit["page"] for unit in requirements[0]["source_units"]] == [2]
    assert [unit["page"] for unit in requirements[1]["source_units"]] == [2, 3]
    assert requirements[1]["document_requirement_ids"] == ["SFR-1", "SFR-2"]
    assert requirements[2]["source_units"] == [] and requirements[2]["document_requirement_ids"] == []
    assert all(row["mandatory"] is None for row in requirements)

    unlinked = retrieval.requirements_from_overview(RUN_ID, result, HAND_ONTOLOGY)
    assert all(row["source_units"] == [] for row in unlinked)


@pytest.mark.parametrize(
    "result",
    [
        {"business_overview": [], "main_tasks": []},
        {"business_overview": [{"text": 1, "evidence": []}], "main_tasks": [], "budget_and_period": []},
        {"business_overview": [{"text": "x"}], "main_tasks": [], "budget_and_period": []},
    ],
)
def test_overview_requirements_reject_invalid_results(result):
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.requirements_from_overview(RUN_ID, result, HAND_ONTOLOGY)
    assert error.value.code == "company_input_invalid"


def test_overview_requirements_reject_invalid_run_id_and_fallback_units():
    result = {"business_overview": [], "main_tasks": [], "budget_and_period": []}
    with pytest.raises(CompanyRetrievalError):
        retrieval.requirements_from_overview("run-1", result, HAND_ONTOLOGY)
    with pytest.raises(CompanyRetrievalError):
        retrieval.requirements_from_overview(RUN_ID, result, HAND_ONTOLOGY, source_units=[_unit("x") | {"structure_id": ""}])


# --- graph paths -------------------------------------------------------------------


def test_paths_direct_partial_unmapped_ordering_and_evidence():
    units = [
        _unit("회의실 임차", block=3),
        _unit("AI 기반 분석과 ISMS 인증", block=1),
        _unit("mail server 운영", block=2),
    ]
    output = _build(units)
    paths = output["graph_paths"]
    ai, mail, rent = units[1]["requirement_id"], units[2]["requirement_id"], units[0]["requirement_id"]
    assert ai < mail < rent

    assert [(p["requirement_id"], p["relation"], p["node_ids"], p["edge_ids"]) for p in paths] == [
        (ai, "direct", ["company", "cap-ai"], ["e-company-cap-ai"]),
        (ai, "direct", ["company", "qual-isms"], ["e-company-qual-isms"]),
        (ai, "partial", ["company", "project-00", "cap-ai"], ["e-company-project-00", "e-project-00-cap-ai"]),
        (ai, "partial", ["company", "project-01", "cap-ai"], ["e-company-project-01", "e-project-01-cap-ai"]),
        (ai, "partial", ["company", "staff-ai", "cap-ai"], ["e-company-staff-ai", "e-staff-ai-cap-ai"]),
        (mail, "direct", ["company", "cap-mail"], ["e-company-cap-mail"]),
        (rent, "unmapped", [], []),
    ]
    # Evidence ids: node0, edge0, node1, ... first appearance, deduplicated.
    assert paths[0]["profile_evidence_ids"] == [_evidence_id("company"), _evidence_id("cap-ai")]
    assert paths[1]["profile_evidence_ids"] == [_evidence_id("company")]  # unknown node/edge carry none
    assert paths[2]["profile_evidence_ids"] == [_evidence_id("company"), _evidence_id("project-00"), _evidence_id("cap-ai")]
    assert paths[6]["profile_evidence_ids"] == []
    assert set(paths[0]) == {"requirement_id", "node_ids", "edge_ids", "profile_evidence_ids", "relation"}

    coverage = output["coverage"]
    assert coverage["included_requirement_ids"] == sorted(row["requirement_id"] for row in units)
    assert coverage["unmapped_requirement_ids"] == [rent]
    assert coverage["excluded_path_count_by_requirement"] == []
    assert coverage["excluded_fact_keys"] == []
    # Requirements keep the splitter order, not path order.
    assert [row["id"] for row in output["requirements"]] == [row["requirement_id"] for row in units]


def test_concept_without_company_link_and_technology_only_match_are_unmapped():
    nodes, edges = _hand_graph()
    units = [_unit("데이터 플랫폼 구축", block=0), _unit("k8s 운영", block=1)]
    output = _build(units, nodes=nodes, edges=edges)
    assert output["requirements"][0]["concept_ids"] == ["capability.platform"]
    assert output["requirements"][1]["concept_ids"] == ["technology.k8s"]
    assert [p["relation"] for p in output["graph_paths"]] == ["unmapped", "unmapped"]
    assert output["coverage"]["unmapped_requirement_ids"] == [units[0]["requirement_id"], units[1]["requirement_id"]]
    # Lexically matched technology fact still travels as a profile fact (retrieval, not judgment).
    assert "tech-k8s" in [fact["fact_key"] for fact in output["profile_facts"]]
    # Its node is frozen too (type + concept) so the slicer can place it (STEP-006 coverage fix).
    assert "tech-k8s" in [node["id"] for node in output["graph_nodes"]]
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)
    k8s_slice = next(row for row in slices if row["requirement_ids"] == [units[1]["requirement_id"]])
    assert "tech-k8s" in {fact["fact_key"] for fact in k8s_slice["profile_facts"]}
    assert "tech-k8s" in {node["id"] for node in k8s_slice["graph_nodes"]}
    platform_slice = next(row for row in slices if row["requirement_ids"] == [units[0]["requirement_id"]])
    assert "tech-k8s" not in {fact["fact_key"] for fact in platform_slice["profile_facts"]}


def test_path_limit_cuts_after_sorting_and_records_excluded_count():
    nodes, edges = _hand_graph(project_count=5)
    units = [_unit("AI 활용", block=0), _unit("mail server", block=1)]
    output = _build(units, nodes=nodes, edges=edges, limit=2)
    ai = units[0]["requirement_id"]
    kept = [p for p in output["graph_paths"] if p["requirement_id"] == ai]
    assert [(p["relation"], p["node_ids"]) for p in kept] == [
        ("direct", ["company", "cap-ai"]),
        ("partial", ["company", "project-00", "cap-ai"]),
    ]
    # 1 direct + 5 project + 1 staff = 7 candidates; 2 kept.
    assert output["coverage"]["excluded_path_count_by_requirement"] == [{"requirement_id": ai, "count": 5}]
    # Graph nodes = kept-path nodes + required (unknown/qualification) fact nodes; edges = kept-path edges.
    referenced_nodes = sorted({n for p in output["graph_paths"] for n in p["node_ids"]} | {"qual-isms"})
    assert [node["id"] for node in output["graph_nodes"]] == referenced_nodes
    referenced_edges = sorted({e for p in output["graph_paths"] for e in p["edge_ids"]})
    assert [edge["id"] for edge in output["graph_edges"]] == referenced_edges


@pytest.mark.parametrize("limit", [0, -1, True, "32", 1.5, None])
def test_invalid_path_limit_is_rejected(limit):
    with pytest.raises(CompanyRetrievalError) as error:
        _build([_unit("AI")], limit=limit)
    assert error.value.code == "path_limit_invalid"


def test_default_path_limit_is_32():
    assert retrieval.DEFAULT_PATH_LIMIT_PER_REQUIREMENT == 32
    nodes, edges = _hand_graph(project_count=40)
    requirements = retrieval.requirements_from_source_units([_unit("AI")], HAND_ONTOLOGY)
    result = retrieval.search_graph_paths(requirements, nodes, edges)
    assert len(result["graph_paths"]) == 32
    assert result["excluded_path_count_by_requirement"] == [
        {"requirement_id": requirements[0]["id"], "count": 1 + 40 + 1 - 32}
    ]


def test_parallel_edges_and_cycles_are_deduplicated_and_terminate():
    nodes, edges = _hand_graph(project_count=1)
    # A duplicate relation id with the same endpoints is a different path (edge tuple differs);
    # an exact duplicate edge row is invalid input.
    edges.append(_edge("e-company-cap-ai-2", "has_capability", "company", "cap-ai"))
    # A cycle back to the company cannot be produced by allowed relation types; a
    # supports_capability loop between two capabilities would be rejected by endpoint types.
    requirements = retrieval.requirements_from_source_units([_unit("AI")], HAND_ONTOLOGY)
    result = retrieval.search_graph_paths(requirements, nodes, edges)
    direct = [p for p in result["graph_paths"] if p["relation"] == "direct"]
    assert [p["edge_ids"] for p in direct] == [["e-company-cap-ai"], ["e-company-cap-ai-2"]]
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.search_graph_paths(requirements, nodes, [*edges, edges[0]])
    assert error.value.code == "company_input_invalid"


def test_search_is_deterministic_and_independent_of_input_order():
    nodes, edges = _hand_graph(project_count=3)
    requirements = retrieval.requirements_from_source_units(
        [_unit("AI 및 ISMS", block=0), _unit("mail server", block=1)], HAND_ONTOLOGY
    )
    first = retrieval.search_graph_paths(requirements, nodes, edges, path_limit_per_requirement=4)
    second = retrieval.search_graph_paths(
        list(reversed(requirements)), list(reversed(nodes)), list(reversed(edges)), path_limit_per_requirement=4
    )
    assert first == second


@pytest.mark.parametrize(
    "mutate",
    [
        lambda nodes, edges: nodes.append(_node("company-2", "company")),
        lambda nodes, edges: nodes.pop(0),
        lambda nodes, edges: nodes[1].update({"source_refs": []}),
        lambda nodes, edges: nodes[1].pop("evidence_ids"),
        lambda nodes, edges: nodes[1].update({"evidence_ids": ["not-a-uuid"]}),
        lambda nodes, edges: nodes[1].update({"status": "maybe"}),
        lambda nodes, edges: nodes[1].update({"type": "notice"}) or None,
        lambda nodes, edges: edges.append(_edge("e-dangling", "has_capability", "company", "missing")),
        lambda nodes, edges: nodes.append(deepcopy(nodes[1])),
        lambda nodes, edges: nodes[1].update({"concept_id": "capability.not-in-ontology"}),
    ],
)
def test_invalid_graph_shapes_fail_closed(mutate):
    nodes, edges = _hand_graph()
    mutate(nodes, edges)
    with pytest.raises(CompanyRetrievalError) as error:
        _build([_unit("AI")], nodes=nodes, edges=edges, profile=_profile_for(_hand_graph()[0]))
    assert error.value.code == "company_input_invalid"


# --- fixture graph ------------------------------------------------------------------


def test_fixture_graph_maps_requirements_to_direct_and_partial_paths_and_keeps_unknown_qualification():
    ontology, nodes, edges, profile = _fixture_graph("demo-data-ai")
    units = [
        _unit("업무 인공지능 기능 적용 및 데이터 수집 처리 기반 구축을 수행한다", block=0, doc_ids=["SFR-001"]),
        _unit("정보보호 관리 인증 보유 업체", block=1),
        _unit("산업 시설 토목 공사 포함", block=2),
        _unit("회의실 임차 및 다과 제공", block=3),
    ]
    requirements = retrieval.requirements_from_source_units(units, ontology)
    assert requirements[0]["concept_ids"] == ["capability.applied-ai", "capability.data-platform"]
    assert requirements[1]["concept_ids"] == ["qualification.security-management"]
    assert requirements[2]["concept_ids"] == ["capability.civil-construction"]
    assert requirements[3]["concept_ids"] == []
    known = {concept.id for concept in ontology.concepts}
    assert {cid for row in requirements for cid in row["concept_ids"]} <= known

    output = retrieval.build_company_retrieval(
        requirements, ontology=ontology, graph_nodes=nodes, graph_edges=edges,
        profile=profile, path_limit_per_requirement=32, profile_budget=100000,
    )
    paths = output["graph_paths"]
    first = [p for p in paths if p["requirement_id"] == units[0]["requirement_id"]]
    assert [(p["relation"], p["node_ids"][-1]) for p in first] == [
        ("direct", "cap-applied-ai"),
        ("direct", "cap-data-platform"),
        ("partial", "cap-applied-ai"),
        ("partial", "cap-data-platform"),
        ("partial", "cap-applied-ai"),
        ("partial", "cap-data-platform"),
    ]
    assert [p["node_ids"][1] for p in first[2:]] == [
        "project-applied-ai", "project-data-platform", "staff-applied-ai", "staff-data-engineering",
    ]
    qual = [p for p in paths if p["requirement_id"] == units[1]["requirement_id"]]
    assert qual == [{
        "requirement_id": units[1]["requirement_id"],
        "node_ids": ["company", "qualification-security-management"],
        "edge_ids": ["edge-company-qualification-security-management"],
        "profile_evidence_ids": [_evidence_id("company")],
        "relation": "direct",
    }]
    civil = [p for p in paths if p["requirement_id"] == units[2]["requirement_id"]]
    assert [(p["relation"], p["node_ids"][-1]) for p in civil] == [("direct", "cap-data-civil-work")]
    node_by_id = {node["id"]: node for node in output["graph_nodes"]}
    # non_core is carried as-is, never converted into a compliance verdict.
    assert node_by_id["cap-data-civil-work"]["value"]["scope"] == "non_core"
    assert node_by_id["qualification-security-management"]["status"] == "unknown"
    assert node_by_id["qualification-security-management"]["value"] is None

    facts = {fact["fact_key"]: fact for fact in output["profile_facts"]}
    assert facts["qualification-security-management"] == {
        "fact_key": "qualification-security-management", "status": "unknown",
        "origin": "fictional_scenario", "value": None, "quote": "",
        "locator": {"fact_key": "qualification-security-management"},
    }
    assert output["coverage"]["unmapped_requirement_ids"] == [units[3]["requirement_id"]]

    # Every evidence id referenced by graph rows/paths is bound to a supplied evidence row.
    evidence_ids = {row["profile_evidence_id"] for row in output["profile_evidence"]}
    referenced = {eid for p in paths for eid in p["profile_evidence_ids"]}
    referenced |= {eid for row in [*output["graph_nodes"], *output["graph_edges"]] for eid in row["evidence_ids"]}
    assert referenced <= evidence_ids
    assert all(row["origin"] == "fictional_scenario" and row["locator_type"] == "profile_fact" for row in output["profile_evidence"])
    assert set(output) == {
        "requirements", "profile_facts", "profile_evidence", "graph_nodes", "graph_edges", "graph_paths", "coverage",
    }
    assert "source_refs" not in json.dumps(output)


@pytest.mark.parametrize("slug", ["demo-cloud-si", "demo-data-ai", "demo-public-si"])
def test_all_fixture_companies_produce_valid_retrieval_and_slices(slug):
    ontology, nodes, edges, profile = _fixture_graph(slug)
    units = [
        _unit("행정 절차 분석 및 공공 데이터 연계 구현", block=0),
        _unit("클라우드 자원 운영 관리와 장애 원인 분석 체계", block=1),
        _unit("업무 인공지능 기능 적용", block=2),
        _unit("정보보호 관리 인증", block=3),
    ]
    output = retrieval.build_company_retrieval(
        retrieval.requirements_from_source_units(units, ontology), ontology=ontology,
        graph_nodes=nodes, graph_edges=edges, profile=profile,
        path_limit_per_requirement=32, profile_budget=4000,
    )
    unknown = {fact["fact_key"] for fact in profile["facts"] if fact["status"] == "unknown"}
    qualifications = {node["id"] for node in nodes if node["type"] == "qualification"}
    assert unknown | qualifications <= {fact["fact_key"] for fact in output["profile_facts"]}
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=4000)
    retrieval.check_slice_coverage(output, slices)


# --- profile facts -----------------------------------------------------------------


def test_unknown_and_qualification_facts_are_always_included_and_budget_only_excludes_optional():
    nodes, edges = _hand_graph(project_count=2)
    # A held qualification with no holds_qualification edge and no lexical match.
    nodes.append(_node("qual-other", "qualification", concept="qualification.isms", value="보유"))
    nodes.append(_node("staff-unknown", "staff_group", status="unknown"))
    profile = _profile_for(nodes)
    # A requirement that matches nothing at all.
    unmatched = _build([_unit("회의실 임차")], nodes=nodes, edges=edges, profile=profile, budget=100000)
    keys = [fact["fact_key"] for fact in unmatched["profile_facts"]]
    assert keys == sorted(["qual-isms", "qual-other", "staff-unknown"])
    assert unmatched["coverage"]["excluded_fact_keys"] == []  # unsearched facts are not "excluded"

    required_size = retrieval.profile_size(
        [fact for fact in unmatched["profile_facts"]],
        [row for row in unmatched["profile_evidence"] if row["fact_key"] in keys],
    )
    tight = _build([_unit("AI 분석")], nodes=nodes, edges=edges, profile=profile, budget=required_size + 10)
    tight_keys = {fact["fact_key"] for fact in tight["profile_facts"]}
    assert {"qual-isms", "qual-other", "staff-unknown"} <= tight_keys
    assert tight["coverage"]["excluded_fact_keys"]  # path facts excluded only by budget
    assert set(tight["coverage"]["excluded_fact_keys"]) <= {"company", "cap-ai", "project-00", "project-01", "staff-ai"}
    assert tight["coverage"]["excluded_fact_keys"] == sorted(tight["coverage"]["excluded_fact_keys"])
    # Paths are still complete and their evidence still resolves.
    evidence_ids = {row["profile_evidence_id"] for row in tight["profile_evidence"]}
    assert {eid for p in tight["graph_paths"] for eid in p["profile_evidence_ids"]} <= evidence_ids

    with pytest.raises(CompanyRetrievalError) as error:
        _build([_unit("AI 분석")], nodes=nodes, edges=edges, profile=profile, budget=10)
    assert error.value.code == "profile_required_too_large"


@pytest.mark.parametrize("budget", [0, -5, True, "4000", None])
def test_invalid_profile_budget_is_rejected(budget):
    with pytest.raises(CompanyRetrievalError) as error:
        _build([_unit("AI")], budget=budget)
    assert error.value.code == "budget_invalid"


def test_profile_and_graph_from_different_versions_are_rejected():
    nodes, edges = _hand_graph()
    profile = _profile_for(nodes)
    extra = deepcopy(profile)
    extra["facts"].append({**extra["facts"][0], "fact_key": "ghost", "locator": {"fact_key": "ghost"}})
    with pytest.raises(CompanyRetrievalError) as ghost:
        _build([_unit("AI")], nodes=nodes, edges=edges, profile=extra)
    assert ghost.value.code == "company_input_invalid"
    missing = deepcopy(profile)
    missing["evidence"] = [row for row in missing["evidence"] if row["fact_key"] != "cap-ai"]
    with pytest.raises(CompanyRetrievalError) as dangling:
        _build([_unit("AI")], nodes=nodes, edges=edges, profile=missing)
    assert dangling.value.code == "company_input_invalid"


def test_requirement_concepts_outside_ontology_are_rejected():
    requirements = retrieval.requirements_from_source_units([_unit("AI")], HAND_ONTOLOGY)
    requirements[0]["concept_ids"] = ["capability.ai", "capability.invented"]
    nodes, edges = _hand_graph()
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.build_company_retrieval(
            requirements, ontology=HAND_ONTOLOGY, graph_nodes=nodes, graph_edges=edges,
            profile=_profile_for(nodes), path_limit_per_requirement=32, profile_budget=100000,
        )
    assert error.value.code == "company_input_invalid"


def test_build_is_pure_and_deterministic():
    nodes, edges = _hand_graph(project_count=3)
    profile = _profile_for(nodes)
    units = [_unit("AI 및 ISMS", block=0), _unit("mail server", block=1), _unit("임차", block=2)]
    snapshot = deepcopy((nodes, edges, profile, units))
    first = _build(units, nodes=nodes, edges=edges, profile=profile)
    second = _build(units, nodes=nodes, edges=edges, profile=profile)
    assert first == second
    assert (nodes, edges, profile, units) == snapshot
    first["graph_nodes"][0]["label"] = "mutated"
    assert nodes[0]["label"] != "mutated"


# --- graph_path_indexes ----------------------------------------------------------


def test_graph_path_indexes_must_be_unique_in_range_and_owned_by_requirement():
    output = _build([_unit("AI", block=0), _unit("mail server", block=1)])
    paths = output["graph_paths"]
    ai = output["requirements"][0]["id"]
    owned = [index for index, p in enumerate(paths) if p["requirement_id"] == ai]
    retrieval.validate_graph_path_indexes(owned, paths, ai)
    retrieval.validate_graph_path_indexes([], paths, ai)
    foreign = next(index for index, p in enumerate(paths) if p["requirement_id"] != ai)
    for bad in ([owned[0], owned[0]], [len(paths)], [-1], [foreign], [True], ["0"]):
        with pytest.raises(CompanyRetrievalError) as error:
            retrieval.validate_graph_path_indexes(bad, paths, ai)
        assert error.value.code == "graph_path_index_invalid"


# --- slices -------------------------------------------------------------------------


def test_slices_carry_global_path_index_units_and_referenced_graph_rows():
    units = [_unit("회의실 임차", block=3), _unit("AI 기반 분석과 ISMS 인증", block=1), _unit("mail server 운영", block=2)]
    output = _build(units)
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)

    assert [row["slice_index"] for row in slices] == list(range(len(slices)))
    # One slice per requirement here, in requirement (splitter) order.
    assert [row["requirement_ids"] for row in slices] == [[unit["requirement_id"]] for unit in units]
    assert [row["requirements"] for row in slices] == [[unit] for unit in units]
    for row in slices:
        for path in row["graph_paths"]:
            index = path["global_path_index"]
            assert {k: v for k, v in path.items() if k != "global_path_index"} == output["graph_paths"][index]
            assert path["requirement_id"] in row["requirement_ids"]
        node_ids = {n for p in row["graph_paths"] for n in p["node_ids"]}
        edge_ids = {e for p in row["graph_paths"] for e in p["edge_ids"]}
        assert {n["id"] for n in row["graph_nodes"]} == node_ids
        assert {e["id"] for e in row["graph_edges"]} == edge_ids
        evidence_ids = {e["profile_evidence_id"] for e in row["profile_evidence"]}
        assert {eid for p in row["graph_paths"] for eid in p["profile_evidence_ids"]} <= evidence_ids
        # Required facts (unknown qualification) travel with every requirement.
        assert "qual-isms" in {fact["fact_key"] for fact in row["profile_facts"]}
    all_indexes = sorted(p["global_path_index"] for row in slices for p in row["graph_paths"])
    assert all_indexes == list(range(len(output["graph_paths"])))
    retrieval.check_slice_coverage(output, slices)


def test_required_facts_without_paths_reach_every_requirement_slice():
    nodes, edges = _hand_graph(project_count=1)
    nodes.append(_node("qual-other", "qualification", concept="qualification.isms", value="보유"))
    nodes.append(_node("staff-unknown", "staff_group", status="unknown"))
    output = _build(
        [_unit("AI 분석", block=0), _unit("회의실 임차", block=1)],
        nodes=nodes, edges=edges, profile=_profile_for(nodes),
    )
    assert {"qual-isms", "qual-other", "staff-unknown"} <= {node["id"] for node in output["graph_nodes"]}
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)
    assert len(slices) == 2
    for row in slices:
        assert {"qual-isms", "qual-other", "staff-unknown"} <= {fact["fact_key"] for fact in row["profile_facts"]}
    other = next(fact for fact in slices[1]["profile_facts"] if fact["fact_key"] == "qual-other")
    assert other["value"] == "보유"
    assert _evidence_id("qual-other") in {row["profile_evidence_id"] for row in slices[1]["profile_evidence"]}


def test_concept_only_facts_reach_every_slice_sharing_their_concept_and_are_never_dropped():
    """STEP-004 gap: a concept-matched fact on no path reached no delivery slice."""

    nodes, edges = _hand_graph(project_count=1)
    nodes.append(_node("domain-public", "domain", concept="domain.public", value="공공 행정"))
    units = [_unit("공공 행정 분야 AI 분석", block=0), _unit("쿠버네티스 운영과 공공 행정 지원", block=1),
             _unit("회의실 임차", block=2)]
    output = _build(units, nodes=nodes, edges=edges, profile=_profile_for(nodes))
    path_nodes = {node for path in output["graph_paths"] for node in path["node_ids"]}
    concept_only = {"tech-k8s", "domain-public"}
    assert not concept_only & path_nodes
    assert concept_only <= {fact["fact_key"] for fact in output["profile_facts"]}
    assert concept_only <= {node["id"] for node in output["graph_nodes"]}
    assert output["coverage"]["excluded_fact_keys"] == []
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)
    by_requirement = {}
    for row in slices:
        by_requirement.setdefault(row["requirement_ids"][0], set()).update(fact["fact_key"] for fact in row["profile_facts"])
    first, second, third = (unit["requirement_id"] for unit in units)
    assert "domain-public" in by_requirement[first] and "tech-k8s" not in by_requirement[first]
    assert {"domain-public", "tech-k8s"} <= by_requirement[second]
    assert not concept_only & by_requirement[third]
    for row in slices:
        facts = {fact["fact_key"] for fact in row["profile_facts"]}
        evidence = {item["profile_evidence_id"] for item in row["profile_evidence"]}
        assert {_evidence_id(key) for key in facts & concept_only} <= evidence
        assert facts & concept_only <= {node["id"] for node in row["graph_nodes"]}
    retrieval.check_fact_coverage(output, slices)

    # A slice set that loses a frozen fact (or its evidence) fails closed.
    for drop in ("fact", "evidence"):
        broken = deepcopy(slices)
        for row in broken:
            if drop == "fact":
                row["profile_facts"] = [fact for fact in row["profile_facts"] if fact["fact_key"] != "tech-k8s"]
            else:
                row["profile_evidence"] = [item for item in row["profile_evidence"] if item["fact_key"] != "tech-k8s"]
        with pytest.raises(CompanyRetrievalError) as error:
            retrieval.check_fact_coverage(output, broken)
        assert error.value.code == "slice_coverage_mismatch"


def test_concept_only_fact_that_cannot_fit_one_slice_is_listed_as_excluded():
    nodes, edges = _hand_graph(project_count=1)
    big = next(node for node in nodes if node["id"] == "tech-k8s")
    big["value"] = "쿠버네티스 " + "가" * 1500
    profile = _profile_for(nodes)
    units = [_unit("k8s 운영", block=0)]
    roomy = _build(units, nodes=nodes, edges=edges, profile=profile)
    facts = {fact["fact_key"]: fact for fact in roomy["profile_facts"]}
    own = [row for row in roomy["profile_evidence"] if row["fact_key"] == "tech-k8s"]
    node = next(row for row in roomy["graph_nodes"] if row["id"] == "tech-k8s")
    selected = retrieval.profile_size(list(facts.values()), roomy["profile_evidence"])
    standalone = retrieval.company_context_size({"graph_nodes": [node], "profile_facts": [facts["tech-k8s"]],
                                                 "profile_evidence": own})
    assert selected < standalone  # the selection budget alone would admit the fact
    tight = _build(units, nodes=nodes, edges=edges, profile=profile, budget=selected)
    assert tight["coverage"]["excluded_fact_keys"] == ["tech-k8s"]
    assert "tech-k8s" not in {fact["fact_key"] for fact in tight["profile_facts"]}
    assert "tech-k8s" not in {node["id"] for node in tight["graph_nodes"]}
    assert "tech-k8s" not in {row["fact_key"] for row in tight["profile_evidence"]}
    slices = retrieval.build_company_slices(tight, source_characters=6000, profile_characters=selected)
    retrieval.check_fact_coverage(tight, slices)
    # The slicer never truncates a concept fact: a smaller slice budget fails closed.
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.build_company_slices(roomy, source_characters=6000, profile_characters=standalone - 1)
    assert error.value.code == "profile_fact_too_large"


def test_oversized_company_context_splits_into_follow_up_slices_without_dropping_paths():
    nodes, edges = _hand_graph(project_count=6)
    output = _build([_unit("AI 분석", block=0), _unit("mail server", block=1)], nodes=nodes, edges=edges)
    one_path = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)
    assert len(one_path) == 2
    budget = 3500  # one partial path context is ~3.1k chars here; all paths together ~13k
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=budget)
    ai = output["requirements"][0]["id"]
    ai_slices = [row for row in slices if row["requirement_ids"] == [ai]]
    assert len(ai_slices) > 1
    assert [row["company_part_index"] for row in ai_slices] == list(range(len(ai_slices)))
    assert {row["company_part_count"] for row in ai_slices} == {len(ai_slices)}
    for row in ai_slices:
        assert row["requirements"] == output["requirements"][0]["source_units"]
        assert retrieval.company_context_size(row) <= budget
    assert sorted(p["global_path_index"] for row in slices for p in row["graph_paths"]) == list(range(len(output["graph_paths"])))
    retrieval.check_slice_coverage(output, slices)


def test_single_source_unit_or_path_over_budget_fails_with_safe_code():
    output = _build([_unit("AI " + "가" * 500)])
    with pytest.raises(CompanyRetrievalError) as source_error:
        retrieval.build_company_slices(output, source_characters=200, profile_characters=100000)
    assert source_error.value.code == "source_unit_too_large"
    with pytest.raises(CompanyRetrievalError) as required_error:
        retrieval.build_company_slices(output, source_characters=6000, profile_characters=20)
    assert required_error.value.code == "profile_required_too_large"
    nodes, edges = _hand_graph()
    no_required = [node for node in nodes if node["id"] != "qual-isms"]
    no_required_edges = [edge for edge in edges if edge["to_id"] != "qual-isms"]
    lean = _build([_unit("AI")], nodes=no_required, edges=no_required_edges)
    with pytest.raises(CompanyRetrievalError) as path_error:
        retrieval.build_company_slices(lean, source_characters=6000, profile_characters=100)
    assert path_error.value.code == "graph_path_too_large"
    for bad in (0, -1, True, "6000"):
        with pytest.raises(CompanyRetrievalError) as budget_error:
            retrieval.build_company_slices(lean, source_characters=bad, profile_characters=4000)
        assert budget_error.value.code == "budget_invalid"


def test_requirement_without_source_units_cannot_be_sliced():
    nodes, edges = _hand_graph()
    result = {"business_overview": [{"text": "AI", "evidence": []}], "main_tasks": [], "budget_and_period": []}
    requirements = retrieval.requirements_from_overview(RUN_ID, result, HAND_ONTOLOGY)
    output = retrieval.build_company_retrieval(
        requirements, ontology=HAND_ONTOLOGY, graph_nodes=nodes, graph_edges=edges,
        profile=_profile_for(nodes), path_limit_per_requirement=32, profile_budget=100000,
    )
    assert output["requirements"][0]["id"] == f"overview:{RUN_ID}:business_overview:0"
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.build_company_slices(output, source_characters=6000, profile_characters=4000)
    assert error.value.code == "source_units_empty"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda slices: slices.pop(),  # missing unit and paths
        lambda slices: slices.append(deepcopy(slices[0]) | {"slice_index": len(slices)}),  # duplicate paths
        lambda slices: slices[0]["graph_paths"][0].update({"global_path_index": 99}),
        lambda slices: slices[0]["graph_paths"][0].update({"relation": "partial"}),  # reordered/mutated
        lambda slices: slices[0]["requirements"].append(deepcopy(slices[1]["requirements"][0])),  # foreign unit
        lambda slices: slices[1].update({"slice_index": 5}),
    ],
)
def test_slice_coverage_check_detects_missing_duplicate_or_foreign_material(mutate):
    output = _build([_unit("AI 분석", block=0), _unit("mail server", block=1), _unit("임차", block=2)])
    slices = retrieval.build_company_slices(output, source_characters=6000, profile_characters=100000)
    retrieval.check_slice_coverage(output, slices)
    mutate(slices)
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.check_slice_coverage(output, slices)
    assert error.value.code == "slice_coverage_mismatch"


def test_errors_never_carry_input_text():
    secret = "SECRET-원문-/var/data/path"
    with pytest.raises(CompanyRetrievalError) as error:
        retrieval.requirements_from_source_units([_unit(secret) | {"structure_id": ""}], HAND_ONTOLOGY)
    assert secret not in str(error.value) and error.value.args == ("company_input_invalid",)
    assert UUID(DOC_ID)  # sanity: fixtures are canonical UUIDs
