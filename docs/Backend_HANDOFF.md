# 세션 인수인계

최종 갱신: 2026-09-01

각 절이 가리키는 문서가 정본이다. 이 파일은 **어디를 봐야 하는지**와
**지금 어디에 서 있는지**만 적는다.

---

## 1. 먼저 읽을 것

| 순서 | 문서 | 왜 |
|---|---|---|
| 1 | [`tracking/decisions-pending-20260831.md`](tracking/decisions-pending-20260831.md) | **결정 대기 0건.** D-5~D-11을 2026-08-31에 전부 결정했다. 결정 내용과 근거가 여기 있다 |
| 2 | [`tracking/lifecycle-workstream.md`](tracking/lifecycle-workstream.md) | 작업 목록 정본. 확정된 사실·결정·할 일·끝낸 일 |
| 3 | [`engineering-notes.md`](engineering-notes.md) 마지막 여섯 절 | host 테스트 실행법과 새로 걸린 함정들 |
| 4 | [`tracking/findings.md`](tracking/findings.md) | 재현 가능한 미해결 문제 |
| 5 | [`tracking/status.md`](tracking/status.md)의 구현 상태 표 | **A-1~A-6 여섯 건을 2026-09-01에 전부 해소했다.** 남은 운영 배포 blocker는 MinIO versioning fail-open과 host-wide port publish다. §7의 우선순위가 여기서 나온다 |

바쁘면 **§7(다음 작업 순서)과 §10(콜드 세션 시작 절차)만 읽어도 착수할 수 있다.**

`CLAUDE.md`와 `AGENTS.md`는 내용이 같고 작업 진입점이다. 변경 전에 반드시 읽는다.

---

## 2. 지금 상태

### 테스트 기준선 (2026-09-01 실측)

```
백엔드 전체 완주       1041 passed, 5 skipped, 0 failed   (약 9분)
파이프라인             41 + 13 + 52 + 2 = 108 OK
프론트엔드 전체        598 passed, 10 skipped, 0 failed   (독립 실행 확인)
프론트엔드 빌드        tsc -b 통과, 초기 JS 358.94 kB / gzip 113.10 kB (500 kB 경고 없음)
Alembic                head = 0015_bid_delta_final_decision, alembic check 드리프트 0건
```

**실패 0건이 현재 기준선이다.** 백엔드·프론트엔드 모두 위임과 독립적으로 직접 실행해
확인했다. 예전 문서의 "정상 실패 6건"·"profile_snapshot 2건 실패"는 더 이상 유효하지 않다.

**Playwright 전체 실행에도 부하 의존 flake가 있다.** 2026-09-01 위임 실행이
`route-context.spec.ts` 2건 실패를 보고했으나 같은 트리에서 단독 실행은 84/84, 전체
재실행은 598/598로 통과했다. 전체 실행의 실패는 단독 재실행과 전체 재실행으로 확인한
뒤에만 회귀로 판단한다.

알려진 flake 1건: `test_screening_orchestrator.py::test_retry_attempt_is_persisted_before_success_and_has_no_failed_response`가
전체 실행에서 드물게 실패한다(2회 중 1회). 단독 재실행은 통과한다. 부하 의존이며 회귀가
아니다.

전체 suite는 저장소 `.env`를 상속하지 않은 최소 환경에서 일회용 PostgreSQL 17과 임시
경로를 pytest 수집 전에 구성해 완주했다. skip 5건은 별도 MinIO가 필요한 4건과 target
container 경로 전용 installed-set 1건이다.

### T-23 phase 1과 phase 2 기반 구현을 완료했다

완료: T-1a, T-1b, T-2, T-2b(3점), T-2c, T-3, T-4, T-5, T-7~T-18, T-20, T-21, T-24.
T-23은 [ADR-0033](tracking/decisions/0033-prespec-overview-review-runtime-contract.md)의
phase 1인 clean 문서 선택, 결정적 절단 snapshot, 자동 준비, 안전한 조회 API와 상세 화면을
구현했다. phase 2는 [ADR-0035](tracking/decisions/0035-prespec-overview-attempt-result-lifecycle.md)에
따라 immutable result/event 저장, 제한된 attempt lifecycle service와 안전한 v2 결과 API까지
구현했다. DB는 구조 제약과 상태 전이 trigger 하나만 맡고 audit·scope·review 갱신은 service
transaction이 맡는다. 실제 사설 모델 transport·worker 실행과 승인 binding은 아직 필요하다.
T-19와 선별 제품 구현을 막던 D-6·D-5는 2026-08-31에 해소했다.

