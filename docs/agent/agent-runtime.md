# 에이전트 런타임

판정 런타임은 파일 계약으로 입력을 고정하고, 하나의 DB FIFO에서 실행을 claim하며, 일곱 개의 논리 span을 순서대로 수행한다. 현재 구현의 동시성은 전역 1이다. 이 문서는 모델이 사람의 최종 판단을 대신하지 않는다는 전제를 포함한다.

## 입력 동결과 바인딩

오케스트레이터는 `data/screening-executions/<execution_id>/screening-input.json`을 만들고 SHA-256 및 다음을 `screening_execution`에 저장한다.

- `execution_id`는 `scr-` 뒤 32자리 lowercase hex, `queue_no`는 DB FIFO 순번이다.
- trigger는 `cli_single|manual_run|quality_gate|schedule`, scope는 `single_notice|full_run|quality_sample`이다.
- `run_id`, single scope의 `notice_id`, requested actor, 정책·프롬프트 version, 모델명·모델 digest, profile source/version/digest, input/artifact 경로·digest가 필수다.
- 입력은 `bidops.screening-input.v1`, run/window/timezone, candidate count, 정규화 공고, 판정 모드, 정책/prompt/profile identity를 포함한다. profile 전문을 입력 계약에 복사하지 않는다.

프로필 `current`는 working tree snapshot이고 `git:<40hex>`는 승인된 역사 commit only다. 현재 문서의 경로와 digest 검사는 [아키텍처](../ARCHITECTURE.md)의 프로필 절차와 동일하다. fresh migrated DB에는 policy row가 없으므로 명시적 seed 이후에만 실행을 만들 수 있다. 정책 body·prompt·모델 설정이 생성 후 바뀌면 실행과 섞지 않고 새 version을 만든다.

워커는 queue claim 후 input bytes, path hardening, DB binding, 그리고 `screening` 용도 모델 identity를 다시 확인한다. identity 확인은 `GET {base_url}/models`의 served id에 설정 모델명(`BIDOPS_VLLM_SCREENING_MODEL`, 기본 `qwen3.8-27B`)이 있는지 보고, 서버가 `model_revision`을 실어 보내는 경우에만 배포 선언 64-hex revision과 대조한다([ADR-0050](../tracking/decisions/0050-unified-openai-compatible-model-client.md), [ADR-0042](../tracking/decisions/0042-c2-model-revision-declared-at-deployment.md)). 허용 host가 비었거나 선언 revision이 64자 hex가 아니면 **네트워크 호출 전에** fail closed한다. mismatch, missing input, invalid profile/policy도 모델 호출 전에 실패한다.

### Frozen generation configuration

실행 생성 시 `app.core.generation_config`가 유일한 source of truth로 stage-aware 설정을 freeze한다. 기본 canonical JSON은 `num_ctx=16384`, `num_predict.perspective=2048`, `num_predict.counterargument=2048`, `num_predict.synthesis=4096`, `think=false`, `stream=false`이며 SHA-256은 compact UTF-8 JSON(`sort_keys=true`, `separators=(',', ':')`, `ensure_ascii=false`)의 바이트를 해시한다. 이 값과 digest는 `screening_execution`과 `screening-input.v1`에 함께 저장되고 worker/retry가 그대로 사용한다. process env를 enqueue 이후 다시 읽지 않으며 row/input 불일치는 모델 호출 전에 실패한다.

**이름과 digest는 계약에 묶여 있어 바꾸지 않는다.** OpenAI 호환 호출에서 stage별 `num_predict`는 `max_tokens`가 되고, `num_ctx`는 대응 파라미터가 없어 binding 기록에만 남으며, `think=false`는 `extra_body.chat_template_kwargs.enable_thinking=false`가 된다.

각 telemetry line에는 non-secret `generation_config_digest`, 실제 `num_ctx`, `num_predict`가 포함된다. quality gate A/B execution, evaluation, operational activation, always-on/scheduled execution도 동일 digest와 canonical object를 요구한다. 이 기능의 live 재검증은 아직 pending이며 Phase 1 실패 evidence를 성공으로 해석하지 않는다.

### 정책이 허용한 입력 매핑

