# 호스트·Compose와 일상 실행

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

## 환경 하나로 선택

모든 Make target과 수집·판정·브리핑 스크립트는 `scripts/compose.sh`를 사용한다.
`BIDOPS_ENV=dev|prod|mock`만 선택하며 `-f`, `--env-file`, `--profile`을 직접 조합하지 않는다.

| 선택 | 프로젝트 / 기본 웹 포트 | 설정 |
|---|---|---|
| `dev` (기본) | `bidops-dev` / `127.0.0.1:18789` | `env/dev.env`; 외부 모델·첨부 egress 없음 |
| `mock` | `bidops-mock` / `127.0.0.1:18790` | `env/mock.env`; 결정적 mock provider와 참조 표식 |
| `prod` | 기존 `bidops` / `127.0.0.1:18788` | `.env`, `env/model.env`, `env/prespec-attachment.env`, `env/c2.env` |

개발·mock은 운영 `.env`를 자동으로 읽지 않는다. `bidops`·기존 `bidops-local` 프로젝트명을
개발에 주면 실행 전에 거부한다. 별도 검증 프로젝트는 `COMPOSE_PROJECT_NAME=bidops-verify`로
지정할 수 있다. prod는 기존 `bidops` 이름·volume·명시된 이미지 태그를 그대로 사용한다.
`BIDOPS_WEB_PORT` 등 명시적 배포 값이 기본값보다 우선한다.

Compose 파일은 11개에서 6개로 줄였다. 기반은 내부망·저장소·서비스와 최소 권한,
`edge`는 공통 이미지·플랫폼·웹 publish, `prod`는 기존 Mac/model/C-2/G2B 설정을 합친다.
`mock-reference`, `luna`, `slack-egress`는 실제로 구분되는 참조·외부 전송 경계를 유지한다.
Luna 비교 화면과 hp-local의 중복 이미지 overlay는 제거했다.

선택 환경의 기본 env 파일에 `BIDOPS_COMPOSE_FEATURES=luna,slack`을 기록하면 모든 명령이
같은 능력을 읽는다(일회성 shell 값이 우선). 필요한 능력만 명시적으로 더한다. Luna는 전용
`BIDOPS_CODEX_AUTH_FILE`, Slack은 `env/slack.env`가 필요하며 worker는 이름으로 직접 시작한다.
mock에서는 외부 전송 능력을 선택할 수 없다. 기능을 붙였다고 모델 호출·Slack 전송이 승인되지는 않는다.
모델 egress는 web·analysis-worker, G2B egress는 prespec-attachment-worker에만 연결된다.
문서 worker는 계속 network 없음·자격증명 없음·scratch volume 하나다. edge가 붙은 web에는
outbound 경로도 생기므로 dev를 완전한 내부망 격리라고 부르지 않는다.

```bash
make env                       # env/dev.env에 별도 임의 자격 생성; 기존 파일 보존
make build                     # 웹·문서·초기화 이미지 빌드
make init                      # DB 역할 → migration → MinIO 초기화, 명시적 실행
make create                    # 웹과 로컬 큐 worker 생성; migration 없음
make health
make config BIDOPS_ENV=prod     # 렌더 검증만; 비밀값 출력 없음
make test-config               # Compose/스크립트 관련 검사만
make test-engine               # 엔진/API 관련 검사만; PG 없으면 해당 변형 skip
```

검사 Python은 `.venv/bin/python`(있을 때), 아니면 `python3`이며 `PYTHON=...`으로 바꾼다.
`make test-engine BIDOPS_TEST_POSTGRES_URL=<폐기 가능한 PostgreSQL 관리 URL>`은 기존 테스트
harness로 임시 DB를 만들어 PostgreSQL 변형까지 검사한다. 운영 DB URL을 넘기지 않는다.

`make env BIDOPS_ENV=mock`부터 같은 순서로 mock을 설치한다. 운영 초기화·migration·재배포는
백업과 단계별 사람 확인 후에만 실행한다. `make up`은 기존 컨테이너 시작일 뿐 최초 설치가 아니다.
`scripts/transfer.py restore`의 별도 복구 bundle `compose.json`은 보관된 실행 상태를 복원하는
경로라 이 selector로 바꾸지 않는다. 현재 소스 설정을 과거 복구에 섞지 않기 위한 예외다.

### Mac 운영 호스트 (2026-10-14~)

