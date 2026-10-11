# 그래프 근거 기반 회사 핏과 Luna 심층검토 — plan

- 기능 ID: `DEMO-03-grounded-analysis`
- 작성일: 2026-10-06
- 근거: [intent](intent.md), [spec](spec.md)

## 변경 파일

경로는 저장소 루트 기준. `<next>` migration은 구현 시 실제 단일 head의 후속 번호로 생성한다.
번호를 선점하지 않으며 core/db.py의 runtime head와 `scripts/runtime-privileges.sql` 권한을 함께 갱신한다(migration에 GRANT를 쓰지 않는다).
기준은 별도 데모 브랜치와 `bidops-local` 격리 자원이다. main이나 운영에 반영하지 않는다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/backend/app/deep_review/services/company_knowledge_retrieval.py | 신규 | concept/경로/coverage |
| web/backend/app/deep_review/services/company_fit.py | 수정 | v2 입력·결과·현재성 |
| web/backend/app/deep_review/services/company_fit_runner.py | 수정 | company_id 분기 claim·입력 구성 |
| web/backend/app/deep_review/cli/enqueue_company_fit.py | 신규 | 회사·공고별 핏 enqueue CLI(worker 역할, dry-run) |
| web/backend/app/deep_review/services/luna_inputs.py | 수정 | 기존 preview·승인에 회사/graph 입력·company_id 결속 |
| web/backend/app/deep_review/services/input_versions.py | 수정 | 회사 binding resolver·demo 정책 `_approved_policy_path` 매핑 |
| web/backend/app/deep_review/services/deep_reviews.py | 수정 | 회사 생성·중복·재시도 |
| web/backend/app/deep_review/services/narrative_inputs.py | 수정 | graph 근거·slice·coverage(분할기 `_requirements`는 그대로 재사용) |
| web/backend/app/deep_review/routers/company_analysis.py | 신규 | 분석 REST |
| web/backend/app/deep_review/services/company_projection.py | 신규 | batch 목록/비교 |
| web/backend/app/deep_review/schemas/company_analysis.py | 신규 | DTO |
| web/backend/app/deep_review/policies/analysis-policy-luna-demo-v1.json | 신규 | DEMO-00 v4 기반 불변 demo 정책 |
| web/backend/app/workers/analysis.py | 수정 | 기존 공용 슬롯 연결 |
| web/backend/app/lifecycle/extensions.py | 수정 | 회사 읽기 projection 계약 |
| web/backend/app/main.py | 수정 | router/provider 조립 |
| web/backend/alembic/versions/<next>_company_analysis.py | 신규 | fit 정책 테이블·company/graph 열·fit attempt 정책 FK 분기(deep_policy nullable+company_fit_policy, CHECK)·provenance_jsonb·DeepReviewPreview/Approval company_id·복합 FK |
| scripts/runtime-privileges.sql | 수정 | 새 테이블·열 권한(핏 attempt INSERT는 worker 전용 유지) |
| web/backend/tests/app/test_runtime_database_privileges.py | 수정 | 새 권한 기대값 |
| web/backend/tests/app/boundary_map.py | 수정 | deep_review가 import하는 lifecycle 공개 파일 추가 |
| web/backend/app/core/api_errors.py | 수정 | 회사 분석 오류 code 등록(또는 deep_review router 허용 목록) |
| web/backend/tests/app/test_company_analysis.py | 신규 | fake 제품 종단 |
| web/backend/tests/deep_review/test_company_knowledge_retrieval.py | 신규 | 매핑·누락 |
| web/backend/app/deep_review/models.py | 수정 | CompanyFitPolicyVersion·company/graph 열·fit attempt 정책 FK 분기·provenance_jsonb(fit attempt·DeepReviewPreview)·DeepReviewPreview/Approval company_id·복합 FK |
| web/backend/app/core/db.py | 수정 | runtime head |
| web/backend/app/core/config.py | 수정 | 목적별 policy UUID |
| web/backend/app/deep_review/__init__.py | 수정 | projection facade |
| web/backend/app/deep_review/cli/__init__.py | 수정 | policy import·enqueue-company-fit dispatch |
| web/backend/app/deep_review/cli/import_profile_policy.py | 수정 | demo policy strict import |
| web/backend/app/deep_review/policies/company-fit-demo-v2.json | 신규 | 불변 목적별 fit policy |

## 작업 순서

