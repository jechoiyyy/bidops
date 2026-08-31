# BidOps UI/UX 잔여 작업 콜드 세션 실행 계획

- 작성일: 2026-08-31
- 범위: [UI/UX 수정 계획](docs/review/2026-08-31-ui-ux-remediation-plan.md)의 남은
  R-08, R-09, R-11
- 현재 결론: R-07과 [ADR-0034](docs/tracking/decisions/0034-bid-delta-final-decision.md)는
  채택됐다. R-08은 업무 gate가 열렸지만 작업 트리 안정화 전에는 시작하지 않는다. R-09와
  R-11은 각각 R-08과 R-09의 실제 완료를 기다린다.
- 비범위: T-23 phase 2, 발주계획 선별 실험, SSO, 알림, 운영 활성화. 다만 현재 T-23 변경이
  R-08 파일과 겹치므로 작업 트리 gate에서만 다룬다.

이 파일은 새 세션이 긴 검토 이력을 다시 추론하지 않고 안전하게 이어가기 위한 실행
진입점이다. 요약이 정본 계약을 대체하지 않는다. 충돌하면 `AGENTS.md`와 아래 정본 문서가
우선한다.

## 0. 새 세션에 전달할 지시문

```text
`/home/jechoi/projects/bidops/plan.md`를 처음부터 끝까지 읽고, 현재 코드와 git 상태를 다시
확인한 뒤 선행조건을 만족하는 가장 앞의 미완료 작업 하나만 수행하라. 독립 작업은
서브에이전트에 파일 소유권을 겹치지 않게 배정하고, coordinator가 통합·전체 검증·문서 갱신을
직접 확인하라. 기존 dirty/untracked 파일을 보존하고, 외부 모델·실제 나라장터·운영 데이터를
호출하지 말며, 완료하지 못한 검증을 통과로 기록하지 마라.
```

사용자가 `R-08`, `R-09`, `R-11` 또는 아래 세부 ID를 지정하면 해당 범위만 수행한다. ID가
없으면 상태를 재확인하고 가장 앞의 `ready` 작업 하나를 고른다. 한 세션에서 다음 상위 작업으로
자동 진입하지 않는다.

## 1. 필수 읽기와 정본 순서

모든 세션은 변경 전에 다음을 읽는다.

1. `AGENTS.md`
2. `docs/standards.md`
3. `docs/engineering-notes.md`
4. 이 파일 전체
5. `docs/review/2026-08-31-ui-ux-remediation-plan.md`의 0절과 대상 R 절
6. `docs/review/2026-08-31-ui-ux-advancement-plan.md`의 0절과 제품 원칙

R-08은 추가로 다음을 읽는다.

1. `web/AGENTS.md`
2. `web/backend/AGENTS.md`
3. `docs/tracking/decisions/0034-bid-delta-final-decision.md`
4. `docs/review/bid-delta-contract-spec.md`
5. `docs/contracts.md`
6. `docs/business-rules.md`
7. `docs/security.md`
8. `docs/operations.md`
9. `docs/tracking/lifecycle-workstream.md`

R-09와 R-11은 추가로 `web/frontend/AGENTS.md`, R-08의 실제 schema·OpenAPI·대상 backend
테스트를 읽는다. 프런트는 문서 예시나 임시 시안을 producer로 간주하지 않는다.

정본 우선순위는 다음과 같다.

1. 가장 가까운 `AGENTS.md`와 보안·운영 강제 규칙
2. 채택 ADR과 `docs/business-rules.md`
3. `docs/contracts.md`와 `docs/review/bid-delta-contract-spec.md`
4. 현재 migration·OpenAPI·실행 테스트
5. 이 계획과 과거 실행 기록

## 2. 현재 상태와 반드시 다시 확인할 사실

작성 시점 관측은 `main@84bbcc5`이고 `origin/main`과 같았다. 실행 시점의 HEAD와 작업 트리가
항상 우선한다.

- R-01~R-06과 R-10은 실행 기록상 완료다.
- R-07은 A1 `go|no_go`, B1 7개 범주와 보수적 material v1, C1 strict, 회사 내부망 모델,
  safe audit allowlist로 채택됐다.
