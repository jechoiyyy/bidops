# 회사 근거 화면을 실무자가 읽는 말로 — 3단계 명세

2026-11-23. 사용자 결정: 회사 근거 화면이 위키 파일의 식별자(`P2024-03 SER-002`, `company.biz_no`, digest)를 그대로 보여 주지 않고 실무자가 바로 읽을 수 있는 말로 보여 준다. 식별자는 지우지 않고 펼친 영역이나 기술 정보에 작게 남긴다(위키 파일과 대조할 수 있어야 한다).

결정된 방향:

- 근거 실적: **요약 먼저 + 사업별로 묶기 + 요구사항 원문 펼치기**.
- 프로필 항목의 이름은 **위키 쪽 이름표 파일**(`<slug>/labels.yaml`)이 정한다. 이름표에 없는 항목은 키를 그대로 보인다.
- 실적 본문은 **화면에서만 정리**한다. 위키 페이지 원문은 고치지 않는다(분석 에이전트가 같은 페이지를 읽는다).

1·2단계 코드(`web/backend/app/deep_review/{services,routers,schemas}/company_wiki*.py`, `web/frontend/src/pages/CompanyWikiPage.tsx`, `src/components/company-wiki/*`, `src/lib/companyWiki*.ts`)를 고친다. 넣기 흐름의 동작은 바꾸지 않는다.

## 이름표 파일 `labels.yaml`

위키 루트(`<묶음 폴더>/<slug>/labels.yaml`)에 있다. `.md`가 아니므로 엔진 묶음과 digest에 들어가지 않는다. 실제 파일의 예는 `/Users/temp/orca/bidops/wiki/rootlab/labels.yaml`이다(읽기만 한다. 테스트 fixture로 복사하지 않고 같은 형식의 작은 예를 만든다).

```yaml
schema: bidops.wiki-labels.v1
sections: {company: 회사, registrations: 등록·인증}
hidden: [schema_version, "registrations.direct_production[].name"]
fields:
  company.capital_krw: {label: 자본금, unit: krw}
  company.revenue_krw.*: {label: "매출액 ({key}년)", unit: krw}
  registrations.direct_production[].status: {label: "직접생산확인 · {item}", values: {valid: 유효, expired: 만료}}
  people.onsite_capacity.*.ok: {label: "{key} 상주", values: {"true": 가능, "false": 불가}}
```

- 경로 표기: 프로필 항목 경로에서 목록 항목의 식별자를 `[]`로, 임의의 키 한 칸을 `*`로 쓴다. 정확히 일치하는 경로가 `*` 경로보다 먼저다.
- `{item}`: 그 목록 항목의 이름. 같은 항목의 `name`·`std`·`title` 값 순으로 있는 것을 쓰고, 없으면 경로의 식별자를 쓴다. `{key}`: `*` 자리의 키.
- `unit`: `krw`(원) · `percent` · `people`(명) · `count`. `values`: 원래 값(문자열로 비교) → 화면에 쓸 말.
- `hidden`: 화면에 내지 않는 항목(다른 항목의 이름으로 쓰이는 것 등).
- 파일이 없거나 형식이 깨져도 조회는 실패하지 않는다. 이름표 없이(키 그대로) 보여 주고 요약 응답의 `labels_available`을 false로 한다.

## 백엔드

### 프로필 `GET /api/company-wiki/profile`

- `sections: [{key, label, facts: [...]}]`로 바꾼다. `label`은 이름표의 `sections`, 없으면 `null`.
- 각 fact: `path`(지금과 같음), `label`(이름표 적용 결과, 없으면 `null`), `value`(원래 값, 지금과 같음), `display_value`(화면용 문자열), `level`.
- `display_value` 규칙(백엔드가 만든다. 화면이 다시 계산하지 않는다):
  - `values`에 있으면 그 말.
  - `unit: krw`는 억·만 단위로 읽기 쉽게: `500000000` → `5억 원`, `3769270000` → `37억 6,927만 원`, `30000000` → `3,000만 원`. `percent` → `15%`. `people` → `35명`. `count` → `9건`.
  - `"unknown"`과 `null`은 바꾸지 않는다(화면이 "미확인"·"값 없음"으로 구분해 적는다). 빈 목록은 `null`이 아니라 빈 문자열이면 그대로 둔다.
  - 그 밖은 `value`와 같다.
- `hidden` 항목은 응답에서 뺀다.

### 요약 `GET /api/company-wiki`

- `last_changed`(YYYY-MM-DD, null 가능)를 더한다: 페이지 frontmatter의 `updated`와 `log.txt` 날짜 중 가장 늦은 날.
- `labels_available`(bool)을 더한다.
- `log`를 구조화한다: `[{date, kind, text, project, project_title, requirement_count, unassigned_count}]`. `kind`는 `ingest`·`feedback`·`init`·`other`. `ingest | P2025-08 | 요구사항 70건, 미분류 10건` 같은 알려진 줄 형식에서 값을 뽑고, 모르는 형식은 `kind: other`와 원문 `text`만 준다. `project_title`은 실적 목록에서 찾는다.

