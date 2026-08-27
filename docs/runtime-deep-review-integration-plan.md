# Runtime·Deep Review 브랜치 통합 실행서

> 작성 기준: 2026-08-27
>
> 목적: 이전 대화가 없는 새 세션에서도 두 개발 브랜치를 안전하게 통합하고, 이후 병합을 fast-forward로 끝낼 수 있는 상태를 만든다.
>
> 변경 제한: 로컬 작업과 커밋까지만 허용한다. push, `main` 병합, 배포, release는 수행하지 않는다.

## 1. 작업 요청

`dryforge/bidops-agent-runtime-design`의 런타임 기능과 `bidops-deep-review`의 세 Agent 기능을 하나의 깨끗한 통합 브랜치에서 결합한다.

통합 결과는 다음 조건을 모두 만족해야 한다.

1. `app/agents/**`와 `app/screening/**`을 모두 보존한다.
2. Agent는 기존 domain/application service를 감싸는 얇은 경계로 남고, screening queue·worker·provider 로직을 복제하지 않는다.
3. 기존 REST 응답과 오류 의미, DB 정본, 불변 실행 계보, 사람 최종 판단 경계를 유지한다.
4. 양쪽에서 추가한 운영 화면과 deep-review 화면을 모두 사용할 수 있어야 한다.
5. 새 Agent REST API, Agent 전용 테이블, 범용 coordinator 저장소를 편의상 추가하지 않는다.
6. `OpportunityDiscoveryAgent`와 `BidOpsCoordinator`는 별도 승인이 없으면 구현하지 않는다.
7. 깨끗한 DB와 기존 DB 양쪽에서 migration이 일관되게 동작한다.
8. 두 원본 브랜치의 기준 커밋이 최종 통합 커밋의 조상이 되어야 한다.

폴더 이름만 미리 복제하는 방식으로 처리하지 않는다. Git은 빈 폴더를 추적하지 않으며, 충돌은 같은 파일과 계약을 양쪽에서 다르게 수정했기 때문에 발생한다. 실제 해결 대상은 파일 구조와 계약의 합집합이다.

## 2. 기준 저장소와 커밋

### 작업 위치

- Git 저장소: `/home/jechoi/orca/workspaces/side/bidops-deep-review-2`
- 프로젝트: `/home/jechoi/orca/workspaces/side/bidops-deep-review-2/bidops-agent`
- 현재 브랜치 작업 폴더: `/home/jechoi/orca/workspaces/side/bidops-deep-review-2`
- 런타임 브랜치가 체크아웃된 기존 폴더: `/home/jechoi/projects/side`

### 고정 기준

| 구분 | 브랜치 | 기준 커밋 |
|---|---|---|
| Deep Review·Agent 기능 기준 | `bidops-deep-review` | `174b2f6ee6ca90ee75523362dd676da35e421b29` |
| Screening runtime | `dryforge/bidops-agent-runtime-design` | `c336d3d8594253044f31600d8702c61ecd7b4712` |
| 공통 조상 | - | `3e076156b44d5e13a12fbf14dc733075fb8b8ab3` |

공통 조상 이후 고유 커밋은 작성 시점 기준으로 Deep Review 쪽 30개, runtime 쪽 98개다. `174b2f6`은 Agent 구현의 검증된 기능 기준이며, 이 실행서를 저장하는 문서 커밋은 그 뒤에 추가된다. 새 세션은 시작 시점의 `bidops-deep-review` HEAD를 실행 기준으로 기록하고, 다음 조건을 모두 확인한 뒤 그 정확한 commit을 merge한다.

- 실행 기준은 `174b2f6`의 후손이다.
- `174b2f6` 이후 변경은 이 실행서뿐이다.
- runtime tip은 `c336d3d`와 같다.

위 조건과 다르면 임의로 최신 tip을 사용하지 않는다. 변경된 tip과 추가 파일을 보고하고, 사용자가 새 tip 통합을 승인한 뒤 충돌 목록을 다시 계산한다.

먼저 다음을 확인한다.

