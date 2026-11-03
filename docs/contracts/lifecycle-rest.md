# 생애주기 REST·입찰 delta

[전체 계약](../contracts.md). 기준일: 2026-10-21. 공통 REST·상태 규칙은 상위 문서를 함께 적용한다. 계약의 존재는 운영 활성화·품질 인수를 뜻하지 않는다.

## 구현된 계약 — 입찰 delta와 최종 결정 (R-07 채택, R-08 구현)

이 절은 [ADR-0034](../tracking/decisions/0034-bid-delta-final-decision.md)와
[OpenAPI·DB 명세](../bid-delta-contract-spec.md)로 채택하고 R-08에서 구현한 계약이다.
아래 경로는 `web/backend/app/deep_review/routers/bid_delta.py`에 존재하며 `app/main.py`에 등록되어 있다.
저장은 `bid_delta_comparison`, `bid_delta_attempt`, `bid_delta_item`, `bid_delta_evidence`,
`bid_final_decision` 5개 table과 revision `0015_bid_delta_final_decision`이 소유한다.

구현 경계는 다음과 같다. 비교 생성은 `pending` comparison과 `queued` attempt를 만들고 202를
반환할 뿐, **비교를 실제로 계산하는 worker와 모델 호출은 아직 구현하지 않았다.** 계산 완료와
실패 전이는 그 worker가 호출할 service 경계(`start_attempt`, `complete_attempt`,
`fail_attempt`)로만 존재하며 HTTP로 노출하지 않는다. 승인된 회사 내부망 binding을 확인할 수
없으면 비교 생성은 503 `bid_delta_service_unavailable`로 fail closed하고 어떤 외부 전송도
하지 않는다. 운영 활성화는 별도 결정이다.

**결정 근거 분리 (ADR-0058, migration `0028_final_decision_basis`).** 비교 worker가 없어도
사람이 최종 Go/No-Go를 기록할 수 있도록, `bid_final_decision.basis_kind`가 `comparison`(위
비교 fence) 또는 `notice_conditions`(공고 조건)를 갖는다. 공고 조건 근거는 `GET
/api/opportunities/{id}/bid-conditions`(모델 호출 없는 결정적 읽기: authoritative 입찰공고를
`bid_no`·`bid_ord` 순으로 나열하고 차수 간 변경·사전규격 대비를 계산)와 `POST
/api/opportunities/{id}/final-decisions`(`expected_notice_id`·`expected_observation_sha256`
fence, actor·사유·idempotency는 비교 근거와 같은 함수 공유)로 별도 경로를 갖는다. 현재성은
근거별로 `services/bid_delta_currentness.py` 한 곳에서 계산해 workspace·결정 큐·업무 집계가
같은 값을 쓴다. 상세 wire shape·오류 표는 [입찰 delta 계약 명세](../bid-delta-contract-spec.md)와
[심층 검토 ERD](../deep-review-erd.md) §8.6, 결정 배경은 [ADR-0058](../tracking/decisions/0058-final-decision-basis-separated-from-comparison.md)이 정본이다.

경로는 다음과 같다.

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/opportunities/{opportunity_id}/bid-delta` | active opportunity ID | 200 `bidops.bid-delta-workspace.v1`; 선택 가능한 exact baseline/comparison snapshot과 기존 비교·결정 projection | 404 `opportunity_not_found`; 409 `opportunity_merged`; 503 `bid_delta_projection_unavailable` |
| `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons` | actor header; UUID request ID, category policy version, 양쪽 exact input fence | 202 `bidops.bid-delta-comparison.v1` | 400 actor; 404 input; 409 authoritative/readiness/scope/version/idempotency; 422 type/policy; 503 policy/service |
| `GET /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}` | opportunity ID와 comparison UUID | 200 comparison, items, 양쪽 evidence, attempts, append-only decision history | 404 not found; 409 scope; 503 projection |
| `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/attempts` | actor header; UUID request ID, expected comparison version | 202 새 append-only attempt를 포함한 comparison | 404 not found; 409 not retryable/version/active/idempotency; 422 구조 검증; 503 service |
| `POST /api/opportunities/{opportunity_id}/bid-delta/comparisons/{comparison_id}/final-decisions` | actor header; decision, nonblank reason, UUID request ID, comparison version/result hash/양쪽 document version fence, supersedes ID | 201 append-only `BidFinalDecisionView` | 400 actor/reason; 404 not found; 409 not completed/version/digest/stale/supersession/idempotency; 422 enum/fence; 503 currentness |

comparison의 baseline·comparison은 각각 authoritative opportunity link, notice, ready bundle,
bundle revision/version, document version ID와 version, structure ID, source SHA-256, structure
payload SHA-256을 고정한다. 여러 입찰공고·정정 중 서버가 `latest`를 추정하지 않으며 요청이
exact pair를 고른다. 새 공고·정정은 기존 comparison이나 결정을 덮지 않고 새 후보가 된다.

calculation status는 `pending|running|completed|failed`, nullable result status는
`changed|unchanged|unknown|failed`다. pending/running의 result는 null이고 failed 계산의
result는 failed다. completed item 하나라도 unknown/failed면 전체 result를 unchanged로 만들지
않는다. `changed|unchanged` item은 기준·비교 양쪽에 exact document/structure/hash와 일치하는
verified locator가 필요하다.

category enum은 `budget_and_economics`, `contract_period_and_schedule`, `eligibility`,
`joint_supply_and_subcontracting`, `scope_and_requirements`, `evaluation`, `submission`이다.
보수적 v1 policy는 공식 값·조건의 실질 변경을 `material`, 양쪽 근거로 의미가 같음이 검증된
표기·절 번호·서식·오탈자 차이만 `non_material`로 둔다. 근거 부족은 `unknown`, 추출·검증
실패는 `failed`이며 수치 임계값을 추정하지 않는다.

최종 결정은 comparison version, result digest, 양쪽 document version에 묶인 별도
append-only row다. actor는 기존 `X-BidOps-Actor-Name` 경계를 따르고 reason·request ID를
요구한다. 새 결정은 직전 결정을 `supersedes_final_decision_id`로 가리킬 뿐 과거 row를
수정하지 않는다. `current|stale|unknown`은 이력 row를 바꾸지 않는 projection이며 시스템
delta·tracking status·심층 검토 final opinion이 사람 결정을 자동 생성하지 않는다.

final decision enum은 `go|no_go`다. strict C1에 따라 새 authoritative 입찰공고·정정 또는
새 ready 비교 문서가 나타나면 기존 decision projection은 즉시 `stale`, 순서나 효력을
확정할 수 없으면 `unknown`이다. 회사 내부망의 allowlist된 사설 vLLM만 사용하며,
exact pair·policy·binding·payload 범위를 확인한 comparison 생성 요청이 건별 내부 모델 처리
승인이다. 외부·hosted fallback은 없고 감사 metadata는 안전한 ID·code·count·hash·binding
digest allowlist만 사용한다. binding은 심층 검토가 쓰는 승인된 사설 vLLM `qwen3.8-27B`를
재사용하며 새 endpoint를 열지 않는다.

비교 대상 문서 role allowlist는 2026-08-31에 확정했다. baseline(사전규격)은
`제안요청서|과업지시서|내역서|제출서식`, comparison(입찰공고)은
`공고|정정|제안요청서|과업지시서|내역서|제출서식`이다. `내역서`는 `budget_and_economics`,
`제출서식`은 `submission` 범주의 근거가 되므로 포함하고 `부록`·`기타`는 제외한다.
allowlist 밖 role의 문서는 후보로 노출되지 않으므로 선택 자체가 불가능하다. 범주 정책은
`bid-delta-policy.v1` 7개로 확정했고 범주 추가는 policy version을 올린다.

채택 계약의 domain 오류는 기존 안전 envelope와 stable code를 사용한다. 구조 자체가 FastAPI
검증을 통과하지 못한 422는 기존 Lean 규칙대로 `detail[]`일 수 있고, parsing 뒤 semantic
422는 `bid_delta_same_input`, `bid_delta_baseline_type_invalid`,
`bid_delta_comparison_type_invalid`, `bid_delta_category_policy_invalid`,
`final_decision_value_invalid`, `final_decision_input_fence_invalid` 중 하나다. 전체 404/409/422/503
code와 테스트 조합은 상세 명세를 따른다.

## 현재 REST 경로

아래 경로는 세 도메인 모듈을 모두 등록한 기본 기동(`BIDOPS_MODULES` 미지정)의 표면이다. `BIDOPS_MODULES`로 모듈을 꺼서 기동하면 그 모듈이 소유한 경로는 등록되지 않아 404이며, `GET /api/health`는 어떤 조합에도 있다([ADR-0045](../tracking/decisions/0045-backend-module-layout.md)). 경로·입력·응답 자체는 모듈 선택과 무관하게 이 절의 계약 그대로다.

### 상태, 회차, 공고

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/health` | 없음 | `{"status":"ok"}` | 프로세스 불가용 |
| `GET /api/workload` | 없음 | `WorkloadResponse` — 집계 시각과 고정 순서 열 항목 | 제공자 부재는 200의 null·사유 |
| `GET /api/runs` | 없음 | `{items: RunSummary[], total}` 전체 회차 | 없음 |
| `POST /api/runs/ingest` | body 또는 query의 run ID | 적재·재적재 건수와 경고 | 404 run directory, 422 run ID 부재 |
| `GET /api/runs/{run_id}` | path run ID | `RunDetailResponse` | 404 |
| `GET /api/runs/{run_id}/stats` | path run ID | `RunStatsResponse`; 계산 불가 count는 null | 404 |
| `GET /api/runs/{run_id}/warnings` | path run ID; optional query `level`, `code` | `WarningListResponse` | 404 |
| `GET /api/runs/{run_id}/pipeline/logs` | path run ID; optional query `execution_id` | `PipelineLogResponse` | 404 |
| `POST /api/runs/{run_id}/pipeline/{stage}` | `stage=collect|sample|report`; optional query `from_raw=false` 또는 optional body `{from_raw:false}` | 202 `PipelineExecutionResponse` | 400 입력·stage, 404 run, 409 active 충돌, 422 body·query |
| `GET /api/notices` | `NoticeList` query | `NoticeListResponse` | 404 run, 422 query |
| `GET /api/pre-specs` | 누적 `PreSpecList` query; 기본 `sw_only=true`; optional `auto_preparation_status`, `deadline_within_days` | `PreSpecListResponse` | 422 query |
| `GET /api/notices/{notice_pk}` | path DB integer notice PK | `NoticeDetailResponse` | 404 |
| `GET /api/notices/{notice_pk}/related` | path DB integer notice PK | `RelatedNoticeListResponse` | 404 |
| `GET /api/notices/{notice_pk}/history` | path DB integer notice PK | `NoticeHistoryResponse` | 404 |
| `GET /api/notices/{notice_pk}/revision-history` | path DB integer notice PK | 200 `NoticeRevisionHistoryResponse`; append-only judgment/review를 sequence 오름차순으로 반환 | 404 `notice_not_found`; 409 `revision_history_conflict`; 500 `processing_failed` |

