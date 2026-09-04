# 입찰 delta·최종 결정 계약 명세

- 작업: UI/UX 수정 계획 R-07
- 기준 HEAD: `52469dc`
- 상태: 채택 — [ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md), 구현 전
- 범위: OpenAPI wire shape, DB 제약, 감사 event, 오류, 테스트 matrix
- 비범위: production code, migration, frontend 구현, 모델 호출, 운영 활성화

이 문서는 채택된 구현 명세다. 현재 backend에는 아래 endpoint와 table이 없다. 작업 트리의
untracked bid-delta frontend는 존재하지 않는 endpoint를 호출하는 시안이며 이 계약의
producer나 구현 완료 근거가 아니다. ADR-0034 채택으로 R-08 진입 gate는 열렸지만 R-09는
실제 R-08 API와 typed error가 구현·검증된 뒤에만 시작한다.

## 1. 현재 코드 조사 결과

이 절은 계약을 설계하기 전의 **조사 시점 기록**이다. 이후 R-08이 bid-delta router를 구현했고 ([ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md)), [ADR-0045](tracking/decisions/0045-backend-module-layout.md)의 모듈 이주로 파일 경로도 바뀌었다(현재 위치는 `app/deep_review/routers/bid_delta.py`, `app/lifecycle/routers/opportunities.py`). 아래 문장은 그 시점의 사실이므로 고치지 않는다.

- `web/backend/app/main.py`는 runs, notices, pre-specs, opportunities, document bundles,
  deep reviews, reports 등의 router만 등록한다. bid-delta router는 없다.
- `web/backend/app/routers/opportunities.py`의 현재 경로는 목록, 단건, candidate link 판정,
  tracking status 변경이다. `/bid-delta` 하위 경로는 없다.
- `Notice`는 누적 외부 identity이고 `source_type`, `bid_no`, `bid_ord`를 가진다.
  `NoticeObservation`은 회차별 snapshot과 source hash를 보존한다.
- authoritative opportunity link는 `(official, 확정)` 또는
  `(candidate, 사람 확인 완료, accepted)`다. pending/rejected/search-unconfirmed link는
  비교 입력 소유권을 만들지 않는다.
- `DocumentBundleItem`은 ready confirm 시점의 document version, version number, content
  SHA-256, role, current flag, structure ID와 structure payload SHA-256을 보존한다.
- 기존 `FinalOpinion`은 사전규격 심층 검토의 특정 report revision·validation에 묶인
  `추진 | 조건부 추진 | 보류 | 검토 종료` 기록이다. 최종 입찰 Go/No-Go table이 아니며
  재사용하지 않는다.
- 공통 `IdempotencyRecord`와 `AuditEvent`는 actor·request ID·안전한 metadata를 같은
  transaction에 묶는 기존 패턴을 제공한다.

## 2. 명명과 상태

### 2.1 wire schema

| 이름 | `schema_version` |
|---|---|
| workspace 조회 | `bidops.bid-delta-workspace.v1` |
| 비교 생성 요청 | `bidops.bid-delta-comparison-create.v1` |
| 비교 조회 | `bidops.bid-delta-comparison.v1` |
| attempt 생성 요청 | `bidops.bid-delta-attempt-create.v1` |
| 최종 결정 생성 요청 | `bidops.bid-final-decision-create.v1` |

모든 response field는 명시적으로 필수다. `?`로 표시한 field만 필수 nullable이며, `optional`로
표시하지 않은 field는 생략할 수 없다. UUID, date, timezone-aware datetime은 JSON string이다.
SHA-256은 64자 lowercase hex다. 열거하지 않은 request field는 거부한다.

### 2.2 서로 다른 상태 축

- calculation status: `pending | running | completed | failed`
- comparison result status: `changed | unchanged | unknown | failed | null`
- item result status: `changed | unchanged | unknown | failed`
- materiality: `material | non_material | unknown`
- decision currentness: `current | stale | unknown`

`pending`, `running`, `failed`, `unknown`, `unchanged`는 서로 바꿀 수 없다. `materiality`는
차이가 있는지와 별개이며 승인된 category policy version으로만 계산한다.

| calculation | result | 완료 시각 | 추가 불변식 |
|---|---|---|---|
| `pending` | `null` | `null` | attempt가 없거나 queued attempt만 있음 |
| `running` | `null` | `null` | active attempt 하나 |
| `completed` | `changed\|unchanged\|unknown` | non-null | 승인 범주가 정확히 한 번씩 item에 존재 |
| `failed` | `failed` | non-null | `last_error_code` non-null |

완료 비교의 보수적 집계 규칙은 다음과 같다.

1. item 하나라도 `unknown|failed`이면 전체 result는 `unknown`이다.
2. 그 밖에 item 하나라도 `changed`이면 전체 result는 `changed`다.
3. 그 밖에는 모든 item이 `unchanged`이므로 전체 result는 `unchanged`다.
4. 계산 전체가 실패했을 때만 전체 result가 `failed`다.

