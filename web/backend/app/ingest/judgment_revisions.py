"""Canonical, ID-free snapshots for screening judgment revisions.

The legacy ``Judgment`` tables remain the read projection.  This helper
normalizes an artifact judgment to exactly the payload shape produced by the
0011 backfill, before any database child identifiers exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def judgment_revision_payload(
    raw: Mapping[str, Any], *, schema_version: str
) -> dict[str, Any]:
    """Build the deterministic ``bidops.judgment-revision-payload.v1`` value.

    Array order is artifact order.  Synthetic positions mirror the legacy
    projection materializer, while nullable scalar values and explicit
    ``unknown`` evidence statuses are retained unchanged.
    """

    perspectives: list[dict[str, Any]] = []
    raw_perspectives = raw.get("perspectives")
    for position, perspective in enumerate(
        raw_perspectives if isinstance(raw_perspectives, list) else (), start=1
    ):
        if not isinstance(perspective, Mapping):
            continue
        evidence: list[dict[str, Any]] = []
        raw_evidence = perspective.get("evidence")
        for item in raw_evidence if isinstance(raw_evidence, list) else ():
            if not isinstance(item, Mapping):
                continue
            evidence.append(
                {
                    "source": item.get("source"),
                    "status": item.get("status"),
                    "fact": item.get("fact"),
                }
            )
        perspectives.append(
            {
                "position": perspective.get("position", position),
                "name": perspective.get("name"),
                "assessment": perspective.get("assessment"),
                "reason": perspective.get("reason"),
                "evidence": evidence,
            }
        )

    counterarguments: list[dict[str, Any]] = []
    raw_counterarguments = raw.get("counterarguments")
    for position, counterargument in enumerate(
        raw_counterarguments if isinstance(raw_counterarguments, list) else (),
        start=1,
    ):
        if isinstance(counterargument, str):
            counterarguments.append({"position": position, "text": counterargument})
        elif isinstance(counterargument, Mapping):
            counterarguments.append(
                {
                    "position": counterargument.get("position", position),
                    "text": counterargument.get("text"),
                }
            )
        else:
            # The compatibility projection retains an invalid historical
            # counterargument as a null-valued row and emits a warning.
            counterarguments.append({"position": position, "text": None})

    verification_items: list[dict[str, Any]] = []
    raw_verification = raw.get("verification_items")
    for item in raw_verification if isinstance(raw_verification, list) else ():
        if not isinstance(item, Mapping):
            continue
        verification_items.append(
            {
                "item": item.get("item"),
                "why": item.get("why"),
                "blocking": bool(item.get("blocking", False)),
                "status": item.get("status"),
            }
        )

    matched_performances: list[dict[str, Any]] = []
    raw_matches = raw.get("matched_performances")
    for item in raw_matches if isinstance(raw_matches, list) else ():
        if not isinstance(item, Mapping):
            continue
        matched_performances.append(
            {
                "name": item.get("name") or item.get("project_name"),
                "match_reason": item.get("match_reason"),
                "mismatch_or_limit": item.get("mismatch_or_limit"),
                "source": item.get("source") or item.get("source_page"),
                "status": item.get("status")
                or item.get("legal_qualification_status"),
            }
        )

    return {
        "schema_version": schema_version,
        "grade": raw.get("grade"),
        "readiness": raw.get("readiness"),
        "primary_focus": raw.get("primary_focus"),
        "exclusion_category": raw.get("exclusion_category"),
        "summary": raw.get("summary"),
        "next_action": raw.get("next_action"),
        "perspectives": perspectives,
        "counterarguments": counterarguments,
        # Current v3 artifacts have already passed the strict screening
        # contract, so retain this substantive judgment list exactly as
        # emitted.  Historical artifacts did not record it and must remain
        # explicitly unknown rather than receiving an inferred empty list.
        "counterargument_resolutions": raw.get("counterargument_resolutions"),
        "verification_items": verification_items,
        "matched_performances": matched_performances,
    }


__all__ = ["judgment_revision_payload"]
