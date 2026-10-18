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

- 사전규격은 `Notice.title|agency|demand_agency`, 사업 추적은 authoritative 소유 링크 대상의 `OrderPlan.title|agency_name`·`Notice.title|agency|demand_agency`, 발주계획은 `OrderPlan.title|agency_name|order_plan_unty_no`를 검색한다.
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
- `PreSpecList` query: optional `sw_only`(default `true`), `business_division`, `origin=추적|신규`, `deadline_within_days`(1..365), `q`, `sort=published|deadline|observed`, `limit` 1..500(default 50), `offset` 0 이상. 기본적으로 누적 `notice.source_type='pre_spec'`를 조회한다. `sw_only=true`는 `sw_business_status='Y'` 또는 추적 중인 발주계획 연결을 포함한다. 이 연결은 같은 opportunity의 notice 링크 status가 `확정`·`사람 확인 완료`·`후보 확인 대기` 중 하나이고 opportunity tracking status가 `계속 추적`·`보류` 중 하나이며, 그 opportunity에 authoritative `order_plan` 링크(`order_plan_id` 존재)가 있는 경우다. 따라서 `검색 미확인`, `미선택`, `종료`, authoritative order-plan 링크가 없는 연결은 예외가 아니다. 응답은 `items`, `total`, `limit`, `offset`, `overview_status_counts`이며 item은 `notice_pk`, `pre_spec_no`, `title`, `agency`, `demand_agency`(추가형, PoC), `published_at`, `deadline_at`, `budget`, 원문 그대로의 `sw_business_status`·`business_division`, `origin`, `opportunity_id`, `tracking_status`, `kept_by_tracking`, `document`, `overview_review_status`를 가진다. `demand_agency`는 사전규격 원문 `rlDminsttNm`(수요기관)이며 값이 없으면 `null`이다. **수요기관은 사전규격에서만 값이 있다** — 입찰공고는 `agency`가 이미 수요기관 우선값이라 입찰공고 상세는 `demand_agency`를 투영하지 않는다. `opportunity_id`·`tracking_status`·`origin`은 pending/rejected/search-unconfirmed link가 아니라 해당 notice의 authoritative active owner만 투영한다. `document`는 `attachments`, `완료`, `대기`, `진행`, `차단`, `실패` 건수이며 큐 행이 없는 첨부는 총계에만 포함한다. `kept_by_tracking`는 `sw_business_status`가 `Y`가 아닌 행이 위 예외로 남을 때만 `true`다. `origin`은 연결된 opportunity의 `first_registered_stage`에서 `order_plan→추적`, `pre_spec|bid_notice→신규`로 투영하고 연결이 없으면 `null`이다. `overview_review_status`(추가, 구 `docs/design/PLAN.md` 3단계, git 이력에서 확인)는 해당 notice의 최신
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
  2026-09-22 개정([ADR-0064](tracking/decisions/0064-prespec-actionable-deadline-scope.md) 결정 4
  개정, 후속 시안 M7 ③ 승인): 그 합집합에 **추적 상태가 null 또는 `미선택`**이라는 조건을 바깥
  AND로 건다. 사람이 `계속 추적`·`보류`·`종료` 중 무엇을 골랐든 그 공고는 이유 불문 `actionable`에서
  빠지고 `tracking`(계속 추적·보류)·`all`에서 보인다. 추적 상태를 `미선택`으로 되돌리면 다시
  들어온다. 이 조건은 `workspace_counts["actionable"]`과 `deadline_scope_counts`에도 같이 걸린다.
  `recent`·`tracking`·`all`과 `next_action` 필드는 바뀌지 않는다.
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
  2026-09-22 확장([ADR-0067](tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md)):
  optional `deadline_within_days`(정수 1..365)는 의견등록 마감이
  `[요청 시각, 요청 시각 KST 일자 + N일의 끝)`에 드는 건만 남기는 **창** 필터다.
  상한은 `+(N+1)`일 00:00 KST의 열린 경계이고(D-day 표시가 날짜 단위이므로 창도 날짜로
  끊는다) 하한이 요청 시각이라 이미 지난 마감은 임박이 아니다. `deadline_at`이 `null`인
  `마감 미확인`은 창에 **들지 않는다** — 미확인을 임박으로 승격시키지 않는다(이 점이
  `deadline_scope=current`와 다르다). `deadline_status`와 같은 자리의 서버 필터이므로
  `items`·`total`과 모든 집계(`workspace_counts`·`overview_status_counts`·
  `deadline_scope_counts`)가 같은 모집단을 읽는다. 인자를 주지 않으면 창이 없다.
  범위를 벗어난 값은 422 `deadline_within_days is invalid`다.
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
- `OpportunityDetailResponse`는 위 사업기회 field와 `links[]` 전체를 반환한다. link는 `id`, `stage=order_plan|notice`, `link_type=official|candidate`, `status=확정|후보 확인 대기|사람 확인 완료|검색 미확인|사람 확인 병합`, `search_strategy?=full|breaking_split|normalized|longest_fragment|prefix12|merge_confirmation`, `attempted_strategies[]`, `agency_match?`, `last_searched_at?`, `evidence_external_no?`, `evidence_bid_no?`, `search_target_kind?=pre_spec|bid_notice`, `human_decision?`, `reviewer_name?`, `reviewed_at?`, `review_reason?`, `record_type?`, `record_id?`, `notice_id?`, `order_plan_id?`, `source_type?`, `title?`, `agency?`, `external_id?`, `record_external_id?`, `budget?`, `deadline_at?`, `planned_order_year?`, `planned_order_month?`(추가형, PoC)다. 뒤 넷은 link 단위 값이다 — link이 공고(`notice`)를 가리키면 `budget`·`deadline_at`을, 발주계획(`order_plan`)을 가리키면 `budget`(=`budget_amount`)·`planned_order_year`·`planned_order_month`를 싣고 대상이 없거나 해당하지 않는 필드는 `null`이다. 서버는 사업기회 단위의 "대표 마감"을 고르지 않는다. `검색 미확인` link도 포함하며 이 상태를 `사전규격 없음`으로 변환하지 않는다. `사람 확인 병합`은 병합으로 끝난 후보 수락 link(비소유, `human_decision=accepted`)이고, `search_strategy=merge_confirmation`은 사람 상태가 있는 사업기회끼리 자동 병합을 거부해 만든 `후보 확인 대기` link다(spec §3.2·§3.3). `search_target_kind`는 `검색 미확인` link가 어느 종류를 찾다 실패했는지 구분한다. target이 있으면 `title`·`record_external_id`가 해당 공고 또는 발주계획을 가리키고, `id`와 `evidence_external_no`로 link 자체와 근거 번호를 식별한다. raw record, filesystem path, object-store metadata는 반환하지 않는다.
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

후보 수락(`PATCH …/links/{id}/decision` `accepted`)이 대상을 이미 소유한 다른 active 사업기회로 이끌면 §3.2와 같은 규칙으로 병합한다. 사람 상태 보유(`tracking_status ≠ 미선택` 또는 `recheck_signal_at IS NOT NULL`) 사업기회가 둘 중 1개 이하면 병합하고 후보 link를 `사람 확인 병합`(비소유, `human_decision=accepted`)으로 남긴다 — 소유권은 옮겨진 공식 link가 갖는다. **둘 다 사람 상태를 갖더라도 두 `tracking_status`가 같고 양쪽 모두 `recheck_signal_at IS NULL`이면 병합한다(2026-09-22, [ADR-0068](tracking/decisions/0068-same-state-merge-and-tracking-reset.md)).** 유지 쪽은 둘 중 오래된 사업기회(`created_at`, 동률이면 `id`)이고 그 추적 상태·사유·선택자·시각은 바뀌지 않으며, 병합된 쪽의 결정은 그 행에 남는 것과 별도로 감사 이벤트 `opportunity.merged.human_confirmed`의 `safe_metadata.merged_human_states[] = [{id, tracking_status, tracking_reason, tracking_selected_by, tracking_selected_at}]`에도 적힌다(같은 상태 병합일 때만 있는 키). 상태가 다르거나 한쪽에 신호가 있으면 409 `candidate_merge_state_conflict`이고 details는 `{opportunities: [{id, tracking_status, tracking_selected_by, tracking_selected_at, recheck_signal, recheck_signal_at}]}`다(`recheck_signal_at`은 2026-09-22 추가, 추가형). 화면은 이 응답을 받아 각 사업을 `미선택`으로 되돌리는 단추를 주며(같은 `PATCH …/tracking-status`, 사유·담당자 필수) 되돌린 뒤 수락을 자동 재시도하지 않는다. 자동 병합(공식 키 재적재)이 같은 조건으로 막히면 경고 `opportunity_merge_confirmation_required`와 함께 `병합 확인` 후보(`search_strategy=merge_confirmation`)를 만들며, 도착 레코드는 고아로 남지 않고 자기 사업기회(없으면 새로 생성)에 붙는다.

#### 레코드 활동 피드·노트 (RL-02, 2026-10-17)

