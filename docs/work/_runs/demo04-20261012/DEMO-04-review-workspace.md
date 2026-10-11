# DEMO-04-review-workspace 기능 기록

- run `demo04-20261012`. 기준 `c50ed55`. 기능 worktree `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/demo04-20261012-DEMO-04-review-workspace`.
- engine=claude. complex 단계는 sdlc:implementer-opus, standard 단계는 sdlc:implementer-sonnet이 구현했다. 리더가 단계마다 같은 빌드로 영향 검사를 다시 돌렸고, 최종 리뷰는 Claude general-purpose가 읽기 전용으로 했다.
- 변경: frontend만 바꿨다. 정본 문서 상태 문구와 findings도 고쳤다. backend·migration·env·이미지는 바꾸지 않았다.
- 증거 요약: `docs/validation-runs/2026-10-12-company-demo/DEMO-04-review-workspace/README.md`. 리뷰: `review.md`.

## 단계

| 단계 | 구현 | 리더 검사 | 판단·우려 |
|---|---|---|---|
| STEP-001 회사 경로와 상태 | `companyApi.ts`, 회사 경로 6개(demo-config enabled일 때만), 셸 회사 선택기·표식, 회사 단위 query/session key, mutation 격리 | 21 passed. 셸 layout 96 passed / 1 failed(기존 design-shell:228) | 임시 추적 입력은 STEP-004에서 공용 컨트롤로 옮김 |
| STEP-001 후속 | `useUnsavedGuard` 재차단 경합 수정(`blocker.location` 의존) | 경쟁 재현 RED 3/3 → GREEN 3/3 | STEP-002 첫 실행의 1회 실패를 재실행 통과로 넘기지 않고 원인을 찾았다 |
| STEP-002 프로필과 graph | `KnowledgeGraph` 관계 목록·근거 패널·잘림 안내·키보드·초점 복귀 | guard spec 포함 489 passed / 4 failed(기존) | mock이 계약 §4 BFS 규칙을 fixture에서 계산한다(브라우저 아님) |
| STEP-003 사전규격과 비교 | 서버 필터 목록, 핏 판정 이력(`CompanyFitAttempts`), 3사 비교 | 45 passed | 계약 §5 GraphPath에는 id만 있어 id로 표시한다. 라벨은 backlog |
| STEP-004 승인·보고서·결정 | `TrackingDecisionControl`·`LunaRequest`·`NarrativeReportReader` 회사 adapter, `CompanyDeepReviewPage` | 302 passed / 2 failed(기존 LS-06) / 1 skipped(설계상) | 원문 대조는 true만 보낸다(끄면 미리보기 불가). 회사 보고서는 읽기 전용. 정상 조작으로 생기지 않는 409는 합성 검사로 분리 |
| STEP-005 영향 화면 인수 | `company-layout.spec.ts` 두 폭, LAYOUT_SPECS, mock fallback 정합 | 두 폭 22 passed, RED 16 failed. 비보안 HTTP origin UUID v4 확인 | — |

## 기능 최종 검증

- 리뷰 수정 전 최종(`dist-final`): build 0. app+두 폭 전 spec 833 passed / 6 failed / 6 skipped(`feature-final-screens.log`). 실패 6건은 기준 빌드에서 재현된 기존 실패다.
- 독립 리뷰: PASS_WITH_NOTES, 차단 0. 같은 회차 주의 3건을 수정했다.
  1. demo-config 판정이 내려가며 화면이 다시 마운트되는 문제. RED 1 failed로 재현한 뒤 수정했다.
  2. 저장 처리 중 이탈 문구.
  3. 회사 이름 미확인 상태의 승인 차단.
- 리뷰 수정 뒤 영향 검사(`dist-l6`): build 0. app 13개 spec 271 passed / 0 failed. 두 폭 layout 117 passed / 2 failed(기존 design-shell:228) / 3 skipped(설계상).
- 정본 문서: ARCHITECTURE·contracts·PRD·PLAN·operations·business-rules·ADR 색인을 "DEMO-04 frontend만, mock 검증, 실제 인수 DEMO-05"로 고쳤다. findings에 기존 실패 3종을 추가했다.

## 증명 판단

- docs: pass. 정본·기능 문서 정합과 독립 리뷰 근거가 있다.
- tests: pass. T1–T7을 spec에 연결했고 리더가 실행했다.
- frontend: pass. build와 두 폭 구조·의미 검사를 했다.
- api_guard: pass. 화면 쪽 승인 경계를 확인했다: 조회만 하면 호출 0, 승인 1회, 입력이 바뀌면 재승인, 회사 일치·이름 확인 전 승인 차단, 원문 대조 true만 전송. 서버 쪽 guard는 바꾸지 않았다(DEMO-01·03 소유).
- postgres: not_applicable. frontend만 바꿨고 DB·응답 shape 변경이 없다.
- real_data_run: not_applicable. 소유 기능은 DEMO-05다.

## 한계와 backlog

- 실제 스택의 생성(202)→폴링→보고서, 회사 evidence endpoint, 회사 전환은 DEMO-05에서 인수한다. 그 전에는 "검증됨"으로 적지 않는다.
- `getDemoConfig`의 재조회 실패 유지 분기는 검사가 실행하지 않고 코드 리뷰로만 확인했다.
- 회사 목록 키보드 조작(↑↓·Ctrl/Cmd+Enter), 회사 화면 CSS의 고정 px 2곳, 사유 maxLength가 UTF-16 단위로 세는 차이, 핏 GraphPath 라벨(계약 확장 필요), LS-06 dirty 규칙.
- 회사 화면은 web 이미지를 재빌드·교체하기 전에는 `bidops-local`에 없다(DEMO-05 준비, 직전 확인 대상).
- 커밋: 수동 정책에 따라 사용자 커밋 대기.
