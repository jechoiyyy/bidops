# 회사 근거 화면을 회사 위키 화면으로 — 1단계 명세 (읽기 전용)

2026-11-23. 사용자 결정: 회사 근거 화면(`/company`)은 회사 위키를 보여 주고 같은 화면에서 실적 넣기를 한다. 이 문서는 그 1단계(읽기)의 명세다. 넣기는 2단계 문서가 따로 다룬다.

구현은 이 복제본(`bidops-wiki-ingest`, 브랜치 `wiki-ingest`)에서 한다. 운영 작업 폴더(`/Users/temp/orca/bidops`)의 파일은 읽기만 하고 고치지 않는다.

## 배경

- 회사 위키의 정본은 BidOps 작업 폴더의 `wiki/`다(Git 밖). 배치: `wiki/<slug>.yaml`(프로필), `<slug>.portfolio.yaml`(실적 목록), `<slug>.provenance.yaml`(값별 확인 수준), `wiki/<slug>/`(위키: `INDEX.md`, `SCHEMA.md`, `glossary.md`, `categories/`, `capabilities/`, `portfolio/`, `rules/`, 곁 파일 `work-units.json`, `log.txt`).
- 백엔드는 이 폴더를 `BIDOPS_ENGINE_COMPANY_BUNDLE_DIR`·`BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG`(`app/core/config.py`의 `engine_company_bundle_dir`·`engine_company_bundle_slug`)로 안다. `app/deep_review/services/engine_runs.py`의 `company_bundle()`이 같은 폴더를 읽는 기존 코드다(읽는 규칙·digest 계산의 기준).
- 위키의 정리 계층은 `work-units.json`이다(스키마 `bidops.wiki-work-units.v1`, 생성·검증 코드는 `packages/bid-deep-engine/src/bid_deep_engine/wiki_tools.py`). 웹 프로세스는 엔진 패키지를 import하지 않는다. 이 파일은 JSON으로 직접 읽는다.
- 지금 `/company`는 DB의 회사 사실 그래프를 보여 준다(`web/frontend/src/pages/CompanyPage.tsx`, `GET /api/company`). 1단계에서 `/company`가 여는 화면을 새 위키 화면으로 바꾼다. 기존 `CompanyPage.tsx`와 그 API·컴포넌트는 **고치지도 지우지도 않는다**(다른 세션이 수정 중이다). 라우트에서만 떼어 낸다.

## 백엔드

소유 모듈은 `deep_review`다. 새 파일: `app/deep_review/services/company_wiki.py`, `routers/company_wiki.py`, `schemas/company_wiki.py`. 모듈 공개 이름 표(`app/deep_review/__init__.py`의 `_EXPORTS`)와 `app/main.py`의 router 표에 `company_wiki_router`를 등록한다. router는 ORM을 쓰지 않는다(DB 조회가 없다).

### 공통 규칙

- 모두 `GET`이고 파일을 읽기만 한다. 요청마다 폴더를 다시 읽는다(캐시 없음).
- 폴더나 slug가 설정되지 않았으면 404 `company_wiki_unavailable`. 설정됐는데 읽을 수 없거나 형식이 깨졌으면 503 `company_wiki_unreadable`. 오류 본문은 기존 형식(`{"error": {"code", "message", "details": null}}`)이고 내부 경로·예외 문자열을 넣지 않는다.
- 읽는 대상은 `company_bundle()`과 같은 규칙으로 고른다: 심볼릭 링크는 읽지 않는다, 위키는 깊이 2 이하의 `.md`만, slug는 기존 정규식.
- 모든 응답에 `bundle_sha256`을 싣는다. 값은 `company_bundle()`이 계산하는 digest와 같아야 한다(같은 함수를 재사용하거나 공통 함수로 뺀다). 화면이 "엔진이 쓰는 자료와 같은 판"임을 보일 수 있게 하려는 것이다.
- 실적 목록의 금액(`amount_krw`)은 어떤 응답에도 넣지 않는다.
- 응답 schema에 파일 시스템 경로를 넣지 않는다. 페이지는 `kind`와 `slug`로만 가리킨다.

