"""심층 검토 화면 시안 4장과 canvas.json을 만든다. 예시 데이터이며 운영 사실이 아니다."""
import json, pathlib
from report_v2 import artboard_report_v2
from report_reb import artboard_report_reb
from common import (page, icon, nav_right, detail_header, tracking_card, tasks_card,
                    evidence_collapsed, step, timeline)

OUT = pathlib.Path(__file__).resolve().parents[1] / "artboards"
OUT.mkdir(parents=True, exist_ok=True)

SUB_STAGES = ["회사 적합성", "요구사항·자격·평가", "수행·위험·경제성", "종합·검증"]


def substage_row(states, details):
    cells = []
    for i, (name, st, d) in enumerate(zip(SUB_STAGES, states, details)):
        if st == "done":
            head = f'<span style="display:flex; align-items:center; gap:6px; font-size:13px; font-weight:600;">{icon("check", "#587a2b", 14, 2.4)}{name}</span>'
            bar = '<div class="bar"><span style="width:100%; background:#3f5a1c;"></span></div>'
        elif st == "running":
            head = f'<span style="display:flex; align-items:center; gap:6px; font-size:13px; font-weight:600; color:#3f5a1c;">{icon("spin", "#75a03b", 14, 2.4)}{name}</span>'
            bar = '<div class="bar"><span style="width:58%;"></span></div>'
        else:
            head = f'<span style="display:flex; align-items:center; gap:6px; font-size:13px; font-weight:500; color:#79837c;">{icon("clock", "#9aa39c", 14, 2)}{name}</span>'
            bar = '<div class="bar"></div>'
        cells.append(f'<div class="kv" style="gap:6px; padding:10px 12px; border-radius:10.5px; background:#ffffff; border:1px solid #eef0ec;"><div style="display:flex; justify-content:space-between; align-items:center;">{head}<span class="mono">{i+1}/4</span></div>{bar}<span class="cap2">{d}</span></div>')
    return f'<div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{"".join(cells)}</div>'


# ---------------------------------------------------------------------------
# 1. 사전규격 상세 · 심층 검토 진행 중
# ---------------------------------------------------------------------------

def artboard_running():
    steps = "".join([
        step(1, "첨부 취득", '<span class="tok tok-accent" style="align-self:flex-start;">3건 완료</span>', "완료 3 · 차단 0 · 실패 0", "done"),
        step(2, "문서 묶음", '<span class="tok tok-accent" style="align-self:flex-start;">확정 완료</span>', "제안요청서·과업지시서 · 80쪽", "done"),
        step(3, "개요 검토", '<span class="tok tok-accent" style="align-self:flex-start;">완료 · 검증 통과</span>', "범위 3~6쪽 · 목차 자동 선택", "done"),
        step(4, "심층 검토", '<span class="tok tok-accent" style="align-self:flex-start;">진행 중 · 2/4 단계</span>', "시작 13:02 · 경과 4분", "running"),
    ])
    progress = f"""<div class="kv" style="gap:10px; padding:14px 16px; border-radius:10.5px; background:#f6f7f4;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:10px;"><span class="sec-title">심층 검토 진행</span><span class="tok tok-outline">참조 실행 · 품질 미측정</span></div><span class="cap2">첨부 원문 전체 · 문서 묶음 수정본 1 · 회사 프로필 v3 · 분석 정책 lean-v1</span></div>
          {substage_row(["done", "running", "wait", "wait"], ["완료 · 부합 · 호출 1 · 3.1k/0.6k tok", "요구사항 청크 7/12 · 호출 7 · 58k/9k tok", "대기", "대기"])}
          <div style="display:flex; align-items:center; gap:8px;" class="cap">{icon("lock", "#79837c", 13)}<span>분석하는 동안 문서 묶음·회사 프로필·정책은 고정됩니다. 새 첨부가 들어오면 이번 분석에 섞지 않고 다음 회차로 남깁니다.</span></div>
        </div>"""
    tl = timeline([
        ("2026-09-16 13:03", "#75a03b", "심층 검토 1단계 완료 · 회사 적합성 부합", "사유 3건 · 확인할 사항 1건 · 원응답 암호화 보관"),
        ("2026-09-16 13:02", "#75a03b", "심층 검토 시작 · 담당자 김지원", "개요 검토 완료 뒤 사람이 시작 · 불변 입력 해시 9c1e…a07b"),
        ("2026-09-16 12:58", "#75a03b", "개요 검토 완료 · 주장 검증 통과", "qwen3.8-27B · policy v7 · 범위 3~6쪽(목차) · 호출 2 · 2.6k/1.9k tok"),
        ("2026-09-11 10:58", "#75a03b", "문서 묶음 확정 · 수정본 1", "제안요청서·과업지시서 포함, 붙임3_서식.zip 제외"),
    ])
    process = f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><h2 class="sec-title" style="font-size:15px;">처리 이력 · 문서 준비 · 검토 실행</h2><div style="display:flex; align-items:center; gap:10px;"><div class="btn btn-outline">문서 준비 열기</div><div class="btn btn-outline">진행 상황 보기 →</div></div></div>
        <div class="body"><div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{steps}</div>
        {progress}
        <span class="cap">추적 선택과 최종 입찰 Go/No-Go는 사람이 결정합니다. 심층 검토가 끝나도 추적 상태는 바뀌지 않습니다.</span>
        {tl}</div>
      </section>
