# 일일 수집·C-2 운영

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

현재 실행은 `export BIDOPS_ENV=prod`로 운영 환경을 명시한 뒤 아래 명령을 쓴다.
격리 개발·mock 설치는 [host](host.md)를 따른다. 이 문서의 이전 참조 실행 기록은 현재 품질·활성화 승인이 아니다.


## 발주계획 선별 실험 운영

제품 선별기를 구현하기 전에 동일한 3일 입력을 동결해 네 방식을 비교한다.

1. 일반용역과 기술용역을 수집하고 발주계획 단계에서는 SW사업대상 여부로 선필터하지 않는다.
2. 원본 응답, 정규화 전체 레코드, 조회 조건, 페이지, source hash, 최초 수집 시각을 보존한다.
3. 키워드 규칙, ColBERT, `qwen3.8-27B`, GPT Luna xhigh를 같은 모집단에 실행한다.
4. GPT Luna에는 공개 발주계획 메타데이터와 별도 승인된 회사 역량 요약만 전송한다. 전송 전에 담당자가 payload를 확인하고 승인 기록을 남긴다.
5. Sol xhigh 결과는 silver reference와 이견 탐색에만 사용한다. 최종 relevance·우선순위 정답은 사람이 판정한다.
6. 방식별 recall, precision, 검토량, 중요 누락, 순위 품질, 비용, 지연, 재현성을 보고서에 기록한다.
7. 선택 방식 또는 조합과 운영 threshold를 승인한 뒤에만 제품 구현과 자동 일정 활성화를 진행한다.

개발계정의 일일 1,000회 요청 한도는 레코드 수가 아니라 실제 HTTP 요청 수로 관리한다. endpoint·페이지·재시도별 사용량을 세고 같은 응답은 회차 cache로 재사용한다. 초기 방어선은 700회 경고, 900회에서 신규 요청 중지다. 운영 전 실제 관측치와 필요한 endpoint 수를 근거로 활용사례를 등록해 증액을 신청한다.

## 목표 수집 일정

발주계획 수집기는 아래 명령으로 명시적으로 실행한다. 스케줄러와 always-on은 기본 비활성이고,
운영자가 회차 디렉터리와 API key 주입을 확인한 뒤 실행한다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --output-dir data/runs/order-plans-$(date +%Y%m%d) \
  --days 21

# 날짜를 고정하는 재현·재조회 모드 (to-date는 제외)
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --output-dir data/runs/order-plans-20260808-20260829
```

기존 raw page를 다시 정규화할 때는 새 회차 디렉터리를 지정한다. 이 모드는 API를 호출하지
않는다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --from-raw data/runs/order-plans-20260808-20260829/raw \
  --output-dir data/runs/order-plans-20260808-20260829-reclassified
```

발주계획과 사전규격 수집은 공고 수집과 별도 회차로 유지한다. 아래 일정은 현재 자동 활성화된
스케줄이 아니라 운영 목표다.

- 발주계획 수집: 매일, 일반용역·기술용역, SW사업대상 선필터 없음.
- 발주계획 사람 검토: 월요일과 목요일. 수집 회차는 검토 일정과 독립적으로 보존한다.
- 사전규격 수집: 매일, 일반용역·기술용역 메타데이터 전량. `SW사업대상`은 필터가 아니라 저장·표시 값이다.
- 사전규격 첨부 문서 다운로드: `SW사업대상=Y` 또는 추적 중인 발주계획 연결로 자격이 생긴 건만 수행한다. 자격이 뒤늦게 생기므로 재평가 큐를 사용한다.
- 사전규격 1차선별: 저비용 판정 후 사람 확인. 승인된 건만 심층 검토 실행.
- 입찰 추적: `계속 추적` 기회에 대해 신규 공고와 정정공고를 확인하고 사전규격 대비 중요 변경을 계산한다.
- 각 단계는 자동 연결 실행과 수동 단독 실행·재시도를 같은 실행 ID, artifact, 상태 전이 규칙으로 제공한다.

### 일일 수집·선별 적재 (`scripts/run-daily-lifecycle.sh`)

위 운영 목표 중 발주계획·사전규격·입찰공고 수집과 선별 적재를 실행하는 host 스크립트다.
`--track order-plans|notices`(필수, 기본값 없음)로 **한 번에 한 트랙만** 돌고, `--date YYYY-MM-DD`
(기준일, 한국시간, 생략 시 **전일**)를 받는다. 발주계획 트랙은 기준일 **하루**, 공고 트랙은 기준일을
포함한 **4일**을 수집한다. 사전규격은 조회 기준인 등록일시(`rgstDt`)보다 공개(접수일시 `rcptDt`)가
최대 3일 늦을 수 있어 하루 창이면 영구히 빠지는 건이 생긴다(2026-09-18 측정). 겹쳐 다시 관측된
공고는 적재에서 no-op이며 첨부·문서 묶음·개요 검토를 다시 만들지 않는다
([ADR-0061](../tracking/decisions/0061-daily-collection-window.md)). 트랙 안에서는 첫 실패에서 즉시
멈추고(`set -euo pipefail`), 두 트랙은 서로의 성공을 전제하지 않는다.

1. Preflight: `manual-workflow-common.sh`의 web 헬스체크. `BIDOPS_G2B_API_KEY` 존재 확인은
   collector 자신이 하므로 스크립트는 별도로 값을 읽거나 출력하지 않는다.
2. 발주계획 트랙(`--track order-plans`): 아래 다섯 단계가 항상 함께 돈다(`--c2` 같은 부분 실행
   플래그는 없다) — ① 자동 실행 확인 `GET /api/order-plan-screening/daily-trigger`. 응답의
   `effective_enabled`가 `false`이면 `daily_trigger_off`와 `reasons[]`, "policy를 교체하면 자동
   실행이 멈춥니다. 새 버전에서 다시 켜야 합니다." 안내문구를 출력하고 **수집 없이** exit 0(다음 절
   참조). 실행에 쓸 `policy_version`도 이 응답에서 받는다. ② 발주계획을 회차
   `lifecycle-<YYYYMMDD>-plans`로 수집한다(`collect_order_plans.py --from-date <기준일> --to-date
   <기준일+1일>`, `--to-date`는 제외구간). ③ `ingest.cli --run <plans> --collection` →
   `--tracked-backfill`. 이어서 `GET /api/runs/<회차 디렉터리>`로 **정규 회차 id**
   (`<디렉터리>--<generated_at>Z`, 적재가 만드는 `Run` 기본키)를 받는다 — 아래 ④·⑤와 실행 목록
   조회·attempt 계산은 전부 이 값을 쓴다. 한 디렉터리에 `Run` 행이 둘 이상이면 어느 것을 판정할지
   추정하지 않고 멈춘다. ④ C-2 실행 요청(`POST /api/order-plan-screening/executions`, 헤더
   `X-BidOps-Trigger: daily_script`, 202를 폴링해 종결 상태까지 기다린다). ⑤ 종결 뒤 감사 표본 draw
   (`POST /api/order-plan-screening/executions/{id}/audit-sample`). 회차·실행·draw의 스킵·재시도
   규칙은 `scripts/run-daily-c2.sh`가 정하며(아래), 발주계획 트랙은 이 스크립트를 그대로 부른다.
