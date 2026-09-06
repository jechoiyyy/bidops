# 백엔드 모듈 작업 규칙

## 책임

이 모듈은 FastAPI REST 계약, SQLAlchemy·Alembic, PostgreSQL 정본, MinIO 객체, 회차 적재, 리뷰, 판정 실행, 문서 준비, 심층 검토, 보고서·근거 조회, scheduler와 worker 상태 전이를 소유한다. 원천 수집·판정 스크립트의 업무 규칙과 React 표현은 여기서 복제하지 않는다.

## 모듈 구조

`app/`은 아래 표의 한 방향으로만 의존하는 네 모듈과 그것을 조립하는 얇은 계층이다
([ADR-0045](../../docs/tracking/decisions/0045-backend-module-layout.md)).

```text
app/
├── core/          db, config, logging_setup, redaction, sql_dialect, constants, db_admin,
│                  generation_config, run_id, api_errors, object_store, clamav,
│                  model_client(용도별 통일 transport), company_profile, model_binding,
│                  schema_base, health
│                  models 2개
├── lifecycle/     회차 적재와 기회 identity, 공고·발주계획·사전규격·첨부 메타
│                  api, extensions, ingest/, routers/, services/, schemas/, runtime
│                  models 10개
├── screening/     C-1 공고 판정과 C-2 발주계획 선별
│                  orchestrator/queue/worker/policy/projection/ingest, routers/, services/,
│                  schemas/, workers/order_plan, cli/, runtime
│                  models 28개
├── deep_review/   문서 준비, 사전규격 개요 검토, 심층 검토, 입찰 delta·최종 결정
│                  services/, routers/, workers/, agents/, document_mcp/, contracts/,
│                  policies/, schemas/, cli/, runtime
│                  models 37개
└── main.py, runtime.py, workers/analysis.py, migrations/, alembic/   ← 조립 계층
```

`tests/`도 같은 축이다. `tests/core/`, `tests/lifecycle/`, `tests/screening/`,
`tests/deep_review/`가 각 모듈의 테스트를 갖고, 앱 조립·migration·runtime 계약·**두 모듈
이상이 합쳐지는 통합 검사**는 `tests/app/`이다. `conftest.py`, `postgres.py`,
`c2_fixtures.py`, `fakes/`, `fixtures/`만 `tests/` 루트에 남는다. 새 테스트 파일을 루트에
떨어뜨리면 경계 테스트가 실패한다 — 소유 모듈을 정해 폴더 안에 두라는 뜻이다.

### 의존 규칙

| import 하는 쪽 | 허용 대상 | 금지 |
|---|---|---|
| core | 표준 라이브러리, 외부 패키지 | 모든 도메인 모듈, 조립 계층 |
| lifecycle | core | screening, deep_review, 조립 계층 |
| screening | core, lifecycle 공개 이름 | deep_review, 조립 계층 |
| deep_review | core, lifecycle 공개 이름, screening 공개 이름 중 읽기 전용 seam 함수 | screening 내부 ORM·service, 조립 계층 |
| 조립 계층 | 네 모듈 공개 이름 | 모듈 내부 |

- **공개 이름은 각 모듈 `__init__.py`의 `_EXPORTS` 표에 올린 것뿐이다.** 표는 지연 해석
  (`__getattr__`)이라 패키지 초기화가 아무것도 import하지 않는다. 새 이름을 공개할 때는 표에
  넣고, 모듈 최상위에서 import하지 않는다 — 순환이 생기면 `python -m <모듈>.cli`가 죽는다.
- 조립 계층의 예외는 `alembic/env.py`, migration revision 파일, `app/migrations/import_sqlite.py`
  가 각 모듈의 `models` 하위 모듈을 import하는 것뿐이다. 이 셋만 전체 테이블 집합을 등록한다.
  `init_db(bind)`는 호출자의 import 그래프에 등록된 것만 만든다.
- **lifecycle 모델은 공개 이름이다.** screening·deep_review는 `Notice`·`Run`·`OrderPlan`·
  `Opportunity`·`Attachment` 등을 ORM으로 읽고 join해도 된다. lifecycle 테이블에 **쓰기와
  잠금**만 lifecycle 공개 함수(`ingest_run`, `lock_notice`, `register_manual_attachment` 등)로
  한다.
