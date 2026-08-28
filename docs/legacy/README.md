# 기존 문서 보관

이 디렉터리는 완료된 계획·인수 자료·목업·과거 검증 기록을 원래 내용과 함께 보존한다. 보관본의
미래 계획, 당시 경로, 당시 상태는 현재 구현의 권위가 아니다. 현재 결정과 실행 규칙은
프로젝트 루트의 `AGENTS.md`·`CLAUDE.md`와 [현재 운영 문서](../architecture.md)를 따른다.

현재 기준 문서는 [아키텍처](../architecture.md), [업무 규칙](../business-rules.md),
[API·파일 계약](../contracts.md), [운영 절차](../operations.md), [보안](../security.md),
[표준](../standards.md), [Agent 워크플로 설계](../agent-workflow-design.md)다. 날짜별 실행 증거와
결정 기록은 [tracking](../tracking/)과 [validation-runs](../validation-runs/)에 있으며, 회사
근거자료는 [reference](../reference/)에 별도로 보존한다.

## 보관 영역

- `planning/`: 프로젝트 개요, PRD, ADR, 구현 계획
- `integration/`: 통합 계획, 워크트리 경계, 인수 기록
- `ui/`: 완료된 UI 개선 계획과 설계 export
- `e2e/`: 이전 E2E 흐름 시각화
- `validation/`: 초기 skill 워크플로 검증 기록

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

이동된 자료와 기존 `planning/**`, `validation/**`의 본문은 정리 과정에서 수정하지 않았다. 원래
경로를 인용하는 내부 문구는 당시 증거의 일부이므로 그대로 보존하며, 현재 문서에서는 위 보관
경로를 사용한다.
