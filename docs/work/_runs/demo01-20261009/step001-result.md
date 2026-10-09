# DEMO-01 STEP-001 결과

- 기준: `sdlc/demo01-20261009-DEMO-01-company-context`, DEMO-00 완료 기준 `c242850`
- 범위: 회사 식별, 회사별 opportunity 추적 저장 모델, nullable 분석 계보, Alembic 0034, runtime head와 최소 권한
- 판정: PostgreSQL 17.11 관련 검사 최종 통과. 제품 소스 동결 후 STEP-002가 이어서 작업한다.

## 변경

- lifecycle 소유 `Company`, `CompanyOpportunityTracking`, append-only `CompanyTrackingEvent`를 추가했다. 원문 정본인 `Notice`와 공유 `Opportunity`에는 `company_id`를 추가하지 않았다.
- `ProfileVersion`, `DeepReview`, `PreSpecCompanyFitAttempt`에 nullable `company_id`를 추가했다. 기존 행은 backfill하지 않고 NULL 계보로 유지한다.
- review/fit의 `(profile_version_id, company_id)` 복합 FK와 PostgreSQL trigger를 함께 사용한다. 따라서 MATCH SIMPLE이 우회할 수 있는 A→NULL profile, NULL→A profile을 포함해 회사가 다른 모든 조합을 거부하고 NULL→NULL legacy 조합만 허용한다.
- profile/review의 회사 scope 변경을 DB와 ORM에서 막았다. fit은 기존 동결 입력 trigger/ORM guard가 `company_id`와 `profile_version_id` 변경을 막는다.
- DeepReview 입력 unique는 legacy NULL partial unique와 non-NULL 회사 scope partial unique로 분리했다. `PreSpecCompanyFitAttempt.input_sha256`의 전역 UNIQUE는 공통 계약 §8에 따라 유지했다. 새 회사 입력이 회사와 `execution_nonce`를 포함해 hash identity를 구분하는 계약이기 때문이다.
- `0034_company_context` migration을 현재 단일 head로 연결하고 runtime head를 갱신했다. migration 자체에는 GRANT가 없으며, `runtime-privileges.sql`에서 app은 회사/current/event 읽기·추가와 current의 허용 열 갱신만, worker는 회사 identity 읽기만 허용했다.
- 0001 migration이 현재 ORM metadata의 미래 열을 읽던 오염을 제거했다. 별도 Lean v1 metadata 복사본에서 0034의 두 `company_id`, FK·unique·partial index를 제외하고 원래 `uq_deep_review_inputs`를 복원한다.
- 닫힌 mapper/table 기대 집합에는 이번 회사 테이블 3개와 기존 DEMO-00의 preview/approval 2개 및 assumption 테이블 3개를 명시했다. `Base.metadata`로 기대값을 자기 유도하지 않는다.

## spec 연결

- T1: UUID 회사 identity와 slug/name/is_fictional 제약 및 원문 공유 경계를 구현했다. flag, `/companies`, `/api/companies`, 잘못된 UUID/없는 회사 응답은 STEP-002 API 범위다.
- T5: 빈 DB와 기존 DB migration, 단일/runtime head, legacy NULL 보존, 회사 scope FK·trigger, downgrade 안전 조건, 실제 runtime role 권한을 검사했다.
- T6: 회사 테이블의 lifecycle 소유, sibling 역방향 import가 없는 mapper 조합, 닫힌 table ownership을 검사했다. 공개 `register_company` service는 계획상 STEP-002 소유이며 이 단계에는 넣지 않았다.

## 검증

- 실행자: 리더 단일 실행
- 환경: `/tmp/bidops-demo00-verify-venv/bin/python`, Python 3.12.15, pytest 8.4.2, SQLAlchemy 2.0.52, psycopg 3.3.4, 일회용 PostgreSQL 17.11
- 선택 suite: company schema/제약, Alembic clean·existing 경로와 autogenerate, runtime privilege 정적·실제 role, mapper/module boundary 및 직접 영향 회귀
- migration 수정 뒤 선택 suite 결과: 132 passed, 0 skipped, 닫힌 기대 목록 4 failed
- 기대 목록 차이 수정 뒤 실패 4개만 재실행: 4 passed, 0 skipped
- 최종 판정: 선택된 136개 검사 모두 통과, skip 없음
- 로그: `step001-tests-after-index-fix.log`, `step001-schema-expectation-delta.log`
- 동결 소스 hash: `step001-source-hashes.json`

## 실패와 해결

1. 최초 두 실행은 0001의 live metadata가 0034 `ProfileVersion.company_id` FK를 미리 생성해 아직 없는 `bidops.company`를 참조하면서 collection 전에 중단됐다. Lean v1 metadata snapshot으로 바꿔 해결했다. 근거는 `step001-migration-diagnostic.log`다.
2. 첫 수정 뒤 `uq_deep_review_legacy_inputs`의 predicate가 제거된 `company_id`를 참조했다. 0034 partial index 두 개를 snapshot에서 이름으로 제외하고 0001 원래 unique만 복원했다. 근거는 `step001-migration-diagnostic2.log`다.
3. migration이 정상화된 뒤 남은 4건은 제품 결함이 아니라 닫힌 기대 집합의 기존 DEMO-00 누락이었다. preview/approval 및 assumption 테이블을 명시 목록에 넣고, 이번 회사 3개를 포함한 정확 비교를 유지했다.

## 후속 주의

- 회사 등록 공개 service, feature flag/API 404·422 계약과 GET 무쓰기 검사는 STEP-002에서 완성해야 한다.
- 회사별 tracking transaction과 idempotency/event 원자성은 STEP-003 범위다. 현재 모델·권한이 그 저장 경계만 제공한다.
- 기존 unscoped API/worker가 non-NULL 회사 review/fit을 배제하는 필터는 후속 단계에서 구현·검사해야 한다.
- migration은 legacy 행을 회사에 귀속하지 않는다. 후속 코드도 NULL 계보를 임의 회사로 보정하거나 원문 Notice/Opportunity에 회사를 기록하면 안 된다.
