# 발주계획 C-2 Phase 2~4 구현·통합 리뷰 (2026-09-02)

## 결과

`docs/PLAN.md`의 Phase 2~4 기능 구현을 완료했다. 각 Phase는 Luna max가 구현하고,
동일 작업 세션 아래의 Sol high 리뷰 결과를 Luna가 다시 판정·수정한 뒤 별도 커밋했다.
최종 통합 리뷰도 같은 방식으로 수행했으며, 미래 확장이나 스타일성 제안은 반영하지 않았다.

| Phase | 범위 | 커밋 |
|---|---|---|
| 2 | C-2 전용 PostgreSQL model, Alembic, 불변 적재, runtime privilege | `c136dfd` |
| 3 | 수동 실행 API, durable worker, vLLM adapter, 중지·stale·telemetry | `aaaef22` |
| 4 | 누적 목록·상세·필터·사람 feedback 검토 화면 | `da508e0` |

## 위임·리뷰 증거

| 범위 | Luna 세션 | Sol high 리뷰 |
|---|---|---|
| Phase 2 | `01a05ddc-0e4a-7b22-b32a-282b692d50ff` | Orca child `Feynman` |
| Phase 3 | `01a05e23-08c2-7c90-99f4-49db8e3f38a8` | task `task_9fd4f16dee0c`, dispatch `ctx_953d0feb9dd2` |
| Phase 4 | `01a05e7c-4f26-74d1-b744-87be2d874160` | task `task_e5f2e83a61d6`, dispatch `ctx_26ce4178c5f2` |
| Phase 2~4 통합 | `01a05edf-8a27-7372-955f-2d4ba656a768` | task `task_27ce315a6d6b`, dispatch `ctx_ef0802b99997`, delivery `delivery_d57ad7f85206` |

## 통합 리뷰에서 수정한 실제 결함

- runtime Alembic head를 `0017`로 맞추고, heartbeat migration에 결정적 감사 marker를 추가했다.
- 활성 policy라도 품질 게이트가 `passed`가 아니면 실행하지 않도록 fail-closed 처리했다.
- source artifact의 SHA-256과 DB 관측 projection을 대조하고 symlink·허용 경로 이탈을 거부했다.
- 모델 호출 직전에 실행 상태와 kill switch를 다시 확인한다.
- batch 완료 journal로 stale process의 성공 prefix와 중단 batch 실패 증거를 복구한다.
- 중지 후 미처리 batch를 가짜 `rejected` attempt로 만들지 않고 `not_attempted`로 보존한다.
- 목록·feedback projection을 같은 최신 성공/부분 성공 execution에 고정했다.
- 1,200~2,000건 모집단을 모두 조회한 뒤 검토 필요·실패 필터와 페이지 경계를 계산한다.
- Phase 2 테이블 6개를 기존 closed-table 회귀 테스트에 포함했다.

앱 role과 worker role 사이에 새 저장 API나 권한 계층을 추가하자는 제안은 반영하지 않았다.
현재 계약상 앱이 완성 artifact의 일회성 적재를 담당하므로 이번 범위에서 분리하면 기능 구현보다
큰 구조 변경이 된다.

## 검증

| 명령·범위 | 결과 |
|---|---|
| Phase 2 disposable PostgreSQL 17 집중 검증 | 71 passed |
| Phase 3 disposable PostgreSQL 17 집중 검증 | 38 passed |
| Phase 4 전체 visual 회귀 | 678 passed, 10 skipped |
| `./run-tests.sh` (최종 수정 후) | exit 0 |
| C-2 backend focused pytest (최종 수정 후) | 19 passed, 2 environment skips |
| `npm run build` (최종 수정 후) | exit 0 |
| `npm run test:visual -- tests/order-plans.spec.ts` | 20 passed (mobile/tablet/laptop/desktop) |
| `docker compose -f docker-compose.t7.yml config -q` | exit 0 |
| `git diff --check` | exit 0 |

전체 `web/run-web-tests.sh`는 PostgreSQL 17에서 1,087개 backend test를 수집했다. 이 실행으로
이번 범위의 migration audit marker, closed table set, C-2 fixture 경로 회귀를 발견해 수정했고
관련 focused 검증은 통과했다. 남은 8개 last-failed 항목은 기존 profile snapshot 1건,
opportunity link/tracking 3건, prespec PostgreSQL 2건, 기존 공고 screening orchestrator 2건이다.
Phase 2~4 변경 경로가 아니며 현재 dirty worktree의 별도 작업을 침범하지 않기 위해 수정하지 않았다.

## 남은 운영 전제

- 승인된 사설 vLLM endpoint와 건별 승인 payload가 준비되지 않아 live model smoke는 실행하지 않았다.
- hosted OpenAI fallback은 추가하지 않았다.
- scheduler·always-on은 계속 비활성이고 수동 실행만 제공한다.
