# 발주계획 선별 `interim-v4` 실행 및 Qwen 잘림 분석

검증일: 2026-08-28 (KST)  
실행 ID: `20260824-20260826-interim-v4`  
분석 방식: 저장된 불변 산출물을 이용한 read-only 사후 분석. 분석 중 모델을 다시 호출하거나 기존 산출물을 수정하지 않았다.

## 결론

- 동결한 발주계획 997건에서 TF-IDF와 BGE-M3 dense는 각각 997건 전체를 처리했다.
- Qwen은 997건 중 747건을 처리했고 250건은 실패해 실행 상태가 `partial_failure`다.
- Qwen 실패는 40개 고정 배치 중 10개에서 발생했으며 오류 코드는 모두 `truncated_output`이다. 배치 하나가 실패하면 그 배치의 25건 전체를 실패로 보존하므로 `10 batch × 25건 = 250건`이 됐다.
- 직접 원인은 Ollama 응답의 `done_reason=length`다. 현재 adapter는 이 값을 `truncated_output`으로 분류한다. timeout, HTTP 장애, JSON parse 실패와는 별도 오류 경로다.
- 가장 유력한 병목은 25건의 구조화 결과와 thinking을 생성하는 요청에 적용된 `num_predict=4096` 생성 한도다. 다만 실패 응답의 token usage와 thinking/content 길이를 저장하지 않아, thinking과 최종 JSON 중 어느 쪽이 한도를 얼마나 소비했는지는 이 산출물만으로 확정할 수 없다.
- 이 결과는 모델 품질 승인이나 운영 정책 활성화 근거가 아니다. 사람 정답이 없으므로 recall·precision·중요 누락은 아직 측정하지 않았다.

## 실행 범위와 고정 binding

| 항목 | 값 |
|---|---|
| 조회 구간 | 2026-08-24 00:00:00 이상, 2026-08-27 00:00:00 미만 (KST) |
| 모집단 | 일반용역·기술용역 997건, 사전 필터 없음 |
| 모델에 허용한 계획 필드 | `title`만 허용 |
| 회사 역량 projection SHA-256 | `2ee0ebdd126341a6a79997341ebb93a76b00d5477d65ee21f635a41ecef2a57a` |
| 선택 범위 | 방식별 Top 50 |
| Qwen | `qwen3.8:27b` |
| Qwen model digest | `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` |
| prompt | `order-plan-batch-relevance-v2` |
| prompt SHA-256 | `593e3fdb97d1c4bf325d831eea7494908e4510e0cee999e349db224a2b5cf4d1` |
| Qwen batch | 25건 × 40개 고정 배치 |
| Qwen 요청 설정 | `stream=false`, strict JSON schema, `temperature=0`, `think="high"`, `num_predict=4096` |
| 요청 timeout | 120초 |

Qwen 출력 계약은 각 입력에 대해 `item_id`, `relevance`, `score`, `reason`을 반환하며, `reason`은 1자 이상 500자 이하인 한국어 한 문장이다. 입력 25건의 ID를 누락·중복·추가하지 않고 입력 순서대로 반환해야 한다.

## 방식별 실행 결과

| 방식 | 상태 | 성공 / 모집단 | 실패 | 배치 | 총 소요시간 | 평균 지연 |
|---|---|---:|---:|---|---:|---:|
| TF-IDF | `success` | 997 / 997 | 0 | 해당 없음 | 259ms | 0.249ms/건 |
| BGE-M3 dense | `success` | 997 / 997 | 0 | 128건 × 8 | 22.029초 | 21.305ms/건 |
| Qwen | `partial_failure` | 747 / 997 | 250 | 25건 × 40 | 3,517.903초 (약 58분 38초) | 3,528.430ms/건 |

TF-IDF와 dense의 전체 처리 성공은 기술적 coverage만 뜻한다. 사람 정답을 이용한 선별 품질 비교는 아직 수행하지 않았다.

## `truncated_output` 관측

실패한 배치 번호는 다음과 같다.

```text
4, 5, 13, 15, 17, 20, 29, 34, 36, 38
```

| 관측값 | 성공 배치 30개 | 실패 배치 10개 |
|---|---:|---:|
| 배치 latency 범위 | 74.034–106.021초 | 69.386–85.953초 |
| 배치 latency 중앙값 | 90.958초 | 75.325초 |
| 입력 token 범위 | 3,890–5,941 | 미기록 |
| 출력 token 범위 | 1,551–1,962 | 미기록 |
| 배치 내 title 총 문자 수 범위 | 634–893자 | 690–884자 |
| 배치 내 title 총 문자 수 중앙값 | 759자 | 798.5자 |
| 가장 긴 단일 title | 78자 | 75자 |

실패 배치의 title이 평균적으로 조금 길기는 하지만 범위가 크게 겹친다. 가장 긴 title 합계와 가장 긴 단일 title은 성공 배치 쪽이 더 컸다. 따라서 title 문자 수만으로 성공과 실패가 갈렸다고 볼 수 없다.

사후 분석 중 Ollama `/api/ps`에서 확인한 해당 모델의 context length는 262,144였고, 성공 배치의 입력은 최대 5,941token이었다. 실패 배치의 title 길이도 성공 배치와 비슷하므로 context 소진보다는 명시적인 4,096 생성 한도가 더 가까운 제한이다.

성공 배치의 최종 출력은 최대 1,962token이었고 3,800token 이상인 성공 배치는 없었다. 실패 배치에서만 더 긴 reasoning 경로 또는 구조화 출력 생성이 발생해 generation budget을 소진했을 가능성이 높다. `temperature=0`이어도 입력 내용에 따라 reasoning과 출력 길이는 달라질 수 있다.