"""
    fit = """<div class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; justify-content:space-between; align-items:center;"><span class="cap">심층 검토 1단계 · 회사 업무 부합 여부</span><span class="tok tok-accent">부합</span></div>
          <ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>정보화 전략·목표 모델 수립은 회사의 ISP·ISMP 컨설팅 수행 역할과 일치</span></li><li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>공제·보험 업무 도메인 실적은 회사 자료에서 확인되지 않음</span></li></ul>
          <span class="cap">개요 3섹션과 회사 구조화 정보만 대조 · 자격·실적 충족 판단이 아님</span></div>"""
    skel = lambda n: "".join(f'<div class="skel" style="width:{w}%;"></div>' for w in n)
    conditions = f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">참여 조건 · 회사 적합성 · 위험 및 미확인 사항</h2><span class="tok">심층 검토 2/4 단계 진행 중</span></div><span class="cap">적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음</span></div>
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:20px; padding:16px 22px 20px;">
          <div class="kv" style="gap:10px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">참여 조건</span><span class="cap">2단계에서 채워짐</span></div>{skel([92, 78, 85, 64])}<span class="cap">참가 자격 matrix가 완료되면 표시합니다.</span></div>
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">회사 적합성</span><span class="cap">모델 참조 · 사람이 확정</span></div>{fit}</div>
          <div class="kv" style="gap:10px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">위험 및 미확인 사항</span><span class="cap">3단계에서 채워짐</span></div>{skel([88, 70, 94, 58])}<span class="cap">수행·위험·경제성 단계가 완료되면 표시합니다.</span></div>
        </div>
      </section>
"""
    status_chip = '<span class="tok tok-accent">심층 검토 진행 중</span>'
    cards = detail_header(status_chip) + tracking_card() + tasks_card() + evidence_collapsed() + process + conditions
    return page(2200, ["탐색과 추적", "사전규격", "R26BD00273769"], nav_right(), cards)


# ---------------------------------------------------------------------------
# 보고서 공통
# ---------------------------------------------------------------------------

def report_head(chips, metrics):
    mcells = "".join(
        f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px;{" border-right:1px solid #eef0ec;" if i < len(metrics)-1 else ""}"><span class="cap">{k}</span><span style="font-size:17px; font-weight:600; line-height:1.3; color:{c};">{v}</span><span class="cap">{s}</span></div>'
        for i, (k, v, s, c) in enumerate(metrics))
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="kv" style="gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:6px;">{chips}</div><div style="display:flex; align-items:center; gap:10px;"><span class="cap2">보고서 수정본 1</span><a href="#" class="cap2">사전규격 상세로 돌아가기</a></div></div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">심층 검토 보고서</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2"><span style="font-size:14px; color:#1b211d;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</span><span style="color:#c9cfc3;">·</span><span>한국예술인복지재단</span><span style="color:#c9cfc3;">·</span><span>R26BD00273769</span></div>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;" class="cap">{icon("lock", "#79837c", 13)}<span>고정 입력 · 문서 묶음 수정본 1(제안요청서·과업지시서 80쪽) · 회사 프로필 v3 · 분석 정책 lean-v1 · qwen3.8-27B · 2026-09-16 13:02~13:13</span></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat({len(metrics)}, minmax(0,1fr)); border-top:1px solid #eef0ec;">{mcells}</div>
      </section>
"""


def toc(active, marks):
    items = [("decision", "의사결정 카드"), ("fit", "회사 적합성"), ("elig", "참가 자격"), ("req", "요구사항 대응"),
             ("eval", "평가·배점과 제안 전략"), ("risk", "위험"), ("econ", "경제성"), ("actions", "질문·내부 조치"),
             ("limits", "문서 묶음·한계"), ("opinion", "심층검토 의견")]
    rows = "".join(
        f'<a href="#" style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; border-radius:5.25px; font-size:13px; {"background:#f1f6e8; color:#3f5a1c; font-weight:600;" if k == active else "color:#4c5650;"}"><span>{t}</span>{marks.get(k, "")}</a>'
        for k, t in items)
    return f'<div class="card kv" style="gap:2px; padding:12px 10px;"><span class="cap" style="padding:0 10px 6px;">보고서 절</span>{rows}</div>'


def evidence_viewer():
    return f"""<div class="card kv" style="gap:10px; padding:14px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center;"><span class="sec-title">원문 근거</span><a href="#" style="font-size:12px;">PDF 열기 ↗</a></div>
      <div class="kv" style="gap:4px;"><span class="cap">선택한 근거 · 참가 자격 3행</span><span style="font-size:13px; font-weight:600;">제안요청서.hwp · p.8 · 2.3 입찰참가자격</span></div>
      <div style="padding:12px; border-radius:10.5px; background:#fbfcf9; border:1px solid #eef0ec; font-size:13px; line-height:1.7; color:#4c5650;">
        <p>가. 「소프트웨어 진흥법」 제58조에 따른 소프트웨어사업자로 신고한 자</p>
        <p>나. 「중소기업제품 구매촉진 및 판로지원에 관한 법률」에 따른 중소기업자</p>
        <p><span class="hl">다. 최근 5년 이내 공공기관 정보화전략계획(ISP·ISMP) 수립 실적 1건 이상을 보유한 자</span></p>
        <p>라. 공동수급은 허용하지 아니함</p>
      </div>
      <span class="cap">검증 · 인용이 원문 p.8에 한 번 대응 · page text sha 4f2c…91de</span>
    </div>"""


def table(head, rows, widths=None):
    th = "".join(f'<th class="th"{f" style=&quot;width:{w}&quot;" if False else ""}>{h}</th>' for h in head)
    body = "".join("<tr>" + "".join(f'<td class="td">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="width:100%; border-collapse:collapse; table-layout:auto;"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def pg(p):
    return f'<a href="#" style="font-size:12px; white-space:nowrap;">{p}</a>'


def section(title, right, body, extra_style=""):
    return f"""      <section class="card" style="display:flex; flex-direction:column;{extra_style}">
        <div class="hdr"><h2 class="sec-title" style="font-size:15px;">{title}</h2><div style="display:flex; align-items:center; gap:10px;">{right}</div></div>
        <div class="body">{body}</div>
      </section>
