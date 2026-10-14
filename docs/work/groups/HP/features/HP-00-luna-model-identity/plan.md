# codex-exec 모델 identity 전환 (gpt-6-luna / high) — plan

- 기능 ID: `HP-00-luna-model-identity`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-14 (같은 날 독립 검사 1·2차 지적 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/services/luna_identity.py | 신규 | PROVIDER/MODEL/REASONING_EFFORT/CLI_VERSION/HP_POLICY_IDENTITY/COMPANY_POLICY_IDENTITIES/ALLOWED_*/matches_runtime |
| web/codex-runner/runner.py | 수정 | MODEL·REASONING_EFFORT·CLI_VERSION 상수, argv |
| web/codex-runner/Dockerfile | 수정 | `@openai/codex@0.162.1` |
| web/backend/app/deep_review/services/luna_client.py | 수정 | identity 사용, cli_version 검사 |
| web/backend/app/deep_review/policies/analysis-policy-luna-hp-v1.json | 신규 | canonical 정책(demo-v1 + identity 키 4개) |
| web/backend/app/deep_review/policies/analysis-policy-luna-v5.json | 신규 | canonical 정책(v4 + identity 키 3개), NULL 계보용 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | hp-v1 파일 매핑, v5 버전 판정, 회사 identity 집합의 path_limit·전역 active 거부, 모델 허용 집합 |
| web/backend/app/deep_review/services/company_deep_review.py | 수정 | 정책 선택 순서(모델→identity 집합→구조), preview/감사 표식을 정책 row에서 |
| web/backend/app/deep_review/services/company_slices.py | 수정 | `policy_identity in COMPANY_POLICY_IDENTITIES` |
| web/backend/app/deep_review/services/luna_inputs.py | 수정 | `snapshot` 안 모델 일치 강제, 표식을 정책 row에서 |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | NULL 계보 create/attempt 강제, worker claim guard·회사 분기 집합, attempt view·invocation metadata 표식 |
| web/backend/app/deep_review/services/assumption_inputs.py, assumption_analysis.py | 수정 | identity 상수, worker 강제 |
| web/backend/app/deep_review/schemas/deep_reviews.py (및 회사 preview DTO) | 수정 | Literal 값 |
| web/backend/tests/deep_review/test_codex_runner.py, tests/app/test_luna_deep_review.py(설정 fixture를 v5로), tests/app/test_company_luna_policy.py, tests/app/test_company_deep_review_binding.py, tests/app/test_company_e2e.py, tests/app/test_assumption_analysis.py, tests/deep_review/test_assumption_inputs.py | 수정 | T1~T9(가짜 runner `cli_version` 0.162.1 포함) |
| web/frontend/src/lib/companyApi.ts, src/components/assumption-analysis/Request.tsx | 수정 | 타입·문구(preview 뒤 settings 표시) |
| web/frontend/tests/fixtures/{company-demo.ts,luna-review.json,luna-relation-warning.json,luna-validation-off.json,assumption-analysis.json}, tests/{luna-deep-review,company-review}.spec.ts, 가정 분석 spec | 수정 | T10 |
| docker-compose.hp-local.yml | 신규 | codex-runner `image: ${BIDOPS_DEMO_CODEX_RUNNER_IMAGE:?…}` overlay |
| docs/contracts.md, docs/work/demo-contract.md | 수정 | ADR-0069 절 두 문장, DEMO-03 정책 줄, §9 한 줄 |
| docs/validation-runs/<날짜>-hp/HP-00/README.md | 신규 | 정책 sha256 2개, 이미지 태그·compose 집합, env 교체, smoke 기록(또는 pending 사유) |

## 작업 순서

1. STEP-001 identity 모듈·runner·client [standard]
   - 목표: 상수 한 곳과 runner 상수가 같고 argv·cli_version 검사가 새 값으로 돈다. 회사 e2e·binding 테스트의 가짜 runner도 새 cli_version을 돌려준다.
   - 작업 대상: luna_identity.py(신규), runner.py, Dockerfile, luna_client.py, test_codex_runner.py, test_company_e2e.py·test_company_deep_review_binding.py의 가짜 runner.
   - 검증: T1, T2, T9(가짜 runner 부분).
2. STEP-002 정책 hp-v1·v5 발행·회사 identity 집합·검증 [complex]
   - 목표: 두 파일이 canonical bytes로 존재하고 import·버전 판정·전역 거부/허용·회사 선택(검사 순서 고정)·worker 회사 분기·slice 검증이 집합 기준으로 동작한다.
   - 작업 대상: 정책 파일 2개, input_versions.py, company_deep_review.py(정책 선택), company_slices.py, deep_reviews.py(회사 분기), test_company_luna_policy.py, test_luna_deep_review.py(전역 거부·worker 거부·설정 fixture v5), test_company_deep_review_binding.py.
   - 검증: T3, T4, T6(hp-v1·v5 부분)(PG).
3. STEP-003 모델 일치 강제와 표식 출처 [complex]
   - 목표: `snapshot`·create/attempt·worker claim·가정 분석 worker가 정책 모델≠identity면 호출 없이 닫히고, preview·감사·attempt view·invocation metadata·가정 분석이 정책 row/identity 값을 쓰며 legacy 조회가 유지된다.
   - 작업 대상: luna_inputs.py, deep_reviews.py(create/attempt/claim/_attempt_view/metadata), company_deep_review.py(preview 응답), assumption_inputs.py, assumption_analysis.py, schemas, 관련 테스트.
   - 검증: T5, T6(legacy 거부 부분), T7, T8(PG 변형 포함).
4. STEP-004 프런트 타입·문구·fixture [standard]
   - 목표: 화면과 fixture가 새 값을 표시하고 Request 문구는 preview 뒤 settings 값을 보이며 build가 통과한다.
   - 작업 대상: companyApi.ts, Request.tsx, fixtures, spec 3종.
   - 검증: T10(`npm run build`, 해당 spec).
5. STEP-005 계약 문서·overlay·증거 README [standard]
   - 목표: contracts.md(ADR-0069 절 두 문장·DEMO-03 정책 줄)·DEMO 계약 §9를 고치고 hp-local overlay를 추가하며 정책 sha256·이미지 절차를 기록한다.
   - 작업 대상: docs/contracts.md, docs/work/demo-contract.md, docker-compose.hp-local.yml, validation-runs README.
   - 검증: `docker compose -f docker-compose.yml -f docker-compose.luna.yml -f docker-compose.hp-local.yml config`(env 주입 확인), `python3 scripts/feature_status.py doctor _`, diff 확인.
6. STEP-006 격리 스택 runner 재빌드·env 교체·smoke [standard]
   - 목표: `bidops-local` codex-runner를 `bidops-local:codex-runner-<YYYYMMDD>`로 올리고(hp-local overlay), hp-v1을 import·선택한 뒤 사용자 승인 1건으로 identity를 확인한다.
   - 작업 대상: 사용자 확인 뒤 build·태그·교체(실행 중 스택의 compose 집합에서 증거 overlay를 hp-local overlay로 바꾼 집합), hp-v1·v5 import, `env/demo.env`의 `BIDOPS_DEMO_DEEP_REVIEW_POLICY_VERSION_ID`·`BIDOPS_DEMO_CODEX_RUNNER_IMAGE`, 승인된 preview 1건.
   - 검증: T11(수동, 건별 승인; 승인 없으면 pending으로 기록).

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | S | 낮음 | standard | 상수·argv·검사 값 교체 |
| STEP-002 | M | 높음 | complex | canonical bytes·불변 정책·identity 집합·검사 순서 불변식 |
| STEP-003 | M | 높음 | complex | 여러 경로의 fail-closed 규칙과 legacy 조회 불변식 |
| STEP-004 | S | 낮음 | standard | 타입·문구·fixture |
| STEP-005 | S | 낮음 | standard | 문서·overlay |
| STEP-006 | S | 중간 | standard | 운영 변경·외부 호출 보호 장치(사용자 확인) |

## 검사 명령과 증거

```sh
cd web/backend
python -m pytest tests/deep_review/test_codex_runner.py tests/app/test_luna_deep_review.py tests/app/test_company_luna_policy.py tests/app/test_company_deep_review_binding.py tests/app/test_company_e2e.py tests/app/test_assumption_analysis.py tests/deep_review/test_assumption_inputs.py -q
# PostgreSQL 변형: 일회용 postgres:17.11, BIDOPS_TEST_POSTGRES_URL, BIDOPS_PRESPEC_OVERVIEW_ENABLED=false
cd ../frontend && npm run build && npx playwright test tests/luna-deep-review.spec.ts tests/company-review.spec.ts --project=app
sha256sum web/backend/app/deep_review/policies/analysis-policy-luna-hp-v1.json web/backend/app/deep_review/policies/analysis-policy-luna-v5.json
docker compose -f docker-compose.yml -f docker-compose.luna.yml -f docker-compose.hp-local.yml config
```

T11은 사용자 확인 뒤 `bidops-local`에서만 실행하고 명령·시각·attempt id·metadata를 README에 적는다. 실행하지 않았으면 "pending: 승인 대기"로 적는다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| gpt-6-luna가 격리 컨테이너 계정에서 거부됨 | smoke `model_access_denied` | 호스트 codex 계정과 auth.json 동일성 확인, HP-03 전까지 막힘으로 보고 |
| CLI 0.162.1 플래그 변경 | T1의 `codex exec --help` 대조 실패 | 플래그 차이를 README에 적고 runner argv 조정 뒤 T1 재실행 |
| v5 버전 판정이 v4와 섞임 | `_approved_policy_path`가 v5 파일에 v4 경로를 돌려줌 | 판정 키를 `execution.cli_version`으로 고정하고 T3에 v4·v5 쌍 추가 |
| legacy fixture·row가 Literal에 걸림 | 테스트 422/ValidationError | attempt/report는 `str|None` 유지, preview만 Literal |
| 정책 파일 bytes가 canonical과 다름 | `load_canonical_policy` 거부 | 발행 스크립트는 `canonical_json_bytes`로 쓰고 sha256 기록 |
| 격리 스택 compose 집합이 워크트리마다 달라 runner 교체가 다른 스택에 적용됨 | `docker inspect` config_files 불일치 | README에 집합을 적고 hp-local overlay를 포함한 같은 집합으로만 교체 |

## 증명

- docs: HP 공통 계약 §0·contracts.md·intent/spec/plan 일치, `doctor _`, diff.
- tests: T1~T9 pytest 로그(exit code).
- postgres: T3~T9 PostgreSQL 변형 로그.
- frontend: T10 build·spec 로그.
- api_guard: T5·T6·T8 fail-closed(호출 0)·T2 identity mismatch 로그로 외부 전송 보호 확인.
- real_data_run: T11 smoke(사용자 승인·격리 스택) 또는 pending 사유.

## 결과

구현 후 작성한다.