revision-history의 404·409·500은 공통 안전 envelope를 사용하며 `details`와 `request_id`는
`null`이다. 저장된 same-notice parent, runtime root execution, review의 exact judgment pin을
해석할 수 없으면 내부 row·SQL·예외를 노출하지 않고 409 `revision_history_conflict`로 닫는다.
그 밖의 예상하지 못한 조회 실패는 500 `processing_failed`다.

### 사업기회와 추적

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/opportunities` | optional `tracking_status`, `first_registered_stage`, `section=조치 필요\|추적 중\|보류\|추적 종료\|신규 입찰공고`, `reason=new_link\|candidate_pending\|merge_confirmation\|blocking_item\|hold_overdue`, `hold_review=overdue\|due_soon\|attention`, `deadline_within_days`(1..365), `q`(2~100자), `sort=created_at\|tracking_status\|first_registered_stage\|hold_review_due_at\|deadline`, `limit` 1..500(default 50), `offset` 0 이상 | `OpportunityListResponse`(`section_counts`·`action_reason_counts` 포함); 기본값은 `종료`를 포함한 전체 | 422 query(`section=미결정`은 집계 전용이라 값 자체를 거부) |
| `GET /api/opportunities/{opportunity_id}` | path DB integer opportunity ID | `OpportunityDetailResponse`; `검색 미확인` link를 포함한 전체 link 목록 | 404 `opportunity_not_found` |
| `GET /api/opportunities/{opportunity_id}/activity` | path DB integer opportunity ID; optional `kinds`(아래 kind 13값의 csv), `limit` 1..200(기본 50), `before`(opaque 커서) | 200 `OpportunityActivityResponse`(`bidops.opportunity-activity.v1`, 아래 "레코드 활동 피드"); 병합된 사업기회도 200이며 `merged_into_opportunity_id`를 채운다 | 404 `opportunity_not_found`; 422 `invalid_request`(모르는 kind·읽을 수 없는 커서)·limit 범위; 확장점 제공자의 예외는 500 `processing_failed` |
| `POST /api/opportunities/{opportunity_id}/notes` | actor headers; body `{kind=note\|action, body(trim 뒤 1..2000자), owner?(≤128자), request_id:UUID}` | 201 `NoteView`(새 노트), 같은 요청의 재생은 200 같은 JSON | 400 `actor_name_required\|actor_name_invalid`; 404 `opportunity_not_found`; 409 `opportunity_merged`·`idempotency_conflict`; 422 body·`invalid_request` |
| `PATCH /api/opportunities/{opportunity_id}/notes/{note_id}/done` | actor headers; body `{request_id:UUID}` | 200 `NoteView`(`done_by`=actor); 이미 완료된 행동은 바꾸지 않고 현재 값 200 | 400 actor; 404 `opportunity_not_found`·`not_found`(노트 없음·다른 사업기회의 노트); 409 `opportunity_merged`·`note_not_action`(`kind=note`)·`idempotency_conflict`; 422 body·path |
| `GET /api/opportunities/{opportunity_id}/deep-reviews` | path DB integer opportunity ID | 200 `{opportunity_id, items[]}` — 연결 공고 전체의 심층 검토 목록 | 404 `not_found`; 422 path; 500 `processing_failed` |
| `GET /api/opportunities/{opportunity_id}/tracking-decisions` | path DB integer opportunity ID | 200 `{opportunity_id, items[], recheck_events[]}`; `items`는 append-only 추적 결정 이력, `recheck_events`는 신호 생성·확인·해제를 감사에서 투영한 이력(`kind=created\|acknowledged\|cleared_by_decision`, `link_id?`, `actor_kind`, `claimed_name?`, `created_at`, `note_present`) | 404 `opportunity_not_found` |
| `POST /api/opportunities/{opportunity_id}/recheck-acknowledgements` | actor headers; body `{expected_link_id, note?(≤500자)}` | 200 `OpportunityDetailResponse`; 신호를 해제하고 추적 상태는 바꾸지 않음 | 400 `actor_name_required\|actor_name_invalid`; 404 `opportunity_not_found`; 409 `recheck_signal_absent`(신호 없음)·`recheck_signal_changed`(근거 링크가 바뀜, details `{current_link_id}`)·`opportunity_merged`; 422 body |
| `POST /api/opportunities/{opportunity_id}/searches` | actor headers; body `{target=pre_spec\|bid_notice}` | 200 `OpportunitySearchResponse`(`searched_at`, `target`, `attempted_strategies[]`, `candidates: OpportunityLinkView[]`, `search_unconfirmed`) | 400 actor; 404 `opportunity_not_found`; 409 `opportunity_merged`; 422 `search_source_missing`(소유 발주계획·사전규격 없음)·body |
| `GET /api/pre-specs/{notice_pk}/order-plan-candidates` | path DB integer notice PK | 200 `PreSpecOrderPlanCandidatesResponse`(`notice_pk`, `items[]`; item은 `link`, `opportunity_id`, `tracking_status`, `order_plans[]` 발주계획 요약) | 404 사전규격 없음 |
| `GET /api/bid-delta/decision-queue` | `status=pending\|all`(기본 `pending`), `limit` 1..500(기본 50), `offset` 0 이상 | 200 `{items, total, limit, offset}`; item은 `opportunity_id`, `title`, `agency`, `tracking_status`, `first_registered_stage`, `recheck_signal`, `bid_notice_external_id`, `comparison_count`, `latest_final_decision`, `decision_currentness`, `deadline_at`, `budget`, `estimated_price`(추가형, PoC) | 422 query; 500 안전 오류 |
| `POST /api/opportunities/order-plan-tracking/preview` | body `{"schema_version":"order-plan-bulk-preview-request.v1","order_plan_ids":[1,2]}` (ID는 positive integer[]); 빈 목록·bool·0·음수·unknown field 거부 | 200 `order-plan-bulk-preview-response.v1` (아래 wire) | 422 body 또는 `invalid_request`; 503 `temporarily_unavailable` |
| `POST /api/opportunities/order-plan-tracking/bulk-start` | actor headers; body `{"schema_version":"order-plan-bulk-start-request.v1","request_id":"UUID","order_plan_ids":[1,2],"reason":"nonblank"}` (ID는 positive integer[]) | 200 `order-plan-bulk-start-response.v1` 최종 receipt (아래 wire) | 400 actor; 409 `idempotency_conflict`; 422 body/`invalid_request`·`tracking_reason_required`; 500 `processing_failed`; 503 `temporarily_unavailable` |
| `POST /api/opportunities/order-plan-tracking/bulk-end` | actor headers; body `{"schema_version":"order-plan-bulk-end-request.v1","request_id":"UUID","order_plan_ids":[1,2],"reason":"nonblank"}` (ID는 positive integer[] 1..200건) | 200 `order-plan-bulk-end-response.v1` 최종 receipt (아래 wire) | 400 actor; 409 `idempotency_conflict`; 422 body(201건 이상은 FastAPI `too_long`)/`invalid_request`·`tracking_reason_required`; 500 `processing_failed`; 503 `temporarily_unavailable` |
| `PATCH /api/opportunities/{opportunity_id}/tracking-status` | actor headers; body `{tracking_status, reason}` | 200 `OpportunityDetailResponse` | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_not_found`; 422 `tracking_status_invalid|tracking_reason_required` |
| `PATCH /api/opportunities/links/{link_id}/decision` | actor headers; body `{decision=accepted|rejected, reason}` | 200 `OpportunityLinkView`; 동일 actor·판정·이유 replay는 같은 reviewed_at | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_link_not_found`; 409 `candidate_link_required|candidate_decision_conflict|candidate_state_conflict|candidate_target_required|candidate_target_already_authoritative|candidate_merge_state_conflict|opportunity_merge_state_conflict`; 422 body·link ID·blank reason |

추적 상태 변경은 `set_tracking_status()`를 통해 사람 선택과 감사 이벤트를 함께 기록한다. `X-BidOps-Actor-Name`은 인증이 아닌 감사 표식이며, 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 사용한다. `recheck_signal`은 시스템 신호 여부이고 `recheck_signal_at`·`recheck_signal_link_id`는 그 시각과 근거 link를 가리킨다. 이 값들은 사람의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at`과 별도이며, `FinalOpinion` 또는 최종 입찰 `Go/No-Go`로 변환하지 않는다.