이 집계는 차이 존재 여부만 말한다. item의 허용 조합은 `unchanged→non_material`,
`unknown|failed→unknown`, `changed→material|non_material|unknown`이다. 전체 result가
`unchanged`면 전체 materiality는 `non_material`, result가 `unknown|failed`면 `unknown`이다.
result가 `changed`이면 material item이 하나라도 있을 때 `material`, 그렇지 않고 unknown
item이 있으면 `unknown`, 나머지는 `non_material`이다.

### 2.3 범주와 materiality 계약

ADR-0034 B1으로 채택한 `BidDeltaCategory` wire enum은 다음 7개다.

- `budget_and_economics`
- `contract_period_and_schedule`
- `eligibility`
- `joint_supply_and_subcontracting`
- `scope_and_requirements`
- `evaluation`
- `submission`

각 category는 승인된 `category_policy_version`에 정확히 한 번 존재해야 한다. item의
`result_status`는 값의 차이 여부, `materiality`는 그 차이가 재검토·최종 결정에 중요한지의
정책 판정이다. v1은 수치 임계값을 추정하지 않는다. 금액·가격 방식·지급·보증·위약,
계약기간·일정·마일스톤·기한, 자격, 공동수급·하도급, 필수 과업·요구사항·산출물·검수·SLA,
평가·배점·실격, 제출 서류·형식·채널·서명 조건의 실질 변경을 `material`로 판정한다.
양쪽 verified evidence로 의미가 같음이 확인된 통화·날짜 표기, 절 번호, 서식·오탈자 차이만
`non_material`이다. 동일 의미를 확정할 수 없거나 근거가 부족하면 `unknown`, 추출·검증
실패는 `failed`이며 둘 다 `non_material`로 축약하지 않는다. 향후 수치 임계값은 사람 정답을
근거로 새 category policy version에서만 추가한다.

## 3. OpenAPI 수준 REST 계약

### 3.1 공통 오류 envelope

domain 오류는 다음 shape를 사용한다.

```json
{
  "error": {
    "code": "bid_delta_input_version_conflict",
    "message": "비교 문서 버전이 변경되었습니다",
    "details": null
  },
  "request_id": "e4ad619e-7f06-4a6f-b0f7-27d72438c4ef"
}
```

내부 path, object key, SQL, prompt, model body, 사용자 파일명, actor 이름은 오류 details에
넣지 않는다. 기존 Lean 규칙대로 path·body가 FastAPI 구조 검증 자체를 통과하지 못한 422는
`{"detail":[...]}`일 수 있다. parsing 뒤 domain validation 422는 아래의 안정 code를 쓴다.

### 3.2 exact input ref

조회 응답의 `BidDeltaInputRef`는 다음 field를 모두 가진다.

```json
{
  "opportunity_link_id": 81,
  "notice_id": 991,
  "notice_source_type": "pre_spec",
  "notice_external_id": "R26BD00267196",
  "bid_ordinal": null,
  "published_at": "2026-08-29T09:00:00+09:00",
  "bundle_id": "11111111-1111-4111-8111-111111111111",
  "bundle_revision": 2,
  "bundle_version": 4,
  "document_version_id": "22222222-2222-4222-8222-222222222222",
  "document_version_version": 3,
  "document_role": "제안요청서",
  "structure_id": "33333333-3333-4333-8333-333333333333",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "structure_payload_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "effective_date": null
}
```

입찰공고 input은 `notice_source_type="bid_notice"`이고 `bid_ordinal`은 원문 값 또는 `null`이다.
서버가 ordinal을 추정하지 않는다. 후보 projection은 `selectable`, `blocked_reason?`을 추가할 수
있다. 비교 생성 요청의 `BidDeltaInputFence`는 display field를 되받지 않고 link·notice·bundle,
bundle revision/version, document version ID/version, structure ID와 두 SHA-256만 필수로 받는다.
서버가 이 fence로 다시 읽은 full ref가 후보와 일치하는지 잠금 안에서 검사한다.

### 3.3 workspace 조회

```text
GET /api/opportunities/{opportunity_id}/bid-delta
```

성공은 200 `BidDeltaWorkspaceView`다.

```json
{
  "schema_version": "bidops.bid-delta-workspace.v1",
  "opportunity_id": 17,
  "baseline_candidates": [],
  "comparison_candidates": [],
  "comparisons": [],
  "latest_final_decision": null,
  "decision_currentness": "unknown",
  "currentness_reasons": ["no_final_decision"],
  "generated_at": "2026-08-31T18:00:00+09:00"
}
```

