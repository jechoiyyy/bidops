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
- 새 API와 Lean API 응답은 내부 filesystem path, 객체 저장소 key의 자격증명, prompt, 모델 원응답, 회사 프로필 전문을 포함하지 않는다. 현재 legacy `AttachmentResponse`는 `stored_path?`를, profile snapshots·sections·unknowns는 filesystem `source_ref`/`source`와 raw·parse error를 반환할 수 있는 구현 격차가 있다. 이 field들은 안전한 소비자 계약으로 사용하지 않는다.
- Lean mutation은 `X-BidOps-Actor-Name`을 요구한다. 이 값은 감사 표식이지 인증 정보가 아니다. 비ASCII 이름은 `X-BidOps-Actor-Name-Format: utf-8-percent-v1`과 canonical UTF-8 percent encoding을 함께 사용한다. 형식이 없으면 printable ASCII를 그대로 보존하며 malformed·제어문자 입력은 `actor_name_invalid`로 거부한다.

## 상태와 식별자

- 수집·판정·심층 검토 실행은 서로 다른 불변 execution ID를 사용한다. 재시도는 기존 실행을 덮지 않고 새 attempt 또는 새 execution으로 남긴다.
- 공고 식별자는 외부 공고번호와 DB 내부 식별자를 구분한다. API 경로의 `{notice_pk}`와 `{notice_id}` 의미를 endpoint schema 그대로 따른다.
- 판정 실행 status는 대기, 실행, 부분 성공, 성공, 실패, 중단을 구분한다. terminal status에는 종료 시각이 있어야 한다.
- 심층 검토 attempt stage는 `requirements_and_evaluation`, `delivery_risk_economics`, `synthesis_and_validation`만 허용한다.
- `계속 추적`, `보류`, `종료`와 최종 입찰 `Go/No-Go`는 향후 기회 계약에서 별도 필드·별도 이벤트로 정의해야 하며 현재 final opinion 값에 임의 매핑하지 않는다.

## JSON wire shape 규칙

아래에서 `field?`는 field가 wire에 있을 때 JSON `null`이 허용된다는 뜻이다. 생략 가능성은 `optional`, null 가능성은 `nullable`로 각각 적는다. `optional`은 생략, `nullable`은 `null`, `optional nullable`은 둘 다를 허용한다. Lean request·response는 열거하지 않은 field를 거부한다. legacy model은 호환 동작을 유지하므로 새 소비자는 정의된 field만 사용한다.

