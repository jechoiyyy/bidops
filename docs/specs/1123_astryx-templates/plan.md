# 시안 1(표 작업대) 적용 수정안 (2026-11-23)

사용자가 관리 화면 전체 배치를 **시안 1 기준**으로 정했다(1-A·1-B·1-C는 채택하지 않음). 이 문서는 시안 1을 제품 코드(`web/frontend/src`)에 옮기는 범위·구조·순서를 정한다. 설계는 감독 세션이 쓰고, 구현은 단계별로 Codex(`codex exec`)에 위임하며, 감독 세션이 단계마다 직접 검증한다.

- 시안: `web/frontend/design/astryx-templates/` — 시안 1 기준은 `variant === "a"`, `mode === "base"` 경로. 보기 `http://127.0.0.1:5195/?m=base&page=<화면>`, 캡처 `shots/1-base-*.png`
- 기준 코드: 2026-11-23 21시 작업 트리(main `dde4155` + 커밋 안 된 UI 변경). 복구 지점은 태그 `before-astryx-plan1-20261123-wip`와 `backups/untracked-before-astryx-plan1-20261123.tgz`
- 인계: `/Users/temp/orca/bidops-wiki-ingest-runs/handoff-ui-session-20261123.md`

## 1. 범위

**바꾸는 것**

1. 목록 4화면(발주계획·사전규격·사업기회·최종 Go/No-Go)의 목록을 열이 있는 표로 바꾸고 목록 60% | 미리보기 40%로 둔다.
2. 미리보기의 사실 표시를 라벨-값 세로 목록 하나로, 하단 결정 영역을 `[현재 상태] … [보조 행동][주 행동 1개]` 결정 띠 하나로 통일한다.
3. 상태 표식·분류 표식·마감 글자·사업 흐름·빈 상태를 공용 부품으로 통일한다.
4. 관리 화면(판정 기준·실행 상태)을 왼쪽 구역 메뉴 + 표 + 미리보기로 바꾼다.
5. 읽기 상세(사전규격 상세·사업기회 레코드·입찰공고 상세)를 본문 + 오른쪽 정보 열 + 하단 결정 띠로 맞춘다. 입찰공고 상세는 옛 양식에서 이 틀로 옮긴다.
6. 입찰 참여 결정에 저장 전 확인 단계 표시를 넣고 요건 표를 사실 목록으로 바꾼다. 오늘 할 일을 건수 칸 + 단계별 업무량 표 + 오늘 결정할 것 표로 바꾼다.
7. 인계 사항: 회사 근거 화면의 문장형 제목 위치와 그 검사를 맞춘다.

**하지 않는 것**

- 색·글꼴·셸(사이드바, 흰 패널, 위치 줄 44px)을 바꾸지 않는다. `bidopsTheme.ts`를 고치지 않는다.
- 백엔드, REST 계약, URL 주소·질의 이름, 페이지 크기(100/200/100/500), sessionStorage key를 바꾸지 않는다.
- 추적 선택·최종 Go/No-Go의 사람 결정 경계, 값 없음·미확인·계산 불가·0의 구분, 품질 표식 규칙을 바꾸지 않는다.
- 회사 근거(`CompanyWikiPage`)의 화면 구조는 바꾸지 않는다. 방금 병합된 화면이고 자체 명세(`docs/specs/1123_wiki-ingest/phase3-spec.md`)가 있다. 인계 사항만 처리한다(§6).
- 1-A·1-B·1-C의 내용(글자 키우기, 줄무늬, 보기 설정)은 넣지 않는다.

## 2. 공용 층을 어떻게 둘 것인가

제품에는 이미 공용 층이 있다(`components/common/ReviewPrimitives.tsx`: `SplitWorkspace`, `ReviewRecordList`/`ReviewRecordRow`, `SelectionToolbar`, `ListPagerControls`, `ReviewPreviewHeader`, `ReviewDecisionBar`, `StickyDecisionHeader`). 새 부품을 나란히 만들지 않고 **이 층을 시안 1 모양으로 바꾼다.** 화면은 틀에 내용만 넘기고, 같은 기능의 모양을 화면 CSS에서 다시 정하지 않는다.