"""


def two_col(main, rail):
    return f'<div style="display:grid; grid-template-columns: minmax(0,1fr) 300px; gap:16px; align-items:start;"><div class="kv" style="gap:16px;">{main}</div><div class="kv" style="gap:16px;">{rail}</div></div>'


# ---------------------------------------------------------------------------
# 2. 심층 검토 보고서 · 완료
# ---------------------------------------------------------------------------

def artboard_report():
    chips = '<span class="tok tok-accent">심층 검토 · 완료</span><span class="tok tok-accent">검증 통과 · 경고 2</span><span class="tok tok-outline">참조 실행 · 품질 미측정</span>'
    metrics = [("분석 단계", "4 / 4 완료", "회사 적합성 → 종합·검증", "#1b211d"),
               ("소요 시간", "11분", "13:02 ~ 13:13", "#1b211d"),
               ("모델 호출", "23회", "재시도 1회 포함", "#1b211d"),
               ("토큰 (입력 / 출력)", "186k / 31k", "provider usage 기준", "#1b211d"),
               ("검증", "통과", "실패 0 · 경고 2", "#3f5a1c")]
    decision = f"""      <section class="card" style="display:flex; flex-direction:column; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #e6ecdc; background:#f9fbf5; border-radius:14px 14px 0 0;"><h2 class="sec-title" style="font-size:15px;">의사결정 카드</h2><span class="cap">시스템 권고는 최종 Go/No-Go가 아닙니다</span></div>
        <div class="body">
          <div style="display:flex; align-items:center; gap:14px;"><span class="cap2" style="font-weight:600; color:#1b211d;">시스템 권고</span><span class="tok tok-strong" style="height:28px; font-size:14px; padding:0 12px;">조건부 추진 검토</span><span class="cap2">선결 조건 2건을 확인하면 추진 검토로 볼 수 있음</span></div>
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:16px;">
            <div class="kv" style="gap:6px;"><span class="cap">추진 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:6px;">{icon("check", "#587a2b", 14, 2.4)}<span>ISMP 수립 과업이 회사 수행 역할과 일치 {pg("p.4")}</span></li><li style="display:flex; gap:6px;">{icon("check", "#587a2b", 14, 2.4)}<span>참가 자격 5개 중 3개 충족 확인 {pg("p.8")}</span></li><li style="display:flex; gap:6px;">{icon("check", "#587a2b", 14, 2.4)}<span>기술 80·가격 20 협상 계약 {pg("p.11")}</span></li></ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">선결 조건</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:6px;">{icon("alert", "#6e3500", 14, 2)}<span>PM ISP 경력 5년 인력 확보 확인</span></li><li style="display:flex; gap:6px;">{icon("alert", "#6e3500", 14, 2)}<span>6개월 내 3개 시스템 분석 가능한 투입 계획</span></li></ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">반대 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:6px;">{icon("x", "#89001a", 14, 2)}<span>공제·보험 도메인 실적이 회사 자료에 없음</span></li><li style="display:flex; gap:6px;">{icon("x", "#89001a", 14, 2)}<span>공동수급 불허로 도메인 파트너 구성 불가 {pg("p.8")}</span></li></ul></div>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; padding-top:10px; border-top:1px solid #eef0ec;" class="cap"><span>다음 행동 · 사전규격 상세에서 추적 결정 → 입찰공고가 나오면 변경 비교 → 최종 Go/No-Go</span><div style="display:flex; gap:10px;"><div class="btn btn-outline">사전규격 상세에서 추적 결정 →</div></div></div>
        </div>
      </section>