3. 공고 트랙(`--track notices`): 사전규격·입찰공고를 회차 `lifecycle-<YYYYMMDD>-notices`로
   수집한다(`collect_notices.py --from-date <기준일−3일> --to-date <기준일> --tag-bid-sw-industry`, 이
   collector의 `--to-date`는 포함구간). 사전규격·입찰공고 스킵 플래그는 쓰지 않아 전량이 한 회차에
   담기고, 입찰공고에는 1468(SW 유사업종) 표시가 함께 붙는다. 이어서 회차를 web 컨테이너로 복사하고
   `ingest.cli --run <notices> --collection` → `--tracked-backfill` → 첨부 취득 자격 갱신
   (`refresh_fetch_eligibility`) 순서로 적재한다.
4. 적재 순서는 트랙 사이에 고정하지 않는다. 공고 선별이 읽는 발주계획 상태는 사람이 정한 추적
   상태(`계속 추적`·`보류`·`종료`)이고, 기준일 하루 창으로 들어온 발주계획에는 아직 추적 상태가 없으므로
   같은 날 발주계획이 먼저 적재됐는지가 공고 선별 결과를 바꾸지 않는다. `--tracked-backfill`은 두 트랙
   끝에서 각각 부르며 다시 불러도 no-op이다.

각 기준일은 그 날짜가 처음 걸리는 단계에서 이어 돈다 — `complete`(회차가 완결이고 web에 `Run`
행도 있음, 할 일 없음), `empty`(완결이고 `counts.total == 0`, 적재 없이 종료), `ingest_pending`
(완결인데 `Run` 행이 없음, 적재만), `collect_new`(회차 디렉터리 없음, 수집부터),
`collect_retry<N>`(불완전한 디렉터리가 있으면 **그 디렉터리는 그대로 두고**
`lifecycle-<YYYYMMDD>-<plans|notices>-retry<N>`(가장 작은 미사용 N)으로 새로 수집). 발주계획
트랙은 회차가 비어 있지 않으면 이 뒤에 더 이어간다 — `성공`·`부분 성공` 실행이 없으면 실행부터,
있는데 감사 표본이 아직 안 뽑혔으면 draw만. 회차 디렉터리는 회차 원본 불변 원칙에 따라 절대
덮어쓰거나 지우지 않는다.

**누락일 감지(2026-11-18, findings W-3·W-4).** 그날 몫(따라잡기 날짜 포함)을 끝낸 뒤 스크립트는 기준일
(범위 모드면 `--to-date`)과 그 앞 `BIDOPS_DAILY_GAP_LOOKBACK_DAYS`일(기본 7, `0`은 끔)의 회차 디렉터리
연속성을 본다. 완결 표식이 있는 디렉터리(기본 또는 `-retry<N>`, 0건 회차 포함)가 있으면 그날은 있는
것이고, 없거나 불완전한 디렉터리뿐이면 빠진 날이다. 로컬 디렉터리만 읽고 web은 부르지 않는다.
`BIDOPS_DAILY_GAP_FLOOR_DATE`(YYYY-MM-DD)보다 앞선 날은 세지 않는다 — cron을 걸기 전의 공백처럼
사람이 확인하고 넘긴 기간을 여기서 인정한다. 빠진 날마다 `gap_detected track=<트랙> date=<날짜>` 한
줄을 찍고 **exit 10**으로 끝난다.

두 트랙 모두, 완결이고 비어 있지 않은 회차인데 web에 `Run` 행이 없는 날(`GET /api/runs/<디렉터리>` 404 — 수집은
끝났는데 적재가 실패했거나 둘 사이에서 `timeout`에 끊긴 날)은
`unjudged_detected track=<트랙> date=<날짜> run=<디렉터리> reason=not_ingested`로 보고하고 `--catch-up-days`가
`ingest_pending`으로 재개한다(2026-11-18 독립 검증 B2). 공고 트랙은 적재 뒤 단계(`--tracked-backfill`,
`refresh_fetch_eligibility`)가 회차가 아니라 전체를 다시 계산하는 전역 단계이고 다음 공고 날마다 다시 돌므로
감지하지 않는다 — 그날 실패는 그날 exit 비0으로만 드러난다.

발주계획 트랙은 하나 더 본다(findings W-5). 창 안에서 완결이고 비어 있지 않은 회차인데 `성공`·`부분 성공`
운영 C-2 실행이 없는 날은 판정 없이 끝난 날이다 — 날짜별 재개가 "실행부터"로 판단하는 것과 같은 기준이며
(재개 규칙처럼 policy 버전은 가리지 않는다) **이번 호출이 방금 처리한 날도 포함한다**. 오늘 C-2가
`active_execution_exists`·503·`policy_not_active`·`retry_limit_reached` 같은 정상 스킵으로 끝났으면 오늘
드러난다. 그런 날마다
`unjudged_detected track=order-plans date=<날짜> run=<디렉터리> reason=<사유>` 한 줄을 찍는다. 사유는
`not_ingested`(`Run` 행 없음), `multiple_run_rows:<n>`(행이 둘 이상 — 고르지 않는다), `active:<상태>`(`대기`·
`실행 중`·`중지 요청`이 잡고 있음), `last:<상태>`(실패·중단만 있음, 가장 늦게 들어온 것), `no_execution`, `audit_sample_missing`(최신 `성공`·
`부분 성공` 실행의 감사 표본 GET이 `preview` — 뽑을 수 있는데 기록이 없음. `pending_human_approval`·
`not_applicable`은 뽑을 것이 없으므로 세지 않는다)이다. 마지막 사유는 폴링이 끊긴 날처럼 실행은 성공했는데
draw를 못 한 날을 잡는다(2026-11-18 감독 시운전).
이 확인은 web을 읽기만 한다 — `GET /api/runs/<디렉터리>`로 정규 id, `GET /api/runs`로 행 수, 실행 목록은 정규
id로만, 성공일은 `GET …/executions/<id>/audit-sample`(계산만 하고 기록하지 않는다).
조회가 실패하면 "누락 없음"이 아니라 실패 코드(2)로 끝난다. 0건 회차와 floor 이전 날은 세지 않는다.

exit 10은 "주의 필요 — 이번 호출이 처리한 날은 모두 성공·정상 스킵이고, 창 안에 빠진 날이나 판정 없는 날이
남았다"는 뜻이다. 요약 줄 `gap check: <n> missing, <m> unjudged day(s) …`가 둘을 따로 센다. 실제
실패(스크립트 자체 검사 2, 실패한 명령의 코드, `timeout`의 124)와 겹치지 않는다.
그날 몫이 실패하면 감지 전에 그 실패 코드로 끝난다. 발주계획 트랙이 `daily_trigger_off`로 수집 없이
끝나는 날은 감지를 하지 않는다(그 기간은 다시 켠 뒤 첫 실행에서 누락일로 보인다). 공고 트랙은 창이
4일이라 하루 빠진 날의 공고는 다음 날 창이 덮지만, 그날 실행이 없었다는 사실은 그대로 보고한다.

**`--catch-up-days N`(기본 0).** 기준일 앞 N일 중 빠진 날(위와 같은 판정, floor 이전 제외)을 오래된
날부터 위의 날짜별 재개 규칙으로 먼저 처리한 뒤 기준일을 처리한다. N은
`BIDOPS_DAILY_GAP_LOOKBACK_DAYS` 이하여야 하고 `--from-date/--to-date`·`--collect-only`와 함께 쓸 수
없다. 첫 실패일에서 트랙이 멈추고 뒤 날짜(기준일 포함)는 돌지 않는다 — `--from-date/--to-date`와
같다. 발주계획 트랙은 preflight·자동 실행 확인 뒤 같은 N일 안의 **판정 없는 날**도 고른다 — 날짜별 재개가
빠진 단계(적재 또는 C-2)만 돌린다. 단 `active:*`(실행이 잡고 있음)·`multiple_run_rows:*`(사람 판단)인 날은
고르지 않고 보고에만 남긴다(돌려도 스킵하거나 멈출 뿐이다). `last:실패`가 이미 두 번이면 재개는
`retry_limit_reached`로 넘어가므로 새 호출은 없고 보고는 계속된다 — `--extra-attempt`는 사람 몫이다.
따라잡는 날마다 C-2 실행을 요청할 수 있으므로(분석 워커의 실제 모델 호출) 범위를 넓히기 전에 승인 범위를
확인한다. 공고 트랙은 빠진 날만 고른다.

