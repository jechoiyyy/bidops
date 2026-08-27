# 구현·검증 현황

기준일: 2026-08-27.

이 문서는 `dryforge/merge-t15-deep-review` 통합 브랜치의 상태를 기록한다. 두 원본
브랜치의 증거를 모두 보존하며, 어느 쪽 증거도 다른 쪽의 통과로 재분류하지 않는다.
구현됨(built), 결정적 검증 통과(verified), 외부 승인 대기(external pending)는 서로
다른 상태다. 실행 ID·게이트 ID·평가 결과를 만들어 쓰지 않는다.

- 통합 전 Deep Review 브랜치 증거: 아래 「Deep Review 브랜치 증거」
- 통합 전 T15 브랜치 증거: 아래 「T15 브랜치 증거」
- 통합 브랜치 자체의 검증 결과: 아래 「통합 브랜치 검증」

## 통합 브랜치 검증

PostgreSQL 17 단일 정본으로 두 브랜치를 통합했다. 통합 커밋의 실제 검증 명령과
결과는 이 절에 기록한다. 통합 이전 두 브랜치의 수치를 통합 결과로 재사용하지 않는다.

### 2026-08-27 통합 후 검증 결과

| 실행 명령 | 결과 |
|---|---|
| `npm run build` | 성공. Vite 6.4.3, 266 modules transformed |
| `npm run test:visual:update` | 성공. 통합 UI 기준선 갱신 후 184개 중 174 passed, 10 skipped |
| `npm run test:visual` | 성공. 갱신된 기준선과 비교해 184개 중 174 passed, 10 skipped |
| `git diff --check` | 성공 |

---

# Deep Review 브랜치 증거

기준일: 2026-08-27
최종 리뷰 코드 기준: `3c8486f` (`bidops-deep-review`)
T1~T8 구현과 검증을 완료했고, 최종 독립 리뷰에서 확인된 회귀를 수정했다. push/merge/release는 하지 않았다.

### 코드 상태

| 영역 | 현재 상태 | 근거 |
|---|---|---|
| 수집·후보·다섯 관점 판정·보고 | 구현됨 | `bidops.*.v2` 계약, 회차 산출물, pipeline/backend 테스트 |
| PostgreSQL 정본과 SQLite 이관 | 구현됨, 실제 백업본 리허설 미수행 | PostgreSQL 17 `bidops` schema, Alembic, 13개 legacy table import/reconciliation 코드 |
| MinIO·ClamAV·문서 격리 | 구현됨, 실제 운영 권한 검증 미수행 | 목적별 bucket/credential, clean scan, `document-worker network_mode:none`, object hash/location |
| 단계 B document bundle | 구현됨 | 7개 bundle/document API, HWP/HWPX/PDF 검사·구조화, immutable ready snapshot |
| Agent 공통 계약·projection | 구현됨 | `web/backend/app/agents/common/`, 별도 Agent 상태 table 없음 |
| DocumentPreparation/DeepReview/Decision Agent | 구현됨 | 세 package의 typed command·adapter·projection과 대응 테스트 |
| 기존 mutation router 연결 | 구현됨 | document bundle·deep review·report mutation이 해당 Agent adapter를 호출하고 Lean v1 14개 API 계약 유지 |
| 단계 C deep-review runtime | 구현됨, provider-neutral | 세 stage, bounded chunk/retry, fenced job, encrypted raw response, report/validation/evidence API |
| React 심층 검토 화면 | 핵심 조회·리포트 검토 구현됨 | ready bundle 선택, review 시작, report/revision/final opinion 화면과 기능 테스트; 통합 후 `ui-component-refresh`의 review workspace 레이아웃을 적용함 |
| Qwen 품질 activation gate | 계산·import 연결 구현됨, 실제 품질 증적 없음 | human-adjudicated scorer, 0.80/0.70/0.10 gate, policy SHA 일치 import |
| T7 Agent 연속 인수 | 실제 격리 Mock E2E 통과 | PostgreSQL·MinIO·ClamAV·document worker 2개·analysis worker·web, `passed=true`, 종료 active WorkJob 0 |
| legacy run ingest | 최종 리뷰에서 해결·실제 재검증됨 | `screening_basis TEXT` migration, 깨끗한 PostgreSQL에서 40 notices/40 judgments를 두 번 멱등 적재, 102자 원문 보존 |
| 백업·복구 자동화 | 구현됨, 실제 snapshot 복구 훈련 미수행 | object-first restore, PostgreSQL restore, active hash 검증 script |

