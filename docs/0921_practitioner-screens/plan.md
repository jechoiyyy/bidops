# 실무 화면 고도화 — 계획

- 상태: 구현 중(2026-09-21 착수). 의도는 [`intent.md`](intent.md), 동작은 [`spec.md`](spec.md).
- 기준 트리: `main` 92c7f32, Alembic head `0030_prespec_review_exclusion`. 이 계획이 새로 만드는 migration은 없다.
- 구현은 `.claude/agents/`의 **`do-opus`(opus·high)·`do-sonnet`(sonnet·high)** 서브에이전트에 위임하고 리더(Fable)는 시안·게이트·검수·병합 준비를 맡는다. 두 정의의 본문은 0918 계획을 가리키므로 위임 프롬프트에서 이 문서를 패키지 정본으로 지정한다.

## 1. 작업 패키지와 모델

모델 기준: 새 컴포넌트·상태 조건·계약 판단·ADR 문안·2천 줄 단일 파일의 구조 변경은 **opus**, 처분표·위치·문구가 닫혀 있는 기계적 변경은 **sonnet**, 시안 제작·게이트 실행·diff 검수·픽셀 기준선 교체·배포 확인 요청은 **리더**.

| ID | 내용 | 모델 | 웨이브 | 선행 | 시안 | 파일 소유(요약) |
|---|---|---|---|---|---|---|
| D0 | 결정 기록: ADR-0066, ADR-0062·0064 개정, 0918 spec §7 개정, decisions.md, ADR.md, findings 인계 | **opus** | 1 | — | — | `docs/tracking/decisions/**`, `docs/ADR.md`, `docs/0918_daily-operation/spec.md`, `docs/0915_ui-redesign/decisions.md`, `docs/tracking/findings.md` |
| B1 | 발주계획 목록 v5·상세 v4 투영 + 이력 `purpose`·시각 + 프런트 타입·mock·spec 리터럴 | **opus** | 1 | — | — | `app/screening/schemas/order_plans.py`, `app/screening/services/order_plan_screening.py`, 해당 pytest, `web/frontend/src/lib/types.ts`, `tests/api-mock.ts`, `tests/order-plans.spec.ts`(리터럴만), `docs/contracts.md`(발주계획 절) |
| B2 | 사전규격 `demand_agency`·검색, Go/No-Go 대기열 마감·예산·정렬, 사업기회 링크 예산·마감 | **sonnet** | 1 | — | — | `app/lifecycle/routers/pre_specs.py`, `schemas/pre_specs.py`, `app/deep_review/services/decision_queue.py`, `schemas/bid_delta.py`, `app/lifecycle/services/opportunity_queries.py`, `schemas/opportunities.py`, 해당 pytest, `docs/contracts.md`(해당 절), `docs/bid-delta-contract-spec.md` |
| R3 | 지역 제한 `없음` → `미확인` 결함 수정(spec §3.4) | **sonnet** | 1 | — | — | `components/notice/NoticeFacts.tsx`, 해당 spec 단언 |
| R1 | 발주계획 다이얼로그 본문을 `components/order-plans/`로 추출(동작 불변) | **sonnet** | 1 | — | — | `pages/OrderPlansPage.tsx`, `components/order-plans/*`(신규) |
| M1 | 시안: 필터 바 3상태(접힘/펼침/회차 선택+접힘), 페이저 4화면, 빈 상태 2화면, 값 없음 문구 대조표, 범위 설명 단추·건수 캡션 이름, 측정 전용 표시 A/B안, 회차 변경 URL 정책 | **리더** | 1 | — | — | `docs/0915_ui-redesign/mockups/0921_practitioner-p1/` |
| U1 | `SourceRunFilter` + `lib/runOptions.ts` + 두 화면 필터 바 이동 + `ListPagerControls` + 두 화면의 이름·캡션 | **opus** | 2 | M1 승인, R1 | M1 | `components/common/SourceRunFilter.tsx`, `lib/runOptions.ts`, `common/ReviewPrimitives.tsx`, `common/WorkspaceFilters.tsx`, `pages/OrderPlansPage.tsx`, `pages/PreSpecsPage.tsx`, `styles/workspace-filters.css`·`order-plans.css`·`pre-specs-relaxed.css`, 해당 spec |
| U2 | 사업 추적·Go/No-Go 빈 상태·로딩·이름·캡션(페이저 교체는 U1 병합 뒤) | **sonnet** | 2 | M1 승인 | M1 | `pages/OpportunitiesPage.tsx`, `pages/GoNoGoPage.tsx`, 해당 css·spec |
| U3 | 포맷 통합(`lib/format.ts`)·호출부 교체·운영 선택기 라벨 통일·죽은 코드 삭제 | **sonnet** | 3 | U1·U2 | M1 | `lib/format.ts`, 중복 7곳, `runs/RunPicker.tsx`, `shell/RunSelector.tsx`, `pages/MetricsPage.tsx`, 삭제 대상 |
| O1 | `/runs` `발주계획 선별` 탭(실행 기록 + 계획별 신호) + 회차 보기 링크 + 안내문 정정 | **opus** | 2 | M2 승인 | M2 | `components/runs/OrderPlanScreeningPanel.tsx`(신규), `pages/RunsPage.tsx`, `pages/RunStatusPage.tsx`, `styles/runstatus-erp.css`, `run-status.spec.ts` |
| R2 | 발주계획 걷어내기(spec §3.1) — 실행 상태 칩 조건 수정 포함 | **opus** | 4 | U1·U3·O1, M3 승인 | M3 | `pages/OrderPlansPage.tsx`, `components/order-plans/*`, `lib/glossary.ts`, 해당 spec |
| R4 | 사전규격 목록 다이얼로그·상세 ⑥ 병합·경계 문장(spec §3.2) | **opus** | 4 | U1, M4 승인 | M4 | `pages/PreSpecDetailPage.tsx`, `pre-specs/PageOverviewSection.tsx`, `pre-specs/CompanyFitSection.tsx`, `pages/PreSpecsPage.tsx`(다이얼로그만) |
| R5 | 심층 검토 기술 정보 접기(spec §3.2) | **opus** | 4 | M4 승인 | M4 | `pages/DeepReviewPage.tsx`, `deep-review/SegmentInventoryPanel.tsx` |
| C1 | 사업 추적 `SplitWorkspace` 골격 | **opus** | 4 | U2·U3, M1c 승인 | M1c | `pages/OpportunitiesPage.tsx`, `opportunities/*`, 해당 css·spec, `explore-workspace-consistency.spec.ts`(사업 추적 행) |
| C2 | Go/No-Go `SplitWorkspace` 골격 | **opus** | 4 | U2·U3, M1c 승인 | M1c | `pages/GoNoGoPage.tsx`, 해당 css·spec, `explore-workspace-consistency.spec.ts`(Go/No-Go 행 — C1 뒤 순차) |
| R6 | Go/No-Go·입찰 변경·판정 이력·셸(spec §3.3) + `/runs?run=…&execution=…`로 들어오면 발주계획 회차의 `발주계획 선별` 탭을 처음부터 연다(R2의 문제 칩 링크가 한 번에 닿게) + `deep-review/TechnicalInfo.tsx`의 낡은 주석 한 줄 | **sonnet** | 5 | C1·C2, M4 승인 | M4 | `pages/GoNoGoPage.tsx`, `pages/BidDeltaDecisionPage.tsx`, `opportunities/NoticeCorrectionDialog.tsx`, `shell/BasisPopover.tsx`·`route-meta.ts`·`Sidebar.tsx`, `notice/RetrievalSignals.tsx`, `pages/ReviewWorkspacePage.tsx`, `common/MutationFeedback.tsx` |
| F0 | P6 공용: B2 필드의 프런트 타입·mock·fixture + 심층 검토 fixture 오류 코드 `model_timeout` → `timeout`(사전에서 해당 줄 삭제) + `tests/fixtures/api.json`의 stale `order-plan-list-response.v1` 정리 | **sonnet** | 6 | B1·B2 병합 | — | `lib/types.ts`, `tests/api-mock.ts`, fixtures |
| F1 | 발주계획 상세 API 연결·판정 변화·행 표식(spec §6.1) + 상세 머리의 `첫 수집 MM-DD`(시안 M3 ④) | **opus** | 7 | F0·R2, M5 승인 | M5 | `order-plans/OrderPlanDetailPane.tsx`·`OrderPlanListRow.tsx`, `pages/OrderPlansPage.tsx` |
| F2 | 사전규격 제외 기록·수요기관, 입찰공고 금액 라벨·개찰일시·실적 매칭(spec §6.2·6.3) + 목록 우측 상세(`PreSpecListDetailPane`)의 경계 문장을 M4 승인 문안으로 | **opus** | 7 | F0·R4, M5 승인 | M5 | `pre-specs/*`, `notice/NoticeFacts.tsx`, `pages/NoticeDetailPage.tsx` |
| F3 | Go/No-Go 마감·예산 열·정렬, 사업 추적 행 예산·마감 + `BidDeltaDecisionPage`의 `안전한 오류 코드` 3곳 접기(R6 잔여) | **sonnet** | 7 | F0·R6, M5 승인 | M5 | `pages/GoNoGoPage.tsx`, `pages/OpportunitiesPage.tsx` |
| H0 | spec §7 계약 닫기(패널별 목록 출처·모집단·정렬) + ADR-0066 | **opus** | 7 | B2 | — | `docs/0921_practitioner-screens/spec.md` §7, `docs/tracking/decisions/0066-*.md`, `docs/contracts.md` workload 절 |
| H1 | workload 누적 키·제공자·`deadline_within_days`·`human_relevance=missing` | **opus** | 8 | H0 | — | `app/lifecycle/schemas/workload.py`·`services/workload.py`·`extensions.py`, screening·deep_review 제공자, 해당 pytest |
| H2 | 대시보드 화면 재편 | **opus** | 9 | H1·F3, M6 승인 | M6 | `pages/DashboardPage.tsx`, `components/dashboard/*`, `dashboard.spec.ts` |
| H3 | `회차 요약`·`검증 상태`를 `/runs` 회차 상세로, 회사 역량 미확인을 회사 프로필로 이식 | **sonnet** | 9 | H1, M6 승인 | M6 | `pages/RunsPage.tsx`(요약 절), `pages/ProfilePage.tsx` |
| M2~M6 | 시안 M2(운영 탭)·M3(발주계획)·M4(사전규격·심층·Go/No-Go·셸)·M1c(골격)·M5(빠진 정보)·M6(대시보드) | **리더** | 각 선행 웨이브 중 | — | — | `docs/0915_ui-redesign/mockups/` |

