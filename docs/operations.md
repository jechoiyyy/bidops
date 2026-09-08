# 운영 절차

## 운영 기준선

- 운영 정본은 PostgreSQL 17의 `bidops` schema와 버전 관리가 켜진 MinIO 객체 저장소다.
- `docker-compose.yml`이 웹, DB, 객체 저장소, 악성코드 검사, 문서 worker, 분석 worker의 기준 배포 파일이다.
- `docker-compose.sqlite-ops.yml`은 SQLite 이전 입력 스냅숏을 백업·검증하는 명시적 `ops` 명령만 제공한다. 애플리케이션 런타임으로 사용하지 않는다.
- 모든 Compose 명령에는 전용 `COMPOSE_PROJECT_NAME`을 사용한다. 다른 worktree의 컨테이너와 volume을 중지하거나 삭제하지 않는다.
- 일상 운영에서 `docker compose down -v`, volume 삭제, 원본 객체 삭제를 사용하지 않는다.
- legacy notice attachment의 id 기반 다운로드 호환 사본은 `/app/web/data/attachments`에 있다. 같은 부모의 `/app/web/data/profile-snapshots`는 승인 프로필 projection이 읽는 artifact이므로 Compose named volume `web-data`가 `/app/web/data` 전체를 보존한다. 업로드는 quarantine·ClamAV 검사 후에만 등록된다.

## 현재 배포 차단 조건

**알려진 운영 배포 차단 조건은 2026-09-01에 전부 해소했다.** MinIO versioning은 bootstrap에서
fail-closed로 검증하고, PostgreSQL·MinIO API·console port는 `BIDOPS_ADMIN_BIND_HOST`
기본값 `127.0.0.1`로 loopback에만 publish한다.

아직 남은 것은 차단 조건이 아니라 운영 훈련이다. 실제 secret, MinIO allow/deny,
egress firewall, backup·restore를 **운영 환경에서** 한 번도 검증하지 않았다.

hosted 외부 모델 reference overlay는 제거됐고 개발 검증에서도 사용하지 않는다. 회사자료 host 입력을 registry에 push·export하지 않으며 로컬 build cache의 접근 범위를 제한한다. legacy notice attachment upload는 quarantine·ClamAV·MinIO 경계를 통과한 파일만 사용한다. 나머지 stack 기동은 폐기 가능한 데이터와 host firewall로 격리한 환경에서만 수행한다.

## 사전 조건

- Docker Engine과 Docker Compose가 필요하다. host 검증에는 Python 3.12+, Node 22+, npm 10+가 필요하다.
- `.env.example`을 `.env`로 복사하고 실제 비밀은 외부 secret manager에서 주입한다. `.env`는 커밋하지 않는다.
- `.env`는 모든 compose 파일이 공유하는 공통 파일이다. overlay 전용 값은 `env/<overlay>.env`에 두고 추가 `--env-file`로 넘긴다. `env/*.env.example`을 같은 이름의 `.env`로 복사해 사용하며 실제 파일은 커밋하지 않는다.
- `BIDOPS_UID`와 `BIDOPS_GID`는 0이 아닌 host 계정과 맞춘다.
- PostgreSQL owner, migrate, app, worker, read-only backup 계정의 비밀번호를 서로 다르게 설정한다.
- MinIO root와 source, structure write/read, quarantine, model-response 자격증명을 용도별로 분리한다.
- 심층 검토 전에 승인된 profile version과 analysis policy version을 채운다. 빈 값이면 deep-review 생성이 fail closed하는 것이 정상이다.
- 프로필 조회 화면은 승인된 profile snapshot에 고정된다. snapshot이 하나도 없으면 `/api/profile/sections`와 `/api/profile/unknowns`가 `503 profile_snapshot_unavailable`로 fail closed하는 것이 정상이다([ADR-0023](tracking/decisions/0023-company-profile-minimal-projection.md)). snapshot은 판정 실행이 만들므로 신규 배포에서는 회차 판정을 한 번 실행한 뒤에 프로필 화면을 사용한다.
- 사설 vLLM을 사용할 때 endpoint의 literal IP와 allowlist를 일치시키고 host firewall에서 해당 IP와 port 외 egress를 차단한다.

### 웹의 회사자료 입력 전제

`docker-compose.yml`의 `web` 서비스는 다음 세 파일을 host checkout에서 read-only로 주입한다. 세 파일은 build context와 runtime image에 없으므로 Compose로 웹 서비스를 실행할 때 반드시 현재 checkout에 regular file로 존재하고 읽을 수 있어야 한다.

```text
docs/reference/company-profile.md
docs/reference/company-performance-titles.tsv
web/backend/app/screening/baseline_company_profile.md
```

Docker/Compose는 bind source가 없는 경우 그 자리에 디렉터리를 만들 수 있다. 그러면 파일을 읽어야 하는 프로필 경계와 수집 subprocess가 regular file 대신 디렉터리를 받아 비정상적으로 실패한다. 기동 전에 다음을 확인한다.

```bash
test -f docs/reference/company-profile.md && test -r docs/reference/company-profile.md
test -f docs/reference/company-performance-titles.tsv && test -r docs/reference/company-performance-titles.tsv
test -f web/backend/app/screening/baseline_company_profile.md && test -r web/backend/app/screening/baseline_company_profile.md
```

프로필 baseline은 실행 시 주입된 파일을 기존 SHA-256 검증으로 확인한다. `skills/` 스크립트는 image에 남아 있어 계약상 fallback으로 제공되지만, 위 세 mount 없이 `docker run`만 실행하면 프로필 관련 경로와 수집 subprocess를 사용할 수 없다. 이 경로는 의도된 보안 경계이므로 Compose를 사용한다.

## 설치된 서버의 일상 실행

저장소 루트에서 Makefile을 사용한다. `make` 또는 `make help`로 명령 목록을 볼 수 있다.

```bash
make up        # 기존 PostgreSQL·MinIO·ClamAV·문서 worker·웹 시작, 최대 60초 준비 대기
make status    # 위 서비스 상태 확인
make health    # 실제 웹 port의 API·화면 응답 확인
make logs      # 웹 로그 실시간 확인, Ctrl+C로 로그 보기 종료
make restart   # 웹 컨테이너만 재시작
make stop      # 웹 컨테이너만 중지; DB·저장소·worker 유지
```

`make start`는 `make up`과 같다. `COMPOSE_PROJECT_NAME` 기본값은 `bidops`이며 다른
배포를 관리할 때는 `make status COMPOSE_PROJECT_NAME=<전용 프로젝트명>`처럼 지정한다.
대기 시간은 `WAIT_TIMEOUT=120`, 로그 줄 수는 `LOG_TAIL=200`으로 바꿀 수 있다.

이 명령은 이미 설치된 컨테이너를 사용한다. 현재 컨테이너에 반영된 정적 UI와 배포 설정을
유지하며, 컨테이너가 빠져 있으면 시작 전에 최초 기동 절차를 안내하고 종료한다.
DB·MinIO 초기화, migration, 분석·수집 worker 시작, 이미지 빌드·컨테이너 재생성은 포함하지 않는다.
컨테이너를 재생성하는 배포에서는 사용할 소스를 빌드하고 UI 반영 상태를 다시 검증한다.

### 화면 노출과 edge overlay

`web`은 base stack에서 internal network에만 붙는다. Docker는 internal 전용 컨테이너의
포트를 publish하지 않고 에러도 내지 않으므로, `docker-compose.edge.yml`을 함께 붙이지 않고
`web`을 **재생성**하면 `ports:` 선언이 조용히 사라지고 화면에 접근할 수 없게 된다.
Makefile의 `COMPOSE`는 이 overlay를 이미 포함한다. `make up`·`make restart`는 컨테이너를
재생성하지 않으므로 안전하지만, 손으로 `up -d`를 돌릴 때는 overlay를 빠뜨리지 않는다.

