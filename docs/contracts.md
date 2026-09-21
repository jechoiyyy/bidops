# 외부 계약

C-2 Ollama 참조 적재는 `skills/bidops-screen/contracts/ollama-reference/`의 별도
검증 프로필을 사용한다. 기존 Phase 0 catalog·schema hash는 불변이다. 파일/DB의
C-2 v1 envelope는 유지하되 `qwen3.8:27b` identity는 새 참조 프로필로 검증한다.
정책은 `activation_candidate`·`not_measured`·활성화 차단이어야 하며, 원 실행의
`quality_status=unmeasured_reference`와 응답·사후 변환 provenance를 보존한다.
DB에는 해당 정책의 `quality_gate_status=not_measured`, `active_slot=null`로 남긴다.
기존 실행 API의 `성공`은 처리 완료만 뜻하며 품질 측정·운영 활성화를 뜻하지 않는다.
모델 판정 binding은 정책의 고정 binding과 필드별 일치해야 한다.

C-2 ranking은 순위 순서, input/result는 수집 원본 순서다. 전체 ID 집합은 같아야 하고
모델 batch는 순위 순서로 구성한다. DB 점수는 `Numeric(20,10)`으로 투영하되 원래
점수 전체 자릿수는 불변 artifact와 `result_sha256`으로 검증한다.

C-1 `candidate_selection`의 기존 `collect-candidate.v2 / candidate_pool_all /
["candidate_pool"]` 조합은 보존한다. 새 정책 버전은 `rules_version=sw-business-selection.v1`,
`mode=sw_business_all`, `include_collection_buckets=[]` 조합을 사용할 수 있다.
이 경우 `full_run`은 수집본의 `qualification_flags.sw_business_status`가 정확히 `Y`인
공고 전체를 동결한다. `N`·누락·null을 Y로 간주하지 않는다.
`single_notice`의 사용자 지정 대상과 기존 고정 `quality_sample` 계약은 유지한다.
기존 정책의 내용·digest를 바꾸거나 새 규칙을 품질 승인으로 취급하지 않는다.

웹 클라이언트, 파이프라인 subprocess, 운영 도구가 의존하는 기본 REST 경로는 `/api`다. 발주계획·사업기회 경로는 아래의 현재 버전 계약만 사용하며, 문서에 없는 경로를 추정해 호출하지 않는다.

## 공통 REST 규칙

- JSON 요청과 응답은 UTF-8이다. timestamp는 timezone 정보를 포함하고, 알 수 없는 값은 `null`과 사유로 표현한다.
- 목록 응답은 원칙적으로 `items`, `total`, `limit`, `offset`을 사용한다. legacy endpoint 중 배열이나 별도 pagination을 반환하는 곳은 호환성을 유지한다.
- 일반 validation 오류는 422, 존재하지 않는 자원은 404, 중복·불가능한 상태 전이는 409, 준비되지 않은 외부 의존성은 503이다.
- Lean document/deep-review API에서 router·service가 반환하는 안정 오류는 다음 형식을 사용한다. `request_id`는 요청에 UUID가 없거나 검증 전에 실패하면 `null`이다.

```json
{
  "error": {
    "code": "bundle_not_ready",
    "message": "ready document bundle이 필요합니다",
    "details": null
  },
  "request_id": "request-id"
}
```

- Lean API도 path·JSON body·multipart/form 자체가 Pydantic/FastAPI 검증을 통과하지 못한 422에는 FastAPI 기본 `{"detail":[...]}`를 반환한다. 그 밖의 Lean 안정 오류만 위 `error` envelope를 사용한다. legacy API는 다른 `{"detail": ...}` 오류도 계속 반환할 수 있으므로 소비자는 endpoint와 status에 맞는 parser를 사용한다.
- 새 API와 Lean API 응답은 내부 filesystem path, 객체 저장소 key의 자격증명, prompt, 모델 원응답, 회사 프로필 전문을 포함하지 않는다. `AttachmentResponse`에도 서버 내부 `stored_path`를 포함하지 않는다.
- Lean mutation과 actor·감사 경계에 편입된 legacy mutation은 `X-BidOps-Actor-Name`을 요구한다. 대상은 문서·심층 검토·리포트·사업기회·첨부·기관 포털·정책 mutation이다. 이 값은 감사 표식이지 인증 정보가 아니다. 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 함께 사용한다. 형식이 없으면 printable ASCII를 그대로 보존하며 malformed·제어문자 입력은 `actor_name_invalid`로 거부한다.

### 목록 검색 `q`

발주계획·사전규격·사업 추적의 raw `q`는 URL/API에서 보존한다. 비교 시 Unicode White_Space 25자(`U+0009`–`000D`, `0020`, `0085`, `00A0`, `1680`, `2000`–`200A`, `2028`, `2029`, `202F`, `205F`, `3000`)와 `U+FEFF`를 제거하고 ASCII `A`–`Z`만 소문자로 바꾼다. 각 필드의 연속 부분 문자열을 독립적으로 비교한다. `%`, `_`, 역슬래시는 literal이며 공백/BOM만 있는 `q`는 검색 해제다. 서버 검색은 다른 필터와 AND이고 `total`·집계·페이지 분할 전에 적용한다.

- 사전규격은 `Notice.title|agency`, 사업 추적은 authoritative 소유 링크 대상의 `OrderPlan.title|agency_name`·`Notice.title|agency|demand_agency`, 발주계획은 `OrderPlan.title|agency_name|order_plan_unty_no`를 검색한다.
- 사업 추적의 2~100자 한계는 위 공백의 연속 구간을 ASCII SPACE 한 칸으로 줄여 양끝을 제거한 값의 Unicode 코드포인트 수로 검사한다. 유효한 raw `q`는 바꾸지 않는다.
- Go/No-Go의 `q`는 API 인자가 아니다. 받은 decision queue 행의 실제 `title|agency`만 클라이언트에서 검색하며 서버 `total`은 유지한다. 상세 동작은 [검색 UX 명세](0921_search-ux/spec.md)를 따른다.

## 상태와 식별자

- 수집·판정·심층 검토 실행은 서로 다른 불변 execution ID를 사용한다. 재시도는 기존 실행을 덮지 않고 새 attempt 또는 새 execution으로 남긴다.
- 공고 식별자는 외부 공고번호와 DB 내부 식별자를 구분한다. API 경로의 `{notice_pk}`와 `{notice_id}` 의미를 endpoint schema 그대로 따른다.
- 판정 실행 status는 대기, 실행, 부분 성공, 성공, 실패, 중단을 구분한다. terminal status에는 종료 시각이 있어야 한다.
- 심층 검토 attempt stage는 `requirements_and_evaluation`, `delivery_risk_economics`, `synthesis_and_validation`만 허용한다.
- `계속 추적`, `보류`, `종료`와 최종 입찰 `Go/No-Go`는 별도 필드·별도 이벤트다. 현재 final opinion 값에 임의 매핑하지 않는다. R-07의 입찰 delta·최종 결정 계약은 [ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md)로 **채택**했고 R-08에서 endpoint·table·migration을 **구현**했다. 비교를 실제로 계산하는 worker와 모델 binding 실행은 아직 없다.

## JSON wire shape 규칙

아래에서 `field?`는 field가 wire에 있을 때 JSON `null`이 허용된다는 뜻이다. 생략 가능성은 `optional`, null 가능성은 `nullable`로 각각 적는다. `optional`은 생략, `nullable`은 `null`, `optional nullable`은 둘 다를 허용한다. Lean request·response는 열거하지 않은 field를 거부한다. legacy model은 호환 동작을 유지하므로 새 소비자는 정의된 field만 사용한다.

- `RunSummary`: `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `screening_basis?`, `status`, `superseded_by?`, `counts`. `counts`는 `notices`, `order_plans`, `judgments`, `reviews`, `collection`이다.
- `IngestRequest`: body의 optional nullable `run_id`와 query의 optional nullable `run_id` 중 적어도 하나가 필요하다. `IngestResponse`는 `run_id`, `notices`, optional `order_plans`(기본 0), `judgments`, `reviews`, `warnings[]`, `warning_counts`다. 같은 회차 재적재는 지원되는 갱신·멱등 경로이며 중복 자체로 409를 반환하지 않는다.
- `NoticeList` query: required `run_id`; optional `grade`, `readiness`, `focus`, `sample_role`(default `analysis`), `attachment=any|none|manual`, `q`, `sort=deadline|grade|published`, `limit` 1..500(default 50), `offset` 0 이상. 응답은 `items`, `total`, 실제 적용한 `filters`다.
- `PreSpecList` query: optional `sw_only`(default `true`), `business_division`, `origin=추적|신규`, `q`, `sort=published|deadline|observed`, `limit` 1..500(default 50), `offset` 0 이상. 기본적으로 누적 `notice.source_type='pre_spec'`를 조회한다. `sw_only=true`는 `sw_business_status='Y'` 또는 추적 중인 발주계획 연결을 포함한다. 이 연결은 같은 opportunity의 notice 링크 status가 `확정`·`사람 확인 완료`·`후보 확인 대기` 중 하나이고 opportunity tracking status가 `계속 추적`·`보류` 중 하나이며, 그 opportunity에 authoritative `order_plan` 링크(`order_plan_id` 존재)가 있는 경우다. 따라서 `검색 미확인`, `미선택`, `종료`, authoritative order-plan 링크가 없는 연결은 예외가 아니다. 응답은 `items`, `total`, `limit`, `offset`, `overview_status_counts`이며 item은 `notice_pk`, `pre_spec_no`, `title`, `agency`, `published_at`, `deadline_at`, `budget`, 원문 그대로의 `sw_business_status`·`business_division`, `origin`, `opportunity_id`, `tracking_status`, `kept_by_tracking`, `document`, `overview_review_status`를 가진다. `opportunity_id`·`tracking_status`·`origin`은 pending/rejected/search-unconfirmed link가 아니라 해당 notice의 authoritative active owner만 투영한다. `document`는 `attachments`, `완료`, `대기`, `진행`, `차단`, `실패` 건수이며 큐 행이 없는 첨부는 총계에만 포함한다. `kept_by_tracking`는 `sw_business_status`가 `Y`가 아닌 행이 위 예외로 남을 때만 `true`다. `origin`은 연결된 opportunity의 `first_registered_stage`에서 `order_plan→추적`, `pre_spec|bid_notice→신규`로 투영하고 연결이 없으면 `null`이다. `overview_review_status`(추가, 구 `docs/design/PLAN.md` 3단계, git 이력에서 확인)는 해당 notice의 최신
`prespec_overview_run.status`를 `notice_id`로 LEFT JOIN해 투영한 `PreSpecOverviewReviewStatus`
10값(`awaiting_document|awaiting_structure|preparing|awaiting_model|queued|running|completed|needs_human_review|failed|cancelled`) 중 하나이며, 그 notice에
run 행이 아직 없으면 `null`이다(개요 검토 미시작). `overview_status_counts`(추가)는
`{status, count}[]`로, 10개 계약값과 `status=null`(run 행 없음) 총 11개 항목이 이 목록 조회의
필터(`sw_only`·`business_division`·`origin`·`q`)는 전부 반영하되 `limit`/`offset`과 무관하게 **필터에 일치하는 전체 건수**를 담아 항상 존재한다(건수 0인 항목도 포함). 클라이언트는 반환된 `items`(현재 페이지)만 그룹에 채우고 그룹 헤더 건수는 `overview_status_counts`를 표시해 페이지네이션과 그룹 건수 표시를 분리한다. 응답에는 object key·로컬 경로·URL을 넣지 않는다.
  item에는 등급과 자동 문서 준비 필드 다섯이 더 있다([ADR-0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)). nullable `grade`, nullable `grade_source=screening_judgment|human_review`, 비 null `auto_preparation_status`(기본 `not_applicable`), nullable `auto_preparation_reason`, nullable `latest_deep_review_id`다. `grade`가 `null`이면 판정도 사람 정정도 없다는 뜻이고 그때 `grade_source`도 `null`이다 — 둘 중 하나만 채우거나 "없음"을 특정 등급으로 접지 않는다. `auto_preparation_status`는 `not_applicable|waiting_attachments|bundle_draft|bundle_ready|overview_running|deep_review_started|deep_review_ready_for_click|blocked` 여덟 값이며 `not_applicable`은 "대상이 아님"이지 "알 수 없음"이 아니다. `auto_preparation_reason`은 안전 코드이며 어휘는 `grade_not_priority`, `awaiting_fetch`, `no_ready_document`, `attachments_failed`(취득 행이 모두 `차단`·`실패`로 끝났고 준비된 문서가 없어 `blocked`가 된 경우), `bundle_has_blocking_issues`, `bundle_unchanged`, `human_bundle_draft`, `processing_failed`, `not_sw_business`, `bundle_not_auto_ready`, `overview_not_completed`, `deep_review_exists`, `service_unavailable`과 문서 묶음 service가 내는 안전 코드다. 이 다섯 값은 저장된 열이 아니라 조회 시점의 파생값이며 공고 수와 무관한 상수 회 조회로 계산한다. 등급과 상태 필터는 아래 누적 탐색 계약에 따라 서버에서 적용한다.
  사전규격 검토 제외 확장(PoC, additive): item에
  `review_exclusion_status=included|excluded`(비 null), `review_exclusion_actor_name`,
  `review_exclusion_reason`, `review_exclusion_changed_at`(timezone 포함 시각)을 추가한다.
  최초 상태는 included이며 변경 정보 세 필드는 null이다.
  `review_exclusion=all|included|excluded` 필터의 기본값은 all이다. 다른 명시적 필터와 AND로
  결합한다. actionable·recent는 excluded를 항상 제외하며 tracking·all은 그대로 표시한다.
  total·페이지·workspace_counts·overview_status_counts도 같은 규칙을 쓴다. 명시적 excluded와
  actionable/recent를 결합하면 0건이다. 전체 이력 UI만 포함 여부 필터를 제공하며 URL과 선택
  fingerprint에 포함하고 다른 보기 이동 시 초기화한다. 상세 왕복 URL도 이를 보존한다.

  `POST /api/pre-specs/review-exclusions` 요청은
  `{notice_ids: int[], status: "included"|"excluded", actor_name: str, reason: str}`다.
  ID는 양의 DB integer(최대 2147483647) 1~200개로 중복을 허용하지 않는다. ID 없음·다른
  source_type·잘못된 ID가 섞이면 전체 422(`invalid_pre_spec_notice_ids`는 대상 조회 실패)다.
  actor_name·reason은 양끝 공백 제거 후 필수이며 각 128·2000자 한도다. 응답은 200
  `{items: [{notice_id, status, outcome: "changed"|"unchanged"}]}`이며 요청 순서다.
  공고를 ID 오름차순으로 잠그고 상태·마지막 변경 정보·`pre_spec.review_exclusion_changed`
  audit_event를 원자적으로 저장한다. 감사 aggregate는 notice/ID이며 safe_metadata에
  previous_status·status·actor_name·reason·changed_at을 남긴다. unchanged는 쓰기를 하지 않는다.
  별도 요청 재생 저장소는 없고 같은 목표 상태의 재요청은 unchanged로 처리한다.
  이 API는 추적·등급·리뷰·분석 자격·원본 관측을 변경하지 않는다.

  2026-09-16 누적 탐색 확장:
  `grade`(기존 등급 및 `판정 없음`), `overview_view=all|attention|pending|completed|failed|cancelled|not_started`,
  `tracking_decision=pending`, `tracking_status=계속 추적|보류|종료|미선택`, `source_run_id`,
  `observed_from`·`observed_to`(날짜), `deadline_status=open|passed|unknown`은 모두 서버 필터다.
  `workspace=actionable|recent|tracking|all`을 추가하며 미지정 API 기본값은 `all`이다.
  `sort`에는 `observed`가 추가된다. 각 필터는 페이지 분할 전에 적용한다.
  `pending`은 실제 대기·실행 상태이고 run 부재는 `not_started`로 구분한다.
  관측 기간은 한국 시간 양끝 날짜를 포함하며, 회차와 기간은 같은 관측 행에 적용한다.
  회차를 지정해도 공고 내용·분석·추적은 현재 상태다. `recent`에 양 날짜가 없으면
  한국 시간 오늘 포함 최근 7일을 적용한다. `actionable`은 개요 사람 확인 필요,
  심층 검토 클릭 대기, 개요 완료이면서 기존 신규·미선택/null 추적 결정 대기의 합집합이다.
  `tracking`은 계속 추적·보류다. 마감이 지났다는 이유로 업무 대상에서 제외하지 않는다.
  2026-09-21 확장([ADR-0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md)):
  `deadline_scope=current|passed|all`(기본 `all`)을 추가한다. `current`는 `deadline_at`이
  요청 시각 이상이거나 `null`인 건, `passed`는 `deadline_at`이 요청 시각 미만인 건이다.
  두 값은 서로소이고 합집합이 전체다. `deadline_scope`는 actionable workspace 술어의
  일부다. 따라서 `workspace_counts`의 `actionable` 칸에는 활성 workspace와 무관하게
  적용되고, `items`·`total`·`overview_status_counts`에는 `workspace=actionable`일 때만
  영향을 준다. `recent`·`tracking`·`all` 칸과 그 workspace의 `items`·`total`은 영향받지
  않는다. `current`는 `마감 미확인`(null)을 포함한다 — 마감 경과로 접지 않는다.
  검토 제외 숨김은 구간 술어보다 먼저 적용하므로 제외 건은 어느 구간에도 들어가지 않는다.
  잘못된 값은 422 `deadline_scope is invalid`다. 구간 건수는 아래 집계 문단이 정의한다.
  item에는 nullable `first_observed_at`, `last_observed_at`,
  `next_action=confirm_overview|open_deep_review|decide_tracking|null`이 추가된다.
  다음 행동은 나열된 순서로 첫 일치를 쓰며 새로운 업무 상태가 아니다.
  응답의 `workspace_counts`는 네 보기 이름을 키로 한 건수 map이며 활성 workspace만
  제외한 필터를 적용한다(recent의 기본 7일 조건은 recent 건수에만 적용).
  `overview_status_counts`는 활성 workspace와 나머지 필터를 적용하고 `overview_view`만
  제외한다. `total`·`items`는 모든 필터를 적용한다. 집계는 limit/offset과 무관하다.
  비 null `deadline_scope_counts{current,passed}`(2026-09-21 추가)는 구간을 적용하기 **전**
  actionable 집합을 두 구간으로 나눈 건수이며, 활성 workspace·활성 `deadline_scope`와
  무관하게 언제나 같은 값이고 언제나 존재한다. 나머지 필터(`q`·`deadline_status`·`grade`
  등)는 모두 반영하고 기준 집합은 `workspace_counts`와 같다. 두 칸의 합은 구간 미적용
  actionable 건수이고, `deadline_scope=current`이면
  `workspace_counts["actionable"] == deadline_scope_counts.current`이며
  `workspace=actionable`을 함께 주면 `total == deadline_scope_counts.current`다. 합계 키
  (`all`)는 두지 않는다 — 필요하면 소비자가 두 칸을 더한다.
  마감 정렬은 마감 전 가까운 순, 마감 경과 최근순, 미확인 순이며 ID로 동률을 해소한다.
  별도의 사전규격 **상세** endpoint는 없다. 상세 화면도 이 목록 endpoint를 쓴다.
- `NoticeListItem`: `id`, `notice_key`, `run_id`, `title?`, `agency?`, `published_at?`, `deadline_at?`, `estimated_price?`, `sample_role?`, `sample_stratum?`, `collection_bucket?`, `grade?`, `readiness?`, `focus?`, `attachment_count`, `attachment_status=none|g2b|manual`이다.
- `ReviewUpsertRequest`: required `run_id`; optional nullable `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `reviewer`; optional `verification_answers`(default `[]`), 요소는 optional nullable `item`, `answer`다. `ReviewResponse`는 `id`, `run_id`, `notice_pk`, 같은 nullable review field, `created_at?`, `updated_at?`, `answers[{id,item?,answer?}]`다. 이 legacy schema의 review 문자열은 wire enum으로 강제되지 않으므로 소비자가 임의의 추가 enum을 가정하지 않는다.
- `AgencyPortalCreateRequest`: required `agency_pattern`, `system_name`, `search_url_template`; optional non-null `enabled`(default `true`), optional nullable `note`. PATCH는 이 다섯 field의 partial body이다. PATCH `enabled`는 nullable이며 `null`을 보내면 현재 값을 바꾸지 않는 no-op이다. `AgencyPortalResponse`는 `id`, 위 다섯 field다.
- legacy `AttachmentResponse`: `id`, `name?`, `url?`, `origin?`, `file_ext?`, `size_bytes?`, `extract_status?`, `created_at?`. `stored_path`는 wire field가 아니며 서버 내부 호환 저장 metadata로만 남는다. notice detail과 첨부 처리 상태에 nested 될 수 있고 다운로드는 `url`의 id 기반 endpoint를 사용한다.
- `RunDetailResponse`는 `RunSummary` 전체와 `collection_scope`, `pipeline[]`, `artifacts[]`, `warning_counts`다. `collection_scope`는 `window_from?`, `window_to?`, `timezone`, `business_area?`, `pre_spec_available?`, `pre_spec_reason?`, `focus_axes[]`, `performance_reference_count?`다. pipeline item은 `name`, `status`, `artifact?`, `script?`, `execution_id?`, `started_at?`, `finished_at?`, `exit_code?`, `execution_allowed`, `message?`다. artifact item은 `name`, `present`, `schema_version?`, `expected_schema_version?`, `valid?`, `warnings[]`다. legacy `status`들은 wire enum으로 강제되지 않는 string이다.
- `RunStatsResponse`: `run_id`, `timezone`, `generated_at`, `collected_count?`, `candidate_count?`, `sample_count`, `priority_review_count`, `audit_missed_count`, `funnel[]`, grade/readiness/focus `*_distribution[]`, `verification_requests[]`, `imminent_deadlines[]`. funnel item은 `key`, `label`, `count?`; distribution item은 `key`, `label`, `count`; verification request는 `item`, `count`, `notice_pks[]`, `profile_sections[]`; deadline item은 `NoticeListItem` 전체와 `blocking_verification_items[]`다.
- `WarningListResponse`: `run_id`, `items[]`, `total`, `level?`, `code?`. warning item은 `id`, `run_id`, `level`, `code`, `message`, nullable opaque JSON `context?`다. `level`은 legacy wire에서 enum으로 강제되지 않는다.
- `NoticeDetailResponse`는 `NoticeListItem` 전체와 `bid_no?`, `bid_ord?`, `source_type?`, `budget?`, `method?`, `url?`, `timezone`, nullable opaque JSON `procurement_class?`, `region_limit?`, `lifecycle?`, `qualification_flags?`, opaque JSON list `focus_matches[]`, `performance_matches[]`, `candidate_sources[]`, `performance_top_score?`, `judgment?`, `attachments[]`, `reviews[]`다.
  - `lifecycle`·`procurement_class`는 opaque JSON이며 서버 schema 검증이 없다. 사전규격 수집기가 채우는 알려진 키는 `lifecycle.pre_spec_no`, `lifecycle.bid_ntice_no_list`(문자열 그대로, 분할하지 않음), `lifecycle.changed_at`, `lifecycle.change_reason`, `procurement_class.detail`·`code`다. 화면은 문자열인지 확인해 읽으며 키가 없거나 형식이 다르면 `미확인`으로 남긴다. 특히 본공고 번호 미확인은 본공고가 없다는 뜻이 아니다.
