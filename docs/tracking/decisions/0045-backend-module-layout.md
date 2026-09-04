# 백엔드를 core·lifecycle·screening·deep_review 네 모듈과 조립 계층으로 배치한다

- 상태: 채택
- 일자: 2026-09-04

## 맥락

[ADR-0043](0043-screening-deep-review-module-boundary.md)이 선별과 심층 검토를 "한 배포 단위
안에서 서로를 import하지 않는 두 모듈"로 채택했다. 그 결정을 `web/backend/app/` 전체에
적용하려 하자 두 모듈로는 덮이지 않는 자리가 드러났다.

- ADR-0043이 분류한 테이블은 42개인데 실제 declarative 테이블은 **74개**다. 나머지는 선별도
  심층도 아닌 **기회 생애주기**(회차·공고·발주계획·사업기회·첨부 메타) 도메인이며, 이것을
  core에 넣으면 core가 다시 거대 공용 폴더가 된다.
- ADR-0043은 선별↔심층 교차 import만 다뤘다. 실측에서는 `db`·`models`·`schemas`가 도메인
  모듈을 import하는 **역방향** 의존과 `services`↔`ingest`, `services`↔`workers` 순환이 있어
  폴더만 옮기면 순환이 따라온다.
- 생애주기 화면이 선별·심층의 결과를 함께 보여 준다. `GET /api/notices`의 등급 필터·정렬은
  SQL join이고 `GET /api/pre-specs`는 개요 검토 상태를 투영한다. 두 모듈을 단순히 갈라 두면
  그 방향이 그대로 역방향 의존이 된다.

이 결정은 그 세 가지를 닫는다. `docs/backend-modules/design.md`가 설계 근거와 소유권 지도를
갖고, 이 ADR은 그중 확정된 것과 실행 중에 바뀐 것을 기록한다.

## 결정

### 1. 네 모듈과 조립 계층

```text
web/backend/app/
├── core/          db, config, logging_setup, redaction, sql_dialect, constants, db_admin,
│                  generation_config, run_id, api_errors, object_store, clamav,
│                  vllm_client(범용), company_profile, model_binding, schema_base, health
│                  models: audit_event, idempotency_record (2)
├── lifecycle/     회차 적재와 기회 identity, 공고·발주계획·사전규격·첨부 메타
│                  api, extensions, ingest/, routers/, services/, schemas/, runtime
│                  models: 10
├── screening/     C-1 공고 판정과 C-2 발주계획 선별
│                  orchestrator/queue/worker/policy/projection/ingest, routers/, services/,
│                  schemas/, workers/order_plan, cli/, runtime
│                  models: 28
├── deep_review/   문서 준비, 사전규격 개요 검토, 심층 검토, 입찰 delta·최종 결정
│                  services/, routers/, workers/, agents/, document_mcp/, contracts/,
│                  policies/, schemas/, cli/, runtime
│                  models: 34
└── main.py, runtime.py, workers/analysis.py, migrations/, alembic/   ← 조립 계층
```

조립 계층은 네 모듈의 **공개 이름**(`__init__.py`에 올린 것)만 import하고 모듈 내부 경로를
import하지 않는다. 예외는 `alembic/env.py`와 migration revision 파일, 그리고
`app/migrations/import_sqlite.py`가 각 모듈의 `models` 하위 모듈을 import하는 것이다.

### 2. 의존 규칙

| import 하는 쪽 | 허용 대상 | 금지 |
|---|---|---|
| core | 표준 라이브러리, 외부 패키지 | 모든 도메인 모듈, 조립 계층 |
| lifecycle | core | screening, deep_review, 조립 계층 |
| screening | core, lifecycle 공개 이름 | deep_review, 조립 계층 |
| deep_review | core, lifecycle 공개 이름, screening 공개 이름 중 읽기 전용 seam 함수 | screening 내부 ORM·service, 조립 계층 |
| 조립 계층 | 네 모듈 공개 이름 (+ alembic·`import_sqlite`는 `models`) | 모듈 내부 |

세부 규칙은 넷이다.

