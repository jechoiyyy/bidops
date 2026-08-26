# Worktree별 Agent 경계와 병합 방향

기준일: 2026-08-27
검토 기준 HEAD: `4f98a5c9ed986b534403df4c8feebaf3ebdbfab0` (`bidops-deep-review`)
T8 상태: 코드 변경 없음, 이 문서를 포함한 지정 문서 7개만 갱신, commit/push/merge/release 없음

## 1. 목적

이 문서는 `bidops-agent-runtime-design`, `ui-component-refresh`, `bidops-deep-review`가 서로 다른 책임을 유지하면서 최종 integration branch에서 합쳐지기 위한 방향과 병합 전 조건을 고정한다.

통합 목표는 runtime-design의 내부 책임을 Agent 폴더로 옮기지 않고 안정적인 application service 경계를
남기는 것이다. 현재 downstream Agent 계약과 adapter 연결은 이 worktree의 T1~T7에서 완료됐으며,
runtime-design과 integration 단계에서는 그 경계를 보존한다.

### 1.1 현재 HEAD의 경계 판정

T1~T7 구현은 `bidops-deep-review`의 현재 HEAD에 순서대로 고정되어 있다. `AgentRunView`는 별도
저장 row가 아니라 기존 domain/audit snapshot에서 계산되고, T7의 `agent_e2e.py`는 새 API나 새
테이블 없이 이 projection을 읽는다. 따라서 통합자는 Agent 상태를 runtime-design의 별도 상태
저장소로 합치지 않는다.

현재 확인된 실제 상태:

- `agents/common`, `document_preparation`, `deep_review`, `decision`과 관련 테스트가 존재한다.
- document bundle/deep review/report의 mutation router는 해당 adapter를 사용한다. 기존 Lean v1
  14개 endpoint와 response/error 의미는 유지한다.
- T7 실제 격리 Mock E2E는 PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web에서
  `passed=true`, `mock-analysis`/`bidops-deterministic-mock-v1`, 외부 OpenAI/Codex/Qwen 호출 0건,
  종료 active WorkJob 0건을 확인한 뒤 자원을 정리했다.
- `OpportunityDiscoveryAgent`, `BidOpsCoordinator`, Agent REST API, Agent 전용 table은 현재도 없다.

## 2. 최종 목표 구조

```text
web/backend/app/
├── agents/
│   ├── common/
│   │   ├── contracts.py
│   │   ├── errors.py
│   │   └── projection.py
│   ├── opportunity_discovery/
│   │   ├── commands.py
│   │   ├── projection.py
│   │   └── agent.py
│   ├── document_preparation/
│   │   ├── commands.py
│   │   ├── projection.py
│   │   └── agent.py
│   ├── deep_review/
│   │   ├── commands.py
│   │   ├── projection.py
│   │   └── agent.py
│   └── decision/
│       ├── commands.py
│       ├── projection.py
│       └── agent.py
└── screening/
    └── 기존 screening domain/runtime 구현
```

의존 방향은 다음과 같다.

```text
router → 해당 Agent adapter → 기존 domain/application service
```

- Agent 패키지는 서로 직접 호출하지 않는다.
- `agents/common`에는 공통 폐쇄 계약과 side-effect 없는 순수 함수만 둔다.
- 기존 service, queue, worker, validator, provider adapter의 업무 로직을 Agent 폴더로 복사하지 않는다.
- `screening`은 모델 실행, queue, worker, policy, quality gate를 담당하는 독립 runtime/domain 계층으로 유지한다.

## 3. 워크트리별 소유권

| Worktree | 소유하는 작업 | 소유하지 않는 작업 |
|---|---|---|
| `bidops-agent-runtime-design` | 기존 `app/screening` runtime, queue/FIFO, worker, policy, quality gate, scheduler, Agent가 호출할 application service 경계 | `agents/common`, 세 deep-review Agent, 폴더 전체 이동, 임의의 공통 Agent 계약 |
| `ui-component-refresh` | runtime 기준 UI component와 화면 갱신, frontend 자체 회귀 | backend Agent 계약, screening 업무 로직, deep-review 서비스 |
| `bidops-deep-review` | `agents/common`, `document_preparation`, `deep_review`, `decision`, 기존 mutation router의 내부 연결, 결정적 mock 연속 검증 | `OpportunityDiscoveryAgent` 실제 구현, screening runtime 재작성, UI 개편 |
| integration branch | `OpportunityDiscoveryAgent`의 얇은 adapter, root export와 최종 router 조립, 공통 파일 충돌 해결, 전체 회귀 | 검증되지 않은 신규 기능, 한쪽 branch 전체 선택에 의한 계약 폐기 |