- bid-delta backend schema·service·router·migration·test는 아직 없다.
- production route `/opportunities/:opportunityId/bid-delta`는 의도적으로 연결되지 않았다.
- 다음 시안은 untracked 상태이며 R-08의 producer가 아니다.
  - `web/frontend/src/components/bid-delta/api.ts`
  - `web/frontend/src/components/bid-delta/types.ts`
  - `web/frontend/src/pages/BidDeltaDecisionPage.tsx`
  - `web/frontend/src/styles/bid-delta-decision.css`
- 시안의 `same`, 대문자 `Go|No-Go`, completed-only 상태, 5개 한글 범주, 단일 GET은 채택
  계약과 다르다. 문서쌍·before/after·근거·시스템/사람 분리 표현만 선택적으로 재사용한다.
- 현재 T-23 phase 2 변경이 `web/backend/app/models.py`, Alembic `0014`,
  `services/prespec_overview.py`와 관련 테스트를 수정하고 있다. R-08의 DB 변경과 겹친다.
- R-07 채택 문서 일부도 작성 시점에는 아직 uncommitted였다. 별도 worktree를 만들 경우 해당
  결정이 기준 commit에 실제 포함됐는지 먼저 확인한다.
- 과거 상태 문서의 Alembic head, table 수, 테스트 수, "delta는 범위 밖" 문구는 현재 코드와
  다를 수 있다. 수치를 복사하지 말고 재측정한다.

모든 세션 시작 시 다음을 기록한다.

```bash
cd /home/jechoi/projects/bidops
pwd
git rev-parse --short HEAD
git branch --show-current
git status --short
git diff --stat
git diff -- <이번 작업의 대상 파일>
```

기존 수정과 untracked 파일은 사용자 작업이다. `reset`, `checkout`, 자동 stash, 일괄 포맷,
일괄 snapshot 갱신으로 치우지 않는다. 대상 파일의 기존 의도나 소유자를 확인할 수 없으면
구현을 멈추고 충돌 파일을 보고한다.

## 3. 작업 DAG

| ID | 작업 | 의존성 | 현재 상태 | 종료 증거 |
|---|---|---|---|---|
| S-00 | 작업 트리·계약 기준선 안정화 | 없음 | ready | R-08 겹침이 없고 채택 계약이 기준 tree에 존재 |
| R08-0 | R-08 구현 기준선·테스트 skeleton 고정 | S-00 | blocked | 실제 Alembic head와 5개 endpoint matrix 확인 |
| R08-1 | DB model·migration·권한·불변 trigger | R08-0 | blocked | 임시 PostgreSQL 17 fresh/rollback/role 검증 |
| R08-2 | Pydantic wire schema·안정 오류 mapping | R08-0 | blocked | 계약 예시와 schema 테스트 1:1 일치 |
| R08-3 | 내부망 비교 runtime·검증기 | R08-0 | blocked | fake 내부 binding과 fail-closed 테스트 |
| R08-4 | service·router·currentness·결정 통합 | R08-1~3 | blocked | 5개 endpoint 대상 테스트 통과 |
| R08-5 | PostgreSQL·전체 backend·문서 검증 | R08-4 | blocked | 전체 결과와 migration 증거 기록 |
| R09-0 | 현재 시안과 실제 R-08 producer 대조 | R08-5 | blocked | 보존·폐기 목록과 exact TS type 확정 |
| R09-1 | workspace·비교·retry·결정 UI 연결 | R09-0 | blocked | production route와 typed error 동작 |
| R09-2 | R-09 기능·반응형 회귀 | R09-1 | blocked | build와 대상 Playwright 4 viewport 통과 |
| R11-0 | visual·bundle 기준선 재측정 | R09-2 | blocked | 실제 snapshot 수와 pre-build chunk 기록 |
| R11-1 | route lazy loading·결정적 visual fixture | R11-0 | blocked | loading/error/SPA fallback 유지 |
| R11-2 | snapshot 승인·전체 visual 회귀 | R11-1 | blocked | 의도별 snapshot 목록과 전체 결과 기록 |

`R08-1`, `R08-2`, `R08-3`만 계약 interface를 먼저 고정한 뒤 병렬화할 수 있다. 나머지는
의존 순서를 지킨다.

## 4. S-00 — 작업 트리 안정화 gate

목표는 사용자 변경을 잃지 않으면서 R-08이 수정할 파일을 한 소유자에게 넘길 수 있는 상태를
만드는 것이다.

