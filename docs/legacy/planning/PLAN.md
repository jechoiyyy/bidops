# BidOps Admin 구현 계획 (보관본)

> `docs/legacy/planning/PRD.md`의 요구사항을 `docs/legacy/planning/ARCHITECTURE.md`의 구조로 구현하기 위한 단계별 계획. 각 단계는 독립적으로 완결되며, 완료 후 diff 리뷰와 커밋을 거쳐 다음 단계로 넘어간다.

## 진행 방식

| 항목 | 규칙 |
|---|---|
| 위임 | 각 단계는 `codex exec`로 구현을 위임한다 (모델 `gpt-5.6-luna`, reasoning effort `xhigh`) |
| 리뷰 | 단계 완료 직후 `git diff`로 검토하고, 즉시 수정이 필요한 사항을 반영한 뒤 다음 단계로 넘어간다 |
| 커밋 | 단계마다 한 개의 커밋을 남긴다. 커밋 메시지는 개조식으로 간략히 작성한다 |
| 최종 | 전 단계 완료 후 전체 코드 리뷰를 수행하고 발견한 문제를 수정한다 |
| 불변 | `skills/` 아래 기존 스크립트와 SKILL.md는 어느 단계에서도 수정하지 않는다 |

## 단계 개요

| 단계 | 제목 | 산출 |
|---|---|---|
| 1 | 백엔드 기반과 데이터 모델 | FastAPI 앱 골격, SQLAlchemy 모델, 설정, 테스트 환경 |
| 2 | 산출물 적재기 | 계약 검증, 회차 적재, 경고 기록, 리뷰 YAML 초기 적재 |
| 3 | 조회 API와 지표 계산 | 회차·공고·통계·검증 지표 엔드포인트 |
| 4 | 프론트엔드 기반 | Vite·Tailwind v4 토큰, 공통 셸, 라우팅, API 클라이언트 |
| 5 | 대시보드 화면 | 지표 4종, 퍼널, 등급 분포, 통과 기준, 마감 임박, 확인 요청 |
| 6 | 검토 대기열과 리뷰 기록 | 마스터-디테일, 필터, 판정 근거 표시, 리뷰 저장 API와 입력 |
| 7 | 공고 판정 상세 | 생애주기, 판정 이력, 전체 근거 표시 |
| 8 | 첨부 확보 | 첨부 API, 업로드, 기관 포털, 확보 큐 화면 |
| 9 | 수집 실행 관리 | 회차 상세, 파이프라인 실행, 로그, 산출물 검증 표시 |
| 10 | 프로필·지표 화면과 통합 마무리 | 회사 프로필 조회, 검증 지표 상세, 정적 서빙, 실행 문서 |

---

## Step 1 · 백엔드 기반과 데이터 모델

**목표**
FastAPI 애플리케이션의 골격과 데이터베이스 스키마를 만든다. 이 단계에서는 데이터를 적재하지 않는다.

**범위**

- `web/backend/pyproject.toml`, `requirements.txt` — fastapi, uvicorn, sqlalchemy, pydantic, pydantic-settings, python-multipart, pyyaml, pytest, httpx
- `web/backend/app/config.py` — 프로젝트 루트, 데이터 디렉토리, 첨부 보관 경로, 리뷰어 이름을 환경변수로 설정한다. 기본 루트는 `web/backend/`에서 두 단계 상위(`bidops-agent/`)로 계산한다
- `web/backend/app/db.py` — 엔진(WAL 활성화), 세션 팩토리, `init_db()`
- `web/backend/app/models.py` — `docs/legacy/planning/ARCHITECTURE.md` 4장의 13개 테이블과 인덱스
- `web/backend/app/main.py` — 앱 생성, CORS(개발용 5173 허용), `/api/health`
- `web/backend/tests/test_models.py` — 인메모리 SQLite에서 테이블 생성과 기본 관계 동작 확인
- `web/backend/tests/test_health.py` — 헬스 엔드포인트 응답 확인
- `.gitignore`에 `web/data/`, `web/backend/.venv/`, `web/frontend/node_modules/`, `web/frontend/dist/` 추가

**설계 지침**

- JSON 원문을 보존하는 컬럼(`*_json`)은 SQLAlchemy `JSON` 타입을 사용하고, 화면에서 자주 거르는 값만 별도 컬럼으로 승격한다
- `notice.notice_key`는 산출물의 `notice_id` 값을 그대로 담고, `bid_no`·`bid_ord`는 이 값에서 파싱한다. 파싱에 실패하면 `None`으로 두고 예외를 발생시키지 않는다
- `run.id`는 디렉토리명과 `generated_at`을 조합한 결정적 문자열로 생성한다 (ADR-009)
- 모든 시각 컬럼은 timezone-aware로 저장한다

