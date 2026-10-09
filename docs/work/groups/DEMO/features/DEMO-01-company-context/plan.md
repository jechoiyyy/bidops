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
| web/backend/app/lifecycle/routers/companies.py | 신규 | 회사·tracking API |
| web/backend/app/lifecycle/schemas/companies.py | 신규 | strict DTO |
| web/backend/app/lifecycle/__init__.py | 수정 | 공개 등록 service |
| web/backend/app/deep_review/models.py | 수정 | nullable 회사 FK |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | unscoped 최신 조회 NULL scope |
| web/backend/app/deep_review/services/company_fit_runner.py | 수정 | legacy claim/enqueue NULL scope |
| web/backend/app/deep_review/services/auto_preparation.py | 수정 | 자동 준비/심층 latest NULL scope |
| web/backend/app/deep_review/services/company_fit.py | 수정 | NULL 회사 최신 조회 |
| web/backend/app/core/config.py | 수정 | BIDOPS_DEMO_ENABLED |
| web/backend/app/main.py | 수정 | router 조립·`GET /api/demo-config`·SPA fallback 앞 404 guard |
| web/backend/alembic/versions/<next>_company_context.py | 신규 | 스키마 migration(권한은 runtime-privileges.sql) |
| web/backend/app/core/db.py | 수정 | runtime head |
| web/backend/app/core/api_errors.py | 수정 | 새 오류 code 등록(회사 경로) |
| scripts/runtime-privileges.sql | 수정 | 새 테이블·열의 app/worker/ro_backup 권한 |
| web/backend/tests/app/test_runtime_database_privileges.py | 수정 | 새 권한 기대값 |
| web/backend/tests/app/test_company_context.py | 신규 | scope·호환·경합·PG |
| web/backend/app/deep_review/services/opportunity_reviews.py | 수정 | 사업별 리뷰 목록·집계 NULL scope |
| web/backend/app/deep_review/services/prespec_projection.py | 수정 | legacy projection |
| web/backend/app/deep_review/services/deep_review_hooks.py | 수정 | 자동 생성 scope |
| web/backend/app/workers/analysis.py | 수정 | worker NULL/company 구분 |

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

아래는 구현 후 실행할 명령이다. 신규 테스트는 아직 없으며 통과를 주장하지 않는다.

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_company_context.py tests/app/test_tracking_lifecycle_flow.py tests/app/test_module_selection.py tests/app/test_module_boundaries.py tests/app/test_alembic_autogenerate.py tests/app/test_runtime_database_privileges.py -q
```

PostgreSQL 대상은 일회용 postgres:17.11과 BIDOPS_TEST_POSTGRES_URL을 사용한다.
운영 DB를 연결하지 않는다. backend 기본 검사에는 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
overview=true가 필요한 사례만 fixture에서 설정한다.
실제 로그/exit code/skip/수동 증거는 `docs/validation-runs/<actual-date>-company-demo/DEMO-01-company-context/`에 남긴다.
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

미구현. 문서 검토와 제품 검증을 구분한다. 실제 작업 후 차이·재시도·증거·커밋 여부를 기록한다.