### R-08·R-09·R-11과 입찰 delta를 구현했다

`docs/review/2026-08-31-ui-ux-remediation-plan.md`의 R-08(DB·REST), R-09(화면),
R-11(route 분할·시각 기준선)을 완료·검증했다. 입찰 delta 비교와 최종 Go/No-Go의
스키마·API·화면·불변 기록이 있고 revision `0015_bid_delta_final_decision`이 head다.

**delta 계산 worker와 모델 adapter는 아직 없다.** 비교를 생성하면 `pending` comparison과
`queued` attempt만 만들어지고 계산은 일어나지 않으며 화면이 그 사실을 안내한다.

### 발주계획 선별 비교 실험을 끝냈다 (2026-09-01)

**사람 gold가 이미 있다.** 997건 전수 판정이
`data/experiments/order-plan-screening/20260824-20260826-sol200-luna797-xhigh-b100-reference-v1/review/human-gold-full-population.tsv`
에 있다. 실험의 비싼 부분은 이미 끝나 있으니 **다시 라벨링하지 마라.**
모집단 sha256 `3a91dab7…`가 interim-v4~v8에서 모두 같고 gold README와 일치한다.

채점 결과(gold v2 기준, 관련 82/997):

```
검토량      BM25    dense   하이브리드   keyword(기존)   Qwen3.8:27B   Sol·Luna
   50      47.6%   39.0%    50.0%       12.2%          43.3%*        50.0%*
  100      72.0%   58.5%    73.2%       29.3%          72.2%*        97.8%*
  150      81.7%   75.6%    86.6%       48.8%          90.0%*       100.0%*
  300      95.1%   91.5%    97.6%       67.1%         100.0%*       100.0%*
전량 회수   663건   839건    764건       983건          294건*        122건*
                                                        * gold v1 기준
```

**세 가지가 확인됐다.**

1. **하이브리드 가설은 맞았다.** Top-50에서 BM25만 18건, dense만 11건을 잡는다 —
   서로 다른 것을 놓치므로 RRF가 두 단독 arm을 이긴다.
2. **어휘 방식으로는 고recall 운영점을 만들 수 없다.** 중요 누락 0을 원하면 997건 중
   764건을 봐야 한다. 선별의 의미가 거의 없다. Sol·Luna는 Top-150에서 100%다.
3. **키워드 확장은 답이 아니다.** 놓친 40건 중 19건은 이미 규칙에 걸렸는데 순위가
   낮아 잘린 것이라 term을 늘려도 그대로다. 나머지도 절반은 표기 변형
   (`GISDB구축용역` 붙여쓰기, `대쉬보드`)이라 **키워드가 아니라 정규화** 문제다.

Luna 토큰 실측(997건 1회, batch_size 100): 입력 34,563 + 가시 출력 51,140 = **85,703 tok**.
단 `xhigh` reasoning 토큰은 저장되지 않아 못 쟀다. **이 값은 하한이다.**
다음 실행 때 토큰 계측을 켜야 실제 비용을 안다.

### gold 재판정 9건은 아직 제안 상태다

`review/readjudication-20260901.tsv`에 18건을 검토해 9건 변경을 기록하고
`human-gold-full-population-v2.tsv`를 파생했다. **원본 gold는 건드리지 않았다.**
reviewer가 `assistant-recommendation`이므로 **사람 확인 전까지 정본이 아니다.**

- 토목 관로 GIS DB 8건 → 비관련 (회사 실적의 GIS는 재난현장 영상 위치 시각화 연계다)
- AX 디바이스 계열 1건 → `높음`을 `낮음`으로 통일
- 민간발주 7건 → 유지 (적합성과 참여 결정을 서로 대신하지 않는다)

이 재판정이 키워드 규칙의 절반을 좌우한다. `GIS`·`DB`는 v1에서 precision 100%였으나
**v2에서 0%·27%**가 된다. v1의 100%는 토목 8건이 만든 착시였다.

---

---

## 3. 결정 대기 0건 — D-5~D-11을 전부 결정했다

정본은 [`tracking/decisions-pending-20260831.md`](tracking/decisions-pending-20260831.md)다.
**사람 결정을 기다리는 항목은 남아 있지 않다.** 아래는 결정된 내용이고, 이제 남은 것은
실행이다.

### 2026-08-31에 내린 결정