- deep_review는 screening의 `current_judgment`·`current_judgments`·`latest_corrected_grade`·
  `latest_corrected_grades` **네** seam만 쓰고, 그 import는 **함수 안에서** 한다. 모듈
  최상위에서 들면 screening 폴더 없이 deep_review 테스트가 수집되지 않는다.
  넷째(`latest_corrected_grades`)는 셋째의 batch 짝이며 2026-09-05에 담당자가 승인했다 —
  회차 적재 hot path와 사전규격 목록이 상수 회 조회를 요구하므로 건별 seam만으로는 N+1
  금지와 동시에 성립하지 않는다.
- **ORM relationship도 import다.** lifecycle 모델은 다른 모듈 모델로 향하는 relationship을 갖지
  않는다. 관계는 소유 모듈이 자기 모델에서 단방향으로 선언한다. 삭제 전파는 ORM cascade 대신
  DB FK `ondelete=CASCADE`로 표현한다.

### lifecycle 확장점

역방향이 필요하면 코드를 옮기지 말고 lifecycle이 정의한 확장점으로 뒤집는다.
`app/lifecycle/extensions.py`가 인터페이스와 프로세스 전역 registry를 갖는다.

| 확장점 | 종류 | 구현 | 제공자가 없을 때 |
|---|---|---|---|
| 공고 판정 | 읽기 projection | screening | 필드 `null`, 분포·지표 빈 값. 등급 필터·`sort=grade` 미지원 |
| 사전규격 개요·문서 준비 상태 | 읽기 projection | deep_review | 개요 상태 `null`, 문서 건수 0 |
| 회차 적재됨 | 이벤트 hook | screening, deep_review | no-op, 건수 0 |
| 추적 결정 변경됨 | 이벤트 hook | deep_review | no-op |
| effective grade 변경됨 | 이벤트 hook | deep_review | no-op. 첨부 취득 자격 재계산과 자동 문서 준비가 일어나지 않는다 |

- 등록은 **`main.py`가 앱 객체를 조립할 때** 한다. lifespan이나 `ApplicationRuntime`에 두면
  runtime을 만들지 않는 격리 API 테스트에서 projection이 빈다.
- `notice_ids_for_filters`의 `None`은 "제한하지 않음", 빈 sequence는 "0건 일치"다. 둘을 섞으면
  제공자 없을 때 전체가 사라지거나 그 반대가 된다.
- projection 구현은 호출부가 넘긴 `notice_ids` 만큼을 **상수 회 조회**로 처리한다. 공고당
  조회(N+1)를 만들지 않는다.
- **hook은 자기 실패를 스스로 가둔다.** 여러 모듈이 같은 hook을 등록하므로, 한 hook의 실패가
  형제 hook의 성공 쓰기를 되돌리면 안 된다. 새 회차 적재 hook은 savepoint를 hook 안에 둔다.
  **예외가 하나 있다.** 판정·리뷰 적재 hook(`screening`)은 일부러 격리하지 않는다 — 산출물이
  깨졌으면 회차 적재 전체를 되돌려야 하고, 그것을 경고로 낮추면 회차 계약이 달라진다.
  격리할지 말지는 "이 hook의 실패가 회차를 무효로 만드는가"로 정한다.
- router 등록 **순서는 조립 계층이 소유한다.** `main.py`의 `(모듈, router 이름)` 표를 고친다.
  더 구체적인 경로가 먼저 와야 한다(`/api/runs/{run_id}/pipeline/judgment`가
  `/api/runs/{run_id}/pipeline/{stage}`보다 앞).

### 모듈 선택과 진입점

`BIDOPS_MODULES`는 `lifecycle`·`screening`·`deep_review`의 쉼표 구분 부분집합이고 기본값은 셋
다이다. core는 항상 포함되므로 `/api/health`는 어떤 조합에도 있다. 알 수 없는 이름이나 빈 값은
기동 실패다. **의존은 import만, 등록은 지정 모듈만** — 꺼진 모듈의 경로는 404다.

