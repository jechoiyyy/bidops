# 사전규격 회사 핏 v2(사업 범위 카드) 판정 표시와 엔진 분석 추천 — plan

- 기능 ID: `PS-01-company-fit-card`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-11-27
- 작업 위치: plain clone `/Users/temp/orca/bidops-fitcard`, 브랜치 `feat/prespec-company-fit-card`(main `65a82d5`에서 분기). main checkout은 운영 위치이고 다른 WIP가 있으므로 쓰지 않는다.

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| `web/backend/app/core/config.py` | 수정 | `prespec_company_fit_card_path`·`prespec_company_fit_card_sha256` |
| `web/backend/app/deep_review/services/company_fit_card.py` | 신규 | 카드 로드·구조 검사·sha·투영(C1) |
| `web/backend/app/deep_review/services/company_fit.py` | 수정 | `PROMPT_VERSION_CARD`·`INSTRUCTION_CARD_V31`·`card_fit_policy`·`frozen_card_input`·`card_model_input`(C2), 카드 현재성(C9), lineage 필터(`card_sha256 IS NULL`), `gate_reasons`의 `company_fit_suggest_only`, `company_fit_view` v2(C5) |
| `web/backend/app/deep_review/services/company_fit_mode.py` | 신규 | `company_fit_mode_state`(C4)·`set_company_fit_mode`(C8) |
| `web/backend/app/deep_review/services/company_fit_runner.py` | 수정 | 카드 enqueue·claim·실행 분기, 프로필 lineage 정지, 심층 자동 시작 미호출 |
| `web/backend/app/deep_review/schemas/company_fit.py` | 수정 | `CompanyFitView`(lineage·card 필드, nullable profile), `CompanyFitResponse` v2, 모드 요청·응답 |
| `web/backend/app/deep_review/models.py` | 수정 | attempt 열·제약, `PreSpecCompanyFitMode` |
| `web/backend/alembic/versions/0044_company_fit_card_lineage.py` | 신규 | spec "저장" 1·2 |
| `scripts/runtime-privileges.sql` | 수정 | 새 테이블·열 권한 |
| `web/backend/app/deep_review/routers/deep_reviews.py` | 수정 | `GET/POST /api/pre-specs/company-fit/mode`, 회사 핏 응답 v2 |
| `web/backend/app/deep_review/cli/__init__.py`, `web/backend/app/deep_review/cli/set_company_fit_mode.py` | 수정, 신규 | CLI(C8) |
| `web/backend/app/deep_review/services/prespec_projection.py` | 수정 | `prespec_status_fields` 반환 dict에 `company_fit` 요약(C6) 키를 더한다(새 메서드 없음) |
| `web/backend/app/lifecycle/schemas/pre_specs.py`, `web/backend/app/lifecycle/routers/pre_specs.py` | 수정 | `PreSpecSort`에 `fit`, `company_fit` 질의·필드(C7). `_deadline_sort_expression`을 공개 함수로 옮긴 것을 쓴다 |
| `web/backend/app/lifecycle/services/pre_spec_scope.py`, `web/backend/app/lifecycle/__init__.py` | 수정 | `pre_spec_deadline_sort_expression(now)`를 공개한다(라우터와 카드 enqueue가 함께 쓴다) |
| `web/backend/app/lifecycle/extensions.py` | 수정 | `prespec_status_fields` 반환 키에 `company_fit`이 있음을 docstring·타입에 적는다(새 메서드 없음) |
| `web/backend/tests/deep_review/test_company_fit_card.py` | 신규 | T1·T2 |
| `web/backend/tests/deep_review/test_company_fit_mode.py` | 신규 | T3·T4 |
| `web/backend/tests/deep_review/test_company_fit_card_runner.py` | 신규 | T5~T9 |
| `web/backend/tests/deep_review/test_company_fit_postgres.py` | 수정 | T11 |
| `web/backend/tests/app/test_api_pre_specs_company_fit.py` | 신규 | T10 |
| `web/backend/tests/fixtures/pre_specs_list_baseline.json`, `tests/deep_review/test_company_fit*.py`, `tests/app/test_api_pre_specs*.py` | 수정 | 새 필드·v2 응답 반영 |
| `web/frontend/src/lib/types.ts`, `web/frontend/src/lib/api.ts` | 수정 | v2 응답·목록 필드·`company_fit` 질의(모드 GET은 부르지 않음) |
| `web/frontend/src/components/pre-specs/CompanyFitSection.tsx` | 수정 | 카드 근거 이름·표식·추천·모드 읽기 |
| `web/frontend/src/lib/preSpecAutoPreparation.ts` | 수정 | `company_fit_suggest_only` 문구 |
| `web/frontend/src/components/pre-specs/PreSpecListRow.tsx`, `PreSpecListDetailPane.tsx`, `web/frontend/src/pages/PreSpecsPage.tsx`, `web/frontend/src/lib/preSpecViews.ts` | 수정 | 열·미리보기·필터·정렬·기본 보기 판정 |
| `web/frontend/src/lib/listSelection.ts`, `web/frontend/src/lib/preSpecSelectionReview.ts` | 수정 | `fit` 선택 정렬·`company_fit_group` 메타데이터, `LIST_PARAMS`에 `company_fit` |
| `web/frontend/tests/api-mock.ts`, `web/frontend/scripts/mock-api.ts` | 수정 | `?fit=` 스위치, 목록 fixture |
| `web/frontend/tests/company-fit.spec.ts`, `web/frontend/tests/pre-specs.spec.ts` | 수정 | T12·T13 |
| `docker/docker-compose.prod.yml` | 수정 | 카드 ro 마운트·env(web·analysis-worker) |
| `docs/business-rules.md`, `docs/contracts/deep-review.md`, `docs/contracts/lifecycle-rest.md`, `docs/contracts/prespec-overview.md`, `docs/operations/prespec-reference.md`, `docs/ADR.md`, `docs/tracking/decisions/0080-prespec-company-fit-card.md`(신규), `docs/work/constitution/roadmap.md`, `docs/validation-runs/20261127-company-fit-probe/README.md` | 수정·신규 | spec "큰 틀 문서와의 관계" |

