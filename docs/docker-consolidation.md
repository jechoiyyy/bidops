# Docker 파일·컨테이너 정리 기록

기준일: 2026-09-04

`t7` 접두사를 걷어내고 Compose 파일·프로젝트·호스트 자원을 하나의 이름 체계로 정리한 기록이다.
`t7`은 과거 T-번호 작업 체계의 "T7: 심층 검토 런타임 통합"에서 온 꼬리표였고, 그 체계는 종료됐다.

## 1. 이름 변경 결과

| 이전 | 이후 | 역할 |
|---|---|---|
| `docker-compose.t7.yml` | `docker-compose.yml` | 애플리케이션 스택 정본. postgres·minio·clamav·web·worker 2종, profile `backup`·`ops` |
| `docker-compose.t7.remote-vllm.yml` | `docker-compose.remote-vllm.yml` | analysis-worker에만 사설 vLLM egress를 여는 overlay |
| `docker-compose.t7.screening.yml` | `docker-compose.screening.yml` | web에만 판정용 모델 egress를 여는 overlay |
| `docker-compose.t7.prespec-attachment.yml` | `docker-compose.prespec-attachment.yml` | 사전규격 첨부 worker와 G2B egress overlay |
| `docker-compose.t7.mock-reference.yml` | `docker-compose.mock-reference.yml` | 모델 없이 상태 전이만 확인하는 mock override |
| `docker-compose.yml` (SQLite ops) | `docker-compose.sqlite-ops.yml` | SQLite 이전 입력 스냅숏의 backup·migrate·verify·seed-policy `ops` 명령. **제거 후보** |
| `COMPOSE_PROJECT_NAME=bidops-deep-review-t7` | `bidops` | 문서와 `scripts/init-runtime.sh`의 기본값 |
| `./backups/t7` | `./backups/postgres` | `ro-backup` profile의 host dump 경로 |
| `tests/app/test_t7_runtime_contract.py` | `tests/app/test_runtime_contract.py` | Compose 파일 다섯 개의 서비스·network·fail-closed 계약 검사 |

기본 스택이 `docker-compose.yml`이 됐으므로 `-f`를 생략해도 같은 파일을 읽는다. 문서의 명령은
overlay와 짝을 맞추기 위해 `-f docker-compose.yml`을 그대로 적는다.

overlay 네 개는 각각 다른 egress network 하나만 열고 endpoint가 비면 기동 전에 fail closed한다.
하나의 파일로 합치면 `docs/security.md`의 목적별 외부 전송 경계가 흐려지므로 합치지 않았다.

코드 쪽은 심층 검토 인수 흐름의 식별자를 함께 바꿨다. `run_t7_e2e`→`run_agent_e2e`,
`T7ProjectionReader`→`AgentProjectionReader`, CLI 플래그 `--t7`→`--agent`, 산출 schema
`bidops.t7-e2e-plan.v1`→`bidops.agent-e2e-plan.v1`, `bidops.t7-e2e-result.v1`→`bidops.agent-e2e-result.v1`,
workflow 값 `t7-mock-reference`→`agent-mock-reference`. 이 문자열은 저장소 밖 소비자가 없다.

바꾸지 않은 것은 두 가지다. `docs/validation-runs/`는 시점별 실행 증거이므로 당시 파일 이름을 그대로 둔다.
백엔드 모듈 경계 주석의 "T7 1·2·3단계"는 2026-09-04 모듈 정리 작업의 이력 서술이라 그대로 둔다.

`docker-compose.sqlite-ops.yml`은 2026-08-31 PostgreSQL 이전 검증
(`docs/validation-runs/20260831-postgresql-migration-verification.md`) 이후 실행 기록이 없다.
SQLite 스냅숏을 다시 이전할 일이 없다고 판단하면 파일과 함께 `bidops_bidops-*`·`bidops-agent_bidops-*`
volume, `web/container-ops.sh`, README·operations·ARCHITECTURE·`.env.example`·AGENTS.md·CLAUDE.md의
언급을 같은 변경에서 지운다.

## 2. 호스트 자원 정리 결과

