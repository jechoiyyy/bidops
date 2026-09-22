# 실무 화면 고도화 — 명세

- 의도는 [`intent.md`](intent.md), 작업 패키지·모델·순서는 [`plan.md`](plan.md).
- 파일:줄은 `main` 92c7f32 기준이다. 구현자는 착수 때 위치를 다시 확인한다.
- 화면이 바뀌는 절은 시안 승인에서 확정된다. 시안이 이 명세와 다르게 승인되면 이 문서를 개정 문장으로 고친다.

## 0. 바뀐 뒤의 하루

- **아침, 대시보드.** 회차를 고르지 않아도 화면이 채워져 있다. 위에는 네 업무 건수, 그 아래 `마감 임박 추적 건`(누적, D-day순), `최종 결정 대기`(입찰 마감순), `사람 확인 필요`(개요 실패·확인 필요 + 공고별 참여 조건 확인 항목), `보류 재검토`, `새 우선 검토 발주계획`. `1차 필터 누락`·`판정 표본` 같은 말은 없다.
- **발주계획.** 행에는 기관·예산·발주 예정·모델 판단(`관련`/`판단 보류`)·추적 상태·판단 근거 한 줄·`첫 수집 09-19`. `Qwen`·`BM25`·policy 이름은 없다. 선별이 실패한 건만 `선별 실패` 표식이 뜬다. 행을 고르면 상세에 신규/계속, 계약방법, 공고 게시 여부, 지난 운영 실행 대비 판정 변화, 사업기회로 가는 링크가 보인다. 상세 필터를 펴면 축 이름이 `모델 판단`·`1차 선별`·`사람 판단`이고 그 안에 `수집 회차`가 있다.
- **사전규격.** 같은 자리에 같은 모양의 `수집 회차`가 있다. 실제 발주처(수요기관)가 보이고 그 이름으로 검색된다. 제외된 건은 누가 왜 언제 뺐는지 보인다.
- **사업 추적·Go/No-Go.** 발주계획과 같은 분할 골격·페이저·빈 상태. 행에 예산·마감이 보이고 Go/No-Go는 입찰 마감 임박순이다.
- **문제가 있는 날.** 자동 선별 스위치가 꺼져 있으면 발주계획 위에 "자동 선별이 꺼져 있습니다 · 운영 화면에서 확인 →" 한 줄이 뜬다. 최근 선별 실행이 실패·중단이면 상단에 문제 칩이 뜬다(지난 성공 뒤의 실패도 잡는다). digest·컨테이너 같은 사유는 `판정 기준 › 발주계획 선별 정책`에 있다.
- **운영자.** `실행 상태 › 수집 실행`에서 발주계획 회차를 고르면 `발주계획 선별` 탭에 실행 ID·policy·binding 해시·배치별 토큰·소요 시간·artifact sha256과 계획별 신호(rank·score)가 있고, 바닥의 `이 회차의 발주계획 보기`로 실무 화면에 회차가 걸린 채 들어간다. 그때 실무 화면 필터 둘째 줄에 `회차 보기 · 09-19~09-20 수집 · 측정 전용 실행 [모든 회차로]`가 뜬다.

## 1. 정보 경계

### 1.1 처분 5종

실무 화면의 문구·값은 하나씩 심사해 다섯 중 하나로 처분한다(d79bc48·4b3a961의 방식).

| 처분 | 뜻 |
|---|---|
| 삭제 | 구조나 다른 표식이 이미 같은 사실을 말한다 |
| 조건부 | 경고 상황에서만 그린다 |
| 이동 | 운영 화면, 같은 화면의 접힌 `기술 정보`, 접근 설명(`aria` description) 중 한 곳으로 옮긴다 |
| 한글화 | 값의 뜻은 실무 정보인데 표기가 계약 토큰·모델명·필드명이다. 표시만 바꾸고 서버 값·URL 값·unknown/null의 의미는 보존한다 |
| 유지 | 판단에 필요하거나 아래 1.2의 경고다 |

- 식별자·해시는 **줄이지 않는다.** 옮길 수는 있다(`lib/glossary.ts:14` 개정).
- 모르는 코드(사유 코드·오류 코드)는 한글화 대상이 아니면 그대로 통과시킨다(`web/frontend/AGENTS.md`).
- 뜻이 다른 빈 값은 합치지 않는다: 서버가 null을 줌 = `미제공`, 확인되지 않음 = `미확인`, 계산할 수 없음 = `계산 불가`, 실제 0 = `0`. 같은 뜻을 다르게 쓴 것만 합치고 영문 `null` 토큰은 표시에서 뺀다.

### 1.2 지우면 안 되는 경고

① 참조 실행 표식(`참조 실행 · 품질 미측정`/`mock 참조`/`표식 없음`, `lib/qualityStatus.ts`) ② 회차 모드 `· 측정 전용 실행`(`scope.purpose === "gate_measurement"`) ③ 부분 산출물·검증 경고 ④ 계산 불가≠0, 실패≠성공/변경 없음 ⑤ 판정 없음≠비관련 ⑥ `is_current=false` 안내 ⑦ 담당자 이름≠인증. 그리고 발주계획 상세의 "계획 정보 기반 탐색 신호 · 회사 적합성과 참여 자격은 미확인", 심층 보고서 범위 주석(`DeepReviewPage.tsx:770`), `AttachmentPanel.tsx:53,79`의 안내, 사전규격 ⑥ 접힌 진단 Collapsible(`0915_ui-redesign/spec.md:234`, 실패·사람 확인이면 기본 열림).

