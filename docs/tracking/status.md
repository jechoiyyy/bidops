# 통합 상태

기준일: 2026-08-26. 이 표는 현재 브랜치에서 직접 검증한 사실만 기록한다. 실행 ID·게이트 ID·평가 결과를 만들어 쓰지 않는다.

## 증거 상태

| 영역 | 상태 | 확인 사실 |
|---|---|---|
| source pipeline | 완료 | `./run-tests.sh` 통과: collect 28, report 13, screen 48, root 2 (총 91) |
| backend/frontend fake CI | 완료 | fresh SQLite migration 뒤 backend 312 passed, frontend production build 통과; 기존 Vite chunk size warning만 관찰 |
| Docker config/build | 완료 | `docker compose config --quiet` 및 `docker compose build` 통과; Python은 `web/backend/requirements.lock` exact pins, frontend production build warning(>500 kB chunk)만 관찰 |
| 관리자 화면 | 완료(컨테이너 검증) | 밝은 RootLab 여유형 체계, 로컬 Pretendard, 공통 셸과 12개 화면 대상을 390/768/1024/1440px에서 검증했다. Pretendard 기반 스냅샷 48개를 갱신했으며 exact Docker 갱신·비갱신 실행 모두 150 passed, 10 intentional skipped였다. host 직접 browser launch는 환경의 `libnspr4/libnss3` 부재로 제한됨 |
| live Ollama/T15 | 대기 | `BIDOPS_LIVE_OLLAMA_TEST=true`와 explicit single live command/marker를 포함한 operator smoke 결과 없음 |

visual의 10 skip은 draft spec의 기존 넓은 화면 보조 흐름 5건이 390px/768px 조건에서 각각 skip된 것이다. 새 검토 대기열 초안 복귀 흐름은 390/768/1024/1440px 모두에서 실행한다. 스냅샷에는 대시보드, 검토 대기열, 판정 이력, 담당자 리뷰 준비 화면, 수집 실행, 첨부 확보, 프로필, 검증 지표, 품질 게이트 두 상태, 정책, 상시 운영이 네 폭으로 고정돼 있다.

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
