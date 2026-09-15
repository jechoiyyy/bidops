# 목록 페이지 시안 3방향 생성: Main(A 경계선형) · DirectionB(브랜드 강조형) · DirectionC(부드러운 카드형)
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build import BASE_CSS, FONT_LINK, icon, svg, I_SEARCH, I_FILTER, I_CHEV_D, I_ARROW_R, I_ALERT, I_CHECK, I_LEAF
OUT = pathlib.Path(__file__).parent

THEMES = {
 "A": dict(label="A · 경계선형", canvas="#ffffff",
    sb=dict(bg="#ffffff", border="#e2e5df", text="#4c5650", group="#79837c", brand="#1b211d", activeBg="#f1f6e8", activeText="#3f5a1c", activeBar="#75a03b", markBg="#75a03b", markFg="#ffffff"),
    topbar_border="#e2e5df", card_border="1px solid #e2e5df", card_shadow="none", radius="10.5px",
    filter_border="1px solid #e2e5df", filter_bg="#ffffff", tab="pill",
    list_head_bg="#ffffff", strip_bg="#f6f7f4", row_sel_bg="#f4f8ee", row_sel_bar="#75a03b",
    pane_bg="#ffffff", pane_head_bg="#ffffff", kpi_bg="#f6f7f4", kpi_border="none",
    primary="#587a2b", outline_bg="#ffffff", foot_bg="#ffffff", foot_border="#e2e5df", sec_accent=False),
 "B": dict(label="B · 브랜드 강조형", canvas="#ffffff",
    sb=dict(bg="#26391a", border="rgba(255,255,255,0.08)", text="#d6e0c8", group="rgba(214,224,200,0.6)", brand="#ffffff", activeBg="rgba(255,255,255,0.10)", activeText="#ffffff", activeBar="#a3cc6a", markBg="#ffffff", markFg="#3f5a1c"),
    topbar_border="#cfdfb5", card_border="1px solid #cfdfb5", card_shadow="none", radius="8.75px",
    filter_border="1px solid #cfdfb5", filter_bg="#f9fbf5", tab="filled",
    list_head_bg="#f1f6e8", strip_bg="#f9fbf5", row_sel_bg="#eaf2dc", row_sel_bar="#75a03b",
    pane_bg="#ffffff", pane_head_bg="#f1f6e8", kpi_bg="#ffffff", kpi_border="1px solid #cfdfb5",
    primary="#587a2b", outline_bg="#ffffff", foot_bg="#f9fbf5", foot_border="#cfdfb5", sec_accent=True),
 "C": dict(label="C · 부드러운 카드형", canvas="#f6f7f4",
    sb=dict(bg="#f6f7f4", border="transparent", text="#4c5650", group="#79837c", brand="#1b211d", activeBg="#ffffff", activeText="#3f5a1c", activeBar="transparent", markBg="#75a03b", markFg="#ffffff"),
    topbar_border="transparent", card_border="1px solid transparent", card_shadow="0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07)", radius="14px",
    filter_border="1px solid transparent", filter_bg="transparent", tab="underline",
    list_head_bg="#ffffff", strip_bg="#ffffff", row_sel_bg="#f1f6e8", row_sel_bar="transparent",
    pane_bg="#ffffff", pane_head_bg="#ffffff", kpi_bg="#f1f6e8", kpi_border="none",
    primary="#587a2b", outline_bg="#ffffff", foot_bg="#fbfcf9", foot_border="#eef0ec", sec_accent=False),
}