```bash
python -m app.screening.cli {run-one, score-candidate-quality}
python -m app.deep_review.cli {run-bc-e2e, run-prespec-e2e, import-profile-policy}
python -m app.lifecycle.ingest.cli {--run <회차> | --all}

python -m app.deep_review.workers.document            # 자격증명 없는 문서 worker
python -m app.deep_review.workers.prespec_attachment  # 사전규격 첨부 취득 worker
python -m app.workers.analysis                        # 모델을 쓰는 합성 worker
```

`run-prespec-e2e`는 사전규격 종단 인수 실행이며 격리 실행 경계
(`BIDOPS_TEST_MODE=1` 또는 pytest)에서만 돈다. 자기 workspace의 SQLite와 filesystem 객체
저장소만 쓰고 live 모델·나라장터를 부르지 않으며, 판정 적재 제공자는
`--extension-provider app.screening:register_lifecycle_extensions`처럼 **이름으로** 받는다 —
deep_review가 형제 모듈을 import하지 않기 위해서다. 제공자가 없으면 판정이 0건이므로
`screening_provider_missing`으로 fail closed한다.

모델을 쓰는 C-2 선별·심층 검토·사전규격 개요 worker에 단독 진입점을 만들지 않는다. 합성
worker가 한 바퀴에 C-2 → 심층 → 개요 순서로 **하나만** claim하며, 따로 띄우면 **모델 슬롯
1개** 보장이 깨진다. 개요 attempt lease는 모듈 상수 `OVERVIEW_LEASE_SECONDS=1200`이고
환경변수로 열지 않는다.

## 경계

- 파이프라인은 versioned file과 subprocess로 호출한다. 내부 script 함수를 서비스로 import하거나 같은 판정 규칙을 다시 구현하지 않는다.
- DB row를 그대로 REST 응답으로 노출하지 않는다. 명명된 Pydantic request/response와 안전한 오류 코드를 사용한다.
- 회사 프로필 조회는 승인된 불변 version·digest에 묶인 구조화 항목·`unknown` projection만 반환한다. filesystem source, source line, raw block·raw text, 원문 예외 문자열을 schema에 넣지 않는다.
- frontend가 DB, run 디렉터리, 객체 key를 직접 읽게 하지 않는다.
- model client와 문서 converter에 광범위 DB session이나 임의 filesystem 권한을 주지 않는다.
- 사용자 파일명으로 저장 경로를 만들지 않는다. 허용 namespace, 서버 생성 key, symlink·path escape 검사를 사용한다.

## DB와 실행 불변 조건

- PostgreSQL 17 `bidops` schema가 운영 정본이다. SQLite는 isolated test와 one-time import에만 사용한다.
- 앱 startup은 Alembic head와 필수 storage를 확인할 뿐 migration, `create_all`, policy·portal seed, 활성화를 수행하지 않는다.
- run, policy, profile, document version, model binding, report revision, final opinion은 불변 또는 append-only다. 재실행은 새 ID와 관계를 만든다.
- 리뷰 적재 뒤에는 DB가 정본이다. YAML 재적재로 기존 리뷰를 덮지 않는다.
- `null`, 0, 빈 문자열, 계산 불가를 직렬화나 집계에서 합치지 않는다.
- active screening slot과 analysis concurrency는 1이다. queue는 FIFO이고 stale 실행은 중단으로 닫으며 자동 resume하지 않는다.
- 핵심 식별자·등급·준비 상태가 없는 판정은 적재하지 않는다. 비핵심 과거 누락은 실제 값과 경고만 저장한다.

## 첨부와 심층 검토

