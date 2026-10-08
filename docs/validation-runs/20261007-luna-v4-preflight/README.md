# Luna v4 선검증 — STEP-001 이전 실패 원인 분류 (2026-10-06)

- 기능: `DEMO-00-luna-preflight` STEP-001. 읽기 전용 분석이며 모델 호출·운영 변경 없음.
- 근거: [v1 기록](../20260922-luna-deep-review/live-validation.md), [v2 기록](../20260923-luna-related-claims/README.md),
  [v3 기록](../20260923-luna-validation-off/README.md), 정책 파일 v2/v3, `services/deep_reviews.py`, `services/narrative_inputs.py`.
- 한계: 운영 스택이 이 작업 장비에 없어(컨테이너·볼륨 없음) 저장된 원응답을 엄격 검증으로 재검사하지 못했다. 아래 분류는 기록과 코드에 근거한다.

## 실패별 분류

| 실행 | 결과 | 직접 원인 | 분류 | 현재 상태 |
|---|---|---|---|---|
| v1 (09-23 09:06, 6분 26초) | 1번째 slice `narrative:claim_relation_out_of_slice` | 주장 1개(20개 중)가 선택 필드 `related_claim_ids`에 근거 ID를 넣음 | 출력 계약의 ID 역할 모호(선택 필드) | v2가 범위 밖 related_claim만 제외·경고(`omit_invalid_with_warning_v1`). 해소 |
| v2 (10:14, 6분 15초) | 1번째 slice `narrative:considered_claim_out_of_slice` | 입력 verified_claims 0개인데 `considered_claim_ids`에 응답 자체의 로컬 주장 ID 30개 반환 | 프롬프트 의미 모호 | v3가 `coverage_rule`에 설명 문장 추가. 단 v3는 검사 off라 효과 **미확인** |
| v3 검증 off (11:16, 53분 41초) | 10번째 slice `validation:dangling_evidence` | 주장 1개의 `evidence_ids`에 응답에 없는 ID 1개 | 모델 출력 무결성 오류(우연적) | 검증기는 정상. 미해결 |

## 새로 확인한 구조 원인 — 시간 예산

1489는 원문 단위가 19개다. 1단계는 단위마다 1회(19회), 2단계도 단위마다 최소 1회(19회, verified claim이 예산을 넘으면 더),
3단계 종합이 1회 이상이라 **한 보고서에 최소 39회** Luna/xhigh를 순차 호출한다(`narrative_inputs.build_slices`).
기록된 호출당 시간은 약 5분 15초~6분 26초(v3 평균 5분 22초)이므로 최소 약 3시간 30분이다.
검토 전체 마감은 코드에 7200초로 고정돼 있고(`deep_reviews.py:1584`, 정책의 `review_timeout_seconds`는 읽지 않음) 세 단계 전체에 한 번 적용된다.
따라서 **검증 오류가 하나도 없어도 1489는 마감 안에 끝날 수 없다.** 이전 세 실행은 이 지점 전에 실패해 드러나지 않았다.
같은 구조면 DEMO 보고서 9건은 공고 크기에 따라 건당 수 시간이며, 단일 슬롯에서 순차 실행된다.

## v4 설계에 주는 제약

1. considered_claim: 프롬프트 설명만으로는 효과가 확인되지 않았다. verified_claims가 없는 slice에서는 필드를 요구하지 않거나 `[]`로 고정하는
   결정적 출력 계약(단계별 schema)이 더 확실하다. 이것은 검증 완화가 아니다.
2. dangling_evidence: 필수 근거 FK 검사이므로 끌 수 없다. 프롬프트 자기 점검 지시는 확률만 낮춘다.
   한 실행에 39회 이상 호출하므로 slice당 오류율이 낮아도 보고서 전체 성공 확률은 크게 떨어진다(관측 1/10 slice는 표본이 너무 작아 추정치로 쓰지 않는다).
3. 시간: 마감 상향, 호출 수 축소(slice당 단위 수 확대·`max_requirements=1` 하드코딩 해제), 추론 강도 하향, 작은 공고 선택 중 하나 이상이 필요하다.

## 사용자 결정이 필요한 항목

| 항목 | 선택지 |
|---|---|
| 시간 예산 | 마감 상향(정책 값을 코드가 읽게) / slice 확대로 호출 축소 / effort xhigh→high / 원문 단위가 적은 공고로 선검증·표본 선정 |
| dangling evidence | 프롬프트 자기 점검만 / 같은 slice 1회 교정 재요청(새 자동 재호출 규칙) / 위험 수용 |
| 운영 단계 실행 위치 | 운영 호스트에서 사용자가 실행 / 운영 호스트에 접근 가능한 세션에서 실행 |

## 판정

STEP-001 분류 완료. v4 정책만으로는 1489 완성을 기대할 수 없다.

2026-10-07 사용자 결정(ADR-0070 개정 표): 검토 마감을 정책 값으로 읽고 v4는 5시간, 원문 단위가 적은 공고 우선(표본 기준),
같은 slice 1회 교정 재요청, 운영 단계는 운영 호스트에서 사용자가 실행. STEP-002는 이 결정으로 진행한다.
