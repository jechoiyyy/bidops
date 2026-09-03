# Phase 3 실행 계획

2026-08-27 웹 코드 리뷰의 BLOCKER 2를 제거한다. 목표는 담당자가 브라우저에서
`공고 → 문서 bundle 준비 → 심층 검토 → 최종 의견` 흐름을 끊김 없이 수행하는 것이다.
정확한 파일별 변경 계약은 [spec.md](./spec.md)에 있다.

## 작업 원칙

- 기존 Lean v1 백엔드 14개 API와 상태 전이 계약은 바꾸지 않는다.
- 문서 준비와 심층 검토 mutation은 claimed actor name을 요구하고, 이름을 인증으로
  표현하지 않는다.
- `effective_grade == "우선 검토"` 게이트와 활성 profile/analysis policy preflight를
  프런트엔드에서 우회하거나 성공처럼 보이지 않는다.
- ready bundle과 완료·실패 attempt는 불변이다. 수정·재시도는 새 snapshot/attempt를
  만드는 기존 서버 동작을 그대로 드러낸다.
- 등급과 참여 준비 상태를 섞지 않고, `unknown`·실패·차단 issue를 임의 보정하지 않는다.
- 백엔드, DB, migration, compose, 파이프라인 산출물 계약은 이번 단계에서 수정하지 않는다.

## 작업 단위와 순서

각 작업은 별도 `codex exec`에 위임한다. 한 작업이 끝날 때마다 실제 diff를 직접 읽고
필요한 수정을 마친 뒤 다음 작업으로 넘어간다.

| ID | 제목 | 주요 대상 | 선행 작업 |
|---|---|---|---|
| T5 | 프런트 Lean API·타입 계약 완성 | `components/deep-review/api.ts`, `types.ts` | 없음 |
| T6 | 문서 준비 작업대와 공고 상세 연결 | 새 `DocumentPreparationPanel.tsx`, `NoticeDetailPage.tsx`, 스타일 | T5 |
| T7 | 실패 attempt 재시도와 진행 상태 갱신 | `DeepReviewPage.tsx` | T5 |
| T8 | 브라우저 흐름 회귀 검증 | Playwright mock/spec, 필요한 고정 fixture | T6, T7 |

직렬 순서는 `T5 → T6 → T7 → T8`이다. T6와 T7은 코드상 독립이지만, T5의 공통 오류·actor
header 계약을 먼저 고정해야 서로 다른 mutation 구현이 갈라지지 않는다.

## 화면 흐름

1. 공고 상세의 심층 검토 섹션에서 현재 bundle 이력과 서버 판정 상태를 조회한다.
2. 담당자 claimed name을 입력하고 새 draft bundle을 만들거나 최신 draft를 이어서 작업한다.
3. HWP/HWPX/PDF를 등록하고 각 문서의 역할·시행일·대체 문서·현재 버전을 확인한다.
4. 안전 검사와 구조화 상태, blocking issue를 확인한 뒤 bundle을 명시적으로 확정한다.
5. ready bundle에서 심층 검토를 시작한다. 서버 preflight 503은 활성 profile과 analysis
   policy가 필요하다는 운영 조치로 표시한다.
6. 분석 화면은 stage 상태를 갱신하고, 실패한 current attempt만 새 attempt로 재시도한다.
7. 완료된 machine report를 수정 revision과 사람 최종 의견으로 이어 간다.

문서 구조 조회 함수는 Lean API 계약에 맞게 추가한다. 현재 `DocumentVersionView`가
`structure_id`를 공개하지 않으므로 문서 준비 화면은 `structure_status`를 정본으로 표시하고,
임의 ID를 만들지 않는다. 구조 ID가 evidence 등 승인된 API projection으로 주어진 소비자는
추가된 구조·페이지 조회 함수를 사용한다.

## 검증

| ID | 시점 | 내용 | 통과 기준 |
|---|---|---|---|
| V1 | T5 후 | 프런트 production build | TypeScript strict와 Vite build 통과 |
| V2 | T6·T7 후 | 프런트 production build | 신규 화면·재시도 타입 오류 없음 |
| V3 | T8 후 | 대상 Playwright spec | 생성→업로드→분류→확정→심층 검토, 403/503, retry 흐름 통과 |
| V4 | 최종 | mock-reference T7 통합 확인 | health 정상, 브라우저 API 흐름에 curl/CLI가 필요하지 않음 |

시각 baseline은 변경 화면만 확인한다. 의도된 레이아웃 변경이 있더라도 기존 snapshot을
무조건 갱신하지 않고 실제 diff를 검토한다. 전체 백엔드 테스트는 백엔드 계약을 수정하지
않으므로 필수 변경 게이트는 아니지만, 통합 검증에서 백엔드 신규 실패가 보이면 즉시 조사한다.

## 범위 밖

- 실제 vLLM 연결, OpenAI fallback, 외부 모델 전송 승인 변경
- profile/policy 생성·활성화 UI 또는 운영 secret 생성
- 자동 입찰 제출, 발주처 연락, 최종 Go/No-Go 자동 결정
- Lean API 응답에 `structure_id`를 새로 추가하는 백엔드 계약 변경
- 기존 회차·review·ready bundle·완료 attempt의 수정

## 위임 방식

```bash
codex exec -m gpt-5.6-luna -c model_reasoning_effort=max \
  -C /home/jechoi/projects/bidops -s workspace-write \
  -o <작업별 요약 파일> "<작업 지시>"
```

각 지시에는 이 계획과 [spec.md](./spec.md)의 해당 절, `docs/standards.md`,
`docs/engineering-notes.md`, `docs/business-rules.md`, `docs/contracts.md`,
`docs/security.md`, `web/frontend/AGENTS.md`를 읽으라는 요구와 커밋·git 이력 조작 금지를 넣는다.

