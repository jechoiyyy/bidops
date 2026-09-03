# BidOps 화면 시안 기준 구현 계획

| 항목 | 내용 |
|---|---|
| 문서 상태 | 시안 기준 재정의 — 구현·검증 전 |
| 기준일 | 2026-09-03 |
| 시각 정본 | docs/design/mockups/_preview 및 대응 PNG |
| 시안 생성기 | docs/design/mockups/screens.py, screens_more.py, preview.py |
| 업무·상태 정본 | docs/PRD.md, docs/business-rules.md, docs/contracts.md |
| 관련 결정 | ADR-0039, ADR-0040, ADR-0041 |

이 계획은 기존 화면이 기능 요구를 얼마나 구현했는지가 아니라, 승인된 시안을 실제 React 화면으로
재현하고 그 결과를 자동으로 검증하는 방법을 고정한다. 기존 구현의 API·업무 상태·감사 규칙은
보존하며, 시안에 없는 업무 판정이나 서버 계약을 새로 만들지 않는다.

## 1. 이번 작업의 목표

최종 목표는 다음 네 가지를 동시에 만족하는 것이다.

1. 14개 시안 아트보드의 셸, 정보 밀도, 컴포넌트 조합, 색·간격·반응형 동작을 운영 화면에서
   재현한다.
2. 적합성 등급, 참여 준비 상태, 추적 승인, 최종 Go/No-Go를 계속 별도 상태와 조작으로 둔다.
3. 시안용 가상 데이터와 운영 API 데이터를 섞지 않는다. 운영 화면은 API만 사용하고, 시각 검증은
   Playwright 고정 fixture만 사용한다.
4. 구현 화면이 시안에서 벗어나면 기존 스냅샷을 덮어써서 통과시키지 않고 검증을 실패시킨다.

현재 _preview의 neutral 무채색 팔레트를 이 계획의 v1 시각 기준으로 고정한다. RootLab 녹색
팔레트로 바꾸려면 먼저 시안을 다시 생성하고 새 기준 버전과 승인 기록을 남긴다.

## 2. 현재 미적용 원인과 교정 원칙

다음 문제를 해결하지 않으면 기능을 추가해도 시안과 구현은 다시 갈라진다.

| 문제 | 교정 원칙 |
|---|---|
| _preview와 _shots가 Git에서 제외되어 기준 이미지가 자동 검증에 쓰이지 않음 | 승인된 기준 PNG를 별도 경로에 버전 관리하고 생성 입력의 hash를 기록 |
| visual test가 구현 후 저장한 자체 스냅샷만 비교함 | 시안 기준 스냅샷과 구현 스냅샷을 고정 fixture·고정 viewport에서 비교 |
| 시안은 전체 셸을 neutral scope 안에서 렌더하지만 AppShell은 페이지 내부만 scope를 가짐 | AppShell 최상위에 neutral scope를 두고 셸부터 같은 테마를 읽게 함 |
| 공통 셸 CSS가 legacy RootLab 토큰을 읽어 시안의 색·폭과 달라짐 | 셸 골격을 Astryx neutral 토큰으로 통일하고 248px 사이드바·76px 상단바를 고정 |
| 시안은 정적 HTML에서 추출한 class 문자열이고 운영 화면은 실제 React 컴포넌트임 | 원자 class 문자열을 복사하지 않고 Astryx 컴포넌트의 실제 props·마크업으로 재구성 |
| 기능 완료와 시각 완료를 같은 것으로 취급함 | 기능 계약 테스트와 시안 충실도 테스트를 별도 게이트로 운영 |

## 3. 시안 기준 산출물

### 3.1 기준 manifest

다음 정보를 담은 디자인 manifest를 추가한다.

- artboard 이름과 시안 파일
- 운영 route와 필요한 query
- viewport width·height 및 캡처 범위
- 고정 API fixture 이름
- 기준 PNG 경로와 생성 시점
- Astryx core·neutral theme·Pretendard 입력 hash

