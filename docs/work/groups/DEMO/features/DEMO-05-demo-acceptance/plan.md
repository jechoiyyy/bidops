# 격리 데모와 실제 예제 인수 — plan

- 기능 ID: `DEMO-05-demo-acceptance`
- 작성일: 2026-10-06
- 근거: [intent](intent.md), [spec](spec.md)

## 변경 파일

경로는 저장소 루트 기준. 이 기능은 migration을 만들지 않는다. 기준 브랜치는 데모 브랜치이며 운영에 배포하지 않는다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| docker-compose.demo.yml | 신규 | 데모 flag·전용 자원·`!override` volumes·fixture 일회성 마운트 |
| .gitignore | 수정 | `data/demo/` 추가 |
| scripts/prepare-company-demo.sh | 신규 | preflight/dry-run·storage/migrate/companies/notices 명시 단계 |
| scripts/verify-company-demo.py | 신규 | read-only API/manifest 인수 검사 |
| docs/demo-fixtures/corpus-manifest.schema.json | 신규 | 공통 §7 schema |
| docs/operations.md | 수정 | 준비/중단/복구/인수 |
| docs/validation-runs/<actual-date>-company-demo/README.md | 신규 | 실제 실행 증거 색인 |
| web/backend/tests/app/test_company_demo_script.py | 신규 | 서비스 계약 기반 도구 검사 |
| web/frontend/tests/company-demo-live.spec.ts | 신규 | 준비된 실제 결과 UI 인수 |
| scripts/record-company-demo-acceptance.py | 신규 | strict 담당자 인수 append-only 기록 |
| web/frontend/playwright.demo.config.ts | 신규 | demo-laptop/demo-desktop; 필수 실제 baseURL; mock/webServer 없음 |

## 작업 순서

1. STEP-001 격리 환경과 도구 [complex]
   - 목표: 격리 환경과 도구의 수용 조건을 충족한다.
   - 작업 대상: Compose/secret/volume/dry-run·fake 계약·엔드포인트 미제공 blocked·data/demo gitignore.
   - 검증: spec T1,T2,T7; 아래 명령과 해당 단계 증거.
2. STEP-002 표본과 회사 입력 동결 [standard]
   - 목표: 표본과 회사 입력 동결의 수용 조건을 충족한다.
   - 작업 대상: 최근 사전규격 후보·G2B 첨부 재취득 확인·6건 데모 회차 적재·별칭 1회 보강과 3사 재등록·활성화·manifest(first_deep_review_notice_id).
   - 검증: spec T3; 아래 명령과 해당 단계 증거.
3. STEP-003 실제 모델 결과 인수 [complex]
   - 목표: 실제 모델 결과 인수의 수용 조건을 충족한다.
   - 작업 대상: 핏 18 enqueue·심층 건별 승인·첫3(demo_ready)→9·read-only verify·운영 Luna와 순차 사용.
   - 검증: spec T4,T5,T7; 아래 명령과 해당 단계 증거.
4. STEP-004 담당자 인수·운영 절차 [standard]
   - 목표: 담당자 인수·운영 절차의 수용 조건을 충족한다.
   - 작업 대상: 실제 두 폭 UI·세 상태 독립 추적·사용자 인수 기록·증거/미완료 기록.
   - 검증: spec T6,T7; 아래 명령과 해당 단계 증거.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-002 | M | 중간 | standard | 확정 계약과 기존 패턴 적용 |
| STEP-003 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-004 | M | 중간 | standard | 확정 계약과 기존 패턴 적용 |

## 검사 명령과 증거

아래는 구현 후 실행할 명령이다. 신규 테스트는 아직 없으며 통과를 주장하지 않는다.

```sh
cd web/backend
BIDOPS_PRESPEC_OVERVIEW_ENABLED=false python3 -m pytest tests/app/test_company_demo_script.py -q
cd ../..
# 아래 실제 인수는 승인된 데모 환경에서 manifest 확정 후 실행:
# python3 scripts/verify-company-demo.py --manifest <frozen-manifest> --base-url <demo-url> --acceptance-dir data/demo/acceptance
# cd web/frontend
# BIDOPS_DEMO_BASE_URL=<demo-url> npx playwright test --config playwright.demo.config.ts --project=demo-laptop
# BIDOPS_DEMO_BASE_URL=<demo-url> npx playwright test --config playwright.demo.config.ts --project=demo-desktop
```

PostgreSQL 대상은 일회용 postgres:17.11과 BIDOPS_TEST_POSTGRES_URL을 사용한다.
운영 DB를 연결하지 않는다. backend 기본 검사에는 BIDOPS_PRESPEC_OVERVIEW_ENABLED=false를 명시한다.
overview=true가 필요한 사례만 fixture에서 설정한다.
실제 로그/exit code/skip/수동 증거는 `docs/validation-runs/<actual-date>-company-demo/DEMO-05-demo-acceptance/`에 남긴다.
선행 검사 결과를 현재 변경의 검사로 적지 않는다. 변경 뒤 영향받은 검사만 재실행한다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 연결만 성공·보고서 미완료 | 9개 보고서 부족/검증 미실시/근거 오류 | 실패 보존·선행 기능 수정·승인된 재실행; mock 대체 금지. 최소 기준(demo_ready)과 목표를 구분해 보고 |
| 로컬 LLM 엔드포인트 지연 | preflight model_endpoint_missing | 개요·핏 단계 대기, 일정 영향을 바로 보고 |
| 같은 Codex 인증 동시 사용 | 운영·데모 Luna가 겹침 | 순차 실행, 실행 시각 기록 |
| 마감 7200초·단일 슬롯 | 보고서당 최대 2시간 | 첫 3건을 먼저 돌려 demo_ready를 확보한 뒤 나머지 |
| 범위 확장 | 후속 구현/운영 호출을 현재 완료로 표시 | 기능별 수용 조건과 실제 증거를 분리 |

## 증명

- docs: 공통 계약·정본·3문서 일치, 지정 모델 독립 리뷰, diff/링크/STEP 검사.
- tests: 모든 spec T ID를 위 STEP과 assertion에 연결해 명령/결과/skip 기록.
- postgres: DB/API shape 변경 시 임시 PG 검사+head/권한; 아니면 N/A 이유 기록.
- frontend: UI 변경 시 build+두 폭 의미/구조; 아니면 N/A 이유 기록.
- api_guard: 회사 소속/모델 경계 변경 시 승인·hash·호출 0 검사; 아니면 N/A 이유 기록.
- real_data_run: DEMO-05에서 실제 18/9건·담당자 인수; 다른 기능은 N/A(소유 DEMO-05).

## 결과

미구현. 문서 검토와 제품 검증을 구분한다. 실제 작업 후 차이·재시도·증거·커밋 여부를 기록한다.
