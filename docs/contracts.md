# 외부 계약

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
- `current_stage`는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|merge|publish|null`이다. `ScreeningExecutionDetailResponse`는 execution field 전체와 `attempts[]`, `failures[]`다. attempt는 `attempt_id`, `execution_id`, `notice_id`, `stage`, `attempt_no`, `status=success|failure`, `failure_type?`, `done_reason?`, `trace_id`, `span_id`, `prompt_eval_count?`, `eval_count?`, `prompt_eval_duration_ns?`, `eval_duration_ns?`, `load_duration_ns?`, `total_duration_ns?`, `generation_config_digest?`, `num_ctx?`, `num_predict?`, `started_at`, `finished_at`, `error_summary?`다. attempt stage는 `기술 적합성|실적 정합성|공공 SI 적합성|사업성·자격 제약|전략 부합|counterargument|synthesis|carried_over_validation`이다.
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
아래 경로는 `web/backend/app/routers/bid_delta.py`에 존재하며 `app/main.py`에 등록되어 있다.
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
확정할 수 없으면 `unknown`이다. 회사 내부망의 allowlist된 Ollama·사설 vLLM만 사용하며,
exact pair·policy·binding·payload 범위를 확인한 comparison 생성 요청이 건별 내부 모델 처리
승인이다. 외부·hosted fallback은 없고 감사 metadata는 안전한 ID·code·count·hash·binding
digest allowlist만 사용한다. binding은 심층 검토가 쓰는 승인된 사설 vLLM Qwen3.8:27B를
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

### 상태, 회차, 공고

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/health` | 없음 | `{"status":"ok"}` | 프로세스 불가용 |
| `GET /api/runs` | 없음 | `{items: RunSummary[], total}` 전체 회차 | 없음 |
| `POST /api/runs/ingest` | body 또는 query의 run ID | 적재·재적재 건수와 경고 | 404 run directory, 422 run ID 부재 |
| `GET /api/runs/{run_id}` | path run ID | `RunDetailResponse` | 404 |
| `GET /api/runs/{run_id}/stats` | path run ID | `RunStatsResponse`; 계산 불가 count는 null | 404 |
| `GET /api/runs/{run_id}/warnings` | path run ID; optional query `level`, `code` | `WarningListResponse` | 404 |
| `GET /api/runs/{run_id}/pipeline/logs` | path run ID; optional query `execution_id` | `PipelineLogResponse` | 404 |
| `POST /api/runs/{run_id}/pipeline/{stage}` | `stage=collect|sample|report`; optional query `from_raw=false` 또는 optional body `{from_raw:false}` | 202 `PipelineExecutionResponse` | 400 입력·stage, 404 run, 409 active 충돌, 422 body·query |
| `GET /api/notices` | `NoticeList` query | `NoticeListResponse` | 404 run, 422 query |
| `GET /api/pre-specs` | 누적 `PreSpecList` query; 기본 `sw_only=true` | `PreSpecListResponse` | 422 query |
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
| `PATCH /api/opportunities/{opportunity_id}/tracking-status` | actor headers; body `{tracking_status, reason}` | 200 `OpportunityDetailResponse` | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_not_found`; 422 `tracking_status_invalid|tracking_reason_required` |
| `PATCH /api/opportunities/links/{link_id}/decision` | actor headers; body `{decision=accepted|rejected, reason}` | 200 `OpportunityLinkView`; 동일 actor·판정·이유 replay는 같은 reviewed_at | 400 `actor_name_required|actor_name_invalid`; 404 `opportunity_link_not_found`; 409 `candidate_link_required|candidate_decision_conflict|candidate_state_conflict|candidate_target_required|candidate_target_already_authoritative`; 422 body·link ID·blank reason |

추적 상태 변경은 `set_tracking_status()`를 통해 사람 선택과 감사 이벤트를 함께 기록한다. `X-BidOps-Actor-Name`은 인증이 아닌 감사 표식이며, 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 사용한다. `recheck_signal`은 시스템 신호 여부이고 `recheck_signal_at`·`recheck_signal_link_id`는 그 시각과 근거 link를 가리킨다. 이 값들은 사람의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at`과 별도이며, `FinalOpinion` 또는 최종 입찰 `Go/No-Go`로 변환하지 않는다.

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

현재 승인된 사설 model binding이 없으므로 운영 코드에는 transport/fallback이 없다. binding이
없는 호출은 `awaiting_model`에 머물며 attempt를 만들지 않고, 테스트 fake는
`reference_only=true`, `deployable=false`를 명시한 경우에만 사용할 수 있다.

