# 설치·설정·모듈

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

## 사전 조건

- Docker Engine과 Docker Compose가 필요하다. host 검증에는 Python 3.12+, Node 22+, npm 10+가 필요하다.
- `.env.example`을 `.env`로 복사하고 실제 비밀은 외부 secret manager에서 주입한다. `.env`는 커밋하지 않는다.
- `.env`는 모든 compose 파일이 공유하는 공통 파일이다. overlay 전용 값은 `env/<overlay>.env`에 두고 추가 `--env-file`로 넘긴다. `env/*.env.example`을 같은 이름의 `.env`로 복사해 사용하며 실제 파일은 커밋하지 않는다.
- `BIDOPS_UID`와 `BIDOPS_GID`는 0이 아닌 host 계정과 맞춘다.
- PostgreSQL owner, migrate, app, worker, read-only backup 계정의 비밀번호를 서로 다르게 설정한다.
- MinIO root와 source, structure write/read, quarantine, model-response, proposal-pdf(`BIDOPS_PROPOSAL_PDF_ACCESS_KEY`·`_SECRET_KEY`, web만 받음 — RL-04 결정 B48) 자격증명을 용도별로 분리한다.
- 심층 검토 전에 승인된 profile version과 analysis policy version을 채운다. 빈 값이면 deep-review 생성이 fail closed하는 것이 정상이다.
- 프로필 조회 화면은 승인된 profile snapshot에 고정된다. snapshot이 하나도 없으면 `/api/profile/sections`와 `/api/profile/unknowns`가 `503 profile_snapshot_unavailable`로 fail closed하는 것이 정상이다([ADR-0023](../tracking/decisions/0023-company-profile-minimal-projection.md)). snapshot은 판정 실행이 만들므로 신규 배포에서는 회차 판정을 한 번 실행한 뒤에 프로필 화면을 사용한다.
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

현재 코드의 기대 head는 `0041_proposal_draft`다. 아래는 사전규격 검토 제외·복원을 도입한 `0030_prespec_review_exclusion`의 변경 설명이다.
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
([ADR-0042](../tracking/decisions/0042-c2-model-revision-declared-at-deployment.md)).

서버를 재기동하거나 vLLM 버전을 올려도 이 값은 바뀌지 않는다. **모델 weight가 실제로
바뀔 때만** 갱신하며, 그때는 값만 고치지 않고 binding을 새 버전으로 올리고 품질 게이트를
다시 측정한다. 응답의 `system_fingerprint`는 빌드·병렬도 지문이므로 이 값으로 쓰지 않는다.

## 모듈 선택과 진입점

백엔드는 `core`·`lifecycle`·`screening`·`deep_review` 네 모듈과 조립 계층으로 나뉜다
([ADR-0045](../tracking/decisions/0045-backend-module-layout.md)). 운영 기동은 세 도메인 모듈을
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
