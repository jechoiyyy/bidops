# backend 모듈 경계 이주 단독 실행 검증 (2026-09-04)

대상 worktree `.dryforge/worktrees/wt1`, branch `dryforge/wt-t9`.
검증 시작 tip `85252ce`(T8 종료), 검증 대상 tip은 아래 "바꾼 것" 두 commit이다.
host에서 sandbox 없이 실행했고 저장소 `.venv`를 그대로 썼다.

이 문서는 실행한 명령과 그 요약 줄을 그대로 남긴다. 이전 통과 기록을 재사용하지 않았다.

## 바꾼 것

| commit | 내용 |
|---|---|
| `996bc5c` | `deep_review`의 선별 seam import 두 자리를 함수 안 지연 호출로 옮김 |
| `d255a37` | `web/backend/scripts/verify_module_isolation.sh` 추가 |

seam 수정은 명세 §4·§6.3(“deep_review는 screening의 읽기 전용 seam 함수를 쓴다”)과
§2 완료 기준 6(“deep_review 테스트가 screening 폴더 없이 수집·통과한다”)이 어긋나 있던
것을 담당자 결정대로 정리한 것이다. `app/deep_review/services/document_bundles.py`와
`app/deep_review/services/input_versions.py`가 모듈 최상위에서 seam을 들여, `app/screening/`을
지우면 `tests/deep_review/` 8개 모듈이 `ModuleNotFoundError`로 수집조차 되지 않았다.
import를 실제 사용 함수(`DocumentBundleService.effective_grade`, `effective_grade_basis`)
안으로 옮겼다. 방향·이름·동작·반환값·오류는 그대로다.

REST 표면 불변을 직접 확인했다. 수정 전후로 `app.main:app`의 OpenAPI 문서를 정렬된 JSON
으로 뽑아 비교한 결과 **diff 0줄**(각 474,067 bytes)이다.

경계 검사기는 `ast.walk`로 파일 전체를 훑으므로 함수 안 import도 그대로 본다. 실측으로
확인했다.

```
app/deep_review/services/document_bundles.py -> ['app.screening:current_judgment', 'app.screening:latest_corrected_grade']
app/deep_review/services/input_versions.py   -> ['app.screening:current_judgment', 'app.screening:latest_corrected_grade']
```

즉 `boundary_map.SEAM_IMPORTS`가 두 이름을 여전히 이름 단위로 강제하며 stale이 되지 않았다.
허용 목록은 늘리지 않았다.

## 마지막 전체 검증

### 1. backend 전체 suite

```bash
cd web/backend && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider -rs
```

```
2 failed, 1240 passed, 5 skipped, 6 warnings in 803.92s (0:13:23)
```

종료 코드 1. 실패 2건은 기존 결함이며 둘 다 `'실패' == '부분 성공'` 단언이다.

- `tests/screening/test_screening_orchestrator.py::test_full_run_continues_after_one_notice_failure_and_publishes_partial`
- `tests/screening/test_screening_orchestrator.py::test_partial_rejudgment_retains_prior_projection_and_revision`

T8 종료 기준선 `2 failed, 1240 passed, 5 skipped`와 같다. 추가 실패, skip 증가, 수집 건수
감소는 없다. skip 5건의 이유는 모두 출력에 남았다.

```
SKIPPED [1] tests/app/test_document_bundles.py:150: requires the isolated T7 MinIO service
SKIPPED [1] tests/app/test_requirements_lock.py:152: installed-set assertion is scoped to the target container path
SKIPPED [3] tests/core/test_minio_e2e.py: requires the isolated T7 MinIO service
```

### 2. 파이프라인 단위·교차 테스트

```bash
./run-tests.sh
```

종료 코드 0.

```
== skills/bidops-collect/tests   Ran 41 tests  OK
== skills/bidops-report/tests    Ran 13 tests  OK
== skills/bidops-screen/tests    Ran 89 tests  OK (skipped=10)
== tests                         Ran  2 tests  OK
```

합계 145 passed로 기대값과 같다.

### 3. 프론트엔드

```bash
cd web/frontend && npm run build && npm run test:visual
```

`npm run build` 종료 코드 0, Vite 초기 JS `index-B3SAj4Ri.js` 358.70 kB / gzip 112.89 kB.

