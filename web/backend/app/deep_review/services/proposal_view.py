"""RL-04 proposal REST services (spec "REST (`bidops.proposal.v1`)"): view, edits, review, stage, exports.

* ``proposal_view``: the draft of an opportunity (latest, or ``draft_id`` of
  that opportunity) with the newest revision of each section, the latest
  sentence edit applied to each sentence (``edited=True``) -- the stored model
  payload is never changed -- requirement links with the verdict matrix fit,
  requirement coverage over the verdict's card units, counters and the latest
  export.  No operational information (policy, model, input/result sha, tokens).
* ``create_sentence_edit``: append-only ``proposal_sentence_edit`` (201); a superseded
  draft is read-only (``stage_transition_invalid``, decision B50) -- also for review.
* ``review_section``: ``completed -> reviewed``; when all six newest revisions are
  reviewed the draft stage moves ``draft -> reviewed`` in the same transaction.
* ``set_draft_stage``: ``reviewed -> ready`` only, never back.
* ``create_export``/``export_pdf``: the ``proposal_export`` seam (``pdf_unavailable``
  until the STEP-007 renderer exists).
* ``ProposalActivityProvider``: lifecycle activity ``draft_prepared`` (read only).

Gate: ``BIDOPS_RL_ANALYSIS_ENABLED`` and the one registered real company, else
404 (the assembly middleware hides the paths first).  Human mutations need the
actor header and are idempotent by ``request_id`` through the core
``IdempotencyRecord`` fence (same scope + same hash replays the stored
snapshot, another hash is ``idempotency_conflict``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.idempotency_fence import IdempotencyFenceError, load_receipt, new_receipt, receipt_id, request_sha256
from ...lifecycle.schemas.opportunity_activity import ActivityItem, ActivityLink
from ..models import ProposalDraft, ProposalSection, ProposalSentenceEdit
from ..schemas.proposal import ProposalView, SectionView
from .input_versions import PROPOSAL_SECTION_KEYS
from .proposal_draft import (
    COMPLETED_SECTION_STATUSES,
    SECTION_TITLES,
    ProposalServiceError,
    latest_sections,
)
from .proposal_export import (
    ProposalExportUnavailable,
    find_export,
    latest_export,
    read_proposal_export,
    render_proposal_export,
)


_RECEIPT_NAMESPACE = uuid5(NAMESPACE_URL, "bidops:proposal-receipt")
ACTIVITY_LINK_LABEL = "제안서 보기"
_ACTIVITY_TITLES = {"completed": "제안서 초안 준비", "partial": "제안서 초안 준비 · 일부 절 실패"}


def _error(code: str) -> ProposalServiceError:
    return ProposalServiceError(code)


# --- gate -----------------------------------------------------------------------------------


def require_proposal_path(session: Session, settings: Any = None) -> Any:
    """RL path only: ``BIDOPS_RL_ANALYSIS_ENABLED`` and the registered real company (else 404)."""

    from .verdict_trigger import real_company

    settings = settings or get_settings()
    if not getattr(settings, "rl_analysis_enabled", False):
        raise _error("not_found")
    company = real_company(session)
    if company is None:
        raise _error("not_found")
    return company


def _draft(session: Session, draft_id: UUID) -> ProposalDraft:
    draft = session.get(ProposalDraft, draft_id) if isinstance(draft_id, UUID) else None
    if draft is None:
        raise _error("not_found")
    return draft


# --- view -------------------------------------------------------------------------------------


def _latest_edits(session: Session, section_ids: list[UUID]) -> dict[tuple[str, str], str]:
    if not section_ids:
        return {}
    rows = session.scalars(
        select(ProposalSentenceEdit).where(ProposalSentenceEdit.section_id.in_(section_ids))
        .order_by(ProposalSentenceEdit.created_at.asc(), ProposalSentenceEdit.id.asc())
    ).all()
    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        latest[(str(row.section_id), str(row.sentence_id).lower())] = row.text
    return latest


def _payload(section: ProposalSection) -> Mapping[str, Any] | None:
    if section.status in COMPLETED_SECTION_STATUSES and isinstance(section.payload, Mapping):
        return section.payload
    return None


def section_view(section: ProposalSection, edits: Mapping[tuple[str, str], str],
                 fit: Mapping[str, str]) -> dict[str, Any]:
    payload = _payload(section)
    paragraphs: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    if payload is not None:
        for paragraph in payload.get("paragraphs") or []:
            sentences = []
            for sentence in paragraph.get("sentences") or []:
                key = (str(section.id), str(sentence["sentence_id"]).lower())
                edited = key in edits
                sentences.append({
                    "sentence_id": sentence["sentence_id"],
                    "text": edits[key] if edited else sentence["text"],
                    "kind": sentence["kind"],
                    "sources": [dict(source) for source in sentence.get("sources") or []],
                    "placeholder_hint": sentence.get("placeholder_hint"),
                    "edited": edited,
                })
            paragraphs.append({"paragraph_id": paragraph["paragraph_id"], "heading": paragraph.get("heading"),
                               "sentences": sentences})
        links = [
            {"unit_id": link["unit_id"], "paragraph_id": link["paragraph_id"],
             "fit_status": fit.get(link["unit_id"], "unknown")}
            for link in payload.get("requirement_links") or []
        ]
    return {
        "section_key": section.section_key, "title": SECTION_TITLES[section.section_key],
        "revision": int(section.revision), "status": section.status, "paragraphs": paragraphs,
        "requirement_links": links, "error_code": section.error_code if section.status == "failed" else None,
    }


def _verdict_fit(session: Session, draft: ProposalDraft) -> tuple[dict[str, str], list[str]]:
    """Matrix fit per unit and the card unit ids (frozen order) of the draft's verdict attempt."""

    from .verdict_view import VerdictViewError, completed_card_attempt

    try:
        attempt = completed_card_attempt(session, draft.verdict_attempt_id)
    except VerdictViewError:
        raise _error("processing_failed") from None
    fit = {str(row["unit_id"]): str(row["fit_status"]) for row in attempt.result.get("matrix") or []}
    cards = [unit.unit_id for unit in attempt.card.units if unit.kind == "card"]
    return fit, cards


