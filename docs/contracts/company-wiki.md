# 회사 위키 읽기 API

`deep_review` 모듈이 제공한다. 모든 경로는 GET이고 요청 시점의 설정된 회사 폴더를 읽는다. 모든 성공 응답은 JSON 객체이며 최상위에 64자리 소문자 hex `bundle_sha256`이 있다. 엔진의 `company_bundle()`과 같은 프로필·곁 YAML·깊이 2 이하 마크다운 원문으로 계산한다. `work-units.json`과 `log.txt`만 바뀌면 digest는 그대로다.

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