| 공용 부품 | 위치 | 출발점 | 대체되는 것 |
| --- | --- | --- | --- |
| `RecordTable` | `components/common/RecordTable.tsx` | Astryx `Table` 조합 방식(`TableHeader`·`TableBody`·`TableRow`·`TableCell`) | `ReviewRecordList`/`ReviewRecordRow`(Astryx List 기반), 사업기회·Go/No-Go가 각자 쓰는 `Table` 데이터 방식 |
| `WorkspaceFrame` | `ReviewPrimitives.tsx`의 `SplitWorkspace` 확장 | 목록 머리 + 선택 도구 + 표 + 쪽 이동 + 미리보기 + 결정 띠 자리를 한 틀로 | 화면별 `*-list-pane`·`*-list-foot`·`*-action-footer` 배치 CSS |
| `DecisionBar` | `ReviewDecisionBar` 일반화 | 왼쪽 현재 상태(라벨+표식+보조 문구), 오른쪽 보조 행동들 + 주 행동 1개 | `footer.pre-specs-detail-actions`, `footer.opportunity-action-footer`, `footer.gng-action-footer`, 관리 화면 `.crit-detail-foot`·`.rs-detail-foot` |
| `StatusMark`·`ClassTag`·`DeadlineText` | `components/common/Marks.tsx` | 시안 `kit.tsx`의 색 표(운영 `.bo-tag`와 같은 토큰 짝) | 화면별 상태 칩·마감 표기 |
| `Facts` | `components/common/Facts.tsx`(기존 파일 확장) | Astryx `MetadataList` — 미리보기·정보 열은 라벨 왼쪽 세로 목록, 머리 영역은 다열 | `dl.c2l-detail-facts`, `dl.pre-specs-detail-figures`, 아이콘 칸, 격자선 표 |
| `FlowSteps` | `components/common/FlowSteps.tsx` | Astryx `Stepper` + 미확인 단계 처리(시안 `Flow`) | 사업기회 번호 원, 레코드 세로 원, 입찰공고 상세 생애주기, 실행 상태 단계 원 |
| `SectionNav` | `components/common/SectionNav.tsx` | 시안의 왼쪽 구역 메뉴 | 관리 화면의 2·3단 탭 |
| `RecordFrame` | `components/common/RecordFrame.tsx` | 시안 `RecordView`의 rail 배치 | `ps-record`·`rec-body`·`judgment-workspace` 배치 |
| 스타일 | `styles/workbench.css` 하나 | 시안 `mock.css`의 시안 1 규칙 | 화면 CSS의 중복 배치 규칙(단계마다 지운다) |

**`RecordTable`의 계약** (가장 중요한 부품)

- 행은 `<tr>`(`TableRow`)이고 `useRowKeyboardNavigation`의 `rowProps`(`data-row-key`, roving `tabIndex`)와 `aria-current`를 **행 요소가 직접 받는다.** `TableRow`는 HTML 속성을 받는다(`@astryxdesign/core/dist/Table/TableRow.d.ts`의 `BaseProps<HTMLTableRowElement>`). 시안 README의 "Table은 행에 속성을 내릴 수 없다"는 데이터 방식에만 해당하는 말이었다.
- 네 목록이 같은 계약을 쓴다. 사업기회·Go/No-Go의 "첫 열 버튼이 `rowProps`를 받는" 방식은 행 방식으로 옮긴다.
- 키 리스너는 표의 스크롤 영역이 진다. ↑↓ 이동, 페이지 경계에서 쪽 넘김, 활성 행의 plain Space로 체크 토글, 화면별 `Ctrl/Cmd+Enter`(발주계획 = 추적 시작, 사전규격 = 상세 열기)는 지금 동작 그대로다.
- 체크 열은 선택이 있는 화면(발주계획·사전규격)에만 있다. active 행과 checked 집합은 분리한다.
- 열은 화면이 배열로 넘긴다. 사업명 열만 남는 폭을 갖고 나머지는 고정 폭이다(비례 열 둘을 쓰면 좁은 폭에서 표가 넘친다 — 시안에서 확인). 긴 사업명은 한 줄로 자르고 `title`로 전체를 준다.
- 검사가 쓰는 표지를 유지한다: 행에 `c2l-row`·`pre-specs-row`·`opportunity-row`·`gng-row` class, 사업명 칸에 `c2l-row-title`·`pre-specs-row-title` class.
- 로딩(`SkeletonBlock`), 빈 상태·오류(`EmptyState`)는 표 자리에서 그린다.

## 3. 화면별 변경

