# 운영·데이터·보안 문제 기록

[전체 색인](../findings.md). 미해결 또는 일부 조치 뒤 검증이 남은 항목이다. 제목의 날짜는 마지막 관측·기록 시점이며 2026-10-21에 다시 재현했다는 뜻이 아니다. 과거 기능명·정책·환경을 현재에 적용하기 전에 소스와 마지막 실행 증거를 확인한다.

## 2026-11-17 통합 개발 Compose의 응답 대기와 worker 경고

- 재현 환경: `integration/deep-agent-baseline`, `bidops-dev:18789`, amd64 app·arm64 문서 worker. 합성 HWPX/회사로 실제 공용 worker와 versioned MinIO/PostgreSQL을 연결했다.
- 해소: 초기 panel 5초 실패는 lazy 파일 로드 뒤 시작하는 필수 notice GET과 assertion이 동기화되지 않은 검사 한계가 있었다. 정확한 GET의 상태·본문·notice ID를 기다리도록 고쳤고 기존 전체/화면/결과 제한은 유지했다.
- 해소: 동기화 뒤 desktop에서 actor 입력이 사라지는 제품 결함을 별도로 확인했다. bundle null→ready의 key 변경이 입력 중 DOM을 교체했다. old-code 회귀 실패 후 stable company/notice key·frozen request/actor/bundle·bundle 변경 현재성 재조회로 수정했다. 최종 UI 9건과 실제 Compose 두 폭 E2E가 통과했다.
- 남은 관측: 초기에 `worker.job_failed`가 있었으나 같은 역할의 각 소비자와 공용 `--once`에서는 재현되지 않았다. 초기 재기동도 60초를 넘긴 뒤 health가 정상화됐다. 당시 host load average가 약 90/132/112로 높았지만 시계열이 없어 원인을 확정하지 않는다. 별도 probe와 최종 기동/기능 성공으로 이 관측을 해소 처리하지 않는다.
- 환경 조치: Docker 기본 address pool 소진은 기존 network/daemon을 건드리지 않고 개발 전용 비중첩 subnet으로 우회했다. 운영·다른 프로젝트의 자원을 변경하지 않았다.
- 후속: 유휴 worker는 민감 payload 없이 event/exception-class를 계측한다. 지연 재현 시 브라우저 body 완료, 서버 duration/DB wait, host/VM 자원을 같은 시점에 대조한다. timeout 확대·강제 클릭으로 실패를 통과시키지 않는다.
- 증거: [통합 검증](../../validation-runs/20261117-engine-integration/README.md), `.sdlc/dev-browser-actor-fixed.log`, `frontend-actor-tests.log`. 초기 실패 로그와 trace도 `.sdlc`에 유지한다.

## 첨부 취득 종결에서 부르는 자동 문서 준비가 커밋되지 않는다 (2026-10-15, 미해결)

- 재현: 첨부 worker(`prespec_attachment` 상시 또는 `--once --notice-id N`)가 공고의 마지막 첨부를
  `완료`로 끝내면 `fetch_claimed`가 `maybe_auto_prepare(session, [notice_id])`를 부른다. 반환값은
  `created=True, confirmed=True`인데 DB에는 묶음·감사·개요 run이 남지 않는다. 2026-10-15 Mac
  운영에서 첨부가 모두 끝난 공고 158건 중 148건에 묶음이 없었고 목록은
  `waiting_attachments`/`no_ready_document`로 보였다. 공고 503에서 반환값과 DB를 대조해 확인했다.
- 원인: `fetch_claimed`는 호출 직전에 커밋하지만 `maybe_auto_prepare`가 자격 조회
  (`Notice` 선택·`effective_grades`)로 session에 transaction을 다시 연다. 그 뒤 `_work_session`이
  `session.in_transaction()`을 참으로 보고 savepoint session을 주므로 `create_bundle`·`confirm`·
  `_enqueue_overview`의 commit은 savepoint만 놓는다. 바깥 transaction을 커밋하는 쪽이 없어
  session이 닫히며 모두 되돌아간다. 회차 적재 hook(바깥 transaction을 커밋하는 호출부)과
  `prepare-overviews` CLI(호출 뒤 `session.commit()`)에서는 남는다. WSL2 운영에서 매일 공고
  회차가 같은 공고를 다시 적재하며 hook이 대신 커밋해 이 결함이 가려졌을 가능성이 높다.
