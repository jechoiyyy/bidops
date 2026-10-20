# 판정 탭 실무자 화면 개선(프런트엔드 1차) — plan

- 기능 ID: `RL-07-verdict-ux`
- 근거: [intent.md](./intent.md), [spec.md](./spec.md)
- 작성일: 2026-10-20 (같은 날 독립 검사 지적 반영)

## 변경 파일

| 경로 | 신규/수정 | 내용 |
|---|---|---|
| web/frontend/src/lib/verdict.ts | 수정 | 파생 함수(spec 규칙 1~11): `cautionItems`, `codeActionSummary`, `isolationLabels`(세 목록 중복 제거 순번, 기존 `isolationTarget` 대체), `companyCellMode`, `allPagesUnknown`(기존 `pageRangeLabel` 기준), `showRootCause`, `checklistCollapsed`, `distinctFitStatuses`, 판단 한글(역할 이름은 기존 `roleLabel` 재사용) |
| web/frontend/src/components/verdict/VerdictCautions.tsx | 신규 | 중앙 주의 포인트 블록(접기·요구사항 보기) |
| web/frontend/src/components/verdict/VerdictSummary.tsx | 수정 | 한 줄 요약·근본 원인 안내·체크리스트 축약·코드 다음 행동 묶음(props: `missingSections`·`rejectedUnitCount`·스크롤 콜백 추가) |
| web/frontend/src/pages/OpportunityRecordPage.tsx | 수정 | `VerdictSummary`에 view의 `missing_sections`·`rejected_units.length`·스크롤 콜백을 넘김(현재 `result`만 넘김, 516행 부근) |
| web/frontend/src/pages/OpportunityVerdictTab.tsx | 수정 | 블록 순서(누락 배너 → 주의 → 검증 실패 → 쪽 안내 → 표), `revealUnitId` 상태(규칙 11), 검증 실패 목록(세 목록 합침) 번호·접기·요구사항 보기·설명 문장, 요약 숫자 스크롤 대상 id, 패널 열림·뷰포트로 `hideCompanyColumn` |
| web/frontend/src/components/verdict/RequirementTable.tsx | 수정 | props `isolationLabels`·`cautionUnitIds`·`revealUnitId`(+소비 콜백)·`hideCompanyColumn` 추가; "주의" 표식, 격리 행 번호, 회사 근거 고정 문구, 원문 열 조건부(열 정의에서 뺌), 상태 select 조건부(숨기면 "전체" 고정), "필수 여부 미표기", 필터 해제·페이지 확장·선택·스크롤 |
| web/frontend/src/components/verdict/SourcePanel.tsx | 수정 | "역할 의견" 절 |
| web/frontend/src/styles/verdict.css | 수정 | 주의 블록·요약 줄·묶음 스타일(토큰만), `.vd-table-scroll.is-compact table { min-width: 0 }`. 열 숨김은 CSS가 아니라 열 정의로(뷰포트 판단은 `matchMedia`) |
| web/frontend/src/components/briefing/PeekPanel.tsx, src/pages/BriefingPage.tsx, src/lib/briefing.ts | 수정 | 판정 이름 4값일 때 `/verdict` 직행 경로 함수 |
| web/frontend/tests/fixtures/verdict.ts, tests/verdict.spec.ts, tests/briefing.spec.ts | 수정 | T1~T20 fixture·검사, 의도적으로 바뀌는 기존 기대값 갱신(아래 STEP-001) |
| docs/1016_rootlab-redefinition/ui-spec.md(§4.4·§4.1), docs/ADR.md, docs/validation-runs/2026-10-20-rl/RL-07/README.md | 수정/신규 | STEP-006 |

## 작업 순서

