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

웹 클라이언트, 파이프라인 subprocess, 운영 도구가 의존하는 기본 REST 경로는 `/api`다. 발주계획 중심의 새 수집·기회 API는 아직 구현되지 않았으므로 현재 경로로 추정해 호출하지 않는다.

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
- `PreSpecList` query: optional `sw_only`(default `true`), `business_division`, `origin=추적|신규`, `q`, `sort=published|deadline`, `limit` 1..500(default 50), `offset` 0 이상. 회차와 무관하게 누적 `notice.source_type='pre_spec'`를 조회한다. `sw_only=true`는 `sw_business_status='Y'` 또는 추적 중인 발주계획 연결을 포함한다. 이 연결은 같은 opportunity의 notice 링크 status가 `확정`·`사람 확인 완료`·`후보 확인 대기` 중 하나이고 opportunity tracking status가 `계속 추적`·`보류` 중 하나이며, 그 opportunity에 authoritative `order_plan` 링크(`order_plan_id` 존재)가 있는 경우다. 따라서 `검색 미확인`, `미선택`, `종료`, authoritative order-plan 링크가 없는 연결은 예외가 아니다. 응답은 `items`, `total`, `limit`, `offset`, `overview_status_counts`이며 item은 `notice_pk`, `pre_spec_no`, `title`, `agency`, `published_at`, `deadline_at`, `budget`, 원문 그대로의 `sw_business_status`·`business_division`, `origin`, `opportunity_id`, `tracking_status`, `kept_by_tracking`, `document`, `overview_review_status`를 가진다. `opportunity_id`·`tracking_status`·`origin`은 pending/rejected/search-unconfirmed link가 아니라 해당 notice의 authoritative active owner만 투영한다. `document`는 `attachments`, `완료`, `대기`, `진행`, `차단`, `실패` 건수이며 큐 행이 없는 첨부는 총계에만 포함한다. `kept_by_tracking`는 `sw_business_status`가 `Y`가 아닌 행이 위 예외로 남을 때만 `true`다. `origin`은 연결된 opportunity의 `first_registered_stage`에서 `order_plan→추적`, `pre_spec|bid_notice→신규`로 투영하고 연결이 없으면 `null`이다. `overview_review_status`(추가, docs/design/PLAN.md 3단계)는 `prespec_overview_review.status`를 `notice_id`로 LEFT JOIN해 투영한 10값 중 하나이며, 그 notice에 리뷰 행이 아직 없으면 `null`이다(개요 검토 미시작; `awaiting_document`로 접어 넣지 않는다). `overview_status_counts`(추가)는 `{status, count}[]`로, 10개 계약값과 `status=null`(리뷰 행 없음) 총 11개 항목이 이 목록 조회의 필터(`sw_only`·`business_division`·`origin`·`q`)는 전부 반영하되 `limit`/`offset`과 무관하게 **필터에 일치하는 전체 건수**를 담아 항상 존재한다(건수 0인 항목도 포함). 클라이언트는 반환된 `items`(현재 페이지)만 그룹에 채우고 그룹 헤더 건수는 `overview_status_counts`를 표시해 페이지네이션과 그룹 건수 표시를 분리한다. 응답에는 object key·로컬 경로·URL을 넣지 않는다.
  item에는 등급과 자동 문서 준비 필드 다섯이 더 있다([ADR-0049](tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)). nullable `grade`, nullable `grade_source=screening_judgment|human_review`, 비 null `auto_preparation_status`(기본 `not_applicable`), nullable `auto_preparation_reason`, nullable `latest_deep_review_id`다. `grade`가 `null`이면 판정도 사람 정정도 없다는 뜻이고 그때 `grade_source`도 `null`이다 — 둘 중 하나만 채우거나 "없음"을 특정 등급으로 접지 않는다. `auto_preparation_status`는 `not_applicable|waiting_attachments|bundle_draft|bundle_ready|overview_running|deep_review_started|deep_review_ready_for_click|blocked` 여덟 값이며 `not_applicable`은 "대상이 아님"이지 "알 수 없음"이 아니다. `auto_preparation_reason`은 안전 코드이며 어휘는 `grade_not_priority`, `awaiting_fetch`, `no_ready_document`, `bundle_has_blocking_issues`, `bundle_unchanged`, `human_bundle_draft`, `processing_failed`, `not_sw_business`, `bundle_not_auto_ready`, `overview_not_completed`, `overview_recommendation_closed`, `overview_bundle_mismatch`, `deep_review_exists`, `service_unavailable`과 문서 묶음 service가 내는 안전 코드다. 이 다섯 값은 저장된 열이 아니라 조회 시점의 파생값이며 공고 수와 무관한 상수 회 조회로 계산한다. **`GET /api/pre-specs`에는 `grade` 질의 인자가 없다.** 화면의 등급 필터는 이미 받은 페이지만 좁히는 브라우저 쪽 필터이므로 `overview_status_counts`와 비대칭이며, 그 비대칭을 화면이 직접 밝힌다.
  별도의 사전규격 **상세** endpoint는 없다. 상세 화면도 이 목록 endpoint를 쓴다.