### 엔드포인트

1. `GET /api/company-wiki` — 요약
   - `slug`, `company_name`(프로필 `company.name`), `bundle_sha256`
   - `counts`: `pages_by_kind`(category/capability/portfolio/rule/glossary별 페이지 수), `portfolio_items`(실적 목록 건수), `portfolio_pages`, `ingested_projects`(`work-units.json`의 `sources` 건수), `work_topics`, `work_units`, `evidence_links`, `units_without_evidence`
   - `work_units_available`: `work-units.json`이 있으면 true. 없으면 false이고 관련 count는 `null`(0으로 적지 않는다).
   - `log`: `log.txt`의 최근 20줄을 최신순으로 `[{date, text}]`(줄 형식 `YYYY-MM-DD | 내용`). 파일이 없으면 빈 배열.
2. `GET /api/company-wiki/profile` — 프로필 값
   - 프로필 YAML의 말단 값을 평평하게 편 목록 `facts: [{path, section, value, level}]`.
   - `path`: 점 경로. 목록 항목은 `registrations.direct_production[8111181101].status`처럼 식별자(`item_no`·`id`·`name` 순으로 있는 것)를, 없으면 순번을 쓴다. provenance 파일의 키 표기와 같게 한다.
   - `section`: 최상위 키(`company`, `registrations`, `people`, `capabilities`, `policy` 등).
   - `value`: 문자열로 바꾼 값. 스칼라 목록은 한 값으로 합친다(`", "`). YAML의 `unknown`·`null`은 그대로 구분해 `"unknown"`과 JSON `null`로 준다.
   - `level`: provenance 파일 `fields[path].level`(`confirmed`·`demo`·`public`·`estimate` 등). 항목이 없으면 `null`.
   - `portfolio_file`·`provenance_file` 같은 파일 가리킴 키는 뺀다.
3. `GET /api/company-wiki/portfolio` — 실적 목록
   - `items: [{id, title, client, period_start, period_end, type, role, has_page, requirement_count, ingested, ingested_at, evidence_links}]`
   - `requirement_count`: 그 실적 페이지의 `### 요구사항 전체 목록(원문)` 소절에 있는 `- ` 줄 수. 소절이 없으면 `null`.
   - `ingested`·`ingested_at`: `work-units.json`의 `sources[id]`. `evidence_links`: 그 실적의 근거 연결 수.
   - 값이 `unknown`이면 문자열 `"unknown"`으로, 키가 없으면 `null`로 준다.
4. `GET /api/company-wiki/work-units` — 업무별 근거 지도
   - `topics: [{id, title, scope, units: [{id, title, covers, not, projects: [{project, req_ids: [...]}], no_record: [{note, as_of, source}]}]}]`
   - `work-units.json`이 없으면 404 `company_wiki_work_units_unavailable`.
5. `GET /api/company-wiki/pages` — 페이지 목록
   - `pages: [{kind, slug, title, updated, confidence, chars}]`. frontmatter에서 읽는다. `INDEX.md`·`SCHEMA.md`는 페이지가 아니다(목록에 없다).
6. `GET /api/company-wiki/pages/{kind}/{slug}` — 페이지 본문
   - `{kind, slug, title, updated, confidence, sources: [...], body}`. `body`는 frontmatter를 뺀 마크다운 원문이다.
   - `kind`는 다섯 값만, `slug`는 `[A-Za-z0-9][A-Za-z0-9-]*`만 받는다. 그 밖은 404 `company_wiki_page_not_found`. 경로를 조립한 뒤 위키 루트 안의 일반 파일인지 다시 확인한다(경로 이탈·심볼릭 링크 거부).
   - `sources` 항목 중 절대 경로로 시작하는 것(`/Users/…`)은 응답에서 뺀다.

