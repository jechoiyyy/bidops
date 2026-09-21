# Spec: 사업 추적 연결·조치 고도화 — 2026-09-17

[`intent.md`](intent.md)의 결정을 구현 가능한 규칙·계약으로 옮긴다. 이 문서와
`docs/contracts.md`·`docs/business-rules.md`가 어긋나면 이 작업 동안은 이 문서가 이기고,
P6에서 두 문서를 이 규칙으로 갱신한다. 코드 위치는 `main` 3344076 기준이다.

## 1. 수집

### 1.1 일일 창

| 원천 | operation | 창 | 회차 | 비고 |
|---|---|---|---|---|
| 발주계획 | `getOrderPlanSttusListServcPPSSrch` | `nticeDt` 최근 21일 | `lifecycle-YYYYMMDD-plans` | ADR-0027 유지. 용역만 반환하고 `일반용역·기술용역` 후처리 |
| 사전규격 | `getPublicPrcureThngInfoServcPPSSrch` | 접수일시 최근 3일 | `lifecycle-YYYYMMDD-notices` | 전량(SW 필터 없음, ADR-0024) |
| 입찰공고 | `getBidPblancListInfoServc` | 공고일시 최근 3일 | 위와 같은 회차 | 전량 |
| 입찰공고 1468 표시 | `getBidPblancListInfoServcPPSSrch` + `indstrytyCd=1468` | 같은 창 | 위와 같은 회차 | 키 집합만 사용 |

- 발주계획 회차와 공고 회차는 따로 만들고 발주계획 → 공고 순으로 적재한다(공고 선별이
  발주계획 사업기회 상태를 읽는다).
- 호출량(실측, 2026-09-14~16): 입찰공고 전체 3일 1,818건 = 2호출, 1468 = 1호출,
  SW 사전규격 33일 465건 = 1호출. 일일 합계는 수십 호출로 한도 1,000에 여유가 크다.

### 1.2 정규화 추가 필드 (모두 optional, `bidops.collected.v2` 유지)

| 필드 | 원천 | 값 |
|---|---|---|
| 사전규격 `demand_agency` | `rlDminsttNm` | 문자열 또는 `null`. 기존 `agency`는 발주기관(`orderInsttNm`) 그대로 |
| 입찰공고 `lifecycle.opening_at` | `opengDt` | timezone-aware ISO 또는 `null` |
| 입찰공고 `qualification_flags.sw_industry_1468` | 1468 조회 키 집합 | `Y`(포함) · `N`(조회 성공·미포함) · `null`(조회 실패·부분 수집) |
| 발주계획 `bid_ntice_no_list` | `bidNtceNoList` | 오타 수정(`collect_order_plans.py:315`) |

- 1468 조회는 수집기 플래그 `--tag-bid-sw-industry`로 켠다. 원문은 `raw/industry1468-page-NNN.json`으로
  보관한다(`bid-`로 시작하면 재분류가 입찰공고 페이지로 읽는다). 수집 파일 최상위 metadata에
  `sw_industry_1468: {status: complete|failed|partial|not_requested, total, pages}`를 남긴다.
  조회가 실패·부분이면 모든 입찰공고가 `null`이고 수집기는 경고와 함께 비0으로 끝나 일일 스크립트가
  적재 전에 멈춘다(다음 날 창에서 다시 수집).
- optional 키 허용 목록을 함께 갱신한다: `app/screening/orchestrator.py:1245,1321`,
  `skills/bidops-screen/scripts/build_screening_results.py:564-579`,
  `app/lifecycle/ingest/loader.py:2494-2500`, `skills/references/workflow-contract.md:42`.
- 관측 snapshot(`loader.py` `_observation_snapshot`)에서 `lifecycle.opening_at`·
  `qualification_flags.sw_industry_1468`은 **값이 `null`이면 넣지 않는다.** `demand_agency`는 값이 있어도
  snapshot에 넣지 않는다(C-1 판정 입력이 이 필드를 싣지 않으므로 같은 회차 C-1 적재와 충돌하지 않게).
  `Notice.demand_agency`에는 저장한다. 기존 회차 재적재의 snapshot hash는 바뀌지 않는다(P2a 테스트로 고정).

## 2. 수집 색인과 선별 적재

### 2.1 수집 색인 `collected_record_index` (migration 0027)

모든 수집 레코드(선별 여부와 무관)를 한 행씩 남기는 **검색용 색인**이다. 사업기회·공고가
아니며 화면에 목록으로 노출하지 않는다.

