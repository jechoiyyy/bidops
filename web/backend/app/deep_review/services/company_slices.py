"""Company deep-review stage slices and slice-output checks (DEMO-03 STEP-004).

Demo contract §5/§9.  Pure functions: no DB session, no network, no model.
The shared analysis slot (STEP-006) calls ``company_stage_slices`` once per
stage with the **approved** preview's frozen ``CompanyAnalysisInput`` and the
validated outputs of the earlier stages; it never rebuilds or extends the
frozen input.

Stage shapes (the stage output schema stays ``bidops.deep-review-stage.v2``):

* ``requirements_and_evaluation``: one slice per source unit,
  ``{slice_index, requirements: [unit]}`` -- exactly the legacy narrative
  shape.  No company or graph input is given to source extraction.
* ``delivery_risk_economics``: the STEP-001 ``build_company_slices`` result
  (``company_requirements``, ``requirements``, ``graph_paths`` with
  ``global_path_index`` in frozen order, their ``graph_nodes``/``graph_edges``,
  ``profile_facts``/``profile_evidence``, ``company_part_index``/
  ``company_part_count``) plus ``company_coverage`` (the frozen coverage limits
  for that requirement) and the earlier verified claims of the same units packed
  with ``pack_verified`` exactly as the legacy builder does
  (``verified_claims``, ``prior_evidence``, ``prior_part_index``,
  ``prior_part_count``).  The slice-level ``requirement_ids`` of
  ``build_company_slices`` is dropped so a unit ID is never offered where the
  model copies document requirement IDs; ``company_requirements[].id`` keeps it.
* ``synthesis_and_validation``: legacy ``pack_verified`` partial slices.

Every source unit appears in at least one slice (union, no foreign or altered
unit), every frozen graph path in exactly one company part and every frozen
profile fact/evidence row in at least one company part (a fact selected only
by concept match travels with the requirements sharing its concept); otherwise the
stage fails closed with ``slice_coverage_mismatch`` and no completed report can
be produced.  Budgets come from the demo policy ``chunking``
(``source_characters``, ``profile_characters``, ``prior_characters``,
``max_characters`` per slice); nothing is truncated or dropped to fit.

The v2 stage output has no graph field, so graph paths are input-only:
``validate_company_slice_output`` reuses ``validate_slice_output`` unchanged
(evidence/considered/coverage/requirement/quote guards) and adds an exact
match of cited company profile evidence against the slice's supplied rows.
Graph node/edge/path identifiers can never satisfy any output ID field because
those fields are already restricted to supplied claim/evidence/unit IDs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Final

from .company_analysis_input import COMPANY_ANALYSIS_INPUT_KEYS, COMPANY_ANALYSIS_INPUT_SCHEMA
from .company_knowledge_retrieval import (
    RELATION_ORDER,
    REQUIREMENT_KEYS,
    CompanyRetrievalError,
    build_company_slices,
    check_fact_coverage,
    check_slice_coverage,
    validate_source_unit,
)
from .input_versions import DEMO_LUNA_POLICY_IDENTITY, STAGES, canonical_json_hash
from .narrative_inputs import NarrativeInputError, _size, pack_verified, validate_slice_output


SOURCE_STAGE, DELIVERY_STAGE, SYNTHESIS_STAGE = STAGES
CHUNKING_KEYS: Final[tuple[str, ...]] = (
    "source_characters", "profile_characters", "prior_characters", "max_characters",
    "path_limit_per_requirement",
)
PATH_KEYS: Final[frozenset[str]] = frozenset({
    "requirement_id", "node_ids", "edge_ids", "profile_evidence_ids", "relation",
})
#: Keys of a delivery slice that come from the frozen input (prior parts repeat them).
COMPANY_SLICE_KEYS: Final[tuple[str, ...]] = (
    "company_requirements", "requirements", "company_part_index", "company_part_count",
    "graph_paths", "graph_nodes", "graph_edges", "profile_facts", "profile_evidence",
    "company_coverage",
)
PRIOR_SLICE_KEYS: Final[tuple[str, ...]] = ("verified_claims", "prior_evidence", "prior_part_index", "prior_part_count")


def _fail(code: str) -> CompanyRetrievalError:
    return CompanyRetrievalError(code)


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _ids(rows: Any, key: str) -> list[str]:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) or not isinstance(row.get(key), str) for row in rows):
        raise _fail("company_input_invalid")
    values = [row[key] for row in rows]
    if len(values) != len(set(values)):
        raise _fail("company_input_invalid")
    return values


def _chunking(frozen: Mapping[str, Any], policy: Any) -> dict[str, int]:
    """The frozen demo policy only: identity, hash binding and positive budgets."""

    if not isinstance(policy, Mapping) or policy.get("policy_identity") != DEMO_LUNA_POLICY_IDENTITY:
        raise _fail("company_policy_invalid")
    if policy.get("pipeline_version") != "narrative-v2":
        raise _fail("company_policy_invalid")
    # ``deep_reviews._policy_payload`` adds the row's ``policy_sha256``; the
    # canonical policy hash is over the approved file content without it.
    declared = policy.get("policy_sha256")
    body = {key: value for key, value in policy.items() if key != "policy_sha256"}
    if canonical_json_hash(body) != frozen["policy_sha256"] or declared not in {None, frozen["policy_sha256"]}:
        raise _fail("company_policy_invalid")
    chunking = policy.get("chunking")
    if not isinstance(chunking, Mapping) or any(not _positive_int(chunking.get(key)) for key in CHUNKING_KEYS):
        raise _fail("company_policy_invalid")
    return {key: int(chunking[key]) for key in CHUNKING_KEYS}


def _units(frozen: Any) -> dict[str, dict[str, Any]]:
    """Validate the frozen deep-review input and return its source units by ID.

    ``company_input_invalid`` for a wrong shape/purpose, a requirement that is
    not exactly one splitter unit with the same ID, or a graph path whose
    requirement, nodes, edges or evidence are not in the frozen input;
    ``source_units_empty`` for a requirement without units.
    """

    if (
        not isinstance(frozen, Mapping)
        or set(frozen) != COMPANY_ANALYSIS_INPUT_KEYS
        or frozen["schema_version"] != COMPANY_ANALYSIS_INPUT_SCHEMA
        or frozen["purpose"] != "deep_review"
        or not isinstance(frozen["policy_sha256"], str)
        or not isinstance(frozen["coverage"], Mapping)
    ):
        raise _fail("company_input_invalid")
    requirements = frozen["requirements"]
    if not isinstance(requirements, list) or not requirements:
        raise _fail("company_input_invalid")
    units: dict[str, dict[str, Any]] = {}
    for row in requirements:
        if not isinstance(row, Mapping) or set(row) != REQUIREMENT_KEYS or not isinstance(row["source_units"], list):
            raise _fail("company_input_invalid")
        if not row["source_units"]:
            raise _fail("source_units_empty")
        try:
            unit = validate_source_unit(row["source_units"][0]) if len(row["source_units"]) == 1 else None
        except CompanyRetrievalError:
            unit = None
        if unit is None or unit["requirement_id"] != row["id"] or row["id"] in units:
            raise _fail("company_input_invalid")
        units[row["id"]] = unit
    node_ids = set(_ids(frozen["graph_nodes"], "id"))
    edge_ids = set(_ids(frozen["graph_edges"], "id"))
    evidence_ids = set(_ids(frozen["profile_evidence"], "profile_evidence_id"))
    _ids(frozen["profile_facts"], "fact_key")
    paths = frozen["graph_paths"]
    if not isinstance(paths, list):
        raise _fail("company_input_invalid")
    for path in paths:
        if not isinstance(path, Mapping) or set(path) != PATH_KEYS or path["requirement_id"] not in units:
            raise _fail("company_input_invalid")
        if path["relation"] not in RELATION_ORDER:
            raise _fail("company_input_invalid")
        for key, known in (("node_ids", node_ids), ("edge_ids", edge_ids), ("profile_evidence_ids", evidence_ids)):
            if not isinstance(path[key], list) or not set(path[key]) <= known:
                raise _fail("company_input_invalid")
        if path["relation"] == "unmapped" and (path["node_ids"] or path["edge_ids"] or path["profile_evidence_ids"]):
            raise _fail("company_input_invalid")
    coverage = frozen["coverage"]
    for key in ("included_requirement_ids", "unmapped_requirement_ids", "excluded_fact_keys", "excluded_path_count_by_requirement"):
        if not isinstance(coverage.get(key), list):
            raise _fail("company_input_invalid")
    return units


def _expected_units(frozen: Mapping[str, Any], units: Mapping[str, Any]) -> set[str]:
    included = frozen["coverage"]["included_requirement_ids"]
    if len(included) != len(set(included)) or set(included) != set(units):
        raise _fail("slice_coverage_mismatch")
    return set(units)


def _previous(stage: str, previous: Any) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    if stage not in STAGES or isinstance(previous, (str, bytes)) or not isinstance(previous, Sequence):
        raise _fail("stage_input_invalid")
    position = STAGES.index(stage)
    if len(previous) != position or any(
        not isinstance(output, Mapping) or output.get("stage") != STAGES[index]
        for index, output in enumerate(previous)
    ):
        raise _fail("stage_input_invalid")
    claims = [row for output in previous for row in output.get("claims", [])]
    evidence = [row for output in previous for row in output.get("evidence", [])]
    return claims, evidence


def _source_slices(frozen: Mapping[str, Any], budget: int) -> list[dict[str, Any]]:
    slices = []
    for requirement in frozen["requirements"]:
        units = requirement["source_units"]
        if any(_size(unit) > budget for unit in units):
            raise _fail("source_unit_too_large")
        if _size(units) > budget:
            raise _fail("requirement_source_too_large")
        slices.append({"slice_index": len(slices), "requirements": deepcopy(units)})
    return slices


def _company_coverage(frozen: Mapping[str, Any], requirement_ids: Sequence[str]) -> dict[str, Any]:
    coverage = frozen["coverage"]
    return {
        "unmapped_requirement_ids": [rid for rid in requirement_ids if rid in set(coverage["unmapped_requirement_ids"])],
        "excluded_fact_keys": list(coverage["excluded_fact_keys"]),
        "excluded_path_count_by_requirement": [
            deepcopy(row) for row in coverage["excluded_path_count_by_requirement"]
            if isinstance(row, Mapping) and row.get("requirement_id") in requirement_ids
        ],
    }


def _delivery_slices(
    frozen: Mapping[str, Any],
    claims: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    chunking: Mapping[str, int],
) -> list[dict[str, Any]]:
    base = build_company_slices(
        frozen, source_characters=chunking["source_characters"], profile_characters=chunking["profile_characters"],
    )
    slices: list[dict[str, Any]] = []
    for row in base:
        requirement_ids = list(row["requirement_ids"])
        company = {key: deepcopy(value) for key, value in row.items() if key not in {"slice_index", "requirement_ids"}}
        company["company_coverage"] = _company_coverage(frozen, requirement_ids)
        unit_ids = {unit["requirement_id"] for unit in row["requirements"]}
        relevant = [claim for claim in claims if unit_ids & set(claim.get("source_unit_ids", []))]
        if not relevant:
            slices.append({"slice_index": len(slices), **company})
            continue
        parts = pack_verified(relevant, evidence, budget=chunking["prior_characters"])
        for part_index, part in enumerate(parts):
            slices.append({
                "slice_index": len(slices), **deepcopy(company),
                "prior_part_index": part_index, "prior_part_count": len(parts),
                "verified_claims": deepcopy(part["verified_claims"]),
                "prior_evidence": deepcopy(part["prior_evidence"]),
            })
    return slices


def company_stage_slices(
    stage: str,
    frozen_input: Mapping[str, Any],
    previous: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Slices of one stage over an approved company ``CompanyAnalysisInput``.

    ``previous`` are the validated (merged) outputs of the earlier stages in
    order (``stage_input_invalid`` otherwise).  ``policy`` must be the frozen
    ``analysis-policy-luna-demo-v1`` payload whose canonical hash is the
    input's ``policy_sha256`` (``company_policy_invalid`` otherwise).  The
    frozen input is never modified.  Failure codes are those of
    ``CompanyRetrievalError``/``NarrativeInputError`` (``company_input_invalid``,
    ``source_units_empty``, ``source_unit_too_large``,
    ``requirement_source_too_large``, ``graph_path_too_large``,
    ``profile_required_too_large``, ``synthesis_*``, ``slice_too_large``,
    ``slice_coverage_mismatch``).
    """

    claims, evidence = _previous(stage, previous)
    units = _units(frozen_input)
    chunking = _chunking(frozen_input, policy)
    expected = _expected_units(frozen_input, units)
    if stage == SOURCE_STAGE:
        slices = _source_slices(frozen_input, chunking["source_characters"])
    elif stage == DELIVERY_STAGE:
        slices = _delivery_slices(frozen_input, claims, evidence, chunking)
    else:
        if {unit for claim in claims for unit in claim.get("source_unit_ids", [])} != expected:
            raise _fail("slice_coverage_mismatch")
        slices = [deepcopy(row) for row in pack_verified(claims, evidence, budget=chunking["prior_characters"])]
    if any(_size(row) > chunking["max_characters"] for row in slices):
        raise _fail("slice_too_large")
    check_company_stage_slices(stage, frozen_input, slices)
    return slices


