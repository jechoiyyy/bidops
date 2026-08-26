# HANDOFF — Mock 기준 전체 워크플로우 Web UI 완성

기준일: 2026-08-26
현재 브랜치: `bidops-deep-review`
작업 디렉터리: `bidops-agent/`
다음 작업의 1순위: **문서 준비부터 심층 검토 완료까지 브라우저만으로 실행 가능한 Web UI 만들기**

## 0. 가장 먼저 알아야 할 결론

백엔드 전체 흐름은 실제 PostgreSQL·MinIO·ClamAV·worker와 결정론적 Mock 분석 provider를
사용한 E2E에서 통과했다.

```text
문서 업로드
→ 안전 검사·구조화
→ ready bundle
→ Stage 1/2/3
→ machine report + validation
→ evidence 조회
→ human full revision + revalidation
→ final opinion
→ 새 첨부
→ 새 bundle/review
→ 이전 결과 보존
```

하지만 이 전체 흐름을 Web UI만으로 실행할 수 있는 상태는 아니다.

- 보고서 조회, evidence, revision, final opinion UI: 구현됨
- ready bundle을 이용한 deep review 시작 UI: 구현됨
- bundle 생성, 파일 업로드, metadata 확인, ready 확정 UI: **없음**
- 분석 진행 자동 갱신과 실패 attempt 재시도 UI: **없거나 불완전**
- 새 첨부를 등록해 새 bundle/review로 이어지는 UI: **없음**

다음 작업은 Qwen 품질 조정이 아니다. **LLM은 계속 Mock으로 두고 Web UI의 전체 구동 방식을
먼저 완성한다.**

## 1. 작업 범위와 금지사항

### 이번 작업에 포함

1. 공고 상세 화면에서 새 document bundle 생성
2. HWP/HWPX/PDF/이미지 업로드
3. 문서별 안전·구조화 상태와 blocking issue 표시
4. 역할, 효력일, 대체 문서, 현재본 metadata 편집
5. optimistic concurrency를 지키는 `문서 준비 완료` 확정
6. ready bundle로 deep review 생성
7. queued/running 상태와 3개 stage를 polling으로 갱신
8. 실패한 review의 새 attempt 실행
9. 기존 보고서·evidence·revision·final opinion UI 회귀
10. 새 첨부 이후 새 bundle/review 생성과 이전 결과 보존 확인

### 이번 작업에서 제외

- 실제 Qwen 또는 Codex 호출
- Qwen prompt/품질 튜닝과 55개 fixture 점수 승인
- SQLite 운영 이관, 복구 훈련, RPO/RTO 검증
- provider 선택 관리 UI
- profile/policy 관리 UI
- 새 API 계약의 임의 추가
- Git commit, push, PR, merge

Mock 결과의 `조건부 추진 검토`는 고정 fixture다. 실제 사업 판단이나 모델 품질 승인으로
표현하면 안 된다.

### 반드시 지킬 안전 경계

- 운영 DB와 운영 object storage를 테스트에 사용하지 않는다.
- `.env`, secret, 원문 bytes, 내부 object key를 UI·로그·fixture에 넣지 않는다.
- 모든 mutation에서 `X-BidOps-Actor-Name`을 요구한다. 이 값은 인증된 사용자로 표현하지 않는다.
- `request_id`가 필요한 mutation은 매 사용자 동작마다 `crypto.randomUUID()`로 만든다.
- document와 bundle의 `version`을 그대로 전송하고 `409 version_conflict`를 사용자에게 표시한다.
- quarantine/blocked 파일을 viewer나 분석으로 우회 전달하지 않는다.
- 기존 report/revision/final opinion을 덮어쓰지 않는다.
- 현재 dirty worktree에는 사용자의 기존 변경이 섞여 있다. `git reset`, `git checkout --`, 광범위한
  정리나 관련 없는 파일 복구를 하지 않는다.

## 2. 권위 문서와 읽는 순서

작업 전 아래 순서로 확인한다.

1. `AGENTS.md`
2. `web/AGENTS.md`
3. `web/frontend/AGENTS.md`
4. `docs/standards.md`
5. `docs/engineering-notes.md`
6. `docs/business-rules.md`
7. `docs/security.md`
8. `docs/contracts.md`
9. `.dryforge/spec.md`의 §4.5, §4.7, §4.9, §7, §8, §13, §16, §17

