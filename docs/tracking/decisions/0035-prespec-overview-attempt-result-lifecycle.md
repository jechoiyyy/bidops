# 사전규격 개요 모델 attempt의 상태 전이와 검증 결과를 분리한다

- 상태: 채택
- 일자: 2026-08-31
- 구현 상태: phase 1과 phase 2의 persistence·lifecycle service·안전한 REST projection을
  구현했다. 실제 사설 모델 transport·worker 실행과 승인 binding은 아직 남았다.

## 맥락

[ADR-0033](0033-prespec-overview-review-runtime-contract.md)은 결정적 절단 snapshot과 모델
attempt를 분리하고, 승인된 사설 vLLM binding이 없으면 `awaiting_model`에서 멈추도록
정했다. phase 1은 이 계약에 따라 snapshot 준비와 안전한 조회까지 구현했다.

결정 당시 `prespec_overview_attempt` row는 UPDATE 전체를 거부하는 append-only 구조인데 상태는
`queued | running | completed | failed | cancelled`를 사용한다. 이대로는 worker가 실제
실행의 시작·종료를 같은 attempt 계보에 기록할 수 없다. 반대로 row 전체 UPDATE를 허용하면
snapshot, 입력 hash, sequence, 모델 binding까지 바뀌어 과거 실행을 재현할 수 없게 된다.

또한 현재 phase 1 API의 `result`는 nullable 결과 범주뿐이다. 조건, 확인 기한, unknown,
근거 locator와 입력 한계를 strict schema로 검증하고 안전하게 내보낼 계약이 필요하다.

## 결정

### 1. attempt 식별·입력·모델 binding은 생성 뒤 불변이다

attempt의 review·snapshot·sequence, 입력 hash, provider/model binding과 binding digest,
`reference_only`·`deployable` 표식은 insert 뒤 바꾸지 않는다. 재실행은 기존 attempt를
초기화하지 않고 sequence가 증가한 새 attempt를 만든다.

운영 runtime 권한은 attempt의 `status`, 허용된 시작·종료 시각, 검증 결과 참조처럼
생애주기에 필요한 열만 column-scoped UPDATE로 연다. 입력·binding 열의 UPDATE와 모든
DELETE는 runtime role에 부여하지 않는다. DB의 단일 상태 전이 trigger는 terminal attempt를
`queued`나 `running`으로 되돌리는 것을 포함한 허용 목록 밖 상태 간선만 거부한다.

허용 전이는 다음과 같다.

- `queued → running | failed | cancelled`
- `running → completed | failed | cancelled`

`completed` 전이는 서비스가 같은 transaction에서 검증 완료 result를 정확히 하나 연결한
경우에만 수행한다. lease 상실, timeout, schema 위반, evidence 검증 실패는 성공으로
보정하지 않고 안전한 실패 code와 함께 `failed`로 닫거나 새 attempt로 재시도한다.

DB 경계는 의도적으로 가볍게 유지한다. FK·UNIQUE·CHECK는 row 구조를, runtime privilege는
입력 계보와 result/event의 불변성을, 상태 전이 trigger 하나는 불가능한 상태 간선을 맡는다.
result scope 검증, event와 상태 변경의 동반, 현재 review projection 갱신은
`prespec_overview` service가 한 transaction으로 묶는다. 이를 다시 교차 table trigger로
중복하지 않는다. migration owner의 임의 SQL은 지원하는 runtime 쓰기 경로가 아니다.

### 2. runtime service의 모든 상태 전이는 별도 append-only event로 감사한다

상태 변경마다 attempt ID와 attempt sequence, event sequence, 이전·다음 상태, 발생 시각,
worker 또는 actor 식별자, request/trace 식별자와 안전한 reason code를 별도 event row에
insert한다. event는 UPDATE·DELETE하지 않는다. endpoint, prompt, 모델 원응답, object path,
credential과 lease 원문은 event나 애플리케이션 로그에 넣지 않는다.

### 3. 검증 결과는 attempt와 분리한 immutable row에 한 번만 기록한다

