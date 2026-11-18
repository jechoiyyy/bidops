# 2026-11-18 발주계획 일일 트랙 보강 배포와 감독 시운전 (`d73182c`)

- 승인: 2026-11-18 사용자가 [설계 고도화안](../../1118_launch-hardening/설계고도화안.md) §7의 항목 중 **cron 설치를 뺀** commit·main 병합, 운영 이미지 빌드·재배포, analysis-worker 기동, 감독 시운전(실제 C-2 호출), 수집 공백 따라잡기 최근 14일을 승인했다. origin push, migration, policy 변경, RL·개요 활성화, Luna 전송은 범위 밖이다.
- 대상: compose 프로젝트 `bidops`, 작업 트리 `/Users/temp/orca/bidops`(main).

## 반영 전 상태

| 항목 | 값 |
|---|---|
| 코드·이미지 | main `6c9605a`, `bidops:main-20261118`(amd64, `3fb99764…`) — 롤백용 보존 |
| Alembic | `0042_engine_run` |
| C-2 | `c2-order-plan-screening-v5`(`1e6d4ef1…`) 활성, 일일 스위치 ON |
| 수집 | cron 0행, 마지막 회차 2026-10-14 |
| worker | analysis-worker `Exited (137)`, 상태 서비스 restart 정책 `no` |

## 단계와 결과

| 단계 | 결과 |
|---|---|
| 1 병합 | `fix/order-plan-daily-hardening`(`80a47a1`)을 main에 `--no-ff` 병합(`d73182c`). push 없음. 롤백 태그 `before-launch-hardening-20261118` = `6c9605a` |
| 2 백업 | owner `pg_dump -Fc`: `backups/postgres/full/bidops-20261118T033636Z.dump`(59,828,499 B, sha256 `6692b3fa926088f32314c9141c7b3a6caf53d380f350db630e9c36124ad1d7c6`, `pg_restore --list` TABLE DATA 111). 운영 `.env` 사본 `backups/env-prod-before-launch-hardening-20261118`(0600). 객체 저장소는 이번 변경이 건드리지 않아 따로 받지 않았다 |
| 3 이미지 | `.env`의 `BIDOPS_IMAGE`를 `bidops:main-20261118b`로 바꾸고 `BIDOPS_ENV=prod scripts/compose.sh build web`(exit 0, amd64, `e66457ca…`). 문서 worker 이미지는 그대로다. migration 없음 |
| 4 web 교체 | `up -d --no-deps --no-build --force-recreate web`. healthy, 재시작 0. `/api/health`·`/api/runs`·`/api/opportunities`·`/api/order-plan-screening/policies`·`daily-trigger` 200. daily-trigger는 반영 전과 같다(v5 `1e6d4ef1…`, switch ON, reasons 없음) |
| 5 재시작 정책 | `docker update --restart unless-stopped`로 postgres·minio·clamav·document-worker 2개에 적용했다(컨테이너 재생성 없음, DB 중단 없음). compose 파일(prod overlay)과 같은 값이다. 다음에 이 서비스들을 `up`하면 구성 hash가 달라 다시 만들어질 수 있다 |
| 6 analysis-worker | 기동 전 모든 대기열을 읽기 전용으로 확인했다: C-2 실행 16건·개요 run 137건·`work_job` 137건 모두 종결 상태, 심층·엔진·회사 핏·제안서 행 0. `up -d --no-deps --no-build analysis-worker`로 새 이미지에서 기동. env: `BIDOPS_C2_EXECUTION_ALLOWED=true`, 개요·회사 핏·OpenAI `false`, GPU 600초 사용·300초 휴지. restart 정책은 `no`(의도) |
| 7 dry-run | `env -i HOME=… PATH=<gnubin:OrbStack:homebrew:…>`에서 `--track order-plans --dry-run` exit 0 |
| 8 감독 시운전 | 아래 |
| 9 따라잡기 | 아래 |

## 감독 시운전 (기준일 2026-11-17)

`flock -n ~/.local/state/bidops/plans.lock timeout 3h ./scripts/run-daily-lifecycle.sh --track order-plans --date 2026-11-17`, `BIDOPS_DAILY_GAP_FLOOR_DATE=2026-11-17`, actor `jechoi`. 로그 `~/.local/state/bidops/logs/trial-plans-20261117.log`.

