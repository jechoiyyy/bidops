"""Deterministic company-knowledge retrieval for DEMO company analysis input.

Demo contract §5/§9 (CompanyAnalysisInput). This module is pure: no DB
session, no network, no model.  It only maps requirement text to ontology
concepts, enumerates company graph paths, selects profile facts within a
budget, records coverage, and packs deep-review slices.  Retrieval is never a
capability or compliance judgment: ``direct``/``partial`` mean "a graph link
exists", ``unmapped`` means "no link was found", and ``unknown`` facts stay
``unknown``.

Accepted shapes
---------------
* ontology: ``app.core.company_ontology.ValidatedOntology`` or a sequence of
  ``OntologyConcept``.  Only its labels/aliases are the dictionary.
* source unit (``SourceUnit``): a mapping with exactly the keys
  ``requirement_id, document_version_id, structure_id, source_sha256,
  document_ordinal, page, block_order, locator_type, locator, text,
  document_requirement_ids`` -- i.e. the ``DeepReviewService._requirements``
  output after the narrative path added ``document_requirement_ids``.
* graph node (``PublicNode``): exactly ``{id,type,label,concept_id,status,
  origin,value,evidence_ids}``; graph edge (``PublicEdge``): exactly
  ``{id,type,from_id,to_id,status,origin,evidence_ids}`` -- the DEMO-02
  ``bidops.company-knowledge-graph.v1`` rows (``model_dump(mode="json")``),
  but for the **whole** graph version, never a truncated view.
  ``source_refs`` or any other key is rejected.
* profile: ``input_versions.profile_context`` output for a
  ``bidops.company-profile.v2`` version: ``{profile_version_id, facts:
  FactV2[], evidence: ProfileEvidence rows[]}`` (extra top-level keys such as
  ``profile_sha256`` are ignored).

Errors are ``CompanyRetrievalError`` with a static code; they subclass
``NarrativeInputError`` so the existing narrative failure handling records the
code without model text, paths, or secrets.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
import re
from typing import Any, Final
from uuid import UUID

from app.core.company_ontology import ORIGINS, OntologyConcept, ValidatedOntology, normalize_term

from .narrative_inputs import NarrativeInputError, _size


DEFAULT_PATH_LIMIT_PER_REQUIREMENT: Final[int] = 32
MAX_GRAPH_HOPS: Final[int] = 3
OVERVIEW_SECTIONS: Final[tuple[str, ...]] = ("business_overview", "main_tasks", "budget_and_period")
RELATION_ORDER: Final[Mapping[str, int]] = {"direct": 0, "partial": 1, "unmapped": 2}

SOURCE_UNIT_KEYS: Final[frozenset[str]] = frozenset({
    "requirement_id", "document_version_id", "structure_id", "source_sha256",
    "document_ordinal", "page", "block_order", "locator_type", "locator", "text",
    "document_requirement_ids",
})
REQUIREMENT_KEYS: Final[frozenset[str]] = frozenset({
    "id", "text", "concept_ids", "mandatory", "source_units", "document_requirement_ids",
})
NODE_KEYS: Final[frozenset[str]] = frozenset({
    "id", "type", "label", "concept_id", "status", "origin", "value", "evidence_ids",
})
EDGE_KEYS: Final[frozenset[str]] = frozenset({
    "id", "type", "from_id", "to_id", "status", "origin", "evidence_ids",
})
EVIDENCE_KEYS: Final[frozenset[str]] = frozenset({
    "profile_evidence_id", "profile_version_id", "fact_key", "source_sha256",
    "locator_type", "locator", "quote",
})
COMPANY_GRAPH_NODE_TYPES: Final[frozenset[str]] = frozenset({
    "company", "capability", "technology", "domain", "staff_group", "project", "qualification", "evidence",
})
CONCEPT_NODE_TYPES: Final[frozenset[str]] = frozenset({"capability", "technology", "domain", "qualification"})
RELATION_TYPES: Final[frozenset[str]] = frozenset({
    "has_capability", "uses_technology", "operates_in", "has_staff", "performed",
    "supports_capability", "holds_qualification", "supported_by",
    "has_requirement", "requires_capability", "requires_qualification",
})
#: RL-03: ``proposed`` (agent-proposed, not confirmed by a person) is carried
#: as-is; like ``unknown`` it is never evidence of possession or absence.
FACT_STATUSES: Final[frozenset[str]] = frozenset({"confirmed", "proposed", "inferred", "unknown"})
#: RL-00 origin enum (7 values).  Retrieval no longer pins the fictional
#: scenario origin: each node/edge/fact keeps its registered origin and a
#: profile evidence row inherits the origin of its fact (RL-03 spec "상태 값").
COMPANY_ORIGINS: Final[frozenset[str]] = ORIGINS
#: Kept for the fictional DEMO fixtures and their tests.
COMPANY_ORIGIN: Final[str] = "fictional_scenario"
# Only these relations are walked from the company node (contract §5:
# has_capability / holds_qualification and supports_capability evidence via
# the company's performed projects and staff groups).
TRAVERSED_RELATIONS: Final[frozenset[str]] = frozenset({
    "has_capability", "holds_qualification", "performed", "has_staff", "supports_capability",
})

_HANGUL_RE: Final[re.Pattern[str]] = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")
_HEX64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_ASCII_ALNUM: Final[str] = "0-9a-z"


class CompanyRetrievalError(NarrativeInputError):
    """Static, source-free code for a rejected company retrieval input."""


def _fail(code: str = "company_input_invalid") -> CompanyRetrievalError:
    return CompanyRetrievalError(code)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(value: Any, code: str) -> int:
    if not _is_int(value) or value < 1:
        raise _fail(code)
    return value


def _uuid_text(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str):
        raise _fail()
    try:
        return str(UUID(value))
    except ValueError:
        raise _fail() from None


def _nonempty_str(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail()
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _fail()
    return list(value)


# --- term matching -----------------------------------------------------------------


def _concepts(ontology: ValidatedOntology | Sequence[OntologyConcept]) -> tuple[OntologyConcept, ...]:
    concepts = ontology.concepts if isinstance(ontology, ValidatedOntology) else ontology
    if isinstance(concepts, (str, bytes)) or not isinstance(concepts, Iterable):
        raise _fail()
    result = tuple(concepts)
    if any(not isinstance(concept, OntologyConcept) for concept in result):
        raise _fail()
    return result


def _term_matches(term: str, text: str) -> bool:
    """Contract §5 rule for one normalized term against normalized text."""

    if len(term) < 2:
        # Single-character terms are never matchable (Hangul 1-char aliases are
        # also rejected at ontology registration).
        return False
    if _HANGUL_RE.search(term):
        return term in text
    pattern = rf"(?<![{_ASCII_ALNUM}]){re.escape(term)}(?![{_ASCII_ALNUM}])"
    return re.search(pattern, text) is not None


def match_concepts(text: str, ontology: ValidatedOntology | Sequence[OntologyConcept]) -> list[str]:
    """Return every ontology concept id whose label/alias occurs in ``text``.

    Text and terms are normalized with ``normalize_term`` (NFKC, casefold,
    whitespace collapse).  Hangul terms (>=2 chars) match as substrings so
    particles/compounds still match; terms without Hangul match only where the
    neighbouring characters are not ASCII letters/digits ("ai" never matches
    "mail").  No synonym expansion, scores, or weights.  Sorted, unique ids.
    """

    if not isinstance(text, str):
        raise _fail()
    normalized = normalize_term(text)
    matched: set[str] = set()
    for concept in _concepts(ontology):
        if concept.id in matched:
            continue
        for term in (concept.label, *concept.aliases):
            if _term_matches(normalize_term(term), normalized):
                matched.add(concept.id)
                break
    return sorted(matched)


# --- requirements -------------------------------------------------------------------


def validate_source_unit(unit: Any) -> dict[str, Any]:
    """Validate one splitter unit and return a deep copy.

    Fallback units (``req-unknown-0000``) or units with empty
    ``document_version_id``/``structure_id``/``source_sha256`` fail with
    ``company_input_invalid``; a unit is never fabricated or repaired.
    """

    if not isinstance(unit, Mapping) or set(unit) != SOURCE_UNIT_KEYS:
        raise _fail()
    _nonempty_str(unit["requirement_id"])
    for key in ("document_version_id", "structure_id"):
        if not isinstance(unit[key], str) or _uuid_text(unit[key]) != unit[key]:
            raise _fail()
    if not isinstance(unit["source_sha256"], str) or _HEX64_RE.fullmatch(unit["source_sha256"]) is None:
        raise _fail()
    for key in ("document_ordinal", "block_order"):
        if not _is_int(unit[key]) or unit[key] < 0:
            raise _fail()
    page = unit["page"]
    if not _is_int(page) or page < 1:
        raise _fail()
    if unit["locator_type"] != "page" or unit["locator"] != {"page": page}:
        raise _fail()
    if not isinstance(unit["locator"]["page"], int) or isinstance(unit["locator"]["page"], bool):
        raise _fail()
    _nonempty_str(unit["text"])
    _string_list(unit["document_requirement_ids"])
    return deepcopy(dict(unit))


def requirements_from_source_units(
    units: Sequence[Mapping[str, Any]],
    ontology: ValidatedOntology | Sequence[OntologyConcept],
) -> list[dict[str, Any]]:
    """Deep-review ``Requirement`` rows: one per splitter unit, splitter order kept.

    ``Requirement.id`` is the unit's ``requirement_id``;
    ``document_requirement_ids`` are copied verbatim; ``mandatory`` is None
    (never inferred); ``concept_ids`` come from ``match_concepts(unit.text)``.
    """

    if isinstance(units, (str, bytes)) or not isinstance(units, Sequence) or not units:
        raise _fail()
    validated = [validate_source_unit(unit) for unit in units]
    ids = [unit["requirement_id"] for unit in validated]
    if len(ids) != len(set(ids)):
        raise _fail()
    return [
        {
            "id": unit["requirement_id"],
            "text": unit["text"],
            "concept_ids": match_concepts(unit["text"], ontology),
            "mandatory": None,
            "source_units": [unit],
            "document_requirement_ids": list(unit["document_requirement_ids"]),
        }
        for unit in validated
    ]


def requirements_from_overview(
    overview_run_id: str | UUID,
    result: Mapping[str, Any],
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    *,
    source_units: Sequence[Mapping[str, Any]] | None = None,
    document_version_id: str | UUID | None = None,
) -> list[dict[str, Any]]:
    """Company-fit ``Requirement`` rows from a completed v7 overview result.

    Rows of ``business_overview``, ``main_tasks``, ``budget_and_period`` (in
    that order, same validation as ``company_fit._run_facts``) become
    ``overview:{overview_run_id}:{section}:{index}`` (index from 0).
    When ``source_units`` (validated splitter units) are given, a row links the
    units whose ``page`` is one of the row's integer evidence pages (and whose
    ``document_version_id`` equals ``document_version_id`` when that is given),
    in the given unit order; ``document_requirement_ids`` is then the sorted
    unique union of the linked units' ids.  Without units both are ``[]``.
    """

    run_id = _uuid_text(overview_run_id)
    if not isinstance(result, Mapping):
        raise _fail()
    units = [validate_source_unit(unit) for unit in (source_units or [])]
    doc_filter = None if document_version_id is None else _uuid_text(document_version_id)
    requirements: list[dict[str, Any]] = []
    for section in OVERVIEW_SECTIONS:
        rows = result.get(section)
        if not isinstance(rows, list):
            raise _fail()
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or not isinstance(row.get("text"), str):
                raise _fail()
            evidence = row.get("evidence")
            if not isinstance(evidence, list):
                raise _fail()
            pages = {
                item["page"] for item in evidence
                if isinstance(item, Mapping) and _is_int(item.get("page"))
            }
            linked = [
                deepcopy(unit) for unit in units
                if unit["page"] in pages and (doc_filter is None or unit["document_version_id"] == doc_filter)
            ]
            requirements.append({
                "id": f"overview:{run_id}:{section}:{index}",
                "text": row["text"],
                "concept_ids": match_concepts(row["text"], ontology),
                "mandatory": None,
                "source_units": linked,
                "document_requirement_ids": sorted({rid for unit in linked for rid in unit["document_requirement_ids"]}),
            })
    return requirements


def _validate_requirements(requirements: Any, concept_ids: set[str] | None) -> list[dict[str, Any]]:
    if isinstance(requirements, (str, bytes)) or not isinstance(requirements, Sequence) or not requirements:
        raise _fail()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in requirements:
        if not isinstance(row, Mapping) or set(row) != REQUIREMENT_KEYS:
            raise _fail()
        requirement_id = _nonempty_str(row["id"])
        if requirement_id in seen:
            raise _fail()
        seen.add(requirement_id)
        if not isinstance(row["text"], str):
            raise _fail()
        concepts = _string_list(row["concept_ids"])
        if concepts != sorted(set(concepts)):
            raise _fail()
        if concept_ids is not None and not set(concepts) <= concept_ids:
            raise _fail()
        if row["mandatory"] is not None and not isinstance(row["mandatory"], bool):
            raise _fail()
        if not isinstance(row["source_units"], list):
            raise _fail()
        units = [validate_source_unit(unit) for unit in row["source_units"]]
        _string_list(row["document_requirement_ids"])
        # A unit may be cited by several overview rows (company_fit); single
        # ownership of a unit is enforced by ``check_slice_coverage`` (deep_review).
        result.append(deepcopy(dict(row)) | {"source_units": units})
    return result


# --- graph --------------------------------------------------------------------------


def _evidence_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise _fail()
    ids = [_uuid_text(item) for item in value]
    if len(ids) != len(set(ids)):
        raise _fail()
    return ids


def normalize_graph(
    graph_nodes: Sequence[Mapping[str, Any]],
    graph_edges: Sequence[Mapping[str, Any]],
    *,
    ontology: ValidatedOntology | Sequence[OntologyConcept] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a whole company graph and return id-sorted deep copies.

    Exactly one ``company`` node; unique node/edge ids; edge endpoints exist;
    enum values valid; ``evidence_ids`` canonical UUID strings; unknown rows
    carry no evidence.  With ``ontology``, concept-typed nodes must reference a
    concept of the same kind and other nodes must have ``concept_id=None``.
    """

    for collection in (graph_nodes, graph_edges):
        if isinstance(collection, (str, bytes)) or not isinstance(collection, Sequence):
            raise _fail()
    kinds = None if ontology is None else {concept.id: concept.kind for concept in _concepts(ontology)}
    nodes: dict[str, dict[str, Any]] = {}
    for raw in graph_nodes:
        if not isinstance(raw, Mapping) or set(raw) != NODE_KEYS:
            raise _fail()
        node_id = _nonempty_str(raw["id"])
        if node_id in nodes or raw["type"] not in COMPANY_GRAPH_NODE_TYPES:
            raise _fail()
        if raw["status"] not in FACT_STATUSES or raw["origin"] not in COMPANY_ORIGINS or not isinstance(raw["label"], str):
            raise _fail()
        concept = raw["concept_id"]
        if concept is not None and not isinstance(concept, str):
            raise _fail()
        if kinds is not None:
            if raw["type"] in CONCEPT_NODE_TYPES:
                if kinds.get(concept) != raw["type"]:
                    raise _fail()
            elif concept is not None:
                raise _fail()
        evidence = _evidence_ids(raw["evidence_ids"])
        if raw["status"] == "unknown" and (evidence or raw["value"] is not None):
            raise _fail()
        nodes[node_id] = deepcopy(dict(raw)) | {"evidence_ids": evidence}
    if [node["type"] for node in nodes.values()].count("company") != 1:
        raise _fail()
    edges: dict[str, dict[str, Any]] = {}
    for raw in graph_edges:
        if not isinstance(raw, Mapping) or set(raw) != EDGE_KEYS:
            raise _fail()
        edge_id = _nonempty_str(raw["id"])
        if edge_id in edges or raw["type"] not in RELATION_TYPES:
            raise _fail()
        if raw["status"] not in FACT_STATUSES or raw["origin"] not in COMPANY_ORIGINS:
            raise _fail()
        if raw["from_id"] not in nodes or raw["to_id"] not in nodes:
            raise _fail()
        evidence = _evidence_ids(raw["evidence_ids"])
        if raw["status"] == "unknown" and evidence:
            raise _fail()
        edges[edge_id] = deepcopy(dict(raw)) | {"evidence_ids": evidence}
    return [nodes[key] for key in sorted(nodes)], [edges[key] for key in sorted(edges)]


