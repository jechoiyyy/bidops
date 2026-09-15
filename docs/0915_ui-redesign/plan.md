# Plan: 관리 화면 재설계 (C 기준) — [`intent.md`](intent.md) 2026-09-15 기준

목표: [`mockups/`](mockups/)의 8화면대로 구현을 마친다. 단계(P0~P4)마다 게이트를 통과한
뒤 다음 단계로 간다. 통짜 위임·통짜 검증을 하지 않는다.

## 시작 전 확인

- 이전 `docs/` 문서(`docs/design/*`·`docs/standards.md`·`docs/tracking/*` 등)와
  `AGENTS.md`·`CLAUDE.md`는 2026-09-15에 의도적으로 삭제됐다(intent 결정 5). 되돌리지
  않고 참조하지 않는다. 코드·테스트 주석이 옛 경로를 가리키는 것은 이번에 고치지
  않는다. 이 작업의 규칙은 `intent.md` §제약과 이 문서가 전부다.
- `web/frontend/node_modules`가 없다. `npm ci` 후 `npx playwright install chromium`.
- 운영 화면(`http://localhost:18887`)은 비교용 읽기 전용이다. 배포하지 않는다.
- 팔레트·등급 ramp·개요 재실행 단추·Go/No-Go 범위는 `intent.md` §결정대로 확정됐다.
  착수 전에 더 받을 답은 없다.

## 바뀌는 파일

| 단계 | 파일 |
|---|---|
| P0 | `web/frontend/src/themes/bidops/bidopsTheme.ts`, `bidops.css`(빌드 산출물), `grade-ramp.css`, `brand.css`(신설), `src/main.tsx`(brand.css import), `scripts/check-contrast.test.mjs`, `src/styles/shell-relaxed.css`, `src/components/shell/Sidebar.tsx`(브랜드 마크), `tests/design-shell.spec.ts` |
| P1 | `src/styles/workspace-filters.css`, `review-primitives.css`, `pre-specs-relaxed.css`, `order-plans.css`, `opportunities-relaxed.css`, `go-no-go.css`, `criteria-erp.css`, `runstatus-erp.css`, `dashboard-erp.css`, `page-overview.css`, `document-preparation.css`, `company-fit.css`, `src/components/common/WorkspaceFilters.tsx`(`WorkspaceFilterBar` 탭 변형), `src/components/common/ReviewPrimitives.tsx`(`SplitWorkspace`·행·칩; Astryx `Token`은 변형을 못 늘리므로 `outline` 칩은 프로젝트 클래스 `.review-chip-outline`), `tests/overflow.spec.ts`(기대 여백) |
| P2 | `src/lib/listSelection.ts`(`selectMany`), `src/components/common/useListSelection.ts`(`selectMany`), `src/pages/PreSpecsPage.tsx`(도구줄·대화상자 제거·인라인 폼 연결), `src/components/pre-specs/PreSpecListDetailPane.tsx`(재작성), `src/components/pre-specs/TrackingDecisionControl.tsx`(`presentation="inline"`), `src/lib/preSpecCautions.ts`(신설, spec §3.2 결정적 산출), `tests/list-selection.spec.ts`, `tests/prespec-list-work.spec.ts`, `tests/pre-specs.spec.ts`, `tests/screen-fixtures.ts`(주의·미확인 표본) |
| P3 | `src/pages/PreSpecDetailPage.tsx`(6단 재배치), `src/components/pre-specs/PreSpecBriefingSection.tsx`, `PreSpecAttachmentList.tsx`(표), `PageOverviewSection.tsx`(알림 줄 분리), `CompanyFitSection.tsx`(문구), `src/components/shell/TopBar.tsx`(순회 슬롯), `src/styles/pre-spec-detail-erp.css`, `tests/prespec-briefing.spec.ts`, `tests/prespec-evidence.spec.ts`, `tests/document-panel-default-open.spec.ts`(선택자) |
| P4 | `tests/pixel-screens.spec.ts-snapshots/*.png` 8장, `tests/design-snapshots/README.md`(이번 시안 위치 추가), `docs/0915_ui-redesign/decisions.md`(신설), `docs/0915_ui-redesign/notes.md`(신설) |

## 작업 순서

### P0 — 팔레트 테마와 셸 (모든 화면이 한 번에 새 색을 받는다)

1. `bidopsTheme.ts` 토큰을 spec §1.1로 바꾸고 `npx @astryxdesign/cli theme build
   src/themes/bidops/bidopsTheme.ts --out src/themes/bidops/bidops.css`. `bidops.css`는
   손으로 고치지 않는다.
