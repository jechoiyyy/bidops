"""심층 검토 보고서 · 완료 — 한국부동산원 「AI 에이전트 플랫폼 구축」 제안요청서(PDF 131쪽) 실제 분석값.

근거 쪽은 PDF 쪽 기준(본문 인쇄 쪽 = PDF 쪽 − 2). 회사 사실은 docs/reference/company-profile.md(2026-08).
분석은 Claude가 문서를 직접 읽어 수행했고 BidOps 모델·결정적 검사는 돌리지 않았다.
"""
from common import page, icon
from report_v2 import pg, pf, ST, num, section, table, kv_grid, small

R = lambda p: pg(f"제안요청서 p.{p}")


def chip(text, cls=""):
    return f'<span class="tok {cls}">{text}</span>'


def head():
    facts = [
        ("사업 예산", "661,870,000원", "부가세 포함 · 만원 이하 절사 · p.3"),
        ("사업 기간", "계약일부터 6개월", "시범운영 최소 2개월 포함 · p.3·p.41"),
        ("계약 방법", "협상에 의한 계약", "기술 90 · 가격 10 · p.73"),
        ("입찰 마감", '<span style="color:#79837c;">미확인</span>', "조달청 입찰공고문 참조 · p.72"),
        ("공고 번호", '<span style="color:#79837c;">미확인</span>', "BidOps 수집 기록 없음"),
        ("참여 대상", "중소 SW사업자", "공동수급 허용 · 하도급 불허"),
    ]
    cells = "".join(
        f'<div style="display:flex; flex-direction:column; gap:2px; padding:12px 16px;{" border-right:1px solid #eef0ec;" if i < 5 else ""}"><span class="cap">{k}</span><span style="font-size:17px; font-weight:600; line-height:1.3;">{v}</span><span class="cap">{c}</span></div>'
        for i, (k, v, c) in enumerate(facts))
    return f"""      <section class="card" style="display:flex; flex-direction:column;">
        <div class="kv" style="gap:10px; padding:20px 24px 16px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><div style="display:flex; align-items:center; gap:6px;"><span class="tok tok-strong">심층 검토 보고서</span><span class="tok tok-outline">문서 직접 분석 · 자동 검사 미실행</span><span class="tok tok-outline">참조 · 품질 미측정</span></div><div style="display:flex; align-items:center; gap:10px;"><span class="tok tok-outline">추적 결정 · 사업기회 미연결</span></div></div>
          <h1 style="font-size:22px; font-weight:600; line-height:1.35;">「AI 에이전트 플랫폼 구축」 용역</h1>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;" class="cap2"><span style="font-size:14px; color:#1b211d;">한국부동산원 AX센터 AX전략부</span><span style="color:#c9cfc3;">·</span><span>입찰 집행 조달청(위탁)</span><span style="color:#c9cfc3;">·</span><span>제안요청서 2026. 2.</span><span style="color:#c9cfc3;">·</span><a href="#" style="font-size:12px;">제안요청서 PDF ↗</a><span class="cap">나라장터 원문 링크 없음</span></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); border-top:1px solid #eef0ec;">{cells}</div>
        <div style="display:flex; justify-content:space-between; gap:12px; padding:10px 24px; border-top:1px solid #eef0ec; background:#fbfcf9;" class="cap"><span>2026-09-17 분석 · 입력 제안요청서 PDF 131쪽 · 회사 프로필(2026-08 기준)</span><span>상태 표시 · 원문 확정 / 본공고에서 확정 / 미확인 / 추론</span></div>
      </section>
"""


