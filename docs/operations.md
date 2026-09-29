# 운영 절차

## 운영 기준선

- 운영 정본은 PostgreSQL 17의 `bidops` schema와 버전 관리가 켜진 MinIO 객체 저장소다.
- `docker-compose.yml`이 웹, DB, 객체 저장소, 악성코드 검사, 문서 worker, 분석 worker, 첨부 worker의 기준 배포 파일이다.
- 모든 Compose 명령에는 전용 `COMPOSE_PROJECT_NAME`을 사용한다. 다른 worktree의 컨테이너와 volume을 중지하거나 삭제하지 않는다.
- 일상 운영에서 `docker compose down -v`, volume 삭제, 원본 객체 삭제를 사용하지 않는다.
- legacy notice attachment의 id 기반 다운로드 호환 사본은 `/app/web/data/attachments`에 있다. 같은 부모의 `/app/web/data/profile-snapshots`는 승인 프로필 projection이 읽는 artifact이므로 Compose named volume `web-data`가 `/app/web/data` 전체를 보존한다. 업로드는 quarantine·ClamAV 검사 후에만 등록된다.

## Compose 파일과 조합

기반 파일 하나에 목적별 overlay를 더해 쓴다. overlay를 붙이지 않으면 그 기능과 그
네트워크는 열리지 않는다.

| 파일 | 여는 것 | 함께 쓰는 env |
|---|---|---|
| `docker-compose.yml` | 웹·DB·객체 저장소·검사·worker. network는 전부 internal이고 host에 아무것도 publish하지 않는다 | `.env` |
| `docker-compose.edge.yml` | 관리 화면을 host loopback에 publish(`web` 포트 선언을 이 파일이 소유) | `.env` |
| `docker-compose.model-egress.yml` | 승인된 vLLM으로의 egress와 `screening`·`overview`·`deep_review` 설정 | `env/model.env` |
| `docker-compose.c2-order-plan.yml` | C-2 발주계획 판정의 승인 입력 파일 마운트와 실행 토글 | `env/model.env` |
| `docker-compose.prespec-attachment.yml` | 사전규격 첨부 worker의 G2B egress와 취득 활성화 | `env/prespec-attachment.env` |
| `docker-compose.mock-reference.yml` | 모델 없이 상태 전이만 확인(egress 없음) | 없음(파일 안에 리터럴) |

자주 쓰는 조합은 세 가지다.

```bash
# 1) 화면만 열기 (모델 호출 없음)
docker compose -f docker-compose.yml -f docker-compose.edge.yml up -d web

# 2) 사전규격 파이프라인 (판정·개요·심층 검토 + 첨부 취득)
docker compose --env-file .env --env-file env/model.env --env-file env/prespec-attachment.env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.model-egress.yml -f docker-compose.prespec-attachment.yml \
  up -d web document-worker analysis-worker prespec-attachment-worker

# 3) C-2 발주계획 판정
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.model-egress.yml -f docker-compose.c2-order-plan.yml \
  up -d web analysis-worker
```

`--env-file`을 명시하면 기본 `.env` 자동 로드가 꺼지므로 공통 파일과 overlay 파일을
함께 넘긴다. `scripts/run-prespec-workflow.sh`와 `scripts/run-order-plan-workflow.sh`가
이 조합을 그대로 가지고 있으므로 손으로 조합하기 전에 먼저 본다.

### 없어진 파일

2026-09-12 정리에서 `docker-compose.screening.yml`과 `docker-compose.remote-vllm.yml`은
`docker-compose.model-egress.yml`·`docker-compose.c2-order-plan.yml`로 나뉘어 합쳤고,
`env/screening.env`·`env/vllm.env`는 `env/model.env` 하나로 합쳤다. SQLite 이전 입력을
다루던 `docker-compose.sqlite-ops.yml`과 `web/container-ops.sh`는 PostgreSQL이 정본이 된 뒤
쓰이지 않아 제거했다. 이전 시점에 만들어진 `bidops_bidops-web-data`·`bidops_bidops-backups`
volume은 자동으로 지워지지 않으므로 내용을 확인한 뒤 사람이 제거한다.

## 현재 배포 차단 조건

**알려진 운영 배포 차단 조건은 2026-09-01에 전부 해소했다.** MinIO versioning은 bootstrap에서
fail-closed로 검증하고, PostgreSQL·MinIO는 internal network에만 있어 host에 publish되지
않는다. 관리 접근은 `docker compose exec`로만 한다.

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
make build     # 모든 buildable Compose image 빌드; 컨테이너 실행·migration 없음
make up        # 기존 PostgreSQL·MinIO·ClamAV·문서 worker·웹 시작, 최대 60초 준비 대기
make status    # 위 서비스 상태 확인
make health    # 실제 웹 port의 API·화면 응답 확인
make logs      # 웹 로그 실시간 확인, Ctrl+C로 로그 보기 종료
make restart   # 웹 컨테이너만 재시작
make stop      # 웹 컨테이너만 중지; DB·저장소·worker 유지
make down      # 현재 Compose 프로젝트의 모든 서비스 중지; 컨테이너·volume 유지
```

`make start`는 `make up`과 같다. `COMPOSE_PROJECT_NAME` 기본값은 `bidops`이며 다른
배포를 관리할 때는 `make status COMPOSE_PROJECT_NAME=<전용 프로젝트명>`처럼 지정한다.
대기 시간은 `WAIT_TIMEOUT=120`, 로그 줄 수는 `LOG_TAIL=200`으로 바꿀 수 있다.

이 명령은 이미 설치된 컨테이너를 사용한다. 현재 컨테이너에 반영된 정적 UI와 배포 설정을
유지하며, 컨테이너가 빠져 있으면 시작 전에 최초 기동 절차를 안내하고 종료한다. `make up`은
Compose service dependency를 따라가지 않고 현재 프로젝트의 정확한 컨테이너 ID만 `docker start`로
시작한다. PostgreSQL·MinIO health와 ClamAV·문서 worker의 running 상태를 확인한 뒤 웹을 시작하고,
`WAIT_TIMEOUT` 안에 API와 화면 응답을 확인한다. DB·MinIO 초기화, migration, 분석·수집 worker
시작, 이미지 빌드·컨테이너 재생성은 포함하지 않으며 분석·수집 worker를 자동으로 재개하지 않는다.

`make stop`은 웹만 중지하고, `make down`은 현재 `COMPOSE_PROJECT_NAME` 프로젝트의 모든 서비스를
중지한다. 둘 다 컨테이너와 volume을 삭제하지 않는다. `make down`에는 서비스 인수를 주지 않아
다른 Compose 프로젝트는 건드리지 않는다.

`make build`는 모든 buildable Compose image를 빌드하는 작업이다. 새 image를 만들어도 이미 존재하는
컨테이너(중지된 컨테이너 포함)가 그 image로 바뀌지는 않는다. 새 image를 반영하는 배포는 명시적으로
컨테이너를 재생성하고, migration은 준비된 DB에 대해 별도 일회성 컨테이너로 실행한다.

```bash
COMPOSE_PROJECT_NAME=bidops docker compose -f docker-compose.yml \
  run --rm --no-deps migrate
```

위 migration 명령은 DB 역할 초기화와 백업·점검을 마친 뒤 운영자가 명시적으로 실행한다. 평상시
`make up`에서는 실행하지 않는다.

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
tailscale serve --bg --tcp=18787 tcp://127.0.0.1:18787   # 켜기
tailscale serve --tcp=18787 off                          # 끄기
tailscale serve status
```

**`--http=`가 아니라 `--tcp=`를 쓴다.** HTTP 모드는 요청의 Host 헤더를 등록된
MagicDNS 이름과 대조하므로, 다른 노드가 **tailnet IP로** 붙으면 어느 핸들러에도
걸리지 않아 tailscaled가 `404 page not found`를 돌려준다(2026-09-12 실측).
TCP 포워딩은 Host를 보지 않으므로 IP·MagicDNS 이름·IPv6 세 경로가 모두 동작한다.

확인은 **다른 노드에서** 한다. 같은 호스트에서 자기 tailnet IP로 붙는 것은 hairpin이라
정상 구성에서도 연결이 안 된다 — 이것을 장애 근거로 읽지 않는다. 호스트에서는
`curl http://127.0.0.1:18787/api/health`까지만 확인할 수 있다.

이 설정은 tailscaled가 보관하므로 재부팅 후에도 남는다. Funnel(공개 인터넷 노출)은 켜지
않는다. WSL2 mirrored 네트워킹에서는 Hyper-V 방화벽 기본 inbound가 Block이라 컨테이너
포트를 tailnet 주소에 직접 bind해도 다른 노드에서 닿지 않는다. 이 proxy 경로가 그 제약을
받지 않는 이유는 tailscaled가 연결을 받아 host loopback으로 넘기기 때문이다.

## 최초 기동

### 기존 화면을 유지하는 사전규격 비교 서버

기존 `bidops` 프로젝트의 DB·MinIO·ClamAV가 실행 중일 때, 비교 overlay는
`web-comparison`만 추가한다. 기존 `web`(18787)을 재생성하지 않으며 별도 이미지와
18887 포트를 쓴다. 포트가 사용 중이면 `BIDOPS_COMPARISON_WEB_PORT=18888`을 명시한다.
두 웹은 같은 데이터를 사용하므로 어느 쪽에서 저장해도 양쪽에 반영된다.

```bash
COMPOSE_PROJECT_NAME=bidops docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.luna-max-comparison.yml build web-comparison
COMPOSE_PROJECT_NAME=bidops docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.luna-max-comparison.yml up -d --no-deps --no-build web-comparison
curl --fail http://127.0.0.1:18787/api/health
curl --fail http://127.0.0.1:18887/api/health
```