def _check_source(units: Mapping[str, Mapping[str, Any]], slices: Sequence[Mapping[str, Any]]) -> None:
    seen: list[str] = []
    for row in slices:
        rows = row.get("requirements")
        if not isinstance(rows, list) or not rows:
            raise _fail("slice_coverage_mismatch")
        for unit in rows:
            unit_id = unit.get("requirement_id") if isinstance(unit, Mapping) else None
            if unit_id not in units or unit != units[unit_id]:
                raise _fail("slice_coverage_mismatch")
            seen.append(unit_id)
    if len(seen) != len(set(seen)) or set(seen) != set(units):
        raise _fail("slice_coverage_mismatch")


def _check_delivery(frozen: Mapping[str, Any], slices: Sequence[Mapping[str, Any]]) -> None:
    nodes = {row["id"]: row for row in frozen["graph_nodes"]}
    edges = {row["id"]: row for row in frozen["graph_edges"]}
    facts = {row["fact_key"]: row for row in frozen["profile_facts"]}
    evidence = {row["profile_evidence_id"]: row for row in frozen["profile_evidence"]}
    groups: dict[tuple[tuple[str, ...], Any], list[Mapping[str, Any]]] = {}
    parts_by_requirement: dict[tuple[str, ...], list[tuple[Any, Any]]] = {}
    for row in slices:
        if any(key not in row for key in COMPANY_SLICE_KEYS) or "requirement_ids" in row:
            raise _fail("slice_coverage_mismatch")
        company_requirements = row["company_requirements"]
        if not isinstance(company_requirements, list) or not company_requirements:
            raise _fail("slice_coverage_mismatch")
        requirement_ids = tuple(item.get("id") if isinstance(item, Mapping) else None for item in company_requirements)
        key = (requirement_ids, row["company_part_index"])
        if key not in groups:
            parts_by_requirement.setdefault(requirement_ids, []).append((row["company_part_index"], row["company_part_count"]))
        groups.setdefault(key, []).append(row)
        indexes = [path.get("global_path_index") if isinstance(path, Mapping) else None for path in row["graph_paths"]]
        if any(type(index) is not int for index in indexes) or indexes != sorted(set(indexes)):
            raise _fail("slice_coverage_mismatch")
        node_ids = {path_node for path in row["graph_paths"] for path_node in path.get("node_ids", [])}
        edge_ids = {path_edge for path in row["graph_paths"] for path_edge in path.get("edge_ids", [])}
        cited = {eid for path in row["graph_paths"] for eid in path.get("profile_evidence_ids", [])}
        for rows, known, id_key in (
            (row["graph_nodes"], nodes, "id"), (row["graph_edges"], edges, "id"),
            (row["profile_facts"], facts, "fact_key"), (row["profile_evidence"], evidence, "profile_evidence_id"),
        ):
            if not isinstance(rows, list) or any(not isinstance(item, Mapping) or known.get(item.get(id_key)) != item for item in rows):
                raise _fail("slice_coverage_mismatch")
        if not node_ids <= {item["id"] for item in row["graph_nodes"]} or not edge_ids <= {item["id"] for item in row["graph_edges"]}:
            raise _fail("slice_coverage_mismatch")
        if not cited <= {item["profile_evidence_id"] for item in row["profile_evidence"]}:
            raise _fail("slice_coverage_mismatch")
    for requirement_ids, parts in parts_by_requirement.items():
        counts = {count for _index, count in parts}
        if len(counts) != 1 or [index for index, _count in parts] != list(range(next(iter(counts)))):
            raise _fail("slice_coverage_mismatch")
    representatives = []
    for (requirement_ids, _part), rows in groups.items():
        first = rows[0]
        company = {key: first[key] for key in COMPANY_SLICE_KEYS}
        if any({key: row[key] for key in COMPANY_SLICE_KEYS} != company for row in rows[1:]):
            raise _fail("slice_coverage_mismatch")
        priors = [row.get("prior_part_index") for row in rows]
        if any("verified_claims" in row for row in rows):
            if any(any(key not in row for key in PRIOR_SLICE_KEYS) or row["prior_part_count"] != len(rows) for row in rows):
                raise _fail("slice_coverage_mismatch")
            if priors != list(range(len(rows))):
                raise _fail("slice_coverage_mismatch")
        elif len(rows) != 1 or any(key in first for key in PRIOR_SLICE_KEYS):
            raise _fail("slice_coverage_mismatch")
        representatives.append({
            "slice_index": len(representatives), "requirement_ids": list(requirement_ids),
            "requirements": first["requirements"], "graph_paths": first["graph_paths"],
        })
    try:
        check_slice_coverage(frozen, representatives)
        # Every frozen fact/evidence row reaches at least one company part
        # (concept-only facts included); none is silently dropped.
        check_fact_coverage(frozen, slices)
    except (KeyError, TypeError, AttributeError):
        raise _fail("slice_coverage_mismatch") from None


