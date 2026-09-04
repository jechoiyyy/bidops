# BidOps 발주계획 C-2 선별 구현 계획

| 항목 | 내용 |
|---|---|
| 문서 상태 | 초안 — 착수 순서와 검증 게이트 |
| 문서 버전 | v0.2 |
| 기준일 | 2026-09-02 |
| 요구사항 | [PRD.md](PRD.md) |
| 채택 결정 | [ADR-0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md) |

이 계획은 `BM25 Top 300 + Qwen`을 scheduler 없이 수동 실행 가능한 제품 기능으로 만드는
순서를 정의한다. 각 단계는 앞 단계의 계약과 검증 증거를 입력으로 사용한다. 코드가 있다는
사실과 운영 활성화를 구분하며, 품질 승인 전에는 scheduler·always-on을 연결하지 않는다.

## 1. 구현 원칙

- 수집·선별·병합 skill은 subprocess와 versioned file 계약으로 연결한다.
- FastAPI가 skill 내부 함수를 import하거나 동일한 BM25·병합 규칙을 다시 구현하지 않는다.
- `OrderPlan`·`OrderPlanObservation`을 재사용하되 발주계획 relevance를 기존 공고
  `Judgment`·등급·준비 상태에 넣지 않는다.
- 전체 모집단, stage1 점수·순위·탈락, stage2 결과·실패를 모두 보존한다.
- 실행 입력과 정책·prompt·모델·회사 역량 binding은 enqueue 시점에 고정한다.
- 모델 호출은 active slot 1, batch size 25를 유지하고 hosted fallback을 만들지 않는다.
- 사람 리뷰와 정책 승인 전이는 app 역할, 모델 attempt와 machine result 전이는 worker 역할의
  최소 권한으로 분리한다.
- 앱 startup, migration, image build는 policy seed·activation, 수집, 모델 호출을 수행하지 않는다.
- scheduler와 always-on은 Phase 6 전까지 수정하거나 연결하지 않는다.

## 2. 단계 요약

| 단계 | 목표 | 주요 산출물 | 완료 게이트 | 현재 |
|---|---|---|---|---|
| Phase 0 | 미확정 정책과 계약 고정 | ADR, 파일·REST·DB 명세, 승인 입력 manifest | 사람 승인과 hash 확정 | 완료 — ADR-0038 |
| Phase 1 | 결정적 BM25와 결과 병합 생산자 | `skills/bidops-screen` CLI·schema validator | skill·루트 파이프라인 테스트 | 완료 — `c55fca8` |
| Phase 2 | 불변 DB 저장과 적재 | SQLAlchemy model, Alembic, loader, runtime privilege | 임시 PostgreSQL 17 검증 | 구현 완료 — `c136dfd`; loader 회귀 1건이 P5-0에 남음 |
| Phase 3 | 수동 실행 API와 Qwen worker | execution service, queue, vLLM adapter, telemetry | fake E2E와 명시적 live smoke | 구현 완료 — `aaaef22`; live smoke 미실행 |
| Phase 4 | 발주계획 검토 화면 | 누적 목록, 실행 상세, 필터, 사람 피드백 | TypeScript build·visual 회귀 | 완료 — `da508e0` |
| Phase 5 | 품질 gate와 수동 운영 승인 | human gold 평가, policy candidate·activation | 명시적 운영 승인, 자동 실행 없음 | 착수 대상 |
| Phase 6 | 고도화: scheduler | 일일 수집·선별 예약, catch-up, 월·목 검토 흐름 | 별도 ADR·운영 검증 뒤 opt-in | 대기 |
| Phase 7 | 생애주기 확장 | 사전규격 독립 수집·연결·delta 추적 | 단계별 별도 계약과 사람 결정 | 대기 |

Phase 2~4의 통합 보정 커밋은 `5e58f20`, `3ce0dcf`이며 `5e58f20`이 만든 migration 회귀 1건도
P5-0에 남아 있다. 구현 완료는 게이트 통과와 같은 뜻이 아니다.

## 3. Phase 0 · 정책과 계약 고정

### 목표

코드가 상태와 의미를 먼저 결정하지 않도록 PRD의 미확정 항목을 문서와 불변 입력으로 고정한다.

### 작업

