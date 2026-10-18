"""RL-04 deterministic proposal PDF renderer (spec "PDF 렌더"; seam: ``proposal_export``).

* Renderer: ReportLab (``renderer_version = reportlab==<version>``) with
  ``invariant=1`` -- fixed CreationDate/ModDate and trailer ``/ID`` -- and the
  backend image's NanumGothic TrueType pair from ``BIDOPS_PDF_FONT_DIR``
  (default ``/usr/share/fonts/truetype/nanum``; no font file lives in the
  repository, D9).  A missing or unreadable font is ``pdf_unavailable``.
  ``font_sha256`` = canonical SHA of ``{file name: sha256}`` of both files, so
  an image font change makes a new overlay.  The date printed on the cover is
  the draft ``created_at`` (KST), never the render time.
* Layout: A4 portrait, body 11 pt with 1.6 leading, page numbers; cover (notice
  title, agency, "초안 · <date> · 제출본 아님", the reference-run marker), table
  of contents, the six sections in spec order with the edit overlay applied,
  appendix A (requirement links: unit, normalized requirement, fit pill text,
  section/paragraph) and appendix B (numbered sources: kind, ref, quote).
* Markers: ``placeholder`` on the PDF highlight colour with "[채울 것: <hint>]",
  ``proposed_figure`` on the same colour with "[제안 수치]", an edited sentence
  ends with "[수정됨]", every ``statement``/``proposed_figure`` ends with its
  superscript source numbers.  A failed section prints a "생성 실패" notice.
  The colour is a PDF-only constant (not a screen theme token).
* Storage: the bytes go to object namespace ``proposal-pdf`` under a server key
  ``proposal-pdf/<sha prefix>-<uuid>.pdf``; ``content_object`` (sha256 unique,
  ``retention_class=proposal-pdf-365d``, not encrypted) and a verified
  ``content_object_location`` pin the hash; ``proposal_export`` is
  UNIQUE(draft_id, overlay_sha256), so the same overlay reuses its row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
from html import escape
import io
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...lifecycle.models import Notice
from ..models import ContentObject, ContentObjectLocation, ProposalDraft, ProposalExport
from . import assets
from .input_versions import PROPOSAL_SECTION_KEYS, canonical_json_hash
from .proposal_draft import SECTION_TITLES, draft_lineage
from .proposal_export import ProposalExportUnavailable


NAMESPACE = "proposal-pdf"
RETENTION_CLASS = "proposal-pdf-365d"
FONT_FILES = ("NanumGothic.ttf", "NanumGothicBold.ttf")
#: PDF-only highlight for placeholders and proposed figures (spec "표식").
HIGHLIGHT = "#FFF4E5"
KST = ZoneInfo("Asia/Seoul")
MAX_PDF_BYTES = 50 * 1024 * 1024
_FIT_TEXT = {"met": "충족", "gap": "미충족", "unknown": "확인 필요"}
_SOURCE_KIND_TEXT = {"requirement_unit": "요구사항", "company_fact": "회사 사실", "notice_meta": "공고 정보"}
_QUALITY_TEXT = {
    "unmeasured_reference": "참조 실행 결과(unmeasured_reference) · 품질 근거 아님",
    "mock_reference": "모의 참조 결과(mock_reference) · 실제 모델 결과 아님",
}
_REGISTERED: dict[str, tuple[str, str]] = {}


def _reportlab() -> Any:
    try:
        import reportlab
    except ImportError:  # pragma: no cover - the lock installs it
        raise ProposalExportUnavailable() from None
    return reportlab


def _font_paths() -> tuple[Path, Path]:
    directory = Path(get_settings().pdf_font_dir)
    return directory / FONT_FILES[0], directory / FONT_FILES[1]


def _font_digests() -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in _font_paths():
        try:
            digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            raise ProposalExportUnavailable() from None
    return digests


def renderer_identity() -> tuple[str, str]:
    """``(renderer_version, font_sha256)``; ``pdf_unavailable`` without ReportLab or the fonts."""

    reportlab = _reportlab()
    return f"reportlab=={reportlab.Version}", canonical_json_hash(_font_digests())


def _fonts(font_sha256: str) -> tuple[str, str]:
    """Register the NanumGothic pair once per font identity; returns (regular, bold) names."""

    if font_sha256 in _REGISTERED:
        return _REGISTERED[font_sha256]
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular_path, bold_path = _font_paths()
    regular, bold = f"BidOpsNanum-{font_sha256[:12]}", f"BidOpsNanumBold-{font_sha256[:12]}"
    try:
        pdfmetrics.registerFont(TTFont(regular, str(regular_path)))
        pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
    except Exception:  # noqa: BLE001 - any unreadable font is pdf_unavailable
        raise ProposalExportUnavailable() from None
    for is_bold, is_italic, name in ((0, 0, regular), (1, 0, bold), (0, 1, regular), (1, 1, bold)):
        addMapping(regular, is_bold, is_italic, name)
    _REGISTERED[font_sha256] = (regular, bold)
    return regular, bold


# --- document --------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return escape(str(value), quote=False)


class _Sources:
    """Global source numbering (first appearance; identical kind/ref/quote share a number)."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self._index: dict[tuple[str, str, str], int] = {}

    def number(self, source: Mapping[str, Any]) -> int:
        key = (str(source.get("kind")), str(source.get("ref")), str(source.get("quote")))
        if key not in self._index:
            self.rows.append(key)
            self._index[key] = len(self.rows)
        return self._index[key]