| 항목 | 값 |
|---|---|
| 회차 | `lifecycle-20261117-plans--20261118T033926.070325Z`, 수집 559건, 적재 경고 0 |
| 실행 | `252e1ce7-37a2-428c-bd23-14dc8981d993`, trigger `daily_script`, attempt 1, `성공`, 03:40:05Z~03:58:43Z(약 19분) |
| 1단계 | 선택 300 / 탈락 259 / 실패 0 |
| 2단계 | 관련 48 / 비관련 193 / 불확실 59 / 실패 0 / 거부 0 |
| 사람 검토 후보 | 107건 |
| 감사 표본 | 10건 |
| 누락일 감지 | `no gap`(floor 2026-11-17) |
| 종료 코드 | 0 |

- 사람 검토 후보 107건은 PoC 게이트의 하루 검토량 임계(80)를 넘는다. 게이트 gold의 하루 모집단은 290~308건이었고 이 날은 559건이다. BM25 Top300이 잘라 낸 259건은 모델 판정을 받지 않았으며, 이 규모에서의 누락은 측정되지 않았다.
- 이 실행은 일일 스크립트가 실제 스택에서 수집→적재→정규 run id 조회→실행 생성→폴링→감사 표본→누락일 감지를 끝까지 지난다는 증거다. v5의 품질을 새로 증명하지 않는다.

## 따라잡기 (2026-11-04 ~ 2026-11-16)

`--from-date 2026-11-04 --to-date 2026-11-16`, `BIDOPS_DAILY_GAP_FLOOR_DATE=2026-11-04`, `timeout 12h`. 로그 `~/.local/state/bidops/logs/catchup-plans-20261104-20261116.log`. 세 번에 걸쳐 끝났고 결과는 아래 2차·3차 표에 있다.

### 1차 시도 중단 (04:25Z, exit 2)

- 첫날 11-04(수집 469건) 실행 `887e0aba-898f-422a-8d5d-6afe69e90e5f`가 `실행 중`일 때 폴링 `GET …/executions/<id>`가 31초 타임아웃(`curl: (28)`)으로 실패했고, 스크립트가 이를 치명 오류로 보고 범위 전체를 멈췄다.
- 원인: 같은 Mac에서 병행하던 UI 작업의 Playwright 검사로 host load average가 232까지 올랐다(16코어). web healthcheck가 5초 제한을 넘겨 `unhealthy`가 됐고(재시작 0), 모델 배치 하나가 실패 뒤 재시도됐으며 다음 배치도 평소 40~90초보다 오래 걸렸다. 운영 제품 결함이 아니라 실행 환경 부하다.
- 실행 자체는 워커에서 계속 진행됐다. 운영 DB·회차 원본에는 손대지 않았다.
- 조치: UI 검사를 한 번에 하나·worker 2개로 제한했다. 스크립트는 폴링 조회의 일시 실패를 상한까지 재시도하도록 고치고, 성공 실행의 감사 표본 누락도 누락 감지가 잡게 한다(구현 중). 11-04 실행이 끝난 뒤 같은 범위를 이어서 돌린다.

### 2차 실행 (보강된 스크립트, main `d3c962f`)

| 기준일 | 수집 | 실행 | 관련 / 불확실 / 실패 | 검토 후보 |
|---|---:|---|---|---:|
| 11-04 | 469 | `887e0aba…` `부분 성공`(1차 시도 때의 실행) | 63 / 40 / 25 | 128 |
| 11-05 | 459 | `942eb77c…` `성공` | 42 / 64 / 0 | 106 |
| 11-06 | 427 | `3ea3ee70…` `성공` | 55 / 40 / 0 | 95 |
| 11-07 | 21 | `33f6308a…` `성공` | 1 / 3 / 0 | 4 |

- 11-04는 `부분 성공`이 이미 있어 새 실행 없이 감사 표본 10건만 뽑았다(`already_executed`). 모델 판정이 없는 25건은 제품 규칙대로 사람 검토 후보에 들어간다. `부분 성공`은 완료로 세므로 `--extra-attempt`로도 다시 실행되지 않는다.

### host 재시작 (14:47~14:53 KST)과 복구