심층 검토 구현의 권위 계약은 `.dryforge/spec.md`와 `docs/deep-review-erd.md`다. REST 응답 필드를
프론트 편의를 위해 임의로 추가하지 않는다.

## 3. 현재 구현 상태

### Backend / runtime

- 분석 provider 선택 경계:
  - `vllm`: 운영 목표
  - `codex-exec`: 승인된 reference 전용
  - `mock`: 현재 전체 워크플로우 테스트 전용
- Mock 구현: `web/backend/app/services/mock_analysis_client.py`
- Mock Compose override: `docker-compose.t7.mock-reference.yml`
- B→C 인수 실행기: `web/backend/app/services/bc_e2e.py`
- 실행 CLI: `web/backend/app/cli/run_bc_e2e.py`
- document/report/final opinion API는 `.dryforge/spec.md` §17의 14개 endpoint로 구현되어 있다.
- worker의 잘못된 web HTTP healthcheck 상속은 Compose에서 비활성화했다.

### Frontend에 이미 있는 것

- 라우트: `/deep-reviews/:deepReviewId`
- 공고 상세에서 ready bundle을 찾고 deep review 시작
- review/attempt/stage 상태 표시
- 13개 report section과 decision card 표시
- validation/unknown 표시
- evidence quote, locator, page/block/bbox 표시
- immutable full report revision 편집·저장
- revision history 표시
- final opinion append 및 validation 실패 acknowledgement

주요 파일:

- `web/frontend/src/pages/NoticeDetailPage.tsx`
- `web/frontend/src/pages/DeepReviewPage.tsx`
- `web/frontend/src/components/deep-review/api.ts`
- `web/frontend/src/components/deep-review/types.ts`
- `web/frontend/tests/deep-review.spec.ts`
- `web/frontend/tests/api-mock.ts`

### Frontend에 없는 것

`web/frontend/src/components/deep-review/api.ts`에는 현재 다음 호출만 있다.

- document bundle 목록 조회
- deep review 생성/조회
- report/evidence 조회
- revision/final opinion 저장

다음 API wrapper와 UI가 없다.

- bundle 생성
- multipart 문서 업로드
- document version metadata patch
- bundle confirm
- deep review attempt 생성
- document structure/page 조회

또한 `DeepReviewPage`는 running review를 안정적으로 polling하지 않는다. report를 review 완료 전부터
조회해 `409 review_not_ready`를 받을 수 있고, review가 완료된 뒤 report query가 자동으로 다시
활성화된다는 보장이 없다.

## 4. 현재 Mock E2E 기준선

상세 증적: `docs/mock-workflow-e2e-result.md`
전체 흐름 HTML: `docs/e2e-flow-overview.html`
실행 runbook: `docs/e2e-bc-acceptance.md`

최초 성공 계보:

- ready bundle: `de013c3c-a9a6-4f93-bc06-2c75684e2e9b`
- deep review: `773b7750-dfda-4390-b583-918edf298489`
- machine revision: `c9094337-cdf0-40f0-9f35-556b37cbb55a`
- human revision: `f9c4f21b-909e-46ff-903a-f7ed8ded338b`
- final opinion: `6f5b8210-b61f-4ba1-9d32-d51690b5fbed`
- evidence 조회 확인: 91건

새 첨부 이후 계보:

- ready bundle: `020c2020-e773-470e-a21a-97f42cb97352`
- deep review: `be147c78-f9e1-4c64-bf43-1bd317960216`
- 상태/validation: `completed` / `passed`
- 이전 review의 machine/human revision과 final opinion 보존 확인

Provider lineage:

```text
analysis_provider = mock-analysis
runtime_model = bidops-deterministic-mock-v1
policy_quality.status = reference_workflow_unmeasured
policy_quality.deployable = false
OpenAI/Codex = disabled
```

현재 격리 Compose project는 `bidops-step-r26bk01680717`이다. secret이 포함된 임시 env 파일의
내용을 출력하거나 커밋하지 않는다. 마지막 확인 시 queued/running `work_job`은 0개였다.

## 5. 다음 구현 순서

### Step 1 — TypeScript API 계약 완성

수정 대상:

- `web/frontend/src/components/deep-review/types.ts`
- `web/frontend/src/components/deep-review/api.ts`