| 항목 | 결정 | 정본 |
|---|---|---|
| D-5 1차 분류 방식 | 실험 승인. arm을 **BM25 · 한국어 dense bi-encoder · RRF 하이브리드** 셋으로 교체하고 ColBERT는 뺀다. LLM arm은 비용 대비 가치로 보류하되 사람 정답은 공유 보존 | [ADR-0021 개정](tracking/decisions/0021-filter-experiment-before-implementation.md) |
| D-6 판정 모델 계보 | `JudgmentRevision → ScreeningExecution`이 정본. 스키마 변경 없이 projection만 추가 | [ADR-0036](tracking/decisions/0036-judgment-model-lineage-source.md) |
| 입찰 delta 문서 role allowlist | baseline `제안요청서·과업지시서·내역서·제출서식` / comparison `공고·정정·제안요청서·과업지시서·내역서·제출서식` | [ADR-0034 확정값](tracking/decisions/0034-bid-delta-final-decision.md) |
| 입찰 delta 범주 정책 | `bid-delta-policy.v1` 7개 확정 | 같은 문서 |
| delta 모델 binding | 승인된 사설 vLLM Qwen3.8:27B 재사용. 새 endpoint 없음 | 같은 문서 |
| 프로필 역사 baseline | commit `ee621835`가 history에 없는 상태를 그대로 둔다. 벤더링 파일이 검증되고 운영은 이미 `current`를 쓴다 | [findings.md](tracking/findings.md) |
| LLM 품질 gate·운영 검증 순서 | LLM 품질 gate 2건은 BM25 실험 뒤로. 운영 검증은 backup·restore만 실험 착수 전에 먼저 | [status.md](tracking/status.md) |
| D-7 G2B egress 방화벽 | 승인 절차만 먼저 올린다. overlay 적용은 D-9 결과를 보고 결정. 열리는 것은 `prespec-attachment-worker` 하나뿐이고 `analysis-worker`(LLM)와 무관하다 | [decisions-pending](tracking/decisions-pending-20260831.md) |
| D-8 21일 재조회 범위 | 종단 관측을 계속 쌓는다. 2026-09-08·09-14가 분기점. 범위 변경은 그 뒤에 판단 | 같은 문서 |
| D-9 첨부 URL 수명 | **측정 완료.** 나이 3~150일 각 30개, 180/180 HTTP 200. 5개월 된 첨부도 그대로 받아진다. 09-13 종단 확인만 남았다 | [validation-run](validation-runs/20260831-prespec-attachment-survival.md) |
| D-10 원문 보존 정책 | 현행 유지. 별도 보존 기간을 만들지 않는다 | `security.md` |
| D-11 PostgreSQL 테스트 | 필수로 만든다. `run-web-tests.sh`/CI에서 강제 | 같은 문서 |

---

## 4. 과거에 찾은 결함 (전부 해결, 재발 방지 테스트 있음)

다시 만들지 마라. 네 건 모두 **"테스트는 초록인데 운영에서 깨진다"** 는 같은 부류였다.

1. **Alembic revision 식별자가 version table 컬럼보다 길었다.**
   `0004`(33자)와 `0006`(39자)이 `VARCHAR(32)`를 넘겨 `alembic upgrade head`가
   PostgreSQL에서 통째로 롤백됐다. **`0004` 이후 어떤 배포도 불가능한 상태였고
   T-7·T-8·T-12·T-16a의 스키마가 정본 저장소에 한 번도 적용된 적이 없었다.**
   → `alembic/env.py`가 version table을 `VARCHAR(64)`로 먼저 만든다.
   폭은 `app.db.ALEMBIC_VERSION_NUM_WIDTH` 한 곳에 있고
   `test_every_revision_identifier_fits_the_version_column`이 강제한다.

2. **PostgreSQL 전용 테스트가 스키마 변경 뒤 갱신되지 않은 채 skip됐다.**
   `test_models_runtime.py`가 `0004`가 없앤 `notice.run_id`에 insert하고 있었다.

3. **legacy 첨부가 객체 식별자를 provenance 자리에 넣었다.**
   12필드 dataclass에 9개를 위치로 넘겨 `object_key`가 `source_system`에 들어갔다.
   MinIO에서 격리 원문을 읽지 못한다. → `kw_only=True`로 재발을 구조적으로 차단.

4. **host에 poppler가 없어 정상 PDF를 손상 판정한다.** (결함이 아니라 측정 함정)