모델별 건수: opus 14, sonnet 8, 리더 시안 7.

## 2. 의존 순서

- **O1 → R2**: C-2 실행 기록의 운영 수신처가 없다. 자리를 만든 뒤에 실무 화면에서 뺀다.
- **R1 → U1 → U3 → R2 → F1**: 모두 `OrderPlansPage.tsx`를 고친다. 한 번에 한 패키지만 소유한다.
- **U2 → U3 → C1·C2 → R6 → F3**: `OpportunitiesPage.tsx`·`GoNoGoPage.tsx`의 소유 순서.
- **U3(포맷) → F***: 새 필드가 처음부터 공용 포맷터를 쓴다.
- **B1·B2 → F0 → F***, **B2 → H0 → H1 → H2**.
- B1·B2·D0·R3·R1은 서로 파일이 겹치지 않아 웨이브 1에서 병렬. `docs/contracts.md`는 B1·B2가 서로 다른 절만 고친다.
- 프런트 병렬은 동시에 3개까지, `PW_PORT` 4173/4174/4175와 `PW_OUT_DIR`를 패키지마다 달리 준다.

## 3. 시안 게이트

- Artifact 웹 페이지, 1280×800·1440×900 두 폭, 현재 화면과 변경안을 나란히, 색은 `bidopsTheme.ts` 토큰 값만, 표시 데이터는 테스트 fixture 값만(운영 DB의 실제 기관·사업명은 올리지 않는다).
- 기능 손실·선택지가 있는 것은 안을 나눠 보인다(M1: 측정 전용 표시 A/B, 회차 변경 URL 정책 / M1c: Table 유지 vs DenseList / M4: 편집 범위 칩).
- 앞 시안의 승인은 다음 시안으로 이어지지 않는다. 승인 뒤 원본을 `docs/0915_ui-redesign/mockups/<날짜>_<이름>/`에 보관하고 결정을 `decisions.md`에 적는다.
- 시안과 무관한 패키지(D0·B1·B2·R3·R1·F0·H0·H1)는 승인을 기다리지 않는다.