"""
    fit = section("1단계 · 회사 적합성", '<span class="tok tok-accent">부합</span><span class="cap">개요 3섹션 × 회사 구조화 정보</span>', f"""
          <p style="font-size:14px; line-height:1.55;">정보화 전략·목표 모델 수립 과업은 회사의 ISP·ISMP 컨설팅 수행 역할과 일치합니다. 공제·보험 업무 도메인 실적은 회사 자료에서 확인되지 않았습니다.</p>
          {table(["구분", "공고 과업 (개요)", "회사 정보", "근거"], [
              ['<span class="tok tok-accent">범위 일치</span>', "통합관리시스템 목표 모델·정보화 전략 수립", '수행 역할 · ISP·ISMP 컨설팅 <span class="tok tok-outline">confirmed</span>', pg("p.5")],
              ['<span class="tok tok-accent">범위 일치</span>', "3개년 단계별 이행 계획과 소요 예산 산정", '대표 실적 · 공공 ISP 3건 <span class="tok tok-outline">confirmed</span>', pg("p.6")],
              ['<span class="tok">정보 부족</span>', "예술인 공제사업 업무 분석", '업무 도메인 · 공제·보험 <span class="tok tok-outline">unknown</span>', pg("p.4")],
          ])}
          <span class="cap">확인할 사항 · 공제·보험 도메인 유사 실적 보유 여부(담당: 기획부) · 모델 참조 결과이며 자격·실적 충족 판단이 아닙니다</span>""")
    elig = section("참가 자격 matrix", '<span class="cap">충족 확인 3 · 미확인 2 · 불충족 0</span>', table(
        ["자격 항목", "공고 요구", "회사 사실", "판정", "근거"], [
            ["소프트웨어사업자", "SW진흥법 제58조 신고", "신고확인서 보유", '<span class="tok tok-accent">충족 확인</span>', pg("p.8")],
            ["기업 규모", "중소기업자 간 경쟁", "중소기업 확인서 보유", '<span class="tok tok-accent">충족 확인</span>', pg("p.8")],
            ["유사 실적", "최근 5년 ISP·ISMP 1건 이상", "공공 ISP 3건 (2022~2025)", '<span class="tok tok-accent">충족 확인</span>', pg("p.8")],
            ["투입 인력", "PM ISP 경력 5년 이상", '<span style="color:#9aa39c; font-weight:600;">미확인</span>', '<span class="tok">미확인</span><div class="cap">확인 · 인사팀 · 09.18</div>', pg("p.9")],
            ["보안", "보안서약서·보안교육 이수", '<span style="color:#9aa39c; font-weight:600;">미확인</span>', '<span class="tok">미확인</span><div class="cap">제출 시점 확인</div>', pg("p.10")],
        ]))
    req = section("요구사항 대응 matrix", '<span class="tok tok-accent">문서 ID 14건 모두 다룸 · 누락 0</span>', f"""
          <div style="display:flex; gap:8px; flex-wrap:wrap;"><span class="tok tok-accent">대응 가능 9</span><span class="tok tok-yellow">추가 확인 3</span><span class="tok tok-red">갭 1</span><span class="tok tok-outline">해당 없음 1</span></div>
          {table(["ID", "요구사항", "대응 상태", "회사 근거 · 차이", "근거"], [
              ['<span class="mono">CSR-001</span>', "현행 업무·시스템 현황 분석", '<span class="tok tok-accent">대응 가능</span>', "공공 ISP 3건의 현황 분석 산출물", pg("p.12")],
              ['<span class="mono">CSR-004</span>', "데이터 표준화·이관 방안 수립", '<span class="tok tok-accent">대응 가능</span>', "데이터 표준화 실적 보유", pg("p.14")],
              ['<span class="mono">CSR-007</span>', "외부 기관 연계(국세청·근로복지공단) 방안", '<span class="tok tok-yellow">추가 확인</span>', "연계 아키텍처 경험은 있으나 해당 기관 연계 실적 미확인", pg("p.15")],
              ['<span class="mono">CSR-010</span>', "공제사업 보험수리 모델 검토", '<span class="tok tok-red">갭</span>', "보험수리 전문 인력이 회사 자료에 없음", pg("p.17")],
              ['<span class="mono">CSR-013</span>', "정보보호 관리체계 인증 준비 지원", '<span class="tok tok-outline">해당 없음</span>', "문서상 발주기관 수행 범위", pg("p.19")],
          ])}
          <div style="display:flex; justify-content:space-between;" class="cap"><span>문서가 준 요구사항 ID 집합과 보고서 주장이 다룬 ID를 결정적으로 대조했습니다.</span><a href="#" style="font-size:12px;">나머지 9건 펼치기</a></div>""")
    evaln = section("평가·배점과 제안 전략", '<span class="tok tok-accent">배점 합계 100 · 코드 재계산 일치</span>', f"""
          <div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:16px;">
            <div class="kv" style="gap:6px;"><span class="cap">배점표 (원문)</span>{table(["항목", "배점"], [["기술평가 · 정량", "20"], ["기술평가 · 정성", "60"], ["가격평가", "20"], ['<b style="font-weight:600;">합계</b>', '<b style="font-weight:600;">100</b>']])}<span class="cap">협상적격자 · 기술점수 85% 이상 {pg("p.11")}</span></div>
            <div class="kv" style="gap:6px;"><div style="display:flex; justify-content:space-between;"><span class="cap">제안 전략</span><span class="tok tok-outline">전략 추론 · 원문 사실 아님</span></div><ul class="kv" style="gap:8px; font-size:13px; line-height:1.55;"><li>정성 60점 중 이행 계획 비중이 커서 단계별 발주 방안의 구체성이 평가 초점으로 보임</li><li>도메인 실적 부족은 현황 분석 방법론과 인터뷰 계획으로 보완하는 구성이 필요</li><li class="cap">반대 근거 · 발표 평가 여부가 원문에 없어 발표 준비 비용은 산정하지 않음</li></ul></div>
          </div>""")
    risks_rows = [
        ("sev-major", "중대", "공동수급 불허", "도메인 파트너와 컨소시엄을 구성할 수 없음", "단독 수행 가능성 검토 · 자문 형태 참여 가능 여부 질의", "기획부", "09.18 의견등록", "p.8"),
        ("sev-normal", "보통", "6개월 내 3개 시스템 분석", "현황 분석 기간이 짧아 인터뷰 범위가 줄 수 있음", "투입 인월 산정 뒤 일정 적정성 의견 제출", "PM 후보", "09.18", "p.4"),
        ("sev-low", "낮음", "산출물 저작권 발주기관 귀속", "방법론 재사용 제한 가능성", "기존 방법론 제외 조항 질의", "법무 검토", "본공고 전", "p.20"),
    ]
    risk_cards = "".join(
        f'<li class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; align-items:center; justify-content:space-between; gap:8px;"><div style="display:flex; align-items:center; gap:8px;"><span class="sev {s}">{sl}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>{pg(p)}</div>'
        f'<div style="display:grid; grid-template-columns: 90px minmax(0,1fr); gap:4px 12px; font-size:13px; line-height:1.5;"><span class="cap">영향</span><span>{imp}</span><span class="cap">확인·완화</span><span>{act}</span><span class="cap">담당 · 기한</span><span>{own} · {due}</span></div></li>'
        for s, sl, t, imp, act, own, due, p in risks_rows)
    risk = section("위험", '<span class="cap">기술·연계 / 보안·법률·계약 · 차단 0 · 중대 1 · 보통 1 · 낮음 1</span>', f'<ul class="kv" style="gap:10px;">{risk_cards}</ul>')
    econ = section("경제성 시나리오", '<span class="tok">산정 불가</span>', f"""
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px;"><div class="tile"><span class="cap">사업 예산 (원문)</span><span style="font-size:14px; font-weight:600;">49,844,864원</span><span class="cap2">부가세 포함 {pg("p.4")}</span></div><div class="tile"><span class="cap">투입 원가</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 투입 인력 단가</span></div><div class="tile"><span class="cap">제안 비용</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 제안 준비 인월</span></div></div>
          <span class="cap">회사 마진·원가는 입력이 없어 만들지 않습니다.</span>""")
    actions = section("질문·내부 조치", '<span class="cap">발주기관 질의 2 · 내부 확인 2</span>', "".join(
        f'<div class="li"><span style="display:flex; gap:10px; align-items:center;"><span class="check"></span><span>{t}</span></span><span class="cap2">{o}</span></div>'
        for t, o in [("공동수급 불허 조항의 자문 참여 허용 여부 (의견등록)", "발주기관 · 09.18"),
                     ("보험수리 모델 검토 범위가 필수인지 (의견등록)", "발주기관 · 09.18"),
                     ("PM 후보 ISP 경력 증빙 확인", "인사팀"),
                     ("공제·보험 도메인 유사 실적 보유 여부", "기획부")]))
    limits = section("문서 묶음·한계", '', """<ul class="kv" style="gap:6px; font-size:13px; line-height:1.55; color:#4c5650;"><li>붙임3_서식.zip은 허용 형식이 아니어서 분석에서 제외했습니다.</li><li>HWP는 변환 PDF 쪽 번호 기준이며 원본 HWP 쪽 번호와 다를 수 있습니다.</li><li>경고 · 요구사항 절 간극 1곳(p.16 표 머리) · 인용 조각 대조 1건.</li></ul>""")
    opinion = section("사전규격 심층검토 의견", '<span class="cap">보고서를 고치지 않고 의견을 별도 기록합니다</span>', """
          <div style="display:grid; grid-template-columns: minmax(0,1fr) 220px; gap:12px; align-items:start;">
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">의견 사유 <span class="cap">· 필수</span></span><div class="field" style="height:72px; align-items:flex-start; padding-top:8px;"><span>예: 선결 조건 2건 확인 뒤 추적 시작 권장</span></div></div>
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div><div class="btn btn-primary" style="height:36px;">의견 저장</div></div>
          </div>
          <span class="cap">추적 결정은 사전규격 상세에서, 최종 입찰 여부는 최종 Go/No-Go에서 사람이 결정합니다.</span>""")
    ok = f'<span style="display:inline-flex;">{icon("check", "#587a2b", 13, 2.4)}</span>'
    warn = '<span class="tok tok-yellow" style="height:18px; font-size:11px;">경고</span>'
    rail = toc("elig", {"decision": ok, "fit": ok, "elig": ok, "req": ok, "eval": ok, "risk": ok, "econ": '<span class="tok" style="height:18px; font-size:11px;">산정 불가</span>', "limits": warn}) + evidence_viewer()
    main = decision + fit + elig + req + evaln + risk + econ + actions + limits + opinion
    cards = report_head(chips, metrics) + two_col(main, rail)
    return page(3700, ["탐색과 추적", "사전규격", "R26BD00273769", "심층 검토 보고서"], '<div class="btn btn-outline">보고서 이력</div>', cards, max_width=1120)


# ---------------------------------------------------------------------------
# 3. 심층 검토 보고서 · 검증 실패
# ---------------------------------------------------------------------------

def artboard_failed():
    chips = '<span class="tok tok-accent">심층 검토 · 완료</span><span class="tok tok-red">검증 실패 · 사람 확인 필요</span><span class="tok tok-outline">참조 실행 · 품질 미측정</span>'
    metrics = [("분석 단계", "4 / 4 완료", "실행은 끝남", "#1b211d"),
               ("모델 호출", "21회", "재시도 없음", "#1b211d"),
               ("토큰 (입력 / 출력)", "171k / 28k", "provider usage 기준", "#1b211d"),
               ("검증", "실패", "중대 2 · 경고 1", "#89001a")]
    banner = f"""      <section class="card" style="display:flex; flex-direction:column; box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #e6bab8;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 22px; border-bottom:1px solid #f1d6d4; background:#fdf3f2; border-radius:14px 14px 0 0;"><div style="display:flex; align-items:center; gap:10px;">{icon("alert", "#89001a", 18, 2)}<h2 class="sec-title" style="font-size:15px; color:#89001a;">검증 실패 · 이 보고서의 권고를 판단 근거로 쓰지 마세요</h2></div><span class="cap">실패 결과는 자동으로 고치지 않습니다</span></div>
        <div class="body">
          {table(["검사", "결과", "내용", "확인"], [
              ['<span class="mono">requirement_inventory</span>', '<span class="sev sev-block">실패 · 중대</span>', "문서의 요구사항 ID 18건 중 7건을 보고서가 다루지 않음<div class=\"cap\">누락 · CSR-012 · CSR-013 · CSR-014 · CSR-015 · CSR-016 · CSR-017 · CSR-018</div>", '<a href="#" style="font-size:12px;">원문에서 확인</a>'],
              ['<span class="mono">claim_support</span>', '<span class="sev sev-block">실패 · 중대</span>', "원문에 대응하지 않는 주장 2건<div class=\"cap\">경제성 · 투입 인월 산정 / 위험 · 하자보수 기간 12개월</div>", '<a href="#" style="font-size:12px;">근거 보기</a>'],
              ['<span class="mono">segment_coverage</span>', '<span class="sev sev-normal">경고 · 보통</span>', "요구사항 절 간극 3곳 (p.16·p.18·p.21 표 머리)", '<span class="cap">차단 안 함</span>'],
          ])}
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding-top:10px; border-top:1px solid #eef0ec;"><span class="cap">재시도는 같은 고정 입력으로 새 분석 회차를 만들고 이 보고서는 이력으로 남깁니다.</span><div style="display:flex; gap:10px;"><div class="btn btn-outline">원문에서 확인</div><div class="btn btn-primary" style="gap:6px;">{icon("retry", "#ffffff", 14, 2)}새 분석 회차로 재시도</div></div></div>
        </div>
      </section>