```bash
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 status --short --branch
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 rev-parse bidops-deep-review
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 rev-parse dryforge/bidops-agent-runtime-design
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 diff --name-status \
  174b2f6ee6ca90ee75523362dd676da35e421b29..bidops-deep-review
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 merge-base \
  bidops-deep-review dryforge/bidops-agent-runtime-design
git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 worktree list --porcelain
git -C /home/jechoi/projects/side status --short --branch
```

## 3. 절대 보호 조건

`/home/jechoi/projects/side`에는 작성 시점 기준으로 수정·삭제·미추적 파일이 다수 존재한다. `bidops-agent`뿐 아니라 같은 저장소의 다른 프로젝트에도 사용자 작업이 있다.

따라서 다음 행위를 금지한다.

- 기존 runtime 작업 폴더에서 직접 merge 또는 rebase
- 사용자 변경의 일괄 stash
- `git clean`, `git reset --hard`, `git checkout -- .`, `git restore .`
- 삭제 파일 복구나 미추적 파일 이동을 임의로 수행
- 기존 runtime 브랜치 ref를 강제로 이동
- 사용자 파일을 통합 브랜치로 복사해 정리하려는 시도

기존 runtime 작업 폴더의 상태를 작업 전후에 읽기 전용으로 비교한다. 원래 있던 변경을 이번 통합 커밋에 포함하지 않는다.

새 통합 worktree는 기존 runtime 폴더와 분리해 만든다. 권장 이름은 다음과 같다.

```text
브랜치: integration/bidops-runtime-deep-review
worktree: /home/jechoi/orca/workspaces/side/bidops-runtime-deep-review-integration
```

같은 이름의 브랜치나 경로가 이미 있으면 삭제하거나 덮어쓰지 말고 상태를 확인해 사용자에게 보고한다.

## 4. 먼저 읽을 자료

작업자는 코드를 수정하기 전에 다음 파일을 읽는다.

1. `bidops-agent/AGENTS.md`
2. `bidops-agent/docs/standards.md`
3. `bidops-agent/docs/engineering-notes.md`
4. `bidops-agent/web/AGENTS.md`
5. `bidops-agent/web/backend/AGENTS.md`
6. `bidops-agent/web/frontend/AGENTS.md`
7. `bidops-agent/docs/worktree-agent-boundary-and-merge-direction.md`
8. `bidops-agent/docs/agent-workflow-design.md`
9. runtime 브랜치의 `bidops-agent/docs/agent-runtime.md`
10. runtime 브랜치의 `bidops-agent/docs/scheduling.md`
11. runtime 브랜치의 `bidops-agent/docs/model-quality-gate.md`

`agent-workflow-design.md`는 세 Agent의 계약과 경계를 정하는 자료다. 이것만으로 runtime 통합을 판단하지 않는다. 브랜치 소유권과 병합 방향은 `worktree-agent-boundary-and-merge-direction.md`, screening 실행·스케줄·품질 게이트는 runtime 브랜치의 세 문서를 함께 기준으로 삼는다.

## 5. 최종 폴더 구조

최종 구조는 다음 합집합을 유지한다. 아래에 없는 기존 service, router, test도 삭제하지 않는다.

```text
bidops-agent/
├── skills/
│   ├── bidops-collect/
│   ├── bidops-screen/
│   └── bidops-report/
└── web/
    ├── backend/
    │   ├── alembic/
    │   │   └── versions/
    │   ├── app/
    │   │   ├── agents/
    │   │   │   ├── common/
    │   │   │   ├── document_preparation/
    │   │   │   ├── deep_review/
    │   │   │   └── decision/
    │   │   ├── screening/
    │   │   ├── schemas/
    │   │   ├── migrations/
    │   │   ├── contracts/
    │   │   │   └── deep_review/
    │   │   ├── document_mcp/
    │   │   ├── cli/
    │   │   ├── policies/
    │   │   ├── routers/
    │   │   ├── services/
    │   │   └── workers/
    │   └── tests/
    │       ├── agents/
    │       ├── fakes/
    │       └── fixtures/
    └── frontend/
        └── src/
            └── components/
                ├── deep-review/
                ├── operations/
                ├── policies/
                └── quality/
```

구조별 소유권은 다음과 같다.

