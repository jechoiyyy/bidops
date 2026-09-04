# BidOps 작업 지침

BidOps는 기획·사업개발 담당자가 나라장터 발주계획을 조기에 탐색하고, 사전규격 제안요청서를 검토한 뒤 입찰공고까지 추적하도록 돕는 사내 의사결정 지원 시스템이다.
관측 규모는 발주계획 3일 약 1,200건, 1주 약 2,000건이며, Python 파이프라인과 FastAPI·React 관리 화면으로 처리한다.
자동 입찰, 발주처 연락, 추적 승인, 최종 Go/No-Go는 사람이 결정한다.

## 저장소 지도

```text
bidops/
├── AGENTS.md, CLAUDE.md              작업 진입점이며 내용은 동일하다
├── docker-compose.t7.yml             PostgreSQL·MinIO 기반 애플리케이션 스택
├── docker-compose.t7.*.yml           목적별 egress·모델 overlay
├── docker-compose.yml                SQLite 이전 입력용 ops 명령
├── run-tests.sh                      파이프라인 단위·교차 테스트
├── data/, reports/                   불변 회차 입력과 파생 보고서
├── docs/
│   ├── architecture.md               현재 구조와 목표 데이터 흐름
│   ├── business-rules.md             생애주기·선별·심층 검토 상태 규칙
│   ├── security.md                   접근·민감정보·모델 전송·감사 정책
│   ├── standards.md                  구현·검증 강제 기준
│   ├── engineering-notes.md          증상별 재발 방지 지식
│   ├── operations.md                 설치·실행·백업·복구 절차
│   ├── contracts.md                  REST·파일·DB 소비자 계약
│   ├── PRD.md, PLAN.md               현재 착수 범위(발주계획 C-2 선별)의 요구와 순서
│   ├── database-guide.md             DB 전체 해설과 설계 근거
│   ├── deep-review-erd.md            심층 검토 DB 권위 계약
│   ├── bid-delta-contract-spec.md    입찰 delta·최종 결정 OpenAPI·DB 명세
│   ├── order-plan-tracking-contract-request.md  발주계획 추적 결정 계약 요청안(제안, 미채택)
│   └── tracking/
│       ├── status.md                 구현과 검증의 현재 상태
│       ├── lifecycle-workstream.md 생애주기 구현의 결정 대기·할 일 기록
│       ├── findings.md               재현 가능한 미해결 문제
│       └── decisions/                기술·운영 결정과 대안·결과
├── skills/
│   ├── bidops-collect/AGENTS.md       수집·정규화·표본 선정
│   ├── bidops-screen/AGENTS.md        구조화 1차 판정·병합
│   └── bidops-report/AGENTS.md        결정적 HTML·피드백 렌더링
└── web/
    ├── AGENTS.md                      이미지·Compose·통합 검증
    ├── backend/AGENTS.md              API·PostgreSQL·객체·worker
    └── frontend/AGENTS.md             React 검토 화면
```

`docs/legacy`는 완료·미채택 계획과 과거 리뷰·목업의 보관소이고, `docs/validation-runs`는 시점별 실행 증거다. 이 자료가 현재 코드와 위 핵심 문서의 계약을 대체하지 않으며, **보관본을 실행 진입점으로 삼지 않는다.** `docs/legacy` 안의 `R-xx`·`A-xx`·phase 작업 번호는 종료된 체계다. 외부 의존성은 나라장터 OpenAPI, PostgreSQL 17, MinIO, ClamAV, Ollama Qwen3.8:27B, 승인된 사설 OpenAI-compatible vLLM, 문서 변환기, 승인 프로필 기준선 검증용 Git, Astryx 디자인 시스템(`@astryxdesign/core@0.5.2`, `@astryxdesign/cli@0.5.2`, 테마 아이콘 레지스트리가 요구하는 `lucide-react@1.39.0`)이다.
Astryx의 "레이아웃도 컴포넌트로만, `<div>` 금지" 규칙은 ADR-0040에 따라 이 저장소에 적용하지 않으며 레이아웃은 프로젝트가 소유한다.
화면의 색은 무드보드(`docs/design/moodborad.jpg`)에서 파생한 프로젝트 소유 테마 `bidops`가 정본이며(ADR-0047), 화면은 테마 토큰만 읽고 `:root`나 화면 CSS에서 `--color-*`를 재정의하지 않는다. 성공·실패·경고 의미색은 무드보드가 정하지 않는다.

## 작업 전 확인

- 모든 변경 전에 `docs/standards.md`, `docs/engineering-notes.md`, 변경 경로에서 가장 가까운 `AGENTS.md`를 읽는다.
- 상태·등급·참여 준비·사람 판정 필드를 바꾸면 `docs/business-rules.md`를, JSON/YAML/REST/DB 계약을 바꾸면 `docs/contracts.md`를 확인한다.
- DB·적재·회차를 바꾸면 원본 불변성, 부분 산출물 경고, DB 정본 리뷰, Alembic 경계를 확인한다.
- 첨부·변환·다운로드·모델 전송·로그를 바꾸면 `docs/security.md`의 경로 격리, 최소 권한, 감사, 건별 외부 전송 승인을 확인한다.
- 배포·일정·모델·backup을 바꾸면 `docs/operations.md`의 현재 실행 명령과 fail-closed 기본값을 확인한다.
- 발주계획 선별 제품 구현은 고정 3일 표본의 키워드·ColBERT·Qwen·GPT Luna 비교 실험과 사람 정답 보고서가 승인된 뒤 시작한다.