overlay를 붙이면 inbound publish와 함께 `web`에 아웃바운드 경로도 생긴다. 모델 호출은
허용 host와 배포 revision 게이트에서 여전히 호출 전에 fail closed하지만, 이 상태를 내부망
격리와 같다고 기록하지 않는다.

노출 범위는 `BIDOPS_WEB_BIND_HOST`가 정하며 기본값은 `127.0.0.1`이다. 애플리케이션에
로그인이 없으므로 이 값을 넓히면 그 network 전체가 접근 경계가 된다.

### 다른 기기에서 화면 열기

`BIDOPS_WEB_BIND_HOST`를 넓히는 대신 loopback을 소비하는 tailnet proxy를 쓴다. LAN에는
열리지 않고 tailnet 노드에서만 보인다.

```bash
tailscale serve --bg --http=18787 http://127.0.0.1:18787   # 켜기
tailscale serve --http=18787 off                           # 끄기
tailscale serve status
```

이 설정은 tailscaled가 보관하므로 재부팅 후에도 남는다. Funnel(공개 인터넷 노출)은 켜지
않는다. WSL2 mirrored 네트워킹에서는 Hyper-V 방화벽 기본 inbound가 Block이라 컨테이너
포트를 tailnet 주소에 직접 bind해도 다른 노드에서 닿지 않는다. 이 proxy 경로가 그 제약을
받지 않는 이유는 tailscaled가 연결을 받아 host loopback으로 넘기기 때문이다.

## 최초 기동

```bash
cp .env.example .env
cp env/vllm.env.example env/vllm.env
export COMPOSE_PROJECT_NAME=bidops
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d postgres minio clamav
./scripts/init-runtime.sh
docker compose --env-file .env --env-file env/vllm.env \
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.remote-vllm.yml \
  up -d web document-worker analysis-worker
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

`--env-file`을 명시하면 기본 `.env` 자동 로드가 꺼지므로 공통 파일과 overlay 파일을 함께 넘긴다. overlay 없이 기동할 때는 `--env-file` 없이 `.env`가 자동 로드된다.

`scripts/init-runtime.sh`는 DB 역할 초기화, Alembic migration, MinIO 버킷·정책 초기화를 순서대로 실행한다. 앱 startup은 이 작업을 대신하지 않는다. `bidops-source`, `bidops-structure`, `bidops-quarantine`, `bidops-model-response` 버킷은 versioning과 최소 권한 정책을 유지한다.

`migrate` service는 Alembic 성공 뒤 `scripts/runtime-privileges.sql`을 적용한다. 이 단계는 이전 blanket grant를 먼저 회수하고 현재 head의 table·operation allowlist를 다시 부여한다. 새 table은 `app`·`worker` 기본 DML을 받지 않으므로 migration에 runtime write path가 추가되면 같은 변경에서 allowlist와 역할 smoke test를 갱신해야 한다. `ro_backup`만 현재·향후 table의 `SELECT` 기본 권한을 유지한다.

사설 vLLM 없이 웹과 문서 준비만 확인할 때는 remote-vLLM overlay를 빼고 기동할 수 있다. 이 경우 분석 worker가 모델 단계에서 실패하는 것은 정상이며 성공으로 보정하지 않는다.

판정 파이프라인이 승인된 모델 endpoint와 나라장터 OpenAPI에 접근해야 할 때만 다음 overlay를 추가한다. 이 overlay는 `web`에 `model-egress` network를 붙이고 `screening` 용도 설정을 주입한다.

```bash
cp env/screening.env.example env/screening.env   # BIDOPS_VLLM_SCREENING_* 를 채운다
COMPOSE_PROJECT_NAME=bidops docker compose \
  --env-file .env --env-file env/screening.env \
  -f docker-compose.yml -f docker-compose.screening.yml \
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
COMPOSE_PROJECT_NAME=bidops docker compose \
  --env-file .env --env-file env/prespec-attachment.env \
  -f docker-compose.yml -f docker-compose.prespec-attachment.yml \
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
python -m app.deep_review.workers.prespec_attachment
python -m app.deep_review.workers.prespec_attachment --once
```

첨부 URL의 수명은 아직 측정하지 않았으므로 `unknown`으로 유지한다. URL·object key·로컬
경로·자격증명은 worker 상태와 감사 상세에 저장하지 않는다.

모델 없이 상태 전이와 저장·검증 계보만 확인할 때는 mock override를 사용한다. 이 override는 전용 값을 파일 안에 리터럴로 선언하므로 추가 env 파일이 필요 없고 어떤 egress도 열지 않는다.

```bash
COMPOSE_PROJECT_NAME=bidops docker compose \
  -f docker-compose.yml -f docker-compose.mock-reference.yml \
  up -d web document-worker analysis-worker