"""
    decision = f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><h2 class="sec-title" style="font-size:15px;">의사결정 카드</h2><span class="cap">시스템 권고는 최종 Go/No-Go가 아닙니다</span></div>
        <div class="body"><div style="display:flex; align-items:center; gap:14px;"><span class="cap2" style="font-weight:600; color:#1b211d;">시스템 권고</span><span class="tok" style="height:28px; font-size:14px; padding:0 12px; color:#79837c; text-decoration:line-through;">보류</span><span class="tok tok-red">검증 실패로 사용 안 함</span></div><p style="font-size:13px; line-height:1.55; color:#79837c;">모델이 낸 권고는 이력으로만 보존합니다. 검증을 통과한 재시도 결과가 나오기 전까지 추진 판단에 쓰지 않습니다.</p></div>
      </section>
"""
    req = section("요구사항 대응 matrix", '<span class="tok tok-red">누락 7건</span>', f"""
          {table(["ID", "요구사항 (원문)", "보고서", "근거"], [
              ['<span class="mono">CSR-011</span>', "통합 데이터 모델 설계", '<span class="tok tok-accent">대응 가능</span>', pg("p.16")],
              ['<span class="mono" style="color:#89001a;">CSR-012</span>', "공제금 지급 이력 데이터 정비 방안", '<span class="tok tok-red">보고서에 없음</span>', pg("p.16")],
              ['<span class="mono" style="color:#89001a;">CSR-013</span>', "정보보호 관리체계 인증 준비 지원", '<span class="tok tok-red">보고서에 없음</span>', pg("p.17")],
              ['<span class="mono" style="color:#89001a;">CSR-014</span>', "개인정보 영향평가 대응 방안", '<span class="tok tok-red">보고서에 없음</span>', pg("p.18")],
          ])}
          <div style="display:flex; justify-content:space-between;" class="cap"><span>누락 행은 원문 요구사항 inventory에서 가져온 것이며 대응 상태를 추정하지 않습니다.</span><a href="#" style="font-size:12px;">나머지 누락 4건 펼치기</a></div>""")
    opinion = section("사전규격 심층검토 의견", '<span class="cap">검증 실패 상태에서도 의견은 남길 수 있습니다</span>', """
          <div style="display:grid; grid-template-columns: minmax(0,1fr) 220px; gap:12px; align-items:start;">
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">의견 사유 <span class="cap">· 필수</span></span><div class="field" style="height:72px; align-items:flex-start; padding-top:8px; color:#1b211d;"><span>요구사항 7건 누락으로 재시도 요청. 재시도 결과 확인 전 추적 보류.</span></div></div>
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px; color:#1b211d;"><span>김지원</span></div><div class="btn btn-disabled" style="height:36px;">의견 저장</div></div>
          </div>
          <div style="display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:10.5px; background:#fdf3f2; border:1px solid #f1d6d4;"><span class="check"></span><span style="font-size:13px; font-weight:600; color:#89001a;">검증 실패를 확인했으며 실패 표시를 그대로 둡니다</span><span class="cap" style="margin-left:auto;">확인해야 저장할 수 있습니다</span></div>""")
    rail = toc("req", {"decision": '<span class="tok tok-red" style="height:18px; font-size:11px;">사용 안 함</span>', "req": '<span class="tok tok-red" style="height:18px; font-size:11px;">누락 7</span>', "risk": '<span class="tok tok-red" style="height:18px; font-size:11px;">근거 없음</span>', "econ": '<span class="tok tok-red" style="height:18px; font-size:11px;">근거 없음</span>', "limits": '<span class="tok tok-yellow" style="height:18px; font-size:11px;">경고</span>'})
    rail += f"""<div class="card kv" style="gap:8px; padding:14px 16px;"><span class="sec-title">분석 회차</span>
      <div class="li" style="font-size:13px;"><span>회차 1 · 13:02 · 검증 실패</span><span class="tok tok-red" style="height:18px; font-size:11px;">현재</span></div>
      <span class="cap">재시도하면 회차 2가 추가되고 회차 1은 그대로 남습니다.</span></div>"""
    main = banner + decision + req + opinion
    cards = report_head(chips, metrics) + two_col(main, rail)
    return page(1520, ["탐색과 추적", "사전규격", "R26BD00273769", "심층 검토 보고서"], '<div class="btn btn-outline">보고서 이력</div>', cards, max_width=1120)


