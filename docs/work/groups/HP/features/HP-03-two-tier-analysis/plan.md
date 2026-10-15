# HP-03 — plan

- 기능 ID: `HP-03-two-tier-analysis`
- 근거: intent.md, spec.md. 작성일2026-10-15. 구현 시작 전 문서다.

## 변경 파일

| 경로 | 구분 | 내용 |
|---|---|---|
| `web/backend/app/deep_review/services/hp_analysis.py` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/schemas/hp_analysis.py` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/contracts/ (HP schema 신규)` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/models.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/services/company_deep_review.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/services/company_analysis_input.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/services/deep_reviews.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/app/deep_review/policies/analysis-policy-hp-v1.json` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/app/core/db.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `web/backend/alembic/versions/` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/tests/deep_review/test_hp_analysis.py` | 신규 | spec 요구사항 구현·검증 |
| `web/backend/tests/app/test_hp_analysis.py` | 신규 | spec 요구사항 구현·검증 |

| `scripts/runtime-privileges.sql` | 수정 | HP stage 역할별 append-only 권한 |
| `web/backend/app/deep_review/services/input_versions.py` | 수정 | HP 정책 identity/file map·card-v1 strict loader |
| `web/backend/app/deep_review/services/luna_identity.py` | 수정 | 새 회사 정책 allowlist, 고정 모델 identity 유지 |
| `web/backend/app/deep_review/services/luna_client.py` | 수정 | 고정 HP runner contract 요청 |
| `web/backend/app/deep_review/schemas/company_analysis.py` | 수정 | preview v1/v2 policy 결속 union |
| `web/codex-runner/runner.py` · `web/codex-runner/Dockerfile` | 수정 | schema allowlist·고정 파일 포함 |
| `web/backend/tests/app/test_runtime_database_privileges.py` | 수정 | stage INSERT/UPDATE/DELETE 실제 역할 검사 |
| `web/backend/tests/app/test_alembic_autogenerate.py` · `web/backend/tests/app/test_company_luna_policy.py` | 수정 | head·policy identity 회귀 |
| `web/backend/tests/deep_review/test_codex_runner.py` | 수정 | 새 contract·기존 contract 동시 검사 |
| `docs/contracts.md` · `docs/deep-review-erd.md` · `docs/database-guide.md` · `docs/operations.md` | 수정 | 구현된 REST/DB/적용 계약으로 갱신 |

## 작업 순서

1. STEP-001 unit 선택·batch·schema [complex]
   - 목표: source identity와 6영역 선택·한도 고정.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T1,T2; 결과/명령/종료코드는 실행 run 폴더에 저장.

2. STEP-002 불변 단계 저장·migration [complex]
   - 목표: append-only row·권한·단일 head 동기화.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T6 및 test_runtime_database_privileges.py·test_alembic_autogenerate.py; 결과/명령/종료코드는 실행 run 폴더에 저장.

3. STEP-003 추출·회사 결정적 대조 [complex]
   - 목표: 숫자/근거/범위/미확인 검증.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T3,T4; 결과/명령/종료코드는 실행 run 폴더에 저장.

4. STEP-004 역할·종합 조립 [complex]
   - 목표: 입력 허용집합·충돌 보존·최종 성공 gate.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T5; 결과/명령/종료코드는 실행 run 폴더에 저장.

5. STEP-005 worker·preview·정책 연결 [complex]
   - 목표: 승인 fence·슬롯·deadline·부분결과.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T7,T8 및 test_company_luna_policy.py·test_codex_runner.py; 결과/명령/종료코드는 실행 run 폴더에 저장.

6. STEP-006 통합·대표 실제 실행 증거 [complex]
   - 목표: mock과 실제 실행 분리·독립 코드리뷰.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T9; 결과/명령/종료코드는 실행 run 폴더에 저장.

## 위임

모든 단계 complex(gpt-5.6-sol/high): 불변 입력·상태·근거·사람 판단 경계를 검사한다. 구현자는 단계 하나만, 리더가 관련 검사를 실행하며 독립 리뷰는 같은 소스·결과를 읽는다. 테스트 ID는 spec 표이며 위 단계가 전부 배정한다.

## 증명

- docs: `python3 scripts/feature_status.py doctor _`, `check-plan HP-03-two-tier-analysis`와 intent 유즈케이스별 실제 증거 대조.
- tests: `cd web/backend && python -m pytest tests/deep_review/test_hp_analysis.py tests/app/test_hp_analysis.py -q`. 새 검사 파일은 loop에서 구현하며 현재 존재/통과한다고 주장하지 않는다.
- postgres: 임시 PostgreSQL17.11 및 BIDOPS_TEST_POSTGRES_URL로 위 관련 backend 파일의 PostgreSQL 변형 실행. HP03는 migration/head/grants/중복claim 포함.
- frontend: N/A — 화면 코드 변경 없음.
- api_guard: 위 backend 관련 API/CLI 검사에서 타회사·404/409/422/503·비밀비노출·입력fence. HP02는 기존 shape 재사용도 확인.
- real_data_run: HP03 T9의 실제 고정 대표1건. 실패/미승인 입력은 pending이며 mock으로 대체 불가.

## 위험과 종료 경계

| 위험 | 징후 | 대응 |
|---|---|---|
| 확정 설정을 실제 기능/품질로 오인 | 준비파일만 있고 실제 증거 없음 | 필수검증을 pending 유지 |
| 원문/회사/정책 기준 혼합 | hash·ID·버전 불일치 | fail closed, 새 버전·새 attempt |
| 미확인을 false/충족으로 변경 | 조건 일부만 맞는데 met | spec 경계 검사, unknown 보존 |
| 사용자 참여 대기 | 사람 경로/gold/인수 없음 | 독립 가능한 단계만 진행, 답 대행 금지 |

실행 전에 필요한 검사 범위를 한 번 정하고 통과 후 동일검사를 반복하지 않는다. 실제환경 적용은 사용자 승인 범위 내 demo/local-20261009·bidops-local만. 전체스위트/전수재빌드는 공통 회귀 근거 없으면 실행하지 않는다. 수동 commit/merge 정책을 유지하며 origin push·브랜치 삭제 없음.

## 결과

아직 구현·실제 기능 검증하지 않았다. loop가 실행 결과를 이 절에 기록한다.