```

이 override는 두 단계를 모두 덮는다. 심층 검토는 `BIDOPS_ANALYSIS_PROVIDER=mock`,
1차 분류는 `BIDOPS_SCREENING_PROVIDER=mock`이다. 둘 다 `BIDOPS_REFERENCE_WORKFLOW_MODE`가
참이 아니면 기동 전에 설정 검증에서 거부된다.

mock 결과의 provider/model 계보는 `mock-analysis` / `bidops-deterministic-mock-v1`로 고정되고 policy quality는 `reference_workflow_unmeasured`, `deployable=false`다. 응답과 화면에는 `quality_status=mock_reference` 표식이 붙는다. 사업 판단이나 모델 품질 평가 근거로 사용하지 않는다.

`BIDOPS_REFERENCE_WORKFLOW_MODE=true`만 켜고 provider는 `vllm`으로 두면 실제 모델을 부르되 결과에 `quality_status=unmeasured_reference` 표식이 붙는다. 이 모드는 policy의 `model_name` 대조를 건너뛰지만 `model_endpoint_ref` 검사는 유지한다. **참조 실행 결과를 운영 완료·품질 근거·정책 활성화 근거로 기록하지 않는다.**

1차 분류 mock은 `ScreeningAttempt.model_digest`가 mock 전용 상수
(`app/screening/mock_transport.py`의 `MOCK_MODEL_DIGEST`)로 남는다. 저장된 판정이
실제 모델 산출인지 mock인지는 이 값으로 판별한다. `model_name`은 실제 경로도 설정된
모델 id만 받으므로 구별에 쓸 수 없다.

### C-2 모델 revision 선언

`BIDOPS_VLLM_MODEL_REVISION`에 서버 운영자가 확인한 64자 model artifact digest를 넣는다.
이 값은 승인 binding의 `stage2_binding.model_digest`와 같아야 하며, 비어 있거나 다르면
C-2 execution이 payload를 한 건도 보내기 전에 실패한다. OpenAI 호환 vLLM은 weight
revision을 응답에도 `/v1/models`에도 싣지 않으므로 이 값이 배포의 선언이다
([ADR-0042](tracking/decisions/0042-c2-model-revision-declared-at-deployment.md)).

서버를 재기동하거나 vLLM 버전을 올려도 이 값은 바뀌지 않는다. **모델 weight가 실제로
바뀔 때만** 갱신하며, 그때는 값만 고치지 않고 binding을 새 버전으로 올리고 품질 게이트를
다시 측정한다. 응답의 `system_fingerprint`는 빌드·병렬도 지문이므로 이 값으로 쓰지 않는다.

## 모듈 선택과 진입점

백엔드는 `core`·`lifecycle`·`screening`·`deep_review` 네 모듈과 조립 계층으로 나뉜다
([ADR-0045](tracking/decisions/0045-backend-module-layout.md)). 운영 기동은 세 도메인 모듈을
모두 등록한다. `BIDOPS_MODULES`는 그 부분집합을 쉼표로 지정해 일부만 올리는 **개발·검증용**
설정이다.

```bash
BIDOPS_MODULES=deep_review          # /api/health와 deep_review 경로만. 나머지는 404
BIDOPS_MODULES=lifecycle,screening  # deep_review 경로 없음
```

- core는 선택 대상이 아니라 항상 포함되므로 `/api/health`는 어떤 조합에도 있다.
- **알 수 없는 이름이나 빈 값은 기동 실패**다(fail closed). 조용히 기본값으로 되돌아가지
  않는다.
- 의존은 import만 하고 등록은 지정 모듈만 한다. 꺼진 모듈의 REST 경로는 404다.
- 값을 지정하지 않으면 분할 전과 같은 앱이 된다. 운영 `.env`에는 두지 않는다.

worker 진입점은 셋뿐이다. 모델을 쓰는 C-2 선별·심층 검토·사전규격 개요 worker에는 단독
진입점이 없다. `app.workers.analysis` 한 프로세스가 셋을 합성하며, 이것이 **모델 슬롯 1개**
보장이다. 한 바퀴에서 C-2 → 심층 → 개요 순서로 **하나만** claim한다. 셋을 따로 띄우는 명령을
만들지 않는다 — 동시에 뜨면 슬롯 1개 보장이 깨진다.

```bash
python -m app.deep_review.workers.document            # 자격증명 없는 문서 worker
python -m app.deep_review.workers.prespec_attachment  # 사전규격 첨부 취득 worker
python -m app.workers.analysis                        # 모델을 쓰는 합성 worker
```

`--once`를 주면 한 건만 처리하고 종료한다. Compose의 `document-worker`는
`python -m app.deep_review.workers.document`를, `analysis-worker`는
`python -m app.workers.analysis`를 실행한다.

CLI 진입점은 모듈별로 하나씩이며 웹 없이 실행한다. migration·MinIO가 준비된 backend 환경에서
쓴다.

```bash
python -m app.screening.cli --help          # run-one, score-candidate-quality
python -m app.deep_review.cli --help        # run-bc-e2e, run-prespec-e2e, import-profile-policy
python -m app.lifecycle.ingest.cli --help   # --run <회차> | --all
```

## 환경 파일 배치

| 파일 | 소비하는 compose | 담는 값 |
|---|---|---|
| `.env` | `docker-compose.yml`, `docker-compose.sqlite-ops.yml` | 프로세스 정체성, 로그, DB·MinIO 자격증명, 암호화 키, port, 승인 profile/policy 참조 |
| `env/vllm.env` | `docker-compose.remote-vllm.yml` | `BIDOPS_VLLM_BASE_URL`, `BIDOPS_VLLM_ALLOWED_HOSTS`, `BIDOPS_VLLM_API_KEY`, `BIDOPS_VLLM_MODEL_REVISION` |
| `env/screening.env` | `docker-compose.screening.yml` | `BIDOPS_VLLM_SCREENING_BASE_URL`, `_ALLOWED_HOSTS`, `_API_KEY`, `_MODEL_REVISION`, `BIDOPS_VLLM_SCREENING_MODEL` |
| 없음 | `docker-compose.mock-reference.yml` | 전용 값을 override 파일 안에 리터럴로 선언한다 |

overlay 전용 값을 `.env`에 두지 않는다. `.env`에 두면 overlay를 붙이지 않은 기동에서도 endpoint가 주입되어 fail-closed 기본값이 흐려진다.

## 상태 확인과 중지

```bash
COMPOSE_PROJECT_NAME=bidops docker compose -f docker-compose.yml ps
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
COMPOSE_PROJECT_NAME=bidops docker compose -f docker-compose.yml logs --since=30m web analysis-worker
COMPOSE_PROJECT_NAME=bidops docker compose -f docker-compose.yml stop web analysis-worker document-worker
```

로그에는 prompt, 모델 응답, 회사자료, 첨부 본문, 자격증명, URL 쿼리 문자열이 없어야 한다. traceback은 기본 비활성이고 안전한 식별자와 오류 분류만 확인한다.

## 설정 범주

| 범주 | 주요 설정 | 운영 규칙 |
|---|---|---|
| 프로세스 | `BIDOPS_UID`, `BIDOPS_GID`, `BIDOPS_LOG_LEVEL`, `BIDOPS_LOG_TRACEBACK` | non-root, 기본 WARNING, 비밀 없는 로그 |
| 나라장터 | `BIDOPS_G2B_API_KEY`, `BIDOPS_G2B_ATTACHMENT_ENABLED`, `BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS`, `BIDOPS_G2B_ATTACHMENT_TIMEOUT_SECONDS` | API key는 수집 실행 때만 주입. 첨부 취득은 기본 false, 승인 host allowlist가 없으면 fail closed |
| C-1 공고 판정 | `BIDOPS_VLLM_SCREENING_{BASE_URL,ALLOWED_HOSTS,API_KEY,MODEL_REVISION}`, `BIDOPS_VLLM_SCREENING_MODEL`, `BIDOPS_SCREENING_{CONTEXT_SIZE,MAX_OUTPUT_TOKENS,SYNTHESIS_MAX_OUTPUT_TOKENS}`, `BIDOPS_SCREENING_PROVIDER`, concurrency/heartbeat/stale | 승인 endpoint, 배포 선언 revision 고정, concurrency 1. 허용 host나 revision이 비면 호출 전에 fail closed |
| 일정·첨부 worker | `BIDOPS_SCHEDULER_ENABLED`, daily/weekly 시간, `BIDOPS_PRESPEC_ENABLED`, `BIDOPS_PRESPEC_ATTACHMENT_WORKER_CONCURRENCY`, `BIDOPS_PRESPEC_ATTACHMENT_WORKER_POLL_SECONDS`, `BIDOPS_PRESPEC_ATTACHMENT_LEASE_SECONDS` | 기본 false/worker 1·5초·120초, 품질 승인·운영자 확인·host firewall 뒤 활성화 |
| DB | owner/migrate/app/worker/ro-backup 비밀번호, port | 역할 분리, migration은 전용 계정 |
| 객체 저장소 | MinIO root와 namespace별 access/secret, endpoint, secure flag | 용도별 최소 권한, versioning 유지 |
| 문서 검사 | ClamAV host/port/timeout | clean scan envelope 없이는 준비 단계 진행 금지 |
| 개요·심층 모델 | `BIDOPS_VLLM_{BASE_URL,ALLOWED_HOSTS,API_KEY,MODEL_REVISION}`과 `BIDOPS_VLLM_{OVERVIEW,DEEP_REVIEW}_*` override, response encryption key/ref | 승인된 사설 endpoint만, 응답 암호화. 모델명은 설정이 아니라 policy가 정한다 |
| 모듈 선택 | `BIDOPS_MODULES` | 미지정이면 세 도메인 모듈 전부. 알 수 없는 이름·빈 값은 기동 실패. 꺼진 모듈 경로는 404 |
| 활성 버전 | active profile version, active analysis policy version | 불변 ID, 빈 값이면 fail closed |
| 외부 참조 | `BIDOPS_OPENAI_ENABLED`, `BIDOPS_REFERENCE_WORKFLOW_MODE` | 심층 검토 provider는 `BIDOPS_ANALYSIS_PROVIDER`의 `vllm`과 `mock` 둘뿐이며 hosted 외부 deep-review provider(codex-exec)와 그 overlay·설정은 저장소에서 제거됐다. 향후 발주계획 전용 projection에서만 공개 plan metadata+최소 승인 요약을 preview·건별 승인 후 전송 |

## 발주계획 선별 실험 운영

제품 선별기를 구현하기 전에 동일한 3일 입력을 동결해 네 방식을 비교한다.

1. 일반용역과 기술용역을 수집하고 발주계획 단계에서는 SW사업대상 여부로 선필터하지 않는다.
2. 원본 응답, 정규화 전체 레코드, 조회 조건, 페이지, source hash, 최초 수집 시각을 보존한다.
3. 키워드 규칙, ColBERT, `qwen3.8-27B`, GPT Luna xhigh를 같은 모집단에 실행한다.
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

## 사전규격 심층 검토 참조 실행

이 절은 사전규격 하나를 **수집 → 판정 → 첨부 취득 → 자동 문서 준비 → 개요 검토 → 심층
검토**까지 한 번 통과시키는 절차다. 담당자 한 사람이 처음부터 끝까지 혼자 실행할 수 있게
단계마다 명령·overlay·환경변수·확인 방법·중단 기준을 적는다.

> **이 절차는 아직 실행되지 않았다.** 이 문서를 쓴 시점에 vLLM 호출, 나라장터 다운로드,
> Compose 스택 기동을 한 번도 수행하지 않았다. 아래 명령은 코드와 Compose 파일에서 읽어
> 구성한 것이며, 실제 실행은 사용자가 한다. 아래 어떤 문장도 "이렇게 돌려 봤다"는 뜻이
> **아니다.**

> **결과의 성격.** 이 실행이 만드는 심층 검토와 개요 검토에는
> `quality_status=unmeasured_reference`(실제 모델) 또는 `mock_reference`(결정적 mock) 표식이
> 붙는다. 이것은 **참조 실행**이며 운영 완료, 모델 품질 근거, 정책 활성화 근거로 쓰지
> 않는다. 사업 판단에 쓰지 않는다.

### 시작 전 확인 — 반복해서 걸리는 다섯 가지

이 다섯은 각 단계 본문에서 다시 언급하지만, 시작 전에 한 번에 읽어 두는 편이 낫다.

1. **수집기 timeout은 300초로 준다.** `collect_notices.py`의 `--timeout` 기본값은 30초이고
   사전규격 구간 수집에서는 거의 항상 모자란다.
2. **회차 디렉터리는 host에서 만들고 `docker compose cp`로 컨테이너에 넣는다.** web
   컨테이너에는 나라장터 API key가 없다. 수집은 host에서 하고 결과 디렉터리만 넣는다.
3. **컨테이너 안에서 `127.0.0.1`을 쓰지 않는다.** 컨테이너의 loopback은 자기 자신이다.
   DB는 `postgres`, 객체 저장소는 `minio`, 검사기는 `clamav`처럼 **서비스 이름**을 쓰고,
   모델 서버는 컨테이너에서 도달 가능한 실제 IP를 쓴다.
4. **`import-profile-policy`가 낸 UUID를 `.env`에 넣은 뒤 반드시 재기동한다.** 설정은
   프로세스 시작 때 읽는다. 값만 넣고 재기동하지 않으면 심층 검토 생성이 계속
   `service_unavailable`로 fail closed한다.
5. **방화벽은 첨부 host와 모델 IP를 각각 한 곳만 연다.** overlay가 network를 붙이는 것과
   egress가 안전한 것은 다른 문제다. overlay는 host 방화벽 정책을 대신하지 않는다.

준비물은 나라장터 API key, 승인된 vLLM endpoint의 IP·port와 운영자가 확인해 준 64자 model
revision, PostgreSQL·MinIO 자격증명이다. 이 문서에는 실제 주소·키를 적지 않는다.
`<approved-ip>`, `<approved-port>`, `<64-hex-revision>` 자리에 담당자가 값을 넣는다.

### 1단계. 담당자 커밋과 스택 기동

작업 전에 현재 worktree가 깨끗한지 확인하고, 이 실행에서 만들 증거 파일이 어느 코드
상태에서 나왔는지 고정한다.

```bash
cd /path/to/bidops
git status --short
git rev-parse HEAD
cp .env.example .env          # 이미 있으면 건너뛴다
export COMPOSE_PROJECT_NAME=bidops
```

`.env`에서 최소한 다음을 채운다. 비밀은 외부 secret manager에서 주입하고 `.env`는
커밋하지 않는다.

```text
BIDOPS_REVIEWER=<담당자 이름>
BIDOPS_G2B_API_KEY=<나라장터 키>
BIDOPS_OWNER_PASSWORD / BIDOPS_MIGRATE_PASSWORD / BIDOPS_APP_PASSWORD /
BIDOPS_WORKER_PASSWORD / BIDOPS_RO_BACKUP_PASSWORD
BIDOPS_MINIO_ROOT_USER / BIDOPS_MINIO_ROOT_PASSWORD 및 용도별 access/secret 6쌍
BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY / _KEY_REF
```

회사자료 세 파일이 regular file로 있어야 한다(없으면 Compose가 그 자리에 디렉터리를
만들고 프로필 경계가 비정상적으로 실패한다).

```bash
test -f docs/reference/company-profile.md && test -r docs/reference/company-profile.md
test -f docs/reference/company-performance-titles.tsv
test -f web/backend/app/screening/baseline_company_profile.md
```

기동한다.

```bash
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d postgres minio clamav
./scripts/init-runtime.sh
docker compose -f docker-compose.yml up -d web document-worker
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