경고 문장이 운영 코드와 한 블록에 있으면 요소를 나눠 문장만 남긴다.

## 2. 공용 UI

### 2.1 수집 회차 선택 — `SourceRunFilter`

- `lib/runOptions.ts`(순수 함수)
  - `runOptionLabel(run)`: `09-19~09-20 수집`(U1은 기존 `formatRunRange`의 긴 표기로 구현했고, U3이 `lib/format.ts`에 연도를 생략하는 짧은 회차 표기를 만들어 맞춘다 — 해가 올해와 다르면 연도를 남긴다. 설명은 `09-20 06:10 생성`). 수집 기간이 없으면 생성 시각 기준 `09-20 06:10 수집분`. `lib/format.ts`의 `formatRunRange`를 재사용한다.
  - `buildSourceRunOptions({ runs, extraRunIds, selectedRunId, isError, audience })`: `audience: "practitioner"`는 description에 생성 시각(같은 기간 재실행을 구분), `"ops"`는 run_id. 목록에 없는 URL 값은 `선택한 회차 (목록에 없음)` + 사유(`회차 목록 조회 실패`/`목록에서 확인할 수 없음`)이며 **조용히 다른 회차로 바꾸지 않는다.** 발주계획에서 실행에만 있는 회차는 `수집 정보 없는 회차`이고 날짜를 지어내지 않는다.
- `components/common/SourceRunFilter.tsx`(Astryx `Selector` 기반): 보이는 라벨 `수집 회차`, `hasSearch`, 누적 옵션 **`모든 수집 회차`** 하나, 로딩 placeholder `회차 목록 조회 중`, 오류는 컴포넌트 안 `role="alert"` 한 줄 + `다시 시도`. props: `runs`, `extraRunIds?`, `value`, `onChange`, `isPending`, `isError`, `onRetry`, `isDisabled?`, `allRunsDescription`.
- 기반으로 쓰지 않는 것: `ReviewFilterSelector`(라벨 숨김 고정, 검색·오류 개념 없음), `RunPickerField`(회차 필수·첫 회차 자동 선택·`?run=` 강제).
- 위치: 발주계획·사전규격 모두 `WorkspaceFilterAdvanced` 안. 사전규격의 관측 날짜 범위는 도구 줄에 남는다. CSS는 `workspace-filters.css` 한 벌이며 `order-plans.css`·`pre-specs-relaxed.css`의 회차 규칙은 지운다.
- **공용 컴포넌트는 표시만 맡고 URL 정책은 페이지가 소유한다.** 지금 발주계획은 회차를 바꾸면 다른 필터·검색을 지우고(`OrderPlansPage.tsx:824`) 사전규격은 기존 조건에 더한다(`PreSpecsPage.tsx:746`). **M1 승인(2026-09-21): 두 화면 모두 회차를 기존 조건에 더한다.** `/runs`의 `이 회차 보기` 링크는 `전체` 보기로 연다.
- 접힌 상태에서 회차가 걸렸음을 알리는 두 장치
  1. `WorkspaceAdvancedToggle`의 `activeCount`에 회차를 포함한다. 정렬(`표시 순서`)은 필터가 아니므로 세지 않는다. 사전규격은 `activeFilterCount`를 새로 만든다. 초기화는 회차도 지운다.
  2. `source_run_id`가 있으면 `WorkspaceFilterContext`에 `회차 보기 · <라벨> [· 측정 전용 실행] [모든 회차로]`를 접힘과 무관하게 그린다. 회차 목록 오류도 이 줄에서 알린다.
- `· 측정 전용 실행`은 **M1 승인(2026-09-21) A안**: 회차 줄에 단일화하고 목록 바닥 줄의 회차 모드 문구는 없앤다(바닥 줄은 `판정 없음` 계열에만 남는다). 조건식은 그대로다. ADR-0062의 09-21 개정(바닥 줄)을 이 결정으로 다시 개정한다.
- 운영 쪽(`shell/RunSelector`, `runs/RunPicker`, Metrics 모달)은 컴포넌트를 두고 옵션 라벨만 `runOptionLabel`로 맞춘다. 대시보드 선택기는 §7에서 패널째 빠진다.

검증 표(같은 패키지에서 spec으로 고정한다. 기존 검사는 펼치지 않은 선택기·native combobox를 전제한다 — `order-plans.spec.ts:139`, `prespec-list-work.spec.ts:135`):

| 입력 | 기대 |
|---|---|
| 상세 필터를 펴고 회차 선택 | URL `source_run_id` 반영, 회차 줄 표시, `activeCount` +1, 선택 집합 초기화 |
| 상세 필터를 접음 | 회차 줄·`activeCount` 유지 |
| `모든 회차로` / 누적 옵션 | URL에서 제거, 회차 줄 사라짐 |
| 필터 초기화 | 회차도 지워짐 |
| 새로고침·뒤로가기 | URL 상태 그대로 복원 |
| 목록에 없는 회차 URL로 진입 | 다른 회차로 바뀌지 않음, 회차 줄에 사유 표시 |
| 회차 목록 조회 실패 | 선택기 안 alert + 회차가 걸려 있으면 회차 줄에도 표시, 목록 자체는 막지 않음 |
| 측정 전용 실행 회차 | `· 측정 전용 실행` 표시(승인된 위치) |
| 미저장 입력이 있는 상태에서 회차 변경 | 기존 미저장 확인 동작 유지 |