### 테스트 (`tests/deep_review/test_company_wiki.py`)

임시 폴더에 작은 위키를 만들어 검사한다. 실제 회사 자료를 fixture로 넣지 않는다.

- 정상: 여섯 엔드포인트의 값(요약 count, 프로필 평탄화와 level, 실적의 `requirement_count`·`ingested`, 근거 지도, 페이지 목록·본문).
- `bundle_sha256`이 `company_bundle()`의 digest와 같다.
- 미설정 404, 깨진 YAML·깨진 `work-units.json` 503, `work-units.json` 없음(요약은 200에 `null` count, 지도는 404).
- 페이지 경로: 허용 밖 `kind`, `..`가 든 slug, 심볼릭 링크 페이지, 깊이 3 파일 → 404.
- 금액이 어느 응답에도 없다. 응답에 절대 경로가 없다.
- `tests/app/test_module_boundaries.py`와 `tests/app/test_module_selection.py`가 통과한다(새 router 등록 포함).

### 문서

- `docs/contracts/company-wiki.md`를 새로 쓰고 `docs/contracts.md` 색인에 넣는다(엔드포인트, 오류 코드, 금액·경로 비노출, digest).
- `web/backend/AGENTS.md` "경계"의 회사 프로필 문장 뒤에 한 줄을 더한다: 회사 위키 조회(`/api/company-wiki`)는 사람이 읽도록 쓴 위키 페이지의 본문과 프로필 값을 묶음 digest와 함께 돌려주는 별도 계약이며, 파일 경로·금액·예외 문자열은 싣지 않는다.

## 프런트엔드

### 라우트

- `web/frontend/src/routes.tsx`에서 `/company`의 element만 새 `CompanyWikiPage`로 바꾼다. 사이드바(`Sidebar.tsx`)와 `CompanyPage.tsx`는 고치지 않는다.
- 새 파일: `src/pages/CompanyWikiPage.tsx`, `src/lib/companyWikiApi.ts`(typed client·query key), `src/components/company-wiki/*`, `src/styles/company-wiki.css`.
- route metadata는 기존 `/company` 것을 쓰되 필요하면 `components/shell/route-meta.ts`에 최소로 더한다.

### 화면

셸 규칙을 따른다(`web/frontend/AGENTS.md` "UI 패턴"): 제목은 `usePageHeader`로 문자열만 올리고, 보기 탭은 `PageHeaderTabs`, 페이지에 `<h1>`을 두지 않는다. 문구는 해요체. 색은 테마 토큰만. 패널 안에 그림자 카드를 두지 않는다.

- 화면 이름 "회사 근거". 제목 문장은 받은 값으로만 만든다. 예: 근거 지도가 있으면 "실적 {portfolio_items}건 가운데 {ingested_projects}건이 업무별 근거 지도에 들어 있어요", 없으면 "실적 {portfolio_items}건이 등록돼 있어요". 값을 못 받았으면 숫자 없는 문장.
- 보기 탭 5개, 주소와 동기화(`?view=overview|portfolio|work-units|pages|log`, 기본 `overview`). 선택 항목도 주소에 둔다(`project=P2025-01`, `topic=<id>`, `page=<kind>/<slug>`).

