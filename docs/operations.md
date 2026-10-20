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
| `docker-compose.slack-egress.yml` | 평일 브리핑 Slack 전송(`web`)·Socket Mode 수신(`slack-worker`)의 `env/slack.env`와 Slack egress | `env/slack.env`(overlay가 `env_file:`로 직접 읽음) |
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

### Mac 운영 호스트 (2026-10-14~)

WSL2 운영 호스트는 2026-10-14 종료했고 운영은 Mac(42-ax)으로 옮겼다
([ADR-0072](tracking/decisions/0072-c2-mac-litellm-ollama.md)). WSL2의 DB·MinIO·승인 프롬프트
v3·사설 vLLM은 넘어오지 않았으므로 아래 v4 절차의 값(`5fa804ff…`, `eth1`, `192.168.0.139`)은
Mac에서 쓰지 않는다. Mac의 C-2는 v5(LiteLLM `local-agent-main` → 로컬 Ollama
`qwen3.8:27b-ctx32k`, digest `41a558fc…`)다.

```bash
scripts/mac-compose.sh config            # 프로젝트 bidops, 파일 6개 + env 4개, profile prespec
scripts/mac-compose.sh up -d --no-build  # BIDOPS_IMAGE(amd64) + BIDOPS_DOCUMENT_IMAGE(arm64), 미리 빌드
scripts/c2-mac-model-preflight.sh        # 별칭 경로·Ollama digest·컨테이너 TLS 도달 (completion 없음)
```

- 조합: 기반 + edge + model-egress + prespec-attachment + c2-order-plan + `docker-compose.mac.yml`,
  env는 `.env`·`env/model.env`·`env/prespec-attachment.env`·`env/c2.env`, `--profile prespec`
  (2026-10-15 사전규격 개요 추가).
- 이미지: `docker build --platform linux/amd64 -f web/Dockerfile -t <BIDOPS_IMAGE> .`와
  `docker build -f web/MinioInit.Dockerfile -t bidops:minio-init .`. vendored rhwp가 x86_64라
  애플리케이션은 Rosetta로 돈다. MinIO는 digest 고정 Chainguard 이미지다.
- **문서 worker만 native arm64 이미지(`BIDOPS_DOCUMENT_IMAGE`)다.** 변환기 자식 프로세스의
  `RLIMIT_DATA` 512MiB가 Rosetta의 mmap 예약과 충돌해 amd64 rhwp가 약 60ms 만에
  `conversion_required`로 끝난다(engineering-notes "Rosetta에서 rhwp 변환이…"). 이미지는
  데모 스택이 쓰던 빌드 정의(`.sdlc/local-runtime/rhwp-arm`, rhwp v0.8.6 commit `cac9b4f7`,
  binary `c32c7cb2…`)에 운영 브랜치의 `web/backend/app`을 넣어 `docker buildx build
  --platform linux/arm64`로 만든다. 앱 트리는 `__pycache__` 없는 사본을 named context로 주고
  `bidops-app.sha256` manifest를 그 사본에서 다시 만든다. 앱 코드를 바꾸면 이 이미지도 다시
  만든다 — 두 이미지의 앱 트리가 어긋나면 안 된다.
- 사전규격은 **개요 검토까지만** 돈다(2026-10-15 사용자 결정). `env/model.env`의 overview 절이
  LiteLLM `local-agent-main`(C-2와 같은 endpoint·digest)과 정책
  `prespec-overview-policy-v7-litellm-v2.json`(호출 900초·출력 예약 8192)을 가리키고
  `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`다. 심층 자동 시작·회사 핏은 `false`, active
  profile/policy ID는 비워 둔다. C-1 판정은 돌리지 않는다 — 개요 플래그가 켜져 있으면
  `SW사업대상=Y` 사전규격이 첨부 취득·묶음·개요 자격을 갖는다. 공고 트랙은
  `run-daily-lifecycle.sh --track notices`이며 발주계획과 같은 lock 파일을 쓴다.
  첨부 host 제한은 앱 허용 목록(`www.g2b.go.kr`)뿐이고 Mac에는 host 방화벽 egress 제한이 없다.
  2026-10-15 실행은 개요 대상을 등록일 10-13·10-14로 좁혔고 상시 `prespec-attachment-worker`는
  **멈춰 둔 상태**다(기록 `validation-runs/20261015-prespec-overview-mac/`). 상시 worker만으로는
  개요까지 가지 않는다 — 취득 종결의 자동 준비가 커밋되지 않고 worker에 개요 정책 경로가 없다
  (findings). 실행 뒤 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`로 되돌렸다(2026-10-15 사용자 결정) —
  켜 둔 채 공고 회차를 다시 적재하면 적재 hook이 첨부가 끝난 다른 날짜 공고의 묶음·개요를 자동으로
  만든다. 다시 켤 때는 대상 범위를 먼저 정한다.
- 노출: web `127.0.0.1:18788`, tailnet은 `tailscale serve --bg --tcp=8188 tcp://127.0.0.1:18788`.
  tailnet ACL이 허용하는 inbound 포트가 정해져 있어(8101–8199 등) `18788`을 직접 열지 않는다.
  같은 Mac의 데모 스택 `bidops-local`은 `:18787`/`:8187`이며 volume·network를 나누지 않는다.
- 모델 설정은 공유 `BIDOPS_VLLM_*` 네 값과 overview 절(`env/model.env`)이다. C-2 adapter와
  개요가 같은 LiteLLM을 쓰고 심층·C-1은 이 배포에서 꺼져 있다. `BIDOPS_VLLM_MODEL_REVISION`은 Ollama
  `/api/tags`의 digest이고 preflight가 binding·generation config와 대조한다.
- 승인 입력 본문(프롬프트 v5·회사 역량 v1)은 gitignore다. `env/c2.env`의 host 경로가
  `/Users/temp/orca/bidops/experiments/order-plan-screening/review-inputs/`를 가리키며, 이
  디렉터리를 백업 대상에 넣는다. 본문을 잃으면 같은 digest로 실행할 수 없다(v3이 그렇게
  사라졌다).
- 첫 `docker compose cp`가 빈 `pipeline-data` volume에 `/app/data/runs`를 만들면 host uid(502)
  소유가 되고, 디렉터리 대신 내용이 `runs/` 바로 아래에 풀린다. 새 스택에서는 먼저
  `scripts/mac-compose.sh exec -T web mkdir -p /app/data/runs`로 만든 뒤 복사한다.
- 일일 스크립트는 GNU `date -d`·`timeout`·`flock`이 필요하다. `brew install coreutils flock`
  뒤 PATH 앞에 `/opt/homebrew/opt/coreutils/libexec/gnubin`을 둔다. 손으로 보충할 때도 같은
  접두사를 붙인다(BSD `date -d`는 바로 실패한다). docker CLI는 OrbStack의
  `/Applications/OrbStack.app/Contents/MacOS/xbin`에 있어 cron PATH에 따로 넣어야 한다 —
  빠지면 사전 점검에서 exit 2로 끝나며 `--dry-run`은 이 점검을 건너뛰어 드러나지 않는다.
  `/bin/bash`는 3.2라 스크립트는 bash 4 기능(음수 배열 첨자 등)을 쓰지 않는다.
  Mac이 잠자기 중이거나 OrbStack·Tailscale·LiteLLM·Ollama가 내려가 있으면 그날 실행은
  fail closed로 끝나며 빠진 날은 `--date`로 사람이 메운다. OrbStack은 로그인 시 자동 시작한다.

  **cron은 설치하지 않았다**(2026-10-14 사용자 결정). 일일 실행은 사람이 아래와 같은 명령을
  `--date`로 직접 돌린다. 나중에 cron을 켤 때 쓸 줄은 다음과 같다.

  ```bash
  # Mac 발주계획 cron 예시 — 설치되어 있지 않음
  30 7 * * * cd /Users/temp/orca/bidops-c2mac && PATH=/opt/homebrew/opt/coreutils/libexec/gnubin:/Applications/OrbStack.app/Contents/MacOS/xbin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin COMPOSE_PROJECT_NAME=bidops BIDOPS_WORKFLOW_WEB_URL=http://127.0.0.1:18788 BIDOPS_C2_DAILY_ACTOR=jechoi flock -n /Users/temp/.local/state/bidops/plans.lock timeout 6h ./scripts/run-daily-lifecycle.sh --track order-plans >> /Users/temp/.local/state/bidops/logs/plans-$(date +\%Y\%m).log 2>&1
  ```

  운영 checkout 경로는 브랜치가 병합되면 main checkout으로 옮긴다. 그때 env 파일 4개와
  `data/runs`의 회차 디렉터리를 함께 옮기고 cron의 `cd` 경로를 바꾼다.

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
- MinIO root와 source, structure write/read, quarantine, model-response, proposal-pdf(`BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`, web만 받음 — RL-04 결정 B48) 자격증명을 용도별로 분리한다.
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

`scripts/init-runtime.sh`는 DB 역할 초기화, Alembic migration, MinIO 버킷·정책 초기화를 순서대로 실행한다. 앱 startup은 이 작업을 대신하지 않는다. `bidops-source`, `bidops-structure`, `bidops-quarantine`, `bidops-model-response`, `bidops-proposal-pdf` 버킷은 versioning과 최소 권한 정책을 유지한다. 만료 규칙은 `bidops-model-response` 90일, `bidops-proposal-pdf`(RL-04 제안서 초안 PDF, `retention_class=proposal-pdf-365d`, 암호화 없음) 365일이며 나머지는 만료하지 않는다.

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
# 특정 공고의 대기·lease 만료 첨부 중 FIFO 한 건만 취득한다.
python -m app.deep_review.workers.prespec_attachment --once --notice-id 179
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

2026-10-09 로컬 ARM 검증은 gitignore 경로
`.sdlc/local-runtime/rhwp-arm`의 `linux/arm64` document-worker 이미지와 rhwp upstream
commit `cac9b4f7cc743535cd7c00fe4f286abd67e7145b`를 사용했다. 이 경로는 child
`RLIMIT_DATA` 512 MiB, `RLIMIT_AS` 32 GiB 등 기존 기본 제한을 바꾸지 않은 상태에서 선택한
실제 HWPX의 PDF 준비가 성공했음을 확인한 로컬 증거다. 전체 Compose·운영 환경의 ARM 지원 근거로
확대하지 않으며, 제품 Compose나 vendored AMD64 binary를 바꾸지 않는다.

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
| `env/slack.env` | `docker-compose.slack-egress.yml` | `BIDOPS_SLACK_*`(활성 스위치·bot/app token·채널 ID·허용 host)와 `BIDOPS_PUBLIC_BASE_URL`. 예시 `env/slack.env.example`만 추적한다 |
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
| Slack 브리핑 | `BIDOPS_SLACK_ENABLED`, `BIDOPS_SLACK_BOT_TOKEN`, `BIDOPS_SLACK_APP_TOKEN`, `BIDOPS_SLACK_CHANNEL_ID`, `BIDOPS_SLACK_ALLOWED_HOSTS`, `BIDOPS_PUBLIC_BASE_URL`, `BIDOPS_BRIEFING_POLICY_PATH` | 기본 꺼짐(fail closed). 토큰은 `env/slack.env`에만 두고 로그·명령줄·문서에 적지 않는다. 호출 전 enabled·토큰·채널·허용 host를 검사한다 |
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