### 2026-08-27 T8 검증 결과

| 실행 명령 | 결과 |
|---|---|
| `./run-tests.sh` | 성공. `skills/bidops-collect` 28개, `skills/bidops-report` 13개, `skills/bidops-screen` 21개, root `tests` 2개가 모두 `OK`(총 64개) |
| `./web/run-web-tests.sh` | 성공. backend `356 passed, 4 skipped, 6 warnings`; 이어서 frontend Vite build 성공(135 modules transformed) |
| `web/backend/.venv/bin/pytest web/backend/tests` | 성공. `356 passed, 4 skipped, 6 warnings in 20.02s` |
| `cd web/frontend && npm run build` | 성공. Vite 6.4.3, 135 modules transformed, `built in 1.88s` |
| `git diff --check` | T8 문서 수정 완료 후 최종 실행에서 성공 확인 |

backend의 4 skip은 `test_document_bundles.py` 1개와 `test_minio_e2e.py` 3개로, 별도 isolated T7
MinIO service가 필요한 live integration test다. pytest의 6 warnings는 Pydantic `schema` field
shadowing 5건과 Starlette/httpx deprecation 1건이며 이번 실행을 실패로 만들지 않았다.

검증 환경에 `web/backend/.venv`가 처음 없어서 `./web/run-web-tests.sh`의 첫 실행은
`/usr/bin/python3: No module named pytest`(exit 1)로 끝났다. `.gitignore` 대상 virtualenv에
`web/backend/requirements.txt`를 설치한 뒤 같은 명령을 재실행해 위 성공 결과를 얻었다. 첫 실패를
통과 결과로 세지 않는다.

### 2026-08-27 최종 리뷰 검증 결과

- `web/backend/.venv/bin/pytest -q web/backend/tests`: `359 passed, 4 skipped, 6 warnings`
- `./run-tests.sh`: collect 28, report 13, screen 21, root 2; 총 64개 성공
- `./web/run-web-tests.sh`: backend 위 결과와 frontend Vite build 성공
- 별도 `npm run build`: Vite 6.4.3, 135 modules transformed, 성공
- 깨끗한 PostgreSQL 17: Alembic head `0002_screening_basis_text`, 같은 legacy 회차를 두 번 적재해
  40 notices/40 judgments와 동일 run ID, `screening_basis` 102자 무절단 보존 확인
- Luna Max 독립 리뷰에서 `UTF-8''`로 시작하는 printable ASCII actor 이름의 identity 회귀와
  percent 조합 충돌을 확인해 명시적 format header 방식으로 수정했다. Unicode round-trip, 모든 ASCII
  보존, unknown format과 malformed/ASCII-only/control encoding 거부를 포함한 관련 회귀
  `208 passed, 1 skipped`를 재검증했다.

### 2026-08-27 T7 실제 격리 E2E

- `docker-compose.t7.yml` + `docker-compose.t7.mock-reference.yml`의 새 격리 project에서 실행했다.
- PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web을 사용했다.
- provider/model은 `mock-analysis` / `bidops-deterministic-mock-v1`이다.
- 외부 OpenAI/Codex/Qwen 호출은 0건이고 종료 queued/running WorkJob은 0건이었다.
- 결과 schema는 `bidops.t7-e2e-result.v1`, `passed=true`였다.
- 종료 후 격리 container, network, volume을 정리했다.

