# 회사 위키 API

## 위키 읽기

`deep_review` 모듈이 제공한다. 아래 아홉 경로는 GET이고 요청 시점의 설정된 회사 폴더를 읽는다. 모든 성공 응답은 JSON 객체이며 최상위에 64자리 소문자 hex `bundle_sha256`이 있다. 엔진의 `company_bundle()`과 같은 프로필·곁 YAML·깊이 2 이하 마크다운 원문으로 계산한다. `labels.yaml`·`work-units.json`·`log.txt`만 바뀌면 digest는 그대로다.

| 경로 | 응답 필드와 의미 |
|---|---|
| `/api/company-wiki` | `slug, company_name, counts, work_units_available, labels_available, last_changed, log`. 마지막 변경일은 모든 페이지의 updated와 전체 로그 날짜 중 가장 늦은 날(YYYY-MM-DD)이며 날짜가 없으면 null이다. 로그는 최근 20줄을 역순으로 담으며 파일이 없으면 빈 배열이다. |
| `/api/company-wiki/profile` | `sections: [{key, label, facts: [{path, label, value, display_value, level}]}]`. 이름표가 없는 절·항목의 label은 null이다. 점 경로의 목록 식별자는 item_no, id, name 순으로 고르고 없으면 0부터 센 순번을 쓴다. 스칼라 목록은 쉼표와 공백으로 합친다. 파일 참조 키는 제외한다. 값과 확인 수준은 각각 nullable이다. |
| `/api/company-wiki/portfolio` | `items: [{id, title, client, period_start, period_end, type, role, has_page, requirement_count, ingested, ingested_at, evidence_links}]`. 요구사항 소절이 없으면 건수는 null, 소절이 비었으면 0이다. 지도 파일이 없으면 반영 여부·날짜·연결 수도 null이다. 지도가 있고 미반영인 실적은 false와 null 날짜를 갖는다. |
| `/api/company-wiki/work-units` | `topics: [{id, title, scope, unit_count, units_without_evidence, project_count}]`. 실적 수는 주제 안에서 중복을 제거한 값이다. |
| `/api/company-wiki/work-units/{topic_id}` | `id, title, scope, units`. 각 업무는 `id, title, covers, not, project_count, latest_year, projects, no_record`를 갖는다. 실적은 `{project, title, client, period_start, period_end, year, requirements: [{req_id, name}]}`이며 원문 줄이 없으면 명칭은 null이다. 종료 연도, 시작 연도, 실적 번호 순으로 연도를 정한다. 연도 내림차순, 동률은 실적 번호 내림차순이다. 기록 없음 메모는 `{note, as_of, source}`다. |
| `/api/company-wiki/portfolio/{project}` | 목록 한 건의 필드와 `domain, scope_lines, work_units, requirements`. 범위는 수행한 요구 범위 절의 목록이며 요구사항 소절·관리 문구를 제외한다. 업무는 `{topic_id, topic_title, units: [{id, title}]}`로 묶고 요구사항은 페이지 순서대로 `{req_id, name}`을 담는다. 페이지가 없는 등록 실적도 기본 값은 조회된다. |
| `/api/company-wiki/portfolio/{project}/requirements/{req_id}` | `project, req_id, name, text`. 실적 번호는 `P[0-9]{4}-[0-9]{2}`, 요구사항 번호는 `[A-Za-z0-9][A-Za-z0-9._-]*`다. text는 원문 줄에서 명칭 뒤의 내용을 최대 300자로 담는다. 내용 없이 명칭만 적힌 줄은 빈 문자열이다. |
| `/api/company-wiki/pages` | `pages: [{kind, slug, title, updated, confidence, chars}]`. chars는 공개 본문의 문자 수다. INDEX·SCHEMA는 제외한다. |
| `/api/company-wiki/pages/{kind}/{slug}` | `kind, slug, title, updated, confidence, sources, body`. 본문은 frontmatter를 제외한 마크다운이다. 페이지 주소에는 종류와 영숫자·하이픈 식별자만 쓴다. |

로그 항목은 `{date, kind, text, project, project_title, requirement_count, unassigned_count}`다. `ingest`는 실적 번호·실적명·요구사항 수·미분류 수를 담는다. `feedback`과 `init`은 각각 분석 피드백 반영과 업무 분류표 생성이다. 해석되지 않은 줄은 `other`로 원래 문구를 유지한다. 구조화된 값이 없으면 null이다.

선택 파일 `<slug>/labels.yaml`의 schema는 `bidops.wiki-labels.v1`이다. sections는 절 이름, fields는 항목 이름·단위·값 번역, hidden은 제외할 경로다. 목록 식별자는 `[]`, 한 칸의 키는 `*`로 매칭하며 정확한 경로가 우선이다. `{item}`은 name·std·title·식별자 순으로, `{key}`는 매칭된 키로 치환한다. display_value는 values 번역을 먼저 쓰고 krw·percent·people·count 단위를 적용한다. null, "unknown", 빈 문자열은 보존한다. 이름표가 없거나 깨진 경우 labels_available은 false이고 원래 경로와 값을 쓴다.