모델 경계에는 정규화 입력에서 정책이 허용한 필드만 canonical JSON으로 투영한다. `raw_source`와 호출자가 덧붙인 키는 모든 prompt에서 제외한다. `focus_matches`·`performance_matches`·`performance_top_score`는 탐색 신호이지 과업 범위나 법적 실적 자격의 확정값이 아니며, API가 확인하지 못한 값은 `unknown_fields`와 evidence status `unknown`으로 보존한다. profile 전문도 보내지 않고, 정책이 지정한 절만 `company_profile_sections_json`으로 보낸다.

현재 seed policy(`screening-policy.v1.20260825`)의 관점별 allow-list는 다음과 같다. 정책 row가 바뀌면 이 표를 추정해 보정하지 않고 새 policy version의 binding으로 기록한다.

| stage | notice input fields | profile sections | output schema |
|---|---|---|---|
| `기술 적합성` | `title`, `procurement_class`, `focus_matches`, `unknown_fields` | `2.1`, `2.2` | `perspective.v1` |
| `실적 정합성` | `title`, `agency`, `performance_matches`, `performance_top_score` | `2.4` | `perspective.v1` |
| `공공 SI 적합성` | `title`, `agency`, `method`, `procurement_class`, `lifecycle` | `2.3`, `2.4` | `perspective.v1` |
| `사업성·자격 제약` | `budget`, `estimated_price`, `method`, `region_limit`, `qualification_flags`, `lifecycle` | `5.2` | `perspective.v1` |
| `전략 부합` | `title`, `agency`, `procurement_class`, `focus_matches`, `candidate_sources` | `4.1` | `perspective.v1` |
| `counterargument` | projected notice와 다섯 perspective | 없음 | `counterargument.v1` |
| `synthesis` | projected notice와 다섯 perspective 및 counterargument | 없음 | `judgment.v3` |

projected notice의 허용 필드 집합은 `notice_id`, `source_type`, `title`, `agency`, `method`, `url`, `collection_bucket`, `published_at`, `deadline_at`, `budget`, `estimated_price`, `procurement_class`, `region_limit`, `lifecycle`, `qualification_flags`, `attachments`, `focus_matches`, `performance_matches`, `performance_top_score`, `candidate_sources`, `unknown_fields`, `sample_stratum`, `sample_role`이다. 템플릿은 각 placeholder를 정확히 한 번만 받아 canonical JSON으로 한 번에 치환한다. unknown/누락/반복 placeholder나 정책 allow-list 밖 field는 prompt assembly 실패다.

## 단일 FIFO와 슬롯

모든 모델 생성 경로가 동일한 `screening_execution` 테이블에 insert한다. `queue_no ASC`가 유일한 순서이고 전역 `active_slot=1` partial unique index가 마지막 동시성 경쟁을 막는다. `BIDOPS_SCREEN_MAX_CONCURRENCY=1`이 코드와 설정의 고정값이다. 따라서 각 다섯 관점도 병렬이 아니라 순차 호출이다.

claim은 짧은 transaction으로 수행하고 busy retry는 제한된다. SQLite 격리 테스트에서만 `BEGIN IMMEDIATE`를 추가로 건다 — 운영 정본인 PostgreSQL에서는 전역 `active_slot=1` partial unique index가 마지막 경쟁을 막는다. API는 queue row를 만든 뒤 202를 반환한다. CLI `--wait`도 직접 호출하지 않고 FIFO 앞의 작업을 먼저 처리한 뒤 자기 실행의 terminal state를 기다린다.

heartbeat pump는 기본 5초마다 갱신한다. 시작 또는 다음 claim에서 기본 60초보다 오래 heartbeat가 없는 active row는 `중단됨`, `stop_reason=process_interrupted`로 회수하고 slot을 푼다. 새 실행을 자동 생성하거나 중단 위치부터 재개하지 않는다.

## 일곱 span

신규와 재판정은 공고마다 다음 순서다. 모든 호출은 non-thinking·non-streaming이며 `seed=0`, `temperature=0.7`, `top_p=0.8`, `top_k=20`으로 고정된다.

| 순번 | span/stage | 산출물·핵심 검증 |
|---:|---|---|
| 1 | `기술 적합성` | 요구기술·수행 범위와 근거 |
| 2 | `실적 정합성` | 회사 실적과 공고 요구의 source/evidence |
| 3 | `공공 SI 적합성` | 공공·SI 수행 적합성 |
| 4 | `사업성·자격 제약` | 자격·제약·정보 부족을 확정하지 않는 판단 |
| 5 | `전략 부합` | 전략 초점과 근거 |
| 6 | `counterargument` | 반대 근거를 별도 구조화하고 generic/repetition 검사 |
| 7 | `synthesis` | grade/readiness를 독립 검증하는 종합 |

