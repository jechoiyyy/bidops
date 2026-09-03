# C-2 모델 revision은 배포 시점 선언으로 1회 대조한다

- 상태: 채택
- 일자: 2026-09-03

## 맥락

C-2 stage 2는 승인 사설 vLLM `qwen3.8-27B`를 호출한다.
[ADR-0038](0038-order-plan-c2-phase0-contracts.md)이 고정한 binding은 weight 신원을
`stage2_binding.model_digest`(`6ae70ca3…`)로 못 박고, 제품 adapter는 그 값을
**매 chat completion 응답 본문의 `model_revision`과 대조**하도록 구현돼 있었다.

2026-09-03 종단 실행에서 이 검증이 한 배치도 통과하지 못한다는 것이 실측으로 확인됐다.

- 승인 endpoint `http://192.168.0.139:58765/v1`의 chat completion 응답 최상위 key는
  `choices, created, id, kv_transfer_params, model, object, prompt_logprobs, prompt_text,
  prompt_token_ids, service_tier, system_fingerprint, usage`뿐이며
  `model_revision`도 `revision`도 없다.
- `/v1/models` 역시 `id`, `root`, `created`, `max_model_len`, `permission`만 준다.
  **OpenAI 호환 vLLM에는 weight revision을 노출하는 면이 없다.**
- 발주계획 1,040건 회차로 실행했을 때 stage 1 BM25는 300 선정 / 740 탈락으로 정상
  완주했고, stage 2는 batch 1·2가 각각 약 224초 생성 뒤
  `model_mismatch / model_revision_invalid`로 거부됐다.

`system_fingerprint`(`vllm-0.24.0-tp2-8477a424`)가 응답에 있지만 이것은 vLLM 빌드와
병렬도의 지문이다. 서버 재기동·버전업·tp 변경으로 바뀌고, 같은 서버에서 weight만
교체해도 그대로일 수 있으므로 weight 신원으로 쓸 수 없다.

한편 C-2 방식을 선택한 [ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md)의 625건 실험은
같은 서버에서 문제없이 완주했다. 실험 adapter
(`experiments/order-plan-screening/scripts/methods.py`의 `QwenAdapter.verify_model_revision`)가
**실행 시작 시 1회, 환경변수 `BIDOPS_QWEN_MODEL_REVISION`과 config의 `model_revision`을
대조**했기 때문이다. 서버에 묻지 않는 검증이었다. 같은 함수의 Ollama 분기는
`/api/tags`의 `digest`를 실제로 읽는데, 이는 Ollama가 그 값을 노출하기 때문이다.

즉 제품은 서버가 충족할 수 없는 수준으로 요구를 올린 상태였고, 그 사실이 확인되지 않은
채 남아 있었다.

## 결정

C-2 stage 2의 model revision 검증을 **배포 시점 1회 선언 대조**로 되돌린다.
사내망 내부 제품이고 대상이 사내 GPU 서버라는 전제에서 사람이 내린 결정이다.

1. 배포는 운영자가 확인한 64자 digest를 `BIDOPS_VLLM_MODEL_REVISION`으로 선언한다.
2. `OrderPlanVllmAdapter`는 **생성 시점에** 그 값이 64자 hex이고 binding의
   `stage2_binding.model_digest`와 같은지 확인한다. 비어 있거나 다르면 payload를
   한 건도 보내기 전에 `binding_mismatch`로 execution 전체가 실패한다.
3. 응답의 `model_revision`은 **있으면 대조하고 없으면 통과**시킨다. 표준 vLLM은
   싣지 않으므로 부재는 실패가 아니다. 승인된 proxy나 다른 서버가 나중에 그 값을
   싣게 되면 추가 코드 없이 더 강한 보증이 살아난다.
4. 응답의 `model` 필드가 `qwen3.8-27B`인지 확인하는 검사는 그대로 둔다. 이것은
   서버가 실제로 말해 주는 값이다.
5. 저장되는 `ScreeningAttempt.model_digest`와 실행 계보의 의미는 바뀌지 않는다.
   다만 그 값의 근거가 "응답이 증명한 값"이 아니라 "배포가 선언한 값"임을 명시한다.

## 대안과 기각 이유

- **응답에 digest를 주입하는 승인 proxy를 둔다.** 매 응답 검증이라는 성질이 유지되고
  실행 중 weight 교체까지 잡힌다. 다만 proxy도 digest를 증명하지 않고 주장하며,
  운영 주체·배치·방화벽 경로가 새로 생긴다. 내부 GPU 서버 한 대를 쓰는 현재 규모에서
  얻는 것보다 비용이 크다고 판단했다. 필요해지면 endpoint만 바꿔 채택할 수 있도록
  위 3번을 남겨 두었다.
- **`system_fingerprint`를 revision으로 받아들인다.** weight 신원이 아니므로 기각했다.
- **검증을 제거한다.** 기각했다. 선언과 binding이 어긋난 배포는 여전히 막아야 한다.

## 결과

- 확인된 사실은 그대로 남는다. **서버는 여전히 자기 weight revision을 말하지 못하며,
  이 선언이 실제 적재된 weight와 일치하는지는 사람의 확인에 달려 있다.**
- 이 저장소에는 digest 계산 방법이 기록돼 있지 않다. 런북은 "서버 운영자가 제공한
  64자 model artifact digest"라고만 한다. 다음에 "지금 서버의 digest가 여전히 이
  값인가"를 스스로 확인하려면 계산 방법을 운영자에게 받아 문서로 고정해야 한다.
  이 공백은 `findings.md`에 남긴다.
- 모델 weight가 바뀌면 `BIDOPS_VLLM_MODEL_REVISION`만 고치는 것으로 끝내지 않는다.
  binding을 새 버전으로 올리고 품질 게이트를 다시 측정한다. 판정 근거가 달라졌기
  때문이다. 서버 재기동·버전업만으로는 이 값이 바뀌지 않는다.
- 외부 hosted 모델로의 자동 전환 금지, 건별 승인, BM25 탈락 보존 등
  [ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md)·[ADR-0038](0038-order-plan-c2-phase0-contracts.md)의
  다른 경계는 그대로다.
