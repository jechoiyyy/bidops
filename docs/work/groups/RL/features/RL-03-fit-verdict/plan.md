# 카드 기반 참여 판정과 판정 화면 — plan

- 기능 ID: `RL-03-fit-verdict`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md), HP-03·HP-04 plan(변경 파일 지도 재사용)
- 작성일: 2026-10-16 (독립 검사 1차 반영; 2026-10-17 배치 B 인터뷰 D1~D13 반영 — [batch-b-interview.md](../../batch-b-interview.md))

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/policies/analysis-policy-luna-rl-v1.json | 신규 | card-v1 정책(HP-03 승인 wire 절 + 실회사 문구). 2026-10-17 결정 B23·B24로 `analysis-policy-luna-rl-v2.json`(selector `card-sections-v2`, 종합 지시에 `missing_sections` 규칙) 추가, v1 파일 불변 |
| web/backend/app/deep_review/contracts/bidops.requirement-extract.v1.json, bidops.verdict-role.v1.json, bidops.practitioner-verdict.v1.json, bidops.card-analysis-input.v1.json | 신규 | 단계·입력 schema |
| web/codex-runner/runner.py, Dockerfile | 수정 | contract `card-extract-v1|card-role-v1|card-synthesis-v1`, schema 파일 COPY |
| web/backend/app/deep_review/models.py, alembic/versions/<head 다음>_card_analysis.py, scripts/runtime-privileges.sql, tests/app/test_runtime_database_privileges.py, tests/app/boundary_map.py, tests/app/test_db_migrations.py | 수정/신규 | 테이블 4·trigger·worker INSERT 5개·등록 |
| web/backend/app/deep_review/services/transfer_policy.py, cli/approve_transfer_policy.py, cli/revoke_transfer_policy.py, cli/drain_verdict_queue.py | 신규 | 승인·철회·큐 |
| web/backend/app/deep_review/services/card_units.py, card_analysis.py, card_compare.py, card_roles.py | 신규 | unit·batch·추출 검증·대조·역할/종합 조립 |
| web/backend/app/deep_review/services/company_deep_review.py, company_analysis_input.py, deep_reviews.py, input_versions.py, luna_identity.py, luna_client.py, luna_inputs.py, schemas/company_analysis.py, company_knowledge_retrieval.py, company_projection.py, contracts/__init__.py | 수정 | gate 분기(RL enabled·실회사, 참조 모드·Luna 플래그 유지, `card-v1`은 개요 gate 생략 — D1)·자동 preview/approval(`actor_kind`·`commit` 인자)·v2 입력(`card_analysis` 키 집합, `overview_*` null 허용·현재성 개요 비교 제외 — D1)·전송 payload 규칙(D2)·card-v1 dispatch·정책 행 선택 env·`_LUNA_POLICY_FILES_BY_IDENTITY`·retrieval status/origin 확장·client contract allowlist |
| web/backend/app/lifecycle/extensions.py, lifecycle/models.py(`briefing_item.slack_message_ts`), app/core/slack.py(`post_thread_reply`) | 수정 | 확장점 2개 선언·스레드 답글·RL-01 추가형 열 |
| web/backend/app/deep_review/services/verdict_trigger.py, auto_preparation.py(hook) | 신규/수정 | 자동 트리거·cap |
| web/backend/app/deep_review/services/verdict_view.py, schemas/verdict_view.py, routers/verdicts.py, routers/company_reads.py, routers/company_analysis.py, main.py | 신규/수정 | REST 4개·가드 |
| web/backend/app/deep_review/extensions 제공자 | 수정 | `verdict_completed`·`verdict_display`·`on_briefing_recommendation` |
| web/backend/app/core/config.py | 수정 | 설정 3개 |
| web/backend/tests/deep_review/test_card_analysis.py, test_card_compare.py, tests/app/test_transfer_policy.py, test_verdict_trigger_postgres.py, test_card_analysis_postgres.py, test_verdict_api.py, test_verdict_payload_guard.py, test_codex_runner.py | 신규/수정 | T1~T10 |
| web/frontend/src/pages/OpportunityVerdictTab.tsx, components/verdict/{VerdictSummary,Checklist,RequirementTable,SourcePanel,RunInfoDialog}.tsx, lib/api.ts, apiErrors.ts, tests/verdict.spec.ts, tests/api-mock.ts | 신규/수정 | T7 |
| docs/work/demo-contract.md, hp-contract.md, contracts.md, business-rules.md, operations.md, ADR.md, 1016_rootlab-redefinition/ui-spec.md, validation-runs/<날짜>-rl/RL-03/README.md | 수정/신규 | STEP-010 |