- `NoticeListItem`: `id`, `notice_key`, `run_id`, `title?`, `agency?`, `published_at?`, `deadline_at?`, `estimated_price?`, `sample_role?`, `sample_stratum?`, `collection_bucket?`, `grade?`, `readiness?`, `focus?`, `attachment_count`, `attachment_status=none|g2b|manual`이다.
- `ReviewUpsertRequest`: required `run_id`; optional nullable `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `reviewer`; optional `verification_answers`(default `[]`), 요소는 optional nullable `item`, `answer`다. `ReviewResponse`는 `id`, `run_id`, `notice_pk`, 같은 nullable review field, `created_at?`, `updated_at?`, `answers[{id,item?,answer?}]`다. 이 legacy schema의 review 문자열은 wire enum으로 강제되지 않으므로 소비자가 임의의 추가 enum을 가정하지 않는다.
- `AgencyPortalCreateRequest`: required `agency_pattern`, `system_name`, `search_url_template`; optional non-null `enabled`(default `true`), optional nullable `note`. PATCH는 이 다섯 field의 partial body이다. PATCH `enabled`는 nullable이며 `null`을 보내면 현재 값을 바꾸지 않는 no-op이다. `AgencyPortalResponse`는 `id`, 위 다섯 field다.
- legacy `AttachmentResponse`: `id`, `name?`, `url?`, `origin?`, `file_ext?`, `size_bytes?`, `extract_status?`, `created_at?`. `stored_path`는 wire field가 아니며 서버 내부 호환 저장 metadata로만 남는다. notice detail과 첨부 처리 상태에 nested 될 수 있고 다운로드는 `url`의 id 기반 endpoint를 사용한다.
- `RunDetailResponse`는 `RunSummary` 전체와 `collection_scope`, `pipeline[]`, `artifacts[]`, `warning_counts`다. `collection_scope`는 `window_from?`, `window_to?`, `timezone`, `business_area?`, `pre_spec_available?`, `pre_spec_reason?`, `focus_axes[]`, `performance_reference_count?`다. pipeline item은 `name`, `status`, `artifact?`, `script?`, `execution_id?`, `started_at?`, `finished_at?`, `exit_code?`, `execution_allowed`, `message?`다. artifact item은 `name`, `present`, `schema_version?`, `expected_schema_version?`, `valid?`, `warnings[]`다. legacy `status`들은 wire enum으로 강제되지 않는 string이다.
- `RunStatsResponse`: `run_id`, `timezone`, `generated_at`, `collected_count?`, `candidate_count?`, `sample_count`, `priority_review_count`, `audit_missed_count`, `funnel[]`, grade/readiness/focus `*_distribution[]`, `verification_requests[]`, `imminent_deadlines[]`. funnel item은 `key`, `label`, `count?`; distribution item은 `key`, `label`, `count`; verification request는 `item`, `count`, `notice_pks[]`, `profile_sections[]`; deadline item은 `NoticeListItem` 전체와 `blocking_verification_items[]`다.
- `WarningListResponse`: `run_id`, `items[]`, `total`, `level?`, `code?`. warning item은 `id`, `run_id`, `level`, `code`, `message`, nullable opaque JSON `context?`다. `level`은 legacy wire에서 enum으로 강제되지 않는다.
- `NoticeDetailResponse`는 `NoticeListItem` 전체와 `bid_no?`, `bid_ord?`, `source_type?`, `budget?`, `method?`, `url?`, `timezone`, nullable opaque JSON `procurement_class?`, `region_limit?`, `lifecycle?`, `qualification_flags?`, opaque JSON list `focus_matches[]`, `performance_matches[]`, `candidate_sources[]`, `performance_top_score?`, `judgment?`, `attachments[]`, `reviews[]`다.
- `JudgmentResponse`: `id`, `schema_version?`, `grade?`, `readiness?`, `primary_focus?`, `exclusion_category?`, `summary?`, `next_action?`, `perspectives[]`, `counterarguments[]`, `verification_items[]`, `matched_performances[]`. perspective는 `id`, `position?`, `name?`, `assessment?`, `reason?`, `evidence[{id,source?,status?,fact?}]`; counterargument는 `id`, `position?`, `text?`; verification item은 `id`, `item?`, `why?`, `blocking`, `status?`; matched performance는 `id`, `name?`, `match_reason?`, `mismatch_or_limit?`, `source?`, `status?`다. 이 legacy 문자열도 wire enum으로 강제되지 않는다.
- `RelatedNoticeListResponse`: `notice_pk`, `items[]`; item은 `relation=ordinal|unified|pre_spec`, `notice_pk`, `notice_key`, `title?`, `grade?`, `published_at?`, `change_reason?`다. `NoticeHistoryResponse`는 `notice_key`, `items[]`; history item은 `notice_pk`, `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `grade?`, `readiness?`, `focus?`, `summary?`, `corrected_grade?`, `corrected_readiness?`, `review_reason?`다.
- `NoticeRevisionHistoryResponse`는 정확히 `notice_pk`, `judgments[]`, `reviews[]`를 갖는다. judgment item은 `id`, `sequence>=1`, `source_kind=runtime|legacy_import|carry_over`, nullable `run_id`, nullable `recording_execution_id`, nullable `source_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. review item은 `id`, `sequence>=1`, `source_kind=human|legacy_import`, nullable `run_id`, nullable `judgment_revision_id`, nullable `origin_execution_id`, `payload_schema_version`, opaque JSON object `payload`, 64자 lowercase SHA-256 `payload_sha256`, `captured_at`이다. `origin_execution_id`는 judgment 승계 chain 또는 review가 고정한 exact judgment revision의 runtime root이며, legacy/unaligned 이력은 `null`이다.
- `OpportunityListResponse`는 `items`, `total`, `limit`, `offset`이다. 기본 목록에는 `merged_into_opportunity_id`가 없는 active row만 포함한다. item은 `id`, `tracking_status=미선택|계속 추적|보류|종료`, `tracking_reason?`, `tracking_selected_by?`, `tracking_selected_at?`, `recheck_signal`, `recheck_signal_at?`, `recheck_signal_link_id?`, `first_registered_stage=order_plan|pre_spec|bid_notice`, nullable `merged_into_opportunity_id`·`merged_at`·`merge_reason`, `links[]`다. `first_registered_stage=order_plan`이면 화면 의미는 `추적`, 그 밖의 `pre_spec|bid_notice`이면 `신규`이며 이 매핑을 화면이 다시 정하지 않는다.
- `OpportunityDetailResponse`는 위 사업기회 field와 `links[]` 전체를 반환한다. link는 `id`, `stage=order_plan|notice`, `link_type=official|candidate`, `status=확정|후보 확인 대기|사람 확인 완료|검색 미확인`, `search_strategy?`, `attempted_strategies[]`, `agency_match?`, `last_searched_at?`, `evidence_external_no?`, `evidence_bid_no?`, `human_decision?`, `reviewer_name?`, `reviewed_at?`, `review_reason?`, `record_type?`, `record_id?`, `notice_id?`, `order_plan_id?`, `source_type?`, `title?`, `agency?`, `external_id?`, `record_external_id?`다. `검색 미확인` link도 포함하며 이 상태를 `사전규격 없음`으로 변환하지 않는다. target이 있으면 `title`·`record_external_id`가 해당 공고 또는 발주계획을 가리키고, `id`와 `evidence_external_no`로 link 자체와 근거 번호를 식별한다. raw record, filesystem path, object-store metadata는 반환하지 않는다.
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
| `GET /api/opportunities` | optional `tracking_status`, `first_registered_stage`, `sort=created_at|tracking_status|first_registered_stage`, `limit` 1..500(default 50), `offset` 0 이상 | `{items: OpportunityListItem[], total, limit, offset}`; 기본값은 `종료`를 포함한 전체 | 422 query |
| `GET /api/opportunities/{opportunity_id}` | path DB integer opportunity ID | `OpportunityDetailResponse`; `검색 미확인` link를 포함한 전체 link 목록 | 404 `opportunity_not_found` |
| `GET /api/opportunities/{opportunity_id}/deep-reviews` | path DB integer opportunity ID | 200 `{opportunity_id, items[]}` — 연결 공고 전체의 심층 검토 목록 | 404 `not_found`; 422 path; 500 `processing_failed` |
| `GET /api/bid-delta/decision-queue` | `status=pending\|all`(기본 `pending`), `limit` 1..500(기본 50), `offset` 0 이상 | 200 `{items, total, limit, offset}` | 422 query; 500 안전 오류 |
| `PATCH /api/opportunities/{opportunity_id}/tracking-status` | actor headers; body `{tracking_status, reason}` | 200 `OpportunityDetailResponse` | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_not_found`; 422 `tracking_status_invalid|tracking_reason_required` |
| `PATCH /api/opportunities/links/{link_id}/decision` | actor headers; body `{decision=accepted|rejected, reason}` | 200 `OpportunityLinkView`; 동일 actor·판정·이유 replay는 같은 reviewed_at | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_link_not_found`; 409 `candidate_link_required|candidate_decision_conflict|candidate_state_conflict|candidate_target_required|candidate_target_already_authoritative`; 422 body·link ID·blank reason |

추적 상태 변경은 `set_tracking_status()`를 통해 사람 선택과 감사 이벤트를 함께 기록한다. `X-BidOps-Actor-Name`은 인증이 아닌 감사 표식이며, 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 사용한다. `recheck_signal`은 시스템 신호 여부이고 `recheck_signal_at`·`recheck_signal_link_id`는 그 시각과 근거 link를 가리킨다. 이 값들은 사람의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at`과 별도이며, `FinalOpinion` 또는 최종 입찰 `Go/No-Go`로 변환하지 않는다.