비교용 worker·migration·수집기는 실행하지 않는다. 원격 확인이 필요하면 기존 18787
전달은 유지하고 `tailscale serve --bg --tcp=18887 tcp://127.0.0.1:18887`을 추가한다.
WSL mirrored 환경에서 비교 컨테이너를 재생성할 때 해당 비교 포트의 serve만 잠시
끄고 기동 후 복원한다. 비교를 마칠 때는 위 Compose 파일 조합으로
`stop web-comparison`만 실행하며 전체 프로젝트 `down`이나 볼륨 삭제를 하지 않는다.

```bash
cp .env.example .env
cp env/model.env.example env/model.env
export COMPOSE_PROJECT_NAME=bidops
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d postgres minio clamav
./scripts/init-runtime.sh
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.model-egress.yml \
  up -d web document-worker analysis-worker
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

`--env-file`을 명시하면 기본 `.env` 자동 로드가 꺼지므로 공통 파일과 overlay 파일을 함께 넘긴다. overlay 없이 기동할 때는 `--env-file` 없이 `.env`가 자동 로드된다.

`scripts/init-runtime.sh`는 DB 역할 초기화, Alembic migration, MinIO 버킷·정책 초기화를 순서대로 실행한다. 앱 startup은 이 작업을 대신하지 않는다. `bidops-source`, `bidops-structure`, `bidops-quarantine`, `bidops-model-response` 버킷은 versioning과 최소 권한 정책을 유지한다.

`migrate` service는 Alembic 성공 뒤 `scripts/runtime-privileges.sql`을 적용한다. 이 단계는 이전 blanket grant를 먼저 회수하고 현재 head의 table·operation allowlist를 다시 부여한다. 새 table은 `app`·`worker` 기본 DML을 받지 않으므로 migration에 runtime write path가 추가되면 같은 변경에서 allowlist와 역할 smoke test를 갱신해야 한다. `ro_backup`만 현재·향후 table의 `SELECT` 기본 권한을 유지한다.

사전규격 검토 제외·복원 배포의 기대 head는 `0030_prespec_review_exclusion`이다.
`notice`에 현재 제외 상태와 마지막 담당자·사유·시각 네 열을 추가하고 기존 건은
included/null로 읽는다. `scripts/runtime-privileges.sql`의 app 열 한정 UPDATE 네 열을
migration과 함께 적용해야 한다. worker 권한과 모델 설정은 바꾸지 않는다.

적용 순서는 전체 백업(`backups/postgres/full/`, 객체 manifest 포함)과
`before-prespec-review-exclusion-<날짜>` 롤백 태그 확보 → 실행 직전 사람 확인 →
서비스 중지·기존 migration 명령으로 head/권한 적용 → 재배포 직전 별도 사람 확인 →
기존 운영 Compose 조합으로 서비스 교체다. migration 승인만으로 재배포하지 않는다.
적용 뒤 `/api/health`, `/api/pre-specs?workspace=all&limit=1`의 새 네 필드,
`/api/pre-specs?workspace=actionable&review_exclusion=excluded`의 total=0을 조회한다.
운영 검증을 위해 실제 공고를 임의로 제외하거나 SQL로 상태를 보정하지 않는다.
이 revision은 사람 변경 정보 보존 때문에 downgrade를 제공하지 않으며 복구는 검증한
배포 전 백업을 별도 DB에 복원하는 기존 절차를 따른다. 코드 검증은 운영 적용 증거가 아니다.

첨부 worker의 자동 준비 경로가 필요로 하는 묶음·큐 INSERT를 worker에 부여한다. 사전규격 첨부 취득이 종결되면 `prespec-attachment-worker`가 같은 프로세스에서 문서 묶음을 만들고 확정한 뒤 개요 run을 큐에 넣으므로, worker 역할은 `document_bundle`·`document_bundle_item`·`idempotency_record`·`work_job` INSERT와 확정에 쓰는 열만 여는 `document_bundle`·`document_bundle_item` 열 한정 UPDATE, 잠금용 `document_structure (id)` UPDATE를 갖는다. 확정은 문서 집합·순서가 그대로면 기존 draft 항목을 지우지 않고 제자리로 갱신하므로 이 권한만으로 끝난다. 이 권한이 없으면 자동 준비가 SQLSTATE `42501`로 막히고 운영자가 app 역할의 보정 명령을 대신 실행해야 한다. worker는 어느 table에도 DELETE를 갖지 않으며, 권한을 바꿀 때는 `scripts/runtime-privileges.sql`과 역할 smoke test를 같은 변경에서 갱신하고 migration 단계로 다시 적용한다.

사설 vLLM 없이 웹과 문서 준비만 확인할 때는 model-egress overlay를 빼고 기동할 수 있다. 이 경우 분석 worker가 모델 단계에서 실패하는 것은 정상이며 성공으로 보정하지 않는다.

`env/model.env`에는 쓰는 용도만 채운다. 비워 둔 용도는 endpoint가 빈 문자열로 남고,
그 용도의 호출은 `resolve_model_endpoint`가 네트워크 접촉 전에 거부한다. C-1 판정만
할 때도 overview·deep_review 값을 요구하지 않고, 그 반대도 마찬가지다.

overlay 추가만으로 egress가 안전해지지 않는다. host firewall의 목적지 제한과 실제 endpoint 승인을 함께 확인한다.

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
보장이다. 한 바퀴에서 C-2 → 심층 → 회사 핏 → 개요 순서로 **하나만** claim한다. 각 단계를 따로 띄우는 명령을
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
python -m app.deep_review.cli --help        # run-bc-e2e, run-prespec-e2e, import-profile-policy, enqueue-overview, prepare-overviews
python -m app.lifecycle.ingest.cli --help   # --run <회차> | --all
```

적재 CLI는 `BIDOPS_MODULES`가 고른 모듈의 lifecycle 확장점을 web 프로세스(`create_app`)와
**같은 선택으로 등록한 뒤** 적재한다(2026-09-19 수정). 즉 CLI로 적재해도 판정·리뷰 적재와
사전규격 첨부 자격 재평가가 web API 적재와 같게 돈다. 등록한 모듈 이름은 stderr에
`extensions: screening, deep_review` 한 줄로 찍히며 stdout은 JSON 결과만 낸다.
`BIDOPS_MODULES=lifecycle`로 좁히면 제공자가 없으므로 회차에 `judgment_ingest_skipped`
경고가 남고, 그 회차는 C-2 실행의 source run으로 쓸 수 없다.

수동 발주계획·사전규격 참조 실행은 아래 단계형 wrapper를 사용한다. 둘 다 기존 회차를
덮어쓰지 않으며, live 모델을 쓸 수 있는 `start-worker(s)`·`run`·`run-c1`·`enqueue`·`all`에는
그 명령 한 번에만 유효한 `--approve-model-call`이 필요하다. `all`은 장시간 대기하지 않고
worker와 실행을 올린 뒤 반환하므로 `status`로 진행을 확인한다.

```bash
scripts/run-order-plan-workflow.sh --help
scripts/run-prespec-workflow.sh --help
```

발주계획 wrapper는 C-2 Phase 0 validator가 `execution_allowed=true`일 때만 `all`을 진행한다.
사전규격 wrapper는 승인된 active C-1 policy, 활성 profile/policy UUID, 개요·회사 핏 참조 실행
설정이 모두 있어야 worker를 올린다. 이 검사는 품질 승인이나 방화벽 승인을 대신하지 않는다.

## 환경 파일 배치

| 파일 | 소비하는 compose | 담는 값 |
|---|---|---|
| `.env` | `docker-compose.yml`, `docker-compose.edge.yml` | 프로세스 정체성, 로그, DB·MinIO 자격증명, 암호화 키, 화면 port, 승인 profile/policy 참조 |
| `env/model.env` | `docker-compose.model-egress.yml`, `docker-compose.c2-order-plan.yml` | 용도별 `BIDOPS_VLLM_{SCREENING,OVERVIEW,DEEP_REVIEW}_*`, 공유 `BIDOPS_VLLM_*`, C-2 입력 파일 host 경로 |
| `env/prespec-attachment.env` | `docker-compose.prespec-attachment.yml` | `BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS` |
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

### 발주계획 일괄 추적 결과 확인

- 응답 유실·시간 초과는 실패 건수가 아니라 **결과 미확인**이다. 같은 탭의 저장된 요청 결과 확인으로 원래 request UUID·대상·담당자·사유를 재전송한다. 새 UUID로 대체하거나 기존 receipt를 수정·삭제하지 않는다.
- 운영자가 DB를 조회할 때는 `bidops.idempotency_record`의
  `operation = 'order_plan_tracking_bulk_start'`와 `request_id`로 찾는다.
  `response_status`, `response_snapshot`의 `completed_at`·`summary`·`items`가 최초 완료 결과다.
  이는 현재 추적 상태의 projection이 아니므로 이후 단건 결정과 달라도 receipt를 보정하지 않는다.
- 같은 request ID의 `bidops.audit_event`에서
  `action = 'opportunity.tracking_status.changed'`인 건수는 receipt의
  `succeeded_owner_count`와 대응한다. 한 소유자에 여러 plan이 있더라도 감사는 한 건이며,
  같은 요청 replay로 늘지 않는다. 담당자·사유나 receipt 전문을 일반 로그·오류 보고서에 복사하지 않는다.
- 항목 실패가 있는 **완료 결과를 확인한 뒤에만** 실패 건 재시도를 새 요청으로 확인한다.
  `idempotency_conflict`는 다른 payload가 같은 key를 사용한 상태이지 새 key 자동 발급 지시가 아니다.
  손상된 저장 결과는 안전 오류로 닫으며 PATCH 반복으로 우회하지 않는다.