`curl`은 **host에서** 실행하므로 `127.0.0.1`이 맞다. 컨테이너 안에서 같은 주소를 쓰지
않는다.

- **확인**: `docker compose ps`에서 `postgres`·`minio`·`clamav`·`web`·`document-worker`가
  healthy 또는 running이고, `/api/health`가 `{"status":"ok"}`다.
- **중단 기준**: `init-runtime.sh`가 실패하거나 `/api/health`가 200이 아니면 다음 단계로
  가지 않는다. MinIO versioning 검증 실패는 fail-closed가 정상 동작이므로 우회하지 않는다.
  `document-worker`가 `PermissionError: '/scratch/inbox'`로 죽으면 스택을 중지하고
  `document-scratch` volume만 지운 뒤 다시 올린다(장애 대응 절).

### 2단계. `import-profile-policy`와 active ID 설정

심층 검토는 승인된 profile version과 analysis policy version이 있어야 생성된다. 이 참조
실행에서는 **품질 인자 없이** import한다 — 아직 측정한 값이 없기 때문이다.

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli import-profile-policy \
  --actor '<담당자 이름>'
```

품질 인자(`--sample-hash`, `--required-item-recall`, `--human-agreement`,
`--unsupported-false-positive-rate`)를 **주지 않는다.** 하나라도 주면
`--expected-policy-sha256`이 함께 필요하고, 측정하지 않은 값을 넣는 것은 이 절차의 범위를
벗어난다. 인자 없이 import하면 policy의 품질 metadata가 비어 `deployable=false`가 되며,
그래서 이 실행이 참조 실행이다.

출력의 `profile_version_id`와 `policy_version_id`를 `.env`에 넣는다.

```text
BIDOPS_ACTIVE_PROFILE_VERSION_ID=<profile_version_id>
BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID=<policy_version_id>
BIDOPS_REFERENCE_WORKFLOW_MODE=true
```

**그리고 반드시 재기동한다.** 값만 넣고 재기동하지 않으면 프로세스가 옛 설정을 들고 있어
심층 검토 생성이 계속 실패한다.

```bash
docker compose -f docker-compose.yml up -d --force-recreate web
```

- **확인**: `docker compose exec web env | grep BIDOPS_ACTIVE_`가 두 UUID를 보여 준다.
  `import-profile-policy` 출력의 `active_configuration_changed`는 항상 `false`다 — 명령이
  환경을 대신 바꾸지 않는다는 뜻이므로 정상이다.
- **중단 기준**: 명령이 `policy_hash_mismatch`나 `invalid_request`로 끝나면 값을 고쳐 넣지
  말고 멈춘다. UUID가 비어 있는 채로 다음 단계를 진행하면 6단계에서 fail closed한다.

### 3단계. 사전규격 회차 수집·표본 선정·적재

수집은 **host에서** 한다. web 컨테이너에는 API key가 없다.

```bash
RUN_ID=$(date +%Y%m%d)-prespec-ref
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date <YYYY-MM-DD> --to-date <YYYY-MM-DD> \
  --output-dir "data/runs/${RUN_ID}" \
  --skip-bids \
  --timeout 300