WSL2 운영 호스트는 2026-10-14 종료했고 운영은 Mac(42-ax)으로 옮겼다
([ADR-0072](../tracking/decisions/0072-c2-mac-litellm-ollama.md)). WSL2의 DB·MinIO·승인 프롬프트
v3·사설 vLLM은 넘어오지 않았으므로 아래 v4 절차의 값(`5fa804ff…`, `eth1`, `192.168.0.139`)은
Mac에서 쓰지 않는다. Mac의 C-2는 v5(LiteLLM `local-agent-main` → 로컬 Ollama
`qwen3.8:27b-ctx32k`, digest `41a558fc…`)다.

```bash
scripts/mac-compose.sh config --quiet    # 호환 진입점: BIDOPS_ENV=prod scripts/compose.sh
scripts/mac-compose.sh up -d --no-build  # BIDOPS_IMAGE(amd64) + BIDOPS_DOCUMENT_IMAGE(arm64), 미리 빌드
scripts/c2-mac-model-preflight.sh        # 별칭 경로·Ollama digest·컨테이너 TLS 도달 (completion 없음)
```

- 조합 정본은 `BIDOPS_ENV=prod scripts/compose.sh`다. `scripts/mac-compose.sh`는 이 selector에
  prod를 넘기는 호환 진입점이다. env 4개는 그대로 읽으며 프로젝트 `bidops`와 기존 volume을 보존한다.
- 앱은 linux/amd64, 문서 worker는 linux/arm64다. MinIO digest와 `bidops:minio-init` 기본값도 유지한다.
  운영은 `BIDOPS_IMAGE`·`BIDOPS_DOCUMENT_IMAGE`를 명시해야 하고 자동 태그 교체는 없다.
- 새 체크아웃은 `docker/Document.Dockerfile`로 native 문서 worker를 빌드한다. rhwp v0.8.6 commit
  `cac9b4f7cc743535cd7c00fe4f286abd67e7145b`를 정확히 받아 `cargo --locked`로 빌드하며,
  Python은 amd64/arm64 wheel hash가 있는 `requirements-document.lock`을 검증한다.
  `.sdlc`의 로컬 빌드 context·사전 제작 이미지에 의존하지 않는다. native 바이너리로 바뀐
  SHA256SUMS 한 행 외 모든 vendor hash는 그대로 검증한다. 앱 코드를 바꾸면 문서 이미지도 빌드한다.
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
  같은 Mac의 데모 스택 `bidops-local`(`:18787`/`:8187`)은 2026-11-18 종료했다(volume 보존,
  옛 `.env`는 `backups/env-demo-local-20261118`). 운영은 Mac에서만 한다.
- 모델 설정은 공유 `BIDOPS_VLLM_*` 네 값과 overview 절(`env/model.env`)이다. C-2 adapter와
  개요가 같은 LiteLLM을 쓰고 심층·C-1은 이 배포에서 꺼져 있다. `BIDOPS_VLLM_MODEL_REVISION`은 Ollama
  `/api/tags`의 digest이고 preflight가 binding·generation config와 대조한다.
- 승인 입력 본문(프롬프트 v5·회사 역량 v1)은 gitignore다. `env/c2.env`의 host 경로가
  `/Users/temp/orca/bidops/experiments/order-plan-screening/review-inputs/`를 가리키며, 이
  디렉터리를 백업 대상에 넣는다. 본문을 잃으면 같은 digest로 실행할 수 없다(v3이 그렇게
  사라졌다).