- `JudgmentResponse`: `id`, `schema_version?`, `grade?`, `readiness?`, `primary_focus?`, `exclusion_category?`, `summary?`, `next_action?`, `perspectives[]`, `counterarguments[]`, `verification_items[]`, `matched_performances[]`. perspective는 `id`, `position?`, `name?`, `assessment?`, `reason?`, `evidence[{id,source?,status?,fact?}]`; counterargument는 `id`, `position?`, `text?`; verification item은 `id`, `item?`, `why?`, `blocking`, `status?`; matched performance는 `id`, `name?`, `match_reason?`, `mismatch_or_limit?`, `source?`, `status?`다. 이 legacy 문자열도 wire enum으로 강제되지 않는다.
- `RelatedNoticeListResponse`: `notice_pk`, `items[]`; item은 `relation=ordinal|unified|pre_spec`, `notice_pk`, `notice_key`, `title?`, `grade?`, `published_at?`, `change_reason?`다. `NoticeHistoryResponse`는 `notice_key`, `items[]`; history item은 `notice_pk`, `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `grade?`, `readiness?`, `focus?`, `summary?`, `corrected_grade?`, `corrected_readiness?`, `review_reason?`다.
- `NoticeRevisionHistoryResponse`는 정확히 `notice_pk`, `judgments[]`, `reviews[]`를 갖는다. judgment item은 `id`, `sequence>=1`, `source_kind=runtime|legacy_import|carry_over`, nullable `run_id`, nullable `recording_execution_id`, nullable `source_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. review item은 `id`, `sequence>=1`, `source_kind=human|legacy_import`, nullable `run_id`, nullable `judgment_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. `origin_execution_id`는 judgment 승계 chain 또는 review가 고정한 exact judgment revision의 runtime root이며, legacy/unaligned 이력은 `null`이다.
- `OpportunityListResponse`는 `section_counts`, `action_reason_counts`, `items`, `total`, `limit`, `offset`이다. 기본 목록에는 `merged_into_opportunity_id`가 없는 active row만 포함한다. item은 `id`, `tracking_status=미선택|계속 추적|보류|종료`, `tracking_reason?`, `tracking_selected_by?`, `tracking_selected_at?`, `recheck_signal`, `recheck_signal_at?`, `recheck_signal_link_id?`, `first_registered_stage=order_plan|pre_spec|bid_notice`, nullable `merged_into_opportunity_id`·`merged_at`·`merge_reason`, `section?`, `action_reasons[]`, nullable `hold_review_due_at`, `links[]`다. `first_registered_stage=order_plan`이면 화면 의미는 `추적`, 그 밖의 `pre_spec|bid_notice`이면 `신규`이며 이 매핑을 화면이 다시 정하지 않는다. `section_counts`는 `조치 필요`·`추적 중`·`보류`·`추적 종료`·`신규 입찰공고`·`미결정` 6키다. `action_reason_counts`는 `new_link`·`candidate_pending`·`merge_confirmation`·`blocking_item`·`hold_overdue` 5키이며 현재 활성 `reason` 필터만 뺀 조건으로 센다(spec §7.4). 구역·사유 정의는 아래 "사업기회 구역·사유·보류 기한" 절을 따른다.
- `OpportunityDetailResponse`는 위 사업기회 field와 `links[]` 전체를 반환한다. link는 `id`, `stage=order_plan|notice`, `link_type=official|candidate`, `status=확정|후보 확인 대기|사람 확인 완료|검색 미확인|사람 확인 병합`, `search_strategy?=full|breaking_split|normalized|longest_fragment|prefix12|merge_confirmation`, `attempted_strategies[]`, `agency_match?`, `last_searched_at?`, `evidence_external_no?`, `evidence_bid_no?`, `search_target_kind?=pre_spec|bid_notice`, `human_decision?`, `reviewer_name?`, `reviewed_at?`, `review_reason?`, `record_type?`, `record_id?`, `notice_id?`, `order_plan_id?`, `source_type?`, `title?`, `agency?`, `external_id?`, `record_external_id?`다. `검색 미확인` link도 포함하며 이 상태를 `사전규격 없음`으로 변환하지 않는다. `사람 확인 병합`은 병합으로 끝난 후보 수락 link(비소유, `human_decision=accepted`)이고, `search_strategy=merge_confirmation`은 사람 상태가 있는 사업기회끼리 자동 병합을 거부해 만든 `후보 확인 대기` link다(spec §3.2·§3.3). `search_target_kind`는 `검색 미확인` link가 어느 종류를 찾다 실패했는지 구분한다. target이 있으면 `title`·`record_external_id`가 해당 공고 또는 발주계획을 가리키고, `id`와 `evidence_external_no`로 link 자체와 근거 번호를 식별한다. raw record, filesystem path, object-store metadata는 반환하지 않는다.
- `TrackingStatusUpdateRequest`는 body의 `tracking_status`와 nonblank `reason`만 받는다. actor는 body에 두지 않고 `X-BidOps-Actor-Name` header에서 얻는다. `tracking_status`는 위 네 값만 허용하며 서버 시각을 `tracking_selected_at`으로 기록한다. `미선택`으로 되돌릴 때 현재 row의 작성자·이유·시각은 null이지만 감사 이벤트에는 남는다. `status`·`tracking_reason`는 이전 호출자와의 호환 입력 alias이며 새 client는 canonical field를 사용한다.
- authoritative opportunity link는 `(official + 확정)` 또는 `(candidate + 사람 확인 완료 + human_decision=accepted)`뿐이다. 후보 대기·거절·검색 미확인은 소유권과 자동 병합에 사용하지 않고 이력으로 보존한다. `PATCH /api/opportunities/links/{link_id}/decision`은 actor header와 `{decision: accepted|rejected, reason}`을 받아 후보 판정·검토 시각·감사 이벤트를 같은 transaction에 기록한다. 같은 reviewer·decision·reason 재전송은 기존 결과를 반환하고 다른 재판정은 409다.
- `AttachmentProcedureResponse`: `notice_pk`, `agency?`, `bid_no?`, `title?`, `status`, `matched_portal?`, `search_url?`, `portal_message`, `steps[]`, `attachments[]`. 현재 producer의 status는 `missing|provided|completed`이지만 legacy schema는 일반 string으로 받는다. `AttachmentQueueResponse`는 `run_id`, `total`, `items[]`; item은 `NoticeListItem` 전체와 `bid_no?`, `matched_portal?`, `search_url?`, `portal_message`다.
- `ValidationMetricsResponse`: `run_id`, `metrics[]`. metric은 `key`, `label`, `value?`, `percentage?`, nullable opaque JSON `threshold?`, `meets_threshold?`, `status=pass|fail|measured|not_measurable`, `basis`, `reason?`; basis는 `numerator`, `denominator`, opaque JSON object `detail`이다.
- `ProfileSectionsProjectionResponse`: `schema_version=bidops.profile-projection.v1`, `profile_version`, `profile_digest`, `sections[]`, `status_counts`, `error_codes[]`. section은 `id`, `number?`, `title`, `heading`, `level`, `state=confirmed|inferred|unknown|mixed|unrecorded`, `status_counts`, `items[]`, `error_codes[]`, `children[]`다. item은 `key`, `label`, `section_id`, `section_number?`, `status=confirmed|inferred|unknown`, `value?`다.
- `ProfileUnknownsProjectionResponse`: 같은 schema·profile binding, `items[]`, `total`, `reference_fields`, `error_codes[]`. item은 `key`, `label`, `section_id`, `section_number?`, `section_title`, `status=unknown`, `value?`, `reference_count?`, `reference_status=counted|unavailable`다. 두 projection은 filesystem `source`, source line, `raw_blocks`, `raw`, 자유 형식 `parse_errors`를 허용하지 않는다. 절 구조화 실패의 위치는 section `id`·`number?`·`title`·`heading` 요약으로만 제공한다. `error_codes`는 `profile_snapshot_unavailable|profile_source_unavailable|profile_yaml_unclosed|profile_yaml_invalid|profile_section_unstructured|profile_references_unavailable` 중 하나이며 예외 문자열을 포함하지 않는다.
- snapshot list item은 `version`, `digest`, `source_kind=working_tree|git_blob`, `created_at`를 반환한다. `source_kind=git_blob`일 때만 `source_ref`에 40자 lowercase commit SHA가 추가되며, `working_tree`의 저장소 상대 경로 `source_ref`는 wire에서 생략하고 내부 provenance로만 보존한다.
- 이전 profile wire의 `source`, source line, `raw_blocks`, `raw`, `parse_errors`, working-tree `source_ref`는 역사적 구현 사실일 뿐 현재 응답에는 더 이상 포함되지 않는다.
- `PipelineExecutionResponse`: `execution_id`, `source_run_id`, `result_run_id?`, `stage`, `status`, start/finish, `exit_code?`, `error?`, `log_count`. log 응답은 `run_id`, `executions[]`, `items[{timestamp,stream,level,message}]`, `total`이다.
- screening create request는 `policy_version`, `profile_source=current|git:<40 lowercase hex>`, `requested_by`다. stop request는 `requested_by`다.
- `ScreeningExecutionResponse`: `queue_no`, `execution_id`, `trigger=cli_single|manual_run|quality_gate|schedule`, `source_run_id`, `scope=single_notice|full_run|quality_sample`, `notice_id?`, `status=대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`, `requested_by`, `policy_version`, `prompt_version`, `model_name`, `model_digest`, `company_profile_version`, `company_profile_digest`, `generation_config`, `generation_config_digest`, `input_artifact_digest`, `queued_at`, `started_at?`, `finished_at?`, `heartbeat_at?`, `stop_requested_at?`, `stop_requested_by?`, `stop_reason=user_requested|process_interrupted|null`, `candidate_count`, `completed_count`, `failure_count`, `published_run_id?`, `error_summary?`, `queue_position?`, `current_notice_id?`, `current_stage?`, `result_urls`. result URL field는 nullable `decisions`, `failures`, `telemetry`, `screening_result`, `published_run`이며 non-null 값은 `/api/`로 시작한다.
- execution은 `single_notice`일 때만 `notice_id`를 갖는다. `대기`일 때만 `queue_position`이 필수이며, `중지 요청`은 요청 시각·actor를 필요로 한다. terminal `성공|부분 성공|실패|중단됨`은 `finished_at`이 필수다. model/profile/generation/input digest는 64자 lowercase SHA-256이고 profile version과 digest는 서로 일치한다.
- `current_stage`는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|merge|publish|null`이다. `ScreeningExecutionDetailResponse`는 execution field 전체와 `attempts[]`, `failures[]`다. attempt는 `attempt_id`, `execution_id`, `notice_id`, `stage`, `attempt_no`, `status=success|failure`, `failure_type?`, `done_reason?`, `trace_id`, `span_id`, `prompt_eval_count?`, `eval_count?`, `prompt_eval_duration_ns?`, `eval_duration_ns?`, `load_duration_ns?`, `total_duration_ns?`, `generation_config_digest?`, `num_ctx?`, `num_predict?`, `started_at`, `finished_at`, `error_summary?`다. OpenAI 호환 transport로 통일한 뒤([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)) `done_reason`은 provider의 `finish_reason`을 담고 `prompt_eval_count`·`eval_count`는 `usage.*`에서 온다. **`*_duration_ns` 네 열은 항상 `null`이다** — 응답에 서버 측 소요 시간 계측이 없고, client 측 경과 시간으로 채우면 과거 회차의 계측과 뜻이 다른 숫자가 같은 열에 섞이기 때문이다. 0으로 바꾸지 않는다. attempt stage는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|carried_over_validation`이다.
- failure는 `notice_id`, `failed_stage=기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|반론 검토|종합 판정|병합·검증`, `failure_type=timeout|truncated_output|schema_violation|evidence_missing|counterargument_repetition`, `last_attempt_at`, `retry_count`, `status=사람 검토 대기`, `failure_context=carried_over_validation|null`, `trace_id?`, `span_id?`, `error_summary`다. success attempt에는 failure type이 없고 failure attempt에는 필수다.
- quality gate create request는 `purpose=model_comparison|operational_approval`, `policy_version`, `profile_source`, `created_by`다. comparison은 고정 역사 Git profile, approval은 `current`만 허용한다. review upsert는 `reviewer`, `evidence_judgment=동의|근거 부족|판단 보류`, optional note다.
- `QualityGateResponse`: `gate_id`, `purpose`, `execution_status=대기|실행 중|완료|실패|중단됨`, `result_status=통과|미달|미측정|보류`, `baseline_run_id`, `sample_artifact_digest`, `baseline_decisions_digest`, `policy_version`, `prompt_version`, `model_name`, `model_digest`, `company_profile_version`, `company_profile_digest`, `generation_config`, `generation_config_digest`, `pass_a_execution_id`, `pass_b_execution_id`, `created_by`, `created_at`, `completed_at?`, `latest_evaluation_id`, opaque `metrics`, `reasons[]`. terminal execution은 completion time이 필수이고 비terminal에는 없으며 pass A/B ID는 다르다.
- `QualityGateDetailResponse`는 gate field 전체와 `pass_a`, `pass_b`, `evaluations[]`, `reviews[]`다. evaluation은 `evaluation_id`, `gate_id`, `revision`, `result_status`, opaque `metrics`, `reasons[]`, `valid_review_count`, `distinct_notice_review_count`, `generation_config`, `generation_config_digest`, `created_at`이다. review는 `review_id`, `gate_id`, `execution_id`, `notice_id`, `decision_digest`, `reviewer`, `evidence_judgment`, `note?`, `created_at`, `updated_at`이다.
- policy create request는 `policy_version`, `created_by`, `prompt_version`, 정확히 다섯 perspective prompt object, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`를 가진다. candidate request는 `confirmed_by`, activation request는 `quality_gate_result_id`와 `confirmed_by`다. `PolicyVersionResponse`는 `schema_version=bidops.screening-policy.v1`, `policy_version`, `prompt_version`, `perspective_prompts`, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`, `content_digest`, `status=draft|activation_candidate|active`, `created_at`, `created_by`, `activated_at?`, `activated_by?`, `quality_gate_result_id?`다. active일 때 activation metadata 세 field는 모두 필수이고 나머지 status에서는 모두 null이다. activation response는 `policy`, `previous_active_policy_version?`, `quality_gate_result_id`, `activation_status=activated`, `activated_at`이다.
- schedule settings update는 optional nullable `daily_time`, `weekly_time`, `prespec_enabled` 중 non-null 하나 이상과 required `updated_by`가 필요하다. 시각은 24시간 `HH:MM`이다. `ScheduleSettingsResponse`는 `timezone=Asia/Seoul`, `daily_time`, `weekly_time`, `prespec_enabled`, `updated_at`, `updated_by`다. schedule execution create는 `job_kind=daily|weekly`, `window_from`, `window_to`, optional nullable `recovery_of_execution_id`, required `requested_by`다. daily window는 하루, weekly는 월→일 7일이다.
- `ScheduleExecutionSummary`: `run_key`, `run_id?`, `window_from`, `window_to`, `job_kind`, `status=예약|실행 중|성공|부분 성공|실패|건너뜀`, `execution_id`, `trigger=schedule|manual`, `duplicate_of_execution_id?`, `recovery_of_execution_id?`, `skip_reason?`, `failure_reason?`, `requested_by`, `started_at?`, `finished_at?`, `candidate_count?`, `result_count?`, `failure_count?`, `partial_artifact?`, `policy_version?`, `model_name?`, `model_digest?`, `prompt_version?`, `company_profile_version?`, `company_profile_digest?`, `generation_config?`, `generation_config_digest?`다. daily run key는 `YYYYMMDD-YYYYMMDD`, weekly는 `weekly:YYYYMMDD-YYYYMMDD`다. duplicate와 recovery는 동시에 있을 수 없고 duplicate는 `건너뜀`+필수 skip reason, recovery는 manual trigger다. profile·generation binding은 각각 pair다. list는 `items,total,limit,offset`이다.
- always-on update는 `enabled`, `confirmed_by`, optional nullable `quality_gate_result_id`이며 enabled일 때 gate ID가 필요하다. `AlwaysOnSwitchResponse`는 `configured_enabled`, `effective_enabled`, `environment_enabled`, `quality_gate_status?`, `quality_gate_result_id?`, `policy_version?`, `model_name?`, `model_digest?`, `prompt_version?`, `company_profile_version?`, `company_profile_digest?`, `generation_config?`, `generation_config_digest?`, `updated_at`, `updated_by`, `rejection_reason?`다. profile version·digest와 generation config·digest는 각각 둘 다 있거나 둘 다 null이어야 한다.

## 구현된 계약 — 입찰 delta와 최종 결정 (R-07 채택, R-08 구현)

이 절은 [ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md)와
[OpenAPI·DB 명세](bid-delta-contract-spec.md)로 채택하고 R-08에서 구현한 계약이다.
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
같은 값을 쓴다. 상세 wire shape·오류 표는 [입찰 delta 계약 명세](bid-delta-contract-spec.md)와
[심층 검토 ERD](deep-review-erd.md) §8.6, 결정 배경은 [ADR-0058](tracking/decisions/0058-final-decision-basis-separated-from-comparison.md)이 정본이다.

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

아래 경로는 세 도메인 모듈을 모두 등록한 기본 기동(`BIDOPS_MODULES` 미지정)의 표면이다. `BIDOPS_MODULES`로 모듈을 꺼서 기동하면 그 모듈이 소유한 경로는 등록되지 않아 404이며, `GET /api/health`는 어떤 조합에도 있다([ADR-0045](tracking/decisions/0045-backend-module-layout.md)). 경로·입력·응답 자체는 모듈 선택과 무관하게 이 절의 계약 그대로다.

### 상태, 회차, 공고

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/health` | 없음 | `{"status":"ok"}` | 프로세스 불가용 |
| `GET /api/workload` | 없음 | `WorkloadResponse` — 집계 시각과 고정 순서 네 항목 | 제공자 부재는 200의 null·사유 |
| `GET /api/runs` | 없음 | `{items: RunSummary[], total}` 전체 회차 | 없음 |
| `POST /api/runs/ingest` | body 또는 query의 run ID | 적재·재적재 건수와 경고 | 404 run directory, 422 run ID 부재 |
| `GET /api/runs/{run_id}` | path run ID | `RunDetailResponse` | 404 |
| `GET /api/runs/{run_id}/stats` | path run ID | `RunStatsResponse`; 계산 불가 count는 null | 404 |
| `GET /api/runs/{run_id}/warnings` | path run ID; optional query `level`, `code` | `WarningListResponse` | 404 |
| `GET /api/runs/{run_id}/pipeline/logs` | path run ID; optional query `execution_id` | `PipelineLogResponse` | 404 |
| `POST /api/runs/{run_id}/pipeline/{stage}` | `stage=collect|sample|report`; optional query `from_raw=false` 또는 optional body `{from_raw:false}` | 202 `PipelineExecutionResponse` | 400 입력·stage, 404 run, 409 active 충돌, 422 body·query |
| `GET /api/notices` | `NoticeList` query | `NoticeListResponse` | 404 run, 422 query |
| `GET /api/pre-specs` | 누적 `PreSpecList` query; 기본 `sw_only=true`; optional `auto_preparation_status` | `PreSpecListResponse` | 422 query |
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
| `GET /api/opportunities` | optional `tracking_status`, `first_registered_stage`, `section=조치 필요\|추적 중\|보류\|추적 종료\|신규 입찰공고`, `reason=new_link\|candidate_pending\|merge_confirmation\|blocking_item\|hold_overdue`, `hold_review=overdue\|due_soon\|attention`, `q`(2~100자), `sort=created_at\|tracking_status\|first_registered_stage\|hold_review_due_at`, `limit` 1..500(default 50), `offset` 0 이상 | `OpportunityListResponse`(`section_counts`·`action_reason_counts` 포함); 기본값은 `종료`를 포함한 전체 | 422 query(`section=미결정`은 집계 전용이라 값 자체를 거부) |
| `GET /api/opportunities/{opportunity_id}` | path DB integer opportunity ID | `OpportunityDetailResponse`; `검색 미확인` link를 포함한 전체 link 목록 | 404 `opportunity_not_found` |
| `GET /api/opportunities/{opportunity_id}/deep-reviews` | path DB integer opportunity ID | 200 `{opportunity_id, items[]}` — 연결 공고 전체의 심층 검토 목록 | 404 `not_found`; 422 path; 500 `processing_failed` |
| `GET /api/opportunities/{opportunity_id}/tracking-decisions` | path DB integer opportunity ID | 200 `{opportunity_id, items[], recheck_events[]}`; `items`는 append-only 추적 결정 이력, `recheck_events`는 신호 생성·확인·해제를 감사에서 투영한 이력(`kind=created\|acknowledged\|cleared_by_decision`, `link_id?`, `actor_kind`, `claimed_name?`, `created_at`, `note_present`) | 404 `opportunity_not_found` |
| `POST /api/opportunities/{opportunity_id}/recheck-acknowledgements` | actor headers; body `{expected_link_id, note?(≤500자)}` | 200 `OpportunityDetailResponse`; 신호를 해제하고 추적 상태는 바꾸지 않음 | 400 `actor_name_required\|actor_name_invalid`; 404 `opportunity_not_found`; 409 `recheck_signal_absent`(신호 없음)·`recheck_signal_changed`(근거 링크가 바뀜, details `{current_link_id}`)·`opportunity_merged`; 422 body |
| `POST /api/opportunities/{opportunity_id}/searches` | actor headers; body `{target=pre_spec\|bid_notice}` | 200 `OpportunitySearchResponse`(`searched_at`, `target`, `attempted_strategies[]`, `candidates: OpportunityLinkView[]`, `search_unconfirmed`) | 400 actor; 404 `opportunity_not_found`; 409 `opportunity_merged`; 422 `search_source_missing`(소유 발주계획·사전규격 없음)·body |
| `GET /api/pre-specs/{notice_pk}/order-plan-candidates` | path DB integer notice PK | 200 `PreSpecOrderPlanCandidatesResponse`(`notice_pk`, `items[]`; item은 `link`, `opportunity_id`, `tracking_status`, `order_plans[]` 발주계획 요약) | 404 사전규격 없음 |
| `GET /api/bid-delta/decision-queue` | `status=pending\|all`(기본 `pending`), `limit` 1..500(기본 50), `offset` 0 이상 | 200 `{items, total, limit, offset}` | 422 query; 500 안전 오류 |
| `POST /api/opportunities/order-plan-tracking/preview` | body `{"schema_version":"order-plan-bulk-preview-request.v1","order_plan_ids":[1,2]}` (ID는 positive integer[]); 빈 목록·bool·0·음수·unknown field 거부 | 200 `order-plan-bulk-preview-response.v1` (아래 wire) | 422 body 또는 `invalid_request`; 503 `temporarily_unavailable` |
| `POST /api/opportunities/order-plan-tracking/bulk-start` | actor headers; body `{"schema_version":"order-plan-bulk-start-request.v1","request_id":"UUID","order_plan_ids":[1,2],"reason":"nonblank"}` (ID는 positive integer[]) | 200 `order-plan-bulk-start-response.v1` 최종 receipt (아래 wire) | 400 actor; 409 `idempotency_conflict`; 422 body/`invalid_request`·`tracking_reason_required`; 500 `processing_failed`; 503 `temporarily_unavailable` |
| `POST /api/opportunities/order-plan-tracking/bulk-end` | actor headers; body `{"schema_version":"order-plan-bulk-end-request.v1","request_id":"UUID","order_plan_ids":[1,2],"reason":"nonblank"}` (ID는 positive integer[] 1..200건) | 200 `order-plan-bulk-end-response.v1` 최종 receipt (아래 wire) | 400 actor; 409 `idempotency_conflict`; 422 body(201건 이상은 FastAPI `too_long`)/`invalid_request`·`tracking_reason_required`; 500 `processing_failed`; 503 `temporarily_unavailable` |
| `PATCH /api/opportunities/{opportunity_id}/tracking-status` | actor headers; body `{tracking_status, reason}` | 200 `OpportunityDetailResponse` | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_not_found`; 422 `tracking_status_invalid|tracking_reason_required` |
| `PATCH /api/opportunities/links/{link_id}/decision` | actor headers; body `{decision=accepted|rejected, reason}` | 200 `OpportunityLinkView`; 동일 actor·판정·이유 replay는 같은 reviewed_at | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_link_not_found`; 409 `candidate_link_required|candidate_decision_conflict|candidate_state_conflict|candidate_target_required|candidate_target_already_authoritative|candidate_merge_state_conflict|opportunity_merge_state_conflict`; 422 body·link ID·blank reason |