```

- `--skip-bids`는 입찰공고를 빼고 사전규격만 담는다. 둘은 같은
  `collected-notices.json` 하나에 들어가므로 이 플래그가 없으면 입찰공고까지 적재된다.
- `--timeout 300`이 핵심이다. 기본 30초로는 구간 수집이 거의 항상 끊긴다.
- 원문 페이지는 `data/runs/${RUN_ID}/raw/`에 남는다. 재분류는 `--from-raw`로 API 호출 없이
  반복할 수 있다.

표본을 고른다. 판정은 `validation-set.json`을 입력으로 쓴다.

```bash
python3 skills/bidops-collect/scripts/select_validation_sample.py \
  "data/runs/${RUN_ID}/collected-notices.json" \
  --output "data/runs/${RUN_ID}/validation-set.json"
```

회차 디렉터리를 컨테이너에 넣고 적재한다.

```bash
docker compose -f docker-compose.yml cp "data/runs/${RUN_ID}" web:/app/data/runs/
docker compose -f docker-compose.yml exec web \
  python -m app.lifecycle.ingest.cli --run "${RUN_ID}"
```

- **확인**: `curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/runs/${RUN_ID}/warnings"`에
  차단 등급 경고가 없다. `/api/pre-specs`의 `total`이 DB의
  `notice where source_type='pre_spec'` 건수와 같다.
- **중단 기준**: 적재 경고에 차단 등급이 있으면 원인을 `docs/tracking/findings.md`에 적고
  멈춘다. 수집 결과가 0건이면 날짜 구간을 바꿔 다시 수집한다 — 빈 회차를 적재하고 진행하면
  뒤 단계의 실패 원인이 모호해진다.

### 4단계. C-1 판정 실행

이 단계부터 모델을 부른다. **먼저 host 방화벽에서 승인된 모델 IP와 port 한 곳만 열고**,
그 다음에 overlay를 붙인다.

```bash
cp env/screening.env.example env/screening.env
```

`env/screening.env`를 채운다. 주소는 **컨테이너에서 도달 가능한** 값이어야 한다.

```text
BIDOPS_VLLM_SCREENING_BASE_URL=http://<approved-ip>:<approved-port>/v1
BIDOPS_VLLM_SCREENING_ALLOWED_HOSTS=<approved-ip>
BIDOPS_VLLM_SCREENING_API_KEY=EMPTY
BIDOPS_VLLM_SCREENING_MODEL_REVISION=<64-hex-revision>
BIDOPS_VLLM_SCREENING_MODEL=qwen3.8-27B
```

`<approved-ip>`에 `127.0.0.1`을 넣지 않는다. host에서 도는 모델 서버라면 컨테이너에서 보이는
host 주소를 쓴다. `ALLOWED_HOSTS`는 base URL의 host와 **같은 리터럴**이어야 한다. 비어 있거나
revision이 64자 hex가 아니면 C-1은 **호출 전에** fail closed한다.

vLLM이 실제로 그 모델을 서빙하는지 먼저 확인한다(host에서).

```bash
curl --fail --silent --show-error \
  -H 'Authorization: Bearer EMPTY' \
  "http://<approved-ip>:<approved-port>/v1/models"
```

응답의 `data[].id`에 `qwen3.8-27B`가 있어야 한다. 없으면 `model_not_served`로 실패하므로
여기서 멈추고 서버 운영자와 모델 id를 맞춘다.

overlay를 붙여 `web`을 재기동한다.

```bash
docker compose --env-file .env --env-file env/screening.env \
  -f docker-compose.yml -f docker-compose.screening.yml \
  up -d web
```

판정을 실행한다. 회차 하나를 통째로 판정한다.

```bash
curl --fail -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-BidOps-Actor-Name: <담당자 이름>' \
  -d '{"scope":"full_run","policy_version":"<active policy version>","profile_source":"current"}' \
  "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/runs/${RUN_ID}/pipeline/judgment"
```

요청 body의 정확한 필드는 `docs/contracts.md`의 `JudgmentExecutionCreateRequest`를 따른다.
202가 오면 `execution_id`로 진행 상태를 본다.

```bash
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/screening/executions?run_id=${RUN_ID}"
```

- **확인**: execution 상태가 `성공` 또는 `부분 성공`이고, `/api/pre-specs`의 항목에 `grade`와
  `grade_source=screening_judgment`가 채워진다. 최소 한 건이 `우선 검토`여야 다음 단계가
  의미가 있다.
- **중단 기준**:
  - `503`으로 즉시 실패하면 모델 preflight 실패다. 허용 host·선언 revision·served id 셋을
    다시 확인한다. **fail-closed를 우회하려고 값을 지어내지 않는다.**
  - 모든 공고가 실패해 `실패`로 끝나면 멈춘다. `error_summary`의 안전 분류만 읽고 로그에서
    prompt·응답 본문을 찾지 않는다.
  - `우선 검토`가 한 건도 없으면 자동 준비가 열리지 않는다. 다른 구간으로 3단계를 다시
    하거나 여기서 절차를 끝낸다 — 등급을 손으로 고쳐 넣지 않는다.
  - 옛 모델 이름(`qwen3.8:27b`)으로 기록된 과거 execution이 같은 DB에 있으면 carry-over
    검증과 enqueue에서 거부된다. 새 DB로 시작하거나 담당자가 이관을 별도로 판단한다.

### 5단계. 첨부 취득 worker

`우선 검토` 등급이 붙으면 첨부 취득 자격이 생긴다. **먼저 host 방화벽에서 승인된 G2B
첨부 host 한 곳만 연다.**

```bash
cp env/prespec-attachment.env.example env/prespec-attachment.env
# BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS 를 방화벽에서 승인한 host와 같게 채운다
docker compose --env-file .env --env-file env/prespec-attachment.env \
  -f docker-compose.yml -f docker-compose.prespec-attachment.yml \
  up -d prespec-attachment-worker
```

overlay가 `BIDOPS_G2B_ATTACHMENT_ENABLED=true`를 덮고 `prespec-egress` network를 붙인다.
overlay 없이는 기본값 `false`로 worker가 idle이고, allowlist가 비면 fail closed한다.
worker 설정은 concurrency 1, poll 5초, lease 120초다.

- **확인**: `docker compose logs --since=10m prespec-attachment-worker`에 안전한 상태 전이만
  보인다. `/api/pre-specs`의 항목 `document` 집계에서 `완료` 건수가 오르고,
  `auto_preparation_status`가 `waiting_attachments`에서 넘어간다.