manifest가 없는 아트보드나 route는 구현 완료 대상으로 표시하지 않는다.

### 3.2 기준 이미지

- 시안 생성 명령을 실행해 14개 HTML과 PNG를 재생성한다.
- 승인된 PNG는 web/frontend/tests/design-snapshots 아래에 복사해 Git으로 관리한다.
- docs/design/mockups/_preview와 _shots는 재생성 작업 디렉터리로만 사용한다.
- 기준 이미지를 갱신할 때는 기존 파일을 먼저 덮지 말고, 변경 사유·영향 화면·승인자를 기록한
  별도 변경으로 남긴다.

### 3.3 고정 fixture

시안에 보이는 제목·상태·건수·날짜·실패·unknown·null을 별도의 시각 fixture로 고정한다.
fixture는 운영 데이터나 회사 역량 사실로 취급하지 않으며, production API와 구분되는
Playwright route mock으로만 제공한다. 시안 값이 바뀌었다고 운영 데이터를 수정하지 않는다.

## 4. 구현 순서

각 단계는 코드와 시안 기준 테스트를 함께 추가하고, 해당 화면의 기준 이미지가 통과한 뒤에만
다음 단계로 진행한다.

### 단계 A — 테마 범위와 공통 셸

수정 대상:

- web/frontend/src/components/shell/AppShell.tsx
- web/frontend/src/components/shell/Sidebar.tsx
- web/frontend/src/components/shell/TopBar.tsx
- web/frontend/src/styles/shell-relaxed.css 및 공통 theme import 순서

작업:

1. AppShell 최상위가 data-astryx-theme="neutral"과 light 모드를 소유하게 한다. 페이지 안에만
   있던 중복 scope는 필요한 경우 유지하되 셸보다 좁아지지 않게 한다.
2. 사이드바, 상단바, 본문 canvas가 시안과 같은 neutral token을 읽도록 legacy 토큰 의존을
   제거하거나 명시적인 token bridge로 한 곳에서 관리한다.
3. 사이드바 248px, 상단바 76px, 본문 여백, overflow·responsive breakpoint를 시안과 고정한다.
4. Pretendard 자체 호스팅과 외부 font 차단을 유지한다.
5. 공통 셸만 캡처한 smoke fixture를 추가해 테마 scope와 치수를 검사한다.

완료 게이트:

- 모든 시안 대상 route에서 셸의 computed theme scope가 neutral이다.
- 1440px 기준 사이드바·상단바 치수가 기준 이미지와 일치한다.
- legacy 녹색 셸이 시안 기준 route에 남지 않는다.
- TypeScript strict와 production build가 통과한다.

### 단계 B — 공통 화면 primitive

시안에 반복되는 다음 구조를 실제 컴포넌트 조합으로 고정한다.

- 밀집 목록 행과 선택 상태
- 목록·상세 split workspace와 mobile 전환
- 필터 bar, SegmentedControl, Selector, TextInput
- 상태 Badge·StatusDot·unknown/null 표시
- sticky detail header와 고정 결정 action
- 본문 반복 목록과 우측 history/link rail
- 접이식 상태 그룹과 빈 상태·부분 성공·실패 상태

Astryx 컴포넌트는 props로 표현하고, 레이아웃만 프로젝트 소유 CSS로 둔다. 화면 한 곳에서
Tailwind utility와 Astryx styling을 섞지 않는다. 시안의 추출된 atomic class 문자열을 직접
React 코드에 붙이지 않는다.

완료 게이트:

- 같은 의미의 상태·버튼·필터가 화면마다 별도 CSS로 복제되지 않는다.
- keyboard focus, disabled reason, 긴 한글, 좁은 viewport가 primitive 테스트에 고정된다.

### 단계 C — 1단계 C-2 발주계획

대상 시안: Main.

작업:

1. 시안과 같은 상단 실행 요약, 필터 순서와 밀도로 배치한다. 실행 설명은 기본 한 줄이며,
   문제 상세는 접었다 펼칠 수 있게 한다.
2. 저장된 뷰는 segmented control, 모델·BM25·사람 피드백은 selector, 검색은 text input으로
   구성한다. 조합 필터의 AND/OR 의미와 URL 동기화는 현재 계약을 유지한다.
3. 목록은 밀집 행으로, 상세는 오른쪽 pane으로 둔다. 제목·기관·예산·계획 시기와 상태 badge의
   노출 순서를 시안과 맞춘다.
4. 상세 pane의 탭은 판정·신호 세부·실행 기록으로 유지하고, 사람 feedback과 저장 후 다음
   action을 시안 위치에 둔다.
5. filtered_out·not_relevant·unknown·null·failed·rejected를 시안의 문구와 구조로 구분한다.

완료 게이트:

- 시안 fixture에서 페이지 이동 없이 선택·입력·저장·다음 이동이 가능하다.
- 목록·상세·필터·footer action의 위치가 기준 이미지와 일치한다.
- 상태 값이 빈칸·0·false로 보정되지 않는다.
- 기존 order-plans 기능 계약과 시안 기준 캡처가 모두 통과한다.

### 단계 D — 3단계 사전규격

대상 시안: PreSpecs.

작업:

1. 왼쪽 목록 pane과 오른쪽 선택 상세 pane을 같은 화면에 둔다.
2. 개요 검토 상태 10값과 미시작(null) 그룹을 모두 표시하고, 사람 검토 필요·실패만 기본
   펼침으로 한다.
3. 행에서 항목을 선택하면 오른쪽 상세가 바뀌며, 심층 추적 승인 action도 상세 pane 안에서
   수행한다. 목록 아래에 별도 패널을 덧붙이는 구조는 제거한다.
4. 시안의 그룹 header, 건수, deadline, 상태 badge, 문서 요약 순서를 유지한다.

완료 게이트:

- 14개 시안 중 PreSpecs 아트보드와 동일한 split 구조가 된다.
- 그룹 수·상태 어휘·0건 표시·부분 페이지 경고가 유지된다.
- 추적 승인과 최종 Go/No-Go가 하나의 control로 합쳐지지 않는다.

### 단계 E — 정보구조와 대시보드

대상 시안: Navigation, Dashboard, Queue, Opportunities, GoNoGo, Criteria, RunStatus.

작업:

1. 사이드바를 회차 검토 / 누적 추적 / 기준과 운영 그룹으로 재배치하고, 모든 항목을 실제
   route와 연결한다.
2. 최종 Go/No-Go를 최상위에 두고, 시안처럼 결정 대기 사업기회 목록을 먼저 보여준다.
3. 판정 기준 4개와 실행 상태·감사 탭을 시안 순서와 밀도로 통합한다.
4. 대시보드의 지금 처리할 일 strip에 네 결정의 이동 경로와 null·확인 불가 상태를 표시한다.
5. Queue의 목록·상세·필터와 Opportunities의 추적 상태 표현을 시안과 통일한다.

완료 게이트:

- 사이드바 항목 수·그룹·활성 상태가 Navigation 기준 이미지와 일치한다.
- 회차 선택기의 표시 여부가 route metadata와 일치한다.
- 기존 경로·query·북마크가 깨지지 않는다.
- 네 결정 화면으로 한 번의 명시적 이동이 가능하다.

### 단계 F — 상세 3종과 심층 검토

대상 시안: OrderPlanDetail, PreSpecDetail, BidDelta, DeepReview, DetailSkeleton.

작업:

1. 세 상세 화면을 공통으로 요약 header → 상태·결정 action → 본문 반복 목록 → 우측 이력/link
   rail 순서로 맞춘다.
2. 결정 action은 header에 sticky로 두되, 최종 Go/No-Go 입력 form 전체를 header에 올려 본문을
   가리지 않는다.