def decision():
    li = lambda ic, col, t, link: f'<li style="display:flex; gap:6px; align-items:flex-start;">{icon(ic, col, 14, 2.2)}<span>{t} {link}</span></li>'
    body = f"""<div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:12px;">
            <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:10.5px; background:#fff8ec; border:1px solid #f0dcb0;">{icon("alert", "#6e3500", 16, 2)}<div class="kv"><span style="font-size:14px; font-weight:600; color:#6e3500;">참여 불가 요인 · 확정 0 · 확인 필요 2</span><span class="cap2">직접생산확인증명서 · 중소기업확인서가 회사 자료에 없음. 없으면 참여 불가</span></div></div>
            <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:10.5px; background:#fff8ec; border:1px solid #f0dcb0;">{icon("alert", "#6e3500", 16, 2)}<div class="kv"><span style="font-size:14px; font-weight:600; color:#6e3500;">추적 결정 전 확인할 일 4건</span><span class="cap2">필수 자격 2 · PM 정규직 상주 인력 · 시연 데모 준비 → 9절</span></div></div>
          </div>
          <div style="display:flex; align-items:center; gap:14px;"><span class="cap2" style="font-weight:600; color:#1b211d;">시스템 권고</span><span class="tok tok-strong" style="height:28px; font-size:14px; padding:0 12px;">조건부 추진 검토</span><span class="cap2">최종 Go/No-Go가 아님 · 문서 직접 분석 결과</span></div>
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:16px;">
            <div class="kv" style="gap:6px;"><span class="cap">추진 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("check", "#587a2b", "sLLM·RAG 기반 AI 에이전트 플랫폼 구축이 회사의 AI 모델·AI Agent 개발 역할과 일치", R(4) + " " + pf("수행 역할 2.2"))}{li("check", "#587a2b", "요구사항 77건 중 대응 가능 62 · 갭 0", pg("5절"))}{li("check", "#587a2b", "공동수급 허용(5인 이하)으로 도메인·음성·OCR 보완 구성이 가능", R(72))}</ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">선결 조건</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("alert", "#6e3500", "직접생산확인증명서(8111159901)·중소기업확인서 보유 증빙", R(71))}{li("alert", "#6e3500", "제안 시점에 RAG·출처 표시 데모 준비(시연 16점)", R(76))}{li("alert", "#6e3500", "PM 정규직 · 사업기간 상주 가능 인력", R(66))}</ul></div>
            <div class="kv" style="gap:6px;"><span class="cap">반대 근거</span><ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;">{li("x", "#89001a", "시범운영 최소 2개월을 빼면 개발 기간이 약 4개월", R(41))}{li("x", "#89001a", "부동산 업무·음성 인식·AI OCR 수행 실적이 회사 자료에 없음", pf("대표 실적 2.4"))}{li("x", "#89001a", "제안서 보상 없음 · 데모 구축 비용을 선부담", R(73))}</ul></div>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; padding-top:10px; border-top:1px solid #eef0ec;" class="cap"><span>다음 행동 · 9절 확인 4건 → 나라장터 공고 수집·연결 → 추적 결정 → 본공고 조건 비교 → 최종 Go/No-Go</span><div class="btn btn-outline">추적 결정은 공고 연결 후</div></div>"""
    return section(1, "의사결정 요약", "한마디로 어떤가", '', body,
                   " box-shadow:0 1px 2px rgba(27,33,29,0.05), 0 6px 18px rgba(27,33,29,0.07), inset 0 0 0 1px #cfdfb5;")


def basics():
    return section(2, "공고 기본정보", "무엇을 하는 사업인가", '<span class="cap">원문 확정 11 · 본공고 확정 1 · 미확인 2</span>', kv_grid([
        ("목적·배경", "업무 복잡성·인력 부담 증가와 원내 지식 단절에 대응해 도메인 특화 sLLM·RAG 기반 지능형 업무 환경을 구축하고 AI 거버넌스 체계를 마련", "fact", R(3)),
        ("범위 · 포함", "① 다중 에이전트 아키텍처 설계 ② sLLM 기본·업무 특화 모델 구축과 성능 검증 ③ RAG 지식베이스·파이프라인 ④ 보고서·회의록·내규 등 10개 에이전트와 내부 챗봇·UI ⑤ 운영·보안·AI 윤리 검증 체계", "fact", R(4)),
        ("10개 에이전트", "챗봇 · 보고서 작성 · 회의록(STT·화자 구분) · 내규 조회 · OCR · 지식 검색 · 정형데이터(건축물대장·토지대장) 검색 · 주소 표준화 · 데이터 분석 · 문서 요약", "fact", R(20)),
        ("범위 · 제외", "개인정보 필터 U-PRIVACY SAFER v4.0, SSO Agent PASS-NI v5.0은 직접구매로 분리발주", "fact", R(8)),
        ("하드웨어·추론 인프라", "GPU 서버 등 공급 범위가 원문에 없음", "unk", small("9절 질의")),
        ("사용자·개발 환경", "한국부동산원 임직원 · JAVA 25, React 19.2, Oracle 19c · 시스템 구성도는 보안서약 후 열람", "fact", R(6)),
        ("산출물·검수", "착수계·사업수행계획서(계약 후 10일), 설계서, 테스트·시범운영 결과서, 매뉴얼, 소스코드, 완료보고서 · 발주자 승인 일자에 완료", "fact", R(64)),
        ("요구사항 규모", "77건 · 기능 14, 성능 5, 인터페이스 8, 데이터 11, 테스트 3, 보안 12, 품질 3, 제약 9, 관리 7, 지원 5", "fact", R(9)),
        ("수행 장소·상주", "PM은 정규직이며 한국부동산원 본사 또는 지정 장소에 상주, 주요 인력은 요청 시 상주", "fact", R(66)),
        ("계약 유형", "조달청 위탁 제한경쟁 · 전자 · 총액 · 협상에 의한 계약", "fact", R(3)),
        ("입찰 일정·보증금", "조달청 입찰공고문 참조", "bid", R(73)),
        ("과업심의위원회", "개최한 사업 · 과업 변경 시 심의 요청 가능", "fact", R(7)),
        ("추진 협조 부서", "윤리준법부·단독주택공시부·적정성검토부·주택통계부", "fact", R(5)),
        ("예산 산정 근거", "원문에 없음(적정 사업기간 산정서는 이미지 첨부)", "unk", R(90)),
    ]))


