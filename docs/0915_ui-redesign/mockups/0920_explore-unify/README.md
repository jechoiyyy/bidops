# 2026-09-20 탐색 화면 통일·일괄 추적 종료 시안

- 게시본: https://claude.ai/artifact/46DZkNcXT2nFmjZiWRkFCH (비공개, Version 2)
- 승인: 2026-09-20 jechoi — 권장안 전부. ⓐ 목록 폭 리사이저 제거 · ⓑ 전체 상세 식별 줄의 기관명 유지 ·
  ⓒ 발주계획 목록 글자 +2px · ⓓ 수집 회차 선택을 필터 아래 줄로 · 사전규격 상세 머리 A안.
- `mockup-template.html`은 게시본의 원본이다. `{{OP_PNG}}`·`{{PS_PNG}}` 자리에는 게시 시점의 픽셀 기준선
  (`web/frontend/tests/pixel-screens.spec.ts-snapshots/order-plans-list-pixel-linux.png`, `pre-specs-list-pixel-linux.png`)을
  base64로 넣었다. 표시 데이터는 테스트 fixture 값뿐이고 글꼴은 Pretendard 대신 Noto Sans KR로 대체 표시했다.
- 결정 정본은 ADR-0062(화면 통일)·ADR-0063(일괄 추적 종료)이다.
