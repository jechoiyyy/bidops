# ADR-0038: 발주계획 C-2 Phase 0 파일·REST·DB 계약

| 항목 | 내용 |
|---|---|
| 상태 | 채택 — 계약 고정만; 운영 활성화 아님 |
| 결정일 | 2026-09-01 |
| 범위 | 발주계획 C-2 `BM25 Top 300 + Qwen`의 Phase 0 |
| 선행 결정 | [ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md) |
| 정본 | [`docs/contracts.md`](../../contracts.md)의 `C-2 Phase 0 fixed contract`, `skills/bidops-screen/contracts/` |

## 문맥

ADR-0037은 고정 625건에서 BM25 Top 300 + Qwen을 비교 실험 방식으로 선택했다. 그러나 기존
`screening.v3`와 `ScreeningExecution`은 공고 다섯 관점 판정의 계약이므로 발주계획 제목
relevance를 그 안에 추가할 수 없다. Phase 1~5가 실험 산출물을 직접 읽거나 미확정 상태를
성공으로 해석하지 않도록 전용 file, REST, DB, 상태와 binding을 먼저 고정한다.

## 결정

### 전용 v1 artifact

다음 schema를 `skills/bidops-screen/contracts/`에 둔다. 모든 신규 JSON은
`schema_version`, `producer`, `consumer`, required key, status enum을 갖고 UTF-8·중복 key
금지·유한 숫자·timezone timestamp를 사용한다.

- `bidops.order-plan-screening-input.v1`: enqueue 때 얼린 `plan_id,title`와 source/policy binding
- `bidops.order-plan-screening-ranking.v1`: 전체 모집단의 BM25 score/rank와 `selected|filtered_out`
- `bidops.order-plan-screening-decisions.v1`: Top 300의 Qwen label과 batch/attempt
- `bidops.order-plan-screening-failures.v1`: 실패·거부·불명확 결과와 안전한 failure code
- `bidops.order-plan-screening-telemetry.v1`: execution/batch/attempt duration·token, 미측정은 `null`
- `bidops.order-plan-screening-result.v1`: stage1·stage2·실패를 합친 full-population result
- `bidops.order-plan-screening-feedback.v1`: 사람 relevance/priority/memo의 append-only revision

source binding의 `raw_manifest_sha256`는 연속된 raw page의 path와 byte SHA-256 canonical
manifest를 고정하며, validator는 page query와 source window도 함께 대조한다. 정책은
`experiments/order-plan-screening/config/order-plan-screening-policy.v1.json`, 현재
실험과 입력을 연결하는 immutable binding은
`experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json`이다.
현재 policy SHA-256은
`3010c7bfb569e062fc8e94b052df0325caccad7e23a34cf1e15dad6a6358e196`, binding SHA-256은
`e0367de6155e362539a867d3b6820e204ba1238a2a613c6b973780c8348c86ef`다. Qwen generation
config digest `1fd2f511a0b1c99f5a57125ebd9e1d67314d98202d42327394daa540abd27754`도
historical result와 policy/binding에 고정한다.

### 상태 분리

- `filtered_out`은 BM25 Top 300 경계이며 `not_relevant`가 아니다.
- `relevant|not_relevant|uncertain`은 발주계획 relevance만 나타낸다.
- `unknown`은 정보 부족·결정 불가, `null`은 미시도·비적용 field다.
- `failed`는 시도된 단계의 runtime/validation 실패, `rejected`는 preflight·binding·payload·policy
  거부다. 어느 것도 `not_relevant`로 보정하지 않는다.
- 기존 적합성 `grade`, 참여 `readiness`, 사업기회 `tracking_status`, 최종 `go_no_go`는 C-2
  result·feedback의 별도 축이다.

실행 전이는 `대기 → 실행 중 → 성공|부분 성공|실패`, `실행 중 → 중지 요청 → 중단됨`,
`대기 → 중단됨`만 허용한다. active slot은 1, batch는 stage1 rank 순서의 25건, retryable
실패의 최대 시도는 2회다. binding/model/payload/policy 거부는 재시도하지 않는다. stale는
자동 resume하지 않고 성공 subset과 failure를 보존한 새 execution으로 사람이 재시작한다.

### 현재 차단 경계

현재 C-1 gold manifest는 `partially_human_adjudicated`다. 사람 adjudication 22건, draft
603건, remaining confirmation 87건을 유지하며, draft를 사람 정답으로 승격하지 않는다.
감사 표본의 크기·주기, 승인 gold 기반 quality threshold, execution별 private vLLM 전송 승인이
없으므로 policy와 binding은 `blocked`, transport는 `execution_allowed=false`다. 검증기는
이 상태에서 `valid_but_blocked`만 반환하며 policy activation이나 endpoint 호출을 수행하지
않는다. scheduler 결정은 이 ADR의 범위가 아니다.

## REST 경계

수동 API는 기존 `/api/screening`과 분리된 `/api/order-plans` 및
`/api/order-plan-screening` namespace를 사용한다. 목록·상세·history·execution·artifact·
feedback·policy inspect/candidate/activate 경로와 required request/response/error envelope는
`docs/contracts.md`의 C-2 REST 표를 정본으로 한다. mutation은 `X-BidOps-Actor-Name`을
감사 표식으로 요구하고, request ID exact replay만 idempotent하게 처리한다. current blocked
binding에서는 execution/activate 성공을 반환하지 않는다.

## DB 경계

Phase 2는 `order_plan_screening_policy`, `order_plan_screening_execution`,
`order_plan_screening_batch_attempt`, `order_plan_screening_result`,
`order_plan_screening_artifact`, `order_plan_screening_feedback` 전용 table을 새로 만든다.
기존 공고용 `screening_*` table의 의미는 변경하지 않는다. execution+plan result와 feedback
revision은 unique, source/policy/binding digest는 immutable, artifact/result/feedback는
append-only다. app·worker·migration owner·`ro_backup` 권한은 분리하고 prompt/profile/model
response 본문은 DB·로그·API에 넣지 않는다.

현재 Alembic head는 `0015_bid_delta_final_decision`이다. Phase 0에서는 migration을 만들지
않고, Phase 2 착수 시 head를 재확인해 `0016_order_plan_screening` 이후 revision으로 만든다.
실제 PostgreSQL 17 제약·trigger·runtime privilege 검증은 그 migration의 완료 조건이다.

## 결과

Phase 1은 전용 v1 schema와 Phase 0 binding을 입력으로 받아 결정적 BM25와 merge producer를
구현한다. Phase 2~5는 같은 digest와 상태 의미를 유지해야 하며, 새 의미를 추가하면 v2와
새 binding을 만든다. 역사적 실험 evidence와 gold 파일은 이 ADR을 맞추기 위해 수정하지 않는다.
