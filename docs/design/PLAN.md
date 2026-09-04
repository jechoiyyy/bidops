# BidOps 화면 시안 기준 구현 계획

| 항목 | 내용 |
|---|---|
| 문서 상태 | 시안 기준 재정의 — 단계 A~F는 ADR-0045 이전 설계로 구현됨, 재작업 필요 |
| 기준일 | 2026-09-04 |
| 시각 정본 | `docs/design/mockups/_shots/` 14장 PNG (2026-09-02 17:46 렌더)와 대응 `_preview/` HTML |
| 시안 생성기 | `docs/design/mockups/build.py`, `screens.py`, `screens_more.py`, `preview.py`, `shoot.mjs` |
| 업무·상태 정본 | `docs/PRD.md`, `docs/business-rules.md`, `docs/contracts.md` |
| 색 정본 | 무드보드 `docs/design/moodborad.jpg` → `PRD.md` §4.1 토큰 표 (ADR-0047) |
| 관련 결정 | ADR-0039, ADR-0040, ADR-0041, ADR-0045, ADR-0046, ADR-0047 |

이 계획은 기존 화면이 기능 요구를 얼마나 구현했는지가 아니라, 승인된 시안을 실제 React 화면으로
재현하고 그 결과를 자동으로 검증하는 방법을 고정한다. 기존 구현의 API·업무 상태·감사 규칙은
보존하며, 시안에 없는 업무 판정이나 서버 계약을 새로 만들지 않는다.

## 0. 시안과 생성기의 현재 상태 — 먼저 해결한다

`_shots/`의 PNG 14장은 저장소에 커밋된 생성기(`screens.py`, `screens_more.py`, `canvas.json`)가
만들 수 있는 화면이 아니다. 확인한 사실은 다음과 같다.

- PNG·`.dc.html`·`_preview/` 산출물 42개는 모두 `사업 추적`, `오늘의 업무`, `추적 시작`,
  `탐색과 추적`을 담고 있다.
- 커밋된 생성기 세 파일에는 그 문자열이 하나도 없다. 대신 `검토 대기열`이 9곳 남아 있다.
- `canvas.json`의 아트보드 제목과 주석도 옛 구조(`검토 대기열 · 공고 1차 판정`, `사업기회 목록`,
  `사이드바 16→8`)를 가리킨다.

즉 **시안을 만든 생성기 버전이 저장소에 없다.** 현재 상태로 재생성 명령을 실행하면 시각 정본이
옛 화면으로 덮여 사라진다.

| 단계 | 상태 | 작업 |
|---|---|---|
| 0-1 | **완료** | `_shots/`·`_preview/`·`*.dc.html` 각 14장을 `web/frontend/tests/design-snapshots/`로 복사해 보존했다. PNG 14장의 sha256이 원본과 일치함을 확인했다 |
| 0-2 | 유효 | 0-3을 마치기 전에는 `screens.py`·`screens_more.py`·`preview.py`·`shoot.mjs`를 실행하지 않는다 |
| 0-3 | 미착수 | 보존본을 정본으로 삼아 생성기와 `canvas.json`을 시안에 맞게 다시 쓴다. `design-snapshots/artboards/`의 HTML이 입력이다 |
| 0-4 | 미착수 | 재생성한 PNG가 보존본과 일치하는지 확인한다. 일치하지 않으면 보존본이 이긴다 |
| 0-5 | **부분 완료** | `bidops` 테마와 대비 검사는 만들었다(단계 A-0·A-1). **아직 남은 것:** 0-4를 통과한 뒤에 시안 렌더 입력을 `bidops` 로 바꿔 **v2 기준 이미지**를 만드는 일(ADR-0047) |

0-3을 마치기 전에는 어떤 화면도 "시안 기준 통과"로 기록하지 않는다. 0-4를 통과하기 전에는 어떤
화면도 "팔레트 적용 완료"로 기록하지 않는다.

**0-4가 실제로 막는 것은 무엇인가.** 보존본 14장은 **무채색 v1**이고 0-4는 재생성 결과를 그것과
대조한다. 0-4를 깨는 것은 (a) 시안 렌더 입력 테마를 `bidops` 로 바꾸는 것과 (b) v2 기준 이미지를
만드는 것이다. 둘 다 `docs/design/mockups/` 의 생성기 입력을 바꾸는 일이다. **앱 쪽 변경은
0-4와 무관하다** — 생성기는 앱의 `data-astryx-theme` scope 도, `src/themes/bidops/` 의 존재도
읽지 않고 `neutral.css` 만 읽는다.

2026-09-04 기준: (a)·(b)는 하지 않았다. 앱은 단계 A로 `bidops` scope 전환까지 마쳤다.
그 결과 **앱이 승인된 시각 기준선 없이 새 팔레트로 돈다.** 팔레트 값 자체는 승인됐지만
(ADR-0047 헤더), 화면 단위 기준 이미지는 0-4 뒤에 만든다. 그때까지 화면의 시각 회귀는
`design-shell.spec.ts` 의 구조 검사와 대비 검사로만 지킨다.

