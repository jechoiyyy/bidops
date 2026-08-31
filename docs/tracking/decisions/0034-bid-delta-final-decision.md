# 입찰 delta와 최종 사람 결정을 불변 비교와 append-only 기록으로 분리한다

- 상태: 제안 — 업무 책임자 결정 대기
- 일자: 2026-08-31
- 구현 상태: 설계만 존재한다. REST endpoint, DB table, migration, production UI는 없다.

## 맥락

[ADR-0022](0022-plan-prespec-centered-lifecycle.md)는 `계속 추적` 사업기회에 입찰공고나
정정이 연결되면 사전규격 대비 material delta를 확인하고 사람이 최종 `Go/No-Go`를
결정하도록 했다. [ADR-0030](0030-opportunity-tracking-state.md)은 사람의 추적 선택과
시스템 재검토 신호를 분리했고, [ADR-0031](0031-prespec-overview-review-stage.md)은
사전규격 개요 검토·심층 검토·최종 입찰 결정을 서로 대신하지 못하게 했다.

현재 backend에는 bid-delta router, schema, service, table이 없다. 작업 트리의 untracked
frontend 시안은 존재하지 않는 `GET /api/opportunities/{id}/bid-delta`를 호출하고,
계산 상태를 `completed` 하나로, 결과 상태를 `changed | same | unknown`으로 가정한다.
이 시안은 현재 API 계약이나 구현 완료의 근거가 아니다.

같은 사업기회에는 여러 사전규격, 입찰공고, 차수, 정정 문서가 연결될 수 있다. `latest`를
암묵적으로 고르거나 mutable `is_current`만 저장하면 나중에 어떤 문서를 비교했는지
재현할 수 없다. 또한 계산 실패를 변경 없음으로 보이게 하거나 시스템 delta를 사람의
최종 결정으로 복사하면 BidOps의 사람 통제 경계를 깨뜨린다.

## 제안