def sidebar(T):
    s = T["sb"]
    def item(label, key, act):
        if act:
            shadow = f"inset 3px 0 0 {s['activeBar']}" if s['activeBar'] != "transparent" else T["card_shadow"] if T["tab"]=="underline" else "none"
            style = f"background:{s['activeBg']}; color:{s['activeText']}; font-weight:600; box-shadow:{shadow};"
        else:
            style = f"color:{s['text']};"
        return f'<a class="nav-item" href="#" style="{style}">{icon(key)}<span>{label}</span></a>'
    def group(label, items):
        lis = "".join(item(l, k, l == "사전규격") for l, k in items)
        return f'''<div style="display:flex; flex-direction:column; padding-top:12px;">
        <div style="padding:0 12px 8px; font-size:12px; font-weight:500; letter-spacing:.08em; color:{s['group']};">{label}</div>
        <div style="display:flex; flex-direction:column; gap:2px;">{lis}</div></div>'''
    return f'''<aside style="display:flex; flex-direction:column; flex:0 0 248px; width:248px; height:100%; box-sizing:border-box; background:{s['bg']}; border-right:1px solid {s['border']};">
  <div style="display:flex; align-items:center; gap:12px; padding:16px 16px 12px; border-bottom:1px solid {s['border']};">
    <div style="display:flex; align-items:center; justify-content:center; width:40px; height:40px; border-radius:8.75px; background:{s['markBg']};">{svg(I_LEAF, 22, s['markFg'], 1.8)}</div>
    <div style="display:flex; flex-direction:column; gap:2px;">
      <div style="font-size:14.88px; font-weight:600; line-height:1.3; color:{s['brand']};">BidOps</div>
      <div style="font-size:12px; line-height:1.3; color:{s['group']};">ROOTLAB · 사업기회 모니터링</div>
    </div>
  </div>
  <nav style="display:flex; flex-direction:column; padding:4px 12px 24px; flex:1 1 auto;">
    {group("오늘의 업무", [("대시보드","dashboard")])}
    {group("탐색과 추적", [("발주계획","order-plan"),("사전규격","judgment"),("사업 추적","queue"),("최종 Go/No-Go","judgment")])}
    {group("기준과 운영", [("판정 기준","policy"),("실행 상태","operations")])}
  </nav>
  <div style="display:flex; flex-direction:column; gap:4px; padding:16px 20px 20px; border-top:1px solid {s['border']}; font-size:12px; color:{s['group']};">
    <span>기획부 · 사업기획</span><span>관리자 화면</span>
  </div>
</aside>'''

def tabs(T):
    data = [("전체","59",False),("개요 완료","8",True),("사람 확인","0",False),("진행·대기","51",False),("실패","0",False)]
    out = []
    for l,n,a in data:
        if T["tab"] == "pill":
            st = f'height:28px; padding:0 10px; border-radius:8.75px; background:{"#f1f6e8" if a else "transparent"}; color:{"#3f5a1c" if a else "#4c5650"};'; nc = "#587a2b" if a else "#79837c"
        elif T["tab"] == "filled":
            st = f'height:28px; padding:0 12px; border-radius:8.75px; background:{"#587a2b" if a else "#ffffff"}; color:{"#ffffff" if a else "#3f5a1c"}; box-shadow:{"none" if a else "inset 0 0 0 1px #cfdfb5"};'; nc = "rgba(255,255,255,0.8)" if a else "#587a2b"
        else:
            st = f'height:32px; padding:0 4px; border-radius:0; background:transparent; color:{"#1b211d" if a else "#79837c"}; box-shadow:{"inset 0 -2px 0 #75a03b" if a else "none"}; margin-right:12px;'; nc = "#587a2b" if a else "#9aa39c"
        out.append(f'<div style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:{600 if a else 500}; {st}"><span>{l}</span><span style="color:{nc};">{n}</span></div>')
    return "".join(out)

def row(T, title, agency, meta, toks, dday, date, checked=False, selected=False):
    bg = f"background:{T['row_sel_bg']}; box-shadow: inset 4px 0 0 {T['row_sel_bar']};" if selected else ""
    ck = "check check-on" if checked else "check"
    ckin = svg(I_CHECK, 12, "#ffffff", 3) if checked else ""
    return f'''<div style="display:flex; align-items:flex-start; gap:8px; padding:8px 16px; border-bottom:1px solid {T['foot_border'] if T['tab']=='underline' else '#e2e5df'}; {bg}">
      <div class="{ck}" style="display:flex; align-items:center; justify-content:center; margin-top:3px;">{ckin}</div>
      <div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; gap:4px;">
        <div style="font-size:15px; font-weight:600; line-height:1.4; color:#1b211d;">{title}</div>
        <div style="font-size:14px; line-height:1.45; color:#4c5650;">{agency}</div>
        <div class="cap2">{meta}</div>
        <div style="display:flex; align-items:center; gap:6px;">{"".join(toks)}</div>
      </div>
      <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px; flex:0 0 auto;"><span class="dday">{dday}</span><span class="cap2">{date}</span></div>
    </div>'''

def rows(T):
    ok = '<span class="tok tok-accent">완료</span>'; un = '<span class="tok tok-outline">미선택</span>'
    return "".join([
        row(T,"예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","4,984.5만원 · 신규 · <b style='font-weight:600; color:#1b211d;'>검토 권장</b>",[ok,un],"D-2","09.16",True,True),
        row(T,"산업단지 데이터 통합 DBMS 구축 용역","한국산업단지공단","7,150만원 · 신규 · 판정 없음",[ok,un],"D-2","09.16",True),
        row(T,"부산경찰청 정보화시스템 통합유지보수 용역","조달청 부산지방조달청","11.1억원 · 신규 · 판정 없음",[ok,un],"D-2","09.16"),
        row(T,"2027년 국가지식자원 통합 플랫폼 유지운영","조달청 서울지방조달청","1.9억원 · 신규 · 판정 없음",[ok,un],"D-2","09.16"),
        row(T,"[혁신G111_국고] 목원대학교 행정시스템 개선 및 고도화 용역 입찰","목원대학교","3.2억원 · 추적 · 관찰 대상",[ok,'<span class="tok tok-outline">계속 추적</span>'],"D-1","09.15"),
        row(T,"차세대 통합 데이터 분석 플랫폼 구축","서울특별시 디지털정책관","예산 미확인 · 신규 · 판정 없음",['<span class="tok tok-orange">사람 검토 필요</span>',un,'<span class="cap2">첨부 차단 1</span>'],"D-4","09.18"),
    ])

