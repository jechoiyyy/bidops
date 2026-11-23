# 회사 위키 API

## 위키 읽기

`deep_review` 모듈이 제공한다. 아래 여섯 경로는 GET이고 요청 시점의 설정된 회사 폴더를 읽는다. 모든 성공 응답은 JSON 객체이며 최상위에 64자리 소문자 hex `bundle_sha256`이 있다. 엔진의 `company_bundle()`과 같은 프로필·곁 YAML·깊이 2 이하 마크다운 원문으로 계산한다. `work-units.json`과 `log.txt`만 바뀌면 digest는 그대로다.

| 경로 | 응답 필드와 의미 |
|---|---|
| `/api/company-wiki` | `slug, company_name, counts, work_units_available, log`. 로그는 최근 20줄을 역순으로 담은 `{date, text}[]`이며 파일이 없으면 빈 배열이다. |
| `/api/company-wiki/profile` | `facts: [{path, section, value, level}]`. 점 경로의 목록 식별자는 item_no, id, name 순으로 고르고 없으면 0부터 센 순번을 쓴다. 스칼라 목록은 쉼표와 공백으로 합친다. 파일 참조 키는 제외한다. 값과 확인 수준은 각각 nullable이다. |
| `/api/company-wiki/portfolio` | `items: [{id, title, client, period_start, period_end, type, role, has_page, requirement_count, ingested, ingested_at, evidence_links}]`. 요구사항 소절이 없으면 건수는 null, 소절이 비었으면 0이다. 지도 파일이 없으면 반영 여부·날짜·연결 수도 null이다. 지도가 있고 미반영인 실적은 false와 null 날짜를 갖는다. |
| `/api/company-wiki/work-units` | `topics: [{id, title, scope, units}]`. 단위는 `{id, title, covers, not, projects, no_record}`이고, 실적별 근거는 `{project, req_ids: string[]}`, 확인 메모는 `{note, as_of, source}`다. 근거와 메모는 각각 빈 배열일 수 있다. |
| `/api/company-wiki/pages` | `pages: [{kind, slug, title, updated, confidence, chars}]`. chars는 공개 본문의 문자 수다. INDEX·SCHEMA는 제외한다. |
| `/api/company-wiki/pages/{kind}/{slug}` | `kind, slug, title, updated, confidence, sources, body`. 본문은 frontmatter를 제외한 마크다운이다. 페이지 주소에는 종류와 영숫자·하이픈 식별자만 쓴다. |

`counts.pages_by_kind`에는 category, capability, portfolio, rule, glossary 다섯 키가 항상 있다. `portfolio_items`는 목록 건수, `portfolio_pages`는 실적 페이지 수다. `ingested_projects, work_topics, work_units, evidence_links, units_without_evidence`는 각각 지도에 등록된 실적, 주제, 단위, 근거 연결, 근거 없는 단위 수다. 지도가 없으면 다섯 값은 null이고 빈 지도라면 0이다. 문자열 `"unknown"`은 JSON null과 구분한다.

파일 경로와 실적 목록의 금액은 공개하지 않는다. 절대 경로인 페이지 출처는 배열에서 제외한다. 공개 텍스트에 로컬 절대 경로가 적힌 줄은 `[경로 생략]`으로, 본문·로그에 실적 금액 숫자가 반복된 곳은 `[금액 생략]`으로 표시한다. 심볼릭 링크를 따라가지 않는다.

오류는 `{"error":{"code":"…","message":"…","details":null}}` 형식이다. 내부 예외나 경로를 포함하지 않는다.

| HTTP | code | 조건 |
|---|---|---|
| 404 | `company_wiki_unavailable` | 폴더 또는 회사 slug 미설정 |
| 503 | `company_wiki_unreadable` | 설정한 묶음의 판독 또는 형식 검사 실패 |
| 404 | `company_wiki_work_units_unavailable` | 근거 지도 조회 시 지도 파일 부재 |
| 404 | `company_wiki_page_not_found` | 허용되지 않은 종류·식별자, 부재·링크·범위 밖 페이지 |

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
