# 일일 운영 고도화 — 계획

- 상태: 구현 중(2026-09-18 착수). fable 검토·2차 검토 인터뷰(결정 10~27)·M0 결과(결정 28)를 반영했다. 의도는 [`intent.md`](intent.md), 동작은 [`spec.md`](spec.md).
- 기준 트리: `main` 6191f35. 이 계획이 건드리는 파일을 수정하는 미병합 브랜치는 없다.
- 구현은 **opus·sonnet 서브에이전트**에 위임한다. 작업 패키지마다 모델을 정했다(§1, 기준은 §6).

## 1. 작업 패키지

### 1.0 한눈에

파일 소유가 겹치지 않게 나눴다. 같은 파일을 두 패키지가 만지는 경우는 **웨이브를 달리해** 뒤 패키지가 앞 패키지의
통합 결과에서 출발한다. `S7`·`S10`·`S12` 번호는 참조 안정성을 위해 비워 두거나 §7로 옮겼다.

| ID | 내용 | 모델 | 웨이브 | 선행 | 파일 소유 (요약) |
|---|---|---|---|---|---|
| M0 | 늦은 색인 측정(발주계획·공고) — **완료**, 사전규격 공개 지연 발견 → 결정 28 | 리더 직접 | 0 | 사용자 승인 | `docs/validation-runs/20260918-late-indexing.md` |
| S1a | 계약·ADR 문안 | **opus** | 1 | — | `docs/tracking/decisions/**`, `docs/ADR.md`, `docs/contracts.md` |
| S1b | 수집 창·적재 순서 서술 치환 | **sonnet** | 1 | — | `docs/business-rules.md`, `docs/ARCHITECTURE.md`, `docs/operations.md`, `docs/model-quality-gate.md`, `skills/bidops-collect/AGENTS.md`, `docs/tracking/lifecycle-workstream.md` |
| S1c | `docs/PLAN.md` 개정·findings 정리 | **opus** | 1 | — | `docs/PLAN.md`, `docs/tracking/findings.md` |
| S0 | 설정 배선(기본값 전부 꺼짐) | **sonnet** | 1 | — | `app/core/config.py` |
| S2 | Alembic `0029` + 권한 | **opus** | 1 | — | `alembic/versions/0029_*.py`, `app/screening/models.py`, `scripts/runtime-privileges.sql`, `app/core/db.py` |
| S9a | 일일 스크립트: 트랙 분리·전일 기준·발주계획 1일·공고 4일 창·`--collect-only` | **sonnet** | 1 | — | `scripts/run-daily-lifecycle.sh` |
| S3 | policy 적재 CLI | **opus**(착수 때 변경 — C-1 `load_policy_file`이 C-2에 안 맞고 권한·guard 판단이 섞임) | 2 | S2 | `app/screening/c2_policy.py`(신규) |
| S4a | policy REST·활성화 | **opus** | 2 | S2 | `services/order_plan_policy.py`·`routers/order_plan_policies.py`(신규), `schemas/order_plans.py`, `app/main.py` |
| S4c | 일일 자동 실행 스위치 서비스·REST (착수 때 S4a와 한 패키지로 합침 — 파일 digest·전송 승인 판정 공유) | **opus** | 2 | S0·S2 | `services/order_plan_daily_trigger.py`·`routers/order_plan_daily_trigger.py`·`schemas/order_plan_daily_trigger.py`(신규) |
| S5a | 품질 게이트 저장소·REST·판정 규칙 | **opus** | 2 | S2 | `services/order_plan_quality_gate.py`·`routers/order_plan_quality_gates.py`·`schemas/order_plan_quality_gates.py`(신규) |
| S5b | gold 게시일별 분할 도구 | **sonnet** | 2 | — | `skills/bidops-collect/scripts/split_order_plan_run_by_day.py`(신규) |
| S6 | 감사 표본 산출 | **opus** | 2 | S2 | `services/order_plan_audit_sample.py`·`routers/order_plan_audit_sample.py`(신규) |
| S8a | 누적 투영 백엔드 | **opus** | 2 | S2 | `services/order_plan_screening.py`(목록 함수만), `app/screening/projection.py` |
| S11 | GPU 휴지(연속 가동 시간 기준) | **sonnet** | 2 | S0 | `app/workers/analysis.py`, `app/screening/worker.py` |
| S15 | 개요 run 중복 방지(결정 28) | **opus** | 2 | — | `app/deep_review/services/overview_runs.py`(`enqueue_overview_run`만), 신규 테스트 |
| S4b | 실행 게이트 수정(헤더·`purpose`·측정 경로·파일 status 제거) + router 등록 | **opus** | 3 | S4c·S5a·S8a | `services/order_plan_screening.py`(실행 생성 경로), `workers/order_plan.py`, `routers/order_plans.py`, `app/main.py` |
| S9b | 회차 조회·`-retryN`·단계별 따라잡기 | **opus** | 3 | S9a | `scripts/run-daily-lifecycle.sh`, `scripts/manual-workflow-common.sh` |
| S13a | 프런트 API·타입 배선 | **sonnet** | 3 | S4a·S4c·S5a·S8a | `web/frontend/src/lib/api.ts`, `lib/types.ts` |
| S16 | 참조 적재가 policy 행을 활성으로 만들지 못하게(ADR-0060, 착수 중 발견) | **opus** | 3 | — | `app/screening/ingest.py`(`_c2_policy_row`만), 테스트 |
| S9c | `run-daily-c2.sh` + 발주계획 트랙 연결·자동 draw | **opus** | 4 | S4b·S6·S9b | `scripts/run-daily-c2.sh`·`scripts/c2-execution-common.sh`(신규), `scripts/run-daily-lifecycle.sh` |
| S8b | 발주계획 화면: 누적 기본·버전/첫 관측일·배너 | **opus** | 4 | S8a·S13a | `pages/OrderPlansPage.tsx`, `tests/order-plans.spec.ts`, `tests/dashboard.spec.ts` |
| S13b | C-2 활성화 화면(기준 화면의 새 탭) | **opus** | 4 | S4a·S4c·S5a·S13a | `pages/OrderPlanPolicyPage.tsx`(신규), `pages/CriteriaPage.tsx`, 신규 spec·fixture |
| S5c | 게이트 측정 스크립트 | **sonnet** | 5 | S4b·S9c | `scripts/run-c2-gate-measurement.sh`(신규) |
| S14 | 운영 문서·상태 기록 마감 | **sonnet** | 5 | 전부 | `docs/operations.md`, `docs/tracking/status.md`, `web/backend/AGENTS.md`, `CLAUDE.md`·`AGENTS.md`(런타임 사실 절) |
| S3b | v3 policy·binding 발행·마운트 | **sonnet** | 사람 결정 뒤 | D-c 값·D-d 값, S3 | `experiments/order-plan-screening/config/*.v3.json`(신규), `docker-compose.yml`, `app/core/config.py`(기본 경로) |

opus 14개(S15 추가, 결정 28), sonnet 10개(+리더 1). 웨이브마다 통합·게이트·diff 검수는 리더가 한다(§6).

### M0 — 늦은 색인 측정 (리더 직접, 위임 없음)

| | |
|---|---|
| 목적 | 1일 창(결정 7·8)의 전제 확인. 같은 기준일을 D일과 D+2일에 수집해 id 집합을 비교한다. **발주계획과 공고 둘 다** 잰다([`spec.md` §9.4](spec.md)) |
| 방법 | 실 API를 부르므로 위임하지 않는다. S9a 전에는 수집기를 직접 부르고(`collect_order_plans.py`·`collect_notices.py --from-date X --to-date …`, 출력은 `data/experiments/late-indexing/…`), S9a 뒤에는 `--collect-only --run-suffix`를 쓴다. 적재하지 않는다 |
| 산출 | `docs/validation-runs/`에 기록 1건. 차이 0이면 1일 창 확정, 있으면 그 건수를 근거로 D-g 또는 결정 7을 다시 연다 |
| 시점 | S1과 동시에 시작한다. 구현 기간과 겹치므로 지연이 없다. 사용자 승인 뒤(실 API·키 사용) |

### S1a — 계약·ADR 문안 (opus)