## 작업 순서

1. STEP-001 정책 파일·schema·runner contract [complex]
   - 목표: 새 정책 identity·세 단계 schema·runner/client allowlist·정책 행 import와 선택 env가 함께 올라가고 기존 contract는 그대로.
   - 작업 대상: 정책 JSON, contracts 4개(+`__init__.py` 맵), runner.py/Dockerfile, luna_identity.py, luna_client.py, input_versions.py(`_LUNA_POLICY_FILES_BY_IDENTITY`), config.py, test_codex_runner.py, test_company_luna_policy.py.
   - 검증: `pytest tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py`.
2. STEP-002 저장 테이블·권한 [standard]
   - 목표: 테이블 4개·trigger·권한(worker INSERT 5개 포함)·등록.
   - 작업 대상: models.py, migration, runtime-privileges.sql, 권한 테스트, boundary_map, test_db_migrations.
   - 검증: `test_db_migrations.py`·`test_runtime_database_privileges.py`(PG).
3. STEP-003 정책 승인·gate [complex]
   - 목표: 승인/철회 CLI(행 canonical sha), 검사 순서, 자동 preview/approval 생성(`actor_kind=system`·commit 위임), 재판정 경로(기존 code), 감사 이벤트(claim 직후), `card-v1` 개요 비의존(gate에서 개요 단계 생략·SW≠Y는 `effective_grade_ineligible`·현재성에서 개요 비교 대신 `overview_*` null 확인, spec "개요 의존 제거" 1·3·5).
   - 작업 대상: transfer_policy.py, CLI 2개, company_deep_review.py gate·resolve·`_review_current`, luna_inputs.approve, deep_reviews.py claim.
   - 검증: T2, T3, T10.
4. STEP-004 unit·batch·입력 v2 [complex]
   - 목표: HP-03 unit/selector/batch 규칙과 `card_analysis` 입력 정확 키(`card-v1`은 `overview_*` null, v2 입력·`FrozenProvenance` nullable validator), 전송 payload 규칙(spec D2: `confirmed` 전부 값 포함, `proposed`/`unknown`은 `{fact_key, status}`만, 노트·운영 정보·모델/정책 id 제외), retrieval의 `proposed`·origin 7값.
   - 작업 대상: card_units.py, company_analysis_input.py, schemas/company_analysis.py, company_knowledge_retrieval.py.
   - 검증: T1(unit·batch), T9.
5. STEP-005 추출 검증·대조·역할/종합 [complex]
   - 목표: HP-03 단계 wire 검증기, 루트랩 allowlist 대조, `proposed_fact`, 종합 검증.
   - 작업 대상: card_analysis.py, card_compare.py, card_roles.py, deep_reviews.py dispatch, 테스트.
   - 검증: T1(나머지), T5(PG).
6. STEP-006 자동 트리거·cap·큐 [complex]
   - 목표: 추천→준비→ready→SW=Y(`sw_business_status='Y'`, 개요 run 없음 — D1)→worker 역할 attempt, cap 큐·drain, 현재성 재트리거 금지, 사전규격만.
   - 작업 대상: verdict_trigger.py, auto_preparation.py hook, drain CLI, lifecycle extensions 선언·deep_review 제공.
   - 검증: T4(PG).
