# 회사 전환·그래프·비교·추적 화면 — plan

- 기능 ID: `DEMO-04-review-workspace`
- 작성일: 2026-10-06
- 근거: [intent](intent.md), [spec](spec.md)

## 변경 파일

경로는 저장소 루트 기준. 이 기능은 frontend만 바꾼다(migration·backend 변경 없음, demo-config·서버 guard는 DEMO-01 소유).
기준은 별도 데모 브랜치와 `bidops-local` 격리 자원이다. main이나 운영에 반영하지 않는다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/frontend/src/routes.tsx | 수정 | 회사 경로/legacy 유지 |
| web/frontend/src/components/shell/AppShell.tsx | 수정 | 회사 선택/데모 표식 |
| web/frontend/src/pages/CompanyProfilePage.tsx | 신규 | 프로필/graph |
| web/frontend/src/pages/CompanyPreSpecsPage.tsx | 신규 | 회사 목록·상세 adapter |
| web/frontend/src/pages/CompanyComparisonPage.tsx | 신규 | 3사 비교 |
| web/frontend/src/components/company/KnowledgeGraph.tsx | 신규 | 관계 목록·근거 패널·키보드 |
| web/frontend/src/components/pre-specs/TrackingDecisionControl.tsx | 수정 | 회사 API adapter·회사 경로 세 상태·request_id·expected_revision |
| web/frontend/src/components/deep-review/LunaRequest.tsx | 수정 | 회사 endpoint adapter(기존 경로 동작 유지) |
| web/frontend/src/lib/apiErrors.ts | 수정 | 회사 경로 오류 code 안내 |
| web/frontend/tests/api-mock.ts | 수정 | 회사 endpoint fixture |
| web/frontend/scripts/mock-api.ts | 수정 | dev:mock에 같은 handler |
| web/frontend/src/pages/DeepReviewPage.tsx | 수정 | 회사 report adapter |
| web/frontend/src/lib/companyApi.ts | 신규 | typed DTO/query keys |
| web/frontend/tests/company-workspace.spec.ts | 신규 | 전환/추적/승인 |
| web/frontend/tests/company-graph.spec.ts | 신규 | graph/근거/접근성 |
| web/frontend/playwright.config.ts | 수정 | LAYOUT_SPECS에 company-layout.spec.ts 추가 |
| web/frontend/tests/company-layout.spec.ts | 신규 | 두 폭 T2/T3/T6 구조 검사 |

2026-10-12 구현 중 추가한 경로(run demo04-20261012에서 수용 범위 변경 없이 기록). 실제 diff가 정본이다.

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/frontend/src/App.tsx | 수정 | demo-config를 확정한 뒤 router를 한 번 만든다 |
| web/frontend/src/components/shell/{TopBar,Sidebar,route-meta}.tsx·ts, CompanySelector.tsx | 수정/신규 | 회사 선택기, 가상회사 표식, 회사 메뉴, 동적 경로 메타 |
| web/frontend/src/lib/api.ts | 수정 | 기존 request 도우미를 이름만 바꿔 내보낸다(동작 변경 없음) |
| web/frontend/src/components/common/useUnsavedGuard.ts | 수정 | 재차단 경합 수정: 막힌 이동마다 확인 창을 연다 |
| web/frontend/src/components/deep-review/NarrativeReportReader.tsx | 수정 | 근거 조회 source 주입(기본값은 기존 그대로) |
| web/frontend/src/components/company/{CompanyHeader,CompanySummaries,CompanyFitAttempts}.tsx | 신규 | 회사 머리글, 요약, 핏 판정 이력 |
| web/frontend/src/styles/company-workspace.css | 신규 | 회사 화면 스타일(테마 토큰) |
| web/frontend/tests/fixtures/company-demo.ts | 신규 | 3사 고정 응답 seed |
| web/frontend/tests/company-{prespecs,comparison,review}.spec.ts | 신규 | T3·T4·T5 |

## 작업 순서

1. STEP-001 회사 경로와 상태 [complex]
   - 목표: 회사 경로와 상태의 수용 조건을 충족한다.
   - 작업 대상: router/selector/API/cache·선택 격리.
   - 검증: spec T1,T7; 아래 명령과 해당 단계 증거.
2. STEP-002 프로필과 graph 탐색 [complex]
   - 목표: 프로필과 graph 탐색의 수용 조건을 충족한다.
   - 작업 대상: 관계 목록/근거 패널/절단 안내.
   - 검증: spec T2,T6; 아래 명령과 해당 단계 증거.
3. STEP-003 사전규격과 비교 [standard]
   - 목표: 사전규격과 비교의 수용 조건을 충족한다.
   - 작업 대상: 목록·상세 adapter/3사/상태 안내.
   - 검증: spec T3,T6; 아래 명령과 해당 단계 증거.
4. STEP-004 승인·보고서·결정 연결 [complex]
   - 목표: 승인·보고서·결정 연결의 수용 조건을 충족한다.
   - 작업 대상: NarrativeReportReader·LunaRequest 재사용·세 상태 추적·충돌·이탈.
   - 검증: spec T4,T5; 아래 명령과 해당 단계 증거.