후보는 active opportunity의 authoritative notice link와 ready bundle item만 반환한다.
baseline은 `pre_spec`, comparison은 `bid_notice`다. 여러 후보를 정렬해도 서버는 선택 값을
응답에 만들지 않는다. `comparisons`는 `id`, `sequence`, 양쪽 ref, calculation/result/
materiality, `version`, `result_sha256?`, 시각을 가진 summary다. `latest_final_decision`은
sequence가 가장 큰 row일 뿐 current임을 뜻하지 않으며 반드시 currentness와 함께 소비한다.

주요 실패:

- 404 `opportunity_not_found`
- 409 `opportunity_merged`
- 503 `bid_delta_projection_unavailable`

### 3.4 비교 생성

```text
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons
X-BidOps-Actor-Name: <claimed actor>
X-BidOps-Actor-Name-Format: utf-8-percent-v1  # 비ASCII일 때만
```

request는 `BidDeltaComparisonCreateRequest`다.

```json
{
  "schema_version": "bidops.bid-delta-comparison-create.v1",
  "request_id": "e4ad619e-7f06-4a6f-b0f7-27d72438c4ef",
  "category_policy_version": "bid-delta-policy.v1",
  "baseline": {
    "opportunity_link_id": 81,
    "notice_id": 991,
    "bundle_id": "11111111-1111-4111-8111-111111111111",
    "bundle_revision": 2,
    "bundle_version": 4,
    "document_version_id": "22222222-2222-4222-8222-222222222222",
    "document_version_version": 3,
    "structure_id": "33333333-3333-4333-8333-333333333333",
    "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "structure_payload_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "comparison": {
    "opportunity_link_id": 82,
    "notice_id": 1102,
    "bundle_id": "44444444-4444-4444-8444-444444444444",
    "bundle_revision": 1,
    "bundle_version": 2,
    "document_version_id": "55555555-5555-4555-8555-555555555555",
    "document_version_version": 1,
    "structure_id": "66666666-6666-4666-8666-666666666666",
    "source_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "structure_payload_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  }
}
```

서버는 opportunity, 두 link, notice, bundle item, structure를 같은 transaction에서 잠그고
exact field를 재검증한다. 성공은 202 `BidDeltaComparisonView`이며 초기
`calculation_status=pending`, `result_status=null`, `version=1`이다. 동일 actor·request ID와
동일 body replay는 같은 response를 반환한다.

주요 실패:

- 400 `actor_name_required | actor_name_invalid`
- 404 `opportunity_not_found | bid_delta_input_not_found`
- 409 `opportunity_merged | bid_delta_input_not_authoritative | bid_delta_input_not_ready |
  bid_delta_input_scope_conflict | bid_delta_input_version_conflict | idempotency_conflict`
- 422 `bid_delta_same_input | bid_delta_baseline_type_invalid |
  bid_delta_comparison_type_invalid | bid_delta_category_policy_invalid`
- 503 `bid_delta_policy_unavailable | bid_delta_service_unavailable`

### 3.5 비교 조회

```text
GET /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}
```

성공은 200 `BidDeltaComparisonView`다.

```json
{
  "schema_version": "bidops.bid-delta-comparison.v1",
  "id": "77777777-7777-4777-8777-777777777777",
  "opportunity_id": 17,
  "sequence": 3,
  "version": 2,
  "category_policy_version": "bid-delta-policy.v1",
  "calculation_status": "running",
  "result_status": null,
  "materiality": "unknown",
  "baseline": {},
  "comparison": {},
  "items": [],
  "attempts": [],
  "result_sha256": null,
  "last_error_code": null,
  "created_at": "2026-08-31T17:00:00+09:00",
  "started_at": "2026-08-31T17:00:02+09:00",
  "completed_at": null,
  "final_decisions": [],
  "latest_final_decision": null,
  "decision_currentness": "unknown",
  "currentness_reasons": ["no_final_decision"]
}
```

`baseline`과 `comparison`은 완전한 `BidDeltaInputRef`다. attempt는 `id`, `sequence`,
calculation status, `last_error_code?`, started/completed time만 반환한다. 원문 모델 응답이나
내부 job 정보는 반환하지 않는다.

item shape는 다음과 같다.

```json
{
  "id": "88888888-8888-4888-8888-888888888888",
  "ordinal": 1,
  "category": "eligibility",
  "result_status": "changed",
  "materiality": "material",
  "before_value": "중소기업 직접생산확인증명 필요",
  "after_value": "직접생산확인증명과 추가 면허 필요",
  "summary": "입찰 참가자격 요건이 추가되었습니다.",
  "baseline_evidence": [
    {
      "id": "99999999-9999-4999-8999-999999999999",
      "side": "baseline",
      "document_version_id": "22222222-2222-4222-8222-222222222222",
      "structure_id": "33333333-3333-4333-8333-333333333333",
      "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "locator_type": "table_cell",
      "locator": {"page": 12, "block_key": "table-4-r7-c2"},
      "quote": "직접생산확인증명서",
      "verification_status": "verified"
    }
  ],
  "comparison_evidence": [
    {
      "id": "aaaaaaaa-2222-4222-8222-aaaaaaaaaaaa",
      "side": "comparison",
      "document_version_id": "55555555-5555-4555-8555-555555555555",
      "structure_id": "66666666-6666-4666-8666-666666666666",
      "source_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "locator_type": "table_cell",
      "locator": {"page": 15, "block_key": "table-6-r3-c2"},
      "quote": "직접생산확인증명서 및 추가 면허",
      "verification_status": "verified"
    }
  ],
  "error_code": null
}
```

