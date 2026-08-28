# HANDOFF — T8 Agent 구현 검토·통합 인수

기준일: 2026-08-27
브랜치: `bidops-deep-review`
검토 기준 HEAD: `4f98a5c9ed986b534403df4c8feebaf3ebdbfab0`
T8 결과: 코드 변경 없음. 지정 문서 7개만 갱신했으며 commit/push/merge/release는 하지 않았다.

## 0. 결론

현재 HEAD에는 T1~T7의 Agent 구현과 결정적 Mock 연속 인수가 들어 있다. T8은 이 구현을 실제 코드와
검증 결과에 맞춰 문서화하고, 다음 통합자가 충돌 지점과 재현 절차를 확인할 수 있게 하는 작업이다.

- 공통 폐쇄 계약·projection과 `DocumentPreparationAgent`, `DeepReviewAgent`, `DecisionAgent`가 구현돼 있다.
- 기존 document bundle/deep review/report mutation router가 해당 Agent adapter를 호출한다. 기존 Lean v1
  14개 REST endpoint의 response, error, version, idempotency 의미는 유지한다.
- `AgentRunView`는 별도 저장 row가 아니라 기존 domain/audit snapshot에서 계산된다. Agent REST API,
  `agent_run` table, `BidOpsCoordinator`, `OpportunityDiscoveryAgent`는 현재 범위에 없다.
- T7의 실제 격리 E2E는 workflow 인수이지 Qwen 품질 승인이 아니다.

## 1. T1~T7 코드 기준선

| 영역 | 실제 위치 | 통합 시 보존할 경계 |
|---|---|---|
| 공통 계약·projection | `web/backend/app/agents/common/` | typed command, safe error, run status/action, read-only projection |
| 문서 준비 | `web/backend/app/agents/document_preparation/` | register → scan/structure → metadata/issues → confirm/ready 전이 |
| 심층 검토 | `web/backend/app/agents/deep_review/` | 3 stage, attempt/retry, report·validation outcome projection |
| 의사결정 | `web/backend/app/agents/decision/` | machine report → human revision → final opinion 전이 |
| mutation 연결 | `web/backend/app/routers/document_bundles.py`, `deep_reviews.py`, `reports.py` | 기존 service를 adapter가 호출하고 public REST 계약을 변경하지 않음 |
| 연속 인수 | `web/backend/app/services/agent_e2e.py`, `app/cli/run_bc_e2e.py` | DB projection 확인, provider guard, 외부 호출 0, active WorkJob 0 |
| Mock runtime | `docker-compose.t7.mock-reference.yml` | `mock-analysis`, `bidops-deterministic-mock-v1`, OpenAI/Codex disabled |

Agent는 기존 service·queue·worker·validator·provider 로직을 복사하지 않는다. screening runtime을
Agent 폴더로 재작성하거나, Agent 상태 전용 schema를 추가하는 것도 이 기준선의 일부가 아니다.

## 2. 커밋 순서와 병합 경계

현재 HEAD에 포함된 구현 순서는 다음과 같다.

| 순서 | commit | 내용 |
|---:|---|---|
| 1 | `1f080f3` | strict common workflow contracts |
| 2 | `dc049ee` | DocumentPreparationAgent |
| 3 | `d658253` | DeepReviewAgent |
| 4 | `dfbe31f` | DecisionAgent |
| 5 | `0a51af2` | decision projection contract 보정 |
| 6 | `110d62f` | 기존 mutation router를 Agent adapter에 연결 |
| 7 | `18ca38b` | adapter 경유 mutation idempotency 보존 |
| 8 | `7313a31` | 누락 PDF content object 거부 보정 |
| 9 | `4f98a5c` | 결정적 T7 Agent 연속 acceptance와 증적 runner |

T8 문서는 새 commit에 들어 있지 않다. 통합자가 이 worktree의 문서 변경을 확인할 때는 다음처럼
현재 diff를 직접 본다.

```bash
git status --short
git diff --stat
git diff -- docs/agent-workflow-design.md \
  docs/agent-workflow-implementation-plan.md \
  docs/mock-workflow-e2e-result.md \
  docs/worktree-agent-boundary-and-merge-direction.md \
  docs/tracking/status.md docs/tracking/findings.md HANDOFF.md
```