---

## 5. 검증 실행법

### 백엔드

```bash
cd /home/jechoi/projects/bidops/web/backend
.venv/bin/python -m pytest tests/ -q
#   → 1041 passed, 5 skipped (약 9분)
```

10분 넘게 걸리고 `TestClient` 구간에서 멈춘 것처럼 보인다. **기다려라.**
uvloop로 우회할 필요 없다 — 기본 asyncio에서 정상 종료하는 것을 세 번 확인했다.

**개별 파일만 지정하면 PostgreSQL harness가 뜨지 않아 postgres 테스트가 조용히 skip된다.**
`pytest tests/ -k "<패턴>"`으로 디렉터리 전체를 선택해야 Docker `postgres:17.11`이 뜬다.

알려진 flake 1건: `test_screening_orchestrator.py::test_retry_attempt_is_persisted_before_success_and_has_no_failed_response`.
전체 실행에서 드물게 실패하고 단독 재실행은 통과한다. 부하 의존이며 회귀가 아니다.

### 파이프라인

```bash
./run-tests.sh
```

### 프론트엔드

```bash
cd /home/jechoi/projects/bidops/web/frontend
npx tsc -b        # 따로
npm run build     # 따로
```

`npm run build`가 rollup native 모듈 누락으로 깨지면
`npm install @rollup/rollup-linux-x64-gnu --no-save`로 복구한다.

### PostgreSQL (스키마를 바꿨으면 필수)

host에 Docker가 있으면 일회용 서버로 실제 검증할 수 있다.

```bash
docker run -d --rm --name bidops-pg \
  -e POSTGRES_DB=bidops -e POSTGRES_USER=owner -e POSTGRES_PASSWORD=local \
  -p 15499:5432 \
  postgres:17.11@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0 \
  postgres -c search_path=bidops,public

docker exec -e PGPASSWORD=local bidops-pg psql -U owner -d bidops \
  -c "CREATE SCHEMA IF NOT EXISTS bidops;" \
  -c "CREATE ROLE migrate LOGIN PASSWORD 'migratepw';" \
  -c "GRANT USAGE, CREATE ON SCHEMA bidops TO migrate;" \
  -c "GRANT CONNECT, CREATE ON DATABASE bidops TO migrate;" \
  -c "ALTER SCHEMA bidops OWNER TO migrate;"

cd web/backend
BIDOPS_DATABASE_URL="postgresql+psycopg://migrate:migratepw@127.0.0.1:15499/bidops" \
  .venv/bin/python -m alembic upgrade head

# 저장소에 있는 PostgreSQL 테스트 (평소에는 조용히 skip된다)
BIDOPS_TEST_POSTGRES_URL="postgresql+psycopg://owner:local@127.0.0.1:15499/postgres" \
  .venv/bin/python -m pytest tests/test_db_migrations.py tests/test_models_runtime.py -q

docker rm -f bidops-pg
```

`test_integration_t14.py` 8건을 통과시키려면 컨테이너 전용 env가 함께 필요하다.

```bash
BIDOPS_DATABASE_URL=<위 PostgreSQL URL> BIDOPS_ROOT=/home/jechoi/projects/bidops \
BIDOPS_DATA_DIR=<임시> BIDOPS_ATTACHMENTS_DIR=<임시> \
  .venv/bin/python -m pytest tests/test_integration_t14.py -q
```

### 발주계획 선별 실험

```bash
cd /home/jechoi/projects/bidops
python3 experiments/order-plan-screening/scripts/score_arms.py \
  --run-dir data/experiments/order-plan-screening/20260824-20260826-interim-v8 \
  --gold data/experiments/order-plan-screening/20260824-20260826-sol200-luna797-xhigh-b100-reference-v1/review/human-gold-full-population.tsv
#   BM25를 그 자리에서 돌리고, 저장된 dense 결과와 RRF로 합쳐 gold로 채점한다
#   --gold 를 human-gold-full-population-v2.tsv 로 바꾸면 재판정본 기준이 된다

python3 -m pytest experiments/order-plan-screening/tests/ -q   # 32 passed
```

**`config/methods.json`에 method를 추가하지 마라.** `common.load_methods_config()`가
`set(config["methods"]) == set(METHOD_NAMES)` 닫힌 집합을 요구해서 기존 6-method 실행이
전부 깨진다. BM25 설정을 `config/bm25.json`으로 분리해 둔 이유다. 방식이 선택되면
그때 `METHOD_NAMES`까지 함께 올린다.

