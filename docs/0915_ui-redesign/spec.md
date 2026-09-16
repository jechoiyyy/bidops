# Spec: 관리 화면 재설계 (C 기준) — 2026-09-15

[`intent.md`](intent.md)의 결과를 구현 가능한 값과 규칙으로 옮긴다. 시각 정본은
[`mockups/shots/`](mockups/shots/) 8장과 [`mockups/artboards/`](mockups/artboards/)의
HTML이며, 아트보드의 값은 과거 앱 `zoom: 0.9` 기준 논리 px다. 제품은 같은 물리 크기를
native compact CSS 토큰으로 옮겼으므로 전역 배율을 적용하지 않는다.
(프레임 1422×889 = 1280×800 창). 시안의 건수·사업명·문안은 규칙을 설명하는 예시
데이터이고 운영 사실이 아니다.

## 사전규격 누적 탐색 변경 (2026-09-16)

이 절은 사전규격 목록의 기존 상태 탭·페이지 한정 필터 설명보다 우선한다.
기존 native compact 크기, 38%/62% 분할, 상세 본문 줄바꿈과 고정 바닥은 유지한다.

| 보기 | 범위 | 기본 정렬 |
|---|---|---|
| 검토할 항목 (기본) | 개요 사람 확인, 심층 검토 클릭 대기, 개요 완료 후 추적 결정 대기의 합집합 | 마감 임박순 |
| 최근 수집 | 한국 시간 오늘 포함 최근 7일의 관측, 기간 변경 가능 | 최근 관측순 |
| 추적 중 | 계속 추적·보류 | 게시 최신순 |
| 전체 이력 | 누적 전체 | 게시 최신순 |

- 모든 의미 필터는 서버가 페이지 분할 전에 적용한다. 보기 건수는 활성 보기만
  제외한 필터 기준, 목록 전체 건수는 활성 보기까지 적용한 기준이다.
- 개요 상태·등급·추적 결정·추적 상태·업무구분·발견 경로·마감 여부는 상세 필터다.
  개요 미시작은 실제 대기·진행과 구분한다.
- 회차 기본값은 모든 회차이며 선택 회차에서 관측된 공고의 현재 상태를 보여준다.
  최근 수집 기간과 회차는 같은 관측 행에 적용한다. 같은 공고는 한 번만 표시한다.
- 마감 임박순은 마감 전 가까운 순 → 마감 경과 최근순 → 미확인 순이다.
  의견 마감 경과는 추적 종료나 검토 완료가 아니다.
- 다음 행동은 사람 확인 → 심층 검토 열기 → 추적 결정 순으로 하나를 표시한다.
  기존 상태에서 파생한 탐색 안내이며 새로운 업무 상태나 자동 실행이 아니다.
- 발견 경로 표시는 발주계획 연계/독립 발견이며 wire의 추적/신규 값은 유지한다.
- 전부 한 페이지면 `전체 N건`, 여러 페이지면 `전체 N건 중 X–Y건`으로 표시한다.
  페이지 크기는 200건이다. 이 범위는 스크롤 viewport가 아니라 페이지의 범위다.
- 조건은 URL에 보존하고 의미 필터 변경 시 offset·선택을 초기화한다. 정렬·페이지
  이동은 선택을 유지한다. 기존 view 링크는 전체 이력의 개요 상태 필터로 연결한다.
- 검증: 200건 이후 일치 항목, 회차 중복, KST 기간 경계, 마감 정렬, 보기 집계,
  선택 순회·미저장 보호, 1280×800·1440×900 레이아웃을 관련 API/UI 검사로 확인한다.

## 1. 팔레트와 토큰

### 1.1 테마 토큰 (`web/frontend/src/themes/bidops/bidopsTheme.ts` → `astryx theme build`)

라이트 값만 바꾼다. 다크는 미활성이므로 현재 값을 둔다. 대비비는 흰 카드 기준이며
`scripts/check-contrast.test.mjs`가 게이트다.

