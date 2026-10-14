"""Deterministic validation for the five deep-review payload contracts.

Model output is treated as untrusted input.  JSON Schema checks shape and
closed fields; this module checks relationships that cannot be expressed in a
portable schema: evidence scope, claim graph integrity, exact arithmetic,
report completeness, and deterministic bounded-stage merging.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from ..contracts import SchemaValidationError, validate_payload

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
MAX_FORMULA_LENGTH = 512
MAX_FORMULA_AST_NODES = 128
MAX_FORMULA_AST_DEPTH = 32
MAX_CLAIM_GRAPH_NODES = 4096
MAX_CLAIM_GRAPH_EDGES = 16384
REQUIRED_SECTIONS = (
    "project_overview", "eligibility_matrix", "scope_deliverables",
    "requirements_matrix", "evaluation_strategy", "delivery_plan",
    "technical_integration_risks", "security_legal_contract_risks",
    "economics_scenarios", "competitive_proposal_strategy",
    "questions_internal_actions", "document_bundle_limitations", "decision_card",
)
NARRATIVE_SECTIONS = (
    "assessment", "scope", "company_fit", "delivery", "evaluation",
    "contract_economics", "actions", "decision_conditions",
)
DOCUMENT_LOCATORS = {"page", "paragraph", "table_cell", "bbox"}
ALL_LOCATORS = DOCUMENT_LOCATORS | {"profile_fact"}
CLAIM_TYPES = {"fact", "calculation", "inference", "opinion", "unknown"}
RISK_SEVERITIES = {"차단", "중대", "보통", "낮음"}


class DeepReviewValidationError(ValueError):
    """Raised by strict validators with stable, machine-readable issues."""

    def __init__(self, issues: Sequence["ValidationIssue"] | "ValidationIssue" | str):
        if isinstance(issues, str):
            issues = [ValidationIssue("contract_invalid", issues)]
        elif isinstance(issues, ValidationIssue):
            issues = [issues]
        self.issues = tuple(issues)
        message = "; ".join(f"{item.code}: {item.message}" for item in self.issues)
        super().__init__(message)


ContractValidationError = DeepReviewValidationError


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = "$"
    severity: str = "차단"
    related_claim_ids: tuple[str, ...] = ()
    related_evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
            "related_claim_ids": list(self.related_claim_ids),
            "related_evidence_ids": list(self.related_evidence_ids),
        }


@dataclass
class ValidationResult:
    """Result returned by non-strict aggregate validators."""

    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    value: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.valid

    @property
    def error_messages(self) -> list[str]:
        return [item.message for item in self.errors]

    def raise_for_status(self) -> dict[str, Any]:
        if not self.valid:
            raise DeepReviewValidationError(self.errors)
        return self.value if self.value is not None else {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [item.as_dict() for item in self.errors],
            "warnings": [item.as_dict() for item in self.warnings],
            "checks": copy.deepcopy(self.checks),
        }


def _issue(code: str, message: str, path: str = "$", *, severity: str = "차단", claims: Iterable[str] = (), evidence: Iterable[str] = ()) -> ValidationIssue:
    return ValidationIssue(code, message, path, severity, tuple(sorted(set(claims))), tuple(sorted(set(evidence))))


def _schema_issues(payload: Mapping[str, Any], name: str) -> list[ValidationIssue]:
    try:
        validate_payload(payload, name)
    except (SchemaValidationError, ValueError, TypeError) as exc:
        return [_issue("schema_invalid", str(exc))]
    return []


def _strict(payload: Mapping[str, Any], name: str, issues: Sequence[ValidationIssue]) -> dict[str, Any]:
    if issues:
        raise DeepReviewValidationError(issues)
    return dict(payload)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _uuid(value: Any) -> bool:
    return isinstance(value, str) and UUID_RE.fullmatch(value) is not None


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _duplicates(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicate: set[Any] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate, key=str)


def _validate_bbox(bbox: Any, path: str, issues: list[ValidationIssue]) -> None:
    if bbox is None:
        return
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in bbox):
        issues.append(_issue("invalid_bbox", "bbox must contain four finite numbers", path))
    elif bbox[0] > bbox[2] or bbox[1] > bbox[3]:
        issues.append(_issue("invalid_bbox", "bbox coordinates must be ordered x0<=x1 and y0<=y1", path))


def _safe_attributes(value: Any, path: str, issues: list[ValidationIssue], depth: int = 0) -> None:
    if depth > 64:
        issues.append(_issue("attribute_depth", "attributes nesting exceeds the deterministic limit", path))
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or re.search(r"(?:path|url|uri|credential|secret|token|password|shell)", key, re.I):
                issues.append(_issue("unsafe_attribute", "attributes may not contain paths, URLs, credentials, or execution fields", f"{path}.{key}"))
            _safe_attributes(child, f"{path}.{key}", issues, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _safe_attributes(child, f"{path}[{index}]", issues, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        issues.append(_issue("invalid_attribute", "attributes must be JSON scalar/array/object values", path))
    elif isinstance(value, float) and not math.isfinite(value):
        issues.append(_issue("invalid_attribute", "attributes cannot contain non-finite numbers", path))


def _validate_locator(locator_type: Any, locator: Any, *, path: str, allow_none: bool = False) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if allow_none and locator_type == "none":
        if locator is not None:
            issues.append(_issue("locator_mismatch", "none locator must be null", f"{path}.locator"))
        return issues
    if locator_type not in ALL_LOCATORS or not isinstance(locator, Mapping):
        issues.append(_issue("locator_mismatch", "locator_type and locator must use one matching branch", path))
        return issues
    expected: set[str]
    if locator_type == "page":
        expected = {"page"}
        if not isinstance(locator.get("page"), int) or isinstance(locator.get("page"), bool) or locator["page"] < 1:
            issues.append(_issue("invalid_locator", "page locator requires page >= 1", f"{path}.locator.page"))
    elif locator_type == "paragraph":
        expected = {"page", "block_key", "paragraph_key", "text_start", "text_end"}
        if not isinstance(locator.get("page"), int) or isinstance(locator.get("page"), bool) or locator["page"] < 1:
            issues.append(_issue("invalid_locator", "paragraph locator requires page >= 1", f"{path}.locator.page"))
        if not _text(locator.get("block_key")):
            issues.append(_issue("invalid_locator", "paragraph locator requires block_key", f"{path}.locator.block_key"))
        for key in ("text_start", "text_end"):
            if locator.get(key) is not None and (not isinstance(locator[key], int) or isinstance(locator[key], bool) or locator[key] < 0):
                issues.append(_issue("invalid_locator", f"{key} must be null or an integer >= 0", f"{path}.locator.{key}"))
        if locator.get("text_start") is not None and locator.get("text_end") is not None and locator["text_start"] > locator["text_end"]:
            issues.append(_issue("invalid_locator", "text_start must be <= text_end", f"{path}.locator"))
    elif locator_type == "table_cell":
        expected = {"page", "block_key", "table_key", "row", "column"}
        if not isinstance(locator.get("page"), int) or isinstance(locator.get("page"), bool) or locator["page"] < 1:
            issues.append(_issue("invalid_locator", "table-cell locator requires page >= 1", f"{path}.locator.page"))
        for key in ("block_key", "table_key"):
            if not _text(locator.get(key)):
                issues.append(_issue("invalid_locator", f"table-cell locator requires {key}", f"{path}.locator.{key}"))
        for key in ("row", "column"):
            if not isinstance(locator.get(key), int) or isinstance(locator.get(key), bool) or locator[key] < 0:
                issues.append(_issue("invalid_locator", f"{key} must be an integer >= 0", f"{path}.locator.{key}"))
    elif locator_type == "bbox":
        expected = {"page", "block_key", "bbox"}
        if not isinstance(locator.get("page"), int) or isinstance(locator.get("page"), bool) or locator["page"] < 1:
            issues.append(_issue("invalid_locator", "bbox locator requires page >= 1", f"{path}.locator.page"))
        if not _text(locator.get("block_key")):
            issues.append(_issue("invalid_locator", "bbox locator requires block_key", f"{path}.locator.block_key"))
        _validate_bbox(locator.get("bbox"), f"{path}.locator.bbox", issues)
    else:
        expected = {"fact_key"}
        if not _text(locator.get("fact_key")):
            issues.append(_issue("invalid_locator", "profile_fact locator requires fact_key", f"{path}.locator.fact_key"))
    extras = sorted(set(locator) - expected)
    if extras:
        issues.append(_issue("locator_extra_field", f"locator has unexpected field(s): {', '.join(extras)}", f"{path}.locator"))
    return issues


def validate_document_structure(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate document structure identity, references, and graph."""

    issues = _schema_issues(payload, "document-structure")
    if issues:
        raise DeepReviewValidationError(issues)
    pages = payload["pages"]
    blocks = payload["blocks"]
    page_numbers = [item["number"] for item in pages]
    block_keys = [item["block_key"] for item in blocks]
    for duplicates, code, message, path in (
        (_duplicates(page_numbers), "duplicate_page", "page numbers must be unique", "$.pages"),
        (_duplicates(block_keys), "duplicate_block", "block keys must be unique", "$.blocks"),
    ):
        if duplicates:
            issues.append(_issue(code, f"{message}: {duplicates}", path))
    pages_set = set(page_numbers)
    parents: dict[str, str | None] = {}
    for index, block in enumerate(blocks):
        path = f"$.blocks[{index}]"
        if block["page"] not in pages_set:
            issues.append(_issue("dangling_page", "block page must exist in pages", f"{path}.page"))
        _validate_bbox(block.get("bbox"), f"{path}.bbox", issues)
        _safe_attributes(block.get("attributes"), f"{path}.attributes", issues)
        if block["type"] == "table_cell":
            attrs = block["attributes"]
            if not isinstance(attrs, Mapping) or not all(key in attrs for key in ("table_key", "row", "column")):
                issues.append(_issue("table_cell_attributes_missing", "table_cell blocks require table_key, row, and column attributes", f"{path}.attributes"))
        parents[block["block_key"]] = block.get("parent_block_key")
    for key, parent in parents.items():
        if parent is not None and parent not in parents:
            issues.append(_issue("dangling_parent", f"block parent does not resolve: {parent}", "$.blocks"))
    issues.extend(_graph_issues(parents, code="cyclic_parent", message="block parent relationship contains a cycle", path="$.blocks"))
    return _strict(payload, "document-structure", issues)