토큰 계측과 PDF 추출에는 `tiktoken`·`pypdf`가 필요하다. `web/backend/.venv`에는 없다.

### 문서 파이프라인 측정

**host가 아니라 런타임 이미지 안에서 한다.** host에는 poppler가 없어 정상 PDF가
`malformed_pdf`로 거부된다.

```bash
docker run --rm --network none -u "$(id -u):$(id -g)" \
  -e PYTHONPATH=/app/web/backend -v "<표본>:/data" -w /app/web/backend \
  bidops-mock-t7-web:latest python /data/<script>.py /data
```

HWP 변환기는 반대로 host에서도 동작한다(Node + 벤더링된 `app/document_mcp/vendor/rhwp`).

---

## 6. codex 위임

```bash
cx exec -m gpt-5.6-luna -c model_reasoning_effort="max" \
  "$(cat <프롬프트파일>)" < /dev/null > <로그파일> 2>&1
```

`cx` = `codex --dangerously-bypass-approvals-and-sandbox`.
**`sandbox_mode="workspace-write"`를 쓰면 안 된다.** Docker를 막아 postgres 테스트가
조용히 skip되고, port 4173 bind가 `EPERM`으로 죽어 Playwright를 못 돌린다.
위임한 검증이 통과했다는 보고를 그대로 믿으면 안 되는 이유다.

### 이번 세션에 겪은 실패 세 가지

전부 **성공한 것처럼 보이는** 실패였다.

- **`&`로 배경 실행하면 셸만 즉시 반환한다.** 프로세스는 계속 돈다. 죽은 줄 알고
  다시 띄우면 **두 codex가 같은 파일을 동시에 고친다.** 실제로 겪었다.
  재실행 전에 `pgrep -af "codex exec"`로 확인한다.
- **작업 디렉터리가 sandbox 쓰기 범위를 정한다.** 하위 디렉터리에서 띄우면
  저장소 루트의 문서와 다른 모듈을 못 고치고 중단한다. 셸 작업 디렉터리는 호출 사이에
  유지되므로 **실행 직전에 `pwd`로 확인한다.**
- **전체 스위트를 "환경 문제"로 단정한다.** 세 번의 위임 모두 `TestClient` 정체를
  보고했지만 직접 돌리면 정상이었다.

### 검수 원칙

**완료 보고를 근거로 쓰지 않는다.** 전체 스위트를 직접 돌리고 바뀐 파일을 직접 읽는다.
이번 세션에서 codex가 T-24 범위 밖의 fail-closed 가드(worker의 object-store 검증)를
조용히 삭제한 것을 그렇게 잡았다.

---

## 7. 다음 작업 순서

**결정은 다 끝났고 남은 것은 실행이다.** 아래는 우선순위 순이다. 위에서부터 집으면 된다.
각 항목에 크기와 막는 것을 적었다.

| 순위 | 항목 | 크기 | 성격 |
|---|---|---|---|
| 1 | C-2 선별 방식 선택 · C-1 gold 재판정 확인 · D-7 방화벽 승인 상신 | — | **사람 몫.** 지금 던져두면 병렬로 돈다 |
| 2 | MinIO versioning fail-open · host-wide port publish · 테스트 harness | 작음 | 운영 배포 blocker의 마지막 |
| 3 | 입찰 delta worker · T-23 worker · 재시작 화면 · T-19 projection | 중간 | 껍데기를 도는 기능으로 |
| 4 | LLM 품질 gate 2건 · screening v3 renderer 연결 | 중간 | 판정을 믿을 수 있게 |
| 5 | 선별 제품 구현 (수집 회차·관계·일일 수집·delta 추적) | 큼 | **C-2 결정 뒤에만** |
| 6 | 실제 운영 검증 · API 증액 근거 · SSO·권한·알림 | 큼 | 이후 범위 |

**어디부터 집을지 갈리면 이 기준을 쓴다.** 당장 운영 배포 계획이 있으면 2번이 먼저다
(작아서 미룰 이유가 없고 끝나면 blocker가 0이 된다). 배포 계획이 없으면 3번이 먼저다
(제품 체감이 가장 크게 바뀐다).

### 1. 사람 몫 — 지금 던져두면 병렬로 돈다

리드타임이 있으므로 다른 무엇보다 먼저 시작한다. **C-2 하나가 5번 전체를 막고 있다.**