### 일일 브리핑·Slack (RL-01, 2026-10-17)

평일 아침 한 번 후보를 고르는 브리핑이다(규칙은 [business-rules.md "브리핑 추천·반응"](business-rules.md), 계약은 [contracts.md "브리핑"](contracts.md)). LLM을 부르지 않는다. **Slack 전송은 기본 꺼짐이며 이 저장소는 cron을 설치하지 않는다.** 2026-10-17 격리 스택(`bidops-local`의 `bidops_rla`)에서 `--send` 없는 감독 시운전(T12: 생성·REST·반응·화면)을 했다([기록](validation-runs/2026-10-16-rl/RL-01/README.md)). 실제 Slack 전송·Socket Mode 연결은 토큰이 없어 아직 하지 않았고, cron도 설치하지 않았다 — 아래는 절차와 예시다.

**배포(운영 변경이므로 직전에 사람 확인).** migration `0038_briefing`(테이블 3개, [contracts.md](contracts.md) 참조)을 적용하고 `web`·`slack-worker` 이미지를 새로 올린다. 전체 백업과 `before-briefing-<날짜>` 롤백 태그를 먼저 남기고 배포 기록에 migration head를 적는다. 브리핑·반응은 DELETE 권한이 없어 되돌리려면 백업으로 복구한다. 이 단계의 승인은 아래 설정·전송·cron 설치로 이어지지 않는다.

**설정과 기동.**

1. `cp env/slack.env.example env/slack.env`로 만들고 값을 채운다(`env/*.env`는 gitignore). 키는 `BIDOPS_SLACK_ENABLED`(기본 `false`), `BIDOPS_SLACK_BOT_TOKEN`(`xoxb-`, 전송·갱신), `BIDOPS_SLACK_APP_TOKEN`(`xapp-`, Socket Mode), `BIDOPS_SLACK_CHANNEL_ID`(브리핑 전용 채널 하나), `BIDOPS_SLACK_ALLOWED_HOSTS`(기본 `slack.com,wss-primary.slack.com`, 정확 일치·빈 값이면 어떤 host도 허용하지 않음), `BIDOPS_PUBLIC_BASE_URL`(메시지의 레코드 링크 기준 주소, 비면 링크 없이 제목만)이다.
2. **fail closed.** `BIDOPS_SLACK_ENABLED=false`(기본)이거나 토큰·채널이 비어 있거나 호출 host가 허용 목록에 없으면 네트워크에 닿지 않는다. 전송기(`app/core/slack.py`)가 호출 전에 이 순서로 검사하고 어긋나면 CLI 출력의 `slack.skipped_reason`이 `slack_disabled`·`token_missing`·`channel_missing`·`host_not_allowed`가 된다. 다른 채널·hosted fallback은 없다. host 방화벽에서 `slack.com`·`wss-primary.slack.com`(443) 외 egress를 막은 뒤에만 켠다.
3. 운영 compose 조합에 `docker-compose.slack-egress.yml`을 더하고 `slack-worker`는 profile `slack`으로 올린다. overlay가 `env/slack.env`를 `web`과 `slack-worker` 두 서비스에만 `env_file:`로 주므로 `--env-file`에는 넣지 않는다(기존 `.env`·`env/model.env`·`env/prespec-attachment.env`·`env/c2.env` 조합은 그대로).

   ```bash
   # 최소 조합 예: 기반 + edge + slack overlay. 운영 조합이면 나머지 overlay와 --env-file도 그대로 붙인다.
   docker compose -f docker-compose.yml -f docker-compose.edge.yml \
     -f docker-compose.slack-egress.yml --profile slack \
     up -d --no-deps --no-build --force-recreate web slack-worker
   ```

   `env/slack.env`가 없으면 compose가 기동 전에 멈춘다. overlay 없이 올린 `slack-worker`는 기본값(꺼짐)이라 연결하지 않고 0으로 끝난다. 켜 놓고 토큰·채널·허용 host가 어긋나면 연결 전에 1로 끝나며 `restart: on-failure`가 드러낸다. 올린 뒤 플래그가 실제로 반영됐는지는 `docker compose exec -T web printenv BIDOPS_SLACK_ENABLED`처럼 **값 하나씩** 본다. `docker compose config`는 `env_file` 값을 펼쳐 토큰이 터미널에 나오므로 이 overlay를 붙인 채 쓰지 않는다.
4. **토큰 취급.** 토큰은 `env/slack.env`(권한 600)에만 두고 명령줄·compose 파일·이미지·로그·이 문서·채팅·티켓에 적지 않는다. 앱은 토큰을 `SecretStr`로만 다루며 로그·응답·오류에 넣지 않는다(실패는 `slack_send_failed`와 안전한 code만). 노출이 의심되면 Slack 앱에서 토큰을 폐기·재발급하고 `env/slack.env`를 고쳐 두 서비스를 다시 만든다. Slack 앱 설정(Socket Mode 사용·interactivity·bot의 `chat:write` 권한·채널 초대·app-level token `connections:write`)은 시운전에서 확인한다.

**실행: `scripts/run-daily-briefing.sh [--date YYYY-MM-DD] [--send] [--dry-run]`.** web 컨테이너 안에서 `python -m app.lifecycle.cli build-briefing --date <D> --json [--send]`를 실행한다(`COMPOSE_PROJECT_NAME` 기본 `bidops`, `docker compose -f docker-compose.yml exec -T web`로 실행 중인 컨테이너를 찾는다). `--date`는 브리핑 날짜 D(기본 오늘 KST)이고 수집 회차는 D-1이다. 토·일은 행 없이 `weekend`로 끝나고 같은 날 재실행은 기존 행을 그대로 둔다(`created=false`). `--dry-run`은 호출 순서만 출력하며 docker·web·Slack을 부르지 않는다(깨끗한 환경 `env -i HOME=… PATH=…`에서도 같다). 종료 코드:

| 코드 | 뜻 |
|---|---|
| 0 | 성공과 정상 건너뜀(`weekend`·`empty`·`already_sent`·`slack_disabled`·`token_missing`·`channel_missing`·`host_not_allowed`·`not_requested`). `collection_run_missing` 같은 수집 경고도 브리핑 상태로 보일 뿐 실패가 아니다 |
| 1 | 브리핑 생성 실패(`company_not_registered` 등, 행 없음). 그 밖의 비0 CLI·docker 종료 코드는 그대로 전달 |
| 2 | 인자 오류, docker·jq 없음 |
| 3 | **`slack_send_failed`.** CLI는 이 경우에도 0으로 끝나고 JSON `warnings[]`에만 코드를 싣는다. cron이 전송 실패를 성공으로 보지 않도록 스크립트가 JSON을 읽어 3으로 바꾼다. 브리핑 행은 남는다 |
| 4 | CLI가 0으로 끝났지만 stdout이 기대한 JSON이 아니어서 `slack_send_failed`를 배제할 수 없음(fail closed) |

**RL-03 연결.** `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED`가 꺼져 있으면(기본) 위 설명 그대로이고 브리핑 CLI는 LLM·Luna를 부르지 않는다. 켜면 새 브리핑이 만들어진 직후 같은 transaction에서 지난날 상한 초과 큐를 처리하고 사전규격 추천 항목마다 자동 판정 시작 조건을 평가한다(모델 호출은 이 CLI가 아니라 분석 worker가 한다). 이 hook의 실패는 브리핑 생성에 영향을 주지 않는다. 절차·승인·상한은 아래 "RL 카드 판정 운영"이 정본이다.

**재시도.** 전송이 실패하면(3) 원인(토큰·네트워크·채널)을 고친 뒤 **같은 명령을 `--send`로 다시 실행**한다. 이미 보낸 메시지는 저장된 ts로 건너뛰고 빠진 메시지만 보내며, 전부 보내면 `slack_sent_at`이 찍히고 이후 재실행은 `already_sent`다. 자동 따라잡기는 없다 — 빠진 날은 `--date <D>`로 사람이 메운다(창은 직전 브리핑 이후라 한 날을 건너뛰면 다음 브리핑에 함께 들어온다). 수집이 덜 끝난 날은 `collection_incomplete`로 만들어지고 이미 만든 행은 다시 만들 수 없으므로, 기준일 수집이 끝난 뒤에 실행한다.

**cron 예시(설치하지 않음).** 브리핑은 notices 트랙이 만든 D-1 회차와 발주계획 트랙의 C-2 결과를 읽으므로 **두 트랙이 끝난 뒤** 돈다. 줄은 두 트랙의 lock 파일을 둘 다 잡아(`flock -w`는 앞 실행이 끝나기를 기다린다) 수집·적재·C-2 실행 중에 끼어들지 않고, `timeout`으로 멈춘 실행을 끊는다. 시각은 운영 결정이다.

```cron
# 문서용 예시 — 설치되어 있지 않음. 감독 시운전을 마치고 사람이 crontab -e로 추가할 때만 참고한다.
# flock -w 3600: notices·plans 트랙이 lock을 쥐고 있으면 최대 1시간 기다린다(기다림이 끝나면 비0으로 끝나 로그에 남는다).
# timeout 30m: 멈춘 실행을 끊는다. 월~금만 돌리며 주말 처리는 CLI도 한 번 더 막는다.
0 9 * * 1-5 cd /path/to/bidops && flock -w 3600 ~/.local/state/bidops/notices.lock flock -w 3600 ~/.local/state/bidops/plans.lock timeout 30m ./scripts/run-daily-briefing.sh --send >> ~/.local/state/bidops/logs/briefing-$(date +\%Y\%m).log 2>&1
```

**설치 전 감독 시운전(T12, 사람 확인 필요).** 순서: ① 깨끗한 환경에서 `env -i HOME=$HOME PATH=$PATH scripts/run-daily-briefing.sh --dry-run`으로 순서를 본 뒤 `--send` 없이 한 번 실행해 JSON·`GET /api/briefings/latest`·`/briefing` 화면을 확인한다. 이 실행은 그날 브리핑 행을 **실제로 만들고 지울 수 없으므로** 시운전 날짜가 곧 그날의 브리핑이다(행을 쓰지 않는 계산 확인은 컨테이너에서 `python -m app.lifecycle.cli build-briefing --dry-run`을 직접 준다). ② `GET /api/briefings/<날짜>/slack-preview`로 보낼 payload를 읽는다. ③ **테스트 채널**로 `--send`를 사람이 확인한 뒤 한 번 실행하고 메시지 1건과 버튼 클릭 → 화면 반영을 본다. ④ `GET /api/workload`의 `briefing_pending`이 화면의 대기 수와 같은지 본다. ⑤ 증거를 `docs/validation-runs/`에 기록한다. 차단 0이 된 뒤에만 cron을 설치한다. 가짜 docker·가짜 CLI로 도는 `tests/app/test_daily_briefing_script.py`는 호출 순서·인자·종료 코드만 증명하며 실제 컨테이너·실제 Slack 전송은 이 시운전이 증명한다.

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
version ID·namespace별 무결성 및 active 집합 일대일 검증이다. 다섯 버킷 모두 백업·복구 대상이다. source·structure·quarantine·proposal-pdf는
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