**완료 기준**

- `.venv/bin/pytest` 전 항목 통과
- `uvicorn app.main:app` 기동 후 `/api/health`가 200을 반환한다
- `init_db()` 실행 시 13개 테이블이 생성된다

---

## Step 2 · 산출물 적재기

**목표**
`data/runs/<run_id>/`와 `reports/<run_id>/`의 파일을 읽어 데이터베이스에 적재한다.

**범위**

- `app/ingest/contracts.py` — 산출물별 Pydantic 모델. `bidops.decisions.v1`과 `v2`를 모두 수용하고, 관점·반론·확인 항목의 필수 여부를 버전에 따라 다르게 검사한다
- `app/ingest/loader.py` — 회차 디렉토리 탐색, 적재 순서(`validation-set` → `screening-results` → `collected-notices`), upsert, 경고 기록
- `app/ingest/feedback.py` — `review-feedback.yaml`에서 값이 채워진 항목만 리뷰로 적재한다
- `app/ingest/cli.py` — `python -m app.ingest.cli --run 20260817-20260823` 또는 `--all`
- `web/backend/tests/test_ingest_contracts.py`, `test_ingest_loader.py` — 픽스처로 정상·결손 산출물을 만들어 검증한다

**적재 규칙** (ADR-003)

| 위반 | 처리 |
|---|---|
| `notice_id`·`grade`·`readiness` 누락 | 해당 판정을 적재하지 않고 `level=error` 경고 |
| 관점 5개 미만 | 있는 만큼 적재하고 `level=warning` 경고에 실제 개수 기록 |
| 반론·확인 항목 없음 | 빈 목록으로 적재하고 `level=warning` |
| 알 수 없는 필드 | 무시하고 `level=info` 경고에 필드명 기록 |
| `validation-set.json` 없음 | 회차 적재를 중단하고 `level=error` |

**설계 지침**

- 재적재는 멱등이어야 한다. 같은 회차를 두 번 적재해도 행이 중복되지 않는다
- 같은 디렉토리라도 `generated_at`이 다르면 새 회차로 적재하고, 이전 회차에 `superseded_by`를 기록한다
- 실제 데이터(`data/runs/20260817-20260823/`)를 적재하는 통합 테스트를 하나 둔다. 파일이 없으면 건너뛴다

**완료 기준**

- 실제 회차를 적재하면 공고 40건, 판정 40건이 들어가고, `decisions.v1`에 대한 경고가 기록된다
- 같은 명령을 두 번 실행해도 건수가 변하지 않는다

---

## Step 3 · 조회 API와 지표 계산

**목표**
화면이 필요로 하는 모든 읽기 엔드포인트를 만든다.

**범위**

- `app/schemas.py` — 응답 모델
- `app/routers/runs.py` — `GET /api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/warnings`, `/api/runs/{run_id}/stats`, `POST /api/runs/ingest`
- `app/routers/notices.py` — `GET /api/notices`(필터·정렬·페이지), `/api/notices/{pk}`, `/api/notices/{pk}/history`
- `app/routers/metrics.py` — `GET /api/metrics/validation`
- `app/services/metrics.py` — 통과 기준 5항목 계산
- 테스트: 필터 조합, 정렬, 지표 계산 경계(계산 불가 처리)

**지표 계산 규칙** (ARCHITECTURE 6.6)

- 계산이 불가능한 항목은 `value: null`과 `status: "not_measurable"`로 응답하고 사유 문자열을 포함한다. 0으로 대체하지 않는다
- 변별력은 분석 표본 기준으로만 계산한다. 감사 표본을 포함하면 값이 왜곡된다
- 관점 분할은 관점이 2개 이상인 판정만 분모로 삼고, 그런 판정이 없으면 계산 불가로 응답한다

**목록 필터**

`run_id`(필수), `grade`, `readiness`, `focus`, `sample_role`, `attachment`(`any`·`none`·`manual`), `q`(제목·기관), `sort`(`deadline`·`grade`·`published`), `limit`, `offset`. 기본값은 분석 표본이면서 등급이 `제외`가 아닌 공고를 마감 임박순으로 정렬한다.

**완료 기준**