이 절의 불변성·분리 원칙은 기존 채택 ADR에서 직접 이어진다. 다만 아래
[결정이 필요한 항목](#결정이-필요한-항목)이 확정되지 않았으므로 전체 제안은 채택 상태가
아니며 구현 진입 근거로 사용할 수 없다.

### 1. 비교 입력을 ready bundle의 정확한 snapshot에 고정한다

하나의 비교는 기준 사전규격과 비교 입찰공고의 다음 값을 각각 저장한다.

- authoritative `opportunity_link.id`와 `notice.id`
- `document_bundle.id`, bundle revision·version
- `document_version.id`, document version의 optimistic `version`
- confirm 시점의 `document_structure.id`
- 원문 `source_sha256`와 structure payload SHA-256

두 입력은 같은 active opportunity에 속한 authoritative link여야 한다. 기준 notice는
`source_type=pre_spec`, 비교 notice는 `source_type=bid_notice`여야 하며, 두 bundle은
`ready`여야 한다. 저장 뒤 입력 ID·hash·정책 버전은 바꾸지 않는다. live attachment,
현재 문서 포인터, 최신 link를 계산 중 다시 읽지 않는다.

### 2. 여러 공고·정정 중 비교 대상은 요청에서 명시한다

조회 projection은 비교 가능한 모든 사전규격·입찰공고·정정 snapshot을 반환한다.
정렬은 선택 편의를 위한 것일 뿐 자동 선택 규칙이 아니다. 비교 생성 요청은 양쪽 snapshot
fence를 모두 보내야 하며, 서버가 누락된 대상을 `latest`로 채우지 않는다.

입찰공고 차수나 정정 문서마다 별도 비교를 만든다. 새 공고·정정이 나타나도 기존 비교,
항목, 근거, 사람 결정을 수정하지 않는다. 하나만 존재할 때 화면이 미리 선택할 수는 있지만
저장 요청에는 여전히 exact fence가 필요하다.

### 3. 계산 상태와 결과 상태를 다른 필드로 둔다

계산 상태는 `pending | running | completed | failed`다. 결과 상태는 nullable
`changed | unchanged | unknown | failed`다.

| 계산 상태 | 결과 상태 | 의미 |
|---|---|---|
| `pending`, `running` | `null` | 아직 결과를 발행하지 않음 |
| `completed` | `changed`, `unchanged`, `unknown` | 승인 범주의 모든 항목이 terminal 결과를 가짐 |
| `failed` | `failed` | 비교 전체를 안전하게 완료하지 못함 |

항목 결과도 `changed | unchanged | unknown | failed`를 사용한다. 항목 `unknown`은 문서에
값이 없거나 비교 의미를 확정할 수 없는 정상적인 불확실성이고, 항목 `failed`는 추출·검증
같은 기술 실패다. 항목에 `unknown` 또는 `failed`가 하나라도 있으면 전체 결과를
`unchanged`로 만들 수 없다.

### 4. 변경 판정은 양쪽 검증 근거를 요구한다

각 항목은 기준·비교 side를 분리한 evidence 목록을 가진다. evidence는 exact document
version, structure ID, source hash, locator type·locator, 안전한 quote, 검증 상태를 가진다.
object key, 내부 path, signed URL, prompt, 모델 원응답은 반환하지 않는다.

`changed`와 `unchanged`는 양쪽에 해당 입력 snapshot과 일치하는 verified locator가 하나
이상 있을 때만 허용한다. 한쪽 근거가 없거나 hash·locator 검증에 실패하면 결과는
`unknown` 또는 `failed`다. 근거가 없다는 사실을 빈 문자열이나 `0`으로 보정하지 않는다.

### 5. 최종 결정은 comparison fence에 묶인 사람의 append-only 기록이다

최종 결정 생성은 actor header, nonblank reason, UUID request ID, comparison ID와 expected
version, comparison result digest, 양쪽 document version ID를 요구한다. 서버는 같은
transaction에서 comparison을 잠그고 exact fence와 현재성 조건을 재검증한 뒤 다음을
함께 insert한다.

- 최종 결정 row와 opportunity별 sequence
- 직전 결정이 있으면 `supersedes_final_decision_id`
- idempotency record
- `bid_final_decision.recorded` 감사 event

기존 결정은 update·delete하지 않는다. 동일 actor·request ID·동일 payload replay는 같은
응답을 반환하고 payload가 다르면 409다. 시스템 결과, 심층 검토 의견, tracking status,
recheck signal은 최종 결정을 만들거나 바꾸지 못한다.

### 6. 현재성은 결정 row를 바꾸지 않는 projection이다

결정 이력에는 당시 comparison fence를 그대로 둔다. 새 authoritative 입찰공고·정정 또는
새 ready document version이 나타나면 이전 결정을 수정하지 않고 `current | stale | unknown`
projection과 reason code로 현재성을 표시한다. 새 입력을 확인할 수 없거나 currentness
계산에 실패하면 `current`로 보정하지 않고 `unknown`으로 둔다.

새 문서는 기존 [ADR-0030](0030-opportunity-tracking-state.md)의 사람 tracking choice를
덮어쓰지 않고 재검토 신호만 올릴 수 있다. 새 comparison과 새 최종 결정은 사람이 별도로
만든다.

## 제안 REST·DB 경계

OpenAPI 수준 wire shape, 상태 불변식, 안정 오류 code, 제안 table·constraint, 감사 event와
테스트 matrix는 [입찰 delta 계약 명세](../../review/bid-delta-contract-spec.md)에 둔다.
핵심 endpoint 제안은 다음과 같다.

- `GET /api/opportunities/{opportunity_id}/bid-delta`
- `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons`
- `GET /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}`
- `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/attempts`
- `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/final-decisions`

위 경로는 모두 **제안**이며 현재 존재하는 endpoint 목록에 포함되지 않는다.

## 결정이 필요한 항목

### A. 최종 결정 enum

| 대안 | 영향 |
|---|---|
| A1. `go | no_go` | 최종성은 가장 명확하다. 미결은 결정 row 없음으로 표현하고 조건부 결정은 만들지 않는다. |
| A2. `go | conditional_go | no_go` | 조건부 참여를 보존하지만 조건·확인 기한·해소 기록의 추가 계약이 필요하다. |
| A3. `go | hold | no_go` | 보류를 명시할 수 있지만 tracking `보류`·심층 의견 `보류`와 혼동될 위험이 크다. |

제안은 A1이다. 업무 책임자가 실제 승인 절차에 조건부 결정을 사용한다면 A2를 선택하고,
조건·확인 기한·해소 이력을 같은 ADR에서 추가로 확정해야 한다.

### B. material 범주와 임계 규칙

| 대안 | 영향 |
|---|---|
| B1. 7개 업무 범주 | `budget_and_economics`, `contract_period_and_schedule`, `eligibility`, `joint_supply_and_subcontracting`, `scope_and_requirements`, `evaluation`, `submission`; 누락 위험이 낮지만 항목 수가 많다. |
| B2. 5개 화면 범주 | 금액·기간·자격·평가·제출 조건; 현재 시안과 가깝지만 공동수급·과업 범위·계약 조건이 묻힌다. |
| B3. 문서별 자유 범주 | 새 공고에 유연하지만 비교·집계·테스트가 결정적이지 않다. |

제안은 B1이다. `changed`와 material 여부는 분리하고, category policy version이 어떤 변화가
`material`인지 또는 `non_material`인지 정한다. 금액 비율·날짜 일수 같은 임계값은 현재
근거가 없으므로 추정하지 않는다.

### C. 최종 결정 currentness

| 대안 | 영향 |
|---|---|
| C1. strict | 새 authoritative bid/정정 또는 새 ready 비교 문서가 생기면 즉시 `stale`; 누락 위험은 낮고 재검토 건수는 늘어난다. |
| C2. material-only | 새 comparison이 material change를 확인한 뒤에만 `stale`; 재검토는 줄지만 계산 전 공백 동안 오래된 결정을 current로 보일 수 있다. |
| C3. manual | 사람이 무효화할 때까지 current; 단순하지만 새 공고를 놓칠 위험이 가장 크다. |

제안은 C1이다. 새 입력의 authoritative 여부나 version 순서를 확정할 수 없으면 `unknown`이며
`current`로 남기지 않는다.

## 대안

**현재 frontend shape를 그대로 backend 계약으로 채택 — 소거한다.** 계산 상태가 하나이고,
`same`이 `unchanged`·미계산·실패를 분리하지 않으며, document version ID와 양쪽 근거 fence,
사람 결정 mutation이 없다.

**opportunity에 최종 결정 현재값을 한 컬럼으로 저장 — 소거한다.** 새 결정이 과거 결정을
덮고 어떤 비교를 보고 판단했는지 재현할 수 없다.

**가장 최신 공고와 문서를 서버가 자동 선택 — 소거한다.** 여러 공고·정정의 순서와 효력을
업무 판단 없이 추정하고 경쟁 중인 version을 조용히 바꿀 수 있다.

**delta가 `unchanged`이면 이전 최종 결정을 자동 승계 — 소거한다.** 시스템 결과가 사람의
최종 결정을 대신하게 된다. 이전 결정을 참고로 표시할 수는 있지만 새 결정 row는 사람이
명시적으로 만들어야 한다.

## 결과

- 비교와 사람 결정의 재현 가능한 lineage, 실패 상태, 양쪽 근거를 설계 수준에서 고정한다.
- 다중 공고·정정을 임의로 하나로 축약하지 않는다.
- enum, material policy, currentness 정책이 정해지기 전에는 구현 가능한 최종 계약이 아니다.
- 이 ADR과 명세의 작성은 R-08 backend 또는 R-09 frontend 구현·승인을 뜻하지 않는다.

## 결정 요청

승인 주체는 **사업개발 업무 책임자**이며, 보안·감사 경계는 **보안/운영 책임자**가 함께
검토한다. 업무 책임자는 A1~A3, B1~B3, C1~C3을 각각 선택하고 material 임계값·조건부 결정
필드가 필요한지 명시해야 한다. 그 선택을 이 ADR에 반영해 상태를 `채택`으로 바꾸기 전에는
R-08과 R-09에 진입하지 않는다.