| 토큰 | 현재 | 변경 | 근거 |
|---|---|---|---|
| `--color-background-body` | `#F2F0EF` | `#F6F7F4` | 회녹 canvas |
| `--color-background-surface` · `-card` · `-popover` | `#FFFFFF` | 유지 | |
| `--color-background-muted` | `#E7E4E2` | `#EEF0EC` | 중립 칩·보조 표면 |
| `--color-background-inverted` | `#161B2F` | `#26391A` | 사이드바가 더는 읽지 않음. `.ps-chip-dark`·실행 단계 번호 등 어두운 면 전용 |
| `--color-on-dark` | `#D4CDCB` | `#E4EAD9` | `#26391A` 위 10.9:1 |
| `--color-accent` · `--color-icon-accent` | `#5B687C` | `#587A2B` | 주 단추 채움 · 흰 글자 4.96:1 · body 위 4.6:1 |
| `--color-accent-muted` | `#E4E7EB` | `#F1F6E8` | 선택 행·활성 탭·완료 칩 바탕 |
| `--color-text-accent` | `#5B687C` | `#3F5A1C` | 링크·강조 글자 7.8:1 |
| `--color-on-accent` | `#FFFFFF` | 유지 | |
| `--color-text-primary` | `#17181F` | `#1B211D` | |
| `--color-text-secondary` | `#3C4452` | `#4C5650` | body 위 7.2:1 |
| `--color-text-disabled` | `#8D8F8E` | `#9AA39C` | disabled 한정 |
| `--color-icon-primary` / `-secondary` | `#17181F` / `#5F6570` | `#1B211D` / `#79837C` | 보조 아이콘 body 위 3.1:1 |
| `--color-border` | `#D4CDCB` | `#E2E5DF` | 장식(3:1 대상 아님) |
| `--color-border-emphasized` | `#9F9A9B` | `#C9CFC3` | 입력 테두리 |
| `--color-success` / `-muted` | `#007004` / `#C5E5C0` | `#3F5A1C` / `#F1F6E8` | intent 결정 1 · 7.2:1 |
| `--color-error`·`-muted`, `--color-warning`·`-muted`, hue ramp 9종 | | 유지 | 경고·실패는 포인트와 경쟁하지 않음 |
| `--radius-container` | 0.75rem(10.5px) | 1rem(14px) | 카드 |
| `--radius-element` · `--radius-inner` | 8.75px · 5.25px | 유지 | 단추·칩 |
| `--shadow-low` | `0 2px 4px …, 0 4px 8px …` | `0 1px 2px rgb(27 33 29/5%), 0 6px 18px rgb(27 33 29/7%)` | 카드가 선 없이 뜸 |

### 1.2 프로젝트 토큰 (`themes/bidops/brand.css`, 신설; `grade-ramp.css`와 같은 방식)

| 토큰 | 값 | 쓰는 곳 |
|---|---|---|
| `--bo-brand` | `#75A03B` | 진행 막대 채움, 완료 단계 테두리·번호 배경, 밑줄 탭 |
| `--bo-brand-edge` | `#CFDFB5` | 완료 단계 카드 테두리, 상세 열기 단추 테두리 |
| `--bo-brand-deep` | `#3F5A1C` | 진행 막대 첫 단(100%) |

`--bo-brand`는 **글자에도, 흰 글자를 얹는 채움에도 쓰지 않는다**(3.07:1).
`check-contrast.test.mjs`에 `['bo-brand', 'color-background-card'] ≥ 3.0`(비텍스트, 실측
3.07:1)만 추가한다. `['bo-brand', 'color-background-body']`(canvas 위)는 실측 2.85:1로
3:1에 못 미쳐 대상이 아니다 — `--bo-brand`는 흰 카드 위 비텍스트에만 쓴다.

### 1.3 등급 ramp (`grade-ramp.css`)

| 단계 | 배경 | 라벨 | 대비 |
|---|---|---|---|
| 1단 우선 검토 | `#3F5A1C` | `#FFFFFF` | 7.8 |
| 2단 검토 권장 | `#587A2B` | `#FFFFFF` | 4.96 |
| 3단 관찰 대상 | `#CFDFB5` | `#1B211D` | 11.6 |
| 4단 제외 | `#EEF0EC` | `#3C4640` | 9.4 |
| 판정 없음 | `#FFFFFF` + 1px `--color-border` | `#4C5650` | 7.5 |

