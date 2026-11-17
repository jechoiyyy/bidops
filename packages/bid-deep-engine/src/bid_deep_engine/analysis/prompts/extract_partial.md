# Pass1 (구간) — RfpFactsPartial 사실 추출 지침

이 단계의 역할: RFP의 **일부 구간**을 읽어 그 구간에 쓰여 있는 사실을 옮기기만 한다. 참가 가능 여부·PASS/FAIL 같은 판정 문자열을 쓰지 않는다. 회사 정보와 비교하지 않고, 점수를 계산하지 않고, 입찰 여부를 권하지 않는다. 구간 안의 값을 스키마의 해당 필드로 옮긴다. 공통 인용·숫자·null 규칙은 system 지침을 따른다.

## 구간 입력 규칙

- 입력 문서는 RFP 전체가 아니라 앞뒤가 잘린 일부 구간이다. 섹션 표지(`<<S012 | kind=… | p.…>>`)는 원문 그대로 남아 있으며 `section_id`는 이 표지의 S번호를 쓴다. 이 구간에 요구사항 목록 블록(`<<REQUIREMENTS …>>`)은 없다.
- **이 구간에 나타난 사실만** 채운다. 다른 구간에 있을 법한 값(예: 이 구간에 사업 개요가 없는데 사업명·예산)을 추측하거나 짐작으로 채우지 않는다. 문서의 다른 부분은 보이지 않는다고 가정한다.
- 이 구간에 근거가 전혀 없는 **최상위 항목은 `null`**이다. 객체(`project`, `schedule`, `evaluation`, `contract_terms`, `system_env`)와 리스트(`eligibility`, `staffing`, `commercial_sw`, `deliverables`, `submission_docs`) 모두 마찬가지다. 빈 객체나 빈 리스트로 채우지 않는다. `null`은 "이 구간은 모른다"는 뜻이고, 합치는 단계가 다른 구간의 값과 코드로 병합한다.
- 최상위 객체를 채울 때도 그 구간 원문에 있는 필드만 채우고 나머지 필드는 `null`(리스트 필드는 빈 리스트)로 둔다.
- 사업명(`project.name`)을 포함한 모든 값은 이 구간 원문에 쓰여 있을 때만 채운다. 사업명이 이 구간에 없으면 `project.name`은 `null`이며 지어내지 않는다.
- 같은 사실이 다른 구간에도 나올 수 있다. 이 구간에서 본 그대로 옮기고, 다른 구간과 값이 다르더라도 맞추거나 조정하지 않는다(충돌 기록은 합치는 단계가 한다).

출력은 RfpFactsPartial JSON 객체 하나다. 최상위 필드는 `project`, `schedule`, `eligibility`, `evaluation`, `staffing`, `contract_terms`, `commercial_sw`, `system_env`, `deliverables`, `submission_docs`다. `schema_version`은 1로 둔다. `conflicts` 필드는 없다.

## 근거(evidence)

- `Evidence` 객체는 `quote`(원문 그대로 200자 이하 연속 구간), `section_id`(표지의 S번호), `page`·`verified`·`repaired`(모두 null)로 쓴다.
- 리스트 형태의 `evidence` 필드(`project`, `schedule`, `evaluation`, `contract_terms`)에는 그 객체에 채운 값을 뒷받침하는 근거를 항목별로 1개 이상 넣는다. 값을 채웠는데 근거가 없으면 안 된다. 값이 모두 null이면 빈 리스트로 둔다.
- 단일 `evidence` 필드(`eligibility[]`, `evaluation.quantitative[]`, `staffing[]`, `commercial_sw[]`, `submission_docs[]`의 각 항목)는 필수다. 그 항목을 가장 잘 뒷받침하는 원문 한 구간을 넣는다.

## project

