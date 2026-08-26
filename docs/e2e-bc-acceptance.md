# 단계 B→C 연속 인수 테스트

기준일: 2026-08-26

이 절차는 `문서 bundle 준비(B) → Qwen 3단계 분석(C) → machine report/validation/evidence 조회`를 하나의 증적으로 확인한다. 운영 DB나 기존 Compose volume을 사용하지 않고 새 프로젝트 이름으로만 실행한다.

## 현재 가능한 것과 아직 필요한 것

저장소에는 다음 실행 경계가 준비되어 있다.

- `app.cli.score_candidate_quality`: 실제 모델 결과를 사람이 판정한 manifest에서 재현율·사람 일치율·근거 부족 오판율을 계산한다. 실패 결과는 policy import 인자를 내보내지 않는다.
- `app.cli.import_profile_policy`: 측정한 policy SHA와 실제 import 대상 SHA가 다르면 저장 전에 거부한다. import 결과는 active 설정을 자동 변경하지 않는다.
- `app.cli.run_bc_e2e`: 문서 업로드·검사·구조화·역할 지정·전체 current 문서 확정 후 deep review를 만들고, 세 stage·validation·evidence를 확인한다.
- `docker-compose.t7.remote-vllm.yml`: analysis worker에만 외부 모델 egress network를 추가하는 선택 override다. vLLM 자체는 이 Compose 밖의 승인 서버에서 운영한다.
- `docker-compose.t7.codex-reference.yml`: 워크플로우 확정 기간에만 Codex exec를 모델 생성 경계에 연결하는 개발용 override다. Qwen 품질 승인이나 운영 배포 증적으로 사용할 수 없다.

아래 항목은 저장소만으로 대신 만들 수 없는 실제 인수 입력이다.

- secret manager가 주입한 격리 환경 credential
- 승인된 원격 vLLM IP endpoint와 immutable revision으로 설치된 `Qwen/Qwen3.8-27B` artifact
- 소방예방정보시스템 55개 요구사항 원문을 포함한 대표 HWP/HWPX와 대표 PDF
- 모델 출력에 대한 담당자의 gold mapping과 claim 판정

`fire_prevention_55.json`은 기대 ID 목록이고 원문 자체가 아니다. `labor_template.hwp`와 `safe.pdf`는 변환·안전성 fixture이므로 이것만으로 실제 모델 품질을 통과했다고 기록하면 안 된다. scorer는 Qwen을 호출하지 않으며 사람 판정을 대체하지 않는다.

## 합격 조건

| 경계 | 합격 조건 |
|---|---|
| 모델 고정 | served model ID가 `qwen3.8-27B`이고, 실행 전후 vLLM image digest·모델 revision/artifact digest가 quality manifest와 일치. non-thinking·temperature 0.7·top_p 0.8·top_k 20·seed 0 조건도 동일 |
| 품질 | 필수 항목 재현율 ≥ 0.80, 사람 판정 일치율 ≥ 0.70, 근거 부족 오판율 ≤ 0.10 |
| 단계 B | 모든 current 문서가 `safe`·`ready`, blocking issue 없이 immutable bundle `ready` |
| 단계 C | 순서가 고정된 세 stage가 모두 `completed`, report validation이 `passed`, report가 같은 review/bundle에 결합되고 evidence endpoint 조회 성공 |
| 격리 | 새 Compose project/volume만 사용, 기존 project 중지·volume 삭제 없음 |

## 1. 격리 런타임 준비

아래 예시는 프로젝트 이름을 `bidops-deep-review-e2e`로 고정한다. `/secure/bidops-e2e.env`는 저장소 밖에서 secret manager가 생성한 파일이어야 한다. `.env.example`의 placeholder를 그대로 쓰지 않는다.

```bash
cd /path/to/bidops-agent
docker compose --project-name bidops-deep-review-e2e \
  --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  build
docker compose --project-name bidops-deep-review-e2e \
  --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  up -d postgres minio clamav
COMPOSE_PROJECT_NAME=bidops-deep-review-e2e \
  docker compose --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  run --rm postgres-init
COMPOSE_PROJECT_NAME=bidops-deep-review-e2e \
  docker compose --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  run --rm migrate
COMPOSE_PROJECT_NAME=bidops-deep-review-e2e \
  docker compose --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  run --rm minio-init
```

`docker compose down -v`, volume 삭제, 다른 project의 `down`은 실행하지 않는다. 애플리케이션 Compose에는 모델 service를 포함하지 않는다. 외부 vLLM 서버와 연결할 때만 `docker-compose.t7.remote-vllm.yml`을 사용하며, URL에 credential을 넣지 않고 아래 값을 외부 env에 정확히 지정한다.

