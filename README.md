# BidOps

BidOps는 기획·사업개발 담당자가 나라장터 **발주계획을 조기에 탐색**하고, **사전규격 제안요청서를 검토**한 뒤 **입찰공고까지 추적**하도록 돕는 사내 의사결정 지원 시스템이다.

시스템은 후보를 수집·정리·비교하고 근거를 원문 위치와 함께 제시한다. **자동 입찰, 발주처 연락, 추적 승인, 최종 Go/No-Go는 사람이 결정한다.**

- 관측 규모: 발주계획 3일 약 1,200건, 1주 약 2,000건
- 구성: Python 수집·선별·보고 파이프라인 + FastAPI 백엔드 + React 관리 화면
- 저장 정본: PostgreSQL 17(`bidops` schema)과 versioning이 켜진 MinIO

## 목차

- [지금 무엇이 되고 무엇이 안 되는가](#지금-무엇이-되고-무엇이-안-되는가)
- [사전 조건](#사전-조건)
- [실행 1: Docker Compose 스택](#실행-1-docker-compose-스택)
- [실행 2: 호스트 개발 서버](#실행-2-호스트-개발-서버)
- [파이프라인 실행](#파이프라인-실행)
  - [수동 워크플로우 wrapper](#수동-워크플로우-wrapper)
- [산출물 적재](#산출물-적재)
- [화면 사용법](#화면-사용법)
- [테스트](#테스트)
- [백업과 복구](#백업과-복구)
- [저장소 지도](#저장소-지도)
- [문서 진입점](#문서-진입점)
- [문제 해결](#문제-해결)

## 지금 무엇이 되고 무엇이 안 되는가

새로 합류했다면 이 절을 먼저 읽는다. 설계된 스키마나 화면이 존재한다는 사실이 운영 완료를 뜻하지 않는다. 항목별 최신 상태는 [docs/tracking/status.md](docs/tracking/status.md)가 정본이다.

동작하는 것

- 나라장터 공고 수집·정규화·검증 표본 선정, 결정적 HTML 보고서 렌더링
- 다섯 관점·반론·종합 구조의 1차 판정과 사람 리뷰 기록
- FastAPI 회차·공고·리뷰·프로필·지표 API, React 관리 화면
- 첨부 quarantine → ClamAV 검사 → 문서 구조화 → 3단계 심층 검토
- PostgreSQL 17 + Alembic, MinIO versioning, 백업·복구 스크립트

의도적으로 꺼져 있거나 아직 없는 것

- **로그인·역할 기반 권한·SSO가 없다.** 사내망 접근 제한이 경계이고, 담당자 이름은 인증이 아니라 감사 표식이다.
- **스케줄러와 always-on은 기본 비활성**이다. 앱 startup은 migration·seed·정책 활성화·모델 호출을 하지 않는다.
- **사전규격 첨부 다운로드는 기본 false**다. 승인 host allowlist가 없으면 fail closed 한다.
- 발주계획 C-2 선별은 수집·적재·BM25·Qwen·화면까지 종단으로 동작한다(2026-09-03 확인). 다만 **운영 활성화는 아니다** — activation blocker 4건이 남아 있고 policy는 승인되지 않았다. validator는 정상일 때도 `valid_but_blocked`를 반환한다.
- 입찰 delta는 저장·REST·화면은 있으나 비교를 계산하는 worker가 없어 운영 활성화 상태가 아니다.
- 알림, 준비·실패 재시작 화면은 미구현이다.

## 사전 조건

| 대상 | 요구사항 |
|---|---|
| Compose 실행 | Docker Engine, Docker Compose |
| 호스트 개발·검증 | Python 3.12+, Node.js 22+, npm 10+ |
| 화면 스냅샷 테스트 | Playwright 브라우저 번들이 미리 설치되어 있어야 한다 |

환경 파일은 다음 규칙을 따른다. 실제 비밀은 외부 secret manager에서 주입하고 `.env`는 커밋하지 않는다.

```bash
cp .env.example .env
# BIDOPS_UID / BIDOPS_GID를 `id -u` / `id -g` 값과 맞춘다 (0이 아닌 계정)
# DB 5개 역할과 MinIO namespace별 자격증명은 서로 다른 값으로 채운다
```

`.env`는 모든 compose 파일이 공유하는 공통 파일이다. **overlay 전용 값을 `.env`에 두지 않는다.** overlay 값은 `env/<overlay>.env`에 두고 추가 `--env-file`로 넘긴다.

| 파일 | 소비하는 compose | 담는 값 |
|---|---|---|
| `.env` | `docker-compose.yml` | 프로세스 정체성, 로그, DB·MinIO 자격증명, 암호화 키, port, 승인 profile/policy 참조 |
| `env/model.env` | `docker-compose.model-egress.yml`, `docker-compose.c2-order-plan.yml` | 용도별(`screening`·`overview`·`deep_review`) vLLM endpoint·allowlist·API key·선언 revision·모델 id, C-2 입력 파일 host 경로 |
| `env/prespec-attachment.env` | `docker-compose.prespec-attachment.yml` | 사전규격 첨부 취득 host allowlist |
| 없음 | `docker-compose.mock-reference.yml` | 전용 값을 override 파일 안에 리터럴로 선언한다 |

### 회사자료 입력 전제

`web` 서비스는 다음 세 파일을 host checkout에서 read-only bind mount로 주입한다. 이 파일들은 build context와 runtime image에 **없다**. 없는 상태로 기동하면 Docker가 그 자리에 디렉터리를 만들어 프로필 경계와 수집 subprocess가 비정상 실패한다. 기동 전에 확인한다.

```bash
test -f docs/reference/company-profile.md && test -r docs/reference/company-profile.md
test -f docs/reference/company-performance-titles.tsv && test -r docs/reference/company-performance-titles.tsv
test -f web/backend/app/screening/baseline_company_profile.md && test -r web/backend/app/screening/baseline_company_profile.md
```

이 경로는 의도된 보안 경계다. `docker run`만으로 우회하지 말고 Compose를 사용한다.

## 실행 1: Docker Compose 스택

`docker-compose.yml`이 기준 배포 파일이다. 항상 전용 `COMPOSE_PROJECT_NAME`을 쓰고, 다른 worktree의 컨테이너·volume을 건드리지 않는다.

파일은 **여는 것 하나씩**을 소유한다. overlay를 붙이지 않으면 그 기능과 그 network는 열리지 않는다.

| 파일 | 여는 것 |
|---|---|
| `docker-compose.yml` | 웹·DB·객체 저장소·검사·worker. network는 전부 internal이고 **host에 아무것도 publish하지 않는다** |
| `docker-compose.edge.yml` | 관리 화면을 host loopback에 publish. `web`의 `ports:` 선언을 이 파일이 소유한다 |
| `docker-compose.model-egress.yml` | 승인된 vLLM egress와 `screening`·`overview`·`deep_review` 설정 |
| `docker-compose.c2-order-plan.yml` | C-2 발주계획 판정의 승인 입력 파일 마운트와 실행 토글 |
| `docker-compose.prespec-attachment.yml` | 사전규격 첨부 worker의 G2B egress와 취득 활성화 |
| `docker-compose.mock-reference.yml` | 모델 없이 상태 전이만 확인(egress 없음) |

**기반 파일만으로 띄우면 화면에 접근할 수 없다.** internal network에만 붙은 컨테이너의 `ports:`를 Docker가 조용히 무시하기 때문이다(에러도 내지 않는다). `web`을 재생성할 때 `-f docker-compose.edge.yml`을 빼면 화면이 조용히 죽는다. `make` 명령의 `COMPOSE`에는 이 overlay가 이미 들어 있다.

이미 설치된 서버는 저장소 루트에서 `make up`으로 켠다. `make status`, `make health`,
`make logs`, `make restart`, `make stop`을 제공하며 `make help`로 사용법을 확인할 수 있다.
기존 컨테이너를 사용하는 명령의 범위는 [일상 실행 절차](docs/operations.md#설치된-서버의-일상-실행)를 따른다.
처음 설치하는 환경에서는 아래 절차를 먼저 진행한다.

```bash
cp .env.example .env
cp env/model.env.example env/model.env
export COMPOSE_PROJECT_NAME=bidops

docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d postgres minio clamav

# DB 역할 초기화 → Alembic migration → MinIO 버킷·정책 초기화
./scripts/init-runtime.sh

docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.model-egress.yml \
  up -d web document-worker analysis-worker

curl --fail "http://127.0.0.1:${BIDOPS_WEB_PORT:-18787}/api/health"
```

화면은 `http://127.0.0.1:18787` 이다. `docker-compose.edge.yml`이 그 publish를 소유하며 기본값은 loopback이다.

PostgreSQL과 MinIO는 host에 publish되지 않는다. 관리 접근은 exec으로 한다.

```bash
docker compose -f docker-compose.yml exec postgres psql -U owner -d bidops
docker compose -f docker-compose.yml exec minio mc ls local/bidops-source
```

다른 기기에서 화면을 볼 때는 `BIDOPS_WEB_BIND_HOST`를 넓히는 대신 loopback을 소비하는 tailnet proxy를 쓴다. **`--http=`가 아니라 `--tcp=`이다** — HTTP 모드는 Host 헤더를 대조해서 tailnet IP로 붙으면 `404 page not found`가 나온다. 자세한 설명은 [다른 기기에서 화면 열기](docs/operations.md#다른-기기에서-화면-열기)에 있다.

```bash
tailscale serve --bg --tcp=18787 tcp://127.0.0.1:18787
```

몇 가지 주의점

- `--env-file`을 명시하면 `.env` 자동 로드가 꺼지므로 공통 파일과 overlay 파일을 **함께** 넘긴다. overlay 없이 기동할 때는 `--env-file` 없이 `.env`가 자동 로드된다.
- 앱 startup은 migration·`create_all`·seed를 하지 않는다. `init-runtime.sh`가 먼저 끝나야 한다.
- 사설 vLLM 없이 웹과 문서 준비만 확인해도 된다. 이때 분석 worker가 모델 단계에서 실패하는 것은 **정상**이며 성공으로 보정하지 않는다.
- 일상 운영에서 `docker compose down -v`나 volume 삭제를 쓰지 않는다.

### 목적별 overlay

판정 파이프라인이 승인된 모델 endpoint·나라장터 OpenAPI에 접근해야 할 때만 egress를 연다.

```bash
cp env/model.env.example env/model.env   # BIDOPS_VLLM_SCREENING_* 를 채운다
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml -f docker-compose.model-egress.yml up -d web
```

C-2 발주계획 판정은 전송(model-egress)과 입력(c2-order-plan)을 **둘 다** 붙인다. 회사 역량 파일과 프롬프트는 저장소가 제공하지 않는 승인 자료라 host 경로를 `env/model.env`에 명시해야 하며, 비우면 overlay가 기동 전에 fail closed한다.

```bash
docker compose --env-file .env --env-file env/model.env \
  -f docker-compose.yml -f docker-compose.edge.yml \
  -f docker-compose.model-egress.yml -f docker-compose.c2-order-plan.yml \
  up -d web analysis-worker
```

사전규격 첨부 취득(기본 비활성, `SW사업대상=Y` 또는 추적 중 발주계획 연결 건만 대상):

```bash
cp env/prespec-attachment.env.example env/prespec-attachment.env
# BIDOPS_G2B_ATTACHMENT_ALLOWED_HOSTS를 승인된 값으로 채운다
docker compose --env-file .env --env-file env/prespec-attachment.env \
  -f docker-compose.yml -f docker-compose.prespec-attachment.yml \
  up -d prespec-attachment-worker
```

`prespec-attachment-worker`는 기반 파일이 `prespec` profile로 소유한다. 서비스 이름을 명시해야 뜨므로 `up -d`만으로는 시작되지 않고, overlay 없이 띄우면 취득이 꾸진 채 idle한다.

모델 없이 상태 전이와 저장·검증 계보만 확인할 때는 mock override를 쓴다. 추가 env 파일이 필요 없고 어떤 egress도 열지 않는다.

```bash
docker compose -f docker-compose.yml -f docker-compose.mock-reference.yml \
  up -d web document-worker analysis-worker
```

mock 결과의 계보는 `mock-analysis` / `bidops-deterministic-mock-v1`로 고정되고 `deployable=false`다. **사업 판단이나 모델 품질 평가 근거로 쓰지 않는다.** 1차 분류가 mock인지 여부는 `ScreeningAttempt.model_digest`로 판별한다(`model_name`으로는 구별할 수 없다).

**overlay를 붙였다는 사실만으로 egress가 안전해지지 않는다.** host firewall의 목적지 제한과 실제 endpoint 승인을 함께 확인한다.

### 상태 확인과 중지

```bash
export COMPOSE_PROJECT_NAME=bidops
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs --since=30m web analysis-worker
docker compose -f docker-compose.yml stop web analysis-worker document-worker
```

로그에는 prompt, 모델 응답, 회사자료, 첨부 본문, 자격증명, URL 쿼리 문자열이 **없어야 한다.**

## 실행 2: 호스트 개발 서버

화면 코드를 고치면서 확인할 때 쓴다. 백엔드는 승인된 PostgreSQL 17을 가리켜야 하며 SQLite URL로 실행하지 않는다. 프론트엔드 dev 서버가 `/api` 요청을 8787 백엔드로 프록시한다.

```bash
# 터미널 1 — 백엔드
cd web/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8787

# 터미널 2 — 프론트엔드
cd web/frontend
npm ci
npm run dev        # http://localhost:5173
```

프론트엔드 스크립트는 `dev`, `dev:mock`, `build`, `preview`, `test:contrast`, `test:screens`, `test:design`, `test:pixel`, `test:pixel:update` 다. UI를 만들 때는 Astryx 디자인 시스템 CLI(`npx @astryxdesign/cli`)로 컴포넌트를 먼저 확인한다. 자세한 규칙은 [CLAUDE.md](CLAUDE.md)와 [web/frontend/AGENTS.md](web/frontend/AGENTS.md)에 있다.

## 파이프라인 실행

수집기는 명시적으로 실행한다. 스케줄러와 always-on은 기본 비활성이고, 운영자가 회차 디렉터리와 API key 주입을 확인한 뒤 실행한다.

### 수동 워크플로우 wrapper

발주계획과 사전규격은 서로 독립된 단계형 shell script로 실행할 수 있다. 두 스크립트 모두
기존 회차를 덮어쓰지 않고, live 모델 호출이 가능한 명령에는 그 실행 한 번에만 유효한
`--approve-model-call`을 요구한다. 실제 비밀·endpoint는 출력하거나 실행 응답 파일에 저장하지
않는다.

```bash
scripts/run-order-plan-workflow.sh --help
scripts/run-prespec-workflow.sh --help
```

#### 발주계획 wrapper

`scripts/run-order-plan-workflow.sh`의 범위는 **발주계획 수집부터 C-2 실행 요청과 결과 게시
대기까지**다.

```text
Phase 0 read-only 검증
→ 발주계획 수집
→ PostgreSQL 적재
→ web·analysis-worker를 C-2 전용 설정으로 기동
→ BM25 Top 300 + Qwen C-2 실행 enqueue
→ worker가 C-2 결과를 게시
```

| 명령 | 이 명령이 진행하는 마지막 지점 |
|---|---|
| `preflight` | web health와 C-2 Phase 0 binding을 읽기 전용으로 검사한다. `execution_allowed=true`가 아니면 중단한다. |
| `collect` | 새 `data/runs/<run-id>/collected-order-plans.json`과 raw page를 만든다. DB에는 적재하지 않는다. |
| `ingest` | 회차를 web의 영속 pipeline volume에 복사하고 PostgreSQL에 적재한다. C-2는 시작하지 않는다. |
| `start-worker` | web과 공유 analysis worker를 C-2 활성·사전규격 분석 비활성 설정으로 재기동한다. 실행 row는 만들지 않는다. |
| `run` | 지정 회차의 C-2 execution을 `대기`로 생성한다. 호출 뒤 worker가 비동기로 BM25·Qwen·결과 게시를 수행한다. |
| `status` | 지정 회차의 C-2 상태·건수·부분 산출물·안전한 오류 코드만 조회한다. 상태를 바꾸지 않는다. |
| `all` | `preflight → collect → ingest → start-worker → run`을 수행하고 **C-2를 enqueue한 직후 반환**한다. 종결까지 기다리지 않는다. |
| `stop-worker` | 공유 analysis worker를 중지한다. 실행·산출물·DB row는 삭제하지 않는다. |

대표 실행:

```bash
scripts/run-order-plan-workflow.sh all \
  --days 3 \
  --actor '담당자 이름' \
  --approve-model-call

scripts/run-order-plan-workflow.sh status --run-id <run-id>
```

이 wrapper는 사람의 relevance 수정, 추적 시작·보류·종료, 사전규격 연결, 최종 Go/No-Go를
자동으로 기록하지 않는다. C-2의 `relevant|uncertain|not_relevant`도 적합성 등급이나 입찰
결정이 아니다. `성공|부분 성공|실패|중단됨`은 `status` 또는 `/order-plans`에서 사람이
확인한다.

#### 사전규격 wrapper

`scripts/run-prespec-workflow.sh`의 범위는 **사전규격 수집부터 C-1 실행 요청, 그리고 조건을
충족한 건의 첨부·문서 준비·개요·회사 핏 비동기 처리까지**다.

```text
active C-1·profile·policy·모델 설정 검증
→ 사전규격만 수집
→ validation-set 표본 선정·PostgreSQL 적재
→ C-1 web + 첨부·문서·analysis worker 기동
→ C-1 전량 판정 enqueue
→ 우선 검토/SW 조건을 충족한 건의 첨부 취득·문서 준비
→ 개요 run
→ 회사 핏 attempt
```

| 명령 | 이 명령이 진행하는 마지막 지점 |
|---|---|
| `preflight` | web health, active C-1 policy, 세 overlay env, 회사자료 파일을 검사한다. 정책을 만들거나 활성화하지 않는다. |
| `import-inputs` | 불변 심층검토 profile/policy 판을 import하고 UUID를 출력한다. `.env` 수정과 프로세스 재기동은 사람이 한다. C-1 정책을 만드는 명령은 아니다. |
| `collect` | `--skip-bids`로 사전규격만 새 회차에 수집한다. 첨부 바이트를 받거나 DB에 적재하지 않는다. |
| `ingest` | `validation-set.json`을 만들고 **그 표본만** 적재한 뒤 첨부 취득 자격을 재평가한다. 전량 적재는 `--analysis-count`·`--audit-count`를 명시해 표본 범위를 넓혀야 한다. |
| `start-workers` | C-1용 web, document worker, 첨부 worker, 공유 analysis worker를 기동한다. C-2는 비활성으로 강제한다. 기존 queue가 있으면 그것도 같은 worker의 대상이다. |
| `run-c1` | 지정 회차의 C-1 전량 판정을 enqueue한다. 이후 자격을 충족한 건은 worker와 hook이 첨부 → 문서 묶음 → 개요 → 회사 핏을 비동기로 이어 간다. |
| `enqueue` | `--notice-id` 한 건 또는 `--limit` 범위의 eligible 건을 개요 queue에 넣는다. 회사 핏을 직접 생성하지 않으며 실제 모델 호출은 analysis worker가 한다. |
| `status` | run ID가 있으면 C-1을, notice ID가 있으면 개요와 회사 핏을 조회한다. 둘 다 없으면 현재 사전규격 50건의 funnel 상태를 보여 준다. |
| `all` | `preflight → collect → ingest → start-workers → run-c1`을 수행하고 **C-1을 enqueue한 직후 반환**한다. 첨부·개요·회사 핏 완료까지 기다리지 않는다. |
| `stop-workers` | analysis worker와 첨부 worker를 중지한다. document worker와 web, 기존 결과는 유지한다. |

대표 실행:

```bash
scripts/run-prespec-workflow.sh all \
  --from-date 2026-09-10 \
  --to-date 2026-09-12 \
  --actor '담당자 이름' \
  --approve-model-call

scripts/run-prespec-workflow.sh status --run-id <run-id>
scripts/run-prespec-workflow.sh status --notice-id <notice-id>
```

후속 자동 단계는 모든 사전규격에 무조건 실행되지 않는다. 첨부 취득 자격, 안전 검사,
현재 문서, 자동 확정 `ready` 묶음과 최신 `completed` 개요가 필요하다. 회사 핏은 현재 등급이
`우선 검토`이고 `SW사업대상=Y`이며 활성 profile/policy와 참조 실행 설정이 맞는 건만
대상이다. 범위가 모호하거나 변환·검증이 실패하면 `needs_human_review`·`failed`·사유 코드로
멈추며 wrapper가 값을 보정하거나 과거 완료 run으로 우회하지 않는다.

이 wrapper의 회사 핏은 현재 참조 실행 범위다. 결과가 `matched`여도 운영 품질 통과나 추적
승인, 심층 검토 승인, 최종 입찰 Go/No-Go를 뜻하지 않는다. 수동 범위 확정, 사람 검토 대기
해소, 추적 결정과 최종 결정은 담당자가 화면/API에서 별도로 수행한다.

```bash
# 최근 21일 발주계획 수집
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --output-dir data/runs/order-plans-$(date +%Y%m%d) --days 21

# 날짜를 고정한 재현·재조회 모드
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --output-dir data/runs/order-plans-20260808-20260829

# 보존된 raw page를 재정규화 (API를 호출하지 않는다)
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --from-raw data/runs/order-plans-20260808-20260829/raw \
  --output-dir data/runs/order-plans-20260808-20260829-reclassified
```

실행은 **원본을 덮어쓰지 않고 새 회차 디렉터리를 만든다.** 이전 회차의 판정은 그대로 보존된다.

주요 스크립트

| 스킬 | 스크립트 | 하는 일 |
|---|---|---|
| `bidops-collect` | `collect_order_plans.py`, `collect_notices.py` | 수집·정규화 |
| `bidops-collect` | `select_validation_sample.py` | 검증 표본 선정 |
| `bidops-screen` | `rank_order_plans_bm25.py` | 발주계획 BM25 랭킹 |
| `bidops-screen` | `build_screening_results.py`, `build_order_plan_screening_results.py` | 판정 결과 병합 |
| `bidops-screen` | `validate_order_plan_phase0.py` | C-2 Phase 0 read-only 계약 검증 |
| `bidops-report` | `render_report.py` | 결정적 HTML·피드백 렌더링 |

발주계획 C-2를 구현·실행하기 전에는 아래 read-only 검증을 통과해야 한다. 이 명령은 모델 endpoint나 외부 API를 호출하지 않고 prompt·profile 본문도 출력하지 않는다.

```bash
python3 skills/bidops-screen/scripts/validate_order_plan_phase0.py --json
```

정상 결과도 현재는 `status=valid_but_blocked`, `execution_allowed=false`, `activation_allowed=false` 다. 남아 있는 blocker를 사람 승인 없이 제거하거나 policy·binding을 직접 수정하지 않는다.

**나라장터 개발계정은 일일 1,000 HTTP 요청 한도**가 있다. 700회 경고, 900회 신규 요청 중지를 초기 방어선으로 삼고 같은 응답은 회차 cache로 재사용한다.

## 산출물 적재

`data/runs/<회차>/` 아래 파일을 읽어 PostgreSQL 정본에 넣는다. 같은 회차를 두 번 적재해도 행이 중복되지 않는다.

```bash
cd web/backend
.venv/bin/python -m app.lifecycle.ingest.cli --run 20260817-20260823   # 회차 하나
.venv/bin/python -m app.lifecycle.ingest.cli --all                     # 발견된 모든 회차
```

적재 순서는 `validation-set.json` → `screening-results.json` → `collected-notices.json` 이고, 마지막으로 `reports/<회차>/review-feedback.yaml` 에서 값이 채워진 항목만 초기 리뷰로 가져온다.

계약을 어긴 산출물은 거부하지 않고 **경고로 기록**한 뒤 있는 만큼 적재한다. 누락된 값을 임의로 채우지 않으며, 기록된 경고는 실행 상태 화면에 그대로 나타난다.

## 화면 사용법

| 화면 | 경로 | 무엇을 하는가 |
|---|---|---|
| 대시보드 | `/` | 수집·후보·우선 검토·1차 필터 누락 지표와 검증 통과 기준. 미달 항목을 숨기지 않는 것이 핵심 |
| 검토 대기열 | `/queue` | 담당자가 가장 오래 머무는 화면. 공고를 고르면 판정 근거가 펼쳐지고, 하단 바에서 리뷰를 저장하면 다음 건으로 넘어간다 |
| 발주계획 C-2 검토 | `/order-plans` | 발주계획 목록과 판정을 한 화면에서 본다. 사람 피드백 revision 저장 |
| 사전규격 | `/pre-specs` | 개요 검토 결과를 판단 순서로 읽고 `계속 추적·보류·종료`를 기록한다 |
| 사업기회 | `/opportunities` | 누적 identity 기준 사업기회와 추적 상태 |
| 입찰 변경 비교 | `/opportunities/:id/bid-delta` | 사전규격 대비 입찰공고의 중요 변경 |
| 최종 Go/No-Go | `/go-no-go` | 사람의 최종 결정 기록 |
| 심층 검토 보고서 | `/deep-reviews/:id` | 3단계 심층 검토 결과와 근거 |
| 판정 기준 | `/criteria` | 회사 프로필, 검증 지표, 품질 게이트, 정책 |
| 실행 상태 | `/run-status` | 파이프라인 단계 실행·로그·산출물 검증·첨부·감사 |

읽는 방법에서 하나만 기억한다. **`계산 불가`와 `0`은 다르다.** 값이 없어 계산할 수 없는 항목은 게이지를 비우고 사유를 함께 보여 준다. 0으로 채워 나쁜 값처럼 보이게 하지 않는다. `값 없음`·`미확인`도 같은 이유로 명시한다.

화면에서 실행할 수 있는 파이프라인 단계는 `collect`(수집·정규화), `sample`(표본 선정), `report`(HTML 생성) 세 가지다. **판정 단계는 화면에서 실행하지 않는다.** 판정은 `screening-decisions.json`을 직접 작성해야 하는 작업이라 화면에는 대기 상태로만 나타나고, 파일이 갱신되면 적재기가 인식한다.

프로필 화면은 승인된 profile snapshot에 고정된다. snapshot이 하나도 없으면 `/api/profile/*`가 `503 profile_snapshot_unavailable`로 fail closed 하는 것이 **정상**이다. snapshot은 판정 실행이 만들므로 신규 배포에서는 회차 판정을 한 번 실행한 뒤 프로필 화면을 쓴다.

## 테스트

live API key나 model endpoint 없이 실행한다.

```bash
./run-tests.sh                              # 파이프라인 단위·교차 테스트
./web/run-web-tests.sh                      # backend + frontend build + Playwright
cd web/frontend && npm run test:screens     # 화면 게이트 (의미 + 구조)
COMPOSE_PROJECT_NAME=bidops \
  docker compose -f docker-compose.yml build
```

`web/run-web-tests.sh`는 임시 PostgreSQL 17 컨테이너를 띄워 migration을 수행하고, 격리 DB에서 backend 테스트 → frontend production build → Playwright 화면 게이트(의미 한 폭 + 구조 두 폭)를 차례로 돌린다. 임시 자원은 실패 경로를 포함한 모든 종료에서 정리된다.

- Docker가 없으면 `BIDOPS_TEST_POSTGRES_URL`에 **폐기 가능한** PostgreSQL 관리 URL을 준다. 운영 DB URL을 쓰지 않는다.
- Playwright는 브라우저 번들을 자동으로 내려받지 않는다. 없으면 안내 문구와 함께 실패한다.
- live vLLM smoke는 운영자가 명시한 한 번의 명령과 대상에서만 수행한다. safety 환경변수가 true라는 사실만으로 실행하지 않는다.

## 백업과 복구

서버 이전용으로 현재 이미지·DB·MinIO·미커밋 소스를 한 폴더에 보존하고 로컬에서 열려면
[서버 이전용 전체 폴더](docs/operations.md#서버-이전용-전체-폴더)의 `scripts/transfer.py`를 사용한다.
생성 폴더는 평문 운영 설정과 회사자료를 포함하므로 Git에서 제외한다.

```bash
# PostgreSQL: timestamp custom-format dump를 ./backups/postgres에 만든다 (기존 백업을 지우지 않는다)
COMPOSE_PROJECT_NAME=bidops docker compose \
  -f docker-compose.yml --profile backup run --rm ro-backup

# MinIO: 네 버킷의 모든 version을 복사하고 object-versions.tsv manifest를 만든다
# 실행 환경에 mc, MINIO_ALIAS, OBJECT_BACKUP_DIR가 필요하다
./scripts/backup-objects.sh
```

DB dump와 객체 manifest는 같은 복구 지점을 식별할 수 있게 **함께** 보존한다.

복구는 기존 운영 대상 위가 아니라 **빈 PostgreSQL과 빈 MinIO**에서 수행한다. 순서는 객체 복사·백업 hash 확인 → DB restore → active manifest 생성 → target version ID·집합 일대일 검증이다. 전체 절차와 필요한 환경변수는 [docs/operations.md](docs/operations.md#복구)에 있다.

## 저장소 지도

```text
bidops/
├── AGENTS.md, CLAUDE.md              작업 진입점이며 내용은 동일하다
├── docker-compose.yml                PostgreSQL·MinIO 기반 애플리케이션 스택 (내부망 전용)
├── docker-compose.edge.yml           관리 화면 host publish (이 파일만 포트를 연다)
├── docker-compose.model-egress.yml   screening·overview·deep_review 모델 egress
├── docker-compose.c2-order-plan.yml  C-2 발주계획 판정 입력 마운트
├── docker-compose.prespec-attachment.yml  사전규격 첨부 G2B egress
├── docker-compose.mock-reference.yml 모델 없는 참조 실행
├── run-tests.sh                      파이프라인 단위·교차 테스트
├── data/, reports/                   불변 회차 입력과 파생 보고서
├── env/                              overlay 전용 환경 파일
├── scripts/                          init·migrate·worker·backup·restore 스크립트
├── docs/                             아래 문서 진입점 참고
├── skills/
│   ├── bidops-collect/               수집·정규화·표본 선정
│   ├── bidops-screen/                구조화 1차 판정·병합
│   └── bidops-report/                결정적 HTML·피드백 렌더링
└── web/
    ├── backend/                      FastAPI · SQLAlchemy 2.x · Pydantic v2 · Alembic
    │   └── app/                      core · lifecycle · screening · deep_review 네 모듈과 조립 계층
    └── frontend/                     Vite 6 · React 19 · TypeScript · TanStack Query v5
```

백엔드는 한 방향으로만 의존하는 네 모듈과 그것을 조립하는 얇은 계층으로 나뉜다
([ADR-0045](docs/tracking/decisions/0045-backend-module-layout.md)). 폴더 구조·의존 규칙·확장점·
경계 테스트는 [web/backend/AGENTS.md](web/backend/AGENTS.md)에 있다.

`docs/validation-runs`는 시점별 실행 증거이며 현재 코드와 문서 계약을 대체하지 않는다. 완료·미채택 계획, 과거 리뷰·목업, 인수인계 문서는 저장소에 보관하지 않으며 필요하면 git 이력에서 찾는다. 과거의 `R-xx`·`A-xx`·phase·T-번호 체계는 종료됐고 새 작업에 다시 쓰지 않는다.

## 문서 진입점

| 문서 | 무엇이 들어 있는가 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 현재 구조·계약·목표 데이터 흐름 (정본) |
| [docs/business-rules.md](docs/business-rules.md) | 생애주기·선별·심층 검토 상태 규칙 |
| [docs/contracts.md](docs/contracts.md) | REST·파일·DB 소비자 계약 |
| [docs/security.md](docs/security.md) | 접근·민감정보·모델 전송·감사 정책 |
| [docs/operations.md](docs/operations.md) | 설치·실행·백업·복구 절차 |
| [docs/standards.md](docs/standards.md) | 구현·검증 강제 기준 |
| [docs/engineering-notes.md](docs/engineering-notes.md) | 증상별 재발 방지 지식 |
| [docs/database-guide.md](docs/database-guide.md) | DB 전체 해설과 설계 근거 |
| [docs/PRD.md](docs/PRD.md), [docs/PLAN.md](docs/PLAN.md) | 현재 착수 범위(발주계획 C-2 선별)의 요구와 순서 |
| [docs/ADR.md](docs/ADR.md), [docs/tracking/decisions/](docs/tracking/decisions/) | 기술·운영 결정과 대안·결과 |
| [docs/design/](docs/design/) | 화면 시안 기준 작업의 정본 — PRD·PLAN·ADR-0039~0041·0046~0048, 무드보드와 목업 |
| [docs/scheduling.md](docs/scheduling.md), [docs/model-quality-gate.md](docs/model-quality-gate.md), [docs/agent/agent-runtime.md](docs/agent/agent-runtime.md) | 공고 판정 런타임의 스케줄·품질 게이트·worker 계약 |
| [docs/tracking/status.md](docs/tracking/status.md) | 구현과 검증의 현재 상태 |
| [docs/tracking/findings.md](docs/tracking/findings.md) | 재현 가능한 미해결 문제 |

코드를 바꾸기 전에는 `docs/standards.md`, `docs/engineering-notes.md`, 변경 경로에서 가장 가까운 `AGENTS.md`를 읽는다.

## 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| 회차 선택기가 비어 있다 | 적재가 안 됐다. `python -m app.lifecycle.ingest.cli --all`을 실행한다 |
| `빌드된 프론트엔드가 없습니다` 503 | `cd web/frontend && npm run build`. 빌드 산출물이 없어도 백엔드 기동 자체는 실패하지 않는다 |
| `/api/profile/*`가 503 `profile_snapshot_unavailable` | 승인된 profile snapshot이 없다. 회차 판정을 한 번 실행한다. fail closed가 정상 동작이다 |
| Docker가 만든 파일을 지울 수 없다 | 컨테이너 사용자 번호가 host와 다르다. `id -u`·`id -g`를 `.env`의 `BIDOPS_UID`·`BIDOPS_GID`에 넣고 다시 띄운다 |
| `document-worker`가 `PermissionError: '/scratch/inbox'`로 즉시 종료 | image가 `/scratch`를 만들기 전에 생성된 `document-scratch` volume이 root 소유다. 스택을 멈추고 **그 volume만** 지운 뒤 다시 올린다. 보존 대상이 아니다 |
| 8787 포트 충돌 | `--port`로 바꾸고 `web/frontend/vite.config.ts`의 프록시 대상도 함께 바꾼다 |
| 컨테이너는 healthy인데 화면 포트가 안 열린다 | `-f docker-compose.edge.yml`을 빠뜨린 채 `web`을 재생성했다. 기반 파일의 network는 전부 internal이라 Docker가 `ports:`를 조용히 무시한다. edge overlay를 붙여 다시 `up -d web` |
| tailnet IP로 붙으면 `404 page not found` | `tailscale serve`가 HTTP 모드다. HTTP 모드는 Host 헤더를 MagicDNS 이름과 대조하므로 IP 접속이 걸리지 않는다. `tailscale serve --http=<port> off` 뒤 `tailscale serve --bg --tcp=<port> tcp://127.0.0.1:<port>` |
| `up -d`를 했는데 `prespec-attachment-worker`가 없다 | 기반 파일이 그 worker를 `prespec` profile로 소유한다. 서비스 이름을 명시해야 뜬다 |
| web이 `Database migration required: current X, expected Y`로 종료 | 정상 fail-closed다. 앱 startup은 migration을 하지 않는다. 이미지를 다시 빌드하고 `run --rm migrate`를 먼저 끝낸다 |
| `all predefined address pools have been fully subnetted` | Docker 주소 풀이 찼다. 프로젝트 하나가 최대 7개 network를 쓰므로 동시 2개가 한계다. 쓰지 않는 Compose 프로젝트를 내리거나 `/etc/docker/daemon.json`의 `default-address-pools`를 넓힌다 |
| `ensurepip is not available` | `sudo apt install python3.12-venv` 또는 Docker 실행을 쓴다 |
| 대시보드 수집 건수가 값 없음 | 해당 회차에 `collected-notices.json`이 없다. 원문 페이지는 용량 때문에 저장소에서 제외되므로 새 클론에서는 정상이다 |
| 첨부 업로드가 거부된다 | HWP·HWPX·PDF만 허용하고 상한은 50MB다. 거부 사유는 화면에 그대로 표시된다 |
| 나라장터 첨부가 삭제되지 않는다 | 의도된 동작이다. 직접 등록한 파일(`manual`)만 삭제할 수 있다 |

### 즉시 보고해야 하는 상황

다음을 발견하면 **관련 worker와 egress를 즉시 중지하고 상태를 보존한 뒤 보고한다.**

- 첨부 원문의 허용 경로 이탈
- API 키·회사자료가 로그나 응답에 노출
- 승인 없는 외부 모델 전송
- 회차 원본 또는 기존 리뷰 덮어쓰기
- 원문과 다른 모델 근거가 검증을 통과

중단된 판정은 자동 resume하지 않는다. heartbeat와 마지막 stage를 확인하고 새 실행 ID로 사람이 재시작한다. 모델 endpoint 장애가 hosted OpenAI 자동 fallback을 일으켜서는 안 된다.

현재 범위에서 해결할 수 없는 구조 문제는 재현 조건, 영향, 지금 해결할 수 없는 이유, 후속 방향을 [docs/tracking/findings.md](docs/tracking/findings.md)에 기록한다.