각 perspective는 정확히 한 번씩 있어야 하고 다섯 개 이름은 unique다. evidence는 source, status, fact를 가져야 한다. 근거 위치가 확인되지 않은 주장을 확정값으로 만들지 않는다. `grade`는 `우선 검토|검토 권장|관찰 대상|제외`, readiness는 `확인 완료|부분 확인 필요|참여 불가 확인|해당 없음` enum이다.

## 호출 출력 계약

모델은 단계에 맞는 JSON object 하나만 반환한다. JSON 앞뒤 Markdown/설명, 알 수 없는 키, 중복 JSON key는 성공 출력이 아니다. validator는 값을 채우거나 보정하지 않고 원래 응답을 버린다.

### 관점과 반론

`perspective.v1`의 exact top-level keys는 `name`, `assessment`, `reason`, `evidence`다. `name`은 호출 stage와 정확히 같고, `assessment`는 `적합|부분 적합|부적합|확인 불가`, `reason`은 10자 이상, `evidence`는 하나 이상이다. evidence item의 exact keys는 `source`, `status`, `fact`이고 status는 `confirmed|inferred|unknown`, source/fact는 빈 문자열일 수 없다.

`counterargument.v1`의 exact top-level key는 `counterarguments` 하나이며 공백 아닌 문자열을 하나 이상 가진다. 정규화한 빈 항목·중복·토큰 Jaccard 0.8 이상 반복·generic boilerplate는 `counterargument_repetition`으로 거부한다. 반론은 공고와 다섯 관점에 구체적으로 연결되어야 한다.

### 종합 판정

`judgment.v3`의 exact top-level keys는 `notice_id`, `grade`, `readiness`, `primary_focus`, `exclusion_category`, `summary`, `perspectives`, `matched_performances`, `counterarguments`, `counterargument_resolutions`, `verification_items`, `next_action`이다. `notice_id`는 입력 공고와 정확히 일치하고 perspectives는 다섯 관점의 unique set을 정확히 한 번씩 가진다. `primary_focus`는 `AI/데이터|블록체인·DID|공공 SI·통합관리|해당 없음`, exclusion은 null 또는 `도메인 불일치|시설·현장 용역|공사·인프라|행사·교육·홍보|연구·조사|감리·평가|물품·임차|자격 미달|취소·종료|기타 비관련`이다.

`matched_performances` item은 `name`, `match_reason`, `mismatch_or_limit`, `source`, `status`를 정확히 가지며 status는 evidence status와 같다. 입력 `performance_matches`가 비어 있지 않으면 이 배열도 비어 있을 수 없다. `counterargument_resolutions`는 counterarguments와 같은 순서·길이이며 item의 exact keys는 `counterargument`, `status`, `reflection`, status는 `수용|기각|추가 확인`이다. `verification_items` item의 exact keys는 `item`, `why`, `blocking`, `status`, `requires_attachment`; blocking/requires_attachment는 boolean, status는 `미확인|확인 완료`다.

교차 검증은 `부분 확인 필요`에 verification item 하나 이상, `확인 완료`에 blocking인 미확인 item 없음, `참여 불가 확인`에 blocking item 하나 이상을 요구한다. `사업성·자격 제약=확인 불가`와 종합 grade `관찰 대상|제외` 조합은 `two_axis_mixing_flag=true`, label `확인 요망`을 붙이는 표시일 뿐 실패·재시도·자동 등급 변경이 아니다.

승계는 이전 완료 판정에 대한 deterministic carry-over validation만 수행하며 모델 span을 호출하지 않는다. 검증 실패는 `병합·검증`의 `carried_over_validation` stage로 기록한다. 승계 결과는 원 판정의 최초 생성 회차·model/prompt/policy binding을 보존한다.

## 호출·재시도·실패

`POST {base_url}/chat/completions`의 전체 시도 수는 stage당 최대 2회다. 호출당 timeout은 300초, 응답 상한은 4 MiB다. 같은 trace 아래 새 span을 만들고, 앞선 실패 attempt와 그 telemetry를 삭제하지 않는다.