```text
BIDOPS_VLLM_BASE_URL=http://<approved-ip>:<published-port>/v1
BIDOPS_VLLM_ALLOWED_HOSTS=<approved-ip>
BIDOPS_VLLM_MODEL=qwen3.8-27B
BIDOPS_VLLM_API_KEY=EMPTY
```

현재 client 계약은 OpenAI Python SDK를 통한 명시적 IP/port의 plain HTTP vLLM base URL `/v1`이다. 실제 호출 path는 `/v1/chat/completions`이고 SDK 자동 재시도·환경 proxy·redirect는 비활성이다. `EMPTY`는 서버 인증이 꺼져 있을 때만 허용한다. endpoint가 HTTPS, hostname 또는 실제 API key를 요구하면 값을 주입하기 전에 transport·secret 계약을 별도로 검토한다. remote override의 `model-egress`는 host firewall에서 승인 IP/port 하나로 제한한다. `document-worker`의 `network_mode: none`은 그대로 유지된다.

생성 계약은 non-thinking, `temperature=0.7`, `top_p=0.8`, `top_k=20`, `seed=0`, 최대 completion 16,384 tokens, 호출당 timeout 300초로 canonical policy에 고정돼 있다. vLLM 요청은 평탄화한 provider JSON Schema로 구조를 제한하고, 응답은 다시 더 엄격한 권위 deep-review-stage validator를 통과해야 한다. 이 중 하나라도 바뀌면 기존 품질 점수를 재사용하지 않는다.

## 2. 모델 artifact 고정과 품질 점수

vLLM 서버 운영자는 `vllm/vllm-openai` image를 `latest`가 아닌 digest로 고정하고, `Qwen/Qwen3.8-27B`도 immutable Hugging Face revision 또는 로컬 artifact digest로 고정한다. 애플리케이션은 응답의 `model`이 `qwen3.8-27B`와 다르면 거부한다.

```bash
curl --fail --silent --show-error \
  -H 'Authorization: Bearer EMPTY' \
  http://<approved-ip>:<published-port>/v1/models
```

`/v1/models`는 served ID·root·max model length 확인용이며 모델 weight digest를 제공하지 않는다. 따라서 실행 전후 API 응답만으로 artifact 고정을 주장하지 않고, 서버 운영자가 제공한 image digest와 model revision/artifact digest를 별도 증적에 기록한다. served ID가 다르거나 외부 digest 증적이 없으면 품질 실행을 활성화 근거로 쓰지 않는다.

실제 모델 출력과 사람 판정을 `/secure/bidops-e2e/input/qwen-quality.json`에 작성한다. 형식은 `bidops.qwen-quality-evaluation.v1`이며 다음 원칙을 지킨다.

- `policy_sha256`: 실행에 사용한 byte-canonical policy의 SHA-256
- `model_artifact_digest`: 서버 운영자가 제공한 immutable model revision/artifact digest
- `samples`: PDF와 HWP/HWPX를 각각 한 건 이상 포함
- `requirements-55` tag가 있는 sample: 정확히 55개의 gold `required_items` 포함
- `detected`: 모델이 gold 항목을 재현했는지 사람 mapping 결과
- `model_status`/`human_status`/`evidence_sufficient`: 선택한 claim별 사람 판정

scorer는 network 없이 실행할 수 있다. `passed=false` 또는 종료 코드 3이면 활성화하지 않는다.

```bash
docker run --rm --network none --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" \
  -v /secure/bidops-e2e/input:/acceptance:ro \
  bidops-deep-review-e2e-web \
  python -m app.cli.score_candidate_quality /acceptance/qwen-quality.json \
  > /secure/bidops-e2e/qwen-quality-result.json
```

통과 결과의 `policy_import_arguments`를 그대로 사용해 measured profile/policy를 import한다. 아래 `<...>`에는 scorer가 출력한 값만 넣는다.

```bash
docker compose --project-name bidops-deep-review-e2e \
  --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  run --rm --no-deps web \
  python -m app.cli.import_profile_policy \
  --actor 'E2E 담당자' \
  --expected-policy-sha256 <policy_sha256> \
  --sample-hash <sample_hash> \
  --required-item-recall <required_item_recall> \
  --human-agreement <human_agreement> \
  --unsupported-false-positive-rate <unsupported_false_positive_rate>
```

