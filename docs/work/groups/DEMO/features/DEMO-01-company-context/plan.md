# 회사 문맥과 독립 추적 — plan

- 기능 ID: `DEMO-01-company-context`
- 작성일: 2026-10-06
- 근거: [intent](intent.md), [spec](spec.md)

## 변경 파일

경로는 저장소 루트 기준. `<next>` migration은 구현 시 실제 단일 head의 후속 번호로 생성한다.
번호를 선점하지 않으며 core/db.py의 runtime head와 `scripts/runtime-privileges.sql` 권한을 함께 갱신한다(migration에 GRANT를 쓰지 않는다).
기준은 DEMO-00이 통합된 main에서 분기한 별도 데모 브랜치와 `bidops-local` 격리 자원이다. 새 기능 run으로 시작하며 main이나 운영에 반영하지 않는다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/lifecycle/models.py | 수정 | 회사/current/event(멱등성은 core IdempotencyRecord) |
| web/backend/app/lifecycle/services/company_context.py | 신규 | 회사 조회/등록·공개 context |
| web/backend/app/lifecycle/services/opportunity_tracking.py | 수정 | 공통 검증·회사별 transaction |
| web/backend/app/lifecycle/routers/companies.py | 신규 | 회사 strict 목록·상세와 회사별 tracking GET/PATCH API |
| web/backend/app/lifecycle/schemas/companies.py | 신규 | strict DTO |
| web/backend/app/lifecycle/__init__.py | 수정 | 공개 등록 service |
| web/backend/app/deep_review/models.py | 수정 | nullable 회사 FK |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | unscoped 최신 조회 NULL scope |
| web/backend/app/deep_review/services/company_fit_runner.py | 수정 | legacy claim/enqueue NULL scope |
| web/backend/app/deep_review/services/auto_preparation.py | 수정 | 자동 준비/심층 latest NULL scope |
| web/backend/app/deep_review/services/company_fit.py | 수정 | NULL 회사 최신 조회 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | legacy active profile·digest 재사용을 NULL 회사로 제한 |
| web/backend/app/deep_review/services/overview_runs.py | 수정 | 개요의 전역 active profile에서 회사 profile 배제 |
| web/backend/app/core/config.py | 수정 | BIDOPS_DEMO_ENABLED |
| web/backend/app/main.py | 수정 | router 조립·`GET /api/demo-config`·SPA fallback 앞 404 guard |
| web/backend/alembic/versions/0001_lean_v1_postgresql.py | 수정 | 빈 DB bootstrap가 live ORM의 후속 회사 스키마를 조기 생성하지 않도록 historical snapshot 고정 |
| web/backend/alembic/versions/0034_company_context.py | 신규 | 회사 스키마 migration(권한은 runtime-privileges.sql) |
| web/backend/app/core/db.py | 수정 | runtime head |
| web/backend/app/core/api_errors.py | 수정 | 새 오류 code 등록(회사 경로) |
| web/frontend/src/lib/apiErrors.ts | 수정 | `company_identity_conflict` 안전 문구 등록 |
| scripts/runtime-privileges.sql | 수정 | 새 테이블·열의 app/worker/ro_backup 권한 |
| web/backend/tests/app/test_runtime_database_privileges.py | 수정 | 새 권한 기대값 |
| web/backend/tests/app/test_company_context.py | 신규 | 회사 API strict shape·등록 transaction·legacy scope의 SQLite/PG 변형 |
| web/backend/tests/app/test_company_context_schema.py | 신규 | migration·FK·NULL legacy lineage의 PostgreSQL 계약 |
| web/backend/tests/app/test_db_migrations.py | 수정 | 새 head와 historical bootstrap 회귀 |
| web/backend/tests/app/test_deep_review_migrations.py | 수정 | historical snapshot가 후속 회사 열·index를 만들지 않는 경계 |
| web/backend/tests/app/test_assumption_analysis.py | 수정 | nullable 회사 FK를 반영한 schema 기대값 |
| web/backend/tests/app/test_mapper_isolation.py | 수정 | lifecycle/deep-review 회사 관계 mapper 격리 검증 |
| web/backend/tests/app/boundary_map.py | 수정 | 회사 context 공개 seam의 모듈 소유권 등록 |
| web/backend/app/deep_review/services/opportunity_reviews.py | 수정 | 사업별 리뷰 목록·집계 NULL scope |
| docs/work/demo-contract.md | 수정 | DEMO-00 v4 로컬 구현과 미실행 Luna 게이트, LiteLLM 핏 transport·승인 경계 정정 |
| docs/business-rules.md, docs/contracts.md | 수정 | DEMO-01 데모 브랜치 구현과 DEMO-02~05 미구현 범위 구분 |
| docs/deep-review-erd.md, docs/ARCHITECTURE.md | 수정 | nullable 회사 계보·모듈 소유 현재 상태와 후속 graph/분석 범위 구분 |
| docs/work/source-baseline.json | 수정 | 위 정본 문서의 변경 hash 갱신 |

