"""심층 검토 화면 시안 공통 조각. 재설계 C 아트보드(PreSpecDetail.dc.html)의 helmet·사이드바를 그대로 쓴다."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = (ROOT / "0915_ui-redesign/mockups/artboards/PreSpecDetail.dc.html").read_text(encoding="utf-8")
HELMET = re.search(r"<helmet>.*?</helmet>", BASE, re.S).group(0)
ASIDE = re.search(r"<aside.*?</aside>", BASE, re.S).group(0)

EXTRA_CSS = """
    .tok-gray { background:#eef0ec; color:#3c4640; }
    .tok-strong { background:#3f5a1c; color:#ffffff; }
    .sev { display:inline-flex; align-items:center; height:20px; padding:0 8px; border-radius:5.25px; font-size:12px; font-weight:600; white-space:nowrap; }
    .sev-block { background:#facecb; color:#89001a; }
    .sev-major { background:#fad0b5; color:#6e3500; }
    .sev-normal { background:#f8da9d; color:#584400; }
    .sev-low { background:#eef0ec; color:#3c4640; }
    .bar { position:relative; height:6px; border-radius:999px; background:#eef0ec; overflow:hidden; }
    .bar > span { position:absolute; left:0; top:0; bottom:0; border-radius:999px; background:#75a03b; }
    .hdr { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #eef0ec; }
    .body { display:flex; flex-direction:column; gap:14px; padding:16px 22px 20px; }
    .mono { font-family:ui-monospace,Menlo,monospace; font-size:12px; color:#79837c; }
    .skel { height:12px; border-radius:6px; background:#eef0ec; }
    .tile { display:flex; flex-direction:column; gap:4px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4; }
    .li { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid #eef0ec; font-size:14px; line-height:1.45; }
    .hl { background:#f1f6e8; box-shadow:inset 0 -2px 0 #75a03b; color:#1b211d; }
"""


def helmet():
    return HELMET.replace("</style>", EXTRA_CSS + "  </style>", 1)


def icon(name, color="#4c5650", size=14, width=1.8):
    paths = {
        "check": '<path d="m5 12 4 4L19 7"></path>',
        "chev": '<path d="m9 6 6 6-6 6"></path>',
        "ext": '<path d="M14 4h6v6M20 4l-9 9"></path><path d="M20 14v6H4V4h6"></path>',
        "doc": '<path d="M6 3h9l4 4v14H6z"></path><path d="M14 3v5h5"></path>',
        "alert": '<path d="M12 4 2.5 20h19z"></path><path d="M12 10v4M12 17.5v.5"></path>',
        "clock": '<circle cx="12" cy="12" r="8.5"></circle><path d="M12 7.5V12l3 2"></path>',
        "dot": '<circle cx="12" cy="12" r="3"></circle>',
        "x": '<path d="M6 6l12 12M18 6 6 18"></path>',
        "retry": '<path d="M4 12a8 8 0 1 0 2.4-5.7"></path><path d="M4 4v5h5"></path>',
        "spin": '<path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5"></path>',
        "lock": '<rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path>',
    }
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>')


def crumbs(*parts):
    out = []
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        if i:
            out.append(icon("chev", "#9aa39c", 12, 2))
        out.append(f'<span style="color:{"#1b211d" if last else "#4c5650"};{" font-weight:600;" if last else ""}">{p}</span>')
    return '<div style="display:flex; align-items:center; gap:6px; font-size:12px;">' + "".join(out) + "</div>"


def page(height, crumb_parts, right_html, cards_html, max_width=1040):
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
{helmet()}
<div style="display:flex; width:1422px; min-height:{height}px; box-sizing:border-box; background:#f6f7f4; overflow:hidden; align-items:stretch;">
{ASIDE}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  <header style="display:flex; align-items:center; justify-content:space-between; gap:16px; height:76px; box-sizing:border-box; padding:12px 18px; background:#f6f7f4;">
    {crumbs(*crumb_parts)}
    <div style="display:flex; align-items:center; gap:12px;">{right_html}</div>
  </header>
  <main style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:12px 18px 40px; background:#f6f7f4;">
    <div style="display:flex; width:100%; flex-direction:column; align-items:center;"><div style="display:flex; width:100%; max-width:{max_width}px; flex-direction:column; gap:16px; padding-top:8px;">
{cards_html}
    </div></div>
  </main>
</div>
</div>
</x-dc>
</body>
</html>
"""


# ---- 사전규격 상세 공통 카드 -------------------------------------------------

def nav_right():
    return ('<span class="cap2">선택 항목 <b style="font-weight:600; color:#1b211d;">1 / 2</b></span>'
            f'<div class="btn btn-disabled" style="gap:4px;">{icon("chev", "#9aa39c", 14, 2).replace("m9 6 6 6-6 6", "m15 6-6 6 6 6")}이전</div>'
            f'<div class="btn btn-outline" style="gap:4px;">다음{icon("chev", "#1b211d", 14, 2)}</div>')


def detail_header(status_chip):
    facts = [
        ("사업 예산", "49,844,864원", "부가세 포함"),
        ("의견등록 마감", '2026.09.18 23:59 <span class="dday">D-2</span>', "KST"),
        ("게시", "2026.09.11 10:49", "KST"),
        ("구분", "일반용역", "SW사업대상 Y"),
        ("적합성 등급", '<span class="tok tok-accent" style="height:24px; font-size:13px;">검토 권장</span>', "등급 출처 · 판정"),
        ("첨부 원문", "3건", "본문 추출 2 · 실패 1"),
    ]
    cells = "".join(
        f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px;{" border-right:1px solid #eef0ec;" if i < 5 else ""}">'
        f'<span class="cap">{k}</span><span style="font-size:17px; font-weight:600; line-height:1.3; color:#1b211d;">{v}</span><span class="cap">{c}</span></div>'
        for i, (k, v, c) in enumerate(facts))
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="kv" style="gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
            <div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-outline">사전규격 · 신규</span><span class="tok tok-accent">D-2</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-outline">본공고 미확인</span><span class="tok tok-outline">일반용역</span>{status_chip}</div>
            <div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-outline">추적 결정 · 미선택</span><a href="#" class="cap2">목록으로 돌아가기</a></div>
          </div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2"><span style="font-size:14px; color:#1b211d;">한국예술인복지재단</span><span style="color:#c9cfc3;">·</span><span>사전규격번호 <b style="font-weight:600; color:#1b211d; font-size:14px;">R26BD00273769</b></span><span style="color:#c9cfc3;">·</span><span>품명 분류 · 정보화 전략 수립 컨설팅</span></div>
          <div style="display:flex; gap:12px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;"><span class="tok tok-accent" style="flex:0 0 auto;">사업 요약</span><p style="font-size:14px; line-height:1.55;">예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다. <a href="#" style="font-size:12px;">근거 · 제안요청서 p.3</a></p></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); border-top:1px solid #eef0ec;">{cells}</div>
      </section>
"""


def tracking_card(extra_line=""):
    return f"""      <section class="card" style="display:flex; flex-direction:column; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #e6ecdc; background:#f9fbf5; border-radius:14px 14px 0 0;"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">추적 결정</h2><span class="cap2">추적 시작 → <b style="font-weight:600; color:#1b211d;">계속 추적</b></span></div><span class="cap">보류·추적 종료는 <a href="#">사업 추적</a>에서 변경</span></div>
        {extra_line}
        <div style="display:grid; grid-template-columns: minmax(0,1.4fr) minmax(0,1fr) auto; gap:12px; align-items:end; padding:16px 22px;">
          <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">선택 사유 <span class="cap">· 필수</span></span><div class="field" style="justify-content:space-between; height:36px;"><span>추적을 시작하는 사유를 선택하세요</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#79837c" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg></div></div>
          <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div></div>
          <div class="btn btn-primary" style="height:36px; padding:0 20px;">추적 시작</div>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 22px 14px;" class="cap"><span>추적을 시작하면 새 문서·입찰공고·정정공고를 계속 확인합니다.</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</span></div>
      </section>
"""


def tasks_card():
    items = [
        ("현행 공제사업 시스템 현황 분석", "창작준비금·예술인 산재보험·긴급복지 3개 시스템의 업무 절차, 데이터 구조, 연계 현황을 조사한다.", "p.4"),
        ("통합관리시스템 목표 모델·정보화 전략 수립", "기능·데이터·연계 아키텍처를 정의하고 외부 기관 연계 방안을 제시한다.", "p.5"),
        ("3개년 단계별 이행 계획과 소요 예산 산정", "단계별 구축 범위, 일정, 예산과 발주 방안을 도출한다.", "p.6"),
    ]
    lis = "".join(
        f'<li style="display:grid; grid-template-columns: 24px minmax(0,1fr) auto; gap:10px; align-items:start; padding:10px 0; border-bottom:1px solid #eef0ec;"><span style="display:flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:#f1f6e8; color:#3f5a1c; font-size:12px; font-weight:600;">{i+1}</span><div class="kv"><span style="font-size:14px; font-weight:600; line-height:1.45;">{t}</span><span style="font-size:14px; line-height:1.5; color:#4c5650;">{d}</span></div><a href="#" style="font-size:12px; white-space:nowrap;">제안요청서 {p}</a></li>'
        for i, (t, d, p) in enumerate(items))
    tiles = "".join(
        f'<div class="tile"><span class="cap">{k}</span><span style="font-size:14px; font-weight:600; color:#1b211d;">{v}</span><span class="cap2">{s}</span></div>'
        for k, v, s in [("사업 규모", "49,844,864원 (부가세 포함)", "제안요청서 p.4"), ("사업 기간", "계약 체결일로부터 6개월", "제안요청서 p.4")])
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">주요 과업과 수행 범위</h2><span class="cap">개요 검토 · 사업 개요·주요 과업·예산 기간</span></div><div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-accent">주장 검증 완료 · 운영 승인 아님</span><a href="#" style="font-size:12px;">전체 근거 PDF 열기 ↗</a></div></div>
        <div class="body"><ol style="display:flex; flex-direction:column;">{lis}</ol><div class="cap">사업 규모와 일정</div><div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:12px;">{tiles}</div><span class="cap">개요 입력 범위 3~6쪽 · 목차에서 `Ⅰ. 사업 개요` 장을 찾아 자동 선택</span></div>
      </section>
"""


def evidence_collapsed():
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr" style="border-bottom:0;"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">근거 문서 · 첨부</h2><span class="cap">첨부 3건 · 본문 추출 2 · 실패 1</span></div><a href="#" style="font-size:12px;">펼치기</a></div>
      </section>
"""


def step(num, title, chip, cap, state):
    if state == "done":
        box = "border:1px solid #cfdfb5; background:#f9fbf5;"
        badge = "background:#75a03b; color:#ffffff;"
    elif state == "running":
        box = "border:1px solid #75a03b; background:#ffffff; box-shadow:0 0 0 3px #f1f6e8;"
        badge = "background:#ffffff; color:#3f5a1c; box-shadow:inset 0 0 0 1.5px #75a03b;"
    else:
        box = "border:1px solid #eef0ec; background:#ffffff;"
        badge = "background:#eef0ec; color:#4c5650;"
    return (f'<div class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; {box}"><div style="display:flex; align-items:center; gap:8px;">'
            f'<span style="display:flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; {badge} font-size:12px; font-weight:600;">{num}</span>'
            f'<span style="font-size:14px; font-weight:600;">{title}</span></div>{chip}<span class="cap2">{cap}</span></div>')


def timeline(rows):
    lis = "".join(
        f'<li style="display:grid; grid-template-columns: 148px 10px minmax(0,1fr); gap:12px; align-items:start; padding:8px 0; border-bottom:1px solid #eef0ec;"><span class="cap2">{t}</span><span style="width:8px; height:8px; border-radius:50%; margin-top:6px; background:{c};"></span><div class="kv"><span style="font-size:14px; font-weight:600;">{h}</span><span class="cap2">{d}</span></div></li>'
        for t, c, h, d in rows)
    return f'<div class="kv" style="gap:6px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">처리 이력</span><div style="display:flex; gap:12px;"><a href="#" style="font-size:12px;">사업기회 보기 →</a></div></div><ul style="display:flex; flex-direction:column;">{lis}</ul></div>'
