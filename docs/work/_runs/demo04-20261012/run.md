# DEMO-04 실행

- 승인: 사용자 2026-10-12 `/sdlc:loop DEMO-04-review-workspace` (같은 날 dry-run 범위 그대로).
- 대상: DEMO-04-review-workspace 단독. 기준 `demo/local-20261009` / `c50ed55`.
- 배치: `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/batch-demo04-20261012` (브랜치 `sdlc/batch-demo04-20261012`).
- DEMO-04: `.sdlc/worktrees/demo-local-20261009/.sdlc/worktrees/demo04-20261012-DEMO-04-review-workspace` (브랜치 `sdlc/demo04-20261012-DEMO-04-review-workspace`, 기준 배치 HEAD `c50ed55`).
- engine=claude: 단계 구현은 `runtime.claude.json` agents(standard=sdlc:implementer-sonnet, complex=sdlc:implementer-opus), 최종 리뷰는 Claude 독립 리뷰(읽기 전용).
- 정책: commit/merge 수동, manual_proof=defer, final_review=true, max_retries=1. main/push/운영 배포·실제 모델 호출 없음.
- 검사: frontend만 변경. `npm run build`, Playwright `app`(신규 spec + `luna-deep-review`·`narrative-report` 회귀), `company-layout.spec.ts` 두 폭. 모두 `tests/api-mock.ts` 고정 응답.

## 시작 시 점검 (2026-10-12)

- DEMO-00·01은 status.json phase=done이나 DEMO-02·03 소스로 프로젝트 스냅샷 hash가 바뀌어 `check`가 stale(입력 변경)로 표시한다. DEMO-04 직접 선행은 DEMO-03(충족)뿐이다. §4 최종 검증에서 처리 여부를 기록한다.
- DEMO-04 status의 STEP-002·004·005 `stale`은 이전 pending의 plan 재계획 흔적이며 구현 이력은 없다.
- `feature.json` commands의 tests/frontend가 비어 있어 plan.md 검사 명령을 사용한다.

## 2026-10-12 진행

- 기능 worktree 생성(배치 HEAD `c50ed55`), `phase implementing`. `npm ci`(238 packages), Playwright chromium 설치.
- 기준 build 통과. 기준 회귀 `luna-deep-review`+`narrative-report` 13 passed (기능 worktree `_runs/demo04-20261012/baseline-regression.log`).
- 환경 차이: 이 Mac에서 `vite preview`가 IPv6 localhost에만 바인딩돼 Playwright webServer(127.0.0.1 대기)가 120초 timeout. 제품 결함 아님. 설정은 바꾸지 않고 preview를 `--host 127.0.0.1`로 직접 띄워 `PW_PORT`로 재사용한다.
- STEP-001 위임(complex, sdlc:implementer-opus) → DONE_WITH_CONCERNS. 리더 검사: build 0, `company-workspace`+`luna-deep-review`+`narrative-report` 21 passed skip 0. 공통 셸 변경이라 셸 layout spec 두 폭도 실행: 96 passed·3 skipped·1 failed(`design-shell` native compact 드롭다운 위치 오차 5~7px>4px). 같은 테스트가 기준 `c50ed55` 빌드에서도 두 폭 실패해 기존 환경 의존 실패로 판정(기능 worktree `baseline-design-shell.log`). STEP-001 done.
- STEP-001 우려 이월: 회사 상세의 최소 추적 입력은 STEP-004에서 `TrackingDecisionControl` 회사 adapter로 옮긴다. 보고서 reader의 근거 조회를 회사 evidence endpoint로 바꾸는 것도 STEP-004.
- STEP-002 위임(complex) → DONE_WITH_CONCERNS. 구현자 첫 병렬 실행에서 STEP-001 "미저장 추적 입력" 검사 1회 실패. 재실행 통과로 넘기지 않고 원인 분석: `useUnsavedGuard` 효과가 `blocker.state`만 의존해, router가 transition으로 묶은 `reset()` 직후 재차단되면 blocked→blocked로 효과가 돌지 않아 창 없이 이동만 막힘(제품 경합). STEP-001 구현자가 경쟁 재현 RED 3/3 실패 → `blocker.location` 의존 추가 → 3/3 통과.
- 리더 검사(동일 빌드): build 0; 회사 spec + 회귀 + guard 사용 기존 spec 12개 489 passed·4 failed·skip 0. 실패 4건(`admin-workspace-consistency:23` 두 폭, `prespec-list-work:678/734` LS-06)은 기준 `c50ed55` 빌드에서도 동일 실패 → 기존 실패, 범위 밖(`baseline-admin-listwork.log`). STEP-002 done.
- STEP-003 위임(standard, sdlc:implementer-sonnet) → DONE_WITH_CONCERNS. 리더 검사: build 0, 회사 spec 4개 45 passed skip 0. 결정: 핏 `GraphPath`는 계약 §5상 `node_ids`·`edge_ids`만 있어 id를 서버 순서로 표시한다. 라벨 해석은 계약 밖이라 backlog. STEP-003 done.
- STEP-004 위임(complex) → DONE_WITH_CONCERNS. 리더 검사: build 0. 회사 spec 5개와 공용 컴포넌트(`TrackingDecisionControl`·`LunaRequest`·`NarrativeReportReader`) 사용 spec 15개: 302 passed·2 failed(기준 LS-06)·1 skipped(`prespec-evidence`, 증거 수집 env가 없을 때 건너뛰도록 설계됨). 결정:
  - 회사 경로 원문 대조는 계약상 true만 허용한다. 체크박스를 재사용하되 끄면 미리보기를 막고 승인을 폐기하며 false는 보내지 않는다.
  - 회사 보고서는 쓰기 endpoint가 없어 읽기 전용임을 화면에 명시한다.
  - `idempotency_conflict`·`preview_used`는 정상 조작으로 생기지 않아 합성 응답 검사로 분리한다.
  STEP-004 done.