- **lifecycle의 모델 클래스는 공개 이름이다.** screening·deep_review는 `lifecycle.models`의
  `Notice`·`Run`·`OrderPlan`·`Opportunity`·`Attachment` 등을 ORM으로 읽고 join해도 된다.
  lifecycle 테이블에 **쓰기와 잠금**만 lifecycle 공개 함수로 한다(`ingest_run`,
  `lock_notice`, `register_manual_attachment` 등).
- **screening의 내부는 deep_review에 공개하지 않는다.** deep_review는 screening이
  `__init__.py`에 올린 읽기 전용 seam 함수 `current_judgment`·`current_judgments`·
  `latest_corrected_grade`만 쓴다.
- **ORM relationship도 import다.** lifecycle 모델은 다른 모듈 모델로 향하는 relationship을
  갖지 않는다. 관계는 소유 모듈이 자기 모델에서 단방향으로 선언한다. 그래야 어느 모듈을
  import하지 않아도 mapper 구성이 성공한다. 첨부 삭제 시 `attachment_fetch` 행 제거는 ORM
  cascade 대신 DB FK `ondelete=CASCADE`가 맡는다.
- **역방향이 필요한 자리는 lifecycle이 정의한 확장점으로 뒤집는다.** lifecycle은 screening과
  deep_review의 존재를 알지 못한다.

### 3. lifecycle 확장점

`app/lifecycle/extensions.py`가 인터페이스와 프로세스 전역 registry를 정의한다.

- 읽기 **projection**: 공고 판정 projection(screening 구현), 사전규격 개요·문서
  projection(deep_review 구현). 등록이 없으면 목록·상세가 그 필드를 `null`(또는 계약이
  `null`을 허용하지 않는 정수 필드는 0)로 채우고, 그 필드에 기대는 동작은 no-op이 된다.
  `notice_ids_for_filters`의 `None`은 "제한하지 않음", 빈 sequence는 "0건 일치"로 구분한다.
- 이벤트 **hook**: 회차 적재됨, 추적 결정 변경됨. 등록이 없으면 no-op이고 건수는 0이다.
- 등록은 **`main.py`의 앱 조립 시점**이다. lifespan이나 `ApplicationRuntime`이 아니다 —
  거기 두면 runtime을 만들지 않는 격리 API 테스트에서 projection이 비게 된다.
- 등록은 import와 객체 생성뿐이다. migration·seed·정책 활성화·모델 호출을 하지 않는다.

### 4. 첨부 취득은 deep_review가 소유한다

첨부 **메타**(`attachment` 테이블)의 쓰기는 lifecycle이 소유하고, 취득 큐·lease·결과
(`attachment_fetch`)와 그 뒤의 문서 흐름은 deep_review가 소유한다. deep_review는
`lifecycle.register_manual_attachment` 같은 공개 함수로 메타를 쓴다.

### 5. 합성 worker를 유지한다

모델을 쓰는 심층 검토·C-2 선별 worker는 `app/workers/analysis.py` 한 프로세스가 계속
합성한다. 실행 가능한 worker 진입점은 다음 셋이다.

```bash
python -m app.deep_review.workers.document           # 자격증명 없는 문서 worker
python -m app.deep_review.workers.prespec_attachment # 사전규격 첨부 취득 worker
python -m app.workers.analysis                       # 모델을 쓰는 합성 worker (슬롯 1개)
```

`app.deep_review.workers.deep_review`와 `app.screening.workers.order_plan`에는 단독 진입점을
두지 않는다. 두 파일은 이주 전부터 `__main__`이 없었고 둘 다 모델을 쓴다. 단독으로 띄울 수
있게 하면 운영자가 합성 worker와 동시에 실행해 **모델 슬롯 1개** 보장을 깰 수 있다.

CLI 진입점은 모듈별로 하나씩이다.

```bash
python -m app.screening.cli {run-one, score-candidate-quality}
python -m app.deep_review.cli {run-bc-e2e, import-profile-policy}
python -m app.lifecycle.ingest.cli {--run <회차> | --all}
```

### 6. `BIDOPS_MODULES` — 의존은 import만, 등록은 지정 모듈만

`BIDOPS_MODULES`는 `lifecycle`·`screening`·`deep_review`의 쉼표 구분 부분집합이고 기본값은
셋 다이다. core는 선택 대상이 아니라 항상 포함되므로 `/api/health`는 어떤 조합에도 있다.
**알 수 없는 이름이나 빈 값은 기동 실패**(fail closed)다. 조용히 기본값으로 되돌아가면
무엇이 등록됐는지 설정만 보고 알 수 없기 때문이다.