# ---------------------------------------------------------------------------
# 4. 사전규격 상세 · 심층 검토 완료 후
# ---------------------------------------------------------------------------

def artboard_after():
    summary_line = f"""<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 22px; border-bottom:1px solid #eef0ec; background:#ffffff;"><div style="display:flex; align-items:center; gap:10px;"><span class="cap2" style="font-weight:600; color:#1b211d;">심층 검토 결과</span><span class="tok tok-strong">조건부 추진 검토</span><span class="cap2">선결 조건 2 · 반대 근거 2 · 검증 통과</span></div><a href="#" style="font-size:12px;">보고서에서 근거 보기 →</a></div>"""
    steps = "".join([
        step(1, "첨부 취득", '<span class="tok tok-accent" style="align-self:flex-start;">3건 완료</span>', "완료 3 · 차단 0 · 실패 0", "done"),
        step(2, "문서 묶음", '<span class="tok tok-accent" style="align-self:flex-start;">확정 완료</span>', "제안요청서·과업지시서 · 80쪽", "done"),
        step(3, "개요 검토", '<span class="tok tok-accent" style="align-self:flex-start;">완료 · 검증 통과</span>', "범위 3~6쪽 · 목차 자동 선택", "done"),
        step(4, "심층 검토", '<span class="tok tok-accent" style="align-self:flex-start;">완료 · 검증 통과</span>', "11분 · 호출 23 · 경고 2", "done"),
    ])
    done_row = substage_row(["done"] * 4, ["부합 · 3.1k/0.6k tok", "자격 5 · 요구사항 14 · 배점 · 98k/16k tok", "위험 3 · 경제성 산정 불가 · 61k/11k tok", "권고 · 검증 통과 · 24k/3k tok"])
    tl = timeline([
        ("2026-09-16 13:13", "#75a03b", "심층 검토 완료 · 검증 통과 (경고 2)", "시스템 권고 조건부 추진 검토 · 보고서 수정본 1"),
        ("2026-09-16 13:03", "#75a03b", "심층 검토 1단계 완료 · 회사 적합성 부합", "사유 3건 · 확인할 사항 1건"),
        ("2026-09-16 13:02", "#75a03b", "심층 검토 시작 · 담당자 김지원", "개요 검토 완료 뒤 사람이 시작"),
        ("2026-09-16 12:58", "#75a03b", "개요 검토 완료 · 주장 검증 통과", "policy v7 · 범위 3~6쪽(목차)"),
    ])
    process = f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><h2 class="sec-title" style="font-size:15px;">처리 이력 · 문서 준비 · 검토 실행</h2><div style="display:flex; align-items:center; gap:10px;"><div class="btn btn-outline">문서 준비 열기</div><div class="btn btn-primary">심층 검토 보고서 열기 →</div></div></div>
        <div class="body"><div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:10px;">{steps}</div>
        <div class="kv" style="gap:10px; padding:14px 16px; border-radius:10.5px; background:#f6f7f4;"><div style="display:flex; align-items:center; justify-content:space-between;"><div style="display:flex; align-items:center; gap:10px;"><span class="sec-title">심층 검토 4단계</span><span class="tok tok-outline">참조 실행 · 품질 미측정</span></div><span class="cap2">13:02 ~ 13:13 · 입력 186k / 출력 31k tok</span></div>{done_row}</div>
        {tl}</div>
      </section>