| 영역 | 보존할 책임 |
|---|---|
| `app/agents/common` | 폐쇄형 command/ref/run view, 안전 오류, 순수 projection helper |
| `app/agents/document_preparation` | 문서 묶음 준비 service를 감싸는 typed adapter와 projection |
| `app/agents/deep_review` | 심층 검토 service·worker 결과를 감싸는 typed adapter와 projection |
| `app/agents/decision` | revision·validation·final opinion을 감싸는 typed adapter와 projection |
| `app/screening` | 판정 실행, FIFO queue, worker, provider, policy, 품질 gate, artifact |
| `app/services/scheduler*` | 스케줄과 상시 운영 조정; Agent 내부로 이동하지 않음 |
| `app/schemas/` | 외부 API 스키마의 패키지 경계; 단일 `app/schemas.py`를 복원하지 않음 |
| frontend `deep-review` | 문서 준비·심층 분석·사람 판단 화면 |
| frontend `operations/policies/quality` | 판정 실행·상시 운영·정책·품질 gate 화면 |

## 6. 병합 전략

runtime 기준에서 통합 브랜치를 만들고 Deep Review 커밋을 merge한다. 98개 runtime 커밋을 rebase하거나 큰 feature 커밋을 임의 순서로 cherry-pick하지 않는다. 충돌을 한 번 해결한 merge commit을 만든다.

예상 준비 명령은 다음과 같다. 실제 실행 전 브랜치와 경로가 비어 있는지 확인한다. `deep_review_tip`에는 새 세션이 확인한 현재 브랜치의 정확한 commit을 보관한다.

```bash
deep_review_tip=$(git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 \
  rev-parse bidops-deep-review)

git -C /home/jechoi/orca/workspaces/side/bidops-deep-review-2 worktree add \
  -b integration/bidops-runtime-deep-review \
  /home/jechoi/orca/workspaces/side/bidops-runtime-deep-review-integration \
  c336d3d8594253044f31600d8702c61ecd7b4712

git -C /home/jechoi/orca/workspaces/side/bidops-runtime-deep-review-integration merge \
  --no-ff "$deep_review_tip"
```

merge가 충돌로 멈추는 것은 예상된 상태다. 모든 충돌을 해결하고 검증하기 전에는 merge commit을 만들지 않는다. 충돌 파일에 `ours` 또는 `theirs`를 파일 전체 단위로 적용하지 않는다.

merge commit이 완성되면 아래 두 명령이 모두 성공해야 한다.

```bash
git merge-base --is-ancestor bidops-deep-review HEAD
git merge-base --is-ancestor c336d3d8594253044f31600d8702c61ecd7b4712 HEAD
```

## 7. 예상 충돌과 해결 기준

작성 시점의 three-way merge 계산에서 다음 20개 파일이 실질 충돌 대상으로 확인됐다. 브랜치가 움직였다면 목록을 다시 계산한다.

### 환경·컨테이너·의존성

| 파일 | 형태 | 해결 기준 |
|---|---|---|
| `.env.example` | add/add | 문서 준비·심층 검토 환경변수와 screening·scheduler 환경변수를 모두 보존한다. 실제 secret이나 로컬 값은 넣지 않는다. |
| `web/Dockerfile` | modify/modify | Agent/deep-review 의존성과 runtime의 lock 기반 재현성, non-root 실행, 운영 entrypoint를 함께 유지한다. |
| `web/backend/pyproject.toml` | modify/modify | 양쪽 직접 의존성과 테스트 설정을 합치고 중복·상충 버전을 제거한다. |
| `web/backend/requirements.txt` | modify/modify | 양쪽 직접 의존성을 모두 반영한 뒤 runtime의 lock 생성 절차로 `requirements.lock`을 재생성한다. |

lock 파일을 손으로 이어 붙이지 않는다. Docker build가 lock 누락 또는 requirements 불일치를 탐지해야 한다.

### DB·migration·스키마