| 화면 | 지금 | 시안 1 | 반드시 유지 |
| --- | --- | --- | --- |
| 발주계획 | `ReviewRecordRow`(li) 2줄 행, 56%, `ReviewDecisionBar` | 표: ☐·사업명·발주기관·예산·(상태)·발주 예정. 적용 필터 토큰. 미리보기 `Facts`(세로)·`DecisionBar` | 선택·복원·selection generation, 일괄 추적 시작/종료 대화상자, `Ctrl/Cmd+Enter`, 직전 사유 다시 쓰기, 위치 표시(1/829), 판정 수정 이력 |
| 사전규격 목록 | 같은 li 행, 밀도 선택 `<select>` | 표: ☐·사업명·발주기관·예산·개요 상태·의견 마감. 밀도 선택은 없앤다(표가 한 가지 밀도) | 선택 검토 순회(`selection_review`), 검토 제외/복원, 일괄 추적, 서버 쪽 보기·필터, 상세 재진입 순서 |
| 사업기회 목록 | `Table` + 첫 열 버튼, 조치 사유 `<ul>`, "다음 확인" 열 | 표: 사업명(조치 사유는 사업명 아래 줄)·발주기관·금액·추적 상태·다음 마감·다음 확인. 미리보기 탭 3개 유지, `FlowSteps` | 조치 사유 칩, 후보 연결·확인 항목 조작, `TrackingStatusDialog`, 저장 안 한 입력 이탈 확인 |
| 최종 Go/No-Go | `Table` + 첫 열 버튼 3줄 | 표: 사업명·발주기관·추정가격·사람 결정·입찰 마감 | 보기별 건수, 결정 화면 진입, 미리보기 탭 3개 |
| 브리핑 | ul grid 행 + PeekPanel 56% | `WorkspaceFrame` + `RecordTable`(사업명·발주기관·반응·마감) + 미리보기 | 반응 버튼, 빈 상태, 탭 2개 |
| 사전규격 상세 | 가운데 1040px 세로 구역, 하단 띠 | 본문 + 오른쪽 정보 열(사실·원문·첨부 요약). 하단 띠 그대로 | 선택 순회 머리, 처리 상태·기술 정보 접힘 규칙(`Collapsible` 금지 그대로), 주장별 쪽 링크, 읽기 폭 |
| 사업기회 레코드 | 정보 열 **왼쪽** 280px, 액션은 위치 줄 | 정보 열을 오른쪽으로. 추적 상태 변경을 하단 결정 띠로. 사업 흐름 `FlowSteps` | 탭 6개와 주소, 꺼진 기능 안내, 노트, 판정·제안서 요청 흐름 |
| 입찰공고 상세(`/judgments`, `/queue`) | 옛 양식(`judgment-workspace`, 본문 탭) | `RecordFrame` + 왼쪽 회차 공고 목록은 `RecordTable`. 회차 선택은 위치 줄 그대로 | 회차 축(ADR-0046 결정 7), 리뷰 저장, 등급 없음 표기 |
| 입찰 참여 결정 | 읽기 \| 결정 44%, 격자선 표 | 같은 2칸. 요건은 `Facts`, 저장 전 확인은 `FlowSteps`(세로) | 결정 값·이유·경계 문구, 추가만 기록, 되돌릴 수 없음 확인. **담당자 이름 입력은 이 화면 것을 그대로 둔다**(사이드바 값으로 합치는 것은 사람 결정 사항, §8) |
| 오늘 할 일 | `CountStrip` + 카드형 패널 | 건수 칸 + 단계별 업무량 표 + 오늘 결정할 것 표 + 일일 수집 | `CollectionStatus` 규칙(`complete`만 수집 완료), 각 업무 화면 링크, 확인할 것 |
| 판정 기준(6주소) | 탭 3겹 + 버튼 행 목록 56% | `SectionNav`(발주계획 선별 / 공고 판정 4구역) + `RecordTable` + 미리보기 + `DecisionBar` | 6개 주소가 각 구역을 직접 연다, 활성화·일일 스위치 확인 절차, 게이트 표 |
| 실행 상태(5주소) | 헤더 탭 4 + 목록 56% | `SectionNav`(4구역) + `RecordTable` + 미리보기(`FlowSteps` 단계 진행) + `DecisionBar` | 5개 주소, 수집 상태 줄, 수동 실행 대화상자, 실패 사유·재시작 표시 |
| 회사 근거 | `CompanyWikiPage` | 구조 변경 없음. §6만 | 병합된 검사 43건 |

시안이 다루지 않은 것은 지금 구현을 그대로 둔다: 모든 대화상자, 로딩·오류 상태, 필터 시트, 토스트, 저장 안 한 입력 이탈 확인.

"단계별 업무량" 표의 숫자는 이미 대시보드 API가 주는 값으로만 채운다. 응답에 없는 열은 만들지 않는다(브라우저에서 계산하지 않는다).

## 4. 기존 규칙·결정과 어긋나는 곳

| # | 지금 문서 | 시안 1 | 처리 |
| --- | --- | --- | --- |
| 1 | 목록 폭: `web/frontend/AGENTS.md` 38%, ADR-0076 38%, `approved-layout.md` 56%(실제 CSS도 56%) | 60% | 새 ADR에서 60%로 정하고 세 문서를 고친다 |
| 2 | `approved-layout.md`: 사업명·기관 한 열, 행 최소 54px(여유 66px) | 열이 있는 표, 한 줄 행 | 새 ADR + `approved-layout.md`에 대체 표기 |
| 3 | `approved-layout.md`: 판정 기준·실행 상태는 "기존 탭" | 왼쪽 구역 메뉴 | 새 ADR |
| 4 | `AGENTS.md`·ADR-0076: 선택 행은 fill, 브랜드 옅은 채움은 상태 표식 전용 | 브랜드 옅은 채움 + 왼쪽 띠(실제 CSS와 같음) | 문서를 실제와 시안에 맞춘다 |
| 5 | `AGENTS.md`·ADR-0076: 하단 슬롯·띠는 추적 결정 전용 | 미리보기 칸 안 결정 띠를 모든 목록·관리 화면이 쓴다 | 셸 하단 슬롯(`PageFooterBar`)은 추적 결정 전용 그대로. 미리보기 칸 안 `DecisionBar`는 별개 부품임을 문서에 적는다. 사업기회 레코드의 추적 상태 변경은 추적 결정이라 하단 슬롯에 넣을 수 있다 |
| 6 | `AGENTS.md`: 사업기회·Go/No-Go는 `rowProps`를 첫 열 버튼이 받는다 | 네 목록 모두 행이 받는다 | `AGENTS.md` "검토 흐름" 고침 |
| 7 | `AGENTS.md`: 사전규격 목록 밀도(촘촘) | 밀도 선택 없음 | 문서 고침. 사람 확인 사항(§8) |
| 8 | `AGENTS.md`·ADR-0076: 화면 제목은 셸이 문장형으로 | 지금 셸은 목록 화면에서 문장형 제목을 그리지 않는다(커밋 안 된 `TopBar.tsx`) | 문서를 지금 셸에 맞춘다: 목록 화면의 데이터 문장은 설명 줄 또는 목록 머리 |
| 9 | 사업기회 레코드 정보 열 방향(문서 규정 없음, 코드는 왼쪽) | 오른쪽 | 새 ADR에 적는다 |
| 10 | 시안 README: "`Table`은 행에 속성을 내릴 수 없다" | 조합 방식은 가능 | README 고침 |