1. C-1 잔여 사람 gold 판정을 완료하고 gold artifact와 SHA-256을 확정한다.
2. 다음 내용을 포함하는 C-2 운영 정책 초안을 만든다.
   - `top_k=300`
   - BM25 정규화·tokenization·tie-break
   - Qwen batch size 25
   - 검토 유지 label `relevant|uncertain`
   - 모집단 300건 이하 처리
   - 탈락 감사 표본 선정·검토 규칙
   - batch 재시도와 실행 상태 계산
3. 사람 피드백의 relevance·우선순위·메모와 revision 규칙을 확정한다.
4. 발주계획 선별 전용 파일 계약을 정한다.
   - frozen input
   - BM25 ranking
   - Qwen decisions·failures·telemetry
   - merged full-population result
5. 수동 실행 REST, 오류 code, idempotency, artifact 조회 경로를 정한다.
6. DB table과 불변/append-only 경계를 정하고 migration 명세를 작성한다.
7. 승인된 prompt v3와 회사 역량 v1은 `review-inputs/manifest.json`으로 상태와 hash를 검증한다.
8. 결정 내용을 새 ADR로 채택하고 `docs/contracts.md`, `docs/business-rules.md`에 반영한다.

### 완료 조건

- 모든 새 JSON에 schema version, producer, consumer, 필수 key와 상태 enum이 있다.
- `unknown`, `null`, 실패, 탈락의 의미가 서로 구분된다.
- 모델·prompt·회사 역량·BM25 config·generation config·gold의 digest가 확정된다.
- 운영 활성화 기준과 미측정 값이 문서에서 구분된다.
- scheduler 관련 결정을 이 단계의 blocker로 두지 않는다.

### Phase 0 실제 산출물과 미완료 경계

위 작업 중 사람의 명시적 결정이 필요한 C-1 gold 완료, 탈락 감사 표본 크기·주기 승인,
quality threshold 승인, 운영 policy activation은 이 작업에서 추정하지 않는다. 현재 상태는
`valid_but_blocked`다. 다음 산출물은 그 경계를 보존한 채 Phase 1~5 구현의 입력 계약을 고정한다.

| 작업 | 현재 산출물 | 현재 판정 |
|---|---|---|
| 1. C-1 gold | `gold-adjudicated-v2/review/manifest.json`, full/remaining SHA-256 | 부분 사람 판정 22, draft 603, 잔여 확인 87; 완료·활성화 부적격 |
| 2. C-2 운영 정책 | `experiments/order-plan-screening/config/order-plan-screening-policy.v1.json` | BM25/Qwen/batch/retry/execution/감사 표본 규칙 고정, `draft`·audit 승인 대기 |
| 3. 사람 feedback | policy `feedback`와 `bidops.order-plan-screening-feedback.v1` | relevance·priority·memo·append-only revision 고정; 다른 판단 축과 분리 |
| 4. 전용 파일 | `skills/bidops-screen/contracts/`의 input/ranking/decisions/failures/telemetry/result/feedback schema | 기존 notice v2/v3와 분리, 새 v1만 사용 |
| 5. 수동 REST | `docs/contracts.md` C-2 REST 표 | Phase 3 구현 경로·오류·idempotency만 고정; 현재 endpoint는 아직 미구현 |
| 6. DB | `docs/contracts.md` C-2 DB·migration 경계 | 전용 table/불변성/role/`0016` 경계 고정; Phase 2 migration은 미구현 |
| 7. 승인 입력 | `review-inputs/manifest.json`와 기존 approved v1/v3 hash | active 입력 검증 완료; prompt/profile 본문은 노출·소급 수정하지 않음 |
| 8. ADR | [ADR-0038](tracking/decisions/0038-order-plan-c2-phase0-contracts.md) | 계약 채택, 운영 활성화 승인은 별도 blocker |

검증 진입점은 다음과 같다. exit 0은 계약이 유효하다는 뜻이고, 출력의 `execution_allowed=false`,
`activation_allowed=false`와 blocker를 함께 확인해야 한다.

```bash
python3 skills/bidops-screen/scripts/validate_order_plan_phase0.py
```

## 4. Phase 1 · 선별 파이프라인 제품화

### 목표

실험 코드를 런타임에서 직접 참조하지 않고, versioned file을 생산·검증하는 제품 파이프라인을
만든다.

### 예상 변경 파일

신규:

- `skills/bidops-screen/scripts/rank_order_plans_bm25.py`
- `skills/bidops-screen/scripts/build_order_plan_screening_results.py`
- `skills/bidops-screen/tests/test_rank_order_plans_bm25.py`
- `skills/bidops-screen/tests/test_build_order_plan_screening_results.py`

필요 시 수정:

- `skills/bidops-screen/AGENTS.md`
- `skills/bidops-screen/SKILL.md`
- `run-tests.sh`

실험 증거인 `experiments/order-plan-screening/` 산출물은 소급 수정하지 않는다. 재사용할 순수
로직은 제품 모듈로 옮기고 실험은 기존 hash와 결과를 보존한다.

### 구현 내용

1. `collected-order-plans.v1`에서 plan ID와 제목을 읽고 전체 모집단을 검증한다.
2. 승인 config로 BM25 점수·근접 역량·결정적 순위를 계산한다.
3. 상위 300과 탈락을 모두 포함한 ranking artifact를 만든다.
4. backend worker가 만든 Qwen decisions·failures·telemetry를 strict schema로 검증한다.
5. ranking과 Qwen 결과를 전체 모집단 기준 merged artifact로 결합한다.
6. 누락·중복·다른 binding·다른 모집단·일부 결과의 성공 위장을 거부한다.

### 테스트

- Unicode NFKC와 공백 정규화
- 같은 입력의 byte-stable 결과
- 동점 tie-break
- 정확한 Top 300과 325개 탈락 fixture
- 모집단 300건 이하 정책 경계
- Qwen 대상이 아닌 plan의 Qwen 결과 유입 차단
- batch ID 누락·중복·부분 실패
- 전체 모집단 합계 불일치와 binding hash 불일치

### 완료 조건

```bash
python3 -m unittest discover -s skills/bidops-screen/tests -p 'test_*.py' -v
./run-tests.sh
```

두 명령이 통과하고 같은 fixture의 산출물 hash가 반복 실행에서 일치해야 한다.

## 5. Phase 2 · DB와 적재

### 목표

발주계획 정본과 별도로 실행·stage 결과·attempt·사람 피드백을 불변 또는 append-only로
저장한다.

### 예상 변경 파일

- `web/backend/app/screening/models.py`
- `web/backend/alembic/versions/0016_order_plan_screening.py`
- `web/backend/app/lifecycle/ingest/contracts.py`
- `web/backend/app/lifecycle/ingest/loader.py`
- `web/backend/app/screening/ingest.py`
- `scripts/runtime-privileges.sql`
- `web/backend/tests/lifecycle/test_ingest_contracts.py`
- `web/backend/tests/app/test_ingest_loader.py`
- `web/backend/tests/app/test_db_migrations.py`
- `web/backend/tests/app/test_runtime_database_privileges.py`
- `web/backend/tests/app/test_alembic_autogenerate.py`

revision 번호는 구현 착수 시 현재 Alembic head를 다시 확인하고 조정한다.

### 권장 데이터 경계

| 개념 | 보존 내용 |
|---|---|
| policy | top-k, BM25·Qwen·prompt·profile binding, 감사·재시도 규칙, 상태 |
| execution | source run·population digest, 요청자, 상태, 시작·종료, 전체 집계 |
| result | execution+order plan별 stage1 점수·순위·상태와 optional Qwen 판정 |
| attempt/batch | model binding, batch 순서·크기, token·duration, 실패 code |
| human review revision | 모델 결과와 분리된 relevance·priority·note·claimed actor·시각 |

정확한 table 이름과 상태는 Phase 0 계약을 따른다.

### 불변성·migration 검증

- 빈 PostgreSQL 17에서 `upgrade head`
- 직전 revision에서 upgrade와 안전한 downgrade 경계
- FK, CHECK, unique, partial index와 append-only trigger
- 같은 artifact 재적재 no-op
- 같은 execution·plan의 다른 hash 충돌 시 전체 rollback
- 기존 `OrderPlanObservation`의 snapshot 불변성 보존
- app·worker·ro_backup 역할별 실제 table/column privilege
- Alembic autogenerate drift 없음

### 완료 조건

새 table이 명시적 권한 없이 runtime 역할에 노출되지 않고, 운영 DB가 아닌 폐기 가능한
PostgreSQL 17에서 migration·적재·재적재 검증이 모두 통과해야 한다.