def eligibility():
    j = {"ok": chip("충족 확인", "tok-accent"), "unk": chip("미확인"), "limit": chip("참여 구조 제약", "tok-outline"), "allow": chip("허용", "tok-outline")}
    rows = [
        ["소프트웨어사업자", "최근 결산일 기준 신고 · 컴퓨터관련서비스사업(1468)<br>" + R(71), "1468 등록 확인<br>" + pf("자격·조달 5.2"), j["ok"]],
        ["중소 SW사업자", "중·소기업 SW사업자만 참여 · 상호출자제한기업집단 불가<br>" + R(71), '<span style="color:#79837c;">중소기업확인서 보유 기록 없음</span><br>' + pf("자격·조달 5.2"), j["unk"] + '<div class="cap">입찰 마감 전일까지 유효</div>'],
        ["직접생산 확인", "정보시스템개발서비스(8111159901) 직접생산확인증명서<br>" + R(71), '<span style="color:#79837c;">직접생산확인증명 미확인</span><br>' + pf("추가 확인 5.2"), j["unk"] + '<div class="cap">필수 · 9절</div>'],
        ["입찰참가자격 등록", "마감 전일까지 나라장터 등록<br>" + R(71), "1468 업종 등록 사실 확인<br>" + pf("자격·조달 5.2"), j["ok"]],
        ["결격 사유", "부정당업자 · 조세포탈 확정 2년 미경과자 제외<br>" + R(71), '<span style="color:#79837c;">회사 자료에 없음</span>', j["unk"]],
        ["공동수급", "공동이행 허용 · 대표사 포함 5인 이하 · 지분 10% 이상 · 협정서 입찰일 전일 18:00<br>" + R(72), "—", j["allow"]],
        ["하도급", "품질 보증을 위해 불허 · 공동수급체 외 인력은 하도급으로 간주<br>" + R(72), "—", j["limit"]],
        ["투입 인력", "제안 인력은 자사(공동수급 구성원) 인력 · PM 정규직 상주<br>" + R(72) + " " + R(66), '<span style="color:#79837c;">PM/PL 수·AI 인력 미확인</span><br>' + pf("인력 2.7"), j["unk"]],
    ]
    return section(3, "참여 가능성", "우리가 입찰할 수 있나", '<span class="cap">충족 확인 2 · 불충족 확인 0 · 미확인 4 · 허용 1 · 제약 1</span>',
                   table(["자격 항목", "공고 요구 · 근거", "회사 사실 · 근거", "판정"], rows) +
                   '<span class="cap">나라장터 입찰공고서와 제안요청서가 다르면 입찰공고서가 우선합니다(p.71). 회사 자료에 없는 자격은 충족·불충족으로 쓰지 않았습니다.</span>')


def evaluation():
    score = table(["평가 항목", "배점", "근거"], [
        ["정량 · 경영상태(신용평가등급)", "4", R(75)],
        ["정량 · 수행실적(최근 3년 생성형 AI 구축)", "6", R(75)],
        ["정성 · 전략 및 방법론", "12", R(75)],
        ["정성 · 기능(공통·LLM·RAG·에이전트)", "12", R(75)],
        ["정성 · 기술(인터페이스·보안·데이터·제약)", "12", R(75)],
        ["정성 · 성능 및 품질", "10", R(75)],
        ["정성 · 프로젝트 관리", "9", R(75)],
        ["정성 · 프로젝트 지원", "9", R(75)],
        ["정성 · 시연평가(정확성 8·응답 품질 8)", "16", R(75)],
        ["입찰가격", "10", R(75)],
        ['<b style="font-weight:600;">합계</b>', '<b style="font-weight:600;">100</b> ' + chip("재계산 일치", "tok-accent"), ""],
    ])
    est = f"""<div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px;">
            <div class="tile"><span class="cap">경영상태 예상</span><span style="font-size:14px; font-weight:600;">3.80 / 4</span><span class="cap2">회사 등급 BB0 → 배점의 95% {R(77)} {pf("기업 정보 1")}</span></div>
            <div class="tile"><span class="cap">수행실적 예상</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가 (4.2 ~ 6.0)</span><span class="cap2">생성형 AI 구축 실적 금액 미확인 · 블록체인·SI·챗봇·RPA는 불인정 {R(78)}</span></div>
          </div>"""
    rules = kv_grid([
        ("협상적격", "기술능력 원점수가 배점한도의 85% 이상 · 차등점수제(순위 간 3점)", "fact", R(73)),
        ("시연평가", "RAG·출처 표시 데모 필수 · 발주기관 질문 무작위 선택 · 당일 수정 불가 · 접속 불가 시 최하점", "fact", R(76)),
        ("시연 분야·학습 자료", "별도 안내 예정", "bid", small("9절 질의")),
        ("동점 처리", "기능 → 기술 → 전략·방법론 → 관리 → 지원 순 고득점", "fact", R(79)),
    ])
    submit = kv_grid([
        ("제안서", "PDF 전자제출 · A4 200쪽 이내 · 제안요약서 30쪽 · 조견표·약어표", "fact", R(83)),
        ("함께 낼 서류", "평가항목 자가점검표 · 시연평가 기초자료(별지 10) · 서약서 · 청렴계약 이행서약서 · 신용평가등급 확인서 · 수행실적 증명", "fact", pg("제안요청서 p.75·p.87")),
        ("제출 기한·장소", "조달청 입찰공고문 참조", "bid", R(88)),
        ("제안 설명회", "없음", "fact", R(88)),
        ("질의", "문서 질의 원칙 · 사업 문의 AX전략부 · 구두 답변은 법적 효력 없음", "fact", R(88)),
        ("제안서 보상", "20억원 미만이라 보상 없음", "fact", R(73)),
    ])
    body = f'<div style="display:grid; grid-template-columns: minmax(0,1.05fr) minmax(0,1fr); gap:20px;"><div class="kv" style="gap:8px;"><span class="cap">배점 (기술 90 · 가격 10)</span>{score}{est}{rules}</div><div class="kv" style="gap:8px;"><span class="cap">제출</span>{submit}</div></div>'
    return section(4, "평가와 제출", "어떻게 뽑고 무엇을 내나", '', body)


