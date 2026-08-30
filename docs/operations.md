# 운영 절차

## 운영 기준선

- 운영 정본은 PostgreSQL 17의 `bidops` schema와 버전 관리가 켜진 MinIO 객체 저장소다.
- `docker-compose.t7.yml`이 웹, DB, 객체 저장소, 악성코드 검사, 문서 worker, 분석 worker의 기준 배포 파일이다.
- 루트 `docker-compose.yml`은 SQLite 이전 입력 스냅숏을 백업·검증하는 명시적 `ops` 명령만 제공한다. 애플리케이션 런타임으로 사용하지 않는다.
- 모든 T7 명령에는 전용 `COMPOSE_PROJECT_NAME`을 사용한다. 다른 worktree의 컨테이너와 volume을 중지하거나 삭제하지 않는다.
- 일상 운영에서 `docker compose down -v`, volume 삭제, 원본 객체 삭제를 사용하지 않는다.

## 현재 배포 차단 조건

현재 T7 stack은 개발·검증에는 사용할 수 있지만 다음 문제가 해결되기 전에는 운영 배포 후보가 아니다.

- runtime image에 회사 profile 자료가 포함된다.
- profile snapshots·sections·unknowns API가 filesystem source/reference, raw profile block, 가공되지 않은 parse error를 반환할 수 있다.
- 개발용 hosted Codex 심층 검토 경로가 RFP와 회사 profile slice를 외부로 보낼 수 있다.
- PostgreSQL과 MinIO port가 host 전체 interface에 publish될 수 있다.
- MinIO versioning 활성화 실패를 bootstrap이 무시한다.
- analysis worker DB role이 업무 table 전체 DML 권한을 가진다.
- 객체 restore가 source와 target version ID를 연결하지 못하고 active manifest 생성·완전성 검사가 없다.
- legacy notice attachment upload가 quarantine·ClamAV·MinIO를 우회하고 응답에 로컬 `stored_path`를 노출한다.

개발 검증에서도 hosted Codex reference overlay, legacy notice attachment upload, profile snapshots·sections·unknowns route를 사용하지 않는다. 회사 profile이 들어간 image를 registry에 push·export하지 않으며 로컬 build cache의 접근 범위를 제한한다. 나머지 stack 기동은 폐기 가능한 데이터와 host firewall로 격리한 환경에서만 수행한다.

## 사전 조건

- Docker Engine과 Docker Compose가 필요하다. host 검증에는 Python 3.12+, Node 22+, npm 10+가 필요하다.
- `.env.example`을 `.env`로 복사하고 실제 비밀은 외부 secret manager에서 주입한다. `.env`는 커밋하지 않는다.
- `.env`는 모든 compose 파일이 공유하는 공통 파일이다. overlay 전용 값은 `env/<overlay>.env`에 두고 추가 `--env-file`로 넘긴다. `env/*.env.example`을 같은 이름의 `.env`로 복사해 사용하며 실제 파일은 커밋하지 않는다.
- `BIDOPS_UID`와 `BIDOPS_GID`는 0이 아닌 host 계정과 맞춘다.
- PostgreSQL owner, migrate, app, worker, read-only backup 계정의 비밀번호를 서로 다르게 설정한다.
- MinIO root와 source, structure write/read, quarantine, model-response 자격증명을 용도별로 분리한다.
- 심층 검토 전에 승인된 profile version과 analysis policy version을 채운다. 빈 값이면 deep-review 생성이 fail closed하는 것이 정상이다.
- 사설 vLLM을 사용할 때 endpoint의 literal IP와 allowlist를 일치시키고 host firewall에서 해당 IP와 port 외 egress를 차단한다.

## 최초 기동