### 2.2 페이저·빈 상태·로딩

- `ListPagerControls`를 `ReviewPrimitives.tsx`의 `ListPager`(:341) 옆에 둔다: Astryx `Button size="sm" variant="secondary"`, `1–50 / 1,234`(천단위), 항상 표시. 발주계획(:1948-1959)에서 승격해 사전규격(:1042-1067)·사업 추적(`OpportunitiesPage.tsx:524-547`)·Go/No-Go(`GoNoGoPage.tsx:515-520`)가 쓴다.
- 빈 상태는 `common/EmptyState`, 로딩은 `SkeletonPanel`. 사업 추적(:477-495)·Go/No-Go(:488-501)의 복제 마크업을 지운다.

### 2.3 포맷과 이름

- `lib/format.ts`에 `formatMoment`·`formatCount`(`WorkspaceFilters.tsx:30`에서 옮기고 re-export)·`formatAmount`·`missingLabel(kind)`를 두고 중복을 교체한다: `orderPlanFormat.ts:8`, `bid-delta/labels.ts:100`, `opportunities/trackingFlow.ts:475`, `PoliciesPage.tsx:78`, `OrderPlanPolicyPage.tsx:149`, `QualityGatesPage.tsx:138`, `OrderPlansPage.tsx:218`, 그리고 `toLocaleString` 직접 호출.
- 목록 범위 설명 단추는 `목록 기준`, 다이얼로그 제목은 `이 목록의 기준`, 목록 머리는 `{화면 이름} 목록 · N건`(M1 승인). 빈 값 문구는 `예산 미제공`·`추정가격 미제공`·`발주 시기 미제공`(연도만 있으면 `2026년 · 월 미제공`). 검색 placeholder와 접근 이름을 일치시킨다(`OrderPlansPage.tsx:1633-1642`).
- 삭제: `common/DataTable.tsx`, `ReviewState`, `ReviewStateGroup`, `ReviewSecondaryInput`, `ReviewOutlineChip`, `WorkspaceFilterEnd`(삭제 전 `src`·`tests` 참조 0 확인).
- 통일하지 않는 것: 사전규격 목록의 무채색 등급(ADR-0055 결정 2).

### 2.4 사업 추적·Go/No-Go 골격

- `opportunity-workspace`·`gng-workspace`를 `SplitWorkspace`로, 목록 머리·sticky 상세 머리·목록 폭을 발주계획·사전규격과 맞춘다. **M1c 승인(2026-09-21): A안** — 목록은 Astryx `Table`을 유지하고 글자 크기·행 간격만 공용 값에 맞춘다. 상세 머리는 `StickyDecisionHeader` + `AgencyFeature`.
- **목록 첫 줄 글자 단의 정본은 공용 `--review-list-primary`(14.4px)다.** 발주계획·사전규격 목록은 2026-09-20에 사용자 승인으로 +2px 올린 값이고, 네 목록이 같은 크기를 쓴다. 사업 추적의 `--opportunity-row-primary`(13.5px)와 그 값을 고정한 단언(`opportunities.spec.ts`의 "13.5px·12.6px 단")은 이 결정으로 14.4px·12.6px로 개정한다(시안 M1c의 표 행이 13.5px로 그려진 것은 시안 CSS의 잔재이며 README의 "공용 값에 맞춘다"가 승인 문안이다). Go/No-Go는 C2에서 이미 14.4px다.
- 교차 검사는 세 축으로 나뉜다(C1): `unifiedFrame`(공용 분할 틀·sticky 상세 머리·페이저 위치·발주기관 블록) 네 화면 모두, `unifiedListParts`(열 이름 줄·선택 도구줄) 탐색 두 화면만, `rowType`(행 첫 줄 크기) 화면별 selector.
- `tests/explore-workspace-consistency.spec.ts:29-34`의 공란을 채운다.

## 3. 운영 정보 처분표

### 3.1 발주계획