- 후처리 hook은 commit 뒤 best effort이다. hook 장애가 사람 결정을 취소하지 않으며,
  replay가 hook의 durable 재전달을 보장하지 않는다. 별도 작업 큐·migration·모델 정책·egress 변경은 없다.

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
| 외부 참조 | `BIDOPS_OPENAI_ENABLED`, `BIDOPS_REFERENCE_WORKFLOW_MODE` | 기존 `BIDOPS_ANALYSIS_PROVIDER=vllm|mock`는 유지한다. ADR-0069의 사용자 요청 사전규격 Luna만 정책 provider `codex-exec`와 전용 overlay로 별도 실행한다. 향후 발주계획 전용 projection에서만 공개 plan metadata+최소 승인 요약을 preview·건별 승인 후 전송 |

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

### 일일 수집·선별 적재 (`scripts/run-daily-lifecycle.sh`)

위 운영 목표 중 발주계획·사전규격·입찰공고 수집과 선별 적재를 실행하는 host 스크립트다.
`--track order-plans|notices`(필수, 기본값 없음)로 **한 번에 한 트랙만** 돌고, `--date YYYY-MM-DD`
(기준일, 한국시간, 생략 시 **전일**)를 받는다. 발주계획 트랙은 기준일 **하루**, 공고 트랙은 기준일을
포함한 **4일**을 수집한다. 사전규격은 조회 기준인 등록일시(`rgstDt`)보다 공개(접수일시 `rcptDt`)가
최대 3일 늦을 수 있어 하루 창이면 영구히 빠지는 건이 생긴다(2026-09-18 측정). 겹쳐 다시 관측된
공고는 적재에서 no-op이며 첨부·문서 묶음·개요 검토를 다시 만들지 않는다
([ADR-0061](tracking/decisions/0061-daily-collection-window.md)). 트랙 안에서는 첫 실패에서 즉시
멈추고(`set -euo pipefail`), 두 트랙은 서로의 성공을 전제하지 않는다.

1. Preflight: `manual-workflow-common.sh`의 web 헬스체크. `BIDOPS_G2B_API_KEY` 존재 확인은
   collector 자신이 하므로 스크립트는 별도로 값을 읽거나 출력하지 않는다.
2. 발주계획 트랙(`--track order-plans`): 아래 다섯 단계가 항상 함께 돈다(`--c2` 같은 부분 실행
   플래그는 없다) — ① 자동 실행 확인 `GET /api/order-plan-screening/daily-trigger`. 응답의
   `effective_enabled`가 `false`이면 `daily_trigger_off`와 `reasons[]`, "policy를 교체하면 자동
   실행이 멈춥니다. 새 버전에서 다시 켜야 합니다." 안내문구를 출력하고 **수집 없이** exit 0(다음 절
   참조). 실행에 쓸 `policy_version`도 이 응답에서 받는다. ② 발주계획을 회차
   `lifecycle-<YYYYMMDD>-plans`로 수집한다(`collect_order_plans.py --from-date <기준일> --to-date
   <기준일+1일>`, `--to-date`는 제외구간). ③ `ingest.cli --run <plans> --collection` →
   `--tracked-backfill`. 이어서 `GET /api/runs/<회차 디렉터리>`로 **정규 회차 id**
   (`<디렉터리>--<generated_at>Z`, 적재가 만드는 `Run` 기본키)를 받는다 — 아래 ④·⑤와 실행 목록
   조회·attempt 계산은 전부 이 값을 쓴다. 한 디렉터리에 `Run` 행이 둘 이상이면 어느 것을 판정할지
   추정하지 않고 멈춘다. ④ C-2 실행 요청(`POST /api/order-plan-screening/executions`, 헤더
   `X-BidOps-Trigger: daily_script`, 202를 폴링해 종결 상태까지 기다린다). ⑤ 종결 뒤 감사 표본 draw
   (`POST /api/order-plan-screening/executions/{id}/audit-sample`). 회차·실행·draw의 스킵·재시도
   규칙은 `scripts/run-daily-c2.sh`가 정하며(아래), 발주계획 트랙은 이 스크립트를 그대로 부른다.
3. 공고 트랙(`--track notices`): 사전규격·입찰공고를 회차 `lifecycle-<YYYYMMDD>-notices`로
   수집한다(`collect_notices.py --from-date <기준일−3일> --to-date <기준일> --tag-bid-sw-industry`, 이
   collector의 `--to-date`는 포함구간). 사전규격·입찰공고 스킵 플래그는 쓰지 않아 전량이 한 회차에
   담기고, 입찰공고에는 1468(SW 유사업종) 표시가 함께 붙는다. 이어서 회차를 web 컨테이너로 복사하고
   `ingest.cli --run <notices> --collection` → `--tracked-backfill` → 첨부 취득 자격 갱신
   (`refresh_fetch_eligibility`) 순서로 적재한다.
4. 적재 순서는 트랙 사이에 고정하지 않는다. 공고 선별이 읽는 발주계획 상태는 사람이 정한 추적
   상태(`계속 추적`·`보류`·`종료`)이고, 기준일 하루 창으로 들어온 발주계획에는 아직 추적 상태가 없으므로
   같은 날 발주계획이 먼저 적재됐는지가 공고 선별 결과를 바꾸지 않는다. `--tracked-backfill`은 두 트랙
   끝에서 각각 부르며 다시 불러도 no-op이다.

각 기준일은 그 날짜가 처음 걸리는 단계에서 이어 돈다 — `complete`(회차가 완결이고 web에 `Run`
행도 있음, 할 일 없음), `empty`(완결이고 `counts.total == 0`, 적재 없이 종료), `ingest_pending`
(완결인데 `Run` 행이 없음, 적재만), `collect_new`(회차 디렉터리 없음, 수집부터),
`collect_retry<N>`(불완전한 디렉터리가 있으면 **그 디렉터리는 그대로 두고**
`lifecycle-<YYYYMMDD>-<plans|notices>-retry<N>`(가장 작은 미사용 N)으로 새로 수집). 발주계획
트랙은 회차가 비어 있지 않으면 이 뒤에 더 이어간다 — `성공`·`부분 성공` 실행이 없으면 실행부터,
있는데 감사 표본이 아직 안 뽑혔으면 draw만. 회차 디렉터리는 회차 원본 불변 원칙에 따라 절대
덮어쓰거나 지우지 않는다.

`--collect-only --run-suffix <name>`은 측정·점검용이다. preflight·자동 실행 확인·회차 조회·적재·
C-2를 전부 건너뛰고 수집만 하며 회차 id는 `lifecycle-<YYYYMMDD>-<plans|notices>-<name>`이 되어
일일 회차 id를 차지하지 않는다(`retry<N>`은 재수집 접미사로 예약돼 쓸 수 없다).

`--dry-run`은 계산한 회차 id·창·각 단계의 정확한 명령만 출력하고 수집·적재·C-2 실행·Docker 호출을
하지 않는다(preflight의 web 헬스체크와 web `Run` 조회도 건너뛰고, 완결 회차는
`complete_or_ingest_pending`으로만 표시한다). 기존 회차 디렉터리가 있으면 절대 덮어쓰지 않고 즉시 멈춘다(회차는
불변). 이 스크립트는 아무것도 삭제하지 않고 cron을 설치하지 않으며, 스크립트 자체는 모델을 호출하지
않는다 — 발주계획 트랙이 요청하는 C-2 실행은 승인된 binding 아래 분석 워커에서 돈다.

**스킵의 세 가지 뜻이 다르다.**

| 뜻 | 값 | exit |
|---|---|---|
| 정상 스킵(할 일 없음) | `daily_trigger_off`, `empty_population`, `active_execution_exists`, `already_executed`, `retry_limit_reached`, POST가 `policy_not_active`·`daily_trigger_off`·503으로 답함 | 0 |
| 트랙을 그 자리에서 멈추는 스킵(따라잡기 중이면 나머지 날짜도 같은 사유로 끝난다) | `daily_trigger_off`, `policy_not_active`, 503, `active_execution_exists` | 0 |
| 다음 날짜로 넘어가는 스킵(따라잡기가 이어진다) | `already_executed`, `empty_population`, `retry_limit_reached` | 0 |

그 밖의 실패는 exit 비0이며 `set -euo pipefail`로 그 트랙을 즉시 멈춘다. 같은 날 재시도까지
실패해도 exit는 비0이다(아래 재시도 규칙).

`active_execution_exists`에는 예외가 하나 있다. 스킵할 때 그 실행의 id·상태·경과 시간을 함께
출력하고, 경과가 `BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS`의 **2배를 넘으면 exit 비0**이다. 워커가
죽어 `대기`로 굳은 실행은 제품 워커의 stale 회수 대상이 아니어서(회수 대상은 `실행 중`·`중지 요청`뿐이고
그나마 살아 있는 워커가 다음 작업을 집을 때만 돈다) 그대로 두면 매일 조용히 exit 0으로 건너뛰기만
한다. 이 경우 워커 상태를 확인하고 실행을 `POST /api/order-plan-screening/executions/<id>/stop`으로
닫은 뒤 다시 돌린다.