def _concept_paths(nodes: Mapping[str, Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    """All (concept_id, relation, node_ids, edge_ids) candidates from the company.

    Simple directed paths of at most ``MAX_GRAPH_HOPS`` edges over
    ``TRAVERSED_RELATIONS``; a node already on the path is not revisited, so
    cycles terminate.  ``direct`` = company -has_capability-> capability or
    company -holds_qualification-> qualification (any scope/status, carried
    as-is).  ``partial`` = path whose last edge is project/staff_group
    -supports_capability-> capability.
    """

    company = next(node_id for node_id, node in nodes.items() if node["type"] == "company")
    adjacency: dict[str, list[Mapping[str, Any]]] = {}
    for edge in edges:
        if edge["type"] in TRAVERSED_RELATIONS:
            adjacency.setdefault(edge["from_id"], []).append(edge)
    for rows in adjacency.values():
        rows.sort(key=lambda edge: (edge["to_id"], edge["id"]))
    found: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []

    def walk(node_ids: tuple[str, ...], edge_ids: tuple[str, ...], last_edge: Mapping[str, Any] | None) -> None:
        if last_edge is not None:
            target = nodes[node_ids[-1]]
            concept = target["concept_id"]
            relation = None
            if len(edge_ids) == 1 and (
                (last_edge["type"] == "has_capability" and target["type"] == "capability")
                or (last_edge["type"] == "holds_qualification" and target["type"] == "qualification")
            ):
                relation = "direct"
            elif (
                last_edge["type"] == "supports_capability"
                and target["type"] == "capability"
                and nodes[node_ids[-2]]["type"] in {"project", "staff_group"}
            ):
                relation = "partial"
            if relation is not None and isinstance(concept, str):
                found.append((concept, relation, node_ids, edge_ids))
        if len(edge_ids) >= MAX_GRAPH_HOPS:
            return
        for edge in adjacency.get(node_ids[-1], []):
            if edge["to_id"] in node_ids:
                continue
            walk((*node_ids, edge["to_id"]), (*edge_ids, edge["id"]), edge)

    walk((company,), (), None)
    return found


def _path_evidence(node_ids: Sequence[str], edge_ids: Sequence[str], nodes: Mapping[str, Mapping[str, Any]], edges: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Evidence ids in path order node0, edge0, node1, edge1, ...; first appearance wins."""

    ordered: list[str] = []
    for position, node_id in enumerate(node_ids):
        rows = [nodes[node_id]]
        if position < len(edge_ids):
            rows.append(edges[edge_ids[position]])
        for row in rows:
            for evidence_id in row["evidence_ids"]:
                if evidence_id not in ordered:
                    ordered.append(evidence_id)
    return ordered


def search_graph_paths(
    requirements: Sequence[Mapping[str, Any]],
    graph_nodes: Sequence[Mapping[str, Any]],
    graph_edges: Sequence[Mapping[str, Any]],
    *,
    path_limit_per_requirement: int = DEFAULT_PATH_LIMIT_PER_REQUIREMENT,
) -> dict[str, Any]:
    """GraphPath search for every requirement (contract §5/§9).

    Returns ``{"graph_paths", "excluded_path_count_by_requirement",
    "unmapped_requirement_ids"}``.  Order: requirement id ascending (plain
    string order), relation direct -> partial -> unmapped, hop count, node id
    tuple, edge id tuple; identical (requirement_id, node_ids, edge_ids) are
    deduplicated.  At most ``path_limit_per_requirement`` paths are kept per
    requirement (cut after sorting, excess counted).  A requirement with no
    concept/company link gets exactly one ``unmapped`` path with empty lists.
    """

    limit = _positive_int(path_limit_per_requirement, "path_limit_invalid")
    rows = _validate_requirements(requirements, None)
    node_list, edge_list = normalize_graph(graph_nodes, graph_edges)
    nodes = {node["id"]: node for node in node_list}
    edges = {edge["id"]: edge for edge in edge_list}
    by_concept: dict[str, list[tuple[str, tuple[str, ...], tuple[str, ...]]]] = {}
    for concept, relation, node_ids, edge_ids in _concept_paths(nodes, edge_list):
        by_concept.setdefault(concept, []).append((relation, node_ids, edge_ids))

    graph_paths: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unmapped: list[str] = []
    for row in sorted(rows, key=lambda item: item["id"]):
        candidates = {
            (node_ids, edge_ids): relation
            for concept in row["concept_ids"]
            for relation, node_ids, edge_ids in by_concept.get(concept, [])
        }
        ordered = sorted(
            ((relation, node_ids, edge_ids) for (node_ids, edge_ids), relation in candidates.items()),
            key=lambda item: (RELATION_ORDER[item[0]], len(item[2]), item[1], item[2]),
        )
        if not ordered:
            unmapped.append(row["id"])
            graph_paths.append({
                "requirement_id": row["id"], "node_ids": [], "edge_ids": [],
                "profile_evidence_ids": [], "relation": "unmapped",
            })
            continue
        if len(ordered) > limit:
            excluded.append({"requirement_id": row["id"], "count": len(ordered) - limit})
        for relation, node_ids, edge_ids in ordered[:limit]:
            graph_paths.append({
                "requirement_id": row["id"],
                "node_ids": list(node_ids),
                "edge_ids": list(edge_ids),
                "profile_evidence_ids": _path_evidence(node_ids, edge_ids, nodes, edges),
                "relation": relation,
            })
    return {
        "graph_paths": graph_paths,
        "excluded_path_count_by_requirement": excluded,
        "unmapped_requirement_ids": unmapped,
    }


def validate_graph_path_indexes(indexes: Any, graph_paths: Sequence[Mapping[str, Any]], requirement_id: str) -> None:
    """Fit ``reasons[].graph_path_indexes`` check: unique, in range, owned by ``requirement_id``."""

    if not isinstance(indexes, list) or any(not _is_int(index) for index in indexes):
        raise _fail("graph_path_index_invalid")
    if len(indexes) != len(set(indexes)):
        raise _fail("graph_path_index_invalid")
    for index in indexes:
        if index < 0 or index >= len(graph_paths) or graph_paths[index].get("requirement_id") != requirement_id:
            raise _fail("graph_path_index_invalid")


# --- profile facts ------------------------------------------------------------------


def _fact_input(fact: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(fact, Mapping):
        raise _fail()
    key = _nonempty_str(fact.get("fact_key"))
    status = fact.get("status")
    origin = fact.get("origin")
    if status not in FACT_STATUSES or not isinstance(origin, str) or origin not in COMPANY_ORIGINS:
        raise _fail()
    if fact.get("locator") != {"fact_key": key} or not isinstance(fact.get("quote"), str):
        raise _fail()
    if status == "unknown" and (fact.get("quote") != "" or fact.get("value") is not None):
        raise _fail()
    return {
        "fact_key": key, "status": status, "origin": origin,
        "value": deepcopy(fact.get("value")), "quote": fact["quote"], "locator": {"fact_key": key},
    }


def _evidence_input(row: Mapping[str, Any], profile_version_id: str, fact_origin: str) -> dict[str, Any]:
    """One ``ProfileEvidenceInput``; its origin is the origin of its fact (preserved, never rewritten)."""

    if not isinstance(row, Mapping) or not EVIDENCE_KEYS <= set(row) or not set(row) <= EVIDENCE_KEYS | {"origin"}:
        raise _fail()
    if row.get("origin", fact_origin) != fact_origin or row["locator_type"] != "profile_fact":
        raise _fail()
    key = _nonempty_str(row["fact_key"])
    if row["locator"] != {"fact_key": key} or not isinstance(row["quote"], str):
        raise _fail()
    if _uuid_text(row["profile_version_id"]) != profile_version_id:
        raise _fail()
    if not isinstance(row["source_sha256"], str) or _HEX64_RE.fullmatch(row["source_sha256"]) is None:
        raise _fail()
    return {
        "profile_evidence_id": _uuid_text(row["profile_evidence_id"]),
        "profile_version_id": profile_version_id,
        "fact_key": key,
        "source_sha256": row["source_sha256"],
        "locator_type": "profile_fact",
        "locator": {"fact_key": key},
        "quote": row["quote"],
        "origin": fact_origin,
    }


def profile_size(facts: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]]) -> int:
    """Budget measure for profile selection (narrative ``_size`` of the pair)."""

    return _size({"profile_facts": list(facts), "profile_evidence": list(evidence)})


def _evidence_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (row["fact_key"], row["profile_evidence_id"])


def _validated_profile(profile: Any, nodes: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(profile, Mapping) or not isinstance(profile.get("facts"), list) or not isinstance(profile.get("evidence"), list):
        raise _fail()
    profile_version_id = _uuid_text(profile.get("profile_version_id"))
    facts: dict[str, dict[str, Any]] = {}
    for fact in profile["facts"]:
        row = _fact_input(fact)
        if row["fact_key"] in facts:
            raise _fail()
        facts[row["fact_key"]] = row
    evidence: dict[str, dict[str, Any]] = {}
    for raw in profile["evidence"]:
        raw_key = raw.get("fact_key") if isinstance(raw, Mapping) else None
        fact = facts.get(raw_key) if isinstance(raw_key, str) else None
        if fact is None:
            raise _fail()
        row = _evidence_input(raw, profile_version_id, fact["origin"])
        if row["profile_evidence_id"] in evidence:
            raise _fail()
        if facts[row["fact_key"]]["status"] == "unknown":
            raise _fail()
        evidence[row["profile_evidence_id"]] = row
    # Profile and graph must be the same binding: one fact per non-evidence node.
    fact_nodes = {node_id for node_id, node in nodes.items() if node["type"] != "evidence"}
    if set(facts) != fact_nodes:
        raise _fail()
    for node_id in fact_nodes:
        if nodes[node_id]["status"] != facts[node_id]["status"]:
            raise _fail()
    return facts, evidence


def select_profile_facts(
    profile: Mapping[str, Any],
    graph_nodes: Sequence[Mapping[str, Any]],
    requirements: Sequence[Mapping[str, Any]],
    graph_paths: Sequence[Mapping[str, Any]],
    *,
    budget: int,
    select_all: bool = False,
) -> dict[str, Any]:
    """Select ``ProfileFactInput`` rows within ``budget`` (``profile_size``).

    ``select_all`` (RL-03 card-v1, spec "전송 payload 규칙" D2): every fact of
    the binding is selected with all its evidence, independent of lexical match
    and of ``budget``; nothing is excluded.  The per-stage transfer projection,
    not this selection, then reduces non-confirmed facts to ``{fact_key,
    status}``.

    Required, independent of lexical match: every ``unknown`` fact and every
    ``qualification`` node fact.  If the required facts alone exceed the
    budget the input fails (``profile_required_too_large``) rather than
    dropping them.  Optional candidates, in order: facts of nodes on the given
    paths (first appearance in path order), then facts of nodes whose
    ``concept_id`` is in any requirement's ``concept_ids`` (fact_key order).
    A candidate that does not fit is listed in ``excluded_fact_keys``; facts
    that were never candidates are not "excluded" and mean nothing.
    ``profile_evidence`` = evidence of selected facts plus every evidence id
    referenced by the given paths (graph binding), sorted by
    (fact_key, profile_evidence_id).  ``profile_facts`` is fact_key sorted.
    """

    limit = _positive_int(budget, "budget_invalid")
    node_list = [dict(node) for node in graph_nodes]
    nodes = {node["id"]: node for node in node_list}
    facts, evidence = _validated_profile(profile, nodes)
    evidence_by_fact: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(evidence.values(), key=_evidence_sort_key):
        evidence_by_fact.setdefault(row["fact_key"], []).append(row)

    if select_all:
        chosen = sorted(facts)
        evidence_ids = {row["profile_evidence_id"] for row in evidence.values()}
        for path in graph_paths:
            if any(evidence_id not in evidence for evidence_id in path["profile_evidence_ids"]):
                raise _fail()
        return {
            "profile_facts": [deepcopy(facts[key]) for key in chosen],
            "profile_evidence": sorted((deepcopy(evidence[eid]) for eid in evidence_ids), key=_evidence_sort_key),
            "excluded_fact_keys": [],
        }
    required = sorted(
        key for key, fact in facts.items()
        if fact["status"] == "unknown" or nodes[key]["type"] == "qualification"
    )
    candidates: list[str] = []
    for path in graph_paths:
        for node_id in path["node_ids"]:
            if node_id in facts and node_id not in required and node_id not in candidates:
                candidates.append(node_id)
    concepts = {concept for row in requirements for concept in row["concept_ids"]}
    for key in sorted(facts):
        if nodes[key]["concept_id"] in concepts and key not in required and key not in candidates:
            candidates.append(key)

    selected = list(required)

    def size(keys: Sequence[str]) -> int:
        ordered = sorted(keys)
        return profile_size([facts[key] for key in ordered], [row for key in ordered for row in evidence_by_fact.get(key, [])])

    if size(selected) > limit:
        raise _fail("profile_required_too_large")
    excluded: list[str] = []
    for key in candidates:
        if size([*selected, key]) <= limit:
            selected.append(key)
        else:
            excluded.append(key)
    chosen = sorted(selected)
    evidence_ids = {row["profile_evidence_id"] for key in chosen for row in evidence_by_fact.get(key, [])}
    for path in graph_paths:
        for evidence_id in path["profile_evidence_ids"]:
            if evidence_id not in evidence:
                raise _fail()
            evidence_ids.add(evidence_id)
    return {
        "profile_facts": [deepcopy(facts[key]) for key in chosen],
        "profile_evidence": sorted((deepcopy(evidence[eid]) for eid in evidence_ids), key=_evidence_sort_key),
        "excluded_fact_keys": sorted(excluded),
    }


def _placeable_profile(
    selection: Mapping[str, Any],
    node_list: Sequence[Mapping[str, Any]],
    graph_paths: Sequence[Mapping[str, Any]],
    *,
    budget: int,
) -> dict[str, Any]:
    """Move concept-only facts that can never fit one slice to ``excluded_fact_keys``.

    A concept-only fact is selected, not required (unknown/qualification) and
    on no kept path; ``build_company_slices`` places it next to the
    requirements sharing its concept, alone if necessary.  If even that
    single-fact company part exceeds ``budget`` it is listed as excluded (and
    its evidence dropped unless a path cites it) -- never silently lost.
    """

    nodes = {node["id"]: node for node in node_list}
    path_nodes = {node_id for path in graph_paths for node_id in path["node_ids"]}
    path_evidence = {eid for path in graph_paths for eid in path["profile_evidence_ids"]}
    facts = list(selection["profile_facts"])
    evidence = list(selection["profile_evidence"])
    excluded = set(selection["excluded_fact_keys"])
    keep: list[dict[str, Any]] = []
    for fact in facts:
        key = fact["fact_key"]
        node = nodes[key]
        required = fact["status"] == "unknown" or node["type"] == "qualification"
        if not required and key not in path_nodes:
            own = [row for row in evidence if row["fact_key"] == key]
            part = {"graph_paths": [], "graph_nodes": [node], "graph_edges": [], "profile_facts": [fact], "profile_evidence": own}
            if company_context_size(part) > budget:
                excluded.add(key)
                continue
        keep.append(fact)
    kept_keys = {fact["fact_key"] for fact in keep}
    return {
        "profile_facts": keep,
        "profile_evidence": [
            row for row in evidence if row["fact_key"] in kept_keys or row["profile_evidence_id"] in path_evidence
        ],
        "excluded_fact_keys": sorted(excluded),
    }


# --- assembly -----------------------------------------------------------------------


def build_coverage(
    requirements: Sequence[Mapping[str, Any]],
    search: Mapping[str, Any],
    excluded_fact_keys: Sequence[str],
) -> dict[str, Any]:
    """``CompanyAnalysisInput.coverage``.

    ``included_requirement_ids`` = every requirement id (sorted);
    ``unmapped_requirement_ids`` = subset with no concept/company link (sorted);
    not a partition.  ``excluded_path_count_by_requirement`` is always present.
    """

    return {
        "included_requirement_ids": sorted(row["id"] for row in requirements),
        "unmapped_requirement_ids": sorted(search["unmapped_requirement_ids"]),
        "excluded_fact_keys": sorted(excluded_fact_keys),
        "excluded_path_count_by_requirement": [dict(row) for row in search["excluded_path_count_by_requirement"]],
    }


def build_company_retrieval(
    requirements: Sequence[Mapping[str, Any]],
    *,
    ontology: ValidatedOntology | Sequence[OntologyConcept],
    graph_nodes: Sequence[Mapping[str, Any]],
    graph_edges: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    path_limit_per_requirement: int,
    profile_budget: int,
    select_all_facts: bool = False,
) -> dict[str, Any]:
    """The retrieval part of ``CompanyAnalysisInput`` for either purpose.

    ``select_all_facts`` is the RL-03 card-v1 mode (D2): every binding fact,
    its node and its evidence are frozen (``profile_budget`` is not applied
    and ``coverage.excluded_fact_keys`` is empty); paths are unchanged.

    Returns exactly ``{requirements, profile_facts, profile_evidence,
    graph_nodes, graph_edges, graph_paths, coverage}``.  ``requirements`` keep
    their given order; ``graph_paths`` follow the §9 order (their list
    positions are the frozen ``graph_path_indexes``/``global_path_index``);
    ``graph_nodes`` are the nodes on kept paths plus the node of **every
    selected fact** (required unknown/qualification facts and facts selected
    by concept match only, so their type and ``concept_id`` survive freezing
    and ``build_company_slices`` can place a concept-only fact in the slices
    of the requirements sharing its concept), ``graph_edges`` the edges on
    kept paths, both id sorted.  A concept-only fact (not required, on no kept
    path) whose own company part -- its node, fact and evidence -- exceeds
    ``profile_budget`` could never be placed in a slice: it is moved to
    ``coverage.excluded_fact_keys`` instead of being dropped silently.  Every
    evidence id on those rows/paths resolves to a ``profile_evidence`` row.
    """

    limit = _positive_int(path_limit_per_requirement, "path_limit_invalid")
    _positive_int(profile_budget, "budget_invalid")
    concepts = _concepts(ontology)
    rows = _validate_requirements(requirements, {concept.id for concept in concepts})
    node_list, edge_list = normalize_graph(graph_nodes, graph_edges, ontology=concepts)
    search = search_graph_paths(rows, node_list, edge_list, path_limit_per_requirement=limit)
    paths = search["graph_paths"]
    selection = select_profile_facts(
        profile, node_list, rows, paths, budget=profile_budget, select_all=select_all_facts,
    )
    profile_part = (
        selection if select_all_facts
        else _placeable_profile(selection, node_list, paths, budget=profile_budget)
    )
    used_nodes = {node_id for path in paths for node_id in path["node_ids"]}
    used_nodes |= {
        node["id"] for node in node_list
        if node["type"] != "evidence" and (node["status"] == "unknown" or node["type"] == "qualification")
    }
    used_nodes |= {fact["fact_key"] for fact in profile_part["profile_facts"]}
    used_edges = {edge_id for path in paths for edge_id in path["edge_ids"]}
    out_nodes = [node for node in node_list if node["id"] in used_nodes]
    out_edges = [edge for edge in edge_list if edge["id"] in used_edges]
    bound = {row["profile_evidence_id"] for row in profile_part["profile_evidence"]}
    if any(not set(row["evidence_ids"]) <= bound for row in (*out_nodes, *out_edges)):
        raise _fail()
    return {
        "requirements": rows,
        "profile_facts": profile_part["profile_facts"],
        "profile_evidence": profile_part["profile_evidence"],
        "graph_nodes": out_nodes,
        "graph_edges": out_edges,
        "graph_paths": paths,
        "coverage": build_coverage(rows, search, profile_part["excluded_fact_keys"]),
    }


# --- slices -------------------------------------------------------------------------


def company_context_size(slice_row: Mapping[str, Any]) -> int:
    """Budget measure of a slice's company part (compared to ``profile_characters``)."""

    return _size({key: slice_row.get(key, []) for key in ("graph_paths", "graph_nodes", "graph_edges", "profile_facts", "profile_evidence")})


def build_company_slices(
    retrieval: Mapping[str, Any],
    *,
    source_characters: int,
    profile_characters: int,
) -> list[dict[str, Any]]:
    """Deep-review slices over a ``build_company_retrieval`` result.

    One or more slices per requirement, in requirement order.  Every slice of
    a requirement carries all of its source units under ``requirements``
    (narrative-compatible key); the units must fit ``source_characters`` (a
    single unit over budget -> ``source_unit_too_large``; several units over
    budget together -> ``requirement_source_too_large``; none ->
    ``source_units_empty``).  The company part (paths with
    ``global_path_index``, their nodes/edges, facts of those nodes that are in
    the input, evidence) must fit ``profile_characters``; part 0 also carries
    the required (unknown + qualification) input facts.  After the paths, the
    requirement's **concept facts** are placed: input facts whose node
    ``concept_id`` is one of the requirement's ``concept_ids`` and that are
    neither required nor on one of its paths (with their node, so the concept
    is visible).  When paths/facts do not fit, follow-up company-comparison
    slices repeat the same units with the next items
    (``company_part_index``/``company_part_count``).  A single path over budget
    -> ``graph_path_too_large``; a single concept fact over budget ->
    ``profile_fact_too_large``; required facts over budget ->
    ``profile_required_too_large``.  Nothing is dropped; the result passes
    ``check_slice_coverage`` and ``check_fact_coverage`` (every input fact and
    evidence row reaches at least one slice).
    """

    source_budget = _positive_int(source_characters, "budget_invalid")
    company_budget = _positive_int(profile_characters, "budget_invalid")
    requirements = retrieval["requirements"]
    paths = retrieval["graph_paths"]
    nodes = {row["id"]: row for row in retrieval["graph_nodes"]}
    edges = {row["id"]: row for row in retrieval["graph_edges"]}
    facts = {row["fact_key"]: row for row in retrieval["profile_facts"]}
    evidence = {row["profile_evidence_id"]: row for row in retrieval["profile_evidence"]}
    evidence_by_fact: dict[str, list[str]] = {}
    for row in sorted(evidence.values(), key=_evidence_sort_key):
        evidence_by_fact.setdefault(row["fact_key"], []).append(row["profile_evidence_id"])
    # Same required rule as ``select_profile_facts``; ``build_company_retrieval``
    # keeps every selected fact's node in ``graph_nodes`` so the type is known.
    required = sorted(
        key for key, fact in facts.items()
        if fact["status"] == "unknown" or (key in nodes and nodes[key]["type"] == "qualification")
    )
    if any(key not in nodes for key in required):
        raise _fail()

    def company_part(path_indexes: Sequence[int], fact_keys: Iterable[str], concept_keys: Sequence[str] = ()) -> dict[str, Any]:
        selected_paths = [{"global_path_index": index, **deepcopy(paths[index])} for index in path_indexes]
        node_ids = {node_id for path in selected_paths for node_id in path["node_ids"]} | set(concept_keys)
        edge_ids = {edge_id for path in selected_paths for edge_id in path["edge_ids"]}
        keys = sorted({*fact_keys, *concept_keys, *(node_id for node_id in node_ids if node_id in facts)})
        evidence_ids = {eid for key in keys for eid in evidence_by_fact.get(key, [])}
        evidence_ids |= {eid for path in selected_paths for eid in path["profile_evidence_ids"]}
        return {
            "graph_paths": selected_paths,
            "graph_nodes": [deepcopy(nodes[key]) for key in sorted(node_ids)],
            "graph_edges": [deepcopy(edges[key]) for key in sorted(edge_ids)],
            "profile_facts": [deepcopy(facts[key]) for key in keys],
            "profile_evidence": sorted((deepcopy(evidence[eid]) for eid in evidence_ids), key=_evidence_sort_key),
        }

    if company_context_size(company_part([], required)) > company_budget:
        raise _fail("profile_required_too_large")

    slices: list[dict[str, Any]] = []
    for requirement in requirements:
        units = requirement["source_units"]
        if not units:
            raise _fail("source_units_empty")
        if any(_size(unit) > source_budget for unit in units):
            raise _fail("source_unit_too_large")
        if _size(units) > source_budget:
            raise _fail("requirement_source_too_large")
        owned = [index for index, path in enumerate(paths) if path["requirement_id"] == requirement["id"]]
        on_paths = {node_id for index in owned for node_id in paths[index]["node_ids"]}
        concepts = set(requirement["concept_ids"])
        concept_facts = sorted(
            key for key in facts
            if key in nodes and nodes[key]["concept_id"] in concepts and key not in required and key not in on_paths
        )
        # Items in order: the requirement's paths (frozen order), then its concept facts.
        items: list[tuple[str, Any]] = [("path", index) for index in owned] + [("fact", key) for key in concept_facts]
        parts: list[tuple[list[int], list[str], list[str]]] = []
        current: list[int] = []
        current_concepts: list[str] = []
        current_facts = list(required)

        def candidate(kind: str, item: Any, with_facts: Sequence[str]) -> dict[str, Any]:
            if kind == "path":
                return company_part([*current, item], with_facts, current_concepts)
            return company_part(current, with_facts, [*current_concepts, item])

        for kind, item in items:
            alone = company_part([item], []) if kind == "path" else company_part([], [], [item])
            if company_context_size(alone) > company_budget:
                raise _fail("graph_path_too_large" if kind == "path" else "profile_fact_too_large")
            occupied = bool(current or current_concepts)
            if occupied and company_context_size(candidate(kind, item, current_facts)) > company_budget:
                parts.append((current, current_facts, current_concepts))
                current, current_facts, current_concepts = [], [], []
            elif not occupied and company_context_size(candidate(kind, item, current_facts)) > company_budget:
                # Required facts and the first item do not fit together: keep the
                # required facts alone in part 0 and continue with a follow-up.
                parts.append(([], current_facts, []))
                current_facts = []
            if kind == "path":
                current.append(item)
            else:
                current_concepts.append(item)
        parts.append((current, current_facts, current_concepts))
        for part_index, (indexes, fact_keys, concept_keys) in enumerate(parts):
            slices.append({
                "slice_index": len(slices),
                "requirement_ids": [requirement["id"]],
                "company_requirements": [{
                    key: deepcopy(requirement[key])
                    for key in ("id", "concept_ids", "mandatory", "document_requirement_ids")
                }],
                "requirements": deepcopy(units),
                "company_part_index": part_index,
                "company_part_count": len(parts),
                **company_part(indexes, fact_keys, concept_keys),
            })
    check_slice_coverage(retrieval, slices)
    check_fact_coverage(retrieval, slices)
    return slices


def check_fact_coverage(retrieval: Mapping[str, Any], slices: Sequence[Mapping[str, Any]]) -> None:
    """Fail with ``slice_coverage_mismatch`` unless every input fact/evidence reaches a slice.

    The union of the slices' ``profile_facts`` keys must equal the input's
    ``profile_facts`` keys and the union of their ``profile_evidence`` ids the
    input's ``profile_evidence`` ids, every row unchanged.  An input fact that
    no slice carries would be silently dropped from the model input.
    """

    facts = {row["fact_key"]: row for row in retrieval["profile_facts"]}
    evidence = {row["profile_evidence_id"]: row for row in retrieval["profile_evidence"]}
    seen_facts: set[str] = set()
    seen_evidence: set[str] = set()
    for row in slices:
        for fact in row.get("profile_facts", []) if isinstance(row, Mapping) else []:
            key = fact.get("fact_key") if isinstance(fact, Mapping) else None
            if key not in facts or fact != facts[key]:
                raise _fail("slice_coverage_mismatch")
            seen_facts.add(key)
        for item in row.get("profile_evidence", []) if isinstance(row, Mapping) else []:
            key = item.get("profile_evidence_id") if isinstance(item, Mapping) else None
            if key not in evidence or item != evidence[key]:
                raise _fail("slice_coverage_mismatch")
            seen_evidence.add(key)
    if seen_facts != set(facts) or seen_evidence != set(evidence):
        raise _fail("slice_coverage_mismatch")


def check_slice_coverage(retrieval: Mapping[str, Any], slices: Sequence[Mapping[str, Any]]) -> None:
    """Fail with ``slice_coverage_mismatch`` unless slices cover the input exactly.

    Rules: ``slice_index`` is 0..n-1 in order; every requirement appears in at
    least one slice; each source unit id is owned by exactly one requirement
    and appears only in slices of that owner; the set union of slice unit ids
    equals the input unit ids (a unit repeated in follow-up company parts of
    its own requirement is the same unit, not a duplicate); each
    ``global_path_index`` appears exactly once overall, in a slice of its
    requirement, with the path content unchanged.
    """

    def fail() -> CompanyRetrievalError:
        return _fail("slice_coverage_mismatch")

    paths = retrieval["graph_paths"]
    owner: dict[str, str] = {}
    unit_rows: dict[str, Mapping[str, Any]] = {}
    for requirement in retrieval["requirements"]:
        for unit in requirement["source_units"]:
            if unit["requirement_id"] in owner:
                raise fail()
            owner[unit["requirement_id"]] = requirement["id"]
            unit_rows[unit["requirement_id"]] = unit
    seen_units: set[str] = set()
    seen_requirements: set[str] = set()
    seen_paths: list[int] = []
    for position, row in enumerate(slices):
        if not isinstance(row, Mapping) or row.get("slice_index") != position:
            raise fail()
        requirement_ids = row.get("requirement_ids")
        if not isinstance(requirement_ids, list) or not requirement_ids:
            raise fail()
        seen_requirements.update(requirement_ids)
        for unit in row.get("requirements", []):
            unit_id = unit.get("requirement_id") if isinstance(unit, Mapping) else None
            if unit_id not in owner or owner[unit_id] not in requirement_ids or unit != unit_rows[unit_id]:
                raise fail()
            seen_units.add(unit_id)
        for path in row.get("graph_paths", []):
            index = path.get("global_path_index") if isinstance(path, Mapping) else None
            if not _is_int(index) or index < 0 or index >= len(paths):
                raise fail()
            if {key: value for key, value in path.items() if key != "global_path_index"} != paths[index]:
                raise fail()
            if paths[index]["requirement_id"] not in requirement_ids:
                raise fail()
            seen_paths.append(index)
    if seen_units != set(owner) or seen_requirements != {row["id"] for row in retrieval["requirements"]}:
        raise fail()
    if sorted(seen_paths) != list(range(len(paths))):
        raise fail()


__all__ = [
    "COMPANY_ORIGINS",
    "CompanyRetrievalError",
    "DEFAULT_PATH_LIMIT_PER_REQUIREMENT",
    "MAX_GRAPH_HOPS",
    "build_company_retrieval",
    "build_company_slices",
    "build_coverage",
    "check_fact_coverage",
    "check_slice_coverage",
    "company_context_size",
    "match_concepts",
    "normalize_graph",
    "profile_size",
    "requirements_from_overview",
    "requirements_from_source_units",
    "search_graph_paths",
    "select_profile_facts",
    "validate_graph_path_indexes",
    "validate_source_unit",
]