### 업무별 근거

응답이 커지므로 둘로 나눈다.

- `GET /api/company-wiki/work-units` — 주제 목록만: `topics: [{id, title, scope, unit_count, units_without_evidence, project_count}]`. `project_count`는 그 주제에 근거가 있는 서로 다른 실적 수.
- `GET /api/company-wiki/work-units/{topic_id}` — 주제 하나의 상세:
  - `units: [{id, title, covers, not, project_count, latest_year, projects: [...], no_record: [...]}]`
  - `projects` 항목: `{project, title, client, period_start, period_end, year, requirements: [{req_id, name}]}`. 최근 순으로 정렬한다(`year` 내림차순, 같으면 실적 번호 내림차순). `year`는 사업 종료 연도, 없으면 시작 연도, 둘 다 없으면 실적 번호의 연도.
  - `requirements[].name`은 실적 페이지의 `요구사항 전체 목록(원문)` 줄에서 번호 다음의 명칭이다(줄 형식 `- <번호> <명칭> — <내용>`). 그 줄이 없으면 `null`.
  - 없는 주제는 404 `company_wiki_topic_not_found`.

### 요구사항 원문

- `GET /api/company-wiki/portfolio/{project}/requirements/{req_id}` → `{project, req_id, name, text}`. `text`는 실적 페이지 목록 줄의 내용 부분(최대 300자, 위키에 적힌 그대로). 실적이나 번호가 없으면 404 `company_wiki_requirement_not_found`. `project`는 `P\d{4}-\d{2}`, `req_id`는 `[A-Za-z0-9][A-Za-z0-9._-]*`만 받는다.

### 실적 상세