Playwright 1차 실행: `1 failed, 14 skipped, 845 passed (10.0m)`.
실패는 `[desktop] tests/common-interactions.spec.ts:337 흡수한 옛 경로는 404를 내지 않고
목적지 화면의 해당 탭으로 열린다`이며, 저장된 뷰의 정렬값이 5초 안에 반영되지 않은
`toHaveValue("deadline")` 시간 초과다. Playwright `strict mode violation`이 아니다.

단독 재실행 `1 passed`, 전체 재실행 `14 skipped, 846 passed (7.0m)` 종료 코드 0.
부하 의존 flake로 판단한다.

이 base의 Playwright 전체 규모는 860건(846 passed + 14 skipped)이며, `docs/tracking/status.md`에
남아 있던 `646 passed, 10 skipped`보다 크다. 이 worktree는 `web/frontend`에서 파일 하나
(`src/components/common/ReviewPrimitives.tsx`)만 더할 뿐 spec을 바꾸지 않았으므로 규모 차이는
이 이주와 무관하고, 기존 기준선 숫자가 오래된 것이다.

### 4. 컨테이너 빌드

```bash
docker compose --env-file <임시 placeholder env> -f docker-compose.t7.yml build
```

종료 코드 0. `wt1-web`, `wt1-migrate`, `wt1-document-worker`, `wt1-analysis-worker`,
`wt1-postgres-init` 다섯 image가 빌드됐다.

이 worktree에는 `.env`가 없어 compose가 interpolation 단계에서 먼저 실패한다. 빌드는 실제
secret을 쓰지 않으므로 `docker-compose.t7.yml`이 요구하는 변수 30개를 임시 디렉터리의
placeholder 값으로 채운 `--env-file`로 돌렸다. 본체 저장소의 `.env`는 읽지 않았고 저장소에는
아무것도 쓰지 않았다.

### 5. 기준 6 스크립트

```bash
web/backend/scripts/verify_module_isolation.sh
```

종료 코드 0. 폐기 가능한 `postgres:17.11` 컨테이너를 스스로 띄워 세 조합 모두 PostgreSQL
테스트까지 실제로 돌렸다.

```
PASS  lifecycle    pytest exit=0  75 passed, 1 warning in 7.90s
PASS  screening    pytest exit=1  2 failed, 394 passed, 1 skipped, 1 warning in 309.43s (0:05:09)
PASS  deep_review  pytest exit=0  230 passed, 6 warnings in 68.41s (0:01:08)
전체: PASS
```

- `screening` 조합의 실패 2건은 위 전체 suite와 같은 기존 결함 2건뿐이며 스크립트가 이름으로
  확인해 출력한다. 그 밖의 실패는 없다.
- skip은 조합마다 명시된다. `lifecycle` 0건, `deep_review` 0건, `screening` 1건
  (`tests/screening/test_profile_snapshot_container_fallback.py:66: the runtime does not contain
  a source checkout`). 조용한 skip이 없다.
- 형제 모듈에서 `app/<module>/models.py` 한 파일만 남긴다. §3이 유일한 예외로 열거한 대로
  `alembic/env.py`와 모든 revision이 네 모듈의 `models`를 import해야 `Base.metadata`가
  완성되기 때문이다. `__init__.py`는 지우므로 `app.screening`은 namespace package가 되고
  `from ...screening import current_judgment` 같은 공개 표면 접근은 그대로 실패한다. 격리
  강도는 줄지 않은 채 PostgreSQL harness만 살아났다.
- 이 방식이 아니면 `BIDOPS_TEST_POSTGRES_URL`을 준 순간 세 조합 모두 수집 전에
  `Alembic failed to migrate the isolated PostgreSQL 17 test database`로 죽고, 주지 않으면
  postgres 표시 테스트가 통째로 skip된다. `deep_review` 조합은 이 방식으로 15건이 skip에서
  통과로 바뀌었다(215+15 skipped → 230 passed).

## 완료 기준 여섯 조건

### 1. 각 모듈이 자기 테이블·서비스·router·worker·schema·테스트를 자기 폴더 안에 갖는다

`tests/app/test_module_boundaries.py`(28 passed)가 폴더 배치와 테이블 소유를 강제하고,
아래 트리를 사람이 직접 확인했다.