```
C-2  방식 선택 (아래 셋 중)                ← 비용 대 누락의 교환. 토큰 실측은 §2에 있다
       (a) 하이브리드 상위 300 → LLM 재순위   recall 97.6% 유지, LLM 호출 70% 절감
       (b) Qwen 단독                        전량 회수 294건, 외부 전송 없음
       (c) 하이브리드 단독 + 검토량 300      모델 비용 0, 3일마다 300건 사람 검토
C-1  gold 재판정 9건 확인                  ← 이게 있어야 v2가 정본이 된다
D-7  방화벽 승인 상신                      ← prespec-attachment-worker 하나가 g2b:443으로
                                             나가는 것. analysis-worker(LLM)와 무관하다
```

D-7 overlay 적용은 승인 뒤에 하고, 그 다음이 T-20 운영 활성화다.

### 2. 남은 운영 배포 blocker — 작고 기반이다

`findings.md`에 재현 조건이 있다. **이 둘을 닫으면 운영 배포 blocker가 0이 된다.**

| | 항목 | 크기 | 왜 지금 |
|---|---|---|---|
| 2-1 | **MinIO versioning fail-open** | 작음 | `scripts/minio-init.sh:22`의 `mc version enable ... \|\| true`가 모든 실패를 삼킨다. versioning이 꺼져 있어도 init이 성공한다. **2026-09-01에 만든 A-6 복구 계약이 version 불변성 전제 위에 서 있으므로 이것이 먼저다** |
| 2-2 | **host-wide port publish** | 작음 | `docker-compose.t7.yml`의 PostgreSQL·MinIO API·console port mapping에 host IP가 없어 LAN에서 직접 접근할 수 있다. 애플리케이션 API만 쓰는 접근 경계를 우회한다 |
| 2-3 | **테스트 harness 고정** (D-11) | 작음~중간 | **`run-web-tests.sh`도 CI도 아직 없다.** 개별 파일만 지정하면 postgres 테스트가 조용히 skip되는 함정이 살아 있고, 이 저장소는 같은 부류 결함에 두 번 데였다(§4의 1·2번) |

### 3. 껍데기를 실제로 도는 기능으로

전부 결정이 끝나 막는 것이 없다. B-3·B-4의 모델 binding은 승인된 사설 vLLM Qwen3.8:27B
재사용으로 확정됐다. 새 endpoint를 열지 않으며 `resolve_runtime_binding()`이 없으면
503으로 fail-closed한다.

| | 항목 | 근거 | 지금 상태 |
|---|---|---|---|
| B-3 | **입찰 delta 계산 worker와 모델 adapter** | [ADR-0034](tracking/decisions/0034-bid-delta-final-decision.md) | 스키마·API·화면·불변기록이 전부 있는데 계산만 안 일어난다. 비교를 만들면 `pending` comparison과 `queued` attempt만 생긴다 |
| B-4 | **T-23 사전규격 개요 model adapter·worker** | [ADR-0033](tracking/decisions/0033-prespec-overview-review-runtime-contract.md)·[0035](tracking/decisions/0035-prespec-overview-attempt-result-lifecycle.md) | 같은 구조. 이것으로 사전규격 검토가 Mock이 아닌 실제 모델로 돈다 |
| B-5 | 문서 준비·실패 attempt 재시작 화면 | typed API는 있음 | 화면 연결만 |
| B-2 | T-19 판정 모델 계보 projection | [ADR-0036](tracking/decisions/0036-judgment-model-lineage-source.md) | 스키마 변경 없이 API·화면만 |

**B-3과 B-4가 "코드는 있는데 안 돎"을 없애는 가장 큰 한 방이다.**

### 4. 판정을 믿을 수 있게

지금은 "코드가 돈다"만 있고 "판정을 믿을 수 있다"가 없다. 심층 검토는 deterministic Mock
provider로만 검증됐고 1차 판정도 40건 운영 품질 승인이 없다.

- LLM 품질 gate 2건 — 1차 판정 40건, 심층 검토 Qwen. 실제 model artifact digest와
  대표 HWP/PDF gold, 사람 판정이 필요하다.
- screening v3를 보고서 renderer에 명시적으로 연결한다.

### 5. 선별 제품 — C-2 결정 뒤에만 착수

C-2가 정해지기 전에 시작하면 버리는 작업이 된다. 의존 순서대로다.