## 오류 분류로 배제할 수 있는 원인

| 후보 원인 | 판단 | 근거 |
|---|---|---|
| 120초 요청 timeout | 주원인 아님 | timeout은 adapter에서 `timeout`으로 별도 분류하며 실패 배치도 모두 120초 전에 끝났다. |
| HTTP 오류 또는 endpoint 단절 | 주원인 아님 | HTTP 오류는 `model_http_*`, 연결 장애는 `model_unavailable`로 별도 분류한다. |
| JSON parse 또는 응답 구조 오류 | 기록된 직접 원인 아님 | parse·key 오류는 `malformed_response` 경로지만 이번 실패는 모두 그 전에 확인한 `done_reason=length`다. |
| 입력 title 길이 | 단독 원인 아님 | 성공·실패 배치의 문자 수 범위가 겹치며 더 긴 성공 배치가 존재한다. |
| 모델 context 소진 | 가능성 낮음 | 관측 입력 크기는 사후 확인한 context length보다 매우 작고, 별도의 4,096 생성 한도가 존재한다. |
| 생성 길이 제한 | 확인됨 | Ollama가 실패한 요청에서 `done_reason=length`를 반환했다. |

## 현재 산출물의 관측 한계

Ollama native adapter는 `done_reason=length`를 확인한 즉시 `AdapterFailure("truncated_output")`를 발생시킨다. 그래서 실패 응답에서 다음 값을 추출하기 전에 batch failure로 전환된다.

- `prompt_eval_count`
- `eval_count`
- `message.thinking` 길이
- 미완성 `message.content` 길이
- thinking과 최종 JSON이 generation budget에서 차지한 비율

실패 행의 input/output token 값은 실제 0token이라는 뜻이 아니라 **미기록**이다. 응답 본문을 일반 로그나 보고서에 보존하지 않은 보안 경계는 유지해야 하지만, 본문 없이 안전한 count와 종료 메타데이터를 기록할 수 있어야 정확한 병목을 분해할 수 있다.

또한 `think="high"`가 이 Qwen model artifact에서 어떤 강도로 해석되는지 별도 확인이 필요하다. 현재 요청이 수락됐다는 사실만으로 해당 값의 정확한 모델별 의미까지 확정하지 않는다.

## 후속 검증 결정

현재 Qwen 결과는 재실행으로 덮어쓰지 않고 `partial_failure` 증거로 보존한다. 다음 실행은 새 run ID를 사용하고 동일한 실패 batch를 고정한 뒤 한 번에 변수 하나만 바꾼다.

1. 실패 응답 본문 없이 `done_reason`, `prompt_eval_count`, `eval_count`, total/eval duration, thinking/content 문자 수만 기록한다.
2. 기존 조건인 batch 25, `num_predict=4096`, 현재 thinking 설정으로 최소 실패 배치를 재현한다.
3. batch만 10으로 줄여 coverage와 latency를 비교한다.
4. 별도 실행에서 batch 25를 유지하고 `num_predict`만 8,192로 늘린다.
5. 해당 Qwen artifact가 공식적으로 지원하는 설정을 확인한 뒤 별도 실행에서 thinking만 변경한다.
6. 각 실행에서 `done_reason=stop`, strict schema 검증, 모집단 coverage, 배치별 latency/token을 함께 판정한다.

운영 후보를 고를 때는 단일 batch의 잘림을 먼저 제거해야 한다. 이후 동일한 사람 정답으로 recall, precision, 중요 누락, 사람 검토량, 총 지연과 자원 사용량을 비교한다. TF-IDF 또는 dense로 후보를 줄이는 단계화는 전체 Qwen 호출량을 줄일 수 있지만, Qwen 단일 batch 잘림 자체를 해결한 것으로 간주하지 않는다.

## 보존 증거

| artifact | SHA-256 |
|---|---|
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/run.json` | `5c647561338c05fd214339e88b2a76ba483b6585cc49d04e5458ade6ea1a30b0` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/population.json` | `6e8d5f275ac45c3cbc59cb7c543f7945c8851f6dba720ae8f14bd4259b2cc1d6` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/results/tfidf.json` | `70186e9153de669bb093c0d192b1350cb20494bac4c50d88d1a9ef68882b6baa` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/results/bge_m3_dense.json` | `332f7e4e5ccebfb8c887a6df15fdc60511e6990b1b58ca31d1735a19412ec22a` |
| `data/experiments/order-plan-screening/20260824-20260826-interim-v4/results/qwen.json` | `1c48cda8e60d708769264d0b94d607e932421845003fcb7a4fe5539935f859ef` |
| `reports/order-plan-screening/20260824-20260826-interim-v4/report.html` | `a76cc7cd5a8ea69b37ea67422a9c9463d78558b56c0f6e835fc1b271512afb40` |
| `reports/order-plan-screening/20260824-20260826-interim-v4/decision-report.html` | `c591ba134440f4f15aeea5d12c7e6b5208744de57a0a42dccdf5846eee30ddf0` |
| approved prompt | `593e3fdb97d1c4bf325d831eea7494908e4510e0cee999e349db224a2b5cf4d1` |

배치 통계는 `population.json`과 `results/qwen.json`의 동일한 정렬을 `plan_id`로 확인한 뒤 앞에서부터 25건씩 나눠 계산했다. latency와 성공 batch token은 각 행에 분배해 저장된 값을 batch별로 다시 합산했다. 실패 batch의 token은 값이 없으므로 0으로 보정하지 않고 `미기록`으로 해석했다.