```bash
cp .env.example .env
cp env/vllm.env.example env/vllm.env
export COMPOSE_PROJECT_NAME=bidops-deep-review-t7
docker compose -f docker-compose.t7.yml build
docker compose -f docker-compose.t7.yml up -d postgres minio clamav
./scripts/init-runtime.sh
docker compose --env-file .env --env-file env/vllm.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  up -d web document-worker analysis-worker
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

`--env-file`을 명시하면 기본 `.env` 자동 로드가 꺼지므로 공통 파일과 overlay 파일을 함께 넘긴다. overlay 없이 기동할 때는 `--env-file` 없이 `.env`가 자동 로드된다.

`scripts/init-runtime.sh`는 DB 역할 초기화, Alembic migration, MinIO 버킷·정책 초기화를 순서대로 실행한다. 앱 startup은 이 작업을 대신하지 않는다. `bidops-source`, `bidops-structure`, `bidops-quarantine`, `bidops-model-response` 버킷은 versioning과 최소 권한 정책을 유지한다.

사설 vLLM 없이 웹과 문서 준비만 확인할 때는 remote-vLLM overlay를 빼고 기동할 수 있다. 이 경우 분석 worker가 모델 단계에서 실패하는 것은 정상이며 성공으로 보정하지 않는다.

판정 파이프라인이 승인된 Ollama와 나라장터 OpenAPI에 접근해야 할 때만 다음 overlay를 추가한다.

```bash
cp env/screening.env.example env/screening.env   # BIDOPS_OLLAMA_BASE_URL을 채운다
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  --env-file .env --env-file env/screening.env \
  -f docker-compose.t7.yml -f docker-compose.t7.screening.yml \
  up -d web
```

overlay 추가만으로 egress가 안전해지지 않는다. host firewall의 목적지 제한과 실제 endpoint 승인을 함께 확인한다. endpoint나 allowlist가 비어 있으면 overlay가 기동 전에 fail closed한다.

사전규격 첨부 바이트 취득은 기본 비활성이다. 메타데이터는 독립 수집 회차에 전량 보존하고,
`SW사업대상=Y` 또는 추적 중인 발주계획으로 연결된 사전규격만 backend worker가 다운로드한다.
연결 조건은 `docs/business-rules.md`의 규칙을 따르며, 사람이 추적 상태를 고른 뒤 큐가 재평가된다.
사용 전에 host firewall에서 승인된 G2B 목적지만 허용하고 별도 env 파일에 allowlist를 채운다.

```bash
cp env/prespec-attachment.env.example env/prespec-attachment.env
# env/prespec-attachment.env의 BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS를 승인된 값으로 채운다.
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  --env-file .env --env-file env/prespec-attachment.env \
  -f docker-compose.t7.yml -f docker-compose.t7.prespec-attachment.yml \
  up -d prespec-attachment-worker
```

`BIDOPS_G2B_ATTACHMENT_ENABLED`는 overlay에서만 `true`로 덮고, overlay를 사용하지 않으면
기본값 `false`로 connector와 worker가 idle한다. `BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS`가
비어 있으면 fail closed한다. `BIDOPS_G2B_ATTACHMENT_TIMEOUT_SECONDS`의 기본값은 30초이며,
worker 설정은 `BIDOPS_PRESPEC_ATTACHMENT_WORKER_CONCURRENCY=1`,
`BIDOPS_PRESPEC_ATTACHMENT_WORKER_POLL_SECONDS=5`,
`BIDOPS_PRESPEC_ATTACHMENT_LEASE_SECONDS=120`이다.

worker를 직접 실행할 때는 migration·MinIO·ClamAV가 준비된 backend 환경에서 다음 명령을 쓴다.

```bash
python -m app.workers.prespec_attachment
python -m app.workers.prespec_attachment --once
```

첨부 URL의 수명은 아직 측정하지 않았으므로 `unknown`으로 유지한다. URL·object key·로컬
경로·자격증명은 worker 상태와 감사 상세에 저장하지 않는다.

모델 없이 상태 전이와 저장·검증 계보만 확인할 때는 mock override를 사용한다. 이 override는 전용 값을 파일 안에 리터럴로 선언하므로 추가 env 파일이 필요 없고 어떤 egress도 열지 않는다.

```bash
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  -f docker-compose.t7.yml -f docker-compose.t7.mock-reference.yml \
  up -d web document-worker analysis-worker