def fit():
    cats = table(["구분", "요구", "대응 가능", "추가 확인", "갭", "해당 없음"], [
        ["기능 SFR", "14", "6", "7", "0", "1"], ["성능 PER", "5", "3", "2", "0", "0"], ["인터페이스 SIR", "8", "7", "1", "0", "0"],
        ["데이터 DAR", "11", "10", "1", "0", "0"], ["테스트 TER", "3", "3", "0", "0", "0"], ["보안 SER", "12", "11", "1", "0", "0"],
        ["품질 QUR", "3", "3", "0", "0", "0"], ["제약 COR", "9", "8", "1", "0", "0"], ["관리 PMR", "7", "6", "1", "0", "0"],
        ["지원 PSR", "5", "5", "0", "0", "0"],
        ['<b style="font-weight:600;">합계</b>', '<b style="font-weight:600;">77</b>', '<b style="font-weight:600;">62</b>', '<b style="font-weight:600;">14</b>', '<b style="font-weight:600;">0</b>', '<b style="font-weight:600;">1</b>'],
    ])
    m = lambda s: f'<span class="mono" style="white-space:nowrap;">{s}</span>'
    rows = [
        [m("SFR-2"), "sLLM 경량화·업무 도메인별 학습", chip("추가 확인", "tok-yellow"), "AI 학습모델 개발은 확인, sLLM 경량화·파인튜닝 실적은 미확인 " + pf("보유 기술 2.1"), "기술 검증(SFR-9)과 데모에서 입증", R(13)],
        [m("SFR-4"), "STT·회의록, 다국어 번역, 문서 사전 검토", chip("추가 확인", "tok-yellow"), "음성 인식 기술 기록 없음", "STT 전문사 공동수급", R(15)],
        [m("SFR-5"), "Layout Detector·AI OCR과 학습 기능", chip("추가 확인", "tok-yellow"), "OCR 기술 기록 없음", "OCR 전문사 공동수급", R(16)],
        [m("SFR-13"), "10개 에이전트(건축물대장·주소 표준화 포함)", chip("추가 확인", "tok-yellow"), "보고서 생성·업무자동화는 확인, 부동산 공부 데이터 연계는 미확인 " + pf("보유 기술 2.1"), "연계 대상 시스템 질의", R(20)],
        [m("PER-4"), "동시 사용자 1,000명 · 첫 단어 5초 이내", chip("추가 확인", "tok-yellow"), "대규모 추론 성능 실적 미확인", "추론 인프라 제공 범위 질의", R(24)],
        [m("DAR-1~9"), "데이터 표준·구조·값 검증·이관·품질", chip("대응 가능", "tok-accent"), "데이터 표준화·품질관리 확인(근거 매우 강함) " + pf("보유 기술 2.1"), "—", R(32)],
        [m("SIR-6"), "연계 표준 수립·개인정보 필터링 수집", chip("대응 가능", "tok-accent"), "기관 간 API·시스템 연계 확인 " + pf("보유 기술 2.1"), "—", R(30)],
        [m("PMR-6"), "PM 정규직 · 상주", chip("추가 확인", "tok-yellow"), "PM/PL 수 미확인 " + pf("인력 2.7"), "상주 가능 PM 지정", R(66)],
        [m("COR-5"), "GS인증 제품 우선 납품 · 기술지원확약서", chip("추가 확인", "tok-yellow"), "GS인증 보유 미확인 " + pf("솔루션 2.8"), "납품 SW 목록 확정", R(56)],
        [m("SFR-14"), "대안 방안은 발주기관 협의 후 적용", chip("해당 없음", "tok-outline"), "협의 조항", "—", R(22)],
    ]
    body = f"""<div class="kv" style="gap:8px; padding:12px 14px; border-radius:10.5px; background:#f6f7f4;">
            <div style="display:flex; align-items:center; gap:10px;"><span class="sec-title">회사 적합성</span><span class="tok tok-accent">부합</span><span class="cap2">공고 과업과 회사 수행 역할·기술의 대조 · 사람이 확정</span></div>
            <ul class="kv" style="gap:6px; font-size:13px; line-height:1.5;"><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>sLLM·RAG 에이전트 플랫폼 구축 ↔ AI 모델 및 AI Agent 개발, 생성형 AI·LLM 기반 정보 분석 {R(4)} {pf("수행 역할 2.2 · 보유 기술 2.1")}</span></li><li style="display:flex; gap:8px;"><span class="tok tok-accent" style="flex:0 0 auto;">범위 일치</span><span>데이터 표준·품질·이관 11건 ↔ 데이터 표준화·품질관리 {R(32)} {pf("보유 기술 2.1")}</span></li><li style="display:flex; gap:8px;"><span class="tok" style="flex:0 0 auto;">정보 부족</span><span>부동산 공시·통계 업무 도메인, 음성 인식·AI OCR ↔ 회사 자료에 없음 {pf("사업영역 2.3")}</span></li></ul>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center;"><div style="display:flex; gap:8px;"><span class="tok tok-accent">대응 가능 62</span><span class="tok tok-yellow">추가 확인 14</span><span class="tok tok-red">갭 0</span><span class="tok tok-outline">해당 없음 1</span></div><span class="tok tok-accent">요구사항 ID 77건 모두 분류 · 총괄표 77건과 일치</span></div>
          {cats}
          <span class="cap">주요 항목 (추가 확인 14건 중 7건과 대표 대응 항목)</span>
          {table(["ID", "요구사항", "대응", "회사 근거 · 차이", "갭 대응 방향", "근거"], rows)}
          <span class="cap">갭은 확인된 요구와 확인된 역량이 어긋날 때만 씁니다. 회사 자료에 없는 역량은 추가 확인으로 남겼습니다.</span>"""
    return section(5, "과업 적합성", "우리가 잘할 수 있나", '', body)