지정한 모듈이 의존하는 모듈의 `models`·seam은 **import되어 동작하지만**, router·runtime·확장점
등록은 **지정한 모듈에만** 한다. 따라서 `BIDOPS_MODULES=deep_review`면 `/api/health`와
deep_review 경로만 있고 lifecycle·screening 경로는 404다.

router 등록 **순서는 조립 계층이 소유한다.** `main.py`가 `(모듈, router 이름)`의 순서 있는
표를 갖고 지정되지 않은 모듈의 항목만 건너뛴다. 모듈별로 묶어서 이어 붙이지 않는다 —
screening의 `POST /api/runs/{run_id}/pipeline/judgment`가 lifecycle의
`/api/runs/{run_id}/pipeline/{stage}`보다 먼저 등록돼야 더 구체적인 경로가 선택된다.
모듈이 router를 소유하고, 순서는 조립이 소유한다.

### 7. "개별로 사용 가능"의 기준 6은 네 모듈에 적용한다

각 모듈의 테스트가 상대 모듈 폴더 없이도 수집·통과해야 한다는 기준을 lifecycle을 포함한 네
모듈 모두에 적용한다. 선별에 의존하는 테스트는 `tests/screening/` 또는 `tests/app/`에 둔다.

### 8. 범위 밖과 제거

- **`experiments/` 런타임 의존은 이 결정의 범위 밖이다.** 경로를 그대로 두고 파일만 옮겼다.
  C-2 stage 2 진행 작업과 겹치며, 경계 테스트도 이 의존은 검사하지 않는다.
- **hosted codex provider는 파일·테스트가 아니라 provider 전체를 제거했다.** 설정·overlay·
  분기만 남으면 죽은 경로가 된다. 남는 심층 검토 provider는 `vllm`과 `mock`뿐이다.

## 대안과 기각 이유

| 항목 | 기각한 안 | 채택 | 이유 |
|---|---|---|---|
| lifecycle이 선별·심층 결과를 보여 주는 방법 | 프론트엔드가 두 API를 합성 | lifecycle 확장점(projection + hook) | REST 계약·프론트엔드·Playwright 화면 회귀를 바꾸지 않는다. 목록의 등급 필터·정렬이 SQL join이라 프론트 합성으로는 계약이 유지되지 않는다 |
| 첨부 취득 소유 | lifecycle | deep_review | `attachment_fetch → document_version` FK와 fetch 완료 시 구조화·개요 준비 호출이 lifecycle→deep_review 역방향을 만든다 |
| `prespec_overview_review` 소유 | (확인 대상) | deep_review | 쓰기 주체가 하나이고 화면 표시는 projection이 맡는다 |
| analysis worker | 폐지하고 Compose는 모듈 worker 둘로 | 모듈 진입점 신설 + 합성 진입점 유지 | 모델 슬롯 1개 보장과 Compose·overlay·runtime contract 테스트를 유지한다 |
| `experiments/` 런타임 의존 | 이주하면서 함께 끊는다 | 범위 밖. 경로 그대로 파일만 이동 | C-2 stage 2 진행 작업과 겹친다 |
| 타 모듈 작업뿐인 endpoint | (언급 없음) | 소유 모듈 router가 같은 경로를 제공 | `routers/reviews.py`의 기존 방식과 같다. 모듈이 없으면 404 |
| `BIDOPS_MODULES` 의존 처리 | 의존 모듈까지 등록 | 의존은 import만, router·runtime은 지정 모듈만 | 단독 기동 검증이 그대로 성립한다 |
| `attachment` 쓰기 | (언급 없음) | lifecycle 소유, deep_review는 공개 함수로 쓴다 | 회차 적재가 deep_review 없이도 첨부 메타를 기록해야 한다 |
| 입찰 delta·최종 결정 | lifecycle | deep_review (테이블 5·서비스·router·schema) | `services/bid_delta.py`가 확정 문서본을 조회·잠그고 `bid_final_decision`이 `document_version`을 참조한다 |
| lifecycle 모델 읽기 | lifecycle만 읽는다 | screening·deep_review도 ORM으로 읽고 join한다. 쓰기·잠금만 공개 함수 | 허용 방향의 직접 조회가 약 100곳이며 seam 함수로 대체할 이유가 없다 |
| C-2 선별 결과 적재 | lifecycle의 loader가 계속 적재 | screening의 회차 적재 hook | screening 테이블 6개를 쓰는 코드는 screening 소유다 |
| 기준 6의 범위 | 선별·심층 두 모듈 | lifecycle 포함 네 모듈 | 문면대로 적용한다 |
| codex 삭제 범위 | 파일·테스트만 | provider 전체 | 설정·overlay·분기만 남으면 죽은 경로가 된다 |
| `vllm_client`·입력 버전 직렬화의 소속 | screening 또는 deep_review 한쪽 | 범용 client·직렬화·상수는 core, C-2 adapter는 screening | deep_review와 screening이 둘 다 쓴다 |

