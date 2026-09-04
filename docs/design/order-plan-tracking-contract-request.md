# 발주계획 추적 결정 계약 요청안

| 항목 | 내용 |
|---|---|
| 상태 | **제안 — 백엔드 파트 검토 대기.** 채택도 구현도 아니다 |
| 작성일 | 2026-09-04 |
| 기준 HEAD | `27588af` (화면 시안 기준 구현 단계 B) |
| 요청자 | 화면 작업([`PLAN.md`](PLAN.md) 단계 C) |
| 선행 결정 | [ADR-0045](ADR.md#adr-0045-사업-추적-중심-정보구조와-추적-결정의-위치) 결정 4·5·6, [`business-rules.md`](../business-rules.md) 추적 상태 |
| 범위 | REST wire shape, 기존 DB 재사용 범위, 오류, 테스트 matrix |
| 비범위 | backend production code, migration, 모델 호출, 운영 활성화, 프런트 구현 |

ADR-0045 결정 4가 **결정 1(추적 결정)을 발주계획 화면에 두기로** 채택했다. 그런데 그 결정을
저장할 REST 경로가 backend에 없다. 이 문서는 화면 쪽이 필요로 하는 계약을 백엔드 파트에
요청하는 안이며, **이 문서가 계약을 확정하지 않는다.** 아래 §7이 확정 전까지 화면이 무엇을
하는지 규정한다.

## 1. 현재 코드 조사 결과 (기준 HEAD `27588af`)

조사한 사실만 적는다.

- `web/backend/app/routers/order_plans.py`의 경로는 다섯이다.
  `GET /order-plans`, `GET /order-plans/{pk}`, `GET /order-plans/{pk}/screening-history`,
  `GET /order-plans/{pk}/screening-feedback`, `POST /order-plans/{pk}/screening-feedback`.
  **추적 결정 경로는 없다.**
- 추적 상태를 바꾸는 유일한 경로는 `PATCH /opportunities/{opportunity_id}/tracking-status`다.
  발주계획 식별자로는 부를 수 없다.
- `Opportunity.tracking_status`는 `미선택 | 계속 추적 | 보류 | 종료` 네 값이고,
  `ck_opportunity_tracking_metadata`가 `미선택`이 아닌 상태에 `tracking_selected_by`·
  `tracking_selected_at`을 강제한다. **필요한 상태 4값은 이미 DB에 있다.**
- `services/opportunity_tracking.set_tracking_status()`는 사람 선택 하나를 기록하고
  `AuditEvent`(action `opportunity.tracking_status.changed`)를 **append-only로 함께 남긴다.**
  ADR-0045 결정 4의 "선택 즉시 append-only 이력"은 이 경로가 이미 만족한다.
- `ingest/loader.py`는 발주계획을 적재할 때 **이미** 그 발주계획을 소유하는 `Opportunity`와
  `stage='order_plan'`·`link_type='official'`·`status='확정'`·
  `evidence_external_no=order_plan_unty_no` 링크를 만든다(`_ensure_opportunity`,
  `_ensure_official_link`). `uq_opportunity_link_authoritative_order_plan` 부분 unique index가
  발주계획 하나에 authoritative 링크가 최대 하나임을 보장한다.
- `OrderPlanListItem`·`OrderPlanDetailResponse`는 `_Strict`(extra 금지)이며
  **`opportunity_id`도 추적 상태도 담지 않는다.**

**따라서 새 table은 필요하지 않을 가능성이 높다.** 소유 사업기회, 상태 4값, append-only 이력이
모두 이미 있다. 없는 것은 (a) 발주계획 응답이 그 상태를 **읽어 오지 않는 것**과 (b) 발주계획
식별자로 그 상태를 **쓸 경로가 없는 것** 둘이다.

## 2. 요청하는 것

### 2.1 요청 A — 읽기 (필수)

발주계획 목록·상세 응답에 소유 사업기회의 추적 상태를 싣는다. 이것이 없으면 화면이 목록 행에
`추적 결정 없음`/`추적 중`을 표시할 수 없고, 결정 전에 이미 결정된 건인지도 알 수 없다.

`OrderPlanListItem`과 `OrderPlanDetailResponse`에 nullable object 하나를 더한다.

```
tracking: {
  opportunity_id: int,
  tracking_status: "미선택" | "계속 추적" | "보류" | "종료",
  tracking_reason: string | null,
  tracking_selected_by: string | null,
  tracking_selected_at: datetime | null,
  inherited_from_order_plan: bool          // 사전규격 승계 표시용. 발주계획에서는 항상 false
} | null
```

- `null`은 **소유 사업기회를 확인하지 못했다**는 뜻이며 `미선택`과 다르다. 화면은 이 둘을 서로
  바꾸어 표시하지 않는다.
- `미선택`일 때 `tracking_reason`·`tracking_selected_by`·`tracking_selected_at`은 DB 제약상
  모두 `null`이다.
- `schema_version`은 `order-plan-list-response.v2` / `order-plan-detail-response.v2`로 올린다.
  `_Strict`가 extra를 거부하므로 field 추가는 **호환 변경이 아니다.** v1 소비자를 남길지는
  백엔드 파트가 정한다.

상세에는 추적 결정 이력도 필요하다(ADR-0045 결정 4, `OrderPlanDetail` 아트보드의 `이력` rail).

```
GET /api/order-plans/{order_plan_pk}/tracking-decisions
→ { schema_version: "order-plan-tracking-history.v1",
    producer: "order-plan-review-api", consumer: "order-plan-review-client",
    order_plan_pk: int, opportunity_id: int | null,
    items: [{ decided_at, tracking_status, previous_tracking_status,
              reason, claimed_name, audit_event_id }] }   // 최신 순
```

`AuditEvent`의 `opportunity.tracking_status.changed` 투영이면 충분하다. 새 저장소가 아니다.

### 2.2 요청 B — 쓰기 (필수)

```
POST /api/order-plans/{order_plan_pk}/tracking-decisions
헤더: X-BidOps-Actor-Name (기존 actor header 규칙 그대로)
본문: order-plan-tracking-decision-create.v1
{ schema_version, producer: "order-plan-review-client",
  consumer: "order-plan-review-api", request_id,
  tracking_status: "계속 추적" | "보류" | "종료",
  reason: string,                       // 필수, 공백만이면 거부
  expected_tracking_status: string | null }   // 낙관적 잠금. null이면 검사하지 않는다
→ 201 order-plan-tracking-decision-response.v1
{ provenance, order_plan_pk, opportunity_id, tracking_status,
  tracking_reason, tracking_selected_by, tracking_selected_at, audit_event_id }
```

서버가 하는 일은 셋이다. (1) 발주계획의 authoritative 소유 사업기회를 찾는다.
(2) 기존 `opportunity_tracking.set_tracking_status()`에 그대로 넘긴다. (3) 그 결과를 돌려준다.
**새 업무 규칙을 만들지 않는다.**

`미선택`은 이 경로로 쓸 수 없다. 화면의 `이번 건 넘기기`는 아무것도 저장하지 않고 다음 건으로만
이동하기 때문이다(§4).

### 2.3 대안 — 요청 B 없이 가는 길

요청 A만 구현하고 화면이 기존 `PATCH /opportunities/{id}/tracking-status`를 부르는 방법도 된다.
그 경우의 대가를 적어 둔다.

| | 요청 B 구현 | 요청 A만 + 기존 PATCH |
|---|---|---|
| 화면이 아는 것 | 발주계획 식별자 하나 | 발주계획 → 사업기회 매핑을 화면이 들고 다녀야 한다 |
| 소유 사업기회 미확인 | 서버가 typed error로 거부 | 화면이 `opportunity_id`가 null인 경우를 각자 처리 |
| 감사 | 요청이 발주계획 화면에서 왔다는 사실이 경로에 남는다 | 남지 않는다 |
| 구현량 | router 하나 + 조회 helper | 없음 |

화면은 **어느 쪽이든 받는다.** 백엔드 파트가 요청 B를 받지 않기로 하면 §7의 client adapter
한 곳만 바꾸면 된다.

## 3. 상태 축이 서로를 대신하지 않는다

이 요청이 **바꾸지 않는** 것을 명시한다. `CLAUDE.md` 강제 게이트와 ADR-0045 결정 5다.

| 축 | 이 요청과의 관계 |
|---|---|
| 모델 판단(`qwen_relevance`) | 바꾸지 않는다. 추적 결정은 relevance를 덮어쓰지 않는다 |
| 사람 판단 수정(`order_plan_screening_feedback`) | **다른 경로·다른 revision.** 한 요청으로 합치지 않는다 |
| 적합성 등급 | 이 요청 범위 밖. 추적 결정이 등급을 채우지 않는다 |
| 참여 준비 상태 | 이 요청 범위 밖 |
| 심층 검토 실행 승인 | 사전규격의 별도 결정. 추적 시작이 실행 승인이 아니다 |
| 최종 입찰 Go/No-Go | 이 요청 범위 밖 |

`미선택`은 `종료`가 아니다. 결정하지 않았다는 뜻이며 자동으로 제외되지 않는다.

## 4. `이번 건 넘기기`의 의미

시안 `Main`의 결정 액션 네 개 중 `이번 건 넘기기`는 **저장하지 않는다.** 상태를 `미선택`에
그대로 두고 다음 발주계획으로 이동할 뿐이다. 서버 요청이 없으므로 이 계약의 범위 밖이며,
화면이 그 사실을 문구로 밝힌다. 넘기기를 `종료`로 저장하는 구현을 만들지 않는다.

## 5. 오류

기존 `opportunity_tracking.OpportunityTrackingError` 코드를 그대로 쓰고 두 개만 더한다.

| 코드 | HTTP | 뜻 |
|---|---|---|
| `not_found` | 404 | 발주계획이 없다 |
| `opportunity_not_found` | 409 | 발주계획을 소유한 authoritative 사업기회를 찾지 못했다 (**신규**) |
| `tracking_status_invalid` | 422 | 지원하지 않는 추적 상태(`미선택` 포함) |
| `tracking_reason_required` | 422 | 사유가 비었다 |
| `actor_name_required` | 422 | 담당자 표식이 없다 |
| `tracking_status_conflict` | 409 | `expected_tracking_status`가 현재 값과 다르다 (**신규**) |
| `idempotency_conflict` | 409 | 같은 `request_id`로 다른 본문이 왔다 |

`opportunity_not_found`를 404가 아니라 409로 두는 이유: 발주계획은 존재하는데 소유 관계가
아직 확정되지 않은 상태이며, 담당자가 사업기회 화면에서 연결을 확인하면 해소된다. 부재가
아니라 충돌이다.

## 6. 테스트 matrix (요청)

| 검사 | 기대 |
|---|---|
| `계속 추적` 저장 | 201, `Opportunity.tracking_status` 변경, `AuditEvent` 1건 추가 |
| 같은 `request_id` 재전송 | 201 동일 응답, `AuditEvent` 추가 없음 |
| `미선택` 전송 | 422 `tracking_status_invalid` |
| 사유 공백 | 422 `tracking_reason_required` |
| actor header 없음 | 422 `actor_name_required` |
| 소유 사업기회 없음 | 409 `opportunity_not_found`, 아무것도 쓰지 않음 |
| `expected_tracking_status` 불일치 | 409 `tracking_status_conflict`, 아무것도 쓰지 않음 |
| 추적 결정 저장 뒤 | `qwen_relevance`, BM25 stage 결과, `order_plan_screening_feedback`이 **변하지 않음** |
| 사람 판단 수정 저장 뒤 | `Opportunity.tracking_status`가 **변하지 않음** |
| 목록 응답 | `tracking`이 `null`인 건과 `미선택`인 건이 구분됨 |

마지막 세 줄이 이 요청의 핵심이다. 두 결정이 서로를 덮지 않는다는 것을 서버가 고정해야 한다.

## 7. 계약 확정 전까지 화면이 하는 것

화면 작업(`PLAN.md` 단계 C)은 이 계약을 기다리지 않고 진행하되, **없는 것을 있는 것처럼 보이게
하지 않는다.** 규칙은 다음과 같다.

1. 추적 결정 UI를 만들고, 저장은 `lib/api.ts`의 adapter 한 곳(`createOrderPlanTrackingDecision`,
   `getOrderPlanTracking*`)을 통해서만 부른다. 계약이 §2.3의 대안으로 확정되면 그 한 곳만 바꾼다.
2. **결정을 화면 상태에만 기록하지 않는다.** 서버가 404·501로 답하면 실패로 표시하고 다음 건으로
   이동하지 않으며, 그 건의 추적 상태를 바꾸지 않는다. 낙관적 갱신을 하지 않는다.
3. 응답에 `tracking`이 없으면 목록·상세는 추적 상태를 **`계약 미구현`으로 표시**한다.
   `미선택`으로도 `추적 없음`으로도 바꾸지 않는다.
4. Playwright fixture는 §2의 wire shape를 그대로 mock한다. 그 fixture가 이 요청안의 실행 가능한
   형태이며, **구현 완료의 근거가 아니다.**
5. 이 문서의 상태가 `채택`으로 바뀌고 backend가 구현·검증되기 전에는 단계 C를 "완료"로 적지
   않는다. [`../tracking/status.md`](../tracking/status.md)가 그 사실을 남긴다.

이 방식의 선례는 [`bid-delta-contract-spec.md`](../bid-delta-contract-spec.md)다. 그 문서도
"작업 트리의 frontend는 존재하지 않는 endpoint를 호출하는 시안이며 구현 완료 근거가 아니다"라고
같은 경계를 적었다.

## 8. 백엔드 파트에 묻는 것

1. §2.1의 field 추가에 `v2` schema를 새로 여는 것과 v1을 확장하는 것 중 어느 쪽인가.
   (`_Strict`라 확장은 소비자 변경을 강제한다.)
2. §2.2를 받는가, §2.3의 대안으로 가는가.
3. `opportunity_not_found`를 409로 두는 데 동의하는가.
4. 추적 결정 이력을 `AuditEvent` 투영으로 내는 것으로 충분한가, 전용 table을 원하는가.
   (화면은 어느 쪽이든 §2.1의 `tracking-decisions` 응답 모양만 지켜지면 된다.)
5. 사유를 자유 문자열로 둘 것인가, 화면의 사유 selector 값 집합을 계약이 고정할 것인가.
   시안은 `후속 사전규격·공고 확인` 같은 선택지를 보여 준다.