새 결정은 **ADR-0077 "표 작업대 배치"** 하나로 적고 ADR-0076·`approved-layout.md`의 해당 문장에 대체 표기를 단다. 문서는 감독 세션이 쓴다(단계 6).

## 5. 단계

각 단계는 그 상태로 멈춰도 화면이 동작해야 한다. 단계마다 감독 세션이 빌드와 해당 검사를 직접 돌리고, 바뀐 화면을 1280·1440·1920 폭에서 캡처해 시안과 대조한다.

검증 명령(`web/frontend`에서):

```bash
npm run build
PW_PORT=4312 PW_OUT_DIR=dist-pw npx playwright test --project=app --workers=2 <spec들>
PW_PORT=4312 PW_OUT_DIR=dist-pw npx playwright test --project=layout-desktop --project=layout-small-desktop --project=layout-laptop --workers=2 design-shell.spec.ts overflow.spec.ts
```

Playwright는 한 번에 하나만 돌린다(운영이 같은 Mac에서 돈다). 테마를 고치지 않으므로 `test:contrast`는 마지막에 한 번만 돌린다. 전체 `test:screens`는 공용 층을 바꾸는 단계 2·3 뒤와 마지막에 돌린다.

| 단계 | 내용 | 주요 파일 | 깨질 검사와 처리 | 검증 spec |
| --- | --- | --- | --- | --- |
| 0 | 인계 사항(§6)과 기준선 정리. 2026-11-23 21시 전체 실행은 1,001 통과·80 실패·18 건너뜀이었다(실패 목록 `baseline-failed-20261123.txt`). 실패를 원인별로 가르고 초록 기준선을 만든다. 0a = 셸·회사·관리·기타 39건, 0b = 발주계획·사전규격 계열 41건 | `pages/CompanyWikiPage.tsx`, 실패한 spec 27개 파일, 원인이 제품 결함인 경우 해당 화면 파일 | 2026-11-21~23 승인 배치를 따르지 못한 낡은 단언은 지금 화면에 맞춘다. 제품이 문서화된 동작 계약을 어긴 경우는 제품을 고친다. 건마다 분류와 근거를 남긴다 | 기준선에서 실패한 spec 전부 |
| 1 | 공용 부품(`RecordTable`·`DecisionBar`·`Marks`·`Facts`·`FlowSteps`·`workbench.css`)과 분할 60/40. 사업기회·Go/No-Go에 적용 | `components/common/*`, `pages/OpportunitiesPage.tsx`, `pages/GoNoGoPage.tsx`, `components/opportunities/OpportunityDetail.tsx`, 해당 CSS | 비율 0.56 단언(`design-shell`, `*-consistency`) → 0.60. `.gng-row`·`.opportunity-row-business`의 버튼·`aria-pressed` 단언 → 행·`aria-current` | `opportunities`, `go-no-go`, `common-interactions`, `design-shell`, `review-workspace-consistency`, `explore-workspace-consistency`, `overflow` |
| 2 | 발주계획·사전규격 목록을 `RecordTable`로. 선택 열, 필터 토큰, 미리보기 `Facts`·`DecisionBar` | `pages/OrderPlansPage.tsx`, `pages/PreSpecsPage.tsx`, `components/order-plans/*`, `components/pre-specs/*`, `ReviewPrimitives.tsx` | `[data-review-primitive="dense-list-row"]`, `.review-list-columns`·`.review-row-columns` 구조 단언, 밀도 선택 단언. 행 class·`data-row-key`·`aria-current`는 유지해 동작 검사는 그대로 통과시킨다 | `order-plans`, `pre-specs`, `prespec-list-work`, `list-selection`, `review-primitives`, `search-ux`, `workspace-filter-sheet`, 위 구조 spec |
| 3 | 관리 화면: `SectionNav` + 표 + 미리보기 | `pages/CriteriaPage.tsx`와 탭 5개, `pages/RunStatusPage.tsx`와 탭 4개, `components/criteria/*`, `components/runs/*`, `components/operations/*` | `admin-workspace-consistency.spec.ts`는 구조 단언 대부분을 새 구조로 다시 쓴다. 탭 개수 단언 → 구역 메뉴 항목 | `criteria`, `order-plan-policies`, `run-status`, `admin-workspace-consistency` |
| 4 | 읽기 상세 3화면 | `pages/PreSpecDetailPage.tsx`, `pages/OpportunityRecordPage.tsx`, `components/record/*`, `pages/NoticeDetailPage.tsx`·`ReviewWorkspacePage.tsx`·`QueuePage.tsx` | 배치 단언(`prespec-detail-layout`, `opportunity-record`), 옛 양식 class | `prespec-*`, `opportunity-record`, `verdict`, `proposal`, `review-primitives`, `route-context` |
| 5 | 입찰 참여 결정, 오늘 할 일, 브리핑 | `pages/BidDeltaDecisionPage.tsx`, `pages/DashboardPage.tsx`, `components/dashboard/*`, `pages/BriefingPage.tsx` | 대시보드 카드 구조 단언, 브리핑 행 구조 단언 | `bid-delta`, `dashboard`, `briefing`, `prespec-briefing` |
| 6 | 문서(ADR-0077, `AGENTS.md`, `approved-layout.md`, README, 현황)와 안 쓰는 CSS·컴포넌트 정리, 전체 검사 | 문서, `styles/*`, `ReviewPrimitives.tsx`의 죽은 export | — | 전체 `test:screens`, `test:contrast`, `npm run build` |
| 7 | 운영 배포(§7) | — | — | 배포 뒤 운영 화면 읽기 확인 |