| 열 | 형식 | 비고 |
|---|---|---|
| `id` | bigint PK | |
| `run_id` | FK run | |
| `record_kind` | `order_plan` · `pre_spec` · `bid_notice` | |
| `record_key` | 문자열 | 발주계획 `order_plan_unty_no`, 공고 `notice_key` |
| `title`, `title_normalized` | text | 정규화는 §4.1 `normalize` |
| `agency`, `demand_agency` | 문자열 | 입찰공고 `agency`는 수요기관, 사전규격 `agency`는 발주기관 |
| `order_plan_unty_no`, `bf_spec_rgst_no`, `bid_no`, `bid_ord` | 문자열 | 공식 키 |
| `sw_business_status`, `sw_industry_1468`, `contract_method` | 문자열 | `null` 보존 |
| `published_at` | timestamptz | |
| `selection_reason` | 문자열 nullable | §2.2 코드, 제외면 `null` |
| `ingested_notice_id` / `ingested_order_plan_id` | FK nullable | 적재된 경우 |

- unique `(run_id, record_kind, record_key)`. 인덱스: 각 공식 키, `bid_no`,
  `(record_kind, title_normalized)`, `agency`.
- 발주계획·사전규격 `bidNtceNoList` 토큰은 자식 테이블 `collected_record_token`
  (`index_id` FK, `token` 문자열, `token` 인덱스)에 한 행씩 둔다. 발주계획 토큰은 공고번호 13자+차수 3자,
  사전규격 토큰은 공고번호 13자다. SQLite·PostgreSQL 모두 인덱스 조회가 되게 배열 열을 쓰지 않는다.
- 같은 레코드가 여러 회차에 있으면 조회는 `published_at`·`run` 생성 시각이 최신인 행을 쓴다.
- 권한: app SELECT/INSERT와 `selection_reason`·`ingested_*` 열 UPDATE, worker SELECT. 토큰 테이블은 app SELECT/INSERT.

### 2.2 선별 규칙

적재 순서는 발주계획 → 사전규격 → 입찰공고. 첫 일치 사유를 기록한다.

| 코드 | 대상 | 조건 |
|---|---|---|
| `order_plan_all` | 발주계획 | 항상 |
| `pre_spec_sw` | 사전규격 | `sw_business_status = 'Y'` |
| `pre_spec_referenced` | 사전규격 | 이번 적재에서 선택된 입찰공고의 `bfSpecRgstNo`가 가리킴, 또는 추적 보충·찾아보기가 요청 |
| `pre_spec_known` | 사전규격 | 같은 사전규격이 이미 적재됨(재관측 갱신, P2b) |
| `bid_same_notice_no` | 입찰공고 | 같은 `bid_no`(차수 무관, 같은 차수 재관측 포함)가 이미 적재됨 |
| `bid_tracked_reference` | 입찰공고 | `orderPlanUntyNo`·`bfSpecRgstNo`·발주계획/사전규격의 `bidNtceNoList` 토큰이 가리키는 레코드의 active 소유 사업기회가 `계속 추적`·`보류`·`종료` |
| `bid_sw_prespec_reference` | 입찰공고 | `bfSpecRgstNo`가 SW=Y 사전규격(DB 또는 색인)을 가리킴 |
| `bid_sw_industry_competitive` | 입찰공고 | `sw_industry_1468 = 'Y'` AND 계약방법이 있고 `수의` 미포함 |
| `tracked_backfill` · `search_result` | 공고 | §5 추적 보충, §4.3 찾아보기 |

- 조건에 쓰는 값이 `null`이면 그 조건은 불일치로 보고 색인에만 남긴다(추정해 적재하지 않는다).
- 적재 통계는 `run.counts_json["selection"]`과 CLI 결과 `selection`에 원천별 `collected`, 사유별
  `selected`, `skipped`로 남긴다(`collected = selected 합 + skipped`). 제외는 경고가 아니다.
  이 통계는 **그 회차 적재 시점의 선별 결과**다. 나중에 추적 보충·찾아보기로 적재된 레코드는 색인 행의
  `selection_reason`에만 반영되고 회차 통계는 다시 쓰지 않는다.
- `--collection`은 수집만 한 회차 디렉터리에 쓴다. 판정 산출물이 있는 회차에 쓰면 판정 적재 hook도 돈다.