def check_company_stage_slices(stage: str, frozen_input: Mapping[str, Any], slices: Sequence[Mapping[str, Any]]) -> None:
    """Re-check stored or rebuilt slices of a stage against the frozen input.

    ``slice_coverage_mismatch`` unless ``slice_index`` is 0..n-1, every frozen
    source unit appears unaltered (source stage: exactly once; delivery: in
    every company part of its requirement), every frozen graph path appears in
    exactly one company part with its ``global_path_index``, unchanged content
    and ascending order, the slice's nodes/edges/facts/evidence are the frozen
    rows, and prior parts are complete.  For synthesis the verified claims must
    cover every source unit.
    """

    if stage not in STAGES:
        raise _fail("stage_input_invalid")
    units = _units(frozen_input)
    expected = _expected_units(frozen_input, units)
    if isinstance(slices, (str, bytes)) or not isinstance(slices, Sequence) or not slices:
        raise _fail("slice_coverage_mismatch")
    if any(not isinstance(row, Mapping) or row.get("slice_index") != index for index, row in enumerate(slices)):
        raise _fail("slice_coverage_mismatch")
    if stage == SOURCE_STAGE:
        _check_source(units, slices)
    elif stage == DELIVERY_STAGE:
        _check_delivery(frozen_input, slices)
    else:
        covered = set()
        for row in slices:
            claims = row.get("verified_claims")
            if row.get("synthesis_phase") not in {"partial", "global"} or not isinstance(claims, list) or not claims:
                raise _fail("slice_coverage_mismatch")
            covered |= {unit for claim in claims for unit in claim.get("source_unit_ids", [])}
        if covered != expected:
            raise _fail("slice_coverage_mismatch")