ADR 번호는 0080을 쓴다. main checkout에 미커밋 0078·0079 파일이 있어 번호가 겹치지 않게 한다.

## 작업 순서

1. STEP-001 카드 로더와 카드 lineage 입력 [complex]
   - 목표: C1·C2를 구현하고, 측정 실행기와 같은 모델 입력을 만든다.
   - 작업 대상: `config.py`, `company_fit_card.py`, `company_fit.py`(card 상수·policy·frozen input·model input)
   - 검증: T1, T2 (`pytest tests/deep_review/test_company_fit_card.py`)
2. STEP-002 migration 0044·ORM·권한 [complex]
   - 목표: 세 lineage 제약, 모드 테이블, insert guard 카드 분기, 권한을 만든다.
   - 작업 대상: `alembic/versions/0044_company_fit_card_lineage.py`, `deep_review/models.py`, `scripts/runtime-privileges.sql`
   - 검증: T11 (일회용 PostgreSQL, 아래 증명 postgres)
3. STEP-003 모드 서비스·REST·CLI [complex]
   - 목표: C4 실효 상태 순서와 C8 기록·멱등·감사를 구현한다.
   - 작업 대상: `company_fit_mode.py`, `routers/deep_reviews.py`, `cli/set_company_fit_mode.py`, `cli/__init__.py`, `schemas/company_fit.py`
   - 검증: T3, T4
4. STEP-004 실행기 카드 분기와 공존 규칙 [complex]
   - 목표: 대상 조건 enqueue, claim 시 현재성 확인, 실행, 심층 자동 시작 미호출을 구현한다. 프로필 lineage 정지와 `company_fit_suggest_only`도 넣는다.
   - 작업 대상: `company_fit_runner.py`, `company_fit.py`(C9, lineage 필터, `gate_reasons`)
   - 검증: T5, T6, T7, T8. 기존 `tests/deep_review/test_company_fit.py`·`tests/deep_review/test_company_fit_enqueue.py`·`tests/app/test_auto_deep_review_start.py`·`tests/app/test_analysis_worker_slots.py` 회귀
5. STEP-005 회사 핏 응답 v2와 목록 프로젝션·정렬·필터 [complex]
   - 목표: C5·C6·C7을 구현한다. lifecycle은 deep_review를 import하지 않는다.
   - 작업 대상: `schemas/company_fit.py`, `company_fit.py`(`company_fit_view`), `prespec_projection.py`, `lifecycle/schemas/pre_specs.py`, `lifecycle/routers/pre_specs.py`, `lifecycle/extensions.py`
   - 검증: T9, T10. 기존 `tests/app/test_api_pre_specs*.py`·`tests/lifecycle/test_pre_specs_extension_points.py` 회귀. 응답 shape 변경이라 PostgreSQL 변형도 돌린다
