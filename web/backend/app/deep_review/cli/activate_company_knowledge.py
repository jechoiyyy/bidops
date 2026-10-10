"""Dispatch shim for activate-company-knowledge."""

from .company_knowledge import activate_main as main
from .company_knowledge import build_activate_parser as build_parser

__all__ = ["build_parser", "main"]