출력의 `profile_version_id`, `policy_version_id`를 `/secure/bidops-e2e.env`의 아래 두 값에 넣는다. UUID가 없는 상태에서 deep review 생성은 의도대로 fail-closed한다.

```text
BIDOPS_ACTIVE_PROFILE_VERSION_ID=<profile_version_id>
BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID=<policy_version_id>
```

## 3. 공고 fixture 적재와 서비스 기동

깨끗한 인수 DB에는 공고가 없으므로 저장소의 검증 회차를 읽기 전용으로 한 번 적재한다. 이 bind mount는 repository fixture만 대상으로 하며 운영 데이터 경로에는 사용하지 않는다.

```bash
docker compose --project-name bidops-deep-review-e2e \
  --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  run --rm --no-deps \
  -v "$PWD/data:/app/data:ro" \
  web python -m app.ingest.cli --run 20260817-20260823
docker compose --project-name bidops-deep-review-e2e \
  --env-file /secure/bidops-e2e.env \
  -f docker-compose.t7.yml -f docker-compose.t7.remote-vllm.yml \
  up -d --force-recreate web document-worker analysis-worker
```

`GET /api/runs`와 `GET /api/notices?run_id=<run-id>&grade=우선%20검토`로 시험할 내부 `notice_id`를 고른다. 이 ID는 나라장터 공고번호가 아니라 API 응답의 정수 `id`다. 해당 공고에 기존 current 문서가 있으면 실행기가 새 업로드와 함께 모두 확정하며, 하나라도 안전성/구조화 조건을 만족하지 못하면 C로 넘어가지 않는다.

## 4. B→C manifest와 실행

`/secure/bidops-e2e/input/bc-run.json`의 문서 경로는 runner 컨테이너에서 보이는 절대 경로여야 한다.

```json
{
  "schema": "bidops.bc-e2e-run.v1",
  "api_base": "http://127.0.0.1:18787",
  "notice_id": 123,
  "actor_name": "E2E 담당자",
  "documents": [
    {"path": "/acceptance/documents/representative.hwp", "role": "제안요청서"},
    {"path": "/acceptance/documents/representative.pdf", "role": "부록"}
  ],
  "analysis_retry_limit": 1
}
```

먼저 dry-run으로 target·파일·크기·역할만 확인한다. 이 단계는 API를 호출하지 않는다.

```bash
docker run --rm --network host --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" \
  -v /secure/bidops-e2e/input:/acceptance:ro \
  bidops-deep-review-e2e-web \
  python -m app.cli.run_bc_e2e /acceptance/bc-run.json --dry-run
```

검토 후 target을 같은 문자열로 다시 확인하고 새 evidence 파일에 기록한다. 출력 파일이 이미 있으면 덮어쓰지 않고 중단한다.

```bash
docker run --rm --network host --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" \
  -v /secure/bidops-e2e/input:/acceptance:ro \
  -v /secure/bidops-e2e/output:/evidence \
  bidops-deep-review-e2e-web \
  python -m app.cli.run_bc_e2e /acceptance/bc-run.json \
  --confirm-target http://127.0.0.1:18787 \
  --analysis-timeout-seconds 3600 \
  --poll-seconds 2 \
  --output /evidence/bc-result.json
```

`bc-result.json`의 `passed=true`만으로 끝내지 않고 다음을 사람이 함께 확인한다.

- `bundle.status=ready`, 모든 document가 `safe`·`ready`
- stage 순서가 `requirements_and_evaluation` → `delivery_risk_economics` → `synthesis_and_validation`
- `report.validation_status=passed`
- evidence의 source SHA와 locator가 기대 원문을 가리킴
- 실행 전후 vLLM image digest와 model revision/artifact digest가 동일
- timeout/잘린 JSON은 내부 최대 2회 재시도 후 안전한 실패가 되고, `analysis_retry_limit=1`일 때만 새 attempt가 한 번 추가됨

## 증적과 중단 기준

다음 파일을 같은 인수 실행 ID로 보관한다.

- secret 값이 제거된 Compose config와 image digest
- 실행 전후 vLLM image digest, served model ID, model revision/artifact digest
- 원문 SHA-256과 사람 판정 manifest
- `qwen-quality-result.json`
- measured profile/policy import 결과와 active UUID
- `bc-result.json`, 서비스 health, 시작·종료 시각

어느 단계든 실패하면 해당 project를 보존한 채 로그의 safe error code와 증적을 먼저 수집한다. 실패를 통과로 바꾸기 위해 DB row, policy quality metadata, report 또는 object를 수동 수정하지 않는다.

## Mock 기준 전체 워크플로우