### 0.1 이미 구현된 단계의 처리

이 branch(`phase-a-shell-worktree`)에는 단계 A~F의 구현이 이미 들어와 있다. 그 구현은
**ADR-0045 이전 설계**를 기준으로 했다. 즉 사이드바가 `회차 검토`/`누적 추적` 8항목이고,
`검토 대기열`이 판정 화면이며, 발주계획에 추적 결정이 없고, 반응형이 네 폭이다.

기존 구현을 지우고 다시 시작하지 않는다. 아래 차이만 단계별로 고쳐 나간다.

| 이미 된 것 | 새 설계와의 차이 | 고칠 단계 |
|---|---|---|
| 셸·테마 scope·248/76px 골격 | 지원 폭이 네 폭이다. 1280~1920px로 좁혀야 한다 | A |
| 공통 primitive | 결정 액션 배치 두 형태와 접힌 보조 입력 영역이 없다 | B |
| 발주계획 목록·상세 | 추적 결정이 없다. 사람 판단 수정만 있다 | C |
| 사전규격 그룹 목록 | 승계 배지와 신규 전용 결합 조작이 없다 | D |
| 사이드바 8항목·검토 대기열 | 7항목·사업 추적으로 바꿔야 한다 | E |
| 상세 3종 골격 | Go/No-Go form이 헤더에 있다면 본문으로 내려야 한다 | F |

기존 visual 기준선(`visual.spec.ts-snapshots`)은 옛 화면의 것이다. 새 설계로 바뀐 화면의
기준선은 §3.2·§5.3의 절차로 다시 만들고, 옛 폭(`mobile`·`tablet`) 기준선은 해당 화면을
이행할 때 함께 지운다.

## 1. 이번 작업의 목표

최종 목표는 다음 다섯 가지를 동시에 만족하는 것이다.

1. 14개 시안 아트보드의 셸, 정보 밀도, 컴포넌트 조합, 색·간격을 운영 화면에서 재현한다.
2. 적합성 등급, 참여 준비 상태, 심층 검토 실행 승인, 최종 Go/No-Go를 계속 별도 상태와 조작으로
   둔다. 추적 결정과 사람 판단 수정도 서로 다른 저장 경로로 둔다(ADR-0045).
3. 시안용 가상 데이터와 운영 API 데이터를 섞지 않는다. 운영 화면은 API만 사용하고, 시각 검증은
   Playwright 고정 fixture만 사용한다.
4. 구현 화면이 시안에서 벗어나면 기존 스냅샷을 덮어써서 통과시키지 않고 검증을 실패시킨다.
5. 데스크톱·노트북 두 폭에서만 검증한다(ADR-0046). 모바일·태블릿 레이아웃을 만들지 않는다.

`_shots`의 neutral 무채색 팔레트는 이 계획의 **v1 시각 기준**이며 생성기 복원(§0-3·0-4)의
대조 기준으로만 남는다. 운영 화면의 색 정본은 무드보드에서 파생한 `bidops` 테마이고
(ADR-0047, `PRD.md` §4.1), 그 팔레트로 렌더한 시안이 **v2 시각 기준**이다.

v2로 넘어가는 조건은 다음 셋을 모두 만족하는 것이다.

1. §0-4가 통과해 생성기가 v1 보존본을 다시 만들어 낸다.
2. `bidops` 테마 빌드 산출물과 대비 검사가 통과한다(단계 A).
3. v2 기준 이미지를 v1 위에 덮어쓰지 않고, 변경 사유·영향 화면·승인자를 기록한 별도 변경으로
   남긴다(§3.2, §6).

v1 무채색 기준선은 삭제하지 않는다.

## 2. 현재 미적용 원인과 교정 원칙

다음 문제를 해결하지 않으면 기능을 추가해도 시안과 구현은 다시 갈라진다.