1. live `git status`, 현재 Alembic heads, 실행 중 agent/terminal과 대상 파일 diff를 확인한다.
2. T-23 phase 2가 계속 작업 중이면 R-08을 시작하지 않는다.
3. T-23 변경이 끝났다면 해당 작업의 자체 검증과 인계 결과를 확인한다. 기존 보고만 믿지 않고
   변경 파일과 최종 요약을 다시 읽는다.
4. `models.py`, 현재 head migration, runtime privilege allowlist, DB table count assertion,
   `docs/contracts.md`의 phase 2 부분이 서로 맞는지 확인한다.
5. 채택된 ADR-0034와 bid-delta 계약 문서가 실제 작업 tree에 존재하는지 확인한다.
6. commit·push가 필요하면 사용자에게 명시적으로 요청받은 범위만 수행한다. 승인 없이 Git
   이력을 만들지 않는다.
7. 겹침을 피하려고 별도 worktree가 필요하면 현재 사용자 diff를 자동 이동하지 않는다. 채택
   계약이 포함된 commit을 기준으로 만들 수 있을 때만 사용한다.

중단 조건:

- `models.py`나 current Alembic head가 다른 작업에서 계속 변한다.
- 채택 계약은 working tree에만 있고 새 작업 위치에는 없다.
- 현재 DB 기준선 테스트가 실패하는데 원인을 R-08 변경으로 덮어야만 진행할 수 있다.
- 기존 변경을 reset/stash/delete해야만 파일 소유권을 분리할 수 있다.

## 5. 멀티에이전트 운영 규칙

coordinator는 작업 선택, 정본 계약 해석, 공용 파일 통합, 최종 테스트와 문서 기록을 소유한다.
worker 완료 문구만으로 완료 처리하지 않는다.

R-08 병렬 wave는 다음처럼 파일 소유권을 분리한다.

| worker | 허용 쓰기 범위 | 금지 범위 |
|---|---|---|
| persistence | `models.py`, 새 bid-delta migration, DB migration/권한 전용 테스트 | schema/router/frontend/공용 문서 |
| contract | 신규 `schemas/bid_delta.py`, schema 전용 테스트 | model/migration/service/router |
| runtime | 신규 `services/bid_delta_runtime.py`, runtime·validator 전용 테스트 | model/migration/router/main |
| coordinator | `services/bid_delta.py`, `routers/bid_delta.py`, `main.py`, 통합 테스트, 문서 | worker 작업 중인 파일의 동시 편집 |

병렬 wave 전에 model 이름, schema import 경계, runtime protocol, 오류 타입을 짧은 interface로
고정한다. worker가 새 상태·오류·필드를 필요로 하면 임의 추가하지 않고 coordinator에게
결정 요청을 보낸다. 같은 파일을 둘 이상의 agent가 편집하지 않는다.

R-09에서는 types/api와 presentation을 나눌 수 있지만 `routes.tsx`, 공용 mock, visual snapshot은
한 agent만 소유한다. R-11의 snapshot 검토와 bundle 측정은 순차 실행한다.

Orca 오케스트레이션을 쓸 때는 Run과 Task/Dispatch를 실제로 만들고, 독립 Task를 모두 만든 뒤
worker를 시작한다. 각 worker는 파일 변경·검증·남은 위험을 `worker_done`으로 보고하고,
coordinator는 diff와 테스트를 직접 재검증한 뒤 worker를 release한다.

## 6. R-08 — delta·최종 결정 backend

### R08-0. 기준선과 skeleton

1. `alembic heads`로 실제 다음 revision을 정한다. 문서의 번호를 추측하지 않는다.
2. `docs/review/bid-delta-contract-spec.md`의 endpoint, DB, 오류, 테스트 matrix를 체크리스트로
   옮긴다.
3. 현재 `Opportunity`, `OpportunityLink`, `DocumentBundle`, `DocumentVersion`,
   `DocumentStructure`, `IdempotencyRecord`, `AuditEvent`, actor header 구현을 재사용한다.
4. 신규 bid-delta 파일이 정말 없는지 확인하고, 동일 업무 규칙을 기존 서비스와 중복 구현하지
   않는다.
5. `test_bid_delta.py`, 필요하면 `test_bid_delta_postgres.py`의 fixture 경계를 먼저 만든다.