- upload는 허용 형식·크기, 서버 생성 key, 악성코드 검사, quarantine, 객체 version을 검증한다. 요청 실패 때 해당 요청이 만든 임시 객체와 DB transaction을 정리한다.
- document bundle confirm은 최신 document version, clean scan, immutable structure snapshot을 같은 fence에서 확인한다.
- document metadata 변경은 notice → latest bundle → document 순서로 잠그고 기대 version과 hash를 재검증한다.
- 심층 검토는 고정 bundle, profile, policy, model reference만 사용한다. live attachment나 변경된 profile을 중간에 다시 읽지 않는다.
- 사전규격 자동 준비는 effective grade가 `우선 검토`인 건만 열고, **자기가 만든 초안만** 확정한다(`confirmed_by_name == "auto-preparation"`). 사람이 만든 초안은 자동으로 확정하지 않는다. 등급이 내려가도 만든 묶음을 되돌리지 않는다([ADR-0049](../../docs/tracking/decisions/0049-prespec-auto-preparation-and-auto-deep-review.md)).
- 자동 준비 상태와 사유는 **저장하지 않는다.** 등급·취득·묶음·개요·심층의 파생값이므로 읽을 때 계산하고, 공고 수와 무관한 상수 회 조회여야 한다. 새 열을 만들지 않는다.
- 자동 심층 시작은 사람 경로와 **같은 함수**(`DeepReviewService.create_review`)를 쓰고 `actor_kind`만 다르다. 별도 생성 경로를 만들면 입력 동결·품질 표식·감사 metadata가 두 벌이 된다.
- 자동 준비·자동 시작의 실패는 촉발한 작업(회차 적재·리뷰 저장)으로 예외를 올리지 않는다. 안전 코드로만 남기고 재시도는 다음 촉발 시점에 한다.
- 문서 segment manifest는 구조 저장 시점의 메모리 payload로만 만든다. append-only이며 `confidence`는 결정적 규칙 결과이므로 언제나 `null`이다. 확률을 지어내지 말고 `needs_human_review` 상태로 남긴다([ADR-0051](../../docs/tracking/decisions/0051-deep-review-v2-deterministic-subset.md)).
- 모델 claims, 숫자, 요구사항, evidence locator는 결정적 schema·근거 검증을 통과해야 한다. 실패는 report에 표시하고 자동 보정하지 않는다.
- model response 객체는 암호화하고 DB에는 key reference, version, hash만 저장한다.

## 접근, 로그, 외부 호출

- 현재 접근 경계는 사내망이며 로그인·role authorization은 없다. 담당자 이름은 mutation 감사 표식이고 인증 성공으로 표현하지 않는다.
- 담당자 이름, prompt, 모델 응답, 공고·회사자료 원문, upload 파일명, credential, DB URL, 쿼리 문자열을 로그에 남기지 않는다.
- 로그 field는 allowlist를 사용하고 외부 예외·subprocess stderr는 저장 전에 redaction한다.
- hosted OpenAI는 운영 기본 비활성이다. 심층 검토 provider는 `vllm`과 `mock`뿐이며 hosted 외부 provider 경로는 제거됐다. 외부 실험은 향후 발주계획 전용 projection에서만 공개 plan metadata와 별도 승인된 최소 회사 역량 요약을 보낼 수 있다. RFP·첨부, profile 전문, evidence, 내부 review·실적은 건별 승인으로도 허용되지 않는다. 허용 projection도 개발 mode, 대상 allowlist, payload preview·승인 중 하나라도 없으면 fail closed한다.
- 모델 호출은 `app/core/model_client.py` 하나를 쓴다. C-1 공고 판정·사전규격 개요·심층 검토가 `screening`·`overview`·`deep_review` 용도로 각각 묶이며, 용도마다 자기 endpoint·허용 host·자격증명·선언 revision을 갖는다([ADR-0050](../../docs/tracking/decisions/0050-unified-openai-compatible-model-client.md)). C-2 발주계획 어댑터만 별도 transport로 남아 있으므로 "유일한 transport"는 앞의 셋에 한정해 읽는다.
- **허용 host가 비었거나 선언 revision이 64자 hex가 아니면 그 용도는 네트워크 호출 전에 fail closed한다.** client를 만든 뒤 검사하지 않는다. 한 용도의 실패를 다른 용도나 다른 provider 자동 fallback으로 처리하지 않는다.
- core에는 고정된 모델명이 없다. 무엇을 부를지는 policy(`model_name`)와 용도별 설정(`BIDOPS_VLLM_SCREENING_MODEL`)이 정한다. 새 모델 상수를 core에 넣지 않는다.
- 응답 schema와 system prompt는 계약을 소유한 도메인 모듈이 `StructuredOutputContract`로 넘긴다. core가 도메인 계약을 알게 만들지 않는다.
- 참조 실행 모드(`BIDOPS_REFERENCE_WORKFLOW_MODE`)의 결과에는 `quality_status` 표식이 붙는다. 표식이 붙은 결과를 운영 완료·품질 근거·활성화 근거로 집계하지 않으며, 표식 없음(`null`)을 미측정이나 측정으로 승격시키지 않는다.

