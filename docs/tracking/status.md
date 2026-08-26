# T14 통합 상태

기준일: 2026-08-26. 이 표는 aggregate `dryforge/task-t14`에서 확인한 사실만 기록한다. 실행 ID·게이트 ID·평가 결과를 만들어 쓰지 않는다.

## 증거 상태

| 영역 | 상태 | 확인 사실 |
|---|---|---|
| source pipeline | 완료 | `./run-tests.sh` 통과: collect 28, report 13, screen 48, root 2 (총 91) |
| backend/frontend fake CI | 완료 | `./web/run-web-tests.sh` 통과: backend 311 passed, frontend production build; 기존 Starlette/httpx deprecation warning 1건과 Vite chunk size warning만 관찰 |
| Docker config/build | 완료 | `docker compose config --quiet` 및 `docker compose build` 통과; Python은 `web/backend/requirements.lock` exact pins, frontend production build warning(>500 kB chunk)만 관찰 |
| visual | 완료(컨테이너) | fresh Docker 실행 2회가 각각 98 passed, 10 intentional skipped. Google Fonts network 차단과 image local fonts(`WenQuanYi Zen Hei`, `Liberation Mono`)로 결정성 확보. host 직접 launch는 환경의 `libnspr4/libnss3` 부재로 제한됨 |
| live Ollama/T15 | 대기 | `BIDOPS_LIVE_OLLAMA_TEST=true`와 explicit single live command/marker를 포함한 operator smoke 결과 없음 |

visual의 10 skip은 draft spec의 mobile/tablet 너비 조건에 따른 의도된 skip(5 × 2)이다. 재현 명령과 image/mount 전제는 [운영 절차](../operations.md)에 있다.

## 운영·활성화 상태

- 기본 scheduler env는 false이고 DB always-on switch도 false다.
- fresh migrated DB는 schedule/always-on 기본 singleton과 migration audit event를 만들며 `screening_policy`와 `agency_portal`은 0행이다. startup/entrypoint는 migration, `create_all`, portal seed, policy seed를 하지 않는다.
- T14/T15에서 policy activation은 수행하지 않았다. seed가 필요하면 operator가 명시적 actor로 별도 실행한다.
- always-on enable, live smoke, OpenAI 호출, 자동 restore/rollback, `down -v`는 수행하지 않았다.
- quality gate의 고정 입력은 run `20260817-20260823`, validation schema v2, 40건 A/B 계약이다. 이 문서는 실제 gate/evaluation ID나 pass/fail 값을 주장하지 않는다.

## 다음 operator gate

1. [운영 절차](../operations.md)의 서비스 중지 → `db-backup`(manifest 보존) → confirm+manifest `db-migrate` → `db-verify` → explicit policy seed → web health 순서를 실제 운영 DB에서 수행한다.
2. [모델 품질 게이트](../model-quality-gate.md)의 `operational_approval`을 current profile snapshot으로 측정하고 review/threshold evidence를 기록한다. `model_comparison` pass는 activation 근거가 아니다.
3. 명시적 operator direction이 있을 때만 marker와 explicit command를 함께 사용한 단 한 번의 live smoke를 기록한다. 그 전에는 T15 live를 pending으로 유지한다.
4. scheduler env cap와 DB switch를 별도로 검토하고, activation과 always-on을 자동으로 켜지 않는다.

## 관련 문서

[아키텍처](../architecture.md) · [에이전트 런타임](../agent-runtime.md) · [스케줄링](../scheduling.md) · [모델 품질 게이트](../model-quality-gate.md) · [외부 인터페이스 계약](../contracts.md) · [운영 절차](../operations.md) · [구현·검증 표준](../standards.md)