위임 모델: 기계적인 단계(0·5)는 `gpt-6.2-sol` medium, 공용 층과 키보드·선택 계약을 건드리는 단계(1·2)는 같은 모델 high, 나머지(3·4)는 medium으로 시작하고 검증에서 계약 위반이 나오면 올린다.

**구현자에게 주는 공통 조건**

- 한 단계의 범위 밖 파일을 고치지 않는다. 백엔드·테마·`scripts/`·환경 파일·운영을 건드리지 않는다. commit·브랜치 전환·push를 하지 않는다.
- 색은 테마 토큰만 읽는다. 새 hex, `:root`의 `--color-*` 재정의, 패널 안 그림자 카드를 만들지 않는다.
- 검사를 통과시키려고 동작을 숨기지 않는다(`.first()`·강제 클릭 금지). 구조가 바뀌어 깨진 단언은 새 구조를 단언하게 고치고, 동작 단언은 지우지 않는다. 고친 단언은 보고에 목록으로 적는다.
- 사용자 문구는 해요체, 서버가 준 문자열·계약 값은 그대로 둔다.

## 6. 인계 사항 처리

- **원인.** 커밋 안 된 `TopBar.tsx`가 레코드 칸이 있는 상세 화면에서만 `usePageHeader`의 `title`·`eyebrow`·`tag`·`facts`를 그린다. 목록·관리 화면은 `<h1>`이 화면 이름이고 `description`만 `p.topbar-view-note`로 나온다. `/company`는 레코드 칸이 없어 51~52행의 문장이 어디에도 나오지 않는다.
- **결정.** 문장("실적 N건 가운데 M건이 업무별 근거 지도에 들어 있어요" / "실적 N건이 등록돼 있어요")을 `description`으로 넘긴다. 근거: 그 순간의 데이터를 말하는 문장은 설명 줄이 진다는 규칙(`web/frontend/AGENTS.md` "UI 패턴")과 같고, 발주계획이 이미 같은 방식이다(`OrderPlansPage.tsx`의 설명 줄). `<h1>`은 "회사 근거"로 둔다. 이미 `description`에 다른 문장이 있으면 그 문장과의 우선순위를 화면 명세(`phase3-spec.md`)에서 확인해 정하고 보고한다.
- **검사.** `tests/company-wiki.spec.ts:139`는 `<h1>`이 아니라 설명 줄의 문장을 단언하게 고친다. `tests/company-ground-truth.spec.ts:24`의 eyebrow 단언과 `tests/company-workspace.spec.ts:176`의 틀린 주석을 지금 셸에 맞춘다. 스냅샷 태그에 남은 UI 세션의 옛 수정(+11/-20)은 옛 `CompanyPage` 검사라 되살리지 않는다.
- **같은 원인의 다른 검사.** 기준선 전체 실행에서 실패하는 것 가운데 셸의 같은 변경 때문인 것(조사에서 추정한 `briefing.spec.ts:517`, `opportunity-record.spec.ts:83` 등)을 단계 0에서 같이 맞춘다. 원인이 다른 실패는 고치지 않고 보고한다.

## 7. 운영 반영 선행 조건

지금 운영 web은 `bidops:list-review-sheets-20261123`, DB는 `0042_engine_run`이다. 새 코드의 `ALEMBIC_HEAD`가 `0043_company_wiki_ingest`라서 **web을 새 이미지로 바꾸려면 DB 변경이 먼저다.** 순서(`docs/operations/host.md`, `docs/operations/company-wiki-ingest.md`, `docs/operations/backup-restore.md`):

1. 전체 검사 통과 확인, 배포 입력 고정(커밋 또는 재현 패치), 롤백 태그.
2. PostgreSQL 전체 백업과 확인. 백업 명령이 postgres를 다시 만들지 않는지 먼저 확인한다(2026-11-21에 실행 중 스레드가 끊긴 일이 있다).
3. linux/amd64 이미지 빌드.
4. migration `0043_company_wiki_ingest`와 `scripts/runtime-privileges.sql` 적용.
5. web 교체, health·읽기 화면 확인. analysis-worker는 web보다 옛 코드라, 같이 바꾸면 UI 세션의 백엔드 변경 13개 파일이 worker에 들어간다.
6. 회사 위키 넣기 기능을 켤 경우에만: MinIO 버킷 `bidops-company-wiki-ingest`와 전용 키, 환경 값, `BIDOPS_COMPANY_WIKI_INGEST_ENABLED`.

저장소 규칙은 재배포·migration·활성화를 각각 직전에 사람이 확인하도록 한다. 구현과 검증이 끝나면 이 목록을 실제 값(이미지 태그, 백업 파일, 명령)으로 채워 한 번에 확인받고, 승인된 범위만 실행한다.