## 승인된 LiteLLM을 사전규격 개요에 쓰는 경우

LiteLLM은 전역 fallback이 아니다. 로컬 참조 실행에서 overview 용도에만 dialect와 불변 정책을
함께 명시하며 기본 v7 정책과 screening·deep_review·C-2 설정은 그대로 둔다. `env/model.env`의
실제 값은 secret 배포 입력으로 관리하고 `GATEWAY_URL`·`GATEWAY_KEY`를 애플리케이션의 공유
`BIDOPS_VLLM_*` fallback으로 연결하지 않는다.

```text
BIDOPS_VLLM_OVERVIEW_API_DIALECT=litellm
BIDOPS_VLLM_OVERVIEW_BASE_URL=<approved-litellm-base>/v1
BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS=<exact-approved-host>
BIDOPS_VLLM_OVERVIEW_API_KEY=<injected-secret>
BIDOPS_VLLM_OVERVIEW_MODEL_REVISION=<declared-revision-if-used>
BIDOPS_PRESPEC_OVERVIEW_POLICY_PATH=/app/web/backend/app/deep_review/policies/prespec-overview-policy-v7-litellm-v1.json
```

문맥 32768의 로컬 `local-agent-main`에서는 v1의 호출 300초·출력 예약 16384로 초안이 끝나지
않는다. 이때는 같은 프롬프트에 호출 900초·출력 예약 8192·lease 3060초만 다른
`prespec-overview-policy-v7-litellm-v2.json`(sha256 `0e69ae43…`)을 쓴다. 이 짝은 `litellm`
dialect에서만 받고(`model_client.APPROVED_EXECUTION_PROFILES`), LiteLLM 요청에는
`reasoning_effort=none`이 함께 실린다. Mac 운영은 v2다(2026-10-15).

정책의 요청 별칭은 `local-agent-main`이다. client는 승인 base의 `/models`에 이 별칭이 있는지
확인하고, 같은 origin과 base prefix의 `/model/info`에서 같은 별칭의 deployment만 읽는다.
base의 끝 `/v1`만 metadata 경로를 만들 때 제거한다. 일치하는 모든 deployment에는 bool이 아닌
양의 정수 `model_info.max_input_tokens`가 있어야 하며 값이 다르면 최솟값을 전체 요청 상한으로
쓴다. 누락·잘못된 shape·미등록 별칭·선언 revision 불일치는 모델 본문을 보내기 전에 실패한다.
metadata가 돌려주는 upstream URL·key는 사용하거나 로그에 남기지 않고 redirect도 따르지 않는다.

web과 analysis-worker에 같은 dialect·endpoint·정책 경로를 렌더링했는지 확인한다. 정책 경로를
설정하는 것만으로 실행을 만들거나 자동화를 켜지 않는다. 준비·metadata 확인·합성 입력 검증
동안에는 `BIDOPS_PRESPEC_OVERVIEW_ENABLED=false`,
`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED=false`, `BIDOPS_PRESPEC_COMPANY_FIT_ENABLED=false`와
scheduler/always-on 비활성을 유지한다. 선택 공고, 선택 쪽, 전송 정보 미리보기를 확인한 뒤 실제
설정 적용과 모델 호출 직전에 각각 사람 확인을 받는다.

승인된 queued overview 한 건을 실제 실행할 때만 큐에 그 승인 run 하나가 있고 C-2·심층·회사 핏
claim 대상이 없음을 먼저 확인한다. 그 다음 합성 analysis worker의 목적별 one-shot 프로세스에만
`BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`를 주고 한 번 실행하며 always-on worker는 띄우지 않는다.
종료 뒤 다시 `false`로 둔다. 이 플래그가 `false`이면 worker가 queued overview를 취소하므로 실제
호출 단계까지 계속 `false`로 두어서는 안 된다. 실패 결과를 재시도나 다른 provider fallback으로
성공 처리하지 않는다.

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


## 가상 SI 3사 데모 목표 계약 (2026-10-06 채택; DEMO-01~04 데모 브랜치 구현(DEMO-04는 mock 화면 검증), DEMO-05 구현 전)

별도 Compose 프로젝트·PostgreSQL·MinIO 자원에서 수동으로 초기화한다. 운영 secret/볼륨을 공유하지 않는다. 새 모델 호출은 실행 직전 승인하며 자동 일정은 비활성이다.
DEMO-02(2026-10-09, 데모 브랜치)는 회사 지식 `import-company-knowledge`·`activate-company-knowledge` CLI를 추가했다. 원본(`docs/demo-fixtures`)은 이미지에 넣지 않고(`.dockerignore` 제외)
일회성 CLI 컨테이너에 `/run/demo-fixtures`로 read-only 마운트해 `--dry-run` → import → 직전 사람 확인 뒤 activate 순서로 쓴다. import는 자동 활성화하지 않는다.
`bidops-local`의 실제 3사 등록·활성화는 2026-10-11 DEMO-03 STEP-007에서 단계별 사용자 확인 후 수행했다(증거 `validation-runs/2026-10-10-company-demo/DEMO-03-grounded-analysis/README.md`). 새 환경에서는 같은 순서와 직전 확인을 다시 거친다.
2026-10-11 DEMO-03 STEP-008부터 회사 핏 enqueue는 `company-fit-demo-v3.json` 정책 행과 공고의 ready bundle을 요구한다. 현재 `bidops-local`에는 v2 행만 import돼 있어 핏 enqueue가 `analysis_policy_unavailable`로 막힌다.
핏을 실제로 돌리기 전에 이미지 재빌드, `import-company-fit-policy`로 v3 import, `env/demo.env`의 `BIDOPS_DEMO_COMPANY_FIT_POLICY_VERSION_ID`를 web·analysis-worker 모두 v3 행으로 바꾸는 일을 각각 직전 확인 후 한다(DEMO-05 준비 단계).
DEMO-04(2026-10-12)는 frontend만 바꿨다. 새 env·migration·서비스는 없다. 회사 화면은 web 이미지를 다시 빌드해 교체하기 전에는 `bidops-local`에 나타나지 않는다. 이 재빌드·교체도 DEMO-05 준비 단계에서 직전 확인 후 한다.
mock으로 화면만 볼 때는 `npm run dev:mock`(5174)을 쓴다. 응답은 Playwright fixture이며 실제 데이터나 회사 사실이 아니다.
[ADR-0070](tracking/decisions/0070-multi-company-knowledge-demo.md) · [공통 계약](work/demo-contract.md) · [기능 로드맵](work/constitution/roadmap.md).


## 회사 근거 갱신 (RL-00, 2026-10-16)

루트랩 회사 근거는 화면에서 고치지 않는다. 회사 파일을 고쳐 새 버전으로 다시 등록한다(이전 버전과 binding 이력은 불변). 원본 파일은 Git 밖 `~/orca/fixtures/company/rootlab/`(`ontology.v2.json`, `rootlab.source.v1.json`)이며 출처·sha256 기록은 `docs/validation-runs/2026-10-16-rl/RL-00/README.md`다. 값은 회사소개서·홈페이지·선호 조건·인터뷰 문서에 있는 확인됨·추정값·확인 필요만 옮기고 새 사실을 만들지 않는다.

1. **파일 수정.** 확인된 값은 해당 `unknown` 노드를 `confirmed`(값·source_ref 채움)로 바꾸거나, `proposed` 노드를 사람이 확인한 뒤 `confirmed`·origin을 확인 출처(`user_interview` 등)로 바꾼다. `proposed`는 origin `agent_proposal`만, `user_interview`는 `confirmed`·`unknown`만, `company_brochure`·`homepage`는 `confirmed`만 허용된다. 한글 이름은 `label`에만 두고 id는 ASCII다.
2. **`--dry-run`.** `python -m app.deep_review.cli import-company-knowledge --ontology <ontology.v2.json> --company <rootlab.source.v1.json> --actor <이름> --dry-run`. DB·객체·모델 쓰기가 없다. exit 0이고 `errors=[]`, `is_fictional=false`, `status_counts`(confirmed·proposed·inferred·unknown)가 수정 의도와 맞는지 본다. exit 2면 `source_invalid`(조합·origin·value 형태)이거나 `real_company_exists`(다른 slug의 실회사가 이미 있음)다.
3. **import.** 같은 명령에서 `--dry-run`만 뺀다. 같은 파일이면 같은 버전이고(`created=false`), 내용이 바뀌면 새 graph·profile version이다. import는 자동 활성화하지 않는다. 출력의 `graph_version_id`를 적어 둔다.
4. **activate.** `python -m app.deep_review.cli activate-company-knowledge --company-id <uuid> --graph-version-id <uuid> --actor <이름>`. binding revision이 오르고 이전 binding 이력이 남는다.
5. **확인.** `GET /api/company`의 `active_graph_version.graph_version_id`가 방금 활성화한 값인지, `GET /api/companies/{company_id}/profile`의 facts 수가 `status_counts` 합과 같고 origin·status가 의도한 값인지 본다. `GET /api/workload`의 `company_attention`은 `proposed`+`unknown` 합과 같아야 한다. 이전 버전은 `profile?graph_version_id=`로 계속 조회된다.
6. **기록.** README에 새 파일 sha256(`source_sha256`·`graph_sha256` 포함)·`status_counts`·변경 사유를 덧붙인다.

CLI는 web 이미지 안에서 돈다. fixture 디렉터리를 읽기 전용으로 마운트한 일회용 컨테이너로 실행한다(예: compose overlay에 `~/orca/fixtures/company/rootlab:/fixtures/rootlab:ro`를 둔 서비스로 `docker compose ... run --rm --no-deps -T <서비스> python -m app.deep_review.cli import-company-knowledge --ontology /fixtures/rootlab/ontology.v2.json --company /fixtures/rootlab/rootlab.source.v1.json --actor <이름>`). 2026-10-16 RL-00 STEP-006은 `bidops-local` 안의 별도 DB `bidops_rla`(기존 `bidops` DB는 HP-03 migration 0039에 있어 main 계열과 이력이 갈라졌다)에서 이 방식으로 import→activate→REST 확인을 했다(README 참조).

