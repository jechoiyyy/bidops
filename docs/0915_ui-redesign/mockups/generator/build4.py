# C 기준 파생 3방향: C1 밀집형 · C2 초록 밴드형 · C3 결정 카드형
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build import BASE_CSS, FONT_LINK, svg, I_SEARCH, I_FILTER, I_CHEV_D, I_ARROW_R, I_ALERT, I_CHECK
from build3 import THEMES, sidebar, tabs, kpi
OUT = pathlib.Path(__file__).parent
T = dict(THEMES["C"])
SERIF = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&amp;display=swap">'

def shell(body_main, extra_head=""):
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  {FONT_LINK}{extra_head}
  <style>{BASE_CSS}
  </style>
</helmet>
<div style="display:flex; width:1422px; height:889px; box-sizing:border-box; background:#f6f7f4; overflow:hidden;">
{sidebar(T)}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  <header style="display:flex; align-items:center; justify-content:space-between; gap:16px; height:76px; box-sizing:border-box; padding:12px 18px; background:#f6f7f4;">
    <div style="display:flex; align-items:center; gap:12px;"><h1 style="font-size:20px; font-weight:600; line-height:1.35; color:#1b211d;">사전규격</h1><span class="cap">누적 사전규격 확인 · 심층 검토 추적 시작</span></div>
    <div style="display:flex; align-items:center; gap:12px;"><div class="btn btn-ghost">표시 범위</div></div>
  </header>
  <main style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:12px 18px 16px; background:#f6f7f4;">
    <div style="display:flex; flex-direction:column; gap:8px; padding:0 4px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <div style="display:flex; align-items:center; gap:4px;">{tabs(T)}</div>
        <div style="display:flex; align-items:center; gap:8px;">
          <div class="field" style="width:264px; box-sizing:border-box; height:32px; gap:8px;">{svg(I_SEARCH, 16, "#79837c")}<span>사업명·기관명 검색</span></div>
          <div class="btn btn-outline" style="width:32px; height:32px; padding:0;">{svg(I_FILTER, 16, "#1b211d")}</div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:10px; padding-bottom:8px;">
        <div style="display:flex; align-items:center; gap:8px; height:28px; padding:0 8px; border-radius:5.25px; background:#f1f6e8; box-shadow: inset 0 0 0 1px #cfdfb5; font-size:12px; font-weight:600; color:#3f5a1c;"><div class="check check-on" style="width:14px; height:14px; display:flex; align-items:center; justify-content:center;">{svg(I_CHECK, 10, "#ffffff", 3)}</div>SW 중심 · 추적 예외 포함</div>
        <span class="cap">일반·기술용역 / SW사업대상 Y + 추적 예외</span>
      </div>
    </div>
    {body_main}
  </main>