v2 응답은 정확히 `schema_version`, `notice_id`, `reviews[]`를 가지며 review에는
`id`, `notice_id`, `status`, nullable `result`, nullable `result_digest`, nullable
`binding_digest`, `validation_status=passed|failed|pending`, nullable `completed_at`,
`current_snapshot`, `attempts[]`를 둔다. attempt에는 기존 안전 요약에
`validation_status`, nullable `result_digest`, nullable `binding_digest`를 추가한다.
result payload 자체에는 provider/model/prompt/storage metadata가 없고, `result_digest`는
canonical JSON payload의 lowercase SHA-256이다. `result`가 있는 경우에는
`schema_version`, `recommendation`, `summary`, `conditions`, `verification_due_at`,
`unknowns`, `evidence`, `input_limitations`만 반환한다.

bundle confirm은 악성코드 clean 결과, document version, structure snapshot과 hash를 고정한다. 심층 attempt와 report materializer는 live 첨부를 다시 읽지 않고 이 snapshot만 사용한다. validation 실패는 report에서 드러나며 자동 통과로 바뀌지 않는다.

Lean wire model의 정확한 shape는 다음과 같다. 별도 `optional` 표기가 없으므로 모든 field는 wire에 필수이며 `?` field만 필수 nullable이다. UUID·date·datetime은 JSON 문자열이고 `source_sha256`는 64자 lowercase SHA-256이다.

- `DocumentVersionView`: `id`, `bundle_id`, `version>=1`, `role`, `effective_date?`, `replaces_document_version_id?`, `is_current`, `safety_status`, `structure_status`, `original_filename`. `role=공고|정정|제안요청서|과업지시서|내역서|제출서식|부록|기타`, `safety_status=quarantined|scanning|safe|blocked`, `structure_status=pending|processing|ready|failed|needs_review`다.
- `BundleIssue`: `issue_id`, `code`, `severity=차단|중대|보통|낮음`, `blocking`, `document_version_id?`, `message`, `locator_type=none|page|paragraph|table_cell|bbox`, nullable opaque object `locator?`다. `BundleView`: `id`, `notice_id`, `revision>=1`, `version>=1`, `status=draft|processing|needs_review|ready|quarantined|failed|superseded`, `documents: DocumentVersionView[]`, `issues: BundleIssue[]`, `confirmed_by?`, `confirmed_at?`, `created_at`. `BundleListResponse`는 pagination field 없는 정확히 `{items: BundleView[]}`다.
- `PatchDocumentVersionRequest`는 `role`, nullable `effective_date`, nullable `replaces_document_version_id`, `is_current`, `version>=1`이 모두 필수다. `ConfirmRequest`는 `request_id`, `version>=1`, `confirmed_documents[]`; 각 확인 항목은 `document_version_id`, `version>=1`이다.
- `DocumentStructure`: `schema=bidops.document-structure.v1`, `structure_id`, `document_version_id`, `source_sha256`, `media_type`, `extractor`, `pages[]`, `blocks[]`, `warnings[]`, `created_at`. extractor는 `name`, `version`, nullable `upstream_commit`; page metadata는 `number>=1`, `width>0`, `height>0`, nullable `image_content_object_id`; block은 `block_key`, nullable `parent_block_key`, `type`, `page>=1`, nullable numeric `bbox[]`, `text`, nullable `confidence`(0..1), opaque object `attributes`다. `DocumentStructurePageView`는 `structure_id`, `page>=1`, `metadata`, `blocks[]`다.
- `DeepReviewCreateRequest`는 `request_id`, `bundle_id`; `DeepReviewAttemptRequest`는 `request_id`다. `StageView`는 `stage=requirements_and_evaluation|delivery_risk_economics|synthesis_and_validation`, `sequence>=1`, `status=queued|running|completed|failed`, `started_at?`, `completed_at?`, `last_error_code?`. `AttemptView`는 `id`, `sequence>=1`, `status=queued|running|completed|failed|superseded`, `stages: StageView[]`, `started_at?`, `completed_at?`, `last_error_code?`. `DeepReviewView`는 `id`, `notice_id`, `bundle_id`, `status=queued|running|completed|failed`, `current_attempt?`, `attempts: AttemptView[]`, `created_at`, `completed_at?`다.
- `ReportRow`: nonblank `row_key`, nonblank `label`, `cells[]`, `claim_ids[]`. `ReportBlock`: nonblank `block_id`, `type=paragraph|matrix|decision_card|scenario|action_list`, nullable `title`, nullable `body`, `claim_ids[]`, `rows: ReportRow[]`. `ReportSection`: `section_key`, nonblank `title`, `blocks: ReportBlock[]`. section key는 `project_overview|eligibility_matrix|scope_deliverables|requirements_matrix|evaluation_strategy|delivery_plan|technical_integration_risks|security_legal_contract_risks|economics_scenarios|competitive_proposal_strategy|questions_internal_actions|document_bundle_limitations|decision_card`다.
- `ReportClaim`: `claim_id`, nonblank `category`, `claim_type=fact|calculation|inference|opinion|unknown`, nonblank `body`, `status=supported|unsupported|conflicting|unknown`, nullable `formula`, `premise_claim_ids[]`, nullable `reason`, `evidence_ids[]`. `ValidationSummary`: `status=passed|failed`, nonnegative `failed`, `warnings`, `passed`다.
- `DeepReviewReport`: `schema=bidops.deep-review-report.v1`, `deep_review_id`, `notice_id`, `bundle_id`, `profile_version_id`, `policy_version_id`, `sections: ReportSection[]`, `system_recommendation=추진 검토|조건부 추진 검토|보류|검토 종료`, `claims: ReportClaim[]`, `unknowns[]`, `validation_summary`, `created_at`.
- `ValidationCheck`: nonblank `check_type`, `status=passed|failed|warning`, `severity=차단|중대|보통|낮음`, nonblank `message`, `related_claim_ids[]`, `related_evidence_ids[]`. `DeepReviewValidation`: `schema=bidops.deep-review-validation.v1`, `validation_run_id`, `report_revision_id`, `status=passed|failed`, `checks: ValidationCheck[]`, `created_at`. `RevisionHistoryItem`: `revision_id`, `sequence>=1`, `origin=machine|human`, nullable `validation_status=passed|failed`, nullable `created_by_name`, `created_at`.
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
| `bidops.document-structure.v1` | page/block/table 구조와 원문 locator |
| `bidops.document-bundle.v1` | 확정된 document versions와 structure snapshot |
| `bidops.deep-review-stage.v1` | 세 단계의 claims, evidence, unknowns, warnings |
| `bidops.deep-review-report.v1` | 검증된 claim을 이용한 보고서 |
| `bidops.deep-review-validation.v1` | 근거·수치·계약 검증 결과 |
| `bidops.analysis-policy.v1` | 모델, chunk, retry, generation, validation 정책 |
| `bidops.company-profile.v1` | 승인된 회사 profile snapshot |