| | |
|---|---|
| 목적 | 모순된 계약 위에 코드를 얹지 않는다 ([`spec.md` §1](spec.md)) |
| 파일 | `docs/tracking/decisions/` 신규 ADR 2건(다음 번호 `0060`·`0061`)과 개정 표기, `docs/ADR.md` 색인(`:111` ADR-0027 폐기, `:160` 서술), `docs/contracts.md` |
| ADR ① | **C-2 policy 활성 정본은 DB 행.** 파일 `policy_status`뿐 아니라 파일의 상태성 필드 전체가 발행 시점 스냅샷이며 어떤 게이트도 읽지 않는다(결정 18). blocker는 런타임 계산. 임계값 정본은 DB 게이트 행. 전송 승인 단위 = binding 튜플(결정 20)과 CLAUDE.md "승인된 payload만 건별 전송"의 관계 — payload 승인은 유지하고 승인 **행위**의 단위만 튜플이다. 일일 스크립트 actor 해석(결정 19). 측정 전용 실행(결정 22) |
| ADR ② | **발주계획·공고 일 단위 수집 전환.** ADR-0027 폐기, ADR-0059 결정 1의 "21일 재조회"·"3일 창" 개정, 발주계획→입찰공고 연결은 입찰공고 측 `orderPlanUntyNo`가 유일 경로. 근거에 `docs/tracking/findings.md:163`(21일 근거가 종단 관측에서 재현되지 않음)과 "세 회차 사이 재등장 0건"을 쓴다. 대가 명시 — 추적 중 발주계획의 변경 미관측(결정 16), 사전규격 등록 후 변경 미관측([`spec.md` §9.4](spec.md)) |
| contracts.md | C-2 절: 실행 게이트에서 파일 status 제거, 상태성 필드 스냅샷 선언, `X-BidOps-Trigger` 헤더, 신규 REST(policies 4·quality-gates 3·audit-sample 2·daily-trigger 2), `execution.purpose`, head 표기(`:1130`의 head `0017`은 낡음, 현재 `0028`) |
| 검증 | 문서·diff만. 앱 빌드·화면 테스트 없음 |
| 사람 결정 | 없음 (문안만). ADR 승인은 필요 |

### S1b — 수집 창·적재 순서 서술 치환 (sonnet)

| | |
|---|---|
| 파일·위치 | `docs/business-rules.md:103`("기존대로(21일 재조회)" → 전일 1일 창. 앞 판이 적은 `:38`은 오기다), `docs/ARCHITECTURE.md:244`(다이어그램 "발주계획 21일·사전규격/입찰 3일"), `docs/operations.md:471-473`(창)·`:476-480`("발주계획 → 공고 적재 순서 고정" → 트랙 분리)·`:489-492`(cron 예시 두 줄), `docs/model-quality-gate.md`에 "C-1 전용" 1문단, `skills/bidops-collect/AGENTS.md:57`(수집기 기본 창 서술과 일일 스크립트의 관계), `docs/tracking/lifecycle-workstream.md:93`(결정 표)·T-2b(종단 관측 과제 종료 표기) |
| 방식 | 치환 대상 문장과 새 문장을 프롬프트에 **그대로** 준다. 판단 여지를 남기지 않는다 |
| 검증 | diff만. `grep -rn "21일\|3일 창" docs skills`로 남은 서술 확인 |

### S1c — `docs/PLAN.md` 개정·findings 정리 (opus)

| | |
|---|---|
| PLAN.md (결정 17) | P5-2 ↔ 이 계획의 S3~S6·S13 연결(`migration 0018` 같은 낡은 표기 갱신). P5-1: D-f = 제품 재실행(측정 전용 실행)으로 닫음, D-a 권고안 = 풀링, D-b 판정 규칙, D-c 형태, D-d 승인 단위. Phase 5 "활성화 뒤에도 유지할 경계"의 **"실행 버튼은 사람이 눌러야 한다" → "사람 또는 사람이 옵트인한 일일 스크립트"**. Phase 6: `:475` "최근 21일 창" 삭제, 선행조건 중 유효한 것(수동 실행 관측·API 할당량·복구 훈련)을 일일 트리거 켜기 전 확인 항목(D-e)으로 옮기고 Phase 6에는 scheduler 통합만 남긴다 |
| findings.md | `:163` "ADR-0027의 21일 재조회 근거…" — ADR ②로 닫는다. 신규 기록(결정 26): ① 회사 핏은 `matched`가 아니면 심층 검토를 막는데 gold·임계값·게이트가 없고 `quality_status`가 `measured`가 될 수 없다 ② 사전규격 개요는 운영 중인데 표본 점검용 라벨을 담을 자리가 없고 수량·날짜 불일치 일부가 경고로 완화돼 있다 ③ C-1 수동 경로가 후보 policy를 받고 그 `제외`가 기본 목록에서 숨는다. 각 항목은 재현 조건·영향·지금 해결할 수 없는 이유·후속 방향을 쓴다([`intent.md` §6](intent.md)의 줄 번호를 근거로) |
| 검증 | 문서·diff만 |

### S0 — 설정 배선 (sonnet)

| | |
|---|---|
| 파일 | `app/core/config.py` |
| 내용 | `c2_daily_trigger_enabled`(`BIDOPS_C2_DAILY_TRIGGER_ENABLED`, 기본 False), `gpu_busy_limit_seconds`(`BIDOPS_GPU_BUSY_LIMIT_SECONDS`, 기본 0.0), `gpu_rest_seconds`(`BIDOPS_GPU_REST_SECONDS`, 기본 0.0). `:221`·`:231` 옆. 음수 거부 |
| 이유 | 설정 파일을 여러 패키지가 동시에 만지지 않게 먼저 한 번에 넣는다 |
| 검증 | 기본값·env 주입·음수 거부 단위 테스트. 기존 설정 테스트 통과 |

### S2 — Alembic `0029` + 권한 (opus)

| | |
|---|---|
| 파일 | `web/backend/alembic/versions/0029_c2_quality_gate.py`(신규), `app/screening/models.py`, `scripts/runtime-privileges.sql`, `app/core/db.py:103` `ALEMBIC_HEAD` |
| `down_revision` | `"0028_final_decision_basis"` |
| 내용 | [`spec.md` §2](spec.md) — 신규 **4테이블**(gate·evaluation·audit_sample·daily_trigger) + 실행 행 **`purpose` 열 1개**(기본 `operational`, 기존 행 backfill) + `quality_gate_status` UPDATE 권한. evaluation·audit_sample·daily_trigger는 append-only trigger |
| 재사용 | `models.py:807-867`(CheckConstraint·`dual()`), `models.py:603-626`(revision unique) |
| 검증 | 임시 PostgreSQL 17에서 head→`0028` downgrade 왕복 실측. `tests/app/test_db_migrations.py`, `test_runtime_database_privileges.py`. 임계값 NULL이면 `미측정`만 허용하는 CHECK, `purpose` CHECK |
| 사람 결정 | 없음 (구조만. 값은 NULL) |

### S3 — policy 파일 적재 CLI (sonnet)

| | |
|---|---|
| 파일 | `app/screening/c2_policy.py`(신규) |
| 내용 | [`spec.md` §3.1](spec.md). 파일의 상태성 필드 값은 검사하지 않고 DB 행은 항상 `draft` |
| 재사용 | `app/screening/policy.py:104` `_reject_duplicate_keys`, `:245` `load_policy_file`, `:321` `PolicyRepository.create` |
| 검증 | 2회 적재 no-op, 1 byte 바뀐 파일 거부, `policy_status='draft'`·`active_slot IS NULL`, digest가 파일 bytes 기준(canonical 아님), 파일 `policy_status`가 `active`여도 행은 `draft` |
| 사람 결정 | 없음 (draft 적재는 활성화가 아니다) |

### S3b — v3 policy·binding 발행·마운트 (sonnet, 사람 결정 뒤)

| | |
|---|---|
| 선행 | **D-c 값**(`max_per_execution`·`review_cadence`·`enabled`)과 **D-d 값**(`approved_by`·`approved_at`·model_digest). 값 없이 발행하지 않는다 |
| 파일 | `experiments/order-plan-screening/config/order-plan-screening-policy.v3.json`·`…-phase0-binding.v3.json`(신규. v2는 고치지 않는다), `docker-compose.yml:177-178,245-246`(마운트 파일명), `app/core/config.py:298-301`(기본 경로) |
| 내용 | [`spec.md` §1.1·§1.3·§5](spec.md) — `audit_sample.max_per_execution`, `external_transport.approval_scope="per_binding"` 등. 상태성 필드는 발행 시점 값으로 두되 `quality_gate.targets`는 null. binding `status`는 `activation_candidate` 또는 `approved`. binding의 `policy.sha256`은 새 policy 파일 bytes의 sha256 |
| 검증 | S3 CLI로 임시 DB에 적재 성공, `policy_file_missing` blocker가 사라짐, v2 파일 bytes 불변. digest는 리더가 직접 다시 계산해 대조한다 |

### S4a — C-2 policy REST·활성화 (opus)

