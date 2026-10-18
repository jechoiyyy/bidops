"""RL-04 STEP-007 T7: deterministic proposal PDF renderer (spec "PDF 렌더").

* outline (pure): six sections in order with the overlay text, placeholder /
  proposed-figure highlight markers, "[수정됨]", superscript source numbers,
  failed-section notice, appendix A (requirement links) and B (sources), cover
  date from the draft ``created_at`` (KST) and the reference-run marker;
* determinism: the same outline renders byte-identical PDFs in-process and in a
  separate interpreter (``invariant=1``, fixed font subset); a different overlay
  renders different bytes;
* a missing font is ``pdf_unavailable``.

Font-dependent cases need the image's NanumGothic pair at ``BIDOPS_PDF_FONT_DIR``
(default ``/usr/share/fonts/truetype/nanum``); they skip with that reason when
the files are absent.  No font file is stored in the repository (D9).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.config import get_settings
from app.deep_review.services.input_versions import canonical_json_hash
from app.deep_review.services.proposal_export import ProposalExportUnavailable
from app.deep_review.services.proposal_render import (
    FONT_FILES,
    HIGHLIGHT,
    pdf_outline,
    render_pdf,
    renderer_identity,
)


BACKEND = Path(__file__).resolve().parents[2]


def _font_dir() -> Path:
    get_settings.cache_clear()
    return Path(get_settings().pdf_font_dir)


def _fonts_available() -> bool:
    directory = _font_dir()
    return all((directory / name).is_file() for name in FONT_FILES)


needs_fonts = pytest.mark.skipif(
    not _fonts_available(),
    reason="NanumGothic.ttf/NanumGothicBold.ttf not found at BIDOPS_PDF_FONT_DIR (image font; not in the repo)",
)

KEYS = ("overview", "track_record", "strategy", "requirements", "operations_sla", "organization")


def _view() -> dict:
    sections = []
    for key in KEYS:
        sections.append({
            "section_key": key, "status": "completed", "error_code": None, "revision": 1,
            "paragraphs": [{"paragraph_id": "p1", "heading": "SFR-1 <대응>", "sentences": [
                {"sentence_id": "s1", "text": "원문 조건에 맞춰 수행한다 <A&B>.", "kind": "statement", "edited": False,
                 "placeholder_hint": None,
                 "sources": [{"kind": "requirement_unit", "ref": "card:u1", "quote": "상주 인력 3명"},
                             {"kind": "company_fact", "ref": "staff:onsite", "quote": "상주 인력"}]},
                {"sentence_id": "s2", "text": "사람이 채운다.", "kind": "placeholder", "edited": False,
                 "placeholder_hint": "투입 인력 수", "sources": []},
                {"sentence_id": "s3", "text": "응답시간 3초 이내로 맞춘다.", "kind": "proposed_figure",
                 "edited": True, "placeholder_hint": None,
                 "sources": [{"kind": "requirement_unit", "ref": "card:u1", "quote": "상주 인력 3명"}]},
            ]}],
            "requirement_links": [{"unit_id": "card:u1", "paragraph_id": "p1", "fit_status": "unknown"}],
        })
    sections[2] = {"section_key": "strategy", "status": "failed", "error_code": "proposal_forbidden_content",
                   "revision": 1, "paragraphs": [], "requirement_links": []}
    return {"sections": sections}


MATRIX = [{"unit_id": "card:u1", "normalized_requirement": "상주 인력 3명 이상", "fit_status": "unknown"},
          {"unit_id": "card:u2", "normalized_requirement": "웹 접근성 준수", "fit_status": "met"}]
NAMES = {"card:u1": "SFR-1", "card:u2": "SFR-2"}


def _outline(view=None, **overrides):
    values = dict(view=view or _view(), notice_title="합성 누리집 고도화", notice_agency="합성기관",
                  created_at=datetime(2026, 10, 17, 16, 30, tzinfo=timezone.utc), quality_status="mock_reference",
                  matrix=MATRIX, unit_names=NAMES)
    values.update(overrides)
    return pdf_outline(**values)


def test_t7_outline_orders_sections_and_carries_every_marker() -> None:
    outline = _outline()
    texts = [value for kind, value in outline if kind not in {"space", "page", "table"}]
    # cover: KST date of the draft created_at (2026-10-18 01:30 KST), never the render time
    assert "초안 · 2026-10-18 · 제출본 아님" in texts
    assert "모의 참조 결과(mock_reference) · 실제 모델 결과 아님" in texts
    headings = [value for kind, value in outline if kind == "heading"]
    assert headings == ["목차", "1. 제안 개요", "2. 사업수행 실적", "3. 수행 전략", "4. 요구사항 수행방안",
                        "5. 운영·SLA", "6. 수행조직", "부록 A. 요구사항 대응표", "부록 B. 출처 목록"]
    body = [value for kind, value in outline if kind == "body"]
    sentence = next(value for value in body if "원문 조건에" in value)
    # statement: escaped text + superscript numbers (sources numbered at first appearance)
    assert "원문 조건에 맞춰 수행한다 &lt;A&amp;B&gt;.<super>1,2</super>" in sentence
    assert f'<span backColor="{HIGHLIGHT}">사람이 채운다. [채울 것: 투입 인력 수]</span>' in sentence
    # proposed figure: highlight + marker, edited suffix, the shared source keeps number 1
    assert f'<span backColor="{HIGHLIGHT}">응답시간 3초 이내로 맞춘다. [제안 수치]</span> [수정됨]<super>1</super>' in sentence
    assert HIGHLIGHT == "#FFF4E5"
    failed = [value for value in body if "생성 실패" in value]
    assert failed == [f'<span backColor="{HIGHLIGHT}">생성 실패 · 이 절은 사람이 작성한다 (proposal_forbidden_content)</span>']
    assert [value for kind, value in outline if kind == "subheading"][0] == "SFR-1 &lt;대응&gt;"
    table = next(value for kind, value in outline if kind == "table")
    assert table[0] == ["요구사항", "정규화 문장", "대조", "절 / 문단"]
    assert table[1][:3] == ["SFR-1", "상주 인력 3명 이상", "확인 필요"]
    assert table[1][3].startswith("제안 개요 / p1") and "수행 전략" not in table[1][3]
    assert table[2] == ["SFR-2", "웹 접근성 준수", "충족", "연결 없음"]
    sources = [value for kind, value in outline if kind == "small"]
    assert sources == ["1. [요구사항] SFR-1 · “상주 인력 3명”", "2. [회사 사실] staff:onsite · “상주 인력”"]
    unmeasured = _outline(quality_status="unmeasured_reference")
    assert any("unmeasured_reference" in str(value) for _kind, value in unmeasured)
    assert not any("reference" in str(value) for _kind, value in _outline(quality_status=None))


def test_t7_missing_font_is_pdf_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BIDOPS_PDF_FONT_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with pytest.raises(ProposalExportUnavailable):
            renderer_identity()
        (tmp_path / FONT_FILES[0]).write_bytes(b"not a font")
        (tmp_path / FONT_FILES[1]).write_bytes(b"not a font")
        _version, sha = renderer_identity()  # files exist: identity is their hash
        with pytest.raises(ProposalExportUnavailable):
            render_pdf(outline=_outline(), font_sha256=sha)  # ReportLab cannot load them
    finally:
        get_settings.cache_clear()


@needs_fonts
def test_t7_renderer_identity_is_reportlab_and_the_font_pair_hash() -> None:
    import reportlab

    version, font_sha256 = renderer_identity()
    directory = _font_dir()
    expected = canonical_json_hash({name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                    for name in FONT_FILES})
    assert version == f"reportlab=={reportlab.Version}" and font_sha256 == expected


_PROBE = """
import hashlib, json, sys
from datetime import datetime
from app.deep_review.services.proposal_render import pdf_outline, render_pdf, renderer_identity
args = json.loads(sys.stdin.read())
args["created_at"] = datetime.fromisoformat(args["created_at"])
data, pages = render_pdf(outline=pdf_outline(**args), font_sha256=renderer_identity()[1])
print(hashlib.sha256(data).hexdigest(), pages)
"""


@needs_fonts
def test_t7_same_outline_is_byte_identical_in_and_across_processes_and_a_new_overlay_differs() -> None:
    _version, font_sha256 = renderer_identity()
    first, pages = render_pdf(outline=_outline(), font_sha256=font_sha256)
    second, _ = render_pdf(outline=_outline(), font_sha256=font_sha256)
    assert first == second and first.startswith(b"%PDF-") and pages >= 9
    assert b"/CreationDate" in first
    args = {"view": _view(), "notice_title": "합성 누리집 고도화", "notice_agency": "합성기관",
            "created_at": "2026-10-17T16:30:00+00:00", "quality_status": "mock_reference", "matrix": MATRIX,
            "unit_names": NAMES}
    env = {**os.environ, "BIDOPS_PDF_FONT_DIR": str(_font_dir()), "PYTHONPATH": str(BACKEND)}
    probe = subprocess.run([sys.executable, "-W", "ignore", "-c", _PROBE], input=json.dumps(args, ensure_ascii=False),
                           capture_output=True, text=True, cwd=BACKEND, env=env, check=True, timeout=120)
    assert probe.stdout.split() == [hashlib.sha256(first).hexdigest(), str(pages)]
    edited = _view()
    edited["sections"][0]["paragraphs"][0]["sentences"][0].update({"text": "고친 문장이다.", "edited": True})
    other, _ = render_pdf(outline=_outline(edited), font_sha256=font_sha256)
    assert hashlib.sha256(other).hexdigest() != hashlib.sha256(first).hexdigest()
    later = deepcopy(_view())
    assert render_pdf(outline=_outline(later, created_at=datetime(2026, 10, 19, tzinfo=timezone.utc)),
                      font_sha256=font_sha256)[0] != first