**발주계획 트랙 전용 환경변수** (`scripts/run-daily-c2.sh`·`scripts/c2-execution-common.sh`가 읽는다):

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `BIDOPS_C2_DAILY_ACTOR` | 없음(필수) | C-2 실행·audit 요청에 실리는 담당자 이름. 감사 표식일 뿐 인증이 아니다. 없으면 시작하지 않는다 |
| `BIDOPS_C2_DAILY_RETRY_WAIT_SECONDS` | 600 | 그 날짜의 실행이 `실패`·`중단됨`뿐일 때, 자동 재시도(attempt+1) 전에 기다리는 시간 |
| `BIDOPS_C2_DAILY_POLL_TIMEOUT_SECONDS` | 7200 | 실행을 종결 상태까지 기다리는 최대 시간. 넘기면 exit 비0으로 스크립트는 멈추지만 실행 자체는 분석 워커에서 계속 진행되고, 다음 호출은 `active_execution_exists`로 건너뛴다 |
| `BIDOPS_C2_DAILY_POLL_INTERVAL_SECONDS` | 30 | 폴링 주기 |

**복구 절차.** 자동 재시도(attempt 2)까지 실패한 회차는 `attempt > 2`로 `retry_limit_reached`
스킵을 낸다 — 이후로는 자동 재시도하지 않는다. 사람이 재개할 때만
`scripts/run-daily-c2.sh <plans run id> --extra-attempt`를 쓴다. 회차 id는 디렉터리 이름
(`lifecycle-<YYYYMMDD>-plans`)으로 줘도 되고 정규 id로 줘도 된다 — 스크립트가 `GET /api/runs/<id>`로
정규 id를 확정한 뒤 C-2를 부른다. `retry_limit_reached` 안내에는 정규 id가 실린다. 헤더 `X-BidOps-Trigger:
manual_resume`으로 실행 하나만 만들고 자동 재시도는 없다. `--dry-run`으로 먼저 계획된 요청을
확인할 수 있다. `retry_limit_reached`를 출력할 때 이 명령을 함께 안내한다.

**스케줄은 기본 비활성이다.** 아래는 실행 예시일 뿐이며 이 저장소는 이 줄을 설치하지 않는다(스케줄러·
always-on 기본 비활성 원칙, `CLAUDE.md`). 트랙마다 한 줄이고 시각은 운영 결정이다. 발주계획 줄은
아래 "C-2 발주계획 선별 활성화 절차"를 마친 뒤에만 설치하고 `BIDOPS_C2_DAILY_ACTOR`를 함께 준다.

```cron
# 문서용 예시 — 설치되어 있지 않음. crontab -e로 운영자가 직접 추가할 때만 참고한다.
# 먼저 한 번: mkdir -p ~/.local/state/bidops/logs
# flock -n: 앞 실행이 아직 돌고 있으면 그 날 줄은 아무것도 하지 않고 끝난다(회차 중복 방지).
# timeout: 멈춘 실행을 끊는다. 발주계획은 폴링 2시간 + 재시도 대기 10분 + 2회차 2시간이 최대이므로 6h로 둔다.
#          timeout이 스크립트를 끊어도 C-2 실행 자체는 분석 워커에서 계속 돌고, 다음 날은
#          active_execution_exists로 건너뛴다(경과가 길면 비0으로 끝나 사람이 본다).
# crontab에서 %는 \%로 적어야 한다. 로그는 저장소 밖에 쌓아 회차·보고서와 섞지 않는다.
30 6 * * * cd /path/to/bidops && flock -n ~/.local/state/bidops/notices.lock timeout 3h ./scripts/run-daily-lifecycle.sh --track notices >> ~/.local/state/bidops/logs/notices-$(date +\%Y%m).log 2>&1
# C-2 활성화·일일 자동 실행이 켜진 뒤에만 설치한다. BIDOPS_C2_DAILY_ACTOR는 감사 표식이며 인증이 아니다.
0 7 * * * cd /path/to/bidops && BIDOPS_C2_DAILY_ACTOR=<담당자 이름> flock -n ~/.local/state/bidops/plans.lock timeout 6h ./scripts/run-daily-lifecycle.sh --track order-plans >> ~/.local/state/bidops/logs/plans-$(date +\%Y%m).log 2>&1
```

**보관**: 회차 디렉터리(`data/runs/lifecycle-*`)는 불변이며 자동으로 지우지 않는다. 보관
기간 정책은 운영자가 수동으로 정하는 결정이며 이 스크립트는 삭제 로직을 갖지 않는다.

**중단 기준**: 아래 중 하나면 실행을 멈추고 원인을 확인한 뒤 그날 몫을 다시 실행한다.
- collector(수집 단계)가 0이 아닌 코드로 종료.
- 적재 뒤 `GET /api/runs/<run_id>/warnings`에 차단 등급 경고가 있음. 이 조회는 회차 **디렉터리
  이름**도 받아 준다(`GET /api/runs/{id}`가 `<디렉터리>--%`로 alias를 풀기 때문이다). 반면 C-2
  실행 생성·조회는 정규 id만 받고 디렉터리 이름에는 409 `source_run_incomplete`으로 답한다 —
  화면·warnings 조회에서 되던 표기가 C-2에서 안 되는 이 비대칭이 B-1의 원인이었다
  (`docs/tracking/findings.md`). 손으로 C-2를 부를 때는 `GET /api/runs/<디렉터리>` 응답의
  `run_id`를 쓴다.
- 수집 결과의 `sw_industry_1468.status != complete`(조회 실패·부분 수집). 이 경우 1468
  표시는 해당 입찰공고에서 `null`로 남아 `bid_sw_industry_competitive` 선별 사유로
  적재되지 않는다 — 다음 날 창에서 같은 공고가 다시 조회되면 자연히 회복되므로, 그날은
  값을 추정해 채우지 말고 다음 날 재실행으로 넘긴다.
- 발주계획 트랙에서 `daily_trigger_off`·`policy_not_active`·503이 아닌 사유로 C-2 실행이 멈춤,
  또는 `retry_limit_reached`가 반복됨 — `--extra-attempt`로 성급하게 재개하기 전에 원인을 본다.

### C-2 발주계획 선별 활성화 절차

발주계획 트랙(위 절)은 이 절차를 전부 마치기 전까지 매일 `daily_trigger_off`로 끝나고 수집하지
않는다. 열두 단계이며 ①~③은 사람 결정 값이 필요하고, 나머지는 그 값이 갖춰진 뒤의 명령·화면
동작이다(`docs/0918_daily-operation/spec.md` §0ⓑ·§3·§4·§11).

1. **gold 확정.** 사람이 확정한 발주계획 정답 표본. 표본 크기와 최종 승인은 운영 결정이다.
2. **임계값 4개.** `threshold_recall_pct`·`threshold_precision_pct`·`threshold_important_missed_max`·
   `threshold_review_load_max`(검토량은 **하루** 기준). 값이 없으면(`null`) 게이트는 `미측정`만
   기록한다 — fail closed가 정상 동작이다.
3. **감사 표본 값.** policy `audit_sample.max_per_execution`·`review_cadence`·`enabled`와 **층
   규칙** `audit_sample.strata_rules`([`docs/contracts.md`](contracts.md) "감사 표본 REST" 참조).
   값이 없으면 draw는 매일 `pending_human_approval`로 끝난다. 2026-09-19 결정으로 v4에
   들어갔다 — `enabled=true`, `max_per_execution=10`, `review_cadence="weekly_mon_thu"`,
   `strata_rules.classification_proximity={contract_method: [제한경쟁, 일반경쟁]}`,
   `strata_rules.performance_similarity_proximity={rank_window: 25}`. **PoC용 값이며 운영
   전환 때 다시 정한다.**
4. **v4 policy·binding·generation config 발행 → 컨테이너 마운트.** 2026-09-19에 발행했다(S3b).
   **`model_digest`를 바꾸면 generation config도 함께 새로 발행해야 한다** — 워커가 동결된
   `generation-config.json`의 `model_revision`을 binding `model_digest`와 대조한다
   (`workers/order_plan.py:383-391`). v3는 이 대조에서 걸려 실행되지 않았다
   ([findings](tracking/findings.md)).

   | 파일 | sha256 |
   |---|---|
   | `…/order-plan-screening-generation-config.v5.json` | `82ced6035d95313f889cd32cc3b5b414b98334f5f090745f0cedb0564804a405` |
   | `…/order-plan-screening-policy.v4.json` | `c5abe3e3fbd3a628486e8a3ee05ce009ac488c9b9df8e83a0f0c22cd6d877461` |
   | `…/order-plan-screening-phase0-binding.v4.json` | `682cb16dd2ac5ed622386a6cea42891633659f2d8073c3bcb6e1af419087790c` |

   generation config v5는 v4에서 `model_revision`(→ `5fa804ff…`)과 `method_version`
   (→ `vllm-qwen-order-plan-batch-nonthinking-v5`) 둘만 다르다. `docker-compose.yml`의
   web(`:180-182`)·analysis-worker(`:250-252`) 마운트 세 줄과 `app/core/config.py`의
   `BIDOPS_C2_POLICY_PATH`·`BIDOPS_C2_BINDING_PATH`·generation config 기본 경로(`:308-312`)가
   같은 변경에서 v4·v5를 가리킨다. v2·v3 파일과 generation config v4는 고치지 않았다.
   **운영 반영은 아직이다**: compose 변경을 반영한 컨테이너 재생성과 아래 적재 CLI 실행이
   남아 있다. 운영 DB의 `c2-order-plan-screening-v3` 행은 버전+digest가 immutable이라 그대로
   `activation_candidate`로 남으며, 필요하면 retire CLI로 내린다.

   ```bash
   python -m app.screening.c2_policy load \
     --policy experiments/order-plan-screening/config/order-plan-screening-policy.v4.json \
     --binding experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v4.json \
     --created-by <담당자 이름>
   ```