### 결정 대기 집계와 큐 응답

[ADR-0053](tracking/decisions/0053-decision-workload-read-contracts.md)의 읽기 전용 계약이다. 세 경로 모두 DB 열을 새로 만들지 않고 기존 목록과 **같은 모집단**을 센다.

- `WorkloadResponse`: `generated_at`(UTC aware)과 `items[]`. item은 `key`, nullable `count`(0 이상), nullable `unavailable_reason` 셋뿐이다. `items`의 순서는 고정이며 `order_plan_pending`, `pre_spec_deep_review_ready`, `tracking_action_required`, `bid_final_decision_pending` 넷이 언제나 모두 있다.
- **제공자 부재와 실제 0은 다르다.** 소유 모듈이 등록되지 않았으면 `count=null`·`unavailable_reason="provider_absent"`이고, screening이 있어도 완료된 C-2 실행이 없으면 `count=null`·`unavailable_reason="no_completed_execution"`이다. 셀 수 있었다면 정수와 `unavailable_reason=null`이다. `null`을 0으로, 0을 `null`로 접지 않는다.
- 각 건수의 소유자는 모듈이다. `order_plan_pending`은 screening이 `GET /api/order-plans`의 최신 완료 실행 범위와 같은 필터(`stage1_status=selected`, `qwen_relevance=relevant,uncertain`, `tracking_status=미선택`)로, `pre_spec_deep_review_ready`는 deep_review가 `GET /api/pre-specs?auto_preparation_status=deep_review_ready_for_click&sw_only=false`와 같은 집합으로, `bid_final_decision_pending`은 deep_review가 `GET /api/bid-delta/decision-queue?status=pending`의 `total`과 같은 값으로 센다. `tracking_action_required`는 lifecycle이 `GET /api/opportunities`의 `조치 필요` 구역과 같은 첫 일치 규칙으로 직접 센다.
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