- 영향: 첨부 취득이 끝나도 묶음·개요가 다음 공고 회차 적재나 사람의 backfill까지 미뤄진다.
- 지금 해결하지 않는 이유: 이번 작업은 운영 실행(개요까지) 범위이고, 수정은 transaction 경계를
  바꾸는 제품 변경이라 회귀 테스트(취득 worker 경로에서 묶음 영속)를 함께 넣어야 한다. 이번에는
  대상 공고마다 `maybe_auto_prepare` 뒤 `session.commit()`을 부르는, `prepare-overviews`와 같은
  방식으로 처리했다.
- 함께 걸리는 설정 결함: 개요 run은 **큐에 넣는 프로세스**의 `BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH`로
  `policy_digest`를 고정한다. `docker-compose.model-egress.yml`은 이 값을 web·analysis-worker에만
  렌더하므로 첨부 worker가 넣은 run은 기본 v7 digest를 갖고, analysis worker(v7-litellm-v2)가
  호출 전에 `binding_mismatch`로 닫는다. 2026-10-15 첨부 worker 컨테이너에서 준비를 돌린 13건이
  이렇게 끝났고(모델 호출 없음), web에서 다시 준비해 재시도했다. 위 커밋 결함을 고치면 이 경로가
  처음으로 실제 run을 남기므로 정책 경로 렌더도 같이 고쳐야 한다.
- 후속 방향: `fetch_claimed`가 자동 준비 뒤 커밋하거나, `maybe_auto_prepare`가 자기 자격 조회
  transaction을 닫은 뒤 `_work_session`을 고르게 한다. 취득 worker 경로 테스트가 실제 DB에서
  묶음 행을 다시 읽어 확인해야 한다(반환값만 보는 테스트는 이 결함을 놓친다).

## WSL2 종료로 C-2 v4 승인 프롬프트와 운영 DB가 사라졌다 (2026-10-14, 일부 해소)

- 재현: Mac 전체와 저장소 이력에서 `order-plan-batch-relevance-v3-approved.txt`(`639f…`)를
  찾으면 없다. 본문은 gitignore된 회사자료였고 WSL2 호스트에만 있었다. 운영 PostgreSQL·
  MinIO 백업도 Mac으로 넘어오지 않았다. 사설 vLLM `192.168.0.139:58765`는 Mac에서 닿지 않는다.
- 영향: v4 binding(프롬프트·모델 digest 고정)은 어디서도 다시 실행할 수 없다. 9-28 이전 C-2
  실행·피드백·게이트 기록과 사업 추적 이력은 Mac 운영 DB에 없다. `data/runs`의
  `lifecycle-*` 디렉터리(10-04 복사본)만 원본으로 남았다.
- 해소한 것: C-2 v5를 새로 발행하고 Mac `bidops` 스택에서 게이트를 다시 거친다
  ([ADR-0072](../decisions/0072-c2-mac-litellm-ollama.md)). 승인 본문 경로는 운영 절차의 백업
  대상에 넣었다.
- 남은 것: 9-28 이전 운영 이력의 복원 수단이 없다. 과거 회차를 Mac DB에 다시 적재하면
  수집·적재는 되지만 사람 판정·추적 이력은 돌아오지 않는다. 승인 입력 본문을 저장소 밖의
  암호화 백업에 두는 절차는 아직 없다.
- 테스트 영향: C-2 service·worker fixture가 v3 본문을 직접 읽어 9-28 이후 그 테스트들이 전부
  수집 단계에서 실패하고 있었다. fixture가 합성 프롬프트를 묶고 관련 digest를 다시 고정하도록
  바꿨다. 이 과정에서 가려져 있던 `test_order_plan_list_v2.py`의 유니코드 casefold 검색 5건이
  SQLite에서 실패하는 것이 드러났다(`ß`·`İ`·`ﬃ`·그리스 문자 비교). C-2 변경과 무관하며 별도로 본다.