정리 전에는 Compose 프로젝트 3개(`bidops-e2e-t7` 실행 중, `bidops-mock-preview`·`bidops-mock-t7` 종료)와
volume만 남은 `bidops-deep-review-t7`, 중단된 pytest 세션이 남긴 PostgreSQL 컨테이너 5개, 익명 volume 209개,
종료 프로젝트 이미지 약 50개가 있었다.

| 자원 | 처리 |
|---|---|
| `bidops-e2e-t7` | web·worker를 멈춘 뒤 named volume 6개를 `bidops_*`로 복제하고, 새 프로젝트가 정상 기동한 것을 확인한 뒤 `down -v --rmi local`로 제거 |
| `bidops-mock-preview`, `bidops-mock-t7` | `down -v --rmi local`로 제거 |
| `bidops-deep-review-t7` volume 6개 | DB에 발주계획 625건(2026-08-27~30 구 회차)만 있고 공고·심층 검토는 0건이어서 제거 |
| `bidops-pytest-pg-*` 5개 | pytest가 돌고 있지 않은 것을 확인하고 제거 |
| 익명 volume 209개 | `docker volume prune` |
| 종료 프로젝트 이미지 (`bidops-mock-*`, `bidops-e2e-t7-*`, `bidops-deep-review-*`, `bidops-agent-e2e-*`, `bidops-ingest-review-*`, `bidops-step-*`, `bidops-review:local`, `bidops-admin:local`, `bidops-a6-ops`) | `docker rmi` |
| 빌드 캐시 | 24시간보다 오래된 항목만 `docker builder prune --filter until=24h` |

건드리지 않은 것: `wt1-*` 이미지(오늘 빌드된 다른 worktree), `mvtest-minio` 컨테이너,
`docker_database_dev`·`docker_redis_dev` volume과 `docker-dev_*`·`ft-*`·`hwp-rs-runtime`·`ollama` 이미지.
이 저장소 밖 작업으로 보이며 담당자가 확인한다. `bidops_bidops-*`·`bidops-agent_bidops-*` volume은
SQLite ops 파일의 결정과 함께 처리한다.

정리 뒤 `docker system df`는 이미지 34개 17.6GB, 컨테이너 11개, volume 13개 313MB, 빌드 캐시 22.2GB다.
정리 전에는 이미지 79개 22.9GB, 컨테이너 36개, volume 231개 11.6GB, 빌드 캐시 23.8GB였다.

## 3. 현재 실행 상태

```bash
docker compose -p bidops --env-file .env --env-file .dryforge/c2-e2e/vllm.env \
  -f docker-compose.yml -f docker-compose.remote-vllm.yml -f .dryforge/c2-e2e/overlay.yml \
  up -d web document-worker analysis-worker
```

- 컨테이너 이름은 `bidops-web-1`, `bidops-postgres-1`처럼 `bidops-` 접두사다. web은 host 18787.
- 복제한 volume으로 기동했으므로 발주계획 1,040건, 사업기회 1,040건, C-2 실행 4회, screening 결과 2,080건이
  그대로 있다. `/api/order-plans`·`/api/opportunities` total과 DB count가 일치했고, headless 브라우저에서
  대시보드·`/order-plans`·`/opportunities`·`/runs`가 콘솔 오류 없이 렌더링됐다.
- `.dryforge/c2-e2e/overlay.yml`은 여전히 필요하다. 기본 스택의 network가 전부 `internal: true`라 host에
  18787을 publish하려면 non-internal network 하나가 있어야 한다(`docs/tracking/findings.md`의 publish port 항목).
  이 overlay는 gitignore 대상이며 운영 활성화 근거가 아니다.

## 4. 검증

- `tests/app/test_runtime_contract.py`, `test_acceptance_clis.py`, `deep_review/test_bc_e2e.py`,
  `test_module_boundaries.py`, `test_static_frontend.py`: 60 passed, 1 failed.
- 실패 1건 `test_web_test_entry_point_runs_every_declared_gate`는 이 변경과 무관하다. 커밋 `7a550ad`가
  `web/run-web-tests.sh`를 `npm run test:screens`로 바꿨는데 테스트는 아직 `npm run test:visual`을
  기대한다. HEAD에서 그대로 재현된다.
- `docker compose ... config -q` 통과, `/api/health` ok.
