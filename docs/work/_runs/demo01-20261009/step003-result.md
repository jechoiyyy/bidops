# STEP-003 회사별 추적 transaction 구현 결과

## 구현

- `GET/PATCH /api/companies/{company_id}/opportunities/{opportunity_id}/tracking`과 strict request/response DTO를 추가했다.
- 행이 없을 때 GET은 `미선택`, revision 0, null metadata를 합성하며 DB row를 만들지 않는다.
- PATCH는 기존 actor·reason·tracking status 검증을 재사용하고, trim한 reason에 1..2000자 제한을 적용한다.
- 회사별 current projection, append-only decision event, 기존 `IdempotencyRecord` receipt를 caller의 한 transaction에서 flush한다.
- reset은 current metadata를 null로 만들지만 event에는 reason·actor·request ID·시각을 보존한다.
- 기존 current row는 `SELECT FOR UPDATE`로 잠근다. 최초 row는 savepoint에서 최종 revision-1 projection을 INSERT하며, current composite PK 충돌만 동시 winner로 인정한다. 충돌 뒤 receipt를 다시 확인하고, 같은 key/body는 저장 snapshot을 strict 검증한 뒤 그대로 replay하며 다른 body는 `idempotency_conflict`, 다른 request의 오래된 revision은 `version_conflict`로 닫는다.
- 회사별 경로는 shared `Opportunity.tracking_*`와 `recheck_*`를 수정하거나 legacy tracking hook을 호출하지 않는다.
- STEP001의 app 권한(회사/current/event/idempotency 조회·추가와 current 허용 열 UPDATE)만 사용한다. STEP003 권한 변경은 없다.

## 검사 코드

- SQLite와 PostgreSQL 변형에 회사 3사의 독립 결정, GET 무쓰기, exact receipt replay, 다른 body 충돌, stale revision, reset 감사, legacy tracking/recheck 불변을 연결했다.
- strict body, UTF-8 percent actor decode, reason 길이, 없는 회사·사업기회 경계를 추가했다.
- event unique 충돌이 current와 receipt를 함께 rollback하는 fail-closed 사례를 추가했다.
- PostgreSQL 실제 `app` role의 동일 missing current row 동시 요청을 두 갈래로 검사한다. 같은 key는 winner snapshot exact replay, 다른 request ID는 한 건 성공과 한 건 `version_conflict`여야 한다.

## 변경 파일

- `web/backend/app/lifecycle/schemas/companies.py`
- `web/backend/app/lifecycle/routers/companies.py`
- `web/backend/app/lifecycle/services/opportunity_tracking.py`
- `web/backend/tests/app/test_company_context.py`

## 검증 상태

구현자는 리더 단일 실행 규칙에 따라 테스트를 실행하지 않고 `git diff --check`만 확인했다.
리더가 SQLite·PostgreSQL 17.11 및 실제 `app` role을 포함한 STEP003 영향 검사를 실행해
57 passed, 0 skipped(21.51초)를 확인했다. 실행 로그는 `step003-tests.log`다.