`--collect-only --run-suffix <name>`은 측정·점검용이다. preflight·자동 실행 확인·회차 조회·적재·
C-2를 전부 건너뛰고 수집만 하며 회차 id는 `lifecycle-<YYYYMMDD>-<plans|notices>-<name>`이 되어
일일 회차 id를 차지하지 않는다(`retry<N>`은 재수집 접미사로 예약돼 쓸 수 없다).

`--dry-run`은 계산한 회차 id·창·각 단계의 정확한 명령만 출력하고 수집·적재·C-2 실행·Docker 호출을
하지 않는다(preflight의 web 헬스체크와 web `Run` 조회도 건너뛰고, 완결 회차는
`complete_or_ingest_pending`으로만 표시한다). `--catch-up-days`가 고른 날짜는 기준일 앞에 같은 모양으로
나열되고, 누락일 감지는 실제 실행이 처리할 날을 뺀 나머지 중 보고할 날을
`[dry-run] would report: gap_detected …`로, 끝날 exit 코드를 한 줄로 알린다. 발주계획 트랙의 판정 상태는
web을 읽어야 하므로 dry-run은 확인하지 않고 "a real run would also check judged state"라고만 알린다
(따라잡기 목록에도 판정 없는 날은 들어가지 않는다). dry-run 자체는 exit 0이다.
기존 회차 디렉터리가 있으면 절대 덮어쓰지 않고 즉시 멈춘다(회차는
불변). 이 스크립트는 아무것도 삭제하지 않고 cron을 설치하지 않으며, 스크립트 자체는 모델을 호출하지
않는다 — 발주계획 트랙이 요청하는 C-2 실행은 승인된 binding 아래 분석 워커에서 돈다.

**스킵의 세 가지 뜻이 다르다.**

| 뜻 | 값 | exit |
|---|---|---|
| 정상 스킵(할 일 없음) | `daily_trigger_off`, `empty_population`, `active_execution_exists`, `already_executed`, `retry_limit_reached`, POST가 `policy_not_active`·`daily_trigger_off`·503으로 답함 | 0 |
| 트랙을 그 자리에서 멈추는 스킵(따라잡기 중이면 나머지 날짜도 같은 사유로 끝난다) | `daily_trigger_off`, `policy_not_active`, 503, `active_execution_exists` | 0 |
| 다음 날짜로 넘어가는 스킵(따라잡기가 이어진다) | `already_executed`, `empty_population`, `retry_limit_reached` | 0 |
| 처리한 날은 끝났고 빠진 날·판정 없는 날이 남음(위 "누락일 감지") | `gap_detected`, `unjudged_detected` | 10 |

트랙을 멈추는 스킵 뒤에도 누락일 감지는 돈다(수집 전 `daily_trigger_off`만 예외). 발주계획 트랙에서
그날 C-2가 정상 스킵으로 끝나면 그날이 판정 없는 날이 되므로 exit는 10이다. 빠진 날·판정 없는 날이
없으면 위 표대로 0이다(`run-daily-c2.sh` 단독 실행은 감지가 없어 그대로 0). 그 밖의 실패는 exit 비0(10 아님)이며 `set -euo pipefail`로 그 트랙을 즉시
멈춘다. 같은 날 재시도까지 실패해도 exit는 비0이다(아래 재시도 규칙).

`active_execution_exists`에는 예외가 하나 있다. 스킵할 때 그 실행의 id·상태·경과 시간을 함께
출력하고, 경과가 `BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS`의 **2배를 넘으면 exit 비0**이다. 스크립트는
자기 회차에 `대기` 실행이 있으면 POST하지 않으므로 이 경로에서는 서버의 `대기` 회수가 돌지 않는다.
서버는 `queued_at`이 `BIDOPS_C2_QUEUED_MAX_DWELL_SECONDS`(기본 4시간)를 넘긴 `대기`를, 진행 중인 실행이
없을 때 **다음 실행 생성 요청(다른 날 회차 포함)이나 워커 claim에서** `중단됨`+`stale_queued`로 닫는다
([C-2 계약](../contracts/c2.md) "C-2 상태 의미와 전이"). 닫힌 실행은 다시 돌지 않는다 — 워커 상태를
확인한 뒤 그날을 `--date`(또는 `scripts/run-daily-c2.sh <회차>`)로 다시 돌리면 attempt 규칙대로 새
실행을 만든다. 아직 닫히지 않은 실행을 바로 치우려면
`POST /api/order-plan-screening/executions/<id>/stop`을 쓴다.

**서버 설정(web·analysis-worker 환경변수).** `BIDOPS_C2_QUEUED_MAX_DWELL_SECONDS`(기본 14400, `0`은 끔,
켜면 `BIDOPS_C2_WORKER_STALE_SECONDS` 이상이어야 기동한다). 기본 4시간은 정상 대기 — 앞선 C-2 한 건(300건
약 26분, heartbeat로 보호), GPU 휴지 최대 300초, `대기`가 들어올 때 이미 claim돼 있던 다른 분석 작업 한
건 — 보다 넉넉하고, 일일 스크립트가 "워커가 없을 수 있다"며 비0으로 끝나는 경과(폴링 7200초의 2배)와
같으며 하루 주기보다 짧아 다음 날 생성 요청이 전날 것을 닫는다. 다른 분석 작업(개요·심층·제안서)의
진행은 C-2 회수의 근거로 보지 않으므로, 그런 작업 하나가 4시간을 넘기면 그 뒤에 들어온 C-2 `대기`가
닫힐 수 있다.

**발주계획 트랙 전용 환경변수** (`scripts/run-daily-c2.sh`·`scripts/c2-execution-common.sh`가 읽는다):

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `BIDOPS_C2_DAILY_ACTOR` | 없음(필수) | C-2 실행·audit 요청에 실리는 담당자 이름. 감사 표식일 뿐 인증이 아니다. 없으면 시작하지 않는다 |
| `BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS` | 600 | 그 날짜의 실행이 `실패`·`중단됨`뿐일 때, 자동 재시도(attempt+1) 전에 기다리는 시간 |
| `BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS` | 7200 | 실행을 종결 상태까지 기다리는 최대 시간. 넘기면 exit 비0으로 스크립트는 멈추지만 실행 자체는 분석 워커에서 계속 진행되고, 다음 호출은 `active_execution_exists`로 건너뛴다 |
| `BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS` | 30 | 폴링 주기 |
| `BIDOPS_C2_DAILY_POLL_MAX_READ_FAILURES` | 10 | 폴링 GET(실행 상세)의 일시 실패 — 응답 없음(timeout 등)·5xx·408·429 — 를 `c2: poll read failed (n/N)` 한 줄로 남기고 같은 주기로 다시 읽는 연속 횟수 상한. 상한에 닿거나 전체 폴링 timeout이면 exit 2. `0`은 첫 실패에서 바로 멈춘다(2026-11-18 이전 동작). 그 밖의 4xx는 언제나 바로 멈추고, 실행 생성 POST는 다시 보내지 않는다 |