def kpi(T, label, value, muted=False):
    return f'<div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:8.75px; background:{T["kpi_bg"]}; border:{T["kpi_border"]}; {"border-top:2px solid #75a03b;" if T["sec_accent"] else ""}"><span class="cap">{label}</span><span style="font-size:16px; font-weight:600; line-height:1.3; color:{"#79837c" if muted else "#1b211d"};">{value}</span></div>'

def pane(T):
    head_band = f"background:{T['pane_head_bg']}; border-bottom:1px solid {T['foot_border']};" if T["sec_accent"] else ""
    title_size = "22px" if T["tab"]=="underline" else "20px"
    return f'''<section style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:{T['pane_bg']};">
  <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px 12px; overflow:hidden;">
    <div style="display:flex; flex-direction:column; gap:6px; {"margin:-14px -18px 0; padding:14px 18px 12px;" if T["sec_accent"] else ""} {head_band}">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="display:flex; align-items:center; gap:8px;"><span class="cap">발주기관</span><span style="font-size:13px; font-weight:600; color:#1b211d;">한국예술인복지재단</span></div>
        <div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-outline">신규</span><span class="tok tok-outline">일반용역</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-accent">추적 결정 · 미선택</span></div>
      </div>
      <h3 style="font-size:{title_size}; font-weight:600; line-height:1.35; color:#1b211d;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3>
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
      {kpi(T,"사업 예산","49,844,864원")}{kpi(T,"의견등록 마감",'9.16 23:59 <span class="dday">D-2</span>')}{kpi(T,"사업 기간","착수 후 6개월")}{kpi(T,"본공고 · 입찰 예정","미확인",True)}
    </div>
    <div style="display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8.75px; background:#fff8ec; border:1px solid #f0dcb0;">
      {svg(I_ALERT, 16, "#6e3500", 1.8)}
      <div style="display:flex; flex:1 1 auto; align-items:center; gap:8px; min-width:0; font-size:14px;"><span style="font-weight:600; color:#6e3500; white-space:nowrap;">주의 1건</span><span style="flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#1b211d;">수행 인력 상주 조건이 근거 위치와 연결되지 않음 · 미확인 2 (사업 기간 · 입찰 예정)</span></div>
      <a href="#" style="font-size:12px; white-space:nowrap;">근거 보기 →</a>
    </div>
  </div>
  <div style="display:flex; flex-direction:column; gap:10px; padding:12px 18px 14px; border-top:1px solid {T['foot_border']}; background:{T['foot_bg']};">
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
      <div style="display:flex; align-items:center; gap:8px;"><span class="sec-title">추적 결정</span><span class="cap2">현재 · 미선택 → 저장하면 계속 추적</span></div>
      <span class="cap">보류·추적 종료는 사업 추적에서 변경</span>
    </div>
    <div style="display:flex; align-items:center; gap:8px;">
      <div class="field" style="flex:1 1 auto; justify-content:space-between;"><span>추적을 시작하는 사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div>
      <div class="field" style="flex:0 0 168px;"><span>담당자 이름 (필수)</span></div>
      <div class="btn btn-primary" style="height:32px; background:{T['primary']};">추적 시작</div>
    </div>
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
      <div class="cap2" style="display:flex; align-items:center; gap:6px;"><span class="cap">다음 작업</span><span style="font-weight:600; color:#1b211d;">추적 결정하기</span><span style="color:#c9cfc3;">·</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정</span></div>
      <a href="#" class="btn btn-outline" style="height:32px; gap:6px; color:#3f5a1c; box-shadow: inset 0 0 0 1px #cfdfb5;">상세 페이지 열기 {svg(I_ARROW_R, 14, "#3f5a1c", 2)}</a>
    </div>
  </div>
</section>'''

