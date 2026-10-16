# 루트랩 회사 근거 등록·버전 고정 — plan

- 기능 ID: `RL-00-company-ground-truth`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-16 (독립 검사 1차 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/core/company_ontology.py | 수정 | `FACT_STATUSES`·`ORIGINS`·origin 고정 해제·`company_fictional_required` 분기·노드 value 확장 표 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | profile v2 `origin` real_company·status 4값·노드/관계 origin 허용 집합 |
| web/backend/app/deep_review/schemas/company_knowledge.py | 수정 | `FactStatus`·`NodeOrigin` 확장, profile/evidence view origin, `CompanyContextView` |
| web/backend/app/deep_review/services/company_knowledge.py | 수정 | status·origin 조합 검증, 실회사/가상 분기, value `{held,detail}` 허용, profile v2 origin, dry-run 출력 키 |
| web/backend/app/lifecycle/services/company_context.py | 수정 | 실회사 1곳 규칙(`real_company_exists`), 감사 metadata 요청값 |
| web/backend/app/deep_review/services/company_knowledge.py(prepare) | 수정 | `fictional_requires_demo`(dry-run 포함), `company_fictional_required` 폐기 |
| web/backend/app/deep_review/routers/company_knowledge.py, schemas/company_knowledge.py | 수정 | `GET /api/company`(`CompanyContextView`), 오류 `company_not_registered` |
| web/backend/app/lifecycle/schemas/workload.py, services/workload.py, deep_review 확장점 제공자 | 수정 | 키 `company_attention` 어휘(lifecycle)·값(deep_review) |
| web/frontend/src/lib/api.ts, lib/types.ts, tests/api-mock.ts | 수정 | `WorkloadKey` 어휘 동기 |
| web/backend/app/deep_review/cli/import_company_knowledge.py, services/company_knowledge.py(`_exit_for`·오류 매핑) | 수정 | `real_company_exists` exit 2, 출력 키 2개 |
| web/backend/app/main.py | 수정 | 회사 라우터 demo 플래그 분리, `_is_demo_only_path` 범위 축소 |
| web/frontend/src/lib/apiErrors.ts | 수정 | `company_not_registered` |
| web/backend/app/core/config.py | 수정 | `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS` |
| web/backend/tests/app/test_company_knowledge_cli.py, test_company_knowledge_api.py, test_company_context.py | 수정 | T1~T5 |
| web/backend/tests/app/test_company_context_postgres.py | 신규 | T6·T7(`requires_postgres`) |
| web/frontend/src/pages/CompanyPage.tsx | 신규 | `/company` 읽기 전용 화면 |
| web/frontend/src/components/company/{AttentionList,FactGroupTable}.tsx | 신규 | ui-spec §3 AttributeList·표 규칙 |
| web/frontend/src/routes.tsx, components/shell/route-meta.ts, components/shell/Sidebar.tsx | 수정 | `/company` 라우트·메타·"회사 근거" 링크 `/profile`→`/company`·건수·워크스페이스 이름(`/api/company`) |
| web/frontend/src/themes/bidops/bidopsTheme.ts(주석 1줄) | 수정 | 추정값 pill blue 허용 주석 |
| web/frontend/src/lib/companyApi.ts, components/company/KnowledgeGraph.tsx | 수정 | status·origin Literal 확장, `getCompanyContext` |
| web/frontend/tests/company-ground-truth.spec.ts | 신규 | T8 |
| docs/work/demo-contract.md, docs/work/hp-contract.md(§1·§5 주석), docs/contracts.md, docs/business-rules.md, docs/operations.md, docs/1016_rootlab-redefinition/ui-spec.md(§1.3·§1.4·§3·§4.6·§7), docs/ADR.md | 수정 | RL 개정 절·REST·상태 대응·재등록 절차·화면 정본 읽기 전용 반영·결정 한 줄 |
| docs/validation-runs/<날짜>-rl/RL-00/README.md | 신규 | fixture sha256·dry-run 결과(T9) |

## 작업 순서

1. STEP-001 계약 enum·검증 규칙 [complex]
   - 목표: status `proposed`·origin 7값·조합 규칙·`{held,detail}` value·실회사/가상 분기가 schema와 service 양쪽에서 같은 결과를 낸다.
   - 작업 대상: core/company_ontology.py, services/input_versions.py, schemas/company_knowledge.py, services/company_knowledge.py(검증·projection·출력 키·`real_company_exists` 매핑), cli/import_company_knowledge.py.
   - 검증: T1(활성화 뒤 GET 200 포함), T2, T5, 기존 `test_company_knowledge*` 전부.
2. STEP-002 실회사 등록 규칙과 demo 분리 [complex]
   - 목표: `register_company`가 `is_fictional=false`를 받고 실회사 1곳을 강제하며, 미들웨어 가드가 `companies_router`·`company_knowledge_router`만 demo 플래그 없이 통과시킨다. 가상 등록은 demo 플래그에만 묶인다.
   - 작업 대상: lifecycle/services/company_context.py, main.py, config.py.
   - 검증: T3, T4.
3. STEP-003 `GET /api/company`와 오류 code [standard]
   - 목표: 단일 회사 조회 REST(`CompanyContextView`, deep_review 소유)·`company_not_registered`·workload `company_attention`(lifecycle 어휘 + deep_review 값). PostgreSQL strict shape, 모듈 경계 검사 통과.
   - 작업 대상: deep_review routers/company_knowledge.py·schemas, lifecycle schemas/workload.py·services/workload.py, deep_review 확장점, api.ts·types.ts·api-mock.ts, apiErrors.ts, test_company_context_postgres.py, `tests/app/test_module_boundaries.py`.
   - 검증: T6, T7.
4. STEP-004 루트랩 회사 파일 작성과 dry-run [complex]
   - 목표: spec "구성 규칙"대로 fixture 파일을 만들고 dry-run 오류 0을 얻는다. 값은 profile §8·homepage-profile·preferences의 confirmed/proposed/unknown만 옮기며 새 사실을 만들지 않는다.
   - 작업 대상: `~/orca/fixtures/company/rootlab/{ontology.v2.json,rootlab.source.v1.json}`(Git 밖, 온톨로지 rl-v2 발행 포함), validation-runs README(출처 쪽·URL 기록).
   - 검증: T9(`import-company-knowledge --dry-run` exit 0, status_counts 기록).
5. STEP-005 `/company` 화면 [standard]
   - 목표: 읽기 전용 화면(세 수치·확인 필요 목록·그룹 표·상단바), 사이드바 건수·워크스페이스 이름 연결, 운영 정보 금지 검사.
   - 작업 대상: CompanyPage.tsx, company 컴포넌트 2개, routes.tsx, route-meta.ts, Sidebar.tsx(`company_attention`), companyApi.ts, KnowledgeGraph.tsx, company-ground-truth.spec.ts.
   - 검증: T8(`npm run build`, Playwright app 프로젝트 해당 spec, 1280·1440).
6. STEP-006 격리 등록·활성화 [standard]
   - 목표: bidops-local에서 import → activate → REST 확인. 운영 DB 아님.
   - 작업 대상: bidops-local 컨테이너, README(ID·sha256).
   - 검증: T7 실제 경로 1회(`GET /api/company`, `/profile` facts 수 = 파일 비evidence 노드 수).
7. STEP-007 문서 개정 [standard]
   - 목표: demo-contract §1·§3·§4(CLI import 출력 shape 포함) RL 개정 절, hp-contract §1·§5 주석, contracts.md 회사 REST·value 확장 표·workload 키(ADR-0067 예외 한 줄), business-rules.md 상태 대응, operations.md "회사 근거 갱신", ui-spec §1.3·§1.4(`attention` 추가·`/profile` 리다이렉트 문구 삭제)·§3·§4.6·§7 읽기 전용·blue 반영, ADR.md 한 줄(ADR-0048 "추정값 pill만 blue" 개정 포함).
   - 작업 대상: 위 문서 7개 + bidopsTheme.ts 주석.
   - 검증: `python3 scripts/feature_status.py doctor _`, diff 검토.

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | enum 조합 불변식·value 타입 확장·v1/v2 분기 보존 |
| STEP-002 | M | 높음 | complex | 등록 경합·1곳 강제·라우터 등록 순서(SPA fallback 전) |
| STEP-003 | S | 중간 | standard | 기존 라우터 패턴 복제 |
| STEP-004 | M | 높음 | complex | 사실을 지어내지 않고 세 문서의 상태를 정확히 옮기는 판단 |
| STEP-005 | M | 중간 | standard | ui-spec·공통 컴포넌트가 닫혀 있음 |
| STEP-006 | S | 낮음 | standard | 절차 실행 |
| STEP-007 | S | 낮음 | standard | 문서 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 회사 파일에 제안값을 `confirmed`로 옮김(사실 조작) | status_counts의 confirmed가 profile §8·preferences의 confirmed 행 수보다 많음 | STEP-004 검증에서 문서별 행 수와 대조, 어긋나면 `proposed`/`unknown`으로 되돌림 |
| 가드 완화로 가상회사·Luna 전송 경로가 운영에 열림 | demo off에서 `/companies`·`company-comparison`·`company_analysis` POST 200 | 통과 라우터를 둘로 한정, T6에서 404 유지 고정 |
| value 확장이 기존 가상 파일을 깨뜨림 | 기존 DEMO·HP fixture import 실패 | 추가 허용만(기존 strict 형태 그대로 통과), T4 |
| v1 가상 경로 회귀 | 기존 `test_company_knowledge*` 실패 | enum 확장은 추가만, 분기는 `is_fictional`로; 기존 테스트 전부 통과가 STEP-001 종료 조건 |
| 화면이 `unknown`을 부족처럼 보이게 함(색·문구) | "확인 필요"가 error 색 | ui-spec 상태 pill 규칙(warning) 고정, T8에 색 토큰 검사 |
| 노드 256 상한 초과 | dry-run `source_invalid` | 최근 연도 실적부터 채우고 나머지 README |

## 증명

- docs: `python3 scripts/feature_status.py doctor _` + demo-contract/contracts/business-rules/operations diff 검토.
- tests: `cd web/backend && pytest tests/app/test_company_knowledge_cli.py tests/app/test_company_knowledge_api.py tests/app/test_company_context.py tests/deep_review/test_company_knowledge.py`.
- postgres: 일회용 `postgres:17.11` + `BIDOPS_TEST_POSTGRES_URL`로 `tests/app/test_company_context_postgres.py`·`test_company_knowledge_api.py`.
- frontend: `cd web/frontend && npm run build && npx playwright test --project=app company-ground-truth.spec.ts common-interactions.spec.ts`.
- api_guard: 비적용 — 외부 호출 없음. 단 demo off에서 가상 경로 404 유지(T6)를 여기 증거로 연결.
- real_data_run: 비적용(RL-05가 담당).

## 결과

run `rla-20261016`(배치 A), 기능 브랜치 `sdlc/rla-20261016-RL-00-company-ground-truth`, 기준 c93da20. 상세는 `docs/work/_runs/rla-20261016/RL-00-company-ground-truth.md`.

- 단계 7/7 done. STEP-001~003·004·005·007 위임, STEP-006은 리더가 실행.
- 증명: tests 140 passed·85 skipped(PG 변형)·exit 0; postgres(일회용 17.11) 255 passed·exit 0(모듈 경계·runtime 권한·alembic drift 포함); frontend build·contrast 8/8·Playwright app 41 + company-layout 20 passed; T9 dry-run exit 0·errors 0; STEP-006 bidops-local `bidops_rla` import·activate·REST 확인.
- 사용자 결정(run 중): bidops-local 검증은 새 DB `bidops_rla`(기존 DB는 HP-03 migration 0039로 이력 분기); demo-on `/companies/:id/profile → /company` 리다이렉트 적용으로 DEMO 프로필 화면 spec 11건(company-graph 10·company-layout 1) 삭제·1건 교체.
- spec 밖 구현 판단: contrast 게이트 blue 금지에 `.co-pill.is-proposed` 단일 예외(spec의 ADR-0048 개정 반영); "곧 만료"는 지난 유효기간 포함; `company_attention` 미집계 사유 `company_profile_not_ready`·`processing_failed`; fixture project 63행(연차 분리), `excl:*` 6개(대기업 SI 행은 kind 없음).
- 독립 리뷰: BLOCKING 없음. 문서 불일치 2건은 반영. backlog: `agent_proposal`을 `proposed` 전용으로 좁히기, `company_attention_count`에 lineage 검사, import 단계 demo 재검사, AttentionList 제목과 ui-spec "확인이 필요한 것" 문구 통일, 미사용 `CompanyProfilePage.tsx` 정리.
- 기존 실패(이번 변경과 무관, HEAD 동일): backend `tests/core/test_postgres_harness.py::test_profile_target_runs_without_docker`(company-profile.md 8절 vs 파서 7절 기대), frontend design-shell 2·admin-workspace-consistency 2·route-context 12(RL 셸 재설계 뒤 낡은 기대값).