### 2.3 적재 모드

- `python -m app.lifecycle.ingest.cli --run <id> --collection`: 회차의
  `collected-order-plans.json`·`collected-notices.json`을 읽어 §2.1 색인 → §2.2 선별 →
  기존 `_upsert_notice`·`_load_order_plans` 경로로 적재한다. 표본(`validation-set.json`)·C-1
  (`screening-input.json`) 적재 경로는 바꾸지 않는다. 구현은 `ingest_run`의 선택 인자
  (`selection="collection"`)로 두어 회차 upsert·통계·hook 흐름을 공유한다.
- `--tracked-backfill`: `계속 추적`·`보류` 사업기회의 공식 키로 색인의 미적재 레코드를 찾아
  §5 규칙으로 적재한다(P2a는 진입점과 색인 기반 적재 함수, P2b는 추적 상태 저장 시 호출).
- 같은 회차를 C-1 판정 적재가 다시 읽어도 충돌하지 않는다. full_run 선택은 수집 레코드를
  그대로 쓰므로 snapshot이 같다(코드 확인, 통합 테스트로 고정).
- CLI 경로의 확장점 등록은 바꾸지 않는다(lifecycle은 형제 모듈을 import하지 않는다). 첨부 취득
  자격 갱신은 daily 스크립트가 적재 뒤 기존 명령(`refresh_fetch_eligibility`)으로 명시 호출한다
  (`operations.md:644` 함정 2와 같은 절차).
- 멱등: 같은 회차 재실행은 색인 unique와 관측 snapshot 검사로 no-op이다.

## 3. 연결과 병합

### 3.1 공식 키 (기존 유지·보완)

| 방향 | 키 | 변경 |
|---|---|---|
| 입찰공고 → 발주계획 | `orderPlanUntyNo` | 유지 |
| 입찰공고 → 사전규격 | `bfSpecRgstNo` | 유지 |
| 발주계획 → 입찰공고 | 발주계획 `bid_ntice_no_list` 토큰 = `bid_no`+`bid_ord` | 오타 수정으로 활성화, 전체 스캔(`loader.py:814-826`) 대신 색인 토큰 조회 |
| 사전규격 → 입찰공고 | 사전규격 `lifecycle.bid_ntice_no_list` 토큰 = `bid_no` | **신규**. 입찰공고 도착 시와 사전규격 재관측 시 양방향 |
| 입찰공고 차수 ↔ 차수 | 같은 `bid_no` | **신규**. 다른 차수의 소유 사업기회를 identity 조회에 포함 |

토큰이 둘 이상의 레코드와 맞으면 연결하지 않고 경고를 남긴다(기존 exact 규칙).

### 3.2 병합 규칙 (자동·사람 공통)

`사람 상태 보유` = `tracking_status ≠ '미선택'` 또는 `recheck_signal_at IS NOT NULL`.
병합 대상 집합 S(잠금 후)에서 H = 사람 상태 보유 사업기회.

| |H| | 동작 |
|---|---|
| 0 | 기존 규칙: 가장 오래된 사업기회를 유지하고 나머지를 병합 |
| 1 | H의 사업기회를 유지하고 나머지를 병합. 유지 쪽의 추적 상태·사유·선택자는 바꾸지 않는다 |
| ≥2 | 병합하지 않는다. 도착 레코드는 자기 사업기회(없으면 새로 생성)에 두고, H의 각 사업기회에 도착 레코드를 target으로 하는 `candidate`·`후보 확인 대기`·`search_strategy='merge_confirmation'` 링크를 만든다. owner+target이 같은 대기·기각 행이 있으면 만들지 않는다 |

- 병합은 기존처럼 secondary를 삭제하지 않고 `merged_into_*` lineage를 남기며 링크를
  primary로 옮긴다(`merge_opportunities`에 `retain` 인자 추가).
- primary의 `first_registered_stage`는 병합된 것 중 가장 이른 단계(`order_plan` <
  `pre_spec` < `bid_notice`)로 둔다.
- 자동 병합으로 primary에 새 공식 확정 링크가 들어오고 primary가 `계속 추적·보류·종료`면
  §6.1 신호를 켠다. 근거 링크는 도착 레코드의 링크다.
- 적재가 `opportunity_merge_state_conflict`로 연결을 되돌리고 공고를 고아로 남기는 경로
  (`loader.py:1509-1530`)는 이 규칙으로 대체한다. 경고 `opportunity_merge_confirmation_required`는
  |H|≥2일 때만 남긴다.