def page(key):
    T = THEMES[key]
    sel_toolbar_bg = T["list_head_bg"] if T["sec_accent"] else "#ffffff"
    switch_bg = "#587a2b" if T["tab"]=="filled" else "#f1f6e8"; switch_fg = "#ffffff" if T["tab"]=="filled" else "#3f5a1c"
    body = f'''<div style="display:flex; width:1422px; height:889px; box-sizing:border-box; background:{T['canvas']}; overflow:hidden;">
{sidebar(T)}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  <header style="display:flex; align-items:center; justify-content:space-between; gap:16px; height:76px; box-sizing:border-box; padding:12px 18px; background:{T['canvas'] if T['tab']=='underline' else '#ffffff'}; border-bottom:1px solid {T['topbar_border']};">
    <div style="display:flex; align-items:center; gap:12px;"><h1 style="font-size:20px; font-weight:600; line-height:1.35; color:#1b211d;">사전규격</h1><span class="cap">누적 사전규격 확인 · 심층 검토 추적 시작</span></div>
    <div style="display:flex; align-items:center; gap:12px;"><div class="btn btn-ghost">표시 범위</div></div>
  </header>
  <main style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:{"12px 18px 16px" if T["tab"]=="underline" else "16px 18px"}; background:{T['canvas']};">
    <div style="display:flex; flex-direction:column; gap:8px; padding:{"0 4px" if T["tab"]=="underline" else "8px 12px"}; border:{T['filter_border']}; border-radius:8.75px; background:{T['filter_bg']};">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="display:flex; align-items:center; gap:4px;">{tabs(T)}</div>
        <div style="display:flex; align-items:center; gap:8px;">
          <div class="field" style="width:264px; box-sizing:border-box; height:32px; gap:8px; border-color:{"#cfdfb5" if T["sec_accent"] else "#c9cfc3"};">{svg(I_SEARCH, 16, "#79837c")}<span>사업명·기관명 검색</span></div>
          <div class="btn btn-outline" style="width:32px; height:32px; padding:0;">{svg(I_FILTER, 16, "#1b211d")}</div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:10px; {"padding-bottom:8px;" if T["tab"]=="underline" else ""}">
        <div style="display:flex; align-items:center; gap:8px; height:28px; padding:0 8px; border-radius:5.25px; background:{switch_bg}; box-shadow: inset 0 0 0 1px #cfdfb5; font-size:12px; font-weight:600; color:{switch_fg};"><div class="check check-on" style="width:14px; height:14px; display:flex; align-items:center; justify-content:center; {"background:#ffffff; border-color:#ffffff;" if T["tab"]=="filled" else ""}">{svg(I_CHECK, 10, "#587a2b" if T["tab"]=="filled" else "#ffffff", 3)}</div>SW 중심 · 추적 예외 포함</div>
        <span class="cap">일반·기술용역 / SW사업대상 Y + 추적 예외</span>
      </div>
    </div>
    <div style="display:flex; flex:1 1 auto; min-height:0; border:{T['card_border']}; border-radius:{T['radius']}; overflow:hidden; box-shadow:{T['card_shadow']}; background:#ffffff;">
      <section style="display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid {T['foot_border'] if T['tab']=='underline' else ('#cfdfb5' if T['sec_accent'] else '#e2e5df')}; background:#ffffff;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 16px; border-bottom:1px solid {T['foot_border']}; background:{T['list_head_bg']};">
          <span class="sec-title">사전규격 목록 <span style="color:#587a2b;">8건</span></span><span class="cap">개요 검토가 완료된 건</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px; padding:8px 16px; border-bottom:1px solid {T['foot_border']}; background:{sel_toolbar_bg};">
          <span style="font-size:12px; font-weight:600; color:#1b211d; white-space:nowrap;">선택 2건</span>
          <div class="btn btn-outline">전체 선택</div>
          <div class="btn btn-outline">전체 해제</div>
          <div class="btn btn-primary" style="background:{T['primary']};">선택 항목 검토</div>
          <span class="cap" style="margin-left:auto; text-align:right;">현재 페이지만 추가</span>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 16px; background:{T['strip_bg']}; border-bottom:1px solid {T['foot_border']}; font-size:12px; color:#4c5650;"><span style="padding-left:24px;">사업명 / 발주기관</span><span>의견 마감</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows(T)}</div>
        <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 16px; border-top:1px solid {T['foot_border']}; background:{T['foot_bg']};" class="cap2"><span>불러온 59건 중 8건 표시</span><span>전체 59건 중 1–59</span></div>
      </section>
      {pane(T)}
    </div>
  </main>
</div>
</div>'''
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
  <style>{BASE_CSS}
  </style>
</helmet>
{body}
</x-dc>
</body>
</html>'''

(OUT/"DirectionA.dc.html").write_text(page("A"), encoding="utf-8")
(OUT/"DirectionB.dc.html").write_text(page("B"), encoding="utf-8")
(OUT/"Main.dc.html").write_text(page("C"), encoding="utf-8")
print("ok")
