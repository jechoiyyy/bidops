# C 셸로 나머지 화면: 사전규격 상세 · 대시보드 · 발주계획 · 사업 추적 · 최종 Go/No-Go · 판정 기준 · 실행 상태
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build import (BASE_CSS, FONT_LINK, svg, I_SEARCH, I_FILTER, I_CHEV_D, I_CHEV_R, I_CHEV_L, I_ARROW_R, I_EXT, I_COPY, I_ALERT, I_INFO, I_CHECK, I_DOC)
from build3 import THEMES, sidebar
OUT = pathlib.Path(__file__).parent
T = dict(THEMES["C"])
C_CSS = """
    .card { background:#ffffff; border:1px solid transparent; border-radius:14px; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07); }
    .utab { display:flex; align-items:center; gap:6px; height:32px; padding:0 4px; margin-right:12px; font-size:12px; font-weight:500; color:#79837c; }
    .utab-on { color:#1b211d; font-weight:600; box-shadow: inset 0 -2px 0 #75a03b; }
    .split-l { display:flex; flex:0 0 38%; min-width:0; flex-direction:column; border-right:1px solid #eef0ec; background:#ffffff; }
    .split-r { display:flex; flex:1 1 auto; min-width:0; flex-direction:column; background:#ffffff; }
    .lh { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec; }
    .lf { display:flex; align-items:center; justify-content:space-between; padding:8px 16px; border-top:1px solid #eef0ec; background:#fbfcf9; font-size:12px; color:#4c5650; }
    .row { display:flex; align-items:flex-start; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec; }
    .row-on { background:#f1f6e8; }
    .th { text-align:left; padding:0 12px 6px 0; border-bottom:1px solid #e2e5df; font-size:12px; font-weight:500; color:#4c5650; }
    .td { padding:10px 12px 10px 0; border-bottom:1px solid #eef0ec; font-size:14px; vertical-align:top; }
    .kv { display:flex; flex-direction:column; gap:2px; }
"""
I_REFRESH = '<path d="M20 12a8 8 0 1 1-2.3-5.7"></path><path d="M20 4v5h-5"></path>'
I_PLAY = '<path d="M7 5v14l11-7z"></path>'
I_SLIDERS = '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"></path><circle cx="16" cy="7" r="2"></circle><circle cx="10" cy="17" r="2"></circle>'
I_LOCK = '<rect x="5" y="11" width="14" height="10" rx="2"></rect><path d="M8 11V7a4 4 0 0 1 8 0v4"></path>'
I_CLOCK = '<circle cx="12" cy="12" r="8"></circle><path d="M12 8v4l3 2"></path>'
I_OPS = '<path d="M4 17h3l2-10 4 14 2-8h5"></path>'
SUBSPAN = lambda x: f'<span class="cap">{x}</span>' if x else ''
I_BUILDING = '<path d="M4 21V6l7-3 7 3v15"></path><path d="M9 21v-6h4v6M4 21h16"></path>'

NSPAN = lambda n, a: f'<span style="color:{"#587a2b" if a else "#9aa39c"};">{n}</span>' if n is not None else ''
def utabs(items):
    return '<div style="display:flex; align-items:center;">' + "".join(
        f'<div class="utab {"utab-on" if a else ""}"><span>{l}</span>{NSPAN(n, a)}</div>' for l,n,a in items) + '</div>'

def search(w=264, ph="사업명·발주기관 검색"):
    return f'<div class="field" style="width:{w}px; box-sizing:border-box; height:32px; gap:8px;">{svg(I_SEARCH, 16, "#79837c")}<span>{ph}</span></div>'
FILTER_BTN = f'<div class="btn btn-outline" style="width:32px; height:32px; padding:0;">{svg(I_FILTER, 16, "#1b211d")}</div>'

def crumbs(*parts):
    out = []
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        out.append(f'<span style="{"color:#1b211d; font-weight:600;" if last else "color:#4c5650;"}">{p}</span>')
        if not last: out.append(svg(I_CHEV_R, 12, "#9aa39c", 2))
    return '<div style="display:flex; align-items:center; gap:6px; font-size:12px;">' + "".join(out) + '</div>'

def page(active, header_left, header_right, main, height=889, extra_head="", main_style=""):
    tall = height != 889
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
  <style>{BASE_CSS}{C_CSS}
  </style>
</helmet>
<div style="display:flex; width:1422px; {"min-height:" + str(height) + "px;" if tall else "height:889px;"} box-sizing:border-box; background:#f6f7f4; overflow:hidden; align-items:stretch;">
{sidebar(T).replace("height:100%;", "height:auto; align-self:stretch;" if tall else "height:100%;")}
<div style="display:flex; flex:1 1 auto; min-width:0; flex-direction:column;">
  <header style="display:flex; align-items:center; justify-content:space-between; gap:16px; height:76px; box-sizing:border-box; padding:12px 18px; background:#f6f7f4;">
    {header_left}
    <div style="display:flex; align-items:center; gap:12px;">{header_right}</div>
  </header>
  <main style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:12px; padding:12px 18px 16px; background:#f6f7f4; {main_style}">
    {main}
  </main>