| | |
|---|---|
| 파일 | `app/screening/routers/order_plan_policies.py`, `app/screening/services/order_plan_policy.py`(둘 다 신규), `schemas/order_plans.py`, `app/main.py` router 등록 |
| 내용 | [`spec.md` §3.2·§3.3](spec.md) — GET 단건·목록, candidate, activate. **blocker는 전부 런타임 계산**(payload blocker를 읽지 않는다). 활성화는 artifact digest로 evaluation을 특정하고 `product_rerun` gate만 받는다 |
| 재사용 | `policy.py:419-520` `PolicyRepository.activate` 순서 복제, `routers/policies.py:176-241`·`:60-69`, `services/order_plan_screening.py:235-249` `_idempotent` |
| 검증 | `tests/screening/test_c2_policy_api.py`(신규): 런타임 blocker 각각(`quality_gate_missing`·`quality_gate_not_passed`·`quality_gate_thresholds_undecided`·`audit_sample_policy_unapproved`·`execution_transport_not_allowed`·`binding_digest_mismatch`·`policy_file_missing`) → `activation_blocked`; payload에 `activation.blockers`가 남아 있어도 런타임 조건이 다 맞으면 활성화된다(GET과 POST의 답이 같다); `reference_artifact_rescore` gate의 `통과`로는 활성화 불가; digest mismatch 409; 같은 `request_id` 다른 body → `idempotency_conflict`; 활성화 후 이전 행 `retired`, audit 2행 |
| 사람 결정 | **D-e**(승인 주체·절차). 구조는 D-e 없이 구현 가능하고 *실제 승인 호출*만 D-e 뒤 |

### S4c — 일일 자동 실행 스위치 (opus)

| | |
|---|---|
| 파일 | `services/order_plan_daily_trigger.py`, `routers/order_plan_daily_trigger.py`, `schemas/order_plan_daily_trigger.py`(전부 신규). router 등록은 S4b가 한다 |
| 내용 | [`spec.md` §3.4](spec.md) — GET `effective_enabled`·`reasons[]`, POST append-only + audit. 다른 패키지가 부를 `effective_state(session, settings)` 함수 하나를 공개한다(S4b가 실행 생성 때 다시 검사) |
| 검증 | `tests/screening/test_c2_daily_trigger.py`(신규): 4중 조건 각각 off일 때 `effective_enabled=false`와 맞는 reason; active가 아닌 버전에 POST → `invalid_request`; policy 교체 뒤 `switch_bound_to_other_version`; 같은 `request_id` 재생; 행 UPDATE 불가 |
| 사람 결정 | 없음 (스위치를 켜는 것은 D-e) |

### S4b — 실행 게이트 수정 + router 등록 (opus)

| | |
|---|---|
| 파일 | `services/order_plan_screening.py`(`_policy_binding`·`create_execution`만 — 목록 함수는 S8a가 끝낸 상태에서 출발), `workers/order_plan.py:265`(삭제)·`:274`(허용값 확대 + `blocked`∧`execution_allowed` 거부)·`:282`(상호 일치만), `routers/order_plans.py`(헤더 파싱), `app/main.py`(S4c·S5a·S6 router 등록) |
| 내용 | [`spec.md` §1.1·§1.2·§1.3·§4.1](spec.md) — payload status 검사 삭제(`:262`); `X-BidOps-Trigger` 헤더 → `trigger` 인자·`safe_metadata.trigger`; `daily_script`·`manual_resume`이면 S4c `effective_state` 재검사; `gate_measurement`면 `activation_candidate\|active` 허용 + `source_run_id`가 gate의 측정 회차 + `purpose='gate_measurement'` |
| 검증 | `test_order_plan_screening_service.py`·`test_order_plan_screening_worker.py`: 파일 status `activation_candidate` + DB 행 `active`로 실행 생성·worker 통과; 파일과 binding status 불일치는 여전히 `binding_mismatch`; 헤더 없음 = 기존 동작 동일; `daily_script` + 스위치 off → 실행 없음; `gate_measurement` + 후보 policy + 측정 회차 → 생성되고 `purpose` 기록; `gate_measurement` + 측정 회차가 아닌 회차 → `invalid_request`; `gate_measurement`여도 전송 미승인이면 503; 알 수 없는 헤더 값 → `invalid_request` |
| 사람 결정 | 없음 |

### S5a — 품질 게이트 저장소·REST·판정 (opus)

| | |
|---|---|
| 파일 | `app/screening/services/order_plan_quality_gate.py`, `routers/order_plan_quality_gates.py`, `schemas/order_plan_quality_gates.py`(전부 신규). router 등록은 S4b |
| 내용 | [`spec.md` §4.2·§4.3](spec.md) — gate 생성(측정 회차 목록 고정), evaluation 기록(pass 2개의 실행 id 대조, 나쁜 쪽 값, 판정 규칙), GET |
| 재사용 | `routers/quality_gates.py:95-105` `_latest()`, `policy.py:268-291` `_audit()` |
| 검증 | `tests/screening/test_c2_quality_gate_store.py`(신규): 임계값 NULL→`미측정` 고정; pass 1개뿐→`보류`; pass 실행에 `부분 성공`이 있으면 `보류`; 두 pass 모두 충족→`통과`; 한 pass만 미달→`미달`; `measured_*`가 나쁜 쪽 값; pass 실행이 `operational`이거나 다른 policy digest면 거부; evaluation 2회에 revision 1→2이고 1행 불변; `reference_artifact_rescore`면 reasons 필수 |
| 사람 결정 | **D-a**(gold 최종 승인)·**D-b**(임계값). 없으면 `미측정`으로만 기록된다 — 그게 정상 동작 |

### S5b — gold 게시일별 분할 도구 (sonnet)

| | |
|---|---|
| 파일 | `skills/bidops-collect/scripts/split_order_plan_run_by_day.py`(신규) + 단위 테스트 |
| 내용 | 입력 회차의 `collected-order-plans.json`을 `published_at`의 KST 날짜로 나눠 **새 회차 디렉터리**를 만든다(id `gate-gold-<YYYYMMDD>-plans`). 원본은 읽기만 한다. 각 산출물은 `schema_version`·`source_window`(그 하루)·`metadata.collection.complete=true`·`counts` 재계산·항목 bytes 불변(`source_sha256` 유지)·파생 표기(`metadata.derived_from`: 원본 회차 id와 파일 sha256). 출력 디렉터리가 있으면 실패한다 |
| 검증 | `order-plans-20260827-20260830-retry1` fixture 축약본으로 4개 회차(합계 = 원본 건수, 교집합 0), 각 산출물이 `_source_population`(`services/order_plan_screening.py:190-225`) 검증을 통과, 재실행 시 덮어쓰지 않고 실패 |

### S5c — 게이트 측정 스크립트 (sonnet)

| | |
|---|---|
| 파일 | `scripts/run-c2-gate-measurement.sh`(신규). POST·폴링은 S9c의 `scripts/c2-execution-common.sh`를 쓴다 |
| 내용 | `<gate_id> --pass 1\|2` — gate의 측정 회차를 순서대로 하나씩 `X-BidOps-Trigger: gate_measurement`로 실행·폴링하고 실행 id 목록을 출력한다. actor 필수. 채점·evaluation 기록은 하지 않는다(사람이 만든 artifact로 따로 POST) |
| 검증 | `--dry-run`이 회차·request_id를 출력하고 호출하지 않음, 실패 실행이 나오면 멈추고 exit 비0, `shellcheck` |

### S6 — 감사 표본 산출 (opus)

| | |
|---|---|
| 파일 | `app/screening/services/order_plan_audit_sample.py`, `routers/order_plan_audit_sample.py`(둘 다 신규). router 등록은 S4b |
| 내용 | [`spec.md` §5](spec.md) — 형태는 **상한 N건, 그 이하는 전건**(`max_per_execution`) |
| 재사용 | `services/order_plan_screening.py:80-96` `_canonical`/`_sha256_bytes`, 기존 `order_plan_screening_feedback` 라벨 경로 |
| 검증 | `tests/screening/test_c2_audit_sample.py`(신규): 같은 입력 2회 draw = byte 동일; `max_per_execution=None`이면 `pending_human_approval`; 모집단 300 이하면 `not_applicable`; 측정 전용 실행이면 `not_applicable`; 탈락 ≤ N이면 전건; 탈락 > N이면 층 우선순위로 N건이고 층 경계 중복 건이 한 층에만 |
| 사람 결정 | **D-c**(N·층 배분·주기·무복원 범위). 형태가 정해졌으므로 값이 채워지면 코드 변경 없이 동작한다 |