실제 Qwen 품질 조정 전에 상태 전이와 저장·검증·사람 의사결정 계보를 확정할 때는
`docker-compose.t7.mock-reference.yml`을 기본 Compose에 결합한다.

```bash
docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  --env-file /secure/bidops-e2e/mvp.env \
  -f docker-compose.t7.yml \
  -f docker-compose.t7.mock-reference.yml \
  up -d
```

이 override는 web과 analysis worker에 다음 경계를 강제한다.

- `BIDOPS_ANALYSIS_PROVIDER=mock`
- `BIDOPS_REFERENCE_WORKFLOW_MODE=true`
- OpenAI/Codex 비활성
- analysis worker의 기존 internal network 유지; model egress 추가 없음
- creation audit의 provider/model은 `mock-analysis` / `bidops-deterministic-mock-v1`
- policy quality는 `reference_workflow_unmeasured`, `deployable=false`

Mock은 입력 slice의 exact quote로 최소 supported claim/evidence를 만들고 Stage 3에 고정 권고를
넣는다. 따라서 결과 내용은 사업 판단이나 모델 품질 평가에 사용할 수 없다. JSON Schema,
claim/evidence validator, encrypted raw-response 저장, report materialization, revision validation,
final opinion은 실제 경로를 그대로 사용한다.

검증 순서는 다음으로 고정한다.

1. `run_bc_e2e`로 upload → safe/structure → ready → 3 stages → machine report/evidence를 완주한다.
2. 현재 report 전체 payload를 base로 `POST .../report-revisions`를 호출한다. factual body를
   바꾸면 같은 review의 `factual_change_evidence_ids`를 함께 보내고 새 validation run을 확인한다.
3. 새 revision/validation ID를 고정해 `POST .../final-opinions`를 호출한다.
4. 새 수동 첨부를 등록한 새 bundle을 ready로 만들고 새 deep review를 실행한다.
5. 이전 review에서 machine/human history와 final opinion을 계속 조회할 수 있고, 새 review에
   사람 수정·최종 의견이 자동 승계되지 않았음을 확인한다.

Qwen 전환 시에는 Mock override를 제거하고 승인된 vLLM override/config를 사용한다. 기존 Mock
review는 provider/model lineage가 고정되어 있으므로 Qwen attempt로 재사용하지 않는다. 새 bundle
또는 새 policy version으로 새 deep review를 만들고 55개 fixture 품질 gate를 별도로 수행한다.

## 임시 Codex exec 기준 실행

Qwen 품질 조정 전에 B→C와 보고서 후속 흐름을 먼저 확정할 때만 `docker-compose.t7.codex-reference.yml`을 사용한다. 외부 전송이므로 대상 내부 `notice_id`마다 담당자 승인이 선행되어야 하며, 다음 세 gate 중 하나라도 빠지면 deep review 생성이 403으로 중단된다.

- `BIDOPS_ANALYSIS_PROVIDER=codex-exec`
- `BIDOPS_OPENAI_ENABLED=true`와 `BIDOPS_CODEX_EXEC_ENABLED=true`
- `BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS`에 대상 내부 notice ID 존재

override는 host Codex 실행 파일과 `auth.json` 파일 하나만 analysis worker에 읽기 전용으로 mount한다. Codex는 `--ephemeral`, read-only sandbox, user config/rules 무시, shell·browser·computer-use·plugin·multi-agent 비활성 상태로 실행된다. BidOps DB/MinIO credential은 subprocess 환경에서 제거되며 prompt와 원문은 stdin으로만 전달된다. raw 응답은 Qwen과 동일하게 암호화 model-response namespace에 저장된다.

```text
BIDOPS_CODEX_EXEC_HOST_BIN=/absolute/path/to/codex
BIDOPS_CODEX_EXEC_HOST_AUTH_FILE=/absolute/path/to/auth.json
BIDOPS_CODEX_EXEC_MODEL=gpt-5.6-sol
BIDOPS_CODEX_EXEC_REASONING_EFFORT=low
BIDOPS_CODEX_EXEC_APPROVED_NOTICE_IDS=123
```

기동할 때 remote-vLLM override 대신 Codex override를 결합한다. 이 실행의 creation audit와 stage invocation metadata에는 실제 provider/model이 `codex-exec-reference`와 Codex model로 남지만, 고정 policy의 Qwen model 이름은 별도 필드로 보존된다. 동일 입력을 Qwen으로 재검증할 때는 provider lineage 충돌을 피하도록 새 격리 DB 또는 새 policy version에서 새 review를 만든다.
