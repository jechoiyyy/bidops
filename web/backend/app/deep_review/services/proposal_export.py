"""RL-04 PDF export seam (spec "PDF 렌더", "저장" ``proposal_export``).

STEP-006 owns the REST wiring and the overlay identity; the renderer itself
(ReportLab + the image's NanumGothic, object storage ``proposal-pdf``, the
``proposal_export`` row with UNIQUE(draft_id, overlay_sha256)) is STEP-007's
``services/proposal_render.py``.  Until that module exists both entry points
fail closed with ``pdf_unavailable`` -- no PDF is ever faked.

``overlay_sha256`` is the canonical SHA-256 of exactly the spec inputs: the
latest section revisions (key, id, revision, status, result sha), the set of
sentence edits of those revisions, ``renderer_version`` (``reportlab==x.y.z``)
and ``font_sha256``.  The same overlay therefore names the same bytes.

STEP-007 contract of ``proposal_render``:

* ``render_proposal_export(session, *, draft, view, actor, overlay) -> dict``
  returning ``{export_id, pdf_sha256, created}`` (an existing row for the same
  overlay → ``created=False``; the caller commits);
* ``read_proposal_export(session, *, row) -> bytes`` returning the stored PDF
  bytes whose SHA-256 equals ``row.pdf_sha256``;
* ``renderer_identity() -> (renderer_version, font_sha256)``;
* each raises ``ProposalExportUnavailable`` when fonts/renderer are missing.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from types import ModuleType
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProposalDraft, ProposalExport, ProposalSentenceEdit
from .input_versions import canonical_json_hash
from .proposal_draft import latest_sections


OVERLAY_SCHEMA = "bidops.proposal-export-overlay.v1"


class ProposalExportUnavailable(RuntimeError):
    """The PDF renderer or its font is not available (``pdf_unavailable``, 503)."""

    code = "pdf_unavailable"


def _renderer() -> ModuleType:
    try:
        return import_module(".proposal_render", __package__)
    except ModuleNotFoundError as error:
        if error.name and error.name.endswith("proposal_render"):
            raise ProposalExportUnavailable() from None
        raise


def overlay_inputs(session: Session, draft: ProposalDraft) -> dict[str, Any]:
    """The renderer-independent part of the overlay: latest revisions and their edit set."""

    sections = latest_sections(session, draft.id)
    rows = [
        {"section_key": key, "section_id": str(row.id), "revision": int(row.revision), "status": row.status,
         "result_sha256": row.result_sha256}
        for key, row in sorted(sections.items())
    ]
    section_ids = [row.id for row in sections.values()]
    edits = sorted(
        str(edit_id) for edit_id in session.scalars(
            select(ProposalSentenceEdit.id).where(ProposalSentenceEdit.section_id.in_(section_ids))
        )
    ) if section_ids else []
    return {"draft_id": str(draft.id), "sections": rows, "edit_ids": edits}


def overlay_sha256(inputs: Mapping[str, Any], *, renderer_version: str, font_sha256: str) -> str:
    """Spec: canonical SHA of section revisions, edit set, ``renderer_version`` and ``font_sha256``."""

    if not isinstance(renderer_version, str) or not renderer_version or not isinstance(font_sha256, str) \
            or len(font_sha256) != 64:
        raise ValueError("renderer identity is invalid")
    return canonical_json_hash({
        "schema": OVERLAY_SCHEMA, "draft_id": inputs["draft_id"], "sections": list(inputs["sections"]),
        "edit_ids": list(inputs["edit_ids"]), "renderer_version": renderer_version, "font_sha256": font_sha256,
    })


def render_proposal_export(session: Session, *, draft: ProposalDraft, view: Mapping[str, Any],
                           actor: str) -> dict[str, Any]:
    """Render (or reuse) the PDF of the draft's current overlay → ``{export_id, pdf_sha256, created}``."""

    renderer = _renderer()
    renderer_version, font_sha256 = renderer.renderer_identity()
    inputs = overlay_inputs(session, draft)
    overlay = overlay_sha256(inputs, renderer_version=renderer_version, font_sha256=font_sha256)
    return renderer.render_proposal_export(session, draft=draft, view=view, actor=actor, overlay={
        **inputs, "renderer_version": renderer_version, "font_sha256": font_sha256, "overlay_sha256": overlay,
    })


def find_export(session: Session, *, draft_id: UUID, export_id: UUID) -> ProposalExport | None:
    row = session.get(ProposalExport, export_id)
    return row if row is not None and row.draft_id == draft_id else None


def read_proposal_export(session: Session, *, row: ProposalExport) -> bytes:
    """The stored PDF bytes of one export row (renderer module reads the object store)."""

    return _renderer().read_proposal_export(session, row=row)


def latest_export(session: Session, draft_id: UUID) -> ProposalExport | None:
    return session.scalar(
        select(ProposalExport).where(ProposalExport.draft_id == draft_id)
        .order_by(ProposalExport.created_at.desc(), ProposalExport.id.desc()).limit(1)
    )


__all__ = [
    "OVERLAY_SCHEMA",
    "ProposalExportUnavailable",
    "find_export",
    "latest_export",
    "overlay_inputs",
    "overlay_sha256",
    "read_proposal_export",
    "render_proposal_export",
]