### S7 — (삭제) 모집단 범위 wire v2

첫 초안의 `population_scope`·`admitted_from`·`out_of_scope`는 결정 7(발주계획 1일 창)로 필요 없어졌다.
요청 본문 계약은 v1 그대로다([`spec.md` §6](spec.md)). 번호는 참조 안정성을 위해 비워 둔다.

### S8a — 누적 투영 백엔드 (opus)

| | |
|---|---|
| 파일 | `app/screening/services/order_plan_screening.py:997-1032`(목록 함수만), `app/screening/projection.py:737-748`, 응답 스키마의 `policy_version`·첫 관측일·`scope` |
| 내용 | [`spec.md` §7](spec.md) — 결과·**feedback** 조인 모두 사업 단위 최신 1건. 누적 범위 = **활성화된 적 있는 policy(`activated_at IS NOT NULL`)의 `purpose='operational'` 완료 실행** |
| 재사용 | 관측이 이미 쓰는 `row_number() over (partition_by …)` 패턴(`:1000-1008`)을 결과와 feedback에 한 번씩 더 |
| 검증 | `tests/screening/test_order_plan_list_v2.py`: 실행 2회(어제·오늘) fixture에서 누적 목록이 두 실행의 판정과 어제 실행의 feedback을 모두 싣는다; **policy v3을 retire하고 v4를 활성화해도 v3의 판정이 누적에 남고 행에 `policy_version`이 보인다**; 활성화된 적 없는 policy의 실행(참조 실행)과 `gate_measurement` 실행은 누적에 없고 회차 선택으로만 보인다; 회차를 고르면 그 회차만; 워크로드가 실행 없는 날 0으로 죽지 않는다 |
| 사람 결정 | 없음 |

### S8b — 발주계획 화면 (opus)

| | |
|---|---|
| 파일 | `web/frontend/src/pages/OrderPlansPage.tsx`, `tests/order-plans.spec.ts`, `tests/dashboard.spec.ts`와 그 fixture |
| 내용 | 회차 선택 기본 해제(`:1789`, `:433,437`), 기본 보기 "추적을 정하지 않은 관련 건", `scope` 누적/회차 구분 표시, 행에 판정 policy 버전·첫 관측일(결정 16), 자동 실행이 꺼져 있을 때 배너와 활성화 화면 링크([`spec.md` §3.4](spec.md)) |
| 검증 | `npx tsc -b && npm run build`, `playwright test tests/order-plans.spec.ts tests/dashboard.spec.ts`(1280x800·1440x900). 픽셀 기준선은 에이전트가 갱신하지 않고 영향 화면만 보고한다 |

### S9a — 일일 스크립트: 트랙 분리·전일 기준·1일 창 (sonnet)

| | |
|---|---|
| 파일 | `scripts/run-daily-lifecycle.sh` |
| 내용 | `--track order-plans\|notices` 필수(`:40-47`), 기준일 기본 전일(`:54`), plans 창 1일(`:68-69`), notices 창 1일(`:70`), 트랙별 순서 분리, `--collect-only --run-suffix <name>`(둘은 함께만), usage·dry-run 출력 갱신. **이 단계의 발주계획 트랙은 수집·적재까지만 묶고 C-2 연결은 S9c가 한다 — S9c 전에는 발주계획 트랙을 cron에 올리지 않는다(결정 10)** |
| 검증 | `--dry-run`이 트랙·회차 id·창을 출력하고 아무 호출도 하지 않는다; `--track` 없음 → 시작하지 않고 exit 비0; `--collect-only`에 `--run-suffix`가 없으면 exit 비0; `shellcheck` |
| 효과 | 공고 트랙을 C-2 준비와 무관하게 먼저 운영에 올릴 수 있다(결정 9) |

### S9b — 회차 조회·`-retryN`·단계별 따라잡기 (opus)

| | |
|---|---|
| 파일 | `scripts/run-daily-lifecycle.sh`, `scripts/manual-workflow-common.sh`(조회 함수 추가. 기존 `workflow_check_new_run_dir`는 그대로) |
| 내용 | [`spec.md` §8](spec.md) — "완전한 회차" 조회(`collection.complete` + `Run` 행), 빈 회차(`counts.total == 0`) 완결 처리, 불완전 디렉터리는 두고 `-retryN`으로 새로 수집, `--from-date/--to-date` 날짜별 **단계별 재개**(두 트랙 공통), 스크립트 자체 sleep 없음 |
| 검증 | `tests/lifecycle/`·`scripts/` 계약 테스트: 3일 범위에서 회차 3개를 날짜 순으로 만들고 완전한 회차는 건너뛴다; 불완전 디렉터리 fixture → 그대로 남고 `-retry1`이 생긴다; 0건 fixture → 적재 없이 완결; 발주계획 수집 실패 fixture에서 공고 트랙이 따로 끝까지 돈다; 같은 날 발주계획·공고 fixture에서 공고만 먼저 적재한 선별 통계가 발주계획을 먼저 적재한 경우와 같다(적재 순서 해제의 근거); 수집기가 0건을 완전한 산출물로 쓰는지 확인하고 아니면 보고한다(수집기 수정은 이 패키지 범위 밖 — 리더가 판단) |

### S9c — `run-daily-c2.sh` + 발주계획 트랙 연결 (opus)

| | |
|---|---|
| 파일 | `scripts/run-daily-c2.sh`·`scripts/c2-execution-common.sh`(신규: POST·폴링·헤더·request_id), `scripts/run-daily-lifecycle.sh`(발주계획 트랙에 자동 실행 확인·C-2·draw 연결) |
| 내용 | [`spec.md` §0ⓒ·§8](spec.md) — 수집 **전** `GET …/daily-trigger`, `empty_population`, attempt 계산(운영 목적 실행만), 헤더 `daily_script`, 재시도 전 `BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS`(기본 600) 대기, `attempt > 2` → `retry_limit_reached` + `--extra-attempt` 안내, `--extra-attempt`(헤더 `manual_resume`, 실행 하나), 성공 뒤 draw, 스킵 사유와 §3.4 안내문구 출력 |
| 검증 | 계약 테스트(mock REST): 스위치 off → **수집기 호출 없음**·exit 0; 4중 조건 각각 off일 때 실행이 생기지 않음; 실패 1개 → 대기 후 attempt 2; 실패 2개 → `retry_limit_reached`·exit 0; `--extra-attempt` → attempt 3이 `manual_resume`으로 생성; 성공 있음 → `already_executed`; 성공 후 draw POST 1회, `pending_human_approval`이면 exit 0; draw 실패는 exit 비0이고 결과 행은 유지; 따라잡기에서 "회차 있음 + 성공 실행 없음"이면 실행부터; `shellcheck` |
| 사람 결정 | **D-d**(전송 승인 값), **D-e**(활성화·운영시작일·cron). 그 전까지 발주계획 트랙은 항상 `daily_trigger_off`로 끝나고 수집하지 않는다 |

### S10 — (이관) 공고 수집 이중 경로 통합