evidence shape는 다음과 같다.

```json
{
  "id": "99999999-9999-4999-8999-999999999999",
  "side": "baseline",
  "document_version_id": "22222222-2222-4222-8222-222222222222",
  "structure_id": "33333333-3333-4333-8333-333333333333",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "locator_type": "table_cell",
  "locator": {"page": 12, "block_key": "table-4-r7-c2"},
  "quote": "직접생산확인증명서",
  "verification_status": "verified"
}
```

`locator_type`은 기존 안전 projection과 같은 `page | paragraph | table_cell | bbox`다.
`verification_status`는 `verified | missing | mismatch`다. `changed|unchanged` item은 양쪽
verified evidence가 각각 하나 이상 있어야 한다. `unknown|failed` item은 nonblank
`error_code`가 필요하며 근거가 일부 있더라도 성공 판정으로 승격하지 않는다.

주요 실패:

- 404 `opportunity_not_found | bid_delta_comparison_not_found`
- 409 `bid_delta_comparison_scope_conflict`
- 503 `bid_delta_projection_unavailable`

### 3.6 실패 비교 재시도

```text
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/attempts
```

actor header와 다음 body를 요구한다.

```json
{
  "schema_version": "bidops.bid-delta-attempt-create.v1",
  "request_id": "b9aa8c5a-49c7-4519-8e47-2087c892881a",
  "expected_comparison_version": 4
}
```

성공은 202 updated `BidDeltaComparisonView`다. 기존 attempt와 결과 row를 수정하지 않고
새 attempt sequence를 만든다. 입력 snapshot과 category policy version은 재시도 중 바꿀 수
없다. 다른 입력은 새 comparison이다.

주요 실패:

- 400 `actor_name_required | actor_name_invalid`
- 404 `opportunity_not_found | bid_delta_comparison_not_found`
- 409 `bid_delta_comparison_not_retryable | bid_delta_version_conflict |
  active_attempt_exists | idempotency_conflict`
- 422 FastAPI 구조 검증 `detail[]`; parsing 뒤 별도 domain 422 없음
- 503 `bid_delta_service_unavailable`

### 3.7 최종 결정 생성

```text
POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/final-decisions
```

actor header와 `BidFinalDecisionCreateRequest`를 요구한다. `decision`은 ADR-0034 A1로 채택한
`go | no_go`만 허용하며, 미결정 상태는 decision row가 없는 것으로 표현한다.

```json
{
  "schema_version": "bidops.bid-final-decision-create.v1",
  "request_id": "bd47bc02-c51c-4260-a285-68c39b991fa2",
  "expected_comparison_version": 4,
  "expected_result_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "baseline_document_version_id": "22222222-2222-4222-8222-222222222222",
  "comparison_document_version_id": "55555555-5555-4555-8555-555555555555",
  "supersedes_final_decision_id": null,
  "decision": "go",
  "reason": "입찰공고의 추가 자격을 확인했고 대응 계획을 승인함"
}
```

서버는 comparison row와 opportunity의 결정 tip을 잠그고 다음을 모두 확인한다.

- calculation status가 `completed`이고 result가 `failed`가 아님
- comparison version, result digest, 양쪽 document version ID가 일치
- adopted currentness policy상 저장 가능한 현재성
- `supersedes_final_decision_id`가 직전 sequence와 일치하거나 첫 결정이면 null
- actor·request ID idempotency payload가 일치

성공은 201 `BidFinalDecisionView`다.

```json
{
  "id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
  "opportunity_id": 17,
  "sequence": 1,
  "comparison_id": "77777777-7777-4777-8777-777777777777",
  "comparison_version": 4,
  "result_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "baseline_document_version_id": "22222222-2222-4222-8222-222222222222",
  "comparison_document_version_id": "55555555-5555-4555-8555-555555555555",
  "supersedes_final_decision_id": null,
  "decision": "go",
  "reason": "입찰공고의 추가 자격을 확인했고 대응 계획을 승인함",
  "claimed_name": "홍길동",
  "request_id": "bd47bc02-c51c-4260-a285-68c39b991fa2",
  "created_at": "2026-08-31T18:10:00+09:00",
  "currentness": "current",
  "currentness_reasons": []
}
```

주요 실패:

- 400 `actor_name_required | actor_name_invalid | final_decision_reason_required`
- 404 `opportunity_not_found | bid_delta_comparison_not_found |
  final_decision_not_found`