`counts.pages_by_kind`에는 category, capability, portfolio, rule, glossary 다섯 키가 항상 있다. `portfolio_items`는 목록 건수, `portfolio_pages`는 실적 페이지 수다. `ingested_projects, work_topics, work_units, evidence_links, units_without_evidence`는 각각 지도에 등록된 실적, 주제, 단위, 근거 연결, 근거 없는 단위 수다. 지도가 없으면 다섯 값은 null이고 빈 지도라면 0이다. 문자열 `"unknown"`은 JSON null과 구분한다.

파일 경로와 실적 목록의 금액은 공개하지 않는다. 절대 경로인 페이지 출처는 배열에서 제외한다. 공개 텍스트에 로컬 절대 경로가 적힌 줄은 `[경로 생략]`으로, 본문·로그에 실적 금액 숫자가 반복된 곳은 `[금액 생략]`으로 표시한다. 심볼릭 링크를 따라가지 않는다.

오류는 `{"error":{"code":"…","message":"…","details":null}}` 형식이다. 내부 예외나 경로를 포함하지 않는다.

| HTTP | code | 조건 |
|---|---|---|
| 404 | `company_wiki_unavailable` | 폴더 또는 회사 slug 미설정 |
| 503 | `company_wiki_unreadable` | 설정한 묶음의 판독 또는 형식 검사 실패 |
| 404 | `company_wiki_work_units_unavailable` | 근거 지도 조회 시 지도 파일 부재 |
| 404 | `company_wiki_page_not_found` | 허용되지 않은 종류·식별자, 부재·링크·범위 밖 페이지 |
| 404 | `company_wiki_topic_not_found` | 요청한 주제 부재 |
| 404 | `company_wiki_project_not_found` | 요청한 실적 미등록 |
| 404 | `company_wiki_requirement_not_found` | 실적·요구사항 식별자 형식 오류 또는 해당 원문 줄 부재 |

## 실적 넣기

기본 경로는 `/api/company-wiki/ingests`다. 모든 POST는 `X-BidOps-Actor-Name`이 필요하다. ASCII 이름은 그대로 보내고, 한글 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 함께 `UTF-8''` 뒤에 UTF-8 퍼센트 인코딩한 값을 보낸다.

|메서드·상대 경로|요청|성공 응답|
|---|---|---|
|POST 기본 경로|헤더 `Idempotency-Key` UUID. multipart/form-data에 `project_id`(예: `P2026-03`), `file`(HWP·HWPX·PDF, 최대 50 MiB)|202 상세. 같은 키·실적·담당자·파일명·내용이면 기존 실행의 현재 상세|
|GET 기본 경로|`limit` 1~100(기본 20), `offset` 0 이상(기본 0)|200 `{items: 요약[], total: 정수}`. 생성 시각과 UUID 내림차순|
|GET `/{id}`|실행 UUID|200 상세|
|POST `/{id}/approve`|JSON `{"expected_status":"awaiting_review"}`|200 상세. `approved` 전이와 반영 job 등록|
|POST `/{id}/reject`|JSON `{"expected_status":"awaiting_review","reason":"반려 사유"}`, 공백 제거 후 1~1000자|200 상세. `rejected`|

**요약 필드**는 `id, request_id, project_id, project_title, status, quality_status, error_code, source_filename, source_size_bytes, source_media_type, requirement_count, created_at, updated_at`이다. MIME은 `application/x-hwp`, `application/hwp+zip`, `application/pdf` 중 하나다. 추출 전 건수와 오류가 없는 실행의 오류 코드는 null이다.

**상세**는 요약에 다음 필드를 추가한다.

|필드|형식·의미|
|---|---|
|`unlisted_id_count`, `unassigned_count`|정수 또는 null. 본문에서 언급됐지만 추출되지 않은 고유 번호 수, 배정 단위가 없는 요구사항 수|
|`units`|배정된 단위별 `{id, title, count}[]`. count는 요구사항 건수|
|`assignments`|원문 추출 순서의 `{req_id, name, unit_titles: string[]}[]`|
|`new_units`, `classification_attempts`|이번 참조 분류의 새 단위는 항상 빈 배열. 시도 횟수는 정수|
|`apply_allowed`|검토 대기이며 참조 반영 스위치가 켜져 있을 때 true|
|`wiki_sha256_before, wiki_sha256_after, backup_name`|문자열 또는 null. 사본 이름은 폴더의 마지막 이름만 반환|
|`created_by_name, decided_by_name, decision_reason, decided_at, applied_at`|생성자는 필수. 나머지는 해당 행동이 일어나기 전 null, 반려 사유는 반려 때만 기록. 시각은 시간대가 있는 ISO 8601|