1. **개요**: 묶음 판 표시(digest 앞 12자), 건수 요약(글자와 숫자, 표식 아님), 프로필 값 표. 표는 `section`별로 묶고 열은 항목(`path`), 값, 확인 수준이다. 확인 수준 문구: `confirmed` 확인됨, `demo` 데모값, `public` 공개 자료, `estimate` 추정, `null` 표시 없음. 값 `"unknown"`은 "미확인", `null`은 "값 없음"으로 서로 다르게 적는다. 색만으로 구분하지 않는다.
2. **실적**: 목록(실적 번호, 사업명, 발주처, 기간, 근거 지도 반영)과 선택한 실적의 페이지 본문. 반영 열 문구: `ingested`면 "넣음 · 요구사항 {requirement_count}건", 페이지는 있는데 요구사항 목록이 없으면 "요구사항 목록 없음", 페이지가 없으면 "페이지 없음". 목록|상세 배치는 기존 목록·상세 화면의 관례(목록 38%)를 따른다.
3. **업무별 근거**: 주제 목록(주제명, 단위 수, 근거 없는 단위 수)과 선택한 주제의 업무 단위들. 단위마다 범위, 근거 실적(실적 번호와 요구사항 번호들, 실적 번호는 실적 보기로 가는 링크), "기록 없음"(근거가 하나도 없을 때)과 기록 없음 확인 메모.
4. **규칙·페이지**: `rule` → `capability` → `category` → `glossary` 순으로 묶은 페이지 목록과 선택한 페이지 본문. `capability` 중 slug가 `work-`로 시작하는 것은 여기서 빼고 3번에서만 보인다.
5. **변경 이력**: `log`를 날짜와 내용으로.

- 마크다운 본문은 새 의존성을 추가하지 않고 표시한다. 제목(`##`, `###`), 목록(`- `), 문단, `[[slug]]` 링크(해당 페이지나 실적으로 이동)만 구분해 그리는 작은 렌더러를 `components/company-wiki/` 안에 둔다. HTML을 그대로 주입하지 않는다(`dangerouslySetInnerHTML` 금지).
- 상태: 로딩, 404 `company_wiki_unavailable`("회사 위키가 아직 연결되지 않았어요"와 무엇을 설정해야 하는지), 503, 근거 지도 없음(3번 탭에 "업무별 근거 지도가 아직 없어요"), 빈 목록, 긴 한글 제목.
- 넣기 버튼이나 입력은 1단계에 두지 않는다.

### 테스트

- `web/frontend/tests/company-wiki.spec.ts`: 가짜 API(`tests/api-mock.ts`의 방식)로 다섯 보기, 주소 동기화, 미확인/값 없음/표시 없음 구분, 근거 없는 단위 표시, 404·503 상태, `[[slug]]` 이동을 검사한다. 가짜 응답은 위 백엔드 schema와 같은 모양이어야 한다.
- 기존 `tests/company-ground-truth.spec.ts`는 옛 `/company` 화면의 검사다. 화면이 라우트에서 내려가므로 이 파일의 검사 중 `/company` 주소에 의존하는 것은 지우고, 지운 이유를 파일 머리 주석이나 커밋 메시지에 적는다. 다른 spec이 `/company`의 옛 내용에 의존하면 같은 방식으로 정리한다. 사이드바의 "회사 근거" 항목과 건수 검사는 그대로 통과해야 한다.
- `npm run build`와 `npm run test:screens`가 통과해야 한다.

### 문서

- `web/frontend/AGENTS.md` "데이터 경계"의 프로필 화면 문장 뒤에 한 줄을 더한다: 회사 근거 화면은 `/api/company-wiki`가 주는 위키 페이지 본문과 프로필 값을 그대로 보여 주며, 마크다운을 HTML로 주입하지 않는다.

## 하지 않는 것

- 넣기, 되돌려 쓰기, 위키 수정(2단계).
- DB 변경, migration, 새 환경 변수, Compose 변경.
- 기존 `GET /api/company`·회사 사실 그래프 코드의 수정이나 삭제.
- 새 npm·Python 의존성.

## 검증 명령

```bash
# 백엔드 (복제본에는 venv가 없다. 운영 작업 폴더의 venv를 읽기 전용으로 쓴다)
cd web/backend && /Users/temp/orca/bidops/.venv/bin/python -m pytest tests/deep_review/test_company_wiki.py tests/app/test_module_boundaries.py tests/app/test_module_selection.py -q

# 프런트엔드
cd web/frontend && npm run build && npm run test:screens
```
