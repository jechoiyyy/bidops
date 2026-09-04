"""Compatibility exports for callers that prefer a schemas module."""

from . import (
    CONTRACT_DIR,
    DEEP_REVIEW_REPORT_SCHEMA,
    DEEP_REVIEW_STAGE_SCHEMA,
    DEEP_REVIEW_VALIDATION_SCHEMA,
    DOCUMENT_BUNDLE_SCHEMA,
    DOCUMENT_STRUCTURE_SCHEMA,
    SCHEMAS,
    load_schema,
    schema_path,
    validate_payload,
)

__all__ = [
    "CONTRACT_DIR", "DEEP_REVIEW_REPORT_SCHEMA", "DEEP_REVIEW_STAGE_SCHEMA",
    "DEEP_REVIEW_VALIDATION_SCHEMA", "DOCUMENT_BUNDLE_SCHEMA",
    "DOCUMENT_STRUCTURE_SCHEMA", "SCHEMAS", "load_schema", "schema_path",
    "validate_payload",
]