</div>
</div>
</x-dc>
</body>
</html>'''

def h1(title, sub=""):
    return f'<div style="display:flex; align-items:center; gap:12px;"><h1 style="font-size:20px; font-weight:600; line-height:1.35; color:#1b211d;">{title}</h1>{SUBSPAN(sub)}</div>'

def write(name, html): (OUT/f"{name}.dc.html").write_text(html, encoding="utf-8")

# ============================================================ 사전규격 상세
def kpi(label, value, sub="", muted=False, last=False):
    return f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px; {"" if last else "border-right:1px solid #eef0ec;"}"><span class="cap">{label}</span><span style="font-size:17px; font-weight:600; line-height:1.3; color:{"#79837c" if muted else "#1b211d"};">{value}</span>{SUBSPAN(sub)}</div>'
def sec(title, right="", body=""):
    return f'''<section class="card" style="display:flex; flex-direction:column;">
  <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #eef0ec;"><h2 class="sec-title" style="font-size:15px;">{title}</h2><div style="display:flex; align-items:center; gap:10px;">{right}</div></div>
  <div style="display:flex; flex-direction:column; gap:14px; padding:16px 22px 20px;">{body}</div></section>'''

def detail():
    task = lambda n,t,d,ev: f'<li style="display:grid; grid-template-columns: 24px minmax(0,1fr) auto; gap:10px; align-items:start; padding:10px 0; border-bottom:1px solid #eef0ec;"><span style="display:flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:#f1f6e8; color:#3f5a1c; font-size:12px; font-weight:600;">{n}</span><div class="kv"><span style="font-size:14px; font-weight:600; line-height:1.45;">{t}</span><span style="font-size:14px; line-height:1.5; color:#4c5650;">{d}</span></div><a href="#" style="font-size:12px; white-space:nowrap;">{ev}</a></li>'
    tasks = "".join([
        task(1,"현행 공제사업 시스템 현황 분석","창작준비금·예술인 산재보험·긴급복지 3개 시스템의 업무 절차, 데이터 구조, 연계 현황을 조사하고 이해관계자 인터뷰를 수행한다.","제안요청서 p.12 §3.1"),
        task(2,"통합관리시스템 목표 모델·정보화 전략 수립","기능·데이터·연계 아키텍처를 정의하고 재단 내부 시스템과 외부 기관(국세청·근로복지공단) 연계 방안을 제시한다.","제안요청서 p.15 §3.2"),
        task(3,"3개년 단계별 이행 계획과 소요 예산 산정","단계별 구축 범위, 일정, 예산과 사업 발주 방안(분리·통합 발주)을 도출하고 우선순위를 제시한다.","제안요청서 p.19 §3.3"),
        task(4,"데이터 표준화·이관 방안","공제사업 데이터 표준(코드·용어)을 정의하고 기존 데이터 정비·이관 절차와 품질 기준을 제시한다.","제안요청서 p.21 §3.4")])
    tile = lambda k,v,s,muted=False: f'<div class="kv" style="gap:4px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;"><span class="cap">{k}</span><span style="font-size:14px; font-weight:600; color:{"#79837c" if muted else "#1b211d"};">{v}</span><span class="cap2">{s}</span></div>'
    scope = f'<div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px;">{tile("사업 규모","49,844,864원 (부가세 포함)","제안요청서 p.4 §1.3")}{tile("사업 기간","계약 체결일로부터 6개월","제안요청서 p.4 §1.4")}{tile("수행 장소","미확인","이번 입력에서 확인되지 않음",True)}</div>'
    cond = lambda t,ev: f'<li style="display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid #eef0ec; font-size:14px; line-height:1.45;"><span style="display:flex; gap:8px;">{svg(I_CHECK, 14, "#587a2b", 2.4)}<span>{t}</span></span><a href="#" style="font-size:12px; white-space:nowrap;">{ev}</a></li>'
    conditions = cond("소프트웨어사업자 신고확인서 보유","p.7 §2.2")+cond("중소기업 확인서 (중소기업자 간 경쟁)","p.7 §2.2")+cond("정보화 전략 수립(ISP·ISMP) 수행 실적 1건 이상","p.8 §2.3")+cond("PM 1인 · ISP 경력 5년 이상","p.9 §2.4")
    risk = lambda tone,tok,t,d: f'<li class="kv" style="gap:4px; padding:10px 12px; border-radius:10.5px; background:{"#fff8ec" if tone=="orange" else "#f6f7f4"}; border:1px solid {"#f0dcb0" if tone=="orange" else "#eef0ec"};"><div style="display:flex; align-items:center; gap:8px;"><span class="tok tok-{tone}">{tok}</span><span style="font-size:14px; font-weight:600;">{t}</span></div><span style="font-size:13px; line-height:1.5; color:#4c5650;">{d}</span></li>'
    risks = risk("orange","근거 위치 없음","수행 인력 상주 조건","모델이 만든 항목이지만 원문 위치와 연결되지 않았습니다. 검증을 통과시키지 않고 사람 검토로 보냅니다.")+risk("gray","미확인","본공고 · 입찰 예정 시기","사전규격 단계라 본공고 번호가 없습니다. 의견등록 마감 뒤 본공고 발생 여부를 확인합니다.")+risk("gray","미확인","수행 장소 · 상주 여부","이번 개요 입력 범위(앞부분 24쪽)에서 확인되지 않았습니다.")
    fit = f'''<div class="kv" style="gap:10px;">
      <div class="kv" style="gap:4px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;"><div style="display:flex; justify-content:space-between;"><span class="cap">적합성 등급</span><span class="cap">출처 · 판정</span></div><div style="display:flex; align-items:center; gap:8px;"><span class="tok tok-accent" style="height:24px; font-size:13px;">검토 권장</span><span class="cap2">회차 판정 · 2026-09-11</span></div><p style="font-size:13px; line-height:1.5; color:#4c5650;">ISP·ISMP 컨설팅 범위가 회사 수행 영역과 겹치나, 공제사업 도메인 실적이 확인되지 않아 우선 검토가 아닌 검토 권장으로 판정.</p><span class="cap">사람 정정 사유 없음</span></div>
      <div class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; justify-content:space-between;"><span class="cap">회사 업무 부합 여부</span><span class="tok tok-yellow">판단 보류 · 정보 부족</span></div>
        <ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>정보화 전략 수립·아키텍처 설계는 회사 프로필의 컨설팅 실적과 일치</span></li><li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>공제·보험 도메인 실적이 회사 자료에 없어 판단 보류</span></li></ul>
        <span class="cap">모델 참조 결과 · 추적 승인과 최종 입찰 결정은 사람이 진행</span></div></div>'''
    att = lambda name,meta,tok,muted=False: f'<tr><td class="td"><div style="display:flex; align-items:center; gap:8px;">{svg(I_DOC, 16, "#79837c")}<span style="font-weight:600; color:{"#79837c" if muted else "#1b211d"};">{name}</span></div></td><td class="td" style="font-size:12px; color:#4c5650;">{meta}</td><td class="td">{tok}</td><td class="td" style="text-align:right;"><div style="display:inline-flex; gap:12px;"><a href="#" style="font-size:12px;">다운로드</a><a href="#" style="font-size:12px;">원본 열기</a></div></td></tr>'
    attachments = att("제안요청서.hwp","HWP · 2.4 MB · 변환 PDF 62쪽",'<span class="tok tok-accent">본문 추출 완료</span>')+att("과업지시서.hwp","HWP · 1.1 MB · 변환 PDF 18쪽",'<span class="tok tok-accent">본문 추출 완료</span>')+att("붙임3_서식.zip","ZIP · 크기 미확인",'<span class="tok tok-red">본문 추출 실패</span>',True)
    evid = lambda cid,t,p: f'<li style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:6px 0; font-size:13px;"><span style="display:flex; gap:8px;"><span style="font-family:ui-monospace,Menlo,monospace; font-size:12px; color:#79837c;">{cid}</span><span>{t}</span></span><a href="#" style="font-size:12px; white-space:nowrap;">{p}</a></li>'
    evidence = evid("C-01","사업 목적과 배경","제안요청서 p.3")+evid("C-04","주요 과업 4건","제안요청서 p.12–21")+evid("C-07","참여 자격 요건","제안요청서 p.7–9")+evid("C-09","수행 인력 상주 조건",'<span class="tok tok-orange">근거 위치 없음</span>')
    step = lambda n,t,tok,sub,done: f'<div class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid {"#cfdfb5" if done else "#eef0ec"}; background:{"#f9fbf5" if done else "#ffffff"};"><div style="display:flex; align-items:center; gap:8px;"><span style="display:flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:{"#75a03b" if done else "#eef0ec"}; color:{"#ffffff" if done else "#4c5650"}; font-size:12px; font-weight:600;">{n}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>{tok}<span class="cap2">{sub}</span></div>'
    steps = step(1,"첨부 취득",'<span class="tok tok-accent" style="align-self:flex-start;">3건 완료</span>',"완료 3 · 대기 0 · 차단 0 · 실패 0",True)+step(2,"문서 묶음",'<span class="tok tok-accent" style="align-self:flex-start;">확정 완료</span>',"수정본 1 · 차단 issue 0건",True)+step(3,"개요 검토",'<span class="tok tok-accent" style="align-self:flex-start;">완료 · 검증 통과</span>',"qwen3.8-27b · prompt v4 · 2026-09-11 11:05",True)+step(4,"심층 검토",'<span class="tok" style="align-self:flex-start;">실행 대기</span>',"회사 적합성 판단 보류라 자동 시작 조건 미충족",False)
    hist = lambda when,t,d,tone="gray": f'<li style="display:grid; grid-template-columns: 148px 10px minmax(0,1fr); gap:12px; align-items:start; padding:8px 0; border-bottom:1px solid #eef0ec;"><span class="cap2">{when}</span><span style="width:8px; height:8px; border-radius:50%; margin-top:6px; background:{ {"gray":"#c9cfc3","accent":"#75a03b","orange":"#e0a04a"}[tone] };"></span><div class="kv"><span style="font-size:14px; font-weight:600;">{t}</span><span class="cap2">{d}</span></div></li>'
    history = hist("2026-09-11 11:05","개요 검토 완료 · 주장 검증 통과","qwen3.8-27b · prompt v4 · 결과 ID ov_7f3a…c21e · 검토 범위 1–24쪽 (자동 선택)","accent")+hist("2026-09-11 11:02","개요 실행 시도 1 · 사람 검토 필요","C-09 수행 인력 상주 조건이 원문 위치와 연결되지 않음 (evidence_missing)","orange")+hist("2026-09-11 10:58","문서 묶음 확정 · 수정본 1","담당자 김지원 · 제안요청서·과업지시서 포함, 붙임3_서식.zip 제외","accent")+hist("2026-09-11 10:49","사전규격 관측 · 신규","R26BD00273769 · 나라장터 수집 회차 2026-09-11")

    main = f'''<div style="display:flex; width:100%; flex-direction:column; align-items:center;"><div style="display:flex; width:100%; max-width:1040px; flex-direction:column; gap:16px; padding-top:8px;">
      <section class="card" style="display:flex; flex-direction:column;">
        <div class="kv" style="gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
            <div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-outline">사전규격 · 신규</span><span class="tok tok-accent">D-2</span><span class="tok tok-outline">SW사업대상 Y</span><span class="tok tok-outline">본공고 미확인</span><span class="tok tok-outline">일반용역</span></div>
            <div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-accent">추적 결정 · 미선택</span><a href="#" class="cap2">목록으로 돌아가기</a></div>
          </div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2"><span style="font-size:14px; color:#1b211d;">한국예술인복지재단</span><span style="color:#c9cfc3;">·</span><span>사전규격번호 <b style="font-weight:600; color:#1b211d; font-size:14px;">R26BD00273769</b></span><div class="btn btn-ghost" style="height:24px; padding:0 6px; gap:4px;">{svg(I_COPY, 14, "#4c5650")}번호 복사</div><div class="btn btn-ghost" style="height:24px; padding:0 6px; gap:4px;">{svg(I_EXT, 14, "#4c5650")}나라장터 원문</div><span style="color:#c9cfc3;">·</span><span>품명 분류 · 정보화 전략 수립 컨설팅</span></div>
          <div style="display:flex; gap:12px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;"><span class="tok tok-accent" style="flex:0 0 auto;">사업 요약</span><p style="font-size:14px; line-height:1.55;">예술인 공제사업(창작준비금·산재보험 등)을 하나의 통합관리시스템으로 재구축하기 위한 중장기 정보화 전략(ISMP)을 수립하는 사업으로, 현행 3개 시스템의 업무·데이터를 분석해 목표 모델과 3개년 이행 계획을 도출한다. <a href="#" style="font-size:12px;">근거 C-01 · 제안요청서 p.3</a></p></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); border-top:1px solid #eef0ec;">{kpi("사업 예산","49,844,864원","부가세 포함")}{kpi("의견등록 마감",'2026.09.16 23:59 <span class="dday">D-2</span>',"KST")}{kpi("게시","2026.09.11 10:49","KST")}{kpi("구분","일반용역","SW사업대상 Y")}{kpi("적합성 등급",'<span class="tok tok-accent" style="height:24px; font-size:13px;">검토 권장</span>',"등급 출처 · 판정")}{kpi("첨부 원문","3건","본문 추출 2 · 실패 1",last=True)}</div>
      </section>

      <section class="card" style="display:flex; flex-direction:column; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #e6ecdc; background:#f9fbf5; border-radius:14px 14px 0 0;"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">추적 결정</h2><span class="cap2">추적 시작 → <b style="font-weight:600; color:#1b211d;">계속 추적</b></span></div><span class="cap">보류·추적 종료는 <a href="#">사업 추적</a>에서 변경</span></div>
        <div style="display:grid; grid-template-columns: minmax(0,1.4fr) minmax(0,1fr) auto; gap:12px; align-items:end; padding:16px 22px;">
          <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">선택 사유 <span class="cap">· 필수</span></span><div class="field" style="justify-content:space-between; height:36px;"><span>추적을 시작하는 사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div></div>
          <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div></div>
          <div class="btn btn-primary" style="height:36px; padding:0 20px;">추적 시작</div>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 22px 14px;" class="cap"><span>추적을 시작하면 새 문서·입찰공고·정정공고를 계속 확인합니다. 이 이름은 결정 이력에 기록됩니다.</span><span>입찰 참여 여부는 최종 Go/No-Go에서 결정합니다.</span></div>
      </section>

      {sec("주요 과업과 수행 범위", '<span class="tok tok-accent">주장 검증 완료 · 운영 승인 아님</span><a href="#" style="font-size:12px;">전체 근거 PDF 열기 ↗</a>', f'<ol style="display:flex; flex-direction:column;">{tasks}</ol><div class="cap">사업 규모와 일정</div>{scope}')}

      <section class="card" style="display:flex; flex-direction:column;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #eef0ec;"><h2 class="sec-title" style="font-size:15px;">참여 조건 · 회사 적합성 · 위험 및 미확인 사항</h2><span class="cap">적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음</span></div>
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:20px; padding:16px 22px 20px;">
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">참여 조건</span><span class="cap">4건</span></div><ul style="display:flex; flex-direction:column;">{conditions}</ul><span class="cap">지역 제한 · 공동수급 허용 여부 · 미확인</span></div>
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">회사 적합성</span><span class="cap">모델 참조 · 사람이 확정</span></div>{fit}</div>
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">위험 및 미확인 사항</span><span class="cap">주의 1 · 미확인 2</span></div><ul class="kv" style="gap:8px;">{risks}</ul></div>
        </div>
      </section>

      {sec("근거 문서 · 첨부", '<span class="cap">첨부 3건 · 근거 항목 4건</span>', f'<table style="width:100%; border-collapse:collapse;"><thead><tr><th class="th">파일</th><th class="th">형식 · 크기</th><th class="th">본문 추출</th><th class="th" style="text-align:right; padding-right:0;">열기</th></tr></thead><tbody>{attachments}</tbody></table><div class="kv" style="gap:4px;"><div style="display:flex; justify-content:space-between;"><span class="cap">문서 근거 · 개요 검토 결과의 주장별 원문 위치</span><a href="#" style="font-size:12px;">상세에서 근거 원문 열기 →</a></div><ul style="display:flex; flex-direction:column;">{evidence}</ul></div><span class="cap">첨부 원문 열기는 검증된 절대 HTTP(S) 주소만 사용하며 나라장터 원문 URL을 대신하지 않습니다.</span>')}

      {sec("처리 이력 · 문서 준비 · 검토 실행", '<div class="btn btn-outline">문서 준비 열기</div><div class="btn btn-outline">개요 검토 다시 실행</div><div class="btn btn-disabled">심층 검토 보고서 열기 →</div>', f'<div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{steps}</div><span class="cap">조건을 충족하면 심층 검토까지 자동으로 시작합니다. 추적 선택과 최종 입찰 Go/No-Go는 사람이 결정합니다.</span><div class="kv" style="gap:6px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">처리 이력</span><div style="display:flex; gap:12px;"><a href="#" style="font-size:12px;">사전규격 목록 →</a><a href="#" style="font-size:12px;">사업기회 보기 →</a></div></div><ul style="display:flex; flex-direction:column;">{history}</ul></div><div style="display:flex; justify-content:space-between;" class="cap"><span>현재 주장 검증 진단 · 고정 입력과 식별 해시 · 회사 적합성 실행 정보</span><a href="#" style="font-size:12px;">펼치기</a></div>')}
    </div></div>'''
    left = crumbs("탐색과 추적","사전규격","R26BD00273769")
    right = f'<span class="cap2">선택 항목 <b style="font-weight:600; color:#1b211d;">1 / 2</b></span><div class="btn btn-disabled" style="gap:4px;">{svg(I_CHEV_L, 14, "#9aa39c", 2)}이전</div><div class="btn btn-outline" style="gap:4px;">다음{svg(I_CHEV_R, 14, "#1b211d", 2)}</div>'
    return page("사전규격", left, right, main, height=2600, main_style="padding-bottom:40px;")

# ============================================================ 대시보드
def dashboard():
    task = lambda n,t,s,c: f'<div class="kv" style="gap:2px; padding:14px 16px; border-right:1px solid #eef0ec;"><div style="display:flex; justify-content:space-between; align-items:center;"><span style="font-size:14px; font-weight:600;"><span style="color:#79837c; font-weight:500; margin-right:6px;">{n}</span>{t}</span>{svg(I_ARROW_R, 14, "#79837c", 2)}</div><span style="font-size:14px;">{s}</span><span class="cap">{c}</span></div>'
    tasks = (task("01","발주계획","추적할 후보 선택","검토 후보 4건")+task("02","사전규격","검토 결과·추적 여부 확인","결정 대기 8건")+task("03","사업 추적","연결·예외 사항 확인","조치 필요 건수 미확인")+task("04","최종 Go/No-Go","입찰 참여 여부 결정","결정 대기 7건")).replace('border-right:1px solid #eef0ec;">' , '">', 0)
    stat = lambda k,v,u,s,hl=False: f'<div class="card kv" style="gap:6px; padding:18px 20px; {"box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5; background:#f9fbf5;" if hl else ""}"><span class="cap2">{k}</span><span style="font-size:30px; font-weight:600; line-height:1.1; letter-spacing:-0.01em;">{v} <span style="font-size:14px; font-weight:500; color:#4c5650;">{u}</span></span><span class="cap">{s}</span></div>'
    bar = lambda k,p,w,c,r1,r2: f'<div style="display:grid; grid-template-columns: 64px minmax(0,1fr) 150px; gap:16px; align-items:center;"><span style="font-size:14px; color:#4c5650;">{k}</span><div style="height:28px; border-radius:6px; background:#eef0ec; overflow:hidden;"><div style="width:{w}%; height:100%; background:{c}; display:flex; align-items:center; padding-left:10px; box-sizing:border-box; font-size:12px; font-weight:600; color:{"#ffffff" if w>40 else "#1b211d"};">{p}</div></div><div class="kv" style="align-items:flex-end;"><span style="font-size:14px; font-weight:600;">{r1}</span><span class="cap">{r2}</span></div></div>'
    gate = lambda t,tok,val,lim,w,c,sub,hl=False: f'<div class="kv" style="gap:8px; padding:12px 14px; border-radius:10.5px; {"background:#fdf0ec; border:1px solid #f0cfc4;" if hl else "border:1px solid #eef0ec;"}"><div style="display:flex; justify-content:space-between; align-items:center;"><span style="font-size:14px; font-weight:600;">{t} <span style="font-weight:500; color:{"#89001a" if hl else "#4c5650"};">{tok}</span></span><span class="cap2"><b style="font-weight:600; color:{"#89001a" if hl else "#1b211d"};">{val}</b> / {lim}</span></div><div style="height:8px; border-radius:4px; background:#eef0ec; overflow:hidden;"><div style="width:{w}%; height:100%; background:{c};"></div></div><span class="cap">{sub}</span></div>'
    main = f'''<div class="card" style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); overflow:hidden;">{tasks}</div>
    <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 4px;">
      <div style="display:flex; align-items:center; gap:10px;"><span style="font-size:14px; font-weight:600;">회차 자료</span><div class="field" style="width:330px; box-sizing:border-box; justify-content:space-between; color:#1b211d; white-space:nowrap;"><span>2026-09-14 ~ 2026-09-15 · 공고 판정 회차</span>{svg(I_CHEV_D, 16, "#79837c")}</div><span class="tok tok-outline">읽기 전용</span><span class="tok tok-accent">회차 완료</span></div>
      <div style="display:flex; align-items:center; gap:10px;" class="cap2"><span>마감과 집계는 선택한 회차의 기준 시각을 따릅니다</span><a href="#" style="display:flex; align-items:center; gap:4px; font-weight:600;">{svg(I_ARROW_R, 14, "#587a2b", 2)}회차 실행 보기</a></div>
    </div>
    <div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px;">{stat("수집 건수","300","건","수집 산출물 기준 · 용역 본공고")}{stat("후보 풀","36","건","전체 수집의 12.0%")}{stat("우선 검토","9","건",'분석 표본 30건의 30.0% <span class="tok tok-red" style="margin-left:4px;">임계 초과</span>',True)}{stat("1차 필터 누락","5","/ 표본 미확인","감사 표본 분모를 확인할 수 없어 누락률을 계산하지 않습니다")}</div>
    <div style="display:grid; grid-template-columns: minmax(0,1.35fr) minmax(0,1fr); gap:12px; flex:1 1 auto; min-height:0;">
      <section class="card" style="display:flex; flex-direction:column;"><div style="display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid #eef0ec;"><span class="sec-title" style="font-size:15px;">판정 파이프라인</span><span class="cap">수집 → 후보 → 표본 → 검토 대기</span></div>
        <div class="kv" style="gap:14px; padding:18px 20px;">{bar("수집","100%",100,"#3f5a1c","300건","기준")}{bar("후보","12.0%",12,"#75a03b","36건","감소 264건 · 88.0%")}{bar("표본","10.0%",10,"#75a03b","30건","감소 6건 · 16.7%")}{bar("검토 대기","30.0%",30,"#cfdfb5","9건","감소 21건 · 70.0%")}<div style="display:grid; grid-template-columns: 64px minmax(0,1fr) 150px; gap:16px;"><span></span><div style="display:flex; justify-content:space-between;" class="cap"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div><span></span></div></div></section>
      <section class="card" style="display:flex; flex-direction:column;"><div style="display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid #eef0ec;"><span class="sec-title" style="font-size:15px;">검증 통과 기준</span><span class="tok tok-red">3개 중 1개 미달 · 계산 불가 1</span></div>
        <div class="kv" style="gap:10px; padding:16px 20px;">{gate("변별력","미달","30%","10~25%",30,"#c9303a","근거 9 / 30건",True)}{gate("관점 분할","통과","65%","40% 이상",65,"#3f5a1c","근거 26 / 40건")}{gate("근거 타당성","계산 불가","계산 불가","70% 이상",0,"#c9cfc3","선택한 회차에 시스템 판정 평가가 기록된 리뷰가 없습니다")}</div></section>
    </div>'''
    right = f'<div class="btn btn-ghost" style="gap:6px;">{svg(I_REFRESH, 14, "#1b211d", 2)}새로고침</div><div class="btn btn-outline" style="gap:6px;">{svg(I_OPS, 14, "#1b211d", 2)}실행 상태</div>'
    return page("대시보드", crumbs("오늘의 업무","대시보드"), right, main)

# ============================================================ 발주계획
def order_plans():
    R = [("안전교육시스템(LMS) 재구축 ISMP 수립 용역","어린이집안전공제회","4,840만원","2026년 09월",True,False),
         ("[한남대학교 산학협력단] 철도 도메인 특화 RAG 기반 AI 실시간 안전교관 시스템 구축 및 연동 용역","한남대학교 산학협력단","1.3억원","2026년 09월",False,True),
         ("군장대학교 혁신지원사업단 「데이터기반 대학 그룹웨어 고도화」용역","군장대학산학협력단","1억원","2026년 09월",False,False),
         ("2026년도 공공기관 동반성장평가 관리시스템 유지보수 및 기능개선 용역","대·중소기업·농어업협력재단","3,000만원","2026년 09월",False,False),
         ("2026년 다면평가 시스템 구축 용역","가덕도신공항건설공단","1,925만원","2026년 09월",False,False),
         ("2027~2028년 본청 및 학교 홈페이지 유지관리 사업 용역","인천광역시교육청","14.9억원","2026년 09월",False,False),
         ("한국어능력시험(TOPIK) PBT 판독 및 이미지채점시스템 문제 유형 확대 용역","교육부 국립국제교육원","2,890만원","2026년 09월",False,False)]
    rows = "".join(f'''<div class="row {"row-on" if sel else ""}"><div class="check {"check-on" if ck else ""}" style="display:flex; align-items:center; justify-content:center; margin-top:3px;">{svg(I_CHECK, 12, "#ffffff", 3) if ck else ""}</div><div class="kv" style="flex:1 1 auto; min-width:0; gap:3px;"><div style="font-size:15px; font-weight:600; line-height:1.4;">{t}</div><div class="cap2">{a} · {b} · {m}</div></div><span class="tok tok-outline" style="flex:0 0 auto;">모델 관련</span></div>''' for t,a,b,m,sel,ck in R)
    fact = lambda k,v: f'<div class="kv"><span class="cap">{k}</span><span style="font-size:15px; font-weight:600;">{v}</span></div>'
    main = f'''<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 4px;">{utabs([("검토 대상","102",True),("전체","482",False),("BM25 탈락","182",False),("실패·거부","0",False)])}<div style="display:flex; gap:8px;">{search()}{FILTER_BTN}</div></div>
    <div class="card" style="display:flex; flex:1 1 auto; min-height:0; overflow:hidden;">
      <section class="split-l">
        <div class="lh"><span class="sec-title">검토 목록 · 현재 필터 결과 <span style="color:#587a2b;">102건</span></span><span class="cap">1–102 / 102</span></div>
        <div style="display:flex; align-items:center; gap:8px; padding:8px 16px; border-bottom:1px solid #eef0ec;"><span style="font-size:12px; font-weight:600;">선택 1건</span><div class="btn btn-outline">전체 선택</div><div class="btn btn-outline">전체 해제</div><div class="btn btn-primary">선택 항목 검토</div></div>
        <div class="cap" style="padding:6px 16px; border-bottom:1px solid #eef0ec;">기본 보기 · BM25 선정 AND 모델 판단 관련·불확실 · 정렬 관련 → 판단 보류 → 비관련 → 값 없음</div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div>
        <div class="lf"><span>필터 외 BM25 선정 제외·비관련·실패 건은 기본 보기에서 숨김</span></div>
      </section>
      <section class="split-r">
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px; overflow:hidden;">
          <div class="kv" style="gap:6px;"><div style="display:flex; align-items:center; justify-content:space-between;"><div style="display:flex; align-items:center; gap:8px;"><span class="cap">발주기관</span><span style="font-size:13px; font-weight:600;">어린이집안전공제회</span></div><span class="tok tok-outline">추적 결정 없음</span></div><h3 style="font-size:20px; font-weight:600; line-height:1.35;">안전교육시스템(LMS) 재구축 ISMP 수립 용역</h3><div class="cap2">발주계획 <b style="font-weight:600; color:#1b211d;">R26DD20867352</b> · 계획 ID 1873</div></div>
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px;"><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f1f6e8;"><span class="cap">발주계획 예산</span><span style="font-size:16px; font-weight:600;">48,400,000원</span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f1f6e8;"><span class="cap">발주 예정</span><span style="font-size:16px; font-weight:600;">2026년 09월</span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f1f6e8;"><span class="cap">사업 분야</span><span style="font-size:16px; font-weight:600;">일반용역</span></div></div>
          <div class="kv" style="gap:8px;"><div style="display:flex; align-items:center; justify-content:space-between;"><span class="sec-title">관련 근거</span><div style="display:flex; gap:6px;"><span class="tok tok-outline">BM25 선정</span><span class="tok tok-accent">모델 관련</span></div></div>
            <div style="padding:10px 12px; border-radius:10.5px; background:#f6f7f4; font-size:14px; line-height:1.5;">안전교육시스템(LMS) 재구축 ISMP 수립은 공공 정보화 ISP 및 시스템 구축 역량과 직접적으로 관련된다.</div>
            <div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; border:1px solid #eef0ec;"><span style="font-size:14px; font-weight:600;">안전교육시스템(LMS) 재구축 ISMP 수립 용역</span><span class="cap">근거 위치 · 발주계획 사업명</span></div>
            <span class="cap">계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인</span></div>
          <div style="display:flex; gap:16px;"><a href="#" style="font-size:12px;">공고 바로가기</a><a href="#" style="font-size:12px;">사람 판단 수정 · 미입력</a><a href="#" style="font-size:12px;">선별 신호 · 실행 기록</a></div>
        </div>
        <div class="kv" style="gap:10px; padding:12px 18px 14px; border-top:1px solid #eef0ec; background:#fbfcf9;">
          <div style="display:flex; align-items:center; gap:8px;"><span class="sec-title">추적 선택</span><span class="tok tok-outline">추적 결정 없음</span><span class="cap">1 / 102건</span></div>
          <div style="display:flex; align-items:center; gap:8px;"><div class="field" style="flex:1 1 auto; justify-content:space-between;"><span>사유를 선택하세요</span>{svg(I_CHEV_D, 16, "#79837c")}</div><div class="field" style="flex:0 0 168px;"><span>담당자 이름 · 감사 표식</span></div><div class="btn btn-primary" style="height:32px;">추적 시작</div></div>
          <div style="display:flex; align-items:center; justify-content:space-between;"><span class="cap">선택 사유와 담당자 이름을 입력하면 추적 결정을 기록할 수 있습니다.</span><div style="display:flex; gap:8px;"><div class="btn btn-disabled">보류</div><div class="btn btn-disabled">추적 종료</div><div class="btn btn-outline">이번 건 넘기기</div></div></div>
        </div>
      </section>
    </div>'''
    right = f'<div class="field" style="width:250px; box-sizing:border-box; justify-content:space-between; color:#1b211d; font-size:12px; white-space:nowrap;"><span>2026-09-10 ~ 2026-09-12 · 발주계획</span>{svg(I_CHEV_D, 14, "#79837c")}</div><span class="tok tok-accent">성공</span><span class="tok tok-red">모델 연결 비허용</span><a href="#" class="cap2">실행 상세 →</a>'
    return page("발주계획", h1("발주계획"), right, main)

# ============================================================ 사업 추적
def opportunities():
    R = [("예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단 · 사전규격에서 시작 · 연결 2건","계속 추적","#2981",True),
         ("2027~2028년 기관 웹서비스 통합유지관리 사업","서울특별시교육청 · 발주계획에서 시작 · 연결 1건","계속 추적","#2893",False),
         ("통합 업무정보관리 시스템(ECM) 구축 사업","한국은행 · 발주계획에서 시작 · 연결 1건","계속 추적","#2887",False),
         ("전략환경 변화 대응을 위한 민관협업 플랫폼 구축","외교부 · 사전규격에서 시작 · 연결 2건","계속 추적","#2848",False),
         ("서울대학교병원 [전산용역비]SUPREME 2.0 플랫폼 고도화 및 유지보수 사업","서울대학교병원 · 발주계획에서 시작 · 연결 1건","계속 추적","#2798",False),
         ("제주 AX에이전트 원천기술 연구 및 자율대응 실증사업 기획 수립 용역","(재)제주테크노파크 · 발주계획에서 시작 · 연결 1건","계속 추적","#2772",False),
         ("AI 기반 파쇄암 입도 분포 분석 시스템 평가 모듈 통합 및 연계 체계 구축 용역","한국해양대학교 산학협력단 · 발주계획에서 시작 · 연결 1건","계속 추적","#2650",False)]
    rows = "".join(f'<div class="row {"row-on" if sel else ""}" style="align-items:center;"><div class="kv" style="flex:1 1 auto; min-width:0; gap:3px;"><div style="font-size:15px; font-weight:600; line-height:1.4;">{t}</div><div class="cap2">{m}</div></div><span class="tok tok-accent">{s}</span><span class="cap" style="font-family:ui-monospace,Menlo,monospace;">{i}</span></div>' for t,m,s,i,sel in R)
    link = lambda n,k,t,a,when,tok: f'<div style="display:grid; grid-template-columns: 28px minmax(0,1fr) auto; gap:12px; align-items:start; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><span style="display:flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; background:#3f5a1c; color:#ffffff; font-size:12px; font-weight:600;">{n}</span><div class="kv" style="gap:2px;"><div style="display:flex; align-items:center; gap:8px;"><span style="font-size:14px; font-weight:600;">{k}</span><span class="tok tok-outline">{tok}</span></div><span style="font-size:14px;">{t}</span><span class="cap2">{a} · {when}</span></div><a href="#" style="font-size:12px;">열기 →</a></div>'
    main = f'''<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 4px;">{utabs([("조치 필요","0",False),("추적 중","7",True),("보류","0",False),("추적 종료","0",False),("전체","1,124",False)])}<div style="display:flex; gap:8px;">{search()}{FILTER_BTN}</div></div>
    <div class="card" style="display:flex; flex:1 1 auto; min-height:0; overflow:hidden;">
      <section class="split-l"><div class="lh"><span class="sec-title">사업 추적 목록 · <span style="color:#587a2b;">7건</span></span><span class="cap">추적 중 전체 7건</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div>
        <div class="lf" style="flex-direction:column; align-items:flex-start; gap:2px;"><span>불러온 7건 기준 · 7건 표시</span><span>구역이 정해지지 않은 미결정 1,117건은 전체에서만 보입니다.</span></div></section>
      <section class="split-r">
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px; overflow:hidden;">
          <div class="kv" style="gap:6px;"><div class="cap2">사업기회 #2981 · 한국예술인복지재단 · 사전규격에서 시작</div><h3 style="font-size:20px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h3><div style="display:flex; gap:6px;"><span class="tok tok-accent">계속 추적</span><span class="tok tok-outline">다음 행동 · 본공고 확인</span><span class="tok tok-outline">담당 김지원</span></div></div>
          {utabs([("연결 레코드","2",True),("추적 이력",None,False),("시스템 신호",None,False)])}
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">사업 생애주기 · 연결 레코드 2건</span><span class="cap">서버에 저장된 관계를 그대로 표시</span></div>
            {link(1,"사전규격","예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","2026-09-11 관측","확정")}
            {link(2,"발주계획","예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","2026-09-10 회차","확정")}
            <div style="display:grid; grid-template-columns: 28px minmax(0,1fr); gap:12px; align-items:center; padding:12px 14px; border-radius:10.5px; border:1px dashed #c9cfc3;"><span style="display:flex; align-items:center; justify-content:center; width:24px; height:24px; border-radius:50%; background:#eef0ec; color:#4c5650; font-size:12px; font-weight:600;">3</span><span class="cap2">입찰공고 · <b style="font-weight:600; color:#79837c;">미확인</b> · 의견등록 마감(9.16) 뒤 본공고 발생 여부를 확인합니다</span></div></div>
        </div>
        <div class="kv" style="gap:8px; padding:12px 18px 14px; border-top:1px solid #eef0ec; background:#fbfcf9;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:16px;"><div class="kv" style="gap:2px; flex:1 1 auto; min-width:0;"><span class="sec-title">추적 상태 변경</span><span class="cap">보류와 추적 종료는 이 화면에서만 사람이 고릅니다. 필수 사유와 담당자 감사 표식을 새 기록으로 남기며 적합성 등급·심층 검토 승인·최종 Go/No-Go를 바꾸지 않습니다.</span></div><div style="display:flex; gap:8px; flex:0 0 auto;"><span class="tok tok-accent" style="height:28px;">계속 추적</span><div class="btn btn-outline">보류</div><div class="btn btn-outline">추적 종료</div></div></div>
          <a href="#" style="font-size:12px;">이 사업기회만 따로 열기 →</a>
        </div>
      </section>
    </div>'''
    return page("사업 추적", h1("사업 추적"), f'<div class="btn btn-ghost" style="gap:6px;">{svg(I_OPS, 14, "#1b211d", 2)}데이터 현황</div>', main)

# ============================================================ 최종 Go/No-Go
def go_no_go():
    R = [("2027~2028년 기관 웹서비스 통합유지관리 사업","서울특별시교육청 서울특별시교육청교육연구정보원","2893","변경 3건","미결정",True),
         ("예술인 공제사업 통합관리시스템 중장기 ISMP 수립","한국예술인복지재단","2981","비교 대기 · 본공고 미확인","미결정",False),
         ("통합 업무정보관리 시스템(ECM) 구축 사업","한국은행","2887","변경 없음","미결정",False),
         ("전략환경 변화 대응을 위한 민관협업 플랫폼 구축","외교부","2848","비교 대기","미결정",False),
         ("서울대학교병원 [전산용역비]SUPREME 2.0 플랫폼 고도화 및 유지보수 사업","서울대학교병원","2798","비교 대기","미결정",False),
         ("제주 AX에이전트 원천기술 연구 및 자율대응 실증사업 기획 수립 용역","(재)제주테크노파크","2772","변경 없음","Go",False),
         ("AI 기반 파쇄암 입도 분포 분석 시스템 평가 모듈 통합 및 연계 체계 구축 용역","한국해양대학교 산학협력단","2650","변경 1건","No-Go",False)]
    dtok = lambda d: f'<span class="tok {"tok-accent" if d=="Go" else "tok-red" if d=="No-Go" else "tok-outline"}">{d}</span>'
    rows = "".join(f'<div class="row {"row-on" if sel else ""}" style="align-items:center;"><div class="kv" style="flex:1 1 auto; min-width:0; gap:3px;"><div style="font-size:15px; font-weight:600; line-height:1.4;">{t}</div><div class="cap2">{a} · 사업기회 {i} · {c}</div></div>{dtok(d)}</div>' for t,a,i,c,d,sel in R)
    chk = lambda t,s,ok: f'<li style="display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-bottom:1px solid #eef0ec; font-size:14px;"><span style="display:flex; gap:8px; align-items:center;">{svg(I_CHECK, 14, "#587a2b", 2.4) if ok else svg(I_CLOCK, 14, "#79837c", 2)}<span>{t}</span></span><span class="cap2">{s}</span></li>'
    main = f'''<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 4px;">{utabs([("검토 대상","7",True),("재검토","0",False),("결정 기록","2",False),("전체","7",False)])}<div style="display:flex; gap:8px;">{search()}{FILTER_BTN}</div></div>
    <div class="cap" style="display:flex; justify-content:space-between; padding:0 4px; margin-top:-6px;"><span>계속 추적 중인 사업 · 미결정·재검토·조회 미확인 포함</span><span>받은 7건 기준</span></div>
    <div class="card" style="display:flex; flex:1 1 auto; min-height:0; overflow:hidden;">
      <section class="split-l"><div class="lh"><span class="sec-title">결정 검토 목록 · <span style="color:#587a2b;">7건</span></span><span class="cap">사람 결정 기준</span></div>
        <div style="display:flex; justify-content:space-between; padding:4px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span>사업명 / 발주기관</span><span>사람 결정</span></div>
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div><div class="lf"><span>받은 7건 기준 · 7건 표시 · 전체 총계가 아닙니다</span></div></section>
      <section class="split-r">
        <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px; overflow:hidden;">
          <div class="kv" style="gap:6px;"><div style="display:flex; align-items:center; justify-content:space-between;"><div style="display:flex; align-items:center; gap:8px;">{svg(I_BUILDING, 16, "#79837c")}<span class="cap">발주기관</span><span style="font-size:13px; font-weight:600;">서울특별시교육청 교육연구정보원</span></div><span class="tok tok-outline">사람 결정 · 미결정</span></div><h3 style="font-size:20px; font-weight:600; line-height:1.35;">2027~2028년 기관 웹서비스 통합유지관리 사업</h3><div class="cap2">사업기회 2893 · 계속 추적 · 입찰공고 20260910481-00 · 입찰 마감 <b style="font-weight:600; color:#1b211d;">2026.09.26 14:00</b> <span class="dday">D-11</span></div></div>
          {utabs([("검토 요약",None,True),("비교 문서",None,False),("결정 기록",None,False)])}
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px;"><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f1f6e8;"><span class="cap">입찰 delta 비교</span><span style="font-size:16px; font-weight:600;">변경 3건 <span class="tok tok-orange">확인 필요</span></span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f1f6e8;"><span class="cap">심층 검토</span><span style="font-size:16px; font-weight:600;">완료 · 검증 통과</span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f6f7f4;"><span class="cap">추정 가격</span><span style="font-size:16px; font-weight:600; color:#79837c;">미확인</span></div></div>
          <div class="kv" style="gap:4px;"><span class="sec-title">결정 전 확인</span><ul style="display:flex; flex-direction:column;">{chk("사전규격 대비 본공고 변경 사항 확인","변경 3건 · 2026-09-12 비교 · 과업 범위·기간·예산",False)}{chk("참여 자격 · 실적 요건 확인","심층 검토 §2 · 충족 4 / 미확인 1",True)}{chk("제안서 준비 일정 · 마감 D-11","담당자 확인 대기",False)}{chk("추정 가격 · 예산 대비","미확인",False)}</ul></div>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 18px 14px; border-top:1px solid #eef0ec; background:#fbfcf9;">
          <div class="kv" style="gap:2px;"><span class="cap">현재 사람 결정</span><span style="font-size:15px; font-weight:600;">미결정</span><span class="cap">결정은 사유와 담당자 이름을 남기며 추적 상태·적합성 등급을 바꾸지 않습니다.</span></div>
          <div style="display:flex; gap:8px;"><div class="btn btn-outline" style="height:32px;">재검토 요청</div><div class="btn btn-outline" style="height:32px; color:#89001a;">No-Go 기록</div><div class="btn btn-primary" style="height:32px;">Go 기록</div></div>
        </div>
      </section>
    </div>'''
    return page("최종 Go/No-Go", h1("최종 Go/No-Go"), f'<div class="btn btn-ghost" style="gap:6px;">{svg(I_OPS, 14, "#1b211d", 2)}데이터 현황</div>', main)

# ============================================================ 판정 기준
def criteria():
    S = [("1 Company Identity","6개 항목 · 하위 절 0개 · 미확인 0개","확정","accent",True),("2 Company Capability","19개 항목 · 하위 절 17개 · 미확인 7개 · 구조화 실패 6건","혼합 상태","",False),("3 Business Evidence","6개 항목 · 하위 절 4개 · 미확인 0개 · 구조화 실패 2건","혼합 상태","",False),("4 Business Preference","8개 항목 · 하위 절 8개 · 미확인 5개","혼합 상태","",False),("5 Business Constraint","4개 항목 · 하위 절 6개 · 미확인 3개 · 구조화 실패 1건","혼합 상태","",False),("6 Unknown / To Be Confirmed","0개 항목 · 하위 절 0개 · 구조화 실패 1건","상태 미기록","outline",False),("7 Profile Metadata","0개 항목 · 하위 절 0개 · 구조화 실패 1건","상태 미기록","outline",False)]
    rows = "".join(f'<div class="row {"row-on" if sel else ""}" style="align-items:center;"><div class="kv" style="flex:1 1 auto; gap:3px;"><span style="font-size:15px; font-weight:600;">{t}</span><span class="cap2">{m}</span></div><span class="tok {"tok-"+tone if tone else ""}">{s}</span></div>' for t,m,s,tone,sel in S)
    tr = lambda k,v: f'<tr><td class="td" style="font-family:ui-monospace,Menlo,monospace; font-size:13px; font-weight:600;">{k}</td><td class="td">{v}</td><td class="td"><span class="tok tok-accent">확정</span></td></tr>'
    table = tr("employees","58")+tr("rnd_ratio","70%")+tr("revenue_2025","38억원")+tr("credit_rating","BBO")+tr("project_solution_count","151건 이상")+tr("inhouse_solution_ratio","주요 솔루션 100% 자체개발로 소개")
    main = f'''<div style="padding:0 4px;">{utabs([("회사 프로필",None,True),("판정 정책",None,False),("품질 게이트",None,False),("검증 지표",None,False)])}</div>
    <div class="card" style="display:flex; flex-direction:column; flex:1 1 auto; min-height:0; overflow:hidden;">
      <div style="display:flex; align-items:center; gap:16px; padding:10px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span>기준 프로필 <b style="font-family:ui-monospace,Menlo,monospace; font-weight:600; color:#1b211d;">company-profile.sha256:381…6ac311</b></span><span class="tok tok-outline">읽기 전용</span><span style="color:#c9cfc3;">|</span><span>판정 정책 <b style="font-weight:600; color:#1b211d;">운영 활성 없음</b></span><span style="margin-left:auto;">미확인 항목 <b style="font-weight:600; color:#1b211d;">15</b></span></div>
      <div style="display:flex; flex:1 1 auto; min-height:0;">
        <section class="split-l"><div class="lh"><span class="sec-title">기준 항목</span><span class="cap">7건</span></div>
          <div class="kv" style="gap:8px; padding:10px 16px; border-bottom:1px solid #eef0ec;">{search(999, "항목·내용 검색").replace("width:999px;", "width:100%;")}<div style="display:flex; gap:4px;"><span class="tok tok-accent">전체</span><span class="tok tok-outline">확정</span><span class="tok tok-outline">추정</span><span class="tok tok-outline">미확인</span></div></div>
          <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div>
          <div class="lf"><span>확정 <b style="font-weight:600; color:#1b211d;">24</b> · 추정 <b style="font-weight:600; color:#1b211d;">4</b> · 미확인 <b style="font-weight:600; color:#1b211d;">15</b> · 승인된 구조화 사본 · 읽기 전용</span></div></section>
        <section class="split-r">
          <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px; overflow:hidden;">
            <div style="display:flex; align-items:flex-start; justify-content:space-between;"><div class="kv" style="gap:4px;"><span class="cap">회사 프로필 · 승인 사본</span><h3 style="font-size:20px; font-weight:600; line-height:1.35;">1 Company Identity</h3><span class="cap2">구조화 항목 6개 · 미확인 0개</span></div><span class="tok tok-outline">읽기 전용</span></div>
            <table style="width:100%; border-collapse:collapse;"><thead><tr><th class="th">항목</th><th class="th">내용</th><th class="th">확인 상태</th></tr></thead><tbody>{table}</tbody></table>
            <a href="#" class="cap2" style="display:flex; align-items:center; gap:4px;">{svg(I_CHEV_R, 12, "#4c5650", 2)}기술 키와 판정 참조 횟수 · Company Identity</a>
            <div class="kv" style="gap:6px;"><span class="sec-title">미확인 항목 참조 횟수</span><span class="cap">판정의 근거 source·fact와 확인 항목 why에서 절 번호 또는 항목 이름이 언급된 횟수입니다.</span><div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:8px;"><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f6f7f4;"><span class="cap">프로필 전체 미확인 항목</span><span style="font-size:16px; font-weight:600;">15건</span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f6f7f4;"><span class="cap">이 절의 미확인 항목</span><span style="font-size:16px; font-weight:600;">0건</span></div></div></div>
          </div>
          <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 18px; border-top:1px solid #eef0ec; background:#fbfcf9;"><span class="cap2" style="display:flex; align-items:center; gap:6px;">{svg(I_LOCK, 14, "#79837c")}승인 사본은 이 화면에서 편집할 수 없습니다.</span><div class="btn btn-outline">사본 정보</div></div>
        </section>
      </div>
    </div>
    <span class="cap" style="padding:0 4px;">기준 변경은 이후 실행에만 적용되며 과거 판정을 소급해 바꾸지 않습니다. 적합성 등급 · 참여 준비 · 추적 선택 · 최종 Go/No-Go는 별도 판단입니다.</span>'''
    return page("판정 기준", crumbs("기준과 운영","판정 기준"), "", main)

# ============================================================ 실행 상태
def run_status():
    R = [("공고 판정 회차","2026-09-14 ~ 2026-09-15","2026. 9. 15. 오전 10:52 · 수집 300 · 회차 완료 · 판정 실행 조회 범위 안 기록 없음",True),("발주계획 회차","2026-09-10 ~ 2026-09-12","2026. 9. 11. 오후 2:14 · 수집 값 없음 · 회차 완료 · 판정 실행 조회 범위 안 기록 없음",False),("공고 판정 회차","2026-09-10 ~ 2026-09-11","2026. 9. 11. 오후 2:13 · 수집 342 · 회차 완료 · 판정 실행 조회 범위 안 기록 없음",False)]
    rows = "".join(f'<div class="row {"row-on" if sel else ""}"><div class="kv" style="flex:1 1 auto; gap:3px;"><div style="display:flex; justify-content:space-between; align-items:center;"><span style="font-size:15px; font-weight:600;">{t}</span><span class="tok tok-outline">판정 실행 없음</span></div><span style="font-size:14px;">{p}</span><span class="cap2">{m}</span></div></div>' for t,p,m,sel in R)
    stage = lambda t,s,d,done: f'<div class="kv" style="gap:4px; padding:12px 14px; border-radius:10.5px; border:1px solid {"#cfdfb5" if done else "#eef0ec"}; background:{"#f9fbf5" if done else "#ffffff"};"><div style="display:flex; align-items:center; gap:6px; font-size:14px; font-weight:600;">{svg(I_CHECK, 14, "#587a2b", 2.4) if done else svg(I_CLOCK, 14, "#79837c", 2)}{t}</div><span class="cap2">{s}</span><span class="cap">{d}</span></div>'
    kv = lambda k,v: f'<div class="kv" style="gap:2px;"><span class="cap">{k}</span><span style="font-size:15px; font-weight:600;">{v}</span></div>'
    main = f'''<div style="padding:0 4px;">{utabs([("수집 실행",None,True),("첨부 확보",None,False),("상시 운영",None,False),("산출물 감사 로그",None,False)])}</div>
    <div class="card" style="display:flex; flex-direction:column; flex:1 1 auto; min-height:0; overflow:hidden;">
      <div style="display:flex; align-items:center; gap:14px; padding:10px 16px; border-bottom:1px solid #eef0ec; font-size:12px; color:#4c5650;"><span>상시 운영 <b style="font-weight:600; color:#1b211d;">꺼짐</b> <span class="cap">설정 꺼짐 · 환경 차단</span></span><span style="color:#c9cfc3;">|</span><span>현재 실행 <b style="font-weight:600; color:#1b211d;">0건</b></span><span style="color:#c9cfc3;">|</span><span>조회 범위 <b style="font-weight:600; color:#1b211d;">최근 0건 / 전체 0건</b> <span class="cap">범위 밖 미확인</span></span><span style="color:#c9cfc3;">|</span><span>마지막 성공 조회 <b style="font-weight:600; color:#1b211d;">오후 1:13:21</b></span><a href="#" style="margin-left:auto; font-size:12px;">운영 조건</a><div class="btn btn-ghost" style="gap:6px;">{svg(I_REFRESH, 14, "#1b211d", 2)}새로고침</div></div>
      <div style="display:flex; flex:1 1 auto; min-height:0;">
        <section class="split-l"><div class="lh"><span class="sec-title">실행 회차 목록</span><span class="cap">3건</span></div>
          <div class="kv" style="gap:8px; padding:10px 16px; border-bottom:1px solid #eef0ec;">{search(999, "회차·기간 검색").replace("width:999px;", "width:100%;")}<div style="display:flex; gap:4px;"><span class="tok tok-accent">전체 3</span><span class="tok tok-outline">실행 중 0</span><span class="tok tok-outline">확인 필요 0</span></div></div>
          <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; overflow:hidden;">{rows}</div>
          <div class="lf"><span>받은 회차 3건 · 표시 3건 · 판정 실행 상태는 최근 0건 조회 범위 기준이며 범위 밖은 미확인입니다</span></div></section>
        <section class="split-r">
          <div style="display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:14px; padding:14px 18px; overflow:hidden;">
            <div class="kv" style="gap:4px;"><div style="display:flex; justify-content:space-between;"><span class="cap">선택한 회차 · 2026-09-14 ~ 2026-09-15</span><span class="tok tok-outline">판정 실행 없음</span></div><h3 style="font-size:20px; font-weight:600; line-height:1.35;">공고 판정 회차</h3><div style="display:flex; justify-content:space-between; align-items:center;"><span class="cap2" style="font-family:ui-monospace,Menlo,monospace;">prespecs-20260914-live-20260915T1200--20260915T015208.137811Z · 생성 2026. 9. 15. 오전 10:52 · 수집 회차 완료</span><span class="tok tok-outline">품질 표식 미제공</span></div></div>
            {utabs([("진행 현황",None,True),("실패 내역 미확인",None,False),("실행 기록",None,False),("실행 기준",None,False)])}
            <div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{stage("수집·정규화","완료","수집 300 · 후보 36",True)}{stage("표본 선정","완료","표본 300건",True)}{stage("공고 판정","대기","판정 0건",False)}{stage("보고 생성","대기","보고 산출물",False)}</div>
            <div class="kv" style="gap:6px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">전체 후보 판정 실행</span><span class="cap">실행 기록 없음</span></div><div class="kv" style="gap:2px; padding:10px 12px; border-radius:10.5px; background:#f6f7f4;"><span style="font-size:14px; font-weight:600;">이 회차에는 조회 범위 안의 전량 판정 실행이 없습니다</span><span class="cap">범위 밖에 실행이 있을 수 있습니다. 없음을 실행 0건이나 성공으로 읽지 않습니다.</span></div></div>
            <div class="kv" style="gap:8px;"><span class="sec-title">수집 범위</span><div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:10px;">{kv("수집","300건")}{kv("판정 후보","36건")}{kv("감사 층","264건")}{kv("표본","300건")}{kv("적재된 판정","0건")}{kv("담당자 리뷰","0건")}</div><span class="cap">수집·정규화 건수와 판정 후보·시도 건수는 다른 값입니다. 두 건수를 합치거나 서로 대신하지 않습니다.</span></div>
          </div>
          <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 18px; border-top:1px solid #eef0ec; background:#fbfcf9;"><span class="cap">결과 게시 전</span><div style="display:flex; gap:8px;"><div class="btn btn-outline" style="gap:6px;">{svg(I_SLIDERS, 14, "#1b211d", 2)}파이프라인 실행</div><div class="btn btn-primary" style="gap:6px;">{svg(I_PLAY, 14, "#ffffff", 2)}전량 판정 대기열에 넣기</div></div></div>
        </section>
      </div>
    </div>
    <span class="cap" style="padding:0 4px;">진행 상태와 품질 표식은 별도입니다. 미확인·미측정을 0이나 성공으로 표시하지 않습니다. 추적 승인과 최종 입찰 Go/No-Go는 이 화면에서 결정하지 않습니다.</span>'''
    return page("실행 상태", crumbs("기준과 운영","실행 상태"), "", main)

write("PreSpecDetail", detail()); write("Dashboard", dashboard()); write("OrderPlans", order_plans()); write("Opportunities", opportunities()); write("GoNoGo", go_no_go()); write("Criteria", criteria()); write("RunStatus", run_status())
print("ok")