## 이전 백업에서 확인한 과거 회사 프로필 객체 버전 누락 (2026-09-29, 미해결)

- 재현: `scripts/transfer-check.py`로 MinIO의 모든 객체 버전과 DB의 verified·미삭제
  `content_object_location`을 대조한다. 이전 작업 전 원본에서 2,228개 객체 버전과
  2,125개 active 참조를 읽었고 아래 두 위치의 version이 없었다.
  `34a5aadb-9fb5-4d82-b5dd-70066065d095`, `ad08be70-ea4b-4a4a-80d2-ac1fc5edcc81`.
- 영향: 둘 다 source namespace의 회사 프로필 근거 객체다. 각각 profile_version 한 건과
  연결되며 document_version 연결은 없다. 과거 위치 자체의 원문 재현을 보증할 수 없다.
  현재 프로필의 다른 정상 위치 존재 여부와 화면 가용성은 별도로 확인한다.
- 이번 작업은 현 상태 보존이므로 DB 위치·기존 근거·원문을 추정하거나 덮어쓰지 않는다.
  원본 누락을 복원 과정에서 생긴 누락과 구분해 이전 폴더의 `manifest/objects.json`에 남긴다.
- 후속: 기존 백업의 동일 version·hash 존재를 확인하고 승인된 프로필 원문과 대조한다.
  필요한 복구는 기존 `--repair-profile-source` 절차로 새 위치와 감사를 추가한다.
  원래 version의 바이트 확인 없이 복구 완료나 정상 참조로 표시하지 않는다.

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
- 상태: **해결** (2026-09-03, [ADR-0042](../decisions/0042-c2-model-revision-declared-at-deployment.md))
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

## ADR-0027의 21일 재조회 근거가 종단 관측에서 재현되지 않는다

- 상태: **해결** (2026-09-18, [ADR-0061](../decisions/0061-daily-collection-window.md))
- 재현 조건: `experiments/lifecycle-linkage-survey/scripts/survey.py`로 게시일 2026-08-24~2026-08-26 구간을 재조회하고 `--baseline-raw`로 이전 관측과 대조한다. 실행 기록은 [`20260831-order-plan-longitudinal.md`](../../validation-runs/20260831-order-plan-longitudinal.md)에 있다.
- 증상: 같은 997건이 5일 동안 `bidNtceNoList` 채움률 45.6% → 46.6%로 **1 포인트**만 올랐다. 같은 나이(6일)의 횡단면 점은 67.8%다. 횡단면 곡선은 3일 45.8% → 6일 67.8% → 9일 77.1%로 가파르게 오르지만 실제로 추적 가능한 코호트는 그 속도로 채워지지 않는다.
- 영향: [ADR-0027](../decisions/0027-order-plan-requery-window.md)이 재조회 범위를 최근 21일로 정한 근거는 횡단면 곡선의 "15~17일 평탄화"다. 실제 코호트가 훨씬 느리게 채워진다면 평탄화 시점이 21일보다 뒤일 수 있고 그러면 창이 짧아 공고 전환을 놓친다. [fill-curve](../../validation-runs/20260829-order-plan-fill-curve.md)가 "횡단면과 종단이 어긋나면 종단이 정본"이라고 미리 정해 두었으므로 이 관측이 우선한다.
- 지금 해결할 수 없는 이유: 종단 관측점이 세 개이고 기간이 5일뿐이다. 21일이 틀렸다고 단정하기에 부족하다. 나이 15일과 21일 근처(2026-09-08, 2026-09-14 무렵) 관측이 나와야 판단할 수 있고, 재조회 범위 변경은 수집 비용과 API 한도에 직접 영향을 주므로 사람 결정이 필요하다.
- 접근 방법: 같은 구간의 재조회를 계속 쌓아 나이 21일 이후까지 본다. 횡단면 구간들은 폭이 3일로 같은데 건수가 28~997로 흔들려(08-15 광복절 구간이 28건) 비교 가능한 코호트가 아니다. 횡단면 기울기가 나이 효과인지 코호트 구성 차이인지 구분하려면 요일 구성이 같은 구간끼리 비교하거나, 08-21~08-23 구간도 종단으로 추적해 두 방법을 같은 코호트에서 직접 대조한다.
- 해결: ADR-0061이 ADR-0027을 폐기하고 발주계획을 전일 하루 창으로 수집하고 재조회하지 않기로 정했다. 21일 창의 길이를 맞추는 문제가 아니라 재조회 자체를 그만두므로 이 관측이 요구한 추가 종단 관측은 더 필요 없다. 발주계획→입찰공고 연결은 입찰공고 측 `orderPlanUntyNo`(ADR-0027 결과 절의 76.7%)가 유일 경로다. 겹치지 않는 세 회차(625·1,040·482건) 사이에 같은 통합번호가 다시 나온 경우는 0건이었다(2026-09-18 실측). 대가로 추적 중 발주계획의 `bidNtceNoList`·예산·발주 시기 변경을 관측하지 못하며, 이는 ADR-0061과 [`0918_daily-operation/plan.md` §4](../../0918_daily-operation/plan.md)에 후속 과제로 남겼다.

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

