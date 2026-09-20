# 발주계획 일괄 추적 종료를 연다

- 상태: 채택 (2026-09-20 사용자 결정)
- 일자: 2026-09-20
- 관련 결정: `docs/business-rules.md` "발주계획 일괄 추적과 단건 추적"·"목록 선택과 사전규격 상세 순회"의 "일괄 hold/close는 제공하지 않는다" 부분 개정(종료만), [ADR-0062](0062-explore-workspace-structure-unification.md)(같은 작업의 화면 통일)
- 근거 요청: 사용자 요청 2026-09-20 — "`/order-plans`에서 이미 확인한 것들이나 추적 종료할 공고들은 누적에서 보이지 않게, 선택한 공고를 일괄 추적 종료"

## 맥락

발주계획 누적 목록의 기본 보기(`검토 대상`)는 추적 상태가 `미선택`인 관련 건만 보여 준다. 이미 `계속 추적`·`보류`·`종료`로
정한 건은 지금도 숨겨진다. 남는 것은 **보았지만 아무 결정도 하지 않은 `미선택` 건**이고, 하루 수십 건씩 쌓인다. 이를 목록에서
치우는 길은 상세에서 한 건씩 `추적 종료`를 누르는 것뿐이었다. 일괄 경로는 `추적 시작`만 있었고 업무 규칙이 일괄 보류·종료를
비목표로 못박고 있었다.

검토한 대안:

- **"확인함" 표식을 새로 저장한다.** 종료와 "그냥 봤음"을 구분할 수 있지만 새 사람 판정 필드·migration·필터 축이 생기고,
  적합성 등급·추적 선택·Go/No-Go를 서로 대신하지 않는다는 게이트 옆에 뜻이 겹치는 네 번째 상태가 생긴다. 채택하지 않았다.
- **사람 피드백(`screening-feedback`) 유무로 숨긴다.** 피드백은 품질 측정용 정답 기록이라 "숨기기" 용도로 쓰면 의미가 섞인다.
  채택하지 않았다.

## 결정

1. **숨김 기준은 추적 종료로 통일한다.** 새 상태·필드·migration을 만들지 않는다. 관심 없는 건은 `종료`로 처리하고, `종료`
   건은 기본 보기에서 빠진다(`전체` 보기, 추적 필터 `종료`, `/opportunities`의 `추적 종료` 구역에서는 계속 조회된다).
   `종료`의 뜻은 그대로다 — 현재 사업기회에 대한 능동 추적을 끝냄이며 영구 삭제가 아니다.
2. **일괄 추적 종료를 연다. 일괄 보류는 열지 않는다.** 보류는 다시 봐야 하는 건이라 일괄 처리의 실익이 작다.
3. **REST는 `POST /api/opportunities/order-plan-tracking/bulk-end`를 새로 둔다.** 기존 `bulk-start`에 `action`을 더해
   일반화하지 않는다 — `bulk-start` v1은 목표 상태를 `계속 추적`으로 고정한 계약이고, receipt의 canonical hash와 결정적
   receipt id가 operation 문자열에 묶여 있어 일반화하면 이미 commit된 receipt의 replay 해시가 바뀐다. `preview`는 두 작업이
   공유한다(`eligible` = 현재 `미선택`).
4. **안전장치는 일괄 추적 시작과 같다.** 미리보기, 공통 담당자 이름(감사 표식), 공통 사유, 확인 단계, owner당 `AuditEvent`
   1건, `request_id` 멱등 receipt. 대상은 현재 `미선택`인 owner뿐이고 나머지는 상태별 제외다. 소유 사업기회가 없으면 만들지
   않고 `owning_opportunity_missing` 실패 항목으로 둔다. 같은 `request_id`를 start와 end에 보내도 receipt id가 operation별로
   갈라져 서로 replay·conflict를 일으키지 않으며, 화면은 저장한 대기 요청에 작업 종류를 함께 묶어 같은 요청이 다른 경로로
   가지 않게 한다.
5. **한 요청의 상한은 200건이다(PoC 값).** 일괄 종료에는 일괄 되돌리기가 없고 되돌림은 단건 PATCH뿐이므로 오조작의 폭을
   제한한다. 초과는 422로 거부하고 화면이 같은 값으로 미리 막는다. `bulk-start` v1에는 상한을 더하지 않는다(계약 불변).
   운영 전환 때 값을 다시 정한다.
6. **post-commit hook은 `tracking_decision_changed` 하나를 그대로 부른다.** 상태와 무관한 "추적 결정이 바뀜" 신호다. 단건
   PATCH의 record backfill은 일괄 경로에 없고 `종료`는 backfill 대상 상태도 아니다.

## 결과

- migration 없음. `IdempotencyRecord.operation`은 `String(128)`이고 CHECK·enum이 없다. Alembic head는 0029 그대로다.
- 로그 이벤트 이름은 종료를 `order_plan.bulk_tracking_end.{succeeded,replayed,conflict}`로 구분한다. 필드 allowlist는 같다.
- 422 본문은 FastAPI 기본 검증 오류 형식이며 보낸 ID 배열을 되돌려 준다(기존 잘못된 ID 422와 같은 동작, 비밀 없음).
- 남은 것: 일괄 시작에는 단건과 달리 record backfill 호출이 없고(의도 미확인) 선택 상한도 없다 — `docs/tracking/findings.md`.