- 실제 데이터에서 검토 대기열 기본 조건(분석 표본이면서 등급이 `제외`가 아닌 공고)이 17건을 반환한다
- 지표 응답에서 변별력 30%(분석 표본 30건 중 `우선 검토` 9건), 관점 분할 65%(관점이 둘 이상인 판정 40건 중 `assessment`가 갈리는 26건)가 계산된다
- 회차가 하나뿐이므로 재현성은 계산 불가로 응답하고, 리뷰가 없으므로 근거 타당성도 계산 불가로 응답한다

---

## Step 4 · 프론트엔드 기반

**목표**
공통 셸과 라우팅, 디자인 토큰, API 클라이언트를 만든다. 각 화면은 자리표시자로 둔다.

**범위**

- `web/frontend/` 초기화 — Vite 6 + React 19 + TypeScript, Tailwind v4, TanStack Query v5, React Router v7
- `vite.config.ts` — `/api`를 `http://localhost:8787`로 프록시
- `src/styles/theme.css` — ARCHITECTURE 7.1의 `@theme` 토큰. IBM Plex Sans KR·Mono를 Google Fonts로 로드한다
- `src/lib/api.ts` — fetch 래퍼와 오류 처리
- `src/lib/types.ts` — 백엔드 응답 타입
- `src/components/shell/` — `Sidebar`, `TopBar`, `RunSelector`, `AppShell`
- `src/components/common/` — `Badge`, `Panel`, `Facts`, `DataTable`, `EmptyState`
- `src/routes.tsx`, `src/App.tsx`
- 회차 선택 상태를 URL 쿼리(`?run=`)로 관리하고, 변경 시 쿼리 캐시를 무효화한다

**컴포넌트 규칙**

- `Badge`의 변형: `grade-1`~`grade-4`, `readiness`, `focus`, `alert`, `neutral`. 색만으로 구분하지 않고 항상 라벨 문자열을 함께 렌더링한다
- 값이 없는 경우 빈 문자열을 렌더링하지 않는다. `값 없음`, `미확인`, `계산 불가` 가운데 맥락에 맞는 문자열을 표시한다
- 아이콘은 인라인 SVG 스트로크 방식으로 작성하고 이모지를 사용하지 않는다

**완료 기준**

- `npm run build`가 타입 오류 없이 통과한다
- 사이드바의 10개 메뉴가 라우팅된다. 구성은 모니터링(대시보드·검토 대기열·마감 추적), 판정(공고 판정 이력·담당자 리뷰 기록), 기준(회사 프로필·검증 지표), 운영(수집 실행·첨부 확보·산출물 감사 로그)이다
- 회차 선택기가 실제 회차 목록을 표시하고, 상단바에 현재 회차의 `screening_basis`가 노출된다

**레이아웃 기준**
`docs/web/design/Main.dc.html`의 사이드바와 상단바 구조를 그대로 따른다. 아트보드는 정적 목업이므로 마크업을 복사하지 말고 치수·색·계층만 따른다.

---

## Step 5 · 대시보드 화면

**목표**
`docs/web/design/Dashboard.dc.html`의 구성을 구현한다.

**범위**

- `src/pages/DashboardPage.tsx`
- `src/components/dashboard/` — `KpiCard`, `PipelineFunnel`, `GradeDistribution`, `ValidationGauges`, `DeadlineTable`, `VerificationRequests`
- `GET /api/runs/{id}/stats`와 `/api/metrics/validation`을 사용한다

**표시 규칙**

- 우선 검토 지표는 임계 구간(10~25%)을 벗어나면 초과 표시를 함께 노출한다
- 통과 기준 게이지에서 계산 불가 항목은 게이지를 0으로 채우지 말고 사유 문장을 표시한다
- 마감 임박은 7일 이내이며, 마감일이 없는 공고는 목록에 넣지 않는다
- 확인 요청 집계는 차단 항목만 대상으로 하고, 항목 문자열로 묶어 건수 내림차순으로 표시한다

**완료 기준**
실제 데이터에서 수집 2,546건, 후보 327건, 우선 검토 9건, 1차 필터 누락 5/10건이 표시되고, 검증 통과 기준 다섯 항목 가운데 재현성과 근거 타당성이 계산 불가로 표시된다.

---

## Step 6 · 검토 대기열과 리뷰 기록

**목표**
핵심 작업 화면을 구현하고 리뷰 저장 경로를 완성한다. `docs/web/design/Main.dc.html` 기준.

**범위**

백엔드

- `app/routers/reviews.py` — `GET /api/reviews`, `PUT /api/notices/{pk}/review`, `GET /api/reviews/export`
- 내보내기는 `bidops.feedback.v2` 구조의 YAML을 생성한다
- 테스트: 저장·갱신 멱등성, 내보내기 형식

프론트엔드

