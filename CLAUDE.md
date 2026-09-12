# BidOps 작업 지침

BidOps는 기획·사업개발 담당자가 나라장터 발주계획을 조기에 탐색하고, 사전규격 제안요청서를 검토한 뒤 입찰공고까지 추적하도록 돕는 사내 의사결정 지원 시스템이다.
관측 규모는 발주계획 3일 약 1,200건, 1주 약 2,000건이며, Python 파이프라인과 FastAPI·React 관리 화면으로 처리한다.
자동 입찰, 발주처 연락, 추적 승인, 최종 Go/No-Go는 사람이 결정한다.

## 저장소 지도

```text
bidops/
├── AGENTS.md, CLAUDE.md              작업 진입점이며 내용은 동일하다
├── docker-compose.yml                PostgreSQL·MinIO 기반 애플리케이션 스택
├── docker-compose.edge.yml           관리 화면 host publish (이 파일만 포트를 연다)
├── docker-compose.model-egress.yml   screening·overview·deep_review 모델 egress
├── docker-compose.c2-order-plan.yml  C-2 발주계획 판정 입력 마운트
├── docker-compose.prespec-attachment.yml  사전규격 첨부 G2B egress
├── docker-compose.mock-reference.yml 모델 없는 참조 실행
├── run-tests.sh                      파이프라인 단위·교차 테스트
├── data/, reports/                   불변 회차 입력과 파생 보고서
├── docs/
│   ├── ARCHITECTURE.md               현재 구조·계약·목표 데이터 흐름 (정본)
│   ├── ADR.md                        결정 통합 색인 (상세는 tracking/decisions/)
│   ├── PRD.md, PLAN.md               현재 착수 범위(발주계획 C-2 선별)의 요구와 순서
│   ├── business-rules.md             생애주기·선별·심층 검토 상태 규칙
│   ├── standards.md                  구현·검증 강제 기준
│   ├── engineering-notes.md          증상별 재발 방지 지식
│   ├── operations.md                 설치·실행·백업·복구 절차
│   ├── contracts.md                  REST·파일·DB 소비자 계약
│   ├── database-guide.md             DB 전체 해설과 설계 근거
│   ├── deep-review-erd.md            심층 검토 DB 권위 계약
│   ├── bid-delta-contract-spec.md    입찰 delta·최종 결정 OpenAPI·DB 명세
│   ├── scheduling.md                 공고 판정 스케줄러의 예약·기간·fail-closed 조건
│   ├── model-quality-gate.md         공고 판정 품질 게이트의 고정 입력과 통과 기준
│   ├── prespec-reference-run-guide.md  사전규격 참조 실행 시작 가이드 (먼저 읽는다)
│   ├── e2e-bc-acceptance.md          문서 준비(B)→심층 검토(C) 연속 인수 절차
│   ├── e2e-lifecycle-fill.md         공고·사전규격·리뷰 테이블 채우기와 화면 확인 절차
│   ├── docker-consolidation.md       t7 접두사 제거와 Compose 프로젝트·호스트 자원 정리 기록
│   ├── agent/agent-runtime.md        공고 판정 worker의 입력 동결·span·telemetry
│   ├── design/                       화면 시안 기준 작업의 정본
│   │   ├── ADR.md                    ADR-0039~0048 (디자인 시스템·정보구조·지원 폭·팔레트)
│   │   ├── PRD.md                    화면 요구와 무드보드 색 토큰 표
│   │   ├── PLAN.md                   시안 기준 구현 순서(단계 A~F)와 검증 절차
│   │   ├── order-plan-tracking-contract-request.md  발주계획 추적 결정 계약 요청안(제안, 미채택)
│   │   └── moodborad.jpg             색 팔레트의 원본 무드보드
│   ├── deep-review-v2/               첨부문서 분석 설계(결정적 부분만 구현, ADR-0051)와 Luna 시안 검증 계획(보류)
│   ├── rhwp-document-pipeline/       rhwp 네이티브 변환 파이프라인 작업 정본(ADR·Requirements·Design·Spec·Plan, 2026-09-10 시작)
│   ├── reference/                    회사 프로필·실적 근거자료
│   ├── validation-runs/              시점별 실행 증거
│   └── tracking/
│       ├── status.md                 구현과 검증의 현재 상태
│       ├── lifecycle-workstream.md   생애주기 구현의 결정 대기·할 일 기록
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

`docs/validation-runs`는 시점별 실행 증거이며 현재 코드와 위 핵심 문서의 계약을 대체하지 않는다. 완료·미채택 계획, 과거 리뷰·목업, 인수인계 문서는 저장소에 보관하지 않으며 필요하면 git 이력에서 찾는다. 과거의 `R-xx`·`A-xx`·phase·T-번호 체계는 종료됐고 새 작업에 다시 쓰지 않는다. 외부 의존성은 나라장터 OpenAPI, PostgreSQL 17, MinIO, ClamAV, 승인된 사설 OpenAI-compatible vLLM(`qwen3.8-27B`), 문서 변환기, 승인 프로필 기준선 검증용 Git, Astryx 디자인 시스템(`@astryxdesign/core@0.5.2`, `@astryxdesign/cli@0.5.2`, 테마 아이콘 레지스트리가 요구하는 `lucide-react@1.39.0`)이다.
Astryx의 "레이아웃도 컴포넌트로만, `<div>` 금지" 규칙은 ADR-0040에 따라 이 저장소에 적용하지 않으며 레이아웃은 프로젝트가 소유한다.
화면의 색은 무드보드(`docs/design/moodborad.jpg`)에서 파생한 프로젝트 소유 테마 `bidops`가 정본이며(ADR-0048), 화면은 테마 토큰만 읽고 `:root`나 화면 CSS에서 `--color-*`를 재정의하지 않는다. 성공·실패·경고 의미색은 무드보드가 정하지 않는다.

## 작업 전 확인

- 모든 변경 전에 `docs/standards.md`, `docs/engineering-notes.md`, 변경 경로에서 가장 가까운 `AGENTS.md`를 읽는다.
- 상태·등급·참여 준비·사람 판정 필드를 바꾸면 `docs/business-rules.md`를, JSON/YAML/REST/DB 계약을 바꾸면 `docs/contracts.md`를 확인한다.
- DB·적재·회차를 바꾸면 원본 불변성, 부분 산출물 경고, DB 정본 리뷰, Alembic 경계를 확인한다.
- 첨부·변환·다운로드·모델 전송·로그를 바꾸면 경로 격리, 최소 권한, 감사, 건별 외부 전송 승인(모델 전송 정책은 ADR-0050 완화 항목 참조)을 확인한다.
- 배포·일정·모델·backup을 바꾸면 `docs/operations.md`의 현재 실행 명령과 fail-closed 기본값을 확인한다.
- 발주계획 선별 제품 구현은 고정 3일 표본의 키워드·ColBERT·Qwen·GPT Luna 비교 실험과 사람 정답 보고서가 승인된 뒤 시작한다.

## 검증 범위와 종료 기준

- 검증은 변경한 기능과 직접 영향받는 경로부터 수행한다. 작은 문구·스타일·단일 화면 변경에 전체 스위트, 전체 이미지 재빌드, 전 화면 재검사를 관성적으로 실행하지 않는다.
- 전체 검사는 공통 기반·여러 모듈의 계약 변경, 관련 검사에서 확인된 광범위한 회귀, 사용자의 명시적 요청처럼 구체적인 근거가 있을 때만 수행한다. 실행 전에 그 이유를 짧게 설명한다.
- 관련 검사가 통과하면 검증을 종료한다. 이후 코드 변경이나 새로운 실패·미해결 위험이 없으면 같은 빌드·테스트·화면 확인을 반복하지 않는다. 수정 후에는 영향받은 검사만 다시 실행한다.
- 실패하면 먼저 원인과 변경 관련성을 확인한다. 통과 결과를 얻기 위한 반복 실행이나 근거 없는 ‘3회 연속 통과’ 검사를 하지 않는다. 무관한 기존 실패는 사실대로 보고하고 작업 범위를 불필요하게 넓히지 않는다.
- 문서만 바꾼 경우에는 변경 내용과 diff를 확인하며 앱 빌드·화면 테스트·배포는 하지 않는다. 검증을 위해 일회성 도구·테스트 인프라·장문의 기록을 과도하게 추가하지 않는다.
- 검증 실행 범위는 이 절을 우선한다. `docs/standards.md`와 하위 `AGENTS.md`의 명령 목록은 매 작업마다 전부 실행하라는 뜻이 아니다. 해당 변경에 필요한 계약·보안·데이터 불변성 검사는 유지하고, 실행한 범위와 남은 한계를 정확히 보고한다.

## 강제 게이트

- 확인되지 않은 회사 역량·자격·실적과 공고 사실을 추정하지 않는다. `unknown`과 `null`은 검증 대기 상태로 보존한다.
- 적합성 등급, 참여 준비 상태, 심층 검토 추적 선택, 최종 입찰 Go/No-Go를 서로 대신하지 않는다.
- 모델의 숫자·요구사항·근거는 원문 위치와 연결하고 결정적 검증을 통과시킨다. 실패 결과는 사람 검토로 보내며 자동 보정하지 않는다.
- 기존 파이프라인은 subprocess·버전 파일 계약으로 연결한다. 웹에서 내부 구현을 가져오거나 같은 업무 규칙을 복제하지 않는다.
- 외부 모델은 승인된 payload만 건별 전송한다. 운영 장애 때 hosted OpenAI로 자동 fallback하지 않는다.
- 모델 호출은 용도(`screening`·`overview`·`deep_review`)별 설정으로 나간다. MVP 기간에는 허용 host·선언 revision을 비워 둬도 그 용도는 호출한다(ADR-0050 §5 완화); 값이 있으면 허용 host 목록·64자 hex 여부를 그대로 검사해 어긋나면 **호출 전에** fail closed한다.
- 참조 실행 결과(`quality_status=unmeasured_reference|mock_reference`)를 운영 완료·품질 근거·정책 활성화 근거로 적지 않는다. 표식 없음(`null`)을 미측정이나 측정으로 승격시키지 않는다.

## 현재 런타임 사실

- PostgreSQL 17의 `bidops` schema와 versioned MinIO가 운영 정본이다. SQLite는 격리 테스트와 일회성 이전 입력에만 사용한다.
- `docker-compose.yml`이 애플리케이션 스택이다. 기본 network는 내부망이며 외부 호출은 목적별 overlay를 명시한 경우에만 연다.
- 관리 화면은 **데스크톱·노트북 전용**이다. 지원 폭은 1280~1920px이며 모바일·태블릿 레이아웃과 터치 전용 조작을 만들지 않는다. 1280px 미만은 가로 스크롤을 허용하고 별도 레이아웃으로 전환하지 않는다(ADR-0047). 화면 검증 viewport는 laptop 1280x800과 desktop 1440x900 두 폭이다.
- 현재 애플리케이션에는 로그인·역할 기반 권한이 없다. 사내망 접근 제한이 경계이고 담당자 이름은 감사 표식일 뿐 인증이 아니다.
- 스케줄러와 always-on은 기본 비활성이다. 앱 startup은 migration, seed, 정책 활성화, 모델 호출을 수행하지 않는다.
- 사전규격은 등급이 `우선 검토`이면 문서 준비를 자동으로 진행한다. `BIDOPS_PRESPEC_OVERVIEW_ENABLED`가 켜져 있으면 ready 묶음에서 개요 run을 자동 enqueue하고, 개요 run이 `completed`이고 `SW사업대상=Y`이며 현재 회사 핏 `matched`인 게이트를 지나야 심층 검토를 자동 시작한다(ADR-0049·ADR-0054, 2026-09-08 회사 핏 게이트 추가, 2026-09-11 개요 스택 재작성). 회사 핏은 기본 비활성이고 현재는 명시적으로 켠 참조 실행만 지원한다. 자동으로 여는 것은 분석의 시작뿐이며 추적 승인과 최종 Go/No-Go는 사람이 결정한다.
- C-1 공고 판정·사전규격 개요·심층 검토는 `app/core/model_client.py` 하나를 용도별 설정으로 부른다. C-2 발주계획 어댑터만 별도 transport로 남아 있다.
- 준비·실패 재시작 화면, 개요 run 실행기·REST·화면(P2·P3), 입찰 delta 계산 worker, deep-review-v2 역할별 모델 분석, SSO, 알림은 아직 구현 전이다. 입찰 delta는 저장·REST·화면까지 있으나 비교를 실제로 계산하는 worker가 없어 `bid_delta_comparison`이 `pending`에 머문다.

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