```

이 override는 두 단계를 모두 덮는다. 심층 검토는 `BIDOPS_ANALYSIS_PROVIDER=mock`,
1차 분류는 `BIDOPS_SCREENING_PROVIDER=mock`이다. 둘 다 `BIDOPS_REFERENCE_WORKFLOW_MODE`가
참이 아니면 기동 전에 설정 검증에서 거부된다.

mock 결과의 provider/model 계보는 `mock-analysis` / `bidops-deterministic-mock-v1`로 고정되고 policy quality는 `reference_workflow_unmeasured`, `deployable=false`다. 사업 판단이나 모델 품질 평가 근거로 사용하지 않는다.

1차 분류 mock은 `ScreeningAttempt.model_digest`가 mock 전용 상수
(`app/screening/mock_transport.py`의 `MOCK_MODEL_DIGEST`)로 남는다. 저장된 판정이
실제 모델 산출인지 mock인지는 이 값으로 판별한다. `model_name`은 `OllamaClient`가
허용 모델만 받으므로 구별에 쓸 수 없다.

## 환경 파일 배치

| 파일 | 소비하는 compose | 담는 값 |
|---|---|---|
| `.env` | `docker-compose.t7.yml`, `docker-compose.yml` | 프로세스 정체성, 로그, DB·MinIO 자격증명, 암호화 키, port, 승인 profile/policy 참조 |
| `env/vllm.env` | `docker-compose.t7.remote-vllm.yml` | `BIDOPS_VLLM_BASE_URL`, `BIDOPS_VLLM_ALLOWED_HOSTS`, `BIDOPS_VLLM_API_KEY` |
| `env/screening.env` | `docker-compose.t7.screening.yml` | `BIDOPS_OLLAMA_BASE_URL`, `BIDOPS_OLLAMA_MODEL` |
| `env/codex.env` | `docker-compose.t7.codex-reference.yml` | 승인 notice ID, host Codex 바이너리·auth 경로 (개발 검증 한정) |
| 없음 | `docker-compose.t7.mock-reference.yml` | 전용 값을 override 파일 안에 리터럴로 선언한다 |

overlay 전용 값을 `.env`에 두지 않는다. `.env`에 두면 overlay를 붙이지 않은 기동에서도 endpoint가 주입되어 fail-closed 기본값이 흐려진다.

## 상태 확인과 중지

```bash
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml ps
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml logs --since=30m web analysis-worker
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml stop web analysis-worker document-worker
```

로그에는 prompt, 모델 응답, 회사자료, 첨부 본문, 자격증명, URL 쿼리 문자열이 없어야 한다. traceback은 기본 비활성이고 안전한 식별자와 오류 분류만 확인한다.

## 설정 범주

| 범주 | 주요 설정 | 운영 규칙 |
|---|---|---|
| 프로세스 | `BIDOPS_UID`, `BIDOPS_GID`, `BIDOPS_LOG_LEVEL`, `BIDOPS_LOG_TRACEBACK` | non-root, 기본 WARNING, 비밀 없는 로그 |
| 나라장터 | `BIDOPS_G2B_API_KEY`, `BIDOPS_G2B_ATTACHMENT_ENABLED`, `BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS`, `BIDOPS_G2B_ATTACHMENT_TIMEOUT_SECONDS` | API key는 수집 실행 때만 주입. 첨부 취득은 기본 false, 승인 host allowlist가 없으면 fail closed |
| 로컬 판정 | `BIDOPS_OLLAMA_BASE_URL`, `BIDOPS_OLLAMA_MODEL`, context/output/timeout, concurrency/heartbeat/stale | 승인 endpoint, digest 고정, concurrency 1 |
| 일정·첨부 worker | `BIDOPS_SCHEDULER_ENABLED`, daily/weekly 시간, `BIDOPS_PRESPEC_ENABLED`, `BIDOPS_PRESPEC_ATTACHMENT_WORKER_CONCURRENCY`, `BIDOPS_PRESPEC_ATTACHMENT_WORKER_POLL_SECONDS`, `BIDOPS_PRESPEC_ATTACHMENT_LEASE_SECONDS` | 기본 false/worker 1·5초·120초, 품질 승인·운영자 확인·host firewall 뒤 활성화 |
| DB | owner/migrate/app/worker/ro-backup 비밀번호, port | 역할 분리, migration은 전용 계정 |
| 객체 저장소 | MinIO root와 namespace별 access/secret, endpoint, secure flag | 용도별 최소 권한, versioning 유지 |
| 문서 검사 | ClamAV host/port/timeout | clean scan envelope 없이는 준비 단계 진행 금지 |
| 심층 모델 | vLLM base URL, allowed hosts, model, API key, response encryption key/ref | 승인된 사설 endpoint만, 응답 암호화 |
| 활성 버전 | active profile version, active analysis policy version | 불변 ID, 빈 값이면 fail closed |
| 외부 참조 | OpenAI·Codex exec enabled, approved notice IDs, reference workflow mode | 현재 Codex deep-review 경로는 사용 금지. 향후 발주계획 전용 projection에서만 공개 plan metadata+최소 승인 요약을 preview·건별 승인 후 전송 |

## 발주계획 선별 실험 운영

제품 선별기를 구현하기 전에 동일한 3일 입력을 동결해 네 방식을 비교한다.

1. 일반용역과 기술용역을 수집하고 발주계획 단계에서는 SW사업대상 여부로 선필터하지 않는다.
2. 원본 응답, 정규화 전체 레코드, 조회 조건, 페이지, source hash, 최초 수집 시각을 보존한다.
3. 키워드 규칙, ColBERT, Qwen3.8:27B, GPT Luna xhigh를 같은 모집단에 실행한다.
4. GPT Luna에는 공개 발주계획 메타데이터와 별도 승인된 회사 역량 요약만 전송한다. 전송 전에 담당자가 payload를 확인하고 승인 기록을 남긴다.
5. Sol xhigh 결과는 silver reference와 이견 탐색에만 사용한다. 최종 relevance·우선순위 정답은 사람이 판정한다.
6. 방식별 recall, precision, 검토량, 중요 누락, 순위 품질, 비용, 지연, 재현성을 보고서에 기록한다.
7. 선택 방식 또는 조합과 운영 threshold를 승인한 뒤에만 제품 구현과 자동 일정 활성화를 진행한다.

개발계정의 일일 1,000회 요청 한도는 레코드 수가 아니라 실제 HTTP 요청 수로 관리한다. endpoint·페이지·재시도별 사용량을 세고 같은 응답은 회차 cache로 재사용한다. 초기 방어선은 700회 경고, 900회에서 신규 요청 중지다. 운영 전 실제 관측치와 필요한 endpoint 수를 근거로 활용사례를 등록해 증액을 신청한다.

## 목표 수집 일정

발주계획 수집기는 아래 명령으로 명시적으로 실행한다. 스케줄러와 always-on은 기본 비활성이고,
운영자가 회차 디렉터리와 API key 주입을 확인한 뒤 실행한다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --output-dir data/runs/order-plans-$(date +%Y%m%d) \
  --days 21

# 날짜를 고정하는 재현·재조회 모드 (to-date는 제외)
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --output-dir data/runs/order-plans-20260808-20260829
```