추적 상태 변경은 `set_tracking_status()`를 통해 사람 선택과 감사 이벤트를 함께 기록한다. `X-BidOps-Actor-Name`은 인증이 아닌 감사 표식이며, 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 사용한다. `recheck_signal`은 시스템 신호 여부이고 `recheck_signal_at`·`recheck_signal_link_id`는 그 시각과 근거 link를 가리킨다. 이 값들은 사람의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at`과 별도이며, `FinalOpinion` 또는 최종 입찰 `Go/No-Go`로 변환하지 않는다.

후보 수락(`PATCH …/links/{id}/decision` `accepted`)이 대상을 이미 소유한 다른 active 사업기회로 이끌면 §3.2와 같은 규칙으로 병합한다. 사람 상태 보유(`tracking_status ≠ 미선택` 또는 `recheck_signal_at IS NOT NULL`) 사업기회가 둘 중 1개 이하면 병합하고 후보 link를 `사람 확인 병합`(비소유, `human_decision=accepted`)으로 남긴다 — 소유권은 옮겨진 공식 link가 갖는다. 둘 다 사람 상태를 가지면 409 `candidate_merge_state_conflict`이고 details는 `{opportunities: [{id, tracking_status, tracking_selected_by, tracking_selected_at, recheck_signal}]}`다. 자동 병합(공식 키 재적재)이 같은 조건으로 막히면 경고 `opportunity_merge_confirmation_required`와 함께 `병합 확인` 후보(`search_strategy=merge_confirmation`)를 만들며, 도착 레코드는 고아로 남지 않고 자기 사업기회(없으면 새로 생성)에 붙는다.

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

#### 발주계획 일괄 추적 v1 wire·원자성

두 POST는 RuntimeContractModel의 v1 field만 받는다. 계획 ID는 서버에서 중복 제거하고
오름차순으로 정규화하므로 preview와 receipt의 `items` 순서도 그 순서다. preview는 계획
존재·authoritative active owner(공식 확정 또는 사람 accepted 후보)·현재 상태만 set 조회하며
추적·감사·receipt·모델 실행을 만들지 않는다. 미리보기 뒤 상태가 바뀔 수 있으므로 bulk-start가
잠금 뒤 다시 확인한 결과가 최종이다.
bulk-start body에는 임의 status나 owner ID가 없고 목표 상태는 고정 `계속 추적`이다.

bulk-end([ADR-0063](tracking/decisions/0063-order-plan-bulk-tracking-end.md))는 bulk-start와 같은 상태 기계를 목표 상태만 바꿔 쓴다.
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
옮기고, native checkbox 또는 활성 행의 plain Space만 checked membership을 한 번 토글한다.
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

[ADR-0053](tracking/decisions/0053-decision-workload-read-contracts.md)의 읽기 전용 계약이다. 세 경로 모두 DB 열을 새로 만들지 않고 기존 목록과 **같은 모집단**을 센다.

- `WorkloadResponse`: `generated_at`(UTC aware)과 `items[]`. item은 `key`, nullable `count`(0 이상), nullable `unavailable_reason` 셋뿐이다. `items`의 순서는 고정이며 `order_plan_pending`, `pre_spec_deep_review_ready`, `tracking_action_required`, `tracking_hold_review_due`, `bid_final_decision_pending` 다섯이 언제나 모두 있다(ADR-0053 §1·§4 갱신, spec §8).
- **제공자 부재와 실제 0은 다르다.** 소유 모듈이 등록되지 않았으면 `count=null`·`unavailable_reason="provider_absent"`이고, screening이 있어도 누적 범위(아래 "발주계획 목록 누적 모드")에 완료된 C-2 운영 실행이 하나도 없으면 `count=null`·`unavailable_reason="no_completed_execution"`이다. 오늘 실행이 없다는 이유로 `null`이 되지 않는다. 셀 수 있었다면 정수와 `unavailable_reason=null`이다. `null`을 0으로, 0을 `null`로 접지 않는다.
- 각 건수의 소유자는 모듈이다. `order_plan_pending`은 screening이 `GET /api/order-plans`의 누적 모드(`source_run_id` 없음) 범위와 같은 필터(`stage1_status=selected`, `qwen_relevance=relevant,uncertain`, `tracking_status=미선택`)로, `pre_spec_deep_review_ready`는 deep_review가 `GET /api/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false`와 같은 집합으로, `bid_final_decision_pending`은 deep_review가 `GET /api/bid-delta/decision-queue?status=pending`의 `total`과 같은 값으로 센다. `tracking_action_required`와 `tracking_hold_review_due`는 lifecycle이 각각 `GET /api/opportunities`의 `조치 필요` 구역, `hold_review=overdue` 건수와 같은 첫 일치 규칙으로 직접 센다.
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

## 사전규격 개요 검토 (MVP, 2026-09-11)

v3 권고형 개요, legacy v4 단일 호출 개요, v5 주장 검증 스택(activation v2·call
ledger·verification)은 폐기했다([ADR-0054](tracking/decisions/0054-prespec-overview-mvp-rewrite.md)).
`prespec_overview_run` 단일 테이블과 `bidops.prespec-overview.v1` 계약으로 다시 쓴다. 첨부
취득·묶음·자동 준비·document_mcp 변환·PDF/쪽 텍스트 스냅샷(`prespec_v4_pdf_snapshot`,
migration 0021/0023/0024)과 주장 결정적 검증 함수는 그대로 유지한다.

### 설정

- `BIDOPS_PRESPEC_OVERVIEW_ENABLED`(bool, 기본 `false`). `true`면 묶음이 ready가 될 때 개요
  run을 자동 enqueue한다. `false`면 enqueue하지 않고 queued run은 `cancelled`로 닫는다.
  이미 `running`인 run은 끝까지 진행한다. `true`인 동안에는 자동 준비와 개요 enqueue의 등급
  조건이 "effective grade `우선 검토` **또는** `SW사업대상=Y`"로 완화된다(2026-09-11 MVP 결정).
  운영 DB에 C-1 판정이 0건이라 `우선 검토`가 없으면 개요를 한 번도 실행할 수 없기 때문이며,
  플래그가 `false`면 완화 없이 기존 등급 규칙만 적용한다.
- `BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH`(기본 `app/deep_review/policies/prespec-overview-policy-v7.json`).
  v7은 개요를 **앞부분 요약 세 절**로 좁힌다([ADR-0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md)).
  v6 파일은 그 정책으로 만든 기존 run의 기록으로 남기지만 현재 loader는 v7만 읽는다.

### 상태 의미

| status | 뜻 | 자동 심층 검토 |
|---|---|---|
| `queued` / `running` | 대기·실행 중 | 대기 |
| `completed` | 남은 주장이 결정적 검사·의미 검토를 통과, `result_json` 있음 | 진행 가능 |
| `needs_human_review` | 통과 주장이 절반 미만·주장 0개(`claims_empty`)·주장/분석의 의미 검토 contradicted/insufficient | `overview_not_completed` |
| `failed` | 기술 실패(`reason_codes`: `pdf_preparation_failed:<code>`, `manifest_invalid`, `draft_format_retry_exhausted`, `semantic_schema_invalid`, `semantic_missing_ids`, `semantic_duplicate_ids`, `semantic_response_invalid`, `timeout`, `input_capacity_exceeded`, `call_budget_exhausted`, `response_store_unavailable`, `lease_expired`, `runner_failed`) | `overview_not_completed` |
| `cancelled` | 플래그 off로 닫힘 | `overview_not_completed` |

종결 사유 코드 중 실행 자체가 막혀 닫는 세 가지는 다음과 같다.

| reason code | 닫히는 status | 뜻 |
|---|---|---|
| `attempts_exhausted` | `failed` | `work_job.max_attempts`를 이미 쓴 queued run을 claim하지 않고 닫았다 |
| `identity_unavailable` | `failed` | 모델 신원 확인이 연속으로 막혀 남은 시도를 다 썼다 |
| `operator_close` | `queued`→`cancelled`, `running`→`failed` | 운영자가 `close-overview-run`으로 닫았다 |

공고의 "현재 개요"는 `created_at` 최신 run이다. 이력은 그 공고의 모든 run.
목록·상세의 `overview_review_status`는 최신 run의 status를 그대로 쓰고, run이 없으면 `null`이다.
자동 심층 검토 사유 판정 순서는 `not_sw_business → bundle_not_auto_ready →
overview_not_completed → service_unavailable → 회사 핏 사유`다. `overview_recommendation_closed`·
`overview_bundle_mismatch`는 삭제됐다.

### REST (`bidops.prespec-overview.v1`)

| 경로 | 응답 |
|---|---|
| `GET /api/pre-specs/{notice_id}/overview` | `{schema, notice_id, current: Run\|null, history: Run[], range_review: RangeReview\|null, verification: Verification\|null}` |
| `POST /api/pre-specs/{notice_id}/overview/range-confirmations` | body `{page_start, page_end, note?}` **또는** `{candidate_indices: [시작 index, 끝 index], note?}`(둘을 함께 보내면 `range_invalid`), `X-BidOps-Actor-Name` 헤더(비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent`). 409 `run_active`(queued/running 있음), 409 `document_not_current_safe`, 422 `range_invalid\|candidate_range_incomplete\|candidate_range_unavailable`. 201 `{run_id, attempt_enqueued: true, page_start, page_end}` |
| `GET /api/pre-specs/{notice_id}/overview/runs/{run_id}/pdf` | 그 run이 읽은 고정 스냅샷 PDF. 404/409 safe 오류 |
| `GET /api/pre-specs/{notice_id}/overview/snapshot/pdf` | run이 없어도 여는 최신 고정 스냅샷 PDF(범위 확정용). run PDF와 같은 경계. 404 `not_found`, 409 `document_not_current_safe`, 503 `pdf_unavailable` |

절 후보 index로 확정하면 서버가 쪽으로 바꾼다: 시작은 고른 절의 쪽, 끝은 **다음 절의 쪽**(마지막
절이면 문서 끝 쪽)이다. 화면은 이 계산을 하지 않는다. 후보가 일부만 있으면
`candidate_range_incomplete`, 후보를 읽을 수 없으면 `candidate_range_unavailable`이며 둘 다
사람이 쪽 범위를 직접 넣어야 한다.

Run 응답 필드: `id, status, range_source(auto|fallback|human), page_start, page_end,
range_reason_codes, reason_codes, warnings, result(완료 시:
business_overview/main_tasks/budget_and_period 각
[{claim_id,text,evidence:[{page,quote}]}], input_limitations[]),
failed_claims(`completed`·`needs_human_review` 모두:
[{claim_id,section,text,reason_codes,evidence}]), model_name, model_revision,
call_count, actor_name, created_at, started_at, completed_at`. 모델 원문·`raw_response_refs`·
내부 경로는 반환하지 않는다.

Run의 파생 필드(저장 값을 옮긴 것이며 새 판정이 아니다):

| 필드 | 값 |
|---|---|
| `result_id` | `completed`면 run id, 그 밖에는 `null` |
| `prompt_version` | 정책 문서의 `prompt_version`. 정책을 읽을 수 없으면 `null` |
| `verification_status` | `checks_json`이 있으면 `passed\|needs_human_review`, 없으면 `null` |
| `document_version_id` | run이 읽은 문서 |
| `source_sha256`·`pdf_sha256`·`pdf_page_count` | run의 동결 스냅샷 값. 준비 전이면 `null` |
| `reviewed_pages` | `[page_start..page_end]` 정수 배열. 범위가 없으면 `[]` |
| `payload_sha256` | `result_json`의 canonical JSON sha256. 없으면 `null` |
| `quality_status` | `model_name`이 `mock`으로 시작하면 `mock_reference`, 아니면 `unmeasured_reference`. **측정된 품질이 아니다** |
| `validation_status`·`evidence_check_status` | `completed`면 `passed`, 그 밖에는 `failed` |
| `validation_errors`·`evidence_check_errors` | run의 `reason_codes` 배열 |

`range_review`(ready 묶음 RFP 문서의 최신 스냅샷이 없으면 `null`):

| 필드 | 값 |
|---|---|
| `target_id` | 최신 run id. run이 없으면 `null` |
| `status` | 최신 run이 `human`이면 `human_confirmed`; `fallback`이거나 `needs_human_review\|failed\|cancelled`이거나 run이 없으면 `pending`; 그 밖에는 `ready` |
| `document_version_id`·`pdf_page_count` | 스냅샷 값 |
| `mode` | 후보 산출물의 `outline\|clause\|page`. 후보가 없으면 `null` |
| `candidate_status` | `complete\|partial\|unavailable` |
| `candidate_count_total`·`candidate_count_returned` | 후보 산출물의 `section_count`와 반환 수 |
| `candidates` | `[{index(0부터), title, page(1부터), char_count}]` |
| `selected_pages` | 최신 run의 `[page_start, page_end]`. 없으면 `null` |
| `warning_codes` | 후보가 부분이면 `section_candidates_incomplete`, 읽을 수 없으면 `section_candidates_unavailable` |
| `reason_code` | 최신 run의 `range_reason_codes[0]`, 없으면 후보 경고 코드, 그것도 없으면 `null` |
| `can_confirm` | 활성 run이 없고 문서·원본이 지금 current·safe일 때만 `true` |
| `assisted` | 항상 `null`(범위 보조 실행은 MVP에 없다) |
| `confirmation` | 가장 최근 사람 확정 `{page_start, page_end, actor_name, note, created_at}`. `note` 본문은 저장하지 않으므로 항상 `null`이고 없으면 전체가 `null` |

2026-09-16 [ADR-0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md) 결정 1로
`result`에서 `important_conditions`·`reviewer_analysis`·`unknowns` **key가 사라졌다.** 빈 배열이
아니라 key 자체가 없으며, 그 자리는 심층 검토가 갖는다. 저장된 `result_json`의 계약 식별자는
`bidops.prespec-overview-claims.v2`이고 폐기된 `bidops.prespec-overview-page-review.v4`는 더
이상 생산하지 않는다. v4 시절 행은 그대로 두고 읽을 때 세 절만 투영한다.

`verification`(현재 run에 `checks_json`이 없으면 `null`): `{verification_id: run id, status:
passed\|needs_human_review, reason_codes: [], claims: [{claim_id, section, text,
deterministic: {status: passed\|failed, reason_codes: []}, semantic: {status:
supported\|contradicted\|insufficient\|not_run, reason_codes: []}, verified_evidence: [{page,
quote, start_char, end_char}]}]}`. `page_text_sha256`은 내부 결속 값이라 나가지 않는다.

### 실행 흐름

analysis worker의 개요 slot이 enqueue(플래그 on ∧ 활성 run 없음 ∧ effective grade
`우선 검토` ∧ ready 묶음에 RFP 문서) → claim(WorkJob lease 1,200초) →
prepare(snapshot 없으면 `prepare_v4_pdf_snapshot`, 변환 300초) → range(human 확정값 또는
자동 선택, 실패 시 fallback 1쪽~min(60쪽,100,000자)에 `range_fallback_head`; 전 쪽 공백이면
`failed/manifest_invalid`) → draft(1회, 형식 오류 시 1회 재생성) →
deterministic(인용 1곳 대응·페이지 범위·duplicate_id 실패와 주장 0개
(`claims_empty`)는 `needs_human_review`; 섹션 배정·수치·역할·VAT·기산점·date·latin·
requirement_id는 warnings) →
semantic(1회; 남은 주장이 모두 supported면 `completed`) → save 순서로 진행한다. 호출 상한은 attempt당
3회(초안 2, 의미 1)이며 상한을 넘기면 `call_budget_exhausted`로 닫는다. 정책은
`prespec-overview-policy-v7.json`(max_pages 60, max_page_text_chars 100000,
max_prompt_chars 120000, max_claims 12, max_model_context_tokens 393216).
의미 단계 입력에는 `expected_claim_ids`와 `expected_check_count`가 들어가고, 그 run의 응답
schema `checks`는 `minItems=maxItems=expected_check_count`로 좁혀 나간다. 정책 파일의
`max_claims`는 상한 검증으로만 남고 **정책 digest는 바뀌지 않는다.** 문맥 상한 판정은 요청 JSON의 byte 수를 token 상계로 쓰므로
한국어 100,000자 입력이 지나갈 수 있도록 천장을 함께 올렸다. 서버가 `max_model_len`을 내지
않으면 초과 판정을 하지 않고 run의 `warnings`에 `context_unverified`를 남긴다.

결정적 검사에서 `quantity_mismatch`·`quantity_metadata_mismatch`·`quantity_relation_ambiguous`·
`quantity_unit_missing`·`date_mismatch`·`requirement_id_mismatch`·`latin_term_mismatch`·
`required_fact_missing`(섹션 배정 쏠림)·`evidence_fragment_match`(2단 편집 쪽에서 인용을 줄·
리스트 표식·생략 기호(`…`·`...`) 조각으로 나눠 순서대로 대조해 통과)·`evidence_dropped`(인용
둘 중 하나만 `quote_not_found`·`quote_ambiguous`라서 그 인용만 뺐다)는 **비차단 경고**이며
run의 `warnings`에만 남는다. 차단은 `quote_not_found`·`quote_ambiguous`·`quote_empty`·
`page_out_of_range`·`evidence_missing`·`fact_empty`·`duplicate_id`뿐이며, 주장이 한 개도
없으면 run은 `needs_human_review/claims_empty`로 닫는다.

#### 범위 선택 전략과 사유 코드 (2026-09-16)

자동 선택은 **목차 우선**이다(ADR-0057 결정 2). 입력 manifest의 `strategy`는
`toc_scope`(목차 항목의 인쇄 쪽을 본문 제목 대조로 물리 쪽에 맞춰 고름)·`heading_scope`(본문
heading만으로 고름)·`human_confirmed`(사람이 확정한 쪽 span) 셋이다. `range_source`는
그대로 `auto|fallback|human`이며 `toc_scope`·`heading_scope` 모두 `auto`다. 목차 전략은 절 후보를
쓰지 않으므로 절 후보 완결성(`candidates_truncated`)과 무관하게 먼저 시도하며, 후보가 잘렸을 때의
자동 확정 금지(`section_candidates_incomplete`)는 목차가 실패한 뒤의 본문 전략에만 적용한다.

목차 전략이 실패하면 본문 전략으로 내려간다. 실패 사유는 `toc_missing`(앞 5쪽에
"제목 … 쪽번호" 항목이 4개 이상인 쪽이 없음)·`toc_alignment_failed`(인쇄 쪽 → 물리 쪽
offset을 두 장 이상에서 같은 값으로 확정하지 못함)·`toc_target_missing`(시작·끝으로 삼을 장
항목이 없음) 셋이다. **자동 선택이 성공하면 `range_reason_codes`는 비어 있다** — 어느 전략을
썼는지는 manifest `strategy`가 말하며, 성공한 선택에 사유를 붙여 `range_review.reason_code`로
노출하지 않는다. 목차 사유는 최종 결과가 fallback이거나 사람 검토일 때만 본문 사유
(`range_too_small`·`scope_heading_missing` 등) **뒤에** `range_fallback_head` 앞자리로 남는다.

의미 검토 응답에 기대 주장 ID가 모두 정확히 한 번씩 있으면 그 밖의 항목은 무시하고 경고
`semantic_extra_ids`를 남긴다. 누락은 `failed/semantic_missing_ids`, 중복은
`failed/semantic_duplicate_ids`, schema·상한 위반은 `failed/semantic_schema_invalid`다
([ADR-0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md) 결정 3).

선택 범위에 예산·기간이 없어 결과의 절이 비면 run의 `warnings`에 `section_empty:<section>`을
남긴다. 빈 절은 사실이며 채우지 않는다.

#### 부분 완료 (2026-09-11, 2026-09-16 갱신)

주장별 차단 코드는 **그 주장만** 결과에서 뺀다. 통과 주장이 1개 이상이고 전체 주장의
`ceil(n/2)` 이상이면 남은 주장으로 의미 검토·구성을 계속해 `completed`가 되고, 미만이면
`needs_human_review/deterministic_check_failed`로 닫는다. `duplicate_id`처럼 초안 전체에
붙는 코드는 그대로 전체를 닫는다. 주장의 인용이 둘이고 하나만 `quote_not_found`·
`quote_ambiguous`이면 **그 인용만** 빼고 주장은 통과하며 경고 `evidence_dropped`가 남는다.
인용이 모두 어긋나면 종전대로 그 주장이 빠진다. 의미 검토에서 주장이 `contradicted`·
`insufficient`면 `needs_human_review/semantic_review_failed`로 닫는다.

이때 run의 `warnings`에 남는 코드는 `claims_dropped`(주장이 하나 이상 빠짐)·
`evidence_dropped`·`semantic_extra_ids`·`section_empty:<section>`이다.
`draft_json`·`checks_json`은 빠진 주장까지 담은 **전체**를 그대로 저장하며(`failed_claims`
투영이 `checks_json`에서 계산된다), 의미 검토·구성에 쓰는 부분집합은 저장하지 않는다.
`result_json`에는 빠진 주장과 빠진 인용이 들어가지 않는다.

개요 입력 PDF의 원본 위치가 여러 공고에 공유되면(같은 첨부 bytes) `source` 위치가 둘 이상이다.
원본의 정체는 hash이므로 가장 오래된 검증 위치 하나를 고정해 고른다.

### DB: `prespec_overview_run` (migration 0026)

`id, notice_id, document_version_id, snapshot_id?, work_job_id, status, range_source,
page_start?, page_end?, range_reason_codes, input_sha256?, policy_digest, model_name,
model_revision?, draft_json?, checks_json?, result_json?, warnings_json, reason_codes,
call_count, raw_response_refs, actor_name?, created_at, started_at, completed_at`.
`raw_response_refs`의 각 항목은 `{stage, sha256, prompt_tokens, output_tokens, latency_ms}`이며 세 계측값은 provider가 낸 사실이고 실패 호출에서는 `null`이다.
인덱스 `ix_prespec_overview_run_notice_created(notice_id, created_at desc)`, 부분 유니크
`uq_prespec_overview_run_active(notice_id) where status in ('queued','running')`. app role은
SELECT/INSERT/UPDATE, worker role은 SELECT/INSERT/UPDATE만 갖는다.

`prespec_company_fit_attempt`의 `page_overview_id`/`overview_result_id`는
`overview_run_id uuid null FK prespec_overview_run(id)`로 바뀐다.

### 삭제되는 계약

`bidops.prespec-overview-reviews.v1/v2`, `bidops.prespec-overview-pages.v1/v2`,
`bidops.prespec-overview-page-review.v3/v4`(v4는 2026-09-16
[ADR-0057](tracking/decisions/0057-overview-scope-and-company-fit-in-deep-review.md)로 폐기,
결과 계약은 `bidops.prespec-overview-claims.v2`), `bidops.prespec-overview-claims.v1`(초안
단계 내부용으로만 유지, 문서 계약 아님), `bidops.prespec-overview-claim-checks.v1`,
`bidops.prespec-overview-policy.v1/v4/v5`, `bidops.prespec-v4-activation.v1/v2`,
`bidops.prespec-overview-range-view.v2`, v4 cohort ops CLI, Luna 명시 참조 실행. 함께 drop되는
테이블은 `prespec_overview_verification`, `prespec_overview_call_event`,
`prespec_v4_attempt`, `prespec_v4_target`, `prespec_page_overview`,
`prespec_overview_attempt_event`, `prespec_overview_result`, `prespec_overview_attempt`,
`prespec_overview_snapshot`, `prespec_overview_review`이고 함수
`tf_prespec_v4_attempt_guard()`도 drop한다. `bidops.section-candidates.v1/v2`와 snapshot
계약(`prespec_v4_pdf_snapshot`)은 유지한다. 적용 전 pg_dump 백업 절차는
`docs/operations.md`의 "0026 적용 전 개요 테이블 백업" 절을 따른다.

bundle confirm은 악성코드 clean 결과, document version, structure snapshot과 hash를 고정한다. 심층 attempt와 report materializer는 live 첨부를 다시 읽지 않고 이 snapshot만 사용한다. validation 실패는 report에서 드러나며 자동 통과로 바뀌지 않는다.

Lean wire model의 정확한 shape는 다음과 같다. 별도 `optional` 표기가 없으므로 모든 field는 wire에 필수이며 `?` field만 필수 nullable이다. UUID·date·datetime은 JSON 문자열이고 `source_sha256`는 64자 lowercase SHA-256이다.

- `DocumentVersionView`: `id`, `bundle_id`, `version>=1`, `role`, `effective_date?`, `replaces_document_version_id?`, `is_current`, `safety_status`, `structure_status`, `original_filename`. `role=공고|정정|제안요청서|과업지시서|내역서|제출서식|부록|기타`, `safety_status=quarantined|scanning|safe|blocked`, `structure_status=pending|processing|ready|failed|needs_review`다.
- `BundleIssue`: `issue_id`, `code`, `severity=차단|중대|보통|낮음`, `blocking`, `document_version_id?`, `message`, `locator_type=none|page|paragraph|table_cell|bbox`, nullable opaque object `locator?`다. `BundleView`: `id`, `notice_id`, `revision>=1`, `version>=1`, `status=draft|processing|needs_review|ready|quarantined|failed|superseded`, `documents: DocumentVersionView[]`, `issues: BundleIssue[]`, `confirmed_by?`, `confirmed_at?`, `created_at`. `BundleListResponse`는 pagination field 없는 정확히 `{items: BundleView[]}`다. 새 issue code `unsupported_attachment_excluded`(severity 보통, `blocking=false`)는 허용 형식 밖 첨부가 묶음에서 제외됐음을 알린다. 그 첨부의 `extract_status`는 `provider_unsupported_excluded`이며, 이름이 `provider_`로 시작하지만 **비차단**이다 — issue 계산이 다른 `provider_*` 규칙보다 먼저 이 값을 검사한다. issue code `source_name_differs`(severity 보통, `blocking=false`)는 첨부 목록의 이름과 document snapshot의 파일명이 다름을 알린다. 원본의 정체는 해시·크기이고 목록 이름은 자리표시자일 수 있으므로 차단하지 않으며, message에 두 이름을 담지 않는다. 원문 크기·provider source snapshot 불일치는 그대로 차단 `source_changed`, source location hash 불일치는 차단 `source_hash_mismatch`다.
- `PatchDocumentVersionRequest`는 `role`, nullable `effective_date`, nullable `replaces_document_version_id`, `is_current`, `version>=1`이 모두 필수다. `ConfirmRequest`는 `request_id`, `version>=1`, `confirmed_documents[]`; 각 확인 항목은 `document_version_id`, `version>=1`이다.
- `DocumentStructure`: `schema=bidops.document-structure.v1`, `structure_id`, `document_version_id`, `source_sha256`, `media_type`, `extractor`, `pages[]`, `blocks[]`, `warnings[]`, `created_at`. extractor는 `name`, `version`, nullable `upstream_commit`; page metadata는 `number>=1`, `width>0`, `height>0`, nullable `image_content_object_id`; block은 `block_key`, nullable `parent_block_key`, `type`, `page>=1`, nullable numeric `bbox[]`, `text`, nullable `confidence`(0..1), opaque object `attributes`다. `DocumentStructurePageView`는 `structure_id`, `page>=1`, `metadata`, `blocks[]`다.
- `DocumentSegmentsView`(`bidops.document-segments.v1`): `schema`, `structure_id`, `document_version_id`, `source_sha256`, `taxonomy_version`, `extractor_binding`, `extractor_binding_sha256`, `payload_sha256`, `segments[]`, `inventory_summary`, `coverage`, `warnings[]`, `created_at`. taxonomy version은 `bidops.segment-taxonomy.v1`이고 `extractor_binding`은 `name`(`bidops-document-segments`), `version`, `taxonomy_version`, `rules_sha256`, `schema`다. segment는 `segment_id`, `ordinal>=1`, `taxonomy_labels[]`(`business_eligibility_evaluation|technical_functional|quality_security_constraints|partnership_governance`), `start_locator`, `end_locator`, `requirement_ids[]`, `source_block_keys[]`, `classification_source`(항상 `deterministic`), `confidence`(**항상 `null`**), `status=classified|needs_human_review`, `page_range`, `mapping_status`를 갖는다. locator는 `kind=paragraph|table_cell|block`, `block_key`, `page>=1`, `ordinal>=0`, nullable `table_key`·`row`·`column`이다. `inventory_summary`는 `expected_ids[]`, `duplicate_ids[]`, `ambiguous_items[]`, `prefixes[]`, `item_count`, `coverage`는 `block_count`, `covered_block_count`, `segment_count`, `gap_count`, `overlap_count`, `gaps[]`, `overlaps[]`, `needs_human_review_count`, `toc`다. **응답에 원문 text와 segment 제목이 없다** — 원문을 wire에 싣지 않기로 한 경계의 결과이며, 화면은 ordinal·label·요구사항 ID·block key·page 링크만 보이고 제목이 없는 이유를 직접 밝힌다.
  `page_range`는 `{first,last}`(둘 다 1 이상, 물리 PDF 순번) 또는 `null`이고 `mapping_status`는 `mapped|partial|unavailable`이다. 둘은 **문단↔페이지 대응표(`bidops.para-page-map.v1`)에서 조회 시점에 계산하는 wire 전용 값**이며 manifest·segment 행에 저장하지 않고 `payload_sha256`의 hash 대상에도 넣지 않는다. 대응표는 native(`rhwp-svg-pdf`) snapshot에서만 오며, 대응표가 없거나 segment의 `source_block_keys` 중 매핑된 키가 하나도 없으면 `mapping_status=unavailable`·`page_range=null`이다 — 미확인을 페이지로 승격시키지 않는다. 전부 매핑되면 `mapped`, 일부만이면 `partial`이고 범위는 매핑된 키의 `min(page_first)`~`max(page_last)`다. 대응표를 가진 snapshot이 있는데 객체를 읽지 못하거나 저장된 SHA-256·schema 검증에 실패하면 조용히 `unavailable`로 낮추지 않고 500 `processing_failed`로 닫는다.