5. **전송 승인(D-d).** binding 튜플(policy, binding, model_digest, allowlist) 단위 승인이다.
   `BIDOPS_C2_EXECUTION_ALLOWED=true`와 host 방화벽·egress 승인이 함께 필요하다.
   2026-09-19에 v4 binding의 `external_transport`로 기록했다 — `execution_allowed=true`,
   `approval_scope="per_binding"`, `approval_required_per_execution=false`,
   `approved_by="jechoi"`, `model_digest=5fa804ff…`(2026-09-11·09-15 서버 선언 revision).
   **환경변수와 방화벽·egress 승인은 아직 남아 있다.**
6. **후보 지정.** 기준 화면(`발주계획 선별 정책` 탭, `/order-plan-policies`)에서 draft 행을
   `activation_candidate`로 올린다(`POST /api/order-plan-screening/policies/candidate`).
7. **gold 게시일별 파생 회차 만들기.**

   ```bash
   python3 skills/bidops-collect/scripts/split_order_plan_run_by_day.py \
     --input-run data/runs/order-plans-20260827-20260830-retry1
   ```

   gold 625건을 게시일별 4개 회차(308·290·9·18건, `data/runs/gate-gold-<YYYYMMDD>-plans`)로
   나눈다. 원본은 고치지 않는다. 각 회차를 컨테이너에 복사하고 적재한다.

   ```bash
   docker compose -f docker-compose.yml cp "data/runs/gate-gold-<YYYYMMDD>-plans" web:/app/data/runs/
   docker compose -f docker-compose.yml exec web \
     python -m app.lifecycle.ingest.cli --run "gate-gold-<YYYYMMDD>-plans" --collection
   ```

   적재 결과의 `warnings`가 **네 회차 모두 빈 배열**인지 확인한다. C-2 실행 생성은 source run에
   적재 경고가 하나라도 있으면 `409 source_run_incomplete`로 거부하며, 응답 message는 code별
   고정 문구라 사유가 보이지 않는다. 사유는 web 컨테이너 로그
   (`docker compose -f docker-compose.yml logs web | grep "c2 request rejected"`)와
   `GET /api/runs/<회차>/warnings`에서 읽는다.

   네 회차를 모두 적재한 뒤 게이트를 만든다(`POST /api/order-plan-screening/quality-gates`, 측정
   회차 4개를 `measurement_run_ids`에 고정. 요청 필드는 `docs/contracts.md`의
   `order-plan-quality-gate-create-request.v1`을 따른다).

   요청의 gold 관련 네 필드는 채점 도구가 계산한다. `scoring_input_sha256`은 **측정 전에
   고정되는 채점 입력의 digest**이고, 채점 때 다시 계산해 대조하면 게이트를 만든 뒤 gold나
   채점 도구가 바뀐 것을 잡는다.

   ```bash
   python3 scripts/score-c2-gate.py scoring-input \
     --gold data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv \
     --run-id gate-gold-20260827-plans --run-id gate-gold-20260828-plans \
     --run-id gate-gold-20260829-plans --run-id gate-gold-20260830-plans
   ```

   출력된 `gold_artifact_sha256`·`gold_manifest_sha256`·`gold_status`·`scoring_input_sha256`을
   게이트 요청에 그대로 넣는다. 임계값 4개와 `policy_sha256`·`binding_sha256`은 도구가 채우지
   않는다(사람 결정과 policy 행의 값이다).
8. **측정 실행 2회.** 같은 묶음(policy·binding·프롬프트·model digest·회사 역량)으로 두 번 돌려 둘
   다 통과해야 한다.

   ```bash
   BIDOPS_C2_GATE_ACTOR=<담당자 이름> scripts/run-c2-gate-measurement.sh \
     --policy-version <v> --gate-id <c2gate-...> --pass 1
   BIDOPS_C2_GATE_ACTOR=<담당자 이름> scripts/run-c2-gate-measurement.sh \
     --policy-version <v> --gate-id <c2gate-...> --pass 2
   ```

   이 스크립트는 게이트의 측정 회차를 순서대로 실행·폴링만 하고 채점하지 않는다.
9. **채점·기록.** 채점은 제품 밖에서 한다. `scripts/score-c2-gate.py`가 gold와 두 pass의
   실행 결과를 대조해 gate artifact 초안과 evaluations POST body 예시를 만든다. **도구는
   계산만 하고 아무것도 POST하지 않는다 — 사람이 artifact를 확인한 뒤 직접 제출한다.**

   ```bash
   # pass가 끝날 때마다 결과를 받아 둔다. 목록 API의 회차 모드는 그 회차의 "최신" 완료
   # 실행만 돌려주므로, pass 2를 돌리고 나면 pass 1의 결과는 REST로 읽을 수 없다.
   python3 scripts/score-c2-gate.py score \
     --gold data/experiments/order-plan-screening/20260827-20260830-gold-adjudicated-v2/review/gold-adjudicated-full-population.tsv \
     --api http://127.0.0.1:18787 --pass1 <실행 id 4개> \
     --out reports/c2-gate-pass1.json --dump-results reports/c2-gate-pass1-results.json

   # pass 2까지 끝나면 pass 1은 dump에서, pass 2는 REST에서 읽어 함께 채점한다.
   # --expect-scoring-input-sha256에는 게이트에 기록한 값을 그대로 준다.
   python3 scripts/score-c2-gate.py score \
     --gold …/gold-adjudicated-full-population.tsv --gate-id <c2gate-...> \
     --expect-scoring-input-sha256 <게이트의 scoring_input_sha256> \
     --results-json reports/c2-gate-pass1-results.json \
     --api http://127.0.0.1:18787 \
     --pass1 <pass 1 실행 id 4개> --pass2 <pass 2 실행 id 4개> \
     --out reports/c2-gate-artifact.json --summary-out reports/c2-gate-summary.md \
     --body-out reports/c2-gate-evaluation-body.json
   ```

   도구는 예측 양성을 검토 후보(`stage1_status=selected` ∧ `qwen_relevance∈{relevant,uncertain}`),
   gold 양성을 `effective_relevance=관련`, 중요 누락을 `effective_priority=높음`인 gold 양성의
   누락으로 센다. recall·precision·중요 누락은 게시일별 결과를 합산하고 검토량은 게시일별
   최댓값(하루 기준)이며, 분모가 0이면 `null`로 남긴다. gold와 네 실행의 모집단이 다르면
   오류로 멈추고, 실행 상태가 `성공`이 아니거나 gold 양성에 `label_source=draft`가 남아 있으면
   artifact와 stderr에 경고로 남긴다(막지는 않는다 — 사람이 판단한다). `metrics_json`의
   `reference_full_window`는 게시일별 결과를 창 전체로 pool한 값이며(검토량은 창 전체 합계),
   ADR-0037의 단일 625건 batch와는 batch 구성이 달라 직접 비교값이 아니다.

   사람이 `--out` artifact와 요약을 확인한 뒤, 출력된 body(같은 artifact의 `artifact_sha256`를
   담고 있다)를 `POST /api/order-plan-screening/quality-gates/{gate_id}/evaluations`로 기록한다.
   코드가 두 pass 중 나쁜 쪽 값을 넣고 판정한다(통과·미달·보류·미측정).
10. **활성화.** 활성화 화면(`발주계획 선별 정책` 탭)에서 policy digest·게이트 결과·런타임
    blocker를 확인한 뒤 승인한다. blocker가 하나라도 있으면 승인 단추는 비활성이다.
11. **자동 실행 켜기.** 같은 화면의 스위치(policy_version에 묶인 DB 행)를 켠다. 이것만으로는
    켜지지 않는다 — 운영자가 설치 때 한 번 환경 cap을 켜고 web을 재배포해야 한다.

    ```bash
    # env/model.env 또는 .env에 추가한 뒤
    BIDOPS_C2_DAILY_TRIGGER_ENABLED=true
    docker compose --env-file .env --env-file env/model.env \
      -f docker-compose.yml -f docker-compose.edge.yml \
      -f docker-compose.model-egress.yml -f docker-compose.c2-order-plan.yml \
      up -d --force-recreate web
    ```

    `docker-compose.c2-order-plan.yml`이 이 값을 web에 전달한다(base compose는 항상 `false`로
    고정한다). **policy를 교체하면 자동 실행이 멈춘다.** 스위치는 이전 버전에 묶여 있으므로 새
    버전에서 다시 켜야 한다.
12. **cron 발주계획 줄 설치.** 운영시작일부터 매 달력일. 앞선 날짜가 있으면 스크립트의
    `--from-date`/`--to-date`로 하루씩 따라잡는다.

**교체 없이 활성 policy를 내린다(예외).** 정상 경로는 위 10번 활성화가 이전 active 행을 같은
transaction에서 `retired`로 내리는 자동 교체다. 대체 버전 없이 자리를 비워야 할 때만 아래 명령을
쓴다 — 예외 운영 조치이며 사람 승인이 먼저다. SQL로 행을 직접 고치지 않는다(감사 기록이 남지
않는다).

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.screening.c2_policy retire \
    --policy-version <v> --retired-by <담당자 이름> --reason "<사유>"
