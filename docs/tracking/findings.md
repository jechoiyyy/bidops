# 미해결 문제

기준일: 2026-09-03

## 판정 입력에 참여 판단용 날짜·비율 항목이 없고 늘리려면 검증기 여섯 곳을 함께 열어야 한다 (2026-09-21, 미해결)

- 재현 조건: 실무자가 참여 여부를 정할 때 보는 자격등록 마감, 공동수급협정 마감, 설명회 일시, 입찰 개시,
  낙찰하한율, 사전규격 납품기한은 어느 화면·어느 API에도 없다. 수집기 정규화 결과에 그 항목이 없기 때문이며
  화면·투영만으로는 채울 수 없다.
- 영향: 항목 하나를 더하려면 판정 입력 계약의 **닫힌 검증기 전체**를 한 변경으로 열어야 한다 — 수집기
  (`skills/bidops-collect/scripts/collect_notices.py`) → `web/backend/app/lifecycle/ingest/contracts.py` →
  `loader.py:669-725`(null 생략 선택 키 집합, 옛 회차의 digest 보존) →
  `web/backend/app/screening/orchestrator.py:1278,1341`(선택 lifecycle 키와 `opening_at` aware 검사) →
  `skills/bidops-screen/scripts/build_screening_results.py:583`(선택 projection 목록) →
  `loader.py:2934-2946,3052-3082`(`_SCREENING_*_KEYS` 허용 키 집합). 한 곳만 열면 기존 회차 적재가 깨지거나 새
  필드가 조용히 버려진다. 과거 회차는 소급하지 않으므로 채워지지 않는 칸이 반드시 생긴다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 7(`docs/0921_practitioner-screens/intent.md` §3·§4)로 실무
  화면 고도화 범위 밖으로 분리했다. **미수집 / 원문 빈 값 / 해석 실패 / 정상**의 4상태 계약을 먼저 설계해야
  한다. 그 계약 없이 필드만 더하면 빈 값이 "그런 조건이 없음"으로 읽혀
  [ADR-0065](decisions/0065-practitioner-ops-information-boundary.md) 결정 4(뜻이 다른 빈 값을 합치지 않는다)를
  바로 깬다.
- 후속: 4상태 계약 확정 → 위 여섯 지점을 한 변경으로 확장(`schema_version` 올림과 이전 소비자 처리 포함) →
  과거 회차는 `미수집`으로 표시 → `docs/contracts.md`에 등록. 착수 시점은 사람이 정한다.

## 발주 예정월·사전규격 등록 후 경과를 알리는 재확인 신호가 없다 (2026-09-21, 미해결)

- 재현 조건: 발주 예정월이 지나도, 사전규격이 등록된 지 오래돼도 화면이 아무 말을 하지 않는다. 후보 임계값은
  발주 예정월 + 2개월, 사전규격 등록 후 45일이다.
- 영향: 임계값의 경험적 근거가 없다. 근거 없이 "지연"이라고 적으면 확인되지 않은 사실을 단정하는 표시가 되므로
  이름은 "재확인 알림"이 맞다. 효과는 두 선택지 중 하나다. ⓐ **배지 전용** — 행·상세에 표식만 그리고 구역·
  집계는 건드리지 않는다. ⓑ **`action_reasons`에 사유 코드 추가** — 이 경우 분류식
  (`web/backend/app/lifecycle/services/opportunity_queries.py:375-381`)에 의해 열린 추적 상태의 건이 자동으로
  `조치 필요` 구역으로 올라가고, 행의 주 행동 우선순위와 칩 순서
  (`web/frontend/src/components/opportunities/trackingFlow.ts:157-171`)에도 자리를 잡아야 한다. 같은 모양의
  선례가 `hold_overdue`다(`opportunity_queries.py:355`의 술어 → 같은 분류식 → `trackingFlow.ts`의 라벨·우선순위).
  ⓑ는 대시보드 건수와 사업 추적 구역 건수를 함께 움직이므로 되돌리기 어렵다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 7로 실무 화면 고도화 범위 밖으로 분리했다. 임계값 근거,
  해제 조건(후속 단계가 연결되면 알림을 끄는가), 월 경계 정의(발주 예정은 월 단위라 "+2개월"의 기준일이
  모호하다)가 모두 미정이다.
- 후속: 실제 데이터로 임계값 근거를 관측한 뒤 ⓐ/ⓑ를 정한다. ⓑ면 `OpportunityActionReason` union·라벨·
  우선순위·필터·대시보드 집계를 한 변경으로 바꾸고 `docs/contracts.md`에 등록한다.

## 발주처 담당자 연락처가 정규화 스키마 밖에 남아 있다 (2026-09-21, 결정 보류)

- 재현 조건: 발주계획 원문 응답에는 담당자 정보가 들어 있으나 `OrderPlan` 정규화 컬럼에는 없다.
  `web/backend/app/lifecycle/models.py:266-273`의 docstring이 그 경계를 적는다 — "The columns below are the
  fields selected by the measured order-plan normalizer.  Contact fields and the remaining response payload stay
  in ``raw_source``/``unknown_fields_json`` rather than becoming guessed schema." 따라서 값은 보존되지만 명명된
  projection이 없어 API·화면에 나올 수 없다.
- 영향: 발주처에 확인할 것이 생겼을 때 실무자가 화면 밖(원문 포털)으로 나가야 한다. `docs/PRD.md` §5.4는
  "발주기관 연락·협상·알림 발송"을 명시적 제외로 두고 있는데, 그것은 **시스템이 대신 연락하는 기능**의 제외이지
  사람이 볼 연락처를 화면에 두는 것을 금지한 문장이 아니다. 두 가지를 같은 것으로 읽으면 결정이 근거 없이 닫힌다 —
  이 항목은 PRD가 이미 금지한 것이 아니라 **아직 결정하지 않은 것**이다.
- 지금 해결하지 않은 이유: 2026-09-21 사용자 결정 8(`docs/0921_practitioner-screens/intent.md` §3)로 이번 범위에서
  빼고 후속 결정으로만 기록하기로 했다. 측정된 정규화 스키마를 넓히는 것은 기존 레코드의 저장 identity에 영향을 줄
  수 있고(`docs/engineering-notes.md` "선택 필드를 계약 모델에 더하면 기존 레코드의 저장 identity가 바뀐다"),
  개인 연락처를 API 응답·로그·감사에 어디까지 실을지가 먼저 정해져야 한다.
- 후속: 표시 여부와 범위(이름 / 부서 / 전화 / 이메일)를 사람이 정한다. 표시하기로 하면 `raw_source`에서 명명된
  projection으로 올리고, 로그·감사·오류 응답에 넣지 않는 규칙을 `docs/contracts.md`와 함께 적는다. 연락 기능
  자체는 PRD §5.4대로 계속 비목표다.

## 입찰공고 `budget`이 세 원문 필드의 fallback이라 무엇을 본 값인지 알 수 없다 (2026-09-21, 미해결)

- 재현 조건: `skills/bidops-collect/scripts/collect_notices.py:612`가
  `"budget": first(record, "asignBdgtAmt", "presmptPrce", "bsisAmount")`로 배정예산 → 추정가격 → 기초금액을 순서대로
  고른다. 바로 다음 줄(`:613`)의 `estimated_price`는 `presmptPrce` 하나다. 저장된 `budget` 값만 보면 셋 중 어느
  원문 필드에서 왔는지 알 수 없고, 두 번째 후보로 떨어진 공고는 `budget`과 `estimated_price`가 같은 값이 된다.
- 영향: 화면이 이 값을 '배정예산'이라 부르면 사실이 아닌 라벨이 된다. 그래서 실무 화면 고도화는 `예산(원문 제공
  금액)`과 `추정가격`을 따로 보이고 값이 같아도 합치지 않는 선에서 멈췄다(`docs/0921_practitioner-screens/spec.md`
  §6.3, [ADR-0065](decisions/0065-practitioner-ops-information-boundary.md) 결정 4). 두 값이 같을 때 그것이 "실제로
  같은 금액"인지 "fallback으로 같아진 것"인지는 여전히 화면에서 구분되지 않는다.
- 지금 해결하지 않은 이유: 출처를 남기려면 수집기 정규화 출력에 `budget_source` 같은 필드를 더해야 하고, 그러면 위
  "판정 입력에 참여 판단용 날짜·비율 항목이 없고…" 항목과 같은 닫힌 검증기 사슬과 과거 회차 소급 문제가 그대로
  따라온다. 2026-09-21 사용자 결정으로 이번 범위 밖이다(intent §4).
- 후속: 위 항목의 4상태 계약과 함께 `budget_source`(또는 세 금액을 각각 보존하는 형태)를 정한다. 과거 회차는
  소급하지 않고 `미수집`으로 남는다. 그때까지 화면·문서는 이 값을 '배정예산'이라 부르지 않는다.

## 발주계획 일괄 추적 시작에는 record backfill도 선택 상한도 없다 (2026-09-20, 미해결)

- 재현: 단건 `PATCH /api/opportunities/{id}/tracking-status`는 `계속 추적`·`보류`로 바뀔 때 router에서
  `_backfill_tracked_records`를 부른다(`app/lifecycle/routers/opportunities.py`). 일괄
  `POST …/order-plan-tracking/bulk-start`의 서비스(`order_plan_bulk_tracking.py`)는 commit 뒤
  `tracking_decision_changed` hook만 부르고 backfill은 부르지 않는다. 같은 요청 스키마의 `order_plan_ids`는
  `min_length=1`뿐이고 상한이 없다.
- 영향: 같은 `계속 추적` 결정이 단건이냐 일괄이냐에 따라 선별 적재로 빠져 있던 연결 레코드의 backfill 여부가
  갈릴 수 있다(의도인지 미확인). 상한이 없으므로 한 요청이 수천 owner를 한 transaction에서 잠글 수 있다.
- 지금 해결하지 않은 이유: 일괄 추적 종료(ADR-0063) 작업 중 코드를 읽다 확인했다. 종료는 backfill 대상
  상태가 아니라 이 차이의 영향을 받지 않고, bulk-start v1은 계약 불변으로 두기로 했다. bulk-end에만 200건
  상한을 뒀다.
- 후속: backfill 누락이 의도인지 0917 사업 추적 계획의 선별 적재 규칙과 대조한다. 상한은 v2 요청 스키마를
  발행할 때 함께 정한다.

## 목록 행 체크박스의 클릭 대상이 24px에 못 미친다 (2026-09-20, 수용됨)

- 재현: 1280×800, `/order-plans`·`/pre-specs` 목록 행 체크박스의 `getBoundingClientRect()`가 14.39×14.39 CSS px다
  (`--bo-ui-scale: 0.9` 적용 뒤). 선택 툴바 단추는 25.19px로 기준을 넘는다.
- 영향: WCAG 2.2 AA "Target Size (Minimum)"의 24 CSS px에 못 미친다. 주변 간격으로 충족하는 예외에 해당할
  여지는 있으나 행 자체도 클릭 대상이라 단정하지 않는다. 탐색 화면 통일(ADR-0062) 이전에도 같은 값이었다.
- 지금 해결하지 않은 이유: `box-sizing: border-box`와 명시 width/height 때문에 padding으로는 대상이 커지지
  않는다. `--size-element-sm`(약 25px)로 올리면 승인 시안의 체크박스 모양과 픽셀 기준선이 함께 바뀐다.
- 2026-09-20 사용자가 그대로 두기로 했다. 확대한다면 시안을 먼저 확인한다.

## 일일 발주계획 트랙이 C-2 단계에서 매일 409로 죽었다 (B-1)

- 확인: 2026-09-19 (독립 검증)
- 상태: **해결** (2026-09-19, `feat/poc-daily-run-id`. 운영 반영은 병합 뒤)
- 재현 조건: `scripts/run-daily-lifecycle.sh --track order-plans`가 회차 id를 디렉터리 이름
  (`lifecycle-<YYYYMMDD>-plans`)으로 만들어 C-2에 넘겼다. 적재가 만드는 `Run` 기본키는
  `<디렉터리>--<generated_at>Z`(`app/core/run_id.py deterministic_run_id`,
  `lifecycle/ingest/loader.py:4468`)이므로 `POST /api/order-plan-screening/executions`가 409
  `source_run_incomplete`("source run을 찾을 수 없습니다")로 답하고 스크립트가 exit 2로 끝났다.
  운영 web에서 제품 코드를 직접 불러 재현했다 — 디렉터리 이름은 ERROR, 정규 id는 OK.
- 원인: 회차 id 표기의 **비대칭**. `GET /api/runs/{id}`만 `LIKE '<id>--%'`로 디렉터리 이름을 풀어
  주고(`lifecycle/routers/common.py get_run`), C-2는 `session.get(Run, source_run_id)` 정확
  조회다(`screening/services/order_plan_screening.py`). 그래서 스크립트의 회차 존재 확인은 200을
  받고 바로 다음 C-2 호출이 409로 죽었다. 같은 이유로 `GET
  /api/order-plan-screening/executions?source_run_id=<디렉터리>`가 늘 0건이라 attempt가 매번 1로
  리셋됐고, 감사 표본 draw·`run-daily-c2.sh <회차>` 복구 경로도 같은 값을 쓰고 있었다.
- 테스트가 못 잡은 이유: 스크립트 테스트의 가짜 web이 `Run` 행을 **디렉터리 이름**으로 등록해
  실제 API 계약과 어긋난 지점을 굳혀 놓았다(`docs/engineering-notes.md`의 재발 방지 항목).
- 해결: 스크립트가 적재 뒤(또는 기존 회차를 이어받을 때) `GET /api/runs/<디렉터리>`의 `run_id`를
  받아 C-2의 모든 호출에 그 값을 쓴다. 제품 API 계약은 바꾸지 않았다. 한 디렉터리에 `Run` 행이 둘
  이상이면(회차 산출물이 바뀌어 다시 적재된 흔적) 고르지 않고 fail closed로 멈춘다. 가짜 web을 실제
  계약대로(기본키 모양, alias 해석, C-2는 정규 id만) 고친 뒤 수정 전 스크립트가 23건 실패하는 것을
  확인하고 고쳤다.
- 남은 공백: 운영 DB에 `lifecycle-*` 회차의 C-2 실행은 아직 0건이라 request_id(uuidv5) 입력이
  정규 id로 바뀐 데 따른 호환 부담은 없다. 실제 web에서의 확인은 병합 뒤 한 번 필요하다.

## 발주계획 회차에 `info` 등급 경고 하나만 있어도 C-2가 영구히 막힌다 (W-2)

- 확인: 2026-09-19 (독립 검증)
- 상태: 미해결 — 등급별 차단 기준이 사람 결정 대기
- 재현 조건: 적재가 그 회차에 `IngestWarning`을 한 줄이라도 남기면
  `screening/services/order_plan_screening.py`의 source run 검사가 **등급을 보지 않고**
  `source_run_incomplete`으로 거부한다. `info`도 `warning`도 `error`와 같게 취급된다. 경고는
  재적재 때 지워지고 같은 산출물이면 같은 경고가 다시 생기므로, 사람이 코드나 DB를 건드리지 않는 한
  그 회차는 영구히 판정할 수 없다.
- 영향: 수집은 됐는데 그날 발주계획이 하루도 판정되지 않고, 일일 스크립트는 exit 비0으로 끝난다.
  회차 원본은 불변이라 "다시 수집"으로도 풀리지 않는다(같은 경고가 다시 난다).
- 지금 해결하지 않는 이유: 어느 등급·어느 code가 판정을 막아야 하는지는 업무 결정이다. 검사 주석이
  적은 대로 "경고가 있으면 계약대로 적재되지 않은 것"이라는 해석 자체가 정책이며, code별 예외를
  넣기 시작하면 진짜 부분 적재까지 통과한다.
- 후속 방향: 차단 등급(예: `error`만)과 그때 화면에 무엇을 보여 줄지를 정한 뒤 검사 조건을 바꾸고,
  통과시킨 경고를 실행 metadata에 남긴다. 그 전에는 회차별로 사람이 경고를 읽고 판단한다.

## 수집 실패일·중단일은 자동으로 따라잡지 않는다 (W-3·W-4)

- 확인: 2026-09-19 (독립 검증)
- 상태: 미해결 — 설계대로의 한계이며 자동 보정을 넣지 않는다
- 재현 조건: `scripts/run-daily-lifecycle.sh`는 기준일 하루만 돈다(기본값 전일). 수집기가 실패하면
  그 트랙은 exit 비0으로 멈추고, 호스트(WSL)가 꺼져 있어 cron 줄이 아예 돌지 못한 날도 아무 기록이
  남지 않는다. 다음 날 실행은 그 전날을 돌아보지 않는다.
- 영향: 발주계획 트랙은 창이 **1일**이라 빠진 날의 발주계획이 어느 회차에도 들어오지 않는다. 공고
  트랙은 창이 4일이라 하루 빠져도 다음 날 창이 덮지만, 이틀 이상 연속으로 빠지면 같은 손실이 난다.
  손실은 사람이 `--from-date/--to-date`로 그 날짜를 다시 돌려야 회복된다(회차 디렉터리는 날짜로
  만들어지므로 나중에 돌려도 그날 몫을 받는다).
- 지금 해결하지 않는 이유: "빠진 날을 자동으로 찾아 돌린다"는 것은 스케줄러 기능이고, 스케줄러·
  always-on은 기본 비활성이라는 원칙에 걸린다. 빠진 날을 어디까지 거슬러 볼지도 사람 결정이다.
- 후속 방향: 알림이 생기면 "어제 회차 디렉터리가 없다"를 그 알림의 첫 항목으로 넣는다. 그 전에는
  운영자가 `data/runs/lifecycle-*`의 날짜 연속성을 눈으로 확인하고 `--from-date/--to-date`로
  따라잡는다.

## 워커가 죽으면 `대기` 실행이 닫히지 않고 남는다 (W-5, 제품 쪽)

- 확인: 2026-09-19 (독립 검증)
- 상태: 미해결(제품) — 스크립트 쪽 가시성만 2026-09-19에 붙였다
- 재현 조건: 분석 워커가 실행을 집어 들기 전에 죽으면 그 실행은 `대기`로 남는다. 제품의 stale 회수는
  `실행 중`·`중지 요청`(`ACTIVE_STATUSES`)만 중단으로 닫고 `대기`는 대상이 아니다. 게다가 회수는
  워커가 다음 작업을 집을 때(`_claim`) 도는 코드라 워커가 아예 없으면 아무것도 회수되지 않는다. 그 회차는 계속
  `active_execution_exists`로 읽히고, 일일 스크립트는 매일 exit 0으로 건너뛴다.
- 영향: 사람이 화면을 따로 보지 않으면 "매일 정상 종료"처럼 보이면서 그날부터 판정이 멈춘다.
- 지금 해결하지 않는 이유: `대기`를 자동으로 닫는 것은 큐 회수 규칙의 변경이다 — 워커가 잠시 없는
  상태와 죽은 상태를 구분하는 기준(무엇을 근거로 몇 초)이 필요하고, 자동 resume·무한 재시작을 만들지
  않는다는 실행 불변 조건과 함께 봐야 한다.
- 지금 한 것: 일일 스크립트가 이 스킵을 낼 때 막고 있는 실행의 id·상태·경과를 출력하고, 경과가
  `BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS`의 2배를 넘으면 exit 비0으로 끝나 사람이 보게 했다. 제품
  워커의 회수 범위는 바꾸지 않았다.
- 후속 방향: 큐 회수 규칙을 정할 때 `대기`의 최대 체류 시간과 그때의 상태(`중단됨` + 사유)를 함께
  정한다.

## model_digest를 바꾸면 generation config도 함께 새로 발행해야 한다

- 확인: 2026-09-19
- 상태: **해결** (2026-09-19, generation config v5 + policy·binding v4 발행)
- 재현 조건: policy·binding v3(`model_digest=5fa804ff…`)를 적재·후보 지정하고 게이트 측정
  pass 1을 돌리면 워커가 모델 호출 전에 `binding_mismatch`로 실패한다. 동결된
  `generation-config.json`(= `order-plan-screening-generation-config.v4.json`, sha256
  `1fd2f511…`, binding `stage2_binding.generation_config_sha256`이 고정)의 `model_revision`이
  `6ae70ca3…`이기 때문이다. 워커는 `generation.model_revision == stage2.model_digest`를 요구한다
  (`workers/order_plan.py:383-391`).
- 원인: `model_digest`는 policy `stage2`·`bindings`, binding `stage2_binding`, **그리고 승인
  generation config 안**까지 네 곳에 있는데 v3 발행이 앞의 셋만 바꿨다. 발행 검증이 적재 CLI와
  조회 blocker만 돌리고 **워커의 파일 묶음 검증을 돌리지 않아** 발행 시점에 드러나지 않았다.
  적재 CLI(`c2_policy.load`)와 `assess_policy`는 generation config를 아예 읽지 않는다.
- 해결: generation config v5(v4에서 `model_revision`·`method_version`만 교체)를 발행하고
  policy·binding v4가 그것을 참조하게 했다. 발행 전에 서비스가 동결하는 것과 같은 6개 파일 묶음을
  임시 디렉터리에 만들어 워커의 `_load_binding_inputs`·`_load_ranking`을 실제로 호출해 통과를
  확인했고, generation config만 v4로 되돌리면 같은 `binding_mismatch`가 재현되는 것도 확인했다.
- 재발 방지: **policy·binding을 새로 발행할 때는 워커 파일 묶음 검증을 건식으로 돌린다.** 적재
  CLI 통과와 조회 blocker 소멸은 실행 가능성을 증명하지 않는다 — 둘 다 stage-2 승인 입력
  (capabilities·prompt·generation config)을 읽지 않기 때문이다.
- 남은 공백: 운영 DB의 `c2-order-plan-screening-v3` 행과 그 게이트(`c2gate-203ab7a5…`)는
  버전+digest가 immutable이라 남는다. 실행에 쓰지 않으려면 retire CLI로 내린다.

## 승인 사설 vLLM이 weight revision을 노출하지 않는다

- 확인: 2026-09-03
- 상태: **해결** (2026-09-03, [ADR-0042](decisions/0042-c2-model-revision-declared-at-deployment.md))
- 재현 조건: 승인 endpoint `http://192.168.0.139:58765/v1`의 chat completion 응답 최상위
  key는 `choices, created, id, kv_transfer_params, model, object, prompt_logprobs,
  prompt_text, prompt_token_ids, service_tier, system_fingerprint, usage`뿐이고
  `model_revision`도 `revision`도 없다. `/v1/models`도 `id`·`root`·`created`·
  `max_model_len`·`permission`만 준다. OpenAI 호환 vLLM에는 weight revision을
  노출하는 면이 없다.
- 당시 영향: 제품 adapter가 매 응답의 `model_revision`을 binding digest와 대조하고
  있어 모든 batch가 `model_mismatch / model_revision_invalid`로 거부됐다.
  발주계획 1,040건 회차에서 stage 1은 300 선정 / 740 탈락으로 정상 완주했고 stage 2는
  batch 1·2가 각각 약 224초 생성 뒤 거부됐다. 결과는 `selected/rejected` 50건으로
  보존됐고 자동 보정은 없었다.
- 해결: ADR-0042로 검증을 배포 시점 1회 선언 대조로 되돌렸다. 배포가
  `BIDOPS_VLLM_MODEL_REVISION`으로 운영자 확인 digest를 선언하고 adapter 생성 시
  binding과 대조한다. 응답의 `model_revision`은 **있으면 대조하고 없으면 통과**한다.
- 남은 공백 1: **digest 계산 방법이 이 저장소 어디에도 없다.** 런북은 "서버 운영자가
  제공한 64자 model artifact digest"라고만 하고, safetensors 파일들의 sha256인지
  manifest의 sha256인지, 어떤 순서로 묶는지가 없다. 따라서 "지금 서버의 digest가
  여전히 `6ae70ca3…`인가"를 이 저장소만으로 다시 확인할 수 없다. 운영자에게 계산
  방법을 받아 문서로 고정해야 한다. 그때까지 이 선언과 실제 적재된 weight의 일치는
  사람의 확인에 달려 있다.

## C-2 stage 2 구현이 측정된 방법과 어긋나 있었다

- 확인: 2026-09-03
- 상태: **해결** (2026-09-03, [ADR-0044](decisions/0044-c2-stage2-matches-the-measured-method.md))
- 재현 조건: 제품이 보내던 요청이 ADR-0037이 625건으로 측정한
  `experiments/order-plan-screening/scripts/methods.py::QwenAdapter._score_batch`와
  네 곳에서 달랐다. ① `plan_id`/`company` vs 승인 prompt가 계약한 `item_id`/
  `company_capabilities` ② `json_object` vs strict `json_schema`
  ③ `chat_template_kwargs`가 `extra_body`에 중첩돼 vLLM이 무시
  ④ generation config를 읽지 않고 하드코딩.
- 원인: stage 1 BM25와 병합은 `skills/` 스크립트를 subprocess로 부르지만 stage 2만
  백엔드가 재구현했고, 그 구현을 실제 서버로 검증한 적이 없었다. 기존 테스트는 오히려
  잘못된 모양(`extra_body` 중첩)을 단언해 네 건을 모두 통과시켰다.
- 해결: 요청 조립을 측정된 방법과 같게 맞추고, 승인 generation config를 아티팩트로
  복원해 실제로 읽게 했으며, 두 body가 같은지 단언하는 적합성 테스트를 넣었다.
  발주계획 1,040건 회차 재실행에서 300/300 완료·실패 0건.
- 남은 공백: BM25와 Qwen 요청 조립이 `experiments/`와 `web/backend/`에 각각 존재한다.
  적합성 테스트가 드리프트를 잡지만 구현이 하나가 된 것은 아니다. stage 2를 stage 1처럼
  subprocess 계약으로 내리는 것은 raw 응답 전달과 실패 코드 계약을 새로 설계해야 해서
  이번 범위에서 하지 않았다.

## legacy v3 screening orchestrator가 부분 성공 대신 실패를 게시한다

- 확인: 2026-09-03
- 상태: **2026-09-07 수정 · 관련 회귀 7건 통과**
- 재현 조건: clean `main`(`6788c4f`)에서 `pytest tests/test_screening_orchestrator.py`를
  (모듈 이주 뒤 `pytest tests/screening/test_screening_orchestrator.py`) 돌리면
  `test_full_run_continues_after_one_notice_failure_and_publishes_partial` 과
  `test_partial_rejudgment_retains_prior_projection_and_revision` 이
  `'실패' == '부분 성공'` 으로 실패한다(34 passed, 2 failed, 약 53초).
- 부하 의존 flake가 아니다. 단독 실행과 전체 실행에서 같은 두 건이 재현되고,
  변경을 stash한 clean tree에서도 같다.
- 영향: 한 건이 실패한 회차의 부분 게시 경로가 성공으로 마감되지 않는다.
  C-2와 무관한 legacy 판정 경로다.
- 원인: C-1과 C-2가 모두 쓰는 `screening-failures.json` 파일명만으로 C-2 회차를
  주장해 C-1 부분 산출물에 없는 `source_run_id`를 요구했다. C-1 failure schema는
  C-1 적재기의 전체 입력 검증으로 보내고, 다른 C-2 식별자와 손상된 파일의 차단은 유지한다.

## 감독 작업 transcript에 G2B API key가 노출됐다

- 확인: 2026-08-31
- 상태: **키 회전 필요**
- 재현 조건: T14 하네스 진단을 위임받은 첫 감독 작업자가 환경을 점검하며
  `BIDOPS_G2B_API_KEY`의 실제 값을 Orca 작업 transcript에 출력했다.
- 영향: 해당 transcript에 접근할 수 있는 주체가 기존 key를 알 수 있으므로 기존 key를
  더 이상 안전하다고 간주할 수 없다. key 값은 저장소 파일·테스트 출력에 다시 기록하지
  않았고, 후속 작업은 외부 호출을 비활성화한 허용 목록 환경에서만 실행했다.
- 즉시 대응: 영향받은 dispatch를 실패·봉인하고 새 안전 작업으로 교체했다.
- 남은 조치: 승인된 외부 secret manager에서 해당 key를 폐기·재발급하고, 영향받은
  transcript·접근 log의 조회 범위를 감사한다. 현재 작업에는 secret manager 권한이 없어 회전을
  수행하지 못했다.

## 저장소 `.env`가 host 백엔드 테스트를 깨뜨리고 90배 느리게 만든다

- 확인: 2026-08-29
- 상태: **해결** (2026-08-29)

`web/backend/app/core/config.py:71`(당시 `app/config.py:33`)이 `env_file=DEFAULT_BIDOPS_ROOT / ".env"`로 저장소 루트의
`.env`를 읽는다. 그 파일에는 컨테이너 안에서만 유효한 값이 들어 있어서 host에서 pytest를
돌리면 실패와 지연을 만든다.

**재현**: HEAD를 별도 worktree(`git worktree add`)로 떼면 `.env`가 gitignore 대상이라 딸려오지
않는다. 같은 코드에 `.env`만 넣고 빼서 비교했다.

| 조건 | 결과 |
|---|---|
| `.env` 없음 | `tests/agents/test_document_preparation.py` 9 passed in **4.5초** |
| `.env` 있음 | 같은 파일 6 failed, 3 passed in **404초** |

원인을 키 단위로 좁혔다.

- **실패 6건**: `BIDOPS_OBJECT_STORE_BACKEND=minio`. 이 세 줄만 넣어도 재현된다(5.2초, 6 failed).
  host에는 MinIO가 없다.
- **404초 지연**: object-store와 ClamAV 키만으로는 재현되지 않는다(5.4초). 전체 `.env`가 있어야
  나오므로 MinIO 자격증명까지 있어야 실제 접속을 시도하며 재시도하는 것으로 보인다. 미확정.

