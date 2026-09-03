# 백엔드 모듈 경계 설계: core · lifecycle · screening · deep_review

| 항목 | 내용 |
|---|---|
| 문서 상태 | 제안. ADR-0043을 보강하는 설계이며 후속 ADR로 확정하기 전까지 구현 착수 근거로만 쓴다 |
| 기준일 | 2026-09-03 (KST) |
| 정본 | docs/backend-modules/design.md |
| 대상 | `web/backend/app/` |
| 관련 문서 | [ADR-0043](../tracking/decisions/0043-screening-deep-review-module-boundary.md), [ADR-0001](../tracking/decisions/0001-artifact-boundary.md), [ADR-0013](../tracking/decisions/0013-screening-orchestrator-boundary.md), [ARCHITECTURE.md](../ARCHITECTURE.md), [standards.md](../standards.md), [web/backend/AGENTS.md](../../web/backend/AGENTS.md) |

## 1. 목적

1차 분류(선별)와 심층 검토를 각각 단독으로 쓸 수 있는 모듈로 가르고, 그 경계를 코드 폴더와 테스트로 고정한다.
ADR-0043이 이미 "한 배포 단위 안에서 서로를 import하지 않는 두 모듈"을 채택했다. 이 문서는 그 결정을 실제 코드 전체에 적용할 수 있도록 다음을 보강한다.

- ADR-0043이 분류한 테이블은 42개이나 `app/models.py`에는 74개가 있다. 나머지는 선별도 심층도 아닌 **기회 생애주기** 도메인이며, 이를 core에 넣으면 core가 다시 거대 공용 폴더가 된다. 따라서 모듈을 넷으로 둔다.
- ADR-0043은 선별↔심층 교차 import만 다뤘다. 실측에서는 `db`·`models`·`schemas`가 도메인 모듈을 import하는 역방향 의존과 `services`↔`ingest`, `services`↔`workers` 순환이 있어, 폴더만 옮기면 순환이 그대로 따라간다. 이 문서는 계층 규칙까지 정한다.

별도 프로세스나 별도 DB로 나누지 않는다. 이유는 ADR-0043의 기각 근거와 같다.

## 2. "개별로 사용 가능"의 정의

다음을 모두 만족하면 달성한 것으로 본다. ADR-0043의 다섯 기준에 모듈 진입점 조건을 더했다.

1. 각 모듈이 자기 테이블·서비스·router·worker·schema를 자기 폴더 안에 갖는다.
2. 의존은 3절의 방향으로만 흐르고, 역방향 import는 테스트가 막는다.
3. `main.py`는 설정으로 고른 모듈의 router만 등록한다. 어느 모듈을 빼도 앱이 기동한다.
4. 각 모듈은 웹 없이 CLI로 실행된다.
5. worker 진입점이 모듈별로 있다. 현재 `workers/analysis.py`는 심층 검토와 C-2 선별을 한 프로세스에서 돌리므로 나눈다.
6. 각 모듈의 테스트가 상대 모듈 폴더 없이도 수집·통과한다.

## 3. 목표 구조와 의존 규칙

```text
web/backend/app/
├── core/            db, config, logging_setup, redaction, sql_dialect, constants,
│                    generation_config, run_id 유틸, actor 검증, 공용 오류
│                    models: audit_event, idempotency_record
├── lifecycle/       수집 회차와 기회 identity, 첨부 취득, 입찰 delta, 최종 결정
│                    ingest(loader·contracts·feedback), routers, services, worker(prespec_attachment)
├── screening/       C-1 공고 판정, C-2 발주계획 선별, 정책·큐·품질 게이트·스케줄·프로필 snapshot
│                    routers, services, worker, orchestrator, cli, contracts, prompts
├── deep_review/     문서 준비, 사전규격 개요 검토, 심층 검토, claim·evidence·보고서·최종 의견
│                    routers, services, agents, workers(document·deep_review), document_mcp, contracts
└── main.py          모듈 router 조립만 한다
```

허용 방향은 **왼쪽으로만**이다.