등급은 항상 글자를 동반한다. 2단이 주 단추 채움과 같은 값인 것은 intent 결정 2로
허용한다.

### 1.4 의미색 사용 규칙(양 화면 공통, 시안 `StatusVocabulary`)

| 대상 | 표현 |
|---|---|
| 개요 검토 상태 | `완료` accent-muted 칩 · `사람 검토 필요` orange · `실패` red · 나머지 중립 |
| 추적 결정 | `미선택`·`계속 추적`·`보류`·`종료`·`사업기회 미연결` 모두 outline 칩(흰 바탕 + 테두리) |
| 근거·검증 | `주장 검증 완료 · 운영 승인 아님` accent-muted · `근거 위치 없음` orange · `검증 실패 · 사람 확인 필요` red |
| 회사 적합성 | `부합` accent-muted · `불일치` red · `판단 보류 · 정보 부족` yellow · `판정 없음 · 불일치 아님` outline |
| D-day | `--color-text-accent` 600 · 경과만 `--color-text-red` |
| 정보 없음 | 글자 `미확인`(`--color-text-disabled`, 600) 또는 중립 칩 `미확인` |

## 2. 공통 셸과 primitive

### 2.1 셸 (`styles/shell-relaxed.css`, `components/shell/*`)

| 부위 | 값 |
|---|---|
| 셸·canvas 배경 | `--color-background-body` (`#F6F7F4`) |
| 사이드바 | 폭 223.2px. 배경 `--color-background-body`, 우측 테두리 없음. 브랜드 줄: 면 없이 아이콘 25.2px(`--color-accent`, mask) + `BidOps` 18/700, 아래 부제 10.8/500, 좌우 14.4px 안쪽 1px `--color-border` 구분선(C안). 항목 최소 높이 32.4px이며 활성은 배경 `--color-background-surface` + `--shadow-low`, 글자 `--color-text-accent` 600. 사이드바 본문은 `--color-on-dark`를 더는 읽지 않는다 |
| 상단바 | 높이 68.4px. 배경 `--color-background-body`, 하단 테두리 없음. 제목 모드 h1 18/600, 경로 모드 10.8px |
| canvas 여백 | `10.8px 16.2px 14.4px`. `design-shell.spec.ts`의 기본 여백 기대값을 함께 바꾼다 |
| 화면 밀도 | 전역 zoom 없이 기존 90% 물리 크기의 native compact 토큰 유지 |

`design-shell.spec.ts` "1440px 셸의 무드보드 색과 기준 치수" 기대값을 위 값으로
바꾸고, `accentToken`이 `587A2B`를 포함하고 `5B687C`를 포함하지 않는지로 뒤집는다.

### 2.2 필터 줄과 보기 탭 (`components/common/WorkspaceFilters.tsx`의 `WorkspaceFilterBar`, `styles/workspace-filters.css`)

- 필터 줄은 테두리·배경 없이 canvas 위에 놓인다(`padding: 0 4px`).
- 보기 탭은 밑줄형: 높이 28.8px, 글자 10.8px, 비활성 라벨 `--color-text-secondary`(비활성
  탭도 누를 수 있는 글자라 4.5:1을 지킨다; 건수만 `--color-text-disabled`), 활성
  `--color-text-primary` 600 + `box-shadow: inset 0 -2px 0 var(--bo-brand)`, 활성
  카운트는 `--color-text-accent`. 탭 사이 10.8px.
- 검색 입력과 고급 필터 토글은 native compact 컨트롤 높이 28.8px을 쓴다.
- `SW 중심 · 추적 예외 포함` 스위치는 native compact 크기, `--color-accent-muted` 바탕 + inset
  1px `--bo-brand-edge`, 글자 `--color-text-accent` 600.