## 8. 위험, 멈춤 조건, 사람이 정할 것

**위험**

- 발주계획 검사만 228건이다. 행 구조를 바꾸면서 선택·키보드 계약이 조용히 깨질 수 있다 → 행 표지를 유지하고 동작 검사를 그대로 통과시키는 것을 단계 2의 합격 조건으로 둔다.
- 1280px에서 표의 사업명 열이 약 10자다(시안 실측). 시안 1의 알려진 한계이며 이번 범위에서 고치지 않는다.
- 작업 트리에 커밋 안 된 변경이 150여 개 파일이고 그중 일부만 운영에 있다. 단계마다 스냅샷 태그를 남긴다.

**멈춤 조건**

- Astryx `Table` 조합 방식으로 §2의 계약(행 속성, 고정 폭 열, 스크롤 영역)을 만족할 수 없으면 단계 1에서 멈추고 보고한다.
- 한 단계에서 동작 검사(구조 단언이 아닌 것)를 지우거나 약하게 해야만 통과한다면 멈추고 보고한다.
- 범위 밖 파일(백엔드, 테마, `scripts/`) 수정이 필요해지면 멈춘다.

**사람이 정할 것** (정해지기 전에는 오른쪽 기본값으로 진행)

| 항목 | 기본값 |
| --- | --- |
| 사전규격 목록의 밀도 선택을 없앨지 | 없앤다(시안 1은 한 가지 밀도) |
| 입찰 참여 결정의 담당자 이름을 사이드바 값으로 합칠지 | 합치지 않는다(저장 흐름이 바뀌므로 지금 입력을 유지) |
| 회사 근거 화면도 왼쪽 구역 메뉴로 바꿀지 | 바꾸지 않는다 |
| 배포 때 회사 위키 넣기 기능을 켤지, analysis-worker도 바꿀지 | 배포 확인 때 묻는다 |

## 9. 진행 기록

감독 세션이 직접 돌린 결과만 적는다. 화면 검사는 Codex 샌드박스에서 Chromium이 뜨지 않아 감독이 돌리고 실패 내용을 되돌려 주는 방식으로 진행한다.