"""
    elig_items = [("소프트웨어사업자 신고", "충족 확인", "tok-accent", "p.8"), ("중소기업자 간 경쟁", "충족 확인", "tok-accent", "p.8"),
                  ("최근 5년 ISP·ISMP 실적 1건", "충족 확인", "tok-accent", "p.8"), ("PM ISP 경력 5년 이상", "미확인", "", "p.9"),
                  ("공동수급", "불허 · 원문 사실", "tok-outline", "p.8")]
    elig = "".join(f'<li class="li"><span style="display:flex; flex-direction:column; gap:2px;"><span>{t}</span><span class="tok {c}" style="align-self:flex-start;">{s}</span></span>{"".join([f"<a href=\"#\" style=\"font-size:12px; white-space:nowrap;\">{p}</a>"])}</li>' for t, s, c, p in elig_items)
    fit = """<div class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; justify-content:space-between; align-items:center;"><span class="cap">심층 검토 1단계 · 회사 업무 부합 여부</span><span class="tok tok-accent">부합</span></div>
          <ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>정보화 전략·목표 모델 수립 ↔ ISP·ISMP 컨설팅 수행 역할</span></li><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>이행 계획·예산 산정 ↔ 공공 ISP 대표 실적 3건</span></li><li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>공제·보험 업무 도메인 실적 미확인</span></li></ul>
          <span class="cap">요구사항 대응 · 대응 가능 9 · 추가 확인 3 · 갭 1 · 해당 없음 1</span></div>"""
    risks = "".join(
        f'<li class="kv" style="gap:4px; padding:10px 12px; border-radius:10.5px; background:{bg}; border:1px solid {bd};"><div style="display:flex; align-items:center; gap:8px;"><span class="sev {s}">{sl}</span><span style="font-size:14px; font-weight:600;">{t}</span></div><span style="font-size:13px; line-height:1.5; color:#4c5650;">{d}</span></li>'
        for s, sl, t, d, bg, bd in [
            ("sev-major", "중대", "공동수급 불허", "도메인 파트너와 컨소시엄 구성 불가 · 자문 참여 가능 여부 의견등록 질의", "#fff8ec", "#f0dcb0"),
            ("sev-normal", "보통", "6개월 내 3개 시스템 분석", "투입 인월 산정 뒤 일정 적정성 확인", "#ffffff", "#eef0ec"),
            ("sev-low", "미확인", "PM 인력 · 보안 제출물", "PM ISP 경력 증빙과 보안서약서 제출 시점 확인 필요", "#f6f7f4", "#eef0ec"),
        ])
    conditions = f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="hdr"><div style="display:flex; align-items:center; gap:10px;"><h2 class="sec-title" style="font-size:15px;">참여 조건 · 회사 적합성 · 위험 및 미확인 사항</h2><span class="tok tok-accent">심층 검토 결과</span></div><span class="cap">적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음</span></div>
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:20px; padding:16px 22px 20px;">
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">참여 조건</span><span class="cap">충족 3 · 미확인 1</span></div><ul style="display:flex; flex-direction:column;">{elig}</ul><a href="#" style="font-size:12px;">참가 자격 matrix 전체 →</a></div>
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">회사 적합성</span><span class="cap">모델 참조 · 사람이 확정</span></div>{fit}</div>
          <div class="kv" style="gap:8px;"><div style="display:flex; justify-content:space-between;"><span class="sec-title">위험 및 미확인 사항</span><span class="cap">중대 1 · 보통 1 · 미확인 1</span></div><ul class="kv" style="gap:8px;">{risks}</ul><a href="#" style="font-size:12px;">위험 절 전체 →</a></div>
        </div>
      </section>
"""
    status_chip = '<span class="tok tok-accent">심층 검토 완료</span>'
    cards = detail_header(status_chip) + tracking_card(summary_line) + tasks_card() + evidence_collapsed() + process + conditions
    return page(2320, ["탐색과 추적", "사전규격", "R26BD00273769"], nav_right(), cards)