### 2.3 분할 작업 영역과 목록 (`components/common/ReviewPrimitives.tsx`의 `SplitWorkspace`, `styles/review-primitives.css`, `pre-specs-relaxed.css`, `order-plans.css` 등)

- 작업 영역 전체가 카드 하나: 배경 surface, 반지름 `--radius-container`, `--shadow-low`,
  테두리 없음, `overflow: hidden`. 목록 38% / 상세 62%, 사이 1px `--color-background-muted`.
- 목록 머리·선택 도구줄·열 이름 줄·행·바닥의 구분선은 전부 `--color-background-muted`
  1px. 바닥과 열 이름 줄 배경 `#FBFCF9`(= body와 surface의 중간; 토큰은
  `color-mix(in srgb, var(--color-background-body) 50%, var(--color-background-surface))`).
- 행: 패딩 7.2px 14.4px, 제목 13.5/600, 기관 12.6, 메타 10.8 `--color-text-secondary`.
  선택 행 배경 `--color-accent-muted`, 좌측 inset 바 없음. 체크박스도 compact 토큰을 쓰며 체크됨은
  `--bo-brand` 채움 + 흰 체크.
- 단추: Astryx `sm` 25.2px·10.8px/500. primary 채움 `--color-accent`,
  outline은 흰 바탕 + inset 1px `--color-border`, ghost 투명. disabled 채움
  `--color-background-muted` + `--color-text-disabled`.
- 칩(Astryx `Token`)도 native compact 높이·글자 크기를 쓴다. `outline` 칩(흰 바탕 + inset 1px
  `--color-border`, 글자 secondary)은 `Token`이 변형을 못 늘리므로 `ReviewPrimitives`의
  프로젝트 클래스로 둔다.

### 2.4 그 밖의 6화면(대시보드·발주계획·사업 추적·최종 Go/No-Go·판정 기준·실행 상태)

구성·문구·상태 규칙은 현재 화면 그대로이고 §2.1~2.3만 적용된다. 시안에서 이들 화면에
새로 그린 요소(최종 Go/No-Go의 `결정 전 확인` 목록·`추정 가격` 칸, 대시보드의 예시
수치)는 이번 범위가 아니다(intent 결정 4). 대시보드 KPI 카드의 강조(우선 검토)는
`--color-accent-muted` 바탕 + inset 1px `--bo-brand-edge`로 바꾼다.

## 3. `/pre-specs` 목록 우측 정보 영역

### 3.1 구성과 데이터 (위에서 아래, `PreSpecListDetailPane.tsx` 재작성)

| 순서 | 영역 | 내용과 출처 | 비어 있을 때 |
|---|---|---|---|
| 1 | 머리 | `발주기관` 캡션 + `agency`; 우측 칩 `origin`, `business_division`, `SW사업대상 {sw_business_status}`, `추적 결정 · {trackingLabel}`; 제목 `title` 20/600 최대 2줄; 메타 줄 `사전규격 {pre_spec_no}` · `게시 {published_at}` · `적합성 등급 {gradeLabel} ({등급 출처})` | `발주기관 미확인`·`사업명 미확인`·`번호 미확인`·`SW 미확인`·`판정 없음`·`미확인` (기존 helper 그대로) |
| 2 | 사업 설명 | 캡션 `사업 설명 · 개요 검토 결과 · {검증 라벨}`; `business_overview[0].text`를 생략 없이 줄바꿈 | 개요 미시작·대기: `preSpecOverviewStatus`의 대기 문장. 완료인데 항목 없음: `이번 입력에서는 확인되지 않았습니다.` |
| 3 | 주요 과업 요약 | 캡션 `주요 과업 요약` + `{n}건 중 {min(n,3)}건 · 전체는 상세에서`; `main_tasks[0..2].text` 번호 목록 | 위와 같음 |
| 4 | 예산·일정 4칸 | `사업 예산`(exact 원) · `의견등록 마감`(월.일 시:분 + D-day) · `게시`(월.일 시:분) · `본공고`(`lifecycle.bid_ntice_no_list`) | 각각 `예산 미확인`·`마감 일시 없음`·`미확인`·`미확인`. 구조화 필드만 쓰고 모델 문장을 칸에 넣지 않는다. 시안의 `사업 기간` 칸은 `게시`로 바꾼다 |
| 5 | 일정·규모 | `budget_and_period[0].text`를 `사업 규모·일정 · {text}`로 생략 없이 줄바꿈하고 출처 페이지 링크를 둔다 | 항목 없음이면 줄 자체를 생략 |
| 6 | 주의사항 | §3.2 | `주의 없음 · 미확인 {m}` 또는 `주의 없음` |
| 7 | 바닥(고정) | §3.3 | |

