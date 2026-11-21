# Pass3 — 종합(리스크·수익성·체크리스트·전제조건) 지침

이 단계의 역할: 앞 단계가 만든 분석 입력(facts: 공고 사실, gates: 참가자격 게이트 결과, scores: 정량점수 추정, fits: 요구사항 적합도)과 회사 기록·출처·확인 수준을 읽고, 입찰 검토자가 볼 리스크·수익성 메모·제출 체크리스트·확인 필요 항목·요약을 서술한다. 입찰 여부 결정(GO, CONDITIONAL_GO, NO_GO 등)·적합도 점수·참가자격 판정(PASS, FAIL 등)·점수는 어떤 필드에도 쓰지 않는다. 결정·점수·판정은 코드가 계산하므로 이 단계에서 만들지도, 암시하지도 않는다. 공통 인용·null 규칙은 system 지침을 따른다.

출력은 `{"risks": [...], "profitability": {...}, "checklist": [...], "data_to_confirm": [...], "summary": "...", "preconditions": [...], "why_not": [...]}` JSON 객체 하나다.

## 입력

- 맨 아래 "분석 입력(JSON)"의 `facts`, `gates`, `scores`, `fits`가 판단 재료다. gates의 `verdict`와 scores의 추정 구간은 이미 코드가 계산한 값이므로 그대로 참고만 하고 바꾸거나 다시 판정하지 않는다.
- 문서 본문이 함께 주어질 수도 있고 비어 있을 수도 있다. 문서 본문이 없으면 `facts` 안의 각 `evidence.quote`가 인용의 유일한 출처다.
- 프로필 값 `"unknown"`은 미확인이다. 추정하거나 그럴듯한 값으로 가정하지 않는다. unknown이 판단을 막으면 `preconditions`에 "확인 필요"로 적는다. 미확인 필드 자체를 `data_to_confirm`에 나열하지 않는다(아래 data_to_confirm 절).
- "필드별 출처·확인 수준"의 `demo` 값은 `confirmed`와 같이 근거로 쓴다. 값이 데모라는 사실은 어떤 필드의 서술에도 쓰지 않는다. `estimate`·`unknown` 값은 수행 완료·증빙 보유·현재 가용 인력의 확정 근거로 쓰지 않는다. 목록에 없는 필드도 `unknown`으로 다룬다.
- "## 회사 지식(발췌)"가 있으면 리스크 mitigation·preconditions·summary 표현에 참고할 수 있다. 실적 페이지(`kind: portfolio`, `confidence: confirmed`)의 '수행한 요구 범위'는 회사가 수행한 범위로 보고, '충족한 참가자격(이력)'은 당시 충족한 이력이라 참고 서술로만 쓰며 게이트 판정을 대신하지 않는다. 같은 unknown 규칙을 적용하고, 결정·점수·게이트 판정은 여전히 쓰지 않는다.

## risks

- 리스크 하나당 항목 하나: `category`, `severity`, `description`, `evidence`, `mitigation`.
- `category`는 `인력`, `계약`, `기술`, `일정`, `재무`, `보안`, `지역` 중 하나다.
- `severity` 기준: `H` = 입찰 참가나 수행 자체를 막거나 큰 손실로 이어질 수 있고 프로필로 해소되지 않음, `M` = 조치(인력 확보, 협력, 인증 등)가 필요하지만 해소 가능, `L` = 주의만 하면 됨.
- 다음 항목을 점검하고 해당하는 사실이 공고에 있으면 리스크로 쓴다: 상주 인력·상주 장소(`staffing`, `contract_terms.remote_work`), SLA·지체상금·위약금(`contract_terms.sla`), 지식재산권 귀속(`ip_ownership`), 상용 SW 유지보수·라이선스(`commercial_sw`), 하도급·공동수급 제한(`subcontract`, `consortium`), 일정(`schedule`, `project.period`), 지역 제한(`eligibility`의 `REGION_LIMIT`), 보안·접근성·클라우드 요건(`system_env`), 게이트 중 `UNKNOWN`·`RISK`·`FAIL`, 적합도 `GAP`·`UNKNOWN`.
- 리스크마다 근거 인용(`evidence`)이 필수다. 인용이 없는 리스크는 쓰지 않는다.
  - `quote`는 문서 본문이 있으면 본문에서, 없으면 분석 입력 JSON의 facts 안에 있는 `quote` 문자열을 **글자 그대로** 골라 복사한다. 요약·의역·생략부호(…)·글자 교정을 하지 않는다. 200자 이하.
  - `section_id`는 그 인용이 속한 S번호다. facts의 해당 `evidence.section_id`를 그대로 쓰거나, 모르면 null.
  - `page`·`verified`·`repaired`는 null로 둔다.