7. STEP-007 REST·view [complex]
   - 목표: HP-04 view + 추가 키(`company_sha256`=graph), 사업기회 별칭(deep_review 라우터), 수동 요청(기존 code), feedback, 미들웨어·서비스 가드 분기.
   - 작업 대상: verdict_view.py, schemas, routers 3개, main.py, company_projection.py.
   - 검증: T6(PG).
8. STEP-008 연결(활동·브리핑·Slack 스레드) [standard]
   - 목표: 제공자 3개(활동·`briefing_verdict_display`·`on_briefing_recommendation`), `post_thread_reply`, `briefing_item.slack_message_ts`, `bidops.briefing.v2`.
   - 작업 대상: extensions 제공자, core/slack.py, lifecycle models/schemas(추가형).
   - 검증: T8.
9. STEP-009 화면 [standard]
   - 목표: ui-spec §4.4 전부·상태 6종·원문 패널·실행 정보 다이얼로그.
   - 작업 대상: 프런트 파일.
   - 검증: T7.
10. STEP-010 문서·mock 경로·실제 1건 [complex]
   - 목표: 문서 8종, bidops-local mock 전 경로(T11, 자동 트리거 on은 여기서만), 짧게 알린 뒤 실제 Luna 1건(T12). T12 조건: bidops-local 격리 스택(운영 `bidops` 스택·DB 금지), `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`·`BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`·`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`로 수동 `POST verdict-requests` 1건; 폴리텍 사전규격 원본 HWP는 `~/orca/fixtures/RFP/(붙임2) 2027년 홈페이지 유지관리 용역사업 제안요청서(수정본).hwp`(이전 수집본과 sha 일치 확인)를 격리 DB에 등록(나라장터 호출 없음, D8); runner만 기존 `docker-compose.luna.yml`의 `luna-egress` bridge로 외부 통신하고 web·worker는 내부망(D7); Luna 인증은 호스트 `~/.codex/auth.json`(CLI 0.162.1)을 `BIDOPS_CODEX_AUTH_FILE` compose secret으로 읽기 전용 마운트하며 값·내용을 로그·문서에 남기지 않음(D6); 정책 승인·요청 actor `jechoi`(D11), `--daily-cap 2`(T12 + 재시도 1); attempt당 호출 약 24회 이내; 검증 실패면 1회만 다시 판정, 그래도 실패면 정지·보고하고 RL-04 T11 보류(D3·D4·D10).
   - 작업 대상: docs, validation-runs README, bidops-local(compose luna overlay·env, 폴리텍 원본 등록).
   - 검증: T11, T12, `doctor _`.
11. STEP-011 항목 단위 추출 실패 격리(결정 B51) [complex]
   - 목표: 추출 검증이 증거 계열 규칙(인용·숫자·개념·잘림·유일성)을 어긴 항목만 `rejected`로 격리하고 나머지로 판정을 이어간다. 격리된 unit은 대조에서 `unknown`(reason `extract_rejected`), 판정은 "진행 가능" 불가(최대 "조건부 진행"), 화면·REST에 "검증 실패 — 사람 확인 필요" 목록. 모델 출력은 고치거나 다른 값으로 바꾸지 않는다. 격리 unit이 전체의 25%를 넘거나 schema 실패가 repair 뒤에도 남으면 지금처럼 판정 전체 실패. 새 불변 정책 v7, mock·T11 재실행, 사용자 승인 범위 안에서 실제 1건(T12, 재시도 1).
   - 작업 대상: card_analysis.py(항목별 위반 수집·격리), card_compare.py(reason enum), card_roles.py·종합 규칙, verdict_view·schema·REST, 정책 v7, mock, 프런트 판정 탭, contracts·business-rules·operations·spec, bidops-local.
   - 검증: T18(격리·임계·판정 상한·view), 기존 T1~T17, T11 mock, T12 실제.