def delivery():
    need = kv_grid([
        ("투입 인력", "PM 정규직 상주 · 주요 인력 요청 시 상주 · 인력 교체는 동급 이상과 사전 승인 · 인원·등급 규정 없음", "fact", pg("제안요청서 p.66·p.89")),
        ("마일스톤", "착수계·사업수행계획서 계약 후 10일 · 요구사항 정의서 분석 후 10일 · 중간보고 협의 · 시범운영 준공 전 최소 2개월 · 준공자료 이관계획 준공 30일 전 · 완료보고 종료 7일 전", "fact", pg("제안요청서 p.41·p.65")),
        ("보고", "주간·월간 보고와 착수·중간·완료 보고회 · 워크숍 비용은 수행사 부담", "fact", R(63)),
        ("발주기관과 정할 것", "sLLM 기반 모델·파라미터 규모, 벡터화 방법, 연계 문서 시스템, 1차 오픈 시기·대상, 정확도 평가 지표", "fact", pg("제안요청서 p.13·p.18·p.25")),
        ("선행 의존성", "시스템 구성도·정보화 현황은 보안서약 후 방문 열람(미확인 책임은 제안사)", "fact", R(7)),
    ])
    econ = f"""<div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:12px;"><div class="tile"><span class="cap">사업 예산</span><span style="font-size:14px; font-weight:600;">661,870,000원</span>{ST["fact"]}</div><div class="tile"><span class="cap">투입 원가 (인월 × 단가)</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 인력 구성안, 등급별 단가, 상주 비용</span></div><div class="tile"><span class="cap">제안 비용</span><span style="font-size:14px; font-weight:600; color:#79837c;">산정 불가</span><span class="cap2">필요 자료 · 데모 구축 인월 · 보상 없음</span></div></div>
          <div style="display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:12px;"><div class="tile"><span class="cap">원가에 넣어야 할 원문 비용</span><span style="font-size:13px; line-height:1.5;">SW 라이선스(계약금액 포함) · 시큐어코딩 검증 도구(사업자 제공) · 워크숍 · 기술이전 · 안정화 · 무상하자 1년</span><span class="cap2">{R(56)} {R(54)} {R(63)} {R(69)}</span></div><div class="tile"><span class="cap">계약 위험 비용</span><span style="font-size:13px; line-height:1.5;">보안 위약금 용역대가 1% · 3% · 5%, 심각 위반은 부정당업체</span><span class="cap2">{R(109)}</span></div></div>
          <span class="cap">입력이 없는 인월·원가·마진은 만들지 않았습니다.</span>"""
    body = f'<div class="kv" style="gap:8px;"><span class="cap">원문의 수행 조건</span>{need}</div><div class="kv" style="gap:8px;"><span class="cap">사업성</span>{econ}</div>'
    return section(6, "수행 계획과 사업성", "할 만한가", '', body)