- `RunSummary`: `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `screening_basis?`, `status`, `superseded_by?`, `counts`. `counts`는 `notices`, `judgments`, `reviews`, `collection`이다.
- `IngestRequest`: body의 optional nullable `run_id`와 query의 optional nullable `run_id` 중 적어도 하나가 필요하다. `IngestResponse`는 `run_id`, `notices`, `judgments`, `reviews`, `warnings[]`, `warning_counts`다. 같은 회차 재적재는 지원되는 갱신·멱등 경로이며 중복 자체로 409를 반환하지 않는다.
- `NoticeList` query: required `run_id`; optional `grade`, `readiness`, `focus`, `sample_role`(default `analysis`), `attachment=any|none|manual`, `q`, `sort=deadline|grade|published`, `limit` 1..500(default 50), `offset` 0 이상. 응답은 `items`, `total`, 실제 적용한 `filters`다.
- `NoticeListItem`: `id`, `notice_key`, `run_id`, `title?`, `agency?`, `published_at?`, `deadline_at?`, `estimated_price?`, `sample_role?`, `sample_stratum?`, `collection_bucket?`, `grade?`, `readiness?`, `focus?`, `attachment_count`, `attachment_status=none|g2b|manual`이다.
- `ReviewUpsertRequest`: required `run_id`; optional nullable `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `reviewer`; optional `verification_answers`(default `[]`), 요소는 optional nullable `item`, `answer`다. `ReviewResponse`는 `id`, `run_id`, `notice_pk`, 같은 nullable review field, `created_at?`, `updated_at?`, `answers[{id,item?,answer?}]`다. 이 legacy schema의 review 문자열은 wire enum으로 강제되지 않으므로 소비자가 임의의 추가 enum을 가정하지 않는다.
- `AgencyPortalCreateRequest`: required `agency_pattern`, `system_name`, `search_url_template`; optional non-null `enabled`(default `true`), optional nullable `note`. PATCH는 이 다섯 field의 partial body이다. PATCH `enabled`는 nullable이며 `null`을 보내면 현재 값을 바꾸지 않는 no-op이다. `AgencyPortalResponse`는 `id`, 위 다섯 field다.
- legacy `AttachmentResponse`: `id`, `name?`, `url?`, `origin?`, `file_ext?`, `size_bytes?`, `stored_path?`, `extract_status?`, `created_at?`. `stored_path` 노출은 지원할 계약이 아니라 제거 전 구현 격차다. notice detail과 첨부 처리 상태에 nested 될 수 있으므로 client는 해당 field를 표시·저장·재전송하지 않는다.
- `RunDetailResponse`는 `RunSummary` 전체와 `collection_scope`, `pipeline[]`, `artifacts[]`, `warning_counts`다. `collection_scope`는 `window_from?`, `window_to?`, `timezone`, `business_area?`, `pre_spec_available?`, `pre_spec_reason?`, `focus_axes[]`, `performance_reference_count?`다. pipeline item은 `name`, `status`, `artifact?`, `script?`, `execution_id?`, `started_at?`, `finished_at?`, `exit_code?`, `execution_allowed`, `message?`다. artifact item은 `name`, `present`, `schema_version?`, `expected_schema_version?`, `valid?`, `warnings[]`다. legacy `status`들은 wire enum으로 강제되지 않는 string이다.
- `RunStatsResponse`: `run_id`, `timezone`, `generated_at`, `collected_count?`, `candidate_count?`, `sample_count`, `priority_review_count`, `audit_missed_count`, `funnel[]`, grade/readiness/focus `*_distribution[]`, `verification_requests[]`, `imminent_deadlines[]`. funnel item은 `key`, `label`, `count?`; distribution item은 `key`, `label`, `count`; verification request는 `item`, `count`, `notice_pks[]`, `profile_sections[]`; deadline item은 `NoticeListItem` 전체와 `blocking_verification_items[]`다.
- `WarningListResponse`: `run_id`, `items[]`, `total`, `level?`, `code?`. warning item은 `id`, `run_id`, `level`, `code`, `message`, nullable opaque JSON `context?`다. `level`은 legacy wire에서 enum으로 강제되지 않는다.
- `NoticeDetailResponse`는 `NoticeListItem` 전체와 `bid_no?`, `bid_ord?`, `source_type?`, `budget?`, `method?`, `url?`, `timezone`, nullable opaque JSON `procurement_class?`, `region_limit?`, `lifecycle?`, `qualification_flags?`, opaque JSON list `focus_matches[]`, `performance_matches[]`, `candidate_sources[]`, `performance_top_score?`, `judgment?`, `attachments[]`, `reviews[]`다.
- `JudgmentResponse`: `id`, `schema_version?`, `grade?`, `readiness?`, `primary_focus?`, `exclusion_category?`, `summary?`, `next_action?`, `perspectives[]`, `counterarguments[]`, `verification_items[]`, `matched_performances[]`. perspective는 `id`, `position?`, `name?`, `assessment?`, `reason?`, `evidence[{id,source?,status?,fact?}]`; counterargument는 `id`, `position?`, `text?`; verification item은 `id`, `item?`, `why?`, `blocking`, `status?`; matched performance는 `id`, `name?`, `match_reason?`, `mismatch_or_limit?`, `source?`, `status?`다. 이 legacy 문자열도 wire enum으로 강제되지 않는다.
- `RelatedNoticeListResponse`: `notice_pk`, `items[]`; item은 `relation=ordinal|unified|pre_spec`, `notice_pk`, `notice_key`, `title?`, `grade?`, `published_at?`, `change_reason?`다. `NoticeHistoryResponse`는 `notice_key`, `items[]`; history item은 `notice_pk`, `run_id`, `window_from?`, `window_to?`, `timezone`, `generated_at`, `grade?`, `readiness?`, `focus?`, `summary?`, `corrected_grade?`, `corrected_readiness?`, `review_reason?`다.
- `AttachmentProcedureResponse`: `notice_pk`, `agency?`, `bid_no?`, `title?`, `status`, `matched_portal?`, `search_url?`, `portal_message`, `steps[]`, `attachments[]`. 현재 producer의 status는 `missing|provided|completed`이지만 legacy schema는 일반 string으로 받는다. `AttachmentQueueResponse`는 `run_id`, `total`, `items[]`; item은 `NoticeListItem` 전체와 `bid_no?`, `matched_portal?`, `search_url?`, `portal_message`다.
- `ValidationMetricsResponse`: `run_id`, `metrics[]`. metric은 `key`, `label`, `value?`, `percentage?`, nullable opaque JSON `threshold?`, `meets_threshold?`, `status=pass|fail|measured|not_measurable`, `basis`, `reason?`; basis는 `numerator`, `denominator`, opaque JSON object `detail`이다.
- 목표 `ProfileSectionsProjectionResponse`: `schema_version=bidops.profile-projection.v1`, `profile_version`, `profile_digest`, `sections[]`, `status_counts`, `error_codes[]`. section은 `id`, `number?`, `title`, `heading`, `level`, `state=confirmed|inferred|unknown|mixed|unrecorded`, `status_counts`, `items[]`, `children[]`다. item은 `key`, `label`, `section_id`, `section_number?`, `status=confirmed|inferred|unknown`, `value?`다.
- 목표 `ProfileUnknownsProjectionResponse`: 같은 schema·profile binding, `items[]`, `total`, `reference_fields`, `error_codes[]`. item은 `key`, `label`, `section_id`, `section_number?`, `section_title`, `status=unknown`, `value?`, `reference_count?`, `reference_status=counted|unavailable`다. 두 projection은 filesystem `source`, source line, `raw_blocks`, `raw`, 자유 형식 `parse_errors`를 허용하지 않는다. 현재 route는 아직 이 schema를 구현하지 않았다.
- 목표 snapshot list item은 `version`, `digest`, `source_kind=working_tree|git_blob`, `created_at`만 반환한다. 현재 `source_ref`는 working-tree 상대 파일 경로나 Git commit을 반환하므로 API projection에서 제거하고, 내부 provenance로만 보존한다.
- 차단된 현재 profile wire는 다음과 같다. snapshots item은 `version`, `digest`, `source_kind`, `source_ref`, `created_at`이다. sections 응답은 `source`, `sections[]`, `status_counts`, `parse_errors[]`; section은 목표 section field에 `raw_blocks[{line_start,raw,error}]`, `raw?`를 추가하고 item에 `source_line?`을 추가한다. unknowns 응답은 `source`, `items[]`, `total`, `reference_fields[]`, `parse_errors[]`; item은 목표 unknown item과 같다. 이 shape는 현재 코드 사실을 기록할 뿐 신규 client가 의존할 계약이 아니다.
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
| `GET /api/notices/{notice_pk}` | path DB integer notice PK | `NoticeDetailResponse` | 404 |
| `GET /api/notices/{notice_pk}/related` | path DB integer notice PK | `RelatedNoticeListResponse` | 404 |
| `GET /api/notices/{notice_pk}/history` | path DB integer notice PK | `NoticeHistoryResponse` | 404 |

