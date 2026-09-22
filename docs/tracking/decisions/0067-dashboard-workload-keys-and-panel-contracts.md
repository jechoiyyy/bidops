# ADR-0067: 실무자 대시보드의 누적 업무 키와 패널 계약

- 상태: 채택
- 결정일: 2026-09-22
- 근거 시안: `docs/0915_ui-redesign/mockups/0921_practitioner-m5-m6/`(M6, 2026-09-22 승인)
- 관련 결정: [ADR-0053](0053-decision-workload-read-contracts.md)(업무 집계 읽기 계약),
  [ADR-0045](0045-backend-module-layout.md)(모듈 경계와 확장점),
  [ADR-0064](0064-prespec-actionable-deadline-scope.md)(사전규격 마감 구간),
  [ADR-0066](0066-practitioner-ops-information-boundary.md)(실무·운영 정보 경계)
- 명세: [`docs/0921_practitioner-screens/spec.md`](../../0921_practitioner-screens/spec.md) §7

## 배경

대시보드의 절반은 회차를 골라야 채워지는 패널이었다. 회차는 운영의 단위이고 실무자의 아침은
누적이므로, M6는 회차 선택기와 회차 의존 패널 넷을 빼고 누적 패널 다섯을 남겼다.

남은 문제는 계약이다. `WorkloadProjection`(`app/lifecycle/extensions.py`)은 **건수와 불가
사유만** 준다. 패널은 건수와 함께 위에서 다섯 줄을 보여 줘야 하는데, 지난 대시보드 작업은
목록 API 한 페이지를 받아 브라우저에서 다시 세다가 두 번 되돌려졌다(`findings.md`의
"사전규격 목록 API에 마감 구간 필터도 임박 집계도 없다"의 위임 초안). 그래서 패널을 그리기
전에 "이 건수를 어느 목록이 같은 모집단으로 내는가"를 먼저 닫는다.

## 결정

1. **패널마다 건수 키 하나와 목록 호출 하나를 짝짓는다.** 짝은 spec §7.1의 표가 정본이다.
   건수는 그 목록 호출의 `total`과 같은 술어·같은 구현에서 나오고, 화면은 페이지를 받아 다시
   세지 않는다(ADR-0053 결정 2·4의 방식을 패널 다섯으로 확장).

2. **새 endpoint를 만들지 않는다.** 다섯 패널의 목록은 이미 있는 목록 API 넷
   (`/api/opportunities`, `/api/pre-specs`, `/api/order-plans`, `/api/bid-delta/decision-queue`)이
   낸다. 더한 것은 query 인자 셋과 정렬 값 하나뿐이다.

   | 추가 | 대상 | 뜻 |
   |---|---|---|
   | `deadline_within_days=N` | `GET /api/opportunities` | 권위 있는 연결의 공고 마감이 `[요청 시각, KST 오늘+N일의 끝]`에 있는 **추적 대상**(`계속 추적`·`보류`) 사업 |
   | `sort=deadline` | `GET /api/opportunities` | 아직 남은 권위 연결 마감 중 가장 이른 것 오름차순, 그런 마감이 없으면 맨 뒤 |
   | `deadline_within_days=N` | `GET /api/pre-specs` | 의견등록 마감이 같은 창에 있는 사전규격 |
   | `first_observed_from=<KST 날짜>` | `GET /api/order-plans` | 그 KST 일자 00:00 이후에 **처음 관측된** 발주계획 |

   `human_relevance=missing`은 이미 구현돼 있었다(`order_plan_screening.py`의 `_filter_values`와
   `missing` NULL 투영). findings의 그 항목은 낡았고, 이 결정은 계약 문서에 그 사실을 적고
   진입점 회귀를 붙이는 것으로 닫는다.

3. **`deadline_within_days`는 추적 상태를 함께 좁힌다.** `hold_review=overdue`가 "보류 상태 +
   기한 지남"을 한 인자로 묶은 선례(ADR-0053 개정 2026-09-17)를 따른다. 패널이 묻는 것은
   "마감 임박 **추적 건**"이고, 종료한 사업의 남은 마감은 할 일이 아니다. `tracking_status`를
   다중 값으로 넓히거나 새 축을 만들지 않는다.

4. **서버는 대표 마감을 고르지 않는다.** spec §5의 결정을 유지한다. 창은 **링크 단위**로
   판정하고 돌려주는 것은 **사업**이며, 응답에 "이 사업의 마감"이라는 단일 필드를 만들지
   않는다. 화면은 이미 있는 `links[]`의 `deadline_at`·`source_type`으로 어느 마감이 임박했는지
   스스로 고른다(그래서 한 패널에 입찰 마감과 의견등록 마감이 종류를 적고 섞인다).
   `sort=deadline`은 정렬 키이지 투영 필드가 아니다.

5. **`사람 확인 필요`의 두 출처를 합치지 않는다.** 개요 검토 실패·사람 확인
   (`overview_human_review`, deep_review 소유, 세는 단위는 **사전규격 공고**)과 공고별 열린
   확인 항목(`blocking_items_open`, lifecycle 소유, 세는 단위는 **사업기회**)은 각각 자기 키를
   갖고 각각 자기 목록 호출을 갖는다. 합계 키 `human_check_required`는 두 하위 건수의 합이며,
   **하나라도 `null`이면 합계도 `null`**(`unavailable_reason="sub_count_unavailable"`)이다.
   화면은 패널 바닥에 두 하위 건수를 따로 적는다.