</div>
</div>
</x-dc>
</body>
</html>'''

CARD = 'border-radius:14px; overflow:hidden; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07); background:#ffffff;'

def toolbar(count_note="이 페이지만 추가"):
    return f'''<div style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec;">
          <span class="sec-title">사전규격 목록 <span style="color:#587a2b;">8건</span></span><span class="cap">개요 검토가 완료된 건</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec;">
          <span style="font-size:12px; font-weight:600; color:#1b211d; white-space:nowrap;">선택 2건</span>
          <div class="btn btn-outline">전체 선택</div><div class="btn btn-outline">전체 해제</div><div class="btn btn-primary">선택 항목 검토</div>
          <span class="cap" style="margin-left:auto;">{count_note}</span>
        </div>'''

FOOT = '<div style="display:flex; align-items:center; justify-content:space-between; padding:8px 16px; border-top:1px solid #eef0ec; background:#fbfcf9;" class="cap2"><span>불러온 59건 중 8건 표시</span><span>전체 59건 중 1–59</span></div>'

ROWS = [
 ("예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","4,984.5만원","신규","검토 권장","완료","미선택","D-2","09.16",True,True),
 ("산업단지 데이터 통합 DBMS 구축 용역","한국산업단지공단","7,150만원","신규","판정 없음","완료","미선택","D-2","09.16",True,False),
 ("부산경찰청 정보화시스템 통합유지보수 용역","조달청 부산지방조달청","11.1억원","신규","판정 없음","완료","미선택","D-2","09.16",False,False),
 ("2027년 국가지식자원 통합 플랫폼 유지운영","조달청 서울지방조달청","1.9억원","신규","판정 없음","완료","미선택","D-2","09.16",False,False),
 ("[혁신G111_국고] 목원대학교 행정시스템 개선 및 고도화 용역 입찰","목원대학교","3.2억원","추적","관찰 대상","완료","계속 추적","D-1","09.15",False,False),
 ("차세대 통합 데이터 분석 플랫폼 구축","서울특별시 디지털정책관","예산 미확인","신규","판정 없음","사람 검토 필요","미선택","D-4","09.18",False,False),
 ("공공데이터 개방 플랫폼 고도화","행정안전부","2.4억원","신규","제외","완료","미선택","D-5","09.19",False,False),
 ("스마트 도서관 통합관리 시스템 구축","경기도교육청","6.8억원","신규","판정 없음","완료","미선택","D-6","09.20",False,False),
]
def ov_tok(s): return f'<span class="tok tok-orange">{s}</span>' if s == "사람 검토 필요" else f'<span class="tok tok-accent">{s}</span>'
def ck(on): return f'<div class="check {"check-on" if on else ""}" style="display:flex; align-items:center; justify-content:center; margin-top:2px;">{svg(I_CHECK, 12, "#ffffff", 3) if on else ""}</div>'

def rows_soft():
    out = []
    for t,a,b,o,g,ov,tr,dd,dt,c,sel in ROWS[:6]:
        bg = "background:#f1f6e8;" if sel else ""
        gtxt = f"<b style='font-weight:600; color:#1b211d;'>{g}</b>" if g != "판정 없음" else g
        out.append(f'''<div style="display:flex; align-items:flex-start; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec; {bg}">{ck(c)}
      <div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; gap:4px;">
        <div style="font-size:15px; font-weight:600; line-height:1.4;">{t}</div><div style="font-size:14px; line-height:1.45; color:#4c5650;">{a}</div>
        <div class="cap2">{b} · {o} · {gtxt}</div><div style="display:flex; align-items:center; gap:6px;">{ov_tok(ov)}<span class="tok tok-outline">{tr}</span></div>
      </div>
      <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;"><span class="dday">{dd}</span><span class="cap2">{dt}</span></div></div>''')
    return "".join(out)

def rows_dense():
    out = []
    for t,a,b,o,g,ov,tr,dd,dt,c,sel in ROWS:
        bg = "background:#f1f6e8;" if sel else ""
        out.append(f'''<div style="display:grid; grid-template-columns: 16px minmax(0,1fr) 78px 52px; gap:10px; align-items:center; min-height:52px; padding:6px 16px; border-bottom:1px solid #eef0ec; {bg}">{ck(c)}
      <div style="display:flex; min-width:0; flex-direction:column; gap:2px;">
        <div style="font-size:14px; font-weight:600; line-height:1.4; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{t}</div>
        <div class="cap2" style="display:flex; align-items:center; gap:6px; overflow:hidden; white-space:nowrap;"><span style="overflow:hidden; text-overflow:ellipsis;">{a}</span><span style="color:#c9cfc3;">·</span><span>{b}</span><span style="color:#c9cfc3;">·</span><span style="{"font-weight:600; color:#1b211d;" if g not in ("판정 없음","제외") else ""}">{g}</span></div>
      </div>
      <div style="display:flex; flex-direction:column; align-items:flex-start; gap:3px;">{ov_tok(ov)}<span class="cap2">{tr}</span></div>
      <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px;"><span class="dday">{dd}</span><span class="cap2">{dt}</span></div></div>''')
    return "".join(out)

def caution(): return f'''<div style="display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:8.75px; background:#fff8ec; border:1px solid #f0dcb0;">{svg(I_ALERT, 16, "#6e3500", 1.8)}
      <div style="display:flex; flex:1 1 auto; align-items:center; gap:8px; min-width:0; font-size:14px;"><span style="font-weight:600; color:#6e3500; white-space:nowrap;">주의 1건</span><span style="flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">수행 인력 상주 조건이 근거 위치와 연결되지 않음 · 미확인 2 (사업 기간 · 입찰 예정)</span></div><a href="#" style="font-size:12px; white-space:nowrap;">근거 보기 →</a></div>'''