| import 하는 쪽 | 허용 대상 | 금지 |
|---|---|---|
| core | 표준 라이브러리, 외부 패키지 | 모든 도메인 모듈 |
| lifecycle | core | screening, deep_review |
| screening | core, lifecycle | deep_review |
| deep_review | core, lifecycle, screening(읽기 전용 seam 함수만) | screening 내부 ORM·service 직접 접근 |
| main | 네 모듈의 `router`·`cli` 공개 이름 | 모듈 내부 |

각 모듈 안의 계층은 `routers → services → models/core`이며, router는 parsing·HTTP 매핑만 한다(backend AGENTS.md). `schemas`는 `models`와 `services`를 import하지 않는다.

## 4. 소유권 지도

이주 시 이 표를 그대로 따른다. "확인" 표시는 이주 전에 한 번 더 검증한다.

### 4.1 테이블 (74)

| 모듈 | 테이블 |
|---|---|
| core (2) | audit_event, idempotency_record |
| lifecycle (16, 확인 1) | run, notice, notice_observation, order_plan, order_plan_observation, opportunity, opportunity_link, attachment, attachment_fetch, agency_portal, ingest_warning, bid_delta_comparison, bid_delta_attempt, bid_delta_item, bid_delta_evidence, bid_final_decision, prespec_overview_review(확인 §7) |
| screening (28) | judgment, judgment_revision, perspective, screening_evidence, counterargument, verification_item, matched_performance, review, review_revision, verification_answer, screening_execution, screening_attempt, company_profile_snapshot, quality_gate, quality_gate_evaluation, quality_gate_review, screening_policy, schedule_setting, schedule_reservation, schedule_execution, always_on_state, screening_audit_event, order_plan_screening_policy, order_plan_screening_execution, order_plan_screening_batch_attempt, order_plan_screening_result, order_plan_screening_artifact, order_plan_screening_feedback |
| deep_review (23, 개요 4) | content_object, content_object_location, content_scan, document_version, document_structure, document_block, document_bundle, document_bundle_item, profile_version, profile_evidence, analysis_policy_version, work_job, deep_review, deep_review_attempt, deep_review_stage, claim, evidence_ref, claim_evidence, report_revision, report_revision_evidence, validation_run, validation_check, final_opinion, prespec_overview_snapshot, prespec_overview_attempt, prespec_overview_result, prespec_overview_attempt_event |

core 2 + lifecycle 16 + screening 28 + deep_review 23 = 69이고, 사전규격 개요 5개(§7)를 더해 74다. 현재 안은 개요 결과 4개를 deep_review에, 사람 리뷰 상태 1개를 lifecycle에 두되 후자는 확인 대상이다.

분류 근거:

- `run`은 수집 회차다. 선별 실행이 run을 참조하지만 소유자는 수집이다.
- `judgment`·`review` 계열은 C-1 판정과 그에 대한 사람 리뷰이므로 선별이다. ADR-0043은 judgment를 core로 두었으나, 선별 모듈이 자기 판정을 소유하지 않으면 "개별 사용"이 성립하지 않는다.
- `schedule_*`·`always_on_state`는 `services/scheduler.py`가 선별 실행만 예약하므로 선별이다.
- `profile_version`·`profile_evidence`·`analysis_policy_version`은 `services/input_versions.py`와 `services/evidence.py`가 심층 검토 입력 동결에만 쓴다. 선별의 프로필은 `company_profile_snapshot`으로 따로 있다.
- `work_job`은 `services/deep_reviews.py`·`reports.py`·`agent_e2e.py`와 `agents/deep_review`만 쓴다.
- 문서 준비(content_object → document_version → document_structure → document_bundle)는 ADR-0043대로 심층 검토다.

### 4.2 services

| 모듈 | 현재 `app/services/` 파일 |
|---|---|
| core | object_store, clamav, `document_bundles.validate_actor`(공용 actor 검증으로 추출), 공용 오류 타입 |
| lifecycle | pipeline, attachments, assets, prespec_attachments, opportunity_tracking, opportunity_integrity, bid_delta, metrics(확인: Judgment·Review 집계를 포함하므로 선별 seam 함수로 읽도록 바꾼다) |
| screening | order_plan_screening, scheduler, scheduled_pipeline, profile, reviews, revisions, candidate_quality, vllm_client, mock_analysis_client(선별·심층 공용 mock이면 core) |
| deep_review | deep_reviews, deep_review_validation, document_bundles, document_converter, document_structures, evidence, input_versions, prespec_overview, reports, agent_e2e, bc_e2e |
| 삭제 | codex_exec_client. backend AGENTS.md가 개발에서도 사용하지 않는다고 정한 경로이며 findings에 외부 전송 범위 초과로 기록됨 |