def validate_document_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate a ready bundle snapshot and its issue locators."""

    issues = _schema_issues(payload, "document-bundle")
    if issues:
        raise DeepReviewValidationError(issues)
    documents = payload["documents"]
    document_ids = [item["document_version_id"] for item in documents]
    ordinals = [item["ordinal"] for item in documents]
    issue_ids = [item["issue_id"] for item in payload["issues"]]
    if duplicates := _duplicates(document_ids):
        issues.append(_issue("duplicate_document", f"document version IDs must be unique: {duplicates}", "$.documents"))
    if duplicates := _duplicates(ordinals):
        issues.append(_issue("duplicate_ordinal", f"document ordinals must be unique: {duplicates}", "$.documents"))
    if duplicates := _duplicates(issue_ids):
        issues.append(_issue("duplicate_issue", f"issue IDs must be unique: {duplicates}", "$.issues"))
    document_set = set(document_ids)
    for index, item in enumerate(documents):
        path = f"$.documents[{index}]"
        if item["source_kind"] == "provider":
            if not _text(item.get("source_system")) or not _text(item.get("source_attachment_key")):
                issues.append(_issue("provider_source_missing", "provider snapshot requires source_system and source_attachment_key", path))
        elif any(item.get(key) is not None for key in ("source_system", "source_attachment_key", "source_url")):
            issues.append(_issue("manual_source_present", "manual snapshot must not retain provider source fields", path))
    blocking = False
    for index, item in enumerate(payload["issues"]):
        path = f"$.issues[{index}]"
        if item["document_version_id"] is not None and item["document_version_id"] not in document_set:
            issues.append(_issue("dangling_issue_document", "issue document_version_id must resolve in documents", f"{path}.document_version_id"))
        issues.extend(_validate_locator(item["locator_type"], item["locator"], path=path, allow_none=True))
        blocking = blocking or bool(item["blocking"])
    if payload["status"] == "ready":
        if not documents:
            issues.append(_issue("ready_without_documents", "ready bundle must contain at least one document", "$.documents"))
        if any(item["safety_status_at_confirmation"] != "safe" for item in documents):
            issues.append(_issue("ready_unsafe_document", "ready bundle documents must all be safe", "$.documents"))
        if blocking:
            issues.append(_issue("ready_blocking_issue", "ready bundle must not contain blocking issues", "$.issues"))
        if not _text(payload.get("confirmed_by")) or not _timestamp(payload.get("confirmed_at")):
            issues.append(_issue("ready_confirmation_missing", "ready bundle requires confirmed_by and timezone-aware confirmed_at", "$"))
    return _strict(payload, "document-bundle", issues)


def _graph_issues(parents: Mapping[str, str | None], *, code: str, message: str, path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    states: dict[str, int] = {}
    for root in parents:
        if states.get(root) == 2:
            continue
        cursor: str | None = root
        active: list[str] = []
        while cursor is not None and states.get(cursor, 0) == 0:
            states[cursor] = 1
            active.append(cursor)
            cursor = parents.get(cursor)
        if cursor is not None and states.get(cursor) == 1:
            cycle_start = active.index(cursor) if cursor in active else 0
            issues.append(_issue(code, f"{message}: {' -> '.join(active[cycle_start:] + [cursor])}", path))
            break
        for key in active:
            states[key] = 2
    return issues


def _claim_cycle_issues(claims: Sequence[Mapping[str, Any]], *, path: str) -> list[ValidationIssue]:
    """Find premise cycles with one bounded, iterative O(V+E) traversal.

    Model output is untrusted, so this deliberately avoids recursive DFS and
    ``list.index`` on the active path (both are easy denial-of-service targets
    with a long or adversarial claim graph).
    """

    node_ids = [claim.get("claim_id") for claim in claims if isinstance(claim.get("claim_id"), str)]
    if len(node_ids) > MAX_CLAIM_GRAPH_NODES:
        return [_issue("claim_graph_bound", "claim premise graph exceeds the bounded node limit", path)]
    node_set = set(node_ids)
    adjacency: dict[str, list[str]] = {}
    edge_count = 0
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        premises = [premise for premise in claim.get("premise_claim_ids", []) if premise in node_set]
        edge_count += len(premises)
        if edge_count > MAX_CLAIM_GRAPH_EDGES:
            return [_issue("claim_graph_bound", "claim premise graph exceeds the bounded edge limit", path)]
        adjacency[claim_id] = premises

    state: dict[str, int] = {}
    for root in adjacency:
        if state.get(root, 0) == 2:
            continue
        state[root] = 1
        active_path = [root]
        active_position = {root: 0}
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            node, next_index = stack[-1]
            neighbors = adjacency.get(node, [])
            if next_index >= len(neighbors):
                stack.pop()
                state[node] = 2
                active_position.pop(node, None)
                active_path.pop()
                continue
            child = neighbors[next_index]
            stack[-1] = (node, next_index + 1)
            child_state = state.get(child, 0)
            if child_state == 2:
                continue
            if child_state == 1:
                start = active_position.get(child, 0)
                cycle = active_path[start:] + [child]
                return [_issue("cyclic_premise", f"claim premise relationship contains a cycle: {' -> '.join(cycle)}", path)]
            state[child] = 1
            active_position[child] = len(active_path)
            active_path.append(child)
            stack.append((child, 0))
    return []


def _context_documents(bundle: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(bundle, Mapping):
        return {}
    documents = bundle.get("documents") or bundle.get("items") or []
    by_document = {item.get("document_version_id"): item for item in documents if isinstance(item, Mapping) and item.get("document_version_id")}
    return by_document


def _context_profile(profile: Mapping[str, Any] | None, profile_version_id: str | None = None) -> tuple[str | None, dict[str, Mapping[str, Any]]]:
    if not isinstance(profile, Mapping):
        return None, {}
    resolved_id = profile.get("profile_version_id") or profile.get("id")
    evidence = profile.get("evidence") or profile.get("profile_evidence") or []
    if isinstance(evidence, Mapping):
        evidence = list(evidence.values())
    by_id = {item.get("profile_evidence_id") or item.get("id"): item for item in evidence if isinstance(item, Mapping) and (item.get("profile_evidence_id") or item.get("id"))}
    return resolved_id, by_id


def _profile_fact_completeness(profile: Mapping[str, Any]) -> list[ValidationIssue]:
    """Require one exact evidence row for every non-unknown profile fact."""

    facts = profile.get("facts")
    if not isinstance(facts, list):
        return []
    evidence = profile.get("evidence") or profile.get("profile_evidence") or []
    if isinstance(evidence, Mapping):
        evidence = list(evidence.values())
    issues: list[ValidationIssue] = []
    keys = [fact.get("fact_key") for fact in facts if isinstance(fact, Mapping)]
    if len(keys) != len(facts) or any(not isinstance(key, str) or not key.strip() for key in keys):
        issues.append(_issue("profile_fact_key_invalid", "profile facts must have non-empty stable keys", "$.profile.facts"))
    if len(set(keys)) != len(keys):
        issues.append(_issue("profile_fact_key_duplicate", "profile fact keys must be unique", "$.profile.facts"))
    by_fact: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in evidence:
        if isinstance(item, Mapping) and isinstance(item.get("fact_key"), str):
            by_fact[item["fact_key"]].append(item)
    fact_keys = {key for key in keys if isinstance(key, str)}
    for key, rows in by_fact.items():
        if key not in fact_keys:
            issues.append(_issue("profile_evidence_extra", "profile evidence must match a declared fact key", "$.profile.evidence"))
        if len(rows) != 1:
            issues.append(_issue("profile_evidence_duplicate", "profile evidence must contain at most one row per fact key", "$.profile.evidence"))
    source_text = profile.get("source_text") or profile.get("source")
    for index, fact in enumerate(facts):
        if not isinstance(fact, Mapping):
            continue
        if fact.get("status") not in {"confirmed", "inferred", "unknown"}:
            issues.append(_issue("profile_fact_status_invalid", "profile fact status is not allowed", f"$.profile.facts[{index}].status"))
        if not _text(fact.get("quote")):
            issues.append(_issue("profile_fact_quote_missing", "profile facts must retain a non-empty source quote", f"$.profile.facts[{index}].quote"))
        elif isinstance(source_text, str) and fact["quote"] not in source_text:
            issues.append(_issue("profile_fact_quote_not_source", "profile fact quote must be a source substring", f"$.profile.facts[{index}].quote"))
        if fact.get("status") == "unknown":
            if isinstance(fact.get("fact_key"), str) and by_fact.get(fact["fact_key"]):
                issues.append(_issue("profile_unknown_has_evidence", "unknown profile facts must not have evidence", f"$.profile.facts[{index}]"))
            continue
        fact_key = fact.get("fact_key")
        rows = by_fact.get(fact_key, []) if isinstance(fact_key, str) else []
        if len(rows) != 1:
            issues.append(_issue("profile_fact_evidence_incomplete", "every non-unknown profile fact requires exactly one matching evidence", f"$.profile.facts[{index}]"))
            continue
        row = rows[0]
        quote = row.get("quote")
        if not _text(quote) or quote != fact.get("quote"):
            issues.append(_issue("profile_fact_quote_mismatch", "profile evidence quote must exactly match the fact source quote", f"$.profile.facts[{index}]"))
        if isinstance(source_text, str) and quote not in source_text:
            issues.append(_issue("profile_fact_quote_not_source", "profile evidence quote must be a source substring", f"$.profile.facts[{index}]"))
    return issues


def _validate_evidence(
    evidence: Mapping[str, Any],
    index: int,
    *,
    bundle: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    profile_version_id: str | None,
    structures: Mapping[str, Mapping[str, Any]] | None = None,
    allow_page_span: bool = False,
    source_verification_enabled: bool = True,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    path = f"$.evidence[{index}]"
    source_kind = evidence["source_kind"]
    if not _text(evidence.get("quote")):
        issues.append(_issue("evidence_quote_missing", "evidence quote must not be blank", f"{path}.quote"))
    if source_kind == "document":
        if evidence.get("document_version_id") is None or evidence.get("structure_id") is None or evidence.get("profile_version_id") is not None or evidence.get("profile_evidence_id") is not None:
            issues.append(_issue("evidence_source_union", "document evidence requires document and structure IDs and null profile IDs", path))
        if evidence.get("locator_type") not in DOCUMENT_LOCATORS:
            issues.append(_issue("evidence_locator_scope", "document evidence must use a document locator", path))
        evidence_id = evidence["evidence_id"]
        if not isinstance(bundle, Mapping):
            issues.append(_issue("bundle_context_missing", "document evidence requires a pinned ready bundle context", path, evidence=[evidence_id]))
        elif bundle.get("status") != "ready":
            issues.append(_issue("bundle_not_ready", "document evidence requires a ready bundle snapshot", path, evidence=[evidence_id]))
        if not isinstance(structures, Mapping):
            issues.append(_issue("structure_context_missing", "document evidence requires a pinned structure context", path, evidence=[evidence_id]))

        by_document = _context_documents(bundle)
        document_id = evidence.get("document_version_id")
        if document_id not in by_document:
            issues.append(_issue("evidence_out_of_bundle", "document evidence is outside the ready bundle snapshot", path, evidence=[evidence["evidence_id"]]))
        if document_id in by_document:
            item = by_document[document_id]
            if item.get("structure_id_at_confirmation") != evidence.get("structure_id"):
                issues.append(_issue("evidence_structure_scope", "evidence structure is not the confirmed bundle structure", path, evidence=[evidence_id]))
            if item.get("content_sha256") != evidence.get("source_sha256"):
                issues.append(_issue("evidence_source_hash_mismatch", "evidence source hash must exactly match the confirmed document content hash", path, evidence=[evidence_id]))

        structure = None
        if isinstance(structures, Mapping):
            candidate = structures.get(evidence.get("structure_id"))
            if isinstance(candidate, Mapping):
                structure = candidate
            else:
                issues.append(_issue("structure_context_missing", "evidence structure ID is absent from the pinned structure context", path, evidence=[evidence_id]))
        if structure is not None:
            if structure.get("structure_id") != evidence.get("structure_id"):
                issues.append(_issue("evidence_structure_scope", "structure payload ID does not match evidence structure ID", path, evidence=[evidence_id]))
            if structure.get("document_version_id") != evidence.get("document_version_id"):
                issues.append(_issue("evidence_document_scope", "structure payload document version does not match evidence", path, evidence=[evidence_id]))
            if structure.get("source_sha256") != evidence.get("source_sha256"):
                issues.append(_issue("evidence_source_hash_mismatch", "evidence source hash must exactly match the pinned structure source hash", path, evidence=[evidence_id]))
            if document_id in by_document and by_document[document_id].get("structure_id_at_confirmation") != structure.get("structure_id"):
                issues.append(_issue("evidence_structure_scope", "pinned structure is not the bundle-confirmed structure", path, evidence=[evidence_id]))
            _resolve_document_locator(evidence, structure, path=path, issues=issues, allow_page_span=allow_page_span, source_verification_enabled=source_verification_enabled)
    else:
        if any(evidence.get(key) is not None for key in ("document_version_id", "structure_id")) or evidence.get("profile_version_id") is None or evidence.get("profile_evidence_id") is None:
            issues.append(_issue("evidence_source_union", "profile evidence requires profile IDs and null document IDs", path))
        if evidence.get("locator_type") != "profile_fact":
            issues.append(_issue("evidence_locator_scope", "profile evidence must use profile_fact locator", path))
        resolved_profile, profile_evidence = _context_profile(profile, profile_version_id)
        evidence_id = evidence["evidence_id"]
        if not isinstance(profile, Mapping) or not resolved_profile or not profile_evidence:
            issues.append(_issue("profile_context_missing", "profile evidence requires a pinned profile version and evidence context", path, evidence=[evidence_id]))
        if profile_version_id is not None and resolved_profile and resolved_profile != profile_version_id:
            issues.append(_issue("profile_context_mismatch", "profile context does not match the requested pinned profile version", path, evidence=[evidence_id]))
        if resolved_profile and evidence.get("profile_version_id") != resolved_profile:
            issues.append(_issue("evidence_out_of_profile", "profile evidence is outside the pinned profile version", path, evidence=[evidence["evidence_id"]]))
        profile_evidence_item = profile_evidence.get(evidence.get("profile_evidence_id"))
        if not profile_evidence_item:
            issues.append(_issue("evidence_profile_ref_missing", "profile evidence ID is not in the pinned profile", path, evidence=[evidence["evidence_id"]]))
        if profile_evidence_item:
            context_fact_key = profile_evidence_item.get("fact_key")
            context_source_hash = profile_evidence_item.get("source_sha256")
            context_quote = profile_evidence_item.get("quote")
            context_profile_id = profile_evidence_item.get("profile_version_id")
            if context_profile_id is not None and context_profile_id != resolved_profile:
                issues.append(_issue("evidence_out_of_profile", "pinned profile evidence belongs to another profile version", path, evidence=[evidence_id]))
            if not _text(context_fact_key) or evidence["locator"].get("fact_key") != context_fact_key:
                issues.append(_issue("profile_fact_key_mismatch", "profile evidence fact_key does not match the pinned profile evidence", path, evidence=[evidence_id]))
            if not _sha(context_source_hash) or context_source_hash != evidence.get("source_sha256"):
                issues.append(_issue("evidence_source_hash_mismatch", "profile evidence source hash must exactly match the pinned evidence", path, evidence=[evidence_id]))
            if source_verification_enabled and (not _text(context_quote) or context_quote != evidence.get("quote")):
                issues.append(_issue("evidence_quote_mismatch", "profile evidence quote must exactly match the pinned evidence quote", path, evidence=[evidence_id]))
    issues.extend(_validate_locator(evidence["locator_type"], evidence["locator"], path=path))
    return issues


def _resolve_document_locator(
    evidence: Mapping[str, Any],
    structure: Mapping[str, Any],
    *,
    path: str,
    issues: list[ValidationIssue],
    allow_page_span: bool = False,
    source_verification_enabled: bool = True,
) -> None:
    """Resolve every document locator and prove its quote comes from content."""

    evidence_id = evidence["evidence_id"]
    locator_type = evidence["locator_type"]
    locator = evidence["locator"]
    page_number = locator.get("page")
    pages = {item.get("number") for item in structure.get("pages", []) if isinstance(item, Mapping)}
    blocks = {
        item.get("block_key"): item
        for item in structure.get("blocks", [])
        if isinstance(item, Mapping) and item.get("block_key")
    }
    if page_number not in pages:
        issues.append(_issue("locator_unresolved", "evidence locator page is absent from the pinned structure", path, evidence=[evidence_id]))
        return

    quote = evidence.get("quote")
    page_blocks = [item for item in blocks.values() if item.get("page") == page_number]
    block = None
    if locator_type == "page":
        from .quote_matching import page_texts
        texts = page_texts(page_blocks) if allow_page_span else [item["text"] for item in page_blocks if isinstance(item.get("text"), str)]
        if source_verification_enabled and not any(quote in text for text in texts):
            issues.append(_issue("evidence_quote_mismatch", "page evidence quote is absent from pinned block content", path, evidence=[evidence_id]))
        return

    block_key = locator.get("block_key")
    block = blocks.get(block_key)
    if block is None:
        issues.append(_issue("locator_unresolved", "evidence locator block is absent from the pinned structure", path, evidence=[evidence_id]))
        return
    if block.get("page") != page_number:
        issues.append(_issue("locator_unresolved", "evidence locator page does not match the pinned block page", path, evidence=[evidence_id]))
    text = block.get("text")
    if source_verification_enabled and (not isinstance(text, str) or quote not in text):
        issues.append(_issue("evidence_quote_mismatch", "evidence quote is absent from pinned block content", path, evidence=[evidence_id]))
    if locator_type == "paragraph":
        start, end = locator.get("text_start"), locator.get("text_end")
        if start is not None and end is not None:
            if not isinstance(text, str) or end > len(text) or (source_verification_enabled and text[start:end] != quote):
                issues.append(_issue("locator_unresolved", "paragraph offsets do not resolve to the cited quote", path, evidence=[evidence_id]))
        paragraph_key = locator.get("paragraph_key")
        if paragraph_key is not None and block.get("attributes", {}).get("paragraph_key") != paragraph_key:
            issues.append(_issue("locator_unresolved", "paragraph key does not match the pinned block", path, evidence=[evidence_id]))
    elif locator_type == "table_cell":
        attrs = block.get("attributes", {})
        if not isinstance(attrs, Mapping) or any(attrs.get(field_name) != locator.get(field_name) for field_name in ("table_key", "row", "column")):
            issues.append(_issue("locator_unresolved", "table-cell locator does not match the pinned structure block", path, evidence=[evidence_id]))
    elif locator_type == "bbox":
        block_bbox = block.get("bbox")
        cited_bbox = locator.get("bbox")
        if not isinstance(block_bbox, list) or len(block_bbox) != 4 or any(cited_bbox[index] < block_bbox[index] for index in (0, 1)) or any(cited_bbox[index] > block_bbox[index] for index in (2, 3)):
            issues.append(_issue("locator_unresolved", "bbox locator is outside the pinned block bounds", path, evidence=[evidence_id]))


def _validate_claims(
    claims: Sequence[Mapping[str, Any]],
    evidence_ids: set[str],
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    path_prefix: str = "$.claims",
    known_claim_ids: set[str] | None = None,
    source_verification_enabled: bool = True,
    result_checks_enabled: bool = True,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    claim_ids = [claim.get("claim_id") for claim in claims]
    if duplicates := _duplicates(claim_ids):
        issues.append(_issue("duplicate_claim", f"claim IDs must be unique: {duplicates}", path_prefix, claims=[str(value) for value in duplicates]))
    ids = {value for value in claim_ids if isinstance(value, str)}
    allowed_premises = ids | (known_claim_ids or set())
    for index, claim in enumerate(claims):
        claim_id = claim["claim_id"]
        path = f"{path_prefix}[{index}]"
        evidence = claim["evidence_ids"]
        premises = claim["premise_claim_ids"]
        if duplicates := _duplicates(evidence):
            issues.append(_issue("duplicate_claim_evidence", f"claim evidence IDs must be unique: {duplicates}", f"{path}.evidence_ids", claims=[claim_id], evidence=[str(value) for value in duplicates]))
        if duplicates := _duplicates(premises):
            issues.append(_issue("duplicate_premise", f"premise IDs must be unique: {duplicates}", f"{path}.premise_claim_ids", claims=[claim_id]))
        for evidence_id in evidence:
            if evidence_id not in evidence_ids:
                issues.append(_issue("dangling_evidence", f"claim references unknown evidence: {evidence_id}", f"{path}.evidence_ids", claims=[claim_id], evidence=[evidence_id]))
        if not result_checks_enabled:
            continue
        for premise in premises:
            if premise not in allowed_premises:
                issues.append(_issue("dangling_premise", f"claim premise does not resolve: {premise}", f"{path}.premise_claim_ids", claims=[claim_id, premise]))
        claim_type = claim["claim_type"]
        if claim_type == "fact":
            if not evidence:
                issues.append(_issue("fact_evidence_required", "fact claims require direct evidence", path, claims=[claim_id]))
            if claim["formula"] is not None or premises:
                issues.append(_issue("fact_shape", "fact claims cannot have formula or premise claims", path, claims=[claim_id]))
        elif claim_type == "calculation":
            if not _text(claim.get("formula")):
                issues.append(_issue("calculation_formula_required", "calculation claims require a formula", path, claims=[claim_id]))
            if not evidence:
                issues.append(_issue("calculation_evidence_required", "calculation claims require input evidence", path, claims=[claim_id]))
            if premises:
                issues.append(_issue("calculation_premise_shape", "calculation claims use evidence inputs, not premise claims", path, claims=[claim_id]))
            if _text(claim.get("formula")):
                try:
                    replay_calculation(claim["formula"], expected=_calculation_expected(claim["formula"], claim["body"]))
                    if source_verification_enabled:
                        issues.extend(_validate_calculation_inputs(claim, evidence_by_id or {}, path=path))
                except ValueError as exc:
                    issues.append(_issue("calculation_replay_failed", str(exc), f"{path}.formula", claims=[claim_id], evidence=evidence))
        elif claim_type == "inference":
            if not premises:
                issues.append(_issue("inference_premise_required", "inference claims require premise claims", path, claims=[claim_id]))
            if not evidence:
                issues.append(_issue("inference_evidence_required", "inference claims require evidence", path, claims=[claim_id]))
            if not _text(claim.get("reason")):
                issues.append(_issue("inference_reason_required", "inference claims require an explanation", path, claims=[claim_id]))
            if claim["formula"] is not None:
                issues.append(_issue("inference_formula_forbidden", "inference claims cannot have a formula", path, claims=[claim_id]))
        elif claim_type == "opinion":
            if not _text(claim.get("reason")):
                issues.append(_issue("opinion_reason_required", "opinion claims require a reason", path, claims=[claim_id]))
            if claim["formula"] is not None or premises:
                issues.append(_issue("opinion_shape", "opinion claims cannot have formula or premise claims", path, claims=[claim_id]))
        elif claim_type == "unknown":
            if not _text(claim.get("reason")):
                issues.append(_issue("unknown_reason_required", "unknown claims must explain the missing or conflicting evidence", path, claims=[claim_id]))
            if claim["formula"] is not None or premises:
                issues.append(_issue("unknown_shape", "unknown claims cannot have formula or premise claims", path, claims=[claim_id]))
    if result_checks_enabled:
        issues.extend(_claim_cycle_issues(claims, path=path_prefix))
    return issues


def _calculation_expected(formula: str, body: str) -> str | None:
    if "=" in formula:
        parts = formula.split("=")
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
    if _numeric_expression(body):
        return body.strip()
    # A result marker avoids guessing at numbers used as explanatory inputs.
    match = re.search(r"(?:결과|합계|총액|result|total|answer)\s*(?:은|는|:|=)\s*([-+]?\d[\d,]*(?:\.\d+)?)", body, re.I)
    return match.group(1).replace(",", "") if match else None


def _numeric_expression(value: str) -> bool:
    return bool(re.fullmatch(r"\s*[-+]?\d[\d,]*(?:\.\d+)?\s*", value or ""))


def _formula_numeric_inputs(formula: str) -> list[Decimal]:
    """Extract only user-supplied numeric literals from the formula LHS.

    Percent normalization adds a synthetic ``100`` denominator later; parsing
    the original left side prevents that implementation detail from becoming
    an uncited input.
    """

    left = formula.replace("×", "*").replace("÷", "/").replace("−", "-").replace("，", ",").split("=", 1)[0]
    values: list[Decimal] = []
    for token in NUMBER_RE.findall(left):
        try:
            values.append(_decimal(token))
        except ValueError:
            continue
    return values


def _quote_numbers(quote: Any) -> list[Decimal]:
    if not isinstance(quote, str):
        return []
    values: list[Decimal] = []
    for token in NUMBER_RE.findall(quote):
        try:
            values.append(_decimal(token))
        except ValueError:
            continue
    return values


_WON_AMOUNT = re.compile(r"(?<![\d.,])([+-]?\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|십만|만|천|백)?\s*원")
_WON_SCALE = {None: 1, "백": 100, "천": 1000, "만": 10000, "십만": 100000, "백만": 1000000, "천만": 10000000, "억": 100000000}
_SHORT_YEAR = re.compile(r"[’'‘]\s*(\d{2})(?=\s*(?:년|[.]))")


def _fact_numeric_status(body: str, quotes: Sequence[str]) -> tuple[bool, bool]:
    """Separate value mismatches from exact currency equivalence and short years.

    A two-digit year alone does not prove a century. It produces a report
    warning, rather than aborting all analysis as a fabricated number.
    """
    amounts = {Decimal(m[1].replace(",", "")) * _WON_SCALE[m[2]] for quote in quotes for m in _WON_AMOUNT.finditer(quote)}
    body_amounts = list(_WON_AMOUNT.finditer(body))
    if any(Decimal(m[1].replace(",", "")) * _WON_SCALE[m[2]] not in amounts for m in body_amounts):
        return False, False
    remainder = _WON_AMOUNT.sub("", body)
    cited = {n for quote in quotes for n in _quote_numbers(quote)}
    missing = set(_quote_numbers(remainder)) - cited
    abbreviated = {int(m[1]) for quote in quotes for m in _SHORT_YEAR.finditer(quote)}
    years = {n for n in missing if n == int(n) and 1900 <= n <= 2199 and int(n) % 100 in abbreviated and re.search(rf"(?<!\d){int(n)}\s*(?:년|[./-])", body)}
    return not (missing - years), bool(years)


def narrative_numeric_warnings(claims: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["evidence_id"]: row for row in evidence}
    warnings = []
    for row in claims:
        quotes = [str(by_id[eid].get("quote", "")) for eid in row.get("evidence_ids", []) if eid in by_id]
        if row["claim_type"] == "fact" and _fact_numeric_status(row["body"], quotes)[1]:
            warnings.append({"check_type": "year_notation", "status": "warning", "severity": "낮음", "message": "원문에 축약된 연도를 본문에서 풀어 썼습니다. 해당 연도는 원문과 함께 확인하십시오.", "related_claim_ids": [row["claim_id"]], "related_evidence_ids": row["evidence_ids"]})
    return warnings


def _validate_calculation_inputs(
    claim: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    *,
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    formula = claim.get("formula")
    if not _text(formula):
        return issues
    cited = [evidence_by_id[evidence_id] for evidence_id in claim.get("evidence_ids", []) if evidence_id in evidence_by_id]
    for numeric_input in _formula_numeric_inputs(formula):
        if not any(numeric_input in _quote_numbers(item.get("quote")) for item in cited):
            issues.append(_issue(
                "calculation_input_evidence_missing",
                f"calculation input {numeric_input} is not present in any cited evidence quote",
                f"{path}.formula",
                claims=[claim["claim_id"]],
                evidence=claim.get("evidence_ids", []),
            ))
    return issues


class _DecimalExpression(ast.NodeVisitor):
    def __init__(self, inputs: Mapping[str, Decimal] | None = None) -> None:
        self.inputs = inputs or {}

    def visit_Expression(self, node: ast.Expression) -> Decimal:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Decimal:
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
            raise ValueError("formula contains a non-decimal literal")
        try:
            return Decimal(str(node.value).replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("formula contains an invalid decimal literal") from exc

    def visit_Name(self, node: ast.Name) -> Decimal:
        if node.id not in self.inputs:
            raise ValueError(f"formula input is not provided: {node.id}")
        return self.inputs[node.id]

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Decimal:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("formula uses a forbidden unary operator")

    def visit_BinOp(self, node: ast.BinOp) -> Decimal:
        left, right = self.visit(node.left), self.visit(node.right)
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow) and right == right.to_integral_value() and abs(right) <= 100:
                return left ** int(right)
        except (InvalidOperation, ZeroDivisionError) as exc:
            raise ValueError("formula arithmetic is not defined") from exc
        raise ValueError("formula uses a forbidden operator")

    def generic_visit(self, node: ast.AST) -> Decimal:
        raise ValueError("formula contains a forbidden expression")


def _parse_bounded_expression(expression: str) -> ast.Expression:
    if len(expression) > MAX_FORMULA_LENGTH:
        raise ValueError("formula exceeds the bounded length limit")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("formula cannot be parsed") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_FORMULA_AST_NODES:
        raise ValueError("formula AST exceeds the bounded node limit")
    pending: list[tuple[ast.AST, int]] = [(tree, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_FORMULA_AST_DEPTH:
            raise ValueError("formula AST exceeds the bounded depth limit")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return tree


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ValueError("expected a decimal value")
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError("decimal value must be finite")
    return parsed


def replay_calculation(formula: str, expected: Any = None, *, inputs: Mapping[str, Any] | None = None) -> Decimal:
    """Replay a safe arithmetic formula with exact ``Decimal`` semantics.

    Formulas may use numbers, named values supplied through ``inputs``,
    parentheses, ``+ - * / % **`` and a single ``=`` assertion.  No code,
    attribute access, float rounding, or implicit model correction is allowed.
    """

    if not _text(formula):
        raise ValueError("calculation formula is empty")
    normalized = formula.replace("×", "*").replace("÷", "/").replace("−", "-").replace("，", ",")
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = re.sub(r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)\s*%(?!\s*\d)", r"(\g<number>/100)", normalized)
    equality = normalized.count("=")
    if equality > 1:
        raise ValueError("formula may contain at most one equality")
    left_text, right_text = (normalized.split("=", 1) + [None])[:2] if equality else (normalized, None)
    supplied = {key: _decimal(value) for key, value in (inputs or {}).items()}
    try:
        tree = _parse_bounded_expression(left_text)
        with localcontext() as context:
            context.prec = 256
            result = _DecimalExpression(supplied).visit(tree)
            if not result.is_finite():
                raise ValueError("formula result is not finite")
            if right_text is not None and right_text.strip():
                asserted = _DecimalExpression(supplied).visit(_parse_bounded_expression(right_text))
                if result != asserted:
                    raise ValueError(f"formula equality failed: {result} != {asserted}")
            if expected is not None:
                expected_decimal = _decimal(expected)
                if result != expected_decimal:
                    raise ValueError(f"formula result does not match claim body: {result} != {expected_decimal}")
            return +result
    except (SyntaxError, ValueError, InvalidOperation, ZeroDivisionError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("formula cannot be replayed deterministically") from exc


def validate_deep_review_stage(
    payload: Mapping[str, Any],
    *,
    bundle: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    profile_version_id: str | None = None,
    expected_deep_review_id: str | None = None,
    known_claim_ids: set[str] | None = None,
    known_evidence_ids: set[str] | None = None,
    known_evidence: Sequence[Mapping[str, Any]] = (),
    structures: Mapping[str, Mapping[str, Any]] | None = None,
    source_verification_enabled: bool = True,
    result_checks_enabled: bool = True,
) -> dict[str, Any]:
    """Validate one bounded analysis stage and all local claim/evidence links."""

    narrative = payload.get("schema") == "bidops.deep-review-stage.v2"
    issues = _schema_issues(payload, "deep-review-stage-v2" if narrative else "deep-review-stage")
    if issues:
        raise DeepReviewValidationError(issues)
    if expected_deep_review_id and payload["deep_review_id"] != expected_deep_review_id:
        issues.append(_issue("review_scope", "stage deep_review_id does not match the current review", "$.deep_review_id"))
    if isinstance(profile, Mapping):
        issues.extend(_profile_fact_completeness(profile))
    evidence = payload["evidence"]
    evidence_ids = [item["evidence_id"] for item in evidence]
    if duplicates := _duplicates(evidence_ids):
        issues.append(_issue("duplicate_evidence", f"evidence IDs must be unique: {duplicates}", "$.evidence"))
    for index, item in enumerate(evidence):
        issues.extend(_validate_evidence(item, index, bundle=bundle, profile=profile, profile_version_id=profile_version_id, structures=structures, allow_page_span=payload.get("schema") == "bidops.deep-review-stage.v2", source_verification_enabled=source_verification_enabled))
    evidence_set = set(evidence_ids) | (known_evidence_ids or set())
    evidence_by_id = {item["evidence_id"]: item for item in known_evidence if item["evidence_id"] in (known_evidence_ids or set())}
    evidence_by_id.update({item["evidence_id"]: item for item in evidence})
    issues.extend(_validate_claims(payload["claims"], evidence_set, evidence_by_id=evidence_by_id, known_claim_ids=known_claim_ids, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled))
    if narrative and result_checks_enabled:
        issues.extend(_narrative_claim_issues(payload["claims"], known_claim_ids or set(), evidence_by_id, source_verification_enabled=source_verification_enabled))
        local_ids = {row["claim_id"] for row in payload["claims"]}
        units = [row["source_unit_id"] for row in payload["coverage"]]
        if _duplicates(units) or _duplicates(payload["considered_claim_ids"]):
            issues.append(_issue("duplicate_coverage", "narrative coverage identities must be unique"))
        for row in payload["coverage"]:
            if not row["claim_ids"] or not set(row["claim_ids"]) <= local_ids or (row["status"] == "needs_review" and not _text(row["reason"])):
                issues.append(_issue("invalid_coverage", "coverage requires local claims and an explicit reason when not reviewed"))
    return _strict(payload, "deep-review-stage", issues)


def _narrative_claim_issues(claims: Sequence[Mapping[str, Any]], known: set[str], evidence: Mapping[str, Mapping[str, Any]], *, source_verification_enabled: bool = True) -> list[ValidationIssue]:
    issues = []
    local = {row["claim_id"] for row in claims}
    for row in claims:
        if source_verification_enabled and row["claim_type"] == "fact":
            quotes = [str(evidence.get(eid, {}).get("quote", "")) for eid in row["evidence_ids"]]
            if not _fact_numeric_status(row["body"], quotes)[0]:
                issues.append(_issue("fact_number_not_in_evidence", "fact numbers must be present in the cited source", claims=[row["claim_id"]], evidence=row["evidence_ids"]))
        related = row["related_claim_ids"]
        if _duplicates(related) or row["claim_id"] in related or not set(related) <= (known | local):
            issues.append(_issue("narrative_relation_invalid", "narrative relationship does not resolve", claims=[row["claim_id"]]))
        if any(_duplicates(row[key]) for key in ("source_unit_ids", "requirement_ids")):
            issues.append(_issue("narrative_source_duplicate", "source identities must be unique", claims=[row["claim_id"]]))
        if row["narrative_role"] == "impact" and row["claim_type"] not in {"inference", "unknown"}:
            issues.append(_issue("impact_type_invalid", "impact must distinguish inference and unknown", claims=[row["claim_id"]]))
        if row["narrative_role"] == "recommendation" and (row["category"] != "system_recommendation" or row["report_section"] != "assessment" or row["body"] not in {"추진 검토", "조건부 추진 검토", "보류", "검토 종료"}):
            issues.append(_issue("recommendation_shape_invalid", "recommendation must use the bounded review enum", claims=[row["claim_id"]]))
    return issues


def _report_block_claim_ids(report: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for section in report.get("sections", []):
        for block in section.get("blocks", []):
            ids.update(block.get("claim_ids", []))
            for row in block.get("rows", []):
                ids.update(row.get("claim_ids", []))
    return ids


def _validate_report_block_ids(report: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    block_ids: dict[str, str] = {}
    row_ids: dict[str, str] = {}
    for section_index, section in enumerate(report.get("sections", [])):
        section_key = section.get("section_key", section_index)
        for block_index, block in enumerate(section.get("blocks", [])):
            block_id = block.get("block_id")
            block_path = f"$.sections[{section_index}].blocks[{block_index}]"
            if block_id in block_ids:
                issues.append(_issue("duplicate_report_block_id", f"report block_id must be globally unique: {block_id}", block_path))
            else:
                block_ids[block_id] = str(section_key)
            if _text(block.get("body")) and not block.get("claim_ids"):
                issues.append(_issue("report_body_claims_required", "factual report body must carry claim IDs", f"{block_path}.body"))
            for row_index, row in enumerate(block.get("rows", [])):
                row_key = row.get("row_key")
                row_path = f"{block_path}.rows[{row_index}]"
                if row_key in row_ids:
                    issues.append(_issue("duplicate_report_row_id", f"report row_key must be globally unique: {row_key}", row_path))
                else:
                    row_ids[row_key] = str(block_id)
                if row.get("cells") and not row.get("claim_ids"):
                    issues.append(_issue("report_cells_claims_required", "factual report cells must carry claim IDs", f"{row_path}.cells"))
    return issues


def validate_deep_review_report(
    payload: Mapping[str, Any],
    *,
    bundle: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    stages: Sequence[Mapping[str, Any]] | None = None,
    expected_deep_review_id: str | None = None,
    structures: Mapping[str, Mapping[str, Any]] | None = None,
    source_verification_enabled: bool = True,
    result_checks_enabled: bool = True,
) -> dict[str, Any]:
    """Validate a full report, mandatory sections, and cross-payload scope."""

    narrative = payload.get("schema") == "bidops.deep-review-report.v2"
    issues = _schema_issues(payload, "deep-review-report-v2" if narrative else "deep-review-report")
    if issues:
        raise DeepReviewValidationError(issues)
    if expected_deep_review_id and payload["deep_review_id"] != expected_deep_review_id:
        issues.append(_issue("review_scope", "report deep_review_id does not match the current review", "$.deep_review_id"))
    sections = payload["sections"]
    keys = [section["section_key"] for section in sections]
    if _duplicates(keys):
        issues.append(_issue("duplicate_report_section", "report section keys must be unique", "$.sections"))
    required_sections = NARRATIVE_SECTIONS if narrative else REQUIRED_SECTIONS
    if set(keys) != set(required_sections) or len(keys) != len(required_sections):
        issues.append(_issue("report_sections_incomplete", "report must contain exactly one of every required section", "$.sections"))
    decision_blocks = [block for section in sections if section["section_key"] == "decision_card" for block in section["blocks"] if block["type"] == "decision_card"]
    if not narrative and not decision_blocks:
        issues.append(_issue("decision_card_missing", "decision_card section must contain a decision_card block", "$.sections"))
    elif not narrative and not any(block["claim_ids"] and (_text(block.get("body")) or block["rows"]) for block in decision_blocks):
        issues.append(_issue("decision_card_unlinked", "decision card must summarize linked core evidence, risks, unknowns, and next actions", "$.sections"))
    issues.extend(_validate_report_block_ids(payload))
    claims = payload["claims"]
    claim_ids = {claim["claim_id"] for claim in claims}
    evidence_list = list(evidence or [])
    evidence_ids = {item.get("evidence_id") for item in evidence_list if isinstance(item, Mapping)}
    if stages:
        stage_claim_ids = {claim.get("claim_id") for stage in stages for claim in stage.get("claims", [])}
        if stage_claim_ids and stage_claim_ids != claim_ids:
            issues.append(_issue("report_stage_claim_mismatch", "report claims must be the deterministic union of stage claims", "$.claims"))
        evidence_ids.update(item.get("evidence_id") for stage in stages for item in stage.get("evidence", []))
    evidence_by_id = {
        item["evidence_id"]: item
        for item in evidence_list
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str)
    }
    issues.extend(_validate_claims(claims, {value for value in evidence_ids if isinstance(value, str)}, evidence_by_id=evidence_by_id, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled))
    block_claim_ids = _report_block_claim_ids(payload)
    if narrative:
        if result_checks_enabled:
            issues.extend(_narrative_claim_issues(claims, set(), evidence_by_id, source_verification_enabled=source_verification_enabled))
        by_id = {row["claim_id"]: row for row in claims}
        displayed = []
        for section in sections:
            if section["status"] != ("available" if section["blocks"] else "not_analyzed"):
                issues.append(_issue("section_status_invalid", "empty sections must remain not analyzed"))
            for block in section["blocks"]:
                displayed.extend(block["claim_ids"])
                claim = by_id.get(block["claim_ids"][0]) if len(block["claim_ids"]) == 1 else None
                if claim is None:
                    issues.append(_issue("narrative_block_link_invalid", "each narrative paragraph must resolve to one claim"))
                    continue
                if (block["body"] != claim["body"] or section["section_key"] != claim["report_section"] or any(block[key] != claim[key] for key in ("narrative_role", "topic_key", "is_key_point")) or block["rows"]):
                    issues.append(_issue("narrative_projection_mismatch", "paragraph must preserve its claim and explicit role", claims=[claim["claim_id"]]))
        if set(displayed) != claim_ids or _duplicates(displayed):
            issues.append(_issue("narrative_claim_omission", "every claim must appear exactly once in the report"))
        if result_checks_enabled:
            units = {unit for row in claims for unit in row["source_unit_ids"]}
            coverage_units = [row["source_unit_id"] for row in payload["coverage"]]
            if set(coverage_units) != units or _duplicates(coverage_units):
                issues.append(_issue("report_source_coverage_mismatch", "report coverage must preserve every analyzed source unit"))
            for row in payload["coverage"]:
                if (not row["claim_ids"] or _duplicates(row["claim_ids"])
                        or any(cid not in by_id or row["source_unit_id"] not in by_id[cid]["source_unit_ids"] for cid in row["claim_ids"])
                        or (row["status"] == "needs_review" and not _text(row["reason"]))):
                    issues.append(_issue("report_source_coverage_invalid", "source coverage must resolve to its claims and retain review limitations"))
    unknown_block_ids = sorted(block_claim_ids - claim_ids)
    if unknown_block_ids:
        issues.append(_issue("dangling_report_claim", f"report block references unknown claim IDs: {unknown_block_ids}", "$.sections"))
    if evidence_list:
        resolved_profile, _ = _context_profile(profile, payload["profile_version_id"])
        for index, item in enumerate(evidence_list):
            issues.extend(_validate_evidence(item, index, bundle=bundle, profile=profile, profile_version_id=resolved_profile or payload["profile_version_id"], structures=structures, allow_page_span=payload.get("schema") == "bidops.deep-review-report.v2", source_verification_enabled=source_verification_enabled))
    if isinstance(bundle, Mapping):
        if bundle.get("bundle_id") and bundle["bundle_id"] != payload["bundle_id"]:
            issues.append(_issue("bundle_scope", "report bundle_id does not match the ready bundle", "$.bundle_id"))
    if isinstance(profile, Mapping):
        profile_id = profile.get("profile_version_id") or profile.get("id")
        if profile_id and profile_id != payload["profile_version_id"]:
            issues.append(_issue("profile_scope", "report profile_version_id does not match the pinned profile", "$.profile_version_id"))
    return _strict(payload, "deep-review-report", issues)


def validate_deep_review_validation(
    payload: Mapping[str, Any],
    *,
    expected_report_revision_id: str | None = None,
    expected_deep_review_id: str | None = None,
    claim_ids: Iterable[str] | None = None,
    evidence_ids: Iterable[str] | None = None,
    related_id_scopes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate append-only validation checks and same-review related IDs."""

    issues = _schema_issues(payload, "deep-review-validation")
    if issues:
        raise DeepReviewValidationError(issues)
    if expected_report_revision_id and payload["report_revision_id"] != expected_report_revision_id:
        issues.append(_issue("revision_scope", "validation report_revision_id does not match the revision", "$.report_revision_id"))
    claim_scope_supplied = claim_ids is not None
    evidence_scope_supplied = evidence_ids is not None
    claim_set = set(claim_ids or ())
    evidence_set = set(evidence_ids or ())
    seen_checks: set[tuple[str, str, str]] = set()
    failed_count = 0
    for index, check in enumerate(payload["checks"]):
        path = f"$.checks[{index}]"
        key = (check["check_type"], check["status"], check["message"])
        if key in seen_checks:
            issues.append(_issue("duplicate_validation_check", "validation checks must be deterministic and unique", path))
        seen_checks.add(key)
        if check["status"] == "failed":
            failed_count += 1
        if duplicates := _duplicates(check["related_claim_ids"]):
            issues.append(_issue("duplicate_related_claim", f"related claim IDs must be unique: {duplicates}", f"{path}.related_claim_ids"))
        if duplicates := _duplicates(check["related_evidence_ids"]):
            issues.append(_issue("duplicate_related_evidence", f"related evidence IDs must be unique: {duplicates}", f"{path}.related_evidence_ids"))
        for related in check["related_claim_ids"]:
            if not claim_scope_supplied and related_id_scopes is None:
                issues.append(_issue("validation_claim_context_missing", "claim membership context is required when related claim IDs are present", path, claims=[related]))
            elif claim_scope_supplied and related not in claim_set:
                issues.append(_issue("validation_claim_scope", f"related claim ID does not belong to this review: {related}", path, claims=[related]))
            if related_id_scopes is not None:
                scope = related_id_scopes.get(related)
                if not isinstance(scope, Mapping):
                    issues.append(_issue("validation_claim_scope", f"related claim ID is absent from membership context: {related}", path, claims=[related]))
                elif expected_deep_review_id and scope.get("deep_review_id") != expected_deep_review_id:
                    issues.append(_issue("validation_claim_scope", f"related claim ID belongs to another review: {related}", path, claims=[related]))
        for related in check["related_evidence_ids"]:
            if not evidence_scope_supplied and related_id_scopes is None:
                issues.append(_issue("validation_evidence_context_missing", "evidence membership context is required when related evidence IDs are present", path, evidence=[related]))
            elif evidence_scope_supplied and related not in evidence_set:
                issues.append(_issue("validation_evidence_scope", f"related evidence ID does not belong to this review: {related}", path, evidence=[related]))
            if related_id_scopes is not None:
                scope = related_id_scopes.get(related)
                if not isinstance(scope, Mapping):
                    issues.append(_issue("validation_evidence_scope", f"related evidence ID is absent from membership context: {related}", path, evidence=[related]))
                elif expected_deep_review_id and scope.get("deep_review_id") != expected_deep_review_id:
                    issues.append(_issue("validation_evidence_scope", f"related evidence ID belongs to another review: {related}", path, evidence=[related]))
    if payload["status"] == "passed" and failed_count:
        issues.append(_issue("validation_status_mismatch", "passed validation cannot contain failed checks", "$.status"))
    if payload["status"] == "failed" and not failed_count:
        issues.append(_issue("validation_status_mismatch", "failed validation must contain at least one failed check", "$.status"))
    return _strict(payload, "deep-review-validation", issues)