**두 트랙 공통 환경변수** (`scripts/run-daily-lifecycle.sh`가 읽는다, 위 "누락일 감지"):

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `BIDOPS_DAILY_GAP_LOOKBACK_DAYS` | 7(cron 래퍼는 31) | 기준일 앞 며칠을 누락일 감지에 넣을지. `0`은 감지를 끈다. `--catch-up-days`의 상한이기도 하다. **창보다 오래된 날은 다시 보지 않는다** — 창 밖으로 밀려난 빠진 날은 그 뒤로 보고되지 않으므로 cron은 31일을 쓰고, 평일 아침 확인에서 exit 10을 넘기지 않는다 |
| `BIDOPS_DAILY_READ_ATTEMPTS` | 3 | 읽기 전용 GET(health·자동 실행 확인·회차 조회·회차 목록·실행 목록·감사 표본 상태)의 시도 횟수. 응답 없음·5xx·408·429면 `read retry (n/N) GET <경로>: …` 한 줄을 남기고 다시 읽는다. 마지막 시도도 실패하면 기존 실패 경로(exit 2). 4xx와 POST는 다시 보내지 않는다. 폴링은 아래 `BIDOPS_C2_DAILY_POLL_MAX_READ_FAILURES`를 따른다 |
| `BIDOPS_DAILY_READ_RETRY_PAUSE_SECONDS` | 5 | 위 재시도 사이의 대기 |
| `BIDOPS_DAILY_GAP_FLOOR_DATE` | 없음 | `YYYY-MM-DD`. 이보다 앞선 날은 보고하지도 따라잡지도 않는다. 사람이 확인한 공백(cron 이전 등)을 인정할 때 쓴다 |

**복구 절차.** 자동 재시도(attempt 2)까지 실패한 회차는 `attempt > 2`로 `retry_limit_reached`
스킵을 낸다 — 이후로는 자동 재시도하지 않는다. 사람이 재개할 때만
`scripts/run-daily-c2.sh <plans run id> --extra-attempt`를 쓴다. 회차 id는 디렉터리 이름
(`lifecycle-<YYYYMMDD>-plans`)으로 줘도 되고 정규 id로 줘도 된다 — 스크립트가 `GET /api/runs/<id>`로
정규 id를 확정한 뒤 C-2를 부른다. `retry_limit_reached` 안내에는 정규 id가 실린다. 헤더 `X-BidOps-Trigger:
manual_resume`으로 실행 하나만 만들고 자동 재시도는 없다. `--dry-run`으로 먼저 계획된 요청을
확인할 수 있다. `retry_limit_reached`를 출력할 때 이 명령을 함께 안내한다.

**스케줄은 기본 비활성이다.** 이 저장소는 cron을 설치하지 않는다(스케줄러·always-on 기본 비활성 원칙,
`CLAUDE.md`). 설치는 cron 승인 때 사람이 한다. 발주계획 줄은 아래 "C-2 발주계획 선별 활성화 절차"를 마친
뒤에만 둔다.

**cron 진입점은 `scripts/cron-daily-track.sh <notices|order-plans>` 하나다**(2026-11-18 독립 검증 B3). crontab
줄은 이 래퍼만 부르므로 시험한 것과 설치한 것이 같다. 래퍼가 하는 일:

- 저장소 루트로 이동하고 PATH를 스스로 정한다(GNU coreutils → OrbStack docker → Homebrew → 시스템). crontab에
  PATH 줄이 필요 없다.
- 기본값: `BIDOPS_ENV=prod`, `BIDOPS_WORKFLOW_WEB_URL=http://127.0.0.1:18788`, `BIDOPS_DAILY_GAP_LOOKBACK_DAYS=31`,
  따라잡기 3일(`BIDOPS_DAILY_CATCH_UP_DAYS`로 바꾼다). 환경변수로 덮을 수 있다.
- 필수(기본값 없음): `BIDOPS_DAILY_GAP_FLOOR_DATE`, 발주계획은 `BIDOPS_C2_DAILY_ACTOR`. 비었거나 `<…>` 자리표시자가
  남아 있으면 아무것도 돌리지 않고 exit 2로 끝나며 사유를 로그와 stderr(cron 메일)에 남긴다.
- **두 트랙이 lock 하나를 쓴다**: `~/.local/state/bidops/daily.lock`(`BIDOPS_DAILY_LOCK_FILE`). `flock -o -w <대기>
  -E 75`로 잡으며 대기는 공고 3600초, 발주계획 7200초다(`BIDOPS_DAILY_LOCK_WAIT_SECONDS`). `-o`는 lock fd를 트랙에
  물려주지 않아 남은 자식 프로세스가 lock을 붙잡지 못하게 한다. 설치된 flock(discoteq 0.4.0)이 `-o`·`-w`·`-E`를
  지원함을 2026-11-18에 확인했다.
- 트랙을 `timeout -k 60 3h`(공고)·`6h`(발주계획)로 감싼다(`BIDOPS_DAILY_TRACK_TIMEOUT`).
- 모든 출력을 `~/.local/state/bidops/logs/<track>-YYYYMM.log`(`BIDOPS_DAILY_LOG_DIR`)에 덧붙인다. 첫 줄은
  `[cron] <일시> track=<트랙> start pid=… env=… floor=… catch_up=…`, 마지막 줄은 언제나
  `[cron] <일시> track=<트랙> exit=<rc>`다. start 줄만 있고 exit 줄이 없으면 그 실행은 도중에 죽었다(host 재시작 등).
- `--dry-run`은 같은 설정으로 트랙의 `--dry-run`을 부르며 lock·timeout을 쓰지 않고 터미널에 출력한다. 설치
  전에 `env -i HOME=$HOME BIDOPS_DAILY_GAP_FLOOR_DATE=<날짜> [BIDOPS_C2_DAILY_ACTOR=<이름>] scripts/cron-daily-track.sh
  <트랙> --dry-run`으로 깨끗한 환경을 확인한다. `--print-crontab`은 이 checkout 경로로 권장 두 줄을 출력한다.

```cron
# scripts/cron-daily-track.sh --print-crontab 출력(문서용 — 설치되어 있지 않음). 자리표시자 둘을 채운다.
30 6 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> /Users/temp/orca/bidops/scripts/cron-daily-track.sh notices
0 7 * * * BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> BIDOPS_C2_DAILY_ACTOR=<담당자 이름> /Users/temp/orca/bidops/scripts/cron-daily-track.sh order-plans
```

`BIDOPS_DAILY_GAP_FLOOR_DATE`는 사람이 확인하고 넘긴 공백(cron 이전 등)의 다음 날이다. 따라잡기 3일은 날마다
C-2 실행(모델 호출)을 요청할 수 있으므로 그 범위가 cron 승인 범위에 들어가야 한다. 발주계획 하루가 최대 약
4시간 10분이라 따라잡을 날이 여럿이면 6시간 timeout(124)에 닿을 수 있다 — 그때는 남은 날을 다음 날 실행이나
사람이 메운다. 공고 06:30 실행이 길어지면 07:00 발주계획은 lock을 최대 2시간 기다린 뒤 75로 끝나고, 그날은 다음
날의 따라잡기·누락일 감지가 드러낸다.

**종료 코드**(래퍼의 exit와 로그 마지막 줄 `exit=<rc>`가 같다):