## 암호화된 model-response active object는 stored-byte hash로 검증할 수 없다

- 재현 조건: 암호화된 model-response를 생성해 `ContentObjectLocation(namespace_key='model-response', status='verified')`로 active manifest에 포함한 뒤 복구 검증을 실행한다. `ContentObject.sha256`는 plaintext aggregate의 SHA-256이고 MinIO object bytes는 `BIDOPS-AESGCM-V1\0` envelope와 nonce·ciphertext다.
- 영향: manifest의 model-response hash를 MinIO stored bytes의 SHA-256과 비교하면 정상 복구도 항상 불일치해 검증이 실패한다. 암호화된 payload의 stored-byte 무결성은 현재 DB hash로 입증할 수 없다.
- 남은 제약: verifier는 model-response의 stored-byte hash 비교를 하지 않고 target version에서 object 존재와 version만 확인한다. 다만 DB active 집합 일치, 누락·추가·중복 실패, source→target version mapping 및 target version 존재 검사는 다른 namespace와 동일하게 유지한다.
- 지금 이렇게 두는 이유: 이번 A-6의 목적은 정상 복구를 검증 가능하게 만드는 것이며, 기존 `ContentObject.sha256`의 plaintext 의미와 암호화 저장 경계를 보존해야 한다. 스키마 변경 없이 이 namespace만 예외 처리하는 것이 현재 복구 계약과 fail-closed 집합 검사를 모두 유지하는 방법이다.
- 후속 방향: stored-byte hash를 별도 필드로 기록하는 스키마 보완을 설계·적용해 암호화 envelope도 내용 무결성까지 검증한다. 이는 이번 범위가 아니다.

## legacy mutation 일부가 담당자 이름과 감사 기록 없이 실행된다

- 재현 조건: legacy review upsert, attachment upload·delete, agency portal create·patch, run ingest·subprocess 실행 endpoint를 호출한다.
- 증상: 해당 경로는 `X-BidOps-Actor-Name`을 요구하지 않거나 reviewer가 optional이고, 작업별 `AuditEvent`를 같은 transaction에 남기지 않는다. Lean 문서·심층 검토와 screening control 계열만 별도 actor·audit 경계를 가진다.
- 영향: 사내 사용자가 변경·승인할 때 이름을 남긴다는 채택 결정이 API 전체에서 성립하지 않으며 누가 첨부를 지우거나 포털·리뷰·회차를 바꿨는지 일관되게 추적할 수 없다.
- 상태: **부분 해결** (2026-09-01, A-4). 첨부 upload/delete, agency portal create/patch, screening policy create/candidate/activate에 기존 actor parser와 append-only `AuditEvent`를 적용했다. legacy review와 일부 run/subprocess mutation은 여전히 별도 작업이다.
- 검증: 세 router의 7개 mutation이 actor 없는 요청을 400으로 거부하고, actor가 있으면 같은 transaction에 `AuditEvent`를 남기는 회귀가 통과했다. frontend API 호출부와 포털·정책 화면도 actor header를 전송한다.
- 접근 방법: 새 감사 테이블이나 helper layer를 만들지 않고 기존 `validate_actor`와 `AuditEvent`를 각 mutation transaction에 연결했다. 과거 actor 없는 row는 추정하지 않는다.

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