1~6은 `.pre-specs-detail-scroll` 안에 두고 사업 설명·과업·일정·주의사항 문장을
말줄임하지 않는다. 폭을 넘는 내용은 줄바꿈하고, 높이를 넘면 1~6 본문만
스크롤하며 머리와 7의 추적 조작은 고정한다(§6).

### 3.2 주의사항 산출(결정적, 새 분석 없음)

- 주의 건수 N = (개요 검증에서 실패한 주장 수: `PageOverviewVerification` 항목 중
  결정적 검사 실패) + `document.차단` + `document.실패` + (`auto_preparation_status`가
  `blocked`이면 1).
- 미확인 건수 M = `unknowns.length`.
- 한 줄 문구 우선순위: 검증 실패 주장의 `text` → 첨부 차단·실패(`첨부 차단 n · 실패 n`)
  → `auto_preparation_reason` 문장 → 없으면 첫 `unknowns[0].text`.
- 표시: `주의 {N}건 · {문구} · 미확인 {M}` + `근거 보기 →`(상세 ⑤로 앵커). N=0이면
  `주의 없음 · 미확인 {M}`. 색은 N>0일 때만 orange 계열(`--color-background-orange` 바탕).

### 3.3 추적 조작과 상세 진입(바닥 고정 블록)

- 줄 1: `추적 결정` + `현재 · {trackingLabel} → 저장하면 계속 추적`; 우측 캡션
  `보류·추적 종료는 사업 추적에서 변경`.
- 줄 2: `TrackingDecisionControl presentation="inline"`(신설 변형): 선택 사유 Selector
  (flex 1) · 담당자 이름 입력(168px) · `추적 시작` primary 32px. 사유 preset·직접 입력·
  담당자 기억·저장 오류·성공 문구·비활성 사유는 기존 컴포넌트 그대로다. 승계·기록된
  사업은 폼 대신 기존 "현재 추적 상태" 블록을 같은 자리에 둔다.
- 줄 3: `다음 작업 · {nextActionOf(item)}` · `입찰 참여 여부는 최종 Go/No-Go에서 결정` +
  우측 `상세 페이지 열기 →`(outline, `preSpecDetailUrl`, 선택 순회 index 규칙은 PN-03
  그대로).
- 대화상자(`추적 선택 변경`)는 없앤다. 미저장 보호는 폼이 `onDirtyChange`로 목록에
  알리고, 행 전환·필터 변경·상세 이동 guard는 기존 `trackingGuard` 그대로 쓴다
  (`LS-06` 두 검사가 그대로 통과해야 한다).

### 3.4 `전체 선택`

- 위치: 도구줄에서 `선택 {n}건` → **`전체 선택`** → `전체 해제` → `선택 항목 검토` 순.
  `aria-label="현재 페이지 전체 선택"`.
- 동작: 현재 페이지에 렌더된 `items`의 `notice_pk`를 기존 `selectedIds` 뒤에 **중복
  없이** 덧붙인다(`lib/listSelection.ts`에 `selectMany(state, ids, metadataById)` 추가,
  `dedupeIds` 재사용). 다른 페이지에서 고른 ID는 그대로 남는다. 정렬 메타데이터는
  `toggle`과 같은 규칙으로 함께 기록한다. 검색 결과 전체 페이지 선택은 만들지 않는다.