2. `grade-ramp.css`를 spec §1.3으로, `brand.css`를 spec §1.2로 만들고 `main.tsx`에서
   `grade-ramp.css` 다음에 import한다. `check-contrast.test.mjs`에 `bo-brand` 비텍스트
   pair와 등급 ramp 새 라벨 pair를 넣는다.
3. `shell-relaxed.css`: 사이드바 배경·테두리·항목·활성, 상단바 배경·테두리, canvas 여백,
   `--shell-sidebar-line` 제거 또는 `--color-border`로 교체. bridge는 이름만 잇고 새 값을
   만들지 않는 규칙을 지킨다. 사이드바 본문이 `--color-on-dark`를 읽는 자리를
   `--color-text-secondary`로 바꾼다.
4. `Sidebar.tsx` 브랜드 마크를 40×40 accent 사각 + 잎 아이콘(인라인 SVG, `NavIcon`과
   같은 방식)으로 바꾼다.
5. `design-shell.spec.ts` 기대값을 spec §2.1로 바꾼다.
6. 게이트: `npm run build`, `npm run test:contrast`, `npm run test:design`. 1440×900 캡처
   8장을 찍어 `mockups/shots/`와 색만 대조한다(구성은 아직 다름).

### P1 — 공통 primitive (6화면이 구성 변경 없이 시안을 따른다)

1. `WorkspaceFilterBar` 보기 탭을 밑줄형으로, 필터 줄 테두리·배경 제거(spec §2.2).
2. `SplitWorkspace`·검토 행·목록 머리/바닥·칩·단추(spec §2.3). `outline` 칩은 Astryx `Token`이 아니라 `ReviewPrimitives`의 프로젝트 클래스로 추가한다.
3. 대시보드·발주계획·사업 추적·최종 Go/No-Go·판정 기준·실행 상태 CSS에서 카드 테두리를
   그림자로, 구분선을 `--color-background-muted`로 바꾼다. 구성·문구는 건드리지 않는다.
4. 게이트: `npm run test:screens`(의미·구조 두 층). 실패는 선택자·기대값이 색·테두리에
   묶여 있던 것인지, 화면이 업무 상태를 잘못 말하는지 먼저 가른다. 캡처 6장 대조 기록.

### P2 — 사전규격 목록 우측 영역과 `전체 선택`

1. `listSelection.ts` `selectMany` + 단위 검사 `LS-08`(중복 없음·기존 순서 유지·메타데이터).
2. `useListSelection` `selectMany` 노출, `PreSpecsPage` 도구줄에 `전체 선택` 추가(spec §3.4).
3. `preSpecCautions.ts`: spec §3.2의 결정적 산출과 단위 검사(검증 실패·첨부 차단·차단
   준비·unknowns만 있는 네 표본 + 전부 없음).
4. `TrackingDecisionControl presentation="inline"`: 기존 record 변형의 필드·검증·저장·
   `onDirtyChange`를 재사용해 한 줄 배치만 다르게 한다.
5. `PreSpecListDetailPane` 재작성(spec §3.1·3.3). 탭 세 개와 `추적 선택 변경` 대화상자를
   없앤다. `PreSpecsPage`의 dialog guard 분기를 인라인 폼의 `onDirtyChange`로 옮긴다.
6. 검사: `screen-fixtures.ts`에 주의 1건·미확인 2건·과업 4건 표본을 추가하고 A3·A4·A5
   검사를 쓴다. `LS-02`·`LS-04`·`LS-06`·`PN-01`·`PN-03`, `pre-specs.spec.ts`의 추적 시작
   3검사(“신규 사전규격은 …”, “사유 예시를 …”, “발주계획에서 승계한 …”)를 대화상자
   없는 흐름으로 고친다.
7. 게이트: `npm run test:screens`. 1280×800 캡처로 A3를 눈으로도 확인한다.

### P3 — 사전규격 상세 6단

1. `TopBar` 액션 슬롯에 순회 컨트롤(`PreSpecDetailNavigation`)을 portal로 옮기고 본문
   상단 카드를 없앤다.
2. `PreSpecDetailPage`를 spec §4 표 순서로 재배치한다. 오른쪽 열을 없애고 `현재 판단`
   알림 줄을 ③ 위로, `확인이 필요한 것`을 ④ 세 번째 열로, `회사 업무 부합 여부`를 ④
   두 번째 열로 옮긴다. `#ps-record-range`·문서 준비 조건부 토글·`Collapsible` 기본 열림
   규칙은 그대로다.
3. `PreSpecAttachmentList`를 표로, `문서 근거` 목록을 ⑤로.
4. `회사 핏` 표기를 `회사 적합성`으로(문구만).
5. `prespec-briefing.spec.ts`를 6단 순서·순회 위치·등급/추적 글자 1회로 개정하고
   `prespec-evidence.spec.ts`·`document-panel-default-open.spec.ts`의 선택자를 맞춘다.
