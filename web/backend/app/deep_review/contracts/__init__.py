"""Authoritative JSON contracts for deep review payloads.

The JSON files in this package are the wire contract.  ``validate_payload``
adds the small amount of JSON-Schema validation needed by callers that do not
install a third-party schema package; domain checks live in
``app.deep_review.services.deep_review_validation``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ._validator import SchemaError, SchemaValidationError, validate_json_schema

CONTRACT_DIR = Path(__file__).parent
SCHEMA_FILES = {
    "document-structure": "bidops.document-structure.v1.json",
    "document-bundle": "bidops.document-bundle.v1.json",
    "deep-review-stage": "bidops.deep-review-stage.v1.json",
    "deep-review-stage-v2": "bidops.deep-review-stage.v2.json",
    "deep-review-report": "bidops.deep-review-report.v1.json",
    "deep-review-report-v2": "bidops.deep-review-report.v2.json",
    "deep-review-validation": "bidops.deep-review-validation.v1.json",
    "document-segments": "bidops.document-segments.v1.json",
    # RL-03 card-v1 (spec "인터페이스"): frozen input and the three Luna stage
    # outputs.  runner ``CONTRACT_SCHEMA_PATHS`` maps the same three files.
    "card-analysis-input": "bidops.card-analysis-input.v1.json",
    "requirement-extract": "bidops.requirement-extract.v1.json",
    # 결정 B33: model output of policy v4 (no concept_candidates/operator;
    # kind x unit branches).  Code assembles the v1 object from it.
    "requirement-extract-v2": "bidops.requirement-extract.v2.json",
    "verdict-role": "bidops.verdict-role.v1.json",
    # 결정 C16 (RL-05): policy v10 role output -- short evidence ids, never triples.
    "verdict-role-v2": "bidops.verdict-role.v2.json",
    "practitioner-verdict": "bidops.practitioner-verdict.v1.json",
    # 결정 B55: policy v9 synthesis output (no blocking_condition_ids; code computes them).
    "practitioner-verdict-v2": "bidops.practitioner-verdict.v2.json",
    # RL-04 (spec "문장 계약"·"생성 입력"): Luna section output (runner
    # ``proposal-section-v1``) and the frozen per-section input.  Kind-conditional
    # sentence rules live in ``services/proposal_validation.py``, not here.
    "proposal-section": "bidops.proposal-section.v1.json",
    "proposal-input": "bidops.proposal-input.v1.json",
}

DOCUMENT_STRUCTURE_SCHEMA = "document-structure"
DOCUMENT_BUNDLE_SCHEMA = "document-bundle"
DEEP_REVIEW_STAGE_SCHEMA = "deep-review-stage"
DEEP_REVIEW_REPORT_SCHEMA = "deep-review-report"
DEEP_REVIEW_VALIDATION_SCHEMA = "deep-review-validation"
DOCUMENT_SEGMENTS_SCHEMA = "document-segments"
CARD_ANALYSIS_INPUT_SCHEMA = "card-analysis-input"
REQUIREMENT_EXTRACT_SCHEMA = "requirement-extract"
REQUIREMENT_EXTRACT_V2_SCHEMA = "requirement-extract-v2"
VERDICT_ROLE_SCHEMA = "verdict-role"
VERDICT_ROLE_V2_SCHEMA = "verdict-role-v2"
PRACTITIONER_VERDICT_SCHEMA = "practitioner-verdict"
PRACTITIONER_VERDICT_V2_SCHEMA = "practitioner-verdict-v2"
PROPOSAL_SECTION_SCHEMA = "proposal-section"
PROPOSAL_INPUT_SCHEMA = "proposal-input"
SCHEMAS = {key: value for key, value in SCHEMA_FILES.items()}


def schema_path(name: str) -> Path:
    """Return a contract path by short name or exact filename."""

    filename = SCHEMA_FILES.get(name, name)
    path = CONTRACT_DIR / filename
    if path.suffix != ".json" or not path.is_file():
        raise KeyError(f"unknown deep-review schema: {name}")
    return path


def load_schema(name: str) -> dict[str, Any]:
    """Load one of the immutable contract schemas."""

    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def validate_payload(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Validate a payload against its closed JSON Schema and return it.

    A shallow copy is returned so callers can safely keep the original model
    untouched.  Cross-document/domain validation is deliberately separate.
    """

    if not isinstance(payload, Mapping):
        raise SchemaValidationError("$ must be an object")
    validate_json_schema(payload, load_schema(name))
    return dict(payload)


__all__ = [
    "CARD_ANALYSIS_INPUT_SCHEMA",
    "CONTRACT_DIR",
    "DEEP_REVIEW_REPORT_SCHEMA",
    "DEEP_REVIEW_STAGE_SCHEMA",
    "DEEP_REVIEW_VALIDATION_SCHEMA",
    "DOCUMENT_BUNDLE_SCHEMA",
    "DOCUMENT_SEGMENTS_SCHEMA",
    "DOCUMENT_STRUCTURE_SCHEMA",
    "PRACTITIONER_VERDICT_SCHEMA",
    "PRACTITIONER_VERDICT_V2_SCHEMA",
    "PROPOSAL_INPUT_SCHEMA",
    "PROPOSAL_SECTION_SCHEMA",
    "REQUIREMENT_EXTRACT_SCHEMA",
    "REQUIREMENT_EXTRACT_V2_SCHEMA",
    "SCHEMAS",
    "SCHEMA_FILES",
    "SchemaError",
    "SchemaValidationError",
    "VERDICT_ROLE_SCHEMA",
    "VERDICT_ROLE_V2_SCHEMA",
    "load_schema",
    "schema_path",
    "validate_json_schema",
    "validate_payload",
]