- `name`: 문서에 사업명이 있을 때만 쓴다. 없으면 null. 지어내지 않는다.
- `agency`: 발주기관 이름. `agency_type`은 `중앙행정`, `지자체`, `교육기관`, `공공기관`, `민간`, `기타` 중 하나이거나 null이다. 정부 부처·청은 `중앙행정`, 시·도·시·군·구는 `지자체`, 학교·교육청은 `교육기관`, 공기업·공단·공사·출연기관은 `공공기관`이다. 판단 근거가 문서에 없으면 null.
- `budget_krw`: 사업예산(추정금액·배정예산·사업비 등) 원 단위 정수. 천원 단위 표기는 곱해서 정수화한다. `budget_note`에는 원문 용어(예: "배정예산", "추정가격")와 조건(부가가치세 포함 여부, 조달수수료 별도 등)을 적는다. `vat_included`는 부가가치세 포함이 명시되면 true, 별도가 명시되면 false, 없으면 null. `is_fixed_price`는 정액(확정금액) 계약이라고 명시된 경우만 true, 실비정산 등이면 false, 없으면 null.
- `period`: `start`·`end`는 `YYYY-MM-DD`, `days`·`months`는 원문 기간 수치, `note`에는 원문 표현(예: "계약체결일로부터 12개월")을 적는다. 시작일·종료일이 없으면 null.
- `contract_method`: 계약 방식(예: "협상에 의한 계약", "적격심사"). `bidding_method`: 입찰 방식(예: "제한경쟁", "일반경쟁", "수의계약")과 전자입찰 여부 등 원문 표현.

## schedule

- `notice_date`(공고일), `briefing`(설명회), `qna_deadline`(질의 마감), `submission_deadline`(제안서·입찰서 제출 마감), `eval_date`(평가일), `kickoff`(착수·계약 예정일)은 `YYYY-MM-DD` 또는 시각이 있으면 `YYYY-MM-DD HH:MM` 형식이다. 연도가 없어 형식을 맞출 수 없으면 원문 문자열을 그대로 쓴다. 문서에 없는 일정은 null.

## eligibility

참가자격 요건 하나당 `EligibilityRule` 하나다. 문서가 한 조항에 여러 요건을 묶었으면 요건별로 나눈다. `text`는 요건 문구를 원문 그대로 옮긴다(창업기업 특례 등 단서도 포함). `code`는 아래 값 중 하나다. 해당하는 코드가 없으면 `OTHER`.

- `G2B_REGISTERED`: 나라장터(국가종합전자조달) 입찰참가자격 등록
- `INDUSTRY_CODE`: 업종(면허·업종코드) 등록 요건 — `params.industry_code`에 코드 목록
- `SW_BUSINESS_REPORT`: 소프트웨어사업자 신고(소프트웨어진흥법)
- `SME_CERT`: 중소기업·소기업·소상공인 확인서 등 기업 규모 증명
- `DIRECT_PRODUCTION`: 직접생산확인증명 — `params.item_no`에 세부품명번호(10자리)를 원문 그대로
- `LARGE_CORP_EXCLUDED`: 대기업 참여 제한
- `MUTUAL_INVEST_GROUP_EXCLUDED`: 상호출자제한기업집단 소속 기업 참여 제한
- `REGION_LIMIT`: 지역 제한(본사·사업장 소재지) — `params.region`에 지역 목록
- `DEBARMENT`: 부정당업자 입찰참가자격 제한 해당 여부
- `TAX_DELINQUENCY`: 국세·지방세 체납 여부
- `PAST_PERFORMANCE`: 참가자격으로서의 수행실적 — `params.years`(최근 N년), `params.amount_krw`(금액 기준, 원), `params.keyword`(실적 종류 키워드)
- `REQUIRED_CERT`: 필수 인증·자격(ISO, GS 인증 등) — `params.cert_name`
- `OTHER`: 위에 해당하지 않는 요건

`params`는 위에 나열한 코드별 필드만 채운다. 그 밖의 코드는 `params`를 비워 둔다(모든 값 null). 원문에 없는 값은 null.

## evaluation