운영 DB에서 import·activate를 실행하는 것은 **직전에 사람 확인을 받는다.** dry-run은 쓰기가 없지만 확인 없이 활성화하지 않는다. 격리 스택(`bidops-local`)에서 먼저 같은 순서로 확인하고 운영 반영은 별도 승인이다. 가상회사 파일은 `BIDOPS_DEMO_ENABLED=true`가 아니면 import·`--dry-run` 모두 `fictional_requires_demo`(exit 2)로 거부된다. "곧 만료" 기준일 수는 `BIDOPS_COMPANY_EXPIRY_WARNING_DAYS`(기본 60, 1..365)다.

## RL 카드 판정 운영 (RL-03, 2026-10-17)

사전규격을 카드·영역 단위로 추출·대조·판정하는 RL-03의 실행·설정·승인 절차다(규칙은 [business-rules.md "RL 자동 분석과 판정 상태"](business-rules.md), 계약은 [contracts.md "카드 기반 참여 판정"](contracts.md)). **구현·mock 검증은 `bidops-local` 격리 스택에서 한 것이고 운영 `bidops` 스택·운영 DB에는 반영하지 않았다.** mock 전체 경로(T11)와 실제 Luna 1건(T12)의 결과는 [검증 기록](validation-runs/2026-10-17-rl/RL-03/README.md)에 적으며 그 기록이 없거나 pending이면 실행하지 않은 것이다. 실제 호출 결과는 `unmeasured_reference`이며 품질·운영 완료 근거로 쓰지 않는다. **모든 단계는 기본 꺼짐이고 아래 승인·플래그를 사람이 직전 확인 후 하나씩 켠다.** 앞 단계의 확인은 다음 단계로 이어지지 않는다.

**플래그.**

| 키 | 기본 | 역할 |
|---|---|---|
| `BIDOPS_RL_ANALYSIS_ENABLED` | `false` | 사업기회 판정 REST·실회사 판정 게이트 개방. 꺼져 있으면 `/api/opportunities/{id}/verdict*`·`/api/analysis/transfer-policy`가 404이고 브리핑 판정 표시·활동 피드 제공자는 아무것도 주지 않는다 |
| `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED` | `false` | 브리핑 추천→자동 시작과 `drain-verdict-queue`. 꺼져 있으면 hook과 drain이 아무것도 읽거나 쓰지 않는다 |
| `BIDOPS_RL_ANALYSIS_POLICY_PATH` | `policies/analysis-policy-luna-rl-v11.json` | import 원본 파일(immutable). 기본값은 결정 B23 전 v1, B30 전 v2, B33 전 v3, B35 전 v4, B37 전 v5, B51 전 v6, B53 전 v7, B55 전 v8, C15 전 v9, C20 전 v10이었고 v1~v10 파일은 그대로 남는다. 승인 CLI는 이 파일의 identity·sha를 선택 행과 대조하므로 **선택 행과 같은 버전**을 가리켜야 한다(v1·v2 행을 계속 쓰면 그 파일 경로를 명시) |
| `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID` | 없음 | import한 정책 행 선택. 비어 있으면 RL 경로 fail closed(`analysis_policy_unavailable`). demo용 선택 env와 별개 |
| `BIDOPS_REFERENCE_WORKFLOW_MODE`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED` | 기존 | **RL 경로도 요구한다**(변경 없음, 결과가 참조 실행 표식) |
| `BIDOPS_PRESPEC_OVERVIEW_ENABLED`·`BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED` | `false` | RL 판정은 개요를 쓰지 않는다. 실제 호출 스택에서는 둘 다 `false`로 둬 개요 모델 호출이 생기지 않게 한다 |

기반 compose는 RL 키를 전달하지 않는다. 키는 web과 `worker` DB 자격으로 도는 서비스(`analysis-worker`·`prespec-attachment-worker`)가 **모두 같은 값**으로 읽어야 하므로 env 파일·overlay로 주고, 올린 뒤 `docker compose exec -T <서비스> printenv BIDOPS_RL_ANALYSIS_ENABLED`처럼 서비스마다 값 하나씩 확인한다.

**1. 배포 전제(운영 변경이므로 직전에 사람 확인).** migration `0040_card_analysis`(테이블 4개 + `briefing_item.slack_message_ts`, [contracts.md](contracts.md))와 `scripts/runtime-privileges.sql`의 새 권한(worker INSERT 5개 포함)을 적용하고 `web`·`analysis-worker`·`codex-runner` 이미지를 새로 올린다. 전체 백업과 `before-rl-verdict-<날짜>` 롤백 태그를 먼저 남기고 migration head를 기록한다. 새 테이블은 DELETE 권한이 없어 되돌리려면 백업으로 복구한다. 회사 근거(RL-00)의 활성 binding이 먼저 있어야 한다(없으면 `company_profile_not_ready`).

**2. 정책 import와 선택.** 정책 행은 승인 대상이자 선택 대상이다. 파일을 고쳐 쓰지 않고 immutable 파일을 import한다.

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli import-profile-policy \
  --policy /app/web/backend/app/deep_review/policies/analysis-policy-luna-rl-v11.json \
  --label analysis-policy-luna-rl-v11 \
  --expected-policy-sha256 8dabbbb473f81d91f5bffb73ea56cafb92876a80680f4d0b376bad245c1cf45a --actor '<담당자 이름>'
# 출력의 policy_version_id를 BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID로 env에 넣고 web·worker 서비스를 재생성한다.
# 이미지에 company-profile.md가 없으면 --profile 로 읽기 전용 마운트한 사본을 준다(2026-10-20 RL-05에서 확인).
# v10 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v10.json --label analysis-policy-luna-rl-v10
#   --expected-policy-sha256 fcfb08ce95887ce51c8454b54c2c51c9ac1ca9c4df63ff1544862387a8130409
# v9 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v9.json --label analysis-policy-luna-rl-v9
#   --expected-policy-sha256 afaba1d3b41177828443cb8e736e9b4728619a07fdfff2241ecb12d505fd2984
# v8 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v8.json --label analysis-policy-luna-rl-v8
#   --expected-policy-sha256 63ca5b691bb87822839193d4b33d0af7a6c7b9569faa86e9345da88ca5857d4c
# v7 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v7.json --label analysis-policy-luna-rl-v7
#   --expected-policy-sha256 2ba1d631b02d71b7c5fca251634bdc756c23b0308226ff14c741da5c2a631710
# v6 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v6.json --label analysis-policy-luna-rl-v6
#   --expected-policy-sha256 84e94954c08a43e5751d1514cf1a02e6865c9d6f05c6483777785e29faf8534a
# v5 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v5.json --label analysis-policy-luna-rl-v5
#   --expected-policy-sha256 19d7ff26fb9899f95237ec931c440bfad89feb42e3626fba89c33132f42928b2
# v4 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v4.json --label analysis-policy-luna-rl-v4
#   --expected-policy-sha256 8cc623f280ca5d155073ecd261f5a2a1ecd3a8d497fc5aec9c815537923183d7
# v3 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v3.json --label analysis-policy-luna-rl-v3
#   --expected-policy-sha256 635f673063ca1a92fb751aea6ffbdb76c54e0d70309b9f0a1e84d961fe192b12
# v2 행이 필요한 환경: --policy …/analysis-policy-luna-rl-v2.json --label analysis-policy-luna-rl-v2
#   --expected-policy-sha256 e733e94a02b1240794ac50b7397d3974fb241917cf73fdeed009ba4ba0c4ff3b
```

**v1 → v2 전환(결정 B23).** v2(`card.selector="card-sections-v2"`)는 기호·사설 영역 불릿 제목(실제 HWP의 U+F06D 등)도 영역 제목으로 보고, 원문에서 찾지 못한 영역이 있어도 종합까지 가서 `missing_sections`를 기록한다(누락이 있으면 판정은 `진행 가능`이 될 수 없다). v1 행으로 이미 만든 판정·승인은 그대로 남는다. 전환 순서: (1) 위 명령으로 v2 import(행 canonical sha = 파일 sha `e733e94a…ff3b`), (2) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v2 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v2 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 서비스마다 값을 확인, (3) **아래 3단계로 v2를 다시 승인**한다 — 승인은 정책 행 sha 단위라 v1 승인은 v2 행에 쓰이지 않는다(승인 없으면 `policy_not_approved`). 일일 상한 `today_used`는 v1·v2 행을 합쳐 센다. 선택 행을 바꾸면 v1 행으로 만든 판정은 현재성 사유 `policy_changed`로 "과거 기준"이 된다. import·선택 변경·승인은 각각 직전에 사람 확인을 받는다.

**v2 → v3 전환(결정 B30).** v3(`card.selector="card-sections-v3"`)는 쪽번호 없는 목차 항목과 본문 없는 제목 unit을 원문 unit에서 빼고, 추출 지시문에 검증 계약(unit당 item 하나·입력 순서, 개념은 payload의 `expected_concepts` 그대로 복사, 날짜·인원·operator 규칙, 중복 금지)을 명시하며, 추출 payload의 unit마다 코드가 계산한 `expected_concepts`를 싣는다(검증기는 그대로, [contracts.md](contracts.md) "전송 payload 규칙"). runner·runner contract·migration은 바뀌지 않아 web·`analysis-worker` 이미지만 새로 올린다. 전환 순서는 v1 → v2와 같다: (1) 위 명령으로 v3 import(행 canonical sha = 파일 sha `635f6730…2b12`), (2) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v3 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v3 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 서비스마다 값을 확인, (3) **v2 승인을 철회(`revoke-transfer-policy`, 사유 기록)하고 아래 3단계로 v3를 다시 승인**한다(`--policy analysis-policy-luna-rl-v3`; 승인은 행 sha 단위라 v2 승인은 v3 행에 쓰이지 않는다). `today_used`는 v1·v2·v3 행을 합쳐 세므로 같은 날 다시 승인할 때는 이미 쓴 수를 반영해 `--daily-cap`을 정한다. 선택 행을 바꾸면 v2 판정은 `policy_changed`로 "과거 기준"이 된다. 실제 호출 전 mock 경로(T11)를 v3 행으로 먼저 다시 돌리고, 추가 실제 호출은 다시 사용자 승인을 받는다(결정 B30). import·선택 변경·철회·승인은 각각 직전에 사람 확인을 받는다.