### 사전규격 개요 검토

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/pre-specs/{notice_id}/overview-reviews` | integer `notice_id` | 200 `bidops.prespec-overview-reviews.v1` | 404 `not_found`; 500 `processing_failed` |
| `GET /api/pre-specs/{notice_id}/overview-reviews/v2` | integer `notice_id` | 200 `bidops.prespec-overview-reviews.v2` | 404 `not_found`; 409 `validation_failed`; 500 `processing_failed` |

응답은 정확히 `schema_version`, `notice_id`, `reviews[]`를 갖는다. 각 review는
`id`, `notice_id`, `status`, nullable `result`, nullable `completed_at`, nullable
`current_snapshot`, `attempts[]`를 반환한다. 상태는
`awaiting_document|awaiting_structure|preparing|awaiting_model|queued|running|needs_human_review|completed|failed|cancelled`,
결과는 `추진 검토|조건부 추진 검토|보류|검토 종료`다. `current_snapshot`은
`id`, `document_version_id`, `structure_id`, `source_sha256`, `payload_sha256`,
`cut_status`, nullable `strategy`, nullable `start_locator`, nullable `end_locator`,
`created_at`을 갖고, `cut_status`는 `pending|ready|unknown|failed`다. locator는
`block_key`, `page`, 결정적 `ordinal`을 갖는 opaque object이며 ready cut의 end는
제외 경계다. attempt 요약은 `id`, `snapshot_id`, `sequence`, `status`, `reference_only`,
`deployable`, `created_at`, nullable `started_at`, nullable `completed_at`만 반환한다.
응답에는 원문 block/content, object key, 내부 path, prompt, model response가 절대
포함되지 않는다. `completed`가 아니면 result와 completed_at은 모두 null이다.

DB 소비자는 `prespec_overview_review`의 notice별 현재 상태와 current snapshot 포인터,
`prespec_overview_snapshot`의 document version·structure·source/payload hash·절단
전략/locator를 사용한다. snapshot과 attempt의 입력 계보는 append-only이며,
runtime worker는 attempt lifecycle 열만 column-scoped UPDATE할 수 있다. DB의 단일 trigger는
허용 상태 간선을 검증하고, service transaction은 audit event·attempt·현재 review 갱신을
함께 flush한다. DB trigger가 event insert와 상태 변경을 교차 table로 결합하지 않는다.
같은 review·document version·structure·hash 입력은 idempotent하게 한 snapshot으로
유지한다. clean 구조가 없으면 각각 `awaiting_document` 또는 `awaiting_structure`를
유지하고, 구조 hash/원문 hash 재검증 실패·warning·입력 제한·TOC 불일치·종료 경계
불명확은 `unknown`/`needs_human_review`로 남기며 모델 호출을 하지 않는다. 승인된
binding 없는 phase 1은 ready snapshot 뒤 `awaiting_model`이고 attempt를 만들지 않는다;
reference-only attempt는 `deployable=false`여야 한다.

#### Phase 2 구현 계약 — `bidops.prespec-overview-reviews.v2`

[ADR-0035](tracking/decisions/0035-prespec-overview-attempt-result-lifecycle.md)는 phase 2의
목표 계약을 채택했고, phase 2는 현재 v1 wire의 scalar 의미를 바꾸지 않고
`GET /api/pre-specs/{notice_id}/overview-reviews/v2`에 새 versioned safe projection을
구현했다. attempt의 snapshot·sequence·입력 hash·binding은 불변으로 유지하고 상태·허용
시각·검증 result 참조만 column-scoped UPDATE한다. 모든 전이는
지원하는 service 경로에서 `prespec_overview_attempt_event`에 append-only로 기록하고, 검증 결과는
`prespec_overview_result`에 attempt당 최대 하나만 immutable insert한다.

결과 payload는 `schema_version=bidops.prespec-overview-result.v1`, 닫힌
`recommendation`, 비어 있지 않은 `summary`, `conditions[]`, nullable RFC 3339
`verification_due_at`, 구조화한 `unknowns[]`, 현재 snapshot locator를 가진 `evidence[]`,
`input_limitations[]`를 strict하게 검증한다. `조건부 추진 검토`에는 non-empty conditions와
non-null verification due가 모두 필요하고, evidence locator/source hash는 현재 ready
snapshot의 범위와 일치해야 한다. 안전한 v2 projection은 검증 결과·result digest·binding
digest만 노출하고 endpoint, prompt, raw response, object path와 내부 오류 detail을
제외한다. 기존 v1의 nullable scalar `result`는 그대로 유지한다.

개요 검토가 쓰는 policy는 저장소의 `app/deep_review/policies/prespec-overview-policy-v1.json`이다. schema는 `bidops.prespec-overview-policy.v1`, `model_name`은 `qwen3.8-27B`, `prompt_version`은 `prespec-overview-v1`, `model_endpoint_ref`는 `vllm-openai-compatible`이며 단일 stage를 갖는다. binding digest는 이 파일의 canonical JSON SHA-256이고 **파일이 정본이다** — 문서에 값을 복사해 두지 않는다. 파일이 없는 배포에는 승인된 개요 binding이 없다는 뜻이고 review는 `awaiting_model`에 남는다. 파일이 있는데 계약을 어기면 추정 보정 없이 멈춘다.

개요 검토는 `app/core/model_client.py`를 `overview` 용도로 묶어 부른다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)). 그 용도의 허용 host가 비었거나 선언 revision이 64자 hex가 아니면 호출 전에 fail closed하며, 그 상태의 리뷰는 `awaiting_model`에 머물고 attempt를 만들지 않는다. hosted fallback은 없다.

실행된 attempt는 품질 표식을 반드시 갖는다. `reference_only`인 attempt는 `mock_reference`, 그 밖은 `unmeasured_reference`이며 둘 다 `deployable=false`로 남는다. `reference_only`인 attempt는 완료할 수 없으므로(`ck_prespec_overview_attempt_completed_binding`) **`status=completed`인 개요 attempt의 표식은 언제나 `unmeasured_reference`다.** `deployable=false`인 `completed`의 뜻은 "완료 불가"가 아니라 **"운영 완료로 집계하지 않음"**이다. 참조 실행 결과를 사업 판단·품질 근거·활성화 근거로 쓰지 않는다.

검증 실패(schema 위반, snapshot 밖 evidence)는 재호출 없이 바로 `failed`다. 재시도는 transport 계열 실패에만 1+2회 적용한다. worker가 잡는 lease 길이는 모듈 상수 1,200초이며 환경변수로 열지 않는다. **만료 lease 회수는 개요 슬롯 안에서 돈다** — 합성 worker가 C-2 큐를 먼저 보므로 그쪽이 계속 붐비면 회수가 늦어진다. 감사 action `prespec_overview.attempt_run`(actor_kind `system`, aggregate_type `prespec_overview_attempt`)의 `safe_metadata`는 `notice_id`, `review_id`, `sequence`, `status`, `reason_code`, `quality_status`, `response_sha256`이다. 암호화된 원응답과 attempt 사이에 직접 FK는 없고 `response_sha256`으로 대조한다.

v2 응답은 정확히 `schema_version`, `notice_id`, `reviews[]`를 가지며 review에는
`id`, `notice_id`, `status`, nullable `result`, nullable `result_digest`, nullable
`binding_digest`, `validation_status=passed|failed|pending`, nullable `completed_at`,
`current_snapshot`, `attempts[]`를 둔다. attempt에는 기존 안전 요약에
`validation_status`, nullable `result_digest`, nullable `binding_digest`, 필수
`quality_status=mock_reference|unmeasured_reference`를 추가한다. review에는 nullable
`quality_status`가 있으며 `null`은 표식 없음이다([ADR-0050](tracking/decisions/0050-unified-openai-compatible-model-client.md)).
result payload 자체에는 provider/model/prompt/storage metadata가 없고, `result_digest`는
canonical JSON payload의 lowercase SHA-256이다. `result`가 있는 경우에는
`schema_version`, `recommendation`, `summary`, `conditions`, `verification_due_at`,
`unknowns`, `evidence`, `input_limitations`만 반환한다.

bundle confirm은 악성코드 clean 결과, document version, structure snapshot과 hash를 고정한다. 심층 attempt와 report materializer는 live 첨부를 다시 읽지 않고 이 snapshot만 사용한다. validation 실패는 report에서 드러나며 자동 통과로 바뀌지 않는다.

Lean wire model의 정확한 shape는 다음과 같다. 별도 `optional` 표기가 없으므로 모든 field는 wire에 필수이며 `?` field만 필수 nullable이다. UUID·date·datetime은 JSON 문자열이고 `source_sha256`는 64자 lowercase SHA-256이다.

- `DocumentVersionView`: `id`, `bundle_id`, `version>=1`, `role`, `effective_date?`, `replaces_document_version_id?`, `is_current`, `safety_status`, `structure_status`, `original_filename`. `role=공고|정정|제안요청서|과업지시서|내역서|제출서식|부록|기타`, `safety_status=quarantined|scanning|safe|blocked`, `structure_status=pending|processing|ready|failed|needs_review`다.
- `BundleIssue`: `issue_id`, `code`, `severity=차단|중대|보통|낮음`, `blocking`, `document_version_id?`, `message`, `locator_type=none|page|paragraph|table_cell|bbox`, nullable opaque object `locator?`다. `BundleView`: `id`, `notice_id`, `revision>=1`, `version>=1`, `status=draft|processing|needs_review|ready|quarantined|failed|superseded`, `documents: DocumentVersionView[]`, `issues: BundleIssue[]`, `confirmed_by?`, `confirmed_at?`, `created_at`. `BundleListResponse`는 pagination field 없는 정확히 `{items: BundleView[]}`다. 새 issue code `unsupported_attachment_excluded`(severity 보통, `blocking=false`)는 허용 형식 밖 첨부가 묶음에서 제외됐음을 알린다. 그 첨부의 `extract_status`는 `provider_unsupported_excluded`이며, 이름이 `provider_`로 시작하지만 **비차단**이다 — issue 계산이 다른 `provider_*` 규칙보다 먼저 이 값을 검사한다.
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

`collected-notices.json`의 `bidops.collected.v2`는 T-11에서 유지한다. 입찰공고 원문에 이미 있는
`orderPlanUntyNo`를 기존 `lifecycle` 안의 선택적 `order_plan_no`로 투영할 뿐이며, 기존 필드의
의미·필수성·레코드 종류를 바꾸지 않는다. 따라서 과거 v2 파일은 그대로 유효하고, 새 v2 파일만
이 선택 필드를 가질 수 있다. 발주계획 전체 원본은 공고 계약의 조용한 확장이 아니라 아래의
독립적인 `collected-order-plans.json` / `bidops.collected-order-plans.v1`로 분리한다.

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
`para_page_map`, `hwpx_verify`를 추가한다. 파일 descriptor는 `{file,byte_count,sha256}`이고
`native/<request_uuid>.hwpx`, `.page-text.json`, `.para-page-map.json`으로만 해소한다.
원본 HWPX는 `hwpx`·`hwpx_verify`가 `null`이고 원문을 재사용한다. HWP 변환본은
`hwpx_verify={identical:true,diff_count:0,pages:{before:N,after:N,identical:true}}`를
반드시 갖는다. 원문·PDF·변환 HWPX를 trusted-side scanner로 검사한다. native
page-text는 `bidops.rhwp-page-text.v1`의 `page_count`, 물리 페이지의
`number,display_page,section,text,text_sha256`를 보존한다. 모든 sidecar를 완료한 뒤
성공 JSON을 publish하며 소비자는 고정 경로·regular file·상한·hash·페이지 수와
schema를 검사한다. 구조 블록을 합쳐 PDF page text를 대신하지 않는다.

## DB와 migration 계약

- 코드의 Alembic head는 `0023_rhwp_snapshot`이다. 운영 적용은 별도 승인 단계다. 그 이전 T-23 phase 2
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
운영 실행·정책 활성화 승인이 아니다. 현재 고정 digest는 policy
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
| `config/order-plan-screening-policy.v1.json` / `bidops.order-plan-screening-policy.v1` | `phase0-contracts` → `phase1-screening-pipeline` | `schema_version`, `producer`, `consumer`, `policy_version`, `policy_status`, `decision_scope`, `created_at`, `stage1`, `stage2`, `audit_sample`, `execution`, `feedback`, `quality_gate`, `bindings`, `activation`; stage2에 model·generation config·prompt·profile SHA-256; `policy_status=draft|activation_candidate|active|retired` | policy payload·binding은 immutable. 활성화는 별도 사람 승인과 audit 없이는 불가하며 현재 `draft`, `activation=blocked`다. |
| `config/order-plan-screening-phase0-binding.v1.json` / `bidops.order-plan-screening-phase0-binding.v1` | `phase0-contracts` → `phase1-screening-pipeline` | 위 provenance, `binding_version`, `status`, `created_at`, `policy`, `selection_decision`, `source_input`(raw-page manifest SHA-256 포함), `selection_evidence_population`, `stage1_binding`, `stage2_binding`, `selection_evidence`, `review_inputs`, `gold`, `external_transport`, `compatibility`, `activation`; current v1 `status=blocked` | 생성 후 immutable. 이 snapshot의 partial gold/current refs와 blocked transport를 바꾸려면 새 binding version을 만든다. 역사적 실험 파일은 read-only이며 binding을 맞추기 위해 소급 수정하지 않는다. |
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

새 endpoint는 기존 `/api/screening`을 확장하지 않고 아래 경로를 사용한다. 현재 Phase 0
binding이 blocked이므로 실행·활성화 endpoint는 성공을 반환하지 않는다.

| method / path | 요청 | 성공 응답의 필수 field | 안정 오류 |
|---|---|---|---|
| `GET /api/order-plans` | `source_run_id?`, `stage1_status?`, `stage2_status?`, `qwen_relevance?`, `human_relevance?`, `q?`, `limit=1..500`, `offset>=0` | `items`, `total`, `limit`, `offset`; item은 `order_plan_pk`, `order_plan_unty_no`, nullable 공개 `source_url`, title, agency, nullable `budget_amount`·`planned_order_year`·`planned_order_month`, source run/observation, BM25 stage status/rank/score/`nearest_capability`, Qwen stage status/score/label/reason, latest human feedback summary | `invalid_request(422)` |
| `GET /api/order-plans/{order_plan_pk}` | path PK | 누적 plan metadata(`budget_amount`, planned year/month, nullable 공개 `source_url` 포함)와 `screening_history`, latest result/feedback; 내부 source path·object key는 반환하지 않음 | `not_found(404)` |
| `GET /api/order-plans/{order_plan_pk}/screening-history` | path PK | `order_plan_pk`, `items[]`; item은 execution/binding digest, status, BM25 `nearest_capability`, result `batch_id`·`attempt_no`, stage result, feedback revision count | `not_found(404)` |
| `POST /api/order-plan-screening/executions` | actor header 필수, `execution-create-request.v1`의 `{schema_version, producer, consumer, request_id, source_run_id, policy_version}` | first request `202`: `execution-create-response.v1`의 provenance와 `execution_id`, `request_id`, `source_run_id`, `policy_version`, `status=대기`, binding digest, `execution_allowed`; 같은 request ID와 같은 payload는 원래 `202` body를 replay | `actor_name_required`, `invalid_request`, `source_run_incomplete`, `policy_not_active`, `binding_mismatch`, `idempotency_conflict`, `active_execution_exists` (`409`), transport unavailable (`503`) |
| `GET /api/order-plan-screening/executions` | `source_run_id?`, `status?`, pagination | `items`, `total`, `limit`, `offset`; 내부 object key·prompt·profile 본문 없음 | `invalid_request(422)` |
| `GET /api/order-plan-screening/executions/{execution_id}` | path ID | execution status, counts, binding digests, timestamps, safe artifact summaries, `attempts[]`의 batch/attempt·model/prompt/profile binding, status/failure, nullable token·duration·시각; `response_object_ref`·`plan_ids_jsonb`·artifact 본문/경로는 반환하지 않음 | `not_found(404)` |
| `POST /api/order-plan-screening/executions/{execution_id}/stop` | actor header, `execution-stop-request.v1`의 `{schema_version, producer, consumer, request_id, reason}` | `202`: `execution-stop-response.v1`의 provenance와 execution ID, `status=중지 요청`, request ID | terminal 또는 중복 다른 request (`409`), `actor_name_required` |
| `GET /api/order-plan-screening/executions/{execution_id}/artifacts/{kind}` | `kind=screening_input|ranking|decisions|failures|telemetry|screening_result` | artifact schema, producer/consumer, digest, safe metadata와 검증 상태; 본문은 승인된 다운로드 경계에서만 | `artifact_kind_invalid`, `artifact_not_ready`, `not_found` |
| `GET /api/order-plans/{order_plan_pk}/screening-feedback` | path PK, `execution_id?` | `items[]`; revision, relevance, nullable priority/memo, claimed actor, created_at | `not_found(404)` |
| `POST /api/order-plans/{order_plan_pk}/screening-feedback` | actor header, `feedback-create-request.v1`의 `{schema_version, producer, consumer, request_id, execution_id, relevance, priority, memo, expected_revision?}` | `201`: `feedback-create-response.v1`의 provenance와 feedback ID, plan/execution, revision, labels, actor 표식, created_at | `feedback_conflict`, `idempotency_conflict`, `not_found`, `actor_name_required` |
| `GET /api/order-plan-screening/policies/{policy_version}` | path version | policy version/status, policy·binding digest, `activation_allowed`, blockers; prompt·profile 본문 없음 | `not_found(404)` |
| `POST /api/order-plan-screening/policies/candidate` | actor header, `policy-candidate-request.v1`의 `{schema_version, producer, consumer, request_id, policy_version, base_policy_sha256, candidate_sha256, reason}` | `201`: `policy-candidate-response.v1`의 provenance와 `activation_candidate` version/status/digest | `invalid_request`, `idempotency_conflict`, `immutable_conflict` |
| `POST /api/order-plan-screening/policies/{policy_version}/activate` | actor header, `policy-activate-request.v1`의 `{schema_version, producer, consumer, request_id, policy_sha256, quality_gate_artifact_sha256, explicit_confirmation:true}` | 승인 후에만 `200`: `policy-activate-response.v1`의 provenance와 active status·audit ID | 현재는 `activation_blocked(409)`, digest mismatch (`409`) |

**미구현 — 발주계획 추적 결정 (요청안, 2026-09-04).** ADR-0046 결정 4가 추적 결정을 발주계획
화면의 결정 1로 채택했으나 그 결정을 읽을·쓸 경로가 위 표에 없다. 목록·상세 응답의 `tracking`
field와 `GET`/`POST /api/order-plans/{order_plan_pk}/tracking-decisions`를 백엔드 파트에
요청했다. wire shape·오류·테스트 matrix는
[`design/order-plan-tracking-contract-request.md`](design/order-plan-tracking-contract-request.md)에 있으며
**제안이고 채택이 아니다.** 그 문서가 채택될 때까지 이 표가 발주계획 REST 계약의 전부다.
화면의 Playwright fixture가 요청안의 모양을 mock하지만 그것은 구현 완료의 근거가 아니다.

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
| `order-plan-list-response.v3` | `order-plan-review-api` → `order-plan-review-client` | `GET /api/order-plans` | provenance, `items`, `total`, `limit`, `offset`; item의 nullable 공개 `source_url`, 예산·계획 시기·BM25 `nearest_capability`와 stage status/label/score | response projection only; 내부 경로·본문 금지 |
| `order-plan-detail-response.v3` | API → client | `GET /api/order-plans/{id}` | provenance, plan metadata의 nullable 공개 `source_url`, `budget_amount`·계획 시기, `screening_history`; history의 `nearest_capability`·`batch_id`·`attempt_no` | read-only projection; 기존 notice response와 혼용 금지 |
| `execution-create-request.v1` / `execution-create-response.v1` | `human-review-client` → `screening-api` → client | execution POST | request provenance, `request_id`, source/policy; response provenance, `execution_id`, `status=대기` | exact replay만 허용; request payload·binding snapshot immutable |
| `execution-list-response.v1` / `execution-detail-response.v1` | `screening-api` → client | execution GET | provenance, `items`/execution, counts, timestamps, safe artifact summaries; detail `attempts[]`에는 binding(model/prompt/profile 및 digest), status/failure, nullable token·duration·시각만 projection; status `대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨` | v1 status meaning fixed; `response_object_ref`·`plan_ids_jsonb`·prompt/profile/model response body 없음 |
| `execution-stop-request.v1` / `execution-stop-response.v1` | `human-review-client` → `screening-api` → client | stop POST | request provenance, `request_id`, `reason`; response provenance, execution ID, `status=중지 요청` | terminal transition and idempotency rules fixed |
| `artifact-summary-response.v1` | `screening-api` → client | artifact GET | provenance, `kind`, `schema_version`, `producer`, `consumer`, digest, validation status | safe metadata only; bytes download is separately authorized |
| `feedback-list-response.v1` / `feedback-create-request.v1` / `feedback-create-response.v1` | `review-api` ↔ client / `postgres-history` | feedback GET/POST | request provenance plus `request_id`, execution, relevance `relevant|not_relevant|uncertain`, priority `high|medium|low|null`; response feedback ID/revision | append-only revision; no grade/readiness/tracking/go-no-go mutation |
| `policy-inspect-response.v1` / `policy-candidate-request.v1` / `policy-candidate-response.v1` / `policy-activate-request.v1` / `policy-activate-response.v1` | `policy-api` ↔ client | policy GET/POST | provenance, policy/binding digest, `activation_allowed`; policy status `draft|activation_candidate|active|retired`, activation status `blocked|activation_candidate|active|retired` | current candidate/activate calls fail closed; activation requires explicit audit approval |

### C-2 DB·migration 경계 (Phase 2 구현 입력)

현재 Alembic head는 `0017_order_plan_screening_heartbeat`이며, C-2 migration은
`0016_order_plan_screening`에서 `0017_order_plan_screening_heartbeat`로 이어진다. Phase 0에서는
DB를 변경하지 않는다. 기존 공고용 `screening_execution`, `screening_attempt`, `screening_policy`를
C-2 의미로 재사용하지 않는다.

| table | 필수 핵심 column / 상태 | 불변성·제약 |
|---|---|---|
| `order_plan_screening_policy` | `id`, `policy_version UNIQUE`, `schema_version`, `producer`, `consumer`, `policy_status=draft|activation_candidate|active|retired`, policy/binding SHA-256, safe activation metadata, created/activated timestamps | payload·digest immutable. status는 `draft→activation_candidate→active→retired` 단방향만 audit와 함께 허용, active partial unique 1개 |
| `order_plan_screening_execution` | `execution_id UUID PK`, `request_id UNIQUE`, `schema_version`, `producer`, `consumer`, source run/artifact/population digest·count, policy version/SHA, binding SHA, `status=대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`, actor 표식, counts, timestamps | source/policy binding snapshot immutable. status transition trigger, terminal timestamp CHECK, active execution partial unique 1개 |
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

### 사전규격 개요 입력 문서 선택 (2026-09-07)

현재 문서 중 정규화된 파일명에 `제안요청서`가 포함된 후보 하나를 선택한다. role·업로드 시각으로 후보를 대체하거나 복수 후보의 우선순위를 정하지 않는다. 후보 없음·복수 후보는 기존 `needs_human_review`와 `current_snapshot=null`로 반환한다. 취득 문서가 전혀 없으면 `awaiting_document`를 유지한다. API schema·DB 상태값은 추가하지 않으며 기존 불변 snapshot·attempt·결과 이력은 보존한다. 프론트엔드의 현재 상태 문구는 `사람 검토 필요`다.

## PDF 페이지 기반 사전규격 개요 (2026-09-07)

권고 없는 설명형 출력 `bidops.prespec-overview-page-review.v3`는 기존
`bidops.prespec-overview-result.v1`과 별개의 계약이다. 프롬프트 v4와 출력 schema v3는
서로 다른 버전 축이다. 기존 `/overview-reviews` 및 `/overview-reviews/v2`는 변경하지 않는다.

- `GET /api/pre-specs/{notice_id}/overview-pages` → `bidops.prespec-overview-pages.v1`.
  해당 공고의 최근 적재 기록 최대 20건을 생성시각 내림차순으로 반환한다. 기록 없음은
  `reviews: []`, 존재하지 않는 사전규격은 404다. 각 기록은 원출력 `payload`, 검증/품질
  상태, 원문 문서 버전·SHA-256, PDF SHA-256·페이지 수·검토한 페이지를 갖는다.
- `payload`는 `business_overview`, `main_tasks`, `budget_and_period`,
  `important_conditions`의 `{text,evidence_pages}` 배열과 `reviewer_analysis`,
  `unknowns`, `input_limitations` 문자열 배열이다. `recommendation`은 없다.
- `GET /api/pre-specs/{notice_id}/overview-pages/{review_id}/pdf`는 결속된 불변 객체 버전의
  스캔된 PDF만 반환한다. 다른 공고의 review ID는 404, 스캔·버전·크기·해시 불일치는
  실패한다. 내부 경로·객체 키·자격증명을 반환하지 않는다. `#page=N`은 PDF 뷰어 순번이다.