### 리뷰, 첨부, 포털, 프로필

| 호출 | 입력 | 성공 응답 | 주요 실패 |
|---|---|---|---|
| `GET /api/reviews` | required query `run_id` | `ReviewResponse[]` | 404 run, 422 run ID 부재 |
| `GET /api/reviews/export` | required query `run_id` | `bidops.feedback.v2` YAML | 404 run, 422 run ID 부재 |
| `PUT /api/notices/{notice_pk}/review` | run ID, reviewer, disposition, grade/readiness feedback, verification answers | DB 정본 리뷰 | 404 공고·회차, 422 |
| `GET /api/notices/{notice_pk}/attachments` | path DB integer notice PK | `AttachmentProcedureResponse` | 404 |
| `POST /api/notices/{notice_pk}/attachments` | path DB integer notice PK; multipart optional `files[]` and optional `file`, 합쳐 1개 이상 | legacy `AttachmentProcedureResponse`; ClamAV·quarantine·MinIO를 거치지 않음 | 400 형식·크기·빈 upload, 404 공고 |
| `DELETE /api/attachments/{attachment_id}` | attachment ID | 204 | 403 나라장터 제공 첨부, 404 |
| `GET /api/attachments/queue` | required query `run_id` | `AttachmentQueueResponse` | 404 run, 422 run ID 부재 |
| `GET /api/attachments/{attachment_id}/download` | attachment ID | legacy 로컬 파일 stream | 404 |
| `GET /api/portals` | 없음 | `AgencyPortalResponse[]` | 없음 |
| `POST /api/portals` | `AgencyPortalCreateRequest` | 201 `AgencyPortalResponse` | 422 빈 필수 field |
| `PATCH /api/portals/{portal_id}` | `AgencyPortalUpdateRequest` partial body | `AgencyPortalResponse` | 404 portal, 422 빈 field |
| `GET /api/profile/snapshots` | 없음 | 현재 `{items,total}`; item의 working-tree `source_ref`가 내부 상대 경로일 수 있어 운영 사용 차단 | 없음 |
| `GET /api/profile/sections` | 없음 | 현재 `source`, structured sections, raw blocks·raw text, parse errors; 운영 사용 차단 | 파싱 실패가 응답에 노출될 수 있음 |
| `GET /api/profile/unknowns` | 없음 | 현재 `source`, unknown items, reference fields, parse errors; 운영 사용 차단 | 파싱 실패가 응답에 노출될 수 있음 |
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
| `POST /api/policies` | immutable `PolicyVersionCreateRequest` | 201 draft `PolicyVersionResponse` | 409 version, 422 schema |
| `GET /api/policies/{policy_version}` | path version | `PolicyVersionResponse` | 404 |
| `POST /api/policies/{policy_version}/candidate` | path version; `PolicyCandidateRequest` | `PolicyVersionResponse` | 404, 409 status, 422 body |
| `POST /api/policies/{policy_version}/activate` | path version; `PolicyActivationRequest` | `PolicyActivationResponse` | 404, 409 gate·binding, 422 body |
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
| `collected-notices.json` / `bidops.collected.v2` | collect | 표본 선정, 웹 적재 | 원본 회차, 정규화 notices, source window |
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