- 409 `bid_delta_comparison_not_completed | bid_delta_version_conflict |
  bid_delta_result_digest_conflict | bid_delta_comparison_stale |
  final_decision_supersession_conflict | idempotency_conflict`
- 422 `final_decision_value_invalid | final_decision_input_fence_invalid`
- 503 `bid_delta_currentness_unavailable`

503은 결정을 쓰지 않는다. 확인 실패를 current로 가정하거나 기존 결정을 수정하지 않는다.

## 4. 다중 공고·정정 선택 규칙

### 4.1 후보 포함

baseline 후보는 다음 조건을 모두 만족한다.

1. active opportunity의 authoritative notice link다.
2. `notice.source_type=pre_spec`다.
3. ready bundle 안의 safe·ready structure document다.
4. role이 채택된 baseline role allowlist에 속한다.

comparison 후보도 같은 조건이지만 `notice.source_type=bid_notice`이고 채택된 bid role
allowlist를 사용한다. pending/rejected/search-unconfirmed link와 draft/failed/blocked bundle은
후보로 선택하지 않는다. UI가 blocked reason을 보여 주기 위해 별도 진단 projection으로
표시할 수는 있다.

### 4.2 정렬과 선택

후보 정렬은 `published_at`, 외부 `bid_ord`, bundle revision, document version을 원문 값과
함께 보여 주는 display 정렬이다. `bid_ord` 누락·비표준 값은 추정하지 않고 null/원문으로
남긴다. 정렬 첫 행이나 마지막 행을 자동 선택하지 않는다.

같은 correction notice의 문서가 여러 개면 exact document version을 선택한다. 여러 문서를
한 comparison input으로 묶어야 한다는 업무 결정이 생기면 현재 단일 input v1을 확장한 새
schema version을 제안한다. v1에서 묵시적으로 여러 문서를 합치지 않는다.

### 4.3 새 입력

새 authoritative bid/정정 또는 새 ready document version은 새 comparison 후보다. 기존
comparison이나 final decision을 수정하지 않는다. 채택한 strict C1에 따라 기존 결정은
derived `stale`, 정책 판단에 필요한 순서를 확정할 수 없으면 `unknown`이다.

## 5. DB 목표 설계 계약

이 절은 migration 자체가 아니라 R-08 backend 구현에 적용할 제약 명세다. ADR-0034 채택으로
R-08 진입 gate는 열렸지만, 실제 revision 번호는 구현 세션에서 배정하며 PostgreSQL 검증 전에는
구현 완료로 보지 않는다.

### 5.1 `bid_delta_comparison`

주요 column:

- `id UUID PK`, `opportunity_id FK`, `sequence`, `version`
- `category_policy_version`
- baseline/comparison의 link, notice, bundle, document version, structure ID, version number,
  source SHA-256, structure payload SHA-256
- `calculation_status`, nullable `result_status`, `materiality`
- nullable `current_attempt_id`, `result_sha256`, `last_error_code`
- `created_by_name`, created/started/completed timestamps

필수 제약:

- `UNIQUE(opportunity_id, sequence)`
- exact input+policy에 대한 unique key 또는 동일 payload idempotent 재사용
- 두 document version ID가 다름
- calculation/result/timestamp 조합 CHECK
- 모든 SHA-256 lowercase 64자 CHECK
- baseline/comparison link가 같은 opportunity에 속하도록 composite FK
- bundle notice와 link notice가 같고 bundle item의 document/structure가 exact한 composite FK
- 입력·정책 fence UPDATE를 항상 거부하고 completed 뒤 projection/result digest UPDATE를
  거부하는 trigger. failed comparison은 새 attempt를 만들 때만 pending projection으로 전이

### 5.2 `bid_delta_attempt`

- `id UUID PK`, `comparison_id`, `sequence`, calculation status
- `work_job_id`, `lease_fence`, `requested_by_name`, timestamps, `last_error_code`
- 승인된 provider·model name/digest, prompt version, generation config/digest 또는 이들을 고정한
  immutable runtime binding ID
- `UNIQUE(comparison_id, sequence)`
- pending/running partial unique active attempt
- terminal timestamp와 failure code CHECK
- 완료·실패 attempt UPDATE/DELETE 거부 trigger

### 5.3 `bid_delta_item`과 `bid_delta_evidence`

item은 comparison, attempt, category, ordinal, result status, materiality, before/after value,
summary, error code를 가진다. `UNIQUE(attempt_id, category)`와
`UNIQUE(attempt_id, ordinal)`을 둔다. adopted policy의 모든 category가 정확히 한 번 있는지는
attempt completion service와 deferred validation trigger가 검사한다. result/materiality 허용
조합도 CHECK로 강제해 unchanged를 material로, unknown/failed를 non-material로 축약하지 않는다.

