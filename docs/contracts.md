# 외부 인터페이스·파일·DB 계약

이 문서는 현재 FastAPI router, Pydantic schema, 파일 writer, SQLAlchemy model과 Alembic migration이 실제로 제공하는 계약을 요약한다. JSON은 UTF-8이다. 날짜·시각은 timezone을 포함한 ISO 8601을 사용하고 확인 불가 값은 `null`/`unknown`을 보존한다.

기본 경로는 `/api`이며 현재 인증 헤더는 없다. JSON 요청은 `application/json`, 첨부 등록은 `multipart/form-data`를 사용한다. 성공 응답은 명명된 Pydantic 모델이고, YAML export와 다운로드는 각 endpoint가 지정한 media type을 사용한다. 소비자는 오류 `detail` 문구를 영구적인 오류 식별자로 사용하지 않는다.

## 공통 REST 오류

기본 prefix는 `/api`이고 현재 인증 헤더는 없다. 오류 body는 FastAPI의 `{"detail": <문자열 또는 검증 오류 목록>}`이며 `detail` 문구는 영구적인 오류 식별자가 아니다.

| 상태 | 의미 |
|---:|---|
| 202 | queue 또는 비동기 pipeline이 접수됨 |
| 400 | 입력·파일·profile/policy 계약 또는 안전 경로 위반 |
| 404 | run/notice/attachment/policy/gate/execution 없음 |
| 409 | 현재 상태·중복 reservation·활성화·환경 cap 충돌 |
| 422 | Pydantic body/query/enum/필수 값 검증 오류 |
| 503 | 모델 preflight 또는 필수 외부 runtime을 접수 전에 사용할 수 없음 |
| 500 | DB·파일·서버 내부 오류. 오류에 prompt/profile/API key를 포함하지 않음 |

`GET /api/health`는 `{"status":"ok"}`의 lightweight 응답이며 Ollama·수집기·DB migration 상태를 대신 보장하지 않는다. 앱 시작에서 DB revision이 head가 아니거나 빈/unversioned DB이면 프로세스가 actionable error로 종료한다.

## 기존 회차·공고 API

| 호출 | 계약 |
|---|---|
| `GET /api/runs` | 최신순 run `items`, `total` |
| `GET /api/runs/{run_id}` | 수집 범위, 단계, artifact 검증, warning count |
| `GET /api/runs/{run_id}/stats` | funnel, grade/readiness, focus, unknown/마감 지표 |
| `GET /api/runs/{run_id}/warnings` | `level`, `code` 선택 filter와 items/total |
| `POST /api/runs/ingest` | JSON 또는 `run_id`로 기존 파일을 DB에 적재; 경로 안전성 위반 400 |
| `POST /api/runs/{run_id}/pipeline/{stage}` | `collect|sample|report`(및 아래 judgment); 비동기 202, 실행 중 중복 409 |
| `GET /api/runs/{run_id}/pipeline/logs` | 선택 `execution_id`에 대한 순서 있는 pipeline 로그 |
| `GET /api/notices` | 필수 `run_id`, grade/readiness/focus/sample_role/attachment/q/sort/limit/offset filter |
| `GET /api/notices/{notice_pk}` | 공고, 다섯 관점 판정, 첨부, review |
| `GET /api/notices/{notice_pk}/related` | 차수·통합·사전규격 관련 공고 |
| `GET /api/notices/{notice_pk}/history` | 안정 공고 key의 회차별 판정·수정 이력 |

`GET /api/notices`는 `run_id`가 필수이고 기본값은 `sample_role=analysis`, `attachment=any`, `sort=deadline`, `limit=50`, `offset=0`이다. `limit`은 1..500, `offset`은 0 이상이다. `grade`를 생략하거나 `all`이 아니면 `제외`를 기본 제외하며, `grade=all`에서 포함한다. `sample_role=all`은 표본 역할 filter를 해제한다. `attachment=any`는 제한 없음, `none`은 첨부가 없는 공고, `manual`은 수동 첨부가 있는 공고다.

정렬은 `deadline`이 마감일 오름차순(null last)·notice DB id 오름차순, `grade`가 `GRADE_ORDER` 순·마감일 오름차순(null last)·id 오름차순, `published`가 게시일 내림차순(null last)·id 내림차순이다. `q`는 title 또는 agency의 case-insensitive 부분 문자열 검색이며, `focus`는 `Judgment.primary_focus`, `readiness`는 readiness 값 filter다. 응답 `filters`는 실제 적용한 값과 limit/offset을 그대로 반환한다.

| `GET /api/reviews?run_id=...` | DB 정본 review |
| `PUT /api/notices/{notice_pk}/review` | review body 전체 교체; 확인 답변은 누락 시 기존 배열을 삭제 |
| `GET /api/reviews/export?run_id=...` | `application/yaml`, `bidops.feedback.v2` |
| `GET /api/metrics/validation?run_id=...` | 계산 가능한 validation 지표와 미측정/계산 불가 상태 |