통합 순서는 최신 검증된 runtime/schema 변경, UI 변경, 이 Agent 기준선, 이후 opportunity adapter와
최종 회귀 순으로 조율한다. 다른 worktree의 실제 상태는 이 문서에서 완료로 가정하지 않는다.

## 3. T7 증적의 해석

상세 증적은 [`docs/mock-workflow-e2e-result.md`](docs/mock-workflow-e2e-result.md)에 보존돼 있다.
2026-08-26 기존 B→C 증적과 2026-08-27 Agent 연속 E2E 증적을 삭제·교체·재명명하지 않는다.

2026-08-27 실행의 사실은 다음과 같다.

- 새 격리 Compose project에서 PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web을 사용했다.
- provider/model은 `mock-analysis` / `bidops-deterministic-mock-v1`이다.
- 결과 schema는 `bidops.t7-e2e-result.v1`, `passed=true`이다.
- 외부 OpenAI/Codex/Qwen 호출은 0건이고 종료 active WorkJob은 0건이다.
- 실행 후 격리 container, network, volume을 정리했다.
- `mock_quality.evaluated=false`이므로 workflow 저장·상태·검증·계보 인수 결과를 Qwen 품질
  evidence, 실제 사업 판단, 배포 승인으로 해석하지 않는다.

현재 기록된 T7 project가 이미 정리된 상태라면 기존 Compose project나 volume을 되살리거나
중지하지 않는다. 재현이 필요할 때만 새 project 이름과 새 volume을 사용한다.

## 4. T8에서 실제 실행한 검증

| 명령 | 결과 |
|---|---|
| `git diff --check` | 성공 |
| `./run-tests.sh` | 성공: collect 28, report 13, screen 21, root 2; 총 64개 unittest |
| `./web/run-web-tests.sh` | 성공: backend `356 passed, 4 skipped, 6 warnings`; frontend Vite build 성공, 135 modules transformed |
| `web/backend/.venv/bin/pytest web/backend/tests` | 성공: `356 passed, 4 skipped, 6 warnings in 20.02s` |
| `cd web/frontend && npm run build` | 성공: Vite 6.4.3, 135 modules transformed, `built in 1.88s` |

backend의 4 skip은 `test_document_bundles.py` 1개와 `test_minio_e2e.py` 3개로, 별도 isolated T7
MinIO service가 필요한 live integration test다. 6 warnings는 Pydantic `schema` field shadowing
5건과 Starlette/httpx deprecation 1건이다. 검증 환경에 ignored `web/backend/.venv`가 처음 없어
`./web/run-web-tests.sh`의 첫 실행이 `/usr/bin/python3: No module named pytest`(exit 1)로 실패했고,
requirements를 설치한 뒤 재실행해 위 성공 결과를 얻었다. 첫 실패를 통과로 세지 않았다.

Playwright visual test는 T8에서 실행하지 않았다. 28개 한글 font snapshot 차이는 사람 승인이
필요하므로 통과로 표시하지 않는다.

### 최종 리뷰 재검증

최종 리뷰 수정 후 backend는 `359 passed, 4 skipped, 6 warnings`, `./run-tests.sh`는 64개 모두
성공했고 `./web/run-web-tests.sh`와 별도 frontend build도 성공했다. 추가로 읽기 전용 structure
client가 write credential을 선택하던 문제, metadata mutation의 최신 bundle ref 경쟁 조건,
한글 actor HTTP header 전송 실패를 수정하고 회귀 테스트를 추가했다.

## 5. 최종 리뷰 결과와 남은 차단 사항

### 5.1 clean PostgreSQL legacy ingest — 해결됨

최종 리뷰에서 `Run.screening_basis`를 원문 보존형 `TEXT`로 바꾸고
`0002_screening_basis_text` migration과 회귀 테스트를 추가했다. 별도의 깨끗한 PostgreSQL 17에서
migration 후 `data/runs/20260817-20260823`를 두 번 적재해 두 실행 모두 공고 40건·판정 40건,
동일 run ID를 확인했다. 실제 102자 설명이 절단 없이 저장됐고 컬럼은 `text`였다. 검증용
container, network, volume은 해당 격리 project에 한정해 정리했다.

### 5.2 Qwen 품질·운영 증적

실제 Qwen 품질 gate에는 immutable image/model artifact digest, 대표 HWP/PDF, 55개 요구사항 원문,
사람 gold mapping과 claim 판정이 필요하다. Mock 결과로 `0.80/0.70/0.10` gate를 채우지 않는다.
실제 backup restore, MinIO 권한, secret/egress firewall, Playwright snapshot 승인도 별도 미완료다.