`.env`가 있는 원래 트리에서는 `test_quality_gate.py`·`test_deep_reviews.py`·
`test_document_bundles.py`가 90초 안에 끝나지 않아 행으로 오인했다. 깨끗한 worktree에서는
각각 108초·10.8초·12.6초에 **전부 통과한다.**

**영향**: `.env`가 있는 상태의 host 테스트 결과는 baseline으로 쓸 수 없다. 실패 12건 중 6건이
`.env` 때문이고, 실행 시간도 신뢰할 수 없다.

**해결 방향**: `docker-compose.yml`이 `BIDOPS_CLAMAV_HOST`·`BIDOPS_OBJECT_STORE_*`를
이미 106~110행과 163~165행에서 선언한다. 공통 `.env`에 중복으로 둘 이유가 없으므로 제거한다.
같은 이유로 `BIDOPS_ROOT`·`BIDOPS_DATA_DIR`·`BIDOPS_ATTACHMENTS_DIR`은 2026-08-29에 이미
제거했다(그 셋은 `PermissionError: /app`으로 수집 단계에서 48개 파일을 전멸시켰다).

**적용 결과 (2026-08-29)**: `.env`와 `.env.example`에서 `BIDOPS_OBJECT_STORE_*`와
`BIDOPS_CLAMAV_*`를 제거했다. `BIDOPS_ROOT`·`BIDOPS_DATA_DIR`·`BIDOPS_ATTACHMENTS_DIR`은
같은 날 먼저 제거했다.

| | 제거 전 | 제거 후 |
|---|---|---|
| 전체 스위트 | 25분 초과로 완주 실패 | **3분 36초** |
| 통과 | 484 (느린 3개 제외 측정) | **711** |
| 실패 | 12 | **6** |

이 시점에 남았던 실패 6건은 `.env`와 무관했다. 2026-08-31에
`tests/test_integration_t14.py` 환경 실패는 pytest 수집 전 일회용 PostgreSQL 17·fresh DB·
필수 환경변수를 구성하는 하네스로 해결했다. profile 2건은 승인 Git blob 부재 시
snapshot을 만들지 않는 fail-closed 계약을 검증하도록 분리했으며, 승인 객체 부재 자체는
아래 미해결 항목으로 남아 있다.

**남은 미확인**: 404초 지연의 정확한 원인 키는 특정하지 못했다. object-store와 ClamAV 키만
넣었을 때는 5.4초에 끝났고 전체 `.env`가 있어야 재현됐으므로, MinIO 자격증명이 관여하는 것으로
보이나 확인하지 않았다. 지연 자체는 사라졌으므로 추적을 중단한다.

## 사전규격 정규화가 원문의 첨부·SW대상·업무구분을 버린다

