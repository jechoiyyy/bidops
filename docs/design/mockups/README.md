# BidOps 화면 시안

`docs/design/PLAN.md`의 이행 대상을 구현 전에 검토하기 위한 14개 정적 아트보드다.
운영 화면이나 실행 진입점이 아니며, 실제 Astryx 테마 CSS와 참고 화면에서 추출한
컴포넌트 class 문자열을 사용해 렌더한다. 레이아웃은 ADR-0040에 따라 프로젝트가 소유한다.

색은 두 버전이 있다. 현재 `_shots/`의 14장은 stock `neutral`로 렌더한 **무채색 v1**이고,
운영 화면의 색 정본은 무드보드 [`../moodborad.jpg`](../moodborad.jpg)에서 파생한 `bidops`
테마다(ADR-0047, `../PRD.md` §4.1). **v2 팔레트 렌더는 아래 §0-4 대조를 통과한 뒤에만 만든다.**
v1은 생성기 복원의 대조 기준이므로 색을 먼저 바꾸면 대조가 항상 실패한다.

## 지금 상태 — 재생성 전에 반드시 읽는다

**`_shots/`의 PNG 14장이 시각 정본이고, 이 디렉터리의 생성기는 그보다 뒤처져 있다.**

산출물(`.dc.html`, `_preview/`, `_shots/`)은 ADR-0045의 구조(`오늘의 업무` / `탐색과 추적`,
`사업 추적`, 발주계획의 `추적 시작`)를 담고 있는데, 커밋된 `screens.py`·`screens_more.py`는
그 문자열을 하나도 갖고 있지 않고 옛 `검토 대기열` 구조를 만든다. 시안을 만든 생성기 버전이
저장소에 없다.

따라서 지금 재생성 명령을 실행하면 **시각 정본이 옛 화면으로 덮여 사라진다.**

`docs/design/PLAN.md` §0의 순서를 지킨다.

1. `_shots/`와 `_preview/`를 `web/frontend/tests/design-snapshots`로 먼저 복사해 보존한다.
2. 보존 전에는 아래 재생성 명령을 실행하지 않는다.
3. 보존본을 정본으로 삼아 생성기와 `canvas.json`을 다시 쓴다.
4. 재생성 결과가 보존본과 다르면 보존본이 이긴다.
5. 4를 통과한 뒤에만 렌더 입력 테마를 `bidops`로 바꿔 v2 기준 이미지를 만든다. v1은 덮어쓰지
   않는다.

## 구성

- `build.py`: Astryx 컴포넌트 마크업과 공통 BidOps 셸 생성기
- `screens.py`: 핵심 8개 아트보드
- `screens_more.py`: 상세·검토·사업 추적 등 나머지 6개 아트보드
- `bo-skeleton.css`: 현행 화면에서 옮긴 프로젝트 소유 레이아웃 골격
- 설치된 Astryx core CSS와 테마 CSS: 렌더 입력.
  v1은 `web/frontend/src/themes/neutral/neutral.css`, v2는 `web/frontend/src/themes/bidops/bidops.css`다.
  scope 속성(`data-astryx-theme`)도 함께 바꾼다
- `astryx-classes.json`: 참고 화면에서 추출한 컴포넌트 class 문자열
- `canvas.json`: 14개 아트보드의 배치와 검토 주석 (현재 구조 기준으로 갱신됨)

`.dc.html`, 단독 미리보기, 스크린샷, 배포용 단일 HTML은 모두 재생성 산출물이므로
Git에 넣지 않는다. 승인된 기준 이미지는 `web/frontend/tests/design-snapshots`에서 관리한다.

## 아트보드와 화면

| 아트보드 | 화면 | 결정 |
|---|---|---|
| `Main` | 발주계획 목록·추적 결정 | 결정 1 |
| `OrderPlanDetail` | 발주계획 상세 | 결정 1 |
| `PreSpecs` | 사전규격 목록 | 결정 2 |
| `PreSpecDetail` | 사전규격 상세 | 결정 2 |
| `DeepReview` | 심층 검토 보고서 | — |
| `Opportunities` | 사업 추적 | 결정 3 |
| `Queue` | 공고 판정 이력 (읽기 전용) | 결정 3 |
| `GoNoGo` | 최종 Go/No-Go 대기 목록 | 결정 4 |
| `BidDelta` | 입찰 변경 비교·결정 | 결정 4 |
| `Dashboard` | 대시보드 | 네 결정 진입점 |
| `Navigation` | 사이드바 16→7 | — |
| `Criteria` | 판정 기준 4탭 | — |
| `RunStatus` | 실행 상태 4탭 | — |
| `DetailSkeleton` | 상세 3종 공통 골격 | — |

## 재생성과 확인

**위 §"지금 상태"의 보존을 마친 뒤에만** `web/frontend` 의존성이 설치된 저장소 루트에서
실행한다.

```bash
cd docs/design/mockups
python3 -m py_compile build.py screens.py screens_more.py preview.py
python3 screens.py
python3 screens_more.py
python3 preview.py
node shoot.mjs
```

결과는 `_preview/`와 `_shots/`에 생성된다. `canvas.json`의 모든 artboard에 대응하는
HTML과 PNG가 만들어졌는지, 그리고 보존한 기준 이미지와 일치하는지 확인한다. 대조할 때는
같은 팔레트 버전끼리 비교한다. v1과 v2를 한 비교에 섞지 않는다. 시안의 예시
값은 업무 규칙을 설명하기 위한 가상 데이터이며 운영 사실이나 확인된 회사 역량으로 취급하지
않는다.

시안은 1440px 한 폭으로 렌더한다. 지원 폭은 1280~1920px이며 모바일·태블릿 아트보드는
만들지 않는다(ADR-0046).

Claude의 격리 worktree처럼 현재 checkout에 `node_modules`가 없고 다른 checkout의 설치를
공유해야 할 때만 해당 프론트엔드 경로를 명시한다.

```bash
BIDOPS_FRONTEND_ROOT=/path/to/bidops/web/frontend node shoot.mjs
```
