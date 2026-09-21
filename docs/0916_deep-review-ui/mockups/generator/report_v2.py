"""심층 검토 보고서 · 완료 — 담당자 질문 순서 12절 구성(2026-09-17 개정). 예시 데이터."""
from common import page, icon


def pg(label):
    return f'<a href="#" style="font-size:12px; white-space:nowrap;">{label}</a>'


def pf(label):
    return f'<a href="#" style="font-size:12px; white-space:nowrap; color:#4c5650; text-decoration:underline; text-decoration-color:#c9cfc3;">프로필 · {label}</a>'


ST = {
    "fact": '<span class="tok tok-accent" style="height:18px; font-size:11px; align-self:flex-start;">원문 확정</span>',
    "bid": '<span class="tok tok-outline" style="height:18px; font-size:11px; align-self:flex-start;">본공고에서 확정</span>',
    "unk": '<span class="tok" style="height:18px; font-size:11px; align-self:flex-start;">미확인</span>',
    "inf": '<span class="tok tok-outline" style="height:18px; font-size:11px; align-self:flex-start;">추론 · 원문 사실 아님</span>',
}


def num(n):
    return f'<span style="display:inline-flex; align-items:center; justify-content:center; min-width:22px; height:22px; padding:0 6px; border-radius:6px; background:#26391a; color:#e4ead9; font-size:12px; font-weight:600;">{n}</span>'


def section(n, title, question, right, body, extra=""):
    return f"""      <section class="card" style="display:flex; flex-direction:column;{extra}">
        <div class="hdr"><div style="display:flex; align-items:center; gap:10px;">{num(n)}<h2 class="sec-title" style="font-size:15px;">{title}</h2><span class="cap">{question}</span></div><div style="display:flex; align-items:center; gap:8px;">{right}</div></div>
        <div class="body">{body}</div>
      </section>
"""