- 재현 조건: `skills/bidops-collect/scripts/collect_notices.py`의 `normalize_prespec`을 `HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc` 응답에 적용하고 결과의 `url`과 `attachments`를 확인한다. 실측은 [`20260828-lifecycle-linkage-survey.md`](../validation-runs/20260828-lifecycle-linkage-survey.md)에 있다.
- 증상: `url`이 읽는 `specDocFileUrl`과 `bfSpecDtlUrl`이 응답에 존재하지 않아 항상 `None`이 된다. 실제 규격서 URL은 `specDocFileUrl1`~`specDocFileUrl5`이며 650건 중 586건이 최소 하나를 갖는다. `attachments`는 빈 배열로 고정돼 있어 과업지시서·제안요청서를 한 건도 확보하지 못한다. `swBizObjYn`(650/650), `bsnsDivNm`(650/650), `bidNtceNoList`(29/650)도 정규화에 담기지 않는다.
- 영향: 사전규격 심층 검토의 입력원이 성립하지 않는다. 문서 묶음을 만들 원문이 없으므로 [ARCHITECTURE.md의 사전규격·문서 준비 흐름](../ARCHITECTURE.md#53-첨부와-문서-준비)이 현재 수집 결과만으로는 시작될 수 없다. SW사업대상과 업무구분이 저장되지 않아 수집 대상 선별의 근거도 남지 않고, 공고 전환 감지에 쓸 `bidNtceNoList`도 유실된다.
- 상태: **해결** (2026-08-30, T-4). `PPSSrch`로 전환하고 `specDocFileUrl1~5`를 `attachments`로, `swBizObjYn`·`bsnsDivNm`을 `qualification_flags`로, `bidNtceNoList`를 `lifecycle`로 옮겼다. 응답에 없는 필드를 읽던 `url` 경로는 제거했다. 원문에 URL이 없는 건은 `unknown_fields`에 `attachments`로 남는다. **첨부를 실제로 내려받는 경로는 여전히 미구현이며 별도 작업이다.** `bidops.collected.v2`는 유지했다 — 기존 필드의 값이 채워지는 변화이고 병합기에 optional로 등록했다.
- (해결 전 기록) 지금 해결할 수 없는 이유: 정규화 계약을 바꾸면 `collected-notices.json` 소비자와 적재 경로의 계약이 함께 바뀐다. 첨부 URL을 실제로 내려받는 경로는 허용 형식·크기, 서버 생성 key, 악성코드 검사, quarantine, 객체 version 검증을 함께 갖춰야 하므로 정규화 필드 추가만으로 끝나지 않는다.
- 접근 방법: 수집 endpoint를 `getPublicPrcureThngInfoServcPPSSrch`로 바꾸고 `inqryDiv=1`(접수일시)로 구간 조회한다. **`swBizObjYn`을 서버 조건으로 얹지 않는다.** 이 문단의 이전 판은 `swBizObjYn=Y` 필터를 지시했으나 [ADR-0024](decisions/0024-prespec-collect-all-flag-sw.md)가 그 반대를 결정했다. 650건 중 `Y`는 55건(8.5%)뿐이고 필터를 켜면 91.5%가 사라진다. 업무구분(일반용역·기술용역)으로만 좁히고 `swBizObjYn`은 저장 후 표시·필터 값으로만 쓴다. 이미 아는 등록번호를 다시 읽을 때는 `inqryDiv=2`가 날짜 구간 없이 단건을 반환한다. 두 endpoint의 응답은 650건에서 필드·값이 완전히 동일하므로 정규화 계약은 그대로 쓸 수 있다. 그 위에서 `specDocFileUrl1`~`5`를 `attachments`로, `swBizObjYn`·`bsnsDivNm`·`bidNtceNoList`를 구조화 필드로 옮긴다. 응답에 없는 필드를 읽는 현재 `url` 경로는 제거한다. 다운로드는 기존 첨부 파이프라인의 검사·격리 경계를 그대로 통과시키고, 원문에 URL이 없는 건은 추정 없이 `unknown`으로 남긴다. 회귀 테스트는 실제 응답 형태의 fixture로 첨부 개수와 SW대상 값이 보존되는지 고정한다.

## host 측정이 정상 PDF를 손상 문서로 판정한다

- 재현 조건: poppler가 없는 host에서 `app.document_mcp.processor.DocumentProcessor.process()`에 정상 PDF를 넣는다. 실측은 [`20260831-prespec-rfp-structure.md`](../validation-runs/20260831-prespec-rfp-structure.md)에 있다.
- 증상: 실제 조달 PDF 16건 중 15건이 `malformed_pdf`가 된다. 같은 파일을 `bidops-mock-t7-web` 이미지 안에서 처리하면 16건 전부 통과한다.
- 영향: 결함이 아니라 측정 함정이다. host에서 문서 파이프라인을 재면 처리 실패율이 크게 부풀려지고, 그 수치로 "PDF는 못 쓴다" 같은 잘못된 결론을 내리게 된다. T-21 초기 측정이 실제로 이 오류를 냈다.
- 상태: **원인 확인.** 표준 PDF 파서가 실패하면 poppler fallback으로 넘어가는데(`processor.py:315`) `pdftotext`·`pdfinfo`가 없으면 fallback이 `malformed_pdf`를 던진다(`processor.py:447-449`). `poppler-utils`는 런타임 이미지에만 있다(`web/Dockerfile:48`).
- 접근 방법: 문서 파이프라인 측정은 런타임 이미지 안에서 한다. 코드 수정은 필요 없다 — 운영 환경에는 poppler가 있다. 다만 fallback이 없을 때의 오류 코드가 `malformed_pdf`(문서 탓)인 것은 오해를 부른다. `converter_unavailable`처럼 환경 탓임이 드러나는 코드로 바꾸면 같은 혼동을 막을 수 있다. 이는 안전 판정을 완화하지 않는 변경이지만 오류 코드 계약을 건드리므로 별도로 다룬다.

## legacy 첨부 취득이 객체 식별자를 provenance 자리에 넣어 운영 백엔드에서 원문을 잃는다

- 재현 조건: `MinioObjectStore`처럼 `FilesystemObjectStore`가 아닌 object store에서 `assets.acquire_legacy_attachment()`를 호출하고 반환된 asset으로 `read_quarantine()`을 호출한다. `web/backend/tests/deep_review/test_legacy_attachment_provenance.py`가 가짜 store로 이 조건을 재현한다.
- 증상: `acquire_legacy_attachment()`가 12필드 `QuarantinedAsset`에 인자를 **9개만 위치로** 넘겼다. `object_key`가 `source_system` 자리에, object version id가 `source_attachment_key` 자리에, etag가 `source_url` 자리에 들어가고 `object_key`·`object_version_id`·`object_etag`는 `None`으로 남았다. `acquire_legacy_attachment()`는 store가 filesystem이 아니면 put 직후 로컬 quarantine 파일을 지우는데, `read_quarantine()`은 `object_key`가 없으면 그 지워진 로컬 경로를 읽으려 한다.
- 영향: 운영 기본 백엔드가 MinIO이므로(`docker-compose.yml`) legacy 첨부 ingest가 운영에서 항상 실패한다. 테스트는 filesystem store를 쓰기 때문에 로컬 파일이 남아 전부 통과했다. `test_minio_e2e`는 upload와 provider 경로만 덮고 legacy 경로를 덮지 않아 이 결함이 드러나지 않았다. 감사·응답으로 object key가 새지는 않는다 — 호출부가 `asset.source_*`를 쓰지 않고 자신의 snapshot 값을 쓴다.
- 상태: **해결** (2026-08-31). 세 생성 지점을 모두 키워드 인자로 바꾸고 `QuarantinedAsset`을 `@dataclass(frozen=True, kw_only=True)`로 만들어 위치 인자 구성을 아예 막았다. 생성 지점이 `assets.py` 안 세 곳뿐이라 외부 호출부에 영향이 없다. 회귀 테스트 4건을 추가했고 결함을 일부러 되살려 두 건이 실패하는 것을 확인했다.
- 남은 위험: 이 결함은 "운영 백엔드에서만 실패하고 테스트 백엔드에서는 통과한다"는 부류다. `test_minio_e2e`는 `BIDOPS_MINIO_E2E=1`이 없으면 skip되므로 같은 부류가 또 잠복할 수 있다. 새 테스트는 MinIO 없이도 도는 가짜 store로 이 부류를 잡는다.

## ADR-0027의 21일 재조회 근거가 종단 관측에서 재현되지 않는다

- 상태: **해결** (2026-09-18, [ADR-0061](decisions/0061-daily-collection-window.md))
- 재현 조건: `experiments/lifecycle-linkage-survey/scripts/survey.py`로 게시일 2026-08-24~2026-08-26 구간을 재조회하고 `--baseline-raw`로 이전 관측과 대조한다. 실행 기록은 [`20260831-order-plan-longitudinal.md`](../validation-runs/20260831-order-plan-longitudinal.md)에 있다.
- 증상: 같은 997건이 5일 동안 `bidNtceNoList` 채움률 45.6% → 46.6%로 **1 포인트**만 올랐다. 같은 나이(6일)의 횡단면 점은 67.8%다. 횡단면 곡선은 3일 45.8% → 6일 67.8% → 9일 77.1%로 가파르게 오르지만 실제로 추적 가능한 코호트는 그 속도로 채워지지 않는다.
- 영향: [ADR-0027](decisions/0027-order-plan-requery-window.md)이 재조회 범위를 최근 21일로 정한 근거는 횡단면 곡선의 "15~17일 평탄화"다. 실제 코호트가 훨씬 느리게 채워진다면 평탄화 시점이 21일보다 뒤일 수 있고 그러면 창이 짧아 공고 전환을 놓친다. [fill-curve](../validation-runs/20260829-order-plan-fill-curve.md)가 "횡단면과 종단이 어긋나면 종단이 정본"이라고 미리 정해 두었으므로 이 관측이 우선한다.
- 지금 해결할 수 없는 이유: 종단 관측점이 세 개이고 기간이 5일뿐이다. 21일이 틀렸다고 단정하기에 부족하다. 나이 15일과 21일 근처(2026-09-08, 2026-09-14 무렵) 관측이 나와야 판단할 수 있고, 재조회 범위 변경은 수집 비용과 API 한도에 직접 영향을 주므로 사람 결정이 필요하다.
- 접근 방법: 같은 구간의 재조회를 계속 쌓아 나이 21일 이후까지 본다. 횡단면 구간들은 폭이 3일로 같은데 건수가 28~997로 흔들려(08-15 광복절 구간이 28건) 비교 가능한 코호트가 아니다. 횡단면 기울기가 나이 효과인지 코호트 구성 차이인지 구분하려면 요일 구성이 같은 구간끼리 비교하거나, 08-21~08-23 구간도 종단으로 추적해 두 방법을 같은 코호트에서 직접 대조한다.
- 해결: ADR-0061이 ADR-0027을 폐기하고 발주계획을 전일 하루 창으로 수집하고 재조회하지 않기로 정했다. 21일 창의 길이를 맞추는 문제가 아니라 재조회 자체를 그만두므로 이 관측이 요구한 추가 종단 관측은 더 필요 없다. 발주계획→입찰공고 연결은 입찰공고 측 `orderPlanUntyNo`(ADR-0027 결과 절의 76.7%)가 유일 경로다. 겹치지 않는 세 회차(625·1,040·482건) 사이에 같은 통합번호가 다시 나온 경우는 0건이었다(2026-09-18 실측). 대가로 추적 중 발주계획의 `bidNtceNoList`·예산·발주 시기 변경을 관측하지 못하며, 이는 ADR-0061과 [`0918_daily-operation/plan.md` §4](../0918_daily-operation/plan.md)에 후속 과제로 남겼다.

## Alembic revision 식별자가 version table 컬럼보다 길어 PostgreSQL 배포가 불가능했다

- 재현 조건: 빈 PostgreSQL 17에서 `alembic upgrade head`를 실행한다. `docs/validation-runs/20260831-postgresql-migration-verification.md`에 실행 기록이 있다.
- 증상: `0003`까지 적용한 뒤 `psycopg.errors.StringDataRightTruncation: value too long for type character varying(32)`로 중단한다. Alembic 1.19.1은 version table을 만들 때 `Column("version_num", String(32))`를 하드코딩하는데(`alembic/ddl/impl.py:169`) `0004_cumulative_external_identity`(33자)와 `0006_bid_first_opportunity_registration`(39자)이 그보다 길다. PostgreSQL DDL은 트랜잭션이라 실행 전체가 롤백되어 `alembic_version` table조차 남지 않는다.
- 영향: `0004` 이후 어떤 배포도 불가능했다. PostgreSQL만 선언 길이를 강제하고 SQLite는 무시하므로 전체 테스트 스위트는 통과하고 있었다. T-7·T-8·T-12·T-16a가 추가한 스키마가 정본 저장소에 한 번도 적용된 적이 없다.
- 상태: **해결** (2026-08-31, T-9). `alembic/env.py`가 migration 실행 전에 version table을 `VARCHAR(64)`로 직접 만들고, 기본 폭으로 이미 만들어진 table은 `ALTER TABLE IF EXISTS`로 넓힌다. Alembic은 `Table.create(checkfirst=True)`로 생성하므로 이미 있는 table을 건드리지 않는다. 두 문장 모두 멱등이다. 폭은 `app.db.ALEMBIC_VERSION_NUM_WIDTH` 한 곳에 있고 `test_every_revision_identifier_fits_the_version_column`이 모든 revision 식별자를 그 안에 가둔다.
- (해결 전 기록) 대안이던 revision 식별자 단축은 `down_revision` 사슬, 파일명, `contracts.md`·`findings.md`·`lifecycle-workstream.md`의 문서화된 식별자를 모두 바꿔야 해서 선택하지 않았다.

## PostgreSQL 전용 테스트가 스키마 변경 뒤에도 갱신되지 않고 skip됐다

- 재현 조건: `BIDOPS_TEST_POSTGRES_URL`을 disposable PostgreSQL 17에 맞추고 `pytest tests/test_models_runtime.py`를 실행한다.
- 증상: 9건이 `column "run_id" of relation "notice" does not exist`로 실패한다. `seed_base()`가 `insert into notice(run_id, notice_key)`를 실행하는데 `run_id`는 `0004_cumulative_external_identity`가 ADR-0026에 따라 `notice`에서 없애고 `notice_observation`으로 옮긴 컬럼이다.
- 영향: T-7이 공고 정체성 모델을 바꿀 때 이 테스트가 함께 갱신되지 않았다. `BIDOPS_TEST_POSTGRES_URL`이 없으면 `requires_postgres`가 조용히 skip하므로 스위트는 계속 초록이었다. **정본 저장소의 불변식을 검증하라고 만든 테스트가 검증하지 않는 상태로 남아 있었다.**
- 상태: **해결** (2026-08-31, T-9). `seed_base()`가 `notice`를 누적 행으로 넣고 `notice_observation(notice_id, run_id, ...)`을 따로 넣는다. 13건 전부 통과한다.
- 남은 위험: skip이 기본값이라는 구조는 그대로다. `web/run-web-tests.sh`를 거치면 임시 PostgreSQL 17이 항상 서므로 이 경로에서는 잠복하지 않는다. 그러나 `pytest tests/test_foo.py`처럼 개별 파일을 직접 지정하면 여전히 조용히 skip하고 exit 0이다(`addopts = "-ra"`가 사유는 출력한다). 이 경로까지 막을지, CI로 대신할지는 D-11의 남은 결정이다.

## 애플리케이션 스택의 publish port가 host에서 열리지 않는다

- 재현 조건: Docker Engine 29.7.2에서 `docker compose -f docker-compose.yml up -d`로 기동한 뒤 `curl http://127.0.0.1:18787/api/health`, `ss -ltn`으로 15432·18787·19000·19001을 확인한다.
- 증상: 컨테이너는 정상이고 `web` 컨테이너 안에서 `/api/health`가 `{"status":"ok"}`를 반환하지만 host에서는 어떤 publish port도 바인딩되지 않는다. `HostConfig.PortBindings`에는 매핑이 남아 있으나 `NetworkSettings.Ports`가 `null`이다. `--internal` bridge 하나에만 붙은 컨테이너에 `-p`를 준 최소 재현에서도 host 연결이 실패하고, 일반 bridge에서는 같은 구성이 성공한다. `docker-compose.yml`의 `database`·`storage`·`scanning`·`analysis`는 모두 `internal: true`이므로 web·postgres·minio의 publish 선언이 전부 무효다.
- 영향: 문서화된 최초 기동 절차의 host `curl` health 확인과 관리 화면 접근이 현재 Docker 버전에서 동작하지 않는다. 컨테이너 내부 실행으로만 상태를 확인할 수 있어 통합 검증 절차와 운영 접근 경로가 성립하지 않는다.
- 상태: **해결** (2026-09-12, publish 소유권을 edge overlay로 옮김). `docker-compose.edge.yml`이 non-internal bridge와 `web`의 `ports:`를 **함께** 소유한다. 기반 파일에는 `ports:` 선언이 하나도 남지 않았으므로 "선언은 있는데 열리지는 않는" 상태가 구조적으로 불가능하다. 기반 파일의 모든 network가 `internal: true`라는 계약은 그대로다.
- 검증: `test_host_exposure_lives_only_in_the_edge_overlay`가 기반 파일에 `ports:`가 없고 edge overlay가 loopback 기본값으로 publish하는 것을 고정한다. 빈 compose로 internal network + `ports:`를 만들어 publish가 무시되는 것도 다시 실측했다(PORTS=`80/tcp`, 연결 실패).
- 남은 제약: edge overlay를 붙이면 `web`에 outbound NAT도 함께 생긴다. 이 상태를 내부망 격리와 같다고 기록하지 않는다(ADR-0050 완화 항목).
- 접근 방법: `com.docker.network.bridge.enable_ip_masquerade=false`를 지정한 전용 edge bridge를 만들어 `web`에만 연결하는 방식을 실측했다. host에서 publish port가 열리고 컨테이너의 외부 TCP 연결은 계속 차단된다(다만 embedded DNS를 통한 외부 이름 해석은 남는다). 함께 `127.0.0.1` 바인딩을 명시해 현재 `0.0.0.0` publish를 좁히고, postgres·minio는 publish 없이 `docker compose exec`로만 접근하도록 분리한다. 계약 테스트는 "egress network는 overlay에서만 추가한다"와 "edge network는 masquerade 비활성"을 확인하도록 바꾼다.

## 발주계획 Qwen 잘림 응답의 실패 token 계측이 보존되지 않는다

- 재현 조건: 실행 `20260824-20260826-interim-v4`의 동결 모집단 997건을 Qwen `qwen3.8:27b`, 고정 batch 25, `think="high"`, `num_predict=4096`으로 판정한다. 40개 중 10개 batch에서 Ollama가 `done_reason=length`를 반환한다.
- 증상: adapter가 `done_reason=length`를 확인하자마자 `truncated_output` 예외를 발생시켜 실패 응답의 `prompt_eval_count`, `eval_count`, thinking/content 길이와 duration을 결과에 옮기지 못한다. 해당 batch의 25건은 오류와 분배 latency만 갖고 input/output token은 `null`로 남는다.
- 영향: 생성 길이 제한이 직접 종료 원인이라는 것은 확인할 수 있지만, batch 크기, thinking 길이, 최종 JSON 길이가 각각 한도 소진에 얼마나 기여했는지 분해할 수 없다. 현재 실행은 747/997건만 성공했으므로 Qwen을 운영 후보로 승인하거나 안전한 batch·token 값을 결정할 근거가 부족하다.
- 지금 해결할 수 없는 이유: 현재 범위는 기존 불변 실행의 사후 결과 기록이다. 실패 batch telemetry를 추가하려면 method-result 계약의 batch 진단 표현, 비밀·본문 비보존 경계, renderer와 단위 테스트를 함께 변경하고 새 run ID로 live 재검증해야 한다.
- 접근 방법: 실패 응답 본문은 저장하지 않고 `done_reason`, prompt/eval token count, total/eval duration, thinking/content 문자 수만 안전한 batch 진단으로 보존한다. 동일 실패 batch에서 기준 설정을 재현한 뒤 batch 10, `num_predict=8192`, 모델이 지원하는 thinking 설정을 한 변수씩 분리해 비교한다. 상세 증거와 artifact hash는 [`20260828-order-plan-screening-interim-v4.md`](../validation-runs/20260828-order-plan-screening-interim-v4.md)에 기록했다.

## 개발용 Codex 심층 검토 경로가 외부 전송 허용 범위를 넘는다

- 재현 조건: (제거 전) `docker-compose.codex-reference.yml`로 `BIDOPS_ANALYSIS_PROVIDER=codex-exec`, reference mode, 승인 notice ID를 설정하고 심층 검토 stage를 실행한다.
- 증상: `CodexExecClient.invoke()`가 일반 vLLM과 같은 `build_prompt()`를 사용한다. stage 입력에는 구조화된 RFP 요구사항 excerpt가 들어가고 delivery stage에는 회사 profile facts·evidence가 들어가므로 hosted Codex에 전송될 수 있다.
- 영향: 공개 발주계획 메타데이터와 별도 승인된 최소 회사 역량 요약만 외부 모델에 보낸다는 확정 정책을 위반한다. 공고 allowlist와 기본 비활성은 실행 승인만 제한할 뿐 금지된 payload 종류를 제거하지 않는다.
- 상태: **해결** (2026-09-03, provider 제거). hosted 외부 deep-review provider와 그 Compose overlay·env 예시·설정·문서를 저장소에서 삭제했다. 남는 심층 검토 provider는 `vllm`과 `mock`뿐이며, 이 경로로 RFP·첨부·profile 전문·evidence가 외부로 나갈 수 있는 코드는 존재하지 않는다.
- 검증: `Settings.analysis_provider`의 선택지가 `{"vllm", "mock"}`뿐이고 `codex` 이름의 설정·속성이 남지 않았음을 `web/backend/tests/core/test_config_t9.py`가 고정한다. backend 전체 suite는 `2 failed, 1091 passed, 5 skipped`였고 실패 2건은 이 변경과 무관한 `tests/screening/test_screening_orchestrator.py`의 기존 결함이다(기준선 `1097 passed`에서 삭제한 테스트 7건을 빼고 새 테스트 1건을 더한 값).
- 후속: 외부 비교 실험이 다시 필요하면 발주계획 전용 projection·payload preview·사람 승인 경계를 새로 설계한다. 그 구현의 테스트는 RFP, 첨부, profile 전문·evidence, 내부 review 필드가 payload에 들어가면 호출 전에 실패하는지 확인해야 한다.

## 런타임 이미지에 회사 프로필 자료가 포함된다

- 재현 조건: 현재 `web/Dockerfile`로 runtime image를 build한 뒤 `/app/docs/reference`와 `/app/web/backend/app/screening` 내용을 검사한다.
- 증상: `COPY docs/reference /app/docs/reference`가 `company-profile.md`와 회사 실적 제목 TSV를 복사하고, 별도 TSV copy가 이를 반복한다. `COPY web/backend/ ./`는 `baseline_company_profile.md`도 복사한다. `.dockerignore`는 reference PDF만 제외한다. Dockerfile의 회사자료 제외 주석과 실제 image 내용이 다르다.
- 영향: image registry, build cache, image export에 회사 프로필·실적 근거가 포함될 수 있어 회사자료를 image에 넣지 않는 보안 경계를 위반한다.
- 상태: **해결** (2026-09-01, runtime image 경계 보완). `docs/reference`의 build-context 예외를 제거하고 backend baseline을 `.dockerignore`로 제외했다. `COPY web/backend/ ./`는 유지하되 세 회사자료는 image에 복사하지 않으며, current profile·회사 실적 제목 TSV·승인 baseline은 `web` 서비스에만 read-only bind mount로 실행 시 주입한다. 기존 baseline digest 검증은 그대로 사용한다.
- 검증: 기존 runtime contract test는 Dockerfile의 세 파일 copy 부재, `.dockerignore`의 세 파일 제외, `web`의 세 read-only mount를 함께 확인했고 `11 passed`였다. 2026-09-01 실제 image build/run에서 `/app/docs/reference/`에는 `.`·`..`만 있었고 profile·실적·baseline 이름을 찾는 `find`는 무출력이었다. `docker compose -f docker-compose.yml config`는 `COMPOSE_OK`, backend 전체 suite는 `1037 passed, 5 skipped, 6 warnings`로 실패 0건이었다.
- 접근 방법: 일반 `docs/reference`와 backend baseline의 bulk copy를 build context 단계에서 차단하고, `skills/`와 그 공개 workflow contract만 image에 둔다. 프로필·실적 reference·baseline은 승인된 read-only host checkout 경계로 실행 시 주입하고, baseline은 기존 digest 검증으로 무결성을 확인한다.

## 프로필 조회 API가 원문과 서버 경로를 노출한다

- 재현 조건: `GET /api/profile/snapshots`, `GET /api/profile/sections`, `GET /api/profile/unknowns`를 호출하거나 프로필 파일 읽기 오류를 유발한다.
- 증상: snapshots item의 working-tree `source_ref`는 내부 상대 파일 경로다. sections 응답은 filesystem `source`, `raw_blocks[].raw`, section `raw`, `source_line`을 포함한다. unknowns도 filesystem `source`를 반환하며 `parse_errors` 문자열에 원본 `OSError`의 절대 경로가 들어갈 수 있다. sections·unknowns는 현재 working tree parser 결과에 묶이고 승인된 불변 profile version·digest를 응답에 고정하지 않는다.
- 영향: 사내망 사용자 모두에게 UI에 필요한 범위를 넘는 회사 프로필 원문과 서버 배치 구조가 노출된다. 실행 중 working tree가 변하면 같은 조회 route가 다른 프로필을 반환할 수 있어 승인 snapshot 경계도 흐려진다.
- 상태: **해결** (2026-09-01, A-3 최소 projection 전환). 세 route는 승인된 snapshot version·digest와 구조화 projection만 반환하고, working-tree `source_ref`·filesystem source·source line·raw block/text·원문 예외를 wire에서 제외한다. Git blob은 40자 SHA만 계보 식별자로 유지하며 파싱·읽기 실패는 닫힌 `error_codes`로 표현한다.
- 검증: 실제 `docs/reference/company-profile.md`의 특징적 문자열과 임시 snapshot artifact 누락 경로를 포함한 `test_profile_projection.py`가 snapshots·sections·unknowns 응답에 원문·절대 경로·원문 parse error가 없음을 확인했다. 백엔드는 `1038 passed, 5 skipped, 6 warnings in 566.02s (0:09:26)`, 프론트엔드는 `598 passed, 10 skipped (5.5m)`으로 완료했고 `tsc`·production build도 통과했다.

## legacy 첨부 업로드가 악성코드 검사와 객체 격리를 우회한다

- 재현 조건: `POST /api/notices/{notice_pk}/attachments`로 허용 확장자·크기의 파일을 등록한 뒤 download endpoint를 호출한다.
- 증상: legacy attachment service는 확장자와 50MiB 한도만 확인하고 `/app/web/data/attachments`로 rename한 뒤 DB를 commit한다. MIME 판별, quarantine, ClamAV, MinIO object version·hash 없이 바로 다운로드할 수 있다. T7은 `/app/data`와 `/app/reports`만 volume으로 연결하므로 이 attachment 경로는 container 재생성 때 유실될 수도 있다. `AttachmentResponse.stored_path`는 DB 값을 그대로 내보내 notice directory와 로컬 저장 layout을 client 계약에 노출한다.
- 영향: 파일 내용이 확장자와 다르거나 악성인 첨부가 웹 process의 로컬 저장소와 사용자 download 경로로 들어가 Lean document upload의 안전 경계를 우회한다. DB row는 남고 파일만 사라지는 불일치도 생길 수 있고, path 노출은 서버 배치 구조를 외부 wire에 고정한다.
- 상태: **해결** (2026-09-01, A-2 legacy upload 안전 경계·응답 projection·보관 volume 보완). 기존 `Attachment` schema와 id 기반 legacy download 호환성은 유지한다.
- 검증: 감염 표식·ClamAV 사용 불가 파일은 4xx로 등록되지 않고 filesystem 산출물이 남지 않으며, safe PDF만 등록된다. 첨부 처리·notice detail 응답에는 `stored_path`가 없고 `docker compose -f docker-compose.yml config`가 통과한다.
- 접근 방법: 업로드 바이트를 quarantine object에 저장하고 MIME·구조·ClamAV 검사를 통과한 경우에만 source object로 승격한 뒤 legacy `Attachment`와 named-volume의 로컬 호환 사본을 만든다. `stored_path`는 내부 metadata로만 유지하고 response schema·serializer에서 제거했다. 기존 attachment object metadata schema 이전은 별도 범위다.

## MinIO versioning 초기화가 실패해도 stack이 계속 기동한다

- 재현 조건: MinIO에서 bucket versioning 명령이 권한·호환성 오류로 실패하는 환경에서 `scripts/minio-init.sh`를 실행한다.
- 증상: `mc version enable` 뒤 `|| true`가 모든 실패를 삼키고 실제 versioning 상태를 다시 확인하지 않는다. init service는 versioning이 꺼져 있어도 성공할 수 있다.
- 영향: DB가 object version ID를 불변 정본처럼 저장하는 전제가 깨지고 overwrite·backup·restore에서 같은 object key의 역사 bytes를 보장할 수 없다.
- 상태: **해결** (2026-09-01). `|| true`를 제거하고 bucket마다 `mc version info --json`으로 상태를 되읽어 `"versioning":{"status":"Enabled"`가 아니면 init service를 실패로 끝낸다. `mc version enable`은 이미 versioned인 bucket에서도 성공하므로 멱등성은 유지된다.
- 되읽기가 필요한 이유: `mc version info`는 **un-versioned bucket에서도 exit 0**을 반환한다(`RELEASE.2025-08-13T08-35-41Z`에서 실측). 종료 상태만으로는 versioning 여부를 구분할 수 없어 status 문자열이 유일한 증거다. mc image에는 `sed`·`awk`가 없어 셸 `case` 매칭으로 판별한다.
- 검증: disposable MinIO(`RELEASE.2025-09-07T16-13-09Z`)에 실제 스크립트를 실행했다. 정상 기동은 exit 0에 4개 bucket 모두 `versioning is enabled`, 재실행도 exit 0. `mc version enable`이 실패하는 상황을 넣으면 수정 전 스크립트는 **exit 0으로 성공하면서 4개 bucket 전부 `un-versioned`** 였고, 수정 후에는 `bucket versioning is not enabled: bidops-source`와 함께 exit 1로 끝난다.

## 객체 복구가 원본 version ID와 복구 대상 version ID를 혼동한다

- 재현 조건: `backup-objects.sh`로 version별 backup을 만든 뒤 빈 MinIO에 `restore.sh`를 실행하고 `verify-active-hashes.sh`로 검사한다.
- 증상: backup manifest는 source version ID를 기록하지만 local file을 target에 `mc cp`하면 새 target version ID가 생긴다. restore는 새 ID를 기록하지 않고 verifier는 source version ID로 target object를 조회한다. `ACTIVE_HASH_MANIFEST`를 DB active reference에서 생성·완전성 검사하는 경로도 없다.
- 영향: 정상 복구도 version lookup에서 실패하거나, 수동 manifest가 일부 active object를 빠뜨려도 DB 연결만 확인한 채 복구 검증이 끝날 수 있다. object-first 복구 완료를 주장할 수 없다.
- 상태: **해결** (2026-09-01, A-6 object-first restore MVP).
- 검증: `backup-objects.sh`가 source stored-byte hash를 확인하고, `restore.sh`가 매 object의 target version ID를 `object-version-mapping.tsv`에 기록한다. 복구 뒤 DB에서 `content_object_location`과 `content_object`를 query해 active manifest를 생성하고, verifier가 일반 namespace의 target ID·stored-byte hash와 model-response의 target ID·존재를 확인하며 DB active 집합 및 복구된 모든 version 집합의 누락·추가·중복을 실패시킨다. disposable MinIO 원본·case별 빈 복구 대상과 PostgreSQL 17에서 정상 복구, 손상 backup, 누락 active object 세 경우를 실행해 확인했다.
- 접근 방법: restore 때 source version → target version mapping과 stored-byte hash를 기록하고 DB가 가리키는 모든 active object를 query해 manifest와 일대일 대조한다. verifier는 일반 namespace에 target version ID와 stored-byte hash를, model-response에는 target version ID와 존재를 검사하며 누락·추가·중복을 모두 실패시킨다.

## 암호화된 model-response active object는 stored-byte hash로 검증할 수 없다

- 재현 조건: 암호화된 model-response를 생성해 `ContentObjectLocation(namespace_key='model-response', status='verified')`로 active manifest에 포함한 뒤 복구 검증을 실행한다. `ContentObject.sha256`는 plaintext aggregate의 SHA-256이고 MinIO object bytes는 `BIDOPS-AESGCM-V1\0` envelope와 nonce·ciphertext다.
- 영향: manifest의 model-response hash를 MinIO stored bytes의 SHA-256과 비교하면 정상 복구도 항상 불일치해 검증이 실패한다. 암호화된 payload의 stored-byte 무결성은 현재 DB hash로 입증할 수 없다.
- 남은 제약: verifier는 model-response의 stored-byte hash 비교를 하지 않고 target version에서 object 존재와 version만 확인한다. 다만 DB active 집합 일치, 누락·추가·중복 실패, source→target version mapping 및 target version 존재 검사는 다른 namespace와 동일하게 유지한다.
- 지금 이렇게 두는 이유: 이번 A-6의 목적은 정상 복구를 검증 가능하게 만드는 것이며, 기존 `ContentObject.sha256`의 plaintext 의미와 암호화 저장 경계를 보존해야 한다. 스키마 변경 없이 이 namespace만 예외 처리하는 것이 현재 복구 계약과 fail-closed 집합 검사를 모두 유지하는 방법이다.
- 후속 방향: stored-byte hash를 별도 필드로 기록하는 스키마 보완을 설계·적용해 암호화 envelope도 내용 무결성까지 검증한다. 이는 이번 범위가 아니다.

## 분석 worker DB 역할이 모든 업무 table을 수정할 수 있다

- 재현 조건: migration 뒤 PostgreSQL에서 `worker` role의 table privilege를 조회한다.
- 증상: `scripts/migrate.sh`가 현재와 미래의 `bidops` 모든 table에 `SELECT, INSERT, UPDATE, DELETE`를 부여한다.
- 영향: 분석 worker 자격증명이 탈취되거나 코드가 오동작하면 사람 리뷰·최종 의견·정책·감사 등 worker 책임 밖의 row도 수정할 수 있어 최소 권한과 사람 결정 경계가 DB에서 강제되지 않는다.
- 상태: **해결** (2026-08-31, MVP DB 보완). `scripts/runtime-privileges.sql`이 migration 뒤 기존 blanket/default grant를 회수하고 app·worker의 table·operation·column allowlist만 다시 부여한다. 미래 table은 두 runtime role에 DML을 자동 상속하지 않고 `ro_backup` 만 `SELECT`를 상속한다.
- 검증: disposable PostgreSQL 17에서 실제 `has_table_privilege`·`has_column_privilege`를 검사한다. worker는 사람 review·judgment/review revision·quality policy·final opinion을 수정할 수 없고, overview도 실제 deterministic preparation에 필요한 review/snapshot 생성과 review 지정 상태 컬럼 갱신만 허용한다.

## PostgreSQL과 MinIO 관리 port가 모든 host interface에 publish된다

- 재현 조건: 기본 `docker-compose.yml`을 기동하고 host의 listen address를 확인한다.
- 증상: PostgreSQL, MinIO API, MinIO console port mapping에 host IP가 없어 Docker가 기본적으로 모든 host interface에 bind할 수 있다.
- 영향: Compose internal network와 무관하게 LAN에서 DB·객체 저장소 port에 직접 접근할 수 있어 애플리케이션 API만 사용하는 접근 경계를 우회한다. 실제 노출 범위가 host firewall 상태에 의존한다.
- 상태: **해결** (2026-09-12, publish 선언 제거). 2026-09-01에는 세 mapping에 `${BIDOPS_ADMIN_BIND_HOST:-127.0.0.1}:` prefix를 붙였지만, 그 선언은 internal network 때문에 애초에 host에 bind된 적이 없다. 이제 PostgreSQL·MinIO의 `ports:`를 제거했고 관리 접근은 `docker compose exec`뿐이다. `BIDOPS_ADMIN_BIND_HOST`·`BIDOPS_POSTGRES_PORT`·`BIDOPS_MINIO_PORT`·`BIDOPS_MINIO_CONSOLE_PORT`도 `.env.example`에서 지웠다.
- 개발 검증 경로: host의 `psql`·`mc` 대신 `docker compose exec postgres psql -U owner bidops`, `docker compose exec minio mc ...`를 쓴다. **애플리케이션 port(`BIDOPS_WEB_PORT`)는 사내망 접근이 설계된 경계이므로 좁히지 않았고, edge overlay가 loopback 기본값으로 publish한다.**

## legacy mutation 일부가 담당자 이름과 감사 기록 없이 실행된다

- 재현 조건: legacy review upsert, attachment upload·delete, agency portal create·patch, run ingest·subprocess 실행 endpoint를 호출한다.
- 증상: 해당 경로는 `X-BidOps-Actor-Name`을 요구하지 않거나 reviewer가 optional이고, 작업별 `AuditEvent`를 같은 transaction에 남기지 않는다. Lean 문서·심층 검토와 screening control 계열만 별도 actor·audit 경계를 가진다.
- 영향: 사내 사용자가 변경·승인할 때 이름을 남긴다는 채택 결정이 API 전체에서 성립하지 않으며 누가 첨부를 지우거나 포털·리뷰·회차를 바꿨는지 일관되게 추적할 수 없다.
- 상태: **부분 해결** (2026-09-01, A-4). 첨부 upload/delete, agency portal create/patch, screening policy create/candidate/activate에 기존 actor parser와 append-only `AuditEvent`를 적용했다. legacy review와 일부 run/subprocess mutation은 여전히 별도 작업이다.
- 검증: 세 router의 7개 mutation이 actor 없는 요청을 400으로 거부하고, actor가 있으면 같은 transaction에 `AuditEvent`를 남기는 회귀가 통과했다. frontend API 호출부와 포털·정책 화면도 actor header를 전송한다.
- 접근 방법: 새 감사 테이블이나 helper layer를 만들지 않고 기존 `validate_actor`와 `AuditEvent`를 각 mutation transaction에 연결했다. 과거 actor 없는 row는 추정하지 않는다.

## 현재 보고서 renderer가 screening v3를 처리하지 못한다

- 재현 조건: `bidops.screening.v3`의 `screening-results.json`을 현재 report stage 또는 `render_report.py`에 전달한다.
- 증상: current screening runtime은 v3를 만들고 적재기는 v3를 받지만 report renderer는 `bidops.screening.v2`만 허용해 즉시 종료한다.
- 영향: 새 판정 실행의 결과를 기존 HTML·feedback 흐름으로 연결할 수 없고 자동 pipeline에서 판정과 보고 사이가 끊긴다.
- 지금 해결할 수 없는 이유: v3의 partial/failure·execution binding을 HTML과 feedback에 어떻게 표시할지 소비자 계약과 회귀 기준이 필요하다.
- 접근 방법: v2 의미를 바꾸지 않은 채 renderer에 명시적 v3 adapter를 추가하고 부분 성공·failure artifact·승계 provenance를 표시한다. v2와 v3 fixture의 결정성을 각각 검증한다.

## 승인된 프로필 기준선 commit이 현재 저장소 history에 없다 (2026-08-31 결정으로 수용)

- 재현 조건: `git cat-file -e ee621835db934ddac944f7a07a986ed0b73ecc7a^{commit}`을
  현재 checkout에서 실행한다.
- 증상: 승인 commit과 그 path의 blob이 둘 다 Git object DB에 없다.
- 실제 영향: **없다.** byte-identical 파일이
  `web/backend/app/screening/baseline_company_profile.md`로 벤더링돼 있고
  `BASELINE_PROFILE_SHA256= a231ab54…`로 검증된다. `read_git_source()`는 git 조회가
  불가할 때만 이 파일로 fallback하고, git이 있으면 동등성을 교차 확인해 drift를 막는다.
  `test_profile_snapshot*` 14건은 현재 모두 통과한다.
- 범위 정정: 이 commit은 `model_comparison` 품질 gate 전용 **역사 anchor**다.
  `operational_approval`은 `profile_source = "current"`를 요구하고 런타임의
  `snapshot_current()`는 현재 working tree 프로필(sha256 `96731dd5f77d…`)을 읽는다.
  운영 판정은 이미 현재 프로필을 쓰고 있으므로 정본이 갈라진 상태가 아니다.
- 결정: 2026-08-31에 이 상태를 그대로 두기로 했다. 현재 프로필을 역사 anchor에 덮어쓰면
  `model_comparison`이 현재-대-현재 비교가 되어 "역사 baseline과 설명 가능한 비교"라는
  목적 자체가 사라지므로 하지 않는다.
- 남는 제약: `git:ee621…`을 요구하는 model comparison gate는 git 경로로 재현할 수 없고
  벤더링 파일에만 의존한다. 그 파일이 저장소에서 사라지면 역사 비교가 불가능해진다.

## 문서 준비와 실패 심층 검토 재시작을 화면에서 완료할 수 없다

- 재현 조건: ready document bundle이 없는 공고를 브라우저에서 열거나 deep-review attempt가 실패한 상태를 연다.
- 증상: 조회와 ready bundle 이후 심층 검토 화면은 있지만 bundle 생성·문서 upload·metadata 수정·확정, 실패 attempt의 새 attempt 생성 action이 없다.
- 영향: 담당자는 curl 또는 CLI를 사용해야 하므로 목표 업무 흐름이 화면에서 끊기고, actor·idempotency·상태 fence를 잘못 다룰 가능성이 커진다.
- 지금 해결할 수 없는 이유: backend 계약은 준비됐지만 frontend Phase 3 구현과 browser 회귀 검증이 별도 코드 작업으로 남아 있다.
- 접근 방법: typed Lean API client, document preparation panel, terminal failure 전용 retry, polling, 403/503 상태 표현을 구현하고 fake API browser 흐름과 좁은 viewport를 검증한다.
- 종결(2026-09-16): 코드에 구현됨(DocumentPreparationPanel 연결). 첨부 취득 실패 재시작만 미구현으로 남는다.

## 개발계정 일일 1,000회 한도의 실제 여유가 측정되지 않았다

- 재현 조건: 발주계획·사전규격을 3일 window로 page 끝까지 수집하고 endpoint·page·retry별 실제 요청 수를 집계한다.
- 증상: 알려진 것은 약 1,200개 발주계획과 약 40개 SW 사전규격이라는 레코드 규모뿐이며, 페이지 크기·endpoint 분할·정정 조회·재시도를 포함한 호출 수 기록은 없다.
- 영향: 일 1,000회가 초기 실험에 충분하다는 추정은 가능하지만 scheduler를 안전하게 활성화하거나 운영 증액량을 산정할 근거는 부족하다.
- 지금 해결할 수 없는 이유: 신규 수집기와 quota telemetry가 아직 없고 실제 개발계정 응답의 pagination을 관측하지 않았다.
- 접근 방법: 동결 3일 실험에서 실제 HTTP 요청을 endpoint·page·retry별로 기록하고 cache hit를 분리한다. 700회 경고, 900회 신규 요청 중지로 시작한 뒤 관측치를 이용해 운영계정 활용사례와 증액량을 정한다.

## 사설 vLLM model artifact가 불변 digest로 고정되지 않았다

- 재현 조건: analysis worker preflight와 `/v1/models` 응답으로 실행 model identity를 확인한다.
- 증상: served model ID `qwen3.8-27B`는 확인할 수 있지만 weight digest가 응답에 없고 server image도 mutable tag를 사용할 수 있다.
- 영향: 같은 model name이 다른 bytes를 가리켜도 실행 당시 승인한 artifact와의 차이를 자동 검출하지 못할 수 있다.
- 지금 해결할 수 없는 이유: image digest와 model revision 또는 로컬 artifact digest는 모델 서버 운영자가 제공해야 한다.
- 접근 방법: server image digest, immutable model revision·artifact digest를 deployment manifest에 고정하고 startup preflight가 이를 quality manifest와 대조하도록 provider 계약을 확장한다.

## 실제 심층 검토 품질 corpus와 사람 gold가 부족하다

- 재현 조건: 대표 HWP/PDF에서 요구사항 recall, 사람 일치율, unsupported claim 비율을 계산하려 한다.
- 증상: 55개 요구사항 기대 ID 사례는 있으나 원문·claim별 gold mapping과 다양한 기관·문서 형식의 사람 adjudication이 충분하지 않다.
- 영향: Mock E2E와 단일 후보 호출은 실제 사업 판단 품질이나 0.80/0.70/0.10 activation 기준을 증명하지 못한다.
- 지금 해결할 수 없는 이유: 완료 사업의 사용 승인된 첨부와 담당자 기준 답안이 더 필요하다.
- 접근 방법: 공공 SI와 AI·데이터 또는 블록체인 축에서 서로 다른 HWP/PDF 사례를 선정하고 source hash, requirement·자격·배점·위험 gold, claim별 사람 판정을 만든다. 실제 immutable model로 gate를 측정한다.

## 실제 backup·권한·복구 훈련이 없다

- 재현 조건: 운영과 같은 secret·MinIO policy·firewall을 가진 격리 환경에서 PostgreSQL dump와 versioned object backup을 빈 대상에 복구한다.
- 증상: script와 Mock E2E는 있지만 실제 snapshot, object manifest, allow/deny matrix, object → DB → active hash 복구 기록이 없다.
- 영향: RPO·RTO, 최소 권한, 암호화 key 복구, container 재생성 뒤 참조 무결성을 운영 수준으로 주장할 수 없다.
- 지금 해결할 수 없는 이유: 실제 secret manager 주입, 백업 보관 위치, 운영 snapshot, 빈 pre-production target은 저장소 밖의 운영 준비가 필요하다.
- 접근 방법: 운영자가 승인한 복사본으로 역할별 DB 권한, MinIO namespace allow/deny, egress, UID/GID를 검사하고 객체를 먼저 복구한 뒤 DB와 active hash를 대조하는 훈련을 기록한다.

## 담당자 이름은 신원을 증명하지 않는다

- 재현 조건: 사내망 사용자가 mutation에서 다른 담당자의 이름을 입력한다.
- 증상: 시스템은 입력 이름을 감사에 남기지만 실제 사용자의 내부 계정과 일치하는지 확인하지 못한다.
- 영향: 리뷰, 정책 활성화, 외부 모델 전송 승인 기록의 작성자 신뢰도가 사내망 접근 통제 수준에 머문다.
- 지금 해결할 수 없는 이유: 현재는 사내망과 claimed name만 사용하기로 했고 SSO·계정·역할 정보가 연결되지 않았다.
- 접근 방법: 향후 SSO subject를 내부 계정에 매핑하고 세션 만료, 역할, 권한 회수, 기존 claimed-name 감사와의 연결 정책을 도입한다.

## 심층 검토 보고서를 사업기회·공고로 되찾을 목록 계약이 없다

- 재현 조건: 공고 판정 이력에서 심층 검토를 생성해 `/deep-reviews/{id}`로 이동한 뒤 화면을 벗어난다. 사업기회 화면이나 공고 화면에서 그 보고서를 다시 연다.
- 증상: `web/backend/app/deep_review/routers/deep_reviews.py`가 제공하는 읽기 계약은 `GET /deep-reviews/{deep_review_id}` 단건뿐이다. 사업기회·공고로 보고서를 나열하는 endpoint가 없고, 사업기회 목록·상세 응답과 공고 응답에도 `deep_review_id`가 없다. 보고서 식별자를 따로 적어 두지 않으면 만든 보고서로 돌아갈 길이 없다.
- 영향: 구 `docs/design/PRD.md`(git 이력, 삭제됨) §2.2가 요구한 "사업기회 화면의 명시적 진입점"을 데이터로 채울 수 없다. 2026-09-02 화면 개선 2단계는 사업기회 상세에 식별자로 여는 진입점을 두고 목록을 제공할 수 없다는 사실을 화면에 명시하는 선에서 멈췄다. 목록이 비어 보이는 것을 보고서가 없다는 뜻으로 오해할 위험은 문구로만 막고 있다.
- 지금 해결할 수 없는 이유: 해결에는 REST 계약 추가(사업기회 또는 공고별 심층 검토 목록)나 기존 응답에 식별자 노출이 필요하다. 화면 개선 2단계의 범위는 프론트엔드이며 `docs/contracts.md`의 소비자 계약과 백엔드를 바꾸지 않기로 했다.
- 접근 방법: `GET /opportunities/{id}/deep-reviews` 또는 `GET /notices/{notice_id}/deep-reviews`를 추가해 보고서 식별자·생성 시각·현재 상태를 돌려주고, `docs/contracts.md`와 `docs/deep-review-erd.md`에 소비자 계약으로 등록한다. 그 뒤 사업기회 화면의 진입점을 식별자 입력이 아니라 목록으로 바꾼다.
- 종결(2026-09-16): 코드에 구현됨(GET /api/opportunities/{id}/deep-reviews).

## Go/No-Go 결정 대기 사업기회를 N+1 없이 집계할 endpoint가 없다

- 재현 조건: 대시보드 "지금 처리할 일"이나 `GoNoGoPage.tsx`에서 "최종 Go/No-Go 결정 대기" 건수를 구하려 한다.
- 증상: `web/backend/app/deep_review/routers/bid_delta.py`는 사업기회 하나의 workspace만 반환하고(`GET /opportunities/{id}/bid-delta` 계열), "계속 추적 중이며 아직 최종 결정이 없는 사업기회 수" 같은 집계 endpoint가 없다. `GoNoGoPage.tsx`는 이를 우회하려고 추적 중 사업기회 목록을 받은 뒤 사업기회마다 bid-delta workspace를 조회하는 N+1을 이미 쓰고 있다(2026-09-02 화면 개선 2단계, 코드 머리 주석에 기록).
- 영향: 대시보드처럼 N+1을 반복할 수 없는 화면(`web/backend/AGENTS.md`·`CLAUDE.md`의 N+1 금지 게이트)은 이 건수를 전혀 계산할 수 없다. 2026-09-03 3단계는 대시보드 항목의 건수를 `null`(확인 불가)로 표시하고 이동 경로만 제공하는 선에서 멈췄다 — 페이지 자체(`GoNoGoPage.tsx`)의 기존 N+1도 아직 걷어내지 못했다.
- 지금 해결할 수 없는 이유: 해결에는 새 집계 REST 계약(예: 사업기회당 최신 `latest_final_decision` 유무를 서버가 먼저 걸러 세는 endpoint)이 필요하며, 이는 백엔드 스키마·서비스 변경이라 이번 프론트엔드 범위를 벗어난다.
- 접근 방법: `GET /opportunities?tracking_status=계속 추적&decision_status=pending` 같은 서버 필터 또는 `GET /bid-delta/pending-count` 집계 endpoint를 추가해 `docs/contracts.md`와 `docs/bid-delta-contract-spec.md`에 등록한다. 그 뒤 `GoNoGoPage.tsx`의 기존 N+1과 대시보드의 `null` 표시를 실제 건수로 교체한다.

## 발주계획 목록 API에 "사람 피드백 미기록" 필터가 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "C-2 검토 대기" 건수를 사람이 아직 판정하지 않은 발주계획 수로 정의하려 한다.
- 증상: `GET /api/order-plans`(`web/backend/app/screening/routers/order_plans.py:78`)는 `qwen_relevance`·`human_relevance`를 필터로 받지만, `human_relevance`는 특정 relevance 값(`relevant`|`not_relevant`|`uncertain`)만 받고 "사람 피드백 행 자체가 없음"을 나타내는 값(`missing`/`null`)을 받지 않는다.
- 영향: 2026-09-03 3단계는 이 항목을 "Qwen 신호가 relevant 또는 uncertain인 발주계획" 건수(사람 피드백 여부와 무관)로 근사했다. 실제 "검토 대기"(아직 아무도 보지 않은 건)보다 넓은 집합이라 과대 계상될 수 있고, 화면 설명 문구로만 그 차이를 알린다.
- 지금 해결할 수 없는 이유: `human_relevance=missing` 같은 값을 추가하려면 서비스 쿼리(`OrderPlanScreeningService.list_order_plans`)와 라우터 계약을 함께 바꿔야 하며, 이번 프론트엔드 범위의 대시보드 작업만으로는 안전하게 변경할 수 없다.
- 접근 방법: `human_relevance`에 `missing` 같은 sentinel 값을 추가해 "사람 피드백 행 없음"을 서버에서 걸러주고, `docs/contracts.md`의 `GET /api/order-plans` 항목에 등록한다. 그 뒤 대시보드와 `OrderPlansPage.tsx`의 "검토 대상" 프리셋이 이 필터를 실제 "미판정" 의미로 좁힐 수 있다.

## 사전규격 목록 API에 마감 구간 필터도 임박 집계도 없다

- 재현 조건: 대시보드 "지금 처리할 일"에서 "사전규격 의견등록 마감 임박" 건수를 구하려 한다.
- 증상: `GET /api/pre-specs`(`web/backend/app/lifecycle/routers/pre_specs.py:95`)는 `sw_only`·`business_division`·`origin`·`q`·`sort`·`limit`·`offset`만 받는다. 마감 구간 필터가 없고 집계 응답도 없다. `sort=deadline`은 `deadline_at ASC NULLS LAST`(`pre_specs.py:180`)라 **첫 페이지가 이미 지난 마감으로 채워진다.** 따라서 한 페이지를 받아 클라이언트에서 세면 두 가지가 동시에 틀린다. (1) 지난 마감을 임박으로 센다 — 회차 산출물 `stats.imminent_deadlines`와 달리 서버가 좁혀 준 창이 없는데 `criticalDeadlineCount`에는 하한이 없다. (2) 임박 구간이 페이지 창 밖이라 애초에 도달하지 못한다.
- 영향: 2026-09-03 3단계는 이 항목의 건수를 `null`(확인 불가)로 두고 이동 경로만 제공하는 선에서 멈췄다. 구현 위임 초안은 `limit=50` 한 페이지를 세어 숫자를 표시했는데, 누적 데이터에서는 거의 항상 "만료된 사전규격 수"를 "마감 3일 이내"로 보여주는 값이라 검수에서 되돌렸다.
- 지금 해결할 수 없는 이유: 해결에는 목록 계약에 마감 구간 필터(`deadline_from`·`deadline_to`)나 임박 집계를 추가해야 하며, 이는 백엔드 라우터·스키마 변경이라 이번 대시보드 작업 범위를 벗어난다.
- 접근 방법: `GET /api/pre-specs`에 `deadline_within_days` 또는 `deadline_from`·`deadline_to`를 추가하고 `docs/contracts.md`의 `PreSpecList` 항목에 등록한다. 그 뒤 대시보드의 `null` 표시를 실제 건수로 바꾸고, `criticalDeadlineCount`의 하한 없음이 회차 산출물 전용 전제임을 호출부에서 다시 확인한다.
- 부분 해소 (2026-09-21, [ADR-0064](decisions/0064-prespec-actionable-deadline-scope.md)): 위 `증상`의 인자 목록은 이미 낡았다 — 2026-09-16에 `deadline_status=open|passed|unknown`이, 2026-09-21에 `deadline_scope=current|passed|all`과 응답 집계 `deadline_scope_counts{current,passed}`가 들어왔다. `sort=deadline`도 3버킷(마감 전 오름 → 경과 최근 → null)이라 "첫 페이지가 지난 마감으로 채워진다"는 현상은 사라졌고, 검토할 항목의 기본 구간에는 경과 건이 아예 오지 않는다. **남은 것**: 새 구간은 `마감 전·미확인 / 마감 경과` 2분할이지 D-n 임박 **창**이 아니다. `deadline_within_days`류의 창 인자와 그 집계는 여전히 없으므로 대시보드 "사전규격 의견등록 마감 임박" 건수는 계속 `null`(확인 불가)로 남는다. `criticalDeadlineCount`의 하한 없음 주의도 그대로 유효하다.

## C-1과 C-2가 모델 호출 경계를 서로 반대로 잡는다

- 확인: 2026-09-03
- 재현 조건: 같은 "선별" 업무의 두 사례가 모델을 부르는 방식을 비교한다.
- 증상: C-2(발주계획)는 `web/backend/app/core/config.py:351,353`이
  `skills/bidops-screen/scripts/rank_order_plans_bm25.py`와
  `build_order_plan_screening_results.py`를 subprocess로 호출한다.
  [ADR-0001](decisions/0001-artifact-boundary.md)의 경계 그대로다.
  반면 C-1(공고)은 `web/backend/app/screening/orchestrator.py`에서 웹 프로세스 안의 판정
  어댑터(`ScreeningModelClient`)를 직접 생성하고, `app/screening/`에 `model_adapter.py`·
  `prompts.py`·`worker.py`가 들어와 있다.
- 2026-09-05 정정: [ADR-0050](decisions/0050-unified-openai-compatible-model-client.md)이
  C-1·개요·심층의 **transport**를 `app/core/model_client.py` 하나로 합쳤다. 그래서 전송 경계와
  fail-closed 규칙은 이제 한 벌이다. **그러나 이 항목이 말하는 경계 차이는 그대로다** — C-1은
  여전히 웹 프로세스 안에서 모델을 부르고 C-2는 subprocess 파일 계약으로 부른다. 위 재현
  조건의 파일 이름만 현재 값으로 고쳤다.
- 영향: 같은 업무 규칙이 두 경계에 나뉘어 있어 모델 전송 감사·테스트 격리·정책 pinning의
  확인 지점이 사례마다 다르다. 새 선별 흐름을 추가할 때 어느 쪽을 따라야 하는지 규칙이 없다.
- 지금 해결할 수 없는 이유: C-1은 [ADR-0013](decisions/0013-screening-orchestrator-boundary.md)이
  판정 단계만 애플리케이션 오케스트레이터로 옮긴 결과이고 이미 운영 중인 흐름이다.
  경계를 되돌리려면 정책 활성화·품질 게이트·큐 재실행 경로를 함께 옮겨야 하며
  [ADR-0043](decisions/0043-screening-deep-review-module-boundary.md)·[ADR-0045](decisions/0045-backend-module-layout.md)의 모듈 이주 범위를 넘는다.
- 접근 방법: 모듈 경계 이주가 끝난 뒤 C-1 오케스트레이터의 모델 호출부만 떼어
  C-2와 같은 subprocess 계약으로 맞출 수 있는지 별도로 판단한다. 그 전까지는 두 경계가
  다르다는 사실을 `ARCHITECTURE.md`에 명시해 새 흐름이 임의로 한쪽을 고르지 않게 한다.

## 운영 백엔드가 `experiments/`를 런타임 의존한다

- 확인: 2026-09-03
- 재현 조건: C-2 실행 경로가 읽는 정책·binding 파일의 위치를 확인한다.
- 증상: `web/backend/app/core/config.py:342,344,346`과 `web/backend/app/screening/ingest.py:1324,1333`이
  `experiments/order-plan-screening/config/order-plan-screening-policy.v1.json`과
  `order-plan-screening-phase0-binding.v1.json`을 읽는다.
  [ADR-0038](decisions/0038-order-plan-c2-phase0-contracts.md)이 고정한 계약의 정본이
  이름상 실험 보관소인 디렉터리에 있다.
- 영향: 실험 정리가 운영을 깨뜨릴 수 있고, 반대로 운영 때문에 실험 디렉터리를 자유롭게
  정리할 수 없다. 계약 파일의 집이 `skills/bidops-screen/contracts/`,
  `web/backend/app/deep_review/contracts/`, `experiments/.../config/` 세 곳으로 갈려
  새 계약을 어디 둘지 규칙이 없다. 물리적 중복은 없다(md5 대조 확인).
- 지금 해결할 수 없는 이유: 경로를 옮기면 `core/config.py`·`screening/ingest.py`와 실행 중인 회차의
  binding 참조가 함께 바뀌므로 C-2 종단 실행으로 재검증해야 한다.
- 접근 방법: 정책·binding을 `skills/bidops-screen/contracts/`로 승격하고 위 참조 경로를
  갱신한 뒤 C-2 종단 실행으로 확인한다. 계약 파일의 위치 규칙을 `docs/contracts.md`에 적는다.

## 모듈 이주가 드러낸 죽은 이름 네 자리

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 세 `_LEGACY_GENERATION_CONFIG*` 상수와 `_validate_relative_source_ref`를
  지웠다(지우기 전 `app/`·`tests/`·`scripts/`·`alembic/`·`docs/` 문자열 참조까지 전수 확인).
  `PageFilters`는 core에서 lifecycle로 내렸다 — 의존 규칙 위반은 아니었고(타입이 screening을
  import하지 않는다), "둘 이상이 쓰는 것을 core에 둔다"는 배정 원칙에서 소비자가
  `NoticeListResponse.filters`와 `lifecycle/routers/notices.py` 하나뿐이었다. 옛 자리에 재수출을
  남기지 않았고 응답 계약은 그대로다. 다섯째였던 `RuntimePipelineBridge.pipeline`도 지웠다 —
  받아서 들고만 있고 부르지 않던 인자라, `ScreeningRuntime`·`build_runtime`·조립 계층이 그것을
  넘기던 사슬을 함께 걷어 냈다. 그 결과 `app/runtime.py`의 모듈 runtime 생성 루프에서
  screening만 다르게 부르던 분기가 사라졌다(모듈 순서를 `screening,lifecycle`로 주면 그 인자가
  `None`이 되던 자리이기도 하다).
- 재현 조건: 아래 네 이름의 읽는 쪽을 `web/backend/app/`과 `tests/` 전체에서 찾는다.
- 증상: 대입만 되고 읽히지 않거나, 정의만 되고 불리지 않는다.
  - `_LEGACY_GENERATION_CONFIG`, `_LEGACY_GENERATION_CONFIG_VALUE`,
    `_LEGACY_GENERATION_CONFIG_DIGEST`(`app/screening/models.py:46,49,52`) — 세 이름 모두
    대입뿐이고 참조가 없다.
  - `_validate_relative_source_ref`(`app/core/schema_base.py:74`) — 호출자가 없다.
  - `RuntimePipelineBridge.pipeline`(`app/screening/runtime.py:56`) — 생성자가 lifecycle
    파이프라인 실행기를 받아 보관하지만 읽는 곳이 없다. 이주 전부터 그랬고, 소유 관계를
    드러내려고 남겼다는 주석이 붙어 있다.
  - `PageFilters`(`app/core/schema_base.py:28`)가 core에 있는데 `grade`·`readiness`·`focus`·
    `sample_role` 필드는 선별 어휘다. 실제 사용처는 lifecycle 하나뿐이다
    (`app/lifecycle/routers/notices.py`, `app/lifecycle/schemas/__init__.py`).
- 영향: 읽는 사람이 "선별 계보가 core에 있다" 또는 "legacy generation config가 아직 쓰인다"고
  읽는다. `PageFilters`는 core가 도메인 어휘를 갖지 않는다는 규칙(ADR-0045 §2)의 예외처럼
  보이지만 실제로는 lifecycle 응답 model이 선별 필터를 그대로 되비추는 REST 계약
  (`NoticeList`의 `filters`)의 결과다.
- 지금 해결할 수 없는 이유: 이번 작업의 원칙은 **동작 보존**이었다. 네 이름을 지우거나 옮기면
  import 그래프와 wire schema 이름이 바뀌어, 이주가 REST 표면을 바꾸지 않았다는 확인이
  흐려진다. `PageFilters`를 lifecycle로 내리는 것은 응답 model의 소유를 바꾸는 일이라 계약
  검토가 따로 필요하다.
- 접근 방법: 죽은 세 자리(legacy generation config 3개, `_validate_relative_source_ref`,
  `RuntimePipelineBridge.pipeline`)는 동작 변화가 없으므로 다음 정리 작업에서 삭제한다.
  `PageFilters`는 `NoticeList`의 `filters` 계약을 `docs/contracts.md`에서 먼저 확인한 뒤
  lifecycle로 내릴지, core에 남기되 필드 소유를 문서로 못박을지 판단한다.

## `experiments/`의 회사자료가 gitignore되어 `git archive` 사본이 자족적이지 않다

- 확인: 2026-09-04
- 재현 조건: `git archive <ref> experiments/order-plan-screening | tar -x -C <새 디렉터리>` 로
  실험 트리를 복사한 뒤 `review-inputs/company/`와 `review-inputs/prompts/`를 본다.
- 증상: `.gitignore:7,8`이 `experiments/order-plan-screening/review-inputs/company/*.json`과
  `review-inputs/prompts/*.txt`를 제외한다. 회사자료를 저장소에 넣지 않는다는 경계의 결과이며
  의도된 것이다. 다만 그래서 git에서 만든 사본에는 그 입력이 없다.
- 영향: 격리 검증을 위해 트리 사본을 만드는 절차(모듈 폴더를 지운 복사본에서 테스트를 돌리는
  식)가 C-2 관련 경로에 닿으면 사본이 자족적이지 않다는 것을 검증자가 미리 알아야 한다.
  모르면 "복사본에서만 실패한다"를 코드 결함으로 오해한다.
- 지금 해결할 수 없는 이유: 회사자료를 저장소나 image에 넣지 않는 것이 확정 경계다
  (런타임 이미지 항목). gitignore를 푸는 것은 답이 아니다.
- 접근 방법: 트리 사본을 만드는 검증 절차는 `git archive` 뒤에 그 두 디렉터리를 작업 트리에서
  따로 복사하는 단계를 포함한다. 사본 기반 검증을 문서로 고정할 때 이 단계를 함께 적는다.

## `create_app()`은 한 프로세스에서 두 번 부를 수 없다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 확장점 등록에 **소유자 키**를 붙였다. 등록 함수는
  `register_*(provider, *, owner: str)` 형태이고, 같은 owner가 다시 등록하면 제자리 교체(예외
  없음), 다른 owner가 이미 찬 projection 자리를 채우려 하면 여전히 `RuntimeError`다. hook은
  `(종류, owner)`로 키를 잡아 **두 번 등록되지 않는다** — 가드를 그냥 없앴다면 회차 적재 hook이
  두 번 실행됐을 것이고, 가드가 그 결함을 가리고 있었다. 실행 순서는 최초 등록 순서
  (= `BIDOPS_MODULES` 순서) 그대로다. owner는 lifecycle이 해석하지 않는 불투명한 문자열이다.
  `uvicorn --factory app.main:create_app`이 동작한다. 등록 시점은 여전히 `main.py` 조립 시점이다.
- 재현 조건: 같은 인터프리터에서 `from app.main import create_app`을 한 뒤
  `create_app()`을 부른다.
- 증상: `RuntimeError: 판정 projection 제공자가 이미 등록됐다`로 끝난다.
  `app/main.py`의 확장점 등록 구역은 **프로세스 전역** registry에 등록하고,
  같은 파일의 모듈 수준 `app = create_app()`이 import만으로 그 등록을 소진한다.
  `app/lifecycle/extensions.py`의 중복 등록 가드가 두 번째 호출을 막는다.
- 영향: 운영은 `web/Dockerfile`의 `uvicorn app.main:app`이라 무해하다. 그러나
  `uvicorn --factory app.main:create_app`은 즉시 죽고, 앱을 두 개 만들려는 코드는
  `reset_extension_registry`와 `restore_extension_registry`를 손으로 짝지어야 한다
  (`tests/app/test_module_selection.py`의 fixture가 그 boilerplate다). 이 제약이
  어느 문서에도 없어 다음 사람이 factory 방식으로 바꾸려다 막힌다.
- 지금 해결할 수 없는 이유: 중복 등록 가드는 "제공자가 조용히 교체되지 않는다"는
  보장이라 그냥 없앨 수 없다. registry 수명을 앱 객체에 매다는 것은 확장점 설계를
  다시 여는 일이고, 이번 이주의 "동작을 바꾸지 않는다"를 벗어난다.
- 접근 방법: `create_app`이 자기 등록 구역의 registry 수명을 소유하게 하거나
  (앱마다 registry를 새로 만들고 등록한다), 재등록을 같은 제공자에 한해 idempotent로
  만든다. 어느 쪽이든 격리 API 테스트에서 projection이 비지 않는 것을 먼저 확인한다.

## 모듈 공개 표면에 밖에서 아무도 쓰지 않는 이름이 많다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 실제 소비자를 AST로 전수 조사해 줄였다 — lifecycle 61→49,
  screening 66→22, deep_review 12→11. 남은 이름 중 정적 import가 없는 것은 조립 계층이
  `getattr`로 가져가는 router 인스턴스 21개와 `build_runtime` 3개뿐이며, 표에 왜 공개인지를
  구역 주석(조립이 쓴다 / 형제 모듈이 쓴다 / 진입점이 쓴다)으로 적었다. deep_review가 쓰는
  screening seam 세 이름은 그대로다. 더 중요한 것은 **경계 검사 6**을 새로 넣은 것이다 —
  조립 계층의 startup 파일(`app/__init__.py`, `main.py`, `runtime.py`)이 상태를 바꾸거나 모델을
  부르는 이름(`activate_policy`, `seed_policy`, `create_profile_snapshot`, `ingest_run`,
  `OllamaClient`, `ScreeningWorker` 등)을 import하면 실패한다. 별도 프로세스 진입점
  (`workers/analysis.py`, `migrations/import_sqlite.py`)과 `alembic/`은 그것이 목적이므로 제외다.
- 재현 조건: `app/**`와 `tests/**`에서 `from app.<module> import X` / `from ..<module> import X`
  를 AST로 모아 각 모듈 `__init__.py`의 `_EXPORTS` 키와 대조한다.
- 증상: screening 공개 이름 66개 중 router 인스턴스와 `build_runtime`을 빼면 40여 개가
  모듈 밖 소비자가 없다(`activate_policy`, `create_policy`, `seed_policy`,
  `ScreeningOrchestrator`, `ScreeningWorker`, `OllamaClient`, `ArtifactStore`,
  `assemble_*_prompt`, `load_run_judgments` 등). lifecycle에도
  `ATTACHMENT_ORIGINS`·`get_notice`·`get_run`·`list_agency_portals`·`match_agency_portal`·
  `list_attachments_for_notice`·`list_order_plans_for_run`·`IngestResult`·
  `ClaimedDirectoryLoad`가 같은 상태다. 테스트조차 하위 경로로 받는다
  (`from app.screening.ollama import OllamaClient`).
- 영향: 넓이 자체보다 **조립 계층이 그 이름들을 쓸 수 있게 된 것**이 문제다.
  `main.py`가 `from .screening import activate_policy, seed_policy`를 하고 startup에서
  부르면 "앱 startup은 seed·정책 활성화를 하지 않는다"는 경계를 깨는데, 경계 검사
  다섯 중 어느 것도 그것을 잡지 못한다 — 조립 계층 → screening 공개 이름은 허용
  방향이기 때문이다.
- 지금 해결할 수 없는 이유: 어느 이름이 "지금 안 쓰이지만 공개여야 하는가"는 모듈
  진입점 설계의 판단이고, 표를 줄이면 `_EXPORTS`와 `__all__`을 함께 손봐야 해서
  이주 검증이 끝난 시점에 넣을 변경이 아니다.
- 접근 방법: 밖에서 안 쓰는 이름을 `_EXPORTS`에서 빼거나, 뺄 수 없으면 표를 구역으로
  나눠 왜 공개인지(조립이 쓴다 / 형제 모듈이 쓴다 / 진입점이다)를 적는다. startup이
  하면 안 되는 일은 별도 검사로 고정하는 편이 낫다.

## `app/deep_review/contracts/schemas.py`는 호출자가 없는 재수출 파일이다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 파일을 지웠다. 재수출하던 이름 10개가 모두
  `app/deep_review/contracts/__init__.py`의 `__all__`에 이미 있고, `schema_path()`가 `.json`
  파일 이름으로 계약을 찾으므로 이 파일의 존재는 무관했다. 계약 JSON과 `_validator.py`는 그대로다.
- 재현 조건: `grep -rn "contracts.schemas\|from .schemas import" web/backend/app web/backend/tests`
- 증상: 파일 첫 줄이 `"""Compatibility exports for callers that prefer a schemas module."""`
  인데 `app/`·`tests/`·`scripts/`·`docs/` 어디에도 호출자가 없다. 이주 전
  (`app/contracts/deep_review/schemas.py`)에도 이미 그랬다.
- 영향: 없다. 다만 "옛 import 경로에 호환 shim을 두지 않는다"는 이번 경계 작업의
  원칙과 파일이 스스로 밝힌 목적이 어긋나 보여, 읽는 사람이 살아 있는 호환 경로로 오해한다.
- 지금 해결할 수 없는 이유: 죽은 코드 정리는 이번 이주의 범위 밖이었다. 이주가 파일을
  옮긴 commit에서 함께 지웠어야 한다.
- 접근 방법: 지운다. 지우기 전에 `deep_review/contracts/__init__.py`가 같은 이름을
  올리고 있는지만 확인한다.

## lifecycle의 확장점 실패 로그가 특정 제공자의 어휘를 쓴다

- 확인: 2026-09-04
- 상태: **해결** (2026-09-04). 이벤트 이름을 `prespec_attachment.refresh_failed`에서
  `extension.tracking_decision_hook_failed`로, 메시지를 "tracking decision extension hook
  failed"로 바꿨다. 제공자 이름 대신 lifecycle이 정당하게 아는 값만 남긴다(등록된 hook 수,
  예외 타입). try/except **동작은 그대로**이며 registry 조회도 try 안에 남겼다 — 밖으로 빼면
  삼켜지던 오류가 500이 된다. `app/lifecycle/**` 전체를 훑었고 이 자리가 유일한 누수였다.
  `services/pipeline.py`의 `screening-results.json`은 형제 모듈이 아니라 파이프라인 **파일 계약**
  이름이라 남겼다.