- 첫 `scripts/compose.sh cp`가 빈 `pipeline-data` volume에 `/app/data/runs`를 만들면 host uid(502)
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
  30 7 * * * cd /Users/temp/orca/bidops && BIDOPS_ENV=prod PATH=/opt/homebrew/opt/coreutils/libexec/gnubin:/Applications/OrbStack.app/Contents/MacOS/xbin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin BIDOPS_ENV=prod BIDOPS_WORKFLOW_WEB_URL=http://127.0.0.1:18788 BIDOPS_DAILY_GAP_FLOOR_DATE=<YYYY-MM-DD> BIDOPS_C2_DAILY_ACTOR=jechoi flock -n /Users/temp/.local/state/bidops/plans.lock timeout 6h ./scripts/run-daily-lifecycle.sh --track order-plans >> /Users/temp/.local/state/bidops/logs/plans-$(date +\%Y\%m).log 2>&1
  ```

  `BIDOPS_DAILY_GAP_FLOOR_DATE`는 cron을 걸기 전 공백 중 따라잡지 않기로 한 기간의 다음 날이다.
  그 뒤로 빠진 날은 `gap_detected`, 판정 없이 끝난 발주계획 날은 `unjudged_detected`와 exit 10으로 드러난다([daily](daily.md) "누락일 감지").

  운영 checkout은 2026-11-18부터 main checkout `/Users/temp/orca/bidops`다. env 파일 4개와
  `data/runs`·`backups`를 옛 `bidops-c2mac`에서 옮겼다
  ([기록](../validation-runs/20261118-ops-main-move/README.md)).
- 앱 이미지는 `BIDOPS_ENV=prod scripts/compose.sh build web`으로 빌드한다. `make build`는
  bootstrap 대상을 arm64로 빌드해 lock hash 검사에서 실패한다(findings). postgres-init·migrate는
  web과 같은 `BIDOPS_IMAGE`를 쓴다. 문서 worker는 `build document-worker`다.
- postgres·minio·clamav·document-worker는 운영 컨테이너의 restart 정책이 `no`다. Mac·OrbStack 재시작 뒤에는
  `up -d --no-deps --no-build --scale document-worker=2 postgres minio clamav web document-worker`로
  다시 올리고, C-2를 돌릴 때는 analysis-worker도 사람 확인 후 올린다. 2026-11-18 코드 수정으로
  `docker/docker-compose.prod.yml`이 이 네 서비스에 `restart: unless-stopped`를 준다(dev·mock은 그대로,
  analysis-worker·init·migrate는 정책 없음). 컨테이너를 다시 만들어야 반영되므로 재배포 전까지는 위 수동
  기동이 그대로 필요하고, 반영 뒤에도 host 재시작 다음에는 `scripts/compose.sh ps`로 상태 서비스가
  올라왔는지 사람이 확인한다.
- `alembic check`를 운영 형태의 postgres(server `search_path=bidops,public`)에 돌리면 모든 테이블이
  없는 것으로 보고된다. `PGOPTIONS='-c search_path=public'`을 주고 실행한다.

### 이전 조합의 처리

종료된 overlay의 이름은 과거 배포 기록과 Git 이력에 남는다. 2026-11-18 배포로 운영 컨테이너는
main checkout의 base+edge+prod 조합으로 다시 만들어졌다. 활성 BidOps cron은 없다.

## 현재 배포 차단 조건

**알려진 운영 배포 차단 조건은 2026-09-01에 전부 해소했다.** MinIO versioning은 bootstrap에서
fail-closed로 검증하고, PostgreSQL·MinIO는 internal network에만 있어 host에 publish되지
않는다. 관리 접근은 `scripts/compose.sh exec`로만 한다.

아직 남은 것은 차단 조건이 아니라 운영 훈련이다. 실제 secret, MinIO allow/deny,
egress firewall, backup·restore를 **운영 환경에서** 한 번도 검증하지 않았다.

hosted 외부 모델 reference overlay는 제거됐고 개발 검증에서도 사용하지 않는다. 회사자료 host 입력을 registry에 push·export하지 않으며 로컬 build cache의 접근 범위를 제한한다. legacy notice attachment upload는 quarantine·ClamAV·MinIO 경계를 통과한 파일만 사용한다. 나머지 stack 기동은 폐기 가능한 데이터와 host firewall로 격리한 환경에서만 수행한다.

## 설치된 서버의 일상 실행

```bash
make up                         # 기존 서비스 시작; 새 이미지·초기화·migration 없음
make status
make health
make logs
make restart                    # 웹만 재시작
make stop                       # 웹만 중지
make down                       # 선택 프로젝트 중지; 컨테이너와 volume 보존
make migrate                    # 명시적 migration만 실행
make status BIDOPS_ENV=prod      # 운영 조회도 같은 selector
```

`make start`는 `make up`과 같다. dev/mock은 analysis-worker도 시작해 로컬 큐를 소비하고,
prod는 웹·DB·MinIO·ClamAV·문서 worker만 시작한다. 운영의 분석·첨부·Slack worker는
명시적으로 관리한다. 기존 컨테이너가 없으면 최초 설치 안내와 함께 종료한다.
PostgreSQL health, MinIO running(Chainguard에는 healthcheck 없음), worker running을
확인한 뒤 웹을 시작하고 API·화면 응답을 확인한다. `WAIT_TIMEOUT=120`, `LOG_TAIL=200`을
지정할 수 있다. 이는 MinIO 객체 입출력까지 검증하는 검사가 아니다.

새 이미지를 반영할 때는 승인 후 `BIDOPS_ENV=prod scripts/compose.sh up -d --no-deps
--no-build --force-recreate <services>`로 정확한 서비스만 재생성한다. 앱 시작·runtime 의존성은
bootstrap 서비스에 연결하지 않는다. `make init`와 `make migrate`는 별도 명령이다.
웹 publish와 플랫폼 설정은 언제나 selector에 포함돼 부분 overlay 재생성으로 사라지지 않는다.

### 다른 기기에서 화면 열기

`BIDOPS_WEB_BIND_HOST`를 넓히는 대신 loopback을 소비하는 tailnet proxy를 쓴다. LAN에는
열리지 않고 tailnet 노드에서만 보인다.

```bash
tailscale serve --bg --tcp=8188 tcp://127.0.0.1:18788   # 켜기
tailscale serve --tcp=8188 off                          # 끄기
tailscale serve status
```

**`--http=`가 아니라 `--tcp=`를 쓴다.** HTTP 모드는 요청의 Host 헤더를 등록된
MagicDNS 이름과 대조하므로, 다른 노드가 **tailnet IP로** 붙으면 어느 핸들러에도
걸리지 않아 tailscaled가 `404 page not found`를 돌려준다(2026-09-12 실측).
TCP 포워딩은 Host를 보지 않으므로 IP·MagicDNS 이름·IPv6 세 경로가 모두 동작한다.

확인은 **다른 노드에서** 한다. 같은 호스트에서 자기 tailnet IP로 붙는 것은 hairpin이라
정상 구성에서도 연결이 안 된다 — 이것을 장애 근거로 읽지 않는다. 호스트에서는
`curl http://127.0.0.1:18788/api/health`까지만 확인할 수 있다.

