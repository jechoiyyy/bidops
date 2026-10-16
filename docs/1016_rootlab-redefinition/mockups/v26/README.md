# 목업 v26 (2026-10-16)

캔버스 원본: https://claude.ai/artifact/HgezMMFTSMwYQPikVB8tpj (버전 26). 이 디렉터리는 같은 시점의 아트보드 HTML 사본이다.

| 파일 | 화면 |
|---|---|
| `Main.dc.html` | 오늘의 브리핑 (리스트 뷰 + 피크 패널) |
| `Slack.dc.html` | Slack 브리핑 메시지 |
| `Timeline.dc.html` | 사업기회 레코드 — 활동 탭 |
| `Verdict.dc.html` | 사업기회 레코드 — 판정 탭 |
| `Proposal.dc.html` | 사업기회 레코드 — 제안서 탭 |
| `Company.dc.html` | 회사 근거 |
| `canvas.json` | 캔버스 배치 메모 |

브라우저에서 바로 열린다. `<x-dc>`·`<helmet>`은 캔버스 런타임 태그라 일반 브라우저에서는 무시되고, `./support.js`는 없어도 정적 렌더에는 영향이 없다. 색은 시안용 hex이며 제품에서는 [`../../ui-spec.md`](../../ui-spec.md) §2의 토큰으로 바꾼다.