- 현재 Alembic head는 `0003_screening_runtime_pg`다.
- `0001_lean_v1_postgresql`은 기존 수집·리뷰와 심층 검토 table, `0002_screening_basis_text`는 긴 판정 설명 보존, `0003_screening_runtime_pg`는 판정 실행·품질·정책·일정·감사와 불변 trigger를 추가한다.
- 앱 startup은 revision과 필수 table 존재만 확인한다. migration과 seed를 실행하지 않는다.
- fresh migration은 schedule과 always-on singleton, migration audit만 만든다. screening policy와 agency portal은 명시적 운영 명령 또는 API로 생성한다.
- active screening slot과 active policy는 각각 최대 하나다. queue claim은 queue number FIFO와 짧은 transaction으로 처리한다. deep-review job claim은 PostgreSQL row lock과 `SKIP LOCKED`를 사용한다.

## 발주계획 중심 목표 계약

다음 의미 계약은 합의됐지만 route와 schema version은 아직 배정하지 않았다. 구현할 때 기존 notice 계약을 몰래 확장하지 말고 새 version을 정의한다.

- 발주계획 원본 전체: 공식 계획번호, 사업명, 기관 코드·명, 예산, 예정일, 계약 방식, 업무 구분, SW 상태, 원문 URL, 최초·최근 발견, source hash.
- 방식별 실험 결과: method/version, score, rank, reason, raw output reference, 실행 비용·지연, 사람 relevance·우선순위와 adjudication.
- 내부 opportunity: plan, pre-spec, bid의 공식 관계와 미확정 후보 관계를 분리하고 관계 근거·확인자를 기록한다.
- 사전규격: 독립 수집 회차, 업무·SW 필터, RFP 첨부 bundle, 저비용 선별, 사람 심층 검토 승인.
- 추적: `계속 추적|보류|종료`, 변경 이력, bid 발견, 사전규격 대비 delta, 알림 delivery 상태.
- 실행: 자동 연결과 수동 단독 실행이 같은 execution, attempt, artifact, idempotency, audit 계약을 공유한다.
- 최종 결정: 입찰공고 시점의 사람 `Go/No-Go`를 추적 선택이나 모델 권고와 분리한다.