| 파일 | 형태 | 해결 기준 |
|---|---|---|
| `web/backend/alembic.ini` | add/add | 단일 Alembic 위치와 DB URL 주입 방식을 정한다. |
| `web/backend/alembic/env.py` | add/add | 통합된 metadata를 사용하고 startup에서 migration을 자동 실행하지 않는 운영 경계를 유지한다. |
| `web/backend/alembic/script.py.mako` | add/add | 통합 revision 템플릿 하나만 유지한다. |
| `web/backend/app/db.py` | modify/modify | 세션·트랜잭션·health 경계와 두 기능군의 DB 접근 요구를 모두 보존한다. |
| `web/backend/app/models.py` | modify/modify | deep-review 25개 테이블 계약과 screening runtime 테이블을 합치되 이름·FK·unique·append-only 의미를 수동 대조한다. |
| `web/backend/app/schemas.py` | modify/delete | 현재 브랜치는 이 파일을 `app/schemas/` 패키지로 분리했다. runtime의 추가 스키마를 해당 패키지에 기능별로 옮기고 단일 파일을 복원하지 않는다. |
| `web/backend/tests/test_ingest_loader.py` | modify/modify | PostgreSQL 정본 적재와 runtime 입력 계약 회귀를 모두 보존한다. |

파일 충돌이 없더라도 Alembic revision에는 의미 충돌이 있다. 현재 브랜치와 runtime 브랜치가 서로 다른 초기 revision 계보를 추가했으므로 자동 병합된 revision 파일을 그대로 인정하면 안 된다.

다음을 확인한다.

- `alembic heads`가 의도한 단일 head 또는 명시적으로 설계된 merge head만 출력하는가
- 깨끗한 PostgreSQL에서 처음부터 최신 revision까지 올라가는가
- 기존 Lean v1 DB를 runtime revision까지 올릴 수 있는가
- 기존 테이블을 두 번 만들거나 `create_all`로 migration을 우회하지 않는가
- `Run.screening_basis`가 `TEXT`로 유지되고 긴 설명이 잘리지 않는가
- upgrade 실패가 운영 DB를 자동 삭제·복구하지 않는가

### 애플리케이션 조립

| 파일 | 형태 | 해결 기준 |
|---|---|---|
| `web/backend/app/config.py` | modify/modify | 환경변수 검증을 fail-closed로 합치고 model/provider URL·credential 기본값을 위험하게 완화하지 않는다. |
| `web/backend/app/main.py` | modify/modify | 기존 deep-review router와 runtime router를 모두 등록한다. startup은 migration·seed·외부 호출을 자동 실행하지 않는다. |

`app/agents/**`는 Deep Review 브랜치 구현을 기준으로 보존한다. runtime의 queue·worker·provider 구현은 `app/screening/**`에 남긴다. Agent 폴더로 업무 로직을 복사하거나 Agent가 worker/provider를 직접 제어하게 만들지 않는다.

### 프런트엔드

| 파일 | 형태 | 해결 기준 |
|---|---|---|
| `web/frontend/src/routes.tsx` | modify/modify | deep-review 화면과 operations·policies·quality 화면의 경로를 모두 등록하고 중복 fallback을 제거한다. |
| `web/frontend/tests/api-mock.ts` | modify/modify | 양쪽 API mock을 합치되 실제 backend 응답과 다른 임의 필드를 만들지 않는다. |

Sidebar, API client, 공통 타입, 화면별 CSS, 시각 snapshot은 자동 병합됐더라도 함께 검토한다. 화면 경로가 존재하는 것만으로 완료 처리하지 말고 직접 URL 접근, 새로고침, 작은 화면, 오류·로딩·빈 상태를 확인한다.

### 문서

| 파일 | 형태 | 해결 기준 |
|---|---|---|
| `docs/architecture.md` | modify/modify | Agent 흐름과 screening runtime·scheduler 흐름을 같은 시스템 구성으로 설명한다. |
| `docs/contracts.md` | modify/modify | 기존 14개 API 의미와 runtime API 계약을 모두 보존하고 코드와 일치시킨다. |
| `docs/operations.md` | modify/modify | deep-review 실행, migration, backup, scheduler, quality gate, container 절차를 실행 순서대로 통합한다. |
| `docs/tracking/status.md` | modify/modify | T8 Agent 검증과 T14 runtime 검증을 모두 남기고 built·verified·external pending을 구분한다. |
| `docs/tracking/findings.md` | modify/modify | 양쪽의 미해결 항목만 합치고 이미 해결된 문제를 되살리지 않는다. |