`ReviewUpsertRequest`는 `run_id`, `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `reviewer`, `verification_answers[]`를 가진다. answer item은 `item`, `answer`이고 모두 nullable text다. 빈 reviewer는 설정의 reviewer name fallback을 사용하며, 문자열은 trim 후 빈 값이면 null로 저장한다. 같은 `(notice_pk, run_id)`는 하나의 review만 가진다. 목록은 notice_pk 오름차순이다.

`ReviewResponse`는 `id`, `run_id`, `notice_pk`, 위 review 필드, `created_at`, `updated_at`, `answers[{id,item,answer}]`를 반환한다. PUT은 answer 배열 전체를 교체한다. `GET /api/reviews/export`는 모든 공고를 포함한 `bidops.feedback.v2` YAML을 `application/yaml`과 `review-feedback.yaml` attachment filename으로 반환하며, 리뷰가 없는 공고도 null 필드와 빈 `verification_answers`로 포함한다.

YAML 정본 호환 구조는 top-level `schema_version: bidops.feedback.v2`, `reviews[]`이며 각 행은 `notice_id`, `disposition`, `system_judgment_review`, `corrected_grade`, `corrected_readiness`, `weakest_perspective`, `reason`, `verification_answers[{item,answer}]`를 가진다. export는 DB review를 수정하지 않으며, reviewer와 내부 DB id는 이 호환 YAML에 포함하지 않는다.

`GET /api/metrics/validation`의 metric item은 `key`, `label`, `value`, `percentage`, `threshold`, `meets_threshold`, `status`, `basis{numerator,denominator,detail}`, `reason`이다. status는 `pass|fail|measured|not_measurable`이고, 계산할 수 없는 단계의 count를 0으로 숨기지 않는다.

프로필·기관 포털의 읽기/관리 경계도 API에만 있다. `GET /api/profile/snapshots`, `/api/profile/sections`, `/api/profile/unknowns`는 snapshot/tree/unknown 보존 정보를 반환한다. `GET /api/portals`, `POST /api/portals`, `PATCH /api/portals/{portal_id}`는 기관 portal metadata를 관리한다. `GET /api/attachments/queue?run_id=...`는 첨부가 없는 공고의 작업 목록을 반환한다.

`GET /api/profile/snapshots`는 immutable metadata만 반환한다: `version`, `digest`, `source_kind`(`working_tree|git_blob`), `source_ref`, `created_at`, `total`. body와 filesystem path는 반환하지 않는다. version은 `company-profile.sha256:<64hex>`이고 digest와 suffix가 일치해야 한다. `git_blob` source_ref는 lowercase 40-hex commit, working-tree source_ref는 relative POSIX path이며 absolute/traversal/backslash를 허용하지 않는다.

snapshot 목록은 `created_at` 내림차순, 같은 시각에는 `digest` 내림차순이며 `total`은 전체 immutable row 수다. `git_blob` snapshot은 승인된 baseline commit과 canonical profile path를 사용하고, working-tree snapshot은 읽은 bytes의 digest를 version에 묶는다.

`ProfileSectionsResponse`는 `source`, recursive `sections`, `status_counts`, `parse_errors`를 반환한다. section은 `id`, number/title/heading/level, state(`confirmed|inferred|unknown|mixed|unrecorded`), status_counts, `items`, `raw_blocks`, `raw`, children을 가진다. item은 key/label/section identity/status(`confirmed|inferred|unknown`)/value/source_line이다. `raw_blocks`는 line_start/raw/error를 가지며 parser가 인식하지 못한 원문을 버리지 않는다.

`ProfileUnknownsResponse`는 source, unknown `items`, total, reference_fields, parse_errors를 반환한다. unknown item은 key/label/section identity/status=`unknown`/value/reference_count/reference_status(`counted|unavailable`)를 가진다. reference DB 조회 실패는 `reference_count=null`, `reference_status=unavailable`이며 0으로 치환하지 않는다.

기관 portal item은 `id`, `agency_pattern`, `system_name`, `search_url_template`, `enabled`, `note`다. `GET /api/portals`는 enabled 내림차순·id 오름차순, POST는 세 필수 text(agency pattern/system name/search template)와 enabled/note를 받아 201, PATCH는 제공한 field만 갱신한다. 필수 text가 공백이면 422, 없는 id는 404다. URL template은 `{bid_no}`와 `{title}` placeholder를 URL-encode해 검색 URL로 만든다.

첨부는 `GET /api/notices/{notice_pk}/attachments`, multipart `POST /api/notices/{notice_pk}/attachments`(HWP/HWPX/PDF, 50MB 이하), `DELETE /api/attachments/{attachment_id}`(수동 첨부만), `GET /api/attachments/{attachment_id}/download`(PDF 또는 octet-stream)이다. 내부 `stored_path`를 조합하지 말고 API URL만 사용한다. 제공 첨부 삭제는 403이다.

업로드는 extension을 filename suffix에서 lowercase로 정규화해 `hwp|hwpx|pdf`만 허용하고, streaming chunk 단위로 50 MiB 초과를 거부한다. 서버 생성 UUID filename을 notice별 attachment root 아래에 쓰며 원래 filename은 metadata로만 보존한다. 임시 upload와 final file은 실패 시 정리한다. `stored_path`는 상대 path로 저장하고 `safe_stored_path`가 root 밖·`..`·symlink escape를 거부한다. 삭제도 동일한 경로 검사를 통과한 수동 파일만 지운다.

`AttachmentProcedureResponse`는 `notice_pk`, agency/bid_no/title, `status`(`missing|provided|completed`), `matched_portal`, `search_url`, `portal_message`, procedure `steps`, `attachments[]`를 반환한다. attachment item은 `id`, name, API `url`, `origin`, `file_ext`, `size_bytes`, `stored_path`, `extract_status`, `created_at`이다. 다운로드는 stored path가 없거나 파일이 아니면 404, PDF만 `application/pdf`, 나머지는 `application/octet-stream`이다. 원래 name의 CR/LF는 filename header에서 제거한다.

`GET /api/attachments/queue`는 run의 첨부 없는 공고만 반환하고 agency, grade, deadline, id로 결정적으로 정렬한다. portal 매칭은 enabled row 중 agency pattern의 casefold 부분 일치에서 가장 긴 pattern, 동률이면 작은 id를 선택한다. `0001_existing_schema`는 portal table을 만들지만 row를 seed하지 않으므로 fresh migrated DB의 queue는 등록된 portal이 없을 때 `matched_portal=null`, search URL 없음으로 응답한다.

## 판정 실행 API

| 호출 | 입력·성공 | 안전한 실패 |
|---|---|---|
| `POST /api/runs/{run_id}/pipeline/judgment` | `policy_version`, `profile_source`, `requested_by`; queue 접수 202 | run/profile/input 400/404, model preflight 503, 중복 409 |
| `GET /api/screening/executions` | status/trigger/run filter, limit/offset; queue list | query validation 422 |
| `GET /api/screening/executions/{execution_id}` | execution detail, binding, current stage, counts, stop/publish/error metadata | 없음 404 |
| `POST /api/screening/executions/{execution_id}/stop` | actor/requester; queued 즉시 중단, running `중지 요청` | terminal state 409 |
| `GET /api/screening/executions/{execution_id}/artifacts/{kind}` | `decisions|failures|telemetry|screening_result` known kind만 | unknown/path escape/not ready 400/404 |

상태는 `대기|실행 중|중지 요청|성공|부분 성공|실패|중단됨`이다. `--wait` CLI도 이 FIFO를 우회하지 않는다. 실행 actor는 인증이 아니라 audit attribution이다.

## 품질·정책·스케줄 API

| 호출 | 계약 |
|---|---|
| `POST /api/quality-gates` | `purpose`, policy version, profile source, `created_by`; A/B 두 `quality_sample`을 같은 transaction으로 queue하고 202 |
| `GET /api/quality-gates` | purpose/status/run filter 목록 |
| `GET /api/quality-gates/{gate_id}` | A/B execution, aggregate status, latest immutable evaluation |
| `PUT /api/quality-gates/{gate_id}/reviews/{notice_id}` | reviewer, evidence judgment, note, decision digest; pass A review만 허용 |
| `GET /api/policies` / `GET /api/policies/{version}` | immutable policy versions/status |
| `POST /api/policies` | version, creator, prompt version, five prompt objects, candidate selection, thresholds; 새 body 생성 |
| `POST /api/policies/{version}/candidate` | actor와 activation candidate projection |
| `POST /api/policies/{version}/activate` | passing operational evaluation ID와 confirmed actor; exact binding일 때만 활성화 |
| `GET /api/schedule/settings` | `ScheduleSettingsResponse`: Asia/Seoul, daily/weekly time, prespec, update metadata |
| `PATCH /api/schedule/settings` | DB singleton 변경 및 즉시 reschedule |
| `GET /api/schedule/executions` | job kind/status/window/recovery 관계 |
| `POST /api/schedule/executions` | 예약·수동 복구 요청; 202 |
| `GET /api/schedule/always-on` | 환경 cap, DB switch, gate/policy binding |
| `PUT /api/schedule/always-on` | false도 actor 필요; true는 actor+passing evaluation ID+환경 true 필요 |

`model_comparison` gate는 activate할 수 없고 `operational_approval`만 current profile로 activate 후보가 된다. 환경 scheduler false에서 always-on true는 409다. 정책/always-on은 pass만으로 자동 변경되지 않는다.

## 파일 계약

모든 artifact는 알려진 execution root 안에 생성되고 UTF-8, SHA-256, path/symlink 검사 대상이다. `data/runs` 파일과 DB run/review/attachment는 원본 보존 정책을 따른다.

| 경로·파일 | schema/제약 | 생성·소비 |
|---|---|---|
| `data/runs/<run_id>/collected-notices.json` | `bidops.collected.v2` | collect → ingest/sample |
| `data/runs/<run_id>/validation-set.json` | `bidops.validation-set.v2` | fixed 40 quality gate; 정기 전체 판정 대체 아님 |
| `data/runs/<run_id>/screening-decisions.json` | 기존 v2, 신규 v3 | 역사 파일 또는 screening worker |
| `data/screening-executions/<id>/screening-input.json` | `bidops.screening-input.v1` | frozen model input |
| `.../screening-decisions.json` | `bidops.decisions.v3` | 성공 판정, 다섯 unique perspective |
| `.../screening-failures.json` | `bidops.screening-failures.v1` | notice별 stage/failure/attempt |
| `.../screening-telemetry.jsonl` | `bidops.screening-telemetry.v1` | trace/span/Ollama 호출 메타데이터 |
| `.../screening-results.json` | screening v3 결과 | deterministic merge |
| `data/runs/<derived>/screening-replacement-provenance.json` | 실행·source 관계 | full run 파생 publish |
| `data/runs/<run_id>/review-feedback.yaml` | `bidops.feedback.v2` | 사람이 읽는 export/DB 정본 호환 |

`screening-input.v1`은 `schema_version`, `execution_id`, `run_id`, `generated_at`, `source_window{from,to,timezone}`, `prompt_version`, `policy_version`, `company_profile_version`, `company_profile_digest`, `candidate_count`, `notices[]`를 갖는다. notice는 normalized fields와 `judgment_mode`(`신규|재판정|승계`), 승계의 `carry_over_from`, 재판정의 `rejudge_reason`을 가진다. 신규/재판정은 일곱 span 대상, 승계는 모델 호출 없음이다.

| 필드 | 계약·검증 |
|---|---|
| `schema_version` | 정확히 `bidops.screening-input.v1` |
| `run_id`, `generated_at` | 현재 immutable run과 연결하고 timezone-aware ISO 8601을 사용 |
| `source_window` | `from`, `to`, `timezone`을 가지며 `timezone=Asia/Seoul`, from ≤ to |
| `candidate_count` | `notices[]` 길이와 정확히 일치하며 후보를 누락해 0으로 숨기지 않음 |
| `notices[]` | `bidops.collected.v2` normalized fields(`notice_id`, 기본 정보, lifecycle, qualification flags, attachments, focus/performance matches, candidate sources, unknown fields, raw source)를 보존하고 회차 안에서 `notice_id`가 unique |
| `judgment_mode` | `신규`, `재판정`, `승계` 중 하나 |
| `carry_over_from` | `승계`에서 완료된 이전 판정 회차 식별자 필수, 그 밖에는 `null` |
| `rejudge_reason` | `재판정`에서만 `정정`, `재공고`, `본공고 전환`, `담당자 요청` 중 하나, 그 밖에는 `null` |

공고 원문·회사 프로필 전문은 입력 파일에 복사하지 않는다. 승계가 이전 계약 검증에 실패하면 모델 호출이나 자동 보정 없이 `screening-failures.v1`의 `schema_violation`으로 격리한다. 이전 run의 파일·DB row·review는 수정하지 않는다.

`decisions.v3`는 model/prompt/policy/profile identity, `judged_in_run`, `recorded_in_run`, `carried_over`, `rejudge_reason`, `two_axis_mixing_flag/label`, grade/readiness, 다섯 perspective, evidence, counterargument, verification items를 가진다. 승계는 원 binding/최초 회차를 보존하며 신규처럼 기록하지 않는다.

### 판정 대상 입력 `bidops.screening-input.v1`

`screening-input.json`은 `schema_version`, `run_id`, `execution_id`, `generated_at`, `source_window{from,to,timezone}`, `prompt_version`, `policy_version`, `company_profile_version`, `company_profile_digest`, `candidate_count`, `notices[]`를 가진다. 실행 artifact의 입력 digest와 DB binding은 bytes를 기준으로 확인한다. `notices[]`는 `bidops.collected.v2`의 normalized notice fields(`notice_id`, 기본 정보, lifecycle, qualification flags, attachments, focus/performance matches, candidate sources, unknown fields, raw source)와 `judgment_mode`를 가진다. 원문·프로필 전문을 복사하지 않는다.

| `judgment_mode` | 호출 | 추가 제약 |
|---|---|---|
| `신규` | 7 span | `carry_over_from=null`, `rejudge_reason=null` |
| `재판정` | 7 span | reason은 `정정|재공고|본공고 전환|담당자 요청` 중 하나 |
| `승계` | 모델 호출 없음 | 완료된 이전 회차 `carry_over_from` 필수, reason null |

후보 전량은 `screening-input.v1`에 들어가며 `validation-set.v2`가 정기 판정 대기열을 대신하지 않는다. `candidate_count`는 notices 길이와 같고 notice ID는 회차 안에서 unique다. 승계는 이전 식별자·grade/readiness·관점·근거·반론·verification을 보존한 새 immutable artifact이고, 원 DB/file/review를 수정하지 않는다.

### 판정 결과 `bidops.decisions.v3`

새 실행의 decisions top-level은 `schema_version`, `execution_id`, `run_id`, `generated_at`, `screening_basis`, `model_name`, `model_digest`, `prompt_version`, `policy_version`, `company_profile_version`, `company_profile_digest`, `judgments[]`다. 각 judgment는 notice identity, `judgment_mode`, `grade`, `readiness`, `primary_focus`, `exclusion_category`, `summary`, `next_action`, 다섯 perspective, `matched_performances`, `counterarguments`, `verification_items`, model/policy/profile binding과 `judged_in_run`, `recorded_in_run`, `carried_over`, `rejudge_reason`, `two_axis_mixing_flag`, `two_axis_mixing_label`을 보존한다.

grade는 `우선 검토|검토 권장|관찰 대상|제외`, readiness는 `확인 완료|부분 확인 필요|참여 불가 확인|해당 없음`이다. perspective 이름은 기술 적합성·실적 정합성·공공 SI 적합성·사업성·자격 제약·전략 부합이 각각 정확히 한 번이다. 각 perspective는 assessment, reason, evidence[{source,status,fact}]를 결정적으로 검증한다. counterargument는 공고 특화 문장이어야 하며 verification item은 item/why/blocking/status를 가진다. 확인 불가를 이유로 grade를 자동 하향하지 않는다.

승계에서 `carried_over=true`, `judged_in_run`은 최초 생성 회차, `recorded_in_run`은 현재 회차다. 신규·재판정은 carried_over false이며 원본 생성과 현재 기록 회차가 같다. profile version은 항상 `company-profile.sha256:<company_profile_digest>`와 일치한다. `사업성·자격 제약=확인 불가`이고 grade가 `관찰 대상|제외`면 `two_axis_mixing_flag=true`, label `확인 요망`을 남기지만 실패나 자동 보정으로 바꾸지 않는다.

| v3 교차 규칙 | 제약 |
|---|---|
| `judgment_mode` | 입력의 같은 notice 값과 일치 |
| `carried_over` | `신규`·`재판정`은 `false`, `승계`는 `true` |
| `judged_in_run` / `recorded_in_run` | 신규·재판정은 동일, 승계는 최초 생성 회차와 현재 기록 회차를 각각 보존 |
| model/prompt/policy/profile binding | 신규·재판정은 실행과 일치, 승계는 원 판정 값을 보존 |
| five perspectives | 기술 적합성, 실적 정합성, 공공 SI 적합성, 사업성·자격 제약, 전략 부합이 각각 정확히 한 번 |
| `two_axis_mixing_*` | 표시가 true여도 실패·재시도·등급 자동 변경을 하지 않고 review/metrics에 남김 |

v3의 grade는 `우선 검토|검토 권장|관찰 대상|제외`, readiness는 `확인 완료|부분 확인 필요|참여 불가 확인|해당 없음`이다. perspective는 assessment/reason/evidence[{source,status,fact}], counterargument는 공고 특화 문장, verification item은 item/why/blocking/status를 가지며 기존 결정적 검증 규칙을 그대로 적용한다.

### 실패·병합·계측 파일

`screening-failures.json`은 `schema_version=bidops.screening-failures.v1`, `execution_id`, `run_id`, `generated_at`, `failure_count`, `failures[]`다. failure item은 `notice_id`, `failed_stage`(다섯 관점/반론 검토/종합 판정/병합·검증), `failure_type`(`timeout|truncated_output|schema_violation|evidence_missing|counterargument_repetition`), `last_attempt_at`, `retry_count`, status=`사람 검토 대기`, `failure_context`(승계 검증이면 `carried_over_validation`), optional trace/span, safe `error_summary`다. 승계 검증 실패는 새 failure type을 만들지 않고 `schema_violation`+`carried_over_validation`으로 기록한다. 실패 공고는 decisions와 merge input에서 제외한다.

| 필드 | 허용 값·의미 |
|---|---|
| `failed_stage` | 다섯 관점, `반론 검토`, `종합 판정`, `병합·검증` |
| `failure_type` | `timeout`, `truncated_output`, `schema_violation`, `evidence_missing`, `counterargument_repetition` |
| `retry_count` | 최초 시도 후 재시도 횟수인 0 이상 정수; 시도 횟수를 성공으로 보정하지 않음 |
| `status` | 항상 `사람 검토 대기` |
| `failure_context` | 승계 검증 실패에서만 `carried_over_validation`, 그 밖에는 `null` |
| `trace_id`, `span_id` | model 호출 실패에는 연결자를 남기고 병합·검증 실패에는 `null`일 수 있음 |
| `error_summary` | 안전한 분류만 저장하며 원문·prompt·profile·secret을 포함하지 않음 |

`screening-telemetry.jsonl`은 실제 artifact line마다 정확히 `schema_version`, `execution_id`, `trace_id`, `span_id`, `notice_id`, `stage`, `attempt_no`, `status`, `failure_type`, `done_reason`, `model_name`, `model_digest`, `prompt_eval_count`, `eval_count`, `prompt_eval_duration_ns`, `eval_duration_ns`, `load_duration_ns`, `total_duration_ns`, `started_at`, `finished_at`을 저장한다. `parent_span_id`, `run_id`, `prompt_version`, `policy_version`, `recorded_at`은 이 JSONL의 필드가 아니며 실행/DB binding에서 추적한다. 공고 하나의 trace 아래 다섯 perspective·counterargument·synthesis span과 재시도 span을 남긴다. 응답이 없거나 측정하지 못한 수치에는 0을 넣지 않고 null을 보존하며 prompt/response body·비밀은 기록하지 않는다.

telemetry의 `stage`는 다섯 관점, `counterargument`, `synthesis` 중 호출 단계이고 `attempt_no` 최초 값은 1이다. `status`는 `success|failure`이며 Ollama가 반환한 token/duration 수치를 재계산하지 않는다. 승계에는 model-call span을 만들지 않고, 재시도는 같은 trace 아래 앞선 실패 span을 삭제하지 않은 채 새 span으로 기록한다. 이 파일은 관측 정본이지 grade/readiness의 정본이 아니다.

v3 merge의 허용 조합은 `screening-input.v1 + decisions.v3 → bidops.screening.v3`뿐이며, 과거 호환은 `validation-set.v2 + decisions.v2 → bidops.screening.v2`다. 다른 세대 조합은 중단한다. 현재 v3 top-level은 `schema_version`, `execution_id`, `generated_at`, `screening_basis`, `source_window`, `model_name`, `model_digest`, `prompt_version`, `policy_version`, `company_profile_version`, `company_profile_digest`, `candidate_count`, `result_count`, `partial_artifact`, `failure_count`, `failure_artifact`, `results[]`다. `partial_artifact`는 성공 subset과 failure artifact가 함께 있을 때 true이며, 모든 후보가 검증되면 false·failure_count 0·failure_artifact null이다. 전역 merge/validation 실패를 성공 산출물로 만들지 않는다. full-run 파생 publish는 `screening-replacement-provenance.json`으로 source/execution 관계를 기록하고 원 run/review/file을 수정하지 않는다.

### 정책 JSON `bidops.screening-policy.v1`

정책 body는 `schema_version`, `policy_version`, `prompt_version`, `perspective_prompts`, `counterargument_prompt`, `synthesis_prompt`, `candidate_selection`, `thresholds`의 canonical JSON이고 DB row에 `content_digest`를 저장한다. perspective prompt key는 다섯 관점과 정확히 일치하고, 각 prompt object는 version/template/input allow-list/output schema/evidence location requirement를 가진다. policy body/threshold는 immutable이며 status는 `draft|activation_candidate|active`, active slot은 최대 하나다. 실제 공고·프로필·API key를 policy body에 넣지 않는다.

`candidate_selection`은 rules version과 focus-title/classification, performance similarity, include conditions, unknown handling을 보존한다. `thresholds`의 고정 이름은 `quality_gate`(reproducibility grade, reviewer agreement, evidence missing, perspective split, discrimination, audit sample size, information sufficiency는 별도 수치 없음)와 `validation.counterargument_repetition`이며, 측정되지 않은 운영값을 0·빈 문자열·통과값으로 채우지 않는다. 현재 gate 기준 수치는 [모델 품질 게이트](./model-quality-gate.md)의 단일 표를 따른다.

## Runtime REST response 세부

`JudgmentExecutionCreateRequest`는 `policy_version`, `profile_source`(`current` 또는 `git:<40 lowercase hex>`), `requested_by`다. actor는 trim 후 1..128자다. `ScreeningStopRequest`는 `requested_by`다. `ScreeningExecutionResponse`는 `queue_no`, `execution_id`(`scr-`+32 lowercase hex), `trigger`, `source_run_id`, `scope`, optional single `notice_id`, `status`, actor/binding fields, `queued_at`, start/finish/heartbeat/stop metadata, counts, optional publish/error/current metadata, `queue_position`, `result_urls`를 가진다. single 외 scope는 notice_id null이다. 대기만 queue_position을 가지며 terminal은 finished_at이 필수다.

`ScreeningExecutionDetailResponse`는 response와 `attempts[]`, `failures[]`를 추가한다. attempt는 `attempt_id`, execution/notice/stage, attempt_no, success/failure, failure type, done reason, trace/span, Ollama token/duration fields, started/finished, error summary다. stage에는 `carried_over_validation`이 포함된다. artifact kind는 `decisions|failures|telemetry|screening_result`만 허용하고 JSON/NDJSON media type과 known API path만 노출한다.

`QualityGateCreateRequest`는 purpose/policy/profile/created_by다. comparison은 정확한 역사 Git profile, approval은 `current`만 허용한다. `QualityGateResponse`는 gate identity, purpose/execution/result status, fixed baseline/sample paths의 digest, policy/prompt/model/profile binding, distinct pass A/B execution IDs, actor/timestamps, latest evaluation ID, metrics/reasons를 가진다. evaluation은 evaluation ID(`gateeval-`+32 hex), gate/revision/result/metrics/reasons/valid review counts/created_at이고 append-only다. review는 review/gate/execution/notice ID, decision digest, reviewer, evidence judgment(`동의|근거 부족|판단 보류`), note, timestamps다.

`PolicyVersionCreateRequest`는 policy_version, created_by, prompt_version, five prompt objects, counterargument/synthesis prompt, candidate selection, thresholds다. candidate request는 confirmed_by, activation request는 `quality_gate_result_id`(`gateeval-`+32 hex)와 confirmed_by다. active response에는 이전 active version, activation status, activated_at과 평가 ID가 포함된다. gate가 latest passing operational approval이 아니거나 binding이 다르면 409다.

`ScheduleSettingsResponse`는 timezone=`Asia/Seoul`, daily_time, weekly_time, prespec_enabled, updated_at/updated_by다. PATCH는 이 셋 중 적어도 하나와 updated_by가 필요하고 HH:MM을 검사한다. `ScheduleExecutionCreateRequest`는 job_kind daily/weekly, window_from/to, optional recovery execution ID, requested_by다. daily는 하루, weekly는 월요일–일요일 7일이어야 한다. summary는 run_key, run/status/kind, execution/trigger, duplicate/recovery relation, skip/failure reason, actor/timestamps/counts/partial, policy/model/prompt/profile binding을 반환한다. run_key는 daily `YYYYMMDD-YYYYMMDD`, weekly `weekly:YYYYMMDD-YYYYMMDD`다.

`AlwaysOnSwitchResponse`는 configured/effective/environment flags, quality gate status/result ID, policy/model/prompt/profile binding, updated actor/time, rejection_reason을 반환한다. PUT body는 enabled, confirmed_by, enabled=true일 때 required evaluation ID다. 환경 false는 409; binding/approval mismatch도 409다. false는 기존 실행·artifact를 삭제하지 않는다.

### REST 모델 필드 표

`ScreeningExecutionResponse`의 exact public keys는 `queue_no`, `execution_id`, `trigger`, `source_run_id`, `scope`, `notice_id`, `status`, `requested_by`, `policy_version`, `prompt_version`, `model_name`, `model_digest`, `company_profile_version`, `company_profile_digest`, `input_artifact_digest`, `queued_at`, `started_at`, `finished_at`, `heartbeat_at`, `stop_requested_at`, `stop_requested_by`, `stop_reason`, `candidate_count`, `completed_count`, `failure_count`, `published_run_id`, `error_summary`, `queue_position`, `current_notice_id`, `current_stage`, `result_urls`다. `result_urls`는 decisions/failures/telemetry/screening_result/published_run의 `/api/` path 또는 null이다. 실행·프로필 전문, filesystem path, prompt body는 public response에 없다.

`QualityGateResponse`의 exact public keys는 `gate_id`, `purpose`, `execution_status`, `result_status`, `baseline_run_id`, `sample_artifact_digest`, `baseline_decisions_digest`, policy/prompt/model/profile binding, `pass_a_execution_id`, `pass_b_execution_id`, `created_by`, `created_at`, `completed_at`, `latest_evaluation_id`, `metrics`, `reasons`다. detail은 `pass_a`, `pass_b`, `evaluations`, `reviews`를 추가한다. pass IDs는 서로 달라야 하며 terminal execution status에서만 completed_at이 존재한다. latest evaluation revision 1은 gate 생성 transaction에 함께 생성된다.

`ScheduleExecutionSummary`의 exact public keys는 `run_key`, `run_id`, `window_from`, `window_to`, `job_kind`, `status`, `execution_id`, `trigger`, `duplicate_of_execution_id`, `recovery_of_execution_id`, `skip_reason`, `failure_reason`, `requested_by`, `started_at`, `finished_at`, `candidate_count`, `result_count`, `failure_count`, `partial_artifact`, policy/model/prompt/profile binding이다. duplicate와 recovery는 동시에 있을 수 없고, duplicate는 반드시 `건너뜀`이다. schedule trigger actor는 `system:scheduler`다.

`PolicyVersionResponse`는 policy body의 schema/version/prompt/perspective/counterargument/synthesis/candidate/threshold fields와 `content_digest`, `status`, `created_at`, `created_by`, `activated_at`, `activated_by`, `quality_gate_result_id`를 반환한다. `PolicyVersionListResponse`는 items/total/active_policy_version, activation response는 policy/previous active version/quality_gate_result_id/activation_status=`activated`/activated_at이다.

`ScheduleSettingsResponse`는 `timezone`, `daily_time`, `weekly_time`, `prespec_enabled`, `updated_at`, `updated_by`; update는 optional daily/weekly/prespec 중 하나 이상과 required updated_by다. `AlwaysOnSwitchResponse`의 configured/effective/environment flags와 결합 metadata는 configured state와 historical approval 조합을 구분하며, rejection reason은 `environment_disabled`, `approval_unavailable`, `approval_metadata_mismatch` 등 안전한 분류만 반환한다.

목록 모델은 공통으로 `{items,total,limit,offset}` 형태를 사용하고 runtime list의 기본 limit은 50, 범위 1..200, offset은 0 이상이다. legacy notices만 limit 최대 500이다. 날짜·timestamp는 timezone-aware 값이고 계산 불가 수량을 0으로 대체하지 않는다.

## DB·migration 계약

Alembic head는 `0004_migration_audit`이며 앱이 실행하는 migration command는 `cd web/backend && alembic upgrade head`다. migration 순서는 다음과 같다.

| revision | 내용 |
|---|---|
| `0001_existing_schema` | run, notice, judgment, perspective/evidence, counterargument, verification, attachment, portal, review, ingest warning |
| `0002_screening_runtime` | profile snapshot, screening execution/attempt, quality gate/evaluation/review, policy, schedule/always-on/audit 및 immutable/approval trigger |
| `0003_schedule_skipped_recovery` | skipped schedule recovery와 projection disable audit |
| `0004_migration_audit` | deterministic `db.migration` event(`audit-e7854deca36d619ac1921856bb9bdbcd`, actor `system:migration`, target head) |

핵심 runtime row는 `screening_execution`(queue_no, execution_id, trigger/scope/status, source run/notice, requested_by, policy/prompt/model/profile/input/artifact binding, heartbeat/stop/count/publish metadata), `screening_attempt`(stage/status/failure/trace/span/Ollama telemetry), `profile_snapshot`, `quality_gate`, `quality_gate_evaluation`(append-only revision), `quality_gate_review`, `screening_policy`, `schedule_reservation`, `schedule_execution`, `always_on_state`, `audit_event`다.

fresh `alembic upgrade head`는 `schedule_setting(singleton_id=1)`과 `always_on_state(singleton_id=1, enabled=false)` 기본 singleton 및 deterministic `db.migration` audit event를 만든다. `schedule_setting`은 migration 시점의 `BIDOPS_SCHEDULE_DAILY_TIME`, `BIDOPS_SCHEDULE_WEEKLY_TIME`, `BIDOPS_PRESPEC_ENABLED`를 읽고, always-on actor는 `system:migration`이다. `screening_policy`와 legacy `agency_portal`에는 migration/startup seed row가 없으므로 fresh migrated DB에서는 두 table 모두 0행이다. policy는 명시적 `python -m app.screening.policy seed-default --created-by ...`로만, portal은 `POST /api/portals`로만 추가한다. 앱 startup은 `init_db()`에서 revision/schema presence를 읽기 확인할 뿐 migration, `create_all`, portal seed, policy seed를 수행하지 않는다.

`screening_execution.active_slot=1`은 하나만 허용한다. queue claim은 `BEGIN IMMEDIATE`와 bounded busy retry다. profile/policy/evaluation binding은 update trigger로 불변이며, policy active는 하나만 허용한다. schedule reservation PK는 run_key이고 duplicate는 skipped execution이다. DB의 empty/unversioned/stale/integrity failure는 성공 서비스가 아니다.

### 안전한 실패 코드·상태

모델 시도에서 사용하는 `failure_type`은 `timeout`, `truncated_output`, `schema_violation`, `evidence_missing`, `counterargument_repetition`이며, 실행 중단은 `stop_reason=process_interrupted` 또는 요청 actor로 남긴다. schedule preflight 실패는 `ollama_unavailable`로 기록한다. 이 값들은 처리 경로를 고르는 안전한 분류이지, 오류 body의 prompt/profile 내용을 대체하는 상세 로그가 아니다. 공고 실패는 `screening-failures.v1`에 격리하고 성공 subset을 보존한다. full run은 일부 성공이면 `부분 성공`, 유효 판정이 없으면 `실패`, stop이면 `중단됨`이고 새 canonical run을 발행하지 않는다. 알 수 없는 artifact kind는 schema validation 422, 존재하지 않는 execution/artifact는 404다.

## DB admin 명령 계약

```bash
cd web/backend
python -m app.db_admin backup --output <backup.db>
python -m app.db_admin migrate --backup-manifest <backup.db.manifest.json> --confirm-service-stopped
python -m app.db_admin verify
python -m app.screening.policy seed-default --created-by <explicit-actor>
```

backup은 SQLite backup API와 `<backup>.manifest.json`을 만들고 schema `bidops.sqlite-backup.v1`, source/backup path, SHA-256, logical snapshot fingerprint, UTC `created_at`을 저장한다. migrate는 manifest identity/digest/fingerprint와 core counts(`run`, `notice`, `judgment`, `review`, `attachment`), FK/quick_check, exact unversioned baseline을 검사한 뒤 temp copy에 Alembic을 적용하고 검증 후에만 live DB를 바꾼다. manifest를 보존하고 자동 rollback하지 않는다.

container wrapper의 migrate는 `BIDOPS_CONFIRM_SERVICE_STOPPED=true`와 `BIDOPS_BACKUP_MANIFEST`가 모두 필요하다. restore는 운영자가 검증한 backup replacement 결정이며 자동으로 수행하지 않는다. `docker compose down -v`는 이 계약에 없다.

## 환경·CLI 고정값

기본 model `qwen3.8:27b`, endpoint는 host default `http://192.168.0.139:11434`, compose default `http://127.0.0.1:11434`, timeout 180s, keep-alive 30m, context 16384, max output 2048, heartbeat 5s, stale 60s, max concurrency 1, scheduler/daily/weekly/prespec/live false다. `BIDOPS_LIVE_OLLAMA_TEST=true`는 운영자가 명시한 단일 live smoke의 safety marker일 뿐 CLI를 자동 live로 바꾸지 않는다. Docker runtime은 `web/backend/requirements.lock`의 exact pinned transitive closure만 `pip install --requirement`으로 설치하며 range-only `requirements.txt`를 설치하지 않는다.

정확한 stop/backup/migrate/verify/seed/start/health/live 순서는 [운영 절차](./operations.md), 재시도·FIFO·7-span은 [에이전트 런타임](./agent-runtime.md), metric threshold는 [모델 품질 게이트](./model-quality-gate.md)를 따른다.