## 실제 backup·권한·복구 훈련이 없다

- 재현 조건: 운영과 같은 secret·MinIO policy·firewall을 가진 격리 환경에서 PostgreSQL dump와 versioned object backup을 빈 대상에 복구한다.
- 증상: script와 Mock E2E는 있지만 실제 snapshot, object manifest, allow/deny matrix, object → DB → active hash 복구 기록이 없다.
- 영향: RPO·RTO, 최소 권한, 암호화 key 복구, container 재생성 뒤 참조 무결성을 운영 수준으로 주장할 수 없다.
- 지금 해결할 수 없는 이유: 실제 secret manager 주입, 백업 보관 위치, 운영 snapshot, 빈 pre-production target은 저장소 밖의 운영 준비가 필요하다.
- 접근 방법: 운영자가 승인한 복사본으로 역할별 DB 권한, MinIO namespace allow/deny, egress, UID/GID를 검사하고 객체를 먼저 복구한 뒤 DB와 active hash를 대조하는 훈련을 기록한다.

## 운영 백엔드가 `experiments/`를 런타임 의존한다

- 확인: 2026-09-03
- 재현 조건: C-2 실행 경로가 읽는 정책·binding 파일의 위치를 확인한다.
- 증상: `web/backend/app/core/config.py:342,344,346`과 `web/backend/app/screening/ingest.py:1324,1333`이
  `experiments/order-plan-screening/config/order-plan-screening-policy.v1.json`과
  `order-plan-screening-phase0-binding.v1.json`을 읽는다.
  [ADR-0038](../decisions/0038-order-plan-c2-phase0-contracts.md)이 고정한 계약의 정본이
  이름상 실험 보관소인 디렉터리에 있다.
- 영향: 실험 정리가 운영을 깨뜨릴 수 있고, 반대로 운영 때문에 실험 디렉터리를 자유롭게
  정리할 수 없다. 계약 파일의 집이 `skills/bidops-screen/contracts/`,
  `web/backend/app/deep_review/contracts/`, `experiments/.../config/` 세 곳으로 갈려
  새 계약을 어디 둘지 규칙이 없다. 물리적 중복은 없다(md5 대조 확인).
- 지금 해결할 수 없는 이유: 경로를 옮기면 `core/config.py`·`screening/ingest.py`와 실행 중인 회차의
  binding 참조가 함께 바뀌므로 C-2 종단 실행으로 재검증해야 한다.
- 접근 방법: 정책·binding을 `skills/bidops-screen/contracts/`로 승격하고 위 참조 경로를
  갱신한 뒤 C-2 종단 실행으로 확인한다. 계약 파일의 위치 규칙을 `docs/contracts.md`에 적는다.

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

## B-F 설계 승인 baseline과 manifest가 없어 전체 설계 게이트를 완료할 수 없다