| 대상 | 처분 |
|---|---|
| 행 `판정 policy …`(`OrderPlanListRow.tsx:36-38`) | 삭제. policy가 없을 때의 `판정 없음`은 유지(경고 ⑤) |
| 행 `첫 관측 …` | 한글화 → `첫 수집 09-19`. 해가 다르면 연도를 붙인다 |
| 배지 `BM25 선정·탈락` | 삭제. `실패·거부`만 `선별 실패`로 조건부(경고 ④) |
| 배지 `Qwen 미시도/실패/거부/unknown`(`orderPlanFormat.ts:56-63`) | 한글화 → `모델 미판정`·`모델 판정 실패`·`모델 응답 거부`·`모델 상태 미확인` |
| 모델 판단 배지·보기 탭(M3 승인 2026-09-21) | 배지는 `모델 ·` 머리말을 둔다(`모델 · 관련`·`모델 · 판단 보류`·`모델 · 비관련`) — 사람 판정으로 읽히지 않게. 보기 탭 `BM25 탈락` → `1차 선별 제외`, `실패·거부` → `선별 실패` |
| `예산 null (미제공)`, `null (계획 시기 미제공)` | 한글화 → `예산 미제공`, `발주 시기 미제공` |
| `피드백 수정본 n` | 조건부(n≥1), `사람 판단 수정 n회` |
| 상단 실행 상태 칩 | **조건을 먼저 고친다.** `latestCompletedExecution`(:418)은 성공·부분 성공만 고르므로 "과거 성공 + 이후 실패 + 진행 중 없음"을 문제없음으로 본다. "목록의 판정 기준 실행"과 "최근 실행의 건강 상태(실패·중단·조회 실패 포함)"를 분리하고 후자에 문제가 있을 때만 칩을 그린다. 칩이 운영 화면 링크를 겸한다 |
| `모델 연결 비허용`, `실행 상세 →` | 이동(§4) / 삭제 |
| 자동 실행 꺼짐 배너(:183-198, 1565) | 조건부 + 한글화. "자동 선별이 꺼져 있습니다 · 운영 화면에서 확인 →". `daily-trigger` 응답에는 오늘 실행 여부가 없으므로 "오늘 돌지 않았습니다"로 단정하지 않는다. 사유 상세는 `OrderPlanPolicyPage`에 이미 있다 |
| "일일 자동 실행 상태를 확인하지 못했습니다. 켜져 있다고 가정하지 않습니다" | 유지 |
| `C-2 실행 목록을 불러오는 중…` | 삭제. 실패 배너는 조건부 + `선별 실행 상태를…` |
| 누적 판정 없음 배너의 execution_id 나열(:1590-1596) | 배너·"실패를 성공으로 해석하지 않습니다"는 유지, 나열만 삭제 |
| 바닥 범위 줄의 `실행 8자 · status · policy` | 삭제. `· 측정 전용 실행`은 유지(§2.1) |
| 상세 필터 축·값(:1655-1725), `filterMeaning`(:1506-1516) | 한글화. 축 `모델 판단`·`1차 선별`·`선별 처리 상태`(R2 구현에서 개명 — 이 축은 1차 선별의 실패·거부까지 걸러 "모델 처리"라 부르면 사실과 어긋난다)·`사람 판단`, 값 `관련`/`판단 보류`/`비관련`/`값 없음` 등. URL 값은 그대로. 용어는 `lib/glossary.ts`에 `ORDER_PLAN_*_LABEL`로 둔다 |
| `실행 상태와 표시 규칙` 다이얼로그(:2003-2023) | 표시 규칙은 한글화해 유지, 실행 상태·run_id 전문은 이동(§4) |
| `SignalPanel`(:483-515) | **M3 승인: `선별 신호 · 실행 기록` 다이얼로그를 없앤다.** 판단 근거·가까운 회사 역량은 상세 본문으로(R2가 한다), rank·score·source run·관측 시각은 이동(§4) |
| `TelemetryPanel`(:517-623) | 이동(§4). `부분 산출물 있음`·실패는 실무 화면에 한 줄 조건부 유지(경고 ③) |
| `사람 판단 수정` 다이얼로그(:2065-2126, :703-707) | 한글화(`관련성`·`우선순위`·`메모`), `execution` 전문은 이동 |
| 상세 머리의 내부 `계획 ID`(`OrderPlanDetailPane.tsx:260`) | 접힌 기술 정보로. 외부 계획번호는 유지 |
| 추적 결정 상태 `계약 미구현`·`사업기회 미연결`(:37-47) | 한글화(실무 말) |

### 3.2 사전규격·심층 검토

| 대상 | 처분 |
|---|---|
| 회차 옵션 설명 `{kind} · {run_id}` | 삭제(§2.1) |
| `표시 범위` 다이얼로그의 `workspace_counts`·`projection`(`PreSpecsPage.tsx:1122-1124`) | 한글화. 품질 표식 문구(:1127)는 유지 |
| `PreSpecDetailPage.tsx:714` claim_id | ⑥ 접힌 진단으로 이동 |
| `CompanyFitSection.tsx:75-85` `판정 기준과 실행 정보` | ⑥ Collapsible로 병합(`0915_ui-redesign/spec.md:234` 준수). `:31` 표식·`:33` 안내는 제자리 |
| `PageOverviewSection.tsx:149-155` 모델·프롬프트, `:281-288` 실행 정보 | ⑥으로 이동. `:164` 표식 유지 |
| 제목 `현재 v4 개요 실행` | 한글화 → `현재 개요 검토` |
| 경계 문장(`PreSpecDetailPage.tsx:291-294, 649-651, 806, 930`) | **M4 승인: ② 추적 결정 카드에 한 번만** — "적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않습니다. 입찰 참여 여부는 최종 Go/No-Go에서 정합니다." 나머지는 삭제. 접힌 곳의 이름은 `기술 정보 · 주장 검증 진단, 고정 입력과 식별 해시, 회사 적합성 실행 정보` |
| `DeepReviewPage.tsx` `안전한 오류 코드`(:389-443) | 조건부. 실패 시 사람 말 한 문장, 코드는 접힌 `기술 정보` |
| 근거 uuid·SHA-256 전문·block_key·bbox(:655-691), 정책·프로필 버전(:762-781) | 같은 화면의 접힌 `기술 정보`로 이동. 시각은 `formatMoment`. 범위 주석(:770) 유지 |
| `SegmentInventoryPanel.tsx:128-183` | 이유 문장 유지, block_key·ID 나열은 접힘 |

### 3.3 Go/No-Go·입찰 변경·판정 이력·셸