1. STEP-001 그래프 검색과 coverage [complex]
   - 목표: 그래프 검색과 coverage의 수용 조건을 충족한다.
   - 작업 대상: 매핑·경로·필수 사실·slice.
   - 검증: spec T1; 아래 명령과 해당 단계 증거.
2. STEP-002 회사 핏 요청과 실행 [complex]
   - 목표: 회사 핏 CLI enqueue와 실행의 수용 조건을 충족한다.
   - 작업 대상: enqueue CLI(worker 역할)·enqueue 시 입력 동결·runner company 분기·SW=Y 자격·v2 결과.
     deep_policy_version_id가 nullable이 되므로 NOT NULL을 전제한 `company_fit.py`(현재성 비교)·`company_fit_runner.py`(enqueue)·`tests/deep_review/test_company_fit.py`를 함께 고친다.
   - 검증: spec T2,T4,T8; 아래 명령과 해당 단계 증거.
3. STEP-003 Luna 승인과 회사 binding [complex]
   - 목표: Luna 승인과 회사 binding의 수용 조건을 충족한다.
   - 작업 대상: 기존 DeepReviewPreview/Approval company_id·preview/재시도·현재성·graph FK·SW=Y 자격.
   - 검증: spec T2,T3,T6; 아래 명령과 해당 단계 증거.
4. STEP-004 새 Luna 정책과 근거 참조 [complex]
   - 목표: DEMO-00 v4 기반 demo 정책과 그래프 근거 참조의 수용 조건을 충족한다.
   - 작업 대상: v4 대비 회사·그래프 입력 설명 차이만·승인 경로 매핑·필수 검증·정책 호환.
   - 검증: spec T4,T5; 아래 명령과 해당 단계 증거.
5. STEP-005 회사별 읽기와 비교 [complex]
   - 목표: 회사별 읽기와 비교의 수용 조건을 충족한다.
   - 작업 대상: projection·서버 필터·pagination·입력 비교·공통 §10 FrozenProvenance 저장/GET.
   - 검증: spec T6,T7 (queued/completed GET, 승인 snapshot의 hash·최상위 identity 일치, 재시도 current_attempt 선택); 아래 명령과 해당 단계 증거.
6. STEP-006 교차 경로 통합 [complex]
   - 목표: 교차 경로 통합의 수용 조건을 충족한다.
   - 작업 대상: fake E2E·공용 슬롯·legacy 분리.
   - 검증: spec T2~T8; 아래 명령과 해당 단계 증거.
7. STEP-007 실제 격리 스택 준비와 호출 전 게이트 확인 [complex]
   - 목표(2026-10-11 재정의): 구현된 회사·graph 입력 경로를 실제 `bidops-local` 스택에 단계별 사용자 확인으로 적용하고(백업·0036 migration·3사 import/activate·demo 정책 import·demo flag·codex-runner), 회사 미리보기가 모델 호출 없이 동결 입력을 만들거나 fail-closed되는 것을 확인한다. 실제 Luna 대표 1건 보고서(원안)는 DEMO-05로 이관했다.
   - 작업 대상: 이미지·migration·CLI import·env/demo.env·compose overlay·preview 호출·읽기 전용 진단. 검사 완화·SQL 보정·모델 호출 없음.
   - 검증: spec T9(재정의); `docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`와 `_runs/demo0203-20261009/demo03-step007-*.log`.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-002 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-003 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-004 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-005 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-006 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-007 | M | 높음 | complex | 실제 외부 전송·완성 보고서 품질 게이트 |

## 검사 명령과 증거