1. STEP-001 판정 화면 파생 함수와 fixture [standard]
   - 목표: spec 규칙 1~11의 파생 함수를 `lib/verdict.ts`(브리핑 경로는 `lib/briefing.ts`)에 두고, T1~T20이 쓸 mock fixture(caution·conflict(met 행 포함)·code 행·카드/segment 격리와 역할 격리·전 행 쪽 미확인(page_range null + mapping_status unavailable)·전 행 unknown·판단 불가+met·체크리스트 동일값·mandatory null·50행 초과 표)를 추가한다. 화면 변경 없음.
   - 이후 단계에서 의도적으로 바뀌는 기존 기대값(약화가 아니라 spec 규칙 반영, 해당 STEP에서 갱신): `tests/verdict.spec.ts` 165~168행·196~202행 목록 `li` 전체 글자 비교(규칙 4 "격리 항목 k"·"요구사항 보기" 버튼 글자 → 항목 이름 locator로 비교, STEP-002), 206~216행 코드 행 개별 표시(규칙 3 묶음 → 펼친 뒤 검사, STEP-003), 280행 "운영 · 미표기"(→ "필수 여부 미표기", STEP-004), 293행 R7 "회사 근거 없음"(unknown·fact_labels 빔 → "연결된 회사 사실 없음", STEP-004), 331~340행 전 행 충족 표의 빈 상태·"전체" 선택(규칙 10으로 select가 사라짐 → 두 상태가 섞인 표에서 "필수만"으로 빈 상태를 만드는 검사로 바꾸고 전 행 충족 표는 T14로 옮김, STEP-004). 줄 번호는 2026-10-20 기준.
   - 작업 대상: src/lib/verdict.ts, src/lib/briefing.ts, tests/fixtures/verdict.ts
   - 검증: `npm run build`(tsc) 통과, 기존 `tests/verdict.spec.ts` 통과(회귀 없음)
2. STEP-002 주의 포인트 블록·검증 실패 목록 연결 [complex]
   - 목표: 중앙 주의 포인트 블록(규칙 1, 5건 접기, 0건 숨김), 표 "주의" 표식, 검증 실패 목록 번호 통일(규칙 4, 세 목록)·3건 접기·"요구사항 보기"·설명 문장, 요구사항으로 이동(규칙 11: 필터 해제·페이지 확장·선택 유지·스크롤). 검증 실패 목록은 지금처럼 모든 상태에서 보인다.
   - 작업 대상: VerdictCautions.tsx(신규), OpportunityVerdictTab.tsx, RequirementTable.tsx, verdict.css
   - 검증: T1, T2, T3, T4, T5, T8, T9, T17, T18
3. STEP-003 좌측 판정 요약 정리 [standard]
   - 목표: 한 줄 요약(규칙 2: 차단 글자, 주의·사람 확인 버튼), 근본 원인 안내(규칙 7, `/company` 링크), 체크리스트 축약(규칙 9), 코드 다음 행동 묶음(규칙 3, 기본 접힘·펼침·목록으로 이동).
   - 작업 대상: VerdictSummary.tsx, OpportunityRecordPage.tsx(props 전달), OpportunityVerdictTab.tsx(스크롤 대상 id), verdict.css
   - 검증: T6, T7, T12, T13, T20
4. STEP-004 대조표·원문 패널 문구 [standard]
   - 목표: 회사 근거 고정 문구(규칙 5), 원문 패널 "역할 의견" 절, 전 행 쪽 미확인 시 원문 열 숨김 + 안내(규칙 6), 상태 select 조건부·"전체" 고정(규칙 10), "필수 여부 미표기". 완료 표와 부분표에 같은 규칙.
   - 작업 대상: RequirementTable.tsx, SourcePanel.tsx, OpportunityVerdictTab.tsx
   - 검증: T10, T11, T14, T15
5. STEP-005 1280 배치와 브리핑 직행 [complex]
   - 목표: 원문 패널 열림 ∧ 뷰포트 < 1440px에서 회사 근거 열을 열 정의에서 빼 표 넘침 제거(`.vd-table-scroll` scrollWidth ≤ clientWidth, 문서 가로 스크롤 없음 측정), 브리핑 판정 이름 4값 → `/verdict` 직행(피크 링크·Enter가 같은 경로 함수).
   - 작업 대상: verdict.css, RequirementTable.tsx, PeekPanel.tsx, BriefingPage.tsx, lib/briefing.ts, tests/briefing.spec.ts
   - 검증: T16, T19, `npm run test:contrast`