## 강제 게이트

- 확인되지 않은 회사 역량·자격·실적과 공고 사실을 추정하지 않는다. `unknown`과 `null`은 검증 대기 상태로 보존한다.
- 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 서로 대신하지 않는다.
- 모델의 숫자·요구사항·근거는 원문 위치와 연결하고 결정적 검증을 통과시킨다. 실패 결과는 사람 검토로 보내며 자동 보정하지 않는다.
- 기존 파이프라인은 subprocess·버전 파일 계약으로 연결한다. 웹에서 내부 구현을 가져오거나 같은 업무 규칙을 복제하지 않는다.
- 외부 모델은 승인된 payload만 건별 전송한다. 운영 장애 때 hosted OpenAI로 자동 fallback하지 않는다.

## 현재 런타임 사실

- PostgreSQL 17의 `bidops` schema와 versioned MinIO가 운영 정본이다. SQLite는 격리 테스트와 일회성 이전 입력에만 사용한다.
- `docker-compose.t7.yml`이 애플리케이션 스택이다. 기본 network는 내부망이며 외부 호출은 목적별 overlay를 명시한 경우에만 연다.
- 관리 화면은 **데스크톱·노트북 전용**이다. 지원 폭은 1280~1920px이며 모바일·태블릿 레이아웃과 터치 전용 조작을 만들지 않는다. 1280px 미만은 가로 스크롤을 허용하고 별도 레이아웃으로 전환하지 않는다(ADR-0046). 화면 검증 viewport는 laptop 1280x800과 desktop 1440x900 두 폭이다.
- 현재 애플리케이션에는 로그인·역할 기반 권한이 없다. 사내망 접근 제한이 경계이고 담당자 이름은 감사 표식일 뿐 인증이 아니다.
- 스케줄러와 always-on은 기본 비활성이다. 앱 startup은 migration, seed, 정책 활성화, 모델 호출을 수행하지 않는다.
- 발주계획·사전규격 중심 신규 흐름, 준비·실패 재시작 화면, 입찰 delta 추적, SSO, 알림은 아직 구현 전이다.

## 문제 보고

첨부 원문의 허용 경로 이탈, API 키·회사자료의 로그나 응답 노출, 승인 없는 외부 모델 전송, 회차 원본 또는 기존 리뷰 덮어쓰기, 원문과 다른 모델 근거의 검증 통과를 발견하면 관련 실행을 중지하고 즉시 보고한다. 현재 범위에서 해결할 수 없는 구조 문제는 재현 조건, 영향, 지금 해결할 수 없는 이유, 후속 방향을 `docs/tracking/findings.md`에 기록한다.

<!-- ASTRYX:START -->
Astryx v0.5.2 · 90+ components
CLI: run every command as `npx @astryxdesign/cli <cmd>` (shown below as `astryx ...`).

SETUP (once, in your app entry e.g. main.tsx) — without these, components render unstyled:
  import "@astryxdesign/core/reset.css";
  import "@astryxdesign/core/astryx.css";

WORKFLOW — discover, don't guess. Before writing UI:
1. `astryx build "<idea>"` — START HERE: returns a kit (closest [page] + [block]s + [component]s). No args = full playbook.
2. `astryx template <name> [--skeleton]` — scaffold the [page]/[block]s it named, or study their layout. Templates are reference code.
3. `astryx component <Name>` — props + examples for every component you use.

RULES:
- No <div> — components do all layout/spacing, page frame included.
- Frame first: read `astryx docs layout` before writing any page or screen — page frame, region widths, breakpoint behavior.
- Dense data = rows (Table, List/Item), never Card-wrapped list items; Card is for standalone widgets. Status = StatusDot/Token; Badge = counts only.
- Custom styling: component props first; else style/className with tokens — var(--color-*|--spacing-*|--radius-*). No raw hex/px. (No StyleX/Tailwind compiler here — don't use xstyle/utility classes.)
- Tokens for every value (`astryx docs tokens`). Brand/accent belongs in the theme (`astryx theme list` / `theme add <slug>`, or `astryx theme template` for a custom one) — never override --color-* in :root.
- SELF-CHECK before you finish: re-read the file and replace any raw <div>/<span> layout, imported .css/@apply, or hardcoded value (#hex, 16px) with the component or a token (var(--color-*|--spacing-*|…)). If unsure a component/prop exists, run `astryx component <Name>` / `astryx search "<thing>"`; don't hand-roll CSS.

MORE CLI:
  search "<query>"   find any component / hook / doc / template / block
  component --list   90+ components by category
  template --list    page + block recipes
  docs <topic>       browser-support, cli-integrations, color, elevation, getting-started, icons, illustrations, internationalization, layout, migration, motion, principles, shape, spacing, styling-libraries, styling, theme, tokens, typography, working-with-ai
  swizzle <Name>     eject component source for deep customization
  upgrade --apply    run after any @astryxdesign/core bump
<!-- ASTRYX:END -->