| failure type | retry |
|---|---|
| `timeout`, `truncated_output` | 같은 frozen prompt와 같은 생성 설정으로 최대 한 번 재시도. 응답이 상한을 넘는 경우도 `truncated_output`으로 분류한다 |
| `schema_violation`, `evidence_missing` | 거부된 response body를 넣지 않는 안전한 correction prompt로 최대 한 번 재시도 |
| `counterargument_repetition` | retry하지 않고 공고 실패로 격리 |

모델 identity 조회(`GET {base_url}/models`)의 transport/mismatch 실패는 preflight 오류이며 model-call retry로 바꾸지 않는다. 안전한 분류는 `model_not_served`, `model_revision_invalid`, `identity_unavailable` 셋이다. schema/evidence correction도 입력·스키마를 다시 제시할 뿐 값을 자동 보정하거나 두 응답을 이어 붙이지 않는다. 모든 attempt telemetry는 남기되 prompt·response body·profile 전문과 비밀은 오류·로그에 남기지 않는다.

실패한 공고는 `screening-failures.json`의 exact top-level `schema_version`, `execution_id`, `run_id`, `generated_at`, `failure_count`, `failures` 아래에 남긴다. failure item의 exact keys는 `notice_id`, `failed_stage`, `failure_type`, `last_attempt_at`, `retry_count`, `status`, `failure_context`, `trace_id`, `span_id`, `error_summary`다. 모델 단계 실패에는 trace/span을 연결하고 `병합·검증` 또는 승계 검증 실패에는 null을 허용한다. `error_summary`는 허용된 안전 분류만 가지며 원문·prompt·profile·secret을 포함하지 않는다. 실패 공고의 상태는 `사람 검토 대기`이고 성공 subset은 보존한다.

- full run에서 일부 공고가 성공하면 `부분 성공`; 하나도 유효하지 않으면 `실패`다.
- 중지 요청이 blocking HTTP 호출 중이면 호출이 끝난 직후 다음 단계 전에 `중단됨`으로 전이한다. 중단 결과는 publish하지 않는다.
- deterministic validator는 값을 보정하거나 grade/readiness를 자동 변경하지 않는다.
- `사업성·자격 제약=확인 불가`이고 종합 grade가 `관찰 대상` 또는 `제외`인 경우 `two_axis_mixing_flag=true`, label `확인 요망`을 남긴다. grade는 그대로이고 사람 검토 대상이다.

## 산출물과 발행

execution artifact directory에는 다음 파일만 알려진 계약으로 취급한다.

| 파일 | schema | 역할 |
|---|---|---|
| `screening-input.json` | `bidops.screening-input.v1` | frozen input |
| `screening-decisions.json` | `bidops.decisions.v3` | 성공 판정 |
| `screening-failures.json` | `bidops.screening-failures.v1` | 공고별 실패 |
| `screening-telemetry.jsonl` | `bidops.screening-telemetry.v1` | 호출 시도 메타데이터 |
| `screening-results.json` | `bidops.screening.v3` | 결정적 병합 결과. execution artifact에서 검증·작성한 뒤 derived run에 publish |

실행 디렉터리에서 known artifact는 `screening-input.json`, `screening-decisions.json`, `screening-failures.json`(실패 시), `screening-telemetry.jsonl`, 그리고 검증 전 임시로 작성되는 `screening-results.json`이다. 성공 attempt의 제한 JSON만 `responses/<sha256(notice_id)[:16]>/<stage>-<attempt>.json`에 보관하고 실패 response body는 보관하지 않는다. 파일과 디렉터리는 UTF-8, immutable-after-publish, symlink/path escape 검사 대상이다. API artifact endpoint는 `decisions|failures|telemetry|screening_result` known kind만 허용하고 내부 path를 소비자에게 위임하지 않는다.

`screening-results.json`의 v3 top-level exact keys는 `schema_version`, `execution_id`, `generated_at`, `screening_basis`, `source_window`, `model_name`, `model_digest`, `prompt_version`, `policy_version`, `company_profile_version`, `company_profile_digest`, `generation_config`, `generation_config_digest`, `candidate_count`, `result_count`, `failure_count`, `partial_artifact`, `failure_artifact`, `results`다. input/decision/failure binding과 model identity가 모두 맞을 때만 publish한다. 일부 공고가 실패하면 성공 result subset과 failure artifact를 함께 보존하고 `partial_artifact=true`; 전역 merge/validation 실패는 성공 결과로 publish하지 않는다.