def _sentence_markup(sentence: Mapping[str, Any], sources: _Sources) -> str:
    kind = sentence.get("kind")
    text = _text(sentence.get("text") or "")
    if kind == "placeholder":
        body = f'<span backColor="{HIGHLIGHT}">{text} [채울 것: {_text(sentence.get("placeholder_hint") or "")}]</span>'
    elif kind == "proposed_figure":
        body = f'<span backColor="{HIGHLIGHT}">{text} [제안 수치]</span>'
    else:
        body = text
    if sentence.get("edited"):
        body += " [수정됨]"
    if kind in {"statement", "proposed_figure"}:
        numbers = [sources.number(source) for source in sentence.get("sources") or []]
        if numbers:
            body += "<super>" + ",".join(str(number) for number in numbers) + "</super>"
    return body


def _matrix(session: Session, draft: ProposalDraft) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Verdict matrix rows (card units, frozen order) and each card unit's display id."""

    from .verdict_view import VerdictViewError, completed_card_attempt

    try:
        attempt = completed_card_attempt(session, draft.verdict_attempt_id)
    except VerdictViewError:
        raise ProposalExportUnavailable() from None
    by_unit = {str(row["unit_id"]): row for row in attempt.result.get("matrix") or []}
    rows: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for unit in attempt.card.units:
        if unit.kind != "card":
            continue
        names[unit.unit_id] = unit.normalized_id or unit.unit_id
        row = by_unit.get(unit.unit_id) or {}
        rows.append({"unit_id": unit.unit_id, "normalized_requirement": row.get("normalized_requirement"),
                     "fit_status": row.get("fit_status", "unknown")})
    return rows, names