### 3.3 후보 수락 = 병합

`PATCH /api/opportunities/links/{link_id}/decision` `accepted`:

1. 대상 레코드가 어느 active 사업기회에도 소유되지 않으면 기존 동작(`사람 확인 완료`·accepted,
   소유권 획득).
2. 다른 active 사업기회가 소유하면 {owner, 대상 소유 사업기회}에 §3.2 규칙을 적용한다.
   - |H|≤1: 병합하고 후보 행을 **`사람 확인 병합`**(비소유 상태, human_decision `accepted`)으로
     바꾼다. 소유권은 옮겨진 공식 링크가 갖는다(authoritative unique index와 충돌 없음).
   - |H|≥2: 409 `candidate_merge_state_conflict`, details `{opportunities: [{id, tracking_status,
     tracking_selected_by, tracking_selected_at, recheck_signal}]}`. 화면은 한쪽을 먼저
     정리하라고 안내한다.
3. 감사: 기존 `opportunity_link.candidate_decision.recorded` + 병합 시
   `opportunity.merged.human_confirmed`(retained·secondary id, link id).
4. 병합 뒤 추적 결정 확장점 hook을 호출해 첨부 취득 자격을 다시 계산한다. 사람 병합은 신호를
   켜지 않는다.

migration 0027의 CHECK 확장: status에 `사람 확인 병합`, search_strategy에 `merge_confirmation`,
`검색 미확인` 행 구분용 `search_target_kind`(`pre_spec`·`bid_notice`) 열. 백엔드
`OpportunityLinkStatus`·`OpportunitySearchStrategy` literal과 프런트 타입을 함께 넓힌다.

## 4. 후보 대조와 찾아보기

### 4.1 이름 사다리

`experiments/lifecycle-linkage-survey/scripts/name_normalize.py`의 `collapse`·`normalize`·
`breaking_split`·`longest_fragment`·`search_variants`와 전략 순서
`full → breaking_split → normalized → longest_fragment → prefix12`를
`app/lifecycle/services/name_matching.py`로 옮긴다(P2a, 동작 동일, 기존 테스트 케이스
이식). 색인의 `title_normalized`와 P2c `opportunity_candidates.py`가 이 모듈을 쓴다. 판정: 원천 제목의 변형 v가 대상 `title_normalized`에 포함되면 그 전략으로 일치.
정밀도는 이 순서다. 수집기에는 복제하지 않는다.

### 4.2 SW=Y 사전규격 자동 후보

- 시점: `pre_spec_sw`로 사전규격을 적재한 직후(같은 트랜잭션, 실패는 적재를 막지 않고 경고).
- 대상: DB 발주계획 중 **기관 일치**(`OrderPlan.agency_name`의 공백 정규화 값 =
  사전규격 `agency` 또는 `demand_agency`) AND 이름 사다리 일치, 그리고 소유 사업기회에
  authoritative 사전규격 링크가 아직 없는 것.
- 결과: 발주계획 **소유 사업기회**가 owner, 사전규격 notice가 target인 `candidate`·
  `후보 확인 대기`, `search_strategy`=첫 일치 전략, `agency_match=true`,
  `attempted_strategies`, `last_searched_at`.
- 정렬·상한: 전략 정밀도 → 발주계획 `published_at` 최신, 사전규격당 5건. 같은 owner+target의
  기각 행이 있으면 다시 만들지 않는다. 0건이면 행을 만들지 않는다.

### 4.3 찾아보기

`POST /api/opportunities/{id}/searches` `{target: "pre_spec" | "bid_notice"}` + actor 헤더.

| target | 원천 제목·기관 | 조회 대상(색인, 최신 행) |
|---|---|---|
| `pre_spec` | 소유 발주계획 `title`·`agency_name` (없으면 422 `search_source_missing`) | `record_kind='pre_spec'` |
| `bid_notice` | 소유 사전규격 `title`·`agency`·`demand_agency`, 없으면 소유 발주계획 | `record_kind='bid_notice'` |

- 이름 사다리 일치 후보를 기관 일치 우선, 전략 정밀도 순으로 최대 5건. 기관 불일치 후보도
  `agency_match=false`로 포함한다. 이미 이 사업기회가 소유한 레코드와 기각 쌍은 제외.
