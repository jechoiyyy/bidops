#!/usr/bin/env python3
"""시안 아트보드 생성기.

참고 시안(artifact 0677620a)에서 뽑아낸 실제 Astryx 렌더 결과를 재료로 쓴다.
  Astryx core CSS      설치된 0.5.2 reset + base
  neutral.css          0단계에서 저장소에 고정한 neutral 테마 빌드 산출물
  bo-skeleton.css      현행 BidOps 페이지 골격 (ADR-0040: 레이아웃은 프로젝트 소유)
  astryx-classes.json  컴포넌트별 실제 class 문자열

서체는 ADR-0039 §5에 따라 Pretendard를 앞에 둔다. 캔버스 뷰어에 Pretendard가
설치돼 있지 않으면 system-ui로 대체되지만, 운영은 자체 호스팅한 woff2를 쓴다.
"""
import json
import os
import pathlib
import re

HERE = pathlib.Path(__file__).parent
CLASSES = json.loads((HERE / "astryx-classes.json").read_text(encoding="utf-8"))
FRONTEND_ROOT = pathlib.Path(
    os.environ.get("BIDOPS_FRONTEND_ROOT", HERE.parents[2] / "web" / "frontend")
)
ASTRYX_CSS = "\n".join(
    path.read_text(encoding="utf-8")
    for path in (
        FRONTEND_ROOT / "node_modules" / "@astryxdesign" / "core" / "src" / "reset.css",
        FRONTEND_ROOT / "node_modules" / "@astryxdesign" / "core" / "dist" / "astryx.css",
        FRONTEND_ROOT / "src" / "themes" / "neutral" / "neutral.css",
    )
)
SKELETON_CSS = (HERE / "bo-skeleton.css").read_text(encoding="utf-8")

FONT_OVERRIDE = """
/* ===== 운영 서체: ADR-0039 §5 — Pretendard 자체 호스팅 ===== */
[data-astryx-theme="neutral"] {
  --font-family-body: Pretendard, system-ui, sans-serif;
  --font-family-heading: Pretendard, system-ui, sans-serif;
  --font-family-code: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
    "Liberation Mono", "Courier New", monospace;
}
body { margin: 0; }

/* ===== 등급 전용 4단 스케일 =====
   등급 4값은 심각도가 아니라 우선순위 순서다. Astryx 의미색(error/warning/success)에
   실으면 "제외"가 위험으로, "우선 검토"가 성공으로 읽힌다. accent 한 색의 농도 4단으로
   순서만 나타내고, 색은 토큰에서 파생한다. */
.bo-grade-seg.is-g1, .bo-grade-swatch.is-g1 { background: var(--color-accent); }
.bo-grade-seg.is-g2, .bo-grade-swatch.is-g2 {
  background: color-mix(in srgb, var(--color-accent) 72%, var(--color-background-card)); }
.bo-grade-seg.is-g3, .bo-grade-swatch.is-g3 {
  background: color-mix(in srgb, var(--color-accent) 44%, var(--color-background-card)); }
.bo-grade-seg.is-g4, .bo-grade-swatch.is-g4 {
  background: color-mix(in srgb, var(--color-accent) 18%, var(--color-background-card)); }
.bo-grade-seg.is-g3 .bo-grade-seg-count,
.bo-grade-seg.is-g4 .bo-grade-seg-count { color: var(--color-text-primary); }

/* 등급 배지도 같은 스케일을 쓴다. Astryx badge 위에 덧씌우지 않고 별도 클래스로 둔다. */
.bo-grade-tag { display:inline-flex; align-items:center; gap:6px; padding:2px 9px;
  border-radius:999px; font-size:12px; font-weight:600; line-height:20px;
  border:1px solid var(--color-border); }
.bo-grade-tag.is-g1 { background:var(--color-accent); color:var(--color-on-accent); border-color:var(--color-accent); }
.bo-grade-tag.is-g2 { background:color-mix(in srgb, var(--color-accent) 72%, var(--color-background-card)); color:var(--color-on-accent); }
.bo-grade-tag.is-g3 { background:color-mix(in srgb, var(--color-accent) 44%, var(--color-background-card)); color:var(--color-text-primary); }
.bo-grade-tag.is-g4 { background:color-mix(in srgb, var(--color-accent) 18%, var(--color-background-card)); color:var(--color-text-primary); }
.bo-grade-tag.is-none { background:var(--color-background-muted); color:var(--color-text-secondary);
  border-style:dashed; }

/* ===== pane 스크롤 격리 =====
   참고 시안의 골격은 정적 캡처용이라 목록·상세가 셸 밖으로 자라도 그냥 잘린다.
   실제 화면은 pane마다 스크롤을 가둬야 결정 액션이 상세 pane 바닥에 붙어
   스크롤 위치와 무관하게 첫 화면에서 보인다(PLAN 4단계 완료 게이트). */
.bo-canvas { min-height: 0; overflow-y: auto; }
.bo-canvas:has(.bo-workspace) { display: flex; flex-direction: column; overflow: hidden; }
.bo-queue { flex: 1 1 auto; min-height: 0; height: auto; }
.bo-workspace { flex: 1 1 auto; min-height: 0; }
.bo-list-scroll, .bo-detail-scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
"""