- 재현 조건: `web/frontend`에서 `npm run test:design`을 실행하고 `docs/design/mockups/canvas.json`의 14개 artboard와 `tests/design-snapshots/`·manifest-driven `design.spec.ts`를 대조한다. 기존 공통 시각 회귀는 `npx playwright test visual.spec.ts`로 실행한다.
- 증상: PLAN.md §3·§5·§7이 요구하는 14-artboard manifest, 승인된 PNG baseline, fixture·viewport·crop 매핑과 그 변경 승인 기록이 저장소에 없다. 현재 design suite는 shell 차원의 5 passed·3 skipped에 그치며, 기존 visual suite는 현 UI와 맞지 않는 baseline 때문에 204 passed·144 failed로 끝난다.
- 영향: B-F 화면의 기능·반응형·접근성 검증은 가능하지만, 승인된 기준 이미지와 픽셀/crop 일치 여부를 주장할 수 없다. 승인 없이 기존 snapshot을 갱신하면 설계 검수 증거를 덮어쓰게 된다.
- 상태: **차단** (2026-09-03 독립검증). 코드 구현 완료의 차단이 아니라 PLAN 전체 완료 정의에 포함된 승인 설계 자산의 부재다.
- 지금 해결할 수 없는 이유: 14개 artboard의 제품 승인 PNG와 각 fixture·viewport·crop의 승인 메타데이터가 저장소나 현재 요청에 제공되지 않았다. 이를 임의로 생성하거나 기존 baseline을 승인본으로 승격할 권한이 없다.
- 접근 방법: 제품·디자인 담당자가 14개 PNG와 source hash, viewport, fixture, crop, 승인자·승인 시각을 제공하면 `tests/design-snapshots/manifest.json`과 manifest-driven `design.spec.ts`를 추가하고, 기준선 변경은 승인 기록이 있을 때만 갱신한다. 그 뒤 laptop 1280x800·desktop 1440x900 두 폭(ADR-0047)과 접근성 게이트를 다시 실행한다. 2026-09-04 팔레트 전환으로 기준 이미지는 무드보드 v2로 만들어야 하며, 그 선행 조건은 design/PLAN.md(git 이력 docs/design/PLAN.md, 삭제됨) §0-3·0-4다.

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

## 입찰 delta 조회가 runtime 테이블 권한 누락으로 실패한다

- 확인: 2026-09-07, 네 검토 화면 UI 반영 뒤 `http://localhost:18787`의 실제 데이터 확인.
- 재현: `GET /api/opportunities/48/bid-delta` (771·1129도 동일)가 HTTP 500, `processing_failed`를 반환한다. 실행 중인 web의 `app` 세션에서 `SET TRANSACTION READ ONLY` 후 `BidDeltaService.workspace(session, 48)`을 호출하면 `InsufficientPrivilege: permission denied for table bid_delta_comparison`이 발생한다(`services/bid_delta.py`, 비교 목록 SELECT). 세션은 rollback했다.
- 원인 범위: `scripts/runtime-privileges.sql`의 명시적 app/worker allowlist에 `bid_delta_*`·`bid_final_decision`이 없다. 따라서 권한 파일 전체를 다시 실행하는 것만으로 해결되지 않는다. 현재 직접 확인한 첫 실패 테이블은 `bid_delta_comparison`이며 나머지 작업 경로의 권한 충족을 검증한 것은 아니다.
- 영향: 최종 Go/No-Go 목록의 사업명·기관은 표시되지만 비교/결정 상태는 조회 실패로 남는다. UI는 이를 미결정·변경 없음·0건으로 바꾸지 않는다. 계산 worker가 아직 없는 문제와는 별개의 조회 장애다.
- 현재 범위에서 해결하지 않은 이유: 이번 변경은 승인 시안의 프론트엔드 구현과 서버 UI 반영이다. 조회 장애는 DB 역할별 테이블·operation 권한 설계, 격리 PostgreSQL 회귀, 운영 권한 적용이 함께 필요한 백엔드 변경이다. UI 반영 과정에서 임의 blanket grant, migration, 실제 결정 쓰기는 수행하지 않았다.
- 후속: 입찰 delta 조회·비교 생성·attempt 재시도·append-only 최종 결정 경로별 app/worker 권한을 검토해 allowlist와 역할 검사를 추가하고, 기존 결정의 UPDATE/DELETE가 거부되는 것을 확인한 뒤 해당 권한을 적용한다. 실제 API의 정상 조회와 권한 경계를 다시 확인한다.
- 화면 및 검증 증거: `/home/jechoi/design-previews/bidops-ui-implementation-20260907/live/verification.json`.

## v4 PDF snapshot/input bounded 단계 상태 (2026-09-08)