6. STEP-006 화면 명세 정정·실제 화면 확인 [standard]
   - 목표: ui-spec §4.4(주의 포인트 블록·unknown 묶음 제외 결정·한 줄 요약·묶음·표/패널/1280 규칙, HP §8과 일치)·§4.1(브리핑 직행) 정정, ADR.md 한 줄, 실제 10건 화면 1280·1440 캡처 확인.
   - 실제 화면 환경: 격리 스택 `bidops-local`의 `rla-web`(래퍼 `.sdlc/local-runtime/rlc-20261019/compose-rlc.sh`, DB `bidops_rla`, v11 판정 10건 — opportunity 414·422·424·433·441·499·502·523·536·541, `127.0.0.1:18797`, tailnet `:8197`). 새 프런트가 든 web 이미지를 `bidops-local:rl07-<날짜>`로 build해 `RLA_IMAGE`만 바꿔 `rla-web`을 `up -d --no-deps --force-recreate`(격리 스택만, 직전 사람 확인). 운영 `bidops` 스택은 건드리지 않는다. 모델 호출 없음.
   - 작업 대상: docs/1016_rootlab-redefinition/ui-spec.md, docs/ADR.md, docs/validation-runs/2026-10-20-rl/RL-07/README.md, bidops-local rla-web 이미지
   - 검증: `python3 scripts/feature_status.py doctor _`, 실제 화면 캡처(real_data_run)

## 위임

| 단계 | 작업량(S/M/L) | 난이도 | 모델 | 이유 |
|---|---|---|---|---|
| STEP-001 | S | 중간 | standard | 규칙이 spec에 닫혀 있음 |
| STEP-002 | M | 높음 | complex | 필터 해제·선택 유지·스크롤 상태 조정, 번호 일치 불변식, 금지 문자열 |
| STEP-003 | M | 중간 | standard | 문구·표시 규칙이 spec에 닫힘 |
| STEP-004 | S | 중간 | standard | 조건 표시 규칙 |
| STEP-005 | M | 높음 | complex | 레이아웃 측정 불변식(1280 넘침 없음), 라우팅 경계 |
| STEP-006 | S | 낮음 | standard | 문서·캡처 |

## 위험

| 위험 | 징후 | 대응 |
|---|---|---|
| 화면이 판정·상태를 다시 계산하게 됨 | 요약·안내가 서버 값 외의 판단을 함 | 파생 함수는 개수·대응만(spec 규칙 1~10), 리뷰에서 대조 |
| 고정 문구가 모델 문장을 숨겨 근거를 잃음 | 패널에서 reason이 안 보임 | T10이 패널 전문을 검사 |
| unit id가 DOM에 새어 나감(요구사항 보기 대상) | 금지 검사 실패 | 대상은 상태(unitId)로만 쥐고 DOM엔 행 번호만(T18) |
| 1280 수정이 1440·패널 닫힘 배치를 깸 | 기존 1440 검사 실패 | T16 두 폭·패널 열림/닫힘 측정, 기존 spec 회귀 |
| 회사 근거 열을 빼고 min-width를 풀어도 1280에서 넘침 | T16 측정 실패 | 원인(열 폭·긴 단어)을 보고하고 멈춤 — 다른 열 숨김은 spec 변경이라 사용자 결정 |
| mock fixture가 실데이터와 달라 통과만 함 | 실제 화면에서 깨짐 | STEP-006 실제 격리 화면 10건 캡처로 확인(CLAUDE.md "가짜로 증명되지 않는 경로") |
| ui-spec과 HP §8 어긋남이 남음 | 문서 diff 누락 | STEP-006에서 §4.4 정정·ADR 한 줄 |

## 증명

- docs: `python3 scripts/feature_status.py doctor _` + ui-spec §4.4·§4.1·ADR·README diff 검토.
- tests: 비적용 — 백엔드·스크립트 변경 없음(프런트 검사는 frontend 키).
- postgres: 비적용 — 서버·DB 변경 없음.
- frontend: `cd web/frontend && npm run build && npm run test:contrast` + Playwright `--project=app` `tests/verdict.spec.ts tests/briefing.spec.ts tests/opportunity-record.spec.ts`(vite preview `--host 127.0.0.1`, 1280×800·1440×900, T1~T20).
- api_guard: 비적용 — 외부 호출·전송 payload 변경 없음.
- real_data_run: STEP-006 환경(bidops-local `rla-web`, DB `bidops_rla`, v11 실제 10건)에서 판정 탭 1280·1440 캡처로 T1·T6·T8·T10·T11·T12·T16 해당 사항 확인 + 사용자 화면 확인(tailnet :8197). 모델 호출 없음.

## 결과

구현 후 작성한다.