```text
web/backend/app/
├── __init__.py, main.py, runtime.py      조립 계층
├── workers/analysis.py                   합성 worker (조립 계층)
├── migrations/import_sqlite.py           일회성 SQLite 이전 입력 (조립 계층)
├── core/          19 py
├── lifecycle/     26 py   ingest/ schemas/ services/ routers/
├── screening/     47 py   cli/ schemas/ services/ workers/ routers/
└── deep_review/   71 py   cli/ contracts/ document_mcp/ policies/ schemas/
                           services/ workers/ agents/ routers/

web/backend/tests/
├── __init__.py, conftest.py, postgres.py, c2_fixtures.py   루트 공용 helper
├── fakes/, fixtures/                                        루트 공용 helper
├── core/          test 6
├── lifecycle/     test 9
├── screening/     test 32
├── deep_review/   test 20
└── app/           test 39   조립·migration·runtime 계약·두 모듈 이상 통합 검사
```

`app/` 아래 도메인 폴더 밖에 남은 `.py`는 `__init__.py`·`main.py`·`runtime.py`·
`workers/analysis.py`·`migrations/import_sqlite.py`뿐이다. 테이블은 §5.1대로
core 2 / lifecycle 10 / screening 28 / deep_review 34 = 74개이며
`tests/app/test_mapper_isolation.py::test_the_four_modules_together_declare_the_whole_schema`와
`tests/app/test_deep_review_migrations.py`가 74를 단언한다(둘 다 통과).

### 2. 의존은 §4 방향으로만 흐른다

`tests/app/test_module_boundaries.py` **28 passed**. 허용 목록 최종 크기는

```python
BASELINE_SIZES = {
    "cross_module_import": 0,
    "router_orm_access": 18,
    "schema_imports_model_or_service": 0,
    "lifecycle_relationship": 0,
}
```

즉 남은 것은 명세 §8이 이번 이주의 범위 밖으로 둔 **검사 2의 router 안 직접 select 18건뿐**
이고 나머지 셋은 0이다. 목록은 stale 항목도 실패시키므로 실제 위반과 정확히 같다.

### 3. `main.py`가 `BIDOPS_MODULES`로 고른 모듈만 등록하고, 어느 도메인 모듈을 빼도 기동한다

`tests/app/test_module_selection.py`가 전체 suite에서 통과했다. 확인 항목:

- `test_health_is_registered_for_every_module_subset` — 모든 부분집합에서 `/api/health` 200
- `test_only_the_selected_module_answers` / `test_module_route_sets_partition_the_default_app`
  — 선택한 모듈의 대표 경로는 응답하고 상대 모듈 경로는 404
- `test_the_process_refuses_to_start_with_a_bad_module_list`,
  `test_the_default_process_starts_with_every_module` — 새 프로세스 기동
- `test_lifecycle_alone_registers_no_extension_provider`,
  `test_screening_registers_only_its_own_extensions`,
  `test_deep_review_registers_only_its_own_extensions`,
  `test_the_default_selection_registers_both_providers`,
  `test_modules_are_parsed_in_the_given_order_with_whitespace_trimmed` — 확장점 등록과 그 순서
- `test_only_the_selected_module_builds_its_runtime`,
  `test_state_names_are_published_for_the_selected_modules_only` — 모듈별 runtime
- `test_the_scheduler_stays_off_unless_enabled` — startup이 정책을 활성화하지 않음

모듈 부재 시 projection `null`과 hook no-op은 `tests/lifecycle/test_api_without_judgment_provider.py`
5건과 `tests/lifecycle/test_extensions.py`, `tests/lifecycle/test_ingest_without_screening.py`,
`tests/app/test_extension_registration.py` 2건이 덮는다. 아래 4번의 실제 CLI 실행이 같은 것을
운영 경로에서 한 번 더 보여 준다.

### 4. 각 모듈이 웹 없이 CLI로 실행된다

`tests/app/test_module_cli_entrypoints.py`가 새 인터프리터에서 `python -m <진입점> --help`를
subprocess로 실제 실행한다(진입점 3개와 하위 명령 전부, 7 조합). 전체 suite에서 통과했다.