후보 수락(`PATCH …/links/{id}/decision` `accepted`)이 대상을 이미 소유한 다른 active 사업기회로 이끌면 §3.2와 같은 규칙으로 병합한다. 사람 상태 보유(`tracking_status ≠ 미선택` 또는 `recheck_signal_at IS NOT NULL`) 사업기회가 둘 중 1개 이하면 병합하고 후보 link를 `사람 확인 병합`(비소유, `human_decision=accepted`)으로 남긴다 — 소유권은 옮겨진 공식 link가 갖는다. **둘 다 사람 상태를 갖더라도 두 `tracking_status`가 같고 양쪽 모두 `recheck_signal_at IS NULL`이면 병합한다(2026-09-22, [ADR-0068](../tracking/decisions/0068-same-state-merge-and-tracking-reset.md)).** 유지 쪽은 둘 중 오래된 사업기회(`created_at`, 동률이면 `id`)이고 그 추적 상태·사유·선택자·시각은 바뀌지 않으며, 병합된 쪽의 결정은 그 행에 남는 것과 별도로 감사 이벤트 `opportunity.merged.human_confirmed`의 `safe_metadata.merged_human_states[] = [{id, tracking_status, tracking_reason, tracking_selected_by, tracking_selected_at}]`에도 적힌다(같은 상태 병합일 때만 있는 키). 상태가 다르거나 한쪽에 신호가 있으면 409 `candidate_merge_state_conflict`이고 details는 `{opportunities: [{id, tracking_status, tracking_selected_by, tracking_selected_at, recheck_signal, recheck_signal_at}]}`다(`recheck_signal_at`은 2026-09-22 추가, 추가형). 화면은 이 응답을 받아 각 사업을 `미선택`으로 되돌리는 단추를 주며(같은 `PATCH …/tracking-status`, 사유·담당자 필수) 되돌린 뒤 수락을 자동 재시도하지 않는다. 자동 병합(공식 키 재적재)이 같은 조건으로 막히면 경고 `opportunity_merge_confirmation_required`와 함께 `병합 확인` 후보(`search_strategy=merge_confirmation`)를 만들며, 도착 레코드는 고아로 남지 않고 자기 사업기회(없으면 새로 생성)에 붙는다.

#### 레코드 활동 피드·노트 (RL-02, 2026-10-17)