evidence는 item, side, ordinal, exact document/structure/hash, locator, quote, verification
status를 가진다. `UNIQUE(item_id, side, ordinal)`을 둔다. completion trigger는
`changed|unchanged` item의 양쪽에 verified evidence가 있고 그 입력 fence가 comparison side와
일치하는지 검사한다. mismatch나 누락을 자동 보정하지 않는다.

item·evidence UPDATE/DELETE를 trigger로 거부한다. 실패 attempt의 부분 item도 보존하고,
재시도는 새 attempt와 새 item/evidence row를 만든다. comparison은 completed attempt 하나를
가리키며 그 결과를 result digest로 고정한다. completed comparison은 다시 계산하지 않고,
다른 계산은 새 comparison row다.

### 5.4 `bid_final_decision`

주요 column:

- `id UUID PK`, `opportunity_id`, `sequence`
- `comparison_id`, `comparison_version`, `result_sha256`
- baseline/comparison document version ID
- nullable `supersedes_final_decision_id`
- 결정 enum, nonblank reason, claimed name, UUID request ID, created time

필수 제약:

- `UNIQUE(opportunity_id, sequence)`
- `UNIQUE(opportunity_id, id)` for scoped self FK
- `UNIQUE(opportunity_id, supersedes_final_decision_id)`로 한 parent의 분기 방지
- `UNIQUE(claimed_name, opportunity_id, request_id)`와 공통 idempotency payload hash
- comparison ID/version/result digest composite FK 또는 같은 transaction의 exact lock 검사
- comparison opportunity와 decision opportunity가 같은 composite FK
- nonblank actor·reason CHECK와 채택 enum CHECK
- 모든 UPDATE·DELETE를 거부하는 append-only trigger

직전 tip 확인과 sequence 배정은 opportunity row lock 안에서 수행한다. DB current flag는 두지
않는다. 현재성은 comparison fence, 새 authoritative 입력, 채택 정책으로 계산한 projection이다.

### 5.5 권한

- `app`: comparison 요청, attempt retry 요청, final decision·idempotency·audit INSERT와 필요한
  제한 column status update만 허용한다.
- `worker`: lease/fence가 맞는 attempt·item·evidence INSERT와 comparison terminal 전이만
  허용한다. final decision에는 쓰기 권한이 없다.
- 새 table은 runtime DML allowlist에 자동 포함하지 않는다. migration 뒤 명시적으로 검토한다.
- startup은 migration, seed, policy 활성화, delta 계산을 실행하지 않는다.
- 회사 내부망의 allowlist된 Ollama·사설 vLLM만 사용한다. 비교 생성 전에 exact 문서 pair,
  category policy version, binding과 payload 범위를 표시하고 actor·request ID가 있는 생성
  요청을 해당 snapshot의 건별 내부 모델 처리 승인으로 감사한다.
- 내부 binding 또는 건별 처리 승인이 없거나 payload가 승인 범위를 벗어나면 503으로 실패
  닫힘 처리한다. 외부 endpoint·hosted OpenAI로 자동 fallback하지 않는다.

## 6. 감사 event

| action | actor kind | 같은 transaction의 대상 | 안전한 metadata |
|---|---|---|---|
| `bid_delta.comparison_requested` | human | comparison·idempotency | comparison/opportunity ID, 양쪽 document/structure ID, policy version |
| `bid_delta.attempt_started` | system | attempt running fence | comparison/attempt ID, sequence, lease fence |
| `bid_delta.comparison_completed` | system | terminal result·items·evidence | comparison ID, result/materiality, category status counts, result hash, runtime binding ID/digest |
| `bid_delta.comparison_failed` | system | failed terminal state | comparison/attempt ID, safe error code |
| `bid_delta.retry_requested` | human | 새 attempt·idempotency | comparison/attempt ID, sequence |
| `bid_final_decision.recorded` | human | decision·idempotency | decision/opportunity/comparison ID, sequence, decision enum, superseded ID |
| `bid_final_decision.recheck_required` | system | 재검토 projection 근거 | decision ID, 새 link/document ID, reason code |

감사 metadata에는 reason 전문, quote, 원문, actor 이름, object key, path, prompt, 모델 응답을
넣지 않는다. actor 이름은 `AuditEvent.claimed_name`에만 두며 인증된 신원으로 표현하지 않는다.

## 7. 안정 오류 code 표