### R08-1. 저장 모델과 migration

구현 대상은 계약 명세 5절의 다음 append-only/immutable 구조다.

- `bid_delta_comparison`: exact 양쪽 input fence, policy, calculation/result/materiality,
  completed result digest
- `bid_delta_attempt`: sequence, lease fence, immutable 내부 runtime binding, terminal state
- `bid_delta_item`: 7개 category가 attempt마다 정확히 한 번, result/materiality 조합 제약
- `bid_delta_evidence`: baseline/comparison side, exact document/structure/hash, verified locator
- `bid_final_decision`: `go|no_go`, reason, actor, request ID, comparison/result/document fence,
  supersession chain

필수 조건:

- 정확한 FK와 unique/check/partial unique를 PostgreSQL에서 강제한다.
- completed/failed attempt, item/evidence, final decision은 UPDATE/DELETE를 거부한다.
- final decision tip sequence와 supersedes는 opportunity row lock 안에서 배정한다.
- DB에 `current=true`를 저장하지 않는다. currentness는 derived projection이다.
- app/worker runtime privilege allowlist를 명시적으로 갱신하며 worker는 final decision을 쓸 수
  없다.
- startup에서 migration, seed, 비교 계산을 실행하지 않는다.

### R08-2. wire schema와 오류

다음 5개 endpoint를 계약 그대로 제공한다.

```text
GET  /api/opportunities/{opportunity_id}/bid-delta
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons
GET  /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/attempts
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/final-decisions
```

- request/response의 `schema_version`, exact input fence, nullable/required field를 명세 예시와
  맞춘다.
- calculation은 `pending|running|completed|failed`, result는
  `changed|unchanged|unknown|failed|null`로 분리한다.
- category 7개, materiality, currentness와 reason code를 임의 번역하지 않는다.
- FastAPI 구조 422와 parsing 뒤 domain 422를 구분한다.
- 400/404/409/422/503의 안정 code와 안전한 message/request ID를 유지한다.
- DB row, object key/path, signed URL, model body를 response에 노출하지 않는다.

### R08-3. 내부망 runtime과 결정적 검증

- 회사 내부망 allowlist의 Ollama 또는 사설 vLLM binding만 허용한다.
- exact pair, category policy, binding, payload 범위와 actor/request ID가 있는 comparison 생성이
  해당 snapshot의 건별 내부 처리 승인이다.
- binding/승인/payload scope가 없거나 어긋나면 503으로 닫고 모델을 호출하지 않는다.
- 외부 endpoint와 hosted fallback을 만들지 않는다.
- fake transport로 timeout, schema 위반, 잘림, 근거 누락, hash/locator mismatch를 재현한다.
- `changed|unchanged`는 양쪽 verified evidence가 있어야 한다. `unknown|failed`를
  `unchanged`/`non_material`로 바꾸지 않는다.
- v1 material 정책은 실질 조건 변경을 material, 양쪽 근거로 같은 의미가 확인된 표기 차이만
  non-material로 둔다. 근거 없는 비율·일수 threshold를 추가하지 않는다.
- raw prompt/response를 DB 일반 column, 로그, audit metadata에 넣지 않는다.

### R08-4. service·router 통합

- router는 parsing과 HTTP mapping만 담당한다.
- service가 후보 조회, exact fence 재검증, row lock, idempotency, attempt 상태 전이, 결과 commit,
  final decision supersession을 같은 논리 transaction에서 소유한다.
- 여러 입찰공고·정정 중 서버가 latest를 자동 선택하지 않는다.
- 새 authoritative bid/정정 또는 새 ready 비교 문서는 기존 결정 row를 수정하지 않고 strict
  currentness를 `stale`로 만든다. 순서·효력이 불확실하면 `unknown`이다.
- 비교 실패 retry는 새 attempt를 만들고 과거 partial item/evidence를 보존한다.
- audit metadata는 안전한 ID, status/error code, policy version, category count, input/result hash,
  binding ID/digest만 허용한다. reason 전문, quote, actor 이름 복제, 원문, prompt/response,
  object key/path는 금지한다.
- `main.py`에 router를 등록하되 앱 startup 동작은 늘리지 않는다.

### R08-5. 완료 검증

최소 검증 순서는 다음과 같다. 실제 생성한 테스트 파일명에 맞춰 좁은 범위부터 실행한다.