**v3 → v4 전환(결정 B33).** v4는 selector `card-sections-v3`를 유지하고 추출 출력 계약을 `bidops.requirement-extract.v2`로 바꾼다: 모델은 의미 필드만 내고(개념 후보·operator 없음) 코드가 그 둘을 채운 뒤 바뀌지 않은 검증기로 판정하며, kind×unit 규칙이 출력 schema에 있어 위반하면 규칙 코드와 item 번호만 담은 repair 1회를 받는다([contracts.md](contracts.md) "정책·단계 contract"). **runner 이미지도 다시 빌드해야 한다**(새 schema 파일 `/app/card-extract-v2.json`과 contract `card-extract-v2` 허용 목록). web·`analysis-worker` 이미지도 새로 올린다. migration은 없다. 순서: (1) runner·web 이미지 재빌드(직전 사람 확인), (2) 위 명령으로 v4 import(행 canonical sha = 파일 sha `8cc623f2…83d7`), (3) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v4 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v4 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`·runner를 재생성하고 서비스마다 값을 확인, (4) v3 승인을 철회하고 `--policy analysis-policy-luna-rl-v4`로 다시 승인(같은 날이면 `today_used`를 반영해 `--daily-cap` 결정), (5) mock 경로(T11)를 v4 행으로 먼저 돌리고, 실제 호출은 사용자 승인 범위(B33: 폴리텍 1건, 정상 8회·최대 16회, 실패 시 정지) 안에서만 한다. 선택 행을 바꾸면 v3 판정은 `policy_changed`로 "과거 기준"이 된다. 각 단계는 직전에 사람 확인을 받는다.

**v4 → v5 전환(결정 B35).** v5는 v4와 같은 추출 출력 계약(v2)·selector를 쓰고 추출 지시문만 바뀐다(숫자 제약은 숫자+단위+붙은 비교어를 그대로 인용, 분·초·글자·시간·간격은 text). 같은 배포에 들어간 검증기 강화(잘린 인용 거부, `까지`·`내에` → `lte`)는 **모든 정책 버전에 적용**되므로, web·`analysis-worker` 이미지를 올리면 v1~v4 행의 새 실행에도 바로 효력이 있다(이미 저장된 단계 행은 다시 검증하지 않는다). **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음; B33 runner 이미지 그대로). 순서: (1) web·`analysis-worker` 이미지 재빌드(직전 사람 확인), (2) 위 명령으로 v5 import(행 canonical sha = 파일 sha `19d7ff26…28b2`), (3) `BIDOPS_RL_DEEP_REVIEW_POLICY_VERSION_ID`를 v5 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v5 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`를 재생성하고 값 확인, (4) v4 승인 철회 → `--policy analysis-policy-luna-rl-v5`로 재승인(같은 날이면 `today_used` 반영), (5) mock 경로(T11)를 v5 행으로 먼저 돌린다(mock이 이제 숫자 제약을 낸다), (6) 실제 호출은 B35 승인 범위(폴리텍 1건, 정상 8회·최대 16회, 실패 시 정지) 안에서만. 각 단계는 직전에 사람 확인을 받는다.

**v5 → v6 전환(결정 B37).** v6는 v5와 같은 계약·selector에 추출 지시문만 바꾼다(숫자 인용은 block 안에서 유일하게 — 반복되면 왼쪽 단어를 붙임, 날짜 범위는 text이고 계산한 숫자 금지). 같은 배포의 검증기 수정(인용 유일성 `constraint_quote_not_unique`, 잘린 인용은 인용된 한 자리만 검사, 범위 `〜`·`.`/`)` 뒤 물결·숫자 사이 하이픈 → `unknown`)은 **모든 정책 버전에 적용**된다. **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음). 순서는 v4 → v5와 같다: web·`analysis-worker` 이미지 재빌드 → v6 import(행 canonical sha = 파일 sha `84e94954…534a`) → 선택 env 변경·재생성·값 확인 → v5 승인 철회·`--policy analysis-policy-luna-rl-v6` 재승인 → mock 경로(T11) 확인. 각 단계는 직전에 사람 확인을 받는다. **v6로는 실제 호출을 한 적이 없다**: 결정 B37로 이 배치의 실제 호출은 끝났고 RL-03 실제 증명(T12)은 pending이다. 다음 실제 호출은 새 사용자 승인 대상이다.

**v6 → v7 전환(결정 B51, 항목 단위 격리).** v7은 v6와 같은 추출 지시·계약·selector에 종합 지시문의 `rejected_units` 규칙만 더한다. 격리(증거 규칙을 어긴 항목만 "검증 실패 — 사람 확인 필요"로 빼고 판정을 이어감, 25% 초과면 판정 실패)는 **v7 이후 행(v7·v8·v9)에서만** 켜지고 v1~v6 행은 지금처럼 묶음 단위로 실패한다. 판정 보기 REST에 `rejected_units`와 matrix 행 `rejected_rule_codes`가 더해지고 판정 탭에 목록이 보인다(가산, migration 없음). **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음). web·`analysis-worker`와 프런트 이미지를 새로 올린다. 순서는 v5 → v6과 같다: 이미지 재빌드 → v7 import(행 canonical sha = 파일 sha `2ba1d631…1710`) → 선택 env 변경·재생성·값 확인 → v6 승인 철회·`--policy analysis-policy-luna-rl-v7` 재승인(같은 날이면 `today_used` 반영) → mock 경로(T11) 확인 → 실제 호출은 B51 승인 범위(폴리텍 1건 + 검증 실패 시 재시도 1회, attempt당 정상 8회·최대 16회) 안에서만. 각 단계는 직전에 사람 확인을 받는다. 판정 탭에 격리 목록이 있으면 담당자가 해당 요구사항을 원문으로 확인한다(자동으로 고치지 않는다).

**v7 → v8 전환(결정 B53).** T12 8차에서 운영·위험 역할이 같은 unit의 제약 인용(추출에서 원문 일치 검증 통과)을 근거로 써 `card_role_invalid`가 났다. 검증기는 이제 **모든 정책 버전**에서 unit별로 item evidence ∪ 그 unit 제약의 locator+quote를 허용하고(다른 unit·원문과 다른 문자열은 계속 거부), v8은 v7과 같은 규칙에 역할·종합 지시문 한 문장만 더한다. web·`analysis-worker` 이미지만 새로 올리고 **runner 이미지는 다시 빌드하지 않는다**(contract·schema 변경 없음), 판정 보기 모양 변화 없음(프런트 재배포 불필요). 순서: 이미지 재빌드 → v8 import(행 canonical sha = 파일 sha `63ca5b69…7d4c`) → 선택 env 변경·재생성·값 확인 → v7 승인 철회·`--policy analysis-policy-luna-rl-v8` 재승인(같은 날이면 `today_used` 반영) → mock 경로(T11) 확인 → B51 승인 범위의 남은 재시도 1회는 v8로. 각 단계는 직전에 사람 확인을 받는다.

**v8 → v9 전환(결정 B55, 종합 출력 계약 v2·종합만 다시 실행).** T12 9차(v8)는 역할 3개까지 통과하고 종합이 역할 밖 대상·차단 조건 범위를 어겨 `card_synthesis_invalid`였다. v9는 추출·역할을 v8과 byte 동일하게 두고 종합 출력 계약을 `bidops.practitioner-verdict.v2`(차단 조건 없음 — 코드가 필수 gap으로 계산, 누락 영역·격리 unit "사람 확인" 행은 코드가 붙임)로 바꾼다. **runner 이미지를 다시 빌드해야 한다**(새 schema 파일 `/app/card-synthesis-v2.json`·contract `card-synthesis-v2` 허용 목록). web·`analysis-worker`·프런트 이미지도 새로 올린다(판정 보기 `next_actions[].origin` 가산·판정 탭 "사람 확인" 표식). migration·권한 변경은 없다. 순서: (1) runner·web·프런트 이미지 재빌드(직전 사람 확인), (2) v9 import(행 canonical sha = 파일 sha `afaba1d3…2984`), (3) 선택 env를 v9 행으로 바꾸고 `BIDOPS_RL_ANALYSIS_POLICY_PATH`를 지정했다면 v9 파일로 맞춘 뒤 web·`analysis-worker`·`prespec-attachment-worker`·runner 재생성·값 확인, (4) v8 승인 철회·`--policy analysis-policy-luna-rl-v9` 재승인(같은 날이면 `today_used` 반영), (5) mock 경로(T11, v9·mock 실패 종합 뒤 resume) 확인, (6) 실제 호출은 새 사용자 승인 범위 안에서만 — 종합만 실패한 v8 attempt는 아래 요청으로 **종합만** 다시 실행할 수 있다(검증된 추출·대조·역할 행 재사용, 호출 1회, 상한 1; 전제 조건이 하나라도 어긋나면 409 `resume_source_invalid`이고 아무것도 남지 않는다). 각 단계는 직전에 사람 확인을 받는다.

```bash
# 종합만 다시 실행(결정 B55): 실패 attempt id는 판정 보기 ⋯ 실행 정보 또는 GET …/verdict의 attempt_id
curl -sS -X POST "http://127.0.0.1:<web 포트>/api/opportunities/<opportunity_id>/verdict-requests" \
  -H 'Content-Type: application/json' -H 'X-BidOps-Actor-Name: <담당자 이름>' \
  -d '{"request_id":"<새 UUID>","resume_from_attempt_id":"<실패 attempt id>"}'
# 202 {request_id, attempt_id, status:"queued"} → worker 처리 뒤 GET …/verdict 로 완료 확인.
# 확인: card.resume.requested·card.stages.reused 감사, analysis.transfer.sent planned_call_count=1,
#       GET /api/analysis/transfer-policy today_used가 1 늘었는지.
```

**v9 → v10 전환(결정 C15·C16).** 새 실행은 v10이 v9를 대신한다(v9 행·attempt·승인 기록은 그대로 남고, v9 → v10은 종합만 다시 실행의 계보가 아니다). v10은 큰 영역 분할(selector `card-sections-v4`)과 역할 출력 계약 v2(근거 번호 인용·역할 항목 격리)·추출 누락 unit 격리를 더한다. **runner 이미지를 다시 빌드해야 한다**(새 schema 파일 `/app/card-role-v2.json`·contract `card-role-v2`), web·`analysis-worker`·프런트도 새로 올린다(판정 보기 `role_isolations` 가산). 순서는 v8 → v9와 같다: 이미지 재빌드 → v10 import(행 canonical sha = 파일 sha `8b5be91e…93f9`) → 선택 env·`BIDOPS_RL_ANALYSIS_POLICY_PATH`를 v10으로 → v9 승인 철회·`--policy analysis-policy-luna-rl-v10` 재승인 → mock 경로(T11) 확인. 각 단계는 직전에 사람 확인을 받는다.

**v10 → v11 전환(결정 C20).** 새 실행은 v11이 v10을 대신한다(파일 sha `8dabbbb4…f45a`; v10 행·attempt는 그대로이고 v10 → v11은 종합만 다시 실행의 계보가 아니다). 순서는 v9 → v10과 같고 runner 이미지 재빌드가 필요하다(새 schema `/app/card-role-v3.json`·`/app/card-synthesis-v3.json`). 각 단계는 직전에 사람 확인을 받는다.