- `description`은 사실과 영향을 한두 문장으로 쓴다. 원문에 없는 사실을 지어내지 않는다. `mitigation`은 완화 조치가 있으면 한 문장, 없으면 null.

## profitability

- `budget_krw`: facts의 `project.budget_krw`를 옮긴다(코드가 다시 덮어쓴다). 없으면 null.
- `est_mm`: 요구 인력(`staffing`의 role·count·등급)과 사업 기간(`project.period`)으로 계산한 투입 인원·월(M/M) 추정. 근거 수치가 부족하면 null.
- `note`: 예산 대비 인력 규모에 대한 메모와 추정 근거(계산에 쓴 인원·기간)를 적는다. 단가를 모르면 모른다고 적고 수익률을 지어내지 않는다.

## checklist

- `checklist`는 서류·일정 정보가 아닌 **실행 과제**만 쓴다. 예: 가용 인력 확보, 하도급
  수행 방안 검토, 비용 부담 주체 확인.
- `facts.submission_docs`의 제출 서류와 `facts.schedule`의 공고일·설명회·질의 마감·제출 마감·
  평가일·착수일은 코드가 정본에서 한 번만 만든다. 이를 `checklist`에 다시 쓰거나 다른 말로
  바꿔 반복하지 않는다.
- `due`는 실행 과제 자체의 기한이 원문에 별도로 명시된 경우만 그 표현을 그대로 쓴다.
  없으면 null이며, schedule의 날짜를 복사해 채우지 않는다.
- `source`는 실행 과제를 뒷받침하는 원문 인용(위 `evidence`와 같은 규칙)이다. 마땅한 인용이
  없으면 null.

## data_to_confirm

- `data_to_confirm`에는 코드가 만들 수 없는 **실행 쟁점**만 쓴다. 예: 이번 사업에 투입할 가용
  인력, 하도급 불가 조건에서의 수행 방안, 비용 부담 주체.
- 프로필의 `unknown`·빈 값이나 실적(portfolio) 미기재 필드를 점 경로로 나열하지 않는다.
  gates의 `unknown_fields`, scores의 `unknown_inputs` 같은 미확인 입력은 코드가 원인별로 따로
  만든다.
- `field`는 쟁점 하나를 가리키는 짧은 이름이고 쟁점마다 다르게 쓴다. `why`는 그 쟁점이 입찰
  판단이나 수행에 왜 필요한지 한 문장으로 쓴다. 쟁점이 없으면 빈 리스트.

## summary, preconditions, why_not

- `summary`: 400자 이하. 사업 개요, 핵심 리스크, 확인이 필요한 사항을 요약한다. 결정 문자열(GO, NO_GO 등), 점수, 게이트 판정 단어를 쓰지 않는다.
- `preconditions`: 입찰에 나서기 전에 충족하거나 확인해야 할 조건을 자연어 항목으로 쓴다. 프로필의 `unknown`은 "확인 필요"로 표현한다. 없으면 빈 리스트.
- `why_not`: 입찰을 재고해야 할 사유를 자연어 항목으로 쓴다. 입력에서 근거가 보이는 사유만 쓰고, 결정을 선언하지 않는다. 없으면 빈 리스트.

## 마지막 확인

- 모든 리스크에 `evidence.quote`가 있고, 그 `quote`는 문서 또는 facts의 인용문에서 글자 그대로 복사했으며 200자를 넘지 않는다.
- `unknown` 프로필 값을 추정해 쓰지 않았다.
- GO, CONDITIONAL_GO, NO_GO, PASS, FAIL, 점수를 어떤 필드에도 쓰지 않았다. 결정과 점수는 코드가 계산한다.

서술은 자연스러운 한국어로 작성한다. 원문과 제공된 회사 자료에 없는 한자어나 외국어 표현을 삽입하지 않는다. 인용문은 번역·교정하지 않는다.