아래는 구현 후 실행할 명령이다. 신규 테스트는 아직 없으며 통과를 주장하지 않는다.

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_company_analysis.py tests/deep_review/test_company_knowledge_retrieval.py tests/app/test_luna_deep_review.py tests/app/test_narrative_review.py tests/deep_review/test_company_fit.py tests/deep_review/test_company_fit_postgres.py tests/app/test_module_boundaries.py tests/app/test_runtime_database_privileges.py -q
```

PostgreSQL 대상은 일회용 postgres:17.11과 BIDOPS_TEST_POSTGRES_URL을 사용한다.
운영 DB를 연결하지 않는다. backend 기본 검사에는 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
overview=true가 필요한 사례만 fixture에서 설정한다.
실제 로그/exit code/skip/수동 증거는 `docs/validation-runs/<actual-date>-company-demo/DEMO-03-grounded-analysis/`에 남긴다.
선행 검사 결과를 현재 변경의 검사로 적지 않는다. 변경 뒤 영향받은 검사만 재실행한다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 실제 실패를 검증 완화로 숨김 | 검증 미실시/끊긴 필수 근거로 완료 | 정책/입력 계약 수정·원본 보존·새 실제 호출은 별도 승인 |
| 기존 runner가 회사 행을 NULL 입력으로 처리 | 회사 attempt가 전역 프로필로 실행 | company 분기 claim과 T8 회귀 |
| 어휘 미일치로 대부분 unmapped | coverage.unmapped 비율이 높음 | 결과로 보존, 별칭 1회 보강(DEMO-05)으로만 대응 |
| 범위 확장 | 후속 구현/운영 호출을 현재 완료로 표시 | 기능별 수용 조건과 실제 증거를 분리 |

## 증명

- docs: 공통 계약·정본·3문서 일치, 지정 모델 독립 리뷰, diff/링크/STEP 검사.
- tests: 모든 spec T ID를 위 STEP과 assertion에 연결해 명령/결과/skip 기록.
- postgres: DB/API shape 변경 시 임시 PG 검사+head/권한; 아니면 N/A 이유 기록.
- frontend: UI 변경 시 build+두 폭 의미/구조; 아니면 N/A 이유 기록.
- api_guard: 회사 소속/모델 경계 변경 시 승인·hash·호출 0 검사; 아니면 N/A 이유 기록.
- real_data_run: 2026-10-11 재계획으로 DEMO-03에는 비적용(N/A). 대표 1건 실제 Luna 심층은 DEMO-05(대표 1건×3사→전체 18/9건·담당자 인수)가 소유한다. 사유·증거는 STEP-007 기록.

## 결과

2026-10-10 STEP-001~006 구현·리더 검증(각 단계 일회용 PostgreSQL 17.11 독립 재실행, 최종 751 passed/0 skipped)과 독립 최종 리뷰(PASS_WITH_NOTES, 차단 0, N2 PG 정렬 변형 수정 반영)를 마쳤다.
STEP-007은 2026-10-11 사용자 단계별 승인으로 실제 `bidops-local`에 백업·롤백 태그·이미지 `bidops-local:demo03-20261011`·0036 migration·3사 import/activate·demo 정책 2건 import·`env/demo.env`·web/analysis-worker 교체·codex-runner 기동을 적용했다. 대표 후보 공고 179의 회사 미리보기는 3사 모두 모델 호출 전에 409 `company_input_invalid`로 fail-closed됐다(segment inventory 11 vs 본문 ID 50, findings 2026-09-22 항목 재현, DEMO-03 결함 아님). 사용자 결정으로 원안 T9(대표 1건 실제 Luna 심층)를 DEMO-05로 이관하고 STEP-007을 "실제 격리 스택 준비·호출 전 게이트 확인"으로 재정의했다. `real_data_run`은 비적용. 증거는 `docs/validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`와 `_runs/demo0203-20261009/demo03-step007-*.log`. 커밋·병합은 수동 정책이다.
기능 기록은 `_runs/demo0203-20261009/DEMO-03-grounded-analysis.md`, 단계별 `demo03-step00N-result.md`, 리뷰 `demo03-review.md`.

- STEP-001: 순수 검색·coverage·slice 모듈, 90건. 리더 153 passed. 어휘 미일치 위험 기록(DEMO-05).
- STEP-002: 0036 단일 migration·fit 정책 v2·CLI 2개·동결 입력·runner 분기. 리더 515 passed/1 failed(DEMO-02 잔존 head 고정 단언, 체인 head 검사로 교체) → 통과. `model_revision` CHECK 완화.
- STEP-003: 회사 preview/승인/생성/재시도 REST·service, worker `approved_company_input`. 리더 625 passed. `version_conflict` 409.
- STEP-004: `analysis-policy-luna-demo-v1`(v4 파생, sha256 9cb6254e…c3b0, path_limit 32 필수, profile_characters 8000)·회사 slice 빌더. 리더 542 passed. path index는 sanitizer로 모델 미노출(provenance 전용).
- STEP-005: 회사별 GET 6개·비교·FrozenProvenance GET·legacy reader 거부, lifecycle 공개 함수 2개. 리더 661 passed.
- STEP-006: 공용 슬롯 claim 분기·fake Luna 종단·legacy writer/CLI/정책 분리·선택 사실 slice 배치·핏 문서 집합 동결. 리더 751 passed.
- 문서: contracts·ARCHITECTURE·business-rules·deep-review-erd DEMO 절 갱신.
- 미커밋 기능 worktree에 보존. main·운영·`bidops-local` 실제 스택에는 미반영.