- 11-08(수집 24건) 실행 `5f5cda00-c866-4fd1-abc9-a610317f3ab1`이 시작된 직후(heartbeat 05:47:14Z) Mac이 재시작됐다(`kern.boottime` 14:53 KST, OrbStack 기동 15:44 KST). 따라잡기 스크립트는 그때 죽었고 exit 줄을 남기지 못했다. 재시작 원인은 확인하지 못했다.
- **상태 서비스 자동 기동(A-4)**: OrbStack이 올라오자 postgres·minio·clamav·document-worker 2개·web이 사람 손 없이 다시 떴다(`unless-stopped`, 재시작 횟수 0, `/api/health` 200). analysis-worker는 의도대로 `Exited (255)`로 남았다. 10-28 재시작 때 3주간 멈췄던 것과 대조되는 실제 환경 증거다.
- **멈춘 `실행 중` 회수**: 사람 확인 뒤 analysis-worker를 다시 올리자 첫 claim에서 위 실행을 `중단됨`·`stale_execution`으로 닫았다(06:47:52Z). 이는 기존 회수 경로이며 이번에 추가한 `대기` 회수(`stale_queued`)는 아니다.
- 로컬 Ollama(`qwen3.8:27b-ctx32k`)와 LiteLLM은 재시작 뒤 응답했다.
- 3차 실행: `--from-date 2026-11-08 --to-date 2026-11-16`을 세션과 분리된 프로세스(`nohup`)로 15:48 KST에 재개했다. 11-08은 `중단됨`만 있으므로 600초 대기 뒤 attempt 2로 다시 실행됐다.

### 3차 실행 결과 (15:48~18:07 KST, exit 0)

로그 `~/.local/state/bidops/logs/catchup-plans-2026-11-08-2026-11-16-1548.log`. 마지막 줄은 `gap check: no gap for order-plans in 2026-11-04..2026-11-16 (floor 2026-11-04)`와 `exit=0`이다.

| 기준일 | 수집 | 실행 | 1단계 선택 / 탈락 | 관련 / 불확실 / 실패 | 검토 후보 | 감사 표본 |
|---|---:|---|---|---|---:|---|
| 11-08 | 24 | `3ada5e2f…` `성공`(attempt 2) | 24 / 0 | 1 / 2 / 0 | 3 | 해당 없음(Top-K 이하) |
| 11-09 | 503 | `7119a9aa…` `성공` | 300 / 203 | 64 / 45 / 0 | 109 | 10 |
| 11-10 | 512 | `b412d799…` `성공` | 300 / 212 | 40 / 46 / 0 | 86 | 10 |
| 11-11 | 485 | `51613e0e…` `성공` | 300 / 185 | 44 / 36 / 0 | 80 | 10 |
| 11-12 | 563 | `e9e4e405…` `성공` | 300 / 263 | 61 / 48 / 0 | 109 | 10 |
| 11-13 | 577 | `0fd6ca1f…` `성공` | 300 / 277 | 45 / 52 / 0 | 97 | 10 |
| 11-14 | 33 | `a400197d…` `성공` | 33 / 0 | 1 / 2 / 0 | 3 | 해당 없음(Top-K 이하) |
| 11-15 | 39 | `fe136785…` `성공` | 39 / 0 | 2 / 5 / 0 | 7 | 해당 없음(Top-K 이하) |
| 11-16 | 627 | `ce82eae5…` `성공` | 300 / 327 | 50 / 41 / 0 | 91 | 10 |

- 11-04~11-17 14일 모두 `성공` 또는 `부분 성공`으로 끝났다. 실행 31건 중 운영(`operational`) 22건은 `성공` 20·`부분 성공` 1(11-04)·`중단됨` 1(재시작 때의 11-08 1차)이고, 나머지 9건은 10월의 게이트 측정 실행이다.
- 평일 10일의 검토 후보는 80~128건이고 9일이 PoC 임계 80을 넘는다(11-11만 80). 평일 수집은 427~627건으로 게이트 gold의 하루 모집단(290~308건)보다 크고, BM25 Top300이 잘라 낸 127~327건은 모델 판정을 받지 않았다. 이 규모에서의 누락은 측정되지 않았다.
- 폴링 읽기 재시도(`poll read failed`)는 3차 실행 로그에 한 번도 찍히지 않았다. 재시도 경로는 실제 스택에서 지나가지 않았다.

## cron 차단 수정 병합과 이미지 맞춤 (18:08~18:10 KST, main `c801a69`)

