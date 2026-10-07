# 회사 문맥과 독립 추적 — spec

- 기능 ID: `DEMO-01-company-context`
- 작성일: 2026-10-06 (같은 날 재계획 개정)
- 근거: [intent](intent.md), [공통 계약](../../../../demo-contract.md) §1·2·8
- 상태: 구현 목표. 현재 제품 계약과 구별한다. 데모 브랜치 전용이며 운영에 배포하지 않는다.

## 큰 틀 문서와의 관계

ADR-0070(개정 포함) 및 기존 정본의 DEMO 목표 절을 구체화한다.
공통 계약 §1·2·8의 필드·필수/nullable·enum 전체·식별/유일성·실패 규칙은 이 spec의 일부다.
기존 단일회사 wire·불변성은 유지한다. 계약 변경은 관련 기능/정본에 함께 반영한다.

## 입력·출력 계약 및 저장

Company·CompanyOpportunityTracking·CompanyTrackingEvent는 lifecycle 소유다.
current PK=(company_id,opportunity_id), event PK=UUID와 (company_id,opportunity_id,revision) UNIQUE다.
멱등성은 별도 receipt 테이블 없이 core `IdempotencyRecord`를 쓴다(operation=`company_tracking.set`, 공통 §8).
현재 상태·감사 event·IdempotencyRecord는 같은 transaction, shared Opportunity의 tracking/recheck 필드는 수정하지 않는다.
공통 actor/reason/state 검증은 기존 tracking service(`_validate_human_name`·`_validate_reason`·`TRACKING_STATUSES`)를 재사용하고 저장 대상을 명시적으로 분기한다.
reason은 기존과 달리 trim 뒤 1~2000자 상한을 둔다. expected_revision 불일치는 기존 409 version_conflict다.
등록용 lifecycle 공개 service `register_company`는 이 기능에서 `app/lifecycle/__init__.py` 공개 이름으로 제공하고 실제 원본 CLI는 DEMO-02가 연결한다.
단독 검사 fixture는 이 공개 service로 회사를 만들며 startup seed를 넣지 않는다.
ProfileVersion/DeepReview/PreSpecCompanyFitAttempt에 nullable company_id를 추가한다.
같은 profile을 참조하는 review/fit의 회사가 일치하도록 composite FK를 사용하고 NULL legacy의 기존 FK도 유지한다.
기존 unique 입력은 NULL 계보에서 유지하고 회사 scope 키를 새 행에 적용한다.
회사 행을 배제해야 하는 기존 읽기는 자동 worker·hook(company_fit_runner `_enqueue_one`·`run_once` claim, auto_preparation,
deep_review_hooks, analysis worker)과 unscoped 최신 결과·목록·집계 조회다. 이들은 company_id IS NULL만 고른다.
기존 보고서·근거·최종 의견의 ID 직접 조회·수정·재시도 경로 전수 점검은 범위 밖이며 main 병합 전 별도 기능으로 넘긴다.
`GET /api/demo-config`와 SPA fallback 앞 서버 404 guard는 이 기능이 `main.py`에 구현한다(공통 §1).
새 테이블·열 권한은 `scripts/runtime-privileges.sql`, 새 오류 code는 `core/api_errors.py`에 등록한다.
새 회사 분석 API는 DEMO-03 소유다. 이 기능에서 그래프·모델 경로를 구현하지 않는다.

## 인터페이스·상태·실패

공통 계약 §1·2·8의 endpoint/DTO를 사용한다. 추적 상태 enum은 기존 Opportunity와 같은 미선택|계속 추적|보류|종료다.
unknown/null·준비 전·stale·실패·참조 표식을 성공/부적합으로 변환하지 않는다.
쓰기 전에 회사 소속을 검사한다. 원문 경로·secret·모델 본문·actor 문자열을 일반 응답/로그에 노출하지 않는다.

## 설정 키와 기본값

| 키 | 기본값 | 허용/적용 | 근거 |
|---|---|---|---|
| BIDOPS_DEMO_ENABLED | false | bool; 격리 데모에서 명시 활성 | 운영 경계 |
| BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED | false | 기존 bool | 사람 요청 분석 |
| tracking reason 길이 | 1~2000 | trim 뒤 | 공통 §2 |

## 결정과 이유

| 결정 | 근거 | 적용하지 않는 대안 |
|---|---|---|
| 회사/입력 버전 명시 | 사용자 전환·비교 선택 | 전역 프로필 교체 |
| 기존 IdempotencyRecord 재사용 | 2026-10-06 재계획: 2주 범위, 기존 관례 | X-Request-ID·새 receipt 테이블 |
| 자동 경로만 회사 배제 | 데모 브랜치 전용(운영 미배포) | 기존 ID 직접 API 전수 점검(main 병합 전 별도) |
| 실제 인수 분리 | 실제 결과 선택·기존 Luna 실패 이력 | mock을 실제 성공으로 집계 |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | flag/UUID/없는 회사 | BIDOPS_DEMO_ENABLED=false에서 /companies·/api/companies 404·demo-config {enabled:false}·UUID 422·없음 404·GET 무쓰기 | API |
| T2 | 회사별 동일 공고 결정 | A/B 독립·C 미선택·legacy Opportunity tracking 필드 그대로 | PG 통합 |
| T3 | replay/경합/reset | 같은 request_id 같은 body는 최초 응답·중복 event 없음, 다른 body 409 idempotency_conflict, stale 409 version_conflict, reset 감사 보존 | PG 통합 |
| T4 | 자동 경로·unscoped 조회 | 회사 소유 fit/review 행을 company_fit_runner enqueue/claim·auto_preparation·deep_review_hooks·worker·unscoped 최신/목록이 고르지 않음, NULL 응답 유지 | 회귀/API |
| T5 | migration/권한/빈 DB/기존 DB | 단일 head·runtime 일치·legacy NULL 보존·새 테이블 app/worker 권한이 runtime-privileges.sql과 일치 | PG |
| T6 | 모듈 조합/공개 service | lifecycle 단독 조회·역방향 import 없음·register_company 공개 이름 | 모듈 통합 |

## 컨벤션 반영 항목

새 회사 경로·origin·graph/version identity는 공통 계약, 상태 분리는 business-rules,
DB·외부 호출은 해당 정본의 DEMO 절에 반영한다. 구현 목표를 현재 동작으로 표시하지 않는다.