- `prespec_page_overview`는 별도의 append-only 테이블이다(Alembic 0019).
  원출력 JSONB, 원문/PDF/프롬프트/정책/모델 해시, 불변 입력 객체·PDF 객체 위치를 보존한다.
  같은 `(run_id, notice_id)`의 동일 재적재는 기존 ID를 반환하고 내용 변경은 거부한다.
  기존 권고 결과 테이블의 제약을 완화하거나 리뷰·추적 행을 덮어쓰지 않는다.
- `validation_status`는 원실행 실패와 새 근거 검사의 실패를 모두 보존한다.
  `evidence_check_status`는 새 검사만의 결과다. 원실행 실패가 새 검사 통과로 지워지지 않는다.
  `quality_status`는 참조 표식만 허용하며 운영 완료나 측정 통과를 뜻하지 않는다.
- `pdf-page-evidence.v3`는 문장 끝의 정확한 `(PDF N페이지 …)` 표기를 언제나 metadata로
  분리한다. `evidence_pages`와 표기 페이지는 모두 검토한 페이지 안에 있어야 하며 벗어나면
  `pdf_locator_mismatch`로 실패한다. 둘이 다른 것은 실패가 아니라 경고
  `pdf_inline_locator_normalized`이고, 숫자·영문·사업금액 의미 검사는 두 집합의 합집합을 본다.
  원출력은 수정하지 않는다. 화면의 중복 페이지 문구 제거는 표시 계층에서만 한다.

