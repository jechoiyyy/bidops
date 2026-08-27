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

---

## 판정 런타임 runbook

live canonical DB는 PostgreSQL 17이다. 아래 「권위 런타임」이 기동 절차를 정하고, 이어지는 판정 런타임 runbook이 중지·backup·migration·seed·health·live smoke의 순서를 고정한다. container entrypoint와 앱 startup은 migrate, `create_all`, portal seed, policy seed를 자동 실행하지 않는다.

`docker-compose.yml`의 `ops` profile에 있는 `db-backup`·`db-verify`는 이제 SQLite migration 입력 스냅숏 전용 도구다. PostgreSQL 정본의 backup·restore는 `scripts/backup-postgres.sh`, `scripts/backup-objects.sh`, `scripts/restore.sh`가 담당한다.

## 사전 조건

프로젝트 루트는 `bidops-agent/`다. Docker 방식은 Docker Engine/Compose, host 방식은 Python 3.12+, venv, Node 22+/npm 10+가 필요하다. 컨테이너는 root로 실행하지 않으며 `.env`의 `BIDOPS_UID`/`BIDOPS_GID`는 0이 아닌 host 사용자와 맞춰야 한다. `/app/data`, `/app/reports`, `/app/backups`, `/app/web/data`는 존재하고 non-root가 읽고 쓸 수 있어야 하며 skills/docs는 읽을 수 있어야 한다. entrypoint는 chown/chmod로 권한을 고치지 않고 권한 오류로 종료한다.

compose는 `data`와 `reports` bind mount, `/app/web/data`의 `bidops-web-data` named volume, `/app/backups`의 `bidops-backups` named volume을 사용한다. 백업 manifest와 DB 파일은 같은 backup volume에서 보존한다. `.env`, API key, run data와 첨부를 image/Git에 복사하지 않는다. compose의 고정 container 경로는 attachment `/app/web/data/attachments`, report `/app/reports`, backup `/app/backups`다. `/app/web/data/bidops.db`는 정본이 아니라 migration 입력 스냅숏 경로다.

판정 generation budget은 `.env`의 `BIDOPS_OLLAMA_MAX_OUTPUT_TOKENS`(기본 2048)와 `BIDOPS_OLLAMA_SYNTHESIS_MAX_OUTPUT_TOKENS`(기본 4096)에서 읽지만 실행 생성 시 canonical frozen config로 한 번만 저장한다. context 기본값은 16384이며 synthesis budget은 context를 넘을 수 없다. migration `0003_screening_runtime_pg`은 canonical JSON/digest 계산을 `bidops.generation_config_canonical_json`·`bidops.generation_config_digest` plpgsql 함수로 제공하고, config 변경 및 quality A/B mismatch를 plpgsql trigger로 거부한다. live 재검증은 아직 pending이다.

앱이 읽는 경로 설정은 `BIDOPS_ROOT`(호환 alias `BIDOPS_PROJECT_ROOT`), `BIDOPS_DATA_DIR`, `BIDOPS_ATTACHMENTS_DIR`(호환 alias `BIDOPS_ATTACHMENT_DIR`), `BIDOPS_DATABASE_URL`이다. reports는 별도 directory 환경변수 없이 project root의 `reports` 경로를 사용한다. backup directory도 별도 directory 환경변수 없이 compose의 `/app/backups` named volume을 사용한다. compose에서 backup 관련 설정으로 지원되는 것은 `BIDOPS_BACKUP_OUTPUT`(backup file path)과 `BIDOPS_BACKUP_MANIFEST`(migrate manifest path)다.

## 표준 Docker 순서

아래 `<manifest>`는 backup 단계에서 출력된 실제 manifest 파일명으로 대체한다. `down -v`는 사용하지 않는다.

### 1. 서비스 중지

```bash
cd /path/to/bidops-agent
docker compose down
```

기존 web/worker가 완전히 멈춘 것을 확인한 뒤에만 다음 단계로 간다. 일반 `down`은 named volume을 보존한다.

### 2. DB backup 및 manifest 보존

```bash
docker compose --profile ops run --rm db-backup
```

기본 출력은 `/app/backups/bidops-<UTC>.db`와 `.manifest.json`이다. 다른 이름이 필요하면 `.env`의 `BIDOPS_BACKUP_OUTPUT`을 명시한다. manifest schema는 `bidops.sqlite-backup.v1`이며 source/backup path, SHA-256, logical snapshot fingerprint, UTC `created_at`을 포함한다. 운영 기록에 DB와 manifest를 모두 보존한다.

### 3. 명시적 migration