C-1 자동화 때 한다 — [§7](#7-이-계획-밖--c-1-자동화-때-할-일). 번호는 참조 안정성을 위해 남긴다.

### S11 — GPU 휴지: 연속 가동 시간 기준 (sonnet)

| | |
|---|---|
| 파일 | `app/workers/analysis.py`, `app/screening/worker.py:292-297`. 설정은 S0이 이미 넣었다 |
| 내용 | [`spec.md` §10](spec.md) — `busy` 누적, `busy ≥ N`이면 다음 claim 전에 M 휴지 후 리셋, idle이 M 이상이면 리셋, `threading.Event` 대기로 SIGTERM 즉시 종료. C-1 워커는 같은 규칙을 따로, `run_until` 제외 |
| 검증 | 기본 0.0에서 기존 워커 테스트 전부 통과(동작 동일, `tests/app/test_analysis_worker_slots.py` 포함). N=5·M=7, 시계 주입: 2초짜리 잡 2개 뒤에는 `poll`만, 3번째 뒤 `wait(7)` 1회 후 `busy=0`; 8초짜리 잡 하나 뒤 `wait(7)`; 잡 없이 idle 7초면 `busy=0`; SIGTERM이 wait를 즉시 깨운다; `run_until` 경로는 휴지 없음 |
| 사람 결정 | 없음 (값은 운영자가 나중에 정한다) |

### S15 — 개요 run 중복 방지 (opus, 결정 28)

| | |
|---|---|
| 목적 | 공고 트랙 4일 창에서 같은 사전규격이 최대 4회 재관측된다. 재관측 적재는 `run_ingested` hook → `maybe_auto_prepare` → `bundle_unchanged` → `_enqueue_overview`로 이어지는데 `enqueue_overview_run`(`overview_runs.py:711`)은 활성 run(대기·실행 중)만 확인해 **완료된 run이 있어도 새 run을 만든다** — 개요·회사 핏 모델 호출이 반복된다. 추적 보충·입찰공고가 가리키는 사전규격 적재도 같은 경로를 탄다 |
| 파일 | `app/deep_review/services/overview_runs.py`의 `enqueue_overview_run`만, 신규 테스트 |
| 규칙 | `range_source="auto"`일 때: 같은 `notice_id`·같은 `document_version_id`(고른 `ready` 묶음 문서)·같은 `policy_digest`로 `completed` 또는 `needs_human_review` run이 있으면 `None`(조용히 물러남). `failed`·`cancelled`는 지금처럼 재시도된다. 사람이 범위를 확정한 `range_source="human"`은 이 규칙을 적용하지 않는다(사람의 명시적 재실행). 문서가 바뀌면(새 묶음·새 버전) 새 run이 들어간다. policy가 바뀌어도 새 run이 들어간다 |
| 검증 | 같은 문서·policy에 `completed` run → `None`; `needs_human_review` → `None`; `failed`·`cancelled`만 → 새 run; 문서 버전이 다르면 새 run; policy digest가 다르면 새 run; `range_source="human"`은 `completed`가 있어도 새 run. 기존 개요 run 테스트 파일 통과 |
| 사람 결정 | 없음(규칙은 결정 28에서 확정) |

### S12 — (이관) notice 관측 snapshot v2

C-1 자동화 때 한다 — [§7](#7-이-계획-밖--c-1-자동화-때-할-일). 번호는 참조 안정성을 위해 남긴다.

### S13a — 프런트 API·타입 배선 (sonnet)

| | |
|---|---|
| 파일 | `web/frontend/src/lib/api.ts`, `web/frontend/src/lib/types.ts` |
| 내용 | policies(목록·단건·candidate·activate), quality-gates(GET), daily-trigger(GET·POST), 실행 목록의 `purpose`, 발주계획 목록 응답의 `policy_version`·첫 관측일·`scope` 누적 형태. 백엔드 schema와 이름을 그대로 맞춘다 |
| 이유 | `lib/api.ts`·`lib/types.ts`는 S8b와 S13b가 함께 쓰므로 먼저 한 번에 넣어 파일 충돌을 없앤다 |
| 검증 | `npx tsc -b` |

### S13b — C-2 활성화 화면 (opus)

| | |
|---|---|
| 파일 | `web/frontend/src/pages/OrderPlanPolicyPage.tsx`(신규), `pages/CriteriaPage.tsx`(탭 1개 추가 — 기존 `policies`·`quality-gates` 탭 옆), 신규 Playwright spec·fixture |
| 내용 | [`spec.md` §11](spec.md) — policy 목록·exact digest·게이트 결과(`미측정`≠`미달` 표면)·측정 실행 목록(읽기 전용)·런타임 blocker·후보 지정·활성화(확인 대화 + `explicit_confirmation`)·자동 실행 스위치·안내문구 |
| 재사용 | `pages/PoliciesPage.tsx`·`pages/QualityGatesPage.tsx`의 구성·actor 입력·확인 대화, `lib/requestId.ts`, `lib/apiErrors.ts`. Astryx 컴포넌트는 `astryx component <Name>`으로 확인, 색은 `bidops` 테마 토큰만(ADR-0048), 레이아웃은 프로젝트 소유(ADR-0040) |
| 검증 | `npx tsc -b && npm run build`; 신규 spec(mock 모드, 1280x800·1440x900): blocker가 있으면 승인 단추 비활성 + 이유 표시, `미측정`·`미달`·`통과` 표면이 서로 다름, 활성화 확인 대화에 digest와 "현재 버전의 자동 실행이 꺼집니다" 문구, 스위치 옆 안내문구, 환경 cap off면 스위치 옆에 사유. 캡처는 데이터 로딩을 기다린 뒤 찍는다. 픽셀 기준선은 사용자 승인 뒤 |
| 사람 결정 | 없음 (누르는 것은 D-e) |

### S14 — 운영 문서·상태 기록 마감 (sonnet)

| | |
|---|---|
| 파일 | `docs/operations.md`(활성화까지의 절차 [`spec.md` §0ⓑ](spec.md), cron 두 줄, `--extra-attempt`, 측정 스크립트, GPU 휴지 두 값, v3 마운트), `docs/tracking/status.md`, `web/backend/AGENTS.md`, `CLAUDE.md`·`AGENTS.md`의 "현재 런타임 사실"(두 파일은 내용이 같아야 한다) |
| 방식 | 최종 통합 트리의 실제 옵션·env 이름을 리더가 뽑아 프롬프트에 그대로 준다 |
| 검증 | diff만. `CLAUDE.md`와 `AGENTS.md`가 동일한지 확인 |

### S16 — 참조 적재의 policy 행 활성 우회 차단 (opus, 2026-09-18 착수 중 발견)

| | |
|---|---|
| 문제 | C-2 실행 디렉터리 참조 적재(`POST /api/runs/ingest`)는 policy 파일의 `policy_status`·`quality_gate.status`·`activation.approved_by/at`을 DB 행에 그대로 복사하고, 파일이 `active`면 `active_slot=1`까지 채운다(`app/screening/ingest.py:1379-1394`). ADR-0060에서 파일 상태는 스냅샷이고 활성 정본은 DB 행이므로, 이 경로는 활성화 API·게이트를 거치지 않고 활성 행을 만들 수 있다. 활성화된 적 있는 policy는 누적 투영(S8a)에도 들어간다 |
| 규칙 | 참조 적재가 **새 행을 만들 때** 파일 `policy_status`는 `draft`·`activation_candidate`만 받고(그 외는 contract error), 행의 `quality_gate_status`는 `passed`가 될 수 없으며, `active_slot`·`activated_by`·`activated_at`은 늘 NULL이다. **이미 있는 행**(적재 CLI·활성화 API가 만든 것)은 digest가 같으면 상태 열을 비교하지 않고 그대로 쓴다 — 파일 상태로 DB 상태를 판정하지 않는다 |
| 검증 | 파일 `active` → 거부; 파일 `activation_candidate` → 행 `activation_candidate`·`activated_at` NULL; 이미 active인 행과 같은 digest의 참조 적재 → 행 불변·적재 성공; 기존 Ollama 참조 적재 테스트 통과 |

## 2. 의존 순서와 웨이브

```
웨이브 0  M0 늦은 색인 측정 시작(리더) · docs/0918 WIP 커밋(사용자 승인)
웨이브 1  S1a  S1b  S1c  S0  S2  S9a                    ← 서로 파일이 겹치지 않는다
웨이브 2  S3  S4a  S4c  S5a  S5b  S6  S8a  S11  S15     ← S2·S0 뒤. 신규 파일 위주
웨이브 3  S4b  S9b  S13a  S16                           ← S4b는 S8a와 같은 파일의 다른 함수라 통합 뒤 출발
웨이브 4  S9c  S8b  S13b
웨이브 5  S5c  S14
사람 결정 뒤  S3b → (사람) 측정 2회 → 채점·기록 → 활성화 → 스위치 → cron A
```

- 공고 트랙은 웨이브 1(S9a)만 끝나면 운영에 올릴 수 있다. 따라잡기는 S9b 뒤.
- 발주계획 트랙은 S9c와 사람 결정 전부가 끝나야 돈다(결정 10).
- S10·S12는 이 계획 밖이다(§7).

## 3. 사람에게 물어야 할 것

2차 검토 인터뷰로 **형태는 닫혔다. 남은 것은 값이다.** 계획에서 정하지 않는다. 값이 없으면 fail closed로 동작한다.

| ID | 닫힌 것 | 남은 것 | 들어가는 자리 |
|---|---|---|---|
| D-a | 권고안 = **풀링 방식**(결정 24). 어느 방식이든 후보로 올렸거나 불확실하다고 본 건은 사람이 전수 확정(현재 잔여 87건), 나머지는 무작위 표본만 확인하고 관련 건이 나오면 gold에 편입하고 표본을 넓힌다 | 표본 크기, "승인된 사람 gold" 최종 승인 | gate `gold_*` digest |
| D-b | 판정 규칙 = **하나라도 미달이면 차단**, 두 pass 모두 통과, 채점 단위 = **게시일별**(결정 22~24) | `recall`·`precision`·`important_missed_max`·`review_load_max`(하루 기준) 네 값. 누락 쪽은 엄격하게, 검토량 쪽은 담당자의 실제 처리 능력(월·목 검토)에 맞춘다. 참고 실측(625건 일괄: recall 96.61%, precision 44.88%, 검토후보 127, 누락 2)은 **방식 선택 근거이지 목표치가 아니고 게시일별 조건의 값도 아니다** | gate `threshold_*` 4컬럼 |
| D-c | 형태 = **상한 N건, 그 이하는 전건**(결정 15) | ① N ② 상한을 넘는 날의 층 3종 배분(정책 문자열은 우선순위 소진이다 — 균등으로 바꿀 것인가) ③ 검토 주기 — 매일인가 월·목인가(`docs/business-rules.md:55`) ④ `replacement: none`이 한 draw 안인가 날짜를 넘어서도인가 ⑤ **층 정의 값**(2026-09-18 착수 중 발견): `classification_proximity`의 기준 열과 코드 목록, `performance_similarity_proximity`의 컷 직후 구간 폭 W. v3 policy `audit_sample.strata_rules`에 넣고, 없으면 탈락 > N인 날은 `pending_human_approval` | v3 policy `audit_sample.*` |
| D-d | 승인 단위 = **binding 튜플**(결정 20). `approval_required_per_execution`은 false | 승인자·승인 시각, 고정할 `model_digest`(현재 서버 선언 revision `5fa804ff…` ≠ v2 binding `6ae70ca3…`), 방화벽/egress 승인 | v3 binding `external_transport`, `BIDOPS_C2_EXECUTION_ALLOWED` |
| D-e | 트리거 = **환경 cap + 버전에 묶인 DB 스위치**(결정 21). 활성화와 **별개 결정**이다 | 활성화를 누가 어떤 절차로 누르나(화면의 사전 확인 항목을 누가 보나). **운영시작일**과 cron 설치(매 달력일, 두 줄의 시각 — C-2·개요·심층 검토는 분석 워커가 직렬로 처리하므로 시각을 떼는 것은 GPU 충돌 회피가 아니라 처리 순서의 선호다). **트리거를 켜기 전 확인 항목**(PLAN.md Phase 6에서 옮겨 옴): 수동 실행에서 본 요청 수·duration·실패 분포, 나라장터 API 할당량, backup·restore와 stale execution 복구 훈련 | 활성화 화면, `BIDOPS_C2_DAILY_TRIGGER_ENABLED`, cron |
| D-f | **제품 재실행(측정 전용 실행)으로 닫음**(결정 22) | — | gate `evaluation_basis='product_rerun'` |
| D-g | M0 측정(사전규격 공개 지연)으로 재개해 공고 수집 창 **4일**로 닫음(결정 28) | — | [`spec.md` §9.4](spec.md) |

## 4. 이 계획으로도 아직 못 켜는 것

| 못 켜는 것 | 이유 | 푸는 것 |
|---|---|---|
| 발주계획 트랙 자체 | 결정 10 — C-2 활성화와 자동 실행 스위치가 켜지기 전에는 수집도 하지 않는다 | 아래 전부 |
| C-2 실행 자체 | `execution_allowed=false`, `BIDOPS_C2_EXECUTION_ALLOWED` 기본 false → 503 (`services/order_plan_screening.py:289`). 측정 전용 실행도 같은 승인을 요구한다 | **D-d 값** + 방화벽/egress 승인 + S3b |
| 게이트 `통과` 판정 | 임계값 4개가 NULL이면 코드는 `미측정`만 쓴다. gold가 승인되지 않으면 채점 입력이 없다 | **D-a·D-b** → 측정 2회 |
| policy 활성화 | 런타임 blocker(`quality_gate_*`·`audit_sample_policy_unapproved`·`execution_transport_not_allowed`·`policy_file_missing`)가 살아 있다. S4a는 이를 **fail closed로 확인**할 뿐 해제하지 않는다 | **D-a~D-d** + S3b |
| 감사 표본 실제 draw | `max_per_execution`·`review_cadence`가 NULL → 자동 draw가 매일 `pending_human_approval`로 끝난다 | **D-c 값** + S3b |
| 무인 일일 운영 | 스위치와 환경 cap이 둘 다 꺼져 있다 | **D-e** |
| 운영 품질·용량 근거 | 배치 실측 1건이 `quality_status=unmeasured_reference`다. **운영 근거로 쓸 수 없다.** BM25 1단계 소요시간은 기록이 없다 | 측정 전용 실행의 telemetry + 활성화 뒤 수동 관측(D-e 확인 항목) |
| 발주계획 측 갱신 관측 | 1일 창이라 `bidNtceNoList`·`changed_at` 갱신을 못 본다. 추적 중인 사업의 예산·발주 시기 변경도 화면에 반영되지 않는다(결정 16). 연결은 입찰공고 측 `orderPlanUntyNo`(76.7%)로만 | 결정 7의 대가. **후속 과제: 추적 중 발주계획만 주기적 재조회**(나라장터 API의 번호 지정 조회 지원 여부부터 확인) |
| 사전규격 등록 후 변경 관측 | 공고는 4일 창(결정 28)이라 등록 뒤 3일 안의 변경만 다시 관측한다. 그 뒤의 사전규격 변경(`chgDt`)은 못 본다(수집본 4개 기준 회차당 0.7~3.6%, 3일 안 변경 포함 값) | 필요하면 변경일 기준 조회(API 지원 확인 필요) |
| C-1 공고 판정 | 자동화 전까지 **운영에 쓰지 않는다**(결정 27). C-1 게이트 0건, policy 둘 다 `activation_candidate`, always-on 미승인, `BIDOPS_SCHEDULER_ENABLED=false`(2026-09-18 운영 확인) | §7 C-1 자동화 트랙 |
| 회사 핏·심층 검토의 운영 사용, 공고명 1차 판별 | 모델 출력이 다음 단계를 자동으로 막는데 품질을 잴 장치가 없다([`intent.md` §6](intent.md), 결정 26) | **운영에서 켜기 전 게이트 필수** — 각자 별도 계획. C-2 게이트 구조를 다시 쓸 수 있다 |
| 사전규격 개요의 품질 근거 | 운영 중이지만 표식은 항상 `unmeasured_reference`이고 표본 점검 라벨을 담을 자리가 없다 | 표본 점검(별도 계획) |
| scheduler 기반 C-2 | `docs/PLAN.md` Phase 6이 별도 ADR과 별도 변경 계획을 요구한다 | Phase 6 |
| `validate_order_plan_phase0.py`로 v3 binding 검증 | 이 validator는 20260827 phase-0 증거에 고정돼 있고 `activation_eligible is False`를 요구한다(`:1365`) | 별도 activation validator 또는 검증 범위 명시 |

## 5. 검증 범위

CLAUDE.md의 검증 범위 규칙을 따른다 — 변경 경로와 직접 영향받는 검사만, 패키지당 1회.
통과한 검사를 반복 실행하지 않는다. 전체 게이트는 **최종 통합 트리에서 1회**만 돌린다(공통 기반인 migration·실행 게이트·
목록 쿼리가 함께 바뀌기 때문).

| 요구 | 입력 | 기대 | 위치 | 패키지 |
|---|---|---|---|---|
| migration·권한 | 빈 DB → 0029, append-only trigger, 역할, `purpose` backfill | downgrade 왕복 통과 | `tests/app/test_db_migrations.py`, `test_runtime_database_privileges.py` | S2 |
| policy 적재 | 2회 적재, 1 byte 변조, 파일 status `active` | no-op·거부·행은 `draft` | `tests/screening/` | S3 |
| policy 활성화 | 런타임 blocker 7종, payload blocker 잔존, rescore gate, digest mismatch, 같은 `request_id` 다른 body | `activation_blocked`·GET과 POST의 답 일치·409·`idempotency_conflict`, 활성화 후 이전 행 `retired` | `tests/screening/test_c2_policy_api.py` | S4a |
| 자동 실행 스위치 | 4중 조건 각각 off, policy 교체 | `effective_enabled=false` + 맞는 reason, `switch_bound_to_other_version` | `tests/screening/test_c2_daily_trigger.py` | S4c |
| 실행 게이트 | 헤더 없음·`daily_script`·`manual_resume`·`gate_measurement`·알 수 없는 값, 파일 status `activation_candidate` + 행 `active` | 기존 동작 동일·스위치 off면 실행 없음·측정은 후보 허용 + 측정 회차만·`invalid_request`, worker 통과 | `test_order_plan_screening_service.py`, `test_order_plan_screening_worker.py` | S4b |
| 품질 게이트 | 임계값 NULL, pass 1개, 부분 성공 pass, 한 pass 미달, evaluation 2회 | `미측정`·`보류`·`보류`·`미달`·revision 1→2이고 1행 불변, `measured_*`는 나쁜 쪽 | `tests/screening/test_c2_quality_gate_store.py` | S5a |
| gold 분할 | 4일치 회차 | 회차 4개, 합계 일치, 교집합 0, 원본 불변 | 도구 단위 테스트 | S5b |
| 감사 표본 | 같은 입력 2회, `max_per_execution=None`, 모집단 300 이하, 탈락 ≤ N, 탈락 > N | byte 동일·`pending_human_approval`·`not_applicable`·전건·N건 | `tests/screening/test_c2_audit_sample.py` | S6 |
| 누적 투영 | 어제·오늘 실행, policy 교체, 참조 실행, 측정 실행 | 둘의 판정·feedback을 싣고 교체 뒤에도 남음, 참조·측정 실행은 없음, 워크로드가 0으로 죽지 않음 | `tests/screening/test_order_plan_list_v2.py` | S8a |
| 일일 스크립트 | `--dry-run`, `--track` 없음, 3일 따라잡기, 불완전 디렉터리, 0건, 스위치 off, 실패 1·2개, `--extra-attempt`, 성공 있음, 공고만 먼저 적재 | 호출 없음·시작 안 함·회차 3개 날짜 순·`-retry1`·적재 없이 완결·**수집 없음**·attempt 2·`retry_limit_reached`·attempt 3(`manual_resume`)·`already_executed`·선별 통계 동일 | `scripts/` 계약 테스트, `tests/lifecycle/`, `shellcheck` | S9a·S9b·S9c·S5c |
| GPU 휴지 | N·M = 0과 5·7, 짧은 잡 연속, 긴 잡 하나, idle, SIGTERM, `run_until` | 기존 동작 동일·누적 뒤 `wait(7)` 1회·즉시 종료·휴지 없음 | `tests/app/` 워커 테스트 | S11 |
| 화면 | 발주계획 화면, 활성화 화면(신규 spec) | 통과. 1280x800·1440x900 | `npx tsc -b && npm run build`, `playwright test tests/order-plans.spec.ts tests/dashboard.spec.ts` + 신규 spec | S8b·S13b |

## 6. 실행 방식

**모델 배정 기준**

| 모델 | 에이전트 타입 | 맡기는 것 | 이 계획의 패키지 |
|---|---|---|---|
| **opus** | `do-opus` (opus·effort high) | 설계 판단이 섞인 구현 — migration·상태 전이·fail-closed 게이트·쿼리 재작성·원본 불변 규칙의 가장자리·새 화면·ADR 문안 | S1a S1c S2 S4a S4b S4c S5a S6 S8a S8b S9b S9c S13b |
| **sonnet** | `do-sonnet` (sonnet·effort high) | 명세가 닫혀 있고 기계적인 것 — 문서 문장 치환, 설정 추가, 재사용 함수가 정해진 CLI, 타입·API 배선, 규칙이 표로 닫힌 스크립트·워커 변경, 값이 정해진 파일 발행 | S0 S1b S3 S3b S5b S5c S9a S11 S13a S14 |

- sonnet 패키지의 프롬프트는 **판단 여지를 남기지 않는다** — 고칠 위치·새 문장·함수 이름·기대 출력을 그대로 준다. 작업 중
  명세 밖 판단이 필요해지면 멈추고 보고하게 한다(리더가 opus로 넘길지 정한다).
- 리더(메인 세션)는 opus·effort xhigh로 진행한다. 위임은 `.claude/agents/do-opus.md`·`do-sonnet.md` 정의로 하며
  모델·effort는 정의 파일이 정한다(Agent 도구에는 effort 인자가 없다). 호출은 `subagent_type`과 `isolation: worktree`만 주고
  `model` 인자는 주지 않는다(호출 인자가 정의 파일의 모델보다 우선한다).
- 공통 규칙(작업 전 읽을 문서, 소유 밖은 보고서의 요청 사항으로, 포그라운드 실행·알림을 기다리려고 턴 종료 금지, 전체 게이트는
  리더 몫, 운영 반영 금지, 보고 형식)은 정의 파일 본문에 있다. 패키지 프롬프트에는 패키지 ID·명세·파일 소유 목록만 적는다.

**브랜치와 통합**

- 패키지별 worktree 브랜치(`feat/do-<id>`)를 쓴다. 워크트리는 커밋 기준이므로 시작 전에 `docs/0918_daily-operation/`을
  WIP 커밋한다(사용자 승인 뒤. `data/runs/**` 등 다른 미추적 파일은 넣지 않는다). 워크트리마다 `.venv`·`node_modules`
  symlink와 `experiments/order-plan-screening/review-inputs/**` 복사가 필요하다.
- 웨이브가 끝나면 리더가 통합 브랜치 `feat/do-integration`에 병합하고, 다음 웨이브의 워크트리는 거기서 출발한다.
  **`main`에는 병합하지 않고 보고한다.**
- 프런트 병렬 패키지(S8b·S13b)는 `PW_PORT`·`PW_OUT_DIR`를 따로 배정한다.

**리더의 몫**

- 웨이브 사이 게이트(§5의 해당 검사)와 로직 diff 검수. 위임 보고를 근거로 쓰지 않는다.
- 검사 실행자는 리더 하나다. 실패하면 먼저 단독 실행으로 원인을 가린다(Playwright strict mode 위반은 flake가 아니다).
- 픽셀 기준선 교체와 운영 반영(migration 적용·compose 변경·cron 설치)은 사람 승인 뒤에만 한다.
- M0 측정은 실 API를 부르므로 리더가 사용자 승인 뒤 직접 실행한다.

## 7. 이 계획 밖 — C-1 자동화 때 할 일

2026-09-18 S10·S12를 이 계획에서 뺐다. 방향(결정 4, 공고 수집은 한 번만)은 그대로이고 구현 시점만 C-1 자동화와
함께로 옮긴다. **그때까지 C-1은 운영에 쓰지 않는다(결정 27).**

**왜 뺐나.**

- scheduler가 돌리는 C-1은 C-1 품질 게이트 통과(고정 40건 A/B, `docs/model-quality-gate.md`)·C-1 policy
  활성화·always-on 승인·`BIDOPS_SCHEDULER_ENABLED`가 모두 있어야 켜진다. 이 계획의 사람 결정(D-a~D-f)은 전부
  C-2용이라 어느 것도 다루지 않는다. S10·S12는 이 계획 안에서 테스트로만 돌고 운영 효과가 없다.
- S12는 발주계획·공고·C-1 결과 적재가 모두 지나는 loader snapshot 계약을 바꾼다. 매일 운영될 공고 트랙에 이득 없는
  위험을 먼저 얹게 된다.
- S12의 필요 여부가 C-1 자동화 방식에 달려 있다(아래).

**그때 먼저 정할 것.**

| 항목 | 내용 |
|---|---|
| **선행조건 ① 게이트 재측정** | 모델 이름이 vLLM served id로 바뀌어(ADR-0050) 고정 40건의 기존 기록을 기준선으로 쓸 수 없다. 새 이름으로 A/B execution을 새로 만들어 게이트를 다시 측정한다(`docs/model-quality-gate.md`, `docs/tracking/findings.md`) |
| **선행조건 ② 수동 경로 정리** | 수동 경로(`cli_single`·`manual_run`)는 게이트를 거치지 않은 `activation_candidate` policy도 받고(`orchestrator.py:1623`, `worker.py:375-377`, `queue.py:427-429`), 그 결과의 `제외`는 기본 목록에서 공고를 숨긴다(`screening/projection.py:52,585`). 활성화된 적 없는 policy의 `제외`를 숨기지 않게 할지, 수동 경로도 `active`만 받게 할지 정한다. 뒤쪽은 테이블 채우기 같은 참조 실행 절차(`docs/e2e-lifecycle-fill.md`)를 함께 고쳐야 한다 |
| 자동화 방식 | ⓐ scheduler가 공고 트랙 회차를 adopt(S10) — 같은 회차를 `--collection`과 merge_load가 두 번 적재하므로 S12가 필요하다([`spec.md` §9.1](spec.md)). adopt는 `-retryN` 접미사를 가진 "그 날짜의 완전한 회차"를 S9b와 같은 조회로 찾아야 한다. ⓑ 공고 트랙이 C-2처럼 REST로 C-1을 부른다 — 결과가 파생 회차(`--screen-…`, `worker.py:1060`)로 적재돼 같은 회차 재적재가 없으므로 S12가 필요 없을 수 있다. 다만 `active`·게이트 통과를 확인하는 장치가 따로 필요하다(선행조건 ②). ⓑ는 `docs/PLAN.md` Phase 6 제약(scheduler 파일)과 무관하다 |
| 시각 | ⓐ면 공고 트랙이 scheduler `daily_time`(기본 02:00, `schedule_setting`) 전에 끝나야 한다. 아니면 그날 `collect_source_missing`이다. `daily_time`을 옮기나 cron을 당기나 |
| GPU 조율 | C-1 워커는 web 프로세스의 별도 스레드라 분석 워커와 서로 조율하지 않는다([`spec.md` §10](spec.md) 한계). C-1이 매일 돌기 시작하면 두 워커의 휴지가 어긋나 GPU 전체가 쉬는 구간이 보장되지 않는다. 프로세스 간 조율이 필요한지 그때 정한다 |
| C-1 활성화 | C-1 게이트 실행·policy 활성화·always-on 승인 주체와 절차 |

**그 사이 지킬 것.**

- scheduler를 켜기 전에 adopt가 먼저다. S10 없이 켜면 scheduler가 따로 수집해 같은 날 공고가 두 회차에 들어간다.
- 공고 회차 창(4일, 결정 28)과 scheduler 예약 창(1일)이 다르다. adopt하면 겹친 공고가 매일 C-1 대상에 다시 들어가
  중복 판정이 된다([`spec.md` §9.2](spec.md)). 판정 대상을 그 회차에서 처음 관측된 공고로 좁히는 방법을 그때 정한다.
- C-1을 점검용으로 부를 수는 있다(`lifecycle-<D−1>-notices`에 `POST /api/runs/{run_id}/pipeline/judgment`, 결과가 파생
  회차로 적재되므로 snapshot 충돌은 없다). 그 판정은 **미측정 policy의 판정**이며 운영 판단의 근거로 쓰지 않는다.

**옮겨 온 단계.** 아래 두 단계와 S1에서 뺀 문서 항목(`docs/contracts.md` notice snapshot v2, ADR "notice 관측
snapshot v2(표본 필드 제외)")은 ⓐ로 정할 때 그대로 쓴다. 모델 배정은 S12 opus(loader 계약 변경), S10 opus.

### S12 — notice 관측 snapshot v2 (표본 필드 제외)

| | |
|---|---|
| 파일 | `app/lifecycle/ingest/loader.py:125`(schema 상수), `:519-520`(`_notice_values`의 `sample_role`·`sample_stratum`을 snapshot 값에서 분리), `:616-666`(v1 저장 관측은 경고 + no-op), `:1962-2030`(`_upsert_notice`에서 두 컬럼을 `demand_agency`와 같은 규칙으로 기록) |
| 내용 | [`spec.md` §9.1](spec.md) 해법 (A) |
| 재사용 | `demand_agency` 처리(`loader.py:1987-2024`), pre-0009 legacy 규칙(`:634-657`) |
| 검증 | `tests/app/test_ingest_loader.py`·`tests/app/test_cumulative_identity.py`의 snapshot 기대값을 v2로 갱신. 신규: collection → validation(표본 포함) → collection 3회 적재에 관측 행 수 불변·충돌 없음이고 `sample_stratum` 컬럼은 채워진다; v1 snapshot 관측이 있는 회차 재적재는 경고 `observation_snapshot_legacy_schema` 1건 + no-op; 발주계획 snapshot 기대값은 변화 없음 |
| 사람 결정 | 없음. 단 C-1 자동화를 scheduler adopt로 정할 때만 필요하다 |

### S10 — 공고 수집 이중 경로 통합 (adopt)

| | |
|---|---|
| 파일 | `app/screening/runtime.py:94-105`의 `collect` 분기만. `_ingest`에 selection 인자를 넘기지 **않는다** |
| 내용 | [`spec.md` §9](spec.md) |
| 선행 | **S12** (snapshot v2 없이는 merge_load 재적재가 반드시 실패한다) |
| 검증 | 오늘 회차 없으면 `collect_source_missing`, 있으면 그 run_id로 다음 단계 진행(`tests/screening/test_scheduled_pipeline.py`). adopt한 회차의 `Run.window_from == window_to == 예약 창`이다(1일 창, 회차 사이 겹침 없음). 같은 회차를 `--collection`→`validation`(표본 포함)→`--collection` 순으로 3회 적재해도 관측 행 수 불변·snapshot 충돌 없음(`tests/lifecycle/`) |
| 사람 결정 | C-1 자동화 방식(위). scheduler adopt로 정할 때만 이 단계가 필요하다 |

검증(옮겨 온 것):

| 요구 | 입력 | 기대 | 위치 |
|---|---|---|---|
| snapshot v2 | collection→validation(표본)→collection 3회, v1 관측 회차 | 관측 행 수 불변·충돌 없음·경고 1건 + no-op | `tests/app/test_ingest_loader.py`, `tests/lifecycle/` |
| 수집 통합 | 회차 유·무, 1일 창 회차 | `collect_source_missing`·`Run` 창 = 예약 창 | `tests/screening/test_scheduled_pipeline.py` |

## 8. 2차 검토 지적이 닫힌 자리

2026-09-18 2차 검토(코드·데이터 대조)와 인터뷰 중 발견을 어디서 닫았는지 적는다.

| # | 지적 | 닫힌 자리 |
|---|---|---|
| 1 | policy 파일의 상태값 문제가 `policy_status`만 풀렸다(`activation.blockers`·`quality_gate.*`·`audit_sample.status`도 immutable, GET과 activate의 답이 갈림) | 결정 18 — [`spec.md` §1.1·§3.2·§3.3](spec.md), S1a·S4a |
| 2 | `trigger` 인자를 실을 자리가 없다(요청 v1은 추가 필드 거부) | 결정 19 — [`spec.md` §1.3·§8](spec.md), S4b |
| 3 | 감사 표본 "값만 채우면 동작"과 "새 필드 필요"가 어긋남 | 결정 15 — [`spec.md` §5](spec.md), S6·D-c |
| 4 | v3 policy·binding 발행·마운트 단계가 없고 마운트 위치 서술이 틀림 | [`spec.md` §1.3](spec.md), S3b |
| 5 | 규모 근거(일 250~350건·탈락 0~50건)가 틀림 | 결정 14 — [`intent.md` §4](intent.md), [`spec.md` §5](spec.md) |
| 6 | 0건인 날 실행 생성이 409 | [`spec.md` §8](spec.md) `empty_population`, S9b·S9c |
| 7 | 재시도를 다 쓴 회차의 복구 경로 없음, 재시도 간격 0초 | 결정 12 — [`spec.md` §8](spec.md), S9c |
| 8 | 따라잡기의 건너뛰기 단위 불명, 수집만 쌓인 날·불완전 디렉터리 | 결정 10 — [`spec.md` §8](spec.md) 단계별 재개·`-retryN`, S9b |
| 9 | policy 교체 때 누적이 비워짐 | 결정 11 — [`spec.md` §7](spec.md), S8a |
| 10 | GPU 휴지 값 하나로는 작업 크기가 안 맞음(C-2는 분석 워커 안에서 직렬) | 결정 13 — [`spec.md` §10](spec.md), S11 |
| 11 | 게이트가 재는 조건(4일치 일괄)과 일일 운영 조건이 다름 | 결정 23 — [`spec.md` §4.2](spec.md), S5a·S5b |
| 12 | 늦은 색인 측정이 공고에만 있음 | [`spec.md` §9.4](spec.md), M0 |
| 13 | 문서 정합 — S1 목록 누락, PLAN.md P5-2·Phase 6과의 관계, scheduler 기각 근거의 "human 위조" | 결정 17·19 — S1a·S1b·S1c |
| 14 | (인터뷰 중) 게이트 측정의 순환 — 실행 API가 active만 받음 | 결정 22 — [`spec.md` §4.1](spec.md), S4b·S5c |
| 15 | (인터뷰 중) PLAN.md "실행 버튼은 사람이 눌러야 한다"와 cron 자동 실행의 충돌 | 결정 17 — S1c |
| 16 | (인터뷰 중) C-2 밖의 모델 사용 지점에 품질 장치가 없음, C-1 수동 경로의 우회 | 결정 26·27 — [`intent.md` §6](intent.md), §4·§7, S1c |
| 17 | (구현 중, M0) 사전규격은 `rgstDt`로 조회되고 `rcptDt`에 공개돼 1일 창이 영구 누락을 만든다. 겹친 창의 재관측은 개요 run을 다시 넣는다 | 결정 28 — [`spec.md` §9.4](spec.md), S9a·S15, [M0 기록](../validation-runs/20260918-late-indexing.md) |