(경로는 web 이미지 안 위치다. 품질 인자는 주지 않는다 — 측정한 값이 없다.) `policy_sha256`은 이 **행의 canonical sha**이고 파일 raw sha가 아니다. 값을 하나라도 바꾸려면 새 버전 파일을 발행하고 다시 import·승인한다.

**3. 전송 정책 승인(사람 직전 확인 대상, 실제 전송 권한을 여는 단계).**

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli approve-transfer-policy \
  --policy analysis-policy-luna-rl-v9 --actor '<담당자 이름>' --daily-cap <N> [--dry-run]
# v1~v8 행을 계속 쓰는 환경이면 --policy analysis-policy-luna-rl-v1|…|v8(정책 파일 경로도 같은 버전)
```

- 출력 JSON의 `approval_id`·`policy_sha256`·`daily_cap`·`created`·`errors`를 기록에 적는다. `--daily-cap`은 하루(KST)에 **실제로 외부 전송한** RL attempt 수의 **코드로 강제되는 상한**이다(1..50, 기본 10, 결정 B17). `today_used`는 `analysis.transfer.sent` 감사가 있고 mock이 아닌 attempt만 센다 — mock attempt·전송 전에 멈춘 attempt는 세지 않는다. 대신 시작(자동·수동·drain) 시점에는 아직 전송하지 않은 실제 attempt(queued·running)를 예약으로 함께 세고, worker가 첫 호출 직전에 상한을 다시 검사해 넘으면 `daily_cap_reached`로 실패시킨다(전송 0). 배치 B 격리 실증은 `--daily-cap 2`(실제 1건 + 재시도 1)로 고정했다. 활성 승인은 정책 sha당 하나이며 두 번째는 `active_approval_exists`(exit 2), 정책·선택 행·모델 identity가 어긋나면 `policy_identity_mismatch`(exit 2)다. `--dry-run`은 쓰기 없이 검사한다.
- 확인: `GET /api/analysis/transfer-policy`의 `active.approval_id`·`daily_cap`·`today_used`가 CLI 출력과 같은지 본다(화면 조작은 서버 상태로 확인한다).
- **철회:** `revoke-transfer-policy --approval-id <id> --actor <이름> --reason <사유>`. 한 번만 가능하며 이후 자동 경로와 worker가 호출 전에 `policy_not_approved`로 멈춘다. 이미 실행 중인 attempt도 첫 호출 전 승인 재검사에서 멈춘다. 상한을 바꾸려면 철회하고 새로 승인한다.

**4. Luna runner와 인증·egress.** 기존 `docker-compose.luna.yml`(profile `luna`)을 쓴다. `codex-runner`만 `luna-internal`(내부)과 `luna-egress` 두 네트워크에 있고 web·`analysis-worker`는 내부망뿐이며 runner에는 DB·MinIO·원문 volume이 없다. 인증은 `env/luna.env`의 `BIDOPS_CODEX_AUTH_FILE`이 가리키는 `auth.json` 파일 **하나를 compose secret으로 runner에만 읽기 전용 마운트**한다. 로컬 PoC는 호스트 개인 로그인 파일을 쓰며(2026-10-17 인터뷰 D6, CLI 0.162.1) 값·파일 내용을 로그·문서·채팅·명령줄에 남기지 않고 다른 서비스에 마운트하지 않는다. runner 이미지는 `card-extract-v1|card-role-v1|card-synthesis-v1` contract를 알아야 하므로 이 변경 뒤 다시 빌드한다. `luna-egress`는 host allowlist가 아니므로 운영에서는 방화벽에서 runner의 필요한 통신만 허용했는지 따로 확인한다. 구현·mock 검증은 Luna 인증·모델 접근·실자료 품질을 증명하지 않는다. 오케스트레이션 명령 배열과 롤백은 [Luna 운영 적용 절차](0922_luna-deep-review/apply.md)의 compose 조합을 따르고 서비스 교체는 `up -d --no-deps --no-build --force-recreate`로 한다.

**4a. 로컬 원본 연결(결정 B15, 첨부 행에 파일이 없을 때).** G2B 링크만 있고 바이트가 없는 사전규격 첨부 행에, 이전 수집본과 sha256이 같은 로컬 원본을 연결한다. G2B를 부르지 않으며 바이트는 G2B fetcher와 **같은** 격리→ClamAV·MIME/확장자 검사→source→문서·구조 경로를 지난다. 연결 뒤 그 공고의 문서 준비를 trigger `operator_local_original`로 연다(등급·브리핑 자격만 건너뛰고 취득 종결·safe·구조·확정 fence는 그대로). 첨부 worker와 같은 자격·네트워크(worker DB 자격, `scanning` 네트워크의 ClamAV, 문서 storage, 변환 scratch)를 쓰므로 `prespec-attachment-worker` 컨테이너에서 실행하고, HWP 변환을 위해 `document-worker`가 떠 있어야 한다. 운영 DB 쓰기이므로 직전에 사람 확인을 받는다.

```bash
# 파일을 컨테이너 안의 임시 경로로 복사한다(호스트 경로는 컨테이너에서 보이지 않는다).
docker compose -f docker-compose.yml cp '<로컬 원본.hwp>' prespec-attachment-worker:/tmp/local-original.hwp
docker compose -f docker-compose.yml exec -T prespec-attachment-worker \
  python -m app.deep_review.cli attach-local-original \
  --notice-id <notice_id> --attachment-id <attachment_id> --file /tmp/local-original.hwp \
  --expected-sha256 <이전 수집본 sha256> --actor '<담당자 이름>' --dry-run
# dry-run 출력(errors=[])을 확인한 뒤 같은 명령을 --dry-run 없이 한 번 실행하고, 임시 파일을 지운다.
docker compose -f docker-compose.yml exec -T prespec-attachment-worker rm -f /tmp/local-original.hwp
```

- 출력 JSON `{notice_id, attachment_id, content_sha256, size_bytes, provenance, fetch_status_before, document_version_id, scan_status, preparation, dry_run, errors}`를 기록에 적는다. `preparation.confirmed=true`면 묶음이 `ready`다. `preparation.reason=awaiting_fetch`면 같은 공고의 다른 첨부 취득이 아직 끝나지 않았다는 뜻이며 그 첨부도 연결하거나 취득을 종결한 뒤 다시 준비한다.
- 거부(exit 2, 쓰기 없음): `sha256_mismatch`, `attachment_notice_mismatch`, `attachment_not_found`, `attachment_has_bytes`(문서가 이미 있거나 취득 `완료` — 이중 등록 방지), `attachment_fetch_in_progress`(G2B worker lease 중), `attachment_source_not_g2b`, `attachment_retired`, `notice_not_pre_spec`, `unsupported_extension`, `file_not_regular`(symlink·디렉터리 포함), `file_size_limit`(50MiB), `malware_detected`, `mime_mismatch`. 재시도성 실패(exit 1): `clamav_unavailable`·`converter_unavailable`·`service_unavailable`·`storage_failed`. 출력·stderr에 로컬 경로는 없다.
- 감사 `prespec_attachment.local_original`(actor=담당자, `provenance=operator_local_original`, sha·크기·문서 id·취득 행의 이전 상태)이 성공·검사 차단마다 하나 남는다. 성공하면 첨부의 취득 행(있으면)이 `완료`로 바뀌고 lease fence가 올라가 이후 G2B worker가 같은 첨부를 다시 쓰지 않는다. 문서 버전은 `source_kind=provider`·`source_system=g2b`(원래 첨부의 출처)이고 `created_by_name`이 담당자다.

**mock 전체 경로(T11, 결정 B16).** `BIDOPS_ANALYSIS_PROVIDER=mock`(참조 모드 필수)이면 카드 판정은 같은 단계·검증기를 지나되 결정적 mock client가 답한다(단위 원문을 그대로 인용, 제약·숫자 없음, 종합은 `판단 불가`). runner·네트워크 호출이 없고 `analysis.transfer.sent`도 남지 않으며 상한을 쓰지 않는다. 생성 감사의 provider 계보가 `mock-analysis`라 판정 보기의 `quality_status`는 `mock_reference`다 — 연결 증명일 뿐 품질 근거가 아니다. mock으로 판정한 공고의 review는 계보가 mock으로 고정되어 같은 DB에서 실제 호출로 이어 갈 수 없으므로(worker가 `service_unavailable`로 거부) T11과 T12는 서로 다른 DB에서 한다.

**5. 수동 요청 시운전.** 자동 시작은 끈 채(`BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`, 개요·심층 자동도 false) 사업기회 판정 탭의 "다시 판정"(또는 `POST /api/opportunities/{id}/verdict-requests`)으로 한 건만 요청한다. 직전에 사람이 대상 공고·상한·승인(`today_used`)을 확인한다. 실제로 전송한 요청만 상한을 소비하고(B17) `analysis.transfer.sent` 감사가 첫 호출 전에 한 번 남아야 한다 — **그 감사가 없는 전송, payload에 노트·`proposed`/`unknown` 값·운영 정보가 들어간 정황, 상한 초과는 즉시 중단하고 보고한다.** 검증 실패(`failed`·`needs_human_review`)는 자동으로 다시 시도하지 않으며 사람이 한 번 다시 판정할 수 있다. 같은 시도가 또 실패하면 멈추고 후속 의존 실행(RL-04 초안)은 보류한다. 증거는 [README](validation-runs/2026-10-17-rl/RL-03/README.md)에 attempt id·sha·호출 수·시간·`analysis.transfer.sent` 건수로 남긴다.

**6. 자동 시작과 큐(운영 자동화, 별도 확인).** `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=true`는 `build-briefing`이 만든 추천 항목마다 위 자동 시작 조건을 평가하게 만든다. 추천받은 SW=Y 사전규격에 ready 묶음이 없으면 문서 준비를 열며, 이때 묶음 생성의 등급 자격만 건너뛴다(결정 B18, 개요 플래그와 무관; 안전 검사·확정 fence는 그대로). 이 플래그를 켜는 것, cron(브리핑 CLI)에서 켜진 채 도는 것은 실제 모델 전송을 일으키므로 승인 상한과 직전 확인이 필요하다. 상한을 넘은 요청은 큐에 쌓이고 **다음 브리핑이 새로 만들어진 직후** 한 번 처리된다(자동 따라잡기 없음). 필요하면 수동으로:

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli drain-verdict-queue [--date YYYY-MM-DD]
# RL-05 홀드아웃: 자동 분석에서 뺄 사전규격
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor '<이름>'
```

`drain`의 `--date`는 "그 날짜(KST) **이전**에 쌓인 요청"을 처리하라는 뜻이며 한 번만 돈다. 출력의 `stopped_reason`(`daily_cap_reached`·`policy_not_approved`·`auto_start_disabled`)·`remaining`(남은 큐)을 확인한다. 큐 길이가 늘기만 하면 상한이나 승인을 사람이 다시 정한다. 자동 시작의 실제 스택 증명은 T11 mock이 하며(실제 스택에서 자동 시작을 켜 둔 실증은 이 기능의 범위가 아니다) 가짜로 증명되지 않는 생성→폴링→후속 경로는 실제 스택에서 한 번 돌기 전까지 "검증됨"이라 쓰지 않는다.

