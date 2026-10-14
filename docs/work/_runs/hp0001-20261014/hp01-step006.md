# HP01 STEP006 — 프런트 타입·라벨

- 구현: `TaxonomyLabel`에 `operations_maintenance`, `SegmentMappingStatus`에 `inherited`, `RequirementInventorySummary`에 필수 `card_item_count`·`label_value_table_count`를 추가했다. 패널은 `운영·유지관리`와 inherited의 `앞 문단 쪽 상속`을 표시한다.
- Mock: `api-mock.ts`를 extractor v2·`bidops.segment-taxonomy.v2` identity 및 새 summary 키에 맞췄다. 기존 mapped·partial·unavailable 사례는 보존했고, 구조 원문 쪽 7과 물리 PDF 쪽 8인 inherited 사례를 추가했다.
- 화면 검사: 기존 deep-review 의미 검사를 새 label·annotation·PDF 링크·원문 page locator·unavailable 보존까지 확장했다. overflow 검사는 `.deep-review-segment-panel`과 목록을 1280·1440px 지원 폭에서 확인한다.
- Astryx 탐색: `npx @astryxdesign/cli build "Update the existing dense requirement segment inventory panel to show the operations and maintenance taxonomy label, inherited PDF page mapping annotation, inventory summary counts, and preserve unavailable page state"` 실행. 가장 가까운 page template만 제안되어 기존 패널의 사전·조건문만 갱신했다.
- 변경 파일: `web/frontend/src/components/deep-review/types.ts`, `SegmentInventoryPanel.tsx`, `tests/api-mock.ts`, `tests/deep-review.spec.ts`, `tests/screen-semantics.spec.ts`, `tests/overflow.spec.ts`.
- 확인: `git diff --check` 통과. 지시대로 frontend build와 Playwright는 실행하지 않았다. 백엔드 검사는 root가 실행했으며 아래 프런트 검사를 root가 한 번 실행한다.

## Root 실행

`web/frontend`에서 root의 IPv4 preview가 4173이 아니면 `PW_PORT`에 해당 포트를 넣는다. Playwright 설정은 `127.0.0.1`을 사용하고 기존 preview를 재사용한다.

```sh
cd web/frontend
npm run build
PW_PORT=4173 PW_OUT_DIR=dist npx playwright test tests/deep-review.spec.ts tests/screen-semantics.spec.ts --project=app --grep '사람 확인 segment는 대응된 PDF 페이지만 링크하고 미확인은 미확인으로 남긴다|심층 보고서 우측 열이 문서 inventory와 사람 확인 필요 segment를 보여준다'
PW_PORT=4173 PW_OUT_DIR=dist npx playwright test tests/overflow.spec.ts --project=layout-laptop --project=layout-desktop --grep 'deep-review-segment-panel 목록이 지원 폭에서 패널 밖으로 넘치지 않는다'
```

핵심 selector는 `.deep-review-segment-list > li[data-segment-ordinal="5"]`, `a[aria-label="5번째 구간 · PDF 8페이지 열기"]`, `.deep-review-segment-list > li[data-segment-ordinal="4"]`(unavailable), `.deep-review-segment-panel`이다. 첫 항목의 원문 버튼은 `7쪽 원문 열기`이며 PDF 링크는 `#page=8`을 사용한다.