- 찾은 레코드가 미적재면 회차 파일에서 `search_result`로 적재한 뒤 후보 링크를 만든다.
- 0건이면 `검색 미확인` 행(`search_target_kind`, `last_searched_at`, `attempted_strategies`)을
  만들거나 갱신한다. 화면·집계는 이것을 "없음"으로 바꾸지 않는다.
- 응답: `{searched_at, target, attempted_strategies, candidates: OpportunityLinkView[],
  search_unconfirmed: bool}`. 감사 `opportunity.search.performed`(건수만).
- 동기 처리다. 색인 SQL + 필요한 회차 파일 파싱(300건 ≈ 700KB ≈ 11ms 실측)으로 요청 안에서
  끝난다.

### 4.4 사전규격 상세용 후보 조회

`GET /api/pre-specs/{notice_pk}/order-plan-candidates` → 그 notice를 target으로 하는
`후보 확인 대기` 링크와 owner 사업기회·발주계획 요약(`title`, `agency_name`,
`planned_order_year/month`, `budget_amount`, `tracking_status`), 링크 view.

## 5. 추적 보충

- 사업기회가 `계속 추적`·`보류`로 저장될 때(추적 상태 서비스 commit 직후, 실패는 저장을
  되돌리지 않고 안전 코드 기록)와 `ingest.cli --tracked-backfill`(daily 스크립트 마지막 단계):
  - 소유 발주계획 `order_plan_unty_no`, 소유 사전규격 `bf_spec_rgst_no`, 소유 입찰공고 `bid_no`로
    색인에서 **미적재** 레코드를 찾는다.
  - 찾은 레코드를 `tracked_backfill`로 적재하고 §3 규칙으로 연결한다(자동 병합이면 신호).
- 조회 창은 색인 전체다(보관 기간 정책은 operations에 기록).

## 6. 재검토 신호와 확인

### 6.1 발생

- `raise_recheck_signal`: 대상 사업기회 `tracking_status ∈ {계속 추적, 보류, 종료}`이고 근거가
  공식 확정 링크일 때 켠다(기존 `종료`만 → 확장). `미선택`·사람 수락 병합은 켜지 않는다.
- 같은 링크 재관측은 no-op, 다른 링크면 근거 교체 + 감사 `opportunity.recheck_signal.created`
  (기존).
- 갱신: `opportunity_tracking.py:194` docstring, `tests/lifecycle/test_opportunity_tracking.py:409-455`,
  ADR-0030 구현 메모.

### 6.2 확인 처리

`POST /api/opportunities/{id}/recheck-acknowledgements` `{expected_link_id: int, note?: string(≤500)}`
+ `X-BidOps-Actor-Name`.

| 결과 | 응답 |
|---|---|
| 성공 | 200 `OpportunityDetailResponse`. 신호 해제, 추적 상태 불변, 감사 `opportunity.recheck_signal.acknowledged` `{opportunity_id, link_id, note_present}` |
| 신호 없음 | 409 `recheck_signal_absent` |
| 근거 링크 불일치 | 409 `recheck_signal_changed`, details `{current_link_id}` |
| 사업기회 없음·병합됨 | 404 `opportunity_not_found` / 409 기존 코드 |

추적 상태 저장이 신호를 해제하는 기존 동작은 유지한다.

### 6.3 이력

`GET /api/opportunities/{id}/tracking-decisions` 응답에 `recheck_events[]`
`{kind: created|acknowledged|cleared_by_decision, link_id, actor_kind, claimed_name, created_at,
note_present}`를 추가한다(감사 이벤트 투영, 상수 회 조회).

## 7. 구역·사유·보류 기한·검색

### 7.1 사유 (`action_reasons[]`, 모든 행에 계산)

| 코드 | 조건 |
|---|---|
| `new_link` | `recheck_signal_at IS NOT NULL` |
| `candidate_pending` | 소유 `candidate`·`후보 확인 대기`·strategy ≠ `merge_confirmation` 존재 |
| `merge_confirmation` | 소유 `candidate`·`후보 확인 대기`·strategy = `merge_confirmation` 존재 |
| `blocking_item` | 연결 공고의 미답변 차단 항목 > 0 (기존 projection) |
| `hold_overdue` | `tracking_status='보류'` AND `tracking_selected_at + 14일 ≤ now` |

### 7.2 구역 (첫 일치)