검증을 통과한 결과는 attempt당 최대 하나인 별도 result row에 insert한다. result payload,
snapshot·source hash binding, result digest, schema version과 생성 시각은 insert 뒤
UPDATE·DELETE하지 않는다. 결과를 다시 만들려면 새 attempt와 새 result를 만든다.

결과 payload는 다음 strict shape를 최소 계약으로 사용한다.

- `schema_version`: `bidops.prespec-overview-result.v1`
- `recommendation`: `추진 검토 | 조건부 추진 검토 | 보류 | 검토 종료`
- `summary`: 비어 있지 않은 문자열
- `conditions[]`: 비어 있지 않은 조건 문자열 목록
- `verification_due_at`: RFC 3339 시각 또는 `null`
- `unknowns[]`: `topic`, `reason`, nullable `verification_action`을 가진 object 목록
- `evidence[]`: `claim`, 그리고 현재 snapshot의 `block_key`·`page`·결정적 `ordinal`을
  가진 `locator` object 목록
- `input_limitations[]`: 비어 있지 않은 문자열 목록

알 수 없는 top-level·nested field, 닫힌 enum 밖의 값, 빈 필수 문자열, 현재 snapshot 밖의
locator는 거부한다. `조건부 추진 검토`는 `conditions`가 비어 있지 않고
`verification_due_at`이 `null`이 아니어야 한다. evidence locator와 source hash가 현재
snapshot 안에서 검증되지 않으면 attempt를 `completed`로 만들지 않는다. unknown이나
입력 한계는 빈 문자열, 거짓 근거, 추정값으로 보정하지 않는다.

### 4. 안전한 API에는 검증 결과와 binding digest만 노출한다

phase 2 API는 검증된 result payload, result digest와 승인 binding의 digest만 반환한다.
provider endpoint, prompt, 모델 원응답, object key/path, credential과 내부 오류 detail은
반환하지 않는다. 공고·review·snapshot ID가 요청 scope와 다르면 교차 공고 내용을
렌더링하지 않고 fail closed한다.

`bidops.prespec-overview-reviews.v1`은 phase 1 wire로 그대로 유지한다. phase 2는 기존 v1의
scalar nullable `result` 의미를 바꾸지 않고 `bidops.prespec-overview-reviews.v2`를 발행해
검증 결과 object를 노출하며, 상세 계약은 [`contracts.md`](../../contracts.md)에 둔다.

### 5. 모델 전송 경계는 ADR-0033을 유지한다

실제 호출은 승인된 로컬 또는 사설 OpenAI-compatible vLLM binding에만 허용한다. 승인된
binding이 없으면 `awaiting_model`을 유지하고 attempt를 만들지 않는다. hosted OpenAI,
Codex 또는 다른 외부 provider로 자동 fallback하지 않는다. 결정적 mock은 계속
`reference_only`, `deployable=false`이며 운영 완료로 집계하지 않는다.

## 대안

**attempt와 모든 전이를 event-sourcing하고 현재 상태를 projection으로 계산 — 소거했다.**

불변성은 강하지만 현재 worker·조회·복구 범위에 비해 projection과 운영 복잡도가 크다.
입력 열 불변, 제한된 상태 열 UPDATE, append-only event 조합으로 필요한 감사를 충족한다.

**실행 중에는 review만 바꾸고 종료 뒤 attempt를 한 번 insert — 소거했다.**

crash나 lease 상실 때 실제로 시작된 실행과 binding 계보가 남지 않는다.

**attempt row 전체 UPDATE 허용 — 소거했다.**

상태 전이 편의를 위해 입력 hash·snapshot·binding까지 덮어쓸 수 있게 되어 재현성과 최소
권한 경계를 깨뜨린다.

## 결과

- T-23 phase 2의 persistence, 상태 전이 service, 검증 결과 저장과 안전한 v2 projection을
  구현했다.
- crash·취소·실패·재시도의 이력을 result와 섞지 않고 되짚을 수 있다.
- 검증되지 않은 결과나 snapshot 밖 근거는 완료·API 결과로 승격되지 않는다.
- 이 구현은 실제 사설 모델 transport·worker 실행 완료나 binding의 배포 승인을 뜻하지
  않는다.