```
5-1  threshold 확정
5-2  전체 발주계획 원본과 방식별 결과를 저장하는 불변 수집 회차·DB 계약
5-3  내부 opportunity와 plan·pre-spec·bid 공식 관계, 사람 확인 대기 relation 후보
5-4  사전규격 독립 일일 수집, 저비용 1차선별, 사람 심층 검토 승인 gate 연결
5-5  계속 추적|보류|종료, 입찰공고 발견, 사전규격 대비 material delta, 최종 사람 Go/No-Go
```

### 6. 이후 범위

- 실제 secret, MinIO allow/deny, egress firewall, PostgreSQL·객체 backup과 빈 대상 restore를
  **운영 환경에서** 검증한다. 스크립트 결함은 2026-09-01에 고쳤고 disposable 환경 검증까지
  했으나 운영 훈련은 아직 없다.
- 개발계정 API 요청 수를 실측하고 운영계정 활용사례·증액 근거를 준비한다.
- SSO·역할 권한과 dashboard·외부 알림을 설계한다. **현재 애플리케이션에는 로그인과 역할
  기반 권한이 없고 사내망 접근 제한이 유일한 경계다.**

### 2026-09-01에 끝낸 것 — 운영 배포 blocker A-1~A-6

여섯 건 모두 착수 전에 현재 코드로 재확인했고 실재했다. 각 건마다 위임 뒤 전체 스위트를
위임과 독립적으로 직접 실행해 확인했다.

| | 항목 | 결과 | 커밋 |
|---|---|---|---|
| A-1 | runtime image가 회사자료를 포함한다 | 해결. `docs/reference` bulk copy, 회사 실적 제목 TSV, `app/screening/baseline_company_profile.md` 세 경로를 build context에서 막고 `web`에 read-only bind mount로 주입한다 | `ed78d93`·`0bdbab1` |
| A-2 | legacy 첨부가 scan·quarantine·MinIO를 우회 | 해결. quarantine→MIME·구조·ClamAV→`safe`만 등록, `stored_path` 응답 제거, `web-data` volume | `2517078` |
| A-3 | 프로필 projection이 원문·경로를 노출 | 해결. ADR-0023의 최소 projection. 승인 snapshot에 고정하고 닫힌 오류 코드로 fail closed | `a0b34db` |
| A-4 | legacy mutation에 actor·audit 없음 | 해결. 첨부·포털·정책 7개 mutation에 actor 검증과 `AuditEvent` | `2517078` |
| A-5 | hosted Codex가 허용 payload 정책과 충돌 | 해결. 닫힌 allowlist 밖 필드·프로필·prior stage는 prompt 생성 전에 fail-closed | `ed78d93` |
| A-6 | backup·restore의 version mapping·manifest 결함 | 해결. target version mapping 기록, DB에서 active manifest 생성, 집합 일대일 대조 | `6eeebd6` |

**착수하기 전에 알아야 할 것 셋.**

1. **`docker-compose.t7.yml`이 배포 입력을 요구한다.** 회사 프로필·실적 TSV·벤더링 baseline
   세 파일은 이미지에 없고 host checkout에서 read-only로 주입된다. 파일이 없으면 Docker가
   그 자리에 **디렉터리를 만들어** 이상하게 실패한다. 확인 명령은 `operations.md`에 있다.
2. **프로필 화면은 승인 snapshot이 있어야 뜬다.** snapshot이 하나도 없으면
   `/api/profile/sections`가 `503 profile_snapshot_unavailable`로 fail closed한다. 정상이다.
   snapshot은 판정 실행이 만들므로 신규 배포에서는 회차 판정을 한 번 돌린 뒤에 쓴다.
3. **암호화 model-response는 stored-byte hash로 검증하지 않는다.** `ContentObject.sha256`이
   plaintext 해시라 비교가 성립하지 않는다. 존재·target version·집합 대조는 유지한다.
   설계상 남은 제약이며 `findings.md`에 후속 방향과 함께 있다.

### 날짜가 정해진 관측 (기록)

사람이 확인했다. 우선순위 항목이 아니라 시점 기록이다. 놓치면 그 지점은 다시 못 잰다.

- **2026-09-08 · 09-14**: T-2b 종단 관측. 나이 15일·21일이 ADR-0027의 21일 재조회 범위
  판단 분기점이다. 명령은
  [validation-run](validation-runs/20260831-order-plan-longitudinal.md) 마지막 절.