`agents/common`은 `bidops-deep-review`가 한 번만 구현한다. runtime-design에서 별도 구현하지 않는다. 이 원칙은 두 워크트리가 서로 다른 공통 enum과 RunView를 만드는 add/add 충돌을 막기 위한 것이다.

## 4. runtime-design에 전달할 방향

runtime-design은 현재 구조를 보존하면서 다음 조건을 만족해야 한다.

1. `app/screening`을 runtime/domain 계층으로 유지한다.
2. router가 queue, worker, provider 세부 구현에 직접 의존하지 않도록 명확한 application service 진입점을 둔다.
3. 이후 `OpportunityDiscoveryAgent`가 그 service를 얇게 감쌀 수 있어야 한다.
4. screening 업무 로직을 router, scheduler, UI adapter에 복사하지 않는다.
5. provider URL, 모델명, credential, DB row를 application-level 입력·출력 계약에 노출하지 않는다.
6. 상태 조회는 저장된 값만 사용하고 UUID, 현재 시각, audit row를 새로 만들지 않는다.
7. 기존 REST, DB schema, queue/FIFO, scheduler, quality gate의 의미를 유지한다.
8. `agents/common`이나 다른 Agent package를 선행 구현하지 않는다.
9. 구조 이동이 필요하다고 판단되면 구현하지 말고 예상 파일, 이점, 충돌 범위를 제안으로 남긴다.

runtime-design 완료 문서에는 다음을 기록한다.

- Agent adapter가 호출할 screening service 진입점
- 각 진입점의 입력, 출력, 안전 오류, transaction 경계
- 조회 가능한 상태와 immutable artifact
- provider-specific 코드의 위치
- Agent 연결 시 수정해야 할 router 목록
- 다른 worktree와 겹치는 공통 파일
- 실행한 테스트와 결과
- 미완료 작업과 병합 중단 조건

## 5. 병합 전 체크리스트

### 5.1 runtime-design

- [ ] 계획된 runtime 작업이 완료됐거나 미완료 범위가 명시돼 있다.
- [ ] `app/screening`의 service 진입점과 transaction 경계가 문서화돼 있다.
- [ ] queue/FIFO, worker recovery, scheduler, quality gate 테스트가 통과한다.
- [ ] `agents/common`과 deep-review Agent 파일을 만들지 않았다.
- [ ] dirty 파일을 관련 변경과 사용자 변경으로 분류했다.
- [ ] runtime 변경을 검토 가능한 커밋으로 고정했다.

### 5.2 ui-component-refresh

- [ ] 검증된 runtime 기준 commit 위에서 작업했는지 확인했다.
- [ ] runtime API와 일치하는 UI만 포함한다.
- [ ] backend Agent 또는 screening 업무 로직 변경이 없다.
- [ ] frontend unit/visual/build 검증 결과를 기록했다.
- [ ] runtime에 먼저 병합할 수 있는 독립 커밋 상태다.

### 5.3 bidops-deep-review

- [x] 현재 Lean v1, vLLM, mock 관련 변경이 T1~T7 commit으로 기준 커밋에 고정돼 있다.
- [x] `agents/common`과 세 Agent가 Agent별 패키지에 분리돼 있다.
- [x] Agent 패키지 사이 직접 import와 service 로직 복사가 없다.
- [x] 기존 REST 14개의 성공·오류 의미가 유지된다.
- [x] 결정적 Mock E2E와 전체 backend/frontend 회귀 결과를 기록했다.
- [x] 실제 Qwen/OpenAI/Codex 호출이 Mock 검증에서 0건임을 확인했다.
- [x] runtime과 겹치는 파일 및 계약별 해결 기준을 이 문서와 HANDOFF에 기록했다.

### 5.4 integration branch