| 구역 | 조건 |
|---|---|
| `조치 필요` | (`계속 추적`·`보류` AND 사유 ≥ 1) OR (`종료` AND `new_link`·`candidate_pending`·`merge_confirmation` 중 하나) |
| `보류` · `추적 종료` · `추적 중` | 기존 |
| `신규 입찰공고` | `미선택` AND `first_registered_stage='bid_notice'` |
| (`미결정`, 집계 전용) | 그 밖의 `미선택` |

- `OpportunitySection`에 `신규 입찰공고` 추가, `section_counts`에 포함. `미결정` 필터는 기존처럼 422.
- 구역·사유는 한 SQL 식으로 계산하고 목록·집계·workload가 같은 식을 쓴다.

### 7.3 보류 기한

- `HOLD_REVIEW_PERIOD_DAYS = 14`(lifecycle 상수). `hold_review_due_at = tracking_selected_at +
  14일`, `보류`일 때만 값, 그 밖은 `null`. 저장하지 않는다.
- 기준 시각 `now`는 Python에서 timezone-aware UTC로 계산해 SQL 파라미터로 넘긴다(SQLite·
  PostgreSQL 일치, 마이크로초 보존). 화면의 D±n은 한국 시간 날짜 차이다.
- 목록 필터 `hold_review=overdue|due_soon|attention`(due_soon: `now < due ≤ now+3일`,
  attention = 둘의 합집합), 정렬 `sort=hold_review_due_at`(오름차순, null 마지막).
- 보류를 다시 저장하면 `tracking_selected_at`이 갱신되어 기한이 새로 시작한다(기존 저장 규칙).

### 7.4 목록 응답 추가

- query: `q`(2~100자), `reason`(§7.1 코드), `hold_review`, `section='신규 입찰공고'`,
  `sort=hold_review_due_at`.
- item: `action_reasons[]`, `hold_review_due_at`.
- response: `action_reason_counts{code: int}`(활성 `reason` 필터만 제외한 기준).

### 7.5 서버 검색 `q`

공백 정규화·소문자 비교로 **소유 링크**(authoritative)의 `OrderPlan.title`·`agency_name`,
`Notice.title`·`agency`·`demand_agency`에 ILIKE 부분일치(EXISTS). 기각·대기 후보 대상은
검색하지 않는다. 인덱스는 추가하지 않는다(범위 밖 아이디어).

## 8. workload와 대시보드

- `GET /api/workload` 키에 `tracking_hold_review_due`(= `hold_review=overdue` 건수)를 추가한다.
  응답 키 순서 고정(ADR-0053 §1·§4 갱신). `tracking_action_required`는 §7.2 `조치 필요`.
- 대시보드 `보류 재검토` 패널: `GET /api/opportunities?hold_review=attention&sort=hold_review_due_at&limit=5`.
  행 = 사업명(대표 링크 제목) · 보류 사유 · `기한 지남 D+n`/`D-n` · 선택자.
  바닥 링크 `사업 추적에서 모두 보기` → `/opportunities?section=조치 필요&reason=hold_overdue`.
  조회 실패·0건·로딩을 문자로 구분한다. 회차 선택과 무관하다.

## 9. 최종 Go/No-Go

### 9.1 공고 조건 요약

`GET /api/opportunities/{id}/bid-conditions` (deep_review 소유, lifecycle 모델 읽기 전용):

```
{ opportunity_id, generated_at,
  pre_spec: {notice_id, title, agency, budget} | null,
  bid_notices: [ { notice_id, bid_no, bid_ord, published_at, observation_sha256,
      conditions: { budget, estimated_price, deadline_at, opening_at, method,
        participation_limited, industry_limited, sw_industry_1468, joint_contract_method,
        successful_bid_method, technical_evaluation_rate, region_limit_basis,
        joint_contract_regions, change_reason, re_notice },
      changes_from_previous: [ {field, status: changed|unchanged|unknown, before, after} ] } ],
  pre_spec_comparison: [ {field: budget|title, status, before, after} ],
  not_comparable: ["deadline_at"] }
```

- 차수는 authoritative 입찰공고를 `bid_no`, `bid_ord` 순. 첫 차수의 `changes_from_previous`는 빈 배열.
- 어느 한쪽이 `null`이면 `unknown`이다(`unchanged`로 추정하지 않는다). 금액은 Decimal 문자열로
  비교한다. 모델 호출 없음.
- `pre_spec_comparison`은 의미가 같은 `budget`·`title`만. 사전규격 `deadline_at`(의견등록마감)과
  입찰 마감은 `not_comparable`.

