"""Batch projection for the screen-facing preliminary assessment.

Automation continues to consume ``effective_grades``.  This projection only
chooses what the list and detail screens display, with human corrections first.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocumentVersion, PrespecOverviewRun
from .effective_grade import EffectiveGrade, SOURCE_HUMAN_REVIEW, effective_grades


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _assessment_details(run: PrespecOverviewRun) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    assessment = run.assessment_json if isinstance(run.assessment_json, Mapping) else {}
    checks = run.assessment_checks_json if isinstance(run.assessment_checks_json, Mapping) else {}
    axes = []
    for row in assessment.get("axes") or []:
        if not isinstance(row, Mapping):
            continue
        axes.append({
            "axis": str(row.get("axis") or ""),
            "relation": str(row.get("relation") or "unknown"),
            "reason": str(row.get("reason") or ""),
            "claim_refs": _strings(row.get("claim_refs")),
            "company_refs": _strings(row.get("company_refs")),
        })
    return axes, _strings(assessment.get("verification_items")), _strings(checks.get("reason_codes"))


def display_assessments(
    session: Session,
    notice_ids: Sequence[int],
    *,
    grades: Mapping[int, EffectiveGrade] | None = None,
    latest_runs: Mapping[int, PrespecOverviewRun | None] | None = None,
) -> dict[int, dict[str, Any]]:
    """Resolve one display value per notice with a constant number of queries."""

    ids = tuple(dict.fromkeys(int(value) for value in notice_ids))
    if not ids:
        return {}
    resolved_grades = grades if grades is not None else effective_grades(session, ids)

    assessment_runs: dict[int, PrespecOverviewRun] = {}
    for run in session.scalars(
        select(PrespecOverviewRun)
        .join(DocumentVersion, DocumentVersion.id == PrespecOverviewRun.document_version_id)
        .where(
            PrespecOverviewRun.notice_id.in_(ids),
            PrespecOverviewRun.contract_version == "overview-assessment-v1",
            PrespecOverviewRun.assessment_status.in_(("graded", "held")),
            DocumentVersion.is_current.is_(True),
            DocumentVersion.safety_status == "safe",
            DocumentVersion.needs_human_review.is_(False),
        )
        .order_by(
            PrespecOverviewRun.notice_id.asc(),
            PrespecOverviewRun.created_at.desc(),
            PrespecOverviewRun.id.desc(),
        )
    ).all():
        assessment_runs.setdefault(int(run.notice_id), run)

    latest_status = {
        int(notice_id): str(run.status) if run is not None else None
        for notice_id, run in (latest_runs or {}).items()
    }
    result: dict[int, dict[str, Any]] = {}
    for notice_id in ids:
        grade = resolved_grades.get(notice_id)
        run = assessment_runs.get(notice_id)
        if grade is not None and grade.source == SOURCE_HUMAN_REVIEW:
            result[notice_id] = {
                "grade": grade.grade,
                "status": "graded",
                "source": "human_review",
                "basis_run_id": None,
                "assessed_at": _iso(grade.assessed_at),
                "quality_status": None,
                "reason_codes": [],
                "axes": [],
                "verification_items": [],
                "semantic_status": None,
                "semantic_scope": [],
                "latest_run_status": latest_status.get(notice_id),
            }
            continue
        if run is not None:
            axes, verification_items, reasons = _assessment_details(run)
            result[notice_id] = {
                "grade": run.assessment_grade if run.assessment_status == "graded" else None,
                "status": str(run.assessment_status),
                "source": "preliminary_assessment",
                "basis_run_id": str(run.id),
                "assessed_at": _iso(run.completed_at or run.created_at),
                "quality_status": (
                    "mock_reference" if str(run.model_name or "").startswith("mock")
                    else "unmeasured_reference"
                ),
                "reason_codes": reasons,
                "axes": axes,
                "verification_items": verification_items,
                "semantic_status": str(run.semantic_status),
                "semantic_scope": _strings(run.semantic_scope_json),
                "latest_run_status": latest_status.get(notice_id),
            }
            continue
        if grade is not None:
            result[notice_id] = {
                "grade": grade.grade,
                "status": "graded",
                "source": "screening_judgment",
                "basis_run_id": grade.run_id,
                "assessed_at": _iso(grade.assessed_at),
                "quality_status": None,
                "reason_codes": [],
                "axes": [],
                "verification_items": [],
                "semantic_status": None,
                "semantic_scope": [],
                "latest_run_status": latest_status.get(notice_id),
            }
            continue
        result[notice_id] = {
            "grade": None,
            "status": "none",
            "source": "none",
            "basis_run_id": None,
            "assessed_at": None,
            "quality_status": None,
            "reason_codes": [],
            "axes": [],
            "verification_items": [],
            "semantic_status": None,
            "semantic_scope": [],
            "latest_run_status": latest_status.get(notice_id),
        }
    return result


__all__ = ["display_assessments"]