정상 전이는 `queued → extracting → classifying → awaiting_review → approved → applying → applied`다. 검토 대기에서 사람이 반려하면 `rejected`, 처리 실패는 `failed`, 실행 중 heartbeat 만료는 `aborted`다. 종결 후 다시 넣으면 새 실행이 생긴다. `quality_status`는 모든 상태에서 `mock_reference`다. 참조 분류를 위키에 반영했다는 기록은 운영 활성화·모델 품질 인수 근거가 아니다.

HTTP 오류는 공통 `{"error":{"code":"…","message":"…","details":null}}` 형식이다.

|HTTP|code|
|---|---|
|400|`actor_name_required`, `actor_name_invalid`|
|404|`company_wiki_ingest_disabled`(목록·상세·쓰기 모두), `not_found`, `company_wiki_unavailable`|
|409|`idempotency_conflict`(같은 키에 다른 입력), `ingest_in_progress`(같은 실적에 미종결 실행), `status_conflict`, `reference_apply_disabled`|
|413|`input_size_limit`|
|422|`invalid_request`(키·UUID·본문·페이지 인자 포함), `project_not_registered`, `unsupported_extension`, `mime_mismatch`|
|503|`company_wiki_unreadable`, `storage_unavailable`, `ingest_unavailable`|

worker 실패는 상세 조회의 HTTP 200과 실행의 `error_code`로 구분한다. `project_not_registered`·`portfolio_page_missing`은 대상 실적 확인 실패, `no_requirements`는 추출 0건, `malware_detected`는 차단 및 원본 버전 삭제다. 문서 처리기는 기존 `SAFE_CONVERTER_CODES` 집합의 코드(예: `clamav_unavailable`, `converter_unavailable`, `timeout`, `mime_mismatch`)만 전달한다. 그 밖에 `hash_mismatch`, `engine_process_failed`, `processing_failed`, 위키 판독 코드, `reference_apply_disabled`, `backup_dir_unset`, `unsafe_backup_dir`, `unsafe_wiki_bundle`, `apply_failed`, `lease_expired`가 있다. `apply_failed`는 사본 복구 뒤 기록한다. 복구 자체가 실패하면 `applying` 상태를 유지한다.

## 회사 자료로 생성한 답변 검증

`GET /api/company-wiki/quality`는 설정된 회사 폴더의 선택 파일 `answer-evaluation.json`을 읽는다. 파일이 없으면 `unmeasured`, 평가 당시와 현재의 회사 묶음 또는 업무 지도 버전이 다르면 `stale`이다. 두 상태 모두 `evaluation=null`, `metrics=[]`다. 파일이 손상됐거나 심볼릭 링크이면 503이다. 일치하면 `reviewed`와 질문별 사람 검수 기록을 반환한다. 이 상태는 사람 검수 완료를 뜻한다. 운영 정책 승인에는 사용하지 않는다.

입력 형식은 [평가 스키마](../../web/backend/app/deep_review/schemas/wiki_quality.py)의 `Evaluation`이다. `bundle_sha256`은 기존 위키 해시다. `work_units_sha256`은 UTF-8 텍스트로 읽은 업무 지도의 SHA-256이며 파일이 없으면 null이다. 질문셋·답변 모델·채점 기준 버전과 사람 검토자·검수일을 함께 저장한다. 채점 모델의 판단까지 수록하면 `judge_version`이 필요하다.

### 평가 실행과 검수

1. 질문셋은 실행 전에 고정한다. 한 실적의 수행 범위, 두 실적을 함께 봐야 하는 질문, 비슷한 사업명에 관한 질문, 필수 자격의 증빙이 없는 질문을 포함한다. 현업 검수자가 질문·기준일·기대 답변·답변 가능 여부·필수 근거 묶음을 지정한다. 한 묶음 안에서는 대체 가능한 페이지 하나를 읽으면 된다. 예를 들어 구축만 확인된 표본에서 “유지보수까지 맡았나?”에 대한 기대 답변은 “구축은 확인, 유지보수는 확인 불가”다.
2. 격리된 Wiki Read 도구를 사용하려면 backend 디렉터리에서 기존 회사 묶음 설정으로 `python -m app.deep_review.cli.wiki_evaluation Q1 Q1.trace.json`을 시작한다. 평가 대상 에이전트의 실제 요청을 표준입력에 JSON 한 줄씩 연결한다. `{"tool":"Read","page":"rule/example"}`에는 공개 본문 또는 오류가 한 줄로 반환된다. `{"tool":"finish","answer":"실제 답변"}`에서 완료 기록을 쓴다. 도구는 모델을 실행하지 않는다. 호출 수는 이 세션의 Read 시도 횟수이며 실패·중복을 포함한다. 페이지 목록은 성공한 Read만 순서대로 담는다. 검색 결과나 미리 제공한 파일을 추가하지 않는다.
3. 사람이 답변의 주요 사실 주장을 나누고 위키에서 확인되는지, 각각의 인용 구절이 그 주장을 지지하는지 표시한다. 채점 모델을 쓴 경우 동일 질문의 모델 판정을 따로 보존한다. 실제 호출의 토큰과 소요 시간은 수집된 경우에만 넣는다. 사람 채점 파일은 평가 스키마의 메타데이터와 `cases`를 따르며, `read_pages`, `tool_calls`는 도구가 채운다. `python -m app.deep_review.cli.assemble_wiki_evaluation reviews.json answer-evaluation.json Q1.trace.json`으로 조립한다. 질문 ID·입력 버전·검수한 답변이 다르면 실패한다. 두 CLI 모두 새 파일로 출력한다.
4. 격리된 회사 폴더에 완성된 파일을 두고 회사 화면의 **답변 품질**에서 확인한다. 공개하는 원문과 집계의 대상은 위키 답변 평가에 한정한다. 운영에 반영할 파일은 별도로 확인한다.