추가할 함수:

```text
createDocumentBundle(noticeId, actorName)
uploadDocument(bundleId, file, actorName)
patchDocumentVersion(documentVersionId, actorName, payload)
confirmDocumentBundle(bundleId, actorName, payload)
createDeepReviewAttempt(deepReviewId, actorName)
```

정확 endpoint와 request shape:

| 동작 | Endpoint | Request 핵심 |
|---|---|---|
| bundle 생성 | `POST /api/notices/{notice_id}/document-bundles` | `{}` + actor header |
| 문서 업로드 | `POST /api/document-bundles/{bundle_id}/documents` | multipart `file`, `request_id` + actor header |
| metadata 수정 | `PATCH /api/document-versions/{id}` | `role`, `effective_date`, `replaces_document_version_id`, `is_current`, `version` |
| ready 확정 | `POST /api/document-bundles/{id}/confirm` | `request_id`, bundle `version`, 모든 `confirmed_documents[{document_version_id,version}]` |
| attempt 재시도 | `POST /api/deep-reviews/{id}/attempts` | `request_id` + actor header |

`any`를 사용하지 말고 backend Pydantic schema와 같은 closed enum/type을 선언한다. multipart 요청에서는
`Content-Type`을 직접 지정하지 말고 브라우저가 boundary를 만들게 한다.

document structure/page 조회 endpoint도 존재하지만 현재 `BundleView.DocumentVersionView`에는
`structure_id`가 없다. 문서 준비 UI에서 구조 원문 preview까지 제공하려고 응답 필드를 임의 추가하지
않는다. P0에서는 `structure_status`와 issue locator를 표시하고, 별도 preview 계약이 필요하면 승인부터
받는다.

### Step 2 — Document preparation UI

권장 구조:

```text
web/frontend/src/components/deep-review/DocumentPreparationPanel.tsx
web/frontend/src/components/deep-review/DocumentVersionEditor.tsx
```

`NoticeDetailPage`의 현재 “심층 검토” section을 다음 상태 기계로 확장한다.

```text
bundle 없음
→ 새 bundle 생성
→ draft/processing
→ 파일 업로드
→ safety/structure polling
→ needs_review이면 metadata와 issue 확인
→ blocking issue가 없을 때 ready confirm
→ deep review 시작
```

필수 표시:

- bundle revision/version/status
- 각 document의 filename, role, version, safety status, structure status
- effective date, replaces document, is_current
- issue severity, blocking 여부, 안전한 message와 locator
- upload/patch/confirm mutation의 loading/error/success
- `version_conflict` 시 목록 재조회 안내
- blocked/quarantined/failed 문서가 있으면 confirm 버튼 비활성화
- actor claimed name 입력과 “인증된 사용자 아님” 설명

파일 upload 직후 곧바로 ready로 간주하지 않는다. document worker가 상태를 바꿀 때까지 bundle query를
polling한다. 현재 bundle version과 document version을 confirm payload에 그대로 사용한다.

### Step 3 — Review 진행 polling과 retry

수정 대상:

- `web/frontend/src/pages/DeepReviewPage.tsx`
- `web/frontend/src/components/deep-review/api.ts`

요구 동작:

- review가 `queued|running`이면 review query를 짧은 간격으로 polling
- report query는 review가 `completed`일 때 활성화
- review 완료 시 report query invalidate/refetch
- review가 `failed`이고 active attempt가 없으면 actor name과 함께 “새 attempt” 버튼 제공
- `active_attempt_exists`, `review_not_ready`, `processing_failed`를 stable code 기준으로 표시
- retry 성공 후 attempt sequence와 3개 stage 상태가 자동 갱신

현재 API error class는 status와 message만 보존한다. UI가 stable code로 분기해야 한다면
`DeepReviewApiError`에 응답 `error.code`를 추가하되 backend response 계약은 바꾸지 않는다.

### Step 4 — 기존 report mutation 회귀 보강

기존 UI는 구현되어 있지만 Playwright는 화면 접근성/overflow 한 건만 확인한다. 다음 mutation을
fixture API에서 실제로 검증한다.

- evidence 버튼 → quote/page projection 표시
- full revision 저장 → request shape와 actor header 확인 → history 증가
- factual body 변경 시 evidence ID 누락 오류 표시
- final opinion append → 최신 revision/validation ID 전송
- validation failed일 때 acknowledgement 전에는 버튼 비활성화
- failed review의 attempt retry