사업기회 레코드 화면(`/opportunities/:id/activity`)의 입력이다. 기능 명세는 `docs/work/groups/RL/features/RL-02-opportunity-timeline/spec.md`, 업무 규칙은 [business-rules.md "사업기회 레코드 단계 바·활동 피드"](../business-rules.md#사업기회-레코드-단계-바활동-피드-rl-02-2026-10-17)다. 오류 code `note_not_action`(409)은 라우터 로컬 map(`routers/opportunities.py`)과 프런트 `src/lib/apiErrors.ts`에만 등록했고, 노트를 못 찾는 경우는 새 code 없이 기존 core `not_found`(404)를 쓴다(core `api_errors`·lifecycle `API_ERROR_CODES` 불변).

**`OpportunityActivityResponse`** — 키는 전부 일곱이다: `{schema_version:"bidops.opportunity-activity.v1", opportunity_id:int, merged_into_opportunity_id:int|null, title:string, stages:OpportunityStageView[6], items:ActivityItem[], next_before:string|null}`.

- `title` = 권위 연결(`official`·`확정` 또는 `candidate`·`사람 확인 완료`·`accepted`) 중 **가장 뒤 단계**(입찰공고 > 사전규격 > 발주계획)의 제목, 없거나 비면 `#<id>`. 한 단계에 권위 연결이 여럿이면 연결 시각이 가장 늦은 것(같으면 연결 id가 큰 것)이 대표다.
- `stages` = `{key, state, at:ts|null}` 6개이며 **순서 고정**이다: `order_plan`, `pre_spec`, `bid_notice`, `deadline`, `opening`, `contract`. `state` enum은 `done|current|upcoming_deadline|pending|unknown`이고 판정 규칙은 business-rules가 정본이다. `raw_source`(파일 경로 문자열)는 읽지 않는다.
- `stages[].link_id:int|null`(추가형, 키는 언제나 있다) = 그 단계를 대표하는 권위 연결 id(`opportunity_stages.representatives`: 연결 시각이 가장 늦은 것, 같으면 id가 큰 것). `order_plan`·`pre_spec`·`bid_notice`는 그 단계 대표, `deadline`·`opening`은 입찰공고 대표의 id(입찰공고가 없으면 `null`), `contract`는 언제나 `null`이다. 화면은 대표 연결을 스스로 고르지 않고 이 id로 `GET /api/opportunities/{id}`의 `links`에서 찾으며, 활동 응답 전이거나 `null`이면 그 연결에서 오는 값을 비워 둔다.
- `items` = `ActivityItem[]`, `at` 내림·동률 `item_id` 내림. `next_before`는 다음 페이지가 있을 때만 값이 있다.
- `before` 커서는 opaque이며 `"<at ISO(UTC, Z)>|<item_id>"`다. 그 키보다 **엄격히 뒤**인 항목만 돌려주므로 같은 시각 묶음 한가운데에서 끊겨도 빠지거나 겹치지 않는다. 시간대 없는 `at`·`|` 앞뒤가 읽히지 않는 값·`item_id`가 `"<kind>:<pk>"` 모양이 아닌 값은 422 `invalid_request`다.
- `kinds`는 csv이고 비어 있으면 필터가 없으며 모르는 kind가 하나라도 있으면 422다. 필터와 커서와 `limit`은 lifecycle 항목과 확장점 항목을 합친 뒤 한 번에 적용한다.

**`ActivityItem`** — 키는 전부 여덟이다: `{item_id:string, kind, at:ts, actor:string|null, title:string, detail:string|null, link:{label, path}|null, status_pill:string|null}`. `item_id` = `"<kind>:<원본 PK>"`(결정적, 저장하지 않음, `|` 없음). 피드는 저장하지 않고 요청마다 원본에서 파생한다. 시스템 처리(수집 회차·변환·모델 호출·정책)는 어떤 kind에도 없다. `kind` 13값과 규칙:

| kind | 원본 | `title` | `link` |
|---|---|---|---|
| `order_plan_found` | 권위 연결 `stage=order_plan`의 `created_at` | "발주계획 발견 · <기관>"(기관 없으면 "발주계획 발견") | `/order-plans/<pk>` |
| `pre_spec_opened` | 권위 연결 사전규격의 `created_at` | "사전규격 공개" | `/pre-specs/<notice_pk>` |
| `bid_posted` | 권위 연결 입찰공고의 `created_at` | "입찰공고 게시" | 공고 외부 URL(`Notice.url`, http(s)만, 새 창). 내부 입찰공고 상세 route는 없다 |
| `notice_corrected` | 권위 연결 공고(사전규격·입찰공고)의 `NoticeObservation` 중 **첫 관측을 뺀** 것에서 `changed_fields_json ∩ {deadline_at,title,budget,estimated_price,method} ≠ ∅` | "정정 · <바뀐 필드 한글>"(마감·제목·예산·추정가격·계약방법 순) | 사전규격 `/pre-specs/<pk>#ps-record-history`, 입찰공고 외부 URL |
| `tracking_decided` | 감사 `opportunity.tracking_status.changed`(`Opportunity.tracking_status` 경로만; 데모 회사별 이벤트 아님) | "<이름>이 <상태>로 결정", 새 상태가 `미선택`이면 "<이름>이 추적 되돌림"(`detail`=사유) | 없음 |
| `recheck_signal` | 감사 `opportunity.recheck_signal.created`·`.acknowledged` | "재확인 신호" / "<이름>이 신호 확인" | 없음 |
| `link_reviewed` | `OpportunityLink.human_decision`이 있는 후보 연결 | "<이름>이 연결 후보 수락\|거절" | 없음 |
| `briefing_reacted` | `briefing_reaction_event` 중 `new ≠ 대기` | "<이름>이 <반응>", `status_pill`=반응 | `/briefing?date=<briefing_date>&selected=<briefing_item_id>` |
| `note_added` | `opportunity_note kind=note` | 본문 첫 줄(≤120자) | 없음 |
| `action_added` | `opportunity_note kind=action`의 `created_at` | "다음 행동: <본문>", **`detail`="담당 <owner>"** | 없음 |
| `action_done` | 같은 행동의 `done_at` | "<이름>이 완료: <본문>" | 없음 |
| `verdict_completed` | 확장점 `opportunity_activity_items`(RL-03) | 제공자 몫 | verdict 탭 |
| `draft_prepared` | 같은 확장점(RL-04) | 제공자 몫 | proposal 탭 |

이름 뒤 조사는 받침에 따라 이/가·으로/로를 고르고 한글 음절이 아닌 끝 글자는 `이`·`로`를 쓴다. 다음 행동 담당은 새 응답 키 없이 `action_added.detail`이 싣는다(run 결정 기록 #14). `verdict_completed`·`draft_prepared`는 제공자가 없으면 항목이 0건이다.

**노트 REST.** `NoteView` = `{note_id:UUID, kind, body, actor, owner, created_at, done_at:ts|null, done_by:string|null}`(키 전부). `owner`는 `kind=action`의 담당 이름이며 비우면 서버가 actor로 채운다(NOT NULL, `kind=note`도 같다). 작성자(`actor`)·완료자(`done_by`)는 요청 헤더 `X-BidOps-Actor-Name`(+`-Format`)에서만 받고 body에 없다. `body`는 앞뒤 공백을 지운 뒤 1..2000자이며 줄바꿈·탭 외 제어 문자와 `owner`의 `system`(대소문자 무시)은 거부한다.

- **멱등**은 core `IdempotencyRecord` fence(`app/core/idempotency_fence.py`)로 한다: `operation="opportunity_note.create"|"opportunity_note.done"`, `aggregate_type="opportunity"`, `aggregate_id=<사업기회 id>`, `claimed_name=actor`, `request_id=body.request_id`. 같은 범위·같은 요청 해시는 저장된 snapshot JSON을 **그대로** 재생하고(POST도 200) 다른 해시는 409 `idempotency_conflict`다. 노트 테이블에는 `request_id` UNIQUE가 없다 — 다른 actor의 같은 `request_id`는 별개의 노트다. 요청 해시 = canonical JSON `{operation, opportunity_id, kind, body(trim), owner(해소 후), actor}`(완료는 `{operation, opportunity_id, note_id, actor}`)의 SHA-256이다.
- 생성 검사 순서: 입력(422·400) → 사업기회 404 → 병합 409 → 영수증 재생·충돌 → 저장. 완료 검사 순서: 입력 → 사업기회 404 → 병합 409 → 노트 404(`not_found`) → `kind=note`면 409 `note_not_action` → 영수증 재생·충돌 → 이미 완료면 현재 값 200 → 완료 저장. 완료는 한 번만 일어나며 다른 사람의 두 번째 완료도 첫 완료를 바꾸지 않는다.
- 쓰기는 사업기회 행을 잠가 같은 사업기회의 노트 쓰기를 직렬화한다. 병합된 사업기회에는 쓰지 않는다(GET만 200).
- **노트 본문은 어떤 모델 입력에도 넣지 않는다**(RL-03·04가 이 규칙을 상속한다). 이 REST는 외부 호출이 없다.

**DB: `opportunity_note`** (migration `0039_opportunity_note`, 이전 head `0038_briefing`). lifecycle 소유(`tests/app/boundary_map.py TABLE_OWNER`).

| 열 | 형 | 비고 |
|---|---|---|
| `id` | UUID PK | |
| `opportunity_id` | INT FK `opportunity.id` `RESTRICT` | 인덱스 `ix_opportunity_note_opportunity (opportunity_id, created_at)` |
| `kind` | VARCHAR(16) | CHECK `kind IN ('note','action')` |
| `body` | TEXT | 길이 1..2000은 API가 보장 |
| `actor`, `owner` | TEXT NOT NULL | |
| `created_at` | timestamptz | 기본 `CURRENT_TIMESTAMP` |
| `done_at`, `done_by` | timestamptz·TEXT NULL | CHECK `(done_at IS NULL) = (done_by IS NULL)` |

- **append-only.** 본문·종류·작성자·담당·생성 시각은 바뀌지 않고 `done_at`·`done_by`만 NULL에서 한 번 채울 수 있다. ORM `before_update`·`before_delete`가 거부하고 DB 권한도 같은 모양이다(`scripts/runtime-privileges.sql`, 열 단위 GRANT 선례): web(`app`)은 `SELECT`·`INSERT`와 **`UPDATE (done_at, done_by)`만**, `worker`는 `SELECT`만, `ro_backup`은 `SELECT`, **어느 역할에도 DELETE가 없다** — 본문 UPDATE는 DB가 거부한다.
- migration downgrade는 노트가 하나라도 있으면 거부한다. models와 migration은 같은 CHECK·인덱스 선언을 쓴다.
- 새 테이블 검사: `tests/app/test_db_migrations.py`, 권한 `tests/app/test_runtime_database_privileges.py`, 본문 UPDATE 거부는 PostgreSQL 전용 `tests/app/test_opportunity_notes_api_postgres.py`.

**확장점 `opportunity_activity_items`.** `lifecycle/extensions.py`가 `OpportunityActivityItemsProvider.opportunity_activity_items(session, opportunity_id) -> Sequence[ActivityItem]`을 선언하는 **hook 방식**이다 — owner별로 `register_opportunity_activity_items(provider, owner=…)`로 등록하고(같은 owner는 제자리 교체) 여러 제공자를 허용하며, registry가 등록 순서대로 항목을 이어 붙인 뒤 정렬·커서·`kinds` 필터는 피드가 lifecycle 항목과 함께 공통으로 한다. 제공자는 읽기 전용이며 사업기회 하나의 사건을 상수 회 조회로 읽고 `item_id`를 `"<kind>:<pk>"`로 결정적으로 만든다. `ActivityItem`·응답 모델은 `lifecycle/schemas/opportunity_activity.py`에 있고 `app.lifecycle` 공개 표면(`tests/app/boundary_map.py` allowlist)으로 제공자가 import한다. `ActivityItem`이 아닌 값을 돌려주면 조립 오류(`TypeError`)이고, 제공자의 예외는 GET을 500으로 만든다(읽기 오류를 빈 목록으로 접지 않는다). 등록된 제공자는 deep_review의 RL-03(`verdict_completed`)·RL-04(`draft_prepared`) 둘이며 owner 키가 서로 달라 한쪽 등록이 다른 쪽을 교체하지 않는다.

### 사업기회 구역·사유·보류 기한

구역(`section`, 첫 일치)과 사유(`action_reasons[]`, 모든 행에 계산)는 서로 다른 축이며 같은 SQL 한 식으로 계산해 목록·집계·`GET /api/workload`가 항상 같은 모집단을 쓴다.

| 구역 | 조건 |
|---|---|
| `조치 필요` | (`계속 추적`\|`보류` AND 사유 1개 이상) OR (`종료` AND `new_link`\|`candidate_pending`\|`merge_confirmation` 중 하나) |
| `추적 중` | `계속 추적`이고 위 조건에 해당하지 않음 |
| `보류` | `보류`이고 위 조건에 해당하지 않음 |
| `추적 종료` | `종료`이고 위 조건에 해당하지 않음 |
| `신규 입찰공고` | `미선택` AND `first_registered_stage=bid_notice` |
| (`미결정`, 집계 전용) | 그 밖의 `미선택`; 목록 `section` 필터 값으로는 받지 않음(422) |

| 사유 코드 | 조건 |
|---|---|
| `new_link` | `recheck_signal_at IS NOT NULL` |
| `candidate_pending` | 소유 사업기회에 `candidate`·`후보 확인 대기`·`search_strategy ≠ merge_confirmation` link 존재 |
| `merge_confirmation` | 소유 사업기회에 `candidate`·`후보 확인 대기`·`search_strategy = merge_confirmation` link 존재 |
| `blocking_item` | 연결 공고의 미답변 차단 항목 1개 이상 (기존 projection) |
| `hold_overdue` | `tracking_status=보류` AND `tracking_selected_at + 14일 ≤ now` |

보류 재검토 기한은 lifecycle 상수 `HOLD_REVIEW_PERIOD_DAYS=14`로 고정한다. `hold_review_due_at = tracking_selected_at + 14일`은 `보류`일 때만 값이 있고 저장하지 않는 파생값이다. 기준 시각은 요청마다 Python에서 timezone-aware UTC로 한 번 계산해 SQL 파라미터로 넘기므로 SQLite·PostgreSQL이 마이크로초까지 일치한다. `보류`를 다시 저장하면 `tracking_selected_at`이 갱신되어 기한이 새로 시작한다. `GET /api/opportunities`의 `hold_review=due_soon`은 `now < 기한 ≤ now+3일`, `attention`은 `overdue`와 `due_soon`의 합집합이다.

마감 임박 창(`deadline_within_days`, 2026-09-22 추가, [ADR-0067](../tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md))은 `hold_review`와 같은 모양의 **복합** 인자다. 정수 1..365를 받고 `권위 있는 연결`(`official`·`확정` 또는 `candidate`·`사람 확인 완료`·`accepted`)의 공고 마감이 `[요청 시각, 요청 시각 KST 일자 + N일의 끝)`에 드는 **추적 대상**(`계속 추적`·`보류`) 사업기회만 남긴다. `hold_review=overdue`가 "보류 상태 + 기한 지남"을 한 인자로 묶은 것과 같은 선례이며 `tracking_status`를 다중 값으로 넓히지 않는다. 창은 **링크 단위**로 판정하고 돌려주는 것은 **사업기회**다 — 응답에 "이 사업의 마감"이라는 대표 필드를 만들지 않으므로 소비자가 `links[]`의 `deadline_at`·`source_type`으로 어느 마감이 임박했는지 고른다. 확인 대기 후보 연결의 마감과 `deadline_at`이 `null`인 연결은 사업기회를 창에 넣지 않으며, 이미 지난 마감도 임박이 아니다. 범위를 벗어난 값은 422다. `sort=deadline`(같은 날 추가)은 **정렬 키일 뿐** 창이 아니다 — 아직 남은 권위 연결 마감 중 가장 이른 것 오름차순이고, 그런 마감이 없는 사업기회는 방언과 무관하게 맨 뒤에 둔 다음 `created_at` 내림·`id` 내림으로 동률을 푼다.

#### 발주계획 일괄 추적 v1 wire·원자성

두 POST는 RuntimeContractModel의 v1 field만 받는다. 계획 ID는 서버에서 중복 제거하고
오름차순으로 정규화하므로 preview와 receipt의 `items` 순서도 그 순서다. preview는 계획
존재·authoritative active owner(공식 확정 또는 사람 accepted 후보)·현재 상태만 set 조회하며
추적·감사·receipt·모델 실행을 만들지 않는다. 미리보기 뒤 상태가 바뀔 수 있으므로 bulk-start가
잠금 뒤 다시 확인한 결과가 최종이다.
bulk-start body에는 임의 status나 owner ID가 없고 목표 상태는 고정 `계속 추적`이다.

bulk-end([ADR-0063](../tracking/decisions/0063-order-plan-bulk-tracking-end.md))는 bulk-start와 같은 상태 기계를 목표 상태만 바꿔 쓴다.
body에 status가 없고 목표는 고정 `종료`다. 요청은 `order-plan-bulk-end-request.v1`, receipt는 정확히
`{schema_version:"order-plan-bulk-end-response.v1", request_id, completed_at, items, summary}`이며 item·summary의 field와
실패 code 목록은 bulk-start와 같다. 성공 item은 `status_at_decision=종료`·audit UUID, 제외 item은 기존
`계속 추적|보류|종료` 상태다. `preview`는 두 작업이 공유한다(`eligible`=현재 `미선택`). `order_plan_ids`는 bulk-end에서만
200건 상한이 있고 초과는 FastAPI 기본 422(`type=too_long`, 보낸 배열을 `input`으로 되돌림)다 — bulk-start v1에는 상한이 없다.
receipt의 operation은 `order_plan_tracking_bulk_end`이고 결정적 receipt UUID와 canonical hash에 operation이 들어가므로,
같은 `request_id`를 start와 end에 보내도 서로 replay·conflict를 일으키지 않는다. 로그 이벤트는
`order_plan.bulk_tracking_end.{succeeded,replayed,conflict}`다. 아래 원자성·잠금·hook 규칙은 두 작업에 똑같이 적용한다.

preview 응답은 정확히 `schema_version`, `selected_plan_count`, `unique_owner_count`,
`eligible_plan_count`, `eligible_owner_count`, `excluded_by_status`, `failure_plan_count`,
`items`를 갖는다. `excluded_by_status`는 `계속 추적|보류|종료` 각각
`{plan_count, owner_count}`이고 item은 정확히
`{order_plan_id, opportunity_id, tracking_status, eligibility, code}`다. eligibility는
`eligible|excluded|failed`이며 `eligible`은 현재 `미선택`, `excluded`는 현재 세 상태,
`failed`는 `order_plan_not_found|owning_opportunity_missing|owner_changed|ownership_conflict|processing_failed|temporarily_unavailable`
중 안전 code를 갖는다. owner가 없거나 후보 확인 대기만 있는 계획을 새 사업기회로 만들지 않는다.
eligible/excluded item은 `opportunity_id`가 non-null이고 각각
`tracking_status=미선택` 또는 기존 제외 상태이며 `code=null`이다. failed item은 `code`가
non-null이고 owner/status는 확인 가능한 경우에만 채운다. `unique_owner_count`와
`eligible_owner_count`는 각 item의 non-null owner를 중복 제거한 수다.

bulk-start의 최종 receipt는 정확히
`{schema_version:"order-plan-bulk-start-response.v1", request_id, completed_at, items, summary}`다.
`request_id`와 non-null `audit_event_id`는 UUID 문자열이며 `completed_at`은 timezone-aware
ISO timestamp다.
item은 `{order_plan_id, opportunity_id, outcome, status_at_decision, code, audit_event_id}`이고
summary는
`selected_plan_count`, `unique_owner_count`, `succeeded_plan_count`,
`succeeded_owner_count`, `excluded_plan_count`, `excluded_by_status`,
`failed_plan_count`를 갖는다.
`selected_plan_count`는 세 outcome 합과 같고, 같은 owner로
연결된 plan은 하나의 outcome/status/code/audit ID를 fan-out한다. 성공은
`status_at_decision=계속 추적`·audit UUID, 제외는 기존 상태와 audit 없음, 실패는 안전 code와
audit 없음이다. 전건 실패도 항목별 결과가 있으면 200 receipt이며 전건 성공을 뜻하지 않는다.
`unique_owner_count`는 전체 item의 non-null owner 수이고 `succeeded_owner_count`는 성공
owner의 중복 제거 수다. summary의 상태별 제외 plan/owner 수는 제외 item과 일치해야 하며
성공 item은 owner/status/audit가 non-null, 제외 item은 owner/status만 non-null, 실패 item은
안전 code만 필수이고 audit는 null이다.

bulk는 owner ID 오름차순 잠금·savepoint로 처리하고, **현재 `미선택`인 owner만** `계속 추적`으로
전환한다. 이미 `계속 추적|보류|종료`인 owner는 제외하며 actor·reason·시각·recheck·기존
감사를 건드리지 않는다. 성공 결정·감사와 최종 JSON receipt는 한 transaction으로 commit한다.
기존 `IdempotencyRecord`의 결정적 UUIDv5 요청 fence와 `request_sha256`을 사용하며 새 table,
정규화한 schema/operation/request UUID/plan ID 집합/reason/actor를 hash에 포함한다. 새 table,
batch job, outbox를 만들지 않는다. post-commit extension hook은 owner별 best-effort이고
hook 전달의 exactly-once를 보장하지 않는다.
동시에 실행된 단건 PATCH가 먼저 commit되면 bulk는 잠금 뒤 그 최신 비-미선택 상태를 제외하고
감사를 만들지 않는다. bulk가 먼저 commit되면 대기 중인 단건 PATCH가 기존 규칙대로 뒤이어
다른 상태 또는 같은 상태 재선택을 기록할 수 있으며 bulk receipt는 바뀌지 않는다. 단건에
새 expected-version/freshness 조건을 추가하지 않는다.

receipt JSON은 strict response DTO 검증 뒤 `model_dump(mode="json")`한 JSON primitive만
저장한다. commit 후 응답이 유실되면 같은 request UUID와 동일 payload/actor로 저장된 status/body를
재검증만 하고 그대로 replay한다. 현재 상태를 다시 판정하거나 시각·UUID·집계·배열 순서를
재계산하지 않는다. 같은 key의 다른 actor·reason·ID 집합은 409다. commit 미확인은 결과를
성공으로 추정하지 않고 같은 key로 확인한다. 완결 receipt의 실패 항목은 자동 재실행하지
않으며, 사람이 결과를 확인한 뒤 실패 plan ID만 새 request UUID로 다시 제출한다(기존 receipt 보존).
구조 검증을 통과하지 못한 JSON body는 공통 규칙대로 FastAPI `detail[]` 422이고, semantic
bulk 오류만 위의 안전 envelope와 code를 사용한다.

#### 목록 선택과 사전규격 상세 순회

발주계획·사전규격 목록은 활성 행과 체크 묶음을 분리한다. 행 클릭·Enter·↑↓는 active만
옮기고(체크 묶음이 없는 사업 추적·최종 Go/No-Go 목록도 같은 ↑↓·클릭 규칙을 쓰며 경계에서
페이지를 넘긴다), native checkbox 또는 활성 행의 plain Space만 checked membership을 한 번 토글한다.
선택은 각 화면의 별도 `sessionStorage` key에서 같은 탭의 page 이동·refresh·상세 왕복 동안
유지하며 탭·계정 간 동기화나 장기 저장은 하지 않는다. 적용된 의미 필터가 달라지면 세대를
올려 선택을 비우고, offset·정렬 변경·refetch는 선택을 유지한다. 정렬 변경 뒤 사전규격
상세에 다시 들어갈 때만 새 순서를 만든다.

발주계획 선택 순서는 기존 relevance 우선순위와 PK 오름차순 동률 규칙을 따른다. 사전규격은
목록이 마지막으로 관측한 `published_at`(내림차순, null 마지막, PK 내림차순) 또는
`deadline_at`(오름차순, null 마지막, PK 오름차순)을 사용한다. timezone offset과 최대
microsecond를 보존해 비교하며, 서버 전체의 새 snapshot을 보장하지 않는다. 선택 검토에
들어가면 이 순서를 opaque `selection_review` token으로 고정하고 위치·전체 건수·양끝
disabled 이전/다음 버튼을 제공한다.

상세의 navigation shell은 본문 성공 여부와 분리되어 loading·404·5xx·source/projection
오류에서도 위치와 목록 복귀를 제공한다. 오류 항목을 자동으로 건너뛰거나 선택에서 지우지
않으며 retry는 같은 항목에 머문다. 목록 복귀 URL은 filter·sort·offset만 보존하고 상세
전용 token은 제거한다. `sessionStorage`를 읽거나 쓸 수 없으면 복원 가능한 bulk/선택 검토
시작을 제공하지 않고 원인과 단건 경로를 안내한다. 기존 단건 상세와 단건 PATCH는 계속
사용한다.

### 결정 대기 집계와 큐 응답

[ADR-0053](../tracking/decisions/0053-decision-workload-read-contracts.md)의 읽기 전용 계약이며 2026-09-22에 실무자 대시보드 패널 계약([ADR-0067](../tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md))이 키 다섯(세는 키 넷과 그중 둘의 합계 하나)을 더했고, 2026-10-16 RL-00이 키 `company_attention` 하나를 끝에 더했고, 2026-10-17 RL-01이 키 `briefing_pending` 하나를 그 뒤에 더했다. 모든 경로가 DB 열을 새로 만들지 않고 기존 목록과 **같은 모집단**을 센다.

- `WorkloadResponse`: `generated_at`(UTC aware)과 `items[]`. item은 `key`, nullable `count`(0 이상), nullable `unavailable_reason` 셋뿐이다. `items`의 순서는 고정이며 `order_plan_pending`, `pre_spec_deep_review_ready`, `tracking_action_required`, `tracking_hold_review_due`, `bid_final_decision_pending`, `tracking_deadline_imminent`, `human_check_required`, `overview_human_review`, `blocking_items_open`, `order_plan_new_priority`, `company_attention`, `briefing_pending` **열**이 언제나 모두 있다(ADR-0053 §1·§4 갱신, ADR-0067 결정 1, spec §7.1·§8). 앞 다섯의 뜻과 소유자는 바뀌지 않았다.
- **제공자 부재와 실제 0은 다르다.** 소유 모듈이 등록되지 않았으면 `count=null`·`unavailable_reason="provider_absent"`이고, screening이 있어도 누적 범위([C-2 발주계획 목록 누적 모드](c2.md#발주계획-목록-누적-모드))에 완료된 C-2 운영 실행이 하나도 없으면 `count=null`·`unavailable_reason="no_completed_execution"`이다. 오늘 실행이 없다는 이유로 `null`이 되지 않는다. 셀 수 있었다면 정수와 `unavailable_reason=null`이다. `null`을 0으로, 0을 `null`로 접지 않는다.
- 각 건수의 소유자는 모듈이다. `order_plan_pending`은 screening이 `GET /api/order-plans`의 누적 모드(`source_run_id` 없음) 범위와 같은 필터(`stage1_status=selected`, `qwen_relevance=relevant,uncertain`, `tracking_status=미선택`)로, `pre_spec_deep_review_ready`는 deep_review가 `GET /api/pre-specs?workspace=actionable&auto_preparation_status=deep_review_ready_for_click&sw_only=false`와 같은 집합으로(2026-09-22 개정 — 이 필터를 건 `actionable`은 "심층 검토 클릭 대기 ∧ 추적 상태 null·`미선택`"으로 줄어든다. 사람이 추적 결정을 내린 건은 이유 불문 빠진다. 검토 제외는 종전대로 업무 집계를 바꾸지 않으므로 제외된 채 결정 대기인 건만 두 값이 갈린다), `bid_final_decision_pending`은 deep_review가 `GET /api/bid-delta/decision-queue?status=pending`의 `total`과 같은 값으로 센다. `tracking_action_required`와 `tracking_hold_review_due`는 lifecycle이 각각 `GET /api/opportunities`의 `조치 필요` 구역, `hold_review=overdue` 건수와 같은 첫 일치 규칙으로 직접 센다.
- **2026-09-22에 더한 네 키도 짝지은 목록 호출의 `total`과 같은 값이다.** 소비자는 건수를 목록 페이지에서 다시 세지 않는다.

  | 키 | 소유 | 같은 값을 내는 목록 호출 |
  |---|---|---|
  | `tracking_deadline_imminent` | lifecycle 직접 | `GET /api/opportunities?deadline_within_days=7` |
  | `overview_human_review` | deep_review 제공자 | `GET /api/pre-specs?overview_view=failed&sw_only=false`와 `overview_view=attention`(나머지 인자는 기본값) 두 `total`의 합 |
  | `blocking_items_open` | lifecycle 직접 | `GET /api/opportunities?reason=blocking_item` |
  | `order_plan_new_priority` | screening 제공자 | `GET /api/order-plans?qwen_relevance=relevant&tracking_status=미선택&first_observed_from=<요청 시각 KST 일자 −1일>` |

- **`company_attention`(2026-10-16, RL-00)은 사이드바 "회사 근거" pill의 건수다.** 값은 실회사 활성 그래프(활성 binding의 graph version snapshot)에서 `status`가 `proposed` 또는 `unknown`인 **비evidence 노드 수**이며 deep_review 제공자가 센다(어휘는 lifecycle `WorkloadKey`·`_WORKLOAD_KEYS`가 소유). 셀 수 없으면 `count=null`이고 사유는 다음 셋이다 — `provider_absent`(등록된 실회사 없음, 제공자 모듈 부재도 같은 값), `company_profile_not_ready`(실회사는 있으나 활성 binding 없음), `processing_failed`(실회사가 둘 이상이거나 snapshot을 읽을 수 없음). 못 센 값을 0으로 접지 않는다. **ADR-0067 "건수 키 = 목록 호출 total" 짝 규칙의 예외다:** 짝 목록 REST가 없고 `/company` 화면이 `GET /api/companies/{id}/profile`의 facts를 직접 센다. 두 값은 요청이 달라 어긋날 수 있으며 서로를 고치지 않는다.
- **`briefing_pending`(2026-10-17, RL-01)은 사이드바 "오늘의 브리핑" 건수다.** 값은 가장 최근 `briefing_date`의 브리핑에서 `kind=recommendation`이고 `reaction=대기`인 항목 수이며 lifecycle이 직접 센다(추적 변화 행은 반응이 없어 세지 않는다). 브리핑이 하나도 없으면 `count=null`·`unavailable_reason="provider_absent"`다 — 0으로 접지 않는다. 짝 목록 호출은 `GET /api/briefings/latest`의 `items[]` 중 `reaction=대기`이며 소비자는 건수를 다시 세지 않는다.
- **`human_check_required`는 측정값이 아니라 두 하위 건수(`overview_human_review` + `blocking_items_open`)의 합이다.** 세는 단위가 서로 다르므로(개요는 **사전규격 공고**, 확인 항목은 **사업기회**) 소비자는 합계만 보여 주지 않고 두 하위 건수를 함께 적는다. **하나라도 `null`이면 합계도 `null`**이고 이때 `unavailable_reason="sub_count_unavailable"`이다 — 제공자 부재를 0으로 접어 "확인할 일 없음"으로 말하지 않는다(ADR-0067 결정 5).
- `tracking_deadline_imminent`의 창은 고정 7일이고 기준 시각은 `generated_at`이다. `order_plan_new_priority`의 "새로"는 관측 행의 최소 시각(`first_observed_at`)이 요청 시각 KST 일자의 **전일** 00:00 이상인 건이며 상한은 없다 — 일일 수집이 아침에 돌므로 당일 도착분도 "새로"에 든다. 건수와 목록은 서로 다른 요청이라 몇 초 차이가 날 수 있으므로, 소비자는 건수를 목록 길이로 덮거나 목록이 비었다고 건수를 0으로 고치지 않는다(ADR-0067 결정 7). `order_plan_new_priority`는 `relevant` 하나로 좁히고 `order_plan_pending`은 `relevant,uncertain`이므로 두 값은 서로 다르며 대신하지 않는다.
- 심층 검토 목록 item은 `deep_review_id`, `notice_id`, nullable `notice_title`, `status`, nullable `quality_status`, `created_at`, nullable `current_attempt_status`, nullable `latest_final_opinion={value, decided_at}`다. 사업기회에 연결된 공고를 중복 제거해 읽으며 후보 링크도 포함한다 — 이 목록은 안전한 색인이지 소유권 확정이 아니다. 생성 시각 내림차순이고, 사업기회가 있고 실행이 없으면 200 빈 목록, 사업기회가 없으면 404다. `quality_status`의 `null`·참조·mock 의미를 승격하지 않는다.
- 최종 결정 큐 item은 `opportunity_id`, nullable `title`, nullable `agency`, `tracking_status`, `first_registered_stage`, `recheck_signal`, nullable `bid_notice_external_id`, 정수 `comparison_count`, nullable `latest_final_decision={decision, decided_at, claimed_name}`, `decision_currentness=current|stale|unknown`이다. `pending`은 active·`계속 추적`·권위 있는 입찰공고 연결이면서 최종 결정이 없거나 그 결정이 `stale`인 건이다. 미결정 `unknown`은 포함하고 기결정 `unknown`은 제외한다. `all`은 입찰공고 미연결 건도 포함한다. 전체를 판정한 뒤 페이지를 자르며 미결정 우선·최근 등록순으로 정렬한다.
- `GET /api/pre-specs`의 `auto_preparation_status`는 응답 필드와 같은 어휘의 optional 필터다. 기존 조건에 AND하며 `total`·`overview_status_counts`·페이지가 **같은 집합**을 읽는다. 제공자(deep_review)가 없으면 빈 집합이고, 그 빈 집합을 "제한하지 않음"으로 바꾸지 않는다. 인자를 주지 않으면 필터가 없다.
- `decision_currentness`는 입찰 delta workspace(`GET /api/opportunities/{opportunity_id}/bid-delta`)와 **같은 규칙을 같은 구현**으로 평가한다. 단건과 batch가 서로 다른 답을 내지 않는다.

### 리뷰, 첨부, 포털, 프로필

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/reviews` | required query `run_id` | `ReviewResponse[]` | 404 run, 422 run ID 부재 |
| `GET /api/reviews/export` | required query `run_id` | `bidops.feedback.v2` YAML | 404 run, 422 run ID 부재 |
| `PUT /api/notices/{notice_pk}/review` | run ID, reviewer, disposition, grade/readiness feedback, verification answers | DB 정본 리뷰 | 404 공고·회차, 422 |
| `GET /api/notices/{notice_pk}/attachments` | path DB integer notice PK | `AttachmentProcedureResponse` | 404 |
| `POST /api/notices/{notice_pk}/attachments` | path DB integer notice PK; actor headers; multipart optional `files[]` and optional `file`, 합쳐 1개 이상 | legacy `AttachmentProcedureResponse`; quarantine·MIME/구조·ClamAV 검사와 source object 승격 후 `safe` 파일만 legacy `Attachment`와 로컬 호환 사본으로 등록 | 400 actor·형식·크기·빈 upload·안전검사 실패, 404 공고, 503 object storage |
| `DELETE /api/attachments/{attachment_id}` | attachment ID; actor headers | 204; append-only `AuditEvent` | 400 actor, 403 나라장터 제공 첨부, 404 |
| `GET /api/attachments/queue` | required query `run_id` | `AttachmentQueueResponse` | 404 run, 422 run ID 부재 |
| `GET /api/attachments/{attachment_id}/download` | attachment ID | legacy 로컬 파일 stream | 404 |
| `GET /api/portals` | 없음 | `AgencyPortalResponse[]` | 없음 |
| `POST /api/portals` | actor headers; `AgencyPortalCreateRequest` | 201 `AgencyPortalResponse`; append-only `AuditEvent` | 400 actor, 422 빈 필수 field |
| `PATCH /api/portals/{portal_id}` | actor headers; `AgencyPortalUpdateRequest` partial body | `AgencyPortalResponse`; append-only `AuditEvent` | 400 actor, 404 portal, 422 빈 field |
| `GET /api/profile/snapshots` | 없음 | `CompanyProfileSnapshotListResponse`; working-tree `source_ref` 생략, Git blob은 SHA만 유지 | 없음 |
| `GET /api/profile/sections` | 없음 | `ProfileSectionsProjectionResponse`; 승인 snapshot binding·구조화 항목·위치 요약·안정 `error_codes` | snapshot 없음 `503 profile_snapshot_unavailable`; artifact 읽기 실패는 binding과 함께 `200`·동일 code |
| `GET /api/profile/unknowns` | 없음 | `ProfileUnknownsProjectionResponse`; 승인 snapshot binding·unknown 항목·참조 집계·안정 `error_codes` | snapshot 없음 `503 profile_snapshot_unavailable`; artifact 읽기 실패는 binding과 함께 `200`·동일 code |
| `GET /api/metrics/validation` | required query `run_id` | `ValidationMetricsResponse` | 404 run, 422 run ID 부재 |

### 판정 실행, 정책, 품질, 일정

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `POST /api/runs/{run_id}/pipeline/judgment` | path run ID; `JudgmentExecutionCreateRequest` | 202 `ScreeningExecutionResponse` | 400 profile·input·준비, 404 run·policy, 422 body, 500 생성 후 재조회, 503 model preflight |
| `GET /api/screening/executions` | optional status, trigger, nonblank run ID, limit 1..200(default 50), offset | `{items,total,limit,offset}` | 422 query, 500 저장 binding 손상 |
| `GET /api/screening/executions/{execution_id}` | path execution ID | `ScreeningExecutionDetailResponse` | 404, 500 저장 binding 손상 |
| `POST /api/screening/executions/{execution_id}/stop` | path execution ID; `ScreeningStopRequest` | `ScreeningExecutionResponse` | 404, 409 terminal, 422 ID·actor, 500 binding 손상 |
| `GET /api/screening/executions/{execution_id}/artifacts/{kind}` | kind=`decisions|failures|telemetry|screening_result` | JSON 또는 NDJSON | 404, 422 |
| `POST /api/quality-gates` | `QualityGateCreateRequest` | 202 `QualityGateResponse` | 404 run·policy, 409 conflict, 422 body·고정 입력, 500 생성 후 재조회, 503 model preflight |
| `GET /api/quality-gates` | optional purpose, execution/result status, limit 1..200, offset | `{items,total,limit,offset}` | 409 stale refresh, 422 query, 500 binding 손상 |
| `GET /api/quality-gates/{gate_id}` | path gate ID | `QualityGateDetailResponse` | 404, 500 binding 손상 |
| `PUT /api/quality-gates/{gate_id}/reviews/{notice_id}` | path gate·notice ID; `QualityGateReviewUpsertRequest` | `QualityGateDetailResponse` | 404 gate·pass A notice, 409 review conflict, 422 body, 500 binding 손상 |
| `GET /api/policies` | optional `status=draft|activation_candidate|active` | `{items,total,active_policy_version}` | 422 query |
| `POST /api/policies` | actor headers; immutable `PolicyVersionCreateRequest` | 201 draft `PolicyVersionResponse`; append-only `AuditEvent`와 screening audit | 400 actor, 409 version, 422 schema |
| `GET /api/policies/{policy_version}` | path version | `PolicyVersionResponse` | 404 |
| `POST /api/policies/{policy_version}/candidate` | path version; actor headers; `PolicyCandidateRequest` | `PolicyVersionResponse`; append-only `AuditEvent`와 screening audit | 400 actor, 404, 409 status, 422 body |
| `POST /api/policies/{policy_version}/activate` | path version; actor headers; `PolicyActivationRequest` | `PolicyActivationResponse`; append-only `AuditEvent`와 screening audit | 400 actor, 404, 409 gate·binding, 422 body |
| `GET /api/schedule/settings` | 없음 | `ScheduleSettingsResponse` | 500 조회 불가 |
| `PATCH /api/schedule/settings` | daily/weekly time 또는 prespec flag 중 하나 이상, updated by | `ScheduleSettingsResponse` | 400 저장, 422 설정 |
| `POST /api/schedule/executions` | `ScheduleExecutionCreateRequest` | 202 `ScheduleExecutionSummary` | 409 예약·recovery, 422 body·window, 500 저장 binding 손상 |
| `GET /api/schedule/executions` | optional job kind, status, `from`, `to`, limit 1..200, offset | `{items,total,limit,offset}` | 422 filter·range, 500 저장 binding 손상 |
| `GET /api/schedule/always-on` | 없음 | `AlwaysOnSwitchResponse` | 500 조회 불가 |
| `PUT /api/schedule/always-on` | `AlwaysOnSwitchUpdateRequest` | `AlwaysOnSwitchResponse` | 409 환경·승인·binding, 422 body, 500 응답 binding 손상 |

판정 실행 응답은 queue number, execution ID, trigger, source run, scope, optional notice, status, actor, policy·prompt·model·profile·input digest binding, 시간, stop 정보, counts, 현재 stage, artifact URL을 반환한다. 실행 detail은 attempts와 failures를 추가한다. 측정하지 않은 token·duration은 0으로 만들지 않는다.

품질 gate는 `model_comparison`과 `operational_approval` 목적을 구분한다. 고정 표본과 baseline digest, 서로 다른 pass A/B 실행, policy·prompt·model·profile binding, append-only evaluation revision, 사람 리뷰를 보존한다. 최신 passing operational approval과 binding이 정확히 일치해야 정책과 always-on을 활성화할 수 있다.

### 문서 준비와 심층 검토

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/notices/{notice_id}/document-bundles` | integer notice ID | 200 `BundleListResponse` | 404 `not_found`; 422 path; 500 `processing_failed` |
| `POST /api/notices/{notice_id}/document-bundles` | actor header; strict 빈 JSON `{}` | 201 `BundleView` | 400 `actor_name_required|actor_name_invalid`; 403 `effective_grade_ineligible`; 404 `not_found`; 422 path·body; 500 `processing_failed` |
| `POST /api/document-bundles/{bundle_id}/documents` | actor header; multipart required `file`; form required UUID `request_id` | 202 `DocumentVersionView` | 400 `actor_name_required|actor_name_invalid|invalid_request|unsafe_document`; 404 `not_found`; 409 `idempotency_conflict`; 422 path·form; 500 `processing_failed`; 503 `service_unavailable` |
| `PATCH /api/document-versions/{document_version_id}` | actor header; `PatchDocumentVersionRequest` | 200 `DocumentVersionView` | 400 `actor_name_required|actor_name_invalid|invalid_request`; 404 `not_found`; 409 `version_conflict`; 422 path·body; 500 `processing_failed` |
| `POST /api/document-bundles/{bundle_id}/confirm` | actor header; `ConfirmRequest` | 200 `BundleView` | 400 `actor_name_required|actor_name_invalid|invalid_request`; 404 `not_found`; 409 `version_conflict|idempotency_conflict|bundle_has_blocking_issues|structure_unavailable`; 422 path·body; 500 `processing_failed` |
| `GET /api/document-structures/{structure_id}` | UUID structure ID | 200 `DocumentStructure` | 403 `unsafe_document`; 404 `not_found`; 422 path; 500 `processing_failed` |
| `GET /api/document-structures/{structure_id}/pages/{page}` | UUID structure ID; page는 1 이상 정수 문자열 | 200 `DocumentStructurePageView` | 403 `unsafe_document`; 404 `not_found`(비정수·1 미만·없는 page 포함); 422 structure UUID; 500 `processing_failed` |
| `GET /api/document-structures/{structure_id}/segments` | UUID structure ID | 200 `DocumentSegmentsView`(`bidops.document-segments.v1`). segment마다 `page_range`·`mapping_status`를 조회 시점에 계산해 붙인다 | 403 `unsafe_document`; 404 `not_found`(구조 없음 또는 manifest 없음); 422 path; 500 `processing_failed`(대응표 읽기·SHA-256·schema 실패) |
| `GET /api/document-structures/{structure_id}/pdf` | UUID structure ID | 200 `application/pdf`. 구조를 가리키면서 대응표를 가진 가장 최근 native snapshot(`created_at` desc, 동률이면 `id` desc)의 PDF 바이트. 헤더는 `Content-Disposition: inline; filename="document-reference.pdf"`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox` | 403 `unsafe_document`; 404 `not_found`(구조 없음 또는 대응표를 가진 snapshot 없음); 409 `pdf_integrity_failed`; 422 path; 503 `pdf_unavailable` |
| `POST /api/notices/{notice_id}/deep-reviews` | actor header; `DeepReviewCreateRequest`; active profile/policy는 서버가 고정 | 202 `DeepReviewView` | 400 `actor_name_required|actor_name_invalid|invalid_request`; 403 `effective_grade_ineligible`; 404 `not_found`; 409 `bundle_not_ready|idempotency_conflict|active_attempt_exists`; 422 path·body; 500 `processing_failed`; 503 `service_unavailable` |
| `GET /api/deep-reviews/{deep_review_id}` | UUID review ID | 200 `DeepReviewView` | 404 `not_found`; 422 path; 500 `processing_failed` |
| `POST /api/deep-reviews/{deep_review_id}/attempts` | actor header; `DeepReviewAttemptRequest` | 202 `AttemptView` | 400 `actor_name_required|actor_name_invalid|invalid_request`; 404 `not_found`; 409 `review_not_ready|active_attempt_exists|idempotency_conflict`; 422 path·body; 500 `processing_failed` |
| `GET /api/deep-reviews/{deep_review_id}/report` | UUID review ID | 200 `ReportView` | 404 `not_found`; 409 `review_not_ready`; 422 path; 500 `processing_failed` |
| `POST /api/deep-reviews/{deep_review_id}/report-revisions` | actor header; `ReportRevisionRequest` | 201 `ReportView` | 400 `actor_name_required|actor_name_invalid|factual_change_evidence_required`; 403 `evidence_out_of_scope|unsafe_document`; 404 `not_found`; 409 `review_not_ready|version_conflict|idempotency_conflict|validation_failed`; 422 path·body 또는 scope 불일치 `validation_failed`; 500 `processing_failed` |
| `POST /api/deep-reviews/{deep_review_id}/final-opinions` | actor header; `FinalOpinionRequest` | 201 `FinalOpinionView` | 400 `actor_name_required|actor_name_invalid|final_opinion_reason_required`; 404 `not_found`; 409 `idempotency_conflict|validation_failed|version_conflict`; 422 path·body; 500 `processing_failed` |
| `GET /api/evidence/{evidence_id}` | UUID evidence ID | 200 `EvidenceView` | 403 `evidence_out_of_scope|unsafe_document`; 404 `not_found`; 422 path; 500 `processing_failed` |

## 발주계획 중심 목표 계약

발주계획 원본 항목은 T-10에서 파일 route와 schema version을 배정했다. 나머지 목표 항목은
아직 배정하지 않았으며, 구현할 때 기존 notice 계약을 몰래 확장하지 말고 각자 새 version을
정의한다.

- **배정 완료 — 발주계획 원본 전체**: `collected-order-plans.json` /
  `bidops.collected-order-plans.v1`. 공식 계획번호, 사업명, 기관 코드·명, 예산, 예정일,
  계약 방식, 업무 구분, SW 상태, 원문 URL, 최초·최근 발견, source hash와 실측된
  `bidNtceNoList`·`ntceNticeYn`·`rcritRgstNo`·`chgDt`를 포함한다.
- 방식별 실험 결과: method/version, score, rank, reason, raw output reference, 실행 비용·지연, 사람 relevance·우선순위와 adjudication.
- 내부 opportunity: plan, pre-spec, bid의 공식 관계와 미확정 후보 관계를 분리하고 관계 근거·확인자를 기록한다.
- 사전규격: 독립 수집 회차, 업무·SW 필터, RFP 첨부 bundle, 저비용 선별, 사람 심층 검토 승인.
- 추적: `계속 추적|보류|종료`, 변경 이력, bid 발견, 사전규격 대비 delta, 알림 delivery 상태.
- 실행: 자동 연결과 수동 단독 실행이 같은 execution, attempt, artifact, idempotency, audit 계약을 공유한다.
- 최종 결정: 입찰공고 시점의 사람 `Go/No-Go`를 추적 선택이나 모델 권고와 분리한다.
