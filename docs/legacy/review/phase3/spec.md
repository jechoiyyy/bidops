# Phase 3 변경 명세

[plan.md](./plan.md)의 각 작업이 만들어야 하는 파일별 결과와 완료 기준이다. 작업자는 해당
절의 범위만 구현하고, 명시되지 않은 백엔드·DB·compose·pipeline 파일을 수정하지 않는다.

공통 규칙:

- API 응답을 프런트에서 재판정하거나 누락값을 추정하지 않는다.
- mutation은 `X-BidOps-Actor-Name` claimed-name 경계를 통과하고, 비ASCII 이름은 서버 계약의
  `utf-8-percent-v1` envelope로 전송한다. 이름을 로그인·인증으로 표현하지 않는다.
- 오류 `detail` 문자열로 분기하지 않는다. Lean 오류의 구조화 `error.code`와 HTTP status만 쓴다.
- request ID는 mutation 한 번마다 `crypto.randomUUID()`로 만들고 재렌더마다 바꾸지 않는다.
- upload는 `FormData`를 사용하며 브라우저가 multipart boundary를 정하도록 `Content-Type`을
  직접 지정하지 않는다.
- ready/superseded bundle, 완료 stage/report/revision/final opinion을 덮어쓰지 않는다.
- 커밋과 git 이력 조작을 하지 않는다.

---

## T5 — 프런트 Lean API·타입 계약 완성

### T5-1 `web/frontend/src/components/deep-review/types.ts`

백엔드 `schemas/document_bundles.py`와 `routers/deep_reviews.py`의 명명된 응답을 그대로 표현한다.

1. 문서 역할을 다음 union으로 정의한다.
   `공고 | 정정 | 제안요청서 | 과업지시서 | 내역서 | 제출서식 | 부록 | 기타`.
2. `safety_status`, `structure_status`, bundle issue의 severity/locator를 명시적 union/interface로
   만든다. 기존 `string`/inline issue를 이 타입으로 교체한다.
3. `DocumentStructure`, `DocumentStructurePageView`, page metadata, extractor, block 타입을
   백엔드 필드와 nullable 의미 그대로 추가한다. `structure_id`를 `DocumentVersionView`에
   추정해서 추가하지 않는다.
4. 문서 patch payload와 bundle confirm payload 타입을 추가한다. confirm은 현재 bundle
   `version`과 모든 `confirmed_documents[{document_version_id,version}]`를 가진다.
5. retry 응답은 기존 `AttemptView`를 재사용한다.

### T5-2 `web/frontend/src/components/deep-review/api.ts`

다음 함수를 추가한다.

| 함수 | 호출 |
|---|---|
| `createDocumentBundle` | `POST /notices/{noticeId}/document-bundles`, body `{}` |
| `uploadDocument` | `POST /document-bundles/{bundleId}/documents`, multipart `file`, `request_id` |
| `patchDocumentVersion` | `PATCH /document-versions/{documentVersionId}` |
| `confirmDocumentBundle` | `POST /document-bundles/{bundleId}/confirm` |
| `getDocumentStructure` | `GET /document-structures/{structureId}` |
| `getDocumentStructurePage` | `GET /document-structures/{structureId}/pages/{page}` |
| `createDeepReviewAttempt` | `POST /deep-reviews/{deepReviewId}/attempts` |

모든 mutation은 공통 actor header helper를 사용한다.

- printable ASCII claimed name은 원문 그대로 `X-BidOps-Actor-Name`으로 보낸다.
- 비ASCII 이름은 UTF-8 bytes를 RFC 3986 uppercase percent로 만들고 값 앞에 `UTF-8''`를 붙이며
  `X-BidOps-Actor-Name-Format: utf-8-percent-v1`도 보낸다.
- trim은 서버의 claimed-name 의미를 바꾸지 않도록 전송 helper에서 하지 않는다. 화면은 빈 값
  여부만 `trim()`으로 검사한다.

`DeepReviewApiError`에는 HTTP `status`, nullable 구조화 `code`, 안전한 `message`를 보존한다.
Lean 오류 body가 아니거나 JSON이 아니면 일반 실패 문구를 사용한다. 네트워크 실패는 status 0이다.
기존 create/revision/final-opinion 함수도 같은 actor helper를 쓰게 하되 요청 body와 반환형은 바꾸지 않는다.