6. STEP-006 상세 화면과 mock [standard]
   - 목표: v2 응답 타입, 카드 근거 이름, 표식, 엔진 분석 추천, 모드 읽기, 사유 문구, `?fit=` mock을 만든다.
   - 작업 대상: `types.ts`, `api.ts`, `CompanyFitSection.tsx`, `preSpecAutoPreparation.ts`, `tests/api-mock.ts`, `scripts/mock-api.ts`, `tests/company-fit.spec.ts`
   - 검증: T12, 증명 frontend
7. STEP-007 목록 열·필터·회사 핏순 정렬 [standard]
   - 목표: 목록 열, 미리보기, 필터, `회사 핏순`, `검토할 항목` 기본 정렬을 만든다.
   - 작업 대상: `PreSpecListRow.tsx`, `PreSpecListDetailPane.tsx`, `PreSpecsPage.tsx`, `preSpecViews.ts`, `listSelection.ts`, `preSpecSelectionReview.ts`, mock 목록 fixture, `tests/pre-specs.spec.ts`
   - 검증: T13, 증명 frontend
8. STEP-008 문서·ADR·운영 compose [standard]
   - 목표: spec "큰 틀 문서와의 관계"의 수정, ADR-0080, prod compose 카드 마운트, 운영 절차를 반영한다.
   - 작업 대상: 변경 파일 표의 docs·`docker/docker-compose.prod.yml`
   - 검증: 증명 docs (`python3 scripts/feature_status.py doctor _`, diff 검토), `docker compose -f … config`로 prod 렌더 확인(값 없음 → `/dev/null` 마운트)
9. STEP-009 측정 재현(승인 뒤 격리 스택) [standard]
   - 목표: 제품 실행기로 11-26 22건을 판정해 측정과 비교하고 기록한다.
   - 작업 대상: 격리 스택 `bidops-prespec1126`(운영 아님).
     - 먼저 그 스택의 overview revision이 64자로 선언됐는지 확인한다(C4 조건 3).
     - 이 브랜치 이미지로 web·analysis-worker를 교체하고, migration 0044를 적용하고, 카드 마운트와 모드 `suggest`를 켠다.
     - 그 스택의 analysis-worker를 멈춘다(슬롯이 같은 행을 claim하지 않게).
     - 카드는 `.sdlc/local-runtime/` 아래 compose override로 web 컨테이너에 ro 마운트한다(git 밖).
     - 실행은 `docs/validation-runs/20261127-company-fit-probe/replay_product.py`(신규, 측정 도구)로 한다. 이 도구는 `PreSpecCompanyFitRunner(clock=2026-11-27 10:30 KST)`의 `run_once`를 `False`가 나올 때까지 반복하고, 결과 행을 `score_gold.py` 입력 형식(JSONL)으로 내보낸다. `docker exec`로 web 컨테이너 안에서 돌린다.
     - 모두 **실행 직전 사용자 승인**이 필요하다. 기록은 `docs/validation-runs/20261127-company-fit-probe/README.md`에 "제품 경로 재현" 절로 남긴다.
   - 검증: T14 (`score_gold.py` 출력)