- `tech_weight`·`price_weight`: 기술평가와 가격평가 비율(정수, 예: 90과 10). 협상에 의한 계약이 아니면 문서에 있는 만큼만 쓴다.
- `qualifying_rule`: 협상적격 기준 문구를 원문 그대로. `qualifying_threshold`: 기준 수치(숫자). `qualifying_basis`: 기준이 점수면 `points`, 배점한도 대비 비율이면 `percent`. 예: "기술평가 85점 이상" -> 85, `points`. "배점한도의 85% 이상" -> 85, `percent`. 기준이 없으면 셋 모두 null.
- `quantitative`: 정량평가 항목. **평가표의 행 하나 = EvalItem 하나**다. 같은 분류이거나 비슷한 항목이라도 합치지 않는다. 행마다 `item`(항목명), `max_points`(그 행의 배점, 숫자), `kind`, `criteria`, `criteria_table_id`, `evidence`를 쓴다. 한 행의 하위 항목이 별도 행으로 배점이 따로 있으면 각각 별도 EvalItem이다.
  - `kind`: 신용평가등급 항목은 `CREDIT_RATING`, 수행실적 항목은 `PAST_PERFORMANCE`, 인증 건수(보유·획득 건수) 항목은 `CERT_COUNT`, 교육 이수 인원 항목은 `STAFF_TRAINING`, 그 밖은 `OTHER`.
  - `criteria`: 그 행의 배점표에 나온 조건과 점수를 그대로 옮긴 목록(`condition` 원문, `points` 숫자). 배점표가 없으면 빈 리스트. 창업기업 특례 기준은 `condition`에 원문 그대로 둔다.
  - `criteria_table_id`: 항상 null. 입력에 표 ID가 없으므로 채우지 않는다.
- `qualitative`: 정성평가 항목(`item`, `max_points`). 평가위원이 점수를 매기는 항목이다.
- `evidence`: 비율·기준점·평가 방식을 뒷받침하는 근거(1개 이상).

## staffing

투입 인력 요건 한 줄당 `StaffingReq` 하나. `role`(역할·직무), `grade`(`초급`, `중급`, `고급`, `특급` 중 하나, 원문에 없으면 null), `count`(인원 수), `resident`(상주 요건이 명시되면 true, 비상주가 명시되면 false, 없으면 null), `location`(상주·근무 장소), `min_years`(최소 경력 연수), `notes`(자격 요건 등 기타 조건), `evidence`.

## contract_terms

- `subcontract`: `allowed`(하도급 허용 true, 금지 false, 언급 없으면 null), `limit_pct`(한도 비율 숫자), `note`.
- `consortium`: `allowed`(공동수급 허용 여부), `type`(`공동이행`, `분담이행`, `주계약자`, `혼합` 중 하나 또는 null), `note`(구성원 수·지분 제한 등).
- `ip_ownership`: 산출물 지식재산권 귀속 조항의 원문 표현. `sla`: `has`(SLA·서비스 수준 협약 존재 여부), `penalty_note`(지체상금·페널티 조건 원문). `warranty_months`: 하자보수·무상유지보수 기간(개월). `proposal_compensation`: 제안 보상 관련 문구. `proposal_page_limit`: 제안서 쪽수 제한(정수).
- `remote_work`: `allowed`(원격 근무 허용 여부), `note`.
- `evidence`: 위 항목을 뒷받침하는 근거(1개 이상).

## commercial_sw, system_env, deliverables, submission_docs

- `commercial_sw`: 상용 소프트웨어를 사용하거나 납품하라고 명시된 항목 하나당 하나(`name`, `vendor`, `evidence`).
- `system_env`: 기술 환경. `framework`(예: 전자정부 표준프레임워크), `cloud`(클라우드·호스팅 요건), `accessibility_std`(웹 접근성 표준·인증), `cms`(콘텐츠 관리 시스템). 없으면 null.
- `deliverables`: 납품·산출물 이름 목록(문자열). 원문 표기대로.
- `submission_docs`: 입찰·제안 시 제출해야 하는 서류 하나당 하나다. `name`, `due`(제출 기한),
  `copies`(부수·세트 수), `stage`(제출 단계·방법), `condition`(조건부 제출 조건), `evidence`를
  쓴다. 네 문자열 필드는 이 구간의 원문 표현 전체를 보존하고, 명시되지 않은 기한·부수·단계·
  조건은 추측하지 말고 null로 둔다.

## 마지막 확인

- 이 구간에 값이 없는 최상위 항목은 `null`이다. 그럴듯한 값으로 채우지 않는다. 구간에 없는 사실을 다른 구간에 있을 것이라고 추측하지 않는다.
- 참가 가능 여부, PASS/FAIL, 점수 계산, 입찰 권고 같은 판정 문자열을 어떤 필드에도 쓰지 않는다.
- 모든 `quote`는 이 구간 원문에서 그대로 복사했고 200자를 넘지 않는다. `section_id`는 인용이 속한 표지의 S번호다.
