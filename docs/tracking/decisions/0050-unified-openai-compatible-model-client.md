# 모델 호출을 하나의 OpenAI 호환 client와 용도별 설정으로 통일한다

- 상태: 채택
- 일자: 2026-09-05

## 맥락

모델을 부르는 자리가 셋으로 갈려 있었다.

- **C-1 공고 판정**: `app/screening/`이 Ollama HTTP API(`/api/generate`·`/api/tags`)를 직접
  부르는 client를 갖고 `BIDOPS_OLLAMA_*` 일곱 개 설정을 읽었다.
- **심층 검토**: `app/core/vllm_client.py`가 승인된 사설 OpenAI 호환 vLLM을 부르고
  `BIDOPS_VLLM_*`를 읽었다. 모델명은 `BIDOPS_VLLM_MODEL` 한 개가 모든 용도를 덮었다.
- **C-2 발주계획 선별**: `app/screening/services/vllm_client.py`가 batch payload 전용
  어댑터를 따로 갖고 있었다.

이 상태의 문제는 세 가지다.

1. **같은 사내 vLLM 배치를 가리키는데 전송 경계가 두 벌이다.** 허용 host 검사, 응답 크기
   상한, redirect 금지, 재시도 규칙, redaction이 Ollama 경로와 vLLM 경로에 각각 있었고
   서로 조금씩 달랐다. 어느 쪽이 정본인지 문서에 적을 수 없었다.
2. **모델명이 전역 하나였다.** `BIDOPS_VLLM_MODEL`을 바꾸면 개요·심층·판정이 함께 바뀐다.
   용도별로 다른 서버나 다른 모델을 쓰는 배포를 표현할 방법이 없었다.
3. **선언 revision의 적용 범위가 C-2뿐이었다.** [ADR-0042](0042-c2-model-revision-declared-at-deployment.md)가
   "OpenAI 호환 vLLM은 weight revision을 노출하지 않으므로 배포가 선언한다"를 채택했는데,
   그 규칙이 C-2 어댑터에만 적용되고 개요·심층·판정에는 없었다.

Ollama 경로는 `qwen3.8:27b`라는 태그 형식 모델명과 `/api/tags`의 blob digest를 전제로
설계돼 있었고, 그 전제는 사내 배포가 vLLM으로 옮겨 가면서 더는 성립하지 않는다.

## 결정

C-1 공고 판정, 사전규격 개요 검토, 심층 검토가 부르는 모델 transport를 `app/core/model_client.py`
하나로 합치고, **무엇을 부를지는 용도별 설정과 policy가 정한다**.

### 1. `core`가 소유하는 것은 transport 경계뿐이다

`app/core/vllm_client.py`(범용)는 `app/core/model_client.py`로 이름이 바뀐다. 이전 경로는
공개 이름만 재수출하는 얇은 shim으로 남아 기존 호출부가 그대로 돌아간다. 새 코드는
`app.core.model_client`를 직접 import한다.

core는 응답 schema도 system prompt도 알지 못한다. 계약을 소유한 도메인 모듈이
`StructuredOutputContract`(이름·JSON schema·system prompt)로 넘기고 client는 그것을 provider
요청에 싣는다. **이 모듈에는 고정된 모델명이 없다.** 모델명을 코드에 박으면 배포가 모델을
바꿀 때 코드를 고쳐야 하고, 그 사이에 실행 row에 기록된 모델명과 실제로 부른 모델이 갈린다.

승인 경계는 한 벌이다. 호출당 timeout 300초, 최대 시도 2회, 응답 4 MiB 상한, 최대 completion
16,384 tokens, `seed=0`·`temperature=0.7`·`top_p=0.8`·`top_k=20`·non-thinking, redirect·환경
proxy·SDK 자동 재시도 금지, 경로·URL·비밀 문자열 redaction.

C-2 발주계획 어댑터(`app/screening/services/vllm_client.py`)는 이번 통일의 범위 밖이라 별도
transport로 남는다. 공통 상한만 core에서 가져온다. 따라서 "유일한 모델 transport"라는 문장은
**C-1·개요·심층에 한정해서** 읽는다.

### 2. 용도는 셋이고 각자 자기 설정을 가진다

용도(`purpose`)는 `screening`(C-1 공고 판정), `overview`(사전규격 개요), `deep_review`다.

| 설정 | 뜻 |
|---|---|
| `BIDOPS_VLLM_BASE_URL`·`_ALLOWED_HOSTS`·`_API_KEY`·`_MODEL_REVISION` | 모든 용도의 공유 기본값 |
| `BIDOPS_VLLM_{SCREENING\|OVERVIEW\|DEEP_REVIEW}_{BASE_URL\|ALLOWED_HOSTS\|API_KEY\|MODEL_REVISION}` | 그 용도의 override |
| `BIDOPS_VLLM_SCREENING_MODEL` | C-1이 부르는 모델 id (기본 `qwen3.8-27B`) |