def _disabled_atoms():
    """비활성 상태를 그리는 StyleX 원자 클래스를 CSS에서 직접 찾는다.

    참고 시안에는 같은 버튼의 활성/비활성 두 벌이 들어 있고 비활성 쪽이 더 짧다.
    이름만 보고는 구분할 수 없으므로 선언 내용으로 가려낸다.
    """
    found = set()
    for m in re.finditer(r"\.(x[0-9a-z]+)(?::not\(#\\#\))+\{([^}]*)\}", ASTRYX_CSS):
        decl = m.group(2).replace(" ", "")
        if "opacity:.5" in decl or "pointer-events:none" in decl:
            found.add(m.group(1))
    return found


DISABLED_ATOMS = _disabled_atoms()


def cls(comp, *want):
    """comp의 class 문자열 중 want 낱말을 모두 가진 것을 고른다.

    후보가 여럿이면 원자 클래스가 가장 적은 것을 고른다. 참고 시안에는 같은
    컴포넌트의 옵션 조합이 여러 벌 들어 있고, 앞에서부터 찾으면 옵션이 붙은 쪽을
    집는다. 예를 들어 Text body/primary의 첫 후보는 `<Text truncate>`라서
    overflow:hidden·text-overflow:ellipsis·white-space:nowrap이 붙어 있고,
    표 셀에 쓰면 내용이 한 줄로 잘린다. 기본은 옵션 없는 쪽이어야 한다.
    """
    cands = CLASSES[comp]
    matches = [c for _tag, c in cands if all(w in c.split() for w in want)]
    enabled = [c for c in matches if not (set(c.split()) & DISABLED_ATOMS)]
    pool = enabled or matches
    if pool:
        return min(pool, key=lambda c: len(c.split()))
    raise KeyError(f"{comp} {want} 없음 — 후보 {[' '.join(c.split()[:3]) for _, c in cands]}")


def text(s, kind="body", color="primary", extra=""):
    c = cls("astryx-text", kind, color)
    return f'<span class="{c}{extra}" data-type="{kind}" data-color="{color}">{s}</span>'


def heading(s, level=3):
    c = cls("astryx-heading", f"level-{level}")
    return f'<h{level} class="{c}" data-level="{level}" data-color="primary">{s}</h{level}>'


def badge(s, variant="neutral", title=None):
    c = cls("astryx-badge", variant)
    t = f' title="{title}"' if title else ""
    return f'<span class="{c}" data-variant="{variant}"{t}>{s}</span>'


