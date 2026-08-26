# Worktree별 Agent 경계와 병합 방향

## 1. 목적

이 문서는 `bidops-agent-runtime-design`, `ui-component-refresh`, `bidops-deep-review`가 서로 다른 책임을 유지하면서 최종 integration branch에서 합쳐지기 위한 방향과 병합 전 조건을 고정한다.

현재 선택은 runtime-design의 진행 중인 코드를 즉시 Agent 폴더로 이동하는 것이 아니다. runtime의 내부 책임을 정리하고 안정적인 application service 경계를 남긴 뒤, 공통 Agent 계약과 개별 Agent adapter를 소유 워크트리 또는 integration 단계에서 연결한다.

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

- [ ] 현재 Lean v1, vLLM, mock 관련 dirty 변경을 기준 커밋으로 분리했다.
- [ ] `agents/common`과 세 Agent가 Agent별 패키지에 분리돼 있다.
- [ ] Agent 패키지 사이 직접 import와 service 로직 복사가 없다.
- [ ] 기존 REST 14개의 성공·오류 의미가 유지된다.
- [ ] 결정적 mock E2E와 전체 backend/frontend 회귀 결과를 기록했다.
- [ ] 실제 Qwen/OpenAI/Codex 호출이 mock 검증에서 0건임을 확인했다.
- [ ] runtime과 겹치는 파일 및 계약별 해결 기준을 기록했다.

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

## 8. 중단 조건

다음 상황에서는 임의로 구조를 바꾸거나 병합하지 않는다.

- 사용자 소유 dirty 변경을 덮어써야 함
- 새 DB schema 또는 public API 없이는 연결할 수 없음
- 기존 REST 의미를 유지할 수 없음
- Agent가 screening 내부 worker/provider를 직접 제어해야 함
- 기존 service 로직을 Agent 폴더에 복사해야 함
- 실제 모델 호출 없이 실행해야 하는 검증에서 외부 provider가 호출됨
- 검증되지 않은 runtime 또는 UI commit을 integration 기준으로 사용해야 함

이 경우 예상 영향 파일, 깨지는 계약, 가능한 대안을 기록하고 사용자 결정을 기다린다.