두 날짜의 bundle/review/revision/opinion ID와 projection checkpoint는
[`docs/mock-workflow-e2e-result.md`](../mock-workflow-e2e-result.md)에 보존한다. Mock 결과의
`mock_quality.evaluated=false`는 실제 Qwen 품질 gate를 통과했다는 의미가 아니다.

### 배포 후보 승격 전 남은 일

1. 원격 vLLM image digest와 `Qwen/Qwen3.8-27B` immutable revision/artifact digest를 고정하고,
   대표 HWP/PDF와 55개 요구사항 gold로 실제 0.80/0.70/0.10 품질 gate를 측정한다.
2. measured profile/policy import와 승인된 외부 egress·secret·MinIO 권한을 실제 배포 환경에서
   검증한다. Mock E2E 증적을 Qwen evidence로 재사용하지 않는다.
3. 운영 SQLite가 아닌 백업 복사본으로 13개 table row/PK/FK, sequence, 리뷰·첨부 metadata,
   실패 후 재실행과 object→DB→active hash 복구를 리허설한다.
4. 고정 Playwright image/font에서 28개 snapshot을 재생성하고 사람이 승인한다. T8에서는 Playwright
   visual test를 실행하지 않았다.
5. 위 조건을 충족하기 전에는 main merge, push, release, Lean v1 tag를 수행하지 않는다.

현재는 T1~T7 Agent 구현과 Mock workflow 인수는 완료됐지만, 실제 Qwen 품질 승인·clean legacy
운영 복구/권한 검증은 완료되지 않은 상태다. clean legacy ingest 차단 문제는 최종 리뷰에서
해결하고 실제 PostgreSQL로 재검증했다.


---

# T15 브랜치 증거

기준일: 2026-08-26. 이 표는 현재 브랜치에서 직접 검증한 사실만 기록한다. 실행 ID·게이트 ID·평가 결과를 만들어 쓰지 않는다.

### 증거 상태

| 영역 | 상태 | 확인 사실 |
|---|---|---|
| source pipeline | 완료 | `./run-tests.sh` 통과: collect 28, report 13, screen 48, root 2 (총 91) |
| backend/frontend fake CI | 완료 | fresh SQLite migration 뒤 backend 312 passed, frontend production build 통과; 기존 Vite chunk size warning만 관찰 |
| Docker config/build | 완료 | `docker compose config --quiet` 및 `docker compose build` 통과; Python은 `web/backend/requirements.lock` exact pins, frontend production build warning(>500 kB chunk)만 관찰 |
| visual | 완료(컨테이너) | fresh Docker 실행 2회가 각각 98 passed, 10 intentional skipped. Google Fonts network 차단과 image local fonts(`WenQuanYi Zen Hei`, `Liberation Mono`)로 결정성 확보. host 직접 launch는 환경의 `libnspr4/libnss3` 부재로 제한됨 |
| live Ollama/T15 Phase 1 | 실패 증거 보존 | exact tag/digest preflight 후 단일 live execution이 5 perspective+counterargument 성공, synthesis bounded retry 2회 `truncated_output`; 최종 `실패` |
| 관리자 화면 | 완료(컨테이너 검증) | 밝은 RootLab 여유형 체계, 로컬 Pretendard, 공통 셸과 12개 화면 대상을 390/768/1024/1440px에서 검증했다. 독립 검토 blocker 수정본의 exact Docker 갱신·비갱신 실행은 각각 172개 중 162 passed, 10 intentional skipped였고, 갱신 실행에서 dashboard 스냅샷 4개를 재생성했다. host 직접 browser launch는 환경의 `libnspr4/libnss3` 부재로 제한됨 |
| 독립 검토 blocker 수정본 재검증 | 완료 | `npm run build` 및 `git diff --check` 통과. `visual.spec.ts` 회귀 테스트 3개 추가 후 Playwright `--list`와 exact Docker 실행 모두 172개를 확인했고, 갱신·비갱신 각각 162 passed, 10 intentional skipped, 갱신 실행의 dashboard 스냅샷 4개 재생성을 확인했다. |