- STEP-005 위임(standard) → DONE. `company-layout.spec.ts` 두 폭 22 passed, RED 16 failed 확인. HTTP 비보안 origin에서도 request_id가 UUID v4임을 확인. STEP-005 done.
- 기능 최종 리더 검사(`dist-final`): build 0. app+layout 두 폭 전 spec 833 passed·6 failed·6 skipped(`feature-final-screens.log`). 실패 6건은 모두 기준 `c50ed55`에서 재현된 기존 실패다. 건너뜀 6건은 캡처 전용이거나 1440 전용이라 설계상 건너뛴다. `mock-review-prototype.spec.ts`는 `.md` import 수집 오류로 제외했다(기준 미변경 파일, 기존 문제).
- 정본 상태 문구 정합화: ARCHITECTURE·contracts·PRD·PLAN·operations·business-rules·ADR 색인. findings에 기존 실패 3종(LS-06, design-shell:228, mock-review-prototype 수집 오류)을 기록했다.
- 독립 최종 리뷰 위임(Claude general-purpose, 읽기 전용). 기능 tree가 배치 병합 뒤 tree와 같으므로 배치 최종 리뷰로도 쓴다.
- 리뷰 결과: PASS_WITH_NOTES, 차단 0(기능 worktree `_runs/demo04-20261012/review.md`). 같은 회차 주의 3건을 수정했다.
  1. demo-config 판정이 내려가며 화면이 다시 마운트되는 문제. RED로 재현한 뒤 수정.
  2. 저장 처리 중 이탈 문구.
  3. 회사 이름 미확인 상태의 승인 차단.
  주의 6(plan 표·결과·증거 위치)은 리더가 문서로 정합화했다. 나머지는 backlog.
- 리뷰 수정 뒤 리더 영향 검사: build 0. app 13개 spec 271 passed. 두 폭 layout 117 passed / 2 failed(기존 design-shell:228) / 3 skipped(설계상).
- proof: docs·tests·frontend·api_guard pass. postgres·real_data_run not_applicable(근거 기록). `phase validating`, `check` 충족.
- plan 표 변경으로 spec_hash가 바뀌어 `run _ accept-spec`을 기록했다(수용 범위 변경 없음). `run _ ready --feature DEMO-04-review-workspace` 통과.
- 사용자가 기능 브랜치에 `b41285c`로 커밋했다(114 files).
- 배치에 no-ff 병합: `83f5270`. 배치 tree와 `b41285c` tree의 diff가 비어 있어 기능 worktree의 검증·리뷰를 그대로 재사용한다(재실행 없음).
- 배치에서 `run _ ready --feature DEMO-04-review-workspace` 충족, `check DEMO-04-review-workspace` 필수 검증 충족.
- `run _ review` 기록: 독립 Claude 리뷰(`review.md`, PASS_WITH_NOTES·차단 0) result=pass.
- `run _ finish`: run state `awaiting_merge`. **대기: 사용자 커밋**(배치 `run.json`·`run.md`). 커밋 뒤 `run _ finish`를 다시 부르고, 기준 브랜치 반영(`run _ finish --merge`, ff-only)은 사용자가 요청할 때만 한다.