```bash
cd /home/jechoi/projects/bidops/web/backend
.venv/bin/python -m pytest tests/test_bid_delta.py -q
```

DB 변경은 별도 일회용 PostgreSQL 17에서 다음을 확인한다.

- 빈 DB `upgrade head`
- 직전 revision으로 허용된 `downgrade` 뒤 재업그레이드
- `alembic check`
- check/FK/unique/partial unique/append-only trigger의 실제 거부
- app/worker role allowlist와 worker final-decision 거부
- 같은 payload replay, 다른 payload conflict, 동시 attempt/decision 단일 승자

PostgreSQL 전용 테스트가 환경변수 없이 skip되지 않았는지 요약의 skip 수를 확인한다. 그 뒤
전체 backend suite를 끝까지 실행한다.

```bash
cd /home/jechoi/projects/bidops/web/backend
.venv/bin/python -m pytest tests -q
```

4분 이상 출력이 없어도 즉시 hang으로 단정하지 않는다. 실패·skip은 기존 baseline과 신규
회귀를 분리한다. 마지막에 관련 정본 문서와 수정 계획 10.13 실행 기록을 갱신하고
`git diff --check`를 실행한다. 이 모든 증거가 없으면 R-08을 완료로 기록하지 않는다.

## 7. R-09 — delta·최종 결정 frontend

R-08 API와 typed error 및 대상 backend·PostgreSQL 테스트 결과가 실제로 존재할 때만 시작한다.

### R09-0. 시안 대조

1. untracked 시안을 삭제하거나 덮어쓰기 전에 전부 읽는다.
2. 실제 R-08 response와 TS type을 field-by-field 대조한다.
3. 문서쌍, 비교 시각, before/after, 양쪽 근거, 시스템 결과와 사람 결정 분리 표현은 접근성
   기준을 만족하면 재사용한다.
4. `same`, 대문자 결정, 5개 범주, completed-only 상태, 단일 evidence, 임의 오류 message 분기,
   단일 GET-only client는 폐기하고 실제 producer에 맞춰 다시 쓴다.

### R09-1. 기능 연결

- workspace에서 baseline/comparison 후보를 사람이 exact pair로 선택한다.
- comparison 생성 뒤 pending/running을 polling하고 completed/failed를 구분한다.
- failed retry는 새 attempt가 생긴다는 점과 과거 이력을 표시한다.
- 7개 category, materiality, 양쪽 document version·hash·verified evidence를 표시한다.
- unknown/failed는 변경 없음으로 보이지 않으며 자동 Go/No-Go 제안을 하지 않는다.
- final decision form은 actor, `go|no_go`, nonblank reason을 요구한다.
- request에 comparison version, result hash, 양쪽 document version, supersedes ID, UUID request ID를
  보낸다.
- stale/version/digest/supersession 409는 자동 보정·재저장하지 않고 refetch와 사람 재검토로
  안내한다.
- 과거 결정과 latest/currentness를 별도로 표시한다.
- `/opportunities/:opportunityId`에서 CTA를 연결하고
  `/opportunities/:opportunityId/bid-delta` route metadata와 뒤로 가기 query 문맥을 보존한다.

### R09-2. 기능 검증

`web/frontend/tests/bid-delta.spec.ts`에 다음을 고정한다.

- calculation `pending|running|completed|failed`
- result `changed|unchanged|unknown|failed`
- material/non-material/unknown과 7개 category
- 양쪽 evidence 및 근거 mismatch/absence 안전 표시
- 결정 미저장, 저장, append-only 과거 이력, stale currentness
- 404/409/422/503 typed error와 retry 가능 여부
- 사업기회 상세 → delta → 저장 → 뒤로 가기
- actor, request ID, exact fence payload
- keyboard focus, live feedback, 390/768/1024/1440px

검증 순서:

```bash
cd /home/jechoi/projects/bidops/web/frontend
npm run build
npx playwright test tests/bid-delta.spec.ts --project=desktop
npx playwright test tests/bid-delta.spec.ts
```

R-09 완료 전에는 route를 production 기능으로 표시하거나 R-11 snapshot을 승인하지 않는다.

## 8. R-11 — 통합 회귀·시각 기준선·bundle 분할

R-01~R-10의 현재 코드와 테스트를 다시 확인하고 R-09가 완료된 뒤 시작한다.