기존 raw page를 다시 정규화할 때는 새 회차 디렉터리를 지정한다. 이 모드는 API를 호출하지
않는다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --from-raw data/runs/order-plans-20260808-20260829/raw \
  --output-dir data/runs/order-plans-20260808-20260829-reclassified
```

발주계획과 사전규격 수집은 공고 수집과 별도 회차로 유지한다. 아래 일정은 현재 자동 활성화된
스케줄이 아니라 운영 목표다.

- 발주계획 수집: 매일, 일반용역·기술용역, SW사업대상 선필터 없음.
- 발주계획 사람 검토: 월요일과 목요일. 수집 회차는 검토 일정과 독립적으로 보존한다.
- 사전규격 수집: 매일, 일반용역·기술용역 메타데이터 전량. `SW사업대상`은 필터가 아니라 저장·표시 값이다.
- 사전규격 첨부 문서 다운로드: `SW사업대상=Y` 또는 추적 중인 발주계획 연결로 자격이 생긴 건만 수행한다. 자격이 뒤늦게 생기므로 재평가 큐를 사용한다.
- 사전규격 1차선별: 저비용 판정 후 사람 확인. 승인된 건만 심층 검토 실행.
- 입찰 추적: `계속 추적` 기회에 대해 신규 공고와 정정공고를 확인하고 사전규격 대비 중요 변경을 계산한다.
- 각 단계는 자동 연결 실행과 수동 단독 실행·재시도를 같은 실행 ID, artifact, 상태 전이 규칙으로 제공한다.

## 검증

소스와 fake 모델 검증은 live API key나 model endpoint 없이 실행한다.

```bash
./run-tests.sh
./web/run-web-tests.sh
cd web/frontend && npm run test:visual
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose -f docker-compose.t7.yml build
```

`web/run-web-tests.sh`는 임시 PostgreSQL 17에서 migration을 수행하고, 격리 DB의 backend 테스트와 frontend production build를 실행한다. Docker가 없으면 `BIDOPS_TEST_POSTGRES_URL`에 폐기 가능한 PostgreSQL 관리 URL을 제공한다. 운영 DB URL을 사용하지 않는다.

live Ollama 또는 vLLM smoke는 운영자가 명시한 한 번의 명령과 대상에서만 수행한다. safety 환경변수가 true라는 사실만으로 실행하지 않는다. 결과에는 모델명, digest 또는 승인된 immutable reference, 정책·프로필 버전, 입력 hash, 시작·종료 시각을 남긴다.

## 백업

PostgreSQL 백업은 현재 Compose 계약상 host의 `./backups/t7`에 쓴다. 실행 뒤 dump를 승인된 외부 보존 위치로 복사하고 보존 위치의 접근권한과 hash를 기록한다.

```bash
COMPOSE_PROJECT_NAME=bidops-deep-review-t7 docker compose \
  -f docker-compose.t7.yml --profile backup run --rm ro-backup