- 비활성: 목록이 비었거나 현재 페이지 항목이 이미 모두 선택돼 있을 때. 우측 캡션
  `이 페이지만 추가`.
- 저장·복원·필터 지문 초기화는 `useListSelection` 규칙 그대로(`LS-04`).

## 4. `/pre-specs/:noticeId` 상세 — 세로 보고서형 6단

단일 열, 카드 최대 폭 1040px 가운데 정렬, 카드 사이 16px. 오른쪽 열(`현재 판단`·
`확인이 필요한 것`·`회사 업무 부합 여부`)은 없애고 내용은 아래 단으로 옮긴다.
등급 라벨과 현재 추적 상태 글자는 화면에 각각 한 번만 나온다.

| 단 | 카드 | 내용(기존 컴포넌트 재사용) |
|---|---|---|
| ① | 머리 카드 | 칩 줄(`사전규격 · {origin}`, D-day, `SW사업대상`, `본공고 {번호|미확인}`, 구분) · 제목 22/600 · 기관·`PreSpecRecordIdentity`(번호 복사·나라장터 원문)·품명 분류 · `사업 요약` 띠(`business_overview[0]` + 근거 링크) · 우측 `추적 결정 · {상태}` 칩 + `목록으로 돌아가기` · 팩트 스트립 6칸(사업 예산·의견등록 마감·게시·구분·적합성 등급(출처)·첨부 원문) 유지 |
| ② | 추적 결정 | `TrackingDecisionControl presentation="record"` 그대로. 카드 테두리 inset 1px `--bo-brand-edge`, 머리 띠 `#F9FBF5`. 캡션 두 줄 유지. 승계·기록 사업은 기존 상태 블록 |
| ③ | 주요 과업과 수행 범위 | `main_tasks` 번호 목록(제목 = 첫 문장, 나머지 본문, 우측 근거 `제안요청서 p.n §`) · `사업 규모와 일정` = `budget_and_period` 항목을 타일로(문장 그대로, 파싱 없음) · 머리 우측 검증 라벨 칩 + `전체 근거 PDF 열기 ↗`. `현재 판단`의 `개요 입력 범위 확정 필요 · 확정하기 →`·`사람 확인 필요 · 사유 n건 → 보기` 알림은 이 카드 맨 위 알림 줄로 옮긴다 |
| ④ | 참여 조건 · 회사 적합성 · 위험 및 미확인 사항 | 3열 grid. **참여 조건**: `important_conditions` + v1 `지켜야 할 조건`(있을 때) 체크 목록 + 근거 링크. **회사 적합성**: 출처·판정 사유(`judgment.summary`, 관점; 등급 칩은 다시 그리지 않는다 — 등급 라벨은 ① 팩트 스트립이 1회 소유) + `사람 정정 사유`(없으면 `사람 정정 사유 없음`) + `회사 업무 부합 여부`(`CompanyFitSection compact`, 판정 없음 문구 그대로). **위험 및 미확인**: 검증 실패 주장(orange `근거 위치 없음`) → `unknowns`(중립 `미확인`) → `judgment.counterarguments`·`verification_items` → 회사 핏 `verification_items`. 카드 머리 우측 캡션 `적합성 등급 · 추적 결정 · 최종 Go/No-Go는 서로 대신하지 않음` |
| ⑤ | 근거 문서 · 첨부 | `PreSpecAttachmentList`를 표(파일 · 형식·크기 · 본문 추출 · 열기)로 · `문서 근거` 주장별 원문 위치 목록(`상세에서 근거 원문 열기 →`, 원문 블록 뷰어 유지) · 첨부 URL 규칙 캡션 |
| ⑥ | 처리 이력 · 문서 준비 · 검토 실행 | 머리 우측 단추: `문서 준비 열기/닫기`(조건부 렌더 토글, 기본값 규칙 `documentPanelDefaultOpen` 그대로) · `심층 검토 보고서 열기 →`(없으면 disabled `시작 기록 없음`) · 4단계 카드(첨부 취득·문서 묶음·개요 검토·심층 검토, 완료는 `--bo-brand-edge` 테두리 + 번호 `--bo-brand`) · 자동 시작 캡션 · 열렸을 때 `개요 입력 범위 확정`(`#ps-record-range`, 항상 mount) → `DocumentPreparationPanel` → `PreSpecDocumentSummary` · `처리 이력` 타임라인(시각·점·제목·설명; `변경 일시·사유`, 개요 실행 이력, 회사 핏 이전 판정) · 접힌 `현재 주장 검증 진단 · 고정 입력과 식별 해시 · 회사 적합성 실행 정보`(`Collapsible`; 실패·사람 확인 상태면 기본 열림) |

