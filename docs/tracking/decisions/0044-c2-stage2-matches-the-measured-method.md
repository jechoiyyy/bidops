# C-2 stage 2를 측정된 방법과 일치시킨다

- 상태: 채택
- 일자: 2026-09-03

## 맥락

2026-09-03 종단 실행(수집 1,040건 → 적재 → C-2 → 화면)에서 stage 2가 한 배치도 완료하지
못했다. 원인은 개별 버그가 아니라 구조였다.

이 저장소의 경계는 *"기존 파이프라인은 subprocess·버전 파일 계약으로 연결한다"*이다.
stage 1 BM25와 결과 병합은 `skills/bidops-screen/scripts/`를 subprocess로 부르지만
**stage 2 모델 호출만 백엔드가 `OrderPlanVllmAdapter`로 새로 구현했고, 그 구현은 실제
서버를 상대로 검증된 적이 없었다.** `web/Dockerfile`은 `skills/`만 COPY하므로
[ADR-0037](0037-order-plan-c2-bm25-top300-qwen.md)이 625건으로 측정한 실험 구현
(`experiments/order-plan-screening/scripts/methods.py`의 `QwenAdapter._score_batch`)은
런타임에 존재하지도 않는다.

그 결과 제품이 보내는 요청이 측정된 방법과 네 곳에서 어긋나 있었다.

| 항목 | 측정된 방법 | 당시 제품 |
|---|---|---|
| payload·출력 식별자 | `item_id`(batch 내 index), `company_capabilities` | `plan_id`(실제 발주계획 번호), `company` |
| `response_format` | `json_schema` + `strict`, 배치 크기까지 스키마로 고정 | `json_object` |
| `chat_template_kwargs` | 최상위 필드 | `extra_body`에 중첩 → vLLM이 무시 |
| generation 설정 | 승인 config를 읽어 조립 | 파일을 읽지 않고 하드코딩 |

승인 prompt(`order-plan-batch-relevance-v3-approved.txt`, binding이 digest로 고정)는
*"각 항목은 batch 안에서만 의미가 있는 item_id와 title을 가진다 … 각 결과에는 item_id,
relevance, score, reason 네 필드만 둔다"*로 계약한다. 제품은 `plan_id`를 요구했으므로
prompt를 따르는 모델의 응답은 전부 `schema_violation`이 됐다. `chat_template_kwargs`가
전달되지 않아 thinking이 켜진 채 8192 토큰을 소진한 것도 같은 뿌리다.

**generation config는 저장소에 없었다.** binding이 못 박은
`generation_config_sha256 = 1fd2f511…`은 `prepare_vllm_qwen_config.py`가 실험 시점
메모리에 만든 `methods.json["methods"]["qwen"]` 객체의 canonical-JSON digest이고 커밋된
적이 없다. worker는 읽을 것이 없어 digest 문자열만 대조했고, 계보에 적힌 설정과 실제로
나간 설정이 달랐다.

## 결정

**stage 2가 보내는 요청을 측정된 방법과 같게 만들고, 계보에 적힌 설정이 실제로 나가게 한다.**

1. **승인 generation config를 아티팩트로 복원한다.** 커밋된 `methods.json`의 `qwen`
   블록에 `prepare_vllm_qwen_config.py`의 v4 필드를 덮은 객체의 digest가
   `1fd2f511…`과 **정확히 일치**함을 확인하고
   `config/order-plan-screening-generation-config.v4.json`에 canonical JSON 바이트로
   기록했다. `sha256_file == digest_json`이므로 기존 digest 경로로 검증된다.
   `think: "high"`는 `update()`가 덮지 않아 남은 값이며 digest에 포함되므로 보존한다.
2. **generation config를 승인 입력으로 승격한다.** `_approved_inputs`가 prompt·
   capabilities와 똑같이 파일로 읽고 digest를 대조하며, execution 디렉터리에
   `generation-config.json`으로 복사된다. worker가 그 파일에서 `max_output_tokens`,
   `timeout_seconds`, `chat_template_kwargs`를 읽어 adapter에 넘긴다. 하드코딩은 없앤다.
3. **모델 payload 식별자를 승인 prompt에 맞춘다.** 모델은 batch-local `item_id`와
   `title`, 그리고 `{profile_version, capabilities}` 형태의 `company_capabilities`만
   받는다. 실제 발주계획 번호는 경계를 넘지 않으며, worker가 batch 위치로 되돌린다.
   `screening-decisions.json`과 DB는 그대로 `plan_id`를 쓴다.
4. **응답을 strict `json_schema`로 제약한다.** 배치 크기를 스키마에 고정해 짧거나 긴
   배치, 이름이 바뀐 필드가 애초에 생성되지 않게 한다.
5. **binding·policy v2를 만든다.** v1은 immutable이므로
   ([ADR-0038](0038-order-plan-c2-phase0-contracts.md)) 새 버전을 추가한다.
   `payload_fields`는 `["title"]`, `company_payload_fields`는
   `["profile_version","capabilities"]`, `forbidden_fields`에 `plan_id`를 더한다.
   키 집합은 v1과 동일하게 두어 contract schema와 contract index digest를 건드리지 않는다.
6. **적합성 테스트를 둔다.** 같은 입력에 대해 adapter가 만든 요청 body가 측정된
   `_score_batch`의 body와 같은지 단언한다. 기존 테스트는 오히려 잘못된 모양
   (`extra_body` 중첩)을 고정하고 있어서 이 네 건이 전부 통과하고 있었다.

## 대안과 기각 이유

- **prompt를 `plan_id`로 고친다.** binding·코드를 안 건드려도 되지만 prompt digest가
  바뀌어 ADR-0037이 그 prompt로 측정한 625건 gold 채점 근거가 무효가 된다. 기각.
- **stage 2를 subprocess 스크립트로 내린다.** CLAUDE.md 경계와 가장 일치하지만 raw 응답
  바이트를 파일로 넘겨 암호화 저장하는 경로와 실패 코드 전달 계약을 새로 설계해야 하고,
  worker의 attempt·heartbeat·중지 수명주기를 쪼개야 한다. 이번 범위에서는 기각하고
  적합성 테스트로 두 구현의 드리프트를 막는다.
- **`system_fingerprint`를 weight 신원으로 쓴다.** 빌드·병렬도 지문이라 기각
  ([ADR-0042](0042-c2-model-revision-declared-at-deployment.md)).

## 결과

- 2026-08-31~09-02 발주계획 1,040건 회차로 재실행해 **300/300 완료, 실패 0건**
  (관련 57 / 비관련 144 / 불확실 99)으로 끝났다. stage 1은 선정 300 / 탈락 740으로
  변경 전과 같다. 배치당 약 48초로 줄었다(thinking을 실제로 끈 결과, 이전 약 224초).
- 이 실행은 **품질 근거가 아니다.** activation blocker 4건은 그대로이고 정책은
  테스트 전용 사본으로만 활성화했다.
- 외부 모델에 보내는 정보가 줄었다. 승인된 payload 허용 목록을 이에 맞춰 좁힌다
  (모델 전송 정책은 ADR-0050 완화 항목 참조).
- 남은 것은 `experiments/`와 `web/backend/`에 BM25와 Qwen 요청 조립이 각각 존재한다는
  점이다. 적합성 테스트가 드리프트를 잡지만 구현이 하나가 된 것은 아니다.
