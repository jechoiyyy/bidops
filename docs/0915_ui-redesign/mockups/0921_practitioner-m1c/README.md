# 2026-09-21 실무 화면 고도화 시안 M1c — 사업 추적·최종 Go/No-Go 분할 골격

- 게시본: https://claude.ai/artifact/GXiHyNiJ2kPZ6ebR5R1VtF (비공개, Version 1). `mockup.html`이 게시본의 원본이다.
- 승인: 2026-09-21 jechoi — **A안**(목록은 Astryx `Table` 유지, 글자 크기·행 간격만 공용 값에 맞춘다).
- 두 안 공통으로 승인된 것: 분할 틀을 공용 `SplitWorkspace`로(38% 비율 유지, 화면별 틀과 복제 CSS 삭제), 상세 머리를 `StickyDecisionHeader`로(스크롤해도 위에 붙음),
  발주기관 강조 블록을 공용 `AgencyFeature`로, `explore-workspace-consistency.spec`의 두 화면 빈칸 채우기.
- B안(발주계획과 같은 네 줄 행)은 채택하지 않았다 — 행마다 `다음 확인` 단추·`사람 결정` 열이 있어 열 구조가 뜻을 갖고, 뒤 작업(M5)에서 예산·마감 열이 늘어난다.
- 표시 데이터는 테스트 fixture 값이다. 명세는 `docs/0921_practitioner-screens/spec.md` §2.4다.