visual의 10 skip은 draft spec의 기존 넓은 화면 보조 흐름 5건이 390px/768px 조건에서 각각 skip된 것이다. 새 검토 대기열 초안 복귀 흐름은 390/768/1024/1440px 모두에서 실행한다. 스냅샷에는 대시보드, 검토 대기열, 판정 이력, 담당자 리뷰 준비 화면, 수집 실행, 첨부 확보, 프로필, 검증 지표, 품질 게이트 두 상태, 정책, 상시 운영이 네 폭으로 고정돼 있다.

### 운영·활성화 상태

- 기본 scheduler env는 false이고 DB always-on switch도 false다.
- fresh migrated DB는 schedule/always-on 기본 singleton과 migration audit event를 만들며 `screening_policy`와 `agency_portal`은 0행이다. startup/entrypoint는 migration, `create_all`, portal seed, policy seed를 하지 않는다.
- T14/T15에서 policy activation은 수행하지 않았다. seed가 필요하면 operator가 명시적 actor로 별도 실행한다.
- live smoke 1회를 수행했으나 synthesis truncation으로 실패했다. always-on enable, OpenAI 호출, 자동 restore/rollback, `down -v`는 수행하지 않았다.
- quality gate의 고정 입력은 run `20260817-20260823`, validation schema v2, 40건 A/B 계약이다. 이 문서는 실제 gate/evaluation ID나 pass/fail 값을 주장하지 않는다.

### T15 Phase 1 live smoke (2026-08-26)

- exact Ollama `http://192.168.0.139:11434`, tag `qwen3.8:27b`, digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`를 `/api/tags`에서 확인했다.
- 전용 `.dryforge/t15-runtime` fresh DB를 `0004_migration_audit`까지 migrate하고 actor `t15-validation`으로 seed/ingest했다. tracked run은 40 notices·40 historical judgments로 적재됐다.
- 단일 current-profile CLI execution `scr-32011bae911d407e945308ea2ea63e57`은 5 perspective와 counterargument가 성공했지만 synthesis 2회가 `truncated_output`으로 실패하여 최종 `실패`, 유효 v3 judgment 0건이다.
- stop smoke는 단일 smoke 성공 조건 미충족으로 수행하지 않았다. 40건 A/B gate와 Phase 2/3 gate도 수행하지 않았다.
- policy는 `activation_candidate`, DB always-on은 `false`, `BIDOPS_SCHEDULER_ENABLED=false`를 시작·종료에 확인했다. activation/always-on/scheduler enable은 수행하지 않았다.
- 상세 binding·artifact SHA-256·telemetry·남은 blocker는 [T15 Phase 1 live smoke 기록](../validation-runs/20260826-t15-phase1-live-smoke.md)에 보존했다.

### 다음 operator gate

1. [운영 절차](../operations.md)의 서비스 중지 → `db-backup`(manifest 보존) → confirm+manifest `db-migrate` → `db-verify` → explicit policy seed → web health 순서를 실제 운영 DB에서 수행한다.
2. [모델 품질 게이트](../model-quality-gate.md)의 `operational_approval`을 current profile snapshot으로 측정하고 review/threshold evidence를 기록한다. `model_comparison` pass는 activation 근거가 아니다.
3. synthesis truncation 원인을 해결하기 전에는 추가 live smoke를 수행하지 않는다. 해결 후에도 명시적 operator direction과 marker를 함께 사용한 단 한 번의 재검증만 허용한다.
4. scheduler env cap와 DB switch를 별도로 검토하고, activation과 always-on을 자동으로 켜지 않는다.

### 관련 문서

[아키텍처](../architecture.md) · [에이전트 런타임](../agent-runtime.md) · [스케줄링](../scheduling.md) · [모델 품질 게이트](../model-quality-gate.md) · [외부 인터페이스 계약](../contracts.md) · [운영 절차](../operations.md) · [구현·검증 표준](../standards.md)

### T15 Phase 1 generation-bound live retry (2026-08-26)

- generation binding 후 승인된 current-profile 단일 live execution `scr-72a1ae87342d4d4485fbb467b0e4d3fa`가 exact Ollama `http://192.168.0.139:11434`, tag `qwen3.8:27b`, digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`로 `성공`했다.
- 7 logical stages(5 perspectives + counterargument + synthesis), 8 attempts, v3 judgment 1건을 확인했다. 첫 synthesis `schema_violation` 후 bounded retry가 성공했으며 모든 attempts/telemetry가 generation digest `51f1878845ed282b20e9c074ca29adbb5ce0a208c89ffae51425a2565ad5dfd1`에 결합됐다.
- 성공 조건 확인 후 stop execution `scr-650cd5e1eea04205b8ffffeaa789df7f`를 실제 `counterargument` 호출 중 한 번 중지했다. actor `t15-validation`, reason `user_requested`, terminal `중단됨`; 6 attempts, synthesis 0건, 부분 artifact 보존을 확인했다.
- 전용 retry DB는 Alembic `0005_generation_config_binding`, policy `activation_candidate`로 유지된다. always-on `false`, schedule `prespec_enabled=false`, `BIDOPS_SCHEDULER_ENABLED=false`, quality gate/schedule execution 0건이다.
- 기존 synthesis-truncation 실패 문서는 수정하지 않았다. 이번 결과는 Phase 1 live retry/stop 증거이며 T15 전체 완료, 40건 A/B 완료, Phase 2/3 gate 통과를 의미하지 않는다. 상세 증거는 [T15 Phase 1 generation-bound live retry](../validation-runs/20260826-t15-phase1-live-retry.md)에 있다.

