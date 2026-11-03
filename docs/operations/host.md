# 호스트·Compose와 일상 실행

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

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
([ADR-0072](../tracking/decisions/0072-c2-mac-litellm-ollama.md)). WSL2의 DB·MinIO·승인 프롬프트
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
- 사전규격의 승인된 2026-10-15 실행 범위는 **개요 검토까지만**이었다. 실행 후 플래그를 끄고 10월 19일 배포에서도 유지했다. 당시 `env/model.env`의 overview 절이
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

## 장애 대응

- 첨부 경로 이탈, 비밀·회사자료 노출, 승인 없는 외부 모델 전송, 기존 회차·리뷰 덮어쓰기, 원문과 다른 근거의 검증 통과가 발견되면 관련 worker와 egress를 즉시 중지하고 상태를 보존한다.
- 중단된 판정은 자동 resume하지 않는다. heartbeat와 마지막 stage를 확인하고 새 실행 ID로 사람이 재시작한다.
- 부분 산출물은 성공 subset과 failure artifact를 함께 보존한다. 유효 결과가 없으면 성공 run을 발행하지 않는다.
- 모델 endpoint 장애가 로컬 판정에서 hosted OpenAI 자동 fallback을 일으키면 안 된다. 외부 재분석은 별도 승인 실행으로만 만든다.
- `document-worker`가 `PermissionError: '/scratch/inbox'`로 즉시 종료하면 image가 `/scratch`를 만들기 전에 생성된 `document-scratch` volume이 root 소유로 남은 것이다. 스택을 중지하고 그 volume만 삭제한 뒤 다시 올린다. 이 volume은 변환 중인 handoff만 담으므로 보존 대상이 아니다.