| rc | 뜻 | 할 일 |
|---|---|---|
| 0 | 성공·정상 스킵 | 없음 |
| 10 | `gap_detected`·`unjudged_detected` — 처리한 날은 정상이고 창 안에 빠진 날·판정 없는 날이 남음 | 로그의 해당 줄 사유대로 메우거나 floor를 올린다 |
| 75 | 공용 lock을 대기 시간 안에 얻지 못함(다른 트랙·수동 실행이 잡고 있음). 아무것도 돌지 않았다 | 잡고 있던 실행을 확인한다. 그날은 다음 실행의 따라잡기가 메운다 |
| 124 | timeout | 어디까지 갔는지 로그를 보고 남은 날을 메운다. C-2 실행은 워커에서 계속 돌 수 있다 |
| 2 | 스크립트 검사 실패(필수 설정 누락, web 읽기가 재시도 뒤에도 실패, 폴링 읽기 연속 실패 등) | 로그의 `error:` 줄 |
| 그 밖의 비0 | 실패한 명령의 코드(수집기 등) | 로그 |

**매 평일 아침 로그 확인.** cron 승인 때 정한 담당자(<담당자 이름 — cron 승인 때 채운다>)가 두 트랙 로그의
마지막 `[cron] … exit=` 줄을 본다. `exit=0`이 아니거나, 그날 start 줄이 없거나, start 줄 뒤에 exit 줄이 없으면
위 표대로 처리한다. 알림은 아직 없다 — 이 확인이 유일한 경보다.

**손으로 돌리는 실행도 같은 lock을 잡는다.** 따라잡기·재개를 사람이 할 때는 cron과 겹치지 않게
`flock -o -w 0 -E 75 ~/.local/state/bidops/daily.lock ./scripts/run-daily-lifecycle.sh …`처럼 같은 lock 파일로
감싼다(75면 cron이나 다른 실행이 돌고 있다). `scripts/run-daily-c2.sh`·`--extra-attempt`도 같다.

**보관**: 회차 디렉터리(`data/runs/lifecycle-*`)는 불변이며 자동으로 지우지 않는다. 보관
기간 정책은 운영자가 수동으로 정하는 결정이며 이 스크립트는 삭제 로직을 갖지 않는다.

**중단 기준**: 아래 중 하나면 실행을 멈추고 원인을 확인한 뒤 그날 몫을 다시 실행한다.
- collector(수집 단계)가 0이 아닌 코드로 종료.
- 적재 뒤 `GET /api/runs/<run_id>/warnings`에 차단 등급 경고가 있음. 이 조회는 회차 **디렉터리
  이름**도 받아 준다(`GET /api/runs/{id}`가 `<디렉터리>--%`로 alias를 풀기 때문이다). 반면 C-2
  실행 생성·조회는 정규 id만 받고 디렉터리 이름에는 409 `source_run_incomplete`으로 답한다 —
  화면·warnings 조회에서 되던 표기가 C-2에서 안 되는 이 비대칭이 B-1의 원인이었다
  (`docs/tracking/findings.md`). 손으로 C-2를 부를 때는 `GET /api/runs/<디렉터리>` 응답의
  `run_id`를 쓴다.
- 수집 결과의 `sw_industry_1468.status != complete`(조회 실패·부분 수집). 이 경우 1468
  표시는 해당 입찰공고에서 `null`로 남아 `bid_sw_industry_competitive` 선별 사유로
  적재되지 않는다 — 다음 날 창에서 같은 공고가 다시 조회되면 자연히 회복되므로, 그날은
  값을 추정해 채우지 말고 다음 날 재실행으로 넘긴다.
- 발주계획 트랙에서 `daily_trigger_off`·`policy_not_active`·503이 아닌 사유로 C-2 실행이 멈춤,
  또는 `retry_limit_reached`가 반복됨 — `--extra-attempt`로 성급하게 재개하기 전에 원인을 본다.
- exit 10. `gap_detected` 날짜는 `--from-date/--to-date`로 메우거나, 메우지 않기로 했으면
  `BIDOPS_DAILY_GAP_FLOOR_DATE`를 그 다음 날로 올린다. `unjudged_detected`는 사유를 먼저 본다 —
  `active:*`면 워커, `last:*`면 실패 원인(두 번째 실패 뒤엔 `--extra-attempt`), `not_ingested`면 적재,
  `multiple_run_rows:*`면 어느 행을 판정할지 사람이 정한 뒤 `--date`나 `run-daily-c2.sh <정규 id>`로 재개한다.
- C-2 실행이 `중단됨`+`stale_queued`로 닫힘 — 분석 워커가 4시간 넘게 그 실행을 집지 못했다는 뜻이다.
  워커 상태를 확인한 뒤 그날을 다시 돌린다.

### C-2 발주계획 선별 활성화 절차

발주계획 트랙(위 절)은 이 절차를 전부 마치기 전까지 매일 `daily_trigger_off`로 끝나고 수집하지
않는다. 열두 단계이며 ①~③은 사람 결정 값이 필요하고, 나머지는 그 값이 갖춰진 뒤의 명령·화면
동작이다(`docs/0918_daily-operation/spec.md` §0ⓑ·§3·§4·§11).

1. **gold 확정.** 사람이 확정한 발주계획 정답 표본. 표본 크기와 최종 승인은 운영 결정이다.
2. **임계값 4개.** `threshold_recall_pct`·`threshold_precision_pct`·`threshold_important_missed_max`·
   `threshold_review_load_max`(검토량은 **하루** 기준). 값이 없으면(`null`) 게이트는 `미측정`만
   기록한다 — fail closed가 정상 동작이다.
3. **감사 표본 값.** policy `audit_sample.max_per_execution`·`review_cadence`·`enabled`와 **층
   규칙** `audit_sample.strata_rules`([`docs/contracts.md`](../contracts.md) "감사 표본 REST" 참조).
   값이 없으면 draw는 매일 `pending_human_approval`로 끝난다. 2026-09-19 결정으로 v4에
   들어갔다 — `enabled=true`, `max_per_execution=10`, `review_cadence="weekly_mon_thu"`,
   `strata_rules.classification_proximity={contract_method: [제한경쟁, 일반경쟁]}`,
   `strata_rules.performance_similarity_proximity={rank_window: 25}`. **PoC용 값이며 운영
   전환 때 다시 정한다.**
4. **v4 policy·binding·generation config 발행 → 컨테이너 마운트.** 2026-09-19에 발행했다(S3b).
   **`model_digest`를 바꾸면 generation config도 함께 새로 발행해야 한다** — 워커가 동결된
   `generation-config.json`의 `model_revision`을 binding `model_digest`와 대조한다
   (`workers/order_plan.py:383-391`). v3는 이 대조에서 걸려 실행되지 않았다
   ([findings](../tracking/findings.md)).

   | 파일 | sha256 |
   |---|---|
   | `…/order-plan-screening-generation-config.v5.json` | `82ced6035d95313f889cd32cc3b5b414b98334f5f090745f0cedb0564804a405` |
   | `…/order-plan-screening-policy.v4.json` | `c5abe3e3fbd3a628486e8a3ee05ce009ac488c9b9df8e83a0f0c22cd6d877461` |
   | `…/order-plan-screening-phase0-binding.v4.json` | `682cb16dd2ac5ed622386a6cea42891633659f2d8073c3bcb6e1af419087790c` |

   generation config v5는 v4에서 `model_revision`(→ `5fa804ff…`)과 `method_version`
   (→ `vllm-qwen-order-plan-batch-nonthinking-v5`) 둘만 다르다. `docker/docker-compose.yml`의
   web(`:180-182`)·analysis-worker(`:250-252`) 마운트 세 줄과 `app/core/config.py`의
   `BIDOPS_C2_POLICY_PATH`·`BIDOPS_C2_BINDING_PATH`·generation config 기본 경로(`:308-312`)가
   같은 변경에서 v4·v5를 가리킨다. v2·v3 파일과 generation config v4는 고치지 않았다.
   **운영 반영은 아직이다**: compose 변경을 반영한 컨테이너 재생성과 아래 적재 CLI 실행이
   남아 있다. 운영 DB의 `c2-order-plan-screening-v3` 행은 버전+digest가 immutable이라 그대로
   `activation_candidate`로 남으며, 필요하면 retire CLI로 내린다.

   ```bash
   python -m app.screening.c2_policy load \
     --policy experiments/order-plan-screening/config/order-plan-screening-policy.v4.json \
     --binding experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v4.json \
     --created-by <담당자 이름>
   ```