**빈 override는 미선언이며 공유값으로 떨어진다.** 개요와 심층은 policy의 `model_name`을
쓰므로 모델명 설정 항목이 없다.

제거된 설정: `BIDOPS_VLLM_MODEL`(및 `settings.vllm_model`),
`BIDOPS_OLLAMA_{MODEL,BASE_URL,TIMEOUT_SECONDS,KEEP_ALIVE,CONTEXT_SIZE,MAX_OUTPUT_TOKENS,SYNTHESIS_MAX_OUTPUT_TOKENS}`,
`BIDOPS_LIVE_OLLAMA_TEST`.

이름이 바뀐 설정: `BIDOPS_OLLAMA_CONTEXT_SIZE` → `BIDOPS_SCREENING_CONTEXT_SIZE`,
`..._MAX_OUTPUT_TOKENS` → `BIDOPS_SCREENING_MAX_OUTPUT_TOKENS`,
`..._SYNTHESIS_MAX_OUTPUT_TOKENS` → `BIDOPS_SCREENING_SYNTHESIS_MAX_OUTPUT_TOKENS`.
`BIDOPS_SCREENING_PROVIDER`는 `vllm|mock`(기본 `vllm`)이다.

### 3. 용도별 fail closed는 네트워크 호출 **전에** 일어난다

`resolve_model_endpoint(purpose)`가 그 용도의 유효 허용 host가 비었거나 선언 revision이
64자 hex가 아니면 `ModelEndpointError`로 멈춘다. client를 만든 뒤에 검사하면 이미 주소를
열어 둔 상태가 되고, 기본값으로 hosted 주소가 새어 들어갈 자리가 생긴다.

한 용도의 fail closed가 다른 용도로 새지 않는다. 개요가 닫혀 있어도 심층은 자기 설정으로
판단한다.

### 4. 선언 revision을 세 용도 전부로 넓힌다

[ADR-0042](0042-c2-model-revision-declared-at-deployment.md)가 C-2에 대해 정한 규칙을 이
결정이 `screening`·`overview`·`deep_review`로 확장한다.

- 배포가 운영자 확인 64자 digest를 `BIDOPS_VLLM_MODEL_REVISION`(또는 용도별 override)으로
  선언한다. 비어 있으면 그 용도는 부르기 전에 fail closed한다.
- `GET {base_url}/models`의 served id에 설정·policy 모델명이 있어야 한다. 없으면
  `model_not_served`다.
- 응답이 `model_revision`(또는 `revision`)을 **실어 보내는 경우에만** 선언값과 대조한다.
  stock vLLM은 싣지 않으므로 부재는 실패가 아니다. 값이 있는데 다르면
  `model_revision_invalid`다.
- 서버에 물을 수 없거나 응답이 계약 밖이면 `identity_unavailable`이다.

새 오류 코드는 `model_not_served`, `model_revision_invalid`, `identity_unavailable` 셋이다.

### 5. 참조 실행 모드는 품질을 주장하지 않고 표식을 남긴다

승인된 모델 artifact와 사람 gold가 아직 없는 상태에서도 전체 흐름을 한 번 통과시켜 봐야
한다. 그렇다고 그 실행을 운영 완료로 집계하면 [ADR-0017](0017-human-enabled-quality-gate.md)의
"코드 완성과 운영 활성화 분리"가 무너진다. 그래서 **실행을 허용하되 결과에 표식을 붙인다.**

`BIDOPS_REFERENCE_WORKFLOW_MODE`(기본 `false`)가 참일 때만 다음이 열린다.

- `BIDOPS_ANALYSIS_PROVIDER=mock`과 `BIDOPS_SCREENING_PROVIDER=mock`. 참조 모드가 아니면
  설정 검증이 기동 전에 거부한다.
- 심층 검토 생성에서 policy의 `model_name` 대조를 건너뛴다. **`model_endpoint_ref` 검사는
  유지한다** — 승인된 OpenAI 호환 transport여야 한다는 조건은 어느 모드에서도 같다.
- 생성 감사의 `policy_quality`가 `{"status": "reference_workflow_unmeasured", "deployable": false}`다.

품질 표식 `quality_status`는 생성 감사에서 계산하며 순서가 규칙이다. mock provider면
`mock_reference`, 그 밖에 참조 모드였으면 `unmeasured_reference`, 측정값이 배치 가능하면
`measured`, **어느 것도 아니면 `null`(표식 없음)**이다. 표식이 없던 시절의 실행을 미측정이나
측정으로 승격시키지 않는다.

개요 검토 attempt의 표식은 `mock_reference|unmeasured_reference` 둘뿐이며 필수다. **품질을
아직 재지 않은 실제 모델 실행(`deployable=false`, `reference_only=false`)은 `completed`가 될
수 있고 mock(`reference_only=true`)은 될 수 없다** — DB CHECK
`ck_prespec_overview_attempt_completed_binding`이 그 경계다. `deployable=false`인 `completed`의
뜻은 "완료 불가"가 아니라 **"운영 완료로 집계하지 않음"**이다.

