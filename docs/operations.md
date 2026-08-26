# 운영 절차

이 runbook은 SQLite를 사용하는 현재 compose/host 구현의 순서를 고정한다. 서비스 중지·backup·migration·seed는 웹 기동과 분리한다. container entrypoint와 앱 startup은 migrate, `create_all`, portal seed, policy seed를 자동 실행하지 않는다.

## 사전 조건

프로젝트 루트는 `bidops-agent/`다. Docker 방식은 Docker Engine/Compose, host 방식은 Python 3.12+, venv, Node 22+/npm 10+가 필요하다. 컨테이너는 root로 실행하지 않으며 `.env`의 `BIDOPS_UID`/`BIDOPS_GID`는 0이 아닌 host 사용자와 맞춰야 한다. `/app/data`, `/app/reports`, `/app/backups`, `/app/web/data`는 존재하고 non-root가 읽고 쓸 수 있어야 하며 skills/docs는 읽을 수 있어야 한다. entrypoint는 chown/chmod로 권한을 고치지 않고 권한 오류로 종료한다.

compose는 `data`와 `reports` bind mount, `/app/web/data`의 `bidops-web-data` named volume, `/app/backups`의 `bidops-backups` named volume을 사용한다. 백업 manifest와 DB 파일은 같은 backup volume에서 보존한다. `.env`, API key, run data와 첨부를 image/Git에 복사하지 않는다. compose의 고정 container 경로는 DB `/app/web/data/bidops.db`, attachment `/app/web/data/attachments`, report `/app/reports`, backup `/app/backups`다.

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

컨테이너 wrapper가 두 환경변수를 요구하며 Python `db_admin migrate --backup-manifest ... --confirm-service-stopped`로 위임한다. migrate는 manifest identity/digest/fingerprint, core row counts, FK/quick_check를 확인하고 temp DB에서 Alembic을 실행한 뒤 검증된 경우에만 live DB를 교체한다. 현재 head는 `0004_migration_audit`다. backup은 유지되며 자동 rollback하지 않는다.

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

visual 테스트는 host `cd web/frontend && npm run test:visual`의 webServer(빌드 후 preview, port 4173) 계약이다. 테스트는 `public/fonts/PretendardVariable.woff2`가 요청되고 적용될 때까지 기다리며 Google Fonts 요청이 없음을 확인한다. host에 `libnspr4/libnss3`가 없어 browser launch가 막히면 project root에서 다음처럼 동일 테스트를 Playwright image로 실행한다.

```bash
docker run --rm --network host --ipc=host --user 1000:1000 \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -v "$PWD:/work" \
  -v "$PWD/web/frontend/node_modules:/work/web/frontend/node_modules" \
  -w /work/web/frontend \
  mcr.microsoft.com/playwright:v1.62.1-noble npm run test:visual
```

기본 bridge 네트워크에서는 Vite preview의 localhost/`::1` bind와 readiness 확인 주소가 분리되어 timeout이 날 수 있다. 이 환경에서는 `--network host`를 포함해야 preview의 `127.0.0.1:4173` readiness가 맞는다. 위 exact image·mount·UID/GID·IPC 명령으로 390/768/1024/1440px의 12개 화면 대상과 핵심 동작을 검증한다. 스냅샷을 갱신할 때는 같은 명령의 `npm run test:visual`을 `npm run test:visual:update`로 바꾼다. 2026-08-26 독립 검토 blocker 수정본의 exact Docker 갱신·비갱신 실행은 각각 전체 172개 중 162 passed, 10 intentional skipped였고, 갱신 실행에서 dashboard 스냅샷 4개가 재생성됐다. 이 10건은 draft spec의 기존 넓은 화면 보조 흐름 5건이 390px와 768px 조건에서 각각 skip된 것이고, 새 동일 공고 초안 복귀 흐름은 네 폭에서 실행된다. host 직접 launch 제한은 환경에 `libnspr4/libnss3`가 없는 browser system libraries 문제일 뿐 제품 코드의 결과로 해석하지 않는다.

## 장애 시 확인

| 증상 | 확인 |
|---|---|
| web 시작 실패 | `docker compose logs web`; DB head/empty 상태, mount UID/GID, required dirs 확인 |
| migration 거부 | 서비스가 정말 중지됐는지, 실제 backup manifest path/digest/fingerprint와 `BIDOPS_CONFIRM_SERVICE_STOPPED=true` 확인 |
| verify 실패 | backup을 보존하고 자동 restore하지 말 것; 별도 복사본에서 검사 |
| queue가 멈춤 | execution heartbeat/stop/stale recovery와 Ollama exact model/digest 확인; 새 실행을 임의로 중복 생성하지 말 것 |
| 스케줄이 없음 | scheduler env cap와 DB always-on switch를 각각 확인; 두 값 모두 true여야 callback이 실제로 동작 |
| 화면이 비어 있음 | health가 아니라 `data/runs`/DB 적재와 API response를 확인; startup이 seed/migrate하지 않는 것이 정상 |