### 4.3 routers

| 모듈 | router |
|---|---|
| lifecycle | runs, notices(확인: Judgment·Review 조회 8곳은 선별 seam으로), opportunities, pre_specs, attachments, portals, bid_delta, metrics, common(Judgment 참조 부분은 screening으로) |
| screening | screening, order_plans, policies, quality_gates, profile, schedule, reviews |
| deep_review | deep_reviews, document_bundles, reports |

### 4.4 worker · CLI · 기타

| 종류 | 현재 위치 | 이주 위치 |
|---|---|---|
| worker | `workers/document.py`, `workers/deep_review.py` | `deep_review/workers/` |
| worker | `workers/order_plan_screening.py` | `screening/workers/` |
| worker | `workers/prespec_attachment.py` | `lifecycle/workers/` |
| worker | `workers/analysis.py` | 폐지. `deep_review` worker와 `screening` C-2 worker 진입점으로 분리하고 Compose `analysis-worker`는 두 command 중 하나를 고르거나 두 서비스로 나눈다 |
| worker | `workers/document_protocol.py` | `deep_review/document_protocol.py`. `services/document_converter.py`가 이를 import하는 순환이 모듈 안으로 들어가므로 해소 |
| CLI | `screening/cli.py` | 유지 |
| CLI | `cli/run_bc_e2e.py`, `cli/score_candidate_quality.py`, `cli/import_profile_policy.py` | 각각 deep_review, screening, deep_review의 `cli.py` |
| agents | `agents/{common,decision,deep_review,document_preparation}` | `deep_review/agents/`. `routers`를 import하는 3곳은 공용 헬퍼를 `core`로 옮겨 끊는다 |
| ingest | `ingest/{loader,contracts,feedback,judgment_revisions,cli}` | `lifecycle/ingest/`. loader가 부르는 `services.revisions`·`reviews`(선별)와 `screening.contracts`는 역방향이므로 §5에서 끊는다 |
| document_mcp | `document_mcp/` | `deep_review/document_mcp/` |
| contracts | `contracts/deep_review/*.json` | `deep_review/contracts/`. C-2 계약은 `skills/bidops-screen/contracts/`가 정본이며 findings의 `experiments/` 의존 해소와 함께 처리 |
| schemas | `schemas/__init__.py`(89 클래스)와 하위 7개 | 각 모듈의 `schemas.py`. `__init__`의 `services.profile`·`screening.generation_config` import는 상수·검증기를 core로 옮겨 끊는다 |
| policies | `policies/analysis-policy-lean-v1.json` | `deep_review/policies/` |
| screening 내부 | `screening/seed_policy.json`, `baseline_company_profile.md`, `generation_config.py` | generation_config만 core로, 나머지 유지 |

### 4.5 테스트

`tests/`는 모듈 폴더를 그대로 따라간다. `tests/core/`, `tests/lifecycle/`, `tests/screening/`, `tests/deep_review/`, 그리고 앱 조립·migration·runtime 계약처럼 모듈을 가로지르는 것은 `tests/app/`에 둔다. `conftest.py`·`postgres.py`·`fakes/`·`fixtures/`는 `tests/` 루트에 남긴다.

