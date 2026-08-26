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

## T15 Phase 1 generation-bound live retry (2026-08-26)

- generation binding 후 승인된 current-profile 단일 live execution `scr-72a1ae87342d4d4485fbb467b0e4d3fa`가 exact Ollama `http://192.168.0.139:11434`, tag `qwen3.8:27b`, digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`로 `성공`했다.
- 7 logical stages(5 perspectives + counterargument + synthesis), 8 attempts, v3 judgment 1건을 확인했다. 첫 synthesis `schema_violation` 후 bounded retry가 성공했으며 모든 attempts/telemetry가 generation digest `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1`에 결합됐다.
- 성공 조건 확인 후 stop execution `scr-650cd5e1eea04205b8ffffeaa789df7f`를 실제 `counterargument` 호출 중 한 번 중지했다. actor `t15-validation`, reason `user_requested`, terminal `중단됨`; 6 attempts, synthesis 0건, 부분 artifact 보존을 확인했다.
- 전용 retry DB는 Alembic `0005_generation_config_binding`, policy `activation_candidate`로 유지된다. always-on `false`, schedule `prespec_enabled=false`, `BIDOPS_SCHEDULER_ENABLED=false`, quality gate/schedule execution 0건이다.
- 기존 synthesis-truncation 실패 문서는 수정하지 않았다. 이번 결과는 Phase 1 live retry/stop 증거이며 T15 전체 완료, 40건 A/B 완료, Phase 2/3 gate 통과를 의미하지 않는다. 상세 증거는 [T15 Phase 1 generation-bound live retry](../validation-runs/20260826-t15-phase1-live-retry.md)에 있다.

## T15 generation-budget binding implementation

stage-aware immutable generation config, migration `0005_generation_config_binding`, A/B/activation/scheduler binding, and fake-only tests are implemented in the T15 worktree. The generation binding was live revalidated once in the Phase 1 retry above; the prior synthesis-truncation failure evidence remains unchanged. This is not a T15-wide completion or Phase 2/3 gate result.

Runtime/API follow-up keeps the same status boundary: canonical JSON+digest
roundtrip and fail-closed drift/tamper checks are fake-tested only. The separate
stop-smoke evidence and partial artifacts are recorded in the Phase 1 retry
document; no activation or always-on state change was made.

## T15 Phase 2 `model_comparison` live A/B (2026-08-26)

- Phase 2는 모델 호출 전에 중단되었다. fixed validation set과 Claude baseline은 각각 40건이고 sample order/correspondence 및 digest 검증은 통과했지만, `QualityGateService.create_gate()`가 고정 ID `20260817-20260823`를 DB에서 요구했다. 검증 DB의 유일한 imported run ID는 `20260817-20260823--20260824T090927.138116Z`여서 `QualityGateValidationError: quality gate run or policy is missing`가 재현되었다.
- Phase 2 gate/evaluation/pass A/pass B는 생성되지 않았고 모델 호출·quality metric·review는 0/미측정이다. 첫 실패 뒤 live 호출은 하지 않았으며, 동일 no-write 전검증 오류를 확인하는 재현 명령만 1회 수행했다. 상세 원인과 backup/hash는 [T15 Phase 2 model comparison 기록](../validation-runs/20260826-t15-phase2-model-comparison.md)에 있다.
- 종료 상태는 Alembic `0005_generation_config_binding`, seed policy `activation_candidate`, always-on `false`, `BIDOPS_SCHEDULER_ENABLED=false`, quality gate/evaluation/review 0이다. 이 상태는 Phase 2 blocker 기록이며 T15 전체 또는 Phase 3 완료를 의미하지 않는다.