| 문제 | 교정 원칙 |
|---|---|
| 시안을 만든 생성기 버전이 저장소에 없어 재생성이 정본을 덮어쓴다 | §0을 먼저 수행한다. 보존 → 생성기 복원 → 대조 순서를 지킨다 |
| `_preview`와 `_shots`가 Git에서 제외되어 기준 이미지가 자동 검증에 쓰이지 않음 | 승인된 기준 PNG를 별도 경로에 버전 관리하고 생성 입력의 hash를 기록 |
| visual test가 구현 후 저장한 자체 스냅샷만 비교함 | 시안 기준 스냅샷과 구현 스냅샷을 고정 fixture·고정 viewport에서 비교 |
| 시안은 전체 셸을 테마 scope 안에서 렌더하지만 AppShell은 페이지 내부만 scope를 가짐 | AppShell 최상위에 `bidops` scope를 두고 셸부터 같은 테마를 읽게 함 |
| 공통 셸 CSS가 legacy RootLab 토큰을 읽어 시안의 색·폭과 달라짐 | 셸 골격을 `bidops` 테마 토큰으로 통일하고 248px 사이드바·76px 상단바를 고정 |
| accent가 무채색이라 등급 4단을 표현할 색이 없음 | 무드보드 anchor에서 accent와 등급 ramp를 만든다(ADR-0047, `PRD.md` §4.1) |
| 브랜드 색을 화면 CSS나 `:root`에서 덮어쓰면 `@scope` 격리와 화면 단위 되돌리기가 깨짐 | 색은 theme 정의 파일에서만 정하고 화면은 토큰만 읽는다 |
| 시안은 정적 HTML에서 추출한 class 문자열이고 운영 화면은 실제 React 컴포넌트임 | 원자 class 문자열을 복사하지 않고 Astryx 컴포넌트의 실제 props·마크업으로 재구성 |
| 쓰지 않는 폭(390·768)의 레이아웃과 분기가 유지 비용을 두 배로 만듦 | 지원 폭을 1280~1920px로 좁히고 이행하는 화면에서 그 화면의 좁은 폭 분기를 함께 정리 |
| 기능 완료와 시각 완료를 같은 것으로 취급함 | 기능 계약 테스트와 시안 충실도 테스트를 별도 게이트로 운영 |

## 3. 시안 기준 산출물

### 3.1 기준 manifest

다음 정보를 담은 디자인 manifest를 추가한다.

- artboard 이름과 시안 파일
- 운영 route와 필요한 query
- viewport width·height 및 캡처 범위
- 고정 API fixture 이름
- 기준 PNG 경로와 생성 시점
- Astryx core·적용 테마(`bidops`, v1 대조용 `neutral`)·Pretendard 입력 hash
- 기준 이미지의 팔레트 버전(`v1-무채색` 또는 `v2-무드보드`)

manifest가 없는 아트보드나 route는 구현 완료 대상으로 표시하지 않는다.

### 3.2 기준 이미지

- 승인된 PNG는 `web/frontend/tests/design-snapshots` 아래에 복사해 Git으로 관리한다. §0-1의
  보존 경로가 여기다.
- `docs/design/mockups/_preview`와 `_shots`는 재생성 작업 디렉터리로만 사용한다.
- 기준 이미지를 갱신할 때는 기존 파일을 먼저 덮지 말고, 변경 사유·영향 화면·승인자를 기록한
  별도 변경으로 남긴다.
- 시안은 1440px 한 폭으로 렌더돼 있다. 1280px 기준 이미지는 구현 화면에서 새로 만들고 시안과
  픽셀 비교하지 않는다. 1280px에서는 §5.2의 구조 검사만 적용한다.

### 3.3 고정 fixture

시안에 보이는 제목·상태·건수·날짜·실패·unknown·null을 별도의 시각 fixture로 고정한다.
fixture는 운영 데이터나 회사 역량 사실로 취급하지 않으며, production API와 구분되는
Playwright route mock으로만 제공한다. 시안 값이 바뀌었다고 운영 데이터를 수정하지 않는다.

## 4. 구현 순서

각 단계는 코드와 시안 기준 테스트를 함께 추가하고, 해당 화면의 기준 이미지가 통과한 뒤에만
다음 단계로 진행한다.

### 단계 A — 팔레트 테마와 공통 셸

수정 대상: `web/frontend/src/themes/bidops/bidopsTheme.ts`(신규),
`web/frontend/src/components/shell/AppShell.tsx`, `Sidebar.tsx`, `TopBar.tsx`,
`web/frontend/src/styles/shell-relaxed.css` 및 공통 theme import 순서.

작업:

0. **[완료 2026-09-04] `bidops` 팔레트 테마를 만들었다**(ADR-0047). `neutralTheme.ts`에서 갈라
   나와 타이포그래피·모션·categorical·컴포넌트 override는 유지하고 색만 무드보드 파생값으로
   바꿨다(`src/themes/bidops/bidopsTheme.ts`, 171 token overrides). anchor 파생값의 혼합비는
   주석에 남겼다. `astryx theme build` 산출물(CSS·JS·d.ts)을 커밋했고 런타임 `defineTheme()`은
   쓰지 않는다. stock `neutral`은 upstream 대조용으로 남겼다. 등급 ramp는 `TokenName`이 닫힌
   union이라 테마에 넣지 못하고 `src/themes/bidops/grade-ramp.css`의 `--bo-*` 프로젝트 토큰이
   됐다(ADR-0047 §3). `--color-background-inverted`는 neutral이 재정의하지 않아 core 기본값이
   남으므로 `bidops`가 navy anchor로 덮는다.
0-1. **[완료 2026-09-04] 대비 검사를 새로 만들었다.**
   `web/frontend/scripts/check-contrast.test.mjs`(`npm run test:contrast`). 빌드된 CSS에서 실제
   토큰 값을 읽어 텍스트 4.5:1, 컴포넌트 식별 비텍스트 3:1, 등급 라벨 4.5:1, `#8D8F8E`의 텍스트
   토큰 배정 금지, 의미색 불변을 검사한다. 6 tests pass.
