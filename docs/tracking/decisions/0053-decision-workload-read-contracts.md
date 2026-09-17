# ADR-0053: 결정 대기 조회와 모듈 소유 집계 계약

- 상태: 채택
- 결정일: 2026-09-07
- 이식일: 2026-09-09 — 이 결정의 백엔드 구현은 미병합 브랜치에 있다가 한 번 유실됐고, `main`에는 확장점(`WorkloadCount`·`WorkloadProjection`·`register_workload_projection`·`workload_counts`)과 프론트 타입만 남아 있었다. 2026-09-09에 백엔드 수직 슬라이스를 다시 이식했다.
- 관련 결정: [모듈 경계 ADR-0045](0045-backend-module-layout.md), 정보구조 ADR-0046(git 이력 docs/design/ADR.md, 삭제됨)

## 배경

페이지를 받은 뒤 브라우저가 필터·건수를 다시 계산하면 누적 대상과 다른 분모를 보여 준다. 대시보드 업무 집계는 여러 모듈이 소유하지만 lifecycle이 형제 모듈의 ORM을 읽는 방식으로 해결할 수 없다. 발주계획 추적 저장은 기존 소유 사업기회와 감사 이벤트로 수행할 수 있다.

## 결정

1. 결정 대기 조회의 신규 GET은 `/api/workload`, `/api/opportunities/{opportunity_id}/deep-reviews`, `/api/bid-delta/decision-queue` 세 개이고, `GET /api/pre-specs`에 optional `auto_preparation_status` 필터를 더한다. 네 번째인 `/api/opportunities/{opportunity_id}/tracking-decisions`는 이미 `main`에 있다. 세 모듈을 조립한 OpenAPI 경로 수는 82개다. DB 테이블·열·migration은 추가하지 않는다.
2. 최신 완료 실행의 범위, 다중 필터, 구역 우선순위, 전체 count와 페이지는 서버에서 결정한다. 없는 결과와 unknown을 구별한다. 행 수에 비례하는 SQL·HTTP 조회를 만들지 않는다.
3. lifecycle은 읽기 확장점·registry를 소유한다. `auto_preparation_status` 필터는 lifecycle이 `OverviewDocumentProjection.notice_ids_for_auto_preparation_status`로 받아 자기 조건에 AND한다. screening은 미답변 차단 공고·개수(`JudgmentProjection.open_blocking_item_counts`·`notice_ids_with_open_blocking_items`)와 발주계획 검토 대기(`order_plan_pending`)를, deep_review는 심층 검토 클릭 대기(`pre_spec_deep_review_ready`)와 입찰 최종 결정 대기(`bid_final_decision_pending`)를 제공한다. 조립 시 각 제공자를 등록하고 업무 집계는 제공자마다 한 번 호출한다. 역방향 import나 router ORM을 추가하지 않는다.
4. `tracking_action_required`는 제공자가 아니라 lifecycle이 자기 목록과 **같은 첫 일치 규칙**(`count_opportunity_section`)으로 센다. 목록의 `조치 필요` 구역 수와 workload 값은 언제나 같은 모집단이다.
5. 제공자 부재와 실제 0을 구분한다. workload 항목은 `count=null`과 안전한 사유(`provider_absent`·`no_completed_execution`)를 보존하고, 제공자가 실제로 0을 셌으면 정수 0과 `unavailable_reason=null`이다. 표식 없음을 0으로 승격시키지 않는다.
6. 최종 결정 큐와 기존 입찰 delta workspace는 **동일한 currentness 규칙을 한 곳**(`services/bid_delta_currentness.comparison_currentness`)에서 단건·batch로 공유한다. 단건 경로(`BidDeltaService._currentness`)는 그 함수를 부르며 규칙을 복제하지 않는다. pending은 "입찰공고가 연결됐고 최종 결정이 없거나 그 결정이 `stale`인 것"이며, 기결정 `unknown`과 `stale`을 구분한다.
7. 심층 검토 목록은 사업기회에 연결된 공고 전체를 중복 제거해 읽고, 후보 링크도 포함한다. 이 목록은 소유권 확정이 아니라 안전한 색인이다. 품질 표식은 배치 계산(`quality_status_for_reviews`)이며 표식 없음(`null`)을 미측정이나 측정으로 승격시키지 않는다.
8. 비교를 실제 계산하는 worker와 정책 활성화는 이 결정에 포함하지 않는다. 조회 편의가 모델 호출·외부 전송·추적 승인·최종 Go/No-Go를 자동 수행하지 않는다.

## 대안과 결과

- 브라우저 페이지 내 필터·합산은 전체 분모를 보장하지 못하므로 채택하지 않았다.
- lifecycle에서 형제 ORM을 직접 읽는 방식은 모듈 물리 격리를 깨므로 확장점으로 대체했다.
- 추적 전용 테이블·POST는 기존 상태·감사를 중복하므로 추가하지 않았다.
- 단건·batch currentness를 각각 구현하는 방식은 같은 업무 규칙이 두 벌이 되므로 채택하지 않았다.

모듈 격리, PostgreSQL 검색·집계·페이지, 목록과 workload의 동일 건수, 모집단이 커져도 상수인 조회 수를 함께 검증한다. 상세 필드는 [contracts.md](../../contracts.md)가 정본이다.

## 개정 (2026-09-17)

[사업 추적 연결·조치 고도화](../../0917_opportunity-tracking/intent.md)가 결정 1의 항목 수를
넷에서 **다섯**으로 늘린다. `tracking_hold_review_due`를 `GET /api/workload`에 추가하고, 값은
lifecycle이 `GET /api/opportunities?hold_review=overdue`와 같은 첫 일치 규칙으로 직접 센다
(결정 4의 "제공자가 아니라 lifecycle이 직접 센다" 원칙을 그대로 따른다). `items`의 고정 순서는
`order_plan_pending`, `pre_spec_deep_review_ready`, `tracking_action_required`,
`tracking_hold_review_due`, `bid_final_decision_pending`이다.

`tracking_action_required`가 세는 **모집단(`조치 필요` 구역)의 정의도 바뀐다.** 이전에는 서버가
구현한 첫 일치 규칙이 사유 없는 `미선택` 신규 입찰공고까지 섞어 셌다. 이번 계획은 구역과 사유를
분리해, `조치 필요`는 추적 대상(`계속 추적`·`보류`·`종료`)의 할 일만 세고 입찰공고로 처음 등록된
미선택 건은 별도 구역 `신규 입찰공고`로 뺀다(spec §7.2). `tracking_action_required`와 목록의
`조치 필요` 구역 건수가 항상 같은 모집단이라는 이 ADR의 결정 4는 그대로 유지되며, 다만 그
모집단 자체가 이번 계획으로 좁아졌다.

결정 6(최종 결정 큐·currentness 단일 규칙)은 [ADR-0058](0058-final-decision-basis-separated-from-comparison.md)이
근거별(`comparison`\|`notice_conditions`) 계산으로 확장했다 — "동일한 currentness 규칙을 한 곳"
원칙은 유지되고 그 한 곳이 근거를 함께 인식하게 됐을 뿐이다.