- **중단 기준**: 로그에 URL·object key·로컬 경로·자격증명이 보이면 **즉시 중지하고 보고한다**
  (문제 보고 절). 허용 host 밖 요청이 나가면 같다. 취득이 전부 `차단`·`실패`로 끝나면
  방화벽과 allowlist를 확인하고, 그래도 안 되면 여기서 멈춘다 — 첨부를 손으로 넣어 절차를
  이어 붙이지 않는다.

### 6단계. 자동 준비·개요 검토·심층 검토 확인

모델을 쓰는 worker는 `analysis-worker` 하나다. 개요와 심층은 이 프로세스가 합성하고 한
바퀴에 하나만 claim한다. 개요 전용 진입점은 없다.

```bash
cp env/vllm.env.example env/vllm.env
```

`env/vllm.env`를 채운다. 여기 값은 `overview`와 `deep_review` 용도의 공유값이 된다.

```text
BIDOPS_VLLM_BASE_URL=http://<approved-ip>:<approved-port>/v1
BIDOPS_VLLM_ALLOWED_HOSTS=<approved-ip>
BIDOPS_VLLM_API_KEY=EMPTY
BIDOPS_VLLM_MODEL_REVISION=<64-hex-revision>
BIDOPS_C2_EXECUTION_ALLOWED=false
BIDOPS_C2_CAPABILITIES_HOST_PATH=<승인된 파일 경로>
BIDOPS_C2_PROMPT_HOST_PATH=<승인된 파일 경로>
```

`remote-vllm` overlay는 `web`에도 C-2용 read-only bind mount를 요구하므로 두 host 경로를
비워 두면 기동이 거부된다. 이 참조 실행에서 C-2를 돌리지 않으므로
`BIDOPS_C2_EXECUTION_ALLOWED`는 `false`로 둔다.

```bash
docker compose --env-file .env --env-file env/vllm.env \
  -f docker-compose.yml -f docker-compose.remote-vllm.yml \
  up -d analysis-worker
```

이 단계에서 사람이 누르는 것은 없다. 자동으로 다음이 일어난다.

1. 등급이 `우선 검토`가 되고 첨부 취득이 끝나면 자동 준비가 묶음 초안을 만들고 확정한다
   (`confirmed_by_name = auto-preparation`).
2. 확정된 묶음으로 개요 검토가 실행된다.
3. `SW사업대상=Y`이고 개요가 `completed`이며 권고가 `검토 종료`가 아니면 심층 검토가
   자동으로 생성된다.

진행은 사전규격 목록의 파생 필드로 읽는다.

```bash
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/pre-specs?limit=50"
```

`auto_preparation_status`가 `not_applicable → waiting_attachments → bundle_draft →
bundle_ready → overview_running → deep_review_started`로 간다.
`deep_review_ready_for_click`에서 멈추면 `auto_preparation_reason`이 **왜 자동으로 열리지
않았는지**를 말한다(`not_sw_business`, `overview_recommendation_closed` 등). 그 값이 정상적인
설명이면 화면에서 사람이 심층 검토를 실행한다.

개요와 심층 결과를 본다.

```bash
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/pre-specs/<notice_id>/overview-reviews/v2"
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/<deep_review_id>"
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/<deep_review_id>/report"
```

- **확인**:
  - 개요 attempt의 `quality_status`가 `unmeasured_reference`(실제 모델) 또는
    `mock_reference`(mock)다. **둘 다 참조 실행이며 운영 완료가 아니다.**
  - 심층 검토의 `status`가 `completed`이고 report의 `validation.status`를 읽는다.
    `failed`도 정상적인 결과다 — 실패를 통과로 바꾸지 않는다.
  - report의 `quality_status`가 위와 같은 표식이거나 `null`이다.
  - `GET /api/document-structures/<structure_id>/segments`가 200이고 `segments[].confidence`가
    전부 `null`이다.
- **중단 기준**:
  - 심층 검토 실행이 `503`으로 닫히면 pinned 입력 대조 실패다. 이 변경 **전에** 만들어진
    검토는 `policy_quality` snapshot 모양이 달라 실행되지 않는다 — 새 attempt를 만든다.
    DB row나 감사 metadata를 고쳐 통과시키지 않는다.
  - segments 조회가 404면 그 구조는 이 변경 전에 만들어져 manifest가 없다. 사후 재구성은
    불가능하므로 문서를 다시 올려 새 구조를 만든다.
  - 모델 호출이 `model_not_served`·`model_revision_invalid`·`identity_unavailable`로 끝나면
    4단계의 확인을 `overview`/`deep_review` 용도에 대해 다시 한다. **다른 endpoint나 hosted
    provider로 바꾸지 않는다.**

### 7단계. 화면 확인과 증거 기록

화면은 데스크톱·노트북 전용이다. 확인 viewport는 laptop 1280x800과 desktop 1440x900이다.

| 화면 | 확인할 것 |
|---|---|
| `/pre-specs` | 등급과 `등급 출처 · 판정\|정정\|없음`, 자동 준비 8값 한국어 문구, 등급 필터가 **브라우저 쪽 필터**라는 안내 |
| `/pre-specs/<notice_pk>` | 개요 카드의 품질 표식(`참조 실행 · 품질 미측정` 또는 `mock 참조`), 근거 locator로 원문 열기 |
| `/deep-reviews/<id>` | 상단 카드 다섯(`종합 판단`·`검증 결과`·`미확인 사항`·`보고서 revision`·`품질 표식`), 우측 열 네 구역(`보고서 범위` → 문서 inventory → `보고서 수정본 저장` → 이력) |
| 문서 inventory 패널 | 선택한 근거가 가리키는 **문서 하나**만 보인다는 안내와 segment 제목이 없는 이유 |

등급 필터는 URL `/pre-specs?grade=<값>`으로 열린다. 허용 값은
`우선 검토|검토 권장|관찰 대상|제외|판정 없음`이고 그 밖의 값은 `전체`로 떨어진다.
`grade`를 바꾸면 `offset`이 초기화된다. **이 필터는 이미 받은 페이지만 좁히므로 상단의
개요 상태 집계와 대상 집합이 다르다.** 화면이 그 사실을 적어 두었는지 함께 확인한다.

증거는 `docs/validation-runs/<날짜>-prespec-deep-review-reference.md`에 남긴다. 아래 틀을
그대로 쓴다. **실제로 실행한 명령과 요약 줄만 적고 이전 통과 기록을 재사용하지 않는다.**

```markdown
# 사전규격 심층 검토 참조 실행 — <YYYY-MM-DD>

- 실행자: <담당자 이름>
- 코드 상태: `git rev-parse HEAD` = <commit>
- Compose project: bidops
- 회차 ID: <RUN_ID>
- 결과 성격: **참조 실행.** quality_status = <unmeasured_reference | mock_reference>
  운영 완료·품질 근거·정책 활성화 근거가 아니다.

## 단계별 결과

| 단계 | 실행한 명령(요약) | 결과 | 비고 |
|---|---|---|---|
| 1 스택 기동 | | | |
| 2 profile/policy import | | profile=<uuid> policy=<uuid> | 품질 인자 없이 import |
| 3 수집·표본·적재 | | 수집 <n>건 / 적재 경고 <n>건 | `--skip-bids --timeout 300` |
| 4 C-1 판정 | | execution=<id> 상태=<...> 우선 검토 <n>건 | |
| 5 첨부 취득 | | 완료 <n> / 차단 <n> / 실패 <n> | 방화벽 승인 host: <host> |
| 6 자동 준비·개요·심층 | | 자동 확정 <n> / 개요 completed <n> / 심층 <id> | |
| 7 화면 확인 | | 1280x800, 1440x900 | |

## 모델 binding

- served model id: <...>
- 배포 선언 revision: <64-hex 앞 8자리만 적는다>
- endpoint: <자리표시자. 실제 IP·port를 적지 않는다>
- 용도별 설정: screening / overview / deep_review

## 관측한 실패와 그대로 남긴 것

- <실패 분류 코드와 건수. 실패를 통과로 바꾼 조치가 있으면 안 된다>

## 이 실행이 증명하지 않는 것

- 모델 품질. 사람 gold도 A/B도 없다.
- 운영 활성화 근거. `deployable=false`다.
- 나라장터 데이터의 정확성.
```