6. 게이트: `npm run test:screens`, `overflow.spec.ts` 두 폭. 2600px 논리 높이 캡처를
   `mockups/shots/PreSpecDetail.png`와 대조.

### P4 — 기준선·문서

1. `decisions.md`를 이 폴더에 새로 쓴다: 팔레트(흰 바탕·`#75A03B` 포인트·`--bo-*`
   프로젝트 토큰), 성공색을 포인트 계열로 옮긴 것, 등급 ramp 초록 4단, 사전규격 목록
   우측 영역 구성, 상세 세로 보고서형 6단, 레이아웃 소유권·지원 폭 1280~1920·zoom 0.9
   유지. 각 항목에 대안과 버린 이유를 한 줄씩 남긴다. 옛 ADR 번호를 잇지 않는다.
2. `npm run test:pixel:update`로 8장 교체. 커밋 메시지와 이 문서 §증거에 변경 사유·
   영향 화면·승인자·승인 시각을 남긴다.
3. `tests/design-snapshots/README.md`에 이번 시안의 위치(`docs/0915_ui-redesign/mockups/`)
   와 MANIFEST를 적는다. 그 디렉터리의 기존 파일은 덮지 않는다.
4. `notes.md`를 이 폴더에 새로 쓴다(재발 방지): `#75A03B`는 글자 금지(3.07:1),
   `--bo-*` 프로젝트 토큰 이유(Astryx `TokenName` 닫힌 union), Tailwind `@theme`이
   `:root`로 방출돼 테마를 이기는 것, 사이드바가 `--color-on-dark`를 읽지 않게 된 것,
   `bidops.css`는 빌드 산출물이라 손으로 고치지 않는 것.

## 위험

- `#75A03B`를 글자나 흰 글자 채움에 쓰면 대비 게이트에 걸린다. 단추·링크는 `#587A2B`,
  글자 강조는 `#3F5A1C`만 쓴다.
- Astryx `TokenName`이 닫힌 union이라 `--bo-brand`를 테마에 넣으면 `tsc -b`가 거부한다.
  프로젝트 CSS(`brand.css`)에 둔다.
- `styles/theme.css`의 Tailwind `@theme`은 `:root`로 방출돼 테마를 이긴다. 새 토큰과
  이름이 겹치는 항목을 거기에 두지 않는다(`design-shell.spec.ts`가 `--color-border`·
  `--color-success`로 감시한다).
- 우측 영역이 1280×800에서 넘칠 수 있다. spec §3.1의 clamp 규칙만으로 맞추고 글자를
  12px 아래로 내리지 않는다. 표본이 넘치면 A3가 잡는다.
- 대화상자를 없애면 미저장 보호 경로가 바뀐다. `LS-06` 두 검사가 폼의 `onDirtyChange`
  경로로 그대로 통과해야 한다. 통과를 위해 `.first()`·강제 클릭으로 가리지 않는다.
- 픽셀 기준선 8장이 전부 바뀐다. 게이트가 아니므로 P4에서 한 번만 교체하고 중간
  단계에서는 돌리지 않는다.
- 성공색·등급 ramp를 포인트 계열로 옮긴 것은 종전 팔레트 규칙과 다르다. `decisions.md`
  기록 없이 머지하지 않는다.
- 사업 추적·대시보드 시안은 운영 화면에 없는 채워진 상태를 그렸다. 구현은 fixture로만
  확인하고 운영 데이터를 만들지 않는다.

## 증거(단계마다 여기에 추가)

| 단계 | 명령 | 결과 | 캡처·기록 |
|---|---|---|---|
| P0 | `npm run build` · `npm run test:contrast` · `npm run test:design` | | 1440 캡처 8장 색 대조 |
| P1 | `npm run test:screens` | | 6화면 캡처 대조 |
| P2 | `npm run test:screens`(+ `LS-08`·A3·A5) | | 1280×800 캡처 |
| P3 | `npm run test:screens`(+ A6·A7) | | 상세 2600 캡처 |
| P4 | `npm run test:pixel:update` | | 사유·영향 화면·승인자·승인 시각 |

시안 대조(A10)는 픽셀 동일이 아니라 구성·색·간격의 일치를 사람이 보고 기록한다.
검증 실행 범위: 단계마다 영향 경로만 돌리고, 통과하면 종료한다. 통과 결과를 얻기 위한
반복 실행, 근거 없는 전체 재검사, 실패를 가리는 수정(`.first()`·강제 클릭)은 하지 않는다.
무관한 기존 실패는 사실대로 적고 범위를 넓히지 않는다.