| 단계 | 결과 |
| --- | --- |
| 0 (2026-11-23) | 기준선 1,001 통과·80 실패 → 정리 뒤 전체 재실행 1,080 통과·1 실패·18 건너뜀. 검사 27개 파일을 지금 화면에 맞췄고 지운 검사는 없다. 제품 변경 3건: 회사 근거 실적 문장을 설명 줄로(`CompanyWikiPage.tsx`), 회차 없이 연 검토 대기열 상세가 빈 화면에 머물던 결함(`QueuePage.tsx`), 사전규격 상세 필터의 날짜 입력이 1280·1440px에서 칸을 넘던 결함(`pre-specs-relaxed.css`). 남은 1건은 검사 mock(`tests/api-mock.ts`의 route callback 안 `page.evaluate`)이 새로고침·이동과 겹칠 때 생기는 경합이고 실행마다 다른 검사가 걸린다 — 따로 고친다. 사전규격 상세의 미저장 사유 보호(PN-06)는 운영 화면에 사유 입력이 없어 그 부분을 뺐고 같은 동작은 `company-review.spec.ts` T4가 검사한다. 스냅샷 태그 `astryx-plan1-phase0-wip` |
| 1 (2026-11-23) | 공용 부품(`RecordTable`·`Marks`·`FlowSteps`·세로 사실 목록·`DecisionBar`·`workbench.css`)과 목록 60/40, 사업기회·최종 Go/No-Go 표 전환. 감독 실행: 관련 화면 검사 358건, 세 폭 구조 검사 151건 통과. 두 화면의 행 이동은 "첫 열 버튼"에서 "행(`tr`)" 방식으로 옮겼고 ↑↓·페이지 경계·이탈 확인 검사가 그대로 통과한다. 눈으로 본 뒤 고친 것: 값 칸 14px 먹색, 1280px 사업명 열 약 190~200px, 쪽 이동 줄 한 형식, 결정 띠 보조 문구 크기. 남긴 것: 값 칸의 낱말 중간 줄바꿈 → 단계 2에서 공용 부품으로 고친다. 스냅샷 태그 `astryx-plan1-phase1-wip` |
| 2 (2026-11-23~24) | 발주계획·사전규격 목록을 체크 열이 있는 `RecordTable`로 전환. 적용 필터 토큰, 세로 사실 목록, `DecisionBar`(사전규격의 주 행동은 `추적 시작하기` 하나, `상세 페이지 열기`는 보조), 목록 바닥의 키보드 안내, 사전규격 밀도 선택 제거. 1차 전체 실행 1,071 통과·11 실패 → 되돌림 뒤 감독 실행: 관련 화면 검사 340건, 세 폭 구조 검사 151건 통과. 제품이 틀렸던 것: 사전규격 표 값이 16px로 나오던 것(14px로 고침). 결정 띠 고정 검사는 CSS 속성 대신 스크롤 전후 위치를 단언하게 바꿨다. 행에서 뺀 값(발주계획 첫 수집일·가까운 역량, 사전규격 발견 구분·SW 값·제외 기록)은 미리보기에서 읽는다. 남긴 것: 사업명 열 폭 우선순위, 발주계획·사전규격 결정 띠의 담당자 안내 위치 차이 → 단계 3 첫 항목. 스냅샷 태그 `astryx-plan1-phase2-wip` |
| 3 (2026-11-24) | 판정 기준·실행 상태를 `SectionNav`(200px) + `RecordTable` + 미리보기(60/40) + `DecisionBar`로 전환. 11개 주소가 각 구역을 직접 연다(`/criteria`·`/order-plan-policies` → 선별 정책, `/run-status`·`/runs` → 수집 실행). 관리 표는 `RecordTable`을 감싼 `AdminRecordTable` 어댑터다. 1차 전체 실행 1,081 통과·3 실패 → 되돌림 뒤 감독 실행: 관련 화면 검사 371건, 세 폭 구조 검사 151건 통과. 제품이 틀렸던 것: 1280px 수집 실행에서 줄바꿈된 관련 링크가 결정 띠를 화면 아래로 밀던 것, 사업명 글자 폭이 여백 때문에 148px이던 것. 상태 표식 색은 표시 문구가 아니라 API 상태 값에서 정하게 바꿨다(첨부 미확보 큐와 상시 운영의 일정·이력 행은 상태 코드가 없어 중립). 단계 2에서 넘어온 사업명 열 폭 우선순위와 결정 띠의 담당자 안내 위치도 이 단계에서 고쳤다. 스냅샷 태그 `astryx-plan1-phase3-wip` |
| 4 (2026-11-24) | 읽기 상세 3화면에 `RecordFrame` 적용. 사전규격 상세: 사실과 원문·첨부 요약을 오른쪽 정보 열(320px)로, 하단 추적 띠·선택 순회·문서 준비 토글·쪽 링크는 그대로. 사업기회 레코드: 정보 열을 왼쪽 280px(활동 탭 420px)에서 오른쪽 320px 하나로, 사업 흐름은 `FlowSteps`, 추적 상태 변경은 하단 결정 띠로. 입찰공고 상세·옛 검토 화면: 옛 양식을 걷고 회차 공고 목록은 `RecordTable`, 탭은 헤더 슬롯으로. 1차 실행 421 통과·3 실패 → 되돌림 뒤 감독 실행: 관련 화면 검사 707건, 세 폭 구조 검사 151건 통과. **수정안과 달라진 것**: 입찰공고 상세는 왼쪽 목록이 있어 오른쪽 정보 열을 쓰면 1280px에서 본문이 약 318px이 된다 — 이 화면은 정보 열 없이 목록 40% \| 상세 60% 두 칸으로 하고 목록 열은 사업명·상태·마감만 둔다. 같이 고친 것: 로딩 자리가 새 두 열 골격을 따르게, 빈 상태의 주 버튼을 검정에서 브랜드 초록(Astryx `Button`)으로. 스냅샷 태그 `astryx-plan1-phase4-wip` |
| 5 (2026-11-24) | 입찰 참여 결정: 읽기 60% \| 결정 40%, 요건은 `Facts`, 저장 전 확인은 한 줄 표시, 바닥은 `DecisionBar`. 담당자 이름 입력·확인 대화상자·추가만 기록은 그대로. 오늘 할 일: 건수 칸 → 오늘 결정할 것 표(두 출처를 마감순으로) → 일일 수집 → 확인할 것. 브리핑: `RecordTable` + 60/40 미리보기, 반응 필터 4개는 그대로. 되돌림 2회 뒤 감독 실행: 전체 1,083 통과·1 실패 → 고친 뒤 관련 화면 검사 123건, 세 폭 구조 검사 151건 통과. **수정안과 달라진 것**: "단계별 업무량" 표는 만들지 않았다 — 응답에 있는 값이 결정 대기 한 열뿐이라 건수 칸과 같은 숫자다. 세로 "저장 전 확인" 단계는 1280px 첫 화면에 결정 이유·담당자 입력이 보여야 한다는 기존 계약을 깨서 한 줄로 줄였다. 제품이 틀렸던 것: 브리핑 표에서 판정 항목의 식별자가 빠진 것, 대시보드 표의 한 열이 몇 px로 줄어 표가 넘치던 것, 사람 결정 값이 모델 판단 색(보라)으로 나오던 것. 스냅샷 태그 `astryx-plan1-phase5-wip` |
| 6a (2026-11-24) | 문서(ADR-0077, `web/frontend/AGENTS.md`, `approved-layout.md`·ADR-0076 대체 표기, ADR 색인, 저장소 지도)와 코드 정리. 안 쓰는 컴포넌트·export와 CSS 규칙 251개(선택자 291개)를 지웠고 `criteria-runstatus.css`를 삭제했다. 감독 실행: **전체 화면 검사 1,085 통과·0 실패·18 건너뜀**, `test:contrast` 통과(테마 파일 변경 없음). 경로에서 빠진 옛 `CompanyPage.tsx`와 전용 파일 4개, `KnowledgeGraph.tsx`는 지우지 않았다(다른 세션이 병합한 코드). 스냅샷 태그 `astryx-plan1-phase6a-wip` |
| 6b (2026-11-24) | 운영 화면 안쪽의 상태 표식을 `StatusMark`·`ClassTag`로 통일(발주계획·사전규격·브리핑·입찰 참여 결정·대시보드·실행 상태·문서 준비·사업기회 레코드의 판정·제안서·활동). tone은 상태 값에서 정하고 품질 표식의 중립 규칙과 등급 표식은 그대로다. 대시보드 건수 칸을 단계 5 이전 모양(흰 바탕·테두리·초록 숫자)으로 되돌렸다 — 단계 5가 시안 구조를 옮기며 색을 바꾼 것을 스냅샷 비교로 찾았다. 모르는 건수의 `–`는 숫자 생략으로, `deep-review-evidence.css`의 raw hex는 토큰으로. 1차 전체 실행 1,081 통과·4 실패 → 되돌림 뒤 감독 실행: **전체 화면 검사 1,085 통과·0 실패·18 건너뜀**. 제품이 틀렸던 것: 사전규격 상세 하단 띠가 표식 때문에 66px로 커진 것(56px 계약으로 되돌림). 스냅샷 태그 `astryx-plan1-phase6b-wip` |
| 배포 전 점검 (2026-11-24) | 최종 빌드를 운영 API(`127.0.0.1:18788`)에 읽기 전용으로 붙여 22개 주소를 열었다(브라우저에서 GET 이외 차단, 차단된 쓰기 0건). 화면 예외·가로 넘침 0. **운영 백엔드를 바꾸지 않을 때 깨지는 화면은 회사 근거 하나**다(`/api/company-wiki` 404 → "회사 근거를 불러오지 못했어요"). `/api/company`·`/api/briefings/latest`의 404와 `/api/profile/*`의 503은 지금 운영에서도 나는 응답이다(미등록 상태). 운영 데이터에서만 보인 결함을 고쳤다: 사전규격 의견 마감 값(`오늘 23:59 · 11.24`)이 열을 넘던 것(132px, 세 폭 회귀 검사 추가), 목록 0건일 때 미리보기 칸이 빈 면이던 것, 관리 화면 상세 안쪽의 큰 옛 상태 칩과 `통과` 표식 잘림, 판정 기준 상세의 테두리 상자, 실행 상태 상세의 안쪽 탭. 사업기회·Go/No-Go 목록의 금액은 10억 원 이상이면 단위 표기(`19.4억원`)로 줄고 원 단위는 툴팁·미리보기에서 읽는다. 감독 실행: **전체 화면 검사 1,088 통과·0 실패·18 건너뜀**. 스냅샷 태그 `astryx-plan1-final-wip`, 운영 데이터 캡처 `shots/product-prod-data-20261124/` |
| 커밋·운영 배포 (2026-11-24) | 사용자 결정 "main에 커밋한 뒤 배포"·"화면만 배포". main `1d85c1b`(프런트엔드·문서), `c660e72`(인계받은 백엔드·계약 문서, 미검증·미배포). 07:10 KST 운영 web을 `bidops:table-workbench-fe-20261124`(직전 web 이미지 + 새 프런트엔드 번들)로 교체했다. DB·백엔드·worker는 그대로다. 회사 근거 화면은 백엔드 배포 전까지 "불러오지 못했어요"로 나온다. 배포 기록(`docs/validation-runs/20261124-table-workbench-frontend/README.md`, git 이력) |
| 백엔드 검증·배포 (2026-11-24) | 사용자 요청 "백엔드 검사 환경 만들어서 검증하고 회사 근거까지 배포". 11:00 KST 운영 DB를 `0043`으로 올리고 web·analysis-worker·첨부 worker를 `bidops:main-20261124-ab08343`으로 교체했다. 회사 근거 화면이 회사 위키를 읽는다. 넣기 스위치는 꺼 둔 그대로다. [검증·배포 기록](../../validation-runs/20261124-company-wiki-backend/README.md) |