증거 파일에 원문, 회사 프로필 전문, prompt, 모델 응답, 비밀값, object key, 실제 IP,
자격증명을 넣지 않는다. 주소와 키는 자리표시자로 적는다.

### 실행 뒤 정리

```bash
docker compose -f docker-compose.yml stop analysis-worker prespec-attachment-worker web
```

`docker compose down -v`와 volume 삭제는 하지 않는다. 회차 원본과 만들어진 검토는
보존한다. 참조 실행이 만든 심층 검토를 나중에 실제 품질 실행으로 재사용하지 않는다 —
provider/model 계보와 품질 표식이 고정돼 있으므로 새 묶음 또는 새 policy version으로 새
검토를 만든다.

## 검증

소스와 fake 모델 검증은 live API key나 model endpoint 없이 실행한다.

### C-2 Phase 0 계약 검증

발주계획 C-2를 구현하거나 실행하기 전에 다음 read-only 검증을 수행한다. 이 명령은 raw
입력·approved manifest·정책·선정 증거·부분 gold·binding의 SHA-256과 구조를 대조하지만,
prompt/profile 본문을 출력하지 않고 모델 endpoint·외부 API를 호출하지 않는다.

```bash
python3 skills/bidops-screen/scripts/validate_order_plan_phase0.py --json
```

정상 결과도 현재는 `status=valid_but_blocked`, `execution_allowed=false`,
`activation_allowed=false`다. `c1_gold_incomplete`, `audit_sample_policy_unapproved`,
`quality_gate_not_measured`, `private_vllm_transport_requires_per_execution_approval`를
사람 승인 없이 제거하거나 policy·binding을 직접 수정하지 않는다. hash가 다르거나 수집
회차가 incomplete·warning 상태이면 exit 2로 종료하며 재생성·보정하지 않는다. scheduler는
이 검증의 대상도 아니고 blocker도 아니다.

```bash
./run-tests.sh
./web/run-web-tests.sh
cd web/frontend && npm run test:contrast
cd web/frontend && npm run test:screens
COMPOSE_PROJECT_NAME=bidops docker compose -f docker-compose.yml build
```

`web/run-web-tests.sh`는 임시 PostgreSQL 17에서 migration을 수행하고, 격리 DB의 backend 테스트와 frontend production build, Playwright 화면 스냅샷 회귀를 실행한다. 검증 폭은 laptop 1280x800과 desktop 1440x900 두 폭이다(ADR-0047. 이전의 네 폭에서 모바일 390·태블릿 768을 없앴다). 화면 검사는 의미·구조·픽셀 세 층이며 게이트는 앞의 둘(`npm run test:screens`)이다. 픽셀 층(`npm run test:pixel`)은 기준 이미지 대조라 게이트가 아니고, 갈아 끼울 때는 사유·영향 화면·승인자를 기록에 남긴다([standards.md](standards.md)). Docker가 없으면 `BIDOPS_TEST_POSTGRES_URL`에 폐기 가능한 PostgreSQL 관리 URL을 제공한다. 운영 DB URL을 사용하지 않는다. Playwright는 브라우저 번들을 자동으로 내려받지 않으므로 없으면 실패한다.

live vLLM smoke는 운영자가 명시한 한 번의 명령과 대상에서만 수행한다. safety 환경변수가 true라는 사실만으로 실행하지 않는다. 결과에는 모델명, digest 또는 승인된 immutable reference, 정책·프로필 버전, 입력 hash, 시작·종료 시각을 남긴다.

## 백업

PostgreSQL 백업은 현재 Compose 계약상 host의 `./backups/postgres`에 쓴다. 실행 뒤 dump를 승인된 외부 보존 위치로 복사하고 보존 위치의 접근권한과 hash를 기록한다.

```bash
COMPOSE_PROJECT_NAME=bidops docker compose \
  -f docker-compose.yml --profile backup run --rm ro-backup
```

`scripts/backup-postgres.sh`는 timestamp가 붙은 custom-format dump를 만들고 기존 백업을 삭제하지 않는다. 4시간 RPO가 필요하면 이 스크립트와 별도로 WAL 보관을 구성하고 복구 시험으로 확인한다.

객체 백업은 네 개의 MinIO 버킷에서 모든 version을 버전별 파일로 복사하고
`OBJECT_BACKUP_DIR/object-versions.tsv`를 만든다. manifest의 각 행은 헤더 없이
`namespace/object_name<TAB>source_version_id<TAB>sha256` 형식이다. `sha256`은 source와
백업 파일의 stored bytes가 같은지 복사 직후 다시 확인한 값이다. 실행 환경에 `mc`,
`MINIO_ALIAS`, `OBJECT_BACKUP_DIR`를 제공한다. object key에 공백과 괄호가 있어도 TSV
필드와 version-qualified 파일명으로 보존한다.

```bash
./scripts/backup-objects.sh
```

DB dump와 객체 manifest는 같은 복구 지점을 식별할 수 있게 함께 보존한다. 암호화 key reference와 실제 key의 백업 정책은 분리하고 접근을 감사한다.

## 복구

복구는 기존 운영 대상 위가 아니라 빈 PostgreSQL과 빈 MinIO 대상에서 수행한다. 네 개 대상
버킷은 versioning이 켜져 있어야 한다. restore는 source version ID를 target에 그대로
재사용한다고 가정하지 않고, 각 `mc cp` 직후 target version ID를 조회한다. 복사 전 백업
파일의 stored-byte hash도 manifest와 대조한다.

`restore.sh`가 만드는 산출물은 다음과 같다.

- `OBJECT_BACKUP_DIR/object-version-mapping.tsv`: 헤더 없는
  `namespace/object_name<TAB>source_version_id<TAB>target_version_id<TAB>sha256` mapping.
  백업 manifest의 source ID와 복구 대상에서 새로 발급된 target ID를 함께 보존한다.
- `ACTIVE_HASH_MANIFEST`: `pg_restore` 뒤
  `scripts/generate-active-hash-manifest.sh`가 복구 DB의 active object reference에서
  원자적으로 다시 만든 manifest다. 수동으로 일부 object를 적은 파일을 준비하지 않는다.

복구 순서는 객체 복사·백업 hash 확인 → DB restore → DB active manifest 생성 → target
version ID·namespace별 무결성 및 active 집합 일대일 검증이다. source·structure·quarantine는
target version의 stored-byte hash까지 대조한다. model-response는 암호화된 응답 envelope를
저장하고 DB의 `ContentObject.sha256`에는 plaintext hash만 기록하므로, 내용 hash는 대조하지
않고 target version에서 object 존재와 version만 확인한다. verifier는 mapping과 target의
모든 복구 version을 대조하며, DB active object의 누락·추가·중복과 target object의
누락·추가·중복을 실패시킨다.

1. 복구 대상과 네트워크를 격리한다.
2. `OBJECT_BACKUP_DIR`, `RESTORE_MINIO_ALIAS`로 버전별 객체를 먼저 복사하고 target ID mapping을 남긴다.
3. `DUMP_FILE`을 빈 PostgreSQL에 `pg_restore`한다.
4. `ACTIVE_HASH_MANIFEST`를 복구 DB의 `bidops.content_object_location`과
   `bidops.content_object`에서 생성한다.