## 6. 충돌 해결 기준

충돌이 나면 파일 전체를 한쪽으로 선택하지 말고 계약별로 수동 대조한다.

| 충돌 대상 | 현재 HEAD에서 유지할 것 |
|---|---|
| `web/backend/app/agents/**` | 이 branch의 common enum·typed command·projection·adapter를 기준으로 유지; 동명 Agent를 새로 만들지 않음 |
| `web/backend/app/agents/__init__.py` | 필요한 export만 합치고 import 순서·순환 의존 방지 |
| `web/backend/app/routers/document_bundles.py` | actor header, request id, version/409, idempotency, 기존 response/error와 DocumentPreparationAgent 연결 |
| `web/backend/app/routers/deep_reviews.py` | ready bundle/attempt 검증, DeepReviewAgent 연결, 기존 `DeepReviewView` 응답 |
| `web/backend/app/routers/reports.py` | append-only revision/opinion, full snapshot, evidence 범위, validation acknowledgement |
| `web/backend/app/services/{document_bundles,deep_reviews,reports}.py` | 기존 domain service와 transaction 경계; Agent 폴더로 업무 로직을 복사하지 않음 |
| models/migrations/config/db | `agent_run`/outbox 같은 Agent 전용 table·column을 이 기준선의 일부로 추가하지 않음 |
| `agent_e2e.py`, T7 tests, Mock override | `--t7`, provider/model guard, 외부 호출 0, active WorkJob 0, `mock_quality.evaluated=false` |
| frontend | T1~T7 Agent 구현에서 변경하지 않음; UI branch의 변경을 덮어쓰지 않음 |

충돌 해결 후 API status/error, actor/idempotency/version, transaction, provider egress, immutable
revision/opinion을 각각 확인하고 integration 기록에 선택 근거를 남긴다.

## 7. 통합 재현 절차

새 작업 디렉터리에서 실행하며, 기존 실행 중인 Compose project와 volume은 건드리지 않는다. 먼저
필수 문서를 읽고 현재 diff가 문서 7개뿐인지 확인한다.

```bash
git status --short
git diff --check
./run-tests.sh
./web/run-web-tests.sh
web/backend/.venv/bin/pytest web/backend/tests
cd web/frontend && npm run build
```

T7 workflow를 다시 확인해야 하면 `docs/e2e-bc-acceptance.md`의 격리 준비 절차를 따르고, 반드시
새 Compose project에 `docker-compose.t7.yml`과 `docker-compose.t7.mock-reference.yml`을 결합한다.
실행 중인 새 web container 안에서 다음 형태로 호출한다.

```bash
docker exec <fresh-isolated-web-container> \
  python -m app.cli.run_bc_e2e /tmp/t7-manifest.json \
  --t7 --confirm-target http://127.0.0.1:8787 \
  --output /tmp/t7-result.json
```

모델은 Mock으로 고정하고 결과의 `mock_quality.evaluated=false`를 유지한다. 이 명령의 성공은
Qwen 품질 gate가 아니다. secret, 원문 bytes, 내부 object key를 로그나 문서에 남기지 않으며,
project/volume 정리는 그 새 project에만 한정한다.

legacy ingest를 재검증할 때도 운영 DB가 아닌 별도의 깨끗한 PostgreSQL에서 실행하고,
`screening_basis` 원문 길이와 두 번째 적재의 멱등성을 함께 확인한다. 기존 산출물을 덮어써서
검증을 통과시키지 않는다.

## 8. 중단 조건과 금지 작업

다음이면 병합을 멈추고 사용자 또는 integration owner에게 근거와 함께 보고한다.

- 사용자 dirty 변경을 덮어써야 하는 경우
- public REST 의미, immutable history, actor/version/idempotency 계약을 유지할 수 없는 경우
- 새 DB schema/API가 필요하다고 판단되는 경우
- Agent가 screening worker/provider를 직접 제어해야 하는 경우
- Qwen 품질 또는 clean ingest 성공을 Mock/부분 실행 결과로 주장해야 하는 경우

이 인수 범위에서는 main merge, push, release, 기존 Compose project/volume 조작, 범위 밖 코드 수정,
T8 새 commit 생성을 수행하지 않는다.