BOARDS = {
    "Main.dc.html": ("사전규격 상세 · 심층 검토 진행 중", artboard_running, 2140),
    "DetailAfter.dc.html": ("사전규격 상세 · 심층 검토 완료 후", artboard_after, 2200),
    "ReportComplete.dc.html": ("심층 검토 보고서 · 완료 (한국부동산원 AI 에이전트 플랫폼)", artboard_report_reb, 3900),
    "ReportFailed.dc.html": ("심층 검토 보고서 · 검증 실패", artboard_failed, 1800),
}

for name, (_title, fn, _h) in BOARDS.items():
    (OUT / name).write_text(fn(), encoding="utf-8")

canvas = {
    "artboards": [
        {"file": "Main.dc.html", "title": BOARDS["Main.dc.html"][0], "x": 0, "y": 0, "w": 1422, "h": 2200},
        {"file": "DetailAfter.dc.html", "title": BOARDS["DetailAfter.dc.html"][0], "x": 1522, "y": 0, "w": 1422, "h": 2320},
        {"file": "ReportComplete.dc.html", "title": BOARDS["ReportComplete.dc.html"][0], "x": 3044, "y": 0, "w": 1422, "h": 9950},
        {"file": "ReportFailed.dc.html", "title": BOARDS["ReportFailed.dc.html"][0], "x": 4566, "y": 0, "w": 1422, "h": 1520},
    ],
    "annotations": [
        {"id": "flow-note", "x": 0, "y": -200, "w": 900, "text": "심층 검토 화면 흐름 시안 (2026-09-16, 재설계 C 기준). 왼쪽부터 ① 사전규격 상세 · 진행 중 → ② 상세 · 완료 후 → ③ 보고서 · 완료 → ④ 보고서 · 검증 실패.\n프레임 1422px = 1280×800 창(zoom 0.9 논리 px). 사업명·수치·요구사항 ID·일시는 규칙을 설명하는 예시 데이터이며 운영 사실이 아니다."},
        {"id": "fit-note", "x": 1522, "y": -200, "w": 700, "text": "회사 적합성은 심층 검토의 1단계로 그렸다(ADR-0057 결정 4, 현재 보류 중 — 검토용). 진행 단계는 회사 적합성 → 요구사항·자격·평가 → 수행·위험·경제성 → 종합·검증 4칸이며, 뒤 3칸은 현재 분석 정책의 3단계와 같다."},
        {"id": "report-note", "x": 3044, "y": -230, "w": 900, "text": "보고서 · 완료 = 실제 문서 분석값 (2026-09-17): 한국부동산원 「AI 에이전트 플랫폼 구축」 제안요청서 PDF 131쪽을 Claude가 직접 판독하고 회사 프로필(2026-08)과 대조했다. 근거는 PDF 쪽 번호(인쇄 쪽 = PDF 쪽 − 2). BidOps 모델·결정적 검사는 실행하지 않았고, 공고가 BidOps에 수집되지 않아 공고 번호·의견등록 마감은 미확인이다. 요구사항 77건 분류와 경영상태 점수(BB0 → 3.80점)는 문서·프로필에서 직접 계산했다. 회사 내부 정보(신용등급·자격)가 들어 있으니 공유 시 주의."},
        {"id": "failed-note", "x": 4566, "y": -200, "w": 700, "text": "검증 실패: 실패 검사와 누락 ID를 맨 위에 두고, 시스템 권고는 이력으로만 보이며 사용하지 않는다. 의견 저장은 '검증 실패를 확인했으며 실패 표시를 그대로 둡니다' 체크 전까지 비활성(현재 구현 규칙). 재시도는 새 분석 회차를 만든다."},
    ],
    "launch": {"view": "canvas"},
}
(OUT / "canvas.json").write_text(json.dumps(canvas, ensure_ascii=False, indent=2), encoding="utf-8")
print("built", ", ".join(BOARDS))