def table(head, rows):
    th = "".join(f'<th class="th">{h}</th>' for h in head)
    body = "".join("<tr>" + "".join(f'<td class="td">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="width:100%; border-collapse:collapse;"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def kv_grid(rows):
    cells = "".join(
        f'<div style="display:grid; grid-template-columns: 120px minmax(0,1fr) auto; gap:12px; align-items:start; padding:10px 0; border-bottom:1px solid #eef0ec;"><span class="cap2" style="font-weight:600; color:#1b211d;">{k}</span><div class="kv" style="gap:4px;"><span style="font-size:14px; line-height:1.5;{" color:#79837c;" if s == "unk" else ""}">{v}</span>{ST[s]}</div>{link}</div>'
        for k, v, s, link in rows)
    return f'<div style="display:flex; flex-direction:column;">{cells}</div>'


def small(t):
    return f'<span class="cap">{t}</span>'


def head():
    facts = [
        ("사업 예산", "49,844,864원", "부가세 포함 · 제안요청서 p.4"),
        ("사업 기간", "계약일부터 6개월", "기산점 계약 체결일 · p.4"),
        ("계약 방법", "협상에 의한 계약", "기술 80 · 가격 20 · p.11"),
        ("의견등록 마감", '09.18 23:59 <span class="dday">D-2</span>', "질의는 이 날까지"),
        ("본공고", '<span style="color:#79837c;">미확인</span>', "사전규격 단계"),
        ("구분", "일반용역", "SW사업대상 Y"),
    ]
    cells = "".join(
        f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px;{" border-right:1px solid #eef0ec;" if i < 5 else ""}"><span class="cap">{k}</span><span style="font-size:17px; font-weight:600; line-height:1.3;">{v}</span><span class="cap">{c}</span></div>'
        for i, (k, v, c) in enumerate(facts))
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="kv" style="gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-strong">심층 검토 보고서</span><span class="tok tok-accent">검증 통과 · 경고 2</span><span class="tok tok-outline">참조 실행 · 품질 미측정</span></div><div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-outline">추적 결정 · 미선택</span><a href="#" class="cap2">사전규격 상세로 돌아가기</a></div></div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">예술인 공제사업 통합관리시스템 중장기 ISMP 수립</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2"><span style="font-size:14px; color:#1b211d;">한국예술인복지재단</span><span style="color:#c9cfc3;">·</span><span>사전규격번호 <b style="font-weight:600; color:#1b211d; font-size:14px;">R26BD00273769</b></span><span style="color:#c9cfc3;">·</span><a href="#" style="font-size:12px;">나라장터 원문 ↗</a><a href="#" style="font-size:12px;">제안요청서 PDF ↗</a><a href="#" style="font-size:12px;">과업지시서 PDF ↗</a></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); border-top:1px solid #eef0ec;">{cells}</div>
        <div style="display:flex; justify-content:space-between; gap:12px; padding:10px 24px; border-top:1px solid #eef0ec; background:#fbfcf9;" class="cap"><span>2026-09-16 13:13 분석 · 문서 묶음 수정본 1 · 회사 프로필 v3 · 분석 정책 lean-v1</span><span>상태 표시 · 원문 확정 / 본공고에서 확정 / 미확인 / 추론</span></div>
      </section>
"""


def decision():
    blocker = f"""<div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:12px;">
            <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:10.5px; background:#f1f6e8;">{icon("check", "#3f5a1c", 16, 2.4)}<div class="kv"><span style="font-size:14px; font-weight:600; color:#3f5a1c;">참여 불가 요인 · 확정된 것 없음</span><span class="cap2">자격 불충족 확인 0 · 차단 위험 0</span></div></div>
            <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:10.5px; background:#fff8ec; border:1px solid #f0dcb0;">{icon("alert", "#6e3500", 16, 2)}<div class="kv"><span style="font-size:14px; font-weight:600; color:#6e3500;">추적 결정 전 확인할 일 2건</span><span class="cap2">PM 경력 증빙 · 공동수급 자문 참여 질의 → 9절</span></div></div>
          </div>"""
    li = lambda ic, col, t, link: f'<li style="display:flex; gap:6px; align-items:flex-start;">{icon(ic, col, 14, 2.2)}<span>{t} {link}</span></li>'
    body = f"""{blocker}
          <div style="display:flex; align-items:center; gap:14px;"><span class="cap2" style="font-weight:600; color:#1b211d;">시스템 권고</span><span class="tok tok-strong" style="height:28px; font-size:14px; padding:0 12px;">조건부 추진 검토</span><span class="cap2">검증을 통과한 항목만 근거로 삼음 · 최종 Go/No-Go가 아님</span></div>
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:16px;">
            <div class="kv" style="gap:6px;"><span class="cap">추진 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("check", "#587a2b", "정보화 전략·목표 모델 수립이 회사 컨설팅 수행 역할과 일치", pg("제안요청서 p.5"))}{li("check", "#587a2b", "필수 자격 3개 충족 확인, 불충족 확인 없음", pg("3절"))}{li("check", "#587a2b", "요구사항 14건 중 대응 가능 9", pg("5절"))}</ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">선결 조건</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("alert", "#6e3500", "PM ISP 경력 5년 인력 증빙", pg("제안요청서 p.9"))}{li("alert", "#6e3500", "공동수급 불허 하에 도메인 보완 방안", pg("제안요청서 p.8"))}</ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">반대 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("x", "#89001a", "공제·보험 도메인 실적이 회사 자료에 없음", pf("대표 실적 2.4"))}{li("x", "#89001a", "보험수리 모델 검토 요구가 갭", pg("과업지시서 p.7"))}</ul></div>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; padding-top:10px; border-top:1px solid #eef0ec;" class="cap"><span>다음 행동 · 9절 확인 → 사전규격 상세에서 추적 결정 → 본공고 나오면 7개 범주 변경 비교 → 최종 Go/No-Go</span><div class="btn btn-outline">사전규격 상세에서 추적 결정 →</div></div>"""
    return section(1, "의사결정 요약", "한마디로 어떤가", '', body,
                   " box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5;")


def basics():
    return section(2, "공고 기본정보", "무엇을 하는 사업인가", '<span class="cap">원문 확정 6 · 본공고 확정 1 · 미확인 2</span>', kv_grid([
        ("목적·배경", "3개로 나뉜 공제사업 시스템(창작준비금·산재보험·긴급복지)을 통합하기 위한 중장기 정보화 전략 수립", "fact", pg("제안요청서 p.3")),
        ("범위 · 포함", "현황 분석, 목표 모델(업무·데이터·연계), 3개년 이행 계획과 소요 예산", "fact", pg("제안요청서 p.5")),
        ("범위 · 제외", "시스템 구축·개발, 정보보호 인증 취득 자체", "fact", pg("과업지시서 p.2")),
        ("산출물·검수", "착수·중간·최종 보고서와 ISMP 결과서 · 최종 보고 후 발주기관 검수", "fact", pg("과업지시서 p.12")),
        ("기간·기산점", "계약 체결일부터 6개월", "fact", pg("제안요청서 p.4")),
        ("수행 장소·상주", "원문에서 확인되지 않음", "unk", small("9절 질의")),
        ("계약 유형", "총액·단가 여부가 사전규격에 없음", "bid", small("본공고")),
        ("예산 산정 기준", "원문에서 확인되지 않음", "unk", small("")),
        ("사업 예산", "49,844,864원 (부가세 포함)", "fact", pg("제안요청서 p.4")),
    ]))


def eligibility():
    j = {"ok": '<span class="tok tok-accent">충족 확인</span>', "unk": '<span class="tok">미확인</span>', "limit": '<span class="tok tok-outline">참여 구조 제약</span>', "na": '<span class="tok tok-outline">제한 없음</span>'}
    rows = [
        ["소프트웨어사업자 신고", "SW진흥법 제58조 신고<br>" + pg("제안요청서 p.8 §2.3가"), "신고확인서 보유<br>" + pf("자격·조달 5.2"), j["ok"]],
        ["기업 규모", "중소기업자 간 경쟁<br>" + pg("제안요청서 p.8 §2.3나"), "중소기업 확인서 (2027.03 만료)<br>" + pf("자격·조달 5.2"), j["ok"]],
        ["유사 실적", "최근 5년 ISP·ISMP 1건 이상<br>" + pg("제안요청서 p.8 §2.3다"), "공공 ISP 3건 (2022~2025)<br>" + pf("대표 실적 2.4"), j["ok"]],
        ["지역 제한", "제한 조항 없음<br>" + pg("제안요청서 p.8"), "—", j["na"]],
        ["공동수급", "허용하지 않음<br>" + pg("제안요청서 p.8 §2.3라"), "단독 참여만 가능", j["limit"]],
        ["하도급·분담이행", '<span style="color:#79837c;">원문에서 확인되지 않음</span>', "—", j["unk"] + '<div class="cap">9절 질의</div>'],
        ["투입 인력", "PM ISP 경력 5년 이상<br>" + pg("제안요청서 p.9"), '<span style="color:#79837c;">회사 자료에 PM 경력 없음</span>', j["unk"] + '<div class="cap">9절 내부 확인</div>'],
        ["보안 증빙", "보안서약서·보안교육 이수<br>" + pg("과업지시서 p.15"), '<span style="color:#79837c;">제출 시점 확인 필요</span>', j["unk"]],
    ]
    return section(3, "참여 가능성", "우리가 입찰할 수 있나", '<span class="cap">충족 확인 3 · 불충족 확인 0 · 미확인 3 · 제약 1</span>',
                   table(["자격 항목", "공고 요구 · 근거", "회사 사실 · 근거", "판정"], rows) +
                   '<span class="cap">회사 사실은 승인된 회사 프로필 v3의 확인된 항목만 씁니다. 자료에 없으면 충족이나 불충족으로 쓰지 않습니다.</span>')


def evaluation():
    score = table(["평가 항목", "배점", "근거"], [
        ["기술 · 정량 (실적·경영상태·인력)", "20", pg("제안요청서 p.11")],
        ["기술 · 정성 (이해도·방법론·이행 계획)", "60", pg("제안요청서 p.11")],
        ["가격", "20", pg("제안요청서 p.11")],
        ['<b style="font-weight:600;">합계</b>', '<b style="font-weight:600;">100</b> <span class="tok tok-accent" style="height:18px; font-size:11px;">코드 재계산 일치</span>', ""],
    ])
    rules = kv_grid([
        ("협상적격", "기술점수 85% 이상", "fact", pg("제안요청서 p.11")),
        ("발표·시연", "원문에서 확인되지 않음", "unk", small("9절 질의")),
        ("감점·실격", "허위 서류 제출 시 실격", "fact", pg("제안요청서 p.12")),
    ])
    submit = kv_grid([
        ("제출 서류", "제안서·가격제안서·정량평가 증빙 (사전규격 기준)", "bid", pg("제안요청서 p.13")),
        ("제출 기한", "본공고에서 정해짐", "bid", small("")),
        ("제출 방식", "나라장터 전자 제출", "fact", pg("제안요청서 p.13")),
        ("제안 설명회", "원문에서 확인되지 않음", "unk", small("")),
    ])
    body = f'<div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:20px;"><div class="kv" style="gap:8px;"><span class="cap">배점</span>{score}{rules}</div><div class="kv" style="gap:8px;"><span class="cap">제출</span>{submit}</div></div>'
    return section(4, "평가와 제출", "어떻게 뽑고 무엇을 내나", '', body)


def fit():
    reqrows = [
        ['<span class="mono" style="white-space:nowrap;">CSR-001</span>', "현행 업무·시스템 현황 분석", '<span class="tok tok-accent">대응 가능</span>', "공공 ISP 3건의 현황 분석 산출물 " + pf("대표 실적 2.4"), "—", pg("과업지시서 p.3")],
        ['<span class="mono" style="white-space:nowrap;">CSR-004</span>', "데이터 표준화·이관 방안", '<span class="tok tok-accent">대응 가능</span>', "데이터 표준화 수행 실적 " + pf("보유 기술 2.1"), "—", pg("과업지시서 p.5")],
        ['<span class="mono" style="white-space:nowrap;">CSR-007</span>', "외부 기관(국세청·근로복지공단) 연계 방안", '<span class="tok tok-yellow">추가 확인</span>', "연계 설계 경험은 있으나 해당 기관 실적 미확인", "기관 연계 사례 확인", pg("과업지시서 p.6")],
        ['<span class="mono" style="white-space:nowrap;">CSR-010</span>', "공제사업 보험수리 모델 검토", '<span class="tok tok-red">갭</span>', "보험수리 전문 인력이 회사 자료에 없음", "외부 자문 인력 · 공동수급 불허라 하도급 가능 여부 질의", pg("과업지시서 p.7")],
        ['<span class="mono" style="white-space:nowrap;">CSR-013</span>', "정보보호 인증 준비 지원", '<span class="tok tok-outline">해당 없음</span>', "범위 제외 조항", "—", pg("과업지시서 p.2")],
    ]
    body = f"""<div class="kv" style="gap:8px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;">
            <div style="display:flex; align-items:center; gap:10px;"><span class="sec-title">회사 적합성</span><span class="tok tok-accent">부합</span><span class="cap2">공고 과업과 회사 수행 역할·실적의 대조 · 모델 참조, 사람이 확정</span></div>
            <ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>목표 모델·정보화 전략 수립 ↔ ISP·ISMP 컨설팅 수행 역할 {pg("제안요청서 p.5")} {pf("수행 역할 2.2")}</span></li><li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>공제·보험 업무 도메인 ↔ 회사 자료 없음 {pf("대표 실적 2.4")}</span></li></ul>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;"><div style="display:flex; gap:8px;"><span class="tok tok-accent">대응 가능 9</span><span class="tok tok-yellow">추가 확인 3</span><span class="tok tok-red">갭 1</span><span class="tok tok-outline">해당 없음 1</span></div><span class="tok tok-accent">문서 요구사항 ID 14건 모두 다룸 · 누락 0</span></div>
          {table(["ID", "요구사항", "대응", "회사 근거 · 차이", "갭 대응 방향", "근거"], reqrows)}
          <div style="display:flex; justify-content:flex-end;"><a href="#" style="font-size:12px;">나머지 9건 펼치기</a></div>"""
    return section(5, "과업 적합성", "우리가 잘할 수 있나", '', body)


def delivery():
    need = kv_grid([
        ("투입 인력", "PM 1명(ISP 경력 5년 이상) · 그 외 인원 수 규정 없음", "fact", pg("제안요청서 p.9")),
        ("마일스톤", "착수 2주 · 중간보고 3개월 · 최종보고 6개월", "fact", pg("과업지시서 p.12")),
        ("선행 의존성", "발주기관이 현행 3개 시스템 자료·담당자 인터뷰 제공", "fact", pg("과업지시서 p.4")),
    ])
    econ = f"""<div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px;"><div class="tile"><span class="cap">사업 예산</span><span style="font-size:14px; font-weight:600;">49,844,864원</span>{ST["fact"]}</div><div class="tile"><span class="cap">투입 원가 (인월 × 단가)</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 인력 구성안, 등급별 단가</span></div><div class="tile"><span class="cap">제안 비용</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 제안 준비 인월</span></div></div>
          <span class="cap">입력이 없는 인월·원가·마진은 만들지 않습니다. 필요 자료가 들어오면 이 칸만 계산합니다.</span>"""
    body = f'<div class="kv" style="gap:8px;"><span class="cap">원문의 수행 조건</span>{need}</div><div class="kv" style="gap:8px;"><span class="cap">사업성</span>{econ}</div>'
    return section(6, "수행 계획과 사업성", "할 만한가", '', body)


def risks():
    contract = table(["계약 조건", "내용", "상태", "근거"], [
        ["지체상금", "계약금액 × 0.125% × 지체일수", ST["fact"], pg("과업지시서 p.18")],
        ["계약보증금", "계약금액의 10%", ST["bid"], small("본공고")],
        ["하자보수", "용역 특성상 규정 없음", ST["fact"], pg("과업지시서 p.18")],
        ["대금 지급", "최종 검수 후 일시 지급", ST["fact"], pg("과업지시서 p.19")],
        ["지식재산권", "산출물 저작권 발주기관 귀속", ST["fact"], pg("과업지시서 p.20")],
    ])
    rows = [
        ("sev-major", "중대", "참여 구조", "공동수급 불허", "도메인·보험수리 파트너와 컨소시엄 불가", "자문·하도급 참여 허용 여부 의견등록 질의", "기획부 · 09.18", "허용 안 되면 CSR-010 갭 유지", "제안요청서 p.8"),
        ("sev-normal", "보통", "수행", "6개월 내 3개 시스템 분석", "현황 분석 인터뷰 범위 축소 가능", "인력 구성안으로 일정 적정성 확인", "PM 후보 · 09.18", "인력 확보 시 낮음", "과업지시서 p.12"),
        ("sev-normal", "보통", "보안·개인정보", "공제 가입자 개인정보 열람", "보안서약·반출 통제 준수 부담", "보안 절차·반출 제한 조항 검토", "보안 담당 · 제출 전", "통제 절차 수립 시 낮음", "과업지시서 p.15"),
        ("sev-low", "낮음", "법률·계약", "산출물 저작권 발주기관 귀속", "자사 방법론 재사용 제한 가능성", "기존 방법론 제외 조항 질의", "법무 검토 · 본공고 전", "질의 결과에 따름", "과업지시서 p.20"),
    ]
    cards = "".join(
        f'<li class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; align-items:center; justify-content:space-between; gap:8px;"><div style="display:flex; align-items:center; gap:8px;"><span class="sev {s}">{sl}</span><span class="tok tok-outline" style="height:18px; font-size:11px;">{cat}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>{pg(p)}</div>'
        f'<div style="display:grid; grid-template-columns: 90px minmax(0,1fr) 90px minmax(0,1fr); gap:4px 12px; font-size:13px; line-height:1.5;"><span class="cap">영향</span><span>{imp}</span><span class="cap">확인·완화</span><span>{act}</span><span class="cap">담당 · 기한</span><span>{own}</span><span class="cap">잔여 위험</span><span>{res}</span></div></li>'
        for s, sl, cat, t, imp, act, own, res, p in rows)
    body = f'<ul class="kv" style="gap:10px;">{cards}</ul><div class="kv" style="gap:8px;"><span class="cap">계약 조건</span>{contract}</div>'
    return section(7, "위험", "무엇이 발목을 잡나", '<span class="cap">차단 0 · 중대 1 · 보통 2 · 낮음 1</span>', body)


def strategy():
    body = f"""<ul class="kv" style="gap:10px; font-size:13px; line-height:1.55;">
            <li style="display:grid; grid-template-columns: 110px minmax(0,1fr); gap:12px;"><span class="cap2" style="font-weight:600; color:#1b211d;">발주 배경</span><span>3개 시스템 분리 운영으로 중복 입력·데이터 불일치가 있다고 원문이 밝힘 {pg("제안요청서 p.3")}</span></li>
            <li style="display:grid; grid-template-columns: 110px minmax(0,1fr); gap:12px;"><span class="cap2" style="font-weight:600; color:#1b211d;">평가 초점</span><span>정성 60점 중 이행 계획 비중이 커서 단계별 발주 방안의 구체성이 핵심으로 보임 {ST["inf"]}</span></li>
            <li style="display:grid; grid-template-columns: 110px minmax(0,1fr); gap:12px;"><span class="cap2" style="font-weight:600; color:#1b211d;">차별점·레퍼런스</span><span>공공 ISP 3건의 통합 데이터 모델 경험을 앞세움 {pf("대표 실적 2.4")} {ST["inf"]}</span></li>
            <li style="display:grid; grid-template-columns: 110px minmax(0,1fr); gap:12px;"><span class="cap2" style="font-weight:600; color:#1b211d;">반대 근거</span><span>도메인 실적 부족은 방법론으로 온전히 메우기 어려움 · 발표 평가 여부 미확인</span></li>
          </ul>"""
    return section(8, "제안 전략", "어떻게 이기나", ST["inf"], body)


def todo():
    blk = '<span class="tok tok-orange" style="height:18px; font-size:11px;">추적 결정 전</span>'
    nb = '<span class="cap">—</span>'
    rows = [
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "PM 후보 ISP 경력 5년 증빙", "내부 확인", "인사팀", "09.18", blk, pg("3절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "공동수급 불허 시 자문·하도급 참여 허용 여부", "의견등록 질의", "기획부", "09.18", blk, pg("7절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "하도급·분담이행 허용 범위", "의견등록 질의", "기획부", "09.18", nb, pg("3절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "발표·시연 평가 여부", "의견등록 질의", "기획부", "09.18", nb, pg("4절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "수행 장소·상주 여부", "의견등록 질의", "기획부", "09.18", nb, pg("2절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "공제·보험 도메인 유사 실적 보유 여부", "내부 확인", "기획부", "09.18", nb, pg("5절")],
        ['<span class="check" style="display:inline-block; vertical-align:middle;"></span>', "인력 구성안과 등급별 단가", "내부 확인", "원가 담당", "추적 시작 후", nb, pg("6절")],
    ]
    return section(9, "확인할 일", "무엇을 더 알아야 하나", '<span class="cap">7건 · 의견등록 질의 4 (마감 09.18 D-2) · 내부 확인 3</span>',
                   table(["", "항목", "구분", "담당", "기한", "막는 결정", "출처"], rows) +
                   '<span class="cap">보고서 어느 절에서든 미확인이 나오면 이 목록에 모입니다. 체크는 담당자 기록이며 보고서 내용을 바꾸지 않습니다.</span>')


def trust():
    docs = table(["입력 문서", "쪽", "분석 포함", "근거 표기"], [
        ["제안요청서.hwp (변환 PDF)", '<span style="white-space:nowrap;">62쪽</span>', '<span class="tok tok-accent">포함</span>', "제안요청서 p.n"],
        ["과업지시서.hwp (변환 PDF)", '<span style="white-space:nowrap;">18쪽</span>', '<span class="tok tok-accent">포함</span>', "과업지시서 p.n"],
        ["붙임3_서식.zip", "—", '<span class="tok">제외 · 허용 형식 아님</span>', "—"],
        ["회사 프로필 v3", "—", '<span class="tok tok-accent">포함</span>', "프로필 · 절 번호"],
    ])
    checks = table(["검사", "결과", "내용"], [
        ['<span class="mono" style="white-space:nowrap;">requirement_inventory</span>', '<span class="tok tok-accent">통과</span>', "문서 ID 14건 모두 다룸"],
        ['<span class="mono">claim_support</span>', '<span class="tok tok-accent">통과</span>', "주장 62건 모두 원문 또는 프로필에 대응"],
        ['<span class="mono">segment_coverage</span>', '<span class="tok tok-yellow">경고</span>', "과업지시서 p.16 표 머리 간극 1곳 · 차단 안 함"],
        ['<span class="mono">evidence_fragment</span>', '<span class="tok tok-yellow">경고</span>', "2단 편집 쪽 인용 1건을 조각으로 대조"],
    ])
    run = '<div style="display:flex; gap:16px; flex-wrap:wrap;" class="cap2"><span>qwen3.8-27B</span><span>분석 정책 lean-v1</span><span>4단계 · 13:02~13:13 (11분)</span><span>모델 호출 23 (재시도 1)</span><span>토큰 입력 186k / 출력 31k</span></div>'
    body = f'<div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:20px;"><div class="kv" style="gap:8px;"><span class="cap">입력 범위</span>{docs}</div><div class="kv" style="gap:8px;"><span class="cap">검사별 결과</span>{checks}</div></div><div class="kv" style="gap:6px;"><span class="cap">실행 정보</span>{run}</div><span class="cap">쪽 번호는 HWP를 변환한 PDF 기준이며 원본 HWP의 쪽 번호와 다를 수 있습니다. 참조 실행 결과는 품질 측정·운영 승인 근거가 아닙니다.</span>'
    return section(10, "신뢰성과 한계", "결과를 믿을 수 있나", '<span class="tok tok-accent">검증 통과 · 경고 2</span>', body)


def human():
    radios = "".join(
        f'<div style="display:flex; align-items:center; gap:8px; height:36px; padding:0 12px; border-radius:8.75px; border:1px solid {"#75a03b" if on else "#c9cfc3"}; background:{"#f1f6e8" if on else "#ffffff"}; font-size:13px; font-weight:{600 if on else 500};"><span style="width:14px; height:14px; border-radius:50%; box-shadow:inset 0 0 0 {"4px #587a2b" if on else "1.5px #9aa39c"}; background:#ffffff;"></span>{t}</div>'
        for t, on in [("추진", False), ("조건부 추진", False), ("보류", False), ("검토 종료", False)])
    body = f"""<div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">사람 의견 <span class="cap">· 필수 · 시스템 권고와 별개로 기록 · 기본 선택 없음</span></span><div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:8px;">{radios}</div></div>
          <div style="display:grid; grid-template-columns: minmax(0,1fr) 220px; gap:12px; align-items:end;">
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">사유 <span class="cap">· 필수</span></span><div class="field" style="height:64px; align-items:flex-start; padding-top:8px;"><span>예: 9절 확인 2건이 해소되면 추적 시작</span></div></div>
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div><div class="btn btn-primary" style="height:36px;">의견 저장</div></div>
          </div>
          <div class="kv" style="gap:4px;"><span class="cap">기록</span><div class="li" style="font-size:13px;"><span>수정본 1 · 기계 생성 · 2026-09-16 13:13</span><span class="cap2">사람 의견 없음</span></div></div>
          <span class="cap">의견은 보고서를 고치지 않습니다. 추적 결정은 사전규격 상세에서, 입찰 참여는 최종 Go/No-Go에서 사람이 결정합니다.</span>"""
    return section(11, "사람 기록", "누가 어떻게 판단했나", '', body)


def rail():
    items = [(1, "의사결정 요약", ""), (2, "공고 기본정보", "미확인 2"), (3, "참여 가능성", "미확인 3"), (4, "평가와 제출", "미확인 2"),
             (5, "과업 적합성", "갭 1"), (6, "수행 계획과 사업성", "산정 불가"), (7, "위험", "중대 1"), (8, "제안 전략", "추론"),
             (9, "확인할 일", "7건"), (10, "신뢰성과 한계", "경고 2"), (11, "사람 기록", "")]
    rows = "".join(
        f'<a href="#" style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; border-radius:5.25px; font-size:13px; {"background:#f1f6e8; color:#3f5a1c; font-weight:600;" if n == 3 else "color:#4c5650;"}"><span style="display:flex; gap:8px;"><span class="mono" style="min-width:16px;">{n}</span>{t}</span>{f"<span class=&quot;cap&quot;>{m}</span>".replace("&quot;", chr(34)) if m else ""}</a>'
        for n, t, m in items)
    toc = f'<div class="card kv" style="gap:2px; padding:12px 10px;"><span class="cap" style="padding:0 10px 6px;">보고서 절</span>{rows}</div>'
    viewer = """<div class="card kv" style="gap:10px; padding:14px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center;"><span class="sec-title">원문 근거</span><a href="#" style="font-size:12px;">PDF 열기 ↗</a></div>
      <div class="kv" style="gap:4px;"><span class="cap">선택 · 3절 유사 실적</span><span style="font-size:13px; font-weight:600;">제안요청서 p.8 · §2.3 입찰참가자격 다</span></div>
      <div style="padding:12px; border-radius:10.5px; background:#fbfcf9; border:1px solid #eef0ec; font-size:13px; line-height:1.7; color:#4c5650;">
        <p>나. 「중소기업제품 구매촉진 및 판로지원에 관한 법률」에 따른 중소기업자</p>
        <p><span class="hl">다. 최근 5년 이내 공공기관 정보화전략계획(ISP·ISMP) 수립 실적 1건 이상을 보유한 자</span></p>
        <p>라. 공동수급은 허용하지 아니함</p>
      </div>
      <div class="kv" style="gap:4px; padding-top:8px; border-top:1px solid #eef0ec;"><span class="cap">대조한 회사 사실</span><span style="font-size:13px;">프로필 v3 · 대표 실적 2.4 · 공공 ISP 3건 (2022~2025)</span></div>
    </div>"""
    return toc + viewer


def artboard_report_v2():
    main = decision() + basics() + eligibility() + evaluation() + fit() + delivery() + risks() + strategy() + todo() + trust() + human()
    body = head() + f'<div style="display:grid; grid-template-columns: minmax(0,1fr) 280px; gap:16px; align-items:start;"><div class="kv" style="gap:16px;">{main}</div><div class="kv" style="gap:16px;">{rail()}</div></div>'
    return page(6200, ["탐색과 추적", "사전규격", "R26BD00273769", "심층 검토 보고서"], '<div class="btn btn-outline">보고서 이력</div>', body, max_width=1136)