3. 발주계획 feedback, 사전규격 추적 승인, 최종 Go/No-Go를 각각의 별도 action으로 보존한다.
4. 심층 검토 보고서의 입력 범위·실패·재시작·근거 연결을 시안의 정보 계층에 맞춘다.

완료 게이트:

- 세 상세 화면에서 첫 viewport에 상태와 결정 action이 보인다.
- 긴 본문을 스크롤해도 header action과 우측 이력의 의미가 변하지 않는다.
- bid-delta, deep-review, document-preparation 기능 계약과 시안 기준 캡처가 모두 통과한다.

## 5. 시안 충실도 검증

### 5.1 별도 Playwright 디자인 스위트

web/frontend/tests/design.spec.ts를 추가한다.

- manifest의 route·fixture·viewport를 순회한다.
- 외부 font·외부 API 요청은 차단하고 로컬 Pretendard 로딩을 확인한다.
- full-page가 아닌 아트보드 기준 캡처 범위를 사용해 시안과 같은 크기로 비교한다.
- 허용 pixel diff를 초과하면 실패한다.
- 일반 visual test의 baseline update 명령으로 디자인 기준 이미지를 덮어쓰지 않는다.

### 5.2 구조적 보조 검사

픽셀 비교만으로 놓치지 않도록 다음을 함께 검사한다.

- AppShell의 neutral scope 존재
- sidebar·topbar·list/detail pane의 computed 치수
- unknown, null, 실패, 부분 성공의 텍스트 존재
- 결정 action의 accessible name과 sticky 상태
- horizontal overflow 없음, mobile에서 list/detail 전환
- 외부 font·외부 모델·DB·filesystem 직접 접근 없음

### 5.3 실행 명령

변경 화면마다 다음을 실행하고 결과를 기록한다.

```bash
cd docs/design/mockups
python3 -m py_compile build.py screens.py screens_more.py preview.py
python3 screens.py
python3 screens_more.py
python3 preview.py
node shoot.mjs

cd ../../../web/frontend
npm run build
npm run test:design
npm run test:visual
```

화면 외 변경이 없더라도 기준 이미지 갱신 사유와 skip·실패를 사실대로 기록한다. 기준 이미지를
갱신했다는 사실만으로 시안 충실도 통과로 간주하지 않는다.

## 6. 작업 단위와 되돌리기

- 단계 A·B는 공통 기반 커밋으로 남기고, 단계 C~F는 화면 묶음별 커밋으로 남긴다.
- 코드, fixture, 기준 이미지, manifest 변경은 같은 검토 단위로 묶는다.
- 시안 한 장의 변경이 다른 화면에 영향을 주면 영향 아트보드와 기준 이미지를 함께 재검증한다.
- 기능 회귀가 생기면 해당 화면 커밋만 되돌린다. API·DB·업무 상태를 시각 수정 때문에 되돌리지
  않는다.
- 기준 이미지 변경은 제품 담당자의 명시적 승인 없이는 병합하지 않는다.

## 7. 완료 정의

전체 작업은 다음을 모두 만족할 때만 완료로 기록한다.

1. manifest의 14개 아트보드가 각각 route·fixture·기준 이미지와 연결된다.
2. 공통 셸과 14개 화면의 디자인 스위트가 허용 diff 안에서 통과한다.
3. production build, 기존 기능 테스트, 접근성·반응형 검사가 통과한다.
4. 업무 상태 분리, unknown/null 보존, API·DB·파일 경계가 변하지 않는다.
5. 실행 명령·통과 범위·실패·skip 사유가 tracking 문서에 남아 있다.

## 8. 범위 밖

- 로그인·역할 기반 권한·알림
- 다크 모드
- 새로운 수집기·모델·DB 계약·업무 판정 규칙
- 시안에 없는 신규 화면
- Astryx 버전 업그레이드
- 시안 가상 데이터를 운영 데이터나 회사 역량 사실로 승격하는 작업