### Step 5 — 새 첨부와 새 계보

성공 report가 있는 공고에서 새 bundle을 만들고 파일을 등록한다.

- 이전 ready bundle/report를 수정하지 않는다.
- 같은 bytes라도 새 manual document version이 생성되는 동작을 허용한다.
- 새 ready bundle로 생성한 review ID가 이전 review와 달라야 한다.
- 이전 report URL에서 machine/human history와 final opinion을 계속 조회할 수 있어야 한다.
- 새 review에 이전 사람 revision/final opinion을 자동 복사하지 않는다.

현재 exact API에는 공고별 deep review 목록 endpoint가 없다. 과거 review를 영구적으로 탐색하는 UI가
필요하다면 새 endpoint를 즉시 만들지 말고 먼저 API 계약 변경 승인을 받는다. 이번 P0에서는 이전 URL의
조회 가능성과 새 review의 독립성을 검증하면 된다.

## 6. Web UI 완료 기준

아래 항목을 모두 충족해야 “전체 워크플로우 Web UI 구현 완료”로 보고한다.

- [ ] `우선 검토` 공고에서 브라우저로 새 bundle을 만들 수 있다.
- [ ] 브라우저로 대표 PDF/HWP를 업로드할 수 있다.
- [ ] safety/structure 상태와 blocking issue가 자동 갱신된다.
- [ ] 역할·효력일·대체·현재본 metadata를 version과 함께 수정할 수 있다.
- [ ] unsafe/failed/blocking 상태에서는 ready confirm이 불가능하다.
- [ ] 정상 문서 전체를 version과 함께 confirm해 ready bundle을 만들 수 있다.
- [ ] ready bundle로 deep review를 생성하고 해당 report route로 이동한다.
- [ ] queued/running review와 Stage 1/2/3 상태가 새로고침 없이 갱신된다.
- [ ] 실패 review에서 새 attempt를 실행할 수 있다.
- [ ] machine report와 validation을 조회할 수 있다.
- [ ] evidence quote와 source page/block을 조회할 수 있다.
- [ ] human full revision을 저장하고 새 validation/history를 확인할 수 있다.
- [ ] final opinion을 최신 revision/validation에 기록할 수 있다.
- [ ] 새 첨부 이후 새 bundle/review가 생성되고 이전 결과가 보존된다.
- [ ] 실제 Qwen/Codex 호출이 한 번도 발생하지 않는다.

## 7. 테스트 계획

### Frontend 기능 테스트

`web/frontend/tests/api-mock.ts`를 확장하고 최소 다음 Playwright 흐름을 추가한다.

1. bundle 없음 → 생성
2. multipart upload → processing 표시
3. polling 후 safe/structure ready 표시
4. metadata patch와 version 증가
5. blocking issue일 때 confirm 차단
6. confirm 성공 후 deep review 시작
7. running stage polling → report 활성화
8. failed attempt retry
9. evidence/revision/final opinion mutation
10. 좁은 화면과 긴 한글 filename/matrix overflow

실행:

```bash
cd web/frontend
npm run build
npx playwright test tests/deep-review.spec.ts
```

새 spec 파일을 만들었다면 해당 파일도 명시적으로 실행한다. 기존 28개 이미지 snapshot은 실행 환경의
한글 글꼴 차이로 흔들릴 수 있다. 기능 assertion 실패와 font snapshot diff를 구분하고, 사람이 이미지를
검토하기 전에는 기준선을 갱신하지 않는다.

### Backend 회귀

마지막 통과 기준:

```text
296 passed, 4 skipped
```

skip 4개는 별도 isolated T7 MinIO opt-in이 필요한 테스트다. 실제 Mock E2E에서는 MinIO를 사용해
전체 흐름을 별도로 통과했다.

의존성이 설치된 현재 Docker image를 이용한 재현 예:

```bash
docker run --rm \
  -v "$PWD:/workspace:ro" \
  -w /workspace/web/backend \
  bidops-step-r26bk01680717-web \
  pytest -q tests
```

최종 검사:

```bash
git diff --check
cd web/frontend && npm run build
```

UI 핵심 흐름 변경이므로 관련 Playwright 테스트 없이 완료 처리하지 않는다.

