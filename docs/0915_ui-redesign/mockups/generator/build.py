# Generates Main.dc.html (목록), PreSpecDetail.dc.html (상세), StatusVocabulary.dc.html
import pathlib
OUT = pathlib.Path(__file__).parent

FONT_LINK = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&amp;display=swap">'

BASE_CSS = """
    :root { --bg:#ffffff; --surface:#ffffff; --muted-surface:#f6f7f4; --border:#e2e5df; --border-strong:#c9cfc3;
      --text:#1b211d; --text-2:#4c5650; --text-3:#79837c; --disabled:#9aa39c;
      --accent:#75a03b; --accent-strong:#587a2b; --accent-deep:#3f5a1c; --accent-soft:#f1f6e8; --accent-edge:#cfdfb5; --accent-row:#f4f8ee;
      --red-bg:#facecb; --red-text:#89001a; --orange-bg:#fad0b5; --orange-text:#6e3500; --yellow-bg:#f8da9d; --yellow-text:#584400;
      --gray-bg:#eef0ec; --gray-text:#3c4640; }
    body { margin:0; background:#ffffff; color:#1b211d; font-family:"Pretendard","Noto Sans KR",system-ui,sans-serif; font-size:14px; line-height:1.5; font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased; }
    a { color:#587a2b; text-decoration:none; } a:hover { color:#3f5a1c; text-decoration:underline; }
    h1,h2,h3,h4,p,dl,dd,dt,ul,ol { margin:0; }
    ul,ol { padding:0; list-style:none; }
    svg { display:block; flex-shrink:0; }
    .nav-item { display:flex; align-items:center; gap:12px; min-height:36px; padding:8px 12px; border-radius:5.25px; font-size:14.25px; }
    .btn { display:inline-flex; align-items:center; justify-content:center; gap:8px; height:28px; padding:0 12px; border-radius:8.75px; font-size:12px; font-weight:500; line-height:1.45; white-space:nowrap; border:0; }
    .btn-primary { background:#587a2b; color:#ffffff; }
    .btn-secondary { background:#f1f6e8; color:#3f5a1c; }
    .btn-ghost { background:transparent; color:#1b211d; }
    .btn-outline { background:#ffffff; color:#1b211d; box-shadow:inset 0 0 0 1px #e2e5df; }
    .btn-disabled { background:#eef0ec; color:#9aa39c; }
    .tok { display:inline-flex; align-items:center; height:20px; padding:0 8px; border-radius:5.25px; font-size:12px; font-weight:500; line-height:1; white-space:nowrap; background:#eef0ec; color:#3c4640; }
    .tok-accent { background:#f1f6e8; color:#3f5a1c; }
    .tok-red { background:#facecb; color:#89001a; }
    .tok-orange { background:#fad0b5; color:#6e3500; }
    .tok-yellow { background:#f8da9d; color:#584400; }
    .tok-outline { background:#ffffff; color:#4c5650; box-shadow:inset 0 0 0 1px #e2e5df; }
    .cap { font-size:12px; line-height:1.45; color:#79837c; }
    .cap2 { font-size:12px; line-height:1.45; color:#4c5650; }
    .sec-title { font-size:14px; line-height:1.4; font-weight:600; color:#1b211d; }
    .card { background:#ffffff; border:1px solid #e2e5df; border-radius:10.5px; }
    .dday { font-size:12px; font-weight:600; color:#587a2b; }
    .dday-passed { color:#89001a; }
    .field { display:flex; align-items:center; height:32px; padding:0 12px; border-radius:8.75px; border:1px solid #c9cfc3; background:#ffffff; font-size:14px; color:#79837c; }
    .check { width:16px; height:16px; border-radius:4px; border:1px solid #c9cfc3; background:#ffffff; flex-shrink:0; }
    .check-on { background:#75a03b; border-color:#75a03b; }
"""

ICON = {
 "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect>',
 "order-plan": '<path d="M5 4h14v16H5z"></path><path d="M8 8h8M8 12h8M8 16h5"></path><path d="M8 4V2M16 4V2"></path>',
 "judgment": '<path d="M6 3h9l4 4v14H6z"></path><path d="M14 3v5h5M9 13h7M9 17h5"></path>',
 "queue": '<path d="M4 6h16M4 12h16M4 18h9"></path>',
 "policy": '<path d="M6 3h9l4 4v14H6z"></path><path d="M14 3v5h5M9 13h7M9 17h5"></path>',
 "operations": '<path d="M4 17h3l2-10 4 14 2-8h5"></path>',
}
def icon(name, size=18, color="currentColor", sw=1.7):
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>'

def svg(path, size=16, color="currentColor", sw=1.7):
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{path}</svg>'

I_SEARCH = '<circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path>'
I_FILTER = '<path d="M4 6h16M7 12h10M10 18h4"></path>'
I_CHEV_D = '<path d="m6 9 6 6 6-6"></path>'
I_CHEV_R = '<path d="m9 6 6 6-6 6"></path>'
I_CHEV_L = '<path d="m15 6-6 6 6 6"></path>'
I_ARROW_R = '<path d="M5 12h14M13 6l6 6-6 6"></path>'
I_EXT = '<path d="M14 4h6v6M20 4l-9 9"></path><path d="M20 14v6H4V4h6"></path>'
I_COPY = '<rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a1 1 0 0 1 1-1h10"></path>'
I_ALERT = '<path d="M12 3 2 20h20z"></path><path d="M12 9v5M12 17h.01"></path>'
I_INFO = '<circle cx="12" cy="12" r="9"></circle><path d="M12 11v5M12 8h.01"></path>'
I_CHECK = '<path d="m5 12 4 4L19 7"></path>'
I_DOC = '<path d="M6 3h9l4 4v14H6z"></path><path d="M14 3v5h5"></path>'
I_DOWNLOAD = '<path d="M12 4v11M7 10l5 5 5-5"></path><path d="M4 20h16"></path>'
I_LEAF = '<path d="M5 19c0-7 4-13 14-14 0 10-5 14-12 14"></path><path d="M5 19c3-4 6-7 10-9"></path>'