모델 response 원문은 암호화된 객체로 저장하고 DB에는 namespace, version, hash, key reference만 둔다. evidence locator는 document version, structure ID, page·block 또는 표 좌표를 포함하며 report의 사실·숫자와 연결된다.

## DB와 migration 계약

- T-23 phase 2 migration은 `0014_prespec_overview_attempt_result`이다. 현재 공유 worktree의
  Alembic head는 별도 입찰 delta 작업인 `0015_bid_delta_final_decision`이며, 아래 T-23 검증
  증거는 `0014` 경계에 해당한다.
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
| `GET /api/order-plans` | `source_run_id?`, `stage1_status?`, `stage2_status?`, `qwen_relevance?`, `human_relevance?`, `q?`, `limit=1..500`, `offset>=0` | `items`, `total`, `limit`, `offset`; item은 `order_plan_pk`, `order_plan_unty_no`, title, agency, nullable `budget_amount`·`planned_order_year`·`planned_order_month`, source run/observation, BM25 stage status/rank/score/`nearest_capability`, Qwen stage status/score/label/reason, latest human feedback summary | `invalid_request(422)` |
| `GET /api/order-plans/{order_plan_pk}` | path PK | 누적 plan metadata(`budget_amount`, planned year/month 포함)와 `screening_history`, latest result/feedback; source·internal path는 반환하지 않음 | `not_found(404)` |
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
| `order-plan-list-response.v1` | `order-plan-review-api` → `order-plan-review-client` | `GET /api/order-plans` | provenance, `items`, `total`, `limit`, `offset`; item의 nullable 예산·계획 시기·BM25 `nearest_capability`와 stage status/label/score | response projection only; 내부 경로·본문 금지 |
| `order-plan-detail-response.v1` | API → client | `GET /api/order-plans/{id}`, `/screening-history` | provenance, plan metadata의 nullable `budget_amount`·계획 시기, `screening_history` 또는 `items`; history의 `nearest_capability`·`batch_id`·`attempt_no` | read-only projection; 기존 notice response와 혼용 금지 |
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