### 9.2 결정 근거 분리 (migration 0028)

`bid_final_decision`:
- nullable로 변경: `comparison_id`, `comparison_version`, `result_sha256`,
  `baseline_document_version_id`, `comparison_document_version_id`.
- 추가: `basis_kind` (`comparison` | `notice_conditions`, NOT NULL, 기존 행 `comparison`),
  `basis_notice_id` FK notice, `basis_observation_sha256` (64 hex).
- CHECK: `comparison`이면 비교 5열 NOT NULL·basis 열 NULL, `notice_conditions`면 반대.
- append-only trigger·unique·supersession 유지.
- 권한: app에 `bid_final_decision` INSERT와 잠금용 `UPDATE (id)`
  (`runtime-privileges.sql:368` 주석 방식). `tests/app/test_runtime_database_privileges.py:59-74,360-392` 갱신.

`POST /api/opportunities/{id}/final-decisions`:

```
{ decision: go|no_go, reason, expected_notice_id, expected_observation_sha256,
  supersedes_final_decision_id: uuid|null, request_id: uuid }  + X-BidOps-Actor-Name
```

| 검사 | 실패 |
|---|---|
| `expected_notice_id` = 최신 authoritative 입찰공고(`published_at`, `bid_ord` 최신) | 409 `final_decision_notice_not_latest` |
| 그 공고 최신 관측 `source_sha256` 일치 | 409 `final_decision_observation_changed` |
| 최신 입찰공고 `published_at` 없음 | 503 `bid_delta_currentness_unavailable`(기존) |
| supersession·idempotency·actor | 기존 코드 재사용(`record_final_decision` 검사를 공유 함수로 추출) |

- currentness: `bid_delta_currentness.py`에 basis 인식 함수 추가(ADR-0053 §6 단일 규칙).
  `notice_conditions` 결정은 기준 공고보다 새 authoritative 입찰공고가 있거나 기준 공고 관측
  hash가 바뀌면 `stale`, 판정 불가면 `unknown`.
- 소비자 수정: `decision_queue.py:115-118` outer join, `bid_delta.py:627-630` 비교 없는 최신
  결정의 503 제거, `schemas/bid_delta.py:125-129` 비교 필드 nullable + `basis_kind`,
  `prespec_projection.py:127` 결정 대기 집계.
- 기존 comparison 경로와 비교 생성 endpoint는 유지한다. 화면은 비교 생성 단추를 비활성으로 둔다.

## 10. REST 변경 요약

| 메서드·경로 | 변경 | 소유 |
|---|---|---|
| `GET /api/opportunities` | `q`·`reason`·`hold_review`·`section=신규 입찰공고`·`sort=hold_review_due_at`, item `action_reasons`·`hold_review_due_at`, `action_reason_counts` | lifecycle |
| `GET /api/opportunities/{id}` | item 필드 동일 추가, 링크 status·strategy literal 확장 | lifecycle |
| `PATCH /api/opportunities/links/{id}/decision` | 수락 병합, 409 `candidate_merge_state_conflict` | lifecycle |
| `POST /api/opportunities/{id}/recheck-acknowledgements` | 신규 | lifecycle |
| `POST /api/opportunities/{id}/searches` | 신규 | lifecycle |
| `GET /api/opportunities/{id}/tracking-decisions` | `recheck_events[]` | lifecycle |
| `GET /api/pre-specs/{notice_pk}/order-plan-candidates` | 신규 | lifecycle |
| `GET /api/workload` | 키 `tracking_hold_review_due` | lifecycle |
| `GET /api/opportunities/{id}/bid-conditions` | 신규 | deep_review |
| `POST /api/opportunities/{id}/final-decisions` | 신규 | deep_review |
| `GET /api/opportunities/{id}/bid-delta`, `GET /api/bid-delta/decision-queue` | 비교 없는 결정 반영 | deep_review |

새 오류 코드는 `routers/opportunities.py` `_ERRORS`(`:39-63`)와 deep_review router 오류 표에
등록하고 details를 전달한다. 등록하지 않은 코드가 500 `processing_failed`가 되지 않게 한다.

## 11. 화면

### 11.1 사업 추적 (`/opportunities`)