def sidebar(active):
    def item(label, key, act):
        style = "background: {{sb.activeBg}}; color: {{sb.activeText}}; font-weight:600; box-shadow: inset 3px 0 0 #75a03b;" if act else "color: {{sb.text}};"
        return f'<a class="nav-item" href="#" style="{style}">{icon(key)}<span>{label}</span></a>'
    def group(label, items):
        lis = "".join(item(l, k, l == active) for l, k in items)
        return f'''<div style="display:flex; flex-direction:column; padding-top:12px;">
        <div style="padding:0 12px 8px; font-size:12px; font-weight:500; letter-spacing:.08em; color: {{{{sb.group}}}};">{label}</div>
        <div style="display:flex; flex-direction:column; gap:2px;">{lis}</div></div>'''
    return f'''<aside style="display:flex; flex-direction:column; flex:0 0 248px; width:248px; height:100%; box-sizing:border-box; background: {{{{sb.bg}}}}; border-right:1px solid {{{{sb.border}}}};">
  <div style="display:flex; align-items:center; gap:12px; padding:16px 16px 12px; border-bottom:1px solid {{{{sb.border}}}};">
    <div style="display:flex; align-items:center; justify-content:center; width:40px; height:40px; border-radius:8.75px; background:#75a03b;">{svg(I_LEAF, 22, "#ffffff", 1.8)}</div>
    <div style="display:flex; flex-direction:column; gap:2px;">
      <div style="font-size:14.88px; font-weight:600; line-height:1.3; color: {{{{sb.brand}}}};">BidOps</div>
      <div style="font-size:12px; line-height:1.3; color: {{{{sb.group}}}};">ROOTLAB · 사업기회 모니터링</div>
    </div>
  </div>
  <nav style="display:flex; flex-direction:column; padding:4px 12px 24px; flex:1 1 auto;">
    {group("오늘의 업무", [("대시보드","dashboard")])}
    {group("탐색과 추적", [("발주계획","order-plan"),("사전규격","judgment"),("사업 추적","queue"),("최종 Go/No-Go","judgment")])}
    {group("기준과 운영", [("판정 기준","policy"),("실행 상태","operations")])}
  </nav>
  <div style="display:flex; flex-direction:column; gap:4px; padding:16px 20px 20px; border-top:1px solid {{{{sb.border}}}}; font-size:12px; color: {{{{sb.group}}}};">
    <span>기획부 · 사업기획</span><span>관리자 화면</span>
  </div>
</aside>'''

SIDEBAR_SCRIPT = """<script data-dc-script data-props='{"sidebar":{"editor":"enum","options":["light","dark"],"default":"light","section":"Shell"}}'>
class Component extends DCLogic {
  renderVals() {
    const dark = (this.props.sidebar ?? 'light') === 'dark';
    return { sb: dark
      ? { bg:'#1f2a17', border:'rgba(255,255,255,0.08)', text:'#d9e2cf', group:'rgba(217,226,207,0.62)', brand:'#ffffff', activeBg:'rgba(117,160,59,0.22)', activeText:'#ffffff' }
      : { bg:'#ffffff', border:'#e2e5df', text:'#4c5650', group:'#79837c', brand:'#1b211d', activeBg:'#f1f6e8', activeText:'#3f5a1c' } };
  }
}
</script>"""

def topbar(left_html, right_html=""):
    return f'''<header style="display:flex; align-items:center; justify-content:space-between; gap:16px; height:76px; box-sizing:border-box; padding:12px 18px; background:#ffffff; border-bottom:1px solid #e2e5df;">
  {left_html}
  <div style="display:flex; align-items:center; gap:12px;">{right_html}</div>
</header>'''

def doc(title, body, extra_css="", script=SIDEBAR_SCRIPT, width=1422, height=889):
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  {FONT_LINK}
  <style>{BASE_CSS}{extra_css}
  </style>
</helmet>
{body}
</x-dc>
{script}
</body>
</html>'''

# ---------------------------------------------------------------- 목록 (Main)
def list_row(title, agency, meta, tokens, dday, date, checked=False, selected=False, two_line=False):
    bg = "background:#f4f8ee; box-shadow: inset 4px 0 0 #75a03b;" if selected else ""
    ck = "check check-on" if checked else "check"
    ckin = svg(I_CHECK, 12, "#ffffff", 3) if checked else ""
    toks = "".join(tokens)
    return f'''<div style="display:flex; align-items:flex-start; gap:8px; padding:8px 16px; border-bottom:1px solid #e2e5df; {bg}">
      <div class="{ck}" style="display:flex; align-items:center; justify-content:center; margin-top:3px;">{ckin}</div>
      <div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; gap:4px;">
        <div style="font-size:15px; font-weight:600; line-height:1.4; color:#1b211d;">{title}</div>
        <div style="font-size:14px; line-height:1.45; color:#4c5650;">{agency}</div>
        <div class="cap2">{meta}</div>
        <div style="display:flex; align-items:center; gap:6px;">{toks}</div>
      </div>
      <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px; flex:0 0 auto;">
        <span class="dday">{dday}</span><span class="cap2">{date}</span>
      </div>
    </div>'''

def main_page():
    tabs = [("전체","59",False),("개요 완료","8",True),("사람 확인","0",False),("진행·대기","51",False),("실패","0",False)]
    tab_html = "".join(
        f'<div style="display:flex; align-items:center; gap:6px; height:28px; padding:0 10px; border-radius:8.75px; font-size:12px; font-weight:{600 if a else 500}; background:{"#f1f6e8" if a else "transparent"}; color:{"#3f5a1c" if a else "#4c5650"};"><span>{l}</span><span style="font-variant-numeric:tabular-nums; color:{"#587a2b" if a else "#79837c"};">{n}</span></div>'
        for l,n,a in tabs)
    rows = "".join([
        list_row("예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","4,984.5만원 · 신규 · <b style='font-weight:600; color:#1b211d;'>검토 권장</b>",
                 ['<span class="tok tok-accent">완료</span>','<span class="tok tok-outline">미선택</span>'],"D-2","09.16",checked=True,selected=True),
        list_row("산업단지 데이터 통합 DBMS 구축 용역","한국산업단지공단","7,150만원 · 신규 · 판정 없음",
                 ['<span class="tok tok-accent">완료</span>','<span class="tok tok-outline">미선택</span>'],"D-2","09.16",checked=True),
        list_row("부산경찰청 정보화시스템 통합유지보수 용역","조달청 부산지방조달청","11.1억원 · 신규 · 판정 없음",
                 ['<span class="tok tok-accent">완료</span>','<span class="tok tok-outline">미선택</span>'],"D-2","09.16"),
        list_row("2027년 국가지식자원 통합 플랫폼 유지운영","조달청 서울지방조달청","1.9억원 · 신규 · 판정 없음",
                 ['<span class="tok tok-accent">완료</span>','<span class="tok tok-outline">미선택</span>'],"D-2","09.16"),
        list_row("[혁신G111_국고] 목원대학교 행정시스템 개선 및 고도화 용역 입찰","목원대학교","3.2억원 · 추적 · 관찰 대상",
                 ['<span class="tok tok-accent">완료</span>','<span class="tok tok-outline">계속 추적</span>'],"D-1","09.15"),
        list_row("차세대 통합 데이터 분석 플랫폼 구축","서울특별시 디지털정책관","예산 미확인 · 신규 · 판정 없음",
                 ['<span class="tok tok-orange">사람 검토 필요</span>','<span class="tok tok-outline">미선택</span>','<span class="cap2">첨부 차단 1</span>'],"D-4","09.18"),
    ])
    pane = f'''
