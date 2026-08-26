# 운영 절차 (Lean v1)

## 권위 런타임

PostgreSQL 17.11의 `bidops` schema가 live canonical DB다. 기존 SQLite는 일회성 migration input 또는 격리 테스트에만 사용하며, 애플리케이션은 SQLite URL로 기동하지 않는다. Lean v1은 기존 13개와 신규 25개, 총 38개 application table을 유지하고 `alembic_version`은 migration DB에만 추가된다.

이 worktree의 Compose는 반드시 명시적인 프로젝트 이름과 T7 파일로 실행한다. main worktree의 Compose·volume을 중지하거나 삭제하지 않는다.

```bash
cd /path/to/bidops-agent
cp .env.example .env  # secret manager가 주입한 값으로만 채운다.
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml build
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml up -d postgres minio clamav
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 ./scripts/init-runtime.sh
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  up -d web document-worker analysis-worker
```

`postgres`는 owner/migrate/app/worker/ro_backup 역할을 분리하고, Compose bootstrap은 MinIO source/structure/quarantine/model-response 버킷·버전닝·정책을 만든다. FastAPI web은 목적별 MinIO credential로 원문·구조를 저장하고 ClamAV clean scan envelope를 원문 hash에 결합해 scratch request를 만들며, credential-free `document-worker` 두 replica는 `network_mode: none`으로 scratch만 처리한다. analysis worker는 concurrency 1로 immutable structure를 읽고, 승인된 원격 vLLM OpenAI-compatible API를 호출해 암호화된 model response만 쓴다. OpenAI Python SDK는 protocol client로만 사용하며 OpenAI hosted API와 Langfuse는 비활성이다.

승인된 원격 vLLM IP를 쓰는 인수 환경은 `docker-compose.t7.remote-vllm.yml`을 추가한다. endpoint와 literal IP allowlist를 외부 env로 주입하고 host firewall에서 그 IP/port 외 egress를 차단한다. 기본 Compose와 `document-worker` network 경계는 바뀌지 않는다.

일상 운영에서 `docker compose down -v`, volume 삭제, host 실데이터 bind mount를 사용하지 않는다. T7 volume은 프로젝트 이름으로 격리되며, 삭제가 필요한 경우에도 별도 승인과 복구 확인이 먼저다.

## 검증

단계 B의 document bundle부터 단계 C의 실제 Qwen machine report까지 연속 인수하는 절차와 증적 형식은 [단계 B→C 연속 인수 테스트](e2e-bc-acceptance.md)를 따른다. 실제 모델·대표 원문·사람 gold가 없는 환경에서는 코드 계약 테스트만 통과한 것으로 기록하고 Qwen 품질 또는 전체 E2E 통과로 표시하지 않는다.

호스트에 backend venv/pytest가 없으면 T7 이미지에서 임시 테스트한다.

```bash
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml run --rm web pytest -q
cd /path/to/bidops-agent
./run-tests.sh
./web/run-web-tests.sh
```

T7 이미지를 만든 뒤에는 위 검증을 현재 worktree image로 반복한다. 실제 snapshot/restore가 제공되지 않은 환경에서는 해당 검사를 통과로 표시하지 않는다. MinIO object backup/restore/hash scripts are wired for version-aware copy, but an actual user-provided snapshot and pre-prod restore drill remain required evidence. PostgreSQL clean migration, downgrade 정책, SQLite reconciliation, HWP/문서 안전성, Qwen fence/chunk/retry/merge, immutable report, API/table/stage 수와 frontend 접근성 fixture를 각각 기록한다.

## 백업·복구 목표와 실행

RPO는 4시간, RTO는 8시간이다. 매일 full PostgreSQL custom dump와 continuous WAL archive를 수행하고, object store는 version-aware copy를 4시간 이내 수행한다. 보존은 daily 14, weekly 8, monthly 6이다. `scripts/backup-postgres.sh`와 `scripts/backup-objects.sh`는 파일을 삭제하지 않는다.

복구 순서는 반드시 versioned object copy → 빈 pre-prod DB에 dump restore → active object hash와 DB 연결 검증이다.

```bash
RESTORE_MINIO_ALIAS=restore \
OBJECT_BACKUP_DIR=/external/restore/objects \
DUMP_FILE=/external/restore/bidops.dump \
ACTIVE_HASH_MANIFEST=/external/restore/active.tsv \
BIDOPS_DATABASE_URL='postgresql+psycopg://ro_backup:***@restore-db/bidops' \
./scripts/restore.sh
```

복구는 별도 pre-prod target에서 수행하며 운영 DB/volume을 drop하지 않는다. 사전 운영 복구 검증과 quarterly drill을 기록하고, 사용자 제공 snapshot이 없는 현재 환경에서는 실제 복구 성공을 주장하지 않는다.

## 장애 확인

| 증상 | 확인 |
|---|---|
| SQLite runtime error | `BIDOPS_DATABASE_URL`이 PostgreSQL 17인지 확인한다. SQLite URL로 우회하지 않는다. |
| profile unavailable | 컨테이너 `/app/docs/reference/company-profile.md`와 `BIDOPS_ROOT=/app`를 확인한다. |
| HWP converter unavailable | `document-worker` image에 Node 22와 pinned converter가 있는지, scratch request/result가 atomic인지 확인한다. worker network는 계속 none이어야 하며 web의 scanner clean envelope가 같은 원문 hash인지 확인한다. |
| object storage unavailable | MinIO endpoint 또는 해당 작업의 purpose credential을 확인한다. Production은 filesystem fallback 없이 fail fast하며, isolated pytest만 filesystem backend를 허용한다. |
| model invocation blocked | `BIDOPS_OPENAI_ENABLED=false`, `BIDOPS_VLLM_BASE_URL`·literal IP allowlist·API key와 `model-egress`를 확인한다. |
| 보고서/validation 불일치 | 해당 claim lease fence, stage 3 persist, materializer, finish audit 순서를 확인하고 수동 DB 수정하지 않는다. |
| API 오류 | `error.code`, `error.message`, `request_id`만 사용자에게 표시하고 내부 exception·경로·credential을 노출하지 않는다. |