- `src/pages/QueuePage.tsx` — 좌 372px 목록, 우 상세
- `src/components/queue/` — `QueueFilters`, `QueueList`, `QueueListItem`
- `src/components/notice/` — `JudgmentSummary`, `NoticeFacts`, `AttachmentPanel`(읽기 전용), `PerspectiveTable`, `CounterargumentList`, `VerificationItemTable`, `RetrievalSignals`, `ReviewBar`
- 필터 상태를 URL 쿼리로 유지한다
- 리뷰 저장 후 목록의 다음 공고로 이동한다

**표시 규칙**

- 관점별 판단의 근거는 `confirmed`·`inferred`·`unknown` 상태를 배지로 구분한다
- 확인 항목의 `blocking`이 참이면 차단 배지를 앞에 둔다
- 검색 신호는 `field_kind`가 `classification`인 경우 근거 강도가 낮음을 명시한다
- 감사 표본은 기본 목록에서 제외하고 필터로만 노출한다

**완료 기준**
40분 이내 검토를 목표로, 목록에서 공고를 고르고 리뷰를 저장하는 왕복이 페이지 이동 없이 이루어진다.

---

## Step 7 · 공고 판정 상세

**목표**
`docs/web/design/NoticeDetail.dc.html` 구성을 구현한다.

**범위**

- `src/pages/NoticeDetailPage.tsx`
- `src/components/notice/LifecycleTimeline.tsx` — 사전규격·본공고·정정·판정·승인·마감
- `src/components/notice/JudgmentHistory.tsx` — `/api/notices/{pk}/history` 사용
- 관점별 판단을 접지 않고 모두 펼쳐 표시한다
- 자격·제약 플래그에서 API가 값을 주지 않은 항목은 `값 없음`으로 명시한다

**타임라인 규칙**

- 사전규격은 번호(`lifecycle.pre_spec_no`)만 수집되고 본문은 수집되지 않으므로, 번호가 있으면 점선 미수집 상태로 표시한다
- `lifecycle.changed_at` 또는 `lifecycle.change_reason`이 있으면 정정 단계를 활성화한다. 실제 데이터에서 `changed_at`은 40건 모두 비어 있고 `change_reason`만 5건 채워져 있으므로, 두 필드를 함께 보아야 정정 이력이 드러난다
- 마감일이 없으면 마감 단계에 `일자 미기재`를 표시한다

**관련 공고 연결**

`/api/notices/{pk}/history`는 같은 `notice_key`의 회차 간 판정 변화를 담당한다. 같은 사업의 다른 차수는 `notice_key`가 다르므로 이 경로로 연결되지 않는다. 따라서 별도의 관련 공고 개념을 둔다.

| 관계 | 기준 |
|---|---|
| 같은 공고의 다른 차수 | `bid_no`가 같고 `bid_ord`가 다르다 |
| 같은 사업의 다른 공고 | `lifecycle.unified_notice_no`가 같다 |
| 같은 사전규격에서 파생 | `lifecycle.pre_spec_no`가 같다 |

**완료 기준**
평생교육관리시스템 플랫폼 구축 용역 공고 3건(`bid:R26BK01687915:000`, `bid:R26BK01687915:001`, `bid:R26BK01688017:000`)이 관련 공고로 서로 연결되어 조회된다. 이 가운데 `bid:R26BK01687915:001`은 취소공고이므로 정정 단계가 활성화된다.

---

## Step 8 · 첨부 확보

**목표**
PRD 4.5절의 첨부 확보 워크플로를 완성한다.

**범위**

백엔드

- `app/services/attachments.py` — 저장 경로 구성, 확장자·크기 검증, 기관 포털 매칭
- `app/routers/attachments.py` — 목록, 업로드, 삭제, 다운로드, 확보 큐
- `app/routers/portals.py` — 기관 포털 CRUD
- 초기 데이터: 한국수자원공사, 한국도로공사, 한국토지주택공사. 검색 주소 템플릿은 `{bid_no}`·`{title}` 자리표시자를 지원하며, 실제 주소는 설정에서 바꿀 수 있도록 시드 데이터로 둔다
- 테스트: 확장자 거부, 크기 초과 거부, 경로 조작 방어, 기관 매칭

프론트엔드

- `src/components/notice/AttachmentPanel.tsx`를 세 상태(제공·미제공·확보 완료)로 확장한다
- `src/pages/AttachmentsPage.tsx` — 확보 큐. 기관별 묶음, 등급·마감 표시, 기관 포털 등록
- 업로드는 드래그 앤 드롭과 파일 선택을 모두 지원한다