def button(s, variant="secondary", disabled=False):
    c = cls("astryx-button", variant, "sm")
    if disabled:
        c += " " + " ".join(sorted(DISABLED_ATOMS))
    disabled_attrs = ' disabled aria-disabled="true"' if disabled else ""
    return (
        f'<button type="button" class="{c}" data-variant="{variant}"'
        f' data-size="sm" data-elevation="none"{disabled_attrs}>{s}</button>'
    )


GRADE_STEP = {"우선 검토": "g1", "검토 권장": "g2", "관찰 대상": "g3", "제외": "g4"}


def grade_tag(value):
    """등급 4값 전용. 의미색 대신 accent 농도 4단으로 순서를 보인다."""
    step = GRADE_STEP.get(value, "none")
    return f'<span class="bo-grade-tag is-{step}">{value}</span>'


def stack(children, direction="vertical", gap=2, extra=""):
    c = cls("astryx-stack", direction, f"gap-{gap}")
    return (
        f'<div class="{c}{extra}" data-direction="{direction}" data-gap="{gap}">'
        + "".join(children)
        + "</div>"
    )


def status_dot(label, variant="warning"):
    c = cls("astryx-status-dot")
    c = c.replace("astryx-status-dot warning", f"astryx-status-dot {variant}")
    return f'<span role="img" aria-label="{label}" class="{c}" data-variant="{variant}"></span>'


def link(s, href="#"):
    c = cls("astryx-link")
    return f'<a href="{href}" class="{c}" data-color="accent">{s}</a>'


def divider():
    c = cls("astryx-divider")
    return f'<div role="separator" aria-orientation="horizontal" class="{c}" data-variant="subtle" data-orientation="horizontal"></div>'


def selector(value, width="150px"):
    fc = cls("astryx-field")
    lc = cls("astryx-field-label")
    sc = cls("astryx-selector")
    ic = cls("astryx-icon")
    return (
        f'<div class="{fc}"><label class="{lc}">'
        f'<div class="{sc}" data-variant="input" data-size="sm" style="min-width:{width}">'
        f"{text(value, 'body', 'primary')}"
        f'<span aria-hidden="true" data-state="collapsed" class="{ic}" data-size="sm" data-color="secondary">▾</span>'
        f"</div></label></div>"
    )


def text_input(placeholder, width="190px"):
    fc = cls("astryx-field")
    lc = cls("astryx-field-label")
    tc = cls("astryx-text-input")
    return (
        f'<div class="{fc}"><label class="{lc}">'
        f'<div class="{tc}" data-size="sm" style="min-width:{width}">'
        f"{text(placeholder, 'body', 'secondary')}</div></label></div>"
    )


def segmented(items, selected_index=0):
    """SegmentedControl을 그린다. selected_index=None이면 미선택 상태다."""
    sc = cls("astryx-segmented-control")
    on = cls("astryx-segmented-control-item", "selected")
    # "md"는 선택된 쪽에도 있으므로 낱말만으로 고르면 둘 다 selected가 된다.
    off = next(
        c for _t, c in CLASSES["astryx-segmented-control-item"]
        if "selected" not in c.split()
    )
    parts = []
    for i, label in enumerate(items):
        c = on if i == selected_index else off
        parts.append(f'<button type="button" class="{c}" data-size="md">{label}</button>')
    return f'<div class="{sc}" role="group">' + "".join(parts) + "</div>"