- 따라잡기가 끝난 뒤 `fix/order-plan-daily-hardening`의 `d1ce3ae`(공고 `not_ingested` 감지·따라잡기, 모든 읽기 GET 재시도, cron 진입점 `scripts/cron-daily-track.sh`)를 main에 `--no-ff` 병합했다(`c801a69`). 실행 중인 스크립트 파일을 바꾸지 않으려고 병합을 미뤘었다. push 없음.
- 백업 `backups/postgres/full/bidops-20261118T090916Z.dump`(62,584,053 B, sha256 `d7518fd5c717f395653a8af1211998734283e5c778ab5211b7e9921dba888a9a`, TABLE DATA 111, head `0042_engine_run`). 롤백 태그 `before-launch-hardening-d-20261118` = `4894b4e`.
- 실행 중인 판정이 없음을 확인하고(`실행 중`·`대기` 0) 이미지 `bidops:main-20261118d`(amd64, `e57f7484…`)를 만들어 web과 analysis-worker를 함께 바꿨다(`up -d --no-deps --no-build --force-recreate web analysis-worker`). 이제 둘이 같은 이미지다. 이 이미지는 `c` 이후의 화면 후속 수정(`5779bed`·`4894b4e`: 일일 수집 블록, 최신 기준일 판단, 검토 순서)을 담는다. migration 없음.
- web healthy·재시작 0, `/api/health`·`/api/feature-flags`·`daily-trigger`·`/api/runs`·`/api/opportunities`·`/policies` 200. feature-flags는 `rl_analysis=false`·`prespec_overview=false`, daily-trigger는 v5 `1e6d4ef1…` ON 그대로다. worker env는 `BIDOPS_C2_EXECUTION_ALLOWED=true`, 개요 false다.

## 공고 트랙 따라잡기 (2026-11-04 ~ 2026-11-17, 18:10~18:23 KST)

이 checkout에서 공고 트랙을 처음 돌렸다. 수집·적재만 하며 모델 호출은 없다(C-1 미실행, 개요 플래그 false). 두 트랙 공용 lock `~/.local/state/bidops/daily.lock`을 썼다.

| 실행 | 기준일 | 결과 |
|---|---|---|
| 단일 시험 `--from-date 2026-11-04 --to-date 2026-11-04` | 11-04 | exit 0, 약 2분. 로그 `catchup-notices-2026-11-04-2026-11-04-1810.log` |
| 범위 `--from-date 2026-11-05 --to-date 2026-11-13` | 11-05~11-13 | exit 0, `no gap`. 로그 `catchup-notices-2026-11-05-2026-11-13-1812.log` |
| cron 명령 그대로(아래 절) | 11-14~11-17 | exit 0, `no gap for notices in 2026-11-04..2026-11-17` |

| 기준일 | 수집(4일 창) | 적재 공고 | 적재 경고 |
|---|---:|---:|---:|
| 11-04 | 3,663 | 600 | 568 |
| 11-05 | 4,843 | 813 | 751 |
| 11-06 | 4,573 | 807 | 756 |
| 11-07 | 3,418 | 603 | 566 |
| 11-08 | 2,259 | 411 | 380 |
| 11-09 | 2,484 | 414 | 383 |
| 11-10 | 2,741 | 439 | 366 |
| 11-11 | 3,938 | 651 | 537 |
| 11-12 | 5,341 | 886 | 672 |
| 11-13 | 5,099 | 891 | 604 |
| 11-14 | 3,841 | 659 | 433 |
| 11-15 | 2,649 | 454 | 260 |
| 11-16 | 2,753 | 418 | 228 |
| 11-17 | 3,035 | 424 | 227 |

- 14회차 모두 수집 `complete: true`이고 Run 상태는 `active`다. 11-17 회차의 경고 227건은 `opportunity_link_target_missing` 226건(입찰공고가 가리키는 사전규격·발주계획이 수집 창 밖이라 연결 대상을 찾지 못함)과 `screening_results_missing` 1건(C-1 판정 결과 없음)이다. 공고 회차의 경고는 C-2 실행을 막지 않는다.
- 적재 뒤 `work_job`은 `completed 75`·`failed 62`로 실행 전과 같고 개요·심층 작업은 생기지 않았다. 첨부 취득 자격 갱신은 매번 0건이었다.
- **사전규격 화면의 검토할 항목은 0건이다**(최근 수집 708건). 개요 검토가 꺼져 있고 추적 중인 발주계획이 없어서다. 수집이 검토 항목으로 이어지려면 발주계획 추적 선택 또는 개요 검토 활성화가 필요하며 후자는 별도 승인 대상이다.

## cron 명령 감독 실행 (18:12~18:23 KST, main `c801a69`)

