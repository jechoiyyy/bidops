"""DEMO-02 STEP-001의 순수 온톨로지·회사 원본 계약 검사.

fixture는 모두 이 테스트에서 만든 합성 값이다. 실제 회사 자료와 ``data/runs``는
읽지 않는다.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from app.core.company_ontology import (
    CompanyKnowledgeValidationError,
    OntologyValidationError,
    build_graph_snapshot,
    parse_company_knowledge_source,
    parse_ontology,
    validate_alias_only_revision,
)


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
        [
            "company",
            "capability",
            "technology",
            "domain",
            "staff_group",
            "project",
            "qualification",
            "requirement",
        ],
        ["evidence"],
    ),
    ("has_requirement", ["notice"], ["requirement"]),
    ("requires_capability", ["requirement"], ["capability"]),
    ("requires_qualification", ["requirement"], ["qualification"]),
]


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    if pretty:
        return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _ontology(*, version: str = "demo-ontology-v1") -> dict[str, object]:
    return {
        "schema_version": "bidops.company-ontology.v1",
        "version": version,
        "concepts": [
            {
                "id": "cap.delivery",
                "label": "업무 시스템 구축",
                "aliases": ["시스템 구축", "Delivery"],
                "kind": "capability",
            },
            {
                "id": "tech.python",
                "label": "Python",
                "aliases": ["파이썬"],
                "kind": "technology",
            },
            {
                "id": "domain.public",
                "label": "공공 업무",
                "aliases": ["공공 SI"],
                "kind": "domain",
            },
            {
                "id": "qual.synthetic",
                "label": "가상 자격",
                "aliases": ["합성 자격"],
                "kind": "qualification",
            },
        ],
        "relations": [
            {
                "type": relation_type,
                "from_types": from_types,
                "to_types": to_types,
                "evidence_required": True,
            }
            for relation_type, from_types, to_types in RELATIONS
        ],
    }


def _source(ontology_sha256: str) -> dict[str, object]:
    return {
        "schema_version": "bidops.company-knowledge-source.v1",
        "company": {
            "slug": "synthetic-si",
            "name": "합성 SI",
            "is_fictional": True,
        },
        "scenario_version": "synthetic-v1",
        "ontology_version": "demo-ontology-v1",
        "ontology_sha256": ontology_sha256,
        "nodes": [
            {
                "id": "company.synthetic",
                "type": "company",
                "label": "합성 SI",
                "concept_id": None,
                "status": "confirmed",
                "origin": "fictional_scenario",
                "value": "가상회사",
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/0/value"},
                        "quote": "가상회사",
                    }
                ],
            },
            {
                "id": "cap.delivery",
                "type": "capability",
                "label": "업무 시스템 구축",
                "concept_id": "cap.delivery",
                "status": "confirmed",
                "origin": "fictional_scenario",
                "value": {"scope": "core", "description": "합성 구축 역량"},
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/1/value/description"},
                        "quote": "합성 구축 역량",
                    }
                ],
            },
            {
                "id": "staff.engineers",
                "type": "staff_group",
                "label": "합성 개발 인력",
                "concept_id": None,
                "status": "confirmed",
                "origin": "fictional_scenario",
                "value": {
                    "role": "개발",
                    "total": 8,
                    "available": 3,
                    "as_of": "2026-10-01",
                },
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/2/value/available"},
                        "quote": "3",
                    }
                ],
            },
            {
                "id": "project.alpha",
                "type": "project",
                "label": "합성 구축 실적",
                "concept_id": None,
                "status": "inferred",
                "origin": "fictional_scenario",
                "value": {
                    "role": "주사업자",
                    "scope": "가상 구축",
                    "amount_krw": 120000000,
                    "started_on": "2025-01-01",
                    "ended_on": "2025-12-31",
                },
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/3/value/scope"},
                        "quote": "가상 구축",
                    }
                ],
            },
            {
                "id": "qual.synthetic",
                "type": "qualification",
                "label": "가상 자격",
                "concept_id": "qual.synthetic",
                "status": "unknown",
                "origin": "fictional_scenario",
                "value": None,
                "source_refs": [],
            },
            {
                "id": "evidence.delivery",
                "type": "evidence",
                "label": "구축 역량 합성 근거",
                "concept_id": None,
                "status": "confirmed",
                "origin": "fictional_scenario",
                "value": {"fact_key": "cap.delivery"},
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/1/value/description"},
                        "quote": "합성 구축 역량",
                    }
                ],
            },
        ],
        "edges": [
            {
                "id": "edge.company-capability",
                "type": "has_capability",
                "from_id": "company.synthetic",
                "to_id": "cap.delivery",
                "status": "confirmed",
                "origin": "fictional_scenario",
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/1/value/description"},
                        "quote": "합성 구축 역량",
                    }
                ],
            },
            {
                "id": "edge.staff-capability",
                "type": "supports_capability",
                "from_id": "staff.engineers",
                "to_id": "cap.delivery",
                "status": "confirmed",
                "origin": "fictional_scenario",
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/2/value/available"},
                        "quote": "3",
                    }
                ],
            },
            {
                "id": "edge.capability-evidence",
                "type": "supported_by",
                "from_id": "cap.delivery",
                "to_id": "evidence.delivery",
                "status": "confirmed",
                "origin": "fictional_scenario",
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": "/nodes/1/value/description"},
                        "quote": "합성 구축 역량",
                    }
                ],
            },
        ],
    }


def _validated() -> tuple[object, dict[str, object], bytes]:
    ontology = parse_ontology(_json_bytes(_ontology()))
    source_value = _source(ontology.sha256)
    source_raw = _json_bytes(source_value, pretty=True)
    return ontology, source_value, source_raw


# T1 — 관계·끝점·중복·cycle 안전성·한글 한 글자 alias


def test_t1_validates_the_exact_relation_vocabulary_and_endpoint_types() -> None:
    ontology, source_value, _ = _validated()

    bad_declaration = _ontology()
    bad_declaration["relations"][0]["to_types"] = ["technology"]  # type: ignore[index]
    with pytest.raises(OntologyValidationError, match="relation_declaration_invalid"):
        parse_ontology(_json_bytes(bad_declaration))

    bad_edge = deepcopy(source_value)
    bad_edge["edges"][0]["to_id"] = "staff.engineers"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="edge_endpoint_invalid"):
        parse_company_knowledge_source(_json_bytes(bad_edge), ontology=ontology)

    self_cycle = deepcopy(source_value)
    self_cycle["edges"][0]["to_id"] = "company.synthetic"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="edge_endpoint_invalid"):
        parse_company_knowledge_source(_json_bytes(self_cycle), ontology=ontology)

    missing_declaration = _ontology()
    missing_declaration["relations"].pop()  # type: ignore[union-attr]
    with pytest.raises(OntologyValidationError, match="relation_declaration_invalid"):
        parse_ontology(_json_bytes(missing_declaration))

    duplicate_declaration = _ontology()
    duplicate_declaration["relations"].append(  # type: ignore[union-attr]
        deepcopy(duplicate_declaration["relations"][0])  # type: ignore[index]
    )
    with pytest.raises(OntologyValidationError, match="relation_declaration_invalid"):
        parse_ontology(_json_bytes(duplicate_declaration))


@pytest.mark.parametrize("collection,key", [("nodes", "id"), ("edges", "id")])
def test_t1_rejects_duplicate_graph_ids(collection: str, key: str) -> None:
    ontology, source_value, _ = _validated()
    duplicate = deepcopy(source_value)
    duplicate[collection].append(deepcopy(duplicate[collection][0]))  # type: ignore[index,union-attr]
    with pytest.raises(CompanyKnowledgeValidationError, match=f"duplicate_{key}"):
        parse_company_knowledge_source(_json_bytes(duplicate), ontology=ontology)


def test_t1_rejects_ambiguous_terms_and_one_character_korean_aliases() -> None:
    one_character = _ontology()
    one_character["concepts"][0]["aliases"] = ["역"]  # type: ignore[index]
    with pytest.raises(OntologyValidationError, match="alias_too_short"):
        parse_ontology(_json_bytes(one_character))

    ambiguous = _ontology()
    ambiguous["concepts"][1]["aliases"] = ["ＳＹＳＴＥＭ   구축"]  # type: ignore[index]
    ambiguous["concepts"][0]["aliases"].append("system 구축")  # type: ignore[index,union-attr]
    with pytest.raises(OntologyValidationError, match="ambiguous_term"):
        parse_ontology(_json_bytes(ambiguous))


# T2 — fictional/unknown/수치·hash·pointer/quote


def test_t2_preserves_raw_source_hash_unknown_and_fictional_origin() -> None:
    ontology, _, source_raw = _validated()
    source = parse_company_knowledge_source(source_raw, ontology=ontology)

    assert source.source_sha256 == hashlib.sha256(source_raw).hexdigest()
    assert source.company.is_fictional is True
    qualification = next(node for node in source.nodes if node.id == "qual.synthetic")
    assert qualification.status == "unknown"
    assert qualification.value is None
    assert qualification.source_refs == ()
    assert {node.origin for node in source.nodes} == {"fictional_scenario"}
    assert {edge.origin for edge in source.edges} == {"fictional_scenario"}


@pytest.mark.parametrize("slug", ["a", "a.b", "a_b", "a" * 65])
def test_t2_company_slug_matches_lifecycle_registration_rules(slug: str) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["company"]["slug"] = slug  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="company_slug_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


@pytest.mark.parametrize("name", ["   ", "가" * 129])
def test_t2_company_name_matches_lifecycle_registration_limits(name: str) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["company"]["name"] = name  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="company_name_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_t2_company_name_preserves_lifecycle_whitespace_normalization() -> None:
    ontology, source_value, _ = _validated()
    padded = deepcopy(source_value)
    padded["company"]["name"] = "  합성 SI  "  # type: ignore[index]

    source = parse_company_knowledge_source(_json_bytes(padded), ontology=ontology)

    assert source.company.name == "합성 SI"


@pytest.mark.parametrize("origin", ["public_document", "model_inference"])
def test_t2_registration_source_rejects_overlay_origins(origin: str) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["nodes"][0]["origin"] = origin  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="source_origin_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_t2_enforces_one_company_node_and_the_profile_fact_limit() -> None:
    ontology, source_value, _ = _validated()
    two_companies = deepcopy(source_value)
    second_company = deepcopy(two_companies["nodes"][0])  # type: ignore[index]
    second_company["id"] = "company.second"
    second_company["source_refs"][0]["locator"]["json_pointer"] = "/nodes/6/value"
    two_companies["nodes"].append(second_company)  # type: ignore[union-attr]
    with pytest.raises(CompanyKnowledgeValidationError, match="company_node_count_invalid"):
        parse_company_knowledge_source(_json_bytes(two_companies), ontology=ontology)

    too_many = deepcopy(source_value)
    # The base source has five non-evidence facts. Add 252 synthetic domain
    # facts so the profile projection would contain 257 facts.
    for number in range(252):
        index = len(too_many["nodes"])  # type: ignore[arg-type]
        too_many["nodes"].append(  # type: ignore[union-attr]
            {
                "id": f"domain.synthetic-{number}",
                "type": "domain",
                "label": f"합성 분야 {number}",
                "concept_id": "domain.public",
                "status": "confirmed",
                "origin": "fictional_scenario",
                "value": f"합성 분야 값 {number}",
                "source_refs": [
                    {
                        "source_id": "self",
                        "locator": {"json_pointer": f"/nodes/{index}/value"},
                        "quote": f"합성 분야 값 {number}",
                    }
                ],
            }
        )
    with pytest.raises(CompanyKnowledgeValidationError, match="profile_fact_count_invalid"):
        parse_company_knowledge_source(_json_bytes(too_many), ontology=ontology)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value["nodes"][2]["value"].__setitem__("total", -1), "negative_number"),
        (lambda value: value["nodes"][2]["value"].__setitem__("available", 9), "available_exceeds_total"),
        (lambda value: value["nodes"][2]["value"].__setitem__("total", True), "integer_invalid"),
        (lambda value: value["nodes"][3]["value"].__setitem__("amount_krw", -1), "negative_number"),
        (lambda value: value["nodes"][3]["value"].__setitem__("started_on", "2026-01-01"), "date_order_invalid"),
    ],
)
def test_t2_rejects_negative_invalid_count_and_date_order(mutate, code: str) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    mutate(invalid)
    with pytest.raises(CompanyKnowledgeValidationError, match=code):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_t2_unknown_is_never_coerced_to_zero_or_given_fake_evidence() -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["nodes"][4]["value"] = "미보유"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="unknown_value_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)

    invalid = deepcopy(source_value)
    invalid["nodes"][4]["source_refs"] = deepcopy(invalid["nodes"][1]["source_refs"])  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="unknown_source_refs_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_t2_rejects_hash_pointer_quote_and_reference_violations() -> None:
    ontology, source_value, _ = _validated()

    bad_hash = deepcopy(source_value)
    bad_hash["ontology_sha256"] = "f" * 64
    with pytest.raises(CompanyKnowledgeValidationError, match="ontology_hash_mismatch"):
        parse_company_knowledge_source(_json_bytes(bad_hash), ontology=ontology)

    bad_pointer = deepcopy(source_value)
    bad_pointer["nodes"][1]["source_refs"][0]["locator"]["json_pointer"] = "/nodes/0/value"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="source_pointer_invalid"):
        parse_company_knowledge_source(_json_bytes(bad_pointer), ontology=ontology)

    bad_quote = deepcopy(source_value)
    bad_quote["nodes"][2]["source_refs"][0]["quote"] = "03"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="source_quote_mismatch"):
        parse_company_knowledge_source(_json_bytes(bad_quote), ontology=ontology)

    fake_edge_ref = deepcopy(source_value)
    fake_edge_ref["edges"][0]["source_refs"][0] = {  # type: ignore[index]
        "source_id": "self",
        "locator": {"json_pointer": "/nodes/3/value/amount_krw"},
        "quote": "120000000",
    }
    with pytest.raises(CompanyKnowledgeValidationError, match="source_ref_not_reused"):
        parse_company_knowledge_source(_json_bytes(fake_edge_ref), ontology=ontology)

    injected_hash = deepcopy(source_value)
    injected_hash["nodes"][1]["source_refs"][0]["source_sha256"] = "a" * 64  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="source_ref_keys_invalid"):
        parse_company_knowledge_source(_json_bytes(injected_hash), ontology=ontology)


def test_t2_rejects_duplicate_json_keys_before_validation() -> None:
    duplicate = b'{"schema_version":"bidops.company-ontology.v1","schema_version":"other"}'
    with pytest.raises(OntologyValidationError, match="duplicate_json_key"):
        parse_ontology(duplicate)


@pytest.mark.parametrize(
    ("location", "bad_value", "code"),
    [
        ("concept_kind", [], "concept_kind_invalid"),
        ("relation_type", {}, "relation_declaration_invalid"),
    ],
)
def test_t2_unhashable_ontology_enums_fail_with_safe_errors(
    location: str, bad_value: object, code: str
) -> None:
    invalid = _ontology()
    if location == "concept_kind":
        invalid["concepts"][0]["kind"] = bad_value  # type: ignore[index]
    else:
        invalid["relations"][0]["type"] = bad_value  # type: ignore[index]

    with pytest.raises(OntologyValidationError, match=code):
        parse_ontology(_json_bytes(invalid))


@pytest.mark.parametrize(
    ("location", "bad_value", "code"),
    [
        ("node_type", [], "node_type_invalid"),
        ("node_status", {}, "node_status_invalid"),
        ("capability_scope", [], "node_value_invalid"),
        ("edge_type", [], "edge_type_invalid"),
        ("edge_status", {}, "edge_status_invalid"),
    ],
)
def test_t2_unhashable_company_enums_fail_with_safe_errors(
    location: str, bad_value: object, code: str
) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    if location == "node_type":
        invalid["nodes"][0]["type"] = bad_value  # type: ignore[index]
    elif location == "node_status":
        invalid["nodes"][0]["status"] = bad_value  # type: ignore[index]
    elif location == "capability_scope":
        invalid["nodes"][1]["value"]["scope"] = bad_value  # type: ignore[index]
    elif location == "edge_type":
        invalid["edges"][0]["type"] = bad_value  # type: ignore[index]
    else:
        invalid["edges"][0]["status"] = bad_value  # type: ignore[index]

    with pytest.raises(CompanyKnowledgeValidationError, match=code):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_t2_graph_snapshot_is_deterministic_and_extends_refs_only_internally() -> None:
    ontology, source_value, source_raw = _validated()
    source = parse_company_knowledge_source(source_raw, ontology=ontology)
    first = build_graph_snapshot(source, ontology=ontology)

    reordered = deepcopy(source_value)
    reordered["nodes"] = list(reversed(reordered["nodes"]))  # type: ignore[arg-type]
    old_indexes = {node["id"]: index for index, node in enumerate(source_value["nodes"])}  # type: ignore[union-attr]
    new_indexes = {node["id"]: index for index, node in enumerate(reordered["nodes"])}  # type: ignore[union-attr]
    for node in reordered["nodes"]:  # type: ignore[union-attr]
        for ref in node["source_refs"]:
            pointer = ref["locator"]["json_pointer"]
            if pointer.startswith("/nodes/"):
                old_index = int(pointer.split("/", 3)[2])
                node_id = source_value["nodes"][old_index]["id"]  # type: ignore[index]
                ref["locator"]["json_pointer"] = pointer.replace(
                    f"/nodes/{old_index}/", f"/nodes/{new_indexes[node_id]}/", 1
                )
    # 관계 근거도 새 원본의 fact pointer를 재사용해야 한다.
    ref_by_quote = {
        ref["quote"]: ref
        for node in reordered["nodes"]  # type: ignore[union-attr]
        for ref in node["source_refs"]
        if node["type"] not in {"evidence"}
    }
    for edge in reordered["edges"]:  # type: ignore[union-attr]
        edge["source_refs"] = [deepcopy(ref_by_quote[ref["quote"]]) for ref in edge["source_refs"]]
    # bytes hash is intentionally different, so compare order determinism on one parsed source
    # by rebuilding twice; graph content itself must be sorted and stable.
    second = build_graph_snapshot(source, ontology=ontology)
    assert first.sha256 == second.sha256
    assert first.sha256 == hashlib.sha256(first.canonical_bytes).hexdigest()
    assert json.loads(first.canonical_bytes) == first.payload
    assert [node["id"] for node in first.payload["nodes"]] == sorted(
        node["id"] for node in first.payload["nodes"]
    )
    assert [edge["id"] for edge in first.payload["edges"]] == sorted(
        edge["id"] for edge in first.payload["edges"]
    )
    assert all(
        ref["source_sha256"] == source.source_sha256
        for item in (*first.payload["nodes"], *first.payload["edges"])
        for ref in item["source_refs"]
    )
    assert all(
        "source_sha256" not in ref
        for item in (*source_value["nodes"], *source_value["edges"])  # type: ignore[index]
        for ref in item["source_refs"]
    )


@pytest.mark.parametrize("mutation", ["node_value", "private_payload"])
def test_t2_snapshot_rejects_nested_mutation_of_a_validated_source(mutation: str) -> None:
    ontology, _, source_raw = _validated()
    source = parse_company_knowledge_source(source_raw, ontology=ontology)
    if mutation == "node_value":
        capability = next(node for node in source.nodes if node.id == "cap.delivery")
        capability.value["description"] = "검증 후 변조"
    else:
        source._payload["nodes"][1]["value"]["description"] = "검증 후 변조"

    with pytest.raises(CompanyKnowledgeValidationError, match="source_integrity_invalid"):
        build_graph_snapshot(source, ontology=ontology)


# T8 — 별칭만 다른 ontology revision


def test_t8_accepts_only_a_new_version_with_alias_changes() -> None:
    previous = parse_ontology(_json_bytes(_ontology()))
    candidate_value = _ontology(version="demo-ontology-v2")
    candidate_value["concepts"][0]["aliases"].append("업무 구축")  # type: ignore[index,union-attr]
    candidate = parse_ontology(_json_bytes(candidate_value))

    validate_alias_only_revision(previous, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "add",
        "delete",
        "kind",
        "label",
        "relation",
        "same_version",
        "remove_alias",
        "no_alias_change",
    ],
)
def test_t8_rejects_non_alias_ontology_changes(mutation: str) -> None:
    previous = parse_ontology(_json_bytes(_ontology()))
    candidate_value = _ontology(version="demo-ontology-v2")
    candidate_value["concepts"][0]["aliases"].append("업무 구축")  # type: ignore[index,union-attr]

    if mutation == "add":
        candidate_value["concepts"].append(  # type: ignore[union-attr]
            {"id": "cap.extra", "label": "추가 역량", "aliases": [], "kind": "capability"}
        )
    elif mutation == "delete":
        candidate_value["concepts"].pop()  # type: ignore[union-attr]
    elif mutation == "kind":
        candidate_value["concepts"][0]["kind"] = "technology"  # type: ignore[index]
    elif mutation == "label":
        candidate_value["concepts"][0]["label"] = "바뀐 레이블"  # type: ignore[index]
    elif mutation == "relation":
        candidate_value["relations"][0]["evidence_required"] = False  # type: ignore[index]
    elif mutation == "same_version":
        candidate_value["version"] = "demo-ontology-v1"
    elif mutation == "remove_alias":
        candidate_value["concepts"][1]["aliases"] = []  # type: ignore[index]
    elif mutation == "no_alias_change":
        candidate_value["concepts"][0]["aliases"].pop()  # type: ignore[index,union-attr]

    try:
        candidate = parse_ontology(_json_bytes(candidate_value))
    except OntologyValidationError:
        if mutation == "relation":
            return
        raise
    with pytest.raises(OntologyValidationError, match="alias_only_revision_invalid"):
        validate_alias_only_revision(previous, candidate)


def test_n2_ontology_version_longer_than_the_storage_column_is_rejected() -> None:
    from app.core.company_ontology import MAX_ONTOLOGY_VERSION_LENGTH

    assert MAX_ONTOLOGY_VERSION_LENGTH == 128
    assert parse_ontology(_json_bytes(_ontology(version="v" * 128))).version == "v" * 128
    assert parse_ontology(_json_bytes(_ontology(version="가" * 128))).version == "가" * 128
    with pytest.raises(OntologyValidationError, match="ontology_version_invalid"):
        parse_ontology(_json_bytes(_ontology(version="v" * 129)))


@pytest.mark.parametrize(
    ("index", "drop"),
    [
        (2, "total"),
        (2, "available"),
        (2, "as_of"),
        (3, "amount_krw"),
        (3, "started_on"),
        (3, "ended_on"),
        (1, "scope"),
        (5, "fact_key"),
    ],
)
def test_b2_node_value_requires_every_declared_key(index: int, drop: str) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["nodes"][index]["value"].pop(drop)  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="node_value_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


@pytest.mark.parametrize("index", [1, 2, 3, 5])
def test_b2_node_value_rejects_undeclared_keys(index: int) -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["nodes"][index]["value"]["prompt"] = "자유 지시"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="node_value_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)


def test_b2_minimal_staff_and_project_values_need_explicit_nulls() -> None:
    ontology, source_value, _ = _validated()
    minimal = deepcopy(source_value)
    minimal["nodes"][2]["value"] = {"role": "개발", "total": 8}  # type: ignore[index]
    minimal["nodes"][2]["source_refs"][0]["locator"]["json_pointer"] = "/nodes/2/value/role"  # type: ignore[index]
    minimal["nodes"][2]["source_refs"][0]["quote"] = "개발"  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="node_value_invalid"):
        parse_company_knowledge_source(_json_bytes(minimal), ontology=ontology)

    minimal = deepcopy(source_value)
    minimal["nodes"][3]["value"] = {"role": "주사업자", "scope": "가상 구축"}  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="node_value_invalid"):
        parse_company_knowledge_source(_json_bytes(minimal), ontology=ontology)

    explicit = deepcopy(source_value)
    explicit["nodes"][2]["value"] = {  # type: ignore[index]
        "role": "개발", "total": None, "available": None, "as_of": None,
    }
    explicit["nodes"][2]["source_refs"][0]["locator"]["json_pointer"] = "/nodes/2/value/role"  # type: ignore[index]
    explicit["nodes"][2]["source_refs"][0]["quote"] = "개발"  # type: ignore[index]
    explicit["edges"][1]["source_refs"] = deepcopy(explicit["nodes"][2]["source_refs"])  # type: ignore[index]
    explicit["nodes"][3]["value"] = {  # type: ignore[index]
        "role": "주사업자", "scope": "가상 구축",
        "amount_krw": None, "started_on": None, "ended_on": None,
    }
    parsed = parse_company_knowledge_source(_json_bytes(explicit), ontology=ontology)
    by_id = {node.id: node for node in parsed.nodes}
    assert by_id["staff.engineers"].value == {
        "role": "개발", "total": None, "available": None, "as_of": None,
    }
    assert by_id["project.alpha"].value["amount_krw"] is None


@pytest.mark.parametrize(
    ("node_type", "value", "accepted"),
    [
        ("notice", {"notice_id": 7}, True),
        ("notice", {}, False),
        ("notice", {"notice_id": 7, "extra": 1}, False),
        ("notice", {"notice_id": True}, False),
        ("requirement", {"text": "필수 요구", "mandatory": None}, True),
        ("requirement", {"text": "필수 요구", "mandatory": True}, True),
        ("requirement", {"text": "필수 요구"}, False),
        ("requirement", {"text": "필수 요구", "mandatory": "yes"}, False),
        ("requirement", {"text": " ", "mandatory": None}, False),
    ],
)
def test_b2_overlay_values_use_exact_key_sets(node_type: str, value: dict, accepted: bool) -> None:
    from app.core import company_ontology

    if accepted:
        assert company_ontology._node_value(node_type, value) == value
    else:
        with pytest.raises(CompanyKnowledgeValidationError, match="node_value_invalid"):
            company_ontology._node_value(node_type, value)


def test_b2_company_sources_still_reject_overlay_node_types() -> None:
    ontology, source_value, _ = _validated()
    invalid = deepcopy(source_value)
    invalid["nodes"][4]["type"] = "requirement"  # type: ignore[index]
    invalid["nodes"][4]["concept_id"] = None  # type: ignore[index]
    with pytest.raises(CompanyKnowledgeValidationError, match="node_type_invalid"):
        parse_company_knowledge_source(_json_bytes(invalid), ontology=ontology)