`prespec_projection.py`와 `deep_review_hooks.py`는 각각 수정된 `auto_preparation`·회사 핏 공용 service를 소비하므로 소스를 중복 수정하지 않고 통합 사례로 간접 검증한다. 분석 worker도 `DeepReviewService.claim_next_job`을 공용 진입점으로 쓰므로 NULL 회사 claim 경계는 그 service와 worker claim 사례에서 검증한다.

## 작업 순서

1. STEP-001 회사 식별과 migration [complex]
   - 목표: 회사 식별과 migration의 수용 조건을 충족한다.
   - 작업 대상: Company·nullable FK·runtime-privileges.sql·runtime head.
   - 검증: spec T1,T5,T6; 아래 명령과 해당 단계 증거.
2. STEP-002 회사 API와 기존 조회 경계 [complex]
   - 목표: 회사 API와 기존 조회 경계의 수용 조건을 충족한다.
   - 작업 대상: context/DTO·demo-config·서버 404 guard·api_errors·자동 worker/hook과 unscoped 최신/목록 NULL scope.
   - 검증: spec T1,T4,T6; 아래 명령과 해당 단계 증거.
3. STEP-003 회사별 추적 transaction [complex]
   - 목표: 회사별 추적 transaction의 수용 조건을 충족한다.
   - 작업 대상: current/event·IdempotencyRecord·경합·reset.
   - 검증: spec T2,T3; 아래 명령과 해당 단계 증거.
4. STEP-004 교차 회사·호환 인수 [complex]
   - 목표: 교차 회사·호환 인수의 수용 조건을 충족한다.
   - 작업 대상: PG/API·자동 enqueue/claim/latest의 회사 행 배제 회귀 및 계약 반영.
   - 검증: spec T1~T6; 아래 명령과 해당 단계 증거.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-002 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-003 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-004 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |

## 검사 명령과 증거

