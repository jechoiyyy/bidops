# DEMO-01 최종 독립 리뷰

- 기준: DEMO-00 통합 commit `c242850`
- 대상: STEP-001~004 최종 동결본과 리더 단일 실행 증거
- 판정: **PASS**
- 차단 문제: 없음

## 판정 근거

1. 회사 identity와 API 경계가 계약에 맞는다. 회사 등록은 caller가 transaction을 소유하고 동일 identity에는 멱등이며 충돌은 닫힌다. strict 목록·상세와 회사별 tracking API는 demo flag가 꺼지면 UUID 검증이나 SPA fallback 전에 404로 닫히고 GET은 행을 만들지 않는다.
2. DB가 회사 계보를 최종 방어한다. `ProfileVersion`, `DeepReview`, `PreSpecCompanyFitAttempt`의 기존 행은 `company_id IS NULL`로 보존되며, FK와 trigger가 A→B, A→NULL, NULL→A를 모두 거부하고 NULL→NULL legacy 조합만 허용한다. profile/review/fit scope는 생성 뒤 바꿀 수 없고, 0001은 미래 ORM metadata를 읽지 않는 독립 snapshot으로 복구됐다. 0034는 clean DB와 기존 자료 경로, 단일 head, downgrade 경계를 함께 검사했다.
3. 기존 자동화는 legacy NULL 계보만 소비한다. active profile, overview 입력, fit/review 최신·목록, 자동 준비·enqueue, worker claim과 lease 회수에 회사 행이 섞이지 않는다. 원문 `Notice`·공유 `Opportunity`와 기존 tracking/recheck 필드는 회사별 결정으로 수정되지 않는다.
4. 회사별 tracking은 current projection, append-only event, idempotency receipt를 caller의 한 transaction에서 처리한다. exact replay는 저장 snapshot을 검증해 같은 결과를 반환하고, 다른 body·stale revision·event 충돌·손상 snapshot은 fail closed한다. 동일 상태의 새 request도 revision과 event를 증가시키며 reset은 current metadata만 비우고 감사 event는 보존한다. PostgreSQL 실제 `app` role의 최초 행 경합, 기존 current UPDATE, reset 권한 경로도 포함됐다.
5. runtime 권한은 app의 회사/current/event/idempotency 최소 읽기·쓰기와 current 허용 열 UPDATE, worker의 회사 identity 읽기로 제한된다. migration에는 runtime GRANT를 넣지 않았고 runtime privilege 스크립트가 현재 단일 head를 따른다.
6. 정본 문서는 구현 범위를 정확히 구분한다. 기존 `demo-contract.md`의 미실행 Luna 정책을 운영 1489건 검증으로 읽히게 하던 문구는 제거됐고, 실제 Luna 대표 인수는 DEMO-03 STEP-007 소유로 남았다. DEMO-01은 별도 데모 브랜치 구현이며 main·운영 반영으로 기록되지 않았다.

## 검증 증거

- STEP-001: PostgreSQL 17.11 schema·migration·권한·module boundary 관련 132건 통과 후 기대 목록 delta 4건 통과, skip 0.
- STEP-002: 신규 SQLite/PostgreSQL 변형 14건, 관련 기존 경로 121건, 명시적으로 활성화한 자동 경로 13건 통과. frontend build 통과.
- STEP-003: SQLite·PostgreSQL 17.11·실제 `app` role을 포함한 영향 검사 57건 통과, skip 0.
- STEP-004: 교차 회사·legacy 호환·동일 상태 새 결정·손상 receipt snapshot·실제 `app` role UPDATE/reset 사례 27건 통과, skip 0, 18.61초.
- 최종 동결 확인: `final-source-hashes.json` 34/34 일치, `source-baseline.json` 15/15 일치, 문서 doctor 6건 통과, `git diff --check` 통과.

검사는 리더가 한 번 실행했고, 이 리뷰는 동결 소스·migration·권한·테스트 assertion과 위 로그를 읽어 판정했다. 동일 검사를 다시 실행하지 않았다.

## 비차단 한계와 후속 게이트

- `test_the_flag_opens_preparation_for_sw_business_without_a_grade` 1건은 기준 commit `c242850`에서도 같은 assertion으로 재현된다. 기능 브랜치의 신규 회귀나 통과로 계산하지 않았으며 `step002-baseline-failure.md`에 분리돼 있다.
- main 병합, 운영 배포, migration 적용, 실제 모델 호출은 수행되지 않았다. 기존 deep-review/report/evidence ID 직접 조회·수정 경로 전수 검사는 main 병합 전 별도 게이트다.
- 실제 Luna 대표 1건은 DEMO-03 STEP-007, 실제 18/9건과 담당자 인수는 DEMO-05의 필수 게이트로 남는다.