별도 프로세스·별도 DB로 나누는 안은 [ADR-0043](0043-screening-deep-review-module-boundary.md)이
이미 기각했고 이 결정은 그 기각을 유지한다.

## 결과

### 확인된 결과

- **REST 표면이 계약 수준에서 불변이다.** 이주 전(`a7deaa2`)과 현재 tip의 OpenAPI 문서를
  각각 생성해 비교하면 경로 74개 집합, 각 경로·method의 parameter·request body·response
  schema, `components` 전체가 같다. 다른 것은 `tags` 두 자리뿐이다 — `/api/health`가 태그
  없음에서 `health`로, `POST /api/runs/{run_id}/pipeline/judgment`가 `runs`에서 `screening`
  으로 바뀌었다. `tags`는 `/docs` 화면의 묶음 라벨이며 `docs/contracts.md`가 계약으로 고정한
  값이 아니다.
- **경계 검사 허용 목록**: 검사 1(모듈 간 import 방향) 0건, 검사 2(router 안 ORM 접근)
  18건(명세가 범위 밖으로 둔 것), 검사 3(schemas→models·services) 0건, 검사 4(lifecycle 교차
  relationship) 0건. 검사 1은 도입 시점 66건, 확장점을 정의한 시점 58건이었다. 목록은 줄어드는
  방향만 허용하며 stale 항목이 남아 있어도 실패한다.
- **모듈 단독 기동**: `BIDOPS_MODULES=lifecycle`은 API 경로 20개, `screening`은 31개,
  `deep_review`는 25개이고 셋 다 지정하면 74개다. 세 조합 모두 `/api/health`를 갖고, 겹치는
  경로는 `/api/health`뿐이다.

### 이 결정이 뜻하지 않는 것

- 이 결정은 **구조 배치**만 정한다. 어느 모듈의 운영 활성화도 뜻하지 않는다. 스케줄러와
  always-on은 그대로 기본 비활성이고, 선별의 상시 운영은
  [ADR-0017](0017-human-enabled-quality-gate.md)의 품질 게이트와 사람의 활성화를 따른다.
- 적합성 등급·참여 준비·추적 선택·최종 Go/No-Go가 서로를 대신하지 않는다는 경계는 그대로다
  ([ADR-0030](0030-opportunity-tracking-state.md)).
- 배포 단위는 하나 그대로다. 모듈 선택은 개발·검증용 기동 옵션이며 운영은 셋 다 등록한다.

### 실행 중에 생긴 이탈과 그 이유

1. **`app/migrations/import_sqlite.py`가 네 모듈의 `models`를 직접 import한다.** 설계의 예외
   목록은 `alembic/env.py`와 migration revision 파일만 적었으나, 이 파일도 legacy·Lean v1
   대상 테이블을 전부 등록해야 한다. 대안(네 모듈의 `__init__` import)은 성립하지 않는다 —
   `app/core/__init__.py`와 `app/deep_review/__init__.py`가 `models`를 공개 이름으로 올리지
   않아 테이블이 등록되지 않는다. 예외 목록에 이 파일을 더했다.
