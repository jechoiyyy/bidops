# 최종 Go/No-Go 결정 근거를 모델 문서 비교와 분리한다

- 상태: 채택
- 일자: 2026-09-17
- 관련 결정: [ADR-0034](0034-bid-delta-final-decision.md) §5 부분 개정, [ADR-0053](0053-decision-workload-read-contracts.md) §6 현재성 단일 규칙 확장
- 근거 요청: 사업 추적 연결·조치 고도화 계획(`docs/0917_opportunity-tracking/`) intent 결정 8, spec §9

## 맥락

[ADR-0034](0034-bid-delta-final-decision.md) §5는 최종 결정을 **완료된 비교(comparison) fence에
묶인** 사람의 append-only 기록으로 정했다. 그런데 비교를 실제로 계산하는 worker와 모델 binding은
구현되지 않았고, 이번 계획에서도 보류한다. 그 결과 운영에서 최종 Go/No-Go를 저장할 수 없다.

- 비교는 `pending`에 머물러 `bid_delta_comparison_not_completed`로만 끝난다.
- `bid_final_decision.comparison_id` 등 비교 5열이 NOT NULL이다.
- `scripts/runtime-privileges.sql`에서 app role은 `bid_final_decision`을 읽기만 한다.

담당자는 모델 비교가 없어도 입찰공고의 공고 조건(금액·마감·개찰·자격·지역 제한·정정 사유)과
차수 간 변경을 보고 Go/No-Go를 판단한다. 이 값은 수집기가 정규화해 `notice`에 이미 저장한
결정적 값이다.

## 결정

**1. 결정 근거는 두 종류이고 한 행은 한 근거만 갖는다.** `bid_final_decision.basis_kind`는
`comparison`(기존 비교 fence) 또는 `notice_conditions`(입찰공고 조건)이다. 비교 근거면 비교 5열이
모두 있고 `basis_notice_id`·`basis_observation_sha256`이 비며, 공고 조건 근거면 그 반대다. DB
CHECK가 섞인 조합과 빠진 열을 거부한다. 기존 행은 `comparison`이다(migration `0028`).

**2. 공고 조건 요약은 결정적 읽기다.** `GET /api/opportunities/{id}/bid-conditions`는 사업기회의
authoritative 입찰공고를 `bid_no`·`bid_ord` 순으로 나열하고 수집 값만 읽는다. 모델을 부르지 않는다.
어느 한쪽이 `null`인 비교는 `unknown`이며 `unchanged`로 추정하지 않는다. 사전규격 대비는 의미가
같은 예산·사업명만 비교하고, 사전규격 의견등록 마감과 입찰 마감은 `not_comparable`로 둔다.

**3. 공고 조건 결정은 사람이 본 공고와 관측에 fence를 건다.**
`POST /api/opportunities/{id}/final-decisions`는 `expected_notice_id`와
`expected_observation_sha256`을 받는다. 서버는 최신 공고를 대신 고르지 않고 확인만 한다.

| 조건 | 결과 |
|---|---|
| authoritative 입찰공고 없음 | 409 `final_decision_bid_notice_missing` |
| 최신 공고 순서(`published_at`, 같으면 `bid_ord`)를 확정할 수 없음 또는 관측 hash 없음 | 503 `bid_delta_currentness_unavailable` |
| 기대 공고가 최신 authoritative 입찰공고가 아님 | 409 `final_decision_notice_not_latest` |
| 그 공고의 최신 관측 `source_sha256`이 기대 값과 다름 | 409 `final_decision_observation_changed` |

actor·사유·결정 값 검증, 사업기회 행 잠금, idempotency 재생, 직전 결정 tip 잠금과 supersession,
sequence 배정, 감사 event는 비교 근거 경로와 **같은 함수**가 수행한다. 결정 enum은 ADR-0034 A1
(`go | no_go`) 그대로다.