이 설정은 tailscaled가 보관하므로 재부팅 후에도 남는다. Funnel(공개 인터넷 노출)은 켜지
않는다. WSL2 mirrored 네트워킹에서는 Hyper-V 방화벽 기본 inbound가 Block이라 컨테이너
포트를 tailnet 주소에 직접 bind해도 다른 노드에서 닿지 않는다. 이 proxy 경로가 그 제약을
받지 않는 이유는 tailscaled가 연결을 받아 host loopback으로 넘기기 때문이다.

## 상태 확인과 중지

```bash
BIDOPS_ENV=prod scripts/compose.sh ps
curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18788}/api/health"
BIDOPS_ENV=prod scripts/compose.sh logs --since=30m web analysis-worker
BIDOPS_ENV=prod scripts/compose.sh stop web analysis-worker document-worker
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
따로 적용하며 서로 조율하지 않는다. `docker/docker-compose.yml`은 두 값을
`${BIDOPS_GPU_BUSY_LIMIT_SECONDS:-0}`·`${BIDOPS_GPU_REST_SECONDS:-0}` 형태로 전달하므로 값을
주지 않으면 기존 동작과 같다.

## 장애 대응

- 첨부 경로 이탈, 비밀·회사자료 노출, 승인 없는 외부 모델 전송, 기존 회차·리뷰 덮어쓰기, 원문과 다른 근거의 검증 통과가 발견되면 관련 worker와 egress를 즉시 중지하고 상태를 보존한다.
- 중단된 판정은 자동 resume하지 않는다. heartbeat와 마지막 stage를 확인하고 새 실행 ID로 사람이 재시작한다.
- 부분 산출물은 성공 subset과 failure artifact를 함께 보존한다. 유효 결과가 없으면 성공 run을 발행하지 않는다.
- 모델 endpoint 장애가 로컬 판정에서 hosted OpenAI 자동 fallback을 일으키면 안 된다. 외부 재분석은 별도 승인 실행으로만 만든다.
- `document-worker`가 `PermissionError: '/scratch/inbox'`로 즉시 종료하면 image가 `/scratch`를 만들기 전에 생성된 `document-scratch` volume이 root 소유로 남은 것이다. 스택을 중지하고 그 volume만 삭제한 뒤 다시 올린다. 이 volume은 변환 중인 handoff만 담으므로 보존 대상이 아니다.