```bash
export BIDOPS_CONFIRM_SERVICE_STOPPED=true
export BIDOPS_BACKUP_MANIFEST=/app/backups/<manifest>.manifest.json
docker compose --profile ops run --rm db-migrate
```

컨테이너 wrapper가 두 환경변수를 요구하며 Python `db_admin migrate --backup-manifest ... --confirm-service-stopped`로 위임한다. migrate는 manifest identity/digest/fingerprint, core row counts, FK/quick_check를 확인하고 temp DB에서 Alembic을 실행한 뒤 검증된 경우에만 live DB를 교체한다. 현재 head는 `0005_generation_config_binding`다. backup은 유지되며 자동 rollback하지 않는다.

### 4. DB verify

```bash
docker compose --profile ops run --rm db-verify
```

verify는 head revision, foreign-key check, SQLite quick check, `run/notice/judgment/review/attachment` core count를 확인한다. 실패하면 web을 올리지 않고 원인과 보존한 manifest를 조사한다.

fresh migration 뒤에는 `schedule_setting`과 disabled `always_on_state` 기본 singleton 및 deterministic migration audit event가 있고, `screening_policy`와 `agency_portal`은 0행이다. 따라서 다음 단계의 policy seed는 명시적으로 필요하며, portal 검색을 사용하려면 operator가 `/api/portals`로 기관 portal metadata를 등록해야 한다. startup/entrypoint는 어느 것도 자동 seed하지 않는다.

### 5. 명시적 policy seed

```bash
export BIDOPS_POLICY_SEED_ACTOR=<explicit-operator-or-bootstrap-actor>
docker compose --profile ops run --rm policy-seed
```

seed는 `policy seed-default --created-by <actor>`를 실행하고 `activation_candidate`를 만든다. 같은 digest에 대해서만 idempotent다. seed는 activation이나 always-on enable이 아니다. actor를 비워 실행하지 않는다.

### 6. web 시작 및 health

```bash
docker compose up -d web
curl -fsS http://127.0.0.1:8787/api/health
docker compose logs --tail=100 web
```

health의 기대 응답은 `{"status":"ok"}`다. health는 Ollama, scheduler, migration을 점검하지 않는다. DB가 empty/unversioned/stale이면 앱이 시작하지 않는 것이 정상적인 안전 동작이다. scheduler/always-on은 기본 false이며 worker만 시작할 수 있다.

### 7. 단 한 번의 live smoke

T14/T15는 operator direction 없이 live smoke, policy activation, always-on을 수행하지 않는다. 명시적으로 승인된 단 한 번의 smoke만 다음 safety marker와 explicit command를 함께 사용한다.

```bash
export BIDOPS_LIVE_OLLAMA_TEST=true
docker compose exec web python -m app.screening.cli run-one \
  --run-id <run_id> --notice-id <notice_id> \
  --policy-version <approved-policy-version> \
  --profile-source current --requested-by <explicit-actor> --wait
```

`BIDOPS_LIVE_OLLAMA_TEST=true`는 marker일 뿐 CLI가 marker를 검사해 자동으로 실행하는 스위치가 아니다. 명령·actor·대상·결과를 운영자가 기록하고, 같은 변경에서 추가 live smoke를 반복하지 않는다. live smoke가 필요 없으면 이 단계는 수행하지 않는다. fake CI는 live endpoint를 호출하지 않는다.

## Host equivalent

host에서는 먼저 uvicorn/worker 프로세스를 멈추고 같은 순서를 실행한다.

```bash
cd /path/to/bidops-agent/web/backend
.venv/bin/python -m app.db_admin backup --output /absolute/backup/bidops-<UTC>.db
.venv/bin/python -m app.db_admin migrate \
  --backup-manifest /absolute/backup/bidops-<UTC>.db.manifest.json \
  --confirm-service-stopped
.venv/bin/python -m app.db_admin verify
.venv/bin/python -m app.screening.policy seed-default --created-by <explicit-actor>
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8787
```

별도 터미널에서 `curl -fsS http://127.0.0.1:8787/api/health`를 확인하고, 명시적 live가 승인된 경우에만 다음처럼 marker와 command를 함께 쓴다.

```bash
cd /path/to/bidops-agent/web/backend
BIDOPS_LIVE_OLLAMA_TEST=true .venv/bin/python -m app.screening.cli run-one \
  --run-id <run_id> --notice-id <notice_id> \
  --policy-version <approved-policy-version> \
  --profile-source current --requested-by <explicit-actor> --wait
```