5. **전송 승인(D-d).** binding 튜플(policy, binding, model_digest, allowlist) 단위 승인이다.
   `BIDOPS_C2_EXECUTION_ALLOWED=true`와 host 방화벽·egress 승인이 함께 필요하다.
   2026-09-19에 v4 binding의 `external_transport`로 기록했다 — `execution_allowed=true`,
   `approval_scope="per_binding"`, `approval_required_per_execution=false`,
   `approved_by="jechoi"`, `model_digest=5fa804ff…`(2026-09-11·09-15 서버 선언 revision).
   **환경변수와 방화벽·egress 승인은 아직 남아 있다.**
6. **후보 지정.** 기준 화면(`발주계획 선별 정책` 탭, `/order-plan-policies`)에서 draft 행을
   `activation_candidate`로 올린다(`POST /api/order-plan-screening/policies/candidate`).
7. **gold 게시일별 파생 회차 만들기.**

   ```bash
   python3 skills/bidops-collect/scripts/split_order_plan_run_by_day.py \
     --input-run data/runs/order-plans-20260827-20260830-retry1
   ```

   gold 625건을 게시일별 4개 회차(308·290·9·18건, `data/runs/gate-gold-<YYYYMMDD>-plans`)로
   나눈다. 원본은 고치지 않는다. 각 회차를 컨테이너에 복사하고 적재한다.

   ```bash
   scripts/compose.sh cp "data/runs/gate-gold-<YYYYMMDD>-plans" web:/app/data/runs/
   scripts/compose.sh exec web \
     python -m app.lifecycle.ingest.cli --run "gate-gold-<YYYYMMDD>-plans" --collection
   ```

   적재 결과의 `warnings`가 **네 회차 모두 빈 배열**인지 확인한다. C-2 실행 생성은 source run에
   `info`가 아닌 등급(`warning`·`error` 등)의 적재 경고가 하나라도 있으면 `409 source_run_incomplete`로
   거부하며(`info`는 통과하고 실행 생성 audit의 `passed_ingest_warnings`에 남는다), 응답 message는 code별
   고정 문구라 사유가 보이지 않는다. 사유는 web 컨테이너 로그
   (`scripts/compose.sh logs web | grep "c2 request rejected"`)와
   `GET /api/runs/<회차>/warnings`에서 읽는다.

   네 회차를 모두 적재한 뒤 게이트를 만든다(`POST /api/order-plan-screening/quality-gates`, 측정
   회차 4개를 `measurement_run_ids`에 고정. 요청 필드는 `docs/contracts.md`의
   `order-plan-quality-gate-create-request.v1`을 따른다).

   요청의 gold 관련 네 필드는 채점 도구가 계산한다. `scoring_input_sha256`은 **측정 전에
   고정되는 채점 입력의 digest**이고, 채점 때 다시 계산해 대조하면 게이트를 만든 뒤 gold나
   채점 도구가 바뀐 것을 잡는다.

   ```bash
   python3 scripts/score-c2-gate.py scoring-input \
     --gold data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv \
     --run-id gate-gold-20260827-plans --run-id gate-gold-20260828-plans \
     --run-id gate-gold-20260829-plans --run-id gate-gold-20260830-plans
   ```

   출력된 `gold_artifact_sha256`·`gold_manifest_sha256`·`gold_status`·`scoring_input_sha256`을
   게이트 요청에 그대로 넣는다. 임계값 4개와 `policy_sha256`·`binding_sha256`은 도구가 채우지
   않는다(사람 결정과 policy 행의 값이다).
8. **측정 실행 2회.** 같은 묶음(policy·binding·프롬프트·model digest·회사 역량)으로 두 번 돌려 둘
   다 통과해야 한다.

   ```bash
   BIDOPS_C2_GATE_ACTOR=<담당자 이름> scripts/run-c2-gate-measurement.sh \
     --policy-version <v> --gate-id <c2gate-...> --pass 1
   BIDOPS_C2_GATE_ACTOR=<담당자 이름> scripts/run-c2-gate-measurement.sh \
     --policy-version <v> --gate-id <c2gate-...> --pass 2
   ```

   이 스크립트는 게이트의 측정 회차를 순서대로 실행·폴링만 하고 채점하지 않는다.
9. **채점·기록.** 채점은 제품 밖에서 한다. `scripts/score-c2-gate.py`가 gold와 두 pass의
   실행 결과를 대조해 gate artifact 초안과 evaluations POST body 예시를 만든다. **도구는
   계산만 하고 아무것도 POST하지 않는다 — 사람이 artifact를 확인한 뒤 직접 제출한다.**

   ```bash
   # pass가 끝날 때마다 결과를 받아 둔다. 목록 API의 회차 모드는 그 회차의 "최신" 완료
   # 실행만 돌려주므로, pass 2를 돌리고 나면 pass 1의 결과는 REST로 읽을 수 없다.
   python3 scripts/score-c2-gate.py score \
     --gold data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv \
     --api http://127.0.0.1:18787 --pass1 <실행 id 4개> \
     --out reports/c2-gate-pass1.json --dump-results reports/c2-gate-pass1-results.json

   # pass 2까지 끝나면 pass 1은 dump에서, pass 2는 REST에서 읽어 함께 채점한다.
   # --expect-scoring-input-sha256에는 게이트에 기록한 값을 그대로 준다.
   python3 scripts/score-c2-gate.py score \
     --gold …/gold-adjudicated-full-population.tsv --gate-id <c2gate-...> \
     --expect-scoring-input-sha256 <게이트의 scoring_input_sha256> \
     --results-json reports/c2-gate-pass1-results.json \
     --api http://127.0.0.1:18787 \
     --pass1 <pass 1 실행 id 4개> --pass2 <pass 2 실행 id 4개> \
     --out reports/c2-gate-artifact.json --summary-out reports/c2-gate-summary.md \
     --body-out reports/c2-gate-evaluation-body.json
   ```

   도구는 예측 양성을 검토 후보(`stage1_status=selected` ∧ `qwen_relevance∈{relevant,uncertain}`),
   gold 양성을 `effective_relevance=관련`, 중요 누락을 `effective_priority=높음`인 gold 양성의
   누락으로 센다. recall·precision·중요 누락은 게시일별 결과를 합산하고 검토량은 게시일별
   최댓값(하루 기준)이며, 분모가 0이면 `null`로 남긴다. gold와 네 실행의 모집단이 다르면
   오류로 멈추고, 실행 상태가 `성공`이 아니거나 gold 양성에 `label_source=draft`가 남아 있으면
   artifact와 stderr에 경고로 남긴다(막지는 않는다 — 사람이 판단한다). `metrics_json`의
   `reference_full_window`는 게시일별 결과를 창 전체로 pool한 값이며(검토량은 창 전체 합계),
   ADR-0037의 단일 625건 batch와는 batch 구성이 달라 직접 비교값이 아니다.

   사람이 `--out` artifact와 요약을 확인한 뒤, 출력된 body(같은 artifact의 `artifact_sha256`를
   담고 있다)를 `POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations`로 기록한다.
   코드가 두 pass 중 나쁜 쪽 값을 넣고 판정한다(통과·미달·보류·미측정).