### 완료 기준

- 일곱 Lean API 호출 함수가 명시적 반환·payload 타입을 가진다.
- `any`, 추정 `structure_id`, 직접 작성한 multipart boundary가 없다.
- 기존 API 함수의 경로와 body가 유지된다.
- `npm run build`가 통과한다.

---

## T6 — 문서 준비 작업대와 공고 상세 연결

### T6-1 `web/frontend/src/components/deep-review/DocumentPreparationPanel.tsx` 신설

공고 하나의 단계 B를 소유하는 컴포넌트를 만든다. props는 최소한 `noticeId`, 화면에 표시된
grade, 심층 검토 생성 성공 callback을 받는다. 서버 정본을 TanStack Query로 읽고 mutation 뒤
`["document-bundles", noticeId]`를 무효화한다.

#### bundle 선택과 생성

- revision 내림차순으로 이력을 표시한다. ready/superseded는 읽기 전용임을 문자로 표시한다.
- 최신 non-ready bundle이 있으면 이어서 사용하고, 없으면 actor 이름과 `새 문서 bundle 만들기`
  버튼을 제공한다. ready 뒤 새 문서 버전을 준비할 수 있도록 별도 새 bundle 생성도 명시적으로
  제공하되 중복 클릭은 막는다.
- 화면 표시 grade가 `우선 검토`가 아니면 서버가 effective grade를 다시 확인하며 403으로
  거부한다는 설명을 먼저 보인다. 서버의 실제 gate를 우회하거나 다른 grade를 보내지 않는다.
- 403/`effective_grade_ineligible`는 “우선 검토 effective grade가 필요”하다고 표시한다.

#### 문서 등록

- 기존 `AttachmentPanel`의 키보드 가능한 dropzone 패턴을 재사용한다.
- `.hwp,.hwpx,.pdf`, 복수 선택, 파일당 50MiB 안내를 표시한다. 파일은 순차 등록하고 각 요청은
  독립 request ID를 쓴다. 한 파일 실패를 전체 성공으로 표시하지 않는다.
- 사용자 로컬 경로나 파일 내용을 화면 밖으로 보내지 않는다. 응답의 `original_filename`은
  사용자 확인용으로만 표시한다.
- safety/structure 상태를 각각 문자 badge로 보여 주고 blocked/failed/needs_review를 ready처럼
  표현하지 않는다.

#### 메타데이터와 구조 상태

- 각 문서는 역할 select, nullable 시행일, nullable 대체 문서 select, 현재 버전 checkbox를 가진다.
- 저장은 응답의 현재 document `version`을 보내고, 성공 뒤 bundle query를 다시 읽는다.
- `structure_status=ready`는 “구조화 완료”, pending/processing은 대기·진행, failed/needs_review는
  실패·사람 확인으로 구분한다. API가 structure ID를 주지 않으므로 ID나 page 수를 추정하지 않는다.

#### bundle 확정과 심층 검토 시작

- 확정 전 문서 1건 이상, 모든 문서 safety safe, structure ready, blocking issue 0건을 화면에서
  확인 가능하게 한다. 버튼 비활성 사유를 문자로 표시한다. 서버가 최종 정본 검사를 다시 한다.
- 확정 요청은 현재 bundle version과 현재 문서 전체의 ID/version snapshot을 보낸다.
- 확정이 ready가 되면 해당 bundle을 수정할 수 없음을 표시하고, actor 이름으로 심층 검토를
  시작할 수 있게 한다.
- 심층 검토 503/`service_unavailable`는 활성 profile version과 analysis policy version이 모두
  필요한 fail-closed 운영 상태라고 설명한다. 자동 fallback이나 다른 provider 호출을 만들지 않는다.
- 성공 시 callback으로 `/deep-reviews/{id}`로 이동한다.

모든 오류는 `role="alert"`, 진행 문구는 적절한 `role="status"`를 사용한다. 색만으로 상태를
전달하지 않는다.

### T6-2 `web/frontend/src/pages/NoticeDetailPage.tsx`

- 기존 ready bundle 전용 IIFE, 로컬 bundle query, createDeepReview mutation을 새 컴포넌트로
  교체한다.
- 공고 선택·회차 query·스크롤·상세 이력의 기존 동작은 바꾸지 않는다.
- 화면 grade는 참고 표시로만 넘긴다. 프런트가 `reviews`를 재계산해 effective grade 정본을
  만들지 않는다.

