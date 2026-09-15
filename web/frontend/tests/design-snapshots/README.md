# 시안 기준 이미지 보존본

`docs/design/PLAN.md` §0-1의 보존 결과다. 여기 있는 파일이 **화면 이행의 시각 정본**이다.

## 왜 여기 있나

`docs/design/mockups/`의 `_shots/`·`_preview/`·`*.dc.html`은 `.gitignore` 대상이라 Git이
지키지 않는다. 그런데 그 산출물을 만든 생성기 버전이 저장소에 없다. 커밋된
`screens.py`·`screens_more.py`는 ADR-0046 이전 구조(`검토 대기열`)를 만들고, 산출물은
이후 구조(`사업 추적`·`오늘의 업무`·`추적 시작`)를 담고 있다.

즉 재생성 명령을 한 번 실행하면 정본이 옛 화면으로 덮여 **복구할 수 없이 사라진다.**
그래서 Git이 지키는 경로로 먼저 복사했다.

## 구성

| 경로 | 내용 | 용도 |
|---|---|---|
| `shots/` | PNG 14장, 1440px | 시안 픽셀 비교의 기준 이미지 |
| `preview/` | 단독 미리보기 HTML 14장 | 렌더 결과 확인 |
| `artboards/` | 캔버스 아트보드 HTML 14장 | 생성기 복원(§0-3)의 입력 |
| `MANIFEST.txt` | 세 묶음의 sha256과 원본 렌더 시각 | 드리프트 검출 |

원본 렌더 시각은 2026-09-02 17:46이고, 복사 직후 PNG 14장의 sha256이 원본과 일치함을
확인했다.

## 규칙

- 이 디렉터리의 파일을 재생성 산출물로 **덮어쓰지 않는다.** 재생성 결과가 여기와 다르면
  여기 있는 것이 이긴다(`PLAN.md` §0-4).
- 기준 이미지를 갱신할 때는 변경 사유·영향 화면·승인자를 기록한 별도 변경으로 남긴다.
  일반 visual test의 baseline update 명령이 이 경로를 건드리게 하지 않는다.
- `shots/`는 1440px 한 폭이다. 1280px 기준 이미지는 구현 화면에서 새로 만들고 시안과
  픽셀 비교하지 않는다(`PLAN.md` §3.2).

## 2026-09-15 재설계(C 기준) 시안은 다른 폴더에 있다

관리 화면 흰 바탕·초록 포인트 재설계(C 기준, 8화면)의 시각 정본은 이 디렉터리가
아니라 저장소 루트의 [`docs/0915_ui-redesign/mockups/`](../../../../docs/0915_ui-redesign/mockups/)
에 있다. 위 "왜 여기 있나" 절의 사정(옛 생성기로 덮이는 문제)과 무관한 별도
작업이라 이 디렉터리 안의 기존 파일(`shots/`·`preview/`·`artboards/`·
`MANIFEST.txt`)은 이번에 건드리지 않았다.

| 경로 | 내용 |
|---|---|
| `docs/0915_ui-redesign/mockups/shots/` | PNG 8장, 1440×900 |
| `docs/0915_ui-redesign/mockups/artboards/` | 캔버스 아트보드 HTML 8장(`*.dc.html`). 값은 앱 `zoom: 0.9` 기준 논리 px라 CSS 값과 1:1 |
| `docs/0915_ui-redesign/mockups/MANIFEST.txt` | 두 묶음의 sha256 |

시안과 [`docs/0915_ui-redesign/spec.md`](../../../../docs/0915_ui-redesign/spec.md)가
어긋나면 시안이 이기고, 시안이 [`docs/0915_ui-redesign/intent.md`](../../../../docs/0915_ui-redesign/intent.md)
§제약의 업무 규칙과 어긋나면 업무 규칙이 이긴다. 결정 기록은
`docs/0915_ui-redesign/decisions.md`·`notes.md`에 있다.