## 6. Phase 3 · 수동 실행 API와 Qwen worker

### 목표

사람이 회차와 binding을 확인해 C-2를 실행하고, 요청과 분리된 worker가 완료·부분 성공·실패를
기록하게 한다. scheduler는 사용하지 않는다.

### 예상 변경 파일

신규:

- `web/backend/app/screening/services/order_plan_screening.py`
- `web/backend/app/screening/routers/order_plans.py`
- `web/backend/app/screening/schemas/order_plans.py`
- `web/backend/tests/screening/test_order_plan_screening_service.py`
- `web/backend/tests/app/test_order_plan_screening_api.py`
- `web/backend/tests/screening/test_order_plan_screening_worker.py`

수정:

- `web/backend/app/main.py`
- `web/backend/app/workers/analysis.py`
- `web/backend/app/screening/services/vllm_client.py` 또는 목적별 전용 adapter
- `web/backend/app/core/config.py`
- `docker-compose.t7.yml`
- `docker-compose.t7.remote-vllm.yml`
- `env/vllm.env.example`

### 구현 내용

1. 실행 생성 시 source run과 모든 binding을 DB·artifact에 고정한다.
2. actor, request ID, payload 허용 필드와 목적을 검증하고 감사 row를 같은 transaction에 남긴다.
3. 실행 생성은 모델 호출을 기다리지 않고 202와 execution ID를 반환한다.
4. 분석 worker는 active slot 1에서 job을 claim하고 BM25 subprocess를 먼저 실행한다.
5. worker는 Top 300을 순서가 고정된 25건 batch로 나눠 사설 vLLM에 보낸다.
6. vLLM client는 literal allowlist, `/v1` path, no redirect·proxy, model·revision 일치를 검사한다.
7. 각 batch 응답을 strict JSON으로 검증하고 token·duration을 attempt에 저장한다.
8. 모델 원응답은 reasoning을 제외하고 암호화된 versioned object로 저장한다.
9. 성공·실패 artifact를 선별 merge subprocess에 전달하고 검증된 결과만 DB projection에 반영한다.
10. stop·stale heartbeat·재시도는 제한된 상태 간선으로 처리하고 자동 resume하지 않는다.

### API 최소 범위

정확한 path는 Phase 0에서 확정하되 다음 기능이 필요하다.

- 누적 발주계획 목록과 최신 C-2 projection 조회
- 특정 발주계획의 관측·선별·사람 피드백 이력 조회
- source run 기준 수동 실행 생성
- 실행 목록·상세·중지
- decisions·failures·telemetry·merged result artifact 조회
- 사람 relevance 피드백 생성·수정 revision

### fake 검증

- 모델 호출 없는 deterministic fake adapter
- Top 300 이외 payload가 전송되지 않음
- 12개 batch × 25 성공, 마지막 partial batch
- timeout·truncated·malformed·ID 중복·model mismatch
- 한 batch 실패의 부분 성공과 나머지 결과 보존
- 다른 provider fallback이 호출되지 않음
- prompt·회사자료·API key·endpoint query가 로그·오류·감사에 없음
- stop, stale recovery, idempotent replay, 동시 실행 충돌

### live smoke 경계

live vLLM 호출은 코드 merge나 테스트 실행의 기본 단계가 아니다. 운영자가 endpoint, 대상 회차,
payload preview와 모델 revision을 명시적으로 승인한 단일 실행에서만 수행한다. 결과에는 입력·정책·
모델·prompt·회사 역량 digest와 시간·token을 남기고 본문은 일반 로그에 남기지 않는다.

### 완료 조건

- fake E2E가 scheduler 없이 수동 실행부터 DB 조회까지 완주한다.
- live smoke가 승인된 경우에만 별도 증거로 기록된다.
- model endpoint가 없거나 revision이 다르면 실행 전 또는 worker 단계에서 fail closed한다.

## 7. Phase 4 · 검토 화면

### 목표

기획 담당자가 누적 발주계획과 C-2 결과를 한 화면에서 검토하고, 모델 결과와 분리된 사람
피드백을 남길 수 있게 한다.

### 예상 변경 파일

신규:

- `web/frontend/src/pages/OrderPlansPage.tsx`
- `web/frontend/src/pages/OrderPlanDetailPage.tsx`
- `web/frontend/src/styles/order-plans.css`
- `web/frontend/tests/order-plans.spec.ts`

수정:

- `web/frontend/src/lib/api.ts`
- `web/frontend/src/lib/types.ts`
- `web/frontend/src/routes.tsx`
- `web/frontend/src/components/shell/Sidebar.tsx`
- `web/frontend/src/components/shell/route-meta.ts`
- `web/frontend/tests/api-mock.ts`
- `web/frontend/tests/visual.spec.ts`

### 화면 요구

- 기본 목록은 최신 성공·부분 성공 실행의 `relevant|uncertain`
- 전체, BM25 탈락, Qwen 비관련, 실패 필터
- 제목, 기관, 예산, 예정 시기, plan ID와 source run 표시
- BM25 rank·score·근접 역량과 Qwen relevance·score·사유 표시
- 실행 model·revision·prompt·profile·policy binding 요약
- batch 실패와 미측정 token·duration의 명확한 상태
- 사람 relevance·priority·note 입력과 revision history
- 모델 결과와 추적 상태·최종 결정의 의미가 다름을 화면에 명시

### 검증

```bash
cd web/frontend
npm run build
npm run test:visual
```

