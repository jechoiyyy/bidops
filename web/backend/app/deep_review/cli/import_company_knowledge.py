"""Dispatch shim for import-company-knowledge."""

from .company_knowledge import build_import_parser as build_parser
from .company_knowledge import import_main as main

__all__ = ["build_parser", "main"]