def risks():
    contract = table(["계약 조건", "내용", "상태", "근거"], [
        ["계약 체결", "낙찰 후 7일 이내 · 세부 사업수행계획서 7일 이내", ST["fact"], R(81)],
        ["계약보증금", "계약금액의 5% 이상(유가증권·보증보험)", ST["fact"], R(81)],
        ["입찰보증금", "조달청 입찰공고문 참조", ST["bid"], R(73)],
        ["지체상금", "제안요청서에 없음", ST["unk"], small("9절")],
        ["대금 지급", "선금·기성 조건 없음 · 대금 신청 시 4대 보험 완납증명", ST["unk"], R(82)],
        ["하자보수", "검사 완료 후 1년 무상(H/W 3년) · 종료 후 12개월 장애 8시간 이내 대응", ST["fact"], pg("제안요청서 p.69·p.70")],
        ["지식재산권", "발주기관·제안사 공동소유 · 상업적 활용은 협의 · 산출물 반출은 확약서", ST["fact"], R(57)],
        ["보안 위약금", "중대 3% · 보통 2건 이상 1% · 심각 5%/부정당업체", ST["fact"], R(109)],
    ])
    rows = [
        ("sev-major", "중대", "참여 자격", "필수 자격 2건 미확인", "직접생산확인증명서·중소기업확인서가 없으면 입찰 무효", "보유·유효기간 확인, 없으면 발급 가능 기간 확인", "경영지원 · 추적 결정 전", "보유 확인 시 해소", 71),
        ("sev-major", "중대", "수행", "6개월 안에 개발 약 4개월", "sLLM 학습·10개 에이전트·연계를 시범운영 2개월 전까지 끝내야 함", "1차 오픈 범위 협의안과 WBS 초안 작성", "PM 후보 · 제안 전", "범위 협의 시 보통", 41),
        ("sev-major", "중대", "제안", "시연평가 16점과 데모 선행 구축", "평가 당일 수정 불가 · 접속 실패 시 최하점 · 보상 없음", "시연 분야 안내 확인, 사내 RAG 데모 재사용 가능성 점검", "기술연구소 · 추적 결정 전", "데모 자산 있으면 보통", 76),
        ("sev-normal", "보통", "기술·연계", "동시 1,000명·첫 단어 5초", "추론 인프라 공급 범위가 원문에 없어 성능 책임 범위 불명확", "GPU 등 인프라 제공 주체·사양 질의", "기획부 · 공고 확인 후", "답변에 따름", 24),
        ("sev-normal", "보통", "보안·개인정보", "폐쇄망·인터넷 차단 개발 환경", "외부 모델·패키지 반입 제약, 원격 개발은 지정 단말·통제시스템 경유", "보안서약 후 자체 보안대책 열람, 오프라인 개발 도구 준비", "보안 담당 · 착수 전", "낮음", 44),
        ("sev-normal", "보통", "보안·개인정보", "국정원 보안적합성 검증 지원 의무", "사업 종료 후에도 조치 완료까지 지원 · 추가 비용은 제안사 귀책", "검증 지원 공수를 원가에 반영", "PM 후보 · 제안 전", "보통", 49),
        ("sev-low", "낮음", "법률·계약", "문서 안 조문·장 번호 불일치", "S/W사업정보 제출 근거가 제46조(COR-3)와 제22조(PMR-3)로 다름 · 목차 장 번호와 본문 불일치", "의견등록으로 정정 요청", "기획부 · 의견등록 기간", "낮음", 55),
    ]
    cards = "".join(
        f'<li class="kv" style="gap:6px; padding:12px 14px; border-radius:10.5px; border:1px solid #eef0ec;"><div style="display:flex; align-items:center; justify-content:space-between; gap:8px;"><div style="display:flex; align-items:center; gap:8px;"><span class="sev {s}">{sl}</span><span class="tok tok-outline" style="height:18px; font-size:11px;">{cat}</span><span style="font-size:14px; font-weight:600;">{t}</span></div>{R(p)}</div>'
        f'<div style="display:grid; grid-template-columns: 90px minmax(0,1fr) 90px minmax(0,1fr); gap:4px 12px; font-size:13px; line-height:1.5;"><span class="cap">영향</span><span>{imp}</span><span class="cap">확인·완화</span><span>{act}</span><span class="cap">담당 · 기한</span><span>{own}</span><span class="cap">잔여 위험</span><span>{res}</span></div></li>'
        for s, sl, cat, t, imp, act, own, res, p in rows)
    body = f'<ul class="kv" style="gap:10px;">{cards}</ul><div class="kv" style="gap:8px;"><span class="cap">계약 조건</span>{contract}</div>'
    return section(7, "위험", "무엇이 발목을 잡나", '<span class="cap">차단 0 · 중대 3 · 보통 3 · 낮음 1</span>', body)


def strategy():
    row = lambda k, v: f'<li style="display:grid; grid-template-columns: 110px minmax(0,1fr); gap:12px;"><span class="cap2" style="font-weight:600; color:#1b211d;">{k}</span><span>{v}</span></li>'
    body = f"""<ul class="kv" style="gap:10px; font-size:13px; line-height:1.55;">
            {row("발주 배경", "생성형 AI로 기존 챗봇·자동화를 대체하고, 업무 순환에 따른 지식 단절과 전문가 의존을 줄이려 함 " + R(3))}
            {row("평가 초점", "시연 16점이 단일 항목 중 가장 크고 기능·기술 각 12점이라, 실제로 답하고 출처를 보이는 데모와 sLLM·RAG 구현 구체성이 승부처로 보임 " + ST["inf"])}
            {row("차별점·레퍼런스", "AI Agent 기반 R&D 분석·의사결정 플랫폼과 AI 공보관 보고서 생성 경험을 보고서·데이터 분석 에이전트 근거로, 데이터 표준화 실적을 DAR 11건 근거로 제시 " + pf("대표 실적 2.4") + " " + ST["inf"])}
            {row("보완 구성", "하도급 불허라 음성 인식·OCR·부동산 데이터 경험사는 공동수급 구성원으로만 참여 가능 " + R(72) + " " + ST["inf"])}
            {row("반대 근거", "수행실적 점수는 최근 3년 생성형 AI 구축 금액만 인정되어 블록체인·SI 실적이 점수에 들어가지 않음 " + R(78))}
          </ul>"""
    return section(8, "제안 전략", "어떻게 이기나", ST["inf"], body)