- `GET /api/company-wiki/portfolio/{project}` → 화면용으로 정리한 실적 한 건:
  - 목록 항목과 같은 기본 값(`id, title, client, period_start, period_end, type, role, has_page, requirement_count, ingested, ingested_at`)과 `domain`(있으면).
  - `scope_lines`: 실적 페이지 `## 수행한 요구 범위` 절의 `- ` 줄(요구사항 전체 목록 소절은 제외). 관리용 문구가 든 줄은 뺀다: 백틱(`` ` ``)이 든 줄, `YAML`·`라벨`·`past.yaml`이 든 줄.
  - `work_units`: 이 실적이 근거인 업무를 주제별로 `[{topic_id, topic_title, units: [{id, title}]}]`.
  - `requirements`: `[{req_id, name}]`(목록 줄 순서).
  - 금액은 싣지 않는다. 없는 실적은 404 `company_wiki_project_not_found`.
- 위키 원문 그대로는 기존 `GET /api/company-wiki/pages/portfolio/{slug}`가 계속 준다.

### 테스트와 문서

- `tests/deep_review/test_company_wiki.py`에 더한다: 이름표 적용(정확 일치가 `*`보다 먼저, `{item}`·`{key}`, `hidden`, `unit` 네 가지와 `krw` 표기 예 세 개, `values`), 이름표 없음·깨짐에서 200과 `labels_available: false`, `last_changed`, 구조화된 `log`(알려진 형식과 모르는 형식), 주제 목록·상세의 값과 정렬, 요구사항 원문, 실적 상세의 `scope_lines` 거르기와 `work_units`, 새 404 코드들, 금액·경로 비노출.
- `docs/contracts/company-wiki.md`를 새 모양으로 고친다.
- 넣기 테스트(`test_company_wiki_ingests.py`)와 경계 검사는 그대로 통과해야 한다.

## 프런트엔드

문구는 해요체, 숫자는 받은 값으로만. 번호(`P2024-03`, `SER-002`)와 경로(`company.biz_no`), digest는 본문 글에 크게 쓰지 않는다.

### 개요

- 맨 위: 회사명, "마지막으로 바뀐 날 · {last_changed}"(없으면 줄을 그리지 않는다). 건수 요약은 실무 용어로: "수행 실적 {portfolio_items}건", "요구사항까지 정리된 실적 {ingested_projects}건", "업무 {work_units}가지", "근거 연결 {evidence_links}건". "페이지 수"류는 기술 정보로 옮긴다.
- 프로필 값: `sections`의 `label`(없으면 key)로 묶고, 항목은 `label`(없으면 `path`), 값은 `display_value`(`"unknown"`은 "미확인", `null`은 "값 없음"), 확인 수준.
- 확인 수준 설명을 표 위에 한 번 적는다: "확인됨 · 담당자가 확인한 값", "공개 자료 · 홈페이지 등 공개된 자료에서 옮긴 값", "데모값 · 시연을 위해 임의로 넣은 값", "추정 · 다른 자료에서 추정한 값", "표시 없음 · 확인 수준이 기록되지 않은 값".
- 맨 아래 접힌 "기술 정보": 묶음 판(digest 앞 12자), 위키 식별 이름(slug), 종류별 페이지 수, 이름표 사용 여부. 기본은 닫힘. Astryx `Collapsible`은 쓰지 않는다(기존 화면의 접기 방식과 같게).

### 실적

- 목록 항목: 사업명이 첫 줄, 다음 줄에 "발주처 · 기간", 그다음 "요구사항 {n}건 정리됨" / "요구사항 목록 없음" / "상세 페이지 없음". 실적 번호는 작은 글씨로 끝에.
- 상세(새 실적 상세 API): 사업명, 발주처·기간·유형·역할(값이 `"unknown"`이면 "미확인", `null`이면 그 줄을 빼지 않고 "값 없음"), "수행한 범위"(`scope_lines`), "이 사업에서 수행한 업무"(`work_units`를 주제별로, 업무 이름은 업무별 근거 보기의 그 주제로 가는 링크), "요구사항"(명칭 목록, 누르면 원문이 펼쳐진다 — 아래 "원문 펼치기"). 맨 아래 접힌 "위키 원문 보기"가 기존 페이지 본문을 그대로 보여 준다.
- "실적 넣기" 단추와 넣기 흐름은 그대로다.

### 업무별 근거

- 주제 목록(새 목록 API): 주제명, "업무 {unit_count}가지 · 실적 {project_count}건"과 근거 없는 업무가 있으면 "근거 없는 업무 {n}가지". 모두 근거가 있으면 그 말은 쓰지 않는다.
- 주제 상세(새 상세 API). 업무 단위마다:
  - 업무명과 범위.
  - 요약 한 줄: "{project_count}개 사업에서 수행 · 최근 {latest_year}년". 근거가 없으면 "수행 기록 없음".
  - 사업별 묶음: 한 줄에 "사업명 · 발주처 · 연도", 그 아래 요구사항 명칭들. 최근 3개 사업만 먼저 보이고 "나머지 {n}개 사업 보기"로 펼친다. 명칭이 `null`이면 번호를 대신 보인다.
  - 사업명은 실적 보기의 그 실적으로 가는 링크.
  - 기록 없음 확인 메모가 있으면 날짜와 함께.
- **원문 펼치기:** 요구사항 명칭은 단추다. 누르면 그 아래에 원문(`text`)과 작은 글씨의 식별자("실적 P2024-03 · 요구사항 SER-002")가 펼쳐진다. 원문은 눌렀을 때 요구사항 원문 API로 받아 오고(받는 동안·실패·없음 상태를 그 자리에서 적는다), 다시 누르면 접힌다. 키보드로 조작할 수 있고 `aria-expanded`를 단다.

### 규칙·페이지, 변경 이력, 넣기 기록

- 규칙·페이지: 목록에서 slug 대신 제목을 보이고(이미 그렇다면 유지), `work-`로 시작하는 페이지는 계속 뺀다.
- 변경 이력: `kind`별 문장. `ingest` → "{project_title} 실적을 넣었어요 · 요구사항 {requirement_count}건"(미분류가 0보다 크면 " · 분류되지 않은 요구사항 {n}건"), `feedback` → "분석에서 확인한 내용을 반영했어요", `init` → "업무 분류표를 만들었어요", `other` → 원문 `text` 그대로. `project_title`이 없으면 실적 번호를 쓴다.
- 넣기 기록: 파일 크기는 KB/MB로(1,024 단위, 소수 한 자리까지), 형식은 "한글(HWP) 문서"·"한글(HWPX) 문서"·"PDF 문서"로(모르는 형식은 원래 값). 목록의 "요구사항 수 70" → "요구사항 70건".

### 테스트

- `tests/company-wiki.spec.ts`·`tests/company-wiki-ingest.spec.ts`·`tests/fixtures/company-wiki.ts`를 새 응답 모양에 맞게 고치고 검사를 더한다: 이름표가 있는 항목과 없는 항목, 미확인·값 없음 구분 유지, 확인 수준 설명, 기술 정보 접힘, 주제 상세의 요약 문장·최근 3개·나머지 펼치기, 원문 펼치기(받는 중·성공·404), 실적 상세의 세 묶음과 위키 원문 접힘, 변경 이력의 네 종류 문장, 파일 크기·형식 표기, 화면 본문에 digest가 기본으로 보이지 않는 것.
- `npm run build` 통과. Playwright는 이 환경에서 띄울 수 없으므로 검사는 작성만 하고 밖에서 돌린다.

## 하지 않는 것

- 위키 페이지 원문, 분석 지시문, 넣기 동작의 변경.
- 새 의존성, DB 변경, 새 환경 변수.
- `Sidebar.tsx`, `src/pages/CompanyPage.tsx` 수정.

## 검증 명령

```bash
cd web/backend && /Users/temp/orca/bidops/.venv/bin/python -m pytest tests/deep_review/test_company_wiki.py tests/deep_review/test_company_wiki_ingests.py tests/app/test_module_boundaries.py tests/app/test_module_selection.py -q
cd web/frontend && npm run build
```
`tests/app/test_module_boundaries.py::test_routers_do_not_touch_the_orm_directly`는 이 작업 전부터 `app/lifecycle/routers/opportunities.py` 때문에 실패한다. 그 파일은 고치지 않는다.