- 상단바: 경로 모드 `탐색과 추적 › 사전규격 › {pre_spec_no|번호 미확인}`. 우측 액션 슬롯에
  `선택 항목 {i} / {n}`(또는 `단건 상세`) + `이전`·`다음`(`aria-label` 기존 그대로).
  본문 맨 위의 순회 카드는 없앤다.
- `개요 검토 다시 실행` 단추는 그리지 않는다(intent 결정 3). 개요 재실행은 문서 준비
  패널 안에서만 연다. ⑥ 머리 단추는 `문서 준비 열기/닫기`·`심층 검토 보고서 열기 →` 둘이다.
- 용어: 화면 안에서 `회사 핏` 표기를 `회사 적합성`으로 통일한다(API 필드명·코드는 유지).

## 5. 바꾸지 않는 것

- REST·파일·DB 계약, 수집기, 모델 호출, `preSpecViews`·`preSpecNextAction`·
  `preSpecOverviewStatus`의 상태 어휘와 문장.
- 목록 행의 구성·글자 크기·순서(`pre-specs.spec.ts` "목록 행은 …" 검사), 보기 탭 순서,
  URL 동기화, 방향키 이동·경계 페이징, 선택 저장·복원·순회(`LS-*`·`PN-*`).
- 사전규격 외 6화면의 구성·문구·상태 규칙.

## 6. 수용 기준

| # | 기준 | 증거 |
|---|---|---|
| A1 | `npm run test:contrast` 통과(새 pair 포함) | 명령 출력 |
| A2 | `design-shell.spec.ts`가 새 색·여백·accent로 두 폭에서 통과 | `npm run test:design` |
| A3 | 목록 우측의 사업 설명·과업·일정·주의사항이 `ellipsis`나 line clamp 없이 줄바꿈되고, 1280×800에서 필요하면 본문만 스크롤하며 추적 조작은 고정된다 | `prespec-list-work.spec.ts` "우측 정보 영역은 긴 내용을 생략하지 않고 필요하면 본문만 스크롤한다" |
| A4 | `전체 선택`이 현재 페이지만 더하고 다른 페이지 선택을 유지하며 중복이 없다 | 새 `LS-08` (단위 `list-selection.spec.ts` + 화면 `prespec-list-work.spec.ts` 2페이지 fixture) |
| A5 | 우측 영역에 사업명·기관·설명·과업 3건·예산·마감·게시·본공고·주의 한 줄·추적 폼·상세 링크가 순서대로 있고 값 없음은 `미확인` 계열 | 새 검사(의미 층) |
| A6 | 상세 6단이 DOM 순서대로 있고 순회 단추가 상단바에 있으며 등급·추적 상태 글자가 각각 1회 | `prespec-briefing.spec.ts` 개정 |
| A7 | `LS-02`·`LS-04`·`LS-06`·`PN-01`·`PN-03`, `pre-specs.spec.ts` 추적 시작 3검사가 대화상자 없이 통과 | 기존 검사 개정 |
| A8 | `npm run test:screens` 전체 통과, `overflow.spec.ts` 두 폭 통과 | 명령 출력 |
| A9 | 픽셀 기준선 8장 교체와 승인 기록 | `plan.md` §증거 + 커밋 메시지 |
| A10 | 1440×900 구현 캡처가 `mockups/shots/`와 구성·색이 일치(픽셀 동일 아님; 글꼴은 Pretendard) | 캡처 8장 비교 기록 |