def draft_view(session: Session, draft: ProposalDraft) -> dict[str, Any]:
    sections = latest_sections(session, draft.id)
    if set(sections) != set(PROPOSAL_SECTION_KEYS):
        raise _error("processing_failed")
    edits = _latest_edits(session, [row.id for row in sections.values()])
    fit, cards = _verdict_fit(session, draft)
    views = [section_view(sections[key], edits, fit) for key in PROPOSAL_SECTION_KEYS]
    placeholders = proposed = 0
    for view in views:
        for paragraph in view["paragraphs"]:
            for sentence in paragraph["sentences"]:
                placeholders += sentence["kind"] == "placeholder"
                proposed += sentence["kind"] == "proposed_figure"
    requirements = next(view for view in views if view["section_key"] == "requirements")
    linked = {link["unit_id"] for link in requirements["requirement_links"]}
    export = latest_export(session, draft.id)
    return {
        "draft_id": str(draft.id), "status": draft.status, "stage": draft.stage,
        "created_at": _iso(draft.created_at), "sections": views,
        "requirement_coverage": {
            "total": len(cards), "linked": sum(1 for unit_id in cards if unit_id in linked),
            "unlinked_unit_ids": [unit_id for unit_id in cards if unit_id not in linked],
        },
        "counters": {
            "sentences_to_confirm": placeholders + proposed, "placeholders": placeholders,
            "proposed_figures": proposed,
            "reviewed_sections": sum(1 for row in sections.values() if row.status == "reviewed"),
        },
        "latest_export": None if export is None else {
            "export_id": str(export.id), "created_at": _iso(export.created_at), "pdf_sha256": export.pdf_sha256,
        },
    }


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _validated(model: Any, value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return model.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise _error("processing_failed") from None


def proposal_view(session: Session, *, opportunity_id: int, draft_id: UUID | None = None,
                  settings: Any = None) -> dict[str, Any]:
    """GET /api/opportunities/{id}/proposal?draft_id= (read only)."""

    from .verdict_trigger import resolve_opportunity

    require_proposal_path(session, settings)
    opportunity = resolve_opportunity(session, int(opportunity_id))
    if opportunity is None:
        raise _error("opportunity_not_found")
    if draft_id is not None:
        draft = session.get(ProposalDraft, draft_id)
        if draft is None or draft.opportunity_id != opportunity.id:
            raise _error("not_found")
    else:
        draft = session.scalar(
            select(ProposalDraft).where(ProposalDraft.opportunity_id == opportunity.id)
            .order_by(ProposalDraft.created_at.desc(), ProposalDraft.id.desc()).limit(1)
        )
    return _validated(ProposalView, {"schema_version": "bidops.proposal.v1",
                                     "draft": None if draft is None else draft_view(session, draft)})


# --- idempotent mutations -----------------------------------------------------------------------


def _with_receipt(
    session: Session,
    *,
    operation: str,
    draft_id: UUID,
    actor: str,
    request_id: UUID,
    request: Mapping[str, Any],
    status: int,
    perform: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Replay the stored snapshot or perform once and store the receipt in the same transaction."""

    scope = {"operation": operation, "aggregate_type": "proposal_draft", "aggregate_id": str(draft_id),
             "claimed_name": actor, "request_id": request_id}
    receipt = receipt_id(_RECEIPT_NAMESPACE, **scope)
    request_hash = request_sha256({"operation": operation, "draft_id": str(draft_id), "actor": actor, **request})
    try:
        stored = load_receipt(session, receipt=receipt, request_hash=request_hash, expected_status=status, **scope)
        if stored is not None:
            session.rollback()
            return stored
        snapshot = perform()
        session.add(new_receipt(receipt=receipt, request_hash=request_hash, snapshot=snapshot,
                                response_status=status, **scope))
        session.commit()
        return snapshot
    except IdempotencyFenceError as error:
        session.rollback()
        raise _error(error.code) from None
    except IntegrityError:
        # A concurrent identical request stored its receipt first: replay it.
        session.rollback()
        try:
            stored = load_receipt(session, receipt=receipt, request_hash=request_hash, expected_status=status,
                                  **scope)
        except IdempotencyFenceError as error:
            session.rollback()
            raise _error(error.code) from None
        session.rollback()
        if stored is None:
            raise _error("processing_failed") from None
        return stored
    except BaseException:
        session.rollback()
        raise


def _locked_draft(session: Session, draft_id: UUID) -> ProposalDraft:
    draft = session.scalar(select(ProposalDraft).where(ProposalDraft.id == draft_id).with_for_update())
    if draft is None:
        raise _error("not_found")
    return draft


def _find_sentence(session: Session, draft: ProposalDraft, sentence_id: UUID) -> ProposalSection:
    wanted = str(sentence_id).lower()
    for section in latest_sections(session, draft.id).values():
        payload = _payload(section)
        if payload is None:
            continue
        for paragraph in payload.get("paragraphs") or []:
            for sentence in paragraph.get("sentences") or []:
                if str(sentence.get("sentence_id", "")).lower() == wanted:
                    return section
    raise _error("sentence_not_found")


def create_sentence_edit(session: Session, *, draft_id: UUID, sentence_id: UUID, text: str, actor: str,
                         request_id: UUID, settings: Any = None) -> dict[str, Any]:
    """POST /api/proposals/{draft_id}/sentences/{sentence_id}/edits → 201 ``{edit_id}`` (append-only)."""

    require_proposal_path(session, settings)
    draft = _draft(session, draft_id)
    clean = text.strip() if isinstance(text, str) else ""
    if not 1 <= len(clean) <= 400:
        raise _error("invalid_request")
    section = _find_sentence(session, draft, sentence_id)

    def perform() -> dict[str, Any]:
        if _locked_draft(session, draft.id).status == "superseded":
            # The API guard, not only the screen: an old draft is read-only (decision B50).
            raise _error("stage_transition_invalid")
        edit = ProposalSentenceEdit(id=uuid4(), section_id=section.id, sentence_id=sentence_id, text=clean,
                                    actor=actor, request_id=request_id)
        session.add(edit)
        session.flush()
        return {"edit_id": str(edit.id)}

    return _with_receipt(session, operation="proposal.sentence.edit", draft_id=draft.id, actor=actor,
                         request_id=request_id, request={"sentence_id": str(sentence_id).lower(), "text": clean},
                         status=201, perform=perform)


def review_section(session: Session, *, draft_id: UUID, section_key: str, actor: str, request_id: UUID,
                   settings: Any = None) -> dict[str, Any]:
    """PATCH /api/proposals/{draft_id}/sections/{key}/review → 200 ``SectionView`` (``reviewed``)."""

    require_proposal_path(session, settings)
    draft = _draft(session, draft_id)
    if section_key not in PROPOSAL_SECTION_KEYS:
        raise _error("not_found")

    def perform() -> dict[str, Any]:
        locked = _locked_draft(session, draft.id)
        if locked.status == "superseded":
            raise _error("stage_transition_invalid")  # decision B50
        sections = latest_sections(session, locked.id)
        section = sections.get(section_key)
        if section is None:
            raise _error("not_found")
        if section.status == "completed":
            section.status = "reviewed"
            section.reviewed_by = actor
            section.reviewed_at = datetime.now(UTC)
            session.flush()
            sections = latest_sections(session, locked.id)
            if locked.stage == "draft" and all(row.status == "reviewed" for row in sections.values()):
                locked.stage = "reviewed"
                session.flush()
        elif section.status != "reviewed":
            raise _error("section_not_completed")
        fit, _cards = _verdict_fit(session, locked)
        edits = _latest_edits(session, [section.id])
        return _validated(SectionView, section_view(section, edits, fit))

    return _with_receipt(session, operation="proposal.section.review", draft_id=draft.id, actor=actor,
                         request_id=request_id, request={"section_key": section_key}, status=200, perform=perform)


def set_draft_stage(session: Session, *, draft_id: UUID, stage: str, actor: str, request_id: UUID,
                    settings: Any = None) -> dict[str, Any]:
    """PATCH /api/proposals/{draft_id}/stage ``{stage:"ready"}`` → 200 ``{stage}`` (from reviewed only)."""

    require_proposal_path(session, settings)
    draft = _draft(session, draft_id)
    if stage != "ready":
        raise _error("invalid_request")

    def perform() -> dict[str, Any]:
        locked = _locked_draft(session, draft.id)
        if locked.stage != "reviewed":
            raise _error("stage_transition_invalid")
        locked.stage = "ready"
        session.flush()
        return {"stage": "ready"}

    return _with_receipt(session, operation="proposal.draft.stage", draft_id=draft.id, actor=actor,
                         request_id=request_id, request={"stage": stage}, status=200, perform=perform)


def create_export(session: Session, *, draft_id: UUID, actor: str, request_id: UUID,
                  settings: Any = None) -> dict[str, Any]:
    """POST /api/proposals/{draft_id}/exports → 201 ``{export_id, pdf_sha256, created}``."""

    require_proposal_path(session, settings)
    draft = _draft(session, draft_id)
    if draft.status not in {"completed", "partial"}:
        raise _error("draft_not_completed")

    def perform() -> dict[str, Any]:
        try:
            result = render_proposal_export(session, draft=draft, view=draft_view(session, draft), actor=actor)
        except ProposalExportUnavailable:
            raise _error("pdf_unavailable") from None
        return {"export_id": str(result["export_id"]), "pdf_sha256": str(result["pdf_sha256"]),
                "created": bool(result["created"])}

    return _with_receipt(session, operation="proposal.export.create", draft_id=draft.id, actor=actor,
                         request_id=request_id, request={}, status=201, perform=perform)


def export_pdf(session: Session, *, draft_id: UUID, export_id: UUID, settings: Any = None) -> tuple[bytes, str]:
    """GET /api/proposals/{draft_id}/exports/{export_id}.pdf → (bytes, pdf_sha256); no side effect."""

    require_proposal_path(session, settings)
    row = find_export(session, draft_id=draft_id, export_id=export_id)
    if row is None:
        raise _error("not_found")
    try:
        data = read_proposal_export(session, row=row)
    except ProposalExportUnavailable:
        raise _error("pdf_unavailable") from None
    return data, row.pdf_sha256


# --- activity -----------------------------------------------------------------------------------


def proposal_activity_items(session: Session, opportunity_id: int, *, settings: Any = None) -> list[ActivityItem]:
    """``draft_prepared``: one item per draft that settled with at least one completed section."""

    try:
        require_proposal_path(session, settings)
    except ProposalServiceError:
        return []
    items: list[ActivityItem] = []
    for draft in session.scalars(select(ProposalDraft).where(ProposalDraft.opportunity_id == int(opportunity_id))):
        status = draft.status
        if draft.completed_at is None or status not in {"completed", "partial", "superseded"}:
            continue
        if status == "superseded":
            sections = latest_sections(session, draft.id)
            if not any(row.status in COMPLETED_SECTION_STATUSES for row in sections.values()):
                continue
            title = _ACTIVITY_TITLES["completed"]
        else:
            title = _ACTIVITY_TITLES[status]
        at = draft.completed_at if draft.completed_at.tzinfo else draft.completed_at.replace(tzinfo=UTC)
        items.append(ActivityItem(
            item_id=f"draft_prepared:{draft.id}", kind="draft_prepared", at=at.astimezone(UTC), actor=None,
            title=title,
            link=ActivityLink(label=ACTIVITY_LINK_LABEL,
                              path=f"/opportunities/{int(opportunity_id)}/proposal?draft_id={draft.id}"),
        ))
    return items


class ProposalActivityProvider:
    """lifecycle 확장점 `opportunity_activity_items`의 RL-04 제공자 (읽기 전용)."""

    def opportunity_activity_items(self, session: Any, opportunity_id: int) -> list[ActivityItem]:
        return proposal_activity_items(session, opportunity_id)


__all__ = [
    "ProposalActivityProvider",
    "create_export",
    "create_sentence_edit",
    "draft_view",
    "export_pdf",
    "proposal_activity_items",
    "proposal_view",
    "require_proposal_path",
    "review_section",
    "section_view",
    "set_draft_stage",
]