**남긴 것** (이번 범위 밖, 후속 후보)

- 백엔드는 2026-11-24에 운영 이미지 런타임과 일회용 PostgreSQL로 검증했다([기록](../../validation-runs/20261124-company-wiki-backend/README.md)). 변경 전부터 실패하던 낡은 검사 28건과 라우터 ORM 규칙 위반 1건(`app/lifecycle/routers/opportunities.py`)은 그대로 남아 있다.

- 상세 내용 안쪽의 직접 쓴 `<dl>` 사실 표시(발주계획 근거, 입찰 변경 비교, 개요 진단 등)와 인라인 빈 상태 문구는 공용 부품으로 옮기지 않았다. 구조가 화면마다 다르다.
- 자동 준비 단계·문서 준비 6단계·제안서 진행의 자체 단계 표시는 그대로다.
- 데모·심층 검토·mock 전용 화면과 회사 근거(`CompanyWikiPage`)는 손대지 않았다.
- 색 대조에서 찾았지만 채택 여부를 정하지 않은 차이 3건: 사업기회 레코드의 `같은 사업으로 연결하기`가 초록 채움에서 테두리 버튼으로, 실행 상태 요약의 칸 사이 선이 `--color-background-muted`에서 `--color-border`로, 대시보드 `새로 볼 것`의 칸 사이 선이 `--bo-line-soft`로 바뀐 것.
- 1280px에서 표의 사업명 열은 180~200px이라 긴 사업명이 잘린다(전체는 `title`과 미리보기).
- 경로에서 빠진 옛 `CompanyPage.tsx`와 전용 파일 4개, `KnowledgeGraph.tsx`는 남아 있다.