- 탭: `조치 필요 · 추적 중 · 보류 · 추적 종료 · 신규 입찰공고 · 전체`. 기본 `조치 필요`.
- 조치 필요 탭 안 사유 칩 필터(서버 `reason`, 건수 = `action_reason_counts`).
- 행: 사업명·기관·단계 줄(기존) + 사유 칩(`새 공고`·`후보 확인`·`병합 확인`·`확인 항목`·
  `보류 기한 지남 D+n`), 사유별 주 행동 1개 — 새 공고: `확인`(상세 확인 사항으로), 후보·병합:
  `후보 확인`(`CandidateLinkDialog`), 보류 기한: `재검토`(`TrackingStatusDialog`).
- 검색: 서버 `q`를 Enter로 적용하고 실제 조건이 바뀔 때 offset 0으로 이동한다. raw URL `q`와 받은 페이지 밖을 포함한 서버 검색은 [목록 검색 UX 명세](../0921_search-ux/spec.md)를 따른다.
- 상세 `확인 사항`: 새 공고 카드에 근거 공고·시각과 `확인 완료`(메모 선택) → ack API, 409는
  최신 상태 다시 읽기 안내. `TrackingStatusDialog`에 "저장하면 새 공고 확인도 함께 처리됩니다".
- 단계 줄: 사전규격 연결 없음 → `사전규격 찾아보기`(소유 발주계획이 있을 때), 입찰공고 연결
  없음 → `입찰공고 찾아보기`. 결과는 후보 목록 또는 `검색 미확인 · 마지막 검색 {시각}`이며
  "레코드가 없다는 뜻이 아닙니다" 문구를 유지한다.
- 후보 수락 409 `candidate_merge_state_conflict`: 양쪽 추적 상태·선택자·시각을 보여 주고 한쪽을
  먼저 정리하라는 안내.
- `추적 이력` 탭: 결정 revision과 `recheck_events`를 시간순으로 함께 표시.
- 상세 `심층 검토 보고서`: `GET /api/opportunities/{id}/deep-reviews` 목록(공고명·상태·품질 표식·
  생성 시각·최신 최종 의견·보고서 링크), 빈 상태 "연결된 심층 검토 보고서가 없습니다. 사전규격
  상세에서 시작합니다." ID 입력 폼 제거.

### 11.2 대시보드

§8 패널을 여정 스트립 아래 전체 폭에 둔다. 여정 타일 03 사업 추적의 건수는 새 `조치 필요`.

### 11.3 최종 Go/No-Go

- 목록(`GoNoGoPage`)은 `GET /api/bid-delta/decision-queue` 한 번으로 그린다(N+1 제거).
- 결정 화면(`BidDeltaDecisionPage`): 상단 `공고 조건` 표(최신 차수)와 `차수 간 변경`(changed만
  강조, unknown은 `미확인`), 사전규격 대비(예산·사업명), `비교 불가: 마감`.
- 결정 폼 근거: 완료된 비교가 있으면 선택 가능, 없으면 `공고 조건` 근거로 저장. 저장 조건
  체크리스트: 최신 차수 확인·사유 입력·담당자 이름.
- pending 1초 폴링 제거, 비교 생성 단추 비활성(`비교 계산 프로그램 미구현` 문구).

### 11.4 사전규격 상세

`발주계획 후보 N건` 구역: §4.4 목록, 각 후보에 발주계획 요약·전략·기관 일치 표시와
`CandidateLinkDialog`(links는 §4.4 응답, `onDirtyChange` 연결). 수락·기각 뒤
`["pre-spec-detail"]`·`["pre-specs"]`·`["opportunity"]` query 무효화. 409 병합 충돌은 §11.1과
같은 안내.

## 12. 문서 갱신 대상 (P6)

`docs/contracts.md`, `docs/business-rules.md`(선별 적재·병합·조치 필요·보류 14일·신호·찾아보기·
입찰공고 전환 절 :175-205), `docs/bid-delta-contract-spec.md`, `docs/deep-review-erd.md`,
`docs/operations.md`(daily 스크립트·cron 예시·보관·중단 기준, 함정 1·2 갱신),
`docs/ARCHITECTURE.md` 해당 절, ADR-0025·0028·0030·0053 개정 메모, 신규 ADR-0058(결정 근거 분리)·
ADR-0059(전량 수집·선별 적재·색인 검색), `docs/tracking/status.md`, `docs/tracking/findings.md`
("사업기회 추적 이력을 읽을 계약이 없고…" 종결), `AGENTS.md`·`CLAUDE.md` 저장소 지도.