서버측 `import-page-overview` CLI는 고정 실행 파일 1건을 적재하는 경로다. frozen policy와
prompt hash, 문서 소속·원문 hash, 실제 PDF 페이지 텍스트 포함 관계를 검증하고 스캔 뒤
저장한다. 이 명령은 모델을 호출하거나 기존 worker 정책을 활성화하지 않는다.

### v4 PDF 준비 snapshot·입력 manifest (2026-09-08)

v4 준비는 기존 `DocumentStructure`·legacy 개요를 갱신하지 않는다. 현재 head 뒤의
`0021_prespec_v4_pdf_contract`가 `prespec_v4_pdf_snapshot`과
`prespec_v4_target`을 추가했고, `0022_prespec_v4_attempt`가 그 manifest를 소비하는
fenced attempt를 추가한다. target은 검증된 PDF에 대해 준비가 끝난 입력 manifest
(또는 사람 확인 경계)만 표현하며, attempt는 그 target·정책·모델 binding 하나를
실행한다. 기존 legacy 권고 attempt/result는 같은 문서의 v4 결과로 대체하거나
덮어쓰지 않는다.

- `prespec_v4_pdf_snapshot`은 current·safe `DocumentVersion`의 정확한 원문
  `ContentObjectLocation`, PDF `ContentObjectLocation`, full page-text JSON
  `ContentObjectLocation`, PDF metadata, page count·page text hash, ClamAV clean
  verdict, worker renderer/font digest와 정규화된 processor options를 묶는다.
  기존 Canvas/PDF full page text object는 `bidops.prespec-v4-page-text.v1` JSON의 모든 물리 페이지
  `{number,text,text_sha256}`를 보존하며 PDF metadata의 페이지별 hash와 일치해야
  한다. 생성 PDF는 기존 `source` namespace에 저장하고 page-text·선택 manifest는
  `structure` namespace에 둔다. 원본 PDF는 동일 source object/location과 bytes를
  그대로 재사용한다.