def validate_final_opinion_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate final-opinion acknowledgement without introducing a sixth schema."""

    required = {"report_revision_id", "validation_run_id", "value", "reason", "acknowledged_validation_failure", "validation_status_at_opinion", "claimed_name", "created_at"}
    issues: list[ValidationIssue] = []
    if set(payload) != required:
        issues.append(_issue("final_opinion_fields", "final opinion snapshot fields are not exact", "$"))
    else:
        if not _uuid(payload["report_revision_id"]) or not _uuid(payload["validation_run_id"]):
            issues.append(_issue("final_opinion_id", "final opinion IDs must be canonical UUIDs", "$"))
        if payload["value"] not in {"추진", "조건부 추진", "보류", "검토 종료"}:
            issues.append(_issue("final_opinion_enum", "final opinion value is not allowed", "$.value"))
        failed = payload["validation_status_at_opinion"] == "failed"
        if payload["validation_status_at_opinion"] not in {"passed", "failed"}:
            issues.append(_issue("final_opinion_validation_status", "validation status is not allowed", "$.validation_status_at_opinion"))
        if not _text(payload["reason"]):
            issues.append(_issue("final_opinion_reason_required", "final opinion reason is required", "$.reason"))
        if failed and (payload["acknowledged_validation_failure"] is not True or not _text(payload["reason"])):
            issues.append(_issue("final_opinion_ack_required", "failed validation requires explicit acknowledgement and reason", "$"))
        if not failed and payload["acknowledged_validation_failure"] is not False:
            issues.append(_issue("final_opinion_ack_shape", "passed validation cannot carry a failure acknowledgement", "$"))
        if not _text(payload["claimed_name"]) or len(payload["claimed_name"].strip()) > 128 or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in payload["claimed_name"]):
            issues.append(_issue("final_opinion_claimed_name", "claimed_name must be a clean non-empty name of at most 128 characters", "$.claimed_name"))
        if not _timestamp(payload["created_at"]):
            issues.append(_issue("final_opinion_timestamp", "created_at must include a timezone", "$.created_at"))
    return _strict(payload, "final-opinion", issues)


@dataclass(frozen=True)
class RequirementInventory:
    expected_count: int
    observed_count: int
    unique_observed_count: int
    missing_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    unexpected_ids: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not (self.missing_ids or self.duplicate_ids or self.unexpected_ids)

    def as_dict(self) -> dict[str, Any]:
        return {"expected_count": self.expected_count, "observed_count": self.observed_count, "unique_observed_count": self.unique_observed_count, "missing_ids": list(self.missing_ids), "duplicate_ids": list(self.duplicate_ids), "unexpected_ids": list(self.unexpected_ids), "valid": self.valid}


def compare_requirement_ids(expected_ids: Iterable[str], observed_ids: Iterable[str]) -> RequirementInventory:
    """Compare requirement IDs without trusting model-reported counts."""

    expected = [str(item) for item in expected_ids]
    observed = [str(item) for item in observed_ids]
    expected_set, observed_set = set(expected), set(observed)
    duplicates = tuple(str(item) for item in _duplicates(observed))
    return RequirementInventory(len(expected_set), len(observed), len(observed_set), tuple(sorted(expected_set - observed_set)), duplicates, tuple(sorted(observed_set - expected_set)))


validate_requirement_inventory = compare_requirement_ids
compare_pilot_requirements = compare_requirement_ids


REQUIREMENT_INVENTORY_CHECK = "requirement_inventory"
SEGMENT_COVERAGE_CHECK = "segment_coverage"


def validate_document_segments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """결정적 segment manifest wire payload를 계약대로 검사한다.

    이 계약에는 원문 text가 없다. segment 순서(``ordinal``)와 ``segment_id``의
    유일성, 그리고 사람 검토가 필요한 segment가 확신도를 만들어 내지 않는다는
    것만 추가로 확인한다.
    """

    issues = _schema_issues(payload, "document-segments")
    if issues:
        raise DeepReviewValidationError(issues)
    segments = payload["segments"]
    if duplicates := _duplicates([str(item["segment_id"]) for item in segments]):
        issues.append(_issue("duplicate_segment_id", f"segment IDs must be unique: {duplicates}", "$.segments"))
    if [int(item["ordinal"]) for item in segments] != list(range(1, len(segments) + 1)):
        issues.append(_issue("segment_ordinal_gap", "segment ordinals must be 1..n without gaps", "$.segments"))
    binding = payload["extractor_binding"]
    if payload["taxonomy_version"] != binding["taxonomy_version"]:
        issues.append(_issue(
            "segment_taxonomy_binding",
            "taxonomy_version must match extractor_binding.taxonomy_version",
            "$.taxonomy_version",
        ))
    for index, segment in enumerate(segments):
        path = f"$.segments[{index}]"
        if segment["status"] == "needs_human_review" and segment["confidence"] is not None:
            issues.append(_issue("segment_review_confidence", "needs_human_review segments must not carry a confidence", path))
        if segment["status"] == "classified" and not segment["taxonomy_labels"]:
            issues.append(_issue("segment_label_missing", "classified segments must carry at least one taxonomy label", path))
        mapping_status = segment["mapping_status"]
        page_range = segment["page_range"]
        if mapping_status == "unavailable" and page_range is not None:
            issues.append(_issue(
                "segment_page_unavailable",
                "unavailable segments must not carry a page_range",
                path,
            ))
        if mapping_status != "unavailable" and page_range is None:
            issues.append(_issue(
                "segment_page_missing",
                "mapped, partial, and inherited segments must carry a page_range",
                path,
            ))
        if mapping_status == "inherited" and page_range is not None and page_range["first"] != page_range["last"]:
            issues.append(_issue(
                "segment_inherited_page_range",
                "inherited page ranges must identify one page",
                path,
            ))
    summary = payload["inventory_summary"]
    if summary["card_item_count"] > summary["item_count"]:
        issues.append(_issue(
            "segment_card_item_count",
            "card_item_count cannot exceed item_count",
            "$.inventory_summary.card_item_count",
        ))
    if summary["label_value_table_count"] > summary["card_item_count"]:
        issues.append(_issue(
            "segment_card_table_count",
            "label_value_table_count cannot exceed card_item_count",
            "$.inventory_summary.label_value_table_count",
        ))
    return _strict(payload, "document-segments", issues)


def build_segment_checks(
    inventory: Mapping[str, Any],
    observed_requirement_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """심층 검토 검증에 더하는 두 check를 결정적으로 만든다.

    ``requirement_inventory``는 stage 1 claim이 보고한 requirement ID 집합과
    묶음의 모든 문서 inventory 합집합을 :func:`compare_requirement_ids`로 비교한다.
    inventory가 비어 있으면(문서에 ID 체계가 없음) 실패로 만들지 않고 경고로 남긴다.

    ``segment_coverage``는 사람 검토가 필요한 segment나 빈 구간·겹침을 경고로만
    드러낸다. 어느 쪽도 자동으로 보정하지 않는다.
    """

    expected = [str(value) for value in inventory.get("expected_ids", []) or []]
    checks: list[dict[str, Any]] = []
    if not expected:
        checks.append({
            "check_type": REQUIREMENT_INVENTORY_CHECK, "status": "warning", "severity": "보통",
            "message": "문서에 요구사항 ID 체계가 없어 inventory 대조를 하지 못했습니다",
            "related_claim_ids": [], "related_evidence_ids": [],
        })
    else:
        result = compare_requirement_ids(expected, observed_requirement_ids)
        if result.missing_ids or result.unexpected_ids:
            checks.append({
                "check_type": REQUIREMENT_INVENTORY_CHECK, "status": "failed", "severity": "중대",
                "message": (
                    "stage 1 claim의 요구사항 ID가 문서 inventory와 다릅니다 "
                    f"(누락 {len(result.missing_ids)}건, 예상 밖 {len(result.unexpected_ids)}건)"
                ),
                "related_claim_ids": [], "related_evidence_ids": [],
            })
        elif result.duplicate_ids:
            checks.append({
                "check_type": REQUIREMENT_INVENTORY_CHECK, "status": "warning", "severity": "보통",
                "message": f"stage 1 claim이 같은 요구사항 ID를 {len(result.duplicate_ids)}건 중복 보고했습니다",
                "related_claim_ids": [], "related_evidence_ids": [],
            })
        else:
            checks.append({
                "check_type": REQUIREMENT_INVENTORY_CHECK, "status": "passed", "severity": "낮음",
                "message": f"요구사항 ID {result.expected_count}건을 문서 inventory와 대조했습니다",
                "related_claim_ids": [], "related_evidence_ids": [],
            })

    if not int(inventory.get("manifest_count", 0) or 0):
        return checks
    needs_review = int(inventory.get("needs_human_review_count", 0) or 0)
    gaps = int(inventory.get("gap_count", 0) or 0)
    overlaps = int(inventory.get("overlap_count", 0) or 0)
    if needs_review or gaps or overlaps:
        checks.append({
            "check_type": SEGMENT_COVERAGE_CHECK, "status": "warning", "severity": "보통",
            "message": (
                "segment manifest에 사람 검토가 필요한 구간이 있습니다 "
                f"(미분류 {needs_review}건, 빈 구간 {gaps}건, 겹침 {overlaps}건)"
            ),
            "related_claim_ids": [], "related_evidence_ids": [],
        })
    else:
        checks.append({
            "check_type": SEGMENT_COVERAGE_CHECK, "status": "passed", "severity": "낮음",
            "message": "segment manifest가 문서 전체를 빈 구간·겹침 없이 덮습니다",
            "related_claim_ids": [], "related_evidence_ids": [],
        })
    return checks


def merge_stage_chunks(
    chunks: Sequence[Mapping[str, Any]],
    *,
    expected_claim_ids: Iterable[str] = (),
    expected_evidence_ids: Iterable[str] = (),
    bundle: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    profile_version_id: str | None = None,
    expected_deep_review_id: str | None = None,
    known_claim_ids: Iterable[str] = (),
    known_evidence_ids: Iterable[str] = (),
    known_evidence: Sequence[Mapping[str, Any]] = (),
    structures: Mapping[str, Mapping[str, Any]] | None = None,
    chunk_order_key: Any = None,
    order_key: Any = None,
    source_verification_enabled: bool = True,
    result_checks_enabled: bool = True,
) -> dict[str, Any]:
    """Merge bounded stage outputs deterministically and reject conflicts.

    Repeated IDs are rejected even when their payloads are identical; different
    payloads are reported as conflicts.  Expected IDs missing after the merge
    are hard failures.  Output order is sorted by canonical UUID/string.
    """

    if not chunks:
        raise DeepReviewValidationError("at least one stage chunk is required")
    def approved_order(chunk: Mapping[str, Any], index: int) -> Any:
        selected_order_key = chunk_order_key if chunk_order_key is not None else order_key
        if callable(selected_order_key):
            return selected_order_key(chunk)
        if isinstance(selected_order_key, Mapping):
            value = selected_order_key.get(id(chunk))
            if value is not None:
                return value
        if isinstance(selected_order_key, Sequence) and not isinstance(selected_order_key, (str, bytes, bytearray)) and index < len(selected_order_key):
            return selected_order_key[index]
        explicit = chunk.get("chunk_order") or chunk.get("chunk_order_key") or chunk.get("order_key") or chunk.get("merge_key")
        if isinstance(explicit, (list, tuple)):
            return tuple(explicit)
        requirements = chunk.get("requirements")
        first_requirement = requirements[0] if isinstance(requirements, list) and requirements and isinstance(requirements[0], Mapping) else {}
        return (
            chunk.get("stage_sequence", 0), first_requirement.get("document_ordinal", 0),
            first_requirement.get("page", 0), first_requirement.get("block_order", 0),
            first_requirement.get("requirement_id", ""), chunk.get("slice_index", index),
        )

    ordered_chunks = [
        chunk
        for _order, _index, chunk in sorted(
            ((approved_order(chunk, index), index, chunk) for index, chunk in enumerate(chunks)),
            key=lambda item: (item[0], item[1]),
        )
    ]
    first = ordered_chunks[0]
    prior_claim_ids = {str(value) for value in known_claim_ids}
    prior_evidence_ids = {str(value) for value in known_evidence_ids}
    review_id = expected_deep_review_id or first.get("deep_review_id")
    all_claim_ids = {item.get("claim_id") for chunk in ordered_chunks for item in chunk.get("claims", []) if isinstance(item, Mapping)}
    all_evidence_ids = {item.get("evidence_id") for chunk in ordered_chunks for item in chunk.get("evidence", []) if isinstance(item, Mapping)}
    for index, chunk in enumerate(ordered_chunks):
        validate_deep_review_stage(
            chunk,
            bundle=bundle,
            profile=profile,
            profile_version_id=profile_version_id,
            expected_deep_review_id=review_id,
            known_claim_ids=prior_claim_ids | {value for value in all_claim_ids if isinstance(value, str)},
            known_evidence_ids=prior_evidence_ids | {value for value in all_evidence_ids if isinstance(value, str)},
            known_evidence=[*known_evidence, *(row for item in ordered_chunks for row in item.get("evidence", []))],
            structures=structures, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled,
        )
        if chunk.get("schema") != first.get("schema") or chunk.get("attempt_id") != first.get("attempt_id") or chunk.get("stage") != first.get("stage"):
            raise DeepReviewValidationError(_issue("chunk_scope", "all chunks must belong to the same attempt and stage", f"$[{index}]"))
    claims: dict[str, Mapping[str, Any]] = {}
    evidence: dict[str, Mapping[str, Any]] = {}
    unknowns: set[str] = set()
    warnings: set[str] = set()
    for chunk_index, chunk in enumerate(ordered_chunks):
        for item in (chunk["claims"] if first["schema"] == "bidops.deep-review-stage.v2" else sorted(chunk["claims"], key=lambda value: value["claim_id"])):
            key = item["claim_id"]
            if key in prior_claim_ids:
                raise DeepReviewValidationError(_issue("prior_claim_redefinition", f"current stage cannot redefine prior claim ID: {key}", f"$[{chunk_index}].claims", claims=[key]))
            if key in claims:
                code = "chunk_conflict" if _canonical(claims[key]) != _canonical(item) else "chunk_duplicate"
                raise DeepReviewValidationError(_issue(code, f"claim ID appears in multiple chunks: {key}", f"$[{chunk_index}].claims", claims=[key]))
            claims[key] = item
        for item in sorted(chunk["evidence"], key=lambda value: value["evidence_id"]):
            key = item["evidence_id"]
            if key in prior_evidence_ids:
                raise DeepReviewValidationError(_issue("prior_evidence_redefinition", f"current stage cannot redefine prior evidence ID: {key}", f"$[{chunk_index}].evidence", evidence=[key]))
            if key in evidence:
                code = "chunk_conflict" if _canonical(evidence[key]) != _canonical(item) else "chunk_duplicate"
                raise DeepReviewValidationError(_issue(code, f"evidence ID appears in multiple chunks: {key}", f"$[{chunk_index}].evidence", evidence=[key]))
            evidence[key] = item
        unknowns.update(chunk["unknowns"])
        warnings.update(chunk["warnings"])
    expected_claim_set, expected_evidence_set = set(expected_claim_ids), set(expected_evidence_ids)
    missing_claims = sorted(expected_claim_set - claims.keys())
    missing_evidence = sorted(expected_evidence_set - evidence.keys())
    issues: list[ValidationIssue] = []
    if missing_claims:
        issues.append(_issue("chunk_missing_claim", f"required claims were not produced: {missing_claims}", "$.claims", claims=missing_claims))
    if missing_evidence:
        issues.append(_issue("chunk_missing_evidence", f"required evidence was not produced: {missing_evidence}", "$.evidence", evidence=missing_evidence))
    if issues:
        raise DeepReviewValidationError(issues)
    # Dict insertion order is the approved chunk order, and each chunk's
    # source order is retained.  This makes output stable under shuffled
    # invocation completion while keeping the merge key observable.
    merged = {"schema": first["schema"], "deep_review_id": first["deep_review_id"], "attempt_id": first["attempt_id"], "stage": first["stage"], "claims": list(claims.values()), "evidence": list(evidence.values()), "unknowns": sorted(unknowns), "warnings": sorted(warnings)}
    if first["schema"] == "bidops.deep-review-stage.v2":
        coverage = {}
        for chunk in ordered_chunks:
            for row in chunk["coverage"]:
                target = coverage.setdefault(row["source_unit_id"], {**row, "claim_ids": []})
                target["claim_ids"].extend(row["claim_ids"])
                if row["status"] == "needs_review":
                    target["status"] = "needs_review"
                    target["reason"] = "; ".join(dict.fromkeys(filter(None, [target["reason"], row["reason"]])))
        merged["coverage"] = list(coverage.values())
        merged["considered_claim_ids"] = list(dict.fromkeys(cid for chunk in ordered_chunks for cid in chunk["considered_claim_ids"]))
    return validate_deep_review_stage(
        merged,
        bundle=bundle,
        profile=profile,
        profile_version_id=profile_version_id,
        expected_deep_review_id=review_id,
        known_claim_ids=prior_claim_ids,
        known_evidence_ids=prior_evidence_ids,
        known_evidence=known_evidence,
        structures=structures, source_verification_enabled=source_verification_enabled, result_checks_enabled=result_checks_enabled,
    )


deterministic_chunk_merge = merge_stage_chunks
merge_chunks = merge_stage_chunks
replay_formula = replay_calculation
validate_structure = validate_document_structure
validate_bundle = validate_document_bundle
validate_stage_payload = validate_deep_review_stage
validate_report_payload = validate_deep_review_report
validate_validation_payload = validate_deep_review_validation


def validate_deep_review(payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Dispatch the strict validator by the authoritative ``schema`` field."""

    schema = payload.get("schema") if isinstance(payload, Mapping) else None
    dispatch = {
        "bidops.document-structure.v1": validate_document_structure,
        "bidops.document-bundle.v1": validate_document_bundle,
        "bidops.deep-review-stage.v1": validate_deep_review_stage,
        "bidops.deep-review-stage.v2": validate_deep_review_stage,
        "bidops.deep-review-report.v1": validate_deep_review_report,
        "bidops.deep-review-report.v2": validate_deep_review_report,
        "bidops.deep-review-validation.v1": validate_deep_review_validation,
        "bidops.document-segments.v1": validate_document_segments,
    }
    if schema not in dispatch:
        raise DeepReviewValidationError(_issue("unknown_schema", f"unsupported deep-review schema: {schema!r}"))
    return dispatch[schema](payload, **kwargs)


__all__ = [
    "ContractValidationError", "DeepReviewValidationError", "RequirementInventory", "ValidationIssue", "ValidationResult",
    "REQUIREMENT_INVENTORY_CHECK", "SEGMENT_COVERAGE_CHECK", "build_segment_checks",
    "compare_pilot_requirements", "compare_requirement_ids", "deterministic_chunk_merge", "merge_stage_chunks",
    "merge_chunks", "replay_calculation", "replay_formula", "validate_bundle", "validate_deep_review", "validate_deep_review_report", "validate_deep_review_stage",
    "validate_deep_review_validation", "validate_document_bundle", "validate_document_segments", "validate_document_structure",
    "validate_final_opinion_snapshot", "validate_report_payload", "validate_stage_payload", "validate_structure", "validate_validation_payload", "validate_requirement_inventory",
]
