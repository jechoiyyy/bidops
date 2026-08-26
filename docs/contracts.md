# 외부 인터페이스·파일·DB 계약

이 문서는 현재 FastAPI router, Pydantic schema, 파일 writer, SQLAlchemy model과 Alembic migration이 실제로 제공하는 계약을 요약한다. JSON은 UTF-8이다. 날짜·시각은 timezone을 포함한 ISO 8601을 사용하고 확인 불가 값은 `null`/`unknown`을 보존한다.

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
| `GET /api/reviews?run_id=...` | DB 정본 review |
| `PUT /api/notices/{notice_pk}/review` | review body 전체 교체; 확인 답변은 누락 시 기존 배열을 삭제 |
| `GET /api/reviews/export?run_id=...` | `application/yaml`, `bidops.feedback.v2` |
| `GET /api/metrics/validation?run_id=...` | 계산 가능한 validation 지표와 미측정/계산 불가 상태 |

프로필·기관 포털의 읽기/관리 경계도 API에만 있다. `GET /api/profile/snapshots`, `/api/profile/sections`, `/api/profile/unknowns`는 snapshot/tree/unknown 보존 정보를 반환한다. `GET /api/portals`, `POST /api/portals`, `PATCH /api/portals/{portal_id}`는 기관 portal metadata를 관리한다. `GET /api/attachments/queue?run_id=...`는 첨부가 없는 공고의 작업 목록을 반환한다.

첨부는 `GET /api/notices/{notice_pk}/attachments`, multipart `POST /api/notices/{notice_pk}/attachments`(HWP/HWPX/PDF, 50MB 이하), `DELETE /api/attachments/{attachment_id}`(수동 첨부만), `GET /api/attachments/{attachment_id}/download`(PDF 또는 octet-stream)이다. 내부 `stored_path`를 조합하지 말고 API URL만 사용한다. 제공 첨부 삭제는 403이다.

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
| `GET /api/schedule/settings` | Asia/Seoul, daily/weekly time, prespec, effective state |
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

`screening-input.v1`은 `schema_version`, `run_id`, `generated_at`, `source_window{from,to,timezone}`, `candidate_count`, `notices[]`를 갖는다. notice는 normalized fields와 `judgment_mode`(`신규|재판정|승계`), 승계의 `carry_over_from`, 재판정의 `rejudge_reason`을 가진다. 신규/재판정은 일곱 span 대상, 승계는 모델 호출 없음이다.

`decisions.v3`는 model/prompt/policy/profile identity, `judged_in_run`, `recorded_in_run`, `carried_over`, `rejudge_reason`, `two_axis_mixing_flag/label`, grade/readiness, 다섯 perspective, evidence, counterargument, verification items를 가진다. 승계는 원 binding/최초 회차를 보존하며 신규처럼 기록하지 않는다.

## DB·migration 계약

Alembic head는 `0004_migration_audit`이며 앱이 실행하는 migration command는 `cd web/backend && alembic upgrade head`다. migration 순서는 다음과 같다.

| revision | 내용 |
|---|---|
| `0001_existing_schema` | run, notice, judgment, perspective/evidence, counterargument, verification, attachment, portal, review, ingest warning |
| `0002_screening_runtime` | profile snapshot, screening execution/attempt, quality gate/evaluation/review, policy, schedule/always-on/audit 및 immutable/approval trigger |
| `0003_schedule_skipped_recovery` | skipped schedule recovery와 projection disable audit |
| `0004_migration_audit` | deterministic `db.migration` event(`audit-e7854deca36d619ac1921856bb9bdbcd`, actor `system:migration`, target head) |

핵심 runtime row는 `screening_execution`(queue_no, execution_id, trigger/scope/status, source run/notice, requested_by, policy/prompt/model/profile/input/artifact binding, heartbeat/stop/count/publish metadata), `screening_attempt`(stage/status/failure/trace/span/Ollama telemetry), `profile_snapshot`, `quality_gate`, `quality_gate_evaluation`(append-only revision), `quality_gate_review`, `screening_policy`, `schedule_reservation`, `schedule_execution`, `always_on_state`, `audit_event`다.

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

기본 model `qwen3.8:27b`, endpoint는 host default `http://192.168.0.139:11434`, compose default `http://127.0.0.1:11434`, timeout 180s, keep-alive 30m, context 16384, max output 2048, heartbeat 5s, stale 60s, max concurrency 1, scheduler/daily/weekly/prespec/live false다. `BIDOPS_LIVE_OLLAMA_TEST=true`는 운영자가 명시한 단일 live smoke의 safety marker일 뿐 CLI를 자동 live로 바꾸지 않는다.

정확한 stop/backup/migrate/verify/seed/start/health/live 순서는 [운영 절차](./operations.md), 재시도·FIFO·7-span은 [에이전트 런타임](./agent-runtime.md), metric threshold는 [모델 품질 게이트](./model-quality-gate.md)를 따른다.