| 대상 | 처분 |
|---|---|
| `verified · 검증됨` 식 병기(`GoNoGoPage.tsx:191-197`) | 한글화(영문 삭제) |
| `안전한 오류 코드`(:683-687, 897-899) | 조건부 + 접힘. `:679-682`의 "실패를 변경 없음으로 처리하지 않습니다"는 유지 |
| `비교 계산 프로그램이 없어…` 4회(:689, 717, 754, 869) | 1회(다이얼로그). 목록은 상태 칩 `비교 불가` |
| 결정 기록 `sequence`(:777-779) | 한글화 → `n번째 결정` |
| `BidDeltaDecisionPage.tsx:105-123` `InputRefFacts`, :143-146 해시 | 접힌 `비교 입력 기술 정보`로 이동. :216 경고 유지 |
| `NoticeCorrectionDialog.tsx:154` run_id 원문 | 회차 라벨(`runOptionLabel`) — 다만 다이얼로그가 회차 metadata(`RunSummary`) 없이 `run_id` 문자열만 받으므로 날짜를 지어내지 않고 "이 공고가 속한 수집 회차에 저장합니다" + 접힌 `기술 정보 · 저장 대상 회차`(전문)로 둔다(R6 구현). 회차 조회를 붙여 라벨을 만드는 것은 후속 |
| `BidDeltaDecisionPage.tsx`의 `안전한 오류 코드`(:350·:352·:986) | R6 범위에서 빠졌다 — F3(같은 화면을 고치는 다음 패키지)에서 Go/No-Go와 같은 방식(사람 말 + 접힌 기술 정보)으로 맞춘다 |
| 상단바 `RunSelector`(queue·judgments) | 유지(이 화면의 업무 축). 라벨만 공용 포맷 |
| `BasisPopover.tsx:47-66` | run_id 삭제, 회차 라벨·생성 시각만 |
| `ReviewWorkspacePage.tsx:109-111`, `RetrievalSignals.tsx:32` `focus_matches`, `API 직접 제공값` 부제 | 한글화 / 삭제 |
| TopBar 편집 범위 칩(`route-meta.ts:134-191`) | **M4 승인: 삭제**(`… 저장 가능`). 읽기 전용 표식과 경고 ⑦ 문장(담당자 입력 옆)은 유지 |
| `MutationFeedback.tsx:53` `· 오류 코드` | **M4 승인**: 문장 옆 접힌 `기술 정보`로, 보조기술에는 설명으로 계속 읽힌다 |
| 사이드바 `관리자 화면` | 삭제 |

### 3.4 우선 수정 — 지역 제한 표시 결함

`NoticeFacts.tsx:25-27`은 `regional_joint_contract_limit === "Y"` 또는 `basis`가 없으면 `지역 제한 없음`을 출력한다. 수집기는 빈 근거가 제한 없음의 증거가 아니라고 적는다(`collect_notices.py:623`). 명시 근거가 없으면 `지역 제한 미확인`으로 고친다. 시안과 무관한 정확성 수정이다.

## 4. 운영 수신처 — `/runs` 회차 상세의 `발주계획 선별` 탭

- 현재 `/runs`는 공고 판정 실행만 읽는다(`RunsPage.tsx:119,207`). C-2 실행 상세는 `OrderPlansPage.tsx:1146`에서만 읽는다.
- `components/runs/OrderPlanScreeningPanel.tsx`(신규): 발주계획 회차일 때 `RunsPage.tsx` 회차 상세에 탭으로 넣는다. 기존 `api.getOrderPlanScreeningExecutions({source_run_id})` + 실행 상세를 쓴다(백엔드 변경 없음). `RunStatusPrimitives`의 `Facts`·`Section`·`DataTable`·`StatusToken`을 재사용한다.
- 담는 것: 실행 ID·policy 버전·policy/binding 해시·집계 12칸·배치별 attempt·모델/revision·토큰·`duration_ms`·부분 산출물·오류 코드·artifact 요약(sha256 전문). 그리고 **계획별 신호**(rank·score·source run·관측 시각) — 실행 단위가 아니라 계획 단위 값이므로 실행을 고른 뒤 계획 목록으로 읽는 경로를 둔다.
- **O1 구현에서 확인된 사실(2026-09-21)**: 계획별 신호는 실행 단위가 아니라 **회차 단위 투영**이다 — `/api/order-plans`는 `source_run_id`만 받고 서버가 그 회차의 최신 완료 실행 하나를 투영한다(`scope.execution_id`). 고른 실행이 그 기준 실행과 다르면 경고 한 줄을 그리고 고른 실행의 결과처럼 보이지 않게 한다. 실행별 계획 신호가 필요해지면 백엔드 투영이 따로 있어야 한다. `부분 산출물`·`오류 코드`는 attempt가 아니라 실행 요약의 값이라 배치 표의 열이 아닌 실행 단위 사실로 둔다(시안 M2와 다른 점). 회차 상세의 탭 상태는 기존대로 지역 상태이고 주소에는 `execution=`만 남는다. `전체` 보기의 주소 표현은 `qwen=`(빈 값 sentinel)이다.
- 식별자·해시는 자르지 않는다. dt 라벨은 glossary 용어.
- 회차 상세 바닥 링크: `이 회차의 발주계획 보기`(`/order-plans?source_run_id=`), `이 회차의 사전규격 보기`(`/pre-specs?workspace=all&sw_only=false&source_run_id=` — `workspace=all`이 아니면 기본 보기에 걸러져 0건처럼 보인다). 실무 화면에서 운영 화면으로 오는 링크는 회차뿐 아니라 execution을 특정한다(회차 하나에 실행이 여럿일 수 있다).
- `RunStatusPage.tsx:152-155` 안내문을 사실에 맞게 고친다.
- **순서 규칙: 이 탭이 먼저 생긴 뒤에 §3.1의 이동 처분을 실행한다.**