API mock은 성공, 부분 성공, 전체 실패, 결과 없음, `null` 계측, 장문 한글 제목을 포함한다.
지원 폭(laptop 1280px·desktop 1440px, 상한 1920px)에서 상태가 색만으로 구분되지 않는지
확인한다. 관리 화면은 데스크톱·노트북 전용이므로 모바일·태블릿 폭은 검증 대상이 아니다
([ADR-0047](design/ADR.md#adr-0047-데스크톱노트북-전용-지원-폭)).

## 8. Phase 5 · 품질 gate와 수동 운영 승인

### 목표

코드가 동작한다는 사실과 C-2를 실제 업무에 사용하는 결정을 분리한다.

### 착수 시점 사실 (2026-09-02)

- Phase 1~4는 커밋됐다. 구현 경로는 존재하지만 아래 세 가지 때문에 실데이터 실행과 품질 측정이
  아직 성립하지 않는다.
- 백엔드 전체 스위트 기준선은 **1076 passed, 5 skipped, 6 failed**다. 6건은 전체 2회 실행과
  건별 단독 재실행에서 동일하게 재현된 결정적 실패이며 부하 의존 flake가 아니다. 측정 시점에
  `web/`·`skills/`에 미커밋 변경은 없었다.
- Phase 0 validator는 여전히 `valid_but_blocked`이고 blocker는 `c1_gold_incomplete`,
  `audit_sample_policy_unapproved`, `quality_gate_not_measured`,
  `private_vllm_transport_requires_per_execution_approval` 넷이다.
- `order_plan_screening_policy` row를 만드는 운영 경로가 없다. 실행 API는
  `policy_status='active'`와 `quality_gate_status='passed'`를 함께 요구하므로 현재는 어떤
  실행도 성립하지 않는다. `docs/contracts.md`의 C-2 policy REST 3개는 계약만 있고 미구현이다.
- C-2 quality gate 결과를 저장할 자리가 없다. policy table에는 `quality_gate_status` 문자열
  한 칸뿐이고, 기존 `quality_gate`·`quality_gate_evaluation` table은 legacy 공고 screening
  전용(`purpose = model_comparison|operational_approval`)이다. 반면 활성화 요청 계약은
  `quality_gate_artifact_sha256`을 요구한다.

### P5-0 · 착수 전 정리

회귀를 안고 측정하면 측정 대상이 제품이 아니게 된다. 품질 측정 전에 닫는다.

1. **`0017` downgrade 호출 교정.**
   `web/backend/alembic/versions/0017_order_plan_screening_heartbeat.py:76`이
   `op.execute(sa.text(...), {params})`를 positional로 호출한다. Alembic 1.19.1의
   `Operations.execute(sqltext, *, execution_options=None)`는 두 번째 positional 인자를 받지
   않아 `TypeError`가 나고, 그 결과 **현재 head에서 downgrade가 한 단계도 진행되지 않는다.**
   같은 파일 upgrade 경로의 `op.get_bind().execute(...)`는 정상이므로 호출 형태만 맞춘다.
   이 한 건이 migration 회귀 4건의 공통 원인이다.
2. **legacy v3 회차를 C-2로 오인하는 분기 교정.**
   `web/backend/app/screening/ingest.py`의 `c2_specific_sibling_present`가
   `screening-ranking|failures|telemetry|feedback.json`의
   **존재만으로** C-2로 분기한다. legacy v3 worker(`web/backend/app/screening/worker.py:580`)가
   같은 이름의 `screening-failures.json`을 쓰므로, 부분 실패한 기존 v3 회차가
   `C-2 source_run_id is missing`으로 적재에 실패한다. 판별을 같은 함수의
   `c2_decisions_present`처럼 `schema_version` 기준으로 통일한다. 이것이 screening
   orchestrator 회귀 2건의 원인이다.
3. **재발 방지 회귀 테스트.** head→`0016` downgrade 왕복과, legacy v3 부분 실패 회차의 적재를
   각각 고정한다.
4. **기록 정정.** `docs/validation-runs/20260902-order-plan-c2-phases2-4.md`는 남은 실패를
   "8건이며 Phase 2~4 변경 경로가 아니다"라고 적었으나 그 구성은 재현되지 않았다. 실제는 6건이고
   전부 이번 변경이 원인이다. 실행 수치와 귀속을 사실대로 정정한다.
5. **상태 갱신.** `docs/tracking/status.md`의 C-2 행, Alembic head(`0017`), 백엔드 기준선
   수치를 현재 사실로 맞춘다.

완료 조건: `./run-tests.sh`와 `web/run-web-tests.sh`의 백엔드 구간이 실패 0건이고, downgrade
왕복이 임시 PostgreSQL 17에서 실측으로 통과한다.

### P5-1 · 사람 결정

측정 자체가 이 결정들에 종속된다. 정해지기 전까지 값은 `null`로 두고 추정하지 않는다.

| ID | 결정 | 현재 값 | 없으면 막히는 것 |
|---|---|---|---|
| D-a | gold를 언제 "승인된 사람 gold"로 볼 것인가 | 사람 22 / draft 603 / 잔여 확인 87 | P5-3의 채점 입력 |
| D-b | quality gate 임계값 `recall`·`precision`·`important_missed_max`·`review_load_max` | 넷 다 `null` | 통과·미달 판정 자체 |
| D-c | 감사 표본 `sample_size`·`review_cadence`·`enabled` | `null`, `pending_human_approval` | BM25 탈락 감사 |
| D-d | 사설 vLLM 전송 승인(D-7 방화벽)과 model artifact digest 고정 | `not_allowed_for_product_runtime` | 반복 실행 측정, live smoke |
| D-e | 활성화 승인 주체·절차와 audit 기록 범위 | 미정 | P5-4 |
| D-f | 채점 대상을 기존 실험 산출물로 할 것인가, 제품 파이프라인 재실행 결과로 할 것인가 | 미정 | P5-3 전체의 성격 |

참고 실측(625건, 방식 선택 근거이며 목표치가 아니다): 검토 유지 recall 96.61%,
precision 44.88%, 사람 검토 후보 127건, BM25 누락 2건.

D-f를 "제품 재실행"으로 정하면 P5-3 전체가 D-d에 종속된다. "기존 산출물 재채점"으로 정하면
지금 측정할 수 있지만 그 결과는 제품이 낸 결과가 아니므로 gate artifact에 그 사실을 남긴다.

### P5-2 · 구현

임계값이 없어도 구조는 fail-closed로 만들 수 있다. P5-1과 병행한다.

1. **policy 등록 경로.** 승인된 policy 파일을 digest 그대로 `draft`로 적재하는 명시적 경로를
   만든다. 앱 startup, image build, migration은 이 일을 하지 않는다.
2. **policy REST 3개 구현.** `GET /api/order-plan-screening/policies/{policy_version}`,
   `POST .../policies/candidate`, `POST .../policies/{policy_version}/activate`.
   `activation_allowed=false`인 동안 활성화는 `activation_blocked(409)`로 닫혀 있어야 한다.
3. **quality gate 산출물의 저장 계약 확정.** artifact와 digest를 어디에 두는지 정하고
   `policy_status`·`quality_gate_status` 전이와 append-only audit을 함께 고정한다. legacy
   `quality_gate` table을 재사용하지 않는다면 그 이유를 계약에 남긴다. migration `0018`의
   필요 여부는 이 결정에서 나온다.
4. **감사 표본 선정기.** policy의 strata, 선정 순서, 무복원 규칙을 결정적으로 구현한다. 현재
   규칙은 문서와 policy 파일에만 있고 실행 코드가 없다.
5. **활성화 화면.** 후보 policy, exact binding, gate 결과, 남은 blocker를 사람이 확인하고
   명시적으로 승인하는 동선. `미측정`과 `미달`을 다른 표면으로 구분하고, 승인 전에는 활성
   정책처럼 보이지 않게 한다.

### P5-3 · 측정

1. 승인된 사람 gold로 고정 모집단을 다시 채점한다.
2. recall, precision, review load, 중요 누락, BM25 rank 분포, 시간·token을 계산한다.
3. accepted-stage1-misses와 새 중요 누락을 함께 검토한다.
4. 같은 binding 반복 실행으로 batch 안정성과 판정 변동을 측정한다.
5. 감사 표본에서 BM25 탈락의 관련 건수를 사람 판정으로 확인한다.

산출물은 임계값 대비 `통과`·`미달`·`미측정`을 구분한 gate artifact 하나다. 실패와 미측정을
0이나 `not_relevant`로 보정하지 않는다.

### P5-4 · 활성화

6. 결과가 D-b 기준을 통과하면 policy를 activation candidate로 지정한다.
7. 운영자가 exact gate·policy·prompt·model·profile binding을 확인하고 수동 활성화한다.

### 활성화 뒤에도 유지할 경계

- 실행 버튼은 사람이 눌러야 한다.
- scheduler와 always-on은 비활성이다.
- 정책 활성화가 곧 모델 호출은 아니다.
- 실패를 다른 provider 호출로 복구하지 않는다.
- 사람의 최종 추적·입찰 결정은 별도다.

### 완료 조건

- P5-0의 회귀가 0건이고 downgrade 왕복이 실측으로 통과한다.
- 품질 평가 artifact, 사람 review, activation audit가 정확한 binding에 연결된다.
- 임계값 미달과 미측정이 활성화를 자동으로 막는다.
- scheduler 없이 대표 회차를 수동으로 실행·검토할 수 있다.

## 9. Phase 6 · 고도화: scheduler

이 단계는 MVP와 분리한다. Phase 0~5가 완료되고 수동 운영에서 실행시간·API 호출량·실패율을
관측한 뒤 별도 ADR과 변경 계획으로 착수한다.

### 선행 조건

- active C-2 policy와 통과한 operational quality gate
- 수동 실행에서 확인한 요청 수, token, duration, 실패·재시도 분포
- 나라장터 API 할당량과 700회 경고·900회 신규 호출 중지 정책 검증
- 모델 endpoint와 host firewall 운영 승인
- backup·restore와 stale execution 복구 훈련
- scheduler actor·audit·중복 예약·catch-up 계약 확정

### 목표 동작

- 발주계획은 최근 21일 창을 매일 독립 수집한다.
- 원본 수집과 C-2 실행을 별도 상태로 기록하고 부분 수집이면 선별을 시작하지 않는다.
- 월요일·목요일에는 누적 미검토 후보를 사람이 볼 수 있게 하되 수집 자체는 매일 유지한다.
- 동일 source run·policy의 중복 실행은 idempotency 규칙으로 건너뛴다.
- 누락 기간 복구는 새 execution으로 남기고 과거 회차를 덮지 않는다.
- 환경 cap과 DB switch가 모두 켜지고 exact quality binding이 일치할 때만 effective enabled가 된다.
- 앱 startup은 밀린 실행을 임의로 시작하지 않는다.

### 예상 변경 영역

- `web/backend/app/screening/services/scheduled_pipeline.py`
- `web/backend/app/screening/services/scheduler.py`
- `web/backend/app/screening/runtime.py`
- `web/backend/app/screening/routers/schedule.py`
- schedule schema·models·migration 또는 기존 계약의 versioned 확장
- `docker-compose.t7.yml`과 목적별 egress overlay
- 운영 화면의 schedule 상태·복구 UI
- `docs/operations.md`, `docs/contracts.md`, 별도 scheduler ADR

MVP 구현 중에는 위 파일을 C-2 자동 실행 목적으로 수정하지 않는다.

## 10. Phase 7 · 생애주기 확장

C-2 이후에는 기존 생애주기 계획에 따라 다음을 별도 단위로 진행한다.

1. 사전규격 독립 일일 수집과 누적 화면
2. 발주계획·사전규격 공식 관계와 사람 확인 대기 후보
3. 저비용 사전규격 선별과 사람 심층 검토 승인
4. `계속 추적|보류|종료` 선택과 입찰공고 발견
5. 사전규격 대비 material delta와 사람 최종 Go/No-Go

C-2 relevance를 이 단계의 적합성·준비·추적·최종 결정으로 자동 변환하지 않는다.

## 11. 통합 검증과 완료 정의

각 phase의 집중 테스트 후 현재 worktree에서 최소 다음을 수행한다.

```bash
./run-tests.sh
./web/run-web-tests.sh
cd web/frontend && npm run test:visual
COMPOSE_PROJECT_NAME=bidops-verify docker compose -f docker-compose.t7.yml build
COMPOSE_PROJECT_NAME=bidops-verify docker compose -f docker-compose.t7.yml config
```

live endpoint 호출은 이 목록에 포함하지 않는다. 별도 승인된 smoke 명령과 결과로 기록한다.

기능 완료는 다음을 모두 만족할 때다.

- 코드, 파일·REST·DB 계약, migration, 권한, 운영 문서가 같은 version을 설명한다.
- 전체 모집단에서 stage1·stage2·실패·사람 검토 상태의 합계가 일치한다.
- 동일 입력 재실행, 부분 실패, 중지, stale recovery와 idempotency가 검증된다.
- 비밀·prompt·회사자료·모델응답 본문이 Git·로그·오류·감사에 없다.
- 수동 실행과 검토가 scheduler 없이 완주한다.
- 품질 미승인 상태가 화면과 API에서 활성 정책처럼 보이지 않는다.

## 12. 현재 상태

기준일 2026-09-02. `구현됨`은 코드와 계약이 있다는 뜻이고 게이트 통과와 같은 뜻이 아니다.

| 항목 | 상태 |
|---|---|
| C-2 방식 선택 | 완료 — ADR-0037 |
| 기준 실험 | 완료 — 625건, Qwen 300건, batch 12개 |
| 알려진 BM25 누락 기록 | 완료 — 2건 수용 기록 |
| 승인 prompt v3·회사 역량 v1 관리 | 완료 — review-input manifest와 hash |
| 제품 파일 계약과 생산 pipeline | 구현됨 — Phase 0 schema·validator, Phase 1 생산자 |
| DB execution·result 계약과 적재 | 구현됨 — `0016`·`0017`, loader, runtime privilege |
| 수동 API·worker | 구현됨 — 실행·중지·artifact·telemetry, live smoke 미실행 |
| 검토 화면 | 구현됨 — 누적 목록, 실행 상세, 필터, 사람 feedback |
| 백엔드 전체 스위트 | 1076 passed, 5 skipped, **6 failed**; 6건 모두 Phase 2~4 경로의 결정적 회귀 |
| head에서의 downgrade | 불가 — `0017` downgrade가 `TypeError`로 즉시 실패 |
| C-2 policy 등록·candidate·활성화 | 미구현 — 운영 경로 없음. 현재 실데이터 실행은 성립하지 않음 |
| quality gate 산출물 저장 자리 | 미정 — C-2 전용 저장 계약 없음 |
| 감사 표본 선정기 | 미구현 — 규칙만 문서·policy에 존재 |
| C-1 사람 gold 잔여 확인 | 사람 결정 대기 — 22 human / 603 draft / 87 remaining |
| threshold·감사 표본 정책 | 계약 초안 고정 — 사람 승인 대기 |
| 사설 vLLM 전송 | 승인 대기 — `not_allowed_for_product_runtime` |
| scheduler 연결 | 고도화 단계로 보류 |

다음 착수점은 P5-0이다. 회귀 6건과 downgrade 불가를 닫고 잘못 기록된 기준선을 정정한 뒤,
P5-1의 사람 결정과 P5-2의 구현을 병행한다. 측정(P5-3)은 D-a~D-d가 정해진 뒤에 시작한다.
scheduler 설계는 이 착수점에 포함하지 않는다.