```

`active` 행만 내려가고 `active_slot`이 비며 `activated_by`·`activated_at`·`quality_gate_status`는
이력으로 남는다. 같은 transaction에 `AuditEvent(action="c2.policy_retired")`가 쌓인다
(`replaced_by_policy_version`은 교체가 아니므로 `null`, `reason`·`via="cli"` 포함). 이미
`retired`면 아무것도 바꾸지 않고 `already_retired`를 출력하며 0으로 끝나고, `draft`·
`activation_candidate`는 `policy_not_active`로 거부한다(비 0). **활성 policy가 없어지면 일일 자동
실행은 `no_active_policy`로 꺼진다** — 다시 켜려면 새 버전을 활성화하고 그 버전의 스위치를 켜야
한다. 일일 자동 실행 스위치 행은 이 명령이 건드리지 않는다(append-only).

**트리거를 켜기 전 확인 항목(D-e).** 위 11을 켜기 전에 다음을 사람이 확인한다 — 수동 실행에서 본
요청 수·소요 시간·실패 분포, 나라장터 API 일일 할당량 여유, backup·restore와 stale execution
복구 훈련. 이 확인은 게이트 통과나 방화벽 승인을 대신하지 않는다.

## GPU 휴지

`BIDOPS_GPU_BUSY_LIMIT_SECONDS`·`BIDOPS_GPU_REST_SECONDS`는 기본값이 둘 다 `0`(꺼짐)이며, 둘
다 0보다 커야 켜진다. 켜지면 워커가 쉬지 않고 일한 시간의 합이 `BIDOPS_GPU_BUSY_LIMIT_SECONDS`
이상일 때 다음 작업을 잡기 전에 `BIDOPS_GPU_REST_SECONDS`만큼 쉬고 그 합을 0으로 되돌린다.
**작업 중간은 끊지 않는다** — C-2 한 실행이나 심층 검토 한 건이 한도를 넘겨도 끝까지 간 뒤에
쉰다. idle이 휴지 시간 이상 이어지면 그것이 곧 휴지이므로 합은 0으로 되돌아간다. 분석 워커
(C-2·심층 검토·회사 핏·개요를 합성하는 한 슬롯)와 web 프로세스 안의 C-1 워커가 이 규칙을 각자
따로 적용하며 서로 조율하지 않는다. `docker-compose.yml`은 두 값을
`${BIDOPS_GPU_BUSY_LIMIT_SECONDS:-0}`·`${BIDOPS_GPU_REST_SECONDS:-0}` 형태로 전달하므로 값을
주지 않으면 기존 동작과 같다.

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
RUN_ID="$(date +%Y%m%d)-prespec-ref-$(uuidgen)"
python3 skills/bidops-collect/scripts/collect_notices.py \
  --from-date <YYYY-MM-DD> --to-date <YYYY-MM-DD> \
  --output-dir "data/runs/${RUN_ID}" \
  --skip-bids \
  --timeout 300
```

- `--skip-bids`는 입찰공고를 빼고 사전규격만 담는다. 둘은 같은
  `collected-notices.json` 하나에 들어가므로 이 플래그가 없으면 입찰공고까지 적재된다.
- `--timeout 300`이 핵심이다. 기본 30초로는 구간 수집이 거의 항상 끊긴다.
- 원문 페이지는 `data/runs/${RUN_ID}/raw/`에 남는다. 기존 회차(빈 폴더 포함)는 재사용하지
  않는다. collector가 회차와 파일을 배타 생성하므로 출력 폴더를 미리 만들지 않는다.
- 재분류는 `--from-raw data/runs/<원본 회차>/raw --output-dir data/runs/<새 회차>`로
  API 호출 없이 수행한다. 같은 날짜·source 선택을 전달하고, 원본 바이트는 검증 후 새 raw에
  복사한다. symlink와 허용 루트 이탈은 거부한다.
- `collection-provenance.json`에 원본 상대 경로·페이지 hash·옵션·완전성·경고가 남는다.
  일부 수집이면 exit 1이며 웹·예약 호출은 자동 적재하지 않는다. 남은 raw를 삭제하거나
  기존 회차에서 재시도하지 말고 별도 새 회차를 사용한다.

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
- **함정 1**: `ingest.cli --run`은 `validation-set.json`의 표본만 적재한다. 회차 전체를
  넣으려면 `collected-notices.json`의 `counts.candidate_pool`·`counts.audit_pool` 값을
  `select_validation_sample.py … --analysis-count <candidate_pool 값> --audit-count
  <audit_pool 값>`에 넘겨 전 건이 담긴 선택 파일을 만든다. `--run <회차> --collection`을 붙이면
  표본 대신 수집 파일 전체를 수집 색인에 남기고 선별 규칙에 맞는 레코드(발주계획 전량·SW사업대상
  사전규격·추적·SW 관련 입찰공고)만 적재한다. `scripts/run-daily-lifecycle.sh`가 매일 이 경로를 쓴다.
- **함정 2(2026-09-19 해소)**: ingest CLI는 이제 확장점을 등록하고 적재하므로 첨부 자격
  갱신 hook이 CLI 경로에서도 돈다. 아래 수동 갱신은 더 이상 필수가 아니며,
  `scripts/run-daily-lifecycle.sh`가 공고 트랙 끝에서 부르는 같은 호출도 중복 실행일 뿐
  해롭지는 않다(멱등). 과거 회차를 손으로 다시 맞출 때만 쓴다.

  ```bash
  docker compose -f docker-compose.yml exec web python -c \
    "from app.core.db import SessionLocal; from app.deep_review.services.prespec_attachments import refresh_fetch_eligibility; s=SessionLocal(); print(refresh_fetch_eligibility(s)); s.commit()"
  ```

### 4단계. C-1 판정 실행

이 단계부터 모델을 부른다. **먼저 host 방화벽에서 승인된 모델 IP와 port 한 곳만 열고**,
그 다음에 overlay를 붙인다.

```bash
cp env/model.env.example env/model.env
```

`env/model.env`의 screening 절을 채운다. 주소는 **컨테이너에서 도달 가능한** 값이어야 한다.

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
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.model-egress.yml \
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

analysis-worker는 source·structure 쓰기 자격, scanning 네트워크, `document-scratch` 볼륨이
필요하다(2026-09-11 반영).

`env/model.env`의 overview 절(개요·회사 핏)과 deep_review 절을 채운다. 두 절 중 비워 둔
값은 공유 `BIDOPS_VLLM_*`로 떨어진다. MVP 기간에는 `*_ALLOWED_HOSTS`·`*_MODEL_REVISION`이
비어 있어도 그 용도는 fail closed하지 않는다(ADR-0050 §5 완화 항목) — 값을 채우면 기존
검사를 그대로 강제한다.

```text
BIDOPS_VLLM_OVERVIEW_BASE_URL=http://<approved-ip>:<approved-port>/v1
BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS=<approved-ip>
BIDOPS_VLLM_OVERVIEW_API_KEY=EMPTY
BIDOPS_VLLM_OVERVIEW_MODEL_REVISION=<64-hex-revision>
BIDOPS_PRESPEC_OVERVIEW_ENABLED=true
BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH=/app/app/deep_review/policies/prespec-overview-policy-v7.json
```

`BIDOPS_PRESPEC_OVERVIEW_ENABLED`가 `false`(기본값)면 개요 run이 자동으로 만들어지지
않는다. 이 참조 실행은 C-2를 돌리지 않으므로 `docker-compose.c2-order-plan.yml`을 붙이지
않으며, 따라서 C-2 입력 파일 host 경로도 필요 없다.

v8 예비 판단 정책 파일은 제품 코드에 있지만 기본값은 v7이다. v8 경로로 바꾸는 것은 실제
모델 호출과 기존 자동화 소비 경계에 영향을 주는 운영 변경이다. 0031 migration, web과
analysis-worker의 동일 image·정책 mount, 고정 표본의 사람 품질 비교, 전체 백업·롤백 태그를
준비한 뒤 **정책 경로 변경 직전에 별도 사람 확인**을 받는다. 참조·mock·미측정 결과만으로
경로를 바꾸지 않는다.

```bash
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.model-egress.yml \
  up -d analysis-worker
```

이 단계에서 사람이 누르는 것은 없다. 자동으로 다음이 일어난다.

1. 등급이 `우선 검토`가 되고 첨부 취득이 끝나면 자동 준비가 묶음 초안을 만들고 확정한다
   (`confirmed_by_name = auto-preparation`).
2. `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`이면 확정된 ready 묶음에서 analysis worker의 개요
   slot이 `prespec_overview_run`을 자동 enqueue하고 실행한다.
3. `SW사업대상=Y`이고 기존 자동화가 소비할 수 있는 개요 전체 검증 결과가 있으며 현재 회사
   핏이 `matched`일 때 심층 검토가 자동으로 생성된다. v8은 `completed`만으로 이 조건을
   충족하지 않고 `semantic_status=passed`와 `overview_full` 범위가 필요하다.

플래그가 켜져 있는 동안 1의 자격은 "`우선 검토` 또는 `SW사업대상=Y`"다(2026-09-11 MVP 완화).
이미 적재가 끝나 촉발 지점이 지나간 공고는 `docker compose exec web python -m
app.deep_review.cli prepare-overviews --all-eligible [--limit N] [--dry-run]`으로 한 번에
태운다 — 이 명령은 묶음 준비와 개요 enqueue까지만 하고 모델을 부르지 않는다. 대상에서
`queued`·`running`·`completed` run이 있는 공고는 빠진다. 0026 적용 뒤에는(과거 run 행이
지워졌으므로) 사실상 run이 없거나 `failed`·`needs_human_review`·`cancelled`로 끝난 공고,
즉 실패한 run만 다시 넣는다.

진행은 사전규격 목록의 파생 필드로 읽는다.

```bash
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/pre-specs?limit=50"
```

`auto_preparation_status`가 `not_applicable → waiting_attachments → bundle_draft →
bundle_ready → overview_running → deep_review_started`로 간다.
`deep_review_ready_for_click`에서 멈추면 `auto_preparation_reason`이 **왜 자동으로 열리지
않았는지**를 말한다(`not_sw_business`, `overview_not_completed` 등). 그 값이 정상적인
설명이면 화면에서 사람이 심층 검토를 실행한다.

개요와 심층 결과를 본다.

```bash
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/pre-specs/<notice_id>/overview"
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/<deep_review_id>"
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/deep-reviews/<deep_review_id>/report"
```