## 8. 격리 환경 사용 시 주의

- Compose project: `bidops-step-r26bk01680717`
- Mock override: `docker-compose.t7.mock-reference.yml`
- active profile ID: `947cad43-e225-4876-aff7-96caa10f1faf`
- active policy ID: `b2cc10f7-6eef-4208-9de1-561fb131f64c`
- 마지막 확인 시 web은 healthy, document/analysis worker는 실행 중, active job은 0개였다.
- worker는 HTTP server가 없으므로 shared web image healthcheck를 비활성화한 상태가 정상이다.
- 인수 CLI는 web 컨테이너 network namespace의 `127.0.0.1:8787`을 사용했다.
- host port 노출은 환경별로 다를 수 있으므로 `docker port` 또는 Compose config로 먼저 확인한다.
- 임시 env 파일에는 secret이 있으므로 내용을 출력·복사·커밋하지 않는다.

Mock 모드의 필수 설정은 다음 의미를 유지해야 한다.

```text
BIDOPS_ANALYSIS_PROVIDER=mock
BIDOPS_REFERENCE_WORKFLOW_MODE=true
BIDOPS_OPENAI_ENABLED=false
BIDOPS_CODEX_EXEC_ENABLED=false
```

기존 Mock review를 vLLM attempt로 재사용하지 않는다. provider/model lineage가 다르면 새 bundle 또는
새 policy version의 새 review가 필요하다.

## 9. 알려진 함정

1. Stage 2 company profile row 중 정상적인 단일 fact가 2KB를 넘는다. 현재 profile budget은 4KB,
   Stage 2 document budget은 15KB다. 다시 2KB로 줄이지 않는다.
2. Mock은 schema-valid 최소 흐름을 만든다. claim 수나 recommendation을 품질 결과로 해석하지 않는다.
3. report GET은 read-only다. 화면 조회로 machine revision을 생성하려 하면 안 된다.
4. report revision은 delta가 아니라 전체 snapshot이다.
5. factual body 변경에는 같은 review 범위의 evidence ID가 필요하다.
6. final opinion은 실제 revision ID와 validation run ID를 함께 고정한다.
7. validation 실패 opinion은 acknowledgement와 reason이 필요하며 실패 label을 유지한다.
8. 새 파일은 기존 bundle row를 수정하는 것이 아니라 새 bundle을 만든다.
9. manual upload는 filename/URL로 deduplicate하지 않는다. 같은 bytes는 content object만 재사용한다.
10. document processor와 Mock/Qwen에 DB/storage credential 또는 임의 path/URL을 넘기지 않는다.

## 10. Git 상태

현재 worktree는 의도적으로 dirty하며 이번 심층 검토 작업과 그 이전 사용자 변경이 함께 있다.

- tracked 수정/삭제 다수
- Mock/vLLM/Codex adapter, E2E runner, 문서 등 untracked 파일 다수
- 아직 commit/push/PR 없음
- `docs/deep-review-cold-session-handoff.md`와 `web/backend/app/services/ollama_client.py`는 삭제 상태다.
  이유를 확인하지 않고 복원하지 않는다.

작업 시작과 종료 시 반드시 다음을 확인한다.

```bash
git status --short
git diff --check
```

관련 없는 사용자 변경을 정리하거나 하나의 commit으로 임의 묶지 않는다.

## 11. 다음 작업자의 첫 행동

1. 이 문서와 §2의 권위 문서를 읽는다.
2. `git status --short`로 현재 변경을 보존한다.
3. `NoticeDetailPage`, `DeepReviewPage`, frontend deep-review API/types를 읽는다.
4. Step 1의 API wrapper와 strict TypeScript types부터 추가한다.
5. `DocumentPreparationPanel`을 작은 상태 단위로 구현한다.
6. API mock과 Playwright 기능 테스트를 구현과 동시에 추가한다.
7. Mock Compose에서 브라우저 전체 흐름을 실제 backend에 한 번 연결한다.
8. Qwen/Codex를 호출하지 않았음을 provider audit와 환경 설정으로 확인한다.

완료 보고에는 구현 파일, 브라우저로 재현한 상태 전이, 새 bundle/review ID, 이전 결과 보존 여부,
backend/frontend/Playwright 테스트 수, 남은 UI 제약을 포함한다.