설치할 줄과 같은 명령을 cron과 같은 최소 환경(`env -i HOME=… PATH=/usr/bin:/bin SHELL=/bin/sh LOGNAME=…`)에서 한 번씩 돌렸다. floor는 `2026-11-04`, 발주계획 actor는 `jechoi`다. cron에는 설치하지 않았다.

| 명령 | 결과 |
|---|---|
| `scripts/cron-daily-track.sh order-plans` | 공고 따라잡기가 lock을 쥔 동안 띄웠다. 18:12:58 start 줄을 남기고 약 7분 lock을 기다린 뒤 실행됐다. `daily C-2 trigger on` → `catch-up: 0 missing or unjudged day(s)` → 11-17 `already_executed`(새 실행 없음, 모델 호출 0) → `audit sample already drawn` → `no gap for order-plans in 2026-11-04..2026-11-17` → 18:20:29 `exit=0` |
| `scripts/cron-daily-track.sh notices` | 18:20:46 start → `catch-up: 3 missing or unjudged day(s)` → 11-14·11-15·11-16을 먼저 수집·적재 → 11-17 → `no gap` → 18:23:40 `exit=0` |

- 실제 스택에서 지나간 것: 래퍼의 PATH 자체 설정, 공용 lock 대기(`flock -o -w`), start/exit 줄, 발주계획의 판정 상태 조회와 감사 표본 조회 GET, `--catch-up-days`의 "없음" 판단(발주계획)과 실제 따라잡기(공고), 누락일 감지(lookback 31 설정이지만 floor 때문에 실제 검사 범위는 11-04..11-17 14일).
- 래퍼는 lock을 얻은 시각을 남기지 않는다. "약 7분 대기"는 start 줄(18:12:58)과 공고 따라잡기 종료 시각에서 추정한 값이다.
- 지나가지 않은 것: 발주계획 따라잡기가 실제로 C-2 실행을 만드는 경우, exit 10·75·124, 읽기 재시도.
- 운영 화면(`~/orca/bidops-captures/20261118-prod-final`): 대시보드 "일일 수집" 블록이 발주계획 `정상 · 최근 기준일 11-17 · C-2 성공 · 사람 검토 107건`, 공고 `정상 · 최근 기준일 11-17 · 적재 경고 227건` 두 줄을 보인다. 발주계획 탭은 `관련 696`·`불확실 668`·`전체 7,827`·`1차 선별 제외 2,813`·`선별 실패 25`다.

## UI·화면 흐름 반영 (16:13 KST, main `4dd8b58`)

- 이미지 `bidops:main-20261118c`(amd64, `339ffec9…`)를 `scripts/compose.sh build web`으로 만들고 web만 `up -d --no-deps --no-build --force-recreate web`으로 바꿨다. analysis-worker는 실행 중이던 판정을 끊지 않으려고 `bidops:main-20261118b` 그대로 뒀다(백엔드 변경은 web의 읽기 전용 `GET /api/feature-flags` 하나라 worker와 무관). 따라잡기가 끝난 뒤 같은 태그로 맞춘다.
- 교체는 스크립트가 11-09 실행을 폴링하던 때에 했다. healthy·재시작 0, `/api/health`·`/api/feature-flags`·`daily-trigger`·`/api/runs`·`/api/opportunities` 200, feature-flags는 `rl_analysis=false`·`prespec_overview=false`, daily-trigger는 그대로다. 폴링 읽기 실패는 기록되지 않았다(교체가 폴링 주기 사이에 끝났다. 재시도 경로 자체는 실제 스택에서 지나가지 않았다).
- 운영 화면 11개 경로를 읽기 전용(GET만 허용)으로 1440×900에서 다시 측정했다(`~/orca/bidops-captures/20261118-prod-after`). 글자 크기는 12·14·16·20뿐이고 4px 격자 밖 값은 1·2px 예외와 `margin-top:auto` 계산값뿐이다(경로별 3~10%). 가로 넘침 0, 화면 제목은 모두 16px. 반영 전 같은 측정은 격자 밖 41~88%, 글자 12종이었다.
- 실제 데이터에서 본 것: 발주계획 `관련 389`·`불확실 393`·`선별 실패 25` 탭, 대시보드의 일일 실행 한 줄. 한 줄이 과거 날짜 따라잡기 중인 실행을 "확인 필요"로 표시하고, 목록 첫 행이 발주 예정월이 지난 건이라는 두 가지를 후속 수정으로 넘겼다.