- **확인**:
  - `current.status`가 `completed`이면 `result`가 채워진다. `needs_human_review`·`failed`도
    정상적인 결과다 — `reason_codes`로 사유를 확인하고 실패를 통과로 바꾸지 않는다.
  - v8 envelope이면 `current.assessment.status`, `semantic_status`, `semantic_scope`를 따로 본다.
    `not_run`은 정상 저위험 경로일 수 있지만 의미검증 통과가 아니고, `held`의 grade는 null이어야
    한다. 화면용 grade가 있어도 자동 심층 시작 자격으로 읽지 않는다.
  - 심층 검토의 `status`가 `completed`이고 report의 `validation.status`를 읽는다.
    `failed`도 정상적인 결과다 — 실패를 통과로 바꾸지 않는다.
  - report의 `quality_status`가 `unmeasured_reference`·`mock_reference`이거나 `null`이다.
    **둘 다 참조 실행이며 운영 완료가 아니다.**
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

사전규격 전체의 깔때기 지표(자격 후보·첨부 완료·묶음 ready·개요 run 상태·이탈 사유·심층
자동 시작)를 한 번에 보려면: `BIDOPS_DATABASE_URL=<...> python scripts/validation/overview_funnel.py [--json] [--since YYYY-MM-DD]`

### 7단계. 화면 확인과 증거 기록

화면은 데스크톱·노트북 전용이다. 확인 viewport는 laptop 1280x800과 desktop 1440x900이다.

| 화면 | 확인할 것 |
|---|---|
| `/pre-specs` | `예비 적합성 등급`과 `개요 기준` 출처, 판단 보류·판정 없음, 자동 준비 8값, `display_grade` 서버 필터와 건수 일치 |
| `/pre-specs/<notice_pk>` | 예비 판단의 축별 이유·출처·시각·품질·선택 의미검증 상태, 개요 카드의 근거 locator로 원문 열기 |
| `/deep-reviews/<id>` | 상단 카드 다섯(`종합 판단`·`검증 결과`·`미확인 사항`·`보고서 revision`·`품질 표식`), 우측 열 네 구역(`보고서 범위` → 문서 inventory → `보고서 수정본 저장` → 이력) |
| 문서 inventory 패널 | 선택한 근거가 가리키는 **문서 하나**만 보인다는 안내와 segment 제목이 없는 이유 |

화면 등급 필터는 URL `/pre-specs?display_grade=<값>`으로 열린다. 허용 값은
`우선 검토|검토 권장|관찰 대상|제외|판단 보류|판정 없음`이고 그 밖의 값은 `전체`로 떨어진다.
필터를 바꾸면 `offset`이 초기화되고 서버가 페이지 분할 전에 적용한다. 구버전
`grade=<값>` URL은 진입 시 `display_grade`로 정규화한다. API의 기존 `grade` query와
응답 `grade|grade_source`는 자동화 호환을 위해 그대로다.

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

`ro_backup`은 table뿐 아니라 현재/향후 `migrate` 소유 sequence의 SELECT도 필요하다.
runtime 권한 정책은 이를 읽기 전용으로 부여하며 USAGE/UPDATE는 부여하지 않는다.
sequence 접근 거부로 종료한 dump는 0 B일 수 있으므로 성공 백업으로 사용하지 않는다.
승인된 최소 권한 복구 뒤 새 경로에 백업하고 exit·크기·SHA-256·`pg_restore --list`를
확인한다. 목록 읽기 성공은 실제 restore 시험이나 WAL/RPO 충족의 증거는 아니다.

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

2026-09-11 MVP 재작성으로 v3(`0012`·`0014`·`0019`)·v4(`0021`·`0022`)·v5(`0025`) 개요
스택을 `prespec_overview_run`(migration `0026`) 단일 테이블로 대체했다
([ADR-0054](tracking/decisions/0054-prespec-overview-mvp-rewrite.md)). `import-page-overview`,
`prespec-v4` cohort ops CLI, Luna 명시 참조 실행 절차는 모두 삭제했다 — 과거 실행 기록이
필요하면 git 이력(commit `71b9954`)에서 찾는다.

