# 기존 문서 보관

이 디렉터리는 완료된 계획·인수 자료·목업·과거 검증 기록을 원래 내용과 함께 보존한다. 보관본의
미래 계획, 당시 경로, 당시 상태는 현재 구현의 권위가 아니다. 현재 결정과 실행 규칙은
프로젝트 루트의 `AGENTS.md`·`CLAUDE.md`와 [현재 운영 문서](../ARCHITECTURE.md)를 따른다.

현재 기준 문서는 [아키텍처](../ARCHITECTURE.md), [통합 ADR](../ADR.md), [PRD](../PRD.md),
[업무 규칙](../business-rules.md),
[API·파일 계약](../contracts.md), [운영 절차](../operations.md), [보안](../security.md),
[표준](../standards.md), [Agent 워크플로 설계](../agent/agent-workflow-design.md)다. 날짜별 실행 증거와
결정 기록은 [tracking](../tracking/)과 [validation-runs](../validation-runs/)에 있으며, 회사
근거자료는 [reference](../reference/)에 별도로 보존한다.

## 보관 영역

- `planning/`: 프로젝트 개요, PRD, ADR, 구현 계획
- `integration/`: 통합 계획, 워크트리 경계, 인수 기록
- `review/`: 시점별 코드 리뷰와 완료·미착수 UI/UX 계획, 단계별 변경 명세
- `ui/`: 완료된 UI 개선 계획과 설계 export
- `e2e/`: 이전 E2E 흐름 시각화
- `validation/`: 초기 skill 워크플로 검증 기록
- `handoff/`: 세션 인수인계 역사 기록
- `tracking/`: 종료된 결정 대기 목록·중복 결정 색인 등 시점별 추적 기록

`review/`의 두 UI/UX 계획은 원래 "콜드 세션 실행 진입점"으로 쓰였다. 보관하면서 그 선언과
실행 프롬프트를 제거했다. **`R-xx`·`A-xx`를 여기서 새로 시작하지 않는다.** 현재 진행 중인
작업은 [`docs/PLAN.md`](../PLAN.md)와 [`docs/tracking/lifecycle-workstream.md`](../tracking/lifecycle-workstream.md)가 정본이다.

## 원래 경로와 보관 경로

| 원래 경로 | 보관 경로 |
|---|---|
| `HANDOFF.md` | `integration/HANDOFF-T8.md` |
| `docs/agent-workflow-implementation-plan.md` | `planning/agent-workflow-implementation-plan.md` |
| `docs/runtime-deep-review-integration-plan.md` | `integration/runtime-deep-review-integration-plan.md` |
| `docs/worktree-agent-boundary-and-merge-direction.md` | `integration/worktree-agent-boundary-and-merge-direction.md` |
| `docs/web/UI-IMPROVEMENT-PLAN.md` | `ui/UI-IMPROVEMENT-PLAN.md` |
| `docs/web/design/*` | `ui/design/*` |
| `docs/e2e-flow-overview.html` | `e2e/e2e-flow-overview.html` |
| `docs/review/**` (`bid-delta-contract-spec.md` 제외) | `review/**` |
| `docs/deep-review-erd-guide.md` | `deep-review-erd-guide.md` (핵심은 `docs/database-guide.md`로 통합) |
| `docs/bge-m3-colbert-container-setup.md` | `bge-m3-colbert-container-setup.md` (ADR-0037로 미채택) |
| `docs/Backend_HANDOFF.md` | `handoff/Backend_HANDOFF-20260901.md` (현재 ADR·PRD·ARCHITECTURE와 tracking이 대체) |
| `docs/tracking/decisions-pending-20260831.md` | `tracking/decisions-pending-20260831.md` (D-5~D-11 결정 완료 후 보관) |
| `docs/tracking/decisions/index.md` | `tracking/decisions-index-20260901.md` (결정 통합 색인 ADR.md가 대체) |

2026-09-01 정리에서 다음은 보관하지 않고 삭제했다. 완료된 작업을 다시 실행하라고 지시하는
문서였고 근거는 각각의 정본에 남아 있다. 필요하면 git 이력에서 복구한다.

| 삭제한 파일 | 삭제 이유 | 근거가 남은 곳 |
|---|---|---|
| `plan.md` (저장소 루트) | R-08·R-09·R-11 실행 계획인데 셋 다 완료됨 | `review/2026-08-31-ui-ux-remediation-plan.md` 10.13 실행 기록 |
| `docs/review/phase3-prompt.md` | 3단계 착수 프롬프트. 3단계 완료됨 | `review/phase3/plan.md`, `review/phase3/spec.md` |
| `docs/tracking/handoff-20260830.md` | `docs/legacy/handoff/Backend_HANDOFF-20260901.md`가 대체 | 통합 ADR·PRD·ARCHITECTURE 및 tracking 문서 |

이동된 자료와 기존 `planning/**`, `validation/**`의 결정·증거 내용은 정리 과정에서 수정하지
않았다. 이동으로 깨지는 상대 링크만 보정했으며, 원래 경로를 인용하는 내부 문구는 당시 증거의
일부이므로 그대로 보존한다.