사업기회 레코드 화면(`/opportunities/:id/activity`)의 입력이다. 기능 명세는 `docs/work/groups/RL/features/RL-02-opportunity-timeline/spec.md`, 업무 규칙은 [business-rules.md "사업기회 레코드 단계 바·활동 피드"](business-rules.md#사업기회-레코드-단계-바활동-피드-rl-02-2026-10-17)다. 오류 code `note_not_action`(409)은 라우터 로컬 map(`routers/opportunities.py`)과 프런트 `src/lib/apiErrors.ts`에만 등록했고, 노트를 못 찾는 경우는 새 code 없이 기존 core `not_found`(404)를 쓴다(core `api_errors`·lifecycle `API_ERROR_CODES` 불변).

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

마감 임박 창(`deadline_within_days`, 2026-09-22 추가, [ADR-0067](tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md))은 `hold_review`와 같은 모양의 **복합** 인자다. 정수 1..365를 받고 `권위 있는 연결`(`official`·`확정` 또는 `candidate`·`사람 확인 완료`·`accepted`)의 공고 마감이 `[요청 시각, 요청 시각 KST 일자 + N일의 끝)`에 드는 **추적 대상**(`계속 추적`·`보류`) 사업기회만 남긴다. `hold_review=overdue`가 "보류 상태 + 기한 지남"을 한 인자로 묶은 것과 같은 선례이며 `tracking_status`를 다중 값으로 넓히지 않는다. 창은 **링크 단위**로 판정하고 돌려주는 것은 **사업기회**다 — 응답에 "이 사업의 마감"이라는 대표 필드를 만들지 않으므로 소비자가 `links[]`의 `deadline_at`·`source_type`으로 어느 마감이 임박했는지 고른다. 확인 대기 후보 연결의 마감과 `deadline_at`이 `null`인 연결은 사업기회를 창에 넣지 않으며, 이미 지난 마감도 임박이 아니다. 범위를 벗어난 값은 422다. `sort=deadline`(같은 날 추가)은 **정렬 키일 뿐** 창이 아니다 — 아직 남은 권위 연결 마감 중 가장 이른 것 오름차순이고, 그런 마감이 없는 사업기회는 방언과 무관하게 맨 뒤에 둔 다음 `created_at` 내림·`id` 내림으로 동률을 푼다.

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

[ADR-0053](tracking/decisions/0053-decision-workload-read-contracts.md)의 읽기 전용 계약이며 2026-09-22에 실무자 대시보드 패널 계약([ADR-0067](tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md))이 키 다섯(세는 키 넷과 그중 둘의 합계 하나)을 더했고, 2026-10-16 RL-00이 키 `company_attention` 하나를 끝에 더했고, 2026-10-17 RL-01이 키 `briefing_pending` 하나를 그 뒤에 더했다. 모든 경로가 DB 열을 새로 만들지 않고 기존 목록과 **같은 모집단**을 센다.

- `WorkloadResponse`: `generated_at`(UTC aware)과 `items[]`. item은 `key`, nullable `count`(0 이상), nullable `unavailable_reason` 셋뿐이다. `items`의 순서는 고정이며 `order_plan_pending`, `pre_spec_deep_review_ready`, `tracking_action_required`, `tracking_hold_review_due`, `bid_final_decision_pending`, `tracking_deadline_imminent`, `human_check_required`, `overview_human_review`, `blocking_items_open`, `order_plan_new_priority`, `company_attention`, `briefing_pending` **열**이 언제나 모두 있다(ADR-0053 §1·§4 갱신, ADR-0067 결정 1, spec §7.1·§8). 앞 다섯의 뜻과 소유자는 바뀌지 않았다.
- **제공자 부재와 실제 0은 다르다.** 소유 모듈이 등록되지 않았으면 `count=null`·`unavailable_reason="provider_absent"`이고, screening이 있어도 누적 범위(아래 "발주계획 목록 누적 모드")에 완료된 C-2 운영 실행이 하나도 없으면 `count=null`·`unavailable_reason="no_completed_execution"`이다. 오늘 실행이 없다는 이유로 `null`이 되지 않는다. 셀 수 있었다면 정수와 `unavailable_reason=null`이다. `null`을 0으로, 0을 `null`로 접지 않는다.
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

## 사전규격 개요 검토와 예비 적합성 판단 (MVP, 2026-09-21)

v3 권고형 개요, legacy v4 단일 호출 개요, v5 주장 검증 스택(activation v2·call
ledger·verification)은 폐기했다([ADR-0054](tracking/decisions/0054-prespec-overview-mvp-rewrite.md)).
`prespec_overview_run` 단일 테이블과 `bidops.prespec-overview.v1|v2` 계약으로 처리한다. v1은
기존 개요 run, v2는 사실 개요와 예비 판단을 분리해 담는 새 run이다([ADR-0066](tracking/decisions/0065-prespec-overview-preliminary-assessment.md)). 첨부
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
  loader는 v7, 불변 `prespec-overview-policy-v8.json`, 로컬 LiteLLM 참조용
  `prespec-overview-policy-v7-litellm-v1.json`의 exact identity만 읽는다. LiteLLM 정책은 v7에서
  `model_name=local-agent-main`, `model_endpoint_ref=litellm-openai-compatible`,
  `prompt_version=prespec-overview-v7-litellm-v1`만 다르고 schema·generation·검증·한도는 같다.
  기본 경로나 전역 모델 설정을 바꾸지 않으며 로컬 참조 실행에서 경로로 명시 선택한다. v8은 같은 세 절과
  예비 판단을 통합 생성하지만 기본 경로가 아니며 품질 비교·migration·배포·정책 변경 승인 전에는
  운영 활성 정책으로 보지 않는다. v6 파일은 기존 run 기록으로만 남는다.

### v8 생성·판정 계약

- 통합 초안 `bidops.prespec-overview-assessment-draft.v1`은 기존 사실 claim 객체와
  `bidops.prespec-preliminary-assessment.v1`을 자식으로 갖는다. 안전한 최상위 JSON을 확인한 뒤
  두 자식을 독립 파싱한다. 판단 자식만 틀리면 개요를 보존하고 `held`로 기록한다.
- 판단은 세 축 `ai_data|blockchain_did|public_si_integration`, 관계
  `direct|partial|indirect|unrelated|unknown`, 실제 수행 역할, 핵심 과업 claim ID, 선택한 회사
  fact ID, 확인 항목을 담는다. 모델은 한국어 등급 라벨을 출력하지 않는다.
- 서버 등급은 가장 강한 유효 관계로 계산한다. 핵심 과업·원문 claim·회사 fact 참조가 유효하지
  않거나 profile이 손상됐거나 역할/관계가 미확인이면 `assessment_status=held`,
  `assessment_grade=null`이다. 세 축이 모두 무관한 `제외`는 선택 의미검증 통과가 필수다.
- 선택 의미검증은 `bidops.prespec-overview-assessment-semantic.v1`이며 claim과 세 axis를 함께
  검사한다. 제외 후보, `quantity_relation_ambiguous`, `delivery_role=unclear`, 모델 uncertainty,
  검증 인용과 생성 문장의 부정·조건 표식 차이가 trigger다. 상태는 `not_run|passed|failed`, 범위는
  `overview_full`, `assessment_axes`, `claim:<id>`, `axis:<id>`로 저장한다. 미실행을 통과로 바꾸지 않는다.
- 호출 상한은 정상 1, 선택 의미검증 포함 2, 형식 재시도 포함 3회다. 사실 오류 재생성, 의미검증
  재시도, 다른 provider fallback은 없다. 선택 의미검증의 기술 실패는 유효한 개요를 유지하고
  등급만 보류한다.
- 선택 프로필은 `BIDOPS_ACTIVE_PROFILE_VERSION_ID`만 독립 해석한다. 미설정은
  `not_configured`, 누락·hash/lineage 손상은 `invalid`이며 손상된 fact는 모델에 보내지 않는다.
  `ready`에서도 `confirmed` fact의 최소 `ref|value|quote`만 동결한다.

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

### REST (`bidops.prespec-overview.v1|v2`)

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

v2 Run은 여기에 `contract_version=overview-assessment-v1`, `assessment{result,checks,grade,
status,semantic_status,semantic_scope}`와 `input_binding{policy_digest,prompt_version,
validator_version,profile_version_id,profile_digest,profile_status,generation_config_digest,
input_binding_sha256,reused_from_run_id}`를 더한다. profile fact 본문과 원응답 참조는 공개하지 않는다. v1·v2 이력이
섞이면 각 run의 저장 버전으로 읽고, envelope `schema`는 v2 run이 하나라도 있으면
`bidops.prespec-overview.v2`다.

`GET /api/pre-specs`는 기존 `grade`·`grade_source`를 유지하면서 `display_assessment`를 추가한다.
`display_assessment`는 `{grade?,status=graded|held|none,source=human_review|preliminary_assessment|
screening_judgment|none,basis_run_id?,assessed_at?,quality_status?,reason_codes[],axes[],
verification_items[],semantic_status?,semantic_scope[],latest_run_status?}`다. 대표값은 사람 정정 →
현재·safe 문서의 최신 v2 graded/held → 기존 선별 등급 → 없음 순이다. 최신 기술 실패·취소·대기는
이전 유효 대표값을 지우지 않고 `latest_run_status`에만 나타난다.

목록 query `display_grade`는 `우선 검토|검토 권장|관찰 대상|제외|판단 보류|판정 없음`이고 기존
`grade` 필터와 독립이다. 서버가 페이지 분할 전에 적용해 `items`, `total`, 건수가 같은 집합을
읽는다. 구버전 화면 URL의 `grade`는 프런트가 `display_grade`로 한 번 정규화한다.

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

### DB: `prespec_overview_run` (migration 0026, 0031 확장)

`id, notice_id, document_version_id, snapshot_id?, work_job_id, status, range_source,
page_start?, page_end?, range_reason_codes, input_sha256?, policy_digest, model_name,
model_revision?, draft_json?, checks_json?, result_json?, warnings_json, reason_codes,
call_count, raw_response_refs, actor_name?, created_at, started_at, completed_at`.
0031은 `contract_version, prompt_version?, validator_version?, profile_version_id?, reused_from_run_id?, profile_digest?,
profile_status, profile_facts_json, generation_config_json?, generation_config_digest?,
input_binding_sha256?, assessment_json?, assessment_checks_json?, assessment_grade?, assessment_status,
semantic_status, semantic_scope_json`을 추가한다. 기존 행은 `contract_version=overview-v1`,
`profile_status=not_configured`, `assessment_status=none`, `semantic_status=not_run`, 빈 scope/facts로
보존한다. `profile_version_id`는 `profile_version(id)`를 `RESTRICT`로 참조하고 hash는 lowercase
hex64, status·grade 조합은 CHECK로 강제한다. downgrade는 결과 이력 보존을 위해 백업 복구만 허용한다.
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
- `DocumentSegmentsView`(`bidops.document-segments.v1`): `schema`, `structure_id`, `document_version_id`, `source_sha256`, `taxonomy_version`, `extractor_binding`, `extractor_binding_sha256`, `payload_sha256`, `segments[]`, `inventory_summary`, `coverage`, `warnings[]`, `created_at`다. 현재 `taxonomy_version`은 `bidops.segment-taxonomy.v2`이며 `extractor_binding`은 `name`(`bidops-document-segments`), `version`, `taxonomy_version`, `rules_sha256`, `schema`를 갖는다. 각 segment는 `segment_id`, `ordinal>=1`, `taxonomy_labels[]`(`business_eligibility_evaluation|technical_functional|quality_security_constraints|partnership_governance|operations_maintenance`), `start_locator`, `end_locator`, `requirement_ids[]`, `source_block_keys[]`, `classification_source`(항상 `deterministic`), `confidence`(항상 `null`), `status=classified|needs_human_review`, `page_range`, `mapping_status`를 갖는다. locator는 `kind=paragraph|table_cell|block`, `block_key`, `page>=1`, `ordinal>=0`, nullable `table_key`·`row`·`column`이다. `inventory_summary`는 `expected_ids[]`, `duplicate_ids[]`, `ambiguous_items[]`, `prefixes[]`, `item_count`, 필수 정수 `card_item_count`·`label_value_table_count`, `coverage`를 갖는다. `coverage`는 `block_count`, `covered_block_count`, `segment_count`, `gap_count`, `overlap_count`, `gaps[]`, `overlaps[]`, `needs_human_review_count`, `toc`를 갖는다. **응답에는 원문 text와 segment 제목이 없다** — 화면은 ordinal·label·요구사항 ID·block key·page 링크만 보이고 제목이 없는 이유를 직접 밝힌다.
- `page_range`는 `{first,last}`(둘 다 1 이상, 물리 PDF 순번) 또는 `null`이고 `mapping_status`는 `mapped|partial|inherited|unavailable`이다. 둘은 **문단↔쪽 대응표(`bidops.para-page-map.v1`)에서 조회 시점에 계산하는 wire 전용 값**이며 manifest·segment 행에 저장하지 않고 `payload_sha256`의 hash 대상에도 넣지 않는다. segment의 `source_block_keys` 중 직접 매핑된 키가 있으면 우선한다. 전부 매핑되면 `mapped`, 일부만이면 `partial`이고 범위는 매핑된 키의 `min(page_first)`~`max(page_last)`다. 직접 매핑이 없으면 build 시점에 저장한 가까운 비어 있지 않은 앞 문단 최대 3개 중 첫 매핑 문단의 `page_first`를 한 쪽짜리 `inherited` 범위로 쓴다. 대응표나 매핑된 anchor가 없으면 `unavailable`·`page_range=null`로 남겨 쪽을 추정하지 않는다. 대응표를 가진 snapshot의 객체를 읽지 못하거나 저장 SHA-256·schema 검증에 실패하면 500 `processing_failed`로 닫는다.
- `requirement_inventory_item`은 기존 열 제목 경로와 새 라벨·값 경로를 함께 보존한다. 기존 행은 `source=column_header_table`, `card=null`이고, 카드 행은 `source=label_value_table`과 원래 category·title·definition·details·선택 필드·table identity·경고·build 시점 `page_anchor_block_keys`를 가진다. 추가 열은 `source TEXT NOT NULL DEFAULT 'column_header_table'`, nullable `card JSONB`, `document_segment.page_anchor_block_keys JSONB NULL`이다. DB 전용 카드 값은 `DocumentSegmentsView`에 원문을 추가하지 않는다.
- analysis-worker CLI `python -m app.deep_review.cli rebuild-segment-manifests (--structure-id <uuid> | --all) [--dry-run]`은 구조마다 `{structure_id, created, manifest_id, errors[]}` JSON 한 줄을 출력한다. DB와 객체 저장소에 접근할 수 있는 analysis-worker 역할에서 실행하고 `--all`은 `ready` 구조만 처리하며 기존 manifest 행은 보존한다. 종료 코드는 성공 0, 입력 오류 2, 처리 오류 1이다.
- 로컬 증거 명령 `PYTHONPATH=web/backend python3 scripts/hp-card-inventory-check.py`는 반복 `--structure <json> --page-map <json>` 입력 또는 짝이 맞는 `<name>.structure.json`·`<name>.para_page_map.json` 파일을 둔 `--dir <directory>`를 받는다. 제품의 manifest builder와 page resolver를 호출하고 DB·네트워크·객체 저장소 접근 없이 문서별 `{name, card_count, inherited_page_count, mapped_page_count, unavailable_count, prefixes, categories, duplicate_ids, warnings}` JSON 배열을 stdout에 출력한다. `--out <path>`는 새 파일을 만들고 기존 경로를 덮어쓰지 않는다. 입력·처리 오류에 원문 text를 포함하지 않는다.
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

모델 response 원문은 암호화된 객체로 저장하고 DB에는 namespace, version, hash, key reference만 둔다. RL-04 제안서 초안 PDF는 namespace `proposal-pdf`(버킷 `bidops-proposal-pdf`, 자격증명 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`)에 암호화 없이 저장하고 `content_object.sha256`이 저장 바이트 hash이며 `retention_class=proposal-pdf-365d`(365일 만료)다. 백업·복구·active hash 검증 대상이다(결정 B48). evidence locator는 document version, structure ID, page·block 또는 표 좌표를 포함하며 report의 사실·숫자와 연결된다.

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
| `GET /api/order-plans` | `source_run_id?`, `stage1_status?`, `stage2_status?`, `qwen_relevance?`, `human_relevance?`(값 `missing`은 "사람 피드백 행 자체가 없음"), `tracking_status?`, `first_observed_from?`(KST 날짜, 포함 하한), `issue?`, `q?`, `limit=1..500`, `offset>=0` | `items`, `total`, `limit`, `offset`; item은 `order_plan_pk`, `order_plan_unty_no`, nullable 공개 `source_url`, title, agency, nullable `budget_amount`·`planned_order_year`·`planned_order_month`, source run/observation, BM25 stage status/rank/score/`nearest_capability`, Qwen stage status/score/label/reason, latest human feedback summary, 결과를 낸 `execution_id`·`policy_version`, `first_observed_at`, nullable `contract_method`·`notice_posted`(수집 원문 `Y`/`N`); `source_run_id`가 없으면 누적 모드(`order-plan-list-response.v5`, "발주계획 목록 누적 모드") | `invalid_request(422)` |
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

### 심층검토 설명형 보고서 v2 (2026-09-22, 선택형 PoC)

`analysis-policy-narrative-v2.json`으로 시작한 실행은 `bidops.deep-review-stage.v2`와
`bidops.deep-review-report.v2`를 사용한다. 기존 v1 정책·stage·report의 의미와 저장된
payload/hash는 변경하지 않는다. `ReportView.report`, `ReportRevisionRequest.report`,
의견 에이전트의 full revision은 `schema`로 구별하는 v1/v2 union이다. 응답 envelope는 유지한다.

- v2 claim은 기존 사실/계산/해석/의견/미확인 계약에 `report_section`, `narrative_role`,
  `topic_key`, `source_unit_ids`, `requirement_ids`, `related_claim_ids`, `is_key_point`를 추가한다.
  `requirement_ids`는 실제 문서 ID이며 `source_unit_ids`의 내부 분할 ID와 구별한다.
- stage는 `coverage[{source_unit_id,status:reviewed|needs_review,claim_ids,reason}]`와
  `considered_claim_ids`를 갖는다. 입력 조각의 원문·회사 근거·선행 주장 밖 참조를 거부한다.
  회사 대조 단계도 입력에 제공된 선행 주장 목록을 선택적으로 반환할 수 있다.
  전체 종합 단계에서는 모든 선행 주장 포함을 계속 요구한다. 회사 근거 ID를 주장 ID로
  대신 사용하는 것은 원문 대조 on/off와 무관하게 거부한다.
  읽을 수 없는 원문·길이 초과·전체 종합 불가를 결과 누락으로 감추지 않는다.
  v2 사실 문장의 숫자는 인용 근거의 숫자와 대조하고 계산은 식을 재연산한다.
  숫자 존재 대조만으로 단위·관계·문장 의미까지 검증되었다고 하지 않는다.
- v2 인용은 고정 원문 위치 안에서 공백·줄바꿈·따옴표 모양·전각 ASCII 차이를
  허용하고, 유일하게 대응하는 **원문의 실제 문자열**을 저장한다. 숫자/영문 토큰 사이의
  공백은 보존한다. page 위치는 같은 페이지의 원문 순서상 연속된 문단까지 허용하고, paragraph/cell 위치는 해당 블록에 한정한다. 중간 문단 생략·순서 변경·다른 페이지 결합은 거부한다. 의미·수치·단위·부정어 변경이나
  다른 문서/위치의 인용은 허용하지 않는다. 암호화된 모델 응답 원본은 그대로 보존한다.
- 원화 금액은 Decimal로 단위를 환산해 같은 값인지 검사한다(84백만원=84,000,000원).
  축약 연도와 대응하는 풀어 쓴 연도는 `year_notation` warning으로 보고서를 허용하되
  세기를 확정하지 않는다. 해당 claim/evidence 연결과 분석 한계를 저장하고 본문 문장
  옆에 확인 사항을 표시한다. 다른 연도·금액은 계속 실패한다.
- 한 원문 조각의 선행 분석이 회사 대조 입력 예산을 넘으면 여러 호출로 분할한다.
  전체 선행 claim ID를 누락 없이 전달하고 같은 원문 조각의 coverage를 합칠 때
  `needs_review`를 우선 보존한다. 전체 종합 입력 상한은 그대로 유지한다.
- 모델이 생성한 로컬 UUID는 호출별 attempt/stage/slice/phase namespace에 결속하고
  내부 참조를 함께 치환한다. 원문·회사 근거 ID와 선행 참조는 유지하며 중복 선언·범위
  밖 참조는 거부한다. 업무 내용이나 검증 실패를 자동 수정하는 경로가 아니다.
- report는 `assessment|scope|company_fit|delivery|evaluation|contract_economics|actions|decision_conditions`
  8개 절이다. 절의 `status=available|not_analyzed`, 문단 하나에 claim 하나를 보존한다.
  모든 claim은 정확히 한 번 본문에 나타나며 body/역할/핵심 표시는 원 claim과 일치해야 한다.
  분류할 결과가 없으면 다른 절의 claim으로 채우지 않는다.
- report의 `generator_version=narrative-v2`, `coverage`, `analysis_limitations`,
  `validation_summary`와 claim의 역할·연결 metadata는 서버 소유다. 후속 revision에서
  schema를 바꾸거나 이를 편집할 수 없다. 본문 수정은 claim과 연결 문단을 함께 바꾸고
  기존처럼 사유·범위 내 근거·base revision 검증을 거쳐 새 snapshot으로 저장한다.
- v2의 검증 요약 건수는 저장할 실제 check의 상태별 건수다. `unknowns`는 업무 미확인
  내용이며 경고 건수로 합산하지 않는다. 구조·근거 검증 통과는 의미 정확성·품질 측정 통과와 다르다.
- `GET /deep-reviews/{id}/report`는 현재 실행이 재시도 중/실패여도 가장 최근 저장된
  revision과 그 revision의 의견을 반환한다. 저장된 보고서가 없으면 409
  `review_not_ready`다. 실행 상태는 기존 `GET /deep-reviews/{id}`로 별도 조회한다.
  GET은 생성·보정하지 않으며 수정/의견 저장에는 기존 완료 실행 gate가 유지된다.

상세 설계·검증 범위는 [0922 명세](0922_deep-review-improvement/spec.md)와
[구현 기록](0922_deep-review-improvement/plan.md)을 따른다.

#### 실행별 원문 대조 선택

- `POST /notices/{id}/deep-reviews`와 `POST /deep-reviews/{id}/attempts`는
  `source_verification_enabled` boolean을 받는다. 기본값 true, 문자열/숫자 coercion은
  거부한다. 시작/재실행 Agent payload도 같은 선택을 받는다. 생략/true의 기존
  idempotency hash는 유지하고 false는 별도 hash이므로 같은 request ID로 바꿀 수 없다.
- 새 attempt의 선택은 `deep_review.source_verification_selected` 감사 행에
  `aggregate_type=deep_review_attempt`, `aggregate_id=attempt ID`,
  `safe_metadata={enabled,scope:source_quotes_and_numbers}`로 한 번 기록한다.
  기존 행이 없는 과거 attempt는 항상 대조를 사용했으므로 true다. worker는 실행 시작에
  해당 선택을 고정해 stage·합병·report 검증에 공통 적용한다. DB migration은 없다.
- false는 원문 인용 문자열 일치와 사실 숫자/계산 입력값의 근거 대조만 생략한다.
  원문 hash·문서/회사자료·페이지/블록 범위·읽기 권한·안전 검사·JSON 형식·참조 연결·
  계산식 재연산·전체 입력 누락 검사는 유지한다. 원본 응답과 인용 내용을 자동 보정하지 않는다.
- `AttemptView.source_verification_enabled`와 `EvidenceView.source_verification_enabled`가
  선택을 표시한다. evidence는 이를 사용한 원래 attempt에서 읽으며 최신 attempt의 설정을
  소급 적용하지 않는다. 끈 실행의 문서 근거 조회는 모델 인용과 실제 원문 페이지를 함께
  반환한다. 회사 근거의 `quote`는 기존처럼 승인 프로필의 실제 원문을 반환한다.
- report의 저장된 checks에 `source_verification_skipped` warning을 남긴다. v2는 분석
  한계에도 표시한다. `validation.status=passed`는 유지된 계약 검사의 통과일 수 있으며
  이 warning이 있으면 UI는 **원문 대조 미실시**로 표시한다. ‘근거 검증 통과’로 표시하거나
  품질 측정·사람 승인을 대신하지 않는다. 과거 revision/checks는 변경하지 않는다.

### 사용자 요청 기반 Luna 심층검토 (ADR-0069)

`POST /api/notices/{notice_id}/deep-review-previews`는
`{bundle_id, source_verification_enabled=true, review_id=null}`를 받아
`DeepReviewPreviewView`를 반환한다. 재실행은 `review_id`의 고정 정책·프로필을 쓴다.
입력은 `preview_id`, `input_sha256`, `provider=codex-exec`, 고정 정책 row의 `model_name`과
`generation.reasoning_effort`, `quality_status=unmeasured_reference`, 대조 설정과 `input`이다.
`input`은 문서·회사 근거를 포함하므로 일반 로그·감사 metadata에 넣지 않는다.
HP-00의 새 identity는 `gpt-6-luna`/`high`, codex CLI `0.162.1`이다. preview·승인 표식의 모델과
effort는 고정 정책 row에서 읽고 실행 metadata의 CLI version은 identity 모듈에서 읽는다. 정책의
모델·effort가 runner identity와 다르면 preview·생성·worker claim은 외부 호출 전에 거부하며
REST는 503 `model_binding_invalid`, worker는 호출 없이 실패로 종결한다. 모델 artifact revision은 없다.
기존 정책 v1~v4·demo-v1과 실행 row는 변경하지 않고, `gpt-5.6-luna`/`xhigh`는 legacy 조회에만 허용한다.
NULL 계보용 `analysis-policy-luna-v5`는 v4에서 `policy_identity`, `model_name`,
`generation.reasoning_effort`, `execution.cli_version` 네 값만 바꾼 불변 정책이다. 가정 분석의
새 불변 input snapshot은 승인 당시 정책을 재확인하도록 `policy_binding={policy_version_id,
policy_sha256,model,reasoning_effort}`를 포함하며 기존 snapshot은 수정하지 않는다.

생성 및 재실행 API·Agent payload에 optional `preview_id`가 추가됐다. Luna 정책에서는
필수이며 없으면 409 `preview_required`, 입력·설정 불일치는 `preview_changed`,
이미 사용한 미리보기는 `preview_used`다. 같은 request ID·actor·payload는 기존 응답을
재생한다. 별도 요청으로 같은 입력 검토를 만들면 `review_exists`, 동일 공고의 실행 중
검토는 `active_attempt_exists`다. 기존 검토는 attempts API로 새 attempt를 만든다.
개요 미완료는 `review_not_ready`, 기능/참조 모드 비활성은 `service_unavailable`이다.

`AttemptView`에 nullable `provider`, `model`, `reasoning_effort`, `preview_id`가 추가됐다.
과거 승인 기록이 없으면 null이며 과거 모델 출처를 추정하지 않는다. 사전규격 목록은
페이지 단위 조회한 `latest_deep_review_status=queued|running|completed|failed|null`을
반환한다. 준비 상태와 실행 상태는 별도다.

migration `0032_luna_deep_review`는 `deep_review_preview`와 `deep_review_approval`을
추가한다. 둘 다 UPDATE/DELETE를 DB trigger와 ORM이 거부한다. 승인 preview와 attempt는
각각 unique이며 FK는 RESTRICT다. app은 SELECT/INSERT, worker는 SELECT만 갖는다.
승인이 존재하면 downgrade를 거부한다. 정책과 모델 revision의 확인되지 않은 값은
추정하지 않는다. 실행 metadata의 CLI version은 HP-00 identity 기준 `0.162.1`이고
모델 artifact revision은 없다.

내부 runner API는 `/calls` POST → `/calls/{id}` GET heartbeat/result → DELETE 취소다.
외부 공개 API가 아니며 worker 전용 내부망에서만 사용한다. prompt는 stdin으로 전달하고
응답은 worker 암호화 저장소로만 보낸다. 실패는 authentication_failed, model_access_denied,
model_timeout, review_timeout, output_truncated, schema_invalid, lease_lost/lease_expired,
validation_failed 등 안전 코드로 남는다. 일부 성공 보고서는 발행하지 않는다.

### Luna v2 보조 연결 경고 (2026-09-23)

사용자 승인 후 새 불변 `analysis-policy-luna-v2.json`에만
`validation.related_claim_policy=omit_invalid_with_warning_v1`을 적용한다.
범위 밖 `related_claim_ids`는 파생 결과에서 제외하며 주장 본문·근거·전제를 고치지 않는다.
암호화 원응답은 보존하고 stage `invocation_metadata.related_claim_diagnostics`에
대상 claim ID·제외 ID·고정 사유를 기록한다. 실제 검증은 제외 후 동일하게 수행한다.
`related_claim_out_of_scope_omitted` validation warning을 해당 문장 및 분석 한계에 표시한다.
`premise_claim_ids`, `evidence_ids`, considered/coverage, 원문·수치·해시 검사는 완화하지 않는다.
종합은 여전히 모든 선행 주장 연결을 요구한다. 중복·자기 참조도 기존처럼 거부한다.
기존 Luna v1/Qwen 정책은 엄격한 동작을 유지하며 과거 실패·보고서를 다시 쓰지 않는다.
새 테이블·migration·응답 schema 변경은 없으며 참조 표식은 유지한다.

## 2026-09-23 검증 off 참조 정책

사용자 요청에 따라 새 Luna v3 정책의 `validation.result_checks=disabled_reference_v1`에서
내용·참조 의미·coverage/considered/요구사항 누락 검증을 수행하지 않는다.
원문 인용·숫자 대조도 끄며 일반 실행의 검증 통과로 표시하지 않는다.
미리보기·보고서에 검증 미실시를 표시하고 `result_validation_skipped` warning을 저장한다.
인증/건별 승인/동결 입력 hash/정책 불변성/lease/JSON schema/DB 식별자 중복·근거 FK/
문서·프로필 소속과 hash/보고서 본문 보존 검사는 유지한다.
이름이 같아도 v1/v2의 정책·결과에는 소급 적용하지 않는다. 실제 모델 품질은 미측정이다.

검사: 저장된 v2 실패 응답의 후보 코드 replay, 기존 회귀+새 off/해시/근거 FK 차단,
PostgreSQL 17.11 저장·REST, 두 폭 경고와 승인 미리보기. 운영 적용/새 호출은 검사 후 진행.

### Luna v4 정책·slice 교정 계약 (2026-10-08, 로컬 구현)

새 불변 `analysis-policy-luna-v4.json`은 `policy_identity=analysis-policy-luna-v4`로 승인 파일을
명시하며, 매핑은 이 값을 v1~v3 내용 기반 판별보다 먼저 확인한다. 모르는 identity는 거부한다.
정책 `execution.review_timeout_seconds=18000`이 검토 전체 Luna deadline이고,
`execution.validation_repair_attempts=1`은 1·2단계의 각 slice에만 적용된다. 최초 응답이
형식·근거 FK·필수 결정 검사를 통과하지 못하면 승인된 같은 동결 입력에 안전한 오류 code와
필드 위치만 더해 완전한 대체 응답을 최대 한 번 요청한다. 3단계 종합과 v1~v3는 자동 교정하지 않는다.
두 원응답은 기존 model-response aggregate 모양을 유지해 암호화 보존하고, 호출 metadata와
보고서 `validation_repair_applied` warning에 교정 사실을 남긴다. 교정 응답도 같은 인용·숫자·
coverage·considered·전제·근거 검사를 모두 통과해야 하며 검사를 끄거나 warning으로 낮추지 않는다.
이 절은 [DEMO-00 STEP-002](work/groups/DEMO/features/DEMO-00-luna-preflight/spec.md)의 로컬 구현
계약이며 운영 배포·정책 import·실제 Luna 호출 또는 품질 검증 완료를 뜻하지 않는다.

## 1489번 가정 분석 v1 (2026-09-23, 운영 적용 전)

기존 심층검토와 별도 계약이다. [작업 명세](0923_assumption-analysis/spec.md)를 따른다.

- `POST /api/notices/{notice_id}/assumption-analysis-previews` (`bundle_id`)는 동결 입력,
  hash, 이전 가정 분석/심층검토 미리보기와 달라진 필드를 반환한다. 전송은 하지 않는다.
- `POST /api/notices/{notice_id}/assumption-analyses` (`preview_id`, `request_id`, 기존
  담당자 헤더)는 승인·입력 재확인 뒤 202 `{id, notice_id}`를 반환한다. 동일 요청의
  replay도 같은 응답이다. 이 가정 버전의 대상은 1489번뿐이다.
- `GET /api/notices/{notice_id}/assumption-analyses`는 실행 목록,
  `GET /api/assumption-analyses/{id}`는 상태·호출 수·현재 호출·단계 부분 결과·근거
  레지스트리·계산표와 완성 보고서(`report`, 미완료는 null)를 반환한다.
- schema는 `bidops.assumption-analysis.v1`. 완료는 세 단계와 8절 설명 본문이 있을 때만
  게시한다. 모델 품질은 `unmeasured_reference`; 사실 주장을 검증된 사실로 승격하지 않는다.
- `preview_changed`, `preview_used`, `active_run_exists`, `idempotency_conflict`는 409.
  기존 Luna readiness/접근 게이트는 유지한다. 미연결 근거는 FK로 만들지 않고 문자열 ID와
  `unlinked`를 보존한다. 원문 인용 불일치·숫자 근거 미확인은 문단 경고다.
- migration `0033_assumption_analysis`: 입력 버전·승인 실행·호출 결과는 append-only.
  공용 `work_job`의 `assumption_analysis` job을 합성 worker 한 슬롯에서 처리한다.
  기존 심층검토 정책/회사 프로필/결과는 수정하지 않는다.


## 가상 SI 3사 데모 계약 (2026-10-09, DEMO-01·02 데모 브랜치 구현; 2026-10-10 DEMO-03 구현, 실제 Luna 대표 1건은 2026-10-11 DEMO-05로 이관)

새 회사 namespace·그래프·입력·비교 DTO는 아래 공통 계약에 고정한다. 기존 API의 wire 의미와 NULL 회사 계보를 유지한다.
DEMO-01은 별도 데모 브랜치에 `GET /api/demo-config`, strict 회사 목록·상세,
회사별 opportunity tracking GET/PATCH, nullable 분석 계보와 legacy NULL 조회·worker 경계를 구현했다.
DEMO-02는 `python -m app.deep_review.cli import-company-knowledge`(`--dry-run` 포함)·`activate-company-knowledge` JSON CLI와
`GET /api/companies/{company_id}/profile`·`/knowledge-graph`·`/profile-evidence/{evidence_id}`를 공통 계약 §4·§8대로 구현했다.
활성 binding이 없으면 profile·graph는 409 `company_profile_not_ready`, 타회사·legacy NULL 자원은 404이며 공개 응답에는 source locator·object key·원문 경로가 없다.
main·운영에는 미반영이다. 회사별 분석·비교 DTO는 아래 DEMO-03 단락이 정한다. DEMO-04(2026-10-12)는 이 DTO를 그대로 소비하는 화면만 추가했다. REST·DB 계약은 바꾸지 않았고, mock 화면 검증만 했다. 실제 인수는 DEMO-05 범위다.
DEMO-04 화면 경로는 `/companies`(회사 선택, 기본 회사를 정하지 않음), `/companies/{company_id}/pre-specs`, `/companies/{company_id}/pre-specs/{notice_id}`, `/companies/{company_id}/profile`, `/companies/{company_id}/deep-reviews/{review_id}`, `/pre-specs/{notice_id}/company-comparison`이다. 회사 추적 PATCH와 심층 생성·재시도는 의도마다 새 UUID v4 `request_id`를 쓰고, 같은 의도의 재시도에는 같은 값을 쓴다.
DEMO-03(2026-10-10, 같은 데모 브랜치)은 공통 계약 §5·§6·§9·§10의 회사별 분석 계약을 구현했다.
- 회사 핏: REST 없이 CLI `python -m app.deep_review.cli import-company-fit-policy --policy <file> --actor <name>`(승인 파일 `company-fit-demo-v2.json`(`bidops.company-fit-policy.v2`, 이력 보존)·`company-fit-demo-v3.json`(`bidops.company-fit-policy.v3` = v2 + `chunking.source_characters`=6000 필수), canonical sha256을 승인 파일과 대조, import만·활성화 없음)과
  `enqueue-company-fit --company-id <uuid> --notice-id <int> --actor <name> [--dry-run]`(worker DB 역할, attempt 1개 queued, `CompanyAnalysisInput(purpose=company_fit, execution_nonce=attempt id, bundle_id=null)`과 FrozenProvenance를 enqueue transaction에서 동결, gate code는 §9 목록(`bundle_not_ready` 포함), exit 0/2/1).
  2026-10-11 개정(STEP-008): 새 enqueue는 v3 정책 행만 쓰고 선택된 행이 v2면 `analysis_policy_unavailable`이며, 이미 동결된 attempt는 저장된 정책 행으로 실행한다. 공고의 최신 ready bundle이 필수(없거나 pinned 구조를 읽을 수 없으면 `bundle_not_ready`)이고
  `documents`/`document_version_ids`는 그 bundle의 문서 집합이며 개요 문서를 포함해야 한다(is_current 문서 fallback 없음). 개요 행 Requirement의 `source_units`는 심층과 같은 분할기 unit(`DeepReviewService._requirements`, max_requirements=1, v3 `source_characters`, inventory 관측 ID=expected_ids 엄격 일치, 불일치 `company_input_invalid`) 중 개요 문서·그 행 evidence 정수 page의 unit이고 `document_requirement_ids`는 그 합집합이며, 연결 unit이 없는 행은 빈 배열이다.
  결과는 `bidops.prespec-company-fit-result.v2`(`reasons[].graph_path_indexes`는 동결 `graph_paths`의 0-based 위치, 중복·범위 밖·타 요구 참조는 검증 실패).
- 회사 심층: `POST /api/companies/{company_id}/pre-specs/{notice_id}/deep-review-previews`(body `{bundle_id,source_verification_enabled:true,review_id?}` → `CompanyDeepReviewPreviewView`, `input`은 이 응답에만), `POST .../deep-reviews`(`{preview_id,source_verification_enabled:true,request_id,bundle_id}` → 202 `CompanyReviewView`), `POST /api/companies/{company_id}/deep-reviews/{review_id}/attempts`(→ 202 기존 AttemptView). nonce=preview id, 승인 재검사도 저장 preview id를 nonce로 재사용, 재시도만 `target_review_id`. 409 `review_exists`(preview 미소비)·`active_attempt_exists`·`preview_used`·`preview_changed`·`version_conflict`(재시도 계보가 현재 아님). 설정 gate(404 DEMO off, 503 `reference_mode_required`·`luna_disabled`·`analysis_policy_unavailable`·`model_binding_invalid`, 409 `company_profile_not_ready`·`overview_not_completed`·`bundle_not_ready`·`company_input_invalid`, 403 `effective_grade_ineligible`=SW사업대상≠Y만)는 replay보다 앞, 상태 검사는 replay 뒤다.
- 회사 읽기(GET, 모델 호출 없음, reference/Luna flag 무관, DEMO off는 404, 타회사 자원은 404): `/api/companies/{company_id}/pre-specs`(`bidops.company-pre-spec-list.v1`; 모집단 SW=Y 사전규격 전체, `q`·`fit`·`tracking_status`·`sort=posted_at_desc|deadline_asc`·`limit`≤500·`offset`, 서버 필터·nulls last·notice_id DESC), `/pre-specs/{notice_id}`, `/pre-specs/{notice_id}/company-fit`(`CompanyScopedFitView[]`: 기존 CompanyFitView+`company_id,graph_version_id,graph_sha256,ontology_version,input_sha256,paths,provenance`, `model_revision` nullable), `/deep-reviews/{review_id}`(`CompanyReviewView`), `/deep-reviews/{review_id}/report`(`bidops.company-report-view.v1` wrapper, 결과 없음 409 `review_not_ready`), `/deep-reviews/{review_id}/evidence/{evidence_id}`, `GET /api/pre-specs/{notice_id}/company-comparison`(`bidops.company-comparison.v1`, §7 slug 오름차순, 최신 생성 실행·fallback 없음, different_input>stale>missing>comparable).
  FrozenProvenance는 동결 snapshot(핏 attempt `provenance_jsonb`, 심층은 승인 preview `provenance_jsonb`)을 그대로 직렬화하고 view와 중복된 identity/hash가 다르면 500 `processing_failed`로 거부한다. fit/review summary는 created_at DESC·id DESC 최신 실행이다.
- legacy 분리: `GET /api/deep-reviews/{id}`·`/report`·`GET /api/evidence/{id}`·`POST .../report-revisions`·`/final-opinions`·`close-deep-review`는 회사 review에 404 `not_found`, legacy preview/check/attempt는 회사 행을 거부한다. NULL 회사 응답은 바뀌지 않았다.
- 정책: 심층 `analysis-policy-luna-demo-v1`(sha256 `9cb6254ef2f7fa3fbc608d775951aed14d958204f5366b30f92da661a4cbc3b0`, v4 파생, `policy_identity` 매핑, `chunking.path_limit_per_requirement`=32 필수, `profile_characters`=8000, execution·validation은 v4 상속)은 `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`로만 선택되고 legacy 전역 활성 정책으로는 거부된다. HP-00은 회사 계보 전용 `analysis-policy-luna-hp-v1`(sha256 `776c3efc908bf005f57df58d153406add592103d7cd7d3874ae9984cd363184b`, `gpt-6-luna`/`high`)을 같은 설정으로 선택 가능한 회사 policy identity 집합에 추가하며, 전역 active로는 거부한다. `global_path_index`·`excluded_path_count_by_requirement`·교정 field path는 프롬프트 sanitizer가 제거하므로 저장·hash·provenance 전용이다.
실제 Luna 대표 1건(원안 T9)은 실행하지 않았고 2026-10-11 재계획으로 DEMO-05로 이관했다. STEP-007은 `bidops-local` 격리 스택 준비와 호출 전 fail-closed 확인까지다.
[ADR-0070](tracking/decisions/0070-multi-company-knowledge-demo.md) · [공통 계약](work/demo-contract.md) · [기능 로드맵](work/constitution/roadmap.md).


## 회사 근거 (RL-00, 2026-10-16)

루트랩 실회사 1곳의 근거를 같은 회사 지식 계약으로 읽는다. 쓰기는 CLI(`import-company-knowledge`·`activate-company-knowledge`)뿐이며 REST는 모두 읽기 전용이다. 정본은 [DEMO 공통 계약](work/demo-contract.md)의 "RL 개정"(R1·R3·R4)이고 이 절은 소비자 계약만 적는다. 기능 명세는 `docs/work/groups/RL/features/RL-00-company-ground-truth/spec.md`다.

- `GET /api/company` → `CompanyContextView` = `{schema_version:"bidops.company-context.v1", company: CompanyDTO, expiry_warning_days: int, active_graph_version: {graph_version_id: UUID, created_at: timestamp} | null}`. 키는 전부이며 추가하지 않는다. 사이드바 워크스페이스 이름과 `/company` 상단바의 "마지막 저장 날짜"(`active_graph_version.created_at`)가 쓴다. deep_review `company_knowledge` router가 소유한다(활성 binding이 deep_review 테이블이라 lifecycle이 가질 수 없다, ADR-0045 경계). 그래서 이 router는 prefix 없이 전체 경로를 선언한다.
  - 실회사 행이 없으면 404 `company_not_registered`. 실회사는 있으나 활성 binding이 없으면 200이고 `active_graph_version=null`이다. binding과 graph version의 회사·profile이 어긋나거나 실회사가 둘 이상이면 500 `processing_failed`다.
  - `expiry_warning_days`는 설정 `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS`(기본 60, 1..365)다. "곧 만료"는 qualification value의 `valid_until`이 오늘부터 이 일수 안이거나 이미 지난 사실이며(지난 것은 "만료됨"으로 표시하고 수치에서 빼지 않는다) 화면이 계산한다.
  - `company_not_registered`는 deep_review router 허용 목록과 프런트 `src/lib/apiErrors.ts`에만 등록한다(lifecycle `API_ERROR_CODES`는 바뀌지 않았다).
- `GET /api/companies/{company_id}/profile`의 `facts[].status`는 `confirmed|proposed|inferred|unknown`, `facts[].origin`은 `fictional_scenario|public_document|model_inference|company_brochure|homepage|user_interview|agent_proposal`로 넓어졌다. `GET …/profile-evidence/{evidence_id}`의 `origin`도 같다. 다른 키·`graph_version_id` 과거 조회·409 `company_profile_not_ready`는 그대로다. `proposed` 사실의 evidence는 1개 있으나 확인 근거가 아니다 — 소비자는 status로 구분한다.
- 회사 경로 중 demo off에서 열려 있는 것은 `GET /api/companies`, `/{id}`, `/{id}/profile`, `/{id}/knowledge-graph`, `/{id}/profile-evidence/{eid}`와 `GET /api/company`뿐이다. 회사별 추적 PATCH·회사별 사전규격/심층 경로·SPA `/companies/*`·`/pre-specs/{id}/company-comparison`은 계속 404다. 위 GET 경로의 GET이 아닌 method도 404다. 예외: `BIDOPS_RL_ANALYSIS_ENABLED=true`이면 RL-03이 `GET /api/companies/{id}/pre-specs/{nid}/verdict`와 `POST …/verdict-feedback`만 더 열고(서비스는 실회사만 받는다), 사업기회 경로 `/api/opportunities/{id}/verdict*`·`/api/analysis/transfer-policy`는 RL이 꺼져 있으면 404다("카드 기반 참여 판정" 절).
- CLI 오류 code 추가: `real_company_exists`(실회사는 DB 전체에서 1곳, 다른 slug의 두 번째 실회사)·`fictional_requires_demo`(`BIDOPS_DEMO_ENABLED`가 꺼진 채 가상회사 파일 import, `--dry-run` 포함). 둘 다 exit 2이며 HTTP로는 노출하지 않는다. `company_fictional_required`는 폐기했다. import 출력 JSON은 기존 9키에 `is_fictional`·`status_counts`를 더한 11키이고 activate 출력(6키)은 그대로다.
- 회사 파일 노드 value 확장(추가 허용, 기존 가상 파일 형태는 그대로 통과):

  | NodeType | 기존 | RL 확장 |
  |---|---|---|
  | domain | string \| null | `{tier:1\|2\|3\|null, keywords:string[], excluded:bool, kind:hardware\|staffing_only\|design_only\|election\|region\|amount_floor\|null}` (`excluded=true`면 `kind` 필수) |
  | qualification | string \| null | `{held:bool, detail:string?, valid_until:date?, issued_on:date?, file_name:string?}` (파일명만, 사본·경로 없음) |
  | capability | `{scope,description}` | `{scope:core\|non_core, description, params:object?}` (`params`는 평면 객체, 값 int·string·bool) |
  | staff_group | `{role,total?,available?,as_of?}` | `+ region:string?, grade:string?` |
  | project | `{role,scope,amount_krw?,started_on?,ended_on?}` | `role`·`scope` null 허용 + `agency:string?`, `year:int?` |

  보유는 확인·세부는 미입력인 사실은 노드 둘로 나눈다(`{held:true,detail:null}` + 별도 `unknown` 노드). status·origin 조합과 파일 종류별 허용 origin은 DEMO 계약 R3이다.
- 읽기 응답에는 graph hash·profile version·원본 위치가 있다. 실무 화면은 이를 DOM에 그리지 않는다(ui-spec §5 운영 정보 금지).

## 브리핑 (RL-01, 2026-10-17)

평일 1회 브리핑의 REST·DB·규칙 파일·CLI·Slack 계약이다. 업무 규칙(후보 모집단·제외·점수)은 [business-rules.md "브리핑 추천·반응"](business-rules.md), 실행 절차는 [operations.md "일일 브리핑·Slack"](operations.md)이 정본이고, 기능 명세는 `docs/work/groups/RL/features/RL-01-daily-briefing/spec.md`다. 브리핑은 lifecycle 모듈이 소유하고 Slack 호출은 `app/core/slack.py` 하나만 한다.

### REST (`bidops.briefing.v2`, RL-03부터; v1에서 키는 그대로이고 `verdict_display` 값만 넓어졌다)

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/briefings/latest` | 없음 | 200 `BriefingView`(가장 최근 `briefing_date`) | 404 `briefing_not_found` |
| `GET /api/briefings/{date}` | path `YYYY-MM-DD` | 200 `BriefingView` | 404 `briefing_not_found`, 422 날짜 형식 |
| `GET /api/briefings/{date}/slack-preview` | path `YYYY-MM-DD` | 200 `{schema_version:"bidops.briefing-slack-preview.v1", channel_id_present:bool, blocks:object[], text:string}` — 실제 전송과 같은 함수가 만든 Block Kit | 404 `briefing_not_found` |
| `PATCH /api/briefings/items/{item_id}/reaction` | 헤더 `X-BidOps-Actor-Name`(+`-Format`); body `{reaction, expected_revision:int≥0, request_id:UUID}` | 200 `BriefingItemView` | 400 `actor_name_required\|actor_name_invalid`; 404 `briefing_item_not_found`; 409 `version_conflict\|idempotency_conflict\|reaction_not_allowed`; 422 body |

- `BriefingView` = `{schema_version:"bidops.briefing.v2", briefing_date, status: generated|empty|collection_incomplete, generated_at, item_count:int(추천 수만), slack_sent_at:ts|null, items:BriefingItemView[], tracked_changes:BriefingItemView[], collection_note:string|null}`. 키는 전부이며 더하지 않는다. `policy_sha256`·`graph_version_id`·`score`는 응답에 없다(운영 정보, DB 열에만). `collection_note`는 저장 열이 아니라 `briefing.warnings`의 수집 회차 경고 code에서 읽는다: `collection_run_missing`→"기준일 수집 회차 없음", `run_ambiguous`→"회차 중복", `collection_run_warnings`→"기준일 수집 회차에 적재 경고가 있습니다", 그 밖은 `null`.
- `BriefingItemView` = `{item_id:UUID, kind: recommendation|tracked_change, rank:int|null, stage: pre_spec|bid_notice|order_plan, notice_id:int|null, order_plan_id:int|null, opportunity_id:int, title, agency, amount_krw:int|null, deadline_at:ts|null, deadline_kind: bid_close|opinion_close|planned_month|null, planned_month:"YYYY-MM"|null, verdict_display, reasons[], blocking[], change_fields:string[], reaction: 대기|채택|무시|나중에|null, reacted_by, reacted_at, reacted_via: screen|slack|null, revision:int≥0, record_path:"/opportunities/<opportunity_id>"}`. `notice_id`와 `order_plan_id`는 정확히 하나만 값이 있다. `tracked_change` 행은 `rank=null`·`reaction=null`이다.
  - `verdict_display`는 **열한 값의 닫힌 집합**이다(v2, RL-03). v1의 다섯 값 `분석 대기|연차 추적|재검토 중|마감 임박|분석 중`에 판정 이름 넷 `진행 가능|조건부 진행|진행 어려움|판단 불가`와 입찰공고용 둘 `사전규격 판정 참조|판정 대상 아님`이 더해졌다. 추적 변화 행(`재검토 중`·`마감 임박`)과 발주계획 추천(`연차 추적`)의 규칙은 v1과 같고, 사전규격·입찰공고 추천 행의 글자는 확장점 `briefing_verdict_display`가 정한다(아래 "카드 기반 참여 판정" 절): 사전규격은 최신 attempt가 대기·실행 중이면 `분석 중`, 아니면 최신 `completed` 판정 이름, 둘 다 없으면 `분석 대기`; 입찰공고는 같은 사업기회의 권위 연결 사전규격에 completed 판정이 있으면 `사전규격 판정 참조`, 없으면 `판정 대상 아님`이다. 제공자가 없거나 RL 분석이 꺼져 있거나 값 집합 밖 글자를 주면 버리고 v1 규칙(`분석 대기`)을 쓴다. 추천 행에 마감 알림이 겹쳐도 표시는 그대로이고 사유만 `change_fields`에 합친다(run 결정 기록 #12).
  - `reasons[]`(최대 3, 순서 고정)는 `{kind:"keyword", text}`·`{kind:"similar_project", count:int≥1}`·`{kind:"repeat_agency", text}`다. 응답 직렬화는 항목마다 `text`·`count` 두 키를 모두 두고 해당 없는 쪽을 `null`로 채운다(예 `{kind:"keyword", text:"유지관리", count:null}`; PostgreSQL strict 응답 테스트가 이 모양을 고정한다). `change_fields`(추적 변화 행의 사유, RL-02 추가형)의 값 집합은 공고 열 이름 `deadline_at|title|budget|estimated_price|method`와 마감 알림 사유 **`deadline_reminder`**다(`deadline_reminder`는 공고 열이 아니므로 규칙 파일 `tracked_change_fields`에 들어가지 않는다). `blocking[]`(최대 2)는 `{kind:"consortium_review"|"deadline_short", text}`다. 지역·하드웨어 등은 제외 조건이라 `blocking`에 없다.
- 반응 PATCH: `reaction`은 `대기|채택|무시|나중에`(되돌리기 = 이전 값으로 새 PATCH). 항목당 반응은 하나이며 "마지막 담당 기록"이다. `expected_revision`이 현재 `revision`과 다르면 409 `version_conflict`(`details.current_revision`), 같은 `request_id`·같은 요청 해시는 저장된 `BriefingItemView` snapshot을 그대로 재생하고 같은 `request_id`에 다른 요청이면 409 `idempotency_conflict`, `tracked_change` 행은 409 `reaction_not_allowed`다. 요청 해시 = canonical JSON `{operation:"briefing.react", item_id, reaction, expected_revision, actor, via}`의 SHA-256, 영수증은 core `IdempotencyRecord`(`operation="briefing.react"`, `aggregate_type="briefing_item"`)이며 fence 로직은 `app/core/idempotency_fence.py` 하나를 `opportunity_tracking`과 브리핑이 공유한다. 반응은 `Opportunity.tracking_*`·`CompanyOpportunityTracking`을 읽지도 쓰지도 않는다.
- 오류 envelope은 "공통 REST 규칙"과 같다. code 등록은 라우터 로컬 map(`routers/briefings.py`)과 프런트 `src/lib/apiErrors.ts`뿐이며 core `api_errors`·lifecycle `API_ERROR_CODES`는 바뀌지 않았다. 등록되지 않은 예외는 500 `processing_failed`다.

### DB (migration `0038_briefing`)

세 테이블 모두 lifecycle 소유다(`tests/app/boundary_map.py TABLE_OWNER`).

| 테이블 | 열(요약) | 제약 |
|---|---|---|
| `briefing` | `id` UUID PK, `briefing_date` DATE, `status`, `generated_at`, `policy_sha256` CHAR(64), `graph_version_id` UUID(**FK 없음** — lifecycle 단독 `init_db`에 참조 테이블이 없다), `item_count`, `excluded_counts` JSONB, `warnings` JSONB, `slack_message_ts`·`tracked_change_message_ts` JSONB NULL(보낸 순서의 `text[]`), `slack_sent_at` NULL, `created_by` | UNIQUE `briefing_date`; CHECK `status IN ('generated','empty','collection_incomplete')` |
| `briefing_item` | `id` UUID PK, `briefing_id`·`notice_id`·`order_plan_id`·`opportunity_id` FK(`RESTRICT`), `kind`, `rank` NULL, `stage`, `score` NUMERIC(6,2) **NULL**(추적 변화 행은 점수가 없다), `reasons`·`blocking`·`change_fields` JSONB, `deadline_at`·`deadline_kind`·`planned_month`·`amount_krw`, `reaction`·`reacted_by`·`reacted_at`·`reacted_via` NULL, `revision` INT 기본 0, `slack_message_ts` TEXT NULL(RL-03 추가형, migration 0040 — 그 항목이 실려 보낸 Slack 메시지의 ts) | CHECK 8개: `(notice_id IS NULL) <> (order_plan_id IS NULL)`; `kind IN ('recommendation','tracked_change')`; `stage IN ('pre_spec','bid_notice','order_plan')`; `deadline_kind IS NULL OR IN ('bid_close','opinion_close','planned_month')`; `reaction IS NULL OR IN ('대기','채택','무시','나중에')`; `reacted_via IS NULL OR IN ('screen','slack')`; kind별 형태(추천은 `rank`·`reaction` 필수, 추적 변화는 둘 다 NULL); `reacted_by`·`reacted_at`·`reacted_via`는 모두 NULL이거나 모두 값. 부분 UNIQUE 3개: `(briefing_id, notice_id) WHERE notice_id IS NOT NULL`, `(briefing_id, order_plan_id) WHERE order_plan_id IS NOT NULL`, `(briefing_id, rank) WHERE rank IS NOT NULL` — 한 브리핑에서 공고·발주계획은 한 행뿐이다 |
| `briefing_reaction_event` | `id` UUID PK, `item_id` FK, `revision`, `previous`, `new`, `actor`, `via`, `request_id` UUID, `created_at` | UNIQUE `(item_id, revision)`; ORM `before_update`·`before_delete`가 거부하고 UPDATE·DELETE 권한도 없다(append-only) |

- models와 migration은 같은 CHECK·인덱스 선언을 쓰며 `test_alembic_autogenerate.py` drift는 0이다. 새 테이블은 `tests/app/test_db_migrations.py NEW_TABLES`에 있다.
- 권한(`scripts/runtime-privileges.sql`): web(`app`) — `briefing`·`briefing_item` SELECT/INSERT/UPDATE, `briefing_reaction_event` SELECT/INSERT. `slack-worker`(`worker` 자격) — `briefing` SELECT, `briefing_item` SELECT와 `UPDATE (reaction, reacted_by, reacted_at, reacted_via, revision)` 열만, `briefing_reaction_event` INSERT. **어느 역할에도 DELETE가 없고** 브리핑을 다시 만들거나 지우는 경로도 없다.

### 규칙 파일 `bidops.briefing-policy.v1`·`v2`

**v2(RL-02, 2026-10-17)가 기본이다.** `web/backend/app/lifecycle/policies/briefing-policy-v2.json`이 `core/config.py` 기본 경로(`BIDOPS_BRIEFING_POLICY_PATH`로 바꿀 수 있다)이고, v1 파일(`briefing-policy-v1.json`)은 immutable 파일 규칙에 따라 지우지 않고 그대로 둔다. 로더는 두 schema를 모두 받으며 v1 파일은 마감 알림이 없는 것(`deadline_reminder_days=()`)으로 읽는다. v2 키는 **v1 전체 + `deadline_reminder_days`**이고 `tracked_change_fields`에 `method`가 더해졌다. 최상위 키는 schema별로 아래가 전부이며 더하거나 빼면 `briefing_policy_invalid`로 거부한다(v1 파일에 `deadline_reminder_days`가 있어도 거부). 파일 바이트의 sha256이 `briefing.policy_sha256`에 고정된다. 값을 하나라도 바꾸려면 새 버전 파일(`briefing-policy-v3.json`)을 발행하고 `config.py` 기본 경로를 함께 올린다(immutable 파일 규칙).

| 키 | 값(v1; v2는 표시한 행만 다름) | 허용 범위 |
|---|---|---|
| `schema` | `"bidops.briefing-policy.v1"` | 고정 |
| `policy_identity` | `"briefing-policy-v1"` | `briefing-policy-v<n>` |
| `top_n` | 10 | 1..30 |
| `weights` | `tier1` 30, `tier2` 20, `tier3` 10, `repeat_agency` 25, `similar_project` 25, `sw_target` 10, `amount_in_range` 10 | 각 0..100 |
| `deadline_warning_days` | 7 | 1..30 |
| `tracked_change_fields` | v1 `["deadline_at","title","budget","estimated_price"]`, **v2 `[…, "method"]`**(활동 피드 `notice_corrected`와 필드 집합을 맞춘다) | |
| `slack_items_per_message` | 10 | 1..12 (Block Kit 50 블록 상한) |
| `large_enterprise_threshold_krw` | 2000000000 | 컨소시엄 검토 표식의 상한 상수 |
| `deadline_reminder_days` (**v2만**) | `[3, 1]` | 정수 1..30, 비어 있지 않고 중복 없음. 마감 KST 날짜 − 브리핑 날짜가 이 값일 때 알림(업무 규칙은 business-rules) |

`schema`·`policy_identity` 행의 값은 v1 기준이며 v2 파일은 각각 `bidops.briefing-policy.v2`·`briefing-policy-v2`다.

### CLI 출력과 경고 code

`python -m app.lifecycle.cli build-briefing [--date YYYY-MM-DD] [--send] [--dry-run] [--json]`의 stdout은 JSON 하나다(`--json`이면 한 줄, 아니면 들여쓰기). `--date`는 브리핑 날짜 D(기본값 오늘 KST)이고 수집 회차는 D-1이다. 진단은 stderr로 낸다.

- 키는 전부 아홉이다: `briefing_date`, `status`(주말·생성 실패는 `null`), `created`(같은 날 재실행은 `false`), `item_count`(추천 수), `tracked_change_count`, `excluded`(`hardware·election·design_only·staffing_only·region·amount_floor`별 건수), `warnings[]`, `slack`={`sent:bool`, `message_ts:string[]`, `skipped_reason:string|null`}.
- 종료 코드: 0 성공(주말·이미 있는 날·Slack 건너뜀·`slack_send_failed` 포함), 1 생성 실패(`warnings=[code]`, 행 없음), 2 인자 오류. **`slack_send_failed`는 종료 코드 0이다** — 전송 실패는 `warnings[]`로만 알리므로 호스트 스크립트 `scripts/run-daily-briefing.sh`가 JSON을 읽어 비0(3)으로 바꾼다.
- 경고·실패 code:

  | code | 뜻 | 종료 |
  |---|---|---|
  | `company_not_registered` | 실회사 확정 사실 projection이 없음(제공자 부재·실회사 없음). 행을 만들지 않는다 | 1 |
  | `briefing_policy_invalid`, `company_facts_invalid` | 규칙 파일·회사 사실이 계약과 다름. 행을 만들지 않는다 | 1 |
  | `collection_run_missing` | D-1 notices 회차 `Run` 행 0건 → `status=collection_incomplete` | 0 |
  | `run_ambiguous` | 그 회차 `Run` 행이 둘 이상(추정하지 않음) → `collection_incomplete` | 0 |
  | `collection_run_warnings` | 그 회차의 `IngestWarning`이 1건 이상 → `collection_incomplete` | 0 |
  | `orphan_candidate` | 소유 사업기회가 없는 후보가 있어 항목을 만들지 않음 | 0 |
  | `order_plan_provider_absent` | 확장점 `briefing_order_plan_candidates` 제공자가 없어 발주계획 후보가 빔(빈 목록과 구분) | 0 |
  | `slack_send_failed` | 전송 시도가 실패. 브리핑은 유지, 그때까지 보낸 ts만 저장 | 0 |

- 최종 `slack.skipped_reason`은 아래 값이며 검사 순서는 `weekend` → `dry_run` → `not_requested` → 전송기 검사 → `empty` → `already_sent`다. `null`은 전송을 시도했다는 뜻이다(성공이면 `sent=true`, 실패면 `slack_send_failed` 경고).

  | 값 | 조건 |
  |---|---|
  | `weekend` | D가 토·일. 행 없음, `status=null`, DB에 닿지 않음 |
  | `dry_run` | `--dry-run` |
  | `not_requested` | `--send` 없음 |
  | `slack_disabled` · `token_missing` · `channel_missing` · `host_not_allowed` | 전송기 호출 전 검사(순서 그대로): `BIDOPS_SLACK_ENABLED`(기본 false), bot token, 채널 ID, 호출 host가 `BIDOPS_SLACK_ALLOWED_HOSTS`에 정확히 있음 |
  | `empty` | `status=empty`이거나 보낼 메시지가 없음, 또는 생성 실패로 행이 없음. 추천이 0건이면 추적 변화만 있어도 `status=empty`이므로 보내지 않는다 |
  | `already_sent` | `slack_sent_at`이 이미 있음 |
  | `null` | 시도함 |

### 확장점과 Slack

- lifecycle `extensions.py`가 선언하고 다른 모듈이 제공한다(lifecycle은 deep_review·screening 테이블을 import하지 않는다, ADR-0045):
  - `company_facts_projection(session) -> CompanyFactsProjection | None` — deep_review 제공. `CompanyFactsProjection = {graph_version_id: UUID, facts: [{fact_key, type, status, label, value}]}`이며 실회사 활성 binding의 비evidence 노드 중 **`status=confirmed`만**이다(제공자가 거르고 규칙이 status를 다시 확인한다). 제공자 없음·실회사 없음은 `None` → `company_not_registered`.
  - `briefing_order_plan_candidates(session, since, until) -> Sequence[int]` — screening 제공. 발주계획별 **최신** C-2 결과가 `qwen_relevance='relevant'`이고 `first_discovered_at`이 `(since, until]`인 발주계획 id를 오름차순으로 낸다. 제공자가 없으면 빈 목록과 경고 `order_plan_provider_absent`다.
  - `opportunity_activity_items(session, opportunity_id) -> Sequence[ActivityItem]` — RL-02가 선언한 **hook**이다. deep_review가 `verdict_completed`(RL-03)와 `draft_prepared`(RL-04, 별도 owner 키 `<deep_review>.proposal`)를 제공한다. 위 "레코드 활동 피드·노트"가 정본이다.
  - `briefing_verdict_display(session, notice_ids) -> {notice_id: str}`, `on_briefing_recommendation`·`briefing_generated` — RL-03이 더한 확장점 둘이다. 아래 "카드 기반 참여 판정"의 "확장점·CLI"가 정본이다.
  - 적재 CLI·web과 같이 이 CLI도 `register_configured_extensions()`로 `BIDOPS_MODULES`가 고른 모듈의 제공자를 등록한다.
- `app/core/slack.py`의 전송기 하나가 `chat.postMessage`(브리핑)·`chat.update`(반응 뒤 갱신)·`chat.postMessage`+`thread_ts`(판정 완료 스레드 답글, `post_thread_reply`, RL-03)·Socket Mode 연결을 모두 맡는다. 호출 전에 enabled·토큰·채널·허용 host를 검사하고 하나라도 어긋나면 네트워크에 닿지 않는다. 토큰은 `SecretStr`이며 로그·응답·오류에 넣지 않고, 전송 payload는 허용한 Block Kit 키(`type`·`text`·`elements`·`style`·`action_id`·`value`)만 쓰고 내용은 `item_id`·제목·기관·금액·마감·이유 텍스트·링크뿐이다. 다른 채널·hosted fallback은 없다.
- 설정: `BIDOPS_SLACK_ENABLED`(기본 false), `BIDOPS_SLACK_BOT_TOKEN`, `BIDOPS_SLACK_APP_TOKEN`, `BIDOPS_SLACK_CHANNEL_ID`, `BIDOPS_SLACK_ALLOWED_HOSTS`(기본 `slack.com,wss-primary.slack.com`), `BIDOPS_PUBLIC_BASE_URL`(레코드 링크 기준 주소). 값 위치는 `env/slack.env`(gitignore, 예시 `env/slack.env.example`)이고 compose overlay `docker-compose.slack-egress.yml`이 web과 `slack-worker`에 준다.
- Slack 버튼 `action_id="briefing_react"`, `value="<item_id>:채택|무시|대기"`. worker는 `request_id = uuid5(SLACK_REACTION_NS, trigger_id)`(`SLACK_REACTION_NS = uuid5(NAMESPACE_URL, "bidops:slack-reaction")`)로 같은 클릭의 중복 전달을 반응 1회로 만들고 `via=slack`으로 화면과 같은 service 함수를 부른다. `나중에`는 화면 전용이다.

## 카드 기반 참여 판정 (RL-03, 2026-10-17)

사전규격 제안요청서를 카드·영역 단위로 추출(Luna) → 결정적 대조(코드) → 역할 3개 → 종합으로 나눠 참여 판정을 만드는 REST·DB·정책·감사 계약이다. wire 원본은 [HP-03](work/groups/HP/features/HP-03-two-tier-analysis/spec.md)·[HP-04](work/groups/HP/features/HP-04-practitioner-verdict/spec.md) spec이고 이 절은 루트랩 차이만 적는다. 업무 규칙은 [business-rules.md "RL 자동 분석과 판정 상태"](business-rules.md), 실행 절차는 [operations.md "RL 카드 판정 운영"](operations.md), 기능 명세는 `docs/work/groups/RL/features/RL-03-fit-verdict/spec.md`다. **판정은 참고 의견이며 적합성 등급·추적 선택·참여 준비·최종 Go/No-Go를 대신하지 않는다.** 결과는 `quality_status=unmeasured_reference`(mock 참조 실행은 `mock_reference`, 결정 B16)로만 표시하며 품질 근거로 쓰지 않는다. 라우터는 deep_review가 소유하고(`routers/verdicts.py`, ADR-0045) 경로 접두사 `/api/opportunities`는 lifecycle 것이다.

### REST

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/opportunities/{opportunity_id}/verdict?attempt_id=` | 사업기회 id, 선택 attempt | 200 `PractitionerVerdictView`. 대상 공고 = 권위 연결 **사전규격**(같은 단계가 여럿이면 `created_at` 최신·id 내림). 사전규격이 없으면 200 `availability=none`·`notice_id=null` | 404 `opportunity_not_found`·`not_found`(RL 분석 꺼짐·실회사 없음) |
| `GET /api/companies/{company_id}/pre-specs/{notice_id}/verdict?attempt_id=` | HP-04 그대로 | 같은 view | 404 `not_found` |
| `POST /api/opportunities/{opportunity_id}/verdict-requests` | 헤더 `X-BidOps-Actor-Name`(+`-Format`), body `{request_id:UUID, resume_from_attempt_id?:UUID}` | 202 `{request_id, attempt_id, status:"queued"}`. 수동 "다시 판정"이며 항상 새 attempt, 아래 "일일 상한" 규칙으로 상한을 검사한다(초과면 409, 큐에 넣지 않음). 같은 `request_id`·같은 요청은 첫 영수증을 재생한다. `resume_from_attempt_id`(결정 B55, 선택)는 그 실패 attempt의 검증된 단계를 재사용해 종합만 다시 실행한다(아래 "종합만 다시 실행"); 같은 `request_id`를 다른 선택으로 쓰면 `idempotency_conflict` | 400 `actor_name_required\|actor_name_invalid`(`system:` 접두 포함); 403 `effective_grade_ineligible`(SW≠Y); 404 `opportunity_not_found\|not_found`(RL 꺼짐·연결 사전규격 없음); 409 아래 표; 422 `invalid_request`·body 검증; 503 설정 gate |
| `POST /api/companies/{company_id}/pre-specs/{notice_id}/verdict-feedback` | 헤더 actor, body `{attempt_id, kind: wrong_verdict\|wrong_unit\|not_requirement\|source_mismatch, unit_id?:string, note?:≤500자, request_id:UUID}` | 201 `{feedback_id}`. append-only이며 판정·추적·Go/No-Go를 바꾸지 않는다. 같은 `request_id`·같은 body는 첫 `feedback_id`를 재생 | 400 actor; 404 `not_found`(attempt가 이 회사·공고의 `card-v1`이 아님); 409 `idempotency_conflict`; 422 `invalid_request`(`unit_id`가 동결 unit이 아님) |
| `GET /api/analysis/transfer-policy` | 없음 | 200 `{schema_version:"bidops.transfer-policy.v1", active: {approval_id, policy_identity, policy_sha256, daily_cap, approved_at, approved_by, today_used:int} \| null}`. 설정 화면용 운영 정보이며 실무 화면에는 없다. `today_used` = 오늘(KST `approved_at`) RL identity 정책 행으로 승인된 attempt 중 **실제 전송한 것**(`analysis.transfer.sent` 감사가 있고 승인 감사의 provider가 `mock-analysis`가 아닌 것)의 수(결정 B17). 대기 중·전송 전 실패·mock attempt는 세지 않는다 | 404 `not_found`(RL 꺼짐) |

- **게이트 두 겹.** (a) 조립 계층 미들웨어(`main.py`)는 `BIDOPS_RL_ANALYSIS_ENABLED=false`이면 `/api/opportunities/{id}/verdict*`·`/api/analysis/transfer-policy`를 등록되지 않은 경로처럼 404로 막고, true이면 `GET …/pre-specs/{id}/verdict`·`POST …/verdict-feedback`만 demo off에서도 통과시킨다(다른 회사별 경로는 RL-00 규칙 그대로). (b) service는 "실회사 ∧ RL enabled" 분기를 더하되 `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED` 검사는 유지한다. 가상회사는 기존 demo 규칙이다.
- **409 코드(수동 요청).** `policy_not_approved`(승인 없음·sha 다름·scope 밖)·`daily_cap_reached`·`active_attempt_exists`·`bundle_not_ready`·`company_profile_not_ready`·`company_input_invalid`·`input_budget_exceeded`·`card_source_selection_incomplete`·`idempotency_conflict`·`resume_source_invalid`(결정 B55: 종합만 다시 실행할 수 없는 원본). `overview_not_completed`는 RL 경로에서 내지 않는다(개요 비의존, D1). 503은 `reference_mode_required`·`luna_disabled`·`analysis_policy_unavailable`·`model_binding_invalid`다. 코드 등록은 deep_review 라우터 로컬 map과 프런트 `src/lib/apiErrors.ts`이며 core `api_errors`·lifecycle `API_ERROR_CODES`는 바뀌지 않았다. 등록되지 않은 예외는 500 `processing_failed`다.
- **`PractitionerVerdictView`** (`schema_version="bidops.practitioner-verdict-view.v1"`, 모든 모델 closed)는 HP-04 키 전부에 RL 가산 키를 더한 것이다. 최상위: `company_id, notice_id(**int \| null**), attempt_id, availability(none|pending|running|completed|failed|needs_human_review|legacy), is_current, stale_reasons[], quality_status, identity, source_binding, result, partial_stage_ids[], error_code, missing_sections[], started_at, finished_at, partial_matrix[]` + RL 추가 `briefing_item_id: UUID|null`, `opportunity_id: int|null`.
  - `notice_id`는 사업기회 별칭에서 연결 사전규격이 없을 때만 `null`이다. 소비자는 `null`을 0으로 접지 않는다.
  - **B4 가산 키(결정 B4; 새 REST 없음).** matrix 행(`result.matrix[]`·`partial_matrix[]`)에 `normalized_requirement: string|null`·`mandatory: bool|null`·`fact_labels: string[]`(대조가 참조한 회사 사실의 라벨), `source_binding.document_versions[]`에 `structure_id: UUID|null`("쪽 전체 보기" 대상 문서 구조, 모르면 `null`). 화면이 문장·필수 여부·근거 라벨을 추정하지 않게 서버가 준다.
  - `source_binding`: `{document_versions:[{document_version_id, source_sha256, structure_id}], company_version_id(=graph_version_id), company_sha256(=graph_sha256, basis 파일 없음), ontology_sha256}`. `identity`: `{policy_id, policy_sha256, model, reasoning_effort, cli_version}`(동결값). 두 값 모두 **화면은 ⋯ "실행 정보" 대화상자에서만** 보여 준다.
  - `availability` 규칙: queued→`pending`, running→`running`, completed→`completed`; failed는 `WorkJob.last_error_code`가 `card_source_selection_incomplete|card_extract_invalid|card_compare_invalid|card_role_invalid|card_synthesis_invalid|card_review_timeout|prompt_rejected`이면 `needs_human_review`, 그 밖은 `failed`(attempt status는 둘 다 `failed`); superseded는 최종 결과가 있으면 `completed`, 없으면 `failed`이며 stale 사유 `superseded`. 명시적으로 고른 narrative attempt는 `legacy`, card attempt가 하나도 없으면 `none`. 기본 attempt는 `DeepReviewApproval.approved_at` 최신 `card-v1`이다.
  - `result`는 completed attempt의 검증된 `synthesis/final` 행이 있을 때만 있다(`verdict`: `진행 가능|조건부 진행|진행 어려움|판단 불가`, `reason`, `blocking_condition_ids`, `checklist`(정확히 5행, 고정 순서 `qualification_track_record·staffing_onsite·amount_period·technology·operations_sla_security`), `matrix`, `cautions`, `conflicts`, `next_actions`; `next_actions[]` = `{unit_id, owner, action, evidence_refs, origin}` — 결정 B55 가산 `origin: "model"|"code"|null`, `code`는 BidOps가 붙인 누락 영역(`unit_id="missing_section:<kind>"`)·격리 unit "사람 확인" 행, `null`은 정책 v9 이전 행). 그 밖의 상태는 `partial_matrix`에 검증이 끝난 compare 행(역할 의견 포함)만 싣고 최종 판정은 없다. 저장된 행이 서로 어긋나면 자동 보정 없이 500 `processing_failed`다.
  - **`rejected_units`(결정 B51, 가산).** 최상위 `rejected_units: [{unit_id, normalized_id: string|null, rule_codes: string[]}]` — 저장된 extract 행의 격리 unit(동결 unit 순서, 상태와 무관, 없으면 `[]`; `normalized_id`는 카드의 요구사항 번호, segment는 null; 모델 문장은 싣지 않음). matrix 행(`result.matrix[]`·`partial_matrix[]`)에 가산 키 `rejected_rule_codes: string[]`(격리 행만 비어 있지 않음)가 붙고, 격리 행은 `type: null`·`fit_status: "unknown"`·`role_findings`·`evidence_refs`·`fact_labels` 빈 배열·`normalized_requirement`·`mandatory` null이다(일반 행의 `type`은 그대로 문자열). 완료 판정에서 `rejected_units`가 비어 있지 않으면 `result.verdict`는 `진행 가능`이 될 수 없고, 최종 행의 목록이 extract 행과 다르면 500 `processing_failed`다. RL-04 제안서 입력의 compare 이유 enum(`bidops.proposal-input.v1.json`)에도 `extract_rejected`가 더해졌다(요구사항 절은 모든 카드를 그대로 연결하고 격리 카드는 그 고정 compare 행으로 나간다; 유형 기준 절은 격리 unit을 고르지 않는다).
  - **`missing_sections`(결정 B23).** 최상위 `missing_sections: ("overview"|"schedule"|"budget"|"eligibility"|"evaluation"|"contract")[]`는 동결 입력 `card_analysis.missing_sections`(selector가 원문에서 찾지 못한 영역) 그대로이며 상태와 무관하게 실린다(판정 없음은 `[]`). `card-sections-v2` 입력은 영역이 빠져도 종합까지 가므로 **`completed`인데 `missing_sections`가 비어 있지 않을 수 있다** — 그 영역의 요구사항은 선택된 unit이 없어 "확인 필요"(unknown)이고, 이때 `result.verdict`는 `진행 가능`이 될 수 없다. `card-sections-v1` 입력은 지금처럼 종합 전에 `card_source_selection_incomplete`(`needs_human_review`)로 멈춘다. 저장된 `synthesis/final` 행의 `missing_sections`가 동결 입력과 다르거나 영역 누락인데 `진행 가능`이면 500 `processing_failed`다. view 키 집합은 바뀌지 않았다(이 키는 처음부터 있었다).
  - `is_current`·`stale_reasons`(순서 `company_changed, ontology_changed, documents_changed, policy_changed, superseded`)는 기존 회사 심층 현재성 규칙을 성분별로 푼 것이다. `card-v1`은 개요를 비교하지 않고 동결 `overview_*`가 둘 다 null인지 본다. SW 플래그 변화는 현재가 아니게 만들지만 HP-04 사유 값이 없다.
- 오류 envelope은 "공통 REST 규칙"과 같다.

### 정책·단계 contract

- 정책 파일 `web/backend/app/deep_review/policies/analysis-policy-luna-rl-v1.json`(immutable, sha256 `9687c49be2cfb0400b97aaa038d19536e2b6a7b792ab957569ef9bc319976c4a`): `policy_identity="analysis-policy-luna-rl-v1"`, `pipeline_version="card-v1"`, `model_endpoint_ref="codex-exec"`, `model_name="gpt-6-luna"`, `generation.reasoning_effort="high"`, `execution.cli_version="0.162.1"`, `review_timeout_seconds=3600`, `card`={`batch_size` 8, `batch_max_chars` 12000, `repair_attempts` 1, `target_seconds` 2400}, `quality_status="unmeasured_reference"`. `prompt_output_contract.company_input_rule`은 실회사 문구다(confirmed만 근거, proposed·unknown은 보유·미보유 어느 쪽 근거도 아님). 값을 바꾸려면 새 버전 파일을 발행한다. 실행은 이 파일이 아니라 `import-profile-policy --policy <파일>`로 import한 `AnalysisPolicyVersion` 행(`BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`)을 고르며, demo 선택 env와 분리된다. `resolve_company_deep_policy`는 RL 경로에서 `card-v1`·`analysis-policy-luna-rl-v1`~`-v8`(`RL_POLICY_IDENTITIES`)만, demo 경로에서 `narrative-v2`만 받는다.
- **정책 v2(결정 B23)** `analysis-policy-luna-rl-v2.json`(immutable, sha256 `e733e94a02b1240794ac50b7397d3974fb241917cf73fdeed009ba4ba0c4ff3b`)은 v1과 `policy_identity="analysis-policy-luna-rl-v2"`·`card.selector="card-sections-v2"`·종합(`synthesis`) 단계 지시문 끝에 붙은 `missing_sections` 규칙 문장(결정 B24: 입력 `missing_sections`는 찾지 못한 원문 영역이고 그 요구사항은 unknown이며, 비어 있지 않으면 판정은 "진행 가능"이 될 수 없고 상한은 "조건부 진행") 세 가지만 다르다(`card` 키 집합: v1 = 포장 4키 정확, v2 = 포장 4키 + `selector` 정확). v1 파일·행은 그대로 import·실행할 수 있다(v1 행은 `card-sections-v1`). RL identity는 모두 `COMPANY_POLICY_IDENTITIES`·`_LUNA_POLICY_FILES_BY_IDENTITY`에 있고 전역 active policy가 될 수 없다. 정책 승인(`approve-transfer-policy --policy <identity>`)은 요청 identity = 선택 행 identity = 정책 파일 identity여야 하며, 승인은 행 canonical sha 단위라 새 버전 행은 새로 승인해야 한다. 일일 상한 `today_used`는 RL identity 행을 모두 함께 센다.
- **정책 v3(결정 B30)** `analysis-policy-luna-rl-v3.json`(immutable, sha256 `635f673063ca1a92fb751aea6ffbdb76c54e0d70309b9f0a1e84d961fe192b12`)은 v2와 `policy_identity="analysis-policy-luna-rl-v3"`·`card.selector="card-sections-v3"`·추출(`extract`) 단계 지시문 세 가지만 다르다(역할·종합 지시문은 B24 문장까지 v2 그대로, `card` 키 집합은 포장 4키 + `selector` 정확). 추출 지시문은 검증기가 이미 강제하던 계약을 명시한다: 입력 unit마다 정확히 한 item·입력 순서·`unit_id` 동일(나누기·합치기·건너뛰기 금지, 한 unit의 여러 조건은 그 item의 constraints, 제목만 있는 unit도 제목을 인용한 item 하나), `concept_candidates` = 그 unit의 `expected_concepts`를 그대로 복사(의미 매핑·추가 금지, null concept 금지), 모든 quote·`alias_text`는 같은 unit 지정 block의 정확한 부분 문자열, 숫자 제약의 quote는 그 숫자 하나만 담는 가장 짧은 부분(여러 숫자는 operator `unknown`일 때만), `kind=date`는 quote에 `YYYY-MM-DD`·`YYYY.M.D`·`YYYY년 M월 D일` 완전 날짜가 있을 때만(값 `YYYY-MM-DD`; 연도·월 등은 `kind=text`로 원문 복사), `unit=person`은 `N명`일 때만(서버·라이선스 수는 `unit=null`), `kind=amount`는 원·천원·백만원·억원만(값 KRW), operator 어휘(이상·최소=`gte`, 이하·이내·최대=`lte`, 표지어 없는 값=`eq`, 양방향·범위 `N~N`·대안 `N/N`·초과·미만·약·정도·전후·내외·착수 후·계약 후=`unknown`), `fact_key`는 항상 null(회사 사실 연결은 코드의 `resolve_fact_key`), 같은 item 안 중복 제약·근거·개념 금지, `normalized_requirement`의 숫자는 unit 원문에 있어야 함. 검증기(`validate_requirement_extract`)는 바뀌지 않았다. v1·v2 파일·행은 그대로 import·실행할 수 있다.
- **정책 v4(결정 B33)** `analysis-policy-luna-rl-v4.json`(immutable, sha256 `8cc623f280ca5d155073ecd261f5a2a1ecd3a8d497fc5aec9c815537923183d7`)은 v3와 `policy_identity="analysis-policy-luna-rl-v4"`·`stage_schema="bidops.requirement-extract.v2"`·추출 지시문 세 가지만 다르다(selector는 `card-sections-v3` 그대로, 역할·종합 지시문은 B24 문장까지 v3 그대로). `stage_schema`는 identity마다 고정이다(v1~v3 = `bidops.requirement-extract.v1`, v4 = `…v2`; 어긋나면 import·실행 거부). 추출 지시문: 입력 unit마다 item 하나·입력 순서, 개념·operator는 출력하지 않음(코드가 파생), quote는 정확한 부분 문자열, kind/unit 표(amount=KRW, duration=month·day·year, count=`N명`일 때만 person 아니면 null, percentage=percent, date=null·값 `YYYY-MM-DD`·완전 날짜일 때만, boolean·text=null), `N시간`·`N일 이내`·`다음 달 N일까지` 같은 시간·상대/기한 날짜는 `kind=text`·`unit=null`, 숫자 제약은 그 숫자 하나만 인용, `fact_key` null, 중복 금지. v1~v3 파일·행은 그대로 import·실행할 수 있다.
- **정책 v5(결정 B35)** `analysis-policy-luna-rl-v5.json`(immutable, sha256 `19d7ff26fb9899f95237ec931c440bfad89feb42e3626fba89c33132f42928b2`)은 v4와 `policy_identity="analysis-policy-luna-rl-v5"`·추출 지시문 두 가지만 다르다(출력 계약 `bidops.requirement-extract.v2`·selector `card-sections-v3`·역할·종합 지시문 그대로, runner·schema 변경 없음). 추출 지시문: 숫자 제약 인용 = 숫자 + 단위어 + 붙은 비교어를 원문 그대로(`5일 이상`·`9글자 이상`·`90%를 초과`·`3회 미만`·`3초 내에`·`4시간 이내`), 맨 숫자나 단위·비교어 앞에서 끊은 인용 금지(거부되고 repair 없음), 분·초·글자·시간(`N분`·`N초`·`N글자`·`N시간`)·간격(`10분 간격`)·상대/기한 날짜는 `kind=text`·`unit=null`, 나머지 v4 규칙 유지(v4의 "가장 짧은 부분 문자열" 문구 삭제). v1~v4 파일·행은 그대로 import·실행할 수 있다.
- **정책 v6(결정 B37)** `analysis-policy-luna-rl-v6.json`(immutable, sha256 `84e94954c08a43e5751d1514cf1a02e6865c9d6f05c6483777785e29faf8534a`)은 v5와 `policy_identity="analysis-policy-luna-rl-v6"`·추출 지시문 두 가지만 다르다(v2 계약·selector v3·역할·종합 그대로, runner·schema 변경 없음). 추출 지시문 규칙 (4) 끝에 두 문장을 더했다: 숫자 인용은 block 안에서 정확히 한 번 나와야 하고 반복되면 왼쪽 인접 단어를 붙여 유일하게 만든다(`1회` 대신 `월 1회`·`연 1회 이상`; 반복 인용은 거부·repair 없음), 날짜 범위 `A ～ B`는 `kind=text`로 원문 그대로이며 인용에 쓰이지 않은 기간·개수 등 숫자를 계산하지 않는다. v1~v5 파일·행은 그대로 import·실행할 수 있다. **v6로는 실제 호출을 하지 않았다**(B37: 이 배치 실제 호출 종료).
- **정책 v7(결정 B51) — 항목 단위 추출 실패 격리.** `analysis-policy-luna-rl-v7.json`(immutable, sha256 `2ba1d631b02d71b7c5fca251634bdc756c23b0308226ff14c741da5c2a631710`)은 v6와 `policy_identity="analysis-policy-luna-rl-v7"`·종합 지시문 끝 문장(입력 `rejected_units`는 BidOps 근거 검증에 실패한 unit이며 그 요구사항은 unknown·사람 확인 대상이고 어느 역할 결과에도 없다; 비어 있지 않으면 "진행 가능" 금지·상한 "조건부 진행"; 격리 unit의 요구를 추측하지 않는다) 두 가지만 다르다(추출 지시문·v2 계약·selector v3·역할 지시문 그대로, runner·schema 변경 없음). 격리는 v7 identity에서만 켜진다(`ITEM_ISOLATION_POLICY_IDENTITIES`); v1~v6은 지금처럼 묶음 단위 실패다. `BIDOPS_RL_ANALYSIS_POLICY_PATH` 기본값은 v7 파일이며 v1~v6 파일·행은 그대로 import·실행할 수 있다.
  - **격리 규칙.** 구조 실패(v2 출력 schema·조립 객체의 pydantic 규칙: kind×unit·값 형식·중복·unit당 item 수/순서)는 지금처럼 호출 전체에 repair 1회이고 남으면 판정 실패다. 그 뒤 검증기가 item별로 증거 계열 규칙을 모은다(`evidence_quote_not_verbatim`·`constraint_quote_not_verbatim`·`constraint_quote_not_unique`·`constraint_quote_truncated`·`constraint_fact_key_invalid`·`constraint_expression`·`requirement_number_untraceable`·`concept_candidates_mismatch`; 규칙과 순서는 기존 검증기 그대로이며 v1~v6 검증기는 첫 위반에서 멈춘다). 하나라도 있는 item은 `rejected` — 모델 내용은 고치지도 쓰지도 않고 원 응답(암호화 저장)에만 남으며, 저장 extract 단계 행의 가산 키 `rejected_units: [{unit_id, rule_codes}]`(batch 순서, 코드만; 옛 행은 `[]`로 읽음)에 기록된다. 자동 보정 없음.
  - **임계.** 격리 unit이 attempt 전체 unit의 25%를 **넘으면**(`rejected×4 > units`, 정확히 25%는 계속) 지금처럼 `card_extract_invalid`(`needs_human_review`)로 실패한다. 누적이며 batch마다 extract·compare 행을 저장한 직후 검사한다(fail fast; 그 batch 행은 사람 확인용으로 남음).
  - **대조·역할.** 격리 unit의 compare 행은 고정 `{fit_status:"unknown", constraint_results:[], evidence_ids:[], reason_codes:["extract_rejected"]}`(새 reason enum 값, 회사 사실 참조 없음)이다. 역할 입력은 요구사항 유형으로 unit을 고르는데 격리 unit은 모델 유형을 쓰지 않으므로 **어느 역할에도 들어가지 않는다**(역할에는 unknown과 같음).
  - **역할 근거(결정 B53, 모든 정책 버전): unit별 허용 근거 = 그 추출 item의 `evidence` 삼중값 ∪ 그 item 자신의 제약 삼중값 `(locator.source_sha256, locator.block_key, quote)`. 둘 다 추출 단계에서 같은 unit block에 원문 그대로 검증됐으므로 완화가 아니며, 다른 unit의 삼중값·원문과 다른 문자열·다른 block은 계속 `card_role_invalid`다. 역할 cautions·역할 최상위 `evidence_refs`도 같은 집합이고, 종합의 cautions·next_actions는 지금처럼 역할이 그 unit에 인용한 근거만 쓸 수 있다(역할이 인용한 제약 삼중값 포함). 조립은 체크리스트 근거에 item evidence 다음으로 역할이 인용한 그 unit의 제약 인용을 더하고, 판정 보기 matrix 행 `evidence_refs`도 item evidence 다음에 그 행 역할 의견이 인용한 제약 인용을 붙인다(인용이 없으면 지금과 같음, 모양 변화 없음). 더 넓은 집합이라 저장된 옛 행은 그대로 검증된다.** 정책 **v8**(결정 B53) `analysis-policy-luna-rl-v8.json`(immutable, sha256 `63ca5b691bb87822839193d4b33d0af7a6c7b9569faa86e9345da88ca5857d4c`)은 v7과 identity, 그리고 세 역할 지시문·종합 지시문 끝 문장 "evidence_refs may cite the unit's evidence entries or its constraint locator+quote, copied exactly; nothing else." 두 가지만 다르다(추출 지시문·계약·selector·항목 단위 격리 그대로, runner 변경 없음). `BIDOPS_RL_ANALYSIS_POLICY_PATH` 기본값은 v8 파일이며 v1~v7은 그대로 import·실행할 수 있다. 2026-10-18 읽기 전용 재생(T12 8차 attempt `340fb13e…`, 정책 v7): 저장된 operations_risk 답(MPR-5가 제약 인용 3개 + caution 1개를 근거로 씀)이 B53 검증기로 통과하고, eligibility_economics·technical_fit은 그대로 통과하며 저장 행과 같다. 종합은 호출되지 않았으므로 자리표시 종합(모델 출력 아님)으로 결정적 부분만 조립·렌더하면 matrix 32/32행(격리 3행 포함)과 체크리스트 5행이 판정 보기 모델을 통과하고, 제약 인용을 근거로 한 행 1개가 그 인용을 `evidence_refs`에 보인다.
  - **종합 출력 계약 v2·정책 v9(결정 B55).** 종합 출력 계약 **v2**(`bidops.practitioner-verdict.v2`, 파일 `contracts/bidops.practitioner-verdict.v2.json`, sha256 `d57ce8d43010b61aa2492833c0ceadc98798294cf8a579861f7eb226f51e2358`, runner contract `card-synthesis-v2` → `/app/card-synthesis-v2.json`; v1 파일은 그대로)는 `schema_version`·`verdict`·`reason`·`cautions`·`next_actions`만 있고 `blocking_condition_ids`가 없다. 모델은 판정·사유·주의·다음 행동만 쓰며 주의·다음 행동은 **역할 결과에 있는 unit id만** 가리킨다. 코드가 `blocking_condition_ids` = compare 행이 `mandatory=true` ∧ `fit_status=gap`인 unit(추출 순서)을 채워 v1 객체로 만든 뒤 **바뀌지 않은** 종합 검증기에 넣는다(자동 보정 없음: 역할 결과 밖 unit·누락 영역·격리 unit을 가리키는 행동, 지어낸 담당, 인용 안 된 근거, 부족·미해결이 있는데 "진행 가능"은 그대로 `card_synthesis_invalid`). 조립은 모델 행동에 `origin="model"`을 붙이고 그 뒤에 코드 "사람 확인" 행을 붙인다 — 누락 영역마다 `{unit_id:"missing_section:<kind>", owner:null, evidence_refs:[], origin:"code", action:"원문에서 '<영역명>' 영역을 찾지 못했습니다. 이 영역의 조건을 원문에서 사람이 확인하세요."}`, 격리 unit마다(추출 순서) `{unit_id:<격리 unit>, owner:null, evidence_refs:[], origin:"code", action:"원문 근거 검증에 실패한 요구사항입니다. 원문에서 사람이 확인하세요(자동으로 고치지 않음)."}`. 저장 행 모델은 origin이 모두 없거나(v9 이전 행 — 저장 모양·결과 sha 그대로, `origin` 키 없음) 모두 있고, 코드 행이 정확히 누락 영역·격리 unit마다 하나씩 모델 행 뒤에 있으며 담당·근거가 없는지 다시 검사한다. **repair 분류(결정):** v2 출력 schema로 표현되는 위반(키 추가·누락·형식, 예: `blocking_condition_ids`를 냄)만 B33식 schema repair 1회(`rule_codes=["output_schema"]`, `item_indexes=[]`)를 받고, "역할 결과의 unit만"은 attempt마다 허용 id가 달라 schema로 표현되지 않으므로 repair 없이 `card_synthesis_invalid`다. 정책 **v9** `analysis-policy-luna-rl-v9.json`(immutable, sha256 `afaba1d3b41177828443cb8e736e9b4728619a07fdfff2241ecb12d505fd2984`)은 v8과 `policy_identity`·`report_schema="bidops.practitioner-verdict.v2"`·종합 지시문(필드 범위: 판정·사유·주의·다음 행동만, 역할 결과 unit만, 차단 조건은 코드가 계산, 누락 영역·격리 unit 사람 확인 행은 코드가 붙임) 세 가지만 다르다(추출·역할 지시문·추출 계약·selector·격리·근거 규칙 byte 동일). `report_schema`는 identity마다 고정이다(v1~v8 = v1 계약, v9 = v2; 어긋나면 import·실행 거부). 완료 감사 `deep_review.job.completed`에 `synthesis_contract`·`synthesis_code_derived_fields=["blocking_condition_ids","next_actions.person_check"]`가 더해진다.
  - **종합만 다시 실행(결정 B55 설계 선택).** 실패한 card attempt의 검증된 extract·compare·role 행을 새 attempt가 재사용하고 종합만 호출한다. 노출은 **새 표면을 가장 적게 만드는** 기존 수동 판정 요청 body의 선택 필드 `resume_from_attempt_id`다(CLI 없음, 프런트 버튼 없음, migration·권한 변경 없음). 요청은 평소처럼 새 attempt(같은 계보면 같은 review, 정책이 다르면 새 review)를 만들고 **같은 단위 작업 안에서** 전제 조건을 검사한다: 원본이 같은 회사·공고의 `failed`(또는 같은 review에서 밀려난 `superseded`) attempt이고 종합 행 없이 batch별 extract·compare와 역할 3개 행이 정확히 있으며, 원본의 승인된 동결 입력(해시·계보 재검사)과 새 동결 입력이 식별 키(`execution_nonce`·`target_review_id`·`policy_version_id`·`policy_sha256`) 밖에서 모두 같고(회사 binding·묶음·문서·card unit/batch·사실·모델 identity·generation config 포함), 두 정책이 `card-v1`이며 identity·`report_schema`·종합 지시문 밖에서 byte 동일(추출·역할 지시문·stage schema·출력 규칙·포장·selector; identity 이름은 믿지 않음)하고 격리 여부가 같아야 한다(v8 → v9 허용). 어긋나면 409 `resume_source_invalid`이고 새 preview·attempt도 남지 않는다. 통과하면 새 attempt에 `card.resume.requested`(`{source_attempt_id, attempt_id}`, 사람 actor) 감사 하나가 같은 트랜잭션에 남는다. worker는 전송 감사 전에 연결을 다시 검사하고(실패하면 `resume_source_invalid`, 전송·상한 0), 재사용 행마다 새 동결 입력으로 단계 입력을 다시 계산해 저장된 `input_sha256`과 같은지, 결과 sha가 맞는지, compare가 같게 다시 계산되는지, 역할이 다시 검증되는지 확인한 뒤 행을 새 attempt로 복사하고 `card.stages.reused`(`{source_attempt_id, stages:[{stage, stage_key, input_sha256, result_sha256}]}`) 감사 하나를 남긴다. 그 attempt의 `analysis.transfer.sent`는 자기 호출만(`planned_call_count=1`) 적고 일일 상한에 1로 센다. 완료 감사에는 `resumed_from_attempt_id`가 붙고 `call_count`는 종합 호출 수다. 같은 `request_id`를 다른 resume 선택으로 다시 쓰면 `idempotency_conflict`다. 원본 attempt·행은 바뀌지 않는다.
  - 2026-10-18 읽기 전용 재생(T12 9차 attempt `5dddad6d…`, 정책 v8, 작업 트리 코드, 쓰기·모델 호출 없음): 저장된 v1 종합 답은 그대로 `card_synthesis_invalid`(차단 7건·역할 밖 행동 3건). 그 답에서 차단 id와 역할 밖 행동만 뺀 v2 모양 답(시험용, 저장 안 함)은 v2 schema를 통과하고, 코드 차단 조건 0건(필수 gap 없음)으로 바뀌지 않은 검증기를 통과하며, 조립·판정 보기 결과는 **"조건부 진행"**, matrix 32행, 다음 행동 6개(모델 3 + 코드 "사람 확인" 3: `missing_section:contract`·격리 STR-1·MPR-2)다. v9 전제 조건은 attempt 9를 받아들인다(저장 동결 입력·지금 binding/묶음으로 다시 만든 동결 입력 모두 내용 동일, 재사용 행 11개, worker 재계산 입력·compare 15/15 일치, 역할 3개 재검증 통과). 이것은 실제 모델 품질 증거가 아니다.
  - **종합·저장.** v7 종합 payload 최상위에 `rejected_units`(격리 unit id 목록, 비면 `[]`; v1~v6 payload에는 키 없음 — 있으면 거부)가 더해지고 T9 guard가 값(정확히 같은 목록·동결 unit id·중복 없음)을 검사한다. 종합 검증은 목록이 비어 있지 않으면 `진행 가능`을 `card_synthesis_invalid`로 거부한다(`missing_sections` B24와 같은 규칙, 답을 고치지 않음). `synthesis/final` 행에 가산 키 `rejected_units: [{unit_id, rule_codes}] | null`(이 키 이전·v1~v6 행은 null)이 붙고, matrix에 격리 unit 행(`type: null`, `fit_status: "unknown"`, `role_findings: []`, 가산 키 `rejected_rule_codes`)이 들어간다. 체크리스트는 채택된 item만 센다. 저장 행 모델은 목록·matrix 행 일치와 `진행 가능` 상한을 다시 검사한다.
  - 2026-10-18 읽기 전용 재생(저장된 실제 추출 답, v7 격리 경로; 32 unit 중 8개까지 격리면 계속, 9개부터 실패): 5차(v3·v1 계약, batch 0만 있음)는 `10일까지` count/day가 구조 위반(`constraint_unit_invalid`·`output_schema`)이라 격리가 아니라 repair 1회 대상이고, 그 제약을 text로 쓴 repair를 가정하면 MPR-1·MPR-2·MPR-4(`constraint_quote_not_unique`), MPR-3(`constraint_quote_not_unique`·`constraint_quote_truncated`) 4개 격리로 계속(누적 4/32). 6차(v4, batch 0·1)는 batch 0에서 MPR-1·MPR-2·MPR-4(`not_unique`) 3개, batch 1에서 MPR-5(`not_unique`)·MHR-2(`truncated`·`constraint_expression`)·PER-1·SER-2(`truncated`) 4개 격리로 누적 7/32, 계속(남은 batch 2·3은 1개까지만 더 격리 가능). 7차(v5, batch 0)는 MPR-2(`not_unique`)·MPR-3(`constraint_expression`, 날짜 범위에서 계산한 기간 12) 2개 격리로 계속. 세 시도 모두 batch 단위 실패가 격리로 바뀌어 저장된 batch까지는 판정을 이어갈 수 있었지만, 격리된 항목은 판정 근거에서 빠지고 판정 상한은 "조건부 진행"이다. 응답이 없는 batch는 재생할 수 없어 끝까지 통과한다는 증거는 아니다.
- 검증기 수정(결정 B37, **모든 정책 버전에 적용** — 결함 수정): (a) **인용 유일성** — `boolean`이 아니고 숫자가 든 제약 인용은 인용 일치와 같은 원문 부분 문자열 기준으로 지정 block에 **정확히 한 번** 나와야 한다(겹침 포함 계수, 아니면 `card_extract_invalid`, rule `constraint_quote_not_unique`, 근거라 repair 없음). 잘린 인용 검사(앞·뒤)는 그 한 자리에만 적용한다(B35의 "어느 한 자리라도" 규칙을 대체). (b) **범위 감지** — 물결 범위에 `〜`(U+301C)와 물결 앞 `.`/`)`를 더하고(`4〜8시간`, `2027. 1. 1. ～ 2027. 12. 31.`), 숫자 둘 사이의 `-`·`–`·`−`(공백 허용)도 범위로 본다(`4-8시간`). 숫자 묶음이 셋인 전화번호(`032-650-6751`)·ISO 날짜(`2027-01-31`)와 글자 뒤 하이픈(`SFR-001`)은 범위가 아니다. 범위는 operator `unknown`. 2026-10-18 읽기 전용 재생: T12 6차 batch 0은 item[4] `2대`(첫 거부)·`1대`, item[5] `12개월`, item[7] `1회`가 `not_unique`(B35에서 잘린 인용으로 보던 `1회`는 이제 유일성 위반), batch 1은 item[0] `3`(4회 등장)이 `not_unique`, item[2] `5`·item[5] `90%`·item[7] `9`·`10`이 잘린 인용이다. T12 7차 batch 0은 item[5] c[0] `12개월`(같은 block 2회)이 먼저 `not_unique`로 걸리고, item[6] c[0] 날짜 범위의 계산된 duration 12는 여전히 숫자 규칙 위반이다(operator는 이제 `unknown`). 4 batch 원문의 범위 표현 중 예전에 `eq`로 읽던 17건(batch별 4·12·1·0)이 이제 `unknown`이다.
- 검증기 강화(결정 B35, **모든 정책 버전에 적용** — 결함 수정): (a) **잘린 인용 거부** — `boolean`이 아니고 숫자가 든 제약 인용이 지정 block에서 나온 자리 중 하나라도 바로 뒤(공백과 조사 `를`·`을`·`의` 하나 허용)에 비교어(`이상`·`이하`·`이내`·`초과`·`미만`·`전후`·`내외`·`정도`·`까지`·`내(에|로)`)가 이어지거나, 인용이 숫자로 끝나고 바로 뒤에 숫자·단위어(`원`·`천원`·`백만원`·`억원`·`만원`·`개월`·`시간`·`글자`·`%`·`명`·`일`·`월`·`년`·`회`·`건`·`분`·`초`·`자`·`대`·`개`·`점`·`주`·`배`·`차`)가 이어지면, 또는 인용이 숫자로 시작하고 어느 자리의 바로 앞이 숫자이거나 숫자 뒤의 `,`·`.`이면(앞잘림, 결정 B36: `10명`의 `0명`, `150,000,000원`의 `000,000원`; `제3조 5명`·`1. 3명`은 통과) `card_extract_invalid`(rule `constraint_quote_truncated`, 근거 실패라 repair 없음). 인용 일치와 같은 원문 부분 문자열 기준이다. (b) **operator 어휘** — `까지`와 숫자(+단위) 바로 뒤의 `내`·`내에`·`내로`는 `이내`처럼 `lte`, `부터…까지`는 범위라 `unknown`, `미만`·`초과`는 그대로 `unknown`(엄격 lt/gt operator 없음), text·date의 착수후·계약후·상대일·종료일포함 `unknown` 규칙은 그대로 우선한다. 2026-10-18 읽기 전용 재생(T12 6차 attempt `28086c87…`, v4 실제 답): batch 0은 이제 item[7] c[0] count `1회`로 거부된다(같은 block에 `연 1회 이상`이 있어 한 자리가 `이상`으로 이어짐; 다른 자리는 `)`). batch 1은 item[0] c[2] `3`(→`회 미만`), item[2] c[0] `5`(→`일 이상`, 기존 숫자 규칙도 위반), item[5] c[1] `90%`(→`를 초과`), item[7] c[0] `9`(→`글자 이상`), item[7] c[1] `10`(→`분 간격`) 다섯 제약이 잘린 인용이다. 6차의 batch 0 통과 결과는 품질 근거가 아니다.
- **추출 출력 계약 v2(결정 B33)** `bidops.requirement-extract.v2.json`(sha256 `1ff9487bfee68d8fd4b09261f90cca678608356827cd504033add09573709b6d`, v1 파일 불변): 최상위 `{schema_version:"bidops.requirement-extract.v2", items}`, item 키 `{unit_id, type, normalized_requirement, mandatory, constraints, unknowns, evidence}`(**`concept_candidates` 없음**), constraint 키 `{kind, value, unit, fact_key(null만), quote, locator}`(**`operator` 없음**). constraint는 kind별 `anyOf` 7갈래이며 갈래마다 `additionalProperties:false`·전 속성 required이고 kind×unit·값 규칙은 pydantic `CardRequirementConstraint` 표와 같다(amount·duration·count·percentage = number, count unit `person|null`, amount `KRW`, duration `month|day|year`, percentage `percent`, date = 문자열 `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`·unit null, boolean = boolean·unit null, text = 비어 있지 않은 문자열·unit null; 실제 달력 유효성은 pydantic이 본다). runner strict decoding에서 검증된 키워드만 쓴다(B28 테스트에 v2 포함). **조립(코드)**: `assemble_requirement_extract_v2`가 v2 답의 모델 필드를 그대로 두고 item마다 `concept_candidates` = 그 unit의 `card_expected_concepts`, constraint마다 `operator` = 검증기와 같은 `expected_constraint_operator(kind, quote)`(검증기 내부의 기존 operator 규칙을 함수로 꺼낸 것, 동작 불변)를 채워 v1 객체를 만들고, 바뀌지 않은 `validate_requirement_extract`가 판정한다. 저장되는 extract 단계 행은 조립된 v1 객체이고 원 응답은 지금처럼 암호화 저장한다. 원 응답 감사 `deep_review.card.raw_response.stored`(extract)와 완료 감사 `deep_review.job.completed`에 `extract_contract="bidops.requirement-extract.v2"`·`code_derived_fields=["concept_candidates","constraints.operator"]`가 붙는다(모델이 내지 않는 필드를 코드가 파생했다는 기록이며 모델 답 보정이 아니다). **repair 분류**: v2 출력 schema 위반과 조립 객체의 pydantic 구조 위반(kind×unit `constraint_unit_invalid`, 값 형식 `constraint_value_invalid`, 중복 `extract_reference_duplicate`·`extract_unknown_duplicate`, unit당 item 수·순서 `extract_unit_coverage`, schema 일반 `output_schema`)은 schema 급이라 기존 1회 repair를 받고, repair envelope `validation_repair`는 `{scope:"syntax_or_schema_only", rule_codes:[…], item_indexes:[…]}`(코드·정수만, 원문·답 문장 없음)이며 그 원 응답 감사에 `repair_rule_codes`가 남는다. Luna client가 같은 v2 출력 schema로 먼저 거부한 답(`schema_invalid`, 원 응답 포함)도 같은 조립 검사로 코드를 뽑아 envelope에 싣는다(뽑을 수 없으면 `output_schema`). v1 계약의 transport repair envelope은 그대로다. 인용·숫자·개념·근거 실패는 지금처럼 repair 없이 `card_extract_invalid`다. 호출 예산은 그대로(계획 B+4, 최대 2×(B+4)). 2026-10-18 읽기 전용 재생: T12 5차 실제 v3 답(attempt `bd0fe0a3…`)을 개념·operator만 빼고 v4 경로에 넣으면 item 7의 `10일까지` count/day 하나만 `constraint_unit_invalid`·`output_schema`로 repair 대상이 되고, 그 제약을 `kind=text`로 바꾸면 조립 + 검증기를 통과하며 파생 개념은 모델이 복사한 개념과 같다.
- **selector(결정 B23·B30).** 동결 `card_analysis.selector.version`은 `card-sections-v1|card-sections-v2|card-sections-v3`(입력 schema `bidops.card-analysis-input.v1.json`의 enum)이고 `selector.sha256`은 그 버전의 canonical selector 정책 sha다(v1 `ac18ffd120333e80b2dccbde0129969d6202e05b9aa1493119a927400ffa67f1` 불변, v2 `d3ed2e2e6f573b1c5a7830ace9a02e363a9a0ae4929643c871b6d6a309b94617` 불변, v3 `8c4332763fb89a47ebd67a3c9f59575406fcef0a2a878ed66dd3309a39654d38`; 버전과 sha가 어긋나면 `card_source_selection_incomplete`). v2 = v1 + 기호 불릿 제목: 첫 글자가 사설 영역(U+E000–U+F8FF, 실제 HWP의 Wingdings U+F06D 등) 또는 card_units `BULLET_HEADING_SYMBOLS`(■□◆◇○●※ 등) 중 하나이고, 불릿 뒤 제목(NFKC·공백 정리)이 40자 이하이며 v1 영역 키워드를 포함하면 번호 제목보다 한 단계 아래 제목으로 그 영역을 연다. 키워드 없는 불릿·40자를 넘는 불릿 문장·`-` 본문 줄은 제목이 아니다(범위를 열지도 닫지도 않음). v2 입력에서 찾지 못한 영역은 종합을 막지 않고 `synthesis/final` 행의 가산 키 `missing_sections`(nullable 목록, 이 키 이전 행은 null)에 그대로 기록되며, 영역이 하나라도 빠지면 종합 검증이 `진행 가능`을 `card_synthesis_invalid`로 거부한다(모델 답을 고치지 않음; 허용 상한은 `조건부 진행`).
  v3 = v2 + 두 제외(결정 B30; v3 입력의 영역 누락도 v2처럼 종합까지 간다): (1) **쪽번호 없는 목차** — 목차 표식 paragraph(manifest 표식 집합 `목차`·`목 차`·`목    차`…, 문서에 정확히 하나) 뒤에 이어지는 빈 줄과 짧은 제목 항목(번호 제목·로마 숫자·기호/사설 영역 불릿·`붙임`/`별첨` 등 접두·괄호 제목·끝 쪽번호 중 하나, 끝 쪽번호를 뗀 NFKC 길이 50자 이하, `:` 없음)을 unit에서 뺀다. paragraph가 아닌 block(표 등)·본문 paragraph·앞 항목과 같은 항목(본문이 같은 제목으로 다시 시작)에서 멈추며, 멈춘 내용 바로 앞(빈 줄 없이)의 항목은 본문 첫 제목으로 보고 빼지 않는다. 범위 계산은 v1의 쪽번호 목차 제외처럼 바꾸지 않는다. (2) **본문 없는 unit** — 빈 block과 "제목만" 번호 제목(번호 뒤에 `:`·숫자가 없음)만으로 된 segment unit은 버리고 그 영역도 있는 것으로 세지 않는다(기호 불릿 제목은 "사업예산: 134,700천원"처럼 값을 담으므로 본문으로 본다). 폴리텍 실제 구조에서 v3는 v2의 35 unit 중 목차 제목 unit 3개(`1. 사업개요`·`2. 추진배경 및 필요성`·`4. 추진일정`)만 빼 32 unit·4 batch가 되고 `missing_sections=["contract"]`는 같다(2026-10-17 읽기 전용 메모리 재구성, 쓰기 없음).
- runner contract(`web/codex-runner`, client allowlist, `contracts/__init__.py` 맵이 같은 집합): `card-extract-v1`→`bidops.requirement-extract.v1.json`(extract schema는 runner `cli_schema`가 `oneOf`를 지우므로 `anyOf`), `card-extract-v2`→`bidops.requirement-extract.v2.json`(결정 B33, 정책 v4; image `/app/card-extract-v2.json`, client schema `requirement-extract-v2`), `card-role-v1`→`bidops.verdict-role.v1.json`, `card-synthesis-v1`→`bidops.practitioner-verdict.v1.json`. 입력 schema `bidops.card-analysis-input.v1.json`. compare는 모델 호출이 없고 schema 파일이 없다. prompt 상한은 100,000자이며 넘으면 자르지 않고 호출 전 `prompt_rejected`로 실패한다.
- 단계 행 `card_analysis_stage`: `stage ∈ extract|compare|role|synthesis`, `stage_key` = extract·compare는 배치 `0..B-1`, role은 `eligibility_economics|technical_fit|operations_risk`, synthesis는 `final`. 계획 호출 수 = B + 4(추출 B + 역할 3 + 종합 1; repair는 응답 schema 형식 오류에 한해 호출당 ≤1, 증거·숫자 오류에는 없음). 완료는 이 행 집합이 정확히 있을 때만 닫는다.
- 단계 실패 code: `card_source_selection_incomplete|card_extract_invalid|card_compare_invalid|card_role_invalid|card_synthesis_invalid|card_review_timeout`, `input_budget_exceeded`, `prompt_rejected`(`card_source_selection_incomplete`는 원문 선택 실패와 `card-sections-v1` 입력의 영역 누락이며, `card-sections-v2`의 영역 누락은 실패가 아니다 — 결정 B23). 실패는 사람 검토로 보내며 자동 보정·자동 재시도가 없다(호출당 schema repair 1회 제외). 목표 2400초는 넘겨도 완료이고 3600초에서 강제 종료한다.
- compare reason_code는 HP-03 집합에 **`proposed_fact`**가 더해졌다. 대조는 `fact_key` allowlist의 값 경로만 읽는다(`qual:branch.value.detail`·`staff:design_publishing.value.available`·`staff:total.value.total` 등, spec "루트랩 재명세 차이"). `proposed`·`unknown`·`inferred`·값 null은 `unknown`이며 `unknown`은 `gap`(부족)이 되지 않는다. 역할은 compare 결과를 넘을 수 없다(assessment = compare `fit_status` 또는 `unknown`).

### 전송 payload 규칙 (D2·B10·B11)

동결 입력(`deep_review_preview.input_snapshot`, `input_sha256` 대상, v2 키 집합 그대로)과 Luna로 나가는 단계 payload를 구분한다. 단계 payload는 동결 입력에서 결정적으로 만든 projection이며 위반하면 호출 전 `company_input_invalid`로 fail closed한다(strict 검사 `check_card_transfer_payload`).

- 공고 원문 unit(카드 + 여섯 영역 segment)과 이전 단계 검증 결과만 나간다.
- **종합 payload의 `missing_sections`(결정 B24).** `card-sections-v2` 입력의 종합 payload 최상위 키는 `{roles, profile_facts, profile_evidence, missing_sections}`이고 `missing_sections`는 동결 `card_analysis.missing_sections`와 순서까지 정확히 같다(누락이 없으면 `[]`; 영역 키 목록일 뿐 원문·회사 값이 아님). `card-sections-v1` 입력의 종합 payload는 지금처럼 `{roles, profile_facts, profile_evidence}`이며 이 키가 있으면 거부한다. `card-sections-v3` 입력도 v2와 같은 종합 키를 쓴다. 역할 payload는 모든 버전에서 바뀌지 않는다.
- **추출 payload의 `expected_concepts`(결정 B30·B33).** 정책 v4(`stage_schema=bidops.requirement-extract.v2`)는 `card-sections-v3` 입력이어도 추출 payload unit을 동결 unit 그대로 보낸다(`expected_concepts` 없음 — 코드가 호출 뒤 채움). 다만 호출 전에 unit마다 `card_expected_concepts`를 계산해 표현 불가면 지금처럼 `company_input_invalid`다. `check_card_transfer_payload`는 `stage_schema` 인자로 이를 구분한다(v2: 온톨로지 필수, unit = 동결 unit 정확, `expected_concepts`가 있으면 거부). 정책 v3의 경우: `card-sections-v3` 입력의 추출 payload 최상위 키는 그대로 `{schema_version, batch, units, ontology}`이고, `units[]`의 각 행은 동결 unit 그대로 + 키 `expected_concepts: [{concept_id, alias_text}]` 하나다. 값은 코드(`card_expected_concepts`)가 그 unit block 원문에서 계산한다: 기대 집합 = 검증기와 같은 `match_concepts`(같은 정규화)를 block마다 돌린 합집합, `alias_text` = 그 개념 자신의 label/alias가 unit 원문에 쓰인 그대로의 부분 문자열(문맥에서도 `match_concepts`가 맞는 첫 출현이며, 그 alias가 맞추는 개념이 모두 기대 집합 안일 때만), 그 alias가 맞추는 개념 전부를 같은 alias로 한 행씩 넣고 `(concept_id, alias_text)` 정렬·중복 없음. 온톨로지 문구와 공고 원문 부분 문자열만 담기며 회사 값이 아니다. 그런 출현이 없는 기대 개념은 어떤 답도 검증을 통과할 수 없으므로 호출 전 `company_input_invalid`다. `check_card_transfer_payload`는 v3 추출에서 온톨로지를 받아(없으면 거부) unit 키 집합(동결 키 + `expected_concepts` 정확)과 값(재계산과 같음)을 검사하고, 온톨로지가 주어지면 어느 버전이든 `ontology` 행이 그 projection과 같은지 본다. v1·v2 추출 unit에 이 키가 있으면 거부한다. mock card client(B16)는 v3 payload의 `expected_concepts`를 그대로 `concept_candidates`로 복사한다. v2 계약(정책 v4·v5)에서는 개념·operator 없이 `mock_numeric_constraints`(결정 B35)로 `N명`·`N원`·`N일 이상`·`N%`를 단위·붙은 비교어까지 인용한 숫자 제약을 낸다(범위·목록의 뒤 숫자 `～3명` 등은 건너뜀). 폴리텍 실제 동결 입력 4 batch에서 1·5·2·14개 제약이 강화된 검증기를 모두 통과했다(읽기 전용 재생). 결정 B37부터 mock 인용이 block에서 반복되면 왼쪽 단어(숫자·여는 괄호·쌍점 없이 최대 3개)를 붙여 유일하게 만들고, 그래도 안 되면 그 제약을 내지 않는다. 실제 4 batch에서는 확장이 필요한 인용이 없었고 B37 검증기로 1·5·2·14개 모두 유일·통과했다.
- 회사 `confirmed` 사실은 `{fact_key, type, label, status, origin, value}`와 `confirmed` evidence가 나간다(전송 projection에서 qualification value의 `file_name`만 뺀다 — B6, 문자열은 고치지 않고 URL·경로·secret이면 `company_input_invalid`). `proposed`·`unknown`은 **`{fact_key, status}` 두 키만**(값·label·quote·source_refs·evidence 없음, graph 노드는 `{id, status}`).
- 추출 단계는 사실 대신 ontology 개념 `{id, label, aliases}`를 받는다(B10, ontology 문구이며 회사 자료가 아님). **역할·종합 단계는 그 호출의 compare가 참조한 사실만** 받는다(B11): 역할 = 자기 compare 행의 `constraint_results[].fact_ids`, 종합 = 세 역할 참조의 합집합. 참조된 `confirmed`는 값과 evidence, 참조된 `proposed`·`unknown`은 `{fact_key, status}`다.
- 나가지 않는 것: RL-02 노트 본문, 운영 정보(승인 id·cap·`today_used`·브리핑/Slack 식별자·attempt/review id), 모델·정책 identity(`policy_version_id`·`policy_sha256`·`model_name`·`model_revision`·`generation_config_sha256`)와 회사 binding version id·sha.
- 이 규칙은 `card-v1` 전용이며 `narrative-v2`는 그대로다. `overview_run_id`·`overview_sha256`은 v2 키를 유지한 채 `card-v1` 입력에서 **둘 다 null**이다(둘 다 null이거나 둘 다 값, 아니면 `company_input_invalid`; v1 입력에 null이 들어와도 거부). DEMO 계약 §5·§6의 "completed 개요" 요구는 `card-v1`에 적용되지 않는다([DEMO 계약 RL-03 주석](work/demo-contract.md)).

### DB (migration `0040_card_analysis`)

네 테이블 모두 deep_review 소유다(`tests/app/boundary_map.py TABLE_OWNER`, `NEW_TABLES` 등록, models와 migration의 CHECK·인덱스 선언 동일, `test_alembic_autogenerate` drift 0). 이 migration은 `briefing_item.slack_message_ts`(위 브리핑 DB)도 더한다.

| 테이블 | 열(요약) | 제약·trigger |
|---|---|---|
| `transfer_policy_approval` | `id`, `policy_identity`, `policy_version_id` FK, `policy_sha256` CHAR(64)(**행 canonical sha**, 파일 raw sha 아님), `model_name`·`reasoning_effort`·`cli_version`, `scope` JSONB(`{stages:["pre_spec"], purposes:["deep_review"]}`), `daily_cap`, `approved_by`·`approved_at`, `revoked_by`·`revoked_at`·`revoke_reason` NULL, `request_id` | UNIQUE `request_id`; 부분 UNIQUE `policy_sha256 WHERE revoked_at IS NULL`(활성 승인은 정책당 하나); CHECK 해시 형식·`daily_cap` 1..50·`revoked_*` 셋 동시 null/값·scope 객체; trigger가 `revoked_*` 한 번 채우기 외 UPDATE와 DELETE를 거부 |
| `card_analysis_stage` | `id`, `attempt_id` FK, `stage`, `stage_key`, `input_sha256`, `result_sha256`, `payload` JSONB, `created_at` | UNIQUE `(attempt_id, stage, stage_key)`; CHECK stage·key·해시·payload 객체; trigger가 모든 UPDATE·DELETE 거부(append-only) |
| `verdict_request` | `id`, `opportunity_id`, `notice_id`, `actor`, `request_id`, `status`(`queued\|started\|rejected`), `reason`(`daily_cap_reached\|gold_holdout\|manual\|null`), `created_at`, `started_attempt_id` NULL | UNIQUE `request_id`; CHECK status·reason·`started_attempt_id`↔status. 수동·상한 큐·홀드아웃 기록 |
| `verdict_feedback` | `id`, `attempt_id` FK, `kind`, `unit_id`, `note`, `actor`, `request_id`, `created_at` | UNIQUE `request_id`; CHECK kind·note ≤500; trigger가 UPDATE·DELETE 거부 |

- 권한(`scripts/runtime-privileges.sql`, **어느 역할에도 DELETE 없음**): `app` — 네 테이블 SELECT, `transfer_policy_approval`·`verdict_request`·`verdict_feedback` INSERT, `transfer_policy_approval`에 `UPDATE (revoked_by, revoked_at, revoke_reason)`, **`verdict_request`에 `UPDATE (status, started_attempt_id)`**(수동 요청의 홀드아웃 해제·drain의 attempt 연결, 결정 B1). `worker` — `transfer_policy_approval`·`card_analysis_stage`·`verdict_request` SELECT, `card_analysis_stage`·`verdict_request` INSERT, `verdict_request`에 `UPDATE (status, started_attempt_id)`, 그리고 ready 전환이 worker 프로세스에서 일어나므로 자동 경로가 `deep_review`·`deep_review_attempt`·`deep_review_stage`·`deep_review_preview`·`deep_review_approval` 5개 테이블에 **INSERT**(UPDATE·DELETE 없음). `ro_backup` — 기존 전체 SELECT. 권한 테스트의 app 전용 단언을 이에 맞췄다.
- 자동 경로의 preview·review·attempt·approval 행은 `actor_kind=system`, `claimed_name="system:transfer-policy"`, `request_id = uuid5(transfer_policy_approval.id, input_sha256)`이며 생성 감사 action은 `deep_review.auto_create`(사람 경로 `deep_review.create`)다.
- **일일 상한(결정 B17·B19).** 시작 시점(자동·수동·drain)의 비교값은 `today_used`(실제 전송 수) + 오늘 승인된 실제 attempt 중 `queued`·`running`이고 아직 전송하지 않은 것(예약)이다. worker는 claim 뒤 첫 호출 직전에 예약 없이·자기 attempt를 빼고 `today_used >= daily_cap`이면 `daily_cap_reached`로 실패시키며 `analysis.transfer.sent`를 쓰지 않는다(전송 0). 날짜는 `DeepReviewApproval.approved_at`의 KST 날짜다.
- **mock 참조 실행(결정 B16).** `BIDOPS_ANALYSIS_PROVIDER=mock`(참조 모드 필수)이면 같은 단계·검증기를 결정적 mock client가 답하고 runner·네트워크 호출이 없다. 생성 감사 `analysis_provider`·`runtime_model`은 `mock-analysis`·`bidops-deterministic-mock-v1`, 승인 감사 `provider`는 `mock-analysis`이며 `analysis.transfer.sent`·모델 응답 저장이 없고 view `quality_status`는 `mock_reference`다. 계보는 review에 고정되어 실제 경로 worker는 mock 계보 attempt를 `service_unavailable`로 거부한다.
- **브리핑 추천 준비(결정 B18).** `BIDOPS_RL_ANALYSIS_ENABLED`이고 추천받은 사전규격이 SW=Y이면 `briefing_recommendation` 준비가 `DocumentBundleService.create_bundle(eligibility_override="briefing_recommendation")`로 묶음 생성의 등급 자격만 건너뛴다(취득 종결·safe·구조·확정 fence 유지). RL이 꺼져 있으면 `effective_grade_ineligible`, SW≠Y면 `grade_not_priority`로 지금처럼 막힌다. 허용 값은 `briefing_recommendation`·`operator_local_original` 둘이고 그 밖은 `invalid_request`다.

### 감사 action

| action | 시점 | `safe_metadata` |
|---|---|---|
| `analysis.transfer.sent` | worker가 card attempt claim 직후·**첫 모델 호출 전** 1회(attempt당, actor_kind `system`) | 정확히 `approval_id, policy_sha256, input_sha256, unit_count, planned_call_count, notice_id, attempt_id`. 토큰·원문·회사 값 없음 |
| `deep_review.external_transfer_approved` | 자동 approval 생성 시 그대로(actor_kind `system`) | 기존 키. `provider`는 attempt의 provider 계보 `codex-exec` 또는 `mock-analysis`(B16) |
| `prespec_attachment.local_original` | `attach-local-original`이 원본을 연결했거나(status `완료`) 검사가 막았을 때(status `차단`) 1회(actor_kind `human`, aggregate `attachment`) | `provenance="operator_local_original", notice_id, attachment_id, attachment_fetch_id, fetch_status_before, content_sha256, size_bytes, scan_status, status, error_code, document_version_id`. 로컬 경로·파일명·URL·객체 key 없음(결정 B15) |
| `verdict.request.manual` | 수동 "다시 판정" 202 직후(actor_kind `human`, aggregate `verdict_request`) | `opportunity_id, notice_id, attempt_id, released_count`(해제한 홀드아웃·충족한 대기 행 수) |
| `deep_review.card.raw_response.stored` | 모델 응답 한 건을 암호화 저장한 뒤(fence 안) | `stage, stage_key, call_index, repair_attempt, content_object_id, response_sha256`(응답 본문 없음) |
| `deep_review.job.completed` | card attempt 완료 | 기존 키 + `pipeline_version="card-v1", batch_count, call_count, elapsed_seconds, target_seconds, target_missed` |

### 설정 키

`BIDOPS_RL_ANALYSIS_ENABLED`(bool, 기본 false: REST·게이트 개방)·`BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED`(bool, 기본 false: 자동 트리거·drain)·`BIDOPS_RL_ANALYSIS_POLICY_PATH`(기본 `policies/analysis-policy-luna-rl-v9.json`, import 원본; 기본값 이력 v1 → v2(B23) → v3(B30) → v4(B33) → v5(B35) → v6(B37) → v7(B51) → v8(B53) → v9(B55))·`BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`(UUID, 비면 RL 경로 fail closed). 승인 행의 `daily_cap`은 CLI 인자(기본 10, 1..50)다. `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED`는 RL 경로도 요구한다(변경 없음). 모두 꺼짐·미설정이 기본이고 앱 startup은 migration·정책 활성화·모델 호출을 하지 않는다.

### 확장점·CLI

- lifecycle `extensions.py`에 선언하고 deep_review가 제공한다(lifecycle은 deep_review를 import하지 않는다).
  - `briefing_verdict_display(session, notice_ids) -> {notice_id: str}` — 읽기 projection(`RLBriefingVerdictDisplay`). 제공자 없음·RL 꺼짐은 빈 사전이며 브리핑은 v1 규칙으로 돌아간다. 넘긴 공고 수와 무관한 상수 회 조회다.
  - **브리핑 추천 hook** 한 확장점(`register_briefing_recommendation_hook`, owner별) — 메서드 둘: `briefing_generated(session, briefing_date)`는 새 브리핑 행이 막 들어간 직후 항목 호출보다 먼저 한 번 불려 지난날 상한 초과 큐를 처리하고, `on_briefing_recommendation(session, notice_id, briefing_item_id)`는 `kind=recommendation`·stage `pre_spec` 항목마다 부른다(입찰공고·발주계획 추천은 부르지 않음). 둘 다 호출자 transaction 안에서 동기 실행되며 구현이 자기 실패를 가둔다(브리핑 생성은 그 성패와 무관). lifecycle이 deep_review CLI를 import하지 않으려고 drain을 이 hook으로 뒤집었다(결정 B13).
  - 활동 hook `opportunity_activity_items`의 deep_review 제공자: 연결된 사전규격의 `completed` attempt마다 `verdict_completed`("판정 완료 · <판정>", 링크 "판정 보기"). 실패·진행 중은 항목이 아니다.
  - 모두 `register_lifecycle_extensions`로 등록하며 `BIDOPS_MODULES`에 `deep_review`가 없으면 no-op이다. 적재 CLI·web·`build-briefing` CLI가 같은 `register_configured_extensions()`를 쓴다.
- Slack 스레드 답글(`app/deep_review/services/verdict_links.py` → `core/slack.py post_thread_reply`): attempt가 `completed`로 닫힌 직후 worker가 한 번, 그 사전규격의 최신 브리핑 추천 항목의 `slack_message_ts`가 있으면 그 메시지 스레드에 "판정 완료 · <판정> · 확인할 것 n"(n = compare `unknown` 요구사항 수) 한 줄을 단다. ts가 null이거나 전송기 호출 전 검사(켜짐·토큰·채널·허용 host)가 막으면 건너뛰며 오류가 아니다. 실패한 attempt는 쓰지 않고 답글 실패는 판정을 바꾸지 않는다(재시도 없음).
- CLI(`python -m app.deep_review.cli`, stdout은 JSON 하나, stderr는 안전 code만, 모델·네트워크 호출 없음):
  - `approve-transfer-policy --policy <identity> --actor <이름> --daily-cap N [--request-id <uuid>] [--dry-run]` → `{approval_id, policy_identity, policy_sha256, model_name, reasoning_effort, cli_version, daily_cap, request_id, created, errors}`. 선택된 정책 행·요청 identity·정책 파일·HP-00 runner identity가 모두 같아야 한다. exit 2 code: `policy_identity_mismatch|analysis_policy_unavailable|active_approval_exists|invalid_request`(cap 1..50 밖)`|actor_name_required|actor_name_invalid`, 저장 실패 `storage_failed` exit 1. `--request-id` 재생은 `created=false`.
  - `revoke-transfer-policy --approval-id <uuid> --actor <이름> --reason <≤500자>` → `{approval_id, policy_sha256, revoked_by, revoked_at, errors}`. 한 번만(`already_revoked`)이며 이후 자동 경로·worker는 호출 전 `policy_not_approved`로 멈춘다. exit 2: `not_found|already_revoked|invalid_request|actor_name_*`.
  - `drain-verdict-queue [--date YYYY-MM-DD]` → `{mode:"drain", as_of, started_attempt_ids[], started, rejected, remaining, stopped_reason, errors}`. 오늘(KST, 기본) **이전**에 `queued`·`daily_cap_reached`로 쌓인 요청을 오래된 순으로 한 번(catch-up 루프 없음) 처리한다. 상한·승인 없음에서 멈추고(`stopped_reason`), 더는 자동으로 시작할 수 없는 공고(사전규격 아님·추천 아님·홀드아웃·SW≠Y·이미 현재 판정·실패 후 수동 필요)의 행은 `rejected`(reason null)로 닫으며 일시 사유는 `queued`로 남는다. 두 플래그가 꺼져 있으면 아무것도 읽거나 쓰지 않고 `stopped_reason="auto_start_disabled"`다. `build-briefing`이 새 브리핑 직후 같은 service를 부른다.
  - `drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor <이름>` → `{mode:"hold", held[], already_held[], errors}`. RL-05 홀드아웃 표식(`rejected`/`gold_holdout`)을 만들어 자동 트리거를 막고 수동 요청이 `started`로 바꿔 해제한다. exit 2 `invalid_request|not_found|actor_name_*`.
  - `attach-local-original --notice-id <N> --attachment-id <A> --file <path> --expected-sha256 <hex> --actor <이름> [--dry-run]`(결정 B15) → `{notice_id, attachment_id, content_sha256, size_bytes, provenance:"operator_local_original", fetch_status_before, document_version_id, scan_status, preparation:{bundle_id, created, confirmed, reason}|null, dry_run, errors}`. 파일은 symlink가 아닌 일반 파일·50MiB 이하이고 sha256이 기대값과 같아야 하며, 첨부 행은 그 사전규격 소속·현재 G2B 행·바이트 없음(문서 버전 없음, 취득 행이 `완료`·`진행` 아님)이어야 한다. 바이트는 G2B fetcher와 같은 격리→ClamAV·MIME/확장자 검사→source→문서(`source_kind=provider`, 원래 G2B 출처, `created_by_name`=담당자)·구조 경로로 저장되고, 취득 행이 있으면 `완료`·fence+1이 된다(없으면 만들지 않음). 그다음 문서 준비를 trigger `operator_local_original`로 연다(묶음 생성 `eligibility_override`도 같은 이름). G2B 호출 없음(ClamAV·변환기는 문서 경로의 내부 서비스). `--dry-run`은 파일·행 검사만 하고 쓰지 않는다. exit 2: `sha256_mismatch|expected_sha256_invalid|attachment_not_found|attachment_notice_mismatch|notice_not_found|notice_not_pre_spec|attachment_retired|attachment_source_not_g2b|attachment_has_bytes|attachment_fetch_in_progress|attachment_changed|unsupported_extension|file_not_found|file_not_regular|file_empty|file_size_limit|file_changed|malware_detected|mime_mismatch|actor_name_*` 등 비재시도 code; exit 1: `clamav_unavailable|converter_unavailable|service_unavailable|storage_failed` 등 재시도성 code.

## 제안서 초안 (RL-04, 2026-10-18)

완료된 RL-03 카드 판정 하나로 제안서 여섯 절 초안과 요구사항 대응표를 만들고 PDF로 내보내는 REST·DB·정책·계약·artifact 계약이다. 업무 규칙은 [business-rules.md "제안서 초안"](business-rules.md#제안서-초안-rl-04-2026-10-18), 실행 절차는 [operations.md "RL 제안서 초안 운영"](operations.md#rl-제안서-초안-운영-rl-04-2026-10-18), 기능 명세는 `docs/work/groups/RL/features/RL-04-proposal-draft/spec.md`, 미정 선택은 결정 B41~B49(`docs/work/_runs/rlb-20261017/decisions.md`)다. **초안은 서류 준비를 돕는 참고 산출물이다.** 판정·추적 선택·최종 Go/No-Go를 대신하지 않고 가격·투입 인력 수를 만들지 않는다. 참조 실행 표식(`unmeasured_reference`, mock은 `mock_reference`)은 PDF 표지와 생성·완료 감사의 `quality_status`에 남고, `ProposalView`에는 없어 화면은 품질 표식을 그리지 않는다(ui-spec §4.5). 어느 쪽이든 품질 근거로 쓰지 않는다. 라우터는 deep_review가 소유하고(`routers/proposals.py`) `/api/opportunities` 접두사는 lifecycle 것이다. 이 절의 모든 경로는 `BIDOPS_RL_ANALYSIS_ENABLED=false`이면 조립 계층 미들웨어가 `{"detail":"Not Found"}` 404로 숨기고, 켜져 있어도 실회사가 없으면 service가 404 `not_found` envelope을 낸다.

### REST (`bidops.proposal.v1`)

사람 mutation은 헤더 `X-BidOps-Actor-Name`(+`-Format`, `system:` 접두 거부)을 요구하고 body의 `request_id`로 멱등이다. body·path가 Pydantic/FastAPI 검증을 통과하지 못하면 FastAPI 기본 422 `{"detail":[...]}`, 그 밖의 안정 오류는 공통 `error` envelope(`request_id`는 body의 값)이다. 초안 생성·절 재생성의 멱등 영수증은 생성 감사의 `request_id`(같은 actor·같은 대상이면 재생, 아니면 409 `idempotency_conflict`)이고, 나머지 mutation은 core `IdempotencyRecord` fence(`aggregate_type=proposal_draft`, `aggregate_id=<draft_id>`, operation `proposal.sentence.edit`·`proposal.section.review`·`proposal.draft.stage`·`proposal.export.create`)다.

| 호출 | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /api/opportunities/{id}/proposal?draft_id=` | 사업기회 id(병합이면 남은 사업기회), 선택 draft | 200 `ProposalView`. `draft_id`가 없으면 그 사업기회의 최신 draft(`created_at`·id 내림, superseded 포함), 없으면 `{schema_version, draft:null}` | 404 `opportunity_not_found`·`not_found`(다른 사업기회의 draft) |
| `POST /api/opportunities/{id}/proposal-requests` | actor, body `{request_id}` | 202 `{draft_id, status}` — 첫 생성은 `queued`, 같은 `request_id` 재생은 그 draft의 **현재** status(결정 B46) | 400 actor; 404 `opportunity_not_found`; 409 `policy_not_approved`·`daily_cap_reached`·`verdict_required`·`draft_in_progress`·`idempotency_conflict`; 503 `analysis_policy_unavailable`·`service_unavailable` |
| `POST /api/proposals/{draft_id}/sections/{key}/regenerations` | actor, body `{request_id}` | 202 `{section_id, revision}`(새 revision, 이전 revision 보존) | 400; 404 `not_found`(draft·key·절 없음); 409 `daily_cap_reached`·`section_in_progress`·`stage_transition_invalid`(superseded draft 결정 B45, stage `reviewed`·`ready` 결정 B50)·`policy_not_approved`·`idempotency_conflict`; 503 |
| `PATCH /api/proposals/{draft_id}/sections/{key}/review` | actor, body `{request_id}` | 200 `SectionView`(`status=reviewed`). 최신 revision이 `completed`면 `reviewed`(+`reviewed_by`·`reviewed_at`)로 바꾸고, 여섯 최신 revision이 모두 reviewed가 되면 같은 transaction에서 draft `stage`를 `draft→reviewed`로 올린다. 이미 reviewed면 현재 view 200(결정 B46) | 404 `not_found`; 409 `section_not_completed`(queued·running·failed)·`stage_transition_invalid`(superseded draft, 결정 B50)·`idempotency_conflict` |
| `POST /api/proposals/{draft_id}/sentences/{sentence_id}/edits` | actor, body `{text:1..400자, request_id}` | 201 `{edit_id}`. append-only overlay이며 생성 payload는 바뀌지 않는다. 앞뒤 공백을 지운 값을 저장한다 | 404 `not_found`·`sentence_not_found`(최신 completed/reviewed revision에 없는 문장); 409 `stage_transition_invalid`(superseded draft, 결정 B50)·`idempotency_conflict`; 422 `invalid_request` envelope(공백만), 401자 이상은 FastAPI 422 |
| `POST /api/proposals/{draft_id}/exports` | actor, body `{request_id}` | 201 `{export_id, pdf_sha256, created}` — 같은 overlay면 기존 행·`created=false`(그래도 201) | 404; 409 `draft_not_completed`(status가 `completed`·`partial`이 아님; partial은 실패 절을 "생성 실패" 문구로 낸다); 503 `pdf_unavailable`(렌더러·폰트·`proposal-pdf` 자격증명 없음 — 영수증을 남기지 않는다) |
| `GET /api/proposals/{draft_id}/exports/{export_id}.pdf` | 없음 | 200 `application/pdf`, 헤더 `X-BidOps-Export-Sha256`. 저장 바이트의 sha256이 `pdf_sha256`과 같을 때만 내보낸다(다시 렌더하지 않는다, 부작용 없음) | 404 `not_found`(다른 draft의 export 포함); 503 `pdf_unavailable`(객체 없음·hash 불일치) |
| `PATCH /api/proposals/{draft_id}/stage` | actor, body `{stage:"ready", request_id}` | 200 `{stage:"ready"}`. `reviewed`에서만, 되돌리기 없음 | 404; 409 `stage_transition_invalid`(이미 ready 포함, 같은 `request_id` 재생은 200)·`idempotency_conflict`; `stage`가 `ready`가 아니면 FastAPI 422 |

**`ProposalView`** = `{schema_version:"bidops.proposal.v1", draft: DraftView|null}`. `DraftView` = `{draft_id, status, stage, created_at, sections: SectionView[6](spec 절 순서), requirement_coverage:{total, linked, unlinked_unit_ids[]}, counters:{sentences_to_confirm, placeholders, proposed_figures, reviewed_sections}, latest_export:{export_id, created_at, pdf_sha256}|null}`. `SectionView` = `{section_key, title, revision, status, paragraphs[], requirement_links[], error_code}`이며 `title`은 화면 고정 이름(제안 개요·사업수행 실적·수행 전략·요구사항 수행방안·운영·SLA·수행조직), 결과가 없는 절은 `paragraphs`·`requirement_links`가 `[]`, `error_code`는 failed일 때만 값이다. paragraph = `{paragraph_id, heading|null, sentences[]}`, sentence = `{sentence_id, text, kind, sources[{kind, ref, quote}], placeholder_hint|null, edited:bool}` — `text`는 그 문장의 최신 edit(`created_at`·id 순 마지막)이고 `edited=true`(문장 단위, 결정 B46). link = `{unit_id, paragraph_id, fit_status}`이며 `fit_status`는 판정 매트릭스 값(없으면 `unknown`)이다. `requirement_coverage`는 판정의 카드 unit(동결 순서) 중 최신 `requirements` 절이 연결한 수이고, `sentences_to_confirm = placeholders + proposed_figures`다. 운영 정보(정책·모델·입력/결과 sha·토큰)는 응답에 없다.

### 정책·계약

- 정책 `web/backend/app/deep_review/policies/proposal-policy-luna-v1.json`(canonical bytes, raw sha256 = 행 canonical sha `0eb36cf9e4318e447dd2c66f59a060a9ec1d87b92c23326200867060973e7d91`): `schema=bidops.analysis-policy.v2`, `policy_identity=proposal-policy-luna-v1`, `pipeline_version=proposal-v1`, `purpose=proposal`, `codex-exec`·`gpt-6-luna`·`high`, `quality_status=unmeasured_reference`, `execution={automatic_retry:false, cli_version:"0.162.1", timeout_seconds:900, review_timeout_seconds:5400, validation_repair_attempts:1}`, `chunking={max_characters:120000, retries:0, timeout_seconds:900}`, `stage_schema=bidops.proposal-section.v1`, `report_schema=bidops.proposal.v1`, `stages`=여섯 절 순서, `prompt_output_contract` 9키(input·sentence·source·forbidden_content·placeholder·company_input·coverage·unknown·repair), `validation` 6키. loader가 키 집합·값을 닫힌 규칙으로 검사하고 `_LUNA_POLICY_FILES_BY_IDENTITY`로만 승인본을 찾는다. 회사 심층 identity 집합에 넣지 않으며 전역 active policy로 쓸 수 없다(`resolve_active_versions` 거부). 행은 `import-profile-policy`로 넣고 `BIDOPS_PROPOSAL_POLICY_VERSION_ID`로 고른다.
- 절 출력 `contracts/bidops.proposal-section.v1.json`(sha256 `807a743f22ed11efda4035bbd7d04104a117c04fcd6d9a7046b184acbe2edd56`): `{section_key, title, paragraphs[≥1]{paragraph_id, heading|null, sentences[≥1]{sentence_id(UUID), text 1..400자, kind statement|placeholder|proposed_figure, sources[]{kind requirement_unit|company_fact|notice_meta, ref, quote}, placeholder_hint|null}}, requirement_links[]{unit_id, paragraph_id}}`. strict 출력 호환(모든 객체 닫힘·전 키 required·nullable은 type 배열, 조건 키워드 없음). kind별 조건은 schema가 아니라 `proposal_validation.py`가 본다.
- 동결 입력 `contracts/bidops.proposal-input.v1.json`(sha256 `ee8044681f69a9d6533666e380a6d87ea660a2ba1d411d5a4286ab45fa69331f` — 2026-10-18 결정 B52로 compare reason enum에 `extract_rejected`를 가산해 최초 `c7ed9c4a…8687`에서 바뀜; 가산이라 기존 입력은 그대로 통과): 20키 닫힌 객체(`schema_version, purpose:"proposal", execution_nonce(=section id), draft_id, opportunity_id, notice_id, verdict_attempt_id, verdict_input_sha256, company_binding, policy_sha256, model_name, reasoning_effort, section_key, notice_meta{title, agency, deadline_at(KST ISO), method, estimated_price(정수면 소수 없음)}: string|null, units, compares, verdict{verdict, reason, checklist}, company_facts[{fact_key, type, label, value}] confirmed만, missing_facts[{fact_key, status: proposed|unknown}], toc_reference[≥1]`). `input_sha256` = 이 객체의 canonical JSON SHA(절마다 다르다). 입력 읽기는 판정 attempt의 승인 preview `input_snapshot.card_analysis.units`, `card_analysis_stage` extract·compare 행, verdict view와 같은 synthesis 투영(`verdict_view.completed_card_attempt`)이다. 절별 unit: overview=overview·schedule·budget 영역 segment, track_record·organization=없음, strategy=추출 type 기술·기능·보안, requirements=모든 카드 unit, operations_sla=운영·성능SLA·보안·계약. 절별 회사 사실: track_record=`project:*`·`cert:*`, organization=`staff:*`, strategy·requirements·operations_sla=그 절 compare가 참조한 사실, overview=없음(결정 B44).
- **Luna로 나가는 payload는 정확히 8키**(`section_key, notice_meta, units, compares, verdict, company_facts, missing_facts, toc_reference`)이며 identity·운영 키는 동결 입력에만 있다. `check_proposal_transfer_payload`가 키 집합·각 부분의 재계산 일치·금지 키(RL-03 목록 + `draft_id, opportunity_id, verdict_attempt_id, verdict_input_sha256, section_id, purpose`)·비confirmed 사실의 `{fact_key, status}` 외 키·prompt sanitizer 안정성·동결 identity/운영 값/비confirmed 값 문자열의 등장 여부를 보고, 어기면 호출 전 `company_input_invalid`다.
- runner contract `proposal-section-v1`: `web/codex-runner/runner.py` `CONTRACT_SCHEMA_PATHS`(`/app/proposal-section.json`), `web/codex-runner/Dockerfile` COPY, `luna_client.CONTRACT_SCHEMAS`(→ `proposal-section`, prompt 상한 120,000자), `contracts.SCHEMA_FILES`(`proposal-section`·`proposal-input`) — 네 곳과 정책 identity 등록이 한 계약이다. prompt envelope은 `{stage, instruction, output_contract, input}`이고 repair는 `validation_repair{scope:"syntax_or_schema_only", rule_codes[], violations[{rule_code, paragraph_index, sentence_index, source_index, link_index, unit_index}]}`(코드·정수만)를 더한다.

### DB (migration `0041_proposal_draft`)

| 테이블 | 열·제약 |
|---|---|
| `proposal_draft` | `id` UUID PK, `opportunity_id`·`notice_id`·`verdict_attempt_id`·`policy_version_id`·`approval_id` FK(`RESTRICT`), `policy_sha256` CHAR(64), `status` 6값(`queued,running,completed,partial,failed,superseded`), `stage` 4값(`toc,draft,reviewed,ready`), `created_by`, `created_at`, `started_at`·`completed_at` NULL. 인덱스 `(opportunity_id, created_at)` |
| `proposal_section` | `id` UUID PK, `draft_id` FK, `section_key` 6값, `revision`≥1, `status` 5값(`queued,running,completed,failed,reviewed`), `input_sha256`·`result_sha256` NULL(64 hex), `payload` JSONB NULL(object), `error_code`, `prompt_tokens`·`output_tokens`·`latency_ms` NULL, `created_at`, `completed_at`, `reviewed_by`·`reviewed_at`(둘 다 값이거나 둘 다 NULL, reviewed와 동치). UNIQUE `(draft_id, section_key, revision)` |
| `proposal_sentence_edit` | `id`, `section_id` FK, `sentence_id` UUID, `text`, `actor`, `request_id`, `created_at`. append-only |
| `proposal_export` | `id`, `draft_id` FK, `overlay_sha256`, `renderer_version`(`reportlab==x.y.z`), `font_sha256`, `content_object_id` FK, `pdf_sha256`, `page_count`≥1, `created_by`, `created_at`. UNIQUE `(draft_id, overlay_sha256)`, append-only |

| 역할 | INSERT | UPDATE(열 단위 GRANT) | trigger |
|---|---|---|---|
| web(`app`) | 네 테이블 전부(draft는 `queued`·`toc`, section은 빈 `queued` 행만) | draft `stage`·`status`(status는 `superseded`만, stage는 `draft→reviewed→ready`만); section `status`(`completed→reviewed`만)·`reviewed_by`·`reviewed_at` | DELETE 거부 |
| `worker` | 없음(행은 web이 만들고 worker는 claim한다, 결정 B41) | draft `status`·`stage`(`toc→draft` 한 단계)·`started_at`(한 번)·`completed_at`; section `status`(`queued→running`·`queued→failed`·`running→completed`·`running→failed`)·`input_sha256`·`result_sha256`·`payload`·`error_code`·토큰·`latency_ms`·`completed_at`(각 한 번) | 결과 열 재기록 거부 |
| `ro_backup` | — | — | SELECT만 |

draft status 전이(trigger·ORM 같은 규칙, 결정 B45): `queued→running`, `running→completed|partial|failed`, 정착된 draft는 재생성 뒤 `completed|partial|failed` 사이에서만 다시 정착, 어느 상태든 `→superseded`(web만, 종단). 어느 역할에도 DELETE가 없다(`scripts/runtime-privileges.sql`). WorkJob은 `job_type=aggregate_type="proposal_section"`, `aggregate_id=section id`, `max_attempts=1`, `priority`=절 순서 역순(개요 먼저)이며 초안 생성 때 6개를 한 transaction에서 만든다.

### 감사 action

| action | 주체 | safe_metadata |
|---|---|---|
| `proposal.draft.created` | human | `draft_id, opportunity_id, notice_id, verdict_attempt_id, approval_id, policy_sha256, provider(codex-exec 또는 mock-analysis), quality_status, section_count, request_hash`(+ 감사 `request_id`) — provider가 draft의 실행 계보를 고정한다 |
| `proposal.section.regeneration_requested` | human | `draft_id, section_id, section_key, revision, approval_id, request_hash` |
| `analysis.transfer.sent`(aggregate `proposal_section`) | system:transfer-policy | `purpose:"proposal", approval_id, policy_sha256, input_sha256, draft_id, section_id, section_key, notice_id`(결정 B44). 절마다 첫 호출 전에 한 번, mock은 없음 |
| `proposal.section.claimed`·`.completed`·`.failed`·`.raw_response.stored` | system:proposal-worker | 절 id·key·revision과 fence·hash·call/repair 수·`quality_status`·오류 code·rule code·정수 위치뿐(원문·토큰 없음) |

### PDF artifact

렌더러는 `services/proposal_render.py`(ReportLab 5.0.1, `invariant=1`, 백엔드 이미지의 NanumGothic 두 파일 — `BIDOPS_PDF_FONT_DIR`)이고 `services/proposal_export.py`가 seam이다. `renderer_version`=`reportlab==<버전>`, `font_sha256`=`{NanumGothic.ttf: sha256, NanumGothicBold.ttf: sha256}`의 canonical SHA, `overlay_sha256`=`{schema:"bidops.proposal-export-overlay.v1", draft_id, sections[{section_key, section_id, revision, status, result_sha256}](최신 revision), edit_ids[](그 revision들의 edit id 정렬), renderer_version, font_sha256}`의 canonical SHA다. 같은 overlay면 기존 행을 쓰고 다시 렌더·업로드하지 않는다. 내용: 표지(공고명·기관·"초안 · <draft created_at KST 날짜> · 제출본 아님"·참조 실행 표식), 목차(제목만), 여섯 절(overlay 적용), 부록 A 요구사항 대응표(요구사항·정규화 문장·대조 글자·절/문단), 부록 B 출처 목록(번호·kind·ref·quote). 표식: placeholder `#FFF4E5` 바탕+"[채울 것: 힌트]", proposed_figure 같은 바탕+"[제안 수치]", 수정 문장 끝 "[수정됨]", 근거 문장 끝 위첨자 출처 번호, 실패 절 "생성 실패" 문구. 바이트는 namespace `proposal-pdf`(버킷 `bidops-proposal-pdf`, 키 `proposal-pdf/<sha 앞 16자>-<uuid>.pdf`)에 암호화 없이 저장하고 `content_object`(`detected_mime=application/pdf`, `retention_class=proposal-pdf-365d`)·verified `content_object_location`(`encryption_key_ref` NULL)으로 고정한다. 자격증명은 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`(web만, 결정 B48·B49)이고 백업·복구·active hash 검증 대상이다.

### 설정 키

`BIDOPS_PROPOSAL_POLICY_PATH`(기본 `policies/proposal-policy-luna-v1.json`), `BIDOPS_PROPOSAL_POLICY_VERSION_ID`(비면 fail closed), `BIDOPS_PDF_FONT_DIR`(기본 `/usr/share/fonts/truetype/nanum`), `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`, 승인 행 `daily_cap`(proposal 기본 3, 1..20). 실행 조건은 기존 `BIDOPS_LUNA_DEEP_REVIEW_ENABLED`·`BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_ANALYSIS_PROVIDER`(mock은 참조 모드에서만)와 `BIDOPS_RL_ANALYSIS_ENABLED`다.

### 확장점·CLI·worker

- 활동 hook `draft_prepared`: 완료 절이 하나 이상인 채 정착한 draft마다 한 건(`item_id=draft_prepared:<draft_id>`, `at=completed_at`, actor 없음, 제목 "제안서 초안 준비"/"제안서 초안 준비 · 일부 절 실패", 링크 "제안서 보기" `/opportunities/<id>/proposal?draft_id=<draft_id>`). RL 경로가 닫혀 있으면 0건이다.
- CLI는 새로 없다. 정책 행은 `import-profile-policy`, 승인은 `approve-transfer-policy --policy proposal-policy-luna-v1 --actor <이름> [--daily-cap N]`(proposal은 `scope={"purposes":["proposal"]}`, 상한 1..20 기본 3, RL 승인과 서로 보이지 않는다)·`revoke-transfer-policy`다.
- worker 진입점 `app.deep_review.workers.proposal.run_once`는 합성 analysis worker의 같은 슬롯 **마지막** 순서다(별도 process 없음).