def table(headers, rows, selected=None, min_width=520):
    wc = cls("astryx-table-scroll-wrapper")
    tc = cls("astryx-table")
    hc = cls("astryx-table-header")
    bc = cls("astryx-table-body")
    rc = cls("astryx-table-row")
    rc_sel = next(c for _t, c in CLASSES["astryx-table-row"] if "xoevpu5" in c)
    thc = cls("astryx-table-header-cell")
    tdc = cls("astryx-table-cell")

    # 참고 시안의 실제 방식: 고정 열은 width와 min-width를 같은 값으로 함께 주고,
    # 늘어나는 열 하나만 width:100%를 갖는다. 둘 중 하나만 주면 열이 눌리거나 밀려난다.
    cells = []
    flex_used = False
    for h, w in headers:
        if w:
            style = f"width:{w};min-width:{w}"
        elif not flex_used:
            style, flex_used = "width:100%;min-width:120px", True
        else:
            style = "width:150px;min-width:150px"
        cells.append(
            f'<th scope="col" class="{thc}" data-density="balanced" style="{style}">'
            + text(h, "label", "secondary")
            + "</th>"
        )
    head_cells = "".join(cells)
    body_rows = []
    for i, cells in enumerate(rows):
        r = rc_sel if selected == i else rc
        tds = "".join(f'<td class="{tdc}" data-density="balanced">{c}</td>' for c in cells)
        body_rows.append(f'<tr class="{r}">{tds}</tr>')
    return (
        f'<div tabindex="0" role="group" aria-label="Table" class="{wc}">'
        f'<table class="{tc}" style="min-width:{min_width}px">'
        f'<thead class="{hc}"><tr class="{rc}">{head_cells}</tr></thead>'
        f'<tbody class="{bc}">' + "".join(body_rows) + "</tbody></table></div>"
    )


# ---------------------------------------------------------------- 공통 셸

NAV = [
    ("회차 검토", [("대시보드", None), ("검토 대기열", None)]),
    ("누적 추적", [("발주계획 C-2", None), ("사전규격", None), ("사업기회", None), ("최종 Go/No-Go", None)]),
    ("기준과 운영", [("판정 기준", None), ("실행 상태", None)]),
]


def sidebar(current):
    groups = []
    for label, items in NAV:
        rows = []
        for name, pending in items:
            active = " is-active" if name == current else ""
            tag = f'<span class="bo-nav-pending">{pending}</span>' if pending else ""
            rows.append(f'<span class="bo-nav-item{active}"><span class="bo-nav-dot"></span>{name}{tag}</span>')
        groups.append(
            f'<div class="bo-nav-group"><span class="bo-nav-group-label">{label}</span>'
            + "".join(rows)
            + "</div>"
        )
    return (
        '<aside class="bo-sidebar">'
        '<div class="bo-brand"><span class="bo-brand-mark">B</span>'
        '<span class="bo-brand-text"><strong>BidOps</strong><span>ROOTLAB · 사업기회</span></span></div>'
        f'<nav class="bo-nav">{"".join(groups)}</nav>'
        '<div class="bo-sidebar-foot">기획부 · 사업기획<br>관리자 화면</div>'
        "</aside>"
    )


def topbar(title, context_html, status_html=""):
    return (
        f'<header class="bo-topbar">{heading(title, 4)}'
        f'<span class="bo-topbar-context">{context_html}</span>'
        f"{status_html}</header>"
    )


def screen(current_nav, topbar_html, content_html):
    return (
        '<div class="xjp7ctv x1tgivj0 x9ynric x19aimcq" data-astryx-theme="neutral" data-theme="light">'
        f'<section class="bo-shell">{sidebar(current_nav)}'
        f'<div class="bo-content">{topbar_html}{content_html}</div>'
        "</section></div>"
    )


def artboard(path, body, width, height):
    css = ASTRYX_CSS + "\n" + SKELETON_CSS + "\n" + FONT_OVERRIDE
    css += f"\n.bo-shell {{ width: {width}px; height: {height}px; min-height: {height}px; }}\n"
    doc = (
        "<!doctype html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n"
        '  <script src="./support.js"></script>\n</head>\n<body>\n<x-dc>\n'
        f"<helmet>\n  <style>\n{css}\n  </style>\n</helmet>\n{body}\n</x-dc>\n</body>\n</html>\n"
    )
    (HERE / path).write_text(doc, encoding="utf-8")
    return len(doc)
