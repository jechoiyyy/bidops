# Mock 전체 워크플로우 E2E 결과

Mock 결과는 워크플로우 상태 전이와 저장·검증 경계의 증적이다. 고정 claim과 권고는
Qwen 품질 또는 실제 사업 판단을 승인하지 않는다.

## 2026-08-27 Agent 연속 E2E

- 격리 Compose project: `bidops-agent-e2e-20260827-a`
- Compose: `docker-compose.t7.yml` + `docker-compose.t7.mock-reference.yml`
- 실제 구성: PostgreSQL, MinIO, ClamAV, document worker 2개, analysis worker, web
- 입력: 격리 DB의 synthetic notice `1`, 저장소의 `safe.pdf` fixture 1개
- provider/model: `mock-analysis` / `bidops-deterministic-mock-v1`
- OpenAI/Codex/Qwen 외부 호출: 0건
- 종료 시 queued/running WorkJob: 0건
- 결과: `bidops.t7-e2e-result.v1`, `passed=true`
- 종료 후 격리 container, network, volume을 모두 제거했다.

첫 흐름은 ready bundle `803bb7b4-10b7-4b9c-82ea-9484748f9de1`, deep review
`3bc330ca-0dcf-41a3-b8c6-d252a5f77701`, lineage
`d8244718-106b-464f-aff2-03e4f0d5cce6`으로 완료됐다. Machine validation과 human
full revision 재검증은 모두 `passed`였고 final opinion
`1b925a34-b83a-4031-ab93-4e05d174d145`가 append-only history에 남았다.

두 번째 업로드는 새 ready bundle `7858ea7b-df19-408b-a5d0-af127ab9f151`, 새 deep
review `97d97bcf-7b43-423b-816b-04eeaeec7172`, 새 lineage
`41e12b7a-12a1-4709-a555-0500ade624e3`을 만들었다. 첫 bundle projection은
`superseded`로 바뀌었지만 첫 attempt, machine/human revision 두 개와 final opinion ID는
그대로 보존됐다. 각 checkpoint에서 다음 projection 계약을 확인했다.

| Checkpoint | DocumentPreparationAgent | DeepReviewAgent | DecisionAgent |
|---|---|---|---|
| 첫 machine report | `completed` / `ready_bundle` | `completed` / `report_ready_validated` | `waiting_human` / report review |
| human full revision | `completed` | `completed` | `waiting_human` / final opinion |
| final opinion | `completed` | `completed` | `completed` / `final_opinion_recorded` |
| 두 번째 ready 이후 첫 흐름 | `superseded` / `superseded_by_new_bundle` | `completed` | `completed` |
| 두 번째 machine report | `completed` / `ready_bundle` | `completed` / `report_ready_validated` | `waiting_human` / report review |

각 projection의 run ID, status, current step, outcome, input/output refs, correlation lineage,
wait reason, available actions도 persisted DB snapshot에서 assertion했다. 각 review의 stage
invocation metadata는 모두 같은 mock provider/model이었으며 review별 mock invocation은
14건이었다.

T7 실행기는 Agent projection을 DB에서 직접 읽으므로 별도 runner container가 아니라 격리
project의 실행 중인 web container 안에서 실행한다. Manifest의 `api_base`는 그 container의
loopback 주소여야 하고 actor fixture는 HTTP header로 전송 가능한 ASCII 이름을 사용한다.

```text
docker exec <isolated-web-container> \
  python -m app.cli.run_bc_e2e /tmp/t7-manifest.json \
  --t7 --confirm-target http://127.0.0.1:8787 \
  --output /tmp/t7-result.json
```

`bidops.t7-e2e-result.v1`은 두 흐름의 bundle/review/attempt/revision/opinion ID, 전체 Agent
projection, bundle 및 append-only history, provider/model audit, active WorkJob 수를 포함한다.
`mock_quality.evaluated`는 항상 `false`다.

## 2026-08-26 기존 B→C E2E

- 격리 Compose project: `bidops-step-r26bk01680717`
- 대상 공고: 내부 notice `1` / 공고번호 `R26BK01680717`
- 분석 provider/model: `mock-analysis` / `bidops-deterministic-mock-v1`
- policy quality: `reference_workflow_unmeasured`, `deployable=false`
- OpenAI/Codex: 비활성

### 최초 성공 계보

- ready bundle: `de013c3c-a9a6-4f93-bc06-2c75684e2e9b` (revision 9, 문서 2개)
- deep review: `773b7750-dfda-4390-b583-918edf298489`
- machine revision: `c9094337-cdf0-40f0-9f35-556b37cbb55a`
- machine validation: `7e91e8e3-3241-4acb-a3e1-d60e70f78194` / `passed`
- 원문 이동 확인 evidence: 91건

| Stage | 상태 | claim | evidence | invocation slice |
|---|---:|---:|---:|---:|
| requirements_and_evaluation | completed | 31 | 31 | 14 |
| delivery_risk_economics | completed | 60 | 60 | 23 |
| synthesis_and_validation | completed | 9 | 0 | 9 |

사람 mutation도 실제 API로 수행했다.

- human full revision: `f9c4f21b-909e-46ff-903a-f7ed8ded338b`
- human validation: `0f1e9d01-6c35-4e6f-9408-9f8894eeb167` / `passed`
- revision history: machine → human, 총 2개
- final opinion: `6f5b8210-b61f-4ba1-9d32-d51690b5fbed` / `조건부 추진`

새 첨부 이후 새 ready bundle `020c2020-e773-470e-a21a-97f42cb97352`와 deep review
`be147c78-f9e1-4c64-bf43-1bd317960216`가 생성됐다. 이전 review의 human revision과 final
opinion은 보존됐고 새 review에는 자동 승계되지 않았다.

당시 자동 회귀는 backend `296 passed, 4 skipped`, Mock·분석·보고서·B→C 집중 회귀
`96 passed`였다. 테스트 중 정상 회사 profile fact의 2KB 초과를 거부하던 Stage 2 입력 조립기를
보정했고, 대표 입력의 최대 prompt 19,006자는 24,000자 상한 안에 남았다.

실제 Qwen 전환은 Mock override를 제거하고 승인된 vLLM/Qwen provider로 새 review를 만든 뒤
55개 fixture의 재현율, 사람 일치율, 근거 부족 오판율과 timeout/잘린 JSON 재시도를 별도로
측정해야 한다.