## 4. 실행 방식

- 패키지마다 워크트리(`~/orca/workspaces/bidops/ps-<id>`)와 브랜치(`feat/ps-<id>-…` 또는 `docs/ps-<id>-…`)를 만든다. 워크트리에는 `web/backend/.venv`·`web/frontend/node_modules`를 main 트리로 symlink하고 `experiments/order-plan-screening/review-inputs`를 복사한다.
- 에이전트는 자기 브랜치에만 커밋한다. **리더는 main에 병합하지 않고** 브랜치·커밋·검증 결과를 보고한다. 뒤 웨이브의 패키지는 앞 패키지 브랜치를 쌓은 통합 브랜치(`integration/practitioner-screens`)에서 출발한다. main 병합·운영 배포·origin push는 각각 사람 확인 뒤에 한다.
- 위임 프롬프트에는 패키지 ID, 이 문서와 spec의 해당 절, 파일 소유 목록, 실행할 검사, "모든 검사는 포그라운드, timeout 600000ms", 보고 형식을 넣는다. 위임 보고를 근거로 쓰지 않고 리더가 영향 범위 검사를 직접 돌린다.

## 5. 검증 범위

| 패키지 | 검사 |
|---|---|
| D0·H0 | diff 확인 |
| B1 | `tests/app/test_order_plan_screening_api.py`, `tests/screening/test_order_plan_list_v2.py`, `tests/app/test_order_plan_screening_service.py` — SQLite + 리더가 일회용 `postgres:17.11`·`BIDOPS_TEST_POSTGRES_URL`·`BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 skip 0 확인. 프런트 `npx tsc -b`, `order-plans.spec.ts` |
| B2 | `test_api_pre_specs.py`, `test_api_pre_specs_projection.py`, `test_bid_delta_api.py`, `test_api_opportunities.py`, `tests/lifecycle/test_opportunity_links.py`, 검색 테스트 — 위와 같은 PostgreSQL 변형 |
| R3 | 공고 상세 spec의 해당 단언 |
| R1 | `order-plans.spec.ts`, `tsc -b`(동작 불변 확인) |
| U1 | `order-plans`·`pre-specs`·`prespec-list-work`·`search-ux`·`explore-workspace-consistency`·`review-primitives` spec + spec §2.1 검증 표 |
| U2·C1·C2 | `opportunities`·`go-no-go`·`explore-workspace-consistency`·`overflow` spec |
| U3 | `tsc -b`, 포맷이 닿는 spec, 공유 코드라 웨이브 끝 전체 1회에 포함 |
| O1·H3 | `run-status`·`overflow` spec |
| R2 | `order-plans`·`order-plan-policies`·`screen-semantics`·`list-selection` spec |
| R4·R5·R6 | `pre-specs`·`page-overview`·`company-fit`·`prespec-evidence`·`deep-review`·`go-no-go`·`bid-delta`·`review-workspace-consistency`·`route-context`·`design-shell`·`common-interactions` spec |
| F1~F3 | `order-plans`·`pre-specs`·`prespec-exclusions`·`go-no-go`·`opportunities`·`screen-semantics`·`overflow` spec |
| H1·H2 | `test_workload_api.py`·`test_workload_extensions.py`·`tests/screening/test_workload_projection.py`·`test_api_pre_specs_workspaces.py` + PostgreSQL 변형, `dashboard` spec |

- `npm run build` + `npm run test:screens` 전체는 **배포 묶음의 통합 트리에서 1회**. 기준선은 main 92c7f32의 668 passed / 2 failed(`admin-workspace-consistency.spec.ts:23` 2건, 기존 결함) / 6 skipped. 부하 flake는 단독 1회로 확인하고 strict mode 위반은 flake로 넘기지 않는다.
- 공유 fixture(`tests/api-mock.ts`)를 고친 패키지(B1·F0) 뒤에는 `--project=app` 전체를 1회 돌린다.
- 픽셀 기준선은 화면이 바뀐 묶음에서 리더가 교체하고 사유를 적는다.

## 6. 배포 묶음

| 묶음 | 패키지 | 비고 |
|---|---|---|
| ① | U1·U2·U3·O1·R1·R3 | 백엔드 변경 없음 |
| ② | R2·R4·R5·C1·C2·R6 | 백엔드 변경 없음 |
| ③ | B1·B2·F0·F1·F2·F3 | 응답 버전 올림과 화면을 함께 |
| ④ | H1·H2·H3 | |

묶음마다 전체 백업(`backups/postgres/full/`) + 롤백 태그 `before-practitioner-screens-<n>-<날짜>` + 사람 확인 + compose 5개·env 4개·`--profile prespec`로 `web` 재생성 + 컨테이너 env 플래그 확인 + 배포 후 운영 화면 확인 + `status.md` 기록. D0 문서는 묶음 ①과 함께 병합한다.

## 7. 사람에게 물을 것

- 시안 M1~M6의 승인과 그 안의 선택지(§3).
- 각 묶음의 main 병합·운영 배포·origin push.
- 분리한 후속 작업(수집 확장, 단계 지연)의 착수 시점과 단계 지연의 효과(배지 / 구역).