10. **활성화.** 활성화 화면(`발주계획 선별 정책` 탭)에서 policy digest·게이트 결과·런타임
    blocker를 확인한 뒤 승인한다. blocker가 하나라도 있으면 승인 단추는 비활성이다.
11. **자동 실행 켜기.** 같은 화면의 스위치(policy_version에 묶인 DB 행)를 켠다. 이것만으로는
    켜지지 않는다 — 운영자가 설치 때 한 번 환경 cap을 켜고 web을 재배포해야 한다.

    ```bash
    # env/model.env 또는 .env에 추가한 뒤
    BIDOPS_C2_DAILY_TRIGGER_ENABLED=true
    scripts/compose.sh \
      up -d --force-recreate web
    ```

    `docker/docker-compose.prod.yml`이 이 값을 web에 전달한다(base compose는 항상 `false`로
    고정한다). **policy를 교체하면 자동 실행이 멈춘다.** 스위치는 이전 버전에 묶여 있으므로 새
    버전에서 다시 켜야 한다.
12. **cron 발주계획 줄 설치.** `scripts/cron-daily-track.sh order-plans`(위 "cron 진입점"). 운영시작일부터 매 달력일. 앞선 날짜가 있으면 스크립트의
    `--from-date`/`--to-date`로 하루씩 따라잡고, 따라잡지 않기로 한 기간은
    `BIDOPS_DAILY_GAP_FLOOR_DATE`로 인정해 누락일 감지(exit 10)에서 뺀다.

**교체 없이 활성 policy를 내린다(예외).** 정상 경로는 위 10번 활성화가 이전 active 행을 같은
transaction에서 `retired`로 내리는 자동 교체다. 대체 버전 없이 자리를 비워야 할 때만 아래 명령을
쓴다 — 예외 운영 조치이며 사람 승인이 먼저다. SQL로 행을 직접 고치지 않는다(감사 기록이 남지
않는다).

```bash
scripts/compose.sh exec web \
  python -m app.screening.c2_policy retire \
    --policy-version <v> --retired-by <담당자 이름> --reason "<사유>"
```

`active` 행만 내려가고 `active_slot`이 비며 `activated_by`·`activated_at`·`quality_gate_status`는
이력으로 남는다. 같은 transaction에 `AuditEvent(action="c2.policy_retired")`가 쌓인다
(`replaced_by_policy_version`은 교체가 아니므로 `null`, `reason`·`via="cli"` 포함). 이미
`retired`면 아무것도 바꾸지 않고 `already_retired`를 출력하며 0으로 끝나고, `draft`·
`activation_candidate`는 `policy_not_active`로 거부한다(비 0). **활성 policy가 없어지면 일일 자동
실행은 `no_active_policy`로 꺼진다** — 다시 켜려면 새 버전을 활성화하고 그 버전의 스위치를 켜야
한다. 일일 자동 실행 스위치 행은 이 명령이 건드리지 않는다(append-only).

**트리거를 켜기 전 확인 항목(D-e).** 위 11을 켜기 전에 다음을 사람이 확인한다 — 수동 실행에서 본
요청 수·소요 시간·실패 분포, 나라장터 API 일일 할당량 여유, backup·restore와 stale execution
복구 훈련. 이 확인은 게이트 통과나 방화벽 승인을 대신하지 않는다.

### 일일 브리핑·Slack (RL-01, 2026-10-17)

평일 아침 한 번 후보를 고르는 브리핑이다(규칙은 [business-rules.md "브리핑 추천·반응"](../business-rules.md), 계약은 [contracts.md "브리핑"](../contracts.md)). LLM을 부르지 않는다. **Slack 전송은 기본 꺼짐이며 이 저장소는 cron을 설치하지 않는다.** 2026-10-17 격리 스택(`bidops-local`의 `bidops_rla`)에서 `--send` 없는 감독 시운전(T12: 생성·REST·반응·화면)을 했다([기록](../validation-runs/2026-10-16-rl/RL-01/README.md)). 실제 Slack 전송·Socket Mode 연결은 토큰이 없어 아직 하지 않았고, cron도 설치하지 않았다 — 아래는 절차와 예시다.

**배포(운영 변경이므로 직전에 사람 확인).** migration `0038_briefing`(테이블 3개, [contracts.md](../contracts.md) 참조)을 적용하고 `web`·`slack-worker` 이미지를 새로 올린다. 전체 백업과 `before-briefing-<날짜>` 롤백 태그를 먼저 남기고 배포 기록에 migration head를 적는다. 브리핑·반응은 DELETE 권한이 없어 되돌리려면 백업으로 복구한다. 이 단계의 승인은 아래 설정·전송·cron 설치로 이어지지 않는다.

**설정과 기동.**

1. `cp env/slack.env.example env/slack.env`로 만들고 값을 채운다(`env/*.env`는 gitignore). 키는 `BIDOPS_SLACK_ENABLED`(기본 `false`), `BIDOPS_SLACK_BOT_TOKEN`(`xoxb-`, 전송·갱신), `BIDOPS_SLACK_APP_TOKEN`(`xapp-`, Socket Mode), `BIDOPS_SLACK_CHANNEL_ID`(브리핑 전용 채널 하나), `BIDOPS_SLACK_ALLOWED_HOSTS`(기본 `slack.com,wss-primary.slack.com`, 정확 일치·빈 값이면 어떤 host도 허용하지 않음), `BIDOPS_PUBLIC_BASE_URL`(메시지의 레코드 링크 기준 주소, 비면 링크 없이 제목만)이다.
2. **fail closed.** `BIDOPS_SLACK_ENABLED=false`(기본)이거나 토큰·채널이 비어 있거나 호출 host가 허용 목록에 없으면 네트워크에 닿지 않는다. 전송기(`app/core/slack.py`)가 호출 전에 이 순서로 검사하고 어긋나면 CLI 출력의 `slack.skipped_reason`이 `slack_disabled`·`token_missing`·`channel_missing`·`host_not_allowed`가 된다. 다른 채널·hosted fallback은 없다. host 방화벽에서 `slack.com`·`wss-primary.slack.com`(443) 외 egress를 막은 뒤에만 켠다.
3. 운영 `.env`에 `BIDOPS_COMPOSE_FEATURES=slack`을 기록한다(Luna도 쓰면 `luna,slack`). selector가 `env/slack.env`를 `web`과 `slack-worker` 두 서비스에만 `env_file:`로 주므로 `--env-file`에는 넣지 않는다(기존 `.env`·`env/model.env`·`env/prespec-attachment.env`·`env/c2.env` 조합은 그대로).

   ```bash
   # prod 선택과 .env의 Slack capability를 모든 명령이 함께 읽는다.
   scripts/compose.sh \
     up -d --no-deps --no-build --force-recreate web slack-worker
   ```

   `env/slack.env`가 없으면 compose가 기동 전에 멈춘다. overlay 없이 올린 `slack-worker`는 기본값(꺼짐)이라 연결하지 않고 0으로 끝난다. 켜 놓고 토큰·채널·허용 host가 어긋나면 연결 전에 1로 끝나며 `restart: on-failure`가 드러낸다. 올린 뒤 플래그가 실제로 반영됐는지는 `scripts/compose.sh exec -T web printenv BIDOPS_SLACK_ENABLED`처럼 **값 하나씩** 본다. `scripts/compose.sh config`는 `env_file` 값을 펼쳐 토큰이 터미널에 나오므로 이 overlay를 붙인 채 쓰지 않는다.