DESC = "예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다."
TASKS = ["현행 공제사업 3개 시스템 업무·데이터 현황 분석 및 이해관계자 요구 조사","통합관리시스템 목표 모델과 정보화 전략 수립 (기능·데이터·연계 아키텍처)","3개년 단계별 이행 계획과 소요 예산 산정, 사업 발주 방안 제시"]
def task_list(size=14, gap=4):
    return '<ol style="display:flex; flex-direction:column; gap:%dpx;">' % gap + "".join(f'<li style="display:flex; gap:8px; font-size:{size}px; line-height:1.45;"><span style="flex:0 0 18px; font-weight:600; color:#587a2b;">{i+1}</span><span>{t}</span></li>' for i,t in enumerate(TASKS)) + '</ol>'

def decision_footer():
    return f'''<div style="display:flex; flex-direction:column; gap:10px; padding:12px 18px 14px; border-top:1px solid #eef0ec; background:#fbfcf9;">
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:8px;"><span class="sec-title">추적 결정</span><span class="cap2">현재 · 미선택 → 저장하면 계속 추적</span></div><span class="cap">보류·추적 종료는 사업 추적에서 변경</span></div>
    <div style="display:flex; align-items:center; gap:8px;"><div class="field" style="flex:1 1 auto; justify-content:space-between;"><span>추적을 시작하는 사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div><div class="field" style="flex:0 0 168px;"><span>담당자 이름 (필수)</span></div><div class="btn btn-primary" style="height:32px;">추적 시작</div></div>
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div class="cap2" style="display:flex; align-items:center; gap:6px;"><span class="cap">다음 작업</span><span style="font-weight:600; color:#1b211d;">추적 결정하기</span><span style="color:#c9cfc3;">·</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정</span></div><a href="#" class="btn btn-outline" style="height:32px; gap:6px; color:#3f5a1c; box-shadow: inset 0 0 0 1px #cfdfb5;">상세 페이지 열기 {svg(I_ARROW_R, 14, "#3f5a1c", 2)}</a></div></div>'''

CHIPS = '<span class="tok tok-outline">신규</span><span class="tok tok-outline">일반용역</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-accent">추적 결정 · 미선택</span>'

# ---------- C1 밀집형: 한 줄 행 8건 + 사실 표 형태의 우측 영역
def c1():
    dl = lambda k, v, muted=False: f'<div style="display:flex; justify-content:space-between; gap:12px; padding:7px 0; border-bottom:1px solid #eef0ec; font-size:14px;"><span class="cap2">{k}</span><span style="font-weight:600; text-align:right; color:{"#79837c" if muted else "#1b211d"};">{v}</span></div>'
    facts_l = dl("사업 예산","49,844,864원") + dl("의견등록 마감",'9.16 23:59 <span class="dday">D-2</span>') + dl("게시","2026.09.11 10:49") + dl("사업 기간","착수 후 6개월")
    facts_r = dl("적합성 등급","검토 권장 (판정)") + dl("본공고 · 입찰 예정","미확인",True) + dl("업무구분 · SW","일반용역 · Y") + dl("첨부 원문","3건 · 추출 실패 1")
    pane = f'''<section style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:#ffffff;">
  <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:12px 18px; overflow:hidden;">
    <div style="display:flex; flex-direction:column; gap:4px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:8px;"><span class="cap">발주기관</span><span style="font-size:13px; font-weight:600;">한국예술인복지재단</span><span class="cap">· 사전규격 R26BD00273769</span></div><div style="display:flex; gap:6px;">{CHIPS}</div></div>
      <h3 style="font-size:18px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3>
    </div>
    <div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:0 24px;"><div>{facts_l}</div><div>{facts_r}</div></div>
    <div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:20px;">
      <div style="display:flex; flex-direction:column; gap:4px;"><span class="cap">사업 설명 · 검증 통과</span><p style="font-size:13px; line-height:1.55; display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden;">{DESC}</p></div>
      <div style="display:flex; flex-direction:column; gap:4px;"><div class="cap" style="display:flex; justify-content:space-between;"><span>주요 과업 요약</span><span>4건 중 3건</span></div>{task_list(13, 3)}</div>
    </div>
    {caution()}
  </div>
  {decision_footer()}
</section>'''
    body = f'''<div style="display:flex; flex:1 1 auto; min-height:0; {CARD}">
      <section style="display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid #eef0ec; background:#ffffff;">
        {toolbar()}
        <div style="display:grid; grid-template-columns: 16px minmax(0,1fr) 78px 52px; gap:10px; padding:4px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span></span><span>사업명 · 발주기관 · 예산 · 등급</span><span>개요 · 추적</span><span style="text-align:right;">마감</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows_dense()}</div>
        {FOOT}
      </section>{pane}</div>'''
    return shell(body)

