# 카드 기반 참여 판정과 판정 화면 — plan

- 기능 ID: `RL-03-fit-verdict`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md), HP-03·HP-04 plan(변경 파일 지도 재사용)
- 작성일: 2026-10-16 (독립 검사 1차 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/policies/analysis-policy-luna-rl-v1.json | 신규 | card-v1 정책(HP-03 승인 wire 절 + 실회사 문구) |
| web/backend/app/deep_review/contracts/bidops.requirement-extract.v1.json, bidops.verdict-role.v1.json, bidops.practitioner-verdict.v1.json, bidops.card-analysis-input.v1.json | 신규 | 단계·입력 schema |
| web/codex-runner/runner.py, Dockerfile | 수정 | contract `card-extract-v1|card-role-v1|card-synthesis-v1`, schema 파일 COPY |
| web/backend/app/deep_review/models.py, alembic/versions/<head 다음>_card_analysis.py, scripts/runtime-privileges.sql, tests/app/test_runtime_database_privileges.py, tests/app/boundary_map.py, tests/app/test_db_migrations.py | 수정/신규 | 테이블 4·trigger·worker INSERT 5개·등록 |
| web/backend/app/deep_review/services/transfer_policy.py, cli/approve_transfer_policy.py, cli/revoke_transfer_policy.py, cli/drain_verdict_queue.py | 신규 | 승인·철회·큐 |
| web/backend/app/deep_review/services/card_units.py, card_analysis.py, card_compare.py, card_roles.py | 신규 | unit·batch·추출 검증·대조·역할/종합 조립 |
| web/backend/app/deep_review/services/company_deep_review.py, company_analysis_input.py, deep_reviews.py, input_versions.py, luna_identity.py, luna_client.py, luna_inputs.py, schemas/company_analysis.py, company_knowledge_retrieval.py, company_projection.py, contracts/__init__.py | 수정 | gate 분기(RL enabled·실회사, 참조 모드·Luna 플래그 유지)·자동 preview/approval(`actor_kind`·`commit` 인자)·v2 입력(`card_analysis` 키 집합)·card-v1 dispatch·정책 행 선택 env·`_LUNA_POLICY_FILES_BY_IDENTITY`·retrieval status/origin 확장·client contract allowlist |
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
   - 목표: 승인/철회 CLI(행 canonical sha), 검사 순서, 자동 preview/approval 생성(`actor_kind=system`·commit 위임), 재판정 경로(기존 code), 감사 이벤트(claim 직후).
   - 작업 대상: transfer_policy.py, CLI 2개, company_deep_review.py gate·resolve, luna_inputs.approve, deep_reviews.py claim.
   - 검증: T2, T3, T10.
4. STEP-004 unit·batch·입력 v2 [complex]
   - 목표: HP-03 unit/selector/batch 규칙과 `card_analysis` 입력 정확 키·payload 허용 키, retrieval의 `proposed`·origin 7값.
   - 작업 대상: card_units.py, company_analysis_input.py, schemas/company_analysis.py, company_knowledge_retrieval.py.
   - 검증: T1(unit·batch), T9.
5. STEP-005 추출 검증·대조·역할/종합 [complex]
   - 목표: HP-03 단계 wire 검증기, 루트랩 allowlist 대조, `proposed_fact`, 종합 검증.
   - 작업 대상: card_analysis.py, card_compare.py, card_roles.py, deep_reviews.py dispatch, 테스트.
   - 검증: T1(나머지), T5(PG).
6. STEP-006 자동 트리거·cap·큐 [complex]
   - 목표: 추천→준비→ready→(개요·SW)→worker 역할 attempt, cap 큐·drain, 현재성 재트리거 금지, 사전규격만.
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
   - 목표: 문서 8종, bidops-local mock 전 경로(T11), 사람 직전 확인 뒤 실제 Luna 1건(T12).
   - 작업 대상: docs, validation-runs README, bidops-local.
   - 검증: T11, T12, `doctor _`.

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

## 증명

- docs: `doctor _`, 문서 8종 diff.
- tests: `pytest tests/deep_review/test_card_analysis.py tests/deep_review/test_card_compare.py tests/app/test_transfer_policy.py tests/app/test_verdict_api.py tests/app/test_verdict_payload_guard.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py`.
- postgres: `test_card_analysis_postgres.py test_verdict_trigger_postgres.py test_db_migrations.py test_runtime_database_privileges.py`.
- frontend: `npm run build && npx playwright test --project=app verdict.spec.ts opportunity-record.spec.ts`.
- api_guard: T3·T9·T10(승인·입력 hash·회사 소속·외부 전송 차단).
- real_data_run: T12 실제 1건(폴리텍 fixture) — 사람 직전 확인, 결과는 `unmeasured_reference`, README에 attempt id·sha·호출 수·시간 기록. T11 mock은 대체가 아님.

## 결과

구현 후 작성한다.
