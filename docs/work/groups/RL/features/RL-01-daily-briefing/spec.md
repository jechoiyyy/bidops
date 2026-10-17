# 평일 브리핑 생성·Slack 전송·반응 저장 — spec

- 기능 ID: `RL-01-daily-briefing`
- 근거: [intent.md](./intent.md), RL-00 spec(회사 사실 노드 규칙), contracts.md "공통 REST 규칙"·"사업기회 구역·사유·보류 기한"·"결정 대기 집계", business-rules.md "전량 수집과 선별 적재"·"조치 필요·신규 입찰공고 구역", ADR-0061(일일 창), ADR-0067(workload 키), ui-spec §3·§4.1·§4.2·§5
- 작성일: 2026-10-16 (같은 날 독립 검사 1차 21건·2차 16건 + RL-02 연관 반영; 3차 검사는 돌리지 않음)

## 큰 틀 문서와의 관계

- 인용하는 절: contracts.md 공통 REST 규칙(오류 envelope·actor 헤더·`request_id` 멱등), `GET /api/workload` 확장점 규칙(ADR-0067 "같은 모집단"), `GET /api/opportunities` 마감 임박 창 정의(링크 단위 `deadline_at`), ADR-0061 일일 창(공고 4일·발주계획 1일, 기준일 전일 KST), business-rules "사전규격 C-1 기본 대상"(SW사업대상 Y), company-preferences §1~§4(값은 RL-00 그래프에 있음), ui-spec §3 공통 컴포넌트·§4.1 브리핑·§4.2 Slack·§5 검증, ux-review §5 결정 3·4·8.
- 이 문서에서 새로 확정하는 항목: 후보 모집단·창, 결정적 점수·제외 규칙과 규칙 파일, 항목·반응 계약, 테이블 3개, REST 3개, CLI·호스트 스크립트, Slack 메시지·Socket Mode worker 계약, workload 키 1개, 화면 상태.
- 큰 틀 문서 수정이 필요한 항목(STEP-008): contracts.md에 브리핑 REST·DB·규칙 파일 절 추가, business-rules.md에 "브리핑 추천·반응" 절, operations.md에 "일일 브리핑·Slack" 절(env 파일·cron 예시·시운전), ARCHITECTURE §4.2 lifecycle 소유 추가·§5.1a 흐름 한 줄, tech-stack에 `slack_sdk` 의존, roadmap RL-01 행 "Luna 정책 발행은 RL-03" 갱신. ADR.md에 한 줄.

## 입력·출력 계약

(REST는 4개다.)

### 기준일과 모집단

- 브리핑 1건 = `briefing_date`(KST 날짜, 평일 = 월~금; 공휴일은 범위 밖) 1건, 하루 1회 생성이며 재생성·삭제는 없다(수정은 다음 날 브리핑으로). 기준일 D의 브리핑은 **D-1 KST 기준 수집**(notices 트랙 4일 창, order-plans 1일 창)이 끝난 뒤 만든다. 후보 창 = (직전 브리핑 `generated_at`, 지금]; 직전 브리핑이 없으면 D-1 00:00 KST부터. 창 안에 처음 관측된 레코드만 후보다(`first_observed_at = min(NoticeObservation.observed_at)` / `OrderPlan.first_discovered_at`). 이미 어느 브리핑의 항목인 공고·발주계획은 다시 추천하지 않는다. 따라잡기는 `--date`로 사람이 돌리며 자동 catch-up은 없다(CLAUDE.md cron 규칙).
- 후보 stage(enum 전체) `pre_spec | bid_notice | order_plan`.
  - `pre_spec`: `Notice.source_type ∈ PRE_SPEC_SOURCE_TYPES`이고 SW사업대상이 `Y`(기존 `sw_only` 조건과 같은 식). `review_exclusion_status='included'`.
  - `bid_notice`: `Notice.source_type = 'bid_notice'`(loader 고정값)이고 `deadline_at > now`. `review_exclusion_status='included'`.
  - `order_plan`: screening 확장점 `briefing_order_plan_candidates(session, since, until)`(제공자 없음 → 빈 목록 + 경고 `order_plan_provider_absent`; relevant 판정 = 누적 실행의 발주계획별 **최신** result)가 돌려주는 C-2 결과 `qwen_relevance='relevant'`인 발주계획 중 **반복 발주처 규칙**(아래)에 맞는 것만. 그 밖의 relevant 발주계획은 브리핑에 넣지 않는다(ADR-0073 결정 3).