### T15 generation-budget binding implementation

stage-aware immutable generation config, migration `0005_generation_config_binding`, A/B/activation/scheduler binding, and fake-only tests are implemented in the T15 worktree. The generation binding was live revalidated once in the Phase 1 retry above; the prior synthesis-truncation failure evidence remains unchanged. This is not a T15-wide completion or Phase 2/3 gate result.

Runtime/API follow-up keeps the same status boundary: canonical JSON+digest
roundtrip and fail-closed drift/tamper checks are fake-tested only. The separate
stop-smoke evidence and partial artifacts are recorded in the Phase 1 retry
document; no activation or always-on state change was made.

### T15 Phase 2 `model_comparison` live A/B (2026-08-26)

- Phase 2는 모델 호출 전에 중단되었다. fixed validation set과 Claude baseline은 각각 40건이고 sample order/correspondence 및 digest 검증은 통과했지만, `QualityGateService.create_gate()`가 고정 ID `20260817-20260823`를 DB에서 요구했다. 검증 DB의 유일한 imported run ID는 `20260817-20260823--20260824T090927.138116Z`여서 `QualityGateValidationError: quality gate run or policy is missing`가 재현되었다.
- Phase 2 gate/evaluation/pass A/pass B는 생성되지 않았고 모델 호출·quality metric·review는 0/미측정이다. 첫 실패 뒤 live 호출은 하지 않았으며, 동일 no-write 전검증 오류를 확인하는 재현 명령만 1회 수행했다. 상세 원인과 backup/hash는 [T15 Phase 2 model comparison 기록](../validation-runs/20260826-t15-phase2-model-comparison.md)에 있다.
- 종료 상태는 Alembic `0005_generation_config_binding`, seed policy `activation_candidate`, always-on `false`, `BIDOPS_SCHEDULER_ENABLED=false`, quality gate/evaluation/review 0이다. 이 상태는 Phase 2 blocker 기록이며 T15 전체 또는 Phase 3 완료를 의미하지 않는다.