| HTTP | code | 조건 |
|---:|---|---|
| 404 | `opportunity_not_found` | opportunity가 없음 |
| 404 | `bid_delta_input_not_found` | link/bundle/document/structure 중 하나가 없음 |
| 404 | `bid_delta_comparison_not_found` | comparison이 없음 |
| 404 | `final_decision_not_found` | supersedes 대상이 없음 |
| 409 | `opportunity_merged` | secondary opportunity에서 mutation 시도 |
| 409 | `bid_delta_input_not_authoritative` | authoritative active owner가 아님 |
| 409 | `bid_delta_input_not_ready` | clean ready bundle/structure가 아님 |
| 409 | `bid_delta_input_scope_conflict` | 두 input이 같은 active opportunity에 속하지 않음 |
| 409 | `bid_delta_input_version_conflict` | submitted version/hash fence가 현재 exact row와 다름 |
| 409 | `bid_delta_comparison_scope_conflict` | comparison이 path opportunity에 속하지 않음 |
| 409 | `bid_delta_comparison_not_retryable` | failed가 아닌 comparison 재시도 |
| 409 | `bid_delta_comparison_not_completed` | 사람 결정 전에 calculation 미완료/실패 |
| 409 | `bid_delta_version_conflict` | expected comparison version 불일치 |
| 409 | `bid_delta_result_digest_conflict` | expected result digest 불일치 |
| 409 | `bid_delta_comparison_stale` | 채택 currentness policy상 새 입력 재검토 필요 |
| 409 | `final_decision_supersession_conflict` | 직전 결정 tip fence 불일치 |
| 409 | `active_attempt_exists` | active attempt 중복 |
| 409 | `idempotency_conflict` | 같은 actor·request ID의 다른 payload |
| 422 | `bid_delta_same_input` | 양쪽 document version이 같음 |
| 422 | `bid_delta_baseline_type_invalid` | baseline이 pre_spec/허용 role이 아님 |
| 422 | `bid_delta_comparison_type_invalid` | comparison이 bid_notice/허용 role이 아님 |
| 422 | `bid_delta_category_policy_invalid` | 미지원/비활성 policy version |
| 422 | `final_decision_value_invalid` | 채택 enum 밖의 값 |
| 422 | `final_decision_input_fence_invalid` | request의 양쪽 document ID가 comparison과 다름 |
| 503 | `bid_delta_policy_unavailable` | approved category/material policy를 읽을 수 없음 |
| 503 | `bid_delta_service_unavailable` | worker/model/필수 내부 서비스가 준비되지 않음 |
| 503 | `bid_delta_projection_unavailable` | 안전한 조회 projection을 만들 수 없음 |
| 503 | `bid_delta_currentness_unavailable` | currentness를 fail-closed 검증할 수 없음 |

400 actor code와 reason code는 기존 `actor_name_required`, `actor_name_invalid`,
`final_decision_reason_required`를 재사용한다. 알 수 없는 내부 예외는 500
`processing_failed`로 정규화하고 세부 예외를 노출하지 않는다.

## 8. 테스트 matrix

| 영역 | 시나리오 | 기대 |
|---|---|---|
| 현재 API 조사 | main/OpenAPI route 목록 | 현재 기준 bid-delta endpoint 0개 |
| 후보 | authoritative pre_spec + ready exact bundle item | baseline 후보 1개 |
| 후보 | pending/rejected/search-unconfirmed link | 선택 후보에서 제외, absence로 오인하지 않음 |
| 후보 | blocked/failed/needs_review document | selectable 아님, 안전한 reason |
| 다중 공고 | bid notice 2개와 correction 2개 | 4개 모두 보존, 자동 선택 없음 |
| 다중 공고 | `bid_ord=null`·비표준 값 | 추정 정렬/차수 생성 없음 |
| 생성 정상 | exact same-opportunity fence | 202 pending, result null, audit/idempotency 같은 transaction |
| 생성 race | client 조회 뒤 document/bundle version 변경 | 409 `bid_delta_input_version_conflict`, row 없음 |
| 생성 scope | 다른 opportunity document 혼합 | 409 `bid_delta_input_scope_conflict` |
| 생성 type | bid notice를 baseline으로 제출 | 422 `bid_delta_baseline_type_invalid` |
| 상태 | pending→running | result null, completed_at null |
| 상태 | 모든 category terminal | completed, result 집계 규칙 일치 |
| 상태 | calculation 전체 실패 | failed/failed, safe error code, partial을 success로 발행하지 않음 |
| 불확실성 | 한 item unknown, 나머지 unchanged | 전체 unknown, unchanged 아님 |
| 불확실성 | 한 item failed, 한 item changed | 전체 unknown, changed만으로 축약하지 않음 |
| 근거 | changed item 양쪽 verified locator | 완료 허용 |
| 근거 | 한쪽 locator 없음/hash mismatch | changed/unchanged 완료 거부, unknown/failed |
| 범주 | adopted policy category 수·순서 | category 정확히 한 번씩, 자유 문자열 거부 |
| 재시도 | failed comparison에 새 request ID | 이전 attempt 보존, 새 sequence 202 |
| 재시도 | running/completed comparison | 409 not retryable/active |
| 결정 정상 | completed current comparison exact fence | 201 append-only row+idempotency+audit |
| 결정 actor | ASCII·canonical 한글 actor | claimed actor 보존, 인증 표시는 없음 |
| 결정 actor | malformed/control/system actor | 400 actor code, row 없음 |
| 결정 이유 | blank/whitespace | 400 `final_decision_reason_required` |
| 결정 replay | 같은 actor/request/body | 동일 ID·created_at 응답, row 1개 |
| 결정 conflict | 같은 actor/request, 다른 body | 409 idempotency conflict |
| 결정 race | 두 사용자가 같은 tip을 supersede | 하나 성공, 하나 409 supersession conflict |
| append-only | decision UPDATE/DELETE 직접 시도 | DB trigger 거부 |
| version fence | stale version/digest/document ID | 각 409/422 안정 code, row 없음 |
| currentness | 새 authoritative bid/ready document 등장 | 기존 row 불변, strict면 stale·recheck event |
| currentness | 새 입력 순서 판단 불가 | unknown, current 아님 |
| 사람 경계 | delta completed/changed | final decision 자동 생성 0건 |
| 사람 경계 | 이전 decision + unchanged 새 comparison | 자동 승계 0건 |
| 보안 | 모든 성공·오류·audit | object key/path/signed URL/prompt/model body/원문 없음 |
| 권한 | worker가 final decision INSERT | DB 권한 거부 |
| 모델 경계 | 내부 binding·건별 처리 승인 없음 또는 payload 범위 위반 | 503, 모델 호출 0건, 외부 전송·hosted fallback 0건 |
| 재현성 | attempt 완료 뒤 runtime binding 변경 | 기존 attempt 불변, 완료 commit 거부 또는 새 comparison |
| 404 | opportunity/input/comparison 누락 | endpoint별 안정 code |
| 409 | merged/stale/version/idempotency | 안전한 envelope와 request ID |
| 422 | semantic enum/type/fence 오류 | 안정 code; 구조 오류는 FastAPI detail |
| 503 | policy/model/currentness 불가 | fail closed, decision·완료 row 없음 |
| PostgreSQL | 빈 DB upgrade/head·제약·trigger·downgrade | disposable PostgreSQL 17에서 실행, SQLite 통과로 대체 금지 |
| concurrency | worker fence 교체 뒤 이전 worker 완료 | commit 거부, terminal 결과 하나 |
| 회귀 | opportunity tracking/final opinion | tracking choice·사전규격 FinalOpinion과 값/이력 분리 |