12. STEP-012 종합 출력 계약 v2와 종합 재실행(결정 B55) [complex]
   - 목표: 종합 출력 계약 v2 — 차단 조건(`blocking_condition_ids`)은 코드가 필수·gap 대조 행에서 계산하고 모델 계약에서 제거, 누락 영역·격리 unit의 "사람 확인" 행동은 코드 행으로 추가(모델 출력 아님). 모델은 판정·이유·주의·역할 unit 행동만. 새 불변 정책 v9. 실패한 card attempt의 검증된 단계(추출·대조·역할)를 같은 동결 입력·정책 계보에서 재사용해 종합만 다시 실행하는 경로(새 attempt, 재사용 단계 출처·sha 감사, 전송 감사·cap 1). mock·T11, 사용자 승인 범위 안에서 실제 1건(종합 1회, repair 포함 최대 2회).
   - 작업 대상: synthesis schema v2·card_roles 조립·검증, card_analysis 재실행 경로, deep_reviews·REST(재실행 요청), runner contract, 정책 v9, mock, 프런트(다시 판정 동작 그대로 또는 재실행 표시), 문서.
   - 검증: T19(계약 v2·코드 행동·재실행 동일성·감사), 기존 테스트, T11 mock, T12 실제.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | identity·allowlist 동시 변경, fail-closed |