- 재현 조건: `app/lifecycle/routers/opportunities.py`의 추적 결정 hook 호출부를 본다.
- 증상: 바로 위 주석이 "어느 모듈이 무엇을 하는지는 모르고"라고 적어 두고, 아래 except
  블록은 `"pre-spec attachment eligibility refresh failed"`와
  `event: "prespec_attachment.refresh_failed"`를 남긴다. 그 문구는 지금 등록된 유일한
  제공자(deep_review)의 어휘다.
- 영향: `BIDOPS_MODULES`에서 deep_review를 빼고 다른 제공자를 붙이면 로그가 거짓이 된다.
  lifecycle이 형제 모듈을 모른다는 규칙이 코드에서는 지켜지는데 로그에서만 새는 자리다.
  (호출부의 try/except 동작 자체는 이주 전과 같다.)
- 지금 해결할 수 없는 이유: 없다. 작은 문자열 변경이지만 이주 검증이 끝난 뒤에 로그
  이벤트 이름을 바꾸면 그 이름에 기대는 관측 기록과 어긋난다.
- 접근 방법: 이벤트 이름을 확장점 이름 기준으로 바꾸고(`extension.tracking_hook_failed`),
  어느 제공자가 실패했는지는 registry가 아는 이름을 함께 남긴다. 로그 이름을 바꾸는
  작업과 함께 묶는다.

## B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다

- 재현 조건: `web/frontend`에서 `npm run test:design`을 실행하고 `docs/design/mockups/canvas.json`의 14개 artboard와 `tests/design-snapshots/`·manifest-driven `design.spec.ts`를 대조한다. 기존 공통 시각 회귀는 `npx playwright test visual.spec.ts`로 실행한다.
- 증상: PLAN.md §3·§5·§7이 요구하는 14-artboard manifest, 승인된 PNG baseline, fixture·viewport·crop 매핑과 그 변경 승인 기록이 저장소에 없다. 현재 design suite는 shell 차원의 5 passed·3 skipped에 그치며, 기존 visual suite는 현 UI와 맞지 않는 baseline 때문에 204 passed·144 failed로 끝난다.
- 영향: B-F 화면의 기능·반응형·접근성 검증은 가능하지만, 승인된 기준 이미지와 픽셀/crop 일치 여부를 주장할 수 없다. 승인 없이 기존 snapshot을 갱신하면 설계 검수 증거를 덮어쓰게 된다.
- 상태: **차단** (2026-09-03 독립검증). 코드 구현 완료의 차단이 아니라 PLAN 전체 완료 정의에 포함된 승인 설계 자산의 부재다.
- 지금 해결할 수 없는 이유: 14개 artboard의 제품 승인 PNG와 각 fixture·viewport·crop의 승인 메타데이터가 저장소나 현재 요청에 제공되지 않았다. 이를 임의로 생성하거나 기존 baseline을 승인본으로 승격할 권한이 없다.
- 접근 방법: 제품·디자인 담당자가 14개 PNG와 source hash, viewport, fixture, crop, 승인자·승인 시각을 제공하면 `tests/design-snapshots/manifest.json`과 manifest-driven `design.spec.ts`를 추가하고, 기준선 변경은 승인 기록이 있을 때만 갱신한다. 그 뒤 laptop 1280x800·desktop 1440x900 두 폭(ADR-0047)과 접근성 게이트를 다시 실행한다. 2026-09-04 팔레트 전환으로 기준 이미지는 무드보드 v2로 만들어야 하며, 그 선행 조건은 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-3·0-4다.

## 발주계획 추적 결정(결정 1)을 저장할 REST 계약이 없다

- 재현 조건: `web/backend/app/screening/routers/order_plans.py`의 경로 다섯 개를 확인한다. 목록·상세·screening-history·screening-feedback(GET/POST)뿐이다. `PATCH /opportunities/{id}/tracking-status`는 사업기회 식별자로만 부를 수 있고, `OrderPlanListItem`·`OrderPlanDetailResponse`(둘 다 `_Strict`)에는 `opportunity_id`도 추적 상태도 없다.
- 증상: ADR-0046(git 이력 docs/design/ADR.md, 삭제됨) 결정 4가 추적 결정을 발주계획 화면의 결정 1로 채택했는데, 그 결정을 읽을 수도 쓸 수도 없다. 구 `docs/design/PLAN.md`(git 이력, 삭제됨) 단계 C 작업 5(추적 결정을 상세 pane 바닥의 결정 액션으로)와 완료 게이트 2("추적 결정과 사람 판단 수정이 서로 다른 요청으로 저장된다")를 서버 없이 만족시킬 수 없다.
- 영향: 단계 C의 화면은 만들 수 있으나 **결정이 서버에 남지 않는다.** 이 상태에서 결정을 화면 상태나 localStorage에 기록하면 담당자에게 저장된 것처럼 보이면서 실제로는 사라지므로, 그렇게 만들지 않는다.
- 상태: **차단** (2026-09-04). 화면 구현의 차단이 아니라 계약의 부재다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 임의로 endpoint를 만들거나 기존 사업기회 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: 요청안을 `order-plan-tracking-contract-request.md`(git 이력 docs/design/order-plan-tracking-contract-request.md, 삭제됨)로 작성해 백엔드 파트에 보낸다. 조사 결과 **새 table은 필요하지 않을 가능성이 높다** — 소유 사업기회와 `stage='order_plan'` official 링크는 `ingest/loader.py`가 이미 만들고, 상태 4값과 append-only `AuditEvent`도 이미 있다. 없는 것은 응답에 그 상태를 싣는 것과 발주계획 식별자로 쓸 경로 둘이다. 계약이 확정될 때까지 화면은 요청안 §7의 규칙을 지킨다: adapter 한 곳으로 호출을 모으고, 실패를 성공으로 보이게 하지 않으며, 응답에 추적 상태가 없으면 `계약 미구현`으로 표시하고 `미선택`으로 바꾸지 않는다. 계약이 구현·검증되기 전에는 단계 C를 완료로 적지 않는다.
- 종결(2026-09-16): 코드에 구현됨(일괄·단건 추적 REST).

## 팔레트 전환 뒤 화면 단위 시각 회귀를 잡을 기준선이 없다 (해결)

- 재현 조건: `web/frontend`에서 `npx playwright test`를 실행한다. 2026-09-04 단계 A(무드보드 팔레트 적용, ADR-0048) 이후 기준이다.
- 증상: 단계 A 직후 `370 passed, 75 failed, 3 skipped`. 실패 75건 중 73건이 `visual.spec.ts`다. 팔레트가 모든 화면의 색을 바꿨으므로 옛 무채색 기준선과 다른 것이 정상이며, 실패 자체는 회귀의 증거가 아니다.
- 정정 (2026-09-04, 단계 B): 그 73건은 전부 스냅샷이 아니다. **팔레트 스냅샷 72건 + `/queue` 1280px 가로 오버플로 1건**이다. 오버플로 1건은 색과 무관한 레이아웃 실패이며(`.notice-attachments-panel`의 첨부 파일명이 19.77px 넘침), 단계 B의 변경 전후로 같은 값이 나오는 것을 확인했다. 단계 E가 `검토 대기열`을 이행할 때 함께 정리한다. 단계 B 이후 수치는 `382 passed, 74 failed, 2 skipped`이며 새 실패는 없다(74 = 위 73건 + `visual.spec.ts:257` flake 1건, 단독 실행 시 통과).
- 해소 (2026-09-04, 단계 E): `/queue` 오버플로 1건을 고쳤다. `.attachment-name`이 ellipsis로 자르고 있었지만 **자름은 부모의 시각 효과일 뿐 자식 `span`의 레이아웃 상자는 그대로 넘쳐 있었다.** 자식이 스스로 `max-width: 100%`와 ellipsis를 갖도록 고쳤고 `visual.spec.ts`의 가로 넘침 36건이 모두 통과한다. **남은 실패는 팔레트 스냅샷 72건뿐이며, 이 finding이 말하는 신호 손실은 그 72건에만 해당한다.**
- 영향: **그 73건이 실패로 남아 있는 동안 화면 단위 레이아웃 회귀를 자동으로 구분할 수 없다.** "색이 바뀌어서 실패"와 "레이아웃이 깨져서 실패"가 같은 실패로 보인다. 셸은 `tests/design-shell.spec.ts`의 구조 검사(테마 scope, computed 색 대 PRD §4.1, 248/76px 치수, 1280·1440·1920px 가로 오버플로 없음, legacy 토큰 회귀)로 지켜지지만 이 검사는 셸 범위이고 화면 내부 레이아웃은 보지 않는다.
- 상태: **해결** (2026-09-04). 당시 판단은 "시안을 다시 렌더해야 기준선을 만들 수 있다"였는데, 그것은 **시안 충실도 대조**의 조건이지 앱 자기 회귀 기준선의 조건이 아니었다. 둘을 한 덩어리로 묶어 둔 탓에 픽셀 72건이 계속 빨간 채로 남아 있었다.
- **해결 (2026-09-04, 화면 검사 층 분리).** 원인은 팔레트가 아니라 **한 파일이 세 가지 일을 하고 있었던 것**이다. `visual.spec.ts` 87개가 픽셀 36 + 가로 넘침 36 + 의미 15로 섞여 있어, 픽셀이 깨지면 나머지 51개의 초록이 같은 실행 결과에 묻혔다. 그래서 "실패하지만 정상"이라는 단서를 문서 다섯 군데에 적어야 했다.
- 조치: 파일을 세 층으로 갈랐다 — `screen-semantics.spec.ts`(의미, 한 폭) · `overflow.spec.ts`(구조, 두 폭) · `pixel-screens.spec.ts`(픽셀, 게이트 밖). 공유 fixture는 `screen-fixtures.ts`로 뺐다. 게이트는 앞의 두 층(`npm run test:screens`)이고 픽셀은 `npm run test:pixel`로만 돈다.
- **기준선 교체 승인 기록.** 사유: 팔레트 전환(ADR-0048)으로 옛 무채색 기준선이 전부 무효가 됐고, 앞으로 화면을 고칠 계획이라 회귀 기준선이 필요하다. 영향 화면: 아래 여덟 장으로 줄였다 — `dashboard`·`criteria`·`order-plans-list`·`order-plan-detail`·`pre-specs-list`·`opportunities-list`·`deep-review-complete`·`bid-delta-changed`. 통짜 36장은 화면을 건드릴 때마다 기준선 커밋을 끌고 오면서 실제로 잡아 주는 것은 골격 여덟 가지가 거의 다였다. 나머지 화면은 구조·의미 층이 본다. 승인: 저장소 소유자의 명시 지시(2026-09-04). 옛 기준선 144장(39MB)은 지우고 새 여덟 장(1.1MB)을 만들었다.
- **남은 한계.** 이 기준선은 **앱이 자기 화면을 찍은 회귀 기준선이며 승인된 시안이 아니다.** 시안 충실도 대조는 여전히 열려 있고 그 선행 조건은 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-3·0-4다 — 위의 "B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다"가 그 항목이다. 또한 발주계획 추적 결정 계약이 없어 화면이 `계약 미구현`을 띄우는 상태가 기준 이미지에 그대로 들어 있다. 회귀 감지에는 문제없지만 **"이 화면이 옳다"는 승인으로 읽지 않는다.**
- 곁들여 고친 것: 마감·감사 경로 검사가 전체 실행에서만 깨지던 flake. 이동 후 주소 확인 여유가 기본 5초여서 400여 개가 동시에 붙으면 못 들어왔다. 단독 실행 6회는 통과했다. 여유를 15초로 늘렸다.

## 사업기회 추적 이력을 읽을 계약이 없고 구역별 집계도 서버가 세지 않는다