추가로 **세 CLI를 실제 PostgreSQL 17에 붙여 한 번씩 돌렸다.** 모델 호출·외부 전송이 일어나는
인자는 쓰지 않았다.

| 명령 | 결과 |
|---|---|
| `python -m app.lifecycle.ingest.cli --run 20260817-20260823` | **exit 0.** 회차를 실제로 적재했다. 선별 모듈이 없는 프로세스라 `judgment_ingest_skipped` warning 38건과 함께 공고까지만 적재했다 — hook no-op이 운영 경로에서 그대로 동작한다 |
| `python -m app.deep_review.cli import-profile-policy --actor …` | exit 2, `import failed: service_unavailable`. CLI가 뜨고 PostgreSQL에 붙어 domain service까지 도달한 뒤 `assets._store`의 문서 object storage(MinIO) 부재에서 멈췄다. 모듈 경계가 아니라 환경 의존이다 |
| `python -m app.screening.cli run-one --run-id … --notice-id … (--wait 없음)` | exit 1, `{"error_code":"input_error","status":"실패"}`. traceback 없이 계약된 입력 오류로 끝났다. 활성 선별 policy가 없는 DB이기 때문이며, 활성화에는 3중 활성화 게이트가 필요하고 `--wait`는 모델을 부르므로 쓰지 않았다 |

`BIDOPS_DATABASE_URL`을 SQLite로 주면 `init_db()`가
`BidOps application runtime requires PostgreSQL 17`로 fail-closed한다는 것도 확인했다.

### 5. worker 진입점이 모듈별로 있다

`__main__`이 있어 **단독으로 실행 가능한 worker 진입점**은 셋이다.

- `app.deep_review.workers.document`
- `app.deep_review.workers.prespec_attachment`
- `app.workers.analysis` — 심층 검토와 C-2 선별을 한 슬롯에서 돌리는 **합성 진입점**이며
  명세대로 조립 계층에 남는다

`app.deep_review.workers.deep_review`와 `app.screening.workers.order_plan`에는 `__main__`이
**없고 만들지 않는다.** 이주 전부터 없었다. 둘 다 모델을 쓰는 worker라 단독 진입점을 만들면
합성 worker와 동시에 떠서 “모델 슬롯 1개” 보장을 깰 수 있다. 담당자 결정이며, 두 worker는
합성 worker를 통해 돈다.

(worker가 아닌 `__main__`은 `app/core/db_admin.py`, `app/screening/policy.py`,
`app/migrations/import_sqlite.py`의 운영·이전 도구다.)

### 6. 네 모듈 모두 형제 도메인 모듈 폴더 없이 수집·통과한다

위 “5. 기준 6 스크립트”가 세 조합 모두 PASS다. core는 항상 있고 lifecycle은 screening·
deep_review의 전제이므로 남긴다.

`app/screening/`을 지운 상태에서 `tests/deep_review/` **230건이 수집되고 전부 통과**했다.
그 seam(`effective_grade`, `effective_grade_basis`)을 실제로 부르는 테스트는
`tests/deep_review/`에 없다 — 그 경로를 태우는 통합 검사는 이미 `tests/app/`에 있으므로
`git mv`로 옮길 파일이 없었다.

## 함께 확인한 것

| 항목 | 확인 |
|---|---|
| `test_alembic_autogenerate`의 빈 diff | `tests/app/test_alembic_autogenerate.py::test_alembic_check_has_no_default_schema_bidops_mirror_drift` 통과 (skip 목록에 없음) |
| 74개 테이블 집합 | `test_the_four_modules_together_declare_the_whole_schema`, `tests/app/test_deep_review_migrations.py` 통과 |
| `BIDOPS_MODULES` 부분집합의 `/api/health` 200·대표 경로·상대 모듈 404 | 위 3번 |
| 첨부 삭제 시 `attachment_fetch` cascade | `tests/deep_review/test_attachment_fetch_cascade.py` 3건 통과. PostgreSQL 변형이 전체 suite와 기준 6 `deep_review` 조합 양쪽에서 실제로 돌았다(skip 없음) |
| 모듈 부재 시 projection `null`·hook no-op, 확장점 등록 순서 | 위 3번, 그리고 4번의 실제 ingest CLI 실행 |
| 경계 검사 허용 목록 최종 크기 | 검사 2의 18건만 남음. 나머지 셋은 0 |
| Alembic head | `0017_order_plan_screening_heartbeat`. 새 revision을 만들지 않았다 |