`quality_status=unmeasured_reference|mock_reference`인 결과는 운영 완료, 품질 근거, 정책
활성화 근거로 쓰지 않는다.

client는 생성 시점이 아니라 **실행 시점**(`run_claim`)에 `for_purpose`로 묶인다. 그래서 생성은
성공하고 설정 실패는 실행에서 fail closed로 난다.

운영 주의: `policy_quality` snapshot 모양이 이 변경으로 바뀌었으므로, **변경 전에 만들어져
아직 실행되지 않은 심층 검토는 pinned 입력 대조가 어긋나 503으로 닫힌다.** 새 attempt가
필요하다. `docs/tracking/findings.md`에 기록했다.

`analysis_provider`는 vLLM 경로에서 `vllm-openai-compatible`로 남는다. 저장된 감사 계약이라
서술로 쓰이는 "openai-compatible"이라는 표현 때문에 값을 바꾸지 않는다.

### 6. Ollama 생성 설정의 대응

C-1의 얼려 둔 `generation_config`는 이름과 digest가 계약에 묶여 있어 바꾸지 않는다.
OpenAI 호환 호출로의 대응은 다음과 같다.

| 얼린 이름 | OpenAI 호환 | 비고 |
|---|---|---|
| `num_predict`(stage별) | `max_tokens` | 그대로 대응 |
| `num_ctx` | 대응 없음 | binding 기록에만 남는다 |
| `think: false` | `extra_body.chat_template_kwargs.enable_thinking=false` | |
| `format` | `response_format` | strict JSON schema |
| `keep_alive` | 없음 | |
| `done_reason` | `finish_reason` | |
| `prompt_eval_count`·`eval_count` | `usage.*` | |
| `*_duration_ns` 네 열 | 없음 | **`null`로 남긴다.** client 측 경과 시간으로 채우면 과거 Ollama 계측과 뜻이 다른 숫자가 같은 열에 섞인다 |

새 실패 경로 `ResponseTooLargeError`는 `truncated_output`으로 분류한다.

### 7. C-1 모델명이 `qwen3.8-27B`가 된다

C-1이 부르는 모델 id가 Ollama 태그 `qwen3.8:27b`에서 vLLM served id `qwen3.8-27B`로 바뀐다.
그 결과 **이전 이름으로 기록된 기존 `ScreeningExecution`과 판정 row는 carry-over 검증,
재판정 검증, `queue.enqueue`에서 거부된다.** 이전 데이터를 이어 쓸지는 별도 판단이 필요하며
`docs/tracking/findings.md`에 기록했다. 이 결정은 자동 이관을 만들지 않는다 — 실행 binding을
사후에 고쳐 쓰는 것은 [ADR-0007](0007-immutable-runs.md)의 불변 회차 규칙에 어긋난다.

저장된 실패 사유 문자열 `ollama_unavailable`은 그대로 둔다. 이미 DB와 artifact에 기록된
계약값이라 이름만 남고 뜻은 "모델 endpoint를 쓸 수 없음"이다.

## 대안과 기각 이유

- **Ollama 경로를 그대로 두고 vLLM만 추가한다** — 전송 경계가 두 벌인 상태가 유지된다.
  감사·테스트 격리·정책 pinning의 확인 지점이 용도마다 달라 새 흐름이 어느 쪽을 따라야
  하는지 규칙이 서지 않는다.
- **모델명을 core 상수로 고정한다** — 배포가 모델을 바꿀 때 코드를 고쳐야 하고, 실행 row에
  기록된 모델명과 실제 호출이 갈릴 수 있다. policy와 용도별 설정이 정하는 편이 안전하다.
- **용도 구분 없이 endpoint 하나만 둔다** — 한 endpoint의 장애나 오설정이 세 업무를 한꺼번에
  닫는다. 또한 용도별 승인 범위를 방화벽·감사에서 구분할 수 없다.
- **선언 revision을 C-2에만 유지한다** — 같은 서버를 부르는 나머지 세 용도가 weight 신원
  없이 돈다. ADR-0042의 근거는 provider가 revision을 노출하지 않는다는 사실이고, 그 사실은
  용도와 무관하다.

## 결과

- `docs/ARCHITECTURE.md`·`web/backend/AGENTS.md`·`docs/backend-modules/design.md`의 모듈
  지도에서 core의 `vllm_client(범용)`는 `model_client`다.
  [ADR-0045](0045-backend-module-layout.md)가 적은 지도의 그 자리를 이 결정이 갱신한다.
- 저장소 문서에서 Ollama는 과거 결정·과거 실행 증거·해결된 findings 항목에만 남는다.
- C-1의 telemetry에서 서버 측 소요 시간 네 열은 `null`이다. 0으로 채우지 않는다.
- 운영 주의: 서버가 응답에 `model_revision`을 싣는 배포에서 선언값이 비어 있으면 그 용도는
  `resolve_model_endpoint` 단계에서 이미 멈춘다. 기본 vLLM은 싣지 않는다.