### T6-3 스타일

새 전용 CSS 파일 또는 기존 `review-workspace-relaxed.css`에 다음을 추가한다.

- 20~24px 카드 padding, 8px 간격 계층, 40~44px 조작부
- 좁은 pane에서 문서 metadata가 한 열로 접히고 전체 문서가 수평 viewport를 넘지 않음
- dropzone keyboard focus와 drag 상태가 보임
- blocking issue, 실패, 대기, ready를 문자와 함께 표시
- 그라데이션·유리 효과·장식 아이콘 없음

### 완료 기준

- ready bundle이 없는 공고에서도 브라우저로 bundle 생성부터 확정까지 수행할 수 있다.
- `우선 검토` gate, 안전/구조화/issue 차단, profile/policy 503이 성공으로 숨겨지지 않는다.
- ready bundle을 직접 수정하지 않으며 confirm payload가 화면 snapshot과 일치한다.
- `npm run build`가 통과한다.

---

## T7 — 실패 attempt 재시도와 진행 상태 갱신

### `web/frontend/src/pages/DeepReviewPage.tsx`

1. review query는 현재 review 또는 current attempt가 `queued|running`인 동안 제한된 간격으로
   다시 조회하고 terminal이면 polling을 멈춘다.
2. report query는 review가 완료되기 전의 409를 최종 오류처럼 고정하지 않는다. review 완료 후
   다시 조회하고, 완료 상태인데 실제 오류가 있으면 그대로 표시한다.
3. current attempt가 `failed`일 때만 claimed actor name과 `새 attempt로 재시도` 버튼을 표시한다.
   queued/running에는 중복 버튼을 두지 않는다.
4. 재시도 성공 시 review/report query를 무효화하고 새 attempt sequence/status를 보여 준다.
   실패한 기존 attempt를 수정·삭제·성공 처리하지 않는다.
5. `active_attempt_exists`, `review_not_ready`, 503 등 서버 오류의 안전한 code/message를 표시한다.
6. 재시도는 새 분석 attempt이며 최종 참여 결정이 아니라는 설명을 둔다.
7. 기존 report revision, evidence, validation 실패 acknowledge, final opinion append 흐름을 유지한다.

### 완료 기준

- 실패 attempt에서만 actor가 있는 재시도가 활성화된다.
- 클릭 한 번이 새 request ID의 attempt POST 한 번을 만들고 중복 클릭은 막힌다.
- 새 attempt가 기존 attempt 이력을 덮어쓰지 않고 화면에 함께 보인다.
- 진행 중 화면이 자동 갱신되고 terminal에서 polling이 멈춘다.
- `npm run build`가 통과한다.

---

## T8 — 브라우저 흐름 회귀 검증

### Playwright mock과 spec

`web/frontend/tests`의 기존 `mockApi` 패턴을 사용해 최소 다음을 자동 검증한다.

1. `우선 검토` 공고: draft 생성 → HWP/HWPX/PDF upload → 역할/시행일 patch → ready confirm →
   deep review 생성 → 해당 report route 이동. 각 method/path/body/header를 검사한다.
2. 비ASCII actor 이름이 `UTF-8''...` + format header로 전송되고 raw 한글 header를 보내지 않는다.
3. 403 `effective_grade_ineligible`가 gate 설명으로 남고 ready로 진행하지 않는다.
4. deep review 생성 503 `service_unavailable`가 활성 profile/policy 필요 상태로 표시된다.
5. failed attempt에서 retry POST 후 새 attempt가 표시되고, running attempt에서는 버튼이 비활성/부재다.
6. 좁은 viewport에서 document metadata와 issue 목록 때문에 document root width가 넘치지 않으며,
   dropzone과 mutation button에 키보드 focus가 가능하다.

고정 응답은 backend Pydantic 필드를 모두 갖게 하고, 성공을 위해 존재하지 않는 field를 만들지 않는다.
기존 광범위 visual snapshot은 의도와 무관하게 다시 쓰지 않는다.

### 완료 기준

- 대상 Playwright spec이 fake API만으로 통과한다.
- 테스트가 curl/CLI나 실제 vLLM/OpenAI/API key를 요구하지 않는다.
- `npm run build`와 대상 Playwright spec이 모두 통과한다.

