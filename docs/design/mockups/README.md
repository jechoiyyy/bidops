# BidOps 화면 시안

`docs/design/PLAN.md`의 이행 대상을 구현 전에 검토하기 위한 14개 정적 아트보드다.
운영 화면이나 실행 진입점이 아니며, 실제 Astryx neutral CSS와 참고 화면에서 추출한
컴포넌트 class 문자열을 사용해 렌더한다. 레이아웃은 ADR-0040에 따라 프로젝트가 소유한다.

## 구성

- `build.py`: Astryx 컴포넌트 마크업과 공통 BidOps 셸 생성기
- `screens.py`: PLAN 1~4단계의 핵심 8개 아트보드
- `screens_more.py`: 상세·검토·사업기회 등 나머지 6개 아트보드
- `bo-skeleton.css`: 현행 화면에서 옮긴 프로젝트 소유 레이아웃 골격
- 설치된 Astryx core CSS, `web/frontend/src/themes/neutral/neutral.css`: 렌더 입력
- `astryx-classes.json`: 참고 화면에서 추출한 컴포넌트 class 문자열
- `canvas.json`: 14개 아트보드의 배치와 검토 주석

`.dc.html`, 단독 미리보기, 스크린샷, 배포용 단일 HTML은 모두 재생성 산출물이므로
Git에 넣지 않는다.

## 재생성과 확인

`web/frontend` 의존성이 설치된 저장소 루트에서 실행한다.

```bash
cd docs/design/mockups
python3 -m py_compile build.py screens.py screens_more.py preview.py
python3 screens.py
python3 screens_more.py
python3 preview.py
node shoot.mjs
```

결과는 `_preview/`와 `_shots/`에 생성된다. `canvas.json`의 모든 artboard에 대응하는
HTML과 PNG가 만들어졌는지 확인한다. 시안의 예시 값은 업무 규칙을 설명하기 위한 가상
데이터이며 운영 사실이나 확인된 회사 역량으로 취급하지 않는다.

Claude의 격리 worktree처럼 현재 checkout에 `node_modules`가 없고 다른 checkout의 설치를
공유해야 할 때만 해당 프론트엔드 경로를 명시한다.

```bash
BIDOPS_FRONTEND_ROOT=/path/to/bidops/web/frontend node shoot.mjs
```