문서는 한쪽 파일 전체를 선택하지 않는다. 현재 코드와 실제 검증 결과를 기준으로 문장별로 통합한다. Mock E2E 성공을 실제 Qwen 품질 승인으로 바꾸어 기록하지 않는다.

## 8. 숨은 자동 병합 영역

Git이 충돌 없이 합친 파일도 계약이 깨질 수 있다. 다음 영역은 반드시 diff를 읽는다.

- `docker-compose.yml`과 runtime별 compose override
- `web/backend/app/ingest/loader.py`
- `web/backend/app/services/pipeline.py`
- backend router 전체와 router 등록 순서
- frontend `src/lib/api.ts`, `src/lib/types.ts`, `src/main.tsx`
- frontend Sidebar와 Runs 화면
- 시각 테스트 fixture와 snapshot
- `AGENTS.md`, `CLAUDE.md`, `docs/business-rules.md`, `docs/standards.md`
- Alembic `versions/` 전체

자동 병합 성공은 의미 정합성 통과를 뜻하지 않는다.

## 9. T단위 실행 방식

모든 작업은 순차적으로 진행한다. 각 T 작업은 `codex exec`에 위임하며 모델은 Luna, reasoning effort는 max로 설정한다. 위임할 때는 해당 T에 필요한 파일·계약·검증 조건만 전달한다. 이전 작업의 전체 대화를 그대로 전달하지 않는다.

각 T가 끝날 때 주 조정자는 반드시 다음을 수행한다.

1. 해당 T의 작업 범위와 실제 diff를 대조한다.
2. 범위 밖 변경, 누락, 계약 위반, 테스트 허점을 직접 검토한다.
3. 수정이 필요하면 같은 범위에서 보완한다.
4. 관련 최소 검증과 `git diff --check`를 실행한다.
5. 추적 파일 변경이 있으면 검토 가능한 단일 커밋을 남긴다.
6. 변경이 없는 조사 단계에는 빈 커밋을 만들지 않는다.
7. 커밋이 완료된 뒤에만 다음 T로 넘어간다.

충돌 상태에서는 부분 커밋을 만들 수 없으므로 실제 merge와 모든 충돌 해결은 하나의 T로 묶는다.

### T1 — 보호 상태와 통합 작업 공간 준비

- 기준 커밋과 공통 조상을 확인한다.
- 현재 `bidops-deep-review` HEAD를 실행 기준 commit으로 기록한다.
- `174b2f6` 이후 변경이 이 실행서뿐인지 확인한다.
- 두 기존 worktree의 dirty 상태를 기록한다.
- 기존 사용자 변경을 건드리지 않는다.
- runtime 기준의 새 integration branch/worktree를 만든다.
- 시작 상태가 정확히 `c336d3d`이고 clean인지 확인한다.

완료 조건:

- 새 worktree만 생성됐다.
- 기존 두 worktree의 추적·미추적 파일에 변화가 없다.
- 추적 파일 변경이 없으므로 빈 커밋은 만들지 않는다.

### T2 — 병합과 충돌 해결

- integration branch에서 T1에 기록한 `bidops-deep-review` tip을 `--no-ff` merge한다.
- 위 20개 충돌과 modify/delete 스키마 충돌을 계약별로 해결한다.
- 자동 병합 영역도 검토한다.
- `app/agents/**`, `app/screening/**`, 분리된 `app/schemas/**`를 모두 보존한다.
- 두 Alembic 계보를 실행 가능한 하나의 migration 전략으로 만든다.
- 미해결 충돌 marker와 unmerged index가 없는지 확인한다.

완료 조건:

```bash
git status --short
git diff --check
git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- . ':!*.png'
```

- merge commit의 부모가 runtime 기준과 Deep Review 기준을 모두 포함한다.
- 커밋 메시지는 양쪽 기능을 통합했다는 의미를 명확히 남긴다.