## 9. 채택 결정표

| 항목 | 채택 | 소거한 대안 | 결과 | 승인 주체 |
|---|---|---|---|---|
| final decision enum | A1 `go \| no_go` | conditional/hold 포함 | 미결은 row 없음, 기존 보류 용어와 분리 | 사업개발 업무 책임자 |
| material category | B1 7개 업무 범주 | 5개 요약 또는 자유 범주 | 누락을 줄이고 정책·테스트 enum을 고정 | 사업개발 업무 책임자 |
| material threshold | 보수적 v1 category policy | 근거 없는 비율·일수 임계값 | 실질 변경은 material, 검증된 표기 차이만 non-material | 사업개발 업무 책임자 |
| currentness | strict C1 | material-only/manual | 새 authoritative 입력 즉시 stale, 불확실하면 unknown | 사업개발 업무 책임자 |
| 모델 | 회사 내부망 allowlist binding | 외부·hosted fallback | 비교 생성 요청이 exact snapshot의 건별 처리 승인 | 보안/운영 책임자 |
| audit/보안 | safe ID·code allowlist | reason/quote 포함 | 민감 회사 판단·원문을 감사 metadata에서 제외 | 보안/운영 책임자 |

wire 예시의 enum·category·materiality/currentness 값은 채택 계약이다. exact input fence,
상태 분리, 양쪽 근거, append-only 사람 결정, stable error와 fail-closed 원칙을 R-08이 그대로
구현해야 한다.

## 10. R-07 실행 기록 입력 자료

수정 계획 10.13절은 이 세션에서 수정하지 않는다. coordinator가 검증 결과를 확인한 뒤 사용할
행 자료는 다음과 같다.

| 일자 | 작업 | 기준 HEAD | 결과 | 검증 | 남은 위험·다음 작업 |
|---|---|---|---|---|---|
| 2026-08-31 | R-07 | 52469dc | 설계 제안 작성·업무 결정 대기 | 추적 파일 4개의 `git diff --check` 통과; 신규 문서 2개의 `git diff --no-index --check` 공백 진단 0건; 변경 문서 6개의 상대 link·heading 검사 0건 | enum·material 범주/임계값·currentness를 사업개발 업무 책임자가 결정하고 보안/운영 책임자가 감사 경계를 검토해야 함. ADR-0034 채택 전 R-08·R-09 진입 불가 |
| 2026-08-31 | R-07 결정 | d323781 | A1·B1 보수적 v1·C1 strict·내부망 모델·safe audit allowlist 채택 | ADR·계약·업무 규칙·추적 문서 정합성 및 `git diff --check` 확인 | R-08 진입 가능; R-09는 실제 R-08 API·typed error 검증 뒤 진입 |