- [ ] 완료되고 전체 검증된 최신 runtime commit을 기준으로 만들었다.
- [ ] runtime의 직접 후속인 UI 변경을 먼저 반영했다.
- [ ] deep-review/Agent branch를 merge commit으로 반영했다.
- [ ] `OpportunityDiscoveryAgent`는 screening service를 감싸는 얇은 adapter로만 추가했다.
- [ ] migration, models, app entry, config/db, backend dependency, frontend route/mock을 파일별·계약별로 검토했다.
- [ ] 충돌 파일에 `ours` 또는 `theirs`를 통째로 적용하지 않았다.
- [ ] 깨끗한 DB migration, backend 전체 테스트, frontend build, 결정적 mock E2E가 통과했다.
- [ ] 검증 완료 전 main merge, push, release를 수행하지 않았다.

## 6. 병합 순서

```text
완료·검증된 runtime 기준
→ ui-component-refresh
→ bidops-deep-review 및 세 Agent
→ OpportunityDiscoveryAgent adapter
→ 전체 회귀
→ main PR
```

- runtime 후속 작업이 완료·검증됐으면 최신 결과를 기준으로 사용한다.
- runtime 후속 작업이 미완료 또는 차단 상태면 마지막으로 완료·검증된 runtime을 먼저 통합하고 후속 변경은 별도 병합한다.
- dirty runtime 또는 deep-review worktree에서 서로 직접 merge하지 않는다.
- 큰 feature commit을 임의 순서로 cherry-pick하지 않는다.

### 6.1 현재 Agent commit 순서

현재 HEAD의 Agent 구현은 다음 순서로 누적됐다. 통합자가 cherry-pick을 선택한다면 이 순서를
그대로 사용하고, 한 번에 branch를 merge한다면 아래 순서를 conflict review 기준으로 사용한다.

| 순서 | commit | 내용 |
|---:|---|---|
| 1 | `1f080f3` | common contract, safe error, 순수 projection helper |
| 2 | `dc049ee` | DocumentPreparationAgent |
| 3 | `d658253` | DeepReviewAgent |
| 4 | `dfbe31f` | DecisionAgent |
| 5 | `0a51af2` | decision projection contract 보정 |
| 6 | `110d62f` | 기존 mutation router를 Agent adapter에 연결 |
| 7 | `18ca38b` | adapter 경유 mutation idempotency 보존 |
| 8 | `7313a31` | PDF content object 누락 거부 회귀 보정 |
| 9 | `4f98a5c` | 결정적 T7 Agent 연속 acceptance와 증적 runner |

T8 문서 변경은 별도 commit이 없으므로 `git diff -- <지정 문서>`로 확인한다. T8 변경을
임의로 코드 commit에 섞거나, 아래 증적을 새 Qwen 품질 결과로 이름을 바꾸지 않는다.

## 7. 집중 충돌 검토 대상

다음 파일과 영역은 양쪽 변경의 의미를 함께 보존해야 한다.

- Alembic configuration과 migration revision
- `web/backend/app/models.py`
- `web/backend/app/main.py`
- `web/backend/app/config.py`
- `web/backend/app/db.py`
- backend `pyproject.toml`, `requirements.txt`, Dockerfile
- frontend route와 API mock
- architecture, contracts, operations 문서

충돌 해결 후에는 schema, API, transaction, provider, UI 계약별로 무엇을 선택했는지 integration 기록에 남긴다.

### 7.1 실제 충돌 파일별 해결 기준