host의 `BIDOPS_ROOT`, `BIDOPS_DATA_DIR`, `BIDOPS_ATTACHMENTS_DIR`, `BIDOPS_DATABASE_URL`, Ollama endpoint가 실제 경로와 일치해야 한다. reports는 `<BIDOPS_ROOT>/reports`, backup은 `db_admin backup --output`의 명시적인 host 경로를 사용한다. `BIDOPS_BACKUP_OUTPUT`/`BIDOPS_BACKUP_MANIFEST`는 container ops wrapper 변수이며 host에서는 명령 인자를 사용한다. `BIDOPS_UID/GID`는 host equivalent에는 적용되지 않지만 파일 소유권을 별도로 확인한다.

## 복구와 restore

SQLite가 corrupt하거나 migration 검증이 실패하면 서비스를 계속 올리거나 자동 rollback하지 않는다. `db-backup`의 backup과 manifest를 보존하고 별도 경로에서 restore를 검증한 뒤, 운영자가 backup replacement 여부를 결정한다. restore는 수동 파일 교체 결정이며 애플리케이션·container·migration이 자동 실행하지 않는다. 결정 후에도 서비스 중지→교체→`db-verify`→web health 순서를 다시 따른다. `docker compose down -v`로 복구하지 않는다.

## 모델·baseline 안전성

모델은 exact `qwen3.8:27b`, `think=false`, `stream=false`다. endpoint unavailable/model identity mismatch는 실패이며 OpenAI fallback/BF16 fallback이 없다. `profile git:<40hex>`의 승인 commit·vendored baseline·Git 부재 시 허용 digest fallback 규칙은 [아키텍처](./architecture.md)의 단일 정본을 따른다. 모델 출력과 profile/prompt 원문을 로그·오류·audit에 넣지 않는다.

## Docker 빌드·visual 확인

일반 image build는 다음이다. frontend production build와 Python runtime을 multistage Dockerfile에서 함께 만든다. Python runtime은 `web/backend/requirements.lock`의 exact pinned transitive closure를 설치하며, `requirements.txt`의 범위 제약을 Docker 설치에 사용하지 않는다. 이미지에는 DB·`.env`·API key·run data를 넣지 않는다.

```bash
docker compose build
```

visual 테스트는 host `cd web/frontend && npm run test:visual`의 webServer(빌드 후 preview, port 4173) 계약이다. 테스트는 Google Fonts 요청을 차단하고 컨테이너에 설치된 `WenQuanYi Zen Hei`·`Liberation Mono` local fonts로 CSS 변수를 덮어써 remote font 상태에 따른 snapshot 변동을 막는다. host에 `libnspr4/libnss3`가 없어 browser launch가 막히면 project root에서 다음처럼 동일 테스트를 Playwright image로 실행한다.

```bash
docker run --rm --network host --ipc=host --user 1000:1000 \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -v "$PWD:/work" \
  -v "$PWD/web/frontend/node_modules:/work/web/frontend/node_modules" \
  -w /work/web/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble npm run test:visual
```

기본 bridge 네트워크에서는 Vite preview의 localhost/`::1` bind와 readiness 확인 주소가 분리되어 timeout이 날 수 있다. 이 환경에서는 `--network host`를 포함해야 preview의 `127.0.0.1:4173` readiness가 맞는다. 위 exact image·mount·UID/GID·IPC 명령으로 fresh Docker 실행 두 번에서 각각 98 passed, 10 intentional skipped가 관찰되었다. 10 skip은 draft spec의 mobile/tablet 너비 조건에 따른 의도된 skip이다. host 직접 launch 제한은 환경에 `libnspr4/libnss3`가 없는 browser system libraries 문제일 뿐 제품 코드의 결과로 해석하지 않는다. 시각 evidence는 [tracking/status](./tracking/status.md)에 실제 실행 결과만 기록한다.

## 장애 시 확인

| 증상 | 확인 |
|---|---|
| web 시작 실패 | `docker compose logs web`; DB head/empty 상태, mount UID/GID, required dirs 확인 |
| migration 거부 | 서비스가 정말 중지됐는지, 실제 backup manifest path/digest/fingerprint와 `BIDOPS_CONFIRM_SERVICE_STOPPED=true` 확인 |
| verify 실패 | backup을 보존하고 자동 restore하지 말 것; 별도 복사본에서 검사 |
| queue가 멈춤 | execution heartbeat/stop/stale recovery와 Ollama exact model/digest 확인; 새 실행을 임의로 중복 생성하지 말 것 |
| 스케줄이 없음 | scheduler env cap와 DB always-on switch를 각각 확인; 두 값 모두 true여야 callback이 실제로 동작 |
| 화면이 비어 있음 | health가 아니라 `data/runs`/DB 적재와 API response를 확인; startup이 seed/migrate하지 않는 것이 정상 |

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