새 흐름은 사람이 누르는 별도 ops 명령이 없다. `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`이면
ready 묶음에서 analysis worker의 개요 slot이 `prespec_overview_run`을 자동 enqueue하고,
prepare(`prespec_v4_pdf_snapshot` 재사용 또는 신규 변환) → range(자동 선택 또는 fallback,
사람 확정은 `POST /api/pre-specs/{notice_id}/overview/range-confirmations`) → draft →
deterministic → v7 전체 semantic 또는 v8 선택 semantic → save 순서로 실행한다. v8은 사실
개요와 예비 판단을 정상 1회에 만들고 위험 신호에만 한 번 더 검증한다. 상세 계약은
[contracts.md](contracts.md#사전규격-개요-검토와-예비-적합성-판단-mvp-2026-09-21)를 정본으로 한다. 진행·결과
확인은 `GET /api/pre-specs/{notice_id}/overview`다(위 6단계 참조).

플래그를 켜지 않고 한 건만 넣어 보려면 `python -m app.deep_review.cli enqueue-overview
--notice-id <id> [--page-start A --page-end B --actor-name <담당자>]`를 쓴다. 이 명령은 대기열에
넣기만 하고 모델을 부르지 않는다 — 실행은 analysis worker의 개요 slot이 한다. 쪽 범위를 주면
`range_source=human`이고, 주지 않으면 자동 선택이다.

묶음이 `ready`가 된 자리에서 enqueue가 실패하면 자동 준비 결과에 비차단 경고
`overview_enqueue_failed`만 남고 방금 끝난 묶음 확정은 되돌리지 않는다.

`prespec_v4_pdf_snapshot`(`0021`)·native rhwp 참조(`0023`)·절 후보(`0024`,
`bidops.section-candidates.v1/v2`)는 그대로 유지한다. renderer는 native `rhwp-svg-pdf`
하나이며 `fontconfig`(`fc-list`)가 이미지에 없으면 모든 HWP·HWPX 준비가
`converter_unavailable`이다.

### 0026 적용 전 개요 테이블 백업

삭제 대상 개요 테이블은 서비스 중지 후 `pg_dump`로 먼저 백업하고 downgrade 경로는 두지
않는다.

```bash
pg_dump -Fc -f overview-tables-pre-0026.dump \
  -t 'bidops.prespec_overview_*' \
  -t bidops.prespec_v4_target \
  -t bidops.prespec_v4_attempt \
  -t bidops.prespec_page_overview \
  "$BIDOPS_DATABASE_URL"
alembic upgrade head
```

`alembic downgrade`는 이 migration에 제공하지 않는다. 복구가 필요하면 위 dump를 별도
스키마에 복원해 대조한다.

### 0031 예비 적합성 열 적용 전 확인

`0031_prespec_preliminary_assessment`는 기존 `prespec_overview_run`을 삭제하지 않고 v1 행을
보존한 채 입력 binding·프로필·판단·의미검증 열을 추가한다. 적용 직전 전체 PostgreSQL/MinIO
백업과 롤백 태그를 남기고 현재 head가 `0030_prespec_review_exclusion`인지 확인한다. 서비스
중지·migration·web/analysis-worker 교체는 각각 직전 사람 확인을 받는다. migration 뒤에는
Alembic head, 기존 행의 `contract_version=overview-v1`, 새 CHECK/FK, app/worker 권한을 확인한다.
downgrade로 이력을 삭제하지 않고 검증된 전체 백업으로 복구한다. 정책 기본값은 migration 뒤에도
v7이며 v8 활성화는 별도 품질 비교와 정책 변경 확인을 요구한다.

### 회사 핏 단계의 배포와 참조 검증

2026-09-08 회사 핏 코드는 기본 비활성이다. 코드 빌드만으로 실행이나 정책 활성화가 일어나지 않는다. DB head는 `0020_prespec_company_fit`이며 기존 운영 DB에 적용할 때는 유지보수 절차의 백업·명시적 migration·runtime 권한 적용 뒤 web과 analysis-worker를 같은 코드로 갱신한다. 기존 개요 완료만으로 심층을 시작하던 경로에도 회사 핏 게이트가 추가되므로, 비활성 상태에서는 자동 심층 시작이 대기한다. 사람의 심층 실행·추적 결정은 기존 경로다.

참조 검증에는 web/analysis-worker 양쪽에 동일한 `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=true`, `BIDOPS_REFERENCE_WORKFLOW_MODE=true`, `BIDOPS_PRESPEC_COMPANY_FIT_MODEL=<승인 모델명>`과 활성 profile/policy ID가 필요하다. 이 문서의 설정 예시는 실행 승인 자체가 아니다. 모델 연결은 기존 overview 용도의 승인 사설 endpoint/허용 host/64자 revision을 사용하며 별도 외부 fallback은 없다. model-response 암호화 저장소도 필요하다. 모델 호출과 활성화는 명시적 실행 승인 후 진행한다.

합성 worker 순서는 C-2 → 심층 → 회사 핏 → 개요이며 한 poll에서 하나만 실행한다. 우선 검토·SW=Y·자동 확정 ready 묶음·동일 문서의 완료된 개요 run·활성 입력 설정과 중복 여부를 유료 호출 전에 검사한다. 최신 `prespec_overview_run.status=completed`가 있으면 이를 사용하고 `needs_human_review`/`failed`일 때는 과거 완료 run으로 우회하지 않는다. 개요 완료 run이 없으면 이 회사 핏 단계는 대기한다.

회사 핏의 호출은 재시도 0, timeout 300초, lease 600초다. lease 만료는 실패로 종결하고 자동 재시작하지 않는다. 새 개요·프로필·정책/모델 입력이면 새 실행이 가능하다. `GET /api/pre-specs/{notice_id}/company-fit`에서 사유·현재성·토큰·시간·품질과 실제 심층 검토 생성을 확인한다. 현재는 참조 실행만 지원하며 품질 측정/사람 정답 없이 운영 자동화를 활성화할 수 없다.

비용 비교는 동일한 조건 통과 모집단에서 핏 입력/출력 토큰 및 시간, 불일치·보류 비율, 이후 심층 검토 사용량을 함께 측정한다. `(핏 단계 전체 비용) < (불일치/보류로 실행하지 않은 심층 검토 추정 비용)`인지 비교하며, 실제 심층이 없던 과거 참조 결과를 절감 실적으로 집계하지 않는다.

### 설명형 심층검토 정책의 선택 (2026-09-22, 아직 운영 적용 전)

새 파일은 `app/deep_review/policies/analysis-policy-narrative-v2.json`이다.
`import-profile-policy --policy <새 파일> --label analysis-policy-narrative-v2`를 명시한 경우에만 이 정책을 등록한다.
기본값인 lean-v1 파일과 기존 active ID는 그대로다. 등록 뒤에도
`active_configuration_changed=false`이며 새 policy ID 선택과 재배포는 별도 작업이다.

이 정책은 Qwen 및 `deep_review` 용도 client를 그대로 사용한다. 코드·합성 fixture 검증은
실제 모델 품질 측정이 아니다. 처음 실제 입력을 확인할 때는 승인된 고정 묶음과 프로필을
사용하고 품질 인자를 지어내지 않으며 참조 실행 표식을 유지한다. 원문별 누락·예외·회사
근거 선택의 회수율·잘못된 해석·호출량을 사람이 확인한다.

원문 조각은 6,000자 입력 예산에서 만들어지고 실제 excerpt는 최대 3,000자다. 회사 근거
선택 예산은 4,000자, 선행 분석 묶음은 8,000자, 마지막 전체 종합 입력은 16,000자다.
최종 prompt 상한 24,000자를 넘거나 전체 종합이 한 입력에 들어가지 않으면 실패로 닫는다.
표본 규모에 따른 실제 지연·호출량은 미측정이다. 실패 때 정책 파일이나 기준을 현장에서
덮어쓰지 말고 새 불변 버전으로 재설계한다.

운영 등록·활성 ID 변경·실제 모델 호출·재배포는 각각 실행 직전에 사람 확인이 필요하다.
배포는 이 문서의 현행 Compose overlay/env·백업·롤백 절차를 따른다.

원문 인용·숫자 대조 on/off는 웹의 문서 준비→심층 검토 시작, 또는 보고서 상단
`분석 설정`에서 새 실행에 선택한다. 기본 on이며 기존 실행은 바뀌지 않는다. off는
`source_verification_enabled=false` 요청과 attempt 감사 행으로 고정되고, 보고서에
`원문 대조 미실시`가 표시된다. 이 값은 정책 품질 활성화·전송 승인·접근 범위·JSON/참조
검사를 끄지 않는다. 대조하지 않은 인용과 수치는 실제 원문 페이지에서 직접 확인한다.
기존 실패 응답을 같은 검증기로 재검사하는 것은 모델 호출 없는 진단이며 새 전체 실행
성공이나 측정된 모델 품질로 기록하지 않는다.


회사 프로필 재등록에서 `service_unavailable`이고 저장소가 `NoSuchVersion`을 반환하면,
원본 해시와 근거를 바꾸지 않는다. 승인된 같은 Markdown 원문이 있을 때만
`import-profile-policy --repair-profile-source --actor <담당자> ...`로 저장 위치를 복구한다.
이 명시적 옵션은 같은 SHA-256·크기의 원문을 저장·재조회하고 기존 프로필의 모든 근거
인용을 재검증한 뒤 새 `ContentObjectLocation`과 `profile.source_location.repaired`
감사를 추가한다. 기존 프로필·근거·과거 위치는 보존하며, 변조된 근거는 복구하지 않는다.

## 사용자 요청 Luna 심층검토 운영 (ADR-0069)

[단계별 적용 명령과 롤백](0922_luna-deep-review/apply.md)이 이번 적용 절차다.
0032 migration, 전용 runner 이미지/secret/egress, 불변 Luna 정책, web/worker 환경을
묶어 적용한다. 각 운영 단계 직전 확인을 받는다. 구현·가짜 실행기 검증으로 실제
Luna 인증·모델 접근·실자료 품질이 확인됐다고 쓰지 않는다. 심층 자동 시작 기본값은
off이며 수집·문서 준비·개요를 끄지 않는다.

### 1489 가정 분석 배포 준비 (2026-09-23)

0033 입력/승인/단계 표, runner의 별도 schema, web/analysis/첨부 worker 이미지가 필요하다.
기존 회사 프로필·Luna v3 활성 정책은 유지하며 새 가정 분석 입력에 별도 계약/코드 hash를
동결한다. 운영 migration·서비스 교체·실제 전송은 각각 직전 확인한다. 준비·복구·검증
내역은 [가정 분석 계획](0923_assumption-analysis/plan.md#운영-적용-준비와-직전-확인)을 따른다.

## 서버 이전용 전체 폴더

`scripts/transfer.py`는 현재 실행 이미지, PostgreSQL 논리 dump·역할, 중지 상태의 MinIO
전체 볼륨, 앱 데이터 볼륨, 미커밋 소스와 호스트 입력을 한 폴더로 보존한다. 기존 버전별
객체 복구와 달리 MinIO 물리 볼륨을 같은 이미지로 복원하므로 객체 version ID가 유지된다.
사용자가 선택한 **평문 보관** 방식이며 환경 파일·회사자료·인증 파일·복호화 키를 포함한다.
생성 위치는 Git에서 제외된 `backups/transfer/`로 제한한다. 과거 백업 묶음은 포함하지 않는다.

```bash
# 준비: 서비스 변경 없이 현재 이미지 8종 등의 실제 구성을 보존한다.
python3 scripts/transfer.py prepare --project bidops \
  --bundle "$PWD/backups/transfer/<UTC시각>"

# 사람의 중단 승인 후 실행. 설치된 모든 일일 cron의 flock 파일을 지정한다.
python3 scripts/transfer.py capture --bundle "$PWD/backups/transfer/<UTC시각>" \
  --lock-file "$HOME/.local/state/bidops/daily.lock" --confirmed-stop

python3 scripts/transfer.py verify --bundle "$PWD/backups/transfer/<UTC시각>"
```

`prepare` 뒤 실행 컨테이너·이미지·running 상태가 바뀌면 새 폴더로 준비한다. capture는
공용 lock 획득과 실행 중 DB 작업 검사를 통과한 뒤 web·worker를 중지한다. DB dump와 객체
기준 검사를 수행하고 MinIO를 중지해 볼륨을 복사한다. 원래 실행 중이던 컨테이너만 재시작한다.
이미 중지된 analysis-worker는 켜지 않으며 crontab도 설치·수정하지 않는다. 실패나 SIGTERM 때도
재시작을 시도한다. SIGKILL·호스트 장애 때는 `manifest/resume-containers.json`의 ID를 확인해
MinIO부터 역순으로 재시작하고 health를 확인한다. 미완료 폴더 위 재실행은 하지 않는다.

완료 표식은 `manifest/snapshot.json`의 `state=captured`와 `manifest/files.json`이다.
후자는 정확한 파일 집합·크기·SHA-256을 검증한다. source의 Git bundle은 기존 이력을,
source 파일 사본과 변경 목록은 미커밋 작업을 보존한다. 호스트 입력은 `inputs/host/`,
실제 bind mount 입력은 `inputs/binds/`에 있으며 Docker 앱 데이터 볼륨과 자동 병합하지 않는다.

새 Linux 서버는 Python 3.12+, Docker Engine·Compose v2와 동일 CPU 아키텍처가 필요하다.
이전 폴더 안의 도구를 사용하며 새 대상 프로젝트·디렉터리·볼륨만 허용한다.

```bash
python3 /path/to/transfer/transfer.py restore --bundle /path/to/transfer \
  --project bidops-restored --target /path/to/new-restore --port 18789
```

이 명령은 저장된 이미지와 역할로 빈 DB에 dump를 복원하고 MinIO·앱 볼륨을 복원한다.
migration·minio-init은 실행하지 않는다. DB 전체 행 수·Alembic revision과 전체 객체 버전·해시,
active 참조 및 모델 응답 복호화 결과를 원본 기준과 비교한다. 원본의 누락 객체는
`manifest/objects.json`의 `issues`로 보존하며 복원 성공으로 고쳐 쓰지 않는다.

열람 모드는 localhost에만 열고 별도 worker를 기동하지 않는다. `transfer-preview.py`는 기존
앱의 DB revision·MinIO 기동 검사를 유지하며 runtime.start를 호출하지 않아 내장 판정 워커의
stale 복구와 자동 실행을 막는다. HTTP 변경 요청은 405이고 DB transaction도 read-only다.
policy 상태와 데이터는 변경하지 않는다. 이 모드는 운영 수집·분석 재개나 공개 서비스가 아니다.
모델 egress·실제 전송·일정 재설치는 별도 운영 전환 절차를 따른다.

검증은 `python3 -m unittest discover -s tests -p test_transfer.py -v`와 격리 실제 복원으로 한다.
파일 해시 통과만으로 복원 검증을 대신하지 않는다. 복원 대상의 `validation.json` 이후에도
대표 목록·첨부·개요·심층 보고서·프로필 API와 화면 열람을 확인해 증거를 보존한다.