- 재현 조건: `web/backend/app/lifecycle/routers/opportunities.py`의 경로 넷을 확인한다. 목록(`GET ""`)·상세(`GET /{id}`)·후보 연결 판정(`PATCH /links/{id}/decision`)·추적 상태 변경(`PATCH /{id}/tracking-status`)뿐이다. 목록 query는 `tracking_status`·`first_registered_stage`·`sort`·`limit`·`offset`이다.
- 증상 1 — **추적 이력이 최근 한 건뿐이다.** `opportunity_tracking`은 상태 변경마다 append-only `AuditEvent`(`opportunity.tracking_status.changed`)를 남기지만 그것을 읽는 endpoint가 없다. 화면이 받는 것은 `OpportunityStateView`의 `tracking_status`·`tracking_reason`·`tracking_selected_by`·`tracking_selected_at` 넷, 즉 **마지막 한 건**이다. ADR-0046(git 이력 docs/design/ADR.md, 삭제됨) 결정 2가 요구한 사업 추적 상세의 `추적 이력` 탭이 이전 결정을 보여줄 수 없다.
- 증상 2 — **구역별 집계와 필터가 없다.** ADR-0046 결정 2의 구역 `조치 필요`는 저장된 상태가 아니라 "미선택이거나, 재검토 신호나 예외 작업이 남았다"는 파생 조건이다. 서버에 `recheck_signal` 필터도 후보 연결 대기 필터도 집계 응답도 없어, 화면이 한 페이지를 받아 직접 나눈다.
- 영향: (1) `추적 이력` 탭은 최근 한 건만 보여주고, 그것이 이전 결정이 없다는 뜻이 아님을 화면이 직접 밝힌다(`.opportunity-contract-gap`). 이전 revision을 화면이 지어내지 않는다. (2) `조치 필요` 구역의 건수는 **받은 페이지 안에서 센 값**이며, 목록 머리말이 그 사실과 남은 건수를 함께 적는다. 전체 총계로 읽으면 과소 계상된다.
- 상태: **수용됨** (2026-09-04, 단계 E). 화면 구현의 차단이 아니라 계약의 부재이며, 두 한계 모두 화면이 숨기지 않고 표시한다.
- 지금 해결할 수 없는 이유: REST·DB 계약은 백엔드 파트의 소유이고, 화면 작업이 감사 기록 읽기 경로를 새로 만들거나 목록 계약의 의미를 바꿀 권한이 없다.
- 접근 방법: (1) `GET /api/opportunities/{id}/tracking-decisions`를 추가해 append-only 이력을 `revision`·`tracking_status`·`reason`·`selected_by`·`selected_at`·`audit_event_id`로 연다. 발주계획 쪽 같은 요청(`order-plan-tracking-contract-request.md`(git 이력 docs/design/order-plan-tracking-contract-request.md, 삭제됨) §2.1)과 같은 wire shape를 쓰면 화면이 `ReviewRevisionHistory` 하나로 둘을 그린다. (2) 목록에 `recheck_signal`·`has_pending_candidate_link` 필터와 구역별 `section_counts` 집계를 추가하고 `docs/contracts.md`의 `OpportunityList` 항목에 등록한다. 그 전까지 화면은 저장된 추적 상태로 서버를 거르고(`추적 중`·`보류`·`추적 종료`) `조치 필요`만 받은 페이지에서 나눈다.
- 종결(2026-09-17): 코드에 구현됨(`GET /api/opportunities/{id}/tracking-decisions`가 append-only 추적 이력을, `GET /api/opportunities`의 `section` 필터와 `section_counts`가 서버 구역 집계를 제공한다).

## C-1 모델명이 바뀌어 기존 실행·판정 row가 새 실행에서 거부된다

- 확인: 2026-09-05
- 재현 조건: 옛 이름(`qwen3.8:27b`)으로 기록된 `ScreeningExecution`과 그 판정이 있는 DB에서
  새 회차를 판정하거나 재판정한다. `web/backend/app/core/model_binding.py`의 `MODEL_NAME`은
  이제 `qwen3.8-27B`이고 C-1이 부르는 이름은
  `settings.vllm_screening_model`(`BIDOPS_VLLM_SCREENING_MODEL`, 기본 `qwen3.8-27B`)이다.
- 증상: carry-over 검증과 재판정 검증이 실행 binding의 모델명을 대조하므로 옛 이름의 row는
  이어지지 않고, `queue.enqueue`도 현재 이름과 다른 binding을 거부한다.
- 영향: 이전 회차의 판정을 승계하려는 재판정이 승계 대신 새 판정으로 떨어지거나 거부된다.
  `docs/model-quality-gate.md`가 고정 입력으로 못 박은 40건 표본도 옛 이름으로 기록돼 있으면
  그 execution을 새 A/B의 baseline으로 재사용할 수 없다.
- 지금 해결할 수 없는 이유: 실행 binding은 불변이다([ADR-0007](decisions/0007-immutable-runs.md)).
  저장된 모델명을 사후에 새 이름으로 고쳐 쓰는 것은 "회차 원본을 덮어쓰지 않는다"는 게이트를
  깬다. 옛 데이터를 이어 쓸지, 새 이름으로 다시 측정할지는 담당자의 판단이 필요하다.
- 접근 방법: (1) 새 이름으로 A/B를 다시 측정하고 옛 execution은 이력으로만 둔다(권장), 또는
  (2) 옛 이름을 새 이름의 별칭으로 인정하는 명시적 매핑을 binding 검증에 도입하고 그 결정을
  ADR로 남긴다. (2)를 고르면 어느 실행이 어느 실제 배포에서 나왔는지 감사에서 구분할 수
  있어야 한다.

## `policy_quality` snapshot 모양이 바뀌어 이전에 만든 미실행 심층 검토가 503으로 닫힌다

- 확인: 2026-09-05
- 재현 조건: 이 변경 **전에** 생성돼 아직 실행되지 않은 심층 검토를 worker가 claim한다.
- 증상: `web/backend/app/deep_review/services/deep_reviews.py`의 `run_claim`이 생성 감사의
  `policy_quality`를 현재 계산값과 **정확히 같은지** 비교한다. 참조 실행 표식을 위해
  snapshot에 `deployable` 키가 항상 붙게 됐으므로 옛 snapshot과 모양이 달라지고
  `service_unavailable`(503, "pinned deep review 입력이 변경되었습니다")로 닫힌다.
- 영향: 변경 시점에 큐에 남아 있던 심층 검토는 실행되지 않는다. 결과가 틀리게 나오는 것이
  아니라 **아예 실행되지 않는** 것이므로 조용한 오염은 없다.
- 지금 해결할 수 없는 이유: 옛 snapshot을 새 모양으로 다시 쓰면 감사 이벤트를 덮어쓰게
  된다. append-only 감사 계약을 깨는 조치라 하지 않는다. 비교를 느슨하게 만들면 pinned 입력
  대조 자체가 약해진다.
- 접근 방법: 해당 review에 **새 attempt를 만든다.** 새 attempt는 현재 모양의 snapshot으로
  다시 고정된다. 운영 절차의 참조 실행 6단계에 이 중단 기준을 적어 두었다.

## 자동 생성된 심층 검토가 실행 단계에서 생성 감사를 찾지 못한다

- 확인: 2026-09-05
- 상태: **해결** (2026-09-05). 생성 감사를 찾는 자리를 **모두** 두 action을 보게 바꿨다.
  `run_claim`의 snapshot 조회와 `create_attempt`의 correlation 조회뿐 아니라
  `services/reports.py`·`routers/reports.py`의 계보 조회, `services/agent_e2e.py`의
  provider context, `agents/deep_review/agent.py`의 재시도 계보,
  `agents/{decision,deep_review}/projection.py`의 생성 감사 선별까지 여덟 자리였다.
  `deep_review.create`·`deep_review.auto_create` 표는 `app/core/constants.py`의
  `DEEP_REVIEW_CREATION_ACTIONS` 한 벌로 옮겼다 — 의존성을 갖지 않는 agent projection도
  같은 표를 읽어야 해서 서비스에 둘 수 없었다. 회귀는 자동 생성된 검토를
  `claim_next_job` → `run_claim`으로 실제로 완주시키고 사람이 재시도까지 하는
  `tests/app/test_auto_deep_review_start.py`의 두 검사가 막는다. 고치기 전에 두 검사가
  각각 503·500으로 실패하는 것을 확인했다.
- 재현 조건: `SW사업대상=Y` 사전규격에서 자동 시작이 심층 검토를 만들고
  (`deep_review.auto_create`), analysis worker가 그 검토를 claim한다.
- 증상: `deep_review.py`의 `run_claim`(`AuditEvent.action == "deep_review.create"`)과
  `create_attempt`의 correlation 조회(`_audit_correlation_id(..., action="deep_review.create")`)가
  생성 action을 **문자열 하나로 고정**하고 있다. 같은 파일이 다른 자리에서는
  `CREATION_ACTIONS`(`deep_review.create`, `deep_review.auto_create`) 튜플을 쓴다.
  자동 생성 review에는 `deep_review.create` 이벤트가 없으므로 `audit_snapshot is None`이 되어
  `service_unavailable`(503, "deep review 입력 snapshot이 없습니다")로 닫히고, 재시도 경로도
  correlation 불일치로 `processing_failed`(500)가 된다.
- 영향: **자동 시작이 만든 심층 검토는 실행되지 않는다.** 화면의
  `auto_preparation_status`는 `deep_review_started`로 보이지만 그 검토는 진행되지 않는다.
  사람이 직접 만든 검토는 영향이 없다. 이 경로를 덮는 테스트는 없다 —
  `tests/deep_review/test_auto_preparation.py`가 감사 action 상수값만 단언한다.
- (해결 전 기록) 지금 해결할 수 없는 이유: T10의 범위는 문서이며 `.py` 파일을 고치지 않는다.
- 남은 위험: 이 결함은 "사람 경로만 테스트하면 통과한다"는 부류다. 생성 action을 하나 더
  더하는 변경이 다시 오면 같은 자리들이 또 갈라진다. 새 생성 경로는 `CREATION_ACTIONS`에
  올리고, 그 경로로 만든 검토를 실제로 실행하는 검사를 함께 넣는다.

## 개요 attempt와 암호화된 원응답 사이에 직접 FK가 없다

- 확인: 2026-09-05
- 재현 조건: 개요 검토 attempt 하나가 어느 모델 응답 객체에서 나왔는지 DB만으로 찾으려 한다.
- 증상: 원응답은 `ContentObject`와 `ContentObjectLocation('model-response')`로 암호화 저장되지만
  `prespec_overview_attempt`에는 그것을 가리키는 열이 없다. 대조는 감사 이벤트
  `prespec_overview.attempt_run`의 `safe_metadata.response_sha256`으로만 가능하다.
- 영향: 감사 이벤트가 없거나 지워지면 attempt와 원응답의 연결을 DB에서 복원할 수 없다.
  응답 객체 자체는 남지만 어느 attempt의 것인지 확정할 수 없다.
- 지금 해결할 수 없는 이유: 이 표에 열을 더하는 것을 명세가 이번 범위에서 두 개
  (`lease_owner`, `lease_expires_at`)로 제한했다. FK를 더하면 그 경계를 넘고, 기존 row의
  backfill 정책도 함께 정해야 한다.
- 접근 방법: nullable `response_content_object_id` FK를 다음 migration에서 더하고, 기존 row는
  추정 없이 `null`로 둔다. 감사 이벤트의 `response_sha256`은 그대로 유지해 두 경로가 서로를
  검증하게 한다.

## 이 변경 전에 만들어진 문서 구조에는 segment manifest가 없다

- 확인: 2026-09-05
- 재현 조건: `0018` 이전에 저장된 `DocumentStructure`의 ID로
  `GET /api/document-structures/{structure_id}/segments`를 호출한다.
- 증상: 404 `not_found`다. manifest는 **구조 저장 시점의 메모리 payload로만** 만들어지고
  저장된 `document_block`에는 ordinal이 없어 경계를 사후에 되짚을 수 없다.
- 영향: 옛 문서로 만든 심층 검토는 문서 inventory 패널이 비고, `requirement_inventory`
  check도 그 문서에 대해서는 근거가 없다. 그 사실이 조용히 "요구사항 누락 없음"으로 읽히면
  안 되므로 화면과 검증이 각각 없음을 밝힌다.
- 지금 해결할 수 없는 이유: 사후 재구성이 **불가능**하다. `document_block`에 ordinal을 더하는
  것은 저장된 구조의 의미를 바꾸는 일이고, 기존 행에 넣을 값이 없다.
- 접근 방법: 그 문서를 다시 올려 새 `DocumentVersion`·`DocumentStructure`를 만든다. 옛
  구조를 고치지 않는다. 대량 재처리가 필요하면 별도 결정으로 다룬다.

## 보고서의 문서 inventory 패널이 문서 하나만 보여 준다

- 확인: 2026-09-05
- 재현 조건: 여러 문서가 든 묶음으로 심층 검토를 하고 보고서 화면의 우측 문서 inventory
  패널을 본다.
- 증상: 패널은 **선택된 근거가 가리키는 문서 하나**의 manifest만 보여 준다. 묶음이나 공고에서
  그 안의 문서들의 `structure_id` 목록을 주는 endpoint가 없고, `DocumentVersionView`에도
  `structure_id`가 없기 때문이다.
- 영향: "문서별 inventory"를 요구한 설계를 절반만 만족한다. 근거를 고르지 않으면 패널이
  비고, 고르면 그 문서만 보인다. 화면이 어느 문서의 것인지 문장으로 밝히므로 다른 문서의
  값으로 오해할 위험은 막고 있다.
- 지금 해결할 수 없는 이유: 해결에 REST 계약 추가가 필요한데, 이번 범위가 허용한 REST 추가
  목록에 그 endpoint가 없다.
- 접근 방법: `DocumentVersionView`에 nullable `structure_id`를 더하거나
  `GET /api/document-bundles/{bundle_id}/structures`를 추가해 `docs/contracts.md`에 등록한다.
  그 뒤 패널을 문서 목록으로 바꾼다.

## 사전규격 목록의 등급 필터가 브라우저 쪽이라 집계와 비대칭이다

- 확인: 2026-09-05
- 재현 조건: `/pre-specs?grade=우선 검토`를 연다.
- 증상: `GET /api/pre-specs`에 `grade` 질의 인자가 없다. 화면 필터는 **이미 불러온 페이지만**
  좁히고, 같은 응답의 `overview_status_counts`는 **필터 이전 전체 집합**을 가리킨다. 두 수의
  대상 집합이 다르다.
- 영향: 페이지를 넘기면 등급별로 보이는 건수가 페이지마다 달라지고, 그룹 헤더 건수와 목록
  건수가 맞지 않는다. 화면이 이 사실을 직접 적어 두었으므로 잘못된 총계로 읽힐 위험은
  문구로 막고 있다.
- 지금 해결할 수 없는 이유: 서버 쪽 `grade` 인자는 `PreSpecList` query 계약과 등급 projection
  확장점을 함께 바꾸는 일이고, 이번 범위가 허용한 REST 변경 밖이다.
- 접근 방법: `PreSpecList` query에 `grade`를 더하고 판정 projection 확장점의
  `notice_ids_for_filters`로 서버에서 거른다. 그때 `overview_status_counts`도 같은 필터를
  반영하게 해 두 수의 대상 집합을 맞춘다.

## 리뷰 저장 hook과 첨부 취득 worker가 같은 문서 집합으로 묶음을 둘 만들 수 있다

- 확인: 2026-09-05
- 재현 조건: 같은 사전규격에 대해 사람이 등급을 정정해 `effective_grade_changed` hook이 도는
  순간과 첨부 취득 worker가 그 공고의 취득을 종결하는 순간이 겹친다. 둘 다
  `maybe_auto_prepare`를 부른다.
- 증상: 두 경로가 각각 현재 문서 집합을 읽고 "묶음이 없거나 지문이 달라졌다"고 판단하면 같은
  문서 집합으로 묶음 revision이 둘 생길 수 있다. worker끼리는 concurrency 1이라 배제되지만
  hook은 web 프로세스에서 돈다.
- 영향: 좁은 경합이며 데이터가 깨지지는 않는다. 묶음은 append-only이고 revision이 하나 더
  생길 뿐이다. 다만 자동 확정이 두 번 일어나면 감사에 `document_bundle.auto_confirm`이 둘
  남고, 어느 것이 심층 검토의 입력인지는 심층 검토 row가 가리키는 `bundle_id`로만 확정된다.
- 지금 해결할 수 없는 이유: 공고 단위 잠금을 자동 준비 경로에 넣으면 회차 적재 hook이 수천
  건에 대해 잠금을 걸게 되고, 그것이 회차 적재 transaction의 성능 특성을 바꾼다. 어느 쪽이
  나은지는 실측 없이 정할 수 없다.
- 접근 방법: 자동 준비 진입에 공고별 advisory lock을 걸거나, 묶음 생성에 문서 지문 기반
  unique 제약을 더해 둘째 생성을 idempotent replay로 만든다. 둘 다 회차 적재 hot path의
  실측이 먼저다.

## `ollama_unavailable` 실패 사유 문자열이 이름만 남았다

- 확인: 2026-09-05
- 재현 조건: `screening_execution`·`schedule_execution`의 실패 사유와
  `screening-failures.json`을 읽는다.
- 증상: 모델 endpoint를 쓸 수 없을 때의 실패 사유가 여전히 `ollama_unavailable`이다
  (`app/screening/services/scheduled_pipeline.py`, `services/scheduler.py`,
  `routers/screening.py`). 현재 transport는 OpenAI 호환 vLLM이므로 이름이 실제 provider와
  맞지 않는다.
- 영향: 이름만 어긋나고 동작은 정확하다. 문서와 화면은 이 값을 "모델 endpoint를 쓸 수 없음"
  으로 읽는다.
- 지금 해결할 수 없는 이유: 이미 DB row와 회차 artifact에 기록된 **저장된 계약값**이다.
  값을 바꾸면 과거 실행의 실패 사유를 재해석해야 하고, 그 재해석은 회차 불변성 게이트에
  걸린다.
- 접근 방법: 새 코드가 새 값(`model_endpoint_unavailable` 등)을 쓰고 과거 값은 읽기 전용
  별칭으로 남기는 방식으로만 바꾼다. 그 전환은 `docs/contracts.md`의 실패 사유 어휘와 화면
  문구를 함께 바꾸는 별도 작업이다.

## 픽셀 기준선 두 장이 현재 화면과 어긋난 채 남아 있다

- 확인: 2026-09-05
- 재현 조건: `cd web/frontend && npm run test:pixel`을 실행한다.
- 증상: `tests/pixel-screens.spec.ts-snapshots/pre-specs-list-pixel-linux.png`와
  `deep-review-complete-pixel-linux.png`가 현재 화면과 다르다.
  - `pre-specs-list`: 등급과 자동 준비 열 **두 개가 추가**됐다.
  - `deep-review-complete`: 상단 카드가 4 → 5(`품질 표식`)로, 우측 열이 3 → 4구역
    (문서 inventory 추가)으로 늘었다.
- 상태: **해결** (2026-09-07, 아래 기록). 확인 시점(2026-09-05)에는 미갱신이었고 그 작업에서는 **다시 찍지 않았다.** 픽셀 층은 게이트가
  아니므로(`docs/standards.md`의 "화면 검사의 세 층") `npm run test:screens`는 영향받지 않는다.
- 영향: 픽셀 층을 돌리면 두 장이 실패한다. 그 실패는 "화면이 틀렸다"가 아니라 "지난
  기준선과 달라졌다"는 뜻이다. 다만 **그 두 화면에 대해서는 픽셀 층이 회귀를 잡아 주지
  못한다** — 새 실패와 기존 실패를 구분할 수 없기 때문이다.
- 지금 해결할 수 없는 이유: 기준선 교체는 `npm run test:pixel:update`로 이미지를 다시 찍는
  일이고, 그러려면 실행 환경에서 앱을 띄워야 한다. T10은 문서 작업이라 화면을 실행하지
  않았다. 승인자 없이 기준 이미지를 갈아 끼우지 않는다.
- 접근 방법: 화면을 실행할 수 있는 작업에서 `npm run test:pixel:update`로 두 장만 갈아 끼우고
  아래를 이 문서에 기록한다.
  - **사유**: 등급·자동 준비 열 추가(ADR-0049)와 품질 표식 카드·문서 inventory 패널
    추가(ADR-0050·0051)로 화면 구조가 바뀌었다.
  - **영향 화면**: `pre-specs-list`, `deep-review-complete` 두 장. 나머지 여섯 장은 그대로다.
  - **승인자**: 아래 2026-09-07 기록 참조.