1. **[완료 2026-09-04]** AppShell 최상위가 `data-astryx-theme="bidops"`와 light 모드를
   소유한다. `AppShell.tsx`와 페이지 10곳의 scope를 함께 옮겨 `neutral` scope가 남지 않게 했고,
   `main.tsx`가 `bidops.css`·`grade-ramp.css`를 import한다. 페이지 안에만
   있던 중복 scope는 필요한 경우 유지하되 셸보다 좁아지지 않게 하고, `neutral`로 남은 scope가
   없는지 확인한다. scope 값 누락은 화면이 테마 없이 렌더되는 결과로 이어진다.
2. **[완료 2026-09-04]** 사이드바·상단바·본문 canvas가 `bidops` token을 읽는다.
   `shell-relaxed.css`의 단일 token bridge가 legacy 이름을 테마 토큰에 잇는다(새 색 값을 만들지
   않는다). 추가로 `theme.css`의 `@theme`이 Astryx와 이름이 겹치는 토큰 4개를 `:root`로 방출해
   테마를 이기고 있던 것을 제거했고, shadcn의 `--color-accent`는 `--color-shadcn-accent`로
   옮겼다(ADR-0047 §4-1). 사이드바의 `#161B2F`는 라이트 모드 안의 surface
   토큰(`--color-background-inverted`, Astryx core 토큰이며 `neutral`은 재정의하지 않는다)이며
   다크 모드가 아니다.
2-1. **[완료 2026-09-04]** `--color-nav-text`를 없앴다. `theme.css`와 `shell-relaxed.css`에
   서로 다른 값(`rgb(255 255 255 / 82%)` 대 `color-mix(--color-on-dark 82%)`)으로 중복 정의돼
   있었다. 사용처 3곳을 모두 `var(--color-on-dark)`로 바꿨다 — PRD §4.1이 사이드바 본문을
   `--color-on-dark`(greige `#D4CDCB`, navy 위 10.87:1)로 규정하므로 코드가 문서와 1:1이 된다.
3. 사이드바 248px, 상단바 76px, 목록 pane `min(390px, 34%)`, 상세 pane `flex:1`, 본문 여백을
   시안과 고정한다. 목록·상세 pane은 각자 스크롤을 가둔다.
4. **[완료 2026-09-04]** 지원 폭을 1280~1920px로 좁혔다. `shell-relaxed.css`의 1180·900·640px
   전환을 제거했고 1280px 미만은 가로 스크롤로 둔다. `playwright.config.ts`의 project를
   laptop 1280×800·desktop 1440×900 두 폭으로 고정하고 mobile 390·tablet 768을 없앴다
   (ADR-0046 결정 4). `theme.css`의 legacy 화면 media 블록은 그대로 두었다(ADR-0046 결정 5).
5. **[유지]** Pretendard 자체 호스팅과 외부 font 차단을 유지한다. `astryx theme build`가
   Google Fonts 링크를 권하지만 **따르지 않는다**(ADR-0039 결정 5).
6. **[완료 2026-09-04]** `tests/design-shell.spec.ts`가 26개 route의 테마 scope와 1440px 치수·
   색을 검사하고, legacy 토큰이 테마를 다시 이기지 않는지, 1280·1440·1920px에서 가로 오버플로가
   없는지를 함께 고정한다(§5.2·§5.3). 승인 PNG가 없는 동안 이 구조 검사가 셸의 완료 게이트다.

**단계 A 실행 결과 (2026-09-04).** `npm run test:contrast` 6 passed · `tsc -b` clean ·
production build 통과 · `design-shell.spec.ts` 5 passed 1 skipped(laptop 1280 / desktop 1440).
전체 Playwright는 **370 passed, 75 failed, 3 skipped**이며 실패는 두 종류다.

| 실패 | 건수 | 성격 |
|---|---|---|
| `visual.spec.ts` 스냅샷 | 73 | **예상된 실패.** 팔레트가 모든 화면의 색을 바꿨으므로 옛 무채색 기준선과 다르다. §3.2·§6에 따라 승인 없이 덮어쓰지 않는다. v2 기준 이미지는 §0-4 뒤에 만든다. 그동안 화면 단위 회귀 신호가 없다는 대가는 [findings.md](../tracking/findings.md)에 수용으로 기록했다 |
| `order-plans.spec.ts:287` (laptop·desktop) | 2 | **팔레트와 무관한 기존 실패.** 390px에서 행 클릭이 제자리 pane 교체가 아니라 `/order-plans/:pk`로 이동한다. 테스트가 기대하는 좁은 폭 동작이 구현과 다르며, 390px는 ADR-0046이 지원하지 않는 폭이다. 단계 C에서 이 테스트를 지원 폭 기준으로 다시 쓰거나 없앤다 |