## 5. 백엔드 투영

필드 투영의 증분 쿼리는 0이고 새 migration은 없다.

| 투영 | 위치 | 계약 |
|---|---|---|
| 발주계획 목록 `contract_method`·`notice_posted` | `app/screening/services/order_plan_screening.py:1060-1094` `_order_plan_item`, `schemas/order_plans.py:232` | `order-plan-list-response.v5`. 목록은 500행씩 전부 받으므로 두 필드만 |
| 판정 이력 응답(`…/screening-history`) | 같은 파일 `ScreeningHistoryResponse` | 항목 모델을 상세와 공유하므로 함께 올린다. 같은 family의 v2~v4를 상세가 써 왔으므로 충돌을 피해 **v5**(B1 결정, 2026-09-21) |
| 발주계획 상세 `contract_method`·`notice_posted`·`procurement_method`·`supervising_agency_name`·`bid_ntice_no_list`·`published_at` | 같은 파일 `:1342` 부근, 스키마 `:296` | `order-plan-detail-response.v4` |
| `ScreeningHistoryItem`에 실행 `purpose`·실행 시각 | `_history_items:1284`, 스키마 `:276` | 상세 v4에 포함. 운영·측정·참조 실행을 화면이 구분한다 |
| 사전규격 목록 `demand_agency` + 검색 `q`에 수요기관 포함 | `app/lifecycle/routers/pre_specs.py:688-693`, `:420` | 추가형(버전 유지, `schemas/pre_specs.py:106` 선례) |
| Go/No-Go 대기열 `deadline_at`·`budget`·`estimated_price`, 마감순 정렬 | `app/deep_review/services/decision_queue.py:53-76`, `schemas/bid_delta.py:224-234` | 마감 null은 맨 뒤, 기존 규칙(결정 없음 먼저)은 2차 키. `docs/bid-delta-contract-spec.md` |
| 사업기회 링크 `budget`·`deadline_at`·`planned_order_year`·`planned_order_month` | `app/lifecycle/services/opportunity_queries.py:79-139` `link_view`(`_link_options`가 이미 eager load) | 링크 단위. 대표 마감은 서버가 고르지 않는다 |

- 입찰공고 상세의 `demand_agency`는 투영하지 않는다. 입찰공고는 `agency`가 이미 수요기관 우선값이고 `demand_agency`는 항상 null이다(`collect_notices.py:566,609`). `agency`를 `수요기관`으로 재명명하지도 않는다(fallback이 있다).
- 버전을 올리는 응답은 백엔드 리터럴·테스트와 프런트 `lib/types.ts`(:1834, :1916)·`tests/api-mock.ts`(:2624, :2930)·`tests/order-plans.spec.ts`를 **한 패키지가** 소유한다. 이전 버전 소비자 처리(standards.md:7)를 확인하고, 프런트가 런타임에 버전을 검사하는지 먼저 본다.
- 문서: `docs/contracts.md`의 해당 절.

## 6. 빠진 실무 정보 화면

### 6.1 발주계획

- `OrderPlanDetailPane.tsx`가 선택 행마다 `api.getOrderPlan`(`api.ts:986`)을 1회 호출한다(`staleTime`). 이력이 많은 계획을 대표 입력으로 잡아 조회 비용을 한 번 확인한다(`_history_items`는 결과마다 실행 조회·feedback count를 한다).
- 상세: 신규/계속(`service_type`), 계약방법·조달방식·총괄기관·공고 게시 여부·연결 공고번호, 판단 근거와 가까운 회사 역량, 사업기회 링크(`tracking.opportunity_id` → `/opportunities/:id`), 관측 이력, 판정 변화.
- **M5 승인(2026-09-22): 판정 변화 표는 만들지 않는다.** 발주계획 판정은 수집 당일 1회만 하며 이후 재판정하지 않는다(사용자 확정). B1이 투영한 `screening_history`의 `execution_purpose`·시각은 계약에 남지만 이 화면의 소비자는 없다.
- 행: 추적 상태 칩만. **판단 근거는 목록에 싣지 않는다**(M5 승인 — 상세에서만).

### 6.2 사전규격

- 검토 제외 기록(누가·왜·언제, `schemas/pre_specs.py:89-91`).
- 수요기관: `AgencyFeature`(`ReviewPrimitives.tsx:240`) 재사용. **M5 승인: 수요기관을 크게, 공고(대행)기관을 작게.** 수요기관이 없으면(직접 공고) 지금처럼 공고기관만. 목록 행도 수요기관을 앞에, `· <공고기관> 대행`을 뒤에.

### 6.3 입찰공고·Go/No-Go·사업 추적

- `NoticeFacts.tsx`: `budget`은 3단 fallback(`collect_notices.py:612`)이라 '배정예산'이라 부르지 않는다. `예산(원문 제공 금액)`과 `추정가격`을 따로 보이고 값이 같아도 합치지 않는다. 개찰일시(`lifecycle.opening_at`), 유사 실적 매칭(`performance_matches`, `judgment.matched_performances`).
- Go/No-Go 대기열: 마감·예산 열, 마감순 기본 정렬. 사업 추적 행: 예산·마감·발주 예정(링크 값 그대로).
- 새 열은 1280px에서 넘치지 않아야 한다(`overflow.spec.ts`).

## 7. 실무자 대시보드