## API와 서비스 구현

- router는 parsing·HTTP mapping만 하고 상태 전이, idempotency, lock, storage 작업은 service에서 처리한다.
- 장시간 변환·모델 작업은 요청 안에서 기다리지 않고 202 execution/attempt와 조회 가능한 상태를 반환한다.
- mutation은 actor, idempotency 또는 기대 version, audit event를 같은 논리 transaction에 묶는다.
- error에는 안정 code와 안전한 message만 두고 내부 path, SQL, model body를 노출하지 않는다.
- 새 schema 의미는 새 version으로 추가한다. 역사 artifact importer의 관대한 처리와 현재 producer의 엄격한 처리를 섞지 않는다.

## 검증

```bash
cd web/backend && .venv/bin/pytest          # 디렉터리 전체. 개별 파일만 지정하면 PostgreSQL 테스트가 skip된다
cd web/backend && .venv/bin/python -m pytest tests/app/test_module_boundaries.py -q
cd web/backend && .venv/bin/python -m pytest tests/app/test_module_selection.py tests/app/test_module_cli_entrypoints.py -q
```

경계는 규율이 아니라 `tests/app/test_module_boundaries.py`의 다섯 검사가 강제한다. 허용 목록
(`tests/app/boundary_allowlist.py`)은 **줄어드는 방향만** 허용한다. 목록에 없는 새 위반은 즉시
실패하고, 목록에 있는데 더 이상 위반이 아닌 항목이 남아 있어도 실패한다.

| 검사 | 대상 | 현재 허용 목록 |
|---|---|---|
| 1. 모듈 간 import 방향 | `app/` 아래 모든 `.py`(조립 계층 포함)와 `tests/<module>/` 아래 모든 `.py` | 0건 |
| 2. router 안의 ORM 접근 | router 파일 | 18건 (service로 내리는 작업을 추적만 한다) |
| 3. schemas → models·services | schema 파일 | 0건 |
| 4. lifecycle 모델의 바깥 방향 relationship | `app/lifecycle/models.py` | 0건 |
| 5. 형제 모듈의 lifecycle 테이블 직접 쓰기·잠금 | `app/screening/**`, `app/deep_review/**` | 0건 |

검사 1은 `tests/app/`을 대상으로 삼지 않는다. 그곳은 두 모듈 이상이 합쳐지는 통합 검사의
자리이기 때문이다. 검사 2·3·4는 `tests/app/`에도 적용된다. 검사 5는 제품 코드(`app/`)만 본다 —
테스트 fixture가 회차·공고 행을 심는 것은 모듈 간 결합이 아니라 검사 대상을 세우는 준비다.

검사 5가 따로 있는 이유: lifecycle **모델 클래스는 공개 이름**이라 검사 1(import 방향)은
`select(Notice)`(허용)와 `session.add(Notice(...))`·`select(Notice).with_for_update()`(금지)를
구분하지 못한다. 읽기·join은 그대로 두고 insert·update·delete·잠금만 잡는다. 필요하면
`lifecycle.lock_notice`·`lock_attachment`·`lock_active_attachments`·`delete_run`·
`register_attachment`·`seed_default_portals` 같은 공개 함수를 쓴다. 없으면 lifecycle에 만든다.

DB 변경은 임시 PostgreSQL 17의 빈 migration, 제약, 중복 적재, rollback을 검사한다. API 변경은 정상과 404/409/422/503, idempotency, 상태 fence, actor encoding, 비밀 없는 오류를 포함한다. 첨부는 형식·크기·path escape·symlink·scan 실패·부분 정리를, 모델·worker는 timeout·잘림·schema·근거 실패·재시도·무승인 외부 호출 차단을 검사한다.