아래는 구현 후 리더가 단일 실행자로 수행하는 영향 검사다. STEP-004에서 추가·수정한
사례는 리더 실행 전까지 통과로 적지 않는다.

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_company_context.py tests/app/test_tracking_lifecycle_flow.py tests/app/test_module_selection.py tests/app/test_module_boundaries.py tests/app/test_alembic_autogenerate.py tests/app/test_runtime_database_privileges.py -q
```

PostgreSQL 대상은 일회용 postgres:17.11과 BIDOPS_TEST_POSTGRES_URL을 사용한다.
운영 DB를 연결하지 않는다. backend 기본 검사에는 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
overview=true가 필요한 사례만 fixture에서 설정한다.
실제 로그/exit code/skip/수동 증거는 `docs/work/_runs/demo01-20261009/`에 남긴다.
선행 검사 결과를 현재 변경의 검사로 적지 않는다. 변경 뒤 영향받은 검사만 재실행한다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 회사 scope 누락 | A 결과가 B 또는 legacy 응답에 표시 | 읽기/쓰기 경계와 FK 수정 후 교차 회사 재검사 |
| 새 테이블 권한 누락 | 데모 스택에서 permission denied | runtime-privileges.sql과 T5 권한 검사 |
| 미점검 ID 직접 API | 회사 review ID를 기존 경로로 열면 노출 | 데모 브랜치 전용·운영 미배포, main 병합 전 별도 기능 |
| 범위 확장 | 후속 구현/운영 호출을 현재 완료로 표시 | 기능별 수용 조건과 실제 증거를 분리 |

## 증명

- docs: 공통 계약·정본·3문서 일치, 지정 모델 독립 리뷰, diff/링크/STEP 검사.
- tests: 모든 spec T ID를 위 STEP과 assertion에 연결해 명령/결과/skip 기록.
- postgres: DB/API shape 변경 시 임시 PG 검사+head/권한; 아니면 N/A 이유 기록.
- frontend: UI 변경 시 build+두 폭 의미/구조; 아니면 N/A 이유 기록.
- api_guard: 회사 소속/모델 경계 변경 시 승인·hash·호출 0 검사; 아니면 N/A 이유 기록.
- real_data_run: DEMO-05에서 실제 18/9건·담당자 인수; 다른 기능은 N/A(소유 DEMO-05).

## 결과

STEP-001~003 제품 구현은 DEMO-00 통합 기준 `c242850`에서 분기한 별도 데모 브랜치에만 있다.
main·운영 반영, 배포, migration 적용, 모델 호출은 수행하지 않았다. STEP-004는 제품 소스를
확장하지 않고 교차 회사·legacy 호환 assertion과 정본 문서만 보완한다.

| spec | assertion·판정 범위 | 증거 |
|---|---|---|
| T1 | demo flag 404 guard, strict 회사 목록·상세, GET 무쓰기, 없는/잘못된 UUID | `test_demo_config_and_disabled_routes_are_guarded_before_validation`, `test_company_list_and_detail_are_strict_sorted_and_read_only`; `step004-tests.log` |
| T2 | 3사의 동일 opportunity 독립 상태와 legacy tracking/recheck 불변 | `test_company_tracking_is_independent_replayable_and_leaves_legacy_state`; `step004-tests.log` |
| T3 | exact replay, 다른 body/stale 충돌, 동일 상태의 새 결정, reset 감사, 손상 snapshot fail-closed, PostgreSQL app-role 경합·UPDATE | `test_company_tracking_*`; `step004-tests.log` |
| T4 | legacy latest/목록, auto-preparation, 자동 enqueue, fit/deep-review claim·lease 회수의 회사 행 배제 | `test_legacy_*`, `test_company_fit_projection_claim_and_recovery_use_only_null_lineage`; `step004-tests.log` |
| T5 | 0034 clean/existing migration, NULL 계보, FK·trigger, runtime 역할 권한 | `step001-tests-after-index-fix.log` 132 pass + `step001-schema-expectation-delta.log` 4 pass, skip 0; STEP-004 DB 스키마 변경 없음 |
| T6 | lifecycle 소유·공개 `register_company`, 역방향 import 없음, 모듈 조합 | `step003-tests.log` 57 pass, skip 0의 module boundary 포함; STEP-004 doctor 6 pass·diff check pass·source baseline 불일치 0 |

STEP-004 변경 사례는 일회용 PostgreSQL 17.11의 실제 `app` role 변형을 포함해 27 passed,
0 skipped(18.61초)다(`docs/work/_runs/demo01-20261009/step004-tests.log`). 문서 doctor는 6 passed,
`git diff --check`는 pass, `source-baseline.json` 불일치는 0이다.

STEP-002의 `test_the_flag_opens_preparation_for_sw_business_without_a_grade` 1건은 main `c242850`에서도 같은 assertion으로
재현된 기존 한계다(`step002-baseline-failure.md`). 이 기능에서 고치거나 통과로 적지 않는다.
DEMO-03 STEP-007의 실제 Luna 대표 인수와 DEMO-05의 18/9건·담당자 인수는 후속 필수 게이트로 남아 있다.
