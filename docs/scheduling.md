# 스케줄링

스케줄러는 시간을 감지하고 영속 예약을 만드는 역할만 한다. 실제 수집·표본·판정·병합·보고는 [에이전트 런타임](./agent-runtime.md)의 동일한 FIFO worker가 수행한다. 기본값은 scheduler와 always-on 모두 false다.

## 시계와 스위치

- APScheduler `3.11.x`(`APScheduler>=3.11.3,<4`) in-process scheduler다.
- 시간대는 코드에 고정된 `Asia/Seoul`이다. 기본 daily 시각은 `02:00`, weekly 시각은 월요일 `06:00`이다.
- `BIDOPS_SCHEDULER_ENABLED=true`일 때만 web lifespan이 APScheduler job을 등록한다. false면 job을 등록하지 않지만 worker와 수동 queue는 동작한다.
- `BIDOPS_SCHEDULE_DAILY_TIME`, `BIDOPS_SCHEDULE_WEEKLY_TIME`, `BIDOPS_PRESPEC_ENABLED`는 최초 DB row의 기본값을 제공한다. DB 설정 row가 있으면 실행 중 환경 변경으로 기존 설정을 덮지 않는다.
- `PATCH /api/schedule/settings`는 DB singleton을 바꾸고 즉시 job을 재예약한다. 이미 만들어진 reservation은 변경하지 않는다.

fresh migration은 schedule settings와 disabled always-on singleton 및 deterministic migration audit event를 만들고 policy/portal row는 만들지 않는다. 따라서 active policy가 없으면 scheduler callback은 effective enabled가 될 수 없고, portal 검색도 별도 API 등록 전에는 매칭되지 않는다. startup은 이 seed를 수행하지 않는다.

상시 실행의 유효 조건은 `BIDOPS_SCHEDULER_ENABLED=true`, DB `always_on_state.enabled=true`, active policy, 최신 passing `operational_approval`, 그리고 그 평가의 current profile·정확한 model/prompt/policy binding이다. 환경 cap 또는 binding 불일치가 있으면 DB switch를 false로 내리고 audit한다. DB switch가 false면 scheduler job이 등록되어도 callback은 no-op이며 reservation·model call을 만들지 않는다. always-on PUT을 환경 false에서 true로 요청하면 409다.

추가로 operational approval의 generation config digest와 A/B execution/evaluation digest가 모두 일치해야 한다. enable 시 현재 process settings의 canonical digest를 approval digest와 비교하고, enable 이후 env가 바뀌면 scheduled judgment가 reservation digest와 현재 settings를 비교해 `generation_config_mismatch`로 fail-closed한다. mismatch 상태에서는 model call, activation 또는 예약 실행을 허용하지 않는다. 이 binding 구현은 아직 live 재검증 전이다.

## 예약 키와 기간

`schedule_reservation`은 `run_key`를 primary key로 사용하고 window from/to, job kind, timezone을 보존한다. 예약이 callback보다 먼저 생성되므로 process crash 뒤 callback이 재실행되어도 중복 작업을 만들지 않는다.

| 작업 | 기본 실행 시각 | `run_key` | 대상 기간 |
|---|---|---|---|
| daily | 매일 02:00 | `YYYYMMDD-YYYYMMDD` | 서울 기준 전일 하루 |
| weekly | 월요일 06:00 | `weekly:YYYYMMDD-YYYYMMDD` | 직전 월요일–일요일 |

daily callback은 effective always-on 확인 후 전일 reservation을 만들고 `collect → sample → judgment enqueue → merge/load → report`를 수행한다. weekly callback은 각 calendar date의 최신 valid completed daily execution을 사용해 주간 보고를 만든다. 7개 날짜가 채워지지 않으면 `부분 성공`이다.

동일 `run_key`의 reservation이 이미 있으면 새 `schedule_execution`을 `건너뜀`, `skip_reason=duplicate_reservation`으로 남기고 audit한다. 기존 winner의 상태를 바꾸지 않는다. 실행 상태는 `예약`, `실행 중`, `성공`, `부분 성공`, `실패`, `건너뜀`이다. actor는 `system:scheduler`다.

## 시작·재기동 catch-up

모든 catch-up은 예약을 먼저 만들고 oldest target date 순으로 실행을 queue한다.

### 최초 enable

`first_enable=true`일 때 현재 서울 시간이 daily 설정 시각 이상이면 전일을 한 번 예약한다. 월요일이고 weekly 설정 시각 이상이면 직전 월–일 주간도 한 번 예약한다. 이 판단은 callback 시각을 다시 계산해 기간을 바꾸지 않는다.

### 재기동

`first_enable=false`이면:

1. existing daily reservation의 마지막 target date를 기준으로 그 다음 날부터 전일까지 누락된 날짜를 하나씩 예약한다.
2. 기존 daily reservation이 하나도 없으면 daily 날짜를 추정하여 채우지 않는다.
3. 기존 failed/partial reservation은 자동 retry하지 않는다.
4. 직전 주간 reservation이 없으면 이전 월–일 주간 하나를 예약한다.

예약 행이 이미 있으면 실행을 새로 만들지 않는다. 수동 recovery는 failed/partial/skipped에만 허용하며 새 execution ID와 `recovery_of` 관계를 만든다. 기존 execution을 in-place retry하거나 과거 로그를 덮어쓰지 않는다.

## 모델 preflight와 실패

schedule enqueue 전 Ollama endpoint 및 exact model/digest preflight를 한다. 실패하면 빈 screening input이나 fallback을 만들지 않고 schedule execution을 실패 사유 `ollama_unavailable`로 남긴다. worker가 실행 중 다시 identity를 검사하며 mismatch도 실패다. OpenAI 호출은 존재하지 않는다.

수집기·표본기·판정·보고 중 한 단계가 실패해도 schedule row에는 정확한 status와 안전한 요약 오류만 남긴다. prompt/profile 원문·API key는 log/audit에 기록하지 않는다. 판정의 공고별 실패와 성공 subset은 [에이전트 런타임](./agent-runtime.md)의 `부분 성공` 규칙을 따른다.

## API·감사

| 호출 | 의미 |
|---|---|
| `GET /api/schedule/settings` | timezone·daily/weekly time·prespec·update metadata 조회 |
| `PATCH /api/schedule/settings` | DB singleton 갱신 및 job 즉시 reschedule |
| `GET /api/schedule/executions` | 상태·job kind·기간·recovery 관계 조회 |
| `POST /api/schedule/executions` | 수동 예약/복구. job kind/window/requested_by를 받고 202 |
| `GET /api/schedule/always-on` | DB switch, environment cap, gate/policy binding 상태 조회 |
| `PUT /api/schedule/always-on` | actor를 요구하는 명시적 switch 변경. true에는 passing evaluation ID도 필요 |

예약 winner/duplicate/recovery/always-on mismatch는 audit event로 남는다. requester/actor는 현재 인증이 아니라 attribution이며, API는 별도 인증을 제공하지 않는다. gate evaluation이 없는 true 요청, wrong purpose/profile/model binding, environment disabled는 409다.

## 운영 경계

DB row seed·policy activation·always-on enable은 startup/scheduler callback이 하지 않는다. T14/T15에서는 operator direction 없이는 수행하지 않는다. 스케줄을 켜기 전 [모델 품질 게이트](./model-quality-gate.md)의 operational approval을 확인하고, 실제 DB·컨테이너 시작/중지·backup 순서는 [운영 절차](./operations.md)를 그대로 따른다.
