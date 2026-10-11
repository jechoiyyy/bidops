"""The existing splitter's source units for company analysis inputs (contract §5, §9).

One helper for both purposes, so a company fit and a company deep review of
the same ready bundle freeze the same units:

* ``DeepReviewService._requirements`` with ``max_requirements=1`` and the
  purpose policy's ``chunking.source_characters`` (the narrative worker's
  splitter, output order and fields unchanged);
* each unit's ``document_requirement_ids`` read from its text with the bundle
  segment inventory's confirmed prefixes;
* the union of observed ids must equal the inventory ``expected_ids`` exactly
  (no relaxation); otherwise ``CompanyAnalysisError("company_input_invalid")``.

Callers map the error to their own surface: the deep path keeps its 409
``DeepReviewServiceError`` (``company_deep_review.company_source_units``), the
fit enqueue reports the ``company_input_invalid`` gate code.  This module sits
apart from both because ``company_deep_review`` imports ``company_fit``; the
splitter class is imported lazily for the same reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from . import document_segments
from .company_analysis_input import CompanyAnalysisError


def bundle_source_units(
    session: Session,
    bundle: Mapping[str, Any],
    structures: Mapping[str, Mapping[str, Any]],
    *,
    source_characters: int,
) -> list[dict[str, Any]]:
    """The pinned bundle's splitter units, exactly as the narrative worker builds them.

    ``bundle``/``structures`` are ``input_versions.bundle_context`` output.  An
    inventory mismatch is ``company_input_invalid`` (the legacy worker would
    fail the same input after approval).
    """

    from .deep_reviews import DeepReviewService

    units = [
        row
        for group in DeepReviewService._requirements(
            bundle, structures, max_characters=source_characters, max_requirements=1
        )
        for row in group
    ]
    inventory = document_segments.inventory_context(
        session, [UUID(str(row["structure_id_at_confirmation"])) for row in bundle["documents"]]
    )
    for unit in units:
        unit["document_requirement_ids"] = sorted(
            document_segments.observed_requirement_ids([str(unit.get("text", ""))], inventory.get("prefixes", []))
        )
    observed = {rid for unit in units for rid in unit["document_requirement_ids"]}
    if observed != set(inventory.get("expected_ids", [])):
        raise CompanyAnalysisError("company_input_invalid")
    return units


__all__ = ["bundle_source_units"]