5. STEP-005 영향 화면 인수 [standard]
   - 목표: 영향 화면 인수의 수용 조건을 충족한다.
   - 작업 대상: build/두 폭 Playwright·api-mock 연결.
   - 검증: spec T1~T7; 아래 명령과 해당 단계 증거.

## 위임

| 단계 | 작업량 | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-002 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-003 | M | 중간 | standard | 확정 계약과 기존 패턴 적용 |
| STEP-004 | M | 높음 | complex | 불변식·상태·외부 실행 경계 |
| STEP-005 | M | 중간 | standard | 확정 계약과 기존 패턴 적용 |

## 검사 명령과 증거

아래는 구현 후 실행할 명령이다. 신규 테스트는 아직 없으며 통과를 주장하지 않는다.

```sh
cd web/frontend
npm run build
npx playwright test tests/company-workspace.spec.ts tests/company-graph.spec.ts tests/luna-deep-review.spec.ts tests/narrative-report.spec.ts --project=app
npx playwright test tests/company-layout.spec.ts --project=layout-laptop --project=layout-desktop
```

Playwright는 `tests/api-mock.ts`의 고정 응답으로 돌며 실제 백엔드에 연결하지 않는다. 실제 결과 화면 인수는 DEMO-05 live config가 맡는다.
실제 로그/exit code/skip/수동 증거는 `docs/validation-runs/<actual-date>-company-demo/DEMO-04-review-workspace/`에 남긴다.
선행 검사 결과를 현재 변경의 검사로 적지 않는다. 변경 뒤 영향받은 검사만 재실행한다.

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 회사 전환 뒤 cache/초안 혼입 | 다른 회사 결과/추적 선택 표시 | query/storage/mutation key 수정 후 전환 검사 |
| LunaRequest 수정이 기존 경로 회귀 | 기존 사전규격 상세 심층 요청 실패 | luna-deep-review.spec.ts 회귀 유지 |
| 범위 확장 | 후속 구현/운영 호출을 현재 완료로 표시 | 기능별 수용 조건과 실제 증거를 분리 |

## 증명

- docs: 공통 계약·정본·3문서 일치, 지정 모델 독립 리뷰, diff/링크/STEP 검사.
- tests: 모든 spec T ID를 위 STEP과 assertion에 연결해 명령/결과/skip 기록.
- postgres: N/A — frontend만 변경.
- frontend: UI 변경 시 build+두 폭 의미/구조; 아니면 N/A 이유 기록.
- api_guard: 회사 소속/모델 경계 변경 시 승인·hash·호출 0 검사; 아니면 N/A 이유 기록.
- real_data_run: DEMO-05에서 실제 18/9건·담당자 인수; 다른 기능은 N/A(소유 DEMO-05).

## 결과

2026-10-12 run `demo04-20261012`에서 STEP-001~005를 구현했다. 리더가 단계마다 영향 검사를 다시 돌렸고, 독립 최종 리뷰(PASS_WITH_NOTES, 차단 0)와 그 회차의 주의 3건 수정까지 마쳤다. 변경은 frontend뿐이고, 검증은 Playwright mock으로만 했다. 실제 백엔드·자료 화면 인수는 DEMO-05가 맡는다. 커밋·병합은 수동 정책이다.
기능 기록은 `_runs/demo04-20261012/DEMO-04-review-workspace.md`, 증거 요약은 `docs/validation-runs/2026-10-12-company-demo/DEMO-04-review-workspace/README.md`, 리뷰는 `_runs/demo04-20261012/review.md`.

- 위 "검사 명령과 증거" 절의 "신규 테스트는 아직 없으며" 문장은 계획 작성 시점 문구다. 실제 실행 결과는 이 절과 리더 로그가 정본이다.
- 이 Mac에서는 `vite preview`가 IPv6 localhost에만 바인딩된다. 그래서 위 명령은 preview를 `--host 127.0.0.1`로 띄우고 `PW_PORT`·`PW_OUT_DIR`로 재사용해 실행했다(설정 변경 없음).
- 최종: `npm run build` exit 0. 리뷰 수정 뒤 영향 app spec 13개 271 passed. 두 폭 layout 117 passed / 2 failed / 3 skipped. 리뷰 수정 전 화면 게이트 전체 833 passed / 6 failed / 6 skipped. 실패는 모두 기준 `c50ed55`에서도 같은 기존 실패이고(findings 2026-10-12·2026-09-16), 건너뜀은 설계상이다.
- 구현 중 추가한 공용 변경은 변경 파일 표의 추가 표에 적었다: `useUnsavedGuard` 재차단 경합 수정, `NarrativeReportReader` 근거 source 주입, 셸·`App.tsx` demo-config 확정.
- 판단: 핏 GraphPath는 계약상 id만 있어 id로 표시한다. 회사 경로 원문 대조는 true만 보낸다. 회사 보고서는 읽기 전용이다. 정상 조작으로 생기지 않는 409는 합성 검사로 분리했다.
- 남은 한계: 실제 스택의 생성→폴링→보고서 흐름과 회사 전환은 DEMO-05에서 인수한다. demo-config 재조회 실패 유지 분기는 코드 리뷰로만 확인했다. 회사 목록 키보드 조작은 backlog다.