**7. Slack 스레드 답글은 지금 켜지 않는다(D5).** 판정 완료 스레드 답글은 판정을 닫는 `analysis-worker`가 `core/slack.py`로 보내는데, Slack overlay(`docker-compose.slack-egress.yml`)는 `env/slack.env`와 egress network를 `web`·`slack-worker`에만 주고 `analysis-worker`에는 주지 않는다. 그래서 현재 구성에서는 전송기 호출 전 검사가 막아 답글이 **건너뛰어지며 오류가 아니다**. 켜려면 worker에 토큰·egress를 주는 별도 overlay 변경과 사람 확인이 필요하며 이번 범위에서는 하지 않았다. 스레드 답글의 증명은 가짜 서버 검사까지이고 실제 Slack 게시 증명으로 적지 않는다.

**8. 되돌리기.** 가장 빠른 차단은 `revoke-transfer-policy`(이후 호출 0)이고, 그다음 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`·`BIDOPS_RL_ANALYSIS_ENABLED=false`로 재생성한다. 이미 저장된 판정·단계 행은 append-only라 지우지 않는다. 승인 철회는 감사 기록이 남는 CLI로만 하며 SQL로 고치지 않는다.

**검증 명령(문서 단계 근거).** 변경 영향 범위만 돌린다: `pytest tests/deep_review/test_card_analysis.py tests/deep_review/test_card_compare.py tests/app/test_transfer_policy.py tests/app/test_verdict_api.py tests/app/test_verdict_payload_guard.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py`, PostgreSQL 변형은 일회용 `postgres:17.11`과 `BIDOPS_TEST_POSTGRES_URL`로 `test_card_analysis_postgres.py test_verdict_trigger_postgres.py test_db_migrations.py test_runtime_database_privileges.py`, 화면은 `npx playwright test --project=app verdict.spec.ts opportunity-record.spec.ts`.

## RL 제안서 초안 운영 (RL-04, 2026-10-18)

판정이 끝난 사업기회의 제안서 초안(여섯 절·요구사항 대응표·PDF)을 만드는 실행·설정·승인 절차다(규칙은 [business-rules.md "제안서 초안"](business-rules.md#제안서-초안-rl-04-2026-10-18), 계약은 [contracts.md "제안서 초안"](contracts.md#제안서-초안-rl-04-2026-10-18)). **구현·mock 검증은 `bidops-local` 격리 스택에서 한 것이고 운영 `bidops` 스택·운영 DB에는 반영하지 않았다.** 실제 Luna 초안 1건(T11)은 입력이 되는 RL-03 실제 판정이 없어 pending이다(결정 B37). 실제 초안·정책 승인·재배포·migration은 모두 직전에 사람 확인을 받는다.

**설정.**

| 키 | 기본 | 역할 |
|---|---|---|
| `BIDOPS_PROPOSAL_POLICY_PATH` | `policies/proposal-policy-luna-v1.json` | import 원본(immutable). 승인 CLI가 이 파일의 identity·sha를 선택 행과 대조한다 |
| `BIDOPS_PROPOSAL_POLICY_VERSION_ID` | 없음 | import한 정책 행 선택. 비면 초안 생성·worker가 fail closed(`analysis_policy_unavailable`). RL-03 선택 env와 별개 |
| `BIDOPS_PDF_FONT_DIR` | `/usr/share/fonts/truetype/nanum` | 백엔드 이미지가 apt `fonts-nanum`으로 넣는 `NanumGothic.ttf`·`NanumGothicBold.ttf`의 위치. 저장소에는 폰트 파일이 없다(D9). 없거나 읽을 수 없으면 내보내기가 503 `pdf_unavailable`. 이미지 폰트가 바뀌면 `font_sha256`이 바뀌어 같은 초안도 새 PDF가 된다 |
| `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`BIDOPS_PROPOSAL_PDF_SECRET_KEY` | 없음(compose는 `:?`로 요구) | 버킷 `bidops-proposal-pdf` 전용 자격증명. **web과 minio-init만** 받는다(분석 worker는 PDF를 다루지 않는다, 결정 B49) |
| `BIDOPS_RL_ANALYSIS_ENABLED`·`BIDOPS_LUNA_DEEP_REVIEW_ENABLED`·`BIDOPS_REFERENCE_WORKFLOW_MODE` | 기존 | 셋 다 켜져 있어야 경로가 열리고 실행된다. 꺼져 있으면 제안서 경로는 404·503이다 |

RL 키와 정책 선택 env는 web과 `analysis-worker`가 **같은 값**으로 읽어야 하므로 env 파일·overlay로 주고, 올린 뒤 서비스마다 `docker compose exec -T <서비스> printenv BIDOPS_PROPOSAL_POLICY_VERSION_ID`로 확인한다. PDF 키는 web에서만 확인한다.