def pdf_outline(
    *,
    view: Mapping[str, Any],
    notice_title: str | None,
    notice_agency: str | None,
    created_at: datetime,
    quality_status: str | None,
    matrix: Sequence[Mapping[str, Any]],
    unit_names: Mapping[str, str],
) -> list[tuple[str, Any]]:
    """The document as ``(kind, value)`` items -- the exact markup the PDF renders (pure, testable).

    kinds: ``title``/``centered``/``heading``/``subheading``/``body``/``small`` (value = ReportLab
    paragraph markup), ``space`` (mm), ``page`` (page break), ``table`` (rows of cell markup).
    """

    date = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    date_text = date.astimezone(KST).date().isoformat()
    sources = _Sources()
    items: list[tuple[str, Any]] = [
        ("space", 60), ("title", _text(notice_title or "제목 없음")), ("space", 8),
        ("centered", _text(notice_agency or "기관 미상")), ("space", 4),
        ("centered", f"초안 · {date_text} · 제출본 아님"),
    ]
    if quality_status in _QUALITY_TEXT:
        items += [("space", 4), ("centered", _text(_QUALITY_TEXT[quality_status]))]
    items += [("page", None), ("heading", "목차")]
    sections = {row["section_key"]: row for row in view.get("sections") or []}
    for index, key in enumerate(PROPOSAL_SECTION_KEYS, start=1):
        items.append(("body", f"{index}. {_text(SECTION_TITLES[key])}"))
    items += [("body", "부록 A. 요구사항 대응표"), ("body", "부록 B. 출처 목록")]
    links: dict[str, list[str]] = {}
    for index, key in enumerate(PROPOSAL_SECTION_KEYS, start=1):
        section = sections.get(key) or {}
        items += [("page", None), ("heading", f"{index}. {_text(SECTION_TITLES[key])}")]
        if section.get("status") not in {"completed", "reviewed"}:
            code = section.get("error_code")
            failed = "생성 실패 · 이 절은 사람이 작성한다" + (f" ({_text(code)})" if code else "")
            items.append(("body", f'<span backColor="{HIGHLIGHT}">{failed}</span>'))
            continue
        for paragraph in section.get("paragraphs") or []:
            if paragraph.get("heading"):
                items.append(("subheading", _text(paragraph["heading"])))
            markup = " ".join(_sentence_markup(sentence, sources) for sentence in paragraph.get("sentences") or [])
            items += [("body", markup or " "), ("space", 2)]
        for link in section.get("requirement_links") or []:
            links.setdefault(str(link["unit_id"]), []).append(f"{SECTION_TITLES[key]} / {link['paragraph_id']}")
    rows = [["요구사항", "정규화 문장", "대조", "절 / 문단"]]
    for row in matrix:
        unit_id = str(row["unit_id"])
        rows.append([
            _text(unit_names.get(unit_id, unit_id)),
            _text(row.get("normalized_requirement") or "—"),
            _text(_FIT_TEXT.get(str(row.get("fit_status")), "확인 필요")),
            _text(", ".join(links.get(unit_id, [])) or "연결 없음"),
        ])
    items += [("page", None), ("heading", "부록 A. 요구사항 대응표"), ("table", rows), ("page", None),
              ("heading", "부록 B. 출처 목록")]
    if not sources.rows:
        items.append(("body", "출처 없음"))
    for number, (kind, ref, quote) in enumerate(sources.rows, start=1):
        label = _SOURCE_KIND_TEXT.get(kind, kind)
        items.append(("small", f"{number}. [{_text(label)}] {_text(unit_names.get(ref, ref))} · “{_text(quote)}”"))
    return items


def render_pdf(*, outline: Sequence[tuple[str, Any]], font_sha256: str) -> tuple[bytes, int]:
    """Render an outline to PDF bytes (byte-identical for the same outline and fonts) and its page count."""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular, bold = _fonts(font_sha256)
    body = ParagraphStyle("body", fontName=regular, fontSize=11, leading=17.6)
    styles = {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=9, leading=13),
        "heading": ParagraphStyle("heading", parent=body, fontName=bold, fontSize=16, leading=24, spaceBefore=6,
                                  spaceAfter=8),
        "subheading": ParagraphStyle("subheading", parent=body, fontName=bold, fontSize=12, leading=19,
                                     spaceBefore=6),
        "title": ParagraphStyle("title", parent=body, fontName=bold, fontSize=20, leading=30, alignment=TA_CENTER),
        "centered": ParagraphStyle("centered", parent=body, alignment=TA_CENTER),
    }
    story: list[Any] = []
    for kind, value in outline:
        if kind == "space":
            story.append(Spacer(1, float(value) * mm))
        elif kind == "page":
            story.append(PageBreak())
        elif kind == "table":
            cells = [[Paragraph(text, styles["small"]) for text in row] for row in value]
            table = Table(cells, colWidths=[28 * mm, 82 * mm, 20 * mm, 40 * mm], repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
            ]))
            story.append(table)
        else:
            story.append(Paragraph(value, styles[kind]))

    def page_number(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 9)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, str(document.page))
        canvas.restoreState()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, invariant=1, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm,
        bottomMargin=20 * mm, title="제안서 초안", author="BidOps", subject="제출본 아님", creator="BidOps",
    )
    document.build(story, onFirstPage=page_number, onLaterPages=page_number)
    data = buffer.getvalue()
    if len(data) > MAX_PDF_BYTES:
        raise ProposalExportUnavailable()
    return data, int(document.page)


# --- seam entry points -----------------------------------------------------------------------


def _existing(session: Session, draft_id: UUID, overlay_sha256: str) -> ProposalExport | None:
    return session.scalar(select(ProposalExport).where(
        ProposalExport.draft_id == draft_id, ProposalExport.overlay_sha256 == overlay_sha256,
    ))


