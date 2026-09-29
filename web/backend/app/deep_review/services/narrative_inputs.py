"""Bounded, deterministic inputs for the opt-in narrative-v2 policy.

Selection is retrieval, never a company capability judgment. Every selected
fact travels with its evidence; omitted material remains an explicit limit.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from uuid import UUID, uuid5
from collections.abc import Mapping, Sequence
from typing import Any


class NarrativeInputError(ValueError):
    """Static, source-free code for a rejected narrative input/output scope."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _terms(value: Any) -> set[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    words = re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", text.casefold())
    # Korean spacing and inflection should not make a relevant fact disappear.
    return {part for word in words for part in ([word] + [word[i:i + 2] for i in range(len(word) - 1)] if re.search("[가-힣]", word) else [word])}


def select_profile(requirements: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], budget: int) -> dict[str, Any]:
    query = _terms(" ".join(str(row.get("text", "")) for row in requirements))
    evidence = [row for row in profile.get("evidence", []) if isinstance(row, Mapping)]
    facts = [row for row in profile.get("facts", []) if isinstance(row, Mapping)]
    ranked = []
    for fact in facts:
        key = str(fact.get("fact_key", ""))
        refs = sorted((row for row in evidence if row.get("fact_key") == key), key=lambda row: str(row.get("profile_evidence_id", "")))
        item = {"fact": dict(fact), "evidence": refs}
        score = len(query & _terms(item))
        if score:
            ranked.append((-score, key, item))
    ranked.sort(key=lambda row: (row[0], row[1]))
    selected, excluded = [], []
    for _, key, row in ranked:
        if _size([*selected, row]) <= budget:
            selected.append(row)
        else:
            excluded.append(key)
    chosen = {str(row["fact"].get("fact_key", "")) for row in selected}
    return {
        "profile_facts": [row["fact"] for row in selected],
        "profile_evidence": [ref for row in selected for ref in row["evidence"]],
        "profile_selection": {
            "rule": "lexical-evidence-v1", "selected_fact_keys": sorted(chosen),
            "budget_excluded_fact_keys": sorted(excluded),
            "unselected_fact_count": len(facts) - len(chosen),
            "scope": "selected_subset", "absence_is_noncompliance": False,
        },
    }


