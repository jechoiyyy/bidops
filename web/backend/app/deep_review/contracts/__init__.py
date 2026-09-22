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
}

DOCUMENT_STRUCTURE_SCHEMA = "document-structure"
DOCUMENT_BUNDLE_SCHEMA = "document-bundle"
DEEP_REVIEW_STAGE_SCHEMA = "deep-review-stage"
DEEP_REVIEW_REPORT_SCHEMA = "deep-review-report"
DEEP_REVIEW_VALIDATION_SCHEMA = "deep-review-validation"
DOCUMENT_SEGMENTS_SCHEMA = "document-segments"
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
    "CONTRACT_DIR",
    "DEEP_REVIEW_REPORT_SCHEMA",
    "DEEP_REVIEW_STAGE_SCHEMA",
    "DEEP_REVIEW_VALIDATION_SCHEMA",
    "DOCUMENT_BUNDLE_SCHEMA",
    "DOCUMENT_SEGMENTS_SCHEMA",
    "DOCUMENT_STRUCTURE_SCHEMA",
    "SCHEMAS",
    "SCHEMA_FILES",
    "SchemaError",
    "SchemaValidationError",
    "load_schema",
    "schema_path",
    "validate_json_schema",
    "validate_payload",
]