def _store(session: Session, data: bytes, digest: str) -> ContentObject:
    content = session.scalar(select(ContentObject).where(ContentObject.sha256 == digest))
    if content is not None:
        location = session.scalar(select(ContentObjectLocation).where(
            ContentObjectLocation.content_object_id == content.id,
            ContentObjectLocation.namespace_key == NAMESPACE, ContentObjectLocation.status == "verified",
        ).limit(1))
        if location is not None and content.size_bytes == len(data):
            return content
    object_key = f"{NAMESPACE}/{digest[:16]}-{uuid4().hex}.pdf"
    try:
        _path, metadata = assets.store_named(NAMESPACE, object_key, data, content_type="application/pdf")
    except assets.AssetError:
        raise ProposalExportUnavailable() from None
    if content is None:
        content = ContentObject(id=uuid4(), sha256=digest, size_bytes=len(data), detected_mime="application/pdf",
                                retention_class=RETENTION_CLASS)
        session.add(content)
        session.flush()
    elif content.size_bytes != len(data):
        raise ProposalExportUnavailable()
    session.add(ContentObjectLocation(
        id=uuid4(), content_object_id=content.id, namespace_key=NAMESPACE, object_key=object_key,
        object_version_id=metadata.object_version_id, etag=metadata.etag, status="verified",
        encryption_key_ref=None, verified_at=datetime.now(UTC),
    ))
    session.flush()
    return content


def render_proposal_export(session: Session, *, draft: ProposalDraft, view: Mapping[str, Any], actor: str,
                           overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Seam: reuse the export of this overlay or render, store and insert it (the caller commits)."""

    overlay_sha256 = str(overlay["overlay_sha256"])
    existing = _existing(session, draft.id, overlay_sha256)
    if existing is not None:
        return {"export_id": existing.id, "pdf_sha256": existing.pdf_sha256, "created": False}
    renderer_version, font_sha256 = renderer_identity()
    if (renderer_version, font_sha256) != (overlay["renderer_version"], overlay["font_sha256"]):
        raise ProposalExportUnavailable()  # the font/renderer changed between identity and render
    notice = session.get(Notice, draft.notice_id)
    matrix, names = _matrix(session, draft)
    lineage = draft_lineage(session, draft.id) or {}
    outline = pdf_outline(
        view=view, notice_title=getattr(notice, "title", None), notice_agency=getattr(notice, "agency", None),
        created_at=draft.created_at, quality_status=lineage.get("quality_status"), matrix=matrix,
        unit_names=names,
    )
    data, page_count = render_pdf(outline=outline, font_sha256=font_sha256)
    digest = hashlib.sha256(data).hexdigest()
    content = _store(session, data, digest)
    row = ProposalExport(
        id=uuid4(), draft_id=draft.id, overlay_sha256=overlay_sha256, renderer_version=renderer_version,
        font_sha256=font_sha256, content_object_id=content.id, pdf_sha256=digest, page_count=page_count,
        created_by=actor,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = _existing(session, draft.id, overlay_sha256)
        if existing is None:
            raise
        return {"export_id": existing.id, "pdf_sha256": existing.pdf_sha256, "created": False}
    return {"export_id": row.id, "pdf_sha256": digest, "created": True}


def read_proposal_export(session: Session, *, row: ProposalExport) -> bytes:
    """Seam: the stored bytes of one export, verified against ``pdf_sha256`` (never re-rendered)."""

    location = session.scalar(select(ContentObjectLocation).where(
        ContentObjectLocation.content_object_id == row.content_object_id,
        ContentObjectLocation.namespace_key == NAMESPACE, ContentObjectLocation.status == "verified",
    ).order_by(ContentObjectLocation.created_at.asc(), ContentObjectLocation.id.asc()).limit(1))
    if location is None:
        raise ProposalExportUnavailable()
    try:
        data, _metadata = assets.read_object(NAMESPACE, location.object_key, max_bytes=MAX_PDF_BYTES,
                                             version_id=location.object_version_id)
    except (assets.AssetError, KeyError):
        raise ProposalExportUnavailable() from None
    if hashlib.sha256(data).hexdigest() != row.pdf_sha256:
        raise ProposalExportUnavailable()
    return data


__all__ = [
    "FONT_FILES",
    "HIGHLIGHT",
    "NAMESPACE",
    "RETENTION_CLASS",
    "pdf_outline",
    "read_proposal_export",
    "render_pdf",
    "render_proposal_export",
    "renderer_identity",
]
