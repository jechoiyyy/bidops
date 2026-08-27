"""Isolated document processing boundary for BidOps Lean v1."""

from .contracts import SCHEMA, UPSTREAM_COMMIT, validate_structure
from .errors import DocumentLimitError, DocumentProcessingError
from .processor import DocumentProcessor, ProcessedDocument, extract_structure, process_bytes, process_document
from .safety import MAX_INPUT_BYTES, ProcessorOptions, detect_media_type, enforce_input_limit

__all__ = [
    "DocumentLimitError",
    "DocumentProcessingError",
    "DocumentProcessor",
    "MAX_INPUT_BYTES",
    "ProcessedDocument",
    "ProcessorOptions",
    "SCHEMA",
    "UPSTREAM_COMMIT",
    "detect_media_type",
    "enforce_input_limit",
    "extract_structure",
    "process_bytes",
    "process_document",
    "validate_structure",
]