- 모든 후보는 소유 사업기회가 있어야 하며(`OpportunityLink` 공식·확정) 없으면 항목을 만들지 않고 생성 경고 `orphan_candidate`로 센다.

### 회사 규칙 입력 (RL-00 활성 그래프, 확장점 경유)

- lifecycle은 deep_review 테이블을 import할 수 없다(ADR-0045·`boundary_map`). 그래서 lifecycle `extensions.py`에 projection 확장점 `company_facts_projection(session) -> CompanyFactsProjection | None`을 선언하고 deep_review가 제공한다: `CompanyFactsProjection = {graph_version_id: UUID, facts: [{fact_key, type, status, label, value}]}` — 실회사 활성 binding의 비evidence 노드 중 **`status=confirmed`만**(제공자가 거른다). 제공자 없음 또는 실회사 없음 → `None` → 생성 실패 `company_not_registered`(exit 1, 브리핑 행 없음). `briefing.graph_version_id`는 FK 없는 UUID 열이다(lifecycle 단독 `init_db`에서 참조 테이블이 없음).
- 읽는 사실(fact_key·value 키는 RL-00 구성 규칙·value 확장 표와 같다): `pref:domain:<nn>` domain `{tier ∈ 1|2|3, keywords[]}`; `excl:<kind>` domain `{excluded:true, keywords[], kind}`; `pref:amount_floor`·`pref:amount_range`·`pref:solo_cap` capability `params.krw`/`params.min_krw`·`params.max_krw`/`params.krw`; `pref:agency:<nn>` domain `keywords[0]`=기관명; `project:<year>-<nn>` `label`=사업명·`value.agency`·`value.year`. `proposed`·`unknown`은 제공자가 이미 뺐고 규칙은 status를 다시 확인한다(이중 검사).
- stage별 후보 필드 매핑:

| 필드 | pre_spec·bid_notice(`Notice`) | order_plan(`OrderPlan`) |
|---|---|---|
| 텍스트 | `title`·`agency`·`demand_agency` | `title`·`agency_name`·`supervising_agency_name` |
| 기관(반복 발주처 비교) | `agency`, `demand_agency` | `agency_name`, `supervising_agency_name` |
| 금액 | `estimated_price` → 없으면 `budget` | `budget_amount` |
| 지역제한 | `region_limit_json` | 없음 → `region` 제외 조건 미적용 |
| 마감 | `deadline_at`(`deadline_kind`: pre_spec→`opinion_close`, bid→`bid_close`) | 없음, `planned_month=planned_order_month`(`deadline_kind=planned_month`) |

### 결정적 점수와 제외 (규칙 파일 `briefing-policy-v1.json`)