### 7.1 계약 (H0에서 닫음, 2026-09-22 — [ADR-0067](../tracking/decisions/0067-dashboard-workload-keys-and-panel-contracts.md))

`WorkloadProjection`(`extensions.py:133`)은 건수·불가 사유만 준다. 패널은 목록도 필요하므로
**패널마다 건수 키 하나와 목록 호출 하나를 짝지었다.** 원칙 넷:

1. **새 endpoint를 만들지 않는다.** 목록은 이미 있는 목록 API 넷이 낸다. 더한 것은 query 인자
   셋(`/api/opportunities`의 `deadline_within_days`, `/api/pre-specs`의 `deadline_within_days`,
   `/api/order-plans`의 `first_observed_from`)과 정렬 값 하나(`/api/opportunities`의
   `sort=deadline`)뿐이다.
2. **건수와 목록은 같은 모집단이다.** 건수는 짝지은 목록 호출의 `total`과 같은 술어·같은
   구현에서 나온다. 화면이 페이지를 받아 다시 세지 않는다(ADR-0053 결정 2·4).
3. **기준 시각은 요청 시각이고 창은 KST 일자로 끊는다.** `7일 이내`의 상한은 "요청 시각의 KST
   일자 + 7일"의 끝(= +8일 00:00 KST, 열린 경계)이고 하한은 요청 시각이다(지난 마감은 임박이
   아니다). 건수와 목록은 서로 다른 요청이라 몇 초 차이가 날 수 있다 — 화면은 건수를 목록
   길이로 덮지 않고, 목록이 비었다고 건수를 0으로 고치지 않는다.
4. **제공자가 없으면 `count=null`·`unavailable_reason`이다.** 화면은 `건수 미확인`으로 적고
   0으로 쓰지 않는다.

| 패널 | 목록 호출(전부 기존 API) | 건수 키 | 모집단이 같은 근거 | 정렬 | 기준 시각 |
|---|---|---|---|---|---|
| 마감 임박 추적 건 | `GET /api/opportunities?deadline_within_days=7&sort=deadline&limit=5` | `tracking_deadline_imminent` (lifecycle 직접) | 건수가 같은 `list_opportunities(deadline_within_days=7)`의 `total`을 같은 술어로 센다 | 아직 남은 권위 연결 마감 중 가장 이른 것 오름 → 그런 마감 없음은 맨 뒤 → `created_at` 내림 → `id` 내림 | 요청 시각(UTC aware), 상한은 KST 일자 |
| 최종 결정 대기 | `GET /api/bid-delta/decision-queue?status=pending&limit=5` | `bid_final_decision_pending` (기존, deep_review) | 제공자가 같은 `decision_queue(status="pending")`의 `total`을 부른다 | 입찰공고 마감 오름·마감 미제공 맨 뒤 → 미결정 먼저(B2에서 구현) | 요청 시각 |
| 사람 확인 필요 — 개요 | `GET /api/pre-specs?sw_only=false&overview_view=failed&sort=deadline` + 같은 호출의 `overview_view=attention` | `overview_human_review` (deep_review 제공자) | 두 개요 상태(`failed`·`needs_human_review`)는 서로 배타적이라 두 `total`의 합이 곧 키 값이다. 둘 다 `sw_only=false`·`workspace=all`·`deadline_scope=all`·`review_exclusion=all`(기본값)로 받아야 제공자와 같은 모집단이다 | 마감 3버킷(ADR-0064) | 요청 시각 |
| 사람 확인 필요 — 공고 확인 항목 | `GET /api/opportunities?reason=blocking_item&limit=5` | `blocking_items_open` (lifecycle 직접) | 목록의 `action_reason_counts["blocking_item"]`·`total`과 같은 첫 일치 분류(`_classified`)를 쓴다 | 기본(`created_at` 내림) | 요청 시각 |
| (위 두 하위의 합계) | — | `human_check_required` | 두 하위 건수의 합. **하나라도 `null`이면 합계도 `null`**(`sub_count_unavailable`) | — | — |
| 보류 재검토 | `GET /api/opportunities?hold_review=attention&sort=hold_review_due_at&limit=5` | `tracking_hold_review_due` (기존, lifecycle 직접) | 기존 계약 그대로 | 보류 기한 오름 | 요청 시각 |
| 새 우선 검토 발주계획 | `GET /api/order-plans?qwen_relevance=relevant&tracking_status=미선택&first_observed_from=<전일 KST 날짜>&limit=5` | `order_plan_new_priority` (screening 제공자) | 제공자가 같은 인자로 `list_order_plans(..., limit=1)`을 불러 `total`을 쓴다(`order_plan_pending`과 같은 방식) | 목록 API의 고정 순서 `order_plan_pk` 오름 — 패널은 `N건 중 상위 5건`으로 적는다 | 요청 시각의 KST 일자 −1일 00:00 |

- **서버는 대표 마감을 고르지 않는다**(§5 유지). `deadline_within_days`는 **링크 단위**로
  판정하고 돌려주는 것은 **사업**이다. 화면이 `links[]`의 `deadline_at`·`source_type`으로 어느
  마감이 임박했는지 골라 종류(`입찰 마감`/`의견등록 마감`)를 적는다. `sort=deadline`은 정렬
  키이며 응답에 대표 마감 필드를 만들지 않는다.
- **창에 드는 링크는 권위 있는 연결뿐이다**(`authoritative_link_predicate` — `official·확정`
  또는 `candidate·사람 확인 완료·accepted`). 확인 대기 후보의 마감이 사업을 할 일로 올리지
  않는다.