<section style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:#ffffff;">
  <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px 12px; overflow:hidden;">
    <div style="display:flex; flex-direction:column; gap:6px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="display:flex; align-items:center; gap:8px;"><span class="cap">발주기관</span><span style="font-size:13px; font-weight:600; color:#1b211d;">한국예술인복지재단</span></div>
        <div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-outline">신규</span><span class="tok tok-outline">일반용역</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-accent">추적 결정 · 미선택</span></div>
      </div>
      <h3 style="font-size:20px; font-weight:600; line-height:1.35; color:#1b211d;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3>
      <div style="display:flex; align-items:center; gap:8px;" class="cap2"><span>사전규격 <b style="font-weight:600; color:#1b211d;">R26BD00273769</b></span><span>·</span><span>게시 2026. 9. 11. 오전 10:49</span><span>·</span><span>적합성 등급 <b style="font-weight:600; color:#1b211d;">검토 권장</b> (판정)</span></div>
    </div>

    <div style="display:flex; flex-direction:column; gap:4px;">
      <div class="cap" style="display:flex; align-items:center; gap:6px;"><span>사업 설명</span><span style="color:#c9cfc3;">·</span><span>개요 검토 결과 · 검증 통과</span></div>
      <p style="font-size:14px; line-height:1.55; color:#1b211d; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다.</p>
    </div>

    <div style="display:flex; flex-direction:column; gap:6px;">
      <div class="cap" style="display:flex; align-items:center; justify-content:space-between;"><span>주요 과업 요약</span><span>4건 중 3건 · 전체는 상세에서</span></div>
      <ol style="display:flex; flex-direction:column; gap:4px;">
        <li style="display:flex; gap:8px; font-size:14px; line-height:1.45;"><span style="flex:0 0 18px; font-weight:600; color:#587a2b;">1</span><span>현행 공제사업 3개 시스템 업무·데이터 현황 분석 및 이해관계자 요구 조사</span></li>
        <li style="display:flex; gap:8px; font-size:14px; line-height:1.45;"><span style="flex:0 0 18px; font-weight:600; color:#587a2b;">2</span><span>통합관리시스템 목표 모델과 정보화 전략 수립 (기능·데이터·연계 아키텍처)</span></li>
        <li style="display:flex; gap:8px; font-size:14px; line-height:1.45;"><span style="flex:0 0 18px; font-weight:600; color:#587a2b;">3</span><span>3개년 단계별 이행 계획과 소요 예산 산정, 사업 발주 방안 제시</span></li>
      </ol>
    </div>

    <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:8px;">
      <div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">사업 예산</span><span style="font-size:16px; font-weight:600; line-height:1.3;">49,844,864원</span></div>
      <div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">의견등록 마감</span><span style="font-size:16px; font-weight:600; line-height:1.3;">9.16 23:59 <span class="dday">D-2</span></span></div>
      <div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">사업 기간</span><span style="font-size:16px; font-weight:600; line-height:1.3;">착수 후 6개월</span></div>
      <div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">본공고 · 입찰 예정</span><span style="font-size:16px; font-weight:600; line-height:1.3; color:#79837c;">미확인</span></div>
    </div>

    <div style="display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8.75px; background:#fff8ec; border:1px solid #f0dcb0;">
      {svg(I_ALERT, 16, "#6e3500", 1.8)}
      <div style="display:flex; flex:1 1 auto; align-items:center; gap:8px; min-width:0; font-size:14px;"><span style="font-weight:600; color:#6e3500;">주의 1건</span><span style="flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#1b211d;">수행 인력 상주 조건이 근거 위치와 연결되지 않음 · 미확인 2 (사업 기간 · 입찰 예정)</span></div>
      <a href="#" style="font-size:12px; white-space:nowrap;">근거 보기 →</a>
    </div>
  </div>

  <div style="display:flex; flex-direction:column; gap:10px; padding:12px 18px 14px; border-top:1px solid #e2e5df; background:#ffffff;">
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
      <div style="display:flex; align-items:center; gap:8px;"><span class="sec-title">추적 결정</span><span class="cap2">현재 · 미선택 → 저장하면 계속 추적</span></div>
      <span class="cap">보류·추적 종료는 사업 추적에서 변경</span>
    </div>
    <div style="display:flex; align-items:center; gap:8px;">
      <div class="field" style="flex:1 1 auto; justify-content:space-between;"><span>추적을 시작하는 사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div>
      <div class="field" style="flex:0 0 168px;"><span>담당자 이름 (필수)</span></div>
      <div class="btn btn-primary" style="height:32px; flex:0 0 auto;">추적 시작</div>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
      <div class="cap2" style="display:flex; align-items:center; gap:6px;"><span class="cap">다음 작업</span><span style="font-weight:600; color:#1b211d;">추적 결정하기</span><span style="color:#c9cfc3;">·</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정</span></div>
      <a href="#" class="btn btn-outline" style="height:32px; gap:6px;">상세 페이지 열기 {svg(I_ARROW_R, 14, "#1b211d", 2)}</a>
    </div>
  </div>