완료 게이트:

- 모든 시안 대상 route에서 셸의 computed theme scope가 `bidops`다. `neutral` scope가 남은
  화면이 없다.
- 셸의 computed 색이 `PRD.md` §4.1의 토큰 값과 일치한다(canvas·사이드바·accent·본문 텍스트).
- 대비 검사가 통과하고, 텍스트 토큰에 `#8D8F8E`가 배정되지 않았다.
- 1440px 기준 사이드바·상단바 치수가 기준 이미지와 일치한다.
- 1280px에서 목록·상세 분할이 유지되고 가로 스크롤이 없다.
- legacy 녹색 셸이 시안 기준 route에 남지 않는다.
- `:root`나 화면 CSS에서 `--color-*`를 재정의한 곳이 없다.
- TypeScript strict와 production build가 통과한다.

### 단계 B — 공통 화면 primitive

시안에 반복되는 다음 구조를 실제 컴포넌트 조합으로 고정한다.

- 밀집 목록 행과 선택 상태
- 목록·상세 split workspace (좁은 폭 전환 없이 두 pane 유지)
- 필터 bar, SegmentedControl, Selector, TextInput, `현재 조합 저장`·`필터 초기화`
- 상태 Badge·StatusDot·`unknown`/`null`/`계산 불가` 표시
- 등급 4단 전용 스케일(의미색이 아니라 slate accent 농도 순서, `PRD.md` §4.1)과 항상 동반하는
  텍스트 라벨
- 상세 pane 바닥의 결정 액션 바와, 단독 상세 화면의 sticky 헤더 액션
- 본문 반복 목록과 우측 이력·연결 rail (rail에는 결정 액션을 두지 않는다)
- 접이식 상태 그룹과 빈 상태·부분 성공·실패 상태
- 접힌 보조 입력 영역(사람 판단 수정, 추적 상태 변경)과 그 append-only revision 이력

Astryx 컴포넌트는 props로 표현하고, 레이아웃만 프로젝트 소유 CSS로 둔다. 화면 한 곳에서
Tailwind utility와 Astryx styling을 섞지 않는다. 시안의 추출된 atomic class 문자열을 직접
React 코드에 붙이지 않는다.

완료 게이트:

- 같은 의미의 상태·버튼·필터가 화면마다 별도 CSS로 복제되지 않는다.
- 등급 4단이 색과 라벨을 함께 쓰고, 상태 의미색에 blue 계열이 없다.
- keyboard focus, disabled reason, 긴 한글이 primitive 테스트에 고정된다.
- 결정 액션이 두 폭 모두에서 스크롤 위치와 무관하게 첫 화면에 보인다.

### 단계 C — 발주계획

대상 시안: `Main`, `OrderPlanDetail`.

먼저 정리할 것: `order-plans.spec.ts:287`(좁은 폭 pane 전환)은 390px를 전제하므로 ADR-0046의
지원 폭 밖이다. 지원 폭 기준으로 다시 쓰거나 없앤다. 단계 A의 viewport 축소(mobile·tablet
project 제거) 뒤 laptop·desktop 두 폭에서 실패로 남아 있다.

작업:

1. 시안과 같은 상단 요약(`누적 데이터 · C-2 relevance 정책 · 회차 선택기 없음`), 실행 상태 배지,
   `실행 상세` 진입점을 배치한다.
2. 저장된 뷰는 segmented control, 모델 판단·BM25·사람 판단 보정은 selector, 검색은 text input으로
   구성하고 `현재 조합 저장`·`필터 초기화`를 둔다. 조합 필터의 AND/OR 의미와 URL 동기화는 현재
   계약을 유지한다.
3. 목록 머리글에 현재 조합의 의미와 건수를, 바닥에 기본 보기가 숨기는 것을 쓴다.
4. 목록은 밀집 행으로, 상세는 오른쪽 pane으로 둔다. 신호 세부와 운영 텔레메트리는 상세의
   `신호 세부`·`실행 기록` 탭으로 옮긴다.
5. **추적 결정을 상세 pane 바닥의 결정 액션으로 만든다**: `추적 시작`·`보류`·`추적 종료`·
   `이번 건 넘기기`. 선택 즉시 append-only 이력을 남기고 다음 건으로 이동하며 별도 저장 버튼을
   두지 않는다. 미선택이 추적 종료가 아니라는 문구와 사유 selector·담당자 감사 표식을 둔다.
6. **사람 판단 수정을 접힌 별도 영역으로 분리한다.** 열었을 때만 relevance·우선순위·메모를 새
   revision으로 기록하고, 추적 결정과 저장 경로를 공유하지 않는다.
7. 상세 화면(`/order-plans/:pk`)은 헤더 sticky 액션 + 본문 + 우측 이력·연결 rail 골격으로 맞추고
   revision 단위 수정 이력을 보여준다.
8. `filtered_out`·`not_relevant`·`unknown`·`null`·`failed`·`rejected`를 시안의 문구와 구조로
   구분한다.