| 영역 | 현재 HEAD의 의미 | 통합 시 보존할 것 |
|---|---|---|
| `web/backend/app/agents/**` | 세 Agent와 common 계약의 유일한 구현 | runtime-design 쪽에 동명 Agent 계약이 생겨도 양쪽을 통째로 선택하지 말고 이 branch의 공통 enum·RunView·adapter를 기준으로 수동 대조 |
| `web/backend/app/agents/__init__.py` | common, command, projection, Agent의 root export | 다른 branch의 export를 필요한 만큼 합치되 Agent export와 import 순서를 보존 |
| `web/backend/app/routers/document_bundles.py` | bundle 4 mutation이 DocumentPreparationAgent command/adapter를 사용 | 기존 response model·stable error·actor header·version/idempotency 검사를 유지하며 router 변경을 수동 결합 |
| `web/backend/app/routers/deep_reviews.py` | review 생성·attempt retry가 DeepReviewAgent를 사용 | ready bundle/attempt ref 검증과 기존 `DeepReviewView` 계약을 함께 유지 |
| `web/backend/app/routers/reports.py` | full revision·final opinion이 DecisionAgent를 사용 | full snapshot, evidence scope, validation acknowledgement, append-only 응답을 함께 유지 |
| `web/backend/app/services/{document_bundles,deep_reviews,reports}.py` | adapter가 재사용하는 기존 domain service 경계 | 업무 로직을 Agent 폴더로 복사하지 말고 service 계약과 transaction 경계를 유지 |
| `web/backend/app/services/agent_e2e.py`, `app/cli/run_bc_e2e.py`, T7 tests | 새 API/table 없는 persisted projection acceptance | `--t7`, provider/model guard, projection assertion, active WorkJob 0 검사를 유지 |
| `docker-compose.t7.mock-reference.yml` | web/analysis-worker를 local Mock으로 고정 | `mock-analysis`, `bidops-deterministic-mock-v1`, OpenAI/Codex disabled, reference mode를 보존 |
| models/migrations/config/db | Agent 전용 table/column/migration은 없음 | 충돌이 생겨도 `agent_run`/outbox를 추가하지 않고 Lean v1 schema·security 경계를 계약별로 검토 |
| frontend | T1~T7 Agent 구현에서 frontend 코드는 변경하지 않음 | UI branch의 변경을 이 branch의 backend adapter 결과로 추정해 덮어쓰지 않음 |

## 8. 통합 재현 검증

통합자는 새 작업 디렉터리와 새 격리 Compose project에서 다음을 실행한다. 현재 운영/기존
Compose project와 volume은 대상이 아니다.

```bash
git diff --check
./run-tests.sh
./web/run-web-tests.sh
web/backend/.venv/bin/pytest web/backend/tests
cd web/frontend && npm run build
```

T8에서 확인한 최종 기준은 root unittest 64개 성공, backend `356 passed, 4 skipped`, frontend
Vite build 성공이다. backend의 4 skip은 isolated T7 MinIO가 필요한 live integration test다.
검증 환경에 `.venv`가 없으면 `./web/run-web-tests.sh`는 pytest import 단계에서 실패하므로,
`web/backend/requirements.txt`를 설치한 격리 virtualenv를 먼저 준비하고 실패한 첫 실행을
성공으로 세지 않는다. Playwright visual test는 T8에서 실행하지 않았고, 28개 한글 font snapshot
차이는 아직 사람 승인이 필요하다.

T7 acceptance를 재현할 때는 새 project에 `docker-compose.t7.yml`과
`docker-compose.t7.mock-reference.yml`을 결합하고, 실행 중인 web container 안에서 아래 CLI를
호출한다. `mock_quality.evaluated=false`를 유지하며 실제 Qwen 품질 gate로 해석하지 않는다.

```bash
docker exec <fresh-isolated-web-container> \
  python -m app.cli.run_bc_e2e /tmp/t7-manifest.json \
  --t7 --confirm-target http://127.0.0.1:8787 \
  --output /tmp/t7-result.json
```

현재 기록된 T7 project는 이미 정리됐으며, 그 실행은 PostgreSQL·MinIO·ClamAV·document worker
2개·analysis worker·web, Mock provider/model, 외부 OpenAI/Codex/Qwen 0건, 종료 active WorkJob
0건, `passed=true`를 확인했다. 상세 ID와 두 날짜 증적은
`docs/mock-workflow-e2e-result.md`에 있다.

## 9. 중단 조건

다음 상황에서는 임의로 구조를 바꾸거나 병합하지 않는다.

- 사용자 소유 dirty 변경을 덮어써야 함
- 새 DB schema 또는 public API 없이는 연결할 수 없음
- 기존 REST 의미를 유지할 수 없음
- Agent가 screening 내부 worker/provider를 직접 제어해야 함
- 기존 service 로직을 Agent 폴더에 복사해야 함
- 실제 모델 호출 없이 실행해야 하는 검증에서 외부 provider가 호출됨
- 검증되지 않은 runtime 또는 UI commit을 integration 기준으로 사용해야 함

이 경우 예상 영향 파일, 깨지는 계약, 가능한 대안을 기록하고 사용자 결정을 기다린다.