단계가 9개다. STEP-009는 사람 승인이 필요한 수동 실행이라 앞 8단계와 따로 둔다. 기능을 나누지는 않는다(STEP-001~008만으로도 검토할 수 있다).

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 측정 입력과 byte 단위로 같아야 한다는 불변식이 있다 |
| STEP-002 | M | 높음 | complex | 기존 trigger·check 두 migration(0020·0036) 위에 세 lineage 불변식을 얹는다 |
| STEP-003 | M | 높음 | complex | 평가 순서·멱등·감사 규칙 |
| STEP-004 | L | 높음 | complex | 상태 전이·공존·외부 모델 호출 보호 장치 |
| STEP-005 | L | 높음 | complex | 모듈 경계(확장점)·페이지 경계 정렬 |
| STEP-006 | M | 중간 | standard | spec이 문구·조건을 닫았고 기존 컴포넌트 패턴이 있다 |
| STEP-007 | M | 중간 | standard | `CompanyPreSpecsPage`의 회사 핏 열·필터 패턴을 따른다 |
| STEP-008 | M | 낮음 | standard | 문서·설정 |
| STEP-009 | S | 중간 | standard | 승인된 명령을 실행하고 기록한다. 판단은 사람이 한다 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 제품 모델 입력이 측정과 달라 결과가 달라진다 | T2에서 instruction·키 불일치, T14에서 일치 수가 크게 떨어짐 | T2가 측정 문자열과 bytes를 비교한다. T14 결과는 사실대로 기록하고, 프롬프트를 고쳐 맞추지 않는다 |
| 프로필 lineage 질의가 카드 행을 섞어 읽는다(같은 `company_id IS NULL`) | 기존 회사 핏·자동 심층 테스트 실패, gate가 카드 행으로 matched 판단 | 프로필 질의 전부에 `card_sha256 IS NULL`을 넣고 T8로 고정한다 |
| 카드 matched가 심층 자동 시작이나 추적을 만든다(ADR-0078 위반 유혹) | DeepReview 행·추적 변경 발생 | T6·T8이 0건을 확인한다. 추천은 표시만 한다 |
| 카드 파일이 git에 들어간다(공개 저장소) | `git status`에 카드 yaml | 테스트는 합성 카드를 쓰고, prod는 host 경로 마운트만 한다. 측정 폴더 복사본에서도 카드는 제외했다 |
| 목록 정렬에 공고 id 목록이 커서 느려진다 | `sort=fit` 응답 지연 | 그룹 순위는 VALUES/CTE join으로 넘기고, T10에 수백 건 fixture를 둔다 |
| 첫 켜기 때 열린 공고가 몰려 worker 슬롯을 오래 쓴다(건당 약 50초) | 회사 핏 슬롯이 개요 슬롯보다 앞이라(`workers/analysis.py`) 개요 run이 밀린다. C-2는 회사 핏보다 앞이다 | 한 poll에 1건만 enqueue한다. 운영 켜기는 아침 cron 뒤 한가한 시간에 한다. 밀린 개요 건수를 지켜본다(operations 문서에 적음). 슬롯 순서는 이번에 바꾸지 않는다 |
| main checkout WIP와 `types.ts`·`api.ts`가 겹친다 | 병합 충돌 | 병합은 수동이다. 충돌 위치를 결과 절에 남긴다 |
| 응답 v2로 다른 소비자가 깨진다 | `CompanyFitAttempts`·회사 화면 회귀 | 회사 lineage REST(`company_reads`)는 바꾸지 않는다. `CompanyFitSection`만 v2를 읽는다 |

## 증명

- docs: `python3 scripts/feature_status.py doctor _`, spec "큰 틀 문서와의 관계" 항목별 diff 대조, ADR-0080·roadmap PS 절 확인
- tests: `bash -lc "cd web/backend && python -m pytest -q -x -p no:cacheprovider tests/deep_review/test_company_fit_card.py tests/deep_review/test_company_fit_mode.py tests/deep_review/test_company_fit_card_runner.py tests/app/test_api_pre_specs_company_fit.py"`와 회귀 `tests/deep_review/test_company_fit.py tests/deep_review/test_company_fit_enqueue.py tests/app/test_auto_deep_review_start.py tests/app/test_analysis_worker_slots.py tests/app/test_api_pre_specs.py tests/app/test_api_pre_specs_projection.py tests/app/test_api_pre_specs_workspaces.py tests/lifecycle/`. 공통 테이블 migration이 있으므로 release 이미지 안 전체 백엔드 스위트를 한 번 돌리고, 기존 알려진 실패와 구분해 적는다
- postgres: `docker run -d --rm --name pg-ps01 -e POSTGRES_PASSWORD=pw -p <빈 포트>:5432 postgres:17.11`, 그 뒤 `BIDOPS_TEST_POSTGRES_URL=postgresql+psycopg://postgres:pw@127.0.0.1:<포트>/postgres pytest tests/deep_review/test_company_fit_postgres.py tests/app/test_db_migrations.py tests/app/test_deep_review_migrations.py tests/app/test_runtime_database_privileges.py tests/app/test_api_pre_specs_company_fit.py`
- frontend: `bash -lc "cd web/frontend && npm run build && npm run test:contrast"`. 그리고 빈 `PW_PORT`·`PW_OUT_DIR`로 `npx playwright test tests/company-fit.spec.ts tests/pre-specs.spec.ts --workers=2`(운영 실행 중이면 한 번에 하나)
- api_guard: T6(모델 입력 키 7개, `verify_identity` 불일치 시 호출 없음), T3·T4(`effective` 아니면 enqueue·claim 없음)
- real_data_run: feature.json상 RL 전용이라 비적용이다. 대신 STEP-009 T14를 승인 뒤 수동 기록으로 남기며, 품질 근거로 쓰지 않는다

## 결과

구현 후 작성한다.
