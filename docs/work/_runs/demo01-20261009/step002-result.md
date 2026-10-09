# DEMO-01 STEP-002 결과

- 기준: `sdlc/demo01-20261009-DEMO-01-company-context`, DEMO-00 완료 기준 `c242850`
- 범위: 회사 등록 공개 seam과 strict 조회 API, 데모 flag/404 guard, 기존 자동화·최신·목록의 legacy NULL 계보 경계
- 판정: STEP-002 신규 SQLite/PostgreSQL 변형과 직접 영향 검사가 통과했다. 기준 commit에서도 재현되는 자동 준비 기존 실패 1건은 이 단계 범위 밖으로 분리했다.

## 변경

- caller가 transaction을 소유하는 `register_company`를 lifecycle 공개 seam으로 추가했다. 같은 slug와 identity는 멱등이고 다른 identity는 `company_identity_conflict`이며, 등록과 감사 이벤트는 함께 commit 또는 rollback된다.
- `GET /api/companies`와 `GET /api/companies/{company_id}`를 strict DTO로 추가했다. 목록은 slug 순서와 pagination을 지키며 GET은 쓰지 않는다.
- `BIDOPS_DEMO_ENABLED` 기본값을 false로 추가했다. `/api/demo-config`는 항상 `{enabled}`만 반환하고, 비활성 상태의 `/companies`·하위 경로와 company-comparison UI/API는 UUID 검증이나 SPA fallback 전에 404가 된다.
- legacy active profile·digest 재사용, overview profile 동결, review/fit 최신·목록·집계, 자동 준비, stale recovery와 worker claim을 `company_id IS NULL` 계보로 한정했다. 기존 ID 직접 조회·수정 경로와 STEP-003 tracking transaction은 건드리지 않았다.
- `prespec_projection`·`deep_review_hooks`는 수정된 공용 service를 소비하고, analysis worker는 `DeepReviewService.claim_next_job`을 소비하므로 중복 규칙을 추가하지 않았다.
- 외부 모델 호출과 배포는 각각 0회다.

## 검증

- 실행자: 리더 단일 실행
- 초기 선택 suite: 신규 7개와 기존 직접 영향 121개, 합계 128개. 결과 125 passed / 3 failed. 실패는 SQLite savepoint 이전 외부 transaction 부재 1건과 잘못된 `DeepReviewService` fixture 인자 2건이었다.
- 신규 파일을 SQLite와 실제 migrated PostgreSQL로 확장한 14개 변형: 11 passed / 3 failed. 남은 3건은 PostgreSQL이 드러낸 fixture FK insert 순서 2건과 company-fit bound input 누락 1건이었다.
- fixture를 실제 FK·bound payload 계약에 맞춘 뒤 실패한 PostgreSQL 3건만 재실행: 3 passed.
- 회사 API strict shape와 caller rollback의 Company/AuditEvent 0건은 PostgreSQL 변형에서 통과했다.
- 기존 자동 경계 77개: 기본 `BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`로 기대 분기에 들어가지 않은 13개는 명시적 true 격리 환경에서 모두 통과했다. 최종 76 passed / 기존 실패 1개다.
- frontend build: passed.
- 로그: `step002-tests.log`, `step002-company-delta.log`, `step002-postgres-fixture-delta.log`, `step002-legacy-boundaries.log`, `step002-legacy-enabled-delta.log`, `step002-frontend-build.log`
- 동결 제품 소스 hash: `step002-source-hashes.json`

## 실패와 해결

1. Python SQLite driver는 SELECT만으로 물리 transaction을 시작하지 않아 첫 SAVEPOINT 해제가 등록 행을 지속시켰다. SQLite에서 savepoint 전에 외부 transaction을 명시해 caller rollback이 Company와 AuditEvent를 함께 되돌리도록 했다. PostgreSQL transaction 동작은 유지했다.
2. 신규 worker fixture가 존재하지 않는 생성자 인자를 넘기던 오류를 실제 `DeepReviewService` 계약에 맞췄다.
3. PostgreSQL fixture는 회사 parent를 먼저 flush하고, company-fit trigger가 요구하는 10개 bound input을 실제 열 값과 일치시켰다. 제품 DB 제약은 완화하지 않았다.

## 기존 실패

`test_the_flag_opens_preparation_for_sw_business_without_a_grade`는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`에서도 bundle service 호출 전 멈춘다. STEP-002의 `auto_preparation.py` 변경은 이후 legacy deep-review 조회 두 곳의 `company_id IS NULL` 필터뿐이며, DEMO-00 기준 `c242850`에서도 같은 assertion이 재현됐다. 따라서 현재 단계의 회귀가 아니라 기존 자동 준비 테스트·자격 경계의 불일치로 판정하고 제품 범위를 넓혀 수정하지 않았다.