def todo():
    blk = chip("추적 결정 전", "tok-orange")
    nb = '<span class="cap">—</span>'
    c = '<span class="check" style="display:inline-block; vertical-align:middle;"></span>'
    rows = [
        [c, "직접생산확인증명서(정보시스템개발서비스 8111159901) 보유·유효기간", "내부 확인", "경영지원", "추적 결정 전", blk, pg("3절")],
        [c, "중소기업확인서 유효기간(입찰 마감 전일 기준)", "내부 확인", "경영지원", "추적 결정 전", blk, pg("3절")],
        [c, "PM 정규직·상주 가능 인력과 sLLM·RAG 개발 인력", "내부 확인", "사업부", "추적 결정 전", blk, pg("6절")],
        [c, "RAG·출처 표시 데모를 제안 기간 안에 준비할 수 있는지", "내부 확인", "기술연구소", "추적 결정 전", blk, pg("7절")],
        [c, "최근 3년 생성형 AI 구축 실적 금액(수행실적 점수)", "내부 확인", "기획부", "제안 전", nb, pg("4절")],
        [c, "GPU 등 추론 인프라 공급 범위와 사양", "발주기관 질의", "기획부", "공고 확인 후", nb, pg("2절")],
        [c, "시연 분야·학습 자료·질문 수·멀티턴 제한", "발주기관 질의", "기획부", "공고 확인 후", nb, pg("4절")],
        [c, "지체상금·대금 지급(선금·기성) 조건", "본공고 확인", "기획부", "본공고", nb, pg("7절")],
        [c, "음성 인식·AI OCR·부동산 데이터 공동수급 후보", "내부 확인", "사업부", "제안 전", nb, pg("5절")],
        [c, "조문 근거(제46조·제22조)와 목차 장 번호 불일치 정정", "발주기관 질의", "기획부", "의견등록 기간", nb, pg("7절")],
    ]
    return section(9, "확인할 일", "무엇을 더 알아야 하나", '<span class="cap">10건 · 추적 결정 전 4 · 발주기관 질의 3 · 본공고 확인 1</span>',
                   table(["", "항목", "구분", "담당", "기한", "막는 결정", "출처"], rows) +
                   '<span class="cap">의견등록 마감일은 공고가 수집되지 않아 확인하지 못했습니다. 기한은 공고 확인 뒤 날짜로 바꿉니다.</span>')


def trust():
    docs = table(["입력 문서", "쪽", "분석 포함", "근거 표기"], [
        ["한국부동산원 AI 에이전트 플랫폼 구축 용역.pdf", '<span style="white-space:nowrap;">131쪽</span>', chip("포함", "tok-accent"), "제안요청서 p.n (PDF 쪽)"],
        ["같은 이름의 HWP 원본", "—", chip("미사용 · PDF와 동일본으로 간주 안 함"), "—"],
        ["적정 사업기간 산정서(p.90)·영향평가 결과서(p.116)", "2쪽", chip("글자 없음 · 이미지"), "—"],
        ["회사 프로필(2026-08 기준)", "—", chip("포함", "tok-accent"), "프로필 · 절 번호"],
    ])
    checks = table(["확인", "결과", "내용"], [
        ["요구사항 수", chip("일치", "tok-accent"), "총괄표 77건 = 목록 77건 = 상세 77건"],
        ["배점 합계", chip("일치", "tok-accent"), "정량 10 + 정성 80 + 가격 10 = 100 · 정성 세부 합 80"],
        ["평가 비중", chip("일치", "tok-accent"), "종합 기술 90 · 가격 10 = 배점표"],
        ["요구사항 명칭", chip("불일치", "tok-yellow"), "SFR-1 목록 ‘서비스 구성’ · 상세 ‘시스템 구성’"],
        ["조문 근거", chip("불일치", "tok-yellow"), "S/W사업정보 제출 근거 제46조(p.55) · 제22조(p.62)"],
        ["목차 장 번호", chip("불일치", "tok-yellow"), "목차 Ⅲ 제안요청 내용 · 본문 Ⅳ 제안요청 내용"],
        ["BidOps 결정적 검사", chip("미실행"), "인용 대조·요구사항 inventory 검사는 돌리지 않음"],
    ])
    run = '<div style="display:flex; gap:16px; flex-wrap:wrap;" class="cap2"><span>분석 · Claude가 PDF 텍스트(pdftotext -layout)를 직접 판독</span><span>2026-09-17</span><span>BidOps 모델·토큰 기록 없음</span></div>'
    body = f'<div style="display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap:20px;"><div class="kv" style="gap:8px;"><span class="cap">입력 범위</span>{docs}</div><div class="kv" style="gap:8px;"><span class="cap">문서 내부 대조</span>{checks}</div></div><div class="kv" style="gap:6px;"><span class="cap">실행 정보</span>{run}</div><span class="cap">쪽 번호는 PDF 쪽이며 본문 하단 인쇄 쪽 번호는 PDF 쪽에서 2를 뺀 값입니다. 나라장터 입찰공고서와 다르면 입찰공고서가 우선합니다. 이 결과는 참조 분석이며 품질 측정·운영 승인 근거가 아닙니다.</span>'
    return section(10, "신뢰성과 한계", "결과를 믿을 수 있나", chip("문서 대조 불일치 3", "tok-yellow"), body)