### T3 — Backend 구조·DB 계약 검토

- models, schema package, config, DB session, main/router 등록을 양방향으로 대조한다.
- runtime REST 스키마가 분리된 schema package에서 정상 import되는지 확인한다.
- Agent mutation router가 기존 adapter를 계속 호출하는지 확인한다.
- startup이 migration, seed, external provider 호출을 암묵적으로 실행하지 않는지 확인한다.
- Alembic head, clean DB upgrade, 기존 DB upgrade를 검증한다.

수정이 있으면 별도 fix commit을 만든다.

### T4 — Screening·Agent 경계 검토

- screening orchestrator·queue·worker·scheduler·quality gate 책임이 `app/screening`과 service 경계에 남아 있는지 확인한다.
- 세 Agent가 기존 domain service를 재사용하고 정본을 복제하지 않는지 확인한다.
- projection 조회가 DB write, UUID 생성, 현재 시각 생성, 새 audit row 생성을 하지 않는지 확인한다.
- provider URL, credential, object key, raw prompt/model output이 Agent 외부 계약과 감사 metadata에 노출되지 않는지 확인한다.
- `OpportunityDiscoveryAgent`, coordinator, Agent 전용 persistence가 추가되지 않았는지 확인한다.

수정이 있으면 별도 fix commit을 만든다.

### T5 — Frontend 통합

- deep-review, operations, policies, quality, runs 화면과 route를 모두 보존한다.
- API client와 타입이 backend 계약과 일치하는지 확인한다.
- polling 취소, stale response 무시, optimistic conflict, loading/error/empty 상태를 회귀 검토한다.
- 직접 URL, 새로고침, desktop·tablet·mobile 화면을 확인한다.
- 시각 snapshot은 네트워크 폰트에 의존하지 않아야 한다.

수정이 있으면 별도 frontend fix commit을 만든다.

### T6 — 문서 정합성

- 통합된 구조·API·운영 절차·현재 상태를 문서에 반영한다.
- 기준 HEAD가 오래된 문서는 실제 통합 commit과 검증 결과로 갱신한다.
- Agent Mock E2E와 runtime fake/container 검증을 실제 모델 품질 승인과 구분한다.
- 완료된 문제는 findings에서 제거하고 외부 승인이 필요한 항목만 남긴다.
- `CLAUDE.md`와 `AGENTS.md`가 동일한지 확인한다.

수정이 있으면 문서 전용 커밋을 만든다.

### T7 — 전체 검증

아래 검증을 깨끗한 integration worktree에서 실행한다. 기존 운영 Compose project와 volume을 재사용하지 않는다.

```bash
git diff --check
./bidops-agent/run-tests.sh
./bidops-agent/web/run-web-tests.sh
```

추가로 프로젝트 운영 문서의 현재 명령에 따라 다음을 검증한다.

- backend 전체 pytest
- frontend production build
- Docker Compose configuration
- lock 기반 Docker build
- 깨끗한 PostgreSQL migration
- 기존 Lean v1 상태에서 최신 migration
- screening runtime의 deterministic fake 통합 테스트
- 세 Agent의 isolated deterministic Mock E2E
- 종료 시 active work job 0건과 임시 격리 자원 정리

실제 Qwen/Ollama 호출, OpenAI 전송, scheduler 활성화, policy activation, 운영 DB 변경은 별도 사용자 승인 없이는 수행하지 않는다. 해당 검증은 pending으로 정확히 보고하며 fake/mock 성공으로 대체하지 않는다.

테스트 실패가 통합 결함이면 수정하고 검증 fix commit을 만든다. 환경·권한·외부 서비스 때문에 실행할 수 없으면 성공으로 기록하지 말고 조건과 영향을 보고한다.

### T8 — 최종 독립 리뷰와 브랜치 정렬 준비

- 전체 integration diff를 공통 조상과 양쪽 부모 기준으로 각각 검토한다.
- 양쪽 브랜치의 기능이 누락됐는지 확인한다.
- 충돌 해결 과정에서 임의 기본값, API 완화, migration 우회가 들어갔는지 확인한다.
- 전체 테스트 결과와 남은 외부 gate를 대조한다.
- 수정이 필요하면 고친 뒤 최종 fix commit과 관련 검증을 남긴다.
- push, `main` merge, release는 하지 않는다.

