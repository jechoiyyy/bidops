# DEMO-04 회사 전환·그래프·비교·추적 화면 검증 (2026-10-12)

- 범위: frontend만 바꿨다. 백엔드·migration·env·이미지 변경은 없다. 모든 화면 검사는 `tests/api-mock.ts` 고정 응답으로만 돌렸다. 실제 백엔드, `bidops-local`, 모델 호출은 쓰지 않았다.
- 이 기록은 실제 자료나 실제 모델 품질의 근거가 아니다. 실제 3사 화면 인수는 DEMO-05가 맡는다.
- 기준 `c50ed55`(demo/local-20261009), run `demo04-20261012`, 기능 브랜치 `sdlc/demo04-20261012-DEMO-04-review-workspace`.
- 실행 로그는 `docs/work/_runs/demo04-20261012/`에 있다(아래 파일명은 모두 이 폴더 기준).

## 실행 환경

- macOS(Apple Silicon), Node `npm ci`, Playwright chromium v1234.
- 이 Mac에서는 `vite preview`가 IPv6 localhost에만 바인딩돼 Playwright webServer가 timeout한다. 설정은 바꾸지 않았다. preview를 `--host 127.0.0.1`로 직접 띄우고 `PW_PORT`·`PW_OUT_DIR`로 재사용했다.

## 최종 결과

| 검사 | 명령 | 결과 | 로그 |
|---|---|---|---|
| production build | `npm run build` (tsc -b + vite) | exit 0 | `review-fix-leader-build-default.log` |
| 영향 app spec (리뷰 수정 뒤) | 회사 spec 5개 + luna·narrative·deep-review·pre-specs·route-context·run-status·review-primitives·company-fit, `--project=app` | 271 passed · 0 failed · 0 skipped | `review-fix-leader-app.log` |
| 두 폭 layout (리뷰 수정 뒤) | `--project=layout-laptop --project=layout-desktop` | 117 passed · 2 failed · 3 skipped | `review-fix-leader-layout.log` |
| 화면 게이트 전체 (리뷰 수정 전 최종) | app + 두 폭, `mock-review-prototype` 제외 | 833 passed · 6 failed · 6 skipped | `feature-final-screens.log` |

- 실패는 모두 기준 `c50ed55` 빌드에서도 같은 실패다(`baseline-design-shell.log`, `baseline-admin-listwork.log`).
  - `design-shell.spec.ts:228`: 두 폭.
  - `prespec-list-work.spec.ts:678`·`:734`(LS-06).
  - `admin-workspace-consistency.spec.ts:23`: 두 폭.
  - 기록은 `docs/tracking/findings.md` 2026-10-12 항목과 2026-09-16 항목.
- 건너뜀은 모두 설계상이다. 캡처 전용 env가 없을 때 건너뛰는 `criteria-capture`·`prespec-evidence`, laptop에서 1440 전용 검사를 건너뛰는 `design-shell` 3건이다.
- `mock-review-prototype.spec.ts`는 `.md` import 때문에 수집 단계에서 오류가 난다. 기준에서 바뀌지 않은 파일의 문제라 제외했다.
- 리뷰 수정 뒤에는 영향받는 검사만 다시 돌렸다. 바뀌지 않은 나머지 spec은 리뷰 수정 전 최종 실행 결과를 재사용한다.

## 수용 기준 연결

| T | 검사 |
|---|---|
| T1 회사 전환·새로고침·뒤로·복수 탭·mutation 격리 | `company-workspace.spec.ts` |
| T2 관계 목록·근거 패널·키보드·절단 안내 | `company-graph.spec.ts`, 두 폭 구조는 `company-layout.spec.ts` |
| T3 비교 상태·목록 필터·핏 이력 | `company-comparison.spec.ts`, `company-prespecs.spec.ts` |
| T4 세 상태 저장·409·이탈 | `company-review.spec.ts`, `company-workspace.spec.ts` |
| T5 미리보기·승인 1회·변경 시 재승인·조회 호출 0·핏 승인 UI 없음 | `company-review.spec.ts` |
| T6 1280/1440·긴 한글·로딩·HTTP origin UUID | `company-layout.spec.ts`(비보안 origin `http://bidops-insecure.test` 포함), 각 spec의 1440 overflow 검사 |
| T7 build·legacy 회귀 | build와 legacy spec(`luna-deep-review`·`narrative-report`·`pre-specs` 등) |

## RED 확인 (검사가 결함을 잡는지)

- `step001-playwright-red-check.log`: 회사 공통 무효화·공통 선택 key 결함 빌드 → 3 failed.
- `step001-guard-red.log`: 확인 창 재차단 경합 → 3/3 failed. 수정 뒤 `step001-guard-green-race.log`는 3/3 passed.
- `step002-playwright-red.log`: 초점 복귀·잘림 안내 제거 → 2 failed.
- `step003-playwright-red.log`: stale 라벨·서버 fit 인자 제거 → 6 failed.
- `step004-playwright-red.log`: version_conflict 초안 삭제·조회 시 미리보기 호출 → 2 failed.
- `step005-layout-red.log`: nowrap 강제 → 16 failed.
- `review-fix-playwright-red.log`: demo-config 재조회 실패 시 회사 경로가 사라짐 → 1 failed.

## 증명하지 못한 것

- 실제 백엔드의 생성(202)→폴링→보고서 흐름, 회사 evidence endpoint, 회사 전환. mock으로만 확인했다(DEMO-05).
- `getDemoConfig`의 "재조회 실패 시 앞선 판정 유지" 분기. 회차 전환 무효화에서 demo-config를 빼면서 이 경로는 검사에서 실행되지 않고, 코드 리뷰로만 확인했다.
- 회사 원본이 `fictional_scenario`만 허용하므로 `public_document`·`model_inference` 출처 문구는 화면 증거가 없다.