- 파일 위치 `web/backend/app/lifecycle/policies/briefing-policy-v1.json`, 키 전체: `{schema:"bidops.briefing-policy.v1", policy_identity:"briefing-policy-v1", top_n:10, weights:{tier1:30,tier2:20,tier3:10,repeat_agency:25,similar_project:25,sw_target:10,amount_in_range:10}, deadline_warning_days:7, tracked_change_fields:["deadline_at","title","budget","estimated_price"], slack_items_per_message:10, large_enterprise_threshold_krw:2000000000}`. sha256을 브리핑 행에 고정한다. 값 변경은 새 버전 파일(`tunable`은 표에 표시).
- 텍스트 정규화 함수 `briefing_rules.normalize_text(s)` = NFKC → `name_matching.normalize`(구분자→공백·collapse·선두 태그 제거) → 모든 공백 제거 → casefold. 매칭 대상 = 위 매핑 표의 텍스트 3개를 `" "`로 이어 `normalize_text`. 키워드·기관명도 같은 함수로 정규화한 뒤 부분문자열/동일 비교한다(`name_matching.normalize` 단독은 NFKC·casefold가 없어 쓰지 않는다).
- `similar_project` 식: 후보 텍스트 `T`와 각 `project:*` `label`에 대해 `fragments(label)` 중 길이 ≥ `name_matching.MIN_FRAGMENT_CHARS`(라이브러리 상수 6)인 fragment를 `normalize_text`한 것이 하나라도 `normalize_text(T)`의 부분문자열이면 그 project는 hit. hit 수를 `reasons`에 적는다. 별도 정책 키는 두지 않는다.
- 제외(먼저 적용, 하나라도 맞으면 항목 없음, 제외 사유 집계만 저장): `excl kind=hardware|election|design_only|staffing_only` 키워드 hit; `region`: **보류(2026-10-17 사용자 결정, 독립 리뷰 지적)** — 수집한 `region_limit_json.basis`는 지역 이름이 아니라 소재지 판단 기준(`rgnLmtBidLocplcJdgmBssNm`, 예 "본사소재지")이고 `joint_contract_regions[]`는 공동도급 의무 지역이라 참가 가능 지역 이름이 없다. 모르는 값은 제외 근거가 아니므로 `region` 제외는 적용하지 않고 `excluded.region`은 항상 0이다(키는 유지). `excl:region.keywords`(허용 지역 이름, 루트랩 v2 = 대구·세종)는 형태만 읽는다. 참가 가능 지역 수집은 후속(docs/tracking/findings.md 2026-10-17); `amount_floor`: `estimated_price`(없으면 `budget`)가 있고 `< pref:amount_floor.params.krw`(`excl:amount_floor` domain 노드는 표식일 뿐 값은 `pref:amount_floor`에서 읽는다). 금액이 둘 다 없으면 제외하지 않는다.
- 점수 = tier 최고 1개 가중치 + `repeat_agency`(기관 필드 둘 중 하나가 어느 `pref:agency:*`의 `keywords[0]`과 `normalize` 동일) + `similar_project`(위 식 hit ≥ 1) + `sw_target`(pre_spec Y) + `amount_in_range`(금액이 `params.min_krw..max_krw` 안). 동점은 마감 오름차순(마감 없음은 뒤), 다음 `first_observed_at` 오름차순.
- 반복 발주처 규칙(order_plan 전용) = `repeat_agency` **그리고** `similar_project` 둘 다 참. 하나만 참이면 후보 아님.
- 상위 `top_n`만 `kind=recommendation` 항목. 점수 0(어떤 가중치도 없음)은 항목에 넣지 않는다.
- `reasons`(칩, 최대 3, 순서 고정): `{kind:"keyword", text:<첫 hit 키워드>}`, `{kind:"similar_project", count:n}`, `{kind:"repeat_agency", text:<기관명>}`. 해당 없는 칩은 생략.
- `blocking`(차단 조건, RL-01이 결정적으로 아는 것만, 최대 2): `{kind:"consortium_review", text:"<임계 한글> 이상 · 컨소시엄 검토"}`(금액 ≥ `min(pref:solo_cap.params.krw, large_enterprise_threshold_krw)`; 20억은 대기업 참여 가능 구간 상수로 규칙 파일에 둔다), `{kind:"deadline_short", text:"마감 n일"}`(마감 ≤ `deadline_warning_days`). 지역·HW 등은 제외 조건이므로 blocking에 없다.
- `tracked_change` 묶음: 추적 상태 `계속 추적|보류`인 사업기회의 권위 연결 공고(`stage=notice`; 권위 연결 = contracts "마감 임박 창"의 정의)에 창 안 `NoticeObservation.changed_fields_json ∩ tracked_change_fields ≠ ∅`인 관측이 있으면 **(브리핑, 공고)당 1행**(`kind=tracked_change`, `change_fields[]`=바뀐 필드 합집합, `reaction` 없음·`verdict_display="재검토 중"`). 다른 기능(RL-02 마감 알림)이 같은 공고에 사유를 더하면 **같은 행의 `change_fields`에 합친다**(행을 추가하지 않는다; `verdict_display`는 정정이 있으면 "재검토 중", 마감 사유만이면 "마감 임박"). top_n과 별도이고 상한 없음.

### 항목·반응 계약