- **`deadline_within_days`는 추적 대상(`계속 추적`·`보류`)으로 함께 좁힌다.** `hold_review`가
  "보류 + 기한"을 한 인자로 묶은 선례와 같다(ADR-0067 결정 3). 패널 바닥 문구
  "추적 중·보류 사업 중 7일 이내"가 이 모집단이다.
- `WorkloadKey`(`app/lifecycle/schemas/workload.py`)의 고정 순서는 기존 다섯 뒤에
  `tracking_deadline_imminent`, `human_check_required`, `overview_human_review`,
  `blocking_items_open`, `order_plan_new_priority`로 **열**이다. 다른 모듈의 테이블은
  확장점으로만 받는다 — lifecycle이 `prespec_overview_run`·`order_plan_screening_result`를
  세지 않는다.
- 함께 닫는 findings: 사전규격 `deadline_within_days`(ADR-0064 부분 해소의 "남은 것")는 이
  패키지가 인자를 더해 닫는다. **M6가 `사전규격 의견등록 마감 임박` 패널 자체를 뺐으므로 이
  인자를 쓰는 workload 키는 없다** — 닫히는 것은 "창 인자와 그 집계가 없다"이고, 사전규격
  마감은 이제 `마감 임박 추적 건` 패널이 사업기회 단위로(의견등록 마감 링크를 포함해) 말한다.
  발주계획 `human_relevance=missing`은 **이미 구현돼 있었다**
  (`order_plan_screening.py`의 `_filter_values`와 `missing` NULL 투영) — findings 문장이 낡았고,
  이 패키지는 계약 문서에 적고 진입점 회귀를 붙이는 것으로 닫는다.

### 7.2 화면에서 빼는 것과 행선지

| 패널 | 행선지 |
|---|---|
| 회차 선택기, `회차 실행 보기 →` | 삭제(운영 화면 진입은 사이드바) |
| `회차 요약`, `검증 상태` | `/runs` 회차 상세로 이식 |
| `담당자 확인 요청` | 회사 역량 미확인(프로필 절 기준) → `판정 기준 › 회사 프로필`. 공고별 blocking 확인 항목(`notice_pks`, `projection.py:677`) → 대시보드 `사람 확인 필요`에서 사업 추적 상세 `확인 사항` 탭으로 |
| 회차 기준 `마감 공고` | 누적 `마감 임박 추적 건`으로 대체 |

### 7.3 패널

- 마감 임박 추적 건(**7일 이내**, 3일 이내는 빨간 D-day, 의견등록 마감과 입찰 마감을 종류를 적어 한 패널에), 최종 결정 대기(마감순), 사람 확인 필요(하위 건수 둘을 바닥에 따로), 보류 재검토(`HoldReviewPanel` 유지), 새 우선 검토 발주계획(**전일 수집 회차에서 처음 관측 + 모델 판단 관련**, `first_observed_at` 기준 — M6 승인 2026-09-22; H1 구현은 `first_observed_from=<전일 KST 00:00>` 하한만 두고 상한을 두지 않는다 — 당일 07:00 cron 도착분도 '새로'에 든다. 리더 채택 2026-09-22). 발주계획 타일에 `· 새로 N`.
- `새로`의 창은 `first_observed_from=<요청 시각 KST 일자 −1일>`이다. 즉 **전일 00:00 KST 이후에 처음 관측된 것**이라 전일 회차와 당일 회차 도착분을 함께 담는다. 일일 수집 cron이 아침 07:00에 도는데(`env/c2.env`) 창을 전일 하루로 닫으면 실무자가 보러 온 오늘 아침 도착분이 빠진다 — "새로 들어온 것"을 보여 주는 패널의 뜻과 어긋나므로 하한만 두고 상한은 두지 않는다.
- `모델 판단 관련`은 `qwen_relevance=relevant` 한 값이다(M6 문안 그대로). `order_plan_pending`이 쓰는 `relevant,uncertain`보다 좁으므로 두 건수는 다른 값이며 서로 대신하지 않는다.

## 8. 문서 개정 목록

| 문서 | 개정 |
|---|---|
| ADR-0066(신규) | 실무 화면과 운영 화면의 정보 경계 — §1 |
| ADR-0062 | 회차 선택 행(도구 줄 → 상세 필터 안, 공용 컴포넌트, run_id 제외, `/runs` 링크), 실행 상태 표시 행(최근 실행에 문제가 있을 때만) |
| ADR-0064 결정 7 | 도구 줄 순서에서 수집 회차 칸 제거 |
| `docs/0918_daily-operation/spec.md` §7 '행 표시'(결정 16) | 행에는 첫 수집일만, policy는 운영 화면, `판정 없음` 유지 |
| `web/frontend/src/lib/glossary.ts:14` | "줄이지 않는다. 운영 화면·접힌 기술 정보로 옮길 수 있다" |
| `docs/0915_ui-redesign/decisions.md`, `docs/ADR.md` | 항목 추가 |
| `docs/tracking/findings.md` | 분리한 후속 작업 인계(수집 확장, 단계 지연, 담당자 연락처, `budget` 출처) |
| `docs/contracts.md`, `docs/bid-delta-contract-spec.md` | §5, §7 |
| ADR-0067(신규, H0) | 대시보드 누적 workload 키와 패널 계약 — §7 |
| `docs/tracking/status.md` | 패키지·배포 기록 |