## 남은 것

- `tests/screening/test_screening_orchestrator.py`의 기존 결함 2건은 이 이주와 무관하며 그대로다.
- Playwright 전체 규모(860건)와 `status.md`에 남아 있던 646건 기준선이 다르다. 이 이주의
  변경이 아니다.

## 통합 base에서 다시 돌린 완료 검증

위 기록은 작업 worktree(`dryforge/wt-t9`)에서 나온 것이다. T9과 T10을 `dryforge/backend-modules`에
병합한 뒤 **통합된 상태(`0a889f5`)에서 같은 명령을 처음부터 다시 돌렸다.** 이전 통과 기록을
재사용하지 않았다.

| 명령 | 결과 | 종료 코드 |
|---|---|---|
| `cd web/backend && .venv/bin/python -m pytest tests/ -q -p no:cacheprovider -rs` | `2 failed, 1240 passed, 5 skipped, 6 warnings in 611.46s (0:10:11)` | 1 |
| `./run-tests.sh` | collect 41 / report 13 / screen 89(skipped 10) / root 2 = 145, 전부 OK | 0 |
| `cd web/frontend && npm run build` | `✓ built in 1.21s`, 초기 JS `index-B3SAj4Ri.js` 358.70 kB / gzip 112.89 kB | 0 |
| `cd web/frontend && npm run test:visual` | `14 skipped, 846 passed (9.9m)` — 1차 실행에서 바로 통과했다(재실행 없음) | 0 |
| `docker compose -f docker-compose.t7.yml build` | `bidops-migrate`, `bidops-postgres-init`, `bidops-web`, `bidops-document-worker`, `bidops-analysis-worker` 다섯 image 빌드 | 0 |
| `web/backend/scripts/verify_module_isolation.sh` | lifecycle `75 passed` / screening `2 failed, 394 passed, 1 skipped` / deep_review `230 passed`, 전체 PASS | 0 |

backend 실패 2건은 위와 같은 기존 결함 2건뿐이며 로그에서 이름과 단언
(`'실패' == '부분 성공'`)을 확인했다.

- `tests/screening/test_screening_orchestrator.py::test_full_run_continues_after_one_notice_failure_and_publishes_partial`
- `tests/screening/test_screening_orchestrator.py::test_partial_rejudgment_retains_prior_projection_and_revision`

skip 5건의 사유는 모두 출력에 남았다(MinIO 격리 서비스 4건, 컨테이너 경로 전용 installed-set 1건).

`web/frontend`는 이주 전 `a7deaa2`부터 `0a889f5`까지 **diff가 비어 있다.** 이 이주는 프론트엔드를
한 줄도 바꾸지 않았으므로 위 Playwright 결과는 이주의 영향을 받지 않는 상태의 측정이다.

### 이주 전후 REST 표면 — 정정된 측정

`a7deaa2`와 `0a889f5`를 각각 `git archive`로 뽑은 깨끗한 사본에서 `app.main:app`의 OpenAPI 문서를
정렬된 JSON으로 생성해 비교했다. **diff는 11줄이고 전부 `tags`다.**

```
14345c14345,14348          /api/health 의 tags: (없음) → ["health"]
17912c17915                POST /api/runs/{run_id}/pipeline/judgment 의 tags: ["runs"] → ["screening"]
```

경로 74개와 각 경로의 메서드·파라미터·요청 본문·응답 스키마, `components` 전체는 동일하다.
두 변화는 T3가 `/api/health`를 `app/core/health.py`로, T5a가 판정 실행 endpoint를 screening router로
옮기면서 생긴 것이며(중간 commit `cb1e4b5`에서 이미 나타난다) 소유 모듈을 정확히 반영한다.
`tags`는 `/docs` 화면의 묶음 이름표이고 `docs/contracts.md`가 계약으로 고정한 값이 아니다.

이 문서의 앞부분에 적힌 "diff 0줄"은 seam 수정 **전후**를 비교한 값이다. 이주 **전체**의
전후 비교는 위 11줄이 정확한 값이다.