- `DeepReviewCreateRequest`는 `request_id`, `bundle_id`; `DeepReviewAttemptRequest`는 `request_id`다. `StageView`는 `stage=requirements_and_evaluation|delivery_risk_economics|synthesis_and_validation`, `sequence>=1`, `status=queued|running|completed|failed`, `started_at?`, `completed_at?`, `last_error_code?`. `AttemptView`는 `id`, `sequence>=1`, `status=queued|running|completed|failed|superseded`, `stages: StageView[]`, `started_at?`, `completed_at?`, `last_error_code?`. `DeepReviewView`는 `id`, `notice_id`, `bundle_id`, `status=queued|running|completed|failed`, `current_attempt?`, `attempts: AttemptView[]`, `created_at`, `completed_at?`, nullable `quality_status=measured|unmeasured_reference|mock_reference`다. `quality_status`가 `null`이면 **표식 없음**이며, 표식이 없던 시절의 실행을 미측정이나 측정으로 승격시키지 않는다.
- `ReportRow`: nonblank `row_key`, nonblank `label`, `cells[]`, `claim_ids[]`. `ReportBlock`: nonblank `block_id`, `type=paragraph|matrix|decision_card|scenario|action_list`, nullable `title`, nullable `body`, `claim_ids[]`, `rows: ReportRow[]`. `ReportSection`: `section_key`, nonblank `title`, `blocks: ReportBlock[]`. section key는 `project_overview|eligibility_matrix|scope_deliverables|requirements_matrix|evaluation_strategy|delivery_plan|technical_integration_risks|security_legal_contract_risks|economics_scenarios|competitive_proposal_strategy|questions_internal_actions|document_bundle_limitations|decision_card`다.
- `ReportClaim`: `claim_id`, nonblank `category`, `claim_type=fact|calculation|inference|opinion|unknown`, nonblank `body`, `status=supported|unsupported|conflicting|unknown`, nullable `formula`, `premise_claim_ids[]`, nullable `reason`, `evidence_ids[]`. `ValidationSummary`: `status=passed|failed`, nonnegative `failed`, `warnings`, `passed`다.
- `DeepReviewReport`: `schema=bidops.deep-review-report.v1`, `deep_review_id`, `notice_id`, `bundle_id`, `profile_version_id`, `policy_version_id`, `sections: ReportSection[]`, `system_recommendation=추진 검토|조건부 추진 검토|보류|검토 종료`, `claims: ReportClaim[]`, `unknowns[]`, `validation_summary`, `created_at`, optional nullable `quality_status=measured|unmeasured_reference|mock_reference`. `quality_status`는 `contracts/bidops.deep-review-report.v1.json`에 **required가 아닌** optional nullable enum으로 추가됐으므로 이전에 저장된 revision은 이 key가 없거나 `null`이며 그것이 "표식 없음"이다. 사람 수정본은 이 값을 편집할 수 없고 서버가 생성 계보에서 다시 계산한다.
- `ValidationCheck`: nonblank `check_type`, `status=passed|failed|warning`, `severity=차단|중대|보통|낮음`, nonblank `message`, `related_claim_ids[]`, `related_evidence_ids[]`. `check_type`에는 결정적 check 두 종이 추가됐다([ADR-0051](tracking/decisions/0051-deep-review-v2-deterministic-subset.md)). `requirement_inventory`는 누락·예상 밖 요구사항 ID를 `failed`·중대, 중복을 warning, ID 체계 없는 문서를 warning "inventory 없음"으로 남기고, `segment_coverage`는 간극·중첩을 warning·보통으로 남기며 차단하지 않는다. `DeepReviewValidation`: `schema=bidops.deep-review-validation.v1`, `validation_run_id`, `report_revision_id`, `status=passed|failed`, `checks: ValidationCheck[]`, `created_at`. `RevisionHistoryItem`: `revision_id`, `sequence>=1`, `origin=machine|human`, nullable `validation_status=passed|failed`, nullable `created_by_name`, `created_at`.
- `FinalOpinionView`: `id`, `sequence>=1`, `value=추진|조건부 추진|보류|검토 종료`, `reason`, `validation_status_at_opinion=passed|failed`, `acknowledged_validation_failure`, `claimed_name`, `created_at`. `ReportView`: `deep_review_id`, `current_revision_id`, `report: DeepReviewReport`, `validation: DeepReviewValidation`, `history: RevisionHistoryItem[]`, nullable `final_opinion: FinalOpinionView`다.
- `ReportRevisionRequest`: `request_id`, `base_revision_id`, `report: DeepReviewReport`, nonblank `reason`, `factual_change_evidence_ids[]`. `FinalOpinionRequest`: `request_id`, `report_revision_id`, `validation_run_id`, `value=추진|조건부 추진|보류|검토 종료`, `reason`, `acknowledged_validation_failure`; schema는 빈 문자열을 구조적으로 거부하지 않지만 service는 blank reason을 400 `final_opinion_reason_required`로 거부한다.
- `EvidenceView`: `evidence_id`, `source_kind=document|profile`, nullable `document_version_id`, nullable `structure_id`, nullable `profile_version_id`, nullable `profile_evidence_id`, `locator_type=page|paragraph|table_cell|bbox|profile_fact`, opaque object `locator`, `quote`, nullable `confidence`(0..1), `source_sha256`, nullable `page: DocumentStructurePageView`다.

Lean 안정 오류 code의 전체 vocabulary는 `invalid_request`, `actor_name_required`, `actor_name_invalid`, `not_found`, `effective_grade_ineligible`, `bundle_not_ready`, `bundle_has_blocking_issues`, `unsafe_document`, `structure_unavailable`, `version_conflict`, `idempotency_conflict`, `active_attempt_exists`, `service_unavailable`, `review_not_ready`, `evidence_out_of_scope`, `factual_change_evidence_required`, `validation_failed`, `final_opinion_reason_required`, `processing_failed`다. 소비자는 table에 적힌 endpoint별 status/code 조합만 정상 계약으로 처리하고, 알려지지 않은 조합은 안전하게 실패시킨다.

## 파이프라인 파일 계약

모든 파일은 UTF-8, 불변 run 디렉터리, 명시적 schema version을 사용한다.

| 파일·schema | 생산자 | 소비자 | 핵심 의미 |
|---|---|---|---|
| `review-inputs/manifest.json` / `bidops.order-plan-review-inputs-manifest.v1` | 발주계획 실험 담당자 | 입력 검증기, 실행 담당자 | Git에서 제외된 회사 역량·prompt 본문의 상대 경로, 승인·초안 상태, 실행 허용 여부, SHA-256과 active 선택 |
| `selection-decision.json` / `bidops.order-plan-screening-selection-decision.v1` | C-2 사람 결정권자 | 선별 제품 정책·구현 담당자 | 선택한 stage1·stage2 binding, 측정 지표, 수용한 누락 artifact, 운영 활성화와 분리된 선택 상태 |
| `collected-notices.json` / `bidops.collected.v2` | collect | 표본 선정, 웹 적재 | 원본 회차, 정규화 notices, source window |
| `collection-provenance.json` / `bidops.collection-provenance.v1` | 사전규격·입찰 공통 collector | 재분류·운영 확인 | 원본 raw 상대 경로, 실행 옵션, 보존 페이지 SHA-256, 완전성·경고 |
| `collected-order-plans.json` / `bidops.collected-order-plans.v1` | `collect_order_plans.py` | 웹 적재 | 전체 발주계획 projection, 공식 계획번호·연관 공고번호·관측 범위·원문 hash |
| `validation-set.json` / `bidops.validation-set.v2` | collect sample | screen v2, 품질 기준선 | 고정 표본과 source identity |
| `screening-input.json` / `bidops.screening-input.v1` | runtime orchestrator | screen v3 worker | execution/run, 후보, 불변 binding |
| `screening-decisions.json` / `bidops.decisions.v2` | 과거 screen | v2 merge, 품질 baseline | 과거 판정 계약 |
| `screening-decisions.json` / `bidops.decisions.v3` | 현재 screen | v3 merge, 웹 적재 | 5개 관점, 반론, 종합, 근거 |
| `screening-failures.json` / `bidops.screening-failures.v1` | screen | 웹, 운영자 | 실패 stage/type, retry, 안전한 요약 |
| `screening-telemetry.jsonl` / `bidops.screening-telemetry.v1` | screen | 관측 적재 | 호출 span, model digest, token/duration |
| `screening-results.json` / `bidops.screening.v2` | legacy merge | report, 웹 적재 | 과거 결정적 HTML·feedback 입력 |
| `screening-results.json` / `bidops.screening.v3` | runtime merge | 웹 적재 | 성공 subset, partial/failure·execution binding; 현재 report renderer는 미지원 |
| `review-feedback.yaml` / `bidops.feedback.v2` | report/API export | 호환 가져오기 | 사람 리뷰 교환; DB가 적재 뒤 정본 |
| replacement provenance / `bidops.screening-replacement.v1` | full rerun publish | 적재·감사 | source run과 새 execution 관계 |

허용 merge는 `validation-set.v2 + decisions.v2 → screening.v2`와 `screening-input.v1 + decisions.v3 → screening.v3`다. 세대를 섞으면 중단한다. v3 성공 결과는 execution, run, policy, prompt, model digest, profile digest, input digest를 역추적할 수 있어야 한다. 일부 notice 실패 시 성공 subset과 failure artifact를 함께 보존하고 `partial_artifact=true`로 표시한다.

현재 `render_report.py`는 `bidops.screening.v2`만 허용한다. v3를 report stage에 전달하면 계약 오류로 종료하며, v3 HTML·feedback 연결은 구현되지 않았다. 소비자는 v3가 자동으로 보고서까지 이어진다고 가정하지 않는다.

사전규격·입찰 공통 collector는 `--output-dir`을 배타 생성한다. 기존 빈 폴더·파일·symlink와
허용 루트 이탈은 키 확인·HTTP 전에 거부하며 raw와 최종 JSON도 배타 쓰기한다. 웹·예약 호출은
출력 폴더를 선생성하지 않는다. `--from-raw SOURCE_RAW`는 원본을 읽기만 하고 별도의 새 회차에
바이트·hash를 검증 복사한다. 기본 `--allowed-root`는 저장소의 `data/runs`, 웹·예약은
`settings.bidops_root/data/runs`다. 테스트만 별도 허용 루트를 명시 주입한다.
provenance v1 필드는 `schema_version`, `generated_at`, nullable `source_raw`, `source_window`,
`options(rows,timeout,skip_bids,skip_prespecs)`, `sources`, `complete`, `warnings`,
`raw_pages[{path,source_path,sha256}]`다. 원본 경로는 허용 루트 상대 경로이고 자격증명은 없다.
페이지 누락·건수 불일치·안전 상한 등 부분 수집은 경고와 `complete=false`, exit 1로 남기며
웹·예약은 자동 적재하지 않는다. 중간 실패의 raw를 보존하고 재시도는 새 회차에서 수행한다.
정규화 v2와 사전규격·입찰의 종료일 포함(0000~2359), 발주계획의 종료일 제외는 유지한다.

`collected-notices.json`의 `bidops.collected.v2`는 T-11에서 유지한다. 입찰공고 원문에 이미 있는
`orderPlanUntyNo`를 기존 `lifecycle` 안의 선택적 `order_plan_no`로 투영할 뿐이며, 기존 필드의
의미·필수성·레코드 종류를 바꾸지 않는다. 따라서 과거 v2 파일은 그대로 유효하고, 새 v2 파일만
이 선택 필드를 가질 수 있다. 발주계획 전체 원본은 공고 계약의 조용한 확장이 아니라 아래의
독립적인 `collected-order-plans.json` / `bidops.collected-order-plans.v1`로 분리한다.

`bidops.collected.v2`는 사업 추적 연결을 위한 optional 필드 넷을 추가로 가질 수 있다(spec §1.2,
2026-09-17). 모두 미확인이면 `null`이고 기존 필드의 의미는 바꾸지 않는다.

| 필드 | 원천 | 값 |
|---|---|---|
| 사전규격 `demand_agency` | `rlDminsttNm` | 문자열 또는 `null`. 기존 `agency`는 발주기관(`orderInsttNm`) 그대로 |
| 입찰공고 `lifecycle.opening_at` | `opengDt` | timezone-aware ISO 또는 `null` |
| 입찰공고 `qualification_flags.sw_industry_1468` | 1468(소프트웨어사업자) 업종 조회 | `Y`(포함)·`N`(조회 성공·미포함)·`null`(조회 실패·부분 수집) |
| 발주계획 `bid_ntice_no_list` | `bidNtceNoList` | `collect_order_plans.py`의 필드명 오타를 고친 뒤 원문 값 |

`sw_industry_1468`은 수집기 플래그 `--tag-bid-sw-industry`로 켠 조회이며 1468 조회 원문은
`raw/industry1468-page-NNN.json`으로 별도 보관한다(파일명이 `bid-`로 시작하지 않으므로 재분류가
입찰공고 raw 페이지로 잘못 읽지 않는다). 수집 파일 최상위 `metadata.sw_industry_1468`에
`{status: complete|failed|partial|not_requested, total, pages}`를 남긴다. 조회가 실패·부분이면
그 회차의 모든 입찰공고 `sw_industry_1468`이 `null`이고 수집기는 경고와 함께 비0 종료 코드로
끝나 일일 스크립트가 적재 전에 멈춘다(다음 날 창에서 다시 조회). `demand_agency`·
`lifecycle.opening_at`·`qualification_flags.sw_industry_1468`은 값이 `null`이면 관측 snapshot에
넣지 않고, `demand_agency`는 값이 있어도 snapshot에 넣지 않는다(C-1 판정 입력이 이 필드를 싣지
않으므로 같은 회차 C-1 적재와 snapshot hash가 충돌하지 않는다). `Notice.demand_agency` DB 열에는
저장한다.

### 적재 CLI와 수집 색인 (spec §2)

`python -m app.lifecycle.ingest.cli`는 세 모드를 갖는다(`--run`/`--all`은 상호 배타).

| 모드 | 뜻 |
|---|---|
| `--run <회차>`(기본 `selection="validation"`) | 검증 표본(`validation-set.json`)이나 C-1 입력(`screening-input.json`)의 공고만 적재한다. 발주계획은 전량 적재한다. 기존 C-1 적재 경로이며 코드의 실제 selector 값은 `validation`이다 |
| `--run <회차> --collection`(`selection="collection"`) | 표본이 없어도 오류가 아니다. `collected-order-plans.json`·`collected-notices.json`의 모든 레코드를 `collected_record_index`(migration `0027`)에 한 행씩 남기고, 선별 규칙(아래 표)에 맞는 레코드만 같은 적재 경로로 적재한다 |
| `--tracked-backfill` | `계속 추적`·`보류` 사업기회가 가리키는 색인의 미적재 레코드를 찾아 적재한다(추적 상태 저장 직후와 daily 스크립트 마지막 단계에서도 호출) |

선별 사유 코드(`ck_collected_record_index_selection_reason`과 같은 닫힌 집합)는
`order_plan_all`, `pre_spec_sw`, `pre_spec_referenced`, `pre_spec_known`, `bid_same_notice_no`,
`bid_tracked_reference`, `bid_sw_prespec_reference`, `bid_sw_industry_competitive`,
`tracked_backfill`, `search_result` 10개다. 조건에 쓰는 값이 `null`이면 그 조건은 불일치로 보고
색인에만 남긴다(추정 적재하지 않는다). `--collection` 적재의 `IngestResult.selection`과
`run.counts_json["selection"]`은 원천(`order_plan`·`pre_spec`·`bid_notice`)별
`{collected, selected: {사유코드: 건수}, skipped}`이며 `collected = sum(selected) + skipped`가
항상 성립한다. 이 통계는 **그 회차 적재 시점의 선별 결과 snapshot**이다 — 나중에 추적 보충
(`--tracked-backfill`)이나 찾아보기(`POST /api/opportunities/{id}/searches`)로 적재된 레코드는
색인 행의 `selection_reason`에만 반영되고 회차 통계는 다시 쓰지 않는다. 같은 회차 재실행은
색인 unique 제약과 관측 snapshot 검사로 no-op이다.

발주계획 artifact의 canonical `order_plans[]`는 실측 API 필드를 다음처럼 보존·정규화한다.

artifact의 `metadata`에는 endpoint 식별자와 적용한 업무구분 범위를 함께 남긴다. 현재
생산자 범위는 `bsnsDivNm`의 `일반용역`·`기술용역` allowlist이며, 범위 밖으로 제외한 원문
건수는 `counts.excluded_out_of_scope`와 `counts.excluded_business_divisions`에 기록한다.
`metadata.order_month_scope`는 PPSSrch가 요구하는 `200412`~`999912` 보조 범위이고,
`metadata.collection.complete=false`이면 페이지 안전 상한 등으로 부분 수집된 회차다.

- `order_plan_unty_no` ← `orderPlanUntyNo`, `title` ← `bizNm`
- 기관은 `orderInsttCd`·`orderInsttNm`·`totlmngInsttNm`, 업무·서비스는
  `bsnsDivCd`·`bsnsDivNm`·`bsnsTyCd`·`bsnsTyNm`을 사용한다.
- 금액은 `sumOrderAmt`·`orderContrctAmt`, 예정 시기는 `orderYear` + `orderMnth`,
  방식은 `prcrmntMethd`·`cntrctMthdNm`을 사용한다.
- `published_at`/`changed_at`은 각각 `nticeDt`/`chgDt`, 연관 공고는
  `bid_ntice_no_list` ← `bidNtceNoList`, 게시 여부는 `notice_posted` ← `ntceNticeYn`,
  원문 URL은 `source_url` ← `orderPlanDtlUrl`이다.
- `rcrit_rgst_no` ← `rcritRgstNo`는 빈 응답도 `null`인 계약 필드로 남긴다. 발주계획 응답에서
  측정되지 않은 SW 상태는 `sw_business_status: null`과 `unknown_fields`로 검증 대기 상태를
  구분한다. `first_discovered_at`, `last_discovered_at`, `source_sha256`, `raw_source`도
  각 항목에 유지한다.
- `bidNtceNoList`와 `ntceNticeYn`은 공고 전환·재관측 비교의 신호다. `chgDt`는 관측 값으로
  보존하지만 갱신 감지 신호로 사용하지 않는다.

이 artifact의 loader는 `OrderPlan`을 공식 계획번호로 누적 upsert하고
`OrderPlanObservation(order_plan_id, run_id)`를 추가한다. 신규 observation은
`bidops.order-plan-observation-snapshot.v1`의 결정적 정규화 snapshot과 그 lowercase
SHA-256을 함께 보존한다. 확인되지 않은 키는 warning으로 기록하고 해석하지 않는다.
이전 실험 산출물의 `bidops.order-plan-population.v1`와 `items` 목록은 읽기 전용 호환
입력으로만 취급하고 canonical 파일을 덮어쓰지 않는다.

`NoticeObservation`의 신규 snapshot schema는
`bidops.notice-observation-snapshot.v1`이다. 두 snapshot 모두 top-level
`schema_version`, `record_kind`, `record`를 가지며 notice snapshot은 수집 artifact가
첨부 목록을 제공한 경우 안전한 첨부 metadata 목록도 가진다. snapshot hash는 이 payload를
UTF-8, key 정렬, 공백 없는 JSON으로 직렬화해 계산한다. 같은 외부 식별자와 run에 같은 hash가
다시 들어오면 no-op이고 다른 hash면 회차 전체를 rollback한다. `0009` 이전 observation의 세
snapshot field는 추정 backfill하지 않으며, 같은 과거 회차 재적재는 warning과 함께 projection
변경 없이 건너뛴다.

승계 판정은 `carried_over=true`, 최초 `judged_in_run`, 현재 `recorded_in_run`을 보존한다. 승계를 새 모델 호출로 기록하지 않는다. 승계 validation 실패는 별도 성공 판정으로 만들지 않고 사람 검토 대기 failure로 남긴다.

## 심층 검토 내부 artifact

| schema | 용도 |
|---|---|
| `bidops.agent-command.v1` | API가 worker에 전달하는 fenced command |
| `bidops.agent-run.v1` | worker 실행, 입력·출력 hash, 상태와 lineage |
| `bidops.document-converter-request.v1` | network 없는 변환 worker 요청 |
| `bidops.document-converter-result.v1` | 변환 결과와 안전한 오류 |
| `bidops.document-converter-request.v2` | `prepare_pdf=true` 문서 변환 요청과 원문 hash/scan 결속 |
| `bidops.document-converter-result.v2` | 구조 JSON과 request UUID 결속 PDF sidecar metadata |
| `bidops.document-structure.v1` | page/block/table 구조와 원문 locator |
| `bidops.para-page-map.v1` | native rhwp 구조 블록과 물리 PDF 페이지 대응 (생성·검증·버전 고정 저장) |
| `bidops.document-bundle.v1` | 확정된 document versions와 structure snapshot |
| `bidops.deep-review-stage.v1` | 세 단계의 claims, evidence, unknowns, warnings |
| `bidops.deep-review-report.v1` | 검증된 claim을 이용한 보고서 |
| `bidops.deep-review-validation.v1` | 근거·수치·계약 검증 결과 |
| `bidops.analysis-policy.v1` | 모델, chunk, retry, generation, validation 정책 |
| `bidops.company-profile.v1` | 승인된 회사 profile snapshot |

모델 response 원문은 암호화된 객체로 저장하고 DB에는 namespace, version, hash, key reference만 둔다. evidence locator는 document version, structure ID, page·block 또는 표 좌표를 포함하며 report의 사실·숫자와 연결된다.

`bidops.para-page-map.v1`은 `page_count`, `paragraph_count`, `paragraphs[]`,
`blocks[]`, `unmapped_block_keys[]`, `mapping`을 갖는다. 문단 identity는
`(section, para_index)`이고 `page_first`·`page_last`는 1 기준 물리 PDF 순번이다.
구조 블록의 `match=exact`는 검증된 source HWPX 문단 identity에만 사용한다.
HWP 변환본·표 셀의 `match=page_text`는 전체 텍스트의 유일 발생만 허용하고
`para_index=null`이며, 확인하지 못한 source section도 `null`로 둔다.
빈 블록·미확인 연결은 `unmapped_block_keys`에 보존하며 매핑률 0도 유효하다.
`mapping`의 세 블록 집계는 mapped·unmapped의 중복 없는 전체 분할과 같아야 하고
`rule=para-page-align.v1`로 고정한다. [상세 계약과 정렬 규칙](rhwp-document-pipeline/Spec.md)을 따른다.
대응표와 canonical JSON 바이트는 native `ProcessedDocument`의 별도 속성이다.
기존 구조 JSON·REST는 유지하고 scratch v2의 `native_sidecars` descriptor와
`prespec_v4_pdf_snapshot`의 객체 참조로 저장 경계를 연결한다.

문서 변환 scratch 계약은 v1 구조 결과와 v2 PDF preparation 결과를 구분한다. v1은
기존 `request.v1`/`result.v1` envelope와 structure JSON만 사용한다. 요청 options의
`prepare_pdf=true`는 `bidops.document-converter-request.v2`를 선택하고, 성공 결과는
`bidops.document-converter-result.v2`의 `pdf_sidecar`를 반드시 포함한다. sidecar는
JSON/base64로 넣지 않고 request UUID에서 도출한 단일
`pdf/<request_uuid>.pdf` 파일로 원자적으로 publish한다. 결과 JSON은
`file`, `byte_count`, `sha256`, 기존 `pdf_metadata`, `source_kind`를 결속하며,
worker는 PDF sidecar를 먼저 완료한 뒤 결과 JSON을 마지막에 publish한다.