4. **토큰 취급.** 토큰은 `env/slack.env`(권한 600)에만 두고 명령줄·compose 파일·이미지·로그·이 문서·채팅·티켓에 적지 않는다. 앱은 토큰을 `SecretStr`로만 다루며 로그·응답·오류에 넣지 않는다(실패는 `slack_send_failed`와 안전한 code만). 노출이 의심되면 Slack 앱에서 토큰을 폐기·재발급하고 `env/slack.env`를 고쳐 두 서비스를 다시 만든다. Slack 앱 설정(Socket Mode 사용·interactivity·bot의 `chat:write` 권한·채널 초대·app-level token `connections:write`)은 시운전에서 확인한다.

**실행: `scripts/run-daily-briefing.sh [--date YYYY-MM-DD] [--send] [--dry-run]`.** web 컨테이너 안에서 `python -m app.lifecycle.cli build-briefing --date <D> --json [--send]`를 실행한다(`BIDOPS_ENV` 기본 `dev`; 운영은 `prod`, `scripts/compose.sh exec -T web`로 실행 중인 컨테이너를 찾는다). `--date`는 브리핑 날짜 D(기본 오늘 KST)이고 수집 회차는 D-1이다. 토·일은 행 없이 `weekend`로 끝나고 같은 날 재실행은 기존 행을 그대로 둔다(`created=false`). `--dry-run`은 호출 순서만 출력하며 docker·web·Slack을 부르지 않는다(깨끗한 환경 `env -i HOME=… PATH=…`에서도 같다). 종료 코드:

| 코드 | 뜻 |
|---|---|
| 0 | 성공과 정상 건너뜀(`weekend`·`empty`·`already_sent`·`slack_disabled`·`token_missing`·`channel_missing`·`host_not_allowed`·`not_requested`). `collection_run_missing` 같은 수집 경고도 브리핑 상태로 보일 뿐 실패가 아니다 |
| 1 | 브리핑 생성 실패(`company_not_registered` 등, 행 없음). 그 밖의 비0 CLI·docker 종료 코드는 그대로 전달 |
| 2 | 인자 오류, docker·jq 없음 |
| 3 | **`slack_send_failed`.** CLI는 이 경우에도 0으로 끝나고 JSON `warnings[]`에만 코드를 싣는다. cron이 전송 실패를 성공으로 보지 않도록 스크립트가 JSON을 읽어 3으로 바꾼다. 브리핑 행은 남는다 |
| 4 | CLI가 0으로 끝났지만 stdout이 기대한 JSON이 아니어서 `slack_send_failed`를 배제할 수 없음(fail closed) |

**RL-03 연결.** `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED`가 꺼져 있으면(기본) 위 설명 그대로이고 브리핑 CLI는 LLM·Luna를 부르지 않는다. 켜면 새 브리핑이 만들어진 직후 같은 transaction에서 지난날 상한 초과 큐를 처리하고 사전규격 추천 항목마다 자동 판정 시작 조건을 평가한다(모델 호출은 이 CLI가 아니라 분석 worker가 한다). 이 hook의 실패는 브리핑 생성에 영향을 주지 않는다. 절차·승인·상한은 아래 "RL 카드 판정 운영"이 정본이다.

**재시도.** 전송이 실패하면(3) 원인(토큰·네트워크·채널)을 고친 뒤 **같은 명령을 `--send`로 다시 실행**한다. 이미 보낸 메시지는 저장된 ts로 건너뛰고 빠진 메시지만 보내며, 전부 보내면 `slack_sent_at`이 찍히고 이후 재실행은 `already_sent`다. 자동 따라잡기는 없다 — 빠진 날은 `--date <D>`로 사람이 메운다(창은 직전 브리핑 이후라 한 날을 건너뛰면 다음 브리핑에 함께 들어온다). 수집이 덜 끝난 날은 `collection_incomplete`로 만들어지고 이미 만든 행은 다시 만들 수 없으므로, 기준일 수집이 끝난 뒤에 실행한다.

**cron 예시(설치하지 않음).** 브리핑은 notices 트랙이 만든 D-1 회차와 발주계획 트랙의 C-2 결과를 읽으므로 **두 트랙이 끝난 뒤** 돈다. 줄은 두 트랙이 함께 쓰는 lock `daily.lock` 하나를 잡아(`flock -w`는 앞 실행이 끝나기를 기다린다) 수집·적재·C-2 실행 중에 끼어들지 않고, `timeout`으로 멈춘 실행을 끊는다. 시각은 운영 결정이다. 07:00 발주계획이 lock을 최대 2시간 기다릴 수 있으므로 09:00 브리핑의 1시간 대기가 끝날 수도 있다 — 그날은 사람이 다시 돌린다.

```cron
# 문서용 예시 — 설치되어 있지 않음. 감독 시운전을 마치고 사람이 crontab -e로 추가할 때만 참고한다.
# flock -w 3600 -E 75: 일일 트랙(공용 daily.lock)이 돌고 있으면 최대 1시간 기다린다(기다림이 끝나면 75로 끝나 로그에 남는다).
# timeout 30m: 멈춘 실행을 끊는다. 월~금만 돌리며 주말 처리는 CLI도 한 번 더 막는다.
0 9 * * 1-5 cd /path/to/bidops && BIDOPS_ENV=prod flock -o -w 3600 -E 75 ~/.local/state/bidops/daily.lock timeout 30m ./scripts/run-daily-briefing.sh --send >> ~/.local/state/bidops/logs/briefing-$(date +\%Y\%m).log 2>&1
```

**설치 전 감독 시운전(T12, 사람 확인 필요).** 순서: ① 깨끗한 환경에서 `env -i HOME=$HOME PATH=$PATH scripts/run-daily-briefing.sh --dry-run`으로 순서를 본 뒤 `--send` 없이 한 번 실행해 JSON·`GET /api/briefings/latest`·`/briefing` 화면을 확인한다. 이 실행은 그날 브리핑 행을 **실제로 만들고 지울 수 없으므로** 시운전 날짜가 곧 그날의 브리핑이다(행을 쓰지 않는 계산 확인은 컨테이너에서 `python -m app.lifecycle.cli build-briefing --dry-run`을 직접 준다). ② `GET /api/briefings/<날짜>/slack-preview`로 보낼 payload를 읽는다. ③ **테스트 채널**로 `--send`를 사람이 확인한 뒤 한 번 실행하고 메시지 1건과 버튼 클릭 → 화면 반영을 본다. ④ `GET /api/workload`의 `briefing_pending`이 화면의 대기 수와 같은지 본다. ⑤ 증거를 `docs/validation-runs/`에 기록한다. 차단 0이 된 뒤에만 cron을 설치한다. 가짜 docker·가짜 CLI로 도는 `tests/app/test_daily_briefing_script.py`는 호출 순서·인자·종료 코드만 증명하며 실제 컨테이너·실제 Slack 전송은 이 시운전이 증명한다.