최종 ancestry 확인:

```bash
git merge-base --is-ancestor bidops-deep-review HEAD
git merge-base --is-ancestor c336d3d8594253044f31600d8702c61ecd7b4712 HEAD
git status --short --branch
```

## 10. 원본 브랜치 정렬

통합 브랜치가 검증되면 `bidops-deep-review`는 통합 커밋의 조상이므로 통합 브랜치를 받아들일 때 추가 코드 충돌이 없어야 한다.

그러나 `dryforge/bidops-agent-runtime-design`은 `/home/jechoi/projects/side`의 dirty worktree에서 체크아웃되어 있다. 사용자 변경을 먼저 보호하지 않고 원본 runtime 브랜치를 갱신하지 않는다.

다음 중 하나를 사용자가 명시적으로 선택해야 한다.

1. 기존 dirty 변경을 사용자가 별도 브랜치에 커밋한 뒤 runtime 브랜치를 integration commit으로 fast-forward한다.
2. 기존 dirty 변경의 소유권과 처리 방향을 사용자가 지정한 뒤 안전하게 분리한다.
3. 원본 runtime 브랜치는 그대로 두고 검증된 integration branch를 최종 통합 대상으로 사용한다.

원본 runtime 브랜치가 안전하게 integration commit을 가리키게 된 뒤에만 현재 브랜치에서 다음 형태의 확인을 수행한다.

```bash
git merge --ff-only dryforge/bidops-agent-runtime-design
```

이 명령 실행 자체도 현재 브랜치를 이동하므로 최종 승인 전에는 실행하지 않는다. 두 브랜치 중 하나라도 통합 이후 새 커밋을 받으면 fast-forward 보장은 사라지므로 ancestry와 merge-tree를 다시 확인한다.

## 11. 중단 조건

다음 상황에서는 추측으로 진행하지 말고 즉시 사용자에게 보고한다.

- 기존 dirty 파일을 수정·이동·삭제해야만 다음 단계가 가능한 경우
- 기준 branch tip이 기록된 commit과 달라진 경우
- clean DB와 기존 DB를 모두 지원하는 migration 순서를 결정할 근거가 없는 경우
- 기존 REST 의미를 유지하면서 runtime 기능을 연결할 수 없는 경우
- 새 public API나 새 Agent persistence 없이는 통합할 수 없다고 판단되는 경우
- Agent가 screening 내부 worker/provider를 직접 제어해야만 하는 경우
- 실제 external model 호출이나 운영 credential 없이는 필수 검증을 통과시킬 수 없는 경우
- 시각 snapshot 변경을 사람이 판단해야 하는 경우
- 테스트 실패가 기존 결함인지 통합 회귀인지 코드와 이력만으로 구분되지 않는 경우

중단 보고에는 영향 파일, 깨지는 계약, 이미 확인한 근거, 가능한 선택지를 포함한다.

## 12. 최종 보고 형식

최종 보고에는 다음을 빠짐없이 포함한다.

1. integration branch와 최종 commit
2. merge commit의 두 부모
3. T별 commit 목록
4. 20개 예상 충돌의 실제 처리 결과
5. 자동 병합됐지만 수동 검토한 핵심 파일
6. 최종 폴더 구조와 양쪽 기능 보존 여부
7. DB migration 전략과 clean/existing DB 검증 결과
8. backend, frontend, container, deterministic E2E의 명령과 정확한 결과
9. 실행하지 않은 live·운영 검증과 그 이유
10. 기존 `/home/jechoi/projects/side` 사용자 변경을 건드리지 않았다는 확인
11. 원본 runtime 브랜치 fast-forward 가능 여부
12. push·`main` merge·release를 수행하지 않았다는 확인

완료의 기준은 “충돌 marker가 없다”가 아니라, 두 브랜치의 계약과 기능을 모두 보존한 통합 commit이 재현 가능한 검증을 통과하고 양쪽 기준 commit을 조상으로 포함하는 것이다.