consumer는 고정 namespace와 UUID filename을 다시 계산하고 stat·bounded read,
regular-file/no-symlink, byte count·SHA-256·`%PDF-` 검사를 통과한 sidecar만
`ProcessedDocument.converted_pdf_bytes`와 `.pdf_metadata`로 복원한다. 생성 PDF는
trusted-side ClamAV로 exact bytes를 재검사하며, 원본 PDF 입력은 `.original_bytes`를
그대로 보존하고 v2 sidecar의 `source_kind=original`로 구분한다. 이 경우 request의
선언 MIME가 아니라 검증된 structure의 `media_type=application/pdf`를 기준으로 하며,
sidecar bytes와 원문 hash가 exact match여야 한다. `pdf_metadata`는 빈 object를
허용하지 않고 `bidops.pdf-snapshot.v1`의 physical `page_count`와 페이지별
`number`, `width`, `height`, normalized text의 `text_sha256`를 structure와 함께
검증한다. 성공 소비 뒤 해당 request의 result/sidecar만 삭제하며, timeout 중 claimed
input과 다른 request 파일은 삭제하지 않는다. scratch는 임시 handoff이고 DB/MinIO
정본이나 영속 snapshot이 아니다.

native `renderer=rhwp-svg-pdf` 성공 결과는 `native_sidecars`에 `hwpx`, `page_text`,
`para_page_map`, `section_candidates`, `hwpx_verify`를 추가한다. 파일 descriptor는 `{file,byte_count,sha256}`이고
`native/<request_uuid>.hwpx`, `.page-text.json`, `.para-page-map.json`으로만 해소한다.
원본 HWPX는 `hwpx`·`hwpx_verify`가 `null`이고 원문을 재사용한다. HWP 변환본은
`hwpx_verify={identical:true,diff_count:0,pages:{before:N,after:N,identical:true}}`를
반드시 갖는다. 원문·PDF·변환 HWPX를 trusted-side scanner로 검사한다. native
page-text는 `bidops.rhwp-page-text.v1`의 `page_count`, 물리 페이지의
`number,display_page,section,text,text_sha256`를 보존한다. 모든 sidecar를 완료한 뒤
성공 JSON을 publish하며 소비자는 고정 경로·regular file·상한·hash·페이지 수와
schema를 검사한다. 구조 블록을 합쳐 PDF page text를 대신하지 않는다.

후보는 현재 `bidops.section-candidates.v2`로 생성하고 기존 v1도 읽는다.
후보 산출 실패가 구조의 `section_candidates_unavailable` 경고에 명시되어 있고 핵심
산출물의 독립 검증이 통과한 경우에만 `native_sidecars.section_candidates=null`을
허용한다. descriptor 키 자체의 누락이나 경고 없는 null은 거부한다. 실제 후보 파일의
JSON `null`도 유효 후보가 아니며 거부한다. 후보가 있으면
고정 경로·byte 수·hash·canonical JSON·후보 결속 검사를 그대로 적용한다. 저장된
snapshot의 후보 참조 세 열은 이 경우 함께 null이며 원본·PDF·페이지 텍스트·대응표의
필수 참조와 검사는 생략하지 않는다. 후보 미제공은 변환 또는 내용 검토 성공을 뜻하지 않는다.

## DB와 migration 계약

- 이 작업 브랜치의 Alembic head는 `0028_final_decision_basis`다(`app/core/db.py:103`). `main`의 head는
  `0026_overview_mvp`이고 `0027`·`0028`은 2026-09-17 기준 미병합 브랜치에만 있다. 운영 DB 적용 기록은
  `docs/tracking/status.md`가 정본이다(기록상 `0025_overview_claim_ledger`까지). `0019`~`0026`은 이 목록에 개별 bullet이 없고 각자의 계약
  절(사전규격 개요 §`0026`은 위 "사전규격 개요 검토" §DB 참조)에서 다룬다. 그 이전 T-23 phase 2
  migration은 `0014_prespec_overview_attempt_result`이며, 아래 T-23 검증 증거는 `0014`
  경계에 해당한다.
- `0001_lean_v1_postgresql`은 기존 수집·리뷰와 심층 검토 table, `0002_screening_basis_text`는 긴 판정 설명 보존, `0003_screening_runtime_pg`는 판정 실행·품질·정책·일정·감사와 불변 trigger를 추가한다.
- `0004_cumulative_external_identity`, `0005_opportunity_links`, `0006_bid_first_opportunity_registration`은 공고·발주계획 누적 관측, opportunity 공식 링크, 입찰공고 최초 등록과 대기 참조 해소를 추가한다.
- `0007_opportunity_tracking_state`는 사업기회 추적 상태를 추가한다. `tracking_status`는 `미선택`·`계속 추적`·`보류`·`종료`이고 기본값은 `미선택`이다. CHECK가 `미선택`일 때 작성자·이유·시각이 없고 그 밖의 값일 때 작성자와 시각이 반드시 있음을 강제한다. 시스템 재검토 신호(`recheck_signal_at`, `recheck_signal_link_id`)는 사람 선택 컬럼과 분리되어 있고 근거가 된 `opportunity_link`를 가리킨다.
- `0008_prespec_attachment_fetch`는 사전규격 첨부 바이트의 조건부 취득·재평가·lease 상태를 `attachment_fetch`에 기록한다. 문서 bundle 없이 source provenance가 있는 `DocumentVersion`을 만든다.
- `0009_observation_snapshot_retention`은 신규 공고·발주계획 observation에 nullable legacy 호환 snapshot schema·JSONB·SHA-256 묶음을 추가한다. 기존 observation은 `null` 그대로 두며, 수집에서 사라진 provider 첨부는 삭제하지 않고 `retired_at`·`retired_reason`으로 보존한다.
- `0010_opportunity_link_integrity`는 authoritative target별 partial unique index와 non-destructive opportunity merge lineage를 추가한다. migration은 기존 authoritative 중복을 자동 수정하지 않고 충돌 target/link ID를 제시하며 중단한다. 자동 merge는 모든 row가 `미선택`이고 recheck state가 없을 때만 가능하다.
- `0011_judgment_review_revisions`는 현재 `Judgment`·`Review` projection을 유지하면서 notice별 append-only `judgment_revision`·`review_revision` 이력을 추가한다. 판정 revision은 observation run, 기록 screening execution, 같은 notice의 승계 parent를 분리해 보존하고, 사람 review revision은 선택적으로 정확한 judgment revision을 고정한다. 두 payload는 ID를 넣지 않은 `bidops.judgment-revision-payload.v1`·`bidops.review-revision-payload.v1` JSON object와 canonical lowercase SHA-256을 저장한다. 기존 review의 run이 같은 notice observation이 아니면 migration은 ID를 제시하고 중단하며, legacy review의 과거 judgment alignment는 추정하지 않아 `judgment_revision_id=null`로 남긴다.
- `0012_prespec_overview_review`는 사전규격 개요 review의 현재 상태와 clean `DocumentVersion`·`DocumentStructure`를 연결한 append-only 절단 snapshot, 향후 모델 attempt 계보를 추가했다. snapshot은 source/payload hash와 deterministic prefix locator를 고정하고, 현재 구조가 갱신되면 과거 snapshot을 덮지 않고 새 row를 만든다. 이 revision의 attempt 전체 append-only trigger는 `0014`에서 제한된 lifecycle UPDATE 계약으로 교체된다.
- `0013_document_integrity`는 attachment가 있는 문서의 `(attachment_id, version)`과 attachment별 current 최대 1개를 partial unique index로, bundle 안 ordinal을 UNIQUE로 강제한다. 기존 충돌은 ID와 키를 제시하고 추정 보정 없이 migration을 중단한다.
- `0014_prespec_overview_attempt_result`는 phase-1 attempt의 review/input/binding/result 참조와 result/event table을 추가한다. FK·UNIQUE·CHECK가 row 구조를 강제하고, 단일 DB trigger는 허용 상태 간선만 검증한다. runtime privilege는 app에 안전 조회, worker에 attempt/result/event의 최소 SELECT·INSERT와 attempt의 `status`·`started_at`·`completed_at`·`result_id` column UPDATE만 허용해 입력 계보와 result/event의 UPDATE·DELETE를 막는다. result scope, timestamp 의미, event 동반과 review projection은 service transaction에서 검증하며 교차 table trigger로 중복하지 않는다. legacy inline result/completed attempt가 발견되면 추정 보정 없이 upgrade를 중단하고, downgrade도 phase-2 row가 남아 있으면 거부한다.
- `0018_prespec_auto_preparation_segments`는 자동 준비와 결정적 문서 segment를 추가한다.
  `ck_attachment_fetch_eligibility_reason`에 `priority_grade` 자격 사유를 더하고,
  `ck_prespec_overview_attempt_completed_binding`을
  `status <> 'completed' OR reference_only IS FALSE`로 교체한다. 품질을 아직 재지 않은 실제
  모델 실행(`deployable=false`)도 완료될 수 있고 **mock 참조 실행(`reference_only=true`)만**
  완료를 막는다는 뜻이다. 상태 전이 trigger는 그대로 둔다. `prespec_overview_attempt`에 nullable
  `lease_owner`(varchar 255)와 `lease_expires_at`(timestamptz)을 더하고, worker의 column-scoped
  UPDATE 허용 열을 `status`·`started_at`·`completed_at`·`result_id`·`lease_owner`·`lease_expires_at`으로
  넓힌다. 새 table 셋(`document_segment_manifest`, `document_segment`,
  `requirement_inventory_item`)은 append-only이며 FK는 `ondelete=CASCADE`,
  `(document_version_id, structure_id)` 복합 FK를 함께 갖고, 유일키는
  `(structure_id, taxonomy_version, extractor_binding_sha256)`다. runtime role에는 SELECT와
  INSERT만 준다. downgrade는 `priority_grade` 행, `deployable=false` 완료 attempt, 세 table의
  행이 하나라도 있으면 추정 보정 없이 거부한다.
- `0027_collection_index_and_linkage`는 `collected_record_index`(선별 여부와 무관하게 수집
  레코드마다 한 행, unique `(run_id, record_kind, record_key)`)와 자식 `collected_record_token`
  (`bidNtceNoList` 토큰)을 추가한다. `notice.demand_agency`(사전규격 수요기관)와 같은 공고번호의
  다른 차수 조회용 `ix_notice_bid_no`(기존 `0001`로 생성된 신규 DB에는 이미 있음, 기존 DB에만
  추가)도 더한다. `opportunity_link`의 `ck_opportunity_link_status`에 `사람 확인 병합`,
  `ck_opportunity_link_search_strategy`에 `merge_confirmation`을 더하고 `검색 미확인` 행이 어느
  종류를 찾다 실패했는지 구분하는 nullable `search_target_kind`(`pre_spec`·`bid_notice`)와 CHECK를
  추가한다. downgrade는 색인 행, non-null `demand_agency`, 새 status·strategy·search_target_kind
  값이 하나라도 있으면 거부한다. 권한: app SELECT/INSERT와 색인의 `selection_reason`·
  `ingested_*` 열 UPDATE, worker SELECT; 토큰 table은 app SELECT/INSERT.
- `0028_final_decision_basis`(ADR-0058)는 `bid_final_decision`의 비교 5열
  (`comparison_id`·`comparison_version`·`result_sha256`·양쪽 document version ID)을 nullable로
  바꾸고, `basis_kind`(`comparison`\|`notice_conditions`, NOT NULL, 기존 행은 `comparison`),
  `basis_notice_id`(FK `notice`), `basis_observation_sha256`(64 hex)을 추가한다. CHECK는 근거가
  `comparison`이면 비교 5열이 모두 있고 basis 두 열이 비고, `notice_conditions`면 그 반대임을
  강제한다. `ADD COLUMN ... DEFAULT`로 기존 행을 채운 뒤 기본값은 지워 새 INSERT가 근거를
  명시하게 한다. append-only trigger·unique·supersession FK는 그대로다. downgrade는
  `notice_conditions` 행이 하나라도 있으면 거부한다. 권한: app에 `bid_final_decision` INSERT와
  tip 잠금용 `UPDATE (id)`를 추가하며 비교·attempt·item·evidence 권한은 바꾸지 않는다.
- `0029`(ADR-0060, 예정)는 C-2 품질 게이트·evaluation·감사 표본·일일 스위치 4테이블과
  `order_plan_screening_execution.purpose`를 추가한다. 열·제약·권한은 아래 "C-2 DB·migration 경계"의 `0029` 절이 정본이다.
- 앱 startup은 revision과 필수 table 존재만 확인한다. migration과 seed를 실행하지 않는다.
- fresh migration은 schedule과 always-on singleton, migration audit만 만든다. screening policy와 agency portal은 명시적 운영 명령 또는 API로 생성한다.
- active screening slot과 active policy는 각각 최대 하나다. queue claim은 queue number FIFO와 짧은 transaction으로 처리한다. deep-review job claim은 PostgreSQL row lock과 `SKIP LOCKED`를 사용한다.

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

## C-2 Phase 0 fixed contract

Phase 0에서 고정한 C-2 계약의 machine-readable index는
[`skills/bidops-screen/contracts/contract-index.v1.json`](../skills/bidops-screen/contracts/contract-index.v1.json)이다.
정책과 현재 worktree의 실제 입력·증거를 묶은 binding은
`experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json`이며,
읽기 전용 검증기는 `skills/bidops-screen/scripts/validate_order_plan_phase0.py`다. 이 문서와
schema 파일의 `schema_version`, `producer`, `consumer`, 필수 key, status enum이 다르면
새 schema version 없이는 소비하지 않는다. index는 각 schema 파일의 SHA-256과 고정된 파일
집합도 보존하며, 검증기는 index·schema digest가 바뀌면 fail closed한다.

현재 binding은 계약상 유효하지만 `blocked`다. 수집 원본은 625건이고 C-1 gold는 사람 판정
22건·draft 603건·잔여 확인 87건이다. 따라서 validator의 `valid_but_blocked`는 검증 성공이지
운영 실행·정책 활성화 승인이 아니다. 이 validator는 **v1·v2 phase-0 증거 전용**이다 — 20260827 phase-0
증거에 고정돼 있고 gold `activation_eligible is False`를 요구한다(`validate_order_plan_phase0.py:1365`). v3
policy·binding은 이 validator의 검증 범위 밖이며, v3의 정합성은 적재 CLI 검증과 런타임 blocker가 맡는다
([ADR-0060](tracking/decisions/0060-c2-policy-db-row-authority.md)). 현재 고정 digest는 policy
`3010c7bfb569e062fc8e94b052df0325caccad7e23a34cf1e15dad6a6358e196`, binding
`e0367de6155e362539a867d3b6820e204ba1238a2a613c6b973780c8348c86ef`, source
`d608e1ad71dd03467278ad06a8c3290b5a5db47a118b3f1fcda5c7e90d122faf`, population
`7846e7ff51002dac613f85cc1a3e8a358430c9519ed96c6501e8e41c9f3d1c5a`, BM25
`e026b2bdd2f99ddc09ae17bc83b1cd9cc40ef413f3b72372a35db32918d696da`, Qwen model
`6ae70ca30563209f09ec0114ce5813f7a232b38e5bb409f2adbd0e9bbe318b11`, prompt
`639f7332e1120a41b2e8d8306126f121ae1ed37068a81b1687aff9ce66ab9d12`, 회사 역량 파일
`8f60dfece1934bdf857cd7e57d0fdd1860d01871131d98c3f2e8f9d71f271eae`, generation config
`1fd2f511a0b1c99f5a57125ebd9e1d67314d98202d42327394daa540abd27754`다.

### C-2 stage 2 wire 계약

승인된 사설 vLLM에 실제로 나가는 요청과 받는 응답의 계약이다. 이 모양은
[ADR-0037](tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md)이 625건으로 측정한
것과 같아야 하며, 차이는 곧 "측정하지 않은 방법을 운영에 쓰는 것"이다
([ADR-0044](tracking/decisions/0044-c2-stage2-matches-the-measured-method.md)).

요청은 `POST {base_url}/chat/completions` 하나이며 body는 다음으로 고정한다.

- `messages[0]`은 승인 prompt 원문을 담은 `system`, `messages[1]`은 payload의 canonical
  JSON을 담은 `user`다. 둘을 한 message로 이어붙이지 않는다.
- `temperature: 0`, `stream: false`. `top_p`와 `seed`는 보내지 않는다.
- `max_tokens`와 `chat_template_kwargs`는 승인 generation config
  (`generation_config_sha256`이 가리키는 파일)에서 읽는다. 하드코딩하지 않는다.
- `chat_template_kwargs`는 **최상위 필드**다. `extra_body`는 OpenAI 파이썬 SDK 개념이라
  raw JSON에서는 서버가 무시한다.
- `response_format`은 `json_schema` + `strict: true`이며 schema가 배치 크기를
  `minItems`/`maxItems`로 고정한다.

payload는 `{company_capabilities: {profile_version, capabilities[{id,summary}]},
items: [{item_id, title}]}`이다. `item_id`는 `0..batch-1`의 batch-local index이며
**실제 발주계획 번호는 보내지 않는다.**

응답 `items`의 각 행은 `{item_id, relevance, score, reason}` 네 필드뿐이다.
`item_id`는 각 정확히 한 번 나타나야 하고 순서는 자유다. worker가 batch 위치로
`plan_id`를 되돌리며, 그 이후의 내부 artifact와 DB는 전부 `plan_id`를 쓴다.

### C-2 파일·schema 경계

모든 신규 C-2 JSON은 UTF-8·중복 key 금지·유한 숫자·timezone timestamp를 사용한다. 아래
파일은 생성 후 덮어쓰지 않으며, `producer`가 만든 파일은 `consumer`가 같은 v1 binding과
digest를 확인한 뒤에만 읽는다.

| 파일 / schema | producer → consumer | 필수 top-level key와 status | 호환·불변 경계 |
|---|---|---|---|
| `config/order-plan-screening-policy.v1.json` / `bidops.order-plan-screening-policy.v1` | `phase0-contracts` → `phase1-screening-pipeline` | `schema_version`, `producer`, `consumer`, `policy_version`, `policy_status`, `decision_scope`, `created_at`, `stage1`, `stage2`, `audit_sample`, `execution`, `feedback`, `quality_gate`, `bindings`, `activation`; stage2에 model·generation config·prompt·profile SHA-256; `policy_status=draft|activation_candidate|active|retired` | policy payload·binding은 immutable. 활성화는 별도 사람 승인과 audit 없이는 불가하다. **활성 여부의 정본은 DB 행이다** — `policy_status`와 `activation.*`·`quality_gate.*`·`audit_sample.status/pending_decision`은 발행 시점 스냅샷이며 어떤 게이트도 읽지 않는다(아래 "C-2 policy 활성 정본과 파일 스냅샷"). |
| `config/order-plan-screening-phase0-binding.v1.json` / `bidops.order-plan-screening-phase0-binding.v1` | `phase0-contracts` → `phase1-screening-pipeline` | 위 provenance, `binding_version`, `status`, `created_at`, `policy`, `selection_decision`, `source_input`(raw-page manifest SHA-256 포함), `selection_evidence_population`, `stage1_binding`, `stage2_binding`, `selection_evidence`, `review_inputs`, `gold`, `external_transport`, `compatibility`, `activation`; `status=blocked|activation_candidate|approved`(v1·v2 발행값은 `blocked`, v3은 `activation_candidate` 또는 `approved`). `status=blocked`이면서 `external_transport.execution_allowed=true`인 조합은 모순이며 `binding_mismatch`로 거부한다 | 생성 후 immutable. 이 snapshot의 partial gold/current refs와 blocked transport를 바꾸려면 새 binding version을 만든다. 역사적 실험 파일은 read-only이며 binding을 맞추기 위해 소급 수정하지 않는다. |
| `screening-input.json` / `bidops.order-plan-screening-input.v1` | `order-plan-screening-orchestrator` → `order-plan-screening-worker` | `execution_id`, `source_run_id`, `source_artifact`, `population_count`, `population_sha256`, `policy`, `stage1_binding`, `stage2_binding`, `items`, `status`, `created_at`; `status=frozen` | enqueue 시점 snapshot. `items`는 `plan_id,title`만 가지며 생성 후 변경·재사용하지 않는다. |
| `screening-ranking.json` / `bidops.order-plan-screening-ranking.v1` | `order-plan-screening-bm25` → `order-plan-screening-merge` | `execution_id`, `source_run_id`, input·policy digest, `status`, `population_count`, `selected_count`, `filtered_out_count`, `items`; `status=성공|실패`, item `stage1_status=selected|filtered_out|failed|rejected` | 전체 모집단 1행/plan. `filtered_out`은 deterministic Top 300 경계이며 결과에서 삭제하지 않는다. |
| `screening-decisions.json` / `bidops.order-plan-screening-decisions.v1` | `order-plan-screening-qwen-worker` → `order-plan-screening-merge` | binding·input/ranking digest, `status`, candidate/success/failure/batch count, `batches`, `items`; `status=성공|부분 성공|실패`, relevance `relevant|not_relevant|uncertain` | 처리된 rank-contiguous batch prefix만 기록한다. 성공한 Qwen item만 기록하고 실패 batch는 failure artifact와 함께 보존하며, 중지·process interruption으로 미처리된 selected item은 이 파일에 넣지 않는다. stage1 탈락 item도 넣지 않는다. |
| `screening-failures.json` / `bidops.order-plan-screening-failures.v1` | `order-plan-screening-worker` → review·merge | `execution_id`, `source_run_id`, `status`, `failure_count`, `failures`, `created_at`; `status=none|partial|failed|rejected`, outcome `failed|rejected|unknown` | 실패는 `not_relevant`로 보정하지 않는다. `failure_type`과 안전한 `error_code`만 저장하고 prompt·response 본문은 저장하지 않는다. |
| `screening-telemetry.json` / `bidops.order-plan-screening-telemetry.v1` | `order-plan-screening-worker` → observability·merge | execution/batch/attempt measurement, `status`, `created_at`; `status=complete|partial|not_measured` | 제공되지 않은 duration·token은 `null`; 0으로 보정하지 않는다. attempt metadata만 append-only다. |
| `screening-results.json` / `bidops.order-plan-screening-result.v1` | `order-plan-screening-merge` → `postgres-loader-and-review-api` | input/policy digest, `status`, `partial_artifact`, `counts`, 전체 `items`, `created_at`; `status=성공|부분 성공|실패|거부됨` | 동일 execution+plan은 한 번만 publish. 부분 결과는 `partial_artifact=true`이고 failure와 함께 보존한다. |
| `screening-feedback.json` / `bidops.order-plan-screening-feedback.v1` | `human-review-api` → `postgres-review-history` | `feedback_id`, `execution_id`, `plan_id`, `revision`, `actor_kind`, `claimed_name`, `relevance`, `priority`, `memo`, `created_at`; relevance `relevant|not_relevant|uncertain`, priority `high|medium|low|null` | revision append-only. 기존 feedback update/delete 금지; 새 판단은 새 revision과 `supersedes_feedback_id`로 기록한다. |

full-population result item은 상태 조합도 검증한다. `filtered_out|failed|rejected`인 stage1과
처리되지 않은 selected item은 stage2 `not_attempted`와 모든 Qwen·batch·failure field
`null`을 사용한다. stage2 `success`만 relevance/score/reason과 batch/attempt를 가질 수
있고, 실패·거부·unknown은 Qwen label을 만들지 않고 안전한 failure code로 남긴다.

기존 `bidops.screening-input.v1`, `bidops.decisions.v3`, `bidops.screening.v3`와
`ScreeningExecution`은 공고 다섯 관점 판정 계약이다. C-2 v1의 relevance를 그 계약에
추가하거나 동일한 table의 의미를 재해석하지 않는다. 구 실험의 `population.json`과
선정·Qwen·gold evidence는 호환 입력·증거로만 읽는다.

`source_input.raw_manifest_sha256`는 source run의 연속된 raw page 파일명과 각 파일 byte
SHA-256의 canonical manifest digest다. validator는 이 digest와 함께 각 page의 endpoint,
query window, order-month 범위, page 번호·개수도 대조한다. raw page나 query metadata를
바꾸면 기존 binding으로는 통과하지 않으며 새 binding version과 사람 검토가 필요하다.

### C-2 상태 의미와 전이

| 값 | 의미 | 다른 값으로 자동 변환하지 않는 것 |
|---|---|---|
| `filtered_out` | BM25가 deterministic Top 300 밖으로 배치한 상태 | Qwen `not_relevant`, 적합성 등급, 추적 종료 |
| `not_relevant` | Qwen 또는 사람의 relevance label | BM25 탈락, 참여 불가, 최종 `no_go` |
| `uncertain` | relevance는 판정했지만 사람 확인이 필요한 label | `relevant`, `unknown`, 준비 완료 |
| `unknown` | 입력·응답·연결의 정보가 부족하거나 결과를 결정할 수 없음 | `not_relevant`, 성공, `null` |
| `null` | 그 field가 아직 시도되지 않았거나 해당되지 않아 값 자체가 없음 | unknown·실패·음성 relevance |
| `failed` | 시도된 단계가 timeout·transport·검증 실패 등으로 종료됨 | `not_relevant`, 성공 |
| `rejected` | preflight·binding·payload·policy 검증에서 실행을 거부함 | 모델 실패, 음성 relevance |
| `relevant` | 발주계획 제목의 선별 relevance만 의미함 | 적합성·참여 준비·`계속 추적`·최종 Go |

실행의 허용 전이는 `대기 → 실행 중 → 성공|부분 성공|실패`, `실행 중 → 중지 요청 →
중단됨`, `대기 → 중단됨`이다. `성공|부분 성공|실패|중단됨`은 terminal이며 종료 시각이
필수다. active slot은 1, queue는 FIFO, stale/process interruption은 자동 resume하지
않고 사람이 새 execution을 만든다. retryable batch failure는 `timeout`, `truncated_output`,
`schema_violation`, `id_mismatch`, `transport`에 한해 최대 2회까지며, binding·model·payload·
policy rejection은 retry하지 않는다. 재시도 후에도 결과가 없으면 failure artifact와
`human_review_required`를 남긴다. hosted provider fallback은 없다.