def validate_company_slice_output(
    output: Mapping[str, Any],
    input_slice: Mapping[str, Any],
    stage: str,
    *,
    source_verification_enabled: bool = True,
) -> None:
    """``validate_slice_output`` unchanged, then exact company evidence rows.

    A cited profile evidence must be a supplied row of this slice (checked by
    ``validate_slice_output``) and copy its ``profile_version_id``,
    ``source_sha256``, ``locator`` and ``quote`` exactly
    (``profile_evidence_mismatch``).  Never modifies ``output``.
    """

    validate_slice_output(output, input_slice, stage, source_verification_enabled=source_verification_enabled)
    supplied = {row["profile_evidence_id"]: row for row in input_slice.get("profile_evidence", [])}
    for row in output["evidence"]:
        if row["source_kind"] != "profile":
            continue
        item = supplied[row["profile_evidence_id"]]
        if (
            row.get("profile_version_id") != item["profile_version_id"]
            or row.get("source_sha256") != item["source_sha256"]
            or row.get("locator_type") != "profile_fact"
            or row.get("locator") != item["locator"]
            or row.get("quote") != item["quote"]
        ):
            raise NarrativeInputError("profile_evidence_mismatch")


def company_validation_profile(frozen_input: Mapping[str, Any]) -> dict[str, Any]:
    """The pinned company profile context for ``validate_deep_review_stage``/merge.

    Only the frozen evidence rows: the deterministic stage validators then
    check profile evidence membership, version, hash and quote, and fact
    numbers against the cited quotes.  Facts are omitted on purpose: the legacy
    completeness check requires a quote per fact, while a company ``unknown``
    fact has an empty quote by contract.
    """

    return {
        "profile_version_id": frozen_input["profile_version_id"],
        "profile_sha256": frozen_input["profile_sha256"],
        "evidence": deepcopy(list(frozen_input["profile_evidence"])),
    }


__all__ = [
    "COMPANY_SLICE_KEYS",
    "STAGES",
    "check_company_stage_slices",
    "company_stage_slices",
    "company_validation_profile",
    "validate_company_slice_output",
]