2. **경계 검사 1의 대상 범위는 `app/` 아래 모든 `.py`(조립 계층 포함)와 `tests/<module>/`
   아래 모든 `.py`다.** 검사기가 한때 `tests/app/`도 조립 계층으로 보고 "공개 이름만" 규칙을
   적용했는데, `tests/app/`은 `tests/<module>/`이 아니다. 그 과잉 적용은 통합 테스트를 제자리에
   두려면 각 모듈이 내부 이름 86개를 공개해야 하게 만들어, 테스트 배치 규칙과 완료 기준을
   동시에 불가능하게 했다. `app/`에 대한 보장은 그대로이며, 합성 트리 테스트가 "`tests/app/`은
   통과하지만 `app/`의 조립 계층 파일이 같은 import를 하면 여전히 실패한다"를 고정한다.
3. **deep_review → screening seam은 지연 호출이다.** 의존 규칙은 deep_review가 screening의
   읽기 전용 seam을 쓰도록 허용하는데, 기준 6은 deep_review 테스트가 screening 폴더 없이
   통과하라고 한다. 모듈 최상위에서 seam을 import하면 두 조항이 어긋난다. 그래서 seam은
   **필요할 때만** — 함수 안에서 — import한다. screening이 있을 때 동작은 완전히 같고,
   없으면 모듈은 뜨며 그 조회를 실제로 쓰는 테스트만 `tests/app/`으로 간다.
4. **네 모듈의 `__init__.py`는 지연 공개다**(`_EXPORTS` 표 + 모듈 `__getattr__`). models 분할
   과정에서 `app/ingest/loader.py`(현재 `app/lifecycle/ingest/loader.py`)가 `app.lifecycle.models`를 import하게 되자 패키지 초기화가
   `app/lifecycle/api.py`를 거쳐 loader로 되돌아오는 순환이 생겨 `python -m app.screening.cli`가
   죽었다(전체 테스트는 conftest의 import 순서 때문에 이를 가렸다). 패키지 초기화가 아무것도
   import하지 않게 만들어 끊었고, 새 인터프리터에서 `python -m <진입점> --help`를 실제로
   실행하는 회귀 테스트(`tests/app/test_module_cli_entrypoints.py`)를 두었다.
5. **`app/core/db.py`의 `init_db()`가 더 이상 모든 모델을 스스로 등록하지 않는다.** 예전에는
   `from .. import models`로 전부 등록했는데, 분할 뒤 그것은 core → 도메인 모듈 역방향이다.
   이제 등록은 그 모듈의 `models`를 import한 쪽이 하고, 전체 집합이 필요한 조립 계층
   (`alembic/env.py`, `app/migrations/import_sqlite.py`)이 네 모듈을 들인다. `init_db(bind)`는
   호출자의 import 그래프에 등록된 것만 만든다.
6. **"개요 상태 필터는 422" 조항은 도달 불가다.** `GET /api/pre-specs`에는 개요 상태 query
   필터가 원래 없었고(`docs/contracts.md`의 query param 목록), 새로 만들면 그 자체가 REST 표면
   변경이다. registry의 `overview_filters_supported` 술어는 존재하되 사용처가 없다.
7. **hook 실패 격리는 hook 구현 안에 둔다.** 회차 적재 hook은 savepoint를 hook 안에 두었고
   추적 결정 hook은 호출부에 남겼다(동치는 테스트로 확인). 여러 모듈이 같은 hook을 등록할 때
   한 hook의 실패가 형제 hook의 성공 쓰기를 되돌리지 않으려면 hook 안이 맞다. 앞으로 추가되는
   hook은 자기 보호를 갖춰야 한다.
8. **`tests/agents/`의 두 파일은 `tests/app/`으로 갔다**(`test_deep_review_agent.py`,
   `test_document_preparation_agent.py`). fixture가 screening의 판정 행을 심어 두 모듈이 합쳐지는
   검사이기 때문이다. `docs/backend-modules/design.md` §4.5 표는 `tests/deep_review`로 적었지만
   테스트 배치의 산문 규칙("두 모듈 이상이 합쳐지는 통합 검사는 `tests/app/`")을 따랐다.

### 남는 것

- router 안의 `select`를 service로 내리는 작업은 검사 2의 허용 목록 18건으로 추적만 한다.
- `ingest/loader.py`의 도메인별 분할은 lifecycle 안에서 별도로 진행한다.
- `experiments/` 런타임 의존과 그 밖에 이번 범위에서 고치지 않은 관찰은
  [`findings.md`](../findings.md)에 있다.