**보안 규칙** (ARCHITECTURE 10장)

- 저장 파일명은 서버가 생성하고 원본 파일명은 메타데이터로만 보관한다
- 삭제는 `origin=manual`인 첨부에만 허용한다
- 애플리케이션은 외부 조달시스템에 요청하지 않고 링크만 생성한다

**완료 기준**
첨부 없는 공고에서 확보 절차 3단계가 표시되고, 파일을 등록하면 `origin=manual`로 목록에 나타난다. 현재 회차의 표본 40건 가운데 첨부가 없는 공고는 5건이며, 확보 큐가 이 5건을 담는다. 이 5건의 발주기관에는 MVP 3개 기관이 포함되어 있지 않으므로, 등록된 조달시스템이 없는 경우의 안내가 실제로 확인된다.

---

## Step 9 · 수집 실행 관리

**목표**
`docs/web/design/Runs.dc.html` 구성을 구현하고 파이프라인을 화면에서 실행한다.

**범위**

백엔드

- `app/services/pipeline.py` — `collect`·`sample`·`report` 세 단계를 서브프로세스로 실행한다. 판정 단계는 실행하지 않는다 (ADR-006)
- 실행은 백그라운드 작업으로 처리하고, 표준 출력·표준 오류를 줄 단위로 저장한다
- `app/routers/runs.py`에 실행·로그 엔드포인트를 추가한다
- API 키는 응답과 로그에 포함하지 않는다

프론트엔드

- `src/pages/RunsPage.tsx` — 좌 296px 회차 목록, 우 상세
- `src/components/runs/` — `PipelineStages`, `ArtifactValidation`, `CollectionScope`, `ExecutionLog`
- 실행 중에는 폴링으로 로그를 갱신한다

**표시 규칙**

- 산출물 검증에서 `decisions.v1`은 경고로 표시하고 어떤 필드가 누락되었는지 함께 보여준다
- 판정 단계는 실행 버튼 없이 대기 상태와 안내 문장을 표시한다
- 사전규격 수집 실패는 수집 범위 영역에 사유와 함께 표시한다

**완료 기준**
`--from-raw` 재분류를 화면에서 실행하고 로그가 갱신되며, 완료 후 새 회차가 목록에 추가된다.

---

## Step 10 · 프로필·지표 화면과 통합 마무리

**목표**
남은 두 화면을 구현하고 애플리케이션을 하나로 묶는다.

**범위**

- `app/routers/profile.py` — `company-profile.md`를 파싱하여 절 구조와 정보 상태를 반환한다. `unknown` 항목이 판정 근거에서 참조된 횟수를 함께 집계한다
- `src/pages/ProfilePage.tsx` — 절 트리, 상태별 필터, 참조 횟수
- `src/pages/MetricsPage.tsx` — 통과 기준 5항목의 계산 근거와 회차별 추이
- `app/main.py` — 빌드된 프론트엔드를 정적 파일로 서빙한다
- `web/README.md` — 설치, 실행, 적재, 테스트 명령
- `web/run-web-tests.sh` — 백엔드 pytest와 프론트 vitest·build를 함께 실행한다

**프로필 파싱 규칙**

- 마크다운을 읽기 전용으로 파싱한다. 편집 기능은 만들지 않는다
- 파싱에 실패한 절은 건너뛰지 않고 원문 그대로 표시한다

**완료 기준**

- `npm run build` 후 백엔드 단독 실행으로 전체 화면이 동작한다
- `web/run-web-tests.sh`가 전 항목 통과한다

---

## 최종 검토

전 단계 완료 후 다음을 점검하고 발견한 문제를 수정한다.

| 관점 | 확인 내용 |
|---|---|
| 데이터 정합성 | 화면의 모든 값이 산출물 필드로 역추적되는가. 애플리케이션이 값을 보정하거나 만들어내는 지점이 없는가 |
| 계약 준수 | 적재기가 누락 필드를 기본값으로 채우지 않는가. 경고가 화면에 실제로 노출되는가 |
| 지표 정확성 | 계산 불가와 0이 구분되는가. 변별력이 분석 표본만으로 계산되는가 |
| 보안 | 업로드 검증, 경로 구성, API 키 노출 여부 |
| 성능 | 목록 조회 300ms, 상세 200ms 기준 충족. N+1 조회 여부 |
| 접근성 | 등급·상태가 색만으로 구분되지 않는가 |
| 일관성 | 등급·상태 문자열이 워크플로 계약과 정확히 일치하는가 |
| 불변 조건 | `skills/` 아래 파일이 변경되지 않았는가 |