- 준비 API는 source hash, renderer/font/config digest로 기존 snapshot을 변환 전에
  조회한다. 같은 source version·worker provenance·options이면 worker를 다시
  호출하지 않고 같은 PDF/page-text object version을 반환한다. cache hit도 source,
  PDF, page-text object를 저장된 namespace·object key·version·etag·size·SHA-256으로
  bounded read하고 최신 `ContentScan.status=clean`을 확인한다. 기존 Canvas renderer에는
  `runtime_sha256`와 실제 Chromium binary의 `chromium_sha256`, font에는 실제
  설치 파일 바이트를 정렬해 만든 `font_manifest_sha256`가 있어야 한다. 배포가
  선언한 `worker_image_digest`가 있을 때만 선택적으로 함께 결속하며, 선언이 없을
  때 asset fingerprint를 이미지 digest로 가장하지 않고 `null`로 둔다. generated
  PDF에서는 이 값이 caller dict가 아니라 실제 document-worker가 PDF metadata에
  넣은 vendored runtime·Canvas adapter·processor/CSS·Chromium/font fingerprint와
  일치해야 한다. 원본 PDF는 `rerendered=false`와 실제 bounded Poppler/stdlib
  text-extractor provenance를 기록하고 `font_provenance=null`로 둔다. config의 `options`는
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
- `0023`은 `prespec_v4_attempt.validation_warnings` nullable JSONB도 추가한다.
  worker는 snapshot INSERT와 attempt의 경고 열 UPDATE를 허용받지만 snapshot
  UPDATE/DELETE와 terminal attempt 수정은 거부된다. 경고의 실제 생산 연결은
  이후 WP-3에서 한다. converter의 허용된 안전 오류는
  `pdf_preparation_failed:<code>`와 `AuditEvent.safe_metadata.converter_code`에 남기며
  미등록 예외는 일반 코드로 닫고 원문·경로·stderr는 넣지 않는다.
- `bidops.prespec-v4-input-manifest.v1`은 선택된 장·절의 정확한 page substring,
  시작/끝 locator, 선택 page hash, 원본 full-page hash, 입력 제한을 담는다. 목차
  잔여와 다음 장 제목은 substring에 포함하지 않으며, 필요한 첫 `과업내용`
  subsection만 다음 장에서 이어 붙일 수 있다. 범위 경계가 없거나 문서가
  ambiguous하면 `needs_human_review`로 남기며 전체 문서 fallback·고정 page 절단·
  표 배치 추정은 하지 않는다.
- target identity는 SQL `NULL` unique에 의존하지 않고 snapshot·observation·manifest
  상태의 canonical SHA-256으로 저장한다. explicit sample도 같은 입력을 중복
  삽입할 수 없다. observed 대상은 `NoticeObservation`의 명시된 snapshot/source
  hash와 attachment change 근거가 있을 때만 만들며, 같은 URL의 bytes 교체나
  `DocumentVersion.created_at`을 신규 관측으로 추정하지 않는다.
- `prespec_v4_attempt`는 notice별 sequence, target/source/PDF/manifest hash,
  `bidops.prespec-overview-policy.v4` digest, `prespec-overview-v4`, model name/revision,
  generation, lease와 result/raw-response digest를 보존한다. 정상 target은
  `queued|running|completed|failed|cancelled`를 거치며 retry는 새 attempt다. PDF
  준비 실패는 target 없는 `failed` row로 현재 상태에 보인다. worker는 v4 attempt의
  lifecycle 열만 갱신하고, terminal row와 target/result 범위는 DB trigger·FK로
  보호한다. `mock_reference`도 통제 결과로 저장할 수 있지만 운영 품질·자동 심층
  시작 근거로 승격되지 않는다.
- v4 정본 policy는 기존 `experiments/prespec-overview-pdf-reference/policy.json`의
  `system_prompt`, `stages` 지시문, `prompt_output_contract`의 reader format·두
  synthetic few-shot, output schema, generation, chunking을 그대로 보존한다. 배포
  식별자만 policy v4·`qwen3.8-27B`·`prespec-overview-v4`로 결속한다. 모델 입력은
  `{schema_version, blocks: [{pdf_page, text}], input_limitations}`이며 manifest의
  source/hash/storage 필드는 전송하지 않는다.
- `GET /api/pre-specs/{notice_id}/overview-pages`는 기존 `reviews` 이력과 별도로
  서버가 검증한 `current`를 반환한다. `current`는 `attempt_id`,
  `status=queued|running|completed|failed|needs_human_review|stale|cancelled`,
  `result_id`, `reason_code`, `prompt_version`, `created_at`를 갖는다. 적용 기록이
  없으면 `current=null`; 실패·진행이면 과거 성공을 current로 가장하지 않는다.
  GET은 저장·모델 호출·attempt 생성 없이 문서 current/safe, snapshot/result hash,
  policy·overview 설정의 model revision, page-v3 validator와 evidence-check
  `passed` 결속을 다시 확인한다. `DocumentVersion.needs_human_review=true`인
  입력은 stale로 투영한다. 여러 공고 조회자는 같은 판정의 batch projection을
  사용하며 공고마다 current를 재조회하지 않는다.

실제 운영 DB/MinIO에 이 migration이나 snapshot/attempt row를 쓰지 않았고 모델
호출·scheduler 활성화도 하지 않았다. SQLite 격리 roundtrip과 임시 PostgreSQL
upgrade/constraint 검사는 기존 object-store/scratch contract와 함께 구현 검증에만
사용한다.

### v4 cohort 활성·준비 ops 계약 (2026-09-09)