### R11-0. 기준선

1. 같은 Node/npm 환경에서 `npm run build`를 실행하고 초기 chunk와 gzip 크기를 기록한다.
2. 실제 `visual.spec.ts` target 수와 Playwright project 수로 현재 snapshot 수를 다시 센다.
   작성 시점 관측은 12 target × 4 viewport = 48개이며 과거 문서의 24개를 믿지 않는다.
3. 기존 snapshot diff를 사람 눈으로 분류하기 전 `test:visual:update`를 실행하지 않는다.

### R11-1. 구현

- opportunity, pre-spec, document preparation, deep-review, bid-delta의 결정적 fixture를 사용한다.
- delta의 pending/running/completed/failed와 changed/unchanged/unknown/failed를 포함한다.
- 날짜, request ID, polling 시각은 fixture로 고정한다.
- `routes.tsx`의 정적 page import를 route 단위 lazy import로 분할한다.
- loading/error state와 FastAPI SPA fallback을 유지한다.
- 수정 전후 chunk/초기 전송량을 같은 환경에서 기록한다.

### R11-2. 승인과 전체 회귀

1. 대상 spec desktop
2. 대상 spec 네 viewport
3. snapshot diff 수동 검토
4. 의도된 target만 제한 갱신하고 각 파일의 이유 기록
5. 전체 `npm run test:visual`
6. production build 재실행과 bundle 수치 기록

`./web/run-web-tests.sh`는 Playwright 전체를 대신하지 않는다. 전체 visual 결과, 의도적 skip,
갱신한 snapshot 목록과 이유가 없으면 R-11을 완료로 기록하지 않는다.

## 9. 공통 안전·중단 조건

다음이면 관련 구현을 즉시 중단한다.

- 사용자 파일의 허용 경로 이탈, 원문·회사자료·비밀·객체 path 노출
- 승인되지 않은 외부 모델 전송 또는 hosted fallback 필요
- 기존 document/attempt/item/evidence/final decision row 덮어쓰기
- `unknown|null|failed`를 성공·없음·unchanged로 바꾸는 경로
- 시스템 delta가 사람 최종 결정을 자동 생성·수정하는 경로
- actor 이름을 인증·권한으로 표현해야만 구현 가능한 요구
- backend 계약 없이 frontend mutation이나 production route를 먼저 만들어야 하는 상황
- 현재 사용자 diff를 보존할 수 없는 파일 충돌
- 실제 PostgreSQL 검증 없이 DB 작업을 완료로 기록해야 하는 상황

외부 모델, 실제 나라장터, 운영 DB·MinIO, scheduler/always-on은 이 계획의 검증에서 호출하거나
활성화하지 않는다. 구조적 문제는 재현 조건과 영향을 `docs/tracking/findings.md`에 기록한다.

## 10. 문서·Git·세션 종료

작업 완료 시 함께 갱신할 문서:

- `docs/review/2026-08-31-ui-ux-remediation-plan.md` 10.13 실행 기록
- `docs/tracking/status.md`
- `docs/tracking/lifecycle-workstream.md`
- 계약이 구현과 달라졌다면 먼저 구현을 멈추고 ADR/계약 결정 절차를 다시 연다.
- 운영·보안 경계가 바뀌었으면 `docs/security.md`, `docs/operations.md`, `docs/contracts.md`

검증 마지막에는 다음을 실행한다.

```bash
git status --short
git diff --stat
git diff --check
```

생성물, 실험 원문, 비밀, 로컬 DB, Playwright 임시 산출물을 범위에 섞지 않는다. commit·push는
사용자가 명시적으로 요청한 경우에만 수행하고, 그때도 현재 작업과 무관한 dirty 파일을
포함하지 않는다.

종료 보고 형식:

```text
작업 ID: <S-00|R08-x|R09-x|R11-x>
기준 HEAD: <short sha>
진입 gate: <충족 근거>
기존 겹침: <없음 | 파일과 보존 방법>
서브에이전트: <task/파일 소유권/결과>
변경 파일: <목록>
완료 기준: <충족/미충족과 근거>
검증: <실행한 정확한 명령과 결과>
미실행 검증: <없음 | 이유>
남은 위험: <내용>
다음 가능 작업: <ID | 승인/정리 필요>
```