## cron 설치 전 독립 재검증 (18:30 KST 전후, 읽기 전용)

구현에 관여하지 않은 컨텍스트가 `d1ce3ae`·래퍼·당일 로그·실제 환경을 읽고 **조건부 설치 가능, 코드 차단 0**으로 판정했다. 스크립트 테스트 4개 파일 161건 통과, crontab 없음, `--print-crontab` 출력과 제안 줄이 같음을 확인했다.

- 조건(사람 결정): ① 평일 아침 로그 확인 담당자 지정, ② 재부팅 뒤 analysis-worker가 꺼져 있는 경우(B4)의 처리, ③ cron 승인 범위에 하루 최대 C-2 실행 4건(따라잡기 3일 + 기준일)과 attempt 2 재시도를 포함.
- B4의 실제 동작: worker가 꺼져 있으면 실행이 `대기`로 남고 스크립트는 7200초 폴링 뒤 exit 2로 끝난다. 다음 날 실행이 4시간을 넘긴 `대기`를 `stale_queued`로 닫으며 attempt 1을 소모한다. 재부팅 때 `실행 중`이 굳어 있으면 worker가 올라올 때까지 모든 생성이 409다. 조용한 누락은 없으나(매일 exit 2·10, 대시보드 정오 뒤 지연 표시) 자동 회복은 최근 3일뿐이다.
- 주의: 실패 신호는 로그의 `exit=` 줄과 대시보드뿐이고 cron 메일은 설정 오류일 때만 나간다. `daily_trigger_off`는 exit 0으로 끝나므로 확인할 때 함께 본다. cron 맥락(TCC·launchd 세션)과 래퍼를 거친 실제 C-2 실행 생성은 설치 뒤 첫 실행에서 처음 지나간다.
- 이 재검증이 짚은 기록 오류 두 곳(실행 건수의 운영/측정 구분, 31일 창 표현)은 위에서 고쳤다.

## 이 기록이 증명하지 않는 것

- 이번에 고친 경로 중 실제 스택에서 지나가지 않은 것: `대기` 실행 회수(`stale_queued`), `info` 경고 통과와 audit 기록, `unjudged_detected`·`gap_detected`와 exit 10, 발주계획 따라잡기가 실제 C-2 실행을 만드는 경우, 폴링·읽기 재시도, `audit_sample_missing`, 래퍼의 exit 75·124. 격리 테스트(PostgreSQL 변형 포함)만 통과했다. host 재시작 뒤 상태 서비스 자동 기동, 공용 lock 대기, `--catch-up-days`의 공고 따라잡기와 발주계획 "없음" 판단은 위에서 실제로 확인했다.
- cron은 설치하지 않았다. 독립 검증(2026-11-18)의 차단 4건 중 B1(공고 14일 따라잡기 + 감지 창 31일)·B2(스크립트)는 해소했고, B3는 래퍼의 종료 코드 줄과 대시보드 공고 줄까지 했으며 **아침에 로그를 볼 담당 지정**이 남았다. B4(재부팅 뒤 analysis-worker 자동 기동)는 사용자 결정 대기라 반영하지 않았다. 재검증은 코드 차단 0·조건부로 끝났다(위 절).
- 공고 트랙은 수집·적재만 확인했다. C-1 판정·개요 검토·문서 준비는 돌지 않았고 사전규격 검토 항목은 0건이다.
- 평일 발주계획의 Top300 절단 밖(하루 127~327건) 누락과 검토 후보 80건 초과는 v5 게이트 조건 밖의 규모이며 품질을 새로 측정하지 않았다.
- 2026-10-15~11-03의 발주계획은 수집하지 않는다(사용자 결정: 최근 14일만).

## 롤백

현재 운영은 main `c801a69`·이미지 `bidops:main-20261118d`(web·analysis-worker 동일)다. 직전 상태로는 `.env`의 `BIDOPS_IMAGE`를 `bidops:main-20261118c`로(코드 태그 `before-launch-hardening-d-20261118`), 이번 작업 전체 이전으로는 `.env`의 `BIDOPS_IMAGE`를 `bidops:main-20261118`로 되돌리고 `up -d --no-deps --no-build --force-recreate web analysis-worker`. 코드는 태그 `before-launch-hardening-20261118`. 스키마 변경이 없어 DB 복원은 필요 없다. 이번에 생긴 C-2 실행·감사 표본 행은 지우지 않는다.