완료 게이트:

- 시안 fixture에서 페이지 이동 없이 선택·결정·이동이 가능하다.
- 추적 결정과 사람 판단 수정이 서로 다른 요청·다른 revision으로 저장된다.
- 추적 결정이 모델 판단·적합성 등급·참여 준비 상태를 바꾸지 않는다(테스트로 고정).
- 상태 값이 빈칸·0·false로 보정되지 않는다.
- 기존 order-plans 기능 계약과 시안 기준 캡처가 모두 통과한다.

### 단계 D — 사전규격

대상 시안: `PreSpecs`, `PreSpecDetail`.

작업:

1. 왼쪽 목록 pane과 오른쪽 선택 상세 pane을 같은 화면에 둔다. 목록 아래에 별도 패널을 덧붙이는
   구조는 제거한다.
2. 개요 검토 상태 10값과 미시작(`null`) 그룹을 모두 표시하고 0건 그룹도 숨기지 않는다.
   `사람 검토 필요`·`실패`만 기본 펼침으로 한다.
3. 상세 pane에서 `심층 검토 실행`을 승인한다. 승계된 추적 상태는 배지로 밝히고 다시 묻지 않는다.
4. 신규 사전규격에만 `추적 시작하고 심층 검토`를 제공하고, 이력에는 추적 시작과 심층 검토 실행을
   별도 항목으로 남긴다.
5. `추적 종료`·`보류` 조작을 이 화면에 두지 않는다. 사업 추적으로 보낸다.
6. 상세는 개요 검토 5단계 진행, 요구사항 항목과 근거 위치, 근거 없음 강조, 첨부의 배포 가능·불가
   구분, 우측 이력·연결 rail을 시안 순서로 배치한다.
7. 그룹 header, 건수, deadline, 상태 badge, 문서 요약 순서를 유지한다.

완료 게이트:

- `PreSpecs` 아트보드와 동일한 split 구조가 된다.
- 그룹 수·상태 어휘·0건 표시·부분 페이지 경고가 유지된다.
- 심층 검토 실행 승인과 최종 Go/No-Go가 하나의 control로 합쳐지지 않는다.
- 승계된 건에서 추적 상태를 다시 묻지 않는다(테스트로 고정).

### 단계 E — 정보구조와 사업 추적

대상 시안: `Navigation`, `Dashboard`, `Opportunities`, `Queue`, `GoNoGo`, `Criteria`, `RunStatus`.

이 단계가 ADR-0045를 이행한다. 순서를 지킨다: 먼저 사업 추적을 만들고 예외 작업 경로를 옮긴 뒤,
마지막에 공고 판정 이력을 읽기 전용으로 바꾼다.

작업:

1. 사이드바를 `오늘의 업무` / `탐색과 추적` / `기준과 운영` 세 묶음 7항목으로 재배치한다.
   `검토 대기열` 항목을 없애고 `사업기회`를 `사업 추적`으로 바꾼다.
2. `route-meta.ts`를 새 구조에 맞춘다. `runSelectorVisible`은 대시보드와 공고 판정 이력에만
   `true`다. `queue`의 `editScope`는 3-2가 끝날 때까지 `리뷰 저장 가능`으로 둔다.
3. 사업 추적 화면을 만든다.
   - 3-1. 구역 segmented(`조치 필요`·`추적 중`·`보류`·`추적 종료`), 한 사업기회 한 행, 다음 행동
     배지, 정렬·검색.
   - 3-2. 상세 탭 `연결 레코드`·`추적 이력`·`시스템 신호`. 예외 작업(근거 없음·검증 실패·연결
     불확실) 처리 경로를 여기로 옮긴다. 시스템 신호는 집계나 추적 결정을 자동으로 만들지 않는다.
   - 3-3. 추적 상태 변경은 접힌 영역이며 보류·추적 종료에 필수 사유와 담당자 감사 표식을 새
     revision으로 기록한다.
4. 공고 판정 이력을 사업 추적 상세에서 여는 화면으로 옮기고 회차 선택기를 유지한다. **3-2가
   동작한 뒤에만** 읽기 전용으로 전환한다. 옛 경로 `/queue`·`/judgments`·`/reviews`·`/deadlines`는
   404를 내지 않고 각 뷰의 정식 주소로 남긴다.
5. 최종 Go/No-Go를 최상위에 두고 시안처럼 결정 대기 사업기회 목록을 먼저 보여준다. 목록 행에
   `변경 비교 결과 없음`도 값으로 표시한다.
6. 판정 기준 4탭과 실행 상태 4탭을 시안 순서·밀도로 통합한다. 판정 기준에 "이 화면이 정하지 않는
   것"과 정책 차단 사유를, 실행 상태에 운영 텔레메트리와 상시 운영 차단 사유를 남긴다.