- **2026-09-13**: D-9 종단 확인. 2026-08-30 표본 30건 URL 재호출. 횡단면은 이미 쟀다 —
  나이 3~150일 **180/180 생존**
  ([survival](validation-runs/20260831-prespec-attachment-survival.md)). 종단은 **URL 회전**을
  본다. 횡단면이 답하지 못하는 유일한 질문이다.

---

## 8. 이번 범위가 아닌 것

- 자동 입찰 제출, 발주처 연락, 모델의 최종 참여 결정은 이 제품이 하지 않는다.
- hosted OpenAI 자동 fallback과 scheduler·always-on 자동 활성화는
  선별 방식·threshold 승인 전에는 넣지 않는다.
  (입찰 delta 계산 worker는 더 이상 범위 밖이 아니다. §7의 3번으로 착수 가능하다.)
- SSO·역할 권한·알림은 [`tracking/status.md`](tracking/status.md)의 14번 이후다.
- 현재 애플리케이션에는 로그인과 역할 기반 권한이 없다. 사내망 접근 제한이 경계이고
  담당자 이름은 감사 표식일 뿐 인증이 아니다.

---

## 9. 작업 트리 주의

**커밋되지 않은 변경이 많다.** 2026-09-01 기준 `git status --porcelain`이 173개다.
`main`의 마지막 커밋은 `84bbcc5 feat(db): harden lifecycle persistence and postgres harness`이고,
그 이후 작업은 전부 작업 트리에만 있다.

커밋 안 된 주요 산출물:

```
입찰 delta (R-08·R-09)
  web/backend/app/{services,routers,schemas}/bid_delta.py
  web/backend/alembic/versions/0015_bid_delta_final_decision.py
  web/backend/tests/test_bid_delta_{api,models,postgres}.py
  web/frontend/src/pages/BidDeltaDecisionPage.tsx, components/bid-delta/, styles/bid-delta-decision.css
  web/frontend/tests/bid-delta.spec.ts + visual 스냅샷

route 분할 (R-11)
  web/frontend/src/components/common/LazyRouteBoundary.tsx, routes.tsx

T-23 사전규격 overview phase 2
  web/backend/app/services/prespec_overview.py, schemas/pre_specs.py, models.py
  alembic/versions/0014_prespec_overview_attempt_result.py

선별 실험 (2026-09-01)
  experiments/order-plan-screening/scripts/{methods.py 의 BM25Adapter, score_arms.py}
  experiments/order-plan-screening/config/bm25.json
  experiments/lifecycle-linkage-survey/scripts/prespec_attachment_survival.py
  data/experiments/prespec-attachment-survival/20260831/survival.json
  .../review/{readjudication-20260901.tsv, human-gold-full-population-v2.tsv}

문서
  docs/Backend_HANDOFF.md(이 파일, 신규), contracts.md, tracking/{status,findings,
  lifecycle-workstream,decisions-pending-20260831}.md, decisions/{0021,0034,index}.md,
  decisions/0036-judgment-model-lineage-source.md(신규),
  validation-runs/20260831-prespec-attachment-survival.md(신규)
```

`docs/HANDOFF.md`가 삭제로 잡히는 것은 이 파일로 이름을 바꿨기 때문이다. 정상이다.

**`data/experiments/`는 `.gitignore`가 제외하지 않는다.** 원문 API 페이지가 커밋에 들어간다.
`--from-raw`로 재생성할 수 있으므로 저장소 크기가 문제되면 제외를 검토하라. 다만 실험
재현성의 근거이므로 지우기 전에 ADR-0021의 보존 요구를 확인해야 한다.

---

## 10. 콜드 세션 시작 절차

1. `CLAUDE.md`와 이 파일을 읽는다.
2. §7의 우선순위 표에서 집을 항목을 고른다. **1번(사람 몫)은 먼저 던져두면 병렬로 돈다.**
   당장 운영 배포 계획이 있으면 2번, 없으면 3번부터 집는다.
3. 착수 전에 `status.md`의 해당 행을 현재 코드로 **직접 다시 확인한다.**
   기록이 맞을 수도, 이미 고쳐졌을 수도 있다. 2026-09-01에는 A-1~A-6 여섯 건이 전부 맞았고,
   그 중 A-1은 기록보다 누출 경로가 둘 더 있었다.
4. 변경 전에 §5로 기준선을 잡는다. **실패 0건이 현재 기준선이다.**
5. 위임하면 §6의 검수 원칙을 지킨다 — 완료 보고를 근거로 쓰지 않는다.