- **기준선 교체 기록 (2026-09-07)**
  - 명령: `cd web/frontend && npm run test:pixel:update` → 9 passed, 8장 교체(`bid-delta-changed`,
    `criteria`, `dashboard`, `deep-review-complete`, `opportunities-list`, `order-plan-detail`,
    `order-plans-list`, `pre-specs-list`).
  - 사유: UI/UX 고도화 4웨이브. cascade layer 순서 선언(`styles/layers.css`)으로 Astryx 컴포넌트
    chrome이 전 화면에서 되살아났고, 상단바가 경로 표시로 바뀌었으며, 타이포 4단
    (`styles/typography.css`, 최소 12px)·배지 `danger` 분리·사전규격 목록 리스트 행·대시보드
    할 일 스트립 재구성·용어 한국어화가 들어갔다. 위에 적힌 두 장의 이전 드리프트(등급·자동
    준비 열, 품질 표식 카드·문서 inventory)도 이번 교체에 포함됐다.
  - 영향 화면: 8장 전부. 픽셀 층은 게이트가 아니며 `npm run test:screens` 300 passed /
    `npm run test:contrast` 9 pass를 같은 트리에서 확인했다.
  - 승인자: jechoi (저장소 소유자, 2026-09-07 대화에서 "픽셀 기준선 갱신하고 웨이브 단위로
    커밋해줘"로 명시 지시). 실행: Claude Code 세션.

## runtime image에 쓰이지 않는 `BIDOPS_OLLAMA_BASE_URL` ENV가 남아 있다

- 확인: 2026-09-05
- 상태: **해결** (2026-09-05). `web/Dockerfile`의 `ENV` 줄과 health 주석의 Ollama
  언급을 지우고 `docker compose -f docker-compose.yml build`를 다시 확인했다(exit 0).
  `BIDOPS_VLLM_MODEL`을 읽는 곳이 없어 `docker-compose.mock-reference.yml`의 두 줄도
  함께 지웠다.
- (해결 전 기록) 재현 조건: `web/Dockerfile`의 32행을 본다.
- 증상: image가 `BIDOPS_OLLAMA_BASE_URL=http://127.0.0.1:11434`를 `ENV`로 굽는다. 이 설정은
  `app/core/config.py`에서 제거됐으므로 어떤 코드도 읽지 않는다.
- 영향: 동작에는 영향이 없다(pydantic settings가 모르는 환경변수를 무시한다). 다만 컨테이너
  환경을 읽는 사람에게 **아직 Ollama를 쓴다**는 잘못된 신호를 준다.
- 지금 해결할 수 없는 이유: T10은 문서 작업이며 `web/Dockerfile`의 기능 줄은 이번 범위의
  소유가 아니다. 지우면 image layer가 바뀌므로 build 검증과 함께 해야 한다.
- 접근 방법: 다음 backend 작업에서 그 `ENV` 줄과 100행의 주석 문구를 함께 지우고
  `COMPOSE_OK`와 image build를 다시 확인한다.

## 요구사항 대조 검사가 ID 체계를 가진 실제 문서에서 구조적으로 실패한다

- 확인: 2026-09-05
- 재현 조건: 요구사항 ID 체계를 가진 제안요청서로 심층 검토를 완주시키고 보고서의
  `validation_summary`를 본다. `tests/fixtures/.../fire_prevention_55.json`이 기대하는
  유일 ID는 55개다.
- 증상: stage 1 claim 상한이 8개(`app/core/model_client.py`의 `bounded_output_rule`)라
  모델이 문서의 ID를 다 언급할 수 없다. `deep_review_validation`의 `requirement_inventory`가
  `missing = expected - observed`를 `failed`(중대)로 올리고, `reports.py`가 그것을 보고서
  `validation_status = "failed"`로 승격한다. `system_recommendation`은 `보류`가 된다.
- 영향: 첫 참조 실행부터 ID 체계가 있는 문서의 보고서가 **구조적으로** 실패로 나온다.
  이것은 "문서를 잘못 읽었다"가 아니라 "검사 기대치와 모델 출력 예산이 맞지 않는다"는 뜻이다.
- 지금 해결할 수 없는 이유: 명세 §6.7이 "누락·예상 밖 ID가 있으면 `failed`(중대)"로 정했다.
  claim 상한을 올리면 참조 실행 비용과 프롬프트 경계가 함께 바뀌고, 기대 집합을 좁히면
  명세를 고쳐야 한다. 담당자가 2026-09-05에 이번 차수에는 명세대로 두기로 결정했다.
- 접근 방법: 다음 차수에 셋 중 하나를 명세 개정과 함께 정한다.
  (a) 기대 집합을 stage가 실제로 다룬 구간으로 좁힌다.
  (b) 누락을 경고로 낮추고 누락 목록만 보고서에 싣는다.
  (c) claim 상한을 문서 규모에 맞게 연다.

## mock 종단의 개요 검토가 실제 참조 실행과 응답에서 구분되지 않는다

- 확인: 2026-09-05
- 재현 조건: `python -m app.deep_review.cli run-prespec-e2e`로 mock 종단을 완주시키고
  개요 attempt의 `quality_status`를 본다. `unmeasured_reference`가 나오며, 이는 실제
  승인 사설 vLLM 참조 실행과 같은 값이다.
- 원인: 명세 §6.3이 `reference_only=true`인 attempt의 완료를 금지하고(§7의
  `ck_prespec_overview_attempt_completed_binding`도 같다), §8이 `quality_status`를
  `reference_only` 하나로만 가른다. 그래서 저장소만으로 개요를 완주시키려면 mock을
  provider가 아니라 **transport 계층**에 두어야 하고, 그때 binding은 `reference_only=false`가
  되어 표식이 `unmeasured_reference`로 남는다.
- 영향: 화면·응답만으로는 mock 종단이 만든 개요 결과와 실제 참조 실행 결과를 가릴 수 없다.
  현재는 mock 종단이 테스트·검증 경로에서만 돌고 운영 화면에 그 데이터가 생기지 않아
  실제 혼동은 일어나지 않는다. 심층 검토의 `mock_reference`는 provider에서 나오므로
  이 제약과 무관하다.
- 지금 해결할 수 없는 이유: 세 번째 판별자(attempt에 transport 표식)를 넣으려면 명세 §8이
  허용한 응답·DB 변경 목록 밖의 열과 필드가 필요하다. 담당자가 2026-09-05에 이번 차수에는
  기록만 남기기로 결정했다.
- 접근 방법: 다음 차수에 attempt에 transport 표식을 더하고 `quality_status` 계산을
  `reference_only`와 transport 두 축으로 가른다.
- 종결(2026-09-11): `prespec_overview_attempt`·`reference_only`·`ck_prespec_overview_attempt_completed_binding`이
  참조하던 v4/v5 개요 attempt 테이블을 [ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)로
  삭제했다. 새 `prespec_overview_run`은 `quality_status` 필드 자체를 두지 않으므로(계약은
  [contracts.md](../contracts.md#사전규격-개요-검토-mvp-2026-09-11)) 이 판별 문제가 해당 스택
  폐기로 종결됐다.

## 회사 프로필 원문 일부가 심층 모델 fact 입력에서 빠진다

- 확인: 2026-09-07, 미해결.
- 재현: `docs/reference/company-profile.md`를 `app.core.company_profile.parse_profile`과
  `app.deep_review.services.input_versions._profile_payload_and_facts`로 읽는다.
  43 facts(confirmed 24, inferred 4, unknown 15)와 `profile_section_unstructured`가 나온다.
- 영향: 대표 실적·인증·솔루션 등 일부 서술/표는 원문에 있어도 모델 fact로 들어가지 않는다.
  파일 보유나 import 성공을 정보 충분성으로 해석할 수 없다.
- 이번 범위: 사용자가 요청한 프로필 충분성 점검과 실제 첨부·개요 실행이다.
  원문 보유 사실의 구조화 계약과 미확인 정보의 담당자 확인이 필요하므로
  추정 보완이나 기존 snapshot 변경으로 해결하지 않았다.
- 후속: 근거 위치를 보존한 구조화와 새 버전 import, 원문 대비 fact 포함 범위 검사,
  자격·인력·실적 증빙의 정보 공백 확인.
- 상세: [실행 범위와 프로필 점검](../validation-runs/20260907-prespec-overview-profile-check.md).
- 후속 실행: 기존 43 facts를 모두 보존한 별도 구조화 후보 117 facts를 profile version 2로
  가져왔다. 원문의 명시적 confirmed 항목과 unknown 후보를 구분했고 활성화하지 않았다.
  실제 자격·실적·가용 인력의 정보 공백은 남아 있다.
  [실제 실행 기록](../validation-runs/20260907-prespec-overview-live.md) 참고.

## 개요 제목 인식이 공백·번호·표 구조를 놓치고 목차를 본문으로 선택한다

- 확인: 2026-09-07, 미해결. 실제 64건 중 제목 경계 미확정 29건, 완료 공고 52에서 목차 10블록 입력을 확인했다.
- 재현: `_normalise_heading_text("1. 사업 개요")`는 `사업 개요`를 반환하지만 닫힌 어휘는 `사업개요`다. 마침표 없는 로마숫자는 남고 paragraph 대체 인식은 표 셀과 절 계층을 보존하지 않는다.
- 영향: 본문이 있어도 검토 대기하거나 다른 절·목차가 개요 입력으로 확정된다. locator 검증 통과를 본문 선택·사실 정확성 검증으로 사용할 수 없다.
- 현재 범위와 미해결 이유: 원인 조사 및 파싱 비교 실험이며 운영 파서·불변 snapshot을 수정하지 않았다. 어휘만 늘리는 수정으로는 목차와 계층 오류가 남는다.
- 후속: 동일 원문의 결정적 파서·Qwen·직접 검토를 비교하고 제목 정규화·목차 배제·표 제목·절 계층을 함께 검증한다. 기존 결과는 보존하고 수정 후 새 버전으로 재분석한다.
- 증거: [미완료 52건 분석](../validation-runs/20260907-prespec-failure-analysis.md).
- 추가 재현(2026-09-08): `R26BD00271191`(notice 142)의 완료 attempt
  `992b2824-3573-4c2f-8c8a-29b02f95cc6b`는 감리용역 자체가 아닌 감리대상 사업의
  개요를 발췌했다. 구조 `22541eb7-4e1b-4a0a-9ec4-e0d329dbc774`의 상위 절
  `paragraph-1-71`이 입력에서 빠지고 `paragraph-1-72`부터 `paragraph-1-74` 직전까지만
  선택됐다. 빈 블록 제외 3개로 재구성한 prompt SHA-256은 실행 preflight와 일치했다.
  인용문·요약의 정확 일치 검사를 통과해도 금액·기간이 어느 사업에 속하는지 보장하지
  못한다. 요청 범위는 저장 데이터·생성 경로 조회여서 기존 snapshot·완료 결과는
  보존했다. 후속 검증에는 상위 절 맥락과 발주 대상/감리 대상 구분을 포함해야 한다.

## 개요의 조건부 권고가 확인 기한을 생성하고 위치 검증이 주장 의미를 보장하지 않는다

- 확인: 2026-09-07, 미해결. SW사업대상=Y 10건의 실제 Qwen 개요 테스트에서 재현했다.
- 재현: 개선된 개요 범위의 원문만 제공하고 기존 결과 schema로 Qwen thinking 꺼짐 호출을 한다. 회사 프로필과 승인된 확인 기한은 제공하지 않는다.
- 증상: 10건 모두 조건부 권고와 임의 확인 기한을 생성했고, 7건은 실행일보다 과거였다. 최소 5건에서 실제 존재하는 한 문단의 범위보다 넓은 내용을 claim에 묶었다. 1건에서는 이미 수행한 절차를 앞으로 필요한 절차로 summary에서 바꿨다.
- 원인과 영향: 조건부 권고는 기한을 필수로 요구하지만 입력에는 승인된 기한이 없다. `validate_overview_result`는 schema와 ordinal/block_key를 검사하며 기한의 출처·claim 전체의 의미·summary의 완료 상태까지 검증하지 않는다. 형식·위치 통과를 사실 정확성이나 후속 자동 분석 승인으로 사용할 수 없다.
- 이번 조치: 별도 실험의 최종 결과 10건을 `needs_human_review`로 분류하고 validation 감사에 사유를 남겼다. 운영 리뷰·정책·snapshot에 반영하지 않았으며 원응답을 수정하지 않았다.
- 현재 해결하지 않은 이유: 요청 범위는 10건 실제 테스트다. 확인 기한의 소유권과 조건부 권고 계약, 다중 문단 근거 및 의미 검증을 함께 정해야 하므로 기한을 임의 보정하거나 출력 계약을 조용히 변경하지 않았다.
- 후속: 승인된 확인 기한이 없는 경우의 권고 규칙을 명시하고, claim별 다중 근거·숫자·날짜·완료 상태의 검증과 사람 확인 경계를 보완한다.
- 증거: [Qwen 10건 개요 검토 실험](../validation-runs/20260907-prespec-overview-qwen-10.md).
- 종결(2026-09-11): `추진 검토|조건부 추진 검토|보류|검토 종료` 권고와 `verification_due_at`
  필드 자체가 [ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새
  `prespec_overview_run`의 result에는 권고·확인 기한이 없고 claim별 인용 대조·필수 섹션만
  결정적으로 검사하므로(계약은 [contracts.md](../contracts.md#사전규격-개요-검토-mvp-2026-09-11))
  이 문제는 해당 스택 폐기로 종결됐다.

## 2026-09-03~09-07 실제 참조 실행의 개요 검증 실패

- 확인: 2026-09-07. 실행 근거: [기간별 실제 실행](../validation-runs/20260907-pipeline-20260903-20260907-live.md).
- 재현: 문서 범위가 `ready`인 R26BD00271850·R26BD00271607·R26BD00271523을
  승인 사설 Ollama `qwen3.8:27b`의 고정 digest·개요 정책으로 실행했다.
- 결과: 앞의 2건은 `validation_failed`, 마지막 1건은 `prompt_rejected`로 종료됐다.
  개요 완료 결과가 없어 자동 심층 검토의 필수 조건을 만족하지 않는다.
- 경계: 이번 작업은 기간 수집과 실제 참조 경로 확인이다. 응답 계약을 느슨하게 하거나
  입력을 임의 절단해 완료 상태로 만들지 않는다. 실패 attempt와 원응답을 보존했다.
- 후속: 보존된 응답을 대상으로 값이 아닌 검증 경로·오류 유형만 추출하여 정책/출력 계약
  불일치를 분석하고, 입력 크기·프롬프트 거부 조건을 별도로 재현한다. 정책 변경이 필요하면
  새 버전과 새 참조 실행으로 검증하며 기존 실패나 품질 상태를 소급 변경하지 않는다.

## lifecycle projection의 Protocol 요구 메서드와 구현 불일치

- 2026-09-08 회사 핏 구현의 전체·집중 회귀에서도 같은 2개가 재현됐다. 이번 변경의
  회사 핏/설정/슬롯/경계 74개와 PostgreSQL 집중 44개는 통과했으며, 기존 Protocol 공백은
  별도 수정 대상으로 유지한다([검증 기록](../validation-runs/20260908-prespec-company-fit.md)).
- 확인: 2026-09-07 전체 백엔드 검사에서 1,528 통과·2 실패·5 skip. 실패 2건만
  다시 실행해 동일하게 재현했다.
- 실패: `tests/deep_review/test_prespec_projection.py::test_projection_satisfies_the_lifecycle_protocol`,
  `tests/screening/test_projection.py::test_projection_and_hook_satisfy_the_lifecycle_protocols`.
- 원인: 개요 구현에 `notice_ids_for_auto_preparation_status`, 판정 구현에
  `notice_ids_with_open_blocking_items`·`open_blocking_item_counts`가 없다.
  Protocol, 두 구현, 두 검사 파일은 작업 전 HEAD와 동일하다.
- 영향: runtime Protocol 적합성 검사가 실패하며 관련 필터·blocking 집계 제공 계약을
  완전히 충족한다고 말할 수 없다. 이번 수집·기본 목록 HTTP 검증은 통과했다.
- 범위: 기간 수집과 참조 실행 중 발견한 기존 기능 계약 공백이다. 빈 값을 반환하는
  메서드로 감추지 않고, 각 모듈의 정본 조회·필터 동작을 구현하는 별도 변경에서
  실제 데이터 기반 회귀와 함께 해결한다.

## 실제 C-1 부분 결과의 게시 실패가 남아 있다

- 확인: 2026-09-07. 3건 입력의 실행 `scr-56da935e7aab41a1b976e1b85a295c7b`.
- 재현: 앱 조립으로 적재 hook 2개를 등록하고, 현재 선택 수집 필드와 C-1 실패 파일
  식별 수정이 들어간 별도 실행 컨테이너에서 SW Y 3건을 실제 판정한다.
- 결과: 성공 응답 1건·검증 실패 2건 및 `screening-results.json`이 생성됐지만
  실행은 `execution_failure`, `published_run_id=null`로 종료됐다.
- 확인 범위: hook 누락을 보완해도 재현됐다. 관련 부분 게시 회귀는 통과하지만
  실제 게시의 추가 실패 원인은 확정하지 못했다. 성공 응답을 DB 판정으로 수동 투영하지 않았다.
- 후속: 이 실행의 고정 입력·결과·실패 파일로 모델 호출 없는 게시 재현을 구성하고
  게시 검증/적재 경계의 예외 종류·발생 위치를 비밀 없이 좁혀야 한다. 원본 회차·
  실패 상태·사람 리뷰를 소급 수정하지 않고, 재현 검사와 새 실행으로 해결을 입증한다.
- 영향: 해당 기간 C-1 게시와 이를 전제로 하는 자동 심층/9단계 완료는 확인되지 않았다.

## HWP/HWPX 구조의 page 값은 실제 PDF 페이지가 아니다

- 확인: 2026-09-07, 사전규격 개요 실패 6건의 직접 검토 및 PDF 페이지 참조 실행.
- 재현: `document_mcp/hwpx.py::extract_hwpx`는 `section_names`의 순번을 `page_number`로 넣는다. HWP도 `processor.py`에서 HWPX로 변환한 뒤 같은 추출기를 사용한다. 여러 실제 페이지를 가진 단일 구역 문서가 page=1인 블록들로 저장된다.
- 영향: 이 값을 PDF 실제 쪽수로 표시하면 잘못된 근거 위치를 안내한다. 이번 ID 137의 구조화 개요에서는 예산·기간 문구가 빈 기호로 추출됐지만, 같은 원본의 참조 변환 PDF 4페이지에서는 두 값이 확인됐다. 따라서 입력 범위 수정과 텍스트 추출 품질 검토도 함께 필요하다.
- 현재 조치: 기존 불변 구조·개요 결과는 변경하지 않았다. 별도 참조 실행은 HWP/HWPX 원본 해시, 변환 PDF 해시, 물리적 PDF 페이지(표지 포함 1부터), 선택 페이지 텍스트 해시를 결속한다. 모델 출력에는 각 사실의 PDF 페이지와 인용문을 직접 연결한다. 기존 page를 PDF 페이지로 승격시키지 않는다.
- 남은 작업: 운영 문서 구조 계약에 페이지 기준(실제 PDF/구역 등)과 변환본 버전을 명시하고, 변환 PDF의 저장·검증·조회 및 청크별 페이지 범위를 동일한 불변 입력에 결속해야 한다. PDF 변환 품질과 본문 추출 누락도 검증해야 한다. 기존 구조 전체를 재해석하거나 덮어쓰는 방식으로 해결할 수 없어 이번 참조 실행에서 운영 구조 migration은 하지 않았다.
- 증거: `experiments/prespec-overview-pdf-reference/README.md`, 이번 실행의 비공개 source/PDF/input manifest. 참조 PDF는 고정된 rhwp SVG와 Chromium으로 생성했으며 한컴 렌더링과 동일한 페이지 배치를 보증하지 않는다.

## 입찰 delta 조회가 runtime 테이블 권한 누락으로 실패한다

- 확인: 2026-09-07, 네 검토 화면 UI 반영 뒤 `http://localhost:18787`의 실제 데이터 확인.
- 재현: `GET /api/opportunities/48/bid-delta` (771·1129도 동일)가 HTTP 500, `processing_failed`를 반환한다. 실행 중인 web의 `app` 세션에서 `SET TRANSACTION READ ONLY` 후 `BidDeltaService.workspace(session, 48)`을 호출하면 `InsufficientPrivilege: permission denied for table bid_delta_comparison`이 발생한다(`services/bid_delta.py`, 비교 목록 SELECT). 세션은 rollback했다.
- 원인 범위: `scripts/runtime-privileges.sql`의 명시적 app/worker allowlist에 `bid_delta_*`·`bid_final_decision`이 없다. 따라서 권한 파일 전체를 다시 실행하는 것만으로 해결되지 않는다. 현재 직접 확인한 첫 실패 테이블은 `bid_delta_comparison`이며 나머지 작업 경로의 권한 충족을 검증한 것은 아니다.
- 영향: 최종 Go/No-Go 목록의 사업명·기관은 표시되지만 비교/결정 상태는 조회 실패로 남는다. UI는 이를 미결정·변경 없음·0건으로 바꾸지 않는다. 계산 worker가 아직 없는 문제와는 별개의 조회 장애다.
- 현재 범위에서 해결하지 않은 이유: 이번 변경은 승인 시안의 프론트엔드 구현과 서버 UI 반영이다. 조회 장애는 DB 역할별 테이블·operation 권한 설계, 격리 PostgreSQL 회귀, 운영 권한 적용이 함께 필요한 백엔드 변경이다. UI 반영 과정에서 임의 blanket grant, migration, 실제 결정 쓰기는 수행하지 않았다.
- 후속: 입찰 delta 조회·비교 생성·attempt 재시도·append-only 최종 결정 경로별 app/worker 권한을 검토해 allowlist와 역할 검사를 추가하고, 기존 결정의 UPDATE/DELETE가 거부되는 것을 확인한 뒤 해당 권한을 적용한다. 실제 API의 정상 조회와 권한 경계를 다시 확인한다.
- 화면 및 검증 증거: `/home/jechoi/design-previews/bidops-ui-implementation-20260907/live/verification.json`.

## PDF 개요 연결 검증에서 확인한 범위 밖 회귀 실패 (2026-09-07)

- 재현: backend에서 `pytest tests/deep_review/test_prespec_projection.py::test_projection_satisfies_the_lifecycle_protocol tests/screening/test_projection.py::test_projection_and_hook_satisfy_the_lifecycle_protocols`.
  `OverviewDocumentProjection`과 `JudgmentProjection`의 요구 메서드를 현재 구현체가 모두
  제공하지 않아 runtime protocol 검사가 실패한다. 해당 protocol/구현 파일은 이번 PDF
  개요 저장 변경에서 수정하지 않았다. 별도 생애주기 필터·차단 항목 집계 구현과 함께
  정합성을 맞춰야 하므로 설명형 개요 저장 범위에서 임의의 빈 응답 메서드를 추가하지 않았다.
- frontend에서 `npm run test:screens`: 337 passed / 11 failed / 4 skipped.
  실패는 `common-interactions`, `route-context`, `screen-semantics`의 기존 화면 제목
  (`검토 대기열` 기대 / `공고 판정 이력` 표시), 회차 영역 기대값, 중복 `사람 검토 필요`
  문구 선택자다. 새 `page-overview.spec.ts`와 사전규격 관련 38개 검사는 통과했다.
  현재 화면 명칭·회차 구분의 정본에 맞춰 해당 기존 회귀 기대값을 검토해야 한다.
- 영향: 전체 회귀 게이트를 통과했다고 주장하거나 이 기록만으로 배포 승인 근거로 사용할
  수 없다. 재현 명령과 이번 변경의 상세 검증은
  `docs/validation-runs/20260907-prespec-page-overview-integration.md`에 기록한다.

## [해결됨] 필수 RFP의 rhwp SVG PDF가 표 안의 원문을 보존하지 못한다 (2026-09-08)

- 확인: root 독립 worker 조건 검증에서 실제 RFP HWPX
  `/tmp/bidops-v4-required-sample.h0vd7q/source.hwpx`를 변환했다. 원본은
  `840114` bytes, SHA-256은
  `7cc3b5f3894d984ce641e9462030990cbb4cfc1d6869b18bc9047899a23f4665`이며, 생성 PDF는
  `10113018` bytes, 85 physical pages, object marker `70080`, SHA-256은
  `ca77c04344886ca6e4cf57a3b2deed1955fc469d0e36aa5155c51cd88947b4f6`였다.
- 재현: 생성 PDF p5 `3. 감리대상 사업 > □ 사업개요`의 파란 상자가 시각적으로
  완전히 비어 있다. 원본 HWPX XML과 `renderPageHtml`/`getPageTextLayout`에는
  사업명, 사업비 `13,225,835,150원 VAT포함`, 착수일부터 12개월이 존재한다.
  `renderPageHtml`은 중첩 absolute 좌표 때문에 그대로 인쇄할 수 없고, 같은 vendored
  WASM의 실제 canvas 경로에서는 해당 내용이 표시되는 별도 비교 결과가 있다.
- 영향: 위 수치는 구형 SVG adapter의 historical 결과이며 현재 경로의 성공 근거로
  사용하지 않는다. 원문 XML을 PDF 위에 덧붙이거나 숫자·문장을 추정 보정하지 않았다.
- 해결: `rhwp_render_pages.mjs`를 제거하고 같은 vendored WASM의
  `renderPageToCanvas`와 `getPageTextLayout().runs`를 기존 Chromium print HTML에
  연결했다. 실표본을 같은 non-root/network-none 조건에서 다시 실행해 85 physical
  pages, p4 `298,735,350원`·`365일`·`189MD`, p5
  `13,225,835,150원`·`12개월`, p7~8의 감리 절 구분을 text와 p4/p5 PNG로
  확인했다. Canvas PDF는 SHA-256
  `77fa66fca472a89f2b6a1608602eb6afb0be802068e62998dfec007f539f0010`, 전체
  extracted text SHA-256은
  `e58ab1e90fd216005d283417e11991eab177300e2f0f4ed3afbdd0dc837328ef`다.
- 남은 범위: v2 scratch sidecar는 통과했지만 실표본 PDF의 DB/MinIO immutable
  snapshot과 v4 runner/model/UI 연결은 아직 수행하지 않는다. dependency upgrade,
  OCR/XML 보정, 범용 renderer framework는 추가하지 않았다.

## [해결됨] 준비 PDF의 nonempty font glyph가 정본 text를 가리는 문제 (2026-09-08)

- 재현: 개발 HWP의 Canvas 생성 PDF를 기존 stdlib PDF parser가 `7 blocks/31 chars`
  의 `ଇ`·`ೇ` 같은 glyph로 반환해 nonempty 결과가 되면서 Poppler fallback을
  억제했다. 같은 PDF를 bounded `pdfinfo`/`pdftotext -layout -enc UTF-8`로 읽으면
  `38,581`자의 본문이 확인됐다. 기존 원본 PDF59도 같은 준비 경로에서 `84p/85,515`
  chars를 반환했다.
- 해결: `prepare_pdf=True`의 생성·원본 PDF 모두 stdlib parser를 object/page
  제한 검사용으로만 실행하고, 텍스트 정본은 shared deadline 아래 bounded Poppler로
  읽는다. `prepare_pdf=False` legacy 경로와 `pdf_object_limit`은 그대로 유지하며
  limit 초과를 fallback 성공으로 바꾸지 않는다.
- 검증: `tests/deep_review/test_document_mcp.py`의 nonempty-glyph 회귀와 개발/운영
  실제 구조 검사가 통과했다. 이 수정은 OCR·언어 휴리스틱·원문 XML 덧붙이기를
  추가하지 않는다.

## v4 PDF snapshot/input bounded 단계 상태 (2026-09-08)

`prespec_v4_pdf_snapshot`와 `prespec_v4_target`의 최소 계약, full page-text/versioned
object binding, worker provenance/options 결속, source namespace generated PDF 저장,
변환 전 snapshot 재사용, canonical explicit-sample identity, heading substring
selector를 isolated storage에서 검증했다. `PrespecV4Attempt` 선행 스키마는 실제
runner 소비자가 없어 보류했다. 운영 DB/MinIO 쓰기·migration 적용·model/UI 인수는
남아 있으며, 기존 `DocumentStructure`·legacy 개요/리뷰는 덮어쓰지 않았다.

## [해결됨] v4 snapshot cache가 최신 scan/object identity를 확인하지 않던 경계 (2026-09-08)

- 원인: 초기 cache hit 경로가 verified location만 확인하고 object version·etag·실제
  bytes/page-text JSON·최신 ClamAV scan 행을 다시 읽지 않았다. 과거 clean 뒤에
  `infected`/`unavailable` 행이 생겨도 재사용할 수 있는 구조였다.
- 해결: cache hit에서 source/PDF/page-text를 기존 ObjectStore의 정확한 version으로
  bounded read하고 content object의 size/hash/mime, location etag, page metadata를
  다시 대조한다. 최신 `ContentScan` 하나의 status가 `clean`일 때만 재사용하며 과거
  clean으로 후퇴하지 않는다. generated PDF는 worker metadata의 실제 runtime·Chromium·
  font fingerprint와 준비 caller 기대값이 일치할 때만 저장한다.
- 검증: `test_prespec_v4_preparation.py` 5 passed, 임시 PostgreSQL 17에서
  `test_prespec_v4_postgres.py` 1 passed 및 migration 제약 focused 5 passed.

운영 DB/MinIO에 0021을 적용하거나 실제 snapshot을 생성한 것은 아니다.

## [해결됨] v4 provenance가 자산 hash를 이미지 digest로 오인하던 경계 (2026-09-08)

- 원인: worker image digest 선언이 없을 때 runtime/Chromium/font 자산을 합친 hash를
  `worker_image_digest`로 기록했고, `fc-list`의 이름·경로 출력만 hash해 같은 경로의
  font bytes 교체를 잡지 못했다. Chromium launcher script도 실제 print binary처럼
  기록할 수 있었다.
- 해결: 선언된 image digest만 선택적으로 기록하고 미선언은 `null`로 남긴다. runtime
  fingerprint에는 vendored Canvas adapter와 processor/CSS 및 실제 Chromium ELF hash를
  포함하고, 정렬한 설치 font 파일의 size·bytes hash로 manifest를 만든다. 원본 PDF v2
  sidecar는 재렌더하지 않음, 실제 processor hash와 Poppler `pdfinfo`/`pdftotext`
  binary hash, `font_provenance=null`을 검증한다.
- 검증: document-mcp provenance/font-byte 회귀, worker protocol 14개, v4 preparation
  5개와 runtime contract를 포함한 focused 73개가 통과했다. 실제 PDF59 sidecar는
  84 physical pages로 통과했고, 격리 source-PDF snapshot 재사용에서 converter 1회와
  동일 snapshot을 확인했다.

운영 DB/MinIO migration·snapshot row와 runner/model/UI 연결은 여전히 수행하지 않았다.

## [원인 확인] notice 142 표준 PDF 준비가 300초 deadline에서 종료됨 (2026-09-09)

- 재현: `R26BD00271191` 필수 HWPX를 명시 표본 표준 prepare로 실행했다. 첫 시도는
  `conversion_required`, 두 번째 시도는 `pdf_preparation_failed`였고, 마지막 2GiB
  worker 시도도 job `9a8ded11-f357-4847-a534-65be6a0810f8`, attempt
  `954abd8b-e161-457a-9236-464fb47604ba`, `300048ms` timeout으로 실패했다.
- 영향: notice 142에는 성공 PDF, immutable snapshot, current result를 저장하지
  않았으며 실제 PDF/UI 인수는 미검증이다. 이미 완료된 35 개발 HWP와 59 운영 PDF
  current 결과에는 영향을 주지 않는다.
- 조치: 원인으로 입증되지 않은 Chromium `RLIMIT_FSIZE=256MiB` 임시 변경은
  원복했다. 2GiB 조건에서도 timeout이 발생했으므로 fsize를 해결책으로 확정하지
  않는다. 추가 변환 진단·대체 테스트·모델 호출은 수행하지 않았다.
- 후속: worker 원래 runtime 조건으로 복원하고, 별도 승인된 환경 원인 조사 후에만
  재시도한다. 실패 attempt는 보존하며 자동 성공·기존 snapshot 재사용으로 우회하지
  않는다.

- 원인 확인(2026-09-09): 운영 worker image `bidops-v4-luna-reference:20260909-final`에서 같은
  source bytes로 격리 재실행해 두 한계를 분리했다. (1) compose `pids_limit: 128`이 Chromium 렌더
  thread를 굶겨(`pthread_create: Resource temporarily unavailable (11)`, pids 123/128, 렌더러 CPU
  1~5% 유휴) deadline까지 진행하지 못했다. (2) v4 CLI 기본 출력 예산 20 MiB(Chromium
  `RLIMIT_FSIZE`는 그 4배인 80 MiB)가 85쪽 렌더에 부족해 PDF 없이 `conversion_required`로 끝났다.
  memory 2 GiB와 `RLIMIT_FSIZE=256 MiB` 가설은 원인이 아니다.

  | pids_limit | max_output_bytes | 결과 |
  |---|---|---|
  | 128 (당시 compose) | 100 MiB | 300초 timeout, Chromium `pthread_create` 실패 |
  | 128 | 20 MiB (당시 CLI 기본값) | 21초 `conversion_required` (PDF 미생성) |
  | 512 | 20 MiB | 18초 `conversion_required` |
  | 512 | 32 / 48 / 100 MiB | 성공 16.8~20.8초, 85쪽, 11,041,060 bytes |

  ```bash
  docker run --network none --user 1000:1000 --memory 1g --cap-drop=ALL \
    --security-opt no-new-privileges --pids-limit <128|512> \
    bidops-v4-luna-reference:20260909-final python -c \
    'DocumentProcessor(clamav_checker=lambda _: True).process(bytes, "application/hwp+zip", opts)'
  ```
- 조치(2026-09-09): compose document-worker `pids_limit`을 512로, v4 CLI 기본 `max_output_bytes`를
  64 MiB(`ProcessorOptions` 상한 100 MiB 이내)로 올렸다. **운영 재실행은 하지 않았다** — 컨테이너
  재생성과 notice 142 새 attempt는 별도 운영 단계이며 그 전까지 142는 `unverified`로 남는다.
- 운영 재실행(2026-09-10): `212e5ed`가 main에 들어온 뒤 document-worker 두 개를 base compose와 image 고정
  overlay(`bidops-v4-luna-reference:20260909-final`)로 재생성해 `PidsLimit=512`·memory 1 GiB·`network_mode none`·
  `cap_drop ALL`·동일 image·`/scratch` volume을 확인했다. overview endpoint `192.168.0.139:58765`가 닿지 않아
  `--activate`는 `model_binding_unavailable`로 실패했고, 2026-09-08 감사의 Luna reference-only
  binding(`692b50e4…`, `gpt-5.6-luna`, `reference_only=true`, `deployable=false`)을 `--binding`으로 재구성해
  `explicit_sample`로 활성화했다. 첫 `--prepare`는 43초 뒤 attempt `dbbc7b5f-35c5-4f21-8adb-1c2b042dd61e`(sequence 5)
  `pdf_preparation_failed`였고 3분 뒤 같은 입력의 직접 재현이 22.8초에 성공했으므로 원인은 **미확정**이다. 두 번째 실행은
  23.1초에 snapshot `e68670e0-4bf7-4cd9-baa1-174f19e5e994`(85쪽, 11,041,060 bytes, PDF SHA-256 `2774fd76…`,
  `verified`·ClamAV `clean`)와 target `200e9557-d5d5-4a0f-afa8-896d44b41261`(`ready`, `heading_scope`, 3~13쪽)을
  남겼다. attempt는 enqueue하지 않았고 activation은 즉시 OFF로 되돌렸다(감사 `31bee035-6263-4444-bafe-439b0f16c12a`).
  첫 시도 중 append된 감사 `176c61bb-2538-459c-a1f3-ec208debed57`의 사유
  `notice_142_prepare_done_activation_restored_off`는 그 시점에 준비된 것이 없어 사실과 다르지만, 감사 행은
  append-only이므로 고치지 않고 부정확함만 기록한다. 새 target에 attempt가 없어 `current`는 여전히 실패 attempt
  `dbbc7b5f…`를 보여 주고 142의 UI/PDF 링크 인수는 Qwen endpoint 복구까지 미완이다.
- R6 운영 인수(2026-09-10): native 이미지 `bidops-rdp-r6:20260910`과 0023 migration 뒤 같은 source bytes로 native snapshot
  `f8a42b74-8710-4cc8-90f0-9ca8ae4ed3f1`(`rhwp-svg-pdf` 0.8.6, 79쪽, PDF SHA-256 `aee7e648…` 4,829,134 bytes, 기존 구조
  `22541eb7…` 결속, 대응표 `38958774…`)과 target `f7c73503-8f70-47d4-a309-c9fbd9cfd122`(`ready`, 4~12쪽)를 31초에 준비했다.
  Canvas snapshot `e68670e0…`·target `200e9557…`은 보존됐고 attempt는 없다. `GET /api/document-structures/22541eb7…/pdf`가
  이 PDF를 돌려주고 segments 77건이 `mapped` 35·`partial` 42다. `current`는 여전히 `dbbc7b5f…`이며 아래 projection 항목은 열려 있다
  ([R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md)).
- 사실 정정(2026-09-11): 위 "조치(2026-09-09)"가 기록한 `pids_limit: 512`는 R6 이후 이미지
  재생성(`bidops-rdp-r6:20260910` 이후)에서 `fc-list` 추가와 함께 **128로 되돌아갔다** — R6·R7·
  현재 운영 document-worker는 모두 `PidsLimit=128`이다(R6/R7 기록, 2026-09-10). 512로 올린
  기록은 2026-09-09~10 사이의 중간 상태일 뿐 현재 사실이 아니므로, 운영 pids 값을 확인할
  때는 이 항목이 아니라 `docker inspect <container> --format '{{.HostConfig.PidsLimit}}'`
  실측을 정본으로 한다.

## pdf_preparation_failed가 변환기의 실제 오류 코드를 감춘다 (2026-09-10)

- 재현: `prespec-v4 --prepare`로 변환을 실패시키면 `prepare_v4_pdf_snapshot`이 converter 예외를 종류와 무관하게
  `pdf_preparation_failed` 하나로 감싼다(`web/backend/app/deep_review/services/prespec_v4.py:855`).
- 영향: 2026-09-10 notice 142의 43초 실패 attempt `dbbc7b5f-35c5-4f21-8adb-1c2b042dd61e`에는 그 일반 코드만 남아
  deadline·출력 예산·렌더 실패를 구분할 수 없었고, 3분 뒤 같은 입력의 직접 재현이 성공해 원인은 미확정으로 남았다.
- 해결 구현(R3, 운영 미적용): converter의 허용된 안전 코드를
  `pdf_preparation_failed:<code>`와 감사 `safe_metadata.converter_code`에 함께 보존한다.
  미등록 예외는 일반 코드로 남기며 경로·원문·프롬프트·stderr는 넣지 않는다.
  [R3 검증](../validation-runs/2026-09-10-rhwp-r3-snapshot.md)을 참고한다.
  과거 실패 attempt는 그대로 보존하고 당시 원인도 미확정으로 유지한다.
- `current` projection은 attempt가 없는 `ready` target을 드러내지 않는다. 142의 새 target
  `200e9557-d5d5-4a0f-afa8-896d44b41261`이 `ready`여도 `GET /api/pre-specs/142/overview-pages`의 `current`는 직전
  실패 attempt를 계속 보여 준다.


## 같은 문서 버전의 native 구조가 기존 구조와 다르면 준비를 거부한다 (2026-09-10)

- 재현 조건: `document_structure`가 이미 있는 문서 버전을 다른 native renderer
  identity로 준비하면서 새 구조의 pages 또는 blocks가 기존 payload와 다르다.
  R3의 합성 충돌 테스트로 확인했으며 운영 표본에서 발생했다고 단정하지 않는다.
- 영향: `structure_binding_mismatch`로 준비를 실패시키고 기존 구조·리뷰를 보존한다.
  원본이 같다는 이유만으로 서로 다른 블록에 기존 structure ID를 붙이지 않는다.
- 현재 범위에서 구조를 추가할 수 없는 이유: `document_structure.document_version_id`
  UNIQUE와 기존 소비자의 단일 구조 조회 계약이 있다. R3에서 이 계약을 없애거나
  재렌더링만으로 업무 문서 버전을 새로 만들지 않는다.
- 후속: 운영 인수 전에 기존 구조와 비교한다. 충돌이 있는 문서를 지원하려면
  구조 revision과 리뷰의 명시적 구조 참조를 함께 설계·승인한 뒤 이관한다.
- 운영 확인(2026-09-10 R6): 세 표본의 기존 구조 payload와 R6 이미지 native 출력을 대조했다. 142(`hwpx-stdlib`, 1쪽·2,561 blocks)와
  59(`pdf-poppler-fallback`, 84·84)는 pages·blocks가 동일해 준비가 기존 구조에 결속됐다. **35는 다르다** — 기존 `hwp-rhwp-hwpx`
  구조(WASM rhwp export, 1,349 blocks)와 native rhwp 0.8.6 export 구조(1,454 blocks)가 64개 구간에서 갈린다. 실행하면
  `structure_binding_mismatch` 실패 attempt가 append돼 35의 `current`(completed Luna reference)를 덮으므로 R6에서 35는 준비하지
  않았다. 35의 native snapshot은 구조 revision 설계·승인 뒤에만 만든다.

## 전체 backend·화면 스위트의 기존 실패 4건이 rhwp 단계와 무관하게 남아 있다 (2026-09-10)

- 재현 조건: main `753d639`(R5 병합)에서 `pytest tests/`와 `npm run test:screens`를 각 1회 실행한다.
  같은 4건은 `a9ddb99`(R3 직후, P1·R4·R5 이전)와 `bbbbaae`(R4 이전)에서도 같은 방식으로 재현된다.
- 증상: backend `tests/app/test_alembic_autogenerate.py::test_alembic_check_has_no_default_schema_bidops_mirror_drift`가
  `alembic check`에서 `prespec_v4_attempt`·`prespec_v4_pdf_snapshot`·`prespec_v4_target`의 FK·check·index 차이를
  "New upgrade operations detected"로 보고한다. `tests/app/test_deep_review_migrations.py::test_model_has_exact_closed_table_set`과
  `tests/app/test_mapper_isolation.py::test_the_four_modules_together_declare_the_whole_schema`는 모델 테이블 수 82 ≠ 기대 81로 실패한다.
  화면 `tests/common-interactions.spec.ts:211`(UC-02 상태 문구)은 `.pre-spec-overview-statuses`에 "사람 검토 필요" 문구가 없어 실패한다.
- 영향: 0023까지의 migration과 모델 metadata가 autogenerate 기준으로 어긋나 있고, 닫힌 테이블 목록 테스트가 새 테이블 하나를
  승인하지 않은 상태다. 운영 DB에 적용된 migration이 잘못됐다는 뜻은 아니며 R3 PostgreSQL smoke·roundtrip은 통과했다.
- 현재 범위에서 해결할 수 없는 이유: rhwp 단계(P1·R4·R5)는 이 테스트가 검사하는 모델·migration·화면을 바꾸지 않았고,
  R5 게이트는 "기존 실패 목록과 같거나 줄어듦"이다. 원인 확정에는 0021~0023 autogenerate 차이 검토와 82번째 테이블의 승인 여부 결정이 필요하다.
- 후속: R6 운영 인수 전에 autogenerate 차이를 0024 migration 또는 모델 보정으로 닫고 닫힌 테이블 목록을 갱신한다.
  화면 1건은 사전규격 개요 상태 fixture와 문구 계약을 대조해 별도 작업으로 닫는다.
- 2026-09-10 R6는 이 4건을 닫지 않은 채 진행했다. 운영에 적용한 0023은 R3의 PostgreSQL 17 smoke·roundtrip과 R6 적용 후
  열·권한·행 수 확인으로 검증했으며, autogenerate 대조 실패는 여전히 열린 테스트 결함이다.

## R5 런타임 이미지에 `fc-list`가 없어 native 변환이 전부 실패했다 (2026-09-10, 해결)

- 재현: `bidops-rdp-r5:20260910`(R5 게이트를 통과한 이미지)에서 notice 142 HWPX를 격리 조건(pids 128·1 GiB·network none)으로
  `DocumentProcessor`에 넣으면 rhwp 네 호출이 끝난 뒤 26.8초에 `converter_unavailable`("PDF 글꼴 manifest를 확인할 수 없습니다")로
  끝난다. `_font_manifest_sha256`이 `shutil.which("fc-list")`를 요구하는데 이미지에 `fontconfig` 패키지가 없다.
- 원인: R0~R3 이미지의 `fontconfig`는 Chromium(`libpango`)의 의존성으로만 설치돼 있었고, R5가 Chromium을 제거하면서 함께
  사라졌다. R5 게이트("chromium·node 없음, runtime contract")는 폰트 manifest 실행 경로를 검사하지 않았다.
- 영향: 그대로 배포했다면 HWP·HWPX 준비가 모두 실패하고 notice 범위 실패 attempt가 `current`를 덮었을 것이다. 운영 배포 전
  R6 격리 실측에서 발견해 운영 영향은 없다.
- 조치: `web/Dockerfile` apt 목록에 `fontconfig`를 명시하고 `tests/app/test_runtime_contract.py`의 단언을
  `fontconfig fonts-nanum fonts-noto-cjk`로 고쳤다. `bidops-rdp-r6:20260910`에서 `fc-list`와 폰트 manifest
  `92e5dc4f…1650a9`(R3 이미지와 동일)를 확인했다([R6 기록](../validation-runs/2026-09-10-rhwp-pipeline.md)).
- 남은 것: 이미지 안에서 실제 변환기 실행을 검사하는 게이트가 없다. 다음 이미지 변경부터는 R6 기록의 probe 명령으로 표본 1건을
  실제 실행해 확인한다.

## 개요 범위 보조 호출에 temperature 0을 줄 수 없다 (2026-09-10)

- 재현: `app/core/model_client.py`의 `complete_structured`는 승인 generation 상수 `APPROVED_GENERATION["temperature"]=0.7`을 고정 전송하고 per-call 인자가 없다. R7 `--assist-range`는 결정적 제안을 위해 temperature 0을 계약했지만 넣을 자리가 없어 재시도 0·seed 0·strict json_schema로 대신했다.
- 영향: 같은 후보 목록에 대한 모델 제안이 호출마다 달라질 수 있다. 제안은 사람이 확인하는 참조일 뿐 target을 바꾸지 않으므로 업무 영향은 없다.
- 현재 범위에서 해결할 수 없는 이유: 승인 generation 값은 용도별 품질 게이트와 묶여 있어 R7 범위에서 core 계약을 바꾸지 않았다.
- 후속: `complete_structured`에 용도별 per-call generation override(허용 목록 안에서만)를 두거나 range-assist 용도의 승인 generation을 별도로 선언한다.
- 종결(2026-09-11): `--assist-range` CLI와 그 대상인 `prespec_v4_target`은
  [ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새 계약에는 모델
  보조 range 제안 CLI가 없으므로 이 문제는 해당 스택 폐기로 종결됐다.

## 확정 대기 target에 검토 manifest 참조가 결속되지 않는다 (2026-09-10)

- 재현: R7의 `prepare_v4_notice`가 선택기 미결정 시 `bidops.prespec-v4-range-review.v1` manifest를 객체·content row로 저장하지만, `freeze_v4_target`이 ready가 아닌 selection에 manifest 참조를 주면 `manifest_reference_invalid`로 막아 `needs_human_review` target의 `manifest_content_object_id`는 `null`이다.
- 영향: 검토 manifest는 존재하고 후보 개수·digest를 담지만 target 행에서 FK로 따라갈 수 없다. `range_review` 투영은 후보를 snapshot의 산출물 ⑦에서 읽으므로 화면 기능에는 영향이 없다.
- 후속: `freeze_v4_target`에 non-ready selection의 review manifest 참조를 허용하는 분기와 그 검증을 추가한다.
- 종결(2026-09-11): `prespec_v4_target`과 `freeze_v4_target`은
  [ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새
  `prespec_overview_run`은 target 테이블을 거치지 않고 자기 행에 직접
  `range_source`·`page_start`·`page_end`·`range_reason_codes`를 두므로 이 문제는 해당 스택
  폐기로 종결됐다.

## 실표본에서 사람 확정 흐름을 재현할 문서가 없다 (2026-09-10)

- 상황: 35/59/142 모두 heading 선택기가 `ready`라 `needs_human_review` target이 만들어지지 않는다. R7의 확정 REST·화면·CLI 보조는 API 종단 테스트(`test_page_overview`·`test_prespec_v4_ops`)와 Playwright 목 검사로만 확인했다.
- 후속: 다음 수집 회차에서 heading 선택기가 미결정인 사전규격이 나오면 `docs/validation-runs/2026-09-10-rhwp-r7-range-review.md`의 절차로 운영 확인하고 결과를 이 항목에 덧붙인다.
- 종결(2026-09-11): 확정 REST는 `POST /api/pre-specs/{notice_id}/overview/range-confirmations`로,
  대상 테이블은 `prespec_overview_run`으로 바뀌었다([ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)).
  옛 target 기반 확정 흐름과 그 테스트(`test_prespec_v4_ops`)는 함께 삭제됐으므로 이 항목은
  해당 스택 폐기로 종결하고, 실표본 사람 확정 재현은 새 endpoint 기준으로 별도 후속을
  연다.

## 개요 숫자 검증이 기간을 사업예산 근거로 허용한다 (2026-09-10, 새 v5 실행 해결)

- 재현: `page_overview_validation.validate_page_overview_detailed`에 유효한 page-review v3 payload를 넣는다. 근거 페이지는 `사업을 진행한다. 시스템을 구축한다. 계약기간은 6개월이다. 예산은 미정이다.`, `budget_and_period`의 사실은 `사업예산은 6억원이다.`와 `evidence_pages=[1]`이다. 격리 합성 입력에서 결과는 `errors=[]`, `warnings=[]`였다.
- 원인·영향: 숫자를 정수 문자열 집합으로 비교하므로 `6개월`과 `6억원`을 구분하지 않는다. 사업예산·기간·단위·수치의 관계가 틀려도 v4 runner가 완료 결과로 저장하고 화면이 근거 검사 통과로 표시할 수 있다. 실제 Qwen 응답에서 이 오류가 발생했다는 관측은 아니다.
- 해결: 새 v5 실행은 주장별 정확 인용과 Decimal 수치·단위·주체·역할·VAT·기산점을 검사하고 별도 Qwen 의미 검토를 요구한다. 하나라도 미검증이면 전체 `needs_human_review`, 결과 없음이다. 검증된 문장만 결정적으로 구성한다. 과거 v3 parser·원응답·결과를 보존하며 새 검증 통과로 승격하지 않는다.
- 검증: 새 순수 검증기의 고유 95개 사례와 runner 사실 실패·의미 불확실·최종 구성/소비자 재검사에서 기간→예산, 단위/주체/VAT 교환과 근거 위조를 차단했다(Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)). 의미 응답은 fake이며 실제 Qwen 품질 검증·운영 배포는 아직 아니다.

## 사전규격 수집기를 같은 회차에 재실행하면 원문을 덮어쓴다 (2026-09-10, 해결)

- 재현: 임시 `raw/prespec-page-001.json`에 기존 내용을 만든 뒤 `collect_notices.collect_source`를 같은 경로로 호출한다. HTTP 함수는 빈 정상 응답을 반환하는 fake로 교체한다. 외부 호출 없이 기존 파일이 새 응답으로 교체됨을 확인했다.
- 원인·영향: `collect_notices.py`는 raw 페이지와 `collected-notices.json`을 모두 `write_text`로 쓰며 기존 회차를 거부하지 않는다. 운영 문서의 날짜 기반 회차 ID를 같은 날 재사용하면 과거 원문·정규화 산출물의 불변성이 깨진다. 발주계획 전용 수집기의 배타적 파일 생성과 다르다.
- 해결: collector의 회차/파일 배타 생성과 `--from-raw SOURCE_RAW`→별도 새 출력 계약, lifecycle·예약 호출부를 함께 수정했다. 기존 빈 폴더·symlink·경로 이탈은 키 확인 전에 거부한다.
- 검증: collector 최초 35건, 발주계획 정규화 회귀 8건, 교차 pipeline 2건, 직접 backend 호출부 22건 통과. 실제 두 프로세스 경쟁의 패자 키·HTTP 호출은 0회였고 기존 raw hash·부분 실패 보존을 확인했다. 이후 최종 JSON 저장 실패가 완료 provenance를 남기는 경계도 수정해 신규 사례 포함 관련 3건 통과(collector 고유 36건). 실행 명령은 작업 Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)에 기록한다. 운영 수집·기존 회차 변경은 하지 않았다.

## 최초 모델 확인 실패가 개요 worker 수명 동안 캐시된다 (2026-09-10, 해결)

- 재현: `PrespecV4OverviewRunner`에 첫 `verify_identity`만 실패하고 이후 정상인 fake client를 주고 `_resolve()`를 두 번 호출한다. 두 결과 모두 `(None, None)`이고 실제 identity 호출은 1회다. fake client를 직접 다시 확인하면 정상 identity를 반환한다.
- 원인·영향: 실패도 `_resolved=(None, None)`으로 저장하고 이후 즉시 반환한다. 합성 worker가 runner를 loop 밖에서 한 번 만들기 때문에 사설 vLLM이 복구되어도 큐가 `awaiting_model`에 머문다. 기존 `PreSpecOverviewRunner`도 같은 실패 캐시 패턴이다.
- 해결: 두 runner의 성공 binding cache와 일시 실패를 분리했다. purpose/endpoint 설정/model/revision/policy 결속과 10→30→60→120→300초 backoff, 고정 오류 차단, 내부 client 정리, 실행 중 identity 오류 무효화를 적용했다.
- 검증: 두 runner와 core의 fake clock 사례에서 최초 실패 후 복구, 대기 중 문서 호출 0, 고정 불일치 유지와 설정 변경을 확인했다. Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)의 관련 core 57건/기존 개요·Luna·analysis 69건/v4 27건 범위에 포함되며 운영 장애를 유발하지 않았다.

## 비활성 v4 대기 작업이 다른 문서의 기존 개요 처리도 막는다 (2026-09-10, 해결)

- 재현: 격리 SQLite·filesystem fixture에서 v4 target을 활성화·enqueue한 뒤 비활성화한다. 처리 가능한 legacy runner를 주입하고 합성 개요 `run_once`를 부르면 `status=disabled`, `claimed=false`, legacy 호출 0회다.
- 원인·영향: `prespec_v4_runner.py`는 queued/running v4 attempt가 하나라도 있고 activation이 OFF이면 legacy 분기와 lease 만료 처리 전에 반환한다. 해당 v4 문서를 제외한 기존 개요까지 진행되지 않으며 만료된 v4 running 상태도 이 경로에서는 닫히지 않는다.
- 해결: OFF와 무관하게 lease를 정리하고, 처리 가능한 v4가 없으면 예약 문서를 제외한 legacy를 배정한다. OFF는 대기·실행 attempt와 연결 job을 같은 gate에서 취소하며 이전 activation의 늦은 응답은 call 이력만 남긴다.
- 검증: fake worker/clock의 OFF·배정·만료·다른 소유자 사례와 임시 PostgreSQL 17의 두 세션 gate 경쟁 4건에서 중지 이후 claim/게시 차단, 초안·의미 응답 뒤 OFF→ON fence, 게시가 먼저인 완료 보존을 확인했다(Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)). 운영 큐는 변경하지 않았다.

## ro_backup의 sequence SELECT 누락으로 운영 DB 백업이 실패한다 (2026-09-10, 해결)

- 재현: 현재 0024 운영 DB에 기존 `scripts/backup-postgres.sh`를 ro_backup 계정으로 실행하면 `permission denied for sequence agency_portal_id_seq`로 exit 1이다. 새 백업 `backups/prespec-precall-20260910-HGYzGB/postgres/full/bidops-20260910T103149Z.dump`는 0 B로 남아 복구에 사용할 수 없다. 읽기 전용 catalog 조회에서 bidops sequence 22개 모두 해당 역할의 SELECT가 없음을 확인했다.
- 원인·영향: `scripts/runtime-privileges.sql`은 ro_backup의 모든 sequence 권한을 회수하지만 마지막에는 현재/미래 table SELECT만 복구한다. pg_dump가 sequence의 last_value/is_called를 읽지 못해 검증 가능한 DB 백업과 새 0025 운영 적용을 막는다. 이번 claim ledger 변경 전부터의 정책이며 객체 백업 966 version은 별도로 정상 완료했다.
- 해결: 사용자 운영 승인 뒤 runtime 정책에 현재/미래 sequence SELECT만 추가했다. 임시 PostgreSQL에서 현재/새 sequence 읽기·nextval/setval 거부와 app/worker 미래 권한 미상속, 정적 정책 검사 2건이 통과했다. 운영에서는 소유자 migrate로 22개 SELECT만 복구하고 ro_backup 계정으로 새 dump를 생성했다(22,530,409 B, SHA `f04fb97c528312bfe32df64b9273b17901d3793d4af597f9088e5596ff0a67d1`, pg_dump·pg_restore 목록 읽기 exit 0).
- 보존: 이전 0 B 실패 파일과 객체 백업은 남겼다. 새 백업 manifest는 `backups/prespec-deploy-20260910-cqJZ3W/manifest.json`이며 기존 객체 백업이 현재 DB의 active 참조 596개를 모두 포함한다. 실제 restore·외부 보존 복사·WAL 검증은 미실행이다.

## 0910 신규 RFP 절 후보 검사 실패 (2026-09-11 운영 core 재준비6건 해결)

- 재현: 승인된 신규 notice743·745·746·747·754·755의 안전한 RFP를 기존 `bidops-rdp-r7:20260910` worker, prepare_pdf=true/300초/64MiB 조건으로 각1회 준비하면 `pdf_preparation_failed:section_candidates_invalid`로 terminal 실패한다. 같은 실행의 다른9건은 snapshot을 만들었다.
- 영향: 위6건은 개요 입력을 동결하지 못해 Qwen 호출 대상에서 제외된다. 원본15개 전체의 version/hash/size 재조회는 일치했으며 이 실패를 원문 변조나 악성코드 검출로 단정하지 않는다.
- 원인: 사이드 리뷰의 pinned rhwp digest 재현은 6건 모두 exit0였다. 743·745·754·755는 정상 outline(전체/반환 5/5·5/5·28/28·1/1), 746·747은 67/50·111/50 부분 반환인데 BidOps가 mode와 전체=반환을 잘못 강제했다. 이는 전체 PDF 재변환 성공 근거는 아니다.
- 수정/검증: outline·총/반환 수를 구분한 후보 v2, digest의 advisory 실패와 검증된 core 분리, 부분 후보의 수동 쪽 선택을 구현했다. native parser/processor·sidecar 소비·범위 연결 격리 검사가 통과했다(Plan(0910 안정화 Plan, 폐기됨 — git 이력 `71b9954`)).
- 운영 확인: 후속 승인으로 수정 web/document-worker2를 반영하고 위6건만 각1회 준비해 모두 core PDF/page-text를 얻었다. 원본·기존 실패·결과·리뷰는 동일하고 새 snapshot/target각6을 추가했다. 743·745는 범위 시작 미확정,746·747은 부분 후보라 수동 확인이다. 754·755는 제안 작성 양식 오선택을 발견해 아래 후속으로 분리했다. Qwen은0, source-only 준비 뒤 OFF다. [새 실행 증거](../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/README.md), [이전 실패 보존](../../.dryforge/prespec-0910-preparation-3vfrYK/pdf-execution.json).

## 준비된 선택 manifest의 공백 페이지 거부 (2026-09-11 코드·고정 입력 검증·배포 완료)

- 재현: 신규744 target `4445f2a6-bb87-4807-9245-4fbb87c327dc`와759 target `86441326-d178-4055-aee4-503a76168528`은 range ready이지만 `_load_manifest`에서 `manifest_invalid`다. 선택 범위 마지막744/9쪽은8자,759/8쪽은9자의 공백뿐이며 해당 검사 `not text_value.strip()`를 위반한다. manifest SHA/byte count와 각 page text SHA는 모두 일치한다.
- 영향: 입력 용량이나 사실 검증과 무관한 준비 계약 불일치다. 모델HTTP0에서 발견했으며 기존 준비 실패 함수로 `failed/manifest_invalid`를 기록해 빈 성공 상태로 보이지 않게 했다. 원문·PDF·target·manifest는 그대로 보존했다.
- 수정/검증: 일부 공백은 번호/text/hash 그대로 허용하고 전체 공백은 거부한다. 공백 인용을 근거로 통과시키지 않는 직접 검사4건과 운영 고정 입력의 읽기 전용 hash/PDF 재확인, 두 단계 offline preview가 통과했다. 744(3,549자)·759(2,171자)는 입력 준비 가능이며 실제 Qwen/내용 검증 성공은0이다. 수정본 배포는 완료했고 이전 failed 행과 고정 원문은 보존했다. 모델 전송은 하지 않았다. [MVP 준비 기록](../../.dryforge/prespec-0910-preparation-3vfrYK/README.md).

## 0910의 수동 범위·대체 문서·안전 오류 후속 (2026-09-11, 미완료)

- 실패6건의 core 재준비 뒤754·755의 자동 ready가 각각49쪽124자/30쪽145자의 `제안개요` 작성 양식을 선택한 것을 확인했다. 해당 명시 장 제목만 `ambiguous_scope_boundary`로 보내는 최소 가드와 기존 ready의 읽기 전용 경고를 검증·배포했다. 기술적 용량이 작아도 범위가 부적격이므로 입력 준비 완료에 넣지 않는다. 기존 target은 보존하며743·745·746·747·751·753·754·755·756·758·760 총11건의 정당한 범위를 담당자가 확인해야 한다. [운영 확인](../../.dryforge/prespec-mvp-deploy-20260911-OIBy24/scope-api-verification.json).
- 753의 기존 2–18쪽/65,141자 범위는 같은 줄 복수 장 경계로 모호하다. 새 선택기는 전체 page-text/PDF hash를 읽기 전용 대조한 뒤 `ambiguous_scope_boundary`를 반환했고 기존 target은 보존했다. 751·756·758·760과 함께 담당자가 PDF에서 정당한 범위를 확인해야 한다. 용량 한도 확대·요약·자동 분할은 하지 않는다.
- 752에는 안전한 과업지시서/용역설명서가 있으나 v4는 파일명 기반 RFP 선택만 한다. 기존 document role 수정 API와 bundle 선택은 이 실행 선택에 연결되지 않는다. 권장 최소안은 explicit_sample 준비의 정확한 document_version_id 선택과 notice/current/safe/hash/source 승인·actor 감사 결속이다. 자동 선택 확대나 role 변경으로 우회하지 않고 계약/담당자 결정 대기로 남긴다.
- 750·757의 저장 오류 `unsafe_document`만으로 악성 여부를 판정할 수 없다. attachment 경계는 allowlist 밖 세부 processor 코드를 unsafe_document로, API는 일부 안전 오류를 포괄 코드로 낮춘다. 기존 안전한 저장 정보에서는 더 좁은 원인을 확인하지 못했다. 승인된 격리 재진단/안전한 코드 확장 없이는 추정하지 않으며 차단과 원본을 보존한다.

## 승인된 Qwen 참조 worker의 목적지 제한 미확인 (2026-09-11, 추가 조회 생략 후 참조 실행)

- 재현: 현재 image의 non-root/read-only 임시 컨테이너를 `bidops_model-egress`의 실제 예정 source172.30.0.2에 연결해 TCP만 검사했다. 승인 Qwen192.168.0.139:58765와 불허 외부1.1.1.1:443 모두 연결됐다. host172.30.0.1:22의 connection refused는 방화벽 차단 증거가 아니다. 임시 컨테이너는 제거했다.
- 영향: endpoint allowlist는 있어도 host egress 경계를 충족하지 못한다. 744·749·759·761의 입력·전송 승인은 확인했지만 모델 HTTP·activation·enqueue 전에 중단했으므로 이번 점검의 문서/자격증명 전송·DB 쓰기는0이다. 기존 OFF를 유지했다.
- 원인/후속: 앞선 관리자 스크립트는 첨부 source172.19.0.2만 제한한다. 모델 source의 전용 규칙이 필요하나 `sudo -n`은 password required여서 권한을 우회하지 않았다. 기존 규칙을 보존하는 정확한 source/목적지 전용 적용 스크립트의 구문·비관리자 거부를 확인했다. 관리자 적용 결과와 같은 source의 실제 허용/차단을 확인한 뒤에만 승인4건을 실행한다. [점검·적용 대상](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md).
- 후속: 관리자 실행은 dedicated_chain_exists로 중단됐고 같은 source의 새 TCP 검사에서 Qwen 허용·외부 연결 거부를 관측했다. 사용자는 추가 체인/연결 규칙 조회를 생략하고 기능을 실행하도록 명시했다. 이번4건만 그 예외로 실행하고 OFF로 종료했다. 기존 방화벽은 변경하지 않았으며 체인 내용까지 검증 완료한 것으로 기록하지 않는다. 상시/다음 운영 배포의 방화벽 검증을 면제하는 일반 정책 변경이 아니다.

## Qwen v5 실표본4건이 모두 결정적 검사에서 종료된다 (2026-09-11, 미완료)

- 재현/범위: 승인된744·749·759·761의 고정 전체 선택 원문과 v5 binding으로 실제 Qwen 초안을 각1회 받았다. 네 응답 모두 파싱되며 형식 재생성·timeout·용량 초과는 없었다. 결정적 검사에서 모두 needs_human_review, semantic0·최종 개요0이다. [실행 증거](../../.dryforge/prespec-qwen-0911-mHF0bO/README.md).
- 관측: 744·749·761의8개 주장 모두 business_overview로 분류되어 필수 main_tasks가 없다. 759는 두 필수 섹션이 있지만 수치 metadata/단위, 분석 전제 및 unknown 사유 검사가 실패했다. 전체32주장 중 결정적15 통과/17 실패이며 의미 검토 전이므로 통과15도 최종 검증 문장이 아니다. 수치·단위·관계·날짜 대조 오류 코드는 실제 사실 오류와 검증기 과탐을 구별한 사람 판정이 아니다.
- 종결(2026-09-11): 이 관측은 policy v5·`bidops.prespec-overview-claims.v1`(8개 주장 상한 포함)·
  activation v2·call ledger 스택 전체를 대상으로 한다. [ADR-0054](decisions/0054-prespec-overview-mvp-rewrite.md)로
  이 스택을 삭제하고 정책 v6(`max_claims 12`)로 다시 썼으므로, 여기 기록된 8/32주장 비율과
  실패 사유 개수는 새 스택에 그대로 적용되지 않는다. 새 실행 결과는 별도 참조 실행으로
  다시 측정한다. 이 항목은 해당 스택 폐기로 종결한다.

## ingest CLI 경로가 deep_review 첨부 자격 hook을 부르지 않는다 (2026-09-11, 해결 2026-09-19)

- 재현: `python -m app.lifecycle.ingest.cli --run <RUN_ID>`는 `app.deep_review`의
  등록 함수를 import하지 않는다. `app/lifecycle/ingest/loader.py`는 module-level
  `extension_registry()` 싱글턴에 등록된 hook만 부르므로(`_run_ingested_hooks`),
  이 CLI 프로세스에서 그 싱글턴은 비어 있어
  `PreSpecAttachmentEligibilityHook.run_ingested` → `refresh_fetch_eligibility`가
  돌지 않는다. web 프로세스(FastAPI 앱 기동 경로)는 `app/deep_review/__init__.py`가
  이 hook을 등록하므로 API로 적재하면 정상 동작한다.
- 영향: ingest CLI로 적재한 회차는 사전규격 첨부 취득 자격이 자동으로 재평가되지
  않는다. `docs/operations.md` 3단계에 web 컨테이너에서 `refresh_fetch_eligibility`를
  수동으로 1회 부르는 임시 절차를 추가해 이 공백을 메웠다(2026-09-11).
- 해결(2026-09-19): `app/lifecycle/ingest/cli.py`가 적재 전에
  `register_configured_extensions()`로 `BIDOPS_MODULES`가 고른 모듈의
  `register_lifecycle_extensions`를 `run_prespec_e2e.py`와 같은 방식(이름을 런타임에
  푼다)으로 등록한다. web 프로세스(`create_app`)와 **같은 선택**을 쓰므로 CLI 적재와
  API 적재가 같은 hook 집합을 부른다. 제공자를 찾지 못하면 fail closed다. 아래의
  같은 뿌리 결함(C-2 409)과 한 수정으로 함께 닫혔다.

## 운영 `attachment.name`이 나라장터 자리표시자라 파일명 대조가 무의미하다 (2026-09-11, 경고로 완화됨·미해결)

- 재현: 운영 나라장터 응답의 `attachment.name`은 흔히 "첨부 1"류 자리표시자이고
  실제 파일명은 취득 응답 header에서만 온다. `document_bundles.py`의 확정 검사가
  `attachment.name != document.original_filename`이면 `source_name_differs`를
  내지만, 이 코드는 `blocking=False`(비차단 경고)로 완화돼 있다 — 원문 정체는
  이름이 아니라 hash·크기로 확인하기 때문이다(`web/backend/app/deep_review/services/document_bundles.py:428`
  부근 주석 참고).
  실제 원문이 바뀐 경우는 크기·hash·provider snapshot 검사가 별도로 차단한다.
- 영향: 나라장터가 원문 이름을 주지 않는 한 이 경고는 정상 케이스에서도 계속
  남고, 이름 기반 대조 자체는 사실상 정보를 주지 못한다. 확정을 막지는 않는다.
- 후속: 수집 단계(`skills/bidops-collect`)에서 취득 응답 header의 실제 파일명을
  더 이른 시점에 확보해 `attachment.name`에 반영할 수 있으면 이 경고를 줄일 수
  있다. 지금 범위에서는 해결하지 않는다.
- 영향/다음 판단: 입력 준비·전송·암호화 저장·검증 실패/근거 PDF 조회는 작동하나 검증된 개요를 얻는 실제 성공 경로는 미확인이다. 다음 개선은 초안 section/quantity/unknown 계약과 결정적 규칙의 실원문 적합성을 이 고정 응답/인용으로 좁혀 확인하는 것이 우선이다. 이번 실행 요청에서 새 정책/검증 방식 변경·사실 자동 수정·재호출을 임의로 진행하지 않는다. 원문·기존 결과/사람 리뷰/참조 표식과 실패 응답을 보존했다.

## 첨부 worker의 자동 문서 준비가 DB 권한에서 거부된다 (2026-09-15, 미해결)

- 재현: 운영 PostgreSQL의 `worker` 역할로 실행 중인 `prespec-attachment-worker`가
  사전규격 첨부를 `완료`로 종결한 뒤 `fetch_claimed`의 `maybe_auto_prepare`를 호출하면
  `ProgrammingError`, SQLSTATE `42501`로 자동 준비가 실패한다. 2026-09-14 수집 회차
  `prespecs-20260914-live-20260915T1200--20260915T015208.137811Z`에서 재현했으며,
  첨부 취득 자체는 `완료 28 / 차단 6`으로 정상 종결됐다.
- 원인·영향: `prespec_attachments.fetch_claimed`는 첨부 worker 프로세스에서 묶음 생성·확정까지
  호출하지만 `scripts/runtime-privileges.sql`의 worker INSERT allowlist에는
  `document_bundle`과 `document_bundle_item`이 없다. 따라서 첨부 종결 촉발점의 자동 준비는
  항상 권한에서 막히고, 운영자가 app 역할의 `prepare-overviews` 보정 명령을 실행해야 개요
  queue가 만들어진다. 첨부 결과는 자동 준비와 별도 transaction이라 되돌아가지 않는다.
- 지금 해결하지 않은 이유·후속: 이번 범위는 2026-09-14 실사용 회차 실행이며 역할 권한 계약,
  최소 권한 검사, 운영 권한 재적용을 함께 바꾸는 백엔드 수정은 포함하지 않았다. 자동 준비를
  app 소유 queue/hook으로 옮기거나 worker에 필요한 묶음 생성 권한만 좁게 부여하는 두 안을
  비교하고, 임시 PostgreSQL에서 허용 INSERT와 기존 UPDATE/DELETE 거부를 검증한 뒤 운영에
  적용한다. 이번 회차는 app 역할에서 대상 notice 26건만 동일 서비스로 다시 호출해 보정했다.
- 브랜치에서 해결(confirm 제자리 갱신), 운영 적용은 별도: worker에
  `document_bundle`·`document_bundle_item`·`idempotency_record`·`work_job` INSERT와
  확정에 쓰는 열만 여는 `document_bundle`·`document_bundle_item` 열 한정 UPDATE, 잠금용
  `document_structure (id)` UPDATE를 부여했다. 함께 `_seed_bundle_items`가 문서 집합·순서가
  그대로면 기존 draft item을 지우지 않고 제자리로 갱신하게 고쳐(`in_place`), 자동 준비
  경로가 `document_bundle_item` DELETE 권한 없이 끝난다. 문서 집합이 달라진 draft는 종전대로
  다시 넣고(`reseed`) 그 경로는 app 역할이 쓴다. 두 경로의 확정 결과는 같고 감사 행에
  `item_refresh`로 어느 쪽이었는지 남는다. worker는 어느 table에도 DELETE를 갖지 않는다.
- 후속: 같은 촉발점의 `maybe_auto_start_deep_review`는 worker 프로세스에서 `deep_review`를
  INSERT할 수 있으나 worker에는 그 권한이 없다(현재는 개요 run이 `completed`인 공고가 다시
  촉발될 때만 닿는다). 권한을 줄지 자동 시작을 app 경로로 옮길지는 미결이다.

## 운영 모델 주소가 TEST-NET 자리표시자로 배포됐다 (2026-09-16, 운영 조치 완료·코드 방지 진행 중)

- 재현: 2026-09-16 `bidops-web-1`·`bidops-analysis-worker-1` 환경의
  `BIDOPS_VLLM_BASE_URL=http://192.0.2.10:8000/v1`, `BIDOPS_VLLM_ALLOWED_HOSTS=192.0.2.10`.
  worker 안에서 TCP connect가 timeout. 개요 run은 9/15 이후 완료 0건, 대기 38건.
- 원인: 2026-09-12 compose 정리에서 `env/vllm.env`(자리표시자 값)를 `env/model.env`로
  합치면서 실제 주소(`http://192.168.0.139:58765/v1`, 9/11 검증 기록)가 유실됐다.
  `_validated_base_url`은 allowlist 문자열 일치만 보고 예약 대역을 거부하지 않는다.
- 조치: 2026-09-16 `env/model.env`를 실제 주소로 정정하고 analysis worker를
  재생성했다(validation-run `2026-09-16-overview-recovery.md`). 브랜치
  `feat/overview-claim-guard`가 RFC 5737 예약 대역을 호출 전에 거부하도록 한다.
- 후속: worker 기동 시 endpoint preflight는 아직 없다.

## 개요 worker의 claim 루프가 재시도 상한을 무시한다 (2026-09-16, 코드 수정 진행 중)

- 재현: 운영 `work_job`에서 `max_attempts=3`인 개요 job의 `attempt_count`가
  205(실행 중)·321(9/15 `lease_expired` 실패). 대기 38건이 처리되지 않았다.
- 원인: `overview_runs._claim_next`가 claim 시 `attempt_count`를 올리고,
  `verify_identity()` 실패를 `_release`로 `queued`에 되돌리며 카운터·상한을 보지
  않는다. `max_attempts`는 `work_job` 경로 어디서도 읽히지 않고
  `deep_reviews.claim_next_job`의 만료 reclaim도 같다. 사람이 run을 닫는
  REST·CLI가 없다.
- 영향: 모델 endpoint가 죽어 있으면 한 작업이 1초 poll마다 재점유돼 대기열
  머리를 영구히 막는다.
- 후속: 브랜치 `feat/overview-claim-guard`가 상한 게이트·`_release` 복원·identity
  backoff·`close-overview-run` CLI를 추가한다.

## 화면 스위트의 발주계획·공통 골격 spec 53건이 main에서 실패한다 (2026-09-16, 원인 미확인)

- 재현: main `bdd6c25`에서 `PW_PORT=4183 npx playwright test <spec> --project=app --workers=2`.
  `order-plans.spec.ts` 46건, `review-primitives.spec.ts` 3건, `admin-workspace-consistency.spec.ts` 2건,
  `review-workspace-consistency.spec.ts` 1건, `explore-workspace-consistency.spec.ts` 1건이 실패한다.
  발주계획 목록은 mock 응답이 있는데도 "조건에 맞는 계획이 없습니다"로 비어 `.c2l-row`가 0개이고,
  실행 상태 화면은 `.rs-detail-foot`이 없다. 부하를 줄여(worker 2) 다시 돌려도 같은 건수다.
- 영향: 같은 날 오전 `10cb5be` 기록은 `--project=app` 449 passed·0 failed였다. 그 사이 main의 프런트 코드
  변경은 없고(백엔드·권한 SQL·문서만), 개요 3섹션 변경(ADR-0057) 통합 트리도 같은 53건만 실패했다
  (그 외 1건은 의도한 배치 변경의 spec 기대값 누락이라 고쳤다). 따라서 이번 변경의 회귀는 아니다.
- 지금 해결하지 않은 이유: 원인을 확인하지 않았다. 날짜에 의존하는 mock 데이터(관측 기간·마감 기준)나
  공유 mock의 회차 목록이 후보다. 이번 범위는 개요 검토 재설계라 확장하지 않았다.
- 후속: `10cb5be`를 격리 워크트리로 체크아웃해 같은 spec을 돌려 날짜 의존인지 코드 의존인지 먼저 가른다.
- 2026-09-20 재확인(main `acdf0d9`, 같은 명령): `order-plans.spec.ts`·`explore-workspace-consistency.spec.ts`·
  `review-primitives.spec.ts`·`pre-specs.spec.ts`·`prespec-list-work.spec.ts`는 **156 passed · 0 failed**다.
  발주계획 목록이 비던 50건은 더 재현되지 않는다(그 사이 무엇이 고쳤는지는 가르지 않았다). **남은 것은
  `admin-workspace-consistency.spec.ts:23`의 2건(1280·1440)**으로, 수정 없는 main에서 실행 상태 화면의
  `.rs-detail-foot`이 보이지 않아 똑같이 실패한다. 이 항목은 그 2건으로 좁혀 유지한다.
- 2026-09-20 함께 확인된 기존 실패 1건: `common-interactions.spec.ts:266` "사이드바는 7항목…"이 main에서 8개를
  본다. `acdf0d9`(나라장터 바로가기 추가)가 8번째 `.sidebar-item`을 넣고 `design-shell.spec.ts`만 갱신했다.
  바로가기를 `SIDEBAR_ITEMS`에 넣을지 카운트에서 뺄지는 그 변경의 의도에 달려 있어 고치지 않았다.
  → 같은 날 해소(`dd5da1d`): 바로가기는 그룹 밖 외부 링크이고 `design-shell.spec.ts`가 따로 검사하므로 주 메뉴 항목만 세게 했다.

## 비교 근거 최종 결정 경로가 runtime `app` 역할에서 실행되지 않는다 (2026-09-17, 수용됨)

- 재현 조건: `scripts/runtime-privileges.sql:55`에서 `bid_delta_comparison`은 app에 SELECT만
  주고, `bid_delta_attempt`·`bid_delta_item`·`bid_delta_evidence`는 app·worker 어느 쪽에도
  아무 권한이 없다(파일 어디에도 이름이 없다). `POST /api/opportunities/{id}/bid-delta/comparisons`
  (`services/bid_delta.py:806` `create_comparison`)는 `session.add(comparison)`·
  `session.add(attempt)`로 두 table에 INSERT한다. 최소 권한의 `app` DB 역할로 이 endpoint를
  호출하면 PostgreSQL이 권한 오류(SQLSTATE `42501`)로 거부한다.
- 증상: 비교 생성 202 응답과 `pending` comparison·`queued` attempt는 테스트·상승된 DB 자격
  증명(migration/superuser 역할)으로 검증됐을 뿐, 운영이 쓰는 `app` 역할로는 재현되지 않는다.
  이 경로는 애초에 비교를 실제로 계산하는 worker가 없어 `pending`에 머무는 것으로 문서화돼
  있었지만([ADR-0058](decisions/0058-final-decision-basis-separated-from-comparison.md) 맥락,
  `docs/contracts.md` "구현된 계약 — 입찰 delta와 최종 결정"), 이번 확인으로 **`pending`조차
  runtime 권한으로는 만들 수 없다**는 사실이 드러났다.
- 영향: `basis_kind=comparison` 최종 결정 경로 전체(비교 생성 → attempt 재시도 →
  완료된 비교 기반 결정)가 운영 `app` 역할에서 시작조차 되지 않는다. `basis_kind=
  notice_conditions` 경로(공고 조건 결정, ADR-0058)는 영향 없다 — 그 경로는 `bid_final_decision`
  INSERT와 `UPDATE (id)`만 필요하며 두 권한 모두 이미 app에 있다(`runtime-privileges.sql:150,224`).
- 지금 해결할 수 없는 이유: 비교를 실제로 계산하는 worker가 아직 구현되지 않았고 이번 계획은
  그 구현을 명시적으로 보류했다(ADR-0058 §6 "비교 계산 worker와 모델 binding은 계속 보류").
  worker 없이 `bid_delta_comparison`·`bid_delta_attempt`·`bid_delta_item`·`bid_delta_evidence`
  INSERT 권한만 먼저 열면 계산되지 않는 `pending` 행만 쌓이고 실제 문제(모델 호출·계산 로직
  부재)는 그대로다. 권한 설계는 그 worker의 쓰기 경계(app이 만들고 worker가 계산·완료하는
  분리, `bid_final_decision`이 이미 쓰는 패턴)와 함께 정해야 중복 개정을 피한다.
- 접근 방법: 비교 계산 worker를 구현할 때 함께 `scripts/runtime-privileges.sql`에 app의
  `bid_delta_comparison`·`bid_delta_attempt` INSERT(비교·attempt 생성은 API가 함)와 worker의
  계산 완료용 column-scoped UPDATE(`0014_prespec_overview_attempt_result`가 쓴 것과 같은
  패턴: `status`·`started_at`·`completed_at`·result 참조 열만)를 추가하고
  `tests/app/test_runtime_database_privileges.py`에 각 table의 허용 INSERT/UPDATE와 거부되는
  DELETE·다른 열 UPDATE를 고정한다.
- 상태: 수용됨. 현재 범위(공고 조건 근거 경로)는 이 권한 공백과 무관하게 동작하므로 이번
  계획에서는 수정하지 않는다.

## 회사 핏은 심층 검토를 막는데 품질을 잴 장치가 없다 (2026-09-18, 미해결)

- 재현 조건: `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=true`(기본 false, `web/backend/app/core/config.py:197`)와
  참조 실행 모드에서 사전규격 개요가 `completed`인 공고의 회사 핏 결과가 `matched`가 아니면
  `web/backend/app/deep_review/services/company_fit.py:272-273`이 `company_fit_<decision>` 사유를 내고,
  `web/backend/app/deep_review/services/auto_preparation.py:460-461`이 그 사유로 심층 검토 자동 시작을 막는다.
  회사 핏 시도 table의 `quality_status`는 CHECK로 `unmeasured_reference`·`mock_reference`만 허용한다
  (`web/backend/app/deep_review/models.py:1723`). 회사 핏에는 gold·임계값·활성화 게이트가 없다.
- 영향: 모델 출력이 사람 눈에 닿기 전에 다음 단계를 막는 지점인데, 떨어진 건이 맞게 떨어졌는지 잴 방법이 없다.
  `quality_status`가 `measured`가 될 수 없는 구조라 측정을 해도 기록할 자리가 없다. 핏에서 떨어진 공고도 목록에는
  남으므로 C-2 탈락보다는 피해가 작다. 지금은 기본 비활성이고, 켜도 참조 실행 모드가 아니면
  `company_fit_reference_only`로 닫히므로(`company_fit.py:245-246`) 운영에 닿지 않는다.
- 지금 해결할 수 없는 이유: 일일 운영 고도화 계획은 C-2 게이트만 구현하고 C-2 밖의 품질 장치는 지도와 선행조건만
  기록하기로 했다([`0918_daily-operation/intent.md` §6](../0918_daily-operation/intent.md) 결정 26). 회사 핏 gold를
  만들 표본과 사람 정답이 아직 없고 임계값은 사람 결정이다.
- 후속 방향: 회사 핏을 운영에서 켜기 전에 게이트를 먼저 만든다(별도 계획). C-2 게이트 구조 — 승인된 사람 gold,
  NULL이면 `미측정`인 임계값, 같은 묶음 2 pass, append-only evaluation — 를 다시 쓸 수 있다. `quality_status` CHECK에
  측정값을 담을 자리를 함께 설계한다.

## 사전규격 개요는 운영 중인데 표본 점검 라벨을 담을 자리가 없다 (2026-09-18, 미해결)

- 재현 조건: 운영의 web·분석 워커·첨부 워커는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`로 개요를 자동으로 돌린다
  (2026-09-18 컨테이너 확인). 개요 run의 `quality_status`는 항상 `unmeasured_reference`(모델명이 `mock`이면
  `mock_reference`)다(`web/backend/app/deep_review/services/overview_runs.py:481-483`). 개요 결과에 사람이 정답·오답을
  다는 table·REST가 없다 — 개요의 쓰기 REST는 쪽 범위 확정(`POST /api/pre-specs/{notice_id}/overview/range-confirmations`,
  `web/backend/app/deep_review/routers/overviews.py:91`)뿐이다. 수량·날짜 불일치 일부(`quantity_mismatch`·
  `quantity_metadata_mismatch`·`quantity_relation_ambiguous`·`quantity_unit_missing`·`date_mismatch` 등)는 실패가 아니라
  경고로 분류된다(`web/backend/app/deep_review/services/prespec_overview_claim_validation.py:37-49`).
- 영향: 개요는 건을 거르지 않는다 — 대상은 나라장터 SW 대상 표시로 정해지고 모델 판단이 아니다
  (`web/backend/app/deep_review/services/effective_grade.py:135-169`). 인용문·쪽수를 원문과 대조하는 결정적 검증이 있고
  실패하면 `needs_human_review`다. 그러나 경고로 완화된 수량·날짜 불일치가 담당자에게 얼마나 자주 틀린 정보로
  닿는지 셀 방법이 없고, 품질 표식이 참조 표식에서 벗어날 근거도 쌓이지 않는다.
- 지금 해결할 수 없는 이유: 사람이 근거와 함께 읽는 지점이라 정식 게이트보다 표본 점검이 맞다고 판단했지만
  ([`0918_daily-operation/intent.md` §6](../0918_daily-operation/intent.md)), 라벨 축·저장 table·REST·화면을 새로
  설계해야 하고 일일 운영 고도화 계획은 C-2만 구현한다(결정 26).
- 후속 방향: 별도 계획으로 개요 run 단위의 표본 점검 라벨(주장별 맞음·틀림·원문 없음 등)을 append-only로 담을 자리를
  만들고, 경고 코드별 발생률과 라벨을 대조해 경고로 둘지 실패로 올릴지 다시 정한다. 라벨이 쌓이기 전까지
  `unmeasured_reference`를 측정으로 승격시키지 않는다.

## C-1 수동 경로가 후보 policy를 받고 그 `제외`가 기본 목록에서 숨는다 (2026-09-18, 수용됨)

- 재현 조건: C-1 공고 판정을 수동 경로(`cli_single`·`manual_run`)로 부르면 `activation_candidate` policy도 받는다 —
  `web/backend/app/screening/orchestrator.py:1623`(trigger가 `schedule`이 아니면 `activation_candidate|active` 허용),
  `web/backend/app/screening/worker.py:375-377`, `web/backend/app/screening/queue.py:427-429`. 그 결과의 `제외` 판정은
  필터가 없을 때 공고 목록 기본 조건에서 빠진다(`web/backend/app/screening/projection.py:52`의
  `DEFAULT_EXCLUDED_GRADE = "제외"`, `:585`의 `Judgment.grade != DEFAULT_EXCLUDED_GRADE`).
- 영향: 품질 게이트를 통과한 적 없는 policy의 `제외`가 담당자의 기본 보기에서 공고를 숨긴다. 테이블 채우기 같은 참조
  실행 절차(`docs/e2e-lifecycle-fill.md` 6단계의 `/runs` 화면 판정 실행)가 이 경로를 쓰므로 참조 실행 결과가 운영 화면의 기본 보기를 바꿀 수 있다.
  C-1 게이트는 0건이고 policy 둘 다 `activation_candidate`이며 `BIDOPS_SCHEDULER_ENABLED=false`다(2026-09-18 운영 확인).
- 지금 해결할 수 없는 이유: 활성화된 적 없는 policy의 `제외`를 숨기지 않게 할지, 수동 경로도 `active`만 받게 할지는
  C-1 자동화 방식과 함께 정해야 한다. 뒤쪽을 고르면 참조 실행 절차를 함께 고쳐야 한다. 일일 운영 고도화 계획은
  C-1 코드를 그대로 두고 **C-1 자동화 전까지 C-1을 운영에 쓰지 않기로** 정했다(결정 27).
- 후속 방향: C-1 자동화 때 [`0918_daily-operation/plan.md` §7](../0918_daily-operation/plan.md)의 선행조건 ② "수동 경로
  정리"에서 두 안 중 하나를 고른다. 그 전까지 C-1을 점검용으로 부른 판정은 미측정 policy의 판정이며 운영 판단의
  근거로 쓰지 않는다.

## 운영 DB의 C-2 policy v2가 활성화 API 없이 active·passed로 있다 (2026-09-18, 운영 조치 완료 2026-09-19)

- 재현 조건: 운영 DB에 `c2-order-plan-screening-v2`가 `policy_status=active`·`quality_gate_status=passed`
  (`active_slot=1`)로, v1이 `retired`·`passed`로 있다. 2026-09-03 종단 확인 때 테스트 전용 SQL로 직접
  DB 행을 활성화한 것이며(`docs/tracking/status.md`의 발주계획 C-2 선별 항목 "테스트 전용 policy 사본으로만
  활성화했고 품질 근거가 아니다"), 그 활성화에 대응하는 `AuditEvent(action="c2.policy_activated")`나 그
  실행 이력이 없다.
- 영향: 이번 웨이브의 새 활성화 탭(`/order-plan-policies`)은 policy 행의 `policy_status`·
  `quality_gate_status`·`active_slot`을 읽어 게이트를 통과한 활성 policy처럼 보여준다 — v2는 이 조건을
  전부 만족한다. 실제로는 v2 binding의 `external_transport.execution_allowed`가 승인되지 않았고
  `BIDOPS_C2_EXECUTION_ALLOWED`도 기본 false이므로 C-2 실행과 일일 자동 실행은 여전히 fail closed다. 화면
  표시와 실제 실행 가능 여부가 갈리는 지점이라 담당자가 "이미 활성화됐다"고 오인할 수 있다.
- 지금 해결할 수 없는 이유: 활성 행을 되돌리는 것은 DB 데이터를 직접 고치는 운영 작업이라 사람 승인이
  필요하고, 이번 계획의 범위(코드·문서)를 넘는다. v2를 그대로 retire하면 그 근거가 된 2026-09-03 종단
  확인 기록과의 관계도 함께 정리해야 한다.
- 후속 방향: 배포 때 `python -m app.screening.c2_policy retire`로 v2를 내린다(사람 승인됨, 2026-09-19).
  교체 없이 `retired`·`active_slot=NULL`로 내려가고 감사 이벤트(`c2.policy_retired`,
  `replaced_by_policy_version=null`)가 남으며, 활성 policy가 없으므로 일일 자동 실행도
  `no_active_policy`로 꺼진 채 시작한다(절차는 `docs/operations.md`의 C-2 활성화 절). 운영 조치 전이므로
  이 항목은 실제 실행과 그 결과 확인 뒤에 닫는다. v3를 정식 활성화하면 그 시점에는 활성화 transaction이
  이전 active를 자동으로 내린다(§3.3 9번, `docs/0918_daily-operation/spec.md`).
- 조치 결과(2026-09-19): 운영 DB를 백업(`backups/postgres/full/bidops-20260919T063021Z.dump`, SHA-256
  `f0fb31f1…3e4a09`)하고 그 사본으로 0026→0029 migration과 retire CLI를 격리 리허설한 뒤, 운영에 migration
  `0029_c2_quality_gate`를 적용하고 web 컨테이너에서 retire CLI를 실행했다(담당자 `jechoi`). v2는
  `retired`·`active_slot=NULL`이고 `c2.policy_retired` 감사 이벤트 1건이 남았다. `activated_by=e2e-test`·
  `quality_gate_status=passed`는 이력으로 그대로 남는다 — 품질 근거가 아니다. 화면 확인: 활성화 탭 "운영 활성
  없음", 발주계획 "누적 판정 없음"(참조 실행을 "최근 운영 실행"으로 적지 않음), 자동 실행 배너 없음, 대시보드
  "완료된 선별 실행 없음". 활성화 탭은 교체 없이 내린 v2도 "교체됨"으로 표시한다(문구 미수정).

## 발주계획 화면이 누적 목록을 500행씩 전부 받아 브라우저에서 거른다 (2026-09-18, 미해결)

- 재현 조건: `web/frontend/src/pages/OrderPlansPage.tsx:77`의 `PAGE_SIZE = 500`으로 누적 목록을 한 번에
  최대 500행 받아 브라우저에서 필터링한다. 활성화 뒤 발주계획은 하루 약 300건씩 누적으로 늘어난다
  (`docs/0918_daily-operation/spec.md` §7 — 활성화된 적 있는 policy의 운영 목적 완료 실행 전부가 누적
  범위).
- 영향: 누적 기간이 늘수록(며칠만 지나도 500건을 넘는다) 서버가 이미 필터링해 줄 수 있는 조건도 클라이언트가
  전량을 받아서 걸러야 하므로 응답 크기와 렌더 비용이 계속 커진다. 목록 응답의 `human_feedback`에
  `execution_id`가 없어 화면이 `expected_revision`(다음 사람 피드백 저장 시 낙관적 잠금에 쓰는 값)을
  계산하려면 별도 조회가 필요하다.
- 지금 해결할 수 없는 이유: 서버 쪽 필터·페이지네이션은 목록 쿼리(`services/order_plan_screening.py`의
  누적 투영)와 화면 양쪽을 함께 다시 설계해야 하고, 이번 일일 운영 고도화 계획은 누적 투영을 "회차 선택
  없이 전체를 한 번에 반환"하는 현재 모양으로 두고 활성화 경로만 구현했다.
- 후속 방향: 별도 계획으로 목록 API에 서버 쪽 필터·페이지 파라미터를 추가하고, 응답 `human_feedback`에
  `execution_id`를 실어 화면이 재조회 없이 `expected_revision`을 계산하게 한다(`docs/contracts.md`
  변경 제안).

## 1280 폭 대시보드에 세로 스크롤이 생긴다 (2026-09-19, 수용됨)

- 재현 조건: viewport 1280x800에서 대시보드(`/`)를 열고 사업 추적 보류 패널이 5행일 때 페이지에 약 170px
  세로 스크롤이 생긴다. 2026-09-17 사업 추적 고도화(main 7249ae9)에서 들어온 배치이며 그 작업의 화면 확인
  때 관측한 값이다. 2026-09-19에는 다시 재지 않았다.
- 영향: 1280 폭에서 대시보드 하단 패널을 보려면 스크롤해야 한다. 가로 스크롤이나 별도 레이아웃 전환이
  아니므로 ADR-0047(지원 폭 1280~1920px) 위반은 아니다.
- 지금 해결할 수 없는 이유: 일일 운영 고도화(`feat/do-integration`) 병합 범위와 무관한 기존 main의 배치이고,
  패널 행 수·높이를 줄이는 것은 대시보드 구성 결정이다. 2026-09-19 사용자가 그대로 두기로 했다.
- 후속 방향: 대시보드를 다시 손댈 때 보류 패널의 행 상한 또는 패널 높이 배분을 함께 정한다.

## 적재 CLI로 넣은 회차를 C-2가 `409 source_run_incomplete`로 거부한다 (2026-09-19, 해결 2026-09-19)

- 재현: `python -m app.lifecycle.ingest.cli --run <id> --collection`(일일 스크립트
  `scripts/run-daily-lifecycle.sh`와 `docs/operations.md` 활성화 절차 7단계가 쓰는 경로)은
  CLI 프로세스에 모듈 확장점이 등록돼 있지 않아 `loader.py:_complete_run_ingest`가
  `extensions.run_ingest_hook_count == 0` 분기로 빠지고 회차에
  `IngestWarning(code="judgment_ingest_skipped")`를 남긴다. C-2 실행 생성은 source run에
  ingest warning이 하나라도 있으면 `409 source_run_incomplete`로 거부하므로, CLI로 적재한
  회차는 C-2 입력이 될 수 없었다.
- 영향: 2026-09-19 운영에서 게이트 측정 pass 1이 첫 회차에서 멈췄다. **일일 발주계획 트랙
  (`--track order-plans` → CLI 적재 → `run-daily-c2.sh`)도 같은 이유로 매일 409가 된다.**
  `docs/0918_daily-operation/spec.md` §9.2의 공고 adopt 검사("IngestWarning 0건")도 CLI 적재
  회차에서는 항상 실패했다. 우회로는 같은 회차를 web 프로세스의 `POST /api/runs/ingest`로 다시
  적재하는 것뿐이었고(재적재가 그 회차 경고를 지운다), REST 적재에는 `--collection` 모드가 없다.
- 진단이 늦은 이유: router(`routers/order_plans.py`)가 응답 message를 code별 고정 문구로
  바꾸므로 "source run에 ingest warning이 있습니다"라는 구체 사유가 API 응답에 보이지 않았고,
  거부를 남기는 서버 로그도 없었다.
- 해결(2026-09-19): ① CLI가 `BIDOPS_MODULES` 선택대로 확장점을 등록한 뒤 적재한다(위 항목과
  같은 수정). ② `_error_response`가 서비스의 구체 사유를 서버 로그에 남긴다 — 응답 `details`는
  `docs/contracts.md`가 이 code에서 `null`로 고정하므로 바꾸지 않았다. ③ source run 검사를
  `OrderPlanScreeningService.require_complete_source_run`으로 뽑아 회귀 검사가 제품 코드를
  그대로 부른다(`tests/app/test_ingest_cli_extensions.py`, 새 인터프리터로 적재 → 같은 DB에서 검사).
- 남은 것: 적재 경고 자체는 계속 C-2를 막는다(부분 적재 회차를 통과시키지 않기 위해 의도한 것이다).
  등록이 되는데도 경고가 남는 회차는 진짜 부분 적재이므로 경고 code로 원인을 본다.