`relevant|not_relevant|uncertain`은 발주계획 relevance 축이다. 기존 공고의 적합성 등급·
참여 준비 상태, 사업기회의 `계속 추적|보류|종료`, 입찰 시점 사람 `go|no_go`는 서로 다른
필드와 이벤트이며 C-2 feedback이 변경하지 않는다.

### C-2 수동 REST 계약 (Phase 3 구현 입력)

새 endpoint는 기존 `/api/screening`을 확장하지 않고 아래 경로를 사용한다. v1·v2 binding은
`external_transport.execution_allowed=false`이므로 v3 발행 전까지 실행은 503, 활성화는 `activation_blocked`로
끝난다. 2026-09-18 일일 운영 계약(policy 목록·품질 게이트·감사 표본·일일 자동 실행 스위치, 트리거 헤더,
`purpose`, 목록 누적 모드)의 요청·응답 필드와 오류는 아래 "C-2 일일 운영 계약" 절이 정본이고 이 표는 요약이다.

| method / path | 요청 | 성공 응답의 필수 field | 안정 오류 |
|---|---|---|---|
| `GET /api/order-plans` | `source_run_id?`, `stage1_status?`, `stage2_status?`, `qwen_relevance?`, `human_relevance?`, `q?`, `limit=1..500`, `offset>=0` | `items`, `total`, `limit`, `offset`; item은 `order_plan_pk`, `order_plan_unty_no`, nullable 공개 `source_url`, title, agency, nullable `budget_amount`·`planned_order_year`·`planned_order_month`, source run/observation, BM25 stage status/rank/score/`nearest_capability`, Qwen stage status/score/label/reason, latest human feedback summary, 결과를 낸 `execution_id`·`policy_version`, `first_observed_at`, nullable `contract_method`·`notice_posted`(수집 원문 `Y`/`N`); `source_run_id`가 없으면 누적 모드(`order-plan-list-response.v5`, "발주계획 목록 누적 모드") | `invalid_request(422)` |
| `GET /api/order-plans/{order_plan_pk}` | path PK | 누적 plan metadata(`budget_amount`, planned year/month, nullable 공개 `source_url`, nullable `supervising_agency_name`·`procurement_method`·`contract_method`·`notice_posted`·`bid_ntice_no_list`·`published_at` 포함)와 `screening_history`, latest result/feedback; 내부 source path·object key는 반환하지 않음 | `not_found(404)` |
| `GET /api/order-plans/{order_plan_pk}/screening-history` | path PK | `order_plan_pk`, `items[]`; item은 execution/binding digest, status, BM25 `nearest_capability`, result `batch_id`·`attempt_no`, stage result, feedback revision count, 실행 행의 `execution_purpose=operational\|gate_measurement`와 nullable `execution_started_at`·`execution_finished_at` | `not_found(404)` |
| `POST /api/order-plan-screening/executions` | actor header 필수, optional `X-BidOps-Trigger: daily_script\|manual_resume\|gate_measurement`(없음 = 사람 수동 운영 실행), `execution-create-request.v1`의 `{schema_version, producer, consumer, request_id, source_run_id, policy_version}`(본문 불변) | first request `202`: `execution-create-response.v1`의 provenance와 `execution_id`, `request_id`, `source_run_id`, `policy_version`, `status=대기`, binding digest, `execution_allowed`; 같은 request ID와 같은 payload는 원래 `202` body를 replay(헤더는 hash에 들어가지 않는다) | `actor_name_required`·`actor_name_invalid`(400), `invalid_request`(422, 알 수 없는 트리거 값·측정 회차가 아닌 `gate_measurement` 포함), `source_run_incomplete`, `policy_not_active`, `binding_mismatch`, `daily_trigger_off`, `idempotency_conflict`, `active_execution_exists` (`409`), transport unavailable (`503`) — "실행 트리거 헤더와 게이트" |
| `GET /api/order-plan-screening/executions` | `source_run_id?`, `status?`, pagination | `execution-list-response.v2`: `items`, `total`, `limit`, `offset`; item에 `purpose=operational\|gate_measurement`; 내부 object key·prompt·profile 본문 없음 | `invalid_request(422)` |
| `GET /api/order-plan-screening/executions/{execution_id}` | path ID | `execution-detail-response.v2`: `purpose`, execution status, counts, binding digests, timestamps, safe artifact summaries, `attempts[]`의 batch/attempt·model/prompt/profile binding, status/failure, nullable token·duration·시각; `response_object_ref`·`plan_ids_jsonb`·artifact 본문/경로는 반환하지 않음 | `not_found(404)` |
| `POST /api/order-plan-screening/executions/{execution_id}/stop` | actor header, `execution-stop-request.v1`의 `{schema_version, producer, consumer, request_id, reason}` | `202`: `execution-stop-response.v1`의 provenance와 execution ID, `status=중지 요청`, request ID | terminal 또는 중복 다른 request (`409`), `actor_name_required` |
| `GET /api/order-plan-screening/executions/{execution_id}/artifacts/{kind}` | `kind=screening_input|ranking|decisions|failures|telemetry|screening_result` | artifact schema, producer/consumer, digest, safe metadata와 검증 상태; 본문은 승인된 다운로드 경계에서만 | `artifact_kind_invalid`, `artifact_not_ready`, `not_found` |
| `GET /api/order-plans/{order_plan_pk}/screening-feedback` | path PK, `execution_id?` | `items[]`; revision, relevance, nullable priority/memo, claimed actor, created_at | `not_found(404)` |
| `POST /api/order-plans/{order_plan_pk}/screening-feedback` | actor header, `feedback-create-request.v1`의 `{schema_version, producer, consumer, request_id, execution_id, relevance, priority, memo, expected_revision?}` | `201`: `feedback-create-response.v1`의 provenance와 feedback ID, plan/execution, revision, labels, actor 표식, created_at | `feedback_conflict`, `idempotency_conflict`, `not_found`, `actor_name_required` |
| `GET /api/order-plan-screening/policies` | 없음 | `policy-list-response.v1`: `items[]`(version·상태·`quality_gate_status`·digest·`activated_at`), `total` | — |
| `GET /api/order-plan-screening/policies/{policy_version}` | path version | `policy-inspect-response.v1`: 행 요약, 컨테이너 파일 존재, `external_transport`·`audit_sample` 설정값, 선택된 게이트, `activation_allowed`, **런타임 계산** `blockers[]`(파일의 `activation.blockers`는 읽지 않음); prompt·profile 본문 없음 | `not_found(404)` |
| `POST /api/order-plan-screening/policies/candidate` | actor header, `policy-candidate-request.v1`의 `{schema_version, producer, consumer, request_id, policy_version, base_policy_sha256, candidate_sha256, reason}` | `201`: `policy-candidate-response.v1`의 provenance와 `activation_candidate` version/status/digest | `actor_name_*`(400), `invalid_request`(422), `not_found`(404), `idempotency_conflict`·`immutable_conflict`(409) |
| `POST /api/order-plan-screening/policies/{policy_version}/activate` | actor header, `policy-activate-request.v1`의 `{schema_version, producer, consumer, request_id, policy_sha256, quality_gate_artifact_sha256, explicit_confirmation}` | `200`: `policy-activate-response.v1`의 provenance와 active status·gate/evaluation·이전 active version·audit ID | `actor_name_*`(400), `not_found`(404), `immutable_conflict`(409, digest mismatch), `activation_blocked`(409, `details.blockers[]`), `invalid_request`(422, 확인 없음), `idempotency_conflict`(409). 검증 순서는 "활성화 검증 순서" |
| `POST /api/order-plan-screening/quality-gates` | actor header, `order-plan-quality-gate-create-request.v1` | `201`: `order-plan-quality-gate-response.v1` | `actor_name_*`(400), `invalid_request`(422), `not_found`(404), `immutable_conflict`·`idempotency_conflict`(409) |
| `GET /api/order-plan-screening/quality-gates` | required `policy_version` | `order-plan-quality-gate-list-response.v1`: gate와 최신 evaluation, 측정 실행 목록 | `invalid_request`(422), `not_found`(404) |
| `POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations` | actor header, `order-plan-quality-evaluation-create-request.v1` | `201`: `order-plan-quality-evaluation-response.v1`(코드가 판정한 `result_status`와 나쁜 쪽 `measured_*`) | `actor_name_*`(400), `invalid_request`(422), `not_found`(404), `immutable_conflict`·`idempotency_conflict`(409) |
| `GET /api/order-plan-screening/executions/{execution_id}/audit-sample` | path ID | `audit-sample-preview-response.v1`(미저장 계산 또는 이미 기록된 표본) | `not_found`(404), `execution_not_completed`(409) |
| `POST /api/order-plan-screening/executions/{execution_id}/audit-sample` | actor header, optional `X-BidOps-Trigger`, `audit-sample-draw-request.v1` | `201` 첫 기록 / `200` 기존 표본·`pending_human_approval`·`not_applicable`: `audit-sample-draw-response.v1` | `actor_name_*`(400), `invalid_request`(422), `not_found`(404), `execution_not_completed`·`immutable_conflict`·`idempotency_conflict`(409) |
| `GET /api/order-plan-screening/daily-trigger` | 없음 | `daily-trigger-state-response.v1`: `effective_enabled`, active `policy_version`·`policy_sha256`, `switch`, `reasons[]` | — |
| `POST /api/order-plan-screening/daily-trigger` | actor header, `daily-trigger-set-request.v1` | `201`: `daily-trigger-set-response.v1` | `actor_name_*`(400), `invalid_request`(422), `idempotency_conflict`(409) |