# ---------- C2 초록 밴드형: 우측 영역 머리를 짙은 초록 밴드로, KPI 타일이 밴드에 걸침
def c2():
    tile = lambda k, v, muted=False: f'<div style="display:flex; flex-direction:column; gap:2px; padding:10px 12px; border-radius:10.5px; background:#ffffff; box-shadow:0 1px 2px rgba(27,33,29,0.06), 0 4px 12px rgba(27,33,29,0.08);"><span class="cap">{k}</span><span style="font-size:16px; font-weight:600; line-height:1.3; color:{"#79837c" if muted else "#1b211d"};">{v}</span></div>'
    band_chip = lambda s, strong=False: f'<span class="tok" style="background:{"#75a03b" if strong else "rgba(255,255,255,0.14)"}; color:#ffffff;">{s}</span>'
    pane = f'''<section style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:#ffffff;">
  <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">
    <div style="display:flex; flex-direction:column; gap:8px; padding:16px 18px 40px; background:#26391a; color:#ffffff;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:8px;"><span style="font-size:12px; color:rgba(255,255,255,0.65);">발주기관</span><span style="font-size:13px; font-weight:600;">한국예술인복지재단</span></div><div style="display:flex; gap:6px;">{band_chip("신규")}{band_chip("일반용역")}{band_chip("SW사업대상 Y")}{band_chip("추적 결정 · 미선택", True)}</div></div>
      <h3 style="font-size:21px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3>
      <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:rgba(255,255,255,0.75);"><span>사전규격 <b style="font-weight:600; color:#ffffff;">R26BD00273769</b></span><span>·</span><span>게시 2026. 9. 11. 오전 10:49</span><span>·</span><span>적합성 등급 <b style="font-weight:600; color:#ffffff;">검토 권장</b> (판정)</span></div>
    </div>
    <div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px; margin:-28px 18px 0;">{tile("사업 예산","49,844,864원")}{tile("의견등록 마감",'9.16 23:59 <span class="dday">D-2</span>')}{tile("사업 기간","착수 후 6개월")}{tile("본공고 · 입찰 예정","미확인",True)}</div>
    <div style="display:flex; flex-direction:column; gap:12px; padding:14px 18px 12px;">
      <div style="display:flex; flex-direction:column; gap:4px;"><div class="cap">사업 설명 · 개요 검토 결과 · 검증 통과</div><p style="font-size:14px; line-height:1.55; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">{DESC}</p></div>
      <div style="display:flex; flex-direction:column; gap:6px;"><div class="cap" style="display:flex; justify-content:space-between;"><span>주요 과업 요약</span><span>4건 중 3건 · 전체는 상세에서</span></div>{task_list()}</div>
      {caution()}
    </div>
  </div>
  {decision_footer()}
</section>'''
    body = f'''<div style="display:flex; flex:1 1 auto; min-height:0; {CARD}">
      <section style="display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid #eef0ec; background:#ffffff;">
        {toolbar()}
        <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span style="padding-left:24px;">사업명 / 발주기관</span><span>의견 마감</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows_soft()}</div>
        {FOOT}
      </section>{pane}</div>'''
    return shell(body)