7. 대시보드의 `지금 결정할 일` 스트립을 네 결정으로 맞추고(발주계획·추적 결정, 사전규격·심층 검토
   승인, 예외 조치·연결·실패, 최종 입찰 Go/No-Go) 각 화면으로 이동하게 한다. 회차 데이터가 읽기
   전용임을 밝히고 계산 불가를 0으로 바꾸지 않는다.

완료 게이트:

- 사이드바 항목 수·그룹·활성 상태가 `Navigation` 기준 이미지와 일치한다.
- 회차 선택기의 표시 여부가 `route-meta.ts`와 일치하고, 대시보드와 공고 판정 이력에만 보인다.
- 현재 `routes.tsx`에 등록된 경로(index 포함 26개)가 모두 404를 내지 않는다.
- 한 사업기회가 사업 추적 목록에 한 행으로만 나타난다.
- 리뷰 저장 경로가 사라진 시점이 없다. 읽기 전용 전환 커밋 이전에 예외 작업 경로가 통과한다.
- 네 결정 화면으로 대시보드에서 한 번의 명시적 이동이 가능하다.

### 단계 F — 상세 3종과 심층 검토

대상 시안: `DetailSkeleton`, `OrderPlanDetail`, `PreSpecDetail`, `BidDelta`, `DeepReview`.

작업:

1. 세 상세 화면(발주계획 상세·사전규격 상세·입찰 변경 비교)을 공통으로 요약 header → 헤더 고정
   상태·결정 action → 본문 반복 목록 → 우측 이력·연결 rail 순서로 맞춘다. rail에는 결정 액션을
   두지 않는다.
2. 입찰 변경 비교의 헤더에는 `결정 저장`·`결정 입력으로 이동`·`비교 재계산`만 두고, 최종
   Go/No-Go 입력 form은 본문에 둔다. form 바로 위에 저장 조건 3개를 쓴다.
3. delta는 범주별 반복 목록으로 두고 중요 변경·비중요 변경·`확인 필요 · 중요도 미확인`과
   `검증됨`·`근거 없음`을 구분한다. 비교 기준(기준 사전규격·대상 입찰공고·문서 묶음 상태·계산
   시각)을 남긴다.
4. 발주계획 추적 결정, 사전규격 심층 검토 실행 승인, 최종 Go/No-Go를 각각의 별도 action으로
   보존한다. 보류는 최종 결정 값이 아니며 기록을 만들지 않는다.
5. 심층 검토 보고서는 상단 카드 4개, 결정 카드 요약 표, Validation 실패 블록(`원문에서 확인`·
   `새 attempt로 재시도`), 우측 보고서 범위·수정본 저장·이력으로 배치한다. 수정본은 새 immutable
   revision이며 담당자 claimed name을 필수로 받는다.

완료 게이트:

- 세 상세 화면에서 첫 viewport에 상태와 결정 action이 보인다.
- 긴 본문을 스크롤해도 header action과 우측 이력의 의미가 변하지 않는다.
- 되돌릴 수 없는 입력 form이 헤더에 올라가 있지 않다.
- bid-delta, deep-review, document-preparation 기능 계약과 시안 기준 캡처가 모두 통과한다.

## 5. 시안 충실도 검증

### 5.1 별도 Playwright 디자인 스위트

`web/frontend/tests/design.spec.ts`를 추가한다.

- manifest의 route·fixture·viewport를 순회한다.
- 외부 font·외부 API 요청은 차단하고 로컬 Pretendard 로딩을 확인한다.
- full-page가 아닌 아트보드 기준 캡처 범위를 사용해 시안과 같은 크기로 비교한다.
- 허용 pixel diff를 초과하면 실패한다.
- 일반 visual test의 baseline update 명령으로 디자인 기준 이미지를 덮어쓰지 않는다.

### 5.2 구조적 보조 검사

픽셀 비교만으로 놓치지 않도록 다음을 함께 검사한다.

- AppShell의 `bidops` scope 존재와, `neutral` scope가 남지 않았는지
- 셸·목록·상세의 computed 색이 `PRD.md` §4.1 토큰 값과 일치하는지
- 등급 4단이 색만이 아니라 텍스트 라벨을 함께 쓰는지
- sidebar·topbar·list/detail pane의 computed 치수와, 두 pane이 각자 스크롤을 가두는지
- `unknown`, `null`, `계산 불가`, 실패, 부분 성공의 텍스트 존재
- 결정 action의 accessible name과 고정 위치(분할 화면은 pane 바닥, 단독 상세는 헤더)
- 추적 결정과 사람 판단 수정이 다른 요청으로 저장되는지
- 회차 선택기 표시 여부가 `route-meta.ts`와 일치하는지
- 1280·1440·1920px에서 horizontal overflow 없음
- 외부 font·외부 모델·DB·filesystem 직접 접근 없음

### 5.3 검증 viewport

`playwright.config.ts`의 project를 두 폭으로 고정한다(ADR-0046).