5. mapping의 target version ID로 active object의 hash와 DB active 집합을 대조한다.
6. FK, Alembic head, 핵심 row 수, active document·model response 참조를 검사한다.
7. API read-only smoke와 대표 보고서 재현을 확인한 뒤에만 전환 여부를 사람이 결정한다.

```bash
OBJECT_BACKUP_DIR=/approved/objects \
DUMP_FILE=/approved/db.dump \
ACTIVE_HASH_MANIFEST=/approved/active-hashes.tsv \
RESTORE_MINIO_ALIAS=restore \
BIDOPS_DATABASE_URL='postgresql+psycopg://...' \
BIDOPS_DATABASE_HOST=restore-db \
BIDOPS_DATABASE_PORT=5432 \
BIDOPS_DATABASE_NAME=bidops \
BIDOPS_DATABASE_USER=restore-user \
BIDOPS_DATABASE_PASSWORD='injected-secret' \
./scripts/restore.sh
```

host에 `mc`·`pg_restore`·`psql`이 없으면 동일한 변수를 주입한 승인된 ops image에서
`bash /opt/bidops/scripts/restore.sh`를 실행한다. `BIDOPS_DATABASE_URL`은 실행 계약 식별자로
함께 주입하고, 실제 명령은 `BIDOPS_DATABASE_HOST`·`PORT`·`NAME`·`USER`와
`BIDOPS_DATABASE_PASSWORD`를 사용한다. `RESTORE_MINIO_ALIAS`는 네 개 target bucket에
접근할 수 있는 `mc` alias여야 한다. 복구 중 source object, 기존 백업 파일, DB row를
삭제하지 않으며, target이 비어 있지 않거나 versioning이 꺼져 있으면 검증 실패로 끝난다.

## 승인된 Ollama를 쓰는 경우

`BIDOPS_VLLM_OVERVIEW_API_DIALECT=ollama`를 명시하고 overview 전용 endpoint,
allowed hosts, 모델 digest와 `BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH`를 함께 고정한다.
정책은 실제 served model name을 사용한 별도 불변 파일이며 기존 정책을 덮어쓰지 않는다.
기본 dialect는 기존 vLLM이다. 이 설정은 C-1·C-2·심층 모델 설정을 바꾸지 않는다.

C-1과 심층 검토도 명시적인 실행 승인 뒤 각각
`BIDOPS_VLLM_SCREENING_API_DIALECT=ollama`,
`BIDOPS_VLLM_DEEP_REVIEW_API_DIALECT=ollama`로 같은 transport 검증을 사용한다.
용도별 endpoint·allowed hosts·digest와 실제 served model name을 함께 고정한다.
심층 검토는 해당 모델명의 별도 불변 정책과 참조 실행 설정을 사용하고 기존 정책의
측정값을 승계하지 않는다. C-2는 별도 transport와 품질 binding을 유지하므로
이 설정으로 모델이나 승인 binding을 바꾸지 않는다.

Ollama 호환 요청은 `reasoning_effort=none`을 사용한다. OpenAI 호환 API에서
top_k를 덮을 수 없으므로 매 completion 전에 `/api/tags`의 digest와 `/api/show`의
모델 `top_k=20`을 확인한다. 미확인·불일치는 본문 전송 전에 실패한다.
temperature/top_p/seed/출력 한도와 JSON schema는 기존 고정 generation 계약을 유지한다.
참고: [Ollama 공식 호환 문서](https://docs.ollama.com/api/openai-compatibility).

개요만 실행할 때는 active profile/policy ID를 비워 자동 심층 시작을 열지 않는다.
분석은 기존 합성 worker의 `--once`와 동시성 1을 사용한다. 별도 개요 daemon을 만들지 않는다.
host 방화벽의 목적지 제한과 허용·거부 연결을 확인하고 나서 실제 입력을 전송한다.

첨부 worker에는 source/quarantine 외에 structure 쓰기와 전용 structure 읽기 자격증명이
필요하다. 실제 변환은 `document-scratch`를 공유하는 네트워크 없는 document-worker가 맡는다.
runtime privilege 파일의 worker 열별 권한도 적용돼 있어야 한다. `notice.id`의 UPDATE는
PostgreSQL 행 잠금에 필요한 권한이며 코드에서 ID를 바꾸지 않는다. 첨부의 `extract_status`,
문서의 `is_current` 외에 원문 metadata를 worker가 수정하도록 권한을 넓히지 않는다.

## 장애 대응

- 첨부 경로 이탈, 비밀·회사자료 노출, 승인 없는 외부 모델 전송, 기존 회차·리뷰 덮어쓰기, 원문과 다른 근거의 검증 통과가 발견되면 관련 worker와 egress를 즉시 중지하고 상태를 보존한다.
- 중단된 판정은 자동 resume하지 않는다. heartbeat와 마지막 stage를 확인하고 새 실행 ID로 사람이 재시작한다.
- 부분 산출물은 성공 subset과 failure artifact를 함께 보존한다. 유효 결과가 없으면 성공 run을 발행하지 않는다.
- 모델 endpoint 장애가 로컬 판정에서 hosted OpenAI 자동 fallback을 일으키면 안 된다. 외부 재분석은 별도 승인 실행으로만 만든다.
- `document-worker`가 `PermissionError: '/scratch/inbox'`로 즉시 종료하면 image가 `/scratch`를 만들기 전에 생성된 `document-scratch` volume이 root 소유로 남은 것이다. 스택을 중지하고 그 volume만 삭제한 뒤 다시 올린다. 이 volume은 변환 중인 handoff만 담으므로 보존 대상이 아니다.

## PDF 개요 출력 연결

Alembic `0019_prespec_page_overview`는 설명형 참조 요약을 별도 테이블에 추가한다.
앱 startup은 여전히 migration을 실행하지 않는다. 배포 전 기존 백업 manifest·서비스
중지·명시적 확인 절차를 따른 뒤 migration과 `scripts/runtime-privileges.sql`을 적용한다.
새 테이블은 app 읽기, worker 읽기/추가만 허용하고 UPDATE/DELETE trigger로 불변성을
강제한다. 적재 행이 있으면 downgrade는 거부한다.

서버측 명령(설정된 ops 환경, worker DB 역할, source/structure 객체 쓰기와 ClamAV 필요):

```bash
python -m app.deep_review.cli import-page-overview \
  --run-dir /absolute/frozen-run-directory --notice-id 614 --actor jechoi --check-only
python -m app.deep_review.cli import-page-overview \
  --run-dir /absolute/frozen-run-directory --notice-id 614 --actor jechoi
```

입력은 해당 디렉터리의 `<id>-input.json`, `<id>-output.json`, `<id>-outcome.json`,
`run-manifest.json`, `<id>.hwp`, `<id>.pdf`, `code/policy.json`이다. 원문 확장자는 참조 실행의
고정 파일명이며 내용은 HWP/HWPX일 수 있다. `pdftotext`로 물리 페이지를 검증한다.
`--check-only`는 frozen binding·PDF 추출·근거 검사를 확인하되 DB 문서 소속 및 ClamAV
검사는 적재 시 수행한다. 출력에 원문·프롬프트·경로를 기록하지 않는다.
추가 Qwen 호출, 기존 리뷰 변경, 정책 활성화는 없다. 후속 모델 실행 결과도 같은 frozen
파일 계약으로 명시적으로 적재한다. 기존 권고 worker를 새 요약 worker로 교체하지 않는다.