**4. 현재성은 근거별로 한 모듈이 계산한다.** `services/bid_delta_currentness.py`의
`decision_currentness`가 workspace·결정 큐·업무 집계의 공통 규칙이다. 비교 근거는 기존 규칙을 그대로
쓴다. 공고 조건 근거는 다음과 같다.

- 기준 공고보다 새 authoritative 입찰공고가 있거나 기준 공고의 최신 관측 hash가 기록 값과 다르면
  `stale`(`newer_bid_notice`, `notice_observation_changed`)
- 순서나 hash를 확인할 수 없으면 `unknown`(`ordering_unknown`, `observation_unknown`)
- 확실한 `stale` 사유가 있으면 `unknown`보다 우선하고, 둘 다 없을 때만 `current`

ADR-0034 C1 strict를 유지한다. 결정 row는 바뀌지 않고 새 결정은 사람이 다시 기록한다.

**5. 권한은 결정 추가에 필요한 만큼만 연다.** app role에 `bid_final_decision` INSERT와 tip 잠금용
열 권한 `UPDATE (id)`를 준다. append-only trigger가 모든 UPDATE·DELETE를 계속 거부한다. 비교·attempt·
item·evidence의 권한은 바꾸지 않는다.

**6. ADR-0034 개정 범위.** §5 "최종 결정은 comparison fence에 묶인다"는 `comparison` 근거에만
적용한다. 비교 생성·조회·재시도와 비교 근거 결정 계약, material 정책(B1), 결정 enum(A1), 현재성(C1),
내부망 모델 경계(D)는 바뀌지 않는다. 비교 계산 worker와 모델 binding은 계속 보류한다.

## 대안

- **비교 worker를 먼저 구현한다 — 소거.** 이번 계획이 보류한 모델 호출·평가를 앞당기고, 그동안
  결정 기록이 계속 막힌다.
- **계산하지 않은 placeholder comparison을 만들어 기존 경로에 태운다 — 소거.** 계산되지 않은 비교가
  `completed`처럼 보이며 ADR-0034 §3의 상태 분리를 깬다.
- **서버가 최신 공고를 골라 fence 없이 저장한다 — 소거.** ADR-0034 §2의 자동 선택 금지와 충돌하고,
  사람이 본 차수와 저장된 근거가 달라질 수 있다.
- **공고 조건 결정 테이블을 따로 둔다 — 소거.** sequence·supersession chain·결정 큐·현재성이 두
  벌이 된다.
- **모델이 공고 조건을 요약한다 — 소거.** 이번 범위는 모델 호출·외부 전송을 새로 만들지 않는다.

## 결과

- 비교 worker 없이 사람이 최종 Go/No-Go를 기록할 수 있다. 결정 큐·`bid_final_decision_pending`·
  workspace가 공고 조건 결정을 기결정으로 세고 현재성을 함께 보여 준다. workspace는 비교 없는 최신
  결정에서 503을 내지 않는다.
- migration `0028_final_decision_basis`가 비교 5열을 nullable로 바꾸고 basis 열·CHECK·FK를 더한다.
  downgrade는 `notice_conditions` 행이 하나라도 있으면 거부한다.
- 새 차수·정정이 적재되거나 기준 공고의 관측 내용이 바뀌면 결정은 `stale`로 표시되고 결정 큐에 다시
  올라온다.
- 최종 결정 응답(`bidops.bid-final-decision.v1`)에 `basis_kind`·`basis_notice_id`·
  `basis_observation_sha256`이 더해지고 비교 필드는 nullable이 된다. 화면 소비자는 후속 단계에서 갱신한다.
- 비교 근거 경로는 app role에서 여전히 실행되지 않는다(비교 행 INSERT·잠금 권한 없음). 비교 worker를
  구현할 때 그 권한을 함께 검토한다.
- 상세 wire shape·제약·오류 표는 [입찰 delta 계약 명세](../../bid-delta-contract-spec.md)와
  [심층 검토 ERD](../../deep-review-erd.md) §8.6이 정본이다.