- `reaction` enum 전체 `대기 | 채택 | 무시 | 나중에`. 초기 `대기`. `tracked_change` 행은 `reaction=null` 고정.
- 반응은 항목당 하나(팀 결정이 아니라 "마지막 담당 기록")다. 두 사람이 다르게 누르면 나중 요청이 `expected_revision` 불일치로 409 `version_conflict`를 받고 재조회 뒤 다시 누른다; 모든 시도는 이벤트로 남는다(ux-review §2 이관 항목의 결정).
- `reacted_via` enum `screen | slack`. `reacted_by`는 화면은 actor 헤더 이름, Slack은 사용자 표시 이름(`users.info` 호출 없이 interaction payload의 `user.username`/`name` 중 있는 것).
- 되돌리기 = 새 반응 PATCH(이전 값으로). 모든 변화는 `briefing_reaction_event` append(`previous`·`new`·`actor`·`via`·`request_id`). `revision`은 0부터 +1.
- 멱등: core `IdempotencyRecord`(`app/core/models.py`; `operation="briefing.react"`, `aggregate_type="briefing_item"`, `aggregate_id=<item_id>`, `claimed_name=actor`, `request_id=body`, `request_sha256` = canonical JSON `{operation, item_id, reaction, expected_revision, actor, via}`의 SHA). 같은 key·같은 hash는 저장 snapshot(`BriefingItemView`) 재생, 다른 hash는 409 `idempotency_conflict`. fence 로직은 `opportunity_tracking.py`의 사설 함수를 `core/idempotency_fence.py`로 뽑아 둘이 같이 쓴다(복제 금지). `expected_revision` 불일치 409 `version_conflict`.
- 반응은 `Opportunity.tracking_*`·`CompanyOpportunityTracking`을 바꾸지 않는다(검사 T6).