발주계획의 사람 추적 시작은 C-2 relevance와 별도인
`POST /api/opportunities/order-plan-tracking/preview`·`bulk-start`·`bulk-end` 계약을 사용한다
(상세 wire·원자성·receipt 규칙은 [사업기회와 추적](#사업기회와-추적)의
`발주계획 일괄 추적 v1 wire·원자성`에 있다). 기존 C-2 screening execution을 만들거나
`GET/POST /api/order-plans/{order_plan_pk}/tracking-decisions`를 호출하지 않는다.
이 endpoint들은 API의 결과 확인·추적 결정을 위한 것이며 C-2 실행·모델 활성화·최종 입찰
결정을 의미하지 않는다.

actor header `X-BidOps-Actor-Name`은 인증이 아닌 감사 표식이다. request body에 actor를
중복해서 받지 않으며, API 응답·error details에는 prompt/profile/model response 본문,
secret, 로컬 경로, object key를 넣지 않는다. `request_id`가 다른 동일 execution mutation은
idempotency conflict로 거부한다.

REST body와 JSON response의 wire schema도 v1로 고정한다. GET query 자체에는 body
provenance를 요구하지 않지만 response envelope에는 항상 `schema_version`, `producer`,
`consumer`가 포함된다. 아래 schema family 외의 field 추가나 status 의미 변경은 새 wire
schema version을 만들며, 기존 C-2 v1 consumer는 알 수 없는 version을 거부한다.

| wire schema | producer → consumer | endpoint | 필수 key / status enum | 호환·불변 경계 |
|---|---|---|---|---|
| `order-plan-list-response.v5` | `order-plan-review-api` → `order-plan-review-client` | `GET /api/order-plans` | provenance, `scope`(`mode=cumulative\|run`), `items`, `total`, `limit`, `offset`; item의 nullable 공개 `source_url`, 예산·계획 시기·BM25 `nearest_capability`와 stage status/label/score, nullable `execution_id`·`policy_version`·`first_observed_at`·`contract_method`·`notice_posted` | response projection only; 내부 경로·본문 금지. v3은 2026-09-18 누적 모드와 함께, v4는 2026-09-21 계약·공고 두 field와 함께 폐기("발주계획 목록·상세 실무 field") |
| `order-plan-detail-response.v4` | API → client | `GET /api/order-plans/{id}` | provenance, plan metadata의 nullable 공개 `source_url`, `budget_amount`·계획 시기·`supervising_agency_name`·`procurement_method`·`contract_method`·`notice_posted`·`bid_ntice_no_list`·`published_at`, `screening_history`; history의 `nearest_capability`·`batch_id`·`attempt_no`·`execution_purpose`·실행 시각 | read-only projection; 기존 notice response와 혼용 금지. v3은 2026-09-21 폐기("발주계획 목록·상세 실무 field") |
| `order-plan-detail-response.v5` | API → client | `GET /api/order-plans/{id}/screening-history` | provenance, `order_plan_pk`, `items[]`(상세의 `screening_history`와 같은 항목 모델) | 상세와 **같은 family 이름**을 쓰고 번호만 따로 올려 왔다(옛 v1). 번호는 family 안에서 한 번만 쓰므로 v5다 — 같은 문자열이 두 모양을 뜻하지 않는다 |
| `execution-create-request.v1` / `execution-create-response.v1` | `human-review-client` → `screening-api` → client | execution POST | request provenance, `request_id`, source/policy; response provenance, `execution_id`, `status=대기` | exact replay만 허용; request payload·binding snapshot immutable |
| `execution-list-response.v2` / `execution-detail-response.v2` | `screening-api` → client | execution GET | provenance, `items`/execution, `purpose=operational\|gate_measurement`, counts, timestamps, safe artifact summaries; detail `attempts[]`에는 binding(model/prompt/profile 및 digest), status/failure, nullable token·duration·시각만 projection; status `대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨` | status meaning fixed(v1과 같음); v2는 `purpose` 추가; `response_object_ref`·`plan_ids_jsonb`·prompt/profile/model response body 없음 |
| `execution-stop-request.v1` / `execution-stop-response.v1` | `human-review-client` → `screening-api` → client | stop POST | request provenance, `request_id`, `reason`; response provenance, execution ID, `status=중지 요청` | terminal transition and idempotency rules fixed |
| `artifact-summary-response.v1` | `screening-api` → client | artifact GET | provenance, `kind`, `schema_version`, `producer`, `consumer`, digest, validation status | safe metadata only; bytes download is separately authorized |
| `feedback-list-response.v1` / `feedback-create-request.v1` / `feedback-create-response.v1` | `review-api` ↔ client / `postgres-history` | feedback GET/POST | request provenance plus `request_id`, execution, relevance `relevant|not_relevant|uncertain`, priority `high|medium|low|null`; response feedback ID/revision | append-only revision; no grade/readiness/tracking/go-no-go mutation |
| `policy-list-response.v1` / `policy-inspect-response.v1` / `policy-candidate-request.v1` / `policy-candidate-response.v1` / `policy-activate-request.v1` / `policy-activate-response.v1` | `human-review-client` → `policy-api` → `human-review-client` | policy GET/POST | provenance, policy/binding digest, `activation_allowed`, 런타임 `blockers[]`; policy status `draft\|activation_candidate\|active\|retired` | blocker와 활성화 검증은 같은 런타임 조건을 쓴다. 파일의 상태성 필드는 읽지 않는다. activation requires explicit audit approval |
| `order-plan-quality-gate-create-request.v1` / `order-plan-quality-gate-response.v1` / `order-plan-quality-gate-list-response.v1` / `order-plan-quality-evaluation-create-request.v1` / `order-plan-quality-evaluation-response.v1` | `human-review-client` → `quality-gate-api` → `human-review-client` | quality-gates GET/POST | provenance, gate digest·임계값(nullable)·`evaluation_basis`·측정 회차; evaluation `result_status=통과\|미달\|미측정\|보류`, 나쁜 쪽 `measured_*` | gate immutable, evaluation append-only revision. 코드는 채점하지 않고 판정 규칙만 적용 |
| `audit-sample-preview-response.v1` / `audit-sample-draw-request.v1` / `audit-sample-draw-response.v1` | `human-review-client` → `audit-sample-api` → `human-review-client` | audit-sample GET/POST | provenance, `status=preview\|drawn\|pending_human_approval\|not_applicable`, `sample[]`\|null | 결정적 계산; 기록은 append-only·무복원 |
| `daily-trigger-state-response.v1` / `daily-trigger-set-request.v1` / `daily-trigger-set-response.v1` | `human-review-client` → `daily-trigger-api` → `human-review-client` | daily-trigger GET/POST | provenance, `effective_enabled`, `reasons[]`, 버전에 묶인 `switch` | 스위치 행 append-only; 대상은 현재 active 버전만 |

### C-2 일일 운영 계약 (2026-09-18, ADR-0060·0061)

[ADR-0060](tracking/decisions/0060-c2-policy-db-row-authority.md)(policy 활성 정본·게이트·트리거)과
[ADR-0061](tracking/decisions/0061-daily-collection-window.md)(발주계획 하루·공고 4일 수집 창)의 wire 정본이다. 아래 표의 요청·응답
필드와 오류 코드를 그대로 구현한다. 동작 서술은 `docs/0918_daily-operation/spec.md` §1·§3~§5·§7·§8이다.

#### 공통 규칙

- 요청 body는 기존 C-2 관례를 따른다 — `schema_version`(`<name>-request.v1`), `producer: human-review-client`,
  endpoint별 `consumer`, UUID `request_id`, 열거하지 않은 field 거부. body가 이 검증을 통과하지 못하면 FastAPI 기본 422
  `{"detail":[...]}`다. 그 밖의 오류는 C-2 envelope `{"error":{"code","message","details"},"request_id"}`다.
  `details`는 아래에서 따로 적은 곳(`activation_blocked`·`daily_trigger_off`)만 채우고 나머지는 `null`이다.
- 응답은 `schema_version`·`producer`·`consumer`(`human-review-client`)를 갖는다.
- 모든 POST는 `X-BidOps-Actor-Name`(+`X-BidOps-Actor-Name-Format`)이 필수다. 없으면 `actor_name_required(400)`,
  형식 위반·`system`이면 `actor_name_invalid(400)`(`core/api_errors.py:103`). actor는 body에 넣지 않는다.
- 모든 POST는 `request_id`로 idempotent하다. 같은 operation·같은 `request_id`·같은 body hash는 원래 응답을 같은
  status로 replay하고, body가 다르면 `idempotency_conflict(409)`다(`IdempotencyRecord`, operation 이름은 각 절).
- `invalid_request`는 422, `not_found`는 404, 상태·digest 충돌은 409, transport 미준비는 503이다.
- 응답·오류·audit에는 prompt·회사 역량 본문, 모델 응답, 내부 경로, object key를 넣지 않는다.
- digest는 64자 lowercase hex SHA-256이다.

#### C-2 policy 활성 정본과 파일 스냅샷

- **활성 여부의 정본은 `order_plan_screening_policy` 행이다**(`policy_status`·`quality_gate_status`·`active_slot`). 운영
  실행 게이트는 행의 `policy_status='active' ∧ quality_gate_status='passed'`와 digest 일치만 본다. policy 파일 payload의
  `policy_status`는 enum 유효성(`draft|activation_candidate|active|retired`)만 검사하고 게이트 값으로 쓰지 않는다.
  worker는 파일과 binding의 `policy_status`가 **서로 같은지**만 확인한다.
- **파일의 상태성 필드는 발행 시점 스냅샷이며 어떤 게이트·blocker·스위치도 읽지 않는다** — policy의 `policy_status`,
  `activation.status/enabled/approved_by/approved_at/blockers`, `quality_gate.status/targets/human_adjudication_count/
  draft_label_count/remaining_confirmation_count/activation_eligible`, `audit_sample.status/pending_decision`.
  파일 schema(`bidops.order-plan-screening-policy.v1`)는 바뀌지 않는다.
- 파일에서 읽는 것은 **설정값뿐**이다 — policy `audit_sample.enabled`·`max_per_execution`·`review_cadence`·`strata`·
  `selection_order`·`replacement`, binding `external_transport.execution_allowed`·`approval_scope`·`approved_by`·
  `approved_at`·`approval_required_per_execution`. v3 policy의 `quality_gate.targets`는 `null`로 발행하고 기존
  `audit_sample.sample_size`는 v3에서 쓰지 않는다(`null`).
- **임계값 4개의 정본은 DB 게이트 행**(`threshold_*`)이다.
- binding `status`는 `blocked|activation_candidate|approved`를 받는다. `status=blocked ∧ external_transport.
  execution_allowed=true`는 서비스·worker가 `binding_mismatch`로 거부한다.
- **digest는 파일 bytes 기준**이다(canonical 재직렬화 아님). 운영 컨테이너의 `BIDOPS_C2_POLICY_PATH`·
  `BIDOPS_C2_BINDING_PATH`에 digest가 일치하는 일반 파일(symlink 아님)이 있어야 한다. 없으면 실행은
  `binding_mismatch`, 조회·활성화는 blocker `policy_file_missing`이다.
- 전송 승인의 단위는 binding 튜플(policy, binding, `model_digest`, allowlist)이다. `approval_scope="per_binding"`,
  `approval_required_per_execution=false`. payload 형태 승인과 digest 일치 검사는 실행마다 그대로다.

#### 실행 트리거 헤더와 게이트

`POST /api/order-plan-screening/executions`의 요청 헤더 `X-BidOps-Trigger`:

| 헤더 값 | 뜻 | policy 행 조건 | 추가 검사 | `purpose` |
|---|---|---|---|---|
| (없음) | 사람의 수동 운영 실행 | `active` ∧ `quality_gate_status='passed'` | — (기존 동작과 같다) | `operational` |
| `daily_script` | 일일 스크립트(cron 설치자의 옵트인) | 같음 | 일일 자동 실행 `effective_enabled`를 다시 계산해 거짓이면 `daily_trigger_off(409)`, `details.reasons[]`는 스위치 조회의 `reasons[]`와 같다. 요청 `policy_version`이 현재 active 버전이 아니면 `policy_not_active(409)` | `operational` |
| `manual_resume` | 사람이 한도를 넘긴 회차에 `--extra-attempt`로 추가 시도 | 같음 | `daily_script`와 같다 | `operational` |
| `gate_measurement` | 품질 게이트 측정 전용 실행 | `activation_candidate` 또는 `active`. `quality_gate_status`는 보지 않는다. 아니면 `policy_not_active(409)` | `source_run_id`가 그 policy_version의 gate 중 하나의 `measurement_run_ids`에 있어야 한다. 아니면 `invalid_request(422)`. 일일 스위치·환경 cap은 보지 않는다 | `gate_measurement` |
| 그 외 값·빈 문자열 | — | — | `invalid_request(422)` | — |

- 네 경우 모두 digest 일치·파일 존재·`BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `execution_allowed`(아니면 503
  `service_unavailable`)·`active_execution_exists`(active slot 1)는 같다.
- 헤더는 요청 hash에 들어가지 않는다. idempotency는 `request_id`와 body로만 판정하므로 같은 `request_id`·같은 body를
  다른 헤더로 다시 보내면 원래 응답이 replay된다.
- audit `c2.execution_created`의 `safe_metadata.trigger`에 헤더 값(없으면 `null`)을 남긴다. `actor_kind`는 언제나
  `human`이다.
- 요청 body `execution-create-request.v1`은 바뀌지 않는다. 응답 `execution-create-response.v1`도 그대로다.
- `execution-list-response.v2`·`execution-detail-response.v2`는 v1 field 전체에 `purpose`
  (`operational|gate_measurement`)를 더한다. 목록 query는 바뀌지 않는다.
- `gate_measurement` 실행은 누적 투영·워크로드·감사 표본 draw에서 빠진다.

#### policy REST

operation 이름: `c2_policy_candidate`, `c2_policy_activate`.

**`PolicySummary`**(목록 item과 단건의 공통 field): `policy_version`, `policy_status=draft|activation_candidate|active|retired`,
nullable `quality_gate_status=not_measured|measured|passed|failed`, `policy_sha256`, `binding_sha256`, `created_by`,
`created_at`, nullable `activated_by`, nullable `activated_at`. `activated_at`은 retire 뒤에도 남는다(누적 범위 판정에 쓴다).

| endpoint | 요청 | 성공 응답 | 오류 |
|---|---|---|---|
| `GET /api/order-plan-screening/policies` | 없음 | `200` `policy-list-response.v1`: `items[]: PolicySummary`(`created_at` 내림차순), `total` | — |
| `GET /api/order-plan-screening/policies/{policy_version}` | path | `200` `policy-inspect-response.v1`: `PolicySummary` 전체 + `binding_status`(binding payload `status` 원문), `policy_file_present`·`binding_file_present`(컨테이너 경로에 digest 일치 파일), `external_transport={execution_allowed?, approval_scope?, approved_by?, approved_at?, approval_required_per_execution?}`(binding 값, 없으면 `null`), `audit_sample={enabled?, max_per_execution?, review_cadence?}`(policy 값, 없으면 `null`), nullable `quality_gate={gate_id, evaluation_basis, thresholds_decided, latest_evaluation: {evaluation_id, revision, result_status, artifact_sha256, evaluated_at}?}`(아래 "선택된 게이트"), `activation_allowed`, `blockers[]: {code, detail?}` | `not_found(404)` |
| `POST /api/order-plan-screening/policies/candidate` | `policy-candidate-request.v1`: `schema_version`, `producer`, `consumer=policy-api`, `request_id`, `policy_version`, nullable `base_policy_sha256`, `candidate_sha256`, `reason`(공백 아님, ≤500자) | `201` `policy-candidate-response.v1`: `request_id`, `policy_version`, `policy_status=activation_candidate`, `policy_sha256`, `binding_sha256`, `audit_event_id` | `not_found(404)` 버전 없음; `immutable_conflict(409)` — `candidate_sha256`≠행 `policy_sha256`, `base_policy_sha256`≠현재 active 행 digest(active가 없으면 `null`만 허용), 행이 `draft`가 아님; `invalid_request(422)` 공백 사유; `idempotency_conflict(409)` |
| `POST /api/order-plan-screening/policies/{policy_version}/activate` | `policy-activate-request.v1`: `schema_version`, `producer`, `consumer=policy-api`, `request_id`, `policy_sha256`, `quality_gate_artifact_sha256`, `explicit_confirmation`(bool, 필수) | `200` `policy-activate-response.v1`: `request_id`, `policy_version`, `policy_status=active`, `quality_gate_status=passed`, `policy_sha256`, `binding_sha256`, `gate_id`, `evaluation_id`, nullable `previous_active_policy_version`, `activated_by`, `activated_at`, `audit_event_id` | 아래 "활성화 검증 순서" |

`explicit_confirmation`은 schema에서 `true`로 고정하지 않는다. `false`도 body 검증은 통과하고 검증 순서 8번에서
`invalid_request`로 거부된다 — blocker 판정이 확인 누락보다 먼저 보이게 하려는 것이다.

**런타임 blocker** — 단건 GET과 활성화 POST가 같은 조건으로 계산한다. payload의 `activation.blockers`·
`quality_gate.activation_eligible`은 읽지 않는다. `blockers[]`는 다음 순서로 실패한 것을 모두 싣는다.

| code | 조건 | `detail` |
|---|---|---|
| `quality_gate_missing` | 선택할 수 있는 게이트가 없다 | `null` |
| `quality_gate_thresholds_undecided` | 선택된 게이트의 `threshold_*` 중 하나라도 `NULL`(D-b 미결정) | `null` |
| `quality_gate_not_passed` | 선택된 게이트의 최신 evaluation이 없거나 `통과`가 아님 | `미측정`·`미달`·`보류` 또는 `none`(evaluation 없음) |
| `audit_sample_policy_unapproved` | policy `audit_sample.enabled is not True` 또는 `max_per_execution`·`review_cadence` 중 하나라도 없음(D-c) | `null` |
| `execution_transport_not_allowed` | binding `external_transport.execution_allowed is not True`, `approval_scope != "per_binding"`, `approved_by`·`approved_at` 중 하나라도 비어 있음(D-d) | `null` |
| `binding_digest_mismatch` | binding payload의 `policy.sha256`≠행 `policy_sha256`, `policy.policy_version`≠행 버전, `status`가 허용값 밖, 또는 `blocked ∧ execution_allowed=true` | `null` |
| `policy_file_missing` | 컨테이너 경로에 digest 일치 파일이 없음 | `policy`·`binding`·`both` |

- **선택된 게이트**: 같은 `policy_version`이고 `evaluation_basis='product_rerun'`이며 `policy_sha256`·`binding_sha256`이
  행과 같은 게이트만 후보다(`reference_artifact_rescore`·digest 불일치 게이트는 후보가 아니다). 후보 중 임계값이 모두
  있고 최신 evaluation이 `통과`인 첫 게이트(`created_at` 내림차순, 같으면 `gate_id` 내림차순)를 고르고, 없으면 가장 최근
  후보를 고른다. 후보가 없으면 `quality_gate=null`이고 blocker는 `quality_gate_missing`이다.
- `activation_allowed = (policy_status == 'activation_candidate') ∧ blockers == []`. 이때 선택된 게이트의 최신 evaluation
  `artifact_sha256`로 활성화를 요청하면 검증 3~7번을 통과한다 — 조회와 활성화의 답이 갈리지 않는다.
- 환경 변수 `BIDOPS_C2_EXECUTION_ALLOWED`는 활성화 조건이 아니다. 실행과 일일 스위치가 따로 본다.

**활성화 검증 순서** — 한 transaction에서, 대상 policy 행을 `with_for_update()`로 잠근 채 순서대로 검사한다. 게이트 행은
잠그지 않는다 — app 역할은 게이트 테이블에 UPDATE 권한이 없어 `FOR UPDATE`를 쓸 수 없고(0029 권한), evaluation 기록도
같은 policy 행을 잠가 활성화와 직렬화한다. actor 헤더(400)·body(422)·idempotency replay/`idempotency_conflict`(409)는 이보다 먼저다.

| # | 검사 | 실패 |
|---|---|---|
| 0 | `policy_version` 행이 있다 | `not_found(404)` |
| 1 | 행이 `activation_candidate` | `activation_blocked(409)`, blocker `policy_not_candidate`(`detail`=현재 상태) |
| 2 | 요청 `policy_sha256` == 행 값 | `immutable_conflict(409)` |
| 3 | 요청 `quality_gate_artifact_sha256`와 같은 `artifact_sha256`의 evaluation이 있고, 그것이 **그 gate의 최신 revision**이다 | `activation_blocked(409)`, `quality_gate_artifact_unknown` 또는 `quality_gate_evaluation_not_latest` |
| 4 | `result_status='통과'` ∧ gate `evaluation_basis='product_rerun'` ∧ gate `policy_sha256`·`binding_sha256` == 행 ∧ binding payload 일관성 ∧ 파일 존재 | `activation_blocked(409)`, `quality_gate_not_passed`·`quality_gate_basis_not_product_rerun`·`quality_gate_digest_mismatch`·`binding_digest_mismatch`·`policy_file_missing` |
| 5 | 그 gate의 임계값 4개가 모두 있다(D-b) | `activation_blocked(409)`, `quality_gate_thresholds_undecided` |
| 6 | policy `audit_sample` 설정이 있다(D-c) | `activation_blocked(409)`, `audit_sample_policy_unapproved` |
| 7 | binding `external_transport` 승인이 있다(D-d) | `activation_blocked(409)`, `execution_transport_not_allowed` |
| 8 | `explicit_confirmation is True` | `invalid_request(422)` |
| 9 | 기존 active 행을 `retired`·`active_slot=NULL`로 내리고 flush한 뒤 대상을 `active`·`active_slot=1`·`quality_gate_status='passed'`·`activated_by/at`으로 올린다 | unique index 위반은 rollback 후 `activation_blocked(409)`, blocker `active_slot_conflict`. **unique index가 최종 심판이다** |

- 1·2번은 첫 실패에서 멈춘다. 3~7번은 모두 평가하고 실패한 blocker를 이 순서로 `details.blockers[]`에 모두 싣는다
  (`details = {"blockers": [{code, detail}]}`). `policy_not_candidate`·`quality_gate_artifact_unknown`·
  `quality_gate_evaluation_not_latest`·`quality_gate_basis_not_product_rerun`·`quality_gate_digest_mismatch`·
  `active_slot_conflict`는 활성화 요청에만 나오는 code다(조회는 특정 artifact를 받지 않는다).
- 감사: 대상에 `AuditEvent(actor_kind="human", action="c2.policy_activated", aggregate_type="order_plan_screening_policy",
  aggregate_id=policy_version, safe_metadata={from_status, to_status, policy_sha256, binding_sha256,
  quality_gate_artifact_sha256, evaluation_id, previous_active_policy_version})`. 내려간 이전 active 행에는
  `action="c2.policy_retired"`(`safe_metadata={from_status:"active", to_status:"retired", replaced_by_policy_version}`)를
  같은 transaction에 남긴다. 후보 지정은 `action="c2.policy_candidate_set"`이다.
- 같은 `c2.policy_retired`를 운영 명령 `python -m app.screening.c2_policy retire`도 남긴다(교체 없는 retire). 그때는
  `safe_metadata={from_status:"active", to_status:"retired", replaced_by_policy_version:null, reason, via:"cli"}`이고
  `request_id`는 `null`이다 — 소비자는 `replaced_by_policy_version`이 `null`일 수 있다고 읽는다.
- 새 버전을 활성화하면 그 버전에는 일일 스위치 행이 없으므로 자동 실행은 꺼진다(아래 스위치 절).

#### 품질 게이트 REST

operation 이름: `c2_quality_gate_create`, `c2_quality_evaluation_create`. 코드는 **채점하지 않는다** — 사람이 만든 gate
artifact의 값을 기록하고 연결과 판정 규칙만 검사한다.

**`GateView`**: `gate_id`(`c2gate-` + 32 hex, 서버 생성), `policy_version`, `policy_sha256`, `binding_sha256`,
`gold_manifest_sha256`, `gold_artifact_sha256`, `gold_status`(문자열 원문), `scoring_input_sha256`,
`evaluation_basis=product_rerun|reference_artifact_rescore`, `scoring_unit=per_published_day`,
`measurement_run_ids[]`(요청 순서 보존), `required_pass_count=2`, `thresholds={recall_pct?, precision_pct?,
important_missed_max?, review_load_max?}`, `created_by`, `created_at`, nullable `latest_evaluation: EvaluationView`.

`scoring_input_sha256`은 측정 전에 고정되는 채점 입력의 digest다 — canonical JSON(정렬 키·UTF-8·최소 구분자·끝
개행 없음) `{schema_version:"bidops.c2-gate-scoring-input.v1", gold_artifact_sha256, gold_manifest_sha256,
measurement_run_ids(정렬), scoring_tool_sha256, scoring_unit, candidate_rule, important_rule}`의 sha256이며
`scripts/score-c2-gate.py scoring-input`이 계산한다. 측정 결과를 바꾸지 않고 점수만 바꿀 수 있는 것(gold, 측정
회차 집합, 채점 도구, 후보·중요 규칙)이 전부 들어가므로, 채점 때 다시 계산해 이 값과 대조하면 게이트 생성 뒤의
교체를 잡는다. 서버는 이 값을 대조하지 않고 기록만 한다(코드는 채점하지 않는다).

**`EvaluationView`**: `evaluation_id`(불투명 문자열), `gate_id`, `revision`(1부터), `result_status=통과|미달|미측정|보류`,
`pass_execution_ids={pass_1: [UUID], pass_2: [UUID]?}`, nullable `measured_recall_pct`·`measured_precision_pct`·
`measured_important_missed`·`measured_review_load`, `metrics={pass_1, pass_2?, agreement_pct?, reference_full_window?}`,
`reasons[]`, `artifact_sha256`, `evaluated_by`, `evaluated_at`.

`PassMetrics` = `{recall_pct?, precision_pct?, important_missed?, review_load?}`. pct는 0~100 숫자(소수 넷째 자리까지 —
저장 열 `Numeric(7,4)`, 임계값·`agreement_pct`도 같다), 나머지는 0 이상 정수, 모두 nullable. 문자열 숫자·bool은 거부한다.
품질 게이트 응답의 `producer`는 `quality-gate-api`다. recall·precision·중요 누락은 그 pass의 게시일별 결과를 합산한 값, `review_load`는 게시일별 검토 후보 수의
**최댓값**(하루 기준)이다.

| endpoint | 요청 | 성공 응답 | 오류 |
|---|---|---|---|
| `POST /api/order-plan-screening/quality-gates` | `order-plan-quality-gate-create-request.v1`: `schema_version`, `producer`, `consumer=quality-gate-api`, `request_id`, `policy_version`, `policy_sha256`, `binding_sha256`, `gold_manifest_sha256`, `gold_artifact_sha256`, `gold_status`(1~32자, 저장 열 `String(32)`), `scoring_input_sha256`, `evaluation_basis`, `measurement_run_ids`(1개 이상, 중복 없음), `threshold_recall_pct`, `threshold_precision_pct`, `threshold_important_missed_max`, `threshold_review_load_max`(네 key 모두 필수, 값은 **`null` 허용**) | `201` `order-plan-quality-gate-response.v1`: `GateView`(`latest_evaluation=null`) + `request_id` | `not_found(404)` policy 없음; `immutable_conflict(409)` 요청 digest≠policy 행; `invalid_request(422)` 없는 `Run`·중복 회차·범위 밖 임계값; `idempotency_conflict(409)` |
| `GET /api/order-plan-screening/quality-gates?policy_version=…` | required query `policy_version` | `200` `order-plan-quality-gate-list-response.v1`: `policy_version`, `items[]: GateView + measurement_executions[]`(`created_at` 내림차순). `measurement_executions`는 `purpose='gate_measurement'`·같은 policy_version·`source_run_id ∈ measurement_run_ids`인 실행의 `{execution_id, source_run_id, status, queued_at, finished_at?}`(읽기 전용) | `invalid_request(422)` query 없음; `not_found(404)` policy 없음 |
| `POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations` | `order-plan-quality-evaluation-create-request.v1`: `schema_version`, `producer`, `consumer=quality-gate-api`, `request_id`, `artifact_sha256`, `pass_execution_ids={pass_1: [UUID], pass_2: [UUID]?}`, `pass_metrics={pass_1: PassMetrics, pass_2: PassMetrics?}`, nullable `agreement_pct`(0~100), nullable `reference_full_window: PassMetrics`, `reasons[]`(각 ≤500자, 0~20개) | `201` `order-plan-quality-evaluation-response.v1`: `EvaluationView` + `request_id` | `not_found(404)` gate 없음; `invalid_request(422)` 아래 연결 검사 실패; `immutable_conflict(409)` 다른 evaluation이 이미 쓴 `artifact_sha256`; `idempotency_conflict(409)` |

연결 검사(실패하면 기록하지 않고 `invalid_request`):

- `product_rerun` gate: 있는 pass마다 실행 id가 모두 존재하고 `purpose='gate_measurement'`이며 policy·binding digest가
  gate와 같고, 그 pass의 `source_run_id` 집합이 gate의 `measurement_run_ids`와 **정확히 같다**(회차당 실행 하나). 한
  실행이 두 pass에 같이 나오면 안 된다. `pass_2`가 없으면 `pass_metrics.pass_2`도 없어야 한다.
- `reference_artifact_rescore` gate: 제품 실행이 없으므로 각 pass의 실행 id 목록은 빈 목록이어야 한다. 서버가
  `reasons`에 고정 code `not_product_pipeline_result`("제품 파이프라인이 낸 결과가 아님")를 **항상** 넣는다. 이 gate의
  evaluation은 `통과`여도 활성화를 열지 못한다(활성화 4번).

판정 규칙(코드가 계산, 위에서부터 첫 일치, **하나라도 미달이면 차단**):

| 조건 | `result_status` | 서버가 `reasons`에 넣는 code |
|---|---|---|
| gate 임계값 중 하나라도 `NULL` | `미측정` | `thresholds_undecided` |
| pass가 2개 미만, 있는 pass의 측정값 중 하나라도 `null`, 또는 `product_rerun`에서 pass 실행 중 status가 `성공`이 아닌 것이 있음(`부분 성공` 포함) | `보류` | `pass_count_below_required`·`measurement_missing`·`pass_execution_not_success` 중 해당하는 것 전부 |
| 두 pass 모두 네 지표 충족(recall·precision ≥ 임계값, 중요 누락·검토량 ≤ 임계값) | `통과` | — |
| 어느 pass든 하나라도 미달 | `미달` | 미달 지표마다 `threshold_not_met:recall_pct`·`threshold_not_met:precision_pct`·`threshold_not_met:important_missed`·`threshold_not_met:review_load` |

- **`measured_*`는 나쁜 쪽 값이다** — recall·precision은 있는 pass 중 작은 값, 중요 누락·검토량은 큰 값. 있는 pass 중 하나라도
  그 지표가 `null`이면 그 `measured_*`는 `null`이다. 계산 불가를 통과로 바꾸지 않는다.
- revision은 gate마다 1부터 증가하고 이전 evaluation은 바뀌지 않는다(append-only). "최신"은 가장 큰 revision이다.
- `artifact_sha256`는 전체 evaluation에서 유일하다 — 활성화 요청의 artifact digest가 gate와 evaluation을 특정한다.
- 감사: `c2.quality_gate_created`, `c2.quality_evaluation_recorded`(`safe_metadata={gate_id, revision, result_status,
  evaluation_basis, artifact_sha256}`).

#### 감사 표본 REST

operation 이름: `c2_audit_sample_draw`. 입력은 그 실행의 `stage1_status='filtered_out'` 결과 행이고, 설정은 그 실행이
고정한 policy payload의 `audit_sample`에서 읽는다.

**`AuditSampleView`**(미리보기와 기록의 공통 field): `execution_id`, `status=preview|drawn|pending_human_approval|not_applicable`,
nullable `reason`, nullable `pending_decision`, `policy_version`, `policy_sha256`, `population_count`, `filtered_out_count`,
nullable `max_per_execution`, nullable `review_cadence`, nullable `sample[]`, nullable `drawn_by`, nullable `drawn_at`.
`sample` item은 `order_plan_pk`, `order_plan_unty_no`, nullable `title`, `stratum=classification_proximity|
performance_similarity_proximity|uniform_hash`, `selection_rank`(1부터), `plan_id_sha256`(통합번호 UTF-8의 SHA-256),
`stage1_rank`, `stage1_score`, nullable `nearest_capability`다.

상태 결정(위에서부터 첫 일치):

| 조건 | `status` | 나머지 field |
|---|---|---|
| 실행 status가 `성공`·`부분 성공`이 아님 | — | `execution_not_completed(409)` |
| 실행 `purpose='gate_measurement'` | `not_applicable` | `reason="execution.purpose.gate_measurement"`, `sample=null` |
| `population_count` ≤ policy stage1 top_k(현재 300) | `not_applicable` | `reason="stage1.population.at_or_below_top_k"`, `sample=null` |
| `audit_sample.enabled is not True` 또는 `max_per_execution`·`review_cadence` 중 하나라도 없음 | `pending_human_approval` | `pending_decision="max_per_execution_and_review_cadence"`, `sample=null`. **값을 추정하지 않는다** |
| 탈락 > N인데 층 규칙이 없거나 규칙·`strata`·`selection_order`·`replacement` 형식이 틀림 | `pending_human_approval` | `pending_decision="audit_sample_strata_rules"`, `sample=null` |
| 이미 기록된 행이 있음 | `drawn` | 기록된 행 |
| 그 밖 | GET `preview` / POST `drawn` | 계산한 표본 |

- 형태: 실행당 상한 N(`max_per_execution`)건, 탈락이 N 이하면 전건. 각 건은 정책 `strata` 우선순위에서 처음 일치하는
  층 **하나에만** 배정되고(`replacement: none`), 순서는 `stratum_priority_then_sha256_plan_id` — 층 우선순위, 층 안에서
  `plan_id_sha256` 오름차순이다. 같은 입력은 byte 단위로 같은 표본을 낸다. 층 정의는 spec §5다.
- 층 규칙은 policy `audit_sample.strata_rules`(v3에서 발행)다. `classification_proximity`: `{"field": <발주계획 열>,
  "values": [<문자열>, ...]}` — `field`는 `business_division_code`·`service_type_code`·`procurement_method`·
  `contract_method`·`agency_code` 중 하나이고, 그 열 값이 `values`에 있으면 이 층이다. `performance_similarity_proximity`:
  `{"rank_window": W}`(양의 정수) — `top_k < stage1_rank ≤ top_k + W`. `uniform_hash`: 규칙 없음(나머지 전부). 규칙은
  `strata`에 있는 두 층 모두에 있어야 한다(값은 D-c 사람 결정, `docs/0918_daily-operation/plan.md` §3).
- 탈락이 N을 넘는데 규칙이 없거나, 규칙·`strata`·`selection_order`·`replacement`의 형식이 틀리면 `pending_human_approval`,
  `pending_decision="audit_sample_strata_rules"`, `sample=null`(200)이다. 탈락이 N 이하이고 규칙이 없으면 전건을
  `uniform_hash`로 매긴다(전건이라 배분이 의미 없다). 층 안 순서가 같은 `plan_id_sha256`이면 `order_plan_pk` 오름차순이다.

| endpoint | 요청 | 성공 응답 | 오류 |
|---|---|---|---|
| `GET /api/order-plan-screening/executions/{execution_id}/audit-sample` | path | `200` `audit-sample-preview-response.v1`: `AuditSampleView`. 저장하지 않는다 | `not_found(404)`, `execution_not_completed(409)` |
| `POST` 같은 경로 | optional `X-BidOps-Trigger: daily_script\|manual_resume`(없음 = 사람), `audit-sample-draw-request.v1`: `schema_version`, `producer`, `consumer=audit-sample-api`, `request_id` | 첫 기록 `201`, 이미 기록됨·`pending_human_approval`·`not_applicable`은 `200`. `audit-sample-draw-response.v1`: `AuditSampleView` + `request_id`, nullable `audit_event_id`. `pending_human_approval`·`not_applicable`은 아무것도 기록하지 않는다 | `not_found(404)`, `execution_not_completed(409)`, `invalid_request(422)` 그 외 트리거 값, `immutable_conflict(409)` 다시 계산한 표본이 기록된 행과 다름, `idempotency_conflict(409)` |

- 기록은 한 transaction에 표본 행 전부와 `AuditEvent(action="c2.audit_sample_drawn", aggregate_type=
  "order_plan_screening_execution", safe_metadata={trigger, sample_count, filtered_out_count, max_per_execution,
  review_cadence, policy_version})`를 넣는다. `trigger`는 헤더 값(없으면 `null`)이다.
- 표본 건의 사람 라벨은 기존 `POST /api/order-plans/{order_plan_pk}/screening-feedback`을 쓴다. 새 라벨 축은 없다.

#### 일일 자동 실행 스위치 REST

operation 이름: `c2_daily_trigger_set`.

`effective_enabled`는 네 조건이 모두 참일 때만 참이다 — 환경 cap `BIDOPS_C2_DAILY_TRIGGER_ENABLED`(기본 false) ∧ 현재
active 버전의 최신 스위치 행 `enabled=true` ∧ `BIDOPS_C2_EXECUTION_ALLOWED` ∧ binding `execution_allowed` ∧ (policy
`active` + `quality_gate_status='passed'` + policy·binding 파일 존재). `reasons[]`는 거짓인 조건을 다음 순서로 싣는다.

| code | 조건 |
|---|---|
| `env_cap_off` | `BIDOPS_C2_DAILY_TRIGGER_ENABLED`가 거짓 |
| `no_active_policy` | active 행이 없다. 이때 아래 code는 계산하지 않는다 |
| `switch_off` | 현재 active 버전의 최신 스위치 행이 `enabled=false`이거나, 행이 없고 다른 버전에 켜진 최신 행도 없다 |
| `switch_bound_to_other_version` | 현재 active 버전에는 행이 없고, 다른 버전의 최신 행이 `enabled=true`다 |
| `quality_gate_not_passed` | active 행의 `quality_gate_status`가 `passed`가 아니다 |
| `execution_transport_not_allowed` | `BIDOPS_C2_EXECUTION_ALLOWED`가 거짓이거나 binding `execution_allowed is not True` |
| `policy_file_missing` | 컨테이너 경로에 digest 일치 policy·binding 파일이 없다 |

| endpoint | 요청 | 성공 응답 | 오류 |
|---|---|---|---|
| `GET /api/order-plan-screening/daily-trigger` | 없음 | `200` `daily-trigger-state-response.v1`: `effective_enabled`, nullable `policy_version`·`policy_sha256`(현재 active 행), nullable `switch={enabled, reason?, set_by, set_at}`(현재 active 버전의 최신 행), `reasons[]` | — |
| `POST /api/order-plan-screening/daily-trigger` | `daily-trigger-set-request.v1`: `schema_version`, `producer`, `consumer=daily-trigger-api`, `request_id`, `policy_version`, `enabled`(bool), nullable `reason`(공백 아님, ≤200자), `explicit_confirmation`(bool) | `201` `daily-trigger-set-response.v1`: `request_id`, `policy_version`, `policy_sha256`, `enabled`, `reason?`, `set_by`, `set_at`, `audit_event_id`, 그리고 기록 직후의 `effective_enabled`·`reasons[]` | `invalid_request(422)` — `policy_version`이 현재 active 버전이 아님(active가 없을 때 포함), `explicit_confirmation`이 `true`가 아님, 공백 사유; `idempotency_conflict(409)` |

- POST는 append-only 행 하나와 `AuditEvent(action="c2.daily_trigger_set", aggregate_type="order_plan_screening_policy",
  aggregate_id=policy_version, safe_metadata={enabled, policy_sha256})`를 한 transaction에 남긴다. 환경 cap이 꺼져 있어도
  스위치 행은 기록되며 결과는 `effective_enabled`·`reasons[]`로 드러난다.
- 서비스는 `X-BidOps-Trigger: daily_script|manual_resume` 실행 요청에 같은 조건을 다시 계산한다(위 트리거 절).
- 안내문구("policy를 교체하면 자동 실행이 멈춥니다. 새 버전에서 다시 켜야 합니다.")는 화면·스크립트가 표시한다. wire
  field가 아니다.

#### 발주계획 목록 누적 모드

`GET /api/order-plans`의 query는 바뀌지 않는다. 응답은 `order-plan-list-response.v5`다(누적 모드를 넣은
2026-09-18에 v4였고 2026-09-21에 v5로 올랐다 — 아래 "발주계획 목록·상세 실무 field").

- **버전을 올리는 이유**: 이 절의 wire 규칙("field 추가나 의미 변경은 새 wire schema version")과 v1→v3 선례
  (`source_url` 추가)를 따른다. item에 field가 늘고 `scope`의 모양과 뜻이 바뀐다.
- **누적 모드**(`source_run_id` 없음, 화면 기본): 범위는 **활성화된 적 있는 policy(`activated_at IS NOT NULL`)의
  `purpose='operational'` 완료(`성공|부분 성공`) 실행 전부**다. 현재 active인지는 묻지 않는다 — policy를 교체해도 과거
  판정이 남는다. 참조 실행(한 번도 active가 아닌 policy)과 측정 전용 실행은 빠진다.
  - 결과: 발주계획마다 범위 안 결과 중 **최신 1건**(실행 `finished_at` 내림차순, 같으면 `execution_id` 내림차순).
  - feedback: 발주계획마다 **최신 1건**(`created_at` 내림차순, 같으면 `revision` 내림차순). 실행과 무관하다.
  - 관측: 발주계획마다 최신 관측 1건(기존 규칙).
  - `scope = {"mode": "cumulative", "policy_versions": [...], "activated_policy_versions": [...]}` — 두 목록 모두 policy의
    `activated_at` 오름차순(같으면 버전 오름차순)이다.
    - `policy_versions`: **위 범위에 실행이 실제로 있는** policy 버전. 활성화된 적은 있지만 범위 실행이 0건인 policy는
      들어가지 않는다. 범위가 비면 `scope`는 있고 이 목록은 빈 목록이며, 이때 대시보드의 `order_plan_pending`도
      `no_completed_execution`으로 `null`이다 — 두 값은 언제나 함께 간다.
    - `activated_policy_versions`: **활성화된 적 있는(`activated_at IS NOT NULL`)** policy 버전 전부. 실행의 완료 여부를
      묻지 않으므로 대기·실행 중·실패만 있는 버전도 들어간다. 불변식 `policy_versions ⊆ activated_policy_versions`.
    - 화면은 `activated_policy_versions`로 실행 상태를 보일 범위(상태 칩·실행 목록·"최근 운영 실행" 문장)를 정하고,
      `policy_versions`로 판정 유무를 정한다. 한 번도 활성화되지 않은 policy의 `purpose='operational'` 실행(참조 실행)은
      두 목록 어디에도 없으므로 화면이 운영 결과로 말하지 않는다.
- **회차 모드**(`source_run_id` 있음, 감사용): 그 회차의 최신 완료 실행 하나로 좁힌다. policy·purpose를 묻지 않는다.
  관측은 그 회차의 관측이다. feedback은 누적 모드와 같이 발주계획별 최신 1건이다. `scope = {"mode": "run", "execution_id",
  "source_run_id", "status": "성공"|"부분 성공", "finished_at"?, "policy_version", "purpose"}`이고 그 회차에 완료 실행이
  없으면 `scope=null`이다.
- item 추가 field(두 모드 공통): nullable `execution_id`(그 행의 결과를 낸 실행 — feedback 요청의 `execution_id`로
  쓴다), nullable `policy_version`(그 실행의 policy), nullable `first_observed_at`(그 발주계획의 가장 이른
  `order_plan_observation.observed_at`). 결과가 없는 행은 앞 둘이 `null`이다. 발주계획은 첫 관측 그대로 고정되므로
  (ADR-0061) 화면은 `first_observed_at`을 판정 기준 시점으로 보인다.
- 필터(`stage1_status`·`stage2_status`·`qwen_relevance`·`human_relevance`·`tracking_status`·`issue`·`q`)는 두 모드 모두
  투영된 결과·feedback에 적용한다. 기본 보기("추적을 정하지 않은 관련 건")는 화면이 기존 필터로 조합한다.
- 2026-09-18 누적 모드 회차에서는 상세(`order-plan-detail-response.v3`)와 screening-history를 바꾸지 않았다.
  둘은 2026-09-21에 바뀐다 — 아래 절.

#### 발주계획 목록·상세 실무 field (2026-09-21)

실무 화면이 계약방법·공고 게시 여부·지난 실행의 성격을 화면에서 묻지 않아도 되게 하는 **투영만의 확장**이다.
새 migration·새 업무 규칙·새 enum은 없고 값은 `order_plan`·`order_plan_screening_execution` 행의 열 그대로다
(동작 서술은 `docs/0921_practitioner-screens/spec.md` §5).

- **목록 `order-plan-list-response.v4` → `.v5`**: item에 nullable `contract_method`(`cntrctMthdNm` 원문)와
  nullable `notice_posted`(`ntceNticeYn` 원문 `Y`/`N`)가 는다. 화면이 500행을 한 번에 받으므로 목록에는 이
  둘만 넣는다. `notice_posted`는 bool로 좁히지 않는다 — `null`은 `N`이 아니라 미제공이다.
- **상세 `order-plan-detail-response.v3` → `.v4`**: plan metadata에 nullable `supervising_agency_name`,
  `procurement_method`(`prcrmntMethd` 원문), `contract_method`, `notice_posted`, `bid_ntice_no_list`,
  `published_at`이 는다. `bid_ntice_no_list`는 **수집 원문 문자열 그대로**이고 공고번호가 여럿이어도 서버가
  쪼개지 않는다(적재기도 같은 한 문자열을 `split_tokens`로 읽는다).
- **`ScreeningHistoryItem`에 실행 성격**: `execution_purpose`(`operational|gate_measurement`, 실행 행의
  `purpose` 그대로)와 nullable `execution_started_at`·`execution_finished_at`이 는다. 서버가 대표 시각
  하나를 고르지 않고 두 값을 그대로 낸다(대기는 둘 다 `null`, 실행 중은 `finished`만 `null`).
  - **참조 실행은 새 field로 말하지 않는다.** C-2 실행에는 `quality_status` 열이 없고 참조 실행의 `purpose`도
    `operational`이다. 화면은 지금까지처럼 그 항목의 `policy_version`이 누적 `scope.activated_policy_versions`에
    없으면 참조 실행으로 읽는다. 목적만으로 가리면 참조 실행이 운영 판정으로 보인다.
  - 같은 항목 모델을 쓰는 `GET /api/order-plans/{id}/screening-history`도 함께 올린다. 이 응답은 상세와 같은
    `order-plan-detail-response` family 이름을 쓰면서 번호만 따로 올려 왔고(옛 v1), 번호는 family 안에서 한
    번만 쓰므로 **v5**로 간다.
- **증분 쿼리 0**: 세 투영 모두 이미 읽는 행(`OrderPlan`, `_history_items`가 결과마다 `session.get`으로 읽는
  실행 행)에서 값을 꺼낸다. `_history_items`의 기존 실행 조회·feedback count N+1은 이 회차에서 고치지 않는다.
- **이전 버전 소비자**: C-2 wire 규칙대로 옛 version consumer는 알 수 없는 version을 거부한다. 이 저장소의
  유일한 소비자는 관리 화면이고 런타임 `schema_version` 검사가 없으므로, 타입 리터럴과 mock을 같은 회차에
  올려 계약을 한 묶음으로 닫는다(`web/frontend/src/lib/types.ts`, `tests/api-mock.ts`).

### C-2 DB·migration 경계 (Phase 2 구현 입력)

C-2 테이블은 `0016_order_plan_screening`이 만들고 `0017_order_plan_screening_heartbeat`이 heartbeat를 더했다.
현재 Alembic head는 `0028_final_decision_basis`(`app/core/db.py:103`)이고, 일일 운영 계약의 DB 변경은 다음
revision `0029`다(아래 "`0029` — 게이트·감사 표본·일일 스위치"). 기존 공고용 `screening_execution`,
`screening_attempt`, `screening_policy`, `quality_gate`를 C-2 의미로 재사용하지 않는다.

| table | 필수 핵심 column / 상태 | 불변성·제약 |
|---|---|---|
| `order_plan_screening_policy` | `id`, `policy_version UNIQUE`, `schema_version`, `producer`, `consumer`, `policy_status=draft|activation_candidate|active|retired`, policy/binding SHA-256, safe activation metadata, `quality_gate_status`, created/activated timestamps | payload·digest immutable. status는 `draft→activation_candidate→active→retired` 단방향만 audit와 함께 허용, active partial unique 1개. **활성 여부의 정본이다**(ADR-0060) — 행은 명시적 적재 CLI(`python -m app.screening.c2_policy load`)가 파일 bytes digest로 항상 `draft`로 만들고, `quality_gate_status='passed'`는 활성화 transaction만 쓴다 |
| `order_plan_screening_execution` | `execution_id UUID PK`, `request_id UNIQUE`, `schema_version`, `producer`, `consumer`, source run/artifact/population digest·count, policy version/SHA, binding SHA, `status=대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`, `purpose=operational|gate_measurement`(`0029`), actor 표식, counts, timestamps | source/policy binding snapshot immutable. status transition trigger, terminal timestamp CHECK, active execution partial unique 1개 |
| `order_plan_screening_batch_attempt` | execution FK, `batch_id`, sequence, attempt no, `schema_version`, `producer`, `consumer`, plan count/IDs digest, model/prompt/profile/generation digests, attempt status, failure type/code, token/duration nullable, timestamps | `(execution_id,batch_id,attempt_no) UNIQUE`; max attempt 2; identity·입력·binding payload는 immutable, `running→success|failed|rejected`만 fenced status/timestamp/measurement 전이 허용, 모든 전이는 append-only audit event로 기록, model response는 encrypted object reference only |
| `order_plan_screening_result` | execution FK, `order_plan_id` FK, `schema_version`, `producer`, `consumer`, stage1 rank/score/status, stage2 status, nullable Qwen label/score/reason, batch/attempt, failure code, binding digest | `(execution_id,order_plan_id) UNIQUE`; 전체 모집단 1행/plan; stage1 `filtered_out`이면 stage2 `not_attempted`와 Qwen fields null; result update/delete 금지 |
| `order_plan_screening_artifact` | execution FK, kind/schema/producer/consumer, SHA-256, byte count, object version reference, validation status, created_at | `(execution_id,kind) UNIQUE`; object bytes와 metadata overwrite 금지; API에는 safe summary만 projection |
| `order_plan_screening_feedback` | execution/plan FK, feedback UUID, revision, actor 표식, relevance, nullable priority/memo, optional supersedes ID, created_at | `(execution_id,order_plan_id,revision) UNIQUE`; append-only trigger, update/delete 금지; grade/readiness/tracking/final decision FK 없음 |

DB row contract의 provenance와 required key/status enum은 아래와 같이 고정한다. `schema_version`,
`producer`, `consumer`는 단순 설명용 컬럼이 아니라 각 row에 저장하고, 같은 row schema의
consumer가 모르는 version은 적재하지 않는다.

| DB row schema_version | producer → consumer | required key | status / enum | 호환·불변 경계 |
|---|---|---|---|---|
| `bidops.order-plan-screening-policy.v1` | `phase0-contracts` → `policy-api` | `id`, `policy_version`, `schema_version`, `producer`, `consumer`, policy/binding digest, safe activation metadata, timestamps | `policy_status=draft|activation_candidate|active|retired` | file policy와 동일 digest만 적재; payload·digest immutable |
| `bidops.order-plan-screening-execution-row.v1` | `screening-api` → `screening-worker-and-review-api` | `execution_id`, `request_id`, provenance, source run/artifact/population digest·count, policy/binding snapshot, actor 표식, counts, timestamps | `status=대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨` | 새 row schema 없이 field/status 의미 변경 금지; snapshot immutable |
| `bidops.order-plan-screening-batch-attempt-row.v1` | `screening-worker` → `screening-merge-and-observability` | execution/batch/sequence/attempt, provenance, plan IDs digest, model/prompt/profile/generation digests, attempt status, safe failure code, nullable measurements, timestamps | `attempt_status=running|success|failed|rejected` | identity·입력·binding payload는 append-only. `running→success|failed|rejected`만 fenced status/timestamp/measurement 전이로 허용하고 모든 전이를 append-only audit event로 남긴다. max attempt 2; response body는 encrypted object reference only |
| `bidops.order-plan-screening-result-row.v1` | `order-plan-screening-merge` → `postgres-loader-and-review-api` | execution/plan identity, provenance, input/policy/binding digest, stage1/stage2 fields, nullable Qwen fields, failure code, timestamps | `status=성공|부분 성공|실패|거부됨`; relevance `relevant|not_relevant|uncertain` | file envelope `bidops.order-plan-screening-result.v1`과 구별되는 per-plan row schema; execution+plan one row; result update/delete 금지 |
| `bidops.order-plan-screening-artifact-row.v1` | `screening-artifact-writer` → `screening-api` | execution, kind, provenance, SHA-256, byte count, object version reference, validation status, created_at | `validation_status=pending|valid|invalid` | `(execution_id,kind)` immutable; object overwrite 금지; safe summary만 API에 투영 |
| `bidops.order-plan-screening-feedback.v1` | `human-review-api` → `postgres-review-history` | feedback/plan/execution identity, revision, provenance, actor 표식, relevance, nullable priority/memo, supersedes ID, created_at | `relevance=relevant|not_relevant|uncertain`, `priority=high|medium|low|null`; record is append-only | revision insert only; 기존 row update/delete 및 다른 상태축 변경 금지 |

모든 C-2 table row의 `schema_version`, `producer`, `consumer`는 해당 v1 file/wire contract와
일치해야 한다. file과 직접 대응하지 않는 row는 위 row schema를 사용한다. 모든 table은
`OrderPlan`·`OrderPlanObservation`와 source run FK/identity를 확인하고, hash가
같은 재적재만 no-op으로 허용한다. 같은 execution·plan에 다른 input/binding/result hash가
들어오면 전체 transaction을 rollback한다. CHECK는 음수 count·score 범위·상태와 nullable
조합을 거부한다. `audit_event`와 `idempotency_record`는 기존 공통 table을 재사용하되
각 mutation의 endpoint·request ID·safe code·binding digest를 남긴다.

DB role은 migration owner가 DDL을 수행하고, app은 검증된 목록·execution 생성·feedback·
audit/idempotency와 제한된 status mutation만 수행하며, worker는 frozen input을 읽고
batch/attempt/artifact/result/telemetry를 삽입한다. worker는 사람 feedback을 쓰지 않고
app은 raw model response object를 읽지 않는다. `ro_backup`은 SELECT만 갖는다. runtime
privilege allowlist와 실제 PostgreSQL 17 제약·trigger 검증은 Phase 2의 `0016`에서 수행한다.

#### `0029` — 게이트·감사 표본·일일 스위치

`down_revision = "0028_final_decision_basis"`. 신규 테이블 4개와 실행 행 열 1개다. 테이블 이름은 아래 그대로다. 기존
C-1 `quality_gate`는 `policy_version`·`pass_a/b_execution_id`·`company_profile_version`·`baseline_run_id`가 NOT NULL이라
C-2가 채울 수 없으므로 재사용하지 않는다.

| table | column | 제약·불변성 |
|---|---|---|
| `order_plan_screening_quality_gate` | `gate_id` PK(`c2gate-` + 32 hex), `policy_version`, `policy_sha256`, `binding_sha256`, `gold_manifest_sha256`, `gold_artifact_sha256`, `gold_status`, `scoring_input_sha256`, `evaluation_basis`, `scoring_unit`, `measurement_run_ids_json`, `required_pass_count`, `threshold_recall_pct`, `threshold_precision_pct`, `threshold_important_missed_max`, `threshold_review_load_max`, `created_by`, `created_at` | `evaluation_basis IN ('product_rerun','reference_artifact_rescore')`, `scoring_unit='per_published_day'`, `required_pass_count=2`, 임계값 4열은 **NULL 허용**(NULL = D-b 미결정, `review_load_max`는 하루 기준). payload·digest immutable. 임계값의 정본이다 |
| `order_plan_screening_quality_evaluation` | `evaluation_id` PK, `gate_id` FK, `revision`, `result_status`, `pass_execution_ids_json`, `measured_recall_pct`, `measured_precision_pct`, `measured_important_missed`, `measured_review_load`(4열 nullable), `metrics_json`, `reasons_json`, `artifact_sha256`, `evaluated_by`, `evaluated_at` | **append-only**(UPDATE/DELETE 금지 trigger). `UNIQUE(gate_id, revision)`, `result_status IN ('통과','미달','미측정','보류')`. CHECK: 그 gate의 임계값이 하나라도 NULL이면 `result_status='미측정'`만 허용(교차 테이블 조건이므로 trigger 또는 서비스 검사 — 구현 방식은 migration이 정한다). `artifact_sha256`은 전체에서 유일하다 |
| `order_plan_screening_audit_sample` | `id` PK, `execution_id` FK, `order_plan_id` FK, `stratum`, `selection_rank`, `plan_id_sha256`, `filtered_out_count`, `max_per_execution`, `review_cadence`, `policy_version`, `policy_sha256`, `drawn_by`, `drawn_at` | **append-only**. `stratum IN ('classification_proximity','performance_similarity_proximity','uniform_hash')`. `UNIQUE(execution_id, order_plan_id)`가 무복원의 근거다 |
| `order_plan_screening_daily_trigger` | `id` PK, `policy_version` FK(`order_plan_screening_policy.policy_version`), `policy_sha256`, `enabled`(bool), `reason`(nullable, 200자), `set_by`, `set_at`, `request_id` UNIQUE | **append-only**. 스위치의 현재 값은 그 `policy_version`의 최신 행이다. 새 버전에는 행이 없으므로 꺼진 것으로 본다 |
| `order_plan_screening_execution`(기존) | `purpose` `String(24)` NOT NULL DEFAULT `'operational'` | `CHECK (purpose IN ('operational','gate_measurement'))`. 기존 행은 전부 `operational`로 채운다. INSERT 때만 쓴다 |

첫 초안의 실행 열 `population_scope_version`·`source_population_count`·`excluded_count`·`excluded_sha256`과 결과 열
`input_title_sha256`은 만들지 않는다 — 발주계획은 하루 창으로 수집해 재관측이 없으므로 모집단 범위도 제목 변경 재판정도
없다(ADR-0061 결정 1·4).

권한(`scripts/runtime-privileges.sql`):

- 신규 4테이블은 **app 역할에만** `SELECT`·`INSERT`를 준다. worker 역할에는 주지 않는다. `UPDATE`·`DELETE`는 누구에게도
  없다.
- `order_plan_screening_policy`의 app column UPDATE 목록에 `quality_gate_status` 한 열만 더한다. 활성화 transaction에서만
  쓴다.
- `order_plan_screening_execution.purpose`는 app이 INSERT 때만 쓴다. app·worker의 UPDATE 목록에 넣지 않는다.
- `ro_backup`은 신규 테이블도 SELECT만 갖는다.

### v4 PDF 준비 snapshot (2026-09-08, 2026-09-11 갱신)

PDF 준비는 기존 `DocumentStructure`·legacy 개요를 갱신하지 않는다.
`0021_prespec_v4_pdf_contract`가 추가한 `prespec_v4_pdf_snapshot`은 유지하는 입력
스냅숏이다. `0022`가 추가했던 `prespec_v4_target`·`prespec_v4_attempt`는 migration
0026에서 삭제하고, 개요 run(`prespec_overview_run`)이 이 snapshot을 가리킨다.

- `prespec_v4_pdf_snapshot`은 current·safe `DocumentVersion`의 정확한 원문
  `ContentObjectLocation`, PDF `ContentObjectLocation`, full page-text JSON
  `ContentObjectLocation`, PDF metadata, page count·page text hash, ClamAV clean
  verdict, worker renderer/font digest와 정규화된 processor options를 묶는다.
  Canvas 이력 행과 새 native/원본 PDF의 full page text object는
  `bidops.prespec-v4-page-text.v1` JSON의 모든 물리 페이지
  `{number,text,text_sha256}`를 보존하며 PDF metadata의 페이지별 hash와 일치해야
  한다. 생성 PDF는 기존 `source` namespace에 저장하고 page-text·선택 manifest는
  `structure` namespace에 둔다. 원본 PDF는 동일 source object/location과 bytes를
  그대로 재사용한다.
- 준비 API는 source hash, renderer/font/config digest로 기존 snapshot을 변환 전에
  조회한다. 같은 source version·worker provenance·options이면 worker를 다시
  호출하지 않고 같은 PDF/page-text object version을 반환한다. cache hit도 source,
  PDF, page-text object를 저장된 namespace·object key·version·etag·size·SHA-256으로
  bounded read하고 최신 `ContentScan.status=clean`을 확인한다. Canvas renderer로
  만든 이력 행은 읽기만 하며, 새 snapshot은 native 지문(`rhwp_version`·
  `rhwp_binary_sha256`)과 실제 설치 파일 바이트를 정렬해 만든 font manifest
  (`font_manifest_sha256`)만 결속한다. 배포가 선언한 `worker_image_digest`가 있을 때만 선택적으로 함께 결속하며, 선언이 없을
  때 asset fingerprint를 이미지 digest로 가장하지 않고 `null`로 둔다. generated
  PDF에서는 이 값이 caller dict가 아니라 실제 document-worker가 PDF metadata에
  넣은 native renderer·font fingerprint와 일치해야 한다. 원본 PDF는
  `rerendered=false`와 실제 bounded Poppler/stdlib text-extractor provenance를 기록하고 `font_provenance=null`로 둔다. config의 `options`는
  `ProcessorOptions.from_mapping`의 확정 기본값을 포함한 정규화 mapping이어야 한다.
- native snapshot은 `hwpx_content_object_id`·`hwpx_location_id`·`hwpx_verify_jsonb`
  (HWP만), `structure_id`·`structure_location_id`, `para_page_map_content_object_id`·
  `para_page_map_location_id`·`para_page_map_sha256`, `rhwp_binary_sha256`·`rhwp_version`을
  추가로 결속한다. 모두 nullable로 추가하며 과거 행을 backfill하지 않는다. 변환
  HWPX는 `source`, 구조·native page-text·대응표는 `structure` namespace다. renderer
  값은 `pdf_metadata_jsonb.renderer`와 `renderer_jsonb`에 있고 별도 열은 없다.
  native renderer digest는 renderer JSON 전체의 canonical SHA-256이고 font/config
  digest와 함께 캐시 identity를 구성한다. 저장·재사용 때 모든 객체의 정확한
  version·etag·size·hash를 확인하고 HWPX 검증 결과와 page-text/map 계약을 재검증한다.
  같은 문서 버전의 기존 구조는 원본·MIME·pages·blocks가 모두 같은 경우에만 재사용하며
  다르면 `structure_binding_mismatch`로 거부한다. 기존 구조와 리뷰는 덮어쓰지 않는다.
converter의 허용된 안전 오류는 `pdf_preparation_failed:<code>`와
`AuditEvent.safe_metadata.converter_code`에 남기며 미등록 예외는 일반 코드로 닫고
원문·경로·stderr는 넣지 않는다. 개요 run이 이 snapshot을 가리킨다 — run은 자기 범위
선택(`range_source`·`page_start`·`page_end`)만 따로 갖고 snapshot 자체는 재사용한다.

### 사전규격 회사 핏 계약 (`bidops.prespec-company-fit.v1`)

`GET /api/pre-specs/{notice_id}/company-fit`은 해당 공고의 최근 attempt 최대 20개(최신 순), 자동 판정 활성 여부, 서버가 계산한 자동 준비 사유와 실제 최신 `deep_review_id`를 반환한다. 공고 없음/다른 source type은 404, 잘못된 id는 422, 내부 오류는 안전한 `processing_failed` 500이다. GET은 실행을 만들거나 모델을 호출하지 않는다.

- 실행 상태: `queued|running|completed|failed|needs_human_review`. 결과가 없거나 검증에 실패한 실행의 `result`는 null이다.
- 결과: `bidops.prespec-company-fit-result.v1`, `decision=matched|mismatch|unknown`, `summary`, `reasons[]`, `verification_items[]`. 각 사유는 `kind=scope_match|scope_mismatch|information_gap`, 모델 의견 `explanation`, `notice_refs[]`, `company_refs[]`를 갖는다. 입력에 없는 ref, 중복 ref, 확인되지 않은 회사 근거로 만든 일치/불일치, 인용 근거에 없는 숫자는 검증 실패다. 자동 보정하지 않는다.
- `notice_facts`는 해당 개요의 문장과 PDF 페이지 또는 HWPX 구조 블록 위치, 공고 제목이다. `company_facts`는 승인 프로필의 fact key/status/value만 반환한다. 회사 원문·quote·filesystem source·객체 경로는 응답하지 않는다.
- `overview_run_id`, `document_version_id`, 개요 run status, profile id/digest, policy digest, model name/revision, prompt version, 품질 표식, 생성/완료 시각과 입력/출력 토큰·소요시간을 보존한다. 사용량 부재는 null, 실제 0은 0이다.
- `is_current=false`이면 과거 입력 기준이다. 프로필·활성 심층 정책·개요·문서·핏 정책/모델 변경, 입력 hash 불일치가 현재성을 막는다. 회사 핏 결과와 실제 심층 검토 생성 여부를 서로 추정하지 않는다.
- 자동 사유는 `company_fit_disabled|pending|queued|running|stale|mismatch|unknown|failed|needs_human_review|validation_failed|reference_only`에서 접두사 `company_fit_`을 각각 붙인 코드다. 기존 자동 준비 사유도 그대로 반환한다.

`prespec_company_fit_attempt`는 입력 JSON (`bidops.prespec-company-fit-input.v1`, 정책 전문 포함)과 SHA-256, 개요/문서/프로필/심층 정책 FK를 동결한다. 입력 digest는 유일하다. 실행 상태·lease·결과·사용량만 전이할 수 있고 종결 후 UPDATE/DELETE는 DB/ORM에서 거부한다. 원응답은 기존 암호화 model-response 저장소에 저장한다. 종결 이력이 있으면 migration downgrade를 거부한다. 앱 역할은 SELECT, 합성 worker만 INSERT 및 제한된 상태 열 UPDATE를 받는다.