</section>'''

    body = f'''<div style="display:flex; width:1422px; height:889px; box-sizing:border-box; background:#ffffff; overflow:hidden;">
{sidebar("사전규격")}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  {topbar('<h1 style="font-size:20px; font-weight:600; line-height:1.35; color:#1b211d;">사전규격</h1>', '<div class="btn btn-ghost">표시 범위</div>')}
  <main style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:16px 18px; background:#ffffff;">
    <div style="display:flex; flex-direction:column; gap:8px; padding:8px 12px; border:1px solid #e2e5df; border-radius:8.75px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="display:flex; align-items:center; gap:4px;">{tab_html}</div>
        <div style="display:flex; align-items:center; gap:8px;">
          <div class="field" style="width:264px; box-sizing:border-box; height:32px; gap:8px;">{svg(I_SEARCH, 16, "#79837c")}<span>사업명·기관명 검색</span></div>
          <div class="btn btn-outline" style="width:32px; height:32px; padding:0;">{svg(I_FILTER, 16, "#1b211d")}</div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:10px;">
        <div style="display:flex; align-items:center; gap:8px; height:28px; padding:0 8px; border-radius:5.25px; background:#f1f6e8; box-shadow: inset 0 0 0 1px #cfdfb5; font-size:12px; font-weight:600; color:#3f5a1c;"><div class="check check-on" style="width:14px; height:14px; display:flex; align-items:center; justify-content:center;">{svg(I_CHECK, 10, "#ffffff", 3)}</div>SW 중심 · 추적 예외 포함</div>
        <span class="cap">일반·기술용역 / SW사업대상 Y + 추적 예외</span>
      </div>
    </div>

    <div style="display:flex; flex:1 1 auto; min-height:0; border:1px solid #e2e5df; border-radius:10.5px; overflow:hidden;">
      <section style="display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid #e2e5df; background:#ffffff;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 16px; border-bottom:1px solid #e2e5df;">
          <span class="sec-title">사전규격 목록 <span style="color:#587a2b;">8건</span></span><span class="cap">개요 검토가 완료된 건</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px; padding:8px 16px; border-bottom:1px solid #e2e5df; background:#ffffff;">
          <span style="font-size:12px; font-weight:600; color:#1b211d; white-space:nowrap;">선택 2건</span>
          <div class="btn btn-outline">전체 선택</div>
          <div class="btn btn-outline">전체 해제</div>
          <div class="btn btn-primary">선택 항목 검토</div>
          <span class="cap" style="margin-left:auto; text-align:right;">현재 페이지 8건만 추가</span>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 16px; background:#f6f7f4; border-bottom:1px solid #e2e5df; font-size:12px; color:#4c5650;"><span style="padding-left:24px;">사업명 / 발주기관</span><span>의견 마감</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div>
        <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 16px; border-top:1px solid #e2e5df; background:#f6f7f4;" class="cap2"><span>불러온 59건 중 8건 표시</span><span>전체 59건 중 1–59</span></div>
      </section>
      {pane}
    </div>
  </main>
</div>
</div>'''
    return doc("사전규격 목록", body)

# ---------------------------------------------------------------- 상세 (PreSpecDetail)
def kpi(label, value, sub="", muted=False):
    color = "#79837c" if muted else "#1b211d"
    subh = f'<span class="cap">{sub}</span>' if sub else ""
    return f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px; border-right:1px solid #e2e5df;"><span class="cap">{label}</span><span style="font-size:17px; font-weight:600; line-height:1.3; color:{color};">{value}</span>{subh}</div>'

def section(title, right="", body="", id_=""):
    return f'''<section class="card" style="display:flex; flex-direction:column;">
  <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 20px; border-bottom:1px solid #e2e5df;">
    <h2 class="sec-title" style="font-size:15px;">{title}</h2>
    <div style="display:flex; align-items:center; gap:10px;">{right}</div>
  </div>
  <div style="display:flex; flex-direction:column; gap:14px; padding:16px 20px 18px;">{body}</div>