| STEP-002 | S | 낮음 | standard | 패턴 존재 |
| STEP-003 | M | 높음 | complex | 승인 순서·자동 approval·감사 불변식 |
| STEP-004 | M | 높음 | complex | 허용 키·동결 hash |
| STEP-005 | L | 높음 | complex | 검증 규칙·단위 환산·unknown 보존 |
| STEP-006 | M | 높음 | complex | 트리거 경합·cap·현재성 |
| STEP-007 | M | 높음 | complex | projection 정확성·별칭 해석 |
| STEP-008 | S | 중간 | standard | 확장점 패턴 |
| STEP-009 | L | 중간 | standard | ui-spec 닫힘 |
| STEP-010 | M | 높음 | complex | 실제 외부 호출·사람 확인 경계 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 승인 없이 전송 | 감사 이벤트 없는 attempt | gate 순서 첫 단계, T3 |
| `proposed`를 근거로 met | compare에 `proposed_fact` 없이 met | T1 고정 |
| 직접생산 품명 세부 없음 → gap 처리 | 자격 체크리스트 gap | detail null → unknown 규칙, T1 |
| cap 큐가 자동 catch-up처럼 쌓임 | queued 수 증가 | drain은 브리핑 생성 뒤 1회·cap 안에서만, 큐 수를 설정 화면에 표시 |
| 운영 정보가 실무 화면에 노출 | 금지 문자열 검사 실패 | 실행 정보는 다이얼로그 한 곳 |
| worker INSERT 권한 확대가 다른 경로로 새어 나감 | 권한 테스트 app 전용 단언 실패 | 5개 테이블 INSERT만, UPDATE/DELETE 없음, 테스트 갱신 |
| 입찰공고 판정 기대 | 사용자가 입찰공고 판정을 요구 | spec 머리 범위 결정을 보고, 후속 기능으로 등록 |
| 실제 호출을 문서 승인으로 오인 | T12를 사람 확인 없이 실행 | STEP-010은 직전 확인 대상, 기본 플래그 false |
| 노트 본문 payload 유입 | T9 실패 | 입력 조립이 lifecycle 노트를 읽지 않음 |
| `proposed`/`unknown` 값 또는 운영 정보 전송 | T9 (b)(c) 실패, payload에 "BBB0"·policy sha | 전송 projection이 `{fact_key, status}`만 남김(D2), 위반 시 호출 전 fail closed·실행 중지·보고 |
| 개요 모델 호출 유입(RL 제약 위반) | 실제 스택에 개요 run·LiteLLM/vLLM 호출 흔적 | `card-v1` 개요 gate 생략(D1), 실제 스택 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`, T4 개요 호출 0 |
| 실제 호출 상한 초과 | T12 호출 수 24 초과·attempt 3개 이상 | 승인 `--daily-cap 2`, 재시도 1회 뒤 정지(D10), 자동 재시도·자동 보정 없음 |
| "확인 필요"가 많은 결과를 판정 실패로 오인 | T12 unit 다수가 unknown | 회사 unknown 21건이 원인인 데이터 상태로 README에 기록(D13), 보강은 RL-05 전 인터뷰 |
| Luna 인증 정보 노출 | 로그·README에 auth.json 내용 | 읽기 전용 secret 마운트만, 내용 출력 금지(D6) |

## 증명

- docs: `doctor _`, 문서 8종 diff.
- tests: `pytest tests/deep_review/test_card_analysis.py tests/deep_review/test_card_compare.py tests/app/test_transfer_policy.py tests/app/test_verdict_api.py tests/app/test_verdict_payload_guard.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py`.
- postgres: `test_card_analysis_postgres.py test_verdict_trigger_postgres.py test_db_migrations.py test_runtime_database_privileges.py`.
- frontend: `npm run build && npx playwright test --project=app verdict.spec.ts opportunity-record.spec.ts`.
- api_guard: T3·T9·T10(승인·입력 hash·회사 소속·외부 전송 차단).
- real_data_run: T12 실제 1건(폴리텍 사전규격, `~/orca/fixtures/RFP/` 로컬 원본 HWP, 나라장터 호출 없음) — 2026-10-17 배치 B 인터뷰가 범위 승인이며 실제 호출·정책 승인 CLI·runner 재배포·bidops-local 스택 변경 직전에 짧게 알리고 진행. 실제 호출은 이 1건(attempt당 약 24회 이내)뿐이고 자동 트리거는 실제 스택에서 꺼 둔다(자동 트리거는 T4·T11 mock으로 증명). 검증 실패면 1회만 다시 판정하고 그래도 실패면 정지·보고, RL-04 T11 보류(D3·D4·D10). spec의 호출당 repair(≤1) 외 자동 재시도·자동 보정 없음. runner만 `luna-egress`(D7), 인증은 `~/.codex/auth.json` 읽기 전용 secret(D6), actor `jechoi`(D11). 결과는 `unmeasured_reference`로만 기록하고 품질 근거로 쓰지 않으며 "확인 필요" 비중은 데이터 상태로 적는다(D13). README에 attempt id·sha·호출 수·시간·`analysis.transfer.sent` 감사 기록. 정지 조건: 승인 감사 없는 전송, payload에 노트·`proposed`/`unknown` 값·운영 정보, 상한 초과 → 즉시 중단·보고. Slack 스레드는 가짜 서버 검사(T8)까지이며 실제 Slack 증명으로 적지 않는다(D5). T11 mock은 T12의 대체가 아님.

## 결과

2026-10-18, run `rlb-20261017`. STEP-001~010 done, 상태 validating. 상세 기록 `docs/work/_runs/rlb-20261017/RL-03-fit-verdict.md`, 결정 B1~B39 `docs/work/_runs/rlb-20261017/decisions.md`.

- 구현: 카드 판정 파이프라인(unit·batch, 추출→결정적 대조→3역할→종합), 정책 단위 전송 승인·일일 상한·`analysis.transfer.sent` 감사, 판정 REST·화면 탭·활동·브리핑 연동, 자동 트리거·drain, mock 참조 실행, 로컬 원본 연결 CLI. 정책 v1~v6(기본 v6), selector v1~v3, 추출 계약 v1·v2, migration `0040_card_analysis`.
- 증명: docs·tests(284)·postgres(156)·frontend(build + 52)·api_guard(57) pass. **real_data_run pending** — 실제 Luna T12 1~7차 모두 판정을 얻지 못함(마지막은 단일 제약 검증 실패). 사용자 결정 B37(옵션 B)로 pending 유지, 구조 원인은 `docs/tracking/findings.md` "RL-03 카드 판정은 제약 하나의…".
- T11 mock 경로는 8차(v6) completed, `mock_reference`이며 T12 대체가 아님. 실제 전송 합계 모델 호출 8회(모두 사용자 승인 범위).