`prespec_v4_pdf_snapshot`와 `prespec_v4_target`의 최소 계약, full page-text/versioned
object binding, worker provenance/options 결속, source namespace generated PDF 저장,
변환 전 snapshot 재사용, canonical explicit-sample identity, heading substring
selector를 isolated storage에서 검증했다. `PrespecV4Attempt` 선행 스키마는 실제
runner 소비자가 없어 보류했다. 운영 DB/MinIO 쓰기·migration 적용·model/UI 인수는
남아 있으며, 기존 `DocumentStructure`·legacy 개요/리뷰는 덮어쓰지 않았다.

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

## 확정 대기 target에 검토 manifest 참조가 결속되지 않는다 (2026-09-10)

- 재현: R7의 `prepare_v4_notice`가 선택기 미결정 시 `bidops.prespec-v4-range-review.v1` manifest를 객체·content row로 저장하지만, `freeze_v4_target`이 ready가 아닌 selection에 manifest 참조를 주면 `manifest_reference_invalid`로 막아 `needs_human_review` target의 `manifest_content_object_id`는 `null`이다.
- 영향: 검토 manifest는 존재하고 후보 개수·digest를 담지만 target 행에서 FK로 따라갈 수 없다. `range_review` 투영은 후보를 snapshot의 산출물 ⑦에서 읽으므로 화면 기능에는 영향이 없다.
- 후속: `freeze_v4_target`에 non-ready selection의 review manifest 참조를 허용하는 분기와 그 검증을 추가한다.
- 종결(2026-09-11): `prespec_v4_target`과 `freeze_v4_target`은
  [ADR-0054](../decisions/0054-prespec-overview-mvp-rewrite.md)로 삭제됐다. 새
  `prespec_overview_run`은 target 테이블을 거치지 않고 자기 행에 직접
  `range_source`·`page_start`·`page_end`·`range_reason_codes`를 두므로 이 문제는 해당 스택
  폐기로 종결됐다.

## 승인된 Qwen 참조 worker의 목적지 제한 미확인 (2026-09-11, 추가 조회 생략 후 참조 실행)

- 재현: 현재 image의 non-root/read-only 임시 컨테이너를 `bidops_model-egress`의 실제 예정 source172.30.0.2에 연결해 TCP만 검사했다. 승인 Qwen192.168.0.139:58765와 불허 외부1.1.1.1:443 모두 연결됐다. host172.30.0.1:22의 connection refused는 방화벽 차단 증거가 아니다. 임시 컨테이너는 제거했다.
- 영향: endpoint allowlist는 있어도 host egress 경계를 충족하지 못한다. 744·749·759·761의 입력·전송 승인은 확인했지만 모델 HTTP·activation·enqueue 전에 중단했으므로 이번 점검의 문서/자격증명 전송·DB 쓰기는0이다. 기존 OFF를 유지했다.
- 원인/후속: 앞선 관리자 스크립트는 첨부 source172.19.0.2만 제한한다. 모델 source의 전용 규칙이 필요하나 `sudo -n`은 password required여서 권한을 우회하지 않았다. 기존 규칙을 보존하는 정확한 source/목적지 전용 적용 스크립트의 구문·비관리자 거부를 확인했다. 관리자 적용 결과와 같은 source의 실제 허용/차단을 확인한 뒤에만 승인4건을 실행한다. 점검·적용 대상 (`../../.dryforge/prespec-qwen-0911-mHF0bO/README.md`, 실행 당시 로컬 산출물·현재 checkout 없음).
- 후속: 관리자 실행은 dedicated_chain_exists로 중단됐고 같은 source의 새 TCP 검사에서 Qwen 허용·외부 연결 거부를 관측했다. 사용자는 추가 체인/연결 규칙 조회를 생략하고 기능을 실행하도록 명시했다. 이번4건만 그 예외로 실행하고 OFF로 종료했다. 기존 방화벽은 변경하지 않았으며 체인 내용까지 검증 완료한 것으로 기록하지 않는다. 상시/다음 운영 배포의 방화벽 검증을 면제하는 일반 정책 변경이 아니다.

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