```

`scripts/backup-postgres.sh`는 timestamp가 붙은 custom-format dump를 만들고 기존 백업을 삭제하지 않는다. 4시간 RPO가 필요하면 이 스크립트와 별도로 WAL 보관을 구성하고 복구 시험으로 확인한다.

객체 백업은 버전별 파일과 `object-versions.tsv`를 만든다. 실행 환경에 `mc`, `MINIO_ALIAS`, `OBJECT_BACKUP_DIR`를 제공한다.

```bash
./scripts/backup-objects.sh
```

DB dump와 객체 manifest는 같은 복구 지점을 식별할 수 있게 함께 보존한다. 암호화 key reference와 실제 key의 백업 정책은 분리하고 접근을 감사한다.

## 복구

현재 restore script는 source version ID와 target version ID를 연결하지 못하고 DB active reference에서 완전한 manifest를 만들지 않으므로 복구 가능한 운영 도구가 아니다. 아래 순서와 환경변수는 수정 후 지켜야 할 목표 계약이며, 현재 script를 가치 있는 snapshot이나 운영 전환에 사용하지 않는다.

복구는 기존 운영 대상 위가 아니라 빈 PostgreSQL과 빈 MinIO 대상에서 수행한다.

1. 복구 대상과 네트워크를 격리한다.
2. `OBJECT_BACKUP_DIR`, `RESTORE_MINIO_ALIAS`로 버전별 객체를 먼저 복사한다.
3. `DUMP_FILE`을 빈 PostgreSQL에 `pg_restore`한다.
4. `ACTIVE_HASH_MANIFEST`와 복구 객체의 hash를 대조한다.
5. FK, Alembic head, 핵심 row 수, active document·model response 참조를 검사한다.
6. API read-only smoke와 대표 보고서 재현을 확인한 뒤에만 전환 여부를 사람이 결정한다.

```bash
OBJECT_BACKUP_DIR=/approved/objects \
DUMP_FILE=/approved/db.dump \
ACTIVE_HASH_MANIFEST=/approved/active-hashes.tsv \
RESTORE_MINIO_ALIAS=restore \
BIDOPS_DATABASE_URL='postgresql+psycopg://...' \
BIDOPS_DATABASE_HOST=restore-db \
BIDOPS_DATABASE_USER=restore-user \
BIDOPS_DATABASE_PASSWORD='injected-secret' \
./scripts/restore.sh
```

현재 명령은 source volume 삭제나 `dropdb`는 수행하지 않지만 target version mapping과 active manifest 검증이 보완되기 전에는 성공적인 복구를 보장하지 않는다.

## 장애 대응

- 첨부 경로 이탈, 비밀·회사자료 노출, 승인 없는 외부 모델 전송, 기존 회차·리뷰 덮어쓰기, 원문과 다른 근거의 검증 통과가 발견되면 관련 worker와 egress를 즉시 중지하고 상태를 보존한다.
- 중단된 판정은 자동 resume하지 않는다. heartbeat와 마지막 stage를 확인하고 새 실행 ID로 사람이 재시작한다.
- 부분 산출물은 성공 subset과 failure artifact를 함께 보존한다. 유효 결과가 없으면 성공 run을 발행하지 않는다.
- 모델 endpoint 장애가 로컬 판정에서 hosted OpenAI 자동 fallback을 일으키면 안 된다. 외부 재분석은 별도 승인 실행으로만 만든다.
- `document-worker`가 `PermissionError: '/scratch/inbox'`로 즉시 종료하면 image가 `/scratch`를 만들기 전에 생성된 `document-scratch` volume이 root 소유로 남은 것이다. 스택을 중지하고 그 volume만 삭제한 뒤 다시 올린다. 이 volume은 변환 중인 handoff만 담으므로 보존 대상이 아니다.