| project | 크기 | 용도 |
|---|---|---|
| `laptop` | 1280×800 | 최소 지원 폭. 구조 검사와 자체 스냅샷 |
| `desktop` | 1440×900 | 시안 기준 폭. 시안 픽셀 비교 |

1920px는 overflow 검사만 별도로 수행한다. `mobile`(390)과 `tablet`(768) project는 없앤다.
기존 테스트의 `viewport.width <= 900` 계열 skip 조건과 분기는 해당 화면을 이행할 때 함께
제거한다. 한 번에 지우지 않는다.

### 5.4 실행 명령

변경 화면마다 다음을 실행하고 결과를 기록한다. **§0-3을 마치기 전에는 재생성 블록을 실행하지
않는다.**

```bash
# 팔레트 테마 빌드 (단계 A-0. 토큰을 고쳤을 때만 다시 돌린다)
cd web/frontend
npx @astryxdesign/cli theme build src/themes/bidops/bidopsTheme.ts \
  --out src/themes/bidops/bidops.css
npm run test:contrast   # scripts/check-contrast.test.mjs

# 재생성 (§0-3 이후에만; v2 렌더는 §0-4 통과 이후에만)
cd ../../docs/design/mockups
python3 -m py_compile build.py screens.py screens_more.py preview.py
python3 screens.py
python3 screens_more.py
python3 preview.py
node shoot.mjs

# 구현 검증
cd ../../../web/frontend
npm run build
npm run test:design
npm run test:visual
```

화면 외 변경이 없더라도 기준 이미지 갱신 사유와 skip·실패를 사실대로 기록한다. 기준 이미지를
갱신했다는 사실만으로 시안 충실도 통과로 간주하지 않는다. 기준 이미지에는 팔레트 버전
(`v1-무채색`·`v2-무드보드`)을 함께 기록하고, 두 버전을 한 비교에 섞지 않는다.

## 6. 작업 단위와 되돌리기

- 단계 0은 단독 커밋으로 남긴다. 보존과 생성기 복원을 구현 커밋과 섞지 않는다.
- 팔레트 테마 도입(§0-5, 단계 A-0)은 화면 구현과 섞지 않고 단독 커밋으로 남긴다. 테마 정의,
  빌드 산출물, 대비 검사, scope 속성 치환이 한 단위다.
- v2 기준 이미지는 v1을 덮어쓰지 않고 별도 변경으로 추가한다. 팔레트 때문에 생긴 diff와 화면
  구조 때문에 생긴 diff를 한 커밋에 섞지 않는다.
- 단계 A·B는 공통 기반 커밋으로 남기고, 단계 C~F는 화면 묶음별 커밋으로 남긴다.
- 단계 E는 3-2(예외 작업 경로) 커밋과 4(읽기 전용 전환) 커밋을 분리한다. 순서를 바꾸지 않는다.
- 코드, fixture, 기준 이미지, manifest 변경은 같은 검토 단위로 묶는다.
- 시안 한 장의 변경이 다른 화면에 영향을 주면 영향 아트보드와 기준 이미지를 함께 재검증한다.
- 기능 회귀가 생기면 해당 화면 커밋만 되돌린다. API·DB·업무 상태를 시각 수정 때문에 되돌리지
  않는다.
- 기준 이미지 변경은 제품 담당자의 명시적 승인 없이는 병합하지 않는다.

## 7. 완료 정의

전체 작업은 다음을 모두 만족할 때만 완료로 기록한다.

1. 시안 생성기가 `_shots`의 14장을 다시 만들어 낸다(§0-4).
2. manifest의 14개 아트보드가 각각 route·fixture·기준 이미지와 연결된다.
3. 공통 셸과 14개 화면의 디자인 스위트가 두 폭에서 허용 diff 안에 통과한다.
3-1. 화면의 computed 색이 `PRD.md` §4.1의 토큰 값과 일치하고 대비 검사가 통과한다. `:root`·화면
   CSS의 `--color-*` 재정의가 없다.
4. production build, 기존 기능 테스트, 접근성 검사가 통과한다.
5. 업무 상태 분리, `unknown`/`null` 보존, 리뷰 저장 경로 보존, API·DB·파일 경계가 변하지 않는다.
   실패·미측정 상태가 팔레트 톤에 맞추느라 정상처럼 보이지 않는다.
6. 실행 명령·통과 범위·실패·skip 사유가 tracking 문서에 남아 있다.

## 8. 범위 밖

- 모바일·태블릿 레이아웃과 터치 전용 조작
- 로그인·역할 기반 권한·알림
- 다크 모드(`bidops` 테마의 dark 값은 정의하되 화면에서 활성화하지 않는다)
- 무드보드 밖의 새 브랜드 색 도입과 의미색 재정의
- 새로운 수집기·모델·DB 계약·업무 판정 규칙
- 시안에 없는 신규 화면
- Astryx 버전 업그레이드
- 시안 가상 데이터를 운영 데이터나 회사 역량 사실로 승격하는 작업