지표는 분자와 분모를 반환한다. 인용 정확도는 사람이 연결을 인정하고 해당 페이지 본문에 인용 구절이 실제로 있는 인용 쌍의 비율이다. 주장별 인용 여부는 그 조건을 충족한 인용이 하나 이상인 주장을 센다. 근거 없는 단정의 분모는 검수자가 식별한 사실 주장이다. 보류율은 답변 가능·불가능 질문을 각각 분모로 삼는다. Recall은 충족된 필수 근거 묶음 수, Precision은 질문별 관련 고유 페이지 수를 각 분모에 합산한다. 완전한 읽기 기록이 없는 질문은 두 지표에서 제외한다. 빈 읽기 기록은 필요한 근거를 하나도 읽지 않은 것으로 처리한다. 분모 0은 계산 대상 없음이다. 토큰 미수집과 실제 0은 별도로 표시한다.

### 루트랩 첫 검수용 질문 초안

2026-11-24 로컬 자료 기준이다. 아래 기대값은 사람이 검수할 초안이다. 평가 결과 파일에는 넣지 않았다. 당시 회사 묶음은 `3cfc7155705038635bd57a148d9e1a894dfa649add7e164787e6ba2fa1b3c70e`, 업무 지도는 `8acc7867ed6a85a9da1739bd2351b7a1327e6547bc6a75a3f9aa7f04d02bec2c`다.

| 질문 | 기대 답변과 검수할 점 | 확인할 페이지 |
|---|---|---|
| 대구연구장비정보시스템 고도화 구축 용역의 발주기관은 어디인가? | 재단법인 대구테크노파크. 사업명과 발주기관이 같은 실적에 기재됐는지 확인한다. | portfolio/P2020-01 |
| 대구연구장비 사업과 NIA 제안서 접수 시스템은 같은 발주기관인가? | 다르다. 각 실적의 발주기관을 인용한다. NIA는 등록 명칭과 RFP 당시 표기를 구별한다. | portfolio/P2020-01, portfolio/P2021-01 |
| NIA 제안서 접수 시스템 RFP에 적힌 발주기관 명칭은 무엇인가? | 위키가 기록한 RFP 당시 표기는 한국정보화진흥원이다. 현재 등록 명칭만 인용한 답변은 질문을 충족하지 못한다. | portfolio/P2021-01 |
| P2020-01 실적의 과업기간 문구만으로 실제 준공일을 특정할 수 있는가? | 해당 문구로 확인할 수 있는 것은 계약일부터 5개월 이내라는 조건이다. 실제 준공일을 제시하면 그 날짜를 명시한 별도 근거가 필요하다. | portfolio/P2020-01 |

인용의 `reported_location`은 모델이 답한 출처 표기 원문이다. 명시적인 페이지를 식별할 수 없으면 `page=null`로 보존하고 인용 분모에는 포함하며 지지 판정은 false다.

파일 열람 방식으로 답변을 생성할 때는 backend의 `python -m app.deep_review.cli.wiki_answer_prompt '질문' portfolio/P2020-01`이 만든 지침을 사용한다. 답변에는 페이지 경로와 절 제목을 함께 적는다. 새 채점표는 `citation_format=page_and_section`으로 기록하고 인용마다 `page`, `section`, `quote`를 보존한다. 검증기는 해당 절 안의 원문을 대조한다. 첫 제목 앞의 본문은 section=null로 대조한다. 이 필드가 없는 이전 채점표는 당시 페이지 단위 기준으로 읽는다. 근거 없는 단정의 목표 건수는 0이며 분모가 없으면 측정 결과는 계산 대상 없음이다.