`screening-telemetry.jsonl`의 각 line은 위 필드와 `generation_config_digest`, `num_ctx`, `num_predict`를 가진다. provider가 주지 않은 token/duration은 0으로 만들지 않고 null로 남긴다. **OpenAI 호환 응답에는 서버 측 소요 시간 계측이 없으므로 `prompt_eval_duration_ns`·`eval_duration_ns`·`load_duration_ns`·`total_duration_ns` 네 값은 항상 null이다** — client 측 경과 시간으로 채우면 과거 회차의 계측과 뜻이 다른 숫자가 같은 열에 섞인다. token 수는 `usage.*`에서, `done_reason`은 `finish_reason`에서 온다. telemetry에는 model/prompt/policy/profile 원문이나 API key를 넣지 않으며 execution/DB binding은 별도로 보존한다.

full run의 성공·부분 성공 처리에서는 원 `data/runs/<source>`를 읽기만 하고 새 이름에 source provenance, current screening artifacts, `screening-replacement-provenance.json`을 복사한다. 원 회차의 reviews/files/judgments는 변경하지 않는다. single notice와 quality sample은 execution artifact와 DB gate evidence로만 남는다.

## CLI와 API 진입점

재현 가능한 single notice 명령은 다음이다.

```bash
cd web/backend
python -m app.screening.cli run-one \
  --run-id <run_id> --notice-id <notice_id> \
  --policy-version screening-policy.v1.20260825 \
  --profile-source current --requested-by <actor> [--wait]
```

수집·표본·병합·보고서 skill subprocess 한 단계의 상한은 상수 **300초**이며 모델 설정에서 오지 않는다 — 이 단계들은 모델을 부르지 않는다. 모델 호출당 timeout(같은 300초)과는 별개 값이다.

CLI는 profile/model/digest와 artifact 경로·상태 메타데이터만 출력한다. exit code는 성공 0, 부분 성공 2, 실패·중단·입력 오류 1이다. prompt, profile 전문, API key를 출력하지 않는다.

`POST /api/runs/{run_id}/pipeline/judgment`는 동일한 queue로 enqueue하고 202를 반환한다. 모델 preflight 실패는 queue row를 만들기 전에 503이다. `POST /api/screening/executions/{execution_id}/stop`은 actor를 audit attribution으로 저장하며 인증을 제공하지 않는다. queued stop은 즉시 terminal `중단됨`, running stop은 `중지 요청`, terminal stop은 409다.

Quality gate가 만드는 두 pass도 각각 독립적인 `quality_sample` execution이며 같은 fixed input/identity를 사용한다. A/B와 review/evaluation revision은 [모델 품질 게이트](../model-quality-gate.md)를 참조한다.

## 운영 불변식

1. model은 `BIDOPS_VLLM_SCREENING_MODEL`이 정한 정확한 served id(기본 `qwen3.8-27B`)다. endpoint 불가·identity mismatch는 실패이며 hosted OpenAI fallback이 아니다. **이 이름이 이전 태그 형식(`qwen3.8:27b`)에서 바뀌었으므로 옛 이름으로 기록된 기존 실행·판정 row는 carry-over·재판정 검증과 enqueue에서 거부된다**([findings](../tracking/findings.md)).
2. 정책·prompt·model·profile·input/artifact digest는 실행 생성 후 바뀌지 않는다.
3. FIFO, active slot 1, bounded retry, heartbeat recovery는 수동·스케줄·quality trigger에 공통이다.
4. 실패·부분 성공·중단의 사실과 성공 subset을 보존하며 자동 재개·자동 등급 보정·자동 발행을 하지 않는다.
5. 스케줄 catch-up/recovery와 DB migration/seed는 별도 운영 계약이다. 정확한 명령은 [운영 절차](../operations.md), REST·파일·DB status/error는 [외부 인터페이스 계약](../contracts.md)에 있다.

모델 실행의 `generation_config` JSON과 digest는 execution artifact, DB
projection, quality gate/evaluation, schedule/always-on response에서 동일한
canonical object로 검증·노출한다. 환경 drift는 model inspection,
reservation, queue row보다 먼저 fail closed하며 legacy all-2048 digest를 새
예약의 승인으로 승격하지 않는다. 이 경계는 아직 live 재검증되지 않았고
Phase 1 synthesis truncation 실패 evidence를 성공으로 바꾸지 않는다.