**1. 배포 전제(운영 변경, 직전 사람 확인).** migration `0041_proposal_draft`(테이블 4개, [contracts.md](contracts.md#제안서-초안-rl-04-2026-10-18))와 `scripts/runtime-privileges.sql`의 새 권한을 적용하고 `web`·`analysis-worker`·`codex-runner`(contract `proposal-section-v1` 스키마 COPY) 이미지를 새로 올린다. 전체 백업과 `before-rl-proposal-<날짜>` 롤백 태그를 먼저 남긴다. **main 병합 뒤 운영 스택을 다시 올리기 전에** 운영 env(`.env` 등 gitignore 파일)에 `BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`를 넣고 `minio-init`을 다시 실행해 버킷 `bidops-proposal-pdf`(versioning·전용 정책·365일 만료)를 만든다 — 키가 없으면 compose가 web·minio-init 기동을 거부한다(결정 B49). 이 단계도 직전에 사람 확인을 받는다.

**2. 정책 import와 선택.** 파일을 고쳐 쓰지 않고 immutable 파일을 import한다.

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli import-profile-policy \
  --policy /app/web/backend/app/deep_review/policies/proposal-policy-luna-v1.json \
  --label proposal-policy-luna-v1 \
  --expected-policy-sha256 0eb36cf9e4318e447dd2c66f59a060a9ec1d87b92c23326200867060973e7d91 --actor '<담당자 이름>'
# 출력의 policy_version_id를 BIDOPS_PROPOSAL_POLICY_VERSION_ID로 env에 넣고 web·analysis-worker를 재생성한다.
```

이 행은 전역 active policy나 RL-03 판정 정책으로 쓸 수 없다(선택하면 fail closed).

**3. 전송 정책 승인(사람 직전 확인, 실제 전송 권한을 여는 단계).**

```bash
docker compose -f docker-compose.yml exec web \
  python -m app.deep_review.cli approve-transfer-policy \
  --policy proposal-policy-luna-v1 --actor '<담당자 이름>' --daily-cap 1 [--dry-run]
```

- 실제 사용(T11)은 `--daily-cap 1`(초안 1건 = 절 6건, 배치 B 인터뷰 D3·D10)이다. 기본은 3, 범위 1..20이며 절 다시 쓰기는 1/6건으로 센다. 승인 행은 `scope={"purposes":["proposal"]}`로 RL-03 승인과 따로 있고 서로의 게이트·상한에 보이지 않는다. 출력 JSON의 `approval_id`·`policy_sha256`·`daily_cap`을 기록한다.
- 철회는 `revoke-transfer-policy --approval-id <id> --actor <이름> --reason <사유>`이고 이후 worker가 첫 호출 전에 `policy_not_approved`로 멈춘다(절은 `failed`). 상한을 바꾸려면 철회하고 새로 승인한다.

**4. 실행.** 초안은 사업기회 제안서 탭의 "제안서 초안 만들기"(또는 `POST /api/opportunities/{id}/proposal-requests`)로 만든다. 직전에 사람이 대상 판정·상한·승인을 확인한다. 절 실행은 합성 `analysis-worker`의 같은 슬롯에서 **다른 큐가 비었을 때 마지막으로** 돈다(새 서비스 없음). worker는 절마다 입력을 동결·검사한 뒤 승인·상한을 다시 보고(자기 절 제외) → runner 주소를 검사하고 → `analysis.transfer.sent`(purpose `proposal`)를 한 번 남긴 뒤 → `codex-runner`(`proposal-section-v1`, 절당 900초)를 부른다(주소·승인 실패는 감사·상한 소비 없이 절 `failed`). Luna runner·인증·egress는 RL-03과 같다("RL 카드 판정 운영" 4). 실패한 절은 자동으로 다시 돌지 않으며 사람이 "이 절 다시 쓰기"를 누른다(검토 완료·제출 준비 단계에서는 막히고 새 초안으로 다시 만든다, 결정 B50). 초안 1회차의 절들은 첫 실행부터 5400초를 공유한다.

**5. mock 경로(T10).** `BIDOPS_ANALYSIS_PROVIDER=mock`(참조 모드 필수)이면 같은 게이트·검증기를 지나되 결정적 mock client가 절을 만든다(요구사항 원문을 통째로 인용, 빠진 회사 사실은 빈 자리, 대응표 누락 0). runner·네트워크 호출이 없고 `analysis.transfer.sent`도 없다. 생성할 때는 실제와 같이 **활성 proposal 승인과 상한 여유가 필요하지만** mock 계보 초안의 절은 사용량에 세지 않는다. 생성 감사의 provider 계보가 `mock-analysis`로 고정되어 결과는 `mock_reference`이고, 나중에 실제 provider worker가 그 초안을 실행하지 않는다(`model_binding_invalid`). mock 초안을 실제 품질 근거로 쓰지 않는다. 격리 스택 시운전 기록은 RL-04 검증 기록에 있다.

**6. PDF.** "PDF로 내보내기"(`POST /api/proposals/{draft_id}/exports`)는 web이 렌더해 `bidops-proposal-pdf`에 암호화 없이 저장하고 같은 내용이면 기존 PDF를 돌려준다. 저장 바이트는 `content_object.sha256`과 같아야만 내려가며(`GET …/exports/{id}.pdf`), 이 버킷은 객체 백업·복구·active hash 검증 대상이고 365일 뒤 만료한다. 폰트가 없는 환경(호스트 테스트 등)은 `BIDOPS_PDF_FONT_DIR`로 위치를 준다.

**7. 되돌리기.** 가장 빠른 차단은 `revoke-transfer-policy`(이후 호출 0), 그다음 `BIDOPS_RL_ANALYSIS_ENABLED=false`로 재생성이다. 초안·절·수정·PDF 행은 append-only라 지우지 않으며 SQL로 고치지 않는다.

**검증 명령(문서 단계 근거).** `pytest tests/deep_review/test_proposal_input.py tests/deep_review/test_proposal_validation.py tests/deep_review/test_mock_proposal_client.py tests/deep_review/test_proposal_render.py tests/app/test_proposal_transfer_policy.py tests/app/test_proposal_draft.py tests/app/test_proposal_api.py tests/deep_review/test_codex_runner.py tests/app/test_company_luna_policy.py tests/app/test_runtime_contract.py`(PostgreSQL 변형은 `BIDOPS_TEST_POSTGRES_URL`, PDF 사례는 `BIDOPS_PDF_FONT_DIR`이 있어야 skip 없이 돈다).

## RL 판정 gold 인수 평가 (RL-05, 2026-10-19)

RL-03 카드 판정이 사용자 gold 10건과 맞는지 보는 평가 절차다(기준·독립성 규칙은 [model-quality-gate.md "RL 판정 gold 인수"](model-quality-gate.md#rl-판정-gold-인수-rl-05), 계약은 [RL-05 spec](work/groups/RL/features/RL-05-gold-acceptance/spec.md)). **격리 스택 `bidops-local`의 별도 DB에서만 하고 운영 `bidops` 스택·운영 DB는 건드리지 않는다.** 제품 CLI `export-evaluation`은 읽기 전용이고 채점·인수는 제품 밖(`scripts/rl-gold.py`)과 사람이 한다. 결과는 사람이 `accept`하기 전까지 `unmeasured_reference`이며 품질 근거가 아니다. 실행 기록은 [validation-runs/2026-10-19-rl/RL-05](validation-runs/2026-10-19-rl/RL-05/README.md)다.

**평가 디렉터리.** Git 밖 `.sdlc/local-runtime/rl-evaluation-<날짜>/`(`.git/info/exclude`로 무시)에 `selection.v1.json`, `cards/`, `cards.json`, `gold.v1.json`, `actual.v1.json`, `alignment.v1.json`, `prediction.v1.json`, `receipt.json`, `score.v1.json`, `acceptance.json`을 둔다. `--out`으로 쓰는 **파일은 모두 새로 만든다**(같은 이름이 있으면 `output_exists`, 디렉터리는 이미 있어도 된다)이고 worktree 안이면 git이 무시하는 경로만 허용한다(`output_not_ignored`). `export-evaluation`은 DB·객체 저장소에 닿는 컨테이너 안에서 돌고 `--selection`·`--gold`·`--out`은 그 컨테이너 안 경로이므로 평가 디렉터리를 마운트하거나 결과를 꺼내 쓴다. `rl-gold.py`는 파일만 읽고 쓰며 호스트에서 돈다. 문서 원문·gold·모델 답은 저장소·로그에 남기지 않는다.

1. **후보 고르기.** 사전규격 중 문서 준비 `ready`, 개요 `completed`, **묶음마다 분석 원문(source)이 하나**인 것만 후보다. 원문이 여럿인 묶음은 export가 `selection_mismatch`로 거부한다. 요구사항 카드가 10개 미만인 문서는 카드 상태 표본 10개를 채울 수 없어 gold를 쓸 수 없으므로 뺀다(카드 수는 5단계 `cards.json`에서 보이므로 후보 몇 건을 여유로 두고 고른다). 선정은 사람이 하며 도구는 고르지 않는다. 대체 후보까지 4단계의 홀드아웃에 함께 넣는다.
2. **회차 적재.** 격리 DB에 수집 회차 디렉터리를 바이트 그대로 복사하고(파일별 sha256 대조) 적재한다: `python -m app.lifecycle.ingest.cli --run <회차> --collection`. 격리 DB에는 사업기회 연결 대상·선별 결과가 없어 `opportunity_link_target_missing`·`screening_results_missing` 경고가 나는 것이 정상이다. 적재 직후 `GET /api/runs/<회차>/warnings`로 경고 종류만 확인한다.
3. **원문 연결.** 격리 DB에는 G2B 링크만 있고 바이트가 없다. 검증된 객체 백업(`object-versions.tsv`의 sha256과 버전이 맞는 source 객체)이나 담당자가 가진 사본을 가져와 [RL-03 4a절](#rl-카드-판정-운영-rl-03-2026-10-17)의 `attach-local-original --notice-id <id> --attachment-id <id> --file <파일> --expected-sha256 <sha256> --actor '<이름>'`로 연결한다. **`--dry-run`을 먼저** 보고(`errors=[]`) 실제 실행한다. G2B를 부르지 않으며 ClamAV·MIME 검사를 지난다. 모든 묶음이 `ready`인지 확인한다.
4. **홀드아웃 — 다른 무엇보다 먼저.** 선정 공고를 gold 작성 전에 자동 분석에서 뺀다: `python -m app.deep_review.cli drain-verdict-queue --hold <notice_id,…> --reason gold_holdout --actor '<이름>'`(RL-03 6절). 공고마다 `verdict_request`에 `rejected`·`gold_holdout` 행이 생기고 같은 시점에 그 공고의 RL review가 0건이어야 한다. 선정이 끝날 때까지 web·worker의 `BIDOPS_RL_ANALYSIS_AUTO_START_ENABLED=false`를 유지한다.
5. **카드 pack과 빈 gold 양식.** 사람이 `selection.v1.json`(`bidops.rl-evaluation-selection.v1`: 문서별 `document_id`·`notice_id`·`opportunity_id`·`source_sha256`·`structure_id`·`manifest_id`·`title`·`agency`, `company_sha256`=활성 graph sha, `ontology_sha256`, `selected_on`)을 쓴다. 이어서:

   ```bash
   python -m app.deep_review.cli export-evaluation --cards --selection <eval>/selection.v1.json --out <eval>/cards
   python3 scripts/rl-gold.py export-cards --cards-pack <eval>/cards --out <eval>/cards.json
   python3 scripts/rl-gold.py blank-gold --cards <eval>/cards.json --selection <eval>/selection.v1.json --out <eval>/gold.v1.json
   python3 scripts/rl-gold.py gold-check --gold <eval>/gold.v1.json --selection <eval>/selection.v1.json   # 빈 양식은 human_gold_incomplete(exit 2)가 정상
   ```

   `selection_mismatch`·`binding_mismatch`는 선정 파일이 DB와 다르다는 뜻이다. 카드 pack은 읽기 전용으로 꺼낸 구조·page map이고 모델 답이 없다. PDF 스냅샷이 없으면 page map 파일이 없고 `page_map_sha256`은 `null`이다.
6. **사람이 gold를 쓴다 — 모델 실행 전.** 문서마다 판정·차단 조건·충족/부족·주의·카드 상태 표본 10을 적고 `annotator`·`authored_at`(ISO-8601, 시간대 포함)·`written_before_model_output=true`를 채운다. 미작성 `null`과 확인 후 없음 `[]`을 구분한다. `gold-check`가 exit 0이어야 다음으로 간다. gold를 고치면 새 버전 디렉터리를 만든다.
7. **실제 판정(모델 실행).** `gold-check` 통과 뒤에만 공고마다 수동으로 요청한다(`POST /api/opportunities/{id}/verdict-requests` 또는 판정 탭). 이 요청이 holdout 행을 해제한다. **실제 Luna 전송은 RL-03 정책 단위 승인([RL-03 3절](#rl-카드-판정-운영-rl-03-2026-10-17), 상한)이 있어야 하고 요청 직전에 사람이 대상·상한·승인을 확인한다.** 상한을 넘는 날은 다음 KST 날로 나눈다. 판정이 `failed`면 그대로 두고 결정 B55의 종합 재실행 같은 RL-03 절차로 이어 가며 gold·표본을 바꿔 맞추지 않는다. 완료된 attempt만 채점 대상이다.
8. **actual → alignment → 최종 export → 채점.** 순서가 바뀌면 안 된다.
   1. 먼저 gold·alignment **없이** 별도 초안 디렉터리로 내보낸다: `export-evaluation --actual --selection <eval>/selection.v1.json --out <eval>/actual-draft`. 결과는 `actual.v1.json` 하나(모델이 낸 차단 조건 단위 목록 포함)다. 선정 공고마다 완료된 RL attempt가 없으면 `missing_attempt`, 같은 조건의 정책 다름·mock·실패·실행 중 attempt는 점수 대상이 아니라 건수만 요약에 남는다.
   2. 사람이 `alignment.v1.json`(`bidops.rl-condition-alignment.v1`)을 쓴다: **gold 파일 sha256과 위 actual 파일 sha256을 적고**, 모델의 차단 조건 단위마다 대응하는 gold 조건 ID(없으면 빈 목록)와 사유를 적는다. 모델 차단 단위는 하나도 빠지면 안 된다(`invalid_alignment`).
   3. 최종 디렉터리(**초안과 다른 경로** — 같은 이름 파일을 다시 만들 수 없다)로 내보낸다: `export-evaluation --actual --selection … --gold <eval>/gold.v1.json --condition-alignment <eval>/alignment.v1.json --out <eval>`. `gold_after_model`·`holdout_violated`면 export가 거부되고 그 표본은 교체 대상이다. 성공하면 `actual.v1.json`·`prediction.v1.json`·`receipt.json`이 생긴다초안과 최종의 `actual.v1.json`은 같은 바이트(같은 attempt·같은 입력)라 alignment의 actual sha가 그대로 맞는다..
   4. `python3 scripts/rl-gold.py score --gold <eval>/gold.v1.json --prediction <eval>/prediction.v1.json --criteria docs/work/groups/HP/preparation/acceptance-criteria.approved.v1.json --out <eval>/score.v1.json`. 출력은 지표 네 개·비일치 목록이고 `decision=null`이다.
9. **인수 기록(사람).** 사람이 `acceptance.json`(`bidops.rl-acceptance.v1`)에 `decision`(`accept|reject|defer`)·`decided_by`·`decided_at`·`reason`을 적는다. 같은 파일에 `criteria_sha256`·`selection_sha256`·`gold_sha256`·`actual_sha256`·`alignment_sha256`·`prediction_sha256`·`scoring_tool_sha256`·`scoring_input_sha256`(receipt + criteria sha + 도구 sha의 canonical sha, [HP-06](work/groups/HP/features/HP-06-gold-acceptance/spec.md) 정의)·`metrics`·`adjudication_file_sha256`(비일치·중대 오류 검토 파일)를 채운다. 도구는 이 파일을 쓰지 않는다. 파일 sha256을 검증 기록에 적는다.

**되돌리기·한계.** export는 쓰기가 없어 되돌릴 것이 없다. 홀드아웃·gold·alignment를 잘못 만들면 새 평가 디렉터리와 새 버전으로 다시 한다(옛 것은 남긴다). 홀드아웃 행은 제품 REST·CLI로만 바꾸고 SQL로 고치지 않는다. 표본 10건·한 회사·참조 실행이므로 통과해도 운영 품질 보증이 아니다.