</section>'''

def detail_page():
    task = lambda n, t, d, ev: f'''<li style="display:grid; grid-template-columns: 24px minmax(0,1fr) auto; gap:10px; align-items:start; padding:10px 0; border-bottom:1px solid #eef0ec;">
      <span style="display:flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:#f1f6e8; color:#3f5a1c; font-size:12px; font-weight:600;">{n}</span>
      <div style="display:flex; flex-direction:column; gap:2px;"><span style="font-size:14px; font-weight:600; line-height:1.45;">{t}</span><span style="font-size:14px; line-height:1.5; color:#4c5650;">{d}</span></div>
      <a href="#" style="font-size:12px; white-space:nowrap;">{ev}</a></li>'''
    tasks = "".join([
        task(1,"현행 공제사업 시스템 현황 분석","창작준비금·예술인 산재보험·긴급복지 3개 시스템의 업무 절차, 데이터 구조, 연계 현황을 조사하고 이해관계자 인터뷰를 수행한다.","제안요청서 p.12 §3.1"),
        task(2,"통합관리시스템 목표 모델·정보화 전략 수립","기능·데이터·연계 아키텍처를 정의하고 재단 내부 시스템과 외부 기관(국세청·근로복지공단) 연계 방안을 제시한다.","제안요청서 p.15 §3.2"),
        task(3,"3개년 단계별 이행 계획과 소요 예산 산정","단계별 구축 범위, 일정, 예산과 사업 발주 방안(분리·통합 발주)을 도출하고 우선순위를 제시한다.","제안요청서 p.19 §3.3"),
        task(4,"데이터 표준화·이관 방안","공제사업 데이터 표준(코드·용어)을 정의하고 기존 데이터 정비·이관 절차와 품질 기준을 제시한다.","제안요청서 p.21 §3.4"),
    ])
    scope = '''<div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px;">
      <div style="display:flex; flex-direction:column; gap:4px; padding:12px 14px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">사업 규모</span><span style="font-size:14px; font-weight:600;">49,844,864원 (부가세 포함)</span><span class="cap2">제안요청서 p.4 §1.3</span></div>
      <div style="display:flex; flex-direction:column; gap:4px; padding:12px 14px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">사업 기간</span><span style="font-size:14px; font-weight:600;">계약 체결일로부터 6개월</span><span class="cap2">제안요청서 p.4 §1.4</span></div>
      <div style="display:flex; flex-direction:column; gap:4px; padding:12px 14px; border-radius:8.75px; background:#f6f7f4;"><span class="cap">수행 장소</span><span style="font-size:14px; font-weight:600; color:#79837c;">미확인</span><span class="cap2">이번 입력에서 확인되지 않음</span></div>
    </div>'''
    cond = lambda t, ev: f'<li style="display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid #eef0ec; font-size:14px; line-height:1.45;"><span style="display:flex; gap:8px;">{svg(I_CHECK, 14, "#587a2b", 2.4)}<span>{t}</span></span><a href="#" style="font-size:12px; white-space:nowrap;">{ev}</a></li>'
    conditions = "".join([
        cond("소프트웨어사업자 신고확인서 보유","p.7 §2.2"),
        cond("중소기업 확인서 (중소기업자 간 경쟁)","p.7 §2.2"),
        cond("정보화 전략 수립(ISP·ISMP) 수행 실적 1건 이상","p.8 §2.3"),
        cond("PM 1인 · ISP 경력 5년 이상","p.9 §2.4"),
    ])
    risk = lambda tone, tok, t, d: f'''<li style="display:flex; flex-direction:column; gap:4px; padding:10px 12px; border-radius:8.75px; background:{ {"orange":"#fff8ec","gray":"#f6f7f4"}[tone] }; border:1px solid { {"orange":"#f0dcb0","gray":"#e2e5df"}[tone] };">
      <div style="display:flex; align-items:center; gap:8px;"><span class="tok tok-{tone}">{tok}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>
      <span style="font-size:13px; line-height:1.5; color:#4c5650;">{d}</span></li>'''
    risks = "".join([
        risk("orange","근거 위치 없음","수행 인력 상주 조건","모델이 만든 항목이지만 원문 위치와 연결되지 않았습니다. 검증을 통과시키지 않고 사람 검토로 보냅니다."),
        risk("gray","미확인","본공고 · 입찰 예정 시기","사전규격 단계라 본공고 번호가 없습니다. 의견등록 마감 뒤 본공고 발생 여부를 확인합니다."),
        risk("gray","미확인","수행 장소 · 상주 여부","이번 개요 입력 범위(앞부분 24쪽)에서 확인되지 않았습니다."),
    ])
    fit = f'''<div style="display:flex; flex-direction:column; gap:10px;">
      <div style="display:flex; flex-direction:column; gap:4px; padding:12px 14px; border-radius:8.75px; background:#f6f7f4;">
        <div style="display:flex; align-items:center; justify-content:space-between;"><span class="cap">적합성 등급</span><span class="cap">출처 · 판정</span></div>
        <div style="display:flex; align-items:center; gap:8px;"><span class="tok tok-accent" style="height:24px; font-size:13px;">검토 권장</span><span class="cap2">회차 판정 · 2026-09-11</span></div>
        <p style="font-size:13px; line-height:1.5; color:#4c5650;">ISP·ISMP 컨설팅 범위가 회사 수행 영역과 겹치나, 공제사업 도메인 실적이 확인되지 않아 우선 검토가 아닌 검토 권장으로 판정.</p>
        <span class="cap">사람 정정 사유 없음</span>
      </div>
      <div style="display:flex; flex-direction:column; gap:6px; padding:12px 14px; border-radius:8.75px; border:1px solid #e2e5df;">
        <div style="display:flex; align-items:center; justify-content:space-between;"><span class="cap">회사 업무 부합 여부</span><span class="tok tok-yellow">판단 보류 · 정보 부족</span></div>
        <ul style="display:flex; flex-direction:column; gap:6px; font-size:13px; line-height:1.5;">
          <li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>정보화 전략 수립·아키텍처 설계는 회사 프로필의 컨설팅 실적과 일치</span></li>
          <li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>공제·보험 도메인 실적이 회사 자료에 없어 판단 보류</span></li>
        </ul>
        <span class="cap">모델 참조 결과 · 추적 승인과 최종 입찰 결정은 사람이 진행</span>
      </div>
    </div>'''
    att = lambda name, meta, status_tok, muted=False: f'''<tr>
      <td style="padding:10px 12px 10px 0; border-bottom:1px solid #eef0ec;"><div style="display:flex; align-items:center; gap:8px;">{svg(I_DOC, 16, "#79837c")}<span style="font-size:14px; font-weight:600; color:{"#79837c" if muted else "#1b211d"};">{name}</span></div></td>
      <td style="padding:10px 12px 10px 0; border-bottom:1px solid #eef0ec;" class="cap2">{meta}</td>
      <td style="padding:10px 12px 10px 0; border-bottom:1px solid #eef0ec;">{status_tok}</td>
      <td style="padding:10px 0; border-bottom:1px solid #eef0ec; text-align:right;"><div style="display:inline-flex; gap:12px;"><a href="#" style="font-size:12px;">다운로드</a><a href="#" style="font-size:12px;">원본 열기</a></div></td></tr>'''
    attachments = "".join([
        att("제안요청서.hwp","HWP · 2.4 MB · 변환 PDF 62쪽",'<span class="tok tok-accent">본문 추출 완료</span>'),
        att("과업지시서.hwp","HWP · 1.1 MB · 변환 PDF 18쪽",'<span class="tok tok-accent">본문 추출 완료</span>'),
        att("붙임3_서식.zip","ZIP · 크기 미확인",'<span class="tok tok-red">본문 추출 실패</span>', True),
    ])
    evid = lambda cid, t, p: f'<li style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:6px 0; font-size:13px;"><span style="display:flex; gap:8px;"><span style="font-family:ui-monospace,Menlo,monospace; font-size:12px; color:#79837c;">{cid}</span><span>{t}</span></span><a href="#" style="font-size:12px; white-space:nowrap;">{p}</a></li>'
    evidence = "".join([
        evid("C-01","사업 목적과 배경","제안요청서 p.3"),
        evid("C-04","주요 과업 4건","제안요청서 p.12–21"),
        evid("C-07","참여 자격 요건","제안요청서 p.7–9"),
        evid("C-09","수행 인력 상주 조건",'<span class="tok tok-orange">근거 위치 없음</span>'),
    ])
    step = lambda n, t, tok, sub, done: f'''<div style="display:flex; flex-direction:column; gap:6px; padding:12px 14px; border-radius:8.75px; border:1px solid {"#cfdfb5" if done else "#e2e5df"}; background:{"#f9fbf5" if done else "#ffffff"};">
      <div style="display:flex; align-items:center; gap:8px;"><span style="display:flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:{"#75a03b" if done else "#eef0ec"}; color:{"#ffffff" if done else "#4c5650"}; font-size:12px; font-weight:600;">{n}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>
      {tok}<span class="cap2">{sub}</span></div>'''
    steps = "".join([
        step(1,"첨부 취득",'<span class="tok tok-accent" style="align-self:flex-start;">3건 완료</span>',"완료 3 · 대기 0 · 차단 0 · 실패 0",True),
        step(2,"문서 묶음",'<span class="tok tok-accent" style="align-self:flex-start;">확정 완료</span>',"수정본 1 · 차단 issue 0건",True),
        step(3,"개요 검토",'<span class="tok tok-accent" style="align-self:flex-start;">완료 · 검증 통과</span>',"qwen3.8-27b · prompt v4 · 2026-09-11 11:05",True),
        step(4,"심층 검토",'<span class="tok" style="align-self:flex-start;">실행 대기</span>',"회사 핏 판단 보류라 자동 시작 조건 미충족",False),
    ])
    hist = lambda when, t, d, tone="gray": f'''<li style="display:grid; grid-template-columns: 148px 10px minmax(0,1fr); gap:12px; align-items:start; padding:8px 0; border-bottom:1px solid #eef0ec;">
      <span class="cap2" style="font-variant-numeric:tabular-nums;">{when}</span>
      <span style="width:8px; height:8px; border-radius:50%; margin-top:6px; background:{ {"gray":"#c9cfc3","accent":"#75a03b","orange":"#e0a04a"}[tone] };"></span>
      <div style="display:flex; flex-direction:column; gap:2px;"><span style="font-size:14px; font-weight:600;">{t}</span><span class="cap2">{d}</span></div></li>'''
    history = "".join([
        hist("2026-09-11 11:05","개요 검토 완료 · 주장 검증 통과","qwen3.8-27b · prompt v4 · 결과 ID ov_7f3a…c21e · 검토 범위 1–24쪽 (자동 선택)","accent"),
        hist("2026-09-11 11:02","개요 실행 시도 1 · 사람 검토 필요","C-09 수행 인력 상주 조건이 원문 위치와 연결되지 않음 (evidence_missing)","orange"),
        hist("2026-09-11 10:58","문서 묶음 확정 · 수정본 1","담당자 김지원 · 제안요청서·과업지시서 포함, 붙임3_서식.zip 제외","accent"),
        hist("2026-09-11 10:49","사전규격 관측 · 신규","R26BD00273769 · 나라장터 수집 회차 2026-09-11"),
    ])

    body = f'''<div style="display:flex; width:1422px; min-height:100%; box-sizing:border-box; background:#ffffff; align-items:stretch;">
{sidebar("사전규격")}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  {topbar('<div style="display:flex; align-items:center; gap:6px; font-size:12px; color:#4c5650;"><a href="#" style="color:#4c5650;">탐색과 추적</a>' + svg(I_CHEV_R, 12, "#9aa39c", 2) + '<a href="#" style="color:#4c5650;">사전규격</a>' + svg(I_CHEV_R, 12, "#9aa39c", 2) + '<span style="color:#1b211d; font-weight:600;">R26BD00273769</span></div>',
             '<span class="cap2">선택 항목 <b style="font-weight:600; color:#1b211d;">1 / 2</b></span><div class="btn btn-disabled" style="gap:4px;">' + svg(I_CHEV_L, 14, "#9aa39c", 2) + '이전</div><div class="btn btn-outline" style="gap:4px;">다음' + svg(I_CHEV_R, 14, "#1b211d", 2) + '</div>')}
  <main style="display:flex; flex:1 1 auto; flex-direction:column; align-items:center; padding:20px 18px 40px; background:#ffffff;">
    <div style="display:flex; width:100%; max-width:1040px; flex-direction:column; gap:16px;">

      <section class="card" style="display:flex; flex-direction:column;">
        <div style="display:flex; flex-direction:column; gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
            <div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-outline">사전규격 · 신규</span><span class="tok tok-accent">D-2</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-outline">본공고 미확인</span><span class="tok tok-outline">일반용역</span></div>
            <div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-accent">추적 결정 · 미선택</span><a href="#" class="cap2">목록으로 돌아가기</a></div>
          </div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2">
            <span style="font-size:14px; color:#1b211d;">한국예술인복지재단</span><span style="color:#c9cfc3;">·</span>
            <span>사전규격번호 <b style="font-weight:600; color:#1b211d; font-size:14px;">R26BD00273769</b></span>
            <div class="btn btn-ghost" style="height:24px; padding:0 6px; gap:4px;">{svg(I_COPY, 14, "#4c5650")}번호 복사</div>
            <div class="btn btn-ghost" style="height:24px; padding:0 6px; gap:4px;">{svg(I_EXT, 14, "#4c5650")}나라장터 원문</div>
            <span style="color:#c9cfc3;">·</span><span>품명 분류 · 정보화 전략 수립 컨설팅</span>
          </div>
          <div style="display:flex; gap:12px; padding:12px 14px; border-radius:8.75px; background:#f6f7f4;">
            <span class="tok tok-accent" style="flex:0 0 auto;">사업 요약</span>
            <p style="font-size:14px; line-height:1.55;">예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다. <a href="#" style="font-size:12px;">근거 C-01 · 제안요청서 p.3</a></p>
          </div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); border-top:1px solid #e2e5df;">
          {kpi("사업 예산","49,844,864원","부가세 포함")}
          {kpi("의견등록 마감",'2026.09.16 23:59 <span class="dday">D-2</span>',"KST")}
          {kpi("게시","2026.09.11 10:49","KST")}
          {kpi("구분","일반용역","SW사업대상 Y")}
          {kpi("적합성 등급",'<span class="tok tok-accent" style="height:24px; font-size:13px;">검토 권장</span>',"등급 출처 · 판정")}
          {kpi("첨부 원문","3건","본문 추출 2 · 실패 1").replace("border-right:1px solid #e2e5df;","")}
        </div>
      </section>

      <section class="card" style="display:flex; flex-direction:column; border-color:#cfdfb5;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 20px; border-bottom:1px solid #e2e5df; background:#f9fbf5; border-radius:10.5px 10.5px 0 0;">
          <div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">추적 결정</h2><span class="cap2">추적 시작 → <b style="font-weight:600; color:#1b211d;">계속 추적</b></span></div>
          <span class="cap">보류·추적 종료는 <a href="#">사업 추적</a>에서 변경</span>
        </div>
        <div style="display:grid; grid-template-columns: minmax(0,1.4fr) minmax(0,1fr) auto; gap:12px; align-items:end; padding:16px 20px;">
          <div style="display:flex; flex-direction:column; gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">선택 사유 <span style="color:#89001a;">·</span> <span class="cap">필수</span></span><div class="field" style="justify-content:space-between; height:36px;"><span>추적을 시작하는 사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div></div>
          <div style="display:flex; flex-direction:column; gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div></div>
          <div class="btn btn-primary" style="height:36px; padding:0 20px;">추적 시작</div>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px 14px;" class="cap">
          <span>추적을 시작하면 새 문서·입찰공고·정정공고를 계속 확인합니다. 이 이름은 결정 이력에 기록됩니다.</span>
          <span>입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</span>
        </div>
      </section>

      {section("주요 과업과 수행 범위", '<span class="tok tok-accent">주장 검증 완료 · 운영 승인 아님</span><a href="#" style="font-size:12px;">전체 근거 PDF 열기 ↗</a>',
               f'<ol style="display:flex; flex-direction:column;">{tasks}</ol><div class="cap" style="display:flex; align-items:center; gap:6px;">사업 규모와 일정</div>{scope}')}

      <section class="card" style="display:flex; flex-direction:column;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 20px; border-bottom:1px solid #e2e5df;">
          <h2 class="sec-title" style="font-size:15px;">참여 조건 · 회사 적합성 · 위험 및 미확인 사항</h2>
          <span class="cap">적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음</span>
        </div>
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:20px; padding:16px 20px 18px;">
          <div style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="sec-title">참여 조건</span><span class="cap">4건</span></div><ul style="display:flex; flex-direction:column;">{conditions}</ul><span class="cap">지역 제한 · 공동수급 허용 여부 · 미확인</span></div>
          <div style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="sec-title">회사 적합성</span><span class="cap">모델 참조 · 사람이 확정</span></div>{fit}</div>
          <div style="display:flex; flex-direction:column; gap:8px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="sec-title">위험 및 미확인 사항</span><span class="cap">주의 1 · 미확인 2</span></div><ul style="display:flex; flex-direction:column; gap:8px;">{risks}</ul></div>
        </div>
      </section>

      {section("근거 문서 · 첨부", '<span class="cap">첨부 3건 · 근거 항목 4건</span>',
               f'<table style="width:100%; border-collapse:collapse;"><thead><tr><th style="text-align:left; padding:0 12px 6px 0; border-bottom:1px solid #e2e5df; font-size:12px; font-weight:500; color:#4c5650;">파일</th><th style="text-align:left; padding:0 12px 6px 0; border-bottom:1px solid #e2e5df; font-size:12px; font-weight:500; color:#4c5650;">형식 · 크기</th><th style="text-align:left; padding:0 12px 6px 0; border-bottom:1px solid #e2e5df; font-size:12px; font-weight:500; color:#4c5650;">본문 추출</th><th style="text-align:right; padding:0 0 6px; border-bottom:1px solid #e2e5df; font-size:12px; font-weight:500; color:#4c5650;">열기</th></tr></thead><tbody>{attachments}</tbody></table>'
               f'<div style="display:flex; flex-direction:column; gap:4px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="cap">문서 근거 · 개요 검토 결과의 주장별 원문 위치</span><a href="#" style="font-size:12px;">상세에서 근거 원문 열기 →</a></div><ul style="display:flex; flex-direction:column;">{evidence}</ul></div>'
               '<span class="cap">첨부 원문 열기는 검증된 절대 HTTP(S) 주소만 사용하며 나라장터 원문 URL을 대신하지 않습니다.</span>')}

      {section("처리 이력 · 문서 준비 · 검토 실행", '<div class="btn btn-outline">문서 준비 열기</div><div class="btn btn-outline">개요 검토 다시 실행</div><div class="btn btn-disabled">심층 검토 보고서 열기 →</div>',
               f'<div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{steps}</div>'
               '<span class="cap">조건을 충족하면 심층 검토까지 자동으로 시작합니다. 추적 선택과 최종 입찰 Go/No-Go는 사람이 결정합니다.</span>'
               f'<div style="display:flex; flex-direction:column; gap:6px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="sec-title">처리 이력</span><div style="display:flex; gap:12px;"><a href="#" style="font-size:12px;">사전규격 목록 →</a><a href="#" style="font-size:12px;">사업기회 보기 →</a></div></div><ul style="display:flex; flex-direction:column;">{history}</ul></div>'
               '<div style="display:flex; align-items:center; justify-content:space-between;" class="cap"><span>현재 주장 검증 진단 · 고정 입력과 식별 해시 · 회사 핏 실행 정보</span><a href="#" style="font-size:12px;">펼치기</a></div>')}

    </div>
  </main>