v4는 기본 `off`다. 별도 registry/table을 만들지 않고 `audit_event`의
`action=prespec_v4.activation`, `aggregate_type=prespec_v4_activation` append-only
행으로 활성·중단 이력을 남긴다. 가장 최근 행이 `active`가 아니거나 schema, policy
digest, reference-only model binding이 검증되지 않으면 dispatch와 enqueue는
`v4_disabled`로 fail closed한다. 활성 metadata에는 `explicit_sample` 또는
`new_reference`, artifact SHA-256, policy/model/prompt/binding digest, 활성 시각,
표본의 notice/document/source SHA-256·크기, 자동 대상 조건과
`quality_status=unmeasured_reference`를 저장한다. 고정 표본은 수동 개요 검증용이며
등급을 만들어 자동 심층 대상처럼 취급하지 않는다.

`prespec-v4` CLI의 `--dry-run`은 읽기만 하고 안전한 id/status/reason만 출력한다.
`--prepare`는 활성 cohort에서 current/safe·단일 제안요청서 문서·검증된 source
object를 확인한 별도 준비 경계에서 scratch v2 PDF를 호출하고 snapshot/page-text/
substring manifest를 동결한다. attachment download의 120초 lease를 재사용하지
않는다. `--enqueue`는 같은 트랜잭션에서 기존 `WorkJob` aggregate slot과 새 v4
attempt를 만들고, `--retry`는 terminal failed/cancelled target에 새 sequence
attempt를 append한다. 기존 attempt/target/result를 수정하거나 legacy overview로
우회하지 않는다. PDF·관측·범위 실패는 target 없는 `failed` current 또는
`needs_human_review`로 남기며 model call을 만들지 않는다.

`explicit_sample`은 activation 표본의 notice key/document UUID/source hash/size가
현재 safe document와 정확히 맞아야 한다. `new_reference`는 활성 시각 뒤의
`NoticeObservation`에 첨부 name/url/provider key/size와 실제 DocumentVersion source
hash/size가 함께 결속되어야 한다. 이전 관측이 없으면 최초 관측, 이전 snapshot의
첨부 metadata fingerprint가 달라지면 attachment change로 인정한다. 동일 hash의
재수집·재변환, 관측이 없는 문서, `DocumentVersion.created_at`만으로 만든 신규성은
제외한다. 자동 대상은 `source_type=pre_spec`, `SW사업대상=Y`, effective grade가
`우선 검토`, `auto-preparation` confirmed ready bundle을 모두 요구한다.

준비/예약은 app role이 source/structure object와 snapshot/target/WorkJob/attempt를
append하고, analysis worker는 source를 읽지 않고 frozen manifest만 소비하며 attempt
lifecycle 열만 갱신한다. worker의 model read는 v4 current binding과 기존 page-v3
validator를 다시 확인한다. 운영 DB/MinIO 쓰기·scheduler·실제 모델 호출은 명시적인
활성·배포 절차가 끝나기 전 수행하지 않는다.

### Luna 명시 참조 개요 실행 (2026-09-09)

사용자 명시 참조 실행만 `bidops.prespec-v4-luna-reference.v1` generation record의
고정 input/output 파일을 읽는다. record의 `actualmodel=gpt-5.6-luna`,
`effort=max`, `opaqueweightsrevision=null`, policy 파일 hash, prompt hash와
sample input/output hash를 확인한 뒤 generation record 전체의 SHA-256을 세 sample의
공통 v4 `model_digest`로 사용한다. sample별 입력·출력·prompt manifest SHA는 audit
metadata에 별도로 보존한다. 이는 weight revision이나 Qwen revision이 아니며, binding은
`provider=luna-reference`, `reference_only=true`, `deployable=false`,
`quality_status=unmeasured_reference`로만 저장한다.

`--enqueue-reference`는 app role에서 target과 response provenance를 결속한 queued
attempt와 audit 행을 만든다. `--run-reference`는 worker role에서 그 queued attempt와
동일 manifest audit를 확인한 뒤 기존 `PrespecV4OverviewRunner`의 raw 암호화 저장,
page-v3 validator, result/current projection을 실행한다. 두 명령은 분리되며 worker는
attempt/WorkJob lifecycle 열만 갱신한다. 이 경로는 automatic/new-reference cohort,
회사 핏 자동 gate, 심층 검토를 우회하지 않고 수동 참조 current 결과만 제공한다.


### 사전규격 회사 핏 계약 (`bidops.prespec-company-fit.v1`)

`GET /api/pre-specs/{notice_id}/company-fit`은 해당 공고의 최근 attempt 최대 20개(최신 순), 자동 판정 활성 여부, 서버가 계산한 자동 준비 사유와 실제 최신 `deep_review_id`를 반환한다. 공고 없음/다른 source type은 404, 잘못된 id는 422, 내부 오류는 안전한 `processing_failed` 500이다. GET은 실행을 만들거나 모델을 호출하지 않는다.

- 실행 상태: `queued|running|completed|failed|needs_human_review`. 결과가 없거나 검증에 실패한 실행의 `result`는 null이다.
- 결과: `bidops.prespec-company-fit-result.v1`, `decision=matched|mismatch|unknown`, `summary`, `reasons[]`, `verification_items[]`. 각 사유는 `kind=scope_match|scope_mismatch|information_gap`, 모델 의견 `explanation`, `notice_refs[]`, `company_refs[]`를 갖는다. 입력에 없는 ref, 중복 ref, 확인되지 않은 회사 근거로 만든 일치/불일치, 인용 근거에 없는 숫자는 검증 실패다. 자동 보정하지 않는다.
- `notice_facts`는 해당 개요의 문장과 PDF 페이지 또는 HWPX 구조 블록 위치, 공고 제목이다. `company_facts`는 승인 프로필의 fact key/status/value만 반환한다. 회사 원문·quote·filesystem source·객체 경로는 응답하지 않는다.
- `overview_kind=page|extractive`, `overview_id`, `document_version_id`, 개요 digest, profile id/digest, policy digest, model name/revision, prompt version, 품질 표식, 생성/완료 시각과 입력/출력 토큰·소요시간을 보존한다. 사용량 부재는 null, 실제 0은 0이다.
- `is_current=false`이면 과거 입력 기준이다. 프로필·활성 심층 정책·개요·문서·핏 정책/모델 변경, 입력 hash 불일치가 현재성을 막는다. 회사 핏 결과와 실제 심층 검토 생성 여부를 서로 추정하지 않는다.
- 자동 사유는 `company_fit_disabled|pending|queued|running|stale|mismatch|unknown|failed|needs_human_review|validation_failed|reference_only`에서 접두사 `company_fit_`을 각각 붙인 코드다. 기존 자동 준비 사유도 그대로 반환한다.

`prespec_company_fit_attempt`는 입력 JSON (`bidops.prespec-company-fit-input.v1`, 정책 전문 포함)과 SHA-256, 개요/문서/프로필/심층 정책 FK를 동결한다. 입력 digest는 유일하다. 실행 상태·lease·결과·사용량만 전이할 수 있고 종결 후 UPDATE/DELETE는 DB/ORM에서 거부한다. 원응답은 기존 암호화 model-response 저장소에 저장한다. 종결 이력이 있으면 migration downgrade를 거부한다. 앱 역할은 SELECT, 합성 worker만 INSERT 및 제한된 상태 열 UPDATE를 받는다.
