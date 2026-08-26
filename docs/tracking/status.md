# T14 통합 상태

기준일: 2026-08-26. 이 표는 aggregate `dryforge/task-t14`에서 확인한 사실만 기록한다. 실행 ID·게이트 ID·평가 결과를 만들어 쓰지 않는다.

## 증거 상태

| 영역 | 상태 | 확인 사실 |
|---|---|---|
| source pipeline | 완료 | `./run-tests.sh` 통과: collect 28, report 13, screen 48, root 2 (총 91) |
| backend/frontend fake CI | 완료 | `./web/run-web-tests.sh` 통과: backend 311 passed, frontend production build; 기존 Starlette/httpx deprecation warning 1건과 Vite chunk size warning만 관찰 |
| Docker config/build | 완료 | `docker compose config --quiet` 및 `docker compose build` 통과; Python은 `web/backend/requirements.lock` exact pins, frontend production build warning(>500 kB chunk)만 관찰 |
| visual | 완료(컨테이너) | fresh Docker 실행 2회가 각각 98 passed, 10 intentional skipped. Google Fonts network 차단과 image local fonts(`WenQuanYi Zen Hei`, `Liberation Mono`)로 결정성 확보. host 직접 launch는 환경의 `libnspr4/libnss3` 부재로 제한됨 |
| live Ollama/T15 Phase 1 | 실패 증거 보존 | exact tag/digest preflight 후 단일 live execution이 5 perspective+counterargument 성공, synthesis bounded retry 2회 `truncated_output`; 최종 `실패` |

visual의 10 skip은 draft spec의 mobile/tablet 너비 조건에 따른 의도된 skip(5 × 2)이다. 재현 명령과 image/mount 전제는 [운영 절차](../operations.md)에 있다.

## 운영·활성화 상태

- 기본 scheduler env는 false이고 DB always-on switch도 false다.
- fresh migrated DB는 schedule/always-on 기본 singleton과 migration audit event를 만들며 `screening_policy`와 `agency_portal`은 0행이다. startup/entrypoint는 migration, `create_all`, portal seed, policy seed를 하지 않는다.
- T14/T15에서 policy activation은 수행하지 않았다. seed가 필요하면 operator가 명시적 actor로 별도 실행한다.
- live smoke 1회를 수행했으나 synthesis truncation으로 실패했다. always-on enable, OpenAI 호출, 자동 restore/rollback, `down -v`는 수행하지 않았다.
- quality gate의 고정 입력은 run `20260817-20260823`, validation schema v2, 40건 A/B 계약이다. 이 문서는 실제 gate/evaluation ID나 pass/fail 값을 주장하지 않는다.

## T15 Phase 1 live smoke (2026-08-26)

- exact Ollama `http://192.168.0.139:11434`, tag `qwen3.8:27b`, digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`를 `/api/tags`에서 확인했다.
- 전용 `.dryforge/t15-runtime` fresh DB를 `0004_migration_audit`까지 migrate하고 actor `t15-validation`으로 seed/ingest했다. tracked run은 40 notices·40 historical judgments로 적재됐다.
- 단일 current-profile CLI execution `scr-32011bae911d407e945308ea2ea63e57`은 5 perspective와 counterargument가 성공했지만 synthesis 2회가 `truncated_output`으로 실패하여 최종 `실패`, 유효 v3 judgment 0건이다.
- stop smoke는 단일 smoke 성공 조건 미충족으로 수행하지 않았다. 40건 A/B gate와 Phase 2/3 gate도 수행하지 않았다.
- policy는 `activation_candidate`, DB always-on은 `false`, `BIDOPS_SCHEDULER_ENABLED=false`를 시작·종료에 확인했다. activation/always-on/scheduler enable은 수행하지 않았다.
- 상세 binding·artifact SHA-256·telemetry·남은 blocker는 [T15 Phase 1 live smoke 기록](../validation-runs/20260826-t15-phase1-live-smoke.md)에 보존했다.

## 다음 operator gate

1. [운영 절차](../operations.md)의 서비스 중지 → `db-backup`(manifest 보존) → confirm+manifest `db-migrate` → `db-verify` → explicit policy seed → web health 순서를 실제 운영 DB에서 수행한다.
2. [모델 품질 게이트](../model-quality-gate.md)의 `operational_approval`을 current profile snapshot으로 측정하고 review/threshold evidence를 기록한다. `model_comparison` pass는 activation 근거가 아니다.
3. synthesis truncation 원인을 해결하기 전에는 추가 live smoke를 수행하지 않는다. 해결 후에도 명시적 operator direction과 marker를 함께 사용한 단 한 번의 재검증만 허용한다.
4. scheduler env cap와 DB switch를 별도로 검토하고, activation과 always-on을 자동으로 켜지 않는다.

## 관련 문서

[아키텍처](../architecture.md) · [에이전트 런타임](../agent-runtime.md) · [스케줄링](../scheduling.md) · [모델 품질 게이트](../model-quality-gate.md) · [외부 인터페이스 계약](../contracts.md) · [운영 절차](../operations.md) · [구현·검증 표준](../standards.md)

## T15 generation-budget binding implementation

stage-aware immutable generation config, migration `0005_generation_config_binding`, A/B/activation/scheduler binding, and fake-only tests are implemented in the T15 worktree. The implementation has not been live revalidated; the Phase 1 synthesis-truncation failure evidence above remains unchanged and no success claim is made.

Runtime/API follow-up keeps the same status boundary: canonical JSON+digest
roundtrip and fail-closed drift/tamper checks are fake-tested only. No Phase 1
success or live revalidation claim is made.