### REST (`bidops.briefing.v1`)

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/briefings/latest` | 없음(query 없음) | 200 `BriefingView`(가장 최근 `briefing_date`) | 404 `briefing_not_found` |
| `GET /api/briefings/{date}` | path `YYYY-MM-DD` | 200 `BriefingView` | 404 `briefing_not_found`, 422 날짜 |
| `GET /api/briefings/{date}/slack-preview` | path | 200 `{schema_version:"bidops.briefing-slack-preview.v1", channel_id_present:bool, blocks:JSON[], text:string}` (실제 보낼 payload와 같은 함수) | 404 |
| `PATCH /api/briefings/items/{item_id}/reaction` | actor 헤더; body `{reaction:채택\|무시\|나중에\|대기, expected_revision:int, request_id:UUID}` | 200 `BriefingItemView` | 400 actor; 404 `briefing_item_not_found`; 409 `version_conflict\|idempotency_conflict\|reaction_not_allowed`(tracked_change 행); 422 body |

`BriefingView = {schema_version:"bidops.briefing.v1", briefing_date, status: generated|empty|collection_incomplete, generated_at, item_count:int(추천 수만), slack_sent_at:ts|null, items:BriefingItemView[], tracked_changes:BriefingItemView[], collection_note:string|null}`. **`policy_sha256`·`graph_version_id`는 응답에 넣지 않는다**(운영 정보, DB 열에만). `BriefingItemView = {item_id:UUID, kind:recommendation|tracked_change, rank:int|null, stage, notice_id:int|null, order_plan_id:int|null, opportunity_id:int, title, agency, amount_krw:int|null, deadline_at:ts|null, deadline_kind: bid_close|opinion_close|planned_month|null, planned_month:"YYYY-MM"|null, verdict_display: 분석 대기|연차 추적|재검토 중|마감 임박|분석 중(v1에서 닫힌 다섯 값; RL-03이 판정 enum을 더해 v2로 올린다), reasons[], blocking[], change_fields:string[], reaction, reacted_by, reacted_at, reacted_via, revision, record_path:"/opportunities/<id>"}`(RL-02가 `/activity` 리다이렉트를 붙인다). `score`는 응답에 넣지 않는다.
- 오류 code는 lifecycle 관례대로 `routers/briefings.py`의 로컬 오류 map + 프런트 `apiErrors.ts`에 등록한다(`core/api_errors.py`는 손대지 않는다).

- `GET /api/workload`에 키 `briefing_pending`(최근 브리핑의 `reaction=대기` 추천 수; 브리핑 없음은 `null`/`provider_absent`)을 lifecycle이 직접 센다. 사이드바 "오늘의 브리핑" 건수가 이 키를 읽는다. **최종 키 순서**(`WorkloadKey`·`_WORKLOAD_KEYS`·`types.ts`·`api-mock.ts`·`test_workload_api.py` 동일): 기존 10개 뒤에 `company_attention`(RL-00), `briefing_pending`(RL-01) 순.

### CLI·호스트 스크립트

- `python -m app.lifecycle.cli build-briefing [--date YYYY-MM-DD] [--send] [--dry-run] [--json]` — **`--date` = 브리핑 날짜 D**(기본값 오늘 KST), 수집 회차는 D-1. D가 토·일이면 exit 0, 행 없음, `status=null`·`slack.skipped_reason=weekend`. (lifecycle `cli.py` 신설, 기존 `ingest/cli.py`와 같은 extension 등록·exit 규칙; `tests/app/test_module_cli_entrypoints.py` 진입점 표에 추가). 출력 JSON `{briefing_date, status, created:bool, item_count, tracked_change_count, excluded:{<kind>:n}, warnings:[code], slack:{sent:bool, message_ts:string[], skipped_reason:string|null}}`. 같은 날 재실행은 `created=false`(멱등, 기존 행 유지). **재생성·삭제 옵션은 없다**(append-only; DELETE 권한도 주지 않는다).
- `collection_incomplete` 판정의 회차 조회: `Run.id LIKE 'lifecycle-<D-1 YYYYMMDD>-notices--%' OR Run.id LIKE 'lifecycle-<D-1>-notices-retry%--%'`(스크립트의 retry 디렉터리 포함). 0행 → incomplete(`collection_note="기준일 수집 회차 없음"`); 2행 이상 → 추정하지 않고 incomplete(`"회차 중복"`, 경고 `run_ambiguous`); 1행이면 그 run의 `IngestWarning` 수가 0일 때만 완전.
- `--send`: `BIDOPS_SLACK_ENABLED=true`·토큰·채널이 있고 status ≠ `empty`·`slack_sent_at IS NULL`일 때만 1회 전송. 평일이 아니면 `skipped_reason=weekend`. 전송 전 allowlist(`slack.com`) 검사, 실패는 `slack_send_failed` 경고로 남기고 브리핑은 유지(재전송은 `--send` 재실행).
- `scripts/run-daily-briefing.sh [--date] [--send] [--dry-run]`: `run-daily-lifecycle.sh`와 같은 깨끗한 환경 규칙, web 컨테이너 안에서 CLI 실행(`docker compose exec -T web python -m app.lifecycle.cli build-briefing …`), `flock`은 두 트랙 공용 lock 재사용. cron 설치는 사람이 하며 예시만 operations.md에 둔다.

### Slack

- 설정(env 파일 `env/slack.env`, gitignore): `BIDOPS_SLACK_ENABLED=false`, `BIDOPS_SLACK_BOT_TOKEN`, `BIDOPS_SLACK_APP_TOKEN`(Socket Mode), `BIDOPS_SLACK_CHANNEL_ID`, `BIDOPS_SLACK_ALLOWED_HOSTS=slack.com,wss-primary.slack.com`, `BIDOPS_PUBLIC_BASE_URL`(레코드 링크). 토큰은 로그·응답·오류에 넣지 않는다. compose overlay `docker-compose.slack-egress.yml`이 **web(`--send`가 도는 곳)과 slack-worker 두 서비스**에 env 파일과 egress를 준다.
- 메시지(ui-spec §4.2): header "오늘의 브리핑 · M월 D일 (요일) · n건" → 항목마다 section(제목 링크 `<base><record_path>`(=`/opportunities/<id>`; RL-02가 리다이렉트를 붙임) · 기관 · 금액 · 마감 D-n[7일 이내만 강조]) + context(판정 표시 — 이유 칩 텍스트 " · " 연결 / 차단 조건) + actions(버튼 `볼게요` primary·`무시` default, `action_id="briefing_react"`, `value="<item_id>:채택|무시"`) + divider → 마지막 "화면에서 보기" 링크. payload에는 `item_id`·제목·기관·금액·마감·이유 텍스트·링크만.
- 추적 변화 메시지: 같은 형식(버튼 없음, 헤더 "추적 중 사업 변화"). 메시지당 항목 ≤ `slack_items_per_message`(10, Block Kit 50 블록 상한 안)이고 넘치면 같은 헤더로 메시지를 나눈다; 추천 메시지도 같은 상한(top_n ≤ 10이라 1건). `briefing.slack_message_ts`·`tracked_change_message_ts`는 보낸 순서의 `text[]`.
- Socket Mode worker `python -m app.lifecycle.cli slack-worker`(별도 프로세스, compose 서비스 `slack-worker`, 기본 비기동·profile `slack`): `block_actions` 수신 → `value` 파싱 → 같은 service 함수로 반응 저장(`via=slack`, `request_id = uuid5(SLACK_REACTION_NS, trigger_id)`, `SLACK_REACTION_NS = uuid5(NAMESPACE_URL, "bidops:slack-reaction")` 상수, `expected_revision`=조회한 현재 값; 409 `version_conflict`면 재조회 후 **1회** 재시도, 다시 실패하면 메시지에 "화면에서 먼저 반응했습니다" 표시) → `chat.update`로 해당 항목 블록을 "✓ <이름>이 <반응> · 되돌리기(버튼 `value="<item_id>:대기"`)"로 교체. 다른 `action_id`는 무시·감사 로그. 응답 ack는 3초 내.
- 의존: `slack_sdk>=3.27,<4`(tech-stack 추가). hosted fallback·다른 채널 전송 없음.

### 화면 `/briefing` (ui-spec §4.1)

- 데이터: 화면 `?date=`가 없으면 `GET /api/briefings/latest`, 있으면 `GET /api/briefings/{date}`; `?selected=<item_id>`가 있으면 그 행을 선택해 피크를 연다(ui-spec §1.4의 `selected=<notice>`를 `item_id`로 고정 — 발주계획 항목은 notice가 없다); 반응 PATCH; 공고 상세는 기존 `/api/pre-specs/:id`·`/api/order-plans/:pk`(피크 보조 정보). 주 버튼 대비는 2026-10-16 테마 교체(ADR-0048 개정, `test:contrast` 8/8)로 해결됐으며 화면 CSS는 색을 재정의하지 않는다.
- 뷰 탭 = `reaction` 필터(반응 대기·채택·무시·나중에), 건수는 클라이언트 계산. 표 6열·둘째 묶음·피크 패널·키보드(1·2·H·Enter·Esc·Z)·토스트 되돌리기는 §4.1 그대로. 판정 셀은 `verdict_display`. **RL-01이 그리지 않는 §4.1 요소**(대응 필드 없음, 빈 블록 금지): 피크의 판정 블록(사유·확인할 것)과 다음 행동 체크(RL-03·02), 상단바 "공고 추가"·"공유"·"가져오기"(후속), 도구 중 보기 설정(후속). 피크는 머리·제목·보조·반응 버튼 3·반응 기록·왜 추천(칩)·자세히 보기만.
- 상태: `status=empty` → 빈 상태 "오늘 추천할 공고가 없습니다 · 수집 정상"; `collection_incomplete` → 경고 블록 "오늘 수집이 끝나지 않았습니다"(`collection_note`); 404 → "브리핑은 아직 발송되지 않았습니다"(현재 자리 화면 문구 유지).
- 표시 금지: `policy`·`score`·`generated_at` 초 단위·집계 분모·모델명.

## 설정 키와 기본값

| 키 | 타입 | 기본값 | 허용 범위 | 비고 |
|---|---|---|---|---|
| `briefing-policy-v1.json` `top_n` | int | 10 | 1..30 | `tunable`, 새 버전 파일로만 변경 |
| `weights.*` | int | 30/20/10/25/25/10/10 | 0..100 | `tunable` |
| `slack_items_per_message` | int | 10 | 1..12 | Block Kit 50 블록 상한 |
| `deadline_warning_days` | int | 7 | 1..30 | ui-spec 7일과 같음 |
| `BIDOPS_SLACK_ENABLED` | bool | false | | fail-closed |
| `BIDOPS_SLACK_*` 토큰·채널 | str | 없음 | | env 파일, 비면 전송 skip |
| `BIDOPS_SLACK_ALLOWED_HOSTS` | csv | `slack.com,wss-primary.slack.com` | | allowlist |
| `BIDOPS_BRIEFING_POLICY_PATH` | path | 위 파일 | | immutable 파일 규칙 |

## 상태 값과 실패 처리

- `briefing.status`: `generated | empty | collection_incomplete`. `collection_incomplete` 판정 = 기준일 D-1의 notices 트랙 `Run` 행이 없거나 `IngestWarning`이 1건 이상. 항목은 그래도 만든다.
- 반응: `대기|채택|무시|나중에`; `reacted_via`: `screen|slack`.
- 오류 code 추가: REST `briefing_not_found`·`briefing_item_not_found`·`reaction_not_allowed`(라우터 로컬 map + `apiErrors.ts`); CLI 경고/종료 `company_not_registered`·`slack_send_failed`·`run_ambiguous`.

## 저장

- `briefing` {id UUID PK, briefing_date DATE UNIQUE, status, generated_at, policy_sha256 CHAR(64), graph_version_id UUID(FK 없음), item_count INT, excluded_counts JSONB, warnings JSONB, slack_message_ts JSONB NULL(text[]), slack_sent_at TS NULL, tracked_change_message_ts JSONB NULL, created_by TEXT}. CHECK `status IN ('generated','empty','collection_incomplete')`.
- `briefing_item` {id UUID PK, briefing_id FK, kind, rank INT NULL, stage, notice_id INT NULL FK, order_plan_id INT NULL FK, opportunity_id INT FK, score NUMERIC(6,2), reasons JSONB, blocking JSONB, change_fields JSONB, deadline_at TS NULL, deadline_kind, planned_month TEXT NULL, amount_krw BIGINT NULL, reaction TEXT NULL, reacted_by TEXT NULL, reacted_at TS NULL, reacted_via TEXT NULL, revision INT NOT NULL DEFAULT 0}. CHECK 전부(models와 migration에 같은 선언): `(notice_id IS NULL) <> (order_plan_id IS NULL)`; `kind IN ('recommendation','tracked_change')`; `stage IN ('pre_spec','bid_notice','order_plan')`; `deadline_kind IS NULL OR deadline_kind IN ('bid_close','opinion_close','planned_month')`; `reaction IS NULL OR reaction IN ('대기','채택','무시','나중에')`; `reacted_via IS NULL OR reacted_via IN ('screen','slack')`; `(kind='recommendation' AND rank IS NOT NULL AND reaction IS NOT NULL) OR (kind='tracked_change' AND rank IS NULL AND reaction IS NULL)`; `(reacted_by IS NULL) = (reacted_at IS NULL) AND (reacted_by IS NULL) = (reacted_via IS NULL)`. 부분 UNIQUE 인덱스(기존 `postgresql_where` 패턴): `(briefing_id, notice_id) WHERE notice_id IS NOT NULL`, `(briefing_id, order_plan_id) WHERE order_plan_id IS NOT NULL`, `(briefing_id, rank) WHERE rank IS NOT NULL`. 같은 공고가 추천과 추적 변화에 동시에 해당하면 추천 행만 만들고 변화 사유는 추천 행 `change_fields`에 적는다(공고당 1행 보장). `test_alembic_autogenerate.py` drift 0.
- `briefing_reaction_event` {id UUID PK, item_id FK, revision INT, previous TEXT, new TEXT, actor TEXT, via TEXT, request_id UUID, created_at}; UNIQUE(item_id, revision); append-only(UPDATE/DELETE 권한 없음).
- migration `0038_briefing.py`(단일 head 후속), 권한은 `scripts/runtime-privileges.sql`(web: SELECT/INSERT/UPDATE briefing·briefing_item, SELECT/INSERT briefing_reaction_event; **worker(slack-worker)**: SELECT briefing, `UPDATE (reaction, reacted_by, reacted_at, reacted_via, revision) ON briefing_item`·SELECT, INSERT briefing_reaction_event만; ro_backup SELECT; **DELETE는 어느 역할에도 없음**). 새 테이블은 `tests/app/boundary_map.py TABLE_OWNER`(lifecycle)와 `tests/app/test_db_migrations.py NEW_TABLES`에 추가한다.

## 인터페이스(CLI·UI·API)

위 REST·CLI·스크립트·Slack worker. 외부 호출 보호 장치: `core/slack.py` 전송기 하나가 allowlist·토큰 존재·`BIDOPS_SLACK_ENABLED` 검사를 호출 전에 하고, payload 생성 함수가 허용 키만 넣는다(T8).

## 결정과 이유

| 결정 | 이유 | 버린 대안 |
|---|---|---|
| 이유·차단 조건은 결정적 규칙 | 사용자 결정(2026-10-16) | Luna 요약 |
| Slack Socket Mode | 사용자 결정(2026-10-16); 공개 URL 없음 | 공개 endpoint, 링크만 |
| 발주계획은 반복 발주처 ∧ 유사 실적일 때만 | ADR-0073 결정 3 "연차 사업 예고 전용" | relevant 전부 |
| 규칙이 `confirmed` 사실만 읽음 | ADR-0073 결정 6 | proposed 포함 |
| 반응이 추적 상태를 바꾸지 않음 | ux-review 결정 3 | 채택 = 계속 추적 |
| 가중치·N은 immutable 규칙 파일 | CLAUDE.md "policy 파일은 버전+sha256 고정" 관례 | 환경변수 |
| `score`·`policy_sha256`을 응답에서 제외 | ui-spec 표시 금지(운영 정보) | 포함 후 화면에서 숨김 |
| 브리핑을 lifecycle이 소유, 발주계획은 확장점 | ADR-0045 모듈 의존 방향(lifecycle이 screening을 import하지 않음), workload 선례 | 새 모듈 |
| 0건이면 Slack 미발송 | ui-spec §4.2 | 빈 메시지 |
| N/A — 다중 채널·DM | 사용자 Q2 "bot 전용 채널 하나" | |

## 테스트 케이스

| ID | 시나리오 | 기대 결과 | 종류 |
|---|---|---|---|
| T1 | 고정 fixture(사전규격 Y/N, 입찰공고, relevant 발주계획 반복/비반복, HW·선거·타지역·소액 후보) | 제외 사유 집계 정확, 반복∧유사만 order_plan 항목, 점수·동점 정렬·top_n 절단 결정적(같은 입력 두 번 = 같은 결과) | 단위 |
| T2 | 회사 사실 `proposed` 키워드만 있는 분야 | 규칙에 반영 안 됨(점수 0) | 단위 |
| T3 | 추적 중 사업의 마감 변경 관측 / 미추적 사업의 변경 | tracked_change 1행 / 0행 | 단위 |
| T4 | 같은 날 재실행; 첫 실행(직전 브리핑 없음) 창; 이미 항목인 공고 재등장; 추천과 추적 변화 동시 해당 | created=false·행 불변 / D-1 00:00 KST부터 / 재추천 없음 / 공고당 1행 | 단위 |
| T5 | notices Run 0행 / 2행 / 1행+경고 1건 / 1행+경고 0 | `collection_incomplete`(각 note) / `collection_incomplete`+`run_ambiguous` / `collection_incomplete` / `generated`; 항목은 모두 생성 | 단위 |
| T6 | 반응 PATCH: 채택→되돌리기, 멱등 replay, 두 사람 충돌(revision), tracked_change 행, CHECK·부분 UNIQUE 위반 insert | 이벤트 append·`version_conflict`·`reaction_not_allowed`·DB 거부, `Opportunity.tracking_status` 불변 | 통합(PostgreSQL 포함, strict dict) |
| T7 | workload `briefing_pending` | 최근 브리핑 대기 수와 같음, 없으면 null | 단위 |
| T8 | slack-preview·전송기: 허용 키만, 토큰 미설정·enabled false·주말·0건·allowlist 밖 host | 전송 0회·skipped_reason, 토큰이 어떤 문자열에도 없음 | 단위(가짜 Slack 서버) |
| T9 | Socket Mode worker 가짜 payload(`block_actions`, 다른 action_id, 중복 전달, 화면과 경쟁 409) | 반응 저장 1회(멱등), `chat.update` 1회, 무시·감사, 409 뒤 재조회 1회 | 단위(가짜) |
| T10 | 화면: 탭 필터·피크·키보드 1/2/H/Z·토스트·빈 상태·수집 경고·금지 문자열, 1280·1440 | Playwright app 통과 | 프런트 |
| T11 | `scripts/run-daily-briefing.sh --dry-run` 깨끗한 환경 | 호출 순서 출력, 실제 호출 0 | 스크립트 |
| T12 | bidops-local 실제 1회: build → 화면 → `--send`는 테스트 채널로 사람 확인 뒤 | 메시지 1건, 버튼 클릭 → 화면 반영 | 수동(감독 시운전) |

## 컨벤션 반영 항목

- REST `bidops.briefing.v1`, reaction enum, `verdict_display` 값 집합, workload 키 `briefing_pending`(lifecycle `WorkloadKey`·`_WORKLOAD_KEYS`·프런트 `types.ts`·`api-mock.ts WORKLOAD_KEYS` 동기), 확장점 `company_facts_projection`, 오류 code, 규칙 파일 `bidops.briefing-policy.v1`, env `BIDOPS_SLACK_*`, compose overlay·profile `slack`, `requirements.lock` 갱신(`test_requirements_lock.py`).
