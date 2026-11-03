# 사전규격 참조 실행

[전체 운영 절차](../operations.md). 기준일: 2026-10-21. 명령은 별도 표시가 없으면 저장소 루트에서 실행한다. 운영 변경·실제 전송은 단계별 승인 범위를 따른다.

현재 운영의 마지막 확인은 2026-10-19다. 아래 참조 절차의 과거 실행 상태는 현재 스위치 상태가 아니다. 신규 실행에서 당시 승인을 재사용하지 않는다.

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

`web/run-web-tests.sh`는 임시 PostgreSQL 17에서 migration을 수행하고, 격리 DB의 backend 테스트와 frontend production build, Playwright 화면 스냅샷 회귀를 실행한다. 검증 폭은 laptop 1280x800과 desktop 1440x900 두 폭이다(ADR-0047. 이전의 네 폭에서 모바일 390·태블릿 768을 없앴다). 화면 검사는 의미·구조·픽셀 세 층이며 게이트는 앞의 둘(`npm run test:screens`)이다. 픽셀 층(`npm run test:pixel`)은 기준 이미지 대조라 게이트가 아니고, 갈아 끼울 때는 사유·영향 화면·승인자를 기록에 남긴다([standards.md](../standards.md)). Docker가 없으면 `BIDOPS_TEST_POSTGRES_URL`에 폐기 가능한 PostgreSQL 관리 URL을 제공한다. 운영 DB URL을 사용하지 않는다. Playwright는 브라우저 번들을 자동으로 내려받지 않으므로 없으면 실패한다.

live vLLM smoke는 운영자가 명시한 한 번의 명령과 대상에서만 수행한다. safety 환경변수가 true라는 사실만으로 실행하지 않는다. 결과에는 모델명, digest 또는 승인된 immutable reference, 정책·프로필 버전, 입력 hash, 시작·종료 시각을 남긴다.

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

## PDF 개요 출력 연결

2026-09-11 MVP 재작성으로 v3(`0012`·`0014`·`0019`)·v4(`0021`·`0022`)·v5(`0025`) 개요
스택을 `prespec_overview_run`(migration `0026`) 단일 테이블로 대체했다
([ADR-0054](../tracking/decisions/0054-prespec-overview-mvp-rewrite.md)). `import-page-overview`,
`prespec-v4` cohort ops CLI, Luna 명시 참조 실행 절차는 모두 삭제했다 — 과거 실행 기록이
필요하면 git 이력(commit `71b9954`)에서 찾는다.

새 흐름은 사람이 누르는 별도 ops 명령이 없다. `BIDOPS_PRESPEC_OVERVIEW_ENABLED=true`이면
ready 묶음에서 analysis worker의 개요 slot이 `prespec_overview_run`을 자동 enqueue하고,
prepare(`prespec_v4_pdf_snapshot` 재사용 또는 신규 변환) → range(자동 선택 또는 fallback,
사람 확정은 `POST /api/pre-specs/{notice_id}/overview/range-confirmations`) → draft →
deterministic → v7 전체 semantic 또는 v8 선택 semantic → save 순서로 실행한다. v8은 사실
개요와 예비 판단을 정상 1회에 만들고 위험 신호에만 한 번 더 검증한다. 상세 계약은
[contracts.md](../contracts/prespec-overview.md#사전규격-개요-검토와-예비-적합성-판단-mvp-2026-09-21)를 정본으로 한다. 진행·결과
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

2026-09-08 회사 핏 코드는 기본 비활성이다. 코드 빌드만으로 실행이나 정책 활성화가 일어나지 않는다. 회사 핏의 도입 revision은 `0020_prespec_company_fit`이고 현재 head는 `0041_proposal_draft`다. 새 환경에 적용할 때는 유지보수 절차의 백업·명시적 migration·runtime 권한 적용 뒤 web과 analysis-worker를 같은 코드로 갱신한다. 기존 개요 완료만으로 심층을 시작하던 경로에도 회사 핏 게이트가 추가되므로, 비활성 상태에서는 자동 심층 시작이 대기한다. 사람의 심층 실행·추적 결정은 기존 경로다.

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
배포는 [호스트·Compose](host.md)와 [백업·복구](backup-restore.md)의 현행 절차를 따른다.

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

[단계별 적용 명령과 롤백](../0922_luna-deep-review/apply.md)이 이번 적용 절차다.
0032 migration, 전용 runner 이미지/secret/egress, 불변 Luna 정책, web/worker 환경을
묶어 적용한다. 각 운영 단계 직전 확인을 받는다. 구현·가짜 실행기 검증으로 실제
Luna 인증·모델 접근·실자료 품질이 확인됐다고 쓰지 않는다. 심층 자동 시작 기본값은
off이며 수집·문서 준비·개요를 끄지 않는다.

### 1489 가정 분석 배포 준비 (2026-09-23)

0033 입력/승인/단계 표, runner의 별도 schema, web/analysis/첨부 worker 이미지가 필요하다.
기존 회사 프로필·Luna v3 활성 정책은 유지하며 새 가정 분석 입력에 별도 계약/코드 hash를
동결한다. 운영 migration·서비스 교체·실제 전송은 각각 직전 확인한다. 준비·복구·검증
내역은 [가정 분석 계획](../0923_assumption-analysis/plan.md#운영-적용-준비와-직전-확인)을 따른다.