# ---------- C3 결정 카드형: 추적 결정을 바닥 고정 대신 우측 결정 카드로, 본문은 세리프 제목의 보고서 톤
def c3():
    stat = lambda k, v, muted=False: f'<div style="display:flex; flex-direction:column; gap:2px;"><span class="cap">{k}</span><span style="font-size:16px; font-weight:600; line-height:1.3; letter-spacing:-0.01em; white-space:nowrap; color:{"#79837c" if muted else "#1b211d"};">{v}</span></div>'
    decision = f'''<aside style="display:flex; flex:0 0 236px; flex-direction:column; gap:12px; padding:14px 14px 16px; border-radius:12px; background:#f6f7f4; border:1px solid #e8ebe4;">
      <div style="display:flex; flex-direction:column; gap:2px;"><span class="sec-title">추적 결정</span><span class="cap2">현재 · <b style="font-weight:600; color:#1b211d;">미선택</b> → 저장하면 계속 추적</span></div>
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div class="field" style="justify-content:space-between; background:#ffffff;"><span>선택 사유</span>{svg(I_CHEV_D, 16, "#79837c")}</div>
        <div class="field" style="background:#ffffff;"><span>담당자 이름 (필수)</span></div>
        <div class="btn btn-primary" style="height:36px;">추적 시작</div>
      </div>
      <div style="display:flex; flex-direction:column; gap:6px;" class="cap"><span>보류·추적 종료는 사업 추적에서 변경합니다.</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</span></div>
      <div style="display:flex; flex-direction:column; gap:6px; padding-top:10px; border-top:1px solid #e2e5df;"><div class="cap2"><span class="cap">다음 작업 </span><b style="font-weight:600; color:#1b211d;">추적 결정하기</b></div><a href="#" class="btn btn-outline" style="height:32px; gap:6px; color:#3f5a1c; box-shadow: inset 0 0 0 1px #cfdfb5; justify-content:center;">상세 페이지 열기 {svg(I_ARROW_R, 14, "#3f5a1c", 2)}</a></div>
    </aside>'''
    pane = f'''<section style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:#ffffff;">
  <div style="display:flex; flex:1 1 auto; min-height:0; gap:20px; padding:18px 20px 16px; overflow:hidden;">
    <div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column; gap:16px;">
      <div style="display:flex; flex-direction:column; gap:6px;">
        <div style="display:flex; align-items:center; gap:8px; white-space:nowrap; overflow:hidden;" class="cap2"><span style="font-weight:600; color:#1b211d;">한국예술인복지재단</span><span style="color:#c9cfc3;">·</span><span>사전규격 R26BD00273769</span><span style="color:#c9cfc3;">·</span><span>게시 2026. 9. 11.</span></div>
        <h3 style="font-family:'Noto Serif KR','Pretendard',serif; font-size:22px; font-weight:700; line-height:1.35; letter-spacing:-0.01em;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">{CHIPS}<span class="tok tok-outline">적합성 등급 · 검토 권장</span></div>
      </div>
      <div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:12px 16px; padding:12px 0; border-top:1px solid #e2e5df; border-bottom:1px solid #e2e5df;">{stat("사업 예산","49,844,864원")}{stat("의견등록 마감",'9.16 23:59 <span class="dday">D-2</span>')}{stat("사업 기간","착수 후 6개월")}{stat("본공고 · 입찰 예정","미확인",True)}</div>
      <div style="display:flex; flex-direction:column; gap:4px;"><div class="cap">사업 설명 · 검증 통과</div><p style="font-size:14px; line-height:1.6; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">{DESC}</p></div>
      <div style="display:flex; flex-direction:column; gap:6px;"><div class="cap" style="display:flex; justify-content:space-between;"><span>주요 과업 요약</span><span>4건 중 3건 · 전체는 상세에서</span></div>{task_list(14, 5)}</div>
      {caution()}
    </div>
    {decision}
  </div>
</section>'''
    body = f'''<div style="display:flex; flex:1 1 auto; min-height:0; {CARD}">
      <section style="display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid #eef0ec; background:#ffffff;">
        {toolbar()}
        <div style="display:flex; align-items:center; justify-content:space-between; padding:4px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span style="padding-left:24px;">사업명 / 발주기관</span><span>의견 마감</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows_soft()}</div>
        {FOOT}
      </section>{pane}</div>'''
    return shell(body, SERIF)

(OUT/"DirectionC1.dc.html").write_text(c1(), encoding="utf-8")
(OUT/"DirectionC2.dc.html").write_text(c2(), encoding="utf-8")
(OUT/"DirectionC3.dc.html").write_text(c3(), encoding="utf-8")
print("ok")