| 대상 폴더 | 현재 테스트 파일 |
|---|---|
| tests/app | test_alembic_autogenerate, test_api_lifespan_t9, test_config_t9, test_db_migrations, test_health, test_logging_setup, test_models, test_models_runtime, test_postgres_harness, test_requirements_lock, test_runtime_database_privileges, test_static_frontend, test_t7_runtime_contract, test_object_store, test_minio_e2e |
| tests/lifecycle | test_api_notices, test_api_opportunities, test_api_pre_specs, test_api_runs, test_api_pipeline_service_t9, test_attachments, test_bid_delta_*, test_cumulative_identity, test_ingest_contracts, test_ingest_loader, test_legacy_attachment_provenance, test_metrics, test_opportunity_*, test_pipeline_service, test_prespec_attachment_*, test_revision_migrations |
| tests/screening | test_api_quality_policy, test_api_schedule_t9, test_api_screening, test_candidate_quality, test_generation_config_t15(core로), test_order_plan_screening_*, test_profile*, test_quality_*, test_reviews, test_revisions, test_review_revision_integration, test_scheduled_pipeline, test_scheduler*, test_screening_*, test_t15_runtime_binding, test_schemas_t9(확인) |
| tests/deep_review | tests/agents/*, test_acceptance_clis, test_bc_e2e, test_deep_review_*, test_deep_reviews, test_document_*, test_integration_t14, test_mock_analysis_client, test_prespec_overview*, test_reports |
| 삭제 | test_codex_exec_client |

## 5. 잘라야 할 의존 (실측)

2026-09-03 기준 `app/` 패키지 간 import를 실측한 결과 중, 3절 규칙에 어긋나는 것이다. 폴더 이주 전에 끊는다.

| 현재 import | 위반 종류 | 처리 |
|---|---|---|
| `db.py:83`, `models.py:45`, `db_admin.py:26` → `screening.generation_config` | core가 도메인을 봄 | `generation_config`를 `core/`로 이동 |
| `schemas/__init__.py:18` → `services.profile.PROFILE_PARSE_ERROR_CODES` | schema가 service를 봄 | 상수를 `core/constants` 또는 screening `schemas`로 |
| `schemas/__init__.py:653` → `screening.generation_config` | schema가 도메인을 봄 | 위와 같이 core 이동으로 해소 |
| `agents/*` → `routers` (3곳) | 하위가 상위를 봄 | 공용 헬퍼를 core 또는 deep_review services로 |
| `ingest/loader.py` → `services.revisions`, `services.reviews` | lifecycle이 screening을 봄 | 판정·리뷰 적재를 screening이 제공하는 적재 함수로 호출하거나, 판정 적재 부분을 `screening/ingest.py`로 분리 |
| `ingest/loader.py` → `screening.contracts`, `screening.generation_config` | lifecycle이 screening을 봄 | generation_config는 core로. `screening.contracts`의 판정 계약 파싱은 screening 적재 함수 안으로 |
| `ingest/feedback.py` → `services.revisions`, `services.reviews` | lifecycle이 screening을 봄 | 리뷰 피드백 적재를 `screening/`로 이동 |
| `screening/{orchestrator,worker,quality_gate}` → `ingest.loader.parse_run_id`, `deterministic_run_id`, `ingest_run` | 순환 | run_id 유틸은 core로. `ingest_run` 호출은 screening → lifecycle 방향이므로 허용 |
| `services/document_converter.py` → `workers.document_protocol` | services가 worker를 봄 | 둘 다 deep_review 안으로 옮기고 protocol을 service 옆에 둠 |
| `services/bid_delta.py` → `services.document_bundles.validate_actor` | lifecycle이 deep_review를 봄 | `validate_actor`를 core로 추출 |
| `services/document_bundles.py:677` → `Judgment` ORM 직접 조회 | deep_review가 screening 내부를 봄 | ADR-0043 seam 함수로 대체 |
| `routers/notices.py`, `routers/common.py`, `services/metrics.py` → `Judgment`, `Review` | lifecycle이 screening 내부를 봄 | screening이 공개하는 읽기 전용 조회 함수로 대체 |
| `runtime.py` → `ingest`, `screening`, `services` | 조립 코드 | `main.py` 옆에 두고 모듈 공개 이름만 사용하도록 정리 |

이 목록은 패키지 단위 grep 실측이므로 이주 직전에 파일 단위로 재측정한다.

## 6. seam 계약

모듈 사이의 읽기는 상대 모듈이 공개한 함수로만 한다. 공개 함수는 각 모듈 `__init__.py`에 이름을 올린다.

| 방향 | 공개 함수(안) | 대체하는 현재 접근 |
|---|---|---|
| screening → lifecycle | `lifecycle.get_notice`, `lifecycle.list_order_plans_for_run`, `lifecycle.ingest_run` | orchestrator·worker·C-2 서비스의 Notice·OrderPlan·Run 조회 |
| deep_review → lifecycle | `lifecycle.get_notice`, `lifecycle.lock_notice` | `services/deep_reviews.py:410`의 `with_for_update()` 잠금 경로 유지 |
| deep_review → screening | `screening.current_judgment(notice_id)` | `services/document_bundles.py:677` |
| lifecycle → screening | 없음. 금지 | notices router·metrics·common의 Judgment·Review 조회는 screening router 또는 screening이 lifecycle에 등록하는 projection 콜백으로 옮긴다 |

lifecycle이 선별 결과를 화면에 같이 보여 줘야 하는 경우(공고 목록의 등급 표시 등)는 두 가지 중 하나를 택한다. 첫째, frontend가 두 API를 따로 호출해 합친다. 둘째, screening이 기동 시 lifecycle에 projection 제공자를 등록한다. 기본은 첫째이며, 목록 N+1이 문제되면 둘째를 쓴다. 이 선택은 후속 ADR에 기록한다.

## 7. 사전규격 개요 검토의 소속

`services/prespec_overview.py`는 Notice와 `prespec_overview_*` 다섯 테이블 외에 ContentObject·DocumentVersion·DocumentStructure를 읽는다. 문서 테이블이 deep_review 소유이므로 lifecycle에 두면 lifecycle → deep_review 역방향이 생긴다.

결정(안): 사전규격 개요 검토는 **deep_review의 "개요 검토" 단계**로 둔다. ARCHITECTURE §5.4가 개요와 심층 검토를 한 흐름으로 다루는 것과 일치한다. 개요 뒤의 사람 결정 `계속 추적|보류|종료`는 ADR-0030의 추적 상태이며 lifecycle의 opportunity가 소유한다. 즉 deep_review가 결과를 내고, 사람의 추적 결정은 lifecycle API로 기록한다.

`prespec_overview_review`(사람 리뷰 상태)는 위 결정에 따라 deep_review로 가는 것이 일관되나, 추적 결정과 같은 화면에서 쓰이므로 §4.1에 "확인"으로 남긴다.

## 8. 진입점

- `main.py`: `BIDOPS_MODULES` 설정(기본 `lifecycle,screening,deep_review`)에 있는 모듈의 `router`만 `include_router`한다. core는 항상 포함된다. `/api/health`는 core가 소유한다.
- `runtime.py`: 모듈별 `start()`/`shutdown()`을 순서대로 호출하는 조립 코드로 줄인다. 모듈이 빠지면 그 모듈의 runtime도 만들지 않는다.
- worker: `python -m app.deep_review.workers.document`, `python -m app.deep_review.workers.deep_review`, `python -m app.screening.workers.order_plan`, `python -m app.lifecycle.workers.prespec_attachment`. Compose command를 함께 바꾼다. 이미지는 하나를 유지한다.
- CLI: `python -m app.screening.cli`, `python -m app.deep_review.cli`, `python -m app.lifecycle.ingest.cli`.
- Alembic: 단일 체인 유지. `alembic/env.py:18`의 `from app import models`를 네 모듈의 models import로 바꾼다. 테이블 이름·제약은 바뀌지 않으므로 새 revision은 만들지 않고, `test_alembic_autogenerate`의 빈 diff로 확인한다.

## 9. 경계 강제

문서와 리뷰만으로는 유지되지 않는다(ADR-0043 "교차 import 0건은 규율의 결과"). 다음 테스트를 `tests/app/test_module_boundaries.py`로 둔다.

- `app/` 아래 모든 `.py`의 import를 AST로 읽어 3절의 허용 표에 없는 모듈 간 import가 있으면 실패한다.
- 각 모듈의 `routers/*.py`가 `sqlalchemy.select`, `Session.execute`, `.query(`를 import·호출하면 실패한다. 현재 위반이 있으므로 도입 시점에는 파일별 허용 목록을 두고, 목록을 줄이는 방향만 허용한다.
- `schemas`가 `models`·`services`를 import하면 실패한다.

이 테스트는 이주 첫 단계에서 "현재 위반 목록"을 허용 목록으로 갖고 시작해, 단계마다 목록을 줄인다. 새 위반이 추가되면 즉시 실패한다.

## 10. 적용 순서

각 단계는 앞 단계의 동작을 바꾸지 않으며 단계마다 전체 backend suite와 `test_alembic_autogenerate`가 통과해야 한다. 상세 작업 분할은 별도 PLAN에서 한다.

1. 경계 테스트 도입. 현재 위반을 허용 목록으로 기록한다.
2. core 확정. generation_config, run_id 유틸, validate_actor, 공용 상수·오류를 `core/`로 옮기고 §5의 역방향 의존을 끊는다.
3. seam 함수 도입. §6의 공개 함수를 만들고 직접 ORM 접근을 대체한다.
4. `models.py` 분할. §4.1대로 네 파일로 나누고 `env.py`를 갱신한다.
5. 폴더 이주. §4.2~4.5대로 services·routers·workers·agents·ingest·schemas·tests를 옮긴다. 로직 변경 없음.
6. 진입점 분리. `main.py` 모듈 선택, `runtime.py` 조립, worker 진입점과 Compose command.
7. 단독 실행 검증. §2의 여섯 조건을 각각 확인하고 결과를 `docs/tracking/status.md`에 기록한다.

## 11. 검증 기준

```bash
cd web/backend && .venv/bin/python -m pytest tests/ -q     # 디렉터리 전체 지정. 개별 파일 지정 시 PostgreSQL 테스트가 조용히 skip된다
./run-tests.sh
cd web/frontend && npm run build && npm run test:visual
```

- 2026-09-03 기준선: backend 1097 passed, 5 skipped, 2 failed. 실패 2건은 `test_screening_orchestrator.py`의 기존 결함이며 clean main에서도 재현된다. 이 2건 외의 실패만 회귀로 본다.
- 파이프라인 145 passed, frontend visual 646 passed, 10 skipped.
- 각 단계 완료 시 `test_module_boundaries`의 허용 목록 크기가 줄었는지 확인한다.
- 7단계에서 `BIDOPS_MODULES=screening`과 `BIDOPS_MODULES=deep_review`로 각각 기동해 `/api/health`와 해당 모듈 API가 응답하고 상대 모듈 경로는 404임을 확인한다.

## 12. 범위 밖

다음은 이 설계와 독립이며 findings·ADR에서 따로 다룬다. 이주 중에 함께 고치지 않는다.

- 운영 백엔드의 `experiments/order-plan-screening/config/` 런타임 의존 (findings)
- C-1과 C-2의 모델 호출 경계 불일치 (findings, ADR-0043 결과 절)
- `ingest/loader.py` 5,085줄의 도메인별 분할. 폴더 이주 뒤 lifecycle 안에서 진행한다
- router 안의 select를 service로 내리는 작업. 경계 테스트 허용 목록으로 추적만 한다
- Compose·스크립트 폴더 재배치, 의존성 단일 원천, CI 도입

## 13. 확인이 필요한 항목

이주 전에 코드에서 확인하고 결과를 이 문서에 반영한다.

- `attachment`(lifecycle)가 `content_object`(deep_review)를 FK로 참조하는지. 참조하면 문서 준비의 content_object·content_scan·document_version을 lifecycle로 옮기고 deep_review는 document_structure 이후만 소유하는 대안을 검토한다.
- `prespec_overview_review`의 소속 (§7).
- `services/metrics.py`와 `routers/notices.py`의 Judgment·Review 조회를 seam 함수로 바꿀 때 목록 화면의 응답 지연이 허용 범위인지.
- `mock_analysis_client`가 선별·심층 양쪽 mock인지. 양쪽이면 core, 한쪽이면 그 모듈.
- `test_schemas_t9`, `test_generation_config_t15`의 실제 대상 모듈.
- Compose `analysis-worker`를 두 서비스로 나눌 때 `document-scratch`·`analysis` network 배정과 lease concurrency 1 유지 방법.