def human():
    radios = "".join(
        f'<div style="display:flex; align-items:center; gap:8px; height:36px; padding:0 12px; border-radius:8.75px; border:1px solid #c9cfc3; background:#ffffff; font-size:13px; font-weight:500;"><span style="width:14px; height:14px; border-radius:50%; box-shadow:inset 0 0 0 1.5px #9aa39c; background:#ffffff;"></span>{t}</div>'
        for t in ["추진", "조건부 추진", "보류", "검토 종료"])
    body = f"""<div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">사람 의견 <span class="cap">· 필수 · 시스템 권고와 별개로 기록 · 기본 선택 없음</span></span><div style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:8px;">{radios}</div></div>
          <div style="display:grid; grid-template-columns: minmax(0,1fr) 220px; gap:12px; align-items:end;">
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">사유 <span class="cap">· 필수</span></span><div class="field" style="height:64px; align-items:flex-start; padding-top:8px;"><span>예: 필수 자격 2건과 데모 준비가 확인되면 추적 시작</span></div></div>
            <div class="kv" style="gap:6px;"><span class="cap2" style="font-weight:600; color:#1b211d;">담당자 이름 (필수)</span><div class="field" style="height:36px;"><span>예: 홍길동</span></div><div class="btn btn-primary" style="height:36px;">의견 저장</div></div>
          </div>
          <div class="kv" style="gap:4px;"><span class="cap">기록</span><div class="li" style="font-size:13px;"><span>수정본 1 · 문서 직접 분석 · 2026-09-17</span><span class="cap2">사람 의견 없음</span></div></div>
          <span class="cap">의견은 보고서를 고치지 않습니다. 추적 결정은 공고를 사업기회에 연결한 뒤 사전규격 상세에서, 입찰 참여는 최종 Go/No-Go에서 사람이 결정합니다.</span>"""
    return section(11, "사람 기록", "누가 어떻게 판단했나", '', body)


def rail():
    items = [(1, "의사결정 요약", "확인 4"), (2, "공고 기본정보", "미확인 2"), (3, "참여 가능성", "미확인 4"), (4, "평가와 제출", "산정 불가 1"),
             (5, "과업 적합성", "추가 확인 14"), (6, "수행 계획과 사업성", "산정 불가"), (7, "위험", "중대 3"), (8, "제안 전략", "추론"),
             (9, "확인할 일", "10건"), (10, "신뢰성과 한계", "불일치 3"), (11, "사람 기록", "")]
    rows = "".join(
        f'<a href="#" style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; border-radius:5.25px; font-size:13px; {"background:#f1f6e8; color:#3f5a1c; font-weight:600;" if n == 3 else "color:#4c5650;"}"><span style="display:flex; gap:8px;"><span class="mono" style="min-width:16px;">{n}</span>{t}</span>' + (f'<span class="cap">{mk}</span>' if mk else "") + '</a>'
        for n, t, mk in items)
    toc = f'<div class="card kv" style="gap:2px; padding:12px 10px;"><span class="cap" style="padding:0 10px 6px;">보고서 절</span>{rows}</div>'
    viewer = f"""<div class="card kv" style="gap:10px; padding:14px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center;"><span class="sec-title">원문 근거</span><a href="#" style="font-size:12px;">PDF 열기 ↗</a></div>
      <div class="kv" style="gap:4px;"><span class="cap">선택 · 3절 직접생산 확인</span><span style="font-size:13px; font-weight:600;">제안요청서 p.71 · Ⅴ.1 입찰참가자격</span></div>
      <div style="padding:12px; border-radius:10.5px; background:#fbfcf9; border:1px solid #eef0ec; font-size:13px; line-height:1.7; color:#4c5650;">
        <p>ㅇ 「중소기업 범위 및 확인에 관한 규정」에 따라 전자입찰서 제출 마감일 전일까지 발급되어 유효기간 내에 있는 중소기업확인서를 소지한 자 <span class="hl">및 정보시스템 개발서비스(세부품명번호 : 8111159901)의 직접생산 확인증명서를 소지한 자</span></p>
      </div>
      <div class="kv" style="gap:4px; padding-top:8px; border-top:1px solid #eef0ec;"><span class="cap">대조한 회사 사실</span><span style="font-size:13px;">프로필 5.2 추가 확인 필요 · direct_production_certificate: 값 없음</span></div>
    </div>"""
    return toc + viewer


def artboard_report_reb():
    main = decision() + basics() + eligibility() + evaluation() + fit() + delivery() + risks() + strategy() + todo() + trust() + human()
    body = head() + f'<div style="display:grid; grid-template-columns: minmax(0,1fr) 280px; gap:16px; align-items:start;"><div class="kv" style="gap:16px;">{main}</div><div class="kv" style="gap:16px;">{rail()}</div></div>'
    return page(9950, ["탐색과 추적", "사전규격", "번호 미확인", "심층 검토 보고서"], '<div class="btn btn-outline">보고서 이력</div>', body, max_width=1136)