def pack_verified(claims: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], *, budget: int, phase: str = "partial") -> list[dict[str, Any]]:
    by_id = {str(row["evidence_id"]): row for row in evidence}

    def payload(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        ids = dict.fromkeys(str(eid) for row in rows for eid in row.get("evidence_ids", []))
        if any(eid not in by_id for eid in ids):
            raise NarrativeInputError("synthesis_evidence_missing")
        return {"verified_claims": list(rows), "prior_evidence": [by_id[eid] for eid in ids], "synthesis_phase": phase}

    result, current = [], []
    for claim in claims:
        if _size(payload([claim])) > budget:
            raise NarrativeInputError("synthesis_item_too_large")
        if current and _size(payload([*current, claim])) > budget:
            result.append(payload(current))
            current = []
        current.append(claim)
    if current:
        result.append(payload(current))
    if not result:
        raise NarrativeInputError("synthesis_input_empty")
    if phase == "global" and len(result) != 1:
        # Never silently turn a bounded partial decision into a global one.
        raise NarrativeInputError("global_synthesis_too_large")
    return [{"slice_index": index, **row} for index, row in enumerate(result)]


def build_slices(stage: str, units: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], previous: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims = [row for output in previous for row in output.get("claims", [])]
    evidence = [row for output in previous for row in output.get("evidence", [])]
    if stage == "synthesis_and_validation":
        return pack_verified(claims, evidence, budget=int(policy["chunking"]["prior_characters"]))
    if not units or any(not str(row.get("text", "")).strip() for row in units):
        raise NarrativeInputError("source_units_empty")
    output = []
    for index, unit in enumerate(units):
        row = {"slice_index": index, "requirements": [dict(unit)]}
        if stage == "delivery_risk_economics":
            row.update(select_profile([unit], profile, int(policy["chunking"]["profile_characters"])))
            relevant = [claim for claim in claims if unit["requirement_id"] in claim.get("source_unit_ids", [])]
            if relevant:
                parts = pack_verified(relevant, evidence, budget=int(policy["chunking"]["prior_characters"]))
                for part_index, part in enumerate(parts):
                    output.append({**row, "slice_index": len(output), "prior_part_index": part_index,
                                   "prior_part_count": len(parts),
                                   **{key: part[key] for key in ("verified_claims", "prior_evidence")}})
                continue
        row["slice_index"] = len(output)
        output.append(row)
    return output


def bind_local_ids(output: Mapping[str, Any], input_slice: Mapping[str, Any]) -> dict[str, Any]:
    """Bind model-local IDs to an invocation; never alter claim/evidence content."""
    result = deepcopy(dict(output))
    maps = []
    for field, id_key, prior in (("claims", "claim_id", input_slice.get("verified_claims", [])), ("evidence", "evidence_id", input_slice.get("prior_evidence", []))):
        ids = [row[id_key] for row in result[field]]
        if len(ids) != len(set(ids)) or set(ids) & {row[id_key] for row in prior}:
            raise NarrativeInputError("local_identifier_redefinition")
        try:
            if any(str(UUID(value)) != value for value in ids):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise NarrativeInputError("local_identifier_invalid") from None
        prefix = f"{output['stage']}:{input_slice['slice_index']}:{input_slice.get('synthesis_phase', '')}:{field}"
        mapping = {value: str(uuid5(UUID(output["attempt_id"]), prefix + ":" + value)) for value in ids}
        for row in result[field]:
            row[id_key] = mapping[row[id_key]]
        maps.append(mapping)
    claims, evidence = maps
    for row in result["claims"]:
        for key in ("related_claim_ids", "premise_claim_ids"):
            row[key] = [claims.get(value, value) for value in row[key]]
        row["evidence_ids"] = [evidence.get(value, value) for value in row["evidence_ids"]]
    for row in result["coverage"]:
        row["claim_ids"] = [claims.get(value, value) for value in row["claim_ids"]]
    return result


def project_related_claims(output: Mapping[str, Any], input_slice: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drop only out-of-scope optional links under the explicit new policy.

    Call after ID binding and before all ordinary validators. Never repair
    premises, evidence, duplicates, self-links or synthesis coverage. Raw output
    remains separate; diagnostics contain IDs only, never model text.
    """
    result = deepcopy(dict(output))
    diagnostics = []
    if policy.get("validation", {}).get("related_claim_policy") != "omit_invalid_with_warning_v1":
        return result, diagnostics
    allowed = {row["claim_id"] for row in result["claims"]} | {row["claim_id"] for row in input_slice.get("verified_claims", [])}
    for row in result["claims"]:
        removed = [value for value in row["related_claim_ids"] if value not in allowed]
        if removed:
            row["related_claim_ids"] = [value for value in row["related_claim_ids"] if value in allowed]
            diagnostics.append({"code": "related_claim_out_of_scope_omitted", "claim_id": row["claim_id"], "removed_related_claim_ids": removed})
    return result, diagnostics


def related_claim_checks(diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"check_type": "related_claim_out_of_scope_omitted", "status": "warning", "severity": "낮음",
             "message": f"관련 주장 연결 {len(row['removed_related_claim_ids'])}개를 확인할 수 없어 제외했습니다.",
             "related_claim_ids": [row["claim_id"]], "related_evidence_ids": []}
            for row in diagnostics]


def validate_slice_output(output: Mapping[str, Any], input_slice: Mapping[str, Any], stage: str, *, source_verification_enabled: bool = True) -> None:
    """Check actual input membership, in addition to the stage schema/graph."""
    claims = output["claims"]
    local = {row["claim_id"]: row for row in claims}
    units = {row["requirement_id"]: row for row in input_slice.get("requirements", [])}
    supplied_prior = {row["claim_id"] for row in input_slice.get("verified_claims", [])}
    if stage != "synthesis_and_validation":
        if not set(output["considered_claim_ids"]) <= supplied_prior:
            raise NarrativeInputError("considered_claim_out_of_slice")
        coverage = output["coverage"]
        if len(coverage) != len(units) or {row["source_unit_id"] for row in coverage} != set(units):
            raise NarrativeInputError("source_coverage_mismatch")
        expected_requirements = {rid for row in units.values() for rid in row.get("document_requirement_ids", [])}
        observed = {rid for row in claims for rid in row["requirement_ids"]}
        if observed != expected_requirements:
            raise NarrativeInputError("requirement_coverage_mismatch")
        for claim in claims:
            if not claim["source_unit_ids"] or not set(claim["source_unit_ids"]) <= set(units):
                raise NarrativeInputError("claim_source_out_of_slice")
        for row in coverage:
            linked = [local[cid] for cid in row["claim_ids"] if cid in local]
            if not linked or any(row["source_unit_id"] not in claim["source_unit_ids"] for claim in linked):
                raise NarrativeInputError("coverage_claim_missing")
            if row["status"] == "reviewed" and not any(claim["claim_type"] != "unknown" and len(claim["body"].strip()) > 12 for claim in linked):
                raise NarrativeInputError("coverage_without_analysis")
    else:
        expected = supplied_prior
        prior_units = {unit for row in input_slice.get("verified_claims", []) for unit in row["source_unit_ids"]}
        prior_requirements = {rid for row in input_slice.get("verified_claims", []) for rid in row["requirement_ids"]}
        if any(not set(row["source_unit_ids"]) <= prior_units or not set(row["requirement_ids"]) <= prior_requirements for row in claims):
            raise NarrativeInputError("synthesis_source_out_of_slice")
        if output["coverage"] or set(output["considered_claim_ids"]) != expected:
            raise NarrativeInputError("synthesis_coverage_mismatch")
        linked = {cid for row in claims for cid in [*row["related_claim_ids"], *row["premise_claim_ids"]]}
        if not expected <= linked:
            raise NarrativeInputError("synthesis_claim_omission")
        recommendations = [row for row in claims if row["narrative_role"] == "recommendation"]
        if len(recommendations) != (1 if input_slice.get("synthesis_phase") == "global" else 0):
            raise NarrativeInputError("recommendation_scope_mismatch")
    if any(not set([*row["related_claim_ids"], *row["premise_claim_ids"]]) <= (set(local) | supplied_prior) for row in claims):
        raise NarrativeInputError("claim_relation_out_of_slice")
    supplied_evidence = {row["evidence_id"] for row in input_slice.get("prior_evidence", [])} | {row["evidence_id"] for row in output["evidence"]}
    if any(not set(row["evidence_ids"]) <= supplied_evidence for row in claims):
        raise NarrativeInputError("evidence_out_of_slice")
    for row in output["evidence"]:
        if row["source_kind"] == "document":
            if not row["quote"] or not any(row["document_version_id"] == unit.get("document_version_id") and row["structure_id"] == unit.get("structure_id") and (row["quote"] in unit["text"] if source_verification_enabled else row["locator"].get("page") == unit.get("page")) for unit in units.values()):
                raise NarrativeInputError("document_evidence_out_of_slice")
        elif row["source_kind"] == "profile":
            if row["profile_evidence_id"] not in {item["profile_evidence_id"] for item in input_slice.get("profile_evidence", [])}:
                raise NarrativeInputError("profile_evidence_out_of_slice")


__all__ = ["build_slices", "pack_verified", "select_profile", "validate_slice_output"]