</div>
</div>'''
    return doc("사전규격 상세", body)

# ---------------------------------------------------------------- 상태 표현 통일 (StatusVocabulary)
def vocab_page():
    def row(label, chips, note):
        return f'<div style="display:grid; grid-template-columns: 150px minmax(0,1fr) 300px; gap:16px; align-items:center; padding:12px 0; border-bottom:1px solid #eef0ec;"><span class="cap2" style="font-weight:600; color:#1b211d;">{label}</span><div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">{chips}</div><span class="cap">{note}</span></div>'
    def sw(hexv, name):
        return f'<div style="display:flex; flex-direction:column; gap:6px; width:118px;"><div style="height:44px; border-radius:8.75px; background:{hexv}; border:1px solid #e2e5df;"></div><span class="cap2" style="font-weight:600; color:#1b211d;">{name}</span><span class="cap" style="font-family:ui-monospace,Menlo,monospace;">{hexv}</span></div>'
    grades = "".join([
        '<span class="tok" style="background:#3f5a1c; color:#ffffff;">우선 검토</span>',
        '<span class="tok" style="background:#75a03b; color:#ffffff;">검토 권장</span>',
        '<span class="tok" style="background:#cfdfb5; color:#1b211d;">관찰 대상</span>',
        '<span class="tok" style="background:#eef0ec; color:#3c4640;">제외</span>',
        '<span class="tok tok-outline">판정 없음</span>'])
    body = f'''<div style="display:flex; width:1040px; box-sizing:border-box; flex-direction:column; gap:20px; padding:28px 32px 32px; background:#ffffff;">
  <div style="display:flex; flex-direction:column; gap:4px;"><h1 style="font-size:20px; font-weight:600; line-height:1.35;">색 팔레트와 상태 표현 통일</h1><span class="cap2">흰색 바탕 위에 포인트 #75a03b 하나. 목록 우측 영역과 상세 페이지가 같은 명칭·같은 칩을 쓴다.</span></div>
  <div style="display:flex; gap:12px; flex-wrap:wrap;">
    {sw("#75a03b","포인트")}{sw("#587a2b","포인트 · 진하게")}{sw("#3f5a1c","포인트 · 글자")}{sw("#f1f6e8","포인트 · 연하게")}{sw("#cfdfb5","포인트 · 테두리")}{sw("#ffffff","바탕")}{sw("#f6f7f4","보조 표면")}{sw("#e2e5df","구분선")}
  </div>
  <div class="cap">글자 #1b211d · 보조 글자 #4c5650 · 캡션 #79837c. 흰 바탕에서 #75a03b는 3.1:1이라 채움·테두리·강조에만 쓰고, 단추 채움과 링크 글자는 #587a2b(5.0:1)를 쓴다. 성공 의미색은 포인트 초록을 공유하고 경고·실패는 기존 테마 ramp를 그대로 둔다.</div>
  <div style="display:flex; flex-direction:column;">
    {row("적합성 등급", grades, "밀도 순서만 표현하고 항상 글자와 함께 쓴다 · 등급 출처(판정·정정·없음)는 캡션")}
    {row("추적 결정", '<span class="tok tok-outline">미선택</span><span class="tok tok-outline">계속 추적</span><span class="tok tok-outline">보류</span><span class="tok tok-outline">종료</span><span class="tok tok-outline">사업기회 미연결</span>', "이 화면이 정하는 것은 추적 시작 하나 · 보류·종료는 사업 추적에서")}
    {row("개요 검토 상태", '<span class="tok tok-accent">완료</span><span class="tok">실행 대기</span><span class="tok">실행 중</span><span class="tok tok-orange">사람 검토 필요</span><span class="tok tok-red">실패</span><span class="tok tok-outline">취소</span>', "실패와 사람 검토만 의미색 · 나머지는 중립")}
    {row("근거·검증", '<span class="tok tok-accent">주장 검증 완료 · 운영 승인 아님</span><span class="tok tok-orange">근거 위치 없음</span><span class="tok tok-red">검증 실패 · 사람 확인 필요</span>', "원문 위치와 연결된 주장만 통과 · 실패는 자동 보정하지 않음")}
    {row("회사 적합성", '<span class="tok tok-accent">부합</span><span class="tok tok-red">불일치</span><span class="tok tok-yellow">판단 보류 · 정보 부족</span><span class="tok tok-outline">판정 없음 · 불일치 아님</span>', "모델 참조 결과 · 사람이 확정")}
    {row("일정", '<span class="dday">D-2</span><span class="dday">D-0</span><span class="dday dday-passed">D+3 경과</span><span class="cap2">일시 없음</span>', "의견등록 마감 기준 · 경과만 붉게")}
    {row("정보 없음", '<span style="font-size:14px; font-weight:600; color:#79837c;">미확인</span><span class="tok">미확인</span><span class="cap2">이번 입력에서는 확인되지 않았습니다.</span>', "null·unknown은 추정하지 않고 미확인으로 보존")}
  </div>
  <div style="display:flex; align-items:center; gap:12px; padding:14px 16px; border-radius:8.75px; background:#f6f7f4;">
    <div class="btn btn-primary">추적 시작</div><div class="btn btn-secondary">선택 항목 검토</div><div class="btn btn-outline">전체 선택</div><div class="btn btn-ghost">표시 범위</div><div class="btn btn-disabled">이전</div>
    <span class="cap" style="margin-left:auto;">단추 28px · 반지름 8.75px · 12px/500 (기존 Astryx sm 규격 유지)</span>
  </div>
</div>'''
    return doc("상태 표현 통일", body, script="")

if __name__ == "__main__":
    print("library only")