6. **기준 시각은 요청 시각이고 창은 KST 일자로 끊는다.** `deadline_within_days=7`의 상한은
   "요청 시각의 KST 일자 + 7일"의 끝(= +8일 00:00 KST, 열린 경계)이다. D-day가 날짜 단위
   표시이므로 창도 날짜 단위로 끊는다. 하한은 요청 시각이므로 이미 지난 마감은 임박이 아니다.
   `first_observed_from`도 KST 일자 00:00을 하한으로 쓴다(사전규격 목록의
   `observed_from`·`observed_to`와 같은 규칙).

7. **건수와 목록은 서로 다른 요청이다.** 화면이 `GET /api/workload`와 목록을 따로 받으므로 몇
   초 차이는 생길 수 있다. 화면은 건수를 목록 길이로 덮지 않고, 목록이 비었다고 건수를 0으로
   고치지 않는다. 패널 바닥에 범위와 기준을 적는다.

8. **DB 열·migration·새 저장 상태를 만들지 않는다.** 네 키 전부가 기존 행에서 계산되는 집계다.
   `order_plan_new_priority`의 "새로"는 `first_observed_at`(관측 행의 최소 시각)에서 나오며 새
   플래그를 저장하지 않는다.

9. **역방향 import를 만들지 않는다.** lifecycle은 `tracking_deadline_imminent`와
   `blocking_items_open`을 자기 테이블에서 직접 세고(ADR-0053 결정 4의 원칙),
   `overview_human_review`는 deep_review, `order_plan_new_priority`는 screening이
   `WorkloadProjection`으로 등록해 넘긴다. lifecycle이 `prespec_overview_run`이나
   `order_plan_screening_result`를 세지 않는다. `blocking_items_open`이 쓰는 "열린 확인 항목이
   있는 공고" 집합은 지금처럼 screening의 `JudgmentProjection`에서 받는다 — 제공자가 없으면 그
   사유가 그대로 0건 일치로 이어진다(`notice_ids_for_filters`의 `None`/빈 sequence 규칙).

## 대안과 결과

- **패널마다 전용 endpoint를 만드는 안**: 건수·목록 모집단이 한 구현에 갇혀 가장 안전하지만
  경로가 다섯 개 늘고 기존 목록 API와 규칙이 두 벌이 된다. 인자 셋으로 같은 보장을 얻을 수
  있어 채택하지 않았다(결정 2).
- **마감 임박을 사업 단위 대표 마감 필드로 투영하는 안**: 화면이 단순해지지만 서버가 "이
  사업의 마감"을 고르게 되고, 의견등록 마감과 입찰 마감을 한 값으로 접는다. spec §5 결정과
  어긋나므로 링크 단위 판정 + 사업 반환으로 남겼다(결정 4).
- **`tracking_status`를 쉼표 다중 값으로 넓히는 안**: `deadline_within_days`를 순수 창 인자로
  둘 수 있었지만, 기존 `OpportunityTrackingStatus` 단일 값 계약을 넓히는 변경이 패널 하나를 위해
  전 목록 소비자에게 퍼진다. `hold_review` 선례를 따랐다(결정 3).
- **`overview_view`에 `failed`+`needs_human_review` 합집합 값을 새로 만드는 안**: 패널이 목록을
  한 번만 받으면 되지만 필터 어휘에 상태 아닌 값이 생긴다. 두 상태가 서로 배타적이라 기존 값
  둘(`failed`·`attention`)로 두 번 받고 `total`을 더하면 같은 모집단이 되므로 계약을 넓히지
  않았다.
- **`human_check_required`를 두 하위 건수의 합 대신 화면 합산으로 두는 안**: 제공자 부재를
  화면이 다시 판단해야 해서 `null`을 0으로 접기 쉽다. 서버가 합계와 null 전파를 함께
  책임진다(결정 5).

## 검증

- `GET /api/workload`의 열 항목이 항상 모두 있고 순서가 고정임, 제공자 부재·실제 0·합계의
  null 전파가 구분됨, 모집단이 커져도 조회 수가 상수임(`tests/app/test_workload_api.py`).
- 각 키가 짝지은 목록 호출의 `total`과 같음(같은 파일, PostgreSQL).
- 창 경계: 정확히 N일 뒤 마감은 포함, N+1일 00:00 KST는 제외, 이미 지난 마감은 제외
  (`tests/app/test_api_opportunities.py`, `tests/app/test_api_pre_specs_workspaces.py`).
- `first_observed_from`의 KST 일자 경계와 `human_relevance=missing`의 진입점 회귀
  (`tests/app/test_order_plan_screening_api.py`).
- 제공자별 집계와 확장점 규칙(`tests/screening/test_workload_projection.py`,
  `tests/lifecycle/test_workload_extensions.py`, `tests/app/test_module_boundaries.py`).
